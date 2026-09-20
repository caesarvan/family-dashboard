import { isMediaId, validatePhoto, type Photo, type PhotoAccount } from './photos.ts';

export const DUPLICATE_LABEL = '展示副本一致，原图未核验';
export type PhotoDuplicates = {
  photoId: string; photoRevision: number; matchBasis: 'display-copy-sha256'; label: typeof DUPLICATE_LABEL;
  items: Photo[]; total: number; limit: 20; offset: number; hasMore: boolean;
  coverage: { scope: 'mine'; scanLimit: 1000; scanned: number; capped: boolean; unverifiable: number };
};
type Read = <T>(path: string) => Promise<T>;
export class PhotoDuplicatesChanged extends Error {
  constructor() { super('照片或来源已变化，请读取当前照片后重新查找。'); }
}
const invalid = (): never => { throw new PhotoDuplicatesChanged(); };
const integer = (value: unknown, max: number): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 && value <= max;
const source = (item: Photo) => item.source || 'google-photos';
export function duplicatePhotoKey(item: Photo): string {
  validatePhoto(item);
  if (!item.canManage || item.mediaType === 'video'
    || (source(item) === 'local-upload' ? item.accountId !== null : typeof item.accountId !== 'string' || !/^[a-f0-9]{32}$/.test(item.accountId))) return invalid();
  return JSON.stringify([item.id, item.revision, source(item), item.accountId]);
}
export function photoDuplicatesQuery(id: string, offset = 0): string {
  if (!isMediaId(id) || !integer(offset, 4000) || offset % 20) return invalid();
  return `/media/items/${id}/duplicates?limit=20&offset=${offset}`;
}
export function readPhotoDuplicates(raw: unknown, target: Photo, offset: number): PhotoDuplicates {
  duplicatePhotoKey(target); photoDuplicatesQuery(target.id, offset);
  const value = raw as PhotoDuplicates;
  const c = value?.coverage;
  if (!value || value.photoId !== target.id || value.photoRevision !== target.revision
    || value.matchBasis !== 'display-copy-sha256' || value.label !== DUPLICATE_LABEL || value.limit !== 20 || value.offset !== offset
    || !integer(value.total, 1000) || !Array.isArray(value.items) || value.items.length !== Math.min(20, Math.max(0, value.total - offset))
    || value.hasMore !== (offset + 20 < value.total) || !c || c.scope !== 'mine' || c.scanLimit !== 1000
    || !integer(c.scanned, 1000) || !integer(c.unverifiable, 1000) || c.scanned + c.unverifiable > 1000
    || c.scanned < value.total || typeof c.capped !== 'boolean') return invalid();
  let previous = '';
  for (const item of value.items) {
    duplicatePhotoKey(item);
    if (item.id === target.id || item.id <= previous || source(item) === source(target)) return invalid();
    previous = item.id;
  }
  return value;
}
export function duplicateCoverageText(value: PhotoDuplicates): string {
  return (value.coverage.capped || value.coverage.unverifiable ? '仅检查了部分已保存照片。' : '')
    + `已核对 ${value.coverage.scanned} 张本人的已保存照片。`
    + (value.coverage.unverifiable ? `${value.coverage.unverifiable} 张无法核验。` : '')
    + '只比较不同来源；未找到结果也不代表原图不同。';
}
// This is an additional UI invalidation check, never an authority grant. The
// duplicates endpoint and original detail/preview remain the server authority.
export async function verifyDuplicatePhotos(items: readonly Photo[], read: Read): Promise<void> {
  for (const expected of items) {
    const key = duplicatePhotoKey(expected);
    const result = await read<{ item: Photo }>(`/media/items/${expected.id}`);
    if (duplicatePhotoKey(result.item) !== key) return invalid();
  }
  if (items.some(item => source(item) === 'google-photos')) {
    const result = await read<{ accounts: PhotoAccount[] }>('/accounts');
    if (!Array.isArray(result?.accounts)) return invalid();
    for (const item of items) if (source(item) === 'google-photos'
      && !result.accounts.some(account => account.id === item.accountId && account.provider === 'google'
        && account.capabilities?.photos === true && account.needsReauth === false)) return invalid();
  }
}
export async function fetchPhotoDuplicates(target: Photo, offset: number, read: Read): Promise<PhotoDuplicates> {
  await verifyDuplicatePhotos([target], read);
  const page = readPhotoDuplicates(await read(photoDuplicatesQuery(target.id, offset)), target, offset);
  await verifyDuplicatePhotos([target, ...page.items], read);
  return page;
}
