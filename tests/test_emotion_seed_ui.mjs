import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../app/web/app.js', import.meta.url), 'utf8');
const extract = name => source.match(new RegExp(`function ${name}[\\s\\S]*?\\n}\\n`))[0];
const {emotionTakesHtml} = vm.runInNewContext(`const esc = s => String(s).replaceAll('"','&quot;'); const icon = () => ''; const fieldHelp = () => '';
${extract('emotionTakesHtml')}\n({emotionTakesHtml})`);

function setup() {
  const controls = new Map();
  const get = selector => {
    if (!controls.has(selector)) controls.set(selector, {value:'', textContent:'', dataset:{}, handlers:{}, classList:{toggle(){}}, remove(){}, addEventListener(name,fn){this.handlers[name]=fn;}, focus(){this.focused=true;}});
    return controls.get(selector);
  };
  const seed = get('[data-emotion-seed]'); seed.value = '2608'; seed.dataset.neutralSeed = '2608';
  seed.reportValidity = () => seed.value !== '' && Number.isInteger(Number(seed.value)) && +seed.value >= 0 && +seed.value <= 2147483647;
  get('b').textContent = 'Shouting'; get('[data-emotion-text]').value = 'An invented audition line.';
  const box = {dataset:{emotionTake:'shouting'},open:true,closest(){return {};}};
  const calls = []; let refreshed = 0;
  const state = {$:get, $$:selector=>selector==='[data-emotion-take]'?[box]:[], bindFieldHelp(){},
    esc:String, icon:()=>'', toast(){}, guard:async fn=>fn(), modal:async()=>true,
    api:async(path,request)=>{calls.push({path,body:request.body});return {fixed:{takes:path.endsWith('/unfix')?{}:{shouting:{}}},url:'/probe.wav',path:'work/previews/probe.wav',text:'Invented.',seed:request.body.seed,same_voice:-.14,recipe_source:'saved reference description'};}};
  vm.runInNewContext(`${extract('bindEmotionTakes')}\nthis.bind=bindEmotionTakes;`,state);
  state.bind({},'Ada',async()=>{refreshed++;});
  const click = selector => get(selector).onclick({currentTarget:get(selector)});
  return {get,seed,calls,click,box,refreshed:()=>refreshed};
}

test('emotion seed control uses the approved seed and a saved emotional take seed when available',()=>{
  const html=emotionTakesHtml({url:'/neutral.wav',origin:{seed:2608},takes:{shouting:{url:'/shout.wav',origin:{seed:2711}}}}, {},[{key:'shouting',label:'Shouting'}],99);
  assert.match(html,/data-neutral-seed="2608" value="2711"/);
  assert.match(html,/type="number" min="0" max="2147483647" step="1" required/);
  assert.match(html,/Use neutral seed/); assert.match(html,/not emotion intensity/);
  assert.match(html,/Compare with neutral voice[\s\S]*src="\/neutral.wav"/);
});

test('manual seed zero is sent exactly and low similarity is explained',async()=>{
  const ui=setup();ui.seed.value='0';await ui.click('[data-emotion-audition]');
  assert.equal(ui.calls[0].body.seed,0);assert.equal(ui.calls[0].body.variant,undefined);
  assert.match(ui.get('[data-emotion-result]').innerHTML,/Very low similarity/);
  assert.match(ui.get('[data-emotion-result]').innerHTML,/does not clone the neutral recording/);
});

test('another take advances the entered seed and reset never starts inference',async()=>{
  const ui=setup();await ui.click('[data-emotion-audition]');
  ui.seed.value='2710';await ui.click('[data-emotion-again]');
  assert.equal(ui.calls[1].body.seed,2711);
  await ui.click('[data-emotion-reset]');assert.equal(ui.seed.value,'2608');assert.equal(ui.calls.length,2);
});

test('invalid manual seeds make no preview request',async()=>{
  for(const value of ['', '-1','1.5','2147483648']){
    const ui=setup();ui.seed.value=value;await ui.click('[data-emotion-audition]');assert.equal(ui.calls.length,0);
  }
});

test('approval keeps the heard seed even when the input is edited afterwards',async()=>{
  const ui=setup();ui.seed.value='42';await ui.click('[data-emotion-audition]');
  ui.seed.value='99';await ui.click('[data-emotion-fix]');
  assert.equal(ui.calls[1].body.origin.seed,42);assert.equal(ui.refreshed(),1);
});

test('approval updates status without replacing the open emotion or discarding its input',async()=>{
  const ui=setup();await ui.click('[data-emotion-audition]');
  const html=ui.get('[data-emotion-result]').innerHTML;
  ui.get('[data-emotion-text]').value='An unsent second audition draft.';
  await ui.click('[data-emotion-fix]');
  assert.equal(ui.box.open,true);assert.equal(ui.get('[data-emotion-result]').innerHTML,html);
  assert.equal(ui.get('[data-emotion-text]').value,'An unsent second audition draft.');
  assert.equal(ui.get('[data-emotion-count]').textContent,'1/1');
  assert.equal(ui.get('[data-emotion-fix]').disabled,true);
  assert.equal(ui.get('[data-emotion-fix]').textContent,'Approved');
  assert.match(ui.get('[data-emotion-feedback]').textContent,/Continue with another emotion/);
  assert.equal(ui.calls.length,2,'No page reload or metadata fetch after approval');
});

test('removing an approved take keeps the panel open and allows explicit reapproval',async()=>{
  const ui=setup();await ui.click('[data-emotion-audition]');await ui.click('[data-emotion-fix]');
  await ui.get('[data-emotion-remove]').handlers.click();
  assert.equal(ui.box.open,true);assert.equal(ui.get('[data-emotion-count]').textContent,'0/1');
  assert.equal(ui.get('[data-emotion-fix]').disabled,false);
  await ui.click('[data-emotion-fix]');
  assert.equal(ui.get('[data-emotion-count]').textContent,'1/1');
});
