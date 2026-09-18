import { sessionIdentity } from './sessionIdentity.ts';
import { validatePlace, type Place } from './places';
import { readTripPhoto, readTripPhotoPage, type TripPhotoPage } from './tripPhotos';
import type { Photo } from './photos';

export class RecapError extends Error { constructor(message = '回顾内容暂时无法核对，请重新读取。', public status = 0) { super(message); } }
export class RecapDiscarded extends Error {}
const bad = (): never => { throw new RecapError(); };
const obj = (v: unknown): Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : bad();
const text = (v: unknown, max = 500, empty = true): string => typeof v === 'string' && v.length <= max && (empty || !!v.trim()) ? v : bad();
const integer = (v: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): number => Number.isSafeInteger(v) && Number(v) >= min && Number(v) <= max ? v as number : bad();
const rows = (v: unknown, max: number): unknown[] => Array.isArray(v) && v.length <= max ? v : bad();
const unique = <T extends { id: string }>(v: T[]): T[] => new Set(v.map(x => x.id)).size === v.length ? v : bad();
export const recapId = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{24}$/.test(v);
const id = (v: unknown): string => recapId(v) ? v : bad();
const day = (v: unknown): string => {
  const s = text(v, 10, false), n = new Date(s + 'T00:00:00Z');
  return /^\d{4}-\d\d-\d\d$/.test(s) && Number.isFinite(n.getTime()) && n.toISOString().slice(0, 10) === s ? s : bad();
};
const stamp = (v: unknown): string => {
  const s = text(v, 60, false); day(s.slice(0, 10)); return /^\d{4}-\d\d-\d\d[T ](?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d(?:\.\d{1,6})?)?(?:Z|[+-]\d\d:\d\d)$/.test(s) && Number.isFinite(Date.parse(s)) ? s : bad();
};
const local = (v: unknown): string => { const s = text(v, 19, false); day(s.slice(0, 10)); return /^\d{4}-\d\d-\d\dT(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?$/.test(s) ? s.replace('T', ' ') : bad(); };
const timezone = (v: unknown): string => { const s = text(v, 100, false); try { new Intl.DateTimeFormat('zh-CN', { timeZone: s }); return s; } catch { return bad(); } };
const clock = (v: unknown): string => v === '' ? '时刻未提供' : typeof v === 'string' && /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(v) ? v : bad();
export type RecapEvent = { id: string; title: string; location: string; note: string; owner: string; start: string; end: string; kind: string; timing: string[]; booking: string | null };
export type RecapJourney = { id: string; tripId: string; revision: number; title: string; start: string; end: string; note: string; tripPresent: boolean;
  destinations: { id: string; city: string; country: string; arrival: string; departure: string; timeZone: string | null }[]; events: RecapEvent[] };
export type RecapPlaces = { items: Place[]; total: number; offset: number; limit: 24; hasMore: boolean };
export type RecapSnapshot = { journey: RecapJourney; places: RecapPlaces; photos: TripPhotoPage; photo: Photo | null };

/** Only current linked events are rendered. Missing records are never recreated from plan.segments. */
export function readRecapJourney(raw: unknown, expectedId: string): RecapJourney {
  const r = obj(raw), plan = obj(r.plan), trip = r.trip === null ? null : obj(r.trip), uid = id(r.id), tripId = id(r.tripId);
  if (uid !== id(expectedId) || trip && id(trip.id) !== tripId) bad();
  const base = trip || plan, start = day(base.start), end = day(base.end); if (end < start) bad();
  const destinations = unique(rows(plan.destinations, 20).map(v => { const d = obj(v), arrival = day(d.arrival), departure = day(d.departure); if (departure < arrival) bad();
    return { id: text(d.key, 64, false), city: text(d.city, 80, false), country: text(d.country, 60), arrival, departure, timeZone: d.timeZone === undefined ? null : timezone(d.timeZone) }; }));
  const events = unique(rows(r.events, 101).map(v => {
    const e = obj(v), eventStart = stamp(e.start), eventEnd = stamp(e.end); integer(e.revision, 1);
    if (Date.parse(eventEnd) < Date.parse(eventStart) || typeof e.allDay !== 'boolean' || e.journeyId !== uid || e.tripId !== tripId) bad();
    const t = e.travelTiming == null ? null : obj(e.travelTiming); let kind = '行程', booking: string | null = null, timing: string[];
    if (t) {
      if (t.schemaVersion !== 2 || !['flight', 'stay', 'activity', 'legacy_day'].includes(String(t.kind)) || !['idea', 'booked', 'cancelled'].includes(String(t.bookingState))) bad();
      kind = ({ flight: '航班', stay: '住宿', activity: '活动', legacy_day: '日期安排' } as Record<string, string>)[String(t.kind)];
      booking = ({ idea: '计划中', booked: '人工标记已预订', cancelled: '人工标记已取消' } as Record<string, string>)[String(t.bookingState)];
      if (t.startLocal !== undefined) {
        timing = [`${local(t.startLocal)}（${timezone(t.startTimeZone)}）`, `至 ${local(t.endLocal)}（${timezone(t.endTimeZone)}）`];
      } else {
        const begin = day(t.startDate), finish = day(t.endDateExclusive); if (finish <= begin) bad();
        timing = t.kind === 'stay' ? [`${begin} 入住 · ${finish} 退房`, `${integer(t.nights, 1)} 晚 · ${timezone(t.timeZone)}`, `入住 ${clock(t.checkInTime)} · 退房 ${clock(t.checkOutTime)}`]
          : [`${begin} 至 ${finish}（结束日不含）`, t.timeZone === undefined ? '日期安排，不代表准确时刻' : timezone(t.timeZone)];
      }
    } else if (e.allDay) {
      // Existing v1 events use +08 compatibility dates and an exclusive end.
      timing = [`${eventStart.slice(0, 10)} 至 ${eventEnd.slice(0, 10)}（结束日不含）`, '全天日期安排'];
    } else {
      const format = (s: string) => new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(s));
      timing = [`${format(eventStart)} 至 ${format(eventEnd)}（北京时间）`];
    }
    return { id: id(e.id), title: text(e.title, 500, false), location: text(e.location ?? '', 500), note: text(e.note ?? '', 8000), owner: text(e.owner, 100, false), start: eventStart, end: eventEnd, kind, timing, booking };
  })).sort((a, b) => Date.parse(a.start) - Date.parse(b.start) || a.id.localeCompare(b.id));
  return { id: uid, tripId, revision: integer(r.revision, 1), title: text(base.title, 500, false), start, end, note: text(base.note ?? '', 6000), tripPresent: !!trip, destinations, events };
}

export function recapPagePath(kind: 'places' | 'photos', journeyId: string, offset: number): string {
  id(journeyId); integer(offset, 0, kind === 'places' ? 3000 : 4000); if (offset % 24 || !['places', 'photos'].includes(kind)) bad();
  return `/${kind === 'places' ? 'journey-places' : 'media/items'}?scope=visible&journeyId=${journeyId}&limit=24&offset=${offset}`;
}
export function readRecapPlaces(raw: unknown, journey: RecapJourney, owner: string, offset: number): RecapPlaces {
  recapPagePath('places', journey.id, offset); const r = obj(raw), total = integer(r.total, 0, 3000);
  if (r.offset !== offset || r.limit !== 24 || r.hasMore !== (offset + 24 < total)) bad();
  const items = unique(rows(r.items, 24).map(v => {
    const p = validatePlace(obj(v) as Place);
    if (p.journeyId !== journey.id || p.journey?.tripId !== journey.tripId || p.canManage !== (p.owner === owner) || !p.canManage && p.visibility !== 'shared') bad();
    if (p.coordinateGridDegrees !== null && (typeof p.coordinateGridDegrees !== 'number' || !Number.isFinite(p.coordinateGridDegrees) || p.coordinateGridDegrees <= 0 || p.coordinateGridDegrees > 360)) bad();
    if (p.coordinatePrecision === 'hidden' || p.coordinatePrecision === 'none') { if (p.coordinates !== null) bad(); }
    else if (!p.coordinates) bad();
    const startDate = p.startDate === null ? null : day(p.startDate), endDate = p.endDate === null ? null : day(p.endDate);
    if (endDate && (!startDate || endDate < startDate) || p.status === 'visited' && (!p.visitedConfirmedAt || !p.visitedConfirmedBy)) bad();
    // Discard raw-coordinate extras, request receipts and source metadata.
    return { id: p.id, owner: text(p.owner, 100, false), name: text(p.name, 160, false), country: text(p.country, 100), city: text(p.city, 100),
      coordinates: p.coordinates ? { latitude: p.coordinates.latitude, longitude: p.coordinates.longitude } : null,
      coordinatePrecision: p.coordinatePrecision, coordinateGridDegrees: p.coordinateGridDegrees, coordinateDisclosure: p.coordinateDisclosure,
      status: p.status, visibility: p.visibility, journeyId: journey.id, journey: { id: journey.id, tripId: journey.tripId, title: journey.title },
      startDate, endDate, revision: p.revision, canManage: p.canManage, visitedConfirmedAt: p.visitedConfirmedAt === null ? null : stamp(p.visitedConfirmedAt),
      visitedConfirmedBy: p.visitedConfirmedBy === null ? null : text(p.visitedConfirmedBy, 100, false), createdAt: stamp(p.createdAt), updatedAt: stamp(p.updatedAt) };
  }));
  if (items.length !== Math.min(24, Math.max(0, total - offset))) bad();
  return { items, total, offset, limit: 24, hasMore: r.hasMore as boolean };
}
export function readRecapPhotos(raw: unknown, journey: RecapJourney, offset: number): TripPhotoPage {
  const page = readTripPhotoPage(raw, journey.id, offset); if (page.total > 4000 || page.items.some(p => p.journey?.tripId !== journey.tripId || p.visibility === 'private' && !p.canManage)) bad(); return page;
}
export function readRecapPhoto(raw: unknown, journey: RecapJourney, expectedId: string): Photo {
  const p = readTripPhoto(obj(raw).item, journey.id, expectedId); if (p.journey?.tripId !== journey.tripId || p.visibility === 'private' && !p.canManage) bad(); return p;
}
export type RecapSession = { user: { role: string; householdId?: string; id: string; auth_version?: number } | null; csrf?: string | null };
export const recapSignature = sessionIdentity;
export class RecapFence {
  private epoch = 0;
  constructor(private expected: string) {}
  invalidate() { ++this.epoch; }
  async run<T>(me: () => Promise<RecapSession>, read: () => Promise<T>, current: () => boolean): Promise<T> {
    const epoch = this.epoch;
    const check = (s: RecapSession) => { if (!current() || epoch !== this.epoch) throw new RecapDiscarded();
      if (!s || s.user?.role !== 'member' || !s.user.householdId || !s.user.id || !Number.isSafeInteger(s.user.auth_version) || Number(s.user.auth_version) < 1 || !s.csrf || recapSignature(s) !== this.expected) throw new RecapDiscarded('identity'); };
    check(await me()); let value!: T, error: unknown, failed = false;
    try { value = await read(); } catch (e) { failed = true; error = e; }
    check(await me()); if (failed) throw error; return value;
  }
}
/** Same-origin GET allowlist only; no provider URL, owner override, or write option. */
export async function recapRequest(path: string, signal: AbortSignal): Promise<unknown> {
  const photo = /^\/media\/items\/[a-f0-9]{24}\/preview$/.test(path);
  if (path !== '/me' && !/^\/journeys\/[a-f0-9]{24}$/.test(path) && !/^\/media\/items\/[a-f0-9]{24}(?:\/preview)?$/.test(path)) {
    const m = /^\/(journey-places|media\/items)\?scope=visible&journeyId=([a-f0-9]{24})&limit=24&offset=(0|[1-9]\d*)$/.exec(path);
    if (!m || recapPagePath(m[1] === 'journey-places' ? 'places' : 'photos', m[2], Number(m[3])) !== path) bad();
  }
  const controller = new AbortController(), deadline = performance.now() + 15000, abort = () => controller.abort();
  const check = () => { if (signal.aborted) throw new RecapDiscarded(); if (controller.signal.aborted || performance.now() >= deadline) throw new RecapError('读取超时或连接中断，请重新读取回顾。'); };
  check(); signal.addEventListener('abort', abort, { once: true }); const timer = setTimeout(abort, 15000);
  try {
    const response = await fetch('/api' + path, { method: 'GET', mode: 'same-origin', credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal: controller.signal, headers: { Accept: photo ? 'image/jpeg' : 'application/json' } }); check();
    if (!response.ok) throw new RecapError([401, 403].includes(response.status) ? '身份或权限需要重新核对。' : [404, 410].includes(response.status) ? '旅行、地点或照片已移除，或不再对你可见。' : '暂时无法读取回顾，请稍后重试。', response.status);
    if (response.redirected || (response.headers.get('Content-Type') || '').split(';')[0].trim().toLowerCase() !== (photo ? 'image/jpeg' : 'application/json')) bad();
    const reader = response.body?.getReader(); if (!reader) return bad(); const chunks: Uint8Array[] = []; let length = 0;
    try { while (true) { const { done, value } = await reader.read(); check(); if (done) break; length += value.byteLength;
      if (length > (photo ? 2 * 1024 * 1024 : 2_000_000)) { controller.abort(); throw new RecapError('回顾内容超出读取限制。'); } chunks.push(value); } }
    finally { void reader.cancel().catch(() => {}); reader.releaseLock(); }
    const bytes = new Uint8Array(length); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
    check(); if (photo) { if (length < 4 || bytes[0] !== 255 || bytes[1] !== 216 || bytes[length - 2] !== 255 || bytes[length - 1] !== 217) bad(); return new Blob([bytes], { type: 'image/jpeg' }); }
    try { return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); } catch { return bad(); }
  } catch (e) { check(); if (e instanceof RecapError || e instanceof RecapDiscarded) throw e; throw new RecapError('连接中断，请重新读取回顾。'); }
  finally { clearTimeout(timer); signal.removeEventListener('abort', abort); }
}
