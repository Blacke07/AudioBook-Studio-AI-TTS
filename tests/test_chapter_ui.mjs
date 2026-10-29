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

test('Gemma emotion proposals join the review queue; a speaker problem on the same line is named first', () => {
  const rows = [{speaker: 'Ada', text: 'a', emotion_source: 'ai'}, {speaker: 'Unassigned', text: 'b', emotion_source: 'ai'},
    {speaker: 'Ada', text: 'c', emotion_source: 'manual'}];
  assert.deepEqual(reviewQueue(rows).map(item => [item.index, item.why]), [[0, 'Emotion'], [1, 'Unassigned']]);
});

test('each line has an emotion menu that saves the author choice and explains a missing take', () => {
  assert.match(source, /<select data-emotion="\$\{index\}" aria-label="Emotion of this line"/);
  assert.match(source, /api\("\/api\/chapter\/delivery", \{ method: "PUT", body: \{ volume, stem, row: index, emotion, source_hash: data\.source_hash \} \}\)/);
  assert.match(source, /data-emotion-keep="\$\{index\}"/);
  assert.match(source, /line\.emotion_missing \? `<span class="chip warn"/);
  assert.match(source, /Some emotions use the neutral take\./);
  assert.match(style, /\.emotion-pick\.quiet \{ opacity:\.45;/);
  assert.match(style, /prefers-reduced-motion: reduce\) \{ \.emotion-pick\.quiet \{ transition:none; \} \}/);
});

test('a fixed voice lists every emotion with its approved take or the neutral fallback', () => {
  const {emotionTakesHtml} = vm.runInNewContext(`const esc = s => String(s); const icon = () => ''; const fieldHelp = () => '';
    ${extract('emotionTakesHtml')}\n({emotionTakesHtml})`);
  const choices = [{key: 'neutral', label: 'Neutral'}, {key: 'angry', label: 'Angry'}, {key: 'tender', label: 'Tender'}];
  const html = emotionTakesHtml({takes: {angry: {url: '/a.wav'}}}, {tender: 'Come closer.'}, choices);
  assert.match(html, /Emotion takes · <span data-emotion-count>1\/2<\/span>/);
  assert.doesNotMatch(html, /data-emotion-take="neutral"/);
  assert.match(html, /data-emotion-take="angry"[\s\S]*Approved[\s\S]*src="\/a\.wav"[\s\S]*data-emotion-remove/);
  assert.match(html, /data-emotion-take="tender"[\s\S]*Neutral take used[\s\S]*Come closer\./);
  assert.match(source, /api\("\/api\/voices\/fix", \{ method: "POST", body: \{ role, path: take\.path, text: take\.text, emotion,/);
  assert.match(source, /bindEmotionTakes\(\$\("\.fixed-box"\), "Narrator",/);
  assert.doesNotMatch(source, /bindEmotionTakes\(\$\("\.fixed-box"\), "Narrator", viewNarrator\)/);
});
