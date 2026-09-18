// Real Flask test-client cookies/SQLite responses, not mocked successful DTOs or browser evidence.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { spawn, spawnSync } from 'node:child_process';
import { createInterface } from 'node:readline';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { registerHooks } from 'node:module';
registerHooks({ resolve(specifier, context, next) { return next(specifier === './personalAccounts' ? './personalAccounts.ts' : specifier, context); } });
const p = await import('../frontend/src/lib/personalAccounts.ts');
const m = await import('../frontend/src/lib/memberships.ts');
const root = fileURLToPath(new URL('..', import.meta.url));
function python() {
  if (process.env.MEMBERSHIP_TEST_PYTHON) return process.env.MEMBERSHIP_TEST_PYTHON;
  const local = resolve(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  if (existsSync(local)) return local;
  for (const command of ['python', 'python3', ...(process.platform === 'win32' ? ['py'] : [])]) {
    const probe = spawnSync(command, ['-c', 'import sys; print(sys.executable)'], { encoding: 'utf8', timeout: 5000, windowsHide: true });
    if (probe.status === 0 && probe.stdout.trim()) return probe.stdout.trim();
  }
  throw new Error('Install project Python dependencies or set MEMBERSHIP_TEST_PYTHON.');
}
async function bridge(mode) {
  const child = spawn(python(), ['-B', '-X', 'utf8', resolve(root, 'tests/expo_membership_recovery_fixture.py'), mode], { windowsHide: true });
  const lines = createInterface({ input: child.stdout })[Symbol.asyncIterator]();
  let stderr = ''; child.stderr.on('data', value => { stderr += value; });
  child.stdin.on('error', value => { stderr += '\n' + value.message; });
  const exited = new Promise((accept, reject) => { child.once('error', reject); child.once('close', code => accept(code)); });
  async function next() { const row = await lines.next(); assert(!row.done, stderr || 'Flask bridge exited'); return JSON.parse(row.value); }
  const ready = await next(), calls = [];
  return { ready, calls,
    async invalidateRoute() { child.stdin.write(JSON.stringify({ invalidateRoute: true }) + '\n'); assert.equal((await next()).invalidated, true); },
    async fetch(path, options = {}) {
      calls.push([path, options.method || 'GET']);
      child.stdin.write(JSON.stringify({ path, method: options.method || 'GET', body: options.body, headers: options.headers }) + '\n');
      const raw = await next();
      return new Response(raw.body, { status: raw.status, headers: { 'Content-Type': raw.contentType } });
    },
    async close() {
      if (child.exitCode === null && !child.stdin.destroyed) child.stdin.end(JSON.stringify({ close: true }) + '\n');
      assert.equal(await exited, 0, stderr);
    }
  };
}

for (const mode of ['invalid_route', 'missing_route', 'missing_default', 'missing_child']) test('actual recovery: ' + mode, { timeout: 45000 }, async () => {
  const api = await bridge(mode), prior = globalThis.fetch, signal = new AbortController().signal;
  globalThis.fetch = api.fetch;
  try {
    const response = await api.fetch('/api/me'), raw = await response.json();
    assert.equal(response.status, mode === 'invalid_route' ? 400 : mode === 'missing_route' ? 404 : 503);
    assert.equal(typeof raw.error, 'string');
    const before = await p.readMembershipIdentity(signal);
    assert.equal(before.member.unavailable.status, response.status);
    assert.equal(before.member.user, null); assert.equal(before.account.account, null);
    assert.throws(() => p.requireMembershipMember(before), p.MembershipError);
    assert.notEqual(p.identitySignature(before), p.identitySignature({ ...before, member: { user: null, csrf: null } }));
    const login = await p.membershipRequest('/account/login', signal, { method: 'POST', csrf: before.account.csrf,
      payload: { login: api.ready.login, password: api.ready.password } });
    const after = await p.readMembershipIdentity(signal);
    assert(m.acceptedMembershipTransition(before, after, 'login', login));
    assert.equal(after.member.unavailable.status, response.status);
    const homes = await new p.MembershipFence(p.identitySignature(after)).run(() => p.readMembershipIdentity(signal),
      async () => m.readHouseholds(await p.membershipRequest('/account/households', signal)), () => true);
    const target = homes.memberships.find(value => value.id === api.ready.target.id); assert(target);
    if (mode === 'missing_default' || mode === 'missing_child') assert.equal(homes.unavailable.length, 1);
    const requestId = p.newMembershipRequestId();
    const result = await p.membershipRequest('/account/switch-household', signal, { method: 'POST', csrf: after.account.csrf,
      payload: { requestId, membershipId: target.id, expectedRevision: target.revision } });
    const entered = await p.readMembershipIdentity(signal);
    assert(m.acceptedMembershipTransition(after, entered, 'switch', result));
    assert.equal(entered.member.unavailable, undefined); assert.equal(entered.member.user.householdId, target.householdId);
    assert.equal(p.requireMembershipMember(entered).user.id, target.memberId);
    const operation = p.readOperation(await p.membershipRequest('/account/operations/' + requestId, signal), requestId, value => m.readMembershipResult('switch', value, true));
    assert.equal(operation.state, 'completed');
    assert.equal(api.calls.filter(([url, method]) => method === 'POST' && url.endsWith('/switch-household')).length, 1);
    assert(api.calls.filter(([, method]) => method === 'POST').every(([url]) => url.startsWith('/api/account/')));
  } finally { globalThis.fetch = prior; await api.close(); }
});

test('actual committed switch with lost reply remains readable by original id while household route is unavailable', { timeout: 45000 }, async () => {
  const api = await bridge('invalid_route'), prior = globalThis.fetch, signal = new AbortController().signal;
  globalThis.fetch = api.fetch;
  try {
    const anonymous = await p.readMembershipIdentity(signal);
    await p.membershipRequest('/account/login', signal, { method: 'POST', csrf: anonymous.account.csrf,
      payload: { login: api.ready.login, password: api.ready.password } });
    const before = await p.readMembershipIdentity(signal), requestId = p.newMembershipRequestId();
    const original = { requestId, membershipId: api.ready.target.id, expectedRevision: api.ready.target.revision };
    globalThis.fetch = async (url, options) => {
      const real = await api.fetch(url, options);
      if (url === '/api/account/switch-household') { assert.equal(real.status, 200); await real.arrayBuffer(); throw new TypeError('Drop actual committed reply'); }
      return real;
    };
    await assert.rejects(p.membershipRequest('/account/switch-household', signal, { method: 'POST', csrf: before.account.csrf, payload: original }), p.MembershipError);
    await api.invalidateRoute(); globalThis.fetch = api.fetch;
    const current = await p.readMembershipIdentity(signal);
    const handle = { requestId, action: 'switch', scope: 'account', accountId: before.account.account.id, targetId: api.ready.target.householdId, operation: null };
    assert(m.operationBelongsTo(handle, current)); assert(current.member.unavailable);
    const op = await new p.MembershipFence(p.identitySignature(current)).run(() => p.readMembershipIdentity(signal),
      async () => p.readOperation(await p.membershipRequest('/account/operations/' + requestId, signal), requestId,
        value => m.validateResultTarget(handle, m.readMembershipResult('switch', value, true))), () => true);
    assert.equal(op.state, 'completed'); assert.equal(op.result.householdId, api.ready.target.householdId);
    assert(current.member.unavailable, 'Historical receipt must not install a current household');
    assert.equal(api.calls.filter(([url, method]) => method === 'POST' && url.endsWith('/switch-household')).length, 1);
    assert.equal(original.requestId, requestId);
  } finally { globalThis.fetch = prior; await api.close(); }
});

const account = () => ({ account: { id: 'a'.repeat(32), login: 'recovery.account' }, csrf: 'synthetic-csrf', authVersion: 1, authenticationGeneration: 2 });
const unavailable = () => ({ user: null, csrf: null, unavailable: { status: 503, reason: 'household_unavailable' } });
const unavailableReply = () => new Response(JSON.stringify({ error: '此家庭的数据暂不可用，请稍后再试或返回家庭入口', recoveryUrl: '/space/home' }),
  { status: 503, headers: { 'Content-Type': 'application/json' } });
test('synthetic rejection controls: transport/permission/unknown server errors are never anonymous or unavailable', async () => {
  const prior = globalThis.fetch;
  try {
    for (const response of [
      () => { throw new TypeError('offline'); },
      () => new Response('<html>503</html>', { status: 503 }),
      ...[401, 403, 404, 500, 503].map(status => () => new Response(JSON.stringify({ error: 'unrelated failure', recoveryUrl: '/space/home' }), { status, headers: { 'Content-Type': 'application/json' } })),
      () => new Response(JSON.stringify({ error: '此家庭的数据暂不可用，请稍后再试或返回家庭入口' }), { status: 503, headers: { 'Content-Type': 'application/json' } })
    ]) {
      globalThis.fetch = async url => url === '/api/me' ? response() : new Response(JSON.stringify(account()), { headers: { 'Content-Type': 'application/json' } });
      await assert.rejects(p.readMembershipIdentity(new AbortController().signal), p.MembershipError);
    }
  } finally { globalThis.fetch = prior; }
});
test('unavailable household still fences personal generation before and after reads', async () => {
  const prior = globalThis.fetch; let count = 0;
  try {
    globalThis.fetch = async url => {
      if (url === '/api/me') return unavailableReply();
      const value = account(); if (++count === 2) value.authenticationGeneration++;
      return new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } });
    };
    await assert.rejects(p.readMembershipIdentity(new AbortController().signal), p.MembershipDiscarded);
  } finally { globalThis.fetch = prior; }
});
test('unavailable is not proof of leaving or a successful switch; original account operation remains attributable', () => {
  const identity = { account: account(), member: unavailable() }, changed = structuredClone(identity);
  const handle = { requestId: 'b'.repeat(32), action: 'switch', scope: 'account', accountId: identity.account.account.id, operation: null };
  assert(m.operationBelongsTo(handle, identity));
  assert(!m.operationBelongsTo({ ...handle, scope: 'member', memberId: 'member1', householdId: 'default' }, identity));
  assert(!m.acceptedMembershipTransition(identity, identity, 'leave', { state: 'left' }));
  changed.account.authenticationGeneration++; changed.account.csrf = 'rotated';
  assert(!m.acceptedMembershipTransition(identity, changed, 'switch', { ok: true, entry: '/app/home', householdId: 'default', memberId: 'member1' }));
  changed.account.authenticationGeneration++;
  assert(!m.acceptedMembershipTransition(identity, changed, 'login', { account: changed.account.account }));
  assert.equal(p.canStartNewMembershipOperation(p.readOperation({ requestId: handle.requestId, found: false, state: null, result: null }, handle.requestId, v => v)), false);
});
