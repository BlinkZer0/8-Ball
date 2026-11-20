# Conventions (inherited from The Ham, Brass Knuckles and E-PianoVST)

Eight Ball follows the house style of [E-PianoVST](https://github.com/BlinkZer0/E-PianoVST) v1.0 as refined by
Brass Knuckles and [The Ham](../../The%20Ham) (local clones in `../`). Everything in The Ham's
`docs/CONVENTIONS.md` applies. This file restates the rules briefly and, under **Eight Ball:**, lists every
place where Eight Ball changes or extends a pattern.

## 1. Repository layout

```
README.md                    user-facing: features, screenshots, build/install, release history, layout
.gitignore                   .vs/  build/  *.user  dist/
.gitattributes               * text=auto, *.bat and *.ps1 crlf
start.bat -> serve.ps1       PowerShell HttpListener serving web/ (or vst/ui with -Ui) on localhost:8080
docs/                        CONVENTIONS.md, PLAN.md, screenshots/, index.html (GitHub Pages copy of the web build)
web/index.html               GENERATED web build (milestone 6; never edited by hand)
vst/
  CMakeLists.txt  build.bat  install.bat  package.ps1  README.md
  Source/                    C++ (see 3)
  ui/                        HTML/CSS/SVG/JS UI, compiled into the binary as BinaryData
  webhost/                   WebAssembly build of the DSP core + browser stand-in for the bridge (milestone 6)
  presets/factory_presets.json
  tests/
```

## 2. Build system

- CMake 3.22+, C++17, **JUCE 8.0.17** (`GIT_TAG 8.0.17-security`), `FetchContent`, shallow. The cache variable
  `EIGHTBALL_JUCE_DIR` points at a local JUCE checkout instead; `build.bat` passes a sibling project's download
  (The Ham, No Strings, Brass Knuckles, E-Piano) when one exists.
- `juce_add_plugin`: `FORMATS VST3 Standalone`, `IS_SYNTH TRUE`, `NEEDS_MIDI_INPUT TRUE`, `NEEDS_WEBVIEW2 TRUE`,
  `VST3_CATEGORIES Instrument Synth`, `EDITOR_WANTS_KEYBOARD_FOCUS TRUE`, `COPY_PLUGIN_AFTER_BUILD FALSE`.
- Defines `JUCE_WEB_BROWSER=1`, `JUCE_USE_WIN_WEBVIEW2_WITH_STATIC_LINKING=1`, `JUCE_USE_CURL=0`,
  `JUCE_VST3_CAN_REPLACE_VST2=0`, `JUCE_DISPLAY_SPLASH_SCREEN=0`. The MSVC runtime is linked statically.
- One `juce_add_binary_data` target holds `ui/*.html|css|js|svg` and `presets/factory_presets.json`. BinaryData
  is looked up by file name, so every UI file name must be unique.
- Console app `EightBallTests` compiles the preset manager, the model store and the test sources, and includes
  the header-only engine. It is built with `JUCE_PLUGINHOST_VST3=1` for `--host-check`.
- `build.bat`: work dir `%LOCALAPPDATA%\EightBallVST` (build + deps), builds `EightBallVST_VST3`,
  `EightBallVST_Standalone` and `EightBallTests`. Messages are prefixed `[Eight Ball]`.
- `install.bat`: copies `Eight Ball.vst3` to `%CommonProgramFiles%\VST3` through an elevated PowerShell.
- `package.ps1`: `dist\Eight-Ball-<version>-Windows-x64.zip` with the Standalone, the VST3 and a README.txt, after
  checking with `dumpbin` that neither binary needs the Visual C++ Redistributable.

Identity: product `Eight Ball`, target `EightBallVST`, company `EightBall`, manufacturer code `Ebal`, plugin code
`Eb8b`, namespace `eightball`, env vars `EIGHTBALL_UI_DIR` / `EIGHTBALL_UI_PAGE`, WebView2 data folder
`%TEMP%\EightBallVST-WebView2`.

## 3. C++ source structure

| File | Role |
|---|---|
| `dsp/ParamTable.h` | **The parameter table in plain C++** (no JUCE): `enum ParamIndex`, index helpers (`opParam`, `pmParam`, `rmParam`, `outParam`, `fltParam`, `lfoParam`, `modParam`), `paramTable()` of `{id, name, Kind, min, max, def, step, Unit, log, choices, noPreset}`, the choice-index enums the engine uses, `paramToNorm / paramFromNorm`. |
| `dsp/Common.h` | Constants, `Rng`, the safety clipper, the half-band decimator (HIIR design), the TPT SVF. |
| `dsp/Wavetable.h` | `WaveSpec` (partials + phases, or a drawn cycle) -> band-limited mipmapped `Wavetable`; the starter shapes. |
| `dsp/Envelope.h` | `EnvSpec` (multi-point, tension, sustain, loop, sync) and the per-voice `EnvState`. |
| `dsp/Model.h` | `Model`: the per-operator wavetables, the 30 envelope specs, the drawn LFO shapes. |
| `SynthEngine.h` | The engine: voices, operators, the PM and ring grids, output column, filters, voice modes, oversampling. `prepare / setParamValues / setModel / noteOn / noteOff / render(L, R, n) / panic`. |
| `Params.h` | JUCE side: `formatValue`, `logRange`, `createParameterLayout()` with `ParameterID{id, 1}`, `paramTableToJson()`. |
| `ModelStore.*` | Message-thread owner of the model data; bakes wavetables, JSON in/out, lock-free hand-off to the engine. |
| `PresetManager.*` | Factory presets from BinaryData (templates + overrides), user folder scan, read/write/`migrate()`. |
| `MidiRouting.h` | MIDI message -> engine (shared by the plugin and the test tools), `learnableCC`. |
| `PluginProcessor.*` | APVTS, sample-accurate MIDI, MIDI learn, programs, state (params + model + learn map), latency. |
| `PluginEditor.*` | `WebBrowserComponent` (WebView2), resource provider, bridge events, 30 Hz timer that pushes only changes. |

Rules:
- `juce::ScopedNoDenormals` in `processBlock`. Feedback paths flush values below 1e-30 to exactly 0.
- The engine runs in **double** precision.
- **Control rate `kChunk = 32` samples.** Modulation is evaluated once per chunk and per-sample targets are ramped
  linearly across the chunk.
- Master gain is smoothed per sample. The output safety clipper is exactly linear below -1.9 dBFS.
- Parameter changes made by presets go through `beginChangeGesture / setValueNotifyingHost / endChangeGesture`.
  `master` is never stored in presets.

**Eight Ball:**
- **The DSP core has no JUCE in it at all**, including its parameter table, because milestone 6 compiles the same
  source to WebAssembly instead of hand-writing a JavaScript twin (E-Piano, Brass Knuckles and The Ham keep a
  line-for-line `dsp-worklet.js`; Eight Ball doesn't). `SynthEngine.h` and `dsp/*.h` are the files that build.
- **Parameters are smoothed inside the engine, in their normalised domain** (about 5 ms one-pole at the chunk
  rate), so every knob is click-free without the plugin doing anything. Bool / choice / int parameters snap.
- **The engine takes the raw parameter array** (`setParamValues (const float*)`) and maps it itself; there is no
  `EngineParamsFromValues.h`. The global mod matrix (milestone 2) applies to the normalised values, which is how
  "any knob" can be a destination.
- **Operators that do nothing cost nothing.** Once per chunk the engine finds the operators that reach an output
  (not muted, allowed by solo, routed somewhere) and, transitively, everything that modulates them; only those
  render. Filters that nothing has fed during a note are skipped too.

## 4. Parameters

- **Append-only.** New parameters go at the end of `ParamIndex`. Indices and string IDs never change.
- **New parameters default to neutral**, so older presets and projects sound unchanged.
- The **whole table is defined and frozen in milestone 1**: 491 parameters (global, 8 x 17 operator fields,
  8 x 8 PM, 8 x 8 ring, 8 x 4 output column, 3 x 10 filter fields + routing, 4 x 8 LFO fields, FX, 7 FX slots,
  16 x 4 mod slots). Parameters for later milestones exist but do nothing yet.
- `dsp/ParamTable.h` and `ui/js/params.js` are mirrored by hand. `EightBallTests --dump-params` prints the C++
  table as JSON and `tests/check-params.ps1` fails on any difference (ids, names, kinds, ranges, defaults, steps,
  units, log, choices, noPreset).

**Eight Ball:**
- **The mod matrix's destination list is "every Float parameter before the mod slots, except master"**, generated
  from the table in both C++ and JS. The mod slots are therefore the last block of the table, and any parameter
  appended later becomes a new destination at the end of the list.
- **State that is not a host parameter** lives in the **Model** and travels in presets and project state as named
  JSON blocks (`waves`, `envs`, `lfoShapes`): the harmonic editor's partials or drawn cycle per operator, the
  multi-point envelopes (3 per operator, 2 per filter), the drawn LFO shapes. The MIDI-learn map is project state
  only (`midiLearn`, `cc=paramId;...`), as in The Ham.

## 5. UI <-> C++ bridge

Inherited: `ui/js/engine-juce.js` wraps `window.__JUCE__.backend` in a `JuceEngine` class.
- UI -> host: `uiReady`, `setParam {id,value}`, `gesture {id,begin}`, `noteOn {note,vel}`, `noteOff {note}`, `panic`,
  `modWheel {value}`, `loadPreset {id}`, `savePreset {name,overwrite}`, `deletePreset {id}`, `loadPresetFile`,
  `openPresetFolder`, `paramMenu {id,x,y}`, `midiLearn {id}`, `midiForget {id}`, `learnCancel`. Web only: `setTempo`, `selectMidi`.
- Host -> UI (30 Hz, only changes): `params`, `notes`, `stats`, `config`, `presetList`, `preset`, `saveResult`,
  `message`, `learn`. Web only: `midiInputs`.
- On `uiReady` the editor clears its `lastSent` cache, so everything is sent again. Drags send `gesture begin/end`;
  one-shot changes are wrapped in a gesture by the editor. UI notes go through `MidiKeyboardState`.
- Dev mode: env var **`EIGHTBALL_UI_DIR`** loads the UI from disk. `EIGHTBALL_UI_PAGE` opens a page directly.

**Eight Ball** extensions:
- `setParams {values:{id:value...}}` sets many parameters at once (algorithm layouts, Clear, Randomize); each becomes
  its own gesture.
- `setWave {op, wave}`, `setEnv {key, env}`, `setLfoShape {lfo, shape}` edit the Model; the host answers with a full
  `model {waves, envs, lfoShapes}` whenever its version changes (a preset load, a project reload, an edit).
- `initPreset` loads the factory Init patch.
- `stats` carries `voices, peak, sustain, modWheel, bpm, ops[8] (mean |output| per operator), active (bit mask of
  operators doing something)` for the operator activity bars and, in milestone 4, the animated matrix.
- **Right-click on a control opens the UI's own menu**: MIDI learn / Forget CC, Reset to default, and "Host automation
  menu…" which sends `paramMenu` (FL Studio's *Create automation clip*). The Ham used a LEARN mode button instead;
  the brief asks for right-click. Shift + right-click keeps the browser menu (DevTools).

## 6. UI code

- Plain ES, `'use strict'`, no framework, no build step. Scripts load in order:
  `params.js, engine-juce.js, knob.js, controls.js, piano.js, matrix.js, app.js`.
- All controls are SVG. `Knob` is the reference widget (drag, Shift or Ctrl for fine, wheel, arrows, double-click
  reset, gestures; sizes `md` and `sm`). Panels are built in `app.js` (`addKnob`, `control(Class, id)`) and every
  control carries `data-param`. Pages are tabs with an LED that shows whether the page's features are active.
  The whole panel scales to fit the window.
- CSS custom properties on `:root`.

**Eight Ball:**
- Same widget family and dark chassis as E-Piano, new identity: **gunmetal panels, felt green-cyan accent
  (`--accent: #35d6b4`), an eight ball as the logo**, inverted keys (black naturals, white sharps). The console is
  laid out at 1260 px wide; the plugin window (1180 x 900) scales it.
- `Tooltip` (one floating element for every `[data-param]` / `[data-tip]`: name + value) and `ContextMenu`
  (the right-click menu) live in `controls.js`.
- `MatrixPage` (`matrix.js`) draws the 8 x 8 PM grid, the 8 x 8 ring grid and the output column as grids of small
  knobs and holds the algorithm layouts as plain data.
- The OPERATORS page is **eight strips**, one per operator (mute / solo, activity bar, wave screen and selector,
  then every knob in one row, with a quick AMP ENV ADSR that edits the four points of the operator's amplitude
  envelope). Pages: OPERATORS, MATRIX, FILTERS, ARTICULATORS · LFO, FX, PRESETS.

## 7. Presets

- Factory presets: `presets/factory_presets.json`, **templates and per-preset overrides**; model blocks merge the
  same way (only the parts given). The resolved values are defaults, then the template chain, then the preset.
- User presets: `Documents\Eight Ball\Presets`, subfolders = categories, rescanned every ~2 s by signature.
  Delete moves the file to the Recycle Bin. SAVE replaces the current user preset; SAVE AS asks for a name.
- File: `.ebpreset`, plain JSON `{ "format": "Eight Ball Preset", "version": 1, "name", "category",
  "params": {id: value}, "waves": {...}, "envs": {...}, "lfoShapes": {...} }`. Missing parameters load at their
  defaults, values are clamped, master is never stored, missing model parts load at their defaults.
- Factory presets are also host programs (`"<Category> - <Name>"`).

**Eight Ball:** 64 presets in milestone 5 (8 categories x 8); milestone 1 ships Init plus one per category.
Level-matched with `EightBallTests --loudness` in milestone 5.

## 8. Web build (milestone 6)

**Eight Ball:** the DSP core (`SynthEngine.h`, `dsp/*.h`) is compiled to WebAssembly with Emscripten and run in an
AudioWorklet; `web-host.js` provides `window.__JUCE__.backend` on top of Web Audio + Web MIDI, and `build-web.ps1`
assembles `web/index.html` from `ui/` the same way E-Piano does. There is no JavaScript twin of the engine and no
parity test: the browser runs the same compiled code as the plugin.

## 9. Tests

| Command | What |
|---|---|
| `EightBallTests.exe` | parameter table, presets, file round trip (with model blocks), old / partial / garbage files, and the engine checks: wavetables, envelopes, operators, the matrix, filters, voice modes, bypass switches, clicks, stuck notes, aliasing, oversampling, the model hand-off |
| `--dump-params` | C++ parameter table as JSON (diffed by `check-params.ps1`) |
| `--bench` | CPU for 16 voices x 8 operators (unison 1, 2x oversampling, unison 4) and a 2-op patch |
| `--loudness` | loudness of every factory preset (level matching) |
| `--render "<Category/Name>" out.wav [seconds] [note]` | renders a preset to a WAV, for listening without a DAW |
| `--host-check "<path to .vst3>"` | loads the built VST3 like a DAW: scan, parameters, sound, automation, state round trip |
| `tests\check-params.ps1` | params.js == ParamTable.h |
| `tests\run-ui-tests.ps1 [-Page ops|matrix|presets]` | the plugin UI in headless Edge with a stand-in bridge: no script errors, controls for every parameter, drag / double-click / layouts / quick ADSR / keyboard / right-click menu / tooltip / preset browser; also saves a screenshot |

**Eight Ball:** every on/off switch has a bypass test that renders with the feature off and compares with the
plain path: filter on/off (exactly equal to the dry render), filter mix 0, 2x oversampling off (identical to the
plain render; on matches it after the decimator's delay), mute, solo. Later milestones add the same for every
LFO, mod slot and FX unit.

## 10. Docs and release style

Plain, concrete language. Numbers are measured, not guessed (CPU %, test counts, delays). No Image-Line wording,
layouts or preset names anywhere: the brief's inspiration is the architecture only.
