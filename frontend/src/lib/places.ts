import { sessionIdentity } from './sessionIdentity.ts';
import type { Member } from './types';

export type Coordinates = { latitude: number; longitude: number };
export type MapFilters = { scope: string; status: string; year: string; owner: string; journeyId: string };
export type MapView = { filters: MapFilters; offset: number; selected?: string };
export type Place = {
  id: string; owner: string; name: string; country: string; city: string;
  coordinates: Coordinates | null; coordinatePrecision: 'exact' | 'approximate' | 'hidden' | 'none';
  coordinateGridDegrees: number | null; coordinateDisclosure: 'hidden' | 'coarse' | 'exact';
  sharedCoordinates?: Coordinates | null; sharedCoordinatePrecision?: string;
  status: 'visited' | 'planned' | 'wish'; visibility: 'private' | 'shared';
  journeyId: string | null; journey: { id: string; tripId: string; title: string } | null;
  startDate: string | null; endDate: string | null; revision: number; canManage: boolean;
  visitedConfirmedAt: string | null; visitedConfirmedBy: string | null; createdAt: string; updatedAt: string;
};
export type PlacePage = { items: Place[]; total: number; offset: number; limit: number; hasMore: boolean };
export type PlaceDraft = {
  id?: string; name: string; country: string; city: string; latitude: string; longitude: string;
  status: Place['status']; visibility: Place['visibility']; coordinateDisclosure: Place['coordinateDisclosure'];
  startDate: string; endDate: string; journeyId: string; confirmed: boolean;
};
export type PlaceSession = { user: Member | null; csrf?: string | null };
export const placeLabels = { visited: '已到访', planned: '已计划', wish: '想去' };
export const emptyFilters = (): MapFilters => ({ scope: 'visible', status: '', year: '', owner: '', journeyId: '' });
export const emptyPlacePage = (): PlacePage => ({ items: [], total: 0, offset: 0, limit: 24, hasMore: false });
export const isPlaceId = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{24}$/.test(value);
export function coordinatesValid(value: unknown): value is Coordinates {
  if (!value || typeof value !== 'object') return false;
  const point = value as Coordinates;
  return Number.isFinite(point.latitude) && Math.abs(point.latitude) <= 90 && Number.isFinite(point.longitude) && Math.abs(point.longitude) <= 180;
}
const invalid = () => new Error('地点数据无法核对，请重新读取。');
export function validatePlace(value: Place): Place {
  if (!value || !isPlaceId(value.id) || !Number.isSafeInteger(value.revision) || value.revision < 1
    || !['name', 'country', 'city', 'owner', 'createdAt', 'updatedAt'].every(key => typeof value[key as keyof Place] === 'string')
    || !Object.hasOwn(placeLabels, value.status) || !['private', 'shared'].includes(value.visibility)
    || !['hidden', 'coarse', 'exact'].includes(value.coordinateDisclosure) || typeof value.canManage !== 'boolean'
    || !['exact', 'approximate', 'hidden', 'none'].includes(value.coordinatePrecision)
    || value.coordinates !== null && !coordinatesValid(value.coordinates)
    || value.journeyId !== null && !isPlaceId(value.journeyId)
    || value.journeyId === null && value.journey !== null
    || value.journeyId !== null && (!value.journey || value.journey.id !== value.journeyId || !isPlaceId(value.journey.tripId) || typeof value.journey.title !== 'string')) throw invalid();
  return value;
}
export function validatePlacePage(value: PlacePage, offset: number): PlacePage {
  if (!value || !Array.isArray(value.items) || value.items.length > 24 || value.limit !== 24 || value.offset !== offset
    || !Number.isSafeInteger(value.total) || value.total < 0 || typeof value.hasMore !== 'boolean') throw invalid();
  value.items.forEach(validatePlace); return value;
}
export function safeMapView(value?: MapView): MapView {
  const filters = emptyFilters();
  if (value?.filters) {
    if (['visible', 'mine', 'shared'].includes(value.filters.scope)) filters.scope = value.filters.scope;
    if (Object.hasOwn(placeLabels, value.filters.status)) filters.status = value.filters.status;
    if (/^\d{4}$/.test(value.filters.year) && Number(value.filters.year) > 0) filters.year = value.filters.year;
    if (typeof value.filters.owner === 'string' && value.filters.owner.length <= 100) filters.owner = value.filters.owner;
    if (isPlaceId(value.filters.journeyId)) filters.journeyId = value.filters.journeyId;
  }
  return { filters, offset: value && Number.isSafeInteger(value.offset) && value.offset >= 0 && value.offset <= 3000 ? value.offset : 0,
    ...(isPlaceId(value?.selected) ? { selected: value.selected } : {}) };
}
export const placeQuery = (filters: MapFilters, offset: number) => {
  const query = new URLSearchParams({ limit: '24', offset: String(offset) });
  Object.entries(filters).forEach(([key, value]) => { if (value) query.set(key, value); }); return query.toString();
};
export function placeDraft(place?: Place): PlaceDraft {
  return { ...(place ? { id: place.id } : {}), name: place?.name || '', country: place?.country || '', city: place?.city || '',
    latitude: place?.coordinates ? String(place.coordinates.latitude) : '', longitude: place?.coordinates ? String(place.coordinates.longitude) : '',
    status: place?.status || 'wish', visibility: place?.visibility || 'private', coordinateDisclosure: place?.coordinateDisclosure || 'hidden',
    startDate: place?.startDate || '', endDate: place?.endDate || '', journeyId: place?.journeyId || '', confirmed: false };
}
function dateInput(value: string): string | null {
  const trimmed = value.trim(); if (!trimmed) return null;
  const date = new Date(trimmed + 'T12:00:00Z');
  if (!/^\d{4}-\d{2}-\d{2}$/.test(trimmed) || !Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== trimmed) throw new Error('日期请填写有效的 YYYY-MM-DD。');
  return trimmed;
}
export function placePayload(draft: PlaceDraft, original?: Place | null): Record<string, unknown> {
  const name = draft.name.trim(), country = draft.country.trim(), city = draft.city.trim();
  if (!name || name.length > 160 || country.length > 100 || city.length > 100) throw new Error('请填写地点名称（最多 160 字），国家和城市最多 100 字。');
  const lat = draft.latitude.trim(), lng = draft.longitude.trim();
  let coordinates: Coordinates | null = null;
  if (lat || lng) {
    const decimal = /^[+-]?(?:\d+(?:\.\d{1,6})?|\.\d{1,6})$/;
    if (!decimal.test(lat) || !decimal.test(lng)) throw new Error('经纬度须成对填写，最多六位小数。');
    coordinates = { latitude: Number(lat), longitude: Number(lng) };
    if (!coordinatesValid(coordinates)) throw new Error('纬度范围为 -90 到 90，经度范围为 -180 到 180。');
  }
  const startDate = dateInput(draft.startDate), endDate = dateInput(draft.endDate);
  if (endDate && (!startDate || endDate < startDate)) throw new Error('结束日期须不早于开始日期。');
  if (draft.journeyId && !isPlaceId(draft.journeyId)) throw new Error('请重新选择关联旅行。');
  const value = { name, country, city, coordinates, status: draft.status, visibility: draft.visibility, coordinateDisclosure: draft.coordinateDisclosure,
    startDate, endDate, journeyId: draft.journeyId || null };
  const changedVisit = !original || original.status !== 'visited' || ['name', 'country', 'city', 'startDate', 'endDate', 'journeyId'].some(key => value[key as keyof typeof value] !== original[key as keyof Place])
    || JSON.stringify(coordinates) !== JSON.stringify(original.coordinates);
  if (draft.status === 'visited' && changedVisit && !draft.confirmed) throw new Error('请先明确确认实际到访；日期或照片不会自动证明到访。');
  return { ...value, confirmVisited: draft.status === 'visited' && draft.confirmed };
}
export const placeSignature = sessionIdentity;
export class PlaceDiscarded extends Error {}
export class PlaceFence {
  private epoch = 0;
  constructor(private me: () => Promise<PlaceSession>, private expected: string) {}
  invalidate() { ++this.epoch; }
  async run<T>(action: (csrf: string) => Promise<T>, current: () => boolean): Promise<T> {
    const epoch = this.epoch;
    const check = (session: PlaceSession) => {
      if (!current() || epoch !== this.epoch) throw new PlaceDiscarded();
      if (session.user?.role !== 'member' || !session.csrf || placeSignature(session) !== this.expected) throw new PlaceDiscarded('identity');
      return session.csrf;
    };
    const csrf = check(await this.me()); let value!: T, failure: unknown, failed = false;
    try { value = await action(csrf); } catch (caught) { failed = true; failure = caught; }
    check(await this.me()); if (failed) throw failure; return value;
  }
}

// The public world outline is bounded and validated before building SVG paths.
// User coordinates never enter these paths or a public cache.
export function landPaths(value: unknown): string[] {
  const data = value as { type?: string; features?: { type?: string; geometry?: { type?: string; coordinates?: unknown[] } }[] };
  if (data?.type !== 'FeatureCollection' || !Array.isArray(data.features) || data.features.length > 500) throw new Error('底图格式不正确');
  let vertices = 0;
  return data.features.flatMap(feature => {
    const geometry = feature.geometry;
    if (feature.type !== 'Feature' || !geometry || !['Polygon', 'MultiPolygon'].includes(geometry.type || '') || !Array.isArray(geometry.coordinates)) throw new Error('底图格式不正确');
    const polygons = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates;
    return polygons.map(polygon => {
      if (!Array.isArray(polygon)) throw new Error('底图格式不正确');
      return polygon.map(ring => {
        if (!Array.isArray(ring) || ring.length < 4) throw new Error('底图格式不正确');
        const points = ring.map((point: unknown, index: number) => {
          if (!Array.isArray(point) || point.length !== 2 || !coordinatesValid({ longitude: point[0], latitude: point[1] }) || ++vertices > 20000) throw new Error('底图坐标不正确');
          return `${index ? 'L' : 'M'}${((point[0] + 180) * 1000 / 360).toFixed(2)},${((90 - point[1]) * 500 / 180).toFixed(2)}`;
        });
        if (JSON.stringify(ring[0]) !== JSON.stringify(ring[ring.length - 1])) throw new Error('底图轮廓未闭合');
        return points.join(' ') + 'Z';
      }).join(' ');
    });
  });
}
