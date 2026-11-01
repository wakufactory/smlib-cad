/* TRS loop parser and cached-mesh playback. This module never requests geometry. */
(() => {
  'use strict';
  const defaults = {position:[0,0,0], euler:[0,0,0], scale:[1,1,1]};
  function angleExpression(source,syntaxOnly=false){
    if(source.startsWith('${') && source.endsWith('}'))source=source.slice(2,-1);
    const tokens=source.match(/(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?|[A-Za-z_][A-Za-z_0-9]*|\S/g)||[];
    if(!tokens.length || tokens.length>512)throw Error('angle expression must contain 1 to 512 tokens');
    let index=0;
    function finite(value){
      if(syntaxOnly)return 1;
      if(!Number.isFinite(value))throw Error('angle expression result must be finite');
      return value;
    }
    function expression(depth=0,product=false){
      if(depth>32)throw Error('angle expression is too deeply nested');
      let value=product?atom(depth):expression(depth,true);
      const operators=product?['*','/']:['+','-'];
      while(index<tokens.length && operators.includes(tokens[index])){
        const op=tokens[index++],right=product?atom(depth):expression(depth,true);
        if(!syntaxOnly && op==='/' && right===0)throw Error('angle expression: division by zero');
        value=finite(op==='+'?value+right:op==='-'?value-right:op==='*'?value*right:value/right);
      }
      return value;
    }
    function atom(depth){
      if(depth>32)throw Error('angle expression is too deeply nested');
      const token=tokens[index++]||'';
      if(token==='+' || token==='-'){const value=atom(depth+1);return token==='-'?-value:value;}
      if(token==='('){
        const value=expression(depth+1);
        if(tokens[index++]!==')')throw Error('angle expression: expected closing parenthesis');
        return value;
      }
      if(/^[A-Za-z_][A-Za-z_0-9]*$/.test(token)){
        if(['NaN','Infinity'].includes(token))throw Error('number must be finite');
        if(!syntaxOnly){const error=Error('expression requires model definitions');error.modelReference=true;throw error;}
        if(tokens[index]==='('){
          index++;
          if(tokens[index]!==')'){
            expression(depth+1);
            while(tokens[index]===','){index++;expression(depth+1);}
          }
          if(tokens[index++]!==')')throw Error('angle expression: expected closing parenthesis');
        }
        return 1;
      }
      if(!/^(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/.test(token))throw Error('angle expression: expected a finite number or parenthesized expression');
      return finite(Number(token));
    }
    const value=expression();
    if(index!==tokens.length)throw Error('angle expression: unexpected token');
    return value;
  }
  function animationWords(line,n){
    const simple=line.trim().split(/\s+/).filter(Boolean);
    if(simple[0]!=='key' && simple[0]!=='animation' && simple[0]!=='cycle')return simple;
    const words=[],stack=[];
    let word='';
    for(const char of line){
      if(/\s/.test(char) && !stack.length){
        if(word){words.push(word);word='';}
        continue;
      }
      word+=char;
      if(char==='(' || char==='{')stack.push(char);
      else if(char===')' || char==='}'){
        if(stack.pop()!==({')':'(','}':'{'})[char])throw Error(`Animation line ${n}: unmatched expression delimiter`);
      }
    }
    if(stack.length)throw Error(`Animation line ${n}: unmatched expression delimiter`);
    if(word)words.push(word);
    return words;
  }
  function quaternion([x,y,z]) {
    [x,y,z]=[x,y,z].map(v=>v*Math.PI/360);
    const sx=Math.sin(x),sy=Math.sin(y),sz=Math.sin(z),cx=Math.cos(x),cy=Math.cos(y),cz=Math.cos(z);
    return [sx*cy*cz-cx*sy*sz,cx*sy*cz+sx*cy*sz,cx*cy*sz-sx*sy*cz,cx*cy*cz+sx*sy*sz];
  }
  function sampleTimes(track, duration) {
    const times=new Set([0,duration]);
    for(const [channel,keys] of Object.entries(track.channels)){
      const period=track.cycles?.[channel]??duration,count=Math.round(duration/period),steps=[];
      for(let i=1;i<keys.length;i++){
        const [a,av]=keys[i-1],[b,bv]=keys[i];
        let subdivisions=1;
        if(channel==='euler'){
          const changes=av.map((v,j)=>Math.abs(bv[j]-v));
          subdivisions=Math.max(1,Math.ceil(changes.reduce((s,v)=>s+v,0)/45));
          // Only coupled Euler rotations need the additional temporal samples.
          if(changes.filter(delta=>delta!==0).length>1)subdivisions=Math.max(subdivisions,Math.ceil((b-a)*60));
        }
        steps.push(subdivisions);
      }
      if(count*steps.reduce((s,v)=>s+v,0)+1>120000)throw Error('Animation exceeds 120000 generated samples');
      for(let cycle=0;cycle<count;cycle++){
        for(let i=1;i<keys.length;i++){
          const a=keys[i-1][0],b=keys[i][0],subdivisions=steps[i-1];
          for(let j=0;j<subdivisions;j++)times.add(Math.min(duration,cycle*period+a+(b-a)*j/subdivisions));
        }
        if(times.size>120000)throw Error('Animation exceeds 120000 generated samples');
      }
    }
    return [...times].sort((a,b)=>a-b);
  }
  function parse(source='',syntaxOnly=false) {
    if(typeof source!=='string' || source.length>100000)throw Error('animationSource must be text (at most 100000 characters)');
    const lines=source.split(/\r?\n/).map((line,i)=>[i+1,animationWords(line.split('#')[0],i+1)]).filter(([,w])=>w.length);
    if(!lines.length)return null;
    function fail(n,text){throw Error(`Animation line ${n}: ${text}`);}
    function number(word,n,angle=false){
      if(angle || syntaxOnly || !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(word)){
        try{
          const value=angleExpression(word,syntaxOnly);
          if(!syntaxOnly && !angle && Math.abs(value)>1e9)fail(n,'number must be finite and within ±1e9');
          return value;
        }catch(error){
          if(error.modelReference){error.message=`Animation line ${n}: ${error.message}`;throw error;}
          fail(n,error.message);
        }
      }
      // Match Python float's decimal syntax; reject JavaScript-only hex/binary numbers.
      const value=Number(word);
      if(!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(word) || !Number.isFinite(value))fail(n,'number must be finite');
      if(!angle && Math.abs(value)>1e9)fail(n,'number must be finite and within ±1e9');
      return value;
    }
    const [n,w]=lines[0];
    if(w.length!==3 || w[0]!=='animation' || w[1]!=='loop')fail(n,'expected animation loop <seconds>');
    const duration=number(w[2],n);
    if(!syntaxOnly && (duration<=0 || duration>1000))fail(n,'duration must be greater than 0 and at most 1000 seconds');
    const tracks=[];
    let track=null,closed=false,keyCount=0;
    for(const [n,w] of lines.slice(1)){
      if(closed)fail(n,'only one animation block is allowed');
      if(w.length===1 && w[0]==='end'){
        if(!track){closed=true;continue;}
        if(!Object.keys(track.channels).length)fail(n,'track needs keys');
        for(const channel of Object.keys(track.cycles||{})){
          if(!Object.hasOwn(track.channels,channel))fail(n,`${channel} cycle needs keys`);
        }
        for(const [channel,keys] of Object.entries(track.channels)){
          if(syntaxOnly)continue;
          const period=track.cycles?.[channel]??duration;
          if(keys[0][0]!==0 || keys.at(-1)[0]!==period)fail(n,`${channel} needs keys at 0 and ${period} seconds`);
          const first=keys[0][1],last=keys.at(-1)[1];
          const equal=channel==='euler'
            ? Math.abs(quaternion(first).reduce((s,v,i)=>s+v*quaternion(last)[i],0))>=1-1e-9
            : first.every((v,i)=>Math.abs(v-last[i])<=1e-9);
          if(channel==='euler' && track.cycles?.euler && !first.every((v,i)=>Math.abs((last[i]-v)/360-Math.round((last[i]-v)/360))<=1e-9))fail(n,'euler cycle endpoints must differ by whole turns on each axis');
          if(!equal)fail(n,`${channel} loop endpoints must have the same pose`);
        }
        tracks.push(track);track=null;
      }else if(w.length===2 && w[0]==='track' && !track){
        if(tracks.length>=256 || tracks.some(t=>t.target===w[1]))fail(n,'duplicate target or more than 256 tracks');
        track={target:w[1],channels:{}};
      }else if(w.length===3 && w[0]==='cycle' && track && Object.hasOwn(defaults,w[1])){
        const channel=w[1],cycles=track.cycles ||= {};
        if(Object.hasOwn(cycles,channel))fail(n,'duplicate channel cycle');
        const period=number(w[2],n),count=duration/period;
        if(!syntaxOnly && !(period>0 && period<=duration))fail(n,'cycle period must be greater than 0 and at most the loop duration');
        if(!syntaxOnly && (!Number.isFinite(count) || count>120000 || Math.abs(count-Math.round(count))>1e-9))fail(n,'loop duration must be a whole number of cycles (at most 120000)');
        cycles[channel]=period;
      }else if(w.length===6 && w[0]==='key' && track && Object.hasOwn(defaults,w[2])){
        const time=number(w[1],n),value=w.slice(3).map(v=>number(v,n,w[2]==='euler'));
        const keys=track.channels[w[2]] ||= [];
        if(!syntaxOnly && (time<0 || time>duration || (keys.length && time<=keys.at(-1)[0])))fail(n,'channel key times must increase within the loop duration');
        if(!syntaxOnly && w[2]==='scale' && Math.min(...value)<=0)fail(n,'scale must be positive');
        keys.push([time,value]);
        if(++keyCount>4096)fail(n,'at most 4096 keys are allowed');
      }else fail(n,'expected track <group>, cycle position|euler|scale <seconds>, key <seconds> position|euler|scale x y z, or end');
    }
    if(!closed || track || !tracks.length)fail(lines.at(-1)[0],'close all blocks with end; at least one track is required');
    if(!syntaxOnly && tracks.reduce((s,t)=>s+sampleTimes(t,duration).length,0)>120000)throw Error('Animation exceeds 120000 generated samples');
    return {duration,tracks};
  }
  function validate(source){
    try{parse(source);}catch(error){if(!error.modelReference)throw error;parse(source,true);}
  }
  function bind(animation, meshes){
    const paths=new Map(),bound=new Map();
    for(const mesh of meshes){
      const path=[];
      for(const group of mesh.groupPath||[]){path.push(group.name);paths.set(path.join('/'),[...path]);}
    }
    for(const track of animation?.tracks||[]){
      const matches=[...paths].filter(([path,names])=>track.target.includes('/')?path===track.target.replace(/^\//,''):names.at(-1)===track.target);
      if(matches.length!==1)throw Error(`Animation target ${track.target}: group missing, invisible, consumed by Boolean, or ambiguous; use a full group path`);
      const path=matches[0][0];
      if(bound.has(path))throw Error(`Animation target ${track.target}: duplicate group track`);
      bound.set(path,track);
    }
    return bound;
  }
  function sample(track,time){
    const pose=Object.fromEntries(Object.entries(defaults).map(([k,v])=>[k,[...v]]));
    for(const [channel,keys] of Object.entries(track.channels)){
      const period=track.cycles?.[channel],turns=period?Math.floor(time/period):0;
      const local=period?Math.max(0,Math.min(period,time-turns*period)):time;
      let value=[...keys.at(-1)[1]];
      if(local<=keys[0][0])value=[...keys[0][1]];
      else for(let i=1;i<keys.length;i++){
        const [a,av]=keys[i-1],[b,bv]=keys[i];
        if(local<=b){const u=(local-a)/(b-a);value=av.map((v,j)=>v+(bv[j]-v)*u);break;}
      }
      if(channel==='euler' && period)value=value.map((v,i)=>v+turns*(keys.at(-1)[1][i]-keys[0][1][i]));
      pose[channel]=value;
    }
    return pose;
  }
  class Player {
    constructor(THREE,draw,status){
      this.THREE=THREE;this.draw=draw;this.status=status;this.records=[];this.time=0;this.running=false;
      this.vector=new THREE.Vector3();this.quat=new THREE.Quaternion();this.scale=new THREE.Vector3();
      this.frameMatrix=new THREE.Matrix4();this.world=new THREE.Matrix4();
    }
    matrix(pose,target){
      this.vector.set(...pose.position);this.quat.set(...quaternion(pose.euler));this.scale.set(...pose.scale);
      return target.compose(this.vector,this.quat,this.scale);
    }
    configure(source,meshes,rendered){
      const animation=parse(source),bound=bind(animation,meshes); // Validate before replacing a running clip.
      const T=this.THREE;
      const records=meshes.map((mesh,i)=>{
        let path='';const base=new T.Matrix4();
        const frames=(mesh.groupPath||[]).map(group=>{
          path+=(path?'/':'')+group.name;
          const matrix=this.matrix(group,new T.Matrix4());base.multiply(matrix);
          return {matrix,track:bound.get(path)};
        });
        return {frames,inverse:base.invert(),objects:[rendered[i].solid,rendered[i].normal,rendered[i].wire]};
      });
      this.pause();this.animation=animation;this.records=records;this.time=0;this.seek(0);
    }
    seek(time){
      this.time=this.animation?Math.max(0,Math.min(this.animation.duration,time)):0;
      for(const record of this.records){
        this.world.identity();
        for(const frame of record.frames){
          this.world.multiply(frame.matrix);
          if(frame.track)this.world.multiply(this.matrix(sample(frame.track,this.time),this.frameMatrix));
        }
        this.world.multiply(record.inverse);
        for(const object of record.objects){object.matrixAutoUpdate=false;object.matrix.copy(this.world);object.matrixWorldNeedsUpdate=true;}
      }
      this.draw();this.status?.(this.time,this.animation?.duration||0,this.running);
    }
    play(){
      if(!this.animation || this.running)return;
      this.running=true;this.previous=null;
      const tick=now=>{
        if(!this.running)return;
        if(this.previous!==null)this.time=(this.time+(now-this.previous)/1000)%this.animation.duration;
        this.previous=now;this.seek(this.time);this.handle=requestAnimationFrame(tick);
      };
      this.handle=requestAnimationFrame(tick);
      this.status?.(this.time,this.animation.duration,true);
    }
    pause(){
      this.running=false;
      if(this.handle!==undefined)cancelAnimationFrame(this.handle);
      this.handle=undefined;this.status?.(this.time,this.animation?.duration||0,false);
    }
    reset(){this.pause();this.seek(0);}
    clear(){this.pause();this.records=[];this.animation=null;this.time=0;this.status?.(0,0,false);}
  }
  globalThis.ModelAnimation={parse,validate,bind,sample,sampleTimes,quaternion,Player};
})();
