import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const app=readFileSync(new URL('../app/web/app.js',import.meta.url),'utf8');
const source=readFileSync(new URL('../app/web/own-voice.js',import.meta.url),'utf8');
const escape=app.split('\n').find(line=>line.startsWith('const esc ='));
function setup(response=async()=>({created:true})) {
  const fields={model:{value:'VoiceDesign'},design:{value:'An invented, clear adult voice.'},
    custom:{value:'',disabled:true},seed:{value:'0'}};
  const nodes=new Map();
  const get=selector=>{if(!nodes.has(selector))nodes.set(selector,{hidden:false,disabled:false,textContent:''});return nodes.get(selector);};
  const events={}; let changes=0;
  const form={elements:{namedItem:name=>fields[name]},querySelector:get,
    reportValidity:()=>Number.isInteger(+fields.seed.value)&&fields.seed.value!==''&&+fields.seed.value>=0&&+fields.seed.value<=2147483647
      &&(fields.model.value==='VoiceDesign'?!!fields.design.value.trim():!!fields.custom.value)};
  const dialog={isConnected:false,querySelector:selector=>selector==='form'?form:get(selector),setAttribute(){},
    addEventListener(name,fn){events[name]=fn;},showModal(){},remove(){this.isConnected=false;},close(){events.close();}};
  const calls=[];
  const context={document:{createElement:()=>dialog,body:{append(){dialog.isConnected=true;}}},toast(){},
    api:async(path,options)=>{calls.push({path,...options});return response(path,options);}};
  vm.runInNewContext(escape+'\n'+source+'\nthis.feature=OwnVoice;',context);
  const character={name:'Visitor <one>',read_as:'Shared guide',seed:0};
  const closed=context.feature.editor(character,{Ryan:'English voice'},'revision',async()=>{changes++;});
  return {feature:context.feature,character,dialog,fields,get,events,calls,closed,changes:()=>changes,
    submit:()=>form.onsubmit({preventDefault(){}})};
}
test('creation explains the separate reading step and escapes character names',()=>{
  const ui=setup(),html=ui.dialog.innerHTML;
  assert.match(html,/Visitor &lt;one&gt;/);assert.doesNotMatch(html,/<one>/);
  assert.match(html,/Current reading voice/);assert.match(html,/Your reading rules stay as they are/);
});
test('cancelling the dialog never creates or auditions a voice',async()=>{
  const ui=setup();ui.get('[data-own-voice-cancel]').onclick();await ui.closed;
  assert.equal(ui.calls.length,0);assert.equal(ui.changes(),0);
});
test('exact seed zero and selected recipe reach only the creation endpoint',async()=>{
  const ui=setup();await ui.submit();
  assert.equal(ui.calls.length,1);assert.equal(ui.calls[0].path,'/api/characters/own-voice');
  assert.equal(ui.calls[0].body.seed,0);assert.equal(ui.calls[0].body.revision,'revision');
  assert.equal(ui.calls[0].body.role,'Visitor <one>');assert.equal(ui.changes(),1);
  assert.equal(ui.dialog.isConnected,false);
});
test('switching models validates only the relevant recipe fields',async()=>{
  const ui=setup();ui.fields.model.value='CustomVoice';ui.fields.model.onchange();
  assert.equal(ui.fields.design.disabled,true);assert.equal(ui.fields.custom.disabled,false);
  assert.equal(ui.get('[data-own-custom]').hidden,false);
  await ui.submit();assert.equal(ui.calls.length,0);
  ui.fields.custom.value='Ryan';await ui.submit();assert.equal(ui.calls[0].body.model,'CustomVoice');
});
test('invalid fields do not call the server',async()=>{
  for(const value of ['', '-1','1.5','2147483648']){
    const ui=setup();ui.fields.seed.value=value;await ui.submit();assert.equal(ui.calls.length,0);
  }
});
test('server errors preserve the open dialog and all input for correction',async()=>{
  const ui=setup(async()=>{throw new Error('Characters changed.');});await ui.submit();
  assert.equal(ui.dialog.isConnected,true);assert.equal(ui.fields.seed.value,'0');
  assert.equal(ui.get('[data-own-voice-error]').hidden,false);
  assert.match(ui.get('[data-own-voice-error]').textContent,/Characters changed/);
  assert.equal(ui.get('[type="submit"]').disabled,false);assert.equal(ui.changes(),0);
});
test('a pending creation cannot be submitted twice or dismissed as cancelled',async()=>{
  let release;const ui=setup(()=>new Promise(resolve=>{release=resolve;}));
  const pending=ui.submit();await ui.submit();ui.get('[data-own-voice-cancel]').onclick();
  let prevented=false;ui.events.cancel({preventDefault(){prevented=true;}});
  assert.equal(prevented,true);assert.equal(ui.calls.length,1);assert.equal(ui.dialog.isConnected,true);
  release({created:true});await pending;assert.equal(ui.changes(),1);
});
