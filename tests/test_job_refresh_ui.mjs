import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../app/web/app.js', import.meta.url), 'utf8');
const region = source.slice(source.indexOf('let workerState ='), source.indexOf('function renderWorker()'));

function page({busy = false} = {}) {
  const statuses = [], refreshes = [];
  const sandbox = {
    api: async () => statuses.shift() || {running: false, done: 0, phase: '', log: []},
    renderWorker: () => {},
    // 1200 ms is the debounce of a page refresh; every other timer is the status poll itself.
    setTimeout: (callback, ms) => { if (ms === 1200) refreshes.push(callback); }, clearTimeout: () => {},
    view: {}, document: {querySelector: () => (busy ? {} : null), activeElement: null},
    $$: () => [], CharacterRegistry: {dirty: () => false},
  };
  vm.createContext(sandbox);
  vm.runInContext(region + ';this.poll=pollWorker;this.schedule=scheduleRefresh;this.busy=userIsBusy;', sandbox);
  return {sandbox, statuses, refreshes};
}

const running = (done) => ({running: true, done, phase: 'Generating audio', log: ['a']});
const idle = () => ({running: false, done: 0, phase: '', log: ['a', 'b']});

test('a view that refreshes only when the queue ends is not reloaded during progress', async () => {
  const {sandbox, statuses, refreshes} = page();
  let reloads = 0;
  sandbox.schedule(() => reloads++, true);
  statuses.push(running(0), running(1));
  await sandbox.poll(); await sandbox.poll();
  assert.equal(refreshes.length, 0, 'Progress alone must not reload the characters');
  statuses.push(idle());
  await sandbox.poll();
  assert.equal(refreshes.length, 1, 'The end of the queue reloads them once');
  refreshes[0]();
  assert.equal(reloads, 1);
});

test('a view that follows progress is refreshed while the queue runs and when it ends', async () => {
  const {sandbox, statuses, refreshes} = page();
  sandbox.schedule(() => {});
  statuses.push(running(0), running(1), idle());
  for (let step = 0; step < 3; step++) await sandbox.poll();
  assert.equal(refreshes.length, 3);
});

test('an open dialog, a focused field or playing audio keeps the page from refreshing under the author', () => {
  assert.equal(page().sandbox.busy(), false);
  assert.equal(page({busy: true}).sandbox.busy(), true);
  const typing = page().sandbox;
  typing.document.activeElement = {tagName: 'TEXTAREA'};
  assert.equal(typing.busy(), true);
  const playing = page().sandbox;
  playing.$$ = () => [{paused: false}];
  assert.equal(playing.busy(), true);
});
