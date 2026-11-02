const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync(require.resolve('../index.html'), 'utf8');
assert.match(html, /id="source-line-numbers"[^>]*aria-hidden="true"/);
assert.match(html, /<textarea id="source" wrap="off"/);

const sourceEvents = {};
const animationEvents = {};
const elements = {
  source: {value: '', scrollTop: 0, addEventListener(name, fn) {sourceEvents[name] = fn;}},
  'animation-source': {value: '', scrollTop: 0, addEventListener(name, fn) {animationEvents[name] = fn;}},
  'animation-source-line-numbers': {style: {}},
  'animation-source-line-numbers-inner': {style: {}},
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
const animationNumbers=elements['animation-source-line-numbers-inner'];
assert.match(html, /id="animation-source-line-numbers"[^>]*aria-hidden="true"/);
assert.equal(animationNumbers.textContent,'1');
elements['animation-source'].value='animation loop 4\n\nend\n';
animationEvents.input();
assert.equal(animationNumbers.textContent,'1\n2\n3\n4');
assert.equal(numbers.textContent,'1','editor gutters are independent');
elements['animation-source'].scrollTop=40.5;
animationEvents.scroll();
assert.equal(animationNumbers.style.transform,'translateY(-40.5px)');
elements['animation-source'].value=Array(100).fill('key').join('\n');
context.refreshSourceLines();
assert.equal(elements['animation-source-line-numbers'].style.width,'calc(3ch + 20px)');
assert.equal(animationNumbers.textContent.split('\n').length,100,'programmatic animation replacements refresh line numbers');
elements['animation-source'].value='';
context.refreshSourceLines();
assert.equal(animationNumbers.textContent,'1');
console.log('source line numbers: typing, trailing newline, scrolling, and programmatic updates passed');
