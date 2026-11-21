#pragma once
// ============================================================================
//  Eight Ball DSP engine. Plain C++ (no JUCE, no allocation after prepare(),
//  no locks); the same source compiles to WebAssembly for the HTML build.
//
//  Per voice, per sample:
//    8 operators in index order. Each reads its phase modulation input from
//    the 8x8 PM grid (cells from a lower-numbered operator use this sample's
//    output, cells from a higher-numbered one and self-feedback use the last
//    sample's; feedback averages the last two, DX-style), looks up its
//    band-limited mipmapped wavetable (unison 1-8 sub-oscillators with detune
//    and stereo spread), applies level x velocity x amp envelope, then the
//    ring-mod grid. Its output goes through the output column to Filter 1,
//    Filter 2, Filter 3 and/or Dry. The three multimode filters (TPT SVF,
//    12/24 dB) are per voice and run Parallel, Series or 1+2 > 3.
//  Global: voice sum -> FX chain (dsp/Effects.h) -> master (smoothed) -> safety clip.
//
//  Control rate: every kChunk (32) samples the envelopes, pitches, levels,
//  pans, sends, grid depths and filter coefficients are recomputed; every one
//  of them is ramped linearly per sample in between. Parameters themselves
//  are smoothed (about 5 ms) in their normalised domain, so no knob steps.
//  2x oversampling (a toggle) runs the whole voice path at twice the rate and
//  decimates the voice sum with a polyphase half-band filter.
//
//  Modulation (the 16-slot mod matrix) adds to a parameter's normalised value:
//  offset = source x amount, clamped to 0..1, then mapped like the knob. The
//  four LFOs are global oscillators (free-running or locked to the song
//  position when synced); each voice fades an LFO in over its Delay time.
//  Sources that differ per voice (envelopes, velocity, key, the LFOs with
//  their fade) are applied per voice to the operator, grid and filter
//  parameters; the wheel, aftertouch and bend to everything else as well.
// ============================================================================
#include <limits>
#include "dsp/Common.h"
#include "dsp/ParamTable.h"
#include "dsp/Wavetable.h"
#include "dsp/Envelope.h"
#include "dsp/Model.h"
#include "dsp/Effects.h"

namespace eightball
{
constexpr int kMaxVoices = 32;
constexpr int kMaxUnison = 8;
constexpr int kMaxCells  = kNumOps * kNumOps;
constexpr double kMaxPmTurns = 2.0;           // PM grid depth 1.0 = 2 turns (4 pi rad) of phase at modulator level 1
constexpr double kFltEnvOctaves = 5.0;        // filter env amount 1.0 = 5 octaves
constexpr double kFltVelOctaves = 2.0;        // filter velocity 1.0 = 2 octaves across the velocity range
constexpr double kVoiceGain = 0.35;           // per-voice headroom

struct OpState
{
    std::array<double, kMaxUnison> phase {};
    double out = 0, prev = 0, prev2 = 0;
    void reset (double p) { phase.fill (p); out = prev = prev2 = 0; }
};

// Ramped per-sample targets of one operator
struct OpCtl
{
    std::array<double, kMaxUnison> dt {}, panL {}, panR {};
    double gain = 0, modScale = 1;
    std::array<double, kNumOutputs> send {};
};

struct FilterCtl { double g = 0.1, k = 2, drive = 0, mix = 1, level = 1; };

struct VoiceCtl
{
    std::array<OpCtl, kNumOps> op;
    std::array<FilterCtl, kNumFilters> flt;
    std::array<double, kMaxCells> pm {}, rm {};   // depth per cell (index src * 8 + dst)
};

struct FilterState
{
    std::array<SVF, 4> svf;   // [channel * 2 + stage]
    bool quiet = true;        // nothing has reached this filter since its last reset
    void reset() { for (auto& s : svf) s.reset(); quiet = true; }
};

struct Voice
{
    std::array<OpState, kNumOps> op;
    std::array<EnvState, kNumEnvs> env;
    std::array<FilterState, kNumFilters> flt;
    std::array<int, kNumOps> mip {};        // wavetable level per op (per chunk)
    int note = -1;
    int velocity = 0;
    double velN = 0;
    uint64_t age = 0;
    double timeOn = 0;                      // seconds since the note started (LFO delay)
    bool held = false, sustained = false, alive = false;
    double pitch = 60, glideFrom = 60, glideTo = 60, glidePos = 1;
    VoiceCtl cur;
    bool snap = true;
    // per-voice modulated parameter values (mod matrix), valid for this chunk
    std::array<int, kNumModSlots> ovParam {};
    std::array<double, kNumModSlots> ovVal {};
    int numOv = 0;

    bool active() const { return alive; }
};

struct LfoState
{
    double phase = 0;      // cycles (unbounded)
    double hold = 0;       // sample & hold value
    long long cycle = -1;  // which cycle the hold belongs to
    double value = 0;      // this chunk's output, -1..1 (depth applied)
};

// One active mod slot, resolved once per chunk
struct ModSlot
{
    int dst = -1;          // parameter index
    int src = srcNone;
    double amt = 0;
    bool perVoice = false; // the destination is an operator / grid / filter parameter
};

class SynthEngine
{
public:
    SynthEngine()
    {
        const auto& t = paramTable();
        for (int i = 0; i < kNumParams; ++i)
        {
            const auto& d = t[(size_t) i];
            plog[(size_t) i] = d.log;
            psmooth[(size_t) i] = d.kind == Kind::Float;
            raw[(size_t) i] = std::numeric_limits<float>::quiet_NaN();   // so the first value always applies
            val[(size_t) i] = base[(size_t) i] = d.def;
            targetNorm[(size_t) i] = normCur[(size_t) i] = paramToNorm (d, d.def);
        }
        model = &defaultModel;
    }

    void prepare (double sampleRate)
    {
        sr = sampleRate;
        masterSmooth = smoothCoef (0.02, sr);
        paramSmooth = smoothCoef (0.005, sr / kChunk);
        for (int w = 0; w < 5; ++w) (void) starterTable (w);   // build the starter tables now, not on the audio thread
        rng.seed (0x2545F491u);
        for (auto& v : voices) v = Voice {};
        for (auto& l : lfo) l = LfoState {};
        hbL.reset(); hbR.reset();
        fx.prepare (sr);
        masterGain = val[master];
        panic();
    }

    // All parameter values, once per block (indexed by ParamIndex).
    void setParamValues (const float* values)
    {
        const auto& t = paramTable();
        for (int i = 0; i < kNumParams; ++i)
        {
            const float v = values[i];
            if (v == raw[(size_t) i]) continue;
            raw[(size_t) i] = v;
            if (psmooth[(size_t) i]) targetNorm[(size_t) i] = paramToNorm (t[(size_t) i], v);
            else { val[(size_t) i] = base[(size_t) i] = v; normCur[(size_t) i] = targetNorm[(size_t) i] = paramToNorm (t[(size_t) i], v); }
        }
    }
    // Snap every smoothed parameter to its target (preset load, tests)
    void settleParams()
    {
        const auto& t = paramTable();
        for (int i = 0; i < kNumParams; ++i)
            if (psmooth[(size_t) i]) { normCur[(size_t) i] = targetNorm[(size_t) i]; val[(size_t) i] = base[(size_t) i] = paramFromNorm (t[(size_t) i], normCur[(size_t) i]); }
        updateActiveOps();
    }

    // The model (wavetables, envelopes, LFO shapes). The pointer must stay valid until the next call.
    void setModel (const Model* m) { model = m != nullptr ? m : &defaultModel; }
    const Model& currentModel() const { return *model; }

    // Called once per host block, before render(): tempo and song position (synced LFOs lock to it while playing)
    void setTransport (double bpmIn, double ppqIn, bool playingIn)
    {
        bpm = bpmIn > 0 ? bpmIn : 120.0;
        ppqAtBlock = ppqIn;
        playing = playingIn;
        blockPos = 0;
    }

    //==========================================================================
    void noteOn (int note, int vel)
    {
        if (vel <= 0) { noteOff (note); return; }
        const int heldBefore = keyCount;
        pushKey (note);
        const int mode = (int) val[voiceMode];
        const bool porta = val[portaOn] >= 0.5;
        const int maxVoices = clampi ((int) val[poly], 1, kMaxVoices);

        if (mode == modePoly)
        {
            Voice* v = nullptr;
            for (int i = 0; i < maxVoices; ++i) if (voices[(size_t) i].active() && voices[(size_t) i].note == note) { v = &voices[(size_t) i]; break; }
            if (v == nullptr) for (int i = 0; i < maxVoices; ++i) if (! voices[(size_t) i].active()) { v = &voices[(size_t) i]; break; }
            if (v == nullptr)   // steal: released first, then oldest
            {
                for (int i = 0; i < maxVoices; ++i)
                {
                    auto& x = voices[(size_t) i];
                    if (v == nullptr) { v = &x; continue; }
                    const bool xr = ! x.held && ! x.sustained, vr = ! v->held && ! v->sustained;
                    if ((xr && ! vr) || (xr == vr && x.age < v->age)) v = &x;
                }
            }
            startVoice (*v, note, vel, porta && lastNote >= 0 ? lastPitch : (double) note);
        }
        else
        {
            Voice& v = voices[0];
            const bool overlapping = heldBefore > 0 && v.active() && v.held;
            if (mode == modeLegato && overlapping)
            {
                setVoicePitch (v, note, porta);
                v.note = note;
                v.velocity = vel;
            }
            else
                startVoice (v, note, vel, porta && lastNote >= 0 ? (v.active() ? v.pitch : lastPitch) : (double) note);
        }
        lastNote = note;
        lastPitch = note;
    }

    void noteOff (int note)
    {
        removeKey (note);
        const bool mono = (int) val[voiceMode] != modePoly;
        for (int i = mono ? 1 : 0; i < kMaxVoices; ++i)
        {
            auto& v = voices[(size_t) i];
            if (v.note == note && v.held && v.active())
            {
                if (sustainPedal) { v.held = false; v.sustained = true; }
                else release (v);
            }
        }
        if (! mono) return;
        Voice& v = voices[0];
        if (! (v.active() && v.held && v.note == note)) return;
        if (keyCount > 0)
        {
            const int back = keys[(size_t) (keyCount - 1)];
            setVoicePitch (v, back, val[portaOn] >= 0.5);
            v.note = back;
            lastNote = back;
            lastPitch = back;
        }
        else if (sustainPedal) { v.held = false; v.sustained = true; }
        else release (v);
    }

    void setSustain (bool on)
    {
        sustainPedal = on;
        if (! on) for (auto& v : voices) if (v.sustained) release (v);
    }
    void setPitchBend (double v)  { bend = clampd (v, -1.0, 1.0); }
    void setModWheel (double v)   { wheel = clampd (v, 0.0, 1.0); }
    void setAftertouch (double v) { aftertouch = clampd (v, 0.0, 1.0); }

    void allNotesOff()
    {
        sustainPedal = false;
        keyCount = 0;
        for (auto& v : voices) if (v.active()) release (v);
    }

    void panic()
    {
        sustainPedal = false;
        keyCount = 0;
        for (auto& v : voices)
        {
            for (auto& e : v.env) e.kill();
            for (auto& f : v.flt) f.reset();
            v.held = v.sustained = v.alive = false;
        }
        fx.reset();   // delay and reverb tails too
    }

    // Writes (does not add) numSamples into L and R (R may be null: mono sums).
    void render (float* L, float* R, int numSamples)
    {
        const bool os = val[oversample] >= 0.5;
        if (os != lastOs) { lastOs = os; hbL.reset(); hbR.reset(); }
        int pos = 0;
        while (pos < numSamples)
        {
            const int n = std::min (kChunk, numSamples - pos);
            smoothParams();
            updateLfos (n / sr);
            updateModSlots();
            updateActiveOps();
            if (os)
            {
                renderChunk (2 * n, 2.0 * sr);
                const auto& d = halfband2x();
                for (int i = 0; i < n; ++i)
                {
                    outL[(size_t) i] = hbL.down (d, mixL[(size_t) (2 * i)], mixL[(size_t) (2 * i + 1)]);
                    outR[(size_t) i] = hbR.down (d, mixR[(size_t) (2 * i)], mixR[(size_t) (2 * i + 1)]);
                }
            }
            else
            {
                renderChunk (n, sr);
                for (int i = 0; i < n; ++i) { outL[(size_t) i] = mixL[(size_t) i]; outR[(size_t) i] = mixR[(size_t) i]; }
            }
            fx.process (outL.data(), outR.data(), n, val, bpm);

            const double target = val[master] * dbToGain (val[presetGain]);   // the preset's level trim, then the master
            double g = masterGain;
            for (int i = 0; i < n; ++i)
            {
                g += (target - g) * masterSmooth;
                if (R != nullptr)
                {
                    const float yl = (float) safetyClip (outL[(size_t) i] * g);
                    const float yr = (float) safetyClip (outR[(size_t) i] * g);
                    L[pos + i] = yl; R[pos + i] = yr;
                    peak = std::max (peak, std::max (std::abs (yl), std::abs (yr)));
                }
                else
                {
                    const float y = (float) safetyClip (0.5 * (outL[(size_t) i] + outR[(size_t) i]) * g);
                    L[pos + i] = y;
                    peak = std::max (peak, std::abs (y));
                }
            }
            masterGain = g;
            pos += n;
            blockPos += n;
        }
    }

    //==========================================================================
    int activeVoices() const { int c = 0; for (const auto& v : voices) if (v.active()) ++c; return c; }
    bool sustainDown() const { return sustainPedal; }
    double modWheelValue() const { return wheel; }
    double tempo() const { return bpm; }
    float takePeak() { const float p = peak; peak = 0; return p; }
    // mean |output| of each operator over the samples rendered since the last call (for the animated matrix)
    void takeOpActivity (float* out8)
    {
        const double inv = activitySamples > 0 ? 1.0 / activitySamples : 0.0;
        for (int k = 0; k < kNumOps; ++k) { out8[k] = (float) (opActivity[(size_t) k] * inv); opActivity[(size_t) k] = 0; }
        activitySamples = 0;
    }
    bool opActive (int k) const { return activeOp[(size_t) k]; }
    double paramValue (int i) const { return val[(size_t) i]; }
    // the LFOs' current outputs (-1..1, depth applied; 0 when off), for the UI
    double lfoValue (int l) const { return lfo[(size_t) l].value; }
    // the compressor's deepest gain reduction (dB) since the last call
    double takeGainReduction() { return fx.takeGainReduction(); }
    const FxChain& effects() const { return fx; }
    static int latencySamples (bool os) { return os ? HalfbandState::kLatency2x : 0; }
    // the whole plugin's latency for these switch states
    static int latencyFor (bool os, bool distortionOn, bool limiterOn) { return latencySamples (os) + FxChain::latencyFor (distortionOn, limiterOn); }

private:
    static int clampi (int v, int lo, int hi) { return v < lo ? lo : (v > hi ? hi : v); }
    // unmodulated (global) parameter values
    double op (int k, int field) const { return val[(size_t) opParam (k, field)]; }
    // a voice's view of a parameter: the mod matrix's per-voice result, or the global value
    double pv (const Voice& v, int i) const
    {
        if (v.numOv == 0) return val[(size_t) i];   // the common case: no per-voice modulation this chunk
        for (int j = 0; j < v.numOv; ++j) if (v.ovParam[(size_t) j] == i) return v.ovVal[(size_t) j];
        return val[(size_t) i];
    }
    double opv (const Voice& v, int k, int field) const { return pv (v, opParam (k, field)); }

    void pushKey (int note) { removeKey (note); if (keyCount < 128) keys[(size_t) keyCount++] = note; }
    void removeKey (int note)
    {
        int w = 0;
        for (int r = 0; r < keyCount; ++r) if (keys[(size_t) r] != note) keys[(size_t) w++] = keys[(size_t) r];
        keyCount = w;
    }

    void release (Voice& v)
    {
        v.held = v.sustained = false;
        for (int i = 0; i < kNumEnvs; ++i) v.env[(size_t) i].gateOff (model->envs[(size_t) i]);
    }

    void setVoicePitch (Voice& v, int note, bool glide)
    {
        v.glideFrom = v.pitch;
        v.glideTo = note;
        v.glidePos = glide ? 0.0 : 1.0;
        if (! glide) v.pitch = note;
    }

    void startVoice (Voice& v, int note, int vel, double fromPitch)
    {
        const bool fresh = ! v.active();
        for (int k = 0; k < kNumOps; ++k)
        {
            if (op (k, fPhaseReset) >= 0.5) v.op[(size_t) k].reset (0.0);
            else if (fresh) v.op[(size_t) k].reset (rng.uni());
            else { auto& o = v.op[(size_t) k]; o.out = o.prev = o.prev2 = 0; }
        }
        if (fresh) for (auto& f : v.flt) f.reset();
        for (int i = 0; i < kNumEnvs; ++i) v.env[(size_t) i].gateOn (model->envs[(size_t) i]);
        v.note = note;
        v.velocity = vel;
        v.velN = vel / 127.0;
        v.age = ++ageCounter;
        v.timeOn = 0;
        v.held = true;
        v.sustained = false;
        v.alive = true;
        v.glideFrom = fromPitch;
        v.glideTo = note;
        v.glidePos = fromPitch == (double) note ? 1.0 : 0.0;
        v.pitch = fromPitch;
        v.snap = true;
    }

    // ---- parameters -----------------------------------------------------------
    void smoothParams()
    {
        const auto& t = paramTable();
        for (int i = 0; i < kNumParams; ++i)
        {
            if (! psmooth[(size_t) i]) continue;
            const double d = targetNorm[(size_t) i] - normCur[(size_t) i];
            if (d == 0.0) continue;
            if (std::abs (d) < 1e-5) normCur[(size_t) i] = targetNorm[(size_t) i];
            else normCur[(size_t) i] += d * paramSmooth;
            val[(size_t) i] = base[(size_t) i] = paramFromNorm (t[(size_t) i], normCur[(size_t) i]);
        }
    }

    // ---- LFOs (global) -----------------------------------------------------------
    double lfoShapeValue (int l, int wave, double p) const
    {
        switch (wave)
        {
            case lfoSine:     return std::sin (kTwoPi * p);
            case lfoTriangle: return p < 0.25 ? 4.0 * p : (p < 0.75 ? 2.0 - 4.0 * p : 4.0 * p - 4.0);
            case lfoSaw:      return 2.0 * p - 1.0;
            case lfoSquare:   return p < 0.5 ? 1.0 : -1.0;
            case lfoSampleHold: return lfo[(size_t) l].hold;
            default:
            {
                const auto& s = model->lfoShapes[(size_t) l].pts;
                const double x = p * kLfoShapePoints;
                const int i0 = (int) x, i1 = (i0 + 1) % kLfoShapePoints;
                const double f = x - i0;
                return s[(size_t) (i0 % kLfoShapePoints)] + (s[(size_t) i1] - s[(size_t) (i0 % kLfoShapePoints)]) * f;
            }
        }
    }

    void updateLfos (double chunkSec)
    {
        for (int l = 0; l < kNumLfos; ++l)
        {
            auto& L = lfo[(size_t) l];
            auto lp = [this, l] (int field) { return val[(size_t) lfoParam (l, field)]; };
            if (lp (hOn) < 0.5) { L.value = 0; L.phase = 0; L.cycle = -1; continue; }
            const bool sync = lp (hSync) >= 0.5;
            double hz;
            if (sync)
            {
                const double beats = kLfoDivBeats[clampi ((int) lp (hDiv), 0, kNumLfoDivs - 1)];
                hz = (bpm / 60.0) / beats;
                if (playing)   // lock to the song position
                    L.phase = (ppqAtBlock + (blockPos / sr) * (bpm / 60.0)) / beats;
                else
                    L.phase += hz * chunkSec;
            }
            else
            {
                hz = lp (hRate);
                L.phase += hz * chunkSec;
            }
            if (L.phase > 1e9) L.phase -= 1e9;   // keep the accumulator in range after days of running
            const double total = L.phase + lp (hPhase) / 360.0;
            const long long cyc = (long long) std::floor (total);
            if (cyc != L.cycle) { L.cycle = cyc; L.hold = rng.bi(); }
            const double p = total - (double) cyc;
            L.value = lfoShapeValue (l, (int) lp (hWave), p) * lp (hDepth);
        }
    }

    // ---- mod matrix -------------------------------------------------------------
    static bool perVoiceParam (int i) { return i >= op1Wave && i <= fltLast; }

    // Resolves the active slots; applies the global sources to the non-voice destinations.
    void updateModSlots()
    {
        const auto& t = paramTable();
        const auto& dstMap = modDestParams();
        // restore what the last chunk modulated globally
        for (int j = 0; j < numGlobalMod; ++j) { const int i = globalModParam[(size_t) j]; val[(size_t) i] = base[(size_t) i]; }
        numGlobalMod = 0;
        numSlots = 0;
        std::array<double, kNumModSlots> gOff {};
        for (int s = 0; s < kNumModSlots; ++s)
        {
            if (val[(size_t) modParam (s, mOn)] < 0.5) continue;
            const int src = (int) val[(size_t) modParam (s, mSrc)];
            const int dsel = (int) val[(size_t) modParam (s, mDst)];
            const double amt = val[(size_t) modParam (s, mAmt)];
            if (src <= srcNone || dsel <= 0 || dsel >= (int) dstMap.size() || std::abs (amt) < 1e-6) continue;
            ModSlot& m = slots[(size_t) numSlots++];
            m.dst = dstMap[(size_t) dsel];
            m.src = src;
            m.amt = amt;
            m.perVoice = perVoiceParam (m.dst);
            if (! m.perVoice)
            {
                // global destination: only the global sources count
                int j = 0;
                for (; j < numGlobalMod; ++j) if (globalModParam[(size_t) j] == m.dst) break;
                if (j == numGlobalMod) { globalModParam[(size_t) numGlobalMod++] = m.dst; gOff[(size_t) j] = 0; }
                gOff[(size_t) j] += globalSource (src) * amt;
            }
        }
        for (int j = 0; j < numGlobalMod; ++j)
        {
            const int i = globalModParam[(size_t) j];
            val[(size_t) i] = paramFromNorm (t[(size_t) i], normCur[(size_t) i] + gOff[(size_t) j]);
        }
    }

    double globalSource (int src) const
    {
        if (src >= srcLfo1 && src <= srcLfoLast) return lfo[(size_t) (src - srcLfo1)].value;
        switch (src)
        {
            case srcModWheel:   return wheel;
            case srcAftertouch: return aftertouch;
            case srcPitchBend:  return bend;
            default:            return 0.0;   // per-voice sources have no global value
        }
    }

    // A source as one voice sees it. Envelopes: amplitude and filter envelopes 0..1, pitch and
    // mod-index envelopes -1..1 (their level 0.5 is neutral). Key: -1 at C1 .. +1 at C9 (C4 = 0).
    double voiceSource (const Voice& v, const std::array<double, kNumEnvs>& e, int src) const
    {
        if (src >= srcLfo1 && src <= srcLfoLast)
        {
            const int l = src - srcLfo1;
            const double delay = val[(size_t) lfoParam (l, hDelay)];
            const double fade = delay > 1e-4 ? clampd (v.timeOn / delay, 0.0, 1.0) : 1.0;
            return lfo[(size_t) l].value * fade;
        }
        if (src >= srcOpAmpEnv1 && src <= srcOpAmpEnvLast)     return e[(size_t) opEnvIndex (src - srcOpAmpEnv1, envAmp)];
        if (src >= srcOpPitchEnv1 && src <= srcOpPitchEnvLast) return 2.0 * e[(size_t) opEnvIndex (src - srcOpPitchEnv1, envPitch)] - 1.0;
        if (src >= srcOpModEnv1 && src <= srcOpModEnvLast)     return 2.0 * e[(size_t) opEnvIndex (src - srcOpModEnv1, envMod)] - 1.0;
        if (src >= srcFltCutEnv1 && src <= srcFltCutEnvLast)   return e[(size_t) fltEnvIndex (src - srcFltCutEnv1, fenvCutoff)];
        if (src >= srcFltLvlEnv1 && src <= srcFltLvlEnvLast)   return e[(size_t) fltEnvIndex (src - srcFltLvlEnv1, fenvLevel)];
        switch (src)
        {
            case srcVelocity:   return v.velN;
            case srcModWheel:   return wheel;
            case srcAftertouch: return aftertouch;
            case srcPitchBend:  return bend;
            case srcKey:        return clampd ((v.pitch - 60.0) / 48.0, -1.0, 1.0);
            default:            return 0.0;
        }
    }

    // The per-voice destinations for this chunk
    void updateVoiceMod (Voice& v, const std::array<double, kNumEnvs>& e)
    {
        v.numOv = 0;
        if (numSlots == 0) return;
        const auto& t = paramTable();
        std::array<double, kNumModSlots> off {};
        for (int s = 0; s < numSlots; ++s)
        {
            const auto& m = slots[(size_t) s];
            if (! m.perVoice) continue;
            int j = 0;
            for (; j < v.numOv; ++j) if (v.ovParam[(size_t) j] == m.dst) break;
            if (j == v.numOv) { v.ovParam[(size_t) v.numOv++] = m.dst; off[(size_t) j] = 0; }
            off[(size_t) j] += voiceSource (v, e, m.src) * m.amt;
        }
        for (int j = 0; j < v.numOv; ++j)
        {
            const int i = v.ovParam[(size_t) j];
            v.ovVal[(size_t) j] = paramFromNorm (t[(size_t) i], normCur[(size_t) i] + off[(size_t) j]);
        }
    }

    // Which operators do anything: audible ones (routed to an output, not muted,
    // allowed by solo) and, transitively, everything that modulates them.
    void updateActiveOps()
    {
        bool anySolo = false;
        for (int k = 0; k < kNumOps; ++k) anySolo = anySolo || op (k, fSolo) >= 0.5;
        std::array<bool, kNumOps> usable {};
        for (int k = 0; k < kNumOps; ++k)
        {
            usable[(size_t) k] = op (k, fMute) < 0.5 && op (k, fLevel) > 1e-6;
            bool routed = false;
            for (int j = 0; j < kNumOutputs; ++j) routed = routed || val[(size_t) outParam (k, j)] > 1e-6;
            audibleOp[(size_t) k] = usable[(size_t) k] && routed && (! anySolo || op (k, fSolo) >= 0.5);
            activeOp[(size_t) k] = audibleOp[(size_t) k];
        }
        for (int pass = 0; pass < kNumOps; ++pass)
        {
            bool changed = false;
            for (int s = 0; s < kNumOps; ++s)
            {
                if (activeOp[(size_t) s] || ! usable[(size_t) s]) continue;
                for (int d = 0; d < kNumOps; ++d)
                    if (activeOp[(size_t) d] && (val[(size_t) pmParam (s, d)] > 1e-6 || val[(size_t) rmParam (s, d)] > 1e-6))
                    { activeOp[(size_t) s] = true; changed = true; break; }
            }
            if (! changed) break;
        }
        numActive = 0;
        for (int k = 0; k < kNumOps; ++k) if (activeOp[(size_t) k]) activeList[(size_t) numActive++] = k;
        // grid cells in use (both ends active)
        numPm = numRm = 0;
        for (int s = 0; s < kNumOps; ++s)
        {
            if (! activeOp[(size_t) s]) continue;
            for (int d = 0; d < kNumOps; ++d)
            {
                if (! activeOp[(size_t) d]) continue;
                if (val[(size_t) pmParam (s, d)] > 1e-6) pmList[(size_t) numPm++] = s * kNumOps + d;
                if (val[(size_t) rmParam (s, d)] > 1e-6) rmList[(size_t) numRm++] = s * kNumOps + d;
            }
        }
    }

    // ---- control rate -----------------------------------------------------------
    static double panLaw (double pos, bool left)
    {
        const double ang = (clampd (pos, -1.0, 1.0) + 1.0) * kPi / 4.0;   // centre = unity in both channels
        return std::min (1.0, 1.4142135623730951 * (left ? std::cos (ang) : std::sin (ang)));
    }

    // Targets for the end of this chunk. rate = the rate the voice runs at (2x when oversampling).
    void updateVoice (Voice& v, VoiceCtl& T, int n, double rate)
    {
        const double chunkSec = n / rate;
        const double beatsPerSec = bpm / 60.0;
        const auto& M = *model;

        // envelopes
        std::array<double, kNumEnvs> e {};
        for (int i = 0; i < kNumEnvs; ++i)
        {
            const auto& spec = M.envs[(size_t) i];
            e[(size_t) i] = v.env[(size_t) i].advance (spec, spec.sync ? chunkSec * beatsPerSec : chunkSec);
        }
        v.timeOn += chunkSec;

        // glide
        if (v.glidePos < 1)
        {
            v.glidePos = std::min (1.0, v.glidePos + chunkSec / std::max (val[portaTime], 0.001));
            v.pitch = v.glideFrom + (v.glideTo - v.glideFrom) * v.glidePos;
        }
        const double bendSemis = bend * val[bendRange];

        // the mod matrix's per-voice results (read through opv / pv below)
        updateVoiceMod (v, e);

        bool anyAlive = false;
        for (int a = 0; a < numActive; ++a)
        {
            const int k = activeList[(size_t) a];
            auto& C = T.op[(size_t) k];
            const auto& amp = v.env[(size_t) opEnvIndex (k, envAmp)];
            if (amp.active()) anyAlive = true;
            const double ampLvl = amp.finished() ? 0.0 : e[(size_t) opEnvIndex (k, envAmp)];
            const double pitchSemis = (2.0 * e[(size_t) opEnvIndex (k, envPitch)] - 1.0) * opv (v, k, fPitchEnvAmt);
            C.modScale = std::max (0.0, 1.0 + (2.0 * e[(size_t) opEnvIndex (k, envMod)] - 1.0) * opv (v, k, fModEnvAmt));

            double hz;
            if (op (k, fFixed) >= 0.5)
                hz = opv (v, k, fHz) * std::pow (2.0, (opv (v, k, fFine) / 100.0 + pitchSemis) / 12.0);
            else
            {
                const double tracked = 60.0 + (v.pitch + bendSemis - 60.0) * opv (v, k, fKeyTrack);
                hz = opv (v, k, fRatio) * noteToHz (tracked + opv (v, k, fFine) / 100.0 + pitchSemis);
            }
            const double dt = std::min (hz / rate, 0.49);
            const int subs = clampi ((int) op (k, fUnison), 1, kMaxUnison);
            const double detune = opv (v, k, fDetune), spread = opv (v, k, fSpread), pan = opv (v, k, fPan);
            for (int u = 0; u < subs; ++u)
            {
                const double pos = subs > 1 ? 2.0 * u / (subs - 1) - 1.0 : 0.0;
                C.dt[(size_t) u] = dt * std::pow (2.0, detune * pos / 1200.0);
                C.panL[(size_t) u] = panLaw (pan + spread * pos, true);
                C.panR[(size_t) u] = panLaw (pan + spread * pos, false);
            }
            v.mip[(size_t) k] = Wavetable::levelFor (dt);
            const double velCurve = 0.05 + 0.95 * std::pow (v.velN, 1.5);
            const double velGain = 1.0 + opv (v, k, fVel) * (velCurve - 1.0);
            C.gain = opv (v, k, fLevel) * velGain * ampLvl / std::sqrt ((double) subs);
            const bool audible = audibleOp[(size_t) k];
            for (int j = 0; j < kNumOutputs; ++j) C.send[(size_t) j] = audible ? pv (v, outParam (k, j)) : 0.0;
        }
        v.alive = anyAlive;

        for (int c = 0; c < numPm; ++c)
        {
            const int idx = pmList[(size_t) c];
            const double d = pv (v, pm11 + idx);
            T.pm[(size_t) idx] = d * d * kMaxPmTurns;
        }
        for (int c = 0; c < numRm; ++c)
        {
            const int idx = rmList[(size_t) c];
            T.rm[(size_t) idx] = pv (v, rm11 + idx);
        }

        for (int f = 0; f < kNumFilters; ++f)
        {
            auto& F = T.flt[(size_t) f];
            auto fp = [this, &v, f] (int field) { return pv (v, fltParam (f, field)); };
            const double cutEnv = e[(size_t) fltEnvIndex (f, fenvCutoff)];
            const double oct = fp (gEnvAmt) * kFltEnvOctaves * cutEnv
                             + fp (gKeyTrack) * (v.pitch - 60.0) / 12.0
                             + fp (gVel) * kFltVelOctaves * (v.velN - 0.5);
            F.g = SVF::gFor (fp (gCutoff) * std::pow (2.0, oct), rate);
            F.k = SVF::kFor (fp (gReso));
            F.drive = fp (gDrive);
            F.mix = fp (gMix);
            F.level = e[(size_t) fltEnvIndex (f, fenvLevel)];
        }
    }

    // ---- audio rate -------------------------------------------------------------
    static double saturate (double x, double drive)
    {
        if (drive <= 0.0) return x;
        const double g = 1.0 + 7.0 * drive;
        return x + drive * (std::tanh (g * x) - x);
    }

    double filterOne (Voice& v, int f, int ch, double x, const FilterCtl& F, const SVFCoefs& c, int type, bool twoStage, bool on)
    {
        if (! on) return x * F.level;
        auto& st = v.flt[(size_t) f];
        double y = saturate (x, F.drive);
        y = st.svf[(size_t) (ch * 2)].process (y, c, type);
        if (twoStage) y = st.svf[(size_t) (ch * 2 + 1)].process (y, c, type);
        return (x + (y - x) * F.mix) * F.level;
    }

    void renderVoice (Voice& v, int n, double rate)
    {
        VoiceCtl T = v.cur;
        updateVoice (v, T, n, rate);
        if (v.snap) { v.cur = T; v.snap = false; }
        if (! v.alive) { v.cur = T; return; }

        const double inv = 1.0 / n;
        VoiceCtl& C = v.cur;
        // per-sample increments
        VoiceCtl I;
        std::array<int, kNumOps> subs {};
        std::array<int, kNumOps> wave {};
        for (int a = 0; a < numActive; ++a)
        {
            const int k = activeList[(size_t) a];
            subs[(size_t) k] = clampi ((int) op (k, fUnison), 1, kMaxUnison);
            wave[(size_t) k] = (int) op (k, fWave);
            auto& ik = I.op[(size_t) k]; const auto& tk = T.op[(size_t) k]; const auto& ck = C.op[(size_t) k];
            for (int u = 0; u < subs[(size_t) k]; ++u)
            {
                ik.dt[(size_t) u] = (tk.dt[(size_t) u] - ck.dt[(size_t) u]) * inv;
                ik.panL[(size_t) u] = (tk.panL[(size_t) u] - ck.panL[(size_t) u]) * inv;
                ik.panR[(size_t) u] = (tk.panR[(size_t) u] - ck.panR[(size_t) u]) * inv;
            }
            ik.gain = (tk.gain - ck.gain) * inv;
            ik.modScale = (tk.modScale - ck.modScale) * inv;
            for (int j = 0; j < kNumOutputs; ++j) ik.send[(size_t) j] = (tk.send[(size_t) j] - ck.send[(size_t) j]) * inv;
        }
        for (int c = 0; c < numPm; ++c) { const int i = pmList[(size_t) c]; I.pm[(size_t) i] = (T.pm[(size_t) i] - C.pm[(size_t) i]) * inv; }
        for (int c = 0; c < numRm; ++c) { const int i = rmList[(size_t) c]; I.rm[(size_t) i] = (T.rm[(size_t) i] - C.rm[(size_t) i]) * inv; }
        for (int f = 0; f < kNumFilters; ++f)
        {
            I.flt[(size_t) f].g = (T.flt[(size_t) f].g - C.flt[(size_t) f].g) * inv;
            I.flt[(size_t) f].k = (T.flt[(size_t) f].k - C.flt[(size_t) f].k) * inv;
            I.flt[(size_t) f].drive = (T.flt[(size_t) f].drive - C.flt[(size_t) f].drive) * inv;
            I.flt[(size_t) f].mix = (T.flt[(size_t) f].mix - C.flt[(size_t) f].mix) * inv;
            I.flt[(size_t) f].level = (T.flt[(size_t) f].level - C.flt[(size_t) f].level) * inv;
        }
        const int routing = (int) val[fltRouting];
        std::array<int, kNumFilters> ftype {};
        std::array<bool, kNumFilters> f24 {}, fon {}, fused {};
        for (int f = 0; f < kNumFilters; ++f)
        {
            ftype[(size_t) f] = (int) val[(size_t) fltParam (f, gType)];
            f24[(size_t) f] = val[(size_t) fltParam (f, gSlope)] >= 0.5;
            fon[(size_t) f] = val[(size_t) fltParam (f, gOn)] >= 0.5;
        }
        // A filter that nothing feeds (now or earlier in this note) is skipped entirely.
        // Once fed it keeps running until the voice ends, so a tail never cuts off.
        for (int f = 0; f < kNumFilters; ++f)
        {
            bool fed = false;
            for (int a = 0; a < numActive && ! fed; ++a)
            {
                const auto& ck = C.op[(size_t) activeList[(size_t) a]];
                const auto& tk = T.op[(size_t) activeList[(size_t) a]];
                fed = ck.send[(size_t) f] > 1e-9 || tk.send[(size_t) f] > 1e-9;
            }
            if (routing == routeSeries && f > 0) fed = fed || fused[(size_t) f - 1];
            if (routing == routeTwoIntoThree && f == 2) fed = fed || fused[0] || fused[1];
            if (fed) v.flt[(size_t) f].quiet = false;
            fused[(size_t) f] = ! v.flt[(size_t) f].quiet;
        }
        const bool anyFilter = fused[0] || fused[1] || fused[2];
        std::array<SVFCoefs, kNumFilters> fc;
        const Wavetable* tables[kNumOps];
        for (int k = 0; k < kNumOps; ++k)
        {
            const int w = wave[(size_t) k];
            tables[k] = w == waveCustom ? (model->tables[(size_t) k] != nullptr ? model->tables[(size_t) k] : &starterTable (waveSine))
                      : (w == waveNoise ? nullptr : &starterTable (w));
        }

        for (int i = 0; i < n; ++i)
        {
            // ramps
            for (int a = 0; a < numActive; ++a)
            {
                const int k = activeList[(size_t) a];
                auto& ck = C.op[(size_t) k]; const auto& ik = I.op[(size_t) k];
                for (int u = 0; u < subs[(size_t) k]; ++u)
                {
                    ck.dt[(size_t) u] += ik.dt[(size_t) u]; ck.panL[(size_t) u] += ik.panL[(size_t) u]; ck.panR[(size_t) u] += ik.panR[(size_t) u];
                }
                ck.gain += ik.gain; ck.modScale += ik.modScale;
                for (int j = 0; j < kNumOutputs; ++j) ck.send[(size_t) j] += ik.send[(size_t) j];
            }
            for (int c = 0; c < numPm; ++c) { const int idx = pmList[(size_t) c]; C.pm[(size_t) idx] += I.pm[(size_t) idx]; }
            for (int c = 0; c < numRm; ++c) { const int idx = rmList[(size_t) c]; C.rm[(size_t) idx] += I.rm[(size_t) idx]; }
            if (anyFilter)
                for (int f = 0; f < kNumFilters; ++f)
                {
                    if (! fused[(size_t) f]) continue;
                    auto& F = C.flt[(size_t) f]; const auto& Fi = I.flt[(size_t) f];
                    F.g += Fi.g; F.k += Fi.k; F.drive += Fi.drive; F.mix += Fi.mix; F.level += Fi.level;
                    fc[(size_t) f].set (F.g, F.k);
                }

            double busL[kNumOutputs] {}, busR[kNumOutputs] {};
            for (int a = 0; a < numActive; ++a)
            {
                const int k = activeList[(size_t) a];
                auto& o = v.op[(size_t) k];
                const auto& ck = C.op[(size_t) k];

                // phase modulation input (turns)
                double pmIn = 0;
                for (int c = 0; c < numPm; ++c)
                {
                    const int idx = pmList[(size_t) c];
                    if ((idx & 7) != k) continue;
                    const int s = idx >> 3;
                    const double src = s < k ? v.op[(size_t) s].out : (s == k ? 0.5 * (o.prev + o.prev2) : v.op[(size_t) s].prev);
                    pmIn += C.pm[(size_t) idx] * src;
                }
                pmIn *= ck.modScale;

                double mono = 0, L = 0, R = 0;
                const int ns = subs[(size_t) k];
                if (tables[k] == nullptr)   // noise
                {
                    for (int u = 0; u < ns; ++u)
                    {
                        const double y = rng.bi();
                        mono += y; L += y * ck.panL[(size_t) u]; R += y * ck.panR[(size_t) u];
                    }
                }
                else
                {
                    const Wavetable& tb = *tables[k];
                    const int lvl = v.mip[(size_t) k];
                    for (int u = 0; u < ns; ++u)
                    {
                        double ph = o.phase[(size_t) u];
                        const double y = tb.lookup (lvl, ph + pmIn);
                        ph += ck.dt[(size_t) u];
                        if (ph >= 1.0) ph -= 1.0;
                        o.phase[(size_t) u] = ph;
                        mono += y; L += y * ck.panL[(size_t) u]; R += y * ck.panR[(size_t) u];
                    }
                }
                const double g = ck.gain;
                mono *= g; L *= g; R *= g;

                for (int c = 0; c < numRm; ++c)
                {
                    const int idx = rmList[(size_t) c];
                    if ((idx & 7) != k) continue;
                    const int s = idx >> 3;
                    const double src = s < k ? v.op[(size_t) s].out : (s == k ? o.prev : v.op[(size_t) s].prev);
                    const double d = C.rm[(size_t) idx];
                    const double m = (1.0 - d) + d * src;
                    mono *= m; L *= m; R *= m;
                }
                o.out = mono;
                opActivity[(size_t) k] += std::abs (mono);
                scopeAcc[(size_t) k][(size_t) i] += mono;
                for (int j = 0; j < kNumOutputs; ++j) { busL[j] += L * ck.send[(size_t) j]; busR[j] += R * ck.send[(size_t) j]; }
            }
            for (int a = 0; a < numActive; ++a)
            {
                auto& o = v.op[(size_t) activeList[(size_t) a]];
                o.prev2 = o.prev; o.prev = o.out;
            }

            // filters
            double yL = busL[busDry], yR = busR[busDry];
            if (anyFilter)
            {
                double fL[kNumFilters] {}, fR[kNumFilters] {};
                auto run = [&] (int f, double inL, double inR)
                {
                    if (! fused[(size_t) f]) return;
                    fL[f] = filterOne (v, f, 0, inL, C.flt[(size_t) f], fc[(size_t) f], ftype[(size_t) f], f24[(size_t) f], fon[(size_t) f]);
                    fR[f] = filterOne (v, f, 1, inR, C.flt[(size_t) f], fc[(size_t) f], ftype[(size_t) f], f24[(size_t) f], fon[(size_t) f]);
                };
                if (routing == routeSeries)
                {
                    run (0, busL[0], busR[0]);
                    run (1, busL[1] + fL[0], busR[1] + fR[0]);
                    run (2, busL[2] + fL[1], busR[2] + fR[1]);
                    yL += fL[2]; yR += fR[2];
                }
                else if (routing == routeTwoIntoThree)
                {
                    run (0, busL[0], busR[0]);
                    run (1, busL[1], busR[1]);
                    run (2, busL[2] + fL[0] + fL[1], busR[2] + fR[0] + fR[1]);
                    yL += fL[2]; yR += fR[2];
                }
                else
                {
                    for (int f = 0; f < kNumFilters; ++f) run (f, busL[f], busR[f]);
                    yL += fL[0] + fL[1] + fL[2]; yR += fR[0] + fR[1] + fR[2];
                }
            }
            mixL[(size_t) i] += yL * kVoiceGain;
            mixR[(size_t) i] += yR * kVoiceGain;
        }
        v.cur = T;
        if (! v.alive) { for (auto& f : v.flt) f.reset(); v.held = v.sustained = false; }
    }

    void renderChunk (int n, double rate)
    {
        std::fill (mixL.begin(), mixL.begin() + n, 0.0);
        std::fill (mixR.begin(), mixR.begin() + n, 0.0);
        for (int k = 0; k < kNumOps; ++k) std::fill (scopeAcc[(size_t) k].begin(), scopeAcc[(size_t) k].begin() + n, 0.0);
        for (auto& v : voices)
            if (v.active()) renderVoice (v, n, rate);
        activitySamples += n;
        // the per-operator scopes (sum over voices), at the base rate
        const int step = rate > sr * 1.5 ? 2 : 1;
        for (int i = 0; i < n; i += step)
        {
            for (int k = 0; k < kNumOps; ++k) scope[(size_t) k][(size_t) scopePos] = (float) scopeAcc[(size_t) k][(size_t) i];
            scopePos = (scopePos + 1) % kScopeLen;
        }
    }

public:
    static constexpr int kScopeLen = 512;
    // The last `count` scope points of operator k, every `stride`-th sample, oldest first
    void copyScope (int k, float* out, int count, int stride) const
    {
        int pos = scopePos - count * stride;
        pos = ((pos % kScopeLen) + kScopeLen) % kScopeLen;
        for (int i = 0; i < count; ++i) { out[i] = scope[(size_t) k][(size_t) pos]; pos = (pos + stride) % kScopeLen; }
    }
private:

    //==========================================================================
    std::array<Voice, kMaxVoices> voices;
    Model defaultModel;
    const Model* model = nullptr;

    std::array<float, kNumParams> raw {};
    std::array<double, kNumParams> targetNorm {}, normCur {}, val {}, base {};   // val = base + global modulation
    std::array<bool, kNumParams> plog {}, psmooth {};

    std::array<LfoState, kNumLfos> lfo;
    std::array<ModSlot, kNumModSlots> slots;
    int numSlots = 0;
    std::array<int, kNumModSlots> globalModParam {};
    int numGlobalMod = 0;

    std::array<bool, kNumOps> activeOp {}, audibleOp {};
    std::array<int, kNumOps> activeList {};
    int numActive = 0;
    std::array<int, kMaxCells> pmList {}, rmList {};
    int numPm = 0, numRm = 0;

    std::array<double, 2 * kChunk> mixL {}, mixR {};
    std::array<double, kChunk> outL {}, outR {};
    FxChain fx;
    HalfbandState hbL, hbR;
    bool lastOs = false;

    std::array<int, 128> keys {};
    int keyCount = 0;
    Rng rng;
    double sr = 48000, masterGain = 0.7, masterSmooth = 0.001, paramSmooth = 0.5;
    double bend = 0, wheel = 0, aftertouch = 0;
    double bpm = 120, ppqAtBlock = 0;
    int blockPos = 0;        // samples rendered since setTransport()
    bool playing = false;
    int lastNote = -1;
    double lastPitch = 60;
    uint64_t ageCounter = 0;
    bool sustainPedal = false;
    float peak = 0;
    std::array<double, kNumOps> opActivity {};
    std::array<std::array<double, 2 * kChunk>, kNumOps> scopeAcc {};
    std::array<std::array<float, kScopeLen>, kNumOps> scope {};
    int scopePos = 0;
    int activitySamples = 0;
};
} // namespace eightball
