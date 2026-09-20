import { memberIdentity, sessionIdentity, type IdentitySession } from './sessionIdentity.ts';

export type TVTrip = { id: string; tripId: string; title: string; start: string; end: string; revision: number; tripRevision: number };
export type TVRoutePlace = { id: string; name: string; country: string; city: string;
  coordinates: { latitude: number; longitude: number } | null; coordinatePrecision: 'exact' | 'approximate' | 'hidden' | 'none';
  coordinateGridDegrees: number | null; status: 'visited' | 'planned' | 'wish'; startDate: string | null; endDate: string | null };
export type TVRouteStop = { index: number; state: 'unavailable' } | { index: number; state: 'available'; place: TVRoutePlace };
export type TVRoute = { id: string; title: string; revision: number; stops: TVRouteStop[]; segments: { fromIndex: number; toIndex: number }[] };
export type JourneyReview = { status: 'ready' | 'journey_unavailable'; journey: TVTrip | null;
  routeStatus: 'not_selected' | 'available' | 'unavailable'; route: TVRoute | null; sourceVersion: string };
export type JourneyPreview = { previewToken: string; expiresAt: string; playbackRevision: number; sourceVersion: string;
  journey: TVTrip; mediaCount: number; routeStatus: 'not_selected' | 'available'; route: TVRoute | null; canStart: boolean };
export type JourneyOperation = { requestId: string; kind: 'journey_start'; deviceId: string; resultRevision: number; completedAt: string };
export type JourneyMarker = { memberIdentity: string; deviceId: string; requestId: string };
export const TRIP_TV_STORAGE_KEY = 'family-dashboard:trip-tv-operation:v1';
export const TRIP_TV_JSON_BYTES = 512 * 1024;
const bad = (): never => { throw new Error('电视回顾资料无法核对，请重新读取。'); };
const obj = (v: unknown): Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : bad();
const int = (v: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): number => Number.isSafeInteger(v) && Number(v) >= min && Number(v) <= max ? Number(v) : bad();
const text = (v: unknown, max: number, empty = false): string => typeof v === 'string' && (empty || !!v.trim()) && Array.from(v).length <= max && !/[\u0000-\u001f\u007f]/.test(v) ? v : bad();
export const tripTVId = (v: unknown, size = 24): string => typeof v === 'string' && new RegExp('^[a-f0-9]{' + size + '}$').test(v) ? v : bad();
const date = (v: unknown, empty = false): string => typeof v === 'string' && (empty && v === '' || /^\d{4}-\d{2}-\d{2}$/.test(v)) ? v : bad();
const instant = (v: unknown): string => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(v) && Number.isFinite(Date.parse(v)) ? v : bad();
export function readTVTrip(value: unknown): TVTrip {
  const v = obj(value); return { id: tripTVId(v.id), tripId: tripTVId(v.tripId), title: text(v.title, 100), start: date(v.start), end: date(v.end), revision: int(v.revision, 1), tripRevision: int(v.tripRevision, 1) };
}
export function readTVRoute(value: unknown): TVRoute {
  const v = obj(value);
  if (!Array.isArray(v.stops) || !v.stops.length || v.stops.length > 100 || !Array.isArray(v.segments) || v.segments.length > 99) bad();
  const stops = (v.stops as unknown[]).map((raw, index): TVRouteStop => {
    const s = obj(raw); if (s.index !== index) bad();
    if (s.state === 'unavailable') { if (Object.keys(s).some(k => !['index', 'state'].includes(k))) bad(); return { index, state: 'unavailable' }; }
    if (s.state !== 'available') bad();
    const p = obj(s.place), precision = p.coordinatePrecision;
    if (!['exact', 'approximate', 'hidden', 'none'].includes(String(precision)) || !['visited', 'planned', 'wish'].includes(String(p.status))) bad();
    let coordinates: TVRoutePlace['coordinates'] = null;
    if (p.coordinates !== null) {
      const c = obj(p.coordinates);
      if (typeof c.latitude !== 'number' || !Number.isFinite(c.latitude) || Math.abs(c.latitude) > 90
        || typeof c.longitude !== 'number' || !Number.isFinite(c.longitude) || Math.abs(c.longitude) > 180) bad();
      coordinates = { latitude: c.latitude as number, longitude: c.longitude as number };
    }
    if ((precision === 'hidden' || precision === 'none') !== (coordinates === null)
      || p.coordinateGridDegrees !== (precision === 'approximate' ? 0.1 : null)) bad();
    if (precision === 'approximate' && coordinates && [coordinates.latitude, coordinates.longitude].some(n => Math.abs(n * 10 - Math.round(n * 10)) > 1e-7)) bad();
    return { index, state: 'available', place: { id: tripTVId(p.id), name: text(p.name, 160), country: text(p.country, 100, true), city: text(p.city, 100, true),
      coordinates, coordinatePrecision: precision as TVRoutePlace['coordinatePrecision'], coordinateGridDegrees: p.coordinateGridDegrees as number | null,
      status: p.status as TVRoutePlace['status'], startDate: p.startDate === null ? null : date(p.startDate, true), endDate: p.endDate === null ? null : date(p.endDate, true) } };
  });
  const seen = new Set<number>();
  const segments = (v.segments as unknown[]).map(raw => {
    const s = obj(raw), fromIndex = int(s.fromIndex, 0, 98), toIndex = int(s.toIndex, 1, 99), a = stops[fromIndex], b = stops[toIndex];
    // Only the supplied adjacent, authorized coordinate pairs may become lines.
    if (toIndex !== fromIndex + 1 || seen.has(fromIndex) || a?.state !== 'available' || b?.state !== 'available' || !a.place.coordinates || !b.place.coordinates) bad();
    seen.add(fromIndex); return { fromIndex, toIndex };
  });
  return { id: tripTVId(v.id), title: text(v.title, 160), revision: int(v.revision, 1), stops, segments };
}
export function readJourneyReview(value: unknown): JourneyReview {
  const v = obj(value);
  if (!['ready', 'journey_unavailable'].includes(String(v.status)) || !['available', 'unavailable', 'not_selected'].includes(String(v.routeStatus))) bad();
  const journey = v.journey === null ? null : readTVTrip(v.journey), route = v.route === null ? null : readTVRoute(v.route);
  if ((v.status === 'ready') !== !!journey || (v.routeStatus === 'available') !== !!route || !journey && route) bad();
  return { status: v.status as JourneyReview['status'], journey, routeStatus: v.routeStatus as JourneyReview['routeStatus'], route, sourceVersion: tripTVId(v.sourceVersion, 64) };
}
export function readJourneyScope(value: Record<string, unknown>): { scope?: 'all' | 'journey'; journeyReview?: JourneyReview | null } {
  // Legacy all-media DTOs remain readable; a half-upgraded scoped DTO never is.
  if (value.scope === undefined && value.journeyReview === undefined) return {};
  if (value.scope === 'all' && value.journeyReview === null) return { scope: 'all', journeyReview: null };
  if (value.scope !== 'journey' || value.mode !== 'photos') bad();
  const review = readJourneyReview(value.journeyReview);
  if (review.status === 'journey_unavailable' && (value.photoCount !== 0 || value.item != null || value.progress != null)) bad();
  return { scope: 'journey', journeyReview: review };
}
export function journeyCanStart(review: JourneyReview | null | undefined, count: number): boolean {
  return review ? review.status === 'ready' && (count > 0 || !!review.route?.stops.some(s => s.state === 'available')) : count > 0;
}
export function readJourneyPreview(value: unknown, journeyId: string, routeId: string | null, revision: number): JourneyPreview {
  const v = obj(value), journey = readTVTrip(v.journey), route = v.route === null ? null : readTVRoute(v.route), mediaCount = int(v.mediaCount, 0, 2000);
  if (journey.id !== journeyId || (route?.id ?? null) !== routeId || v.playbackRevision !== revision
    || v.routeStatus !== (route ? 'available' : 'not_selected') || v.canStart !== (mediaCount > 0 || !!route?.stops.some(s => s.state === 'available'))) bad();
  return { previewToken: text(v.previewToken, 4096), expiresAt: instant(v.expiresAt), playbackRevision: revision,
    sourceVersion: tripTVId(v.sourceVersion, 64), journey, route, routeStatus: route ? 'available' : 'not_selected', mediaCount, canStart: v.canStart as boolean };
}
export function readJourneyOperation(value: unknown, marker: JourneyMarker): JourneyOperation {
  const v = obj(value);
  if (v.kind !== 'journey_start' || v.requestId !== marker.requestId || v.deviceId !== marker.deviceId) bad();
  return { requestId: marker.requestId, deviceId: marker.deviceId, kind: 'journey_start', resultRevision: int(v.resultRevision, 1), completedAt: instant(v.completedAt) };
}
export function restoreJourneyMarker(storage: Pick<Storage, 'getItem' | 'removeItem'> | null, identity: string): JourneyMarker | null {
  if (!storage) return null;
  try { const raw = storage.getItem(TRIP_TV_STORAGE_KEY); if (!raw) return null; const v = obj(JSON.parse(raw));
    if (v.memberIdentity !== identity || Object.keys(v).sort().join() !== 'deviceId,memberIdentity,requestId') { storage.removeItem(TRIP_TV_STORAGE_KEY); return null; }
    return { memberIdentity: identity, deviceId: tripTVId(v.deviceId), requestId: tripTVId(v.requestId, 32) };
  } catch { try { storage.removeItem(TRIP_TV_STORAGE_KEY); } catch {} return null; }
}
export function forgetJourneyMarker(storage: Pick<Storage, 'getItem' | 'removeItem'> | null, marker: JourneyMarker | null) {
  if (!storage || !marker) return;
  try { const raw = JSON.parse(storage.getItem(TRIP_TV_STORAGE_KEY) || 'null');
    if (raw?.memberIdentity === marker.memberIdentity && raw.deviceId === marker.deviceId && raw.requestId === marker.requestId) storage.removeItem(TRIP_TV_STORAGE_KEY);
  } catch {}
}
export const journeyActor = (session: IdentitySession) => memberIdentity(session.user);
export class TripTVDiscarded extends Error {}
export class TripTVError extends Error { constructor(public status: number) { super(status === 409 ? '电视或旅行资料已变化，请重新核对后再开始。' : '暂时无法核对电视回顾，请稍后重试。'); } }
export class TripTVRejected extends Error {}
/** Both identity checks cover the write as well as every sensitive read. */
export class TripTVFence {
  constructor(private identity: string, private me: () => Promise<IdentitySession>) {}
  async run<T>(job: (csrf: string) => Promise<T>, current: () => boolean): Promise<T> {
    const check = (s: IdentitySession) => { if (!current()) throw new TripTVDiscarded();
      if (s.user?.role !== 'member' || !s.csrf || sessionIdentity(s) !== this.identity) throw new TripTVDiscarded('identity'); return s.csrf; };
    const csrf = check(await this.me()); let result!: T, failure: unknown, failed = false;
    try { result = await job(csrf); } catch (error) { failed = true; failure = error; }
    check(await this.me()); if (failed) throw failure; return result;
  }
}
export async function tripTVRequest(path: string, options: RequestInit = {}, csrf = ''): Promise<unknown> {
  if (!/^\/(?:me|devices|journey-routes\?[^#]*|media-playback\/devices\/[a-f0-9]{24}(?:\/journey-(?:preview|start))?|media-playback\/operations\/[a-f0-9]{32})$/.test(path)) bad();
  const controller = new AbortController(), abort = () => controller.abort(); options.signal?.addEventListener('abort', abort, { once: true });
  if (options.signal?.aborted) controller.abort(); const timer = setTimeout(abort, 20000);
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  try {
    const response = await fetch('/api' + path, { ...options, signal: controller.signal, credentials: 'same-origin', mode: 'same-origin', cache: 'no-store', redirect: 'error',
      headers: { 'Content-Type': 'application/json', ...(csrf ? { 'X-CSRF-Token': csrf } : {}) } });
    if (response.redirected || typeof window !== 'undefined' && response.url !== new URL('/api' + path, window.location.origin).href
      || !response.headers.get('Content-Type')?.toLowerCase().startsWith('application/json')) bad();
    reader = response.body?.getReader(); if (!reader) bad(); const chunks: Uint8Array[] = []; let length = 0;
    while (true) { const part = await reader!.read(); if (controller.signal.aborted) bad(); if (part.done) break;
      length += part.value.length; if (length > TRIP_TV_JSON_BYTES) bad(); chunks.push(part.value); }
    const bytes = new Uint8Array(length); let offset = 0; for (const part of chunks) { bytes.set(part, offset); offset += part.length; }
    const result = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
    if (!response.ok) throw new TripTVError(response.status); return result;
  } finally { clearTimeout(timer); options.signal?.removeEventListener('abort', abort); if (reader) { void reader.cancel().catch(() => {}); reader.releaseLock(); } }
}
