/* Portable, versioned document for both editor modes. */
const ModelFile = (() => {
  function number(value, name, min, max = Infinity) {
    if (typeof value !== 'number' || !Number.isFinite(value) || value < min || value > max) {
      throw Error(`${name} は ${min}～${max === Infinity ? '上限なし' : max} の数値にしてください`);
    }
    return value;
  }

  function exportScale(value) {
    if(typeof value !== 'number' || !Number.isFinite(value) || value <= 0)throw Error('保存時の座標倍率は正の数値にしてください');
    return value;
  }

  function images(value) {
    if(!Array.isArray(value) || value.length>3)throw Error('画像は1メッセージにつき3枚までです');
    return value.map(item=>{
      if(!item || typeof item.name!=='string' || item.name.length>200 || typeof item.dataUrl!=='string' || item.dataUrl.length>2796250)throw Error('添付画像の形式が不正です');
      const match=/^data:image\/(png|jpeg|webp);base64,([A-Za-z0-9+/]*={0,2})$/.exec(item.dataUrl);
      const bytes=match ? match[2].length*3/4-(match[2].endsWith('==')?2:match[2].endsWith('=')?1:0) : 0;
      if(!match || match[2].length%4 || bytes<1 || bytes>2*1024*1024)throw Error('画像はPNG・JPEG・WebP、1枚2 MiB以下にしてください');
      return {name:item.name,dataUrl:item.dataUrl};
    });
  }

  function chat(value) {
    if (!value || value.version !== 1 || !Array.isArray(value.messages) || value.messages.length > 100) throw Error('チャット履歴の形式が不正です');
    let length = 0, imageLength = 0;
    const messages = value.messages.map(item => {
      if (!item || !['user', 'assistant', 'system'].includes(item.role) || typeof item.text !== 'string' ||
          (item.error !== undefined && typeof item.error !== 'boolean')) throw Error('チャット履歴のメッセージが不正です');
      length += item.text.length;
      if (length > 200000) throw Error('チャット履歴は合計20万文字以下にしてください');
      const attachments=item.images===undefined ? [] : images(item.images);
      if(attachments.length && item.role!=='user')throw Error('画像はユーザーの発言にのみ添付できます');
      imageLength+=attachments.reduce((n,image)=>n+image.dataUrl.length,0);
      if(imageLength>12000000)throw Error('保存する会話の画像が多すぎます（画像データ合計12 MBまで）');
      return {role:item.role, text:item.text, ...(item.error ? {error:true} : {}), ...(attachments.length?{images:attachments}:{})};
    });
    return {version:1, messages};
  }

  function objectTree(nodes) {
    if(!Array.isArray(nodes))throw Error('objectTree は配列にしてください');
    return nodes.map(node=>{
      if(!node || typeof node.name!=='string' || !node.name || !['group','solid'].includes(node.type))throw Error('objectTree のノードが不正です');
      if(node.type==='group')return {type:'group',name:node.name,children:objectTree(node.children)};
      if(node.children!==undefined)throw Error('solid に children は指定できません');
      return {type:'solid',name:node.name};
    });
  }

  function validate(document, validateAnimation = true) {
    if (!document || typeof document !== 'object' || Array.isArray(document)) throw Error('モデルのJSONオブジェクトが必要です');
    if (document.format !== 'smlib-model' || document.version !== 1 || !['text', 'python'].includes(document.mode)) {
      throw Error('対応していないモデル形式またはバージョンです');
    }
    if (typeof document.source !== 'string') throw Error('source はテキストにしてください');
    const animationSource = document.animationSource === undefined ? '' : document.animationSource;
    if(typeof animationSource!=='string')throw Error('animationSource はテキストにしてください');
    if(validateAnimation)globalThis.ModelAnimation?.validate(animationSource);
    if(document.animationClip!==undefined && typeof document.animationClip!=='string')throw Error('animationClip はテキストにしてください');
    const p = document.parameters;
    if (!p || typeof p !== 'object' || Array.isArray(p)) throw Error('parameters が必要です');
    return {
      format: 'smlib-model', version: 1, mode: document.mode, source: document.source,
      ...(document.animationSource === undefined ? {} : {animationSource}),
      ...(document.animationClip === undefined ? {} : {animationClip:document.animationClip}),
      ...(document.chat === undefined ? {} : {chat:chat(document.chat)}),
      ...(document.objectTree === undefined ? {} : {objectTree:objectTree(document.objectTree)}),
      parameters: {
        chord: number(p.chord, '曲面精度', 0.001, 2),
        angle: number(p.angle, '角度条件', 1, 90),
        exportScale: exportScale(p.exportScale === undefined ? 1 : p.exportScale)
      }
    };
  }

  function parse(json) {
    let document;
    try { document = JSON.parse(json); }
    catch(error) {
      // Safari reports both truncated strings and literal newlines as
      // "Unterminated string", without a location. Diagnose the original text.
      let start = -1, escaped = false, detail = '';
      const location = index => {
        const lines = json.slice(0, index).split('\n');
        return `${lines.length}行${lines[lines.length - 1].length + 1}列`;
      };
      for(let i = 0; i < json.length; i++) {
        const char = json[i];
        if(start < 0) { if(char === '"')start = i; continue; }
        if(char.charCodeAt(0) < 32) {
          detail = `${location(i)}: JSON文字列内に未エスケープの制御文字があります（文字列開始: ${location(start)}）`;
          break;
        }
        if(escaped)escaped = false;
        else if(char === '\\')escaped = true;
        else if(char === '"')start = -1;
      }
      if(!detail && start >= 0)detail = `${location(start)}からのJSON文字列が閉じる前にファイルが終わっています`;
      throw Error(`${error.message}${detail ? `\n${detail}` : ''}`);
    }
    return validate(document);
  }

  return { validate, chat, images, exportScale, objectTree, parse };
})();

const $ = id => document.getElementById(id);
function selectEditorTab(name, focus=false){
  for(const tab of ['model','animation']){
    const button=$('tab-'+tab),panel=$(tab+'-panel'),selected=tab===name;
    if(panel)panel.hidden=!selected;
    button?.setAttribute?.('aria-selected',String(selected));
    if(button)button.tabIndex=selected?0:-1;
    if(selected && focus)button?.focus?.();
  }
  refreshSourceLines();
}
for(const name of ['model','animation']){
  $('tab-'+name)?.addEventListener?.('click',()=>selectEditorTab(name));
  $('tab-'+name)?.addEventListener?.('keydown',event=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    event.preventDefault();
    selectEditorTab(event.key==='Home'?'model':event.key==='End'?'animation':name==='model'?'animation':'model',true);
  });
}
const canvas = $('canvas');
const message = $('message');
const editorLineCounts = new Map();
function syncSourceLineScroll(id='source'){
  const numbers=$(id+'-line-numbers-inner');
  if(numbers?.style)numbers.style.transform=`translateY(${-($(id).scrollTop||0)}px)`;
}
function refreshSourceLines(){
  for(const id of ['source','animation-source']){
    const source=$(id),gutter=$(id+'-line-numbers'),numbers=$(id+'-line-numbers-inner');
    if(!source || !gutter?.style || !numbers?.style)continue;
    let count=1;
    for(const char of source.value||'')if(char==='\n')count++;
    if(count!==editorLineCounts.get(id)){
      numbers.textContent=Array.from({length:count},(_,index)=>index+1).join('\n');
      gutter.style.width=`calc(${Math.max(2,String(count).length)}ch + 20px)`;
      editorLineCounts.set(id,count);
    }
    syncSourceLineScroll(id);
  }
}
const usdModel = $('usd-model');
const modelStatus = $('model-status');
let examples = {}, currentMeshes = [], rendered = [], center = [0, 0, 0], radius = 20;
let guides = [], guideBounds = null;
let yaw = -0.72, pitch = 0.44, zoom = 2.8;
let resetPreviewView = true;
let THREE, renderer, scene, camera, perspectiveCamera, orthographicCamera, cameraLight;
let viewportWidth = 0, viewportHeight = 0;
let previewRequestId = 0;
let previewFailure = null;
let currentObjectTree = [];
const hiddenPreviewNodes = new Set();
let selectedPreviewNode = null;
let selectionSurfaceMaterial, selectionWireMaterial, selectionAxes;
function previewNodeKeys(mesh){
  const path=(mesh.groupPath||[]).map(group=>['group',group.name]);
  return [...path.map((_,index)=>JSON.stringify(path.slice(0,index+1))),
    JSON.stringify([...path,['solid',mesh.name]])];
}
let currentMeshKey=null;
function modelingKey(){return JSON.stringify(['source','mode','chord','angle'].map(id=>$(id).value));}
let animationPlayer = null;
let resolvedAnimation = null;
let animationApplyId = 0;
function animationKey(){return JSON.stringify([$('mode').value,$('source').value,animationText()]);}
function animationText(){return $('animation-source')?.value || '';}
function selectedAnimationClip(){
  if(!animationText().trim())return '';
  const clips=ModelAnimation.parse(animationText(),true)?.clips||[];
  return clips.find(clip=>clip.name===$('animation-clip').value)?.name||clips[0]?.name||'';
}
function updateClipOptions(clips,selected){
  if(!clips.length){restoreClipSelection();return;}
  $('animation-clip').replaceChildren(...clips.map(clip=>{
    const option=document.createElement('option');option.value=clip.name;option.textContent=clip.name;return option;
  }));
  $('animation-clip').value=selected||'';
}
function restoreClipSelection(name=''){
  const option=document.createElement('option');option.value=name||'';option.textContent=name||'なし';
  $('animation-clip').replaceChildren(option);$('animation-clip').value=name||'';
}
function animationStatus(time,duration,running){
  $('animation-play').textContent=running?'一時停止':'再生';
  $('animation-seek').max=duration || 1;
  $('animation-seek').value=time;
  $('animation-time').textContent=`${time.toFixed(2)} / ${duration.toFixed(2)} s`;
}
async function applyAnimation(){
  if(!animationPlayer)throw Error('WebGL プレビューを準備してください');
  if($('preview-mode').value==='model')throw Error('再生コントロールは WebGL プレビューで使用してください');
  if(currentMeshKey!==modelingKey())throw Error('モデルが変更されています。先にプレビューを更新してください');
  const key=animationKey(),source=animationText(),id=++animationApplyId;
  let numericSource=source;
  if(resolvedAnimation?.key===key)numericSource=resolvedAnimation.source;
  else{
    try{ModelAnimation.parse(source);}catch(error){
      if(!error.modelReference)throw error;
      const data=await(await request('/animation/resolve')).json();
      if(id!==animationApplyId || key!==animationKey() || currentMeshKey!==modelingKey())return false;
      if(typeof data.resolvedAnimationSource!=='string')throw Error('アニメーションの評価結果が不正です');
      numericSource=data.resolvedAnimationSource;
      resolvedAnimation={key,source:numericSource};
    }
  }
  animationPlayer.configure(numericSource,currentMeshes,rendered,$('animation-clip').value);
  updateClipOptions(animationPlayer.collection?.clips||[],animationPlayer.animation?.name);
  appliedAnimationSource=source;
  return true;
}
async function updateAnimationPreview(){
  if(!animationPlayer || !currentMeshes.length || currentMeshKey!==modelingKey() || $('preview-mode').value==='model')return preview();
  if(!await applyAnimation())return false;
  saveDraft();
  previewFailure=null;
  return true;
}
$('animation-apply').onclick=async()=>{
  try{if(!await applyAnimation())return;saveDraft();note('アニメーション設定を適用しました');}catch(error){note(error.message,true);}
};
$('animation-play').onclick=async()=>{
  try{
    if($('preview-mode').value==='model')throw Error('再生コントロールは WebGL プレビューで使用してください');
    if(animationPlayer?.running){animationPlayer.pause();return;}
    if(animationText()!==appliedAnimationSource || currentMeshKey!==modelingKey())if(!await applyAnimation())return;
    if(!animationPlayer?.animation)throw Error('アニメーションを設定して「設定を適用」を押してください');
    animationPlayer.play();
  }catch(error){note(error.message,true);}
};
let appliedAnimationSource='';
$('animation-clip').onchange=async()=>{
  try{if($('preview-mode').value==='model'){saveDraft();await preview();}else{if(!await applyAnimation())return;saveDraft();}}catch(error){note(error.message,true);}
};
$('animation-reset').onclick=()=>animationPlayer?.reset();
function seekAnimation(){
  // pause() refreshes the controls with the old playback time. Capture the
  // slider's requested time first so that refresh cannot overwrite the seek.
  const time=Number($('animation-seek').value);
  animationPlayer?.pause();
  animationPlayer?.seek(time);
}
$('animation-seek').oninput=seekAnimation;
$('animation-seek').onchange=seekAnimation;
const cameraLightDirection = [-0.6, 0.8, 0.8]; // left, up, toward viewer

function note(text, error = false) { message.textContent = text; message.style.color = error ? '#ff9b93' : '#9dd9c5'; }
const draftKey='smlib-modeler.draft.v1';
let draftEdited=false;
const draftFields=['source','mode','sample','chord','angle','export-scale','file-name','shading-mode','preview-mode','grid-spacing','grid-plane','grid-offset','projection-mode'];
const draftChecks=['show-axes','show-grid'];
function saveDraft(){
  draftEdited=true;
  try{
    if(!window.localStorage)return;
    const fields=Object.fromEntries(draftFields.map(id=>[id,String($(id).value)]));
    const checks=Object.fromEntries(draftChecks.map(id=>[id,$(id).checked]));
    window.localStorage.setItem(draftKey,JSON.stringify({version:1,fields,checks,animationSource:animationText(),animationClip:$('animation-clip').value}));
//    note('ブラウザに自動保存済み');
  }catch(error){
    note('自動保存できません。JSONで保存してください',true);
  }
}
function restoreDraft(){
  try{
    const raw=window.localStorage?.getItem(draftKey);
    if(!raw)return false;
    const draft=JSON.parse(raw);
    if(draft.version!==1 || !draft.fields || !draft.checks ||
       !draftFields.slice(0,-4).every(id=>typeof draft.fields[id]==='string') ||
       !draftFields.slice(-4).every(id=>draft.fields[id]===undefined || typeof draft.fields[id]==='string') ||
       !draftChecks.every(id=>typeof draft.checks[id]==='boolean'))throw Error('Invalid draft');
    const options={mode:['text','python'],sample:['clear','default','gallery','circular','sweeps','offsets','functions','groups','animation'],
      'shading-mode':['shading','wireframe','normal'],'preview-mode':['webgl','model'],
      'grid-plane':['xy','yz','zx'],'projection-mode':['perspective','orthographic']};
    if(Object.entries(options).some(([id,values])=>draft.fields[id]!==undefined && !values.includes(draft.fields[id])))throw Error('Invalid draft option');
    if(draft.animationSource!==undefined && typeof draft.animationSource!=='string')throw Error('Invalid animation draft');
    $('animation-source').value=draft.animationSource || '';
    restoreClipSelection(draft.animationClip);
    for(const id of draftFields)if(draft.fields[id]!==undefined)$(id).value=draft.fields[id];
    refreshSourceLines();
    for(const id of draftChecks)$(id).checked=draft.checks[id];
    if($('preview-mode').value==='model' && modelModeError())$('preview-mode').value='webgl';
    note('前回の編集内容を復元しました');
    return true;
  }catch(error){
    note('前回の編集内容を復元できませんでした',true);
    return false;
  }
}
// Store raw input values, including unfinished numbers and invalid model code.
for(const event of ['input','change'])document.addEventListener?.(event,e=>{
  if(e.target.id==='animation-source' || draftFields.includes(e.target.id) || draftChecks.includes(e.target.id))saveDraft();
});
window.addEventListener?.('pagehide',saveDraft);
function modelModeError(){
  if(location.protocol !== 'https:' || !window.isSecureContext)return 'USDZ <model> プレビューには信頼済みの HTTPS 接続が必要です';
  if(!window.HTMLModelElement)return 'このブラウザは <model> 要素に対応していません';
  return '';
}
function showPreviewMode(){
  const native=$('preview-mode').value==='model';
  if(native)animationPlayer?.pause();
  for(const id of ['animation-apply','animation-play','animation-reset','animation-seek'])$(id).disabled=native;
  canvas.hidden=native;
  usdModel.hidden=!native;
  modelStatus.hidden=!native;
  $('shading-mode').hidden=native;
  $('projection-mode').hidden=native;
  $('view-controls').hidden=native;
  if(!native)draw();
}
function setupRenderer(){
  renderer = new THREE.WebGLRenderer({canvas, antialias: true});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(0x0e1a26);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  scene = new THREE.Scene();
  if(globalThis.ModelAnimation)animationPlayer=new ModelAnimation.Player(THREE,draw,animationStatus);
  perspectiveCamera = new THREE.PerspectiveCamera(45, 1, 0.01, 1000);
  orthographicCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.01, 1000);
  scene.add(perspectiveCamera, orthographicCamera);
  scene.add(new THREE.AmbientLight(0xffffff, 0.7));
  cameraLight = new THREE.DirectionalLight(0xffffff, 3);
  cameraLight.position.set(...cameraLightDirection);
  changeProjection();
}
function changeProjection(){
  if(!renderer)return;
  camera=$('projection-mode').value==='orthographic'?orthographicCamera:perspectiveCamera;
  camera.add(cameraLight);
  camera.add(cameraLight.target);
  draw();
}
function sub(a,b){return a.map((v,i)=>v-b[i]);}
function cameraEye(){const d=radius*zoom;return [center[0]+d*Math.cos(pitch)*Math.cos(yaw),center[1]+d*Math.cos(pitch)*Math.sin(yaw),center[2]+d*Math.sin(pitch)];}
function draw(){
  if(!renderer)return;
  const w=Math.max(1,canvas.clientWidth),h=Math.max(1,canvas.clientHeight);
  if(w!==viewportWidth || h!==viewportHeight){
    renderer.setSize(w,h,false);viewportWidth=w;viewportHeight=h;
  }
  if(camera.isOrthographicCamera){
    const halfHeight=radius*zoom*Math.tan(Math.PI/8);
    camera.left=-halfHeight*w/h;camera.right=halfHeight*w/h;
    camera.top=halfHeight;camera.bottom=-halfHeight;
  }else camera.aspect=w/h;
  camera.near=Math.max(0.01,radius*zoom/1000);
  camera.far=radius*zoom+radius*10;
  camera.updateProjectionMatrix();
  camera.position.set(...cameraEye());
  // Keep screen-up perpendicular to the view direction, even at the poles.
  const sinPitch = Math.sin(pitch);
  camera.up.set(-sinPitch * Math.cos(yaw), -sinPitch * Math.sin(yaw), Math.cos(pitch));
  camera.lookAt(...center);
  const mode=$('shading-mode').value;
  const selection=$('preview-mode').value==='webgl'?selectedPreviewNode:null;
  let selectedGroup=null;
  for(const mesh of rendered){
    const visible=!mesh.nodeKeys.some(key=>hiddenPreviewNodes.has(key));
    mesh.solid.visible=visible && mode==='shading';
    mesh.normal.visible=visible && mode==='normal';
    mesh.wire.visible=visible && mode==='wireframe';
    const index=selection===null?-1:mesh.nodeKeys.indexOf(selection);
    const selected=visible && index>=0;
    mesh.wire.material=selected && mesh.wire.visible
      ? (selectionWireMaterial??=new THREE.LineBasicMaterial({color:0x64dcff,toneMapped:false}))
      : mesh.wireMaterial;
    const surface=selected && mode!=='wireframe';
    if(surface){
      selectionSurfaceMaterial??=new THREE.MeshBasicMaterial({
        color:0x64dcff,opacity:0.4,transparent:true,depthWrite:false,toneMapped:false,
        side:THREE.DoubleSide,forceSinglePass:true,polygonOffset:true,polygonOffsetFactor:-1,polygonOffsetUnits:-1
      });
      mesh.highlight??=new THREE.Mesh(mesh.solid.geometry,selectionSurfaceMaterial);
      const parent=mode==='normal'?mesh.normal:mesh.solid;
      if(mesh.highlight.parent!==parent)parent.add(mesh.highlight);
    }
    if(mesh.highlight)mesh.highlight.visible=surface;
    if(!selectedGroup && index>=0){
      const depth=Math.min(index+1,mesh.groupPath.length);
      const selectionPath=mesh.nodeKeys.slice(0,index+1);
      if(depth>0 && !selectionPath.some(key=>hiddenPreviewNodes.has(key))){
        selectedGroup=mesh.groupPath.slice(0,depth);
      }
    }
  }
  const showLocalAxes=drawSelectionAxes(selectedGroup,w,h);
  for(const guide of guides){
    if(guide.toggle==='show-grid'){
      drawGrid(guide,showLocalAxes?selection:null,selectedGroup);
      continue;
    }
    guide.object.visible=$(guide.toggle).checked && !showLocalAxes;
  }
  renderer.render(scene,camera);
}
function drawGrid(guide,selection,groups){
  const {object,settings}=guide;
  object.visible=$('show-grid').checked;
  if(!object.visible)return;
  if(selection===null){
    object.geometry=guide.worldGeometry;
    if(guide.localGeometry){
      object.matrix.identity();
      object.matrixWorldNeedsUpdate=true;
    }
    return;
  }
  const world=selectionAxes.world;
  if(selection!==guide.gridSelection){
    const [lo,hi]=guideBounds;
    const bounds=new THREE.Box3(new THREE.Vector3(...lo),new THREE.Vector3(...hi));
    // Preview bounds are baked before animation, so convert them with the rest pose.
    const rest=animationPlayer.groupMatrix(groups,new THREE.Matrix4(),undefined,{animated:false});
    bounds.applyMatrix4(rest.invert());
    guide.localGeometry?.dispose();
    guide.localGeometry=gridGeometry(bounds.min.toArray(),bounds.max.toArray(),settings);
    guide.gridSelection=selection;
  }
  object.geometry=guide.localGeometry;
  object.matrixAutoUpdate=false;
  object.matrix.copy(world);
  object.matrixWorldNeedsUpdate=true;
}
function drawSelectionAxes(groups,width,height){
  const overlay=$('local-axes');
  overlay.hidden=true;
  if(!groups || !animationPlayer)return false;
  camera.updateMatrixWorld();
  if(!selectionAxes){
    selectionAxes={
      world:new THREE.Matrix4(),local:new THREE.Matrix4(),origin:new THREE.Vector3(),projected:new THREE.Vector3(),
      directions:[new THREE.Vector3(),new THREE.Vector3(),new THREE.Vector3()]
    };
  }
  const {world,local,origin,projected,directions}=selectionAxes;
  animationPlayer.groupMatrix(groups,world,local).extractBasis(...directions);
  origin.setFromMatrixPosition(world);
  projected.copy(origin).project(camera);
  if(projected.z < -1 || projected.z > 1 || !Number.isFinite(projected.z))return false;
  const x=(1+projected.x)*width/2,y=(1-projected.y)*height/2;
  const depth=camera.isOrthographicCamera?radius*zoom:-projected.copy(origin).applyMatrix4(camera.matrixWorldInverse).z;
  const length=depth*2*Math.tan(Math.PI/8)*64/height;
  const svg=overlay.firstElementChild;
  svg.setAttribute('viewBox',`0 0 ${width} ${height}`);
  for(const [index,axis] of Array.from(svg.children).entries()){
    projected.copy(directions[index]).setLength(length).add(origin).project(camera);
    const endX=(1+projected.x)*width/2,endY=(1-projected.y)*height/2;
    axis.setAttribute('transform',`translate(${x} ${y})`);
    const [line,label]=axis.children;
    line.setAttribute('x2',endX-x);line.setAttribute('y2',endY-y);
    label.setAttribute('x',endX-x+4);label.setAttribute('y',endY-y-4);
  }
  projected.setFromMatrixPosition(local);
  const coordinates=['x','y','z'].map(axis=>`${axis.toUpperCase()} ${Number(projected[axis].toFixed(4))}`);
  const frame=groups.length>1?'親座標':'ワールド座標';
  $('local-axes-origin').textContent=`原点（${frame}） ${coordinates.join(' / ')}`;
  overlay.hidden=false;
  return true;
}
function gridSettings(){
  const spacing=Number($('grid-spacing').value),offset=Number($('grid-offset').value);
  const plane=$('grid-plane').value;
  if(!$('grid-spacing').value.trim() || !Number.isFinite(spacing) || spacing<=0 ||
     !$('grid-offset').value.trim() || !Number.isFinite(offset) || Math.abs(offset)>1e30 ||
     !['xy','yz','zx'].includes(plane))return null;
  return {spacing,offset,axes:{xy:[0,1,2],yz:[1,2,0],zx:[2,0,1]}[plane]};
}
function gridRange(low, high, spacing=1){
  const first=Math.floor(low/spacing)-2,last=Math.ceil(high/spacing)+2;
  if(last-first<=100)return [first,last];
  const middle=Math.round((low/spacing+high/spacing)/2);
  return [middle-50,middle+50];
}
function gridPoints(lo,hi,settings={spacing:1,offset:0,axes:[0,1,2]}){
  const {spacing,offset,axes:[u,v,n]}=settings;
  if(!Number.isFinite(spacing) || spacing<=0 || !Number.isFinite(offset) || Math.abs(offset)>1e30)return [];
  // Above this range Float32 positions cannot resolve adjacent grid points.
  if([lo[u],hi[u],lo[v],hi[v]].some(value=>Math.abs(value/spacing)>8_388_608))return [];
  const [u0,u1]=gridRange(lo[u],hi[u],spacing);
  const [v0,v1]=gridRange(lo[v],hi[v],spacing);
  const positions=[];
  for(let a=u0;a<=u1;a++)for(let b=v0;b<=v1;b++){
    const point=[0,0,0];point[u]=a*spacing;point[v]=b*spacing;point[n]=offset;
    positions.push(...point);
  }
  return positions;
}
function updateGuides(lo,hi){
  for(const {object,worldGeometry,localGeometry} of guides){
    scene.remove(object);
    (worldGeometry||object.geometry).dispose();
    localGeometry?.dispose();
    object.material.dispose();
  }
  guides=[];
  guideBounds=lo.every(Number.isFinite) && hi.every(Number.isFinite)?[lo.slice(),hi.slice()]:null;
  if(!guideBounds)return;
  const pad=Math.max(2,radius*0.1);
  const ends=[0,1,2].map(axis=>[Math.min(0,lo[axis]-pad),Math.max(0,hi[axis]+pad)]);
  for(const [axis,color] of [[0,0xff6262],[1,0x65d98a],[2,0x69aaff]]){
    const positions=[0,0,0,0,0,0];
    positions[axis]=ends[axis][0];positions[axis+3]=ends[axis][1];
    const geometry=new THREE.BufferGeometry();
    geometry.setAttribute('position',new THREE.BufferAttribute(new Float32Array(positions),3));
    const object=new THREE.LineSegments(geometry,new THREE.LineBasicMaterial({color,toneMapped:false,depthTest:false,depthWrite:false}));
    object.renderOrder=1;
    scene.add(object);guides.push({object,toggle:'show-axes'});
  }
  const settings=gridSettings()||{spacing:1,offset:0,axes:[0,1,2]};
  const worldGeometry=gridGeometry(lo,hi,settings);
  const object=new THREE.Points(worldGeometry,new THREE.PointsMaterial({color:0xb3c4d0,size:3,sizeAttenuation:false,transparent:true,opacity:0.65,depthWrite:false,toneMapped:false}));
  scene.add(object);guides.push({object,toggle:'show-grid',settings,worldGeometry});
}
function gridGeometry(lo,hi,settings){
  const geometry=new THREE.BufferGeometry();
  geometry.setAttribute('position',new THREE.BufferAttribute(new Float32Array(gridPoints(lo,hi,settings)),3));
  return geometry;
}
function changeGrid(){
  const valid=!!gridSettings();
  $('grid-spacing').setAttribute?.('aria-invalid',String(!valid));
  $('grid-offset').setAttribute?.('aria-invalid',String(!valid));
  if(valid && guideBounds){updateGuides(...guideBounds);draw();}
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
function faceNormalColors(positions){
  const colors=new Float32Array(positions.length);
  const linearChannel=value=>{
    const srgb=Math.max(0,Math.min(1,(value+1)/2));
    return srgb<=0.04045?srgb/12.92:((srgb+0.055)/1.055)**2.4;
  };
  for(let i=0;i<positions.length;i+=9){
    const ax=positions[i+3]-positions[i],ay=positions[i+4]-positions[i+1],az=positions[i+5]-positions[i+2];
    const bx=positions[i+6]-positions[i],by=positions[i+7]-positions[i+1],bz=positions[i+8]-positions[i+2];
    const nx=ay*bz-az*by,ny=az*bx-ax*bz,nz=ax*by-ay*bx;
    const length=Math.hypot(nx,ny,nz);
    const rgb=[linearChannel(length?nx/length:0),linearChannel(length?ny/length:0),linearChannel(length?nz/length:0)];
    for(let j=i;j<i+9;j+=3)colors.set(rgb,j);
  }
  return colors;
}
function show(meshes){
  animationPlayer?.clear();
  for(const mesh of rendered){
    scene.remove(mesh.solid,mesh.normal,mesh.wire);
    mesh.solid.geometry.dispose();mesh.solid.material.dispose();
    mesh.normal.material.dispose();
    mesh.wire.geometry.dispose();mesh.wireMaterial.dispose();
  }
  rendered=[];
  const lo=[Infinity,Infinity,Infinity],hi=[-Infinity,-Infinity,-Infinity];
  for(const mesh of meshes){
    const geometry=new THREE.BufferGeometry();
    geometry.setAttribute('position',new THREE.BufferAttribute(new Float32Array(mesh.positions),3));
    geometry.setAttribute('normal',new THREE.BufferAttribute(new Float32Array(mesh.normals),3));
    geometry.setAttribute('color',new THREE.BufferAttribute(faceNormalColors(mesh.positions),3));
    const color=new THREE.Color().setRGB(...mesh.material.baseColor,THREE.LinearSRGBColorSpace);
    const solid=new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({
      color,metalness:mesh.material.metallic,roughness:mesh.material.roughness
    }));
    const normal=new THREE.Mesh(geometry,new THREE.MeshBasicMaterial({vertexColors:true,side:THREE.DoubleSide,toneMapped:false}));
    const edgeGeometry=new THREE.BufferGeometry();
    edgeGeometry.setAttribute('position',new THREE.BufferAttribute(triangleEdges(mesh.positions),3));
    const lineColor=new THREE.Color().setRGB(...mesh.material.baseColor.map(c=>0.45+0.55*c),THREE.LinearSRGBColorSpace);
    const wire=new THREE.LineSegments(edgeGeometry,new THREE.LineBasicMaterial({color:lineColor}));
    scene.add(solid,normal,wire);
    rendered.push({solid,normal,wire,wireMaterial:wire.material,groupPath:mesh.groupPath||[],nodeKeys:previewNodeKeys(mesh)});
    for(let i=0;i<mesh.positions.length;i+=3)for(let j=0;j<3;j++){lo[j]=Math.min(lo[j],mesh.positions[i+j]);hi[j]=Math.max(hi[j],mesh.positions[i+j]);}
  }
  if(meshes.length && resetPreviewView){
    center=lo.map((x,i)=>(x+hi[i])/2);
    radius=Math.max(1,Math.hypot(...sub(hi,lo))/2);
    yaw=-0.72;pitch=0.44;zoom=meshes.length>1?2.25:2.8;
    resetPreviewView=false;
  }
  updateGuides(lo,hi);
  draw();
}
async function request(path,filename){
  const data={animationSource:animationText(),mode:$('mode').value,source:$('source').value,chord:Number($('chord').value),angle:Number($('angle').value)};
  data.animationClip=selectedAnimationClip();
  if(path==='/animation/resolve'){
    const paths=new Map(currentMeshes.map(mesh=>{
      const groupPath=(mesh.groupPath||[]).map(({name,position,euler,scale,quaternion})=>({name,position,euler,scale,quaternion}));
      return [JSON.stringify(groupPath.map(group=>group.name)),{groupPath}];
    }));
    data.animationGroups=[...paths.values()];
  }
  if(filename)data.filename=filename;
  if(path==='/export' || path==='/export/usdz' || path==='/preview/usdz'){
    if(!$('export-scale').checkValidity() || $('export-scale').value.trim()==='')throw Error('保存時の座標倍率は正の数値にしてください');
    data.exportScale=ModelFile.exportScale(Number($('export-scale').value));
  }
  const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  if(!response.ok){const data=await response.json();throw Error(data.error||'Processing failed');}
  return response;
}
function updateObjectTree(objects){
  const roots=new Map();
  for(const object of objects){
    let children=roots;
    for(const group of object.groupPath||[]){
      const key='group:'+group.name;
      if(!children.has(key))children.set(key,{name:group.name,group:true,children:new Map()});
      children=children.get(key).children;
    }
    children.set('solid:'+object.name,{name:object.name,group:false,children:new Map()});
  }
  function nodes(children){
    return [...children.values()].map(node=>node.group
      ? {type:'group',name:node.name,children:nodes(node.children)}
      : {type:'solid',name:node.name});
  }
  renderObjectTree(nodes(roots));
}
function renderObjectTree(nodes){
  currentObjectTree=ModelFile.objectTree(nodes);
  hiddenPreviewNodes.clear();
  selectedPreviewNode=null;
  const tree=$('object-tree'),entries=[];
  tree.textContent='';
  function refresh(){
    for(const {checkbox,row,label,path,key,node} of entries){
      const visible=!path.some((_,index)=>hiddenPreviewNodes.has(JSON.stringify(path.slice(0,index+1))));
      checkbox.checked=!hiddenPreviewNodes.has(key);
      checkbox.setAttribute('aria-label',`${node.name} を${hiddenPreviewNodes.has(key)?'表示':'非表示'}`);
      checkbox.title=checkbox.disabled?'表示切替は WebGL プレビューで利用できます':checkbox.getAttribute('aria-label');
      const selected=selectedPreviewNode===key;
      label.setAttribute('aria-pressed',String(selected));
      row.className='object-tree-row'+(visible?'':' is-hidden')+(selected?' is-selected':'');
    }
  }
  function append(children,prefix,parentPath){
    children.forEach((node,index)=>{
      const last=index===children.length-1;
      const path=[...parentPath,[node.type,node.name]],key=JSON.stringify(path);
      const row=document.createElement('div'),branch=document.createElement('span'),label=document.createElement('button'),checkbox=document.createElement('input');
      branch.className='object-tree-branch';
      branch.textContent=`${prefix}${last?'└─ ':'├─ '}`;
      label.textContent=`${node.name}${node.type==='group'?' (G)':''}`;
      label.type='button';label.className='object-tree-label';
      checkbox.type='checkbox';checkbox.className='object-visibility';
      checkbox.disabled=$('preview-mode').value==='model';
      label.disabled=checkbox.disabled;
      label.onclick=()=>{
        if($('preview-mode').value!=='webgl')return;
        selectedPreviewNode=selectedPreviewNode===key?null:key;
        refresh();draw();
      };
      checkbox.onclick=()=>{
        if($('preview-mode').value==='model')return;
        if(hiddenPreviewNodes.has(key))hiddenPreviewNodes.delete(key);else hiddenPreviewNodes.add(key);
        refresh();draw();
      };
      row.appendChild(branch);row.appendChild(checkbox);row.appendChild(label);tree.appendChild(row);
      entries.push({checkbox,row,label,path,key,node});
      if(node.type==='group')append(node.children,prefix+(last?'   ':'│  '),path);
    });
  }
  append(currentObjectTree,'',[]);
  if(!entries.length)tree.textContent='オブジェクトはありません';
  refresh();draw();
}

async function preview(){
  saveDraft();
  animationPlayer?.pause();
  const requestId=++previewRequestId;
  const previewModelKey=modelingKey();
  const previewSource=$('source').value,previewMode=$('mode').value,previewAnimationSource=animationText();
  $('preview').disabled=true;$('export').disabled=true;$('export-usdz').disabled=true;note('計算中…');
  try{
    if($('preview-mode').value==='model'){
      const error=modelModeError();if(error)throw Error(error);
      showPreviewMode();usdModel.hidden=true;modelStatus.textContent='USDZ を生成中…';
      const data=await(await request('/preview/usdz')).json();
      if(requestId!==previewRequestId)return;
      usdModel.src=data.url;usdModel.hidden=false;modelStatus.textContent='USDZ を読み込み中…';
      if(usdModel.ready)await usdModel.ready;
      if(requestId!==previewRequestId)return;
      if(data.animationClips)updateClipOptions(data.animationClips,data.animationClip);
      updateObjectTree(data.objects||[]);
      modelStatus.hidden=true;note('USDZ <model> プレビューを更新しました');
    }else{
      showPreviewMode();
      const data=await(await request('/preview')).json();
      if(requestId!==previewRequestId)return;
      currentMeshes=data.meshes;currentMeshKey=previewModelKey;
      resolvedAnimation=typeof data.resolvedAnimationSource==='string'
        ? {key:JSON.stringify([previewMode,previewSource,previewAnimationSource]),source:data.resolvedAnimationSource}:null;
      show(data.meshes);
      if(animationPlayer && data.meshes.length)await applyAnimation();
      updateObjectTree(data.meshes);
      const triangles=data.meshes.reduce((n,m)=>n+m.positions.length/9,0);
      $('mesh-stats').textContent=`トライアングル数: ${triangles.toLocaleString()}\nソリッド数: ${data.meshes.length.toLocaleString()}`;
      note(data.log || 'プレビューを更新しました');
    }
    $('export').disabled=false;$('export-usdz').disabled=false;
    previewFailure=null;return true;
  }catch(e){if(requestId!==previewRequestId)return;previewFailure={source:previewSource,mode:previewMode,animationSource:previewAnimationSource,error:e.message};if($('preview-mode').value==='model'){usdModel.hidden=true;modelStatus.textContent=e.message;modelStatus.hidden=false;}note(e.message,true);return false;}finally{if(requestId===previewRequestId)$('preview').disabled=false;}
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
  try{const name=saveFileName(format),response=await request(format==='usdz'?'/export/usdz':'/export',name),blob=await response.blob(),url=URL.createObjectURL(blob);
    const meshCount=response.headers.get('X-Mesh-Count'),materialCount=response.headers.get('X-Material-Count');
    const counts=`mesh数 ${meshCount===null?'—':Number(meshCount).toLocaleString()} / material数 ${materialCount===null?'—':Number(materialCount).toLocaleString()}`;
    const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    note(`${name} (${(blob.size/1024).toFixed(1)} KiB) を保存しました · ${counts}`);
  }catch(e){note(e.message,true);}finally{$(id).disabled=false;}
}
function modelDocument(validateAnimation=true){
  for(const id of ['chord','angle','export-scale']){
    if(!$(id).checkValidity() || $(id).value.trim()==='') throw Error(`${$(id).labels[0]?.textContent || id} の値が不正です`);
  }
  return ModelFile.validate({
    format:'smlib-model',version:1,mode:$('mode').value,source:$('source').value,animationSource:animationText(),animationClip:validateAnimation?selectedAnimationClip():$('animation-clip').value,
    objectTree:currentObjectTree,
    parameters:{chord:Number($('chord').value),angle:Number($('angle').value),
      exportScale:Number($('export-scale').value)}
  },validateAnimation);
}
async function saveModel(){
  $('save-model').disabled=true;
  try{
    const name=saveFileName('json');
    const data=modelDocument();
    const chat=globalThis.ModelChat?.snapshot();
    if(chat)data.chat=ModelFile.chat(chat);
    const content=JSON.stringify(data,null,2)+'\n';
    const blob=new Blob([content],{type:'application/json'});
    if(blob.size>16_000_000)throw Error('JSONファイルは16 MB以下にしてください');
    const response=await fetch('/save/json',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({filename:name,content})});
    if(!response.ok){const error=await response.json();throw Error(error.error||'保存に失敗しました');}
    const url=URL.createObjectURL(blob),a=document.createElement('a');
    a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    note(`${name} を保存しました`);
  }catch(e){note(e.message,true);}finally{$('save-model').disabled=false;}
}
async function loadModel(file){
  if(!file)return;
  let text;
  try{
    if(file.size>16_000_000)throw Error('JSONファイルは16 MB以下にしてください');
    text=await file.text();
    const data=ModelFile.parse(text),p=data.parameters;
    globalThis.ModelChat?.assertIdle();
    animationPlayer?.clear();
    $('animation-source').value=data.animationSource || '';
    restoreClipSelection(data.animationClip);
    $('mode').value=data.mode;$('sample').value='default';$('source').value=data.source;
    refreshSourceLines();
    $('chord').value=p.chord;$('angle').value=p.angle;
    $('export-scale').value=p.exportScale;
    if(file.name && /\.json$/i.test(file.name))$('file-name').value=file.name.replace(/\.json$/i,'');
    $('save-model').disabled=false;
    $('export').disabled=true;$('export-usdz').disabled=true;
    globalThis.ModelChat?.restore(data.chat);
    renderObjectTree(data.objectTree||[]);
    previewFailure=null;
    resetPreviewView=true;
  }catch(e){
    const fileInfo=`${file.name || 'JSON'}: ${file.size} bytes${text===undefined ? '' : ` / 読み取り後 ${new Blob([text]).size} bytes`}`;
    note(`JSONを読み込めません: ${e.message}\n${fileInfo}`,true);return;
  }
  finally{$('model-file').value='';}
  await preview();
}
$('preview').onclick=preview;$('export').onclick=()=>exportFile('glb');$('export-usdz').onclick=()=>exportFile('usdz');
$('save-model').onclick=saveModel;
$('load-model').onclick=()=>$('model-file').click();
$('model-file').onchange=e=>loadModel(e.target.files[0]);
$('shading-mode').onchange=draw;
$('projection-mode').onchange=changeProjection;
$('show-axes').onchange=draw;$('show-grid').onchange=draw;
for(const id of ['grid-spacing','grid-plane','grid-offset']){
  $(id).oninput=changeGrid;$(id).onchange=changeGrid;
}
$('preview-mode').onchange=()=>{
  if($('preview-mode').value==='model'){
    const error=modelModeError();
    if(error){$('preview-mode').value='webgl';showPreviewMode();note(error,true);return;}
  }
  showPreviewMode();preview();
};
$('mode').onchange=()=>{resetPreviewView=true;animationPlayer?.clear();restoreClipSelection();$('animation-source').value='';$('sample').value='default';$('source').value=examples[$('mode').value]||'';refreshSourceLines();$('export').disabled=true;$('export-usdz').disabled=true;saveDraft();};
function clearModel(){
  // Invalidate pending previews so an older response cannot restore the model.
  ++previewRequestId;
  previewFailure=null;
  resetPreviewView=true;
  animationPlayer?.clear();restoreClipSelection();$('animation-source').value='';
  $('source').value='';
  refreshSourceLines();
  currentMeshes=[];
  if(scene)show([]);
  usdModel.removeAttribute('src');usdModel.hidden=true;
  modelStatus.textContent='';modelStatus.hidden=true;
  $('mesh-stats').textContent='トライアングル数: 0\nソリッド数: 0';
  updateObjectTree([]);
  $('export').disabled=true;$('export-usdz').disabled=true;
  $('preview').disabled=!renderer;
  viewPointers.clear();
  note('');
  saveDraft();
}
$('example').onclick=()=>{
  if($('sample').value==='clear'){clearModel();return;}
  const sample=$('sample').value;
  const variants=examples.variants?.[sample] || (sample==='default'
    ? {text:examples.text,python:examples.python} : {text:examples[sample]});
  const mode=typeof variants[$('mode').value]==='string' ? $('mode').value
    : ['text','python'].find(mode=>typeof variants[mode]==='string');
  if(!mode){note('このサンプルはまだ読み込めません。',true);return;}
  resetPreviewView=true;
  animationPlayer?.clear();restoreClipSelection();$('animation-source').value=examples.animations?.[sample] || '';
  $('mode').value=mode;$('source').value=variants[mode];
  refreshSourceLines();
  $('export').disabled=true;$('export-usdz').disabled=true;
  preview();
};
$('source').addEventListener('keydown',e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();preview();}});
$('source').addEventListener('input',refreshSourceLines);
$('source').addEventListener('scroll',()=>syncSourceLineScroll('source'));
$('animation-source').addEventListener?.('input',refreshSourceLines);
$('animation-source').addEventListener?.('scroll',()=>syncSourceLineScroll('animation-source'));
// Track captured pointers so a second finger switches rotation to pinch zoom.
const viewPointers = new Map();
function pinchDistance(){
  const [a,b]=Array.from(viewPointers.values());
  return Math.hypot(a[0]-b[0],a[1]-b[1]);
}
function setZoom(value){zoom=Math.max(0.1,Math.min(30,value));}
canvas.addEventListener('pointerdown',e=>{
  if(e.pointerType==='mouse' && e.button!==0)return;
  viewPointers.set(e.pointerId,[e.clientX,e.clientY]);
  canvas.setPointerCapture(e.pointerId);
});
function endViewPointer(e){viewPointers.delete(e.pointerId);}
canvas.addEventListener('pointerup',endViewPointer);
canvas.addEventListener('pointercancel',endViewPointer);
canvas.addEventListener('lostpointercapture',endViewPointer);
canvas.addEventListener('pointermove',e=>{
  const previous=viewPointers.get(e.pointerId);
  if(!previous)return;
  const before=viewPointers.size>=2?pinchDistance():0;
  viewPointers.set(e.pointerId,[e.clientX,e.clientY]);
  if(viewPointers.size>=2){
    const after=pinchDistance();
    if(before>0 && after>0)setZoom(zoom*before/after);
  }else{
    yaw-=(e.clientX-previous[0])*0.007;
    pitch=Math.max(-Math.PI/2,Math.min(Math.PI/2,pitch+(e.clientY-previous[1])*0.007));
  }
  draw();
});
canvas.addEventListener('wheel',e=>{e.preventDefault();setZoom(zoom*Math.exp(e.deltaY*0.001));draw();},{passive:false});
canvas.ondblclick=()=>{yaw=-0.72;pitch=0.44;zoom=2.8;draw();};
new ResizeObserver(draw).observe(canvas);
const restoredDraft=restoreDraft();
refreshSourceLines();
async function startupJson(path){
  const controller=typeof AbortController==='function'?new AbortController():null;
  let timer;
  const timeout=new Promise((_,reject)=>{
    if(typeof setTimeout==='function')timer=setTimeout(()=>{
      reject(Error(`${path} の読み込みが時間切れになりました`));
      controller?.abort();
    },10000);
  });
  try{
    return await Promise.race([
      fetch(path,controller?{signal:controller.signal}:{}).then(async response=>{
        if(!response.ok)throw Error(`${path} の読み込みに失敗しました (${response.status})`);
        return response.json();
      }),timeout
    ]);
  }finally{if(timer!==undefined)clearTimeout(timer);}
}
async function initializeApp(loadThree=()=>import('https://cdn.jsdelivr.net/npm/three@0.186.1/build/three.module.js')){
  // These requests run independently so a stalled response cannot hide the editor.
  const examplesTask=startupJson('/examples').then(data=>{
    examples=data;
    if(!restoredDraft && !draftEdited && !$('source').value){$('source').value=examples.text;refreshSourceLines();}
  }).catch(error=>{if(!restoredDraft)note(error.message,true);});
  const statusTask=startupJson('/status').then(state=>{
    $('status').textContent=state.ready?'SMLib 接続済み':`_smlib_core 未導入: ${state.error}`;
    if(!state.ready)note('SMLib の Python バインディングをビルドしてください。セットアップは README を参照。',true);
    return state;
  }).catch(error=>{
    $('status').textContent='SMLib 接続確認失敗';
    note(error.message,true);
    return {ready:false};
  });
  try{
    THREE=await loadThree();
    setupRenderer();
    $('preview').disabled=false;
    $('preview-mode').disabled=false;
    showPreviewMode();
  }catch(error){note(error.message,true);return;}
  const state=await statusTask;
  if(restoredDraft){
    if(!$('source').value.trim())clearModel();
    else if(state.ready)await preview();
  }
  await examplesTask;
}
initializeApp();
