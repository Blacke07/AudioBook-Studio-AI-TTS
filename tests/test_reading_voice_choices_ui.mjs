import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const app=readFileSync(new URL('../app/web/app.js',import.meta.url),'utf8');
const esc=app.split('\n').find(line=>line.startsWith('const esc ='));
const source=readFileSync(new URL('../app/web/voice-rules.js',import.meta.url),'utf8');
async function open(voices,preferred_voice,preview=false) {
  const fields={'[name="scope"]':{value:'everywhere'},'[name="read_as"]':{value:''}},calls=[];
  const state={document:{querySelector:s=>fields[s]},$:()=>({}),guard:fn=>fn(),html:'',
    modal:async(_title,html)=>{state.html ||= html;return preview&&calls.length===1?{scope:'everywhere',read_as:'Ada'}:null;},
    api:async(path,options)=>{
      calls.push({path,body:options?.body});
      if(path.endsWith('/cast'))return {characters:[{name:'Ada',read_as:'Shared guide',explicit_read_as:'Shared guide'}],voices};
      return {chapters:[],lines:0,request:options.body,plan_id:'synthetic'};
    }};
  vm.runInNewContext(esc+'\n'+source+'\nthis.feature=VoiceRules;',state);
  await state.feature.editor('Ada',{preferred_voice});
  return {state,fields,calls};
}
test('a character without an own recipe has no phantom own voice option',async()=>{
  const ui=await open(['Narrator','Shared guide']);
  assert.doesNotMatch(ui.state.html,/<option value="Ada">Own voice/);
  assert.equal(ui.fields['[name="read_as"]'].value,'Shared guide');assert.equal(ui.calls.length,1);
});
test('the explicit use-own action preselects the created voice but still requires preview',async()=>{
  const ui=await open(['Narrator','Shared guide','Ada'],'Ada',true);
  assert.match(ui.state.html,/<option value="Ada">Own voice/);
  assert.equal(ui.fields['[name="read_as"]'].value,'Ada');
  assert.equal(ui.calls[1].path,'/api/voice-rules/preview');
  assert.equal(ui.calls[1].body.preferred_voice,undefined);
  assert.equal(ui.calls.some(c=>c.path.endsWith('/apply')),false,'Cancelled preview must never activate a voice');
});
test('Quick view disables unavailable own voices but keeps the category own-voice policy',()=>{
  const state={esc:value=>String(value),window:{addEventListener(){}},document:{addEventListener(){}}};
  const registry=readFileSync(new URL('../app/web/character-registry.js',import.meta.url),'utf8');
  vm.runInNewContext(registry+'\nthis.feature=CharacterRegistry;',state);
  state.feature.state={voices:['Shared guide'],document:{characters:[{name:'Ada'}]}};
  assert.match(state.feature.voices('own',true,'Ada'),/value="own" selected disabled>Own voice — create one first/);
  assert.doesNotMatch(state.feature.voices('own',false),/disabled/);
  state.feature.state.voices.push('Ada');
  assert.doesNotMatch(state.feature.voices('own',true,'Ada'),/disabled/);
});
