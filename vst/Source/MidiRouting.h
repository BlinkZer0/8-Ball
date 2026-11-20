#pragma once
// How a MIDI message reaches the engine. Shared by the plugin (PluginProcessor)
// and the test tools. MIDI learn acts on parameters, so it lives in the
// processor, not here.
#include <juce_audio_basics/juce_audio_basics.h>
#include "SynthEngine.h"

namespace eightball
{
inline void routeMidi (SynthEngine& engine, const juce::MidiMessage& m)
{
    if (m.isNoteOn())                                   engine.noteOn (m.getNoteNumber(), m.getVelocity());
    else if (m.isNoteOff())                             engine.noteOff (m.getNoteNumber());
    else if (m.isSustainPedalOn())                      engine.setSustain (true);
    else if (m.isSustainPedalOff())                     engine.setSustain (false);
    else if (m.isPitchWheel())                          engine.setPitchBend ((m.getPitchWheelValue() - 8192) / 8192.0);
    else if (m.isControllerOfType (1))                  engine.setModWheel (m.getControllerValue() / 127.0);
    else if (m.isChannelPressure())                     engine.setAftertouch (m.getChannelPressureValue() / 127.0);
    else if (m.isAftertouch())                          engine.setAftertouch (m.getAfterTouchValue() / 127.0);
    else if (m.isAllSoundOff())                         engine.panic();
    else if (m.isAllNotesOff() || m.isResetAllControllers()) engine.allNotesOff();
}

// MIDI learn: controllers that can't be learned (bank select, mod wheel, sustain, channel mode messages).
inline bool learnableCC (int cc) { return cc != 0 && cc != 1 && cc != 32 && cc != 64 && cc < 120; }
} // namespace eightball
