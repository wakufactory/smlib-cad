const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const fields = {source:'box body 0 0 0 1 1 1',mode:'text',sample:'default',chord:'0.08',angle:'20',
  finish:'none','finish-size':'1','export-scale':'1','file-name':'model',
  'shading-mode':'shading','preview-mode':'webgl','grid-spacing':'1','grid-plane':'xy',
  'grid-offset':'0','projection-mode':'orthographic'};
const draft=JSON.stringify({version:1,fields,checks:{'show-axes':true,'show-grid':true}});
const elements={canvas:{clientWidth:600,clientHeight:400,addEventListener(){}},
  source:{value:'',scrollTop:0,addEventListener(){}},message:{style:{}},
  'usd-model':{removeAttribute(){}}};
const statusResolvers=[];
const context=vm.createContext({
  document:{getElementById:id=>elements[id] ||= {style:{},value:'',checked:true,addEventListener(){}}},
  window:{localStorage:{getItem:()=>draft,setItem(){}},addEventListener(){}},
  location:{protocol:'http:'},ResizeObserver:class{observe(){}},console,
  fetch:(path)=>{
    if(path==='/status')return new Promise(resolve=>statusResolvers.push(resolve));
    if(path==='/examples')return new Promise(()=>{});
    if(path==='/preview')return Promise.resolve({ok:false,json:async()=>({error:'形状計算が時間内に完了しませんでした'})});
    throw Error(`Unexpected request: ${path}`);
  }
});
vm.runInContext(fs.readFileSync(require.resolve('../app.js'),'utf8'),context);

class Camera{
  constructor(){this.up={set(){}};this.position={set(){}};}
  add(){} updateProjectionMatrix(){} lookAt(){}
}
class OrthographicCamera extends Camera{constructor(){super();this.isOrthographicCamera=true;}}
class WebGLRenderer{setPixelRatio(){} setClearColor(){} setSize(){} render(){}}
class Scene{add(){}}
class DirectionalLight{constructor(){this.position={set(){}};this.target={};}}
const THREE={WebGLRenderer,Scene,PerspectiveCamera:Camera,OrthographicCamera,
  AmbientLight:class{},DirectionalLight,SRGBColorSpace:'srgb',ACESFilmicToneMapping:'aces'};

(async()=>{
  context.initializeApp(async()=>THREE);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(elements.preview.disabled,false,'the editor is usable while startup requests are pending');
  assert.equal(elements['preview-mode'].disabled,false);
  assert.equal(elements.source.value,fields.source);
  assert.equal(elements.canvas.hidden,false);

  statusResolvers.at(-1)({ok:true,json:async()=>({ready:true})});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(elements.preview.disabled,false,'a timed-out restored preview releases the button');
  assert.match(elements.message.textContent,/形状計算が時間内に完了しませんでした/);
  assert.equal(elements.source.value,fields.source);
  context.setTimeout=callback=>setImmediate(callback);
  context.clearTimeout=()=>{};
  context.initializeApp(async()=>THREE);
  await new Promise(resolve=>setImmediate(resolve));
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(elements.preview.disabled,false,'startup timeout also leaves retry available');
  assert.match(elements.message.textContent,/\/status の読み込みが時間切れ/);
  assert.equal(elements.source.value,fields.source);
  console.log('reload timeout: editor available during startup and after preview failure passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
