import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const read=name=>readFileSync(new URL('../app/web/'+name,import.meta.url),'utf8');
const workflow=read('workflow.js');
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function ui(accept=true){
  const calls=[],messages=[],dialogs=[];
  const context={window:{addEventListener(){}},document:{addEventListener(){}},esc,
    modal:async(...args)=>{dialogs.push(args);return accept;},toast:t=>messages.push(t),pollNow:()=>calls.push('poll'),
    api:async(path,options)=>calls.push({path,...options}),selected:new Set(),icon:()=>''};
  vm.runInNewContext(workflow+'\nthis.ui=ChapterWorkflow;',context);
  return{...context.ui,calls,messages,dialogs};
}
test('Review speakers queues a distinct Gemma pass only for eligible chapters after confirmation',async()=>{
  const review=ui();await review.reviewSpeakers('Lantern',[{stem:'001',speaker_review_count:2},{stem:'002',speaker_review_count:0}]);
  assert.deepEqual(JSON.parse(JSON.stringify(review.calls[0])),{path:'/api/run',method:'POST',body:{volume:'Lantern',stems:['001'],steps:['review']}});
  assert.equal(review.calls[1],'poll');assert.match(review.dialogs[0][1],/before and after/);
  assert.match(review.messages[0],/Speaker review queued/);
});
test('cancel and no uncertain lines never start Gemma or silently reanalyze a chapter',async()=>{
  const cancelled=ui(false);await cancelled.reviewSpeakers('Lantern',[{stem:'001',speaker_review_count:2}]);assert.equal(cancelled.calls.length,0);
  const empty=ui();await empty.reviewSpeakers('Lantern',[{stem:'001',speaker_review_count:0}]);
  assert.equal(empty.calls.length,0);assert.match(empty.messages[0],/No uncertain/);
});
test('the volume button preserves the chapter selection and invokes review instead of a table filter',async()=>{
  const source=read('app.js'),start=source.indexOf('  $("#review-text").onclick'),end=source.indexOf('  $("#diagnose-text")',start);
  const button={},calls=[];
  vm.runInNewContext(source.slice(start,end),{$:()=>button,guard:fn=>fn(),name:'Lantern',
    selected:new Set(['002']),chapters:[{stem:'001'},{stem:'002'}],ChapterWorkflow:{reviewSpeakers:async(...args)=>calls.push(args)}});
  await button.onclick({currentTarget:button});
  assert.deepEqual(JSON.parse(JSON.stringify(calls)),[['Lantern',[{stem:'002'}]]]);
});
