import assert from 'node:assert/strict';
import { test } from 'node:test';
import { existsSync } from 'node:fs';
import { registerHooks } from 'node:module';
import { fileURLToPath } from 'node:url';

registerHooks({ resolve(specifier, context, next) {
  if (/^\.\.?\//.test(specifier) && context.parentURL && !/\.[a-z]+$/i.test(specifier)) {
    const candidate = new URL(specifier + '.ts', context.parentURL);
    if (existsSync(fileURLToPath(candidate))) return next(candidate.href, context);
  }
  return next(specifier, context);
} });
const { sessionIdentity } = await import('../frontend/src/lib/sessionIdentity.ts');
const { PhotoReadFence } = await import('../frontend/src/lib/photos.ts');
const { MembersFence } = await import('../frontend/src/lib/householdMembers.ts');
const { BaselineFence } = await import('../frontend/src/lib/financeBaseline.ts');
const { DeviceFence } = await import('../frontend/src/lib/devices.ts');
const fixture = () => ({ user: { role: 'member', id: 'member1', householdId: 'default', auth_version: 1,
  membershipRevision: 2, accountId: 'a'.repeat(32), accountAuthVersion: 1, authenticationGeneration: 4 }, csrf: 'test-only-csrf' });

test('all module fences use the same complete identity as the household provider', async () => {
  for (const [module, name] of Object.entries({ photos: 'photo', householdMembers: 'members', devices: 'device',
    preferences: 'preference', homeLayout: 'layout', inventory: 'inventory', places: 'place',
    journeyDocuments: 'document', journeySegments: 'segment', routines: 'routine', financeBaseline: 'baseline',
    financeSourceImport: 'source', financeAccounts: 'account', shoppingSettlement: 'settlement', tripRecap: 'recap' })) {
    const signature = (await import(`../frontend/src/lib/${module}.ts`))[name + 'Signature'];
    assert.equal(signature, sessionIdentity, module);
    assert.equal(signature(fixture()), sessionIdentity(fixture()));
  }
});

const runs = {
  photos: (expected, me, job) => new PhotoReadFence(me, fixture().user, expected).read(job, () => true),
  members: (expected, me, job) => new MembersFence(expected).run(me, job, () => true),
  finance: (expected, me, job) => new BaselineFence(expected).run(me, job, () => true),
  devices: (expected, me, job) => new DeviceFence(me, expected).run(job, () => true),
};
for (const [name, run] of Object.entries(runs)) {
  test(`${name}: actual fence accepts unchanged identity and rejects every derived field change before/after work`, async () => {
    const value = fixture(), expected = sessionIdentity(value);
    assert.equal(await run(expected, async () => value, async () => 'actual-result'), 'actual-result');
    for (const field of ['membershipRevision', 'accountId', 'accountAuthVersion', 'authenticationGeneration']) {
      const altered = structuredClone(value);
      altered.user[field] = typeof altered.user[field] === 'string' ? 'b'.repeat(32) : altered.user[field] + 1;
      let called = false;
      await assert.rejects(() => run(expected, async () => altered, async () => { called = true; }));
      assert.equal(called, false, field);
      let reads = 0;
      await assert.rejects(() => run(expected, async () => ++reads === 1 ? value : altered, async () => 'stale-result'));
      assert.equal(reads, 2);
    }
  });
}
