import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { readJourneyReview, readJourneyPreview, readTVRoute, restoreJourneyMarker, forgetJourneyMarker, TRIP_TV_STORAGE_KEY, TripTVFence, TripTVDiscarded, journeyActor } from '../src/lib/tvTripRecap.ts';
import { sessionIdentity } from '../src/lib/sessionIdentity.ts';
import { readPlayback, playbackPayload } from '../src/lib/devices.ts';
import { readTVPlayback } from '../src/ui/TVPhotoPlayer.model.ts';
const device='a'.repeat(24),journey='b'.repeat(24),routeId='c'.repeat(24),requestId='d'.repeat(32),source='e'.repeat(64);
const member={user:{role:'member',id:'alice',householdId:'house',auth_version:1},csrf:'csrf-one'};
const trip=()=>({id:journey,tripId:'f'.repeat(24),title:'合成旅行',start:'2026-09-01',end:'2026-09-03',revision:1,tripRevision:1});
const stop=(index)=>({index,state:'available',place:{id:index.toString(16).padStart(24,'0'),name:'合成站点'+index,country:'合成国家',city:'合成城市',coordinates:{latitude:20+index*.1,longitude:100},coordinatePrecision:'approximate',coordinateGridDegrees:.1,status:'visited',startDate:null,endDate:null}});
const route=(count=9)=>({id:routeId,title:'合成共享路线',revision:2,stops:Array.from({length:count},(_,i)=>stop(i)),segments:Array.from({length:Math.max(0,count-1)},(_,i)=>({fromIndex:i,toIndex:i+1}))});
const review=()=>({status:'ready',journey:trip(),routeStatus:'available',route:route(),sourceVersion:source});
const playback=()=>({deviceId:device,revision:3,mode:'photos',paused:false,intervalSeconds:10,position:0,photoCount:0,canStart:true,updatedAt:'2026-09-21T00:00:00Z',scope:'journey',journeyReview:review()});
const tv=()=>({...playback(),serverTime:'2026-09-21T00:00:00Z',validUntil:'2026-09-21T00:00:15Z',item:null,progress:null,protocol:2,playbackCsrf:'10.20.'+'0'.repeat(64)});
const preview=(revision=3)=>({previewToken:'opaque-token',expiresAt:'2026-09-21T00:05:00Z',playbackRevision:revision,sourceVersion:source,journey:trip(),mediaCount:0,routeStatus:'available',route:route(),canStart:true});
const receipt=(id=requestId)=>({requestId:id,kind:'journey_start',deviceId:device,resultRevision:4,completedAt:'2026-09-21T00:00:01Z'});
const storage=()=>{const values=new Map();return{getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k),values};};

test('route-only is playable on phone and TV without a media item/progress; previous/next stay unavailable',()=>{
  assert.equal(readPlayback(playback(),device).canStart,true);assert.equal(readTVPlayback(tv(),device).item,null);
  assert.throws(()=>playbackPayload(readPlayback(playback(),device),'next'));
  assert.equal(playbackPayload(readPlayback(playback(),device),'pause').revision,3);
  const gone={...tv(),canStart:false,journeyReview:{status:'journey_unavailable',journey:null,routeStatus:'unavailable',route:null,sourceVersion:source}};
  assert.equal(readTVPlayback(gone,device).scope,'journey');
  assert.throws(()=>readTVPlayback({...gone,canStart:true},device));
  assert.throws(()=>readTVPlayback({...tv(),scope:'all',journeyReview:null},device));
});
test('TV route projection strips private fields and rejects hidden/coarse leaks or crossing a missing stop',()=>{
  const r=route(3);r.stops[0].place.secret='private';assert(!('secret' in readTVRoute(r).stops[0].place));
  r.stops[1]={index:1,state:'unavailable'};assert.throws(()=>readTVRoute(r));
  r.segments=[];assert.equal(readTVRoute(r).stops[1].state,'unavailable');
  r.segments=[{fromIndex:0,toIndex:2}];assert.throws(()=>readTVRoute(r));
  for(const patch of [{coordinatePrecision:'hidden'},{coordinates:{latitude:20.12345,longitude:100}},{coordinateGridDegrees:null}]){
    const v=route(1);Object.assign(v.stops[0].place,patch);assert.throws(()=>readTVRoute(v));
  }
  assert.throws(()=>readTVRoute({...route(),stops:[{index:0,state:'unavailable',name:'private'}]}));
});
test('preview binds original journey, route and control revision; unavailable routes never retain old metadata',()=>{
  assert.equal(readJourneyPreview(preview(),journey,routeId,3).mediaCount,0);
  for(const args of [[journey,null,3],['0'.repeat(24),routeId,3],[journey,routeId,4]])assert.throws(()=>readJourneyPreview(preview(),...args));
  assert.throws(()=>readJourneyReview({...review(),routeStatus:'unavailable'}));
  assert.equal(readJourneyReview({...review(),routeStatus:'unavailable',route:null}).route,null);
});
test('minimal recovery is actor-bound and an old completion cannot clear a newer marker',()=>{
  const store=storage(),marker={memberIdentity:journeyActor(member),deviceId:device,requestId};
  store.setItem(TRIP_TV_STORAGE_KEY,JSON.stringify(marker));assert.deepEqual(restoreJourneyMarker(store,marker.memberIdentity),marker);
  const newer={...marker,requestId:'e'.repeat(32)};store.setItem(TRIP_TV_STORAGE_KEY,JSON.stringify(newer));forgetJourneyMarker(store,marker);assert(store.getItem(TRIP_TV_STORAGE_KEY));
  assert.equal(restoreJourneyMarker(store,'another-member'),null);assert.equal(store.values.size,0);
  store.setItem(TRIP_TV_STORAGE_KEY,JSON.stringify({...marker,previewToken:'private'}));assert.equal(restoreJourneyMarker(store,marker.memberIdentity),null);
});
test('write fence rejects late identity and post-me failure without classifying the write as rejected',async()=>{
  let calls=0,commits=0;const f=new TripTVFence(sessionIdentity(member),async()=>++calls===1?member:{...member,user:{...member.user,id:'bob'}});
  await assert.rejects(()=>f.run(async()=>{commits++;return 'committed';},()=>true),e=>e instanceof TripTVDiscarded&&e.message==='identity');assert.equal(commits,1);
  calls=0;const g=new TripTVFence(sessionIdentity(member),async()=>{if(++calls===2)throw Error('me404');return member;});
  await assert.rejects(()=>g.run(async()=>{commits++;return 'committed';},()=>true),/me404/);assert.equal(commits,2);
});

// Run actual TSX/hooks and handlers. HTTP/DOM here are controlled unit seams;
// actual Flask sessions, layout, two browsers and media decoding are separate.
function harness(options={}) {
  const ts=createRequire(import.meta.url)('typescript'),values=[],effects=[],cleanups=[],listeners=new Map(),timers=new Map();
  let cursor=0,dirty=true,tree,dead=false,timerId=0,now=0,identity=structuredClone(member),postMeFailure=false,hold=null;
  const calls=[],store=options.storage||storage();let server=playback(),operation=null;
  const env={online:true,user:identity.user,csrf:identity.csrf,identityKey:sessionIdentity(member),refresh:async()=>{}};
  const equal=(a,b)=>Array.isArray(a)&&Array.isArray(b)&&a.length===b.length&&a.every((x,i)=>Object.is(x,b[i]));
  const react={createElement(type,props,...children){return{type,props:{...props,children:children.flat(Infinity)}};},
    useRef(value){const i=cursor++;return values[i]||=({current:value});},useState(value){const i=cursor++;if(!(i in values))values[i]=typeof value==='function'?value():value;return[values[i],v=>{values[i]=typeof v==='function'?v(values[i]):v;dirty=true;}];},
    useCallback(fn,deps){const i=cursor++;if(!equal(values[i]?.deps,deps))values[i]={deps,fn};return values[i].fn;},
    useEffect(fn,deps){const i=cursor++;if(!equal(values[i],deps)){values[i]=deps;effects.push(()=>{cleanups[i]?.();cleanups[i]=fn();});}}};
  const events={addEventListener(k,f){if(!listeners.has(k))listeners.set(k,new Set());listeners.get(k).add(f);},removeEventListener(k,f){listeners.get(k)?.delete(f);}};
  const document={...events,hidden:false},navigator={onLine:true};
  const timerApi={setTimeout(fn,ms){const id=++timerId;timers.set(id,{fn,at:now+ms,repeat:false,ms});return id;},setInterval(fn,ms){const id=++timerId;timers.set(id,{fn,at:now+ms,repeat:true,ms});return id;},clearTimeout:id=>timers.delete(id),clearInterval:id=>timers.delete(id)};
  const reply=(path,data,status=200)=>{const r=new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}});Object.defineProperty(r,'url',{value:'https://example.test'+path});return r;};
  const fetch=async(path,init)=>{
    calls.push({path,method:init.method||'GET',body:init.body?JSON.parse(init.body):null});
    if(path==='/api/me'){if(postMeFailure){postMeFailure=false;return reply(path,{},404);}return reply(path,identity);}
    if(path==='/api/devices'&&options.noDevices)return reply(path,[]);
    if(path==='/api/devices')return reply(path,[{id:device,name:'合成电视',focus:'shared',calendarView:'today',revision:1,created_at:'2026-09-21',layout:{order:['calendar','finance','tasks','shopping','trips'],hidden:[],theme:'forest',density:'comfortable'}}]);
    if(path.startsWith('/api/journey-routes?'))return reply(path,{items:[{id:routeId,title:'合成共享路线',journeyId:journey,visibility:'shared',revision:2,canManage:true,stopCount:9,unavailableCount:0}],total:1,limit:24,offset:0,hasMore:false});
    if(path.endsWith('/journey-preview')){const p=preview(server.revision);if(JSON.parse(init.body).routeId===null)Object.assign(p,{route:null,routeStatus:'not_selected',mediaCount:1});return reply(path,p);}
    if(path.endsWith('/journey-start')){if(options.dropBefore){options.dropBefore=false;throw Error('disconnected before delivery');}operation=receipt(JSON.parse(init.body).requestId);server={...server,revision:4};if(options.postMeFailure)postMeFailure=true;if(options.drop)throw Error('lost after real synthetic commit');return reply(path,{operation,playback:server,replayed:false});}
    if(path.includes('/operations/')){if(hold){const wait=hold;await wait.promise;}return reply(path,options.notFound||!operation?{found:false}:{found:true,operation,playback:server});}
    if(path==='/api/media-playback/devices/'+device){if(hold){const wait=hold;await wait.promise;}if(init.method==='PUT'){assert.equal(JSON.parse(init.body).revision,server.revision);const action=JSON.parse(init.body).action;server={...server,revision:server.revision+1,paused:action==='pause'};if(action==='dashboard')server={...server,mode:'dashboard',scope:'all',journeyReview:null,canStart:false};}return reply(path,server);}
    throw Error('Unexpected '+path);
  };
  const modules=new Map(),src=new URL('../src/',import.meta.url);
  const mocks={react,'react-native':{View:'View',StyleSheet:{create:v=>v},AppState:{currentState:'active',addEventListener(){return{remove(){}};}}},
    'react-native-paper':{ActivityIndicator:'Spinner',Button:'Button',RadioButton:{Item:'Radio'},Text:'Text',TextInput:'Input',useTheme:()=>({colors:{error:'error',onSurface:'text',onSurfaceVariant:'muted'}})},
    'expo-router':{useFocusEffect(fn){react.useEffect(fn,[fn]);}},'../lib/household':{useHousehold:()=>env},'../ui/components':{EmptyState:'Empty',PageHeader:'Header',SectionCard:'Card'},'./WorldMap':{default:'Map',__esModule:true}};
  function load(file){if(modules.has(file.href))return modules.get(file.href);const exports={};modules.set(file.href,exports);
    const code=ts.transpileModule(readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText;
    runInNewContext(code,{exports,require:n=>{if(mocks[n])return mocks[n];if(!n.startsWith('.'))throw Error('Unexpected import '+n);return load(new URL(/\.(ts|tsx)$/.test(n)?n:n+'.ts',file));},fetch,sessionStorage:store,document,navigator,window:{...events,location:{origin:'https://example.test'}},URL,Response,AbortController,Uint8Array,TextDecoder,crypto:{getRandomValues:v=>v.fill(13)},performance:{now:()=>now},...timerApi});return exports;
  }
  const filename=options.display?'ui/TVTripRecap.tsx':'components/TripTVRecapPanel.tsx';
  let code=readFileSync(new URL(filename,src),'utf8');
  // Export existing inner component for hook execution; production source is unchanged.
  if(!options.display)code=code.replace('function Workspace(', 'export function Workspace(');
  const exports={},file=new URL(filename,src);
  runInNewContext(ts.transpileModule(code,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText,
    {exports,require:n=>mocks[n]||load(new URL(/\.(ts|tsx)$/.test(n)?n:n+'.ts',file)),fetch,sessionStorage:store,document,navigator,window:{...events,location:{origin:'https://example.test'}},URL,Response,AbortController,Uint8Array,TextDecoder,crypto:{getRandomValues:v=>v.fill(13)},performance:{now:()=>now},...timerApi});
  const Component=options.display?exports.default:exports.Workspace,props=options.display?{review:review(),paused:false,hasMedia:false,scale:1}:{journeyId:journey,onBack(){},identity:sessionIdentity(member),actor:journeyActor(member)};
  const nodes=n=>!n||typeof n!=='object'?[]:[n,...(n.props.children||[]).flatMap(nodes),...(n.props.action?nodes(n.props.action):[])];
  const textNode=n=>typeof n==='string'?n:typeof n==='number'?String(n):!n||typeof n!=='object'?'':(n.props.children||[]).map(textNode).join(' ');
  const text=()=>textNode(tree);
  const find=id=>nodes(tree).find(n=>n.props.testID===id);
  async function flush(){for(let i=0;i<30;i++){if(dirty&&!dead){dirty=false;cursor=0;tree=Component(props);while(effects.length)effects.shift()();}await new Promise(setImmediate);}}
  const close=()=>{dead=true;cleanups.forEach(fn=>fn?.());};
  return{calls,store,flush,close,text,find,props,get server(){return server;},changeServer(fn){server=fn(server);},
    async press(id){const n=find(id);assert(n,'missing '+id);assert(!n.props.disabled,'disabled '+id);const target=n.props.onPress?n:(n.props.children||[]).find(n=>n?.props.onPress);target.props.onPress();await flush();},
    async event(name){if(name==='offline')navigator.onLine=false;if(name==='online')navigator.onLine=true;for(const fn of listeners.get(name)||[])fn();await flush();},
    async advance(ms){now+=ms;for(const[id,t]of [...timers])if(t.at<=now){if(t.repeat)t.at=now+t.ms;else timers.delete(id);t.fn();}await flush();},
    async render(){dirty=true;await flush();},
    gate(){let release;hold={promise:new Promise(r=>release=r)};return()=>{release();hold=null;};},identity(){identity={...identity,user:{...identity.user,id:'bob'}};},
    setOperation(value){operation=value;}};
}
async function select(h){await h.flush();await h.press('trip-tv-device-'+device);await h.press('trip-tv-route-'+routeId);await h.press('trip-tv-preview');}
test('actual phone chooses server preview, starts once, controls fresh revision, and hides media next for route-only',async t=>{
  const h=harness();t.after(h.close);await select(h);assert(h.text().includes('合成旅行'));await h.press('trip-tv-start');
  assert.equal(h.calls.filter(c=>c.path.endsWith('/journey-start')).length,1);assert(!h.find('trip-tv-next'));assert.equal(h.store.values.size,0);
  h.changeServer(p=>({...p,revision:8}));await h.press('trip-tv-pause');assert.equal(h.calls.find(c=>c.method==='PUT').body.revision,8);
  assert(h.find('trip-tv-resume'));await h.press('trip-tv-dashboard');assert(h.text().includes('当前显示家庭看板'));
});
for(const option of ['drop','postMeFailure'])test('actual '+option+' after committed start preserves minimal marker and GET recovers without another POST',async t=>{
  const h=harness({[option]:true});t.after(h.close);await select(h);await h.press('trip-tv-start');assert(h.find('trip-tv-unknown'));
  const value=JSON.parse(h.store.getItem(TRIP_TV_STORAGE_KEY));assert.deepEqual(Object.keys(value).sort(),['deviceId','memberIdentity','requestId']);
  assert(!JSON.stringify(value).includes('csrf-one'));await h.press('trip-tv-recheck');assert(!h.find('trip-tv-unknown'));assert(h.text().includes('已核对原开始回执'));
  assert.equal(h.calls.filter(c=>c.path.endsWith('/journey-start')).length,1);
});
test('actual reload reads original operation first; found false retains unknown and never starts',async t=>{
  const store=storage();store.setItem(TRIP_TV_STORAGE_KEY,JSON.stringify({memberIdentity:journeyActor(member),deviceId:device,requestId}));
  const h=harness({storage:store,notFound:true});t.after(h.close);await h.flush();assert(h.find('trip-tv-unknown'));assert(h.text().includes('读取时尚无原操作回执'));
  assert(h.calls.some(c=>c.path.endsWith('/operations/'+requestId)));assert(!h.calls.some(c=>c.method==='POST'));assert(!h.find('trip-tv-start'));
});
test('actual offline hides private projection; later GET followed by another member cannot install it or preserve old marker',async t=>{
  const h=harness({drop:true});t.after(h.close);await select(h);await h.press('trip-tv-start');await h.event('offline');assert(!h.text().includes('合成旅行'));
  const release=h.gate();await h.event('online');h.identity();release();await h.flush();assert(!h.text().includes('合成旅行'));assert(h.text().includes('登录身份已变化'));assert.equal(h.store.values.size,0);
});
test('actual TV eight-stop pages rotate, pause holds page, and a changed projection clears old route data',async t=>{
  const h=harness({display:true});t.after(h.close);await h.flush();assert(h.find('tv-trip-stop-7'));assert(!h.find('tv-trip-stop-8'));
  await h.advance(15000);assert(h.find('tv-trip-stop-8'));assert(!h.find('tv-trip-stop-0'));
  h.props.paused=true;await h.render();await h.advance(30000);assert(h.find('tv-trip-stop-8'));
  h.props.review={...review(),sourceVersion:'1'.repeat(64),route:null,routeStatus:'unavailable'};await h.render();assert(!h.find('tv-trip-route'));assert(!h.text().includes('合成共享路线'));
});
test('actual explicit retry queries receipt first and reuses the original request/token/body',async t=>{
  const h=harness({dropBefore:true});t.after(h.close);await select(h);await h.press('trip-tv-start');
  await h.press('trip-tv-recheck');assert(h.find('trip-tv-unknown-current'));assert(h.find('trip-tv-retry'));
  const count=h.calls.length;await h.press('trip-tv-retry');
  const posts=h.calls.filter(c=>c.path.endsWith('/journey-start'));assert.equal(posts.length,2);assert.deepEqual(posts[0].body,posts[1].body);
  const tail=h.calls.slice(count);assert(tail.findIndex(c=>c.path.includes('/operations/'))<tail.findIndex(c=>c.path.endsWith('/journey-start')));
  assert(!h.find('trip-tv-unknown'));assert.equal(h.store.values.size,0);
});
test('actual reload without token can explicitly re-preview after receipt/current GET, never automatically starts',async t=>{
  const store=storage();store.setItem(TRIP_TV_STORAGE_KEY,JSON.stringify({memberIdentity:journeyActor(member),deviceId:device,requestId}));
  const h=harness({storage:store});t.after(h.close);await h.flush();assert(!h.find('trip-tv-retry'));assert(h.find('trip-tv-repreview'));
  const count=h.calls.length;await h.press('trip-tv-repreview');assert.equal(store.values.size,0);assert(h.find('trip-tv-start'));assert(!h.find('trip-tv-unknown'));
  const tail=h.calls.slice(count);assert(tail.some(c=>c.path.includes('/operations/')));assert(tail.some(c=>c.path.endsWith('/journey-preview')));
  assert(!h.calls.some(c=>c.path.endsWith('/journey-start')));assert(h.text().includes('上次请求仍可能稍后完成'));
});
test('actual idle preview identity check clears old trip without starting or persisting private DTO',async t=>{
  const h=harness();t.after(h.close);await select(h);assert(h.find('trip-tv-preview-content'));h.identity();await h.advance(5000);
  assert(!h.find('trip-tv-preview-content'));assert(!h.text().includes('合成旅行'));assert.equal(h.store.values.size,0);assert(!h.calls.some(c=>c.path.endsWith('/journey-start')));
});
test('actual refresh drops a removed device selection and does not keep polling its stale identity',async t=>{
  const options={},h=harness(options);t.after(h.close);await select(h);options.noDevices=true;
  await h.event('offline');await h.event('online');assert(!h.find('trip-tv-controls'));assert(h.text().includes('没有已配对电视'));
  const count=h.calls.filter(c=>c.path==='/api/media-playback/devices/'+device).length;await h.advance(5000);
  assert.equal(h.calls.filter(c=>c.path==='/api/media-playback/devices/'+device).length,count);assert(h.find('trip-tv-preview').props.disabled);
});
