// Execute the actual TypeScript flow against a temporary real Flask/SQLite API.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = process.env.ASSISTANT_TEST_ROOT;
const ts = require(path.join(root, 'frontend/node_modules/typescript'));
function load(name, imports = {}) {
  const source = fs.readFileSync(path.join(root, 'frontend/src/lib', name + '.ts'), 'utf8');
  const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const module = { exports: {} };
  vm.runInNewContext(js, { module, exports: module.exports, require: key => {
    assert.ok(Object.hasOwn(imports, key), 'Unexpected import'); return imports[key];
  }, process, console, URL, fetch });
  return module.exports;
}
const api = load('api');
const identity = load('sessionIdentity');
const trips = load('trips', { './sessionIdentity.ts': identity });
const list = load('assistantList', { './trips': trips });
const { AssistantFlow } = load('assistant', { './api': api, './sessionIdentity.ts': identity, './assistantList': list });
const origin = process.env.ASSISTANT_TEST_ORIGIN;
assert.match(origin, /^http:\/\/127\.0\.0\.1:\d+$/);
const cookie1 = process.env.ASSISTANT_TEST_COOKIE1, cookie2 = process.env.ASSISTANT_TEST_COOKIE2;
let cookie = cookie1;
const checks = [];
const plain = value => JSON.parse(JSON.stringify(value));
async function raw(route, method = 'GET', payload, csrf) {
  assert.match(route, /^\/[a-z]/);
  const response = await fetch(origin + '/api' + route, { method, redirect: 'error',
    headers: { Cookie: cookie, 'Content-Type': 'application/json', ...(csrf ? { 'X-CSRF-Token': csrf } : {}) },
    ...(method === 'GET' ? {} : { body: JSON.stringify(payload) }) });
  const value = await response.json();
  if (!response.ok) throw new api.ApiError(value.error, response.status, value.code);
  return value;
}
async function fixture() {
  cookie = cookie1;
  const session = await raw('/me');
  const h = { live: true, calls: [], mode: '', after: null, stateReads: 0, planReads: [] };
  const flow = new AssistantFlow(session.user, {
    current: () => h.live,
    read: async route => {
      if (route === '/state') h.stateReads++;
      if (/^\/assistant\/plans\/[a-f0-9]{32}$/.test(route)) h.planReads.push(route);
      const result = await raw(route);
      if (h.after && route.startsWith('/assistant/search')) await h.after();
      return result;
    },
    mutate: async (route, method, value) => {
      h.calls.push({ route, method, value: plain(value) });
      if (route.endsWith('/apply') && h.mode === 'before') { h.mode = ''; throw new api.ApiError('Synthetic lost request', 0); }
      const result = await raw(route, method, value, session.csrf);
      if (h.after && route === '/assistant/plan') await h.after();
      if (route.endsWith('/apply') && h.mode === 'after') { h.mode = ''; throw new api.ApiError('Synthetic lost response after real commit', 0); }
      if (route.endsWith('/apply') && h.mode === 'malformed') { h.mode = ''; return {}; }
      return result;
    },
    refresh: async () => { h.stateReads++; await raw('/state'); },
  }, () => {});
  await flow.load(); assert.equal(flow.state.ready, true);
  return { flow, h };
}
const count = async title => (await raw('/state')).tasks.filter(x => x.title === title).length;
const ok = label => { checks.push(label); console.log('PASS ' + label); };

(async () => {
  let { flow, h } = await fixture();
  await flow.plan('待办：first exact；not selected', false, false);
  assert.equal(await count('first exact'), 0); assert.equal(flow.state.plan.actions.length, 2);
  flow.select(1); await flow.apply();
  assert.equal(await count('first exact'), 1); assert.equal(await count('not selected'), 0);
  assert.equal(flow.state.receipt.created.length, 1); const calls = h.calls.length; await flow.apply(); assert.equal(h.calls.length, calls);
  ok('real_preview_selected_apply_receipt_no_second_write');

  for (const mode of ['after', 'before', 'malformed']) {
    ({ flow, h } = await fixture());
    const title = 'uncertain ' + mode;
    await flow.plan('待办：' + title + '；kept out', false, false); flow.select(1); h.mode = mode;
    await flow.apply(); assert.ok(flow.state.pending); assert.equal(flow.state.receipt, null);
    const intent = plain(flow.state.pending); flow.select(1);
    assert.deepEqual(plain(flow.state.selected), [0]);
    const beforeCalls = h.calls.length; await flow.apply(); assert.equal(h.calls.length, beforeCalls);
    await flow.plan('待办：must not replace', false, false); assert.equal(h.calls.length, beforeCalls);
    await flow.checkOutcome(); assert.equal(h.planReads.at(-1), '/assistant/plans/' + intent.id);
    assert.equal(flow.state.checkedAfterUnknown, mode === 'before');
    assert.equal(await count(title), mode === 'before' ? 0 : 1);
    await flow.apply(); assert.equal(await count(title), 1); assert.equal(flow.state.receipt.created.length, 1);
    const writes = h.calls.filter(x => x.route.endsWith('/apply'));
    assert.equal(writes.length, mode === 'before' ? 2 : 1);
    if (mode === 'before') { assert.deepEqual(writes[0], writes[1]); assert.equal(writes[1].route, '/assistant/plans/' + intent.id + '/apply'); }
    else assert.equal(flow.state.pending, null); // GET applied receipt closes uncertainty without a second POST.
    ok('real_' + mode + '_unknown_readback_then_same_intent');
  }

  ({ flow, h } = await fixture());
  await flow.plan('待办：old plan cleared', false, false); await flow.plan('request AI', true, false);
  assert.equal(flow.state.plan, null); assert.ok(flow.state.error); assert.equal(await count('old plan cleared'), 0);
  ok('real_unconfigured_model_error_cannot_apply_old_plan');

  ({ flow, h } = await fixture()); await flow.plan('待办：different identity cannot apply', false, false);
  cookie = cookie2; await flow.apply(); assert.equal(flow.state.expired, true); assert.equal(flow.state.plan, null);
  assert.equal(h.calls.filter(x => x.route.endsWith('/apply')).length, 0);
  ok('real_member_switch_clears_draft_before_apply');

  ({ flow, h } = await fixture()); await flow.plan('待办：anonymous cannot apply', false, false);
  cookie = ''; await flow.apply(); assert.equal(flow.state.expired, true); assert.equal(flow.state.plan, null);
  ok('real_logout_clears_draft_before_apply');

  ({ flow, h } = await fixture());
  h.after = async () => { cookie = cookie2; }; await flow.plan('待办：late different member plan', false, false);
  assert.equal(flow.state.expired, true); assert.equal(flow.state.plan, null);
  ok('real_response_late_after_cookie_switch_discarded');

  ({ flow, h } = await fixture());
  h.after = async () => { h.live = false; flow.close(); }; await flow.plan('待办：left screen draft', false, false);
  assert.equal(flow.state.plan, null); assert.equal(flow.state.receipt, null);
  ok('late_plan_after_unmount_discarded');

  ({ flow, h } = await fixture()); await flow.plan('搜索：分页合成', true, true);
  assert.equal(flow.state.plan.id, null); assert.equal(flow.state.plan.mode, 'local');
  assert.equal(flow.state.search.total, 22); assert.equal(flow.state.search.matches.length, 20);
  await flow.search(flow.state.search.query, 20); assert.equal(flow.state.search.matches.length, 2);
  const beforeSearchApply = h.calls.length; await flow.apply(); assert.equal(h.calls.length, beforeSearchApply);
  ok('real_local_search_pagination_is_read_only_even_model_selected');

  h.after = async () => flow.setForeground(false);
  await flow.search('分页合成'); assert.equal(flow.state.search, null);
  flow.setForeground(true); assert.equal(flow.state.search, null);
  ok('late_search_during_background_cannot_reappear');

  ({ flow, h } = await fixture());
  await flow.plan('待办：same user session changed', false, false);
  cookie = process.env.ASSISTANT_TEST_COOKIE1_NEW;
  await flow.apply(); assert.equal(flow.state.expired, true); assert.equal(flow.state.plan, null);
  ok('same_member_new_csrf_session_clears_plan');

  fs.writeFileSync(process.env.ASSISTANT_TEST_REPORT, JSON.stringify({ passed: true, checks, boundary: 'Actual TS flow and real Flask/SQLite/session/CSRF; synthetic data, no model, browser layout or production acceptance.' }, null, 2));
})().catch(error => { console.error(error); process.exitCode = 1; });
