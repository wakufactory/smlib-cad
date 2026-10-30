const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require.resolve('../index.html'), 'utf8');
const leftPane = html.split('</aside>')[0];
const leftMarkup = html.split('<main><aside>')[1].split('</aside>')[0];
const viewport = html.split('</aside>')[1].split('<section class="source-pane"')[0];
assert(leftMarkup.trimStart().startsWith('<div id="message" role="status"></div>'));
assert(!/<details id="command-reference"[^>]*\sopen(?:\s|>)/.test(leftMarkup));
assert(leftMarkup.lastIndexOf('id="grid-settings"') > leftMarkup.lastIndexOf('id="export-usdz"'));
assert(leftMarkup.trimEnd().endsWith('</div>'), 'grid settings are the last left-pane element');
for(const id of ['show-grid','grid-spacing','grid-plane','grid-offset']){
  assert(leftPane.includes(`id="${id}"`), `${id} belongs in the left settings pane`);
  assert(!viewport.includes(`id="${id}"`));
}
assert.match(viewport, /id="projection-mode"[^>]*><option value="orthographic">平行投影<\/option>/);

const values = {
  mode: 'text', source: 'box first 0 0 0 1 1 1', chord: '0.08', angle: '20',
  finish: 'none', 'finish-size': '1', sample: 'default', 'file-name': 'model',
  'export-scale': '1', 'grid-spacing':'1', 'grid-plane':'xy', 'grid-offset':'0', 'projection-mode':'orthographic'
};
const elements = Object.fromEntries(Object.entries(values).map(([id, value]) =>
  [id, {value, disabled: false, labels: [{textContent: id}], checkValidity: () => true}]));
for (const id of ['message', 'status', 'preview', 'export', 'export-usdz', 'object-tree', 'mesh-stats', 'export-stats-glb', 'export-stats-usdz', 'save-model', 'load-model', 'model-file', 'shading-mode', 'preview-mode', 'view-controls', 'show-axes', 'show-grid', 'usd-model', 'model-status', 'hint', 'example']) {
  elements[id] = elements[id] || {value: '', disabled: false};
}
elements['preview-mode'].value = 'webgl';
elements['show-axes'].checked = true;
elements['show-grid'].checked = true;
elements['usd-model'].ready = Promise.resolve();
elements.message.style = {};
elements.source.addEventListener = () => {};
elements.canvas = {getContext: () => null, addEventListener() {}};
let savedBlob, downloadName;
let exportPath, requestBody, allowExport = false;
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
  fetch: async (path, options) => {
    if(options)requestBody=JSON.parse(options.body);
    if (allowExport && path === '/preview/usdz') {
      exportPath = path;
      return {ok: true, json: async () => ({url: '/preview/assets/test.usdz', objects: [{name:'body',groupPath:[{name:'assembly'}]}]})};
    }
    if (allowExport && (path === '/export' || path === '/export/usdz')) {
      exportPath = path;
      return {ok: true, headers: new Map([['X-Mesh-Count', '3'], ['X-Material-Count', path === '/export' ? '2' : '1']]), blob: async () => new Blob(['test'])};
    }
    throw Error('No server request expected');
  }
});
vm.runInContext(fs.readFileSync(require.resolve('../app.js'), 'utf8'), context);
const ModelFile = vm.runInContext('ModelFile', context);
assert.equal(context.gridPoints([0, 0, 0], [0, 0, 0]).length / 3, 25);
assert.equal(context.gridPoints([0, 0, 0], [1000, 1000, 0]).length / 3, 101 * 101);
assert.equal(context.gridPoints([1e9, 0, 0], [1e9 + 1, 1, 0]).length, 0);
let previewCalls = 0;
const actualPreview = context.preview;
context.preview = async () => {previewCalls++;};
vm.runInContext('examples = {circular: "group ring\\nend", sweeps: "profile p\\npolygon 0 0 1 0 0 1\\nend", functions: "fn size(x) = x * 2\\nbox body 0 0 0 ${size(2)} 1 1"}', context);
for (const [sample, source] of [
  ['circular', 'group ring\nend'],
  ['sweeps', 'profile p\npolygon 0 0 1 0 0 1\nend'],
  ['functions', 'fn size(x) = x * 2\nbox body 0 0 0 ${size(2)} 1 1']
]) {
  elements.mode.value = 'python';
  elements.sample.value = sample;
  elements.example.onclick();
  assert.equal(elements.mode.value, 'text');
  assert.equal(elements.source.value, source);
}
assert.equal(previewCalls, 3, 'loading each sample automatically previews');
elements.source.value = values.source;
elements.sample.value = 'default';
previewCalls = 0;

const document = {
  format: 'smlib-model', version: 1, mode: 'text',
  source: 'box body 0 0 0 10 10 10\n',
  parameters: {chord: 0.02, angle: 12, finish: 'fillet', finishSize: 0.5, exportScale: 2.5}
};
assert.equal(JSON.stringify(ModelFile.parse(JSON.stringify(document))), JSON.stringify(document));
assert.equal(ModelFile.parse(JSON.stringify({...document, parameters: {...document.parameters, exportScale: undefined}})).parameters.exportScale, 1);
for (const invalid of [
  {...document, version: 2},
  {...document, mode: 'other'},
  {...document, source: 5},
  {...document, parameters: {...document.parameters, chord: 0}},
  {...document, parameters: {...document.parameters, angle: 91}},
  {...document, parameters: {...document.parameters, finish: 'other'}},
  {...document, parameters: {...document.parameters, finishSize: null}},
  {...document, parameters: {...document.parameters, exportScale: 0}},
  {...document, parameters: {...document.parameters, exportScale: '2'}}
]) assert.throws(() => ModelFile.parse(JSON.stringify(invalid)));

(async () => {
  elements.chord.value = '0.02';
  elements.angle.value = '12';
  elements.finish.value = 'fillet';
  elements['finish-size'].value = '0.5';
  elements['export-scale'].value = '2.5';
  elements['save-model'].onclick();
  assert.equal(downloadName, 'model.json');
  elements['file-name'].value = 'engine block.glb';
  elements['save-model'].onclick();
  assert.equal(downloadName, 'engine block.json');
  allowExport = true;
  await elements.export.onclick();
  assert.equal(exportPath, '/export');
  assert.equal(requestBody.exportScale, 2.5);
  assert.equal(downloadName, 'engine block.glb');
  assert.equal(elements['export-stats-glb'].textContent, 'GLB: mesh数 3 / material数 2');
  assert.match(elements.message.textContent, /mesh数 3 \/ material数 2/);
  await elements['export-usdz'].onclick();
  assert.equal(exportPath, '/export/usdz');
  assert.equal(requestBody.exportScale, 2.5);
  assert.equal(downloadName, 'engine block.usdz');
  assert.equal(elements['export-stats-usdz'].textContent, 'USDZ: mesh数 3 / material数 1');
  assert.equal(elements['export-stats-glb'].textContent, 'GLB: mesh数 3 / material数 2');
  elements['export-scale'].value = '0';
  exportPath = undefined;
  await elements.export.onclick();
  assert.equal(exportPath, undefined);
  assert.match(elements.message.textContent, /座標倍率/);
  assert.equal(elements['export-stats-glb'].textContent, 'GLB: mesh数 3 / material数 2');
  elements['export-scale'].value = '2.5';
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
  assert.equal(JSON.parse(json).parameters.exportScale, 2.5);
  elements.source.value = 'box changed 0 0 0 2 2 2';
  elements.chord.value = '0.8';
  await context.loadModel({name: 'model.json', size: json.length, text: async () => json});
  assert.equal(previewCalls, 1);
  assert.equal(elements.source.value, values.source);
  assert.equal(elements.chord.value, 0.02);
  assert.equal(elements.angle.value, 12);
  assert.equal(elements.finish.value, 'fillet');
  assert.equal(elements['finish-size'].value, 0.5);
  assert.equal(elements['export-scale'].value, 2.5);
  assert.equal(elements['finish-size'].disabled, false);
  assert.equal(elements['file-name'].value, 'model');

  const pythonSource = 'result = sm.create_box((0, 0, 0), 2, 3, 4)\n';
  for (const id of ['chord', 'angle', 'finish-size', 'export-scale']) elements[id].value = String(elements[id].value);
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
  elements['export-scale'].value = String(elements['export-scale'].value); // HTML input values are strings.
  elements['preview-mode'].value = 'model';
  await actualPreview();
  assert.equal(exportPath, '/preview/usdz', elements.message.textContent);
  assert.equal(requestBody.exportScale, 2.5);
  assert.equal(elements['usd-model'].src, '/preview/assets/test.usdz');
  assert.equal(elements['object-tree'].textContent, '└─ assembly (group)\n   └─ body');
  assert.equal(elements.canvas.hidden, true);
  assert.equal(elements['usd-model'].hidden, false);
  assert.equal(elements['view-controls'].hidden, true);
  assert.equal(elements['projection-mode'].hidden, true);
  context.location.protocol = 'http:';
  elements['preview-mode'].onchange();
  assert.equal(elements['preview-mode'].value, 'webgl');
  assert.equal(elements.canvas.hidden, false);
  assert.equal(elements['view-controls'].hidden, false);
  assert.equal(elements['projection-mode'].hidden, false);
  assert.equal(elements['show-axes'].checked, true);
  assert.equal(elements['show-grid'].checked, true);
  assert.match(elements.message.textContent, /HTTPS/);
  context.preview = async () => {previewCalls++;};
  const image={name:'reference.png',dataUrl:'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aDm8AAAAASUVORK5CYII='};
  const chat = {version:1,messages:[{role:'user',text:'幅を2にして',images:[image]}, {role:'assistant',text:'幅を変更しました。'}, {role:'system',text:'計算エラー',error:true}]};
  let restored, blocked = false;
  context.ModelChat = {snapshot:()=>chat, restore:value=>{restored=value;}, assertIdle:()=>{if(blocked)throw Error('応答待ち');}};
  for(const id of ['chord','angle','finish-size','export-scale'])elements[id].value=String(elements[id].value);
  elements['save-model'].onclick();
  const savedChatJson = await savedBlob.text();
  assert.deepEqual(JSON.parse(savedChatJson).chat, chat);
  await context.loadModel({size:savedChatJson.length,text:async()=>savedChatJson});
  assert.equal(JSON.stringify(restored),JSON.stringify(chat));
  const stateBefore = elements.source.value;
  const invalidChat = JSON.stringify({...JSON.parse(savedChatJson),source:'should not apply',chat:{version:1,messages:[{role:'invalid',text:'x'}]}});
  await context.loadModel({size:invalidChat.length,text:async()=>invalidChat});
  assert.equal(elements.source.value,stateBefore);
  assert.equal(JSON.stringify(restored),JSON.stringify(chat));
  blocked=true;
  await context.loadModel({size:json.length,text:async()=>json});
  assert.equal(JSON.stringify(restored),JSON.stringify(chat));
  blocked=false;
  await context.loadModel({size:json.length,text:async()=>json});
  assert.equal(restored,undefined); // Legacy model files clear the previous model's chat.
  assert.throws(()=>ModelFile.chat({version:1,messages:[{role:'user',text:'x'.repeat(200001)}]}));
  assert.throws(()=>ModelFile.images([{...image,dataUrl:'https://example.com/image.png'}]));
  assert.throws(()=>ModelFile.images(Array(4).fill(image)));
  assert.throws(()=>ModelFile.chat({version:1,messages:[{role:'assistant',text:'x',images:[image]}]}));
  // Update only on a successful, current preview; keep names as plain text.
  context.preview=actualPreview;
  context.show=()=>{};
  const treeMeshes=[
    {name:'body',groupPath:[{name:'assembly'}],positions:[]},
    {name:'bolt',groupPath:[{name:'assembly'},{name:'detail'}],positions:[]},
    {name:'loose<solid>',groupPath:[],positions:[]}
  ];
  context.request=async()=>({json:async()=>({meshes:treeMeshes})});
  await actualPreview();
  const tree='├─ assembly (group)\n│  ├─ body\n│  └─ detail (group)\n│     └─ bolt\n└─ loose<solid>';
  assert.equal(elements['object-tree'].textContent,tree);
  elements.source.value='edited but not previewed';
  assert.equal(elements['object-tree'].textContent,tree);
  context.request=async()=>{throw Error('calculation failed');};
  await actualPreview();
  assert.equal(elements['object-tree'].textContent,tree);
  let finishOld;
  context.request=()=>new Promise(resolve=>{finishOld=resolve;});
  const oldPreview=actualPreview();
  context.request=async()=>({json:async()=>({meshes:[{name:'newest',positions:[]}]})});
  await actualPreview();
  finishOld({json:async()=>({meshes:treeMeshes})});
  await oldPreview;
  assert.equal(elements['object-tree'].textContent,'└─ newest');
  context.updateObjectTree(treeMeshes);
  for(const id of ['chord','angle','finish-size','export-scale'])elements[id].value=String(elements[id].value);
  const expectedTree=[
    {type:'group',name:'assembly',children:[
      {type:'solid',name:'body'},
      {type:'group',name:'detail',children:[{type:'solid',name:'bolt'}]}
    ]},
    {type:'solid',name:'loose<solid>'}
  ];
  elements['save-model'].onclick();
  const treeJson=await savedBlob.text();
  assert.deepEqual(JSON.parse(treeJson).objectTree,expectedTree);
  assert.deepEqual(JSON.parse(JSON.stringify(ModelFile.parse(treeJson).objectTree)),expectedTree);
  assert.equal(JSON.parse(treeJson).source,'edited but not previewed');
  context.updateObjectTree([]);
  context.preview=async()=>false; // Restore the saved tree even if recalculation fails.
  await context.loadModel({size:treeJson.length,text:async()=>treeJson});
  assert.equal(elements['object-tree'].textContent,tree);
  const restoredSource=elements.source.value;
  const invalidTree=JSON.stringify({...JSON.parse(treeJson),source:'do not apply',objectTree:[{type:'group',name:'bad',children:'bad'}]});
  await context.loadModel({size:invalidTree.length,text:async()=>invalidTree});
  assert.equal(elements.source.value,restoredSource);
  assert.equal(elements['object-tree'].textContent,tree);
  for(const invalid of [null,{},[{type:'unknown',name:'a'}],[{type:'solid',name:'a',children:[]}],[{type:'solid',name:''}]]){
    assert.throws(()=>ModelFile.parse(JSON.stringify({...document,objectTree:invalid})));
  }
  const legacyJson=JSON.stringify(document);
  await context.loadModel({size:legacyJson.length,text:async()=>legacyJson});
  assert.equal(elements['object-tree'].textContent,'オブジェクトはありません');
  for(const id of ['chord','angle','finish-size','export-scale'])elements[id].value=String(elements[id].value);
  elements['save-model'].onclick();
  assert.deepEqual(JSON.parse(await savedBlob.text()).objectTree,[]);
  console.log('model-file UI: text/Python save, restore, auto-preview, and invalid-file preservation passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
