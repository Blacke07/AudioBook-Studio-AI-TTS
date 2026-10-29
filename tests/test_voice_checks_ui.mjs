import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../app/web/app.js', import.meta.url), 'utf8');
const region = source.slice(source.indexOf('function mainCastNames('), source.indexOf('function drawCharacters()'));
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(region + ';this.main=mainCastNames', sandbox);

const data = {
  characters: [...['Ada', 'Morgan', 'Guard', 'Cook'].map((name) => ({name, own_voice: true})),
    {name: 'Mother', own_voice: false}, {name: 'Mature man', library: true, own_voice: true}],
  registry: {reading: {Guard: 'Mature man', Mother: 'Mature man', Morgan: 'Narrator'}},
};

test('voice checks compare only characters who read with their own voice, never the shared voices or those without a voice', () => {
  assert.deepEqual([...sandbox.main(data)].sort(), ['Ada', 'Cook']);
});

test('without a character organisation every character still counts', () => {
  assert.deepEqual([...sandbox.main({characters: [{name: 'Ada'}, {name: 'Cook'}]})].sort(), ['Ada', 'Cook']);
});
