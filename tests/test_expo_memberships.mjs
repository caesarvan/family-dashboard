// Focused client contracts/transport tests. Synthetic DTOs are not running API evidence.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { registerHooks } from 'node:module';
registerHooks({ resolve(specifier, context, next) { return next(specifier === './personalAccounts' ? './personalAccounts.ts' : specifier, context); } });
const p = await import('../frontend/src/lib/personalAccounts.ts');
const m = await import('../frontend/src/lib/memberships.ts');
const A = 'a'.repeat(32), B = 'b'.repeat(32), R = 'c'.repeat(32), I = 'd'.repeat(32);
const account = () => ({ account: { id: A, login: 'synthetic.user' }, csrf: 'account-csrf', authVersion: 2, authenticationGeneration: 4 });
const identity = () => ({ account: account(), member: { user: { id: 'member1', householdId: 'default', role: 'member', auth_version: 3, membershipRevision: 1 }, csrf: 'member-csrf' } });
const membership = () => ({ id: I, householdId: 'default', memberId: 'member1', memberName: '合成甲', householdRole: 'admin', state: 'active', revision: 1 });
const invitation = () => ({ id: I, state: 'pending', revision: 1, expiresAt: '2026-09-25T00:00:00+00:00', householdRole: 'member' });
const handle = () => ({ requestId: R, action: 'link', scope: 'account', accountId: A, login: 'synthetic.user', householdId: 'default', memberId: 'member1', operation: null });

test('personal session requires precise nullable identity, CSRF and safe browser generation', () => {
  assert.deepEqual(p.readAccountSession(account()), account());
  assert.deepEqual(p.readAccountSession({ account: null, csrf: 'anon', authVersion: null, authenticationGeneration: 0 }), { account: null, csrf: 'anon', authVersion: null, authenticationGeneration: 0 });
  for (const change of [v => v.account.id = 'member1', v => v.csrf = '', v => v.authVersion = true, v => v.authenticationGeneration = -1, v => v.authenticationGeneration = 2 ** 53]) {
    const value = account(); change(value); assert.throws(() => p.readAccountSession(value));
  }
});
test('combined identity separates every account/member version, membership, household and CSRF', () => {
  const original = identity(); assert.deepEqual(p.readMemberSession(original.member), original.member);
  for (const change of [v => v.account.authenticationGeneration++, v => v.account.authVersion++, v => v.account.csrf += 'x', v => v.account.account.id = B,
    v => v.member.user.householdId = 'f'.repeat(24), v => v.member.user.id = 'member2', v => v.member.user.auth_version++, v => v.member.user.membershipRevision++, v => v.member.csrf += 'x']) {
    const altered = identity(); change(altered); assert.notEqual(p.identitySignature(altered), p.identitySignature(original));
  }
  const missing = identity().member; delete missing.user.membershipRevision; assert.throws(() => p.readMemberSession(missing));
});
test('household and membership readers reject cross-household rows, duplicates and invalid versions', () => {
  assert.equal(m.readMemberships({ memberships: [membership()] }, 'default').length, 1);
  assert.throws(() => m.readMemberships({ memberships: [membership()] }, 'f'.repeat(24)));
  assert.throws(() => m.readMemberships({ memberships: [membership(), membership()] }, 'default'));
  for (const change of [v => v.revision = 0, v => v.state = 'paused', v => v.householdRole = 'owner', v => v.memberId = '../member1']) {
    const value = membership(); change(value); assert.throws(() => m.readMembership(value));
  }
});
test('directory unavailable is preserved, never interpreted as missing household', () => {
  const { state, ...row } = membership();
  const list = { memberships: [{ ...row, name: '合成家庭', slug: 'home' }], unavailable: [{ householdId: 'f'.repeat(24), code: 'temporarily_unavailable' }] };
  assert.equal(m.readHouseholds(list).unavailable.length, 1);
  list.unavailable[0].householdId = 'default'; assert.throws(() => m.readHouseholds(list));
});
test('confirmation household label must come from the same current household', () => {
  assert.deepEqual(m.readCurrentHousehold({ id: 'default', name: '合成家', slug: 'home', entry: '/space/home' }, 'default'), { id: 'default', name: '合成家', slug: 'home' });
  assert.throws(() => m.readCurrentHousehold({ id: 'f'.repeat(24), name: '其他家', slug: 'other' }, 'default'));
});
test('invitation first response may contain secret, historical receipt must not', () => {
  assert.equal(m.readInvitationCreated({ invitation: invitation(), token: 'secret' }).token, 'secret');
  assert.equal(m.readInvitationCreated({ invitation: invitation() }, true).token, null);
  assert.throws(() => m.readInvitationCreated({ invitation: invitation(), token: 'secret' }, true));
  assert.equal(m.readInvitation({ ...invitation(), state: 'invalid' }).state, 'invalid');
  assert.throws(() => m.readInvitation({ ...invitation(), householdRole: 'admin' }));
});
test('inspect contains bounded household and both ephemeral tickets without members', () => {
  const raw = { household: { id: 'default', name: '合成家庭', slug: 'home' }, householdRole: 'member', joinTicket: 'join', eligibilityToken: 'eligible', expiresAt: '2026-09-18T10:00:00Z' };
  assert.equal(m.readJoinPreview(raw).household.id, 'default');
  assert.throws(() => m.readJoinPreview({ ...raw, householdRole: 'admin' }));
  assert.throws(() => m.readJoinPreview({ ...raw, eligibilityToken: '' }));
});
test('unknown false and pending never authorize a fresh request', () => {
  for (const raw of [{ requestId: R, found: false, state: null, result: null }, { requestId: R, found: true, state: 'pending', result: null }]) {
    assert.equal(p.canStartNewMembershipOperation(p.readOperation(raw, R, m.readMembership)), false);
  }
  const ended = p.readOperation({ requestId: R, found: true, state: 'not_committed', result: null }, R, m.readMembership);
  assert.equal(p.canStartNewMembershipOperation(ended), true);
  assert.throws(() => p.readOperation({ ...ended, result: membership() }, R, m.readMembership));
  assert.throws(() => p.readOperation({ ...ended, requestId: B }, R, m.readMembership));
});
test('all valid normalized account prefixes agree with the backend grammar', () => {
  for (const login of ['_a.b', '.abc', '-abc', 'abc']) assert.equal(p.loginName(login), login);
  for (const login of ['AAa', 'ab', 'a/b', 'a b']) assert.throws(() => p.loginName(login));
});
test('write pending/not_committed envelopes preserve the original operation without decoding a final summary', () => {
  for (const state of ['pending', 'not_committed']) {
    const raw = { requestId: R, found: true, state, result: null };
    assert.deepEqual(m.readMembershipWriteReply(handle(), raw), raw);
  }
  assert.throws(() => m.readMembershipWriteReply(handle(), { requestId: B, found: true, state: 'pending', result: null }));
  assert.equal(m.readMembershipWriteReply(handle(), membership()).state, 'completed');
});
test('completed operation requires actual finite result, current list is not a receipt', () => {
  const op = p.readOperation({ requestId: R, found: true, state: 'completed', result: membership() }, R, m.readMembership);
  assert.equal(op.result.id, I);
  assert.throws(() => p.readOperation({ ...op, result: null }, R, m.readMembership));
  assert.throws(() => p.readOperation({ ...op, result: { memberships: [membership()] } }, R, m.readMembership));
});
test('retained handles are isolated by personal account or exact member and household', () => {
  const h = handle(); assert.equal(m.operationBelongsTo(h, identity()), true);
  const foreign = identity(); foreign.account.account.id = B; assert.equal(m.operationBelongsTo(h, foreign), false);
  const local = { ...h, scope: 'member' }; foreign.member.user.householdId = 'f'.repeat(24); assert.equal(m.operationBelongsTo(local, foreign), false);
  foreign.member.user.householdId = 'default'; foreign.member.user.id = 'member2'; assert.equal(m.operationBelongsTo(local, foreign), false);
});
test('finite replies stay bound to the original target and operation state', () => {
  assert.equal(m.validateResultTarget(handle(), membership()).id, I);
  assert.throws(() => m.validateResultTarget(handle(), { ...membership(), memberId: 'member2' }));
  assert.throws(() => m.validateResultTarget({ ...handle(), action: 'leave' }, membership()));
  const r = m.readMembershipResult('revoke', { invitation: { ...invitation(), state: 'revoked' } });
  assert.equal(m.validateResultTarget({ ...handle(), action: 'revoke', targetId: I }, r).invitation.state, 'revoked');
});
test('login/register transitions require exactly next generation and rotated CSRF', () => {
  const before = identity(), after = identity(); after.account.authenticationGeneration++; after.account.csrf = 'new';
  assert.equal(m.acceptedMembershipTransition(before, after, 'login', { account: after.account.account }), true);
  after.account.authenticationGeneration++; assert.equal(m.acceptedMembershipTransition(before, after, 'login', { account: after.account.account }), false);
  after.account.authenticationGeneration--; after.account.csrf = before.account.csrf; assert.equal(m.acceptedMembershipTransition(before, after, 'login', { account: after.account.account }), false);
});
test('switch checks target household/member, account origin and exact browser generation', () => {
  const before = identity(), after = identity(); after.account.authenticationGeneration++; after.account.csrf = 'new';
  after.member.user = { ...after.member.user, accountId: A, accountAuthVersion: 2, authenticationGeneration: 5 };
  const result = { ok: true, householdId: 'default', memberId: 'member1', entry: '/app/home' };
  assert.equal(m.acceptedMembershipTransition(before, after, 'switch', result), true);
  after.member.user.accountId = B; assert.equal(m.acceptedMembershipTransition(before, after, 'switch', result), false);
});
test('bind preserves old local member cookie and increments only membership version', () => {
  const before = identity(), after = identity(); after.member.user.membershipRevision++;
  assert.equal(m.acceptedMembershipTransition(before, after, 'link', { ...membership(), revision: 2 }), true);
  after.member.user.auth_version++; assert.equal(m.acceptedMembershipTransition(before, after, 'link', { ...membership(), revision: 2 }), false);
});
test('personal logout may preserve original local member but never a derived member', () => {
  const before = identity(), after = identity(); after.account = { account: null, authVersion: null, csrf: 'new', authenticationGeneration: 5 };
  assert.equal(m.acceptedMembershipTransition(before, after, 'logout', { ok: true }), true);
  before.member.user.accountId = A; after.member.user.accountId = A;
  assert.equal(m.acceptedMembershipTransition(before, after, 'logout', { ok: true }), false);
  after.member = { user: null, csrf: null }; assert.equal(m.acceptedMembershipTransition(before, after, 'logout', { ok: true }), true);
});
test('transport allowlist rejects arbitrary paths, extra owners and cross-domain CSRF', () => {
  const options = { method: 'POST', csrf: 'member-csrf', accountCsrf: 'account-csrf', payload: { requestId: R, memberPassword: 'old', expectedAuthVersion: 3, expectedRevision: 1 } };
  assert.doesNotThrow(() => p.validateMembershipRequest('/membership-links', options));
  assert.throws(() => p.validateMembershipRequest('/membership-links', { ...options, accountCsrf: undefined }));
  assert.throws(() => p.validateMembershipRequest('/membership-links', { ...options, payload: { ...options.payload, owner: 'member2' } }));
  assert.throws(() => p.validateMembershipRequest('https://example.com/api/account/me', {}));
  assert.throws(() => p.validateMembershipRequest('/account/me?token=secret', {}));
  assert.throws(() => p.validateMembershipRequest('/account/logout', { method: 'POST', csrf: 'x', memberCsrf: 'wrong', payload: { requestId: R } }));
});
test('resume only targets original account operation and carries no replacement intent', () => {
  assert.doesNotThrow(() => p.validateMembershipRequest('/account/operations/' + R + '/resume', { method: 'POST', csrf: 'current-account', payload: {} }));
  assert.throws(() => p.validateMembershipRequest('/account/operations/' + R + '/resume', { method: 'POST', csrf: 'x', payload: { requestId: B } }));
  assert.throws(() => p.validateMembershipRequest('/membership-operations/' + R + '/resume', { method: 'POST', csrf: 'x', payload: {} }));
  assert.throws(() => p.validateMembershipRequest('/account/operations/' + R, { method: 'GET', csrf: 'secret' }));
});
test('fresh full identity is checked before work and after both success and rejection', async () => {
  let calls = 0; const f = new p.MembershipFence(p.identitySignature(identity()));
  await assert.rejects(f.run(async () => { calls++; const v = identity(); if (calls === 2) v.member.user.membershipRevision++; return v; }, async () => 123, () => true), p.MembershipDiscarded);
  assert.equal(calls, 2);
  calls = 0; await assert.rejects(f.run(async () => { calls++; return identity(); }, async () => { throw new Error('rejected'); }, () => true), /rejected/); assert.equal(calls, 2);
});
test('hidden/epoch invalidation discards an in-flight result even if identity is unchanged', async () => {
  const f = new p.MembershipFence(p.identitySignature(identity()));
  await assert.rejects(f.run(async () => identity(), async () => { f.invalidate(); return 123; }, () => true), p.MembershipDiscarded);
  await assert.rejects(f.run(async () => identity(), async () => 123, () => false), p.MembershipDiscarded);
});
test('bounded transport uses no-store, redirect rejection, domain-specific headers and no automatic retry', async () => {
  const original = globalThis.fetch; const calls = [];
  try {
    globalThis.fetch = async (url, init) => { calls.push({ url, init }); return new Response(JSON.stringify({ error: '合成拒绝', code: 'conflict' }), { status: 409, headers: { 'Content-Type': 'application/json' } }); };
    await assert.rejects(p.membershipRequest('/account/eligibility', new AbortController().signal,
      { method: 'POST', csrf: 'account', memberCsrf: 'member', payload: { memberPassword: 'legacy' } }), e => e.status === 409);
    assert.equal(calls.length, 1); assert.equal(calls[0].init.cache, 'no-store'); assert.equal(calls[0].init.redirect, 'error');
    assert.equal(calls[0].init.headers['X-CSRF-Token'], 'account'); assert.equal(calls[0].init.headers['X-Member-CSRF-Token'], 'member');
  } finally { globalThis.fetch = original; }
});
test('derived member proof cannot belong to another personal account version or browser generation', async () => {
  const original = globalThis.fetch;
  try {
    for (const change of [u => u.accountId = B, u => u.accountAuthVersion++, u => u.authenticationGeneration++]) {
      const current = identity(); Object.assign(current.member.user, { accountId: A, accountAuthVersion: 2, authenticationGeneration: 4 }); change(current.member.user);
      globalThis.fetch = async url => new Response(JSON.stringify(url === '/api/me' ? current.member : current.account), { headers: { 'Content-Type': 'application/json' } });
      await assert.rejects(p.readMembershipIdentity(new AbortController().signal), p.MembershipDiscarded);
    }
  } finally { globalThis.fetch = original; }
});
test('malformed/oversized/non-JSON replies stay unconfirmed; aborted requests never send', async () => {
  const original = globalThis.fetch; let count = 0;
  try {
    for (const response of [() => new Response('{', { headers: { 'Content-Type': 'application/json' } }), () => new Response('x'.repeat(512001), { headers: { 'Content-Type': 'application/json' } }), () => new Response('<html>')]) {
      globalThis.fetch = async () => { count++; return response(); };
      await assert.rejects(p.membershipRequest('/account/me', new AbortController().signal), p.MembershipError);
    }
    const abort = new AbortController(); abort.abort(); await assert.rejects(p.membershipRequest('/account/me', abort.signal), p.MembershipDiscarded); assert.equal(count, 3);
  } finally { globalThis.fetch = original; }
});
test('operation identifiers use cryptographic randomness and exact lowercase length', () => {
  const values = new Set(Array.from({ length: 100 }, () => p.newMembershipRequestId())); assert.equal(values.size, 100);
  for (const value of values) assert.match(value, /^[a-f0-9]{32}$/);
});
