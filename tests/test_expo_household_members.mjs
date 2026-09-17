// Pure contract/fence tests. These examples are not evidence of a running API.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import * as m from '../frontend/src/lib/householdMembers.ts';

const session = () => ({ user: { id: 'member1', name: '合成甲', role: 'member', householdId: 'synthetic-household', auth_version: 3 }, csrf: 'synthetic-session-credential' });
const example = () => ({ currentMemberId: 'member1', members: [
  { id: 'member1', name: '合成甲', householdRole: 'admin', authVersion: 3, activeSessionCount: 1, capabilities: { changeRole: false, revokeSessions: false } },
  { id: 'member2', name: '合成乙', householdRole: 'admin', authVersion: 7, activeSessionCount: 2, capabilities: { changeRole: true, revokeSessions: true } },
] });
const read = raw => m.readMembers(raw, 'member1', 3);
const intent = () => m.memberIntent(read(example()), 'member2', 'role', 'member');

test('current member/version and unique identity are required', () => {
  assert.equal(read(example()).members.length, 2);
  for (const mutate of [r => r.currentMemberId = 'member2', r => r.members[0].authVersion++, r => r.members.pop(), r => r.members.push(r.members[1])]) {
    const r = example(); mutate(r);
    if (r.members.length === 1) r.members = [example().members[1]];
    assert.throws(() => read(r));
  }
});
test('ordinary member projection cannot expose partner counts or management capability', () => {
  const r = example(); r.members[0].householdRole = 'member';
  for (const row of r.members) { row.activeSessionCount = null; row.capabilities = { changeRole: false, revokeSessions: false }; }
  assert.equal(read(r).members[1].activeSessionCount, null);
  r.members[1].activeSessionCount = 0; assert.throws(() => read(r));
  r.members[1].activeSessionCount = null; r.members[1].capabilities.revokeSessions = true; assert.throws(() => read(r));
});
test('bounded fields, exact booleans, and safe positive versions', () => {
  for (const [key, value] of [['id', '../member2'], ['name', '\u0000'], ['householdRole', 'owner'], ['authVersion', true], ['authVersion', 0], ['authVersion', 1.1], ['activeSessionCount', -1]]) {
    const r = example(); r.members[1][key] = value; assert.throws(() => read(r));
  }
  const r = example(); r.members[0].capabilities.changeRole = true; assert.throws(() => read(r));
});
test('intents are precise immutable CAS payloads and do not include names or identities in JSON', () => {
  const role = intent(), revoke = m.memberIntent(read(example()), 'member2', 'revoke');
  assert.deepEqual(role.body, { expectedAuthVersion: 7, householdRole: 'member' });
  assert.deepEqual(revoke.body, { expectedAuthVersion: 7 });
  assert(Object.isFrozen(role)); assert(Object.isFrozen(role.body));
  assert.throws(() => m.memberIntent(read(example()), 'member1', 'role', 'member'));
  assert.throws(() => m.memberIntent(read(example()), 'member2', 'role', 'admin'));
  assert.throws(() => m.memberIntent(read(example()), 'foreign', 'revoke'));
});
test('any change to target version, name, role or permission invalidates an old confirmation', () => {
  const original = intent(); assert(m.intentStillAllowed(original, read(example())));
  for (const mutate of [r => r.members[1].authVersion++, r => r.members[1].name = '新名称', r => r.members[1].householdRole = 'member', r => r.members[1].capabilities.changeRole = false]) {
    const r = example(); mutate(r); assert.equal(m.intentStillAllowed(original, read(r)), false);
  }
});
test('only a matching immediate response is accepted; current list is never a receipt', () => {
  const original = intent(), result = { ok: true, member: { id: 'member2', householdRole: 'member', authVersion: 8 }, revoked: 0 };
  assert.equal(m.readMemberResult(result, original).revoked, 0);
  for (const mutate of [r => r.ok = false, r => r.member.id = 'member1', r => r.member.authVersion = 7, r => r.member.authVersion = 9, r => r.member.householdRole = 'admin', r => r.revoked = null]) {
    const r = structuredClone(result); mutate(r); assert.throws(() => m.readMemberResult(r, original));
  }
  assert.throws(() => m.readMemberResult(example(), original));
});
test('ending local review requires same unknown handle, actor and current epoch', () => {
  const original = intent(), identity = m.membersSignature(session()), proof = { intent: original, identity, epoch: 12 };
  assert.equal(m.canEndMemberReview(null, original, identity, 12), false);
  assert.equal(m.canEndMemberReview(proof, original, identity, 12), true);
  assert.equal(m.canEndMemberReview(proof, intent(), identity, 12), false);
  assert.equal(m.canEndMemberReview(proof, original, identity, 13), false);
  assert.equal(m.canEndMemberReview(proof, original, identity + 'foreign', 12), false);
});
test('preflight identity mismatch never dispatches a write', async () => {
  const s = session(), fence = new m.MembersFence(m.membersSignature(s)); let writes = 0;
  await assert.rejects(fence.run(async () => ({ ...s, csrf: 'new-session' }), async () => ++writes, () => true), m.MembersDiscarded);
  assert.equal(writes, 0);
});
test('postflight full identity changes discard successful late responses', async () => {
  for (const field of ['id', 'householdId', 'auth_version', 'role', 'csrf']) {
    const s = session(), changed = structuredClone(s); if (field === 'csrf') changed.csrf += '-new';
    else changed.user[field] = field === 'auth_version' ? 4 : field === 'role' ? 'tv' : 'other';
    let calls = 0, writes = 0; const fence = new m.MembersFence(m.membersSignature(s));
    await assert.rejects(fence.run(async () => ++calls === 1 ? s : changed, async () => ++writes, () => true), m.MembersDiscarded);
    assert.equal(writes, 1); assert.equal(calls, 2);
  }
});
test('invalidated lifetime rejects both callbacks and future stale continuations', async () => {
  const s = session(), fence = new m.MembersFence(m.membersSignature(s)); let release;
  const wait = new Promise(resolve => { release = resolve; });
  const pending = fence.run(async () => s, async () => { await wait; return 'late'; }, () => true);
  await Promise.resolve(); fence.invalidate(); release(); await assert.rejects(pending, m.MembersDiscarded);
});
test('only definite write rejection with a successful after-me is classified as rejected', async () => {
  const s = session(), fence = new m.MembersFence(m.membersSignature(s)); let count = 0;
  const guard = job => fence.run(async () => { ++count; return s; }, job, () => true);
  await assert.rejects(m.checkedMemberWrite(guard, async () => { throw new m.MembersError('conflict', 409); }), m.MembersRejected);
  assert.equal(count, 2);
  for (const status of [0, 401, 500]) await assert.rejects(m.checkedMemberWrite(guard, async () => { throw new m.MembersError('unknown', status); }), e => e instanceof m.MembersError && !(e instanceof m.MembersRejected));
  let after = false;
  await assert.rejects(m.checkedMemberWrite(job => fence.run(async () => { if (after) throw new m.MembersError('offline'); after = true; return s; }, job, () => true),
    async () => { throw new m.MembersError('conflict', 409); }), e => !(e instanceof m.MembersRejected));
});
test('transport refuses external URLs, query ownership, invalid verbs and broadened payloads before fetch', async () => {
  const old = globalThis.fetch; let calls = 0; globalThis.fetch = async () => { ++calls; throw Error('must not fetch'); };
  try {
    const signal = new AbortController().signal;
    for (const [path, options] of [['https://example.test/api/members', {}], ['/members?owner=member2', {}], ['/members/../role', { method: 'PATCH', payload: { expectedAuthVersion: 7, householdRole: 'member' }, csrf: 'x' }],
      ['/members/member2/role', { method: 'POST', payload: { expectedAuthVersion: 7, householdRole: 'member' }, csrf: 'x' }],
      ['/members/member2/revoke-sessions', { method: 'POST', payload: { expectedAuthVersion: 7, owner: 'member2' }, csrf: 'x' }], ['/members', { method: 'GET', csrf: 'x' }]])
      await assert.rejects(m.membersRequest(path, signal, options), m.MembersError);
    assert.equal(calls, 0);
  } finally { globalThis.fetch = old; }
});
test('transport enforces nonredirecting same-origin no-store and rejects oversized, bad UTF8 and nonJSON bodies', async () => {
  const old = globalThis.fetch, signal = new AbortController().signal; let seen;
  try {
    globalThis.fetch = async (path, options) => { seen = { path, options }; return new Response('{}', { headers: { 'Content-Type': 'application/json' } }); };
    assert.deepEqual(await m.membersRequest('/members', signal), {});
    assert.equal(seen.path, '/api/members'); assert.equal(seen.options.redirect, 'error'); assert.equal(seen.options.cache, 'no-store'); assert.equal(seen.options.credentials, 'same-origin');
    for (const [bytes, headers] of [['x', { 'Content-Type': 'text/html' }], ['{', { 'Content-Type': 'application/json' }], [new Uint8Array([0xff]), { 'Content-Type': 'application/json' }], ['x'.repeat(128001), { 'Content-Type': 'application/json' }]]) {
      globalThis.fetch = async () => new Response(bytes, { headers }); await assert.rejects(m.membersRequest('/members', signal), m.MembersError);
    }
    const stopped = new AbortController(); stopped.abort(); await assert.rejects(m.membersRequest('/me', stopped.signal), m.MembersDiscarded);
  } finally { globalThis.fetch = old; }
});
