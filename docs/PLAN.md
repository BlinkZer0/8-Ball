# Eight Ball: build plan

Status (2026-11-20): **all six milestones built, v1.0**: the full synth (milestones 1-4), 1044 level-matched
factory presets from 8-operator recipes with A/B compare and search (5), and the web build (6): the engine
compiled to WebAssembly under the same UI, at https://blinkzer0.github.io/8-Ball/ . All automated checks pass;
milestones 2-6 are still waiting for hand-testing by ear.

The brief's milestones, each ending with a stop for hand-testing:

| # | Milestone | What it delivers | Status |
|---|---|---|---|
| 1 | DSP core + operators + matrix | plain-C++ engine, wavetable operators, 8x8 PM + 8x8 ring + output column, voice modes, 2x oversampling, the plugin, a usable UI for operators and the matrix | **done** |
| 2 | Filters + articulators + LFOs | the FILTERS page, the multi-point envelope editor, 4 LFOs, the 16-slot mod matrix | **done** |
| 3 | FX tab | Distortion, Chorus, Phaser, Delay, Reverb, EQ, Compressor / Limiter with drag-to-reorder | **done** |
| 4 | Full UI + animated matrix | the harmonic editor and drawn shapes, glowing cells, per-operator scopes, signal-flow lines, Animate toggle | **done** |
| 5 | Presets | 1044 factory presets (the brief said 64; the user then asked for 200, then about 1000, built on 8-operator architectures that show the matrix off), level-matched, A/B compare | **done** |
| 6 | HTML build | the DSP core compiled to WebAssembly, Web Audio + Web MIDI, the same UI and presets | **done** |

## Milestone 1 notes

**The engine** (`vst/Source/SynthEngine.h` + `dsp/*.h`, plain C++):
- Every parameter is in a JUCE-free table (`dsp/ParamTable.h`, 491 parameters), frozen now so that projects from
  milestone 1 keep loading through milestone 6. The things a host lane can't automate (harmonic editor partials,
  drawn cycles, multi-point envelopes, drawn LFO shapes) live in the Model and travel as JSON blocks.
- Operators: a set of up to 128 partials (level + phase) or a drawn 256-point cycle is baked into a wavetable with
  8 mip levels (128, 64, 32, 16, 8, 4, 2, 1 harmonics), 2048 samples each; a note picks the fullest table whose top
  harmonic stays below Nyquist. Starter shapes: sine, saw, square, triangle, half-sine, noise. Ratio 0.5-32 in 0.5
  steps, fine +-100 cents, fixed Hz mode, key tracking 0-200% (ratio mode; fixed ignores it), level, pan, velocity,
  unison 1-8 with detune and spread (constant-power sum), phase reset or random start phase, mute, solo.
- The matrix: 8x8 PM depths (cell depth d = d^2 x 2 turns of phase at modulator level 1, so a full cell is about
  12.6 rad of index; cells from a lower-numbered operator use this sample's output, from a higher-numbered one
  the last sample's; self-feedback averages the last two samples, DX-style), 8x8 ring-mod depths (d: blend
  between unmodulated and multiplied), and the output column (each operator to Filter 1 / 2 / 3 / Dry).
  Mute removes an operator entirely; solo keeps only the soloed operators' outputs but their modulators still
  work, so a soloed carrier sounds as it does in the mix.
- Envelopes: multi-point with per-segment tension, sustain point, loop region, tempo sync. Every jump
  (release, retrigger, voice steal) fades the difference out over the next segment, so nothing clicks. Three per
  operator (amplitude, pitch: (2 level - 1) x amount semitones, modulation index: scales the incoming PM), two
  per filter (cutoff: level x amount x 5 octaves, level).
- Filters (DSP only in milestone 1; the page comes in 2): three TPT state-variable filters per voice, LP / BP /
  HP, 12 or 24 dB, drive (blend to tanh), key tracking, envelope and velocity to cutoff, mix; Parallel, Series
  1>2>3 or 1+2>3. A filter that nothing has fed in a note is skipped.
- Voices: 1-32 (default 16), Poly / Mono / Legato, portamento (time knob; glides in Poly from the last note too),
  sustain pedal, pitch bend (range knob), retrigger of a held note restarts the attack from the current level.
- Smoothing: parameters are smoothed in the engine (about 5 ms) and everything per-sample is ramped across each
  32-sample chunk: no zipper noise on any knob, measured by the click tests.
- 2x oversampling (toggle): the whole voice path runs at twice the rate and the voice sum is decimated with an
  8-coefficient polyphase half-band filter. Measured: a 440 Hz sine matches the plain path to 1.6% RMS after a
  1-sample delay (reported to the host); alias energy below the fundamental of a heavily modulated E7 drops to
  under half.

**Measured** (`EightBallTests --bench`, Release, this machine, 48 kHz):

| case | milestone 1 | milestone 2 | milestone 3 |
|---|---|---|---|
| 16 voices x 8 operators, unison 1, all carriers + 4 PM cells | 7.8% | 8.7% | 7.9% |
| the same with 2x oversampling | 14.1% | 14.8% | 14.4% |
| 16 voices x 8 operators, unison 4 | 14.8% | 15.8% | 14.9% |
| 16 voices x 2 operators (a classic 2-op patch) | 2.5% | 2.7% | 2.6% |
| 16 voices x 8 operators, all 7 FX units on | | | 8.9% |
| the FX chain alone (silence in) | | | 0.9% |

(% of one core; the figures move by about ±0.5 between runs, so the milestone-2 column was partly noise: the LFO
and mod-slot pass costs well under a point with no slots active)

After milestone 5, timed one case at a time with 20 s of idle before each (`--bench <case>`): 8 ops 8.2%, 2× OS
14.9%, unison 4 16.1%, 2 ops 2.7%, all 7 FX on 9.2%, the FX alone 1.0% (the oversampled distortion adds about
0.1 of that). **This laptop's turbo window closes about 2.5 s into a run**: in one `--bench` pass the cases after
the second read up to twice as slow (unison 4 at 23%, 2 ops at 6%) although the code is the same, so time cases
cold when a number matters.

Found by the checks during milestone 1 (fixed): parameters set to exactly 0 never reached the engine (the
first-value compare started from 0 instead of "unset"); a curved envelope segment could evaluate a hair past its
end and `pow()` a negative base, giving NaN at the end of a one-shot envelope (the Tine Piano preset) and a crash
in a table lookup (Brassy Lead): positions are now clamped and a non-finite phase reads as silence. Every factory
preset is now rendered through a full note by the tests.

**Checks**: `EightBallTests.exe` (parameter table, presets, files, 8 groups of engine checks: all pass),
`check-params.ps1` (491 parameters match), `run-ui-tests.ps1` (24 checks per page: pass), `--host-check` on the
built VST3 (scan, 491 parameters with names and text, sound, automation during playback, state round trip with
the model: pass).

**What to try in Minihost Modular** (milestone 1):
- `vst\build.bat`, `vst\install.bat`, rescan. Or run the Standalone `Eight Ball.exe`.
- Play the Init patch (a sine). On OPERATORS, turn op 2's PM into op 1 up on the MATRIX page (row 2, column 1):
  brightness. Try the algorithm buttons, RANDOMIZE, the diagonal (feedback) cells, the RING grid, and the
  output column (route an op to F1: filter 1 is a 2 kHz low-pass by default).
- Mute / solo, unison + detune + spread, FIXED with the Hz knob, phase RESET off (random start phases).
- The quick AMP ENV knobs per operator. Mono / legato / portamento at the bottom right. 2x OS.
- Presets: the 10 starters on the PRESETS page, SAVE AS, the user folder, LOAD, INIT. Save the Minihost project,
  reopen it: every knob, the envelopes and the preset name must come back.
- Right-click a knob: MIDI learn (move a controller), Forget, Reset, the host automation menu.
- Dev loop: set `EIGHTBALL_UI_DIR=<repo>\vst\ui` before starting Minihost and edit `vst/ui` live (reopen the
  window); `start.bat -Ui` previews the UI in a browser without audio; `EightBallTests --render "Basses/FM Punch
  Bass" out.wav` renders a preset to listen to without a DAW.

## Milestone 2 notes

**Engine** (`SynthEngine.h`):
- **LFOs** are four global oscillators updated once per chunk: sine, triangle, saw (rising), square, sample & hold
  (a new random value each cycle), or the drawn 64-point shape from the model (linear interpolation). Rate in Hz
  or a tempo division; a synced LFO locks its phase to the host's song position while playing (`ppq`, advanced by
  the samples rendered since the block started) and free-runs otherwise. Phase offset in degrees, depth 0..1.
  Each voice fades an LFO in over the LFO's Delay (linear, from the note start, also after a retrigger).
- **The mod matrix** resolves the active slots per chunk (on, a source, a destination, amount not 0). A
  destination among the operator, grid and filter parameters is per voice: in `updateVoice` the slots' sources are
  read for that voice (its envelope levels, velocity, key, the faded LFOs, the wheel / aftertouch / bend), summed
  per destination, added to the parameter's normalised value, clamped, and mapped; the operator / grid / filter
  code reads those parameters through `pv (voice, index)`, which falls back to the global value. The other
  destinations (portamento time, the FX parameters) are modulated globally by the global sources only, with the
  unmodulated value kept in `base[]` so the modulation is removed again when the slot goes. Everything a slot
  changes lands in the per-chunk targets, so it is ramped per sample like a knob move.
- Source ranges: amplitude and filter envelopes 0..1; pitch and mod-index envelopes −1..1 (their level 0.5 is
  neutral); velocity, wheel, aftertouch 0..1; bend −1..1; key −1 at C1 .. +1 at C9 (C4 = 0).
- The engine reports the LFO outputs (`lfoValue`) and the plugin sends them as `stats.lfo[4]` for the meters.

**UI**:
- FILTERS: one panel per filter (on, LP / BP / HP, 12 / 24 dB, a response screen computed from the SVF's
  analogue prototype at the current cutoff and resonance, the seven knobs, buttons that open the two envelopes),
  and the routing panel with a diagram and "fed by op …" per filter.
- ARTICULATORS · LFO: the envelope editor (`envelope.js`), the target bar (OP 1-8 / F1-F3 × AMP / PITCH / MOD IDX
  or CUTOFF / LEVEL), the toolbar (SYNC, SUSTAIN, LOOP START / END, CLEAR LOOP, DELETE, shapes, COPY / PASTE), the
  envelope's amount knob, the four LFO strips (wave, a shape screen that is drawable for the Drawn wave, rate,
  depth, delay, phase, sync + division, a live meter), and the 16 mod slots with a grouped destination list.
  Knobs an active slot drives carry an orange marker; the page LED lights for any LFO or slot in use.
- The quick AMP ENV knobs and the editor edit the same envelope: an edit in one refreshes the other, and the host's
  echo of a local edit is ignored for 300 ms as for parameters.

**Factory file**: `"modDst": { "mod1Dst": "flt1Cutoff" }` names a slot's destination by id (the numeric list index
is unreadable). Two starters use the new features: Wobble Bass (synced LFO 1 → filter 1 cutoff) and Vibrato Lead
(LFO 2 with a delay → op fine tune; the mod wheel → PM depth).

**What to try in Minihost Modular** (milestone 2):
- FILTERS: route op 1 to F1 on the MATRIX page (or load Wobble Bass), sweep CUTOFF and RESO, try 24 dB, BP / HP,
  DRIVE, the routing modes, the ON switch (must be a clean bypass), ENV with the CUTOFF ENV button.
- ARTICULATORS: pick OP 1 / AMP, drag points, drag a segment to curve it, double-click to add a point, right-click a
  point for sustain / loop, SYNC and change the host tempo, the shapes menu; then PITCH with the AMOUNT knob (a
  pitch drop), MOD IDX on a modulator-fed carrier. Check the quick ADSR knobs on OPERATORS follow.
- LFO 1 → a slot → Op 1 Level at 4 Hz (tremolo), then Filter 1 Cutoff; SYNC with 1/4 and press play; DELAY 1 s;
  Drawn wave and draw in the screen; the meter moves.
- Mod matrix: Velocity → Filter 1 Cutoff, Mod Wheel → PM 2 > 1, Key → Op 1 Pan, Aftertouch → anything; two slots
  on one knob. The orange marker on the destination knob. Save a preset with slots and envelopes, reload it,
  save the project and reopen it.

## Milestone 3 notes

**Engine** (`dsp/Effects.h`, `FxChain` in `SynthEngine::render` between the voice sum and the master):
- Every unit: `out = dry + enable × mix × (wet − dry)`. `enable` follows ON with a 3 ms time constant (a toggle
  crossfades, settled in about 10 ms); a unit that has settled off is skipped and reset, so OFF is bit-identical
  to no unit and a delay or reverb tail does not come back when the unit is switched on again.
- Order: `fxOrder1..7` name the unit in each position; the first mention of a unit wins, units left out run last
  in default order (so an automation lane that names the same unit twice still runs everything once).
- Distortion (soft tanh / hard / sine fold / bit-crush with sample hold, gain 1 + 30·drive², compensated by
  gain^−0.35, one-pole tone, output gain), chorus (two sine-modulated delay lines, spread = the right LFO's phase
  offset), phaser (4 / 8 / 12 all-passes, centre 200 Hz … 4 kHz swept ±2 octaves, feedback), delay (time in ms or
  a tempo division, smoothed over 50 ms so changes glide instead of clicking, tone at the output, ping-pong), reverb
  (Freeverb-style combs + all-passes, size, decay, damping, pre-delay, width), EQ (RBJ biquads per chunk, unused
  bands skipped), compressor (peak detector, attack / release, makeup, limiter at −0.3 dBFS, gain reduction in the
  stats). The chain costs about 0.8% of a core with every unit on (`--bench`).
- Added after milestone 5 (before the web build froze the engine): the distortion's shaper runs 2× oversampled
  (the half-band pair as upsampler and decimator; 2 samples of delay, the dry path delayed to match, reported as
  latency while the unit is on; the tests show the aliasing of a hard clip on E6 drops to under a third), and the
  limiter has 64 samples of lookahead (1.3 ms, reported as latency while LIMIT is on; a peak can no longer pass
  the ceiling). The safety clipper still sits after the master.

**UI**: the chain bar (seven chips; drag one, or a panel's ⋮⋮ handle, onto another to move it) and one panel per
unit in chain order: ON, the knobs, MIX; the EQ panel draws its response from the same biquad formulas, the
compressor shows its gain reduction, the delay greys out TIME or the division depending on SYNC. The FX tab LED
lights when any unit is on. Soft FM Pad (chorus + reverb) and Pluck (synced ping-pong delay) use the chain.

**What to try in Minihost Modular** (milestone 3):
- Load Pluck: the dotted-eighth ping-pong echo follows the host tempo; turn the delay off mid-phrase (no click, the
  tail stops cleanly), on again, change SYNC / DIV / TIME while playing (the time glides).
- Soft FM Pad: chorus and reverb; try SIZE, DECAY, PRE-DLY, WIDTH 0 (mono tail).
- Distortion types on a bass with DRIVE up; TONE; the OUT knob. Phaser on a pad with 12 stages and feedback.
- EQ: watch the curve while turning the knobs; LO CUT on a bass; a MID boost with a narrow Q.
- Compressor: THRESH down with a chord, the GR meter moves; LIMIT with MAKEUP up: no clipping.
- Drag REVERB before DISTORTION, then DELAY first; save a preset and reload it: the order comes back.

## Milestone 4 notes

**Wave editor** (`ui/js/waveeditor.js`, an overlay on the OPERATORS page, opened by clicking an operator's wave
screen):
- HARMONIC: 64 partials (the engine takes up to 128; files with more keep them, the editor shows 64), a level bar
  (0..100%) and a phase bar (−180°..+180°, stored in turns 0..1) each; drag across the bars to paint, Shift for
  nothing special (the bars are coarse enough), double-click a bar to reset it. DRAWN: `ShapeEditor` with 256
  points. Mode switches convert: harmonic → drawn renders the sum (normalised), drawn → harmonic is a DFT, the same
  maths as `partialsFromShape`. Starters: sine, saw, square, triangle, half-sine (drawn), organ. CLEAR, RANDOM
  (a few decaying partials, drawn out when in drawn mode), NORMALIZE. A preview of one cycle.
- Opening the editor on a starter wave shows that starter's partials (or the half-sine's drawing), so there is
  something to start from; the first edit switches the operator's Wave to Custom and sends `setWave`. Sends are
  throttled to 30 Hz while dragging (the plugin bakes a table per send, about 2 ms); the last state always goes
  out on release. The host's echo of a local edit is ignored for 300 ms as for envelopes.

**Animated matrix** (`ui/js/matrix.js`, second row of the MATRIX page):
- The engine keeps a 512-sample ring per operator (its output summed over voices, at the base rate even with
  2× OS) and `copyScope` hands out every 4th sample. The processor copies the eight rings into a buffer under a
  sequence counter whenever the UI has asked for them (`setAnimate`), the editor sends `scope` at 20 Hz for the
  active operators only (silent ones send an empty array).
- Glow: `stats.ops` (mean |output|) × a cell's depth drives a `--glow` custom property on each cell; the row /
  column numbers, the flow nodes and the edges use the same value. The flow diagram is rebuilt from the grid and
  output parameters whenever one changes; with ANIMATE on the PM and output edges run a dash animation.
- ANIMATE is remembered in localStorage (on by default). Off, the glow is cleared, the scopes go flat and the
  plugin stops sending scopes.

**Preset**: Harmonic Pad (two custom harmonic operators, a slow LFO on the cutoff, chorus + reverb).

**What to try in Minihost Modular** (milestone 4):
- OPERATORS: click op 1's wave screen; paint the level bars (hear the timbre change while dragging), the phase
  bars (a saw's phases change the shape, not much the sound), SAW / SQUARE / ORGAN, DRAWN and draw a shape, back
  to HARMONIC (the partials of your drawing), RANDOM, NORMALIZE, CLEAR, ✕ or Esc. The strip screen shows the
  result; the Wave dropdown reads Custom. Pick a starter in the dropdown again: the custom wave stays in the
  model, Custom brings it back. Save a preset with custom waves and reload it; save the project and reopen it.
- MATRIX: with ANIMATE on, play a chord on Two 4-op stacks: the cells, numbers, flow lines and scopes move;
  turn ANIMATE off: everything stops (and the plugin stops sending scopes). Load Harmonic Pad and watch the
  scopes of op 1 and 2.

## Milestone 5 notes

**The presets** are recipes in `vst/presets/make_presets.py`, a few lines each against a builder
(`Preset.op(k, ratio, level, ...)`, `pm`, `fb`, `out` / `carriers`, `flt`, `lfo`, `mod`, `dist` … `comp`, `mono` /
`legato`; envelope helpers `adsr`, `perc`, `pitch_drop`, `swell`, `env`). Families share a core (a `piano()`, a
`wobble()` with division / LFO shape / filter / distortion arguments, `growl()` with two formant band-passes, a
`lead()`, `pad()`, `pluck()`, `stab()`, `organ()`, a `drum()` and `fx()` wrapper) and every preset in a family sets
its own character. The script asserts unique names and at least 200 presets and writes `factory_presets.json`
(never edit the JSON). 1044 presets, 12 categories. Second round (after the user asked for about 1000 presets
that use more operators): every family is now an 8-operator architecture (a piano has three carriers with their
own modulators, a shared hammer and a soundboard sub; the dubstep bass has a saw carrier with feedback, its
octave, a ring-modulated formant carrier into filter 2, a sine sub to Dry and a transient click; pads have three
detuned carriers, a fifth and a slow index modulator; leads a 3-op stack, an octave carrier, a ring cell on the
wheel, a sub and breath noise; drums a pitch-dropping body, a knock, a click pair and noise). Variants are deep
copies with a modifier (`variant(base, 'Wide', mod_wide)` …) and the dubstep grid is divisions × LFO shapes ×
filter types × clean / dirty plus vowels × divisions. `make_presets.py` asserts that every preset has at least five
operators in the signal path (three for drum hits and noise effects).

**Level matching:** a new parameter `presetGain` (dB, after the FX, before the master; the TRIM knob in the global
strip) carries each preset's trim. `EightBallTests --presets <file> --loudness` measures every preset from a JSON
file without rebuilding (loudest 100 ms RMS at master 1: a C4 E4 G4 chord at velocity 100, one C1 for basses and
mono presets, one C3 for drums and FX; the note is released after 2 s so one-shots and releases count too), and
`make_presets.py --match <that output>` moves every trim so the measurement lands at -18 dBFS, holding a trim back
when it would put the peak above -1 dBFS (the compressor / limiter in a chain keeps the loop from converging
exactly, so the match runs three times; drum hits and effects are measured on a 40 ms window, everything else
on 100 ms). Result for the 1044-preset library: 1029 of 1043 trimmed presets within +-0.5 dB of -18 dBFS, the
rest within 1.4 dB (the kicks read 0.6 dB high because their own limiter pushes back, two hats and a tick are
held by the peak guard); trims range from -12.4 to +12 dB. Trims are stored in `presets/trims.json` and re-applied on every generation.

**A/B compare** (host side): `abToggle` snapshots the current sound (parameters, model, preset name), applies the
other slot and keeps the snapshot as the new other slot; the first flip therefore gives two copies. `abCopy`
overwrites the other slot. Not part of the project state. The header shows A / B and COPY.

**What to try in Minihost Modular** (milestone 5):
- Step through the categories with ‹ ›: levels should stay even (watch the meter). Dubstep Bass on C1-C2 with
  the host playing (synced wobbles follow the tempo and lock to the beat); the mod wheel opens most of them.
  Drums on C3; FX & Risers: Riser 2 Bars / 4 Bars with the transport running (they are in beats).
- A/B: load Wob 1/4 Classic, press B (a copy), load Growl Talk 1/8, press A / B to compare, COPY to overwrite.
- TRIM: the preset's own gain; it saves into user presets.

## Milestone 6 notes

**No JavaScript twin.** `vst/webhost/wasm-engine.cpp` is a flat C API (`eb_create`, `eb_params`, `eb_render`,
`eb_note_on` …, 40 exports) over `SynthEngine.h` + `dsp/*.h`, the same files the plugin compiles. `build-web.ps1`
runs `em++ -O3 -std=c++17 -fno-exceptions -fno-rtti -s STANDALONE_WASM=1 --no-entry` (Emscripten in
`%LOCALAPPDATA%\EightBallVST\emsdk`; `em++`, not `emcc`: the C++ runtime has to be linked) and gets a 162 KB
`.wasm` whose only imports are four WASI stubs (`fd_write` and friends, never called) and the memory-growth
notification; `web-host.js` satisfies them with no-ops. The page inlines the wasm as base64, the factory JSON and
the UI, as E-Piano does: `web/index.html` is 4.7 MB, one file, and `docs/index.html` is the GitHub Pages copy.

**Two engine instances.** The AudioWorklet owns the one that makes sound; the module (`WebAssembly.Module`) is
compiled once on the main thread and passed in through `processorOptions`, and the worklet's processor source is
built from `makeEngine`'s and `wasmImports`'s own source text so there is one wrapper for both sides. The main
thread keeps a second instance that bakes wavetables (`eb_bake_wave`, about 2 ms) and posts the finished table
(8 × 2049 floats) to the worklet (`eb_set_table`), so a wave drag never stalls the audio thread, the same split
as the plugin's ModelStore. Opened from disk Chrome and Edge refuse worklet modules on `file://`; the host then
runs that main-thread instance through a ScriptProcessor (1024-frame buffers rendered in 128-frame chunks). The
status bar says which (`Web · AudioWorklet · 48.0 kHz · ~10 ms`).

**The bridge.** `web-host.js` handles every event in `PluginEditor.h` the same way the C++ does: factory presets
are resolved in JS (defaults ← template chain ← params, `modDst` by id through `MOD_DEST_IDS`, model blocks
merged like `modelDataFromJson`), user presets live in localStorage or in a linked folder (File System Access,
remembered in IndexedDB, re-scanned every 2 s like the plugin's folder watcher, `.ebpreset` files identical to
the VST's), MIDI learn maps CC → parameter in JS and is remembered, A/B is the same snapshot swap, stats come
from the worklet at 30 Hz and scopes at 20 Hz while ANIMATE is on. `emitEvent` stays synchronous so the file and
folder pickers keep the click's user activation.

**Headless check.** `tests/run-web-tests.ps1` loads the built page in headless Edge with `tests/web-tests.js`
appended; the page exposes `window.__eightBallWeb` (`render(note, frames)` on the main-thread instance,
`loadFactory(i)`) so the test can render Init, Grand Piano, Wob 1/4 Sine LP, Kick 808 Deep and Chip Lead through
the real wasm and check RMS / peak / finiteness, as well as the preset browser, A/B and a browser preset's save,
search and delete. 28 checks.

**Version 1.0.** CMake project 1.0.0, the header reads v1.0, `package.ps1` names the zip after it.

**What to try in a browser** (milestone 6):
- `start.bat`, then http://localhost:8080 (Chrome or Edge for MIDI). Click once: the status bar should read
  `Web · AudioWorklet`. Play the keys and the A–' row; plug in a controller: the MIDI IN picker lists it.
- Step through the presets; the wobbles follow the BPM box. Open the wave editor and drag partials while holding a
  note: no dropouts. ANIMATE on the MATRIX page.
- FOLDER → pick `Documents\Eight Ball\Presets`: the plugin's user presets appear; SAVE AS writes a file the
  plugin sees. Reload the page: the folder reconnects after one click on FOLDER (the browser asks again).
- Open `web\index.html` straight from Explorer: it still plays (ScriptProcessor, more latency).
