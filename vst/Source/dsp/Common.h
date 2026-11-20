#pragma once
// ============================================================================
//  Shared DSP building blocks. Header-only, plain C++: no JUCE, no allocation
//  after prepare(), no locks. The same code compiles to WebAssembly for the
//  HTML build, so keep it to doubles and std:: maths.
// ============================================================================
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>

namespace eightball
{
constexpr double kPi     = 3.141592653589793;
constexpr double kTwoPi  = 6.283185307179586;
constexpr int    kChunk  = 32;    // control rate: modulation once per 32 samples, per-sample ramps in between
constexpr double kSilence = 1e-4; // -80 dB

inline double clampd (double v, double lo, double hi) { return v < lo ? lo : (v > hi ? hi : v); }
inline double dbToGain (double db) { return std::pow (10.0, db / 20.0); }
inline double noteToHz (double note) { return 440.0 * std::pow (2.0, (note - 69.0) / 12.0); }

// Deterministic RNG (LCG). The same sequence in every build.
struct Rng
{
    uint32_t s = 0x2545F491u;
    void seed (uint32_t v) { s = v; }
    uint32_t next() { s = s * 1664525u + 1013904223u; return s; }
    double uni() { return (double) (next() >> 8) * (1.0 / 16777216.0); } // [0, 1)
    double bi()  { return uni() * 2.0 - 1.0; }                            // [-1, 1)
};

// Output safety clipper: exactly linear up to 0.8 (-1.9 dBFS), then a tanh knee
// that never exceeds 1. Below the knee it adds nothing.
inline double safetyClip (double x)
{
    const double a = std::abs (x);
    if (a <= 0.8) return x;
    const double y = 0.8 + 0.2 * std::tanh ((a - 0.8) / 0.2);
    return x < 0 ? -y : y;
}

// One-pole coefficient for a time constant in seconds at a given update rate
inline double smoothCoef (double seconds, double updatesPerSecond)
{
    return 1.0 - std::exp (-1.0 / (std::max (seconds, 1e-5) * updatesPerSecond));
}

// ---------------------------------------------------------------------------
// Half-band filters for 2x oversampling: polyphase IIR (two all-pass chains),
// designed at start-up from a closed formula (the Valenzuela-Constantinides
// design as published in HIIR). 8 coefficients, transition 0.04: flat to
// 20 kHz at 48 kHz, images and aliases from 28 kHz down by about 99 dB.
// Not linear phase: about 1.3 samples of delay at the base rate (kLatency2x
// rounds it; measured by the tests).
// ---------------------------------------------------------------------------
struct HalfbandDesign
{
    static constexpr int kMax = 12;
    int n = 0;
    double c[kMax] {};
    HalfbandDesign (int numCoefs, double transition) : n (numCoefs)
    {
        const int order = n * 2 + 1;
        double k = std::tan ((1.0 - 2.0 * transition) * kPi / 4.0);
        k *= k;
        const double kk = std::sqrt (std::sqrt (1.0 - k * k));
        const double e = 0.5 * (1.0 - kk) / (1.0 + kk);
        const double e4 = e * e * e * e;
        const double q = e * (1.0 + e4 * (2.0 + e4 * (15.0 + 150.0 * e4)));
        for (int idx = 0; idx < n; ++idx)
        {
            const int cc = idx + 1;
            double num = 0, den = 0, t;
            int i = 0, j = 1;
            do { t = std::pow (q, i * (i + 1)) * std::sin ((i * 2 + 1) * cc * kPi / order) * j; num += t; j = -j; ++i; } while (std::abs (t) > 1e-100);
            num *= std::pow (q, 0.25);
            i = 1; j = -1;
            do { t = std::pow (q, i * i) * std::cos (i * 2 * cc * kPi / order) * j; den += t; j = -j; ++i; } while (std::abs (t) > 1e-100);
            den += 0.5;
            const double ww = num / den, w2 = ww * ww;
            const double x = std::sqrt ((1.0 - w2 * k) * (1.0 - w2 / k)) / (1.0 + w2);
            c[idx] = (1.0 - x) / (1.0 + x);
        }
    }
};

inline const HalfbandDesign& halfband2x() { static const HalfbandDesign d (8, 0.04); return d; }

struct HalfbandState
{
    static constexpr int kLatency2x = 1;   // base-rate samples, measured by the tests (about 1.3)
    double x[HalfbandDesign::kMax] {}, y[HalfbandDesign::kMax] {};
    void reset() { for (int i = 0; i < HalfbandDesign::kMax; ++i) x[i] = y[i] = 0; }
    void run (const HalfbandDesign& d, double& s0, double& s1)
    {
        int i = 0;
        for (; i + 1 < d.n; i += 2)
        {
            const double t0 = (s0 - y[i]) * d.c[i] + x[i];
            const double t1 = (s1 - y[i + 1]) * d.c[i + 1] + x[i + 1];
            x[i] = s0; x[i + 1] = s1;
            y[i] = t0; y[i + 1] = t1;
            s0 = t0; s1 = t1;
        }
        if (i < d.n)
        {
            const double t0 = (s0 - y[i]) * d.c[i] + x[i];
            x[i] = s0; y[i] = t0; s0 = t0;
        }
    }
    // two inputs at 2x -> one output at the base rate
    double down (const HalfbandDesign& d, double in0, double in1)
    {
        double s0 = in1, s1 = in0;
        run (d, s0, s1);
        return 0.5 * (s0 + s1);
    }
};

// TPT state-variable filter, one 12 dB stage with low / band / high outputs.
// The coefficients are computed per sample (so cutoff and resonance move
// smoothly) once per filter and shared by its stages and channels.
struct SVFCoefs
{
    double a1 = 1, a2 = 0, a3 = 0, k = 2;
    void set (double g, double k_)
    {
        k = k_;
        a1 = 1.0 / (1.0 + g * (g + k));
        a2 = g * a1;
        a3 = g * a2;
    }
};

struct SVF
{
    double ic1 = 0, ic2 = 0;
    void reset() { ic1 = ic2 = 0; }
    static double gFor (double fc, double sr) { return std::tan (kPi * clampd (fc, 10.0, sr * 0.45) / sr); }
    static double kFor (double reso) { return 2.0 - 1.9 * clampd (reso, 0.0, 1.0); } // Q 0.5 .. 10
    // returns the selected output (0 lp, 1 bp, 2 hp)
    double process (double x, const SVFCoefs& c, int type)
    {
        const double a1 = c.a1, a2 = c.a2, a3 = c.a3, k = c.k;
        const double v3 = x - ic2;
        const double v1 = a1 * ic1 + a2 * v3;
        const double v2 = ic2 + a2 * ic1 + a3 * v3;
        ic1 = 2.0 * v1 - ic1;
        ic2 = 2.0 * v2 - ic2;
        // flush denormals in the feedback path
        if (std::abs (ic1) < 1e-30) ic1 = 0;
        if (std::abs (ic2) < 1e-30) ic2 = 0;
        if (type == 1) return v1;                      // band-pass
        if (type == 2) return x - k * v1 - v2;         // high-pass
        return v2;                                     // low-pass
    }
};
} // namespace eightball
