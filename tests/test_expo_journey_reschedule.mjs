import assert from 'node:assert/strict';
import { test } from 'node:test';
import { checkedRescheduleWrite, clockText, failedRescheduleIntent, initialRescheduleDraft, localOverride, mayExitReschedule, offsetText, pageItems, readRescheduleOperation, readReschedulePreview, readRescheduleReceipt, readRescheduleSnapshot, rebaseRescheduleDraft, reschedulePayload, RescheduleRejected, RescheduleUnverified, snapshotVersion, validRescheduleDay } from '../frontend/src/lib/journeyReschedule.ts';
import { PlaceDiscarded, PlaceFence, placeSignature } from '../frontend/src/lib/places.ts';

const jid = 'a'.repeat(24), tripId = 'b'.repeat(24), operation = 'c'.repeat(32);
const row = (key, kind, eligible = true) => ({ key, kind, title: key, before: { start: '2027-03-10', end: '2027-03-12' }, eligible, reason: eligible ? null : 'completed', endExclusive: false });
const rawSource = () => ({ journeyId: jid, revision: 7, start: '2027-03-10', end: '2027-03-12', snapshotToken: 'signed-original', expiresIn: 1800, items: [row('trip', 'overview', false), row('destination:tokyo', 'destination'), row('segment:flight', 'segment'), row('task:prepare', 'task'), row('task:complete', 'task', false), row('place:' + 'd'.repeat(24), 'place'), row('shopping:coffee', 'shopping', false)], warnings: [], capabilities: { shoppingDue: false } });
const source = () => readRescheduleSnapshot(rawSource(), jid);
const draft = () => ({ ...initialRescheduleDraft(source()), start: '2027-03-20', end: '2027-03-23', selectedKeys: ['task:prepare'] });
function preview(snapshot = source(), form = draft()) {
  return { journeyId: jid, revision: 7, start: form.start, end: form.end, items: snapshot.items.map(item => ({ ...item, selected: item.key === 'trip' || form.selectedKeys.includes(item.key), after: item.key === 'trip' ? { start: form.start, end: form.end } : form.selectedKeys.includes(item.key) ? { start: '2027-03-20', end: '2027-03-22' } : { ...item.before } })), warnings: [], blockingIssues: [], canApply: true, previewToken: 'signed-preview', expiresIn: 1800 };
}
const intent = () => ({ body: Object.freeze({ previewToken: 'signed-preview', idempotencyKey: operation }), start: '2027-03-20', end: '2027-03-23', uncertain: false });
const receipt = () => ({ id: jid, tripId, revision: 8, replayed: false, operation: 'reschedule', reschedule: { start: '2027-03-20', end: '2027-03-23', changedKeys: ['trip', 'task:prepare'] }, calendar: { local: 'updated', cloud: 'status_not_checked' } });
const http = error => typeof error?.status === 'number' ? { status: error.status, code: error.code } : undefined;
const apiError = (status, code = '') => Object.assign(new Error('endpoint'), { status, code });
const session = () => ({ user: { role: 'member', householdId: 'first', id: 'a', auth_version: 1 }, csrf: 'first-session' });

test('opening is keep-only; request projects dates and explicit keys without modifying the original snapshot', () => {
  const snapshot = source(), form = initialRescheduleDraft(snapshot), original = JSON.stringify(snapshot);
  assert.deepEqual(form.selectedKeys, []);
  form.start = '2027-04-01'; form.end = '2027-04-03'; form.owner = 'foreign'; form.plan = { private: 'injected' };
  assert.deepEqual(reschedulePayload(snapshot, form), { snapshotToken: 'signed-original', start: '2027-04-01', end: '2027-04-03', selectedKeys: [] });
  assert.equal(JSON.stringify(snapshot), original);
});
test('changing proposed dates repeatedly never shifts source or protected history', () => {
  const snapshot = source(), form = draft();
  const first = reschedulePayload(snapshot, form), second = reschedulePayload(snapshot, { ...form, start: '2027-04-20', end: '2027-04-23' });
  assert.equal(first.snapshotToken, second.snapshotToken); assert.equal(snapshot.items[3].before.start, '2027-03-10');
  for (const key of ['trip', 'task:complete', 'shopping:coffee', 'place:foreign']) assert.throws(() => reschedulePayload(snapshot, { ...form, selectedKeys: [key] }));
  assert.throws(() => reschedulePayload(snapshot, { ...form, selectedKeys: ['task:prepare', 'task:prepare'] }));
});
test('strict leap days, range limits and invalid partial values fail before preview request', () => {
  assert.equal(validRescheduleDay('2028-02-29'), true); assert.equal(validRescheduleDay('2027-02-29'), false);
  for (const [start, end] of [['2027-3-10', '2027-03-12'], ['1999-01-01', '2000-01-01'], ['2027-03-12', '2027-03-10'], ['', '2027-03-12'], ['2027-01-01', '2028-01-04']]) assert.throws(() => reschedulePayload(source(), { ...draft(), start, end }));
});
test('snapshot rejects foreign identity, duplicate keys, unsupported kinds and dishonest shopping capabilities', () => {
  for (const patch of [{ journeyId: tripId }, { revision: 0 }, { revision: 1.5 }, { capabilities: { shoppingDue: true } }]) assert.throws(() => readRescheduleSnapshot({ ...rawSource(), ...patch }, jid));
  for (const invalid of [{ ...row('task:bad', 'task'), kind: 'calendar' }, row('trip', 'overview', true), row('segment:evil/../../', 'segment')]) {
    const value = rawSource(); value.items.push(invalid); assert.throws(() => readRescheduleSnapshot(value, jid));
  }
  const duplicate = rawSource(); duplicate.items.push(duplicate.items[1]); assert.throws(() => readRescheduleSnapshot(duplicate, jid));
});
test('full existing 3000 places plus all plan rows fit source projection and twelve-item pages', () => {
  const value = rawSource(); value.items = [row('trip', 'overview', false), ...Array.from({ length: 20 }, (_, n) => row('destination:d' + n, 'destination'))];
  for (const kind of ['segment', 'task', 'shopping']) value.items.push(...Array.from({ length: 100 }, (_, n) => row(kind + ':k' + n, kind, kind !== 'shopping')));
  value.items.push(...Array.from({ length: 3000 }, (_, n) => row('place:' + n.toString(16).padStart(24, '0'), 'place')));
  const all = readRescheduleSnapshot(value, jid); assert.equal(all.items.length, 3321);
  const places = all.items.filter(item => item.kind === 'place'), visited = [];
  for (let page = 0; page < 250; page++) { const result = pageItems(places, page); assert.equal(result.pages, 250); assert.equal(result.items.length, 12); visited.push(...result.items.map(item => item.key)); }
  assert.equal(new Set(visited).size, 3000); assert.equal(pageItems(places, 999).page, 249);
});
test('snapshot fingerprint ignores a newly signed token but catches dates, revisions and protection changes', () => {
  const snapshot = source(); assert.equal(snapshotVersion(snapshot), snapshotVersion({ ...snapshot, snapshotToken: 'resigned' }));
  for (const patch of [{ revision: 8 }, { start: '2027-03-11' }, { items: snapshot.items.map(item => item.key === 'task:prepare' ? { ...item, eligible: false, reason: 'completed' } : item) }]) assert.notEqual(snapshotVersion(snapshot), snapshotVersion({ ...snapshot, ...patch }));
});
test('conflict rebase retains date draft and explicitly reports newly protected or removed choices', () => {
  const snapshot = source(), form = { ...draft(), selectedKeys: ['task:prepare', 'segment:flight'], timeOverrides: { 'segment:flight': { start: { local: '2027-03-20T03:30' } } } };
  const next = { ...snapshot, revision: 8, items: snapshot.items.map(item => item.key === 'segment:flight' ? { ...item, eligible: false } : item) };
  const result = rebaseRescheduleDraft(form, next); assert.equal(result.draft.start, form.start); assert.deepEqual(result.removed, ['segment:flight']); assert.deepEqual(result.draft.selectedKeys, ['task:prepare']); assert.deepEqual(result.draft.timeOverrides, {}); assert.equal(form.selectedKeys.length, 2);
});
test('DST correction carries local wall clock and explicit chosen offset, never edits the timezone', () => {
  const form = { ...draft(), selectedKeys: ['segment:flight'], timeOverrides: { 'segment:flight': { start: { local: '2027-11-07T01:30', offsetMinutes: -300, timeZone: 'injected' } } } };
  assert.deepEqual(reschedulePayload(source(), form).timeOverrides, { 'segment:flight': { start: { local: '2027-11-07T01:30', offsetMinutes: -300 } } });
  assert.deepEqual(localOverride({ local: '2027-03-14T03:30:00', offsetMinutes: -240 }), { local: '2027-03-14T03:30:00', offsetMinutes: -240 });
  for (const raw of [{ local: '2027-02-29T03:30' }, { local: '2027-03-14T24:00' }, { local: '2027-03-14T03:30Z' }, { local: '2027-03-14T03:30', offsetMinutes: 1.5 }, { local: '2027-03-14T03:30', offsetMinutes: 841 }]) assert.throws(() => localOverride(raw));
  assert.throws(() => reschedulePayload(source(), { ...form, selectedKeys: [] }));
});
test('preview must agree with the original snapshot, dates, selected rows and preserved rows', () => {
  assert.equal(readReschedulePreview(preview(), source(), draft()).canApply, true);
  const variations = [value => value.journeyId = tripId, value => value.revision++, value => value.start = '2027-04-01', value => value.items[1].selected = true, value => value.items[1].after.start = '2027-04-01', value => value.items[3].before.start = '2027-03-09', value => value.items.pop()];
  for (const patch of variations) { const value = preview(); patch(value); assert.throws(() => readReschedulePreview(value, source(), draft())); }
});
test('blocked DST preview accepts structured corrections and never enables confirmation', () => {
  const form = { ...draft(), selectedKeys: ['segment:flight'] }, value = preview(source(), form);
  value.canApply = false; value.previewToken = null; value.blockingIssues = [{ code: 'ambiguous_local_time', key: 'segment:flight', field: 'start', message: '请选择偏移', local: '2027-11-07T01:30', timeZone: 'America/New_York', choices: [{ offsetMinutes: -240, instant: '2027-11-07T05:30:00Z' }, { offsetMinutes: -300, instant: '2027-11-07T06:30:00Z' }] }];
  const result = readReschedulePreview(value, source(), form); assert.equal(result.canApply, false); assert.equal(result.blockingIssues[0].choices.length, 2);
  value.canApply = true; value.previewToken = 'bad'; assert.throws(() => readReschedulePreview(value, source(), form));
});
test('confirmation retains precise clock and offset changes even when calendar dates do not change', () => {
  const raw = rawSource(); raw.items[2].timeBefore = { start: { local: '2027-03-10T01:30:00', timeZone: 'America/New_York', offsetMinutes: -300 }, end: { local: '2027-03-12T04:30:00', timeZone: 'America/New_York', offsetMinutes: -300 } };
  const snapshot = readRescheduleSnapshot(raw, jid), form = { ...draft(), selectedKeys: ['segment:flight'] }, value = preview(snapshot, form);
  value.items[2].timeAfter = { start: { local: '2027-03-20T03:30:00', timeZone: 'America/New_York', offsetMinutes: -240 }, end: { local: '2027-03-22T04:30:00', timeZone: 'America/New_York', offsetMinutes: -240 } };
  const result = readReschedulePreview(value, snapshot, form);
  assert.equal(clockText(result.items[2].timeAfter.start), '2027-03-20 03:30:00 · America/New_York · UTC-04:00');
  assert.equal(offsetText(330), 'UTC+05:30'); assert.equal(offsetText(0), 'UTC+00:00');
  delete value.items[2].timeAfter; assert.throws(() => readReschedulePreview(value, snapshot, form));
});
test('per-row warnings above item count remain complete and are bounded into pages', () => {
  const value = preview(); value.warnings = Array.from({ length: 6004 }, (_, n) => ({ code: 'outside_trip_dates', key: null, message: '保留原日期 ' + n }));
  const result = readReschedulePreview(value, source(), draft()); assert.equal(result.warnings.length, 6004);
  assert.equal(pageItems(result.warnings, 500).items.length, 4); assert.equal(pageItems(result.warnings, 500).pages, 501);
});
test('historical receipt is bound to original operation and proposed dates, with no current snapshot installation', () => {
  const original = intent(), value = receipt(); assert.equal(readRescheduleReceipt(value, jid, original).revision, 8);
  assert.equal(readRescheduleOperation({ found: true, idempotencyKey: operation, result: value }, jid, original).id, jid);
  for (const patch of [{ found: false }, { idempotencyKey: 'e'.repeat(32) }, { result: { ...value, id: tripId } }, { result: { ...value, operation: 'create' } }, { result: { ...value, reschedule: { ...value.reschedule, start: '2027-03-21' } } }]) assert.throws(() => readRescheduleOperation({ found: true, idempotencyKey: operation, result: value, ...patch }, jid, original));
});
test('real persisted receipt omits transport replayed; only a matching operation lookup normalizes it', () => {
  const stored = receipt(); delete stored.replayed;
  assert.throws(() => readRescheduleReceipt(stored, jid, intent()));
  const found = readRescheduleOperation({ found: true, idempotencyKey: operation, result: stored }, jid, intent());
  assert.equal(found.replayed, true); assert.equal(found.revision, 8); assert.equal(Object.hasOwn(stored, 'replayed'), false);
  assert.throws(() => readRescheduleOperation({ found: true, idempotencyKey: 'd'.repeat(32), result: stored }, jid, intent()));
});
test('endpoint rejection is definitive only after both identity reads succeed', async () => {
  const who = session(); let reads = 0; const fence = new PlaceFence(async () => { reads++; return who; }, placeSignature(who));
  let failure; try { await checkedRescheduleWrite(action => fence.run(action, () => true), async () => { throw apiError(409, 'stale_preview'); }, http); } catch (error) { failure = error; }
  assert.ok(failure instanceof RescheduleRejected); assert.equal(failure.code, 'stale_preview'); assert.equal(reads, 2); assert.equal(failedRescheduleIntent(intent(), failure), null);
});
test('lost success or invalid receipt keeps the exact original key; later 400/409 cannot turn unknown into a new operation', () => {
  const original = intent();
  for (const failure of [apiError(0), apiError(408), apiError(503), new Error('malformed receipt')]) {
    const pending = failedRescheduleIntent(original, failure); assert.equal(pending.uncertain, true); assert.equal(pending.body, original.body);
    for (const status of [400, 409, 410]) { const later = failedRescheduleIntent(pending, new RescheduleRejected(status, 'expired')); assert.equal(later.body, original.body); assert.equal(later.uncertain, true); }
  }
});
test('internal exit stays locked while a write is in flight or any original intent remains unresolved', () => {
  assert.equal(mayExitReschedule(null, true), false); assert.equal(mayExitReschedule(intent(), false), false);
  const unresolved = failedRescheduleIntent(intent(), apiError(0)); assert.equal(mayExitReschedule(unresolved, false), false);
  const later = failedRescheduleIntent(unresolved, new RescheduleRejected(400, 'expired')); assert.equal(mayExitReschedule(later, false), false);
  const rejected = failedRescheduleIntent(intent(), new RescheduleRejected(409, 'stale')); assert.equal(mayExitReschedule(rejected, false), true);
  assert.equal(mayExitReschedule(null, false), true);
});
test('post-write identity failures 401/403/408/429 conceal and preserve unknown instead of unlocking a retry with a new key', async () => {
  for (const status of [401, 403, 408, 429]) {
    const who = session(); let reads = 0, writes = 0;
    const fence = new PlaceFence(async () => { if (++reads === 2) throw apiError(status); return who; }, placeSignature(who));
    let failure; try { await checkedRescheduleWrite(action => fence.run(action, () => true), async () => { writes++; return receipt(); }, http); } catch (error) { failure = error; }
    assert.ok(failure instanceof RescheduleUnverified); assert.equal(writes, 1); assert.equal(failedRescheduleIntent(intent(), failure).uncertain, true);
  }
});
test('member, household and CSRF changes discard delayed private success and failure alike', async () => {
  for (const patch of [{ user: { ...session().user, id: 'b' } }, { user: { ...session().user, householdId: 'other' } }, { csrf: 'different' }]) {
    for (const fails of [false, true]) {
      const first = session(); let who = first; const fence = new PlaceFence(async () => who, placeSignature(first));
      await assert.rejects(fence.run(async () => { who = { ...first, ...patch }; if (fails) throw apiError(404); return rawSource(); }, () => true), PlaceDiscarded);
    }
  }
});
test('a background epoch makes earlier private success and error unusable after foreground reentry', async () => {
  for (const fails of [false, true]) {
    const who = session(), fence = new PlaceFence(async () => who, placeSignature(who)); let release;
    const deferred = new Promise(resolve => { release = resolve; });
    const pending = fence.run(async () => { await deferred; if (fails) throw apiError(409); return rawSource(); }, () => true);
    await Promise.resolve(); fence.invalidate(); release(); await assert.rejects(pending, PlaceDiscarded);
  }
});
