// ============================================================================
//  Parameter controls besides the knob. Same conventions as Knob:
//  setValue(v) updates the display, onChange(v) fires on user edits.
//    ToggleButton - bool param   (click; double-click = default)
//    Segmented    - choice param (click; wheel / arrow keys step; double-click = default)
//    SelectBox    - choice param (native dropdown; wheel steps; double-click = default)
//    ModWheel     - SVG performance wheel (drag, wheel, arrow keys, double-click = 0)
//    Tooltip      - one floating tooltip for every control (name + value)
//    ContextMenu  - the right-click menu (MIDI learn, reset, host menu)
// ============================================================================
'use strict';

class ToggleButton {
  constructor(def, value, onChange, label) {
    this.def = def;
    this.onChange = onChange;
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'power';
    b.innerHTML = `<span class="led"></span><span>${label || 'ON'}</span>`;
    b.addEventListener('click', () => this.onChange(this.value >= 0.5 ? 0 : 1));
    b.addEventListener('dblclick', (e) => e.preventDefault());
    this.el = b;
    this.setValue(value);
  }
  setValue(v) {
    this.value = v;
    this.el.classList.toggle('on', v >= 0.5);
    this.el.setAttribute('aria-pressed', v >= 0.5);
  }
}

class Segmented {
  constructor(def, value, onChange, labels) {
    this.def = def;
    this.onChange = onChange;
    const wrap = document.createElement('div');
    wrap.className = 'seg';
    wrap.setAttribute('role', 'radiogroup');
    wrap.setAttribute('aria-label', def.name);
    this.buttons = (labels || def.choices).map((label, i) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = label;
      b.setAttribute('role', 'radio');
      b.addEventListener('click', () => this.pick(i));
      wrap.appendChild(b);
      return b;
    });
    wrap.addEventListener('wheel', (e) => { e.preventDefault(); this.pick(this.value + (e.deltaY < 0 ? 1 : -1)); }, { passive: false });
    wrap.addEventListener('keydown', (e) => {
      const dir = { ArrowUp: 1, ArrowRight: 1, ArrowDown: -1, ArrowLeft: -1 }[e.key];
      if (dir) { e.preventDefault(); e.stopPropagation(); this.pick(this.value + dir); this.buttons[this.value].focus(); }
    });
    wrap.addEventListener('dblclick', () => this.pick(this.def.def));
    this.el = wrap;
    this.setValue(value);
  }
  pick(i) {
    i = clamp(Math.round(i), 0, this.buttons.length - 1);
    if (i !== this.value) this.onChange(i);
  }
  setValue(v) {
    this.value = clamp(Math.round(v), 0, this.buttons.length - 1);
    this.buttons.forEach((b, i) => { b.classList.toggle('on', i === this.value); b.setAttribute('aria-checked', i === this.value); });
  }
}

class SelectBox {
  // labels: optional alternative texts; groups: optional array parallel to the choices, consecutive equal
  // names become an <optgroup> ('' = none)
  constructor(def, value, onChange, labels, groups) {
    this.def = def;
    this.onChange = onChange;
    const s = document.createElement('select');
    s.className = 'param-select';
    s.setAttribute('aria-label', def.name);
    let grp = null, grpName = null;
    (labels || def.choices).forEach((label, i) => {
      const opt = new Option(label, String(i));
      const gname = groups ? groups[i] : '';
      if (!gname) { s.appendChild(opt); grp = null; grpName = null; return; }
      if (gname !== grpName) { grp = document.createElement('optgroup'); grp.label = gname; grpName = gname; s.appendChild(grp); }
      grp.appendChild(opt);
    });
    s.addEventListener('change', () => this.onChange(Number(s.value)));
    s.addEventListener('wheel', (e) => {
      e.preventDefault();
      const i = clamp(this.value + (e.deltaY < 0 ? -1 : 1), 0, s.options.length - 1);
      if (i !== this.value) this.onChange(i);
    }, { passive: false });
    s.addEventListener('dblclick', () => { if (this.value !== this.def.def) this.onChange(this.def.def); });
    s.addEventListener('keydown', (e) => e.stopPropagation()); // arrow keys belong to the dropdown, not the piano
    this.el = s;
    this.setValue(value);
  }
  setValue(v) {
    this.value = clamp(Math.round(v), 0, this.el.options.length - 1);
    this.el.value = String(this.value);
  }
}

class ModWheel {
  constructor(onChange, onGesture) {
    this.onChange = onChange;
    this.onGesture = onGesture || null;
    this.value = 0;
    this.drag = null;
    const H = 110, W = 26, T = 16;
    this.H = H; this.T = T;
    const ridges = Array.from({ length: 14 }, (_, i) => `<line x1="4" x2="${W - 4}" y1="${6 + i * 7.5}" y2="${6 + i * 7.5}"/>`).join('');
    const el = document.createElement('div');
    el.className = 'wheel-ctl';
    el.innerHTML = `
      <svg class="wheel-svg" viewBox="0 0 ${W} ${H}" tabindex="0" role="slider" aria-label="Mod wheel"
           aria-valuemin="0" aria-valuemax="127">
        <rect class="wh-slot" x="0.5" y="0.5" width="${W - 1}" height="${H - 1}" rx="5"/>
        <g class="wh-ridges">${ridges}</g>
        <rect class="wh-fill" x="3" width="${W - 6}" rx="3"/>
        <rect class="wh-thumb" x="2" width="${W - 4}" height="${T}" rx="3"/>
      </svg>
      <span class="ctl-label">MOD</span>
      <span class="wheel-value">0</span>`;
    this.el = el;
    this.svg = el.querySelector('svg');
    this.thumb = el.querySelector('.wh-thumb');
    this.fill = el.querySelector('.wh-fill');
    this.readout = el.querySelector('.wheel-value');
    this.bind();
    this.render();
  }

  set(v, notify) {
    v = clamp(v, 0, 1);
    if (v === this.value) return;
    this.value = v;
    this.render();
    if (notify) this.onChange(v);
  }
  setValue(v) { if (!this.drag) this.set(v, false); }

  render() {
    const y = (this.H - this.T - 4) * (1 - this.value) + 2;
    this.thumb.setAttribute('y', y.toFixed(1));
    this.fill.setAttribute('y', (y + this.T / 2).toFixed(1));
    this.fill.setAttribute('height', Math.max(0, this.H - 3 - (y + this.T / 2)).toFixed(1));
    const midi = Math.round(this.value * 127);
    this.readout.textContent = midi;
    this.svg.setAttribute('aria-valuenow', String(midi));
  }

  bind() {
    const svg = this.svg;
    const fromY = (clientY) => {
      const r = svg.getBoundingClientRect();
      return 1 - (clientY - r.top - (this.T / 2) * (r.height / this.H)) / (r.height * (this.H - this.T) / this.H);
    };
    svg.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      svg.setPointerCapture(e.pointerId);
      svg.focus();
      this.drag = { y: e.clientY, v: this.value };
      if (this.onGesture) this.onGesture(true);
      if (!e.shiftKey) this.set(fromY(e.clientY), true); // click jumps, Shift-drag is relative + fine
    });
    svg.addEventListener('pointermove', (e) => {
      if (!this.drag) return;
      if (e.shiftKey) {
        this.drag.v = clamp(this.drag.v + (this.drag.y - e.clientY) * 0.002, 0, 1);
        this.drag.y = e.clientY;
        this.set(this.drag.v, true);
      } else {
        this.drag.y = e.clientY;
        this.drag.v = fromY(e.clientY);
        this.set(this.drag.v, true);
      }
    });
    const end = () => { if (!this.drag) return; this.drag = null; if (this.onGesture) this.onGesture(false); };
    svg.addEventListener('pointerup', end);
    svg.addEventListener('pointercancel', end);
    svg.addEventListener('dblclick', () => this.set(0, true));
    svg.addEventListener('wheel', (e) => { e.preventDefault(); this.set(this.value + (e.deltaY < 0 ? 1 : -1) * (e.shiftKey ? 1 / 127 : 8 / 127), true); }, { passive: false });
    svg.addEventListener('keydown', (e) => {
      const dir = { ArrowUp: 1, ArrowRight: 1, ArrowDown: -1, ArrowLeft: -1 }[e.key];
      if (dir) { e.preventDefault(); e.stopPropagation(); this.set(this.value + dir * (e.shiftKey ? 1 / 127 : 8 / 127), true); }
    });
  }
}

// One floating tooltip for every [data-param] control (and anything with data-tip):
// "Name  value". Follows the hovered control; updates while a knob is dragged.
class Tooltip {
  constructor(getText) {
    this.getText = getText;   // (element) -> string | null
    this.el = document.createElement('div');
    this.el.className = 'tooltip hidden';
    document.body.appendChild(this.el);
    this.target = null;
    document.addEventListener('pointerover', (e) => {
      const t = e.target.closest ? e.target.closest('[data-param], [data-tip]') : null;
      if (t !== this.target) { this.target = t; this.update(); }
    });
    document.addEventListener('pointerout', (e) => {
      if (this.target && !this.target.contains(e.relatedTarget)) { this.target = null; this.update(); }
    });
    document.addEventListener('pointerdown', (e) => { if (e.button === 2) this.hide(); });
  }
  hide() { this.el.classList.add('hidden'); }
  update() {
    const t = this.target;
    const text = t ? this.getText(t) : null;
    if (!text) { this.hide(); return; }
    this.el.textContent = text;
    this.el.classList.remove('hidden');
    const r = t.getBoundingClientRect();
    const w = this.el.offsetWidth, h = this.el.offsetHeight;
    let x = r.left + r.width / 2 - w / 2, y = r.top - h - 6;
    if (y < 4) y = r.bottom + 6;
    x = clamp(x, 4, window.innerWidth - w - 4);
    this.el.style.left = `${x}px`;
    this.el.style.top = `${y}px`;
  }
  refresh() { if (this.target) this.update(); }
}

// A small custom context menu: items [{ label, onPick, disabled }], shown at (x, y)
class ContextMenu {
  constructor() {
    this.el = document.createElement('div');
    this.el.className = 'ctx-menu hidden';
    document.body.appendChild(this.el);
    document.addEventListener('pointerdown', (e) => { if (!this.el.contains(e.target)) this.hide(); }, true);
    window.addEventListener('keydown', (e) => { if (e.key === 'Escape') this.hide(); });
    window.addEventListener('blur', () => this.hide());
  }
  show(x, y, title, items) {
    this.el.innerHTML = '';
    if (title) { const t = document.createElement('div'); t.className = 'ctx-title'; t.textContent = title; this.el.appendChild(t); }
    for (const it of items) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'ctx-item';
      b.textContent = it.label;
      b.disabled = !!it.disabled;
      b.addEventListener('click', () => { this.hide(); it.onPick(); });
      this.el.appendChild(b);
    }
    this.el.classList.remove('hidden');
    const w = this.el.offsetWidth, h = this.el.offsetHeight;
    this.el.style.left = `${clamp(x, 4, window.innerWidth - w - 4)}px`;
    this.el.style.top = `${clamp(y, 4, window.innerHeight - h - 4)}px`;
  }
  hide() { this.el.classList.add('hidden'); }
}
