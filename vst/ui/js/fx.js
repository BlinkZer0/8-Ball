// ============================================================================
//  The FX page: the chain bar (seven chips in the order the fxOrder1-7
//  parameters give; drag a chip or a panel's handle to reorder) and one panel
//  per unit, laid out in chain order: on/off, the knobs, mix. The EQ panel
//  draws its response, the compressor shows its gain reduction.
// ============================================================================
'use strict';

const FX_LABELS = ['DISTORTION', 'CHORUS', 'PHASER', 'DELAY', 'REVERB', 'EQ', 'COMP'];
const FX_PREFIX = ['dst', 'cho', 'pha', 'dly', 'rev', 'eq', 'cmp'];

class FxPage {
  // host: { values, addKnob, control, setParams, log }
  constructor(container, host) {
    this.host = host;
    this.container = container;
    this.panels = [];
    this.chips = [];
    this.drag = null;
    this.build();
  }

  // the order resolved like the engine does it: first mention wins, missing units go last
  order() {
    const v = this.host.values, used = new Set(), out = [];
    for (let p = 1; p <= NUM_FX; p++) { const u = clamp(Math.round(v[`fxOrder${p}`]), 0, NUM_FX - 1); if (!used.has(u)) { used.add(u); out.push(u); } }
    for (let u = 0; u < NUM_FX; u++) if (!used.has(u)) out.push(u);
    return out;
  }

  setOrder(order) {
    const o = {};
    order.forEach((u, i) => { o[`fxOrder${i + 1}`] = u; });
    this.host.setParams(o);
    this.host.log(`FX order: ${order.map(u => FX_LABELS[u]).join(' › ')}`);
  }

  build() {
    const h = this.host;
    const bar = document.createElement('div');
    bar.className = 'panel fx-chainbar';
    bar.innerHTML = '<div class="panel-head"><span class="panel-title">CHAIN</span><span class="mx-hint">voices › these units in this order › master · drag a unit to move it</span></div>';
    this.chain = document.createElement('div');
    this.chain.className = 'fx-chain';
    for (let u = 0; u < NUM_FX; u++) {
      const chip = document.createElement('div');
      chip.className = 'fx-chip';
      chip.dataset.unit = u;
      chip.innerHTML = `<span class="led"></span><span class="fx-chip-name">${FX_LABELS[u]}</span>`;
      chip.dataset.tip = `${FX_LABELS[u]}: drag to move it in the chain`;
      this.bindDrag(chip, u);
      this.chips.push(chip);
    }
    bar.appendChild(this.chain);
    this.container.appendChild(bar);

    this.grid = document.createElement('div');
    this.grid.className = 'fx-grid';
    this.container.appendChild(this.grid);
    for (let u = 0; u < NUM_FX; u++) this.panels.push(this.panel(u));
    this.layout();
  }

  panel(u) {
    const h = this.host, pre = FX_PREFIX[u];
    const id = (f) => `${pre}${f}`;
    const panel = document.createElement('div');
    panel.className = `panel fx-panel fx-${pre}`;
    panel.dataset.unit = u;
    const head = document.createElement('div');
    head.className = 'panel-head';
    const handle = document.createElement('span');
    handle.className = 'fx-handle';
    handle.textContent = '⋮⋮';
    handle.dataset.tip = 'Drag to move this unit in the chain';
    this.bindDrag(handle, u);
    head.appendChild(handle);
    const title = document.createElement('span');
    title.className = 'panel-title';
    title.textContent = FX_LABELS[u];
    head.appendChild(title);
    const pos = document.createElement('span');
    pos.className = 'fx-pos';
    head.appendChild(pos);
    head.appendChild(h.control(ToggleButton, id('On'), 'ON').el);
    panel.appendChild(head);
    const body = document.createElement('div');
    body.className = 'fx-body';
    panel.appendChild(body);
    const row = (cls) => { const r = document.createElement('div'); r.className = `knob-row fx-knobs ${cls || ''}`; body.appendChild(r); return r; };
    const knob = (parent, f, label) => h.addKnob(parent, id(f), { size: 'md', label });
    const u8 = { u, panel, pos };

    switch (u) {
      case 0: {
        const top = document.createElement('div'); top.className = 'fx-top'; body.appendChild(top);
        top.appendChild(h.control(Segmented, 'dstType', ['SOFT', 'HARD', 'FOLD', 'CRUSH']).el);
        const r = row();
        knob(r, 'Drive', 'DRIVE'); knob(r, 'Tone', 'TONE'); knob(r, 'Out', 'OUT'); knob(r, 'Mix', 'MIX');
        break;
      }
      case 1: {
        const r = row();
        knob(r, 'Rate', 'RATE'); knob(r, 'Depth', 'DEPTH'); knob(r, 'Delay', 'DELAY'); knob(r, 'Feedback', 'FDBK'); knob(r, 'Spread', 'SPREAD'); knob(r, 'Mix', 'MIX');
        break;
      }
      case 2: {
        const top = document.createElement('div'); top.className = 'fx-top'; body.appendChild(top);
        top.appendChild(document.createTextNode('STAGES'));
        top.appendChild(h.control(Segmented, 'phaStages', ['4', '8', '12']).el);
        const r = row();
        knob(r, 'Rate', 'RATE'); knob(r, 'Depth', 'DEPTH'); knob(r, 'Center', 'CENTER'); knob(r, 'Feedback', 'FDBK'); knob(r, 'Mix', 'MIX');
        break;
      }
      case 3: {
        const top = document.createElement('div'); top.className = 'fx-top'; body.appendChild(top);
        top.appendChild(h.control(ToggleButton, 'dlySync', 'SYNC').el);
        const div = h.control(SelectBox, 'dlyDiv'); div.el.classList.add('fx-div'); top.appendChild(div.el);
        top.appendChild(h.control(ToggleButton, 'dlyPingPong', 'PING-PONG').el);
        const r = row();
        u8.time = knob(r, 'Time', 'TIME'); knob(r, 'Feedback', 'FDBK'); knob(r, 'Tone', 'TONE'); knob(r, 'Mix', 'MIX');
        u8.div = div.el;
        break;
      }
      case 4: {
        const r = row();
        knob(r, 'Size', 'SIZE'); knob(r, 'Decay', 'DECAY'); knob(r, 'Damp', 'DAMP'); knob(r, 'PreDelay', 'PRE-DLY'); knob(r, 'Width', 'WIDTH'); knob(r, 'Mix', 'MIX');
        break;
      }
      case 5: {
        const W = 300, H = 56;
        const scr = document.createElement('div');
        scr.className = 'screen fx-eq-screen';
        scr.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><g class="flt-grid"></g><path class="flt-fill" d=""/><path class="scr-line" d=""/></svg>`;
        body.appendChild(scr);
        u8.eq = { W, H, grid: scr.querySelector('.flt-grid'), fill: scr.querySelector('.flt-fill'), line: scr.querySelector('.scr-line') };
        const r1 = row();
        knob(r1, 'LowCut', 'LO CUT'); knob(r1, 'LowFreq', 'LOW HZ'); knob(r1, 'LowGain', 'LOW'); knob(r1, 'MidFreq', 'MID HZ'); knob(r1, 'MidGain', 'MID');
        const r2 = row();
        knob(r2, 'MidQ', 'MID Q'); knob(r2, 'HighFreq', 'HIGH HZ'); knob(r2, 'HighGain', 'HIGH'); knob(r2, 'HighCut', 'HI CUT'); knob(r2, 'Mix', 'MIX');
        break;
      }
      default: {
        const top = document.createElement('div'); top.className = 'fx-top'; body.appendChild(top);
        top.appendChild(h.control(ToggleButton, 'cmpLimit', 'LIMIT 0 dB').el);
        const meter = document.createElement('div');
        meter.className = 'fx-gr';
        meter.innerHTML = '<span class="ctl-label">GR</span><div class="fx-gr-bar"><div class="fx-gr-fill"></div></div><span class="fx-gr-val">0 dB</span>';
        meter.dataset.tip = 'Gain reduction';
        top.appendChild(meter);
        u8.grFill = meter.querySelector('.fx-gr-fill'); u8.grVal = meter.querySelector('.fx-gr-val');
        const r = row();
        knob(r, 'Thresh', 'THRESH'); knob(r, 'Ratio', 'RATIO'); knob(r, 'Attack', 'ATTACK'); knob(r, 'Release', 'RELEASE'); knob(r, 'Makeup', 'MAKEUP'); knob(r, 'Mix', 'MIX');
        break;
      }
    }
    return u8;
  }

  // ---- drag to reorder (chips and panel handles) ---------------------------------
  bindDrag(el, unit) {
    el.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      el.setPointerCapture(e.pointerId);
      this.drag = { unit, order: this.order(), moved: false };
      this.chips[unit].classList.add('dragging');
      this.panels[unit].panel.classList.add('dragging');
    });
    el.addEventListener('pointermove', (e) => {
      const d = this.drag;
      if (!d) return;
      // the chip under the pointer (chips are laid out in chain order)
      const over = this.chips.find(c => { const r = c.getBoundingClientRect(); return e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top - 40 && e.clientY <= r.bottom + 40; })
               || this.panels.map(p => p.panel).find(p => { const r = p.getBoundingClientRect(); return e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom; });
      if (!over) return;
      const target = Number(over.dataset.unit);
      if (target === d.unit) return;
      const order = d.order.filter(u => u !== d.unit);
      order.splice(order.indexOf(target) + (order.indexOf(target) >= d.order.indexOf(d.unit) ? 1 : 0), 0, d.unit);
      if (order.join() !== d.order.join()) { d.order = order; d.moved = true; this.layout(order); }
    });
    const end = () => {
      const d = this.drag;
      if (!d) return;
      this.drag = null;
      this.chips[d.unit].classList.remove('dragging');
      this.panels[d.unit].panel.classList.remove('dragging');
      if (d.moved) this.setOrder(d.order); else this.layout();
    };
    el.addEventListener('pointerup', end);
    el.addEventListener('pointercancel', end);
  }

  // DOM order = chain order
  layout(order) {
    order = order || this.order();
    for (const u of order) this.chain.appendChild(this.chips[u]);
    order.forEach((u, i) => {
      const p = this.panels[u];
      this.grid.appendChild(p.panel);
      p.pos.textContent = `#${i + 1}`;
    });
  }

  refresh(ids) {
    const v = this.host.values;
    if (!this.drag && (!ids || [...ids].some(id => /^fxOrder/.test(id)))) this.layout();
    if (!ids || [...ids].some(id => /On$/.test(id) && /^(dst|cho|pha|dly|rev|eq|cmp)/.test(id))) {
      for (let u = 0; u < NUM_FX; u++) {
        const on = v[`${FX_PREFIX[u]}On`] >= 0.5;
        this.chips[u].classList.toggle('on', on);
        this.panels[u].panel.classList.toggle('off', !on);
      }
    }
    if (!ids || [...ids].some(id => /^eq/.test(id))) this.drawEq();
    if (!ids || [...ids].some(id => /^dly(Sync)$/.test(id))) {
      const sync = v.dlySync >= 0.5;
      this.panels[3].time.el.classList.toggle('na', sync);
      this.panels[3].div.classList.toggle('na', !sync);
    }
  }

  // |H| of an RBJ biquad at frequency hz (the same formulas as dsp/Effects.h)
  static biquadMag(c, hz, sr) {
    const w = 2 * Math.PI * hz / sr, c1 = Math.cos(w), s1 = Math.sin(w), c2 = Math.cos(2 * w), s2 = Math.sin(2 * w);
    const nr = c.b0 + c.b1 * c1 + c.b2 * c2, ni = -(c.b1 * s1 + c.b2 * s2);
    const dr = 1 + c.a1 * c1 + c.a2 * c2, di = -(c.a1 * s1 + c.a2 * s2);
    return Math.sqrt((nr * nr + ni * ni) / (dr * dr + di * di));
  }
  static rbj(kind, hz, q, gainDb, sr) {
    const w = 2 * Math.PI * clamp(hz, 10, sr * 0.49) / sr, c = Math.cos(w), s = Math.sin(w);
    const norm = (b0, b1, b2, a0, a1, a2) => ({ b0: b0 / a0, b1: b1 / a0, b2: b2 / a0, a1: a1 / a0, a2: a2 / a0 });
    if (kind === 'lp') { const a = s / (2 * q); return norm((1 - c) / 2, 1 - c, (1 - c) / 2, 1 + a, -2 * c, 1 - a); }
    if (kind === 'hp') { const a = s / (2 * q); return norm((1 + c) / 2, -(1 + c), (1 + c) / 2, 1 + a, -2 * c, 1 - a); }
    const A = Math.pow(10, gainDb / 40);
    if (kind === 'peak') { const a = s / (2 * q); return norm(1 + a * A, -2 * c, 1 - a * A, 1 + a / A, -2 * c, 1 - a / A); }
    const beta = Math.sqrt(2) * Math.sqrt(A) * s * 0.5;
    if (kind === 'ls') return norm(A * ((A + 1) - (A - 1) * c + 2 * beta), 2 * A * ((A - 1) - (A + 1) * c), A * ((A + 1) - (A - 1) * c - 2 * beta),
                                   (A + 1) + (A - 1) * c + 2 * beta, -2 * ((A - 1) + (A + 1) * c), (A + 1) + (A - 1) * c - 2 * beta);
    return norm(A * ((A + 1) + (A - 1) * c + 2 * beta), -2 * A * ((A - 1) + (A + 1) * c), A * ((A + 1) + (A - 1) * c - 2 * beta),
                (A + 1) - (A - 1) * c + 2 * beta, 2 * ((A - 1) - (A + 1) * c), (A + 1) - (A - 1) * c - 2 * beta);
  }

  drawEq() {
    const v = this.host.values, e = this.panels[5].eq, sr = 48000;
    const W = e.W, H = e.H, fLo = 20, fHi = 20000, dbLo = -24, dbHi = 24;
    const xOf = (hz) => Math.log(hz / fLo) / Math.log(fHi / fLo) * W;
    const yOf = (db) => (dbHi - clamp(db, dbLo, dbHi)) / (dbHi - dbLo) * H;
    let g = '';
    for (const hz of [50, 100, 200, 500, 1000, 2000, 5000, 10000]) g += `<line x1="${xOf(hz).toFixed(1)}" x2="${xOf(hz).toFixed(1)}" y1="0" y2="${H}"/>`;
    for (const db of [-12, 0, 12]) g += `<line class="${db === 0 ? 'zero' : ''}" x1="0" x2="${W}" y1="${yOf(db).toFixed(1)}" y2="${yOf(db).toFixed(1)}"/>`;
    e.grid.innerHTML = g;
    const stages = [];
    if (v.eqLowCut > 20.5) stages.push(FxPage.rbj('hp', v.eqLowCut, 0.7071, 0, sr));
    if (v.eqHighCut < 19900) stages.push(FxPage.rbj('lp', v.eqHighCut, 0.7071, 0, sr));
    if (Math.abs(v.eqLowGain) > 0.01) stages.push(FxPage.rbj('ls', v.eqLowFreq, 1, v.eqLowGain, sr));
    if (Math.abs(v.eqMidGain) > 0.01) stages.push(FxPage.rbj('peak', v.eqMidFreq, v.eqMidQ, v.eqMidGain, sr));
    if (Math.abs(v.eqHighGain) > 0.01) stages.push(FxPage.rbj('hs', v.eqHighFreq, 1, v.eqHighGain, sr));
    const on = v.eqOn >= 0.5, mix = v.eqMix;
    let d = '';
    const N = 100;
    for (let i = 0; i <= N; i++) {
      const hz = fLo * Math.pow(fHi / fLo, i / N);
      let m = 1;
      for (const s of stages) m *= FxPage.biquadMag(s, hz, sr);
      const out = on ? Math.abs((1 - mix) + mix * m) : 1;
      d += `${i ? 'L' : 'M'}${(i / N * W).toFixed(1)} ${yOf(20 * Math.log10(Math.max(out, 1e-6))).toFixed(1)}`;
    }
    e.line.setAttribute('d', d);
    e.fill.setAttribute('d', `${d} L${W} ${yOf(0)} L0 ${yOf(0)} Z`);
  }

  // compressor gain reduction from the plugin (dB)
  meter(gr) {
    if (typeof gr !== 'number') return;
    const p = this.panels[6];
    p.grFill.style.width = `${clamp(gr / 24, 0, 1) * 100}%`;
    p.grVal.textContent = `${gr < 0.05 ? 0 : -Math.round(gr * 10) / 10} dB`;
  }
}
