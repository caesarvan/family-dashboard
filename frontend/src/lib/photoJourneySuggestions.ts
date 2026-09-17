import { isMediaId, validatePhoto } from './photos';
import type { Photo } from './photos';

export type PhotoJourneySuggestion = {
  journeyId: string; journeyRevision: number; tripRevision: number;
  title: string; start: string; end: string;
  referenceTimezone: string; referenceTimezoneSource: 'legacy_default' | 'plan';
  sourceDate: string; alreadyLinked: boolean;
  reason: { code: 'date_overlap'; message: string };
};
export type PhotoJourneySuggestions = {
  photoId: string; photoRevision: number;
  sourceTimeState: 'known' | 'unknown'; sourceCreatedAt: string | null;
  currentJourneyId: string | null; suggestions: PhotoJourneySuggestion[];
  limit: 20; hasMore: boolean;
  reason: { code: 'date_overlap' | 'source_time_unknown' | 'no_matching_journeys'; message: string };
};

const invalid = (): never => { throw new Error('照片或旅行建议已变化，请重新读取后核对。'); };
function object(raw: unknown, fields: string[]): Record<string, unknown> {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return invalid();
  const value = raw as Record<string, unknown>, keys = Object.keys(value);
  if (keys.length !== fields.length || fields.some(k => !Object.hasOwn(value, k))) return invalid();
  return value;
}
function text(raw: unknown, max: number): string {
  if (typeof raw !== 'string' || raw.length > max) return invalid();
  return raw;
}
function revision(raw: unknown): number {
  if (typeof raw !== 'number' || !Number.isSafeInteger(raw) || raw < 1) return invalid();
  return raw;
}
function id(raw: unknown): string { return isMediaId(raw) ? raw : invalid(); }
function boolean(raw: unknown): boolean { return typeof raw === 'boolean' ? raw : invalid(); }
function date(raw: unknown): string {
  if (typeof raw !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(raw)) return invalid();
  const [y, m, d] = raw.split('-').map(Number);
  const days = [31, y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (y < 1 || m < 1 || m > 12 || d < 1 || d > days[m - 1]) return invalid();
  return raw;
}
function sourceInstant(raw: unknown): string {
  if (typeof raw !== 'string' || !/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,9})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.test(raw)) return invalid();
  date(raw.slice(0, 10));
  // Keep original nanoseconds and offset; only the server calculates sourceDate.
  return raw;
}
function reason<C extends PhotoJourneySuggestions['reason']['code']>(raw: unknown, code: C): { code: C; message: string } {
  const r = object(raw, ['code', 'message']);
  if (r.code !== code) return invalid();
  return { code, message: text(r.message, 1000) };
}

export function readPhotoJourneySuggestions(raw: unknown, photo: Photo): PhotoJourneySuggestions {
  validatePhoto(photo);
  if (!photo.canManage || (photo.journey !== null && (!photo.journey || !isMediaId(photo.journey.id) || !isMediaId(photo.journey.tripId)))) return invalid();
  const v = object(raw, ['photoId', 'photoRevision', 'sourceTimeState', 'sourceCreatedAt', 'currentJourneyId', 'suggestions', 'limit', 'hasMore', 'reason']);
  const photoId = id(v.photoId), photoRevision = revision(v.photoRevision);
  const currentJourneyId = v.currentJourneyId === null ? null : id(v.currentJourneyId);
  if (photoId !== photo.id || photoRevision !== photo.revision || currentJourneyId !== (photo.journey?.id ?? null)
    || v.limit !== 20 || !Array.isArray(v.suggestions) || v.suggestions.length > 20) return invalid();
  if (v.sourceTimeState !== 'known' && v.sourceTimeState !== 'unknown') return invalid();
  const sourceTimeState = v.sourceTimeState;
  const sourceCreatedAt = sourceTimeState === 'known' ? sourceInstant(v.sourceCreatedAt) : v.sourceCreatedAt === null ? null : invalid();
  // Current owner DTOs carry both fields. Older Photo types may omit both.
  const origin = photo as Photo & { sourceCreatedAt?: unknown; sourceTimeState?: unknown };
  if (Object.hasOwn(origin, 'sourceCreatedAt') || Object.hasOwn(origin, 'sourceTimeState')) {
    if (origin.sourceCreatedAt !== sourceCreatedAt || origin.sourceTimeState !== sourceTimeState) return invalid();
  }
  const hasMore = boolean(v.hasMore), seen = new Set<string>();
  const suggestions = v.suggestions.map(rawRow => {
    const row = object(rawRow, ['journeyId', 'journeyRevision', 'tripRevision', 'title', 'start', 'end', 'referenceTimezone', 'referenceTimezoneSource', 'sourceDate', 'alreadyLinked', 'reason']);
    const journeyId = id(row.journeyId), start = date(row.start), end = date(row.end), sourceDate = date(row.sourceDate);
    const referenceTimezone = text(row.referenceTimezone, 100);
    const referenceTimezoneSource = row.referenceTimezoneSource;
    if (seen.has(journeyId) || start > sourceDate || sourceDate > end
      || !/^[A-Za-z0-9_+.-]+(?:\/[A-Za-z0-9_+.-]+)*$/.test(referenceTimezone)
      || (referenceTimezoneSource !== 'plan' && referenceTimezoneSource !== 'legacy_default')
      || (referenceTimezoneSource === 'legacy_default' && referenceTimezone !== 'Asia/Shanghai')) return invalid();
    seen.add(journeyId);
    const alreadyLinked = boolean(row.alreadyLinked);
    if (alreadyLinked !== (journeyId === currentJourneyId)) return invalid();
    return { journeyId, journeyRevision: revision(row.journeyRevision), tripRevision: revision(row.tripRevision),
      title: text(row.title, 500), start, end, referenceTimezone,
      referenceTimezoneSource: referenceTimezoneSource as 'plan' | 'legacy_default', sourceDate, alreadyLinked,
      reason: reason(row.reason, 'date_overlap') };
  });
  if ((hasMore && suggestions.length !== 20) || (sourceTimeState === 'unknown' && (suggestions.length || hasMore))) return invalid();
  const code = sourceTimeState === 'unknown' ? 'source_time_unknown' : suggestions.length ? 'date_overlap' : 'no_matching_journeys';
  return { photoId, photoRevision, sourceTimeState, sourceCreatedAt, currentJourneyId, suggestions, limit: 20, hasMore, reason: reason(v.reason, code) };
}

export function photoSuggestionBody(photo: Photo, suggestions: PhotoJourneySuggestions, journeyId: string): {
  revision: number; journeyId: string; expectedJourneyRevision: number; expectedTripRevision: number;
} {
  const current = readPhotoJourneySuggestions(suggestions, photo);
  const row = current.suggestions.find(value => value.journeyId === id(journeyId));
  if (!row || row.alreadyLinked) throw new Error('请先选择尚未关联的旅行建议。');
  return { revision: current.photoRevision, journeyId: row.journeyId,
    expectedJourneyRevision: row.journeyRevision, expectedTripRevision: row.tripRevision };
}
