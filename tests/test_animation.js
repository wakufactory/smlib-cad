const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
let next=0,frames=new Map(),draws=0,requests=0;
const context=vm.createContext({
  requestAnimationFrame:fn=>{frames.set(++next,fn);return next;},
  cancelAnimationFrame:id=>frames.delete(id),
  fetch:()=>{requests++;throw Error('Playback must never request geometry');}
});
vm.runInContext(fs.readFileSync(require.resolve('../html/animation.js'),'utf8'),context);
const A=context.ModelAnimation;
const source=fs.readFileSync(require.resolve('../examples/animation_loop.anim'),'utf8');
const plain=value=>JSON.parse(JSON.stringify(value));
assert.equal(A.parse('# empty'),null);
const clip=A.parse(source);
assert.equal(clip.duration,4);
assert.equal(clip.tracks.length,3);
assert.deepEqual(plain(A.sample(clip.tracks[0],1).euler),[0,0,90]);
assert.deepEqual(plain(A.sample(clip.tracks[1],1).position),[6,0,0]);
assert.deepEqual(plain(A.sample(clip.tracks[2],2).scale),[1.6,1.6,1.6]);
const rotationClip=(first,last,channel='euler')=>`animation loop 4\ntrack rotor\nkey 0 ${channel} 0 0 ${first}\nkey 4 ${channel} 0 0 ${last}\nend\nend`;
// Loop endpoints may differ; position/scale cycles jump back at their boundary.
for(const [channel,first,last] of [['position',[0,0,0],[12,0,0]],['euler',[0,0,0],[0,0,180]],['scale',[1,1,1],[2,3,4]]]){
  const source=`animation loop 4\ntrack rotor\nkey 0 ${channel} ${first.join(' ')}\nkey 4 ${channel} ${last.join(' ')}\nend\nend`;
  assert.doesNotThrow(()=>A.validate(source));
  const track=A.parse(source).tracks[0];
  assert.deepEqual(plain(A.sample(track,4)[channel]),last);
  assert.deepEqual(plain(A.sample(track,0)[channel]),first);
  const cyclic=A.parse(source.replace('track rotor',`track rotor\ncycle ${channel} 4`).replace('loop 4','loop 8')).tracks[0];
  assert.deepEqual(plain(A.sample(cyclic,4)[channel]),channel==='euler'?last:first);
}
for(const expression of ['${angle(4)}','angle(period)','${angle(2 + 2) + rpm * 0}', 'sin(radians(360))']){
  const source=rotationClip(0,expression);
  assert.throws(()=>A.parse(source),error=>error.modelReference===true);
  assert.doesNotThrow(()=>A.validate(source));
}
assert.doesNotThrow(()=>A.validate('animation loop ${period}\ntrack rotor\nkey 0 euler 0 0 0\nkey ${period} euler 0 0 ${angle(period)}\nend\nend'));
for(const expression of ['${angle(4) +}','Math.sin(0)','${angle(4,)}','${angle(4)}garbage']){
  assert.throws(()=>A.validate(rotationClip(0,expression)));
}
for(const base of [1e12,-1e12]){
  const track=A.parse(rotationClip(base,base+360)).tracks[0];
  assert.deepEqual(plain(A.sample(track,2).euler),[0,0,base+180]);
}
for(const value of ['1e999','-1e999','NaN'])assert.throws(()=>A.parse(rotationClip(value,value)),/finite/);
for(const channel of ['position','scale'])assert.throws(()=>A.parse(rotationClip('1e12','1e12',channel)),/within ±1e9/);
for(const [expression,expected] of [['360*10',3600],['(360 * (2 + 3))',1800],
  ['${360 * (2 + 3)}',1800],['-360*2',-720],['((1e3 - 280) / 2)',360],
  ['360/2/2*4',360],['((.5 + .5) * 360)',360]]){
  const track=A.parse(rotationClip(0,expression)).tracks[0];
  assert.deepEqual(plain(track.channels.euler.at(-1)[1]),[0,0,expected]);
  assert.deepEqual(plain(A.sample(track,2).euler),[0,0,expected/2]);
}
for(const expression of ['1/0','1e308*10','360**2','0x168','Math.sin(0)',
  '__import__("os")','turns*360','(360','${360','360)','(360 +)','()',
  '('.repeat(34)+'360'+')'.repeat(34),'('+Array(257).fill('0').join('+')+')']){
  assert.throws(()=>A.parse(rotationClip(0,expression)),/Animation line 4:/);
}
for(const bad of [source.replace('loop 4','loop 0'),
  source.replace('key 4 euler','key 3 euler'),source.replace('1.6 1.6 1.6','0 1 1'),
  source.replace('key 2 position','key 0 position'),source+'\nend',source.replace('loop 4','loop 0x4'),
  source.replace('0 0 360','0 0 360000000')])assert.throws(()=>A.parse(bad));

// Independent periods stay compact and rotations accumulate across the seam.
const cycles=`animation loop 120
track rotor
cycle euler 2
cycle position 3
key 0 euler 0 0 0
key 2 euler 0 0 -720
key 0 position 0 0 0
key 1.5 position 12 0 0
key 3 position 0 0 0
end
end`;
const cyclic=A.parse(cycles).tracks[0];
assert.equal(Object.values(cyclic.channels).reduce((n,keys)=>n+keys.length,0),5);
for(const [t,angle,x] of [[0,0,0],[2,-720,8],[7.5,-2700,12],[120,-43200,0]]){
  assert.deepEqual(plain(A.sample(cyclic,t).euler),[0,0,angle]);
  assert.deepEqual(plain(A.sample(cyclic,t).position),[x,0,0]);
}
const cycleTimes=A.sampleTimes(cyclic,120);
for(const t of [0,1.5,3,118.5,120])assert(cycleTimes.includes(t));
assert.doesNotThrow(()=>A.validate(cycles.replace('cycle euler 2','cycle euler (period * 1)')));
for(const bad of [cycles.replace('cycle euler 2','cycle euler 0'),
  cycles.replace('cycle euler 2','cycle euler 7'),
  cycles.replace('cycle euler 2','cycle euler 121'),
  cycles.replace('cycle euler 2','cycle euler 2\ncycle euler 2'),
  cycles.replace('cycle euler 2','cycle scale 2'),
  cycles.replace('key 2 euler','key 120 euler'),
  cycles.replace('cycle euler 2','cycle euler 0.00000001'),
  cycles.replace('0 0 -720','0 0 360000')])assert.throws(()=>A.parse(bad));

const decimal=A.parse(`animation loop 1
track rotor
cycle euler 0.1
cycle scale 0.2
key 0 euler 0 0 0
key 0.1 euler 0 0 360
key 0 scale 1 1 1
key 0.1 scale 2 2 2
key 0.2 scale 1 1 1
end
end`).tracks[0];
for(const t of [0.1,0.3,0.6,1])assert(Math.abs(A.sample(decimal,t).euler[2]-t*3600)<1e-9);
for(const v of A.sample(decimal,0.5).scale)assert(Math.abs(v-2)<1e-9);
assert.deepEqual(plain(A.sample(decimal,1).scale),[1,1,1]);

const longCycles=A.parse(`animation loop 720
track second
cycle euler 1
key 0 euler 0 0 0
key 1 euler 0 0 -360
end
track first_assembly
cycle euler 2
key 0 euler 0 0 0
key 2 euler 0 0 360
end
end`);
assert.deepEqual(plain(longCycles.tracks.map(t=>A.sampleTimes(t,720).length)),[5761,2881]);
for(const [index,track] of longCycles.tracks.entries()){
  const values=A.sampleTimes(track,720).map(t=>A.sample(track,t).euler[2]);
  assert.equal(values.at(-1),[-259200,129600][index]);
  for(let i=1;i<values.length;i++)assert(Math.abs(values[i]-values[i-1])<=45.000001);
}
const coupled=A.parse(rotationClip(0,360).replace('0 0 360','360 360 0')).tracks[0];
assert(A.sampleTimes(coupled,4).length>=241);
assert.deepEqual(plain(A.sampleTimes(A.parse(rotationClip(0,0)).tracks[0],4)),[0,4]);

const forSource=`animation loop 4
track rotor
for i in range(5)
key i euler 0 0 ${'${i * 360}'}
end
end
end`;
assert.throws(()=>A.parse(forSource),error=>error.modelReference===true);
assert.doesNotThrow(()=>A.validate(forSource));
assert.doesNotThrow(()=>A.validate(forSource.replace('range(5)','range(count)')));
assert.doesNotThrow(()=>A.validate(forSource.replace('for i in range(5)','for j in range(1)\nfor i in range(5)')+'\nend'));
for(const bad of [forSource.replace('track rotor\n',''),forSource+'\nend',
  forSource.replace('for i in range(5)','for i in range(5)\ncycle euler 4'),
  forSource.replace('for i in range(5)','for i range(5)'),
  forSource.replace('range(5)','range(5 +)'),forSource.replace('key i','key (i +)')])assert.throws(()=>A.validate(bad));

// A tiny symbolic matrix harness records transform order. Applying the recorded
// operations to points gives independent numeric checks without a WebGL context.
class Vector {set(...v){this.v=v;return this;}}
class Quaternion extends Vector {}
function rotate(p,q){
  const [x,y,z,w]=q,[a,b,c]=p;
  const t=[2*(y*c-z*b),2*(z*a-x*c),2*(x*b-y*a)];
  return [a+w*t[0]+y*t[2]-z*t[1],b+w*t[1]+z*t[0]-x*t[2],c+w*t[2]+x*t[1]-y*t[0]];
}
class Matrix {
  constructor(){this.identity();}
  identity(){this.ops=[];return this;}
  compose(p,q,s){this.ops=[{p:[...p.v],q:[...q.v],s:[...s.v]}];return this;}
  multiply(m){this.ops.push(...m.ops.map(o=>({...o})));return this;}
  invert(){this.ops.reverse();this.ops=this.ops.map(o=>({...o,inverse:!o.inverse}));return this;}
  copy(m){this.ops=m.ops.map(o=>({...o}));return this;}
  point(p){
    for(const o of [...this.ops].reverse()){
      if(o.inverse){
        p=p.map((v,i)=>v-o.p[i]);p=rotate(p,[-o.q[0],-o.q[1],-o.q[2],o.q[3]]);p=p.map((v,i)=>v/o.s[i]);
      }else{p=rotate(p.map((v,i)=>v*o.s[i]),o.q).map((v,i)=>v+o.p[i]);}
    }
    return p;
  }
}
const THREE={Vector3:Vector,Quaternion,Matrix4:Matrix};
const group=(name,position=[0,0,0],euler=[0,0,0],scale=[1,1,1])=>({name,position,euler,scale});
const meshes=[{groupPath:[group('parent',[10,20,0],[0,0,90],[2,3,1]),group('child',[1,0,0])]}];
const objects=()=>({solid:{matrix:new Matrix()},normal:{matrix:new Matrix()},wire:{matrix:new Matrix()}});
const rendered=[objects()];
const nested=`animation loop 4
track parent
key 0 position 0 0 0
key 2 position 1 0 0
key 4 position 0 0 0
end
track parent/child
key 0 position 0 0 0
key 2 position 0 1 0
key 4 position 0 0 0
end
end`;
const player=new A.Player(THREE,()=>draws++);
player.configure(nested,meshes,rendered);
function close(actual,expected){actual.forEach((v,i)=>assert(Math.abs(v-expected[i])<1e-9,`${actual} != ${expected}`));}
// Original baked world point for child local origin: parent([1,0,0]) = [10,22,0].
close(rendered[0].solid.matrix.point([10,22,0]),[10,22,0]);
player.seek(2);
// Parent animation [1,0,0] and child animation [0,1,0] both precede parent's static rotation/scale.
close(rendered[0].solid.matrix.point([10,22,0]),[7,24,0]);
const groupWorld=new Matrix();
player.groupMatrix(meshes[0].groupPath.slice(0,1),groupWorld);
close(groupWorld.point([0,0,0]),[10,22,0]);
const groupLocal=new Matrix();
player.groupMatrix(meshes[0].groupPath,groupWorld,groupLocal);
close(groupWorld.point([0,0,0]),[7,24,0]);
close(groupLocal.point([0,0,0]),[1,1,0]);
close(groupWorld.point([1,0,0]),[7,26,0]);
close(groupWorld.point([0,1,0]),[4,24,0]);
for(const mode of ['normal','wire'])close(rendered[0][mode].matrix.point([10,22,0]),[7,24,0]);
player.play();assert(player.running);assert.equal(frames.size,1);
function frame(now){const [id,fn]=frames.entries().next().value;frames.delete(id);fn(now);}
frame(100);frame(1100);assert.equal(player.time,3);
frame(3100);assert.equal(player.time,1,'wraps at the common loop duration');
player.pause();assert.equal(frames.size,0);
assert.throws(()=>player.configure(nested.replace('track parent\n','track missing\n'),meshes,rendered));
assert.equal(player.time,1,'invalid edits preserve the current clip');
player.reset();assert.equal(player.time,0);
close(rendered[0].solid.matrix.point([10,22,0]),[10,22,0]);
player.configure('',meshes,rendered);assert.equal(player.animation,null);
close(player.groupMatrix(meshes[0].groupPath,groupWorld).point([0,0,0]),[10,22,0]);
player.play();assert.equal(frames.size,0);
assert.equal(requests,0);assert(draws>3);
assert.throws(()=>A.bind(clip,meshes));
assert.equal(A.bind(A.parse(nested.replace('track parent\n','track /parent\n')),meshes).size,2);
const repeated=[{groupPath:[group('a'),group('child')]},{groupPath:[group('b'),group('child')]}];
assert.throws(()=>A.bind(A.parse(nested.replace('track parent\n','track child\n')),repeated));
const quaternionRendered=[objects()];
const quaternionMeshes=plain(meshes);
quaternionMeshes[0].groupPath[0].quaternion=[0,0,Math.SQRT1_2,Math.SQRT1_2];
// Deliberately omit the Euler fallback to verify quaternion is used directly.
delete quaternionMeshes[0].groupPath[0].euler;
const quaternionPlayer=new A.Player(THREE,()=>draws++);
quaternionPlayer.configure(nested,quaternionMeshes,quaternionRendered);
quaternionPlayer.seek(2);
close(quaternionRendered[0].solid.matrix.point([10,22,0]),[7,24,0]);
close(quaternionPlayer.groupMatrix(quaternionMeshes[0].groupPath,groupWorld).point([0,0,0]),[7,24,0]);
console.log('animation: parser, nested nonuniform transforms, playback, loop, pause, seek, reset, and zero geometry requests passed');
