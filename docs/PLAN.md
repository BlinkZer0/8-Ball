# Eight Ball: build plan

Status (2026-11-20): **milestone 1 built**: the DSP core, the 8 operators, the PM / ring / output matrix, the
plugin (VST3 + Standalone), a working OPERATORS and MATRIX UI, 10 starter presets, the test tool. All automated
checks pass; waiting for hand-testing in Minihost Modular.

The brief's milestones, each ending with a stop for hand-testing:

| # | Milestone | What it delivers | Status |
|---|---|---|---|
| 1 | DSP core + operators + matrix | plain-C++ engine, wavetable operators, 8x8 PM + 8x8 ring + output column, voice modes, 2x oversampling, the plugin, a usable UI for operators and the matrix | **done** |
| 2 | Filters + articulators + LFOs | the FILTERS page (DSP is already in the engine), the multi-point envelope editor, 4 LFOs, the 16-slot mod matrix | next |
| 3 | FX tab | Distortion, Chorus, Phaser, Delay, Reverb, EQ, Compressor / Limiter with drag-to-reorder | |
| 4 | Full UI + animated matrix | the harmonic editor and drawn shapes, glowing cells, per-operator scopes, signal-flow lines, Animate toggle | |
| 5 | Presets | 64 factory presets, level-matched, A/B compare | |
| 6 | HTML build | the DSP core compiled to WebAssembly, Web Audio + Web MIDI, the same UI and presets | |

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

| case | % of one core |
|---|---|
| 16 voices x 8 operators, unison 1, all carriers + 4 PM cells | 7.8% |
| the same with 2x oversampling | 14.1% |
| 16 voices x 8 operators, unison 4 | 14.8% |
| 16 voices x 2 operators (a classic 2-op patch) | 2.5% |

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
