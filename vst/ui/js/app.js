// ============================================================================
//  UI wiring, shared by the plugin and the web build.
//   - talks only to JuceEngine (engine-juce.js). In the plugin that is JUCE's
//     native bridge to C++; in the web build vst/webhost/web-host.js provides
//     the same bridge on top of Web Audio + Web MIDI.
//   - the host owns all parameter state and the model (waves, envelopes);
//     automation, preset loads and MIDI notes flow back in as events
//   - the whole panel scales to fit the window
// ============================================================================
(function () {
  'use strict';

  const $ = (sel) => document.querySelector(sel);
  function el(tag, cls, html) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html !== undefined) e.innerHTML = html;
    return e;
  }
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* storage unavailable */ } },
  };
  const esc = (s) => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  // ---------------------------------------------------------------- state ---
  const values = defaultParamValues();      // replaced by the plugin's state on connect
  let model = null;                         // { waves, envs, lfoShapes } from the host
  let presetList = [];                      // [{id, name, category, factory}] factory first, then user
  let presetFolder = '';
  let current = { id: '', name: '—', category: '' };
  let presetDirty = false;
  let activeCat = null;
  let learnMap = {}, learnArmed = '';

  const engine = new JuceEngine();
  const knobs = {};
  const bound = {};             // id -> [controls with setValue()]
  const dragging = new Set();   // params being dragged in the UI
  const lastLocal = {};         // id -> time of last UI-side change
  const refreshers = [];        // functions run after values change: (changedIds:Set|null) => void

  // ---------------------------------------------------- parameter plumbing ---
  function applyValue(id, v) {
    values[id] = v;
    if (knobs[id]) knobs[id].setValue(v);
    (bound[id] || []).forEach(c => c.setValue(v));
  }
  function refresh(ids) { refreshers.forEach(fn => fn(ids)); tooltip.refresh(); }

  // A change made in this UI
  function setParam(id, v) {
    lastLocal[id] = performance.now();
    applyValue(id, v);
    engine.setParam(id, v);
    markDirty(id);
    refresh(new Set([id]));
  }
  // Many at once (algorithm layouts, randomize)
  function setParams(obj) {
    const now = performance.now();
    const changed = new Set();
    for (const id in obj) {
      if (!PARAM_BY_ID[id]) continue;
      lastLocal[id] = now;
      applyValue(id, obj[id]);
      changed.add(id);
      markDirty(id);
    }
    engine.setParams(obj);
    refresh(changed);
  }
  function markDirty(id) {
    if (!PARAM_BY_ID[id].noPreset && !presetDirty) { presetDirty = true; renderPresetName(); }
  }

  const gestureFn = (id, begin) => {
    if (begin) { dragging.add(id); engine.beginGesture(id); }
    else { dragging.delete(id); engine.endGesture(id); }
  };

  function addKnob(parent, id, opts) {
    const k = new Knob(PARAM_BY_ID[id], values[id], (v) => setParam(id, v), (begin) => gestureFn(id, begin), opts);
    if (knobs[id]) (bound[id] = bound[id] || []).push(k);   // a second knob for the same parameter (e.g. an envelope amount)
    else knobs[id] = k;
    k.el.dataset.param = id;
    parent.appendChild(k.el);
    return k;
  }

  // Bind a non-knob control (ToggleButton / Segmented / SelectBox) to a param
  function control(Cls, id, ...extra) {
    const c = new Cls(PARAM_BY_ID[id], values[id], (v) => setParam(id, v), ...extra);
    (bound[id] = bound[id] || []).push(c);
    c.el.dataset.param = id;
    return c;
  }

  // Changes coming from the plugin (automation, presets, state restore)
  engine.on('params', (obj) => {
    const now = performance.now();
    const changed = new Set();
    for (const id in obj) {
      if (!PARAM_BY_ID[id]) continue;
      // don't fight the user's hand: skip params being dragged or changed here in the last 300 ms
      if (dragging.has(id) || (lastLocal[id] !== undefined && now - lastLocal[id] < 300)) continue;
      applyValue(id, obj[id]);
      changed.add(id);
    }
    if (changed.size) refresh(changed);
  });

  // ---------------------------------------------------------- tooltip -------
  const tooltip = new Tooltip((node) => {
    const id = node.dataset.param;
    if (id && PARAM_BY_ID[id]) {
      const d = PARAM_BY_ID[id];
      let t = `${d.name}: ${formatParam(d, values[id])}`;
      if (learnMap[id] !== undefined) t += `  ·  CC ${learnMap[id]}`;
      if (learnArmed === id) t += '  ·  move a controller to learn';
      return t;
    }
    return node.dataset.tip || null;
  });

  // ----------------------------------------------------- context menu -------
  // Right-click any control: MIDI learn / forget, reset, the host's automation menu.
  // Shift + right-click keeps the browser menu (Inspect / DevTools).
  const ctxMenu = new ContextMenu();
  document.addEventListener('contextmenu', (e) => {
    if (e.shiftKey) return;
    const ctl = e.target.closest('[data-param]');
    if (!ctl) { e.preventDefault(); return; }
    e.preventDefault();
    const id = ctl.dataset.param;
    const d = PARAM_BY_ID[id];
    const items = [];
    if (learnArmed === id) items.push({ label: 'Learning… (cancel)', onPick: () => engine.learnCancel() });
    else items.push({ label: 'MIDI learn', onPick: () => { engine.midiLearn(id); logMidi(`MIDI learn: move a knob or fader on your controller for ${d.name}`); } });
    if (learnMap[id] !== undefined) items.push({ label: `Forget CC ${learnMap[id]}`, onPick: () => engine.midiForget(id) });
    items.push({ label: 'Reset to default', onPick: () => setParam(id, d.def) });
    if (engine.connected) items.push({ label: 'Host automation menu…', onPick: () => engine.paramMenu(id, e.clientX, e.clientY) });
    ctxMenu.show(e.clientX, e.clientY, `${d.name}: ${formatParam(d, values[id])}`, items);
  });

  engine.on('learn', ({ armed, map }) => {
    if (learnArmed && !armed && map[learnArmed] !== undefined) logMidi(`Learned: CC ${map[learnArmed]} → ${PARAM_BY_ID[learnArmed].name}`);
    learnArmed = armed;
    learnMap = map;
    document.querySelectorAll('[data-param]').forEach(n => {
      const id = n.dataset.param;
      n.classList.toggle('learn-armed', id === armed);
      n.classList.toggle('learned', map[id] !== undefined);
    });
    tooltip.refresh();
  });

  // ------------------------------------------------------------ presets ----
  engine.on('presetList', ({ presets, folder }) => {
    presetList = presets;
    presetFolder = folder;
    if (!activeCat || !categories().includes(activeCat)) activeCat = current.category || (presets[0] && presets[0].category);
    renderBrowser();
  });

  engine.on('preset', (p) => {
    const changed = p.id !== current.id || p.name !== current.name;
    current = p;
    if (changed) presetDirty = false;
    if (p.category && categories().includes(p.category)) activeCat = p.category;
    renderPresetName();
    renderBrowser();
  });

  engine.on('message', ({ text }) => logMidi(text));

  function categories() {
    const cats = [];
    for (const p of presetList) if (!cats.includes(p.category)) cats.push(p.category);
    if (!presetList.some(p => !p.factory) && !cats.includes('User')) cats.push('User');
    return cats;
  }

  function loadPreset(p) {
    presetDirty = false;
    current = { id: p.id, name: p.name, category: p.category };
    for (const id in lastLocal) delete lastLocal[id]; // let all incoming values through
    renderPresetName();
    renderBrowser();
    engine.loadPreset(p.id); // plugin applies the values and sends them back
  }

  function stepPreset(dir) {
    if (!presetList.length) return;
    const i = presetList.findIndex(p => p.id === current.id);
    const next = i < 0 ? 0 : (i + dir + presetList.length) % presetList.length;
    loadPreset(presetList[next]);
  }

  function renderPresetName() {
    $('#preset-name').textContent = current.name + (presetDirty ? ' *' : '');
    $('#preset-cat').textContent = (current.category || 'Preset').toUpperCase();
  }

  const tabsEl = $('#cat-tabs');
  const gridEl = $('#preset-grid');
  function renderBrowser() {
    const cats = categories();
    tabsEl.innerHTML = '';
    for (const c of cats) {
      const t = el('button', 'cat-tab', esc(c));
      t.type = 'button';
      t.setAttribute('role', 'tab');
      t.setAttribute('aria-selected', c === activeCat);
      t.classList.toggle('active', c === activeCat);
      t.classList.toggle('has-current', c === current.category);
      t.addEventListener('click', () => { activeCat = c; renderBrowser(); });
      tabsEl.appendChild(t);
    }
    gridEl.innerHTML = '';
    const items = presetList.filter(p => p.category === activeCat);
    if (!items.length) {
      gridEl.appendChild(el('div', 'grid-empty',
        `No user presets yet. Click <b>SAVE AS</b> to store the current sound.<br>
         Preset files in <span class="path">${esc(presetFolder)}</span> show up here automatically.`));
    }
    for (const p of items) {
      const b = el('button', 'preset-btn', `<span class="pb-name">${esc(p.name)}</span>`);
      b.type = 'button';
      b.title = p.name;
      b.classList.toggle('selected', p.id === current.id);
      b.addEventListener('click', () => loadPreset(p));
      if (!p.factory) {
        const del = el('span', 'pb-del', '×');
        del.title = 'Delete preset';
        del.addEventListener('click', (e) => {
          e.stopPropagation();
          openModal({ title: 'Delete preset', body: `Move <b>${esc(p.name)}</b> to the Recycle Bin?`, ok: 'DELETE', danger: true,
                      onOk: () => engine.deletePreset(p.id) });
        });
        b.appendChild(del);
      }
      gridEl.appendChild(b);
    }
    $('#preset-folder-path').textContent = presetFolder ? `User presets: ${presetFolder}` : '';
  }

  // Save = under the current name (user presets replace themselves), Save As = ask for a name
  function savePrompt(saveAs) {
    const isUser = current.id && !current.id.startsWith('factory:');
    if (!saveAs && isUser) { engine.savePreset(current.name, true); return; }
    openModal({
      title: saveAs ? 'Save preset as' : 'Save preset',
      body: `Saved to <span class="path">${esc(presetFolder)}</span>`,
      input: isUser ? current.name : `${current.name} (copy)`,
      ok: 'SAVE',
      onOk: (name) => { if (name.trim()) engine.savePreset(name.trim(), false); },
    });
  }
  engine.on('saveResult', ({ ok, exists, name, error }) => {
    if (ok) { presetDirty = false; renderPresetName(); logMidi(`Saved preset "${name}"`); }
    else if (exists) {
      openModal({ title: 'Replace preset?', body: `A preset named <b>${esc(name)}</b> already exists. Replace it?`, ok: 'REPLACE', danger: true,
                  onOk: () => engine.savePreset(name, true) });
    } else logMidi(`Save failed: ${error}`);
  });

  $('#preset-prev').addEventListener('click', () => stepPreset(-1));
  $('#preset-next').addEventListener('click', () => stepPreset(1));
  $('#preset-init').addEventListener('click', () => { for (const id in lastLocal) delete lastLocal[id]; engine.initPreset(); });
  $('#preset-save').addEventListener('click', () => savePrompt(false));
  $('#preset-saveas').addEventListener('click', () => savePrompt(true));
  $('#preset-load').addEventListener('click', () => engine.loadPresetFile());
  $('#preset-folder').addEventListener('click', () => engine.openPresetFolder());

  // ------------------------------------------------------------- modal -----
  const modal = $('#modal'), modalInput = $('#modal-input'), modalOk = $('#modal-ok');
  let modalOnOk = null;
  function openModal({ title, body, input, ok, danger, onOk }) {
    $('#modal-title').textContent = title;
    $('#modal-body').innerHTML = body || '';
    modalOk.textContent = ok || 'OK';
    modalOk.classList.toggle('danger', !!danger);
    modalInput.style.display = input === undefined ? 'none' : '';
    modalInput.value = input || '';
    modalOnOk = onOk;
    modal.classList.remove('hidden');
    if (input !== undefined) { modalInput.focus(); modalInput.select(); } else modalOk.focus();
  }
  function closeModal(accept) {
    if (modal.classList.contains('hidden')) return;
    modal.classList.add('hidden');
    const fn = modalOnOk;
    modalOnOk = null;
    if (accept && fn) fn(modalInput.value);
  }
  modalOk.addEventListener('click', () => closeModal(true));
  $('#modal-cancel').addEventListener('click', () => closeModal(false));
  modal.addEventListener('pointerdown', (e) => { if (e.target === modal) closeModal(false); });
  modal.addEventListener('keydown', (e) => {
    e.stopPropagation(); // typing a name must not play notes
    if (e.key === 'Enter') { e.preventDefault(); closeModal(true); }
    else if (e.key === 'Escape') { e.preventDefault(); closeModal(false); }
  });
  modal.addEventListener('keyup', (e) => e.stopPropagation());

  // --------------------------------------------------------- waveforms ------
  // One cycle of an operator's wave for its screen: starters are computed directly,
  // Custom comes from the model (partials or the drawn shape).
  function opWavePoints(k, N) {
    const wave = values[opParamId(k, 'Wave')] | 0;
    const pts = new Float32Array(N + 1);
    if (wave === 5) { for (let i = 0; i <= N; i++) pts[i] = Math.sin(i * 12.9898) * 43758.5453 % 1 * 1.6 - 0.8; return pts; }
    let spec = null;
    if (wave === 6 && model && model.waves && model.waves[String(k + 1)]) spec = model.waves[String(k + 1)];
    if (spec && spec.mode === 'drawn' && spec.shape) {
      const s = spec.shape;
      for (let i = 0; i <= N; i++) pts[i] = s[Math.floor((i % N) / N * s.length)] || 0;
      return pts;
    }
    let levels, phases;
    if (spec && spec.levels) { levels = spec.levels; phases = spec.phases || []; }
    else {
      levels = []; phases = [];
      const H = 32;
      for (let h = 1; h <= H; h++) {
        let a = 0, p = 0;
        if (wave === 0) a = h === 1 ? 1 : 0;
        else if (wave === 1) a = 1 / h;
        else if (wave === 2) a = h % 2 ? 1 / h : 0;
        else if (wave === 3) { a = h % 2 ? 1 / (h * h) : 0; p = (((h - 1) / 2) % 2) ? 0.5 : 0; }
        else if (wave === 4) { // half sine: sine for half a cycle (drawn)
          for (let i = 0; i <= N; i++) pts[i] = (i % N) < N / 2 ? Math.sin(2 * Math.PI * (i % N) / N) : 0;
          return pts;
        }
        levels.push(a); phases.push(p);
      }
    }
    let peak = 0;
    for (let i = 0; i <= N; i++) {
      let y = 0;
      for (let h = 0; h < levels.length; h++) if (levels[h]) y += levels[h] * Math.sin(2 * Math.PI * ((h + 1) * i / N + (phases[h] || 0)));
      pts[i] = y;
      peak = Math.max(peak, Math.abs(y));
    }
    if (peak > 1e-6) for (let i = 0; i <= N; i++) pts[i] /= peak;
    return pts;
  }
  function wavePath(pts, w, h) {
    const pad = 4, N = pts.length - 1, out = [];
    for (let i = 0; i <= N; i++) out.push(`${(i / N * w).toFixed(1)},${(h / 2 - pts[i] * (h / 2 - pad)).toFixed(1)}`);
    return 'M' + out.join(' L');
  }

  function makeScreen(parent, w, h) {
    const s = el('div', 'screen', `
      <svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><path class="scr-grid" d="M0 ${h / 2} H${w}"/><path class="scr-line" d=""/></svg>
      <div class="scr-text"></div>`);
    parent.appendChild(s);
    return { path: s.querySelector('.scr-line'), text: s.querySelector('.scr-text'), root: s };
  }

  // ================================================================ OPERATORS =
  const opsPage = $('#ops-page');
  const opUi = [];
  const ADSR_DEFS = {
    A: { id: '', name: 'Attack', group: '', type: 'float', min: 0.001, max: 5, def: 0.005, unit: 's', skew: 'log' },
    D: { id: '', name: 'Decay', group: '', type: 'float', min: 0.005, max: 10, def: 0.3, unit: 's', skew: 'log' },
    S: { id: '', name: 'Sustain', group: '', type: 'float', min: 0, max: 1, def: 0.8, unit: '%' },
    R: { id: '', name: 'Release', group: '', type: 'float', min: 0.005, max: 10, def: 0.3, unit: 's', skew: 'log' },
  };
  for (let k = 0; k < NUM_OPS; k++) {
    const strip = el('div', 'op-strip');
    strip.dataset.op = k;
    const idc = el('div', 'op-id', `<span class="op-num">OP ${k + 1}</span>`);
    const mute = control(ToggleButton, opParamId(k, 'Mute'), 'M');
    const solo = control(ToggleButton, opParamId(k, 'Solo'), 'S');
    mute.el.classList.add('op-mute'); solo.el.classList.add('op-solo');
    const ms = el('div', 'op-ms');
    ms.append(mute.el, solo.el);
    idc.appendChild(ms);
    const act = el('div', 'op-activity', '<div class="op-act-fill"></div>');
    idc.appendChild(act);
    strip.appendChild(idc);

    const wv = el('div', 'op-wave');
    const scr = makeScreen(wv, 120, 44);
    wv.appendChild(control(SelectBox, opParamId(k, 'Wave')).el);
    strip.appendChild(wv);

    const row = el('div', 'op-knobs');
    const g1 = el('div', 'kgroup');
    ['Ratio', 'Fine', 'Level', 'Pan', 'Vel', 'KeyTrack'].forEach(f => addKnob(g1, opParamId(k, f)));
    const hz = addKnob(g1, opParamId(k, 'Hz'));
    row.appendChild(g1);
    const g2 = el('div', 'kgroup');
    ['Unison', 'Detune', 'Spread'].forEach(f => addKnob(g2, opParamId(k, f)));
    row.appendChild(g2);
    const g3 = el('div', 'kgroup switches');
    g3.appendChild(control(ToggleButton, opParamId(k, 'Fixed'), 'FIXED').el);
    g3.appendChild(control(ToggleButton, opParamId(k, 'PhaseReset'), 'RESET').el);
    row.appendChild(g3);
    // quick amplitude envelope (edits the multi-point envelope's four points; the full editor is on the Articulators page)
    const g4 = el('div', 'kgroup env');
    const envLabel = el('button', 'kgroup-label link', 'AMP ENV ›');
    envLabel.type = 'button';
    envLabel.dataset.tip = `Open op ${k + 1}'s amplitude envelope in the editor`;
    envLabel.addEventListener('click', () => openEnv(`op${k + 1}Amp`));
    g4.appendChild(envLabel);
    const adsr = {};
    for (const f of ['A', 'D', 'S', 'R']) {
      const kn = new Knob(ADSR_DEFS[f], ADSR_DEFS[f].def, () => sendAdsr(k), null, { size: 'md' });
      kn.el.dataset.tip = `Op ${k + 1} amp ${ADSR_DEFS[f].name.toLowerCase()}`;
      adsr[f] = kn;
      g4.appendChild(kn.el);
    }
    row.appendChild(g4);
    // envelope amounts (the pitch and mod-index envelopes themselves are edited on the Articulators page)
    const g5 = el('div', 'kgroup env');
    g5.appendChild(el('span', 'kgroup-label', 'ENV AMOUNT'));
    addKnob(g5, opParamId(k, 'PitchEnvAmt'), { size: 'md', label: 'PITCH' });
    addKnob(g5, opParamId(k, 'ModEnvAmt'), { size: 'md', label: 'MOD IDX' });
    row.appendChild(g5);
    strip.appendChild(row);
    opsPage.appendChild(strip);
    opUi.push({ k, strip, scr, hz, keyTrack: knobs[opParamId(k, 'KeyTrack')], adsr, g4, act: act.firstChild });
  }

  function sendAdsr(k) {
    const u = opUi[k];
    const A = u.adsr.A.value, D = u.adsr.D.value, S = u.adsr.S.value, R = u.adsr.R.value;
    const env = { points: [[0, 0, 0], [A, 1, 0], [A + D, S, -0.5], [A + D + R, 0, -0.5]], sustain: 2, loopStart: -1, loopEnd: -1, sync: false };
    setEnvModel(`op${k + 1}Amp`, env, 'ops');
  }

  // An envelope edited in this UI (the quick ADSR knobs or the editor): keep the local model,
  // tell the plugin, and refresh the other view of the same envelope.
  function setEnvModel(key, env, from) {
    if (!model) model = { waves: {}, envs: {}, lfoShapes: {} };
    if (!model.envs) model.envs = {};
    model.envs[key] = env;
    lastLocal[`env:${key}`] = performance.now();
    engine.setEnv(key, env);
    if (!presetDirty) { presetDirty = true; renderPresetName(); }
    if (from !== 'ops') refreshAdsrKnobs(key);
    if (from !== 'art' && art) art.setModel(model);
  }

  function refreshAdsrKnobs(key) {
    const m = /^op(\d)Amp$/.exec(key);
    if (!m) return;
    const u = opUi[Number(m[1]) - 1];
    const e = model.envs[key];
    const simple = e && e.points && e.points.length === 4 && e.sustain === 2 && e.points[0][0] === 0 && !e.sync;
    u.g4.classList.toggle('na', !simple);
    if (simple) {
      const p = e.points;
      u.adsr.A.setValue(p[1][0]);
      u.adsr.D.setValue(Math.max(0.005, p[2][0] - p[1][0]));
      u.adsr.S.setValue(p[2][1]);
      u.adsr.R.setValue(Math.max(0.005, p[3][0] - p[2][0]));
    }
  }

  function refreshOps(ids) {
    for (const u of opUi) {
      const k = u.k, g = `op${k + 1}`;
      if (ids && ![...ids].some(id => id.startsWith(g))) continue;
      const wave = values[opParamId(k, 'Wave')] | 0;
      const fixed = values[opParamId(k, 'Fixed')] >= 0.5;
      const muted = values[opParamId(k, 'Mute')] >= 0.5;
      u.hz.el.style.display = fixed ? '' : 'none';
      u.keyTrack.el.style.display = fixed ? 'none' : '';
      u.scr.path.setAttribute('d', wavePath(opWavePoints(k, 120), 120, 44));
      const pitch = fixed ? formatParam(PARAM_BY_ID[opParamId(k, 'Hz')], values[opParamId(k, 'Hz')])
                          : `${formatParam(PARAM_BY_ID[opParamId(k, 'Ratio')], values[opParamId(k, 'Ratio')])}`;
      u.scr.text.textContent = `${OP_WAVES[wave].toUpperCase()}  ${pitch}`;
      u.strip.classList.toggle('off', muted);
    }
  }
  refreshers.push(refreshOps);

  // the model (waves, envelopes, LFO shapes) from the host: refresh custom waveforms, the quick ADSR knobs, the editors
  engine.on('model', (m) => {
    const now = performance.now();
    // keep what this UI edited in the last 300 ms (the host echoes it back)
    if (model && model.envs && m.envs)
      for (const key in m.envs) if (lastLocal[`env:${key}`] !== undefined && now - lastLocal[`env:${key}`] < 300) m.envs[key] = model.envs[key];
    if (model && model.lfoShapes && m.lfoShapes)
      for (const l in m.lfoShapes) if (lastLocal[`lfo:${l}`] !== undefined && now - lastLocal[`lfo:${l}`] < 300) m.lfoShapes[l] = model.lfoShapes[l];
    model = m;
    for (const u of opUi) refreshAdsrKnobs(`op${u.k + 1}Amp`);
    refreshOps();
    art.setModel(model);
  });

  // =================================================================== MATRIX =
  const matrix = new MatrixPage($('#matrix-page'), { values, addKnob, setParams, log: logMidi });

  // ================================================================== FILTERS =
  function openEnv(key) { art.openEnv(key); showPage('art'); }
  const filters = new FiltersPage($('#filters-page'), { values, addKnob, control, openEnv });
  refreshers.push((ids) => filters.refresh(ids));

  // ======================================================= ARTICULATORS · LFO =
  const art = new ArtPage($('#art-page'), {
    values, addKnob, control, setParam, menu: ctxMenu, log: logMidi,
    getModel: () => model,
    setEnv: (key, env) => setEnvModel(key, env, 'art'),
    setLfoShape: (l, pts) => {
      if (!model) model = { waves: {}, envs: {}, lfoShapes: {} };
      if (!model.lfoShapes) model.lfoShapes = {};
      model.lfoShapes[String(l + 1)] = pts;
      lastLocal[`lfo:${l + 1}`] = performance.now();
      engine.setLfoShape(l, pts);
      if (!presetDirty) { presetDirty = true; renderPresetName(); }
    },
  });
  refreshers.push((ids) => art.refresh(ids));
  // a marker on every knob an active mod slot drives
  let moddedIds = new Set();
  refreshers.push((ids) => {
    if (ids && ![...ids].some(id => /^mod\d/.test(id))) return;
    const next = art.modulatedIds();
    for (const id of moddedIds) if (!next.has(id)) [knobs[id], ...(bound[id] || [])].forEach(c => c && c.el.classList.remove('modded'));
    for (const id of next) [knobs[id], ...(bound[id] || [])].forEach(c => c && c.el.classList.add('modded'));
    moddedIds = next;
  });

  // ======================================================================= FX =
  const fx = new FxPage($('#fx-page'), { values, addKnob, control, setParams, log: logMidi });
  refreshers.push((ids) => fx.refresh(ids));

  // ================================================================= GLOBAL =
  {
    const row = $('#global-knobs');
    addKnob(row, 'master', { size: 'md', label: 'MASTER' });
    addKnob(row, 'poly', { size: 'md', label: 'VOICES' });
    addKnob(row, 'portaTime', { size: 'md', label: 'PORTA' });
    addKnob(row, 'bendRange', { size: 'md', label: 'BEND' });
    const sw = $('#global-switches');
    sw.appendChild(control(Segmented, 'voiceMode', ['POLY', 'MONO', 'LEG']).el);
    const r2 = el('div', 'switch-row');
    r2.appendChild(control(ToggleButton, 'portaOn', 'PORTA').el);
    r2.appendChild(control(ToggleButton, 'oversample', '2× OS').el);
    sw.appendChild(r2);
  }

  // ========================================================== page tabs ===
  const pageTabs = Array.from(document.querySelectorAll('.page-tab'));
  const pageEls = Array.from(document.querySelectorAll('.page'));
  const PAGE_HINTS = {
    ops: 'Drag knobs up / down · Shift or Ctrl = fine · double-click = default · right-click = MIDI learn',
    matrix: 'Row modulates column · diagonal = feedback · drag a cell up / down · double-click = clear it',
    filters: 'Three filters per voice · send operators to them on the MATRIX page · ENV opens the cutoff by up to 5 octaves',
    art: 'Drag points · drag a segment = curve · double-click = add / delete a point · right-click = sustain, loop · SYNC = beats',
    fx: 'Global, after the voices · drag a unit to reorder the chain · every ON is a true bypass · MIX blends dry and wet',
    presets: 'Factory presets and the files in your user folder; SAVE AS stores the current sound',
  };
  let activePage = 'ops';
  try { activePage = store.get('eightball.page') || 'ops'; } catch (e) { /* storage blocked */ }
  function showPage(p) {
    if (!PAGE_HINTS[p]) p = 'ops';
    activePage = p;
    pageEls.forEach(pg => pg.classList.toggle('active', pg.dataset.page === p));
    pageTabs.forEach(t => { t.classList.toggle('active', t.dataset.page === p); t.setAttribute('aria-selected', t.dataset.page === p); });
    $('#page-hint').textContent = PAGE_HINTS[p];
    store.set('eightball.page', p);
  }
  pageTabs.forEach(t => t.addEventListener('click', () => showPage(t.dataset.page)));

  function refreshPageLeds() {
    let cells = false, toFilters = false;
    for (let s = 0; s < NUM_OPS; s++)
      for (let d = 0; d < NUM_OPS; d++) cells = cells || values[pmId(s, d)] > 0 || values[rmId(s, d)] > 0;
    for (let k = 0; k < NUM_OPS; k++) for (let j = 0; j < 3; j++) toFilters = toFilters || values[outId(k, j)] > 0;
    $('#matrix-led').classList.toggle('on', cells);
    $('#filters-led').classList.toggle('on', toFilters);
    $('#art-led').classList.toggle('on', [1, 2, 3, 4].some(l => values[`lfo${l}On`] >= 0.5) || art.modulatedIds().size > 0);
    $('#fx-led').classList.toggle('on', ['dst', 'cho', 'pha', 'dly', 'rev', 'eq', 'cmp'].some(u => values[`${u}On`] >= 0.5));
  }
  refreshers.push(refreshPageLeds);

  // ---------------------------------------------------------- notes / UI ---
  const monitor = $('#midi-monitor');
  const midiLed = $('#midi-led');
  let ledTimer = 0;
  function logMidi(text) { monitor.textContent = text; }
  function flashLed() {
    midiLed.classList.add('on');
    clearTimeout(ledTimer);
    ledTimer = setTimeout(() => midiLed.classList.remove('on'), 90);
  }

  const piano = new Piano($('#piano'), { numKeys: 24, baseNote: 48, onNoteOn: (n, v) => noteOn(n, v), onNoteOff: (n) => noteOff(n) });

  function noteOn(note, vel) { engine.noteOn(note, vel); piano.setNote(note, true); }
  function noteOff(note) { engine.noteOff(note); piano.setNote(note, false); }

  // All sounding notes (host MIDI + this keyboard), reported by the plugin
  engine.on('notes', ({ on, off }) => {
    off.forEach(n => piano.setNote(n, false));
    on.forEach(n => piano.setNote(n, true));
    flashLed();
    if (on.length) logMidi(`NOTE ON   ${on.map(n => `${midiNoteName(n)} (${n})`).join('  ')}`);
    else if (off.length) logMidi(`NOTE OFF  ${off.map(n => `${midiNoteName(n)} (${n})`).join('  ')}`);
  });

  function setOctave(base) {
    base = clamp(base, 12, 96);
    for (const [k, n] of heldKeys) { noteOff(n); heldKeys.delete(k); }
    piano.setBase(base);
    $('#octave-readout').textContent = `${midiNoteName(Math.max(base, KEY_LOWEST))}–${midiNoteName(Math.min(base + 23, KEY_HIGHEST))}`;
  }
  $('#oct-down').addEventListener('click', () => setOctave(piano.base - 12));
  $('#oct-up').addEventListener('click', () => setOctave(piano.base + 12));

  // Computer keyboard: two rows, A = C
  const KEYMAP = { a: 0, w: 1, s: 2, e: 3, d: 4, f: 5, t: 6, g: 7, y: 8, h: 9, u: 10, j: 11,
                   k: 12, o: 13, l: 14, p: 15, ';': 16, "'": 17 };
  const heldKeys = new Map();
  window.addEventListener('keydown', (e) => {
    if (e.repeat || e.ctrlKey || e.metaKey || e.altKey) return;
    if (/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName) || !modal.classList.contains('hidden')) return;
    const key = e.key.toLowerCase();
    if (key === 'z') { setOctave(piano.base - 12); return; }
    if (key === 'x') { setOctave(piano.base + 12); return; }
    if (key in KEYMAP && !heldKeys.has(key)) {
      const note = piano.base + KEYMAP[key];
      if (note < KEY_LOWEST || note > KEY_HIGHEST) return;
      heldKeys.set(key, note);
      noteOn(note, 100);
    }
  });
  window.addEventListener('keyup', (e) => {
    const key = e.key.toLowerCase();
    if (heldKeys.has(key)) { noteOff(heldKeys.get(key)); heldKeys.delete(key); }
  });
  window.addEventListener('blur', () => { for (const [, n] of heldKeys) noteOff(n); heldKeys.clear(); });

  $('#panic-btn').addEventListener('click', () => {
    engine.panic();
    piano.clear();
    heldKeys.clear();
    logMidi('PANIC — all voices killed');
  });

  // ------------------------------------------------------------- stats -----
  const meterFill = $('#meter-fill');
  const meterClip = document.querySelector('.meter-clip');
  const sustainLed = $('#sustain-led');
  let clipTimer = 0;
  engine.on('stats', ({ voices, peak, sustain, modWheel, bpm, ops, active, lfo, gr }) => {
    art.meters(lfo);
    fx.meter(gr);
    $('#voice-count').textContent = `${voices}/${values.poly | 0}`;
    sustainLed.classList.toggle('on', !!sustain);
    if (typeof modWheel === 'number') wheel.setValue(modWheel);
    if (typeof bpm === 'number' && bpm > 0 && document.activeElement !== bpmInput) bpmInput.value = String(Math.round(bpm * 10) / 10);
    const db = 20 * Math.log10(Math.max(peak, 1e-5));
    meterFill.style.width = `${clamp((db + 60) / 60, 0, 1) * 100}%`;
    if (peak > 0.95) {
      meterClip.classList.add('on');
      clearTimeout(clipTimer);
      clipTimer = setTimeout(() => meterClip.classList.remove('on'), 800);
    }
    if (ops) for (const u of opUi) {
      const a = ops[u.k] || 0;
      u.act.style.height = `${clamp(a * 160, 0, 100)}%`;
      u.strip.classList.toggle('idle', !((active >> u.k) & 1));
    }
  });

  let connectedOnce = false;
  engine.on('config', ({ sampleRate, blockSize, wrapper, audio, running, startPage }) => {
    const web = wrapper === 'Web';
    document.body.classList.toggle('web', web);
    bpmInput.readOnly = !web;
    const sr = sampleRate > 0 ? `${(sampleRate / 1000).toFixed(1)} kHz · ${blockSize} smp` : 'not playing yet';
    $('#audio-info').textContent = audio || `${wrapper} · ${sr}`;
    $('#audio-led').classList.toggle('on', running !== false);
    if (!connectedOnce) logMidi('Connected — play your MIDI controller, the keys, or A–\' on the keyboard');
    if (!connectedOnce && startPage) showPage(startPage);
    connectedOnce = true;
    fit();
  });

  // ---- mod wheel, tempo, MIDI input (web build) --------------------------------
  const wheel = new ModWheel((v) => engine.modWheel(v));
  $('#wheel-slot').replaceWith(wheel.el);

  const bpmInput = $('#bpm-input');
  bpmInput.addEventListener('change', () => {
    const v = clamp(Number(bpmInput.value) || 120, 20, 300);
    bpmInput.value = String(v);
    engine.setTempo(v);
  });

  const midiSelect = $('#midi-select');
  engine.on('midiInputs', ({ inputs, selected, error }) => {
    midiSelect.innerHTML = '';
    if (error) { midiSelect.appendChild(new Option('MIDI unavailable', 'all')); midiSelect.disabled = true; return; }
    midiSelect.disabled = false;
    midiSelect.appendChild(new Option(inputs.length ? `All inputs (${inputs.length})` : 'No MIDI devices', 'all'));
    inputs.forEach(d => midiSelect.appendChild(new Option(d.name + (d.state === 'connected' ? '' : ' (off)'), d.id)));
    midiSelect.value = Array.from(midiSelect.options).some(o => o.value === selected) ? selected : 'all';
  });
  midiSelect.addEventListener('change', () => engine.selectMidi(midiSelect.value));

  // --------------------------------------------------------- fit window ----
  // The fixed-size panel is scaled to fit the window.
  const synth = $('.synth');
  function fit() {
    const vw = window.innerWidth, vh = window.innerHeight;
    const w = synth.offsetWidth + 16, h = synth.offsetHeight + 16;
    const s = Math.min(vw / w, vh / h);
    synth.style.transform = `translateX(-50%) scale(${s})`;
  }
  window.addEventListener('resize', fit);

  // -------------------------------------------------------------- init -----
  renderPresetName();
  renderBrowser();
  showPage(activePage);
  refresh();
  setOctave(48);
  fit();
  if (engine.connected) engine.uiReady();
  else logMidi('Not running inside the plugin — no audio engine connected (UI preview only)');
})();
