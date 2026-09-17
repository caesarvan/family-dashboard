export type TVPhotoPlayerProps = { deviceId: string; active: boolean; onUnauthorized: () => void };
export type TVPhoto = { id: string; revision: number; width: number; height: number; previewUrl: string };
export type TVPlayback = {
  deviceId: string; revision: number; mode: 'dashboard' | 'photos'; paused: boolean;
  intervalSeconds: number; position: number; photoCount: number; canStart: boolean;
  updatedAt: string | null; serverTime: string; validUntil: string; item: TVPhoto | null;
};
export const TV_PHOTO_POLL_MS = 2000;
export const TV_PHOTO_TIMEOUT_MS = 5000;
export const TV_PHOTO_MAX_LEASE_MS = 15000;
export const TV_PHOTO_MAX_BYTES = 2 * 1024 * 1024;
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
  if (!integer(value.revision, 0, Number.MAX_SAFE_INTEGER) || (value.mode !== 'dashboard' && value.mode !== 'photos')
    || typeof value.paused !== 'boolean' || !integer(value.intervalSeconds, 5, 120)
    || !integer(value.photoCount, 0, 2000) || !integer(value.position, 0, Math.max(0, value.photoCount - 1))
    || typeof value.canStart !== 'boolean' || value.canStart !== (value.photoCount > 0)) throw new Error('Invalid display state');
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
  }
  return { deviceId, revision: value.revision, mode: value.mode as TVPlayback['mode'], paused: value.paused,
    intervalSeconds: value.intervalSeconds, position: value.position, photoCount: value.photoCount,
    canStart: value.canStart, updatedAt: value.updatedAt as string | null, serverTime: value.serverTime as string,
    validUntil: value.validUntil as string, item };
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
