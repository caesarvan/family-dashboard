import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, Image, Platform, StyleSheet, View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { Button, Chip, Divider, IconButton, Searchbar, SegmentedButtons, Text, useTheme } from 'react-native-paper';
import { FamilyState, ScreenProps } from '../lib/types';
import { useHousehold } from '../lib/household';
import { request } from '../lib/api';
import { PhotoReadFence, type PhotoSession } from '../lib/photos';
import ShoppingSettlementPanel from '../components/ShoppingSettlementPanel';
import InventoryScreen from './InventoryScreen';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';
import { useDisplayDensity } from '../ui/theme';
import { dayKey } from '../lib/calendar';
import { compareShoppingItems, shoppingScheduleText } from '../lib/trips';

export const money = (value?:number|null) => Number.isSafeInteger(value) ? '¥'+((value as number)/100).toLocaleString('zh-CN',{maximumFractionDigits:2}) : '未填写';

function CompleteItem({ title, checked, disabled, onPress }: { title: string; checked: boolean; disabled: boolean; onPress: () => void }) {
  // Paper icon checkbox with a >=44px target (pending DOM measurement) and one Space action.
  const keyboard = Platform.OS === 'web' ? { onKeyDown: (event: React.KeyboardEvent<HTMLElement>) => {
    if (event.key === ' ' || event.key === 'Spacebar') {
      event.preventDefault(); event.stopPropagation();
      if (!disabled && !event.repeat) onPress();
    }
  } } : {};
  return <IconButton {...keyboard} icon={checked ? 'checkbox-marked' : 'checkbox-blank-outline'} size={24}
    accessibilityRole="checkbox" accessibilityLabel={(checked ? '恢复' : '完成') + title}
    accessibilityState={{ checked, disabled }} aria-checked={checked} disabled={disabled}
    onPress={onPress} style={styles.iconButton} />;
}

export default function ListScreen(props: ScreenProps & {kind:'tasks'|'shopping'}) {
  const household=useHousehold();
  return <ListWorkspace key={household.identityKey+':'+props.kind} {...props} identityKey={household.identityKey} />;
}

function ListWorkspace(props: ScreenProps & {kind:'tasks'|'shopping';identityKey:string}) {
  const {kind,onToggle,onEdit,pendingId}=props; const theme=useTheme(), density=useDisplayDensity(), household=useHousehold();
  const latest=useRef(household);latest.current=household;
  const alive=useRef(false), focused=useRef(false), settlementRef=useRef<string|null>(null), settlementPending=useRef(false);
  const [settlement,setSettlement]=useState<string|null>(null), [savedState,setSavedState]=useState<FamilyState|null>(null);
  const [inventoryShopping,setInventoryShopping]=useState<string|null>(null), [returnToItem,setReturnToItem]=useState<string|null>(null);
  const [returnNotice,setReturnNotice]=useState('');
  const inventoryPending=useRef(false), positionedReturn=useRef<string|null>(null);
  const notifyInventoryPending=useCallback((message:string|null)=>{
    inventoryPending.current=!!message;props.onInventoryPending?.(message);
  },[props.onInventoryPending]);
  function returnFromInventory(){
    if(!alive.current||!focused.current||latest.current.identityKey!==props.identityKey||inventoryPending.current||!inventoryShopping)return;
    setReturnToItem(inventoryShopping);setInventoryShopping(null);void latest.current.refresh();
  }
  const state=savedState&&savedState.revision>props.state.revision?savedState:props.state;
  const settlementFence=useRef(new PhotoReadFence(()=>request<PhotoSession>('/me'),props.user,props.identityKey));
  const current=()=>alive.current&&focused.current&&latest.current.identityKey===props.identityKey&&latest.current.user?.role==='member'
    &&latest.current.online&&AppState.currentState!=='background'&&AppState.currentState!=='inactive'
    &&(typeof document==='undefined'||!document.hidden)&&(typeof navigator==='undefined'||navigator.onLine!==false);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;settlementFence.current.invalidate();props.onShoppingSettlementPending?.(false);};},[]);
  useFocusEffect(useCallback(()=>{focused.current=true;return()=>{focused.current=false;settlementFence.current.invalidate();};},[]));
  const notifySettlementPending=useCallback((value:boolean)=>{
    if(!alive.current||latest.current.identityKey!==props.identityKey||!settlementRef.current)return;
    settlementPending.current=value;props.onShoppingSettlementPending?.(value);
  },[props.identityKey,props.onShoppingSettlementPending]);
  function openSettlement(id:string){
    if(kind!=='shopping'||!current()||pendingId||settlementRef.current)return;
    settlementRef.current=id;settlementPending.current=false;setSettlement(id);
  }
  function closeSettlement(){
    if(!alive.current||!focused.current||latest.current.identityKey!==props.identityKey||settlementPending.current)return;
    settlementFence.current.invalidate();settlementRef.current=null;setSettlement(null);props.onShoppingSettlementPending?.(false);
  }
  async function settlementSaved(){
    const target=settlementRef.current;
    if(!target)throw new Error('核对页面已关闭，请重新读取采购清单。');
    // refresh() catches errors internally. Read explicitly before acknowledging
    // parent refresh, so a known save cannot be mistaken for a refreshed list.
    const snapshot=await settlementFence.current.read(()=>request<FamilyState>('/state'),()=>current()&&settlementRef.current===target);
    if(!Number.isSafeInteger(snapshot.revision)||!Array.isArray(snapshot.shopping))throw new Error('采购清单暂时无法核对，请重新读取。');
    setSavedState(snapshot);void latest.current.refresh();
  }
  const [filter,setFilter]=useState('pending'); const [query,setQuery]=useState(''); const shopping=kind==='shopping';
  const all=state[kind], pending=all.filter(item=>!item.done);
  const today=dayKey(new Date());
  const items=all.filter(item=>(filter==='all'||item.done===(filter==='done'))&&(!query||(item.title+' '+(item.note||'')).toLocaleLowerCase().includes(query.toLocaleLowerCase()))).sort(shopping?compareShoppingItems:(a,b)=>Number(a.done)-Number(b.done)||(a.due||'9999').localeCompare(b.due||'9999'));
  const budget=pending.reduce((sum,item)=>sum+(item.budget||0),0), unknown=pending.filter(item=>!Number.isSafeInteger(item.budget)).length;
  useEffect(()=>{
    if(inventoryShopping||!returnToItem)return;
    const original=all.find(row=>row.id===returnToItem);
    setReturnNotice(!original?'原采购已不在当前清单中。':!items.some(row=>row.id===returnToItem)?'原采购已不符合当前筛选，可切换“全部”查看。':'已返回原采购，筛选保持不变。');
    if(typeof document!=='undefined'&&positionedReturn.current!==returnToItem){
      positionedReturn.current=returnToItem;
      const row=document.querySelector<HTMLElement>(`[data-testid="shopping-item-${returnToItem}"]`);
      row?.scrollIntoView({block:'center'});row?.focus({preventScroll:true});
    }
  },[inventoryShopping,returnToItem,state.revision,filter,query]);
  if(inventoryShopping)return <InventoryScreen {...props} inventoryRequest={undefined} shoppingSourceId={inventoryShopping} onReturnToShopping={returnFromInventory} onInventoryPending={notifyInventoryPending}/>;
  if(settlement)return <ShoppingSettlementPanel key={props.identityKey+':'+settlement} shoppingId={settlement} onClose={closeSettlement} onSaved={settlementSaved} onPendingChange={notifySettlementPending} />;
  return <View style={[styles.page,{gap:density.screenGap}]}>
    <PageHeader title={shopping?'采购清单':'共同待办'} description={shopping?'需要什么，顺手记下。':'一起安排，完成后直接勾选。'} action={<Button mode="contained" icon="plus" contentStyle={styles.buttonContent} onPress={()=>onEdit(kind)}>{shopping?'添加采购':'添加待办'}</Button>} />
    {!!returnNotice&&<Text accessibilityLiveRegion="polite">{returnNotice}</Text>}
    {shopping&&<SectionCard title="待采购预算"><Text variant="headlineMedium">{money(budget)}</Text><Text variant="bodySmall" style={{color:theme.colors.onSurfaceVariant}}>{unknown?`另有 ${unknown} 件未填写预算`:'已填写物品的预计总价'} · 采购预算不会自动计入支出</Text></SectionCard>}
    {shopping&&<Button icon="package-variant-closed" mode="outlined" contentStyle={styles.buttonContent} onPress={()=>props.onInventory()}>查看家里已有和在途物品</Button>}
    <View style={[styles.tools,{gap:density.sectionGap}]}><SegmentedButtons style={styles.filters} density="regular" value={filter} onValueChange={setFilter} buttons={[
      {value:'pending',label:shopping?'待采购':'待完成',style:styles.filterButton,labelStyle:styles.segmentLabel},
      {value:'done',label:shopping?'已买到':'已完成',style:styles.filterButton,labelStyle:styles.segmentLabel},
      {value:'all',label:'全部',style:styles.filterButton,labelStyle:styles.segmentLabel},
    ]} /><Searchbar style={styles.search} placeholder={shopping?'搜索物品':'搜索待办'} value={query} onChangeText={setQuery} /></View>
    <SectionCard title={`${filter==='all'?'全部':filter==='done'?'已完成':'待处理'} · ${items.length} 项`}>
      {!items.length?<EmptyState title={query?'没有找到匹配内容':'清单很清爽'} description={query?'换一个关键词试试。':shopping?'把下次需要买的东西记下来。':'需要处理的事情，随时加进来。'} />:items.map((item,index)=><React.Fragment key={item.id}>
        {index>0&&<Divider />}
        <View testID={`${kind}-item-${item.id}`} tabIndex={shopping&&returnToItem===item.id?-1:undefined} style={[styles.row,{paddingVertical:density.rowPadding}]}>
          <CompleteItem title={item.title} checked={item.done} disabled={!!pendingId||!!item.sync?.readOnly} onPress={()=>void onToggle(kind,item)} />
          <View style={styles.body}><Text variant="titleMedium" style={[styles.name,item.done&&{color:theme.colors.onSurfaceVariant,textDecorationLine:'line-through'}]}>{item.title}</Text>
            <Text variant="bodySmall" style={{color:theme.colors.onSurfaceVariant}}>{item.owner==='shared'?'一起':state.people.find(p=>p.id===item.owner)?.name||'家庭成员'}{!shopping&&item.due?' · '+item.due:''}{shopping?' · '+(item.quantity||'1 件'):''}{item.sync?' · 已同步':''}</Text>
            {shopping&&<Text variant="bodySmall" style={{color:!item.done&&!!item.due&&item.due<today?theme.colors.error:theme.colors.onSurfaceVariant}}>{shoppingScheduleText(item,today)}</Text>}
            {shopping&&<Text variant="bodySmall">预算 {money(item.budget)}{item.done||Number.isSafeInteger(item.actual)?' · 实付 '+money(item.actual):''}</Text>}
            {!!item.note&&<Text variant="bodySmall" style={{color:theme.colors.onSurfaceVariant}}>{item.note}</Text>}
            {!!item.photoIds?.length&&<View style={styles.photos}>{item.photoIds.map(id=><Image key={id} accessibilityLabel={item.title+'参考图片'} source={{uri:'/api/photos/'+encodeURIComponent(id)}} style={styles.photo} />)}</View>}
            {item.sync?.readOnly&&<Chip compact>来源只读</Chip>}
            {shopping&&<Button icon="package-variant-closed" accessibilityLabel={'登记或查看库存：'+item.title} contentStyle={styles.buttonContent} style={styles.settlementButton} disabled={!!pendingId||!household.online} onPress={()=>{if(current()&&!settlementRef.current){positionedReturn.current=null;setReturnNotice('');setInventoryShopping(item.id);}}}>登记或查看库存</Button>}
            {shopping&&!item.sync&&<Button icon="receipt-text-check-outline" accessibilityLabel={'核对实付：'+item.title} contentStyle={styles.buttonContent} style={styles.settlementButton} disabled={!!pendingId||!household.online} onPress={()=>openSettlement(item.id)}>核对实付</Button>}
          </View>
          {!item.sync&&<IconButton icon="pencil-outline" size={24} style={styles.iconButton} accessibilityLabel={'编辑'+item.title} onPress={()=>onEdit(kind,item)} />}
        </View>
      </React.Fragment>)}
    </SectionCard>
    {!shopping&&<Button icon="cloud-sync-outline" contentStyle={styles.buttonContent} onPress={()=>props.onLegacy('connections')}>管理同步清单</Button>}
  </View>;
}
const styles=StyleSheet.create({
  page:{minWidth:0},tools:{flexDirection:'row',flexWrap:'wrap'},
  filters:{flexGrow:1,flexBasis:280,minWidth:0,maxWidth:'100%'},filterButton:{minWidth:0},
  // Height is inside Paper's ripple, not padding around a smaller hit target.
  segmentLabel:{minHeight:26,paddingVertical:3},buttonContent:{minHeight:44},
  search:{flexGrow:1,flexBasis:220,minWidth:0,maxWidth:'100%',height:48,borderRadius:8},
  row:{flexDirection:'row',alignItems:'flex-start',gap:8},iconButton:{margin:0,minWidth:44,minHeight:44,flexShrink:0},
  body:{flex:1,minWidth:0,gap:6},name:{fontSize:15,lineHeight:23,fontWeight:'600'},
  settlementButton:{alignSelf:'flex-start',maxWidth:'100%'},
  photos:{flexDirection:'row',flexWrap:'wrap',gap:8,marginTop:4},photo:{width:68,height:68,borderRadius:8},
});
