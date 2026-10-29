import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const code=readFileSync(new URL('../app/web/character-picker.js',import.meta.url),'utf8');
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state={document:{characters:[{name:'Ada'},{name:'Captain <Hart>'},{name:'Morgan'},{name:'Other'}],
  voices:[{name:'Shared guide'}],organization:{categories:[{id:'b',name:'Guests'},{id:'a',name:'Main cast'}],
    characters:{Ada:{category:'a'},Morgan:{category:'b'},'Captain <Hart>':{category:'b'},Other:{category:'gone'}}}},
  reading:{Morgan:'Shared guide'}};
const load=extra=>{const context={NARRATOR:'Narrator',UNASSIGNED:'Unassigned',esc,icon:()=>'<svg></svg>',...extra};
  vm.runInNewContext(code+'\nthis.picker=CharacterPicker;',context);return context.picker;};

test('groups preserve registry category and character order and never include shared voices',()=>{
  const groups=load().groups(state);
  assert.deepEqual(Array.from(groups,g=>g.name),['Narration','Guests','Main cast','Uncategorized']);
  assert.deepEqual(Array.from(groups[1].characters,c=>c.name),['Captain <Hart>','Morgan']);
  assert.equal(groups.flatMap(g=>g.characters).filter(c=>c.name==='Shared guide').length,0);
});
test('picker escapes names and submits one canonical target without defaulting Unassigned to Narrator',()=>{
  const picker=load(),html=picker.markup(state,'Captain <Hart>');
  assert.match(html,/Captain &lt;Hart&gt;/);assert.doesNotMatch(html,/<Hart>/);
  assert.equal((html.match(/name="target"/g)||[]).length,1);
  assert.match(picker.markup(state,'Unassigned'),/name="target" value=""/);
  assert.match(picker.markup(state,'Unassigned'),/Choose a character/);
});

function fixture(){
  const listeners=new Map(),document={activeElement:null,addEventListener:(k,f)=>listeners.set('doc:'+k,f),removeEventListener:k=>listeners.delete('doc:'+k)};
  const element=(dataset={})=>({dataset,attrs:{},hidden:true,style:{},focus(){document.activeElement=this;this.onfocus?.();},
    setAttribute(k,v){this.attrs[k]=v;}});
  const trigger=element(),value={value:'Ada'},label={},categories=Array.from({length:4},(_,i)=>element({category:String(i)}));
  const people=element();let html='',buttons=[];
  Object.defineProperty(people,'innerHTML',{get:()=>html,set:v=>{html=v;buttons=Array.from(v.matchAll(/data-person="(\d+)"/g),m=>element({person:m[1]}));}});
  people.querySelectorAll=()=>buttons;people.querySelector=()=>buttons[0];
  const popup=element();popup.querySelector=()=>people;popup.querySelectorAll=()=>categories;
  popup.contains=target=>target===people||target===popup||buttons.includes(target)||categories.includes(target);
  popup.remove=()=>{popup.removed=true;};
  const field={querySelector:s=>({'.character-picker-trigger':trigger,'[name="target"]':value,'#character-picker-value':label,'.character-picker-popup':popup}[s]),contains:target=>target===trigger};
  const overlay={append:()=>{},addEventListener:(k,f)=>listeners.set(k,f),removeEventListener:k=>listeners.delete(k)};
  const root={querySelector:()=>field,closest:()=>overlay};
  trigger.getBoundingClientRect=()=>({width:600,left:100,top:120,bottom:166});
  const window={innerWidth:1000,innerHeight:800,addEventListener:(k,f)=>listeners.set('win:'+k,f),removeEventListener:k=>listeners.delete('win:'+k)};
  const dispose=load({window,document}).bind(root,state);
  return{trigger,value,label,popup,people,categories,listeners,dispose,document,buttons:()=>buttons};
}
test('hover browses categories without changing identity; clicking a person selects explicitly',()=>{
  const ui=fixture();ui.trigger.onclick();assert.equal(ui.popup.hidden,false);
  ui.categories[1].onmouseenter();assert.equal(ui.value.value,'Ada');
  assert.match(ui.people.innerHTML,/Reads as Shared guide/);assert.match(ui.people.innerHTML,/Captain &lt;Hart&gt;/);
  ui.buttons()[1].onclick();assert.equal(ui.value.value,'Morgan');assert.equal(ui.label.textContent,'Morgan');
  assert.equal(ui.popup.hidden,true);assert.equal(ui.document.activeElement,ui.trigger);ui.dispose();
});
test('Escape closes only the picker and disposal removes popup and all global listeners',()=>{
  const ui=fixture();ui.trigger.onclick();let stopped=false;
  ui.listeners.get('keydown')({key:'Escape',preventDefault(){},stopImmediatePropagation(){stopped=true;}});
  assert.equal(stopped,true);assert.equal(ui.popup.hidden,true);assert.equal(ui.value.value,'Ada');
  ui.dispose();assert.equal(ui.popup.removed,true);assert.equal(ui.listeners.size,0);
});
test('keyboard opens the selected category and moves between category and character columns',()=>{
  const ui=fixture(),event=key=>({key,preventDefault(){}});
  ui.trigger.onkeydown(event('ArrowDown'));assert.equal(ui.document.activeElement,ui.categories[2]);
  ui.categories[2].onkeydown(event('ArrowUp'));assert.equal(ui.document.activeElement,ui.categories[1]);
  ui.categories[1].onkeydown(event('ArrowRight'));assert.equal(ui.document.activeElement,ui.buttons()[0]);
  ui.people.onkeydown(event('ArrowLeft'));assert.equal(ui.document.activeElement,ui.categories[1]);ui.dispose();
});
