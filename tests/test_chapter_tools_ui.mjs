import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const read=name=>readFileSync(new URL('../app/web/'+name,import.meta.url),'utf8');
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const feature=(file,name,extra={})=>{
  const context={esc,icon:()=>'<svg></svg>',NARRATOR:'Narrator',UNASSIGNED:'Unassigned',...extra};
  vm.runInNewContext(read(file)+'\nthis.feature='+name+';',context);return context.feature;
};

test('visual boundaries use Unicode code points and allow the exact repeated occurrence',()=>{
  const split=feature('line-split.js','LineSplit');
  const text='🙂 Wait here. Wait here.',position=Array.from('🙂 Wait here. ').length;
  const line={text,split_points:[{position,kind:'Sentence end'}]};
  assert.equal(split.points(line)[0][0],position);
  const html=split.markup(line,false,position);
  assert.match(html,/🙂 Wait here\. <button/);assert.match(html,/before Wait here\./);
  assert.match(html,/aria-pressed="true"/);assert.equal((html.match(/data-cut=/g)||[]).length,1);
});

test('speech-tag scissors and optional word boundaries escape source markup',()=>{
  const split=feature('line-split.js','LineSplit'),text='<A signal,> Ada said softly.';
  const line={text,split_points:[{position:12,kind:'Speech tag'}]};
  assert.equal(split.points(line).length,1);assert.ok(split.points(line,true).length>1);
  assert.match(split.markup(line),/&lt;A signal,&gt;/);assert.doesNotMatch(split.markup(line),/<A signal/);
  assert.match(split.markup(line),/Speech tag/);
});

function castUI(actions) {
  const calls=[],elements=new Map(),modals=[];let routes=0,voice;
  const el=selector=>{if(!elements.has(selector))elements.set(selector,{classList:{add(){}},value:'',disabled:false});return elements.get(selector);};
  const root={classList:{add(){}},querySelector:el};
  const state={document:{characters:[{name:'Ada'},{name:'Morgan'}]}};
  const cast=feature('chapter-cast.js','ChapterCast',{
    document:{querySelector:()=>root},modal:async(title,body)=>{modals.push({title,body});return actions.shift();},
    api:async(path,options)=>{calls.push({path,body:options?.body});return path==='/api/character-registry'?state:
      {request:options.body,plan_id:'preview',lines:2,chapters:[{volume:'Lantern',chapter:'001',lines:2,removed_voice_overrides:1}]};},
    toast(){},route:async()=>{routes++;},VoiceRules:{editor:(...args)=>{voice=args;}},
    CharacterPicker:{markup:()=>'<div class="character-picker"></div>',bind:()=>()=>{}},
  });
  const data={source_hash:'source',script_revision:'revision',lines:[{speaker:'Ada',text:'Wait.'}],
    voice_rules:{characters:{Ada:'Morgan'},lines:[{row:0,read_as:'Narrator'}]}};
  return{cast,calls,modals,data,routes:()=>routes,voice:()=>voice};
}

test('chapter character replacement only writes after a separate preview and explicit Apply',async()=>{
  const ui=castUI([{target:'Morgan',scope:'chapter'},true]);
  await ui.cast.editor('Ada','Lantern','001',ui.data);
  assert.deepEqual(ui.calls.map(c=>c.path),['/api/character-registry','/api/character-registry/reassign-preview','/api/character-registry/reassign']);
  assert.equal(ui.calls[1].body.script_revision,'revision');assert.equal(ui.calls[1].body.scope,'chapter');
  assert.equal(ui.routes(),1);assert.match(ui.modals[1].body,/1 old line voice overrides removed/);
  assert.ok(ui.calls.every(c=>!c.path.includes('/merge')));
});

test('cancelled preview and unchanged character cause no writes',async()=>{
  for(const actions of [[{target:'Morgan',scope:'everywhere'},false],[{target:'Ada',scope:'line'}],[null]]){
    const ui=castUI(actions);await ui.cast.editor('Ada','Lantern','001',ui.data,0);
    assert.ok(ui.calls.every(c=>c.path!=='/api/character-registry/reassign'));assert.equal(ui.routes(),0);
  }
});

test('reading-voice shortcut forwards current chapter and line choices without identity changes',async()=>{
  const ui=castUI(['voice']);await ui.cast.editor('Ada','Lantern','001',ui.data,0);
  const [name,context]=ui.voice();assert.equal(name,'Ada');assert.equal(context.row,0);
  assert.equal(context.chapter_choice,'Morgan');assert.equal(context.line_choice,'Narrator');
  assert.equal(ui.calls.length,1);
});

test('tag scope describes exact included and excluded chapter boundaries',()=>{
  const tags=feature('character-tags.js','CharacterTags');
  const state={volumes:[{id:'v',name:'Lantern'}],document:{organization:{contexts:[{id:'c',chapter_range:{from:'002',before:'010'}}]}}};
  const meta={alias_scopes:{Traveler:{volumes:['v'],contexts:['c']}}};
  assert.equal(tags.scope('Traveler',meta,state),'Lantern — From 002 · before 010');
  assert.equal(tags.scope('Other',meta,state),'All volumes');
});

test('character tag pills preserve scope hints and escape names without becoming new identities',()=>{
  const tags=feature('character-tags.js','CharacterTags');
  const state={volumes:[],document:{characters:[{name:'Ada',aliases:['<The guest>']}],organization:{contexts:[],characters:{Ada:{}}}}};
  const html=tags.summary('Ada',state);assert.match(html,/&lt;The guest&gt;/);assert.match(html,/title="All volumes"/);
  assert.doesNotMatch(html,/<The guest>/);assert.equal(state.document.characters.length,1);
});

test('a rejected tag keeps its editor and inputs so the user can correct it in place',async()=>{
  let close,closed=false,applied=false,allow=false;
  const fields=[{name:'alias',value:'Ada'},{name:'volume',value:''},{name:'from',value:''},{name:'before',value:''},
    {name:'display',type:'checkbox',checked:true}],error={hidden:true};
  const buttons=[{click(){closed=true;close(null);}},{disabled:false}];
  const select=s=>s==='.tag-error'?error:s==='#tag-volume'?fields[1]:s==='#tag-from'?fields[2]:s==='#tag-before'?fields[3]:
    buttons[Number(s.match(/data-i="(\d)"/)?.[1])];
  const root={classList:{add(){}},querySelector:select};
  const tags=feature('character-tags.js','CharacterTags',{
    document:{querySelector:()=>root},$:select,$$:s=>s==='[name]'?fields:buttons,
    modal:()=>new Promise(resolve=>{close=resolve;}),
    api:async()=>{if(!allow)throw new Error('That name already belongs to an identity.');return{plan_id:'ready'};},toast(){},
  });
  tags.apply=async()=>{applied=true;};
  const pending=tags.edit('Ada',null,{revision:'current',volumes:[],document:{organization:{contexts:[],characters:{Ada:{}}}}});
  await new Promise(resolve=>setImmediate(resolve));
  await buttons[1].onclick({stopPropagation(){}});
  assert.equal(closed,false);assert.equal(error.hidden,false);assert.match(error.textContent,/already belongs/);
  assert.equal(fields[0].value,'Ada');assert.equal(applied,false);
  allow=true;fields[0].value='The traveler';await buttons[1].onclick({stopPropagation(){}});await pending;
  assert.equal(closed,true);assert.equal(applied,true);
});

test('sticky chapter controls contain one audio player and obsolete phrase-entry UI is gone',()=>{
  const app=read('app.js'),chapter=app.slice(app.indexOf('async function viewChapter('),app.indexOf('/* speaker picker */'));
  assert.equal((chapter.match(/<audio id="player"/g)||[]).length,1);
  assert.ok(chapter.indexOf('<audio id="player"')<chapter.indexOf('${c.error ?'));
  assert.doesNotMatch(chapter,/Words where the new segment begins/);
  assert.match(chapter,/LineSplit\.editor/);assert.match(chapter,/ChapterCast\.bind/);
  assert.match(read('index.html'),/character-tags\.js/);
});
