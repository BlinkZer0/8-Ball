#pragma once
// ============================================================================
//  Freeform multi-point envelopes ("articulators").
//
//  An EnvSpec is a list of points (time, level, tension of the segment that
//  leads to the point), a sustain point, an optional loop region and a tempo
//  sync flag. Levels are always 0..1; the user of the envelope decides what
//  that means (amplitude: gain; pitch: (2 level - 1) x amount semitones;
//  modulation index: 1 + (2 level - 1) x amount; filter cutoff: octaves x amount).
//
//  Runtime: the level is evaluated once per control chunk and ramped per
//  sample by the voice. While the gate is held the envelope stops at the
//  sustain point, or cycles the loop region. On release it jumps to the
//  release part (after the sustain point or the loop). Whenever the envelope
//  jumps (release, retrigger, voice steal) the difference between the level
//  it was at and the level it jumps to fades out over the next segment, so
//  nothing clicks.
// ============================================================================
#include "Common.h"

namespace eightball
{
constexpr int kMaxEnvPoints = 32;

struct EnvPoint { float time = 0, level = 0, tension = 0; };   // time: seconds, or beats when synced

struct EnvSpec
{
    int numPoints = 0;
    std::array<EnvPoint, kMaxEnvPoints> pts {};
    int sustain = -1;     // point index, -1 = none (one-shot)
    int loopStart = -1;   // point indices, -1 = no loop
    int loopEnd = -1;
    bool sync = false;    // times in beats

    void add (float t, float l, float tension = 0.0f)
    {
        if (numPoints < kMaxEnvPoints) pts[(size_t) numPoints++] = { t, l, tension };
    }
    double endTime() const { return numPoints > 0 ? pts[(size_t) numPoints - 1].time : 0.0; }
    bool hasLoop() const { return loopStart >= 0 && loopEnd > loopStart && loopEnd < numPoints; }
    bool hasSustain() const { return sustain >= 0 && sustain < numPoints; }

    // The curve of a segment: tension 0 = linear, > 0 slow start (concave), < 0 fast start (convex).
    // u is clamped: point times are floats and the position is a double, so u can land a hair
    // outside 0..1 at a segment's end, and pow() of a negative base would be NaN.
    static double curve (double u, double tension)
    {
        u = clampd (u, 0.0, 1.0);
        if (tension > 1e-6)  return std::pow (u, 1.0 + 4.0 * tension);
        if (tension < -1e-6) return 1.0 - std::pow (1.0 - u, 1.0 - 4.0 * tension);
        return u;
    }

    // Level at time t (no gate logic). seg is a cached segment index (in/out).
    double eval (double t, int& seg) const
    {
        if (numPoints == 0) return 0.0;
        if (numPoints == 1 || t <= pts[0].time) return pts[0].level;
        if (t >= pts[(size_t) numPoints - 1].time) return pts[(size_t) numPoints - 1].level;
        if (seg < 0 || seg >= numPoints - 1) seg = 0;
        while (seg > 0 && t < pts[(size_t) seg].time) --seg;
        while (seg < numPoints - 2 && t >= pts[(size_t) seg + 1].time) ++seg;
        const auto& a = pts[(size_t) seg];
        const auto& b = pts[(size_t) seg + 1];
        const double len = (double) b.time - (double) a.time;
        const double u = len > 1e-9 ? clampd ((t - (double) a.time) / len, 0.0, 1.0) : 1.0;
        return a.level + (b.level - a.level) * curve (u, b.tension);
    }

    // length of the segment that starts at point i (for click-free jumps)
    double segmentLength (int i) const
    {
        if (i < 0 || i + 1 >= numPoints) return 1e-3;
        return std::max (1e-4, (double) pts[(size_t) i + 1].time - pts[(size_t) i].time);
    }

    // Common shapes
    static EnvSpec adsr (float a, float d, float s, float r, float peak = 1.0f)
    {
        EnvSpec e;
        e.add (0.0f, 0.0f);
        e.add (a, peak, 0.0f);
        e.add (a + d, s, -0.5f);
        e.add (a + d + r, 0.0f, -0.5f);
        e.sustain = 2;
        return e;
    }
    static EnvSpec flat (float level)
    {
        EnvSpec e;
        e.add (0.0f, level);
        e.add (1.0f, level);
        e.sustain = 1;
        return e;
    }
};

struct EnvState
{
    enum Stage { Idle = 0, Held, Released, Finished };
    int stage = Idle;
    double t = 0;             // position in the spec's time units
    double level = 0;         // last evaluated level
    double offset = 0;        // level difference being faded out after a jump
    double offsetLen = 1e-3;  // over this many time units
    double offsetT = 0;
    int seg = 0;

    // (Re)start. From an active state the old level fades into the new attack.
    void gateOn (const EnvSpec& s)
    {
        if (active() && s.numPoints > 0) jump (s, 0, 0.0);
        else { offset = 0; t = 0; seg = 0; }
        stage = Held;
    }
    void gateOff (const EnvSpec& s)
    {
        if (stage != Held) return;
        stage = Released;
        // jump to the release part: after the sustain point, or after the loop
        int from = -1;
        if (s.hasSustain()) from = s.sustain;
        else if (s.hasLoop()) from = s.loopEnd;
        if (from >= 0 && t < s.pts[(size_t) from].time + 1e-9) jump (s, from, s.pts[(size_t) from].time);
    }
    void kill() { stage = Idle; level = 0; offset = 0; }
    bool active() const { return stage == Held || stage == Released; }
    bool finished() const { return stage == Finished; }

    // Advance by dt (seconds, or beats when synced) and return the level.
    double advance (const EnvSpec& s, double dt)
    {
        if (stage == Idle || stage == Finished) return level;
        if (s.numPoints == 0) { level = 0; stage = Finished; return 0; }
        t += dt;
        if (stage == Held)
        {
            if (s.hasLoop())
            {
                const double ls = s.pts[(size_t) s.loopStart].time, le = s.pts[(size_t) s.loopEnd].time;
                if (t >= le && le > ls) { t = ls + std::fmod (t - ls, le - ls); seg = s.loopStart; }
            }
            else if (s.hasSustain())
            {
                const double st = s.pts[(size_t) s.sustain].time;
                if (t > st) t = st;
            }
        }
        double v = s.eval (t, seg);
        if (offset != 0)
        {
            const double u = clampd ((t - offsetT) / offsetLen, 0.0, 1.0);
            v += offset * (1.0 - u);
            if (u >= 1.0) offset = 0;
        }
        level = v;
        const bool holding = stage == Held && (s.hasLoop() || s.hasSustain());
        if (! holding && t >= s.endTime()) { stage = Finished; level = s.pts[(size_t) s.numPoints - 1].level; }
        return level;
    }

private:
    void jump (const EnvSpec& s, int toPoint, double toTime)
    {
        int sg = toPoint;
        const double target = s.eval (toTime, sg);
        offset = level - target;
        offsetLen = s.segmentLength (toPoint);
        offsetT = toTime;
        t = toTime;
        seg = sg;
    }
};
} // namespace eightball
