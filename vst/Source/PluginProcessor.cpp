#include "PluginProcessor.h"
#include "PluginEditor.h"
#include "MidiRouting.h"

using namespace eightball;

EightBallProcessor::EightBallProcessor()
    : AudioProcessor (BusesProperties().withOutput ("Output", juce::AudioChannelSet::stereo(), true)),
      apvts (*this, nullptr, "EightBallState", createParameterLayout())
{
    for (int i = 0; i < kNumParams; ++i)
    {
        const auto id = paramId (i);
        params[(size_t) i] = apvts.getParameter (id);
        rawValues[(size_t) i] = apvts.getRawParameterValue (id);
        jassert (params[(size_t) i] != nullptr && rawValues[(size_t) i] != nullptr);
    }
    for (auto& m : learnMap) m = -1;
    setCurrentProgram (0); // a fresh instance starts on the first factory preset
    startTimerHz (50);
}

EightBallProcessor::~EightBallProcessor()
{
    stopTimer();
}

//==============================================================================
void EightBallProcessor::prepareToPlay (double sampleRate, int)
{
    for (int i = 0; i < kNumParams; ++i) blockValues[(size_t) i] = paramValue (i);
    engine.setParamValues (blockValues.data());
    engine.prepare (sampleRate);
    engine.settleParams();
    keyboardState.reset();
    const int lat = SynthEngine::latencySamples (paramValue (oversample) >= 0.5f);
    reportedLatency = lat;
    setLatencySamples (lat);
}

bool EightBallProcessor::isBusesLayoutSupported (const BusesLayout& layouts) const
{
    const auto out = layouts.getMainOutputChannelSet();
    return out == juce::AudioChannelSet::stereo() || out == juce::AudioChannelSet::mono();
}

void EightBallProcessor::setParamFromUi (int index, float value, bool gesture)
{
    auto* p = params[(size_t) index];
    if (gesture) p->beginChangeGesture();
    p->setValueNotifyingHost (p->convertTo0to1 (value));
    if (gesture) p->endChangeGesture();
}

//==============================================================================
void EightBallProcessor::forgetLearn (int paramIndex)
{
    for (auto& m : learnMap)
        if (m.load() == paramIndex) m = -1;
    if (learnArmed.load() == paramIndex) learnArmed = -1;
    ++learnVersion;
}

int EightBallProcessor::learnedCC (int paramIndex) const
{
    for (int cc = 0; cc < 128; ++cc)
        if (learnMap[(size_t) cc].load() == paramIndex) return cc;
    return -1;
}

// "cc=paramId;cc=paramId..." (parameter IDs are stable)
juce::String EightBallProcessor::learnStateString() const
{
    juce::String s;
    for (int cc = 0; cc < 128; ++cc)
        if (const int i = learnMap[(size_t) cc].load(); i >= 0 && i < kNumParams)
            s << cc << '=' << paramId (i) << ';';
    return s;
}

void EightBallProcessor::restoreLearnState (const juce::String& s)
{
    for (auto& m : learnMap) m = -1;
    for (const auto& item : juce::StringArray::fromTokens (s, ";", ""))
    {
        const int cc = item.upToFirstOccurrenceOf ("=", false, false).getIntValue();
        const int i = paramIndexForId (item.fromFirstOccurrenceOf ("=", false, false));
        if (i >= 0 && cc >= 0 && cc < 128) learnMap[(size_t) cc] = i;
    }
    learnArmed = -1;
    ++learnVersion;
}

void EightBallProcessor::pushParamChange (int index, float value)
{
    const auto scope = paramFifo.write (1);
    if (scope.blockSize1 > 0) paramBuf[(size_t) scope.startIndex1] = { index, value };
    else if (scope.blockSize2 > 0) paramBuf[(size_t) scope.startIndex2] = { index, value };
}

// An armed parameter takes the next learnable CC; a learned CC becomes a parameter
// change handed to the message thread (so the host and the UI see it).
bool EightBallProcessor::handleLearn (const juce::MidiMessage& m)
{
    if (! m.isController()) return false;
    const int cc = m.getControllerNumber();
    if (! learnableCC (cc)) return false;
    if (const int armed = learnArmed.load(); armed >= 0)
    {
        for (auto& slot : learnMap)
            if (slot.load() == armed) slot = -1;
        learnMap[(size_t) cc] = armed;
        learnArmed = -1;
        ++learnVersion;
    }
    if (const int target = learnMap[(size_t) cc].load(); target >= 0)
    {
        pushParamChange (target, m.getControllerValue() / 127.0f);
        return true;
    }
    return false;
}

void EightBallProcessor::timerCallback()
{
    const auto scope = paramFifo.read (paramFifo.getNumReady());
    auto apply = [this] (int start, int size)
    {
        for (int i = start; i < start + size; ++i)
        {
            const auto& pc = paramBuf[(size_t) i];
            auto* p = params[(size_t) pc.index];
            p->beginChangeGesture();
            p->setValueNotifyingHost (pc.value);
            p->endChangeGesture();
        }
    };
    apply (scope.startIndex1, scope.blockSize1);
    apply (scope.startIndex2, scope.blockSize2);

    model.collectRetired();

    // the oversampling filters delay the output a few samples: tell the host
    if (const int lat = SynthEngine::latencySamples (paramValue (oversample) >= 0.5f); lat != reportedLatency)
    {
        reportedLatency = lat;
        setLatencySamples (lat);
    }
}

//==============================================================================
void EightBallProcessor::handleMidi (const juce::MidiMessage& m)
{
    if (! handleLearn (m)) routeMidi (engine, m);
}

void EightBallProcessor::processBlock (juce::AudioBuffer<float>& buffer, juce::MidiBuffer& midi)
{
    juce::ScopedNoDenormals noDenormals;
    const int n = buffer.getNumSamples();

    if (panicRequested.exchange (false))
        engine.panic();
    if (const float w = uiModWheel.exchange (-1.0f); w >= 0.0f)   // mod wheel dragged in the UI
        engine.setModWheel (w);
    if (const auto* m = model.takeIncoming())
        engine.setModel (m);

    // Merges notes played on the UI keyboard into `midi`, and tracks all
    // sounding notes so the editor can light up the keys.
    keyboardState.processNextMidiBuffer (midi, 0, n, true);

    for (int i = 0; i < kNumParams; ++i) blockValues[(size_t) i] = paramValue (i);
    engine.setParamValues (blockValues.data());

    // Host tempo + song position (tempo-synced envelopes / LFOs). No play head -> 120 BPM.
    double bpm = 120.0, ppq = 0.0;
    bool playing = false;
    if (auto* ph = getPlayHead())
    {
        if (const auto pos = ph->getPosition())
        {
            if (const auto b = pos->getBpm()) bpm = *b;
            if (const auto q = pos->getPpqPosition()) ppq = *q;
            playing = pos->getIsPlaying();
        }
    }
    engine.setTransport (bpm, ppq, playing);

    float* L = buffer.getWritePointer (0);
    float* R = buffer.getNumChannels() > 1 ? buffer.getWritePointer (1) : nullptr;

    // Sample-accurate: render up to each MIDI event, then apply it.
    int pos = 0;
    for (const auto meta : midi)
    {
        const int t = juce::jlimit (0, n, meta.samplePosition);
        if (t > pos)
        {
            engine.render (L + pos, R != nullptr ? R + pos : nullptr, t - pos);
            pos = t;
        }
        handleMidi (meta.getMessage());
    }
    if (pos < n)
        engine.render (L + pos, R != nullptr ? R + pos : nullptr, n - pos);

    for (int ch = 2; ch < buffer.getNumChannels(); ++ch)
        buffer.clear (ch, 0, n);

    statVoices.store (engine.activeVoices());
    statSustain.store (engine.sustainDown());
    statModWheel.store ((float) engine.modWheelValue());
    statBpm.store ((float) engine.tempo());
    const float pk = engine.takePeak();
    if (pk > statPeak.load()) statPeak.store (pk);
    float act[kNumOps];
    engine.takeOpActivity (act);
    int mask = 0;
    for (int k = 0; k < kNumOps; ++k)
    {
        statOpActivity[(size_t) k].store (act[k]);
        if (engine.opActive (k)) mask |= 1 << k;
    }
    statActiveMask.store (mask);
    for (int l = 0; l < kNumLfos; ++l) statLfo[(size_t) l].store ((float) engine.lfoValue (l));
    const float gr = (float) engine.takeGainReduction();
    if (gr > statGr.load()) statGr.store (gr);

    if (wantScopes.load())
    {
        scopeSeq.fetch_add (1, std::memory_order_acq_rel);   // odd: writing
        for (int k = 0; k < kNumOps; ++k)
            engine.copyScope (k, scopeBuf.data() + k * kScopePoints, kScopePoints, SynthEngine::kScopeLen / kScopePoints);
        scopeSeq.fetch_add (1, std::memory_order_acq_rel);   // even: done
    }
}

//==============================================================================
// Sets every parameter except master, and the model. Anything the preset doesn't
// specify goes to its default.
void EightBallProcessor::applyPreset (const PresetData& preset)
{
    for (int i = 0; i < kNumParams; ++i)
    {
        if (i == master || paramDef (i).noPreset) continue;
        const float stored = preset.values[(size_t) i];
        const float v = std::isnan (stored) ? paramDef (i).def : stored;
        auto* p = params[(size_t) i];
        const float norm = p->convertTo0to1 (v);
        if (std::abs (p->getValue() - norm) < 1e-7f) continue; // unchanged: don't spam the host
        p->beginChangeGesture();
        p->setValueNotifyingHost (norm);
        p->endChangeGesture();
    }
    model.setAll (preset.model);
}

PresetData EightBallProcessor::snapshot() const
{
    PresetData data;
    const auto info = currentPreset();
    data.name = info.name;
    data.category = info.category;
    for (int i = 0; i < kNumParams; ++i)
        if (i != master && ! paramDef (i).noPreset) data.values[(size_t) i] = paramValue (i);
    data.model = model.data();
    return data;
}

void EightBallProcessor::abToggle()
{
    const PresetData now = snapshot();
    const PresetInfo nowInfo = currentPreset();
    if (abStashed)
    {
        applyPreset (abOther);
        setPresetInfo (abOtherInfo.id, abOtherInfo.name, abOtherInfo.category);
    }
    abOther = now;
    abOtherInfo = nowInfo;
    abStashed = true;
    abSlotB = ! abSlotB;
    ++presetVersion;
}

void EightBallProcessor::abCopy()
{
    abOther = snapshot();
    abOtherInfo = currentPreset();
    abStashed = true;
    ++presetVersion;
}

void EightBallProcessor::setPresetInfo (const juce::String& id, const juce::String& name, const juce::String& category)
{
    {
        const juce::ScopedLock sl (presetLock);
        presetInfo = { id, name, category };
    }
    ++presetVersion;
}

EightBallProcessor::PresetInfo EightBallProcessor::currentPreset() const
{
    const juce::ScopedLock sl (presetLock);
    return presetInfo;
}

void EightBallProcessor::setCurrentProgram (int index)
{
    index = juce::jlimit (0, getNumPrograms() - 1, index);
    currentProgram = index;
    const auto& preset = presetManager.factory()[(size_t) index];
    applyPreset (preset);
    setPresetInfo ("factory:" + juce::String (index), preset.name, preset.category);
    updateHostDisplay (ChangeDetails().withProgramChanged (true));
}

void EightBallProcessor::initPreset()
{
    const int i = presetManager.findFactory ("Init");
    setCurrentProgram (i >= 0 ? i : 0);
}

const juce::String EightBallProcessor::getProgramName (int index)
{
    if (index < 0 || index >= getNumPrograms()) return {};
    const auto& p = presetManager.factory()[(size_t) index];
    return p.category + " - " + p.name;
}

bool EightBallProcessor::loadPresetById (const juce::String& id, juce::String& error)
{
    if (id.startsWith ("factory:"))
    {
        const int index = id.fromFirstOccurrenceOf (":", false, false).getIntValue();
        if (index < 0 || index >= getNumPrograms()) { error = "Unknown preset"; return false; }
        setCurrentProgram (index);
        return true;
    }

    presetManager.rescanIfChanged();
    if (const auto* entry = presetManager.findUser (id))
    {
        PresetData data;
        if (! PresetManager::readFile (entry->file, data, error)) return false;
        applyPreset (data);
        setPresetInfo (entry->id, entry->name, entry->category);
        return true;
    }
    error = "Preset not found (was it moved or deleted?)";
    return false;
}

bool EightBallProcessor::loadPresetFile (const juce::File& file, juce::String& error)
{
    PresetData data;
    if (! PresetManager::readFile (file, data, error)) return false;
    applyPreset (data);
    const auto userId = presetManager.idForFile (file);
    if (userId.isNotEmpty())
        setPresetInfo (userId, file.getFileNameWithoutExtension(), presetManager.categoryForFile (file));
    else
        setPresetInfo ("file:" + file.getFullPathName(), data.name, "File");
    return true;
}

bool EightBallProcessor::saveUserPreset (const juce::String& rawName, bool overwrite, bool& alreadyExists, juce::String& error)
{
    alreadyExists = false;
    const auto name = rawName.trim();
    if (name.isEmpty()) { error = "Enter a name for the preset"; return false; }

    const auto file = presetManager.fileForName (name);
    if (file.existsAsFile() && ! overwrite) { alreadyExists = true; return false; }

    PresetData data = snapshot();
    data.name = name;
    data.category = "User";

    if (! PresetManager::writeFile (file, data, error)) return false;
    presetManager.rescanIfChanged();
    setPresetInfo (presetManager.idForFile (file), file.getFileNameWithoutExtension(), presetManager.categoryForFile (file));
    return true;
}

bool EightBallProcessor::deleteUserPreset (const juce::String& id, juce::String& error)
{
    presetManager.rescanIfChanged();
    const auto* entry = presetManager.findUser (id);
    if (entry == nullptr) { error = "Only user presets can be deleted"; return false; }
    const auto file = entry->file;
    if (! file.moveToTrash() && ! file.deleteFile()) { error = "Couldn't delete " + file.getFullPathName(); return false; }
    presetManager.rescanIfChanged();
    if (currentPreset().id == id)                       // keep the sound, drop the link to the file
        setPresetInfo ({}, currentPreset().name, "User");
    return true;
}

//==============================================================================
void EightBallProcessor::getStateInformation (juce::MemoryBlock& destData)
{
    auto state = apvts.copyState();
    const auto info = currentPreset();
    state.setProperty ("program", currentProgram.load(), nullptr);
    state.setProperty ("presetId", info.id, nullptr);
    state.setProperty ("presetName", info.name, nullptr);
    state.setProperty ("presetCategory", info.category, nullptr);
    state.setProperty ("stateVersion", kPresetVersion, nullptr);
    state.setProperty ("midiLearn", learnStateString(), nullptr);
    {   // waves, envelopes, LFO shapes travel with the project as one JSON block
        auto* o = new juce::DynamicObject();
        modelDataToJson (model.data(), *o);
        state.setProperty ("model", juce::JSON::toString (juce::var (o), true), nullptr);
    }
    if (auto xml = state.createXml())
        copyXmlToBinary (*xml, destData);
}

void EightBallProcessor::setStateInformation (const void* data, int sizeInBytes)
{
    if (auto xml = getXmlFromBinary (data, sizeInBytes))
    {
        if (xml->hasTagName (apvts.state.getType()))
        {
            auto state = juce::ValueTree::fromXml (*xml);
            currentProgram = juce::jlimit (0, getNumPrograms() - 1, (int) state.getProperty ("program", 0));
            const auto name = state.getProperty ("presetName").toString();
            if (name.isEmpty())
            {
                const auto& p = presetManager.factory()[(size_t) currentProgram.load()];
                setPresetInfo ("factory:" + juce::String (currentProgram.load()), p.name, p.category);
            }
            else
            {
                setPresetInfo (state.getProperty ("presetId").toString(), name,
                               state.getProperty ("presetCategory").toString());
            }
            restoreLearnState (state.getProperty ("midiLearn").toString());
            {
                ModelData md;   // a project without a model block (older build) gets the defaults
                modelDataFromJson (juce::JSON::parse (state.getProperty ("model").toString()), md);
                model.setAll (md);
            }
            apvts.replaceState (state);
        }
    }
}

//==============================================================================
juce::AudioProcessorEditor* EightBallProcessor::createEditor()
{
    return new EightBallEditor (*this);
}

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new EightBallProcessor();
}
