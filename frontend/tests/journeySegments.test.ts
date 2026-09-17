import assert from 'node:assert/strict';
import test from 'node:test';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import type * as Model from '../src/lib/journeySegments';
const m: typeof Model = await import(new URL('../src/lib/journeySegments.ts', import.meta.url).href);

const root = fileURLToPath(new URL('../../', import.meta.url));
// Real temporary Flask/SQLite; no fabricated successful business DTOs.
const python = String.raw`
import copy,json,os,socket,sys,tempfile
from pathlib import Path
if os.environ.get('JOURNEY_MODEL_BACKEND_ROOT'):
    sys.path.insert(0,os.environ['JOURNEY_MODEL_BACKEND_ROOT'])
os.environ['MEMBER1_PASSWORD']='testing-password-one'
os.environ['MEMBER2_PASSWORD']='testing-password-two'
def blocked(*a,**k): raise AssertionError('Network is forbidden in the DTO fixture')
socket.create_connection=blocked
socket.socket.connect=blocked
from app import create_app
def checked(r,status=200):
    assert r.status_code==status,(r.status_code,r.json)
    return r.json
with tempfile.TemporaryDirectory(prefix='journey-segment-dto-') as directory:
    app=create_app({'TESTING':True,'SECRET_KEY':'isolated-segments-test-secret','DATA_DIR':directory,'SESSION_COOKIE_SECURE':False})
    c=app.test_client()
    checked(c.post('/api/login',json={'username':'member1','password':'testing-password-one'}))
    session=checked(c.get('/api/me'));h={'X-CSRF-Token':session['csrf']}
    def preview(plan,**extra):return checked(c.post('/api/journeys/preview',json={'plan':plan,**extra},headers=h))
    def apply(p,k,status):return checked(c.post('/api/journeys/apply',json={'previewToken':p['previewToken'],'idempotencyKey':k},headers=h),status)
    def versions(d):return {x['id']:x['revision'] for x in [d['trip'],*d['tasks'],*d['shopping'],*d['events']] if x}
    v1={'title':'Two cities','start':'2027-10-01','end':'2027-10-12','international':True,'memberIds':['member1','member2'],'budget':123456789,'saved':23456,'paid':789,'note':'原计划\n保留',
        'destinations':[{'key':'old-city','city':'东京','country':'日本','arrival':'2027-10-01','departure':'2027-10-12'}],
        'shopping':[{'key':'unknown','title':'未知预算','owner':'member2','quantity':'1','budget':None},{'key':'free','title':'零预算','owner':'shared','quantity':'1','budget':0}],
        'segments':[{'key':'old-segment','title':'原全天','start':'2027-10-02','end':'2027-10-03'}]}
    one=apply(preview(v1),'model-v1-initial',201);d1=checked(c.get('/api/journeys/'+one['id']))
    v2=json.loads(Path('static/examples/journey-plan-v2.json').read_text(encoding='utf8'));v2['memberIds']=['member1','member2']
    v2['segments'] += [{'key':'timed','kind':'activity','title':'有时刻活动','start':{'local':'2027-10-09T10:00','timeZone':'Europe/Paris'},'end':{'local':'2027-10-09T12:00','timeZone':'Europe/Paris'}},
                       {'key':'legacy','kind':'legacy_day','title':'保留日期','start':'2027-10-01','end':'2027-10-01'}]
    initial=preview(v2);two=apply(initial,'model-v2-initial',201);d2=checked(c.get('/api/journeys/'+two['id']))
    changed=copy.deepcopy(d2['plan']);changed['segments'][0]['title']='确认后的航班说明'
    p2=preview(changed,journeyId=d2['id'],revision=d2['revision'],expectedEntities=versions(d2));receipt=apply(p2,'model-v2-update',200)
    replay=apply(p2,'model-v2-update',200);operation=checked(c.get('/api/journeys/operations/model-v2-update'))
    latest=checked(c.get('/api/journeys/'+d2['id']))
    event=next(x for x in latest['events'] if x['workflowKey']=='segment:'+changed['segments'][0]['key'])
    checked(c.patch('/api/items/events/'+event['id'],json={'revision':event['revision'],'title':'日历中独立修改','owner':'member2'},headers=h))
    manual=checked(c.get('/api/journeys/'+d2['id']))
    preserved=preview(manual['plan'],journeyId=manual['id'],revision=manual['revision'])
    conflict_plan=copy.deepcopy(manual['plan']);conflict_plan['segments'][0]['title']='另一个计划标题'
    conflict=preview(conflict_plan,journeyId=manual['id'],revision=manual['revision'])
    choices={conflict['summary']['conflicts'][0]['itemKey']:{'title':'current'}}
    resolved=preview(conflict_plan,journeyId=manual['id'],revision=manual['revision'],conflictResolutions=choices)
    dst=copy.deepcopy(manual['plan']);dst['segments'][0]['departure']={'local':'2026-11-01T01:30','timeZone':'America/New_York','airport':'JFK','city':'纽约'}
    issue=checked(c.post('/api/journeys/preview',json={'plan':dst,'journeyId':manual['id'],'revision':manual['revision']},headers=h),400)
    checked(c.patch('/api/items/tasks/'+d1['tasks'][0]['id'],json={'revision':d1['tasks'][0]['revision'],'due':''},headers=h))
    cleared=checked(c.get('/api/journeys/'+d1['id']))
    checked(c.delete('/api/items/tasks/'+cleared['tasks'][0]['id'],json={'revision':cleared['tasks'][0]['revision']},headers=h))
    deleted_task=checked(c.get('/api/journeys/'+d1['id']))
    checked(c.delete('/api/items/shopping/'+d2['shopping'][0]['id'],json={'revision':manual['shopping'][0]['revision']},headers=h))
    deleted_purchase=checked(c.get('/api/journeys/'+d2['id']))
    # Existing full-plan editing can explicitly detach a task while preserving
    # its standalone record. A coherent plan/link result remains editable.
    detach_plan=copy.deepcopy(deleted_task['plan']);detach_plan['checklist']=[]
    result=apply(preview(detach_plan,journeyId=deleted_task['id'],revision=deleted_task['revision'],expectedEntities=versions(deleted_task)),'model-detach-checklist',200)
    detached=checked(c.get('/api/journeys/'+d1['id']))
    state=checked(c.get('/api/state'))
    assert any(row['id']==d1['tasks'][1]['id'] for row in state['tasks'])
    print(json.dumps({'cleared':cleared,'deletedTask':deleted_task,'deletedPurchase':deleted_purchase,'detached':detached,'session':session,'capabilities':checked(c.get('/api/journeys/templates')),'v1':d1,'v2':d2,'initialPreview':initial,'preview':p2,'receipt':receipt,'replay':replay,'operation':operation,'latest':latest,'manual':manual,'preserved':preserved,'conflict':conflict,'resolved':resolved,'dstPlan':dst,'issue':issue},ensure_ascii=False))
`;
const produced = spawnSync(process.env.JOURNEY_MODEL_PYTHON || 'python', ['-B', '-X', 'utf8', '-c', python], { cwd: root, encoding: 'utf8', maxBuffer: 8_000_000 });
assert.equal(produced.status, 0, produced.stderr + produced.stdout);
const dto = JSON.parse(produced.stdout);
const caps = m.readCapabilities(dto.capabilities);
const members = ['member1', 'member2'];
const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v));
const d2 = () => m.readJourneyDetail(dto.v2, dto.v2.id);
const draft = () => m.editSegmentDraft(d2());

test('real normalized v2 DTO preserves every supported kind and all nonsegment plan data', () => {
  const d = d2(), edit = m.editSegmentDraft(d);
  assert.deepEqual(edit.plan, d.plan);
  assert.equal(edit.plan.schemaVersion, 2);
  assert.deepEqual(new Set(edit.plan.segments.map(s => 'kind' in s ? s.kind : null)), new Set(['flight', 'stay', 'activity', 'legacy_day']));
  const body = m.previewPayload(edit, caps, members);
  assert.equal(body.journeyId, d.id); assert.equal(body.revision, d.revision); assert.equal(caps.editSourceSnapshot, true);
  assert.deepEqual(body.expectedEntities, Object.fromEntries([d.trip!, ...d.tasks, ...d.shopping, ...d.events].map(x => [x.id, x.revision])));
  assert.deepEqual(body.plan.checklist, d.plan.checklist);
  assert.deepEqual(body.plan.shopping, d.plan.shopping);
  assert.deepEqual([body.plan.budget, body.plan.saved, body.plan.paid, body.plan.memberIds], [d.plan.budget, d.plan.saved, d.plan.paid, d.plan.memberIds]);
});

test('actual independently edited event owner remains a valid preserved preview field', () => {
  const preview = m.readSegmentPreview(dto.preserved);
  assert.ok(preview.summary.preserved.some(row => row.fieldGroup === 'owner' && row.current.owner === 'member2'));
});

test('actual task due clearing cannot silently restore the old plan deadline', () => {
  const d = m.readJourneyDetail(dto.cleared); assert.equal(d.tasks[0].due, '');
  assert.throws(() => m.editSegmentDraft(d), /清空截止日期/);
});
test('actual task deletion cannot recreate a checklist item through segment editing', () => {
  const d = m.readJourneyDetail(dto.deletedTask); assert.equal(d.tasks.length, d.plan.checklist.length - 1);
  assert.throws(() => m.editSegmentDraft(d), /准备事项.*删除或解除关联/);
});
test('actual purchase deletion cannot recreate a shopping item through segment editing', () => {
  const d = m.readJourneyDetail(dto.deletedPurchase); assert.equal(d.shopping.length, d.plan.shopping.length - 1);
  assert.throws(() => m.editSegmentDraft(d), /采购事项.*删除或解除关联/);
});
test('explicit full-plan detachment retains independent records and its coherent result remains editable', () => {
  const d = m.readJourneyDetail(dto.detached), edit = m.editSegmentDraft(d);
  assert.deepEqual(edit.plan.checklist, []); assert.deepEqual(d.tasks, []);
  assert.deepEqual(edit.plan.shopping, d.plan.shopping);
});

test('explicit v1 upgrade preserves stable legacy keys, members, exact money and null versus zero', () => {
  const v1 = m.editSegmentDraft(m.readJourneyDetail(dto.v1));
  assert.equal(v1.plan.schemaVersion, undefined);
  assert.throws(() => m.previewPayload(v1, caps, members));
  const upgraded = m.upgradeToV2(v1, 'Asia/Shanghai', { 'old-city': 'Asia/Tokyo' }, caps);
  assert.equal(upgraded.plan.schemaVersion, 2);
  assert.deepEqual(upgraded.plan.segments[0], { ...v1.plan.segments[0], kind: 'legacy_day', bookingState: 'idea', datePolicy: 'shift_with_trip' });
  for (const field of ['memberIds', 'budget', 'saved', 'paid', 'checklist', 'shopping', 'start', 'end'] as const) assert.deepEqual(upgraded.plan[field], v1.plan[field]);
  assert.deepEqual(upgraded.plan.shopping.map(x => x.budget), [null, 0]);
  assert.equal(v1.plan.schemaVersion, undefined);
  assert.throws(() => m.upgradeToV2(v1, 'Asia/Shanghai', {}, caps));
});

test('missing capabilities, unknown versions, downgrade, duplicate keys and foreign members fail closed', () => {
  assert.equal(m.readCapabilities({}).canWriteV2, false);
  assert.equal(m.readCapabilities({ capabilities: { schemaVersions: [1, 2] } }).canWriteV2, false);
  assert.equal(m.readCapabilities({ capabilities: { schemaVersions: [1, 2], editSourceSnapshot: true } }).canWriteV2, true);
  assert.throws(() => m.previewPayload(draft(), m.readCapabilities({}), members));
  for (const mutate of [(p: any) => p.schemaVersion = 3, (p: any) => p.segments.push(clone(p.segments[0])), (p: any) => p.memberIds.push('foreign'), (p: any) => p.checklist[0].owner = 'foreign', (p: any) => p.destinations[0].arrival = '2027-02-30', (p: any) => p.budget = 1.25]) {
    const d = draft(); mutate(d.plan); assert.throws(() => m.previewPayload(d, caps, members));
  }
  const d = draft(); (d.plan as any).schemaVersion = 1; assert.throws(() => m.previewPayload(d, caps, members));
  const swapped = draft(); swapped.expectedEntities[swapped.tripId]++; assert.throws(() => m.previewPayload(swapped, caps, members));
});

test('20 destinations and 100 segments accepted; capacity plus one and dangling destination rejected', () => {
  const d = draft(); assert.equal(d.plan.schemaVersion, 2); if (d.plan.schemaVersion !== 2) return;
  const sample = d.plan.destinations[0]; d.plan.destinations = Array.from({ length: 20 }, (_, i) => ({ ...sample, key: 'd' + i }));
  d.plan.segments = Array.from({ length: 100 }, (_, i) => ({ key: 's' + i, kind: 'legacy_day', title: 'Day', start: '2027-10-01', end: '2027-10-01', location: '', note: '', bookingState: 'idea', datePolicy: 'fixed', destinationKey: 'd0' }));
  assert.equal(m.previewPayload(d, caps, members).plan.segments.length, 100);
  const excess = clone(d); excess.plan.destinations.push({ ...sample, key: 'd20' }); assert.throws(() => m.previewPayload(excess, caps, members));
  d.plan.segments.push({ ...d.plan.segments[0], key: 's100' }); assert.throws(() => m.previewPayload(d, caps, members));
  d.plan.segments.pop(); d.plan.segments[0].destinationKey = 'missing'; assert.throws(() => m.previewPayload(d, caps, members));
});

test('local date/zone edits remove old UTC and fold choice without moving other endpoints', () => {
  const p = { local: '2026-11-01T01:30:00', timeZone: 'America/New_York', offsetMinutes: -240, instant: '2026-11-01T05:30:00Z', airport: 'JFK', city: '纽约' };
  assert.deepEqual(m.updateTimePoint(p, { local: p.local }), p);
  const changed = m.updateTimePoint(p, { local: '2026-11-01T02:30' });
  assert.equal(changed.offsetMinutes, undefined); assert.equal(changed.instant, undefined); assert.equal(changed.airport, 'JFK'); assert.equal(p.offsetMinutes, -240);
  assert.equal(m.updateTimePoint(p, { timeZone: 'Europe/Paris' }).instant, undefined);
  assert.throws(() => m.updateTimePoint(p, { instant: 'forged' } as any));
});

test('overview edits never shift retained dates, completed preparation or money; malformed normalized clocks reject', () => {
  const d = draft(), before = clone(d.plan); d.plan.start = '2030-01-01'; d.plan.end = '2030-01-12';
  const p = m.previewPayload(d, caps, members).plan;
  assert.deepEqual(p.destinations, before.destinations); assert.deepEqual(p.segments, before.segments); assert.deepEqual(p.checklist, before.checklist); assert.deepEqual(p.shopping, before.shopping);
  assert.deepEqual([p.budget, p.saved, p.paid], [before.budget, before.saved, before.paid]);
  const malformed = clone(dto.preview); malformed.plan.segments[0].arrival.instant = malformed.plan.segments[0].departure.instant;
  assert.throws(() => m.readSegmentPreview(malformed));
  const overflow = clone(dto.preview); overflow.plan.segments[0].unexpectedTime = 'not preserved silently'; assert.throws(() => m.readSegmentPreview(overflow));
});

test('unknown hotel clocks remain unknown and changes invalidate only derived timing', () => {
  const p = m.readSegmentPreview(dto.initialPreview).plan.segments.find(s => s.kind === 'stay') as Model.Stay;
  assert.equal(p.checkInTime, ''); assert.equal(p.checkInInstant, undefined);
  const changed = m.updateStayTiming({ ...p, checkInTime: '10:00', checkInInstant: '2027-10-01T01:00:00Z', checkInOffsetMinutes: 540 }, { checkInTime: '' });
  assert.equal(changed.checkInInstant, undefined); assert.equal(changed.checkInOffsetMinutes, undefined); assert.equal(changed.checkInTime, '');
  assert.equal(m.updateStayTiming(p, { checkOutDate: '2027-10-08' }).nights, undefined);
  assert.equal(m.newSegment('flight').kind, 'flight'); assert.equal((m.newSegment('flight') as Model.Flight).departure.local, '');
});

test('actual DST choices require the same draft and exact field, and never install guessed UTC', () => {
  const d = draft(); d.plan = clone(dto.dstPlan); const issue = m.readTimeIssue(dto.issue, d);
  assert.equal(issue.code, 'ambiguous_local_time'); assert.equal(issue.choices.length, 2);
  const chosen = m.applyTimeChoice(d, issue, issue.choices[0].offsetMinutes);
  const s = (chosen.plan as Model.JourneyPlanV2).segments[0] as Model.Flight;
  assert.equal(s.departure.offsetMinutes, issue.choices[0].offsetMinutes); assert.equal(s.departure.instant, undefined);
  assert.throws(() => m.applyTimeChoice(d, issue, 123));
  const edited = clone(d); edited.plan.title += ' changed'; assert.throws(() => m.applyTimeChoice(edited, issue, issue.choices[0].offsetMinutes));
  assert.throws(() => m.applyTimeChoice(d, { ...issue, field: 'referenceTimezone' }, issue.choices[0].offsetMinutes));
});

test('real preserved/conflict/resolved summaries require exact supported field groups', () => {
  assert.ok(m.readSegmentPreview(dto.preserved).summary.preserved.length);
  const p = m.readSegmentPreview(dto.conflict); assert.equal(p.canApply, false); assert.equal(p.previewToken, null); assert.equal(p.summary.conflicts[0].fieldGroup, 'title');
  assert.equal(m.readSegmentPreview(dto.resolved).summary.resolved[0].resolution, 'current');
  const d = m.editSegmentDraft(m.readJourneyDetail(dto.manual));
  assert.throws(() => m.previewPayload(d, caps, members, { 'segment:x': { budget: 'plan' } } as any));
  const broken = clone(dto.conflict); broken.canApply = true; assert.throws(() => m.readSegmentPreview(broken));
});

test('fresh entity revisions require review; explicit rebase keeps only editing scope and current nonedited values', () => {
  const d = draft(); if (d.plan.schemaVersion !== 2) return; d.plan.segments[0].title = '草稿标题';
  const latest = m.readJourneyDetail(dto.manual); assert.notEqual(m.detailFingerprint(latest), d.observed);
  latest.trip!.budget = 77; latest.trip!.saved = 66; latest.trip!.paid = 55;
  const next = m.rebaseSegmentDraft(d, latest);
  assert.equal(next.plan.budget, 77); assert.equal(next.plan.saved, 66); assert.equal(next.plan.paid, 55);
  assert.equal(next.plan.segments[0].title, '草稿标题'); assert.equal(next.observed, m.detailFingerprint(latest));
  assert.throws(() => m.rebaseSegmentDraft(d, m.readJourneyDetail(dto.v1)));
});

test('actual update/replay and historical receipt are matched to the original journey, key and version', () => {
  const intent = m.createSegmentIntent(m.readSegmentPreview(dto.preview), draft(), 'model-v2-update');
  assert.equal(m.readSegmentReceipt(dto.receipt, intent).replayed, false);
  assert.equal(m.readSegmentReceipt(dto.replay, intent).replayed, true);
  assert.equal(dto.operation.result.replayed, undefined);
  assert.equal(m.readSegmentOperation(dto.operation, intent).replayed, true);
  assert.throws(() => m.readSegmentOperation({ ...dto.operation, idempotencyKey: 'some-other-key' }, intent));
  assert.throws(() => m.readSegmentReceipt({ ...dto.receipt, operation: 'reschedule' }, intent));
  assert.throws(() => m.readSegmentReceipt({ ...dto.receipt, tripId: '0'.repeat(24) }, intent));
  const unknown = { ...intent, uncertain: true }; assert.equal(m.failedSegmentIntent(unknown, new m.SegmentRejected('expired', 409))!.body, unknown.body);
  assert.equal(m.failedSegmentIntent(intent, new m.SegmentRejected('first request rejected', 409)), null);
  assert.ok(m.failedSegmentIntent(intent, new m.SegmentError('not found', 404)));
});

test('identity fence validates CSRF, role, household, version and rejects late background results', async () => {
  const session = dto.session as Model.SegmentSession, fence = new m.SegmentFence(m.segmentSignature(session));
  assert.equal(await fence.run(async () => session, async () => 42, () => true), 42);
  for (const changed of [{ ...session, csrf: 'new' }, { ...session, user: { ...session.user!, householdId: 'other' } }, { ...session, user: { ...session.user!, role: 'tv' as const } }]) {
    let calls = 0; await assert.rejects(fence.run(async () => ++calls === 1 ? session : changed, async () => 42, () => true), m.SegmentDiscarded);
  }
  await assert.rejects(fence.run(async () => session, async () => { fence.invalidate(); return 42; }, () => true), m.SegmentDiscarded);
});

test('only an endpoint rejection after successful post-me may unlock; 401, 410 and late me errors retain intent', async () => {
  const original = globalThis.fetch; const signal = new AbortController().signal;
  const guard: Model.SegmentGuard = async job => job('csrf');
  try {
    globalThis.fetch = async () => new Response(JSON.stringify({ error: 'stale preview' }), { status: 409, headers: { 'Content-Type': 'application/json' } });
    await assert.rejects(m.checkedSegmentWrite(guard, csrf => m.segmentRequest('/journeys/apply', signal, { method: 'POST', csrf, payload: {} })), m.SegmentRejected);
    const late: Model.SegmentGuard = async job => { await job('csrf'); throw new m.SegmentError('me rejected', 409); };
    await assert.rejects(m.checkedSegmentWrite(late, csrf => m.segmentRequest('/journeys/apply', signal, { method: 'POST', csrf, payload: {} })), e => e instanceof m.SegmentError && !(e instanceof m.SegmentRejected));
    for (const status of [401, 408, 410, 500]) { globalThis.fetch = async () => new Response('{}', { status, headers: { 'Content-Type': 'application/json' } }); await assert.rejects(m.checkedSegmentWrite(guard, csrf => m.segmentRequest('/journeys/apply', signal, { method: 'POST', csrf, payload: {} })), e => !(e instanceof m.SegmentRejected)); }
  } finally { globalThis.fetch = original; }
});

test('transport rejects arbitrary paths and preserves same-origin no-store no-redirect rules', async () => {
  const original = globalThis.fetch; let calls = 0;
  try {
    globalThis.fetch = async (_url, init) => { calls++; assert.equal(init!.mode, 'same-origin'); assert.equal(init!.cache, 'no-store'); assert.equal(init!.redirect, 'error'); assert.equal(init!.credentials, 'same-origin'); return new Response('{}', { headers: { 'Content-Type': 'application/json' } }); };
    await assert.rejects(m.segmentRequest('https://example.invalid', new AbortController().signal)); assert.equal(calls, 0);
    await assert.rejects(m.segmentRequest('/journeys/apply', new AbortController().signal, { method: 'DELETE' } as any)); assert.equal(calls, 0);
    await m.segmentRequest('/journeys/templates', new AbortController().signal); assert.equal(calls, 1);
    const aborted = new AbortController(); aborted.abort(); await assert.rejects(m.segmentRequest('/me', aborted.signal)); assert.equal(calls, 1);
  } finally { globalThis.fetch = original; }
});
