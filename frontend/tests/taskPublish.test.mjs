import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readFileSync,existsSync} from 'node:fs';
import {createRequire} from 'node:module';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {runInNewContext} from 'node:vm';
const require=createRequire(import.meta.url),ts=require('typescript'),root=resolve(dirname(fileURLToPath(import.meta.url)),'../src');
const clone=value=>JSON.parse(JSON.stringify(value));
function loader(mocks={},globals={}){
  const cache=new Map();
  function load(path){
    path=resolve(path);if(!existsSync(path))path+=existsSync(path+'.ts')?'.ts':'.tsx';
    if(cache.has(path))return cache.get(path);const exports={};cache.set(path,exports);
    const code=ts.transpileModule(readFileSync(path,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText;
    runInNewContext(code,{exports,require:name=>name in mocks?mocks[name]:load(resolve(dirname(path),name)),Date,Intl,Error,encodeURIComponent,...globals});return exports;
  }return load;
}
const lib=loader()(resolve(root,'lib/taskPublish.ts'));
const task=(id='task1')=>({id,revision:1,title:id==='task1'?'核对护照':'整理行李',owner:'alice',tripId:'trip1',journeyId:'journey1',due:'2027-09-28',note:'合成备注',done:false});
const source=(id='source1')=>({id,name:id==='source1'?'家庭主清单':'本人清单',provider:'microsoft',accountName:'合成账户',accountOwner:'alice',primary:id==='source1',writeAuthorized:true});
const publication=(status='published',id='task1')=>({id:'publication-'+id,entityId:id,sourceId:'source1',provider:'microsoft',status,error:'',owner:'alice',accountOwner:'alice',updatedAt:'2026-09-20T00:00:00Z',canManage:true,localChangesPending:false,reconnectSourceIds:[]});
const state=()=>({journeyId:'journey1',tasks:[task(),task('task2')],sources:[source(),source('source2')],publications:[],note:'合成同步说明',intervalSeconds:30});
const preview=(value=state(),ids=['task1'],sid='source1')=>({tasks:value.tasks.filter(row=>ids.includes(row.id)).map(row=>({...row,reconnect:value.publications.some(p=>p.entityId===row.id&&p.status==='disconnected')})),source:value.sources.find(row=>row.id===sid),previewToken:'synthetic-preview',note:'请核对'});

test('real API shape has accountOwner, primary and no calendar accountId; empty trips are allowed',()=>{
  assert.equal(lib.readTaskState(state(),'journey1').sources[0].accountId,undefined);
  const empty=state();empty.tasks=[];empty.sources=[];assert.equal(lib.readTaskState(empty,'journey1').tasks.length,0);
  assert.equal(lib.readTaskPreview(preview(),'source1',['task1'],'journey1').tasks[0].id,'task1');
});
for(const [name,change] of [
  ['wrong journey',s=>s.journeyId='elsewhere'],['foreign task',s=>s.tasks[0].journeyId='elsewhere'],
  ['duplicate task',s=>s.tasks.push(s.tasks[0])],['invalid day',s=>s.tasks[0].due='2027-02-30'],
  ['duplicate publication',s=>s.publications=[publication(),publication()]],
  ['publication outside trip',s=>s.publications=[publication('pending','foreign')]],
  ['invalid management flag',s=>s.publications=[{...publication(),canManage:'yes'}]],
  ['unknown freshness',s=>s.publications=[{...publication(),localChangesPending:undefined}]],
])test('state rejects '+name,()=>{const value=state();change(value);assert.throws(()=>lib.readTaskState(value,'journey1'));});
test('preview requires the exact selected tasks and target; malformed receipts cannot imply accepted work',()=>{
  for(const [target,ids] of [['source2',['task1']],['source1',['task2']],['source1',['task1','task2']]])assert.throws(()=>lib.readTaskPreview(preview(),target,ids,'journey1'));
  assert(!lib.validTaskReceipt({queued:true,publicationIds:['p','p'],needsAuthorization:false},2));
  assert(!lib.validTaskReceipt({queued:true,publicationIds:['p'],needsAuthorization:false},2));
  assert(lib.validTaskReceipt({queued:true,publicationIds:['p'],needsAuthorization:true},1));
});
test('reconnect permits only authorized original targets, never an arbitrary replacement',()=>{
  const value=state();value.publications=[{...publication('disconnected'),reconnectSourceIds:['source2']}];
  assert(!lib.selectableTask(value,'task1','source1'));assert(lib.selectableTask(value,'task1','source2'));
  value.publications[0].canManage=false;assert(!lib.selectableTask(value,'task1','source2'));
  assert(lib.selectableTask(value,'task2','source1'));
});
test('cloud confirmation distinguishes pending local changes; actions honor management and terminal states',()=>{
  assert.match(lib.taskStatus({...publication(),localChangesPending:true}),/等待云端确认/);
  assert.match(lib.taskStatus({...publication(),localChangesPending:null}),/待核对/);
  assert.deepEqual(clone(lib.taskActions({...publication('conflict'),canManage:false})),[]);
  assert.deepEqual(clone(lib.taskActions(publication('remote_deleted'))),[]);
  assert.deepEqual(clone(lib.taskActions(publication('disconnected'))),[]);
  assert.deepEqual(clone(lib.taskActions(publication('conflict'))),['conflict','pause']);
  assert.deepEqual(clone(lib.taskActions(publication('paused'))),['resume']);
});
test('unknown confirmation is observed only for all original tasks and the original target',()=>{
  const value=state(),p=preview(value,['task1','task2']);value.publications=[publication('pending')];assert(!lib.confirmationObserved(value,p));
  value.publications.push(publication('published','task2'));assert(lib.confirmationObserved(value,p));
  value.publications[1].sourceId='source2';assert(!lib.confirmationObserved(value,p));
  value.publications[1].sourceId='source1';value.publications[1].status='disconnected';assert(!lib.confirmationObserved(value,p));
});
test('comparison validates both sides without expecting calendar-only fields',()=>{
  const {title,note,due,done}=task(),content={title,note,due,done};
  assert.equal(lib.readTaskComparison({local:content,remote:content,previewToken:'synthetic'}).remote.due,due);
  assert.throws(()=>lib.readTaskComparison({local:content,remote:null,previewToken:'synthetic'}));
});

// Executes the actual TSX panel and PlaceFence with synthetic HTTP. No DOM,
// backend, real provider, production or model calls are claimed by these tests.
function harness(options={}){
  const f={session:{user:{id:'alice',name:'合成本人',role:'member',householdId:'home',auth_version:1},csrf:'synthetic'},wire:state(),calls:[],pending:[],...options};
  let instance,cursor=0,dirty=true,tree,renderNumber=0;
  const instances=new Map(),effects=[],listeners=new Map(),timers=[];
  const target={addEventListener(name,fn){if(!listeners.has(name))listeners.set(name,new Set());listeners.get(name).add(fn);},removeEventListener(name,fn){listeners.get(name)?.delete(fn);}};
  const document={hidden:false,...target},window={...target},navigator={onLine:true};
  const changed=(a,b)=>!a||!b||a.length!==b.length||a.some((v,i)=>v!==b[i]);
  function useState(value){const holder=instance,i=cursor++;if(!(i in holder.values))holder.values[i]=typeof value==='function'?value():value;return[holder.values[i],next=>{holder.values[i]=typeof next==='function'?next(holder.values[i]):next;dirty=true;}];}
  function useRef(value){const i=cursor++;if(!(i in instance.values))instance.values[i]={current:value};return instance.values[i];}
  function useEffect(fn,deps){const holder=instance,i=cursor++;if(changed(holder.values[i],deps)){holder.values[i]=deps;effects.push(()=>{holder.cleanups[i]?.();holder.cleanups[i]=fn();});}}
  function useCallback(fn,deps){const i=cursor++;if(!instance.values[i]||changed(instance.values[i].deps,deps))instance.values[i]={deps,fn};return instance.values[i].fn;}
  const react={useState,useRef,useEffect,useCallback,Fragment:'Fragment',createElement(type,props,...children){const values=children.length?children:[props?.children];return{type,props:{...props,children:values.flat(Infinity).filter(v=>v!==false&&v!==null&&v!==undefined)}};}};
  class ApiError extends Error{constructor(message,status){super(message);this.status=status;}}
  const identity=loader()(resolve(root,'lib/sessionIdentity.ts'));
  const household={user:f.session.user,identityKey:identity.sessionIdentity(f.session),online:true,state:{people:[f.session.user,{id:'bob',name:'合成同行'}]},refresh:async()=>{f.refreshes=(f.refreshes||0)+1;}};
  const request=async(path,init,csrf)=>{
    const body=init?.body?JSON.parse(init.body):undefined;f.calls.push({path,method:init?.method||'GET',body,csrf});
    if(path==='/me')return clone(f.session);
    if(path.startsWith('/task-publish/state')){if(f.stateGate)await f.stateGate;if(f.stateError)throw new Error('合成读取失败');return clone(f.wire);}
    if(path==='/task-publish/preview'){if(f.previewGate)await f.previewGate;if(f.previewError)throw new Error('合成预览失败');return clone(preview(f.wire,body.entityIds,body.sourceId));}
    if(path==='/task-publish/confirm'){
      if(f.confirmGate)await f.confirmGate;
      const call=f.calls.findLast(row=>row.path==='/task-publish/preview'),ids=call.body.entityIds;
      if(f.commit!==false)f.wire.publications=ids.map(id=>({...publication('pending',id),sourceId:call.body.sourceId}));
      if(f.confirmError)throw new ApiError('合成响应丢失',0);
      return{queued:true,publicationIds:ids.map(id=>'publication-'+id),needsAuthorization:false};
    }
    const match=path.match(/^\/task-publish\/publications\/([^/]+)\/(.+)$/);assert(match,path);
    const row=f.wire.publications.find(row=>row.id===match[1]),action=match[2];assert(row);
    if(action==='conflict-preview')return{local:{title:'本地版本',due:'2027-09-28',done:false,note:'本地备注'},remote:{title:'云端版本',due:'2027-09-29',done:true,note:'云端备注'},previewToken:'synthetic-conflict'};
    if(action==='conflict-confirm'){row.status=body.resolution==='remote'?'published':'pending';return{queued:body.resolution==='local',adopted:body.resolution==='remote'};}
    row.status=action==='pause'?'paused':'pending';if(f.actionError)throw new ApiError('合成未知操作',0);return action==='pause'?{paused:true}:{queued:true};
  };
  const mocks={react,'react-native':{View:'View',StyleSheet:{create:x=>x},AppState:{currentState:'active',addEventListener:()=>({remove(){}})}},
    'react-native-paper':Object.fromEntries(['ActivityIndicator','Button','Divider','Searchbar','Text'].map(name=>[name,name])),
    'expo-router':{useFocusEffect:fn=>useEffect(fn,[fn])},'../lib/api':{ApiError,request},'../lib/household':{useHousehold:()=>household},
    '../ui/components':{PageHeader:'PageHeader',SectionCard:'SectionCard'},'../ui/SelectionRow':{SelectionRow:'SelectionRow'}};
  const Panel=loader(mocks,{document,window,navigator,setInterval:fn=>{timers.push(fn);return timers.length;},clearInterval:()=>{}})(resolve(root,'screens/JourneyTasksPanel.tsx')).default;
  const props={journeyId:'journey1',onBack:()=>{f.back=true;},onConnections:()=>{f.connections=true;},onPendingChange:value=>f.pending.push(value)};
  function expand(node,path='0'){
    if(node===null||node===false||node===undefined)return null;if(typeof node!=='object')return node;if(Array.isArray(node))return node.map((n,i)=>expand(n,path+'.'+i));
    if(typeof node.type==='function'){
      const key=path+':'+node.type.name+':'+(node.props.key||'');if(!instances.has(key))instances.set(key,{values:[],cleanups:[]});
      const previous=instance,oldCursor=cursor;instance=instances.get(key);instance.seen=renderNumber;cursor=0;const result=node.type(node.props);instance=previous;cursor=oldCursor;return expand(result,key);
    }return{...node,props:{...node.props,action:node.props.action?expand(node.props.action,path+'.action'):undefined,children:(node.props.children||[]).map((n,i)=>expand(n,path+'.'+(n?.props?.key||i)))}};
  }
  function render(){dirty=false;renderNumber++;tree=expand(react.createElement(Panel,props));for(const[key,row]of instances)if(row.seen!==renderNumber){row.cleanups.forEach(fn=>fn?.());instances.delete(key);}while(effects.length)effects.shift()();}
  async function flush(){for(let i=0;i<20;i++){if(dirty)render();await new Promise(setImmediate);}if(dirty)render();}
  function nodes(value){if(!value||typeof value!=='object')return[];if(Array.isArray(value))return value.flatMap(nodes);return[value,...nodes(value.props.action),...nodes(value.props.children)];}
  function content(value){if(typeof value==='string'||typeof value==='number')return String(value);if(!value)return'';if(Array.isArray(value))return value.map(content).join(' ');return content(value.props.children);}
  const find=label=>{const matches=nodes(tree).filter(node=>(node.props.accessibilityLabel||content(node.props.children)).replace(/\s+/g,' ').trim()===label&&node.props.onPress);assert.equal(matches.length,1,label);return matches[0];};
  return{f,flush,text:()=>content(tree),disabled:label=>!!find(label).props.disabled,selected:label=>find(label).props.checked,
    async click(label){const node=find(label);assert(!node.props.disabled,label+' disabled');node.props.onPress();await flush();},
    async hide(hidden){document.hidden=hidden;for(const fn of listeners.get('visibilitychange')||[])fn();await flush();},
    async offline(value){navigator.onLine=!value;for(const fn of listeners.get(value?'offline':'online')||[])fn();await flush();},
    async cookieOnly(){f.session={...f.session,user:{...f.session.user,id:'bob'}};},
    async replaceMember(){f.session={...f.session,user:{...f.session.user,id:'bob'}};household.user=f.session.user;household.identityKey=identity.sessionIdentity(f.session);dirty=true;await flush();},
    async tick(){for(const fn of timers)fn();await flush();}};
}
async function selectAndPreview(h){await h.flush();await h.click('选择清单：Microsoft To Do · 家庭主清单 · 合成账户');await h.click('选择待办：核对护照');await h.click('预览选中待办');}
test('actual panel selects original tasks, previews complete content, confirms and returns to the trip',async()=>{
  const h=harness();await selectAndPreview(h);assert(h.text().includes('合成备注'));assert(h.text().includes('看板负责人： 合成本人'));
  assert(!h.f.calls.some(row=>row.path.endsWith('/confirm')));await h.click('确认连接这 1 项待办');assert(h.text().includes('等待同步'));assert(!h.text().includes('采用云端内容'));
  assert.deepEqual(h.f.calls.find(row=>row.path.endsWith('/preview')).body,{sourceId:'source1',entityIds:['task1']});
  assert.equal(h.f.calls.find(row=>row.path.endsWith('/confirm')).body.previewToken,'synthetic-preview');await h.click('返回旅行');assert(h.f.back);
});
test('failed preview retains selection; no selected task is silently defaulted or duplicated',async()=>{
  const h=harness({previewError:true});await selectAndPreview(h);assert(h.text().includes('合成预览失败'));assert(h.selected('选择待办：核对护照'));assert(!h.selected('选择待办：整理行李'));
  assert(!h.f.calls.some(row=>row.path.endsWith('/confirm')));h.f.previewError=false;await h.click('预览选中待办');assert(h.text().includes('确认连接这'));
});
test('lost confirmation response recovers original binding by read only',async()=>{
  const h=harness({confirmError:true});await selectAndPreview(h);await h.click('确认连接这 1 项待办');assert(h.text().includes('先核对当前状态'));assert(h.disabled('取消本页选择并返回旅行'));
  await h.click('核对当前状态');assert(h.text().includes('已找到刚才所选待办'));assert.equal(h.f.calls.filter(row=>row.path.endsWith('/confirm')).length,1);
});
test('unobserved confirmation cannot retry before a fresh read and reuses the exact original credential',async()=>{
  const h=harness({confirmError:true,commit:false});await selectAndPreview(h);await h.click('确认连接这 1 项待办');assert(!h.text().includes('使用原确认再次核对'));
  await h.click('核对当前状态');h.f.commit=true;h.f.confirmError=false;await h.click('使用原确认再次核对');
  const calls=h.f.calls.filter(row=>row.path.endsWith('/confirm'));assert.equal(calls.length,2);assert.deepEqual(calls[0].body,calls[1].body);assert(h.text().includes('等待同步'));
});
for(const resolution of ['local','remote'])test('actual conflict '+resolution+' sends explicit resolution and preserves original publication',async()=>{
  const wire=state();wire.publications=[publication('conflict')];const h=harness({wire});await h.flush();await h.click('对比并处理');assert(h.text().includes('本地备注'));assert(h.text().includes('云端备注'));
  await h.click(resolution==='remote'?'采用云端内容':'确认以本地更新云端');
  assert.deepEqual(h.f.calls.find(row=>row.path.endsWith('/conflict-confirm')).body,{previewToken:'synthetic-conflict',resolution});assert.equal(h.f.wire.publications[0].entityId,'task1');
});
test('pause, resume and uncertain retry use existing publication paths',async()=>{
  const wire=state();wire.publications=[publication()];const h=harness({wire});await h.flush();await h.click('暂停同步');assert(h.text().includes('已暂停同步'));await h.click('恢复同步');assert(h.text().includes('等待同步'));
  h.f.wire.publications[0].status='uncertain';await h.click('刷新状态');await h.click('再次核对原清单');assert(h.f.calls.some(row=>row.path.endsWith('/retry')));
});
test('a periodic state read disables writes until it completes, then resume sends once',async()=>{
  const wire=state();wire.publications=[publication('paused')];const h=harness({wire});await h.flush();
  let release;h.f.stateGate=new Promise(resolve=>{release=resolve;});await h.tick();
  assert(h.disabled('恢复同步'),'Visible resume must not silently discard a click during background polling');
  assert(!h.f.calls.some(row=>row.path.endsWith('/resume')));
  release();await h.flush();assert(!h.disabled('恢复同步'));await h.click('恢复同步');
  assert.equal(h.f.calls.filter(row=>row.path.endsWith('/resume')).length,1);assert(h.text().includes('等待同步'));
});
test('unknown confirmation retry remains disabled during a later background read',async()=>{
  const h=harness({confirmError:true,commit:false});await selectAndPreview(h);await h.click('确认连接这 1 项待办');
  await h.click('核对当前状态');let release;h.f.stateGate=new Promise(resolve=>{release=resolve;});await h.tick();
  assert(h.disabled('使用原确认再次核对'));assert(h.disabled('核对当前状态'));
  release();await h.flush();h.f.commit=true;h.f.confirmError=false;await h.click('使用原确认再次核对');
  const calls=h.f.calls.filter(row=>row.path.endsWith('/confirm'));assert.equal(calls.length,2);assert.deepEqual(calls[0].body,calls[1].body);
});
test('reconnection selects only original matching source, and preview makes reuse visible',async()=>{
  const wire=state();wire.publications=[{...publication('disconnected'),reconnectSourceIds:['source2']}];const h=harness({wire});await h.flush();await h.click('选择清单：Microsoft To Do · 家庭主清单 · 合成账户');assert(h.disabled('选择待办：核对护照'));
  await h.click('选择清单：Microsoft To Do · 本人清单 · 合成账户');assert(!h.disabled('选择待办：核对护照'));await h.click('选择待办：核对护照');await h.click('预览选中待办');assert.equal(h.f.calls.find(row=>row.path.endsWith('/preview')).body.sourceId,'source2');assert(h.text().includes('重新连接原清单，保留云端原任务'));
});
test('background/offline hides content and keeps same-identity selection after a fresh read',async()=>{
  const h=harness();await h.flush();await h.click('选择清单：Microsoft To Do · 家庭主清单 · 合成账户');await h.click('选择待办：核对护照');await h.hide(true);assert(!h.text().includes('合成备注'));assert(!h.text().includes('核对护照'));
  await h.hide(false);assert(h.selected('选择待办：核对护照'));await h.offline(true);assert(!h.text().includes('核对护照'));await h.offline(false);assert(h.selected('选择待办：核对护照'));
});
test('late preview after a cookie-only member change is discarded and private draft clears',async()=>{
  const h=harness();await h.flush();await h.click('选择清单：Microsoft To Do · 家庭主清单 · 合成账户');await h.click('选择待办：核对护照');let release;h.f.previewGate=new Promise(resolve=>{release=resolve;});await h.click('预览选中待办');await h.cookieOnly();release();await h.flush();
  assert(!h.text().includes('合成备注'));assert(!h.text().includes('确认连接这'));assert(h.text().includes('登录身份已变化'));assert(!h.disabled('返回旅行'));assert(!h.f.calls.some(row=>row.path.endsWith('/confirm')));
});
test('late preview while hidden never reopens preview; foreground recovers by read only',async()=>{
  const h=harness();await h.flush();await h.click('选择清单：Microsoft To Do · 家庭主清单 · 合成账户');await h.click('选择待办：核对护照');let release;h.f.previewGate=new Promise(resolve=>{release=resolve;});await h.click('预览选中待办');await h.hide(true);release();await h.flush();assert(!h.text().includes('确认连接这'));await h.hide(false);
  assert(h.selected('选择待办：核对护照'));assert(!h.text().includes('确认连接这'));assert(!h.disabled('预览选中待办'));
});
test('returning while an old state read is in flight eventually recovers without a stuck loading screen',async()=>{
  let release;const gate=new Promise(resolve=>{release=resolve;});const h=harness({stateGate:gate});await h.flush();await h.hide(true);await h.hide(false);release();await h.flush();
  assert(!h.disabled('选择清单：Microsoft To Do · 家庭主清单 · 合成账户'));await h.click('选择清单：Microsoft To Do · 家庭主清单 · 合成账户');assert(!h.disabled('选择待办：核对护照'));assert(!h.f.calls.some(row=>row.method==='POST'));
});
test('unknown management action must be read and acknowledged; it is never silently repeated',async()=>{
  const wire=state();wire.publications=[publication()];const h=harness({wire,actionError:true});await h.flush();await h.click('暂停同步');assert(!h.text().includes('已核对，保留当前状态'));
  await h.click('核对当前状态');assert(h.text().includes('已暂停同步'));await h.click('已核对，保留当前状态');
  assert.equal(h.f.calls.filter(row=>row.path.endsWith('/pause')).length,1);assert(!h.disabled('恢复同步'));
});
test('source revocation preserves visible choices but blocks another preview until explicitly corrected',async()=>{
  const h=harness();await h.flush();await h.click('选择清单：Microsoft To Do · 家庭主清单 · 合成账户');await h.click('选择待办：核对护照');h.f.wire.sources=[];await h.click('刷新状态');assert(!h.f.calls.some(row=>row.path.endsWith('/preview')));assert(h.f.pending.at(-1));
});
test('read-only publication shows no management actions and source authorization is explicit in preview',async()=>{
  const wire=state();wire.publications=[{...publication('conflict'),canManage:false}];wire.sources[0].writeAuthorized=false;const h=harness({wire});await h.flush();assert(h.text().includes('由确认成员或账户拥有者管理'));assert(!h.text().includes('对比并处理'));
  await h.click('选择清单：Microsoft To Do · 家庭主清单 · 合成账户');await h.click('选择待办：整理行李');await h.click('预览选中待办');assert(h.text().includes('账户尚缺待办写入权限'));assert(!h.f.calls.some(row=>row.path.endsWith('/confirm')));
});
