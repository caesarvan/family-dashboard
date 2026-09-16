import type { CalendarEvent, ListItem, Member, Person, Trip } from './types';

export type Destination = {key:string;city:string;country:string;arrival:string;departure:string;timeZone?:string};
export type Preparation = {key:string;title:string;owner:string;due?:string;dueOffsetDays?:number;note:string;category?:string};
export type Purchase = {key:string;title:string;owner:string;quantity:string;budget:number|null;note:string};
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
export type Draft = {plan:Plan;budget:string;saved:string;paid:string;journeyId?:string;revision?:number;tripId?:string;tripRevision?:number;observed?:string};
export type Session = {user:Member|null;csrf?:string|null};

export const copy = <T,>(value:T):T => JSON.parse(JSON.stringify(value));
export const memberKey = (member:Member|null) => JSON.stringify([member?.role,member?.householdId,member?.id,member?.auth_version]);
export const sessionKey = (session:Session) => JSON.stringify([memberKey(session.user),session.csrf]);
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
    return live?{...row,title:live.title,owner:live.owner,quantity:live.quantity||row.quantity,budget:live.budget??null,note:live.note||''}:row;
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
