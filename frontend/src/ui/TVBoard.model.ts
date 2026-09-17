import type { CalendarEvent, ListItem, Trip } from '../lib/types';
import type { DeviceCard, DeviceLayout } from '../lib/devices';
import { bounds, dayKey, dayStart, eventsForDay } from '../lib/calendar';

export const TV_PAGE_MS = 20_000;

/** Order is visual reading order; hidden cards keep their configured position. */
export function tvBoardRows(layout: DeviceLayout): DeviceCard[][] {
  const cards = layout.order.filter(key => !layout.hidden.includes(key));
  if (cards.length <= 2) return cards.length ? [cards] : [];
  const first = cards.length === 3 ? 1 : 2;
  return [cards.slice(0, first), cards.slice(first)];
}

export function tvPage<T>(items: readonly T[], capacity: number, cycle: number) {
  const size = Math.max(1, Math.floor(capacity));
  const pages = Math.max(1, Math.ceil(items.length / size));
  const page = Math.max(0, Math.floor(cycle)) % pages;
  return { items: items.slice(page * size, (page + 1) * size), page: page + 1, pages };
}

export type TVDayPage = { day: string; events: CalendarEvent[]; page: number; pages: number; total: number };

/** Every day and every event appears; focus changes tie ordering, never visibility. */
export function tvCalendarPages(events: CalendarEvent[], days: string[], focus: string,
  now: number, columns: number, capacity: number): TVDayPage[][] {
  const size = Math.max(1, Math.floor(capacity)), width = Math.max(1, Math.floor(columns));
  const today = dayKey(now);
  const daily = days.map(day => {
    let ordered = eventsForDay(events, day, focus);
    if (day === today) {
      const allDay = ordered.filter(event => event.allDay), timed = ordered.filter(event => !event.allDay);
      const first = timed.findIndex(event => bounds(event).end >= now);
      if (first >= 0) ordered = [...allDay, ...timed.slice(first), ...timed.slice(0, first)];
    }
    return { day, events: ordered, total: ordered.length, pages: Math.max(1, Math.ceil(ordered.length / size)) };
  });
  const result: TVDayPage[][] = [];
  for (let start = 0; start < daily.length; start += width) {
    const group = daily.slice(start, start + width), count = Math.max(...group.map(day => day.pages));
    for (let page = 0; page < count; page++) {
      result.push(group.map(day => ({ ...day, ...tvPage(day.events, size, page) }))
        .map(({ items, ...day }) => ({ ...day, events: items })));
    }
  }
  return result;
}

export function tvPending(items: ListItem[], focus: string): ListItem[] {
  return items.filter(item => !item.done).sort((a, b) =>
    Number(b.owner === focus) - Number(a.owner === focus) ||
    (a.due || '9999-12-31').localeCompare(b.due || '9999-12-31') || a.id.localeCompare(b.id));
}

export function tvUpcoming(trips: Trip[], today: string): Trip[] {
  return trips.filter(trip => trip.end >= today).sort((a, b) => a.start.localeCompare(b.start) || a.id.localeCompare(b.id));
}

/** Display integer cents directly, including zero. Never sum or convert currencies. */
export function tvMoney(cents: unknown): string {
  if (typeof cents !== 'number' || !Number.isSafeInteger(cents)) return '待核对';
  const value = BigInt(cents), negative = value < BigInt(0), absolute = negative ? -value : value;
  const integer = (absolute / BigInt(100)).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return `${negative ? '−' : ''}¥${integer}.${(absolute % BigInt(100)).toString().padStart(2, '0')}`;
}

export function tvCountdown(start: string, today: string): string {
  const days = Math.ceil((dayStart(start) - dayStart(today)) / 86_400_000);
  return Number.isFinite(days) ? days > 0 ? `还有 ${days} 天出发` : '旅途中' : '日期待核对';
}

/** Still reading positions overlap by 20%; a very long item extends its own page. */
export function tvReadDuration(viewport: number, content: number): number {
  if (viewport <= 0) return TV_PAGE_MS;
  const steps = Math.ceil(Math.max(0, content - viewport) / (viewport * 0.8));
  return Math.max(TV_PAGE_MS, 6_000 + steps * 5_000);
}

export function tvScrollOffset(viewport: number, content: number, phase: number): number {
  const step = Math.floor(Math.max(0, phase - 3_000) / 5_000);
  return Math.min(Math.max(0, content - viewport), step * Math.max(0, viewport) * 0.8);
}
