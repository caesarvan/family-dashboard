import React, {useCallback, useEffect, useRef, useState} from 'react';
import {useFocusEffect} from 'expo-router';
import {StyleSheet, View} from 'react-native';
import {SelectionRow} from '../ui/SelectionRow';
import {ActivityIndicator, Button, Checkbox, Chip, Dialog, Divider, HelperText, IconButton, List, Portal, Searchbar, Text, TextInput, useTheme} from 'react-native-paper';
import {ApiError, request} from '../lib/api';
import {useHousehold} from '../lib/household';
import {dayKey} from '../lib/calendar';
import type {ListItem, ScreenProps, Trip} from '../lib/types';
import {copy, editDraft, eventDates, initialPlanningDraft, memberKey, newDraft, newKey, previewPayload, purchaseBudgetText, readForMember, recordVersions, SessionChangedError, summaryCounts, upgradeDraft, validateReceipt, type Draft, type Journey, type Plan, type Preview} from '../lib/trips';
import {EmptyState, PageHeader, SectionCard} from '../ui/components';
import {money} from './ListScreen';
import type {MapView} from '../lib/places';
import {isPlaceId, safeMapView} from '../lib/places';
import JourneyCalendarPanel from './JourneyCalendarPanel';
import JourneyPlacesPanel from './JourneyPlacesPanel';
import JourneyReschedulePanel from './JourneyReschedulePanel';
import MapScreen from './MapScreen';
import TripPhotosScreen from './TripPhotosScreen';

type Props=ScreenProps & {tripRequest?:{key:number;id?:string}; onReturnMap?:()=>void; initialDraft?:Draft; onExitPlanning?:()=>void};
type Pending={previewToken:string;idempotencyKey:string};
type TravelPanel={kind:'calendar'|'places'|'reschedule';journeyId:string;tripId:string}|{kind:'map';view:MapView;tripId:string}|{kind:'photos';journeyId:string;view:MapView;tripId:string};
export default function TripsScreen(props:Props) {
  const {mutate,refresh,online,identityKey}=useHousehold(), theme=useTheme();
  const [panel,setPanel]=useState<TravelPanel|null>(null),[mapReturn,setMapReturn]=useState<MapView|undefined>();
  const panelOpen=useRef(false);panelOpen.current=!!panel;
  const focused=useRef(false),session=useRef(identityKey);session.current=identityKey;
  useFocusEffect(useCallback(()=>{focused.current=true;return()=>{focused.current=false;setPanel(null);setMapReturn(undefined);};},[identityKey]));
  const actor=memberKey(props.user), identity=useRef(actor); identity.current=actor;
  const initial=useRef<{actor:string;present:boolean;invalidated:boolean;draft:Draft|null;error:string}|null>(null);
  if(initial.current===null){
    let seeded:Draft|null=null,seedError='';
    if(props.initialDraft!==undefined&&props.user.role==='member')try{seeded=initialPlanningDraft(props.initialDraft,props.state.people);}catch(failure){seedError=failure instanceof Error?failure.message:'旅行草案无法读取';}
    initial.current={actor,present:props.initialDraft!==undefined,invalidated:false,draft:seeded,error:seedError};
  }
  const alive=useRef(true), readVersion=useRef(0), writing=useRef(false), requestKey=useRef<number|undefined>(undefined);
  const [journeys,setJourneys]=useState<Journey[]|null>(null),[detail,setDetail]=useState<Journey|null>(null),[legacy,setLegacy]=useState<Trip|null>(null);
  const [draft,setDraft]=useState<Draft|null>(initial.current.draft),[preview,setPreview]=useState<Preview|null>(null),[pending,setPending]=useState<Pending|null>(null);
  const [uncertain,setUncertain]=useState(false),[blocked,setBlocked]=useState(false),[busy,setBusy]=useState(''),[reading,setReading]=useState(false);
  const [error,setError]=useState(initial.current.error),[notice,setNotice]=useState(''),[query,setQuery]=useState(''),[discard,setDiscard]=useState(false);
  const editing=useRef(false); editing.current=!!draft;
  const selected=useRef(''); selected.current=detail?.id||'';
  const current=(key:string)=>alive.current&&identity.current===key;
  const message=(failure:unknown)=>failure instanceof Error?failure.message:'暂时无法读取旅行';
  const locked=!!busy||uncertain||!online;

  // A read must belong to the same member session before AND after its response.
  // The parent additionally remounts this screen on its full (including CSRF) identity key.
  async function read<T>(path:string,key=actor):Promise<T> {
    try{return await readForMember<T>(path,key,request,()=>current(key));}
    catch(failure){if(failure instanceof SessionChangedError)throw new ApiError(failure.message,401);throw failure;}
  }
  async function load(id?:string) {
    const key=actor, ticket=++readVersion.current; setReading(true); setError('');
    try {
      const values=await read<{journeys:Journey[]}>('/journeys',key);
      const next=id?await read<Journey>('/journeys/'+encodeURIComponent(id),key):null;
      if(!current(key)||ticket!==readVersion.current)return;
      setJourneys(values.journeys); if(id)setDetail(next);
    }catch(failure){
      if(!current(key)||ticket!==readVersion.current)return;
      setJourneys(null);setDetail(null);setLegacy(null);setError(message(failure));
      if(failure instanceof ApiError&&[401,403].includes(failure.status)){setDraft(null);setPreview(null);setPending(null);void refresh();}
    }finally{if(current(key)&&ticket===readVersion.current)setReading(false);}
  }
  useEffect(()=>{
    const seed=initial.current!;
    if(seed.actor!==actor){seed.invalidated=true;seed.draft=null;seed.error='';}
    const useSeed=!seed.invalidated&&seed.actor===actor;
    alive.current=true;setPanel(null);setMapReturn(undefined);setJourneys(null);setDetail(null);setLegacy(null);setDraft(useSeed?seed.draft:null);setPreview(null);setPending(null);setUncertain(false);setBlocked(false);setBusy('');setError(useSeed?seed.error:'');setNotice('');setQuery('');
    if(props.user.role==='member'&&!(useSeed&&seed.present))void load();
    return()=>{alive.current=false;++readVersion.current;};
  },[actor]);
  useEffect(()=>{if(props.user.role==='member'&&!initial.current?.error&&!editing.current&&!writing.current&&!panelOpen.current)void load(selected.current||undefined);},[props.state.revision]);
  useEffect(()=>{
    const incoming=props.tripRequest;
    if(!incoming||incoming.key===requestKey.current)return;
    requestKey.current=incoming.key;
    if(initial.current?.present)return;
    if(editing.current||writing.current){setNotice('请先完成或取消当前旅行编辑，再打开另一趟旅行。');return;}
    if(!incoming.id)startNew();
    else void openTrip(incoming.id);
  },[props.tripRequest?.key]);

  function clearEditor(){setDraft(null);setPreview(null);setPending(null);setUncertain(false);setBlocked(false);setError('');}
  function startNew(){if(writing.current||props.user.role!=='member')return;++readVersion.current;setPanel(null);setMapReturn(undefined);setReading(false);setDetail(null);setLegacy(null);clearEditor();setDraft(newDraft(props.state.people,dayKey()));setNotice('');}
  async function openTrip(tripId:string,edit=false){
    if(writing.current||editing.current)return;
    const key=actor,ticket=++readVersion.current;setReading(true);setError('');setDetail(null);setLegacy(null);setNotice('');
    try{
      const values=await read<{journeys:Journey[]}>('/journeys',key), linked=values.journeys.find(row=>row.tripId===tripId);
      const row=linked?await read<Journey>('/journeys/'+encodeURIComponent(linked.id),key):null;
      // Read legacy trips from current server state too; props may predate a deletion/edit.
      const snapshot=row?null:await read<{trips:Trip[];tasks:ListItem[]}>('/state',key);
      if(!current(key)||ticket!==readVersion.current||editing.current)return;
      setJourneys(values.journeys);
      if(row){setDetail(row);if(edit)setDraft(editDraft(row));}
      else {const trip=snapshot!.trips.find(item=>item.id===tripId);if(!trip)throw new ApiError('这趟旅行已被删除，请刷新',404);setLegacy(trip);if(edit)setDraft(upgradeDraft(trip,props.state.people,snapshot!.tasks));}
    }catch(failure){if(current(key)&&ticket===readVersion.current){setError(message(failure));if(failure instanceof ApiError&&[401,403].includes(failure.status))void refresh();}}
    finally{if(current(key)&&ticket===readVersion.current)setReading(false);}
  }
  function change(update:(plan:Plan)=>void){if(locked||writing.current)return;setDraft(value=>{if(!value)return value;const next=copy(value);update(next.plan);return next;});setPreview(null);setPending(null);setBlocked(false);setError('');}
  function amount(field:'budget'|'saved'|'paid',value:string){if(locked)return;setDraft(old=>old?{...old,[field]:value}:null);setPreview(null);setPending(null);setBlocked(false);}
  function purchaseAmount(key:string,value:string){if(locked||writing.current)return;setDraft(old=>old?{...old,purchaseBudgets:{...old.purchaseBudgets,[key]:value}}:null);setPreview(null);setPending(null);setBlocked(false);setError('');}
  function usePreparation(items:Plan['checklist']){if(!items||locked||writing.current)return;change(plan=>{plan.checklist=copy(items);});setNotice('准备建议已展开，可以调整负责人和截止日期。修改后请重新预览。');}
  async function makePreview(expandPreparation=false){
    if(!draft||locked||writing.current)return;const key=actor;writing.current=true;setBusy('preview');setError('');
    try{
      const payload=previewPayload(draft,props.state.people);
      if(draft.journeyId&&draft.observed){const fresh=await read<Journey>('/journeys/'+encodeURIComponent(draft.journeyId),key);if(recordVersions(fresh)!==draft.observed)throw new ApiError('旅行或关联事项已更新',409);}
      if(!current(key))return;
      const value=await mutate<Preview>('/journeys/preview','POST',payload);
      if(!current(key))return;
      if(expandPreparation){setDraft(old=>old?{...old,plan:{...old.plan,checklist:copy(value.plan.checklist||[])}}:null);setPreview(null);setPending(null);setNotice('准备建议已展开，可以调整负责人和截止日期。修改后请重新预览。');}
      else {setPreview(value);setPending(value.previewToken?{previewToken:value.previewToken,idempotencyKey:newKey()}:null);}
      setBlocked(false);
    }catch(failure){if(current(key))setError(failure instanceof ApiError&&failure.status===409?'旅行已变化，输入仍保留。请先核对最新计划后重新编辑。':message(failure));}
    finally{writing.current=false;if(current(key))setBusy('');}
  }
  async function apply(){
    if(!pending||busy||blocked||!online||writing.current)return;const key=actor,payload=pending;writing.current=true;setBusy('apply');setError('');
    try{
      const result=await mutate<unknown>('/journeys/apply','POST',payload);
      if(!current(key))return;
      if(!validateReceipt(result)||(draft?.journeyId&&result.id!==draft.journeyId)||(draft?.tripId&&result.tripId!==draft.tripId))throw new ApiError('保存回执无法核实，请核对原保存',0);
      clearEditor();setNotice(result.replayed?'已核对原保存结果，没有重复创建。':'旅行已保存，准备清单和本地日程已更新。');setLegacy(null);
      await refresh();if(current(key))await load(result.id);
    }catch(failure){
      if(!current(key))return;
      const unknown=uncertain||failure instanceof ApiError&&(failure.status===0||failure.status>=500);
      const rejected=failure instanceof ApiError&&failure.status>0&&failure.status<500;
      setUncertain(unknown);setBlocked(rejected);
      setError(unknown?(rejected?'原保存结果仍未知，且原预览已无法重试。请关闭并核对旅行列表，勿直接重新创建。':'连接中断，保存结果暂时未知。请用下方按钮核对原保存；会沿用同一预览和操作编号，不会再创建一趟旅行。'):failure instanceof ApiError&&failure.status===409?'预览已过期或旅行内容已变化。请先核对最新记录；当前输入仍保留。':message(failure));
      if(failure instanceof ApiError&&[401,403].includes(failure.status)){clearEditor();setDetail(null);setJourneys(null);void refresh();}
    }finally{writing.current=false;if(current(key))setBusy('');}
  }
  async function toggle(kind:'tasks'|'shopping',item:ListItem){
    if(writing.current||!online||item.sync?.readOnly||!detail)return;
    const key=actor,id=detail.id;writing.current=true;setBusy(item.id);setError('');
    try{await mutate('/items/'+kind+'/'+encodeURIComponent(item.id),'PATCH',{revision:item.revision,done:!item.done});if(!current(key))return;await refresh();if(current(key)){setNotice(item.done?'已恢复':'已完成');await load(id);}}
    catch(failure){if(current(key)){await load(id);if(current(key))setError(message(failure)+'。已重新读取，请核对当前状态后再操作。');}}
    finally{writing.current=false;if(current(key))setBusy('');}
  }
  function cancel(){if(busy)return;if(uncertain){setError('保存结果尚未核实，请先核对原保存。关闭页面后请先检查旅行列表，勿直接重新创建。');return;}setDiscard(true);}
  const field=(label:string,value:string,onChangeText:(value:string)=>void,maxLength=100)=><TextInput key={label} mode="outlined" outlineStyle={{borderRadius:8}} dense label={label} accessibilityLabel={label} value={value} onChangeText={onChangeText} maxLength={maxLength} disabled={locked}/>;
  const ownerChoices=(label:string,value:string,onChange:(owner:string)=>void)=><View style={styles.fields}><Text variant="bodySmall">{label}</Text><View style={styles.wrap}>{[{id:'shared',name:'一起'},...props.state.people].map(person=><Chip key={person.id} selected={value===person.id} accessibilityLabel={label+'：'+person.name} disabled={locked} onPress={()=>onChange(person.id)}>{person.name}</Chip>)}</View></View>;
  const group=(items:ListItem[],kind:'tasks'|'shopping')=>items.map(item=><View style={styles.item} key={item.id}><Checkbox.Android status={item.done?'checked':'unchecked'} disabled={!!busy||!online||!!item.sync?.readOnly} accessibilityLabel={(item.done?'恢复':'完成')+item.title} onPress={()=>void toggle(kind,item)}/><View style={styles.body}><Text variant="titleSmall" style={item.done?{textDecorationLine:'line-through',color:theme.colors.onSurfaceVariant}:undefined}>{item.title}</Text><Text variant="bodySmall">{item.owner==='shared'?'一起':props.state.people.find(p=>p.id===item.owner)?.name||'家庭成员'}{item.due?' · '+item.due:''}{kind==='shopping'?' · '+(item.quantity||'1 件'):''}</Text>{!!item.note&&<Text variant="bodySmall">{item.note}</Text>}{kind==='shopping'&&<Text variant="bodySmall">预算 {money(item.budget)}{item.done?' · 实付 '+money(item.actual):''}</Text>}{item.sync?.readOnly&&<Text variant="bodySmall">来源只读</Text>}</View><IconButton icon="pencil-outline" accessibilityLabel={'编辑'+item.title} disabled={!!busy||!!item.sync} onPress={()=>props.onEdit(kind,item)}/></View>);
  if(props.user.role!=='member')return <Text>旅行编辑仅供已登录家庭成员使用。</Text>;
  // Route-local navigation stores identifiers and map filters only. Each child
  // performs a fresh session-fenced read; late callbacks cannot reopen a panel.
  const canNavigate=()=>current(actor)&&focused.current&&session.current===identityKey;
  const backToTrip=(tripId:string)=>{if(!canNavigate())return;setPanel(null);void openTrip(tripId);};
  const openPanel=(kind:'calendar'|'places'|'reschedule')=>{if(!canNavigate()||!detail||busy||reading||draft)return;++readVersion.current;setPanel({kind,journeyId:detail.id,tripId:detail.tripId});};
  if(panel?.kind==='reschedule')return <JourneyReschedulePanel journeyId={panel.journeyId} onBack={()=>backToTrip(panel.tripId)} onSaved={result=>{if(!canNavigate()||result.journeyId!==panel.journeyId)return;void refresh();backToTrip(panel.tripId);}}/>;
  if(panel?.kind==='calendar')return <JourneyCalendarPanel journeyId={panel.journeyId} onBack={()=>backToTrip(panel.tripId)} onConnections={()=>{if(canNavigate())props.onNavigate('connections');}}/>;
  if(panel?.kind==='places')return <JourneyPlacesPanel journeyId={panel.journeyId} onBack={()=>backToTrip(panel.tripId)} onOpenMap={view=>{if(canNavigate())setPanel({kind:'map',view:safeMapView(view),tripId:panel.tripId});}}/>;
  if(panel?.kind==='photos')return <TripPhotosScreen {...props} journeyId={panel.journeyId} onBack={()=>{if(canNavigate())setPanel({kind:'map',view:panel.view,tripId:panel.tripId});}}/>;
  if(panel?.kind==='map')return <View style={styles.page}><MapScreen {...props} initialView={panel.view} onBack={()=>backToTrip(panel.tripId)}
    onOpenTrip={(journey,view)=>{if(!canNavigate()||!isPlaceId(journey.id)||!isPlaceId(journey.tripId))return;setMapReturn(safeMapView(view));backToTrip(journey.tripId);}}
    onOpenPhotos={(journey,view)=>{if(canNavigate()&&isPlaceId(journey.id)&&isPlaceId(journey.tripId))setPanel({kind:'photos',journeyId:journey.id,tripId:panel.tripId,view:safeMapView(view)});}}/></View>;
  const active=detail?.trip||legacy;
  return <View style={styles.page}>
    {!!props.onExitPlanning&&!draft&&<Button accessibilityLabel="返回助理" icon="arrow-left" disabled={!!busy} onPress={props.onExitPlanning}>返回助理</Button>}
    {!!props.onReturnMap&&!draft&&<Button icon="arrow-left" disabled={!!busy} onPress={props.onReturnMap}>返回足迹地图</Button>}
    {!!mapReturn&&!draft&&<Button icon="arrow-left" disabled={!!busy||!active} onPress={()=>{if(canNavigate()&&active)setPanel({kind:'map',view:mapReturn,tripId:active.id});}}>返回地图位置</Button>}
    <PageHeader title={draft?(draft.journeyId?'编辑旅行':draft.tripId?'完善旅行计划':'计划旅行'):detail||legacy?'旅行详情':'旅行'} description={draft?'先安排日期与目的地，再按需补充细节。':undefined} action={!draft&&!detail&&!legacy?<Button mode="contained" icon="plus" disabled={!!busy||!online} onPress={startNew}>计划旅行</Button>:undefined}/>
    {!!notice&&<Text accessibilityLiveRegion="polite">{notice}</Text>}
    {!!error&&<HelperText type="error" accessibilityRole="alert">{error}</HelperText>}
    {reading&&<ActivityIndicator accessibilityLabel="正在读取旅行"/>}
    {draft?<>
      <SectionCard title="基本安排"><View style={styles.fields}>
        {field('旅行名称',draft.plan.title,value=>change(plan=>{plan.title=value;}))}
        <View style={styles.columns}><View style={styles.column}>{field('出发日期（YYYY-MM-DD）',draft.plan.start,value=>change(plan=>{const old=plan.start;plan.start=value;if(!draft.journeyId&&!draft.tripId)for(const dest of plan.destinations)if(dest.arrival===old)dest.arrival=value;}),10)}</View><View style={styles.column}>{field('返程日期（包含当天）',draft.plan.end,value=>change(plan=>{const old=plan.end;plan.end=value;if(!draft.journeyId&&!draft.tripId)for(const dest of plan.destinations)if(dest.departure===old)dest.departure=value;}),10)}</View></View>
        <Text variant="bodySmall">{draft.plan.schemaVersion===2?'参考时区：'+draft.plan.referenceTimezone+'。改变总日期不会自动移动分段与准备截止。':'日期包含出发和返程当天，生成北京时间的全天日程。已有分段和截止日期不会随总日期自动移动。'}</Text>
        <View style={styles.wrap}>{props.state.people.map(person=><Chip key={person.id} selected={draft.plan.memberIds.includes(person.id)} disabled={locked} onPress={()=>change(plan=>{plan.memberIds=plan.memberIds.includes(person.id)?plan.memberIds.filter(id=>id!==person.id):[...plan.memberIds,person.id];})}>{person.name}</Chip>)}</View>
        <SelectionRow label="境外旅行" checked={draft.plan.international} disabled={locked} onPress={()=>change(plan=>{plan.international=!plan.international;})}/>
        {draft.plan.destinations.map((dest,index)=><View style={styles.fields} key={dest.key}><Text variant="titleSmall">目的地 {index+1}</Text>{field('城市 '+(index+1),dest.city,value=>change(plan=>{plan.destinations[index].city=value;}),80)}{field('国家或地区 '+(index+1),dest.country,value=>change(plan=>{plan.destinations[index].country=value;}),60)}<View style={styles.columns}><View style={styles.column}>{field('抵达日期 '+(index+1),dest.arrival,value=>change(plan=>{plan.destinations[index].arrival=value;}),10)}</View><View style={styles.column}>{field('离开日期 '+(index+1),dest.departure,value=>change(plan=>{plan.destinations[index].departure=value;}),10)}</View></View>{dest.timeZone&&<Text variant="bodySmall">当地时区：{dest.timeZone}（高级编辑见经典旅行）</Text>}{draft.plan.destinations.length>1&&<Button disabled={locked} onPress={()=>change(plan=>{plan.destinations.splice(index,1);})}>移除目的地 {index+1}</Button>}</View>)}
        {draft.plan.schemaVersion!==2&&<Button icon="plus" disabled={locked||draft.plan.destinations.length>=20} onPress={()=>change(plan=>{plan.destinations.push({key:newKey(),city:'',country:'',arrival:plan.start,departure:plan.end});})}>增加目的地</Button>}
      </View></SectionCard>
      <List.Accordion title="预算" description={'总预算 '+draft.budget+' 元 · 可按需填写'}><View style={styles.fields}>{(['budget','paid','saved'] as const).map((name,index)=>field(['总预算（元）','已付金额（元）','已留备用金（元）'][index],draft[name],value=>amount(name,value),14))}<Text variant="bodySmall">人民币口径。准备金和已付金额单独记录，采购不会自动重复计为支出。</Text></View></List.Accordion>
      <List.Accordion title="准备清单与采购" description={draft.plan.checklist?`${draft.plan.checklist.length} 项准备 · ${draft.plan.shopping.length} 件采购`:'保存时生成常用准备清单'}>
        <View style={styles.fields}>{!draft.plan.checklist?<><Text>准备建议由服务器根据当前计划生成，可先展开，再分配负责人。</Text><Button accessibilityLabel="展开并调整建议" disabled={locked} loading={busy==='preview'} onPress={()=>void makePreview(true)}>展开并调整建议</Button><Button disabled={locked} onPress={()=>change(plan=>{plan.checklist=[];})}>改为自己填写</Button></>:<>{draft.plan.checklist.map((row,index)=><View style={styles.fields} key={row.key}>{field('准备事项 '+(index+1),row.title,value=>change(plan=>{plan.checklist![index].title=value;}))}{ownerChoices('准备负责人 '+(index+1),row.owner,value=>change(plan=>{plan.checklist![index].owner=value;}))}{field('准备截止 '+(index+1),row.due||'',value=>change(plan=>{plan.checklist![index].due=value;}),10)}<Button disabled={locked} onPress={()=>change(plan=>{plan.checklist!.splice(index,1);})}>移出准备事项 {index+1}</Button></View>)}<Button disabled={locked||draft.plan.checklist.length>=100} icon="plus" onPress={()=>change(plan=>{plan.checklist!.push({key:newKey(),title:'',owner:'shared',due:plan.start,note:'',category:'preparation'});})}>增加准备事项</Button></>}
          {draft.plan.shopping.map((row,index)=><View style={styles.fields} key={row.key}>{field('采购名称 '+(index+1),row.title,value=>change(plan=>{plan.shopping[index].title=value;}))}{field('采购数量 '+(index+1),row.quantity,value=>change(plan=>{plan.shopping[index].quantity=value;}),30)}{ownerChoices('采购负责人 '+(index+1),row.owner,value=>change(plan=>{plan.shopping[index].owner=value;}))}{field('采购预算（元，可不填） '+(index+1),purchaseBudgetText(draft,row),value=>purchaseAmount(row.key,value),14)}<Text variant="bodySmall">留空表示尚未估算，0 表示预计无需花费。保存后可添加参考图片。</Text><Button disabled={locked} onPress={()=>change(plan=>{plan.shopping.splice(index,1);})}>移出采购 {index+1}</Button></View>)}<Button icon="plus" disabled={locked||draft.plan.shopping.length>=100} onPress={()=>change(plan=>{plan.shopping.push({key:newKey(),title:'',quantity:'1 件',owner:'shared',budget:null,note:''});})}>增加采购</Button><Text variant="bodySmall">移出计划的已有记录保留为独立事项，完成状态与图片不会删除。</Text>
        </View>
      </List.Accordion>
      <List.Accordion title="分段行程与备注"><View style={styles.fields}>
        {draft.plan.schemaVersion===2?<Text>已有航班、住宿、活动和时区将完整保留。本页可编辑基本安排；复杂分段请在保存或取消后打开经典旅行编辑。</Text>:draft.plan.segments===undefined?<Text>将按每个目的地生成全天停留安排。</Text>:<>{draft.plan.segments.map((row,index)=><View style={styles.fields} key={row.key}>{field('行程标题 '+(index+1),row.title,value=>change(plan=>{plan.segments![index].title=value;}))}{field('行程开始 '+(index+1),String(row.start||''),value=>change(plan=>{plan.segments![index].start=value;}),10)}{field('行程结束 '+(index+1),String(row.end||''),value=>change(plan=>{plan.segments![index].end=value;}),10)}{field('行程地点 '+(index+1),row.location||'',value=>change(plan=>{plan.segments![index].location=value;}),200)}<Button disabled={locked} onPress={()=>change(plan=>{plan.segments!.splice(index,1);})}>移出分段 {index+1}</Button></View>)}<Button icon="plus" disabled={locked||draft.plan.segments.length>=100} onPress={()=>change(plan=>{plan.segments!.push({key:newKey(),title:'',start:plan.start,end:plan.end,location:'',note:''});})}>增加分段</Button></>}
        {field('旅行备注',draft.plan.note,value=>change(plan=>{plan.note=value;}),2000)}
      </View></List.Accordion>
      {preview&&<SectionCard title="确认变更"><View style={styles.fields}>
        <Text>新增：{summaryCounts(preview.summary.create)}</Text><Text>更新：{summaryCounts(preview.summary.update)}</Text>{!!preview.summary.detach&&<Text>移出计划 {preview.summary.detach} 项，记录仍保留。</Text>}
        <Text>准备 {preview.plan.checklist?.length||0} 项 · 采购 {preview.plan.shopping.length} 件 · 分段 {preview.plan.segments?.length||0} 项</Text>
        {preview.plan.checklist?.map(item=><Text variant="bodySmall" key={item.key}>{item.title} · {item.owner==='shared'?'一起':props.state.people.find(person=>person.id===item.owner)?.name||'家庭成员'} · {item.due}</Text>)}
        {!draft.plan.checklist&&<Button accessibilityLabel="调整准备建议与负责人" disabled={locked} onPress={()=>usePreparation(preview.plan.checklist)}>调整准备建议与负责人</Button>}
        {preview.plan.shopping.map(item=><Text variant="bodySmall" key={item.key}>{item.title} · {item.owner==='shared'?'一起':props.state.people.find(person=>person.id===item.owner)?.name||'家庭成员'} · 预算 {money(item.budget)}</Text>)}
        {preview.summary.warnings.map((warning,index)=><Text key={index}>{warning.message||'请核对本次日期或分段变化。'}</Text>)}{!!preview.summary.preserved.length&&<Text>已保留 {preview.summary.preserved.length} 处独立修改。</Text>}{!!preview.summary.cloudReviews.length&&<Text>已有云端时间需要另行复核；本次不会直接更改云日历。</Text>}
        <Text variant="bodySmall">{preview.summary.policyNotice}</Text>{!preview.canApply&&<Text accessibilityRole="alert">安排存在 {preview.summary.conflicts.length} 处独立修改冲突。请先取消编辑，在经典旅行核对并选择保留哪一项，本页不会覆盖冲突。</Text>}
        <Button accessibilityLabel={uncertain?'核对原保存':'确认保存旅行'} mode="contained" disabled={!pending||!!busy||blocked||!online} loading={busy==='apply'} onPress={()=>void apply()}>{uncertain?'核对原保存':'确认保存旅行'}</Button>
      </View></SectionCard>}
      <View style={styles.wrap}><Button disabled={!!busy||uncertain} onPress={cancel}>取消编辑</Button><Button mode={preview?'outlined':'contained'} disabled={locked} loading={busy==='preview'} onPress={()=>void makePreview()}>预览变更</Button></View>
      {blocked&&<Text>输入仍保留。需要重新读取时，先记下变更，再取消编辑并打开最新旅行；不要沿用旧版本覆盖。</Text>}
      {uncertain&&blocked&&<Button onPress={()=>setDiscard(true)}>关闭并核对列表</Button>}
    </>:detail||legacy?<>
      <View style={styles.wrap}><Button icon="arrow-left" disabled={!!busy} onPress={()=>{++readVersion.current;setDetail(null);setLegacy(null);void load();}}>全部旅行</Button><Button mode="contained" icon="pencil-outline" disabled={!!busy||reading||!online} onPress={()=>{if(active)void openTrip(active.id,true);}}>编辑旅行</Button><Button disabled={!!busy||reading} onPress={()=>{if(active)void openTrip(active.id);}}>刷新</Button></View>
      <SectionCard title={active?.title||detail?.plan.title||'旅行'}><View style={styles.fields}><Text variant="titleMedium">{active?.destination||detail?.plan.destinations.map(row=>row.city).join(' → ')}</Text><Text>{active?.start||detail?.plan.start} — {active?.end||detail?.plan.end}（包含返程日）</Text>{!!active?.note&&<Text>{active.note}</Text>}<Text>预算 {money(detail?.budget.total??active?.budget)} · 已付 {money(detail?.budget.paid??active?.paid)}</Text><Text>已留备用金 {money(detail?.budget.reserved??active?.saved)}</Text></View></SectionCard>
      {detail?<>
        <View style={styles.wrap}><Button mode="outlined" icon="calendar-edit" disabled={!!busy||reading||!online} onPress={()=>openPanel('reschedule')}>调整日期</Button><Button mode="outlined" icon="map-marker-outline" disabled={!!busy||reading||!online} onPress={()=>openPanel('places')}>旅行地点</Button><Button mode="outlined" icon="calendar-sync-outline" disabled={!!busy||reading||!online} onPress={()=>openPanel('calendar')}>同步到日历</Button></View>
        <SectionCard title={`准备 · ${detail.progress.done}/${detail.progress.total}`} action={<Button disabled={!!busy||!online} onPress={()=>setDraft(editDraft(detail))}>管理清单</Button>}>{detail.tasks.length?group(detail.tasks,'tasks'):<Text>没有准备事项。可以在编辑旅行中添加。</Text>}</SectionCard>
        <SectionCard title={`采购 · ${detail.progress.purchased}/${detail.progress.purchaseCount}`}>{detail.shopping.length?group(detail.shopping,'shopping'):<Text>这趟旅行尚未安排采购。</Text>}<Text variant="bodySmall">计划采购 {money(detail.budget.purchaseBudget)}{detail.budget.unknownPurchaseBudgets?`，另有 ${detail.budget.unknownPurchaseBudgets} 件未填预算`:''} · 已买实付 {money(detail.budget.purchaseActual)}{detail.budget.unknownPurchaseActuals?`，另有 ${detail.budget.unknownPurchaseActuals} 件未填实付`:''}</Text><Text variant="bodySmall">{detail.budget.note}</Text></SectionCard>
        <SectionCard title="本地行程">{detail.events.map(event=><View style={styles.event} key={event.id}><Text variant="titleMedium">{event.title}</Text><Text>{eventDates(event)}</Text>{!!event.location&&<Text>{event.location}</Text>}{!!event.note&&<Text variant="bodySmall">{event.note}</Text>}<Divider/></View>)}<Text variant="bodySmall">这里显示看板本地安排。点击「同步到日历」选择云日历，并查看发布进度。</Text></SectionCard>
      </>:<SectionCard title="完善行程"><Text>这是一条基础旅行记录。编辑后可预览生成本地行程与准备清单，原旅行和已有本地准备记录会保留。</Text></SectionCard>}
      <Button icon="open-in-app" onPress={()=>props.onLegacy('trips')}>高级分段与资料（经典旅行）</Button>{!props.onReturnMap&&!mapReturn&&<Button icon="map-outline" onPress={()=>props.onNavigate('map')}>足迹地图</Button>}
    </>:<>
      <Searchbar placeholder="搜索旅行或目的地" value={query} onChangeText={setQuery}/>
      {journeys===null?<EmptyState title={reading?'正在读取旅行':'旅行暂时无法读取'} action={!reading?<Button onPress={()=>void load()}>重试</Button>:undefined}/>:props.state.trips.filter(trip=>[trip.title,trip.destination||''].join(' ').toLocaleLowerCase().includes(query.toLocaleLowerCase())).sort((a,b)=>a.start.localeCompare(b.start)).map(trip=><SectionCard key={trip.id} title={trip.title} action={<Button disabled={reading} onPress={()=>void openTrip(trip.id)}>查看</Button>}><Text>{trip.destination}</Text><Text>{trip.start} — {trip.end}</Text><Text variant="bodySmall">预算 {money(trip.budget)} · 已付 {money(trip.paid)}</Text></SectionCard>)}
      {journeys!==null&&!props.state.trips.length&&<EmptyState title="下一站，想去哪里？" description="先定日期和目的地，其余慢慢安排。" action={<Button mode="contained" disabled={!online} onPress={startNew}>计划第一趟旅行</Button>}/>}
    </>}
    <Portal><Dialog visible={discard} style={{borderRadius:12,maxWidth:520,width:'92%',alignSelf:'center'}} onDismiss={()=>setDiscard(false)}><Dialog.Title>{uncertain?'关闭并核对保存结果？':'放弃这次编辑？'}</Dialog.Title><Dialog.Content><Text>{uncertain?'原保存可能已经成功。关闭后先检查旅行列表，确认前不要重新创建；当前操作凭证不会跨页面保存。':'未保存的修改会丢弃，原旅行保持不变。'}</Text></Dialog.Content><Dialog.Actions><Button onPress={()=>setDiscard(false)}>继续编辑</Button><Button onPress={()=>{setDiscard(false);const wasUnknown=uncertain;clearEditor();if(wasUnknown){setDetail(null);setLegacy(null);void refresh();void load();}else void load(detail?.id);}}>{uncertain?'关闭并核对':'放弃修改'}</Button></Dialog.Actions></Dialog></Portal>
  </View>;
}
export {TripsScreen};
const styles=StyleSheet.create({page:{gap:16},fields:{gap:12},columns:{flexDirection:'row',gap:12,flexWrap:'wrap'},column:{minWidth:180,flexGrow:1,flexBasis:220},wrap:{flexDirection:'row',gap:8,flexWrap:'wrap',alignItems:'center'},item:{flexDirection:'row',alignItems:'flex-start',gap:6,paddingVertical:10},body:{flex:1,minWidth:0,gap:4},event:{gap:6,marginBottom:16}});
