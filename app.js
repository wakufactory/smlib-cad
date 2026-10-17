/* Portable, versioned document for both editor modes. */
const ModelFile = (() => {
  function number(value, name, min, max = Infinity) {
    if (typeof value !== 'number' || !Number.isFinite(value) || value < min || value > max) {
      throw Error(`${name} は ${min}～${max === Infinity ? '上限なし' : max} の数値にしてください`);
    }
    return value;
  }

  function validate(document) {
    if (!document || typeof document !== 'object' || Array.isArray(document)) throw Error('モデルのJSONオブジェクトが必要です');
    if (document.format !== 'smlib-model' || document.version !== 1 || !['text', 'python'].includes(document.mode)) {
      throw Error('対応していないモデル形式またはバージョンです');
    }
    if (typeof document.source !== 'string') throw Error('source はテキストにしてください');
    const p = document.parameters;
    if (!p || typeof p !== 'object' || Array.isArray(p)) throw Error('parameters が必要です');
    const finish = p.finish;
    if (!['none', 'chamfer', 'fillet'].includes(finish)) throw Error('全体加工の種類が不正です');
    return {
      format: 'smlib-model', version: 1, mode: document.mode, source: document.source,
      parameters: {
        chord: number(p.chord, '曲面精度', 0.001, 2),
        angle: number(p.angle, '角度条件', 1, 90),
        finish,
        finishSize: number(p.finishSize, '幅/半径', 0.001)
      }
    };
  }

  return { validate, parse: json => validate(JSON.parse(json)) };
})();

const $ = id => document.getElementById(id);
const canvas = $('canvas');
const message = $('message');
let examples = {}, currentMeshes = [], rendered = [], center = [0, 0, 0], radius = 20;
let yaw = 0.72, pitch = 0.44, zoom = 2.8, dragging = false, last = [0, 0];
let THREE, renderer, scene, camera;
let viewportWidth = 0, viewportHeight = 0;
const cameraLightDirection = [-0.6, 0.8, 0.8]; // left, up, toward viewer

function note(text, error = false) { message.textContent = text; message.style.color = error ? '#ff9b93' : '#9dd9c5'; }
function setupRenderer(){
  renderer = new THREE.WebGLRenderer({canvas, antialias: true});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(0x0e1a26);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(45, 1, 0.01, 1000);
  camera.up.set(0, 0, 1);
  scene.add(camera);
  scene.add(new THREE.AmbientLight(0xffffff, 0.7));
  const key = new THREE.DirectionalLight(0xffffff, 3);
  key.position.set(...cameraLightDirection);
  camera.add(key);
  camera.add(key.target);
}
function sub(a,b){return a.map((v,i)=>v-b[i]);}
function cameraEye(){const d=radius*zoom;return [center[0]+d*Math.cos(pitch)*Math.cos(yaw),center[1]+d*Math.cos(pitch)*Math.sin(yaw),center[2]+d*Math.sin(pitch)];}
function draw(){
  if(!renderer)return;
  const w=Math.max(1,canvas.clientWidth),h=Math.max(1,canvas.clientHeight);
  if(w!==viewportWidth || h!==viewportHeight){
    renderer.setSize(w,h,false);viewportWidth=w;viewportHeight=h;
  }
  camera.aspect=w/h;
  camera.near=Math.max(0.01,radius*zoom/1000);
  camera.far=radius*zoom+radius*10;
  camera.updateProjectionMatrix();
  camera.position.set(...cameraEye());
  camera.lookAt(...center);
  const wireframe=$('shading-mode').value==='wireframe';
  for(const mesh of rendered){mesh.solid.visible=!wireframe;mesh.wire.visible=wireframe;}
  renderer.render(scene,camera);
}
function triangleEdges(positions){
  const edges=new Float32Array(positions.length*2);
  for(let i=0;i<positions.length;i+=9){
    edges.set(positions.slice(i,i+6),i*2);
    edges.set(positions.slice(i+3,i+9),i*2+6);
    edges.set(positions.slice(i+6,i+9),i*2+12);
    edges.set(positions.slice(i,i+3),i*2+15);
  }
  return edges;
}
function show(meshes){
  for(const mesh of rendered){
    scene.remove(mesh.solid,mesh.wire);
    mesh.solid.geometry.dispose();mesh.solid.material.dispose();
    mesh.wire.geometry.dispose();mesh.wire.material.dispose();
  }
  rendered=[];
  const lo=[Infinity,Infinity,Infinity],hi=[-Infinity,-Infinity,-Infinity];
  for(const mesh of meshes){
    const geometry=new THREE.BufferGeometry();
    geometry.setAttribute('position',new THREE.BufferAttribute(new Float32Array(mesh.positions),3));
    geometry.setAttribute('normal',new THREE.BufferAttribute(new Float32Array(mesh.normals),3));
    const color=new THREE.Color().setRGB(...mesh.material.baseColor,THREE.LinearSRGBColorSpace);
    const solid=new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({
      color,metalness:mesh.material.metallic,roughness:mesh.material.roughness
    }));
    const edgeGeometry=new THREE.BufferGeometry();
    edgeGeometry.setAttribute('position',new THREE.BufferAttribute(triangleEdges(mesh.positions),3));
    const lineColor=new THREE.Color().setRGB(...mesh.material.baseColor.map(c=>0.45+0.55*c),THREE.LinearSRGBColorSpace);
    const wire=new THREE.LineSegments(edgeGeometry,new THREE.LineBasicMaterial({color:lineColor}));
    scene.add(solid,wire);
    rendered.push({solid,wire});
    for(let i=0;i<mesh.positions.length;i+=3)for(let j=0;j<3;j++){lo[j]=Math.min(lo[j],mesh.positions[i+j]);hi[j]=Math.max(hi[j],mesh.positions[i+j]);}
  }
  if(meshes.length){center=lo.map((x,i)=>(x+hi[i])/2);radius=Math.max(1,Math.hypot(...sub(hi,lo))/2);}
  zoom=meshes.length>1?2.25:2.8;draw();
}
async function request(path){
  const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:$('mode').value,source:$('source').value,chord:Number($('chord').value),angle:Number($('angle').value),finish:$('finish').value,finishSize:Number($('finish-size').value)})});
  if(!response.ok){const data=await response.json();throw Error(data.error||'Processing failed');}
  return response;
}
async function preview(){
  $('preview').disabled=true;$('export').disabled=true;$('export-usdz').disabled=true;note('計算中…');
  try{const data=await(await request('/preview')).json();currentMeshes=data.meshes;show(data.meshes);
    const triangles=data.meshes.reduce((n,m)=>n+m.positions.length/9,0);
    note(`${data.meshes.length} solid / ${triangles.toLocaleString()} triangles${data.log?'\n'+data.log:''}`);
    $('export').disabled=false;$('export-usdz').disabled=false;
  }catch(e){note(e.message,true);}finally{$('preview').disabled=false;}
}
function saveFileName(format){
  const base=$('file-name').value.trim().replace(/\.(glb|usdz|json)$/i,'');
  if(!base || base==='.' || base==='..' || /[\\/:*?"<>|\x00-\x1f]/.test(base) || base.endsWith('.')){
    throw Error('保存ファイル名を入力してください（パスや使用できない文字は含められません）');
  }
  return `${base}.${format}`;
}
async function exportFile(format){
  const id=format==='usdz'?'export-usdz':'export';
  $(id).disabled=true;note(`${format.toUpperCase()} を生成中…`);
  try{const name=saveFileName(format),blob=await(await request(format==='usdz'?'/export/usdz':'/export')).blob(),url=URL.createObjectURL(blob);
    const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);note(`${name} (${(blob.size/1024).toFixed(1)} KiB) を保存しました`);
  }catch(e){note(e.message,true);}finally{$(id).disabled=false;}
}
function modelDocument(){
  for(const id of ['chord','angle','finish-size']){
    if(!$(id).checkValidity() || $(id).value.trim()==='') throw Error(`${$(id).labels[0]?.textContent || id} の値が不正です`);
  }
  return ModelFile.validate({
    format:'smlib-model',version:1,mode:$('mode').value,source:$('source').value,
    parameters:{chord:Number($('chord').value),angle:Number($('angle').value),
      finish:$('finish').value,finishSize:Number($('finish-size').value)}
  });
}
function saveModel(){
  try{
    const name=saveFileName('json');
    const data=modelDocument();
    const blob=new Blob([JSON.stringify(data,null,2)+'\n'],{type:'application/json'});
    const url=URL.createObjectURL(blob),a=document.createElement('a');
    a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    note(`${name} を保存しました`);
  }catch(e){note(e.message,true);}
}
async function loadModel(file){
  if(!file)return;
  try{
    if(file.size>1_000_000)throw Error('JSONファイルは1 MB以下にしてください');
    const data=ModelFile.parse(await file.text()),p=data.parameters;
    $('mode').value=data.mode;$('sample').value='default';$('source').value=data.source;
    $('chord').value=p.chord;$('angle').value=p.angle;
    $('finish').value=p.finish;$('finish-size').value=p.finishSize;
    if(file.name && /\.json$/i.test(file.name))$('file-name').value=file.name.replace(/\.json$/i,'');
    $('finish-size').disabled=p.finish==='none';$('save-model').disabled=false;
    $('export').disabled=true;$('export-usdz').disabled=true;
  }catch(e){note(`JSONを読み込めません: ${e.message}`,true);return;}
  finally{$('model-file').value='';}
  await preview();
}
$('preview').onclick=preview;$('export').onclick=()=>exportFile('glb');$('export-usdz').onclick=()=>exportFile('usdz');
$('save-model').onclick=saveModel;
$('load-model').onclick=()=>$('model-file').click();
$('model-file').onchange=e=>loadModel(e.target.files[0]);
$('shading-mode').onchange=draw;
$('finish').onchange=()=>$('finish-size').disabled=$('finish').value==='none';
$('mode').onchange=()=>{$('sample').value='default';$('source').value=examples[$('mode').value]||'';$('export').disabled=true;$('export-usdz').disabled=true;};
$('example').onclick=()=>{
  if(['gallery','circular','sweeps','offsets'].includes($('sample').value)){
    $('mode').value='text';$('source').value=examples[$('sample').value]||'';
  }
  else $('source').value=examples[$('mode').value]||'';
  $('export').disabled=true;$('export-usdz').disabled=true;
};
$('source').addEventListener('keydown',e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();preview();}});
canvas.addEventListener('pointerdown',e=>{dragging=true;last=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId);});
canvas.addEventListener('pointerup',()=>dragging=false);
canvas.addEventListener('pointermove',e=>{if(!dragging)return;yaw+=(e.clientX-last[0])*0.007;pitch=Math.max(-1.48,Math.min(1.48,pitch+(e.clientY-last[1])*0.007));last=[e.clientX,e.clientY];draw();});
canvas.addEventListener('wheel',e=>{e.preventDefault();zoom=Math.max(1.2,Math.min(30,zoom*Math.exp(e.deltaY*0.001)));draw();},{passive:false});
canvas.ondblclick=()=>{yaw=0.72;pitch=0.44;zoom=2.8;draw();};
new ResizeObserver(draw).observe(canvas);
(async()=>{
  examples=await(await fetch('/examples')).json();$('source').value=examples.text;
  const state=await(await fetch('/status')).json();
  $('status').textContent=state.ready?'SMLib 接続済み':`_smlib_core 未導入: ${state.error}`;
  if(!state.ready)note('SMLib の Python バインディングをビルドしてください。セットアップは README を参照。',true);
  THREE=await import('https://cdn.jsdelivr.net/npm/three@0.186.1/build/three.module.js');
  setupRenderer();
  $('preview').disabled=false;
  draw();
})().catch(e=>note(e.message,true));
