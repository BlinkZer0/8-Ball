// ============================================================================
//  The matrix page: the 8x8 PM grid, the 8x8 ring-mod grid and the output
//  column, as grids of small knobs (drag up/down, Ctrl or Shift = fine,
//  double-click = reset), plus the algorithm layouts, Clear and Randomize.
//  Below the grids: the signal-flow diagram (nodes on a ring, an edge per
//  cell, carriers to the output) and eight operator scopes. With ANIMATE on,
//  cells, headers, nodes and edges glow with each operator's output and the
//  scopes show the live waveforms the plugin sends.
//
//  Layouts are plain data: { name, pm: [[src, dst, depth]...], carriers: [op...] }
//  (1-based operator numbers). Applying one clears both grids and the output
//  column, sets the cells, and routes the carriers to Dry.
// ============================================================================
'use strict';

const MATRIX_LAYOUTS = [
  { name: 'Single carrier', pm: [], carriers: [1] },
  { name: 'Stack 2 > 1', pm: [[2, 1, 0.5]], carriers: [1] },
  { name: 'Stack 3 > 2 > 1', pm: [[3, 2, 0.4], [2, 1, 0.5]], carriers: [1] },
  { name: 'Stack 4 > 3 > 2 > 1', pm: [[4, 3, 0.35], [3, 2, 0.4], [2, 1, 0.5]], carriers: [1] },
  { name: 'Fan: 2, 3, 4 > 1', pm: [[2, 1, 0.4], [3, 1, 0.35], [4, 1, 0.3]], carriers: [1] },
  { name: 'Parallel pairs', pm: [[2, 1, 0.5], [4, 3, 0.5], [6, 5, 0.5], [8, 7, 0.5]], carriers: [1, 3, 5, 7] },
  { name: 'Two 4-op stacks', pm: [[4, 3, 0.35], [3, 2, 0.4], [2, 1, 0.5], [8, 7, 0.35], [7, 6, 0.4], [6, 5, 0.5]], carriers: [1, 5] },
  { name: 'Stack + pair', pm: [[4, 3, 0.35], [3, 2, 0.4], [2, 1, 0.5], [6, 5, 0.5]], carriers: [1, 5] },
  { name: 'Three stacks', pm: [[2, 1, 0.5], [4, 3, 0.5], [6, 5, 0.5], [8, 7, 0.4], [7, 5, 0.3]], carriers: [1, 3, 5] },
  { name: 'Feedback chain', pm: [[2, 2, 0.4], [2, 1, 0.5], [4, 4, 0.4], [4, 3, 0.5]], carriers: [1, 3] },
  { name: 'Shared modulator', pm: [[5, 1, 0.4], [5, 2, 0.4], [5, 3, 0.4], [5, 4, 0.4]], carriers: [1, 2, 3, 4] },
  { name: 'All carriers (additive)', pm: [], carriers: [1, 2, 3, 4, 5, 6, 7, 8] },
];

class MatrixPage {
  // host: { values, addKnob(parent, id, opts), setParams(obj), log(text), store, setAnimate(on) }
  constructor(container, host) {
    this.host = host;
    this.container = container;
    this.cells = {};   // param id -> knob
    this.build();
  }

  grid(title, idFn, cls) {
    const panel = document.createElement('div');
    panel.className = `panel mx-panel ${cls}`;
    const head = document.createElement('div');
    head.className = 'panel-head';
    head.innerHTML = `<span class="panel-title">${title}</span><span class="mx-hint">row: modulator · column: target</span>`;
    panel.appendChild(head);
    const g = document.createElement('div');
    g.className = 'mx-grid';
    g.appendChild(this.cornerCell());
    for (let d = 0; d < NUM_OPS; d++) g.appendChild(this.headCell(`${d + 1}`, 'col'));
    for (let s = 0; s < NUM_OPS; s++) {
      g.appendChild(this.headCell(`${s + 1}`, 'row'));
      for (let d = 0; d < NUM_OPS; d++) {
        const id = idFn(s, d);
        const cell = document.createElement('div');
        cell.className = 'mx-cell' + (s === d ? ' diag' : '');
        const k = this.host.addKnob(cell, id, { size: 'sm', noValue: true, label: '' });
        this.cells[id] = k;
        g.appendChild(cell);
      }
    }
    panel.appendChild(g);
    return panel;
  }

  cornerCell() { const c = document.createElement('div'); c.className = 'mx-corner'; c.innerHTML = '<span>from ↓ to →</span>'; return c; }
  headCell(text, cls) { const c = document.createElement('div'); c.className = `mx-head-cell ${cls}`; c.textContent = text; return c; }

  build() {
    const row = document.createElement('div');
    row.className = 'mx-row';
    row.appendChild(this.grid('PHASE MODULATION', pmId, 'pm'));
    row.appendChild(this.grid('RING MODULATION', rmId, 'rm'));

    // output column: op x (F1 F2 F3 Dry)
    const out = document.createElement('div');
    out.className = 'panel mx-panel out';
    out.innerHTML = '<div class="panel-head"><span class="panel-title">OUTPUT</span><span class="mx-hint">each op to the filters and dry</span></div>';
    const g = document.createElement('div');
    g.className = 'mx-grid out-grid';
    g.appendChild(this.cornerCell());
    OUT_BUSES.forEach(b => g.appendChild(this.headCell(b.toUpperCase(), 'col')));
    for (let k = 0; k < NUM_OPS; k++) {
      g.appendChild(this.headCell(`${k + 1}`, 'row'));
      for (let j = 0; j < NUM_OUTPUTS; j++) {
        const cell = document.createElement('div');
        cell.className = 'mx-cell' + (j === 3 ? ' dry' : '');
        this.cells[outId(k, j)] = this.host.addKnob(cell, outId(k, j), { size: 'sm', noValue: true, label: '' });
        g.appendChild(cell);
      }
    }
    out.appendChild(g);
    row.appendChild(out);

    // tools: layouts, clear, randomize
    const tools = document.createElement('div');
    tools.className = 'panel mx-panel tools';
    tools.innerHTML = '<div class="panel-head"><span class="panel-title">ALGORITHMS</span></div>';
    const list = document.createElement('div');
    list.className = 'mx-layouts';
    for (const L of MATRIX_LAYOUTS) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'pd-btn mx-layout';
      b.textContent = L.name;
      b.dataset.tip = `Fill the grid: ${L.name}`;
      b.addEventListener('click', () => this.applyLayout(L));
      list.appendChild(b);
    }
    tools.appendChild(list);
    const actions = document.createElement('div');
    actions.className = 'mx-actions';
    const clear = document.createElement('button');
    clear.type = 'button'; clear.className = 'pd-btn'; clear.textContent = 'CLEAR';
    clear.dataset.tip = 'Clear every cell; op 1 stays routed to Dry';
    clear.addEventListener('click', () => this.applyLayout(MATRIX_LAYOUTS[0]));
    const rnd = document.createElement('button');
    rnd.type = 'button'; rnd.className = 'pd-btn primary'; rnd.textContent = 'RANDOMIZE';
    rnd.dataset.tip = 'Random PM cells and carriers; Amount sets how many and how deep';
    rnd.addEventListener('click', () => this.randomize());
    actions.append(clear, rnd);
    // the amount knob is UI-only (not a host parameter)
    this.amountDef = { id: '', name: 'Amount', group: '', type: 'float', min: 0, max: 1, def: 0.4, unit: '%' };
    this.amount = 0.4;
    const amt = new Knob(this.amountDef, this.amount, (v) => { this.amount = v; }, null, { size: 'md' });
    amt.el.dataset.tip = 'Randomize amount';
    actions.appendChild(amt.el);
    tools.appendChild(actions);
    row.appendChild(tools);
    this.container.appendChild(row);

    // ---- second row: the signal-flow diagram and the operator scopes (the animation)
    const row2 = document.createElement('div');
    row2.className = 'mx-row';
    const flow = document.createElement('div');
    flow.className = 'panel mx-panel flow';
    flow.innerHTML = '<div class="panel-head"><span class="panel-title">SIGNAL FLOW</span><span class="mx-hint">PM solid · ring dashed · carriers to the output</span></div>';
    this.flowSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    this.flowSvg.setAttribute('viewBox', '0 0 300 170');
    this.flowSvg.setAttribute('class', 'flow-svg');
    flow.appendChild(this.flowSvg);
    row2.appendChild(flow);

    const scopes = document.createElement('div');
    scopes.className = 'panel mx-panel scopes';
    const sh = document.createElement('div');
    sh.className = 'panel-head';
    sh.innerHTML = '<span class="panel-title">OPERATOR SCOPES</span><span class="mx-hint">each operator\'s output, all voices summed · cells and lines glow with the signal</span>';
    this.animate = (this.host.store && this.host.store.get('eightball.animate')) !== '0';
    this.animateBtn = new ToggleButton({ name: 'Animate' }, this.animate ? 1 : 0, (v) => this.setAnimate(v >= 0.5), 'ANIMATE');
    this.animateBtn.el.dataset.tip = 'Live scopes, glowing cells and flow lines (off saves a little CPU in the UI)';
    sh.appendChild(this.animateBtn.el);
    scopes.appendChild(sh);
    const grid = document.createElement('div');
    grid.className = 'scope-grid';
    this.scopeUi = [];
    for (let k = 0; k < NUM_OPS; k++) {
      const s = document.createElement('div');
      s.className = 'screen op-scope';
      s.innerHTML = `<svg viewBox="0 0 120 44" preserveAspectRatio="none"><path class="scr-grid" d="M0 22 H120"/><path class="scr-line" d="M0 22 H120"/></svg><span class="scope-num">${k + 1}</span>`;
      grid.appendChild(s);
      this.scopeUi.push({ el: s, path: s.querySelector('.scr-line') });
    }
    scopes.appendChild(grid);
    row2.appendChild(scopes);
    this.container.appendChild(row2);
    this.drawFlow();
    this.setAnimate(this.animate, true);
  }

  setAnimate(on, initial) {
    this.animate = on;
    this.animateBtn.setValue(on ? 1 : 0);
    this.container.classList.toggle('animating', on);
    if (this.host.store) this.host.store.set('eightball.animate', on ? '1' : '0');
    if (this.host.setAnimate) this.host.setAnimate(on);
    if (!on) {
      for (const id in this.cells) this.cells[id].el.parentNode.style.removeProperty('--glow');
      this.container.querySelectorAll('.mx-head-cell').forEach(c => c.style.removeProperty('--glow'));
      this.flowSvg.querySelectorAll('[data-src]').forEach(e => e.style.removeProperty('--glow'));
      for (const s of this.scopeUi) s.path.setAttribute('d', 'M0 22 H120');
    }
    void initial;
  }

  // the graph: 8 operator nodes on a ring, the output in the centre; an edge per PM / ring cell, self loops for feedback
  drawFlow() {
    const v = this.host.values;
    const cx = 150, cy = 85, R = 66;
    const pos = (k) => { const a = -Math.PI / 2 + k * 2 * Math.PI / NUM_OPS; return [cx + R * Math.cos(a), cy + R * Math.sin(a)]; };
    let edges = '', nodes = '';
    const edge = (s, d, depth, cls) => {
      const [x1, y1] = pos(s), [x2, y2] = pos(d);
      // curve bowing to the side so the s->d and d->s edges don't overlap
      const mx = (x1 + x2) / 2, my = (y1 + y2) / 2, dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy) || 1;
      const bow = 14, qx = mx + (-dy / len) * bow, qy = my + (dx / len) * bow;
      const w = 0.8 + 2.4 * depth;
      edges += `<path class="flow-edge ${cls}" data-src="${s}" d="M${x1.toFixed(1)} ${y1.toFixed(1)} Q${qx.toFixed(1)} ${qy.toFixed(1)} ${x2.toFixed(1)} ${y2.toFixed(1)}" stroke-width="${w.toFixed(2)}" marker-end="url(#flowArrow)"/>`;
    };
    for (let s = 0; s < NUM_OPS; s++)
      for (let d = 0; d < NUM_OPS; d++) {
        const pm = v[pmId(s, d)], rm = v[rmId(s, d)];
        if (s === d) {
          if (pm > 0 || rm > 0) {
            const [x, y] = pos(s);
            const ax = x + (x - cx) / R * 12, ay = y + (y - cy) / R * 12;
            edges += `<circle class="flow-edge loop ${rm > 0 && !(pm > 0) ? 'rm' : 'pm'}" data-src="${s}" cx="${ax.toFixed(1)}" cy="${ay.toFixed(1)}" r="6" stroke-width="${(0.8 + 2.4 * Math.max(pm, rm)).toFixed(2)}"/>`;
          }
          continue;
        }
        if (pm > 0) edge(s, d, pm, 'pm');
        if (rm > 0) edge(s, d, rm, 'rm');
      }
    for (let k = 0; k < NUM_OPS; k++) {
      let send = 0;
      const buses = [];
      for (let j = 0; j < NUM_OUTPUTS; j++) if (v[outId(k, j)] > 0) { send = Math.max(send, v[outId(k, j)]); buses.push(OUT_BUSES[j]); }
      if (send > 0) {
        const [x, y] = pos(k);
        const t = 0.33, ex = x + (cx - x) * (1 - t) * 0.76, ey = y + (cy - y) * (1 - t) * 0.76;
        edges += `<path class="flow-edge out" data-src="${k}" d="M${(x + (cx - x) * 0.2).toFixed(1)} ${(y + (cy - y) * 0.2).toFixed(1)} L${ex.toFixed(1)} ${ey.toFixed(1)}" stroke-width="${(0.8 + 2 * send).toFixed(2)}" marker-end="url(#flowArrowOut)"/>`;
        nodes += `<text class="flow-bus" x="${(x + (cx - x) * 0.55).toFixed(1)}" y="${(y + (cy - y) * 0.55 - 4).toFixed(1)}">${buses.join(' ')}</text>`;
      }
    }
    for (let k = 0; k < NUM_OPS; k++) {
      const [x, y] = pos(k);
      nodes += `<g class="flow-node" data-op="${k}"><circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="12"/><text x="${x.toFixed(1)}" y="${(y + 4).toFixed(1)}">${k + 1}</text></g>`;
    }
    nodes += `<g class="flow-node out"><circle cx="${cx}" cy="${cy}" r="14"/><text x="${cx}" y="${cy + 4}">OUT</text></g>`;
    this.flowSvg.innerHTML = `<defs>
        <marker id="flowArrow" viewBox="0 0 10 10" refX="22" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0 L10 5 L0 10 z"/></marker>
        <marker id="flowArrowOut" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0 L10 5 L0 10 z"/></marker>
      </defs>${edges}${nodes}`;
    this.flowEdges = Array.from(this.flowSvg.querySelectorAll('[data-src]'));
    this.flowNodes = Array.from(this.flowSvg.querySelectorAll('.flow-node[data-op]'));
  }

  refresh(ids) {
    if (!ids || [...ids].some(id => /^(pm|rm|out)\d/.test(id))) this.drawFlow();
  }

  // 30 Hz: operator activity (mean |output|) -> cell, header, node and edge glow
  animateStats(ops, active) {
    if (!this.animate || !ops) return;
    const v = this.host.values;
    const act = ops.map(a => clamp(a * 5, 0, 1));
    for (let s = 0; s < NUM_OPS; s++) {
      const on = (active >> s) & 1;
      for (let d = 0; d < NUM_OPS; d++) {
        const pm = this.cells[pmId(s, d)], rm = this.cells[rmId(s, d)];
        pm.el.parentNode.style.setProperty('--glow', (on ? v[pmId(s, d)] * act[s] : 0).toFixed(3));
        rm.el.parentNode.style.setProperty('--glow', (on ? v[rmId(s, d)] * act[s] : 0).toFixed(3));
      }
      for (let j = 0; j < NUM_OUTPUTS; j++) this.cells[outId(s, j)].el.parentNode.style.setProperty('--glow', (on ? v[outId(s, j)] * act[s] : 0).toFixed(3));
    }
    for (const e of this.flowEdges) e.style.setProperty('--glow', act[Number(e.dataset.src)].toFixed(3));
    for (const n of this.flowNodes) n.style.setProperty('--glow', act[Number(n.dataset.op)].toFixed(3));
  }

  // 20 Hz: the scopes (128 points per operator, empty for silent ones)
  drawScopes(ops) {
    if (!this.animate || !ops) return;
    for (let k = 0; k < NUM_OPS; k++) {
      const pts = ops[k];
      const u = this.scopeUi[k];
      if (!pts || pts.length < 2) { u.path.setAttribute('d', 'M0 22 H120'); u.el.classList.remove('live'); continue; }
      let peak = 0;
      for (const p of pts) peak = Math.max(peak, Math.abs(p));
      const g = peak > 1e-4 ? Math.min(20 / peak, 1 / Math.max(peak, 0.05)) * 1 : 0;   // normalise but keep quiet signals small
      const scale = peak > 1e-4 ? 20 / Math.max(peak, 0.2) : 0;
      void g;
      let d = '';
      for (let i = 0; i < pts.length; i++) d += `${i ? 'L' : 'M'}${(i / (pts.length - 1) * 120).toFixed(1)} ${(22 - pts[i] * scale).toFixed(1)}`;
      u.path.setAttribute('d', d);
      u.el.classList.toggle('live', peak > 1e-4);
    }
  }

  // every grid id -> 0, then the layout
  applyLayout(L) {
    const v = {};
    for (let s = 0; s < NUM_OPS; s++)
      for (let d = 0; d < NUM_OPS; d++) { v[pmId(s, d)] = 0; v[rmId(s, d)] = 0; }
    for (let k = 0; k < NUM_OPS; k++) for (let j = 0; j < NUM_OUTPUTS; j++) v[outId(k, j)] = 0;
    for (const [s, d, depth] of L.pm) v[pmId(s - 1, d - 1)] = depth;
    for (const c of L.carriers) v[outId(c - 1, 3)] = 1;
    this.host.setParams(v);
    this.host.log(`Matrix: ${L.name}`);
  }

  randomize() {
    const a = this.amount;
    const v = {};
    for (let s = 0; s < NUM_OPS; s++)
      for (let d = 0; d < NUM_OPS; d++) {
        const p = s === d ? 0.08 * a : 0.3 * a;
        v[pmId(s, d)] = Math.random() < p ? Math.round(100 * (0.15 + 0.7 * a * Math.random())) / 100 : 0;
        v[rmId(s, d)] = Math.random() < 0.05 * a ? Math.round(100 * (0.3 * a * Math.random())) / 100 : 0;
      }
    const carriers = [];
    for (let k = 0; k < NUM_OPS; k++) {
      const isCarrier = k === 0 || Math.random() < 0.35 * a;
      if (isCarrier) carriers.push(k);
      for (let j = 0; j < NUM_OUTPUTS; j++) v[outId(k, j)] = 0;
      if (isCarrier) v[outId(k, 3)] = Math.round(100 * (0.6 + 0.4 * Math.random())) / 100;
    }
    // a carrier that modulates nothing and is modulated by nothing is fine; make sure every
    // modulator reaches a carrier somewhere, otherwise it's wasted
    for (let s = 0; s < NUM_OPS; s++) {
      if (carriers.includes(s)) continue;
      const reaches = Array.from({ length: NUM_OPS }, (_, d) => v[pmId(s, d)] > 0).some(Boolean);
      if (!reaches && Math.random() < 0.6 * a) {
        const d = carriers[Math.floor(Math.random() * carriers.length)];
        v[pmId(s, d)] = Math.round(100 * (0.2 + 0.5 * a * Math.random())) / 100;
      }
    }
    this.host.setParams(v);
    this.host.log(`Matrix randomized (amount ${Math.round(a * 100)}%)`);
  }
}
