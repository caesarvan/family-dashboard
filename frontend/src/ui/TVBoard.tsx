import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { ScrollView, StyleSheet, View, useWindowDimensions, type LayoutChangeEvent } from 'react-native';
import { Card, Text } from 'react-native-paper';
import type { CalendarMode, FamilyState, ListItem } from '../lib/types';
import { deviceCardNames, type DeviceCard, type DeviceLayout } from '../lib/devices';
import { dayKey, duration, rangeDays, rangeSummary, shortDay, timeLabel, weekday, weekNames } from '../lib/calendar';
import { expoTokens } from './theme';
import { TV_PAGE_MS, tvBoardRows, tvCalendarPages, tvCountdown, tvMoney, tvPage, tvPending,
  tvReadDuration, tvScrollOffset, tvUpcoming, type TVDayPage } from './TVBoard.model';

export type TVBoardProps = {
  state: FamilyState;
  focus: string;
  mode: CalendarMode;
  layout: DeviceLayout;
  /** Controller clock in milliseconds. Identity/visibility/auth belong to that controller. */
  now: number;
};

const palettes = {
  light: { background: expoTokens.canvas, card: expoTokens.canvasSoft, ink: expoTokens.ink,
    muted: expoTokens.body, soft: expoTokens.strong, accent: '#000000', edge: expoTokens.outline, danger: '#b4232a' },
  forest: { background: '#101d1c', card: '#172725', ink: '#f4f1e8', muted: '#a6bab0',
    soft: '#233931', accent: '#b4d9af', edge: '#30473d', danger: '#f2aba0' },
  ocean: { background: '#0e2030', card: '#152e40', ink: '#eff6f4', muted: '#a6c2cf',
    soft: '#203e53', accent: '#8bcfce', edge: '#2a4b60', danger: '#f2ada6' },
} as const;
type Palette = typeof palettes[keyof typeof palettes];
type Display = { colors: Palette; scale: number; font: number; compact: boolean };
const clock = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
const modeName = { today: '今日', week: '本周', around: '前后 3 天' };
const ReadingContext = createContext<(key: string, viewport: number, content: number) => void>(() => {});

function Copy({ children, display, muted = false, size, strong = false, danger = false }: {
  children: ReactNode; display: Display; muted?: boolean; size?: number; strong?: boolean; danger?: boolean;
}) {
  const fontSize = size ?? display.font;
  return <Text style={{ color: danger ? display.colors.danger : muted ? display.colors.muted : display.colors.ink,
    fontSize, lineHeight: Math.ceil(fontSize * 1.4), fontWeight: strong ? '600' : '400', flexShrink: 1 }}>{children}</Text>;
}

/** Only the visible viewport is clipped. Every pixel of long content is visited without touch. */
function ReadingPane({ children, phase, resetKey, display, label }: {
  children: ReactNode; phase: number; resetKey: string; display: Display; label: string;
}) {
  const scroll = useRef<ScrollView>(null);
  const report = useContext(ReadingContext);
  const [height, setHeight] = useState(0), [content, setContent] = useState(0);
  const extra = Math.max(0, content - height), position = tvScrollOffset(height, content, phase);
  useEffect(() => {
    report(resetKey, height, content);
    return () => report(resetKey, 0, 0);
  }, [report, resetKey, height, content]);
  useEffect(() => { scroll.current?.scrollTo({ y: Math.round(position), animated: false }); }, [position, resetKey]);
  return <View style={styles.pane}>
    <ScrollView ref={scroll} style={styles.pane} contentContainerStyle={{ gap: 16 * display.scale, paddingBottom: 2 }}
      onLayout={event => setHeight(event.nativeEvent.layout.height)} onContentSizeChange={(_, value) => setContent(value)}
      scrollEnabled={false} showsVerticalScrollIndicator={false} accessibilityLabel={label}>
      {children}
    </ScrollView>
    {extra > 1 ? <Copy display={display} muted size={18 * display.scale}>长内容自动翻阅</Copy> : null}
  </View>;
}

function Meter({ value, display, label }: { value: number; display: Display; label: string }) {
  const fraction = Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
  return <View accessibilityRole="progressbar" accessibilityLabel={label}
    accessibilityValue={{ min: 0, max: 100, now: Math.round(fraction * 100) }}
    style={{ height: 7 * display.scale, borderRadius: 99, backgroundColor: display.colors.soft, overflow: 'hidden' }}>
    <View style={{ width: `${fraction * 100}%`, height: '100%', backgroundColor: display.colors.accent }} />
  </View>;
}

function ownerName(state: FamilyState, id: string): string {
  return id === 'shared' ? '共同' : state.people.find(person => person.id === id)?.name || '家庭成员';
}

function CalendarDay({ day, state, display, phase, pageKey }: {
  day: TVDayPage; state: FamilyState; display: Display; phase: number; pageKey: string;
}) {
  return <View style={[styles.column, { gap: 12 * display.scale }]} testID={`tv-day-${day.day}`}>
    <View>
      <Copy display={display} strong>{shortDay(day.day)} {weekNames[weekday(day.day)]}</Copy>
      <Copy display={display} muted size={18 * display.scale}>{day.total} 项{day.pages > 1 ? ` · ${day.page}/${day.pages} 页` : ''}</Copy>
    </View>
    <ReadingPane phase={phase} resetKey={`${pageKey}:${day.day}:${day.page}`} display={display} label={`${day.day} 日程详情`}>
      {day.events.length ? day.events.map(event => <View key={event.id} testID={`tv-event-${event.id}`} style={{ gap: 5 * display.scale }}>
        <Copy display={display} muted size={20 * display.scale}>{timeLabel(event, day.day)} · {ownerName(state, event.owner)}</Copy>
        <Copy display={display} strong>{event.title}</Copy>
        {event.location ? <Copy display={display} muted size={20 * display.scale}>{event.location}</Copy> : null}
      </View>) : <Copy display={display} muted>暂无安排</Copy>}
    </ReadingPane>
  </View>;
}

function Calendar({ state, focus, mode, now, cycle, phase, display, width, height }: TVBoardProps & {
  cycle: number; phase: number; display: Display; width: number; height: number;
}) {
  const today = dayKey(now), days = useMemo(() => rangeDays(mode, today), [mode, today]);
  const summary = useMemo(() => rangeSummary(state.events, days, focus), [state.events, days, focus]);
  const columns = mode === 'today' ? 1 : Math.max(1, Math.min(7, Math.floor(width / (280 * display.scale))));
  const capacity = Math.max(1, Math.min(display.compact ? 4 : 3, Math.floor((height - (mode === 'today' ? 140 : 240) * display.scale) / (150 * display.scale))));
  const minute = Math.floor(now / 60_000) * 60_000;
  const pages = useMemo(() => tvCalendarPages(state.events, days, focus, minute, columns, capacity),
    [state.events, days, focus, minute, columns, capacity]);
  const page = pages[cycle % pages.length], peak = Math.max(60, ...summary.days.map(day => day.busyMinutes));
  return <>
    <Copy display={display} muted size={20 * display.scale}>
      {modeName[mode]} · {summary.total} 项安排 · {ownerName(state, focus)}{focus === 'shared' ? '' : '与共同'} {duration(summary.busyMinutes)}
    </Copy>
    {mode !== 'today' ? <View style={[styles.row, { gap: 6 * display.scale }]} testID="tv-week-overview">
      {summary.days.map(day => <View key={day.day} style={{ flex: 1, minWidth: 0, gap: 4 * display.scale }}>
        <Copy display={display} strong={day.day === today} size={18 * display.scale}>{shortDay(day.day)}</Copy>
        <Meter display={display} value={day.busyMinutes / peak} label={`${day.day} ${day.total} 项，${duration(day.busyMinutes)}`} />
        <Copy display={display} muted size={16 * display.scale}>{day.total}项{day.allDay ? ` · 全天${day.allDay}` : ''}</Copy>
      </View>)}
    </View> : null}
    <View style={[styles.row, styles.pane, { gap: 20 * display.scale }]}>
      {page.map(day => <CalendarDay key={day.day} day={day} state={state} display={display} phase={phase} pageKey={String(cycle)} />)}
    </View>
    <Copy display={display} muted size={18 * display.scale}>
      {pages.length > 1 ? `第 ${cycle % pages.length + 1}/${pages.length} 页 · 自动轮换 · ` : ''}时长合并重叠安排，全天另计
    </Copy>
  </>;
}

function Money({ state, display, phase }: { state: FamilyState; display: Display; phase: number }) {
  const finance = state.finance, confirmed = typeof finance.confirmedAt === 'string' && Number.isFinite(Date.parse(finance.confirmedAt));
  const fields = [['周转目标', finance.reserveTarget], ['日常预算', finance.livingBudget],
    ['旅行准备金', finance.travelSaved], ['长期共同储蓄', finance.longterm]] as const;
  return <ReadingPane phase={phase} resetKey={`finance:${finance.revision}`} display={display} label="共同资金详情">
    {confirmed ? <>
      <View><Copy display={display} muted>荷包余额</Copy><Copy display={display} strong size={40 * display.scale}>{tvMoney(finance.wallet)}</Copy></View>
      <View style={{ gap: 8 * display.scale }}>
        <Copy display={display}>本月日常支出 {tvMoney(finance.livingSpent)}</Copy>
        {Number.isSafeInteger(finance.livingSpent) && Number.isSafeInteger(finance.livingBudget) && finance.livingBudget > 0
          ? <><Meter display={display} value={finance.livingSpent / finance.livingBudget} label="日常预算使用比例" />
            {finance.livingSpent > finance.livingBudget ? <Copy display={display} danger>已超过本月日常预算</Copy> : null}</> : null}
      </View>
      {fields.map(([label, value]) => <View key={label}><Copy display={display} muted size={20 * display.scale}>{label}</Copy><Copy display={display} strong>{tvMoney(value)}</Copy></View>)}
      <Copy display={display} muted size={18 * display.scale}>手动核对 · {Number.isFinite(Date.parse(finance.confirmedAt!)) ? dayKey(finance.confirmedAt!) : '核对时间待确认'}</Copy>
    </> : <>
      <Copy display={display} strong>共同资金待核对</Copy>
      <Copy display={display} muted>在手机或电脑核对荷包余额与本月支出后，这里会显示共同资金与预算进度。</Copy>
    </>}
  </ReadingPane>;
}

function List({ kind, state, focus, now, cycle, phase, display, height }: {
  kind: 'tasks' | 'shopping'; state: FamilyState; focus: string; now: number; cycle: number; phase: number; display: Display; height: number;
}) {
  const items = useMemo(() => tvPending(state[kind], focus), [state, kind, focus]);
  const capacity = Math.max(1, Math.min(display.compact ? 5 : 4, Math.floor((height - 120 * display.scale) / (100 * display.scale))));
  const page = tvPage(items, capacity, cycle), today = dayKey(now);
  const detail = (item: ListItem) => [ownerName(state, item.owner), kind === 'shopping' ? item.quantity : '',
    item.due ? `${item.due < today ? '已逾期 · ' : ''}${item.due}` : ''].filter(Boolean).join(' · ');
  return <>
    <Copy display={display} muted size={20 * display.scale}>{items.length} 项待完成</Copy>
    <ReadingPane phase={phase} resetKey={`${kind}:${page.page}`} display={display} label={kind === 'tasks' ? '待办详情' : '采购详情'}>
      {page.items.length ? page.items.map(item => <View key={item.id} testID={`tv-${kind}-${item.id}`} style={{ gap: 5 * display.scale }}>
        <Copy display={display} strong>{item.title}</Copy>
        <Copy display={display} muted size={20 * display.scale}>{detail(item)}</Copy>
        {kind === 'shopping' ? <Copy display={display} muted size={20 * display.scale}>预算 {tvMoney(item.budget)}</Copy> : null}
      </View>) : <>
        <Copy display={display} strong>{kind === 'tasks' ? '眼下的事，都安排好了' : '暂时没有待采购物品'}</Copy>
        <Copy display={display} muted>需要时在手机或电脑添加，这里会自动更新。</Copy>
      </>}
    </ReadingPane>
    {page.pages > 1 ? <Copy display={display} muted size={18 * display.scale}>第 {page.page}/{page.pages} 页 · 自动轮换</Copy> : null}
  </>;
}

function Travel({ state, now, cycle, phase, display }: {
  state: FamilyState; now: number; cycle: number; phase: number; display: Display;
}) {
  const today = dayKey(now), trips = useMemo(() => tvUpcoming(state.trips, today), [state.trips, today]);
  const page = tvPage(trips, 1, cycle), trip = page.items[0];
  const tasks = trip ? state.tasks.filter(task => task.tripId === trip.id) : [], done = tasks.filter(task => task.done).length;
  return <>
    <ReadingPane phase={phase} resetKey={`trip:${trip?.id || 'empty'}`} display={display} label="旅行详情">
      {trip ? <>
        <Copy display={display} strong size={30 * display.scale}>{trip.title}</Copy>
        <Copy display={display} muted>{trip.start} — {trip.end}</Copy>
        {trip.destination ? <Copy display={display}>{trip.destination}</Copy> : null}
        <Copy display={display} strong>{tvCountdown(trip.start, today)}</Copy>
        <Copy display={display} muted>准备进度 {done} / {tasks.length}</Copy>
        <Meter display={display} value={tasks.length ? done / tasks.length : 0} label="旅行准备进度" />
        <Copy display={display} muted>{tasks.find(task => !task.done)?.title || (tasks.length ? '准备就绪，期待出发' : '在手机添加准备事项')}</Copy>
      </> : <><Copy display={display} strong>下一站，去哪里？</Copy><Copy display={display} muted>计划一次周末出走，或一段期待已久的旅程。</Copy></>}
    </ReadingPane>
    {page.pages > 1 ? <Copy display={display} muted size={18 * display.scale}>第 {page.page}/{page.pages} 趟 · 自动轮换</Copy> : null}
  </>;
}

function Tile({ name, props, display }: {
  name: DeviceCard; props: TVBoardProps; display: Display;
}) {
  const [size, setSize] = useState({ width: 700, height: 380 });
  const padding = (display.compact ? 20 : 24) * display.scale;
  const [cycle, setCycle] = useState(0), startedAt = useRef(props.now);
  const readings = useRef(new Map<string, number>()), duration = useRef(TV_PAGE_MS);
  const phase = Math.max(0, props.now - startedAt.current);
  const report = useCallback((key: string, viewport: number, content: number) => {
    if (viewport > 0) readings.current.set(key, tvReadDuration(viewport, content));
    else readings.current.delete(key);
    duration.current = Math.max(TV_PAGE_MS, ...readings.current.values());
  }, []);
  useEffect(() => {
    // Refreshes and each clock tick preserve the current page. Long measured text
    // gets enough still reading positions before this card advances independently.
    if (props.now < startedAt.current || props.now - startedAt.current >= duration.current) {
      startedAt.current = props.now; setCycle(value => value + 1);
    }
  }, [props.now]);
  const measured = (event: LayoutChangeEvent) => {
    const { width, height } = event.nativeEvent.layout;
    setSize(old => old.width === width && old.height === height ? old : { width, height });
  };
  return <ReadingContext.Provider value={report}><Card mode="contained" contentStyle={styles.pane} style={[styles.tile, { backgroundColor: display.colors.card,
    borderRadius: expoTokens.cardRadius * display.scale }]} testID={`tv-card-${name}`}>
    <Card.Content onLayout={measured} style={[styles.tileContent, { paddingHorizontal: padding, paddingVertical: padding, gap: (display.compact ? 10 : 14) * display.scale }]}>
      <Text accessibilityRole="header" style={{ color: display.colors.ink, fontSize: 32 * display.scale,
        lineHeight: 42 * display.scale, fontWeight: '600' }}>{name === 'trips' ? '接下来的旅行' : deviceCardNames[name]}</Text>
      {name === 'calendar' ? <Calendar {...props} {...size} width={Math.max(1, size.width - 2 * padding)} display={display} cycle={cycle} phase={phase} />
        : name === 'finance' ? <Money state={props.state} display={display} phase={phase} />
          : name === 'tasks' || name === 'shopping' ? <List kind={name} {...props} height={size.height} display={display} cycle={cycle} phase={phase} />
            : <Travel {...props} display={display} cycle={cycle} phase={phase} />}
    </Card.Content>
  </Card></ReadingContext.Provider>;
}

/** Read-only projection. Controller owns auth, filtered DTO validation and clock suspension. */
export default function TVBoard(props: TVBoardProps) {
  const { state, focus, mode, layout, now } = props, window = useWindowDimensions();
  const [size, setSize] = useState({ width: window.width, height: window.height });
  const scale = Math.max(0.65, Math.min(size.width / 1920, size.height / 1080));
  const display: Display = { colors: palettes[layout.theme], scale, compact: layout.density === 'compact',
    font: (layout.density === 'compact' ? 22 : 26) * scale };
  const rows = tvBoardRows(layout), today = dayKey(now);
  return <View testID="expo-tv-board" onLayout={event => {
    const { width, height } = event.nativeEvent.layout;
    setSize(old => old.width === width && old.height === height ? old : { width, height });
  }} style={[styles.board, { backgroundColor: display.colors.background, padding: 28 * scale, gap: 22 * scale }]}>
    <View style={[styles.row, { justifyContent: 'space-between', alignItems: 'center', gap: 24 * scale }]}>
      <View style={{ flex: 1, minWidth: 0 }}>
        <Text accessibilityRole="header" style={{ color: display.colors.ink, fontSize: 38 * scale, lineHeight: 48 * scale, fontWeight: '600' }}>家庭看板</Text>
        <Copy display={display} muted size={20 * scale}>{ownerName(state, focus)} · {modeName[mode]} · 只读展示</Copy>
      </View>
      <View style={{ alignItems: 'flex-end', flexShrink: 1 }}>
        <Copy display={display} strong size={46 * scale}>{clock.format(new Date(now))}</Copy>
        <Copy display={display} muted size={20 * scale}>{today} {weekNames[weekday(today)]} · 上海时间</Copy>
      </View>
    </View>
    <View style={[styles.pane, { gap: 20 * scale }]}>
      {rows.map((row, index) => <View key={index} style={[styles.row, styles.pane, { gap: 20 * scale }]}>
        {row.map(name => <Tile key={name} name={name} props={props} display={display} />)}
      </View>)}
    </View>
  </View>;
}

const styles = StyleSheet.create({
  board: { flex: 1, minHeight: 0, minWidth: 0, width: '100%', height: '100%' },
  row: { flexDirection: 'row', minWidth: 0 },
  pane: { flex: 1, minHeight: 0, minWidth: 0 },
  column: { flex: 1, minWidth: 0, minHeight: 0 },
  tile: { flex: 1, minWidth: 0, minHeight: 0, overflow: 'hidden' },
  tileContent: { flex: 1, minHeight: 0, minWidth: 0 },
});
