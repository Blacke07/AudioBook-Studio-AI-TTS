import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const app=readFileSync(new URL('../app/web/app.js',import.meta.url),'utf8');
const code=app.slice(app.indexOf('function queueCharacterSave('),app.indexOf('/* ---------- narrator ---------- */'));
function setup(responder=async()=>({duplicates:[]})) {
  const timers=new Map(),calls=[];let id=0;
  const state={structuredClone,characterData:{characters:[{name:'Ada',note:'first'}]},characterSaveTimer:null,characterSaveTask:null,
    setTimeout:fn=>{timers.set(++id,fn);return id;},clearTimeout:key=>timers.delete(key),
    toast(){},guard:fn=>fn(),api:async(path,options)=>{calls.push({path,body:options?.body});return responder(path,options);}};
  vm.runInNewContext(code+'\nthis.queue=queueCharacterSave;this.flush=flushCharacterSave;',state);
  return {state,calls,timers,queue:state.queue,flush:state.flush};
}
test('creation flushes pending character edits once and clears their delayed timer',async()=>{
  const ui=setup();ui.queue();ui.state.characterData.characters[0].note='latest';await ui.flush();
  assert.equal(ui.timers.size,0);assert.equal(ui.calls.filter(c=>c.body).length,1);
  assert.equal(ui.calls[0].body.characters[0].note,'latest');assert.equal(ui.state.characterSaveTask,null);
});
test('an in-flight save finishes before the next snapshot and before recipe creation can start',async()=>{
  let release;let writes=0;
  const ui=setup(async(_path,options)=>{
    if(options&&++writes===1)await new Promise(resolve=>{release=resolve;});return {duplicates:[]};
  });
  ui.queue();const callback=[...ui.timers.values()][0];callback();
  await new Promise(resolve=>setImmediate(resolve));
  ui.state.characterData.characters[0].note='newer';ui.queue();const flushed=ui.flush();
  assert.equal(ui.calls.filter(c=>c.body).length,1);release();await flushed;
  assert.deepEqual(ui.calls.filter(c=>c.body).map(c=>c.body.characters[0].note),['first','newer']);
  assert.equal(ui.state.characterSaveTask,null);
});
