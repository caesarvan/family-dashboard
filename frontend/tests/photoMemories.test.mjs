import assert from 'node:assert/strict';
import { test } from 'node:test';
import { memoryOffsetAfterDateChange, photoMemoriesQuery, readPhotoMemories } from '../src/lib/photoMemories.ts';

const photo = (id = 'a'.repeat(24), year = 2025) => ({
  id, revision: 3, caption: '海边', width: 800, height: 600,
  previewUrl: `/api/media/items/${id}/preview`, visibility: 'private', canManage: true,
  createdAt: '2026-08-01T00:00:00Z', journey: null, mediaType: 'photo',
  sourceTimeState: 'known', sourceCreatedAt: `${year}-09-19T18:00:00Z`,
});
const memory = (id, year = 2025) => ({ item: photo(id, year), sourceLocalDate: `${year}-09-20`, yearsAgo: 2026 - year });
const page = (items = [memory()]) => ({
  referenceDate: '2026-09-20', referenceTimezone: 'Asia/Shanghai', dateBasis: 'sourceCreatedAt', scope: 'mine',
  items, total: items.length, limit: 24, offset: 0, hasMore: false, unknownSourceTimeCount: 7,
});

test('owner photos retain original identity and revision across sorted years', () => {
  const original = page([memory('a'.repeat(24)), memory('b'.repeat(24)), memory('c'.repeat(24), 2024)]);
  assert.deepEqual(readPhotoMemories(original, 0), original);
  assert.equal(photoMemoriesQuery(24), '/media/memories/on-this-day?limit=24&offset=24&dateMode=confirmed-or-source');
});

test('date basis is source time, never import time or caller supplied timezone', () => {
  for (const patch of [{ scope: 'shared' }, { referenceTimezone: 'UTC' }, { dateBasis: 'createdAt' }, { referenceDate: '2026-02-29' }])
    assert.throws(() => readPhotoMemories({ ...page(), ...patch }, 0));
  assert.equal(readPhotoMemories(page(), 0).items[0].sourceLocalDate, '2025-09-20');
});

test('shared non-owner, video, missing source time and malformed preview are rejected', () => {
  for (const patch of [{ canManage: false }, { sourceTimeState: 'unknown', sourceCreatedAt: null },
    { previewUrl: 'https://example.invalid/photo' }, { mediaType: 'video' }]) {
    const input = page(); Object.assign(input.items[0].item, patch);
    assert.throws(() => readPhotoMemories(input, 0));
  }
});

test('current year, wrong month-day, wrong elapsed years and duplicates are rejected', () => {
  for (const patch of [{ sourceLocalDate: '2026-09-20', yearsAgo: 0 },
    { sourceLocalDate: '2025-09-21' }, { yearsAgo: 99 }]) {
    const input = page(); Object.assign(input.items[0], patch);
    assert.throws(() => readPhotoMemories(input, 0));
  }
  assert.throws(() => readPhotoMemories(page([memory(), memory()]), 0));
  assert.throws(() => readPhotoMemories(page([memory('b'.repeat(24)), memory('a'.repeat(24))]), 0));
  assert.throws(() => readPhotoMemories(page([memory('b'.repeat(24), 2024), memory('a'.repeat(24))]), 0));
});

test('pagination rejects inconsistent totals and preserves empty out-of-range pages', () => {
  for (const patch of [{ total: 3 }, { hasMore: true }, { offset: 24 }, { unknownSourceTimeCount: -1 }])
    assert.throws(() => readPhotoMemories({ ...page(), ...patch }, 0));
  const empty = { ...page([]), offset: 24, total: 2 };
  assert.deepEqual(readPhotoMemories(empty, 24), empty);
  for (const value of [-24, 1, 4008, Infinity]) assert.throws(() => photoMemoriesQuery(value));
});

test('leap day remains February 29 and does not move to another day', () => {
  const row = memory(undefined, 2024);
  row.sourceLocalDate = '2024-02-29'; row.yearsAgo = 4; row.item.sourceCreatedAt = '2024-02-29T01:00:00Z';
  const input = { ...page([row]), referenceDate: '2028-02-29' };
  assert.deepEqual(readPhotoMemories(input, 0), input);
  assert.throws(() => readPhotoMemories({ ...input, referenceDate: '2028-02-28' }, 0));
});

test('server day changes reset page two for polling and background return', () => {
  const old = { ...page([]), offset: 24, total: 1 };
  const nextDay = readPhotoMemories({ ...old, referenceDate: '2026-09-21' }, 24);
  assert.equal(memoryOffsetAfterDateChange(old.referenceDate, readPhotoMemories(old, 24)), 24);
  assert.equal(memoryOffsetAfterDateChange(old.referenceDate, nextDay), 0);
  // Concealment discards the old photo payload; retaining only its server date
  // still detects midnight. An empty second page must not hide the first page.
  const dateRetainedDuringConcealment = old.referenceDate;
  assert.equal(photoMemoriesQuery(memoryOffsetAfterDateChange(dateRetainedDuringConcealment, nextDay)),
    '/media/memories/on-this-day?limit=24&offset=0&dateMode=confirmed-or-source');
  const firstPage = readPhotoMemories({ ...page([]), referenceDate: nextDay.referenceDate }, 0);
  assert.equal(memoryOffsetAfterDateChange(nextDay.referenceDate, firstPage), 0);
  assert.equal(memoryOffsetAfterDateChange(null, firstPage), 0);
});
