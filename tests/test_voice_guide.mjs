import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import vm from 'node:vm';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const source = readFileSync(path.join(root, 'app/web/app.js'), 'utf8');
const helper = source.slice(source.indexOf('async function showVoiceGuide('), source.indexOf('\nlet characterData ='));
const esc = source.split('\n').find(line => line.startsWith('const esc ='));
const guide = readFileSync(path.join(root, 'app/web/guides/Voice Personality Guide.md'), 'utf8');
const example = readFileSync(path.join(root, 'app/web/guides/Voice Sheet Example.md'), 'utf8');

function context(text, action='copy', ok=true) {
  const observed = { requests: [], copies: [], dialogs: [], toasts: [] };
  const sandbox = {
    fetch: async (...args) => { observed.requests.push(args); return { ok, status: ok ? 200 : 404, text: async () => text }; },
    navigator: { clipboard: { writeText: async text => observed.copies.push(text) } },
    modal: async (...args) => { observed.dialogs.push(args); return action; },
    toast: message => observed.toasts.push(message), icon: () => '',
  };
  vm.runInNewContext(esc + '\n' + helper, sandbox);
  return { observed, show: sandbox.showVoiceGuide };
}

test('copy sends only the complete prompt, without guide instructions or data mutations', async () => {
  const {observed, show} = context(guide);
  await show();
  const expected = guide.match(/```text\r?\n([\s\S]*?)\r?\n```/)[1];
  assert.deepEqual(observed.copies, [expected]);
  assert.match(expected, /^I need VOICE SHEETS/);
  assert.match(expected, /Three real lines from the book/);
  assert.match(expected, /Do not edit the book, application settings or approved voices/);
  assert.equal(observed.requests.length, 1);
  assert.equal(observed.requests[0].length, 1); // Fetch URL only: no POST, PUT, body or import.
  assert.equal(decodeURIComponent(observed.requests[0][0]), '/guides/Voice Personality Guide.md');
  assert.match(observed.dialogs[0][1], /textarea readonly/);
  assert.match(observed.dialogs[0][1], /download=/);
});

test('example is presented and copied intact; closing copies nothing', async () => {
  const copy = context(example); await copy.show(true);
  assert.deepEqual(copy.observed.copies, [example]);
  assert.equal(decodeURIComponent(copy.observed.requests[0][0]), '/guides/Voice Sheet Example.md');
  const close = context(guide, null); await close.show();
  assert.deepEqual(close.observed.copies, []);
});

test('missing or incomplete guide fails explicitly without copying', async () => {
  const missing = context('', 'copy', false);
  await assert.rejects(missing.show(), /404/);
  assert.deepEqual(missing.observed.copies, []);
  const malformed = context('Incomplete document');
  await assert.rejects(malformed.show(), /complete prompt is missing/);
  assert.deepEqual(malformed.observed.copies, []);
});

test('document content is escaped before display, including closing textarea tags', async () => {
  const {observed, show} = context('</textarea><script>unsafe()</script>');
  await show(true);
  assert.doesNotMatch(observed.dialogs[0][1], /<script>/);
  assert.match(observed.dialogs[0][1], /&lt;\/textarea&gt;&lt;script&gt;/);
});
