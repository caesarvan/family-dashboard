import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { runInNewContext } from 'node:vm';
const require = createRequire(import.meta.url), ts = require('typescript');
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../src');
const copy = value => JSON.parse(JSON.stringify(value));
function loader(mocks = {}, globals = {}) {
  const cache = new Map();
  function load(path) {
    path = resolve(path); if (!existsSync(path)) path += existsSync(path + '.ts') ? '.ts' : '.tsx';
    if (cache.has(path)) return cache.get(path);
    const exports = {}; cache.set(path, exports);
    const code = ts.transpileModule(readFileSync(path, 'utf8'), { fileName: path, compilerOptions: {
      module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
    runInNewContext(code, { exports, require: name => name in mocks ? mocks[name] : load(resolve(dirname(path), name)),
      Date, Intl, Error, URL, URLSearchParams, AbortController, TextEncoder, TextDecoder, process: { env: {} }, ...globals });
    return exports;
  } return load;
}
const load = loader(), list = load(resolve(root, 'lib/assistantList.ts')), { AssistantFlow } = load(resolve(root, 'lib/assistant.ts'));
const { ApiError } = load(resolve(root, 'lib/api.ts')), { memberIdentity, sessionIdentity } = load(resolve(root, 'lib/sessionIdentity.ts'));
const id = 'a'.repeat(32), itemId = 'b'.repeat(24);
const session = () => ({ user: { id: 'alice', name: '本人', role: 'member', householdId: 'home', auth_version: 1 }, csrf: 'synthetic' });
const original = () => ({ id, mode: 'local', summary: '合成清单', matches: [], actions: [
  { kind: 'shopping', data: { title: '转换插头', owner: 'shared', quantity: '1 件', due: '2026-10-01' } },
  { kind: 'tasks', data: { title: '确认酒店', owner: 'alice', due: '' } }] });
function memory() { const rows = new Map(); return { rows, getItem: key => rows.get(key) ?? null, setItem: (key, value) => rows.set(key, value), removeItem: key => rows.delete(key) }; }
function fixture(options = {}) {
  const f = { session: session(), plan: original(), calls: [], writes: [], status: 'pending', receipt: null, fail: '', statusError: 0,
    meError: 0, gate: null, refreshes: 0, storage: memory(), observed: [], ...options };
  async function read(path) {
    f.calls.push(path);
    if (path === '/me') { if (f.meError) { const code = f.meError; f.meError = 0; throw new ApiError('identity transport', code); } return copy(f.session); }
    if (path === '/assistant/brief') return { modelConfigured: false };
    assert.equal(path, '/assistant/plans/' + id);
    if (f.statusError) throw new ApiError('unavailable', f.statusError);
    const value = copy({ id, status: f.status, plan: f.plan, receipt: f.receipt });
    if (f.gate) { const gate = f.gate; f.gate = null; await gate; } return value;
  }
  async function mutate(path, method, body) {
    f.calls.push(path); assert.equal(method, 'POST');
    if (path === '/assistant/plan') return copy(f.plan);
    assert.equal(path, '/assistant/plans/' + id + '/apply'); f.writes.push(copy(body));
    const fail = f.fail; f.fail = '';
    if (fail === 'before' || fail === '409') throw new ApiError('synthetic rejected or lost', fail === '409' ? 409 : 0);
    for (const row of body.overrides || []) f.plan.actions[row.index].data = copy(row.data);
    f.status = 'applied'; f.receipt = { ok: true, destination: 'household', created: body.selected.map(index => ({ id: index ? 'c'.repeat(24) : itemId,
      kind: f.plan.actions[index].kind, title: f.plan.actions[index].data.title })) };
    if (fail === 'after') throw new ApiError('lost after commit');
    if (fail.startsWith('postMe')) f.meError = Number(fail.slice(6));
    if (fail === 'malformed') return {};
    return copy(f.receipt);
  }
  const io = { read, mutate, storage: f.storage, refresh: async () => { f.refreshes++; }, current: () => true };
  const flow = new AssistantFlow(copy(f.session.user), io, state => f.observed.push(copy(state)));
  return { f, flow, io, async plan() { await flow.load(); await flow.plan('采购：转换插头；确认酒店', false, false); } };
}
const draft = () => ({ title: '明确采购', owner: 'alice', due: '2028-02-29', note: '只改本页', quantity: '2 件', budget: '159.90', priority: 'high' });

test('editor validates dates, members and integer cents, distinguishing unset and zero', () => {
  const value = list.editedAction('shopping', draft(), ['alice']); assert.equal(value.budget, 15990);
  assert.equal(list.editedAction('shopping', { ...draft(), budget: '' }, ['alice']).budget, null);
  assert.equal(list.editedAction('shopping', { ...draft(), budget: '0.00' }, ['alice']).budget, 0);
  for (const patch of [{ due: '2027-02-29' }, { due: '2101-01-01' }, { title: '' }, { owner: 'outsider' }, { quantity: '' }, { budget: '-1' }, { budget: '1e3' }, { budget: '1.001' }])
    assert.throws(() => list.editedAction('shopping', { ...draft(), ...patch }, ['alice']));
  assert.deepEqual(Object.keys(list.editedAction('tasks', draft(), ['alice'])).sort(), ['due', 'note', 'owner', 'title']);
});
test('single confirmation snapshots selected edits, ignores unselected edits and model hidden fields', async () => {
  const h = fixture(); h.f.plan.actions[0].data.budget = 99999; h.f.plan.actions[0].data.actual = 123;
  await h.plan(); assert.equal(h.flow.state.plan.actions[0].data.budget, undefined);
  const data = list.editedAction('shopping', draft(), ['alice']); h.flow.edit(0, data); h.flow.edit(1, { title: '不选', owner: 'shared' }); h.flow.select(1);
  assert.equal(h.f.writes.length, 0); await h.flow.apply();
  assert.deepEqual(h.f.writes, [{ selected: [0], overrides: [{ index: 0, data: copy(data) }] }]);
  assert.equal(h.flow.state.receipt.created[0].title, '明确采购'); await h.flow.apply(); assert.equal(h.f.writes.length, 1);
});
for (const mode of ['after', 'malformed', 'postMe404', 'postMe410', 'postMe503']) test('committed ' + mode + ' recovers via GET and never repeats apply', async () => {
  const h = fixture(); await h.plan(); h.flow.edit(0, list.editedAction('shopping', draft(), ['alice'])); h.f.fail = mode;
  await h.flow.apply(); assert(h.flow.state.pending); assert.equal(h.flow.state.receipt, null);
  if (mode.startsWith('postMe')) assert.equal(h.flow.state.visible, false);
  await h.flow.checkOutcome(); assert.equal(h.flow.state.receipt.created[0].title, '明确采购'); assert.equal(h.flow.state.pending, null);
  await h.flow.apply(); assert.equal(h.f.writes.length, 1); assert(h.f.calls.includes('/assistant/plans/' + id));
});
for (const mode of ['before', '409']) test(mode + ' preserves draft; GET pending permits explicit same snapshot retry only', async () => {
  const h = fixture(); await h.plan(); h.flow.edit(0, list.editedAction('shopping', draft(), ['alice'])); h.f.fail = mode; await h.flow.apply();
  const frozen = copy(h.flow.state.pending); h.flow.edit(0, { title: 'must not edit', owner: 'shared' }); await h.flow.apply(); assert.equal(h.f.writes.length, 1);
  await h.flow.checkOutcome(); assert.equal(h.flow.state.checkedAfterUnknown, true); assert.equal(h.flow.state.receipt, null);
  assert.match(h.flow.state.notice, /不代表旧请求从未到达/); assert.deepEqual(copy(h.flow.state.pending), frozen);
  await h.flow.apply(); assert.deepEqual(h.f.writes[0], h.f.writes[1]);
});
test('reload restores applied receipt with no title, money, prompt or csrf in sessionStorage', async () => {
  const h = fixture(); await h.plan(); h.flow.edit(0, list.editedAction('shopping', draft(), ['alice'])); h.f.fail = 'after'; await h.flow.apply();
  const stored = JSON.parse(h.f.storage.getItem(list.assistantPlanStorageKey));
  assert.deepEqual(stored, { memberIdentity: memberIdentity(h.f.session.user), planId: id });
  const reload = new AssistantFlow(copy(h.f.session.user), h.io, () => {}); await reload.load();
  assert.equal(reload.state.receipt.created[0].title, '明确采购'); assert.equal(reload.state.plan.actions[0].data.budget, 15990); assert.equal(h.f.writes.length, 1);
});
test('reload pending states lost edits explicitly and cannot confirm before review', async () => {
  const h = fixture(); await h.plan(); h.flow.edit(0, list.editedAction('shopping', draft(), ['alice']));
  const reload = new AssistantFlow(copy(h.f.session.user), h.io, () => {}); await reload.load(); assert(reload.state.needsReview);
  assert.match(reload.state.notice, /原修改未恢复/); await reload.apply(); assert.equal(h.f.writes.length, 0);
  reload.reviewDraft(); await reload.apply(); assert.deepEqual(h.f.writes[0].overrides, []);
});
for (const status of [404, 'expired']) test('unreadable or expired ' + status + ' never substitutes another plan', async () => {
  const h = fixture(); await h.plan(); h.f.fail = 'before'; await h.flow.apply();
  if (status === 404) h.f.statusError = 404; else h.f.status = status;
  await h.flow.checkOutcome(); assert(h.flow.state.unavailable); await h.flow.plan('replace', false, false); await h.flow.apply();
  assert.equal(h.f.calls.filter(p => p === '/assistant/plan').length, 1); assert.equal(h.f.writes.length, 1);
  h.flow.startAfterReview(); assert.equal(h.f.storage.getItem(list.assistantPlanStorageKey), null); assert.equal(h.flow.state.plan, null);
  assert.equal(h.f.calls.filter(p => p === '/assistant/plan').length, 1); // Explicit exit is local, not an automatic new request.
  await h.flow.plan('新需求', false, false); assert.equal(h.f.calls.filter(p => p === '/assistant/plan').length, 2);
});
test('same-identity hidden state retains draft but late result is not installed before fresh GET', async () => {
  const h = fixture(); await h.plan(); h.flow.edit(0, list.editedAction('shopping', draft(), ['alice']));
  let release; h.f.gate = new Promise(resolve => { release = resolve; }); const reading = h.flow.checkOutcome();
  await new Promise(resolve => setImmediate(resolve)); h.flow.setForeground(false); release(); await reading;
  assert.equal(h.flow.state.visible, false); assert.equal(h.flow.state.edits[0].budget, 15990);
  h.flow.setForeground(true); await new Promise(resolve => setImmediate(resolve)); assert.equal(h.flow.state.visible, true);
  assert.equal(h.flow.state.edits[0].budget, 15990);
});
test('late original plan after member switch clears private state and recovery identifier', async () => {
  const h = fixture(); await h.plan(); let release; h.f.gate = new Promise(resolve => { release = resolve; });
  const reading = h.flow.checkOutcome(); await new Promise(resolve => setImmediate(resolve));
  h.f.session = { user: { ...h.f.session.user, id: 'bob' }, csrf: 'other' }; release(); await reading;
  assert(h.flow.state.expired); assert.equal(h.flow.state.plan, null); assert.equal(h.f.storage.getItem(list.assistantPlanStorageKey), null);
});
test('storage from another member or with content fields is discarded', () => {
  const s = memory(), key = memberIdentity(session().user);
  for (const value of [{ memberIdentity: 'other', planId: id }, { memberIdentity: key, planId: id, prompt: 'private' }, { memberIdentity: key, planId: '../bad' }]) {
    s.setItem(list.assistantPlanStorageKey, JSON.stringify(value)); assert.equal(list.recoverPlan(s, key), null); assert.equal(s.rows.size, 0);
  }
});
test('closed or hidden late /me401 cannot remove another identity recovery marker', async () => {
  for (const hide of [false, true]) {
    const h = fixture(); await h.plan(); let reject;
    h.io.read = path => path === '/me' ? new Promise((_, fail) => { reject = fail; }) : Promise.reject(new Error('unexpected'));
    const reading = h.flow.checkOutcome(); await new Promise(resolve => setImmediate(resolve));
    if (hide) h.flow.setForeground(false); else h.flow.close();
    const other = memberIdentity({ ...h.f.session.user, id: 'bob' }); list.retainPlan(h.f.storage, other, 'd'.repeat(32));
    reject(new ApiError('late unauthorized', 401)); await reading;
    assert.equal(list.recoverPlan(h.f.storage, other), 'd'.repeat(32));
  }
});

// Runs the actual TSX handlers; only React host and network transport are synthetic.
function screenHarness(home = false) {
  let holder, cursor = 0, dirty = true, tree;
  const slots = new Map(), effects = [], listeners = new Map();
  const changed = (a, b) => !a || !b || a.length !== b.length || a.some((v, i) => v !== b[i]);
  const react = { Fragment: 'Fragment', createElement: (type, props, ...children) => ({ type, props: { ...props, children: children.flat(Infinity).filter(x => x !== null && x !== undefined && x !== false) } }),
    useState(initial) { const h = holder, i = cursor++; if (!(i in h)) h[i] = typeof initial === 'function' ? initial() : initial; return [h[i], value => { h[i] = typeof value === 'function' ? value(h[i]) : value; dirty = true; }]; },
    useRef(initial) { const i = cursor++; return holder[i] ||= { current: initial }; },
    useEffect(fn, deps) { const h = holder, i = cursor++; if (changed(h[i]?.deps, deps)) { const old = h[i]; h[i] = { deps }; effects.push(() => { old?.cleanup?.(); h[i].cleanup = fn(); }); } },
    useCallback(fn, deps) { const i = cursor++; if (changed(holder[i]?.deps, deps)) holder[i] = { deps, fn }; return holder[i].fn; } };
  const f = fixture(); const sessionValue = f.f.session;
  const events = { addEventListener: (name, fn) => { if (!listeners.has(name)) listeners.set(name, new Set()); listeners.get(name).add(fn); }, removeEventListener: (name, fn) => listeners.get(name)?.delete(fn) };
  const document = { hidden: false, ...events }, navigator = { onLine: true }, window = { sessionStorage: f.f.storage, ...events };
  const household = { user: sessionValue.user, identityKey: sessionIdentity(sessionValue), online: true, mutate: f.io.mutate, refresh: f.io.refresh };
  const theme = { colors: { onSurfaceVariant: '#555', surfaceVariant: '#eee', error: '#900' } };
  const mocks = { react, 'expo-router': { useFocusEffect: fn => react.useEffect(fn, [fn]) },
    'react-native': { AppState: { addEventListener: () => ({ remove() {} }) }, Platform: { OS: 'web' }, StyleSheet: { create: x => x }, View: 'View', useWindowDimensions: () => ({ width: 390 }) },
    'react-native-paper': { Button: 'Button', Chip: 'Chip', Divider: 'Divider', HelperText: 'HelperText', Text: 'Text', TextInput: 'TextInput', IconButton: 'IconButton', useTheme: () => theme },
    '../lib/api': { request: f.io.read }, '../lib/household': { useHousehold: () => household }, '../ui/components': { PageHeader: 'PageHeader', SectionCard: 'SectionCard', EmptyState: 'EmptyState' },
    '../ui/SelectionRow': { SelectionRow: 'SelectionRow' }, '../ui/theme': { useDisplayDensity: () => ({}) }, './CalendarScreen': { EventRow: 'EventRow', RangeControls: 'RangeControls', WorkloadStrip: 'WorkloadStrip' },
  };
  for (const name of ['./JourneyBriefPanel', './TripsScreen', './JourneyDocumentsPanel', './PhotosScreen', './MapWorkspace', '../components/ExistingTripChangePanel', '../components/AssistantFinanceQueryPanel', './HomeLayoutPanel', '../ui/TaskRemindersPanel']) mocks[name] = { __esModule: true, default: 'Unused' };
  const actual = loader(mocks, { document, navigator, window, setTimeout: () => 1, clearTimeout() {} });
  const Component = actual(resolve(root, home ? 'screens/HomeScreen.tsx' : 'screens/AssistantScreen.tsx'))[home ? 'default' : 'AssistantScreen'];
  const edits = [], props = { user: sessionValue.user, state: { people: [{ id: 'alice', name: '本人' }, { id: 'bob', name: '伙伴' }], events: [], tasks: [], shopping: [], trips: [], finance: {} }, layout: { order: ['shopping'], hidden: [] }, focus: 'alice', mode: 'today', onEdit: (...args) => edits.push(args), onNavigate() {} };
  function render(node, path = 'root') {
    if (!node || typeof node !== 'object') return node;
    if (typeof node.type === 'function') { holder = slots.get(path) || {}; slots.set(path, holder); cursor = 0; return render(node.type(node.props), path + '/render'); }
    return { ...node, props: { ...node.props, children: (node.props.children || []).map((n, i) => render(n, path + '/' + (n?.props?.key ?? i))) } };
  }
  async function flush() { for (let turn = 0; turn < 2; turn++) { for (let n = 0; n < 24; n++) {
    if (dirty) { dirty = false; tree = render({ type: Component, props }); } while (effects.length) effects.shift()(); await Promise.resolve();
  } await new Promise(resolve => setImmediate(resolve)); } }
  const nodes = () => { const out = []; function walk(n) { if (!n || typeof n !== 'object') return; out.push(n); n.props.children?.forEach(walk); } walk(tree); return out; };
  const find = id => { const n = nodes().filter(n => n.props.testID === id || n.props.accessibilityLabel === id); assert.equal(n.length, 1, id); return n[0]; };
  const text = (node = tree) => !node || typeof node === 'boolean' ? '' : typeof node !== 'object' ? String(node) : (node.props.children || []).map(text).join(' ');
  return { f: f.f, props, household, edits, flush, nodes, text, find,
    async fill(id, value) { find(id).props.onChangeText(value); await flush(); },
    async click(id) { const n = find(id); assert(!n.props.disabled, id + ' disabled'); n.props.onPress(); await flush(); },
    async pressText(label) { const n = nodes().find(n => n.type === 'Button' && text(n) === label); assert(n && !n.props.disabled, label); n.props.onPress(); await flush(); },
    async offline() { navigator.onLine = false; household.online = false; listeners.get('offline')?.forEach(fn => fn()); dirty = true; await flush(); },
    async online() { navigator.onLine = true; household.online = true; listeners.get('online')?.forEach(fn => fn()); dirty = true; await flush(); } };
}
test('actual screen edits compact card, retains unsaved editor across offline and applies once', async () => {
  const h = screenHarness(); await h.flush(); await h.fill('告诉助理你的需求', '采购：转换插头'); await h.pressText('整理并预览');
  await h.click('action-edit-0'); await h.fill('action-title', '明确清单名称'); await h.fill('action-budget', '0'); await h.fill('action-due', '2028-02-29');
  await h.offline(); assert(!h.text().includes('明确清单名称')); assert.equal(h.nodes().filter(n => n.props.testID === 'assistant-action-editor').length, 0);
  await h.online(); assert.equal(h.find('action-title').props.value, '明确清单名称'); await h.click('action-edit-save');
  assert(h.text().includes('预算 ¥0.00')); await h.click('选择确认酒店'); await h.click('assistant-list-apply'); assert.equal(h.f.writes.length, 1); assert.equal(h.f.writes[0].overrides[0].data.budget, 0);
  assert(h.find('assistant-list-receipt')); assert.equal(h.f.writes[0].overrides[0].data.title, '明确清单名称');
  assert(!h.text().includes('确认酒店')); assert.equal(h.nodes().filter(n => n.props.testID?.startsWith('assistant-list-action-')).length, 0);
});
test('actual home orders dated priority purchases and edits the original item', async () => {
  const h = screenHarness(true);
  h.props.state.shopping = [{ id: 'undated', title: '无日期', owner: 'shared', done: false }, { id: 'low', title: '同日低', owner: 'alice', due: '2026-10-01', priority: 'low', done: false },
    { id: 'high', title: '同日高', owner: 'bob', due: '2026-10-01', priority: 'high', done: false }]; await h.flush();
  assert.deepEqual(h.nodes().filter(n => n.props.testID?.startsWith('home-shopping-')).map(n => n.props.testID), ['home-shopping-high', 'home-shopping-low', 'home-shopping-undated']);
  const row = h.find('home-shopping-high'); assert.match(h.text(row), /伙伴/); assert.match(h.text(row), /2026-10-01/); assert.match(h.text(row), /高优先级/);
  const button = row.props.children.find(n => n?.type === 'Button'); button.props.onPress(); assert.equal(h.edits[0][1], h.props.state.shopping[2]);
});
test('actual screen hides existing search text on foreground identity-read failure', async () => {
  const h = screenHarness(); h.f.plan = { id: null, mode: 'local', summary: '查询完成', actions: [],
    matches: [{ id: itemId, kind: 'tasks', title: '私人搜索标题' }], search: { query: 'needle', offset: 0, limit: 20, total: 1, nextOffset: null } };
  await h.flush(); await h.fill('告诉助理你的需求', '搜索：needle'); await h.pressText('整理并预览');
  assert(h.text().includes('私人搜索标题')); h.f.meError = 503; await h.pressText('整理并预览');
  assert(!h.text().includes('私人搜索标题')); assert(h.nodes().some(node => node.type === 'SectionCard' && node.props.title === '助理内容已隐藏')); assert(h.text().includes('核对身份并继续'));
});
