import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=readFileSync(new URL('../app/web/app.js',import.meta.url),'utf8');
const esc=source.split('\n').find(line=>line.startsWith('const esc ='));
const card=source.slice(source.indexOf('function voxcpmCard'),source.indexOf('function bindVoxcpmCard'));
function feature() {
  const state={};
  vm.runInNewContext(esc+'\n'+card+'\nthis.card=voxcpmCard;this.progress=voxcpmProgress;',state);
  return state;
}
const missing={installed:false,job:{running:false,step:'',error:'',log:[]}};

test('without VoxCPM2 the card offers the setup and a link, and no engine choice',()=>{
  const html=feature().card(missing,{engine:'qwen'});
  assert.match(html,/Not installed/);assert.match(html,/id="vox-install"/);assert.match(html,/id="vox-link"/);
  assert.doesNotMatch(html,/id="engine"/);assert.match(html,/<details class="card narrator-fold" id="narrator-engine" open>/);
});
test('with VoxCPM2 installed the card is a closed toggle between Qwen and VoxCPM2',()=>{
  const ui=feature(),installed={installed:true,job:{running:false,step:'',error:'',log:[]}};
  let html=ui.card(installed,{engine:'qwen'});
  assert.match(html,/Installed/);assert.match(html,/id="engine"/);assert.doesNotMatch(html,/id="vox-install"/);
  assert.match(html,/<option value="qwen" selected>/);assert.doesNotMatch(html,/ open>/);
  html=ui.card(installed,{engine:'voxcpm'});
  assert.match(html,/<option value="voxcpm" selected>/);assert.match(html,/id="vox-unlink"/);
});
test('a running setup shows its step and last line and disables the button; an error stays visible',()=>{
  const ui=feature(),running={installed:false,job:{running:true,step:'Installing PyTorch',error:'',log:['a','Collecting torch']}};
  const html=ui.card(running,{engine:'qwen'});
  assert.match(html,/id="vox-install" disabled/);assert.match(html,/Installing PyTorch/);assert.match(html,/Collecting torch/);
  const failed=ui.card({installed:false,job:{running:false,step:'',error:'pip failed: <b>x</b>',log:[]}},{engine:'qwen'});
  assert.match(failed,/Setup stopped/);assert.match(failed,/&lt;b&gt;x&lt;\/b&gt;/);assert.doesNotMatch(failed,/<b>x<\/b>/);
});
test('the engine select is not given to guard(), whose spinner would empty it and send a blank engine',()=>{
  const bind=source.slice(source.indexOf('function bindVoxcpmCard'),source.indexOf('$("#vox-unlink")'));
  assert.doesNotMatch(bind,/\},\s*e\.target\)\)/);
  assert.match(bind,/value = select\.value/);
});
