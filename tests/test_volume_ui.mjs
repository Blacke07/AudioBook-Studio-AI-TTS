import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../app/web/app.js', import.meta.url), 'utf8');
const volume = source.slice(source.indexOf('let volumeFilter ='), source.indexOf('/* ---------- chapter editor ---------- */'));
const esc = source.split('\n').find(line => line.startsWith('const esc ='));

function page(chapters = [chapter('one', 'generated'), chapter('two', 'new')]) {
  const elements = new Map(), calls = [];
  let boxes = [], rows = [];
  const element = (selector, parent) => {
    if (parent) return parent.box;
    if (!elements.has(selector)) elements.set(selector, {});
    return elements.get(selector);
  };
  const sandbox = {
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
    scheduleRefresh:()=>{}, toast:()=>{}, pollNow:()=>{}, guard:action=>action(),
    api:async (path, options) => {
      calls.push([path, options]);
      return {chapters,volume:{source:'demo'},render_factor:1,video_enabled:false};
    },
  };
  vm.runInNewContext(esc + '\n' + volume, sandbox);
  return {sandbox, element, calls, get boxes() {return boxes;}, get rows() {return rows;},
    async render() {await sandbox.viewVolume('Demo');},
    async select(stems, filter='all') {
      sandbox.stems = stems; sandbox.filter = filter;
      vm.runInNewContext('selected=new Set(stems); volumeFilter=filter;', sandbox);
      await sandbox.viewVolume('Demo');
    }};
}

function chapter(stem, state) {
  return {stem, title:stem, state, estimated_seconds:1, video:{state:'missing',label:'No video'}};
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
