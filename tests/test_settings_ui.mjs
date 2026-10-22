import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../app/web/app.js', import.meta.url), 'utf8');
const settings = source.slice(source.indexOf('async function viewSettings()'), source.indexOf('/* ---------- project transfer ---------- */'));
const line = (prefix) => source.split('\n').find(entry => entry.startsWith(prefix));

function data() {
  return {
    ffmpeg: true,
    model_profile: {label: 'Full', gemma: 'gemma-3-4b'},
    formats: {chapter: {mp3: 'MP3', m4a: 'M4A', wav: 'WAV'}, volume: {m4b: 'M4B', mp3: 'MP3'}},
    video_factor: 0,
    settings: {
      author: 'A. Author', export_format: 'mp3', export_quality: 'standard', volume_format: 'm4b',
      multi_voice: true, announce_titles: true, speech_tags: 'omit_fixed', dialogue_pause: 0.5,
      unclear_policy: 'wait',
      video: {enabled: false, width: 1920, footer: '', before: 1, after: 1, show_omitted: false, progress_bar: false},
    },
  };
}

const capabilities = {
  h264: {available: true, encoder: 'h264_nvenc', reason: 'NVIDIA NVENC'},
  h265: {available: true, encoder: 'hevc_nvenc', reason: 'NVIDIA NVENC'},
  av1: {available: false, encoder: null, reason: 'NVENC unavailable'},
};

function page(payload = data(), codecRequest = Promise.resolve({codecs: capabilities})) {
  const elements = new Map(), calls = [];
  const view = {innerHTML: ''};
  const element = (selector) => {
    // Like the browser: an id the page did not render is null, not a harmless stand-in.
    const id = /^#([A-Za-z0-9_-]+)/.exec(selector)?.[1];
    if (id && !view.innerHTML.includes(`id="${id}"`)) return null;
    if (!elements.has(selector)) elements.set(selector, {checked: false, value: '', dataset: {}, style: {},
      classList: {toggle() {}, add() {}, remove() {}}});
    return elements.get(selector);
  };
  const sandbox = {
    view, document: {addEventListener() {}, querySelectorAll: () => []},
    $: element, $$: () => [],
    icon: (name) => `<svg class="icon" data-icon="${name}"></svg>`,
    guard: (action) => action(), toast: () => {},
    api: async (path, options = {}) => {
      if (path === '/api/video/codecs') return codecRequest;
      if (options.method === 'PUT') calls.push([path, options]);
      return payload;
    },
  };
  vm.runInNewContext([line('const esc ='), settings].join('\n'), sandbox);
  return {sandbox, view, element, calls};
}

test('settings page renders every control its save handler reads', async () => {
  const p = page();
  await p.sandbox.viewSettings();  // would throw on a missing id, as the browser did with "null"
  const html = p.view.innerHTML;
  for (const id of ['save', 'quality', 'volume-format', 'author', 'multi', 'announce', 'tags', 'pause',
    'pause-value', 'video-enabled', 'video-resolution', 'video-footer', 'video-before', 'video-after',
    'video-omitted', 'video-progress', 'video-codec', 'video-codec-help']) {
    assert.ok(html.includes(`id="${id}"`), `the settings page no longer renders #${id}`);
  }
});

test('settings page keeps Audio and Video side by side, Reading below, all collapsible', async () => {
  const p = page();
  await p.sandbox.viewSettings();
  const html = p.view.innerHTML;
  const sections = [...html.matchAll(/<details class="card stack settings-section"[^>]*><summary><h3><svg[^>]*data-icon="([^"]+)"><\/svg> ([A-Za-z]+)<\/h3><\/summary>/g)]
    .map(([, icon, title]) => [`${icon}`, title]);
  assert.deepEqual(sections, [['sound', 'Audio'], ['video', 'Video'], ['book', 'Reading']]);
  assert.equal((html.match(/settings-section"[^>]*\sopen[\s>]/g) || []).length, 3);
  assert.ok(html.indexOf('Audio') < html.indexOf('Video'));
  assert.ok(html.indexOf('Video') < html.indexOf('Reading'));
});

test('codec checks are asynchronous, show a pending state and preserve the saved choice', async () => {
  let finish;
  const pending = new Promise(resolve => { finish = resolve; });
  const payload = data(); payload.settings.video.codec = 'h265';
  const p = page(payload, pending);
  await p.sandbox.viewSettings();
  assert.match(p.view.innerHTML, /id="video-codec" disabled/);
  assert.match(p.view.innerHTML, /Checking…/);
  assert.ok(p.element('#save').onclick, 'saving is wired before probes finish');
  finish({codecs: capabilities});
  await new Promise(resolve => setImmediate(resolve));
  const select = p.element('#video-codec');
  assert.equal(select.disabled, false);
  assert.match(select.innerHTML, /value="h265" selected\s*>H\.265/);
  assert.match(select.innerHTML, /value="av1"\s+disabled>AV1 · NVENC unavailable/);
});

test('a failed check leaves the codec disabled with an explicit retry message', async () => {
  const p = page(data(), Promise.reject(new Error('not available')));
  await p.sandbox.viewSettings();
  await new Promise(resolve => setImmediate(resolve));
  assert.match(p.element('#video-codec-help').textContent, /Encoder checks failed/);
});

test('codec options reflect actual session capabilities instead of placeholders', async () => {
  const p = page();
  await p.sandbox.viewSettings();
  await new Promise(resolve => setImmediate(resolve));
  assert.match(p.element('#video-codec').innerHTML, /value="h264" selected\s*>H\.264 · NVENC/);
  assert.doesNotMatch(settings, /not connected yet|visual only/);
  assert.match(p.element('#video-codec-help').textContent, /Encoded with NVIDIA NVENC when available\./);
});

test('saving sends the chosen codec and preserves the other settings', async () => {
  const p = page();
  await p.sandbox.viewSettings();
  const el = p.element;
  el('#video-enabled').checked = true;
  el('#video-resolution').value = '1280';
  el('#video-before').value = '2';
  el('#video-after').value = '3';
  el('#video-omitted').checked = true;
  el('#video-progress').checked = true;
  el('#video-footer').value = 'Footer';
  el('#video-codec').value = 'h265';
  el('input[name=format]:checked').value = 'm4a';
  el('#quality .on').dataset.q = 'high';
  el('#volume-format').value = 'mp3';
  el('#author').value = 'Me';
  el('#multi').checked = false;
  el('#announce').checked = false;
  el('#tags').checked = true;
  el('#pause').value = '0.8';
  el('input[name=policy]:checked').value = 'narrator';
  const button = el('#save');
  await button.onclick({currentTarget: button});
  assert.equal(p.calls.length, 1);
  const [path, options] = p.calls[0];
  assert.equal(path, '/api/settings');
  assert.equal(options.method, 'PUT');
  const saved = JSON.parse(JSON.stringify(options.body.settings));
  assert.deepEqual(saved.video, {enabled: true, width: 1280, height: 720, before: 2, after: 3,
    show_omitted: true, progress_bar: true, footer: 'Footer', codec: 'h265'});
  assert.equal(saved.export_format, 'm4a');
  assert.equal(saved.export_quality, 'high');
  assert.equal(saved.volume_format, 'mp3');
  assert.equal(saved.author, 'Me');
  assert.equal(saved.multi_voice, false);
  assert.equal(saved.announce_titles, false);
  assert.equal(saved.speech_tags, 'omit_fixed');
  assert.equal(saved.dialogue_pause, 0.8);
  assert.equal(saved.unclear_policy, 'narrator');
  assert.ok(!('codec' in saved));
});
