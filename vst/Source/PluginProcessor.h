#pragma once

#include <juce_audio_utils/juce_audio_utils.h>
#include "Params.h"
#include "PresetManager.h"
#include "ModelStore.h"
#include "SynthEngine.h"

class EightBallProcessor : public juce::AudioProcessor, private juce::Timer
{
public:
    EightBallProcessor();
    ~EightBallProcessor() override;

    void prepareToPlay (double sampleRate, int samplesPerBlock) override;
    void releaseResources() override {}
    bool isBusesLayoutSupported (const BusesLayout& layouts) const override;
    void processBlock (juce::AudioBuffer<float>&, juce::MidiBuffer&) override;

    juce::AudioProcessorEditor* createEditor() override;
    bool hasEditor() const override { return true; }

    const juce::String getName() const override { return JucePlugin_Name; }
    bool acceptsMidi() const override { return true; }
    bool producesMidi() const override { return false; }
    bool isMidiEffect() const override { return false; }
    double getTailLengthSeconds() const override { return 5.0; }

    // The factory presets are exposed to the host as programs.
    int getNumPrograms() override { return (int) presetManager.factory().size(); }
    int getCurrentProgram() override { return currentProgram.load(); }
    void setCurrentProgram (int index) override;
    const juce::String getProgramName (int index) override;
    void changeProgramName (int, const juce::String&) override {}

    void getStateInformation (juce::MemoryBlock& destData) override;
    void setStateInformation (const void* data, int sizeInBytes) override;

    //==============================================================================
    // Presets (message thread)
    struct PresetInfo { juce::String id, name, category; };
    PresetInfo currentPreset() const;
    std::atomic<int> presetVersion { 0 };   // bumps whenever currentPreset() changes

    bool loadPresetById (const juce::String& id, juce::String& error);
    bool loadPresetFile (const juce::File& file, juce::String& error);
    bool saveUserPreset (const juce::String& name, bool overwrite, bool& alreadyExists, juce::String& error);
    bool deleteUserPreset (const juce::String& id, juce::String& error);
    void initPreset();                       // the Init patch (factory "Init")
    eightball::PresetData snapshot() const;  // the current sound as a preset
    void applyPreset (const eightball::PresetData&);

    // A/B compare: two sounds you can flip between. The other slot starts as a copy of the current sound.
    void abToggle();                         // stash the current sound, bring back the other
    void abCopy();                           // copy the current sound into the other slot
    bool abIsB() const { return abSlotB; }
    bool abHasOther() const { return abStashed; }

    eightball::PresetManager presetManager;
    eightball::ModelStore model;             // waves, envelopes, LFO shapes (message thread edits)

    //==============================================================================
    // Used by the editor (message thread)
    juce::AudioProcessorValueTreeState apvts;
    juce::MidiKeyboardState keyboardState;   // UI notes in, all sounding notes out
    juce::RangedAudioParameter* param (int index) const { return params[(size_t) index]; }
    float paramValue (int index) const { return rawValues[(size_t) index]->load(); }
    void setParamFromUi (int index, float value, bool gesture);
    void requestPanic() { panicRequested = true; }
    void setUiModWheel (float v) { uiModWheel = juce::jlimit (0.0f, 1.0f, v); }

    // MIDI learn: arm a parameter, the next learnable CC is assigned to it. One CC per parameter.
    void armLearn (int paramIndex) { learnArmed = paramIndex; ++learnVersion; }
    void cancelLearn() { learnArmed = -1; ++learnVersion; }
    void forgetLearn (int paramIndex);
    int learnedCC (int paramIndex) const;            // -1 = none
    int armedParam() const { return learnArmed.load(); }
    std::atomic<int> learnVersion { 0 };

    std::atomic<int>   statVoices { 0 };
    std::atomic<float> statPeak { 0.0f };
    std::atomic<bool>  statSustain { false };
    std::atomic<float> statModWheel { 0.0f };
    std::atomic<float> statBpm { 120.0f };
    std::array<std::atomic<float>, eightball::kNumOps> statOpActivity {};
    std::atomic<int>   statActiveMask { 0 };          // bit k = operator k is doing something
    std::array<std::atomic<float>, eightball::kNumLfos> statLfo {};   // LFO outputs, -1..1
    std::atomic<float> statGr { 0.0f };               // compressor gain reduction, dB (max since the editor read it)

    // Per-operator scopes for the animated matrix: 128 points each, written by the audio thread under a
    // sequence counter (odd while writing); the editor copies them when the counter is even and unchanged.
    static constexpr int kScopePoints = 128;
    std::atomic<bool> wantScopes { false };           // the UI's Animate toggle
    std::array<float, eightball::kNumOps * kScopePoints> scopeBuf {};
    std::atomic<uint32_t> scopeSeq { 0 };

private:
    void setPresetInfo (const juce::String& id, const juce::String& name, const juce::String& category);
    void handleMidi (const juce::MidiMessage&);
    bool handleLearn (const juce::MidiMessage&);
    void pushParamChange (int index, float value);
    void timerCallback() override;   // applies MIDI-learned changes on the message thread; reports latency
    int currentLatency() const;      // oversampling + distortion + limiter lookahead
    juce::String learnStateString() const;
    void restoreLearnState (const juce::String&);

    std::array<juce::RangedAudioParameter*, eightball::kNumParams> params {};
    std::array<std::atomic<float>*, eightball::kNumParams> rawValues {};
    std::array<float, eightball::kNumParams> blockValues {};
    eightball::SynthEngine engine;
    std::atomic<int> currentProgram { 0 };
    std::atomic<bool> panicRequested { false };
    std::atomic<float> uiModWheel { -1.0f };   // -1 = no pending change
    int reportedLatency = -1;

    // audio thread -> message thread parameter changes (MIDI learn)
    struct ParamChange { int index; float value; };
    juce::AbstractFifo paramFifo { 1024 };
    std::array<ParamChange, 1024> paramBuf {};
    std::array<std::atomic<int>, 128> learnMap {};   // CC -> parameter index, -1 = none
    std::atomic<int> learnArmed { -1 };

    mutable juce::CriticalSection presetLock;
    PresetInfo presetInfo;
    eightball::PresetData abOther;           // the sound in the slot not playing
    PresetInfo abOtherInfo;
    bool abSlotB = false, abStashed = false;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (EightBallProcessor)
};
