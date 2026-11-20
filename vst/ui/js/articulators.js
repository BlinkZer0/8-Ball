// ============================================================================
//  The ARTICULATORS · LFO page:
//    - the envelope editor (EnvEditor) with a target picker: op 1-8 x
//      (amp, pitch, mod index) and filter 1-3 x (cutoff, level), a toolbar
//      (sync, sustain, loop, delete, shapes, copy / paste) and the matching
//      amount knob
//    - the four LFOs: on, wave, a shape screen (drawn shapes are edited right
//      there), rate / depth / delay / phase, sync + division, a live meter
//    - the 16-slot mod matrix: on, source, destination (grouped), amount
// ============================================================================
'use strict';

const ENV_KINDS_OP = [['Amp', 'AMP'], ['Pitch', 'PITCH'], ['Mod', 'MOD IDX']];
const ENV_KINDS_FLT = [['Cutoff', 'CUTOFF'], ['Level', 'LEVEL']];

// the group each mod destination belongs to (for the <optgroup>s)
function modDestGroup(id) {
  if (!id) return '';
  let m;
  if ((m = /^op(\d)/.exec(id))) return `Op ${m[1]}`;
  if (/^pm\d/.test(id)) return 'PM grid';
  if (/^rm\d/.test(id)) return 'Ring grid';
  if (/^out\d/.test(id)) return 'Output column';
  if ((m = /^flt(\d)/.exec(id))) return `Filter ${m[1]}`;
  if ((m = /^lfo(\d)/.exec(id))) return `LFO ${m[1]}`;
  const fx = { dst: 'Distortion', cho: 'Chorus', pha: 'Phaser', dly: 'Delay', rev: 'Reverb', eq: 'EQ', cmp: 'Compressor' };
  for (const k in fx) if (id.startsWith(k)) return fx[k];
  return 'Global';
}

class ArtPage {
  // host: { values, addKnob, control, setParam, getModel(), setEnv(key, env), setLfoShape(l, pts), menu, log }
  constructor(container, host) {
    this.host = host;
    this.container = container;
    this.target = { kind: 'op', index: 0, sub: 0 };   // -> key op1Amp
    this.clipboard = null;
    this.lfoUi = [];
    this.build();
    this.showTarget();
  }

  get key() {
    const t = this.target;
    return t.kind === 'op' ? `op${t.index + 1}${ENV_KINDS_OP[t.sub][0]}` : `flt${t.index + 1}${ENV_KINDS_FLT[t.sub][0]}`;
  }
  // amount parameter that scales this envelope, if any
  get amountId() {
    const t = this.target;
    if (t.kind === 'op') return t.sub === 1 ? `op${t.index + 1}PitchEnvAmt` : t.sub === 2 ? `op${t.index + 1}ModEnvAmt` : null;
    return t.sub === 0 ? `flt${t.index + 1}EnvAmt` : null;
  }

  build() {
    const h = this.host;
    const top = document.createElement('div');
    top.className = 'art-top';

    // ---- envelopes -------------------------------------------------------------
    const env = document.createElement('div');
    env.className = 'panel env-panel';
    const head = document.createElement('div');
    head.className = 'panel-head env-head';
    head.innerHTML = '<span class="panel-title">ENVELOPES</span>';
    this.targetBar = document.createElement('div');
    this.targetBar.className = 'env-targets';
    for (let k = 0; k < NUM_OPS; k++) this.targetBar.appendChild(this.targetButton(`OP ${k + 1}`, 'op', k));
    const sep = document.createElement('span'); sep.className = 'env-sep'; this.targetBar.appendChild(sep);
    for (let f = 0; f < NUM_FILTERS; f++) this.targetBar.appendChild(this.targetButton(`F${f + 1}`, 'flt', f));
    head.appendChild(this.targetBar);
    this.kindBar = document.createElement('div');
    this.kindBar.className = 'seg env-kinds';
    head.appendChild(this.kindBar);
    env.appendChild(head);

    this.editor = new EnvEditor({ width: 760, height: 236, menu: h.menu,
      onChange: (e) => { h.setEnv(this.key, e); },
      onSelect: () => this.refreshToolbar(),
      labelFor: (l) => this.levelLabel(l) });
    env.appendChild(this.editor.el);

    const bar = document.createElement('div');
    bar.className = 'env-toolbar';
    const btn = (text, tip, fn, cls) => {
      const b = document.createElement('button');
      b.type = 'button'; b.className = `pd-btn env-btn ${cls || ''}`; b.textContent = text; b.dataset.tip = tip;
      b.addEventListener('click', fn);
      bar.appendChild(b);
      return b;
    };
    this.syncBtn = new ToggleButton({ name: 'Sync' }, 0, (v) => this.editor.setSync(v >= 0.5), 'SYNC');
    this.syncBtn.el.dataset.tip = 'Envelope times in beats (host tempo) instead of seconds';
    bar.appendChild(this.syncBtn.el);
    this.susBtn = btn('SUSTAIN', 'Hold the envelope at the selected point while the key is down (click again to clear)', () => this.editor.setSustain(this.editor.selected));
    this.loopStartBtn = btn('LOOP START', 'Loop from the selected point…', () => this.editor.setLoopStart(this.editor.selected));
    this.loopEndBtn = btn('LOOP END', '…to the selected point while the key is down', () => this.editor.setLoopEnd(this.editor.selected));
    this.clearLoopBtn = btn('CLEAR LOOP', 'Remove the loop', () => this.editor.clearLoop());
    this.delBtn = btn('DELETE', 'Delete the selected point (or double-click it)', () => this.editor.deletePoint(this.editor.selected));
    const shapes = document.createElement('select');
    shapes.className = 'param-select env-shapes';
    shapes.dataset.tip = 'Replace the envelope with a starting shape';
    shapes.appendChild(new Option('SHAPE…', ''));
    for (const p of ENV_PRESETS) shapes.appendChild(new Option(p.name, p.name));
    shapes.addEventListener('change', () => { if (shapes.value) this.editor.applyPreset(shapes.value); shapes.value = ''; });
    shapes.addEventListener('keydown', (e) => e.stopPropagation());
    bar.appendChild(shapes);
    btn('COPY', 'Copy this envelope', () => { this.clipboard = cloneEnv(this.editor.env); h.log(`Copied ${this.key}`); });
    this.pasteBtn = btn('PASTE', 'Paste the copied envelope here', () => { if (this.clipboard) { this.editor.env = cloneEnv(this.clipboard); this.editor.changed(); } });
    this.amountSlot = document.createElement('div');
    this.amountSlot.className = 'env-amount';
    bar.appendChild(this.amountSlot);
    this.hint = document.createElement('span');
    this.hint.className = 'env-hint';
    bar.appendChild(this.hint);
    env.appendChild(bar);
    top.appendChild(env);

    // ---- LFOs ------------------------------------------------------------------
    const lfo = document.createElement('div');
    lfo.className = 'panel lfo-panel';
    lfo.innerHTML = '<div class="panel-head"><span class="panel-title">LFO</span><span class="mx-hint">global · each voice fades one in over its Delay · a source on the mod matrix</span></div>';
    for (let l = 0; l < NUM_LFOS; l++) lfo.appendChild(this.lfoStrip(l));
    top.appendChild(lfo);
    this.container.appendChild(top);

    // ---- mod matrix --------------------------------------------------------------
    const mod = document.createElement('div');
    mod.className = 'panel mod-panel';
    mod.innerHTML = '<div class="panel-head"><span class="panel-title">MOD MATRIX</span><span class="mx-hint">source × amount is added to the destination knob (its full range = 100%) · right-click a slot\'s knob for MIDI learn</span></div>';
    const grid = document.createElement('div');
    grid.className = 'mod-grid';
    const groups = MOD_DEST_IDS.map(modDestGroup);   // <optgroup>s; the full names stay readable when closed
    this.modRows = [];
    for (let s = 0; s < NUM_MOD_SLOTS; s++) {
      const row = document.createElement('div');
      row.className = 'mod-row';
      row.innerHTML = `<span class="mod-num">${s + 1}</span>`;
      const on = h.control(ToggleButton, `mod${s + 1}On`, '');
      on.el.classList.add('mod-on');
      row.appendChild(on.el);
      const src = h.control(SelectBox, `mod${s + 1}Src`);
      src.el.classList.add('mod-src');
      row.appendChild(src.el);
      const arrow = document.createElement('span'); arrow.className = 'mod-arrow'; arrow.textContent = '›';
      row.appendChild(arrow);
      const dst = h.control(SelectBox, `mod${s + 1}Dst`, null, groups);
      dst.el.classList.add('mod-dst');
      row.appendChild(dst.el);
      h.addKnob(row, `mod${s + 1}Amt`, { size: 'sm', noValue: true, label: '' });
      const val = document.createElement('span'); val.className = 'mod-val'; row.appendChild(val);
      grid.appendChild(row);
      this.modRows.push({ s, row, val });
    }
    mod.appendChild(grid);
    this.container.appendChild(mod);
  }

  targetButton(text, kind, index) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'env-target';
    b.textContent = text;
    b.dataset.kind = kind; b.dataset.index = index;
    b.addEventListener('click', () => { this.target = { kind, index, sub: this.target.kind === kind ? this.target.sub : 0 }; this.showTarget(); });
    return b;
  }

  lfoStrip(l) {
    const h = this.host;
    const id = (f) => `lfo${l + 1}${f}`;
    const strip = document.createElement('div');
    strip.className = 'lfo-strip';
    strip.innerHTML = `<span class="lfo-num">LFO ${l + 1}</span>`;
    const on = h.control(ToggleButton, id('On'), 'ON');
    strip.appendChild(on.el);
    const wave = h.control(SelectBox, id('Wave'));
    wave.el.classList.add('lfo-wave');
    strip.appendChild(wave.el);
    const shape = new ShapeEditor(new Array(64).fill(0), { width: 128, height: 40, onChange: (pts) => h.setLfoShape(l, pts) });
    shape.el.classList.add('lfo-shape');
    shape.el.dataset.tip = 'LFO shape (drag to draw when the wave is Drawn)';
    strip.appendChild(shape.el);
    const meter = document.createElement('div');
    meter.className = 'lfo-meter';
    meter.innerHTML = '<div class="lfo-meter-fill"></div>';
    meter.dataset.tip = 'LFO output';
    strip.appendChild(meter);
    const knobs = document.createElement('div');
    knobs.className = 'knob-row lfo-knobs';
    const rate = h.addKnob(knobs, id('Rate'), { size: 'md', label: 'RATE' });
    h.addKnob(knobs, id('Depth'), { size: 'md', label: 'DEPTH' });
    h.addKnob(knobs, id('Delay'), { size: 'md', label: 'DELAY' });
    h.addKnob(knobs, id('Phase'), { size: 'md', label: 'PHASE' });
    strip.appendChild(knobs);
    const sync = document.createElement('div');
    sync.className = 'lfo-sync';
    sync.appendChild(h.control(ToggleButton, id('Sync'), 'SYNC').el);
    const div = h.control(SelectBox, id('Div'));
    div.el.classList.add('lfo-div');
    sync.appendChild(div.el);
    strip.appendChild(sync);
    this.lfoUi.push({ l, strip, shape, meter: meter.firstChild, rate, div: div.el });
    return strip;
  }

  // ---- envelope target --------------------------------------------------------------
  showTarget() {
    const t = this.target;
    this.targetBar.querySelectorAll('.env-target').forEach(b => b.classList.toggle('on', b.dataset.kind === t.kind && Number(b.dataset.index) === t.index));
    const kinds = t.kind === 'op' ? ENV_KINDS_OP : ENV_KINDS_FLT;
    this.kindBar.innerHTML = '';
    kinds.forEach(([, label], i) => {
      const b = document.createElement('button');
      b.type = 'button'; b.textContent = label;
      b.classList.toggle('on', i === t.sub);
      b.addEventListener('click', () => { this.target.sub = i; this.showTarget(); });
      this.kindBar.appendChild(b);
    });
    this.editor.selected = -1;
    this.loadEnv();
    // the amount knob for this envelope
    this.amountSlot.innerHTML = '';
    const aid = this.amountId;
    if (aid) this.host.addKnob(this.amountSlot, aid, { size: 'md', label: 'AMOUNT' });
    const hints = {
      Amp: 'level = gain', Pitch: 'level 0.5 = no change; the AMOUNT knob sets the range in semitones',
      Mod: 'level 0.5 = the PM depth as set; AMOUNT scales how much the envelope changes it',
      Cutoff: 'level × AMOUNT × 5 octaves added to the cutoff', Level: 'level = filter output gain',
    };
    const kind = t.kind === 'op' ? ENV_KINDS_OP[t.sub][0] : ENV_KINDS_FLT[t.sub][0];
    this.hint.textContent = hints[kind];
    this.refreshToolbar();
  }

  openEnv(key) {
    let m;
    if ((m = /^op(\d)(Amp|Pitch|Mod)$/.exec(key))) this.target = { kind: 'op', index: Number(m[1]) - 1, sub: ENV_KINDS_OP.findIndex(k => k[0] === m[2]) };
    else if ((m = /^flt(\d)(Cutoff|Level)$/.exec(key))) this.target = { kind: 'flt', index: Number(m[1]) - 1, sub: ENV_KINDS_FLT.findIndex(k => k[0] === m[2]) };
    this.showTarget();
  }

  loadEnv() {
    const model = this.host.getModel();
    const e = model && model.envs && model.envs[this.key];
    if (e) this.editor.setEnv(e);
    this.syncBtn.setValue(this.editor.env.sync ? 1 : 0);
  }

  levelLabel(l) {
    const t = this.target, v = this.host.values;
    const kind = t.kind === 'op' ? ENV_KINDS_OP[t.sub][0] : ENV_KINDS_FLT[t.sub][0];
    if (kind === 'Pitch') { const st = (2 * l - 1) * v[`op${t.index + 1}PitchEnvAmt`]; return `${st > 0 ? '+' : ''}${Math.round(st * 10) / 10} st`; }
    if (kind === 'Mod') { const x = 1 + (2 * l - 1) * v[`op${t.index + 1}ModEnvAmt`]; return `×${Math.round(Math.max(0, x) * 100) / 100}`; }
    if (kind === 'Cutoff') { const oct = l * v[`flt${t.index + 1}EnvAmt`] * 5; return `${oct > 0 ? '+' : ''}${Math.round(oct * 10) / 10} oct`; }
    return `${Math.round(l * 100)}%`;
  }

  refreshToolbar() {
    const sel = this.editor.selected >= 0;
    const e = this.editor.env;
    this.susBtn.disabled = !sel;
    this.susBtn.classList.toggle('on', sel && e.sustain === this.editor.selected);
    this.loopStartBtn.disabled = !sel;
    this.loopEndBtn.disabled = !sel;
    this.clearLoopBtn.disabled = e.loopStart < 0;
    this.delBtn.disabled = !sel || e.points.length <= 2;
    this.pasteBtn.disabled = !this.clipboard;
    this.syncBtn.setValue(e.sync ? 1 : 0);
  }

  // the model arrived / changed outside this page
  setModel(m) {
    if (!m) return;
    this.loadEnv();
    this.refreshToolbar();
    this.refreshLfoShapes();
  }

  // ---- LFOs ---------------------------------------------------------------------
  static lfoShapePoints(wave, drawn) {
    const N = 64, out = new Array(N);
    for (let i = 0; i < N; i++) {
      const p = i / N;
      out[i] = wave === 0 ? Math.sin(2 * Math.PI * p)
             : wave === 1 ? (p < 0.25 ? 4 * p : p < 0.75 ? 2 - 4 * p : 4 * p - 4)
             : wave === 2 ? 2 * p - 1
             : wave === 3 ? (p < 0.5 ? 1 : -1)
             : wave === 4 ? [0.3, -0.7, 0.9, 0.1, -0.4, 0.6, -0.9, 0.5][Math.floor(p * 8)]
             : (drawn && drawn[i] !== undefined ? drawn[i] : 0);
    }
    return out;
  }

  refreshLfoShapes() {
    const v = this.host.values, model = this.host.getModel();
    for (const u of this.lfoUi) {
      const wave = v[`lfo${u.l + 1}Wave`] | 0;
      const drawn = model && model.lfoShapes && model.lfoShapes[String(u.l + 1)];
      u.shape.setReadOnly(wave !== 5);
      u.shape.setPoints(ArtPage.lfoShapePoints(wave, drawn));
      const sync = v[`lfo${u.l + 1}Sync`] >= 0.5;
      u.rate.el.classList.toggle('na', sync);
      u.div.classList.toggle('na', !sync);
      u.strip.classList.toggle('off', v[`lfo${u.l + 1}On`] < 0.5);
    }
  }

  refresh(ids) {
    if (!ids || [...ids].some(id => /^lfo\d(Wave|Sync|On)/.test(id))) this.refreshLfoShapes();
    if (!ids || [...ids].some(id => /^mod\d/.test(id))) {
      for (const r of this.modRows) {
        const v = this.host.values, s = r.s + 1;
        const active = v[`mod${s}On`] >= 0.5 && v[`mod${s}Src`] > 0 && v[`mod${s}Dst`] > 0 && Math.abs(v[`mod${s}Amt`]) > 1e-6;
        r.row.classList.toggle('active', active);
        const dstId = MOD_DEST_IDS[v[`mod${s}Dst`] | 0];
        r.val.textContent = dstId ? formatParam(PARAM_BY_ID[`mod${s}Amt`], v[`mod${s}Amt`]) : '';
      }
    }
    if (!ids || [...ids].some(id => /EnvAmt$/.test(id))) this.editor.render();
  }

  // live LFO outputs from the plugin
  meters(lfo) {
    if (!lfo) return;
    for (const u of this.lfoUi) {
      const x = clamp(lfo[u.l] || 0, -1, 1);
      u.meter.style.top = x >= 0 ? `${(1 - x) * 50}%` : '50%';
      u.meter.style.height = `${Math.abs(x) * 50}%`;
    }
  }

  // knobs modulated by an active slot (for the little marker on each knob)
  modulatedIds() {
    const v = this.host.values, out = new Set();
    for (let s = 1; s <= NUM_MOD_SLOTS; s++) {
      if (v[`mod${s}On`] >= 0.5 && v[`mod${s}Src`] > 0 && Math.abs(v[`mod${s}Amt`]) > 1e-6) {
        const id = MOD_DEST_IDS[v[`mod${s}Dst`] | 0];
        if (id) out.add(id);
      }
    }
    return out;
  }
}
