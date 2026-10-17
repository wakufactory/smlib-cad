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
  LineSegments: Object3D, Points: Object3D
};
const objects = new Set();
const scene = {add(object) { objects.add(object); }, remove(object) { objects.delete(object); }};
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
console.log('preview guides: axes, unit grid, toggles, and recalculation passed');
