import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const read=name=>readFileSync(new URL('../app/web/'+name,import.meta.url),'utf8');
const esc=read('app.js').split('\n').find(line=>line.startsWith('const esc ='));
function feature() {
  const state={characterQuery:'',icon:()=>'',colorFor:()=> '#123'};
  vm.runInNewContext(esc+'\n'+read('voice-studio.js')+'\nthis.feature=VoiceStudio;',state);
  return state.feature;
}
function data() {
  return {characters:[{name:'Morgan',read_as:'Narrator',aliases:'',note:'',fixed:null},
    {name:'Ada',read_as:'Ada',aliases:'captain',note:'',fixed:{takes:{angry:{}}}},
    {name:'A very long invented character name',read_as:'Ada',aliases:'',note:'',fixed:null}],
    emotions:[{key:'neutral'},{key:'angry'},{key:'calm'}],registry:{volumes:[{id:'v1'},{id:'v2'}],document:{
      characters:[{name:'Ada'},{name:'A very long invented character name'},{name:'Morgan'}],organization:{
        categories:[{id:'first',name:'Harbor crew'},{id:'second',name:'Visitors'}],characters:{
          Ada:{category:'first',status:'approved',volumes:['v1']},
          'A very long invented character name':{category:'first',status:'provisional',volumes:[]},
          Morgan:{category:'second',status:'approved',volumes:['v2']}}}}}};
}

test('studio uses the registry category and character order, not the audition API order',()=>{
  const ui=feature(),d=data(),groups=ui.groups(d);
  assert.deepEqual(Array.from(groups,g=>g.category.name),['Harbor crew','Visitors']);
  assert.deepEqual(Array.from(groups[0].people,p=>p.c.name),['Ada','A very long invented character name']);
  assert.equal(d.characters[0].name,'Morgan','Grouping must not rewrite the stored cast');
});
test('volume filters preserve unscoped characters and searching includes aliases',()=>{
  const ui=feature(),d=data();ui.volume='v1';
  assert.deepEqual(Array.from(ui.groups(d).flatMap(g=>g.people),p=>p.c.name),['Ada','A very long invented character name']);
  assert.equal(ui.groups(d,'captain')[0].people[0].c.name,'Ada');
  assert.equal(ui.groups(d,'absent').flatMap(g=>g.people).length,0);
});
test('selection survives redraws and moves only when the filters hide it',()=>{
  const ui=feature(),d=data();ui.selected='Morgan';assert.equal(ui.selection(d).c.name,'Morgan');
  ui.volume='v1';assert.equal(ui.selection(d).c.name,'Ada');
  ui.volume='removed';assert.equal(ui.selection(d).c.name,'Ada');assert.equal(ui.volume,'all');
});
test('tiles are escaped summary buttons without editable recipe controls',()=>{
  const ui=feature(),d=data();ui.selected='Ada';
  const html=ui.catalogue(d);
  assert.match(html,/data-studio-character="Ada" aria-pressed="true"/);
  assert.match(html,/Emotions 1\/2/);assert.match(html,/Provisional identity/);
  assert.doesNotMatch(html,/<audio|<input|<textarea|<select/);
  d.characters[1].name='<img>';d.registry.document.characters[0].name='<img>';
  d.registry.document.organization.characters['<img>']=d.registry.document.organization.characters.Ada;
  assert.doesNotMatch(ui.catalogue(d),/<img>/);
});
function page() {
  const seed={value:'2710'},text={value:'An unsent invented draft.'};
  const emotion={dataset:{emotionTake:'shouting'},open:true,querySelector:s=>s==='[data-emotion-seed]'?seed:text};
  const section={dataset:{studioSection:'emotions'},open:true};
  const browser={scrollTop:140,querySelectorAll:()=>[]};
  const editor={dataset:{character:'Ada'},scrollTop:270,querySelectorAll:s=>s==='[data-studio-section]'?[section]:[emotion]};
  return {root:{querySelector:s=>s==='.voice-studio-browser'?browser:editor},browser,editor,section,emotion,seed,text};
}
test('editor state restores open sections, scroll and draft values per character',()=>{
  const ui=feature(),p=page();ui.capture(p.root);
  p.editor.scrollTop=0;p.browser.scrollTop=0;p.section.open=false;p.emotion.open=false;p.seed.value='0';p.text.value='reset';
  ui.restore(p.root);
  assert.equal(p.editor.scrollTop,270);assert.equal(p.browser.scrollTop,140);
  assert.equal(p.section.open,true);assert.equal(p.emotion.open,true);
  assert.equal(p.seed.value,'2710');assert.equal(p.text.value,'An unsent invented draft.');
  p.editor.dataset.character='Morgan';p.section.open=false;ui.capture(p.root);
  p.editor.dataset.character='Ada';ui.restore(p.root);assert.equal(p.section.open,true);
});
test('an approved reference updates only the matching tile counter and data',()=>{
  const ui=feature(),d=data(),counter={textContent:''};
  const tile={dataset:{studioCharacter:'Ada'},querySelector:()=>counter};
  let unrelatedTouched=false;
  const root={querySelectorAll:()=>[tile],querySelector(){unrelatedTouched=true;}};
  const fixed={takes:{angry:{},calm:{}}};ui.referenceChanged(d,'Ada',fixed,root);
  assert.equal(d.characters[1].fixed,fixed);assert.equal(counter.textContent,'Emotions 2/2');assert.equal(unrelatedTouched,false);
});
