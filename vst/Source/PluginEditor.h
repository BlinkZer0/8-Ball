#pragma once

#include <bitset>
#include "PluginProcessor.h"

// Hosts the HTML/SVG UI (vst/ui, compiled in as BinaryData) in a WebView2 and
// bridges it to the processor:
//   UI -> C++ events : uiReady, setParam{id,value}, setParams{values:{id:value...}}, gesture{id,begin},
//                      noteOn{note,vel}, noteOff{note}, panic, modWheel{value},
//                      loadPreset{id}, savePreset{name,overwrite}, deletePreset{id}, initPreset,
//                      loadPresetFile, openPresetFolder, paramMenu{id,x,y},
//                      midiLearn{id}, midiForget{id}, learnCancel,
//                      setWave{op,wave}, setEnv{key,env}, setLfoShape{lfo,shape}
//   C++ -> UI events : params{id:value...}, notes{on[],off[]},
//                      stats{voices,peak,sustain,modWheel,bpm,ops[8],active,lfo[4],gr}, config{...},
//                      presetList{presets[],folder}, preset{id,name,category},
//                      saveResult{ok,exists,name,error}, message{text},
//                      model{waves,envs,lfoShapes}, learn{armed,map{id:cc}}
class EightBallEditor : public juce::AudioProcessorEditor, private juce::Timer
{
public:
    explicit EightBallEditor (EightBallProcessor&);
    ~EightBallEditor() override;

    void paint (juce::Graphics&) override;
    void resized() override;

private:
    void timerCallback() override;
    juce::WebBrowserComponent::Options makeBrowserOptions();
    std::optional<juce::WebBrowserComponent::Resource> getResource (const juce::String& url);

    void onUiReady();
    void onSetParam (const juce::var&);
    void onSetParams (const juce::var&);
    void onGesture (const juce::var&);
    void sendConfig();
    void sendPresetList();
    void sendPreset();
    void sendModel();
    void sendLearn();
    void sendMessage (const juce::String& text);
    void chooseAndLoadPresetFile();
    void showParamMenu (const juce::var&);

    EightBallProcessor& processor;

    std::array<float, eightball::kNumParams> lastSent {};
    std::array<bool, eightball::kNumParams> inGesture {};
    std::bitset<128> lastNotes;
    int lastPresetVersion = -1, lastModelVersion = -1, lastLearnVersion = -1;
    int ticks = 0;
    bool uiReady = false;
    std::unique_ptr<juce::FileChooser> fileChooser;

    juce::WebBrowserComponent browser;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (EightBallEditor)
};
