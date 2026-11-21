// Console tests (no audio device / window needed).
// Build + run:  cmake --build <build> --config Release --target EightBallTests
//   EightBallTests.exe                 parameter table, presets, files, engine checks
//   EightBallTests.exe --dump-params   the C++ parameter table as JSON (tests/check-params.ps1)
//   EightBallTests.exe --bench [case]  CPU: 16 voices x 8 operators (one case only with an index)
//   EightBallTests.exe --loudness      loudness of every factory preset (level matching)
//   EightBallTests.exe --render "<Category/Name>" out.wav [seconds] [note]
//   EightBallTests.exe --host-check "<path to Eight Ball.vst3>"
//   EightBallTests.exe --presets <factory.json> <any of the above>   use that factory file instead of the built-in one
#include "TestRender.h"

using namespace eightball;
using namespace eightball::test;

int failures = 0;
#define CHECK(cond) do { if (! (cond)) { ++failures; std::printf ("FAIL %s:%d  %s\n", __FILE__, __LINE__, #cond); } } while (0)
#define CHECKF(cond, ...) do { if (! (cond)) { ++failures; std::printf ("FAIL %s:%d  %s  ", __FILE__, __LINE__, #cond); std::printf (__VA_ARGS__); std::printf ("\n"); } } while (0)

int runEngineTests();
int runBench (int only);
int runLoudness();
int runRender (const juce::String& preset, const juce::File& out, double seconds, int note);
int runHostCheck (const juce::String& path);

static void paramTableTests()
{
    const auto& t = paramTable();
    std::printf ("parameters: %d\n", (int) t.size());
    CHECK ((int) t.size() == kNumParams);
    // index helpers land on the right IDs
    CHECK (paramDef (op1Wave).id == "op1Wave");
    CHECK (paramDef (opParam (7, fModEnvAmt)).id == "op8ModEnvAmt");
    CHECK (paramDef (pm11).id == "pm11" && paramDef (pmParam (2, 5)).id == "pm36");
    CHECK (paramDef (rm11).id == "rm11" && paramDef (rmLast).id == "rm88");
    CHECK (paramDef (out1F1).id == "out1F1" && paramDef (outParam (7, busDry)).id == "out8Dry");
    CHECK (paramDef (flt1On).id == "flt1On" && paramDef (fltParam (2, gMix)).id == "flt3Mix");
    CHECK (paramDef (fltRouting).id == "fltRouting");
    CHECK (paramDef (lfo1On).id == "lfo1On" && paramDef (lfoParam (3, hPhase)).id == "lfo4Phase");
    CHECK (paramDef (dstOn).id == "dstOn" && paramDef (cmpMix).id == "cmpMix");
    CHECK (paramDef (fxOrder1).id == "fxOrder1" && paramDef (fxOrderLast).id == "fxOrder7");
    CHECK (paramDef (mod1On).id == "mod1On" && paramDef (modParam (15, mAmt)).id == "mod16Amt");
    // unique ids
    for (int i = 0; i < kNumParams; ++i) CHECK (paramIndexForId (paramId (i)) == i);
    // defaults in range; neutral defaults for later milestones (everything off / zero)
    for (int i = 0; i < kNumParams; ++i) CHECK (t[(size_t) i].def >= t[(size_t) i].min && t[(size_t) i].def <= t[(size_t) i].max);
    for (int l = 0; l < kNumLfos; ++l) CHECK (paramDef (lfoParam (l, hOn)).def == 0);
    for (int s = 0; s < kNumModSlots; ++s) CHECK (paramDef (modParam (s, mSrc)).def == 0 && paramDef (modParam (s, mAmt)).def == 0);
    for (int i : { (int) dstOn, (int) choOn, (int) phaOn, (int) dlyOn, (int) revOn, (int) eqOn, (int) cmpOn }) CHECK (paramDef (i).def == 0);
    for (int p = 0; p < kNumFx; ++p) CHECK (paramDef (fxOrderParam (p)).def == (float) p);
    // the Init patch: op 1 to Dry, nothing else routed
    for (int k = 0; k < kNumOps; ++k)
        for (int j = 0; j < kNumOutputs; ++j)
            CHECK (paramDef (outParam (k, j)).def == ((k == 0 && j == busDry) ? 1.0f : 0.0f));
    // mod destinations: the choice list and the index list agree
    const auto& dst = paramDef (modParam (0, mDst)).choices;
    CHECK (dst.size() == modDestParams().size());
    for (size_t i = 1; i < dst.size(); ++i) CHECK (dst[i] == paramDef (modDestParams()[i]).name);
    CHECK (paramDef (modParam (0, mSrc)).choices.size() == (size_t) kNumModSources);
    CHECK (modDestParams().size() > 300);
    // master is never in presets
    CHECK (paramDef (master).noPreset);
}

static void presetTests()
{
    PresetManager pm;
    const auto& f = pm.factory();
    std::printf ("factory presets: %d\n", (int) f.size());
    CHECK (f.size() >= 8);
    juce::StringArray cats;
    for (const auto& p : f)
    {
        cats.addIfNotAlreadyThere (p.category);
        for (int i = 0; i < kNumParams; ++i)
        {
            const float v = p.values[(size_t) i];
            if (i == master) { CHECK (std::isnan (v)); continue; }
            if (! std::isnan (v)) CHECK (v >= paramDef (i).min && v <= paramDef (i).max);
        }
        CHECK (p.name.isNotEmpty());
    }
    std::printf ("categories: %s\n", cats.joinIntoString (", ").toRawUTF8());
    CHECK (pm.findFactory ("Init") >= 0);
    // "modDst" names a slot's destination by parameter id
    if (const int w = pm.findFactory ("Wob 1/4 Sine LP"); w >= 0)
    {
        const int sel = (int) f[(size_t) w].values[modParam (0, mDst)];
        CHECK (sel > 0 && modDestParams()[(size_t) sel] == fltParam (0, gCutoff));
        CHECK (f[(size_t) w].values[modParam (0, mSrc)] == (float) srcLfo1);
    }
    else CHECK (false);
    // the generated file: at least 200 presets, every one level-trimmed (presetGain set), unique names
    CHECK (f.size() >= 200);
    {
        juce::StringArray names;
        int trimmed = 0;
        for (const auto& p : f) { names.add (p.name); if (! std::isnan (p.values[presetGain])) ++trimmed; }
        CHECK (trimmed >= (int) f.size() - 1);   // all but Init
        names.removeDuplicates (false);
        CHECK ((int) names.size() == (int) f.size());
    }

    // save -> load round trip, with model blocks
    const auto tmp = juce::File::getSpecialLocation (juce::File::tempDirectory).getChildFile ("eightball-test.ebpreset");
    juce::String err;
    for (size_t src = 0; src < std::min<size_t> (f.size(), 4); ++src)
    {
        PresetData out = f[src];
        out.name = "Round Trip";
        out.model.waves[2] = WaveSpec::saw();
        out.model.waves[3] = WaveSpec::halfSine();
        out.model.envs[opEnvIndex (1, envAmp)] = EnvSpec::adsr (0.01f, 0.2f, 0.6f, 0.5f);
        out.model.envs[opEnvIndex (1, envAmp)].loopStart = 1;
        out.model.envs[opEnvIndex (1, envAmp)].loopEnd = 2;
        out.model.envs[opEnvIndex (1, envAmp)].sync = true;
        CHECK (PresetManager::writeFile (tmp, out, err));
        PresetData in;
        CHECK (PresetManager::readFile (tmp, in, err));
        CHECK (in.name == "Round Trip");
        for (int i = 0; i < kNumParams; ++i)
        {
            if (i == master) continue;
            const float a = out.values[(size_t) i], b = in.values[(size_t) i];
            if (std::isnan (a)) CHECK (std::isnan (b));
            else CHECKF (std::abs (b - a) < 1e-4f * std::max (1.0f, std::abs (a)), "%s %g vs %g", paramDef (i).id.c_str(), a, b);
        }
        for (int h = 0; h < kMaxPartials; ++h) CHECK (std::abs (in.model.waves[2].level[(size_t) h] - out.model.waves[2].level[(size_t) h]) < 1e-3f);
        CHECK (in.model.waves[3].drawn && std::abs (in.model.waves[3].shape[64] - out.model.waves[3].shape[64]) < 1e-3f);
        const auto& e = in.model.envs[opEnvIndex (1, envAmp)];
        CHECK (e.numPoints == 4 && e.sustain == 2 && e.loopStart == 1 && e.loopEnd == 2 && e.sync);
        CHECK (std::abs (e.pts[2].level - 0.6f) < 1e-3f && std::abs (e.pts[3].time - 0.71f) < 1e-3f);
    }

    // older/partial file: missing params stay NaN (-> defaults when applied), model parts default
    tmp.replaceWithText (R"({"name":"Partial","params":{"op1Ratio":2,"flt1Cutoff":99999}})");
    PresetData partial;
    CHECK (PresetManager::readFile (tmp, partial, err));
    CHECK (partial.values[opParam (0, fRatio)] == 2.0f);
    CHECK (partial.values[fltParam (0, gCutoff)] == 20000.0f);          // clamped to range
    CHECK (std::isnan (partial.values[opParam (1, fRatio)]));
    CHECK (partial.model.envs[opEnvIndex (0, envAmp)].numPoints == 4); // default ADSR

    // garbage is rejected with a message
    tmp.replaceWithText ("not json");
    PresetData bad;
    CHECK (! PresetManager::readFile (tmp, bad, err) && err.isNotEmpty());
    tmp.replaceWithText (R"({"name":"x"})");
    CHECK (! PresetManager::readFile (tmp, bad, err));
    tmp.replaceWithText (R"({"name":"Only a model","envs":{"op1Amp":{"points":[[0,1]]}}})");
    CHECK (PresetManager::readFile (tmp, bad, err) && bad.model.envs[0].numPoints == 1);
    tmp.deleteFile();

    // model JSON: waves without phases, envelopes with unsorted times
    {
        WaveSpec w;
        CHECK (waveFromJson (juce::JSON::parse (R"({"mode":"harmonic","levels":[1,0.5,0.25]})"), w));
        CHECK (! w.drawn && w.level[1] == 0.5f && w.phase[1] == 0.0f);
        EnvSpec e;
        CHECK (envFromJson (juce::JSON::parse (R"({"points":[[0,0],[0.5,1,0.3],[0.2,0.5]],"sustain":9})"), e));
        CHECK (e.numPoints == 3 && e.pts[2].time >= e.pts[1].time && e.sustain == 2);
        CHECK (! envFromJson (juce::JSON::parse (R"({"points":[]})"), e));
    }
    std::printf ("user preset folder: %s\n", PresetManager::userFolder().getFullPathName().toRawUTF8());
}

int main (int argc, char* argv[])
{
    juce::ScopedJuceInitialiser_GUI init;

    // --presets <file>: use this factory file instead of the compiled-in one (tuning without a rebuild)
    if (argc >= 3 && juce::String (argv[1]) == "--presets")
    {
        PresetManager::factoryOverride = juce::File::getCurrentWorkingDirectory().getChildFile (juce::String (argv[2]));
        if (! PresetManager::factoryOverride.existsAsFile()) { std::printf ("no such file: %s\n", argv[2]); return 2; }
        argc -= 2; argv += 2;
    }

    if (argc >= 2 && juce::String (argv[1]) == "--dump-params")
    {
        std::printf ("%s\n", juce::JSON::toString (paramTableToJson(), true).toRawUTF8());
        return 0;
    }
    if (argc >= 2 && juce::String (argv[1]) == "--bench") return runBench (argc >= 3 ? juce::String (argv[2]).getIntValue() : -1);
    if (argc >= 2 && juce::String (argv[1]) == "--loudness") return runLoudness();
    if (argc >= 4 && juce::String (argv[1]) == "--render")
        return runRender (argv[2], juce::File::getCurrentWorkingDirectory().getChildFile (juce::String (argv[3])),
                          argc >= 5 ? juce::String (argv[4]).getDoubleValue() : 3.0, argc >= 6 ? juce::String (argv[5]).getIntValue() : 60);
    if (argc >= 3 && juce::String (argv[1]) == "--host-check") return runHostCheck (argv[2]);

    paramTableTests();
    presetTests();
    runEngineTests();

    std::printf (failures == 0 ? "ALL PASSED\n" : "%d FAILURE(S)\n", failures);
    return failures == 0 ? 0 : 1;
}
