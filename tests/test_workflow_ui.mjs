import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../app/web/workflow.js',import.meta.url),'utf8');
function menu() {
  const listeners = {}, roots = [];
  for (let i=0; i<3; i++) {
    const classes = new Set(), attributes = {};
    const action = {focus() {this.focused=true;}};
    const panel = {hidden:true, style:{}, querySelector:()=>action};
    const trigger = {getBoundingClientRect:()=>({bottom:50}), setAttribute:(key,value)=>attributes[key]=value, focus() {this.focused=true;}};
    const root = {classes, attributes, trigger, panel, action,
      classList:{remove:value=>classes.delete(value),toggle:(value,on)=>on?classes.add(value):classes.delete(value)},
      contains:node=>[root,trigger,panel,action].includes(node),
      querySelector:selector=>selector==='.workflow-trigger'?trigger:panel};
    roots.push(root);
  }
  const sandbox={window:{innerHeight:600,addEventListener:(key,fn)=>listeners[key]=fn},
    document:{addEventListener:(key,fn)=>listeners[key]=fn,querySelectorAll:()=>roots}};
  vm.runInNewContext(source+'\nChapterWorkflow.bind();',sandbox);
  return {roots,listeners};
}

test('mouse hover shows actions without explanations and closes on leaving',()=>{
  const {roots:[root]}=menu();
  root.onpointerenter({pointerType:'mouse'});
  assert.equal(root.panel.hidden,false);
  assert.equal(root.classes.has('explained'),false);
  assert.equal(root.attributes['aria-expanded'],'true');
  root.onpointerleave();
  assert.equal(root.panel.hidden,true);
});

test('click pins explanations, second click closes, and touch does not rely on hover',()=>{
  const {roots:[root]}=menu();
  root.onpointerenter({pointerType:'touch'});
  assert.equal(root.panel.hidden,true);
  root.trigger.onclick();
  root.onpointerleave();
  assert.equal(root.classes.has('explained'),true);
  assert.equal(root.panel.hidden,false);
  root.trigger.onclick();
  assert.equal(root.panel.hidden,true);
});

test('switching category, outside click and Escape close the previous dropdown',()=>{
  const {roots:[first,second],listeners}=menu();
  first.trigger.onclick();
  second.trigger.onclick();
  assert.equal(first.panel.hidden,true);
  assert.equal(second.panel.hidden,false);
  listeners.click({target:{}});
  assert.equal(second.panel.hidden,true);
  first.trigger.onclick();
  listeners.keydown({key:'Escape'});
  assert.equal(first.panel.hidden,true);
  assert.equal(first.trigger.focused,true);
});

test('ArrowDown opens explanations and focuses the first enabled action',()=>{
  const {roots:[root]}=menu();
  let prevented=false;
  root.trigger.onkeydown({key:'ArrowDown',preventDefault:()=>prevented=true});
  assert.equal(prevented,true);
  assert.equal(root.action.focused,true);
  assert.equal(root.classes.has('explained'),true);
});

test('dropdown height is limited by the remaining window space and resize closes it',()=>{
  const {roots:[root],listeners}=menu();
  root.trigger.getBoundingClientRect=()=>({bottom:400});
  root.trigger.onclick();
  assert.equal(root.panel.style.maxHeight,'188px');
  listeners.resize();
  assert.equal(root.panel.hidden,true);
});
