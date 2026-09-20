import { validatePhoto } from './photos.ts';
import type { Photo } from './photos.ts';

export type PhotoMemory = { item: Photo; sourceLocalDate?: string; displayDate?: string; dateBasis?: 'userConfirmedDate' | 'sourceCreatedAt'; yearsAgo: number };
export type PhotoMemories = {
  version?: 2; datePolicy?: 'confirmed-or-source'; unknownEffectiveDateCount?: number;
  referenceDate: string; referenceTimezone: 'Asia/Shanghai'; dateBasis?: 'sourceCreatedAt'; scope: 'mine';
  items: PhotoMemory[]; total: number; limit: 24; offset: number; hasMore: boolean; unknownSourceTimeCount: number;
};
const invalid = (): never => { throw new Error('回看内容已变化，请重新读取。'); };
export const memoryDisplayDate = (row: PhotoMemory): string => row.displayDate ?? row.sourceLocalDate!;
export const memoryDateLabel = (row: PhotoMemory): string => row.dateBasis === 'userConfirmedDate' ? '本人确认日期' : '来源日期';
export const unknownMemoryDates = (page: PhotoMemories): number => page.version === 2 ? page.unknownEffectiveDateCount! : page.unknownSourceTimeCount;
const integer = (v: unknown): v is number => typeof v === 'number' && Number.isSafeInteger(v) && v >= 0;
function date(value: unknown): string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return invalid();
  const [y, m, d] = value.split('-').map(Number);
  const days = [31, y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (!y || m < 1 || m > 12 || d < 1 || d > days[m - 1]) return invalid();
  return value;
}
export function photoMemoriesQuery(offset: number): string {
  if (!integer(offset) || offset > 4000 || offset % 24) return invalid();
  return `/media/memories/on-this-day?limit=24&offset=${offset}&dateMode=confirmed-or-source`;
}
// Retain only the last server date across background concealment. A changed
// day invalidates the old page number even when its photo content was cleared.
export function memoryOffsetAfterDateChange(previousDate: string | null, page: PhotoMemories): number {
  if (previousDate !== null) date(previousDate);
  return previousDate !== null && previousDate !== page.referenceDate ? 0 : page.offset;
}
export function readPhotoMemories(raw: unknown, offset: number): PhotoMemories {
  photoMemoriesQuery(offset);
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return invalid();
  const value = raw as Record<string, unknown>;
  const v2 = value.version === 2;
  if (Object.hasOwn(value, 'version') && !v2) return invalid();
  if (v2 && (Object.keys(value).length !== 12 || !['version', 'datePolicy', 'referenceDate', 'referenceTimezone', 'scope', 'items', 'total', 'limit', 'offset', 'hasMore', 'unknownSourceTimeCount', 'unknownEffectiveDateCount'].every(key => Object.hasOwn(value, key))
    || value.datePolicy !== 'confirmed-or-source' || !integer(value.unknownEffectiveDateCount) || !integer(value.unknownSourceTimeCount) || value.unknownEffectiveDateCount > value.unknownSourceTimeCount)) return invalid();
  const referenceDate = date(value.referenceDate), referenceYear = Number(referenceDate.slice(0, 4));
  if (value.referenceTimezone !== 'Asia/Shanghai' || (!v2 && value.dateBasis !== 'sourceCreatedAt') || value.scope !== 'mine'
    || value.limit !== 24 || value.offset !== offset || !integer(value.total) || !integer(value.unknownSourceTimeCount)
    || !Array.isArray(value.items) || value.items.length !== Math.min(24, Math.max(0, value.total - offset))
    || value.hasMore !== (offset + 24 < value.total)) return invalid();
  const seen = new Set<string>();
  const items = value.items.map((rawItem: unknown): PhotoMemory => {
    if (!rawItem || typeof rawItem !== 'object' || Array.isArray(rawItem)) return invalid();
    const row = rawItem as Record<string, unknown>, item = validatePhoto(row.item as Photo), sourceLocalDate = date(v2 ? row.displayDate : row.sourceLocalDate);
    if (v2 && (Object.keys(row).length !== 4 || !['item', 'displayDate', 'dateBasis', 'yearsAgo'].every(key => Object.hasOwn(row, key))
      || !['sourceCreatedAt', 'userConfirmedDate'].includes(row.dateBasis as string))) return invalid();
    const manual = v2 && row.dateBasis === 'userConfirmedDate';
    if (manual ? item.userConfirmedDate !== sourceLocalDate : v2 && item.userConfirmedDate != null) return invalid();
    const yearsAgo = referenceYear - Number(sourceLocalDate.slice(0, 4));
    if (!item.canManage || item.mediaType === 'video' || !manual && (item.sourceTimeState !== 'known'
      || typeof item.sourceCreatedAt !== 'string' || !Number.isFinite(Date.parse(item.sourceCreatedAt)))
      || sourceLocalDate.slice(5) !== referenceDate.slice(5) || yearsAgo < 1 || row.yearsAgo !== yearsAgo
      || seen.has(item.id)) return invalid();
    seen.add(item.id);
    return manual || v2 ? { item, displayDate: sourceLocalDate, dateBasis: row.dateBasis as 'userConfirmedDate' | 'sourceCreatedAt', yearsAgo } : { item, sourceLocalDate, yearsAgo };
  });
  for (let i = 1; i < items.length; i++) {
    const a = items[i - 1], b = items[i];
    if (memoryDisplayDate(a) < memoryDisplayDate(b) || memoryDisplayDate(a) === memoryDisplayDate(b) && a.item.id >= b.item.id) return invalid();
  }
  return { referenceDate, referenceTimezone: 'Asia/Shanghai', ...(v2 ? { version: 2 as const, datePolicy: 'confirmed-or-source' as const, unknownEffectiveDateCount: value.unknownEffectiveDateCount as number } : { dateBasis: 'sourceCreatedAt' as const }), scope: 'mine',
    items, total: value.total, offset, limit: 24, hasMore: value.hasMore as boolean,
    unknownSourceTimeCount: value.unknownSourceTimeCount };
}
