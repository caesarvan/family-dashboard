export type TaskContent = {title:string;note:string;due:string;done:boolean};
export type PublishTask = TaskContent & {id:string;revision:number;owner:string;tripId:string;journeyId:string;reconnect?:boolean};
export type TaskSource = {id:string;name:string;provider:'microsoft'|'google';accountName:string;accountOwner:string;primary:boolean;writeAuthorized:boolean};
export type TaskPublication = {id:string;entityId:string;sourceId:string;provider:string;status:string;error:string;owner:string;accountOwner:string;updatedAt:string;canManage:boolean;localChangesPending:boolean|null;reconnectSourceIds:string[]};
export type TaskState = {journeyId:string;tasks:PublishTask[];sources:TaskSource[];publications:TaskPublication[];note:string;intervalSeconds:number};
export type TaskPreview = {tasks:PublishTask[];source:TaskSource;previewToken:string;note:string};
export type TaskComparison = {local:TaskContent;remote:TaskContent;previewToken:string};
export type TaskAction = 'pause'|'resume'|'retry'|'conflict';
const object=(value:unknown):value is Record<string,unknown>=>!!value&&typeof value==='object'&&!Array.isArray(value);
const text=(value:unknown,max=10000):value is string=>typeof value==='string'&&value.length<=max;
export const taskId=(value:unknown):value is string=>typeof value==='string'&&/^[A-Za-z0-9_-]{1,128}$/.test(value);
const invalid=()=>new Error('待办同步数据无法核对，请刷新状态。');
const unique=(values:string[])=>new Set(values).size===values.length;
const day=(value:unknown)=>typeof value==='string'&&(value===''||/^\d{4}-\d{2}-\d{2}$/.test(value)&&Number.isFinite(Date.parse(value+'T12:00:00Z'))&&new Date(value+'T12:00:00Z').toISOString().slice(0,10)===value);
function content(value:unknown):boolean {
  return object(value)&&text(value.title,100)&&!!value.title&&text(value.note,500)&&day(value.due)&&typeof value.done==='boolean';
}
function task(value:unknown):value is PublishTask {
  return content(value)&&object(value)&&taskId(value.id)&&Number.isSafeInteger(value.revision)&&Number(value.revision)>0
    &&taskId(value.owner)&&text(value.tripId,128)&&text(value.journeyId,128)&&(value.reconnect===undefined||typeof value.reconnect==='boolean');
}
function source(value:unknown):value is TaskSource {
  return object(value)&&taskId(value.id)&&text(value.name,1000)&&text(value.accountName,1000)&&taskId(value.accountOwner)
    &&['microsoft','google'].includes(String(value.provider))&&typeof value.primary==='boolean'&&typeof value.writeAuthorized==='boolean';
}
function tasks(value:unknown):value is PublishTask[] {
  return Array.isArray(value)&&value.length<=100&&value.every(task)&&unique(value.map(row=>row.id));
}
export function readTaskState(value:unknown,journeyId:string):TaskState {
  if(!object(value)||value.journeyId!==journeyId||!tasks(value.tasks)||!value.tasks.every(row=>row.journeyId===journeyId)
    ||!Array.isArray(value.sources)||value.sources.length>2000||!value.sources.every(source)||!unique(value.sources.map(row=>row.id))
    ||!Array.isArray(value.publications)||value.publications.length>2000||!text(value.note)||!Number.isSafeInteger(value.intervalSeconds)||Number(value.intervalSeconds)<1)throw invalid();
  const ids=new Set(value.tasks.map(row=>row.id));
  for(const row of value.publications)if(!object(row)||!taskId(row.id)||!taskId(row.entityId)||!ids.has(row.entityId)||!taskId(row.sourceId)
    ||!text(row.provider,30)||!text(row.status,60)||!text(row.error)||!taskId(row.owner)||!taskId(row.accountOwner)||!text(row.updatedAt,100)
    ||typeof row.canManage!=='boolean'||row.localChangesPending!==null&&typeof row.localChangesPending!=='boolean'
    ||!Array.isArray(row.reconnectSourceIds)||!row.reconnectSourceIds.every(taskId)||!unique(row.reconnectSourceIds))throw invalid();
  if(!unique(value.publications.map(row=>row.id))||!unique(value.publications.map(row=>row.entityId)))throw invalid();
  return value as TaskState;
}
export function readTaskPreview(value:unknown,sourceId:string,entityIds:string[],journeyId:string):TaskPreview {
  if(!object(value)||!source(value.source)||value.source.id!==sourceId||!tasks(value.tasks)||!value.tasks.length
    ||value.tasks.length!==entityIds.length||!value.tasks.every(row=>entityIds.includes(row.id)&&row.journeyId===journeyId&&typeof row.reconnect==='boolean')
    ||!text(value.previewToken,16000)||!value.previewToken||!text(value.note))throw invalid();
  return value as TaskPreview;
}
export function readTaskComparison(value:unknown):TaskComparison {
  if(!object(value)||!content(value.local)||!content(value.remote)||!text(value.previewToken,16000)||!value.previewToken)throw invalid();
  return value as TaskComparison;
}
export function validTaskReceipt(value:unknown,count:number):boolean {
  return object(value)&&value.queued===true&&typeof value.needsAuthorization==='boolean'&&Array.isArray(value.publicationIds)
    &&value.publicationIds.length===count&&value.publicationIds.every(taskId)&&unique(value.publicationIds);
}
export function selectableTask(state:TaskState,id:string,sourceId:string):boolean {
  if(!state.sources.some(row=>row.id===sourceId)||!state.tasks.some(row=>row.id===id))return false;
  const publication=state.publications.find(row=>row.entityId===id);
  return !publication||publication.status==='disconnected'&&publication.canManage&&publication.reconnectSourceIds.includes(sourceId);
}
export const taskStatuses:Record<string,string>={pending:'等待同步',publishing:'正在同步',published:'云端已确认',retry:'暂时失败，等待重试',
  uncertain:'提交结果未知，正在核对',needs_review:'需要核对原清单',needs_authorization:'等待账户拥有者授权',permission_denied:'没有清单编辑权限',
  conflict:'两边内容不同，请核对',paused:'已暂停同步',disconnected:'原清单已断开',remote_deleted:'云端已移除，本地保留',local_deleted:'本地已移除，云端保留'};
export function taskStatus(row:TaskPublication):string {
  if(row.status==='published'&&row.localChangesPending!==false)return row.localChangesPending?'本地有新修改，等待云端确认':'当前本地内容待核对';
  return taskStatuses[row.status]||'状态暂不支持，请刷新核对';
}
export function taskActions(row:TaskPublication):TaskAction[] {
  if(!row.canManage||!Object.hasOwn(taskStatuses,row.status)||['local_deleted','remote_deleted','disconnected'].includes(row.status))return [];
  if(row.status==='paused')return ['resume'];
  if(row.status==='conflict')return ['conflict','pause'];
  return [...(['retry','uncertain','needs_review','needs_authorization','permission_denied'].includes(row.status)?['retry' as const]:[]),'pause'];
}
export function confirmationObserved(state:TaskState,preview:TaskPreview):boolean {
  return preview.tasks.every(task=>state.publications.some(row=>row.entityId===task.id&&row.sourceId===preview.source.id
    &&row.provider===preview.source.provider&&row.status!=='disconnected'));
}
