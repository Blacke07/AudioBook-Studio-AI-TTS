import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const read=name=>readFileSync(new URL('../app/web/'+name,import.meta.url),'utf8');
const app=read('app.js'),css=read('style.css');
const esc=app.split('\n').find(line=>line.startsWith('const esc ='));
const helper=app.slice(app.indexOf('let fieldHelpId ='),app.indexOf('function drawCharacters()'));
function castMarkup(characters){
 const s={icon:()=>'',characters};
 vm.runInNewContext(esc+'\n'+helper+'\n'+read('voice-rules.js')+'\nhtml=VoiceRules.castMarkup({characters,can_undo:true});',s);
 return s.html;
}
test('Cast groups changes first, hides absent cast, counts and sorts within groups',()=>{
 const h=castMarkup([{name:'Zero',read_as:'Zero',lines:0,chapters:0,fixed:false},{name:'Ada',read_as:'Ada',lines:1,chapters:1,fixed:true},{name:'Max',read_as:'Narrator',lines:3,chapters:2,fixed:true},{name:'Lara',read_as:'Narrator',lines:9,chapters:2,fixed:true}]);
 assert.match(h,/2 changed · 2 unchanged/);assert.match(h,/1 line · 1 chapter/);assert.match(h,/9 lines · 2 chapters/);
 assert.ok(h.indexOf('Changed (2)')<h.indexOf('Unchanged (1)'));assert.ok(h.indexOf('data-cast-voice="Lara"')<h.indexOf('data-cast-voice="Max"'));
 assert.match(h,/<details class="cast-unused"><summary>Not in this volume \(1\)/);
 assert.doesNotMatch(h,/Ada → Ada/);assert.match(h,/Max → Narrator/);
 assert.match(h,/<details id="cast-disclosure">/);assert.match(h,/id="undo-voice-rule"/);assert.match(h,/Help: Voice to review/);
});
test('Cast handles empty data and hostile names as text',()=>{
 assert.match(castMarkup([]),/Add characters or analyze/);
 assert.doesNotMatch(castMarkup([{name:'<img>',read_as:'<img>',lines:1,chapters:1,fixed:true}]),/<img>/);
});
test('optional Cast storage cannot block the disclosure',()=>{
 assert.match(read('voice-rules.js'),/try \{ disclosure.open=localStorage/);
 assert.match(read('voice-rules.js'),/disclosure.ontoggle=/);
});
test('Back has tall desktop target, rest opacity and reduced-motion support',()=>{
 const back=css.slice(css.indexOf('.back {'),css.indexOf('/* ---- surfaces'));
 assert.match(back,/left: 250px/);assert.match(back,/height: 50vh/);assert.match(back,/opacity: \.3/);
 assert.match(back,/back:hover, \.back:focus-visible \{ opacity: 1/);assert.match(back,/prefers-reduced-motion/);
});
test('character template folds detection and creation, preserving all wired fields',()=>{
 const template=app.slice(app.indexOf('return `<div class="card char-card"'),app.indexOf('  $("#voice-guide").onclick'));
 for(const key of ['aliases','note','sample','model','custom','seed']) assert.match(template,new RegExp('data-f="'+key+'"'));
 for(const key of ['listen','reading-voice','profile','description','dice','preset-pick','candidates','candidate-list','audio','fix','unfix','delete'])assert.ok(template.includes('data-'+key),key);
 assert.match(template,/<details class="character-section" data-studio-section="detection"><summary>\$\{c\.library \? 'Who this voice suits' : 'Speaker detection'\}/);assert.match(template,/<details class="character-section" data-studio-section="creation"><summary>Voice creation/);
 assert.match(template,/data-studio-section="reference" open/);assert.doesNotMatch(template,/data-studio-section="(?:detection|creation)" open/);assert.match(template,/href="#\/narrator"/);
 assert.ok(template.indexOf('data-listen')<template.indexOf('Speaker detection'));
});
test('help is keyboard-focusable, described and dismissible without losing focus',()=>{
 const s={icon:()=>''};vm.runInNewContext(esc+'\n'+helper+'\nhtml=fieldHelp("Seed","A <take>");',s);
 assert.match(s.html,/type="button"/);assert.match(s.html,/aria-describedby="field-help-1"/);assert.match(s.html,/role="tooltip" id="field-help-1"/);assert.match(s.html,/A &lt;take&gt;/);
 let dismissed=false;const box={style:{},offsetWidth:200,offsetHeight:80};
 const button={getBoundingClientRect:()=>({top:300,bottom:328,right:260})};
 const tip={querySelector:selector=>selector==='button'?button:box,classList:{add:()=>dismissed=true,remove:()=>dismissed=false}};
 Object.assign(s,{innerWidth:400,innerHeight:700,root:{querySelectorAll:()=>[tip]}});vm.runInNewContext('bindFieldHelp(root)',s);
 button.onkeydown({key:'Escape',stopPropagation(){}});assert.equal(dismissed,true);button.onfocus();assert.equal(dismissed,false);
 assert.equal(box.style.left,'60px','Focusing the button also places the note inside the window');
 assert.match(css,/.field-help:focus-within \.help-content/);
});
test('spoken editor escapes source text and requires preview before save',async()=>{
 const elements=new Map();let pendingResolve,call;
 const s={...{icon:()=>''},$:key=>{if(!elements.has(key))elements.set(key,{value:'new text'});return elements.get(key);},guard:fn=>fn(),api:async(path,options)=>{call=[path,options];return{suggested:'new text'};},modal:(title,html)=>{s.html=html;return new Promise(resolve=>pendingResolve=resolve);}};
 vm.runInNewContext(esc+'\n'+read('spoken-text.js')+'\npending=SpokenText.editor("Demo","one",{source_hash:"abc",lines:[{text:"<script>source</script>",speaker:"Ada"}]},0);',s);
 assert.match(s.html,/&lt;script&gt;/);assert.doesNotMatch(s.html,/<script>/);assert.match(s.html,/Restore original/);
 assert.equal(call,undefined);pendingResolve(null);await s.pending;assert.equal(call,undefined);
});

test('UI keeps UTF-8 arrows and separators without mojibake',()=>{
 for(const name of ['app.js','voice-rules.js','style.css','spoken-text.js'])assert.doesNotMatch(read(name),/Ã|Â|â(?:€|†)/,name);
  assert.ok(read('voice-rules.js').includes('line → chapter → character → category → own voice'));
});
