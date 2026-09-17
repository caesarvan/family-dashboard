import React, { useState } from 'react';
import { Image, Platform, StyleSheet, View } from 'react-native';
import { Button, Chip, Divider, IconButton, Searchbar, SegmentedButtons, Text, useTheme } from 'react-native-paper';
import { ScreenProps } from '../lib/types';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';
import { useDisplayDensity } from '../ui/theme';

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
  const {kind,state,onToggle,onEdit,pendingId}=props; const theme=useTheme(), density=useDisplayDensity();
  const [filter,setFilter]=useState('pending'); const [query,setQuery]=useState(''); const shopping=kind==='shopping';
  const all=state[kind], pending=all.filter(item=>!item.done);
  const items=all.filter(item=>(filter==='all'||item.done===(filter==='done'))&&(!query||(item.title+' '+(item.note||'')).toLocaleLowerCase().includes(query.toLocaleLowerCase()))).sort((a,b)=>Number(a.done)-Number(b.done)||(a.due||'9999').localeCompare(b.due||'9999'));
  const budget=pending.reduce((sum,item)=>sum+(item.budget||0),0), unknown=pending.filter(item=>!Number.isSafeInteger(item.budget)).length;
  return <View style={[styles.page,{gap:density.screenGap}]}>
    <PageHeader title={shopping?'采购清单':'共同待办'} description={shopping?'需要什么，顺手记下。':'一起安排，完成后直接勾选。'} action={<Button mode="contained" icon="plus" contentStyle={styles.buttonContent} onPress={()=>onEdit(kind)}>{shopping?'添加采购':'添加待办'}</Button>} />
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
        <View testID={`${kind}-item-${item.id}`} style={[styles.row,{paddingVertical:density.rowPadding}]}>
          <CompleteItem title={item.title} checked={item.done} disabled={!!pendingId||!!item.sync?.readOnly} onPress={()=>void onToggle(kind,item)} />
          <View style={styles.body}><Text variant="titleMedium" style={[styles.name,item.done&&{color:theme.colors.onSurfaceVariant,textDecorationLine:'line-through'}]}>{item.title}</Text>
            <Text variant="bodySmall" style={{color:theme.colors.onSurfaceVariant}}>{item.owner==='shared'?'一起':state.people.find(p=>p.id===item.owner)?.name||'家庭成员'}{item.due?' · '+item.due:''}{shopping?' · '+(item.quantity||'1 件'):''}{item.sync?' · 已同步':''}</Text>
            {shopping&&<Text variant="bodySmall">预算 {money(item.budget)}{item.done?' · 实付 '+money(item.actual):''}</Text>}
            {!!item.note&&<Text variant="bodySmall" style={{color:theme.colors.onSurfaceVariant}}>{item.note}</Text>}
            {!!item.photoIds?.length&&<View style={styles.photos}>{item.photoIds.map(id=><Image key={id} accessibilityLabel={item.title+'参考图片'} source={{uri:'/api/photos/'+encodeURIComponent(id)}} style={styles.photo} />)}</View>}
            {item.sync?.readOnly&&<Chip compact>来源只读</Chip>}
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
  photos:{flexDirection:'row',flexWrap:'wrap',gap:8,marginTop:4},photo:{width:68,height:68,borderRadius:8},
});
