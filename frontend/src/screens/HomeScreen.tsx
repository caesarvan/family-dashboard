import React, { useEffect, useRef, useState } from 'react';
import { Platform, StyleSheet, View, useWindowDimensions } from 'react-native';
import { Button, Divider, IconButton, Text, useTheme } from 'react-native-paper';
import type { ListItem, ScreenProps } from '../lib/types';
import { dependencyStates } from '../lib/taskDependencies';
import { bounds, dayKey, duration, eventsForDay, overlapsDay, rangeDays, rangeSummary, shortDay } from '../lib/calendar';
import { EmptyState, SectionCard } from '../ui/components';
import { useDisplayDensity } from '../ui/theme';
import { EventRow, RangeControls, WorkloadStrip } from './CalendarScreen';
import HomeLayoutPanel from './HomeLayoutPanel';

const cardKeys = ['calendar', 'finance', 'tasks', 'shopping', 'trips'];
const money = (value: number) => Number.isSafeInteger(value) ? '¥' + new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(value / 100) : '待核对';

function CompleteTask({ title, disabled, onPress }: { title: string; disabled: boolean; onPress: () => void }) {
  // Paper Checkbox.Android fixes its control at 36px even when given a style.
  // Use Paper's 48px icon control with the same checkbox semantics and keyboard action.
  const keyboard = Platform.OS === 'web' ? { onKeyDown: (event: React.KeyboardEvent<HTMLElement>) => {
    if (event.key === ' ' || event.key === 'Spacebar') { event.preventDefault(); event.stopPropagation(); if (!disabled && !event.repeat) onPress(); }
  } } : {};
  return <IconButton {...keyboard} icon="checkbox-blank-outline" size={24} accessibilityRole="checkbox"
    accessibilityLabel={`完成待办：${title}`} accessibilityState={{ checked: false, disabled }} aria-checked={false}
    disabled={disabled} onPress={onPress} style={styles.taskCheckbox} />;
}

export default function HomeScreen(props: ScreenProps) {
  const theme = useTheme(), { width } = useWindowDimensions();
  const density = useDisplayDensity();
  const [busy, setBusy] = useState(''), [error, setError] = useState('');
  const [layoutOpen, setLayoutOpen] = useState(false);
  const [selectedDay, setSelectedDay] = useState<string | undefined>();
  const identity = `${props.user.householdId}:${props.user.id}:${props.user.auth_version}`;
  const current = useRef(identity); current.current = identity;
  const pending = useRef(false);
  useEffect(() => { pending.current = false; setBusy(''); setError(''); setLayoutOpen(false); }, [identity]);
  useEffect(() => { setSelectedDay(undefined); }, [identity, props.mode]);
  if (props.user.role !== 'member') return <EmptyState title="请使用成员账户打开首页" />;
  if (layoutOpen) return <HomeLayoutPanel onClose={() => setLayoutOpen(false)} onPendingChange={props.onHomeLayoutPending} />;
  const { state } = props, today = dayKey(), now = Date.now(), days = rangeDays(props.mode);
  const summary = rangeSummary(state.events, days, props.focus);
  const upcoming = state.events.filter(event => days.some(day => overlapsDay(event, day)) && (bounds(event).end > now || bounds(event).start === now))
    .sort((a, b) => bounds(a).start - bounds(b).start || a.id.localeCompare(b.id)).slice(0, 3);
  const chosenDay = selectedDay && days.includes(selectedDay) ? selectedDay : undefined;
  const appointments = chosenDay ? eventsForDay(state.events, chosenDay, props.focus).slice(0, 3) : upcoming;
  const dependencyState=dependencyStates(state.tasks);
  const tasks = state.tasks.filter(item => !item.done && (!item.due || item.due <= days.at(-1)!))
    .sort((a, b) => Number(dependencyState.get(a.id)!.blocked)-Number(dependencyState.get(b.id)!.blocked) || (a.due || '9999').localeCompare(b.due || '9999') || a.id.localeCompare(b.id));
  const due = tasks.filter(item => item.due).length, overdue = tasks.filter(item => item.due && item.due < today).length;
  const shopping = state.shopping.filter(item => !item.done);
  const trip = state.trips.filter(item => item.end >= today).sort((a, b) => a.start.localeCompare(b.start) || a.id.localeCompare(b.id))[0];
  const focusName = state.people.find(person => person.id === props.focus)?.name || '所选成员';
  const owner = (id: string) => state.people.find(person => person.id === id)?.name || '共同';
  const muted = { color: theme.colors.onSurfaceVariant };
  const wide = width >= 1000;
  const bento = { backgroundColor: theme.colors.surfaceVariant, borderWidth: 0, borderRadius: wide ? 40 : 24 };
  async function toggle(item: ListItem) {
    if (pending.current || props.pendingId || item.sync?.readOnly || dependencyState.get(item.id)!.blocked) return;
    const original = current.current; pending.current = true; setBusy(item.id); setError('');
    try { await props.onToggle('tasks', item); }
    catch { if (original === current.current) setError('未能更新待办，请核对当前状态后重试。'); }
    finally { if (original === current.current) { pending.current = false; setBusy(''); } }
  }
  const cards: Record<string, React.ReactNode> = {
    calendar: <SectionCard style={[styles.bento, bento]} title={chosenDay ? `${shortDay(chosenDay)} 的安排` : '接下来的安排'} action={<Button contentStyle={styles.primaryContent} compact onPress={() => props.onNavigate('calendar')}>全部日程</Button>}>
      <Text variant="bodySmall" style={muted}>{focusName} + 共同 · 忙碌 {duration(summary.busyMinutes)}{summary.allDay ? ` · 全天 ${summary.allDay} 项` : ''}</Text>
      {days.length > 1 && <View style={styles.week}><WorkloadStrip summary={summary} selected={chosenDay} onSelect={setSelectedDay} /></View>}
      {appointments.length ? appointments.map(event => <EventRow key={event.id} event={event} day={chosenDay || (bounds(event).start < now ? today : dayKey(bounds(event).start))} props={props} />)
        : <EmptyState title={chosenDay ? '这天还没有安排' : '接下来没有已记录的安排'} action={<Button contentStyle={styles.primaryContent} onPress={() => props.onEdit('events')}>添加安排</Button>} />}
    </SectionCard>,
    finance: <SectionCard style={[styles.bento, bento]} title="共同资金" action={state.finance.confirmedAt ? <Button contentStyle={styles.primaryContent} compact onPress={() => props.onNavigate('finance')}>查看资金</Button> : undefined}>
      {state.finance.confirmedAt ? <>
        <View style={[styles.money, { paddingVertical: wide ? density.moneyPadding : density.moneyPaddingNarrow }]}><Text variant="bodyMedium" style={muted}>共同余额</Text><Text variant="headlineLarge" style={wide ? styles.balanceWide : styles.balance}>{money(state.finance.wallet)}</Text></View>
        <Divider /><View style={[styles.moneyDetails, { paddingVertical: density.detailPadding }]}>
          <View style={styles.flex}><Text variant="bodySmall" style={muted}>本月已支出</Text><Text variant="titleMedium">{money(state.finance.livingSpent)}</Text></View>
          <View style={styles.flex}><Text variant="bodySmall" style={muted}>本月预算</Text><Text variant="titleMedium">{money(state.finance.livingBudget)}</Text></View>
        </View><Text variant="bodySmall" style={muted}>{`手工核对 · ${shortDay(dayKey(state.finance.confirmedAt))}`}</Text>
      </> : <View style={styles.financeUnconfirmed}>
        <Text variant="bodyLarge" style={muted}>共同资金尚未核对。请先确认余额、本月支出和预算。</Text>
        <Button contentStyle={styles.primaryContent} mode="outlined" style={styles.financeAction} onPress={() => props.onNavigate('finance')}>核对资金</Button>
      </View>}
    </SectionCard>,
    tasks: <SectionCard style={[styles.bento, bento]} title="先做这几件" action={<Button contentStyle={styles.primaryContent} compact onPress={() => props.onNavigate('tasks')}>全部待办</Button>}>
      {tasks.length ? tasks.slice(0, 4).map(item => <View key={item.id} style={[styles.task, { paddingVertical: density.rowPadding }]}>
        <CompleteTask title={item.title} disabled={!!(busy || props.pendingId || item.sync?.readOnly || dependencyState.get(item.id)!.blocked)} onPress={() => void toggle(item)} />
        <View style={styles.flex}><Text variant="titleSmall">{item.title}</Text><Text variant="bodySmall" style={muted}>{item.due ? `${item.due < today ? '已逾期 · ' : ''}${shortDay(item.due)}` : '未设日期'} · {owner(item.owner)}{item.sync?.readOnly ? ' · 来源只读' : ''}</Text>{dependencyState.get(item.id)!.message&&<Text variant="bodySmall" style={muted}>{dependencyState.get(item.id)!.message}</Text>}</View>
        {!item.sync && <Button contentStyle={styles.primaryContent} compact accessibilityLabel={`编辑待办：${item.title}`} disabled={!!(busy || props.pendingId)}
          onPress={() => { if (!busy && !props.pendingId) props.onEdit('tasks', item); }}>编辑</Button>}
      </View>) : <EmptyState title="到期待办已处理完" action={<Button contentStyle={styles.primaryContent} onPress={() => props.onEdit('tasks')}>添加待办</Button>} />}
      {tasks.length > 4 && <Text variant="bodySmall" style={muted}>还有 {tasks.length - 4} 项到期或未排期待办</Text>}
      {!!error && <Text accessibilityRole="alert" style={{ color: theme.colors.error }}>{error}</Text>}
    </SectionCard>,
    shopping: <SectionCard style={[styles.bento, bento]} title="需要添置" action={<Button contentStyle={styles.primaryContent} compact onPress={() => props.onNavigate('shopping')}>采购清单</Button>}>
      {shopping.length ? shopping.slice(0, 3).map(item => <View key={item.id} style={[styles.task, { paddingVertical: density.rowPadding }]}><View style={styles.flex}>
        <Text variant="titleSmall">{item.title}</Text><Text variant="bodySmall" style={muted}>{item.quantity || '未填数量'}</Text></View>
        <Button contentStyle={styles.primaryContent} compact onPress={() => props.onEdit('shopping', item)}>查看</Button></View>)
        : <EmptyState title="暂时没有待采购的物品" action={<Button contentStyle={styles.primaryContent} onPress={() => props.onEdit('shopping')}>添加采购</Button>} />}
      {shopping.length > 3 && <Text variant="bodySmall" style={muted}>还有 {shopping.length - 3} 件待采购</Text>}
    </SectionCard>,
    trips: <SectionCard style={[styles.bento, bento]} title="下一趟旅行" action={<Button contentStyle={styles.primaryContent} compact onPress={() => props.onNavigate('trips')}>全部旅行</Button>}>
      {trip ? <View style={{ gap: density.tripGap }}><Text variant="titleMedium">{trip.title}</Text><Text variant="bodyMedium" style={muted}>{shortDay(trip.start)}—{shortDay(trip.end)}{trip.destination ? ` · ${trip.destination}` : ''}</Text>
        <Button contentStyle={styles.primaryContent} mode="outlined" onPress={() => props.onEdit('trips', trip)}>查看行程</Button></View>
        : <EmptyState title="还没有下一趟旅行" action={<Button contentStyle={styles.primaryContent} onPress={() => props.onEdit('trips')}>计划旅行</Button>} />}
    </SectionCard>,
  };
  const order = [...new Set([...props.layout.order.filter(key => cardKeys.includes(key)), ...cardKeys])].filter(key => !props.layout.hidden.includes(key));
  return <View testID="home-content" style={{ gap: wide ? density.screenGap : density.screenGapNarrow }}>
    <View style={[styles.hero, { gap: wide ? density.heroGap : density.heroGapNarrow }, wide && { paddingTop: density.heroTop, paddingBottom: density.heroBottom }]}>
      <View style={styles.heroCopy}>
        <Text variant="bodySmall" style={muted}>{shortDay(today)} · 我们的每一天</Text>
        <Text accessibilityRole="header" style={[styles.title, wide && styles.titleWide]}>{`${props.user.name}，欢迎回家`}</Text>
        {wide && <Text variant="bodyMedium" style={muted}>今天的安排、共同的计划，一起照顾好。</Text>}
      </View>
      <View style={styles.heroActions}>
        <Button contentStyle={styles.primaryContent} mode="outlined" accessibilityLabel="安排首页" disabled={!!busy || !!props.pendingId} onPress={() => setLayoutOpen(true)}>安排首页</Button>
        <Button contentStyle={styles.primaryContent} icon="plus" accessibilityLabel="添加待办" mode="contained" style={styles.pill} onPress={() => props.onEdit('tasks')}>添加待办</Button>
      </View>
    </View>
    <View style={[wide && styles.overviewWide, { gap: wide ? density.overviewGap : density.overviewGapNarrow }]}>
      <View style={styles.range}><RangeControls props={props} /></View>
      <View style={[styles.metrics, wide && styles.metricsWide]}>
        <Text variant="bodySmall" style={muted}><Text style={styles.metricNumber}>{summary.total}</Text> 项安排</Text>
        <Text variant="bodySmall" style={muted}><Text style={styles.metricNumber}>{due}</Text> 项到期待办{overdue ? ` · ${overdue} 项逾期` : ''}</Text>
        <Text variant="bodySmall" style={muted}><Text style={styles.metricNumber}>{shopping.length}</Text> 件待采购</Text>
      </View>
    </View>
    <View testID="home-card-grid" style={[styles.grid, wide && styles.gridWide, { gap: density.gridGap }]}>{order.map((key, index) => <View key={key} style={[styles.card, wide ? { flexBasis: index === 0 ? '58%' : index === 1 ? '36%' : '30%' } : styles.cardNarrow]}>{cards[key]}</View>)}</View>
  </View>;
}

const styles = StyleSheet.create({
  hero: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', paddingVertical: 4 },
  heroCopy: { flexGrow: 1, flexShrink: 1, flexBasis: 220, minWidth: 0, gap: 8 },
  title: { fontSize: 28, lineHeight: 34, fontWeight: '600', letterSpacing: -0.7 },
  titleWide: { fontSize: 38, lineHeight: 44, letterSpacing: -1 },
  pill: { borderRadius: 999, alignSelf: 'center' }, primaryContent: { minHeight: 44 },
  heroActions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, alignItems: 'center' },
  overviewWide: { flexDirection: 'row', alignItems: 'center' },
  range: { flexGrow: 1, flexShrink: 1, maxWidth: 680 },
  metrics: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 }, metricsWide: { maxWidth: 340, justifyContent: 'flex-end', columnGap: 20, rowGap: 8 },
  metricNumber: { fontSize: 18, lineHeight: 24, fontWeight: '600' },
  grid: { flexDirection: 'row', flexWrap: 'wrap' }, gridWide: { alignItems: 'flex-start' }, card: { minWidth: 0, flexGrow: 1, flexShrink: 1 }, cardNarrow: { width: '100%' }, bento: { flex: 1 },
  financeUnconfirmed: { gap: 16 }, financeAction: { alignSelf: 'flex-start' },
  flex: { flex: 1, minWidth: 0, gap: 4 }, week: { marginTop: 12 }, money: { gap: 8 },
  balance: { fontSize: 32, lineHeight: 40, fontWeight: '600', letterSpacing: -0.8 }, balanceWide: { fontSize: 40, lineHeight: 48, fontWeight: '600', letterSpacing: -1.2 },
  moneyDetails: { flexDirection: 'row', gap: 16 },
  task: { flexDirection: 'row', alignItems: 'center', gap: 8 }, taskCheckbox: { margin: 0, minWidth: 44, minHeight: 44 },
});
