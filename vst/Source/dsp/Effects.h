#pragma once
// ============================================================================
//  The FX chain (global, stereo, after the voice sum, before the master):
//  Distortion, Chorus, Phaser, Delay, Reverb, EQ, Compressor / Limiter, in
//  the order the fxOrder1-7 parameters give. Plain C++ (no JUCE); buffers
//  are allocated in prepare() only.
//
//  Every unit has an on/off and a mix. Off is a true bypass: the unit is
//  skipped and its state cleared, so the output is bit-identical to a chain
//  without it. Switching on or off crossfades over 10 ms (the "enable" ramp),
//  so a toggle mid-note doesn't click. mix 0 is exactly dry too
//  (out = dry + enable x mix x (wet - dry)).
//
//  Parameters arrive already smoothed (the engine's val[] array); anything
//  derived per sample (delay times, the LFOs, gains) is ramped or follows a
//  one-pole, so nothing steps.
// ============================================================================
#include <vector>
#include "Common.h"
#include "ParamTable.h"

namespace eightball
{
// ---------------------------------------------------------------------------
// building blocks
// ---------------------------------------------------------------------------
struct OnePole
{
    double z = 0;
    double lp (double x, double coef) { z += coef * (x - z); if (std::abs (z) < 1e-30) z = 0; return z; }
    void reset() { z = 0; }
};

// coefficient of a one-pole low-pass for a cutoff in Hz
inline double onePoleCoef (double hz, double sr) { return 1.0 - std::exp (-kTwoPi * clampd (hz, 1.0, sr * 0.49) / sr); }

struct DelayLine
{
    std::vector<double> buf;
    int size = 1, w = 0;
    void prepare (int samples) { size = std::max (4, samples); buf.assign ((size_t) size, 0.0); w = 0; }
    void reset() { std::fill (buf.begin(), buf.end(), 0.0); }
    void write (double x) { buf[(size_t) w] = x; if (++w >= size) w = 0; }
    // read `d` samples back (fractional, linear interpolation); d in [1, size - 2]
    double read (double d) const
    {
        d = clampd (d, 1.0, (double) size - 2.0);
        const int di = (int) d;
        const double f = d - di;
        int r0 = w - di; if (r0 < 0) r0 += size;
        int r1 = r0 - 1; if (r1 < 0) r1 += size;
        return buf[(size_t) r0] + (buf[(size_t) r1] - buf[(size_t) r0]) * f;
    }
    double readInt (int d) const
    {
        d = d < 1 ? 1 : (d > size - 1 ? size - 1 : d);
        int r = w - d; if (r < 0) r += size;
        return buf[(size_t) r];
    }
};

// RBJ biquad (transposed direct form II)
struct Biquad
{
    double b0 = 1, b1 = 0, b2 = 0, a1 = 0, a2 = 0;
    double z1 = 0, z2 = 0;
    void reset() { z1 = z2 = 0; }
    void identity() { b0 = 1; b1 = b2 = a1 = a2 = 0; }
    double process (double x)
    {
        const double y = b0 * x + z1;
        z1 = b1 * x - a1 * y + z2;
        z2 = b2 * x - a2 * y;
        if (std::abs (z1) < 1e-30) z1 = 0;
        if (std::abs (z2) < 1e-30) z2 = 0;
        return y;
    }
    void set (double b0_, double b1_, double b2_, double a0, double a1_, double a2_)
    {
        const double inv = 1.0 / a0;
        b0 = b0_ * inv; b1 = b1_ * inv; b2 = b2_ * inv; a1 = a1_ * inv; a2 = a2_ * inv;
    }
    void lowpass (double hz, double q, double sr)
    {
        const double w = kTwoPi * clampd (hz, 10.0, sr * 0.49) / sr, c = std::cos (w), a = std::sin (w) / (2 * q);
        set ((1 - c) / 2, 1 - c, (1 - c) / 2, 1 + a, -2 * c, 1 - a);
    }
    void highpass (double hz, double q, double sr)
    {
        const double w = kTwoPi * clampd (hz, 10.0, sr * 0.49) / sr, c = std::cos (w), a = std::sin (w) / (2 * q);
        set ((1 + c) / 2, -(1 + c), (1 + c) / 2, 1 + a, -2 * c, 1 - a);
    }
    void peak (double hz, double q, double gainDb, double sr)
    {
        const double A = std::pow (10.0, gainDb / 40.0);
        const double w = kTwoPi * clampd (hz, 10.0, sr * 0.49) / sr, c = std::cos (w), a = std::sin (w) / (2 * q);
        set (1 + a * A, -2 * c, 1 - a * A, 1 + a / A, -2 * c, 1 - a / A);
    }
    void lowShelf (double hz, double gainDb, double sr)
    {
        const double A = std::pow (10.0, gainDb / 40.0), sa = std::sqrt (A);
        const double w = kTwoPi * clampd (hz, 10.0, sr * 0.49) / sr, c = std::cos (w), s = std::sin (w);
        const double beta = std::sqrt (2.0) * sa * s * 0.5;   // shelf slope S = 1
        set (A * ((A + 1) - (A - 1) * c + 2 * beta), 2 * A * ((A - 1) - (A + 1) * c), A * ((A + 1) - (A - 1) * c - 2 * beta),
             (A + 1) + (A - 1) * c + 2 * beta, -2 * ((A - 1) + (A + 1) * c), (A + 1) + (A - 1) * c - 2 * beta);
    }
    void highShelf (double hz, double gainDb, double sr)
    {
        const double A = std::pow (10.0, gainDb / 40.0), sa = std::sqrt (A);
        const double w = kTwoPi * clampd (hz, 10.0, sr * 0.49) / sr, c = std::cos (w), s = std::sin (w);
        const double beta = std::sqrt (2.0) * sa * s * 0.5;
        set (A * ((A + 1) + (A - 1) * c + 2 * beta), -2 * A * ((A - 1) + (A + 1) * c), A * ((A + 1) + (A - 1) * c - 2 * beta),
             (A + 1) - (A - 1) * c + 2 * beta, 2 * ((A - 1) - (A + 1) * c), (A + 1) - (A - 1) * c - 2 * beta);
    }
};

// ---------------------------------------------------------------------------
// one unit: the enable ramp and the dry/wet mix every unit shares
// ---------------------------------------------------------------------------
struct FxUnitBase
{
    double enable = 0;       // 0..1, follows the switch with a 3 ms time constant (settled in about 10 ms)
    double enableCoef = 0.01;
    bool dirty = false;      // the unit's state has been touched since its last reset
    void prepareBase (double sr) { enableCoef = smoothCoef (0.003, sr); enable = 0; dirty = false; }
    // Once per chunk: false when the unit is fully off and can be skipped (callers reset it once, see takeReset).
    bool stepEnable (bool on)
    {
        if (on || enable >= 1e-4) { dirty = true; return true; }
        enable = 0;
        return false;
    }
    bool takeReset() { const bool r = dirty; dirty = false; return r; }
    inline double rampEnable (bool on) { enable += ((on ? 1.0 : 0.0) - enable) * enableCoef; return enable; }
};

// ---------------------------------------------------------------------------
struct DistortionFx : FxUnitBase
{
    double sr = 48000;
    OnePole toneL, toneR;
    double holdL = 0, holdR = 0; int holdCount = 0;
    void prepare (double s) { sr = s; prepareBase (s); reset(); }
    void reset() { toneL.reset(); toneR.reset(); holdL = holdR = 0; holdCount = 0; }

    static double shape (int type, double x, double drive)
    {
        switch (type)
        {
            case driveHard: return clampd (x, -1.0, 1.0);
            case driveFold: return std::sin (x * kPi * 0.5);
            case driveCrush: { const double step = std::pow (2.0, -(15.0 - 13.0 * drive)); return clampd (std::round (x / step) * step, -1.0, 1.0); }
            default: return std::tanh (x);
        }
    }

    void process (double* L, double* R, int n, const std::array<double, kNumParams>& v)
    {
        const bool on = v[dstOn] >= 0.5;
        if (! stepEnable (on)) { if (takeReset()) reset(); return; }
        const int type = (int) v[dstType];
        const double drive = v[dstDrive], mix = v[dstMix];
        const double gain = 1.0 + 30.0 * drive * drive;
        const double comp = 1.0 / std::pow (gain, 0.35);            // keep the level roughly where it was
        const double out = dbToGain (v[dstOut]);
        const double tone = v[dstTone];
        const double toneCoef = onePoleCoef (400.0 * std::pow (50.0, tone), sr);
        const bool useTone = tone < 0.999;
        const int hold = type == driveCrush ? 1 + (int) (drive * 24.0) : 1;
        for (int i = 0; i < n; ++i)
        {
            const double en = rampEnable (on) * mix;
            double wl = shape (type, L[i] * gain, drive) * comp, wr = shape (type, R[i] * gain, drive) * comp;
            if (hold > 1)
            {
                if (holdCount <= 0) { holdL = wl; holdR = wr; holdCount = hold; }
                --holdCount;
                wl = holdL; wr = holdR;
            }
            if (useTone) { wl = toneL.lp (wl, toneCoef); wr = toneR.lp (wr, toneCoef); }
            wl *= out; wr *= out;
            L[i] += en * (wl - L[i]);
            R[i] += en * (wr - R[i]);
        }
    }
};

// ---------------------------------------------------------------------------
struct ChorusFx : FxUnitBase
{
    double sr = 48000, phase = 0;
    DelayLine dl, dr;
    double fbL = 0, fbR = 0;
    void prepare (double s) { sr = s; prepareBase (s); dl.prepare ((int) (s * 0.07)); dr.prepare ((int) (s * 0.07)); reset(); }
    void reset() { dl.reset(); dr.reset(); fbL = fbR = 0; phase = 0; }

    void process (double* L, double* R, int n, const std::array<double, kNumParams>& v)
    {
        const bool on = v[choOn] >= 0.5;
        if (! stepEnable (on)) { if (takeReset()) reset(); return; }
        const double rate = v[choRate], depth = v[choDepth], centre = v[choDelay] * 0.001 * sr;
        const double fb = v[choFeedback], spread = v[choSpread], mix = v[choMix];
        const double inc = rate / sr;
        for (int i = 0; i < n; ++i)
        {
            const double en = rampEnable (on) * mix;
            phase += inc; if (phase >= 1.0) phase -= 1.0;
            const double ml = std::sin (kTwoPi * phase), mr = std::sin (kTwoPi * (phase + 0.25 * spread));
            const double tl = std::max (1.0, centre * (1.0 + 0.9 * depth * ml));
            const double tr = std::max (1.0, centre * (1.0 + 0.9 * depth * mr));
            const double wl = dl.read (tl), wr = dr.read (tr);
            dl.write (L[i] + fb * wl);
            dr.write (R[i] + fb * wr);
            L[i] += en * (wl - L[i]);
            R[i] += en * (wr - R[i]);
        }
    }
};

// ---------------------------------------------------------------------------
struct PhaserFx : FxUnitBase
{
    static constexpr int kMaxStages = 12;
    double sr = 48000, phase = 0;
    double x1[2][kMaxStages] {}, y1[2][kMaxStages] {};
    double last[2] {};
    void prepare (double s) { sr = s; prepareBase (s); reset(); }
    void reset() { for (int c = 0; c < 2; ++c) { for (int k = 0; k < kMaxStages; ++k) x1[c][k] = y1[c][k] = 0; last[c] = 0; } phase = 0; }

    double channel (int c, double x, double a, int stages, double fb)
    {
        double s = x + fb * last[c];
        for (int k = 0; k < stages; ++k)
        {
            const double y = a * s + x1[c][k] - a * y1[c][k];
            x1[c][k] = s; y1[c][k] = std::abs (y) < 1e-30 ? 0.0 : y;
            s = y;
        }
        last[c] = s;
        return s;
    }

    void process (double* L, double* R, int n, const std::array<double, kNumParams>& v)
    {
        const bool on = v[phaOn] >= 0.5;
        if (! stepEnable (on)) { if (takeReset()) reset(); return; }
        const double rate = v[phaRate], depth = v[phaDepth], fb = v[phaFeedback], mix = v[phaMix];
        const int stages = 4 * (1 + (int) clampd (v[phaStages], 0, 2));
        const double fc = 200.0 * std::pow (20.0, v[phaCenter]);   // 200 Hz .. 4 kHz
        const double inc = rate / sr;
        for (int i = 0; i < n; ++i)
        {
            const double en = rampEnable (on) * mix;
            phase += inc; if (phase >= 1.0) phase -= 1.0;
            const double lfoL = std::sin (kTwoPi * phase), lfoR = std::sin (kTwoPi * (phase + 0.25));
            const double fL = fc * std::pow (2.0, 2.0 * depth * lfoL), fR = fc * std::pow (2.0, 2.0 * depth * lfoR);
            const double tL = std::tan (kPi * clampd (fL, 20.0, sr * 0.45) / sr), tR = std::tan (kPi * clampd (fR, 20.0, sr * 0.45) / sr);
            const double aL = (tL - 1.0) / (tL + 1.0), aR = (tR - 1.0) / (tR + 1.0);
            const double wl = 0.5 * (L[i] + channel (0, L[i], aL, stages, fb));
            const double wr = 0.5 * (R[i] + channel (1, R[i], aR, stages, fb));
            L[i] += en * (wl - L[i]);
            R[i] += en * (wr - R[i]);
        }
    }
};

// ---------------------------------------------------------------------------
struct DelayFx : FxUnitBase
{
    double sr = 48000, timeCur = -1, timeCoef = 0.001;
    DelayLine dl, dr;
    OnePole toneL, toneR;
    void prepare (double s) { sr = s; prepareBase (s); dl.prepare ((int) (s * 2.2)); dr.prepare ((int) (s * 2.2)); timeCoef = smoothCoef (0.05, s); reset(); }
    void reset() { dl.reset(); dr.reset(); toneL.reset(); toneR.reset(); timeCur = -1; }

    void process (double* L, double* R, int n, const std::array<double, kNumParams>& v, double bpm)
    {
        const bool on = v[dlyOn] >= 0.5;
        if (! stepEnable (on)) { if (takeReset()) reset(); return; }
        double seconds = v[dlySync] >= 0.5 ? kLfoDivBeats[(int) clampd (v[dlyDiv], 0, kNumLfoDivs - 1)] * 60.0 / bpm : v[dlyTime] * 0.001;
        const double target = clampd (seconds * sr, 1.0, (double) dl.size - 2.0);
        if (timeCur < 0) timeCur = target;
        const double fb = v[dlyFeedback], mix = v[dlyMix];
        const bool pingPong = v[dlyPingPong] >= 0.5;
        const double toneCoef = onePoleCoef (300.0 * std::pow (60.0, v[dlyTone]), sr);
        for (int i = 0; i < n; ++i)
        {
            const double en = rampEnable (on) * mix;
            timeCur += (target - timeCur) * timeCoef;
            // the tone filter sits at the delay's output, so every repeat gets darker than the last
            const double wl = toneL.lp (dl.read (timeCur), toneCoef), wr = toneR.lp (dr.read (timeCur), toneCoef);
            if (pingPong)
            {
                dl.write (0.5 * (L[i] + R[i]) + fb * wr);
                dr.write (fb * wl);
            }
            else
            {
                dl.write (L[i] + fb * wl);
                dr.write (R[i] + fb * wr);
            }
            L[i] += en * (wl - L[i]);
            R[i] += en * (wr - R[i]);
        }
    }
};

// ---------------------------------------------------------------------------
// Freeverb-style: 8 parallel combs (damped) + 4 series all-passes per channel, with a pre-delay.
struct ReverbFx : FxUnitBase
{
    static constexpr int kCombs = 8, kAllpasses = 4;
    static constexpr int kCombLen[kCombs] { 1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617 };   // at 44.1 kHz
    static constexpr int kApLen[kAllpasses] { 556, 441, 341, 225 };
    static constexpr int kSpread = 23;
    double sr = 48000, scale = 1, sizeCur = -1, sizeCoef = 0.001;
    DelayLine comb[2][kCombs], ap[2][kAllpasses], pre[2];
    double combLp[2][kCombs] {};
    void prepare (double s)
    {
        sr = s; prepareBase (s);
        scale = s / 44100.0;
        sizeCoef = smoothCoef (0.1, s);
        for (int c = 0; c < 2; ++c)
        {
            for (int k = 0; k < kCombs; ++k) comb[c][k].prepare ((int) ((kCombLen[k] + kSpread) * scale * 1.6) + 4);
            for (int k = 0; k < kAllpasses; ++k) ap[c][k].prepare ((int) ((kApLen[k] + kSpread) * scale) + 4);
            pre[c].prepare ((int) (s * 0.21));
        }
        reset();
    }
    void reset()
    {
        for (int c = 0; c < 2; ++c)
        {
            for (int k = 0; k < kCombs; ++k) { comb[c][k].reset(); combLp[c][k] = 0; }
            for (int k = 0; k < kAllpasses; ++k) ap[c][k].reset();
            pre[c].reset();
        }
        sizeCur = -1;
    }

    double channel (int c, double x, double sizeMul, double feedback, double damp)
    {
        double acc = 0;
        for (int k = 0; k < kCombs; ++k)
        {
            auto& d = comb[c][k];
            const double len = (kCombLen[k] + (c ? kSpread : 0)) * scale * sizeMul;
            const double y = d.read (len);
            double& lp = combLp[c][k];
            lp += (y - lp) * (1.0 - damp);
            if (std::abs (lp) < 1e-30) lp = 0;
            d.write (x + lp * feedback);
            acc += y;
        }
        for (int k = 0; k < kAllpasses; ++k)
        {
            auto& d = ap[c][k];
            const double y = d.readInt ((int) ((kApLen[k] + (c ? kSpread : 0)) * scale));
            const double in = acc + 0.5 * y;
            d.write (in);
            acc = y - 0.5 * in;
            // (the classic allpass: out = -in + y with feedback 0.5; this form keeps unity gain)
        }
        return acc;
    }

    void process (double* L, double* R, int n, const std::array<double, kNumParams>& v)
    {
        const bool on = v[revOn] >= 0.5;
        if (! stepEnable (on)) { if (takeReset()) reset(); return; }
        const double sizeTarget = 0.6 + 0.9 * v[revSize];
        if (sizeCur < 0) sizeCur = sizeTarget;
        const double feedback = 0.70 + 0.28 * v[revDecay];
        const double damp = 0.05 + 0.9 * v[revDamp];
        const double preSamples = clampd (v[revPreDelay] * 0.001 * sr, 1.0, (double) pre[0].size - 2.0);
        const double width = v[revWidth], mix = v[revMix];
        const double wet1 = 0.5 + 0.5 * width, wet2 = 0.5 - 0.5 * width;
        const double inGain = 0.05;   // about Freeverb's level (its 0.015 input gain x 3 wet scale)
        for (int i = 0; i < n; ++i)
        {
            const double en = rampEnable (on) * mix;
            sizeCur += (sizeTarget - sizeCur) * sizeCoef;
            pre[0].write (L[i]); pre[1].write (R[i]);
            const double xl = pre[0].read (preSamples), xr = pre[1].read (preSamples);
            const double in = (xl + xr) * inGain;
            const double a = channel (0, in, sizeCur, feedback, damp);
            const double b = channel (1, in, sizeCur, feedback, damp);
            const double wl = a * wet1 + b * wet2, wr = b * wet1 + a * wet2;
            L[i] += en * (wl - L[i]);
            R[i] += en * (wr - R[i]);
        }
    }
};

// ---------------------------------------------------------------------------
struct EqFx : FxUnitBase
{
    double sr = 48000;
    Biquad lowCut[2], highCut[2], low[2], mid[2], high[2];
    bool useLowCut = false, useHighCut = false, useLow = false, useMid = false, useHigh = false;
    void prepare (double s) { sr = s; prepareBase (s); reset(); }
    void reset() { for (int c = 0; c < 2; ++c) { lowCut[c].reset(); highCut[c].reset(); low[c].reset(); mid[c].reset(); high[c].reset(); } }

    void process (double* L, double* R, int n, const std::array<double, kNumParams>& v)
    {
        const bool on = v[eqOn] >= 0.5;
        if (! stepEnable (on)) { if (takeReset()) reset(); return; }
        useLowCut = v[eqLowCut] > 20.5;
        useHighCut = v[eqHighCut] < 19900.0;
        useLow = std::abs (v[eqLowGain]) > 0.01;
        useMid = std::abs (v[eqMidGain]) > 0.01;
        useHigh = std::abs (v[eqHighGain]) > 0.01;
        for (int c = 0; c < 2; ++c)
        {
            if (useLowCut) lowCut[c].highpass (v[eqLowCut], 0.7071, sr); else lowCut[c].reset();
            if (useHighCut) highCut[c].lowpass (v[eqHighCut], 0.7071, sr); else highCut[c].reset();
            if (useLow) low[c].lowShelf (v[eqLowFreq], v[eqLowGain], sr); else low[c].reset();
            if (useMid) mid[c].peak (v[eqMidFreq], v[eqMidQ], v[eqMidGain], sr); else mid[c].reset();
            if (useHigh) high[c].highShelf (v[eqHighFreq], v[eqHighGain], sr); else high[c].reset();
        }
        const double mix = v[eqMix];
        for (int i = 0; i < n; ++i)
        {
            const double en = rampEnable (on) * mix;
            double wl = L[i], wr = R[i];
            if (useLowCut)  { wl = lowCut[0].process (wl);  wr = lowCut[1].process (wr); }
            if (useLow)     { wl = low[0].process (wl);     wr = low[1].process (wr); }
            if (useMid)     { wl = mid[0].process (wl);     wr = mid[1].process (wr); }
            if (useHigh)    { wl = high[0].process (wl);    wr = high[1].process (wr); }
            if (useHighCut) { wl = highCut[0].process (wl); wr = highCut[1].process (wr); }
            L[i] += en * (wl - L[i]);
            R[i] += en * (wr - R[i]);
        }
    }
};

// ---------------------------------------------------------------------------
struct CompressorFx : FxUnitBase
{
    double sr = 48000, env = 0, limEnv = 0, grDb = 0, limCoefRel = 0.001;
    void prepare (double s) { sr = s; prepareBase (s); limCoefRel = smoothCoef (0.05, s); reset(); }
    void reset() { env = 0; limEnv = 1; grDb = 0; }
    double gainReductionDb() const { return grDb; }   // the deepest reduction since the last call to takeGr()
    double takeGr() { const double g = grDb; grDb = 0; return g; }

    void process (double* L, double* R, int n, const std::array<double, kNumParams>& v)
    {
        const bool on = v[cmpOn] >= 0.5;
        if (! stepEnable (on)) { if (takeReset()) reset(); return; }
        const double thresh = v[cmpThresh], ratio = std::max (1.0, v[cmpRatio]);
        const double att = smoothCoef (v[cmpAttack] * 0.001, sr), rel = smoothCoef (v[cmpRelease] * 0.001, sr);
        const double makeup = dbToGain (v[cmpMakeup]), mix = v[cmpMix];
        const bool limit = v[cmpLimit] >= 0.5;
        const double ceiling = dbToGain (-0.3);
        for (int i = 0; i < n; ++i)
        {
            const double en = rampEnable (on) * mix;
            const double x = std::max (std::abs (L[i]), std::abs (R[i]));
            env += (x - env) * (x > env ? att : rel);
            if (env < 1e-30) env = 0;
            const double lvl = 20.0 * std::log10 (std::max (env, 1e-9));
            const double over = lvl - thresh;
            const double red = over > 0 ? over * (1.0 - 1.0 / ratio) : 0.0;
            double g = dbToGain (-red) * makeup;
            double wl = L[i] * g, wr = R[i] * g;
            if (limit)
            {
                const double p = std::max (std::abs (wl), std::abs (wr));
                const double need = p > ceiling ? ceiling / p : 1.0;
                // instant attack, 50 ms release
                limEnv = need < limEnv ? need : limEnv + (need - limEnv) * limCoefRel;
                if (limEnv > 1.0) limEnv = 1.0;
                wl *= limEnv; wr *= limEnv;
                g *= limEnv;
            }
            const double totalRed = -20.0 * std::log10 (std::max (g / makeup, 1e-9));
            if (totalRed > grDb) grDb = totalRed;
            L[i] += en * (wl - L[i]);
            R[i] += en * (wr - R[i]);
        }
    }
};

// ---------------------------------------------------------------------------
class FxChain
{
public:
    void prepare (double sr)
    {
        dist.prepare (sr); chorus.prepare (sr); phaser.prepare (sr); delay.prepare (sr);
        reverb.prepare (sr); eq.prepare (sr); comp.prepare (sr);
    }
    void reset() { dist.reset(); chorus.reset(); phaser.reset(); delay.reset(); reverb.reset(); eq.reset(); comp.reset(); }

    // The order the fxOrder slots give; a unit named twice runs once (first slot wins); units
    // missing from the slots run last in their default order.
    static void resolveOrder (const std::array<double, kNumParams>& v, int* order)
    {
        bool used[kNumFx] {};
        int n = 0;
        for (int p = 0; p < kNumFx; ++p)
        {
            const int u = (int) clampd (v[(size_t) fxOrderParam (p)], 0, kNumFx - 1);
            if (! used[u]) { used[u] = true; order[n++] = u; }
        }
        for (int u = 0; u < kNumFx; ++u) if (! used[u]) order[n++] = u;
    }

    void process (double* L, double* R, int n, const std::array<double, kNumParams>& v, double bpm)
    {
        int order[kNumFx];
        resolveOrder (v, order);
        for (int p = 0; p < kNumFx; ++p)
        {
            switch (order[p])
            {
                case fxDistortion: dist.process (L, R, n, v); break;
                case fxChorus:     chorus.process (L, R, n, v); break;
                case fxPhaser:     phaser.process (L, R, n, v); break;
                case fxDelay:      delay.process (L, R, n, v, bpm); break;
                case fxReverb:     reverb.process (L, R, n, v); break;
                case fxEq:         eq.process (L, R, n, v); break;
                default:           comp.process (L, R, n, v); break;
            }
        }
    }

    double takeGainReduction() { return comp.takeGr(); }

    DistortionFx dist;
    ChorusFx chorus;
    PhaserFx phaser;
    DelayFx delay;
    ReverbFx reverb;
    EqFx eq;
    CompressorFx comp;
};
} // namespace eightball
