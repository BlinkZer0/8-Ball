// Engine tools for the console test app: --bench, --loudness, --render
#include "TestRender.h"

using namespace eightball;
using namespace eightball::test;

// CPU: 16 voices x 8 operators (the brief's target), measured as % of one core for 10 s of audio.
int runBench()
{
    struct Case { const char* name; int unison; bool os; int ops; };
    const Case cases[] {
        { "16 voices x 8 ops, unison 1 (all 8 ops carriers + 4 PM cells)", 1, false, 8 },
        { "16 voices x 8 ops, unison 1, 2x oversampling", 1, true, 8 },
        { "16 voices x 8 ops, unison 4", 4, false, 8 },
        { "16 voices x 2 ops (a classic 2-op FM patch)", 1, false, 2 },
    };
    for (const auto& c : cases)
    {
        Patch p;
        p.set ("poly", 16).set ("oversample", c.os ? 1.0f : 0.0f);
        for (int k = 0; k < c.ops; ++k)
        {
            p.set (opParam (k, fUnison), (float) c.unison);
            p.set (opParam (k, fRatio), (float) (k % 4 + 1));
            p.set (outParam (k, busDry), 0.5f);
        }
        if (c.ops >= 2) p.set ("pm21", 0.5f);
        if (c.ops >= 4) p.set ("pm43", 0.5f).set ("pm11", 0.3f);
        if (c.ops >= 8) p.set ("pm65", 0.4f).set ("pm87", 0.4f);
        // long sustain so all 16 voices stay busy
        for (int k = 0; k < kNumOps; ++k) p.model.envs[(size_t) opEnvIndex (k, envAmp)] = EnvSpec::adsr (0.01f, 0.1f, 1.0f, 0.5f);

        auto holder = std::make_unique<ModelHolder> (p.model);
        auto enginePtr = std::make_unique<SynthEngine>();
        auto& engine = *enginePtr;
        engine.setParamValues (p.v.data());
        engine.prepare (kSr);
        engine.setModel (&holder->model);
        engine.settleParams();
        std::array<float, 512> L {}, R {};
        for (int n = 48; n < 64; ++n) engine.noteOn (n, 100);
        const int blocks = (int) (kSr * 10 / 512);
        const auto t0 = juce::Time::getMillisecondCounterHiRes();
        for (int b = 0; b < blocks; ++b)
        {
            engine.setParamValues (p.v.data());
            engine.setTransport (120.0, 0.0, false);
            engine.render (L.data(), R.data(), 512);
        }
        const double ms = juce::Time::getMillisecondCounterHiRes() - t0;
        std::printf ("%-62s %6.0f ms for 10 s of audio  (%.1f%% of one core, %d voices)\n",
                     c.name, ms, ms / 100.0, engine.activeVoices());
    }
    return 0;
}

// Loudest 100 ms window (RMS) while a chord (or one note for bass / mono presets) is held
// for 3 s at velocity 100, with master at 1 (the preset's own gain staging is what is measured).
int runLoudness()
{
    PresetManager pm;
    std::printf ("[\n");
    const auto& f = pm.factory();
    for (size_t pi = 0; pi < f.size(); ++pi)
    {
        Patch p;
        applyPresetData (p.v, f[pi]);
        p.model = f[pi].model;
        p.v[master] = 1.0f;
        const bool single = f[pi].category.containsIgnoreCase ("Bass") || p.v[voiceMode] >= 0.5f;
        std::vector<Event> ev;
        if (single) ev.push_back (on (1, 36));
        else { ev.push_back (on (1, 60)); ev.push_back (on (1, 64)); ev.push_back (on (1, 67)); }
        auto r = render (p, (int) (kSr * 3 / kBlock), ev);
        const auto m = r.mono();
        double best = 0;
        for (size_t i = 0; i + 4800 <= m.size(); i += 2400) best = std::max (best, rms (m, i, i + 4800));
        std::printf ("  { \"index\": %d, \"name\": \"%s\", \"category\": \"%s\", \"rms\": %.5f, \"dB\": %.2f, \"peak\": %.3f }%s\n",
                     (int) pi, f[pi].name.toRawUTF8(), f[pi].category.toRawUTF8(), best, dB (best), r.peak,
                     pi + 1 < f.size() ? "," : "");
    }
    std::printf ("]\n");
    return 0;
}

// Renders a factory preset (by "Category/Name" or name) to a WAV: a note held for 2/3 of the
// time, then released. For listening to DSP changes without opening a DAW.
int runRender (const juce::String& preset, const juce::File& out, double seconds, int note)
{
    PresetManager pm;
    const int idx = pm.findFactory (preset);
    if (idx < 0) { std::printf ("unknown preset: %s\n", preset.toRawUTF8()); return 2; }
    Patch p;
    applyPresetData (p.v, pm.factory()[(size_t) idx]);
    p.model = pm.factory()[(size_t) idx].model;
    const int blocks = (int) (kSr * seconds / kBlock);
    auto r = render (p, blocks, { on (1, note), off (blocks * 2 / 3, note) });
    if (! writeWav (out, r)) { std::printf ("couldn't write %s\n", out.getFullPathName().toRawUTF8()); return 2; }
    std::printf ("wrote %s (%s, note %d, %.1f s, peak %.3f)\n", out.getFullPathName().toRawUTF8(),
                 pm.factory()[(size_t) idx].name.toRawUTF8(), note, seconds, r.peak);
    return 0;
}
