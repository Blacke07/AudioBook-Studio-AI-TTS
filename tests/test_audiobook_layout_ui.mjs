import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const read=name=>readFileSync(new URL('../app/web/'+name,import.meta.url),'utf8');
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const feature=(file,name)=>{const context={esc,icon:name=>`<svg data-icon="${name}"></svg>`};vm.runInNewContext(read(file)+`\nthis.feature=${name};`,context);return context.feature;};

test('Prose and Dialogue keep separate editable drafts without changing the supplied prose',()=>{
  const original='An invented quiet passage.',passages=feature('narrator-passages.js','NarratorPassages').create(original);
  assert.equal(passages.text(),original);
  const dialogue=passages.choose('dialogue','An edited prose passage.');
  assert.match(dialogue,/he said|she said/i);assert.match(dialogue,/she replied/i);
  assert.equal(passages.choose('prose','My edited dialogue.'),'An edited prose passage.');
  assert.equal(passages.choose('dialogue',passages.text()),'My edited dialogue.');
  assert.equal(original,'An invented quiet passage.');
  assert.throws(()=>passages.choose('unknown','Discard me'),/Choose Prose or Dialogue/);
  assert.equal(passages.text(),'My edited dialogue.');
});

test('preset buttons update the active field and pressed state and capture typing',()=>{
  const passages=feature('narrator-passages.js','NarratorPassages').create('Prose.'),input={value:'Prose.'};
  const buttons=['prose','dialogue'].map(key=>({dataset:{previewPreset:key},classList:{toggle(){}},setAttribute(k,v){this[k]=v;}}));
  passages.bind({querySelector:()=>input,querySelectorAll:()=>buttons});
  input.value='Edited prose.';input.oninput();buttons[1].onclick();
  assert.equal(buttons[1]['aria-pressed'],'true');assert.match(input.value,/she said/);
  input.value='Edited dialogue.';input.oninput();buttons[0].onclick();
  assert.equal(input.value,'Edited prose.');assert.equal(buttons[1]['aria-pressed'],'false');
  assert.equal(passages.text(),'Edited prose.');
});

test('preview text and report markup escape content rather than interpreting it as HTML',()=>{
  const passages=feature('narrator-passages.js','NarratorPassages').create('</textarea><img src=x>');
  assert.match(passages.html(),/&lt;\/textarea&gt;/);assert.doesNotMatch(passages.html(),/<img/);
  const notices=feature('chapter-notices.js','ChapterNotices');
  const html=notices.html({chapter:{video:{}},lines:[],report:'<script>story</script>'});
  assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<script>/);
});

test('optional notices have separate closed disclosures and keep video links usable',()=>{
  const notices=feature('chapter-notices.js','ChapterNotices');
  const html=notices.html({chapter:{video:{url:'/api/video/test'}},lines:[{emotion_source:'ai'}],report:'An invented report.',
    missing_takes:['Ada|angry'],emotions:[{key:'angry',label:'Angry'}]});
  assert.equal((html.match(/data-chapter-notice=/g)||[]).length,7);
  assert.doesNotMatch(html,/<details[^>]*\sopen(?:\s|>)/);
  assert.match(html,/Open video/);assert.match(html,/id="show-video"/);
  assert.match(html,/aria-label="Analysis report"/);assert.match(html,/angry for Ada/);
  assert.match(html,/Your choices are kept/);
  assert.match(html,/data-review-go="proposed"/);assert.doesNotMatch(html,/Review them in Lines to review/);
});

test('review controls are yellow only for their own pending items, and green otherwise',()=>{
  const notices=feature('chapter-notices.js','ChapterNotices');
  const html=notices.html({chapter:{video:{}},lines:[{speaker:'Ada',basis:'context',emotion_source:'manual'}],report:'Done.'});
  assert.match(html,/chapter-notice warning" data-chapter-notice="context"/);
  assert.match(html,/data-review-go="context"/);
  for(const key of ['missing','proposed','pacing'])assert.match(html,new RegExp(`chapter-notice complete" data-chapter-notice="${key}"`));
  const fresh=notices.html({chapter:{video:{}},lines:[],manual_draft:true});
  assert.match(fresh,/data-chapter-notice="manual"/);
  assert.doesNotMatch(fresh,/chapter-notice complete/);
});

test('manual recovery, unassigned lines and character approval share compact closed controls',()=>{
  const notices=feature('chapter-notices.js','ChapterNotices');
  const html=notices.html({manual_draft:true,chapter:{video:{}},lines:[{speaker:'Unassigned'},{speaker:'Ada'}],
    blockers:[{name:'Ada',label:'<Ada>'}]});
  assert.equal((html.match(/data-chapter-notice=/g)||[]).length,3);
  assert.doesNotMatch(html,/<details[^>]*\sopen(?:\s|>)/);
  assert.doesNotMatch(html,/class="banner/);
  assert.match(html,/id="save-manual"/);assert.match(html,/data-unassigned/);
  assert.match(html,/data-review-character="Ada"/);assert.match(html,/Review &lt;Ada&gt;/);
  assert.match(html,/data-queue-go="1"/);
});

test('one notice opens at a time; Close and Escape restore focus without leaving the page',()=>{
  const notes=[{open:true},{open:false}];notes.forEach(note=>{note.querySelector=()=>({focus(){note.focused=true;}});});
  const bar={querySelectorAll:()=>notes};feature('chapter-notices.js','ChapterNotices').bind({querySelector:()=>bar});
  const target=(note,kind)=>({closest:selector=>selector==='[data-chapter-notice]'?note:selector===kind?{}:null});
  bar.onclick({target:target(notes[1],'summary')});assert.equal(notes[0].open,false);
  notes[1].open=true;bar.onclick({target:target(notes[1],'[data-notice-close]')});assert.equal(notes[1].open,false);assert.equal(notes[1].focused,true);
  notes[0].open=true;let stopped=false;bar.onkeydown({key:'Escape',stopPropagation(){stopped=true;}});
  assert.equal(notes[0].open,false);assert.equal(notes[0].focused,true);assert.equal(stopped,true);
});

test('going to a line closes its notice without stealing focus from the destination',()=>{
  const note={open:true,querySelector:()=>({focus(){throw Error('Do not steal destination focus');}})};
  const bar={querySelectorAll:()=>[note]};feature('chapter-notices.js','ChapterNotices').bind({querySelector:()=>bar});
  bar.onclick({target:{closest:selector=>selector==='[data-chapter-notice]'?note:selector.includes('[data-queue-go]')?{}:null}});
  assert.equal(note.open,false);
});
