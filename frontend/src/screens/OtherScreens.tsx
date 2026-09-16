import React from 'react';
import { StyleSheet, View } from 'react-native';
import { Button, Divider, List, Text, useTheme } from 'react-native-paper';
import { ScreenProps } from '../lib/types';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';
import { money } from './ListScreen';

export function FinanceScreen(props:ScreenProps) {
  const finance=props.state.finance, confirmed=!!finance.confirmedAt;
  const theme=useTheme();
  return <View style={styles.page}><PageHeader title="家庭资金" description="共同资金一起看，个人明细自己管。" action={<Button mode="contained" onPress={()=>props.onLegacy('finance')}>核对与管理</Button>}/>
    <SectionCard title="共同余额"><Text variant="displaySmall" style={{fontWeight:'600'}}>{confirmed?money(finance.wallet):'待核对'}</Text><Text variant="bodySmall" style={{color:theme.colors.onSurfaceVariant}}>周转目标 {money(finance.reserveTarget)}</Text></SectionCard>
    <View style={styles.grid}>{[['本月支出',finance.livingSpent],['日常预算',finance.livingBudget],['旅行准备金',finance.travelSaved],['长期共同储蓄',finance.longterm]].map(([title,value])=><View style={styles.metric} key={title as string}><SectionCard title={title as string}><Text variant="headlineSmall">{confirmed?money(value as number):'待核对'}</Text></SectionCard></View>)}</View>
    <Text variant="bodySmall">{confirmed?'上次核对：'+finance.confirmedAt:'尚未核对共同资金。'} · 税后收入 {finance.contributionPercent}% 共同出资</Text>
    <Button icon="lock-outline" onPress={()=>props.onLegacy('finance')}>查看本人账户、资产与账单</Button>
  </View>;
}
export function MoreScreen(props:ScreenProps) {
  const groups=[{title:'共同生活',items:[['trips','旅行计划','airplane'],['finance','家庭资金','wallet-outline']]},{title:'回忆与物品',items:[['photos','家庭相册','image-multiple-outline'],['map','足迹地图','map-outline'],['inventory','家庭物品','package-variant']]},{title:'工具与设置',items:[['assistant','家庭助理','creation-outline'],['connections','账户与自动同步','cloud-sync-outline'],['household','家庭与成员','account-group-outline'],['settings','电视、外观与其他设置','cog-outline']]}];
  return <View style={styles.page}><PageHeader title="更多" description="常用工具，集中在这里。"/>{groups.map(group=><SectionCard title={group.title} key={group.title}>{group.items.map(([route,title,icon],index)=><React.Fragment key={route}>{index>0&&<Divider/>}<List.Item title={title} left={p=><List.Icon {...p} icon={icon}/>} right={p=><List.Icon {...p} icon="chevron-right"/>} onPress={()=>route==='trips'||route==='finance'||route==='photos'||route==='assistant'||route==='inventory'||route==='map'||route==='connections'?props.onNavigate(route):props.onLegacy(route)} /></React.Fragment>)}</SectionCard>)}</View>;
}
const styles=StyleSheet.create({page:{gap:20},grid:{flexDirection:'row',flexWrap:'wrap',gap:16},metric:{minWidth:220,flex:1}});
