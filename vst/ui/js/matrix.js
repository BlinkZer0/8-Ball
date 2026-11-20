// ============================================================================
//  The matrix page: the 8x8 PM grid, the 8x8 ring-mod grid and the output
//  column, as grids of small knobs (drag up/down, Ctrl or Shift = fine,
//  double-click = reset), plus the algorithm layouts, Clear and Randomize.
//  Milestone 4 adds the animation (glowing cells, per-operator scopes,
//  signal-flow lines) on top of this.
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
  // host: { values, addKnob(parent, id, opts), setParams(obj), log(text) }
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
