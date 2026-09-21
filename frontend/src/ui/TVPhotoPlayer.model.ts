import { readJourneyScope, journeyCanStart, type JourneyReview } from '../lib/tvTripRecap.ts';
export type TVPhotoPlayerProps = { deviceId: string; active: boolean; onUnauthorized: () => void };
export type TVPhoto = { id: string; revision: number; width: number; height: number; previewUrl: string;
  mediaType?: 'photo' | 'video'; videoUrl?: string; durationMs?: number; hasAudio?: boolean };
export type TVPlayback = {
  scope?: 'all' | 'journey'; journeyReview?: JourneyReview | null;
  deviceId: string; revision: number; mode: 'dashboard' | 'photos'; paused: boolean;
  intervalSeconds: number; position: number; photoCount: number; canStart: boolean;
  updatedAt: string | null; serverTime: string; validUntil: string; item: TVPhoto | null;
  protocol?: 2; playbackCsrf?: string; progress?: { playId: string; positionMs: number; sequence: number; durationMs: number } | null;
};
export const TV_PHOTO_POLL_MS = 2000;
export const TV_PHOTO_TIMEOUT_MS = 5000;
export const TV_PHOTO_MAX_LEASE_MS = 15000;
export const TV_PHOTO_MAX_BYTES = 2 * 1024 * 1024;
export const TV_VIDEO_MAX_BYTES = 64 * 1024 * 1024;
export const isTVPhotoId = (value: unknown): value is string => typeof value === 'string' && /^[0-9a-f]{24}$/.test(value);
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const integer = (value: unknown, low: number, high: number): value is number => Number.isSafeInteger(value) && Number(value) >= low && Number(value) <= high;
export class TVPhotoIdentityChanged extends Error {}

function instant(value: unknown): number {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value)) throw new Error('Invalid display time');
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed) || new Date(parsed).toISOString().slice(0, 19) !== value.slice(0, 19)) throw new Error('Invalid display time');
  return parsed;
}

/** Project only the TV DTO; never retain account, owner, filename or arbitrary URLs. */
export function readTVPlayback(value: unknown, deviceId: string): TVPlayback {
  if (!isTVPhotoId(deviceId) || !record(value)) throw new Error('Invalid display state');
  if (value.deviceId !== deviceId) throw new TVPhotoIdentityChanged('Display identity changed');
  const scope = readJourneyScope(value);
  if (!integer(value.revision, 0, Number.MAX_SAFE_INTEGER) || (value.mode !== 'dashboard' && value.mode !== 'photos')
    || typeof value.paused !== 'boolean' || !integer(value.intervalSeconds, 5, 120)
    || !integer(value.photoCount, 0, 2000) || !integer(value.position, 0, Math.max(0, value.photoCount - 1))
    || typeof value.canStart !== 'boolean' || value.canStart !== journeyCanStart(scope.journeyReview, value.photoCount)) throw new Error('Invalid display state');
  instant(value.serverTime); instant(value.validUntil);
  if (value.updatedAt !== null) instant(value.updatedAt);
  if (value.mode === 'dashboard' && (value.photoCount !== 0 || value.item !== null)) throw new Error('Invalid dashboard state');
  let item: TVPhoto | null = null;
  if (value.photoCount === 0) {
    if (value.item !== null) throw new Error('Unexpected display image');
  } else {
    const row = value.item;
    if (!record(row) || !isTVPhotoId(row.id) || !integer(row.revision, 1, Number.MAX_SAFE_INTEGER)
      || !integer(row.width, 1, 1600) || !integer(row.height, 1, 1600)
      || row.previewUrl !== '/api/media-tv/items/' + row.id + '/preview') throw new Error('Invalid display image');
    item = { id: row.id, revision: row.revision, width: row.width, height: row.height, previewUrl: row.previewUrl };
    if (row.mediaType !== undefined) {
      if (row.mediaType !== 'photo' && row.mediaType !== 'video') throw new Error('Invalid media type');
      item.mediaType = row.mediaType;
      if (row.mediaType === 'video') {
        if (row.videoUrl !== '/api/media-tv/items/' + row.id + '/video' || !integer(row.durationMs, 1, 600250)
          || typeof row.hasAudio !== 'boolean' || row.width > 1280 || row.height > 1280) throw new Error('Invalid video');
        Object.assign(item, { videoUrl: row.videoUrl, durationMs: row.durationMs, hasAudio: row.hasAudio });
      }
    }
  }
  const result: TVPlayback = { ...scope, deviceId, revision: value.revision, mode: value.mode as TVPlayback['mode'], paused: value.paused,
    intervalSeconds: value.intervalSeconds, position: value.position, photoCount: value.photoCount,
    canStart: value.canStart, updatedAt: value.updatedAt as string | null, serverTime: value.serverTime as string,
    validUntil: value.validUntil as string, item };
  if (value.protocol !== undefined) {
    if (value.protocol !== 2 || typeof value.playbackCsrf !== 'string' || !/^\d{1,16}\.\d{1,16}\.[0-9a-f]{64}$/.test(value.playbackCsrf)) throw new Error('Invalid playback protocol');
    result.protocol = 2; result.playbackCsrf = value.playbackCsrf;
    if (item) {
      const p = value.progress, duration = item.mediaType === 'video' ? item.durationMs! : value.intervalSeconds * 1000;
      if (!record(p) || !isTVPhotoId(p.playId) || !integer(p.sequence, 0, Number.MAX_SAFE_INTEGER - 1)
        || p.durationMs !== duration || !integer(p.positionMs, 0, duration)) throw new Error('Invalid playback progress');
      result.progress = { playId: p.playId, positionMs: p.positionMs, sequence: p.sequence, durationMs: duration };
    } else {
      if (value.progress !== null) throw new Error('Unexpected progress');
      result.progress = null;
    }
  }
  return result;
}

export type TVProgressEvent = 'ready' | 'checkpoint' | 'paused' | 'ended';
export type TVProgressIntent = { revision: number; playId: string; itemId: string; itemRevision: number;
  sequence: number; positionMs: number; event: TVProgressEvent };
export function progressIntent(value: TVPlayback, event: TVProgressEvent, position: number): TVProgressIntent {
  if (value.protocol !== 2 || !value.progress || !value.item || !value.playbackCsrf
    || !integer(position, 0, value.progress.durationMs)) throw new Error('Progress unavailable');
  return { revision: value.revision, playId: value.progress.playId, itemId: value.item.id, itemRevision: value.item.revision,
    sequence: value.progress.sequence + 1, positionMs: position, event };
}

/** Only a newer committed state resolves an unknown report; no blind POST replay. */
export function reportResolved(intent: TVProgressIntent, state: TVPlayback): boolean {
  return state.revision > intent.revision || !state.progress || state.progress.playId !== intent.playId
    || state.progress.sequence >= intent.sequence;
}

/** Accumulate actual visible photo time, excluding decode, waiting and pause. */
export class TVMediaClock {
  private position = 0;
  private previous: number | null = null;
  reset(position = 0) { this.position = position; this.previous = null; }
  sample(now: number, displaying: boolean, duration: number): number {
    if (!Number.isFinite(now) || now < 0 || !integer(duration, 1, 600250)) throw new Error('Invalid clock');
    if (displaying && this.previous !== null) this.position = Math.min(duration, this.position + Math.max(0, now - this.previous));
    this.previous = displaying ? now : null;
    return Math.floor(Math.min(duration, this.position));
  }
}

/** The wall clock is not an authority: deduct all request/decode time from this lease. */
export function photoDeadline(value: TVPlayback, requestStarted: number, now: number): number {
  const duration = instant(value.validUntil) - instant(value.serverTime);
  if (!Number.isFinite(requestStarted) || requestStarted < 0 || !Number.isFinite(now) || now < requestStarted
    || duration <= 0 || duration > TV_PHOTO_MAX_LEASE_MS || now >= requestStarted + duration) throw new Error('Expired display lease');
  return requestStarted + duration;
}

/** A lifecycle change invalidates all outstanding responses, including decoders ignoring abort. */
export class TVPhotoLease {
  private generation = 0;
  private deadline = 0;
  private revision = -1;
  ticket() { return this.generation; }
  current(ticket: number) { return ticket === this.generation; }
  clear() { this.generation += 1; this.deadline = 0; }
  accept(ticket: number, value: TVPlayback, started: number, now: number) {
    if (!this.current(ticket) || value.revision < this.revision) throw new Error('Stale display state');
    const next = photoDeadline(value, started, now);
    this.deadline = next; this.revision = value.revision;
  }
  valid(ticket: number, now: number) {
    return this.current(ticket) && Number.isFinite(now) && now >= 0 && now < this.deadline;
  }
  expired(now: number) { return this.deadline > 0 && now >= this.deadline; }
}
