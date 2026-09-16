import {test} from 'node:test';
import assert from 'node:assert/strict';
import {toCents,amountText,validDay,tripDays,newDraft,editDraft,upgradeDraft,previewPayload,newKey,recordVersions,eventDates,readForMember,memberKey,SessionChangedError,validateReceipt} from '../frontend/src/lib/trips.ts';

const people=[{id:'member1',name:'甲'},{id:'member2',name:'乙'}];
const plan={schemaVersion:2,referenceTimezone:'Europe/Paris',title:'原计划',start:'2026-10-24',end:'2026-10-26',international:true,memberIds:['member1'],budget:20001,saved:10000,paid:9999,note:'原备注',destinations:[{key:'paris',country:'法国',city:'巴黎',arrival:'2026-10-24',departure:'2026-10-26',timeZone:'Europe/Paris'}],checklist:[{key:'prepare',title:'原准备',owner:'shared',due:'2026-10-20',dueOffsetDays:-4,note:'',category:'preparation'}],shopping:[{key:'bag',title:'背包',owner:'shared',quantity:'1 件',budget:100,note:''}],segments:[{key:'stay',title:'住宿',kind:'stay',propertyName:'合成住宿',timeZone:'Europe/Paris',checkInDate:'2026-10-24',checkOutDate:'2026-10-26',bookingState:'booked',datePolicy:'fixed',unknownExtension:{preserved:true}}]};
const journey={id:'journey123',tripId:'trip123',revision:5,plan,trip:{id:'trip123',revision:7,title:'当前标题',start:plan.start,end:plan.end,budget:11111,saved:8888,paid:2222,note:'当前备注'},tasks:[{id:'task123',revision:3,workflowKey:'task:prepare',title:'实际准备',owner:'member2',due:'2026-10-21',note:'实际备注',done:true}],shopping:[{id:'purchase123',revision:4,workflowKey:'shopping:bag',title:'实际背包',owner:'member1',quantity:'2 件',budget:null,note:'未填写预算',done:true,actual:1250,photoIds:['localphoto']}],events:[]};

test('money parses cents without floating point rounding or coercion',()=>{
  assert.equal(toCents('0.29'),29);assert.equal(toCents('1000000000.00'),100000000000);assert.equal(amountText(100000000000),'1000000000.00');
  for(const raw of ['','-1','1.005','1e3','Infinity','true','1,000','1000000000.01'])assert.throws(()=>toCents(raw));
});
test('date-only inclusive trips stay exact across leap years and DST',()=>{
  for(const day of ['2026-02-29','2101-01-01','1999-12-31','2026-04-31','2026-2-01'])assert.equal(validDay(day),false);
  assert.equal(tripDays('2024-02-28','2024-03-01'),3);assert.equal(tripDays('2026-10-24','2026-10-26'),3);
  assert.equal(tripDays('2024-01-01','2025-01-01'),367);assert.throws(()=>tripDays('2024-01-01','2025-01-02'));assert.throws(()=>tripDays('2026-10-26','2026-10-24'));
});
test('new draft uses current household members, template omission and integer cents',()=>{
  const draft=newDraft(people,'2026-10-01');draft.plan.title='旅行';draft.plan.destinations[0].city='苏州';draft.budget='200.29';
  const payload=previewPayload(draft,people);assert.equal(payload.plan.budget,20029);assert.equal(Object.hasOwn(payload.plan,'checklist'),false);assert.equal(Object.hasOwn(payload.plan,'segments'),false);assert.deepEqual(payload.plan.memberIds,['member1','member2']);
  assert.throws(()=>previewPayload(draft,people.slice(0,1)));assert.equal(draft.plan.budget,0);
});
test('edit preserves v2 metadata and stable keys while keeping current entity edits',()=>{
  const original=JSON.stringify(journey),draft=editDraft(journey),payload=previewPayload(draft,people);
  assert.deepEqual(payload.plan.segments,plan.segments);assert.deepEqual(payload.plan.destinations,plan.destinations);assert.equal(payload.plan.schemaVersion,2);assert.equal(payload.plan.referenceTimezone,'Europe/Paris');
  assert.equal(payload.plan.title,'当前标题');assert.equal(payload.plan.budget,11111);assert.equal(payload.plan.checklist[0].title,'实际准备');assert.equal(payload.plan.checklist[0].due,'2026-10-21');assert.equal(payload.plan.shopping[0].quantity,'2 件');assert.equal(payload.plan.shopping[0].budget,null);
  assert.equal(payload.journeyId,'journey123');assert.equal(payload.revision,5);assert.equal(Object.hasOwn(payload,'observed'),false);assert.equal(JSON.stringify(journey),original);
  assert.notEqual(recordVersions({...journey,tasks:[{...journey.tasks[0],revision:4}]}),draft.observed);
});
test('legacy upgrade only adopts local tasks belonging to that trip',()=>{
  const trip={...journey.trip,id:'old',destination:'苏州'},draft=upgradeDraft(trip,people,[{id:'local',tripId:'old',title:'原准备',owner:'member1',due:'2026-10-20'}, {id:'cloud',tripId:'old',title:'云事项',sync:{provider:'google'}},{id:'other',tripId:'else',title:'其他旅行'}]);
  assert.deepEqual(draft.plan.checklist.map(row=>row.key),['existing-local']);assert.equal(draft.tripId,'old');assert.equal(draft.tripRevision,7);assert.equal(previewPayload(draft,people).plan.destinations[0].city,'苏州');
});
test('operation keys stay within API grammar and are independent',()=>{const a=newKey(),b=newKey();assert.match(a,/^[a-f0-9]{32}$/);assert.notEqual(a,b);});
test('malformed successful apply envelopes cannot be treated as receipts',()=>{
  const valid={id:'a'.repeat(24),tripId:'b'.repeat(24),revision:1,replayed:false};assert.equal(validateReceipt(valid),true);assert.equal(validateReceipt({...valid,replayed:true}),true);
  for(const invalid of [null,[],{},true,{...valid,id:'invalid'},{...valid,tripId:'../other'},{...valid,revision:0},{...valid,revision:1.5},{...valid,revision:true},{...valid,revision:Number.MAX_SAFE_INTEGER+1},{...valid,replayed:0},{...valid,replayed:undefined}])assert.equal(validateReceipt(invalid),false);
});
test('calendar detail displays inclusive final day from exclusive backend end',()=>{
  assert.equal(eventDates({allDay:true,start:'2026-10-24T00:00:00+08:00',end:'2026-10-27T00:00:00+08:00'}),'2026-10-24 — 2026-10-26 · 全天');
  assert.equal(eventDates({allDay:true,start:'2026-10-24T00:00:00+08:00',end:'2026-10-25T00:00:00+08:00'}),'2026-10-24 · 全天');
});
const user={id:'member1',role:'member',householdId:'household',auth_version:1},session={user,csrf:'synthetic-one'};
test('member reads check both sessions and return only stable results',async()=>{
  const calls=[];const fetcher=async path=>{calls.push(path);return path==='/me'?session:{journeys:[]};};
  assert.deepEqual(await readForMember('/journeys',memberKey(user),fetcher,()=>true),{journeys:[]});assert.deepEqual(calls,['/me','/journeys','/me']);
});
test('member reads reject TV before data and csrf, household, auth, or owner change after response',async()=>{
  let called=false;await assert.rejects(readForMember('/journeys',memberKey(user),async path=>{if(path!=='/me')called=true;return {user:{...user,role:'tv'}};},()=>true),SessionChangedError);assert.equal(called,false);
  for(const changed of [{...session,csrf:'synthetic-two'},{...session,user:{...user,id:'member2'}},{...session,user:{...user,householdId:'other'}},{...session,user:{...user,auth_version:2}},{user:null}]){
    let n=0;await assert.rejects(readForMember('/journeys',memberKey(user),async path=>path==='/me'?(++n===1?session:changed):{secret:'must not return'},()=>true),SessionChangedError);
  }
});
test('late reads from a disposed screen are discarded',async()=>{
  let current=true;await assert.rejects(readForMember('/journeys',memberKey(user),async path=>{if(path!=='/me'){current=false;return {journeys:[]};}return session;},()=>current),SessionChangedError);
});
