#pragma once
// ============================================================================
//  Operator waveforms: a set of partials (level + phase each, up to 128) is
//  baked into a band-limited, mipmapped wavetable. Drawn shapes are turned
//  into partials by a DFT first, so every shape goes through the same path.
//
//  Mip levels: 8 tables of 2048 samples, keeping 128, 64, 32, 16, 8, 4, 2
//  and 1 harmonics. At play time the operator picks the fullest table whose
//  top harmonic stays below Nyquist for its frequency, so high notes don't
//  alias. All levels share one normalisation factor (the peak of the fullest
//  table), so a note keeps its level when it crosses a mip boundary.
//
//  Building a table costs about 2 ms (phasor rotation, no sin() per sample)
//  and happens on the message thread; the audio thread only reads.
// ============================================================================
#include "Common.h"

namespace eightball
{
constexpr int kMaxPartials = 128;
constexpr int kDrawPoints  = 256;   // drawn shape resolution (one cycle)

// What the editor edits and what presets store.
struct WaveSpec
{
    bool drawn = false;                              // true: shape[] is the source, partials are derived
    std::array<float, kMaxPartials> level {};        // partial h+1 amplitude, 0..1
    std::array<float, kMaxPartials> phase {};        // partial phase in turns, 0..1
    std::array<float, kDrawPoints> shape {};         // drawn cycle, -1..1

    static WaveSpec sine()     { WaveSpec w; w.level[0] = 1; return w; }
    static WaveSpec saw()      { WaveSpec w; for (int h = 1; h <= kMaxPartials; ++h) w.level[(size_t) (h - 1)] = 1.0f / (float) h; return w; }
    static WaveSpec square()   { WaveSpec w; for (int h = 1; h <= kMaxPartials; h += 2) w.level[(size_t) (h - 1)] = 1.0f / (float) h; return w; }
    static WaveSpec triangle()
    {
        WaveSpec w;
        for (int h = 1; h <= kMaxPartials; h += 2)
        {
            w.level[(size_t) (h - 1)] = 1.0f / (float) (h * h);
            w.phase[(size_t) (h - 1)] = ((h - 1) / 2) % 2 ? 0.5f : 0.0f;   // alternate signs
        }
        return w;
    }
    // sine for the first half of the cycle, silence for the second (TX81Z-style "half sine")
    static WaveSpec halfSine()
    {
        WaveSpec w;
        w.drawn = true;
        for (int i = 0; i < kDrawPoints; ++i)
            w.shape[(size_t) i] = i < kDrawPoints / 2 ? (float) std::sin (kTwoPi * i / kDrawPoints) : 0.0f;
        return w;
    }
};

struct Wavetable
{
    static constexpr int kSize = 2048, kLevels = 8;
    // table[level][i], with a guard sample for linear interpolation
    std::array<std::array<float, kSize + 1>, kLevels> table {};
    static int harmonicsAt (int level) { return kMaxPartials >> level; }

    // The fullest table whose top harmonic is below Nyquist for a frequency of dt cycles per sample.
    static int levelFor (double dt)
    {
        const double allowed = dt > 1e-9 ? 0.5 / dt : 1e9;
        for (int l = 0; l < kLevels; ++l)
            if (harmonicsAt (l) <= allowed) return l;
        return kLevels - 1;
    }

    // phase in turns (any value; a non-finite phase reads as silence instead of indexing garbage)
    double lookup (int level, double phase) const
    {
        if (! (std::abs (phase) < 1e12)) return 0.0;
        phase -= std::floor (phase);
        const double p = phase * kSize;
        const int i = (int) p;
        const double f = p - i;
        const auto& t = table[(size_t) level];
        return t[(size_t) i] + (t[(size_t) i + 1] - t[(size_t) i]) * f;
    }
};

// Partials of a drawn shape: a plain DFT of the 256-point cycle (128 bins). DC is dropped.
inline void partialsFromShape (const std::array<float, kDrawPoints>& shape, std::array<float, kMaxPartials>& level,
                               std::array<float, kMaxPartials>& phase)
{
    for (int h = 1; h <= kMaxPartials; ++h)
    {
        double re = 0, im = 0;
        for (int i = 0; i < kDrawPoints; ++i)
        {
            const double a = kTwoPi * h * i / kDrawPoints;
            re += shape[(size_t) i] * std::cos (a);
            im += shape[(size_t) i] * std::sin (a);
        }
        // shape(i) ~ sum a_h sin(2 pi h i/N + phi_h): a_h = 2|X|/N, phi from atan2
        const double mag = 2.0 * std::sqrt (re * re + im * im) / kDrawPoints;
        const double ph = std::atan2 (re, im);   // sin(a + phi) = sin a cos phi + cos a sin phi
        level[(size_t) (h - 1)] = (float) mag;
        double turns = ph / kTwoPi;
        turns -= std::floor (turns);
        phase[(size_t) (h - 1)] = (float) turns;
    }
}

// Bakes a spec into a mipmapped table. Returns the normalisation gain that was applied.
inline double buildWavetable (const WaveSpec& spec, Wavetable& out)
{
    std::array<float, kMaxPartials> level = spec.level, phase = spec.phase;
    if (spec.drawn) partialsFromShape (spec.shape, level, phase);

    for (int l = 0; l < Wavetable::kLevels; ++l)
    {
        auto& t = out.table[(size_t) l];
        t.fill (0.0f);
        const int H = Wavetable::harmonicsAt (l);
        for (int h = 1; h <= H; ++h)
        {
            const double a = level[(size_t) (h - 1)];
            if (a == 0.0) continue;
            // rotating phasor: s = sin(theta), c = cos(theta), theta += 2 pi h / N
            const double d = kTwoPi * h / Wavetable::kSize;
            const double cd = std::cos (d), sd = std::sin (d);
            const double th0 = kTwoPi * phase[(size_t) (h - 1)];
            double s = std::sin (th0), c = std::cos (th0);
            for (int i = 0; i < Wavetable::kSize; ++i)
            {
                t[(size_t) i] += (float) (a * s);
                const double s2 = s * cd + c * sd;
                c = c * cd - s * sd;
                s = s2;
            }
        }
    }
    double peak = 0;
    for (int i = 0; i < Wavetable::kSize; ++i) peak = std::max (peak, (double) std::abs (out.table[0][(size_t) i]));
    const double gain = peak > 1e-9 ? 1.0 / peak : 1.0;
    for (int l = 0; l < Wavetable::kLevels; ++l)
    {
        auto& t = out.table[(size_t) l];
        for (int i = 0; i < Wavetable::kSize; ++i) t[(size_t) i] = (float) (t[(size_t) i] * gain);
        t[Wavetable::kSize] = t[0];
    }
    return gain;
}

// The starter shapes, built once (call from prepare(), not from the audio callback).
inline const Wavetable& starterTable (int wave)
{
    static const std::array<Wavetable, 5> tables = []
    {
        std::array<Wavetable, 5> t;
        buildWavetable (WaveSpec::sine(), t[0]);
        buildWavetable (WaveSpec::saw(), t[1]);
        buildWavetable (WaveSpec::square(), t[2]);
        buildWavetable (WaveSpec::triangle(), t[3]);
        buildWavetable (WaveSpec::halfSine(), t[4]);
        return t;
    }();
    return tables[(size_t) clampd (wave, 0, 4)];
}

inline WaveSpec starterSpec (int wave)
{
    switch (wave)
    {
        case 1: return WaveSpec::saw();
        case 2: return WaveSpec::square();
        case 3: return WaveSpec::triangle();
        case 4: return WaveSpec::halfSine();
        default: return WaveSpec::sine();
    }
}
} // namespace eightball
