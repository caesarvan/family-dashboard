import type { Photo } from './photos.ts';

// A calendar date, never an instant: Date/UTC conversion changes this meaning.
export function isConfirmedDate(value: unknown): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [y, m, d] = value.split('-').map(Number);
  const days = [31, y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return y >= 1 && m >= 1 && m <= 12 && d >= 1 && d <= days[m - 1];
}
// Only used in saved-photo detail. The server also verifies the sealed source.
export function canConfirmPhotoDate(item: Photo): boolean {
  return item.canManage && item.source === 'local-upload' && item.mediaType !== 'video';
}
export function confirmedDateBody(item: Photo, value: string | null): { revision: number; userConfirmedDate: string | null } {
  if (!canConfirmPhotoDate(item) || !Number.isSafeInteger(item.revision) || item.revision < 1
    || value !== null && !isConfirmedDate(value)) throw new Error('请输入有效日期，格式为 YYYY-MM-DD。');
  return { revision: item.revision, userConfirmedDate: value };
}
