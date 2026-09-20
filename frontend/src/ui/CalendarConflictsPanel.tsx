import React, { useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { Button, Text, TouchableRipple, useTheme } from 'react-native-paper';
import type { CalendarEvent, ScreenProps } from '../lib/types';
import { bounds, DAY, dayKey, dayStart, duration, isLocalEvent, shortDay, type CalendarConflict } from '../lib/calendar';
import { SectionCard } from './components';
import { useDisplayDensity } from './theme';

const clock = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
const PAGE_SIZE = 3;

function eventTime(event: Readonly<CalendarEvent>): string {
  const { start, end } = bounds(event);
  if (!Number.isFinite(start) || !Number.isFinite(end)) return '时间待核对';
  return `${dayKey(start)} ${clock.format(start)} — ${dayKey(end)} ${clock.format(end)}`;
}

export default function CalendarConflictsPanel({ conflicts, props, focusName }: {
  conflicts: readonly CalendarConflict[]; props: ScreenProps; focusName: string;
}) {
  const theme = useTheme(), density = useDisplayDensity();
  const [expanded, setExpanded] = useState<string | null>(null), [shown, setShown] = useState(PAGE_SIZE);
  useEffect(() => { if (expanded && !conflicts.some(group => group.key === expanded)) setExpanded(null); }, [conflicts, expanded]);
  if (props.user.role !== 'member' || !conflicts.length) return null;
  const muted = { color: theme.colors.onSurfaceVariant };
  const owner = (id: string) => id === 'shared' ? '共同' : props.state.people.find(person => person.id === id)?.name || '成员';
  function edit(event: Readonly<CalendarEvent>) {
    // Resolve the original record again; never turn a clipped overlap into a new event.
    const current = props.state.events.find(item => item.id === event.id);
    if (!props.pendingId && props.user.role === 'member' && isLocalEvent(event) && current && isLocalEvent(current)
      && (current.owner === props.focus || current.owner === 'shared')) props.onEdit('events', current);
  }
  return <View testID="calendar-conflicts">
    <SectionCard title={`时间重叠 · ${conflicts.length} 组`}>
      <Text variant="bodySmall" style={muted}>当前范围 · {focusName} + 共同。每两个安排计一组，跨日不重复计组；仅提示时间交叠，是否需要调整由你判断。</Text>
      {conflicts.slice(0, shown).map((group, index) => {
        const open = expanded === group.key;
        return <View key={group.key} testID={`calendar-conflict-${index + 1}`} style={[styles.group, { borderTopColor: theme.colors.outlineVariant }]}>
          <TouchableRipple onPress={() => setExpanded(open ? null : group.key)} accessibilityRole="button"
            accessibilityLabel={`${open ? '收起' : '展开'}第 ${index + 1} 组时间重叠，${shortDay(group.overlaps[0].day)}起，${duration(group.minutes)}`}
            accessibilityHint="查看两个安排的完整标题、时间和负责人" accessibilityState={{ expanded: open }}>
            <View style={[styles.heading, { paddingVertical: density.rowPadding }]}>
              <View style={styles.copy}>
                <Text variant="labelLarge">{shortDay(group.overlaps[0].day)}{group.overlaps.length > 1 ? ` 等 ${group.overlaps.length} 天` : ''} · 重叠 {duration(group.minutes)}</Text>
                <Text variant="bodyMedium" numberOfLines={2}>{group.first.title} / {group.second.title}</Text>
              </View>
              <MaterialCommunityIcons name={open ? 'chevron-up' : 'chevron-down'} size={24} color={theme.colors.onSurfaceVariant}
                accessibilityElementsHidden importantForAccessibility="no" />
            </View>
          </TouchableRipple>
          {open && <View style={styles.details}>
            <View style={styles.spans}>{group.overlaps.map(span => <Text key={span.day} variant="bodySmall" style={muted}>
              {span.day} · {clock.format(span.start)}–{span.end >= dayStart(span.day) + DAY ? '24:00' : clock.format(span.end)} · {duration(span.minutes)}
            </Text>)}</View>
            {[group.first, group.second].map(event => <View key={event.id} style={[styles.event, { backgroundColor: theme.colors.surface }]}>
              <Text variant="titleSmall">{event.title}</Text>
              <Text variant="bodySmall" style={muted}>{eventTime(event)}</Text>
              <Text variant="bodySmall" style={muted}>负责人：{owner(event.owner)}{event.location ? ` · ${event.location}` : ''}</Text>
              {isLocalEvent(event) ? <Button compact mode="outlined" style={styles.action} contentStyle={styles.buttonContent}
                disabled={!!props.pendingId} accessibilityLabel={`${event.travelTiming ? '在旅行中调整' : '调整安排'}：${event.title}`}
                onPress={() => edit(event)}>{event.travelTiming ? '在旅行中调整' : '调整安排'}</Button>
                : <Text variant="bodySmall" style={muted}>同步日程 · 只读，请在原应用调整。</Text>}
            </View>)}
          </View>}
        </View>;
      })}
      {conflicts.length > shown && <Button contentStyle={styles.buttonContent} onPress={() => setShown(value => value + PAGE_SIZE)}>
        再显示 {Math.min(PAGE_SIZE, conflicts.length - shown)} 组（还有 {conflicts.length - shown} 组）
      </Button>}
    </SectionCard>
  </View>;
}

const styles = StyleSheet.create({
  group: { marginTop: 12, borderTopWidth: StyleSheet.hairlineWidth },
  heading: { minHeight: 44, flexDirection: 'row', alignItems: 'center', gap: 12 },
  copy: { flex: 1, minWidth: 0, gap: 4 }, details: { gap: 12, paddingBottom: 8 }, spans: { gap: 4 },
  event: { padding: 12, gap: 8, borderRadius: 12, minWidth: 0 },
  action: { alignSelf: 'flex-start', maxWidth: '100%', borderRadius: 8 }, buttonContent: { minHeight: 44 },
});
