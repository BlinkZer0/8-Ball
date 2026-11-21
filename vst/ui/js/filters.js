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
    // "ops" on the left feed the filters; an extra "ops" arrow from above where a later filter has its own input
    const inLabel = (x, y) => `<text class="small" x="${x}" y="${y}">ops</text>`;
    const feed = (x, y) => arrow(x, y - 26, x, y - 2) + `<text class="small" x="${x + 4}" y="${y - 14}" text-anchor="start">ops</text>`;
    let body = '';
    if (r === 0) { // parallel
      body = box(60, 6, 'F1') + box(60, 36, 'F2') + box(60, 66, 'F3') + box(210, 36, 'OUT')
        + inLabel(18, 44) + arrow(30, 17, 58, 17) + arrow(30, 47, 58, 47) + arrow(30, 77, 58, 77)
        + arrow(106, 17, 208, 43) + arrow(106, 47, 208, 47) + arrow(106, 77, 208, 51);
    } else if (r === 1) { // series
      body = box(44, 46, 'F1') + box(114, 46, 'F2') + box(184, 46, 'F3') + box(254, 46, 'OUT')
        + inLabel(12, 60) + arrow(24, 57, 42, 57) + arrow(90, 57, 112, 57) + arrow(160, 57, 182, 57) + arrow(230, 57, 252, 57)
        + feed(136, 46) + feed(206, 46);
    } else { // 1+2 > 3
      body = box(60, 14, 'F1') + box(60, 62, 'F2') + box(170, 46, 'F3') + box(254, 46, 'OUT')
        + inLabel(18, 50) + arrow(30, 25, 58, 25) + arrow(30, 73, 58, 73)
        + arrow(106, 25, 168, 53) + arrow(106, 73, 168, 61) + arrow(216, 57, 252, 57)
        + feed(192, 46);
    }
    this.diagram.innerHTML = `<svg viewBox="0 0 300 100">${defs}${body}</svg>`;
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
