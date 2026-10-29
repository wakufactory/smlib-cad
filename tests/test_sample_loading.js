const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const elements = {
  sample: {value: 'default'},
  source: {value: '', scrollTop: 0, addEventListener() {}},
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
  fetch: () => new Promise(() => {}), console
});
vm.runInContext(fs.readFileSync(require.resolve('../app.js'), 'utf8'), context);
vm.runInContext(`
  preview = () => {};
  examples = {text:'basic text', python:'basic python', gallery:'gallery text', variants:{
    default:{text:'basic text',python:'basic python'},
    gallery:{text:'gallery text',python:'gallery python\\nsecond line'},
    groups:{python:'groups python'},
    offsets:{text:'offsets text'}
  }};
`, context);
function load(sample, mode, expectedMode, source) {
  elements.sample.value = sample;
  elements.mode.value = mode;
  elements.example.onclick();
  assert.equal(elements.mode.value, expectedMode);
  assert.equal(elements.source.value, source);
  assert.equal(elements['source-line-numbers-inner'].textContent,
    source.split('\n').map((_, i) => i + 1).join('\n'));
}
load('gallery', 'python', 'python', 'gallery python\nsecond line');
load('gallery', 'text', 'text', 'gallery text');
load('groups', 'text', 'python', 'groups python');
load('groups', 'python', 'python', 'groups python');
load('offsets', 'python', 'text', 'offsets text');
load('default', 'python', 'python', 'basic python');
load('default', 'text', 'text', 'basic text');
elements.sample.value = 'missing';
elements.example.onclick();
assert.equal(elements.source.value, 'basic text');
vm.runInContext("delete examples.variants", context);
load('gallery', 'python', 'text', 'gallery text');
assert.match(fs.readFileSync(require.resolve('../index.html'), 'utf8'), /option value="groups"/);
console.log('sample loading: mode variants, fallback, Python groups, and line numbers passed');
