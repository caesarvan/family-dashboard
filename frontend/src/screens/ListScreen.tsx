import React, { useState } from 'react';
import { Image, StyleSheet, View } from 'react-native';
import { Button, Checkbox, Chip, Divider, IconButton, Searchbar, SegmentedButtons, Text, useTheme } from 'react-native-paper';
import { ScreenProps } from '../lib/types';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';

export const money = (value?:number|null) => Number.isSafeInteger(value) ? '¥'+((value as number)/100).toLocaleString('zh-CN',{maximumFractionDigits:2}) : '未填写';
export default function ListScreen(props: ScreenProps & {kind:'tasks'|'shopping'}) {
  const {kind,state,onToggle,onEdit,pendingId}=props; const theme=useTheme();
  const [filter,setFilter]=useState('pending'); const [query,setQuery]=useState(''); const shopping=kind==='shopping';
  const all=state[kind], pending=all.filter(item=>!item.done);
  const items=all.filter(item=>(filter==='all'||item.done===(filter==='done'))&&(!query||(item.title+' '+(item.note||'')).toLocaleLowerCase().includes(query.toLocaleLowerCase()))).sort((a,b)=>Number(a.done)-Number(b.done)||(a.due||'9999').localeCompare(b.due||'9999'));
  const budget=pending.reduce((sum,item)=>sum+(item.budget||0),0), unknown=pending.filter(item=>!Number.isSafeInteger(item.budget)).length;
  return <View style={styles.page}>
    <PageHeader title={shopping?'采购清单':'共同待办'} description={shopping?'需要什么，顺手记下。':'一起安排，完成后直接勾选。'} action={<Button mode="contained" icon="plus" onPress={()=>onEdit(kind)}>{shopping?'添加采购':'添加待办'}</Button>} />
    {shopping&&<SectionCard title="待采购预算"><Text variant="headlineMedium">{money(budget)}</Text><Text variant="bodySmall" style={{color:theme.colors.onSurfaceVariant}}>{unknown?`另有 ${unknown} 件未填写预算`:'已填写物品的预计总价'} · 采购预算不会自动计入支出</Text></SectionCard>}
    {shopping&&<Button icon="package-variant-closed" mode="outlined" onPress={()=>props.onInventory()}>查看家里已有和在途物品</Button>}
    <View style={styles.tools}><SegmentedButtons style={styles.filters} value={filter} onValueChange={setFilter} buttons={[{value:'pending',label:shopping?'待采购':'待完成'},{value:'done',label:shopping?'已买到':'已完成'},{value:'all',label:'全部'}]} /><Searchbar style={styles.search} placeholder={shopping?'搜索物品':'搜索待办'} value={query} onChangeText={setQuery} /></View>
    <SectionCard title={`${filter==='all'?'全部':filter==='done'?'已完成':'待处理'} · ${items.length} 项`}>
      {!items.length?<EmptyState title={query?'没有找到匹配内容':'清单很清爽'} description={query?'换一个关键词试试。':shopping?'把下次需要买的东西记下来。':'需要处理的事情，随时加进来。'} />:items.map((item,index)=><React.Fragment key={item.id}>
        {index>0&&<Divider />}
        <View style={styles.row}>
          <Checkbox.Android status={item.done?'checked':'unchecked'} disabled={!!pendingId||!!item.sync?.readOnly} onPress={()=>void onToggle(kind,item)} accessibilityLabel={(item.done?'恢复':'完成')+item.title} />
          <View style={styles.body}><Text variant="titleMedium" style={[styles.name,item.done&&{color:theme.colors.onSurfaceVariant,textDecorationLine:'line-through'}]}>{item.title}</Text>
            <Text variant="bodySmall" style={{color:theme.colors.onSurfaceVariant}}>{item.owner==='shared'?'一起':state.people.find(p=>p.id===item.owner)?.name||'家庭成员'}{item.due?' · '+item.due:''}{shopping?' · '+(item.quantity||'1 件'):''}{item.sync?' · 已同步':''}</Text>
            {shopping&&<Text variant="bodySmall">预算 {money(item.budget)}{item.done?' · 实付 '+money(item.actual):''}</Text>}
            {!!item.note&&<Text variant="bodySmall" style={{color:theme.colors.onSurfaceVariant}}>{item.note}</Text>}
            {!!item.photoIds?.length&&<View style={styles.photos}>{item.photoIds.map(id=><Image key={id} accessibilityLabel={item.title+'参考图片'} source={{uri:'/api/photos/'+encodeURIComponent(id)}} style={styles.photo} />)}</View>}
            {item.sync?.readOnly&&<Chip compact>来源只读</Chip>}
          </View>
          {!item.sync&&<IconButton icon="pencil-outline" accessibilityLabel={'编辑'+item.title} onPress={()=>onEdit(kind,item)} />}
        </View>
      </React.Fragment>)}
    </SectionCard>
    {!shopping&&<Button icon="cloud-sync-outline" onPress={()=>props.onLegacy('connections')}>管理同步清单</Button>}
  </View>;
}
const styles=StyleSheet.create({page:{gap:20},tools:{gap:12,flexDirection:'row',flexWrap:'wrap'},filters:{flexGrow:1,minWidth:270},search:{flexGrow:1,minWidth:220,height:48,borderRadius:8},row:{flexDirection:'row',alignItems:'flex-start',gap:8,paddingVertical:14},body:{flex:1,minWidth:0,gap:6},name:{fontSize:15,lineHeight:23,fontWeight:'600'},photos:{flexDirection:'row',flexWrap:'wrap',gap:8,marginTop:4},photo:{width:68,height:68,borderRadius:8}});
