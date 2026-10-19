const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const elements = {
  canvas: {clientWidth: 600, clientHeight: 400, addEventListener() {}},
  source: {addEventListener() {}},
  message: {style: {}},
  'show-axes': {checked: true},
  'show-grid': {checked: true},
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
  updateProjectionMatrix() {},
  position: {set() {}}, lookAt() {}
};
let renders = 0;
const renderer = {setSize() {}, render() { renders++; }};
const context = vm.createContext({
  document: {getElementById: id => elements[id] ||= {}},
  ResizeObserver: class {observe() {}},
  fetch: () => new Promise(() => {}),
  window: {}, location: {protocol: 'http:'},
  console
});
vm.runInContext(fs.readFileSync(require.resolve('../app.js'), 'utf8'), context);
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

context.draw();
assert.equal(renders, 1);
elements['show-axes'].checked = false;
elements['show-axes'].onchange();
assert.equal(renders, 2);
assert(first.slice(0, 3).every(object => !object.visible));
assert.equal(first[3].visible, true);
elements['show-grid'].checked = false;
elements['show-grid'].onchange();
assert.equal(first[3].visible, false);

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
console.log('preview guides: axes, unit grid, toggles, and recalculation passed');

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
assert.equal(elements.export.disabled, true);
assert.equal(elements['export-usdz'].disabled, true);
assert.equal(vm.runInContext('currentMeshes.length', context), 0);
assert.equal(vm.runInContext('previewRequestId', context), priorRequest + 1);
console.log('clear model: geometry, guides, USDZ, counts, and pending preview reset passed');
