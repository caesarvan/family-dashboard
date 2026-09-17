import assert from 'node:assert/strict';
import { test } from 'node:test';
import { checkedPlaceMutation, destinationEditor, failedPlaceIntent, journeyPlacePayload, journeyPlaceView, placeReadbackNeedsConceal, PlaceWriteRejected, PlaceWriteUnverified, readJourneyPlaceSource } from '../frontend/src/lib/journeyPlaces.ts';
import { PlaceFence, PlaceDiscarded, placeSignature, validatePlace } from '../frontend/src/lib/places.ts';
import { ApiError } from '../frontend/src/lib/api.ts';

const jid = '1'.repeat(24), tripId = '2'.repeat(24), pid = '3'.repeat(24);
const raw = () => ({ id: jid, tripId, revision: 1, plan: { title: '合成旅行', start: '2027-01-01', end: '2027-01-03',
  destinations: [{ key: 'tokyo', country: '日本', city: '东京', arrival: '2027-01-01', departure: '2027-01-03', coordinates: { latitude: 1, longitude: 2 }, visited: true }] } });
const source = () => readJourneyPlaceSource(raw(), jid);
const form = () => destinationEditor(source(), 'tokyo');
const session = () => ({ user: { role: 'member', householdId: 'first', id: 'a', auth_version: 1 }, csrf: 'session-one' });

test('destinations create only explicit planned private drafts with no inferred position or visitation', () => {
  const value = raw(); value.plan.destinations[0].owner = 'foreign'; value.plan.destinations[0].visibility = 'shared';
  const current = readJourneyPlaceSource(value, jid), draft = destinationEditor(current, 'tokyo');
  assert.deepEqual(draft.draft, { name: '东京', country: '日本', city: '东京', latitude: '', longitude: '', status: 'planned', visibility: 'private', coordinateDisclosure: 'hidden', startDate: '2027-01-01', endDate: '2027-01-03', journeyId: jid, confirmed: false });
  assert.equal(draft.original, null); assert.equal(draft.sourceRevision, 1);
  assert.deepEqual(Object.keys(current.destinations[0]).sort(), ['arrival', 'city', 'country', 'departure', 'key']);
});
test('source projection rejects swapped identity, unsafe revisions, malformed dates and destination keys', () => {
  for (const patch of [{ id: tripId }, { tripId: 'not-id' }, { revision: 0 }, { revision: 1.1 }, { revision: Number.MAX_SAFE_INTEGER + 1 }]) assert.throws(() => readJourneyPlaceSource({ ...raw(), ...patch }, jid));
  for (const patch of [{ arrival: '2027-02-29' }, { departure: '2026-12-31' }, { arrival: '2026-12-31' }, { departure: '2027-01-04' }, { key: '../bad' }]) {
    const value = raw(); Object.assign(value.plan.destinations[0], patch); assert.throws(() => readJourneyPlaceSource(value, jid));
  }
  const duplicate = raw(); duplicate.plan.destinations.push({ ...duplicate.plan.destinations[0] }); assert.throws(() => readJourneyPlaceSource(duplicate, jid));
});
test('twenty bounded destinations and Unicode names are accepted without UTF16 truncation', () => {
  const value = raw(); value.plan.destinations = Array.from({ length: 20 }, (_, n) => ({ ...value.plan.destinations[0], key: 'key' + n, city: '🌏'.repeat(80) }));
  const current = readJourneyPlaceSource(value, jid); assert.equal(current.destinations.length, 20);
  const payload = journeyPlacePayload(destinationEditor(current, 'key0'), current); assert.equal(Array.from(payload.city).length, 80);
  value.plan.destinations.push({ ...value.plan.destinations[0], key: 'extra' }); assert.throws(() => readJourneyPlaceSource(value, jid));
});
test('payload contains only allowed place fields and expected source revision', () => {
  const editor = form(); editor.draft.owner = 'foreign'; editor.draft.requestId = 'injected';
  const payload = journeyPlacePayload(editor, source());
  assert.deepEqual(Object.keys(payload).sort(), ['city', 'confirmVisited', 'coordinateDisclosure', 'coordinates', 'country', 'endDate', 'expectedJourneyRevision', 'journeyId', 'name', 'startDate', 'status', 'visibility']);
  assert.equal(payload.coordinates, null); assert.equal(payload.confirmVisited, false); assert.equal(payload.expectedJourneyRevision, 1);
  assert.throws(() => journeyPlacePayload(editor, { ...source(), revision: 2 }));
  assert.throws(() => journeyPlacePayload(editor, { ...source(), destinations: [] }));
});
test('manual coordinates are paired bounded decimals, never guessed or auto shared', () => {
  const editor = form(); editor.draft.latitude = '31.230400'; editor.draft.longitude = '121.4737';
  assert.deepEqual(journeyPlacePayload(editor, source()).coordinates, { latitude: 31.2304, longitude: 121.4737 });
  for (const [latitude, longitude] of [['1', ''], ['91', '1'], ['1', '-181'], ['1e1', '2'], ['1.1234567', '2'], ['NaN', '2']]) assert.throws(() => journeyPlacePayload({ ...editor, draft: { ...editor.draft, latitude, longitude } }, source()));
  assert.equal(journeyPlacePayload(editor, source()).visibility, 'private');
  editor.draft.visibility = 'shared'; assert.equal(journeyPlacePayload(editor, source()).coordinateDisclosure, 'hidden');
});
test('new drafts cannot become visited or change linked journey implicitly', () => {
  for (const patch of [{ status: 'visited', confirmed: true }, { status: 'wish' }, { journeyId: tripId }, { visibility: 'everyone' }]) assert.throws(() => journeyPlacePayload({ ...form(), draft: { ...form().draft, ...patch } }, source()));
  const editor = form(); editor.draft.name = 'bad\u0000'; assert.throws(() => journeyPlacePayload(editor, source()));
});
test('owned edits retain separate place revision and require explicit changed visited confirmation', () => {
  const editor = form(), payload = journeyPlacePayload(editor, source());
  editor.original = { ...payload, id: pid, revision: 5, status: 'visited', canManage: true };
  editor.draft = { ...editor.draft, id: pid, status: 'visited', name: '修改后的地点' };
  assert.throws(() => journeyPlacePayload(editor, source()), /确认/);
  editor.draft.confirmed = true; const next = journeyPlacePayload(editor, source());
  assert.equal(next.revision, 5); assert.equal(next.expectedJourneyRevision, 1); assert.equal(next.confirmVisited, true);
  editor.original.canManage = false; assert.throws(() => journeyPlacePayload(editor, source()));
});
test('unknown result keeps original immutable intent through a later definitive rejection', () => {
  const original = { method: 'POST', path: '/journey-places', body: Object.freeze({ requestId: 'same-key', expectedJourneyRevision: 1 }), state: 'unknown', uncertain: false };
  const unknown = failedPlaceIntent(original, new ApiError('network', 0)), later = failedPlaceIntent(unknown, new PlaceWriteRejected(409, 'revision'));
  assert.equal(later.state, 'unknown'); assert.equal(later.uncertain, true); assert.equal(later.body, original.body);
  assert.equal(failedPlaceIntent(original, new PlaceWriteRejected(409, 'revision')).state, 'rejected'); assert.equal(failedPlaceIntent(original, new ApiError('after/me', 409)).state, 'unknown');
});
test('map navigation contains authorized IDs and filter state only and preserves a selected page', () => {
  assert.deepEqual(journeyPlaceView(jid, pid, 24), { filters: { scope: 'visible', status: '', year: '', owner: '', journeyId: jid }, offset: 24, selected: pid });
  assert.throws(() => journeyPlaceView(jid, 'bad')); assert.throws(() => journeyPlaceView(jid, pid, 3001));
});
test('identity fence validates both successful and failed private requests', async () => {
  const first = session(); let me = first;
  const fence = new PlaceFence(async () => me, placeSignature(first));
  await assert.rejects(fence.run(async () => { me = { ...first, csrf: 'different' }; return 'private'; }, () => true), PlaceDiscarded);
  me = first;
  await assert.rejects(fence.run(async () => { me = { ...first, user: { ...first.user, householdId: 'second' } }; throw new Error('old private error'); }, () => true), PlaceDiscarded);
});
test('focus epoch invalidation discards a delayed success and delayed failure after resume', async () => {
  for (const failure of [false, true]) {
    const first = session(), fence = new PlaceFence(async () => first, placeSignature(first));
    let release; const wait = new Promise(resolve => { release = resolve; });
    const promise = fence.run(async () => { await wait; if (failure) throw new Error('old'); return 'old'; }, () => true);
    await Promise.resolve(); fence.invalidate(); release(); await assert.rejects(promise, PlaceDiscarded);
  }
});

const intent = () => ({ method: 'POST', path: '/journey-places', body: Object.freeze({ requestId: 'f'.repeat(32), expectedJourneyRevision: 1 }), state: 'unknown', uncertain: false });
const httpStatus = failure => failure instanceof ApiError ? failure.status : undefined;
async function thrown(action) { try { await action(); assert.fail('expected rejection'); } catch (failure) { return failure; } }

test('only mutation rejection followed by successful identity verification unlocks a fresh create', async () => {
  const first = session(); let reads = 0;
  const fence = new PlaceFence(async () => { ++reads; return first; }, placeSignature(first));
  const failure = await thrown(() => checkedPlaceMutation(job => fence.run(job, () => true), async () => { throw new ApiError('source changed', 409); }, httpStatus));
  assert.equal(reads, 2); assert.ok(failure instanceof PlaceWriteRejected);
  assert.equal(failedPlaceIntent(intent(), failure).state, 'rejected');
});
test('committed mutation followed by /me 401 403 408 429 keeps the exact original intent unknown', async () => {
  for (const status of [401, 403, 408, 429]) {
    const first = session(), original = intent(); let reads = 0, submitted = 0;
    const fence = new PlaceFence(async () => { if (++reads === 2) throw new ApiError('identity unavailable', status); return first; }, placeSignature(first));
    const failure = await thrown(() => checkedPlaceMutation(job => fence.run(job, () => true), async () => { ++submitted; return { place: 'committed' }; }, httpStatus));
    assert.equal(submitted, 1); assert.ok(failure instanceof PlaceWriteUnverified);
    const failed = failedPlaceIntent(original, failure); assert.equal(failed.state, 'unknown'); assert.equal(failed.body, original.body);
    assert.equal(failed.body.requestId, 'f'.repeat(32)); assert.equal(failed.body.expectedJourneyRevision, 1);
  }
});
test('failed pre-identity and failed post-identity cannot be mistaken for a mutation rejection', async () => {
  for (const failAt of [1, 2]) {
    const first = session(); let reads = 0, calls = 0;
    const fence = new PlaceFence(async () => { if (++reads === failAt) throw new ApiError('rate limit', 429); return first; }, placeSignature(first));
    const failure = await thrown(() => checkedPlaceMutation(job => fence.run(job, () => true), async () => { ++calls; throw new ApiError('source conflict', 409); }, httpStatus));
    assert.equal(calls, failAt === 1 ? 0 : 1); assert.ok(failure instanceof PlaceWriteUnverified);
    assert.equal(failedPlaceIntent(intent(), failure).state, 'unknown');
  }
});
test('mutation 401 408 and malformed success receipt retain the original request identity', async () => {
  for (const status of [401, 408, 500]) {
    const first = session(), fence = new PlaceFence(async () => first, placeSignature(first));
    const failure = await thrown(() => checkedPlaceMutation(job => fence.run(job, () => true), async () => { throw new ApiError('uncertain', status); }, httpStatus));
    assert.ok(!(failure instanceof PlaceWriteRejected)); assert.equal(failedPlaceIntent(intent(), failure).state, 'unknown');
  }
  const first = session(), fence = new PlaceFence(async () => first, placeSignature(first));
  const result = await checkedPlaceMutation(job => fence.run(job, () => true), async () => ({ place: null }), httpStatus);
  const original = intent();
  const failure = await thrown(async () => validatePlace(result.place));
  assert.equal(result.place, null); assert.equal(failedPlaceIntent(original, failure).body, original.body);
  assert.equal(failedPlaceIntent(original, failure).state, 'unknown');
});
test('post-success readback identity failures require conceal while network failures preserve confirmed success', () => {
  for (const status of [401, 403]) assert.equal(placeReadbackNeedsConceal(new ApiError('no identity', status), false), true);
  assert.equal(placeReadbackNeedsConceal(new PlaceDiscarded('identity'), true), true);
  for (const status of [0, 408, 429, 500]) assert.equal(placeReadbackNeedsConceal(new ApiError('network', status), false), false);
});
test('actual signature change after mutation is distinguishable from temporarily unavailable identity', async () => {
  const first = session(); let me = first;
  const fence = new PlaceFence(async () => me, placeSignature(first));
  const failure = await thrown(() => checkedPlaceMutation(job => fence.run(job, () => true), async () => { me = { ...first, csrf: 'new-member' }; return { place: 'old-member-place' }; }, httpStatus));
  assert.ok(failure instanceof PlaceWriteUnverified); assert.ok(failure.reason instanceof PlaceDiscarded); assert.equal(failure.reason.message, 'identity');
});
