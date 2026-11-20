#pragma once
// ============================================================================
//  Owns the Model data that is not a host parameter (message thread):
//  harmonic editor partials / drawn shapes per operator, the multi-point
//  envelopes, the drawn LFO shapes. Bakes wavetables when a wave changes,
//  serialises everything to JSON for presets and project state, and hands a
//  fresh Model to the audio thread lock-free (atomic incoming / retired
//  pointers, the same handoff E-Piano uses for samples).
// ============================================================================
#include <juce_core/juce_core.h>
#include <atomic>
#include <memory>
#include "dsp/Model.h"

namespace eightball
{
struct ModelData   // what presets store
{
    std::array<WaveSpec, kNumOps> waves;
    std::array<EnvSpec, kNumEnvs> envs;
    std::array<LfoShape, kNumLfos> lfoShapes;
    ModelData()
    {
        for (auto& w : waves) w = WaveSpec::sine();
        for (int i = 0; i < kNumEnvs; ++i) envs[(size_t) i] = defaultEnv (i);
        for (auto& s : lfoShapes) s = LfoShape::sine();
    }
};

// JSON <-> ModelData (plain objects; missing parts keep their defaults)
juce::var waveToJson (const WaveSpec&);
bool waveFromJson (const juce::var&, WaveSpec&);
juce::var envToJson (const EnvSpec&);
bool envFromJson (const juce::var&, EnvSpec&);
juce::var lfoShapeToJson (const LfoShape&);
bool lfoShapeFromJson (const juce::var&, LfoShape&);
// { "waves": { "1": {...} }, "envs": { "op1Amp": {...}, "flt1Cutoff": {...} }, "lfoShapes": { "1": [...] } }
void modelDataToJson (const ModelData&, juce::DynamicObject& into);
void modelDataFromJson (const juce::var& obj, ModelData& out);   // only the parts present
juce::String envKey (int index);                                 // "op1Amp" ... "flt3Level"
int envIndexForKey (const juce::String&);

class ModelStore
{
public:
    ModelStore();
    ~ModelStore();

    const ModelData& data() const { return current; }
    std::atomic<int> version { 0 };   // bumps on every change (the editor resends)

    // Editing (message thread). Each call publishes a new Model to the audio thread.
    void setWave (int op, const WaveSpec&);
    void setEnv (int index, const EnvSpec&);
    void setLfoShape (int lfo, const LfoShape&);
    void setAll (const ModelData&);
    void reset() { setAll (ModelData {}); }

    // Audio thread: the latest Model, or nullptr if nothing new since the last call.
    const Model* takeIncoming();
    // Message thread: free what the audio thread retired.
    void collectRetired();

private:
    struct Published
    {
        Model model;
        std::array<std::shared_ptr<const Wavetable>, kNumOps> tables;   // keeps the tables alive
    };
    void publish();

    ModelData current;
    std::array<std::shared_ptr<const Wavetable>, kNumOps> tables;
    std::atomic<Published*> incoming { nullptr };
    std::atomic<Published*> retired { nullptr };
    Published* active = nullptr;   // audio thread only
};
} // namespace eightball
