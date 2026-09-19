import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { runInNewContext } from 'node:vm';
const require = createRequire(import.meta.url), ts = require('typescript');
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../src');
const clone = value => JSON.parse(JSON.stringify(value));
function loader(mocks = {}, globals = {}) {
  const cache = new Map();
  function load(path) {
    path = resolve(path); if (!existsSync(path)) path += existsSync(path + '.ts') ? '.ts' : '.tsx';
    if (cache.has(path)) return cache.get(path);
    const exports = {}; cache.set(path, exports);
    const js = ts.transpileModule(readFileSync(path, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
    runInNewContext(js, { exports, require: name => name in mocks ? mocks[name] : load(resolve(dirname(path), name)), console, Date, Intl, Error, TypeError, setTimeout, clearTimeout, ...globals });
    return exports;
  }
  return load;
}
const load = loader(), api = load(resolve(root, 'lib/assistantTripChange.ts')), route = load(resolve(root, 'lib/assistantJourney.ts'));
const aid = 'a'.repeat(24), bid = 'b'.repeat(24), tid = 'c'.repeat(24), refA = 'trip_' + 'd'.repeat(24), refB = 'trip_' + 'e'.repeat(24);
const candidate = (other = false) => ({ ref: other ? refB : refA, journeyId: other ? bid : aid, tripId: other ? 'f'.repeat(24) : tid, revision: 3, title: '冰岛旅行', start: other ? '2027-10-01' : '2026-10-01', end: other ? '2027-10-07' : '2026-10-07', timeZones: ['Atlantic/Reykjavik'], sourceIssues: [] });
function plan(status = 'ready', other = false) {
  const selected = ['ready', 'needs_input'].includes(status) ? candidate(other) : null;
  const source = selected && { journeyId: selected.journeyId, tripId: selected.tripId, revision: selected.revision, tripRevision: 7, title: selected.title, start: selected.start, end: selected.end, sourceVersion: 'a'.repeat(64) };
  return { version: 1, intent: 'reschedule_existing', status, mode: 'local', candidates: status === 'choose_trip' ? [candidate(), candidate(true)] : selected ? [selected] : [], selected,
    change: status === 'needs_input' ? { kind: 'start_date', days: null, startDate: null, monthDay: '10-08' } : { kind: 'shift_days', days: 3, startDate: null, monthDay: null }, missingFields: status === 'needs_input' ? ['year'] : status === 'choose_trip' ? ['trip'] : [], issues: [],
    draft: status === 'ready' ? { journeyId: source.journeyId, tripId: source.tripId, revision: 3, start: other ? '2027-10-04' : '2026-10-04', end: other ? '2027-10-10' : '2026-10-10', calendarDays: true } : null,
    requiresPreview: true, source, selectionToken: status === 'choose_trip' ? 'PRIVATE-SELECTION-TOKEN' : null, selectionExpiresIn: status === 'choose_trip' ? 600 : null };
}
function snapshot() {
  return { journeyId: aid, revision: 3, start: '2026-10-01', end: '2026-10-07', snapshotToken: 'PRIVATE-SNAPSHOT', expiresIn: 600, warnings: [], capabilities: { shoppingDue: false }, items: [
    { key: 'trip', kind: 'overview', title: '冰岛旅行', before: { start: '2026-10-01', end: '2026-10-07' }, eligible: false, reason: null, endExclusive: false },
    { key: 'task:packing', kind: 'task', title: '打包行李', before: { start: '2026-09-29', end: '2026-09-29' }, eligible: true, reason: null, endExclusive: false },
  ] };
}
test('existing-trip changes route before new briefs, while search and list commands keep precedence', () => {
  for (const prompt of ['把冰岛旅行延后三天', '冰岛旅行不应该推迟三天', '把冰岛旅行改到10月8日']) { assert.equal(route.isExistingTripChangeRequest(prompt), true); assert.equal(route.isJourneyRequest(prompt), false); }
  for (const prompt of ['搜索冰岛旅行延后三天', '找一下冰岛旅行', '待办：把冰岛旅行推迟三天', '采购：旅行改期保险', '任务：旅行提前三天']) assert.equal(route.isExistingTripChangeRequest(prompt), false);
  assert.equal(route.isJourneyRequest('计划一次冰岛旅行'), true);
  assert.deepEqual(clone(route.assistantPlanOptions('搜索旅行改期', true, true)), { useModel: false, includeHouseholdContext: false });
});
test('wire decoder binds selected candidate, live source, date interpretation and unsigned draft', () => {
  const ready = api.readTripChange(plan()); assert.equal(ready.status, 'ready');
  for (const change of [p => { p.source.tripId = bid; }, p => { p.draft.revision++; }, p => { p.draft.end = '2026-10-11'; }, p => { p.change.days = 4; }, p => { p.issues = ['negated_request']; }, p => { p.selectionToken = 'unexpected'; }, p => { p.selected.ref = refB; }]) {
    const raw = clone(plan()); change(raw); assert.throws(() => api.readTripChange(raw));
  }
  assert.throws(() => api.readTripChange(plan(), refB));
  const missing = api.readTripChange(plan('needs_input')); assert.equal(missing.draft, null); assert(api.tripChangeHints(missing).some(h => h.includes('年份')));
});
test('candidate selection sends only the bound ticket and current reference', () => {
  const choices = api.readTripChange(plan('choose_trip'));
  assert.deepEqual(clone(api.tripSelectionRequest(choices, refB)), { selectionToken: 'PRIVATE-SELECTION-TOKEN', selectedRef: refB });
  assert.throws(() => api.tripSelectionRequest(choices, 'trip_' + 'f'.repeat(24)));
  assert.throws(() => api.tripSelectionRequest(api.readTripChange(plan()), refA));
});
test('real snapshot fields must match before suggested dates initialize and no associations are preselected', () => {
  const suggestion = api.tripSuggestion(api.readTripChange(plan())), source = snapshot();
  assert.deepEqual(clone(api.checkedTripSuggestion(source, suggestion)), { start: '2026-10-04', end: '2026-10-10', selectedKeys: [], timeOverrides: {} });
  for (const change of [s => { s.journeyId = bid; }, s => { s.revision++; }, s => { s.start = '2026-10-02'; }, s => { s.end = '2026-10-08'; }, s => { s.items[0].title = '已重命名'; }, s => { s.items[0].before.start = '2026-10-02'; }]) {
    const altered = snapshot(); change(altered); assert.throws(() => api.checkedTripSuggestion(altered, suggestion), /内容已变化/);
  }
});

// Execute production TSX with hook/Paper and transport doubles. These assertions
// exercise user actions and lifecycle, not browser layout or real provider calls.
function harness(kind = 'change', options = {}) {
  const f = { session: { user: { role: 'member', id: 'member1', householdId: 'home1', auth_version: 1 }, csrf: 'synthetic-csrf' }, calls: [], plan: plan(), snapshot: snapshot(), responseGate: null, status: 0, changeIdentityAfterPost: false, lost: false, receipt: null, planCalls: [], ...options };
  const slots = [], effects = [], cleanups = [], lifecycle = new Map(); let cursor = 0, dirty = true, tree, closed = false, pending = false, saved = null, back = null;
  const document = { hidden: false, addEventListener: (key, fn) => lifecycle.set(key, fn), removeEventListener: key => lifecycle.delete(key) }, window = { addEventListener: (key, fn) => lifecycle.set(key, fn), removeEventListener: key => lifecycle.delete(key) };
  const navigator = { onLine: true };
  const changed = (a, b) => !a || !b || a.length !== b.length || a.some((v, i) => v !== b[i]);
  const useState = initial => { const i = cursor++; if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial; return [slots[i], value => { slots[i] = typeof value === 'function' ? value(slots[i]) : value; dirty = true; }]; };
  const useRef = initial => { const i = cursor++; if (!(i in slots)) slots[i] = { current: initial }; return slots[i]; };
  const useEffect = (fn, deps) => { const i = cursor++; if (changed(slots[i], deps)) { slots[i] = deps; effects.push(() => { cleanups[i]?.(); cleanups[i] = fn(); }); } };
  const useCallback = (fn, deps) => { const i = cursor++; if (!slots[i] || changed(slots[i].deps, deps)) slots[i] = { deps, fn }; return slots[i].fn; };
  const react = { useState, useRef, useEffect, useCallback, Fragment: 'Fragment', createElement: (type, props, ...children) => ({ type, props: { ...props, children: children.flat(Infinity).filter(v => v !== undefined) } }) };
  class ApiError extends Error { constructor(message, status = 0, code = '') { super(message); this.status = status; this.code = code; } }
  const identity = load(resolve(root, 'lib/sessionIdentity.ts'));
  const household = { user: f.session.user, online: true, identityKey: identity.sessionIdentity(f.session), refresh: async () => {} };
  async function request(path, init = {}, csrf) {
    const body = init.body ? JSON.parse(init.body) : null; f.calls.push({ path, method: init.method || 'GET', body, csrf });
    if (path === '/me') return clone(f.session);
    if (path === '/assistant/trip-change') {
      if (f.responseGate) await f.responseGate;
      if (f.changeIdentityAfterPost) f.session.user.auth_version++;
      if (f.status) throw new ApiError('UNTRUSTED PROVIDER DETAIL', f.status, f.status === 409 ? 'stale_source' : 'model_unavailable');
      return clone(typeof f.plan === 'function' ? f.plan(body) : f.plan);
    }
    if (path === '/journeys/' + aid + '/reschedule') return clone(f.snapshot);
    if (path === '/journeys/' + aid + '/reschedule-preview') {
      f.previewBody = body;
      return { journeyId: aid, revision: f.snapshot.revision, start: body.start, end: body.end, items: f.snapshot.items.map(item => ({ ...clone(item), selected: item.key === 'trip' || body.selectedKeys.includes(item.key), after: item.key === 'trip' ? { start: body.start, end: body.end } : body.selectedKeys.includes(item.key) ? { start: '2026-10-02', end: '2026-10-02' } : clone(item.before) })), warnings: [], blockingIssues: [], canApply: true, previewToken: 'PRIVATE-PREVIEW', expiresIn: 600 };
    }
    if (path === '/journeys/apply') {
      f.receipt = { id: aid, tripId: tid, revision: 4, replayed: false, operation: 'reschedule', reschedule: { start: f.previewBody.start, end: f.previewBody.end, changedKeys: ['trip', ...f.previewBody.selectedKeys] } };
      f.snapshot.revision = 4; f.snapshot.start = f.previewBody.start; f.snapshot.end = f.previewBody.end; f.snapshot.items[0].before = { start: f.snapshot.start, end: f.snapshot.end };
      if (f.lost) throw new ApiError('lost response'); return clone(f.receipt);
    }
    if (path.startsWith('/journeys/operations/')) return { found: true, idempotencyKey: path.split('/').at(-1), result: clone(f.receipt) };
    throw new Error('Unexpected API path: ' + path);
  }
  class AssistantFlow {
    constructor(_user, _transport, emit) { this.emit = emit; this.state = { ready: true, busy: false, expired: false, modelConfigured: true }; }
    async load() { this.emit(this.state); }
    async plan(...args) { f.planCalls.push(args); }
    close() {} setForeground() {}
  }
  const mocks = { react, 'react-native': { AppState: { currentState: 'active', addEventListener: (_key, fn) => { lifecycle.set('app', fn); return { remove() {} }; } }, StyleSheet: { create: value => value }, View: 'View' }, 'expo-router': { useFocusEffect: fn => useEffect(fn, [fn]) },
    'react-native-paper': { ...Object.fromEntries(['ActivityIndicator', 'Button', 'Checkbox', 'Chip', 'Dialog', 'Divider', 'HelperText', 'Portal', 'Text', 'TextInput'].map(key => [key, key])), useTheme: () => ({ colors: { onSurfaceVariant: 'gray' } }) },
    '../lib/api': { ApiError, request }, '../lib/household': { useHousehold: () => household }, '../ui/components': { EmptyState: 'EmptyState', PageHeader: 'PageHeader', SectionCard: 'SectionCard' }, '../ui/SelectionRow': { SelectionRow: 'SelectionRow' },
    '../components/AssistantFinanceQueryPanel': { __esModule: true, default: 'AssistantFinanceQueryPanel' },
    '../screens/JourneyReschedulePanel': { __esModule: true, default: 'JourneyReschedulePanel' }, '../lib/assistant': { AssistantFlow, memberKey: identity.memberIdentity },
    './JourneyBriefPanel': { __esModule: true, default: 'JourneyBriefPanel' }, './TripsScreen': { __esModule: true, default: 'TripsScreen' }, '../components/ExistingTripChangePanel': { __esModule: true, default: 'ExistingTripChangePanel' },
  };
  const uiLoad = loader(mocks, { document, window, navigator, crypto: { getRandomValues: array => array.fill(17) } });
  const file = kind === 'change' ? 'components/ExistingTripChangePanel.tsx' : kind === 'reschedule' ? 'screens/JourneyReschedulePanel.tsx' : 'screens/AssistantScreen.tsx';
  const component = uiLoad(resolve(root, file)), props = kind === 'change' ? { initialPrompt: '把冰岛旅行推迟三天', initialUseModel: !!options.useModel, modelConfigured: true, onBack: value => { back = value; }, onSaved: value => { saved = value; }, onPendingChange: value => { pending = value; } } : kind === 'reschedule' ? { journeyId: aid, initialSuggestion: api.tripSuggestion(api.readTripChange(plan())), onBack: () => { back = true; }, onSaved: value => { saved = value; }, onPendingChange: value => { pending = value; } } : { user: f.session.user, state: { people: [] }, onNavigate() {} };
  function expand(node) { if (!node || typeof node !== 'object') return node; if (typeof node.type === 'function') return expand(node.type(node.props)); return { ...node, props: { ...node.props, children: (node.props.children || []).map(expand) } }; }
  function render() { cursor = 0; dirty = false; tree = expand((kind === 'assistant' ? component.AssistantScreen : component.default)(props)); for (const effect of effects.splice(0)) effect(); }
  async function settle() { for (let i = 0; i < 24; i++) { if (dirty && !closed) render(); await new Promise(resolve => setImmediate(resolve)); } }
  const nodes = (node = tree) => !node || typeof node !== 'object' ? [] : [node, ...node.props.children.flatMap(nodes)];
  const text = (node = tree) => typeof node === 'string' || typeof node === 'number' ? String(node) : node && typeof node === 'object' ? [node.props.title || '', node.props.description || '', ...node.props.children.map(text)].join(' ') : '';
  const control = label => nodes().find(node => ['Button', 'SelectionRow', 'TextInput'].includes(node.type) && (node.props.label === label || node.props.accessibilityLabel === label || text(node).trim().replace(/\s+/g, ' ') === label));
  async function click(label) { const node = control(label); assert(node, 'Missing: ' + label + '\n' + text()); assert(!node.props.disabled, 'Disabled: ' + label); node.props.onPress(); await settle(); }
  async function input(label, value) { const node = control(label); assert(node && !node.props.disabled, label); node.props.onChangeText(value); await settle(); }
  return { f, household, props, settle, click, input, nodes, control, text, writes: () => f.calls.filter(call => call.method === 'POST'), get pending() { return pending; }, get back() { return back; }, get saved() { return saved; }, async hide() { document.hidden = true; lifecycle.get('visibilitychange')(); await settle(); }, async show() { document.hidden = false; lifecycle.get('visibilitychange')(); await settle(); }, async offline() { navigator.onLine = false; household.online = false; lifecycle.get('offline')(); await settle(); }, async online() { navigator.onLine = true; household.online = true; lifecycle.get('online')(); await settle(); }, close() { closed = true; cleanups.forEach(cleanup => cleanup?.()); } };
}

test('assistant submit opens existing-change panel ahead of broad new-trip routing', async t => {
  const h = harness('assistant'); t.after(h.close); await h.settle(); await h.input('告诉助理你的需求', '把冰岛旅行延后三天'); await h.click('整理并预览');
  const entry = h.nodes().find(node => node.type === 'ExistingTripChangePanel'); assert(entry); assert.equal(entry.props.initialPrompt, '把冰岛旅行延后三天'); assert.equal(h.f.planCalls.length, 0);
});
test('assistant explicit search stays local even when AI was selected', async t => {
  const h = harness('assistant'); t.after(h.close); await h.settle(); await h.click('使用已配置的 AI 整理'); await h.input('告诉助理你的需求', '搜索冰岛旅行延后三天'); await h.click('整理并预览');
  assert.deepEqual(h.f.planCalls[0], ['搜索冰岛旅行延后三天', false, false]); assert(!h.nodes().some(node => node.type === 'ExistingTripChangePanel'));
});
test('single ready suggestion reads only planning API and does not preview or apply until user proceeds', async t => {
  const h = harness('change', { useModel: true }); t.after(h.close); await h.settle();
  assert.equal(h.writes().length, 1); assert.deepEqual(h.writes()[0].body, { prompt: '把冰岛旅行推迟三天', useModel: true }); assert.equal(h.writes()[0].csrf, 'synthetic-csrf');
  assert.match(h.text(), /2026-10-04/); await h.click('核对改期影响');
  const child = h.nodes().find(node => node.type === 'JourneyReschedulePanel'); assert(child); assert.equal(child.props.initialSuggestion.source.title, '冰岛旅行'); assert.equal(h.writes().length, 1);
});
test('multi-candidate selection reuses original ticket without repeating model payload or exposing token', async t => {
  const h = harness('change', { useModel: true, plan: body => body.selectedRef ? plan('ready', true) : plan('choose_trip') }); t.after(h.close); await h.settle();
  assert(!h.text().includes('PRIVATE-SELECTION-TOKEN')); await h.click('选择旅行 冰岛旅行 2027-10-01');
  assert.deepEqual(h.writes()[1].body, { selectionToken: 'PRIVATE-SELECTION-TOKEN', selectedRef: refB }); assert.match(h.text(), /2027-10-04/);
});
test('missing-year clarification keeps original text editable and never opens reschedule', async t => {
  const h = harness('change', { plan: plan('needs_input') }); t.after(h.close); await h.settle(); assert.match(h.text(), /请补充年份/); assert(!h.control('核对改期影响'));
  await h.input('改期需求', '把冰岛旅行改到2026年10月8日'); h.f.plan = plan(); await h.click('整理改期建议'); assert.equal(h.writes()[1].body.prompt, '把冰岛旅行改到2026年10月8日');
});
test('selection source conflict preserves request and discards stale choice token', async t => {
  const h = harness('change', { plan: plan('choose_trip') }); t.after(h.close); await h.settle(); h.f.status = 409; await h.click('选择旅行 冰岛旅行 2026-10-01');
  assert.match(h.text(), /来源或选择期限已变化/); assert.equal(h.control('改期需求').props.value, '把冰岛旅行推迟三天'); assert(!h.control('核对改期影响')); assert(!h.text().includes('UNTRUSTED PROVIDER DETAIL'));
  h.f.status = 0; h.f.plan = plan(); await h.click('整理改期建议'); assert.equal(h.writes()[2].body.prompt, '把冰岛旅行推迟三天');
});
test('background discards in-flight model result and resume does not call model automatically', async t => {
  let release; const gate = new Promise(resolve => { release = resolve; }); const h = harness('change', { responseGate: gate, useModel: true }); t.after(h.close); await h.settle(); await h.hide(); release(); await h.settle();
  assert(!h.control('改期需求')); h.f.responseGate = null; await h.show(); assert(!h.control('核对改期影响')); assert.equal(h.writes().length, 1); await h.click('整理改期建议'); assert.equal(h.writes().length, 2);
});
test('changed final session clears request and hides successful planning response', async t => {
  const h = harness('change', { changeIdentityAfterPost: true }); t.after(h.close); await h.settle(); assert.match(h.text(), /身份或权限已变化/); assert(!h.control('改期需求')); assert(!h.control('核对改期影响')); assert.equal(h.writes().length, 1);
});
test('TV role cannot open change workspace or invoke planning API', async t => {
  const h = harness('change'); t.after(h.close); h.household.user.role = 'tv'; await h.settle();
  assert.match(h.text(), /请用成员账户/); assert.equal(h.f.calls.length, 0); assert(!h.control('改期需求'));
});
test('offline hides original request and reconnect preserves it without another model call', async t => {
  const h = harness('change', { useModel: true }); t.after(h.close); await h.settle(); await h.input('改期需求', '把冰岛旅行提前两天'); await h.offline();
  assert(!h.control('改期需求')); assert(!h.control('核对改期影响')); await h.online(); assert.equal(h.control('改期需求').props.value, '把冰岛旅行提前两天'); assert.equal(h.writes().length, 1);
});
test('provider failure preserves request without fallback and local retry requires user choice', async t => {
  const h = harness('change', { useModel: true, status: 503 }); t.after(h.close); await h.settle(); assert.equal(h.writes().length, 1); assert(!h.text().includes('UNTRUSTED PROVIDER DETAIL')); assert(!h.control('核对改期影响'));
  await h.click('使用已配置的 AI 整理'); h.f.status = 0; await h.click('整理改期建议'); assert.equal(h.writes()[1].body.useModel, false); assert.equal(h.writes().length, 2);
});
test('real reschedule component rejects renamed source before initializing suggested dates', async t => {
  const source = snapshot(); source.items[0].title = '已修改标题'; const h = harness('reschedule', { snapshot: source }); t.after(h.close); await h.settle();
  assert(h.f.calls.some(call => call.path.endsWith('/reschedule'))); assert.match(h.text(), /内容已变化/); assert(!h.control('新的出发日期')); assert.equal(h.writes().length, 0);
});
test('real reschedule component requires chosen associations, preview, confirmation and recovers lost receipt without duplicate apply', async t => {
  const h = harness('reschedule', { lost: true }); t.after(h.close); await h.settle(); assert.equal(h.control('新的出发日期').props.value, '2026-10-04'); assert.equal(h.control('联动改期：打包行李').props.checked, false); assert.equal(h.writes().length, 0);
  await h.click('联动改期：打包行李'); await h.click('预览改期'); assert.deepEqual(h.writes()[0].body.selectedKeys, ['task:packing']); assert.equal(h.writes()[0].body.snapshotToken, 'PRIVATE-SNAPSHOT'); assert.equal(h.writes()[0].body.start, '2026-10-04');
  await h.click('确认改期'); assert(h.pending); const original = h.writes()[1].body.idempotencyKey; assert(h.control('返回旅行').props.disabled); await h.click('核对保存结果');
  assert.equal(h.writes().filter(call => call.path === '/journeys/apply').length, 1); assert(h.f.calls.some(call => call.path === '/journeys/operations/' + original)); assert.equal(h.pending, false); assert.match(h.text(), /改期已保存/);
});
test('reschedule foreground refresh preserves a users edited date instead of reapplying suggestion', async t => {
  const h = harness('reschedule'); t.after(h.close); await h.settle(); await h.input('新的出发日期', '2026-10-05'); await h.hide(); await h.show(); assert.equal(h.control('新的出发日期').props.value, '2026-10-05'); assert.equal(h.writes().length, 0);
});

for (const name of ['ready', 'needs_input', 'not_found', 'choose_trip', 'selected_ready']) test('decode actual Flask response: ' + name, () => {
  const response = actualResponses[name]; assert.equal(response.status, 200);
  const result = api.readTripChange(response.body, name === 'selected_ready' ? response.body.selected.ref : undefined);
  assert.equal(result.status, name === 'selected_ready' ? 'ready' : name);
});
test('production panel renders actual Flask choices and the selected response without another initial request', async t => {
  const h = harness('change', { plan: body => body.selectedRef ? actualResponses.selected_ready.body : actualResponses.choose_trip.body });
  t.after(h.close); h.props.initialPrompt = '把东京旅行推迟三天'; await h.settle();
  assert.match(h.text(), /东京二旅行/); assert(!h.text().includes(actualResponses.choose_trip.body.selectionToken));
  await h.click('选择旅行 东京旅行 2028-03-02'); assert.match(h.text(), /2028-03-05/);
  assert.deepEqual(h.writes()[1].body, { selectionToken: actualResponses.choose_trip.body.selectionToken, selectedRef: actualResponses.selected_ready.body.selected.ref });
  await h.click('核对改期影响'); const child = h.nodes().find(node => node.type === 'JourneyReschedulePanel');
  assert.equal(child.props.journeyId, actualResponses.selected_ready.body.source.journeyId);
  assert.equal(h.writes().length, 2);
});

// Actual synthetic Flask API 200 responses, source a5432e6e6977ba9f1e7f7edb0b3a9ff0b3593197.
// Source artifact SHA256 89170501c5a3b52257a056a4e826c2b4bade23038c409e64b7d95c8e78f802b5; 0 provider calls.
const actualResponses = {"ready":{"status":200,"body":{"candidates":[{"end":"2028-03-04","journeyId":"6a63de41ec3d46bb4865f6ee","ref":"trip_4a96713925f8afe2cd04825c","revision":1,"sourceIssues":[],"start":"2028-03-02","timeZones":[],"title":"东京旅行","tripId":"4933b069b554a099614e6f1c"}],"change":{"days":3,"kind":"shift_days","monthDay":null,"startDate":null},"draft":{"calendarDays":true,"end":"2028-03-07","journeyId":"6a63de41ec3d46bb4865f6ee","revision":1,"start":"2028-03-05","tripId":"4933b069b554a099614e6f1c"},"intent":"reschedule_existing","issues":[],"missingFields":[],"mode":"local","requiresPreview":true,"selected":{"end":"2028-03-04","journeyId":"6a63de41ec3d46bb4865f6ee","ref":"trip_4a96713925f8afe2cd04825c","revision":1,"sourceIssues":[],"start":"2028-03-02","timeZones":[],"title":"东京旅行","tripId":"4933b069b554a099614e6f1c"},"selectionExpiresIn":null,"selectionToken":null,"source":{"end":"2028-03-04","journeyId":"6a63de41ec3d46bb4865f6ee","revision":1,"sourceVersion":"e3d8ff4652c25edd9a5da1c72e37971223fee3c6137388a2b5f8b64e696889a0","start":"2028-03-02","title":"东京旅行","tripId":"4933b069b554a099614e6f1c","tripRevision":1},"status":"ready","version":1}},"needs_input":{"status":200,"body":{"candidates":[{"end":"2028-03-04","journeyId":"6a63de41ec3d46bb4865f6ee","ref":"trip_4a96713925f8afe2cd04825c","revision":1,"sourceIssues":[],"start":"2028-03-02","timeZones":[],"title":"东京旅行","tripId":"4933b069b554a099614e6f1c"}],"change":{"days":null,"kind":"start_date","monthDay":"10-08","startDate":null},"draft":null,"intent":"reschedule_existing","issues":[],"missingFields":["year"],"mode":"local","requiresPreview":true,"selected":{"end":"2028-03-04","journeyId":"6a63de41ec3d46bb4865f6ee","ref":"trip_4a96713925f8afe2cd04825c","revision":1,"sourceIssues":[],"start":"2028-03-02","timeZones":[],"title":"东京旅行","tripId":"4933b069b554a099614e6f1c"},"selectionExpiresIn":null,"selectionToken":null,"source":{"end":"2028-03-04","journeyId":"6a63de41ec3d46bb4865f6ee","revision":1,"sourceVersion":"e3d8ff4652c25edd9a5da1c72e37971223fee3c6137388a2b5f8b64e696889a0","start":"2028-03-02","title":"东京旅行","tripId":"4933b069b554a099614e6f1c","tripRevision":1},"status":"needs_input","version":1}},"not_found":{"status":200,"body":{"candidates":[],"change":{"days":3,"kind":"shift_days","monthDay":null,"startDate":null},"draft":null,"intent":"reschedule_existing","issues":[],"missingFields":["trip"],"mode":"local","requiresPreview":true,"selected":null,"selectionExpiresIn":null,"selectionToken":null,"source":null,"status":"not_found","version":1}},"choose_trip":{"status":200,"body":{"candidates":[{"end":"2028-03-04","journeyId":"6a63de41ec3d46bb4865f6ee","ref":"trip_4a96713925f8afe2cd04825c","revision":1,"sourceIssues":[],"start":"2028-03-02","timeZones":[],"title":"东京旅行","tripId":"4933b069b554a099614e6f1c"},{"end":"2028-03-04","journeyId":"b22d331fd01e7ab4489281e3","ref":"trip_e7b9b03a2b056af646041e12","revision":1,"sourceIssues":[],"start":"2028-03-02","timeZones":[],"title":"东京二旅行","tripId":"bb3845638e59e0514f34008c"}],"change":{"days":3,"kind":"shift_days","monthDay":null,"startDate":null},"draft":null,"intent":"reschedule_existing","issues":[],"missingFields":["trip"],"mode":"local","requiresPreview":true,"selected":null,"selectionExpiresIn":600,"selectionToken":".eJwVyj1KBDEUAOC7vDpFkveSyaT2Ivl52R3IbJbdGUHE0sJFbG0EESwUPMBi42XGYY8hfvV3C9fglYCQpnYADyOPkQ8KBGzbfORtqxk8ZC5hrhMIGDLvpmG6AQ-9zK5Y40KJkrPWlqjk3mEmVKhUsoS6pN44Q6WTUSO6GLU2TqNJQWkQsD-0cT-Bh_V0Ws4vy_fX-nx_eXtcnz4uP6_L-eH3_RMEpDCF2jYzXw0bPv5_naVFhRgD244o9bKE5JREGWTsi8PQSdJaGcpMSlrVoTKhGKaScokEAsaWuYLfzbXe_QGuj1eo.aq5CTw.okT4uIwWacylmV5tNjCWPwswjbo","source":null,"status":"choose_trip","version":1}},"selected_ready":{"status":200,"body":{"candidates":[{"end":"2028-03-04","journeyId":"6a63de41ec3d46bb4865f6ee","ref":"trip_4a96713925f8afe2cd04825c","revision":1,"sourceIssues":[],"start":"2028-03-02","timeZones":[],"title":"东京旅行","tripId":"4933b069b554a099614e6f1c"},{"end":"2028-03-04","journeyId":"b22d331fd01e7ab4489281e3","ref":"trip_e7b9b03a2b056af646041e12","revision":1,"sourceIssues":[],"start":"2028-03-02","timeZones":[],"title":"东京二旅行","tripId":"bb3845638e59e0514f34008c"}],"change":{"days":3,"kind":"shift_days","monthDay":null,"startDate":null},"draft":{"calendarDays":true,"end":"2028-03-07","journeyId":"6a63de41ec3d46bb4865f6ee","revision":1,"start":"2028-03-05","tripId":"4933b069b554a099614e6f1c"},"intent":"reschedule_existing","issues":[],"missingFields":[],"mode":"local","requiresPreview":true,"selected":{"end":"2028-03-04","journeyId":"6a63de41ec3d46bb4865f6ee","ref":"trip_4a96713925f8afe2cd04825c","revision":1,"sourceIssues":[],"start":"2028-03-02","timeZones":[],"title":"东京旅行","tripId":"4933b069b554a099614e6f1c"},"selectionExpiresIn":null,"selectionToken":null,"source":{"end":"2028-03-04","journeyId":"6a63de41ec3d46bb4865f6ee","revision":1,"sourceVersion":"e3d8ff4652c25edd9a5da1c72e37971223fee3c6137388a2b5f8b64e696889a0","start":"2028-03-02","title":"东京旅行","tripId":"4933b069b554a099614e6f1c","tripRevision":1},"status":"ready","version":1}}};
