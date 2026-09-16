import assert from 'node:assert/strict';
import { test } from 'node:test';
import { blankBriefStop, briefAmount, briefAmountText, briefDay, emptyBrief, journeyBriefPlan, journeyBriefRequest, journeyCheckedRead, preparedJourneyDraft, readJourneyBrief } from '../frontend/src/lib/journeyBrief.ts';
import { PhotoReadDiscarded, PhotoReadFence, photoSignature } from '../frontend/src/lib/photos.ts';

const people = [{ id: 'alice', name: '合成成员甲' }, { id: 'bob', name: '合成成员乙' }];
const stop = () => ({ country: '日本', city: '东京', arrival: '2027-10-01', departure: '2027-10-04' });
const brief = (patch = {}) => ({ mode: 'local', notice: '请补齐并核对', brief: { title: '合成旅行', start: '2027-10-01', end: '2027-10-04', budgetCents: 12345, international: true, destinations: [stop()], note: '不可信的模型备注', ...patch } });
const form = () => readJourneyBrief(brief(), '用户原文', ['alice']).form;
const normalized = () => ({ ...journeyBriefPlan(form(), people).plan, checklist: [{ key: 'packing', title: '合成行李准备', owner: 'shared', due: '2027-09-29', dueOffsetDays: -2, note: '建议需核对', category: 'preparation' }],
  segments: [{ key: 'brief-stop-1', title: '东京 · 停留', start: '2027-10-01', end: '2027-10-04', location: '日本 · 东京', note: '' }] });
const preview = (patch = {}) => ({ canApply: true, previewToken: 'discard-me', journeyId: 'existing', plan: { ...normalized(), ...patch } });

test('unknown budget stays empty and confirmed zero stays exact through the new plan', () => {
  const unknown = readJourneyBrief(brief({ budgetCents: null }), '原文', ['alice']).form;
  assert.equal(unknown.budget, ''); assert.throws(() => journeyBriefPlan(unknown, people), /明确旅行总预算/);
  const zero = readJourneyBrief(brief({ budgetCents: 0 }), '原文', ['alice']).form;
  assert.equal(zero.budget, '0.00'); assert.equal(journeyBriefPlan(zero, people).plan.budget, 0);
  assert.equal(emptyBrief().budget, ''); assert.equal(emptyBrief().international, null); assert.deepEqual(emptyBrief().memberIds, []);
});
test('budget accepts exact cents and rejects ambiguous and over-limit numbers', () => {
  assert.equal(briefAmount(' 123.45 '), 12345); assert.equal(briefAmount('0.01'), 1);
  assert.equal(briefAmount('1000000000.00'), 100000000000); assert.equal(briefAmountText(100000000000), '1000000000.00');
  for (const value of ['', '1,234', '1e2', '-1', '.1', '+1', '1.001', '1000000000.01', '两万元', 'USD 10', 1]) assert.throws(() => briefAmount(value));
  for (const value of [null, true, '100', NaN, 1.1, -1, 100000000001]) assert.throws(() => briefAmountText(value));
});
test('strict real dates and bounded travel interval are required', () => {
  assert.equal(briefDay('2024-02-29'), '2024-02-29'); assert.equal(briefDay('', true), '');
  for (const value of ['2027-02-29', '2027-04-31', '2027-1-01', '1999-12-31', '2101-01-01', '', null]) assert.throws(() => briefDay(value));
  assert.throws(() => journeyBriefPlan({ ...form(), end: '2027-09-30' }, people), /返程/);
  assert.throws(() => journeyBriefPlan({ ...form(), end: '2028-10-03' }, people), /367/);
  assert.throws(() => journeyBriefPlan({ ...form(), destinations: [{ ...stop(), arrival: '2027-09-30' }] }, people), /停留日期/);
  assert.throws(() => journeyBriefPlan({ ...form(), destinations: [{ ...stop(), departure: '2027-10-05' }] }, people), /停留日期/);
});
test('request includes only original text and explicit model choice', () => {
  assert.deepEqual(journeyBriefRequest(' 原文 ', false), { prompt: '原文', useModel: false });
  assert.deepEqual(journeyBriefRequest('', false), { prompt: '', useModel: false });
  assert.throws(() => journeyBriefRequest('', true)); assert.throws(() => journeyBriefRequest('原文', 'true'));
  assert.throws(() => journeyBriefRequest('a'.repeat(2001), false)); assert.throws(() => journeyBriefRequest('bad\u0000', false));
});
test('model identity, note, paid, actions and booking claims do not cross the brief boundary', () => {
  const result = readJourneyBrief(brief({ owner: 'bob', memberIds: ['bob'], id: 'existing', tripId: 'trip', journeyId: 'journey', revision: 100, previewToken: 'signed', publish: true, paid: 10, saved: 20,
    actions: ['save'], destinations: [{ ...stop(), id: 'foreign', owner: 'bob', bookingState: 'booked', timeZone: 'forged' }] }), '可信原文', ['alice']);
  assert.equal(result.form.note, '可信原文'); assert.deepEqual(result.form.memberIds, ['alice']);
  assert.deepEqual(result.form.destinations, [stop()]);
  const payload = journeyBriefPlan({ ...result.form, journeyId: 'injected', revision: 2, tripId: 'injected', previewToken: 'signed' }, people);
  assert.deepEqual(Object.keys(payload), ['plan']);
  assert.deepEqual(Object.keys(payload.plan).sort(), ['budget', 'destinations', 'end', 'international', 'memberIds', 'note', 'paid', 'saved', 'schemaVersion', 'shopping', 'start', 'title']);
  assert.equal(payload.plan.saved, 0); assert.equal(payload.plan.paid, 0); assert.equal(payload.plan.destinations[0].key, 'brief-stop-1');
  assert.equal(payload.plan.checklist, undefined);
});
test('member selection rejects empty, duplicate and foreign household identities', () => {
  for (const memberIds of [[], ['stranger'], ['alice', 'alice'], [null]]) assert.throws(() => journeyBriefPlan({ ...form(), memberIds }, people), /出行成员/);
  assert.deepEqual(journeyBriefPlan({ ...form(), memberIds: ['bob', 'alice'] }, people).plan.memberIds, ['bob', 'alice']);
  assert.throws(() => journeyBriefPlan({ ...form(), international: null }, people), /国内或境外/);
});
test('twenty destinations accepted, twenty-one rejected, dates and cities never guessed', () => {
  const twenty = Array.from({ length: 20 }, stop);
  const draft = journeyBriefPlan({ ...form(), destinations: twenty }, people).plan;
  assert.equal(draft.destinations.length, 20); assert.equal(draft.destinations[19].key, 'brief-stop-20');
  assert.throws(() => journeyBriefPlan({ ...form(), destinations: [...twenty, stop()] }, people));
  assert.throws(() => readJourneyBrief(brief({ destinations: [...twenty, stop()] }), '原文'));
  assert.throws(() => journeyBriefPlan({ ...form(), destinations: [] }, people));
  assert.throws(() => journeyBriefPlan({ ...form(), destinations: [blankBriefStop()] }, people));
  assert.deepEqual(readJourneyBrief(brief({ destinations: [] }), '原文').form.destinations, [blankBriefStop()]);
});
test('read validates types without coercing malformed model values or Unicode lengths', () => {
  for (const patch of [{ budgetCents: true }, { budgetCents: 1.1 }, { international: 'false' }, { start: '2027-02-29' }, { destinations: {} }, { title: 10 }]) assert.throws(() => readJourneyBrief(brief(patch), '原文'));
  assert.equal(readJourneyBrief(brief({ title: '😀'.repeat(100) }), '原文').form.title.length, 200);
  assert.throws(() => readJourneyBrief(brief({ title: '😀'.repeat(101) }), '原文'));
  assert.throws(() => readJourneyBrief({ ...brief(), mode: 'unknown' }, '原文'));
});
test('normalized preview retains editable defaults but removes all identities and authority', () => {
  const value = preview({ id: 'leak', journeyId: 'leak', revision: 2, tripRevision: 4, remoteId: 'foreign', previewToken: 'signed' });
  value.plan.checklist[0].id = 'old-task'; value.plan.checklist[0].done = true;
  value.plan.segments[0].remoteId = 'foreign'; value.plan.segments[0].publish = true;
  const draft = preparedJourneyDraft(value, people);
  assert.deepEqual(Object.keys(draft).sort(), ['budget', 'paid', 'plan', 'saved']);
  assert.equal(draft.budget, '123.45'); assert.equal(draft.plan.checklist[0].owner, 'shared');
  assert.equal(draft.plan.checklist[0].id, undefined); assert.equal(draft.plan.checklist[0].done, undefined);
  assert.equal(draft.plan.segments[0].remoteId, undefined); assert.equal(draft.plan.segments[0].publish, undefined);
  assert.equal(draft.plan.id, undefined); assert.equal(draft.plan.previewToken, undefined);
});
test('normalized preview refuses wrong members, version, amounts, owner and out-of-range rows', () => {
  for (const patch of [{ saved: 1 }, { paid: 1 }, { schemaVersion: 2 }, { shopping: [{ title: '未核对采购' }] }, { memberIds: ['foreign'] }, { budget: 1.1 }]) assert.throws(() => preparedJourneyDraft(preview(patch), people));
  let value = preview(); value.plan.checklist[0].owner = 'foreign'; assert.throws(() => preparedJourneyDraft(value, people));
  value = preview(); value.plan.checklist.push({ ...value.plan.checklist[0] }); assert.throws(() => preparedJourneyDraft(value, people));
  value = preview(); value.plan.segments[0].end = '2027-10-05'; assert.throws(() => preparedJourneyDraft(value, people));
});

const session = (patch = {}) => ({ user: { id: 'alice', householdId: 'synthetic-household', role: 'member', auth_version: 1 }, csrf: 'synthetic-csrf', ...patch });
test('success and endpoint failure both check identity before and after request', async () => {
  let reads = 0; const initial = session(), fence = new PhotoReadFence(async () => { reads++; return initial; }, initial.user, photoSignature(initial));
  assert.equal(await journeyCheckedRead(fence, async () => 42, () => true), 42); assert.equal(reads, 2);
  const failure = new Error('服务器拒绝');
  await assert.rejects(journeyCheckedRead(fence, async () => { throw failure; }, () => true), error => error === failure); assert.equal(reads, 4);
});
test('failure cannot disclose stale errors after household/member/CSRF/epoch changes', async () => {
  for (const next of [session({ csrf: 'changed' }), session({ user: { ...session().user, householdId: 'other' } }), session({ user: { ...session().user, id: 'bob' } }), session({ user: { ...session().user, auth_version: 2 } })]) {
    const initial = session(); let live = initial;
    const fence = new PhotoReadFence(async () => live, initial.user, photoSignature(initial));
    await assert.rejects(journeyCheckedRead(fence, async () => { live = next; throw new Error('private failure'); }, () => true), error => error instanceof PhotoReadDiscarded && error.message === 'identity');
  }
});
test('editing, closing or foreground invalidation suppresses an in-flight success and failure', async () => {
  for (const succeeds of [true, false]) {
    const initial = session(); let current = true;
    const fence = new PhotoReadFence(async () => initial, initial.user, photoSignature(initial));
    await assert.rejects(journeyCheckedRead(fence, async () => { current = false; fence.invalidate(); if (!succeeds) throw new Error('stale failure'); return 'stale success'; }, () => current), PhotoReadDiscarded);
    current = true;
    assert.equal(await journeyCheckedRead(fence, async () => 'fresh', () => current), 'fresh');
  }
});
