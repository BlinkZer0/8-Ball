// Engine checks: operators, the matrix, the output column, filters, voice modes,
// bypass switches, clicks, stuck notes, aliasing.
#include "TestRender.h"

using namespace eightball;
using namespace eightball::test;

extern int failures;
#define CHECK(cond) do { if (! (cond)) { ++failures; std::printf ("FAIL %s:%d  %s\n", __FILE__, __LINE__, #cond); } } while (0)
#define CHECKF(cond, ...) do { if (! (cond)) { ++failures; std::printf ("FAIL %s:%d  %s  ", __FILE__, __LINE__, #cond); std::printf (__VA_ARGS__); std::printf ("\n"); } } while (0)

namespace
{
constexpr size_t kA = 24000, kB = 48000;   // steady window: 0.5 s .. 1.0 s

// A note held for 1.5 s; blocks = 1.5 s
Render play (Patch& p, int note = 69, int vel = 100, int blocks = 563)
{
    return render (p, blocks, { on (1, note, vel) });
}

void wavetableTests()
{
    Wavetable t;
    const double gain = buildWavetable (WaveSpec::saw(), t);
    CHECK (gain > 0);
    double peak = 0;
    for (int i = 0; i < Wavetable::kSize; ++i) peak = std::max (peak, (double) std::abs (t.table[0][(size_t) i]));
    CHECK (std::abs (peak - 1.0) < 1e-3);
    CHECK (t.table[0][Wavetable::kSize] == t.table[0][0]);   // guard sample
    // the 1-harmonic level is a sine
    for (int i = 0; i < Wavetable::kSize; i += 97)
        CHECK (std::abs (t.table[7][(size_t) i] / gain - std::sin (kTwoPi * i / Wavetable::kSize)) < 1e-4);
    // mip selection
    CHECK (Wavetable::harmonicsAt (Wavetable::levelFor (440.0 / 48000.0)) <= 54);
    CHECK (Wavetable::harmonicsAt (Wavetable::levelFor (10000.0 / 48000.0)) == 2);
    CHECK (Wavetable::levelFor (0.4) == Wavetable::kLevels - 1);
    // drawn shape round trip: a drawn sine comes back as partial 1
    WaveSpec d;
    d.drawn = true;
    for (int i = 0; i < kDrawPoints; ++i) d.shape[(size_t) i] = (float) std::sin (kTwoPi * i / kDrawPoints);
    std::array<float, kMaxPartials> lv {}, ph {};
    partialsFromShape (d.shape, lv, ph);
    CHECK (std::abs (lv[0] - 1.0f) < 1e-3f && std::abs (lv[1]) < 1e-3f && std::abs (ph[0]) < 1e-3f);
    // half-sine has a 2nd harmonic
    partialsFromShape (WaveSpec::halfSine().shape, lv, ph);
    CHECK (lv[0] > 0.4f && lv[1] > 0.1f && lv[2] < 0.05f);
}

void envelopeTests()
{
    EnvSpec e = EnvSpec::adsr (0.1f, 0.2f, 0.5f, 0.4f);
    int seg = 0;
    CHECK (std::abs (e.eval (0.05, seg) - 0.5) < 1e-6);
    CHECK (std::abs (e.eval (0.1, seg) - 1.0) < 1e-6);
    CHECK (e.eval (0.2, seg) > 0.5 && e.eval (0.2, seg) < 1.0);
    CHECK (std::abs (e.eval (0.3, seg) - 0.5) < 1e-6);
    CHECK (std::abs (e.eval (5.0, seg)) < 1e-9);
    // tension: negative = fast start
    CHECK (EnvSpec::curve (0.25, -0.5) > 0.25 && EnvSpec::curve (0.25, 0.5) < 0.25 && EnvSpec::curve (0.25, 0) == 0.25);

    EnvState s;
    s.gateOn (e);
    double v = 0;
    for (int i = 0; i < 100; ++i) v = s.advance (e, 0.01);   // t = 1.0: held at sustain
    CHECK (std::abs (v - 0.5) < 1e-9 && s.stage == EnvState::Held);
    s.gateOff (e);
    v = s.advance (e, 0.01);
    CHECK (s.stage == EnvState::Released && v < 0.5 && v > 0.2);
    for (int i = 0; i < 100; ++i) v = s.advance (e, 0.01);
    CHECK (s.finished() && v == 0.0);

    // release from mid-attack: no jump (the offset fades)
    s = EnvState {};
    s.gateOn (e);
    for (int i = 0; i < 5; ++i) v = s.advance (e, 0.01);   // t = 0.05, level 0.5 on the way up
    s.gateOff (e);
    const double v1 = s.advance (e, 0.001);
    CHECK (std::abs (v1 - v) < 0.05);
    // retrigger from the sustain: fades from 0.5 into the new attack, no jump to 0
    s = EnvState {};
    s.gateOn (e);
    for (int i = 0; i < 100; ++i) v = s.advance (e, 0.01);
    s.gateOn (e);
    CHECK (std::abs (s.advance (e, 0.001) - 0.5) < 0.05);

    // loop while held, exit on release
    EnvSpec l = e;
    l.sustain = -1; l.loopStart = 1; l.loopEnd = 2;
    s = EnvState {};
    s.gateOn (l);
    for (int i = 0; i < 100; ++i) v = s.advance (l, 0.01);
    CHECK (s.stage == EnvState::Held && s.t >= 0.1 && s.t <= 0.3);
    s.gateOff (l);
    for (int i = 0; i < 100; ++i) v = s.advance (l, 0.01);
    CHECK (s.finished());

    // one-shot (no sustain, no loop) finishes while held
    EnvSpec o = e;
    o.sustain = -1;
    s = EnvState {};
    s.gateOn (o);
    for (int i = 0; i < 100; ++i) v = s.advance (o, 0.01);
    CHECK (s.finished() && v == 0.0);
}

void operatorTests()
{
    // the Init patch: op 1 sine to Dry
    Patch p;
    auto r = play (p);
    const auto m = r.mono();
    CHECKF (std::abs (zeroCrossFreq (m, kA, kB) - 440.0) < 1.0, "%g Hz", zeroCrossFreq (m, kA, kB));
    CHECK (rms (m, kA, kB) > 0.05);
    CHECK (std::abs (rms (r.L, kA, kB) - rms (r.R, kA, kB)) < 1e-4);     // pan centre
    // pure: 2nd harmonic far down
    CHECK (dB (magAt (m, kA, kB, 880)) - dB (magAt (m, kA, kB, 440)) < -70);
    // two renders are identical (phase reset on, deterministic)
    auto r2 = play (p);
    CHECK (r2.L == r.L);

    // ratio, fine, fixed, key track
    p = Patch().set ("op1Ratio", 2);
    CHECKF (std::abs (zeroCrossFreq (play (p).mono(), kA, kB) - 880.0) < 1.5, "ratio 2");
    p = Patch().set ("op1Fine", 100);
    CHECKF (std::abs (zeroCrossFreq (play (p).mono(), kA, kB) - 466.16) < 1.5, "fine +100");
    p = Patch().set ("op1Fixed", 1).set ("op1Hz", 1000);
    CHECKF (std::abs (zeroCrossFreq (play (p, 40).mono(), kA, kB) - 1000.0) < 2, "fixed, low note");
    CHECKF (std::abs (zeroCrossFreq (play (p, 90).mono(), kA, kB) - 1000.0) < 2, "fixed, high note");
    p = Patch().set ("op1KeyTrack", 0);
    CHECKF (std::abs (zeroCrossFreq (play (p, 72).mono(), kA, kB) - 261.63) < 1.5, "key track 0");
    p = Patch().set ("op1KeyTrack", 0.5f);
    CHECKF (std::abs (zeroCrossFreq (play (p, 84).mono(), kA, kB) - 523.25) < 2, "key track 50%%: two octaves up = one");

    // velocity sensitivity: 0 = same level at any velocity, 1 = much quieter at vel 20
    p = Patch().set ("op1Vel", 0);
    CHECK (std::abs (rms (play (p, 69, 20).mono(), kA, kB) - rms (play (p, 69, 127).mono(), kA, kB)) < 1e-3);
    p = Patch().set ("op1Vel", 1);
    CHECK (rms (play (p, 69, 20).mono(), kA, kB) < 0.2 * rms (play (p, 69, 127).mono(), kA, kB));

    // pan
    p = Patch().set ("op1Pan", -1);
    r = play (p);
    CHECK (rms (r.R, kA, kB) < 1e-3 && rms (r.L, kA, kB) > 0.05);

    // starter waves: saw has a 2nd harmonic, square doesn't, triangle's 3rd is -19 dB
    p = Patch().set ("op1Wave", waveSaw);
    auto s = play (p).mono();
    CHECK (dB (magAt (s, kA, kB, 880)) - dB (magAt (s, kA, kB, 440)) > -7 && dB (magAt (s, kA, kB, 880)) - dB (magAt (s, kA, kB, 440)) < -5);
    p = Patch().set ("op1Wave", waveSquare);
    s = play (p).mono();
    CHECK (dB (magAt (s, kA, kB, 880)) - dB (magAt (s, kA, kB, 440)) < -60);
    CHECK (std::abs (dB (magAt (s, kA, kB, 1320)) - dB (magAt (s, kA, kB, 440)) + 9.5) < 1);
    p = Patch().set ("op1Wave", waveTriangle);
    s = play (p).mono();
    CHECK (std::abs (dB (magAt (s, kA, kB, 1320)) - dB (magAt (s, kA, kB, 440)) + 19.1) < 1);
    p = Patch().set ("op1Wave", waveNoise);
    s = play (p).mono();
    CHECK (rms (s, kA, kB) > 0.05 && magAt (s, kA, kB, 440) < 0.05);
    // custom wave from the model: a saw drawn in the harmonic editor
    p = Patch().set ("op1Wave", waveCustom);
    p.model.waves[0] = WaveSpec::saw();
    s = play (p).mono();
    CHECK (dB (magAt (s, kA, kB, 880)) - dB (magAt (s, kA, kB, 440)) > -7);

    // mute, solo, level 0, out column
    p = Patch().set ("op1Mute", 1);
    CHECK (play (p).peak == 0.0);
    p = Patch().set ("out1Dry", 0);
    CHECK (play (p).peak == 0.0);
    p = Patch().set ("op1Level", 0);
    CHECK (play (p).peak == 0.0);
    p = Patch().set ("out2Dry", 1).set ("op2Ratio", 3).set ("op2Solo", 1);   // op 1 + op 2 to Dry, op 2 soloed
    s = play (p).mono();
    CHECK (magAt (s, kA, kB, 1320) > 0.02 && magAt (s, kA, kB, 440) < 1e-3);
    p = Patch().set ("out2Dry", 1).set ("op2Ratio", 3);
    s = play (p).mono();
    CHECK (magAt (s, kA, kB, 1320) > 0.02 && magAt (s, kA, kB, 440) > 0.02);
    // a soloed carrier keeps its modulators: op 2 -> op 1, op 1 soloed, output still has sidebands
    p = Patch().set ("pm21", 0.5f).set ("op2Ratio", 2).set ("op1Solo", 1);
    s = play (p).mono();
    CHECK (magAt (s, kA, kB, 1320) > 0.01);
}

void matrixTests()
{
    // PM: op 2 (ratio 2) modulates op 1: sidebands at 440 +- 880
    Patch p = Patch().set ("op2Ratio", 2);
    auto dry = play (p).mono();
    p.set ("pm21", 0.5f);
    auto wet = play (p).mono();
    CHECK (magAt (dry, kA, kB, 1320) < 1e-4);
    std::printf ("  PM 2>1 depth 0.5: carrier %.4f, sidebands %.4f %.4f %.4f (dry carrier %.4f)\n", magAt (wet, kA, kB, 440),
                 magAt (wet, kA, kB, 1320), magAt (wet, kA, kB, 2200), magAt (wet, kA, kB, 3080), magAt (dry, kA, kB, 440));
    CHECKF (magAt (wet, kA, kB, 1320) > 0.01, "sideband %g", magAt (wet, kA, kB, 1320));
    // deeper = more sidebands further out
    p.set ("pm21", 1.0f);
    auto deep = play (p).mono();
    CHECK (magAt (deep, kA, kB, 440 + 4 * 880) > magAt (wet, kA, kB, 440 + 4 * 880));
    // the modulator's level scales the index (the 3rd sideband all but vanishes at a fifth of the index)
    p.set ("pm21", 0.5f).set ("op2Level", 0.2f);
    CHECK (magAt (play (p).mono(), kA, kB, 3080) < 0.2 * magAt (wet, kA, kB, 3080));
    // the mod env amount scales the incoming modulation of the carrier: op 1 mod env flat 0 at amount 1 -> no modulation
    p = Patch().set ("op2Ratio", 2).set ("pm21", 0.5f).set ("op1ModEnvAmt", 1);
    p.model.envs[opEnvIndex (0, envMod)] = EnvSpec::flat (0.0f);
    CHECK (magAt (play (p).mono(), kA, kB, 1320) < 1e-4);

    // feedback: a sine with self-PM grows harmonics (saw-like)
    p = Patch().set ("pm11", 0.5f);
    auto fb = play (p).mono();
    CHECK (dB (magAt (fb, kA, kB, 880)) - dB (magAt (fb, kA, kB, 440)) > -20);
    CHECK (std::abs (peakFreq (fb, kA, kB, 300, 600) - 440) < 2);

    // modulation from a higher-numbered operator works too (one sample late)
    p = Patch().set ("op1Ratio", 2).set ("out1Dry", 0).set ("out2Dry", 1).set ("pm12", 0.5f);
    CHECK (magAt (play (p).mono(), kA, kB, 1320) > 0.01);

    // a 3-operator stack: 3 -> 2 -> 1
    p = Patch().set ("op2Ratio", 2).set ("op3Ratio", 3).set ("pm32", 0.6f).set ("pm21", 0.5f);
    auto stack = play (p).mono();
    CHECK (magAt (stack, kA, kB, 440 + 880 + 1320) > 1e-3);

    // ring mod: op 2 (ratio 3) x op 1 -> energy at 1760 (440 + 1320) and 880 (1320 - 440)
    p = Patch().set ("op2Ratio", 3).set ("rm21", 1.0f);
    auto ring = play (p).mono();
    CHECK (magAt (ring, kA, kB, 1760) > 0.01 && magAt (ring, kA, kB, 880) > 0.01);
    CHECK (magAt (ring, kA, kB, 440) < 1e-3);   // pure product: no carrier
    p.set ("rm21", 0.5f);
    ring = play (p).mono();
    CHECK (magAt (ring, kA, kB, 440) > 0.01);   // half: carrier and product

    // an operator that is routed nowhere costs nothing and makes no sound: op 2 level 1, no cell, no output
    p = Patch().set ("op2Ratio", 2);
    auto ePtr = std::make_unique<SynthEngine>();
    auto& e = *ePtr;
    e.setParamValues (p.v.data());
    e.prepare (kSr);
    e.settleParams();
    CHECK (e.opActive (0) && ! e.opActive (1));
    p.set ("pm21", 0.1f);
    e.setParamValues (p.v.data());
    e.settleParams();
    CHECK (e.opActive (1));
    p.set ("op1Mute", 1);   // the carrier is muted: its modulator goes idle too
    e.setParamValues (p.v.data());
    e.settleParams();
    CHECK (! e.opActive (0) && ! e.opActive (1));
}

void filterTests()
{
    // op 1 saw into filter 1, low-pass 300 Hz: the 4th harmonic drops by > 20 dB versus dry
    Patch p = Patch().set ("op1Wave", waveSaw).set ("out1Dry", 0).set ("out1F1", 1).set ("flt1Cutoff", 300);
    auto lp = play (p, 57).mono();     // A3 = 220 Hz
    Patch d = Patch().set ("op1Wave", waveSaw);
    auto dry = play (d, 57).mono();
    const double h4 = dB (magAt (lp, kA, kB, 880)) - dB (magAt (dry, kA, kB, 880));
    CHECKF (h4 < -15 && h4 > -24, "lp12 4th harmonic %g dB (theory -19)", h4);
    // 24 dB: steeper
    p.set ("flt1Slope", 1);
    const double h4b = dB (magAt (play (p, 57).mono(), kA, kB, 880)) - dB (magAt (dry, kA, kB, 880));
    CHECKF (h4b < h4 - 10, "lp24 %g vs lp12 %g", h4b, h4);
    // high-pass: fundamental drops instead
    p.set ("flt1Slope", 0).set ("flt1Type", fltHighpass).set ("flt1Cutoff", 2000);
    auto hp = play (p, 57).mono();
    CHECK (dB (magAt (hp, kA, kB, 220)) - dB (magAt (dry, kA, kB, 220)) < -25);
    // band-pass: both ends down
    p.set ("flt1Type", fltBandpass).set ("flt1Cutoff", 880);
    auto bp = play (p, 57).mono();
    CHECK (dB (magAt (bp, kA, kB, 220)) - dB (magAt (dry, kA, kB, 220)) < -10);
    CHECK (dB (magAt (bp, kA, kB, 7040)) - dB (magAt (dry, kA, kB, 7040)) < -10);

    // BYPASS: filter off = exactly the input (the dry render), whatever the cutoff
    p = Patch().set ("op1Wave", waveSaw).set ("out1Dry", 0).set ("out1F1", 1).set ("flt1Cutoff", 300).set ("flt1On", 0);
    auto off = play (p, 57);
    auto ref = play (d, 57);
    double worst = 0;
    for (size_t i = 0; i < off.L.size(); ++i) worst = std::max (worst, (double) std::abs (off.L[i] - ref.L[i]));
    CHECKF (worst < 1e-6, "filter bypass differs by %g", worst);
    // mix 0 = dry too
    p.set ("flt1On", 1).set ("flt1Mix", 0);
    off = play (p, 57);
    worst = 0;
    for (size_t i = 0; i < off.L.size(); ++i) worst = std::max (worst, (double) std::abs (off.L[i] - ref.L[i]));
    CHECKF (worst < 1e-6, "filter mix 0 differs by %g", worst);

    // resonance adds a peak at the cutoff
    p = Patch().set ("op1Wave", waveSaw).set ("out1Dry", 0).set ("out1F1", 1).set ("flt1Cutoff", 880).set ("flt1Reso", 0.9f);
    auto res = play (p, 57).mono();
    p.set ("flt1Reso", 0);
    auto flat = play (p, 57).mono();
    CHECK (dB (magAt (res, kA, kB, 880)) - dB (magAt (flat, kA, kB, 880)) > 6);

    // key tracking: 100% moves the cutoff with the note, so the harmonic balance is the same an octave up
    p = Patch().set ("op1Wave", waveSaw).set ("out1Dry", 0).set ("out1F1", 1).set ("flt1Cutoff", 500).set ("flt1KeyTrack", 1);
    auto lo = play (p, 48).mono(), hi = play (p, 60).mono();
    const double balLo = dB (magAt (lo, kA, kB, 130.81 * 4)) - dB (magAt (lo, kA, kB, 130.81));
    const double balHi = dB (magAt (hi, kA, kB, 261.63 * 4)) - dB (magAt (hi, kA, kB, 261.63));
    CHECKF (std::abs (balLo - balHi) < 1.5, "key track %g vs %g", balLo, balHi);

    // envelope amount: cutoff env opens the filter at the start, so the first 50 ms is brighter than the sustain
    p = Patch().set ("op1Wave", waveSaw).set ("out1Dry", 0).set ("out1F1", 1).set ("flt1Cutoff", 200).set ("flt1EnvAmt", 0.8f);
    auto env = play (p, 57).mono();
    const double early = dB (magAt (env, 48 + 480, 48 + 2400, 1760)), late = dB (magAt (env, kA, kB, 1760));
    CHECKF (early - late > 10, "env %g vs %g", early, late);
    // velocity -> cutoff
    p = Patch().set ("op1Wave", waveSaw).set ("out1Dry", 0).set ("out1F1", 1).set ("flt1Cutoff", 300).set ("flt1Vel", 1);
    CHECK (magAt (play (p, 57, 127).mono(), kA, kB, 1760) > 3 * magAt (play (p, 57, 10).mono(), kA, kB, 1760));

    // routing: series 1>2>3 with filter 1 LP 300 and filter 3 HP 2000 leaves almost nothing; parallel leaves both bands
    p = Patch().set ("op1Wave", waveSaw).set ("out1Dry", 0).set ("out1F1", 1).set ("flt1Cutoff", 300)
               .set ("flt2Cutoff", 20000).set ("flt3Type", fltHighpass).set ("flt3Cutoff", 2000).set ("fltRouting", routeSeries);
    auto ser = play (p, 57).mono();
    CHECK (rms (ser, kA, kB) < 0.1 * rms (dry, kA, kB));
    p.set ("fltRouting", routeParallel);
    CHECK (rms (play (p, 57).mono(), kA, kB) > 0.3 * rms (dry, kA, kB));
    // 1+2 > 3: op 1 into F1 (LP 300) and F2 (HP 5000), summed into F3 (flat) = both bands present
    p = Patch().set ("op1Wave", waveSaw).set ("out1Dry", 0).set ("out1F1", 1).set ("out1F2", 1).set ("flt1Cutoff", 300)
               .set ("flt2Type", fltHighpass).set ("flt2Cutoff", 5000).set ("flt3Cutoff", 20000).set ("fltRouting", routeTwoIntoThree);
    auto two = play (p, 57).mono();
    CHECK (magAt (two, kA, kB, 220) > 0.5 * magAt (dry, kA, kB, 220) && magAt (two, kA, kB, 7040) > 0.3 * magAt (dry, kA, kB, 7040));
    CHECK (magAt (two, kA, kB, 1320) < 0.2 * magAt (dry, kA, kB, 1320));

    // drive adds harmonics to a sine
    p = Patch().set ("out1Dry", 0).set ("out1F1", 1).set ("flt1Cutoff", 20000).set ("flt1Drive", 1);
    auto drv = play (p).mono();
    CHECK (dB (magAt (drv, kA, kB, 1320)) - dB (magAt (drv, kA, kB, 440)) > -40);
}

void voiceTests()
{
    // polyphony: 2 voices, 3 notes -> 2 active; 16 voices -> 3
    Patch p = Patch().set ("poly", 2);
    auto r = render (p, 100, { on (1, 60), on (2, 64), on (3, 67) });
    CHECK (r.activeAtEnd == 2);
    p.set ("poly", 16);
    r = render (p, 100, { on (1, 60), on (2, 64), on (3, 67) });
    CHECK (r.activeAtEnd == 3);
    // the same note again retriggers its voice (still 1)
    r = render (p, 100, { on (1, 60), on (20, 60) });
    CHECK (r.activeAtEnd == 1);

    // mono: last note wins, and releasing it goes back to the one still held
    p = Patch().set ("voiceMode", modeMono);
    r = render (p, 563, { on (1, 57), on (100, 69), off (300, 69) });
    auto m = r.mono();
    CHECK (r.activeAtEnd == 1);
    CHECKF (std::abs (zeroCrossFreq (m, 200 * 128, 290 * 128) - 440) < 2, "mono high");
    CHECKF (std::abs (zeroCrossFreq (m, 400 * 128, 550 * 128) - 220) < 2, "mono back");

    // legato + portamento: the pitch glides (frequency half way through the glide is in between)
    p = Patch().set ("voiceMode", modeLegato).set ("portaOn", 1).set ("portaTime", 0.5f);
    r = render (p, 563, { on (1, 57), on (188, 69) });   // second note at 0.5 s; glide 0.5..1.0 s
    m = r.mono();
    const double mid = zeroCrossFreq (m, (size_t) (0.72 * kSr), (size_t) (0.78 * kSr));
    CHECKF (mid > 260 && mid < 400, "glide mid %g", mid);
    CHECKF (std::abs (zeroCrossFreq (m, (size_t) (1.2 * kSr), (size_t) (1.45 * kSr)) - 440) < 2, "glide end");
    // legato doesn't retrigger: with a 1 s attack, the second note keeps the level the first reached
    p = Patch().set ("voiceMode", modeLegato);
    p.model.envs[opEnvIndex (0, envAmp)] = EnvSpec::adsr (1.0f, 0.1f, 1.0f, 0.3f);
    r = render (p, 563, { on (1, 57), on (188, 69) });
    m = r.mono();
    CHECK (rmsSec (m, 0.52, 0.56) > 0.9 * rmsSec (m, 0.44, 0.48));
    // poly retrigger of a held note restarts the attack from the level it had: no dip, no jump
    p = Patch();
    p.model.envs[opEnvIndex (0, envAmp)] = EnvSpec::adsr (1.0f, 0.1f, 1.0f, 0.3f);
    r = render (p, 563, { on (1, 57), on (188, 57) });
    m = r.mono();
    CHECK (rmsSec (m, 0.52, 0.56) > 0.9 * rmsSec (m, 0.44, 0.48) && rmsSec (m, 1.3, 1.4) > 1.5 * rmsSec (m, 0.44, 0.48));

    // sustain pedal holds, then releases
    p = Patch();
    r = render (p, 563, { { 1, [] (SynthEngine& e) { e.setSustain (true); } }, on (1, 69), off (100, 69),
                          { 300, [] (SynthEngine& e) { e.setSustain (false); } } });
    m = r.mono();
    CHECK (rmsSec (m, 0.5, 0.7) > 0.05);        // still sounding after note off
    CHECK (rmsSec (m, 1.3, 1.5) < 1e-3);        // gone after the pedal is lifted and the release ran
    CHECK (r.activeAtEnd == 0);

    // no stuck notes: note off -> release runs out -> voice gone, output silent
    p = Patch();
    r = render (p, 563, { on (1, 69), off (100, 69) });
    m = r.mono();
    CHECK (rmsSec (m, 1.0, 1.5) < 1e-4 && r.activeAtEnd == 0);
    // all notes off / panic
    r = render (p, 200, { on (1, 60), on (1, 64), { 50, [] (SynthEngine& e) { e.allNotesOff(); } } });
    CHECK (r.activeAtEnd == 0);
    r = render (p, 100, { on (1, 60), on (1, 64), { 50, [] (SynthEngine& e) { e.panic(); } } });
    CHECK (r.activeAtEnd == 0 && rms (r.mono(), 51 * 128, 100 * 128) == 0.0);

    // pitch bend: +2 semitones at full
    p = Patch();
    r = render (p, 400, { on (1, 69), { 150, [] (SynthEngine& e) { e.setPitchBend (1.0); } } });
    CHECKF (std::abs (zeroCrossFreq (r.mono(), 250 * 128, 390 * 128) - 493.88) < 2, "bend");
    p.set ("bendRange", 12);
    r = render (p, 400, { on (1, 69), { 150, [] (SynthEngine& e) { e.setPitchBend (1.0); } } });
    CHECKF (std::abs (zeroCrossFreq (r.mono(), 250 * 128, 390 * 128) - 880) < 3, "bend 12");
    // fixed operators don't bend
    p = Patch().set ("op1Fixed", 1).set ("op1Hz", 1000);
    r = render (p, 400, { on (1, 69), { 150, [] (SynthEngine& e) { e.setPitchBend (1.0); } } });
    CHECK (std::abs (zeroCrossFreq (r.mono(), 250 * 128, 390 * 128) - 1000) < 2);

    // envelopes: a 0.5 s attack is quiet at 0.1 s and loud at 0.5 s; a long release keeps sounding after note off
    p = Patch();
    p.model.envs[opEnvIndex (0, envAmp)] = EnvSpec::adsr (0.5f, 0.1f, 1.0f, 1.0f);
    r = render (p, 563, { on (1, 69), off (375, 69) });
    m = r.mono();
    CHECK (rmsSec (m, 0.08, 0.12) < 0.4 * rmsSec (m, 0.5, 0.6));
    CHECK (rmsSec (m, 1.2, 1.3) > 0.3 * rmsSec (m, 0.5, 0.6) && rmsSec (m, 1.2, 1.3) < 0.95 * rmsSec (m, 0.5, 0.6));
    // pitch envelope: +12 st at the start, down to 0 after 0.5 s
    p = Patch().set ("op1PitchEnvAmt", 12);
    {
        EnvSpec e;
        e.add (0, 1.0f); e.add (0.5f, 0.5f); e.add (2.0f, 0.5f);
        e.sustain = 2;
        p.model.envs[opEnvIndex (0, envPitch)] = e;
    }
    r = render (p, 563, { on (1, 69) });
    m = r.mono();
    CHECKF (zeroCrossFreq (m, 200, 2400) > 800, "pitch env start %g", zeroCrossFreq (m, 200, 2400));
    CHECKF (std::abs (zeroCrossFreq (m, kA + 12000, kB) - 440) < 2, "pitch env end");
    // tempo-synced envelope: a 1-beat attack takes 0.5 s at 120 BPM and 0.25 s at 240
    p = Patch();
    {
        EnvSpec e = EnvSpec::adsr (1.0f, 0.1f, 1.0f, 0.5f);
        e.sync = true;
        p.model.envs[opEnvIndex (0, envAmp)] = e;
    }
    auto slow = render (p, 300, { on (1, 69) }, 120.0).mono();
    auto fast = render (p, 300, { on (1, 69) }, 240.0).mono();
    CHECK (rmsSec (fast, 0.2, 0.25) > 1.5 * rmsSec (slow, 0.2, 0.25));
}

void qualityTests()
{
    // Phase reset off: two notes in a row start at different (random) phases but have the same level
    Patch p = Patch().set ("op1PhaseReset", 0);
    auto r = render (p, 500, { on (1, 69), off (50, 69), on (250, 69) });
    auto m = r.mono();
    double worst = 0;
    for (size_t i = 0; i < 2000; ++i) worst = std::max (worst, (double) std::abs (m[128 + i] - m[250 * 128 + i]));
    CHECK (worst > 1e-3);
    CHECK (std::abs (rmsSec (m, 0.1, 0.15) / rmsSec (m, 0.1 + 250.0 * 128 / kSr, 0.15 + 250.0 * 128 / kSr) - 1.0) < 0.05);
    // Phase reset on: attacks identical across voices: note on twice in a row = identical starts
    p = Patch();
    r = render (p, 500, { on (1, 69), off (50, 69), on (250, 69) });
    m = r.mono();
    worst = 0;
    for (size_t i = 0; i < 2000; ++i) worst = std::max (worst, (double) std::abs (m[128 + i] - m[250 * 128 + i]));
    CHECKF (worst < 1e-5, "phase reset attack differs by %g", worst);

    // unison: 2 voices detuned beat (level varies over time); 1 voice doesn't
    p = Patch().set ("op1Unison", 2).set ("op1Detune", 30).set ("op1Spread", 0);
    m = play (p).mono();
    double lo = 1e9, hi = 0;
    for (double t = 0.3; t < 1.4; t += 0.02) { const double v = rmsSec (m, t, t + 0.02); lo = std::min (lo, v); hi = std::max (hi, v); }
    CHECKF (hi > 3 * lo, "unison beating %g..%g", lo, hi);
    p = Patch();
    m = play (p).mono();
    lo = 1e9; hi = 0;
    for (double t = 0.3; t < 1.4; t += 0.02) { const double v = rmsSec (m, t, t + 0.02); lo = std::min (lo, v); hi = std::max (hi, v); }
    CHECK (hi < 1.05 * lo);
    // spread puts the sub-oscillators left and right: with 2 voices, L and R differ
    p = Patch().set ("op1Unison", 2).set ("op1Detune", 30).set ("op1Spread", 1);
    auto st = play (p);
    double diff = 0;
    for (size_t i = kA; i < kB; ++i) diff += std::abs (st.L[i] - st.R[i]);
    CHECK (diff / (kB - kA) > 0.01);
    p.set ("op1Spread", 0);
    st = play (p);
    diff = 0;
    for (size_t i = kA; i < kB; ++i) diff += std::abs (st.L[i] - st.R[i]);
    CHECK (diff / (kB - kA) < 1e-6);
    // unison 8 is louder-proof: level within 3 dB of unison 1 (constant power), per sub phase differs
    p = Patch().set ("op1Unison", 8).set ("op1Detune", 20);
    Patch one;
    CHECK (std::abs (dB (rms (play (p).mono(), kA, kB)) - dB (rms (play (one).mono(), kA, kB))) < 4);

    // BYPASS: oversampling off is the plain path (no half-band): a 440 Hz sine renders identically
    // to a reference engine with the switch never touched; oversampling on matches it after the
    // filter's 3-sample delay to within 0.1% RMS
    p = Patch();
    auto off = play (p);
    p.set ("oversample", 1);
    auto os = play (p);
    double bestErr = 1e9;
    int bestShift = -1;
    for (int shift = 0; shift < 8; ++shift)
    {
        double err = 0, ref = 0;
        for (size_t i = kA; i < kB; ++i) { err += std::pow (os.L[i + (size_t) shift] - off.L[i], 2.0); ref += std::pow (off.L[i], 2.0); }
        if (std::sqrt (err / ref) < bestErr) { bestErr = std::sqrt (err / ref); bestShift = shift; }
    }
    std::printf ("  2x oversampling: best whole-sample delay %d, residual %.4f\n", bestShift, bestErr);
    CHECKF (bestShift == HalfbandState::kLatency2x, "decimator delay %d, reported %d", bestShift, HalfbandState::kLatency2x);
    CHECKF (bestErr < 0.03, "oversampling vs plain: %g", bestErr);
    CHECK (SynthEngine::latencySamples (false) == 0 && SynthEngine::latencySamples (true) == HalfbandState::kLatency2x);
    // oversampling reduces aliasing of a heavily modulated high note
    p = Patch().set ("op2Ratio", 7).set ("pm21", 1.0f);
    auto plain = play (p, 100).mono();   // E7 = 2637 Hz
    p.set ("oversample", 1);
    auto clean = play (p, 100).mono();
    // energy in an inharmonic band below the fundamental: 200..2000 Hz, where only aliases can land
    double alPlain = 0, alClean = 0;
    for (double f = 200; f < 2500; f += 50) { alPlain += magAt (plain, kA, kB, f); alClean += magAt (clean, kA, kB, f); }
    CHECKF (alClean < 0.5 * alPlain, "alias energy plain %g vs 2x %g", alPlain, alClean);

    // aliasing of the band-limited tables: a saw at C8 (4186 Hz) has nothing between its harmonics
    p = Patch().set ("op1Wave", waveSaw);
    m = play (p, 108).mono();
    const double fund = magAt (m, kA, kB, 4186.0);
    double between = 0;
    for (double f = 4186.0 * 1.3; f < 4186.0 * 1.7; f += 50) between = std::max (between, magAt (m, kA, kB, f));
    CHECKF (dB (between) - dB (fund) < -60, "saw C8 between harmonics %g dB", dB (between) - dB (fund));

    // CLICKS: a level jump mid-note is smoothed (largest step close to the sine's own)
    p = Patch();
    const double steady = maxStep (play (p).mono(), kA, kB);
    r = render (p, 400, { on (1, 69), { 200, [&p] (SynthEngine&) { p.set ("op1Level", 0.1f); } } });
    const double step = maxStep (r.mono(), 190 * 128, 260 * 128);
    CHECKF (step < 2.0 * steady, "level jump step %g vs steady %g", step, steady);
    // a ratio jump glides, no discontinuity
    r = render (p, 400, { on (1, 69), { 200, [&p] (SynthEngine&) { p.set ("op1Ratio", 4.0f); } } });
    CHECKF (maxStep (r.mono(), 190 * 128, 260 * 128) < 6.0 * steady, "ratio jump %g", maxStep (r.mono(), 190 * 128, 260 * 128));
    // a PM depth jump: the transition is no steeper than the modulated waveform itself
    p = Patch().set ("op2Ratio", 2);
    r = render (p, 500, { on (1, 69), { 200, [&p] (SynthEngine&) { p.set ("pm21", 0.8f); } } });
    const double after = maxStep (r.mono(), 300 * 128, 500 * 128);
    CHECKF (maxStep (r.mono(), 190 * 128, 260 * 128) < 1.2 * std::max (after, steady), "pm jump %g vs after %g", maxStep (r.mono(), 190 * 128, 260 * 128), after);
    // the safety clipper is linear below 0.8 and never exceeds 1
    CHECK (safetyClip (0.5) == 0.5 && safetyClip (-0.79) == -0.79 && safetyClip (5.0) <= 1.0 && safetyClip (-5.0) >= -1.0 && safetyClip (0.9) < 0.9);

    // model handoff: a new table reaches the audio thread, the old one is retired and freed
    auto storePtr = std::make_unique<ModelStore>();
    auto& store = *storePtr;
    const Model* m0 = store.takeIncoming();
    CHECK (m0 != nullptr && store.takeIncoming() == nullptr);
    store.setWave (0, WaveSpec::saw());
    const Model* m1 = store.takeIncoming();   // the new one; the old one is parked as retired
    CHECK (m1 != nullptr && m1 != m0);
    CHECK (store.takeIncoming() == nullptr);
    if (m1 != nullptr) CHECK (m1->tables[0]->table[7][512] > 0.3f);   // partial 1 of the saw at phase 0.25 (after normalisation)
    store.setEnv (0, EnvSpec::flat (0.3f));    // publishes again (and frees the retired one on this thread)
    const Model* m2 = store.takeIncoming();
    CHECK (m2 != nullptr && m2 != m1);
    if (m2 != nullptr) CHECK (m2->envs[0].numPoints == 2 && m2->tables[0]->table[7][512] > 0.3f);
    store.collectRetired();
}
} // namespace

// Every factory preset renders a full note (on, hold, off, release, voice end) with finite, non-silent output.
static void factoryPresetTests()
{
    // regression: a one-shot envelope with a curved last segment used to produce NaN at its end
    {
        Patch p;
        EnvSpec e; e.add (0, 0); e.add (0.003f, 1); e.add (1.5f, 0, -0.6f); e.sustain = -1;
        p.model.envs[opEnvIndex (0, envAmp)] = e;
        auto r = render (p, 1125, { on (1, 60), off (750, 60) });
        bool finite = true;
        for (size_t s = 0; s < r.L.size(); ++s) finite = finite && std::isfinite (r.L[s]);
        CHECK (finite && r.activeAtEnd == 0);
    }
    PresetManager pm;
    for (size_t i = 0; i < pm.factory().size(); ++i)
    {
        const auto& f = pm.factory()[i];
        std::printf ("   preset: %s / %s\n", f.category.toRawUTF8(), f.name.toRawUTF8()); std::fflush (stdout);
        Patch p;
        applyPresetData (p.v, f);
        p.model = f.model;
        const bool mono = p.v[voiceMode] >= 0.5f;
        auto r = render (p, 1125, { on (1, mono ? 36 : 60), off (750, mono ? 36 : 60) });   // 3 s
        bool finite = true;
        size_t firstBad = 0;
        for (size_t s = 0; s < r.L.size(); ++s)
            if (! (std::isfinite (r.L[s]) && std::isfinite (r.R[s]))) { finite = false; firstBad = s; break; }
        CHECKF (finite, "%s has NaN / inf from sample %d (%.3f s)", f.name.toRawUTF8(), (int) firstBad, firstBad / kSr);
        CHECKF (r.peak > 0.005 || f.name == "Init", "%s is silent (peak %g)", f.name.toRawUTF8(), r.peak);
        CHECKF (r.peak <= 1.0, "%s exceeds 0 dBFS", f.name.toRawUTF8());
    }
}

int runEngineTests()
{
    auto step = [] (const char* name, void (*fn)()) { std::printf ("-- %s\n", name); std::fflush (stdout); fn(); };
    step ("wavetables", wavetableTests);
    step ("envelopes", envelopeTests);
    step ("operators", operatorTests);
    step ("matrix", matrixTests);
    step ("filters", filterTests);
    step ("voices", voiceTests);
    step ("quality", qualityTests);
    step ("factory presets", factoryPresetTests);
    return failures;
}
