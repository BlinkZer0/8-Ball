#pragma once
// ============================================================================
//  Presets
//   - factory presets, compiled in from presets/factory_presets.json
//     (templates + per-preset overrides; also exposed to the host as programs)
//   - user presets: *.ebpreset JSON files in Documents\Eight Ball\Presets
//     (shared by every DAW / instance; sub-folders become categories,
//      the folder is re-scanned automatically)
//   - a preset carries the parameter values plus the model blocks: the
//     harmonic editor waves, the multi-point envelopes, the drawn LFO shapes
//   - files carry a format version; older versions are migrated on load
// ============================================================================
#include "Params.h"
#include "ModelStore.h"
#include <vector>

namespace eightball
{
constexpr int kPresetVersion = 1;

struct PresetData
{
    juce::String name, category;
    std::array<float, kNumParams> values;   // NaN = not in preset -> parameter default
    ModelData model;                        // parts missing from the file keep their defaults

    PresetData() { values.fill (NAN); }
};

struct PresetEntry
{
    juce::String id;        // "user:<relative/path.ebpreset>"
    juce::String name, category;
    juce::File file;
};

class PresetManager
{
public:
    PresetManager();

    static juce::File userFolder();
    static constexpr const char* fileExtension = ".ebpreset";
    static constexpr const char* formatName = "Eight Ball Preset";

    // Factory (immutable, any thread)
    const std::vector<PresetData>& factory() const { return factoryPresets; }
    int findFactory (const juce::String& name) const;   // -1 if none

    // User library (message thread only)
    bool rescanIfChanged();                     // true if the list changed
    const std::vector<PresetEntry>& userPresets() const { return user; }
    const PresetEntry* findUser (const juce::String& id) const;
    juce::File fileForName (const juce::String& name) const;
    juce::String idForFile (const juce::File& f) const;  // "" if not inside the user folder
    juce::String categoryForFile (const juce::File& f) const;

    static bool readFile (const juce::File&, PresetData&, juce::String& error);
    static bool readJson (const juce::var& json, PresetData&, juce::String& error);
    static bool writeFile (const juce::File&, const PresetData&, juce::String& error);
    static juce::var toJson (const PresetData&);

    // Brings a preset object written by an older version up to kPresetVersion (in place).
    static void migrate (juce::var& json);

    // Tools only (EightBallTests --presets <file>): read the factory presets from this file instead of
    // the compiled-in copy, so presets can be measured and tuned without rebuilding.
    static juce::File factoryOverride;

private:
    void loadFactory();

    std::vector<PresetData> factoryPresets;
    std::vector<PresetEntry> user;
    juce::String signature;
    bool scanned = false;
};
} // namespace eightball
