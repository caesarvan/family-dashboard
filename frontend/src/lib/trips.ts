import type { CalendarEvent, ListItem, Member, Person, ShoppingPriority, Trip } from './types';
import { memberIdentity, sessionIdentity } from './sessionIdentity.ts';

export type Destination = {key:string;city:string;country:string;arrival:string;departure:string;timeZone?:string};
export type Preparation = {key:string;title:string;owner:string;due?:string;dueOffsetDays?:number;note:string;category?:string};
export type Purchase = {key:string;title:string;owner:string;quantity:string;budget:number|null;note:string;due?:string;priority?:ShoppingPriority};
export type Segment = {key:string;title:string;start?:unknown;end?:unknown;location?:string;note?:string;kind?:string;[key:string]:unknown};
export type Plan = {schemaVersion?:1|2;referenceTimezone?:string;title:string;start:string;end:string;international:boolean;memberIds:string[];budget:number;saved:number;paid:number;note:string;destinations:Destination[];checklist?:Preparation[];shopping:Purchase[];segments?:Segment[]};
type Linked<T> = T & {workflowKey:string};
export type Journey = {id:string;revision:number;tripId:string;plan:Plan;trip:Trip|null;tasks:Linked<ListItem>[];shopping:Linked<ListItem>[];events:Linked<CalendarEvent>[];progress:{done:number;total:number;purchased:number;purchaseCount:number};budget:{total:number;paid:number;reserved:number;purchaseBudget:number;purchaseActual:number;unknownPurchaseBudgets:number;unknownPurchaseActuals:number;note:string};policyNotice:string};
export type Preview = {plan:Plan;canApply:boolean;previewToken:string|null;expiresIn:number;summary:{create:Record<string,number>;update:Record<string,number>;detach:number;policyNotice:string;removedItems:string;warnings:{message?:string}[];conflicts:unknown[];preserved:unknown[];cloudReviews:unknown[]}};
export type Receipt = {id:string;tripId:string;revision:number;replayed:boolean};
export function validateReceipt(value:unknown):value is Receipt {
  if(!value||typeof value!=='object'||Array.isArray(value))return false;
  const row=value as Record<string,unknown>;
  return typeof row.id==='string'&&/^[a-f0-9]{24}$/.test(row.id)&&typeof row.tripId==='string'&&/^[a-f0-9]{24}$/.test(row.tripId)&&Number.isSafeInteger(row.revision)&&Number(row.revision)>0&&typeof row.replayed==='boolean';
}
export type Draft = {plan:Plan;budget:string;saved:string;paid:string;purchaseBudgets?:Record<string,string>;journeyId?:string;revision?:number;tripId?:string;tripRevision?:number;observed?:string};
export type Session = {user:Member|null;csrf?:string|null};

export const copy = <T,>(value:T):T => JSON.parse(JSON.stringify(value));
export const memberKey = memberIdentity;
export const sessionKey = sessionIdentity;
export const recordVersions = (journey:Journey) => JSON.stringify([journey.revision,[journey.trip,...journey.tasks,...journey.shopping,...journey.events].filter(item=>item!==null).map(item=>[item.id,item.revision]).sort((a,b)=>String(a[0]).localeCompare(String(b[0])))]);
export class SessionChangedError extends Error {}
export async function readForMember<T>(path:string,actor:string,fetcher:<V>(path:string)=>Promise<V>,current:()=>boolean):Promise<T> {
  const before=await fetcher<Session>('/me');
  if(!current()||before.user?.role!=='member'||memberKey(before.user)!==actor)throw new SessionChangedError('登录身份已变化，请重新打开旅行');
  const value=await fetcher<T>(path),after=await fetcher<Session>('/me');
  if(!current()||sessionKey(before)!==sessionKey(after))throw new SessionChangedError('登录身份已变化，请重新打开旅行');
  return value;
}
export const amountText = (cents:number) => `${Math.floor(cents/100)}.${String(cents%100).padStart(2,'0')}`;
export function toCents(raw:string):number {
  const value=raw.trim();
  if(!/^\d{1,10}(\.\d{1,2})?$/.test(value))throw new Error('金额请用非负数字，最多两位小数');
  const [whole,fraction='']=value.split('.'), cents=Number(whole)*100+Number(fraction.padEnd(2,'0'));
  if(!Number.isSafeInteger(cents)||cents>100000000000)throw new Error('金额超出允许范围');
  return cents;
}
export function validDay(value:string):boolean {
  if(!/^(20\d{2}|2100)-\d{2}-\d{2}$/.test(value))return false;
  const day=new Date(value+'T00:00:00Z');
  return Number.isFinite(day.getTime())&&day.toISOString().slice(0,10)===value;
}
export function shoppingSchedule(value:{due?:unknown;priority?:unknown}):{due:string;priority:ShoppingPriority} {
  const due=value.due===undefined?'':value.due, priority=value.priority===undefined?'normal':value.priority;
  if(typeof due!=='string'||due!==''&&!validDay(due))throw new Error('采购截止请填写有效的 YYYY-MM-DD（2000—2100 年），或留空');
  if(priority!=='low'&&priority!=='normal'&&priority!=='high')throw new Error('采购优先级请选择低、普通或高');
  return {due,priority};
}
export const shoppingPriorityLabel=(priority:ShoppingPriority='normal')=>({low:'低优先级',normal:'普通',high:'高优先级'})[priority];
export function shoppingScheduleText(item:{due?:string;priority?:ShoppingPriority;done?:boolean},today='',showNormal=false):string {
  const date=item.due?`${item.due}${!item.done&&today&&item.due<today?' · 已逾期':!item.done&&item.due===today?' · 今天截止':''}`:'未设截止日';
  return date+((item.priority&&item.priority!=='normal')||showNormal?' · '+shoppingPriorityLabel(item.priority):'');
}
export function compareShoppingItems(a:ListItem,b:ListItem):number {
  const rank={high:0,normal:1,low:2};
  // Stable ties retain the source order, including legacy records without dates.
  return Number(a.done)-Number(b.done)||(a.due||'9999').localeCompare(b.due||'9999')||rank[a.priority??'normal']-rank[b.priority??'normal'];
}
export function tripDays(start:string,end:string):number {
  if(!validDay(start)||!validDay(end))throw new Error('日期请用有效的 YYYY-MM-DD（2000—2100 年）');
  const days=(Date.parse(end+'T00:00:00Z')-Date.parse(start+'T00:00:00Z'))/86400000+1;
  if(days<1||days>367)throw new Error('返程不能早于出发，单次旅行最多 367 天');
  return days;
}
// UUID is an operation identity, never a secret. Do not fall back to time-only keys.
export function newKey():string {
  if(!globalThis.crypto?.getRandomValues)throw new Error('当前环境无法生成安全操作编号，请重新打开页面');
  return Array.from(globalThis.crypto.getRandomValues(new Uint8Array(16)),n=>n.toString(16).padStart(2,'0')).join('');
}
export function newDraft(people:Person[],day:string):Draft {
  return {plan:{title:'',start:day,end:day,international:false,memberIds:people.map(p=>p.id),budget:0,saved:0,paid:0,note:'',destinations:[{key:'destination-1',city:'',country:'',arrival:day,departure:day}],shopping:[]},budget:'0.00',saved:'0.00',paid:'0.00'};
}
// This hand-off is only a normalized, date-level NEW plan. Existing journeys
// must enter through editDraft/upgradeDraft and their fresh revision checks.
export function initialPlanningDraft(input:unknown,people:Person[]):Draft {
  const record=(value:unknown):Record<string,unknown>=>{if(!value||typeof value!=='object'||Array.isArray(value))throw new Error('旅行草案格式不正确，请返回助理重新整理');return value as Record<string,unknown>;};
  const text=(value:unknown,max:number)=>{if(typeof value!=='string'||Array.from(value).length>max)throw new Error('旅行草案字段不正确，请返回助理重新整理');return value;};
  const cents=(value:unknown)=>{if(!Number.isSafeInteger(value)||Number(value)<0||Number(value)>100000000000)throw new Error('旅行草案金额不正确');return value as number;};
  const rows=(value:unknown,max:number)=>{if(!Array.isArray(value)||value.length>max)throw new Error('旅行草案清单不正确');return value.map(record);};
  const keys=(value:Record<string,unknown>[]):(Record<string,unknown>&{key:string})[]=>{const seen=new Set<string>();return value.map(row=>{const key=text(row.key,64);if(!/^[A-Za-z0-9_-]{1,64}$/.test(key)||seen.has(key))throw new Error('旅行草案项目编号不正确');seen.add(key);return {...row,key};});};
  const source=record(input),raw=record(source.plan);
  if(['id','journeyId','revision','tripId','tripRevision','observed'].some(key=>Object.hasOwn(source,key)||Object.hasOwn(raw,key)))throw new Error('助理草案只能新建旅行，不能指定已有旅行');
  if(raw.schemaVersion!==undefined&&raw.schemaVersion!==1)throw new Error('助理草案只支持日期级新建旅行');
  if(typeof raw.international!=='boolean'||!Array.isArray(raw.memberIds)||raw.memberIds.some(id=>typeof id!=='string'))throw new Error('旅行草案成员或境外标记不正确');
  const plan:Plan={schemaVersion:1,title:text(raw.title,100),start:text(raw.start,10),end:text(raw.end,10),international:raw.international,memberIds:[...raw.memberIds] as string[],budget:cents(raw.budget),saved:cents(raw.saved),paid:cents(raw.paid),note:text(raw.note,2000),
    destinations:keys(rows(raw.destinations,20)).map(row=>({key:row.key,country:text(row.country,60),city:text(row.city,80),arrival:text(row.arrival,10),departure:text(row.departure,10)})),
    shopping:keys(rows(raw.shopping,100)).map(row=>({key:row.key,title:text(row.title,100),owner:text(row.owner,100),quantity:text(row.quantity,30),budget:row.budget===null?null:cents(row.budget),note:text(row.note,500),...shoppingSchedule({due:row.due,priority:row.priority})}))};
  if(!plan.destinations.length||new Set(plan.memberIds).size!==plan.memberIds.length)throw new Error('旅行草案目的地或成员不正确');
  if(raw.checklist!==undefined)plan.checklist=keys(rows(raw.checklist,100)).map(row=>{
    const result:Preparation={key:row.key,title:text(row.title,100),owner:text(row.owner,100),note:text(row.note,500)};
    if(row.due!==undefined)result.due=text(row.due,10);
    if(row.dueOffsetDays!==undefined){if(!Number.isSafeInteger(row.dueOffsetDays)||Number(row.dueOffsetDays)<-730||Number(row.dueOffsetDays)>366)throw new Error('旅行草案准备截止不正确');result.dueOffsetDays=row.dueOffsetDays as number;}
    if(row.category!==undefined)result.category=text(row.category,40);
    return result;
  });
  if(raw.segments!==undefined)plan.segments=keys(rows(raw.segments,100)).map(row=>({key:row.key,title:text(row.title,100),start:text(row.start,10),end:text(row.end,10),location:text(row.location,200),note:text(row.note,500)}));
  const draft:Draft={plan,budget:amountText(plan.budget),saved:amountText(plan.saved),paid:amountText(plan.paid)};
  previewPayload(draft,people);
  return draft;
}
export function purchaseBudgetText(draft:Draft,row:Purchase):string {
  return draft.purchaseBudgets&&Object.hasOwn(draft.purchaseBudgets,row.key)?draft.purchaseBudgets[row.key]:(row.budget===null?'':amountText(row.budget));
}
export function editDraft(journey:Journey):Draft {
  const plan=copy(journey.plan), trip=journey.trip;
  if(trip)Object.assign(plan,{title:trip.title,start:trip.start,end:trip.end,budget:trip.budget,saved:trip.saved,paid:trip.paid,note:trip.note||''});
  // Keep current task/purchase edits, while preserving stable workflow keys and time metadata.
  plan.checklist=plan.checklist?.map(row=>{
    const live=journey.tasks.find(item=>item.workflowKey==='task:'+row.key);
    return live?{...row,title:live.title,owner:live.owner,due:live.due||row.due,note:live.note||''}:row;
  });
  plan.shopping=plan.shopping.map(row=>{
    const live=journey.shopping.find(item=>item.workflowKey==='shopping:'+row.key);
    return live?{...row,title:live.title,owner:live.owner,quantity:live.quantity||row.quantity,budget:live.budget??null,note:live.note||'',...shoppingSchedule(live)}:{...row,...shoppingSchedule(row)};
  });
  return {plan,budget:amountText(plan.budget),saved:amountText(plan.saved),paid:amountText(plan.paid),journeyId:journey.id,revision:journey.revision,observed:recordVersions(journey)};
}
export function upgradeDraft(trip:Trip,people:Person[],tasks:ListItem[]):Draft {
  const draft=newDraft(people,trip.start);
  Object.assign(draft.plan,{title:trip.title,end:trip.end,note:trip.note||'',budget:trip.budget,paid:trip.paid,saved:trip.saved});
  Object.assign(draft.plan.destinations[0],{city:trip.destination||'',departure:trip.end});
  // Explicitly adopt only local preparation; remote tasks retain their original ownership.
  draft.plan.checklist=tasks.filter(task=>task.tripId===trip.id&&!task.sync).map(task=>({key:'existing-'+task.id,title:task.title,owner:task.owner,...(task.due?{due:task.due}:{dueOffsetDays:-7}),note:task.note||'',category:'preparation'}));
  return {...draft,budget:amountText(trip.budget),saved:amountText(trip.saved),paid:amountText(trip.paid),tripId:trip.id,tripRevision:trip.revision};
}
export function previewPayload(draft:Draft,people:Person[]) {
  const plan=copy(draft.plan); tripDays(plan.start,plan.end);
  plan.title=plan.title.trim(); if(!plan.title)throw new Error('先填写旅行名称');
  if(!plan.memberIds.length||plan.memberIds.some(id=>!people.some(p=>p.id===id)))throw new Error('请选择当前家庭的出行成员');
  if([...(plan.checklist||[]),...plan.shopping].some(row=>row.owner!=='shared'&&!people.some(p=>p.id===row.owner)))throw new Error('准备与采购负责人须为一起或当前家庭成员');
  plan.shopping=plan.shopping.map(row=>{const raw=purchaseBudgetText(draft,row);return {...row,budget:raw.trim()===''?null:toCents(raw),...shoppingSchedule(row)};});
  Object.assign(plan,{budget:toCents(draft.budget),saved:toCents(draft.saved),paid:toCents(draft.paid)});
  return {plan,...(draft.journeyId?{journeyId:draft.journeyId,revision:draft.revision}:draft.tripId?{tripId:draft.tripId,tripRevision:draft.tripRevision}:{})};
}
export function summaryCounts(counts:Record<string,number>):string {
  return (['trips','events','tasks','shopping'] as const).filter(key=>counts[key]).map(key=>`${counts[key]} ${({trips:'趟旅行',events:'项安排',tasks:'项准备',shopping:'件采购'})[key]}`).join('、')||'无';
}
export function eventDates(event:CalendarEvent):string {
  if(!event.allDay)return new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(event.start))+' — '+new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(event.end))+'（北京时间）';
  const start=event.start.slice(0,10), exclusive=event.end.slice(0,10);
  const inclusive=new Date(Date.parse(exclusive+'T00:00:00Z')-86400000).toISOString().slice(0,10);
  return start===inclusive?start+' · 全天':start+' — '+inclusive+' · 全天';
}
