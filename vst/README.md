# Eight Ball: VST3 plugin + Standalone (JUCE 8)

This folder is the source of truth for Eight Ball:
- **C++ DSP:** the engine, plain C++ with no JUCE in it (`Source/SynthEngine.h`, `Source/dsp/`), so milestone 6
  compiles the same code to WebAssembly.
- **HTML/SVG UI:** shown inside the plugin through WebView2.

## Build

```
build.bat            VST3 + Standalone + EightBallTests (Release)
build.bat Debug
install.bat          copies "Eight Ball.vst3" to C:\Program Files\Common Files\VST3 (asks for admin)
powershell -ExecutionPolicy Bypass -File package.ps1    dist\Eight-Ball-<version>-Windows-x64.zip
```

Requirements: Visual Studio 2022 or later with the C++ workload, Git, and the WebView2 runtime. Build files go to
`%LOCALAPPDATA%\EightBallVST`, so OneDrive doesn't sync them. JUCE 8.0.17 is reused from The Ham's, No Strings',
Brass Knuckles' or E-Piano's download when one exists, otherwise fetched:

- `...\build\EightBallVST_artefacts\Release\VST3\Eight Ball.vst3`
- `...\build\EightBallVST_artefacts\Release\Standalone\Eight Ball.exe` is the quickest way to test without a DAW.
  Use *Options → Audio/MIDI Settings* to pick the audio device and MIDI input.
- `...\build\EightBallTests_artefacts\Release\EightBallTests.exe`

To open the project in Visual Studio, open `%LOCALAPPDATA%\EightBallVST\build\EightBallVST.sln` after one build.

## Signal flow

```
per voice:   op 1..8 (wavetable, unison) <-- 8x8 PM grid, 8x8 ring grid, envelopes
             each op --> output column --> Filter 1 / Filter 2 / Filter 3 / Dry
             filters: Parallel | Series 1>2>3 | 1+2>3   (SVF, 12/24 dB, drive, key, env, velocity)
modulation:  4 LFOs (global, per-voice fade-in) + 30 envelopes + velocity / wheel / aftertouch / bend / key
             --> 16 mod slots --> added to any parameter's normalised value (per voice where it matters)
global:      sum of voices --> FX chain (7 units, any order) --> master (smoothed) --> safety clip --> out
2x OS:       the whole voice path at twice the rate, the voice sum decimated (polyphase half-band)
```

Control rate: every 32 samples. Envelopes, LFOs, the mod slots, pitch, levels, pans, sends, grid depths and
filter coefficients are recomputed per chunk and ramped per sample. Parameters are smoothed in their normalised
domain (about 5 ms) inside the engine.

The mod matrix adds `source × amount` to a destination's normalised value (0..1, then mapped like the knob) and
clamps. A destination among the operator, grid and filter parameters is resolved per voice, so envelopes,
velocity, key position and the LFOs (with each voice's own delay fade) differ from voice to voice; the other
destinations (portamento time, the FX) take only the global sources (LFOs, wheel, aftertouch, bend). Source
ranges: amplitude and filter envelopes 0..1, pitch and mod-index envelopes −1..1 (level 0.5 = 0), velocity,
wheel and aftertouch 0..1, bend −1..1, key −1 (C1) .. +1 (C9), LFOs −1..1 × depth. Synced LFOs lock to the song
position while the host plays and free-run otherwise.

The FX chain (`dsp/Effects.h`) runs at the base rate on the voice sum, in the order `fxOrder1..7` give (a unit
named twice runs once, units left out run last). Each unit computes `out = dry + enable × mix × (wet − dry)`:
`enable` follows the ON switch with a 3 ms time constant, so switching crossfades, and a unit that has settled off
is skipped and its state cleared, so it is a true bypass. Distortion: gain 1 + 30·drive² into tanh / hard clip /
sine fold / bit-crush (with sample hold), level-compensated, a one-pole tone (400 Hz … 20 kHz), output gain.
Chorus: two modulated delay lines (sine LFO, the right channel offset by spread × 90°). Phaser: 4 / 8 / 12
first-order all-passes swept ±2 octaves around the centre (200 Hz … 4 kHz), feedback, the right channel 90° apart.
Delay: 2 s stereo lines, the time smoothed over 50 ms (so changes glide, no clicks), tone at the output, ping-pong
(mono in, L → R → L). Reverb: Freeverb-style 8 damped combs + 4 all-passes per channel, size scaling the comb
lengths (smoothed), pre-delay up to 200 ms, width. EQ: RBJ biquads, recomputed per chunk from the smoothed knobs,
unused bands skipped. Compressor: peak detector with attack / release, threshold / ratio, makeup, an optional
limiter (instant attack, 50 ms release, −0.3 dBFS ceiling), gain reduction reported to the UI.

Operators run in index order. A PM cell from a lower-numbered operator uses this sample's output, from a
higher-numbered one the last sample's; self-feedback averages the last two samples. A cell's depth d gives
d² × 2 turns of phase per unit of modulator output (a full cell at modulator level 1 is about 12.6 rad). Ring
cells blend between unmodulated and multiplied.

Only operators that reach an output (not muted, allowed by solo, routed somewhere), and everything that modulates
them, are rendered. Filters nothing has fed during a note are skipped.

## In the DAW

- Loads as an instrument (Instrument|Synth) with stereo out and MIDI in.
- **492 automatable parameters.** Knob drags record as single automation gestures.
- **Right-click any control** for the UI's menu: MIDI learn / Forget CC, Reset to default, and the host's own
  parameter menu (FL Studio's *Create automation clip* / *Link to controller*). Shift+right-click opens DevTools.
- **Programs:** the factory presets appear in the DAW's preset/program menu.
- **MIDI:** note on/off with velocity, sustain (CC64), mod wheel (CC1), pitch bend, channel and poly aftertouch,
  all notes off / all sound off; events are applied at the exact sample. Learned CCs become parameter changes the
  host sees. CC 0, 1, 32, 64 and 120+ can't be learned.
- **Host tempo** drives tempo-synced envelopes and LFOs; synced LFOs follow the song position while playing.
- **Latency:** 0 samples, 1 sample with 2× oversampling on (reported to the host).
- **State:** the project saves every parameter, the model (waves, envelopes, LFO shapes), the preset name and the
  MIDI-learn map.

## Parameters

492, defined once in [Source/dsp/ParamTable.h](Source/dsp/ParamTable.h) and mirrored in
[ui/js/params.js](ui/js/params.js):

| Group | Parameters |
|---|---|
| global | master (not in presets), poly 1–32, voiceMode, portaOn, portaTime, oversample, bendRange |
| op1–8 | Wave, Ratio, Fine, Fixed, Hz, KeyTrack, Level, Pan, Vel, Unison, Detune, Spread, PhaseReset, Mute, Solo, PitchEnvAmt, ModEnvAmt |
| matrix | pm11…pm88 (row modulates column), rm11…rm88, out1F1…out8Dry |
| flt1–3 | On, Type, Slope, Cutoff, Reso, Drive, KeyTrack, EnvAmt, Vel, Mix; fltRouting |
| lfo1–4 | On, Wave, Rate, Sync, Div, Depth, Delay, Phase |
| fx | dst*, cho*, pha*, dly*, rev*, eq*, cmp*, fxOrder1–7 (the unit in each chain position) |
| mod1–16 | On, Src, Dst (any Float parameter), Amt |
| presetGain | the preset's level trim in dB (after the FX, before the master; the TRIM knob) |

The table is append-only and was frozen in milestone 1, so projects keep loading through every later milestone.

## The model

What a host lane can't automate lives in the Model and travels in presets and project state as JSON blocks:

```json
"waves":     { "1": { "mode": "harmonic", "levels": [1, 0.5, 0.33], "phases": [0, 0, 0] },
               "2": { "mode": "drawn", "shape": [256 values -1..1] } },
"envs":      { "op1Amp":    { "points": [[0, 0, 0], [0.005, 1, 0], [0.3, 0.8, -0.5], [0.6, 0, -0.5]],
                              "sustain": 2, "loopStart": -1, "loopEnd": -1, "sync": false },
               "op1Pitch":  ..., "op1Mod": ..., "flt1Cutoff": ..., "flt1Level": ... },
"lfoShapes": { "1": [64 values -1..1] }
```

Envelope points are `[time, level, tension]`: time in seconds (beats when synced), level 0..1, tension −1..1 per
segment (negative = fast start). Levels mean: amplitude = gain; pitch = (2·level − 1) × PitchEnvAmt semitones;
modulation index = 1 + (2·level − 1) × ModEnvAmt (scales the PM the operator receives); filter cutoff =
level × EnvAmt × 5 octaves; filter level = gain. Any part missing from a file loads at its default.

`ModelStore` (message thread) bakes a wavetable when a wave changes (about 2 ms, 8 mip levels of 2048 samples)
and hands a new `Model` to the audio thread through atomic incoming / retired pointers; nothing is allocated or
freed on the audio thread.

## Presets

- **Factory:** [presets/factory_presets.json](presets/factory_presets.json) is **generated by
  [presets/make_presets.py](presets/make_presets.py)**: 220 presets in 12 categories, each a short recipe against a
  builder (`op`, `pm`, `flt`, `lfo`, `mod`, `dist` …). Edit the recipes, run the script, never the JSON.
  `"modDst": { "mod1Dst": "flt1Cutoff" }` names a mod slot's destination by parameter id.
- **Level matching:** every factory preset carries a `presetGain` trim (the TRIM knob) so its loudest 100 ms sits at
  −18 dBFS RMS with the master at 1 (a C4 E4 G4 chord at velocity 100, or one note for basses, mono presets, drums
  and FX). `EightBallTests --presets presetsactory_presets.json --loudness` measures, `make_presets.py --match
  <that output>` writes the trims (`presets/trims.json`), holding one back when it would push the peak above −1 dBFS.
- **A/B:** the A / B buttons in the header flip between two sounds (the other slot starts as a copy of the
  current one); COPY puts the current sound into the other slot. Not saved with the project.
- **User folder:** `Documents\Eight Ball\Presets`, shared by every DAW and every instance; scanned on open and
  every 2 seconds; subfolders become category tabs; **SAVE** replaces the current user preset, **SAVE AS** asks for
  a name and before replacing a file; the **×** on a user preset moves it to the Recycle Bin.
- File format: `.ebpreset`, plain JSON
  `{ "format": "Eight Ball Preset", "version": 1, "name", "category", "params": { id: value }, "waves", "envs", "lfoShapes" }`.
  Missing parameters load at their defaults.

## Tests

Build with `build.bat`, then run from `%LOCALAPPDATA%\EightBallVST\build\EightBallTests_artefacts\Release\`:

| Command | Checks |
|---|---|
| `EightBallTests.exe` | parameter table (count, index helpers, unique ids, neutral defaults for later milestones, the mod-destination list), presets (factory incl. `modDst`, round trip with model blocks, partial and garbage files), wavetables (normalisation, mip selection, drawn-shape DFT), envelopes (shapes, sustain, release and retrigger fades, loops, one-shots), operators (pitch of every mode, velocity, pan, every starter wave, custom waves, mute / solo / level / output column), matrix (PM sidebands, feedback, cells from higher-numbered operators, stacks, ring mod, the active-operator logic), filters (every type and slope, bypass = exact dry, mix 0, resonance, key tracking, envelope, velocity, every routing, drive), voices (polyphony and stealing, mono, legato and portamento, sustain, no stuck notes, panic, bend, envelopes, tempo sync), quality (phase reset, unison beating and spread, oversampling bypass and delay, aliasing of tables and of modulated high notes, clicks on level / ratio / depth jumps, the safety clipper, the model hand-off), LFOs + mod matrix (tremolo rate, tempo sync at two tempos, delay fade, square / S&H / drawn / phase, bypass: LFO off, slot off, amount 0, depth 0, no destination = bit-identical to the plain render; velocity → cutoff, key → level per voice, an envelope as a source, the wheel, two slots adding up, a global destination, the stats, no clicks with an LFO on a resonant cutoff), FX chain (every unit off and every unit at mix 0 bit-identical to no chain; distortion harmonics, tone and types; chorus width and level; the phaser's sweeping notch; delay echo timing, feedback, sync at two tempos, ping-pong, tone; reverb tail, decay, pre-delay, width; every EQ band; compression, the gain-reduction stat, the limiter ceiling; the chain order and its resolution; a click-free switch-on of every unit; off again mid-note = exactly the plain path), every factory preset through a full note |
| `--dump-params` | the C++ table as JSON; `tests\check-params.ps1` diffs it against params.js |
| `--bench` | 16 voices × 8 operators: 7.9% of one core (14.4% with 2× OS, 14.9% with unison 4, 8.9% with all 7 FX on); 2 ops: 2.6%; the FX alone 0.9% |
| `--loudness` | loudness of every factory preset (level matching, milestone 5) |
| `--render "<Category/Name>" out.wav [seconds] [note]` | a preset to a WAV |
| `--host-check "<path>\Eight Ball.vst3"` | loads the built VST3 like a DAW: scan, every parameter with a name and text, sound, automation during playback, state round trip into a fresh instance |
| `tests\run-ui-tests.ps1 [-Page ops\|wave\|matrix\|filters\|art\|fx\|presets]` | the UI in headless Edge with a stand-in bridge (69 checks: a control for every parameter, drags, the quick ADSR, the keyboard, the menu, tooltips, the browser, the filter panels and routing, the envelope editor, LFO shapes, the mod matrix, the FX chain drag-reorder, the EQ curve, the gain-reduction meter, the flow diagram, ANIMATE, cell glow and scopes, the wave editor, the A/B buttons) + a screenshot in `tests/screenshots/` |

## Layout

```
CMakeLists.txt  build.bat  install.bat  package.ps1
Source/
  dsp/ParamTable.h           the parameter table (plain C++)
  dsp/Common.h               constants, RNG, safety clipper, half-band decimator, SVF
  dsp/Wavetable.h            partials / drawn cycle -> mipmapped wavetable, starter shapes
  dsp/Envelope.h             multi-point envelopes
  dsp/Model.h                wavetables + envelopes + LFO shapes a voice reads
  dsp/Effects.h              the FX chain: distortion, chorus, phaser, delay, reverb, EQ, compressor / limiter
  SynthEngine.h              the engine (no JUCE)
  Params.h                   JUCE side of the table: display strings, APVTS layout, JSON dump
  ModelStore.*               model data, baking, JSON, lock-free hand-off
  PresetManager.*            factory presets, user folder, .ebpreset read/write
  MidiRouting.h              MIDI message -> engine
  PluginProcessor.*          APVTS, MIDI, MIDI learn, programs, state, latency
  PluginEditor.*             WebView2 host + JS <-> C++ bridge
ui/                          the UI (HTML/CSS/SVG/JS), embedded in the binary
  js/params.js               the parameter table (mirror)
  js/engine-juce.js          the bridge
  js/knob.js, controls.js    SVG knob; toggle, segmented, dropdown, mod wheel, tooltip, context menu
  js/piano.js, matrix.js     keyboard; the matrix page (grids, layouts, the flow diagram, the scopes)
  js/envelope.js             the multi-point envelope editor, the drawn-shape editor
  js/filters.js              the filters page (response curves, routing diagram)
  js/waveeditor.js           the operator wave editor (64 partials + phases, or a drawn cycle)
  js/articulators.js         the articulators page: envelope targets + toolbar, the LFOs, the mod matrix
  js/fx.js                   the FX page: the chain bar (drag to reorder), one panel per unit, the EQ curve
  js/app.js                  UI wiring
presets/factory_presets.json
tests/                       PresetTests.cpp (main), EngineTests.cpp, EngineTools.cpp, HostCheck.cpp,
                             TestRender.h, check-params.ps1, run-ui-tests.ps1, ui-tests.js, screenshots/
```

### Bridge events

| UI → host | host → UI (30 Hz, only changes) |
|---|---|
| `uiReady`, `setParam {id,value}`, `setParams {values}`, `gesture {id,begin}` | `params {id:value,…}` |
| `noteOn {note,vel}`, `noteOff {note}`, `panic`, `modWheel {value}` | `notes {on:[],off:[]}` (host MIDI + UI keys) |
| `loadPreset {id}`, `initPreset`, `savePreset {name,overwrite}`, `deletePreset {id}`, `loadPresetFile`, `openPresetFolder` | `presetList {presets,folder}`, `preset {id,name,category}`, `saveResult {ok,exists,name,error}`, `message {text}` |
| `paramMenu {id,x,y}`, `midiLearn {id}`, `midiForget {id}`, `learnCancel` | `learn {armed, map{id:cc}}` |
| `setWave {op,wave}`, `setEnv {key,env}`, `setLfoShape {lfo,shape}` | `model {waves,envs,lfoShapes}` |
| `setAnimate {on}` | `scope {ops[8][128]}` (20 Hz while on: each active operator's last 512 output samples, every 4th) |
| *web only:* `setTempo {bpm}`, `selectMidi {id}` | `stats {voices,peak,sustain,modWheel,bpm,ops[8],active,lfo[4],gr}`, `config {…}`, *web only:* `midiInputs` |

## Troubleshooting

- **Live UI editing:** set the environment variable `EIGHTBALL_UI_DIR` to this repo's `vst\ui` folder before
  starting the DAW or Standalone. The UI then loads from disk: edit HTML/CSS/JS and just reopen the plugin window.
  `EIGHTBALL_UI_PAGE=matrix` (or `filters`, `art`, `fx`, `presets`) opens that page first.
- **DevTools:** Shift + right-click in the plugin window, then *Inspect*.
- **Blank window:** the WebView2 runtime is missing or blocked. Its data folder is `%TEMP%\EightBallVST-WebView2`;
  deleting it is safe.
- The status bar shows the plugin format, sample rate and block size, and the last notes received. The header
  shows the host tempo that synced envelopes follow.
