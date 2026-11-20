// ============================================================================
//  The operator wave editor (OPERATORS page, opened from an operator's wave
//  screen). Two modes, both baked by the plugin into a band-limited mipmapped
//  wavetable (dsp/Wavetable.h):
//    HARMONIC: 64 partials, a level bar and a phase bar each (drag to paint,
//              Shift = fine, double-click a bar = reset it)
//    DRAWN:    one 256-point cycle drawn by hand (ShapeEditor)
//  Switching modes converts the wave (harmonic sum -> points, or a DFT of
//  the points -> partials, the same maths as partialsFromShape). Starters,
//  Clear, Random, Normalize. Editing sets the operator's Wave to Custom.
//  spec = { mode: 'harmonic', levels: [...], phases: [...] } | { mode: 'drawn', shape: [256] }
// ============================================================================
'use strict';

const WAVE_PARTIALS = 64;
const WAVE_DRAW_POINTS = 256;

function harmonicToShape(levels, phases, N) {
  const out = new Float32Array(N);
  let peak = 0;
  for (let i = 0; i < N; i++) {
    let y = 0;
    for (let h = 0; h < levels.length; h++) if (levels[h]) y += levels[h] * Math.sin(2 * Math.PI * ((h + 1) * i / N + (phases[h] || 0)));
    out[i] = y;
    peak = Math.max(peak, Math.abs(y));
  }
  if (peak > 1e-9) for (let i = 0; i < N; i++) out[i] /= peak;
  return Array.from(out, v => Math.round(v * 10000) / 10000);
}

// partials of a drawn cycle (DFT), levels normalised so the strongest is 1, phases in turns
function shapeToHarmonic(shape, H) {
  const N = shape.length, levels = [], phases = [];
  let peak = 0;
  for (let h = 1; h <= H; h++) {
    let re = 0, im = 0;
    for (let i = 0; i < N; i++) { const a = 2 * Math.PI * h * i / N; re += shape[i] * Math.cos(a); im += shape[i] * Math.sin(a); }
    re *= 2 / N; im *= 2 / N;
    const mag = Math.sqrt(re * re + im * im);
    // sin(2 pi (h t + p)): component = im * sin + re * cos = mag * sin(2 pi h t + atan2(re, im))
    let p = Math.atan2(re, im) / (2 * Math.PI);
    p = ((p % 1) + 1) % 1;
    levels.push(mag); phases.push(mag > 1e-4 ? p : 0);
    peak = Math.max(peak, mag);
  }
  if (peak > 1e-9) for (let h = 0; h < H; h++) levels[h] = Math.round(levels[h] / peak * 10000) / 10000;
  for (let h = 0; h < H; h++) phases[h] = Math.round(phases[h] * 10000) / 10000;
  return { levels, phases };
}

const WAVE_STARTERS = [
  { name: 'SINE', make: () => ({ levels: [1], phases: [0] }) },
  { name: 'SAW', make: () => ({ levels: Array.from({ length: WAVE_PARTIALS }, (_, h) => 1 / (h + 1)), phases: new Array(WAVE_PARTIALS).fill(0) }) },
  { name: 'SQUARE', make: () => ({ levels: Array.from({ length: WAVE_PARTIALS }, (_, h) => h % 2 ? 0 : 1 / (h + 1)), phases: new Array(WAVE_PARTIALS).fill(0) }) },
  { name: 'TRIANGLE', make: () => ({ levels: Array.from({ length: WAVE_PARTIALS }, (_, h) => h % 2 ? 0 : 1 / ((h + 1) * (h + 1))), phases: Array.from({ length: WAVE_PARTIALS }, (_, h) => (h % 4 === 2) ? 0.5 : 0) }) },
  { name: 'HALF-SINE', drawn: true, make: () => Array.from({ length: WAVE_DRAW_POINTS }, (_, i) => i < WAVE_DRAW_POINTS / 2 ? Math.round(Math.sin(2 * Math.PI * i / WAVE_DRAW_POINTS) * 10000) / 10000 : 0) },
  { name: 'ORGAN', make: () => ({ levels: [1, 0.6, 0.8, 0.3, 0, 0.5, 0, 0.35, 0, 0, 0, 0.2, 0, 0, 0, 0.15], phases: new Array(16).fill(0) }) },
];

class WaveEditor {
  // host: { values, getModel(), setWave(k, spec), setParam(id, v), log, onChange(k) }
  constructor(container, host) {
    this.host = host;
    this.k = 0;
    this.spec = { mode: 'harmonic', levels: [1], phases: [0] };
    this.drag = null;
    this.lastSend = 0;
    this.pendingSend = null;
    this.build();
    container.appendChild(this.el);
  }

  build() {
    const el = document.createElement('div');
    el.className = 'wave-editor hidden';
    el.innerHTML = `
      <div class="panel wave-card">
        <div class="panel-head wave-head">
          <span class="panel-title">WAVE</span>
          <div class="env-targets wave-ops"></div>
          <div class="seg wave-mode"><button type="button" data-mode="harmonic">HARMONIC</button><button type="button" data-mode="drawn">DRAWN</button></div>
          <div class="wave-starters"></div>
          <button type="button" class="pd-btn env-btn wave-clear" data-tip="One partial (a sine) / a flat line">CLEAR</button>
          <button type="button" class="pd-btn env-btn wave-random" data-tip="Random partials">RANDOM</button>
          <button type="button" class="pd-btn env-btn wave-normalize" data-tip="Scale the levels so the strongest partial is 100%">NORMALIZE</button>
          <button type="button" class="pd-btn wave-close" data-tip="Close the editor (Esc)">✕</button>
        </div>
        <div class="wave-body harmonic">
          <div class="wave-bars-wrap">
            <span class="wave-axis">LEVEL</span>
            <svg class="wave-bars wave-levels" viewBox="0 0 ${WAVE_PARTIALS * 16} 160" preserveAspectRatio="none"></svg>
          </div>
          <div class="wave-bars-wrap">
            <span class="wave-axis">PHASE</span>
            <svg class="wave-bars wave-phases" viewBox="0 0 ${WAVE_PARTIALS * 16} 70" preserveAspectRatio="none"></svg>
          </div>
          <div class="wave-numbers"></div>
        </div>
        <div class="wave-body drawn"></div>
        <div class="wave-foot">
          <div class="screen wave-preview"><svg viewBox="0 0 400 60" preserveAspectRatio="none"><path class="scr-grid" d="M0 30 H400"/><path class="scr-line" d=""/></svg></div>
          <span class="wave-readout"></span>
        </div>
      </div>`;
    this.el = el;
    const opsBar = el.querySelector('.wave-ops');
    for (let k = 0; k < NUM_OPS; k++) {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'env-target'; b.textContent = `OP ${k + 1}`;
      b.addEventListener('click', () => this.open(k));
      opsBar.appendChild(b);
    }
    el.querySelectorAll('.wave-mode button').forEach(b => b.addEventListener('click', () => this.setMode(b.dataset.mode)));
    const starters = el.querySelector('.wave-starters');
    for (const s of WAVE_STARTERS) {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'pd-btn env-btn'; b.textContent = s.name;
      b.dataset.tip = `Start from a ${s.name.toLowerCase()}`;
      b.addEventListener('click', () => this.applyStarter(s));
      starters.appendChild(b);
    }
    el.querySelector('.wave-clear').addEventListener('click', () => this.clear());
    el.querySelector('.wave-random').addEventListener('click', () => this.random());
    el.querySelector('.wave-normalize').addEventListener('click', () => this.normalize());
    el.querySelector('.wave-close').addEventListener('click', () => this.close());
    el.addEventListener('pointerdown', (e) => { if (e.target === el) this.close(); });
    this.levelsSvg = el.querySelector('.wave-levels');
    this.phasesSvg = el.querySelector('.wave-phases');
    this.numbers = el.querySelector('.wave-numbers');
    this.preview = el.querySelector('.wave-preview .scr-line');
    this.readout = el.querySelector('.wave-readout');
    this.bindBars(this.levelsSvg, 'levels');
    this.bindBars(this.phasesSvg, 'phases');
    let nums = '';
    for (let h = 1; h <= WAVE_PARTIALS; h++) nums += `<span>${h % 4 === 1 || h === WAVE_PARTIALS ? h : ''}</span>`;
    this.numbers.innerHTML = nums;
    this.shape = new ShapeEditor(new Array(WAVE_DRAW_POINTS).fill(0), { width: 1024, height: 230, onChange: (pts) => { this.spec = { mode: 'drawn', shape: pts }; this.send(true); } });
    this.shape.el.classList.add('wave-draw');
    el.querySelector('.wave-body.drawn').appendChild(this.shape.el);
    window.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !this.el.classList.contains('hidden')) this.close(); });
  }

  get isOpen() { return !this.el.classList.contains('hidden'); }

  // ---- open / close ----------------------------------------------------------------
  open(k) {
    this.k = k;
    const m = this.host.getModel();
    const w = m && m.waves && m.waves[String(k + 1)];
    this.spec = w ? JSON.parse(JSON.stringify(w)) : { mode: 'harmonic', levels: [1], phases: [0] };
    // a starter wave (not Custom) is shown as its partials so there is something to start from
    const wave = this.host.values[opParamId(k, 'Wave')] | 0;
    if (wave !== 6) {
      const s = WAVE_STARTERS[Math.min(wave, 4)];
      this.spec = wave === 5 ? { mode: 'drawn', shape: Array.from({ length: WAVE_DRAW_POINTS }, () => Math.round((Math.random() * 2 - 1) * 1000) / 1000) }
                : s.drawn ? { mode: 'drawn', shape: s.make() } : Object.assign({ mode: 'harmonic' }, s.make());
    }
    this.el.querySelectorAll('.wave-ops .env-target').forEach((b, i) => b.classList.toggle('on', i === k));
    this.el.classList.remove('hidden');
    this.render();
  }
  close() { this.flushSend(); this.el.classList.add('hidden'); }

  // ---- editing -----------------------------------------------------------------------
  pad(arr) { const out = arr.slice(0, WAVE_PARTIALS); while (out.length < WAVE_PARTIALS) out.push(0); return out; }

  setMode(mode) {
    if (mode === this.spec.mode) return;
    if (mode === 'drawn') this.spec = { mode: 'drawn', shape: harmonicToShape(this.spec.levels, this.spec.phases || [], WAVE_DRAW_POINTS) };
    else this.spec = Object.assign({ mode: 'harmonic' }, shapeToHarmonic(this.spec.shape, WAVE_PARTIALS));
    this.send(true);
  }
  applyStarter(s) {
    this.spec = s.drawn ? { mode: 'drawn', shape: s.make() } : Object.assign({ mode: 'harmonic' }, s.make());
    this.send(true);
  }
  clear() {
    this.spec = this.spec.mode === 'drawn' ? { mode: 'drawn', shape: new Array(WAVE_DRAW_POINTS).fill(0) } : { mode: 'harmonic', levels: [1], phases: [0] };
    this.send(true);
  }
  random() {
    if (this.spec.mode === 'drawn') {
      // a few random harmonics drawn out, so it is a usable wave rather than noise
      const r = this.randomPartials(12);
      this.spec = { mode: 'drawn', shape: harmonicToShape(r.levels, r.phases, WAVE_DRAW_POINTS) };
    } else this.spec = Object.assign({ mode: 'harmonic' }, this.randomPartials(WAVE_PARTIALS));
    this.send(true);
  }
  randomPartials(n) {
    const levels = [], phases = [];
    for (let h = 0; h < n; h++) {
      levels.push(Math.random() < 0.55 || h === 0 ? Math.round(Math.random() / (1 + h * 0.5) * 10000) / 10000 : 0);
      phases.push(Math.round(Math.random() * 10000) / 10000);
    }
    levels[0] = Math.max(levels[0], 0.5);
    const peak = Math.max(...levels);
    return { levels: levels.map(v => Math.round(v / peak * 10000) / 10000), phases };
  }
  normalize() {
    if (this.spec.mode === 'drawn') {
      const peak = Math.max(1e-9, ...this.spec.shape.map(Math.abs));
      this.spec.shape = this.spec.shape.map(v => Math.round(v / peak * 10000) / 10000);
    } else {
      const peak = Math.max(1e-9, ...this.spec.levels);
      this.spec.levels = this.spec.levels.map(v => Math.round(v / peak * 10000) / 10000);
    }
    this.send(true);
  }

  bindBars(svg, which) {
    const barAt = (e) => {
      const r = svg.getBoundingClientRect();
      const h = clamp(Math.floor((e.clientX - r.left) / r.width * WAVE_PARTIALS), 0, WAVE_PARTIALS - 1);
      const y = (e.clientY - r.top) / r.height;
      const v = which === 'levels' ? clamp(1 - y, 0, 1) : clamp(0.5 - y, -0.5, 0.5);
      return { h, v };
    };
    svg.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      svg.setPointerCapture(e.pointerId);
      if (this.spec.mode !== 'harmonic') return;
      const p = barAt(e);
      this.drag = { which, last: p, fine: e.shiftKey };
      this.paint(which, p.h, p.v);
    });
    svg.addEventListener('pointermove', (e) => {
      if (!this.drag || this.drag.which !== which) return;
      const p = barAt(e);
      const a = this.drag.last, lo = Math.min(a.h, p.h), hi = Math.max(a.h, p.h);
      for (let h = lo; h <= hi; h++) this.paint(which, h, hi === lo ? p.v : a.v + (p.v - a.v) * (h - a.h) / (p.h - a.h), true);
      this.drag.last = p;
      this.render();
      this.send(false);
    });
    const end = () => { if (!this.drag) return; this.drag = null; this.send(true); };
    svg.addEventListener('pointerup', end);
    svg.addEventListener('pointercancel', end);
    svg.addEventListener('dblclick', (e) => {
      if (this.spec.mode !== 'harmonic') return;
      const p = barAt(e);
      this.paint(which, p.h, which === 'levels' ? (p.h === 0 ? 1 : 0) : 0);
      this.send(true);
    });
  }

  paint(which, h, v, silent) {
    const s = this.spec;
    s.levels = this.pad(s.levels || []);
    s.phases = this.pad(s.phases || []);
    if (which === 'levels') s.levels[h] = Math.round(v * 10000) / 10000;
    else s.phases[h] = Math.round((((v + 1) % 1) + 1) % 1 * 10000) / 10000;   // bar -0.5..0.5 -> turns 0..1
    this.readout.textContent = which === 'levels' ? `partial ${h + 1}: ${Math.round(s.levels[h] * 100)}%` : `partial ${h + 1}: phase ${Math.round(((s.phases[h] + 0.5) % 1 - 0.5) * 360)}°`;
    if (!silent) { this.render(); this.send(false); }
  }

  // sends go to the host at most 30 times a second while painting; the last state always goes out
  send(final) {
    const now = performance.now();
    const doSend = () => {
      this.lastSend = performance.now();
      this.pendingSend = null;
      const spec = this.spec.mode === 'drawn' ? { mode: 'drawn', shape: this.spec.shape.slice() }
                 : { mode: 'harmonic', levels: this.trim(this.spec.levels), phases: this.trim(this.spec.phases, this.trim(this.spec.levels).length) };
      this.host.setWave(this.k, spec);
      if ((this.host.values[opParamId(this.k, 'Wave')] | 0) !== 6) this.host.setParam(opParamId(this.k, 'Wave'), 6);
      this.render();
    };
    if (final || now - this.lastSend > 33) { clearTimeout(this.pendingSend); doSend(); }
    else if (!this.pendingSend) this.pendingSend = setTimeout(doSend, 34);
  }
  flushSend() { if (this.pendingSend) { clearTimeout(this.pendingSend); this.pendingSend = null; this.send(true); } }
  trim(arr, min) {
    let n = (arr || []).length;
    while (n > 1 && !(arr[n - 1])) n--;
    n = Math.max(n, min || 1);
    return (arr || []).slice(0, n).map(v => v || 0);
  }

  // ---- drawing --------------------------------------------------------------------------
  render() {
    const s = this.spec;
    const harmonic = s.mode !== 'drawn';
    this.el.querySelector('.wave-body.harmonic').style.display = harmonic ? '' : 'none';
    this.el.querySelector('.wave-body.drawn').style.display = harmonic ? 'none' : '';
    this.el.querySelectorAll('.wave-mode button').forEach(b => b.classList.toggle('on', b.dataset.mode === s.mode));
    if (harmonic) {
      const levels = this.pad(s.levels || []), phases = this.pad(s.phases || []);
      let lb = '', pb = '';
      for (let h = 0; h < WAVE_PARTIALS; h++) {
        const x = h * 16 + 1.5;
        const lh = levels[h] * 156;
        lb += `<rect class="hb-level${levels[h] ? '' : ' zero'}" data-h="${h}" x="${x}" y="${(158 - lh).toFixed(1)}" width="13" height="${Math.max(lh, 1.5).toFixed(1)}"/>`;
        const p = ((phases[h] + 0.5) % 1) - 0.5;   // -0.5..0.5
        const ph = Math.abs(p) * 66;
        pb += `<rect class="hb-phase${Math.abs(p) > 1e-6 ? '' : ' zero'}" data-h="${h}" x="${x}" y="${(p > 0 ? 35 - ph : 35).toFixed(1)}" width="13" height="${Math.max(ph, 1.5).toFixed(1)}"/>`;
      }
      this.levelsSvg.innerHTML = `<line class="hb-axis" x1="0" x2="${WAVE_PARTIALS * 16}" y1="158" y2="158"/>` + lb;
      this.phasesSvg.innerHTML = `<line class="hb-axis" x1="0" x2="${WAVE_PARTIALS * 16}" y1="35" y2="35"/>` + pb;
    } else this.shape.setPoints(s.shape);
    // preview: one cycle
    const pts = harmonic ? harmonicToShape(this.pad(s.levels || []), this.pad(s.phases || []), 200) : s.shape;
    let d = '';
    const N = pts.length;
    for (let i = 0; i <= N; i++) d += `${i ? 'L' : 'M'}${(i / N * 400).toFixed(1)} ${(30 - (pts[i % N] || 0) * 27).toFixed(1)}`;
    this.preview.setAttribute('d', d);
  }
}
