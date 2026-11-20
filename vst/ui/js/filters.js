// ============================================================================
//  The FILTERS page: three panels (on, type, slope, a response screen, the
//  knobs, buttons to the two envelopes) and the routing panel with a diagram.
//  The response curve is the 2-pole SVF's analogue prototype at the current
//  cutoff / resonance (squared for 24 dB); the same k mapping as dsp/Common.h.
// ============================================================================
'use strict';

class FiltersPage {
  // host: { values, addKnob(parent, id, opts), control(Cls, id, ...), openEnv(key), fmt(id) }
  constructor(container, host) {
    this.host = host;
    this.container = container;
    this.flt = [];
    this.build();
  }

  build() {
    const row = document.createElement('div');
    row.className = 'flt-row';
    for (let f = 0; f < NUM_FILTERS; f++) row.appendChild(this.filterPanel(f));
    this.container.appendChild(row);

    const route = document.createElement('div');
    route.className = 'panel flt-route';
    route.innerHTML = `<div class="panel-head"><span class="panel-title">ROUTING</span>
        <span class="mx-hint">operators reach the filters through the output column on the MATRIX page</span></div>`;
    const body = document.createElement('div');
    body.className = 'flt-route-body';
    body.appendChild(this.host.control(Segmented, 'fltRouting', ['PARALLEL', 'SERIES 1 › 2 › 3', '1 + 2 › 3']).el);
    this.diagram = document.createElement('div');
    this.diagram.className = 'flt-diagram';
    body.appendChild(this.diagram);
    this.feeds = document.createElement('div');
    this.feeds.className = 'flt-feeds';
    body.appendChild(this.feeds);
    route.appendChild(body);
    this.container.appendChild(route);
  }

  filterPanel(f) {
    const h = this.host;
    const id = (field) => `flt${f + 1}${field}`;
    const panel = document.createElement('div');
    panel.className = 'panel flt-panel';
    panel.dataset.flt = f;
    const head = document.createElement('div');
    head.className = 'panel-head';
    head.innerHTML = `<span class="panel-title">FILTER ${f + 1}</span>`;
    head.appendChild(h.control(ToggleButton, id('On'), 'ON').el);
    panel.appendChild(head);

    const top = document.createElement('div');
    top.className = 'flt-top';
    top.appendChild(h.control(Segmented, id('Type'), ['LP', 'BP', 'HP']).el);
    top.appendChild(h.control(Segmented, id('Slope'), ['12', '24']).el);
    panel.appendChild(top);

    const W = 360, H = 76;
    const scr = document.createElement('div');
    scr.className = 'screen flt-screen';
    scr.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
        <g class="flt-grid"></g><path class="flt-fill" d=""/><path class="scr-line" d=""/><line class="flt-cut" y1="0" y2="${H}"/></svg>
      <div class="scr-text"></div>`;
    panel.appendChild(scr);

    const knobs = document.createElement('div');
    knobs.className = 'knob-row flt-knobs';
    h.addKnob(knobs, id('Cutoff'), { size: 'md', label: 'CUTOFF' });
    h.addKnob(knobs, id('Reso'), { size: 'md', label: 'RESO' });
    h.addKnob(knobs, id('Drive'), { size: 'md', label: 'DRIVE' });
    h.addKnob(knobs, id('KeyTrack'), { size: 'md', label: 'KEY' });
    h.addKnob(knobs, id('EnvAmt'), { size: 'md', label: 'ENV' });
    h.addKnob(knobs, id('Vel'), { size: 'md', label: 'VEL' });
    h.addKnob(knobs, id('Mix'), { size: 'md', label: 'MIX' });
    panel.appendChild(knobs);

    const btns = document.createElement('div');
    btns.className = 'flt-env-btns';
    const b1 = document.createElement('button');
    b1.type = 'button'; b1.className = 'pd-btn'; b1.textContent = 'CUTOFF ENV ›';
    b1.dataset.tip = `Edit filter ${f + 1}'s cutoff envelope (ENV sets how far it opens: ±5 octaves)`;
    b1.addEventListener('click', () => h.openEnv(`flt${f + 1}Cutoff`));
    const b2 = document.createElement('button');
    b2.type = 'button'; b2.className = 'pd-btn'; b2.textContent = 'LEVEL ENV ›';
    b2.dataset.tip = `Edit filter ${f + 1}'s output level envelope`;
    b2.addEventListener('click', () => h.openEnv(`flt${f + 1}Level`));
    btns.append(b1, b2);
    panel.appendChild(btns);

    this.flt.push({ f, panel, W, H, grid: scr.querySelector('.flt-grid'), fill: scr.querySelector('.flt-fill'),
                    line: scr.querySelector('.scr-line'), cut: scr.querySelector('.flt-cut'), text: scr.querySelector('.scr-text') });
    return panel;
  }

  // |H(jw)| of the analogue 2-pole prototype, per output
  static response(type, k, s) {
    const re = 1 - s * s, im = k * s;           // s^2 + k s + 1 at s = j s
    const den = Math.sqrt(re * re + im * im);
    if (type === 0) return 1 / den;
    if (type === 1) return s / den;
    return (s * s) / den;
  }

  refresh(ids) {
    const v = this.host.values;
    if (!ids || [...ids].some(id => /^flt|^out\d|^fltRouting/.test(id))) {
      for (const u of this.flt) this.drawResponse(u);
      this.drawRouting();
    }
  }

  drawResponse(u) {
    const v = this.host.values, f = u.f;
    const id = (field) => `flt${f + 1}${field}`;
    const type = v[id('Type')] | 0, k = 2 - 1.9 * clamp(v[id('Reso')], 0, 1), two = v[id('Slope')] >= 0.5;
    const fc = v[id('Cutoff')], on = v[id('On')] >= 0.5, mix = v[id('Mix')];
    const W = u.W, H = u.H;
    const fLo = 20, fHi = 20000, dbLo = -48, dbHi = 24;
    const xOf = (hz) => Math.log(hz / fLo) / Math.log(fHi / fLo) * W;
    const yOf = (db) => (dbHi - clamp(db, dbLo, dbHi)) / (dbHi - dbLo) * H;
    let g = '';
    for (const hz of [50, 100, 200, 500, 1000, 2000, 5000, 10000]) g += `<line x1="${xOf(hz).toFixed(1)}" x2="${xOf(hz).toFixed(1)}" y1="0" y2="${H}"/>`;
    for (const db of [-36, -24, -12, 0, 12]) g += `<line class="${db === 0 ? 'zero' : ''}" x1="0" x2="${W}" y1="${yOf(db).toFixed(1)}" y2="${yOf(db).toFixed(1)}"/>`;
    u.grid.innerHTML = g;
    let d = '';
    const N = 120;
    for (let i = 0; i <= N; i++) {
      const hz = fLo * Math.pow(fHi / fLo, i / N);
      let m = FiltersPage.response(type, k, hz / fc);
      if (two) m *= m;
      // what leaves the filter: mix between dry (1) and wet; off = flat
      const out = on ? Math.abs((1 - mix) + mix * m) : 1;
      d += `${i ? 'L' : 'M'}${(i / N * W).toFixed(1)} ${yOf(20 * Math.log10(Math.max(out, 1e-6))).toFixed(1)}`;
    }
    u.line.setAttribute('d', d);
    u.fill.setAttribute('d', `${d} L${W} ${H} L0 ${H} Z`);
    u.cut.setAttribute('x1', xOf(fc).toFixed(1)); u.cut.setAttribute('x2', xOf(fc).toFixed(1));
    u.text.textContent = `${FLT_TYPES[type].replace('-pass', '')} ${two ? 24 : 12} dB  ${formatParam(PARAM_BY_ID[id('Cutoff')], fc)}`;
    u.panel.classList.toggle('off', !on);
  }

  drawRouting() {
    const v = this.host.values;
    const r = v.fltRouting | 0;
    const box = (x, y, t) => `<rect x="${x}" y="${y}" width="44" height="22" rx="4"/><text x="${x + 22}" y="${y + 15}">${t}</text>`;
    const arrow = (x1, y1, x2, y2) => `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" marker-end="url(#fltArrow)"/>`;
    const defs = `<defs><marker id="fltArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0 L10 5 L0 10 z"/></marker></defs>`;
    let body = '';
    if (r === 0) { // parallel
      body = box(50, 4, 'F1') + box(50, 34, 'F2') + box(50, 64, 'F3') + box(200, 34, 'OUT')
        + arrow(10, 15, 48, 15) + arrow(10, 45, 48, 45) + arrow(10, 75, 48, 75)
        + arrow(96, 15, 198, 42) + arrow(96, 45, 198, 45) + arrow(96, 75, 198, 48);
    } else if (r === 1) { // series
      body = box(40, 34, 'F1') + box(110, 34, 'F2') + box(180, 34, 'F3') + box(250, 34, 'OUT')
        + arrow(6, 45, 38, 45) + arrow(86, 45, 108, 45) + arrow(156, 45, 178, 45) + arrow(226, 45, 248, 45)
        + arrow(96, 10, 118, 32) + arrow(166, 10, 188, 32)
        + `<text class="small" x="96" y="7">op › F2</text><text class="small" x="166" y="7">op › F3</text>`;
    } else { // 1+2 > 3
      body = box(50, 10, 'F1') + box(50, 58, 'F2') + box(150, 34, 'F3') + box(250, 34, 'OUT')
        + arrow(10, 21, 48, 21) + arrow(10, 69, 48, 69) + arrow(96, 21, 148, 42) + arrow(96, 69, 148, 48)
        + arrow(196, 45, 248, 45) + arrow(120, 90, 148, 52) + `<text class="small" x="120" y="88">op › F3</text>`;
    }
    this.diagram.innerHTML = `<svg viewBox="0 0 300 92">${defs}${body}</svg>`;
    // which operators feed each filter (from the output column)
    const parts = [];
    for (let f = 0; f < NUM_FILTERS; f++) {
      const ops = [];
      for (let k = 0; k < NUM_OPS; k++) if (v[outId(k, f)] > 0) ops.push(k + 1);
      parts.push(`<span class="${ops.length ? 'fed' : ''}">F${f + 1}: ${ops.length ? 'op ' + ops.join(', ') : 'nothing'}</span>`);
    }
    this.feeds.innerHTML = parts.join('');
  }
}
