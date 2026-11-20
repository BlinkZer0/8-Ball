#pragma once
// Offline rendering + analysis helpers shared by the console tests and tools.
#include <juce_core/juce_core.h>
#include <juce_audio_formats/juce_audio_formats.h>
#include <functional>
#include <vector>
#include "Params.h"
#include "PresetManager.h"
#include "SynthEngine.h"

namespace eightball::test
{
constexpr double kSr = 48000.0;
constexpr int kBlock = 128;

using Values = std::array<float, kNumParams>;

inline Values defaultValues()
{
    Values v {};
    for (int i = 0; i < kNumParams; ++i) v[(size_t) i] = paramDef (i).def;
    return v;
}

inline void applyPresetData (Values& v, const PresetData& p)
{
    for (int i = 0; i < kNumParams; ++i)
        if (i != master && ! std::isnan (p.values[(size_t) i])) v[(size_t) i] = p.values[(size_t) i];
}

inline int paramIndex (const juce::String& id) { return paramIndexForId (id); }

// values.set("op1Ratio", 2)
struct Patch
{
    Values v = defaultValues();
    ModelData model;
    Patch& set (const char* id, float value)
    {
        const int i = paramIndex (id);
        jassert (i >= 0);
        if (i >= 0) v[(size_t) i] = value;
        return *this;
    }
    Patch& set (int index, float value) { v[(size_t) index] = value; return *this; }
    Patch& preset (const PresetManager& pm, const juce::String& name)
    {
        const int i = pm.findFactory (name);
        jassert (i >= 0);
        if (i >= 0) { applyPresetData (v, pm.factory()[(size_t) i]); model = pm.factory()[(size_t) i].model; }
        return *this;
    }
};

struct Event { int block; std::function<void (SynthEngine&)> fn; };
inline Event on (int block, int note, int vel = 100) { return { block, [note, vel] (SynthEngine& e) { e.noteOn (note, vel); } }; }
inline Event off (int block, int note) { return { block, [note] (SynthEngine& e) { e.noteOff (note); } }; }

struct Render
{
    std::vector<float> L, R;
    double peak = 0;
    int activeAtEnd = 0;
    double sr = kSr;
    std::vector<float> mono() const
    {
        std::vector<float> m (L.size());
        for (size_t i = 0; i < L.size(); ++i) m[i] = 0.5f * (L[i] + R[i]);
        return m;
    }
};

// A Model built from a Patch's ModelData (tables baked here; lives as long as the holder)
struct ModelHolder
{
    std::array<Wavetable, kNumOps> tables;
    Model model;
    explicit ModelHolder (const ModelData& d)
    {
        for (int k = 0; k < kNumOps; ++k)
        {
            buildWavetable (d.waves[(size_t) k], tables[(size_t) k]);
            model.tables[(size_t) k] = &tables[(size_t) k];
        }
        model.envs = d.envs;
        model.lfoShapes = d.lfoShapes;
    }
};

// Renders `blocks` x kBlock samples. Parameter changes scheduled through events take
// effect at the start of that block (`patch.v` is re-read every block).
inline Render render (Patch& patch, int blocks, const std::vector<Event>& events = {}, double bpm = 120.0, double sr = kSr)
{
    // heap: the engine (32 voices) and 8 wavetables are too big for the stack
    auto holder = std::make_unique<ModelHolder> (patch.model);
    auto enginePtr = std::make_unique<SynthEngine>();
    auto& engine = *enginePtr;
    engine.setParamValues (patch.v.data());
    engine.prepare (sr);
    engine.setModel (&holder->model);
    engine.settleParams();

    Render r;
    r.sr = sr;
    r.L.resize ((size_t) blocks * kBlock);
    r.R.resize ((size_t) blocks * kBlock);
    for (int b = 0; b < blocks; ++b)
    {
        for (const auto& ev : events) if (ev.block == b) ev.fn (engine);
        engine.setParamValues (patch.v.data());
        engine.setTransport (bpm, 0.0, false);
        engine.render (r.L.data() + b * kBlock, r.R.data() + b * kBlock, kBlock);
    }
    for (size_t i = 0; i < r.L.size(); ++i) r.peak = std::max (r.peak, (double) std::max (std::abs (r.L[i]), std::abs (r.R[i])));
    r.activeAtEnd = engine.activeVoices();
    return r;
}

inline double rms (const std::vector<float>& x, size_t from, size_t to)
{
    to = std::min (to, x.size());
    if (to <= from) return 0;
    double acc = 0;
    for (size_t i = from; i < to; ++i) acc += (double) x[i] * x[i];
    return std::sqrt (acc / (double) (to - from));
}
inline double rmsSec (const std::vector<float>& x, double t0, double t1, double sr = kSr) { return rms (x, (size_t) (t0 * sr), (size_t) (t1 * sr)); }

inline double dB (double a) { return 20.0 * std::log10 (std::max (a, 1e-12)); }

// Magnitude at one frequency (Goertzel, Hann window), normalised so a full-scale sine reads about 0.5
inline double magAt (const std::vector<float>& x, size_t from, size_t to, double hz, double sr = kSr)
{
    to = std::min (to, x.size());
    const size_t n = to - from;
    const double w = kTwoPi * hz / sr;
    const double coef = 2.0 * std::cos (w);
    double s0 = 0, s1 = 0, s2 = 0;
    for (size_t i = 0; i < n; ++i)
    {
        const double win = 0.5 - 0.5 * std::cos (kTwoPi * (double) i / (double) n);
        s0 = x[from + i] * win + coef * s1 - s2;
        s2 = s1; s1 = s0;
    }
    const double re = s1 - s2 * std::cos (w), im = s2 * std::sin (w);
    return std::sqrt (re * re + im * im) / (double) n * 2.0;
}

// Frequency of the strongest component between lo and hi (coarse scan, then refine)
inline double peakFreq (const std::vector<float>& x, size_t from, size_t to, double lo, double hi, double sr = kSr)
{
    double best = lo, bestMag = -1;
    const double step = std::max (1.0, (hi - lo) / 400.0);
    for (double f = lo; f <= hi; f += step)
    {
        const double m = magAt (x, from, to, f, sr);
        if (m > bestMag) { bestMag = m; best = f; }
    }
    for (double f = best - step; f <= best + step; f += step / 40.0)
    {
        const double m = magAt (x, from, to, f, sr);
        if (m > bestMag) { bestMag = m; best = f; }
    }
    return best;
}

// Frequency from rising zero crossings over a steady window (pure-ish tones)
inline double zeroCrossFreq (const std::vector<float>& x, size_t from, size_t to, double sr = kSr)
{
    to = std::min (to, x.size());
    int crossings = 0;
    size_t first = 0, last = 0;
    for (size_t i = from + 1; i < to; ++i)
        if (x[i - 1] <= 0 && x[i] > 0) { if (crossings == 0) first = i; last = i; ++crossings; }
    if (crossings < 2) return 0;
    return (crossings - 1) * sr / (double) (last - first);
}

// Largest sample-to-sample step (click detector)
inline double maxStep (const std::vector<float>& x, size_t from = 0, size_t to = SIZE_MAX)
{
    to = std::min (to, x.size());
    double m = 0;
    for (size_t i = from + 1; i < to; ++i) m = std::max (m, (double) std::abs (x[i] - x[i - 1]));
    return m;
}

inline bool writeWav (const juce::File& f, const Render& r)
{
    f.deleteFile();
    juce::WavAudioFormat fmt;
    std::unique_ptr<juce::OutputStream> out = std::make_unique<juce::FileOutputStream> (f);
    const auto opts = juce::AudioFormatWriterOptions{}.withSampleRate (r.sr).withNumChannels (2).withBitsPerSample (24);
    auto w = fmt.createWriterFor (out, opts);
    if (w == nullptr) return false;
    juce::AudioBuffer<float> b (2, (int) r.L.size());
    for (int i = 0; i < (int) r.L.size(); ++i) { b.setSample (0, i, r.L[(size_t) i]); b.setSample (1, i, r.R[(size_t) i]); }
    return w->writeFromAudioSampleBuffer (b, 0, b.getNumSamples());
}
} // namespace eightball::test
