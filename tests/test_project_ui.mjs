import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../app/web/app.js', import.meta.url), 'utf8');
const helper = source.slice(source.indexOf('const PROJECT_PARTS ='), source.indexOf('/* ---------- start ---------- */'));
const esc = source.split('\n').find(line => line.startsWith('const esc ='));

function context() {
  const elements = new Map(), calls = [], choices = [];
  const element = selector => {
    if (!elements.has(selector)) elements.set(selector, {innerHTML:'',disabled:false,textContent:''});
    return elements.get(selector);
  };
  const sandbox = {view:{innerHTML:''}, $:element, $$:selector => selector.endsWith(':checked') ? choices : [],
    icon:()=>'', toast:()=>{}, guard:async action=>action(), modal:async()=>false,
    api:async (path, options) => {calls.push([path,options]);return {backups:[],last_import:null};}};
  vm.runInNewContext(esc+'\n'+helper, sandbox);
  return {sandbox,elements,calls,element};
}

test('project page leaves book assignments off and escapes backup names', async () => {
  const c = context();
  c.sandbox.api = async()=>({backups:['<img src=x onerror=unsafe()>'],last_import:null});
  await c.sandbox.viewProject();
  assert.match(c.sandbox.view.innerHTML,/data-export-part="cast" checked/);
  assert.match(c.sandbox.view.innerHTML,/data-export-part="volumes" >/);
  assert.match(c.sandbox.view.innerHTML,/&lt;img src=x onerror=unsafe\(\)&gt;/);
  assert.doesNotMatch(c.sandbox.view.innerHTML,/<img/);
});

test('import preview escapes untrusted fields and disables apply after changing choices', async () => {
  const c = context();
  vm.runInNewContext(`importPreview={path:'<script>unsafe()</script>',changes:1,
    summary:{parts:['settings','cast']},choices:{parts:['cast'],characters:[],voices:[],scripts:[],locations:{}},
    items:[{kind:'voice',name:'<img>',action:'skip',reason:'<script>',conflict:true}],ignored:['<iframe>']};`,c.sandbox);
  c.sandbox.drawImportPreview();
  const html=c.element('#import-preview').innerHTML;
  assert.doesNotMatch(html,/<script>|<img>|<iframe>/);
  assert.match(html,/&lt;script&gt;/);
  assert.match(html,/data-import-part="settings" >/);
  assert.match(html,/data-conflict-name="&lt;img&gt;" >/);
  // Dispatch the actual change handler registered by the production renderer.
  let changed;
  c.sandbox.$$ = selector => selector==='[data-import-part], [data-conflict-kind]' ? [{set onchange(fn){changed=fn;}}] : [];
  c.sandbox.drawImportPreview();
  changed();
  assert.equal(c.element('#apply-import').disabled,true);
  assert.match(c.element('#preview-note').textContent,/Update the preview/);
});

test('cancelling the final import confirmation sends no apply request', async () => {
  const c = context();
  vm.runInNewContext(`importPreview={path:'demo.abstudio',changes:1,summary:{parts:['cast']},
    choices:{parts:['cast'],characters:[],voices:[],scripts:[],locations:{}},items:[],ignored:[]};`,c.sandbox);
  c.sandbox.drawImportPreview();
  await c.element('#apply-import').onclick({currentTarget:{}});
  assert.equal(c.calls.length,0);
});

test('cast-only export confirmation warns about references even without book assignments', async () => {
  const c=context();
  await c.sandbox.viewProject();
  c.sandbox.api=async()=>({parts:['cast'],path:'voice-pack.abstudio',characters:1,voices:1,
    volumes:0,scripts:0,bytes:1024,contains_book_text:false});
  let message='';
  c.sandbox.modal=async(title,html)=>{message=html;return false;};
  await c.element('#export-project').onclick({currentTarget:{}});
  assert.match(message,/references, transcripts and notes may contain private material/);
});
