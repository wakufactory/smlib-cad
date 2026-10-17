const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const values = {
  mode: 'text', source: 'box first 0 0 0 1 1 1', chord: '0.08', angle: '20',
  finish: 'none', 'finish-size': '1', sample: 'default'
};
const elements = Object.fromEntries(Object.entries(values).map(([id, value]) =>
  [id, {value, disabled: false, labels: [{textContent: id}], checkValidity: () => true}]));
for (const id of ['message', 'status', 'preview', 'export', 'export-usdz', 'save-model', 'load-model', 'model-file', 'shading-mode', 'example']) {
  elements[id] = elements[id] || {value: '', disabled: false};
}
elements.message.style = {};
elements.source.addEventListener = () => {};
elements.canvas = {getContext: () => null, addEventListener() {}};
let savedBlob, downloadName;
const context = vm.createContext({
  Blob, console, setTimeout: () => {},
  URL: {createObjectURL(blob) {savedBlob = blob; return 'blob:test';}, revokeObjectURL() {}},
  document: {
    getElementById: id => elements[id],
    createElement: () => ({click() {downloadName = this.download;}})
  },
  ResizeObserver: class {observe() {}},
  fetch: async () => {throw Error('No server request expected');}
});
vm.runInContext(fs.readFileSync(require.resolve('../app.js'), 'utf8'), context);
const ModelFile = vm.runInContext('ModelFile', context);
vm.runInContext('examples = {circular: "group ring\\nend", sweeps: "profile p\\npolygon 0 0 1 0 0 1\\nend"}', context);
for (const [sample, source] of [
  ['circular', 'group ring\nend'],
  ['sweeps', 'profile p\npolygon 0 0 1 0 0 1\nend']
]) {
  elements.mode.value = 'python';
  elements.sample.value = sample;
  elements.example.onclick();
  assert.equal(elements.mode.value, 'text');
  assert.equal(elements.source.value, source);
}
elements.source.value = values.source;
elements.sample.value = 'default';
let previewCalls = 0;
context.preview = async () => {previewCalls++;};

const document = {
  format: 'smlib-model', version: 1, mode: 'text',
  source: 'box body 0 0 0 10 10 10\n',
  parameters: {chord: 0.02, angle: 12, finish: 'fillet', finishSize: 0.5}
};
assert.equal(JSON.stringify(ModelFile.parse(JSON.stringify(document))), JSON.stringify(document));
for (const invalid of [
  {...document, version: 2},
  {...document, mode: 'other'},
  {...document, source: 5},
  {...document, parameters: {...document.parameters, chord: 0}},
  {...document, parameters: {...document.parameters, angle: 91}},
  {...document, parameters: {...document.parameters, finish: 'other'}},
  {...document, parameters: {...document.parameters, finishSize: null}}
]) assert.throws(() => ModelFile.parse(JSON.stringify(invalid)));

(async () => {
  elements.chord.value = '0.02';
  elements.angle.value = '12';
  elements.finish.value = 'fillet';
  elements['finish-size'].value = '0.5';
  elements['save-model'].onclick();
  assert.equal(downloadName, 'model.json');
  const json = await savedBlob.text();
  elements.source.value = 'box changed 0 0 0 2 2 2';
  elements.chord.value = '0.8';
  await context.loadModel({name: 'model.json', size: json.length, text: async () => json});
  assert.equal(previewCalls, 1);
  assert.equal(elements.source.value, values.source);
  assert.equal(elements.chord.value, 0.02);
  assert.equal(elements.angle.value, 12);
  assert.equal(elements.finish.value, 'fillet');
  assert.equal(elements['finish-size'].value, 0.5);
  assert.equal(elements['finish-size'].disabled, false);

  const pythonSource = 'result = sm.create_box((0, 0, 0), 2, 3, 4)\n';
  for (const id of ['chord', 'angle', 'finish-size']) elements[id].value = String(elements[id].value);
  elements.mode.value = 'python';
  elements.mode.onchange();
  assert.equal(elements['save-model'].disabled, false);
  elements.source.value = pythonSource;
  elements['save-model'].onclick();
  const pythonJson = await savedBlob.text();
  assert.equal(JSON.parse(pythonJson).mode, 'python');
  elements.mode.value = 'text';
  elements.source.value = 'box changed 0 0 0 1 1 1';
  await context.loadModel({name: 'python.json', size: pythonJson.length, text: async () => pythonJson});
  assert.equal(elements.mode.value, 'python');
  assert.equal(elements.source.value, pythonSource);
  assert.equal(previewCalls, 2);

  const before = elements.source.value;
  await context.loadModel({name: 'bad.json', size: 4, text: async () => '{bad'});
  assert.equal(previewCalls, 2);
  assert.equal(elements.source.value, before);
  assert.match(elements.message.textContent, /JSONを読み込めません/);
  console.log('model-file UI: text/Python save, restore, auto-preview, and invalid-file preservation passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
