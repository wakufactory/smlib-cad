const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
  constructor() { this.value = ''; this.children = []; this.events = {}; this.hidden = false; }
  append(...items) { this.children.push(...items); }
  replaceChildren() { this.children = []; }
  addEventListener(name, handler) { this.events[name] = handler; }
  setAttribute(name,value) { this[name]=value; }
  click() {this.clicked=true;}
  get firstChild() { return {remove: () => this.children.shift()}; }
}
const ids = ['chat-history', 'chat-status', 'chat-input', 'chat-send', 'chat-stop', 'chat-reset',
  'chat-undo', 'chat-apply', 'chat-proposal', 'chat-login', 'chat-login-link', 'chat-connect',
  'source', 'mode', 'example', 'model-file', 'sample', 'export', 'export-usdz', 'chat-attach', 'chat-files', 'chat-images'];
const elements = Object.fromEntries(ids.map(id => [id, new Element()]));
elements.source.value = 'box body 0 0 0 1 1 1'; elements.mode.value = 'text';
let responseSource = 'box body 0 0 0 2 2 2', responseState = 'completed', polling;
let previewCalls = 0, lastSend, cancelled = 0, failPreview = false;
const context = vm.createContext({
  $, URL, console, Date, setTimeout, clearTimeout,
  FileReader: class {readAsDataURL(file){this.result=file.dataUrl;this.onload();}},
  document: {createElement: () => new Element(), createTextNode: text => ({textContent: text})},
  message: {textContent: 'preview error'}, previewFailure: null,
  modelDocument: () => ({source: elements.source.value, mode: elements.mode.value, parameters: {angle: 20}}),
  preview: async () => {
    previewCalls++;
    if (failPreview) context.previewFailure = {source: elements.source.value, mode: elements.mode.value, error: 'bad geometry'};
    return !failPreview;
  },
  fetch: async (path, options) => {
    let data;
    if (path === '/chat/status') data = {available: true, ready: true, message: 'connected'};
    if (path === '/chat/send') {lastSend = JSON.parse(options.body); data = {sessionId: 'session'};}
    if (path === '/chat/poll') {
      if (polling) await polling;
      data = {state: responseState, error: 'usage limit', result: {message: '変更しました', source: responseSource}};
    }
    if (path === '/chat/cancel') { cancelled++; data = {ok: true}; }
    if (path === '/chat/reset') data = {ok: true};
    return {ok: true, json: async () => data};
  }
});
function $(id) { return elements[id]; }
const tick = () => new Promise(resolve => setImmediate(resolve));
async function send(text) { elements['chat-input'].value = text; await elements['chat-send'].onclick(); }

vm.runInContext(fs.readFileSync(require.resolve('../app.js'),'utf8').split('const $ =')[0],context);
vm.runInContext(fs.readFileSync(require.resolve('../chat.js'), 'utf8'), context);
(async () => {
  await tick();
  assert.equal(context.ModelChat.snapshot(),undefined);
  assert.equal(elements['chat-send'].disabled, false);
  const original = elements.source.value;
  await send('大きくして');
  assert.equal(lastSend.source, original);
  assert.equal(lastSend.mode, 'text');
  assert.equal(elements.source.value, responseSource);
  assert.equal(previewCalls, 1);
  await elements['chat-undo'].onclick();
  assert.equal(elements.source.value, original);
  assert.equal(elements['chat-undo'].disabled, true);
  const saved = JSON.parse(JSON.stringify(context.ModelChat.snapshot()));
  assert.equal(saved.messages[0].text,'大きくして');
  assert.equal(saved.messages[1].role,'assistant');

  responseSource = null;
  await send('これは何？');
  assert.equal(elements.source.value, original);
  assert.equal(previewCalls, 2);

  let resolvePoll;
  polling = new Promise(resolve => {resolvePoll = resolve;});
  responseSource = 'box proposed 0 0 0 4 4 4';
  const pending = send('穴を開けて');
  await tick();
  assert.throws(()=>context.ModelChat.assertIdle(),/応答/);
  elements.source.value = 'manual edit';
  elements.source.events.input();
  resolvePoll(); await pending; polling = null;
  assert.equal(elements.source.value, 'manual edit');
  assert.equal(elements['chat-proposal'].hidden, false);
  await elements['chat-apply'].onclick();
  assert.equal(elements.source.value, responseSource);
  await elements['chat-undo'].onclick();
  assert.equal(elements.source.value, 'manual edit');

  failPreview = true;
  await send('直して');
  assert.equal(context.previewFailure.error, 'bad geometry');
  responseSource = null;
  await send('このエラーを直して');
  assert.equal(lastSend.previewError, 'bad geometry');
  failPreview = false;

  responseState = 'failed';
  const beforeFailure = elements.source.value;
  await send('変更して');
  assert.equal(elements.source.value, beforeFailure);
  assert.equal(elements['chat-send'].disabled, false);
  assert.equal(cancelled, 1);

  responseState = 'cancelled';
  await send('変更して');
  assert.equal(elements.source.value, beforeFailure);
  await elements['chat-reset'].onclick();
  assert.equal(elements['chat-history'].children.length, 0);
  assert.equal(elements['chat-undo'].disabled, true);
  responseState='completed'; responseSource=null;
  context.ModelChat.restore(saved);
  assert.equal(JSON.stringify(context.ModelChat.snapshot()),JSON.stringify(saved));
  assert.equal(elements['chat-history'].children[0].children[1].textContent,'大きくして');
  await send('さっきの変更について説明して');
  assert.equal(lastSend.sessionId,null);
  assert.equal(JSON.stringify(lastSend.restoredHistory),JSON.stringify(saved.messages));
  await send('続けて');
  assert.equal(lastSend.restoredHistory,undefined);
  context.ModelChat.restore(undefined);
  assert.equal(context.ModelChat.snapshot(),undefined);
  assert.equal(elements['chat-history'].children.length,0);
  const image={name:'参考.png',dataUrl:'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aDm8AAAAASUVORK5CYII='};
  elements['chat-files'].files=[{name:image.name,type:'image/png',size:68,dataUrl:image.dataUrl}];
  await elements['chat-files'].onchange({target:elements['chat-files']});
  assert.equal(elements['chat-images'].hidden,false);
  assert.equal(elements['chat-images'].children[0].children[0].src,image.dataUrl);
  await send('この画像を参考にして');
  assert.deepEqual(lastSend.images,[image]);
  assert.equal(elements['chat-images'].hidden,true);
  const imageHistory=JSON.parse(JSON.stringify(context.ModelChat.snapshot()));
  assert.deepEqual(imageHistory.messages[0].images,[image]);
  context.ModelChat.restore(imageHistory);
  assert.equal(elements['chat-history'].children[0].children[2].src,image.dataUrl);
  await send('同じ画像を参考に続けて');
  assert.deepEqual(lastSend.restoredHistory[0].images,[image]);
  assert.equal(lastSend.images,undefined);
  elements['chat-files'].files=[{name:'bad.svg',type:'image/svg+xml',size:20,dataUrl:'data:image/svg+xml;base64,AAAA'}];
  await elements['chat-files'].onchange({target:elements['chat-files']});
  assert.equal(elements['chat-images'].hidden,true);
  elements['chat-files'].files=[{name:image.name,type:'image/png',size:68,dataUrl:image.dataUrl}];
  await elements['chat-files'].onchange({target:elements['chat-files']});
  elements['chat-images'].children[0].removeButton.onclick();
  assert.equal(elements['chat-images'].hidden,true);
  console.log('chat UI tests passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
