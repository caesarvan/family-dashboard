import React, { useEffect, useRef, useState } from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';
import { Button, IconButton, ProgressBar, SegmentedButtons, Text, TouchableRipple, useTheme } from 'react-native-paper';
import type { CalendarEvent, CalendarMode, ScreenProps } from '../lib/types';
import { bounds, dayKey, duration, isLocalEvent, rangeDays, rangeSummary, shiftDay, shortDay, timeLabel, weekday, weekNames } from '../lib/calendar';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';
import { SelectionRow } from '../ui/SelectionRow';
import { useDisplayDensity } from '../ui/theme';

export function RangeControls({ props }: { props: ScreenProps }) {
  const density = useDisplayDensity();
  const [pending, setPending] = useState(false), [error, setError] = useState('');
  const identity = `${props.user.householdId}:${props.user.id}:${props.user.auth_version}`;
  const identityRef = useRef(identity); identityRef.current = identity;
  useEffect(() => { setPending(false); setError(''); }, [identity]);
  async function change(mode: string) {
    if (pending || mode === props.mode) return;
    const original = identityRef.current; setPending(true); setError('');
    try { await props.setMode(mode as CalendarMode); }
    catch { if (original === identityRef.current) setError('暂时无法保存显示范围，请重试。'); }
    finally { if (original === identityRef.current) setPending(false); }
  }
  return <View testID="calendar-range-controls" style={[styles.controls, { gap: density.rowPadding }]}>
    <SegmentedButtons value={props.mode} onValueChange={change} density="regular" buttons={[
      { value: 'today', label: '今日', disabled: pending, style: styles.rangeButton, labelStyle: styles.segmentLabel },
      { value: 'week', label: '本周', disabled: pending, style: styles.rangeButton, labelStyle: styles.segmentLabel },
      { value: 'around', label: '前后 3 天', disabled: pending, style: [styles.rangeButton, styles.longRangeButton], labelStyle: styles.segmentLabel }]} />
    <Text variant="labelMedium">日程侧重</Text>
    <View style={styles.people} accessibilityRole="radiogroup" accessibilityLabel="日程侧重">{props.state.people.map(person =>
      <View key={person.id} style={styles.person}><SelectionRow kind="radio" label={person.name}
        checked={props.focus === person.id} onPress={() => props.setFocus(person.id)} /></View>)}</View>
    {!!error && <Text accessibilityRole="alert">{error}</Text>}
  </View>;
}

export function WorkloadStrip({ summary, selected, onSelect }: {
  summary: ReturnType<typeof rangeSummary>; selected?: string; onSelect: (day: string) => void;
}) {
  const theme = useTheme(), density = useDisplayDensity(), peak = Math.max(60, ...summary.days.map(day => day.busyMinutes));
  return <ScrollView horizontal showsHorizontalScrollIndicator={false} accessibilityLabel="所选范围每日安排">
    <View style={styles.week}>{summary.days.map(day => <TouchableRipple key={day.day} onPress={() => onSelect(day.day)}
      accessibilityRole="button" accessibilityState={{ selected: day.day === selected }}
      accessibilityLabel={`${day.day}，${day.total} 项安排，忙碌 ${duration(day.busyMinutes)}${day.allDay ? `，全天 ${day.allDay} 项` : ''}`}
      style={[styles.day, { backgroundColor: day.day === selected ? theme.colors.secondaryContainer : theme.colors.surfaceVariant }]}>
      <View style={[styles.dayInner, { paddingVertical: density.rowPadding }]}><Text variant="labelMedium">{weekNames[weekday(day.day)]}</Text><Text variant="bodySmall">{shortDay(day.day)}</Text>
        <Text variant="titleMedium">{day.total} 项</Text><ProgressBar progress={day.busyMinutes / peak} style={styles.bar} />
        <Text variant="labelSmall">{duration(day.busyMinutes)}</Text>{day.allDay > 0 && <Text variant="labelSmall">全天 {day.allDay} 项</Text>}
      </View></TouchableRipple>)}</View>
  </ScrollView>;
}

export function EventRow({ event, day, props }: { event: CalendarEvent; day: string; props: ScreenProps }) {
  const theme = useTheme(), density = useDisplayDensity(), editable = props.user.role === 'member' && isLocalEvent(event);
  const owner = props.state.people.find(person => person.id === event.owner)?.name || '共同';
  const ongoing = bounds(event).start <= Date.now() && bounds(event).end > Date.now();
  return <TouchableRipple onPress={() => editable && props.onEdit('events', event)} disabled={!editable}
    accessibilityRole={editable ? 'button' : undefined} accessibilityLabel={editable ? `编辑安排：${event.title}` : undefined}>
    <View testID={`calendar-event-${event.id}`} style={[styles.event, { borderBottomColor: theme.colors.outlineVariant, paddingVertical: density.rowPadding }]}>
      <View style={styles.eventTime}><Text variant="labelLarge">{timeLabel(event, day)}</Text>
        <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>{ongoing ? '进行中' : shortDay(day)}</Text></View>
      <View style={styles.eventBody}><Text variant="titleSmall">{event.title}</Text>
        <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>{owner}{event.location ? ` · ${event.location}` : ''}</Text>
        {!editable && <Text variant="labelSmall">同步日程 · 只读</Text>}
      </View>
      {editable && <Text accessibilityElementsHidden style={{ color: theme.colors.onSurfaceVariant }}>›</Text>}
    </View>
  </TouchableRipple>;
}

export default function CalendarScreen(props: ScreenProps) {
  const density = useDisplayDensity();
  const [anchor, setAnchor] = useState<string | undefined>(), [selected, setSelected] = useState(dayKey());
  useEffect(() => { setAnchor(undefined); setSelected(dayKey()); }, [props.mode, props.user.householdId, props.user.id, props.user.auth_version]);
  if (props.user.role !== 'member') return <EmptyState title="请使用成员账户查看日程" />;
  const days = rangeDays(props.mode, anchor), summary = rangeSummary(props.state.events, days, props.focus);
  const chosen = days.includes(selected) ? selected : days.includes(dayKey()) ? dayKey() : days[0];
  const daily = summary.days.find(day => day.day === chosen)!;
  const focusName = props.state.people.find(person => person.id === props.focus)?.name || '所选成员';
  function move(step: number) { const next = shiftDay(anchor || dayKey(), step * (props.mode === 'today' ? 1 : 7)); setAnchor(next); setSelected(next); }
  return <View style={[styles.screen, { gap: density.pageGap }]}>
    <PageHeader title="日程" description="安排看得清，生活从容一点。" action={<Button mode="contained" icon="plus" contentStyle={styles.buttonContent} onPress={() => props.onEdit('events')}>添加安排</Button>} />
    <RangeControls props={props} />
    <View style={styles.navigation}><IconButton icon="chevron-left" size={24} style={styles.iconButton} accessibilityLabel="前一段时间" onPress={() => move(-1)} />
      <Text variant="titleSmall" style={styles.dateRange}>{shortDay(days[0])}{days.length > 1 ? `—${shortDay(days.at(-1)!)}` : ''}</Text>
      <IconButton icon="chevron-right" size={24} style={styles.iconButton} accessibilityLabel="后一段时间" onPress={() => move(1)} />
      <Button compact contentStyle={styles.buttonContent} onPress={() => { setAnchor(undefined); setSelected(dayKey()); }}>回到今天</Button></View>
    <Text variant="bodySmall">{focusName} + 共同 · 忙碌 {duration(summary.busyMinutes)}{summary.allDay ? ` · 全天 ${summary.allDay} 项` : ''}</Text>
    {days.length > 1 && <WorkloadStrip summary={summary} selected={chosen} onSelect={setSelected} />}
    <SectionCard title={`${shortDay(chosen)} ${weekNames[weekday(chosen)]} · ${daily.total} 项安排`}>
      {daily.events.length ? daily.events.map(event => <EventRow key={event.id} event={event} day={chosen} props={props} />)
        : <EmptyState title="这天还没有安排" action={<Button contentStyle={styles.buttonContent} onPress={() => props.onEdit('events')}>添加安排</Button>} />}
    </SectionCard>
    <Text variant="bodySmall">北京时间 · 重叠时段合并统计，全天安排不计入忙碌时长。</Text>
  </View>;
}

const styles = StyleSheet.create({
  screen: { minWidth: 0 }, controls: { minWidth: 0 },
  // Paper's regular segment has 9px inner padding above/below the label.
  // A 26px label box makes the actual TouchableRipple 44px, not just its border.
  segmentLabel: { minHeight: 26, paddingVertical: 3 }, rangeButton: { minWidth: 0 }, longRangeButton: { flex: 1.4 },
  people: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 }, person: { flexBasis: 160, flexGrow: 1, flexShrink: 1, minWidth: 0, maxWidth: 320 },
  navigation: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 4 }, dateRange: { flexShrink: 1, minWidth: 0 },
  iconButton: { margin: 0, minWidth: 44, minHeight: 44 }, buttonContent: { minHeight: 44 },
  week: { flexDirection: 'row', gap: 8 }, day: { width: 84, borderRadius: 12, overflow: 'hidden' },
  dayInner: { paddingHorizontal: 10, gap: 4, minHeight: 112 }, bar: { height: 3, marginVertical: 2, borderRadius: 4 },
  event: { flexDirection: 'row', gap: 12, minHeight: 44, alignItems: 'center', borderBottomWidth: StyleSheet.hairlineWidth },
  eventTime: { width: 86, gap: 4 }, eventBody: { flex: 1, minWidth: 0, gap: 4 },
});
