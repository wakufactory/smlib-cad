/* TRS loop parser and cached-mesh playback. This module never requests geometry. */
(() => {
  'use strict';
  const defaults = {position:[0,0,0], euler:[0,0,0], scale:[1,1,1]};
  const decimal = /^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/;
  function angleExpression(source,syntaxOnly=false,rangeHeader=false){
    if(source.startsWith('${') && source.endsWith('}'))source=source.slice(2,-1);
    if(/\bbase\./.test(source)){
      if(!syntaxOnly){const error=Error('base references require model resolution');error.modelReference=true;throw error;}
      source=source.replace(/\bbase\.(position|euler|scale)\.[xyz]\b/g,'1');
    }
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
          let argumentsCount=0;
          if(tokens[index]!==')'){
            expression(depth+1);
            argumentsCount++;
            while(tokens[index]===','){index++;expression(depth+1);argumentsCount++;}
          }
          if(tokens[index++]!==')')throw Error('angle expression: expected closing parenthesis');
          if(rangeHeader && depth===0 && token==='range' && (argumentsCount<1 || argumentsCount>3)){
            throw Error('range arguments must be one to three integers');
          }
        }
        return 1;
      }
      if(!/^(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/.test(token))throw Error('angle expression: expected a finite number or parenthesized expression');
      const value=Number(token);
      if(!Number.isFinite(value))throw Error('angle expression result must be finite');
      return value;
    }
    const value=expression();
    if(index!==tokens.length)throw Error('angle expression: unexpected token');
    return value;
  }
  function animationWords(line,n){
    const simple=line.trim().split(/\s+/).filter(Boolean);
    if(!['key','animation','track','cycle'].includes(simple[0]?.toLowerCase()))return simple;
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
  function logicalLines(source,strict=true){
    const lines=[];
    let fragments=[],start=1;
    const physical=source.split(/\r\n|\r|\n/);
    if(physical.at(-1)==='')physical.pop();
    for(const [i,raw] of physical.entries()){
      if(!fragments.length)start=i+1;
      const code=raw.split('#')[0].trimEnd();
      if(!raw.includes('#') && code.endsWith('\\')){
        fragments.push(code.slice(0,-1).trimEnd());
        continue;
      }
      const text=[...fragments,code].join(' ').trim();
      if(text)lines.push([start,text]);
      fragments=[];
    }
    if(fragments.length){
      if(strict)throw Error(`Animation line ${start}: trailing backslash requires a following line`);
      lines.push([start,fragments.join(' ').trim()]);
    }
    return lines;
  }
  function globalDefinitions(source){
    // Changing a shared definition invalidates a cached text model.
    return logicalLines(source,false).map(([,text])=>text.match(/^let\s+(.*)$/i)?.[1]).filter(text=>text!==undefined);
  }
  function normalizeWords(words){
    words[0]=words[0].toLowerCase();
    if(words[0]==='key' && words[2])words[2]=words[2].toLowerCase();
    if(words[0]==='cycle' && words[1])words[1]=words[1].toLowerCase();
    if(words[0]==='animation'){
      const loopIndex=words.length===3?1:2;
      if(words[loopIndex])words[loopIndex]=words[loopIndex].toLowerCase();
    }
    return words;
  }
  function validateExpression(word,n,allowBase=false,rangeHeader=false){
    if(!allowBase && /\bbase\./.test(word))throw Error(`Animation line ${n}: base is only available inside a track`);
    try{angleExpression(word,true,rangeHeader);}catch(error){throw Error(`Animation line ${n}: ${error.message}`);}
  }
  function checkName(word,n){
    const remainder=word.replace(/\$\{([^{}]+)\}/g,(_,expression)=>{
      validateExpression(expression,n);
      return '0';
    });
    if(remainder.includes('${'))throw Error(`Animation line ${n}: unclosed or nested \${expression}`);
    return remainder;
  }
  function flattenControl(lines,syntaxOnly){
    // Only the server evaluates authored definitions and expands loops. For
    // editor validation, retain one symbolic copy of each loop body.
    const stack=[],loopNames=new Set(),definitions=new Set(),filtered=[];
    for(const [n,w] of lines){
      const op=w[0],fail=message=>{throw Error(`Animation line ${n}: ${message}`);};
      if(op==='end'){
        if(w.length!==1 || !stack.length)fail('end takes no arguments and requires an open block');
        const block=stack.pop();
        if(block.kind==='for')loopNames.delete(block.name);
        else filtered.push([n,w]);
        continue;
      }
      const context=stack.findLast(block=>block.kind!=='for')?.kind || 'root';
      if(op==='let' || op==='for'){
        if(!syntaxOnly){const error=Error('animation definitions and loops require server resolution');error.modelReference=true;throw error;}
        if(op==='let'){
          if(stack.length)fail('let is only allowed at the top level');
          const match=w.join(' ').match(/^let\s+([A-Za-z_][A-Za-z_0-9]*)\s*=\s*(.+)$/);
          if(!match)fail('let: expected name = expression');
          if(definitions.has(match[1]))fail(`duplicate variable: ${match[1]}`);
          definitions.add(match[1]);
          validateExpression(match[2],n);
        }else{
          const match=w.join(' ').match(/^for\s+([A-Za-z_][A-Za-z_0-9]*)\s+in\s+range\((.*)\)$/i);
          if(!match)fail('expected for <name> in range(...)');
          if(loopNames.has(match[1]))fail(`loop variable already defined: ${match[1]}`);
          validateExpression(`range(${match[2]})`,n,context==='track',true);
          loopNames.add(match[1]);
          if(loopNames.size>32)fail('loop nesting limit exceeded (32)');
          stack.push({kind:'for',name:match[1]});
        }
        continue;
      }
      if(op==='animation' && context==='root' || op==='track' && context==='animation'){
        if((op==='animation' && w.length===4 || op==='track' && w.length===2) && w[1].includes('${')){
          if(!syntaxOnly){const error=Error('animation names require server resolution');error.modelReference=true;throw error;}
          checkName(w[1],n);
        }
        stack.push({kind:op});
      }else if(!(context==='track' && (op==='key' || op==='cycle' && stack.at(-1)?.kind!=='for'))){
        fail(`unexpected ${op} in ${context}`);
      }
      filtered.push([n,w,loopNames.size>0]);
    }
    if(stack.length)throw Error('close all blocks with end');
    return filtered;
  }
  function quaternion([x,y,z]) {
    [x,y,z]=[x,y,z].map(v=>v*Math.PI/360);
    const sx=Math.sin(x),sy=Math.sin(y),sz=Math.sin(z),cx=Math.cos(x),cy=Math.cos(y),cz=Math.cos(z);
    return [sx*cy*cz-cx*sy*sz,cx*sy*cz+sx*cy*sz,cx*cy*sz-sx*sy*cz,cx*cy*cz+sx*sy*sz];
  }
  function channelPeriod(track,channel){
    return track.cycles?.[channel]??track.implicit_cycles?.[channel];
  }
  function cycleRatio(time,period){
    const ratio=time/period,nearest=Math.round(ratio);
    return Math.abs(ratio-nearest)<=4*Number.EPSILON*ratio?nearest:ratio;
  }
  const seamTime=new DataView(new ArrayBuffer(4));
  function beforeSeam(time){
    seamTime.setFloat32(0,time);
    seamTime.setUint32(0,Math.max(0,seamTime.getUint32(0)-1));
    return seamTime.getFloat32(0);
  }
  function sampleTimes(track, duration) {
    const times=new Set([0,duration]);
    for(const [channel,keys] of Object.entries(track.channels)){
      const repeat=channelPeriod(track,channel),period=repeat??duration;
      const ratio=cycleRatio(duration,period),count=Math.ceil(ratio),steps=[];
      const jumps=repeat!==undefined && !(channel==='euler' && track.cycles?.[channel])
        && keys[0][1].some((v,i)=>v!==keys.at(-1)[1][i]);
      if(!Number.isFinite(ratio) || ratio>120000)throw Error('Animation exceeds 120000 generated samples');
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
      if(count*steps.reduce((s,v)=>s+v,0)+(jumps?Math.floor(ratio):0)+1>120000)throw Error('Animation exceeds 120000 generated samples');
      for(let cycle=0;cycle<count;cycle++){
        for(let i=1;i<keys.length;i++){
          const a=keys[i-1][0],b=keys[i][0],subdivisions=steps[i-1];
          for(let j=0;j<subdivisions;j++)times.add(Math.min(duration,cycle*period+a+(b-a)*j/subdivisions));
        }
        if(jumps && cycle+1<=ratio){
          const seam=cycle+1===ratio?duration:(cycle+1)*period;
          times.add(beforeSeam(seam));times.add(seam);
        }
        if(times.size>120000)throw Error('Animation exceeds 120000 generated samples');
      }
    }
    const ordered=[...times].sort((a,b)=>a-b);
    if(!track.cycles && !track.implicit_cycles)return ordered;
    const merged=[];
    for(const time of ordered){
      if(merged.length && time-merged.at(-1)<=4*Number.EPSILON*time)merged[merged.length-1]=time;
      else merged.push(time);
    }
    return merged;
  }
  function parseClip(lines,syntaxOnly,deferExpressions) {
    function fail(n,text){throw Error(`Animation line ${n}: ${text}`);}
    function number(word,n,angle=false){
      if(!decimal.test(word)){
        if(deferExpressions && !syntaxOnly){
          const error=Error(`Animation line ${n}: expression requires server resolution`);
          error.modelReference=true;
          throw error;
        }
        let value;
        try{
          value=angleExpression(word,syntaxOnly);
        }catch(error){
          if(error.modelReference){error.message=`Animation line ${n}: ${error.message}`;throw error;}
          fail(n,error.message);
        }
        if(!syntaxOnly && !angle && Math.abs(value)>1e9)fail(n,'number must be finite and within ±1e9');
        return value;
      }
      const value=Number(word);
      if(!Number.isFinite(value))fail(n,'number must be finite');
      if(syntaxOnly)return 1;
      if(!angle && Math.abs(value)>1e9)fail(n,'number must be finite and within ±1e9');
      return value;
    }
    const [n,w]=lines[0];
    if(w.length===3 && w[0]==='animation' && w[1]==='loop')w.splice(1,0,'main');
    if(w.length!==4 || w[0]!=='animation' || w[2]!=='loop' || !/^[A-Za-z_][A-Za-z_0-9-]*$/.test(syntaxOnly?checkName(w[1],n):w[1]))fail(n,'expected animation [name] loop <seconds>');
    if(/\bbase\./.test(w[3]))fail(n,'base is only available inside a track');
    const duration=number(w[3],n);
    if(!syntaxOnly && (duration<=0 || duration>1000))fail(n,'duration must be greater than 0 and at most 1000 seconds');
    const tracks=[],targets=new Set();
    let track=null,closed=false,keyCount=0;
    for(const [n,w,looped] of lines.slice(1)){
      if(closed)fail(n,'only one animation block is allowed');
      if(w.length===1 && w[0]==='end'){
        if(!track){closed=true;continue;}
        if(!Object.keys(track.channels).length)fail(n,'track needs keys');
        for(const channel of Object.keys(track.cycles||{})){
          if(!Object.hasOwn(track.channels,channel))fail(n,`${channel} cycle needs keys`);
        }
        for(const [channel,keys] of Object.entries(track.channels)){
          if(syntaxOnly)continue;
          const end=keys.at(-1)[0],period=track.cycles?.[channel];
          if(keys[0][0]!==0 || end<=0)fail(n,`${channel} needs keys at 0 and a positive end time`);
          if(period!==undefined && end!==period)fail(n,`${channel} needs keys at 0 and ${period} seconds`);
          if(period===undefined && end<duration)(track.implicit_cycles ||= {})[channel]=end;
        }
        tracks.push(track);track=null;
      }else if(w.length===2 && w[0]==='track' && !track){
        if(!syntaxOnly || (!looped && !w[1].includes('${'))){
          if(targets.size>=256 || targets.has(w[1]))fail(n,'duplicate target or more than 256 tracks');
          targets.add(w[1]);
        }
        track={target:w[1],channels:{}};
      }else if(w.length===3 && w[0]==='cycle' && track && Object.hasOwn(defaults,w[1])){
        const channel=w[1],cycles=track.cycles ||= {};
        if(Object.hasOwn(cycles,channel))fail(n,'duplicate channel cycle');
        const period=number(w[2],n);
        if(!syntaxOnly && !(period>0 && period<=duration))fail(n,'cycle period must be greater than 0 and at most the loop duration');
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
    return {name:w[1],duration,tracks};
  }
  function parse(source='',syntaxOnly=false,{resolved=false,deferExpressions=false}={}){
    // A server response has already passed source, key, and sample limits. Its
    // expanded text can be longer than the source typed into the editor.
    if(typeof source!=='string' || (!resolved && source.length>100000))throw Error('animationSource must be text (at most 100000 characters)');
    const clips=[],names=new Set(),lines=flattenControl(logicalLines(source).map(([n,line])=>[n,normalizeWords(animationWords(line,n))]),syntaxOnly);
    let start=0,depth=0;
    for(let i=0;i<lines.length;i++){
      const [,words]=lines[i];
      if(['animation','track','for'].includes(words[0]))depth++;
      else if(words.length===1 && words[0]==='end')depth--;
      if(depth<=0){
        const clip=parseClip(lines.slice(start,i+1),syntaxOnly,deferExpressions);
        if(syntaxOnly && lines[start][2])clip.looped=true;
        if(!syntaxOnly || (!lines[start][2] && !clip.name.includes('${'))){
          if(names.size>=64 || names.has(clip.name))throw Error(`Animation line ${lines[start][0]}: duplicate clip name or more than 64 clips`);
          names.add(clip.name);
        }
        clips.push(clip);
        start=i+1;
      }
    }
    if(start<lines.length)parseClip(lines.slice(start),syntaxOnly,deferExpressions);
    if(!syntaxOnly){
      let samples=0;
      for(const clip of clips)for(const track of clip.tracks){
        samples+=sampleTimes(track,clip.duration).length;
        if(samples>120000)throw Error('Animation exceeds 120000 generated samples');
      }
    }
    return clips.length?{clips}:null;
  }
  function validate(source){
    try{parse(source,false,{deferExpressions:true});}catch(error){if(!error.modelReference)throw error;parse(source,true);}
  }
  function bind(animation, meshes){
    const paths=new Map(),bound=new Map();
    for(const mesh of meshes){
      const path=[];
      for(const group of mesh.groupPath||[]){path.push(group.name);paths.set(path.join('/'),{names:[...path],group});}
    }
    for(const track of animation?.tracks||[]){
      const matches=[...paths].filter(([path,{names}])=>track.target.includes('/')?path===track.target.replace(/^\//,''):names.at(-1)===track.target);
      if(matches.length!==1)throw Error(`Animation target ${track.target}: group missing, invisible, consumed by Boolean, or ambiguous; use a full group path`);
      const path=matches[0][0];
      if(bound.has(path))throw Error(`Animation target ${track.target}: duplicate group track`);
      bound.set(path,{...track,base:matches[0][1].group});
    }
    return bound;
  }
  function sample(track,time){
    const pose={...defaults,...track.base};
    for(const [channel,keys] of Object.entries(track.channels)){
      const period=channelPeriod(track,channel),ratio=period?cycleRatio(time,period):0;
      const turns=Math.floor(ratio),local=period?(ratio===turns?0:time-turns*period):time;
      let value=[...keys.at(-1)[1]];
      if(local<=keys[0][0])value=[...keys[0][1]];
      else for(let i=1;i<keys.length;i++){
        const [a,av]=keys[i-1],[b,bv]=keys[i];
        if(local<=b){const u=(local-a)/(b-a);value=av.map((v,j)=>v+(bv[j]-v)*u);break;}
      }
      if(channel==='euler' && track.cycles?.[channel])value=value.map((v,i)=>v+turns*(keys.at(-1)[1][i]-keys[0][1][i]));
      if(channel==='euler')delete pose.quaternion;
      pose[channel]=value;
    }
    return pose;
  }
  class Player {
    constructor(THREE,draw,status){
      this.THREE=THREE;this.draw=draw;this.status=status;this.records=[];this.time=0;this.running=false;
      this.vector=new THREE.Vector3();this.quat=new THREE.Quaternion();this.scale=new THREE.Vector3();
      this.frameMatrix=new THREE.Matrix4();this.groupFrameMatrix=new THREE.Matrix4();this.world=new THREE.Matrix4();
      this.tracks=new Map();this.poses=new Map();this.clipTimes=new Map();
    }
    matrix(pose,target){
      this.vector.set(...pose.position);this.quat.set(...(pose.quaternion||quaternion(pose.euler)));this.scale.set(...pose.scale);
      return target.compose(this.vector,this.quat,this.scale);
    }
    appendFrame(target,matrix,path){
      const pose=this.poses.get(path);
      target.multiply(pose?this.matrix(pose,this.frameMatrix):matrix);
    }
    groupMatrix(groups,target,local=this.groupFrameMatrix,{animated=true}={}){
      target.identity();
      local.identity();
      let path='';
      for(const group of groups){
        path+=(path?'/':'')+group.name;
        this.matrix(group,local);
        const pose=animated && this.poses.get(path);
        if(pose)this.matrix(pose,local);
        target.multiply(local);
      }
      return target;
    }
    configure(source,meshes,rendered,name=this.animation?.name,{resolved=false}={}){
      const collection=parse(source,false,{resolved}),clips=collection?.clips||[];
      const bindings=clips.map(clip=>bind(clip,meshes));
      const animation=clips.find(clip=>clip.name===name)||clips[0]||null;
      const bound=bindings[clips.indexOf(animation)]||new Map(); // Validate all clips before replacing playback.
      const preserve=!!collection && meshes===this.meshes && rendered===this.rendered;
      const poses=preserve?new Map(this.poses):new Map();
      const clipTimes=preserve?new Map(clips.map(clip=>[clip.name,Math.min(clip.duration,this.clipTimes.get(clip.name)||0)])):new Map();
      const T=this.THREE;
      const records=meshes.map((mesh,i)=>{
        let path='';const base=new T.Matrix4();
        const frames=(mesh.groupPath||[]).map(group=>{
          path+=(path?'/':'')+group.name;
          const matrix=this.matrix(group,new T.Matrix4());base.multiply(matrix);
          if(!poses.has(path))poses.set(path,{...defaults,...group});
          return {matrix,path};
        });
        return {frames,inverse:base.invert(),objects:[rendered[i].solid,rendered[i].normal,rendered[i].wire]};
      });
      this.pause();this.collection=collection;this.meshes=meshes;this.rendered=rendered;this.source=source;this.resolved=resolved;this.animation=animation;this.records=records;this.tracks=bound;this.poses=poses;this.clipTimes=clipTimes;this.seek(animation?clipTimes.get(animation.name)||0:0);
    }
    select(name){
      if(!this.collection?.clips.some(clip=>clip.name===name))throw Error(`Unknown animation clip: ${name}`);
      this.configure(this.source,this.meshes,this.rendered,name,{resolved:this.resolved});
    }
    seek(time){
      this.time=this.animation?Math.max(0,Math.min(this.animation.duration,time)):0;
      if(this.animation)this.clipTimes.set(this.animation.name,this.time);
      // Only active channels change; all other groups/channels keep their last pose.
      for(const [path,track] of this.tracks){
        const pose={...this.poses.get(path)},sampled=sample(track,this.time);
        for(const channel of Object.keys(track.channels)){
          if(channel==='euler')delete pose.quaternion;
          pose[channel]=sampled[channel];
        }
        this.poses.set(path,pose);
      }
      for(const record of this.records){
        this.world.identity();
        for(const frame of record.frames)this.appendFrame(this.world,frame.matrix,frame.path);
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
    clear(){this.pause();this.records=[];this.tracks.clear();this.poses.clear();this.clipTimes.clear();this.meshes=null;this.rendered=null;this.animation=null;this.collection=null;this.time=0;this.status?.(0,0,false);}
  }
  globalThis.ModelAnimation={globalDefinitions,parse,validate,bind,sample,sampleTimes,quaternion,Player};
})();
