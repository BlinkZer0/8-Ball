#pragma once
// ============================================================================
//  The parameter table, in plain C++ (no JUCE) so the DSP core and the
//  WebAssembly build share it. Params.h wraps it for the plugin (APVTS) and
//  vst/ui/js/params.js mirrors it by hand; EightBallTests --dump-params and
//  tests/check-params.ps1 fail on any difference.
//
//  Rules (house style): append-only. Indices and IDs of existing parameters
//  never change, new ones go at the end and default to neutral, so every
//  preset and project keeps loading. The whole table is defined and frozen in
//  milestone 1; parameters for later milestones exist but do nothing yet.
//
//  Everything that is a list of numbers a host lane can't usefully automate
//  (harmonic editor partials, drawn shapes, multi-point envelopes, drawn LFO
//  shapes) is NOT here: it lives in the Model (dsp/Model.h) and travels in
//  presets and project state as named blocks.
// ============================================================================
#include <cmath>
#include <string>
#include <vector>

namespace eightball
{
constexpr int kNumOps      = 8;
constexpr int kNumFilters  = 3;
constexpr int kNumLfos     = 4;
constexpr int kNumModSlots = 16;
constexpr int kNumFx       = 7;
constexpr int kNumOutputs  = 4;   // output column: Filter 1, Filter 2, Filter 3, Dry

constexpr int kOpFields  = 17;
constexpr int kFltFields = 10;
constexpr int kLfoFields = 8;
constexpr int kModFields = 4;

enum ParamIndex
{
    // ---- global ------------------------------------------------------------
    master, poly, voiceMode, portaOn, portaTime, oversample, bendRange,
    // ---- operators: op k field f = op1Wave + k * kOpFields + f ----------------
    op1Wave,
    opLast = op1Wave + kNumOps * kOpFields - 1,
    // ---- matrix: pm[s][d] = pm11 + s * 8 + d  ("op s modulates op d") --------
    pm11,
    pmLast = pm11 + kNumOps * kNumOps - 1,
    rm11,
    rmLast = rm11 + kNumOps * kNumOps - 1,
    // ---- output column: out[k][j] = out1F1 + k * 4 + j (F1, F2, F3, Dry) -----
    out1F1,
    outLast = out1F1 + kNumOps * kNumOutputs - 1,
    // ---- filters: flt f field g = flt1On + f * kFltFields + g -----------------
    flt1On,
    fltLast = flt1On + kNumFilters * kFltFields - 1,
    fltRouting,
    // ---- LFOs: lfo l field g = lfo1On + l * kLfoFields + g --------------------
    lfo1On,
    lfoLast = lfo1On + kNumLfos * kLfoFields - 1,
    // ---- FX ----------------------------------------------------------------
    dstOn, dstType, dstDrive, dstTone, dstMix, dstOut,
    choOn, choRate, choDepth, choDelay, choFeedback, choSpread, choMix,
    phaOn, phaRate, phaDepth, phaStages, phaFeedback, phaCenter, phaMix,
    dlyOn, dlyTime, dlySync, dlyDiv, dlyFeedback, dlyPingPong, dlyTone, dlyMix,
    revOn, revSize, revDecay, revDamp, revPreDelay, revWidth, revMix,
    eqOn, eqLowCut, eqHighCut, eqLowGain, eqLowFreq, eqMidGain, eqMidFreq, eqMidQ, eqHighGain, eqHighFreq, eqMix,
    cmpOn, cmpThresh, cmpRatio, cmpAttack, cmpRelease, cmpMakeup, cmpLimit, cmpMix,
    fxOrder1,
    fxOrderLast = fxOrder1 + kNumFx - 1,
    // ---- global mod matrix: slot s field g = mod1On + s * kModFields + g -------
    //      (last in the table: its destination list is "every Float parameter
    //       before it", so appending parameters later appends destinations)
    mod1On,
    modLast = mod1On + kNumModSlots * kModFields - 1,
    // ---- appended in milestone 5 (not a mod destination: after the slots) ----
    presetGain,          // level trim in dB, after the FX, before the master (level-matched factory presets)
    kNumParams
};

enum OpField  { fWave, fRatio, fFine, fFixed, fHz, fKeyTrack, fLevel, fPan, fVel, fUnison, fDetune, fSpread,
                fPhaseReset, fMute, fSolo, fPitchEnvAmt, fModEnvAmt };
enum FltField { gOn, gType, gSlope, gCutoff, gReso, gDrive, gKeyTrack, gEnvAmt, gVel, gMix };
enum LfoField { hOn, hWave, hRate, hSync, hDiv, hDepth, hDelay, hPhase };
enum ModField { mOn, mSrc, mDst, mAmt };
enum OutBus   { busF1, busF2, busF3, busDry };

inline int opParam  (int op, int field)    { return op1Wave + op * kOpFields + field; }
inline int pmParam  (int src, int dst)     { return pm11 + src * kNumOps + dst; }
inline int rmParam  (int src, int dst)     { return rm11 + src * kNumOps + dst; }
inline int outParam (int op, int bus)      { return out1F1 + op * kNumOutputs + bus; }
inline int fltParam (int flt, int field)   { return flt1On + flt * kFltFields + field; }
inline int lfoParam (int lfo, int field)   { return lfo1On + lfo * kLfoFields + field; }
inline int modParam (int slot, int field)  { return mod1On + slot * kModFields + field; }
inline int fxOrderParam (int pos)          { return fxOrder1 + pos; }

enum class Kind { Float, Bool, Choice, Int };
enum class Unit { None, Seconds, Ms, Hz, LfoHz, Semitones, Cents, Percent, BipolarPercent, Decibels, Degrees, Ratio, Pan };

struct PDef
{
    std::string id, name;
    Kind kind = Kind::Float;
    float min = 0, max = 1, def = 0;
    float step = 0;            // Float: snap interval (0 = continuous); shown in the UI, host range interval
    Unit unit = Unit::None;
    bool log = false;
    std::vector<std::string> choices;
    bool noPreset = false;     // never stored in presets (master)
};

// Choice indices used by the engine (must match the lists below and params.js)
enum OpWave    { waveSine, waveSaw, waveSquare, waveTriangle, waveHalfSine, waveNoise, waveCustom, kNumOpWaves };
enum VoiceMode { modePoly, modeMono, modeLegato };
enum FltType   { fltLowpass, fltBandpass, fltHighpass };
enum FltRoute  { routeParallel, routeSeries, routeTwoIntoThree };
enum LfoWave   { lfoSine, lfoTriangle, lfoSaw, lfoSquare, lfoSampleHold, lfoDrawn };
enum FxUnit    { fxDistortion, fxChorus, fxPhaser, fxDelay, fxReverb, fxEq, fxCompressor };
enum DriveType { driveSoft, driveHard, driveFold, driveCrush };

// Mod sources: None, LFO 1-4, Op 1-8 amp env, Op 1-8 pitch env, Op 1-8 mod env,
// Filter 1-3 cutoff env, Filter 1-3 level env, Velocity, Mod Wheel, Aftertouch, Pitch Bend, Key
enum ModSource
{
    srcNone, srcLfo1, srcLfoLast = srcLfo1 + kNumLfos - 1,
    srcOpAmpEnv1, srcOpAmpEnvLast = srcOpAmpEnv1 + kNumOps - 1,
    srcOpPitchEnv1, srcOpPitchEnvLast = srcOpPitchEnv1 + kNumOps - 1,
    srcOpModEnv1, srcOpModEnvLast = srcOpModEnv1 + kNumOps - 1,
    srcFltCutEnv1, srcFltCutEnvLast = srcFltCutEnv1 + kNumFilters - 1,
    srcFltLvlEnv1, srcFltLvlEnvLast = srcFltLvlEnv1 + kNumFilters - 1,
    srcVelocity, srcModWheel, srcAftertouch, srcPitchBend, srcKey,
    kNumModSources
};

inline const std::vector<std::string>& lfoDivChoices()
{
    static const std::vector<std::string> c { "1/1", "1/2D", "1/2", "1/2T", "1/4D", "1/4", "1/4T", "1/8D", "1/8", "1/8T",
                                              "1/16D", "1/16", "1/16T", "1/32", "1/32T" };
    return c;
}
constexpr int kNumLfoDivs = 15;
// Synced divisions in quarter-note beats (order = lfoDivChoices)
constexpr double kLfoDivBeats[kNumLfoDivs] = { 4.0, 3.0, 2.0, 4.0 / 3.0, 1.5, 1.0, 2.0 / 3.0, 0.75, 0.5, 1.0 / 3.0,
                                               0.375, 0.25, 1.0 / 6.0, 0.125, 1.0 / 12.0 };

inline std::vector<std::string> modSourceChoices()
{
    std::vector<std::string> c { "None" };
    for (int i = 1; i <= kNumLfos; ++i)    c.push_back ("LFO " + std::to_string (i));
    for (int i = 1; i <= kNumOps; ++i)     c.push_back ("Op " + std::to_string (i) + " Amp Env");
    for (int i = 1; i <= kNumOps; ++i)     c.push_back ("Op " + std::to_string (i) + " Pitch Env");
    for (int i = 1; i <= kNumOps; ++i)     c.push_back ("Op " + std::to_string (i) + " Mod Env");
    for (int i = 1; i <= kNumFilters; ++i) c.push_back ("Filter " + std::to_string (i) + " Cutoff Env");
    for (int i = 1; i <= kNumFilters; ++i) c.push_back ("Filter " + std::to_string (i) + " Level Env");
    c.insert (c.end(), { "Velocity", "Mod Wheel", "Aftertouch", "Pitch Bend", "Key" });
    return c;
}

// The table. Built once; allocation happens at start-up only.
inline const std::vector<PDef>& paramTable()
{
    static const std::vector<PDef> table = []
    {
        std::vector<PDef> d;
        auto add = [&d] (std::string id, std::string name, Kind kind, float mn, float mx, float def,
                         Unit unit = Unit::None, bool log = false, float step = 0.0f)
        {
            PDef p; p.id = std::move (id); p.name = std::move (name); p.kind = kind; p.min = mn; p.max = mx; p.def = def;
            p.unit = unit; p.log = log; p.step = step;
            d.push_back (std::move (p));
        };
        auto fl = [&add] (std::string id, std::string name, float mn, float mx, float def, Unit unit = Unit::None, bool log = false, float step = 0.0f)
        { add (std::move (id), std::move (name), Kind::Float, mn, mx, def, unit, log, step); };
        auto bo = [&add] (std::string id, std::string name, float def) { add (std::move (id), std::move (name), Kind::Bool, 0, 1, def); };
        auto in = [&add] (std::string id, std::string name, int mn, int mx, int def, Unit unit = Unit::None)
        { add (std::move (id), std::move (name), Kind::Int, (float) mn, (float) mx, (float) def, unit); };
        auto ch = [&d] (std::string id, std::string name, std::vector<std::string> choices, int def)
        {
            PDef p; p.id = std::move (id); p.name = std::move (name); p.kind = Kind::Choice; p.min = 0;
            p.max = (float) (choices.size() - 1); p.def = (float) def; p.choices = std::move (choices);
            d.push_back (std::move (p));
        };
        const auto S = [] (int n) { return std::to_string (n); };

        // ---- global
        fl ("master", "Master", 0, 1, 0.7f, Unit::Percent);
        d.back().noPreset = true;
        in ("poly", "Polyphony", 1, 32, 16);
        ch ("voiceMode", "Voice Mode", { "Poly", "Mono", "Legato" }, 0);
        bo ("portaOn", "Portamento", 0);
        fl ("portaTime", "Portamento Time", 0.001f, 5.0f, 0.1f, Unit::Seconds, true);
        bo ("oversample", "2x Oversampling", 0);
        in ("bendRange", "Pitch Bend Range", 0, 24, 2, Unit::Semitones);

        // ---- operators
        for (int k = 1; k <= kNumOps; ++k)
        {
            const std::string o = "op" + S (k), n = "Op " + S (k) + " ";
            ch (o + "Wave", n + "Wave", { "Sine", "Saw", "Square", "Triangle", "Half-sine", "Noise", "Custom" }, 0);
            fl (o + "Ratio", n + "Ratio", 0.5f, 32.0f, 1.0f, Unit::Ratio, false, 0.5f);
            fl (o + "Fine", n + "Fine", -100, 100, 0, Unit::Cents, false, 1.0f);
            bo (o + "Fixed", n + "Fixed", 0);
            fl (o + "Hz", n + "Frequency", 0.1f, 20000.0f, 440.0f, Unit::Hz, true);
            fl (o + "KeyTrack", n + "Key Track", 0, 2, 1, Unit::Percent);
            fl (o + "Level", n + "Level", 0, 1, 1, Unit::Percent);
            fl (o + "Pan", n + "Pan", -1, 1, 0, Unit::Pan);
            fl (o + "Vel", n + "Velocity", 0, 1, 0.5f, Unit::Percent);
            in (o + "Unison", n + "Unison", 1, 8, 1);
            fl (o + "Detune", n + "Detune", 0, 100, 10, Unit::Cents);
            fl (o + "Spread", n + "Spread", 0, 1, 0.5f, Unit::Percent);
            bo (o + "PhaseReset", n + "Phase Reset", 1);
            bo (o + "Mute", n + "Mute", 0);
            bo (o + "Solo", n + "Solo", 0);
            fl (o + "PitchEnvAmt", n + "Pitch Env Amount", -48, 48, 12, Unit::Semitones);
            fl (o + "ModEnvAmt", n + "Mod Env Amount", 0, 1, 1, Unit::Percent);
        }
        // ---- matrix
        for (int s = 1; s <= kNumOps; ++s)
            for (int t = 1; t <= kNumOps; ++t)
                fl ("pm" + S (s) + S (t), "PM " + S (s) + (s == t ? " Feedback" : " > " + S (t)), 0, 1, 0, Unit::Percent);
        for (int s = 1; s <= kNumOps; ++s)
            for (int t = 1; t <= kNumOps; ++t)
                fl ("rm" + S (s) + S (t), "Ring " + S (s) + (s == t ? " Self" : " > " + S (t)), 0, 1, 0, Unit::Percent);
        for (int k = 1; k <= kNumOps; ++k)
        {
            const char* bus[kNumOutputs] { "F1", "F2", "F3", "Dry" };
            const char* busName[kNumOutputs] { "Filter 1", "Filter 2", "Filter 3", "Dry" };
            for (int j = 0; j < kNumOutputs; ++j)
                fl ("out" + S (k) + bus[j], "Op " + S (k) + " > " + busName[j], 0, 1, (k == 1 && j == busDry) ? 1.0f : 0.0f, Unit::Percent);
        }
        // ---- filters
        for (int f = 1; f <= kNumFilters; ++f)
        {
            const std::string o = "flt" + S (f), n = "Filter " + S (f) + " ";
            bo (o + "On", n + "On", 1);
            ch (o + "Type", n + "Type", { "Low-pass", "Band-pass", "High-pass" }, 0);
            ch (o + "Slope", n + "Slope", { "12 dB", "24 dB" }, 0);
            fl (o + "Cutoff", n + "Cutoff", 20, 20000, 2000, Unit::Hz, true);
            fl (o + "Reso", n + "Resonance", 0, 1, 0.1f, Unit::Percent);
            fl (o + "Drive", n + "Drive", 0, 1, 0, Unit::Percent);
            fl (o + "KeyTrack", n + "Key Track", 0, 1, 0, Unit::Percent);
            fl (o + "EnvAmt", n + "Env Amount", -1, 1, 0, Unit::BipolarPercent);
            fl (o + "Vel", n + "Velocity", -1, 1, 0, Unit::BipolarPercent);
            fl (o + "Mix", n + "Mix", 0, 1, 1, Unit::Percent);
        }
        ch ("fltRouting", "Filter Routing", { "Parallel", "Series 1>2>3", "1+2 > 3" }, 0);
        // ---- LFOs
        for (int l = 1; l <= kNumLfos; ++l)
        {
            const std::string o = "lfo" + S (l), n = "LFO " + S (l) + " ";
            bo (o + "On", n + "On", 0);
            ch (o + "Wave", n + "Wave", { "Sine", "Triangle", "Saw", "Square", "S&H", "Drawn" }, 0);
            fl (o + "Rate", n + "Rate", 0.02f, 40.0f, 2.0f, Unit::LfoHz, true);
            bo (o + "Sync", n + "Sync", 0);
            ch (o + "Div", n + "Division", lfoDivChoices(), 8);
            fl (o + "Depth", n + "Depth", 0, 1, 1, Unit::Percent);
            fl (o + "Delay", n + "Delay", 0, 5, 0, Unit::Seconds);
            fl (o + "Phase", n + "Phase", 0, 360, 0, Unit::Degrees);
        }
        // ---- FX
        bo ("dstOn", "Distortion On", 0);
        ch ("dstType", "Distortion Type", { "Soft", "Hard", "Fold", "Crush" }, 0);
        fl ("dstDrive", "Distortion Drive", 0, 1, 0.3f, Unit::Percent);
        fl ("dstTone", "Distortion Tone", 0, 1, 1, Unit::Percent);
        fl ("dstMix", "Distortion Mix", 0, 1, 1, Unit::Percent);
        fl ("dstOut", "Distortion Output", -24, 6, 0, Unit::Decibels);

        bo ("choOn", "Chorus On", 0);
        fl ("choRate", "Chorus Rate", 0.02f, 10.0f, 0.8f, Unit::LfoHz, true);
        fl ("choDepth", "Chorus Depth", 0, 1, 0.5f, Unit::Percent);
        fl ("choDelay", "Chorus Delay", 1, 30, 7, Unit::Ms);
        fl ("choFeedback", "Chorus Feedback", -0.95f, 0.95f, 0, Unit::BipolarPercent);
        fl ("choSpread", "Chorus Spread", 0, 1, 1, Unit::Percent);
        fl ("choMix", "Chorus Mix", 0, 1, 0.5f, Unit::Percent);

        bo ("phaOn", "Phaser On", 0);
        fl ("phaRate", "Phaser Rate", 0.02f, 10.0f, 0.5f, Unit::LfoHz, true);
        fl ("phaDepth", "Phaser Depth", 0, 1, 0.7f, Unit::Percent);
        ch ("phaStages", "Phaser Stages", { "4", "8", "12" }, 1);
        fl ("phaFeedback", "Phaser Feedback", -0.95f, 0.95f, 0.3f, Unit::BipolarPercent);
        fl ("phaCenter", "Phaser Center", 0, 1, 0.5f, Unit::Percent);
        fl ("phaMix", "Phaser Mix", 0, 1, 0.5f, Unit::Percent);

        bo ("dlyOn", "Delay On", 0);
        fl ("dlyTime", "Delay Time", 1, 2000, 375, Unit::Ms, true);
        bo ("dlySync", "Delay Sync", 0);
        ch ("dlyDiv", "Delay Division", lfoDivChoices(), 8);
        fl ("dlyFeedback", "Delay Feedback", 0, 0.95f, 0.4f, Unit::Percent);
        bo ("dlyPingPong", "Delay Ping-pong", 0);
        fl ("dlyTone", "Delay Tone", 0, 1, 0.6f, Unit::Percent);
        fl ("dlyMix", "Delay Mix", 0, 1, 0.3f, Unit::Percent);

        bo ("revOn", "Reverb On", 0);
        fl ("revSize", "Reverb Size", 0, 1, 0.6f, Unit::Percent);
        fl ("revDecay", "Reverb Decay", 0, 1, 0.5f, Unit::Percent);
        fl ("revDamp", "Reverb Damping", 0, 1, 0.5f, Unit::Percent);
        fl ("revPreDelay", "Reverb Pre-delay", 0, 200, 10, Unit::Ms);
        fl ("revWidth", "Reverb Width", 0, 1, 1, Unit::Percent);
        fl ("revMix", "Reverb Mix", 0, 1, 0.25f, Unit::Percent);

        bo ("eqOn", "EQ On", 0);
        fl ("eqLowCut", "EQ Low Cut", 20, 2000, 20, Unit::Hz, true);
        fl ("eqHighCut", "EQ High Cut", 1000, 20000, 20000, Unit::Hz, true);
        fl ("eqLowGain", "EQ Low Gain", -18, 18, 0, Unit::Decibels);
        fl ("eqLowFreq", "EQ Low Freq", 40, 1000, 200, Unit::Hz, true);
        fl ("eqMidGain", "EQ Mid Gain", -18, 18, 0, Unit::Decibels);
        fl ("eqMidFreq", "EQ Mid Freq", 200, 8000, 1000, Unit::Hz, true);
        fl ("eqMidQ", "EQ Mid Q", 0.3f, 8, 1, Unit::None);
        fl ("eqHighGain", "EQ High Gain", -18, 18, 0, Unit::Decibels);
        fl ("eqHighFreq", "EQ High Freq", 1000, 16000, 5000, Unit::Hz, true);
        fl ("eqMix", "EQ Mix", 0, 1, 1, Unit::Percent);

        bo ("cmpOn", "Compressor On", 0);
        fl ("cmpThresh", "Compressor Threshold", -60, 0, -12, Unit::Decibels);
        fl ("cmpRatio", "Compressor Ratio", 1, 20, 4, Unit::Ratio);
        fl ("cmpAttack", "Compressor Attack", 0.1f, 200, 10, Unit::Ms, true);
        fl ("cmpRelease", "Compressor Release", 5, 2000, 100, Unit::Ms, true);
        fl ("cmpMakeup", "Compressor Makeup", 0, 24, 0, Unit::Decibels);
        bo ("cmpLimit", "Limiter", 0);
        fl ("cmpMix", "Compressor Mix", 0, 1, 1, Unit::Percent);

        for (int p = 0; p < kNumFx; ++p)
            ch ("fxOrder" + S (p + 1), "FX Slot " + S (p + 1), { "Distortion", "Chorus", "Phaser", "Delay", "Reverb", "EQ", "Compressor" }, p);

        // ---- global mod matrix. Destinations: every Float parameter before this point except master.
        std::vector<std::string> dst { "None" };
        for (const auto& p : d)
            if (p.kind == Kind::Float && ! p.noPreset) dst.push_back (p.name);
        for (int s = 1; s <= kNumModSlots; ++s)
        {
            const std::string o = "mod" + S (s), n = "Mod " + S (s) + " ";
            bo (o + "On", n + "On", 1);
            ch (o + "Src", n + "Source", modSourceChoices(), 0);
            ch (o + "Dst", n + "Destination", dst, 0);
            fl (o + "Amt", n + "Amount", -1, 1, 0, Unit::BipolarPercent);
        }
        // ---- milestone 5
        fl ("presetGain", "Preset Gain", -24, 12, 0, Unit::Decibels);
        return d;
    }();
    return table;
}

// Mod destination choice index -> parameter index (0 = none -> -1). Same rule as the list above.
inline const std::vector<int>& modDestParams()
{
    static const std::vector<int> v = []
    {
        std::vector<int> out { -1 };
        const auto& t = paramTable();
        for (int i = 0; i < mod1On; ++i)
            if (t[(size_t) i].kind == Kind::Float && ! t[(size_t) i].noPreset) out.push_back (i);
        return out;
    }();
    return v;
}

// value <-> 0..1 (the same mapping the host and params.js use)
inline double paramToNorm (const PDef& d, double v)
{
    if (d.log) { const double n = std::log (v / d.min) / std::log (d.max / d.min); return n < 0 ? 0 : (n > 1 ? 1 : n); }
    const double n = (v - d.min) / (d.max - d.min);
    return n < 0 ? 0 : (n > 1 ? 1 : n);
}
inline double paramFromNorm (const PDef& d, double n)
{
    n = n < 0 ? 0 : (n > 1 ? 1 : n);
    return d.log ? d.min * std::pow (d.max / d.min, n) : d.min + n * (d.max - d.min);
}
} // namespace eightball
