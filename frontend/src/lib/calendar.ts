import type { CalendarEvent, CalendarMode } from './types';

export const DAY = 86_400_000;
export const weekNames = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
const dateFormat = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' });
const clockFormat = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });

export function dayKey(value: string | number | Date = Date.now()): string { return dateFormat.format(new Date(value)); }
export function dayStart(day: string): number { return Date.parse(day + 'T00:00:00+08:00'); }
export function shiftDay(day: string, offset: number): string { return dayKey(dayStart(day) + offset * DAY); }
export function weekday(day: string): number { return new Date(day + 'T12:00:00Z').getUTCDay(); }
export function shortDay(day: string): string { return `${Number(day.slice(5, 7))}/${Number(day.slice(8, 10))}`; }
export function rangeDays(mode: CalendarMode, anchor = dayKey()): string[] {
  const first = mode === 'week' ? shiftDay(anchor, -((weekday(anchor) + 6) % 7)) : mode === 'around' ? shiftDay(anchor, -3) : anchor;
  return Array.from({ length: mode === 'today' ? 1 : 7 }, (_, i) => shiftDay(first, i));
}
export function bounds(event: CalendarEvent): { start: number; end: number } {
  return { start: event.allDay ? dayStart(event.start.slice(0, 10)) : Date.parse(event.start),
    end: event.allDay ? dayStart(event.end.slice(0, 10)) : Date.parse(event.end) };
}
export function overlapsDay(event: CalendarEvent, day: string): boolean {
  const { start, end } = bounds(event), lower = dayStart(day), upper = lower + DAY;
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return false;
  if (start === end) return !event.allDay && start >= lower && start < upper;
  return start < upper && end > lower;
}
export function eventsForDay(events: CalendarEvent[], day: string, focus = ''): CalendarEvent[] {
  return events.filter(event => overlapsDay(event, day)).sort((a, b) => Number(!!b.allDay) - Number(!!a.allDay) ||
    Math.max(bounds(a).start, dayStart(day)) - Math.max(bounds(b).start, dayStart(day)) ||
    Number(b.owner === focus) - Number(a.owner === focus) || a.id.localeCompare(b.id));
}
export function unionMinutes(intervals: [number, number][]): number {
  const ordered = intervals.filter(([a, b]) => Number.isFinite(a) && Number.isFinite(b) && b > a).sort((a, b) => a[0] - b[0]);
  let total = 0, start: number | undefined, end = 0;
  for (const [a, b] of ordered) {
    if (start === undefined) { start = a; end = b; }
    else if (a <= end) end = Math.max(end, b);
    else { total += end - start; start = a; end = b; }
  }
  return (total + (start === undefined ? 0 : end - start)) / 60_000;
}
export function daySummary(events: CalendarEvent[], day: string, focus: string) {
  const visible = eventsForDay(events, day, focus), relevant = visible.filter(event => event.owner === focus || event.owner === 'shared');
  const lower = dayStart(day), upper = lower + DAY;
  return { day, events: visible, total: visible.length, allDay: relevant.filter(event => event.allDay).length,
    busyMinutes: unionMinutes(relevant.filter(event => !event.allDay).map(event => {
      const value = bounds(event); return [Math.max(lower, value.start), Math.min(upper, value.end)];
    })) };
}
export function rangeSummary(events: CalendarEvent[], days: string[], focus: string) {
  const daily = days.map(day => daySummary(events, day, focus));
  const selected = events.filter(event => days.some(day => overlapsDay(event, day)));
  return { days: daily, total: selected.length, busyMinutes: daily.reduce((n, day) => n + day.busyMinutes, 0),
    allDay: selected.filter(event => event.allDay && (event.owner === focus || event.owner === 'shared')).length };
}
export function timeLabel(event: CalendarEvent, day: string): string {
  if (event.allDay) return '全天';
  const { start, end } = bounds(event), lower = dayStart(day), upper = lower + DAY;
  if (!Number.isFinite(start) || !Number.isFinite(end)) return '时间待核对';
  const begin = start < lower ? '00:00' : clockFormat.format(new Date(start));
  return begin + (start === end ? '' : '–' + (end >= upper ? '24:00' : clockFormat.format(new Date(end))));
}
export function duration(minutes: number): string { return minutes < 60 ? `${Number(minutes.toFixed(1))} 分钟` : `${Number((minutes / 60).toFixed(1))} 小时`; }
export function isLocalEvent(event: CalendarEvent): boolean { return !event.sync; }

export type CalendarConflictSpan = { day: string; start: number; end: number; minutes: number };
export type CalendarConflict = {
  key: string;
  first: Readonly<CalendarEvent>;
  second: Readonly<CalendarEvent>;
  overlaps: CalendarConflictSpan[];
  minutes: number;
};

function validCalendarDay(day: string): boolean {
  const start = dayStart(day);
  return /^\d{4}-\d{2}-\d{2}$/.test(day) && Number.isFinite(start) && dayKey(start) === day;
}

/** Derive pairs only from the caller's current authorized state; never a write credential. */
export function calendarConflicts(events: readonly CalendarEvent[], days: readonly string[], focus: string): CalendarConflict[] {
  const selected = [...new Set(days)].filter(validCalendarDay).sort().map(day => ({ day, start: dayStart(day) }));
  if (!selected.length) return [];
  const firstDay = selected[0].start, lastDayEnd = selected[selected.length - 1].start + DAY;
  // State contains one current row per ID. Repeated references must not duplicate a pair.
  const seen = new Set<string>();
  const timed: { event: CalendarEvent; start: number; end: number }[] = [];
  for (const event of events) {
    if (seen.has(event.id)) continue;
    seen.add(event.id);
    if (event.allDay || (event.owner !== focus && event.owner !== 'shared')) continue;
    const value = bounds(event);
    if (!Number.isFinite(value.start) || !Number.isFinite(value.end) || value.end <= value.start ||
      !validCalendarDay(event.start.slice(0, 10)) || !validCalendarDay(event.end.slice(0, 10)) ||
      value.start >= lastDayEnd || value.end <= firstDay) continue;
    timed.push({ event, ...value });
  }
  timed.sort((a, b) => a.start - b.start || (a.event.id < b.event.id ? -1 : a.event.id > b.event.id ? 1 : 0));
  const result: CalendarConflict[] = [];
  for (let i = 0; i < timed.length; i++) {
    const a = timed[i];
    for (let j = i + 1; j < timed.length; j++) {
      const b = timed[j];
      if (b.start >= a.end) break;
      const start = Math.max(a.start, b.start), end = Math.min(a.end, b.end);
      const overlaps: CalendarConflictSpan[] = [];
      for (const day of selected) {
        const clippedStart = Math.max(start, day.start), clippedEnd = Math.min(end, day.start + DAY);
        if (clippedEnd > clippedStart) overlaps.push({ day: day.day, start: clippedStart, end: clippedEnd, minutes: (clippedEnd - clippedStart) / 60_000 });
      }
      if (!overlaps.length) continue;
      const [first, second] = a.event.id < b.event.id ? [a.event, b.event] : [b.event, a.event];
      result.push({ key: JSON.stringify([first.id, second.id]), first, second, overlaps,
        minutes: overlaps.reduce((total, span) => total + span.minutes, 0) });
    }
  }
  return result.sort((a, b) => a.overlaps[0].start - b.overlaps[0].start || (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
}
