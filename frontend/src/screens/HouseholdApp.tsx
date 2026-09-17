import { openLocal } from '../lib/navigation';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { View } from 'react-native';
import { ActivityIndicator, Button, Snackbar, Text } from 'react-native-paper';
import { useLocalSearchParams, useNavigation, useNavigationContainerRef, useRouter } from 'expo-router';
import { useHousehold } from '../lib/household';
import { Entity, ItemKind, RouteName, ScreenProps } from '../lib/types';
import AppShell from '../ui/AppShell';
import ItemEditor from '../ui/ItemEditor';
import HomeScreen from './HomeScreen';
import CalendarScreen from './CalendarScreen';
import ListScreen from './ListScreen';
import LoginScreen from './LoginScreen';
import { MoreScreen } from './OtherScreens';
import FinanceScreen from './FinanceScreen';
import InvestmentsScreen from './InvestmentsScreen';
import { TripsScreen } from './TripsScreen';
import PhotosScreen from './PhotosScreen';
import { AssistantScreen } from './AssistantScreen';
import InventoryScreen from './InventoryScreen';
import MapWorkspace from './MapWorkspace';
import AccountsScreen from './AccountsScreen';
import DevicesScreen from './DevicesScreen';
import { readSyncAuthResult, syncAuthMessage, type SyncAuthResult } from '../lib/authNavigation';

const titles:Record<RouteName,string>={home:'首页',calendar:'日程',tasks:'待办',shopping:'采购',trips:'旅行',finance:'家庭资金',investments:'我的持仓',photos:'家庭相册',assistant:'家庭助理',inventory:'家庭物品',map:'足迹地图',connections:'账户与自动同步',devices:'电视与播放',more:'更多'};
const legacyRoutes=new Set(['home','calendar','tasks','shopping','trips','map','photos','finance','assistant','connections','household','settings','inventory']);
export default function HouseholdApp({screen='home'}:{screen?:string}) {
  const route=Object.hasOwn(titles,screen)?screen as RouteName:'home', router=useRouter();
  const navigation=useNavigationContainerRef();
  const pageNavigation=useNavigation();
  const params=useLocalSearchParams<{ request?: string; item?: string; auth?: string; reason?: string }>();
  const [authResult,setAuthResult]=useState<SyncAuthResult|undefined>(()=>route==='connections'?readSyncAuthResult(params.auth,params.reason):undefined);
  useEffect(()=>{
    if(route!=='connections'){setAuthResult(undefined);return;}
    const result=readSyncAuthResult(params.auth,params.reason);
    if(!result)return;
    setAuthResult(result);
    // Initial route effects run before the root navigation container is ready.
    // Subscribe before checking so the one-time ready event cannot be missed.
    let consumed=false;
    const consume=()=>{if(!consumed&&navigation.isReady()){consumed=true;router.setParams({auth:undefined,reason:undefined});}};
    const unsubscribe=navigation.addListener('ready',consume);
    consume();
    return ()=>{consumed=true;unsubscribe();};
  },[route,params.auth,params.reason,router,navigation]);
  const household=useHousehold(); const {user,state,loading,online,error,refresh,preferences,notice,setNotice}=household;
  const [editor,setEditor]=useState<{kind:ItemKind;item?:Entity;key:number}|null>(null);
  const [pendingId,setPendingId]=useState('');
  const requestKey=typeof params.request==='string'?Number(params.request):0;
  const tripRequest=route==='trips'&&Number.isSafeInteger(requestKey)&&requestKey>0
    ?{key:requestKey,id:typeof params.item==='string'?params.item:undefined}:undefined;
  const inventoryRequest=route==='inventory'&&Number.isSafeInteger(requestKey)&&requestKey>0
    ?{key:requestKey,id:typeof params.item==='string'&&/^[a-f0-9]{24}$/.test(params.item)?params.item:undefined}:undefined;
  const actor=household.identityKey;
  const pendingNavigation=useRef({actor,locked:false,message:'',source:''});
  const activeActor=useRef(actor);activeActor.current=actor;
  const activeRoute=useRef(route);activeRoute.current=route;
  const onReschedulePending=(locked:boolean)=>{
    if(activeActor.current!==actor||!locked&&pendingNavigation.current.source!=='reschedule')return;
    pendingNavigation.current={actor,locked,message:locked?'请先核对这次改期的保存结果，再离开旅行页面。':'',source:'reschedule'};
  };
  const onDevicePending=useCallback((message:string|null)=>{
    if(activeActor.current!==actor||route!=='devices'||activeRoute.current!==route||!message&&pendingNavigation.current.source!=='devices')return;
    pendingNavigation.current={actor,locked:!!message,message:message||'',source:'devices'};
  },[actor,route]);
  const onHomeLayoutPending=useCallback((message:string|null)=>{
    if(activeActor.current!==actor||route!=='home'||activeRoute.current!==route||!message&&pendingNavigation.current.source!=='home-layout')return;
    pendingNavigation.current={actor,locked:!!message,message:message||'',source:'home-layout'};
  },[actor,route]);
  const onAppearancePending=useCallback((message:string|null)=>{
    if(activeActor.current!==actor||route!=='more'||activeRoute.current!==route||!message&&pendingNavigation.current.source!=='appearance')return;
    pendingNavigation.current={actor,locked:!!message,message:message||'',source:'appearance'};
  },[actor,route]);
  const onDocumentsPending=useCallback((locked:boolean)=>{
    if(activeActor.current!==actor||activeRoute.current!==route||!['trips','map','assistant','more'].includes(route)
      ||!locked&&pendingNavigation.current.source!=='documents')return;
    pendingNavigation.current={actor,locked,message:locked?'请先保存或放弃旅行资料的修改；结果不明时，先核对再离开。':'',source:'documents'};
  },[actor,route]);
  const onRoutinesPending=useCallback((locked:boolean)=>{
    if(activeActor.current!==actor||route!=='more'||activeRoute.current!==route
      ||!locked&&pendingNavigation.current.source!=='routines')return;
    pendingNavigation.current={actor,locked,message:locked?'请先保存或放弃例行计划的修改；结果不明时，先核对再离开。':'',source:'routines'};
  },[actor,route]);
  const onSegmentsPending=useCallback((locked:boolean)=>{
    if(activeActor.current!==actor||activeRoute.current!==route||!['trips','map','assistant'].includes(route)
      ||!locked&&pendingNavigation.current.source!=='segments')return;
    pendingNavigation.current={actor,locked,message:locked?'请先保存或放弃行程分段的修改；结果不明时，先核对再离开。':'',source:'segments'};
  },[actor,route]);
  const onFinanceSourcePending=useCallback((locked:boolean)=>{
    if(activeActor.current!==actor||route!=='finance'||activeRoute.current!==route
      ||!locked&&pendingNavigation.current.source!=='finance-source')return;
    pendingNavigation.current={actor,locked,message:locked?'请先确认或放弃资产来源预览；保存结果不明时，先核对或保留操作编号再返回。':'',source:'finance-source'};
  },[actor,route]);
  const onMembersPending=useCallback((locked:boolean)=>{
    if(activeActor.current!==actor||route!=='more'||activeRoute.current!==route
      ||!locked&&pendingNavigation.current.source!=='members')return;
    pendingNavigation.current={actor,locked,message:locked?'请先确认或取消成员操作；结果不明时，先核对再离开。':'',source:'members'};
  },[actor,route]);
  const onTripImportPending=useCallback((locked:boolean)=>{
    if(activeActor.current!==actor||activeRoute.current!==route||!['trips','map','assistant'].includes(route)
      ||!locked&&pendingNavigation.current.source!=='trip-import')return;
    pendingNavigation.current={actor,locked,message:locked?'请先确认或放弃旅行导入；保存结果不明时，先核对再离开。':'',source:'trip-import'};
  },[actor,route]);
  const onFinanceAccountsPending=useCallback((locked:boolean)=>{
    if(activeActor.current!==actor||route!=='finance'||activeRoute.current!==route
      ||!locked&&pendingNavigation.current.source!=='finance-accounts')return;
    pendingNavigation.current={actor,locked,message:locked?'请先保存或放弃账户草稿；结果不明时，先核对或保留操作编号再返回。':'',source:'finance-accounts'};
  },[actor,route]);
  const onShoppingSettlementPending=useCallback((locked:boolean)=>{
    if(activeActor.current!==actor||activeRoute.current!==route||!['shopping','finance'].includes(route)
      ||!locked&&pendingNavigation.current.source!=='shopping-settlement')return;
    pendingNavigation.current={actor,locked,message:locked?'请先完成或取消采购实付核对；保存结果不明时，先读取当前资料再离开。':'',source:'shopping-settlement'};
  },[actor,route]);
  const holdNavigation=()=>{
    if(pendingNavigation.current.actor!==actor||!pendingNavigation.current.locked)return false;
    setNotice(pendingNavigation.current.message);return true;
  };
  useEffect(()=>{
    const isPending=()=>pendingNavigation.current.actor===activeActor.current&&pendingNavigation.current.locked;
    const unsubscribe=pageNavigation.addListener('beforeRemove',event=>{if(isPending()){event.preventDefault();setNotice(pendingNavigation.current.message);}});
    const beforeUnload=(event:BeforeUnloadEvent)=>{if(isPending()){event.preventDefault();event.returnValue='';}};
    if(typeof window!=='undefined')window.addEventListener('beforeunload',beforeUnload);
    return()=>{unsubscribe();if(typeof window!=='undefined')window.removeEventListener('beforeunload',beforeUnload);};
  },[pageNavigation,setNotice]);
  useEffect(()=>{setEditor(null);setPendingId('');setNotice('');},[actor]);
  useEffect(()=>{if(user?.role==='tv')void openLocal('/tv');},[user?.role]);
  const onLegacy=(fragment:string)=>{if(!holdNavigation()&&legacyRoutes.has(fragment))void openLocal('/classic#'+fragment);};
  const onNavigate=(next:RouteName)=>{if(!holdNavigation())router.push((next==='home'?'/':'/'+next) as never);};
  const handle=(action:()=>Promise<unknown>)=>{void action().catch(e=>setNotice(e instanceof Error?e.message:'暂时无法完成操作'));};
  if(loading)return <View style={{flex:1,alignItems:'center',justifyContent:'center',gap:16}}><ActivityIndicator/><Text>正在打开家庭看板…</Text></View>;
  if(!user)return <LoginScreen authError={authResult?.status==='error'?syncAuthMessage(authResult):''}/>;
  if(user.role==='tv')return <View><Text>正在打开电视看板…</Text><Button onPress={()=>openLocal('/tv')}>打开电视</Button></View>;
  if(!state)return <View style={{padding:32,gap:16}}><Text>{error||'正在读取家庭数据…'}</Text><Button onPress={()=>void refresh()}>重新加载</Button><Button onPress={()=>handle(household.logout)}>退出登录</Button></View>;
  const props:ScreenProps={state,user,focus:household.focus,mode:preferences.homeView,layout:household.layout,setFocus:household.setFocus,setMode:async mode=>{
    try{await household.savePreferences({homeView:mode});}catch(failure){if(activeActor.current===actor)setNotice(failure instanceof Error?failure.message:'暂时无法保存显示范围');throw failure;}
  },onNavigate,onLegacy,pendingId,tripRequest,inventoryRequest,onReschedulePending,onDevicePending,onHomeLayoutPending,onAppearancePending,onDocumentsPending,onRoutinesPending,onMembersPending,onSegmentsPending,onTripImportPending,onFinanceSourcePending,onFinanceAccountsPending,onShoppingSettlementPending,
    onInventory:(id)=>{
      if(holdNavigation())return;
      if(id!==undefined&&!/^[a-f0-9]{24}$/.test(id)){setNotice('物品链接已失效，请重新搜索');return;}
      router.push({pathname:'/inventory',params:{request:String(Date.now()),...(id?{item:id}:{})}} as never);
    },
    onEdit:(kind,item)=>{
      if(holdNavigation())return;
      if(kind==='trips'){router.push({pathname:'/trips',params:{request:String(Date.now()),...(item?.id?{item:item.id}:{})}} as never);return;}
      if(item?.sync){setNotice('同步内容请在原应用修改');return;}
      if(kind==='events'&&(item as any)?.travelTiming){onNavigate('trips');return;}
      setEditor({kind,item,key:Date.now()});
    },
    onToggle:async(kind,item)=>{
      if(pendingId||item.sync?.readOnly)return;
      setPendingId(item.id);
      try {await household.mutate('/items/'+kind+'/'+encodeURIComponent(item.id),'PATCH',{done:!item.done,revision:item.revision});await refresh();setNotice(item.done?'已恢复':kind==='shopping'?'已记为买到':'已完成');}
      catch(e){setNotice(e instanceof Error?e.message:'暂时无法保存');}
      finally{setPendingId('');}
    }};
  return <><AppShell route={route} title={titles[route]} name={user.name} householdName={state.household?.name||'我们的家'} onNavigate={onNavigate} onCreate={kind=>props.onEdit(kind)} onRefresh={()=>void refresh()} onLogout={()=>handle(household.logout)} refreshing={household.refreshing} offline={!online} onLegacy={onLegacy}>
    <View key={actor}>
      {household.preferencesUncertain&&<View style={{gap:8,marginBottom:16}} testID="preferences-uncertain">
        <Text>显示设置的保存结果尚未核对。读取当前状态后，再决定是否修改。</Text>
        <Button accessibilityLabel="核对显示设置" mode="outlined" disabled={household.preferencesBusy||!online} onPress={()=>handle(household.checkPreferences)}>核对显示设置</Button>
      </View>}
      {route==='home'?<HomeScreen {...props}/>:route==='calendar'?<CalendarScreen {...props}/>:route==='tasks'||route==='shopping'?<ListScreen key={route} kind={route} {...props}/>:route==='finance'?<FinanceScreen {...props}/>:route==='investments'?<InvestmentsScreen {...props}/>:route==='trips'?<TripsScreen {...props} onReschedulePending={onReschedulePending}/>:route==='photos'?<PhotosScreen {...props}/>:route==='assistant'?<AssistantScreen {...props}/>:route==='inventory'?<InventoryScreen {...props}/>:route==='map'?<MapWorkspace {...props}/>:route==='connections'?<AccountsScreen {...props} authResult={authResult}/>:route==='devices'?<DevicesScreen {...props}/>:<MoreScreen {...props}/>}
    </View>
  </AppShell>{editor&&<ItemEditor key={actor+':'+editor.key} kind={editor.kind} item={editor.item} onDismiss={()=>setEditor(current=>current?.key===editor.key?null:current)}/>}
    {/* Unmount dismissed notices so Paper's previous hide animation cannot hide the next one. */}
    {!!notice&&<Snackbar key={actor+':'+notice} visible onDismiss={()=>setNotice(current=>current===notice?'':current)} duration={5000}
      action={{label:'知道了',onPress:()=>setNotice(current=>current===notice?'':current)}}>{notice}</Snackbar>}
  </>;
}
