// ============================================================================
//  Parameter definitions. Must match vst/Source/dsp/ParamTable.h exactly (IDs,
//  names, ranges, defaults, steps, units, log skew, choice lists, order).
//  EightBallTests --dump-params + tests/check-params.ps1 fail on any difference.
//  New parameters are only appended, with neutral defaults.
// ============================================================================
'use strict';

const NUM_OPS = 8, NUM_FILTERS = 3, NUM_LFOS = 4, NUM_MOD_SLOTS = 16, NUM_FX = 7, NUM_OUTPUTS = 4;
const MAX_VOICES = 32;

const OP_WAVES = ['Sine', 'Saw', 'Square', 'Triangle', 'Half-sine', 'Noise', 'Custom'];
const VOICE_MODES = ['Poly', 'Mono', 'Legato'];
const FLT_TYPES = ['Low-pass', 'Band-pass', 'High-pass'];
const FLT_SLOPES = ['12 dB', '24 dB'];
const FLT_ROUTINGS = ['Parallel', 'Series 1>2>3', '1+2 > 3'];
const LFO_WAVES = ['Sine', 'Triangle', 'Saw', 'Square', 'S&H', 'Drawn'];
const LFO_DIVS = ['1/1', '1/2D', '1/2', '1/2T', '1/4D', '1/4', '1/4T', '1/8D', '1/8', '1/8T',
                  '1/16D', '1/16', '1/16T', '1/32', '1/32T'];
const LFO_DIV_BEATS = [4, 3, 2, 4 / 3, 1.5, 1, 2 / 3, 0.75, 0.5, 1 / 3, 0.375, 0.25, 1 / 6, 0.125, 1 / 12];
const DRIVE_TYPES = ['Soft', 'Hard', 'Fold', 'Crush'];
const PHASER_STAGES = ['4', '8', '12'];
const FX_UNITS = ['Distortion', 'Chorus', 'Phaser', 'Delay', 'Reverb', 'EQ', 'Compressor'];
const OUT_BUSES = ['F1', 'F2', 'F3', 'Dry'];
const OUT_BUS_NAMES = ['Filter 1', 'Filter 2', 'Filter 3', 'Dry'];

function modSourceChoices() {
  const c = ['None'];
  for (let i = 1; i <= NUM_LFOS; i++) c.push(`LFO ${i}`);
  for (let i = 1; i <= NUM_OPS; i++) c.push(`Op ${i} Amp Env`);
  for (let i = 1; i <= NUM_OPS; i++) c.push(`Op ${i} Pitch Env`);
  for (let i = 1; i <= NUM_OPS; i++) c.push(`Op ${i} Mod Env`);
  for (let i = 1; i <= NUM_FILTERS; i++) c.push(`Filter ${i} Cutoff Env`);
  for (let i = 1; i <= NUM_FILTERS; i++) c.push(`Filter ${i} Level Env`);
  c.push('Velocity', 'Mod Wheel', 'Aftertouch', 'Pitch Bend', 'Key');
  return c;
}
const MOD_SOURCES = modSourceChoices();

// (id, name, group, min, max, def, unit, extra)
const fl = (id, name, group, min, max, def, unit, extra) => Object.assign({ id, name, group, type: 'float', min, max, def, unit: unit || '' }, extra || {});
const bo = (id, name, group, def) => ({ id, name, group, type: 'bool', min: 0, max: 1, step: 1, def });
const it = (id, name, group, min, max, def, unit) => ({ id, name, group, type: 'int', min, max, def, step: 1, unit: unit || '' });
const ch = (id, name, group, choices, def) => ({ id, name, group, type: 'choice', min: 0, max: choices.length - 1, step: 1, def, choices });

function buildParams() {
  const d = [];
  // ---- global
  d.push(fl('master', 'Master', 'global', 0, 1, 0.7, '%', { noPreset: true }));
  d.push(it('poly', 'Polyphony', 'global', 1, 32, 16));
  d.push(ch('voiceMode', 'Voice Mode', 'global', VOICE_MODES, 0));
  d.push(bo('portaOn', 'Portamento', 'global', 0));
  d.push(fl('portaTime', 'Portamento Time', 'global', 0.001, 5, 0.1, 's', { skew: 'log' }));
  d.push(bo('oversample', '2x Oversampling', 'global', 0));
  d.push(it('bendRange', 'Pitch Bend Range', 'global', 0, 24, 2, 'st'));
  // ---- operators
  for (let k = 1; k <= NUM_OPS; k++) {
    const o = `op${k}`, n = `Op ${k} `, g = `op${k}`;
    d.push(ch(`${o}Wave`, `${n}Wave`, g, OP_WAVES, 0));
    d.push(fl(`${o}Ratio`, `${n}Ratio`, g, 0.5, 32, 1, 'ratio', { step: 0.5 }));
    d.push(fl(`${o}Fine`, `${n}Fine`, g, -100, 100, 0, 'ct', { step: 1, bipolar: true }));
    d.push(bo(`${o}Fixed`, `${n}Fixed`, g, 0));
    d.push(fl(`${o}Hz`, `${n}Frequency`, g, 0.1, 20000, 440, 'Hz', { skew: 'log' }));
    d.push(fl(`${o}KeyTrack`, `${n}Key Track`, g, 0, 2, 1, '%'));
    d.push(fl(`${o}Level`, `${n}Level`, g, 0, 1, 1, '%'));
    d.push(fl(`${o}Pan`, `${n}Pan`, g, -1, 1, 0, 'pan', { bipolar: true }));
    d.push(fl(`${o}Vel`, `${n}Velocity`, g, 0, 1, 0.5, '%'));
    d.push(it(`${o}Unison`, `${n}Unison`, g, 1, 8, 1));
    d.push(fl(`${o}Detune`, `${n}Detune`, g, 0, 100, 10, 'ct'));
    d.push(fl(`${o}Spread`, `${n}Spread`, g, 0, 1, 0.5, '%'));
    d.push(bo(`${o}PhaseReset`, `${n}Phase Reset`, g, 1));
    d.push(bo(`${o}Mute`, `${n}Mute`, g, 0));
    d.push(bo(`${o}Solo`, `${n}Solo`, g, 0));
    d.push(fl(`${o}PitchEnvAmt`, `${n}Pitch Env Amount`, g, -48, 48, 12, 'st', { bipolar: true }));
    d.push(fl(`${o}ModEnvAmt`, `${n}Mod Env Amount`, g, 0, 1, 1, '%'));
  }
  // ---- matrix
  for (let s = 1; s <= NUM_OPS; s++)
    for (let t = 1; t <= NUM_OPS; t++)
      d.push(fl(`pm${s}${t}`, `PM ${s}${s === t ? ' Feedback' : ' > ' + t}`, 'matrix', 0, 1, 0, '%'));
  for (let s = 1; s <= NUM_OPS; s++)
    for (let t = 1; t <= NUM_OPS; t++)
      d.push(fl(`rm${s}${t}`, `Ring ${s}${s === t ? ' Self' : ' > ' + t}`, 'matrix', 0, 1, 0, '%'));
  for (let k = 1; k <= NUM_OPS; k++)
    for (let j = 0; j < NUM_OUTPUTS; j++)
      d.push(fl(`out${k}${OUT_BUSES[j]}`, `Op ${k} > ${OUT_BUS_NAMES[j]}`, 'matrix', 0, 1, (k === 1 && j === 3) ? 1 : 0, '%'));
  // ---- filters
  for (let f = 1; f <= NUM_FILTERS; f++) {
    const o = `flt${f}`, n = `Filter ${f} `, g = `flt${f}`;
    d.push(bo(`${o}On`, `${n}On`, g, 1));
    d.push(ch(`${o}Type`, `${n}Type`, g, FLT_TYPES, 0));
    d.push(ch(`${o}Slope`, `${n}Slope`, g, FLT_SLOPES, 0));
    d.push(fl(`${o}Cutoff`, `${n}Cutoff`, g, 20, 20000, 2000, 'Hz', { skew: 'log' }));
    d.push(fl(`${o}Reso`, `${n}Resonance`, g, 0, 1, 0.1, '%'));
    d.push(fl(`${o}Drive`, `${n}Drive`, g, 0, 1, 0, '%'));
    d.push(fl(`${o}KeyTrack`, `${n}Key Track`, g, 0, 1, 0, '%'));
    d.push(fl(`${o}EnvAmt`, `${n}Env Amount`, g, -1, 1, 0, 'bip', { bipolar: true }));
    d.push(fl(`${o}Vel`, `${n}Velocity`, g, -1, 1, 0, 'bip', { bipolar: true }));
    d.push(fl(`${o}Mix`, `${n}Mix`, g, 0, 1, 1, '%'));
  }
  d.push(ch('fltRouting', 'Filter Routing', 'filters', FLT_ROUTINGS, 0));
  // ---- LFOs
  for (let l = 1; l <= NUM_LFOS; l++) {
    const o = `lfo${l}`, n = `LFO ${l} `, g = `lfo${l}`;
    d.push(bo(`${o}On`, `${n}On`, g, 0));
    d.push(ch(`${o}Wave`, `${n}Wave`, g, LFO_WAVES, 0));
    d.push(fl(`${o}Rate`, `${n}Rate`, g, 0.02, 40, 2, 'lfohz', { skew: 'log' }));
    d.push(bo(`${o}Sync`, `${n}Sync`, g, 0));
    d.push(ch(`${o}Div`, `${n}Division`, g, LFO_DIVS, 8));
    d.push(fl(`${o}Depth`, `${n}Depth`, g, 0, 1, 1, '%'));
    d.push(fl(`${o}Delay`, `${n}Delay`, g, 0, 5, 0, 's'));
    d.push(fl(`${o}Phase`, `${n}Phase`, g, 0, 360, 0, 'deg'));
  }
  // ---- FX
  d.push(bo('dstOn', 'Distortion On', 'dst', 0));
  d.push(ch('dstType', 'Distortion Type', 'dst', DRIVE_TYPES, 0));
  d.push(fl('dstDrive', 'Distortion Drive', 'dst', 0, 1, 0.3, '%'));
  d.push(fl('dstTone', 'Distortion Tone', 'dst', 0, 1, 1, '%'));
  d.push(fl('dstMix', 'Distortion Mix', 'dst', 0, 1, 1, '%'));
  d.push(fl('dstOut', 'Distortion Output', 'dst', -24, 6, 0, 'dB'));

  d.push(bo('choOn', 'Chorus On', 'cho', 0));
  d.push(fl('choRate', 'Chorus Rate', 'cho', 0.02, 10, 0.8, 'lfohz', { skew: 'log' }));
  d.push(fl('choDepth', 'Chorus Depth', 'cho', 0, 1, 0.5, '%'));
  d.push(fl('choDelay', 'Chorus Delay', 'cho', 1, 30, 7, 'ms'));
  d.push(fl('choFeedback', 'Chorus Feedback', 'cho', -0.95, 0.95, 0, 'bip', { bipolar: true }));
  d.push(fl('choSpread', 'Chorus Spread', 'cho', 0, 1, 1, '%'));
  d.push(fl('choMix', 'Chorus Mix', 'cho', 0, 1, 0.5, '%'));

  d.push(bo('phaOn', 'Phaser On', 'pha', 0));
  d.push(fl('phaRate', 'Phaser Rate', 'pha', 0.02, 10, 0.5, 'lfohz', { skew: 'log' }));
  d.push(fl('phaDepth', 'Phaser Depth', 'pha', 0, 1, 0.7, '%'));
  d.push(ch('phaStages', 'Phaser Stages', 'pha', PHASER_STAGES, 1));
  d.push(fl('phaFeedback', 'Phaser Feedback', 'pha', -0.95, 0.95, 0.3, 'bip', { bipolar: true }));
  d.push(fl('phaCenter', 'Phaser Center', 'pha', 0, 1, 0.5, '%'));
  d.push(fl('phaMix', 'Phaser Mix', 'pha', 0, 1, 0.5, '%'));

  d.push(bo('dlyOn', 'Delay On', 'dly', 0));
  d.push(fl('dlyTime', 'Delay Time', 'dly', 1, 2000, 375, 'ms', { skew: 'log' }));
  d.push(bo('dlySync', 'Delay Sync', 'dly', 0));
  d.push(ch('dlyDiv', 'Delay Division', 'dly', LFO_DIVS, 8));
  d.push(fl('dlyFeedback', 'Delay Feedback', 'dly', 0, 0.95, 0.4, '%'));
  d.push(bo('dlyPingPong', 'Delay Ping-pong', 'dly', 0));
  d.push(fl('dlyTone', 'Delay Tone', 'dly', 0, 1, 0.6, '%'));
  d.push(fl('dlyMix', 'Delay Mix', 'dly', 0, 1, 0.3, '%'));

  d.push(bo('revOn', 'Reverb On', 'rev', 0));
  d.push(fl('revSize', 'Reverb Size', 'rev', 0, 1, 0.6, '%'));
  d.push(fl('revDecay', 'Reverb Decay', 'rev', 0, 1, 0.5, '%'));
  d.push(fl('revDamp', 'Reverb Damping', 'rev', 0, 1, 0.5, '%'));
  d.push(fl('revPreDelay', 'Reverb Pre-delay', 'rev', 0, 200, 10, 'ms'));
  d.push(fl('revWidth', 'Reverb Width', 'rev', 0, 1, 1, '%'));
  d.push(fl('revMix', 'Reverb Mix', 'rev', 0, 1, 0.25, '%'));

  d.push(bo('eqOn', 'EQ On', 'eq', 0));
  d.push(fl('eqLowCut', 'EQ Low Cut', 'eq', 20, 2000, 20, 'Hz', { skew: 'log' }));
  d.push(fl('eqHighCut', 'EQ High Cut', 'eq', 1000, 20000, 20000, 'Hz', { skew: 'log' }));
  d.push(fl('eqLowGain', 'EQ Low Gain', 'eq', -18, 18, 0, 'dB', { bipolar: true }));
  d.push(fl('eqLowFreq', 'EQ Low Freq', 'eq', 40, 1000, 200, 'Hz', { skew: 'log' }));
  d.push(fl('eqMidGain', 'EQ Mid Gain', 'eq', -18, 18, 0, 'dB', { bipolar: true }));
  d.push(fl('eqMidFreq', 'EQ Mid Freq', 'eq', 200, 8000, 1000, 'Hz', { skew: 'log' }));
  d.push(fl('eqMidQ', 'EQ Mid Q', 'eq', 0.3, 8, 1, ''));
  d.push(fl('eqHighGain', 'EQ High Gain', 'eq', -18, 18, 0, 'dB', { bipolar: true }));
  d.push(fl('eqHighFreq', 'EQ High Freq', 'eq', 1000, 16000, 5000, 'Hz', { skew: 'log' }));
  d.push(fl('eqMix', 'EQ Mix', 'eq', 0, 1, 1, '%'));

  d.push(bo('cmpOn', 'Compressor On', 'cmp', 0));
  d.push(fl('cmpThresh', 'Compressor Threshold', 'cmp', -60, 0, -12, 'dB'));
  d.push(fl('cmpRatio', 'Compressor Ratio', 'cmp', 1, 20, 4, 'ratio'));
  d.push(fl('cmpAttack', 'Compressor Attack', 'cmp', 0.1, 200, 10, 'ms', { skew: 'log' }));
  d.push(fl('cmpRelease', 'Compressor Release', 'cmp', 5, 2000, 100, 'ms', { skew: 'log' }));
  d.push(fl('cmpMakeup', 'Compressor Makeup', 'cmp', 0, 24, 0, 'dB'));
  d.push(bo('cmpLimit', 'Limiter', 'cmp', 0));
  d.push(fl('cmpMix', 'Compressor Mix', 'cmp', 0, 1, 1, '%'));

  for (let p = 0; p < NUM_FX; p++) d.push(ch(`fxOrder${p + 1}`, `FX Slot ${p + 1}`, 'fxOrder', FX_UNITS, p));

  // ---- global mod matrix: destinations = every float parameter before this point except master
  const dst = ['None'];
  for (const p of d) if (p.type === 'float' && !p.noPreset) dst.push(p.name);
  for (let s = 1; s <= NUM_MOD_SLOTS; s++) {
    const o = `mod${s}`, n = `Mod ${s} `;
    d.push(bo(`${o}On`, `${n}On`, 'mod', 1));
    d.push(ch(`${o}Src`, `${n}Source`, 'mod', MOD_SOURCES, 0));
    d.push(ch(`${o}Dst`, `${n}Destination`, 'mod', dst, 0));
    d.push(fl(`${o}Amt`, `${n}Amount`, 'mod', -1, 1, 0, 'bip', { bipolar: true }));
  }
  return d;
}

const PARAM_DEFS = buildParams();
const PARAM_BY_ID = Object.fromEntries(PARAM_DEFS.map(d => [d.id, d]));
// mod destination choice index -> parameter id
const MOD_DEST_IDS = ['', ...PARAM_DEFS.slice(0, PARAM_DEFS.findIndex(d => d.id === 'mod1On')).filter(d => d.type === 'float' && !d.noPreset).map(d => d.id)];

const opParamId = (op, field) => `op${op + 1}${field}`;   // op 0-based
const pmId = (s, t) => `pm${s + 1}${t + 1}`;
const rmId = (s, t) => `rm${s + 1}${t + 1}`;
const outId = (op, bus) => `out${op + 1}${OUT_BUSES[bus]}`;

function clamp(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }

function defaultParamValues() {
  return Object.fromEntries(PARAM_DEFS.map(d => [d.id, d.def]));
}

// value <-> 0..1 normalized (same mapping the VST host will see)
function paramToNorm(d, v) {
  if (d.skew === 'log') return clamp(Math.log(v / d.min) / Math.log(d.max / d.min), 0, 1);
  return clamp((v - d.min) / (d.max - d.min), 0, 1);
}

function paramFromNorm(d, n) {
  n = clamp(n, 0, 1);
  let v = d.skew === 'log' ? d.min * Math.pow(d.max / d.min, n) : d.min + n * (d.max - d.min);
  if (d.step) v = Math.round(v / d.step) * d.step;
  return clamp(v, d.min, d.max);
}

function formatParam(d, v) {
  if (d.type === 'choice') return d.choices[clamp(Math.round(v), 0, d.choices.length - 1)];
  if (d.type === 'bool') return v >= 0.5 ? 'On' : 'Off';
  switch (d.unit) {
    case 's':     return v < 1 ? `${Math.round(v * 1000)} ms` : `${v.toFixed(2)} s`;
    case 'ms':    return v < 10 ? `${v.toFixed(1)} ms` : `${Math.round(v)} ms`;
    case 'Hz':    return v >= 1000 ? `${(v / 1000).toFixed(v >= 10000 ? 1 : 2)} kHz` : v < 10 ? `${v.toFixed(2)} Hz` : `${Math.round(v)} Hz`;
    case 'lfohz': return `${v.toFixed(v < 1 ? 3 : v < 10 ? 2 : 1)} Hz`;
    case 'st':    return `${v > 0 ? '+' : ''}${Math.abs(v - Math.round(v)) > 0.01 ? v.toFixed(1) : Math.round(v)} st`;
    case 'ct':    return `${v > 0 ? '+' : ''}${Math.round(v)} ct`;
    case '%':     return `${Math.round(v * 100)}%`;
    case 'bip':   return `${v > 0.004 ? '+' : ''}${Math.round(v * 100)}%`;
    case 'dB':    return `${v > 0.05 ? '+' : ''}${v.toFixed(1)} dB`;
    case 'deg':   return `${Math.round(v)}°`;
    case 'ratio': return `${Math.abs(v - Math.round(v)) > 0.01 ? v.toFixed(2) : Math.round(v)} x`;
    case 'pan':   return Math.abs(v) < 0.005 ? 'C' : `${Math.round(Math.abs(v) * 100)} ${v < 0 ? 'L' : 'R'}`;
    default:      return Math.abs(v - Math.round(v)) < 1e-4 ? String(Math.round(v)) : v.toFixed(2);
  }
}
