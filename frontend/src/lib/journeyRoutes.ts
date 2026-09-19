import { coordinatesValid, validatePlace, type Coordinates, type Place } from './places';
import { ApiError, request } from './api';
import { checkedPlaceMutation, PlaceWriteRejected } from './journeyPlaces';

export type RouteStop = { index: number; state: 'available'; place: Place } | { index: number; state: 'unavailable' };
export type RouteSegment = { fromIndex: number; toIndex: number };
export type RouteLine = { fromIndex: number; toIndex: number; from: Coordinates; to: Coordinates; approximate: boolean };
export type RouteMarker = { indices: number[]; point: Coordinates; names: string[]; approximate: boolean };
export type RouteMap = { lines: RouteLine[]; markers: RouteMarker[] };
export type JourneyRoute = { id: string; title: string; journeyId: string; visibility: 'private' | 'shared'; revision: number; canManage: boolean; sourceVersion: string; stops: RouteStop[] };
export type RouteDetail = { route: JourneyRoute; segments: RouteSegment[] };
export type RouteSummary = Omit<JourneyRoute, 'sourceVersion' | 'stops'> & { stopCount: number; unavailableCount: number };
export type RoutePage = { items: RouteSummary[]; total: number; limit: number; offset: number; hasMore: boolean };
export type RouteReceipt = { operation: { requestId: string; kind: 'create' | 'update' | 'delete'; routeId: string; resultRevision: number; completedAt: string }; replayed: boolean; current: RouteDetail | null };
export type StopInput = { placeId: string; expectedRevision: number } | { keepUnavailableIndex: number };
export type RouteOrigin = Pick<JourneyRoute, 'id' | 'journeyId' | 'visibility' | 'revision' | 'canManage' | 'sourceVersion'> & { stops: { index: number; state: RouteStop['state'] }[] };
export type RouteDraft = { title: string; visibility: 'private' | 'shared'; stops: StopInput[]; expectedJourneyRevision: number; original: RouteOrigin | null };
export type RouteIntent = { requestId: string; method: 'POST' | 'PUT' | 'DELETE'; path: string; body: Record<string, unknown>; routeId?: string; uncertain: boolean };
const bad = (): never => { throw new Error('路线数据无法核对，请重新读取。'); };
const obj = (v: unknown): Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : bad();
const num = (v: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): number => Number.isSafeInteger(v) && Number(v) >= min && Number(v) <= max ? v as number : bad();
const text = (v: unknown, max = 160, empty = false): string => typeof v === 'string' && (empty || !!v.trim()) && Array.from(v).length <= max && !/\p{C}/u.test(v) ? v : bad();
const bool = (v: unknown): boolean => typeof v === 'boolean' ? v : bad();
const rows = (v: unknown, max = 100): unknown[] => Array.isArray(v) && v.length <= max ? v : bad();
export const routeId = (v: unknown, length = 24): string => typeof v === 'string' && new RegExp('^[a-f0-9]{' + length + '}$').test(v) ? v : bad();
const visibility = (v: unknown): JourneyRoute['visibility'] => v === 'private' || v === 'shared' ? v : bad();
function point(v: unknown): Coordinates | null { if (v === null) return null; if (!coordinatesValid(v)) return bad(); return { latitude: v.latitude, longitude: v.longitude }; }
function precision(v: unknown): Place['coordinatePrecision'] { return ['exact', 'approximate', 'hidden', 'none'].includes(String(v)) ? v as Place['coordinatePrecision'] : bad(); }
/** Project a place DTO onto known fields; no raw extras enter the map or recovery. */
export function readRoutePlace(value: unknown, journeyId: string, publicOnly = false): Place {
  const p = validatePlace(obj(value) as Place);
  if (p.journeyId !== routeId(journeyId) || !p.canManage && p.visibility !== 'shared' || publicOnly && (p.visibility !== 'shared' || p.canManage)) bad();
  const coordinates = point(p.coordinates), coordinatePrecision = precision(p.coordinatePrecision);
  if ((coordinatePrecision === 'hidden' || coordinatePrecision === 'none') !== (coordinates === null)) bad();
  if (coordinatePrecision === 'approximate' && p.coordinateGridDegrees !== 0.1 || coordinatePrecision !== 'approximate' && p.coordinateGridDegrees !== null) bad();
  if (!p.canManage && (p.coordinateDisclosure === 'hidden' && coordinates || p.coordinateDisclosure === 'coarse' && coordinates && coordinatePrecision !== 'approximate')) bad();
  if (coordinatePrecision === 'approximate' && coordinates && [coordinates.latitude, coordinates.longitude].some(n => Math.abs(n * 10 - Math.round(n * 10)) > 1e-7)) bad();
  const result: Place = { id: p.id, owner: text(p.owner, 100), name: text(p.name), country: text(p.country, 100, true), city: text(p.city, 100, true), coordinates,
    coordinatePrecision, coordinateGridDegrees: p.coordinateGridDegrees, coordinateDisclosure: p.coordinateDisclosure, status: p.status, visibility: p.visibility,
    journeyId, journey: { id: journeyId, tripId: routeId(p.journey!.tripId), title: text(p.journey!.title, 500) }, startDate: p.startDate, endDate: p.endDate,
    revision: p.revision, canManage: p.canManage, visitedConfirmedAt: p.visitedConfirmedAt, visitedConfirmedBy: p.visitedConfirmedBy, createdAt: p.createdAt, updatedAt: p.updatedAt };
  if (!publicOnly && p.canManage && Object.hasOwn(p, 'sharedCoordinates')) {
    result.sharedCoordinates = point(p.sharedCoordinates); result.sharedCoordinatePrecision = precision(p.sharedCoordinatePrecision);
    if ((result.sharedCoordinatePrecision === 'hidden' || result.sharedCoordinatePrecision === 'none') !== (result.sharedCoordinates === null)) bad();
  }
  return result;
}
export function publicRoutePlace(p: Place): Place | null {
  if (p.visibility !== 'shared') return null;
  if (!p.canManage) return p;
  if (!Object.hasOwn(p, 'sharedCoordinates') || !p.sharedCoordinatePrecision) return null;
  return readRoutePlace({ ...p, coordinates: p.sharedCoordinates, coordinatePrecision: p.sharedCoordinatePrecision,
    coordinateGridDegrees: p.sharedCoordinatePrecision === 'approximate' ? 0.1 : null, canManage: false }, p.journeyId!, true);
}
function summary(value: unknown, journeyId: string): Omit<RouteSummary, 'stopCount' | 'unavailableCount'> {
  const r = obj(value), result = { id: routeId(r.id), title: text(r.title), journeyId: routeId(r.journeyId), visibility: visibility(r.visibility), revision: num(r.revision, 1), canManage: bool(r.canManage) };
  if (result.journeyId !== journeyId || !result.canManage && result.visibility !== 'shared') bad(); return result;
}
export function readRouteDetail(value: unknown, journeyId: string, expectedId?: string): RouteDetail {
  const r = obj(value), raw = obj(r.route), base = summary(raw, journeyId);
  if (expectedId && base.id !== routeId(expectedId)) bad();
  const stops = rows(raw.stops).map((v, index): RouteStop => {
    const s = obj(v); if (s.index !== index) bad();
    if (s.state === 'unavailable') { if (Object.keys(s).some(k => k !== 'index' && k !== 'state')) bad(); return { index, state: 'unavailable' }; }
    if (s.state !== 'available') bad();
    return { index, state: 'available', place: readRoutePlace(s.place, journeyId, base.visibility === 'shared') };
  });
  if (!stops.length) bad();
  const segments = rows(r.segments, 99).map(v => { const s = obj(v); return { fromIndex: num(s.fromIndex, 0, 99), toIndex: num(s.toIndex, 0, 99) }; });
  if (JSON.stringify(segments) !== JSON.stringify(adjacentRouteSegments(stops))) bad();
  return { route: { ...base, sourceVersion: routeId(raw.sourceVersion, 64), stops }, segments };
}
export function readRoutePage(value: unknown, journeyId: string, scope: 'mine' | 'shared', offset: number, limit = 24): RoutePage {
  num(offset, 0, 10000); num(limit, 1, 100);
  const r = obj(value), total = num(r.total); if (r.offset !== offset || r.limit !== limit || r.hasMore !== (offset + limit < total)) bad();
  const items = rows(r.items, limit).map(v => { const raw = obj(v), base = summary(raw, journeyId), stopCount = num(raw.stopCount, 1, 100), unavailableCount = num(raw.unavailableCount, 0, stopCount);
    if (scope === 'mine' && !base.canManage || scope === 'shared' && base.visibility !== 'shared') bad(); return { ...base, stopCount, unavailableCount }; });
  if (new Set(items.map(r => r.id)).size !== items.length || items.length !== Math.min(limit, Math.max(0, total - offset))) bad();
  return { items, total, offset, limit, hasMore: bool(r.hasMore) };
}
export function readRouteReceipt(value: unknown, intent: RouteIntent, journeyId: string): RouteReceipt {
  const r = obj(value), o = obj(r.operation), kind = intent.method === 'POST' ? 'create' : intent.method === 'PUT' ? 'update' : 'delete';
  if (o.requestId !== routeId(intent.requestId, 32) || o.kind !== kind || intent.routeId && o.routeId !== intent.routeId) bad();
  const operation: RouteReceipt['operation'] = { requestId: intent.requestId, kind, routeId: routeId(o.routeId), resultRevision: num(o.resultRevision, 1), completedAt: text(o.completedAt, 64) };
  if (!Number.isFinite(Date.parse(operation.completedAt))) bad();
  let current: RouteDetail | null = null;
  if (r.current !== null) {
    const now = obj(obj(r.current).route);
    if (routeId(now.id) !== operation.routeId || num(now.revision, 1) < operation.resultRevision || kind === 'delete') bad();
    if (now.journeyId !== null) routeId(now.journeyId);
    // Completion survives a later move/deleted journey. Never render another journey here.
    if (now.journeyId === journeyId) current = readRouteDetail(r.current, journeyId, operation.routeId);
  }
  return { operation, replayed: bool(r.replayed), current };
}
export function routeDraft(route: JourneyRoute | null, journeyRevision: number): RouteDraft {
  if (route && !route.canManage) bad();
  return { title: route?.title || '', visibility: route?.visibility || 'private', expectedJourneyRevision: num(journeyRevision, 1), original: route ? routeOrigin(route) : null,
    stops: route?.stops.map(s => s.state === 'available' ? { placeId: s.place.id, expectedRevision: s.place.revision } : { keepUnavailableIndex: s.index }) || [] };
}
export function routeOrigin(route: JourneyRoute): RouteOrigin {
  return { id: route.id, journeyId: route.journeyId, visibility: route.visibility, revision: route.revision, canManage: route.canManage, sourceVersion: route.sourceVersion,
    stops: route.stops.map(s => ({ index: s.index, state: s.state })) };
}
export function draftRouteStops(draft: RouteDraft, places: Map<string, Place>): RouteStop[] {
  return draft.stops.map((s, index) => {
    const p = 'placeId' in s ? places.get(s.placeId) : undefined, projected = p && (draft.visibility === 'shared' ? publicRoutePlace(p) : p);
    return projected ? { index, state: 'available', place: projected } : { index, state: 'unavailable' };
  });
}
export function routeWriteIntent(draft: RouteDraft, journeyId: string, requestId: string): RouteIntent {
  const original = draft.original; if (original && (!original.canManage || original.journeyId !== journeyId)) bad();
  const kept = new Set<number>();
  const stops = rows(draft.stops).map(value => { const s = obj(value);
    if (Object.hasOwn(s, 'placeId')) return { placeId: routeId(s.placeId), expectedRevision: num(s.expectedRevision, 1) };
    const index = num(s.keepUnavailableIndex, 0, 99);
    if (!original || original.stops[index]?.state !== 'unavailable' || kept.has(index) || original.visibility === 'private' && draft.visibility === 'shared') bad();
    kept.add(index); return { keepUnavailableIndex: index };
  });
  if (!stops.length) throw new Error('请至少选择一站。');
  return { requestId: routeId(requestId, 32), method: original ? 'PUT' : 'POST', path: '/journey-routes' + (original ? '/' + original.id : ''), routeId: original?.id, uncertain: false,
    body: { requestId, title: text(draft.title.trim()), journeyId: routeId(journeyId), expectedJourneyRevision: num(draft.expectedJourneyRevision, 1), visibility: visibility(draft.visibility), stops,
      ...(original ? { revision: num(original.revision, 1), sourceVersion: routeId(original.sourceVersion, 64) } : {}) } };
}
export function routeDeleteIntent(route: JourneyRoute, requestId: string): RouteIntent {
  if (!route.canManage) bad(); return { requestId: routeId(requestId, 32), method: 'DELETE', path: '/journey-routes/' + routeId(route.id), routeId: route.id, uncertain: false,
    body: { requestId, revision: num(route.revision, 1), sourceVersion: routeId(route.sourceVersion, 64) } };
}
export async function sendRouteIntent(intent: RouteIntent, guard: <T>(action: (csrf: string) => Promise<T>) => Promise<T>, journeyId: string, signal?: AbortSignal): Promise<RouteReceipt> {
  const raw = await checkedPlaceMutation(guard, csrf => request<unknown>(intent.path, { method: intent.method, body: JSON.stringify(intent.body), signal }, csrf), e => e instanceof ApiError ? e.status : undefined);
  return readRouteReceipt(raw, intent, journeyId);
}
/** Only a fenced, definitive rejection frees the draft; never replace an unknown key. */
export function routeIntentUnknown(intent: RouteIntent, failure: unknown): boolean { return intent.uncertain || !(failure instanceof PlaceWriteRejected); }

/** A straight schematic, split at the antimeridian; never a navigation path. */
export function routeGeometry(stops: RouteStop[], segments: RouteSegment[]): RouteMap {
  const lines: RouteLine[] = [], markers: RouteMarker[] = [];
  const points = new Map<string, RouteMarker>();
  for (const stop of stops) {
    if (stop.state !== 'available' || !stop.place.coordinates || !coordinatesValid(stop.place.coordinates)) continue;
    const point = stop.place.coordinates, key = `${point.latitude}:${point.longitude}`;
    let marker = points.get(key);
    if (!marker) { marker = { indices: [], point, names: [], approximate: false }; points.set(key, marker); markers.push(marker); }
    marker.indices.push(stop.index); marker.names.push(stop.place.name);
    marker.approximate ||= stop.place.coordinatePrecision === 'approximate';
  }
  const seen = new Set<number>();
  for (const segment of segments) {
    const { fromIndex, toIndex } = segment;
    // Do not reconnect a filtered list, even if a malformed server suggests it.
    if (!Number.isSafeInteger(fromIndex) || toIndex !== fromIndex + 1 || seen.has(fromIndex)) continue;
    seen.add(fromIndex);
    const first = stops[fromIndex], second = stops[toIndex];
    if (!first || !second || first.index !== fromIndex || second.index !== toIndex || first.state !== 'available' || second.state !== 'available') continue;
    const from = first.place.coordinates, to = second.place.coordinates;
    if (!from || !to || !coordinatesValid(from) || !coordinatesValid(to)) continue;
    const base = { fromIndex, toIndex, approximate: first.place.coordinatePrecision === 'approximate' || second.place.coordinatePrecision === 'approximate' };
    const delta = to.longitude - from.longitude;
    if (Math.abs(delta) <= 180) { lines.push({ ...base, from, to }); continue; }
    const unwrapped = to.longitude + (delta > 180 ? -360 : 360), edge = delta > 180 ? -180 : 180;
    const distance = unwrapped - from.longitude;
    // +180/-180 are the same meridian: no across-map artefact or division by zero.
    if (!distance) { lines.push({ ...base, from, to: { ...to, longitude: from.longitude } }); continue; }
    const latitude = from.latitude + (to.latitude - from.latitude) * (edge - from.longitude) / distance;
    lines.push({ ...base, from, to: { latitude, longitude: edge } }, { ...base, from: { latitude, longitude: -edge }, to });
  }
  return { lines, markers };
}

export function adjacentRouteSegments(stops: RouteStop[]): RouteSegment[] {
  return stops.flatMap((stop, index) => index + 1 < stops.length && stop.state === 'available' && stop.place.coordinates
    && stops[index + 1].state === 'available' && (stops[index + 1] as Extract<RouteStop, { state: 'available' }>).place.coordinates
    ? [{ fromIndex: index, toIndex: index + 1 }] : []);
}
