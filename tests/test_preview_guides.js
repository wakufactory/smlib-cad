const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const elements = {
  canvas: {clientWidth: 600, clientHeight: 400, addEventListener() {}},
  source: {addEventListener() {}},
  message: {style: {}},
  'show-axes': {checked: true},
  'show-grid': {checked: true},
  'grid-spacing': {value: '1'},
  'grid-plane': {value: 'xy'},
  'grid-offset': {value: '0'},
  'projection-mode': {value: 'orthographic'},
  'shading-mode': {value: 'shading'}
};
class Geometry {
  constructor() { this.attributes = {}; this.disposed = false; }
  setAttribute(name, value) { this.attributes[name] = value; }
  dispose() { this.disposed = true; }
}
class Material {
  constructor(options) { this.options = options; this.disposed = false; }
  dispose() { this.disposed = true; }
}
class Object3D {
  constructor(geometry, material) { this.geometry = geometry; this.material = material; this.visible = true; }
  add(child) { child.parent = this; }
}
const THREE = {
  BufferGeometry: Geometry,
  BufferAttribute: class { constructor(array) { this.array = array; } },
  LineBasicMaterial: Material, PointsMaterial: Material,
  MeshStandardMaterial: Material, MeshBasicMaterial: Material,
  LineSegments: Object3D, Points: Object3D, Mesh: Object3D,
  Color: class { setRGB() { return this; } },
  LinearSRGBColorSpace: 'linear', DoubleSide: 'double'
};
const objects = new Set();
const scene = {
  add(...items) { for (const item of items) objects.add(item); },
  remove(...items) { for (const item of items) objects.delete(item); }
};
const camera = {
  updateProjectionMatrix() {}, updateMatrixWorld() {},
  position: {set() {}}, up: {set() {}}, lookAt() {}, add() {}
};
let renders = 0;
const renderer = {setSize() {}, render() { renders++; }};
const context = vm.createContext({
  document: {getElementById: id => elements[id] ||= {},
    createElement: () => ({children: [], attributes: {}, appendChild(child) {this.children.push(child);},
      setAttribute(name, value) {this.attributes[name] = value;}, getAttribute(name) {return this.attributes[name];}})},
  ResizeObserver: class {observe() {}},
  fetch: () => new Promise(() => {}),
  window: {}, location: {protocol: 'http:'},
  console
});
vm.runInContext(fs.readFileSync(require.resolve('../html/app.js'), 'utf8'), context);
context.THREE = THREE;
vm.runInContext('THREE = globalThis.THREE; scene = globalThis.scene; camera = globalThis.camera; renderer = globalThis.renderer',
  Object.assign(context, {scene, camera, renderer}));

context.updateGuides([-1, -1, -1], [1, 1, 1]);
assert.equal(objects.size, 4);
const first = Array.from(objects);
assert.deepEqual(Array.from(first[0].geometry.attributes.position.array), [-3, 0, 0, 3, 0, 0]);
assert.deepEqual(Array.from(first[1].geometry.attributes.position.array), [0, -3, 0, 0, 3, 0]);
assert.deepEqual(Array.from(first[2].geometry.attributes.position.array), [0, 0, -3, 0, 0, 3]);
assert.equal(first[3].geometry.attributes.position.array.length / 3, 49);
assert.deepEqual(Array.from(first[3].geometry.attributes.position.array.slice(0, 3)), [-3, -3, 0]);
const orthoCamera = {...camera, isOrthographicCamera: true};
context.orthographicCamera=orthoCamera;
context.perspectiveCamera=camera;
context.cameraLight={target:{}};
vm.runInContext('orthographicCamera=globalThis.orthographicCamera; perspectiveCamera=globalThis.perspectiveCamera; cameraLight=globalThis.cameraLight',context);
elements['projection-mode'].value='orthographic';
elements['projection-mode'].onchange();
assert.equal(vm.runInContext('camera',context),orthoCamera);
const halfHeight=20*2.8*Math.tan(Math.PI/8);
assert(Math.abs(orthoCamera.top-halfHeight)<1e-9);
assert(Math.abs(orthoCamera.right-halfHeight*1.5)<1e-9);
context.setZoom(2);
elements.canvas.clientWidth=400;
context.draw();
assert(Math.abs(orthoCamera.top-20*2*Math.tan(Math.PI/8))<1e-9);
assert(Math.abs(orthoCamera.right-orthoCamera.top)<1e-9);
context.setZoom(2.8);
elements.canvas.clientWidth=600;
elements['projection-mode'].value='perspective';
elements['projection-mode'].onchange();
assert.equal(vm.runInContext('camera',context),camera);
elements['grid-spacing'].value = '2';
elements['grid-plane'].value = 'yz';
elements['grid-offset'].value = '5';
elements['grid-offset'].oninput();
let changed = Array.from(objects)[3];
assert.equal(changed.geometry.attributes.position.array.length / 3, 49);
assert.deepEqual(Array.from(changed.geometry.attributes.position.array.slice(0, 3)), [5, -6, -6]);
elements['grid-plane'].value = 'zx';
elements['grid-plane'].onchange();
changed = Array.from(objects)[3];
assert.deepEqual(Array.from(changed.geometry.attributes.position.array.slice(0, 3)), [-6, 5, -6]);
elements['grid-spacing'].value = '0';
elements['grid-spacing'].oninput();
assert.equal(Array.from(objects)[3], changed, 'invalid spacing retains the last valid grid');
elements['grid-spacing'].value = '1';
elements['grid-plane'].value = 'xy';
elements['grid-offset'].value = '0';
elements['grid-spacing'].oninput();

const current = Array.from(objects);
const beforeDraw = renders;
context.draw();
assert.equal(renders, beforeDraw + 1);
elements['show-axes'].checked = false;
elements['show-axes'].onchange();
assert.equal(renders, beforeDraw + 2);
assert(current.slice(0, 3).every(object => !object.visible));
assert.equal(current[3].visible, true);
elements['show-grid'].checked = false;
elements['show-grid'].onchange();
assert.equal(current[3].visible, false);

context.updateGuides([10, 20, 0], [11, 21, 1]);
assert(first.every(object => object.geometry.disposed && object.material.disposed));
assert.equal(objects.size, 4);
context.draw();
assert(Array.from(objects).every(object => !object.visible));

const mesh = {name: 'face', positions: [0, 0, 0, 1, 0, 0, 0, 1, 0],
  normals: [0, 0, -1, 0, 0, -1, 0, 0, -1],
  material: {baseColor: [0.2, 0.4, 0.6], metallic: 0, roughness: 1}};
context.show([mesh]);
const preview = vm.runInContext('rendered[0]', context);
const colors = Array.from(preview.normal.geometry.attributes.color.array);
const middle = ((0.5 + 0.055) / 1.055) ** 2.4;
for (let i = 0; i < colors.length; i += 3) {
  assert(Math.abs(colors[i] - middle) < 1e-6);
  assert(Math.abs(colors[i + 1] - middle) < 1e-6);
  assert.equal(colors[i + 2], 1); // Geometry faces +Z; supplied smooth normals point -Z.
}
assert.equal(preview.normal.material.options.vertexColors, true);
assert.equal(preview.normal.material.options.toneMapped, false);
assert.equal(preview.normal.geometry, preview.solid.geometry);
const negativeZ = context.faceNormalColors([0, 0, 0, 0, 1, 0, 1, 0, 0]);
assert(Math.abs(negativeZ[0] - middle) < 1e-6);
assert(Math.abs(negativeZ[1] - middle) < 1e-6);
assert.equal(negativeZ[2], 0);
const positiveX = context.faceNormalColors([0, 0, 0, 0, 1, 0, 0, 0, 1]);
assert.equal(positiveX[0], 1);
assert(Math.abs(positiveX[1] - middle) < 1e-6);
assert(Math.abs(positiveX[2] - middle) < 1e-6);

for (const [mode, expected] of [
  ['shading', [true, false, false]],
  ['wireframe', [false, false, true]],
  ['normal', [false, true, false]]
]) {
  elements['shading-mode'].value = mode;
  elements['shading-mode'].onchange();
  assert.deepEqual([preview.solid.visible, preview.normal.visible, preview.wire.visible], expected);
}
context.show([mesh]);
assert(preview.solid.geometry.disposed);
assert(preview.normal.material.disposed);
assert.equal(vm.runInContext('rendered[0].normal.visible', context), true);
console.log('preview guides: axes, configurable grid, toggles, and recalculation passed');

// Clear removes geometry and guides, resets counts, and invalidates pending work.
elements['usd-model'].src = '/preview/assets/old.usdz';
elements['usd-model'].removeAttribute = function(name) { delete this[name]; };
elements.source.value = 'box old 0 0 0 1 1 1';
const priorRequest = vm.runInContext('previewRequestId', context);
context.clearModel();
assert.equal(objects.size, 0);
assert.equal(elements.source.value, '');
assert.equal(elements['usd-model'].src, undefined);
assert.equal(elements['usd-model'].hidden, true);
assert.equal(elements['model-status'].hidden, true);
assert.equal(elements['mesh-stats'].textContent, 'トライアングル数: 0\nソリッド数: 0');
assert.equal(elements['object-tree'].textContent, 'オブジェクトはありません');
assert.equal(elements.export.disabled, true);
assert.equal(elements['export-usdz'].disabled, true);
assert.equal(vm.runInContext('currentMeshes.length', context), 0);
assert.equal(vm.runInContext('previewRequestId', context), priorRequest + 1);
console.log('clear model: geometry, guides, USDZ, counts, and pending preview reset passed');

// Tree visibility only changes cached render objects, including all display modes.
elements['object-tree'] = {children: [], appendChild(row) {this.children.push(row);}};
elements['preview-mode'].value = 'webgl';
const treeMeshes = [
  {...mesh, name:'face', groupPath:[{name:'assembly'}]},
  {...mesh, name:'face', groupPath:[{name:'other'}]},
  {...mesh, name:'bolt', groupPath:[{name:'assembly'},{name:'detail'}]}
];
context.show(treeMeshes);
context.updateObjectTree(treeMeshes);
const rows = elements['object-tree'].children;
const checkboxes = rows.map(row => row.children[1]);
const snapshot = vm.runInContext('JSON.stringify(currentObjectTree)',context);
let unexpectedSideEffects = 0;
context.request = context.saveDraft = context.saveModel = () => {unexpectedSideEffects++;};
// assembly, face, detail, bolt, other, face
checkboxes[1].onclick();
checkboxes[0].onclick();
checkboxes[0].onclick();
for(const mode of ['shading','wireframe','normal']) {
  elements['shading-mode'].value = mode;
  context.draw();
  const visible = vm.runInContext('rendered.map(mesh => [mesh.solid,mesh.normal,mesh.wire].some(object => object.visible))', context);
  assert.deepEqual(Array.from(visible), [false,true,true], 'child stays hidden after restoring parent; duplicate name is independent');
}
checkboxes[2].onclick();
assert.equal(vm.runInContext('rendered[2].normal.visible',context),false,'nested group hides its descendants');
assert.equal(checkboxes[3].checked,true,'child retains its own visibility');
assert(rows[3].className.includes('is-hidden'),'ancestor hiding is reflected in tree');
assert.equal(vm.runInContext('JSON.stringify(currentObjectTree)',context),snapshot,'visibility is absent from saved model');
assert.equal(unexpectedSideEffects,0,'toggle performs no requests or saves');

const labels = rows.map(row => row.children[2]);
const previews = vm.runInContext('rendered', context);
labels[5].onclick();
assert(rows[5].className.includes('is-selected'));
assert.equal(labels[5].getAttribute('aria-pressed'),'true');
assert.equal(previews[1].highlight.parent,previews[1].normal);
assert.equal(previews[0].highlight,undefined,'the same name under another group is independent');
elements['shading-mode'].value = 'shading';
context.draw();
assert.equal(previews[1].highlight.parent,previews[1].solid);
elements['shading-mode'].value = 'wireframe';
context.draw();
assert.equal(previews[1].wire.material.options.color,0x64dcff);
assert.equal(previews[1].highlight.visible,false);
labels[5].onclick();
assert.equal(labels[5].getAttribute('aria-pressed'),'false');
assert.equal(previews[1].wire.material,previews[1].wireMaterial);

// The selected prefix is supplied to the pose calculation, even if the child is hidden.
const element = (children=[]) => ({children,attributes:{},
  setAttribute(name,value){this.attributes[name]=value;}});
const svg = element(Array.from({length:3},()=>element([element(),element()])));
const axes = elements['local-axes'] = {firstElementChild:svg};
THREE.Matrix4 = class {
  extractBasis(...directions){directions.forEach((vector,i)=>vector.x=i+1);}
  invert(){return this;}
  copy(matrix){this.position=matrix.position;return this;}
  identity(){this.position=[0,0,0];return this;}
};
THREE.Vector3 = class {
  constructor(x,y,z){Object.assign(this,{x,y,z});}
  toArray(){return [this.x,this.y,this.z];}
  setFromMatrixPosition(matrix){[this.x,this.y,this.z]=matrix.position||[0,0,0];return this;}
  copy(vector){Object.assign(this,vector);return this;}
  project(){return this;}
  setLength(length){this.x*=length;return this;}
  add(origin){this.x+=origin.x;this.y=origin.y;this.z=origin.z;return this;}
};
THREE.Box3 = class {
  constructor(min,max){Object.assign(this,{min,max});}
  applyMatrix4(){}
};
elements['projection-mode'].value='orthographic';
elements['projection-mode'].onchange();
elements['show-axes'].checked=true;
elements['show-axes'].onchange();
const worldAxes=vm.runInContext("guides.filter(guide=>guide.toggle==='show-axes').map(guide=>guide.object)",context);
assert(worldAxes.every(axis=>axis.visible));
let axesPath;
let gridOrigin=[0,0,0];
context.player = {groupMatrix(groups,target,local){
  axesPath=groups.map(group=>group.name);
  target.position=local?gridOrigin:[0,0,0];
  if(local)local.position=[1.25,-2,3];
  return target;
}};
vm.runInContext('animationPlayer=globalThis.player', context);
labels[0].onclick();
assert.deepEqual(Array.from(axesPath),['assembly']);
assert.equal(axes.hidden,false);
assert.equal(elements['local-axes-origin'].textContent,'原点（ワールド座標） X 1.25 / Y -2 / Z 3');
assert.equal(svg.children[0].attributes.transform,'translate(300 200)');
assert(svg.children[0].children[0].attributes.x2>0,'axis direction is projected to the viewport');
assert(worldAxes.every(axis=>!axis.visible),'local axes suppress world axes');
assert.equal(previews[0].wire.material,previews[0].wireMaterial,'hidden child is not highlighted');
checkboxes[2].onclick();
assert.equal(previews[2].wire.material.options.color,0x64dcff,'visible descendant is highlighted');
labels[3].onclick();
assert.deepEqual(Array.from(axesPath),['assembly','detail'],'mesh selection uses its immediate group');
assert.equal(axes.hidden,false);
assert.equal(elements['local-axes-origin'].textContent,'原点（親座標） X 1.25 / Y -2 / Z 3');
assert(worldAxes.every(axis=>!axis.visible));
const grid=vm.runInContext("guides.find(guide=>guide.toggle==='show-grid').object",context);
const worldGrid=grid.geometry;
grid.matrix=new THREE.Matrix4();
elements['show-grid'].checked=true;
elements['show-grid'].onchange();
const localGrid=grid.geometry;
assert.notEqual(localGrid,worldGrid);
gridOrigin=[5,6,0.5];
context.draw();
assert.deepEqual(grid.matrix.position,gridOrigin,'grid follows the current group origin');
assert.equal(grid.geometry,localGrid,'animation reuses the local grid points');
labels[2].onclick();
assert.deepEqual(Array.from(axesPath),['assembly','detail']);
checkboxes[2].onclick();
assert.equal(axes.hidden,true,'hiding the selected group hides its axes');
assert(worldAxes.every(axis=>axis.visible),'world axes return to their existing setting');
assert.equal(grid.geometry,worldGrid);
assert.deepEqual(grid.matrix.position,[0,0,0]);
labels[0].onclick();
labels[0].onclick();
assert.equal(axes.hidden,true,'deselecting clears the overlay');
assert(worldAxes.every(axis=>axis.visible));
assert.equal(unexpectedSideEffects,0,'selection performs no requests or saves');

elements['preview-mode'].value = 'model';
checkboxes[4].onclick();
assert.equal(unexpectedSideEffects,0);
assert.equal(vm.runInContext('hiddenPreviewNodes.size',context),2,'model mode ignores visibility clicks');
elements['object-tree'].children=[];
context.updateObjectTree(treeMeshes);
assert(elements['object-tree'].children.every(row => row.children[1].disabled));
assert(elements['object-tree'].children.every(row => row.children[2].disabled));
assert.equal(vm.runInContext('selectedPreviewNode',context),null);
assert.equal(vm.runInContext('hiddenPreviewNodes.size',context),0,'new preview resets transient visibility');
console.log('object tree: per-node visibility, hierarchy, modes, and no generation/save passed');
