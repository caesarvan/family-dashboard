import assert from 'node:assert/strict';
import { test } from 'node:test';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';
const source = process.env.EXPO_TV_PLAYER_SOURCE_ROOT
  ? pathToFileURL(resolve(process.env.EXPO_TV_PLAYER_SOURCE_ROOT, 'frontend/src/ui/TVPhotoPlayer.model.ts'))
  : new URL('../frontend/src/ui/TVPhotoPlayer.model.ts', import.meta.url);
const { readTVPlayback, photoDeadline, TVPhotoIdentityChanged, TVPhotoLease, TV_PHOTO_MAX_BYTES } = await import(source.href);
const deviceId = 'a'.repeat(24), photoId = 'b'.repeat(24);
const photo = () => ({ id: photoId, revision: 1, width: 1600, height: 900, previewUrl: '/api/media-tv/items/' + photoId + '/preview' });
const state = () => ({ deviceId, revision: 3, mode: 'photos', paused: false, intervalSeconds: 10,
  photoCount: 2, position: 1, canStart: true, updatedAt: '2026-09-17T00:00:00+00:00',
  serverTime: '2026-09-17T00:00:00.123456+00:00', validUntil: '2026-09-17T00:00:15.123456+00:00', item: photo() });

test('TV projection discards member/account/filename metadata and accepts only current device identity', () => {
  const raw = state();
  assert.deepEqual(readTVPlayback({ ...raw, owner: 'private', accountId: 'private', item: { ...raw.item, caption: 'private', displayFilename: 'private' } }, deviceId), raw);
  assert.throws(() => readTVPlayback({ ...raw, deviceId: 'c'.repeat(24) }, deviceId), TVPhotoIdentityChanged);
  for (const input of [null, [], true, 'body']) assert.throws(() => readTVPlayback(input, deviceId));
  assert.throws(() => readTVPlayback(raw, '../device'));
});

test('dashboard and empty photos remain distinct without inventing a photo or position', () => {
  const empty = { ...state(), photoCount: 0, position: 0, canStart: false, item: null };
  assert.equal(readTVPlayback(empty, deviceId).mode, 'photos');
  assert.equal(readTVPlayback({ ...empty, revision: 0, mode: 'dashboard', updatedAt: null }, deviceId).item, null);
  for (const patch of [{ position: 1 }, { item: photo() }, { canStart: true }]) assert.throws(() => readTVPlayback({ ...empty, ...patch }, deviceId));
  assert.throws(() => readTVPlayback({ ...state(), mode: 'dashboard' }, deviceId));
  assert.throws(() => readTVPlayback({ ...state(), item: null }, deviceId));
});

test('state validates booleans, revisions, bounds, known mode and collection position', () => {
  for (const patch of [{ revision: -1 }, { revision: true }, { revision: Number.MAX_SAFE_INTEGER + 1 },
    { mode: 'video' }, { mode: { toString: () => 'photos' } }, { paused: 1 }, { intervalSeconds: 4 },
    { intervalSeconds: 121 }, { photoCount: 2001 }, { position: -1 }, { position: 2 },
    { position: 0.5 }, { canStart: 1 }, { canStart: false }, { updatedAt: undefined }]) {
    assert.throws(() => readTVPlayback({ ...state(), ...patch }, deviceId), JSON.stringify(patch));
  }
  assert.equal(readTVPlayback({ ...state(), paused: true }, deviceId).paused, true);
});

test('photo cannot redirect to member APIs, data URLs or external endpoints', () => {
  for (const previewUrl of ['data:image/jpeg;base64,AAAA', 'javascript:alert(1)', 'https://example.org/photo.jpg',
    '//example.org/photo.jpg', '/api/media/items/' + photoId + '/preview', '/api/media-tv/items/' + photoId + '/preview?cache=1',
    '/api/media-tv/items/' + photoId + '/preview#x', '/api/media-tv/items/' + photoId + '/preview/']) {
    assert.throws(() => readTVPlayback({ ...state(), item: { ...photo(), previewUrl } }, deviceId));
  }
  for (const patch of [{ id: '../private' }, { revision: 0 }, { revision: true }, { width: 1601 }, { height: 0 }, { width: 5.2 }]) {
    assert.throws(() => readTVPlayback({ ...state(), item: { ...photo(), ...patch } }, deviceId));
  }
  assert.equal(TV_PHOTO_MAX_BYTES, 2097152);
});

test('malformed or nonexistent server dates cannot authorize a frame', () => {
  for (const value of ['yesterday', '2026-09-17', '2026-09-17T00:00:00', '2026-02-30T00:00:00Z', '2026-09-17T25:00:00Z']) {
    for (const field of ['serverTime', 'validUntil', 'updatedAt']) assert.throws(() => readTVPlayback({ ...state(), [field]: value }, deviceId));
  }
});

test('lease uses monotonic request start, deducts latency and refuses expired or excessive duration', () => {
  const value = readTVPlayback(state(), deviceId);
  assert.equal(photoDeadline(value, 1000, 4000), 16000);
  assert.equal(photoDeadline({ ...value, validUntil: '2026-09-17T00:00:03.123456Z' }, 1000, 3999), 4000);
  for (const [started, now] of [[1000, 16000], [1000, 999], [-1, 0], [Infinity, Infinity], [1000, NaN]]) {
    assert.throws(() => photoDeadline(value, started, now));
  }
  for (const validUntil of [value.serverTime, '2026-09-16T23:59:59Z', '2026-09-17T00:00:15.124Z']) {
    assert.throws(() => photoDeadline({ ...value, validUntil }, 1000, 1001));
  }
});

test('paused authorization still expires, and lifecycle invalidation rejects late status or decode', () => {
  const value = readTVPlayback({ ...state(), paused: true }, deviceId), lease = new TVPhotoLease();
  const original = lease.ticket();
  lease.accept(original, value, 1000, 1001);
  assert.equal(lease.valid(original, 15999), true);
  assert.equal(lease.valid(original, 16000), false);
  assert.equal(lease.expired(16000), true);
  lease.clear();
  assert.equal(lease.valid(original, 1002), false);
  assert.throws(() => lease.accept(original, value, 1003, 1004));
  const resumed = lease.ticket();
  lease.accept(resumed, value, 2000, 2001);
  assert.equal(lease.valid(original, 2002), false);
  assert.equal(lease.valid(resumed, 2002), true);
});

test('renewal requires a current response and cannot roll a device revision backward', () => {
  const value = readTVPlayback(state(), deviceId), lease = new TVPhotoLease(), ticket = lease.ticket();
  lease.accept(ticket, value, 1000, 1001);
  lease.accept(ticket, value, 3000, 3001);
  assert.equal(lease.valid(ticket, 17000), true);
  assert.throws(() => lease.accept(ticket, { ...value, revision: 2 }, 5000, 5001));
  assert.equal(lease.valid(ticket, 18000), false);
  lease.clear();
  assert.throws(() => lease.accept(lease.ticket(), { ...value, revision: 1 }, 20000, 20001));
});
