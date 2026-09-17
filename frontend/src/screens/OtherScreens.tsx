import React, { useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { Divider, List } from 'react-native-paper';
import { ScreenProps } from '../lib/types';
import { PageHeader, SectionCard } from '../ui/components';
import AppearancePanel from './AppearancePanel';
import JourneyDocumentsPanel from './JourneyDocumentsPanel';
import RoutinesPanel from './RoutinesPanel';

export function MoreScreen(props:ScreenProps) {
  const [appearance, setAppearance] = useState(false);
  const [documents, setDocuments] = useState(false);
  const [routines, setRoutines] = useState(false);
  if(appearance)return <AppearancePanel onClose={()=>setAppearance(false)} onPendingChange={props.onAppearancePending}/>;
  if(documents)return <JourneyDocumentsPanel onBack={()=>setDocuments(false)} onPendingChange={props.onDocumentsPending}/>;
  if(routines)return <RoutinesPanel onBack={()=>setRoutines(false)} onPendingChange={props.onRoutinesPending}/>;
  const groups=[{title:'共同生活',items:[['routines','家庭例行计划','calendar-sync-outline'],['trips','旅行计划','airplane'],['documents','我的旅行资料','file-document-outline'],['finance','家庭资金','wallet-outline'],['investments','我的持仓','chart-donut']]},{title:'回忆与物品',items:[['photos','家庭相册','image-multiple-outline'],['map','足迹地图','map-outline'],['inventory','家庭物品','package-variant']]},{title:'工具与设置',items:[['assistant','家庭助理','creation-outline'],['connections','账户与自动同步','cloud-sync-outline'],['devices','电视与播放','television'],['household','家庭与成员','account-group-outline'],['settings','外观与其他设置','cog-outline']]}];
  return <View style={styles.page}><PageHeader title="更多" description="常用工具，集中在这里。"/>{groups.map(group=><SectionCard title={group.title} key={group.title}>{group.items.map(([route,title,icon],index)=><React.Fragment key={route}>{index>0&&<Divider/>}<List.Item title={route==='settings'?'外观设置':title} accessibilityLabel={route==='settings'?'外观设置':title} left={p=><List.Icon {...p} icon={icon}/>} right={p=><List.Icon {...p} icon="chevron-right"/>} onPress={()=>route==='settings'?setAppearance(true):route==='documents'?setDocuments(true):route==='routines'?setRoutines(true):route==='trips'||route==='finance'||route==='investments'||route==='photos'||route==='assistant'||route==='inventory'||route==='map'||route==='connections'||route==='devices'?props.onNavigate(route):props.onLegacy(route)} /></React.Fragment>)}</SectionCard>)}</View>;
}
const styles=StyleSheet.create({page:{gap:20}});
