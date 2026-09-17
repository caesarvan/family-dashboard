import assert from 'node:assert/strict';
import { test } from 'node:test';
import { homeCards, readHomeLayout, homeLayoutPayload, sameHomeLayout, moveHomeCard, toggleHomeCard, resetHomeLayout,
  rebaseHomeDraft, layoutSignature, HomeLayoutFence, LayoutDiscarded, LayoutError, LayoutRejected, checkedLayoutWrite, layoutRequest } from '../frontend/src/lib/homeLayout.ts';
const layout = (patch = {}) => ({ revision: 0, order: [...homeCards], hidden: [], ...patch });
const session = (patch = {}) => ({ user: { id: 'member1', role: 'member', householdId: 'default', auth_version: 1, name: 'Synthetic' }, csrf: 'synthetic-csrf', ...patch });

test('GET retains future stored cards while PUT uses known-card protocol only', () => {
  const raw = layout({ revision: 7, order: ['calendar', 'future-weather', ...homeCards.slice(1)], hidden: ['future-weather', 'finance'], secret: 'drop' });
  const parsed = readHomeLayout(raw);
  assert(parsed.order.includes('future-weather')); assert(parsed.hidden.includes('future-weather')); assert.equal(parsed.secret, undefined);
  assert.deepEqual(homeLayoutPayload(parsed), layout({ revision: 7, hidden: ['finance'] }));
  assert.deepEqual(raw.order, ['calendar', 'future-weather', ...homeCards.slice(1)]);
});
test('malformed versions, duplicate cards, unknown hidden keys and all-hidden fail closed', () => {
  for (const patch of [{ revision: true }, { revision: -1 }, { revision: 1.5 }, { revision: Number.MAX_SAFE_INTEGER + 1 },
    { order: ['calendar'] }, { order: [...homeCards, 'calendar'] }, { hidden: ['unknown'] }, { hidden: [...homeCards] }, { hidden: ['trips', 'trips'] }]) {
    assert.throws(() => readHomeLayout(layout(patch)), LayoutError);
  }
});
test('known cards reorder without dropping future keys and boundaries are no-ops', () => {
  const before = layout({ order: ['calendar', 'future', ...homeCards.slice(1)] });
  const next = moveHomeCard(before, 'finance', -1);
  assert.deepEqual(next.order, ['finance', 'future', 'calendar', 'tasks', 'shopping', 'trips']);
  assert.deepEqual(before.order, ['calendar', 'future', ...homeCards.slice(1)]);
  assert.deepEqual(moveHomeCard(next, 'finance', -1), next);
  assert.deepEqual(moveHomeCard(next, 'trips', 1), next);
});
test('last known card cannot hide even if a future card remains visible', () => {
  const one = layout({ order: [...homeCards, 'future'], hidden: homeCards.slice(1) });
  assert.throws(() => toggleHomeCard(one, 'calendar'), /至少保留/);
  assert.deepEqual(toggleHomeCard(one, 'finance').hidden, ['tasks', 'shopping', 'trips']);
});
test('reset and explicit rebase preserve latest future settings and do not mutate drafts', () => {
  const draft = layout({ revision: 2, order: [...homeCards].reverse().concat('old-future'), hidden: ['calendar', 'old-future'] });
  assert.deepEqual(resetHomeLayout(draft), layout({ revision: 2, order: [...homeCards, 'old-future'], hidden: ['old-future'] }));
  const latest = layout({ revision: 4, order: [...homeCards, 'new-future'], hidden: ['new-future'] });
  const rebased = rebaseHomeDraft(draft, latest);
  assert.equal(rebased.revision, 4); assert.deepEqual(rebased.order, [...homeCards].reverse().concat('new-future'));
  assert.deepEqual(rebased.hidden, ['calendar', 'new-future']); assert.equal(draft.revision, 2);
  assert(sameHomeLayout(draft, rebased)); assert(!sameHomeLayout(latest, rebased));
});
test('same-session before/after checks return the real result and reject every identity axis', async () => {
  const original = session(), expected = layoutSignature(original);
  for (const changed of [session({ csrf: 'other' }), session({ user: { ...original.user, id: 'member2' } }),
    session({ user: { ...original.user, householdId: 'other' } }), session({ user: { ...original.user, auth_version: 2 } }), session({ user: null })]) {
    const fence = new HomeLayoutFence(expected); let reads = 0;
    await assert.rejects(fence.run(async () => ++reads === 1 ? original : changed, async () => 'private', () => true), LayoutDiscarded);
  }
  const fence = new HomeLayoutFence(expected);
  assert.equal(await fence.run(async () => original, async csrf => csrf, () => true), original.csrf);
});
test('invalidated epoch rejects late success or failure even after foreground resumes', async () => {
  for (const fail of [false, true]) {
    const value = session(), fence = new HomeLayoutFence(layoutSignature(value));
    let release; const blocked = new Promise(resolve => { release = resolve; });
    const result = fence.run(async () => value, async () => { await blocked; if (fail) throw new LayoutError('old', 409); return layout(); }, () => true);
    await Promise.resolve(); fence.invalidate(); release();
    await assert.rejects(result, LayoutDiscarded);
  }
});
test('only actual PUT rejection with successful after-identity is definitive', async () => {
  const value = session(), fence = new HomeLayoutFence(layoutSignature(value));
  const guarded = write => fence.run(async () => value, write, () => true);
  await assert.rejects(checkedLayoutWrite(guarded, async () => { throw new LayoutError('conflict', 409); }), LayoutRejected);
  for (const status of [0, 401, 403, 408, 500]) {
    await assert.rejects(checkedLayoutWrite(guarded, async () => { throw new LayoutError('uncertain', status); }), error => error instanceof LayoutError && !(error instanceof LayoutRejected));
  }
  for (const status of [403, 409, 429]) {
    let reads = 0;
    const guard = write => fence.run(async () => { if (++reads === 2) throw new LayoutError('after-me', status); return value; }, write, () => true);
    await assert.rejects(checkedLayoutWrite(guard, async () => layout()), error => error instanceof LayoutError && !(error instanceof LayoutRejected));
  }
});
test('transport restricts routes and sends same-origin CAS PUT once without automatic retry', async () => {
  const original = globalThis.fetch, calls = [];
  try {
    globalThis.fetch = async (url, options) => { calls.push({ url, options }); return new Response(JSON.stringify(layout()), { headers: { 'Content-Type': 'application/json' } }); };
    await layoutRequest('/dashboard-layout', new AbortController().signal, layout(), 'csrf');
    assert.equal(calls.length, 1); assert.equal(calls[0].url, '/api/dashboard-layout');
    assert.equal(calls[0].options.method, 'PUT'); assert.equal(calls[0].options.mode, 'same-origin');
    assert.equal(calls[0].options.redirect, 'error'); assert.equal(calls[0].options.cache, 'no-store');
    assert.equal(calls[0].options.headers['X-CSRF-Token'], 'csrf'); assert.deepEqual(JSON.parse(calls[0].options.body), layout());
    await assert.rejects(layoutRequest('/devices', new AbortController().signal));
    await assert.rejects(layoutRequest('/me', new AbortController().signal, layout(), 'csrf'));
    assert.equal(calls.length, 1);
    globalThis.fetch = async () => { calls.push('failed'); throw new Error('synthetic disconnect'); };
    await assert.rejects(layoutRequest('/dashboard-layout', new AbortController().signal, layout(), 'csrf'), LayoutError);
    assert.equal(calls.length, 2);
  } finally { globalThis.fetch = original; }
});
test('aborted request cannot return a late successful layout', async () => {
  const original = globalThis.fetch, controller = new AbortController();
  try {
    globalThis.fetch = async () => { controller.abort(); return new Response(JSON.stringify(layout()), { headers: { 'Content-Type': 'application/json' } }); };
    await assert.rejects(layoutRequest('/dashboard-layout', controller.signal), LayoutDiscarded);
  } finally { globalThis.fetch = original; }
});
