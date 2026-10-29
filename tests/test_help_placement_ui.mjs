import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../app/web/app.js', import.meta.url), 'utf8');
const place = source.slice(source.indexOf('function placeFieldHelp('), source.indexOf('function bindFieldHelp('));

function note({anchor, size, window = {width: 400, height: 700}}) {
  const box = {style: {}, offsetWidth: size.width, offsetHeight: size.height};
  const tip = {querySelector: (selector) => (selector === 'button'
    ? {getBoundingClientRect: () => ({top: anchor.top, bottom: anchor.top + 28, right: anchor.right})} : box)};
  const sandbox = {innerWidth: window.width, innerHeight: window.height};
  vm.createContext(sandbox);
  vm.runInContext(place + ';this.place=placeFieldHelp', sandbox);
  sandbox.place(tip);
  return {left: parseFloat(box.style.left), top: parseFloat(box.style.top)};
}

test('a note opens above its button and ends where the button ends', () => {
  const at = note({anchor: {top: 400, right: 300}, size: {width: 250, height: 100}});
  assert.deepEqual(at, {left: 50, top: 294});
});

test('a note that would leave the window on the left is moved back inside it', () => {
  const at = note({anchor: {top: 400, right: 120}, size: {width: 250, height: 100}});
  assert.equal(at.left, 8);
});

test('a note near the top of the window opens below its button', () => {
  const at = note({anchor: {top: 20, right: 300}, size: {width: 250, height: 100}});
  assert.equal(at.top, 20 + 28 + 6);
});

test('a note taller than the room is kept inside the window', () => {
  const at = note({anchor: {top: 40, right: 300}, size: {width: 250, height: 690}, window: {width: 400, height: 700}});
  assert.ok(at.top >= 8 && at.top + 690 <= 700 + 8, JSON.stringify(at));
});
