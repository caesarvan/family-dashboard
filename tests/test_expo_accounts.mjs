import assert from 'node:assert/strict';
import { test } from 'node:test';
import { accountId, selectionVersion, readAccounts, readDiscovery, selectionDraft, sourcePayload, sameSelection, selectionChanges, reviewSelection, accountTime } from '../frontend/src/lib/accounts.ts';

const id = 'a'.repeat(32), version = 'a'.repeat(64), newer = 'b'.repeat(64);
const calendar = { id: 'remote-calendar', kind: 'calendar', name: '合成工作安排', writable: false };
const task = { id: 'remote-tasks', kind: 'tasks', name: '合成家庭清单', writable: true };
const saved = { id: 'b'.repeat(32), remoteId: calendar.id, kind: 'calendar', name: calendar.name, owner: 'member1', primary: false, lastSuccess: '', error: '' };
const account = { id, name: '合成账户', email: 'example@example.test', provider: 'microsoft', needsReauth: false,
  capabilities: { sync: true, photos: false }, sources: [saved], selectionVersion: version };
const providers = [{ id: 'microsoft', name: 'Microsoft', configured: true }, { id: 'google', name: 'Google', configured: false }];
const discovery = { sources: [calendar, task], selected: [saved], selectionVersion: version };
const draft = () => selectionDraft(id, readDiscovery(discovery), 'member1');

test('account DTO projects display-only fields and leaves provider addresses and credentials out', () => {
  const value = readAccounts({ accounts: [{ ...account, tokens: 'not a real token', subject: 'remote-user', clientId: 'private' }], providers: providers.map(p => ({ ...p, callbackUrl: 'https://example.test/auth', loginUrl: '/other' })) });
  assert.deepEqual(value, { accounts: [account], providers });
  assert.equal(accountId('../accounts'), false); assert.equal(selectionVersion(version + '?'), false);
});

test('invalid identities, missing opaque version and malformed capabilities fail closed', () => {
  for (const patch of [{ id: '../accounts' }, { id: id.toUpperCase() }, { provider: 'apple' }, { selectionVersion: null }, { selectionVersion: '' }, { capabilities: { sync: 'true', photos: false } }, { needsReauth: 'false' }, { email: 'x'.repeat(321) }]) {
    assert.throws(() => readAccounts({ accounts: [{ ...account, ...patch }], providers }));
  }
});

test('duplicate and over-limit accounts or saved sources are rejected rather than truncated', () => {
  assert.throws(() => readAccounts({ accounts: [account, account], providers }));
  assert.throws(() => readAccounts({ accounts: Array.from({ length: 5 }, (_, index) => ({ ...account, id: index.toString(16).padStart(32, '0') })), providers }));
  assert.throws(() => readAccounts({ accounts: [{ ...account, sources: [saved, saved] }], providers }));
  assert.throws(() => readAccounts({ accounts: [account], providers: [providers[0], providers[0]] }));
});

test('source discovery permits 500 of each kind and rejects partial-looking oversized sets', () => {
  const sources = Array.from({ length: 500 }, (_, i) => [{ ...calendar, id: 'calendar-' + i }, { ...task, id: 'task-' + i }]).flat();
  assert.equal(readDiscovery({ ...discovery, sources }).sources.length, 1000);
  assert.throws(() => readDiscovery({ ...discovery, sources: sources.concat(calendar) }));
  assert.throws(() => readDiscovery({ ...discovery, sources: Array.from({ length: 501 }, (_, i) => ({ ...calendar, id: String(i) })) }));
  assert.throws(() => readDiscovery({ ...discovery, sources: [calendar, calendar] }));
});

test('same remote ID in different kinds is valid but local source IDs never become remote IDs', () => {
  const value = selectionDraft(id, readDiscovery({ ...discovery, sources: [calendar, { ...task, id: calendar.id }] }), 'member2');
  assert.equal(value.rows.length, 2); assert.equal(value.rows[1].selected, false);
  assert.deepEqual(sourcePayload(value), { sources: [{ remoteId: calendar.id, kind: 'calendar', owner: 'member1', primary: false }], selectionVersion: version });
});

test('undiscovered existing selection remains selected and cannot silently disappear on save', () => {
  const value = selectionDraft(id, readDiscovery({ ...discovery, sources: [task] }), 'member1');
  assert.equal(value.rows.length, 2); assert.equal(value.rows[1].selected, true); assert.equal(value.rows[1].available, false);
  assert.throws(() => sourcePayload(value), /未发现/);
  value.rows[1].selected = false;
  assert.deepEqual(sourcePayload(value).sources, []);
  assert.deepEqual(selectionChanges(value).removed, [saved]);
});

test('explicit source removal is reflected in the complete replacement review', () => {
  const value = draft(); value.rows[0].selected = false; value.rows[1].selected = true; value.rows[1].primary = true;
  assert.deepEqual(selectionChanges(value).removed, [saved]);
  assert.deepEqual(sourcePayload(value).sources, [{ remoteId: task.id, kind: 'tasks', owner: 'shared', primary: true }]);
});

test('read-only task lists, invalid owners and calendar primary are rejected', () => {
  for (const patch of [{ writable: false }, { owner: 'member1' }, { owner: 'other' }]) {
    const value = draft(); Object.assign(value.rows[1], patch, { selected: true }); assert.throws(() => sourcePayload(value));
  }
  const value = draft(); value.rows[0].primary = true; assert.throws(() => sourcePayload(value));
});

test('account source cap and one-primary invariant apply before POST', () => {
  const value = draft(); value.rows = Array.from({ length: 13 }, (_, i) => ({ ...value.rows[0], id: String(i), selected: true }));
  assert.throws(() => sourcePayload(value), /12/);
  value.rows = [{ ...draft().rows[1], selected: true, primary: true }, { ...draft().rows[1], id: 'other-tasks', selected: true, primary: true }];
  assert.throws(() => sourcePayload(value), /一份/);
});

test('unknown write recovery compares exact choices independently of display names, ordering and timestamps', () => {
  const first = { remoteId: calendar.id, kind: 'calendar', owner: 'shared', primary: false };
  const second = { remoteId: task.id, kind: 'tasks', owner: 'shared', primary: true };
  assert.equal(sameSelection([first, second], [{ ...second, name: 'renamed', lastSuccess: 'later' }, first]), true);
  for (const changed of [{ ...first, owner: 'member2' }, { ...first, remoteId: 'other' }]) assert.equal(sameSelection([first], [changed]), false);
  assert.equal(sameSelection([second], [{ ...second, primary: false }]), false);
});

test('explicit conflict review adopts fresh version but preserves user changes and reveals new removals', () => {
  const value = draft(); value.rows[0].owner = 'shared'; value.rows[1].selected = true;
  const added = { ...saved, id: 'c'.repeat(32), remoteId: 'new-remote', name: '另一处新增日历' };
  const result = reviewSelection(value, { ...account, sources: [saved, added], selectionVersion: newer });
  assert.equal(value.version, version); assert.equal(result.version, newer); assert.equal(result.rows[0].owner, 'shared');
  assert.equal(result.rows[1].selected, true); assert.equal(result.rows[2].selected, false);
  assert.deepEqual(selectionChanges(result).removed, [added]);
  assert.equal(sourcePayload(result).sources.length, 2);
  assert.throws(() => reviewSelection(value, { ...account, id: 'd'.repeat(32) }));
});

test('empty success time is distinct from failed or malformed timestamps', () => {
  assert.equal(accountTime(''), '尚无成功记录'); assert.equal(accountTime('not-time'), '成功时间无法识别');
  assert.notEqual(accountTime('2026-09-16T01:00:00Z'), '尚无成功记录');
});
