#include "PresetManager.h"
#include "BinaryData.h"
#include <functional>

namespace eightball
{
namespace
{
float clampParam (int index, float v)
{
    const auto& d = paramDef (index);
    return juce::jlimit (d.min, d.max, v);
}

// Copies every known { "paramId": value } of obj into values. Returns how many were found.
int applyParamObject (const juce::var& obj, std::array<float, kNumParams>& values)
{
    int found = 0;
    if (auto* o = obj.getDynamicObject())
        for (const auto& prop : o->getProperties())
        {
            const int i = paramIndexForId (prop.name.toString());
            if (i < 0 || i == master || ! (prop.value.isDouble() || prop.value.isInt() || prop.value.isInt64() || prop.value.isBool()))
                continue;
            values[(size_t) i] = clampParam (i, (float) (double) prop.value);
            ++found;
        }
    return found;
}

// "modDst": { "mod1Dst": "flt1Cutoff" }: a mod slot's destination named by parameter id instead of
// its index in the destination list (factory file only; readable and immune to the list growing).
void applyModDstObject (const juce::var& obj, std::array<float, kNumParams>& values)
{
    auto* o = obj.getDynamicObject();
    if (o == nullptr) return;
    const auto& dst = modDestParams();
    for (const auto& prop : o->getProperties())
    {
        const int slotParam = paramIndexForId (prop.name.toString());
        const int target = paramIndexForId (prop.value.toString());
        if (slotParam < 0 || target < 0) { jassertfalse; continue; }   // typo in the factory file
        for (size_t i = 0; i < dst.size(); ++i)
            if (dst[i] == target) { values[(size_t) slotParam] = (float) i; break; }
    }
}
} // namespace

PresetManager::PresetManager()
{
    loadFactory();
}

//==============================================================================
// Factory file format:
//   { "templates": { "<name>": { "base": "<other template>"?, "params": {...}, "waves"?, "envs"?, "lfoShapes"? } },
//     "categories": [ { "name": "Basses",
//                       "presets": [ { "name": "...", "base": "<template>"?, "params": {...}, "waves"?, "envs"?, "lfoShapes"? } ] } ] }
// A preset's values = parameter defaults <- template chain (base first) <- its own params;
// model blocks merge the same way (only the parts given).
juce::File PresetManager::factoryOverride;

void PresetManager::loadFactory()
{
    const auto json = factoryOverride.existsAsFile()
                        ? juce::JSON::parse (factoryOverride.loadFileAsString())
                        : juce::JSON::parse (juce::String::fromUTF8 (BinaryData::factory_presets_json, BinaryData::factory_presets_jsonSize));
    const auto templates = json["templates"];

    std::function<void (const juce::String&, PresetData&, int)> applyTemplate;
    applyTemplate = [&] (const juce::String& name, PresetData& d, int depth)
    {
        if (name.isEmpty() || depth > 8) return;
        const auto t = templates[juce::Identifier (name)];
        jassert (t.isObject()); // unknown template name
        if (! t.isObject()) return;
        applyTemplate (t["base"].toString(), d, depth + 1);
        applyParamObject (t["params"], d.values);
        applyModDstObject (t["modDst"], d.values);
        modelDataFromJson (t, d.model);
    };

    if (const auto* cats = json["categories"].getArray())
    {
        for (const auto& cat : *cats)
        {
            const auto* list = cat["presets"].getArray();
            if (list == nullptr) continue;
            for (const auto& p : *list)
            {
                PresetData d;
                d.name = p["name"].toString();
                d.category = cat["name"].toString();
                applyTemplate (p["base"].toString(), d, 0);
                applyParamObject (p["params"], d.values);
                applyModDstObject (p["modDst"], d.values);
                modelDataFromJson (p, d.model);
                factoryPresets.push_back (std::move (d));
            }
        }
    }

    if (factoryPresets.empty()) // never leave the host with zero programs
    {
        PresetData init;
        init.name = "Init";
        init.category = "Init";
        factoryPresets.push_back (init);
    }
}

int PresetManager::findFactory (const juce::String& catSlashName) const
{
    for (size_t i = 0; i < factoryPresets.size(); ++i)
        if (factoryPresets[i].category + "/" + factoryPresets[i].name == catSlashName || factoryPresets[i].name == catSlashName)
            return (int) i;
    return -1;
}

//==============================================================================
juce::File PresetManager::userFolder()
{
    return juce::File::getSpecialLocation (juce::File::userDocumentsDirectory)
        .getChildFile ("Eight Ball")
        .getChildFile ("Presets");
}

juce::String PresetManager::idForFile (const juce::File& f) const
{
    const auto root = userFolder();
    if (! f.isAChildOf (root)) return {};
    return "user:" + f.getRelativePathFrom (root).replaceCharacter ('\\', '/');
}

juce::String PresetManager::categoryForFile (const juce::File& f) const
{
    const auto root = userFolder();
    const auto parent = f.getParentDirectory();
    if (parent == root || ! f.isAChildOf (root)) return "User";
    return parent.getRelativePathFrom (root).replaceCharacter ('\\', '/');
}

bool PresetManager::rescanIfChanged()
{
    const auto root = userFolder();
    root.createDirectory();

    const auto files = root.findChildFiles (juce::File::findFiles, true, juce::String ("*") + fileExtension);

    juce::String sig;
    for (const auto& f : files)
        sig << f.getFullPathName() << '|' << f.getSize() << '|' << f.getLastModificationTime().toMilliseconds() << ';';

    if (scanned && sig == signature) return false;
    scanned = true;
    signature = sig;

    user.clear();
    for (const auto& f : files)
        user.push_back ({ idForFile (f), f.getFileNameWithoutExtension(), categoryForFile (f), f });

    std::sort (user.begin(), user.end(), [] (const PresetEntry& a, const PresetEntry& b)
    {
        if (a.category != b.category) return a.category.compareNatural (b.category) < 0;
        return a.name.compareNatural (b.name) < 0;
    });
    return true;
}

const PresetEntry* PresetManager::findUser (const juce::String& id) const
{
    for (const auto& e : user)
        if (e.id == id) return &e;
    return nullptr;
}

juce::File PresetManager::fileForName (const juce::String& name) const
{
    return userFolder().getChildFile (juce::File::createLegalFileName (name.trim()) + fileExtension);
}

//==============================================================================
// Migration. Each step takes a preset object of version N to N + 1. Add a step
// whenever a release renames a parameter or changes what a stored value means;
// plain additions need nothing (missing params load at their defaults).
void PresetManager::migrate (juce::var& json)
{
    if (! json.isObject()) return;
    int version = json.hasProperty ("version") ? (int) json["version"] : 1;
    version = std::max (version, 1);
    if (version < kPresetVersion) version = kPresetVersion;
    json.getDynamicObject()->setProperty ("version", version);
}

//==============================================================================
// User file format:
//   { "format": "Eight Ball Preset", "version": 1, "name": "...", "category": "...",
//     "params": { "<paramId>": value, ... },          (master is never stored)
//     "waves": {...}, "envs": {...}, "lfoShapes": {...} }
bool PresetManager::readJson (const juce::var& input, PresetData& d, juce::String& error)
{
    if (! input.isObject()) { error = "Not an Eight Ball preset"; return false; }
    auto json = juce::JSON::parse (juce::JSON::toString (input, true)); // private copy for migration
    migrate (json);
    const bool hasParams = json["params"].isObject();
    const bool hasModel = json["waves"].isObject() || json["envs"].isObject() || json["lfoShapes"].isObject();
    if (! hasParams && ! hasModel)
    {
        error = "No Eight Ball settings found";
        return false;
    }
    applyParamObject (json["params"], d.values);
    d.name = json["name"].toString().trim();
    d.category = json["category"].toString();
    d.model = ModelData {};
    modelDataFromJson (json, d.model);
    return true;
}

bool PresetManager::readFile (const juce::File& f, PresetData& d, juce::String& error)
{
    juce::var json;
    if (! f.existsAsFile() || juce::JSON::parse (f.loadFileAsString(), json).failed() || ! json.isObject())
    {
        error = "Not a valid preset file: " + f.getFileName();
        return false;
    }
    if (! readJson (json, d, error))
    {
        error << " in " << f.getFileName();
        return false;
    }
    if (d.name.isEmpty()) d.name = f.getFileNameWithoutExtension();
    return true;
}

juce::var PresetManager::toJson (const PresetData& d)
{
    auto* params = new juce::DynamicObject();
    for (int i = 0; i < kNumParams; ++i)
    {
        const auto& def = paramDef (i);
        if (i == master || def.noPreset || std::isnan (d.values[(size_t) i])) continue;
        // round to 6 significant digits so the files stay readable
        const double v = juce::String (d.values[(size_t) i], 6).getDoubleValue();
        params->setProperty (juce::String (def.id), v);
    }
    auto* root = new juce::DynamicObject();
    root->setProperty ("format", formatName);
    root->setProperty ("version", kPresetVersion);
    root->setProperty ("name", d.name);
    root->setProperty ("category", d.category);
    root->setProperty ("params", juce::var (params));
    modelDataToJson (d.model, *root);
    return juce::var (root);
}

bool PresetManager::writeFile (const juce::File& f, const PresetData& d, juce::String& error)
{
    if (! f.getParentDirectory().createDirectory() || ! f.replaceWithText (juce::JSON::toString (toJson (d))))
    {
        error = "Couldn't write " + f.getFullPathName();
        return false;
    }
    return true;
}
} // namespace eightball
