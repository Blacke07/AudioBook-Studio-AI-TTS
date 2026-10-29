import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../app/web/character-registry.js', import.meta.url), 'utf8');
const region = source.slice(source.indexOf('const CATEGORY_COLORS'), source.indexOf('/* One staged registry'));
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(region + ';this.style=categoryStyle;this.palette=CATEGORY_COLORS', sandbox);

test('a category with a hex color marks its section with that color', () => {
  assert.equal(sandbox.style({color: '#5b9bff'}), ' style="--category-color:#5b9bff"');
});

test('a missing or malformed color adds nothing, so a stored value can never inject markup', () => {
  for (const bad of [{}, undefined, {color: ''}, {color: 'blue'}, {color: '#12345'}, {color: '#5b9bff" onclick="x'}]) {
    assert.equal(sandbox.style(bad), '');
  }
});

test('every palette color is a valid hex value', () => {
  assert.ok(sandbox.palette.length >= 10);
  for (const [, value] of sandbox.palette) assert.match(value, /^#[0-9a-f]{6}$/);
});
