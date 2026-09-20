import assert from 'node:assert/strict';
import { test } from 'node:test';
import { DUPLICATE_LABEL, duplicateCoverageText, fetchPhotoDuplicates, photoDuplicatesQuery, readPhotoDuplicates, verifyDuplicatePhotos, withPhotoDuplicateRead } from '../src/lib/photoDuplicates.ts';
import { PhotoReadFence, PhotoReadDiscarded } from '../src/lib/photos.ts';

const id = n => n.toString(16).padStart(24, '0');
const accountId = 'f'.repeat(32);
const photo = (n = 1, source = 'local-upload') => ({ id: id(n), revision: 2, caption: '合成照片',
  width: 800, height: 600, previewUrl: `/api/media/items/${id(n)}/preview`, visibility: 'private', canManage: true,
  createdAt: '2026-09-20T01:00:00Z', journey: null, mediaType: 'photo', source,
  accountId: source === 'local-upload' ? null : accountId });
const target = photo(), other = photo(2, 'google-photos');
const page = (items = [other], offset = 0, total = items.length) => ({ photoId: target.id, photoRevision: target.revision,
  matchBasis: 'display-copy-sha256', label: DUPLICATE_LABEL, items, total, limit: 20, offset, hasMore: offset + 20 < total,
  coverage: { scope: 'mine', scanLimit: 1000, scanned: total, capped: false, unverifiable: 0 } });
const accounts = { accounts: [{ id: accountId, provider: 'google', needsReauth: false, capabilities: { photos: true } }] };
function transport(change = () => {}) {
  const calls = [];
  return { calls, async read(path) {
    calls.push(path);
    let value = path === '/accounts' ? structuredClone(accounts) : path.includes('/duplicates?') ? page()
      : { item: path.endsWith(target.id) ? structuredClone(target) : structuredClone(other) };
    await change(path, value, calls);
    return value;
  } };
}
test('exact display-copy contract retains canonical IDs and source, never invents original equality', () => {
  assert.deepEqual(readPhotoDuplicates(page(), target, 0), page());
  assert.equal(photoDuplicatesQuery(target.id, 20), `/media/items/${target.id}/duplicates?limit=20&offset=20`);
  for (const patch of [{ matchBasis: 'perceptual' }, { label: '原图相同' }, { photoId: id(6) }, { photoRevision: 3 }])
    assert.throws(() => readPhotoDuplicates({ ...page(), ...patch }, target, 0));
});
test('pagination checks counts, ordering, duplicates and empty out-of-range pages', () => {
  assert.deepEqual(readPhotoDuplicates(page([], 20, 1), target, 20), page([], 20, 1));
  for (const offset of [-20, 1, 4020, Infinity]) assert.throws(() => photoDuplicatesQuery(target.id, offset));
  for (const value of [page([other], 0, 2), { ...page(), hasMore: true }, page([other, other]),
    page([photo(3, 'google-photos'), other])]) assert.throws(() => readPhotoDuplicates(value, target, 0));
});
test('private owner-only static photos and original authorized preview are required', () => {
  for (const patch of [{ id: target.id }, { canManage: false }, { mediaType: 'video' }, { source: 'local-upload', accountId: null },
    { source: 'google-photos', accountId: null }, { accountId: id(99) }, { previewUrl: 'https://example.invalid/image.jpg' }])
    assert.throws(() => readPhotoDuplicates(page([{ ...other, ...patch }]), target, 0));
  assert.throws(() => readPhotoDuplicates(page(), { ...target, canManage: false }, 0));
});
test('coverage never presents a capped/unverifiable scan as all original photos', () => {
  for (const patch of [{ capped: true }, { unverifiable: 2 }]) {
    const p = readPhotoDuplicates({ ...page(), coverage: { ...page().coverage, ...patch } }, target, 0);
    assert.match(duplicateCoverageText(p), /仅检查了部分已保存照片/);
  }
  assert.match(duplicateCoverageText(page([])), /未找到结果也不代表原图不同/);
  for (const patch of [{ scope: 'shared' }, { scanLimit: 2000 }, { scanned: 0 }, { unverifiable: 1001 }])
    assert.throws(() => readPhotoDuplicates({ ...page(), coverage: { ...page().coverage, ...patch } }, target, 0));
});
test('metadata/source changes after the response are rejected before results install', async () => {
  const t = transport((path, value, calls) => {
    if (path.endsWith(target.id) && calls.some(p => p.includes('duplicates?'))) value.item.revision++;
  });
  await assert.rejects(fetchPhotoDuplicates(target, 0, t.read), /照片或来源已变化/);
  const revoked = transport((path, value) => { if (path === '/accounts') value.accounts[0].needsReauth = true; });
  await assert.rejects(fetchPhotoDuplicates(target, 0, revoked.read), /照片或来源已变化/);
});
test('visible-page verification checks original metadata without another scan', async () => {
  const t = transport(); await verifyDuplicatePhotos([target, other], t.read);
  assert.equal(t.calls.some(p => p.includes('duplicates?')), false);
  assert.deepEqual(t.calls, [`/media/items/${target.id}`, `/media/items/${other.id}`, '/accounts']);
});
test('member, household, session and offline late responses are discarded by the real photo fence', async () => {
  const user = { id: 'owner', householdId: 'one', auth_version: 1, role: 'member' };
  for (const patch of [{ id: 'partner' }, { householdId: 'two' }, { auth_version: 2 }]) {
    let reads = 0;
    const fence = new PhotoReadFence(async () => ({ user: ++reads === 1 ? user : { ...user, ...patch }, csrf: 'synthetic' }), user);
    const t = transport();
    await assert.rejects(fence.read(() => fetchPhotoDuplicates(target, 0, t.read), () => true), PhotoReadDiscarded);
  }
  let online = true;
  const fence = new PhotoReadFence(async () => ({ user, csrf: 'synthetic' }), user);
  const t = transport(path => { if (path.includes('duplicates?')) online = false; });
  await assert.rejects(fence.read(() => fetchPhotoDuplicates(target, 0, t.read), () => online), PhotoReadDiscarded);
});
test('network failure and response-time candidate deletion never produce a successful empty page', async () => {
  const t = transport(path => { if (path.endsWith(other.id)) throw new Error('404'); });
  await assert.rejects(fetchPhotoDuplicates(target, 0, t.read), /404/);
  await assert.rejects(fetchPhotoDuplicates(target, 0, async () => { throw new Error('offline'); }), /offline/);
});


test('bounded read: at most four concurrent details plus one accounts request', async () => {
  const items = [target, ...Array.from({ length: 20 }, (_, n) => photo(n + 2, 'google-photos'))];
  let active = 0, peak = 0, accountReads = 0;
  const pending = [], calls = [];
  const operation = withPhotoDuplicateRead(async path => {
    calls.push(path);
    if (path === '/accounts') { accountReads++; return accounts; }
    active++; peak = Math.max(peak, active);
    await new Promise(resolve => pending.push(resolve)); active--;
    return { item: items.find(item => path.endsWith(item.id)) };
  }, () => true, read => verifyDuplicatePhotos(items, read));
  for (let round = 0; round < 8; round++) {
    await new Promise(setImmediate); assert.ok(active <= 4); pending.splice(0).forEach(resolve => resolve());
  }
  await operation; assert.equal(peak, 4); assert.equal(accountReads, 1); assert.equal(calls.length, 22);
});

test('bounded read: whole scan expires even if a transport never resolves or ignores abort', async () => {
  const calls = [], signals = [];
  await assert.rejects(withPhotoDuplicateRead(async (path, signal) => {
    calls.push(path); signals.push(signal); return new Promise(() => {});
  }, () => true, read => fetchPhotoDuplicates(target, 0, read), { deadlineMs: 15 }), /检查超时/);
  assert.deepEqual(calls, [`/media/items/${target.id}`]); assert.ok(signals.every(signal => signal.aborted));
});

test('bounded read: a source failure aborts the batch and does not dispatch queued details', async () => {
  const items = Array.from({ length: 20 }, (_, n) => photo(n + 2, 'google-photos'));
  const calls = [], signals = [];
  await assert.rejects(withPhotoDuplicateRead(async (path, signal) => {
    calls.push(path); signals.push(signal);
    if (path === '/accounts') return { accounts: [] };
    return new Promise(() => {});
  }, () => true, read => verifyDuplicatePhotos(items, read)), /照片或来源已变化/);
  assert.equal(calls.length, 5); assert.ok(signals.every(signal => signal.aborted));
});

test('bounded read: identity/lifetime loss never starts another queued read', async () => {
  const items = Array.from({ length: 20 }, (_, n) => photo(n + 2, 'google-photos'));
  let current = true; const pending = [], calls = [];
  const operation = withPhotoDuplicateRead(async path => {
    calls.push(path); if (path === '/accounts') return accounts;
    await new Promise(resolve => pending.push(resolve)); return { item: items.find(item => path.endsWith(item.id)) };
  }, () => current, read => verifyDuplicatePhotos(items, read));
  await new Promise(setImmediate); current = false; pending.splice(0).forEach(resolve => resolve());
  await assert.rejects(operation, PhotoReadDiscarded); assert.equal(calls.length, 5);
});

test('bounded read: external concealment aborts in-flight work and retains no late result', async () => {
  const controller = new AbortController(); let release; const calls = [], signals = [];
  const operation = withPhotoDuplicateRead(async (path, signal) => {
    calls.push(path); signals.push(signal); await new Promise(resolve => { release = resolve; }); return { item: target };
  }, () => true, read => fetchPhotoDuplicates(target, 0, read), { signal: controller.signal });
  await new Promise(setImmediate); controller.abort(); await assert.rejects(operation, PhotoReadDiscarded);
  release(); await new Promise(setImmediate); assert.equal(calls.length, 1); assert.ok(signals.every(signal => signal.aborted));
});
