# Eight Ball: v0.1 (milestone 1 of 6)

Eight Ball is an 8-operator FM synthesizer: harmonic-editor wavetable operators, an 8×8 phase-modulation grid
plus an 8×8 ring-modulation grid, three multimode filters, freeform envelopes, four LFOs, a mod matrix, an FX
chain and 64 presets, in a VST3 plugin, a Standalone app and (last) a browser build that runs the same DSP core
as WebAssembly. It is the fifth instrument in the family after
[E-Piano](https://github.com/BlinkZer0/E-PianoVST), Brass Knuckles, No Strings and The Ham, and is built the
same way.

| Build | Where | Status |
|---|---|---|
| **VST3 plugin** + Standalone | [`vst/`](vst/README.md) | milestone 1: the DSP core, the 8 operators, the matrix, the plugin, the OPERATORS and MATRIX pages, 10 starter presets; all automated checks pass |
| **Web build** | `web/index.html` | milestone 6 |

The plan, the milestones and the measured results are in [docs/PLAN.md](docs/PLAN.md). The house rules are in
[docs/CONVENTIONS.md](docs/CONVENTIONS.md).

## Screenshots

| OPERATORS | MATRIX |
|---|---|
| ![Operators page](vst/tests/screenshots/ui-ops.png) | ![Matrix page](vst/tests/screenshots/ui-matrix.png) |

(made by `vst\tests\run-ui-tests.ps1` from the real UI with a stand-in bridge)

## What it does so far (milestone 1)

**The 8 operators**
- Each operator plays a **band-limited, mipmapped wavetable** baked from a set of partials (level and phase each,
  up to 128) or a drawn cycle, so high notes don't alias. Starter shapes: sine, saw, square, triangle, half-sine,
  noise. The harmonic editor and drawn-shape mode arrive with the full UI (milestone 4); the engine, the preset
  format and the Custom wave already carry them.
- **Ratio** 0.5–32 in half steps, **fine** ±100 cents, **fixed** frequency mode (Hz), **key tracking** 0–200%.
- **Level**, **pan**, **velocity** sensitivity.
- **Unison** 1–8 sub-oscillators with **detune** and stereo **spread** (constant-power sum).
- **Phase reset** on (identical attacks) or off (each note starts at a random phase).
- **Mute** removes an operator entirely; **solo** keeps only the soloed operators' outputs, but their modulators
  keep working, so a soloed carrier sounds as it does in the mix.
- A quick **AMP ENV** (attack, decay, sustain, release) per operator edits the four points of its amplitude
  envelope. The envelopes are freeform multi-point underneath (tension per segment, sustain point, loop region,
  tempo sync); the editor comes in milestone 2.

**The matrix**
- An **8×8 PM grid**: every cell is a depth knob for "operator X modulates operator Y"; the diagonal is
  self-feedback. Phase modulation, DX-style: a full cell at modulator level 1 is about 12.6 rad of index.
- A separate **8×8 ring-modulation grid** that works the same way.
- An **output column** that sends each operator to Filter 1, Filter 2, Filter 3 and/or Dry, each with its own level.
- Drag a cell up or down, Ctrl or Shift for fine control, double-click to reset.
- **Algorithm layouts** fill the grid: single carrier, stacks of 2 / 3 / 4, a fan, parallel pairs, two 4-op stacks,
  stack + pair, three stacks, feedback chains, a shared modulator, all carriers (additive). Plus **Clear** and
  **Randomize** with an amount knob.
- Operators that reach no output (and nothing that only feeds them) cost nothing.

**Filters** (engine only in milestone 1; the page comes in milestone 2)
- Three multimode filters per voice: low-pass, band-pass, high-pass, 12 or 24 dB, with cutoff, resonance, drive,
  key tracking, envelope amount and velocity. Routing: Parallel, Series 1→2→3, or 1+2 → 3; a mix level each.

**Voices**
- 1–32 voices (16 by default), **Poly / Mono / Legato**, **portamento** with a time knob, sustain pedal,
  pitch bend with a range knob, aftertouch and mod wheel received (sources for the mod matrix in milestone 2).
- **2× oversampling** (toggle): the whole voice path runs at twice the rate and is decimated with a polyphase
  half-band filter. 1 sample of latency, reported to the host.
- Every knob is smoothed in the engine (about 5 ms) and everything per-sample is ramped: no zipper noise, no
  clicks on parameter changes, retriggers or releases (measured by the tests).

**Playing**
- MIDI: note on/off with velocity, sustain (CC64), mod wheel (CC1), pitch bend, channel and poly aftertouch,
  all-notes-off / all-sound-off.
- **MIDI learn: right-click any knob**, then move a controller. The menu also forgets a CC, resets the knob, and
  opens the host's own automation menu (FL Studio's *Create automation clip*). Learned CCs are saved in the project.
- 24-key on-screen keyboard (two octaves of the 88-key range, octave buttons or Z / X), lit by incoming MIDI;
  computer keys `A W S E D F T G Y H U J K O L P ; '`; a mod wheel; PANIC.
- Hover any control for a tooltip with its name and value.

**Presets**
- 10 starter presets (Init plus one per category: E-Pianos & Bells, Basses, Leads, Pads, Brass & Plucks,
  Organs & Keys, Evolving & Textures, FX & Percussion). The 64 level-matched factory presets come in milestone 5.
- A category browser (PRESETS page), ‹ › arrows, INIT, SAVE (replaces the current user preset), SAVE AS, LOAD,
  FOLDER; `*` after the name when you've changed something.
- `.ebpreset` files (plain JSON: every parameter plus the waves, envelopes and LFO shapes) in
  `Documents\Eight Ball\Presets`, shared by the plugin, the Standalone and (later) the web build; subfolders are
  categories; new files show up on their own.
- The host project saves every setting, the model and the MIDI-learn map.

## VST3 plugin and Standalone (`vst/`)

```
vst\build.bat      build VST3 + Standalone + the test tool (Release)
vst\install.bat    copy "Eight Ball.vst3" to C:\Program Files\Common Files\VST3
vst\package.ps1    dist\Eight-Ball-<version>-Windows-x64.zip (Standalone + VST3 + install notes)
```

- Loads as an instrument with stereo out and MIDI in. All 491 parameters can be automated, and a knob drag records
  as one automation move. MIDI events are applied at the exact sample they arrive.
- The 10 presets also appear in the DAW's program menu.
- The UI is HTML/SVG shown through WebView2 and scaled to the window size.
- Requirements: Windows, Visual Studio 2022 or later (C++ workload), Git. JUCE 8.0.17 is reused from a sibling
  project's download or fetched on the first build. Release builds link the MSVC runtime statically; users need
  only the WebView2 runtime (built into Windows 11 and current Windows 10).

Build details, the bridge between the UI and C++, tests and troubleshooting are in [vst/README.md](vst/README.md).

## Measured

`EightBallTests --bench` (Release, 48 kHz, one core of this machine):

| case | % of one core |
|---|---|
| 16 voices × 8 operators, unison 1 (all carriers + 4 PM cells) | 7.8% |
| the same with 2× oversampling | 14.1% |
| 16 voices × 8 operators, unison 4 | 14.8% |
| 16 voices × 2 operators | 2.5% |

Automated checks (all passing): the parameter table and the preset files, 7 groups of engine checks (wavetables,
envelopes, operators, matrix, filters, voices, quality: bypass switches, clicks, stuck notes, aliasing,
oversampling), `check-params.ps1` (491 parameters match between C++ and JS), `run-ui-tests.ps1` (24 UI checks per
page), `--host-check` (the built VST3 loaded like a DAW: parameters, sound, automation, state round trip).

**Still to confirm by hand:** everything in Minihost Modular and FL Studio: sound, the UI, MIDI learn, the
right-click host menu, project save / reopen.

## Dev workflow

- `EIGHTBALL_UI_DIR=<repo>\vst\ui` in the environment before starting the DAW or the Standalone: the UI loads from
  disk, so you can edit HTML / CSS / JS and just reopen the window.
- `start.bat -Ui` serves `vst/ui` in a browser as a UI preview (no audio).
- `EightBallTests --render "Basses/FM Punch Bass" out.wav 3 48` renders a preset to a WAV to hear DSP changes
  without a DAW. `--bench`, `--loudness`, `--host-check` as above.
- Milestone 6 adds the browser build with the same DSP core, which is the "hear DSP changes without recompiling the
  VST" path.

## Repository layout

```
web/index.html            web build (milestone 6)
docs/                     PLAN.md, CONVENTIONS.md
start.bat, serve.ps1      local server: the web build, or -Ui for the UI preview
vst/                      VST3 plugin + Standalone (JUCE 8): Source/, ui/, presets/, tests/
```
