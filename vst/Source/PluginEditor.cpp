#include "PluginEditor.h"
#include "BinaryData.h"

using namespace eightball;

namespace
{
const juce::Colour kBackground { 0xff0b0d10 };

const char* mimeForExtension (const juce::String& ext)
{
    if (ext == "html") return "text/html";
    if (ext == "js")   return "text/javascript";
    if (ext == "css")  return "text/css";
    if (ext == "svg")  return "image/svg+xml";
    if (ext == "json") return "application/json";
    if (ext == "png")  return "image/png";
    return "application/octet-stream";
}

std::vector<std::byte> toBytes (const void* data, size_t size)
{
    const auto* p = static_cast<const std::byte*> (data);
    return { p, p + size };
}

juce::var makeObject (std::initializer_list<std::pair<const char*, juce::var>> props)
{
    auto* obj = new juce::DynamicObject();
    for (const auto& [k, v] : props) obj->setProperty (k, v);
    return juce::var (obj);
}
} // namespace

//==============================================================================
EightBallEditor::EightBallEditor (EightBallProcessor& p)
    : AudioProcessorEditor (p), processor (p), browser (makeBrowserOptions())
{
    lastSent.fill (std::numeric_limits<float>::quiet_NaN());

    addAndMakeVisible (browser);
    browser.goToURL (juce::WebBrowserComponent::getResourceProviderRoot());

    setResizable (true, true);
    setResizeLimits (760, 560, 2800, 2400);
    setSize (1180, 900);
    startTimerHz (30);
}

EightBallEditor::~EightBallEditor()
{
    stopTimer();
    // Close any knob gestures the UI didn't get to finish.
    for (int i = 0; i < kNumParams; ++i)
        if (inGesture[(size_t) i]) processor.param (i)->endChangeGesture();
}

void EightBallEditor::paint (juce::Graphics& g) { g.fillAll (kBackground); }
void EightBallEditor::resized() { browser.setBounds (getLocalBounds()); }

//==============================================================================
juce::WebBrowserComponent::Options EightBallEditor::makeBrowserOptions()
{
    using Opts = juce::WebBrowserComponent::Options;

    // WebView2 needs a writable data folder; the default (next to the host's exe) usually isn't.
    const auto userData = juce::File::getSpecialLocation (juce::File::tempDirectory).getChildFile ("EightBallVST-WebView2");

    return Opts{}
        .withBackend (Opts::Backend::webview2)
        .withWinWebView2Options (Opts::WinWebView2{}
                                     .withUserDataFolder (userData)
                                     .withBackgroundColour (kBackground)
                                     .withStatusBarDisabled())
        .withNativeIntegrationEnabled()
        .withKeepPageLoadedWhenBrowserIsHidden()
        .withResourceProvider ([this] (const juce::String& url) { return getResource (url); })
        .withEventListener ("uiReady",    [this] (const juce::var&) { onUiReady(); })
        .withEventListener ("setParam",   [this] (const juce::var& e) { onSetParam (e); })
        .withEventListener ("setParams",  [this] (const juce::var& e) { onSetParams (e); })
        .withEventListener ("gesture",    [this] (const juce::var& e) { onGesture (e); })
        .withEventListener ("noteOn", [this] (const juce::var& e)
        {
            const int note = juce::jlimit (0, 127, (int) e["note"]);
            const float vel = juce::jlimit (1, 127, (int) e["vel"]) / 127.0f;
            processor.keyboardState.noteOn (1, note, vel);
        })
        .withEventListener ("noteOff", [this] (const juce::var& e)
        {
            processor.keyboardState.noteOff (1, juce::jlimit (0, 127, (int) e["note"]), 0.0f);
        })
        .withEventListener ("panic", [this] (const juce::var&)
        {
            processor.keyboardState.allNotesOff (0);
            processor.requestPanic();
        })
        .withEventListener ("modWheel", [this] (const juce::var& e) { processor.setUiModWheel ((float) (double) e["value"]); })
        // the matrix animation: the UI asks for the per-operator scopes only while it shows them
        .withEventListener ("setAnimate", [this] (const juce::var& e) { processor.wantScopes = (bool) e["on"]; })
        .withEventListener ("loadPreset", [this] (const juce::var& e)
        {
            juce::String error;
            if (! processor.loadPresetById (e["id"].toString(), error)) sendMessage (error);
            sendPreset();
        })
        .withEventListener ("initPreset", [this] (const juce::var&) { processor.initPreset(); sendPreset(); })
        .withEventListener ("savePreset", [this] (const juce::var& e)
        {
            const auto name = e["name"].toString().trim();
            bool exists = false;
            juce::String error;
            const bool ok = processor.saveUserPreset (name, (bool) e["overwrite"], exists, error);
            browser.emitEventIfBrowserIsVisible ("saveResult", makeObject ({
                { "ok", ok }, { "exists", exists }, { "name", name }, { "error", error } }));
            if (ok) { sendPresetList(); sendPreset(); }
        })
        .withEventListener ("deletePreset", [this] (const juce::var& e)
        {
            juce::String error;
            if (processor.deleteUserPreset (e["id"].toString(), error)) sendMessage ("Preset moved to the Recycle Bin");
            else sendMessage (error);
            sendPresetList();
            sendPreset();
        })
        .withEventListener ("loadPresetFile", [this] (const juce::var&) { chooseAndLoadPresetFile(); })
        // right-click on a control: the host's own parameter menu (automation, link to controller...).
        // Hosts without one get a small fallback menu.
        .withEventListener ("paramMenu", [this] (const juce::var& e) { showParamMenu (e); })
        // MIDI learn: arm a parameter (the next CC moved is assigned to it), forget it, or cancel
        .withEventListener ("midiLearn", [this] (const juce::var& e)
        {
            const int i = paramIndexForId (e["id"].toString());
            if (i >= 0) processor.armLearn (i);
        })
        .withEventListener ("midiForget", [this] (const juce::var& e)
        {
            const int i = paramIndexForId (e["id"].toString());
            if (i >= 0) processor.forgetLearn (i);
        })
        .withEventListener ("learnCancel", [this] (const juce::var&) { processor.cancelLearn(); })
        // model edits: harmonic editor / drawn shape, envelopes, LFO shapes
        .withEventListener ("setWave", [this] (const juce::var& e)
        {
            WaveSpec w;
            if (waveFromJson (e["wave"], w)) processor.model.setWave ((int) e["op"], w);
        })
        .withEventListener ("setEnv", [this] (const juce::var& e)
        {
            EnvSpec s;
            const int i = envIndexForKey (e["key"].toString());
            if (i >= 0 && envFromJson (e["env"], s)) processor.model.setEnv (i, s);
        })
        .withEventListener ("setLfoShape", [this] (const juce::var& e)
        {
            LfoShape s;
            if (lfoShapeFromJson (e["shape"], s)) processor.model.setLfoShape ((int) e["lfo"], s);
        })
        .withEventListener ("openPresetFolder", [] (const juce::var&)
        {
            const auto folder = PresetManager::userFolder();
            folder.createDirectory();
            folder.startAsProcess();
        });
}

void EightBallEditor::chooseAndLoadPresetFile()
{
    fileChooser = std::make_unique<juce::FileChooser> ("Load Eight Ball preset", PresetManager::userFolder(),
                                                        juce::String ("*") + PresetManager::fileExtension);
    const auto chooserFlags = juce::FileBrowserComponent::openMode | juce::FileBrowserComponent::canSelectFiles;
    fileChooser->launchAsync (chooserFlags, [safeThis = juce::Component::SafePointer<EightBallEditor> (this)] (const juce::FileChooser& fc)
    {
        if (safeThis == nullptr) return;
        const auto file = fc.getResult();
        if (file == juce::File()) return; // cancelled
        juce::String error;
        if (safeThis->processor.loadPresetFile (file, error)) safeThis->sendMessage ("Loaded " + file.getFileName());
        else safeThis->sendMessage (error);
        safeThis->sendPreset();
    });
}

void EightBallEditor::showParamMenu (const juce::var& e)
{
    const int i = paramIndexForId (e["id"].toString());
    if (i < 0) return;
    auto* p = processor.param (i);
    const juce::Point<int> pos ((int) e["x"], (int) e["y"]);

    if (auto* host = getHostContext())
        if (auto menu = host->getContextMenuForParameter (p))
        {
            menu->showNativeMenu (pos);
            return;
        }

    // No host menu (e.g. Standalone): minimal fallback
    juce::PopupMenu m;
    m.addSectionHeader (p->getName (64) + ": " + p->getCurrentValueAsText());
    m.addItem (1, "Reset to default");
    m.showMenuAsync (juce::PopupMenu::Options().withTargetComponent (this)
                                                .withTargetScreenArea (localAreaToGlobal (juce::Rectangle<int> (pos.x, pos.y, 1, 1))),
                     [safeThis = juce::Component::SafePointer<EightBallEditor> (this), i] (int result)
                     {
                         if (safeThis == nullptr || result != 1) return;
                         auto* param = safeThis->processor.param (i);
                         param->beginChangeGesture();
                         param->setValueNotifyingHost (param->getDefaultValue());
                         param->endChangeGesture();
                     });
}

void EightBallEditor::sendLearn()
{
    lastLearnVersion = processor.learnVersion.load();
    auto* map = new juce::DynamicObject();
    for (int i = 0; i < kNumParams; ++i)
        if (const int cc = processor.learnedCC (i); cc >= 0) map->setProperty (paramId (i), cc);
    const int armed = processor.armedParam();
    browser.emitEventIfBrowserIsVisible ("learn", makeObject ({
        { "armed", armed >= 0 ? juce::var (paramId (armed)) : juce::var ("") }, { "map", juce::var (map) } }));
}

void EightBallEditor::sendModel()
{
    lastModelVersion = processor.model.version.load();
    auto* o = new juce::DynamicObject();
    modelDataToJson (processor.model.data(), *o);
    browser.emitEventIfBrowserIsVisible ("model", juce::var (o));
}

// A consistent copy of the scope buffer (retry while the audio thread is writing), only the active operators
void EightBallEditor::sendScopes()
{
    std::array<float, kNumOps * EightBallProcessor::kScopePoints> buf {};
    for (int attempt = 0; attempt < 4; ++attempt)
    {
        const uint32_t s0 = processor.scopeSeq.load (std::memory_order_acquire);
        if (s0 & 1u) continue;
        buf = processor.scopeBuf;
        if (processor.scopeSeq.load (std::memory_order_acquire) == s0) break;
    }
    const int active = processor.statActiveMask.load();
    juce::Array<juce::var> ops;
    for (int k = 0; k < kNumOps; ++k)
    {
        juce::Array<juce::var> pts;
        if ((active >> k) & 1)
            for (int i = 0; i < EightBallProcessor::kScopePoints; ++i)
                pts.add (std::round (buf[(size_t) (k * EightBallProcessor::kScopePoints + i)] * 1000.0f) / 1000.0);
        ops.add (juce::var (pts));
    }
    browser.emitEventIfBrowserIsVisible ("scope", makeObject ({ { "ops", ops } }));
}

void EightBallEditor::sendMessage (const juce::String& text)
{
    browser.emitEventIfBrowserIsVisible ("message", makeObject ({ { "text", text } }));
}

void EightBallEditor::sendPresetList()
{
    auto& pm = processor.presetManager;
    pm.rescanIfChanged();

    juce::Array<juce::var> list;
    const auto& factory = pm.factory();
    for (size_t i = 0; i < factory.size(); ++i)
        list.add (makeObject ({ { "id", "factory:" + juce::String ((int) i) }, { "name", factory[i].name },
                                { "category", factory[i].category }, { "factory", true } }));
    for (const auto& e : pm.userPresets())
        list.add (makeObject ({ { "id", e.id }, { "name", e.name }, { "category", e.category }, { "factory", false } }));

    browser.emitEventIfBrowserIsVisible ("presetList", makeObject ({
        { "presets", list }, { "folder", PresetManager::userFolder().getFullPathName() } }));
}

void EightBallEditor::sendPreset()
{
    const auto info = processor.currentPreset();
    lastPresetVersion = processor.presetVersion.load();
    browser.emitEventIfBrowserIsVisible ("preset", makeObject ({
        { "id", info.id }, { "name", info.name }, { "category", info.category } }));
}

std::optional<juce::WebBrowserComponent::Resource> EightBallEditor::getResource (const juce::String& url)
{
    auto path = url.upToFirstOccurrenceOf ("?", false, false).trimCharactersAtStart ("/");
    if (path.isEmpty()) path = "index.html";
    const auto fileName = path.fromLastOccurrenceOf ("/", false, false);
    const auto mime = mimeForExtension (fileName.fromLastOccurrenceOf (".", false, false).toLowerCase());

    // Dev mode: set EIGHTBALL_UI_DIR to the vst/ui folder to load the UI from disk
    // (edit HTML/CSS/JS and just reopen the editor, no rebuild needed).
    const auto devDir = juce::SystemStats::getEnvironmentVariable ("EIGHTBALL_UI_DIR", {});
    if (devDir.isNotEmpty())
    {
        const auto f = juce::File (devDir).getChildFile (path);
        juce::MemoryBlock mb;
        if (f.existsAsFile() && f.loadFileAsData (mb))
            return juce::WebBrowserComponent::Resource { toBytes (mb.getData(), mb.getSize()), mime };
    }

    // Embedded UI. BinaryData is keyed by file name (all UI file names are unique).
    for (int i = 0; i < BinaryData::namedResourceListSize; ++i)
    {
        if (fileName == BinaryData::originalFilenames[i])
        {
            int size = 0;
            if (const auto* data = BinaryData::getNamedResource (BinaryData::namedResourceList[i], size))
                return juce::WebBrowserComponent::Resource { toBytes (data, (size_t) size), mime };
        }
    }
    return std::nullopt;
}

//==============================================================================
void EightBallEditor::onUiReady()
{
    uiReady = true;
    lastSent.fill (std::numeric_limits<float>::quiet_NaN()); // force a full resend
    lastNotes.reset();
    sendConfig();
    sendPresetList();
    sendPreset();
    sendModel();
    sendLearn();
    timerCallback();
}

void EightBallEditor::onSetParam (const juce::var& e)
{
    const int i = paramIndexForId (e["id"].toString());
    if (i < 0) return;
    const float v = (float) (double) e["value"];
    processor.setParamFromUi (i, v, ! inGesture[(size_t) i]);   // wheel / keys / double-click: one-shot gesture
    lastSent[(size_t) i] = processor.paramValue (i); // don't echo it back to the UI
}

// Many parameters at once (algorithm presets, clear, randomize): each change is its own gesture.
void EightBallEditor::onSetParams (const juce::var& e)
{
    if (auto* o = e["values"].getDynamicObject())
        for (const auto& prop : o->getProperties())
        {
            const int i = paramIndexForId (prop.name.toString());
            if (i < 0) continue;
            processor.setParamFromUi (i, (float) (double) prop.value, true);
            lastSent[(size_t) i] = processor.paramValue (i);
        }
}

void EightBallEditor::onGesture (const juce::var& e)
{
    const int i = paramIndexForId (e["id"].toString());
    if (i < 0) return;
    const bool begin = (bool) e["begin"];
    if (begin == inGesture[(size_t) i]) return;
    inGesture[(size_t) i] = begin;
    if (begin) processor.param (i)->beginChangeGesture();
    else       processor.param (i)->endChangeGesture();
}

void EightBallEditor::sendConfig()
{
    const auto wrapper = juce::String (juce::AudioProcessor::getWrapperTypeDescription (processor.wrapperType));
    browser.emitEventIfBrowserIsVisible ("config", makeObject ({
        { "sampleRate", processor.getSampleRate() },
        { "blockSize",  processor.getBlockSize() },
        { "wrapper",    wrapper },
        { "voices",     kMaxVoices },
        // dev / screenshots: EIGHTBALL_UI_PAGE=matrix (etc.) opens that page first
        { "startPage",  juce::SystemStats::getEnvironmentVariable ("EIGHTBALL_UI_PAGE", {}) },
    }));
}

void EightBallEditor::timerCallback()
{
    if (! uiReady) return;

    // Parameter changes (host automation, preset loads, state restore)
    auto* changed = new juce::DynamicObject();
    for (int i = 0; i < kNumParams; ++i)
    {
        const float v = processor.paramValue (i);
        if (v != lastSent[(size_t) i]) // NaN != anything -> always sent after uiReady
        {
            changed->setProperty (paramId (i), v);
            lastSent[(size_t) i] = v;
        }
    }
    juce::var changedVar (changed);
    if (changed->getProperties().size() > 0)
        browser.emitEventIfBrowserIsVisible ("params", changedVar);

    // Preset changed outside the UI (host program change, project reload)
    if (processor.presetVersion.load() != lastPresetVersion)
        sendPreset();
    if (processor.model.version.load() != lastModelVersion)
        sendModel();
    if (processor.learnVersion.load() != lastLearnVersion)
        sendLearn();

    // Autoload: pick up preset files added/removed/edited in the preset folder (every ~2 s)
    if (++ticks % 60 == 0 && processor.presetManager.rescanIfChanged())
        sendPresetList();

    // the operator scopes (20 Hz, only while the UI animates them)
    if (processor.wantScopes.load() && ticks % 3 == 0)
        sendScopes();

    // Sounding notes (host MIDI + UI keyboard)
    juce::Array<juce::var> on, off;
    for (int n = 0; n < 128; ++n)
    {
        const bool down = processor.keyboardState.isNoteOnForChannels (0xffff, n);
        if (down != lastNotes[(size_t) n])
        {
            lastNotes[(size_t) n] = down;
            (down ? on : off).add (n);
        }
    }
    if (! on.isEmpty() || ! off.isEmpty())
        browser.emitEventIfBrowserIsVisible ("notes", makeObject ({ { "on", on }, { "off", off } }));

    juce::Array<juce::var> ops, lfos;
    for (int k = 0; k < kNumOps; ++k) ops.add (juce::String (processor.statOpActivity[(size_t) k].load(), 4).getDoubleValue());
    for (int l = 0; l < kNumLfos; ++l) lfos.add (juce::String (processor.statLfo[(size_t) l].load(), 3).getDoubleValue());
    browser.emitEventIfBrowserIsVisible ("stats", makeObject ({
        { "voices",   processor.statVoices.load() },
        { "peak",     processor.statPeak.exchange (0.0f) },
        { "sustain",  processor.statSustain.load() },
        { "modWheel", processor.statModWheel.load() },
        { "bpm",      processor.statBpm.load() },
        { "ops",      ops },
        { "active",   processor.statActiveMask.load() },
        { "lfo",      lfos },
        { "gr",       juce::String (processor.statGr.exchange (0.0f), 2).getDoubleValue() },
    }));
}
