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
    for (let f = 1; f <= 3; f++) {
      m.envs[`flt${f}Cutoff`] = { points: [[0, 0, 0], [0.005, 1, 0], [0.405, 0.5, -0.5], [0.805, 0, -0.5]], sustain: 2, loopStart: -1, loopEnd: -1, sync: false };
      m.envs[`flt${f}Level`] = { points: [[0, 1, 0], [1, 1, 0]], sustain: 1, loopStart: -1, loopEnd: -1, sync: false };
    }
    for (let l = 1; l <= 4; l++) m.lfoShapes[String(l)] = Array.from({ length: 64 }, (_, i) => Math.round(Math.sin(2 * Math.PI * i / 64) * 1000) / 1000);
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
          toUi('stats', { voices: 0, peak: 0, sustain: false, modWheel: 0, bpm: 120, ops: [0, 0, 0, 0, 0, 0, 0, 0], active: 1, lfo: [0.5, 0, 0, 0] });
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
    // every operator, matrix, filter, LFO and mod-slot parameter has a control; so do the global ones
    const missing = PARAM_DEFS.filter(d => !/^fxOrder/.test(d.id) && !document.querySelector(`[data-param="${d.id}"]`)).map(d => d.id);
    check(missing.length === 0, `every parameter but the FX order has a control (missing: ${missing.join(', ') || 'none'})`);
    check($$('.op-strip').length === 8, '8 operator strips');
    // op 3 reaches nothing: its strip is idle and ON is off; clicking ON unmutes it and routes it to Dry
    check($$('.op-strip')[2].classList.contains('idle') && !$$('.op-strip')[2].querySelector('.op-on').classList.contains('on') && /not routed/.test($$('.op-strip')[2].querySelector('.op-route').textContent), 'an unrouted operator shows idle with ON off');
    const nOn = sent.length;
    $$('.op-strip')[2].querySelector('.op-on').click();
    const spOn = sent.slice(nOn).find(s => s.ev === 'setParams');
    check(spOn && spOn.data.values.out3Dry === 1 && spOn.data.values.op3Mute === 0, 'ON sends out3Dry = 1 and op3Mute = 0');
    check(!$$('.op-strip')[2].classList.contains('idle') && $$('.op-strip')[2].querySelector('.op-on').classList.contains('on') && /DRY/.test($$('.op-strip')[2].querySelector('.op-route').textContent), 'the strip is live and shows its route');
    $$('.op-strip')[2].querySelector('.op-on').click();
    check(sent[sent.length - 1].ev === 'setParams' && sent[sent.length - 1].data.values.op3Mute === 1, 'ON again mutes it');
    $$('.op-strip')[2].querySelector('.op-on').click();
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
    // a big library scrolls inside the browser; the panel keeps the size the OPERATORS page gives it
    const synthH = $('.synth').offsetHeight;
    const big = [];
    for (let i = 0; i < 400; i++) big.push({ id: `factory:${i + 3}`, name: `Wob ${i} Test`, category: 'Dubstep Bass', factory: true });
    (listeners.presetList || []).forEach(f => f({ presets: [{ id: 'factory:0', name: 'Init', category: 'Init', factory: true }, ...big], folder: 'C:\\x' }));
    $$('.cat-tab').find(t => t.textContent.startsWith('Dubstep')).click();
    const grid = $('#preset-grid');
    check($$('.preset-btn').length === 400 && grid.scrollHeight > grid.clientHeight + 200 && $('.synth').offsetHeight === synthH,
          `400 presets scroll inside the browser (scroll ${grid.scrollHeight} in ${grid.clientHeight}), panel height unchanged (${$('.synth').offsetHeight} vs ${synthH})`);
    (listeners.presetList || []).forEach(f => f({ presets: [
      { id: 'factory:0', name: 'Init', category: 'Init', factory: true },
      { id: 'factory:1', name: 'Tine Piano', category: 'E-Pianos & Bells', factory: true },
      { id: 'user:My Sound.ebpreset', name: 'My Sound', category: 'User', factory: false },
    ], folder: 'C:\\Users\\me\\Documents\\Eight Ball\\Presets' }));
    $$('.cat-tab').find(t => t.textContent.startsWith('Init')).click();
    const srch = $('#preset-search');
    srch.value = 'tine'; srch.dispatchEvent(new Event('input'));
    check($$('.preset-btn').length === 1 && /Tine Piano/.test($$('.preset-btn')[0].textContent) && /1 of 3 match/.test($('#preset-count').textContent), 'search finds Tine Piano across categories');
    srch.value = ''; srch.dispatchEvent(new Event('input'));
    $$('.page-tab').find(t => t.dataset.page === 'ops').click();

    // incoming params update knobs (not the one just dragged within 300 ms: op2Ratio is skipped)
    (listeners.params || []).forEach(f => f({ op3Level: 0.25, op2Ratio: 7 }));
    check(/25%/.test($('[data-param="op3Level"] .knob-value').textContent), 'host param change updates a knob');
    check(!/7/.test($('[data-param="op2Ratio"] .knob-value').textContent), 'a knob just edited here ignores the echo for 300 ms');

    // A/B: B flips (abToggle), COPY sends abCopy, the preset event moves the highlight
    const n20 = sent.length;
    $('#ab-b').click(); $('#ab-copy').click(); $('#ab-a').click();
    check(sent.slice(n20).filter(s => s.ev === 'abToggle').length === 1 && sent.slice(n20).some(s => s.ev === 'abCopy'), 'A/B buttons send abToggle once and abCopy');
    (listeners.preset || []).forEach(f => f({ id: 'factory:0', name: 'Init', category: 'Init', ab: 'B', abOther: true }));
    check($('#ab-b').classList.contains('on') && !$('#ab-a').classList.contains('on'), 'preset event with ab = B highlights B');
    (listeners.preset || []).forEach(f => f({ id: 'factory:0', name: 'Init', category: 'Init', ab: 'A', abOther: true }));


    // ---- filters page
    $$('.page-tab').find(t => t.dataset.page === 'filters').click();
    check($$('.flt-panel').length === 3 && $$('.flt-panel .scr-line').every(p => p.getAttribute('d').length > 50), 'three filter panels draw a response curve');
    const n4 = sent.length;
    $('[data-param="fltRouting"] button:nth-child(2)').click();
    check(sent.slice(n4).some(s => s.ev === 'setParam' && s.data.id === 'fltRouting' && s.data.value === 1), 'routing switch sends setParam fltRouting = 1');
    check($('.flt-diagram svg').innerHTML.includes('F3') && /F1: op 1|F1: nothing/.test($('.flt-feeds').textContent), 'routing diagram and feed list render');
    (listeners.params || []).forEach(f => f({ flt1On: 0 }));
    check($$('.flt-panel')[0].classList.contains('off'), 'filter off dims its panel');
    (listeners.params || []).forEach(f => f({ flt1On: 1 }));
    $$('.flt-env-btns .pd-btn')[0].click();
    check($('.page[data-page="art"]').classList.contains('active') && $('.env-panel .env-target.on').textContent === 'F1' && $('.env-kinds button.on').textContent === 'CUTOFF',
          'CUTOFF ENV button opens the editor on filter 1 cutoff');

    // ---- articulators page: the envelope editor
    const envSvg = $('.env-svg');
    check(envSvg && $$('.env-pt').length === 4, `editor shows the 4 points of flt1Cutoff (${$$('.env-pt').length})`);
    $$('.env-panel .env-target').find(b => b.textContent === 'OP 2').click();
    check($('.env-panel .env-target.on').textContent === 'OP 2' && $('.env-kinds button.on').textContent === 'AMP' && $$('.env-pt').length === 4, 'OP 2 target shows its amp envelope');
    // double-click on the curve adds a point and sends setEnv
    const er = envSvg.getBoundingClientRect();
    envSvg.setPointerCapture = () => {};
    const n5 = sent.length;
    envSvg.dispatchEvent(new MouseEvent('dblclick', { bubbles: true, clientX: er.left + er.width * 0.6, clientY: er.top + er.height * 0.5 }));
    const se2 = sent.slice(n5).find(s => s.ev === 'setEnv');
    check(se2 && se2.data.key === 'op2Amp' && se2.data.env.points.length === 5, 'double-click adds a point and sends setEnv op2Amp with 5 points');
    check($$('.env-pt').length === 5, 'the editor shows 5 points');
    // dragging the new point (index 3) sends setEnv with a changed level
    const pt3 = $$('.env-pt')[3];
    const pr = pt3.getBoundingClientRect();
    const n6 = sent.length;
    const pev = (type, dy) => envSvg.dispatchEvent(new PointerEvent(type, { bubbles: true, clientX: pr.left + 4, clientY: pr.top + 4 + dy, pointerId: 3, button: 0, buttons: 1 }));
    pt3.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, clientX: pr.left + 4, clientY: pr.top + 4, pointerId: 3, button: 0, buttons: 1 }));
    pev('pointermove', 20); pev('pointerup', 20);
    const se3 = sent.slice(n6).filter(s => s.ev === 'setEnv').pop();
    check(se3 && se3.data.env.points[3][1] < se2.data.env.points[3][1], 'dragging a point down lowers its level and sends setEnv');
    // the quick ADSR knobs follow (the op 2 envelope is no longer a plain ADSR: 5 points)
    check($$('.op-strip')[1].querySelector('.kgroup.env').classList.contains('na'), 'the op 2 quick ADSR shows "custom shape" for a 5-point envelope');
    // sustain via the toolbar on the selected point (the one just dragged)
    const n7 = sent.length;
    $$('.env-btn').find(b => b.textContent === 'SUSTAIN').click();
    const se4 = sent.slice(n7).find(s => s.ev === 'setEnv');
    check(se4 && se4.data.env.sustain === 3, `SUSTAIN moves the sustain to the selected point (sustain = ${se4 && se4.data.env.sustain})`);
    // a shape preset replaces the envelope
    const shapes = $('.env-shapes');
    shapes.value = 'Pluck'; shapes.dispatchEvent(new Event('change'));
    const se5 = sent.filter(s => s.ev === 'setEnv').pop();
    check(se5 && se5.data.env.points.length === 3 && se5.data.env.sustain === -1, 'shape "Pluck" sends a 3-point one-shot envelope');

    // ---- LFOs
    check($$('.lfo-strip').length === 4, '4 LFO strips');
    const n8 = sent.length;
    const lfoWave = $('[data-param="lfo1Wave"]');
    lfoWave.value = '5'; lfoWave.dispatchEvent(new Event('change'));
    check(sent.slice(n8).some(s => s.ev === 'setParam' && s.data.id === 'lfo1Wave' && s.data.value === 5), 'LFO wave select sends setParam');
    const shapeSvg = $$('.lfo-shape')[0].querySelector('svg');
    check(!$$('.lfo-shape')[0].classList.contains('ro'), 'Drawn wave makes the shape screen editable');
    const sr = shapeSvg.getBoundingClientRect();
    shapeSvg.setPointerCapture = () => {};
    const n9 = sent.length;
    shapeSvg.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, clientX: sr.left + 5, clientY: sr.top + 5, pointerId: 4, button: 0, buttons: 1 }));
    shapeSvg.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, clientX: sr.left + sr.width / 2, clientY: sr.top + sr.height - 5, pointerId: 4, button: 0, buttons: 1 }));
    shapeSvg.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, clientX: sr.left + sr.width / 2, clientY: sr.top + sr.height - 5, pointerId: 4, button: 0 }));
    const sl = sent.slice(n9).find(s => s.ev === 'setLfoShape');
    check(sl && sl.data.lfo === 0 && sl.data.shape.length === 64 && sl.data.shape.slice(0, 8).some(v => v > 0.5) && sl.data.shape[32] < -0.5,
          `drawing in the shape screen sends setLfoShape with 64 points (${sl && sl.data.shape.slice(0, 4)} … ${sl && sl.data.shape[32]})`);
    check(parseFloat($$('.lfo-meter-fill')[0].style.height) > 0, 'LFO meter shows the stats value');

    // ---- mod matrix
    check($$('.mod-row').length === 16, '16 mod slots');
    const dstSel = $('[data-param="mod1Dst"]');
    check(dstSel.querySelectorAll('optgroup').length > 10 && dstSel.options.length === PARAM_BY_ID.mod1Dst.choices.length, `destination list grouped (${dstSel.querySelectorAll('optgroup').length} groups, ${dstSel.options.length} entries)`);
    const n10 = sent.length;
    const srcSel = $('[data-param="mod1Src"]');
    srcSel.value = '1'; srcSel.dispatchEvent(new Event('change'));
    dstSel.value = String(MOD_DEST_IDS.indexOf('flt1Cutoff')); dstSel.dispatchEvent(new Event('change'));
    (listeners.params || []).forEach(f => f({ mod1Amt: 0.5 }));
    check(sent.slice(n10).filter(s => s.ev === 'setParam' && /^mod1(Src|Dst)$/.test(s.data.id)).length === 2, 'source / destination selects send setParam');
    check($$('.mod-row')[0].classList.contains('active') && /\+50%/.test($$('.mod-val')[0].textContent), 'an active slot is highlighted with its amount');
    check($('[data-param="flt1Cutoff"]').classList.contains('modded'), 'the destination knob gets a modulation marker');
    check($('#art-led').classList.contains('on'), 'the ARTICULATORS tab LED lights for an active slot');

    // ---- FX page
    $$('.page-tab').find(t => t.dataset.page === 'fx').click();
    check($$('.fx-panel').length === 7 && $$('.fx-chip').length === 7, '7 FX panels and 7 chain chips');
    check($$('.fx-chip').map(c => c.textContent.trim()).join(',') === 'DISTORTION,CHORUS,PHASER,DELAY,REVERB,EQ,COMP', `chain shows the default order (${$$('.fx-chip').map(c => c.textContent.trim()).join(',')})`);
    check($$('.fx-eq-screen .scr-line')[0].getAttribute('d').length > 50, 'EQ panel draws its response');
    const n11 = sent.length;
    $('[data-param="revOn"]').click();
    check(sent.slice(n11).some(s => s.ev === 'setParam' && s.data.id === 'revOn' && s.data.value === 1), 'reverb ON sends setParam');
    check($$('.fx-chip').find(c => c.textContent.includes('REVERB')).classList.contains('on') && $('#fx-led').classList.contains('on'), 'the chip and the FX tab LED light up');
    // drag the REVERB chip onto the DISTORTION chip: reverb first
    const rev = $$('.fx-chip').find(c => c.textContent.includes('REVERB')), dst = $$('.fx-chip').find(c => c.textContent.includes('DISTORTION'));
    const rr = rev.getBoundingClientRect(), dr = dst.getBoundingClientRect();
    rev.setPointerCapture = () => {};
    const n12 = sent.length;
    rev.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, clientX: rr.left + 5, clientY: rr.top + 5, pointerId: 5, button: 0, buttons: 1 }));
    rev.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, clientX: dr.left + 5, clientY: dr.top + 5, pointerId: 5, button: 0, buttons: 1 }));
    rev.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, clientX: dr.left + 5, clientY: dr.top + 5, pointerId: 5, button: 0 }));
    const so = sent.slice(n12).find(s => s.ev === 'setParams');
    check(so && so.data.values.fxOrder1 === 4 && so.data.values.fxOrder2 === 0 && so.data.values.fxOrder7 === 6, `dragging REVERB first sends the new order (${so && JSON.stringify(so.data.values)})`);
    check($$('.fx-chip')[0].textContent.includes('REVERB') && $$('.fx-panel')[0].classList.contains('fx-rev'), 'chips and panels follow the new order');
    (listeners.stats || []).forEach(f => f({ voices: 1, peak: 0.5, sustain: false, modWheel: 0, bpm: 120, ops: [0, 0, 0, 0, 0, 0, 0, 0], active: 1, lfo: [0, 0, 0, 0], gr: 6.5 }));
    check(/-6.5 dB/.test($('.fx-gr-val').textContent), 'gain reduction meter shows the stats value');

    // ---- the animated matrix
    $$('.page-tab').find(t => t.dataset.page === 'matrix').click();
    check($$('.flow-node').length === 9 && $$('.flow-edge.pm').length >= 1 && $$('.flow-edge.out').length >= 1, `flow diagram: ${$$('.flow-edge').length} edges after the layout`);
    const n13 = sent.length;
    const anim = $$('.mx-panel.scopes .power')[0];
    anim.click(); anim.click();
    check(sent.slice(n13).filter(s => s.ev === 'setAnimate').length === 2 && $('#matrix-page').classList.contains('animating'), 'ANIMATE toggle sends setAnimate and ends up on');
    (listeners.stats || []).forEach(f => f({ voices: 1, peak: 0.5, sustain: false, modWheel: 0, bpm: 120, ops: [0.3, 0.3, 0, 0, 0, 0, 0, 0], active: 3, lfo: [0, 0, 0, 0], gr: 0 }));
    check(parseFloat($('[data-param="pm21"]').parentNode.style.getPropertyValue('--glow')) > 0.3, `an active PM cell glows (--glow ${$('[data-param="pm21"]').parentNode.style.getPropertyValue('--glow')})`);
    (listeners.scope || []).forEach(f => f({ ops: [Array.from({ length: 128 }, (_, i) => Math.sin(i / 10) * 0.3), [], [], [], [], [], [], []] }));
    check($$('.op-scope')[0].classList.contains('live') && $$('.op-scope .scr-line')[0].getAttribute('d').length > 500 && !$$('.op-scope')[1].classList.contains('live'), 'scope event draws op 1 and leaves silent ops flat');

    // ---- the wave editor
    $$('.page-tab').find(t => t.dataset.page === 'ops').click();
    $$('.op-strip')[0].querySelector('.op-wave .screen').click();
    const we = $('.wave-editor');
    check(we && !we.classList.contains('hidden') && $$('.hb-level').length === 64 && $$('.hb-phase').length === 64, 'clicking a wave screen opens the editor with 64 level and phase bars');
    const lv = $('.wave-levels');
    const lr = lv.getBoundingClientRect();
    lv.setPointerCapture = () => {};
    const n14 = sent.length;
    lv.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, clientX: lr.left + lr.width * (2.5 / 64), clientY: lr.top + lr.height * 0.5, pointerId: 6, button: 0, buttons: 1 }));
    lv.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, clientX: lr.left + lr.width * (2.5 / 64), clientY: lr.top + lr.height * 0.5, pointerId: 6, button: 0 }));
    const sw = sent.slice(n14).filter(s => s.ev === 'setWave').pop();
    check(sw && sw.data.op === 0 && sw.data.wave.mode === 'harmonic' && Math.abs(sw.data.wave.levels[2] - 0.5) < 0.05 && sw.data.wave.levels[0] === 1,
          `painting partial 3 to 50% sends setWave (${sw && JSON.stringify(sw.data.wave.levels.slice(0, 4))})`);
    check(sent.slice(n14).some(s => s.ev === 'setParam' && s.data.id === 'op1Wave' && s.data.value === 6), 'editing sets Op 1 Wave to Custom');
    check(/CUSTOM/.test($$('.op-strip')[0].querySelector('.scr-text').textContent), 'the strip screen shows CUSTOM');
    $('.wave-mode [data-mode="drawn"]').click();
    const n15 = sent.length;
    const dw = $('.wave-draw svg');
    const dr2 = dw.getBoundingClientRect();
    dw.setPointerCapture = () => {};
    dw.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, clientX: dr2.left + 2, clientY: dr2.top + 2, pointerId: 7, button: 0, buttons: 1 }));
    dw.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, clientX: dr2.left + dr2.width / 2, clientY: dr2.top + dr2.height - 2, pointerId: 7, button: 0, buttons: 1 }));
    dw.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, clientX: dr2.left + dr2.width / 2, clientY: dr2.top + dr2.height - 2, pointerId: 7, button: 0 }));
    const sw2 = sent.slice(n15).filter(s => s.ev === 'setWave').pop();
    check(sw2 && sw2.data.wave.mode === 'drawn' && sw2.data.wave.shape.length === 256 && sw2.data.wave.shape[128] < -0.5, 'DRAWN mode: drawing sends a 256-point shape');
    $('.wave-mode [data-mode="harmonic"]').click();
    const sw3 = sent.filter(s => s.ev === 'setWave').pop();
    check(sw3 && sw3.data.wave.mode === 'harmonic' && sw3.data.wave.levels.length >= 1, 'back to HARMONIC converts the drawing to partials');
    $('.wave-close').click();
    check(we.classList.contains('hidden'), 'close hides the editor');
    if (window.__uiTestPage === 'wave') { $$('.op-strip')[1].querySelector('.op-wave .screen').click(); $$('.wave-starters .pd-btn')[1].click(); }

    // leave the page the screenshot run asked for
    if (window.__uiTestPage) { const t = $$('.page-tab').find(x => x.dataset.page === (window.__uiTestPage === 'wave' ? 'ops' : window.__uiTestPage)); if (t) t.click(); }
    if (window.__uiTestPage === 'matrix') $$('.mx-layout').find(b => b.textContent.startsWith('Two 4-op')).click();
    if (window.__uiTestPage === 'filters') $('[data-param="fltRouting"] button:nth-child(3)').click();
    const fails = results.filter(r => !r.ok).length;
    document.getElementById('ui-test-out').textContent = JSON.stringify({ fails, results });
    document.title = 'done';
  }
  window.addEventListener('load', () => setTimeout(() => { try { run(); } catch (e) { document.title = 'ERROR ' + (e.stack || e); } }, 300));
})();
