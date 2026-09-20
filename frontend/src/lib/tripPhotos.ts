import { isMediaId, validatePhoto } from './photos';
import type { Photo } from './photos';

export type TripPhotoScope = 'visible' | 'mine' | 'shared';
export type TripPhotoPage = { items: Photo[]; total: number; offset: number; limit: 24; hasMore: boolean };
export type TripPhotoJourney = { id: string; tripId: string; title: string };
const fail = () => new Error('旅行相册已变化，请重新读取。');
const record = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw fail();
  return value as Record<string, unknown>;
};
const title = (value: unknown): string => {
  if (typeof value !== 'string' || !value.trim() || value.length > 500) throw fail();
  return value;
};

// Keep only the travel caption used here, not budgets, tasks or other fields
// returned by the workflow detail endpoint.
export function readTripPhotoJourney(value: unknown, journeyId: string): TripPhotoJourney {
  const row = record(value);
  if (!isMediaId(journeyId) || row.id !== journeyId || !isMediaId(row.tripId)) throw fail();
  const trip = row.trip == null ? null : record(row.trip);
  if (trip && trip.id !== row.tripId) throw fail();
  return { id: journeyId, tripId: row.tripId, title: title(trip ? trip.title : record(row.plan).title) };
}

export function readTripPhoto(value: unknown, journeyId: string, expectedId?: string): Photo {
  const row = record(value);
  validatePhoto(row as Photo);
  if (!isMediaId(journeyId) || expectedId && row.id !== expectedId) throw fail();
  const journey = record(row.journey);
  if (journey.id !== journeyId || !isMediaId(journey.tripId)
    || !Number.isSafeInteger(row.width) || Number(row.width) < 1
    || !Number.isSafeInteger(row.height) || Number(row.height) < 1
    || Number(row.width) * Number(row.height) > 20000000
    || typeof row.createdAt !== 'string' || !Number.isFinite(Date.parse(row.createdAt))) throw fail();
  // Source filenames, provider account IDs and source timestamps are not part
  // of this read-only projection, even when the current member owns the photo.
  return {
    id: row.id as string, revision: row.revision as number, caption: row.caption as string,
    width: row.width as number, height: row.height as number, previewUrl: row.previewUrl as string,
    visibility: row.visibility as Photo['visibility'], canManage: row.canManage as boolean,
    createdAt: row.createdAt,
    ...(row.mediaType === 'video' ? { mediaType: 'video' as const, durationMs: row.durationMs as number,
      hasAudio: row.hasAudio as boolean, videoUrl: row.videoUrl as string } : row.mediaType === 'photo' ? { mediaType: 'photo' as const } : {}),
    journey: { id: journeyId, tripId: journey.tripId, title: title(journey.title) },
  };
}

export function tripPhotoQuery(journeyId: string, scope: TripPhotoScope, offset: number): string {
  if (!isMediaId(journeyId) || !['visible', 'mine', 'shared'].includes(scope)
    || !Number.isSafeInteger(offset) || offset < 0 || offset > 4000 || offset % 24) throw fail();
  return `/media/items?scope=${scope}&journeyId=${journeyId}&limit=24&offset=${offset}`;
}

export function readTripPhotoPage(value: unknown, journeyId: string, offset: number): TripPhotoPage {
  tripPhotoQuery(journeyId, 'visible', offset);
  const row = record(value);
  if (!Array.isArray(row.items) || row.items.length > 24 || row.limit !== 24 || row.offset !== offset
    || !Number.isSafeInteger(row.total) || Number(row.total) < 0 || typeof row.hasMore !== 'boolean'
    || row.items.length !== Math.min(24, Math.max(0, Number(row.total) - offset))
    || row.hasMore !== (offset + 24 < Number(row.total))) throw fail();
  const items = row.items.map(value => readTripPhoto(value, journeyId));
  if (new Set(items.map(item => item.id)).size !== items.length) throw fail();
  return { items, total: row.total as number, limit: 24, offset, hasMore: row.hasMore };
}
