// ============================================================================
//  JUCE bridge: the plugin's side of the UI. Talks to the C++ processor
//  through JUCE 8's native integration (window.__JUCE__.backend), which JUCE
//  injects into the page. The web build provides the same backend in
//  vst/webhost/web-host.js, so app.js runs unchanged.
// ============================================================================
'use strict';

class JuceEngine {
  constructor() {
    this.backend = (window.__JUCE__ && window.__JUCE__.backend) || null;
    this.connected = !!this.backend;
    this.handlers = {};
    if (this.backend) {
      for (const ev of ['params', 'notes', 'stats', 'config', 'presetList', 'preset', 'saveResult', 'message',
                        'midiInputs', 'model', 'learn']) {
        this.backend.addEventListener(ev, (data) => { if (this.handlers[ev]) this.handlers[ev](data); });
      }
    }
  }

  on(event, fn) { this.handlers[event] = fn; }
  emit(id, payload) { if (this.backend) this.backend.emitEvent(id, payload || {}); }

  uiReady() { this.emit('uiReady'); }

  // parameters
  setParam(id, value) { this.emit('setParam', { id, value }); }
  setParams(values) { this.emit('setParams', { values }); }
  beginGesture(id) { this.emit('gesture', { id, begin: true }); }
  endGesture(id) { this.emit('gesture', { id, begin: false }); }

  // notes
  noteOn(note, vel) { this.emit('noteOn', { note, vel }); }
  noteOff(note) { this.emit('noteOff', { note }); }
  panic() { this.emit('panic'); }
  modWheel(value) { this.emit('modWheel', { value }); }

  // right-click on a control -> the host's parameter menu (automation...)
  paramMenu(id, x, y) { this.emit('paramMenu', { id, x: Math.round(x), y: Math.round(y) }); }
  // MIDI learn
  midiLearn(id) { this.emit('midiLearn', { id }); }
  midiForget(id) { this.emit('midiForget', { id }); }
  learnCancel() { this.emit('learnCancel'); }

  // model: harmonic editor waves, envelopes, drawn LFO shapes
  setWave(op, wave) { this.emit('setWave', { op, wave }); }
  setEnv(key, env) { this.emit('setEnv', { key, env }); }
  setLfoShape(lfo, shape) { this.emit('setLfoShape', { lfo, shape }); }

  // web build only (the plugin takes tempo + MIDI from the host)
  setTempo(bpm) { this.emit('setTempo', { bpm }); }
  selectMidi(id) { this.emit('selectMidi', { id }); }

  // presets
  loadPreset(id) { this.emit('loadPreset', { id }); }
  initPreset() { this.emit('initPreset'); }
  savePreset(name, overwrite) { this.emit('savePreset', { name, overwrite: !!overwrite }); }
  deletePreset(id) { this.emit('deletePreset', { id }); }
  loadPresetFile() { this.emit('loadPresetFile'); }
  openPresetFolder() { this.emit('openPresetFolder'); }
}
