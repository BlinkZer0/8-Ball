#pragma once
// ============================================================================
//  JUCE side of the parameter table (dsp/ParamTable.h holds the table itself):
//  host display strings, the APVTS layout, id lookup.
// ============================================================================
#include <juce_audio_processors/juce_audio_processors.h>
#include <unordered_map>
#include "dsp/ParamTable.h"

namespace eightball
{
inline const PDef& paramDef (int index) { return paramTable()[(size_t) index]; }
inline juce::String paramId (int index) { return juce::String (paramDef (index).id); }

inline int paramIndexForId (const juce::String& id)
{
    static const std::unordered_map<std::string, int> map = []
    {
        std::unordered_map<std::string, int> m;
        for (int i = 0; i < kNumParams; ++i) m[paramTable()[(size_t) i].id] = i;
        return m;
    }();
    const auto it = map.find (id.toStdString());
    return it == map.end() ? -1 : it->second;
}

inline juce::String formatValue (Unit unit, float v)
{
    switch (unit)
    {
        case Unit::Seconds:   return v < 1.0f ? juce::String (juce::roundToInt (v * 1000.0f)) + " ms" : juce::String (v, 2) + " s";
        case Unit::Ms:        return v < 10.0f ? juce::String (v, 1) + " ms" : juce::String (juce::roundToInt (v)) + " ms";
        case Unit::Hz:        return v >= 1000.0f ? juce::String (v / 1000.0f, v >= 10000.0f ? 1 : 2) + " kHz"
                                                  : (v < 10.0f ? juce::String (v, 2) : juce::String (juce::roundToInt (v))) + " Hz";
        case Unit::LfoHz:     return juce::String (v, v < 1.0f ? 3 : (v < 10.0f ? 2 : 1)) + " Hz";
        case Unit::Semitones: return (v > 0 ? "+" : "") + juce::String (v, std::abs (v - std::round (v)) > 0.01f ? 1 : 0) + " st";
        case Unit::Cents:     return (v > 0 ? "+" : "") + juce::String (juce::roundToInt (v)) + " ct";
        case Unit::Percent:   return juce::String (juce::roundToInt (v * 100.0f)) + "%";
        case Unit::BipolarPercent: return (v > 0.004f ? "+" : "") + juce::String (juce::roundToInt (v * 100.0f)) + "%";
        case Unit::Decibels:  return (v > 0.05f ? "+" : "") + juce::String (v, 1) + " dB";
        case Unit::Degrees:   return juce::String (juce::roundToInt (v)) + juce::String (juce::CharPointer_UTF8 ("\xc2\xb0"));
        case Unit::Ratio:     return juce::String (v, std::abs (v - std::round (v)) > 0.01f ? 2 : 0) + " x";
        case Unit::Pan:       return std::abs (v) < 0.005f ? juce::String ("C")
                                   : juce::String (juce::roundToInt (std::abs (v) * 100.0f)) + (v < 0 ? " L" : " R");
        case Unit::None:
        default:              return std::abs (v - std::round (v)) < 1e-4f ? juce::String (juce::roundToInt (v)) : juce::String (v, 2);
    }
}

// Same log mapping as paramToNorm / paramFromNorm (ParamTable.h, params.js)
inline juce::NormalisableRange<float> logRange (float lo, float hi)
{
    return { lo, hi,
             [] (float start, float end, float n) { return start * std::pow (end / start, n); },
             [] (float start, float end, float v) { return std::log (v / start) / std::log (end / start); },
             [] (float start, float end, float v) { return juce::jlimit (start, end, v); } };
}

inline juce::AudioProcessorValueTreeState::ParameterLayout createParameterLayout()
{
    juce::AudioProcessorValueTreeState::ParameterLayout layout;
    for (const auto& d : paramTable())
    {
        const juce::ParameterID pid { juce::String (d.id), 1 };
        const juce::String name (d.name);
        const auto unit = d.unit;
        switch (d.kind)
        {
            case Kind::Bool:
                layout.add (std::make_unique<juce::AudioParameterBool> (pid, name, d.def >= 0.5f));
                break;
            case Kind::Choice:
            {
                juce::StringArray choices;
                for (const auto& c : d.choices) choices.add (juce::String (c));
                layout.add (std::make_unique<juce::AudioParameterChoice> (pid, name, choices, (int) d.def));
                break;
            }
            case Kind::Int:
                layout.add (std::make_unique<juce::AudioParameterInt> (
                    pid, name, (int) d.min, (int) d.max, (int) d.def,
                    juce::AudioParameterIntAttributes().withStringFromValueFunction (
                        [unit] (int v, int) { return formatValue (unit, (float) v); })));
                break;
            case Kind::Float:
            default:
            {
                auto range = d.log ? logRange (d.min, d.max) : juce::NormalisableRange<float> (d.min, d.max);
                if (! d.log && d.step > 0) range.interval = d.step;
                layout.add (std::make_unique<juce::AudioParameterFloat> (
                    pid, name, range, d.def,
                    juce::AudioParameterFloatAttributes().withStringFromValueFunction (
                        [unit] (float v, int) { return formatValue (unit, v); })));
                break;
            }
        }
    }
    return layout;
}

// The C++ table as JSON (EightBallTests --dump-params; diffed against params.js by tests/check-params.ps1)
inline juce::var paramTableToJson()
{
    juce::Array<juce::var> out;
    for (const auto& d : paramTable())
    {
        auto* o = new juce::DynamicObject();
        o->setProperty ("id", juce::String (d.id));
        o->setProperty ("name", juce::String (d.name));
        o->setProperty ("type", d.kind == Kind::Bool ? "bool" : d.kind == Kind::Choice ? "choice" : d.kind == Kind::Int ? "int" : "float");
        o->setProperty ("min", d.min);
        o->setProperty ("max", d.max);
        o->setProperty ("def", d.def);
        o->setProperty ("step", d.kind == Kind::Float ? d.step : 1.0f);   // bool / choice / int step by 1
        const char* units[] { "", "s", "ms", "Hz", "lfohz", "st", "ct", "%", "bip", "dB", "deg", "ratio", "pan" };
        o->setProperty ("unit", units[(int) d.unit]);
        o->setProperty ("log", d.log);
        o->setProperty ("noPreset", d.noPreset);
        juce::Array<juce::var> ch;
        for (const auto& c : d.choices) ch.add (juce::String (c));
        o->setProperty ("choices", ch);
        out.add (juce::var (o));
    }
    return out;
}
} // namespace eightball
