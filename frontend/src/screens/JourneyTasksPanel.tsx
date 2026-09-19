import React,{useCallback,useEffect,useRef,useState} from 'react';
import {AppState,StyleSheet,View} from 'react-native';
import {useFocusEffect} from 'expo-router';
import {ActivityIndicator,Button as PaperButton,Divider,Searchbar,Text} from 'react-native-paper';
import {ApiError,request} from '../lib/api';
import {useHousehold} from '../lib/household';
import {PlaceDiscarded,PlaceFence,type PlaceSession} from '../lib/places';
import {confirmationObserved,readTaskComparison,readTaskPreview,readTaskState,selectableTask,taskActions,taskStatus,validTaskReceipt,
  type PublishTask,type TaskAction,type TaskComparison,type TaskContent,type TaskPreview,type TaskPublication,type TaskState} from '../lib/taskPublish';
import {PageHeader,SectionCard} from '../ui/components';
import {SelectionRow} from '../ui/SelectionRow';

type Props={journeyId:string;onBack:()=>void;onConnections:()=>void;onPendingChange?:(value:boolean)=>void};
type Comparison={id:string;value:TaskComparison};
type Pending={kind:'confirm';preview:TaskPreview}|{kind:'action';id:string;action:'pause'|'resume'|'retry'|'conflict-confirm';resolution?:'local'|'remote'};
const foreground=()=>typeof document==='undefined'||!document.hidden;
const connected=()=>typeof navigator==='undefined'||navigator.onLine!==false;
const provider=(value:string)=>value==='microsoft'?'Microsoft To Do':'Google Tasks';
const errorText=(value:unknown)=>value instanceof Error?value.message:'暂时无法读取同步状态。';
class WriteRejected extends Error {}
const Button=(props:React.ComponentProps<typeof PaperButton>)=><PaperButton {...props} contentStyle={[{minHeight:44},props.contentStyle]}/>;

export default function JourneyTasksPanel(props:Props){
  const household=useHousehold();
  return <TaskWorkspace key={household.identityKey+':'+props.journeyId} {...props} identityKey={household.identityKey}/>;
}
function TaskWorkspace(props:Props&{identityKey:string}){
  const household=useHousehold(),latest=useRef(household);latest.current=household;
  const alive=useRef(false),focused=useRef(false),active=useRef(false),denied=useRef(false),epoch=useRef(0),working=useRef(false),reading=useRef(false);
  const appActive=useRef(AppState.currentState!=='background'&&AppState.currentState!=='inactive');
  const fence=useRef(new PlaceFence(()=>request<PlaceSession>('/me'),props.identityKey));
  const submitted=useRef<Pending|null>(null),recovered=useRef(false);
  const [snapshot,setSnapshot]=useState<TaskState|null>(null),[visible,setVisible]=useState(false),[busy,setBusy]=useState(false),[refreshing,setRefreshing]=useState(false);
  const [error,setError]=useState(''),[notice,setNotice]=useState(''),[selected,setSelected]=useState(''),[ids,setIds]=useState<string[]>([]);
  const [query,setQuery]=useState(''),[taskPage,setTaskPage]=useState(0),[sourcePage,setSourcePage]=useState(0),[statusPage,setStatusPage]=useState(0);
  const [preview,setPreview]=useState<TaskPreview|null>(null),[comparison,setComparison]=useState<Comparison|null>(null),[unknown,setUnknown]=useState(false),[checked,setChecked]=useState(false);
  const current=()=>alive.current&&active.current&&focused.current&&!denied.current&&appActive.current&&foreground()&&connected()
    &&latest.current.online&&latest.current.identityKey===props.identityKey&&latest.current.user?.role==='member';
  const locked=busy||refreshing||unknown||!household.online;
  // Use the parent's existing travel-operation navigation guard; selections and
  // unknown writes remain in this instance until explicitly discarded/read back.
  useEffect(()=>{props.onPendingChange?.(busy||unknown||ids.length>0||!!preview||!!comparison);},[busy,unknown,ids.length,preview,comparison]);
  function conceal(clear=false){
    active.current=false;++epoch.current;fence.current.invalidate();setVisible(false);setSnapshot(null);setBusy(false);
    if(submitted.current){setUnknown(true);setChecked(false);recovered.current=false;}
    if(clear){setSelected('');setIds([]);setQuery('');setPreview(null);setComparison(null);setNotice('');setUnknown(false);setChecked(false);submitted.current=null;}
  }
  function failed(failure:unknown){
    if(!current())return;
    if(failure instanceof PlaceDiscarded){
      if(failure.message==='identity'){conceal(true);denied.current=true;setError('登录身份已变化，请返回后重新打开旅行。');void latest.current.refresh();}
      return;
    }
    if(failure instanceof ApiError&&[401,403].includes(failure.status)){
      conceal();setError('身份或访问权限暂时无法核对，内容已隐藏。请重新读取。');void latest.current.refresh();return;
    }
    setError(errorText(failure));
  }
  const guarded=<T,>(action:(csrf:string)=>Promise<T>,ticket=epoch.current)=>fence.current.run(action,()=>current()&&ticket===epoch.current);
  const fetchState=async()=>readTaskState(await guarded(()=>request<unknown>('/task-publish/state?journeyId='+encodeURIComponent(props.journeyId))),props.journeyId);
  async function reload(background=false){
    if(!current()||working.current||reading.current)return;
    const ticket=epoch.current;reading.current=true;setRefreshing(true);if(!background)setBusy(true);
    try{
      const value=await fetchState();if(!current()||ticket!==epoch.current)return;
      setSnapshot(value);setVisible(true);setError('');
      const pending=submitted.current;
      if(pending){
        recovered.current=true;setChecked(true);
        if(pending.kind==='confirm'&&confirmationObserved(value,pending.preview)){
          submitted.current=null;setUnknown(false);setChecked(false);setPreview(null);setIds([]);
          setNotice('已找到刚才所选待办与原清单的连接。请在下方查看云端实际进度。');
        }else{setUnknown(true);setNotice('已读取当前状态，刚才操作的回执仍未确认。请先核对下方进度。');}
      }
    }catch(failure){if(ticket===epoch.current){failed(failure);setSnapshot(null);setVisible(false);}}
    finally{reading.current=false;setRefreshing(false);if(ticket===epoch.current)setBusy(false);else if(current()){setBusy(false);void reload();}}
  }
  function enter(){
    if(!alive.current||active.current||!focused.current||denied.current||!appActive.current||!foreground()||!connected()||!latest.current.online)return;
    active.current=true;void reload();
  }
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;active.current=false;++epoch.current;fence.current.invalidate();props.onPendingChange?.(false);};},[]);
  useFocusEffect(useCallback(()=>{focused.current=true;enter();return()=>{focused.current=false;conceal();};},[]));
  useEffect(()=>{
    const visibility=()=>{if(foreground())enter();else conceal();};
    const offline=()=>{conceal();setError('连接中断，内容已隐藏；联网后重新核对。');};
    const online=()=>enter();
    if(typeof document!=='undefined')document.addEventListener('visibilitychange',visibility);
    if(typeof window!=='undefined'){window.addEventListener('offline',offline);window.addEventListener('online',online);}
    const subscription=AppState.addEventListener('change',value=>{appActive.current=value==='active';if(appActive.current)enter();else conceal();});
    const timer=setInterval(()=>{if(current())void reload(true);},10000);
    return()=>{if(typeof document!=='undefined')document.removeEventListener('visibilitychange',visibility);
      if(typeof window!=='undefined'){window.removeEventListener('offline',offline);window.removeEventListener('online',online);}
      subscription.remove();clearInterval(timer);};
  },[]);
  useEffect(()=>{if(household.online)enter();else conceal();},[household.online]);
  async function post(path:string,payload:unknown,mutation=false){
    return guarded(async csrf=>{
      try{return await request<unknown>('/task-publish/'+path,{method:'POST',body:JSON.stringify(payload)},csrf);}
      catch(failure){if(mutation&&failure instanceof ApiError&&[400,403,404,409,422,429].includes(failure.status))throw new WriteRejected(failure.message);throw failure;}
    });
  }
  async function operation(action:()=>Promise<void>,allowUnknown=false){
    if(!current()||working.current||reading.current||unknown&&!allowUnknown)return;
    const ticket=epoch.current;working.current=true;setBusy(true);setError('');setNotice('');
    try{await action();}
    catch(failure){if(ticket===epoch.current&&current()){
      if(submitted.current&&failure instanceof WriteRejected){submitted.current=null;setUnknown(false);setChecked(false);}
      else if(submitted.current){setUnknown(true);setChecked(false);recovered.current=false;setNotice('提交结果暂未确认。先核对当前状态，不会自动再次提交。');}
      failed(failure);
    }}
    finally{
      working.current=false;
      if(ticket===epoch.current)setBusy(false);
      // A response discarded while hidden cannot overwrite a draft. Once back,
      // only a fresh read may expose content or recover a committed operation.
      else if(current()){setBusy(false);void reload();}
    }
  }
  function chooseSource(id:string){if(locked)return;setSelected(id);setIds([]);setPreview(null);setComparison(null);setTaskPage(0);setError('');}
  function chooseTask(id:string){if(locked||!snapshot||!selectableTask(snapshot,id,selected))return;setIds(old=>old.includes(id)?old.filter(value=>value!==id):[...old,id]);setPreview(null);setError('');}
  async function makePreview(){
    if(!snapshot||!selected||!ids.length)return;
    if(ids.some(id=>!selectableTask(snapshot,id,selected))){setError('所选待办或原清单已变化，请核对选择。');return;}
    const sourceId=selected,entityIds=[...ids];
    await operation(async()=>{const value=readTaskPreview(await post('preview',{sourceId,entityIds}),sourceId,entityIds,props.journeyId);setPreview(value);setComparison(null);setTaskPage(0);});
  }
  async function confirm(retry=false){
    const frozen=retry&&submitted.current?.kind==='confirm'?submitted.current.preview:preview;
    if(!frozen||retry&&!recovered.current)return;
    await operation(async()=>{
      submitted.current={kind:'confirm',preview:frozen};
      const result=await post('confirm',{previewToken:frozen.previewToken},true);
      if(!validTaskReceipt(result,frozen.tasks.length))throw new Error('同步请求的回执暂时无法核对。');
      submitted.current=null;setUnknown(false);setChecked(false);setPreview(null);setIds([]);
      setNotice('已连接选中待办。只有“云端已确认”才表示最新内容已到云端。');
      try{setSnapshot(await fetchState());}catch(failure){setNotice('连接请求已接收，进度暂时无法读取；请刷新状态。');throw failure;}
    },retry);
  }
  async function compare(row:TaskPublication){
    if(!taskActions(row).includes('conflict'))return;
    await operation(async()=>{setComparison({id:row.id,value:readTaskComparison(await post('publications/'+row.id+'/conflict-preview',{}))});setPreview(null);});
  }
  async function command(row:TaskPublication,action:Exclude<TaskAction,'conflict'>|'conflict-confirm',resolution?:'local'|'remote'){
    if(!row.canManage||action!=='conflict-confirm'&&!taskActions(row).includes(action)||action==='conflict-confirm'&&(!comparison||comparison.id!==row.id||!resolution))return;
    await operation(async()=>{
      submitted.current={kind:'action',id:row.id,action,resolution};
      const result=await post('publications/'+row.id+'/'+action,action==='conflict-confirm'?{previewToken:comparison!.value.previewToken,resolution}:{},true) as {paused?:boolean;queued?:boolean;adopted?:boolean};
      if(!result||(action==='pause'?result.paused!==true:action==='conflict-confirm'?result.queued!==(resolution==='local')||result.adopted!==(resolution==='remote'):result.queued!==true))throw new Error('操作回执暂时无法核对。');
      submitted.current=null;setUnknown(false);setChecked(false);setComparison(null);
      setNotice(action==='pause'?'已暂停后续同步，两边原事项保留。':resolution==='remote'?'已采用云端内容，本地负责人和旅行关联保持。':'已收到同步请求，请查看实际进度。');
      setSnapshot(await fetchState());if(resolution==='remote')void latest.current.refresh();
    });
  }
  function acknowledge(){if(!current()||busy||!unknown||!checked)return;submitted.current=null;setUnknown(false);setChecked(false);setPreview(null);setComparison(null);setIds([]);setNotice('保留当前已读取的状态。后续操作请重新选择并预览。');}
  function back(){if(busy||unknown)return;setIds([]);setPreview(null);setComparison(null);props.onPendingChange?.(false);props.onBack();}
  const person=(id:string)=>id==='shared'?'一起':household.state?.people.find(row=>row.id===id)?.name||'家庭成员';
  const fields=(row:TaskContent)=><View style={styles.fields}><Text variant="titleSmall">{row.title}</Text><Text variant="bodySmall">{row.due||'未设截止日期'} · {row.done?'已完成':'未完成'}</Text>{!!row.note&&<Text variant="bodySmall">{row.note}</Text>}</View>;
  const taskCard=(row:PublishTask)=><View style={styles.fields}>{fields(row)}<Text variant="bodySmall">看板负责人：{person(row.owner)}{row.reconnect?' · 重新连接原清单，保留云端原任务':''}</Text><Divider/></View>;
  const pager=(page:number,total:number,set:(value:number)=>void)=><View style={styles.row}><Button disabled={busy||page===0} onPress={()=>set(page-1)}>上一页</Button><Text>{page+1} / {Math.max(1,Math.ceil(total/12))} 页 · {total} 项</Text><Button disabled={busy||(page+1)*12>=total} onPress={()=>set(page+1)}>下一页</Button></View>;
  if(!visible||!snapshot)return <View style={styles.page}><PageHeader title="旅行待办同步"/>{busy&&<ActivityIndicator/>}<Text accessibilityRole="alert">{error||'正在核对旅行待办与可用清单…'}</Text><Button disabled={busy||!household.online} onPress={()=>{if(active.current)void reload();else enter();}}>重新读取同步状态</Button><Button disabled={busy||unknown} onPress={back}>返回旅行</Button></View>;
  const filtered=snapshot.tasks.filter(row=>(row.title+' '+row.note).toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  const page=Math.min(taskPage,Math.max(0,Math.ceil(filtered.length/12)-1)),sp=Math.min(sourcePage,Math.max(0,Math.ceil(snapshot.sources.length/12)-1)),pp=Math.min(statusPage,Math.max(0,Math.ceil(snapshot.publications.length/12)-1));
  const activeComparison=comparison&&snapshot.publications.find(row=>row.id===comparison.id);
  return <View style={styles.page}>
    <PageHeader title="旅行待办同步" description="把准备事项带到常用清单，继续使用同一份任务。"/>
    <View style={styles.row}><Button icon="arrow-left" disabled={busy||unknown} onPress={back}>{ids.length||preview||comparison?'取消本页选择并返回旅行':'返回旅行'}</Button><Button loading={busy} disabled={busy||refreshing} onPress={()=>void reload()}>{unknown?'核对当前状态':'刷新状态'}</Button></View>
    {!!error&&<Text accessibilityRole="alert">{error}</Text>}{!!notice&&<Text accessibilityLiveRegion="polite">{notice}</Text>}
    {unknown&&<SectionCard title="先核对刚才的操作"><Text>请求可能已经完成。下方显示当前进度，不会自动重新提交。</Text>{checked&&<View style={styles.fields}>{submitted.current?.kind==='confirm'&&<Button disabled={busy||refreshing} onPress={()=>void confirm(true)}>使用原确认再次核对</Button>}<Button disabled={busy} onPress={acknowledge}>已核对，保留当前状态</Button></View>}</SectionCard>}
    {!unknown&&(comparison?<SectionCard title="核对两边内容"><View style={styles.fields}><Text variant="titleMedium">看板本地</Text>{fields(comparison.value.local)}<Divider/><Text variant="titleMedium">云端清单</Text>{fields(comparison.value.remote)}<Text>采用云端内容仍保留看板负责人、旅行关联和原任务。</Text><View style={styles.row}><Button disabled={locked||!activeComparison?.canManage} onPress={()=>activeComparison&&void command(activeComparison,'conflict-confirm','remote')}>采用云端内容</Button><Button mode="contained" disabled={locked||!activeComparison?.canManage} onPress={()=>activeComparison&&void command(activeComparison,'conflict-confirm','local')}>确认以本地更新云端</Button><Button disabled={busy} onPress={()=>setComparison(null)}>暂不处理</Button></View></View></SectionCard>:preview?<SectionCard title="确认连接待办"><View style={styles.fields}><Text variant="titleMedium">{provider(preview.source.provider)} · {preview.source.name}{preview.source.primary?' · 家庭主清单':''}</Text><Text>{preview.source.accountName}</Text>{!preview.source.writeAuthorized&&<Text>账户尚缺待办写入权限。可以先确认，账户拥有者完成授权后才能同步。</Text>}{preview.tasks.map(row=><View key={row.id}>{taskCard(row)}</View>)}<Text variant="bodySmall">{preview.note}</Text><View style={styles.row}><Button disabled={busy} onPress={()=>setPreview(null)}>返回选择</Button><Button mode="contained" disabled={locked} onPress={()=>void confirm()}>确认连接这 {preview.tasks.length} 项待办</Button></View></View></SectionCard>:<SectionCard title="选择清单与准备事项"><View style={styles.fields}>
      <Text variant="bodySmall">看板负责人继续保留，不会转换成云端指派。仅勾选并确认的事项会持续同步。</Text>
      {snapshot.sources.length?<><View accessibilityRole="radiogroup" accessibilityLabel="目标待办清单">{snapshot.sources.slice(sp*12,(sp+1)*12).map(row=><SelectionRow key={row.id} kind="radio" label={provider(row.provider)+' · '+row.name+' · '+row.accountName+(row.primary?' · 家庭主清单':'')+(!row.writeAuthorized?' · 需授权':'')} accessibilityLabel={'选择清单：'+provider(row.provider)+' · '+row.name+' · '+row.accountName} checked={selected===row.id} disabled={locked} onPress={()=>chooseSource(row.id)}/>)}</View>{snapshot.sources.length>12&&pager(sp,snapshot.sources.length,setSourcePage)}
      {selected&&!snapshot.sources.some(row=>row.id===selected)&&<Text accessibilityRole="alert">原清单已不可用，请重新选择。原待办保持不变。</Text>}
      <Searchbar placeholder="搜索本次旅行准备" value={query} onChangeText={value=>{setQuery(value);setTaskPage(0);}}/>
      {filtered.slice(page*12,(page+1)*12).map(row=><View key={row.id} style={styles.fields}><SelectionRow kind="checkbox" label={row.title} accessibilityLabel={'选择待办：'+row.title} checked={ids.includes(row.id)} disabled={locked||!selectableTask(snapshot,row.id,selected)} onPress={()=>chooseTask(row.id)}/><Text variant="bodySmall">{person(row.owner)} · {row.due||'未设截止日期'} · {row.done?'已完成':'未完成'}{snapshot.publications.some(p=>p.entityId===row.id)?' · 已有连接，进度见下方':''}</Text></View>)}
      {!filtered.length&&<Text>{snapshot.tasks.length?'没有匹配的准备事项。':'这趟旅行暂无准备事项，请返回旅行添加。'}</Text>}{filtered.length>12&&pager(page,filtered.length,setTaskPage)}
      <Text>已选 {ids.length} 项</Text><Button mode="contained" disabled={locked||!ids.length||ids.some(id=>!selectableTask(snapshot,id,selected))} onPress={()=>void makePreview()}>预览选中待办</Button></>:<Text>还没有可用的清单。请先连接本人账户并选择清单，或由伴侣开放家庭主清单。</Text>}
      <Button disabled={locked||ids.length>0} onPress={props.onConnections}>管理账户与清单</Button>{ids.length>0&&<Button disabled={locked} onPress={()=>setIds([])}>清除本次选择</Button>}
    </View></SectionCard>)}
    <SectionCard title="同步进度"><View style={styles.fields}>{snapshot.publications.length?snapshot.publications.slice(pp*12,(pp+1)*12).map(row=><View key={row.id} style={styles.fields}><Text variant="titleSmall">{snapshot.tasks.find(task=>task.id===row.entityId)?.title||'原待办'}</Text><Text>{taskStatus(row)}</Text>{!!row.error&&<Text variant="bodySmall">{row.error}</Text>}{!row.canManage&&<Text variant="bodySmall">由确认成员或账户拥有者管理</Text>}<View style={styles.row}>{taskActions(row).map(action=><Button key={action} disabled={locked||!!preview||!!comparison} onPress={()=>action==='conflict'?void compare(row):void command(row,action)}>{action==='conflict'?'对比并处理':action==='pause'?'暂停同步':action==='resume'?'恢复同步':['uncertain','needs_review'].includes(row.status)?'再次核对原清单':'重试同步'}</Button>)}</View>{row.status==='disconnected'&&<Text variant="bodySmall">{row.reconnectSourceIds.length?'在上方选择原清单并勾选这项待办，再预览重连。':'请由账户拥有者恢复原清单授权，再刷新核对。'}</Text>}<Divider/></View>):<Text>尚未连接。选择原待办并确认后，会在这里显示进度。</Text>}{snapshot.publications.length>12&&pager(pp,snapshot.publications.length,setStatusPage)}</View></SectionCard>
  </View>;
}
const styles=StyleSheet.create({page:{gap:16,minWidth:0},fields:{gap:12,minWidth:0},row:{flexDirection:'row',flexWrap:'wrap',gap:8,alignItems:'center'}});
