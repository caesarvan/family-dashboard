export type CalendarSource = {id:string;name:string;accountId:string;provider:'google'|'microsoft';accountName:string;writeAuthorized:boolean};
export type PublishedEvent = {title:string;start:string;end:string;allDay:boolean;location:string;note:string};
export type LocalPublishedEvent = PublishedEvent & {id:string;revision:number};
export type Publication = {id:string;entityId:string;sourceId:string;provider:string;status:string;error:string;reviewRequired:0|1;localRevision:number|null;updatedAt:string;localChangesPending:boolean|null};
export type CalendarPublicationState = {journeyId:string;events:LocalPublishedEvent[];sources:CalendarSource[];publications:Publication[];note:string};
export type CalendarPreview = {events:LocalPublishedEvent[];source:CalendarSource;previewToken:string;note:string};
export type CalendarComparison = {local:PublishedEvent;remote:PublishedEvent|null;previous?:PublishedEvent|null;previewToken:string;note:string};
export const calendarStatuses:Record<string,string> = {
  pending:'等待同步',publishing:'正在写入云日历',published:'云端已确认',retry:'暂时失败，等待重试',
  needs_authorization:'等待日历写入授权',permission_denied:'没有此日历的编辑权限',conflict:'云端已修改，请核对',
  error:'同步失败，请核对',paused:'已停止同步',local_deleted:'本地已移除，云端保留',needs_review:'旅行时间变化，请核对',
};
const object=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v);
const text=(v:unknown,max=10000):v is string=>typeof v==='string'&&v.length<=max;
export const calendarId=(v:unknown):v is string=>typeof v==='string'&&/^[A-Za-z0-9_-]{1,100}$/.test(v);
const valid=()=>new Error('同步数据无法核对，请刷新状态。');
function event(value:unknown,local=false):boolean {
  if(!object(value)||!['title','start','end','location','note'].every(k=>text(value[k]))||typeof value.allDay!=='boolean')return false;
  if(!Number.isFinite(Date.parse(value.start as string))||!Number.isFinite(Date.parse(value.end as string))||Date.parse(value.end as string)<=Date.parse(value.start as string))return false;
  return !local||(calendarId(value.id)&&Number.isSafeInteger(value.revision)&&Number(value.revision)>0);
}
function source(value:unknown):boolean {
  return object(value)&&calendarId(value.id)&&calendarId(value.accountId)&&text(value.name,1000)&&text(value.accountName,1000)
    &&['google','microsoft'].includes(value.provider as string)&&typeof value.writeAuthorized==='boolean';
}
function events(value:unknown):boolean {
  return Array.isArray(value)&&value.length>=1&&value.length<=101&&value.every(v=>event(v,true))&&new Set(value.map(v=>v.id)).size===value.length;
}
export function readCalendarState(value:unknown,journeyId:string):CalendarPublicationState {
  if(!object(value)||value.journeyId!==journeyId||!events(value.events)||!Array.isArray(value.sources)||value.sources.length>2000
    ||!value.sources.every(source)||new Set(value.sources.map(v=>v.id)).size!==value.sources.length
    ||!Array.isArray(value.publications)||value.publications.length>10000||!text(value.note))throw valid();
  for(const row of value.publications)if(!object(row)||!calendarId(row.id)||!calendarId(row.entityId)||!calendarId(row.sourceId)
    ||!text(row.provider,30)||!text(row.status,60)||!text(row.error)||![0,1].includes(row.reviewRequired as number)
    ||row.localRevision!==null&&(!Number.isSafeInteger(row.localRevision)||Number(row.localRevision)<0)
    ||!text(row.updatedAt,100)||row.localChangesPending!==null&&typeof row.localChangesPending!=='boolean')throw valid();
  if(new Set(value.publications.map(v=>v.id)).size!==value.publications.length)throw valid();
  return value as CalendarPublicationState;
}
export function readCalendarPreview(value:unknown,sourceId:string):CalendarPreview {
  if(!object(value)||!source(value.source)||(value.source as CalendarSource).id!==sourceId||!events(value.events)
    ||!text(value.previewToken,6000)||!value.previewToken||!text(value.note))throw valid();
  return value as CalendarPreview;
}
export function readCalendarComparison(value:unknown,review:boolean):CalendarComparison {
  if(!object(value)||!event(value.local)||!(value.remote===null?review:event(value.remote))
    ||value.previous!==undefined&&value.previous!==null&&!event(value.previous)
    ||!text(value.previewToken,6000)||!value.previewToken||!text(value.note))throw valid();
  return value as CalendarComparison;
}
export function publicationStatus(row:Publication):string {
  if(row.reviewRequired)return '旅行时间变化，请核对';
  if(row.status==='published'&&row.localChangesPending===null)return '当前本地内容待核对，保留原云端状态';
  if(row.status==='published'&&row.localChangesPending)return '本地有新修改，等待云端确认';
  return calendarStatuses[row.status]||'状态暂不支持，请刷新核对';
}
export function publicationActions(row:Publication):('review'|'conflict'|'retry'|'resume'|'pause')[] {
  if(!Object.hasOwn(calendarStatuses,row.status)||row.status==='local_deleted')return [];
  const actions:('review'|'conflict'|'retry'|'resume'|'pause')[]=[];
  if(row.reviewRequired)actions.push('review');
  else if(row.status==='conflict')actions.push('conflict');
  else if(row.status==='paused')actions.push('resume');
  else if(['retry','error','needs_authorization','permission_denied'].includes(row.status))actions.push('retry');
  if(row.status!=='paused')actions.push('pause');
  return actions;
}
export function publishedEventRange(row:PublishedEvent):string {
  if(row.allDay){
    const start=row.start.slice(0,10),end=new Date(Date.parse(row.end.slice(0,10)+'T12:00:00Z')-86400000).toISOString().slice(0,10);
    return start===end?start+' · 全天':start+' — '+end+' · 全天';
  }
  // Keep the explicit server offset; browser timezone must not silently shift it.
  return row.start.replace('T',' ')+' → '+row.end.replace('T',' ');
}
export function validQueueReceipt(value:unknown):boolean {
  return object(value)&&value.queued===true&&Array.isArray(value.publicationIds)&&value.publicationIds.length>=1
    &&value.publicationIds.length<=101&&value.publicationIds.every(calendarId)&&typeof value.needsAuthorization==='boolean';
}
