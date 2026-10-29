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
  characters: ['Ada', 'Morgan', 'Guard', 'Clerk', 'Cook'].map((name) => ({name})),
  registry: {
    reading: {Morgan: 'Morgan', Guard: 'Morgan', Clerk: 'Narrator'},
    document: {organization: {
      categories: [{id: 'cast', voice: 'own'}, {id: 'extras', voice: 'Morgan'}],
      characters: {Ada: {category: 'cast'}, Morgan: {category: 'extras'}, Guard: {category: 'extras'},
                   Clerk: {category: 'cast'}, Cook: {category: 'cast'}},
    }},
  },
};

test('voice checks compare only characters of an own-voice category who read with their own voice', () => {
  assert.deepEqual([...sandbox.main(data)].sort(), ['Ada', 'Cook']);
});

test('without a character organisation every character still counts', () => {
  assert.deepEqual([...sandbox.main({characters: [{name: 'Ada'}, {name: 'Cook'}]})].sort(), ['Ada', 'Cook']);
});
