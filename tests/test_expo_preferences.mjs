import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readPreferences, readPreferencePayload, preferencesPayload, samePreferences, rebasePreferences, acceptPreferences,
  preferenceSignature, PreferenceFence, PreferenceDiscarded, PreferenceError, PreferenceRejected, checkedPreferenceWrite, preferenceRequest } from '../frontend/src/lib/preferences.ts';
const prefs = (patch = {}) => ({ theme:'forest', colorMode:'light', density:'comfortable', homeView:'today', revision:0, ...patch });
const payload = (patch = {}) => ({ revision:0, changes:{colorMode:'dark'}, ...patch });
const session = (patch = {}) => ({ user:{id:'member1',role:'member',householdId:'default',auth_version:1,name:'Synthetic'},csrf:'synthetic-csrf', ...patch });

test('preferences preserve legacy theme separately from Expo color and project only known fields', () => {
  assert.deepEqual(readPreferences({...prefs(),private:'discard'}),prefs());
  for(const theme of ['forest','ocean','light'])assert.equal(readPreferences(prefs({theme,colorMode:'dark'})).theme,theme);
  for(const patch of [{revision:true},{revision:-1},{revision:0.5},{revision:Number.MAX_SAFE_INTEGER+1},{colorMode:'forest'},{theme:'dark'},{density:'small'},{homeView:'month'},{revision:undefined}])
    assert.throws(()=>readPreferences(prefs(patch)),PreferenceError);
});
test('CAS patch accepts only known nonempty changes and a safe revision', () => {
  assert.deepEqual(readPreferencePayload(payload()),payload());
  for(const value of [{...payload(),owner:'member2'},{...prefs()},payload({changes:{}}),payload({changes:{theme:'dark'}}),payload({changes:{revision:9}}),payload({changes:{colorMode:'dark',secret:'x'}}),payload({revision:true})])
    assert.throws(()=>readPreferencePayload(value),PreferenceError);
  assert.equal(readPreferencePayload(payload({revision:Number.MAX_SAFE_INTEGER})).revision,Number.MAX_SAFE_INTEGER);
});
test('appearance saves only changed values; rebasing preserves newer unrelated settings', () => {
  const base=prefs({revision:2}), draft=prefs({revision:2,colorMode:'dark'}), latest=prefs({revision:4,density:'compact',homeView:'week',theme:'ocean'});
  assert.deepEqual(preferencesPayload(base,draft),{revision:2,changes:{colorMode:'dark'}});
  assert.deepEqual(rebasePreferences(base,draft,latest),{...latest,colorMode:'dark'});
  assert.deepEqual(rebasePreferences(base,base,latest),latest);
  assert.equal(base.revision,2);assert.equal(draft.density,'comfortable');
  assert(samePreferences(base,prefs({revision:12})));assert(!samePreferences(base,draft));
  assert.throws(()=>preferencesPayload(base,base),PreferenceError);
});
test('same-session before/after checks return the real result and reject every identity axis', async () => {
  const original = session(), expected = preferenceSignature(original);
  for (const changed of [null, session({ csrf: 'other' }), session({ user: { ...original.user, id: 'member2' } }),
    session({ user: { ...original.user, householdId: 'other' } }), session({ user: { ...original.user, auth_version: 2 } }), session({ user: null })]) {
    const fence = new PreferenceFence(expected); let reads = 0;
    await assert.rejects(fence.run(async () => ++reads === 1 ? original : changed, async () => 'private', () => true), PreferenceDiscarded);
  }
  const fence = new PreferenceFence(expected);
  assert.equal(await fence.run(async () => original, async csrf => csrf, () => true), original.csrf);
});
test('verified save cannot be replaced by a late old poll; another identity cannot install any revision', () => {
  const identity = preferenceSignature(session()), old = prefs({ revision: 2 }), saved = prefs({ revision: 3, colorMode: 'dark' });
  const installed = acceptPreferences(old, saved, identity, identity);
  assert.deepEqual(installed, saved);
  assert.equal(acceptPreferences(installed, old, identity, identity), installed);
  assert.equal(acceptPreferences(installed, prefs({ revision: 99 }), identity, 'other-session'), null);
  assert.deepEqual(acceptPreferences(installed, prefs({ revision: 4, density: 'compact' }), identity, identity), prefs({ revision: 4, density: 'compact' }));
});
test('invalidated epoch rejects late success or failure even after foreground resumes', async () => {
  for (const fail of [false, true]) {
    const value = session(), fence = new PreferenceFence(preferenceSignature(value));
    let release; const blocked = new Promise(resolve => { release = resolve; });
    const result = fence.run(async () => value, async () => { await blocked; if (fail) throw new PreferenceError('old', 409); return prefs(); }, () => true);
    await Promise.resolve(); fence.invalidate(); release();
    await assert.rejects(result, PreferenceDiscarded);
  }
});
test('only actual PUT rejection with successful after-identity is definitive', async () => {
  const value = session(), fence = new PreferenceFence(preferenceSignature(value));
  const guarded = write => fence.run(async () => value, write, () => true);
  await assert.rejects(checkedPreferenceWrite(guarded, async () => { throw new PreferenceError('conflict', 409); }), PreferenceRejected);
  for (const status of [0, 401, 403, 408, 500]) {
    await assert.rejects(checkedPreferenceWrite(guarded, async () => { throw new PreferenceError('uncertain', status); }), error => error instanceof PreferenceError && !(error instanceof PreferenceRejected));
  }
  for (const status of [403, 409, 429]) {
    let reads = 0;
    const guard = write => fence.run(async () => { if (++reads === 2) throw new PreferenceError('after-me', status); return value; }, write, () => true);
    await assert.rejects(checkedPreferenceWrite(guard, async () => prefs()), error => error instanceof PreferenceError && !(error instanceof PreferenceRejected));
  }
});
test('failed pre-write identity read never invokes the write or marks an uncertain mutation', async () => {
  const value = session(), fence = new PreferenceFence(preferenceSignature(value));
  let attempted = 0, uncertain = null;
  const guard = write => fence.run(async () => { throw new PreferenceError('identity network failure'); }, write, () => true);
  await assert.rejects(checkedPreferenceWrite(guard, async () => { attempted++; uncertain = prefs(); return prefs(); }), PreferenceError);
  assert.equal(attempted, 0); assert.equal(uncertain, null);
});
test('transport restricts routes and sends same-origin CAS PUT once without automatic retry', async () => {
  const original = globalThis.fetch, calls = [];
  try {
    globalThis.fetch = async (url, options) => { calls.push({ url, options }); return new Response(JSON.stringify(prefs()), { headers: { 'Content-Type': 'application/json' } }); };
    await preferenceRequest('/preferences', new AbortController().signal, payload(), 'csrf');
    assert.equal(calls.length, 1); assert.equal(calls[0].url, '/api/preferences');
    assert.equal(calls[0].options.method, 'PUT'); assert.equal(calls[0].options.mode, 'same-origin');
    assert.equal(calls[0].options.redirect, 'error'); assert.equal(calls[0].options.cache, 'no-store');
    assert.equal(calls[0].options.headers['X-CSRF-Token'], 'csrf'); assert.deepEqual(JSON.parse(calls[0].options.body), payload());
    await assert.rejects(preferenceRequest('/devices', new AbortController().signal));
    await assert.rejects(preferenceRequest('/me', new AbortController().signal, payload(), 'csrf'));
    assert.equal(calls.length, 1);
    globalThis.fetch = async () => { calls.push('failed'); throw new Error('synthetic disconnect'); };
    await assert.rejects(preferenceRequest('/preferences', new AbortController().signal, payload(), 'csrf'), PreferenceError);
    assert.equal(calls.length, 2);
  } finally { globalThis.fetch = original; }
});
test('aborted request cannot return a late successful preferences', async () => {
  const original = globalThis.fetch, controller = new AbortController();
  try {
    globalThis.fetch = async () => { controller.abort(); return new Response(JSON.stringify(prefs()), { headers: { 'Content-Type': 'application/json' } }); };
    await assert.rejects(preferenceRequest('/preferences', controller.signal), PreferenceDiscarded);
  } finally { globalThis.fetch = original; }
});
