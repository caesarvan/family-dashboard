import type { CalendarEvent, CalendarMode, FamilyState, ListItem, Person, SharedFinance, Trip } from './types';
import { isDeviceId, readDeviceLayout, type DeviceLayout } from './devices';
import { isOwnerId } from './memberId.ts';

export type TVIdentity = { id: string; householdId: string; name: string; role: 'tv' };
export type TVSpace = { id: string; name: string; slug: string; entry: string };
export type TVSnapshot = { state: FamilyState; display: { focus: string; calendarView: CalendarMode; layout: DeviceLayout } };
export type TVPair = { code: string; secret: string; expiresIn: number };
export class TVError extends Error { constructor(message: string, public status = 0) { super(message); } }
export class TVDiscarded extends Error {}
const invalid = () => new TVError('电视数据暂时无法核对，请重新连接。');
const object = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw invalid();
  return value as Record<string, unknown>;
};
const text = (value: unknown, maximum: number, empty = false): string => {
  if (typeof value !== 'string' || (!empty && !value) || Array.from(value).length > maximum) throw invalid();
  return value;
};
const integer = (value: unknown, minimum = 0, maximum = Number.MAX_SAFE_INTEGER): number => {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < minimum || value > maximum) throw invalid();
  return value;
};
const boolean = (value: unknown): boolean => { if (typeof value !== 'boolean') throw invalid(); return value; };
const spaceId = (value: unknown): string => {
  if (value !== 'default' && !isDeviceId(value)) throw invalid();
  return value as string;
};
const owner = (value: unknown): string => {
  if (!isOwnerId(value)) throw invalid();
  return value;
};
function date(value: unknown, timestamp = false, empty = false): string {
  const result = text(value, 40, empty);
  if (!result && empty) return '';
  const day = result.slice(0, 10), normalized = new Date(day + 'T00:00:00Z');
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || !Number.isFinite(normalized.getTime()) || normalized.toISOString().slice(0, 10) !== day) throw invalid();
  if (result === day) return result;
  if (!timestamp || !/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d(?:\.\d{1,6})?)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.test(result)
    || !Number.isFinite(Date.parse(result))) throw invalid();
  return result;
}
function id(value: unknown): string {
  const result = text(value, 128);
  if (!/^[A-Za-z0-9_-]+$/.test(result)) throw invalid();
  return result;
}
function list<T extends { id: string }>(raw: unknown, read: (value: unknown) => T): T[] {
  if (!Array.isArray(raw)) throw invalid();
  const result = raw.map(read);
  if (new Set(result.map(item => item.id)).size !== result.length) throw invalid();
  return result;
}
function base(raw: Record<string, unknown>, optionalOwner = false) {
  return { id: id(raw.id), revision: integer(raw.revision, 1), title: text(raw.title, 2048),
    owner: owner(optionalOwner && raw.owner === undefined ? 'shared' : raw.owner) };
}

/** A member cookie is never accepted as a television identity. Config is read from /state. */
export function readTVIdentity(raw: unknown): TVIdentity | null {
  const value = object(raw);
  if (value.csrf !== null && value.csrf !== undefined) throw invalid();
  if (value.user === null) return null;
  const user = object(value.user);
  if (user.role !== 'tv' || !isDeviceId(user.id)) throw invalid();
  return { id: user.id, householdId: spaceId(user.householdId), name: text(user.name, 30), role: 'tv' };
}
export function tvIdentityKey(value: TVIdentity): string { return `${value.householdId}:${value.id}`; }
export function sameTVIdentity(a: TVIdentity | null, b: TVIdentity | null): boolean {
  return a === null || b === null ? a === b : tvIdentityKey(a) === tvIdentityKey(b);
}
export function readTVSpace(raw: unknown): TVSpace {
  const value = object(raw), slug = text(value.slug, 80);
  if (!/^[a-z][a-z0-9-]{2,31}$/.test(slug) || value.entry !== `/space/${slug}`) throw invalid();
  return { id: spaceId(value.id), name: text(value.name, 80), slug, entry: `/space/${slug}` };
}
export function readTVPair(raw: unknown): TVPair {
  const value = object(raw);
  if (typeof value.code !== 'string' || !/^[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{8}$/.test(value.code)
    || typeof value.secret !== 'string' || !/^[A-Za-z0-9_-]{32,100}$/.test(value.secret)) throw invalid();
  return { code: value.code, secret: value.secret, expiresIn: integer(value.expiresIn, 1, 600) };
}
export function readTVPairPoll(raw: unknown): boolean { return boolean(object(raw).approved); }

/** Project only the board's shared fields. Never retain wealth, accounts, notes or media bytes. */
export function readTVSnapshot(raw: unknown, actor: TVIdentity): TVSnapshot {
  const value = object(raw), household = object(value.household);
  if (spaceId(household.id) !== actor.householdId) throw invalid();
  const people = list<Person>(value.people, entry => {
    const person = object(entry), uid = owner(person.id);
    if (uid === 'shared') throw invalid();
    return { id: uid, name: text(person.name, 80) };
  });
  const display = object(value.display), focus = owner(display.focus);
  if (focus !== 'shared' && !people.some(person => person.id === focus)) throw invalid();
  if (display.calendarView !== 'today' && display.calendarView !== 'week' && display.calendarView !== 'around') throw invalid();
  const events = list<CalendarEvent>(value.events, entry => {
    const row = object(entry), start = date(row.start, true), end = date(row.end, true);
    const allDay = row.allDay === undefined ? false : boolean(row.allDay);
    if ((!allDay && (start.length === 10 || end.length === 10)) || Date.parse(end) < Date.parse(start)) throw invalid();
    return { ...base(row), start, end, allDay, location: text(row.location ?? '', 2048, true) };
  });
  const readList = (entry: unknown, shopping: boolean): ListItem => {
    const row = object(entry);
    return { ...base(row), done: boolean(row.done), due: date(row.due ?? '', false, true),
      ...(row.tripId ? { tripId: id(row.tripId) } : {}),
      ...(shopping ? { quantity: text(row.quantity ?? '', 30, true), budget: row.budget == null ? null : integer(row.budget) } : {}) };
  };
  const tasks = list(value.tasks, row => readList(row, false)), shopping = list(value.shopping, row => readList(row, true));
  const trips = list<Trip>(value.trips, entry => {
    const row = object(entry), start = date(row.start), end = date(row.end);
    if (end < start) throw invalid();
    return { ...base(row, true), start, end, destination: text(row.destination ?? '', 2048, true),
      budget: integer(row.budget), saved: integer(row.saved), paid: integer(row.paid) };
  });
  const money = object(value.finance);
  const finance: SharedFinance = { revision: integer(money.revision, 1), wallet: integer(money.wallet),
    livingSpent: integer(money.livingSpent), livingBudget: integer(money.livingBudget),
    reserveTarget: integer(money.reserveTarget), travelSaved: integer(money.travelSaved), longterm: integer(money.longterm),
    contributionPercent: integer(money.contributionPercent, 0, 100), confirmedAt: date(money.confirmedAt ?? '', true, true) };
  return { state: { revision: integer(value.revision, 1), household: { id: actor.householdId,
    name: text(household.name, 80), slug: text(household.slug, 80) }, people, events, tasks, shopping, trips, finance },
    display: { focus, calendarView: display.calendarView, layout: readDeviceLayout(display.layout) } };
}

/** Invalidate even failed/aborted work. Old requests cannot become current on resume. */
export class TVGeneration {
  private version = 0;
  private active = false;
  open(): number { this.active = true; return ++this.version; }
  close(): void { this.active = false; ++this.version; }
  ticket(): number { return this.version; }
  current(ticket: number): boolean { return this.active && ticket === this.version; }
  check(ticket: number): void { if (!this.current(ticket)) throw new TVDiscarded(); }
}

export type TVPath = '/me' | '/state' | '/spaces/current' | '/pair/start' | '/pair/poll';
export async function tvRequest(path: TVPath, signal: AbortSignal, body?: Record<string, unknown>): Promise<unknown> {
  const write = path === '/pair/start' || path === '/pair/poll';
  if (!['/me', '/state', '/spaces/current', '/pair/start', '/pair/poll'].includes(path)
    || (!write && body !== undefined)) throw invalid();
  const controller = new AbortController(), deadline = performance.now() + 8_000;
  const abort = () => controller.abort();
  if (signal.aborted) throw new TVDiscarded();
  signal.addEventListener('abort', abort, { once: true });
  const timer = setTimeout(abort, 8_000);
  const check = () => { if (signal.aborted) throw new TVDiscarded(); if (controller.signal.aborted || performance.now() >= deadline) throw new TVError('连接超时，内容已隐藏。'); };
  try {
    const response = await fetch('/api' + path, { method: write ? 'POST' : 'GET', mode: 'same-origin',
      credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal: controller.signal,
      headers: { 'Content-Type': 'application/json', 'X-Display-Mode': 'tv' },
      ...(write ? { body: JSON.stringify(body ?? {}) } : {}) });
    check();
    if (response.redirected) throw invalid();
    if (!response.ok) throw new TVError(response.status === 410 ? '配对码已过期。' : response.status === 401 || response.status === 403
      ? '电视连接已失效，请重新核对。' : '暂时无法连接家庭看板。', response.status);
    if (!response.headers.get('Content-Type')?.toLowerCase().includes('application/json')) throw invalid();
    const value: unknown = await response.json(); check(); return value;
  } catch (error) {
    check();
    if (error instanceof TVError || error instanceof TVDiscarded) throw error;
    throw new TVError('连接中断，内容已隐藏。');
  } finally { clearTimeout(timer); signal.removeEventListener('abort', abort); }
}

export function isTVRoute(pathname: string): boolean { return /^\/(?:app\/)?tv\/?$/.test(pathname); }
