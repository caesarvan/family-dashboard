import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readFileSync,existsSync} from 'node:fs';
import {createRequire} from 'node:module';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {runInNewContext} from 'node:vm';
import {webcrypto} from 'node:crypto';

const require=createRequire(import.meta.url),ts=require('typescript'),root=resolve(dirname(fileURLToPath(import.meta.url)),'../src');
const copy=value=>JSON.parse(JSON.stringify(value));
function loader(mocks={},globals={}) {
  const cache=new Map();
  function load(path) {
    path=resolve(path);if(!existsSync(path))path+=existsSync(path+'.ts')?'.ts':'.tsx';
    if(cache.has(path))return cache.get(path);
    const exports={};cache.set(path,exports);
    const code=ts.transpileModule(readFileSync(path,'utf8'),{fileName:path,compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText;
    runInNewContext(code,{exports,require:name=>name in mocks?mocks[name]:load(resolve(dirname(path),name)),Date,Intl,Error,TextEncoder,TextDecoder,AbortController,crypto:webcrypto,encodeURIComponent,...globals});return exports;
  }return load;
}
const load=loader(),trips=load(resolve(root,'lib/trips.ts')),segments=load(resolve(root,'lib/journeySegments.ts')),reschedule=load(resolve(root,'lib/journeyReschedule.ts')),imports=load(resolve(root,'lib/tripImport.ts'));
const journeyId='1'.repeat(24),tripId='2'.repeat(24),purchaseId='3'.repeat(24);
const people=[{id:'alice',name:'合成本人'},{id:'bob',name:'合成同行'}];
const purchase=()=>({key:'adapter',title:'转换插头',owner:'alice',quantity:'2 件',budget:null,note:'合成采购'});
const plan=()=>({schemaVersion:1,title:'合成旅行',start:'2027-10-01',end:'2027-10-07',international:true,memberIds:['alice','bob'],budget:2000000,saved:0,paid:0,note:'',destinations:[{key:'stop',country:'冰岛',city:'雷克雅未克',arrival:'2027-10-01',departure:'2027-10-07'}],checklist:[],shopping:[purchase()],segments:[]});
const detail=()=>({id:journeyId,tripId,revision:1,plan:plan(),trip:{id:tripId,revision:2,workflowKey:'trip',title:'合成旅行',owner:'shared',start:'2027-10-01',end:'2027-10-07',budget:2000000,saved:0,paid:0,note:''},tasks:[],shopping:[{...purchase(),id:purchaseId,revision:3,workflowKey:'shopping:adapter',tripId,journeyId,done:false,actual:null,photoIds:['synthetic-photo']}],events:[],policyNotice:'合成说明',progress:{done:0,total:0,purchased:0,purchaseCount:1},budget:{total:2000000,paid:0,reserved:0,purchaseBudget:0,purchaseActual:0,unknownPurchaseBudgets:1,unknownPurchaseActuals:1,note:'合成预算'}});
const row=(id,patch={})=>({id,revision:1,title:id,owner:'alice',done:false,...patch});
const fixtureSnapshot=(capability=true)=>({journeyId,revision:1,start:'2027-10-01',end:'2027-10-07',snapshotToken:'synthetic-source',expiresIn:900,capabilities:{shoppingDue:capability},warnings:[],items:[
  {key:'trip',kind:'overview',title:'合成旅行',before:{start:'2027-10-01',end:'2027-10-07'},eligible:false,reason:null,endExclusive:false},
  {key:'shopping:adapter',kind:'shopping',title:'转换插头',before:{start:capability?'2027-09-28':null,end:capability?'2027-09-28':null},eligible:capability,reason:capability?null:'no_date',endExclusive:false},
  {key:'shopping:done',kind:'shopping',title:'已买雨衣',before:{start:'2027-09-25',end:'2027-09-25'},eligible:false,reason:'completed',endExclusive:false},
  {key:'shopping:empty',kind:'shopping',title:'未定采购',before:{start:null,end:null},eligible:false,reason:'no_date',endExclusive:false},
  {key:'shopping:remote',kind:'shopping',title:'来源采购',before:{start:'2027-09-26',end:'2027-09-26'},eligible:false,reason:'cloud_managed',endExclusive:false},
]});
const fixturePreview=(source,body)=>({...source,start:body.start,end:body.end,items:source.items.map(item=>({...copy(item),selected:item.kind==='overview'||body.selectedKeys.includes(item.key),after:item.kind==='overview'?{start:body.start,end:body.end}:body.selectedKeys.includes(item.key)?{start:'2027-10-05',end:'2027-10-05'}:copy(item.before)})),blockingIssues:[],canApply:true,previewToken:'synthetic-preview',expiresIn:900});

test('legacy schedule defaults differ from invalid null, false, malformed dates and priorities',()=>{
  assert.deepEqual(copy(trips.shoppingSchedule({})),{due:'',priority:'normal'});
  for(const bad of [{due:null},{due:false},{due:0},{due:'2027-02-29'},{due:'1999-12-31'},{due:'2101-01-01'},{due:'2027-9-28'},{priority:null},{priority:true},{priority:'urgent'}])assert.throws(()=>trips.shoppingSchedule(bad));
  for(const due of ['','2000-02-29','2100-12-31'])for(const priority of ['low','normal','high'])assert.deepEqual(copy(trips.shoppingSchedule({due,priority})),{due,priority});
});
test('new planning handoff and preview keep date, zero or unknown budget and priority',()=>{
  const p=plan();Object.assign(p.shopping[0],{due:'2027-10-10',priority:'high',budget:0});
  const d=trips.initialPlanningDraft({plan:p},people),out=trips.previewPayload(d,people).plan.shopping[0];
  assert.deepEqual(copy(out),p.shopping[0]);assert.equal(out.due,'2027-10-10');
  d.plan.shopping[0].budget=null;assert.equal(trips.previewPayload(d,people).plan.shopping[0].budget,null);
  d.plan.shopping[0].due='2100-02-29';assert.throws(()=>trips.previewPayload(d,people));
});
test('general journey edit gives live empty date and normal priority authority over stale plan',()=>{
  const d=detail();Object.assign(d.plan.shopping[0],{due:'2027-09-28',priority:'high'});Object.assign(d.shopping[0],{due:'',priority:'normal'});
  const out=trips.previewPayload(trips.editDraft(d),people).plan.shopping[0];
  assert.equal(out.due,'');assert.equal(out.priority,'normal');assert.equal(d.plan.shopping[0].due,'2027-09-28');
  delete d.shopping[0].due;delete d.shopping[0].priority;
  assert.equal(trips.editDraft(d).plan.shopping[0].due,'');assert.equal(trips.editDraft(d).plan.shopping[0].priority,'normal');
});
for(const version of [1,2])test(`strict v${version} plan accepts old omission and new fields, rejects unknown or invalid fields`,()=>{
  const p=plan();if(version===2){p.schemaVersion=2;p.referenceTimezone='Asia/Shanghai';p.destinations[0].timeZone='Atlantic/Reykjavik';}
  assert.equal(segments.readPlan(p,true).shopping[0].due,'');assert.equal(segments.readPlan(p,true).shopping[0].priority,'normal');
  Object.assign(p.shopping[0],{due:'2027-09-28',priority:'high'});assert.equal(segments.readPlan(p,true).shopping[0].due,'2027-09-28');
  for(const patch of [{due:'2027-02-29'},{priority:'urgent'},{priority:null},{dueMode:'offset'}]){const bad=copy(p);Object.assign(bad.shopping[0],patch);assert.throws(()=>segments.readPlan(bad,true));}
});
test('v2 segment editing, upgrade and rebase preserve live purchase metadata and revisions',()=>{
  const d=detail();Object.assign(d.plan.shopping[0],{due:'2027-09-28',priority:'high'});Object.assign(d.shopping[0],{due:'',priority:'low'});
  const caps={schemaVersions:[1,2],editSourceSnapshot:true,canWriteV2:true};
  const draft=segments.upgradeToV2(segments.editSegmentDraft(d),'Asia/Shanghai',{stop:'Atlantic/Reykjavik'},caps);
  const out=segments.previewPayload(draft,caps,['alice','bob']);
  assert.equal(out.plan.shopping[0].due,'');assert.equal(out.plan.shopping[0].priority,'low');assert.equal(out.expectedEntities[purchaseId],3);
  d.shopping[0].revision=4;d.shopping[0].due='2027-10-02';d.shopping[0].priority='normal';
  const rebased=segments.rebaseSegmentDraft(draft,d);assert.equal(rebased.plan.shopping[0].due,'2027-10-02');assert.equal(rebased.expectedEntities[purchaseId],4);
  assert.deepEqual(d.shopping[0].photoIds,['synthetic-photo']);assert.equal(d.shopping[0].id,purchaseId);
});
test('JSON import keeps both old omitted input and new preview/current schedule DTOs',()=>{
  const p=plan(),old=imports.parseTripImport(JSON.stringify({plan:p}));assert.equal(old.plan.shopping[0].due,undefined);
  Object.assign(p.shopping[0],{due:'2027-09-28',priority:'high'});
  const input=imports.tripImportPreviewBody(imports.parseTripImport(JSON.stringify({plan:p})),[1,2]);assert.equal(input.plan.shopping[0].due,'2027-09-28');
  const preview={plan:p,canApply:true,previewToken:'synthetic',expiresIn:900,summary:{create:{trips:1,shopping:1},update:{},detach:0,conflicts:[],preserved:[],resolved:[],cloudReviews:[],warnings:[],policyNotice:'合成',calendar:'合成'}};
  assert.equal(imports.readTripImportPreview(preview).plan.shopping[0].priority,'high');
  const d=detail();d.plan=p;Object.assign(d.shopping[0],{due:'',priority:'normal'});assert.equal(imports.readTripImportCurrent(d,{id:journeyId,tripId,revision:1}).shopping[0].due,'');
});
test('shopping order is unfinished, earliest date, priority, then stable source order',()=>{
  const items=[row('done',{done:true,due:'2027-01-01',priority:'high'}),row('none'),row('low',{due:'2027-09-28',priority:'low'}),row('normal-a',{due:'2027-09-28'}),row('high',{due:'2027-09-28',priority:'high'}),row('earlier',{due:'2027-09-27',priority:'low'}),row('normal-b',{due:'2027-09-28',priority:'normal'})];
  assert.deepEqual(items.sort(trips.compareShoppingItems).map(x=>x.id),['earlier','high','normal-a','normal-b','low','none','done']);
  assert.equal(trips.shoppingScheduleText(row('x',{due:'2027-09-28',priority:'high'}),'2027-09-29'),'2027-09-28 · 已逾期 · 高优先级');
  assert(!trips.shoppingScheduleText(row('x',{done:true,due:'2027-09-28'}),'2027-09-29').includes('逾期'));
  assert.equal(trips.shoppingScheduleText(row('old'),'2027-09-29'),'未设截止日');
});
test('reschedule accepts true/false capabilities, starts unselected and retains concrete reasons',()=>{
  for(const capability of [false,true]){
    const s=reschedule.readRescheduleSnapshot(fixtureSnapshot(capability),journeyId);assert.equal(s.capabilities.shoppingDue,capability);
    assert.deepEqual(copy(reschedule.initialRescheduleDraft(s).selectedKeys),[]);
    assert.match(reschedule.impactReason(s.items[2]),/已完成/);assert.match(reschedule.impactReason(s.items[3]),/未设日期/);assert.match(reschedule.impactReason(s.items[4]),/云端来源/);
  }
  for(const bad of ['true',null,0,undefined]){const s=fixtureSnapshot();s.capabilities.shoppingDue=bad;assert.throws(()=>reschedule.readRescheduleSnapshot(s,journeyId));}
});
test('reschedule rejects contradictory eligible dates and completed/cloud/no-date selections',()=>{
  for(const patch of [{reason:'completed'},{reason:'cloud_managed'},{before:{start:null,end:null}},{before:{start:'2027-09-28',end:'2027-09-29'}}]){const s=fixtureSnapshot();Object.assign(s.items[1],patch);assert.throws(()=>reschedule.readRescheduleSnapshot(s,journeyId));}
  const s=reschedule.readRescheduleSnapshot(fixtureSnapshot(),journeyId),draft=reschedule.initialRescheduleDraft(s);
  for(const key of ['shopping:done','shopping:empty','shopping:remote'])assert.throws(()=>reschedule.reschedulePayload(s,{...draft,selectedKeys:[key]}));
  const old=fixtureSnapshot();old.capabilities.shoppingDue=false;assert.throws(()=>reschedule.readRescheduleSnapshot(old,journeyId));
});
test('reschedule preview moves only explicit selection, rejects changed unselected dates, and drops stale selection on rebase',()=>{
  const source=reschedule.readRescheduleSnapshot(fixtureSnapshot(),journeyId),draft={...reschedule.initialRescheduleDraft(source),start:'2027-10-08',end:'2027-10-14',selectedKeys:['shopping:adapter']};
  const body=reschedule.reschedulePayload(source,draft),wire=fixturePreview(source,body),p=reschedule.readReschedulePreview(wire,source,draft);
  assert.equal(p.items[1].after.start,'2027-10-05');assert.equal(p.items[2].after.start,'2027-09-25');assert.equal(p.items[3].after.start,null);
  wire.items[2].after.start='2027-10-02';assert.throws(()=>reschedule.readReschedulePreview(wire,source,draft));
  const latest=fixtureSnapshot();latest.items[1].eligible=false;latest.items[1].reason='completed';
  const next=reschedule.rebaseRescheduleDraft(draft,reschedule.readRescheduleSnapshot(latest,journeyId));assert.deepEqual(copy(next.removed),['shopping:adapter']);assert.deepEqual(copy(next.draft.selectedKeys),[]);assert.equal(next.draft.start,draft.start);
});

// Executes the real TSX handlers with synthetic DTOs and a small hook renderer.
// Paper/native hosts and HTTP transport are substitutes; this is not a browser,
// server, layout, persistence, cloud or production end-to-end validation.
function harness(screen,options={}) {
  const f={calls:[],dismissed:0,applies:0,failItem:false,failApply:false,failPreview:false,snapshot:fixtureSnapshot(options.capability??true),...options};
  const session={user:{...people[0],role:'member',householdId:'synthetic',auth_version:1},csrf:'synthetic-csrf'};
  let holder,cursor=0,dirty=true,tree,renderNumber=0;
  const instances=new Map(),effects=[],listeners=new Map();
  const events={addEventListener(name,fn){if(!listeners.has(name))listeners.set(name,new Set());listeners.get(name).add(fn);},removeEventListener(name,fn){listeners.get(name)?.delete(fn);}};
  const document={hidden:false,...events,querySelector:()=>null},window={...events},navigator={onLine:true};
  const changed=(a,b)=>!a||!b||a.length!==b.length||a.some((v,i)=>v!==b[i]);
  const useState=value=>{const h=holder,i=cursor++;if(!(i in h.values))h.values[i]=typeof value==='function'?value():value;return[h.values[i],next=>{h.values[i]=typeof next==='function'?next(h.values[i]):next;dirty=true;}];};
  const useRef=value=>{const i=cursor++;if(!(i in holder.values))holder.values[i]={current:value};return holder.values[i];};
  const useEffect=(fn,deps)=>{const h=holder,i=cursor++;if(changed(h.values[i],deps)){h.values[i]=deps;effects.push(()=>{h.cleanups[i]?.();h.cleanups[i]=fn();});}};
  const useCallback=(fn,deps)=>{const i=cursor++;if(!holder.values[i]||changed(holder.values[i].deps,deps))holder.values[i]={deps,fn};return holder.values[i].fn;};
  const react={useState,useRef,useEffect,useCallback,Fragment:'Fragment',createElement(type,props,...children){return{type,props:{...props,children:children.flat(Infinity).filter(x=>x!==null&&x!==undefined&&x!==false)}};}};
  class ApiError extends Error {constructor(message,status){super(message);this.status=status;}}
  const state={revision:1,people,events:[],tasks:[],shopping:options.shopping??[],trips:[detail().trip],finance:{},sync:{}};
  const household={state,user:session.user,identityKey:trips.sessionKey(session),online:true,refresh:async()=>{},setNotice:()=>{}};
  const receipt=()=>({id:journeyId,tripId,revision:2,replayed:false,operation:'reschedule',reschedule:{start:'2027-10-08',end:'2027-10-14',changedKeys:['trip','shopping:adapter']}});
  async function request(path,requestOptions={}) {
    const body=requestOptions.body?JSON.parse(requestOptions.body):undefined;f.calls.push({path,method:requestOptions.method||'GET',body});
    if(path==='/me')return copy(session);
    if(path===`/journeys/${journeyId}/reschedule`)return copy(f.snapshot);
    if(path===`/journeys/${journeyId}/reschedule-preview`){if(f.failPreview)throw new ApiError('synthetic conflict',409);return fixturePreview(f.snapshot,body);}
    if(path==='/journeys/apply'){f.applies++;if(f.failApply)throw new ApiError('synthetic unknown',0);return receipt();}
    if(path.startsWith('/journeys/operations/'))return {found:true,idempotencyKey:path.split('/').at(-1),result:receipt()};
    if(path==='/journeys')return {journeys:[detail()]};
    if(path===`/journeys/${journeyId}`)return detail();
    throw new Error('Unexpected synthetic read '+path);
  }
  household.mutate=async(path,method,body)=>{
    f.calls.push({path,method,body:copy(body)});
    if(path.startsWith('/items/')){if(f.failItem)throw new ApiError('synthetic unknown',0);return {};}
    if(path==='/journeys/preview')return {plan:copy(body.plan),canApply:true,previewToken:'synthetic-trip-preview',expiresIn:900,summary:{create:{trips:1,shopping:1},update:{},detach:0,warnings:[],conflicts:[],preserved:[],cloudReviews:[],policyNotice:'合成说明'}};
    throw new Error('Unexpected synthetic mutation '+path);
  };
  const paper=Object.fromEntries(['Button','Checkbox','Chip','Divider','HelperText','IconButton','Text','TextInput','ActivityIndicator','Portal','Searchbar'].map(name=>[name,name]));
  paper.Dialog={Title:'DialogTitle',Content:'DialogContent',ScrollArea:'DialogScrollArea',Actions:'DialogActions'};
  paper.List={Accordion:'Accordion',Icon:'ListIcon'};paper.Menu={Item:'MenuItem'};paper.Checkbox={Item:'CheckboxItem',Android:'CheckboxAndroid'};
  paper.useTheme=()=>({colors:{onSurfaceVariant:'#555',error:'#b00'}});
  paper.SegmentedButtons=props=>react.createElement('SegmentedButtons',props,...props.buttons.map(button=>react.createElement('Segment', {...button,onPress:()=>props.onValueChange(button.value)},button.label)));
  const mocks={react,'react-native':{View:'View',Image:'Image',ScrollView:'ScrollView',Platform:{OS:'web'},StyleSheet:{create:x=>x},AppState:{currentState:'active',addEventListener:()=>({remove(){}})}},'react-native-paper':paper,'expo-router':{useFocusEffect:fn=>useEffect(fn,[fn])},'expo-image-picker':{},'expo-image-manipulator':{},'../lib/api':{ApiError,request},'../lib/household':{useHousehold:()=>household},'../ui/components':{PageHeader:'PageHeader',SectionCard:'SectionCard',EmptyState:'EmptyState'},'../ui/theme':{useDisplayDensity:()=>({screenGap:16,sectionGap:12,rowPadding:12})},'../ui/SelectionRow':{SelectionRow:'SelectionRow'}};
  for(const path of ['../components/ShoppingSettlementPanel','./InventoryScreen','./JourneyCalendarPanel','./JourneyTasksPanel','./JourneyPlacesPanel','./JourneyReschedulePanel','./MapScreen','./TripPhotosScreen','./JourneyDocumentsPanel','../components/JourneySegmentsPanel','../components/TripRecapPanel','../components/JourneyRoutesPanel','../components/TripImportPanel'])mocks[path]={default:'UnusedPanel'};
  const files={editor:'ui/ItemEditor.tsx',list:'screens/ListScreen.tsx',trips:'screens/TripsScreen.tsx',reschedule:'screens/JourneyReschedulePanel.tsx'};
  const Component=loader(mocks,{document,window,navigator})(resolve(root,files[screen])).default;
  const screenProps={state,user:session.user,focus:'',mode:'today',layout:{},setFocus(){},setMode:async()=>{},onNavigate(){},onEdit:(kind,item)=>{f.edited={kind,item};},onToggle:async()=>{},onLegacy(){},onInventory(){}};
  const props=screen==='editor'?{kind:'shopping',item:options.item,onDismiss:()=>{f.dismissed++;}}:screen==='list'?{...screenProps,kind:'shopping'}:screen==='trips'?{...screenProps,initialDraft:{plan:plan()}}:{journeyId,onBack(){},onSaved:()=>{f.saved=true;}};
  function expand(node,path='0') {
    if(node===null||node===undefined||node===false)return null;if(typeof node!=='object')return node;if(Array.isArray(node))return node.map((n,i)=>expand(n,path+'.'+i));
    if(typeof node.type==='function'){
      const key=path+':'+node.type.name;if(!instances.has(key))instances.set(key,{values:[],cleanups:[]});
      const previous=holder,oldCursor=cursor;holder=instances.get(key);holder.seen=renderNumber;cursor=0;const result=node.type(node.props);holder=previous;cursor=oldCursor;return expand(result,key);
    }
    return {...node,props:{...node.props,action:node.props.action?expand(node.props.action,path+'.action'):undefined,children:(node.props.children||[]).map((child,i)=>expand(child,path+'.'+(child?.props?.key??i)))}};
  }
  function render(){dirty=false;renderNumber++;tree=expand(react.createElement(Component,props));for(const [key,h]of instances)if(h.seen!==renderNumber){h.cleanups.forEach(fn=>fn?.());instances.delete(key);}while(effects.length)effects.shift()();}
  async function flush(){for(let i=0;i<30;i++){if(dirty)render();await new Promise(setImmediate);}assert(!dirty,'synthetic render did not settle');}
  function nodes(value){if(!value||typeof value!=='object')return[];if(Array.isArray(value))return value.flatMap(nodes);return[value,...nodes(value.props.action),...nodes(value.props.children)];}
  function text(value){if(typeof value==='string'||typeof value==='number')return String(value);if(!value)return'';if(Array.isArray(value))return value.map(text).join(' ');return text(value.props.children);}
  function find(label){const matches=nodes(tree).filter(n=>(n.props.accessibilityLabel||n.props.label||text(n.props.children))===label&&(n.props.onPress||n.props.onChangeText));assert.equal(matches.length,1,label);return matches[0];}
  return{f,flush,text:()=>text(tree),nodes:()=>nodes(tree),value:label=>find(label).props.value,disabled:label=>!!find(label).props.disabled,
    async click(label){const n=find(label);assert(!n.props.disabled,label+' disabled');n.props.onPress();await flush();},async input(label,value){const n=find(label);assert(!n.props.disabled,label+' disabled');n.props.onChangeText(value);await flush();}};
}
test('actual ItemEditor sends deadline/priority with unchanged photo and financial fields, and clears explicitly',async()=>{
  const item={...row(purchaseId),title:'转换插头',due:'2027-09-28',priority:'high',budget:10000,actual:null,photoIds:['synthetic-photo']};
  const h=harness('editor',{item});await h.flush();assert.equal(h.value('采购截止日期（可选）'),'2027-09-28');
  await h.input('采购截止日期（可选）','');await h.click('采购优先级：普通');await h.click('保存');
  const call=h.f.calls.find(x=>x.path.startsWith('/items/'));assert.equal(call.method,'PATCH');assert.equal(call.body.due,'');assert.equal(call.body.priority,'normal');assert.equal(call.body.revision,1);assert.equal(call.body.budget,10000);assert.deepEqual(call.body.photoIds,['synthetic-photo']);assert.equal(h.f.dismissed,1);
});
test('actual ItemEditor blocks invalid date before mutation and retains new-item defaults',async()=>{
  const h=harness('editor');await h.flush();assert(h.text().includes('未设截止日'));await h.input('物品名称','转换插头');await h.input('采购截止日期（可选）','2027-02-29');await h.click('保存');assert.match(h.text(),/有效的 YYYY-MM-DD/);assert.equal(h.f.calls.length,0);
  await h.input('采购截止日期（可选）','');await h.click('保存');assert.equal(h.f.calls[0].body.due,'');assert.equal(h.f.calls[0].body.priority,'normal');
});
test('actual ItemEditor freezes new controls after uncertain save without losing date',async()=>{
  const h=harness('editor',{failItem:true});await h.flush();await h.input('物品名称','转换插头');await h.input('采购截止日期（可选）','2027-09-28');await h.click('采购优先级：高');await h.click('保存');
  assert(h.disabled('保存'));assert(h.disabled('采购截止日期（可选）'));assert(h.disabled('采购优先级：低'));assert.equal(h.value('采购截止日期（可选）'),'2027-09-28');assert.match(h.text(),/核对后再操作/);assert.equal(h.f.calls.length,1);
});
test('actual shopping list sorts by date and priority and marks only unfinished overdue rows',async()=>{
  const h=harness('list',{shopping:[row('low',{due:'2000-01-01',priority:'low'}),row('done',{done:true,due:'2000-01-01',priority:'high'}),row('normal',{due:'2000-01-01'}),row('high',{due:'2000-01-01',priority:'high'}),row('none')]});await h.flush();
  assert.deepEqual(h.nodes().filter(n=>n.props.testID?.startsWith('shopping-item-')).map(n=>n.props.testID),['shopping-item-high','shopping-item-normal','shopping-item-low','shopping-item-none']);assert.match(h.text(),/已逾期/);assert.match(h.text(),/高优先级/);assert.match(h.text(),/未设截止日/);
  await h.click('已买到');assert(!h.text().includes('已逾期'));assert.deepEqual(h.nodes().filter(n=>n.props.testID?.startsWith('shopping-item-')).map(n=>n.props.testID),['shopping-item-done']);
});
test('actual TripsScreen controls keep schedule in preview and require separate confirm',async()=>{
  const h=harness('trips');await h.flush();await h.input('采购截止日期 1（可选）','2027-10-10');await h.click('采购优先级 1：高');await h.click('预览变更');
  const call=h.f.calls.find(x=>x.path==='/journeys/preview');assert.equal(call.body.plan.shopping[0].due,'2027-10-10');assert.equal(call.body.plan.shopping[0].priority,'high');assert.equal(call.body.plan.shopping[0].budget,null);assert(h.text().includes('2027-10-10 · 高优先级'));assert(!h.f.calls.some(x=>x.path==='/journeys/apply'));
  await h.input('采购截止日期 1（可选）','');assert(!h.text().includes('确认保存旅行'));await h.click('预览变更');assert.equal(h.f.calls.at(-1).body.plan.shopping[0].due,'');
});
test('actual reschedule panel defaults to unchanged and presents reasons before explicit preview',async()=>{
  const h=harness('reschedule');await h.flush();assert.match(h.text(),/已完成/);assert.match(h.text(),/未设日期/);assert.match(h.text(),/云端来源/);assert(!h.nodes().some(n=>n.props.accessibilityLabel==='联动改期：已买雨衣'));
  await h.input('新的出发日期','2027-10-08');await h.input('新的返程日期','2027-10-14');await h.click('预览改期');assert.deepEqual(h.f.calls.find(x=>x.path.endsWith('/reschedule-preview')).body.selectedKeys,[]);assert(!h.f.calls.some(x=>x.path==='/journeys/apply'));
  await h.click('继续修改');await h.click('联动改期：转换插头');await h.click('预览改期');assert.equal(h.f.calls.filter(x=>x.path.endsWith('/reschedule-preview')).at(-1).body.selectedKeys[0],'shopping:adapter');assert.match(h.text(),/2027-09-28\s+→ 2027-10-05/);
});
test('actual reschedule panel displays old server capability without offering purchase movement',async()=>{
  const h=harness('reschedule',{capability:false});await h.flush();assert.match(h.text(),/当前服务不支持采购截止联动/);assert(!h.nodes().some(n=>n.props.accessibilityLabel?.startsWith('联动改期：')));
});
test('actual reschedule conflict keeps dates for review, and uncertain apply recovers the same original operation',async()=>{
  const h=harness('reschedule',{failPreview:true});await h.flush();await h.input('新的出发日期','2027-10-08');await h.input('新的返程日期','2027-10-14');await h.click('联动改期：转换插头');await h.click('预览改期');assert.equal(h.value('新的出发日期'),'2027-10-08');assert(h.nodes().some(n=>n.props.title==='内容已变化，输入仍保留'));
  h.f.failPreview=false;await h.click('读取最新并重新核对');await h.click('已核对最新内容');await h.click('预览改期');h.f.failApply=true;await h.click('确认改期');
  assert(h.nodes().some(n=>n.props.title==='先核对这次改期'));const original=h.f.calls.find(x=>x.path==='/journeys/apply').body;await h.click('核对保存结果');assert(h.f.calls.some(x=>x.path==='/journeys/operations/'+original.idempotencyKey));assert.equal(h.f.applies,1);assert(h.nodes().some(n=>n.props.title==='改期已保存'));
});
