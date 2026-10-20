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
const sentRequests = [];
let previewSteps = [], replySources = [], replyStates = [];
const context = vm.createContext({
  $, URL, console, Date, setTimeout, clearTimeout,
  FileReader: class {readAsDataURL(file){this.result=file.dataUrl;this.onload();}},
  document: {createElement: () => new Element(), createTextNode: text => ({textContent: text})},
  message: {textContent: 'preview error'}, previewFailure: null,
  modelDocument: () => ({source: elements.source.value, mode: elements.mode.value, parameters: {angle: 20}}),
  preview: async () => {
    previewCalls++;
    const source=elements.source.value,mode=elements.mode.value;
    const step=previewSteps.shift();
    const ok=typeof step==='function' ? await step() : (step===undefined ? !failPreview : step);
    context.previewFailure=ok ? null : {source,mode,error:'bad geometry'};
    return ok;
  },
  fetch: async (path, options) => {
    let data;
    if (path === '/chat/status') data = {available: true, ready: true, message: 'connected'};
    if (path === '/chat/send') {lastSend = JSON.parse(options.body);sentRequests.push(lastSend); data = {sessionId: 'session'};}
    if (path === '/chat/poll') {
      if (polling) await polling;
      data = {state:replyStates.length ? replyStates.shift() : responseState, error: 'usage limit', result: {message: '変更しました', source:replySources.length ? replySources.shift() : responseSource}};
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
  const failedStart=sentRequests.length;
  await send('直して');
  assert.equal(sentRequests.length-failedStart,3); // Initial request plus at most two automatic corrections.
  for(const request of sentRequests.slice(failedStart+1)){
    assert.equal(request.previewError,'bad geometry');
    assert.match(request.message,/bad geometry/);
    assert.equal(request.sessionId,'session');
  }
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

  // Stop after the first successful correction and use the failing source as input.
  context.ModelChat.restore(undefined);
  const originalSource=elements.source.value;
  let start=sentRequests.length, calls=previewCalls;
  replySources=['invalid first','corrected first'];previewSteps=[false,true];
  await send('変更して');
  assert.equal(sentRequests.length-start,2);
  assert.equal(previewCalls-calls,2);
  assert.equal(sentRequests[start+1].source,'invalid first');
  assert.equal(elements.source.value,'corrected first');
  await elements['chat-undo'].onclick();
  assert.equal(elements.source.value,originalSource); // Undo covers the whole correction chain.

  // A second correction may succeed; no fourth request is made on repeated failure.
  start=sentRequests.length;
  replySources=['invalid second','still invalid','corrected second'];previewSteps=[false,false,true];
  await send('別の変更');
  assert.equal(sentRequests.length-start,3);
  assert.equal(sentRequests[start+2].source,'still invalid');
  assert.equal(elements.source.value,'corrected second');
  start=sentRequests.length;
  replySources=['bad one','bad two','bad three'];previewSteps=[false,false,false];
  await send('また変更');
  assert.equal(sentRequests.length-start,3);
  assert.match(context.ModelChat.snapshot().messages.at(-1).text,/2回/);
  assert.equal(elements['chat-send'].disabled,false);
  // A new user request starts a fresh two-retry allowance.
  start=sentRequests.length;
  replySources=['bad four','bad five','good six'];previewSteps=[false,false,true];
  await send('もう一度');
  assert.equal(sentRequests.length-start,3);

  // Manual edits during preview prevent automatic correction of stale source.
  start=sentRequests.length;replySources=['bad while editing'];
  previewSteps=[()=>{elements.source.value='manual during preview';elements.source.events.input();return false;}];
  await send('変更');
  assert.equal(sentRequests.length-start,1);
  assert.equal(elements.source.value,'manual during preview');

  // Stop during preview prevents the first retry, even though the GPT turn is already completed.
  start=sentRequests.length;replySources=['bad when stopped'];
  previewSteps=[async()=>{await elements['chat-stop'].onclick();return false;}];
  await send('停止テスト');
  assert.equal(sentRequests.length-start,1);

  // Cancellation of an automatic request ends the chain immediately.
  start=sentRequests.length;replySources=['bad before cancellation',null];
  replyStates=['completed','cancelled'];previewSteps=[false];
  await send('リトライ中に停止');
  assert.equal(sentRequests.length-start,2);
  assert.equal(elements.source.value,'bad before cancellation');

  // Explicitly applying a conflict proposal uses the same two-retry limit.
  polling=new Promise(resolve=>{resolvePoll=resolve;});
  replySources=['proposal with error'];
  const conflict=send('保留する変更');await tick();
  elements.source.value='manual before proposal';elements.source.events.input();resolvePoll();await conflict;polling=null;
  start=sentRequests.length;replySources=['fixed proposal'];previewSteps=[false,true];
  await elements['chat-apply'].onclick();
  assert.equal(sentRequests.length-start,1);
  assert.equal(elements.source.value,'fixed proposal');
  console.log('chat UI tests passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
