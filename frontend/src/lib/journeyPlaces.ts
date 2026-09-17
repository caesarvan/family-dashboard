import type { MapView, Place, PlaceDraft } from './places';

export type JourneyPlaceSource = { id: string; tripId: string; revision: number; title: string; destinations: { key: string; country: string; city: string; arrival: string; departure: string }[] };
export type JourneyPlaceEditor = { draft: PlaceDraft; original: Place | null; sourceRevision: number; destinationKey?: string };
export type PlaceIntent = { method: 'POST' | 'PATCH'; path: string; body: Record<string, unknown>; id?: string; state: 'unknown' | 'rejected'; uncertain: boolean };
const object = (value: unknown): Record<string, unknown> => { if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('旅行数据格式不正确。'); return value as Record<string, unknown>; };
const id = (value: unknown): string => { if (typeof value !== 'string' || !/^[a-f0-9]{24}$/.test(value)) throw new Error('旅行编号不正确。'); return value; };
const revision = (value: unknown): number => { if (!Number.isSafeInteger(value) || Number(value) < 1) throw new Error('版本无法核对。'); return Number(value); };
function text(value: unknown, maximum: number, empty = false): string {
  if (typeof value !== 'string' || /\p{C}/u.test(value)) throw new Error('地点文字格式不正确。');
  const result = value.trim(); if ((!result && !empty) || Array.from(result).length > maximum) throw new Error('地点文字长度不正确。'); return result;
}
function day(value: unknown, optional = false): string | null {
  if (optional && value === '') return null;
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value < '0001-01-01') throw new Error('日期请填写有效的 YYYY-MM-DD。');
  const date = new Date(value + 'T00:00:00Z');
  if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== value) throw new Error('日期不存在。'); return value;
}
export function readJourneyPlaceSource(value: unknown, expectedId: string): JourneyPlaceSource {
  const row = object(value), plan = object(row.plan); if (id(row.id) !== id(expectedId)) throw new Error('旅行已变化，请重新打开。');
  const start = day(plan.start)!, end = day(plan.end)!;
  if (end < start || !Array.isArray(plan.destinations) || !plan.destinations.length || plan.destinations.length > 20) throw new Error('旅行日期或目的地无法核对。');
  const seen = new Set<string>();
  const destinations = plan.destinations.map(value => {
    const item = object(value), key = text(item.key, 64), arrival = day(item.arrival)!, departure = day(item.departure)!;
    if (!/^[A-Za-z0-9_-]+$/.test(key) || seen.has(key) || arrival < start || departure > end || departure < arrival) throw new Error('旅行目的地或停留日期无法核对。');
    seen.add(key); return { key, country: text(item.country, 60, true), city: text(item.city, 80), arrival, departure };
  });
  return { id: row.id as string, tripId: id(row.tripId), revision: revision(row.revision), title: text(plan.title, 100), destinations };
}
export function destinationEditor(source: JourneyPlaceSource, key: string): JourneyPlaceEditor {
  const stop = source.destinations.find(item => item.key === key); if (!stop) throw new Error('这个目的地已移出旅行，请重新核对。');
  return { sourceRevision: source.revision, destinationKey: key, original: null, draft: { name: stop.city, country: stop.country, city: stop.city,
    latitude: '', longitude: '', status: 'planned', visibility: 'private', coordinateDisclosure: 'hidden', startDate: stop.arrival, endDate: stop.departure, journeyId: source.id, confirmed: false } };
}
export function journeyPlacePayload(editor: JourneyPlaceEditor, source: JourneyPlaceSource): Record<string, unknown> {
  const draft = editor.draft;
  if (editor.sourceRevision !== source.revision || draft.journeyId !== source.id) throw new Error('旅行计划已变化，请核对最新旅行。');
  if (editor.destinationKey && !source.destinations.some(stop => stop.key === editor.destinationKey)) throw new Error('这个目的地已移出旅行，请重新选择。');
  if (editor.original && (!editor.original.canManage || draft.id !== editor.original.id || editor.original.journeyId !== source.id)) throw new Error('请重新打开本人地点。');
  if (draft.status !== (editor.original?.status || 'planned')) throw new Error('此入口不能自动改变到访状态。');
  if (!['private', 'shared'].includes(draft.visibility) || !['hidden', 'coarse', 'exact'].includes(draft.coordinateDisclosure) || typeof draft.confirmed !== 'boolean') throw new Error('请核对共享与到访设置。');
  const name = text(draft.name, 160), country = text(draft.country, 100, true), city = text(draft.city, 100, true);
  const latitude = draft.latitude.trim(), longitude = draft.longitude.trim(); let coordinates: { latitude: number; longitude: number } | null = null;
  if (latitude || longitude) {
    const decimal = /^[+-]?(?:\d+(?:\.\d{1,6})?|\.\d{1,6})$/;
    if (!decimal.test(latitude) || !decimal.test(longitude)) throw new Error('经纬度须成对填写，最多六位小数。');
    coordinates = { latitude: Number(latitude), longitude: Number(longitude) };
    if (!Number.isFinite(coordinates.latitude) || !Number.isFinite(coordinates.longitude) || Math.abs(coordinates.latitude) > 90 || Math.abs(coordinates.longitude) > 180) throw new Error('坐标超出范围。');
  }
  const startDate = day(draft.startDate, true), endDate = day(draft.endDate, true);
  if (endDate && (!startDate || endDate < startDate)) throw new Error('结束日期须不早于开始日期。');
  const value = { name, country, city, coordinates, status: draft.status, visibility: draft.visibility, coordinateDisclosure: draft.coordinateDisclosure, startDate, endDate, journeyId: source.id };
  const original = editor.original;
  if (draft.status === 'visited' && (!original || ['name', 'country', 'city', 'startDate', 'endDate', 'journeyId'].some(key => value[key as keyof typeof value] !== original[key as keyof Place])
    || JSON.stringify(coordinates) !== JSON.stringify(original.coordinates)) && !draft.confirmed) throw new Error('请明确确认修改后的地点与日期确实到访。');
  return { ...value, confirmVisited: draft.status === 'visited' && draft.confirmed, expectedJourneyRevision: revision(editor.sourceRevision), ...(original ? { revision: revision(original.revision) } : {}) };
}
export function journeyPlaceView(journeyId: string, selected?: string, offset = 0): MapView {
  if (!Number.isSafeInteger(offset) || offset < 0 || offset > 3000) throw new Error('地点页码无法核对。');
  return { filters: { scope: 'visible', status: '', year: '', owner: '', journeyId: id(journeyId) }, offset, ...(selected ? { selected: id(selected) } : {}) };
}
export class PlaceWriteRejected extends Error {
  constructor(readonly status: number, message: string) { super(message); }
}
export class PlaceWriteUnverified extends Error {
  constructor(readonly reason: unknown) { super('地点写入前后的身份暂时无法核对。'); }
}
type MutationOutcome<T> = { ok: true; value: T } | { ok: false; failure: unknown };
/** Only a mutation rejection that survives BOTH identity checks is definitive. */
export async function checkedPlaceMutation<T>(
  guard: <R>(action: (csrf: string) => Promise<R>) => Promise<R>,
  action: (csrf: string) => Promise<T>,
  httpStatus: (failure: unknown) => number | undefined,
): Promise<T> {
  let outcome: MutationOutcome<T>;
  try {
    outcome = await guard(async csrf => {
      try { return { ok: true as const, value: await action(csrf) }; }
      catch (failure) { return { ok: false as const, failure }; }
    });
  } catch (reason) { throw new PlaceWriteUnverified(reason); }
  if (outcome.ok) return outcome.value;
  const status = httpStatus(outcome.failure);
  if (status !== undefined && [400, 403, 404, 409, 410, 413, 415, 422, 429].includes(status)) {
    throw new PlaceWriteRejected(status, outcome.failure instanceof Error ? outcome.failure.message : '地点保存被拒绝。');
  }
  throw outcome.failure;
}
// A later HTTP rejection cannot disprove an earlier request with no response.
// Raw HTTP errors may come from /me, so they NEVER unlock a new create intent.
export function failedPlaceIntent(intent: PlaceIntent, failure: unknown): PlaceIntent {
  const uncertain = intent.uncertain || !(failure instanceof PlaceWriteRejected);
  return { ...intent, uncertain, state: uncertain ? 'unknown' : 'rejected' };
}
export function placeReadbackNeedsConceal(failure: unknown, identityFailure: boolean): boolean {
  return identityFailure || !!failure && typeof failure === 'object' && 'status' in failure && [401, 403].includes(Number(failure.status));
}
