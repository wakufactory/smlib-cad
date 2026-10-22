const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync(require.resolve('../index.html'), 'utf8');
assert.match(html, /id="source-line-numbers"[^>]*aria-hidden="true"/);
assert.match(html, /<textarea id="source" wrap="off"/);

const sourceEvents = {};
const elements = {
  source: {value: '', scrollTop: 0, addEventListener(name, fn) {sourceEvents[name] = fn;}},
  'source-line-numbers': {style: {}},
  'source-line-numbers-inner': {style: {}},
  canvas: {addEventListener() {}},
  'usd-model': {removeAttribute() {}},
  message: {style: {}}
};
const context = vm.createContext({
  document: {getElementById: id => elements[id] ||= {addEventListener() {}, style: {}}},
  window: {}, location: {protocol: 'http:'},
  ResizeObserver: class {observe() {}},
  fetch: () => new Promise(() => {}),
  console
});
vm.runInContext(fs.readFileSync(require.resolve('../app.js'), 'utf8'), context);

const numbers = elements['source-line-numbers-inner'];
assert.equal(numbers.textContent, '1');
elements.source.value = 'box a\n\nbox b\n';
sourceEvents.input();
assert.equal(numbers.textContent, '1\n2\n3\n4');
elements.source.scrollTop = 26.5;
sourceEvents.scroll();
assert.equal(numbers.style.transform, 'translateY(-26.5px)');
elements.source.value = 'single line';
context.refreshSourceLines();
assert.equal(numbers.textContent, '1');
assert.equal(elements['source-line-numbers'].style.width, 'calc(2ch + 20px)');
console.log('source line numbers: typing, trailing newline, scrolling, and programmatic updates passed');
