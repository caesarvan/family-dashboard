import assert from 'node:assert/strict';
import { test } from 'node:test';
import { RoutineError, RoutineDiscarded, RoutineRejected, RoutineFence, checkedRoutineWrite, routineSignature,
  routineAmount, routineBudget, routineDate, routineDraft, draftRoutinePayload, rebaseRoutineDraft,
  readRoutinePlan, readRoutineContext, readRoutinePayload, readRoutinePreview, readRoutineConfirmed, readRoutineReceipt,
  routineContextPath, routineOperationPath, routineRequest } from '../frontend/src/lib/routines.ts';

const planId = 'a'.repeat(32), entityId = 'b'.repeat(24), operationKey = 'c'.repeat(64);
const schedule = { frequency:'monthly', interval:1, anchor:'2028-01-31', timeZone:'Asia/Shanghai', monthEnd:'clamp' };
const template = { title:'合成月末整理', owner:'shared', note:'' };
const entity = { id:entityId, revision:1, ...template, done:false, due:'2028-01-31' };
const occurrence = { index:1, scheduledOn:'2028-01-31', entityId, state:'pending', entity };
const plan = (patch = {}) => ({ id:planId, revision:2, kind:'tasks', state:'active', status:'pending', template, schedule,
  current:occurrence, nextDates:['2028-02-29','2028-03-31','2028-04-30'], history:[occurrence], createdBy:'member1',
  createdAt:'2028-01-30T10:00:00+00:00',updatedAt:'2028-01-30T10:00:00+00:00', ...patch });
const context = (patch = {}) => ({ version:1, today:'2028-01-30', timeZone:'Asia/Shanghai', limit:{activePlans:100,itemsPerKind:2500}, plans:[plan()], pageInfo:{page:0,pageSize:40,more:false}, ...patch });
const payload = () => ({ operation:'create', kind:'tasks', template, schedule });
const preview = (patch = {}) => ({ operation:'create',today:'2028-01-30',timeZone:'Asia/Shanghai',before:null,after:{kind:'tasks',template,schedule,state:'active'},
  nextDates:['2028-01-31','2028-02-29','2028-03-31'],willGenerate:{index:1,scheduledOn:'2028-01-31',kind:'tasks',data:{...template,done:false,due:'2028-01-31',tripId:''}},warnings:[],previewToken:'signed-synthetic',operationKey,expiresInSeconds:600,...patch });
const pending = { operation:'create',operationKey,previewToken:'signed-synthetic' };
const session = () => ({ user:{id:'member1',name:'合成',householdId:'default',role:'member',auth_version:1},csrf:'synthetic-csrf' });
const receipt = (patch = {}) => ({found:true,operationKey,operation:'create',planId,revision:2,generated:{id:entityId,kind:'tasks',revision:1,scheduledOn:'2028-01-31'},createdAt:'2028-01-30T10:00:00+00:00',...patch});
const json = (value, status = 200) => new Response(JSON.stringify(value), {status, headers:{'Content-Type':'application/json'}});

test('amount input keeps unknown separate from exact zero and rejects rounded or scientific money', () => {
  assert.equal(routineBudget(' '),null);assert.equal(routineBudget('0.00'),0);assert.equal(routineBudget('123.45'),12345);
  assert.equal(routineAmount(0),'0.00');assert.equal(routineAmount(null),'');assert.equal(routineAmount(12345),'123.45');
  assert.equal(routineBudget('1000000000.00'),100000000000);
  for(const v of ['1.001','-0','01','1e2','Infinity','1000000000.01','1,000.00'])assert.throws(()=>routineBudget(v),RoutineError);
  for(const v of [true,0.1,Number.MAX_SAFE_INTEGER+1,-1])assert.throws(()=>routineAmount(v),RoutineError);
});
test('strict schedule dates and bounded intervals preserve monthly anchor rather than client date math', () => {
  assert.equal(routineDate('2028-02-29'),'2028-02-29');assert.equal(routineDate('2100-12-31'),'2100-12-31');
  for(const v of ['2027-02-29','2028-02-30','2028-2-1','1999-12-31','2101-01-01','2028-01-31Z'])assert.throws(()=>routineDate(v),RoutineError);
  for(const [frequency,max] of [['daily',365],['weekly',52],['monthly',12]]){
    assert.equal(readRoutinePayload({...payload(),schedule:{...schedule,frequency,interval:max}}).schedule.interval,max);
    for(const interval of [0,max+1,1.5,true])assert.throws(()=>readRoutinePayload({...payload(),schedule:{...schedule,frequency,interval}}),RoutineError);
  }
  assert.deepEqual(readRoutinePreview(preview(),payload()).nextDates,['2028-01-31','2028-02-29','2028-03-31']);
});
test('drafts enforce current family owners, Unicode character limits and full shopping fields', () => {
  const draft={...routineDraft(undefined,'2028-01-31','shopping'),title:'😀'.repeat(100),quantity:'1 包',owner:'member2',budget:'0'};
  const value=draftRoutinePayload(draft,[{id:'member2',name:'合成'}]);assert.equal(value.template.budget,0);assert.equal(value.template.title,draft.title);
  assert.equal(draftRoutinePayload({...draft,budget:''},[{id:'member2',name:'合成'}]).template.budget,null);
  assert.throws(()=>draftRoutinePayload(draft,[{id:'member1',name:'另一人'}]),RoutineError);
  assert.throws(()=>draftRoutinePayload({...draft,title:'😀'.repeat(101)},[{id:'member2',name:'合成'}]),RoutineError);
  for(const change of [{actor:'member2'}, {requestId:'invented'}, {revision:0}])assert.throws(()=>readRoutinePayload({...payload(),...change}),RoutineError);
  assert.throws(()=>readRoutinePayload({...payload(),template:{...template,secret:'not sent'}}),RoutineError);
});
test('same-plan conflict rebase carries only edited fields and preserves latest unrelated choices', () => {
  const old=readRoutinePlan(plan()),draft={...routineDraft(old),title:'我的改名'},newer=readRoutinePlan(plan({revision:4,template:{...template,owner:'member2',note:'另一成员备注'},schedule:{...schedule,interval:2}}));
  const result=rebaseRoutineDraft(old,draft,newer);assert.equal(result.title,'我的改名');assert.equal(result.owner,'member2');assert.equal(result.note,'另一成员备注');assert.equal(result.interval,'2');
  assert.equal(draftRoutinePayload(result,[{id:'member2',name:'合成'}],newer).revision,4);
  assert.throws(()=>rebaseRoutineDraft(old,draft,{...newer,id:'other'}),RoutineError);
});
test('context accepts one focused off-page plan and rejects mixed pagination or duplicate identities', () => {
  const plans=Array.from({length:41},(_,i)=>plan({id:'opaque_'+i}));
  assert.equal(readRoutineContext(context({plans}),0,'opaque_40').plans.length,41);
  assert.throws(()=>readRoutineContext(context({plans})),RoutineError);
  assert.throws(()=>readRoutineContext(context({plans:[plan(),plan()]})),RoutineError);
  assert.throws(()=>readRoutineContext(context(),1),RoutineError);
  assert.equal(routineContextPath(2,true,'old-plan_1'),'/routines/context?page=2&includeArchived=true&planId=old-plan_1');
  for(const id of ['../me','id?x=1','https://outside/'])assert.throws(()=>routineContextPath(0,false,id),RoutineError);
});
test('context projects shared business fields only, preserves edits to current item independently', () => {
  const current={...occurrence,entity:{...entity,title:'当前事项另改',due:'2150-01-01',credential:'discard',photoIds:['secret']}};
  const result=readRoutinePlan(plan({current,private:'discard'}));
  assert.equal(result.current.entity.title,'当前事项另改');assert.equal(result.current.entity.due,'2150-01-01');assert.equal(result.template.title,template.title);
  assert.equal(result.private,undefined);assert.equal(result.current.entity.credential,undefined);assert.equal(result.current.entity.photoIds,undefined);
  assert.equal(readRoutinePlan(plan({current:{...occurrence,entity:null,state:'missing'}})).current.entity,null);
  assert.throws(()=>readRoutinePlan(plan({revision:1.5})),RoutineError);
});
test('preview identity and before/after fields cannot silently change the intended operation', () => {
  assert.equal(readRoutinePreview(preview(),payload()).operationKey,operationKey);
  for(const change of [{operation:'archive'},{operationKey:'BAD'},{before:plan()},{after:{kind:'tasks',template:{...template,title:'changed'},schedule,state:'active'}},{after:{kind:'tasks',template,schedule,state:'paused'}}])assert.throws(()=>readRoutinePreview(preview(change),payload()),RoutineError);
  const input={operation:'pause',planId,revision:2}, value=preview({operation:'pause',before:plan(),after:{kind:'tasks',template,schedule,state:'paused'},willGenerate:null});
  assert.equal(readRoutinePreview(value,input).after.state,'paused');assert.throws(()=>readRoutinePreview(value,{...input,revision:3}),RoutineError);
});
test('history receipt is a summary, matched to original key/operation and never treated as current plan', () => {
  assert.equal(readRoutineReceipt(receipt(),pending).revision,2);
  assert.equal(readRoutineReceipt({...receipt(),plan:{state:'active'}},pending).plan,undefined);
  assert.equal(readRoutineConfirmed({operation:'create',operationKey,plan:plan(),generated:receipt().generated,replayed:true},pending).planId,planId);
  for(const change of [{found:false},{operationKey:'d'.repeat(64)},{operation:'skip'},{revision:false}])assert.throws(()=>readRoutineReceipt(receipt(change),pending),RoutineError);
  assert.throws(()=>readRoutineReceipt(receipt({operation:'update',planId:'other'}),{...pending,operation:'update',planId}),RoutineError);
  assert.throws(()=>readRoutineConfirmed({operation:'create',operationKey,plan:plan(),generated:null},pending),RoutineError);
});
test('full identity fence rejects each actor axis before dispatch and after response', async () => {
  for(const phase of ['before','after'])for(const axis of ['id','householdId','auth_version','role','csrf']){
    const first=session(),other=session();if(axis==='csrf')other.csrf='new';else other.user[axis]=axis==='auth_version'?2:'changed';
    const fence=new RoutineFence(routineSignature(first));let reads=0,writes=0;
    await assert.rejects(fence.run(async()=>phase==='before'||++reads===2?other:first,async()=>{writes++;return 'sensitive';},()=>true),RoutineDiscarded);
    assert.equal(writes,phase==='before'?0:1);
  }
});
test('conceal invalidates late successes and failures without lending them a new foreground epoch', async () => {
  for(const failure of [false,true]){
    const s=session(),fence=new RoutineFence(routineSignature(s));let done;const deferred=new Promise(r=>done=r);
    const result=fence.run(async()=>s,async()=>{await deferred;if(failure)throw new RoutineError('old',409);return 'old';},()=>true);
    await Promise.resolve();fence.invalidate();done();await assert.rejects(result,RoutineDiscarded);
  }
});
test('only exact HTTP failures after successful identity validation can release a first confirm', async () => {
  const saved=globalThis.fetch,s=session(),fence=new RoutineFence(routineSignature(s)),guard=job=>fence.run(async()=>s,job,()=>true);
  try {
    for(const [status,code,rejected] of [[409,'',true],[410,'preview_expired_unapplied',true],[410,'other',false],[401,'',false],[403,'',false],[408,'',false],[500,'',false]]){
      globalThis.fetch=async()=>json({error:'synthetic',code},status);
      await assert.rejects(checkedRoutineWrite(guard,csrf=>routineRequest('/routines/confirm',new AbortController().signal,{payload:{previewToken:'original'},csrf})),e=>e instanceof RoutineError && (e instanceof RoutineRejected)===rejected && e.code===code);
    }
    await assert.rejects(checkedRoutineWrite(guard,async()=>{throw new RoutineError('not endpoint',409);}),e=>!(e instanceof RoutineRejected));
    globalThis.fetch=async()=>json({error:'conflict'},409);let reads=0;
    await assert.rejects(checkedRoutineWrite(job=>fence.run(async()=>{if(++reads===2)throw new RoutineError('after-me',429);return s;},job,()=>true),csrf=>routineRequest('/routines/confirm',new AbortController().signal,{payload:{previewToken:'original'},csrf})),e=>e.status===429&&!(e instanceof RoutineRejected));
  } finally {globalThis.fetch=saved;}
});
test('failed preflight never calls confirm and GET missing receipt retains its precise error code', async () => {
  const original=globalThis.fetch,s=session(),fence=new RoutineFence(routineSignature(s));let calls=0;
  try {
    await assert.rejects(checkedRoutineWrite(job=>fence.run(async()=>{throw new RoutineError('offline');},job,()=>true),async()=>{calls++;}),RoutineError);assert.equal(calls,0);
    globalThis.fetch=async()=>json({error:'not found',code:'routine_receipt_not_found'},404);
    await assert.rejects(routineRequest(routineOperationPath(operationKey),new AbortController().signal),e=>e.status===404&&e.code==='routine_receipt_not_found');
  } finally {globalThis.fetch=original;}
});
test('malformed fresh identity and non-JSON permission errors still fail closed', async () => {
  for(const s of [{...session(),csrf:42},{...session(),user:{...session().user,householdId:42}},{...session(),user:{...session().user,auth_version:0}}]){
    let writes=0;await assert.rejects(new RoutineFence(routineSignature(s)).run(async()=>s,async()=>{writes++;},()=>true),RoutineDiscarded);assert.equal(writes,0);
  }
  const saved=globalThis.fetch;try{globalThis.fetch=async()=>new Response('<html>Denied</html>',{status:403,headers:{'Content-Type':'text/html'}});
    await assert.rejects(routineRequest('/me',new AbortController().signal),e=>e instanceof RoutineError&&e.status===403);
  }finally{globalThis.fetch=saved;}
});
test('transport is bounded same-origin and never retries or sends credentials to arbitrary paths', async () => {
  const saved=globalThis.fetch,calls=[];
  try {
    globalThis.fetch=async(url,options)=>{calls.push({url,options});return json(context());};
    await routineRequest(routineContextPath(),new AbortController().signal);assert.equal(calls[0].url,'/api/routines/context?page=0&includeArchived=false');
    for(const name of ['credentials','mode'])assert.equal(calls[0].options[name],'same-origin');assert.equal(calls[0].options.redirect,'error');assert.equal(calls[0].options.cache,'no-store');
    for(const path of ['https://outside/api/routines/confirm','//outside','/routines/context?owner=member2','/routines/operations/../me'])await assert.rejects(routineRequest(path,new AbortController().signal),RoutineError);
    assert.equal(calls.length,1);
    globalThis.fetch=async()=>{calls.push('failed');throw new TypeError('connection');};
    await assert.rejects(routineRequest('/routines/confirm',new AbortController().signal,{payload:{previewToken:'same-token'},csrf:'synthetic'}),RoutineError);assert.equal(calls.length,2);
    globalThis.fetch=async()=>new Response('x',{headers:{'Content-Type':'application/json','Content-Length':'4000001'}});
    await assert.rejects(routineRequest(routineContextPath(),new AbortController().signal),RoutineError);
    const c=new AbortController();c.abort();await assert.rejects(routineRequest('/me',c.signal),RoutineDiscarded);
  } finally {globalThis.fetch=saved;}
});
