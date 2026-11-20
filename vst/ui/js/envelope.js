// ============================================================================
//  EnvEditor: the freeform multi-point envelope editor (ARTICULATORS page).
//    env = { points: [[time, level, tension]...], sustain, loopStart, loopEnd, sync }
//    - drag a point: time (x) and level (y); Shift or Ctrl = fine; the first point stays at t = 0
//    - drag a segment up / down: its tension (the curve of the segment that leads to the next point)
//    - double-click on the curve: add a point there; double-click a point: delete it
//    - click a point: select it (the toolbar's SUSTAIN / LOOP buttons act on the selection)
//    - right-click: a menu for the same (set sustain / loop here, delete)
//    - the host sends onChange(env) on every edit (the plugin stores it in the model)
//  ShapeEditor: a draw-by-dragging editor for a fixed number of -1..1 points
//    (the LFO "Drawn" wave; milestone 4 reuses it for the operator shapes).
//  The curve maths mirror dsp/Envelope.h exactly.
// ============================================================================
'use strict';

function envCurve(u, tension) {
  u = clamp(u, 0, 1);
  if (tension > 1e-6) return Math.pow(u, 1 + 4 * tension);
  if (tension < -1e-6) return 1 - Math.pow(1 - u, 1 - 4 * tension);
  return u;
}

function envEval(points, t) {
  const n = points.length;
  if (!n) return 0;
  if (n === 1 || t <= points[0][0]) return points[0][1];
  if (t >= points[n - 1][0]) return points[n - 1][1];
  let i = 0;
  while (i < n - 2 && t >= points[i + 1][0]) i++;
  const a = points[i], b = points[i + 1];
  const len = b[0] - a[0];
  const u = len > 1e-9 ? (t - a[0]) / len : 1;
  return a[1] + (b[1] - a[1]) * envCurve(u, b[2] || 0);
}

function cloneEnv(e) {
  return { points: e.points.map(p => [p[0], p[1], p[2] || 0]), sustain: e.sustain, loopStart: e.loopStart, loopEnd: e.loopEnd, sync: !!e.sync };
}

const ENV_PRESETS = [
  { name: 'ADSR', make: () => ({ points: [[0, 0, 0], [0.005, 1, 0], [0.305, 0.8, -0.5], [0.605, 0, -0.5]], sustain: 2, loopStart: -1, loopEnd: -1, sync: false }) },
  { name: 'Pluck', make: () => ({ points: [[0, 0, 0], [0.003, 1, 0], [1.2, 0, -0.6]], sustain: -1, loopStart: -1, loopEnd: -1, sync: false }) },
  { name: 'Swell', make: () => ({ points: [[0, 0, 0], [1.5, 1, 0.3], [2.5, 0.8, -0.2], [4, 0, -0.4]], sustain: 2, loopStart: -1, loopEnd: -1, sync: false }) },
  { name: 'Gate (loop)', make: () => ({ points: [[0, 0, 0], [0.01, 1, 0], [0.24, 1, 0], [0.25, 0, 0], [0.5, 0, 0], [0.6, 0, -0.5]], sustain: -1, loopStart: 1, loopEnd: 4, sync: false }) },
  { name: 'Flat (neutral)', make: () => ({ points: [[0, 0.5, 0], [1, 0.5, 0]], sustain: 1, loopStart: -1, loopEnd: -1, sync: false }) },
  { name: 'Flat (full)', make: () => ({ points: [[0, 1, 0], [1, 1, 0]], sustain: 1, loopStart: -1, loopEnd: -1, sync: false }) },
  { name: 'Fall', make: () => ({ points: [[0, 1, 0], [0.4, 0, -0.5], [1, 0, 0]], sustain: 2, loopStart: -1, loopEnd: -1, sync: false }) },
  { name: 'Rise', make: () => ({ points: [[0, 0, 0], [0.4, 1, 0.3], [1, 1, 0]], sustain: 2, loopStart: -1, loopEnd: -1, sync: false }) },
];

class EnvEditor {
  // opts: { width, height, onChange(env), onSelect(index), menu: ContextMenu, labelFor(level) -> string }
  constructor(opts) {
    this.W = opts.width || 720;
    this.H = opts.height || 220;
    this.onChange = opts.onChange || (() => {});
    this.onSelect = opts.onSelect || (() => {});
    this.menu = opts.menu || null;
    this.labelFor = opts.labelFor || ((l) => `${Math.round(l * 100)}%`);
    this.env = ENV_PRESETS[0].make();
    this.selected = -1;
    this.drag = null;
    this.tMax = 1;
    const PAD = { l: 34, r: 12, t: 10, b: 20 };
    this.PAD = PAD;
    const el = document.createElement('div');
    el.className = 'env-editor';
    el.innerHTML = `
      <svg class="env-svg" viewBox="0 0 ${this.W} ${this.H}" tabindex="0" aria-label="Envelope editor">
        <rect class="env-bg" x="${PAD.l}" y="${PAD.t}" width="${this.W - PAD.l - PAD.r}" height="${this.H - PAD.t - PAD.b}" rx="4"/>
        <rect class="env-loop" x="0" y="${PAD.t}" width="0" height="${this.H - PAD.t - PAD.b}"/>
        <g class="env-grid"></g>
        <path class="env-fill" d=""/>
        <path class="env-line" d=""/>
        <line class="env-sustain" x1="0" x2="0" y1="${PAD.t}" y2="${this.H - PAD.b}"/>
        <g class="env-points"></g>
        <text class="env-readout" x="${this.W - PAD.r - 4}" y="${PAD.t + 12}"></text>
      </svg>`;
    this.el = el;
    this.svg = el.querySelector('svg');
    this.grid = el.querySelector('.env-grid');
    this.fill = el.querySelector('.env-fill');
    this.line = el.querySelector('.env-line');
    this.loopRect = el.querySelector('.env-loop');
    this.susLine = el.querySelector('.env-sustain');
    this.pointsG = el.querySelector('.env-points');
    this.readout = el.querySelector('.env-readout');
    this.bind();
    this.render();
  }

  // ---- coordinates --------------------------------------------------------
  get plotW() { return this.W - this.PAD.l - this.PAD.r; }
  get plotH() { return this.H - this.PAD.t - this.PAD.b; }
  xOf(t) { return this.PAD.l + (t / this.tMax) * this.plotW; }
  yOf(l) { return this.PAD.t + (1 - l) * this.plotH; }
  tOf(x) { return clamp((x - this.PAD.l) / this.plotW, 0, 1) * this.tMax; }
  lOf(y) { return clamp(1 - (y - this.PAD.t) / this.plotH, 0, 1); }
  // client -> SVG user units
  pt(e) {
    const r = this.svg.getBoundingClientRect();
    return { x: (e.clientX - r.left) * this.W / r.width, y: (e.clientY - r.top) * this.H / r.height };
  }

  setEnv(env) {
    if (this.drag) return;
    this.env = cloneEnv(env);
    if (this.selected >= this.env.points.length) this.selected = -1;
    this.render();
  }

  changed() {
    this.render();
    this.onChange(cloneEnv(this.env));
  }

  fitTime() {
    const end = this.env.points.length ? this.env.points[this.env.points.length - 1][0] : 1;
    const want = Math.max(this.env.sync ? 1 : 0.25, end * 1.15);
    // only grow / shrink in steps so the view doesn't jitter while dragging
    if (!this.drag || want > this.tMax) {
      const steps = this.env.sync ? [1, 2, 4, 8, 16, 32, 64] : [0.25, 0.5, 1, 2, 3, 5, 8, 12, 20, 30, 60];
      this.tMax = steps.find(s => s >= want) || want;
    }
  }

  render() {
    const e = this.env;
    this.fitTime();
    // grid: time ticks and 4 level lines
    let g = '';
    const unit = e.sync ? 'b' : 's';
    const nTicks = this.tMax <= 1 ? 4 : this.tMax <= 8 ? this.tMax : 8;
    for (let i = 0; i <= nTicks; i++) {
      const t = this.tMax * i / nTicks, x = this.xOf(t);
      g += `<line x1="${x.toFixed(1)}" x2="${x.toFixed(1)}" y1="${this.PAD.t}" y2="${this.H - this.PAD.b}"/>`;
      g += `<text x="${x.toFixed(1)}" y="${this.H - 6}" text-anchor="${i === nTicks ? 'end' : 'middle'}">${e.sync ? (Math.round(t * 100) / 100) + (i === nTicks ? ' beats' : '') : (t < 1 ? Math.round(t * 1000) + 'ms' : (Math.round(t * 100) / 100) + unit)}</text>`;
    }
    for (let i = 0; i <= 4; i++) {
      const y = this.yOf(i / 4);
      g += `<line x1="${this.PAD.l}" x2="${this.W - this.PAD.r}" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}"/>`;
      g += `<text x="${this.PAD.l - 4}" y="${(y + 3).toFixed(1)}" text-anchor="end">${this.labelFor(i / 4)}</text>`;
    }
    this.grid.innerHTML = g;
    // curve
    const pts = e.points;
    const N = 240;
    let d = '';
    const end = pts.length ? pts[pts.length - 1][0] : 0;
    for (let i = 0; i <= N; i++) {
      const t = this.tMax * i / N;
      const l = t <= end ? envEval(pts, t) : pts[pts.length - 1][1];
      d += `${i ? 'L' : 'M'}${this.xOf(t).toFixed(1)} ${this.yOf(l).toFixed(1)}`;
    }
    this.line.setAttribute('d', d);
    this.fill.setAttribute('d', d + `L${this.W - this.PAD.r} ${this.H - this.PAD.b} L${this.PAD.l} ${this.H - this.PAD.b} Z`);
    // loop + sustain
    if (e.loopStart >= 0 && e.loopEnd > e.loopStart && e.loopEnd < pts.length) {
      const x0 = this.xOf(pts[e.loopStart][0]), x1 = this.xOf(pts[e.loopEnd][0]);
      this.loopRect.setAttribute('x', x0.toFixed(1)); this.loopRect.setAttribute('width', Math.max(0, x1 - x0).toFixed(1));
      this.loopRect.style.display = '';
    } else this.loopRect.style.display = 'none';
    if (e.sustain >= 0 && e.sustain < pts.length) {
      const x = this.xOf(pts[e.sustain][0]).toFixed(1);
      this.susLine.setAttribute('x1', x); this.susLine.setAttribute('x2', x);
      this.susLine.style.display = '';
    } else this.susLine.style.display = 'none';
    // points + tension handles
    let ph = '';
    for (let i = 0; i < pts.length; i++) {
      const [t, l] = pts[i];
      const cls = ['env-pt', i === this.selected ? 'sel' : '', i === e.sustain ? 'sus' : '', (i === e.loopStart || i === e.loopEnd) ? 'loop' : ''].join(' ');
      ph += `<circle class="${cls}" data-i="${i}" cx="${this.xOf(t).toFixed(1)}" cy="${this.yOf(l).toFixed(1)}" r="5"/>`;
      if (i > 0) {
        const a = pts[i - 1];
        const tm = (a[0] + t) / 2, lm = a[1] + (l - a[1]) * envCurve(0.5, pts[i][2] || 0);
        ph += `<rect class="env-th" data-seg="${i}" x="${(this.xOf(tm) - 3).toFixed(1)}" y="${(this.yOf(lm) - 3).toFixed(1)}" width="6" height="6" rx="1"/>`;
      }
    }
    this.pointsG.innerHTML = ph;
    const sel = this.selected >= 0 && this.selected < pts.length ? pts[this.selected] : null;
    this.readout.textContent = sel ? `pt ${this.selected + 1}  ${this.fmtTime(sel[0])}  ${this.labelFor(sel[1])}  ${sel[2] ? `tension ${sel[2] > 0 ? '+' : ''}${Math.round(sel[2] * 100)}%` : ''}` : '';
  }

  fmtTime(t) { return this.env.sync ? `${Math.round(t * 1000) / 1000} beats` : (t < 1 ? `${Math.round(t * 1000)} ms` : `${Math.round(t * 1000) / 1000} s`); }

  // ---- editing ----------------------------------------------------------------
  select(i) { this.selected = i; this.render(); this.onSelect(i); }

  addPointAt(t, l) {
    const pts = this.env.points;
    let i = pts.findIndex(p => p[0] > t);
    if (i < 0) i = pts.length;
    if (pts.length >= 32) return;
    pts.splice(i, 0, [t, l, 0]);
    // keep the sustain / loop markers on the same points
    const fix = (k) => (k >= i ? k + 1 : k);
    if (this.env.sustain >= 0) this.env.sustain = fix(this.env.sustain);
    if (this.env.loopStart >= 0) this.env.loopStart = fix(this.env.loopStart);
    if (this.env.loopEnd >= 0) this.env.loopEnd = fix(this.env.loopEnd);
    this.selected = i;
    this.changed();
  }

  deletePoint(i) {
    const e = this.env;
    if (e.points.length <= 2 || i < 0 || i >= e.points.length) return;
    e.points.splice(i, 1);
    const fix = (k) => (k === i ? -1 : k > i ? k - 1 : k);
    e.sustain = fix(e.sustain);
    e.loopStart = fix(e.loopStart);
    e.loopEnd = fix(e.loopEnd);
    if (e.loopEnd <= e.loopStart) e.loopStart = e.loopEnd = -1;
    if (i === 0) e.points[0][0] = 0;
    this.selected = -1;
    this.changed();
  }

  setSustain(i) { this.env.sustain = this.env.sustain === i ? -1 : i; this.changed(); }
  setLoopStart(i) {
    const e = this.env;
    e.loopStart = i;
    if (e.loopEnd <= i) e.loopEnd = Math.min(e.points.length - 1, i + 1);
    if (e.loopEnd <= e.loopStart) e.loopStart = e.loopEnd = -1;
    this.changed();
  }
  setLoopEnd(i) {
    const e = this.env;
    e.loopEnd = i;
    if (e.loopStart < 0 || e.loopStart >= i) e.loopStart = Math.max(0, i - 1);
    if (e.loopEnd <= e.loopStart) e.loopStart = e.loopEnd = -1;
    this.changed();
  }
  clearLoop() { this.env.loopStart = this.env.loopEnd = -1; this.changed(); }
  setSync(on) {
    // keep the shape: seconds -> beats at 120 BPM and back
    const f = on ? 2 : 0.5;
    if (!!this.env.sync === !!on) return;
    this.env.sync = !!on;
    for (const p of this.env.points) p[0] = Math.round(p[0] * f * 10000) / 10000;
    this.tMax = 1;
    this.changed();
  }
  applyPreset(name) {
    const p = ENV_PRESETS.find(x => x.name === name);
    if (!p) return;
    const sync = this.env.sync;
    this.env = p.make();
    if (sync) { this.env.sync = true; for (const q of this.env.points) q[0] *= 2; }
    this.selected = -1;
    this.changed();
  }

  bind() {
    const svg = this.svg;
    svg.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      svg.setPointerCapture(e.pointerId);
      svg.focus();
      const t = e.target;
      const p = this.pt(e);
      if (t.classList && t.classList.contains('env-pt')) {
        const i = Number(t.dataset.i);
        this.drag = { kind: 'pt', i, x: p.x, y: p.y, t0: this.env.points[i][0], l0: this.env.points[i][1] };
        this.select(i);
      } else if (t.classList && t.classList.contains('env-th')) {
        const i = Number(t.dataset.seg);
        this.drag = { kind: 'tension', i, y: p.y, v0: this.env.points[i][2] || 0 };
      } else {
        // on the curve body: drag the tension of the segment under the pointer
        const tt = this.tOf(p.x);
        const pts = this.env.points;
        let i = pts.findIndex(q => q[0] > tt);
        if (i > 0 && i < pts.length && Math.abs(this.yOf(envEval(pts, tt)) - p.y) < 14) this.drag = { kind: 'tension', i, y: p.y, v0: pts[i][2] || 0 };
        else this.select(-1);
      }
    });
    svg.addEventListener('pointermove', (e) => {
      const d = this.drag;
      if (!d) return;
      const p = this.pt(e);
      const fine = e.shiftKey || e.ctrlKey ? 0.2 : 1;
      const pts = this.env.points;
      if (d.kind === 'pt') {
        const q = pts[d.i];
        let t = d.t0 + (p.x - d.x) * fine * this.tMax / this.plotW;
        const lo = d.i === 0 ? 0 : pts[d.i - 1][0], hi = d.i + 1 < pts.length ? pts[d.i + 1][0] : Infinity;
        t = d.i === 0 ? 0 : clamp(t, lo, hi);
        q[0] = Math.round(t * 10000) / 10000;
        q[1] = Math.round(clamp(d.l0 + (d.y - p.y) * fine / this.plotH, 0, 1) * 10000) / 10000;
        this.changed();
      } else if (d.kind === 'tension') {
        const a = pts[d.i - 1], b = pts[d.i];
        const dir = b[1] >= a[1] ? -1 : 1;   // dragging towards the "slow start" side of the curve
        pts[d.i][2] = Math.round(clamp(d.v0 + dir * (d.y - p.y) * fine / 60, -1, 1) * 1000) / 1000;
        this.changed();
      }
    });
    const end = () => { if (!this.drag) return; this.drag = null; this.render(); };
    svg.addEventListener('pointerup', end);
    svg.addEventListener('pointercancel', end);
    svg.addEventListener('dblclick', (e) => {
      const t = e.target;
      if (t.classList && t.classList.contains('env-pt')) { this.deletePoint(Number(t.dataset.i)); return; }
      if (t.classList && t.classList.contains('env-th')) { this.env.points[Number(t.dataset.seg)][2] = 0; this.changed(); return; }
      const p = this.pt(e);
      this.addPointAt(Math.round(this.tOf(p.x) * 10000) / 10000, Math.round(this.lOf(p.y) * 10000) / 10000);
    });
    svg.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (!this.menu) return;
      const t = e.target;
      const items = [];
      if (t.classList && t.classList.contains('env-pt')) {
        const i = Number(t.dataset.i);
        this.select(i);
        items.push({ label: this.env.sustain === i ? 'Clear sustain' : 'Sustain here', onPick: () => this.setSustain(i) });
        items.push({ label: 'Loop start here', onPick: () => this.setLoopStart(i) });
        items.push({ label: 'Loop end here', onPick: () => this.setLoopEnd(i) });
        if (this.env.loopStart >= 0) items.push({ label: 'Clear loop', onPick: () => this.clearLoop() });
        items.push({ label: 'Delete point', onPick: () => this.deletePoint(i), disabled: this.env.points.length <= 2 });
        this.menu.show(e.clientX, e.clientY, `Point ${i + 1}`, items);
      } else {
        const p = this.pt(e);
        const tt = this.tOf(p.x), ll = this.lOf(p.y);
        items.push({ label: 'Add point here', onPick: () => this.addPointAt(tt, ll) });
        if (this.env.loopStart >= 0) items.push({ label: 'Clear loop', onPick: () => this.clearLoop() });
        this.menu.show(e.clientX, e.clientY, 'Envelope', items);
      }
    });
    svg.addEventListener('keydown', (e) => {
      if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); e.stopPropagation(); this.deletePoint(this.selected); }
      else if (e.key === 'Escape') this.select(-1);
    });
  }
}

// Draw-by-dragging editor for N points in -1..1 (one cycle). onChange(array)
class ShapeEditor {
  constructor(points, opts) {
    this.pts = Float32Array.from(points);
    this.N = this.pts.length;
    this.W = (opts && opts.width) || 160;
    this.H = (opts && opts.height) || 50;
    this.onChange = (opts && opts.onChange) || (() => {});
    this.readOnly = !!(opts && opts.readOnly);
    this.drag = null;
    const el = document.createElement('div');
    el.className = 'shape-editor screen';
    el.innerHTML = `<svg viewBox="0 0 ${this.W} ${this.H}" preserveAspectRatio="none" tabindex="0" aria-label="Shape">
        <path class="scr-grid" d="M0 ${this.H / 2} H${this.W}"/><path class="scr-line" d=""/><circle class="shape-dot" r="2.5" cx="-10" cy="0"/></svg>`;
    this.el = el;
    this.svg = el.querySelector('svg');
    this.path = el.querySelector('.scr-line');
    this.dot = el.querySelector('.shape-dot');
    this.bind();
    this.render();
  }
  setPoints(points) { if (this.drag) return; this.pts = Float32Array.from(points); this.N = this.pts.length; this.render(); }
  setReadOnly(ro) { this.readOnly = ro; this.el.classList.toggle('ro', ro); }
  // a moving marker (the LFO's phase / value), x and y in 0..1 / -1..1
  marker(phase, value) {
    if (phase === null) { this.dot.setAttribute('cx', -10); return; }
    this.dot.setAttribute('cx', (phase * this.W).toFixed(1));
    this.dot.setAttribute('cy', (this.H / 2 - value * (this.H / 2 - 3)).toFixed(1));
  }
  render() {
    const pad = 3;
    let d = '';
    for (let i = 0; i <= this.N; i++) d += `${i ? 'L' : 'M'}${(i / this.N * this.W).toFixed(1)} ${(this.H / 2 - this.pts[i % this.N] * (this.H / 2 - pad)).toFixed(1)}`;
    this.path.setAttribute('d', d);
  }
  pt(e) {
    const r = this.svg.getBoundingClientRect();
    return { i: clamp(Math.floor((e.clientX - r.left) / r.width * this.N), 0, this.N - 1), v: clamp(1 - ((e.clientY - r.top) / r.height) * 2, -1, 1) };
  }
  bind() {
    const svg = this.svg;
    svg.addEventListener('pointerdown', (e) => {
      if (e.button !== 0 || this.readOnly) return;
      e.preventDefault();
      svg.setPointerCapture(e.pointerId);
      const p = this.pt(e);
      this.drag = p;
      this.pts[p.i] = p.v;
      this.render();
    });
    svg.addEventListener('pointermove', (e) => {
      if (!this.drag) return;
      const p = this.pt(e);
      // fill every point between the last position and this one
      const a = this.drag, lo = Math.min(a.i, p.i), hi = Math.max(a.i, p.i);
      for (let i = lo; i <= hi; i++) this.pts[i] = hi === lo ? p.v : a.v + (p.v - a.v) * (i - a.i) / (p.i - a.i);
      this.drag = p;
      this.render();
    });
    const end = () => { if (!this.drag) return; this.drag = null; this.onChange(Array.from(this.pts, v => Math.round(v * 1000) / 1000)); };
    svg.addEventListener('pointerup', end);
    svg.addEventListener('pointercancel', end);
  }
}
