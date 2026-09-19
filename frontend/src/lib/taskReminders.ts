import type {ListItem} from './types';

export type ReminderFilter='unread'|'all';
export type ReminderTask=Pick<ListItem,'id'|'title'|'owner'|'due'|'revision'|'dependsOn'|'blockedBy'|'dependencyStatus'|'sync'>;
export type TaskReminder={task:ReminderTask;occurrence:string;revision:number;eligibleAt:string;status:'unread'|'read'|'snoozed';readAt:string|null;snoozedUntil:string|null};
export type ReminderPage={items:TaskReminder[];unreadCount:number;total:number;page:number;pageSize:40;hasMore:boolean;serverNow:string;timeZone:'Asia/Shanghai';worker:{lastCheckedAt:string|null;stale:boolean;capacityBlocked?:boolean}};
export type ReminderIntent={taskId:string;requestId:string;occurrence:string;revision:number;action:'read'|'snooze';snoozedUntil?:string};
export type ReminderOperation=Omit<ReminderIntent,'snoozedUntil'>&{readAt:string|null;snoozedUntil:string|null;committedAt:string};
export type ReminderRecovery={intent:ReminderIntent;filter:ReminderFilter;page:number};
const bad=():never=>{throw new Error('提醒资料暂时无法核对，请重新读取。');};
const obj=(v:unknown):Record<string,unknown>=>v!==null&&typeof v==='object'&&!Array.isArray(v)?v as Record<string,unknown>:bad();
const text=(v:unknown,max=128):string=>typeof v==='string'&&v.length>0&&v.length<=max?v:bad();
const taskTitle=(v:unknown):string=>typeof v==='string'&&v.length>0&&Array.from(v).length<=2048?v:bad();
const integer=(v:unknown,min=0):number=>typeof v==='number'&&Number.isSafeInteger(v)&&v>=min?v:bad();
const hex=(v:unknown,len:number)=>typeof v==='string'&&new RegExp('^[a-f0-9]{'+len+'}$').test(v)?v:bad();
const stamp=(v:unknown):string=>typeof v==='string'&&/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$/.test(v)&&Number.isFinite(Date.parse(v))?v:bad();
const nullableStamp=(v:unknown)=>v===null?null:stamp(v);
const flag=(v:unknown)=>typeof v==='boolean'?v:bad();
const ids=(v:unknown)=>{if(!Array.isArray(v)||v.length>20)bad();const result=(v as unknown[]).map(x=>text(x));if(new Set(result).size!==result.length)bad();return result;};
export const reminderQuery=(filter:ReminderFilter,page:number)=>'/task-reminders?filter='+filter+'&page='+integer(page);
export function readReminderPage(raw:unknown,filter:ReminderFilter,page:number,memberId:string):ReminderPage {
  const v=obj(raw),now=stamp(v.serverNow),worker=obj(v.worker);
  if(v.page!==page||v.pageSize!==40||v.timeZone!=='Asia/Shanghai'||!Array.isArray(v.items)||v.items.length>40)bad();
  const items=(v.items as unknown[]).map(raw=>{
    const row=obj(raw),t=obj(row.task),due=text(t.due,10);
    if(!/^\d{4}-\d{2}-\d{2}$/.test(due)||!Number.isFinite(Date.parse(due+'T00:00:00Z'))||new Date(due+'T00:00:00Z').toISOString().slice(0,10)!==due||![memberId,'shared'].includes(String(t.owner)))bad();
    if(!['ready','blocked','done'].includes(String(t.dependencyStatus))||!['unread','read','snoozed'].includes(String(row.status))||filter==='unread'&&row.status!=='unread')bad();
    const task:ReminderTask={id:text(t.id),title:taskTitle(t.title),owner:text(t.owner),due,revision:integer(t.revision,1),dependsOn:ids(t.dependsOn),blockedBy:ids(t.blockedBy),dependencyStatus:t.dependencyStatus as ReminderTask['dependencyStatus']};
    if(t.sync!==undefined)task.sync=obj(t.sync);
    const result:TaskReminder={task,occurrence:hex(row.occurrence,64),revision:integer(row.revision),eligibleAt:stamp(row.eligibleAt),status:row.status as TaskReminder['status'],readAt:nullableStamp(row.readAt),snoozedUntil:nullableStamp(row.snoozedUntil)};
    if(result.status==='read'&&!result.readAt||result.status==='snoozed'&&(!result.snoozedUntil||Date.parse(result.snoozedUntil)<=Date.parse(now)))bad();
    return result;
  });
  if(new Set(items.map(row=>row.task.id)).size!==items.length)bad();
  const total=integer(v.total),unreadCount=integer(v.unreadCount),hasMore=flag(v.hasMore);
  if(total<items.length||hasMore!==(page*40+items.length<total))bad();
  return{items,total,unreadCount,page,pageSize:40,hasMore,serverNow:now,timeZone:'Asia/Shanghai',worker:{lastCheckedAt:nullableStamp(worker.lastCheckedAt),stale:flag(worker.stale),...(worker.capacityBlocked===undefined?{}:{capacityBlocked:flag(worker.capacityBlocked)})}};
}
export function snoozeTime(serverNow:string,choice:'hour'|'tomorrow'):string {
  const now=Date.parse(stamp(serverNow));
  if(choice==='hour')return new Date(now+3600000).toISOString();
  const shanghai=new Date(now+8*3600000),next=Date.UTC(shanghai.getUTCFullYear(),shanghai.getUTCMonth(),shanghai.getUTCDate()+1,1);
  return new Date(next).toISOString();
}
export function reminderIntent(row:TaskReminder,action:'read'|'snooze',serverNow:string,choice:'hour'|'tomorrow'='hour'):ReminderIntent {
  if(!globalThis.crypto?.getRandomValues)throw new Error('请通过安全连接打开看板后再操作。');
  const requestId=Array.from(globalThis.crypto.getRandomValues(new Uint8Array(16)),n=>n.toString(16).padStart(2,'0')).join('');
  return Object.freeze({taskId:row.task.id,requestId,occurrence:row.occurrence,revision:row.revision,action,...(action==='snooze'?{snoozedUntil:snoozeTime(serverNow,choice)}:{})});
}
export function reminderBody(intent:ReminderIntent){const {taskId,...body}=intent;return body;}
export function readReminderOperation(raw:unknown,intent:ReminderIntent):ReminderOperation {
  const v=obj(obj(raw).operation);
  if(v.requestId!==intent.requestId||v.taskId!==intent.taskId||v.occurrence!==intent.occurrence||v.action!==intent.action||v.revision!==intent.revision+1)bad();
  const readAt=nullableStamp(v.readAt),snoozedUntil=nullableStamp(v.snoozedUntil);
  if(intent.action==='read'&&(!readAt||snoozedUntil!==null)||intent.action==='snooze'&&(readAt!==null||!snoozedUntil||Date.parse(snoozedUntil)!==Date.parse(intent.snoozedUntil!)))bad();
  return{...intent,revision:integer(v.revision,1),readAt,snoozedUntil,committedAt:stamp(v.committedAt)};
}

// One tab-scoped minimal envelope. No title, task notes, CSRF or raw identity.
const KEY='family.task-reminder-recovery.v1';
const storageError=()=>new Error('无法保留操作恢复记录，请允许此网站存储后重试。');
const storage=()=>{try{if(typeof sessionStorage==='undefined')throw storageError();return sessionStorage;}catch{throw storageError();}};
export async function reminderScope(identity:string):Promise<string>{
  if(!globalThis.crypto?.subtle)throw storageError();
  const digest=await globalThis.crypto.subtle.digest('SHA-256',new TextEncoder().encode(identity));
  return Array.from(new Uint8Array(digest),n=>n.toString(16).padStart(2,'0')).join('');
}
function readRecovery(raw:unknown):ReminderRecovery {
  const v=obj(raw),i=obj(v.intent);
  if(!['unread','all'].includes(String(v.filter))||!['read','snooze'].includes(String(i.action)))bad();
  const intent:ReminderIntent={taskId:text(i.taskId),requestId:hex(i.requestId,32),occurrence:hex(i.occurrence,64),revision:integer(i.revision),action:i.action as ReminderIntent['action']};
  if(intent.action==='snooze')intent.snoozedUntil=stamp(i.snoozedUntil);else if(i.snoozedUntil!==undefined)bad();
  return{intent:Object.freeze(intent),filter:v.filter as ReminderFilter,page:integer(v.page)};
}
export function loadReminderRecovery(scope:string):ReminderRecovery|null {
  const store=storage();let raw:string|null;
  try{raw=store.getItem(KEY);}catch{throw storageError();}if(!raw)return null;
  let v:Record<string,unknown>;try{v=obj(JSON.parse(raw));}catch{throw storageError();}
  // Called only after /me has confirmed the current member.
  if(v.scope!==scope){try{store.removeItem(KEY);}catch{throw storageError();}return null;}
  try{if(v.version!==1)bad();return readRecovery(v.recovery);}catch{throw storageError();}
}
export function saveReminderRecovery(scope:string,recovery:ReminderRecovery):void {
  const value=JSON.stringify({version:1,scope:hex(scope,64),recovery:readRecovery(recovery)});
  try{const store=storage();store.setItem(KEY,value);if(store.getItem(KEY)!==value)throw storageError();}catch{throw storageError();}
}
export function clearReminderRecovery(scope:string):void {
  try{const store=storage(),raw=store.getItem(KEY);if(raw&&obj(JSON.parse(raw)).scope===scope)store.removeItem(KEY);}catch{throw storageError();}
}
export async function forgetReminderIdentity(identity:string):Promise<void>{clearReminderRecovery(await reminderScope(identity));}
