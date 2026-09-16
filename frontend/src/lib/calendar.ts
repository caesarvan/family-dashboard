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
