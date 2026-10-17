const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const values = {
  mode: 'text', source: 'box first 0 0 0 1 1 1', chord: '0.08', angle: '20',
  finish: 'none', 'finish-size': '1', sample: 'default', 'file-name': 'model'
};
const elements = Object.fromEntries(Object.entries(values).map(([id, value]) =>
  [id, {value, disabled: false, labels: [{textContent: id}], checkValidity: () => true}]));
for (const id of ['message', 'status', 'preview', 'export', 'export-usdz', 'save-model', 'load-model', 'model-file', 'shading-mode', 'preview-mode', 'usd-model', 'model-status', 'hint', 'example']) {
  elements[id] = elements[id] || {value: '', disabled: false};
}
elements['preview-mode'].value = 'webgl';
elements['usd-model'].ready = Promise.resolve();
elements.message.style = {};
elements.source.addEventListener = () => {};
elements.canvas = {getContext: () => null, addEventListener() {}};
let savedBlob, downloadName;
let exportPath, allowExport = false;
const context = vm.createContext({
  Blob, console, setTimeout: () => {},
  URL: {createObjectURL(blob) {savedBlob = blob; return 'blob:test';}, revokeObjectURL() {}},
  document: {
    getElementById: id => elements[id],
    createElement: () => ({click() {downloadName = this.download;}})
  },
  ResizeObserver: class {observe() {}},
  location: {protocol: 'https:'},
  window: {isSecureContext: true, HTMLModelElement: class {}},
  fetch: async path => {
    if (allowExport && path === '/preview/usdz') {
      exportPath = path;
      return {ok: true, json: async () => ({url: '/preview/assets/test.usdz'})};
    }
    if (allowExport && (path === '/export' || path === '/export/usdz')) {
      exportPath = path;
      return {ok: true, blob: async () => new Blob(['test'])};
    }
    throw Error('No server request expected');
  }
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
const actualPreview = context.preview;
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
  elements['file-name'].value = 'engine block.glb';
  elements['save-model'].onclick();
  assert.equal(downloadName, 'engine block.json');
  allowExport = true;
  await elements.export.onclick();
  assert.equal(exportPath, '/export');
  assert.equal(downloadName, 'engine block.glb');
  await elements['export-usdz'].onclick();
  assert.equal(exportPath, '/export/usdz');
  assert.equal(downloadName, 'engine block.usdz');
  elements['file-name'].value = '  ';
  exportPath = undefined;
  await elements['export-usdz'].onclick();
  assert.equal(exportPath, undefined);
  assert.match(elements.message.textContent, /保存ファイル名/);
  elements['file-name'].value = 'folder/model';
  assert.throws(() => context.saveFileName('glb'), /保存ファイル名/);
  elements['file-name'].value = 'model';
  elements['save-model'].onclick();
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
  assert.equal(elements['file-name'].value, 'model');

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
  assert.equal(elements['file-name'].value, 'python');

  const before = elements.source.value;
  const nameBefore = elements['file-name'].value;
  await context.loadModel({name: 'bad.json', size: 4, text: async () => '{bad'});
  assert.equal(previewCalls, 2);
  assert.equal(elements.source.value, before);
  assert.equal(elements['file-name'].value, nameBefore);
  assert.match(elements.message.textContent, /JSONを読み込めません/);
  context.preview = actualPreview;
  elements['preview-mode'].value = 'model';
  await actualPreview();
  assert.equal(exportPath, '/preview/usdz');
  assert.equal(elements['usd-model'].src, '/preview/assets/test.usdz');
  assert.equal(elements.canvas.hidden, true);
  assert.equal(elements['usd-model'].hidden, false);
  context.location.protocol = 'http:';
  elements['preview-mode'].onchange();
  assert.equal(elements['preview-mode'].value, 'webgl');
  assert.equal(elements.canvas.hidden, false);
  assert.match(elements.message.textContent, /HTTPS/);
  console.log('model-file UI: text/Python save, restore, auto-preview, and invalid-file preservation passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
