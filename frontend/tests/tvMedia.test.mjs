import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { readTVPlayback, TVMediaClock, progressIntent, reportResolved, TV_VIDEO_MAX_BYTES } from '../src/ui/TVPhotoPlayer.model.ts';
const device='a'.repeat(24), itemId='b'.repeat(24), playId='c'.repeat(24);
const base=Date.parse('2026-09-20T00:00:00Z'), copy=value=>structuredClone(value);
const video=()=>({id:itemId,revision:3,width:160,height:90,mediaType:'video',durationMs:8000,hasAudio:true,
  previewUrl:'/api/media-tv/items/'+itemId+'/preview',videoUrl:'/api/media-tv/items/'+itemId+'/video'});
const snapshot=()=>({deviceId:device,revision:1,mode:'photos',paused:false,intervalSeconds:5,position:0,photoCount:1,canStart:true,
  updatedAt:new Date(base).toISOString(),serverTime:new Date(base).toISOString(),validUntil:new Date(base+15000).toISOString(),
  protocol:2,playbackCsrf:'100.15100.'+'d'.repeat(64),item:video(),progress:{playId,sequence:0,positionMs:0,durationMs:8000}});
test('video DTO binds TV-only URL, duration and progress; ignores private metadata',()=>{
  const input=snapshot(),parsed=readTVPlayback({...input,item:{...input.item,accountId:'secret'}},device);
  assert.deepEqual(parsed,input);assert.equal(TV_VIDEO_MAX_BYTES,64*1024*1024);
  for(const patch of [{videoUrl:input.item.videoUrl+'?revision=3'},{durationMs:600251},{hasAudio:undefined},{mediaType:'other'}])
    assert.throws(()=>readTVPlayback({...input,item:{...input.item,...patch}},device));
  for(const patch of [{durationMs:5000},{positionMs:8001},{sequence:-1},{playId:'other'}])
    assert.throws(()=>readTVPlayback({...input,progress:{...input.progress,...patch}},device));
});
test('photo display clock excludes loading/pause gaps and cannot use fixed interval for video',()=>{
  const c=new TVMediaClock();c.reset(700);assert.equal(c.sample(100000,false,5000),700);
  assert.equal(c.sample(101000,true,5000),700);assert.equal(c.sample(102500,true,5000),2200);
  assert.equal(c.sample(102600,false,5000),2200);assert.equal(c.sample(500000,false,5000),2200);
  assert.equal(c.sample(500001,true,5000),2200);assert.equal(c.sample(500501,true,5000),2700);
});
test('unknown report resolves only from committed sequence, new control revision or new play instance',()=>{
  const s=readTVPlayback(snapshot(),device),intent=progressIntent(s,'ended',8000);
  assert.equal(reportResolved(intent,s),false);assert.equal(intent.itemId,itemId);assert.equal(intent.itemRevision,3);
  assert.equal(reportResolved(intent,{...s,revision:2}),true);
  assert.equal(reportResolved(intent,{...s,progress:{...s.progress,sequence:1}}),true);
  assert.equal(reportResolved(intent,{...s,progress:{...s.progress,playId:'e'.repeat(24)}}),true);
});

// Actual TSX/hooks/controller with synthetic DOM, media metadata and HTTP.
// Native decoding, layout, autoplay policies and real Flask remain browser work.
function harness(options={}) {
  const ts=createRequire(import.meta.url)('typescript');let state=snapshot(),now=0,dirty=true,dead=false,cursor=0,tree;
  const values=[],effects=[],cleanups=[],timers=new Map(),listeners=new Map(),calls=[],revoked=[],created=[];
  let timerId=0,assetGate=null,reportGate=null,unknownPost=false,reportFail=false,denied=false;
  const same=(a,b)=>Array.isArray(a)&&Array.isArray(b)&&a.length===b.length&&a.every((x,i)=>Object.is(x,b[i]));
  const react={createElement(type,props,...children){return{type,props:{...props,children:children.flat(Infinity)}};},
    useRef(v){const i=cursor++;return values[i]||=( {current:v});},
    useState(v){const i=cursor++;if(!(i in values))values[i]=typeof v==='function'?v():v;return[values[i],next=>{values[i]=typeof next==='function'?next(values[i]):next;dirty=true;}];},
    useLayoutEffect(fn,deps){const i=cursor++;if(!same(values[i],deps)){values[i]=deps;effects.push(()=>{cleanups[i]?.();cleanups[i]=fn();});}}};
  const events={addEventListener(name,fn){if(!listeners.has(name))listeners.set(name,new Set());listeners.get(name).add(fn);},removeEventListener(name,fn){listeners.get(name)?.delete(fn);}};
  class Element {
    constructor(){this.src='';this.hidden=true;this.naturalWidth=160;this.naturalHeight=90;}
    removeAttribute(){this.src='';}getAttribute(){return this.src;}decode(){return Promise.resolve();}
  }
  class Movie extends Element {
    constructor(){super();this.readyState=2;this.duration=8;this.videoWidth=160;this.videoHeight=90;this.currentTime=0;this.paused=true;this.ended=false;this.seeking=false;this.muted=true;}
    pause(){this.paused=true;}
    load(){this.ended=false;this.currentTime=0;if(this.src)queueMicrotask(()=>{this.onloadedmetadata?.();this.oncanplay?.();});}
    play(){if(options.blocked)return Promise.reject(new Error('synthetic autoplay denied'));this.paused=false;return Promise.resolve();}
  }
  const image=new Element(),movie=new Movie();
  const document={...events,hidden:false,createElement(){return new Movie();}},navigator={onLine:true};
  class ObjectURL extends URL {static createObjectURL(){const url='blob:synthetic-'+(created.length+1);created.push(url);return url;}static revokeObjectURL(url){revoked.push(url);}}
  const timerApi={setTimeout(fn,ms){const id=++timerId;timers.set(id,{fn,at:now+ms,ms,repeat:false});return id;},
    setInterval(fn,ms){const id=++timerId;timers.set(id,{fn,at:now+ms,ms,repeat:true});return id;},clearTimeout(id){timers.delete(id);},clearInterval(id){timers.delete(id);}};
  function response(path,body,type='application/json',status=200){const headers={'Content-Type':type};if(status===503&&options.busy)headers['Retry-After']='1';if(type==='video/mp4'&&options.contentLength)headers['Content-Length']=options.contentLength;
    const r=new Response(type==='application/json'?JSON.stringify(body):body,{status,headers});Object.defineProperty(r,'url',{value:'http://localhost'+path});return r;}
  const raw=()=>({...copy(state),serverTime:new Date(base+now).toISOString(),validUntil:new Date(base+now+15000).toISOString()});
  const fetch=async(path,init)=>{
    calls.push({path,method:init.method,body:init.body?JSON.parse(init.body):null,init});
    if(path==='/api/media-tv/playback')return response(path,denied?{}:raw(),'application/json',denied?401:200);
    if(path===video().videoUrl){if(assetGate)await assetGate.promise;if(options.busy)return response(path,{error:'private upstream message',code:'video_busy'},'application/json',503);return response(path,new Uint8Array([0,0,0,24,102,116,121,112]),'video/mp4',options.videoStatus||200);}
    if(path==='/api/media-tv/playback/progress'){
      const body=JSON.parse(init.body);assert.equal(init.headers['X-Display-Mode'],'tv');assert(init.headers['X-TV-Playback-CSRF']);
      if(body.revision!==state.revision||body.playId!==state.progress.playId||body.sequence<=state.progress.sequence)return response(path,{},'application/json',409);
      if(body.event==='ended'){state.revision++;state.progress={playId:state.revision.toString(16).padStart(24,'0'),positionMs:0,sequence:0,durationMs:8000};}
      else state.progress={...state.progress,positionMs:body.positionMs,sequence:body.sequence};
      const committed=raw();
      if(body.event==='checkpoint'&&reportGate)await reportGate.promise;
      if(unknownPost){unknownPost=false;throw new Error('response lost after commit');}
      if(reportFail)return response(path,{},'application/json',503);
      return response(path,committed);
    }
    throw new Error('Unexpected path '+path);
  };
  const modules=new Map();
  function load(name){if(modules.has(name))return modules.get(name);const exports={};modules.set(name,exports);
    const file=new URL('../src/ui/'+name,import.meta.url),code=ts.transpileModule(readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true,target:ts.ScriptTarget.ES2022}}).outputText;
    const mocks={react,'react-native':{View:'View',StyleSheet:{create:v=>v},useWindowDimensions:()=>({width:1920,height:1080})},'react-native-paper':{Text:'Text',Button:'Button',ActivityIndicator:'Spinner'}};
    runInNewContext(code,{exports,require:n=>mocks[n]||load(n.replace('./','')+'.ts'),document,navigator,window:{...events,location:{origin:'http://localhost'}},fetch,performance:{now:()=>now},Image:Element,HTMLVideoElement:Movie,URL:ObjectURL,Blob,AbortController,Uint8Array,TextDecoder,Error,Date,Promise,...timerApi});return exports;}
  const Component=load('TVPhotoPlayer.web.tsx').default,props={deviceId:device,active:true,onUnauthorized(){denied=true;}};
  const nodes=(n=tree)=>!n||typeof n!=='object'?[]:[n,...(n.props.children||[]).flatMap(x=>nodes(x))];
  const text=(n=tree)=>typeof n==='string'?n:!n||typeof n!=='object'?'':n.props.children.map(text).join(' ');
  async function flush(){for(let i=0;i<35;i++){if(dirty&&!dead){dirty=false;cursor=0;tree=Component(props);for(const n of nodes())if(n.props.ref){const el=n.type==='video'?movie:image;n.props.ref.current=el;if(n.type==='video'){el.onloadedmetadata=n.props.onLoadedMetadata;el.oncanplay=n.props.onCanPlay;el.onended=n.props.onEnded;}}while(effects.length)effects.shift()();}await new Promise(setImmediate);}}
  async function advance(ms){const end=now+ms;while(now<end){const dt=Math.min(100,end-now);now+=dt;if(!movie.paused&&!movie.ended){movie.currentTime=Math.min(movie.duration,movie.currentTime+dt/1000);if(movie.currentTime>=movie.duration){movie.ended=true;movie.paused=true;movie.onended?.();}}for(const[id,t]of [...timers])if(t.at<=now){if(t.repeat)t.at=now+t.ms;else timers.delete(id);t.fn();}await flush();}}
  const close=()=>{dead=true;cleanups.forEach(fn=>fn?.());};
  return{calls,created,revoked,movie,flush,advance,close,text,get state(){return state;},pause(){state.paused=true;state.revision++;},resume(){state.paused=false;state.revision++;},
    next(){state.revision++;state.progress={...state.progress,playId:'e'.repeat(24),positionMs:0,sequence:0};},
    gateReport(){let release;reportGate={promise:new Promise(r=>release=r)};return()=>{release();reportGate=null;};},
    gate(){let release;assetGate={promise:new Promise(r=>release=r)};return()=>{release();assetGate=null;};},unknown(){unknownPost=true;},deny(){denied=true;},
    async retry(){options.busy=false;nodes().find(n=>n.type==='Button').props.onPress();await flush();},
    async event(name){if(name==='offline')navigator.onLine=false;if(name==='visibilitychange')document.hidden=true;for(const f of listeners.get(name)||[])f();await flush();}};
}
test('actual TV component renews independently while video bytes wait; cached Blob is not re-downloaded',async t=>{
  const h=harness();t.after(h.close);const release=h.gate();await h.flush();await h.advance(6000);
  assert(h.calls.filter(c=>c.path==='/api/media-tv/playback').length>=3);
  assert.equal(h.calls.filter(c=>c.path.endsWith('/video')).length,1);assert.equal(h.state.progress.positionMs,0);
  release();await h.flush();assert.equal(h.created.length,1);assert.equal(h.movie.paused,false);
  await h.advance(2000);assert.equal(h.calls.filter(c=>c.path.endsWith('/video')).length,1);
  assert(!h.calls.some(c=>c.init.headers?.Range));
});
test('actual TV component pause/resume retains offset and full video ended alone advances',async t=>{
  const h=harness();t.after(h.close);await h.flush();await h.advance(2400);h.pause();await h.advance(2100);
  const at=h.movie.currentTime;assert(h.movie.paused&&at>2);await h.advance(2000);assert.equal(h.movie.currentTime,at);
  assert(h.calls.some(c=>c.body?.event==='paused'&&c.body.positionMs>2000));
  h.resume();await h.advance(2100);assert(!h.movie.paused);assert.equal(h.state.revision,3);
  await h.advance(9000);assert(h.calls.some(c=>c.body?.event==='ended'&&c.body.positionMs===8000));
});
for(const event of ['offline','visibilitychange','pagehide'])test('actual TV lifecycle '+event+' stops video and releases Blob',async t=>{
  const h=harness();t.after(h.close);await h.flush();assert.equal(h.created.length,1);await h.event(event);
  assert(h.movie.paused&&h.movie.src==='');assert.deepEqual(h.revoked,h.created);
});
test('actual TV shows autoplay denial and never advances while blocked',async t=>{
  const h=harness({blocked:true});t.after(h.close);await h.flush();await h.advance(6000);
  assert(h.text().includes('浏览器尚未允许'));assert.equal(h.state.progress.positionMs,0);
  assert(!h.calls.some(c=>c.body?.event==='ended'));
});
test('actual committed response loss reads state to recover without replaying the same POST',async t=>{
  const h=harness();t.after(h.close);h.unknown();await h.flush();assert(h.text().includes('提交结果尚未核对'));
  const first=h.calls.find(c=>c.method==='POST').body;await h.advance(2200);
  assert.equal(h.calls.filter(c=>c.body&&JSON.stringify(c.body)===JSON.stringify(first)).length,1);
  assert(!h.text().includes('提交结果尚未核对'));assert.equal(h.movie.paused,false);
});
test('actual revoked lease clears cached video and stops further byte reads',async t=>{
  const h=harness();t.after(h.close);await h.flush();h.deny();await h.advance(2200);
  assert(h.movie.paused&&h.movie.src==='');assert.equal(h.calls.filter(c=>c.path.endsWith('/video')).length,1);
});
for(const options of [{videoStatus:206},{contentLength:'9'}])test('actual TV refuses partial/truncated video '+JSON.stringify(options),async t=>{
  const h=harness(options);t.after(h.close);await h.flush();await h.advance(2200);
  assert.equal(h.created.length,0);assert.equal(h.calls.filter(c=>c.path.endsWith('/video')).length,1);
  assert(!h.calls.some(c=>c.method==='POST'));assert(h.text().includes('画面已清除'));
});
test('actual TV late bytes after offline cannot recreate a Blob or send ready',async t=>{
  const h=harness();t.after(h.close);const release=h.gate();await h.flush();await h.event('offline');release();await h.flush();
  assert.equal(h.created.length,0);assert(!h.calls.some(c=>c.method==='POST'));assert(h.movie.paused);
});
test('actual TV busy video retains item and independent permissions, then explicit retry plays',async t=>{
  const h=harness({busy:true});t.after(h.close);await h.flush();await h.advance(6000);
  assert(h.text().includes('视频正在读取'));assert(!h.text().includes('private upstream'));
  assert.equal(h.state.progress.positionMs,0);assert.equal(h.state.revision,1);
  assert.equal(h.calls.filter(c=>c.path.endsWith('/video')).length,1);
  assert(h.calls.filter(c=>c.path==='/api/media-tv/playback').length>=3);
  assert(!h.calls.some(c=>c.method==='POST'));await h.retry();
  assert.equal(h.calls.filter(c=>c.path.endsWith('/video')).length,2);assert.equal(h.movie.paused,false);
});
test('actual TV busy is not permission: revocation clears waiting state without fetching or advancing',async t=>{
  const h=harness({busy:true});t.after(h.close);await h.flush();h.deny();await h.advance(2200);
  assert(!h.text().includes('视频正在读取'));assert(h.movie.paused&&h.movie.src==='');
  assert.equal(h.calls.filter(c=>c.path.endsWith('/video')).length,1);assert(!h.calls.some(c=>c.method==='POST'));
});
test('classic TV offers same-origin modern entry without media fetch or playback timer',()=>{
  const children=[],listeners={},nodes=[];let timerCalls=0,fetches=0;
  const node=()=>{const n={style:{},children:[],setAttribute(k,v){this[k]=v;},append(...items){this.children.push(...items);},remove(){this.removed=true;}};nodes.push(n);return n;};
  const document={hidden:false,createElement:node,createTextNode:text=>({text}),body:{append:n=>children.push(n),classList:{remove(){}}},addEventListener:(k,v)=>listeners[k]=v};
  const window={addEventListener:(k,v)=>listeners[k]=v};
  const context={window,document,user:{role:'tv',id:device,householdId:'one'},csrf:'',isTV:true,isDemo:false,
    clearInterval(){},setInterval(){timerCalls++;},URL,fetch(){fetches++;throw new Error('Unexpected classic media request');}};
  runInNewContext(readFileSync(new URL('../../static/media-tv.js',import.meta.url),'utf8'),context);
  window.MediaTV.ensureDisplay();window.MediaTV.ensureDisplay();assert.equal(children.length,1);
  assert.equal(children[0].children[1].href,'/app/tv');assert.match(children[0].children[0].text,/经典电视页不再播放/);
  listeners.pagehide();assert(children[0].removed);window.MediaTV.ensureDisplay();
  context.user={role:'member'};window.MediaTV.notifyIdentityChanged();assert(children[1].removed);
  window.MediaTV.ensureDisplay();assert.equal(children.length,2);assert.equal(timerCalls,0);assert.equal(fetches,0);
});
test('actual delayed checkpoint cannot lose a real video ended; advances exactly once after response',async t=>{
  const h=harness();t.after(h.close);await h.flush();const release=h.gateReport();await h.advance(8200);
  assert(h.movie.ended&&h.movie.paused);assert.equal(h.state.revision,1);
  assert(h.calls.some(c=>c.body?.event==='checkpoint'));assert(!h.calls.some(c=>c.body?.event==='ended'));
  release();await h.flush();await h.advance(300);
  const reports=h.calls.filter(c=>c.body?.event==='ended');assert.equal(reports.length,1);
  assert.equal(reports[0].body.playId,playId);assert.equal(reports[0].body.positionMs,8000);assert.equal(h.state.revision,2);
});
for(const action of ['pause','deny','next','offline'])test('actual delayed checkpoint ending respects '+action+' before slot is released',async t=>{
  const h=harness();t.after(h.close);await h.flush();const release=h.gateReport();await h.advance(action==='offline'?8200:6900);
  if(action==='offline')await h.event('offline');else h[action]();
  // Allow the independent poll to observe changed controls/permission before
  // releasing the old response, below its five-second request deadline.
  await h.advance(action==='offline'?900:2200);release();await h.flush();await h.advance(2100);
  assert(!h.calls.some(c=>c.body?.event==='ended'),'obsolete/paused/unauthorized end must not be sent');
  if(action==='next'){
    assert(h.calls.some(c=>c.body?.event==='ready'&&c.body.playId==='e'.repeat(24)));
    assert.equal(h.movie.paused,false);assert.equal(h.state.revision,2);
  }else assert(h.movie.paused);
});
test('actual delayed checkpoint with unknown response freezes end until a current GET resolves it',async t=>{
  const h=harness();t.after(h.close);await h.flush();const release=h.gateReport();await h.advance(8200);
  h.unknown();release();await h.flush();assert(h.text().includes('提交结果尚未核对'));
  assert(h.movie.paused&&h.movie.src==='');assert(!h.calls.some(c=>c.body?.event==='ended'));
  await h.advance(300);assert(!h.text().includes('提交结果尚未核对'));
  assert(!h.calls.some(c=>c.body?.event==='ended'));assert.equal(h.state.revision,1);
  assert.equal(h.calls.filter(c=>c.body?.event==='checkpoint'&&c.body.sequence===2).length,1);
});
