import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../app/web/character-registry.js', import.meta.url), 'utf8');
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
const stored = {};

function stub() {
  return {dataset:{}, classList:{add(){},remove(){},toggle(){},contains(){return false}}, addEventListener(){},
          querySelector(){return stub()}, querySelectorAll(){return []}, focus(){},
          getBoundingClientRect(){return {top:0,height:40}}, setAttribute(){}, remove(){}};
}

function sandbox() {
  const view = {innerHTML:'', querySelectorAll(){return []}, querySelector(){return null}};
  const api = {view, esc, icon:()=>'', $:()=>stub(), $$:()=>[], modal:async()=>null, api:async()=>{},
    toast(){}, guard:(action)=>action(), sessionStorage:{getItem:k=>stored[k]??null,setItem(k,v){stored[k]=v},removeItem(k){delete stored[k]}},
    location:{hash:''}, document:{addEventListener(){}, querySelectorAll(){return []}},
    window:{addEventListener(){}}, crypto:{randomUUID:()=>'generated-id'}, setTimeout, clearTimeout};
  vm.runInNewContext(source + '\n;globalThis.__registry = CharacterRegistry;', api);
  return api;
}

function fixture() {
  return {document:{version:2, characters:[
      {name:'Ada',aliases:['the keeper'],gender:'female',note:'',model:'same as narrator',custom_voice:'Ryan',voice_design:'',seed:1,read_as:'Narrator'},
      {name:'Morgan',aliases:[],gender:'male',note:'',model:'same as narrator',custom_voice:'Aiden',voice_design:'',seed:2},
      {name:'Bela',aliases:[],gender:'female',note:'',model:'same as narrator',custom_voice:'Vivian',voice_design:'',seed:3}],
    organization:{categories:[{id:'uncategorized',name:'Uncategorized',description:'',voice:'own'},
                              {id:'guests',name:'Guests',description:'',voice:'Narrator'}],
      characters:{Ada:{category:'uncategorized',status:'approved',label:'Ada',reason:'',volumes:['volume-one']},
                  Morgan:{category:'guests',status:'provisional',label:'Morgan',reason:'New speaker',contexts:[],labels:[]},
                  Bela:{category:'uncategorized',status:'approved',label:'Bela',reason:''}},
      allow_provisional:false, contexts:[]}},
    revision:'rev-1', reading:{Ada:'Narrator',Morgan:'Morgan',Bela:'Bela'},
    fixed:{Ada:true}, volumes:[{id:'volume-one',name:'Volume One'},{id:'volume-two',name:'Volume Two'}]};
}

test('Quick view shows volume membership between category and reading voice', () => {
  const s = sandbox(), registry = s.__registry;
  registry.state = fixture();
  registry.saved = JSON.stringify(registry.state.document);
  registry.draw();
  const html = s.view.innerHTML;
  assert.ok(html.indexOf('<th>Category</th>') < html.indexOf('<th>Volumes</th>'));
  assert.ok(html.indexOf('<th>Volumes</th>') < html.indexOf('<th>Reading voice</th>'));
  assert.ok(html.indexOf('<th>Reading voice</th>') < html.indexOf('<th>Status</th>'));
  assert.ok(html.indexOf('<th>Status</th>') < html.indexOf('<th>Actions</th>'));
  assert.match(html, /Priority 1 · 2 characters/);
  assert.match(html, /Priority 2 · 1 character/);
  assert.match(html, /data-volumes-edit="Ada"/);
  assert.match(html, /<span class="chip volume-chip" title="Volume One">Volume One<\/span>/);
  assert.match(html, /All volumes/);
  assert.match(html, /data-row-menu="Ada"/);
  assert.match(html, /data-row-menu="Morgan"/);
  assert.doesNotMatch(html, /registry-actions row-actions/);
  assert.match(html, /id="registry-assign-volumes"/);
  assert.match(html, /id="registry-contexts"/);
});

test('volume filter shows explicit members and unscoped characters only', () => {
  const registry = sandbox().__registry;
  registry.state = fixture();
  registry.volumeFilter = 'volume-two';
  assert.equal(registry.matches({name:'Ada',aliases:[]}), false);
  assert.equal(registry.matches({name:'Morgan',aliases:[]}), true);
  registry.volumeFilter = 'volume-one';
  assert.equal(registry.matches({name:'Ada',aliases:[]}), true);
  assert.equal(registry.matches({name:'Morgan',aliases:[]}), true);
  registry.volumeFilter = 'all';
  assert.equal(registry.reorderable(), true);
  registry.volumeFilter = 'volume-one';
  assert.equal(registry.reorderable(), false);
});

test('drag reordering follows the pointer inside and across categories', () => {
  const registry = sandbox().__registry;
  registry.state = fixture();
  registry.draw = () => {};
  registry.moveCharacter('Bela', -1);
  assert.deepEqual(registry.state.document.characters.map(c=>c.name), ['Bela','Morgan','Ada']);
  registry.drag = {type:'character',name:'Ada'};
  const row = {dataset:{character:'Morgan'}, getBoundingClientRect:()=>({top:0,height:40})};
  registry.dropOnRow(row, {clientY:30});
  assert.deepEqual(registry.state.document.characters.map(c=>c.name), ['Bela','Morgan','Ada']);
  assert.equal(registry.state.document.organization.characters['Ada'].category, 'guests');
  assert.equal(registry.drag, null);
});

test('dropping a character on a category appends after its last member', () => {
  const registry = sandbox().__registry;
  registry.state = fixture();
  registry.draw = () => {};
  registry.drag = {type:'character',name:'Ada'};
  registry.dropOnCategory({dataset:{category:'guests'}, getBoundingClientRect:()=>({top:0,height:20})}, {clientY:10});
  assert.equal(registry.state.document.organization.characters['Ada'].category, 'guests');
  assert.deepEqual(registry.state.document.characters.map(c=>c.name), ['Morgan','Ada','Bela']);
});

test('volume dialog assigns and clears membership without touching voices', async () => {
  const s = sandbox(), registry = s.__registry;
  registry.state = fixture();
  registry.draw = () => {};
  registry.draftChanged = () => {};
  s.modal = async () => ({'volume-0':false, 'volume-1':true});
  await registry.editVolumes(['Ada'], 'Volumes for Ada');
  assert.deepEqual(registry.state.document.organization.characters['Ada'].volumes, ['volume-two']);
  assert.equal(registry.state.document.organization.characters['Ada'].status, 'approved');
  assert.equal(registry.state.reading['Ada'], 'Narrator');
  s.modal = async () => ({});
  await registry.editVolumes(['Ada'], 'Volumes for Ada');
  assert.equal('volumes' in registry.state.document.organization.characters['Ada'], false);
});

test('hidden characters cannot be dragged while a filter is active', () => {
  const s = sandbox(), registry = s.__registry;
  registry.state = fixture();
  registry.volumeFilter = 'volume-one';
  assert.equal(registry.reorderable(), false);
  registry.draw();
  assert.match(s.view.innerHTML, /Drag reordering is off while a search or filter is active/);
  registry.volumeFilter = 'all';
  registry.draw();
  assert.doesNotMatch(s.view.innerHTML, /Drag reordering is off/);
});

test('category actions menu closes with Escape and stays pinned after a click', () => {
  assert.match(source, /if\(event\.key==='Escape'\)\{menu\.open=false;summary\.focus\(\);\}/);
  assert.match(source, /menu\.dataset\.pinned='1'/);
  assert.match(source, /menu\.onpointerleave=/);
});

test('row Actions is a floating menu positioned like the category menu', () => {
  const s = sandbox();
  const menu = {className:'', dataset:{}, style:{}, offsetWidth:220, offsetHeight:180, innerHTML:'',
    querySelectorAll(){return [];}, remove(){menu.removed=true;}, setAttribute(){}, focus(){}};
  s.document.createElement = () => menu;
  s.document.body = {append(element){s.appended = element;}};
  s.innerWidth = 1000;
  s.innerHeight = 800;
  const button = {getBoundingClientRect:()=>({top:60,bottom:100,right:500}), setAttribute(){}};
  const registry = s.__registry;
  registry.state = fixture();
  registry.openRowMenu(button, 'Ada', true);
  assert.equal(s.appended, menu);
  assert.equal(menu.style.top, '106px');
  assert.equal(menu.style.right, '500px');
  assert.equal(menu.dataset.pinned, '1');
  assert.match(menu.className, /row-menu/);
  registry.closeRowMenu();
  assert.equal(menu.removed, true);
});

test('row bindings target table rows, never the action buttons inside them', () => {
  assert.match(source, /view\.querySelectorAll\('tr\[data-character\]'\)/);
  assert.doesNotMatch(source, /view\.querySelectorAll\('\[data-character\]'\)/);
  assert.match(source, /view\.querySelector\(`tr\[data-character=/);
});

test('chapter blockers are listed separately from line review', () => {
  const app = readFileSync(new URL('../app/web/app.js', import.meta.url), 'utf8');
  assert.match(app, /Lines to review \(/);
  assert.ok(app.includes('approval in this chapter'));
  assert.match(app, /data-review-character/);
  assert.match(app, /line\.basis === "context"/);
  assert.match(app, /Speaker inferred from narrative context/);
  assert.doesNotMatch(app, /Needs review \(/);
});
