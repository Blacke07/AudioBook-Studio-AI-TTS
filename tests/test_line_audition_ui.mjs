import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=readFileSync(new URL('../app/web/line-audition.js',import.meta.url),'utf8');
const app=readFileSync(new URL('../app/web/app.js',import.meta.url),'utf8');
const escapeSource=app.split('\n').find(line=>line.startsWith('const esc ='));
const tick=()=>new Promise(resolve=>setImmediate(resolve));

function setup(responder) {
  const controls=new Map(),events={};
  let useButtons=[];
  const element=selector=>{
    if(!controls.has(selector)) controls.set(selector,{hidden:false,disabled:false,textContent:'',onclick:null});
    return controls.get(selector);
  };
  const takeBox=element('[data-takes]');
  Object.defineProperty(takeBox,'innerHTML',{set(value){
    this.html=value;
    useButtons=[...value.matchAll(/data-use-take="(\d+)"/g)].map(match=>({dataset:{useTake:match[1]},disabled:false}));
  }});
  const dialog={isConnected:false,querySelector:element,
    querySelectorAll(selector){return selector==='audio'?[]:useButtons;},
    setAttribute(){},addEventListener(name,fn){events[name]=fn;},showModal(){this.shown=true;},
    close(){events.close();},remove(){this.isConnected=false;},
    getBoundingClientRect(){return {left:10,right:100,top:10,bottom:100};}};
  const calls=[],notices=[],focus={count:0};
  const state={icon:()=>'',document:{createElement:()=>dialog,body:{append(){dialog.isConnected=true;}}},
    api:async(path,options)=>{calls.push({path,...options});return responder(path,options);},
    toast:text=>notices.push(text)};
  vm.runInNewContext(escapeSource+'\n'+source+'\nthis.feature=LineAudition;',state);
  const data={audition_enabled:true,source_hash:'source',script_revision:'revision',emotions:[{key:'angry',label:'Angry'}],
    lines:[{speaker:'Ada',read_as:'Morgan',text:'Original text.',spoken_text:'Spoken text!',emotion:'angry',variant:2}]};
  return {feature:state.feature,data,dialog,calls,notices,element,buttons:()=>useButtons,
    trigger:{focus(){focus.count++;}},focus};
}
const take=variant=>({token:'token-'+variant,url:'/api/audio?path=work/preview.wav',variant,current:variant===2,
  read_as:'Morgan',emotion:'Angry',text:'Spoken text!',warnings:['Neutral delivery is used.']});

test('chapter has a labelled audition independent of saved chapter playback',()=>{
  const s=setup(()=>take(2));
  assert.match(s.feature.trigger(s.data.lines[0],0,s.data),/Audition line/);
  assert.match(app,/LineAudition\.bind/);
  assert.match(app,/Play saved chapter from here/);
  assert.match(readFileSync(new URL('../app/web/index.html',import.meta.url),'utf8'),/src="line-audition.js"/);
  for(const extra of [{speaker:'Unassigned'},{omitted:true}])
    assert.match(s.feature.trigger({...s.data.lines[0],...extra},0,s.data),/disabled/);
  assert.match(s.feature.trigger(s.data.lines[0],0,{...s.data,manual_draft:true}),/disabled/);
});

test('cards escape voices, warnings and audio URLs and distinguish preview from selection',()=>{
  const s=setup(()=>take(2));
  const markup=s.feature.cards([{...take(2),url:'" onerror="bad',warnings:['<img src=x>']}],false);
  assert.doesNotMatch(markup,/<img/);
  assert.match(markup,/&lt;img/);
  assert.match(markup,/&quot; onerror=&quot;/);
  assert.match(markup,/Keep current take/);
  assert.match(s.feature.cards([take(2),take(3)],false),/Use this take/);
});

test('opening uses the saved source revision and spoken context, closing never applies',async()=>{
  const s=setup((path,options)=>take(options.body.variant));
  s.feature.open('Lantern','001',s.data,0,s.trigger,()=>{});
  await tick();
  assert.equal(s.dialog.shown,true);
  assert.equal(s.calls[0].path,'/api/chapter/audition');
  assert.deepEqual(JSON.parse(JSON.stringify(s.calls[0].body)),{
    volume:'Lantern',stem:'001',row:0,source_hash:'source',script_revision:'revision',variant:2});
  assert.equal(s.element('[data-reading-text]').textContent,'Spoken text!');
  assert.match(s.element('[data-takes]').html,/Neutral delivery is used/);
  s.dialog.close();
  assert.equal(s.calls.length,1);
  assert.equal(s.focus.count,1);
});

test('comparison keeps the current take and only explicit selection applies a token',async()=>{
  const s=setup((path,options)=>path.endsWith('/apply')?{changed:true}:take(options.body.variant));
  let refreshed=null;
  s.feature.open('Lantern','001',s.data,0,s.trigger,row=>{refreshed=row;});
  await tick();
  await s.element('[data-compare]').onclick();
  assert.equal(s.calls.length,2);
  assert.equal(s.calls[1].body.variant,3);
  assert.equal(s.buttons().length,2);
  await s.buttons()[1].onclick();
  assert.equal(s.calls[2].path,'/api/chapter/audition/apply');
  assert.equal(s.calls[2].method,'PUT');
  assert.equal(s.calls[2].body.token,'token-3');
  assert.equal(refreshed,0);
  assert.equal(s.dialog.isConnected,false);
});

test('late preview results never reopen a closed dialog or apply a take',async()=>{
  let complete;
  const s=setup(()=>new Promise(resolve=>{complete=resolve;}));
  s.feature.open('Lantern','001',s.data,0,s.trigger,()=>{});
  s.dialog.close();
  complete(take(2));await tick();
  assert.equal(s.dialog.isConnected,false);
  assert.equal(s.calls.length,1);
  assert.equal(s.buttons().length,0);
});

test('generation errors stay visible with explicit retry and no selection change',async()=>{
  const s=setup(()=>{throw new Error('The chapter changed. Refresh it.');});
  s.feature.open('Lantern','001',s.data,0,s.trigger,()=>{});
  await tick();
  assert.equal(s.element('[data-error]').hidden,false);
  assert.match(s.element('[data-error]').textContent,/chapter changed/);
  assert.equal(s.element('[data-retry]').hidden,false);
  assert.equal(s.calls.length,1);
});
