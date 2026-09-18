import assert from 'node:assert/strict';
import { test } from 'node:test';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';

// Optional source override lets an independent, frozen worktree supply the real
// implementation without copying its product files into this test worktree.
const moduleUrl = process.env.EXPO_DEVICES_SOURCE_ROOT
  ? pathToFileURL(resolve(process.env.EXPO_DEVICES_SOURCE_ROOT, 'frontend/src/lib/devices.ts'))
  : new URL('../frontend/src/lib/devices.ts', import.meta.url);
const { readDeviceLayout, readDevices, deviceDraft, defaultDeviceLayout, devicePayload, pairPayload,
  sameDeviceSettings, moveDeviceCard, toggleDeviceCard, readPlayback, playbackPayload,
  DeviceFence, deviceSignature, DeviceDiscarded, checkedDeviceMutation, DeviceWriteRejected } = await import(moduleUrl.href);

const id = 'a'.repeat(24), otherId = 'b'.repeat(24);
const people = [{ id: 'member1', name: '合成本人' }, { id: 'member2', name: '合成伴侣' }];
const device = () => ({ id, name: '合成电视', focus: 'member1', calendarView: 'week', revision: 3,
  created_at: '2026-09-17T11:30:00+08:00', layout: defaultDeviceLayout() });
const state = () => ({ deviceId: id, revision: 0, mode: 'dashboard', paused: false,
  intervalSeconds: 10, position: 0, photoCount: 0, canStart: false, updatedAt: null });
const photos = () => ({ ...state(), revision: 8, mode: 'photos', photoCount: 3, canStart: true,
  updatedAt: '2026-09-17T03:30:00Z' });
const session = () => ({ user: { role: 'member', householdId: 'default', id: 'member1', auth_version: 1 }, csrf: 'synthetic-csrf' });
const http = (status) => Object.assign(new Error('synthetic HTTP failure'), { status });
const status = error => error?.status;

test('device DTO projects public fields, rejects duplicate IDs and never retains a pairing secret', () => {
  const raw = device();
  assert.deepEqual(readDevices([{ ...raw, secret: 'synthetic', secret_hash: 'private', code: 'ABCDEFGH', approved: 1 }]), [raw]);
  assert.deepEqual(readDevices([]), []);
  for (const patch of [{ id: '../devices' }, { id: id.toUpperCase() }, { revision: 0 }, { revision: true },
    { revision: 1.2 }, { revision: Number.MAX_SAFE_INTEGER + 1 }, { focus: 'invalid/member' },
    { calendarView: 'month' }, { name: '' }, { name: '长'.repeat(31) }, { created_at: null }]) {
    assert.throws(() => readDevices([{ ...raw, ...patch }]));
  }
  assert.throws(() => readDevices([raw, raw]));
  assert.equal(readDevices([{ ...raw, focus: 'm_' + 'a'.repeat(24) }])[0].focus, 'm_' + 'a'.repeat(24));
  for (const value of [null, {}, '[]', [null]]) assert.throws(() => readDevices(value));
});

test('layout requires a complete unique permutation and retains at least one card', () => {
  const layout = defaultDeviceLayout();
  for (const patch of [{ order: [] }, { order: [...layout.order, 'calendar'] },
    { order: ['calendar', 'calendar', 'tasks', 'shopping', 'trips'] }, { hidden: layout.order },
    { hidden: ['finance', 'finance'] }, { hidden: ['private-accounts'] }, { theme: 'custom-url' },
    { density: 'tiny' }, { stylesheet: 'unsafe' }]) assert.throws(() => readDeviceLayout({ ...layout, ...patch }));
  assert.throws(() => readDeviceLayout({ order: layout.order, hidden: [], theme: 'forest' }));
  const value = readDeviceLayout({ ...layout, hidden: ['trips', 'finance'] });
  assert.deepEqual(value.hidden, ['finance', 'trips']);
});

test('draft ordering and card visibility are immutable and cannot hide the last card', () => {
  const original = device(), serialized = JSON.stringify(original), draft = deviceDraft(original);
  draft.layout.order.reverse(); draft.layout.hidden.push('finance');
  assert.equal(JSON.stringify(original), serialized);
  let layout = defaultDeviceLayout();
  assert.deepEqual(moveDeviceCard(layout, 'calendar', -1), layout);
  layout = moveDeviceCard(layout, 'tasks', -1);
  assert.deepEqual(layout.order, ['calendar', 'tasks', 'finance', 'shopping', 'trips']);
  for (const key of ['finance', 'tasks', 'shopping', 'trips']) layout = toggleDeviceCard(layout, key);
  assert.throws(() => toggleDeviceCard(layout, 'calendar'));
  assert.deepEqual(toggleDeviceCard(layout, 'tasks').hidden, ['finance', 'shopping', 'trips']);
  assert.deepEqual(original.layout, defaultDeviceLayout());
});

test('Unicode names use character limits, trim boundaries and reject control characters', () => {
  const raw = device(), draft = deviceDraft(raw);
  for (const name of ['🌻'.repeat(30), '字'.repeat(30)]) assert.equal(devicePayload({ ...draft, name }, raw, people).name, name);
  assert.equal(devicePayload({ ...draft, name: '  客厅电视  ' }, raw, people).name, '客厅电视');
  for (const name of ['', '  ', '🌻'.repeat(31), '电视\u0000', '电视\n名称', '电视\u007f']) {
    assert.throws(() => devicePayload({ ...draft, name }, raw, people));
  }
});

test('settings payload whitelists current people, versions and editable fields', () => {
  const raw = device(), draft = deviceDraft(raw);
  assert.deepEqual(devicePayload({ ...draft, owner: 'foreign', token: 'hidden' }, raw, people), {
    revision: 3, name: '合成电视', focus: 'member1', calendarView: 'week', layout: defaultDeviceLayout() });
  assert.throws(() => devicePayload({ ...draft, focus: 'member2' }, raw, [people[0]]));
  const third = { id: 'm_' + 'a'.repeat(24), name: '新成员' };
  assert.throws(() => devicePayload({ ...draft, focus: third.id }, raw, people));
  assert.equal(devicePayload({ ...draft, focus: third.id }, raw, [...people, third]).focus, third.id);
  assert.equal(devicePayload({ ...draft, focus: 'shared' }, raw, []).focus, 'shared');
  for (const revision of [0, -1, true, '3', Infinity]) assert.throws(() => devicePayload(draft, { ...raw, revision }, people));
  assert.equal(sameDeviceSettings(draft, deviceDraft(raw)), true);
  for (const patch of [{ name: '不同' }, { focus: 'shared' }, { calendarView: 'today' }, { layout: { ...draft.layout, density: 'compact' } }]) {
    assert.equal(sameDeviceSettings(draft, { ...draft, ...patch }), false);
  }
});

test('pairing only sends normalized eight-character code and explicitly selected settings', () => {
  const draft = { code: ' abcd 2345 ', name: '合成电视', focus: 'member2', calendarView: 'around', secret: 'not sent', layout: defaultDeviceLayout() };
  assert.deepEqual(pairPayload(draft, people), { code: 'ABCD2345', name: '合成电视', focus: 'member2', calendarView: 'around' });
  for (const code of ['', 'ABCDEFG', 'ABCDEFGHJ', 'ABCDI234', 'ABCDO234', 'ABCD0234', 'ABCD1234', 'https://example.invalid']) {
    assert.throws(() => pairPayload({ ...draft, code }, people));
  }
});

test('playback zero revision is a legitimate unsaved default and extra metadata is discarded', () => {
  assert.deepEqual(readPlayback({ ...state(), filename: 'hidden', account: 'hidden', previewUrl: 'https://invalid' }, id), state());
  assert.deepEqual(readPlayback(photos(), id), photos());
  for (const patch of [{ deviceId: otherId }, { revision: -1 }, { revision: true }, { revision: 0.2 },
    { mode: 'video' }, { paused: 0 }, { intervalSeconds: 4 }, { intervalSeconds: 121 },
    { intervalSeconds: 5.5 }, { position: -1 }, { position: 1000001 }, { photoCount: 2001 },
    { photoCount: true }, { canStart: true }, { updatedAt: {} }]) assert.throws(() => readPlayback({ ...state(), ...patch }, id));
  assert.throws(() => readPlayback({ ...photos(), canStart: false }, id));
});

test('playback commands preserve exact current CAS and send no owner, device ID or extra interval', () => {
  assert.deepEqual(playbackPayload(state(), 'dashboard'), { revision: 0, action: 'dashboard' });
  assert.throws(() => playbackPayload(state(), 'start'));
  for (const action of ['pause', 'resume', 'previous', 'next']) assert.throws(() => playbackPayload(state(), action));
  for (const action of ['start', 'dashboard', 'pause', 'resume', 'previous', 'next']) {
    assert.deepEqual(playbackPayload(photos(), action, '99'), { revision: 8, action });
  }
  assert.throws(() => playbackPayload(photos(), 'grant'));
  for (const text of ['5', '120', ' 17 ']) assert.deepEqual(playbackPayload(photos(), 'interval', text), { revision: 8, action: 'interval', intervalSeconds: Number(text) });
  for (const text of ['', '4', '121', '5.0', '-5', '1e2', 'NaN', 'Infinity', '五']) assert.throws(() => playbackPayload(photos(), 'interval', text));
});

test('identity fence rejects role, family, member, auth version and session changes before any write', async () => {
  const original = session();
  for (const changed of [{ ...original, user: { ...original.user, role: 'tv' } },
    { ...original, user: { ...original.user, householdId: 'other' } },
    { ...original, user: { ...original.user, id: 'member2' } },
    { ...original, user: { ...original.user, auth_version: 2 } }, { ...original, csrf: 'new-session' }, { ...original, csrf: null }]) {
    let writes = 0;
    const fence = new DeviceFence(async () => changed, deviceSignature(original));
    await assert.rejects(fence.run(async () => { ++writes; }, () => true), DeviceDiscarded);
    assert.equal(writes, 0);
  }
});

test('a late successful result cannot pass an invalidated epoch or changed live identity', async () => {
  for (const invalidate of [true, false]) {
    let current = session(), writes = 0;
    const fence = new DeviceFence(async () => current, deviceSignature(current));
    await assert.rejects(fence.run(async () => {
      ++writes;
      if (invalidate) fence.invalidate(); else current = { ...current, csrf: 'different' };
      return photos();
    }, () => true), DeviceDiscarded);
    assert.equal(writes, 1);
  }
});

test('failed GET is checked against the post-read identity before interpreting its 404', async () => {
  let current = session();
  const fence = new DeviceFence(async () => current, deviceSignature(current));
  await assert.rejects(fence.run(async () => {
    current = { ...current, user: { ...current.user, householdId: 'other' } }; throw http(404);
  }, () => true), DeviceDiscarded);
});

test('a mutation rejection is definitive only after both real identity checks succeed', async () => {
  for (const code of [400, 404, 409, 410, 415, 422, 429]) {
    let reads = 0, writes = 0;
    const current = session(), fence = new DeviceFence(async () => { ++reads; return current; }, deviceSignature(current));
    await assert.rejects(checkedDeviceMutation(job => fence.run(job, () => true), async () => {
      ++writes; throw http(code);
    }, status), error => error instanceof DeviceWriteRejected && error.status === code);
    assert.equal(reads, 2); assert.equal(writes, 1);
  }
});

test('post-write /me failure never misclassifies an executed command as rejected', async () => {
  for (const code of [400, 401, 403, 404, 409, 429, 503]) {
    let reads = 0, writes = 0;
    const current = session(), afterError = http(code);
    const fence = new DeviceFence(async () => { if (++reads === 2) throw afterError; return current; }, deviceSignature(current));
    await assert.rejects(checkedDeviceMutation(job => fence.run(job, () => true), async () => {
      ++writes; return photos();
    }, status), error => error === afterError && !(error instanceof DeviceWriteRejected));
    assert.equal(writes, 1); assert.equal(reads, 2);
  }
});

test('post-check failure also supersedes a mutation 409; network and 5xx remain unknown', async () => {
  const current = session();
  let reads = 0;
  const afterError = http(403), fence = new DeviceFence(async () => {
    if (++reads === 2) throw afterError; return current;
  }, deviceSignature(current));
  await assert.rejects(checkedDeviceMutation(job => fence.run(job, () => true), async () => { throw http(409); }, status), error => error === afterError);
  for (const failure of [new Error('network failed'), http(401), http(403), http(500), http(503)]) {
    const stable = new DeviceFence(async () => current, deviceSignature(current));
    await assert.rejects(checkedDeviceMutation(job => stable.run(job, () => true), async () => { throw failure; }, status), error => error === failure && !(error instanceof DeviceWriteRejected));
  }
});
