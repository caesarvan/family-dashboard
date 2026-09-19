import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readFileSync,existsSync} from 'node:fs';
import {createRequire} from 'node:module';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {runInNewContext} from 'node:vm';
import {webcrypto} from 'node:crypto';
const ts=createRequire(import.meta.url)('typescript'),root=resolve(dirname(fileURLToPath(import.meta.url)),'../src');
const clone=v=>JSON.parse(JSON.stringify(v));
function loader(mocks={},globals={}){
  const cache=new Map();function load(path){path=resolve(path);if(!existsSync(path))path+=existsSync(path+'.ts')?'.ts':'.tsx';if(cache.has(path))return cache.get(path);
    const exports={};cache.set(path,exports);const code=ts.transpileModule(readFileSync(path,'utf8'),{fileName:path,compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText;
    runInNewContext(code,{exports,require:n=>n in mocks?mocks[n]:load(resolve(dirname(path),n)),Date,Intl,Error,URLSearchParams,TextEncoder,crypto:webcrypto,Uint8Array,process:{env:{}},...globals});return exports;
  }return load;
}
const helpers=loader(),api=helpers(resolve(root,'lib/api.ts')),identity=helpers(resolve(root,'lib/sessionIdentity.ts')),lib=helpers(resolve(root,'lib/taskReminders.ts'));
const NOW='2026-09-20T02:00:00Z';
const task=(i=1,patch={})=>({id:i.toString(16).padStart(24,'0'),title:'合成提醒 '+i,owner:'alice',due:'2026-09-20',revision:4,done:false,note:'当前真实备注',dependsOn:[],blockedBy:[],dependencyStatus:'ready',...patch});
const row=(i=1,patch={})=>({task:task(i),occurrence:i.toString(16).padStart(64,'0'),revision:0,eligibleAt:'2026-09-20T01:00:00Z',status:'unread',readAt:null,snoozedUntil:null,...patch});
const page=(rows,number=0)=>({items:rows.slice(number*40,number*40+40),total:rows.length,unreadCount:rows.filter(r=>r.status==='unread').length,page:number,pageSize:40,hasMore:(number+1)*40<rows.length,serverNow:NOW,timeZone:'Asia/Shanghai',worker:{lastCheckedAt:null,stale:false}});
const session=()=>({user:{id:'alice',role:'member',householdId:'home',name:'合成本人',auth_version:1,membershipRevision:1},csrf:'synthetic-csrf'});
class MemoryStorage{values=new Map();blocked=false;getItem(k){if(this.blocked)throw Error('storage blocked');return this.values.get(k)||null;}setItem(k,v){if(this.blocked)throw Error('storage blocked');this.values.set(k,v);}removeItem(k){this.values.delete(k);}}
const deferred=()=>{let release;return{promise:new Promise(r=>{release=r;}),release:()=>release()};};

test('wire page accepts expired snooze as unread and rejects wrong actor, page, duplicate and false status',()=>{
  assert.equal(lib.readReminderPage(page([row(1,{snoozedUntil:'2026-09-20T01:30:00Z'})]),'unread',0,'alice').items[0].status,'unread');
  for(const value of [page([row(1,{task:task(1,{owner:'bob'})})]),page([row(1),row(1)]),{...page([row()]),page:1},{...page([row()]),pageSize:99},page([row(1,{status:'snoozed',snoozedUntil:'2026-09-20T01:30:00Z'})])])assert.throws(()=>lib.readReminderPage(value,'unread',0,'alice'));
});
test('snooze uses the frozen server clock, Shanghai next09 across year and exact receipt intent',()=>{
  assert.equal(lib.snoozeTime('2026-12-31T20:00:00Z','tomorrow'),'2027-01-02T01:00:00.000Z');
  const i=lib.reminderIntent(row(),'snooze',NOW);assert.equal(i.snoozedUntil,'2026-09-20T03:00:00.000Z');assert.match(i.requestId,/^[a-f0-9]{32}$/);
  const operation={...i,revision:1,readAt:null,snoozedUntil:i.snoozedUntil,committedAt:NOW};assert.equal(lib.readReminderOperation({operation},i).revision,1);
  for(const patch of [{taskId:'different'},{revision:0},{snoozedUntil:'2026-09-20T04:00:00Z'},{requestId:'a'.repeat(32)}])assert.throws(()=>lib.readReminderOperation({operation:{...operation,...patch}},i));
});

test('cloud titles retain the provider 2048 Unicode code point boundary including non-BMP',()=>{
  for(const title of ['合'.repeat(101),'A'.repeat(2048),'🧭'.repeat(2048)]){
    const value=page([row(1,{task:task(1,{title,sync:{provider:'microsoft'}})})]);
    assert.equal(lib.readReminderPage(value,'unread',0,'alice').items[0].task.title,title);
  }
  for(const title of ['', 'A'.repeat(2049),'🧭'.repeat(2049)])assert.throws(()=>lib.readReminderPage(page([row(1,{task:task(1,{title})})]),'unread',0,'alice'));
});
test('minimal durable envelope excludes title/CSRF, preserves exact retry and clears only confirmed foreign scope',async()=>{
  const store=new MemoryStorage(),l=loader({}, {sessionStorage:store})(resolve(root,'lib/taskReminders.ts')),scope=await l.reminderScope(identity.sessionIdentity(session()));
  const intent=l.reminderIntent(row(),'snooze',NOW,'tomorrow'),value={intent,filter:'all',page:2};l.saveReminderRecovery(scope,value);
  const raw=[...store.values.values()][0];assert(!raw.includes('合成提醒'));assert(!raw.includes('csrf'));assert.deepEqual(clone(l.loadReminderRecovery(scope)),clone(value));
  l.clearReminderRecovery('b'.repeat(64));assert.equal(store.values.size,1);assert.equal(l.loadReminderRecovery('c'.repeat(64)),null);assert.equal(store.values.size,0);
});

// Actual reminder component and PlaceFence; native/Paper hosts and HTTP only are
// synthetic. These tests do not claim browser, Flask or provider acceptance.
function harness(options={}){
  const storage=options.storage||new MemoryStorage(),f={session:session(),rows:[row()],operations:new Map(),calls:[],writes:[],opened:[],...options};
  const household={user:f.session.user,identityKey:identity.sessionIdentity(f.session),online:true,state:{revision:1},refresh:async()=>{f.refreshes=(f.refreshes||0)+1;}};
  const listeners=new Map(),timers=new Map();let serial=0,holder,cursor=0,dirty=true,tree,closed=false;
  const instances=new Map(),types=new Map(),effects=[];
  const events={addEventListener(k,fn){if(!listeners.has(k))listeners.set(k,new Set());listeners.get(k).add(fn);},removeEventListener(k,fn){listeners.get(k)?.delete(fn);}};
  const document={hidden:false,...events},window={...events},navigator={onLine:true};
  const useEffect=(fn,deps)=>{const h=holder,i=cursor++,old=h.values[i];if(!old||!deps||deps.some((v,n)=>v!==old[n])){h.values[i]=deps;effects.push(()=>{h.cleanups[i]?.();if(!h.dead)h.cleanups[i]=fn();});}};
  const react={createElement:(type,props,...children)=>({type,props:{...props,children:children.flat(Infinity).filter(v=>v!==false&&v!=null)}}),Fragment:'Fragment',
    useState(initial){const h=holder,i=cursor++;if(!(i in h.values))h.values[i]=typeof initial==='function'?initial():initial;return[h.values[i],v=>{if(!h.dead){h.values[i]=typeof v==='function'?v(h.values[i]):v;dirty=true;}}];},
    useRef(value){const i=cursor++;return holder.values[i]||=( {current:value});},useEffect,useCallback(fn,deps){const i=cursor++,old=holder.values[i];if(!old||deps.some((v,n)=>v!==old.deps[n]))holder.values[i]={fn,deps};return holder.values[i].fn;}};
  async function request(path,opts={},csrf){
    f.calls.push({path,method:opts.method||'GET'});
    if(path==='/me'){if(f.meGate)await f.meGate.promise;if(f.meStatus)throw new api.ApiError('身份失效',f.meStatus);return clone(f.session);}
    if(path==='/state'){if(f.stateGate)await f.stateGate.promise;return{tasks:clone(f.liveTasks??f.rows.map(r=>({...r.task,done:false,note:'最新备注',revision:7}))) };}
    if(path.startsWith('/task-reminders/operations/')){if(f.receiptGate)await f.receiptGate.promise;const id=path.split('/').at(-1);if(!f.operations.has(id))throw new api.ApiError('未找到',404);return{operation:clone(f.operations.get(id))};}
    if(opts.method==='POST'){
      assert.equal(csrf,f.session.csrf);assert.match(path,/^\/task-reminders\/[^/]+\/actions$/);const body=JSON.parse(opts.body),taskId=decodeURIComponent(path.split('/')[2]);f.writes.push({path,body:clone(body)});
      if(f.postGate)await f.postGate.promise;
      if(f.reject)throw new api.ApiError('合成拒绝',f.reject,f.rejectCode||'reminder_stale');
      if(!f.noCommit){
        if(!f.operations.has(body.requestId)){const operation={...body,taskId,revision:body.revision+1,readAt:body.action==='read'?NOW:null,snoozedUntil:body.snoozedUntil||null,committedAt:NOW};f.operations.set(body.requestId,operation);
          const target=f.rows.find(r=>r.task.id===taskId);if(target)Object.assign(target,{revision:operation.revision,status:body.action==='read'?'read':'snoozed',readAt:operation.readAt,snoozedUntil:operation.snoozedUntil});}
      }
      if(f.postFault!==undefined)throw new api.ApiError('合成连接中断',f.postFault);
      if(f.afterPostMeStatus)f.meStatus=f.afterPostMeStatus;
      return{operation:clone(f.operations.get(body.requestId))};
    }
    if(path.startsWith('/task-reminders?')){
      if(f.listGate)await f.listGate.promise;if(f.listStatus)throw new api.ApiError('合成读取失败',f.listStatus);
      const q=new URLSearchParams(path.split('?')[1]),rows=f.rows.filter(r=>['shared',f.session.user.id].includes(r.task.owner)&&(q.get('filter')!=='unread'||r.status==='unread'));
      const result=page(rows,Number(q.get('page')));result.unreadCount=f.rows.filter(r=>r.status==='unread').length;return clone(result);
    }
    throw Error('unexpected '+path);
  }
  const paper=Object.fromEntries(['ActivityIndicator','Button','Divider','SegmentedButtons','Text'].map(n=>[n,n]));
  const mocks={react,'react-native':{View:'View',StyleSheet:{create:v=>v},AppState:{currentState:'active',addEventListener:(k,fn)=>{events.addEventListener('app',fn);return{remove:()=>events.removeEventListener('app',fn)};}}},'react-native-paper':paper,'expo-router':{useFocusEffect:fn=>useEffect(fn,[fn])},'../lib/household':{useHousehold:()=>household},'../lib/api':{...api,request},'./components':{EmptyState:'EmptyState',PageHeader:'PageHeader',SectionCard:'SectionCard'}};
  const load=loader(mocks,{document,window,navigator,sessionStorage:storage,setInterval:fn=>{const n=++serial;timers.set(n,fn);return n;},clearInterval:n=>timers.delete(n)}),Panel=load(resolve(root,'ui/TaskRemindersPanel.tsx')).default;
  function expand(n,path,seen){if(!n||typeof n!=='object')return n;if(Array.isArray(n))return n.map((c,i)=>expand(c,path+'.'+i,seen));if(typeof n.type==='function'){
    if(!types.has(n.type))types.set(n.type,types.size+1);const key=path+':'+types.get(n.type)+':'+(n.props.key??'');seen.add(key);if(!instances.has(key))instances.set(key,{values:[],cleanups:[],dead:false});holder=instances.get(key);cursor=0;return expand(n.type(n.props),key,seen);
  }return{...n,props:{...n.props,action:expand(n.props.action,path+'.action',seen),children:n.props.children.map((c,i)=>expand(c,path+'.'+(c?.props?.key??i),seen))}};}
  async function flush(){for(let i=0;i<45;i++){if(dirty&&!closed){dirty=false;const seen=new Set();tree=expand(react.createElement(Panel,{onBack:()=>{f.back=true;},onOpenTask:t=>f.opened.push(clone(t))}),'root',seen);for(const[k,h]of instances)if(!seen.has(k)){h.dead=true;h.cleanups.forEach(fn=>fn?.());instances.delete(k);}while(effects.length)effects.shift()();}await new Promise(setImmediate);}assert(!dirty||closed);}
  const nodes=(n=tree)=>!n||typeof n!=='object'?[]:Array.isArray(n)?n.flatMap(x=>nodes(x)):[n,...nodes(n.props.action??null),...nodes(n.props.children??null)];
  const text=(n=tree)=>n==null||n===false?'':typeof n!=='object'?String(n):Array.isArray(n)?n.map(x=>text(x)).join(' '):[n.props.title||'',n.props.description||'',text(n.props.action??null),text(n.props.children)].join(' ');
  const controls=label=>nodes().filter(n=>(n.props.accessibilityLabel||text(n).trim().replace(/\s+/g,' '))===label&&n.props.onPress);
  async function ready(){const end=Date.now()+3000;do{await flush();if(!nodes().some(n=>n.type==='ActivityIndicator'))return;await new Promise(r=>setTimeout(r,2));}while(Date.now()<end);assert.fail('initial async read did not settle: '+text());}
  return{f,storage,household,flush,ready,text,controls,async click(label,index=0){const p=controls(label)[index]?.props;assert(p,label+'\n'+text());assert(!p.disabled,label+' disabled');p.onPress();await flush();},
    async filter(value){const n=nodes().find(n=>n.type==='SegmentedButtons');assert(n);assert(!n.props.buttons.some(b=>b.disabled),text());n.props.onValueChange(value);await flush();},
    async tick(){for(const fn of [...timers.values()])fn();await flush();},
    async offline(){household.online=false;navigator.onLine=false;for(const fn of [...(listeners.get('offline')||[])])fn();dirty=true;await flush();},
    async online(){household.online=true;navigator.onLine=true;for(const fn of [...(listeners.get('online')||[])])fn();dirty=true;await flush();},
    async switchMember(){f.session={user:{...f.session.user,id:'bob'},csrf:'different-session'};household.user=f.session.user;household.identityKey=identity.sessionIdentity(f.session);dirty=true;await flush();},
    close(){closed=true;for(const h of instances.values()){h.dead=true;h.cleanups.forEach(fn=>fn?.());}}};
}
test('real panel read affects only reminder and confirms via exact receipt',async t=>{
  const h=harness();t.after(h.close);await h.ready();await h.click('标为已读');assert.equal(h.f.writes.length,1);assert.equal(h.f.writes[0].body.action,'read');assert(!('done' in h.f.writes[0].body));assert.equal(h.storage.values.size,0);assert.match(h.text(),/这次提醒操作已确认/);assert.equal(h.f.rows[0].task.done,false);
});
for(const fault of [0,503])test('unknown result survives actual component remount and receipt-first recovery without repeated write '+fault,async t=>{
  const h=harness({postFault:fault});await h.ready();await h.click('1 小时后提醒');assert.equal(h.f.writes.length,1);assert.match(h.text(),/操作待核对/);const original=clone(h.f.writes[0].body);h.close();
  const restored=harness({storage:h.storage,operations:h.f.operations,rows:h.f.rows});t.after(restored.close);await restored.ready();assert.equal(restored.f.writes.length,0);assert(restored.f.calls.some(c=>c.path.endsWith(original.requestId)));assert.equal(restored.storage.values.size,0);assert.match(restored.text(),/已确认/);
});
test('receipt404 allows only explicit same-intent retry and never extends snooze',async t=>{
  const h=harness({postFault:503,noCommit:true});t.after(h.close);await h.ready();await h.click('明天 09:00 提醒');const original=clone(h.f.writes[0].body);await h.click('核对操作结果');await h.tick();assert.equal(h.f.writes.length,1);assert.equal(h.controls('重试原操作').length,1);
  h.f.noCommit=false;delete h.f.postFault;await h.click('重试原操作');assert.equal(h.f.writes.length,2);assert.deepEqual(h.f.writes[1].body,original);assert.equal(h.f.operations.size,1);assert.equal(h.storage.values.size,0);
});

for(const status of [429,404])test('committed POST with failed post-action identity check retains intent until receipt '+status,async t=>{
  const h=harness({afterPostMeStatus:status});t.after(h.close);await h.ready();await h.click('1 小时后提醒');
  assert.equal(h.f.writes.length,1);assert.equal(h.f.operations.size,1);assert.equal(h.storage.values.size,1);
  const original=[...h.storage.values.values()][0],requestId=h.f.writes[0].body.requestId;
  assert.equal(JSON.parse(original).recovery.intent.requestId,requestId);assert.match(h.text(),/操作待核对/);assert(!h.text().includes('这次操作未保存'));
  await h.tick();assert.equal(h.f.writes.length,1);assert.equal([...h.storage.values.values()][0],original);
  delete h.f.meStatus;await h.click('核对操作结果');
  assert.equal(h.f.writes.length,1);assert(h.f.calls.some(c=>c.path.endsWith(requestId)));assert.equal(h.storage.values.size,0);assert.match(h.text(),/这次提醒操作已确认/);
});
test('confirmed receipt plus failed list GET retries reads only',async t=>{
  const h=harness({postFault:503});t.after(h.close);await h.ready();await h.click('标为已读');h.f.listStatus=503;await h.click('核对操作结果');assert.equal(h.storage.values.size,0);assert.equal(h.controls('重试原操作').length,0);await h.click('刷新提醒');assert.equal(h.f.writes.length,1);h.f.listStatus=0;await h.click('刷新提醒');assert.equal(h.f.writes.length,1);
});
test('page/filter survive opening the current original task and fresh revision, not reminder snapshot',async t=>{
  const h=harness({rows:Array.from({length:41},(_,i)=>row(i+1))});t.after(h.close);await h.ready();await h.filter('all');await h.click('下一页');await h.click('打开待办');assert.equal(h.f.opened.length,1);assert.equal(h.f.opened[0].id,task(41).id);assert.equal(h.f.opened[0].revision,7);assert.equal(h.f.opened[0].note,'最新备注');assert.match(h.text(),/第\s+2\s+页/);await h.click('刷新提醒');assert.match(h.text(),/第\s+2\s+页/);assert(h.f.calls.at(-2).path.includes('filter=all&page=1'));
});
test('removed or reassigned original task refuses stale editor launch',async t=>{
  const h=harness({liveTasks:[]});t.after(h.close);await h.ready();await h.click('打开待办');assert.equal(h.f.opened.length,0);assert.match(h.text(),/不再属于当前提醒/);
});
test('late original-state response cannot open editor after member switch',async t=>{
  const gate=deferred(),h=harness({stateGate:gate});t.after(h.close);await h.ready();await h.click('打开待办');await h.switchMember();gate.release();await h.flush();assert.equal(h.f.opened.length,0);assert(!h.text().includes('合成提醒 1'));assert.equal(h.storage.values.size,0);
});
test('late action while offline keeps exact intent and reconnect only reads receipt',async t=>{
  const gate=deferred(),h=harness({postGate:gate});t.after(h.close);await h.ready();await h.click('标为已读');await h.offline();gate.release();await h.flush();assert.equal(h.f.writes.length,1);assert.equal(h.storage.values.size,1);assert(!h.text().includes('合成提醒 1'));await h.online();assert.equal(h.f.writes.length,1);assert.equal(h.storage.values.size,0);
});
for(const status of [401,403])test('revoked action authority conceals private content and clears scoped pending '+status,async t=>{
  const h=harness({reject:status});t.after(h.close);await h.ready();await h.click('标为已读');assert.equal(h.storage.values.size,0);assert(!h.text().includes('合成提醒 1'));assert.match(h.text(),/身份或权限已变化/);
});
test('definite capacity conflict clears pending, refreshes and never claims success',async t=>{
  const h=harness({reject:409,rejectCode:'reminder_capacity'});t.after(h.close);await h.ready();await h.click('标为已读');assert.equal(h.storage.values.size,0);assert.match(h.text(),/容量已满/);assert(!h.text().includes('操作已确认'));assert.equal(h.f.rows[0].status,'unread');
});
test('storage denial fails before any write and TV never reads private reminder state',async t=>{
  const storage=new MemoryStorage();storage.blocked=true;const h=harness({storage});t.after(h.close);await h.ready();assert.match(h.text(),/允许此网站存储/);assert.equal(h.f.writes.length,0);
  const s=session();s.user.role='tv';const tv=harness({session:s});t.after(tv.close);await tv.ready();assert.equal(tv.f.calls.length,0);assert.equal(tv.f.writes.length,0);
});
test('unresolved initial identity does not erase a prior pending envelope',async t=>{
  const storage=new MemoryStorage(),l=loader({}, {sessionStorage:storage})(resolve(root,'lib/taskReminders.ts')),scope=await l.reminderScope(identity.sessionIdentity(session()));
  l.saveReminderRecovery(scope,{intent:l.reminderIntent(row(),'read',NOW),filter:'all',page:0});const original=[...storage.values.values()][0];
  const gate=deferred(),h=harness({storage,meGate:gate});t.after(h.close);await h.flush();assert.equal([...storage.values.values()][0],original);assert.equal(h.f.writes.length,0);assert(!h.text().includes('合成提醒 1'));
  gate.release();delete h.f.meGate;await h.ready();assert.equal([...storage.values.values()][0],original);assert.equal(h.controls('重试原操作').length,1);assert.equal(h.f.writes.length,0);
});
test('cloud task opens an honest original-app explanation without pretending to edit snapshot',async t=>{
  const h=harness({rows:[row(1,{task:task(1,{sync:{provider:'microsoft',sourceId:'source'}})})]});t.after(h.close);await h.ready();await h.click('打开待办');assert.equal(h.f.opened.length,0);assert.match(h.text(),/原应用中修改/);assert.equal(h.f.writes.length,0);
});
