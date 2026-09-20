import { validatePhoto } from './photos.ts';
import type { Photo } from './photos.ts';

export type PhotoMemory = { item: Photo; sourceLocalDate: string; yearsAgo: number };
export type PhotoMemories = {
  referenceDate: string; referenceTimezone: 'Asia/Shanghai'; dateBasis: 'sourceCreatedAt'; scope: 'mine';
  items: PhotoMemory[]; total: number; limit: 24; offset: number; hasMore: boolean; unknownSourceTimeCount: number;
};
const invalid = (): never => { throw new Error('回看内容已变化，请重新读取。'); };
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
  return `/media/memories/on-this-day?limit=24&offset=${offset}`;
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
  const referenceDate = date(value.referenceDate), referenceYear = Number(referenceDate.slice(0, 4));
  if (value.referenceTimezone !== 'Asia/Shanghai' || value.dateBasis !== 'sourceCreatedAt' || value.scope !== 'mine'
    || value.limit !== 24 || value.offset !== offset || !integer(value.total) || !integer(value.unknownSourceTimeCount)
    || !Array.isArray(value.items) || value.items.length !== Math.min(24, Math.max(0, value.total - offset))
    || value.hasMore !== (offset + 24 < value.total)) return invalid();
  const seen = new Set<string>();
  const items = value.items.map((rawItem: unknown): PhotoMemory => {
    if (!rawItem || typeof rawItem !== 'object' || Array.isArray(rawItem)) return invalid();
    const row = rawItem as Record<string, unknown>, item = validatePhoto(row.item as Photo), sourceLocalDate = date(row.sourceLocalDate);
    const yearsAgo = referenceYear - Number(sourceLocalDate.slice(0, 4));
    if (!item.canManage || item.mediaType === 'video' || item.sourceTimeState !== 'known'
      || typeof item.sourceCreatedAt !== 'string' || !Number.isFinite(Date.parse(item.sourceCreatedAt))
      || sourceLocalDate.slice(5) !== referenceDate.slice(5) || yearsAgo < 1 || row.yearsAgo !== yearsAgo
      || seen.has(item.id)) return invalid();
    seen.add(item.id);
    return { item, sourceLocalDate, yearsAgo };
  });
  for (let i = 1; i < items.length; i++) {
    const a = items[i - 1], b = items[i];
    if (a.sourceLocalDate < b.sourceLocalDate || a.sourceLocalDate === b.sourceLocalDate && a.item.id >= b.item.id) return invalid();
  }
  return { referenceDate, referenceTimezone: 'Asia/Shanghai', dateBasis: 'sourceCreatedAt', scope: 'mine',
    items, total: value.total, offset, limit: 24, hasMore: value.hasMore as boolean,
    unknownSourceTimeCount: value.unknownSourceTimeCount };
}
