import React, { useEffect, useRef, useState } from 'react';
import { StyleSheet, View, useWindowDimensions } from 'react-native';
import { Button, Checkbox, Divider, Text, useTheme } from 'react-native-paper';
import type { ListItem, ScreenProps } from '../lib/types';
import { bounds, dayKey, duration, eventsForDay, overlapsDay, rangeDays, rangeSummary, shortDay } from '../lib/calendar';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';
import { EventRow, RangeControls, WorkloadStrip } from './CalendarScreen';

const cardKeys = ['calendar', 'finance', 'tasks', 'shopping', 'trips'];
const money = (value: number) => Number.isSafeInteger(value) ? '¥' + new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(value / 100) : '待核对';

export default function HomeScreen(props: ScreenProps) {
  const theme = useTheme(), { width } = useWindowDimensions();
  const [busy, setBusy] = useState(''), [error, setError] = useState('');
  const [selectedDay, setSelectedDay] = useState<string | undefined>();
  const identity = `${props.user.householdId}:${props.user.id}:${props.user.auth_version}`;
  const current = useRef(identity); current.current = identity;
  const pending = useRef(false);
  useEffect(() => { pending.current = false; setBusy(''); setError(''); }, [identity]);
  useEffect(() => { setSelectedDay(undefined); }, [identity, props.mode]);
  if (props.user.role !== 'member') return <EmptyState title="请使用成员账户打开首页" />;
  const { state } = props, today = dayKey(), now = Date.now(), days = rangeDays(props.mode);
  const summary = rangeSummary(state.events, days, props.focus);
  const upcoming = state.events.filter(event => days.some(day => overlapsDay(event, day)) && (bounds(event).end > now || bounds(event).start === now))
    .sort((a, b) => bounds(a).start - bounds(b).start || a.id.localeCompare(b.id)).slice(0, 3);
  const chosenDay = selectedDay && days.includes(selectedDay) ? selectedDay : undefined;
  const appointments = chosenDay ? eventsForDay(state.events, chosenDay, props.focus).slice(0, 3) : upcoming;
  const tasks = state.tasks.filter(item => !item.done && (!item.due || item.due <= days.at(-1)!))
    .sort((a, b) => (a.due || '9999').localeCompare(b.due || '9999') || a.id.localeCompare(b.id));
  const due = tasks.filter(item => item.due).length, overdue = tasks.filter(item => item.due && item.due < today).length;
  const shopping = state.shopping.filter(item => !item.done);
  const trip = state.trips.filter(item => item.end >= today).sort((a, b) => a.start.localeCompare(b.start) || a.id.localeCompare(b.id))[0];
  const focusName = state.people.find(person => person.id === props.focus)?.name || '所选成员';
  const owner = (id: string) => state.people.find(person => person.id === id)?.name || '共同';
  const muted = { color: theme.colors.onSurfaceVariant };
  async function toggle(item: ListItem) {
    if (pending.current || props.pendingId || item.sync?.readOnly) return;
    const original = current.current; pending.current = true; setBusy(item.id); setError('');
    try { await props.onToggle('tasks', item); }
    catch { if (original === current.current) setError('未能更新待办，请核对当前状态后重试。'); }
    finally { if (original === current.current) { pending.current = false; setBusy(''); } }
  }
  const cards: Record<string, React.ReactNode> = {
    calendar: <SectionCard title={chosenDay ? `${shortDay(chosenDay)} 的安排` : '接下来的安排'} action={<Button compact onPress={() => props.onNavigate('calendar')}>全部日程</Button>}>
      <Text variant="bodySmall" style={muted}>{focusName} + 共同 · 忙碌 {duration(summary.busyMinutes)}{summary.allDay ? ` · 全天 ${summary.allDay} 项` : ''}</Text>
      {days.length > 1 && <View style={styles.week}><WorkloadStrip summary={summary} selected={chosenDay} onSelect={setSelectedDay} /></View>}
      {appointments.length ? appointments.map(event => <EventRow key={event.id} event={event} day={chosenDay || (bounds(event).start < now ? today : dayKey(bounds(event).start))} props={props} />)
        : <EmptyState title={chosenDay ? '这天还没有安排' : '接下来没有已记录的安排'} action={<Button onPress={() => props.onEdit('events')}>添加安排</Button>} />}
    </SectionCard>,
    finance: <SectionCard title="共同资金" action={<Button compact onPress={() => props.onNavigate('finance')}>查看资金</Button>}>
      <View style={styles.money}><Text variant="bodyMedium" style={muted}>共同余额</Text><Text variant="headlineLarge">{state.finance.confirmedAt ? money(state.finance.wallet) : '待核对'}</Text></View>
      <Divider /><View style={styles.moneyDetails}>
        <View style={styles.flex}><Text variant="bodySmall" style={muted}>本月已支出</Text><Text variant="titleMedium">{state.finance.confirmedAt ? money(state.finance.livingSpent) : '待核对'}</Text></View>
        <View style={styles.flex}><Text variant="bodySmall" style={muted}>本月预算</Text><Text variant="titleMedium">{state.finance.confirmedAt ? money(state.finance.livingBudget) : '待核对'}</Text></View>
      </View><Text variant="bodySmall" style={muted}>{state.finance.confirmedAt ? `手工核对 · ${shortDay(dayKey(state.finance.confirmedAt))}` : '核对共同资金后显示余额。'}</Text>
    </SectionCard>,
    tasks: <SectionCard title="先做这几件" action={<Button compact onPress={() => props.onNavigate('tasks')}>全部待办</Button>}>
      {tasks.length ? tasks.slice(0, 4).map(item => <View key={item.id} style={styles.task}>
        <Checkbox status="unchecked" accessibilityLabel={`完成待办：${item.title}`} disabled={!!(busy || props.pendingId || item.sync?.readOnly)} onPress={() => void toggle(item)} />
        <View style={styles.flex}><Text variant="titleSmall">{item.title}</Text><Text variant="bodySmall" style={muted}>{item.due ? `${item.due < today ? '已逾期 · ' : ''}${shortDay(item.due)}` : '未设日期'} · {owner(item.owner)}{item.sync?.readOnly ? ' · 来源只读' : ''}</Text></View>
      </View>) : <EmptyState title="到期待办已处理完" action={<Button onPress={() => props.onEdit('tasks')}>添加待办</Button>} />}
      {tasks.length > 4 && <Text variant="bodySmall" style={muted}>还有 {tasks.length - 4} 项到期或未排期待办</Text>}
      {!!error && <Text accessibilityRole="alert" style={{ color: theme.colors.error }}>{error}</Text>}
    </SectionCard>,
    shopping: <SectionCard title="需要添置" action={<Button compact onPress={() => props.onNavigate('shopping')}>采购清单</Button>}>
      {shopping.length ? shopping.slice(0, 3).map(item => <View key={item.id} style={styles.task}><View style={styles.flex}>
        <Text variant="titleSmall">{item.title}</Text><Text variant="bodySmall" style={muted}>{item.quantity || '未填数量'}</Text></View>
        <Button compact onPress={() => props.onEdit('shopping', item)}>查看</Button></View>)
        : <EmptyState title="暂时没有待采购的物品" action={<Button onPress={() => props.onEdit('shopping')}>添加采购</Button>} />}
      {shopping.length > 3 && <Text variant="bodySmall" style={muted}>还有 {shopping.length - 3} 件待采购</Text>}
    </SectionCard>,
    trips: <SectionCard title="下一趟旅行" action={<Button compact onPress={() => props.onNavigate('trips')}>全部旅行</Button>}>
      {trip ? <View style={styles.trip}><Text variant="titleMedium">{trip.title}</Text><Text variant="bodyMedium" style={muted}>{shortDay(trip.start)}—{shortDay(trip.end)}{trip.destination ? ` · ${trip.destination}` : ''}</Text>
        <Button mode="outlined" onPress={() => props.onEdit('trips', trip)}>查看行程</Button></View>
        : <EmptyState title="还没有下一趟旅行" action={<Button onPress={() => props.onEdit('trips')}>计划旅行</Button>} />}
    </SectionCard>,
  };
  const order = [...new Set([...props.layout.order.filter(key => cardKeys.includes(key)), ...cardKeys])].filter(key => !props.layout.hidden.includes(key));
  return <View style={styles.screen}>
    <PageHeader title={`${props.user.name}，欢迎回家`} description={`${shortDay(today)} · 把今天安排得轻一点`} action={<Button icon="plus" mode="contained" onPress={() => props.onEdit('tasks')}>添加待办</Button>} />
    <RangeControls props={props} />
    <View style={styles.metrics}>
      <Text variant="bodyMedium"><Text variant="titleMedium">{summary.total}</Text> 项安排</Text>
      <Text variant="bodyMedium"><Text variant="titleMedium">{due}</Text> 项到期待办{overdue ? ` · ${overdue} 项逾期` : ''}</Text>
      <Text variant="bodyMedium"><Text variant="titleMedium">{shopping.length}</Text> 件待采购</Text>
    </View>
    <View style={styles.grid}>{order.map(key => <View key={key} style={[styles.card, { width: width >= 1000 ? '49%' : '100%' }]}>{cards[key]}</View>)}</View>
  </View>;
}

const styles = StyleSheet.create({
  screen: { gap: 16 }, metrics: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between', gap: 16 }, card: { minWidth: 0 },
  flex: { flex: 1, minWidth: 0, gap: 4 }, week: { marginTop: 12 }, money: { gap: 6, paddingVertical: 16 },
  moneyDetails: { flexDirection: 'row', gap: 16, paddingVertical: 16 },
  task: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 10 }, trip: { gap: 12 },
});
