// ============================================================================
//  Headless checks of the WEB BUILD (web/index.html): the real bridge
//  (webhost/web-host.js) and the real engine (WebAssembly) under the UI, in
//  headless Edge. run-web-tests.ps1 appends this to a copy of the page and
//  reads <pre id="web-test-out">. The page is opened from disk, so audio
//  output itself is not exercised: the engine is driven through the main-thread
//  instance (window.__eightBallWeb.render) that the page also uses to bake
//  wavetables.
// ============================================================================
(function () {
  'use strict';
  const errors = [];
  window.addEventListener('error', (e) => errors.push(`${e.message} (${e.filename}:${e.lineno})`));
  window.addEventListener('unhandledrejection', (e) => errors.push(`rejection: ${e.reason && e.reason.message || e.reason}`));
  const results = [];
  const check = (ok, what) => results.push({ ok: !!ok, what });
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  const wait = (ms) => new Promise(r => setTimeout(r, ms));
  const rms = (a) => { let s = 0; for (let i = 0; i < a.length; i++) s += a[i] * a[i]; return Math.sqrt(s / a.length); };
  const peak = (a) => { let p = 0; for (let i = 0; i < a.length; i++) p = Math.max(p, Math.abs(a[i])); return p; };
  const finish = () => {
    const fails = results.filter(r => !r.ok).length;
    const out = document.createElement('pre');
    out.id = 'web-test-out';
    out.style.display = 'none';
    out.textContent = JSON.stringify({ fails, results });
    document.body.appendChild(out);
    document.title = fails ? `WEB TESTS: ${fails} FAILURE(S)` : 'WEB TESTS OK';
  };

  async function run() {
    const web = window.__eightBallWeb;
    check(window.__JUCE__ && window.__JUCE__.backend, 'the web host provides window.__JUCE__.backend');
    check(web, 'web host test hook present');
    check(/^Eight Ball v\d+\.\d+/.test(document.title), `title carries the version ('${document.title}')`);
    try { await web.ready; } catch (e) { /* no AudioContext in headless: the engine instance is still there */ }
    await wait(300);
    check(errors.length === 0, `no script errors: ${errors.join(' | ') || 'none'}`);
    check(document.body.classList.contains('web'), 'UI knows it runs in the web build (body.web)');
    check(typeof EIGHTBALL_WASM_B64 === 'string' && EIGHTBALL_WASM_B64.length > 100000, `wasm inlined (${Math.round((EIGHTBALL_WASM_B64 || '').length * 3 / 4 / 1024)} KB)`);
    check(typeof FACTORY_JSON === 'object' && FACTORY_JSON.categories.length === 12, `factory JSON inlined (${FACTORY_JSON.categories.length} categories)`);
    check(web.factoryCount >= 1000, `${web.factoryCount} factory presets resolved`);
    const tabs = $$('.cat-tab');
    const countText = $('#preset-count').textContent;
    const total = Number((countText.match(/^(\d+) presets/) || [])[1] || 0);
    check(tabs.length >= 12 && total >= 1000, `preset browser populated (${tabs.length} tabs, '${countText}')`);
    check($('#preset-name').textContent === 'Init', `starts on Init ('${$('#preset-name').textContent}')`);
    check(/Web|audio/i.test($('#audio-info').textContent), `audio status shown ('${$('#audio-info').textContent}')`);
    check($('#bpm-input') && !$('#bpm-input').readOnly, 'tempo is editable in the web build');

    // the engine: Init renders a tone
    const a = web.render(60, 48000 / 2);
    check(rms(a) > 0.01 && peak(a) <= 1.0, `Init renders a note (rms ${rms(a).toFixed(3)}, peak ${peak(a).toFixed(3)})`);
    check(web.render(60, 0).length === 0, 'zero-frame render is fine');

    // a few factory presets through the full note, including a wobble (synced LFO + mod matrix) and a drum
    const names = ['Grand Piano', 'Wob 1/4 Sine LP', 'Kick 808 Deep', 'Chip Lead'];
    const all = FACTORY_JSON.categories.flatMap(c => c.presets.map(p => p.name));
    for (const n of names) {
      const i = all.indexOf(n);
      if (i < 0) { check(false, `preset '${n}' exists`); continue; }
      web.loadFactory(i);
      await wait(50);
      const note = /Kick/.test(n) ? 48 : /Wob/.test(n) ? 36 : 60;
      const b = web.render(note, 48000 / 2);
      check(rms(b) > 0.003 && peak(b) <= 1.0 && !Array.from(b).some(v => !isFinite(v)), `'${n}' renders (rms ${rms(b).toFixed(3)}, peak ${peak(b).toFixed(3)})`);
      check($('#preset-name').textContent === n, `UI shows '${n}'`);
    }

    // the names are unique per category
    const seen = new Set();
    let dup = 0;
    for (const c of FACTORY_JSON.categories) for (const p of c.presets) { const k = `${c.name}/${p.name}`; if (seen.has(k)) dup++; seen.add(k); }
    check(dup === 0, `no duplicate preset names (${seen.size} unique)`);

    // A/B: toggling swaps the sound and the UI label
    web.loadFactory(all.indexOf('Grand Piano'));
    await wait(50);
    window.__JUCE__.backend.emitEvent('abCopy', {});
    web.loadFactory(all.indexOf('Kick 808 Deep'));
    await wait(50);
    window.__JUCE__.backend.emitEvent('abToggle', {});
    await wait(50);
    check($('#preset-name').textContent === 'Grand Piano', `A/B toggle brings back the other sound ('${$('#preset-name').textContent}')`);

    // user presets in this browser: save, find, delete
    window.__JUCE__.backend.emitEvent('savePreset', { name: 'Web Test Sound', overwrite: true });
    await wait(100);
    const search = $('#preset-search');
    search.value = 'web test sound';
    search.dispatchEvent(new Event('input'));
    check($$('.preset-btn').some(c => /Web Test Sound/.test(c.textContent)), 'a saved preset appears in the browser (search finds it)');
    check($('#preset-name').textContent === 'Web Test Sound', `the saved preset is current ('${$('#preset-name').textContent}')`);
    window.__JUCE__.backend.emitEvent('deletePreset', { id: 'local:Web Test Sound' });
    await wait(100);
    search.dispatchEvent(new Event('input'));
    check(!$$('.preset-btn').some(c => /Web Test Sound/.test(c.textContent)), 'deleting removes it');
    search.value = '';
    search.dispatchEvent(new Event('input'));

    check(errors.length === 0, `still no script errors: ${errors.join(' | ') || 'none'}`);
    finish();
  }
  const start = () => run().catch((e) => { check(false, `test script threw: ${e && e.stack || e}`); finish(); });
  if (document.readyState === 'complete') start(); else window.addEventListener('load', start);
})();
