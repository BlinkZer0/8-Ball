// ============================================================================
//  The WebAssembly build of the Eight Ball engine: a flat C API over
//  SynthEngine.h + dsp/*.h (the same source the plugin compiles), called from
//  web-host.js. Nothing JUCE, nothing JavaScript-specific in here.
//
//  Build (vst/webhost/build-web.ps1 does this):
//    em++ wasm-engine.cpp -O3 -std=c++17 -I../Source -fno-exceptions -fno-rtti
//         -s STANDALONE_WASM=1 --no-entry -s EXPORTED_FUNCTIONS=[...] -o eight-ball.wasm
//
//  One Instance = one engine with its own Model (eight wavetables, the 30
//  envelopes, the LFO shapes). The page runs two: one in the AudioWorklet
//  that makes the sound, one on the main thread that bakes wavetables (about
//  2 ms each) and hands the finished tables over, so the audio thread never
//  stalls on a wave edit.
// ============================================================================
#include <cstdlib>
#include <cstring>
#include "SynthEngine.h"

using namespace eightball;

namespace
{
constexpr int kMaxFrames = 512;

struct Instance
{
    SynthEngine engine;
    Model model;
    std::array<Wavetable, kNumOps> tables;
    std::array<float, kNumParams> params {};
    float outL[kMaxFrames] {}, outR[kMaxFrames] {};
    float scratch[kNumOps] {};
};
} // namespace

#define EB_EXPORT extern "C" __attribute__((used, visibility ("default")))

EB_EXPORT void* eb_alloc (int bytes) { return std::malloc ((size_t) bytes); }
EB_EXPORT void eb_free (void* p) { std::free (p); }

EB_EXPORT int eb_num_params() { return kNumParams; }
EB_EXPORT float eb_param_default (int i) { return i >= 0 && i < kNumParams ? paramTable()[(size_t) i].def : 0.0f; }
EB_EXPORT int eb_max_frames() { return kMaxFrames; }

EB_EXPORT Instance* eb_create (double sampleRate)
{
    auto* in = new Instance();
    for (int k = 0; k < kNumOps; ++k)
    {
        buildWavetable (WaveSpec::sine(), in->tables[(size_t) k]);
        in->model.tables[(size_t) k] = &in->tables[(size_t) k];
    }
    for (int i = 0; i < kNumParams; ++i) in->params[(size_t) i] = paramTable()[(size_t) i].def;
    in->engine.setParamValues (in->params.data());
    in->engine.prepare (sampleRate);
    in->engine.setModel (&in->model);
    in->engine.settleParams();
    return in;
}
EB_EXPORT void eb_destroy (Instance* in) { delete in; }

// ---- parameters: write into the array, then apply (once per block) ---------
EB_EXPORT float* eb_params (Instance* in) { return in->params.data(); }
EB_EXPORT void eb_apply_params (Instance* in) { in->engine.setParamValues (in->params.data()); }
EB_EXPORT void eb_settle (Instance* in) { in->engine.setParamValues (in->params.data()); in->engine.settleParams(); }

// ---- audio ------------------------------------------------------------------
EB_EXPORT float* eb_out_l (Instance* in) { return in->outL; }
EB_EXPORT float* eb_out_r (Instance* in) { return in->outR; }
EB_EXPORT void eb_transport (Instance* in, double bpm, double ppq, int playing) { in->engine.setTransport (bpm, ppq, playing != 0); }
EB_EXPORT void eb_render (Instance* in, int frames)
{
    if (frames > kMaxFrames) frames = kMaxFrames;
    in->engine.render (in->outL, in->outR, frames);
}

// ---- MIDI -------------------------------------------------------------------
EB_EXPORT void eb_note_on (Instance* in, int note, int vel) { in->engine.noteOn (note, vel); }
EB_EXPORT void eb_note_off (Instance* in, int note) { in->engine.noteOff (note); }
EB_EXPORT void eb_sustain (Instance* in, int on) { in->engine.setSustain (on != 0); }
EB_EXPORT void eb_bend (Instance* in, double v) { in->engine.setPitchBend (v); }
EB_EXPORT void eb_wheel (Instance* in, double v) { in->engine.setModWheel (v); }
EB_EXPORT void eb_aftertouch (Instance* in, double v) { in->engine.setAftertouch (v); }
EB_EXPORT void eb_all_notes_off (Instance* in) { in->engine.allNotesOff(); }
EB_EXPORT void eb_panic (Instance* in) { in->engine.panic(); }

// ---- the model ----------------------------------------------------------------
// pts: n x [time, level, tension]
EB_EXPORT void eb_set_env (Instance* in, int index, const float* pts, int n, int sustain, int loopStart, int loopEnd, int sync)
{
    if (index < 0 || index >= kNumEnvs) return;
    EnvSpec e;
    float last = 0;
    for (int i = 0; i < n && i < kMaxEnvPoints; ++i)
    {
        float t = pts[i * 3] < last ? last : pts[i * 3];
        last = t;
        e.add (t, pts[i * 3 + 1] < 0 ? 0.0f : (pts[i * 3 + 1] > 1 ? 1.0f : pts[i * 3 + 1]), pts[i * 3 + 2]);
    }
    e.sustain = sustain >= 0 && sustain < e.numPoints ? sustain : -1;
    e.loopStart = loopStart >= 0 && loopStart < e.numPoints ? loopStart : -1;
    e.loopEnd = loopEnd >= 0 && loopEnd < e.numPoints ? loopEnd : -1;
    if (e.loopEnd <= e.loopStart) e.loopStart = e.loopEnd = -1;
    e.sync = sync != 0;
    in->model.envs[(size_t) index] = e;
}
EB_EXPORT void eb_set_lfo_shape (Instance* in, int lfo, const float* pts64)
{
    if (lfo < 0 || lfo >= kNumLfos) return;
    for (int i = 0; i < kLfoShapePoints; ++i) in->model.lfoShapes[(size_t) lfo].pts[(size_t) i] = pts64[i];
}
// Bakes a wave into this instance's table for operator `op` (the main-thread instance does this)
EB_EXPORT void eb_bake_wave (Instance* in, int op, int drawn, const float* levels, int numLevels, const float* phases, const float* shape256)
{
    if (op < 0 || op >= kNumOps) return;
    WaveSpec w;
    w.drawn = drawn != 0;
    if (w.drawn) { for (int i = 0; i < kDrawPoints; ++i) w.shape[(size_t) i] = shape256[i]; }
    else
    {
        for (int i = 0; i < kMaxPartials && i < numLevels; ++i)
        {
            w.level[(size_t) i] = levels[i];
            w.phase[(size_t) i] = phases != nullptr ? phases[i] : 0.0f;
        }
    }
    buildWavetable (w, in->tables[(size_t) op]);
}
// The baked table as a flat float array (kLevels x (kSize + 1)), to copy into another instance
EB_EXPORT int eb_table_floats() { return Wavetable::kLevels * (Wavetable::kSize + 1); }
EB_EXPORT float* eb_table_ptr (Instance* in, int op) { return in->tables[(size_t) (op < 0 ? 0 : op % kNumOps)].table[0].data(); }
EB_EXPORT void eb_set_table (Instance* in, int op, const float* data)
{
    if (op < 0 || op >= kNumOps) return;
    std::memcpy (in->tables[(size_t) op].table[0].data(), data, sizeof (float) * (size_t) eb_table_floats());
}

// ---- stats for the UI -----------------------------------------------------------
EB_EXPORT int eb_active_voices (Instance* in) { return in->engine.activeVoices(); }
EB_EXPORT float eb_take_peak (Instance* in) { return in->engine.takePeak(); }
EB_EXPORT int eb_sustain_down (Instance* in) { return in->engine.sustainDown() ? 1 : 0; }
EB_EXPORT double eb_wheel_value (Instance* in) { return in->engine.modWheelValue(); }
EB_EXPORT float* eb_op_activity (Instance* in) { in->engine.takeOpActivity (in->scratch); return in->scratch; }
EB_EXPORT int eb_active_mask (Instance* in)
{
    int m = 0;
    for (int k = 0; k < kNumOps; ++k) if (in->engine.opActive (k)) m |= 1 << k;
    return m;
}
EB_EXPORT double eb_lfo_value (Instance* in, int l) { return in->engine.lfoValue (l); }
EB_EXPORT double eb_take_gr (Instance* in) { return in->engine.takeGainReduction(); }
EB_EXPORT void eb_scope (Instance* in, int op, float* out, int count, int stride) { in->engine.copyScope (op, out, count, stride); }
