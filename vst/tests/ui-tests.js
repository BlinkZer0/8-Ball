// ============================================================================
//  Headless checks of the plugin UI (vst/ui) with a stand-in bridge.
//  run-ui-tests.ps1 inlines this before the UI's own scripts, so the UI finds
//  window.__JUCE__.backend like it does in the plugin. The mock records every
//  event the UI sends (window.__sent) and answers uiReady with the state a
//  fresh plugin would send. Results are written into <pre id="ui-test-out">.
// ============================================================================
(function () {
  'use strict';
  const listeners = {};
  const sent = [];
  window.__sent = sent;
  const toUi = (ev, data) => setTimeout(() => (listeners[ev] || []).forEach(f => f(data)), 0);
  const defaultModel = () => {
    const m = { waves: {}, envs: {}, lfoShapes: {} };
    for (let k = 1; k <= 8; k++) {
      m.waves[String(k)] = { mode: 'harmonic', levels: [1], phases: [0] };
      m.envs[`op${k}Amp`] = { points: [[0, 0, 0], [0.005, 1, 0], [0.305, 0.8, -0.5], [0.605, 0, -0.5]], sustain: 2, loopStart: -1, loopEnd: -1, sync: false };
      m.envs[`op${k}Pitch`] = { points: [[0, 0.5, 0], [1, 0.5, 0]], sustain: 1, loopStart: -1, loopEnd: -1, sync: false };
      m.envs[`op${k}Mod`] = { points: [[0, 0.5, 0], [1, 0.5, 0]], sustain: 1, loopStart: -1, loopEnd: -1, sync: false };
    }
    return m;
  };
  window.__JUCE__ = {
    backend: {
      addEventListener(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); },
      emitEvent(ev, data) {
        sent.push({ ev, data });
        if (ev === 'uiReady') {
          toUi('config', { sampleRate: 48000, blockSize: 128, wrapper: 'VST3', voices: 32, startPage: '' });
          toUi('presetList', { presets: [
            { id: 'factory:0', name: 'Init', category: 'Init', factory: true },
            { id: 'factory:1', name: 'Tine Piano', category: 'E-Pianos & Bells', factory: true },
            { id: 'user:My Sound.ebpreset', name: 'My Sound', category: 'User', factory: false },
          ], folder: 'C:\\Users\\me\\Documents\\Eight Ball\\Presets' });
          toUi('preset', { id: 'factory:0', name: 'Init', category: 'Init' });
          toUi('params', Object.fromEntries(PARAM_DEFS.map(d => [d.id, d.def])));
          toUi('model', defaultModel());
          toUi('learn', { armed: '', map: {} });
          toUi('stats', { voices: 0, peak: 0, sustain: false, modWheel: 0, bpm: 120, ops: [0, 0, 0, 0, 0, 0, 0, 0], active: 1 });
        }
      },
    },
  };

  const errors = [];
  window.addEventListener('error', (e) => errors.push(`${e.message} (${e.filename}:${e.lineno})`));

  function run() {
    const results = [];
    const check = (ok, what) => results.push({ ok: !!ok, what });
    const $ = (s) => document.querySelector(s);
    const $$ = (s) => Array.from(document.querySelectorAll(s));

    check(errors.length === 0, `no script errors: ${errors.join(' | ') || 'none'}`);
    check(sent.some(s => s.ev === 'uiReady'), 'UI sent uiReady');
    check($('#preset-name').textContent === 'Init', `preset name shown ('${$('#preset-name').textContent}')`);
    // every operator and matrix parameter has a control; so do the global ones
    const missing = PARAM_DEFS.filter(d => (/^op\d|^pm\d|^rm\d|^out\d|^(master|poly|voiceMode|portaOn|portaTime|oversample|bendRange)$/.test(d.id))
                                          && !document.querySelector(`[data-param="${d.id}"]`)).map(d => d.id);
    check(missing.length === 0, `operator / matrix / global params have controls (missing: ${missing.join(', ') || 'none'})`);
    check($$('.op-strip').length === 8, '8 operator strips');
    check($$('.mx-cell').length === 64 + 64 + 32, `matrix cells: ${$$('.mx-cell').length} (64 PM + 64 ring + 32 output)`);
    check($$('.mx-layout').length >= 10, `${$$('.mx-layout').length} algorithm layouts`);

    // a knob drag sends gesture + setParam
    const ratio = $('[data-param="op2Ratio"] svg');
    const r = ratio.getBoundingClientRect();
    const pd = (type, y) => ratio.dispatchEvent(new PointerEvent(type, { bubbles: true, clientX: r.left + 10, clientY: y, pointerId: 1, button: 0, buttons: 1 }));
    ratio.setPointerCapture = () => {};
    const before = sent.length;
    pd('pointerdown', r.top + 20); pd('pointermove', r.top + 10); pd('pointermove', r.top); pd('pointerup', r.top);
    const after = sent.slice(before);
    check(after.some(s => s.ev === 'gesture' && s.data.begin && s.data.id === 'op2Ratio'), 'drag begins a gesture');
    check(after.some(s => s.ev === 'setParam' && s.data.id === 'op2Ratio' && s.data.value > 1), 'drag sends setParam with a higher ratio');
    check(after.some(s => s.ev === 'gesture' && !s.data.begin), 'drag ends the gesture');
    // double-click resets
    ratio.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
    const last = sent[sent.length - 1];
    check(last.ev === 'setParam' && last.data.id === 'op2Ratio' && last.data.value === 1, 'double-click resets to default');

    // a layout fills the grid through setParams
    const n0 = sent.length;
    $$('.mx-layout').find(b => b.textContent.startsWith('Stack 2 > 1')).click();
    const sp = sent.slice(n0).find(s => s.ev === 'setParams');
    check(sp && sp.data.values.pm21 === 0.5 && sp.data.values.out1Dry === 1 && sp.data.values.pm11 === 0, 'layout "Stack 2 > 1" sets pm21 and routes op 1 to Dry');
    check($('#preset-name').textContent.endsWith('*'), 'editing marks the preset dirty');

    // the quick ADSR knob edits the envelope block
    const n1 = sent.length;
    const aKnob = $$('.op-strip')[0].querySelector('.kgroup.env .knob svg');
    aKnob.dispatchEvent(new WheelEvent('wheel', { bubbles: true, deltaY: -100, cancelable: true }));
    const se = sent.slice(n1).find(s => s.ev === 'setEnv');
    check(se && se.data.key === 'op1Amp' && se.data.env.points.length === 4 && se.data.env.sustain === 2, 'attack knob sends setEnv for op1Amp');

    // keyboard: a click on a key sends noteOn / noteOff
    const key = $('.piano-svg .wkey');
    const kr = key.getBoundingClientRect();
    const svg = $('.piano-svg');
    svg.setPointerCapture = () => {};
    const n2 = sent.length;
    svg.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, clientX: kr.left + kr.width / 2, clientY: kr.top + kr.height * 0.8, pointerId: 2, button: 0 }));
    svg.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, clientX: kr.left + kr.width / 2, clientY: kr.top + kr.height * 0.8, pointerId: 2, button: 0 }));
    const notes = sent.slice(n2);
    check(notes.some(s => s.ev === 'noteOn' && s.data.note === 48 && s.data.vel > 90), 'key click sends noteOn C3 with a high velocity near the bottom');
    check(notes.some(s => s.ev === 'noteOff' && s.data.note === 48), 'key release sends noteOff');

    // notes from the host light the key
    (listeners.notes || []).forEach(f => f({ on: [50], off: [] }));
    check($('[data-idx="2"]').classList.contains('down'), 'host note lights the key');

    // right-click opens the custom menu with MIDI learn; picking it sends midiLearn
    const lvl = $('[data-param="op1Level"]');
    lvl.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, clientX: 300, clientY: 300, cancelable: true }));
    const menu = $('.ctx-menu');
    check(menu && !menu.classList.contains('hidden') && menu.textContent.includes('MIDI learn'), 'right-click opens the menu with MIDI learn');
    const n3 = sent.length;
    Array.from(menu.querySelectorAll('.ctx-item')).find(b => b.textContent === 'MIDI learn').click();
    check(sent.slice(n3).some(s => s.ev === 'midiLearn' && s.data.id === 'op1Level'), 'MIDI learn sends midiLearn for op1Level');

    // tooltip shows name + value on hover
    lvl.dispatchEvent(new PointerEvent('pointerover', { bubbles: true }));
    const tip = $('.tooltip');
    check(tip && !tip.classList.contains('hidden') && /Op 1 Level: 100%/.test(tip.textContent), `tooltip text '${tip && tip.textContent}'`);

    // pages switch
    $$('.page-tab').find(t => t.dataset.page === 'presets').click();
    check($('.page[data-page="presets"]').classList.contains('active'), 'presets page shows');
    check($$('.cat-tab').length === 3 && $$('.preset-btn').length >= 1, `preset browser: ${$$('.cat-tab').length} categories`);
    $$('.page-tab').find(t => t.dataset.page === 'ops').click();

    // incoming params update knobs (not the one just dragged within 300 ms: op2Ratio is skipped)
    (listeners.params || []).forEach(f => f({ op3Level: 0.25, op2Ratio: 7 }));
    check(/25%/.test($('[data-param="op3Level"] .knob-value').textContent), 'host param change updates a knob');
    check(!/7/.test($('[data-param="op2Ratio"] .knob-value').textContent), 'a knob just edited here ignores the echo for 300 ms');

    // leave the page the screenshot run asked for
    if (window.__uiTestPage) { const t = $$('.page-tab').find(x => x.dataset.page === window.__uiTestPage); if (t) t.click(); }
    const fails = results.filter(r => !r.ok).length;
    document.getElementById('ui-test-out').textContent = JSON.stringify({ fails, results });
    document.title = 'done';
  }
  window.addEventListener('load', () => setTimeout(() => { try { run(); } catch (e) { document.title = 'ERROR ' + (e.stack || e); } }, 300));
})();
