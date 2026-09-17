import React,{useCallback,useEffect,useRef,useState} from 'react';
import {AppState,StyleSheet,View} from 'react-native';
import {useFocusEffect} from 'expo-router';
import {ActivityIndicator,Button,Divider,Searchbar,Text} from 'react-native-paper';
import {ApiError,request} from '../lib/api';
import {useHousehold} from '../lib/household';
import {openSyncProvider} from '../lib/navigation';
import {PlaceDiscarded,PlaceFence,type PlaceSession} from '../lib/places';
import {calendarId,publicationActions,publicationStatus,publishedEventRange,readCalendarComparison,readCalendarPreview,readCalendarState,validQueueReceipt,
  type CalendarComparison,type CalendarPreview,type CalendarPublicationState,type CalendarSource,type Publication,type PublishedEvent} from '../lib/calendarPublish';
import {PageHeader,SectionCard} from '../ui/components';
import {SelectionRow} from '../ui/SelectionRow';

type Props={journeyId:string;onBack:()=>void;onConnections:()=>void};
type Comparison={id:string;review:boolean;value:CalendarComparison};
const foreground=()=>typeof document==='undefined'||!document.hidden;
const connected=()=>typeof navigator==='undefined'||navigator.onLine!==false;
const provider=(value:string)=>value==='google'?'Google':value==='microsoft'?'Microsoft':value;
const errorText=(value:unknown)=>value instanceof Error?value.message:'暂时无法读取同步状态。';
export default function JourneyCalendarPanel(props:Props){
  const household=useHousehold();
  if(household.user?.role!=='member'||!calendarId(props.journeyId))return <Text>请重新打开本人旅行。</Text>;
  return <CalendarWorkspace key={household.identityKey+':'+props.journeyId} {...props} identityKey={household.identityKey}/>;
}
function CalendarWorkspace(props:Props&{identityKey:string}){
  const household=useHousehold(),latest=useRef(household);latest.current=household;
  const alive=useRef(false),active=useRef(false),focused=useRef(false),denied=useRef(false),epoch=useRef(0),working=useRef(false);
  const appActive=useRef(AppState.currentState!=='background'&&AppState.currentState!=='inactive');
  const fence=useRef(new PlaceFence(()=>request<PlaceSession>('/me'),props.identityKey));
  const submitted=useRef(false),reading=useRef(false);
  const [visible,setVisible]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
  const [snapshot,setSnapshot]=useState<CalendarPublicationState|null>(null),[selected,setSelected]=useState('');
  const [preview,setPreview]=useState<CalendarPreview|null>(null),[comparison,setComparison]=useState<Comparison|null>(null);
  const [unknown,setUnknown]=useState(false),[query,setQuery]=useState(''),[sourcePage,setSourcePage]=useState(0),[eventPage,setEventPage]=useState(0),[publicationPage,setPublicationPage]=useState(0);
  const current=()=>alive.current&&active.current&&focused.current&&!denied.current&&appActive.current&&foreground()&&connected()
    &&latest.current.online&&latest.current.identityKey===props.identityKey;
  const locked=busy||unknown||!household.online;
  function conceal(clear=false){
    active.current=false;++epoch.current;fence.current.invalidate();setVisible(false);setSnapshot(null);setBusy(false);
    working.current=false;reading.current=false;setPreview(null);setComparison(null);
    if(submitted.current)setUnknown(true);
    if(clear){setSelected('');setQuery('');setNotice('');setUnknown(false);submitted.current=false;}
  }
  function failed(failure:unknown){
    if(!current())return;
    if(failure instanceof PlaceDiscarded){
      if(failure.message==='identity'){conceal(true);denied.current=true;setError('登录身份已变化，请重新打开旅行。');void latest.current.refresh();}
      return;
    }
    setError(errorText(failure));
  }
  async function guarded<T>(action:(csrf:string)=>Promise<T>,ticket=epoch.current){
    return fence.current.run(action,()=>current()&&ticket===epoch.current);
  }
  async function fetchState(){
    return readCalendarState(await guarded(()=>request<unknown>('/calendar-publish/journeys/'+props.journeyId)),props.journeyId);
  }
  async function reload(background=false){
    if(!current()||working.current||reading.current)return;
    const ticket=epoch.current;reading.current=true;if(!background)setBusy(true);
    try{
      const value=await fetchState();
      if(!current()||ticket!==epoch.current)return;
      setSnapshot(value);setVisible(true);setError('');
      setSelected(old=>value.sources.some(s=>s.id===old)?old:'');
      setPublicationPage(old=>Math.min(old,Math.max(0,Math.ceil(value.publications.length/12)-1)));
      if(submitted.current){setUnknown(true);setNotice('已读取当前进度，刚才的提交结果仍需核对。不会自动再次提交。');}
    }catch(failure){if(ticket===epoch.current){failed(failure);setSnapshot(null);setVisible(false);}}
    finally{if(ticket===epoch.current){reading.current=false;setBusy(false);}}
  }
  function enter(){
    if(!alive.current||active.current||!focused.current||denied.current||!appActive.current||!foreground()||!connected()||!latest.current.online)return;
    active.current=true;void reload();
  }
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;active.current=false;++epoch.current;fence.current.invalidate();};},[]);
  useFocusEffect(useCallback(()=>{focused.current=true;enter();return()=>{focused.current=false;conceal(true);};},[]));
  useEffect(()=>{
    const visibility=()=>{if(foreground())enter();else conceal();};
    const offline=()=>{conceal();setError('连接中断，日历内容已隐藏。联网后重新核对。');};
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
  async function operation(action:()=>Promise<void>){
    if(!current()||working.current||reading.current||unknown)return;
    const ticket=epoch.current;working.current=true;setBusy(true);setError('');setNotice('');
    try{await action();}
    catch(failure){if(ticket===epoch.current){
      if(submitted.current&&failure instanceof ApiError&&failure.status>=400&&failure.status<500){submitted.current=false;setPreview(null);setComparison(null);}
      if(submitted.current){setUnknown(true);setPreview(null);setComparison(null);setNotice('提交结果尚未确认，请先核对当前状态，不要重复提交。');}failed(failure);
    }}
    finally{if(ticket===epoch.current){working.current=false;setBusy(false);}}
  }
  async function post(path:string,payload:unknown){
    return guarded(csrf=>request<unknown>('/calendar-publish/'+path,{method:'POST',body:JSON.stringify(payload)},csrf));
  }
  async function makePreview(){
    if(!selected)return;
    await operation(async()=>{
      const value=readCalendarPreview(await post('preview',{journeyId:props.journeyId,sourceId:selected}),selected);
      setPreview(value);setComparison(null);setEventPage(0);
    });
  }
  async function confirm(){
    if(!preview)return;
    const frozen={journeyId:props.journeyId,sourceId:preview.source.id,previewToken:preview.previewToken};
    await operation(async()=>{
      submitted.current=true;
      const result=await post('confirm',frozen);
      if(!validQueueReceipt(result))throw new Error('暂时无法确认同步请求的结果。');
      submitted.current=false;setPreview(null);setUnknown(false);
      setNotice('已加入同步队列。只有显示“云端已确认”才表示远端完成；本地新修改仍需等待确认。');
      try{setSnapshot(await fetchState());}catch(failure){setNotice('同步请求已接收，进度暂时无法读取；请刷新同步状态。');throw failure;}
    });
  }
  async function authorize(source:CalendarSource){
    await operation(async()=>{
      const value=await post('authorize',{accountId:source.accountId}) as {url?:string};
      if(!current()||typeof value?.url!=='string'||!openSyncProvider(value.url,source.provider))throw new Error('授权地址无法核对，请重新打开旅行。');
    });
  }
  async function compare(row:Publication,review:boolean){
    await operation(async()=>{
      const value=readCalendarComparison(await post('publications/'+row.id+'/'+(review?'review-preview':'conflict-preview'),{}),review);
      setPreview(null);setComparison({id:row.id,review,value});
    });
  }
  async function command(id:string,action:'pause'|'resume'|'retry'|'review-confirm'|'conflict-confirm',token?:string){
    await operation(async()=>{
      submitted.current=true;
      const result=await post('publications/'+id+'/'+action,token?{previewToken:token}:{});
      if(!result||typeof result!=='object'||(action==='pause'?(result as {paused?:boolean}).paused!==true:(result as {queued?:boolean}).queued!==true))throw new Error('暂时无法确认操作结果。');
      submitted.current=false;setComparison(null);setUnknown(false);
      setNotice(action==='pause'?'已停止后续同步，云端原事项保留。':'同步请求已接收，请查看云端确认状态。');
      setSnapshot(await fetchState());
    });
  }
  function back(){if(!busy&&current())props.onBack();}
  const pager=(page:number,total:number,set:(v:number)=>void)=><View style={styles.row}><Button disabled={busy||page===0} onPress={()=>set(page-1)}>上一页</Button><Text>{page+1} / {Math.max(1,Math.ceil(total/12))} 页 · {total} 项</Text><Button disabled={busy||(page+1)*12>=total} onPress={()=>set(page+1)}>下一页</Button></View>;
  const eventCard=(value:PublishedEvent,label?:string)=><View style={styles.fields}>{label&&<Text variant="titleMedium">{label}</Text>}<Text variant="titleSmall">{value.title}</Text><Text>{publishedEventRange(value)}</Text>{!!value.location&&<Text>{value.location}</Text>}{!!value.note&&<Text>{value.note}</Text>}<Divider/></View>;
  if(!visible||!snapshot)return <View style={styles.fields}><PageHeader title="旅行日历同步"/>{busy&&<ActivityIndicator/>}<Text accessibilityRole="alert">{error||'正在核对本人日历和旅行…'}</Text><Button disabled={busy||!household.online} onPress={()=>{if(active.current)void reload();else enter();}}>重新读取同步状态</Button><Button disabled={busy} onPress={props.onBack}>返回旅行</Button></View>;
  const sources=snapshot.sources.filter(source=>(source.name+' '+source.accountName+' '+provider(source.provider)).toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  const sourceOffset=Math.min(sourcePage,Math.max(0,Math.ceil(sources.length/12)-1));
  const accounts=[...new Map(snapshot.sources.filter(source=>!source.writeAuthorized).map(source=>[source.accountId,source])).values()];
  const names=new Map(snapshot.events.map(event=>[event.id,event.title]));
  return <View style={styles.page}>
    <PageHeader title="旅行日历同步" description="选择自己的日历，核对内容后再同步。"/>
    <View style={styles.row}><Button icon="arrow-left" disabled={busy} onPress={back}>返回旅行</Button><Button loading={busy} disabled={busy} onPress={()=>void reload()}>{unknown?'核对当前状态':'刷新同步状态'}</Button></View>
    {!!error&&<Text accessibilityRole="alert">{error}</Text>}{!!notice&&<Text accessibilityLiveRegion="polite">{notice}</Text>}
    {unknown&&<SectionCard title="先核对刚才的操作"><Text>请求可能已经完成。下方是当前读取的进度；本页暂停再次提交，你可以刷新核对，或返回旅行后重新查看。不要把等待状态当作失败而创建另一份日程。</Text></SectionCard>}
    {comparison?<SectionCard title={comparison.review?'核对旅行时间变化':'核对云端修改'}>
      <View style={styles.fields}>{eventCard(comparison.value.local,'本地旅行安排')}{comparison.value.remote?eventCard(comparison.value.remote,'云端当前内容'):<Text>尚未找到原云端事项。确认后将先核对原同步标识，再创建。</Text>}{comparison.value.previous&&eventCard(comparison.value.previous,'此前等待同步的内容')}
        <Text>{comparison.value.note}</Text><Button mode="contained" disabled={locked} onPress={()=>void command(comparison.id,comparison.review?'review-confirm':'conflict-confirm',comparison.value.previewToken)}>{comparison.review?'确认变化并恢复同步':'确认用本地内容更新'}</Button>
        <Button disabled={locked} onPress={()=>void command(comparison.id,'pause')}>保留云端并停止同步</Button><Button disabled={busy} onPress={()=>setComparison(null)}>取消核对</Button></View>
    </SectionCard>:preview?<SectionCard title="确认同步内容"><View style={styles.fields}>
      <Text variant="titleMedium">{provider(preview.source.provider)} · {preview.source.accountName} · {preview.source.name}</Text>
      {!preview.source.writeAuthorized&&<Text>还未取得日历写入权限。可以先加入队列，授权完成后才会写入云端。</Text>}
      {preview.events.slice(eventPage*12,(eventPage+1)*12).map(event=><View key={event.id}>{eventCard(event)}</View>)}{preview.events.length>12&&pager(eventPage,preview.events.length,setEventPage)}
      <Text>{preview.note}</Text><Button mode="contained" disabled={locked} onPress={()=>void confirm()}>确认加入同步</Button><Button disabled={busy} onPress={()=>setPreview(null)}>返回选择日历</Button>
    </View></SectionCard>:<SectionCard title="同步到哪本日历"><View style={styles.fields}>
      {snapshot.sources.length?<><Searchbar placeholder="搜索日历或账户" value={query} onChangeText={value=>{setQuery(value);setSourcePage(0);}}/>
        <View accessibilityRole="radiogroup" accessibilityLabel="本人目标日历">{sources.slice(sourceOffset*12,(sourceOffset+1)*12).map(source=><SelectionRow key={source.id} kind="radio" label={source.name+' · '+source.accountName} accessibilityLabel={'选择日历：'+source.name+' · '+source.accountName} checked={selected===source.id} disabled={locked} onPress={()=>setSelected(source.id)}/>)}</View>
        {!sources.length&&<Text>没有符合搜索的日历。</Text>}{sources.length>12&&pager(sourceOffset,sources.length,setSourcePage)}
        {selected&&<Text>已选：{snapshot.sources.find(s=>s.id===selected)?.name} · {snapshot.events.length} 项旅行日程</Text>}
        <Button mode="contained" disabled={locked||!selected} onPress={()=>void makePreview()}>预览日程</Button></>:<Text>尚未选择自己的日历。连接账户并选择日历后，再返回此处。</Text>}
      <Button disabled={locked} onPress={props.onConnections}>管理日历连接</Button>
    </View></SectionCard>}
    {accounts.length>0&&!preview&&!comparison&&<SectionCard title="日历写入权限"><View style={styles.fields}><Text>读取与写入需要不同授权。完成平台授权后，返回这趟旅行刷新状态；不会添加参与者或发送邀请。</Text>
      {accounts.map(source=><Button key={source.accountId} accessibilityLabel={'开启日历写入：'+source.accountName} disabled={locked} onPress={()=>void authorize(source)}>{provider(source.provider)} · {source.accountName}：开启日历写入</Button>)}</View></SectionCard>}
    <SectionCard title="同步进度"><View style={styles.fields}>
      {!snapshot.publications.length&&<Text>尚未确认同步到云日历。</Text>}
      {snapshot.publications.slice(publicationPage*12,(publicationPage+1)*12).map(row=>{const name=names.get(row.entityId)||'已移除的本地日程';return <View key={row.id} style={styles.fields}>
        <Text variant="titleMedium">{name}</Text><Text>{provider(row.provider)} · {snapshot.sources.find(s=>s.id===row.sourceId)?.name||'原日历连接'} · {publicationStatus(row)}</Text>
        {!!row.error&&<Text>{row.error}</Text>}<View style={styles.row}>{publicationActions(row).map(action=>{
          const label={review:'核对时间变化',conflict:'核对云端修改',retry:'重试同步',resume:'恢复同步',pause:'停止同步'}[action];
          return <Button key={action} accessibilityLabel={label+'：'+name} disabled={locked||!!preview||!!comparison} onPress={()=>void (action==='review'||action==='conflict'?compare(row,action==='review'):command(row.id,action))}>{label}</Button>;
        })}</View><Divider/></View>;})}
      {snapshot.publications.length>12&&pager(publicationPage,snapshot.publications.length,setPublicationPage)}
      <Text variant="bodySmall">{snapshot.note}</Text>
    </View></SectionCard>
  </View>;
}
const styles=StyleSheet.create({page:{gap:16},fields:{gap:12},row:{flexDirection:'row',flexWrap:'wrap',gap:8,alignItems:'center'}});
