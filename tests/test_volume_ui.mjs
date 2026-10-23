import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../app/web/app.js', import.meta.url), 'utf8');
const volume = source.slice(source.indexOf('let volumeFilter ='), source.indexOf('/* ---------- chapter editor ---------- */'));
const workflow = readFileSync(new URL('../app/web/workflow.js', import.meta.url), 'utf8');
const esc = source.split('\n').find(line => line.startsWith('const esc ='));

function page(chapters = [chapter('one', 'generated'), chapter('two', 'new')]) {
  const elements = new Map(), calls = [];
  let boxes = [], rows = [];
  const element = (selector, parent) => {
    if (parent) return parent.box;
    // Like the browser: an id that the page did not render is null, not a harmless stand-in.
    if (selector.startsWith('#') && !sandbox.view.html.includes(`id="${selector.slice(1)}"`)) return null;
    if (!elements.has(selector)) elements.set(selector, {});
    return elements.get(selector);
  };
  const sandbox = {
    document: {addEventListener:()=>{}, querySelectorAll:()=>[]},
    window: {addEventListener:()=>{}},
    view: {set innerHTML(html) {
      this.html = html;
      elements.clear();
      const checked = [...html.matchAll(/data-select="([^"]+)"[^>]*>/g)];
      boxes = checked.map(([tag, stem]) => ({dataset:{select:stem}, checked:tag.includes(' checked'),
        click() {this.checked = !this.checked; this.onchange();}}));
      rows = boxes.map(box => ({dataset:{stem:box.dataset.select}, box}));
    }},
    $: element, $$: selector => selector === '[data-select]' ? boxes : selector === 'tr.clickable' ? rows : [],
    location:{hash:'#/volume/Demo'}, icon:()=>'', duration:String, chip:()=>'',
    STATE_COLOR:{}, STATE_LABEL:{}, STATE_CLASS:{},
    VoiceRules:{mount:async()=>{}},
    scheduleRefresh:()=>{}, toast:()=>{}, pollNow:()=>{}, guard:action=>action(), modal:async()=>true,
    api:async (path, options) => {
      calls.push([path, options]);
      return {chapters,volume:{source:'demo'},render_factor:1,video_enabled:false};
    },
  };
  vm.runInNewContext(esc + '\n' + workflow + '\n' + volume, sandbox);
  return {sandbox, element, calls, get boxes() {return boxes;}, get rows() {return rows;},
    async render() {await sandbox.viewVolume('Demo');},
    async select(stems, filter='all') {
      sandbox.stems = stems; sandbox.filter = filter;
      vm.runInNewContext('selected=new Set(stems); volumeFilter=filter;', sandbox);
      await sandbox.viewVolume('Demo');
    }};
}

function chapter(stem, state) {
  return {stem, title:stem, state, can_generate:['analyzed','generated','exported'].includes(state), can_export:['generated','exported'].includes(state), estimated_seconds:1, video:{state:'missing',label:'No video'}};
}

test('select-all stays checked after redraw and a second click deselects the batch', async () => {
  const p = page();
  await p.render();
  assert.equal(p.element('#all').checked, false);
  p.element('#all').onchange({target:{checked:true}});
  await p.render();
  assert.equal(p.element('#all').checked, true);
  assert.equal(p.element('#all').indeterminate, false);
  p.element('#all').onchange({target:{checked:false}});
  await p.render();
  assert.equal(p.element('#all').checked, false);
  assert.ok(p.boxes.every(box => !box.checked));
});

test('partial and filtered selection preserves hidden chapters in the batch', async () => {
  const p = page();
  await p.select(['two']);
  assert.equal(p.element('#all').indeterminate, true);
  await p.select(['one','two'], 'generated');
  assert.equal(p.element('#all').checked, true);
  p.element('#all').onchange({target:{checked:false}});
  await p.render();
  await p.element('#run-render').onclick({currentTarget:{}});
  const request = p.calls.find(([path]) => path === '/api/run')[1].body;
  assert.deepEqual(Array.from(request.stems), ['two']);
  assert.equal(request.volume, 'Demo');
  assert.deepEqual(Array.from(request.steps), ['render']);
});

test('Analyze Text can run again after the first analysis, with confirmation', async () => {
  const chapters = [chapter('one', 'new')];
  const p = page(chapters), prompts = [];
  p.sandbox.modal = async (...args) => {prompts.push(args); return true;};
  await p.render();
  await p.element('#run-analyze').onclick({currentTarget:{}});
  assert.equal(prompts.length, 0);
  chapters[0].state = 'analyzed';
  await p.render();
  await p.element('#run-analyze').onclick({currentTarget:{}});
  const jobs = p.calls.filter(([path]) => path === '/api/run').map(([, options]) => options.body);
  assert.equal(jobs.length, 2);
  assert.ok(jobs.every(job => job.force === true && job.automatic === false));
  assert.equal(prompts.length, 1);
  assert.match(prompts[0][1], /speaker assignments/i);
});

test('canceling repeated volume analysis does not queue a job', async () => {
  const p = page([chapter('one', 'generated')]);
  p.sandbox.modal = async () => false;
  await p.render();
  await p.element('#run-analyze').onclick({currentTarget:{}});
  assert.equal(p.calls.filter(([path]) => path === '/api/run').length, 0);
});

test('manual analysis respects selection and automatic processing keeps existing analysis', async () => {
  const p = page();
  p.sandbox.modal = async () => {throw new Error('The selected chapter has no analysis to replace.');};
  await p.select(['two']);
  await p.element('#run-analyze').onclick({currentTarget:{}});
  await p.element('#run-all').onclick({currentTarget:{}});
  const jobs = p.calls.filter(([path]) => path === '/api/run').map(([, options]) => options.body);
  assert.deepEqual(Array.from(jobs[0].stems), ['two']);
  assert.equal(jobs[0].force, true);
  assert.notEqual(jobs[1].force, true);
  assert.equal(jobs[1].automatic, true);
});

test('individual toggles update the master checkbox, including the empty filter', async () => {
  const p = page();
  await p.render();
  p.boxes[0].click();
  await p.render();
  assert.equal(p.element('#all').indeterminate, true);
  p.boxes[1].click();
  await p.render();
  assert.equal(p.element('#all').checked, true);
  await p.select([], 'error');
  assert.match(p.sandbox.view.html, /id="all"[^>]*disabled/);
  assert.equal(p.element('#all').checked, false);
  assert.equal(p.element('#all').indeterminate, false);
});

test('selection cell does not navigate; native label activation is not toggled twice', async () => {
  const p = page();
  await p.render();
  const row = p.rows[0];
  row.onclick({target:{closest:selector => selector === 'td.check' ? row : null}});
  await p.render();
  assert.equal(p.boxes[0].checked, true);
  assert.equal(p.sandbox.location.hash, '#/volume/Demo');
  for (const target of ['input','label']) {
    p.rows[0].onclick({target:{closest:selector => selector === 'td.check' ? p.rows[0] :
      selector === 'input, label' ? target : null}});
    assert.equal(p.boxes[0].checked, true);
    assert.equal(p.sandbox.location.hash, '#/volume/Demo');
  }
  p.rows[0].onclick({target:{closest:()=>null}});
  assert.equal(p.sandbox.location.hash, '#/chapter/Demo/one');
});


test('workflow blocks later steps for a mixed batch and enables them for a ready selection', async () => {
  const p = page();
  await p.render();
  assert.match(p.sandbox.view.html, /id="run-render" disabled/);
  assert.match(p.sandbox.view.html, /id="run-video" disabled/);
  await p.select(['one']);
  assert.doesNotMatch(p.sandbox.view.html, /id="run-render" disabled/);
  assert.doesNotMatch(p.sandbox.view.html, /id="run-video" disabled/);
  assert.match(p.sandbox.view.html, /id="youtube" disabled/);
});

test('every control the volume page wires up is rendered, including whole-volume export', async () => {
  const p = page([chapter('one', 'generated'), chapter('two', 'generated')]);
  await p.render();  // would throw on a missing id, as the browser did with "null"
  assert.match(p.sandbox.view.html, /id="run-volume"/);
  assert.doesNotMatch(p.sandbox.view.html, /id="run-volume" disabled/);
  await p.select(['one']);  // a selection does not limit whole-volume export
  assert.doesNotMatch(p.sandbox.view.html, /id="run-volume" disabled/);
  const mixed = page();
  await mixed.render();
  assert.match(mixed.sandbox.view.html, /id="run-volume" disabled/);
  assert.match(mixed.sandbox.view.html,
    /id="run-volume" disabled title="Generate current audio for every chapter in this volume\."/);
});

test('whole-volume export sits in the volume header, not in the audio menu', async () => {
  const p = page([chapter('one', 'generated'), chapter('two', 'generated')]);
  await p.render();
  const html = p.sandbox.view.html;
  const head = html.slice(html.indexOf('class="page-head"'), html.indexOf('class="card"'));
  assert.match(head, /id="run-volume"/);
  assert.match(head, /id="open-source"/);
  assert.match(head, /id="open-export"/);
  const audioMenu = html.slice(html.indexOf('data-workflow="audio"'), html.indexOf('data-workflow="video"'));
  assert.match(audioMenu, /id="run-render"/);
  assert.match(audioMenu, /id="run-export"/);
  assert.doesNotMatch(audioMenu, /id="run-volume"/);
  await p.select(['one']);
  await p.element('#run-volume').onclick({currentTarget:{}});
  const job = p.calls.find(([path]) => path === '/api/run')[1].body;
  assert.deepEqual([...job.stems], ['one', 'two']);
});

test('the back control follows the logical parent page, not history', async () => {
  const p = page();
  await p.render();
  const parent = (hash) => {
    const route = p.sandbox.parentRoute(hash);
    return route && {href: route.href, label: route.label};
  };
  assert.deepEqual(parent('#/volume/Demo'), {href: '#/', label: 'Back to volumes'});
  assert.deepEqual(parent('#/chapter/Demo/one'), {href: '#/volume/Demo', label: 'Back to Demo'});
  assert.deepEqual(parent('#/chapter/Vol%202/ch%201'), {href: '#/volume/Vol%202', label: 'Back to Vol 2'});
  for (const top of ['#/', '#/characters', '#/narrator', '#/settings', '#/project']) {
    assert.equal(parent(top), null);
  }
  assert.match(p.sandbox.view.html,
    /<a class="back" id="back" href="#\/" aria-label="Back to volumes"/);
});
