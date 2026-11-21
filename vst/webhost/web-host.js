// ============================================================================
//  Web host: stands in for the plugin's C++ side when the UI runs in a
//  browser. It provides window.__JUCE__.backend with exactly the events the
//  JUCE editor uses (see PluginEditor.h), so vst/ui runs unchanged:
//    audio    the engine compiled to WebAssembly (EIGHTBALL_WASM_B64, from
//             vst/Source via webhost/wasm-engine.cpp) in an AudioWorklet, or on
//             the main thread through a ScriptProcessor when opened from disk
//    model    wavetables are baked by a second engine instance on the main
//             thread and copied into the worklet (no stall on the audio thread)
//    MIDI     Web MIDI (all inputs or one): notes, sustain, bend, mod wheel,
//             aftertouch, all notes off; MIDI learn like the plugin's
//    tempo    user-set BPM (the plugin uses the DAW's)
//    presets  factory (FACTORY_JSON, resolved like PresetManager), this browser
//             (localStorage) or a linked folder on disk (File System Access
//             API): the same .ebpreset files as the VST
//    A/B      two sounds to flip between, as in the plugin
// ============================================================================
(function () {
  'use strict';

  // ---------------------------------------------------------- the bridge ---
  const listeners = {};
  const handlers = {};
  const toUi = (ev, data) => queueMicrotask(() => (listeners[ev] || []).forEach(f => f(data)));
  window.__JUCE__ = {
    backend: {
      addEventListener(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); },
      emitEvent(ev, data) { const h = handlers[ev]; if (h) h(data || {}); },   // synchronous: file pickers keep the click's activation
    },
  };
  const message = (text) => toUi('message', { text });
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); return true; } catch (e) { return false; } },
  };
  const PARAM_INDEX = Object.fromEntries(PARAM_DEFS.map((d, i) => [d.id, i]));
  const ENV_KEYS = [];
  for (let k = 1; k <= NUM_OPS; k++) ENV_KEYS.push(`op${k}Amp`, `op${k}Pitch`, `op${k}Mod`);
  for (let f = 1; f <= NUM_FILTERS; f++) ENV_KEYS.push(`flt${f}Cutoff`, `flt${f}Level`);

  // ----------------------------------------------------------- the model ---
  function defaultEnv(key) {
    if (/Amp$/.test(key)) return { points: [[0, 0, 0], [0.005, 1, 0], [0.305, 0.8, -0.5], [0.605, 0, -0.5]], sustain: 2, loopStart: -1, loopEnd: -1, sync: false };
    if (/Cutoff$/.test(key)) return { points: [[0, 0, 0], [0.005, 1, 0], [0.405, 0.5, -0.5], [0.805, 0, -0.5]], sustain: 2, loopStart: -1, loopEnd: -1, sync: false };
    if (/Level$/.test(key)) return { points: [[0, 1, 0], [1, 1, 0]], sustain: 1, loopStart: -1, loopEnd: -1, sync: false };
    return { points: [[0, 0.5, 0], [1, 0.5, 0]], sustain: 1, loopStart: -1, loopEnd: -1, sync: false };
  }
  function defaultModel() {
    const m = { waves: {}, envs: {}, lfoShapes: {} };
    for (let k = 1; k <= NUM_OPS; k++) m.waves[String(k)] = { mode: 'harmonic', levels: [1], phases: [0] };
    for (const key of ENV_KEYS) m.envs[key] = defaultEnv(key);
    for (let l = 1; l <= NUM_LFOS; l++) m.lfoShapes[String(l)] = Array.from({ length: 64 }, (_, i) => Math.round(Math.sin(2 * Math.PI * i / 64) * 1000) / 1000);
    return m;
  }
  function normEnv(e, key) {
    const d = defaultEnv(key);
    if (!e || !Array.isArray(e.points) || !e.points.length) return d;
    const pts = [];
    let last = 0;
    for (const p of e.points) {
      if (!Array.isArray(p) || p.length < 2) continue;
      const t = Math.max(last, Number(p[0]) || 0);
      last = t;
      pts.push([t, clamp(Number(p[1]) || 0, 0, 1), clamp(Number(p[2]) || 0, -1, 1)]);
    }
    if (!pts.length) return d;
    const n = pts.length;
    const idx = (v, def) => (v === undefined || v === null ? def : clamp(Math.round(Number(v)), -1, n - 1));
    const out = { points: pts, sustain: idx(e.sustain, -1), loopStart: idx(e.loopStart, -1), loopEnd: idx(e.loopEnd, -1), sync: !!e.sync };
    if (out.loopEnd <= out.loopStart) out.loopStart = out.loopEnd = -1;
    return out;
  }
  function normWave(w) {
    if (!w || typeof w !== 'object') return null;
    if (w.mode === 'drawn') {
      if (!Array.isArray(w.shape) || w.shape.length < 2) return null;
      const shape = new Array(256).fill(0);
      for (let i = 0; i < 256 && i < w.shape.length; i++) shape[i] = clamp(Number(w.shape[i]) || 0, -1, 1);
      return { mode: 'drawn', shape };
    }
    if (!Array.isArray(w.levels) || !w.levels.length) return null;
    const levels = w.levels.slice(0, 128).map(v => clamp(Number(v) || 0, 0, 1));
    const phases = levels.map((_, i) => clamp(Number((w.phases || [])[i]) || 0, 0, 1));
    return { mode: 'harmonic', levels, phases };
  }
  // merge the blocks a preset carries over a model (only the parts given), like modelDataFromJson
  function mergeModel(into, json) {
    if (!json || typeof json !== 'object') return into;
    if (json.waves) for (const k in json.waves) { const w = normWave(json.waves[k]); if (w && into.waves[k]) into.waves[k] = w; }
    if (json.envs) for (const k in json.envs) if (into.envs[k]) into.envs[k] = normEnv(json.envs[k], k);
    if (json.lfoShapes) for (const l in json.lfoShapes) {
      const s = json.lfoShapes[l];
      if (Array.isArray(s) && s.length >= 2 && into.lfoShapes[l]) into.lfoShapes[l] = Array.from({ length: 64 }, (_, i) => clamp(Number(s[i % s.length]) || 0, -1, 1));
    }
    return into;
  }

  // ------------------------------------------------------ factory presets ---
  // values = defaults <- template chain <- the preset's params (+ modDst by id); model blocks merge the same way
  const FACTORY = [];
  {
    const templates = FACTORY_JSON.templates || {};
    function applyBlock(block, values, model) {
      if (!block) return;
      for (const id in (block.params || {})) {
        const d = PARAM_BY_ID[id];
        if (!d || d.noPreset) continue;
        const v = Number(block.params[id]);
        if (!isNaN(v)) values[id] = clamp(v, d.min, d.max);
      }
      for (const slot in (block.modDst || {})) {
        const i = MOD_DEST_IDS.indexOf(block.modDst[slot]);
        if (PARAM_BY_ID[slot] && i >= 0) values[slot] = i;
      }
      mergeModel(model, block);
    }
    function applyTemplate(name, values, model, depth) {
      if (!name || depth > 8) return;
      const t = templates[name];
      if (!t) return;
      applyTemplate(t.base, values, model, depth + 1);
      applyBlock(t, values, model);
    }
    for (const cat of FACTORY_JSON.categories || []) {
      for (const p of cat.presets || []) {
        const values = {}, model = defaultModel();
        applyTemplate(p.base, values, model, 0);
        applyBlock(p, values, model);
        FACTORY.push({ id: `factory:${FACTORY.length}`, name: p.name, category: cat.name, factory: true, values, model });
      }
    }
  }

  // ---------------------------------------------------------------- state ---
  const values = defaultParamValues();
  let model = defaultModel();
  let current = { id: '', name: '', category: '' };
  let tempo = clamp(Number(store.get('eightball.tempo')) || 120, 20, 300);
  let animate = false;

  // the full value set a preset gives (missing -> default), master untouched
  function presetValues(pv) {
    const out = {};
    for (const d of PARAM_DEFS) {
      if (d.noPreset) continue;
      let v = Number(pv[d.id]);
      if (pv[d.id] === undefined || pv[d.id] === null || isNaN(v)) v = d.def;
      v = clamp(v, d.min, d.max);
      if (d.step && d.type === 'float') v = Math.round(v / d.step) * d.step;
      out[d.id] = v;
    }
    return out;
  }

  // ---------------------------------------------------------------- wasm ---
  // the engine module: compiled once here, instantiated on the main thread (baking, the file:// fallback)
  // and again inside the worklet
  function wasmBytes() {
    const bin = atob(EIGHTBALL_WASM_B64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return bytes;
  }
  // stub every import the module asks for (a standalone build asks for little or nothing)
  function wasmImports(module) {
    const imports = {};
    for (const imp of WebAssembly.Module.imports(module)) {
      imports[imp.module] = imports[imp.module] || {};
      if (imp.kind === 'function') imports[imp.module][imp.name] = (...a) => { if (imp.name === 'proc_exit') throw new Error('wasm exit'); return 0; };
      else if (imp.kind === 'memory') imports[imp.module][imp.name] = new WebAssembly.Memory({ initial: 512 });
    }
    return imports;
  }
  // Engine: a thin JS wrapper around one instance's exports (shared by the main thread and the worklet)
  const initialised = typeof WeakSet === 'function' ? new WeakSet() : null;
  function makeEngine(instance, sampleRate) {
    const ex = instance.exports;
    if (ex._initialize && !(initialised && initialised.has(ex))) { ex._initialize(); if (initialised) initialised.add(ex); }   // static ctors once per instance
    if (ex.eb_num_params() !== PARAM_DEFS.length) throw new Error(`parameter table mismatch: wasm ${ex.eb_num_params()} vs UI ${PARAM_DEFS.length}`);
    const ptr = ex.eb_create(sampleRate);
    const mem = () => ex.memory.buffer;
    const paramsPtr = ex.eb_params(ptr);
    const nParams = PARAM_DEFS.length;
    const floats = (p, n) => new Float32Array(mem(), p, n);
    const maxFrames = ex.eb_max_frames();
    const scratch = ex.eb_alloc(4 * 4096);
    const e = {
      ex, ptr, sampleRate,
      params() { return floats(paramsPtr, nParams); },
      apply() { ex.eb_apply_params(ptr); },
      settle() { ex.eb_settle(ptr); },
      render(frames) { ex.eb_render(ptr, frames); return [floats(ex.eb_out_l(ptr), frames), floats(ex.eb_out_r(ptr), frames)]; },
      maxFrames,
      noteOn(n, v) { ex.eb_note_on(ptr, n, v); }, noteOff(n) { ex.eb_note_off(ptr, n); },
      sustain(on) { ex.eb_sustain(ptr, on ? 1 : 0); }, bend(v) { ex.eb_bend(ptr, v); }, wheel(v) { ex.eb_wheel(ptr, v); },
      aftertouch(v) { ex.eb_aftertouch(ptr, v); }, allNotesOff() { ex.eb_all_notes_off(ptr); }, panic() { ex.eb_panic(ptr); },
      transport(bpm, ppq, playing) { ex.eb_transport(ptr, bpm, ppq, playing ? 1 : 0); },
      setEnv(index, env) {
        const pts = env.points.slice(0, 32);
        const buf = floats(scratch, pts.length * 3);
        pts.forEach((p, i) => { buf[i * 3] = p[0]; buf[i * 3 + 1] = p[1]; buf[i * 3 + 2] = p[2] || 0; });
        ex.eb_set_env(ptr, index, scratch, pts.length, env.sustain, env.loopStart, env.loopEnd, env.sync ? 1 : 0);
      },
      setLfoShape(l, pts) { floats(scratch, 64).set(pts); ex.eb_set_lfo_shape(ptr, l, scratch); },
      bakeWave(op, w) {
        if (w.mode === 'drawn') { floats(scratch, 256).set(w.shape); ex.eb_bake_wave(ptr, op, 1, 0, 0, 0, scratch); }
        else {
          const n = Math.min(128, w.levels.length);
          floats(scratch, n).set(w.levels.slice(0, n));
          floats(scratch + 4 * 128, n).set(w.phases.slice(0, n));
          ex.eb_bake_wave(ptr, op, 0, scratch, n, scratch + 4 * 128, 0);
        }
      },
      tableFloats() { return ex.eb_table_floats(); },
      table(op) { return floats(ex.eb_table_ptr(ptr, op), ex.eb_table_floats()); },
      setTable(op, data) { const n = ex.eb_table_floats(); const p = ex.eb_alloc(4 * n); floats(p, n).set(data); ex.eb_set_table(ptr, op, p); ex.eb_free(p); },
      stats() {
        const act = floats(ex.eb_op_activity(ptr), 8);
        return {
          voices: ex.eb_active_voices(ptr), peak: ex.eb_take_peak(ptr), sustain: !!ex.eb_sustain_down(ptr), modWheel: ex.eb_wheel_value(ptr),
          ops: Array.from(act, a => Math.round(a * 1e4) / 1e4), active: ex.eb_active_mask(ptr),
          lfo: [0, 1, 2, 3].map(l => Math.round(ex.eb_lfo_value(ptr, l) * 1000) / 1000), gr: Math.round(ex.eb_take_gr(ptr) * 100) / 100,
        };
      },
      scope(op) { ex.eb_scope(ptr, op, scratch, 128, 4); return Array.from(floats(scratch, 128), v => Math.round(v * 1000) / 1000); },
    };
    return e;
  }

  // the worklet: the same wrapper, driven by messages from the host
  function synthWorkletModule() {
    // makeEngine and wasmImports are pasted in below as source (functions cannot cross processorOptions)
    const makeEngine = new Function('PARAM_DEFS', 'clamp', `return (${'__MAKE_ENGINE__'});`)(PARAM_DEFS_IN_WORKLET, (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v));
    const wasmImports = new Function(`return (${'__WASM_IMPORTS__'});`)();
    class EightBallProcessor extends AudioWorkletProcessor {
      constructor(options) {
        super();
        const o = options.processorOptions;
        this.engine = null;
        this.pending = [];
        this.bpm = o.bpm || 120;
        this.animate = false;
        this.sinceStats = 0;
        this.sinceScope = 0;
        this.port.onmessage = (e) => this.onMessage(e.data);
        WebAssembly.instantiate(o.module, wasmImports(o.module)).then((inst) => {
          this.engine = makeEngine(inst, sampleRate);
          this.engine.params().set(o.params);
          this.engine.settle();
          this.engine.transport(this.bpm, 0, false);
          for (const m of this.pending) this.onMessage(m);
          this.pending = [];
          this.port.postMessage({ type: 'ready' });
        }).catch((err) => this.port.postMessage({ type: 'error', error: String(err && err.message || err) }));
      }
      onMessage(m) {
        const e = this.engine;
        if (!e) { this.pending.push(m); return; }
        switch (m.type) {
          case 'param': e.params()[m.index] = m.value; break;
          case 'params': { const p = e.params(); for (const i in m.values) p[i] = m.values[i]; if (m.settle) { e.apply(); e.settle(); } break; }
          case 'noteOn': e.noteOn(m.note, m.vel); break;
          case 'noteOff': e.noteOff(m.note); break;
          case 'sustain': e.sustain(m.on); break;
          case 'bend': e.bend(m.value); break;
          case 'modWheel': e.wheel(m.value); break;
          case 'aftertouch': e.aftertouch(m.value); break;
          case 'allNotesOff': e.allNotesOff(); break;
          case 'panic': e.panic(); break;
          case 'tempo': this.bpm = m.bpm; break;
          case 'env': e.setEnv(m.index, m.env); break;
          case 'lfoShape': e.setLfoShape(m.lfo, m.pts); break;
          case 'table': e.setTable(m.op, m.data); break;
          case 'animate': this.animate = !!m.on; break;
          default: break;
        }
      }
      process(inputs, outputs) {
        const e = this.engine;
        const out = outputs[0];
        if (!e || !out || !out[0]) return true;
        const frames = out[0].length;
        e.apply();
        e.transport(this.bpm, 0, false);
        const [L, R] = e.render(frames);
        out[0].set(L);
        if (out[1]) out[1].set(R);
        this.sinceStats += frames;
        if (this.sinceStats >= sampleRate / 30) {
          this.sinceStats = 0;
          const s = e.stats();
          s.type = 'stats';
          s.bpm = this.bpm;
          this.port.postMessage(s);
        }
        if (this.animate) {
          this.sinceScope += frames;
          if (this.sinceScope >= sampleRate / 20) {
            this.sinceScope = 0;
            const mask = e.ex.eb_active_mask(e.ptr);
            const ops = [];
            for (let k = 0; k < 8; k++) ops.push((mask >> k) & 1 ? e.scope(k) : []);
            this.port.postMessage({ type: 'scope', ops });
          }
        }
        return true;
      }
    }
    registerProcessor('eightball-synth', EightBallProcessor);
  }

  // --------------------------------------------------------------- audio ---
  const audio = {
    ctx: null, node: null, port: null, mode: '', error: '', module: null, main: null, ready: false,
    post(m) { if (this.port) this.port.postMessage(m); },
    get running() { return !!this.ctx && this.ctx.state === 'running' && this.ready; },

    async init() {
      this.module = await WebAssembly.compile(wasmBytes());
      // the main-thread instance: bakes wavetables; also the fallback sound engine
      const inst = await WebAssembly.instantiate(this.module, wasmImports(this.module));
      this.main = makeEngine(inst, 48000);
      this.main.params().set(PARAM_DEFS.map(d => values[d.id]));
      this.main.settle();
      pushModel(this.main, true);
    },

    async start() {
      await this.init();
      const ctx = new (window.AudioContext || window.webkitAudioContext)({ latencyHint: 'interactive' });
      this.ctx = ctx;
      ctx.onstatechange = sendConfig;
      let built = null;
      if (ctx.audioWorklet && location.protocol !== 'file:') {
        try {
          const src = `const PARAM_DEFS_IN_WORKLET = ${JSON.stringify(PARAM_DEFS.map(d => ({ id: d.id })))};\n(${synthWorkletModule.toString().replace("'__MAKE_ENGINE__'", JSON.stringify(makeEngine.toString()))})();`;
          const url = URL.createObjectURL(new Blob([src], { type: 'application/javascript' }));
          try { await ctx.audioWorklet.addModule(url); } finally { URL.revokeObjectURL(url); }
          const node = new AudioWorkletNode(ctx, 'eightball-synth', {
            numberOfInputs: 0, numberOfOutputs: 1, outputChannelCount: [2],
            processorOptions: { module: this.module, params: PARAM_DEFS.map(d => values[d.id]), bpm: tempo },
          });
          node.port.onmessage = (e) => onDspMessage(e.data);
          built = { node, port: node.port, mode: 'AudioWorklet' };
        } catch (e) { console.warn('AudioWorklet unavailable, using the main thread', e); }
      }
      if (!built) built = this.scriptProcessor(ctx);
      this.node = built.node; this.port = built.port; this.mode = built.mode;
      this.node.connect(ctx.destination);
      sendConfig();
    },

    // Chrome / Edge block worklet modules on file://: run the main-thread engine through a ScriptProcessor
    scriptProcessor(ctx) {
      // the main instance was created at 48 kHz for baking; make one at the context's rate instead
      if (ctx.sampleRate !== this.main.sampleRate) {
        this.main.ex.eb_destroy(this.main.ptr);
        this.main = makeEngine({ exports: this.main.ex }, ctx.sampleRate);
        this.main.params().set(PARAM_DEFS.map(d => values[d.id]));
        this.main.settle();
        pushModel(this.main, true);
      }
      const main = this.main;
      let bpm = tempo, since = 0;
      const node = ctx.createScriptProcessor(1024, 0, 2);
      node.onaudioprocess = (ev) => {
        const L = ev.outputBuffer.getChannelData(0), R = ev.outputBuffer.getChannelData(1);
        for (let off = 0; off < L.length; off += 128) {
          main.apply(); main.transport(bpm, 0, false);
          const [l, r] = main.render(128);
          L.set(l, off); R.set(r, off);
        }
        since += L.length;
        if (since >= ctx.sampleRate / 30) { since = 0; const s = main.stats(); s.type = 'stats'; s.bpm = bpm; onDspMessage(s); }
      };
      const port = { postMessage: (m) => {
        switch (m.type) {
          case 'param': main.params()[m.index] = m.value; break;
          case 'params': { const p = main.params(); for (const i in m.values) p[i] = m.values[i]; if (m.settle) { main.apply(); main.settle(); } break; }
          case 'noteOn': main.noteOn(m.note, m.vel); break;
          case 'noteOff': main.noteOff(m.note); break;
          case 'sustain': main.sustain(m.on); break;
          case 'bend': main.bend(m.value); break;
          case 'modWheel': main.wheel(m.value); break;
          case 'aftertouch': main.aftertouch(m.value); break;
          case 'allNotesOff': main.allNotesOff(); break;
          case 'panic': main.panic(); break;
          case 'tempo': bpm = m.bpm; break;
          case 'env': main.setEnv(m.index, m.env); break;
          case 'lfoShape': main.setLfoShape(m.lfo, m.pts); break;
          case 'table': break;   // the main instance baked it already
          default: break;
        }
      } };
      this.ready = true;
      return { node, port, mode: 'ScriptProcessor' };
    },
  };

  function onDspMessage(m) {
    if (m.type === 'stats') toUi('stats', m);
    else if (m.type === 'scope') toUi('scope', m);
    else if (m.type === 'ready') { audio.ready = true; sendConfig(); }
    else if (m.type === 'error') { audio.error = m.error; sendConfig(); }
  }

  // the whole model to an engine (the worklet gets baked tables; the main instance bakes itself)
  function pushModel(engine, bakeHere) {
    for (let k = 0; k < NUM_OPS; k++) {
      const w = model.waves[String(k + 1)];
      if (bakeHere) engine.bakeWave(k, w);
    }
    ENV_KEYS.forEach((key, i) => engine.setEnv(i, model.envs[key]));
    for (let l = 0; l < NUM_LFOS; l++) engine.setLfoShape(l, model.lfoShapes[String(l + 1)]);
  }
  function sendModelToDsp() {
    if (!audio.main) return;
    for (let k = 0; k < NUM_OPS; k++) sendWave(k);
    ENV_KEYS.forEach((key, i) => audio.post({ type: 'env', index: i, env: model.envs[key] }));
    for (let l = 0; l < NUM_LFOS; l++) audio.post({ type: 'lfoShape', lfo: l, pts: model.lfoShapes[String(l + 1)] });
  }
  function sendWave(k) {
    if (!audio.main) return;
    audio.main.bakeWave(k, model.waves[String(k + 1)]);
    if (audio.mode === 'AudioWorklet') audio.post({ type: 'table', op: k, data: audio.main.table(k).slice() });
  }

  function sendConfig() {
    const c = audio.ctx;
    let text;
    if (audio.error) text = `Audio error: ${audio.error}`;
    else if (!audio.running) text = 'Click anywhere to enable audio';
    else text = `Web · ${audio.mode} · ${(c.sampleRate / 1000).toFixed(1)} kHz · ~${(((c.baseLatency || 0) + (c.outputLatency || 0)) * 1000).toFixed(1)} ms`;
    const startPage = (location.hash.match(/page=(\w+)/) || [])[1] || '';
    toUi('config', { wrapper: 'Web', sampleRate: c ? c.sampleRate : 0, blockSize: 128, voices: MAX_VOICES, audio: text, running: audio.running, startPage });
  }

  const started = audio.start().catch((e) => { audio.error = e.message || String(e); console.error(e); sendConfig(); });
  function unlockAudio() {
    if (audio.running || audio.error) return;
    started.then(() => audio.ctx && audio.ctx.resume()).then(sendConfig).catch(() => {});
  }
  document.addEventListener('pointerdown', unlockAudio, true);
  document.addEventListener('keydown', unlockAudio, true);

  // ----------------------------------------------------------- parameters ---
  function setParam(id, value) {
    if (!(id in values)) return;
    values[id] = value;
    audio.post({ type: 'param', index: PARAM_INDEX[id], value });
  }
  function applyAll(all, settle) {
    Object.assign(values, all);
    const byIndex = {};
    for (const id in all) byIndex[PARAM_INDEX[id]] = all[id];
    audio.post({ type: 'params', values: byIndex, settle: !!settle });
  }

  // ---------------------------------------------------------- presets ---
  function applyPreset(pv, info, presetModel) {
    const all = presetValues(pv);
    applyAll(all, true);
    model = presetModel ? JSON.parse(JSON.stringify(presetModel)) : defaultModel();
    sendModelToDsp();
    current = info;
    toUi('params', Object.assign({}, values));
    toUi('model', JSON.parse(JSON.stringify(model)));
    toUi('preset', presetInfo());
  }
  // start on the first factory preset, like a fresh plugin instance
  Object.assign(values, presetValues(FACTORY[0].values));
  model = JSON.parse(JSON.stringify(FACTORY[0].model));
  current = { id: FACTORY[0].id, name: FACTORY[0].name, category: FACTORY[0].category };

  // A/B
  const ab = { other: null, otherInfo: null, isB: false };
  function snapshot() { return { values: Object.assign({}, values), model: JSON.parse(JSON.stringify(model)) }; }
  function presetInfo() { return Object.assign({}, current, { ab: ab.isB ? 'B' : 'A', abOther: !!ab.other }); }

  const PRESET_EXT = '.ebpreset';
  const LS_KEY = 'eightball.userPresets.v1';
  const local = {
    read() { try { return JSON.parse(store.get(LS_KEY)) || {}; } catch (e) { return {}; } },
    write(obj) { return store.set(LS_KEY, JSON.stringify(obj)); },
  };
  const localPresets = () => Object.keys(local.read()).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))
    .map(name => ({ id: `local:${name}`, name, category: 'User', factory: false }));

  const fsSupported = typeof window.showDirectoryPicker === 'function';
  const folder = { handle: null, granted: false, files: [], sig: '' };
  const idb = {
    open() {
      return new Promise((res, rej) => {
        const r = indexedDB.open('eightball', 1);
        r.onupgradeneeded = () => r.result.createObjectStore('kv');
        r.onsuccess = () => res(r.result);
        r.onerror = () => rej(r.error);
      });
    },
    async get(key) {
      const db = await this.open();
      return new Promise((res) => { const r = db.transaction('kv').objectStore('kv').get(key); r.onsuccess = () => res(r.result); r.onerror = () => res(undefined); });
    },
    async set(key, val) {
      const db = await this.open();
      return new Promise((res) => { const tx = db.transaction('kv', 'readwrite'); tx.objectStore('kv').put(val, key); tx.oncomplete = () => res(true); tx.onerror = () => res(false); });
    },
  };
  async function scanFolder() {
    if (!folder.handle || !folder.granted) return false;
    const files = [];
    async function walk(dir, path) {
      for await (const [name, h] of dir.entries()) {
        const rel = path ? `${path}/${name}` : name;
        if (h.kind === 'directory') await walk(h, rel);
        else if (name.toLowerCase().endsWith(PRESET_EXT)) {
          const f = await h.getFile();
          files.push({ id: `user:${rel}`, name: name.slice(0, -PRESET_EXT.length), category: path || 'User',
                       factory: false, handle: h, parent: dir, fileName: name, stamp: `${f.size}:${f.lastModified}` });
        }
      }
    }
    try { await walk(folder.handle, ''); } catch (e) { folder.granted = false; return true; }
    files.sort((a, b) => a.category.localeCompare(b.category) || a.name.localeCompare(b.name, undefined, { numeric: true }));
    const sig = files.map(f => `${f.id}|${f.stamp}`).join(';');
    if (sig === folder.sig) return false;
    folder.sig = sig;
    folder.files = files;
    return true;
  }
  function allPresets() { return [...FACTORY, ...folder.files, ...localPresets()]; }
  function sendPresetList() {
    toUi('presetList', {
      presets: allPresets().map(({ id, name, category, factory }) => ({ id, name, category, factory })),
      folder: folder.granted ? `${folder.handle.name} (linked folder)` : 'this browser — click FOLDER to link a folder on disk',
    });
  }
  async function linkFolder(handle, ask) {
    folder.handle = handle;
    folder.sig = '';
    let state = await handle.queryPermission({ mode: 'readwrite' });
    if (state !== 'granted' && ask) state = await handle.requestPermission({ mode: 'readwrite' });
    folder.granted = state === 'granted';
    await idb.set('presetFolder', handle);
    if (folder.granted) await scanFolder();
    sendPresetList();
    return folder.granted;
  }
  if (fsSupported && window.indexedDB) {
    idb.get('presetFolder').then(async (h) => {
      if (h && !(await linkFolder(h, false))) message(`Click FOLDER to reconnect the preset folder "${h.name}"`);
    }).catch(() => {});
  }
  setInterval(async () => { if (await scanFolder()) sendPresetList(); }, 2000);

  function parsePresetText(text, fallbackName) {
    let json;
    try { json = JSON.parse(text); } catch (e) { throw new Error(`Not a valid preset file: ${fallbackName}`); }
    const params = json && typeof json.params === 'object' ? json.params : null;
    const hasModel = json && (json.waves || json.envs || json.lfoShapes);
    if (!params && !hasModel) throw new Error(`No Eight Ball settings found in ${fallbackName}`);
    return { name: String(json.name || '').trim() || fallbackName, params: params || {}, model: mergeModel(defaultModel(), json) };
  }
  function presetText(name, category) {
    const params = {};
    for (const d of PARAM_DEFS) if (!d.noPreset) params[d.id] = +Number(values[d.id]).toPrecision(6);
    return JSON.stringify(Object.assign({ format: 'Eight Ball Preset', version: 1, name, category, params }, model), null, 1);
  }
  const legalName = (s) => s.trim().replace(/[\\/:*?"<>|]/g, '_').slice(0, 60);

  async function loadPresetById(id) {
    const p = allPresets().find(x => x.id === id);
    if (!p) { message('Preset not found (was it moved or deleted?)'); toUi('preset', presetInfo()); return; }
    try {
      const info = { id, name: p.name, category: p.category };
      if (p.factory) applyPreset(p.values, info, p.model);
      else {
        const text = id.startsWith('local:') ? local.read()[p.name] : await (await p.handle.getFile()).text();
        const parsed = parsePresetText(text, p.name);
        applyPreset(parsed.params, info, parsed.model);
      }
    } catch (e) { message(e.message || String(e)); toUi('preset', presetInfo()); }
  }
  async function savePreset(rawName, overwrite) {
    const name = legalName(rawName);
    const result = (r) => toUi('saveResult', Object.assign({ name }, r));
    if (!name) return result({ ok: false, error: 'Enter a name for the preset' });
    try {
      if (folder.granted) {
        const fileName = name + PRESET_EXT;
        if (!overwrite) {
          let exists = true;
          try { await folder.handle.getFileHandle(fileName); } catch (e) { exists = false; }
          if (exists) return result({ ok: false, exists: true });
        }
        const w = await (await folder.handle.getFileHandle(fileName, { create: true })).createWritable();
        await w.write(presetText(name, 'User'));
        await w.close();
        await scanFolder();
        current = { id: `user:${fileName}`, name, category: 'User' };
      } else {
        const all = local.read();
        if (!overwrite && all[name]) return result({ ok: false, exists: true });
        all[name] = presetText(name, 'User');
        if (!local.write(all)) throw new Error('browser storage is unavailable (private window?)');
        current = { id: `local:${name}`, name, category: 'User' };
      }
      sendPresetList();
      toUi('preset', presetInfo());
      result({ ok: true });
    } catch (e) { result({ ok: false, error: e.message || String(e) }); }
  }
  async function deletePreset(id) {
    const p = allPresets().find(x => x.id === id);
    try {
      if (!p || p.factory) throw new Error('Only user presets can be deleted');
      if (id.startsWith('local:')) { const all = local.read(); delete all[p.name]; local.write(all); }
      else { await p.parent.removeEntry(p.fileName); await scanFolder(); }
      if (current.id === id) current = { id: '', name: current.name, category: 'User' };
      message(`Deleted preset "${p.name}"`);
    } catch (e) { message(e.message || String(e)); }
    sendPresetList();
    toUi('preset', presetInfo());
  }
  const fileInput = document.createElement('input');
  fileInput.type = 'file';
  fileInput.accept = `${PRESET_EXT},application/json`;
  fileInput.style.display = 'none';
  document.addEventListener('DOMContentLoaded', () => document.body.appendChild(fileInput));
  fileInput.addEventListener('change', async () => {
    const f = fileInput.files && fileInput.files[0];
    fileInput.value = '';
    if (!f) return;
    try {
      const p = parsePresetText(await f.text(), f.name.replace(/\.[^.]+$/, ''));
      applyPreset(p.params, { id: `file:${f.name}`, name: p.name, category: 'File' }, p.model);
      message(`Loaded ${f.name}`);
    } catch (e) { message(e.message || String(e)); }
  });
  async function folderButton() {
    if (!fsSupported) { message('Linking a preset folder needs Chrome or Edge; presets are saved in this browser instead.'); return; }
    try {
      if (folder.handle && !folder.granted) { if (await linkFolder(folder.handle, true)) message(`Reconnected "${folder.handle.name}"`); return; }
      const handle = await window.showDirectoryPicker({ id: 'eightball-presets', mode: 'readwrite', startIn: 'documents' });
      await linkFolder(handle, true);
      message(`Preset folder linked: ${handle.name}, ${folder.files.length} preset(s). Link Documents\\Eight Ball\\Presets to share presets with the VST.`);
    } catch (e) { if (e && e.name !== 'AbortError') message(`Folder: ${e.message || e}`); }
  }

  // ---------------------------------------------------------------- notes ---
  const sounding = new Set();
  function noteOn(note, vel) {
    if (!audio.running) message('Audio is off: click anywhere on the page once to enable it');
    audio.post({ type: 'noteOn', note, vel });
    sounding.add(note);
    toUi('notes', { on: [note], off: [] });
  }
  function noteOff(note) {
    audio.post({ type: 'noteOff', note });
    if (sounding.delete(note)) toUi('notes', { on: [], off: [note] });
  }
  function allOff() {
    const off = [...sounding];
    sounding.clear();
    if (off.length) toUi('notes', { on: [], off });
  }

  // ----------------------------------------------------------------- MIDI ---
  const midi = { access: null, selected: store.get('eightball.midiInput') || 'all' };
  const learn = { map: {}, armed: '' };     // cc -> param id
  try { learn.map = JSON.parse(store.get('eightball.midiLearn') || '{}') || {}; } catch (e) { learn.map = {}; }
  function sendLearn() {
    const byParam = {};
    for (const cc in learn.map) byParam[learn.map[cc]] = Number(cc);
    toUi('learn', { armed: learn.armed, map: byParam });
  }
  const learnableCC = (cc) => !(cc === 0 || cc === 1 || cc === 32 || cc === 64 || cc >= 120);
  function midiInputs() {
    return midi.access ? Array.from(midi.access.inputs.values()).map(i => ({ id: i.id, name: i.name, state: i.state })) : [];
  }
  function bindMidi() {
    if (!midi.access) return;
    for (const input of midi.access.inputs.values()) {
      const on = midi.selected === 'all' || midi.selected === input.id;
      input.onmidimessage = on ? (e) => onMidi(e.data) : null;
    }
  }
  function onMidi(d) {
    const st = d[0];
    if (st >= 0xf0) return;
    const cmd = st & 0xf0;
    if (cmd === 0x90 && d[2] > 0) noteOn(d[1], d[2]);
    else if (cmd === 0x80 || cmd === 0x90) noteOff(d[1]);
    else if (cmd === 0xb0) {
      const cc = d[1], v = d[2];
      if (cc === 64) audio.post({ type: 'sustain', on: v >= 64 });
      else if (cc === 1) audio.post({ type: 'modWheel', value: v / 127 });
      else if (cc === 120) { audio.post({ type: 'panic' }); allOff(); }
      else if (cc === 123) { audio.post({ type: 'allNotesOff' }); allOff(); }
      else if (learnableCC(cc)) {
        if (learn.armed) {
          for (const k in learn.map) if (learn.map[k] === learn.armed) delete learn.map[k];
          learn.map[cc] = learn.armed;
          learn.armed = '';
          store.set('eightball.midiLearn', JSON.stringify(learn.map));
          sendLearn();
        }
        const id = learn.map[cc];
        if (id && PARAM_BY_ID[id]) { const val = paramFromNorm(PARAM_BY_ID[id], v / 127); setParam(id, val); toUi('params', { [id]: val }); }
      }
    } else if (cmd === 0xd0) audio.post({ type: 'aftertouch', value: d[1] / 127 });
    else if (cmd === 0xa0) audio.post({ type: 'aftertouch', value: d[2] / 127 });
    else if (cmd === 0xe0) audio.post({ type: 'bend', value: (((d[2] << 7) | d[1]) - 8192) / 8192 });
  }
  if (typeof navigator.requestMIDIAccess === 'function') {
    navigator.requestMIDIAccess({ sysex: false }).then((access) => {
      midi.access = access;
      access.onstatechange = () => { bindMidi(); toUi('midiInputs', { inputs: midiInputs(), selected: midi.selected }); };
      bindMidi();
      toUi('midiInputs', { inputs: midiInputs(), selected: midi.selected });
      const n = midiInputs().length;
      message(n ? `MIDI ready: ${n} input(s): ${midiInputs().map(i => i.name).join(', ')}` : 'MIDI ready: no devices found (plug one in, it appears automatically)');
    }).catch((e) => {
      toUi('midiInputs', { inputs: [], selected: 'all', error: true });
      message(`MIDI unavailable: ${e.message || e}`);
    });
  } else {
    queueMicrotask(() => toUi('midiInputs', { inputs: [], selected: 'all', error: true }));
  }

  // ------------------------------------------------- UI -> host events ---
  Object.assign(handlers, {
    uiReady() {
      sendConfig();
      sendPresetList();
      toUi('params', Object.assign({}, values));
      toUi('model', JSON.parse(JSON.stringify(model)));
      toUi('preset', presetInfo());
      sendLearn();
      toUi('stats', { voices: 0, peak: 0, sustain: false, modWheel: 0, bpm: tempo, ops: [0, 0, 0, 0, 0, 0, 0, 0], active: 0, lfo: [0, 0, 0, 0], gr: 0 });
      if (midi.access) toUi('midiInputs', { inputs: midiInputs(), selected: midi.selected });
    },
    setParam({ id, value }) { setParam(id, value); },
    setParams({ values: v }) { const all = {}; for (const id in v) if (id in values) all[id] = v[id]; applyAll(all, false); },
    gesture() {},
    paramMenu() {},   // no host automation menu in a browser (the UI's own menu still has reset and MIDI learn)
    noteOn({ note, vel }) { noteOn(note, vel); },
    noteOff({ note }) { noteOff(note); },
    panic() { audio.post({ type: 'panic' }); allOff(); },
    modWheel({ value }) { audio.post({ type: 'modWheel', value }); },
    setTempo({ bpm }) { tempo = clamp(Number(bpm) || 120, 20, 300); store.set('eightball.tempo', String(tempo)); audio.post({ type: 'tempo', bpm: tempo }); },
    selectMidi({ id }) { midi.selected = id; store.set('eightball.midiInput', id); bindMidi(); },
    midiLearn({ id }) { learn.armed = PARAM_BY_ID[id] ? id : ''; sendLearn(); },
    midiForget({ id }) { for (const k in learn.map) if (learn.map[k] === id) delete learn.map[k]; store.set('eightball.midiLearn', JSON.stringify(learn.map)); sendLearn(); },
    learnCancel() { learn.armed = ''; sendLearn(); },
    setWave({ op, wave }) {
      const w = normWave(wave);
      if (!w || op < 0 || op >= NUM_OPS) return;
      model.waves[String(op + 1)] = w;
      sendWave(op);
    },
    setEnv({ key, env }) {
      const i = ENV_KEYS.indexOf(key);
      if (i < 0) return;
      model.envs[key] = normEnv(env, key);
      audio.post({ type: 'env', index: i, env: model.envs[key] });
    },
    setLfoShape({ lfo, shape }) {
      if (lfo < 0 || lfo >= NUM_LFOS || !Array.isArray(shape)) return;
      model.lfoShapes[String(lfo + 1)] = Array.from({ length: 64 }, (_, i) => clamp(Number(shape[i % shape.length]) || 0, -1, 1));
      audio.post({ type: 'lfoShape', lfo, pts: model.lfoShapes[String(lfo + 1)] });
    },
    setAnimate({ on }) { animate = !!on; audio.post({ type: 'animate', on: animate }); },
    loadPreset({ id }) { loadPresetById(id); },
    initPreset() { const p = FACTORY.find(x => x.name === 'Init') || FACTORY[0]; applyPreset(p.values, { id: p.id, name: p.name, category: p.category }, p.model); },
    savePreset({ name, overwrite }) { savePreset(name, overwrite); },
    deletePreset({ id }) { deletePreset(id); },
    loadPresetFile() { fileInput.click(); },
    openPresetFolder() { folderButton(); },
    abToggle() {
      const now = snapshot(), nowInfo = Object.assign({}, current);
      if (ab.other) applyPreset(ab.other.values, ab.otherInfo, ab.other.model);
      ab.other = now; ab.otherInfo = nowInfo;
      ab.isB = !ab.isB;
      toUi('preset', presetInfo());
    },
    abCopy() { ab.other = snapshot(); ab.otherInfo = Object.assign({}, current); toUi('preset', presetInfo()); },
  });

  // ---- for the headless check (tests/run-web-tests.ps1): render on the main-thread engine
  window.__eightBallWeb = {
    ready: started,
    factoryCount: FACTORY.length,
    render(note, frames) {
      const e = audio.main;
      if (!e) throw new Error('engine not ready');
      e.params().set(PARAM_DEFS.map(d => values[d.id]));
      e.apply(); e.settle();
      e.noteOn(note, 100);
      const out = new Float32Array(frames);
      for (let off = 0; off < frames; off += 128) {
        e.apply(); e.transport(tempo, 0, false);
        const [L] = e.render(Math.min(128, frames - off));
        out.set(L.subarray(0, Math.min(128, frames - off)), off);
      }
      e.noteOff(note);
      return out;
    },
    loadFactory(i) { const p = FACTORY[i]; applyPreset(p.values, { id: p.id, name: p.name, category: p.category }, p.model); pushModel(audio.main, true); },
  };
})();
