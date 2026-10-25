import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../app/web/app.js', import.meta.url), 'utf8');
const style = readFileSync(new URL('../app/web/style.css', import.meta.url), 'utf8');
const extract = name => source.match(new RegExp(`function ${name}[\\s\\S]*?\\n}\\n`))[0];
const {nextToResolve, reviewQueue} = vm.runInNewContext(
  `const UNASSIGNED = 'Unassigned';\n${extract('nextToResolve')}\n${extract('reviewQueue')}\n({nextToResolve, reviewQueue})`);
const lines = speakers => speakers.map(speaker => ({speaker, text: speaker}));

test('the next unresolved line follows the one just resolved', () => {
  const all = lines(['Ada', 'Narrator', 'Unassigned', 'Ada', 'Unassigned']);
  assert.equal(nextToResolve(all, 0), 2);
  assert.equal(nextToResolve(all, 2), 4);
});

test('after the last open line it returns to the first one, and is null when none remain', () => {
  assert.equal(nextToResolve(lines(['Unassigned', 'Ada', 'Ada']), 2), 0);
  assert.equal(nextToResolve(lines(['Ada', 'Narrator', 'Morgan']), 1), null);
});

test('the review queue lists unassigned, context and pacing lines in reading order', () => {
  const rows = [{speaker: 'Ada', text: 'a'}, {speaker: 'Unassigned', text: 'b'},
    {speaker: 'Ada', text: 'c', basis: 'context'}, {speaker: 'Narrator', text: 'd', flagged: true},
    {speaker: 'Morgan', text: 'e', basis: 'explicit'}];
  assert.deepEqual(reviewQueue(rows).map(item => [item.index, item.why]),
    [[1, 'Unassigned'], [2, 'Context'], [3, 'Pacing']]);
  assert.deepEqual(reviewQueue(rows.slice(0, 1)), []);
});

test('resolving a speaker asks before moving on and shows a resolved sign at the end', () => {
  assert.match(source, /lines\[index\]\.speaker === UNASSIGNED \? \{ prompt: index \} : \{\}/);
  assert.match(source, /Go to the next one\?/);
  assert.match(source, /All speakers resolved/);
  assert.match(source, /queue-done">\$\{icon\("check"\)\} Resolved/);
  assert.match(source, /prefers-reduced-motion: reduce/);
  assert.match(source, /target\.focus\(\{ preventScroll: true, focusVisible: true \}\)/);
});

test('the sticky menu toggle is remembered and guarded against blocked storage', () => {
  assert.match(source, /id="pin-head" aria-pressed="\$\{pinned\}"/);
  assert.match(source, /try \{ return localStorage\.getItem\("chapterMenuSticky"\)/);
  assert.match(source, /classList\.toggle\("sticky", on\)/);
  assert.match(style, /\.page-head\.sticky \{ position:sticky; top:0;/);
});

test('the review queue only takes the free space on wide windows', () => {
  assert.match(style, /\.review-queue \{ display:none; \}/);
  assert.match(style, /@media \(min-width:1780px\) \{\s*\.review-queue \{ display:block; position:fixed;/);
});

test('the chapter table has audio, video and listen buttons and chips that explain themselves', () => {
  assert.match(source, /outdated: "Audio outdated"/);
  assert.match(source, /c\.state === "outdated" \? c\.outdated_reason : ""/);
  assert.match(source, /warn has-reason/);
  for (const part of ['data-make="audio"', 'data-make="video"', 'data-play="${c.audio']) {
    assert.ok(source.includes(part), part);
  }
  assert.match(source, /\["render", "export"\] : \["video"\]/);
  assert.match(style, /\.chip\.has-reason \{ cursor:help; \}/);
});
