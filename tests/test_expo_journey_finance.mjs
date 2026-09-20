import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { runInNewContext } from 'node:vm';
import { webcrypto } from 'node:crypto';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../frontend');
const ts = createRequire(resolve(root, 'package.json'))('typescript');
const copy = x => JSON.parse(JSON.stringify(x));
function loader(mocks = {}, globals = {}) {
  const cache = new Map();
  function load(path) {
    path = resolve(path); if (!existsSync(path)) path += existsSync(path + '.ts') ? '.ts' : '.tsx';
    if (cache.has(path)) return cache.get(path);
    const exports = {}; cache.set(path, exports);
    const code = ts.transpileModule(readFileSync(path, 'utf8'), { fileName: path, compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
    runInNewContext(code, { exports, require: name => name in mocks ? mocks[name] : load(resolve(dirname(path), name)), Error, Date, URL, URLSearchParams, TextEncoder, AbortController, crypto: webcrypto, process: { env: {} }, ...globals });
    return exports;
  } return load;
}
const load = loader(), lib = load(resolve(root, 'src/lib/journeyFinance.ts')), api = load(resolve(root, 'src/lib/api.ts'));
const sessionIdentity = load(resolve(root, 'src/lib/sessionIdentity.ts')).sessionIdentity;
const journeyId = 'a'.repeat(24), tripId = 'b'.repeat(24), allocationId = 'c'.repeat(32), payId = 'original-payment_1';
const session = () => ({ user: { id: 'alice', name: '合成本人', role: 'member', householdId: 'home', auth_version: 1 }, csrf: 'synthetic-csrf' });
const j = () => ({ id: journeyId, tripId, title: '合成旅行', revision: 3, tripRevision: 5, sharedBudgetCents: 200000, sharedManualPaidCents: 99999, sharedSavedCents: 50000 });
const payment = (patch = {}) => ({ id: payId, revision: 7, title: '合成原付款', date: '2026-09-20', kind: 'payments', flow: 'expense', currency: 'CNY', amountCents: 100000, refundedCents: 10000, netCents: 90000, reservedCents: 0, availableCents: 90000, eligible: true, reasonCode: null, ...patch });
const link = (patch = {}) => ({ id: allocationId, revision: 1, journeyId, tripId, paymentId: payId, amountCents: 70000, status: 'active', state: 'current', reasonCodes: [], acceptedNetCents: 90000, acceptedRefundedCents: 10000, createdAt: '2026-09-20T00:00:00Z', updatedAt: '2026-09-20T00:00:00Z', journey: j(), payment: payment(), ...patch });
const page = (rows = [], q = { journeyId }) => ({ version: 1, journey: q.journeyId ? j() : null, summary: q.journeyId ? { currency: 'CNY', coverage: 'owner_partial', currentAllocatedCents: rows.filter(r => r.state === 'current').reduce((n, r) => n + r.amountCents, 0), needsReviewAllocatedCents: rows.filter(r => r.state === 'needs_review').reduce((n, r) => n + r.amountCents, 0), activeAllocatedCents: rows.filter(r => r.status === 'active').reduce((n, r) => n + r.amountCents, 0), currentCount: rows.filter(r => r.state === 'current').length, needsReviewCount: rows.filter(r => r.state === 'needs_review').length, sharedBudgetCents: 200000 } : null, allocations: rows, pageInfo: { page: q.page || 0, pageSize: 40, hasMore: false }, readAt: '2026-09-20T00:00:00Z' });
const preview = plan => ({ version: 1, operation: plan.operation, allocationId: plan.operation === 'apply' ? null : allocationId, journey: j(), payment: payment(), beforeAllocatedCents: plan.operation === 'apply' ? 0 : 70000, afterAllocatedCents: plan.operation === 'revoke' ? 0 : plan.amountCents, beforeStatus: plan.operation === 'apply' ? null : 'active', afterStatus: plan.operation === 'revoke' ? 'revoked' : 'active', unchanged: { ledger: true, shopping: true, sharedTrip: true }, warnings: [], previewToken: 'synthetic-opaque-token', expiresAt: new Date(Date.now() + 600000).toISOString(), expiresInSeconds: 600 });
const receipt = intent => ({ requestId: intent.requestId, allocationId, revision: 1, operation: 'apply', completedAt: '2026-09-20T00:00:00Z' });
const store = () => { const data = new Map(); return { data, getItem: k => data.get(k) ?? null, setItem: (k, v) => data.set(k, v), removeItem: k => data.delete(k) }; };
const deferred = () => { let release; const promise = new Promise(resolve => { release = resolve; }); return { promise, release }; };

test('integer cents are exact; no rounding, exponent, unsafe amount or net over-allocation', () => {
  assert.equal(lib.amountCents('0.29'), 29); assert.equal(lib.amountCents('1000000000'), 100000000000);
  for (const value of ['0', '-1', '1.001', '1e3', '1,000', '1000000000.01']) assert.throws(() => lib.amountCents(value));
  const plan = lib.allocationPlan(j(), payment(), '700.00'); assert.equal(plan.amountCents, 70000); assert.equal(plan.paymentId, payId); assert.equal(plan.paymentRevision, 7); assert.equal(plan.tripRevision, 5);
  assert.throws(() => lib.allocationPlan(j(), payment(), '900.01'));
  assert.throws(() => lib.allocationPlan(j(), payment({ currency: 'USD', eligible: false, reasonCode: 'unsupported_currency' }), '1'));
  assert.throws(() => lib.allocationPlan(j(), payment(), '1', link({ journeyId: 'd'.repeat(24) })));
});
test('summary is all-page owner partial, not recomputed from page or shared manual amount', () => {
  const data = page([]); data.summary.currentAllocatedCents = 70000; data.summary.activeAllocatedCents = 70000; data.summary.currentCount = 2;
  assert.equal(lib.readAllocations(data, { journeyId }).summary.currentAllocatedCents, 70000);
  for (const patch of [{ coverage: 'family_total' }, { currency: 'USD' }, { activeAllocatedCents: 1 }]) assert.throws(() => lib.readAllocations({ ...data, summary: { ...data.summary, ...patch } }, { journeyId }));
});
test('DTO bounds reject mismatched original IDs, duplicate rows and wrong page/scope', () => {
  assert.throws(() => lib.allocationsPath({ journeyId, paymentId: payId }));
  assert.throws(() => lib.readAllocations(page([link(), link()]), { journeyId }));
  assert.throws(() => lib.readAllocations(page([link({ payment: payment({ id: 'another' }) })]), { journeyId }));
  assert.throws(() => lib.readAllocations(page(), { journeyId, page: 1 }));
  assert.throws(() => lib.readPayment(payment({ kind: 'orders' })));
  assert.throws(() => lib.readPayment(payment({ amountCents: 1.1 })));
});
test('payment update focus can be outside page; same original ID is mandatory', () => {
  const v = { version: 1, journey: j(), payments: [], focus: payment(), pageInfo: { page: 2, pageSize: 40, hasMore: false }, readAt: '2026-09-20T00:00:00Z' };
  assert.equal(lib.readPayments(v, journeyId, 2, payId).focus.id, payId);
  assert.throws(() => lib.readPayments(v, journeyId, 2, 'wrong'));
  assert.throws(() => lib.readPayments(v, journeyId, 2));
});
test('orphan and refund-drift links remain visible history without inventing missing titles', () => {
  const row = link({ journey: null, payment: null, state: 'needs_review', reasonCodes: ['journey_missing', 'source_missing'] });
  const parsed = lib.readAllocations(page([row], {}), { status: 'all' }); assert.equal(parsed.allocations[0].journey, null); assert.equal(parsed.allocations[0].payment, null);
  assert.equal(lib.readAllocation(link({ state: 'needs_review', reasonCodes: ['payment_overallocated'] })).amountCents, 70000);
});
test('preview must bind operation, amount, original IDs, revisions and unchanged domains', () => {
  const plan = lib.allocationPlan(j(), payment(), '700'); const p = preview(plan); assert.equal(lib.readPreview(p, plan).afterAllocatedCents, 70000);
  for (const patch of [{ afterAllocatedCents: 1 }, { operation: 'revoke' }, { payment: payment({ revision: 8 }) }, { journey: { ...j(), id: 'd'.repeat(24) } }, { unchanged: { ledger: false, shopping: true, sharedTrip: true } }]) assert.throws(() => lib.readPreview({ ...p, ...patch }, plan));
});
test('unknown receipt false is not success; receipt ID mismatch and malformed result reject', () => {
  const intent = { requestId: '1'.repeat(32), previewToken: 'opaque' };
  assert.equal(lib.readOperation({ version: 1, requestId: intent.requestId, found: false, receipt: null }, intent), null);
  assert.throws(() => lib.readOperation({ version: 1, requestId: intent.requestId, found: false, receipt: receipt(intent) }, intent));
  assert.throws(() => lib.readConfirmation({ version: 1, replayed: true, receipt: receipt({ requestId: '2'.repeat(32) }) }, intent));
});
test('session persistence contains only opaque original request and hash; another identity clears it', async () => {
  const s = store(), digest = await lib.identityDigest(sessionIdentity(session())), intent = { requestId: '1'.repeat(32), previewToken: 'opaque' };
  lib.persistIntent(s, digest, intent); const raw = [...s.data.values()][0]; assert.deepEqual(Object.keys(JSON.parse(raw)).sort(), ['identity', 'previewToken', 'requestId', 'version']); assert(!raw.includes('alice')); assert(!raw.includes('csrf'));
  assert.deepEqual(copy(lib.restoreIntent(s, digest)), intent); assert.equal(lib.restoreIntent(s, 'f'.repeat(64)), null); assert.equal(s.data.size, 0);
});
test('only parsed confirm rejection clears unknown, never pre/post me or malformed JSON 409', async () => {
  const reject = () => Promise.reject(new api.ApiError('stale', 409, 'journey_finance_stale'));
  await assert.rejects(lib.checkedConfirm(fn => fn('csrf'), reject), lib.JourneyConfirmRejected);
  await assert.rejects(lib.checkedConfirm(reject, async () => 'not called'), e => !(e instanceof lib.JourneyConfirmRejected));
  await assert.rejects(lib.checkedConfirm(async fn => { await fn('csrf'); return reject(); }, async () => 'committed'), e => !(e instanceof lib.JourneyConfirmRejected));
  await assert.rejects(lib.checkedConfirm(fn => fn('csrf'), () => Promise.reject(new api.ApiError('bad JSON', 409))), e => !(e instanceof lib.JourneyConfirmRejected));
});
test('existing identity fence rejects late result and changed session before write', async () => {
  let me = session(), writes = 0; const f = new lib.JourneyFinanceFence(async () => copy(me), sessionIdentity(me));
  me = { ...me, csrf: 'changed' }; await assert.rejects(f.run(async () => { writes++; }, () => true)); assert.equal(writes, 0);
  me = session(); const g = deferred(), work = f.run(async () => { await g.promise; return 'private'; }, () => true);
  await new Promise(setImmediate); me = { user: { ...me.user, id: 'bob' }, csrf: 'bob' }; g.release(); await assert.rejects(work);
});

// Actual TSX/fence/session store. Host/transport are synthetic; these tests are
// not Flask/SQLite/browser evidence and never stand in for final integration.
function harness(options = {}) {
  const f = { session: session(), links: [], payment: payment(), calls: [], writes: [], confirms: 0, receipt: null, drop: false, found: true, listFail: false, gate: null, ...options };
  const saved = options.store || store(), listeners = new Map(), timers = new Map(); let serial = 0, holder, cursor, dirty = true, tree, closed = false;
  const instances = new Map(), types = new Map(), effects = [];
  const events = { addEventListener(k, fn) { if (!listeners.has(k)) listeners.set(k, new Set()); listeners.get(k).add(fn); }, removeEventListener(k, fn) { listeners.get(k)?.delete(fn); } };
  const document = { hidden: false, hasFocus: () => true, ...events }, window = { sessionStorage: saved, ...events }, navigator = { onLine: true };
  const changed = (a, b) => !a || !b || a.length !== b.length || a.some((x, i) => x !== b[i]);
  const useState = init => { const h = holder, i = cursor++; if (!(i in h.values)) h.values[i] = typeof init === 'function' ? init() : init; return [h.values[i], v => { if (!h.dead) { h.values[i] = typeof v === 'function' ? v(h.values[i]) : v; dirty = true; } }]; };
  const useRef = init => { const i = cursor++; if (!(i in holder.values)) holder.values[i] = { current: init }; return holder.values[i]; };
  const useEffect = (fn, deps) => { const h = holder, i = cursor++; if (changed(h.values[i], deps)) { h.values[i] = deps; effects.push(() => { h.cleanups[i]?.(); if (!h.dead) h.cleanups[i] = fn(); }); } };
  const useCallback = (fn, deps) => { const i = cursor++; if (!holder.values[i] || changed(holder.values[i].deps, deps)) holder.values[i] = { deps, fn }; return holder.values[i].fn; };
  const react = { useState, useRef, useEffect, useCallback, createElement: (type, props, ...children) => ({ type, props: { ...props, children: children.flat(Infinity).filter(n => n !== null && n !== undefined && n !== false) } }), Fragment: 'Fragment' };
  const household = { user: copy(f.session.user), identityKey: sessionIdentity(f.session), online: true, refresh: async () => { f.refreshed = true; } };
  async function request(path, options = {}) {
    f.calls.push(path); const u = new URL('https://synthetic.invalid' + path); let value;
    if (path === '/me') { if (f.meError) throw new api.ApiError('unavailable', f.meError); if (f.afterMeError && f.confirms) throw new api.ApiError('identity failed', 409, 'journey_finance_stale'); return copy(f.session); }
    if (path.endsWith('/preview')) { const plan = JSON.parse(options.body); f.writes.push({ path, plan }); f.plan = plan; value = { ...preview(plan), payment: f.payment }; }
    else if (path.endsWith('/confirm')) {
      const intent = JSON.parse(options.body); f.writes.push({ path, intent }); f.confirms++;
      if (f.reject) throw new api.ApiError('stale', 409, 'journey_finance_stale');
      if (!f.receipt) { f.receipt = { ...receipt(intent), operation: f.plan?.operation || 'apply' }; f.links = [link({ amountCents: f.plan?.amountCents || 70000, revision: f.plan?.operation === 'apply' ? 1 : 2, state: f.plan?.operation === 'revoke' ? 'revoked' : 'current', status: f.plan?.operation === 'revoke' ? 'revoked' : 'active' })]; }
      value = { version: 1, receipt: f.receipt, replayed: f.confirms > 1 };
      if (f.drop) throw new api.ApiError('connection lost');
    }
    else if (path.includes('/operations/')) value = { version: 1, requestId: path.split('/').at(-1), found: !!f.receipt && f.found, receipt: f.found ? f.receipt : null };
    else if (u.pathname.endsWith('/payments')) value = { version: 1, journey: j(), payments: [f.payment], focus: u.searchParams.has('allocationId') ? f.payment : null, pageInfo: { page: Number(u.searchParams.get('page')), pageSize: 40, hasMore: false }, readAt: '2026-09-20T00:00:00Z' };
    else if (u.pathname === '/finance-hub/journey-allocations') { if (f.listFail) throw new api.ApiError('read failed', 503); value = page(copy(f.links.filter(r => u.searchParams.get('status') === 'all' || r.status === 'active')), { journeyId: u.searchParams.get('journeyId'), page: Number(u.searchParams.get('page')) }); }
    else if (u.pathname === '/finance-hub/reconciliation') value = { transaction: { ...f.payment, category: '旅行', source: 'generic' } };
    else throw new Error('Unexpected synthetic path ' + path);
    if (f.gate?.test(path)) { f.gate.used = true; await f.gate.promise; }
    return copy(value);
  }
  const paper = Object.fromEntries(['ActivityIndicator', 'Button', 'Text', 'TextInput', 'Portal'].map(k => [k, k]));
  paper.Dialog = Object.assign('Dialog', { Title: 'DialogTitle', Content: 'DialogContent', Actions: 'DialogActions' }); paper.useTheme = () => ({ colors: { error: '#b00' } });
  const mocks = { react, 'expo-router': { useFocusEffect: fn => useEffect(fn, [fn]) }, 'react-native': { View: 'View', StyleSheet: { create: x => x }, AppState: { currentState: 'active', addEventListener: () => ({ remove() {} }) } }, 'react-native-paper': paper, '../lib/household': { useHousehold: () => household }, './api.ts': { ...api, request }, '../lib/api': { ...api, request }, '../ui/components': { SectionCard: 'SectionCard', PageHeader: 'PageHeader', EmptyState: 'EmptyState' } };
  const ui = loader(mocks, { document, window, navigator, setTimeout: fn => { const id = ++serial; timers.set(id, fn); return id; }, clearTimeout: id => timers.delete(id), setInterval: fn => { const id = ++serial; timers.set(id, fn); return id; }, clearInterval: id => timers.delete(id) });
  const Component = ui(resolve(root, 'src/components/JourneyFinancePanel.tsx')).default;
  const props = { journeyId, onBack() { f.back = true; }, onPendingChange(v) { f.pendingNavigation = v; }, ...options.props };
  function expand(n, path = 'root', seen = new Set()) {
    if (!n || typeof n !== 'object') return n;
    if (Array.isArray(n)) return n.map((v, i) => expand(v, path + '.' + i, seen));
    if (typeof n.type === 'function') { if (!types.has(n.type)) types.set(n.type, types.size + 1); const key = path + ':' + types.get(n.type) + ':' + (n.props.key ?? ''); seen.add(key); if (!instances.has(key)) instances.set(key, { values: [], cleanups: [], dead: false }); holder = instances.get(key); cursor = 0; return expand(n.type(n.props), key, seen); }
    return { ...n, props: { ...n.props, action: expand(n.props.action, path + '.action', seen), children: n.props.children.map((v, i) => expand(v, path + '.' + i, seen)) } };
  }
  function render() { dirty = false; const seen = new Set(); tree = expand(react.createElement(Component, props), 'root', seen); for (const [k, h] of instances) if (!seen.has(k)) { h.dead = true; h.cleanups.forEach(fn => fn?.()); instances.delete(k); } while (effects.length) effects.shift()(); }
  async function flush() { for (let i = 0; i < 60; i++) { if (dirty && !closed) render(); await new Promise(setImmediate); } assert(!dirty || closed); }
  const hidden = n => n?.props?.visible === false;
  function nodes(n = tree) { if (!n || typeof n !== 'object' || hidden(n)) return []; if (Array.isArray(n)) return n.flatMap(v => nodes(v)); return [n, ...nodes(n.props.action ?? null), ...n.props.children.flatMap(v => nodes(v))]; }
  function text(n = tree) { if (typeof n === 'string' || typeof n === 'number') return String(n); if (!n || typeof n !== 'object' || hidden(n)) return ''; return [n.props.title || '', n.props.description || '', ...n.props.children.map(v => text(v)), text(n.props.action ?? null)].join(' '); }
  const controls = label => nodes().filter(n => (n.props.accessibilityLabel || n.props.label || text(n).trim().replace(/\s+/g, ' ')) === label && (n.props.onPress || n.props.onChangeText));
  async function click(label) { const n = controls(label); assert.equal(n.length, 1, label + '\n' + text()); assert(!n[0].props.disabled, label + ' disabled'); n[0].props.onPress(); await flush(); }
  async function input(label, value) { const n = controls(label); assert.equal(n.length, 1, label); assert(!n[0].props.disabled); n[0].props.onChangeText(value); await flush(); }
  return { f, store: saved, household, props, flush, text, nodes, controls, click, input,
    async draft() { await flush(); await click('选择实际付款'); await click('选择这笔付款'); await input('归集金额', '700.00'); },
    async emit(event) { for (const fn of [...(listeners.get(event) || [])]) fn({}); await flush(); },
    async offline() { navigator.onLine = false; household.online = false; await this.emit('offline'); dirty = true; await flush(); },
    async online() { navigator.onLine = true; household.online = true; await this.emit('online'); dirty = true; await flush(); },
    async switchMember() { f.session = { user: { ...f.session.user, id: 'bob' }, csrf: 'bob' }; household.user = copy(f.session.user); household.identityKey = sessionIdentity(f.session); f.links = []; dirty = true; await flush(); },
    close() { closed = true; for (const h of instances.values()) { h.dead = true; h.cleanups.forEach(fn => fn?.()); } },
  };
}

test('actual panel applies original payment and displays readback; original record round trip keeps list', async t => {
  const h = harness(); t.after(h.close); await h.draft(); await h.click('预览归集'); await h.click('确认归集');
  assert.equal(h.f.confirms, 1); assert.match(h.text(), /仅本人已归集\s+CNY 700\.00/); assert.equal(h.f.pendingNavigation, false);
  assert(!h.text().includes('999.99')); await h.click('查看原付款'); assert(h.nodes().some(n => n.props.testID === 'journey-finance-original-payment')); assert(h.text().includes(payId)); await h.click('返回旅行费用'); assert(h.nodes().some(n => n.props.testID === 'journey-allocation-' + allocationId));
});
test('confirmed POST with lost response persists original intent; remount queries receipt without another POST', async t => {
  const h = harness({ drop: true }); await h.draft(); await h.click('预览归集'); await h.click('确认归集'); assert.equal(h.f.confirms, 1); assert(h.nodes().some(n => n.props.testID === 'journey-finance-unknown')); const stored = [...h.store.data.values()][0]; h.close();
  const next = harness({ store: h.store, receipt: h.f.receipt, links: h.f.links }); t.after(next.close); await next.flush(); assert.equal(next.f.confirms, 0); assert(next.f.calls.some(p => p.includes('/operations/' + JSON.parse(stored).requestId))); assert.equal(next.store.data.size, 0); assert(next.text().includes('已保存'));
});
test('found=false freezes new writes; explicit retry uses exact original request body', async t => {
  const h = harness({ drop: true, found: false }); t.after(h.close); await h.draft(); await h.click('预览归集'); await h.click('确认归集'); const original = h.f.writes.at(-1).intent;
  await h.click('核对原请求'); assert(h.text().includes('不能据此判断未提交')); assert.equal(h.f.confirms, 1); assert.equal(h.controls('选择实际付款').length, 0);
  h.f.drop = false; await h.click('重试原请求'); assert.deepEqual(h.f.writes.at(-1).intent, original); assert.equal(h.f.confirms, 2);
});
test('POST success then me409 preserves pending; direct business409 preserves amount draft only', async t => {
  const h = harness({ afterMeError: true }); t.after(h.close); await h.draft(); await h.click('预览归集'); await h.click('确认归集'); assert.equal(h.store.data.size, 1); assert(h.text().includes('身份暂时无法核实')); assert(!h.text().includes('合成原付款')); h.f.afterMeError = false; await h.click('刷新旅行费用'); assert.equal(h.f.confirms, 1); assert.equal(h.store.data.size, 0);
  const other = harness({ reject: true }); t.after(other.close); await other.draft(); await other.click('预览归集'); await other.click('确认归集'); assert.equal(other.store.data.size, 0); assert.equal(other.controls('归集金额')[0].props.value, '700.00'); assert.equal(other.f.confirms, 1);
});
test('saved receipt with list failure retries GET only', async t => {
  const h = harness(); t.after(h.close); await h.draft(); await h.click('预览归集'); h.f.listFail = true; await h.click('确认归集'); assert(h.text().includes('已保存，资料暂未刷新')); assert.equal(h.store.data.size, 0);
  h.f.listFail = false; await h.click('刷新旅行费用'); assert.equal(h.f.confirms, 1); assert(h.text().includes('合成原付款'));
});
test('offline hides financial draft; same identity restores safe amount and re-reads versions', async t => {
  const h = harness(); t.after(h.close); await h.draft(); await h.offline(); assert(!h.text().includes('合成原付款')); assert.equal(h.controls('归集金额').length, 0); h.f.payment.revision = 8; await h.online(); assert.equal(h.controls('归集金额')[0].props.value, '700.00'); await h.click('预览归集'); assert.equal(h.f.writes.at(-1).plan.paymentRevision, 8);
});
test('late private list discarded by post-me; new identity does not inherit pending or draft', async t => {
  const h = harness({ links: [link()] }); t.after(h.close); await h.flush(); const gate = { ...deferred(), test: path => path.startsWith('/finance-hub/journey-allocations?') }; h.f.gate = gate;
  const read = h.click('刷新旅行费用'); await h.flush(); assert(gate.used); h.f.session = { user: { ...h.f.session.user, id: 'bob' }, csrf: 'bob' }; gate.release(); await read; await h.flush(); assert(!h.text().includes('合成原付款')); assert(h.nodes().some(n => n.props.testID === 'journey-finance-hidden'));
  const unknown = harness({ drop: true }); await unknown.draft(); await unknown.click('预览归集'); await unknown.click('确认归集'); assert.equal(unknown.store.data.size, 1); await unknown.switchMember(); assert.equal(unknown.store.data.size, 0); unknown.close();
});
test('orphan allocation in unscoped finance history can preview revoke without original entities', async t => {
  const h = harness({ props: { journeyId: undefined }, links: [link({ journey: null, payment: null, state: 'needs_review', reasonCodes: ['journey_missing', 'source_missing'] })] }); t.after(h.close); await h.flush(); assert(h.text().includes('原旅行已删除')); assert(h.controls('调整归集')[0].props.disabled); await h.click('解除归集'); await h.click('预览解除'); assert.equal(h.f.writes.at(-1).plan.operation, 'revoke'); assert.deepEqual(Object.keys(h.f.writes.at(-1).plan).sort(), ['allocationId', 'operation', 'revision']);
});
test('independent application navigation guard does not clear other panels and rejects stale actor/route', () => {
  const source = readFileSync(resolve(root, 'src/screens/HouseholdApp.tsx'), 'utf8');
  const code = source.match(/const onJourneyFinancePending=useCallback\([\s\S]*?\},\[actor,route\]\);/)[0];
  const compiled = ts.transpileModule(code + '\nglobalThis.invoke=onJourneyFinancePending;', { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  const pendingNavigation = { current: { source: 'shopping-settlement', locked: true } }, activeActor = { current: 'a' }, activeRoute = { current: 'finance' };
  const context = { useCallback: fn => fn, actor: 'a', route: 'finance', activeActor, activeRoute, pendingNavigation }; runInNewContext(compiled, context);
  context.invoke(false); assert.equal(pendingNavigation.current.source, 'shopping-settlement'); context.invoke(true); assert.equal(pendingNavigation.current.source, 'journey-finance'); assert(pendingNavigation.current.message.includes('旅行费用'));
  activeActor.current = 'b'; context.invoke(false); assert.equal(pendingNavigation.current.locked, true); activeActor.current = 'a'; context.invoke(false); assert.equal(pendingNavigation.current.locked, false);
});


test('update preview cannot substitute another original payment or journey with matching revisions', () => {
  const plan = lib.allocationPlan(j(), payment(), '600.00', link()), expected = { journeyId, paymentId: payId };
  const p = preview(plan); assert.equal(lib.readPreview(p, plan, expected).afterAllocatedCents, 60000);
  assert.throws(() => lib.readPreview(p, plan));
  assert.throws(() => lib.readPreview({ ...p, payment: payment({ id: 'different' }) }, plan, expected));
  assert.throws(() => lib.readPreview({ ...p, journey: { ...j(), id: 'd'.repeat(24) } }, plan, expected));
});

test('actual refund adjustment keeps allocation ID, fresh payment revision and only explicit new amount', async t => {
  const fresh = payment({ revision: 8, refundedCents: 40000, netCents: 60000, availableCents: 60000 });
  const h = harness({ payment: fresh, links: [link({ state: 'needs_review', reasonCodes: ['source_changed', 'payment_overallocated'], payment: { ...fresh, reservedCents: 70000, availableCents: 0 } })] }); t.after(h.close); await h.flush();
  assert.match(h.text(), /需核对\s+CNY 700\.00/); await h.click('调整归集'); assert.equal(h.controls('归集金额')[0].props.value, '700.00'); await h.input('归集金额', '600.00'); await h.click('预览归集');
  const plan = h.f.writes.at(-1).plan; assert.deepEqual(copy(plan), { operation: 'update', allocationId, revision: 1, journeyRevision: 3, tripRevision: 5, paymentRevision: 8, amountCents: 60000 });
  await h.click('确认归集'); assert.equal(h.f.confirms, 1); assert(h.nodes().some(n => n.props.testID === 'journey-allocation-' + allocationId)); assert.match(h.text(), /仅本人已归集\s+CNY 600\.00/);
});

test('global orphan revoke confirms original allocation revision and does not revive deleted references', async t => {
  const h = harness({ props: { journeyId: undefined }, links: [link({ journey: null, payment: null, state: 'needs_review', reasonCodes: ['journey_missing', 'source_missing'] })] }); t.after(h.close); await h.flush(); await h.click('解除归集'); await h.click('预览解除'); await h.click('确认解除');
  assert.equal(h.f.confirms, 1); assert.equal(h.f.writes[0].plan.allocationId, allocationId); assert.equal(h.f.writes[0].plan.revision, 1); assert.equal(h.f.links[0].status, 'revoked'); assert.equal(h.f.calls.filter(p => p.startsWith('/journeys')).length, 0); assert.equal(h.f.writes.length, 2);
});


test('preflight me404 hides a draft without posting, then same identity can recover the amount', async t => {
  const h = harness(); t.after(h.close); await h.draft(); h.f.meError = 404; await h.click('预览归集'); assert.equal(h.f.writes.length, 0); assert(!h.text().includes('合成原付款')); assert.equal(h.controls('归集金额').length, 0);
  h.f.meError = 0; await h.click('刷新旅行费用'); assert.equal(h.controls('归集金额')[0].props.value, '700.00'); await h.click('预览归集'); assert.equal(h.f.writes.length, 1);
});
