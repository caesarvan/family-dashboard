import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readFileSync,existsSync} from 'node:fs';
import {createRequire} from 'node:module';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {runInNewContext} from 'node:vm';
import {webcrypto} from 'node:crypto';

const require=createRequire(import.meta.url),ts=require('typescript'),root=resolve(dirname(fileURLToPath(import.meta.url)),'../src');
const clone=value=>JSON.parse(JSON.stringify(value));
function loader(mocks={},globals={}) {
  const cache=new Map();
  function load(path) {
    path=resolve(path);if(!existsSync(path))path+=existsSync(path+'.ts')?'.ts':'.tsx';
    if(cache.has(path))return cache.get(path);
    const exports={};cache.set(path,exports);
    const code=ts.transpileModule(readFileSync(path,'utf8'),{fileName:path,compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText;
    runInNewContext(code,{exports,require:name=>name in mocks?mocks[name]:load(resolve(dirname(path),name)),Date,Intl,Error,URL,URLSearchParams,TextEncoder,TextDecoder,AbortController,crypto:webcrypto,process:{env:{}},...globals});return exports;
  }return load;
}
const load=loader(),api=load(resolve(root,'lib/api.ts')),assistant=load(resolve(root,'lib/assistant.ts')),identity=load(resolve(root,'lib/sessionIdentity.ts'));
const photoId='a'.repeat(24),journeyId='1'.repeat(24),tripId='2'.repeat(24),journey={id:journeyId,tripId,title:'合成原旅行'};
const clonePlace=patch=>({id:photoId,owner:'alice',name:'当前地点名称',country:'合成国家',city:'合成城市',coordinates:{latitude:31.2,longitude:121.4},coordinatePrecision:'exact',coordinateGridDegrees:null,coordinateDisclosure:'hidden',status:'wish',visibility:'private',journeyId,journey,revision:3,canManage:true,createdAt:'2026-09-20',updatedAt:'2026-09-20',startDate:null,endDate:null,visitedConfirmedAt:null,visitedConfirmedBy:null,...patch});
const match=(patch={})=>({kind:'places',id:photoId,title:'旧地点快照',revision:1,visibility:'private',journey,...patch});
const page=(matches,offset=0,total=matches.length)=>({query:'凭证',matches,total,limit:20,offset,nextOffset:offset+matches.length<total?offset+matches.length:null});
const session=()=>({user:{id:'alice',name:'合成本人',role:'member',householdId:'home',auth_version:1},csrf:'synthetic-csrf'});
const deferred=()=>{let release;const promise=new Promise(resolve=>{release=resolve;});return {promise,release};};
// Actual TSX entry/map/fence; synthetic transport/host controls, not browser or API proof.
function harness(options={}) {
  const f={session:session(),matches:[match()],place:clonePlace(),calls:[],mutations:[],gate:null,placeStatus:0,refreshes:0,...options};
  let holder,cursor=0,dirty=true,tree,serial=0,closed=false;
  const instances=new Map(),types=new Map(),effects=[],listeners=new Map(),timers=new Map();
  const events={addEventListener(key,fn){if(!listeners.has(key))listeners.set(key,new Set());listeners.get(key).add(fn);},removeEventListener(key,fn){listeners.get(key)?.delete(fn);}};
  const document={hidden:false,hasFocus:()=>true,...events},window={...events},navigator={onLine:true};
  const changed=(a,b)=>!a||!b||a.length!==b.length||a.some((v,i)=>v!==b[i]);
  const useState=initial=>{const h=holder,i=cursor++;if(!(i in h.values))h.values[i]=typeof initial==='function'?initial():initial;return[h.values[i],next=>{if(!h.dead){h.values[i]=typeof next==='function'?next(h.values[i]):next;dirty=true;}}];};
  const useRef=initial=>{const i=cursor++;if(!(i in holder.values))holder.values[i]={current:initial};return holder.values[i];};
  const useEffect=(fn,deps)=>{const h=holder,i=cursor++;if(changed(h.values[i],deps)){h.values[i]=deps;effects.push(()=>{h.cleanups[i]?.();if(!h.dead)h.cleanups[i]=fn();});}};
  const useCallback=(fn,deps)=>{const i=cursor++;if(!holder.values[i]||changed(holder.values[i].deps,deps))holder.values[i]={deps,fn};return holder.values[i].fn;};
  const react={useState,useRef,useEffect,useCallback,Fragment:'Fragment',createElement:(type,props,...children)=>({type,props:{...props,children:children.flat(Infinity).filter(n=>n!==null&&n!==undefined&&n!==false)}})};
  const household={user:clone(f.session.user),identityKey:identity.sessionIdentity(f.session),online:true,state:{people:[]},refresh:async()=>{f.refreshes++;},setNotice(){}};
  const search=offset=>page(clone(f.matches.slice(offset,offset+20)),offset,f.matches.length);
  async function request(path,options={}) {
    f.calls.push(path);let value;
    if(options.method==='PATCH'){
      assert.equal(path,'/journey-places/'+photoId);const body=JSON.parse(options.body);f.mutations.push({path,method:'PATCH',body});
      assert.equal(body.revision,f.place.revision);f.place={...f.place,...body,revision:f.place.revision+1};value={place:clone(f.place)};
    }
    else if(path==='/me'){value=clone(f.session);}
    else if(path==='/assistant/brief')value={modelConfigured:false};
    else if(path.startsWith('/assistant/search?')){const u=new URL('https://synthetic.invalid'+path);value=search(Number(u.searchParams.get('offset')));}
    else if(path.startsWith('/journey-places?'))value={items:Array.from({length:24},(_,i)=>clonePlace({id:(i+10).toString(16).padStart(24,'0'),name:'本页地点 '+i,coordinates:null})),total:25,limit:24,offset:Number(new URL('https://synthetic.invalid'+path).searchParams.get('offset')),hasMore:true};
    else if(path==='/journey-places/'+photoId){if(f.placeStatus)throw new api.ApiError('地点不可见',f.placeStatus);value={place:clone(f.place)};}
    else if(path==='/journeys')value={journeys:[{id:journeyId,tripId,trip:{title:journey.title}}]};
    else throw new Error('Unexpected synthetic HTTP '+path);
    if(f.gate?.path===path)await f.gate.promise;
    return value;
  }
  household.mutate=async(path,method,body)=>{
    f.mutations.push({path,method,body:clone(body)});
    if(path==='/assistant/plan')return{mode:'local',id:null,summary:'只读搜索',actions:[],matches:search(0).matches,search:{...search(0),matches:undefined}};
    throw new Error('Unexpected synthetic business mutation '+path);
  };
  const paper=Object.fromEntries(['ActivityIndicator','Button','Chip','Divider','HelperText','Icon','Image','Text','TextInput','TouchableRipple','Portal','ProgressBar','SegmentedButtons'].map(k=>[k,k]));
  for(const [name,children]of Object.entries({Dialog:['Title','Content','Actions','ScrollArea'],Menu:['Item'],List:['Accordion','Item'],Card:['Content'],Checkbox:['Android','Item']}))paper[name]=Object.assign(name,...children.map(child=>({[child]:name+child})));
  paper.useTheme=()=>({colors:{error:'#b00',onSurfaceVariant:'#555',onSurface:'#111',primary:'#000',surface:'#fff',onSurfaceDisabled:'#888'}});
  const mocks={react,'react-native':{View:'View',Image:'Image',ScrollView:'ScrollView',Platform:{OS:'web'},StyleSheet:{create:x=>x},useWindowDimensions:()=>({width:390,height:844}),AppState:{currentState:'active',addEventListener:(_name,fn)=>{events.addEventListener('app',fn);return{remove:()=>events.removeEventListener('app',fn)};}},Linking:{}},'react-native-paper':paper,'expo-router':{useFocusEffect:fn=>useEffect(fn,[fn])},'../lib/household':{useHousehold:()=>household},'../lib/api':{...api,request},'./api':{...api,request},'../ui/WorldMap':{__esModule:true,default:'WorldMap'},'../ui/components':{PageHeader:'PageHeader',SectionCard:'SectionCard',EmptyState:'EmptyState'},'../ui/theme':{useDisplayDensity:()=>({screenGap:16,sectionGap:12,tripGap:8})}};
  for(const name of ['./JourneyBriefPanel','./TripsScreen','./JourneyDocumentsPanel','./PhotosScreen','./TripPhotosScreen','../components/ExistingTripChangePanel','../components/AssistantFinanceQueryPanel','../components/PhotoJourneySuggestions'])mocks[name]={__esModule:true,default:'UnusedPanel'};
  const globals={document,window,navigator,setTimeout:fn=>{const id=++serial;timers.set(id,fn);return id;},clearTimeout:id=>timers.delete(id),setInterval:fn=>{const id=++serial;timers.set(id,fn);return id;},clearInterval:id=>timers.delete(id)};
  const ui=loader(mocks,globals),Component=ui(resolve(root,'screens/AssistantScreen.tsx')).AssistantScreen;
  const props={user:household.user,state:{people:[household.user]},onNavigate(){},onInventory(){},...(options.screen==='documents'?{onBack:()=>{f.back=true;}}:{})};
  function expand(node,path='root',seen=new Set()) {
    if(!node||typeof node!=='object')return node;if(Array.isArray(node))return node.map((n,i)=>expand(n,path+'.'+i,seen));
    if(typeof node.type==='function'){
      if(!types.has(node.type))types.set(node.type,types.size+1);const key=path+':'+types.get(node.type)+':'+(node.props.key??'');seen.add(key);
      if(!instances.has(key))instances.set(key,{values:[],cleanups:[],dead:false});holder=instances.get(key);cursor=0;
      return expand(node.type(node.props),key,seen);
    }
    return{...node,props:{...node.props,action:expand(node.props.action,path+'.action',seen),children:node.props.children.map((n,i)=>expand(n,path+'.'+(n?.props?.key??i),seen))}};
  }
  function render(){dirty=false;const seen=new Set();tree=expand(react.createElement(Component,props),'root',seen);for(const [key,h]of instances)if(!seen.has(key)){h.dead=true;h.cleanups.forEach(fn=>fn?.());instances.delete(key);}while(effects.length)effects.shift()();}
  async function flush(){for(let i=0;i<50;i++){if(dirty&&!closed)render();await new Promise(setImmediate);}assert(!dirty||closed,'render did not settle');}
  const hidden=n=>n?.props?.visible===false||n?.props?.style?.display==='none';
  function nodes(n=tree){if(!n||typeof n!=='object'||hidden(n))return[];if(Array.isArray(n))return n.flatMap(v=>nodes(v??null));return[n,...nodes(n.props.action??null),...n.props.children.flatMap(v=>nodes(v??null))];}
  function text(n=tree){if(typeof n==='string'||typeof n==='number')return String(n);if(!n||typeof n!=='object'||hidden(n))return'';return[n.props.title||'',n.props.description||'',...n.props.children.map(v=>text(v??null)),text(n.props.action??null)].join(' ');}
  const control=label=>nodes().filter(n=>(n.props.accessibilityLabel||n.props.label||text(n).trim().replace(/\s+/g,' '))===label&&(n.props.onPress||n.props.onChangeText));
  async function click(label){const found=control(label);assert.equal(found.length,1,label+'\n'+text());assert(!found[0].props.disabled,label+' disabled');found[0].props.onPress();await flush();}
  async function input(label,value){const found=control(label);assert.equal(found.length,1,label);assert(!found[0].props.disabled);found[0].props.onChangeText(value);await flush();}
  return{f,flush,click,input,nodes,text,control,household,props,
    async tick(){for(const fn of [...timers.values()])fn();await flush();},
    async returnNested(){const panel=nodes().find(n=>n.type==='UnusedPanel');assert(panel);(panel.props.onReturnMap||panel.props.onBack)();await flush();},
    async search(){await flush();await input('告诉助理你的需求','搜索：凭证');await click('整理并预览');},
    async emit(event){for(const fn of [...(listeners.get(event)||[])])fn({});await flush();},
    async offline(){navigator.onLine=false;household.online=false;for(const fn of [...(listeners.get('offline')||[])])fn({});dirty=true;await flush();},
    async online(){navigator.onLine=true;household.online=true;for(const fn of [...(listeners.get('online')||[])])fn({});dirty=true;await flush();},
    async switchMember(){f.session={user:{...f.session.user,id:'bob',name:'合成伙伴'},csrf:'new-csrf'};household.user=clone(f.session.user);household.identityKey=identity.sessionIdentity(f.session);props.user=household.user;props.state.people=[household.user];dirty=true;await flush();},
    close(){closed=true;for(const h of instances.values()){h.dead=true;h.cleanups.forEach(fn=>fn?.());}}};
}

test('place search entry validates metadata and carries only original ID, never coordinates or snapshots',()=>{
  const value=assistant.readAssistantSearch(page([match({coordinates:{latitude:1,longitude:2},owner:'PRIVATE'})])).matches[0];
  assert(!('coordinates' in value));assert(!('owner' in value));
  assert.deepEqual(clone(assistant.assistantContentRequest(value,2)),{kind:'places',id:photoId,key:2});
  for(const patch of [{id:'../place'},{revision:0},{journey:{id:'bad'}},{visibility:'public'}])assert.throws(()=>assistant.readAssistantSearch(page([match(patch)])));
  assert.equal(assistant.assistantContentRequest(match({id:'bad'}),1),null);
});

test('actual assistant page two opens off-page original place, nested trip/photos return to map and original search',async t=>{
  const matches=Array.from({length:21},(_,i)=>match({id:i===20?photoId:(i+1).toString(16).padStart(24,'0'),title:i===20?'第21个地点':'地点'+i}));
  const h=harness({matches});t.after(h.close);await h.search();await h.click('下一页');await h.click('查看地点 第21个地点');
  assert(h.text().includes('当前地点名称'));assert(!h.text().includes('旧地点快照'));
  const map=h.nodes().find(n=>n.type==='WorldMap');assert.equal(map.props.selected,photoId);assert.equal(map.props.places.length,25);assert.equal(map.props.places.at(-1).revision,3);
  await h.click('查看旅行');let panel=h.nodes().find(n=>n.type==='UnusedPanel');assert.equal(panel.props.tripRequest.id,tripId);await h.returnNested();
  assert(h.text().includes('当前地点名称'));await h.click('查看旅行照片');panel=h.nodes().find(n=>n.type==='UnusedPanel');assert.equal(panel.props.journeyId,journeyId);await h.returnNested();
  await h.click('返回地点搜索');assert.equal(h.control('告诉助理你的需求')[0].props.value,'搜索：凭证');assert.match(h.text(),/第\s+2\s+页/);
  assert.equal(h.f.calls.filter(p=>p==='/assistant/search?q=%E5%87%AD%E8%AF%81&limit=20&offset=20').length,2);
  assert(h.f.calls.filter(p=>p==='/journey-places/'+photoId).length>=5);assert.equal(h.f.mutations.length,1);
});

test('owned edit uses freshly fetched original revision rather than search revision',async t=>{
  const h=harness();t.after(h.close);await h.search();await h.click('查看地点 旧地点快照');await h.click('编辑地点');
  await h.input('地点名称','明确更正后的地点');await h.click('保存地点');
  const write=h.f.mutations.find(x=>x.method==='PATCH');assert.equal(write.path,'/journey-places/'+photoId);assert.equal(write.body.revision,3);assert.equal(write.body.name,'明确更正后的地点');assert.equal(h.f.place.revision,4);
});

test('shared off-page place keeps projected coordinates and read-only management',async t=>{
  const h=harness({place:clonePlace({owner:'bob',visibility:'shared',canManage:false,coordinatePrecision:'approximate',coordinateDisclosure:'coarse',coordinateGridDegrees:.1})});t.after(h.close);
  await h.search();await h.click('查看地点 旧地点快照');assert(h.text().includes('大致位置'));assert.equal(h.control('编辑地点').length,0);assert.equal(h.control('删除地点').length,0);
});

test('unavailable original target clears detail but keeps a usable return to original search',async t=>{
  const h=harness({placeStatus:404});t.after(h.close);await h.search();await h.click('查看地点 旧地点快照');
  assert(!h.text().includes('当前地点名称'));assert(h.text().includes('不再对你可见'));h.f.matches=[];await h.click('返回地点搜索');assert(h.text().includes('没有找到当前可见'));
});

test('permission polling removes revoked detail/coordinates and nested navigation',async t=>{
  const h=harness();t.after(h.close);await h.search();await h.click('查看地点 旧地点快照');h.f.placeStatus=404;await h.tick();
  assert(!h.text().includes('当前地点名称'));assert.equal(h.control('查看旅行').length,0);assert(!h.nodes().some(n=>n.type==='WorldMap'&&n.props.places.some(p=>p.id===photoId)));
});

test('late original-place response after identity switch cannot reveal old detail or return-state',async t=>{
  const h=harness();t.after(h.close);await h.search();const gate=deferred();h.f.gate={path:'/journey-places/'+photoId,...gate};await h.click('查看地点 旧地点快照');
  await h.switchMember();gate.release();await h.flush();assert(!h.text().includes('当前地点名称'));assert(!h.text().includes('旧地点快照'));assert.equal(h.control('告诉助理你的需求')[0].props.value,'');
});

test('offline conceals private target; same-identity recovery freshly reads the original',async t=>{
  const h=harness();t.after(h.close);await h.search();await h.click('查看地点 旧地点快照');await h.offline();assert(!h.text().includes('当前地点名称'));
  h.f.place=clonePlace({name:'恢复后当前地点',revision:4});await h.online();assert(h.text().includes('恢复后当前地点'));assert(!h.text().includes('当前地点名称'));
});

test('fresh unlinked place does not open stale search journey',async t=>{
  const h=harness({place:clonePlace({journey:null,journeyId:null})});t.after(h.close);await h.search();await h.click('查看地点 旧地点快照');
  assert(h.text().includes('尚未关联旅行'));assert.equal(h.control('查看旅行').length,0);assert.equal(h.control('查看旅行照片').length,0);
});
