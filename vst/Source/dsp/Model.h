#pragma once
// ============================================================================
//  The Model: everything a voice needs that is not a host parameter.
//    - one baked Wavetable per operator (the "Custom" wave)
//    - the multi-point envelopes: 3 per operator (amp, pitch, mod index),
//      2 per filter (cutoff, level)
//    - the drawn LFO shapes
//  Built on the message thread (ModelStore) and handed to the engine as a
//  pointer that stays valid until the next one arrives.
// ============================================================================
#include "Wavetable.h"
#include "Envelope.h"
#include "ParamTable.h"

namespace eightball
{
enum EnvKind { envAmp, envPitch, envMod, kOpEnvKinds };
enum FltEnvKind { fenvCutoff, fenvLevel, kFltEnvKinds };
constexpr int kNumOpEnvs  = kNumOps * kOpEnvKinds;
constexpr int kNumFltEnvs = kNumFilters * kFltEnvKinds;
constexpr int kNumEnvs    = kNumOpEnvs + kNumFltEnvs;
constexpr int kLfoShapePoints = 64;

inline int opEnvIndex (int op, int kind)   { return op * kOpEnvKinds + kind; }
inline int fltEnvIndex (int flt, int kind) { return kNumOpEnvs + flt * kFltEnvKinds + kind; }

inline EnvSpec defaultEnv (int index)
{
    if (index < kNumOpEnvs)
    {
        switch (index % kOpEnvKinds)
        {
            case envAmp:   return EnvSpec::adsr (0.005f, 0.3f, 0.8f, 0.3f);
            case envPitch: return EnvSpec::flat (0.5f);
            default:       return EnvSpec::flat (0.5f);
        }
    }
    return (index - kNumOpEnvs) % kFltEnvKinds == fenvCutoff ? EnvSpec::adsr (0.005f, 0.4f, 0.5f, 0.4f) : EnvSpec::flat (1.0f);
}

struct LfoShape
{
    std::array<float, kLfoShapePoints> pts {};   // -1..1, one cycle
    static LfoShape sine()
    {
        LfoShape s;
        for (int i = 0; i < kLfoShapePoints; ++i) s.pts[(size_t) i] = (float) std::sin (kTwoPi * i / kLfoShapePoints);
        return s;
    }
};

struct Model
{
    std::array<const Wavetable*, kNumOps> tables {};   // custom tables (nullptr = sine)
    std::array<EnvSpec, kNumEnvs> envs;
    std::array<LfoShape, kNumLfos> lfoShapes;

    Model()
    {
        for (int i = 0; i < kNumEnvs; ++i) envs[(size_t) i] = defaultEnv (i);
        for (auto& s : lfoShapes) s = LfoShape::sine();
    }
};
} // namespace eightball
