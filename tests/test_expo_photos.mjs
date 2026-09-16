import assert from 'node:assert/strict';
import { test } from 'node:test';
import { PhotoReadFence, PhotoReadDiscarded, confirmPhotos, countText, newPhotoRequestId, photoError, photoSignature, previewPath, savedSummary, validateImport } from '../frontend/src/lib/photos.ts';

const id = 'a'.repeat(24);
const session = { user: { role: 'member', id: 'member1', householdId: 'home1', auth_version: 1 }, csrf: 'synthetic-browser-csrf' };
const photo = { id, revision: 1, caption: '合成照片', previewUrl: `/api/media/items/${id}/preview`, visibility: 'private', canManage: true };
const row = { id, revision: 4, state: 'awaiting_confirmation', canConfirm: true, resultsState: 'known', results: [], counts: { selected: 10, ready: 3, skipped: 0, failed: 7, pending: 0, saved: 0, unselected: null } };

test('previews require the exact local item path; no provider or TV URLs', () => {
  assert.equal(previewPath(photo), photo.previewUrl);
  for (const path of ['https://photos.google.com/test', '//evil.test/file', `/api/media-tv/items/${id}/preview`, photo.previewUrl + '?key=secret', photo.previewUrl + '#x', '/api/media/items/' + 'b'.repeat(24) + '/preview']) assert.equal(previewPath({ ...photo, previewUrl: path }), '');
  assert.equal(previewPath({ ...photo, id: '../accounts' }), '');
});
test('historical unknown is never a fake zero or full success', () => {
  const old = { ...row, state: 'confirmed', resultsState: 'unknown', counts: { ...row.counts, selected: null, ready: null, failed: null, saved: 3 } };
  assert.equal(savedSummary(old), '已保存 3 张；本次其他处理结果未记录');
  assert.equal(savedSummary({ ...old, counts: { ...old.counts, saved: null } }), '本次保存数量未记录；本次其他处理结果未记录');
  assert.equal(countText(null), '未记录'); assert.equal(countText(undefined), '未记录'); assert.equal(countText(0), '0 张');
  assert.equal(savedSummary({ ...row, state: 'confirmed', counts: { ...row.counts, saved: 3 } }), '已保存 3 张');
});
test('only fixed local error messages; unknown provider/decoder text is discarded', () => {
  assert.equal(photoError('invalid_image'), '图片不完整或无法安全解码。');
  assert(!photoError('<secret>https://private.test/path').includes('secret'));
  assert(photoError('api_disabled').includes('无需重复授权'));
});
test('confirmation keeps selected IDs and original revision/key immutable across retries', () => {
  const selected = [id]; const key = newPhotoRequestId();
  assert.match(key, /^[A-Za-z0-9_-]{16,100}$/);
  const request = confirmPhotos(row, selected, key); selected.push('b'.repeat(24));
  assert.deepEqual(request, { revision: 4, confirmRequestId: key, itemIds: [id], consentVersion: 'media-v1', persistSelected: true });
  assert.throws(() => confirmPhotos(row, [], key)); assert.throws(() => confirmPhotos(row, [id, id], key));
  assert.throws(() => confirmPhotos({ ...row, canConfirm: false }, [id], key));
  assert.throws(() => confirmPhotos({ ...row, state: 'confirmed' }, [id], key));
});
test('import preview validation rejects mismatched IDs, duplicate selections and excess rows', () => {
  const candidate = { id, status: 'successful', item: photo };
  assert.equal(validateImport({ import: row, items: [candidate] }).items[0].item, photo);
  assert.throws(() => validateImport({ import: row, items: [{ ...candidate, id: 'b'.repeat(24) }] }));
  assert.throws(() => validateImport({ import: row, items: [candidate, candidate] }));
  assert.throws(() => validateImport({ import: { ...row, counts: { ...row.counts, saved: 21 } }, items: [] }));
  assert.throws(() => validateImport({ import: { ...row, state: 'unknown-state' }, items: [] }));
});
test('GET checks fresh member identity both before and after business I/O', async () => {
  let calls = 0; const fence = new PhotoReadFence(async () => { calls++; return session; }, session.user, photoSignature(session));
  assert.deepEqual(await fence.read(async () => [photo], () => true), [photo]); assert.equal(calls, 2);
});
test('changed household/member/role/auth version/CSRF before request sends no business GET', async () => {
  for (const changed of [{ ...session, csrf: 'another-browser' }, { ...session, user: null }, ...[{ householdId: 'home2' }, { id: 'member2' }, { role: 'tv' }, { auth_version: 2 }].map(patch => ({ ...session, user: { ...session.user, ...patch } }))]) {
    let queried = false;
    const fence = new PhotoReadFence(async () => changed, session.user, photoSignature(session));
    await assert.rejects(fence.read(async () => { queried = true; }, () => true), error => error instanceof PhotoReadDiscarded && error.message === 'identity');
    assert.equal(queried, false);
  }
});
test('account changes while business GET is in flight discard its private result', async () => {
  let calls = 0;
  const fence = new PhotoReadFence(async () => ++calls === 1 ? session : { ...session, user: { ...session.user, id: 'member2' } }, session.user, photoSignature(session));
  await assert.rejects(fence.read(async () => [photo], () => true), PhotoReadDiscarded);
});
test('route invalidation and late old request sequence cannot publish data', async () => {
  const fence = new PhotoReadFence(async () => session, session.user, photoSignature(session));
  await assert.rejects(fence.read(async () => { fence.invalidate(); return photo; }, () => true), PhotoReadDiscarded);
  let current = true;
  await assert.rejects(fence.read(async () => { current = false; return photo; }, () => current), PhotoReadDiscarded);
});
test('fallback fence pins the first full signature including CSRF', async () => {
  let next = session; const fence = new PhotoReadFence(async () => next, session.user);
  await fence.read(async () => photo, () => true);
  next = { ...session, csrf: 'rotated' };
  await assert.rejects(fence.read(async () => photo, () => true), PhotoReadDiscarded);
});
