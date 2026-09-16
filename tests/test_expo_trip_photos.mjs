import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';
import { test } from 'node:test';

// Metro resolves extensionless TS imports. Match that one resolution when
// running the same source with Node's built-in TypeScript support.
const source = new URL('../frontend/src/lib/tripPhotos.ts', import.meta.url).href;
registerHooks({ resolve(specifier, context, nextResolve) {
  return nextResolve(context.parentURL === source && specifier === './photos' ? './photos.ts' : specifier, context);
} });
const { readTripPhoto, readTripPhotoJourney, readTripPhotoPage, tripPhotoQuery } = await import(source);
const journeyId = 'a'.repeat(24), tripId = 'b'.repeat(24), otherId = 'c'.repeat(24);
const photo = {
  id: 'd'.repeat(24), revision: 2, caption: '合成旅途照片', width: 30, height: 20,
  previewUrl: '/api/media/items/' + 'd'.repeat(24) + '/preview', visibility: 'private', canManage: true,
  createdAt: '2026-09-16T00:00:00Z', journey: { id: journeyId, tripId, title: '合成旅行' },
};
const page = (items = [photo], offset = 0, total = offset + items.length) => ({ items, limit: 24, offset, total, hasMore: offset + 24 < total });

test('gallery uses the workflow ID and rejects non-canonical IDs, scope and page inputs', () => {
  assert.equal(tripPhotoQuery(journeyId, 'visible', 0), `/media/items?scope=visible&journeyId=${journeyId}&limit=24&offset=0`);
  assert.equal(tripPhotoQuery(journeyId, 'shared', 24), `/media/items?scope=shared&journeyId=${journeyId}&limit=24&offset=24`);
  for (const args of [['../accounts', 'visible', 0], [journeyId, 'other', 0], [journeyId, 'visible', -24], [journeyId, 'mine', 1], [journeyId, 'mine', 4008], [journeyId, 'mine', NaN]]) {
    assert.throws(() => tripPhotoQuery(...args));
  }
});

test('fresh journey projection discards budgets, task titles and backend extras', () => {
  const input = { id: journeyId, tripId, trip: { id: tripId, title: '当前名称', budget: 123 }, plan: { title: '旧名称' }, tasks: [{ title: '私人任务' }] };
  assert.deepEqual(readTripPhotoJourney(input, journeyId), { id: journeyId, tripId, title: '当前名称' });
  assert.deepEqual(readTripPhotoJourney({ ...input, trip: null }, journeyId), { id: journeyId, tripId, title: '旧名称' });
  for (const bad of [{ ...input, id: otherId }, { ...input, tripId: '../private' }, { ...input, trip: { id: otherId, title: '错误旅行' } }, { ...input, trip: { id: tripId, title: [] } }]) {
    assert.throws(() => readTripPhotoJourney(bad, journeyId));
  }
});

test('photo projection keeps only permitted local gallery fields', () => {
  assert.deepEqual(readTripPhoto({ ...photo, accountId: 'private-source-account', displayFilename: 'private-original.jpg', sourceCreatedAt: 'private-source-time' }, journeyId), photo);
  assert.equal(readTripPhoto(photo, journeyId, photo.id).id, photo.id);
  assert.throws(() => readTripPhoto(photo, tripId));
  assert.throws(() => readTripPhoto(photo, journeyId, otherId));
});

test('photo re-link, wrong preview authority, malformed dimensions and captions fail closed', () => {
  const badPhotos = [
    { ...photo, journey: null }, { ...photo, journey: { ...photo.journey, id: otherId } },
    { ...photo, journey: { ...photo.journey, tripId: 'not-an-id' } },
    { ...photo, previewUrl: 'https://photos.google.com/private' },
    { ...photo, previewUrl: `/api/media-tv/items/${photo.id}/preview` },
    { ...photo, previewUrl: photo.previewUrl + '?token=secret' },
    { ...photo, caption: 'x'.repeat(501) }, { ...photo, revision: 0 },
    { ...photo, width: 0 }, { ...photo, height: 1.5 }, { ...photo, width: 20000001, height: 1 },
    { ...photo, createdAt: 'not-a-time' }, { ...photo, canManage: 'yes' },
  ];
  for (const bad of badPhotos) assert.throws(() => readTripPhoto(bad, journeyId));
});

test('24-row paging preserves total and current offset, including a now-empty later page', () => {
  const items = Array.from({ length: 24 }, (_, index) => {
    const id = index.toString(16).padStart(24, '0'); return { ...photo, id, previewUrl: `/api/media/items/${id}/preview` };
  });
  const first = readTripPhotoPage(page(items, 0, 25), journeyId, 0);
  assert.equal(first.items.length, 24); assert.equal(first.hasMore, true); assert.equal(first.total, 25);
  const second = readTripPhotoPage(page([photo], 24, 25), journeyId, 24);
  assert.equal(second.items.length, 1); assert.equal(second.hasMore, false);
  assert.deepEqual(readTripPhotoPage(page([], 24, 1), journeyId, 24), page([], 24, 1));
});

test('malformed, mixed-workflow or duplicate result pages are never rendered', () => {
  const badPages = [
    { ...page(), limit: 25 }, { ...page(), offset: 24 }, { ...page(), total: -1 },
    { ...page(), hasMore: true }, { ...page(), total: 3 }, { ...page(), items: {} },
    page([photo, photo]), page([{ ...photo, journey: { ...photo.journey, id: otherId } }]),
    page(Array.from({ length: 25 }, () => photo)),
  ];
  for (const bad of badPages) assert.throws(() => readTripPhotoPage(bad, journeyId, 0));
});
