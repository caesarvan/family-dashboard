import React,{useCallback,useEffect,useRef,useState} from 'react';
import {AppState,StyleSheet,View} from 'react-native';
import {useFocusEffect} from 'expo-router';
import {ActivityIndicator,Button,Divider,SegmentedButtons,Text} from 'react-native-paper';
import {ApiError,request} from '../lib/api';
import {useHousehold} from '../lib/household';
import {PlaceDiscarded,PlaceFence,type PlaceSession} from '../lib/places';
import {clearReminderRecovery,loadReminderRecovery,readReminderOperation,readReminderPage,reminderBody,reminderIntent,reminderQuery,reminderScope,saveReminderRecovery,
  type ReminderFilter,type ReminderPage,type ReminderRecovery,type TaskReminder} from '../lib/taskReminders';
import type {FamilyState,ListItem} from '../lib/types';
import {EmptyState,PageHeader,SectionCard} from './components';

type Props={onBack:()=>void;onOpenTask:(task:ListItem)=>void};
const foreground=()=>typeof document==='undefined'||!document.hidden;
const connected=()=>typeof navigator==='undefined'||navigator.onLine!==false;
const message=(e:unknown)=>e instanceof Error?e.message:'暂时无法读取提醒，请重新核对。';
const time=(value:string)=>new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(value));
export default function TaskRemindersPanel(props:Props){
  const household=useHousehold();
  if(household.user?.role!=='member')return <EmptyState title="请使用成员账户查看本人提醒"/>;
  return <ReminderWorkspace key={household.identityKey} {...props} identityKey={household.identityKey}/>;
}
function ReminderWorkspace(props:Props&{identityKey:string}){
  const household=useHousehold(),latest=useRef(household);latest.current=household;
  const alive=useRef(false),focused=useRef(false),active=useRef(false),denied=useRef(false),epoch=useRef(0),working=useRef(false);
  const appActive=useRef(AppState.currentState!=='background'&&AppState.currentState!=='inactive');
  const fence=useRef(new PlaceFence(()=>request<PlaceSession>('/me'),props.identityKey));
  const scope=useRef(''),initialized=useRef(false),pending=useRef<ReminderRecovery|null>(null),view=useRef({filter:'unread' as ReminderFilter,page:0});
  const [filter,setFilter]=useState<ReminderFilter>('unread'),[page,setPage]=useState(0),[snapshot,setSnapshot]=useState<ReminderPage|null>(null);
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState(''),[recovery,setRecovery]=useState<ReminderRecovery|null>(null),[missing,setMissing]=useState(false);
  const current=()=>alive.current&&focused.current&&active.current&&!denied.current&&appActive.current&&foreground()&&connected()&&latest.current.online
    &&latest.current.user?.role==='member'&&latest.current.identityKey===props.identityKey;
  const guarded=<T,>(action:(csrf:string)=>Promise<T>,ticket=epoch.current)=>fence.current.run(action,()=>current()&&ticket===epoch.current);
  const locked=busy||!!recovery||!snapshot||!household.online;
  function conceal(){active.current=false;++epoch.current;fence.current.invalidate();setSnapshot(null);setMissing(false);}
  function fail(e:unknown){
    if(!alive.current)return;
    if(e instanceof PlaceDiscarded&&e.message==='identity'||e instanceof ApiError&&[401,403].includes(e.status)){
      conceal();denied.current=true;pending.current=null;setRecovery(null);setNotice('');
      if(scope.current)try{clearReminderRecovery(scope.current);}catch{/* Content stays concealed even when browser storage is blocked. */}
      setError('登录身份或权限已变化，请返回首页重新读取。');void latest.current.refresh();return;
    }
    if(e instanceof PlaceDiscarded)return;
    setError(message(e));
  }
  async function initialize(){
    if(initialized.current)return;
    const saved=await guarded(async()=>{
      const key=await reminderScope(props.identityKey);
      if(!current())throw new PlaceDiscarded();
      scope.current=key;return loadReminderRecovery(key);
    });
    initialized.current=true;
    if(saved){pending.current=saved;setRecovery(saved);view.current={filter:saved.filter,page:saved.page};setFilter(saved.filter);setPage(saved.page);}
  }
  function confirmed(){
    // Clear durable intent before enabling any further action. A storage failure
    // keeps recovery locked and the next attempt still queries the same receipt.
    clearReminderRecovery(scope.current);pending.current=null;setRecovery(null);setMissing(false);
    setNotice('这次提醒操作已确认。待办的完成状态没有改变。');
  }
  async function checkReceipt(){
    const saved=pending.current;if(!saved)return;
    const value=await guarded(async()=>{
      try{return await request<unknown>('/task-reminders/operations/'+saved.intent.requestId);}
      catch(e){if(e instanceof ApiError&&e.status===404)return null;throw e;}
    });
    if(value===null){setMissing(true);setNotice('还未找到这次操作的回执。可再次核对，或明确重试原操作。');return;}
    readReminderOperation(value,saved.intent);confirmed();
  }
  async function readList(){
    setSnapshot(null);
    const target={...view.current};
    const value=readReminderPage(await guarded(()=>request<unknown>(reminderQuery(target.filter,target.page))),target.filter,target.page,latest.current.user!.id);
    setSnapshot(value);
  }
  async function run(job:()=>Promise<void>){
    if(!current()||working.current)return;
    const ticket=epoch.current;working.current=true;setBusy(true);setError('');
    try{await job();}
    catch(e){if(alive.current&&ticket===epoch.current){fail(e);if(pending.current)setRecovery(pending.current);}}
    finally{working.current=false;if(alive.current){setBusy(false);if(ticket!==epoch.current&&current())void reload();}}
  }
  async function reload(){await run(async()=>{setSnapshot(null);await initialize();setMissing(false);await checkReceipt();await readList();});}
  function enter(){if(!alive.current||active.current||!focused.current||denied.current||!appActive.current||!foreground()||!connected()||!latest.current.online)return;active.current=true;void reload();}
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;active.current=false;++epoch.current;fence.current.invalidate();};},[]);
  useFocusEffect(useCallback(()=>{focused.current=true;enter();return()=>{focused.current=false;conceal();};},[]));
  useEffect(()=>{
    const visibility=()=>{if(foreground())enter();else conceal();},offline=()=>{conceal();setError('连接中断，联网后请重新核对提醒。');},online=()=>enter();
    if(typeof document!=='undefined')document.addEventListener('visibilitychange',visibility);
    if(typeof window!=='undefined'){window.addEventListener('offline',offline);window.addEventListener('online',online);}
    const sub=AppState.addEventListener('change',value=>{appActive.current=value==='active';if(appActive.current)enter();else conceal();});
    const timer=setInterval(()=>{if(current())void reload();},30000);
    return()=>{sub.remove();clearInterval(timer);if(typeof document!=='undefined')document.removeEventListener('visibilitychange',visibility);if(typeof window!=='undefined'){window.removeEventListener('offline',offline);window.removeEventListener('online',online);}};
  },[]);
  useEffect(()=>{if(household.online)enter();else conceal();},[household.online]);
  useEffect(()=>{if(initialized.current&&current())void reload();},[household.state?.revision]);
  function change(filter:ReminderFilter,page:number){if(locked)return;view.current={filter,page};setFilter(filter);setPage(page);setNotice('');void reload();}
  async function submit(){
    const saved=pending.current;if(!saved)return;
    try{
      const result=await guarded(csrf=>request<unknown>('/task-reminders/'+encodeURIComponent(saved.intent.taskId)+'/actions',
        {method:'POST',body:JSON.stringify(reminderBody(saved.intent))},csrf));
      readReminderOperation(result,saved.intent);confirmed();
    }catch(e){
      if(e instanceof ApiError&&[400,404,409,422,429].includes(e.status)){
        clearReminderRecovery(scope.current);pending.current=null;setRecovery(null);setMissing(false);
        setNotice(e.code==='reminder_capacity'?'这次操作未保存，提醒历史容量已满，请联系管理员整理。':'这次操作未保存，请核对最新提醒后再操作。');
        setSnapshot(null);
        try{await readList();}catch{/* Preserve the actual rejected-write explanation; retry is a read. */}
      }else if(pending.current&&current()){setMissing(false);setNotice('操作结果尚未确认，已保留核对记录。不会自动再次提交。');}
      throw e;
    }
    await readList();
  }
  async function act(row:TaskReminder,action:'read'|'snooze',choice:'hour'|'tomorrow'='hour'){
    if(locked||!snapshot)return;
    const serverNow=snapshot.serverNow;
    await run(async()=>{
      const saved={intent:reminderIntent(row,action,serverNow,choice),...view.current};
      // Store only after a fresh identity check, before the first possible POST.
      await guarded(async()=>{saveReminderRecovery(scope.current,saved);pending.current=saved;setRecovery(saved);});
      setMissing(false);setNotice('');await submit();
    });
  }
  async function retry(){
    if(!missing||!pending.current)return;
    await run(async()=>{setMissing(false);await checkReceipt();if(pending.current)await submit();});
  }
  async function open(row:TaskReminder){
    if(locked)return;
    await run(async()=>{
      const live=await guarded(()=>request<FamilyState>('/state'));
      const task=Array.isArray(live.tasks)?live.tasks.find(t=>t.id===row.task.id):undefined;
      if(!task||![latest.current.user!.id,'shared'].includes(task.owner)||task.done||!task.due||task.due!==row.task.due){setSnapshot(null);throw new Error('这项待办已变化或不再属于当前提醒，请刷新后重新选择。');}
      if(task.sync){setNotice('这项待办来自同步清单，请在原应用中修改。');return;}
      props.onOpenTask(task);
    });
  }
  return <View style={styles.page} testID="task-reminders-panel">
    <PageHeader title="我的提醒" description="看板内提醒 · 到期日 09:00（北京时间）" action={<Button onPress={props.onBack} disabled={busy} contentStyle={styles.button}>返回首页</Button>}/>
    <Text variant="bodySmall">仅显示分配给你或一起处理的到期待办；已读和稍后提醒只影响你。</Text>
    <View style={styles.row}><SegmentedButtons value={filter} onValueChange={value=>change(value as ReminderFilter,0)} buttons={[{value:'unread',label:'未读',disabled:locked},{value:'all',label:'全部',disabled:locked}]}/><Button icon="refresh" disabled={busy||!household.online||denied.current} onPress={()=>{if(!active.current)enter();else void reload();}} contentStyle={styles.button}>刷新提醒</Button></View>
    {busy&&<ActivityIndicator accessibilityLabel="正在核对提醒"/>}
    {!!error&&<Text accessibilityRole="alert">{error}</Text>}{!!notice&&<Text accessibilityLiveRegion="polite">{notice}</Text>}
    {recovery&&!denied.current&&<SectionCard title="一项操作待核对"><Text>已保留原操作。先核对回执，避免重复处理。</Text><View style={styles.row}><Button disabled={busy||!household.online} onPress={()=>void reload()} contentStyle={styles.button}>核对操作结果</Button>{missing&&<Button mode="outlined" disabled={busy||!household.online} onPress={()=>void retry()} contentStyle={styles.button}>重试原操作</Button>}</View></SectionCard>}
    {snapshot&&<>
      <Text>{snapshot.unreadCount} 项未读 · {snapshot.total} 项{filter==='unread'?'未读提醒':'到期提醒'}</Text>
      {snapshot.worker.stale&&<Text variant="bodySmall">提醒检查稍有延迟，当前到期待办仍可查看。{snapshot.worker.lastCheckedAt?'上次检查 '+time(snapshot.worker.lastCheckedAt)+'。':''}</Text>}
      {snapshot.worker.capacityBlocked&&<Text variant="bodySmall">部分提醒暂时无法记录，请联系管理员整理提醒历史。</Text>}
      {!snapshot.items.length?<EmptyState title={filter==='unread'?'暂时没有未读提醒':'暂时没有到期提醒'}/>:snapshot.items.map(row=><SectionCard key={row.task.id} title={row.task.title}>
        <View style={styles.fields}><Text variant="bodySmall">{row.task.due} 到期 · {row.task.owner==='shared'?'一起处理':'分配给我'} · {row.status==='read'?'已读':row.status==='snoozed'?'暂缓至 '+time(row.snoozedUntil!):'未读'}</Text>
          {row.task.dependencyStatus==='blocked'&&<Text variant="bodySmall">还有前置事项未完成，打开待办可核对。</Text>}
          <View style={styles.row}><Button disabled={locked} onPress={()=>void open(row)} contentStyle={styles.button}>打开待办</Button>{row.status!=='read'&&<Button disabled={locked} onPress={()=>void act(row,'read')} contentStyle={styles.button}>标为已读</Button>}<Button disabled={locked} onPress={()=>void act(row,'snooze','hour')} contentStyle={styles.button}>1 小时后提醒</Button><Button disabled={locked} onPress={()=>void act(row,'snooze','tomorrow')} contentStyle={styles.button}>明天 09:00 提醒</Button></View>
        </View>
      </SectionCard>)}
      <Divider/><View style={styles.row}><Button disabled={locked||page===0} onPress={()=>change(filter,page-1)} contentStyle={styles.button}>上一页</Button><Text>第 {page+1} 页</Text><Button disabled={locked||!snapshot.hasMore} onPress={()=>change(filter,page+1)} contentStyle={styles.button}>下一页</Button></View>
    </>}
  </View>;
}
const styles=StyleSheet.create({page:{gap:16,minWidth:0},row:{flexDirection:'row',flexWrap:'wrap',gap:8,alignItems:'center'},fields:{gap:8,minWidth:0},button:{minHeight:44}});
