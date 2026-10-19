const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require.resolve('../app.js'), 'utf8');
const key = 'smlib-modeler.draft.v1';
const storage = new Map();
function page() {
  const events = {};
  const values = {source:'', mode:'text', sample:'default', chord:'0.08', angle:'20', finish:'none',
    'finish-size':'1', 'export-scale':'1', 'file-name':'model', 'shading-mode':'shading', 'preview-mode':'webgl'};
  const elements = Object.fromEntries(Object.entries(values).map(([id,value])=>[id,{value,addEventListener(){}}]));
  const window = {localStorage:{getItem:k=>storage.get(k) ?? null,setItem:(k,v)=>storage.set(k,v)}, addEventListener(name,fn){events[name]=fn;}};
  const context = vm.createContext({window, console, location:{protocol:'http:'},
    document:{getElementById:id=>elements[id] ||= {style:{},checked:true,addEventListener(){},removeAttribute(){}},
      addEventListener(name,fn){events[name]=fn;}},
    ResizeObserver:class {observe(){}}, fetch:()=>new Promise(()=>{})});
  vm.runInContext(source,context);
  return {context,elements,events,window};
}
const first = page();
first.elements.source.value = 'box unfinished';
first.elements.chord.value = ''; // Preserve incomplete input too.
first.elements['file-name'].value = 'draft';
first.elements['show-grid'].checked = false;
first.events.input({target:{id:'source'}});
assert(storage.has(key));
const reloaded = page();
assert.equal(reloaded.elements.source.value, 'box unfinished');
assert.equal(reloaded.elements.chord.value, '');
assert.equal(reloaded.elements['file-name'].value, 'draft');
assert.equal(reloaded.elements['show-grid'].checked, false);
reloaded.context.clearModel();
const cleared = page();
assert.equal(cleared.elements.source.value, '');
assert.equal(vm.runInContext('restoredDraft',cleared.context),true);
cleared.elements.source.value = 'latest edit';
cleared.events.pagehide();
assert.equal(JSON.parse(storage.get(key)).fields.source,'latest edit');
storage.set(key,'broken JSON');
const corrupt = page();
assert.equal(corrupt.elements.mode.value,'text');
assert.equal(vm.runInContext('restoredDraft',corrupt.context),false);
corrupt.window.localStorage.setItem=()=>{throw Error('QuotaExceededError');};
assert.doesNotThrow(()=>corrupt.context.saveDraft());
assert.match(corrupt.elements['draft-status'].textContent,/自動保存できません/);
console.log('local draft: reload, unfinished input, clear, pagehide, corrupt data, and storage failure passed');
