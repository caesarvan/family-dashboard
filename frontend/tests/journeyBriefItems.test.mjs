import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { runInNewContext } from 'node:vm';
const require = createRequire(import.meta.url), ts = require('typescript'), root = resolve(dirname(fileURLToPath(import.meta.url)), '../src');
const clone = value => JSON.parse(JSON.stringify(value));
function loader(mocks = {}, globals = {}) {
  const cache = new Map();
  function load(path) {
    path = resolve(path); if (!existsSync(path)) path += existsSync(path + '.ts') ? '.ts' : '.tsx';
    if (cache.has(path)) return cache.get(path);
    const exports = {}; cache.set(path, exports);
    const code = ts.transpileModule(readFileSync(path, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
    runInNewContext(code, { exports, require: name => name in mocks ? mocks[name] : load(resolve(dirname(path), name)), Date, Intl, Error, ...globals }); return exports;
  }
  return load;
}
const source = '合成原文：2027-10-01 出发，核对护照并买插头。';
const wire = () => ({ mode: 'model', notice: '请核对草案', warnings: ['采购截止要求只保留备注。'], brief: { title: '合成旅行', start: '2027-10-01', end: '2027-10-07', budgetCents: 2000000, international: true,
  destinations: [{ country: '冰岛', city: '雷克雅未克', arrival: '2027-10-01', departure: '2027-10-07' }],
  checklist: [{ key: 'brief-task-1', title: '核对护照', assigneeText: '我', owner: 'alice', note: '', sourceText: '核对护照', due: '', dueOffsetDays: -3 }],
  shopping: [{ key: 'brief-purchase-1', title: '转换插头', assigneeText: '同行', owner: 'bob', note: '截止：出发前3天', sourceText: '买插头', quantity: '两只', budgetCents: null }] } });

// Executes the actual panel, item editor and identity fence with synthetic HTTP
// values. It does not claim backend, browser layout, provider or cloud validation.
function harness(options = {}) {
  const f = { session: { user: { id: 'alice', name: '合成本人', role: 'member', householdId: 'home', auth_version: 1 }, csrf: 'synthetic' },
    people: [{ id: 'alice', name: '合成本人' }, { id: 'bob', name: '合成同行' }], wire: wire(), calls: [], prepared: [], gate: null, failure: null, ...options };
  let instance, cursor = 0, dirty = true, tree, renderNumber = 0;
  const instances = new Map(), effects = [], listeners = new Map();
  const eventTarget = { addEventListener(name, fn) { if (!listeners.has(name)) listeners.set(name, new Set()); listeners.get(name).add(fn); }, removeEventListener(name, fn) { listeners.get(name)?.delete(fn); } };
  const document = { hidden: false, ...eventTarget }, navigator = { onLine: true }, window = { ...eventTarget };
  const changed = (a, b) => !a || !b || a.length !== b.length || a.some((v, i) => v !== b[i]);
  function useState(value) { const holder = instance, i = cursor++; if (!(i in holder.values)) holder.values[i] = typeof value === 'function' ? value() : value; return [holder.values[i], next => { holder.values[i] = typeof next === 'function' ? next(holder.values[i]) : next; dirty = true; }]; }
  function useRef(value) { const i = cursor++; if (!(i in instance.values)) instance.values[i] = { current: value }; return instance.values[i]; }
  function useEffect(fn, deps) { const holder = instance, i = cursor++; if (changed(holder.values[i], deps)) { holder.values[i] = deps; effects.push(() => { holder.cleanups[i]?.(); holder.cleanups[i] = fn(); }); } }
  function useCallback(fn, deps) { const i = cursor++; if (!instance.values[i] || changed(instance.values[i].deps, deps)) instance.values[i] = { deps, fn }; return instance.values[i].fn; }
  const react = { useState, useRef, useEffect, useCallback, Fragment: 'Fragment', createElement(type, props, ...children) { return { type, props: { ...props, children: children.flat(Infinity).filter(v => v !== false && v !== null && v !== undefined) } }; } };
  class ApiError extends Error { constructor(message, status) { super(message); this.status = status; } }
  const identity = loader()(resolve(root, 'lib/sessionIdentity.ts'));
  const household = { user: f.session.user, identityKey: identity.sessionIdentity(f.session), online: true, refresh: async () => { f.refreshes = (f.refreshes || 0) + 1; } };
  const request = async path => { f.calls.push({ path, method: 'GET' }); assert.equal(path, '/me'); return clone(f.session); };
  household.mutate = async (path, method, body) => {
    f.calls.push({ path, method, body: clone(body) });
    if (path === '/assistant/journey-brief') { if (f.gate) await f.gate; if (f.failure) throw f.failure; return clone(f.wire); }
    assert.equal(path, '/journeys/preview');
    if (f.previewGate) await f.previewGate;
    const plan = clone(body.plan);
    // Fixed synthetic server response for the original fixture; deadline edits
    // are independently asserted on outbound payloads, not inferred from this.
    plan.checklist = (plan.checklist || []).map(row => ({ ...row, due: row.due || '2027-09-28', dueOffsetDays: row.dueOffsetDays ?? -3, category: 'preparation' }));
    plan.segments = [{ key: 'stay', title: '停留', start: plan.start, end: plan.end, location: '冰岛', note: '' }];
    return { canApply: true, previewToken: 'not-an-apply-grant', plan };
  };
  const mocks = { react, 'react-native': { View: 'View', StyleSheet: { create: x => x }, AppState: { currentState: 'active', addEventListener: () => ({ remove() {} }) } },
    'react-native-paper': Object.fromEntries(['Button', 'Divider', 'HelperText', 'Text', 'TextInput', 'ActivityIndicator'].map(n => [n, n])),
    'expo-router': { useFocusEffect: fn => useEffect(fn, [fn]) }, '../lib/api': { ApiError, request }, '../lib/household': { useHousehold: () => household },
    '../ui/components': { PageHeader: 'PageHeader', SectionCard: 'SectionCard' }, '../ui/SelectionRow': { SelectionRow: 'SelectionRow' } };
  mocks['react-native-paper'].useTheme = () => ({ colors: { onSurfaceVariant: '#555' } });
  const Panel = loader(mocks, { document, window, navigator })(resolve(root, 'screens/JourneyBriefPanel.tsx')).default;
  const props = { user: f.session.user, people: f.people, initialPrompt: source, initialUseModel: true, prepareOnOpen: true, onPrepared: d => f.prepared.push(clone(d)), onCancel: () => { f.cancelled = true; } };
  function expand(node, path = '0') {
    if (node === null || node === false || node === undefined) return null;
    if (typeof node !== 'object') return node;
    if (Array.isArray(node)) return node.map((n, i) => expand(n, path + '.' + i));
    if (typeof node.type === 'function') {
      const key = path + ':' + node.type.name;
      if (!instances.has(key)) instances.set(key, { values: [], cleanups: [] });
      const previous = instance, oldCursor = cursor; instance = instances.get(key); instance.seen = renderNumber; cursor = 0;
      const result = node.type(node.props); instance = previous; cursor = oldCursor; return expand(result, key);
    }
    return { ...node, props: { ...node.props, action: node.props.action ? expand(node.props.action, path + '.action') : undefined,
      children: (node.props.children || []).map((child, i) => expand(child, path + '.' + (child?.props?.key || i))) } };
  }
  function render() { dirty = false; renderNumber++; tree = expand(react.createElement(Panel, props)); for (const [key, row] of instances) if (row.seen !== renderNumber) { row.cleanups.forEach(fn => fn?.()); instances.delete(key); } while (effects.length) effects.shift()(); }
  async function flush() { for (let i = 0; i < 15; i++) { if (dirty) render(); await new Promise(setImmediate); } if (dirty) render(); }
  function nodes(value) { if (!value || typeof value !== 'object') return []; if (Array.isArray(value)) return value.flatMap(nodes); return [value, ...nodes(value.props.action), ...nodes(value.props.children)]; }
  function content(value) { if (typeof value === 'string' || typeof value === 'number') return String(value); if (!value) return ''; if (Array.isArray(value)) return value.map(content).join(' '); return content(value.props.children); }
  const find = label => { const matches = nodes(tree).filter(n => (n.props.accessibilityLabel || content(n.props.children)) === label && (n.props.onPress || n.props.onChangeText)); assert.equal(matches.length, 1, label); return matches[0]; };
  return { f, flush, text: () => content(tree), byId: id => nodes(tree).find(n => n.props.testID === id), value: label => find(label).props.value,
    async click(label) { const n = find(label); assert(!n.props.disabled, label + ' disabled'); n.props.onPress(); await flush(); },
    async input(label, value) { const n = find(label); assert(!n.props.disabled, label + ' disabled'); n.props.onChangeText(value); await flush(); },
    async hide(hidden) { document.hidden = hidden; for (const fn of listeners.get('visibilitychange') || []) fn(); await flush(); },
    async offline(value) { navigator.onLine = !value; for (const fn of listeners.get(value ? 'offline' : 'online') || []) fn(); await flush(); },
    async replaceMember() { f.session = { ...f.session, user: { ...f.session.user, id: 'bob' } }; household.user = f.session.user; household.identityKey = identity.sessionIdentity(f.session); props.user = f.session.user; dirty = true; await flush(); },
    async renamePerson() { f.people = f.people.map(p => p.id === 'bob' ? { ...p, name: '新名称' } : p); props.people = f.people; dirty = true; await flush(); } };
}

test('nonempty item cards open, null budget remains empty, preview hands editable items onward without saving', async () => {
  const h = harness(); await h.flush();
  assert(h.byId('journey-brief-task-1')); assert(h.byId('journey-brief-purchase-1'));
  assert.equal(h.value('采购预算（元）1'), ''); assert(h.text().includes('采购截止要求只保留备注'));
  await h.click('出行成员：合成本人（我）'); await h.input('采购预算（元）1', '0'); await h.click('核对并继续编辑');
  const payload = h.f.calls.find(c => c.path === '/journeys/preview').body.plan;
  assert.equal(payload.shopping[0].budget, 0); assert.equal(payload.checklist[0].dueOffsetDays, -3);
  assert.equal(payload.shopping[0].note, '截止：出发前3天'); assert.equal(payload.shopping[0].due, undefined);
  assert.equal(h.f.prepared.length, 1); assert.equal(h.f.prepared[0].plan.shopping[0].budget, 0);
  assert.equal(h.f.prepared[0].previewToken, undefined); assert(!h.f.calls.some(c => /apply/.test(c.path)));
});

test('unresolved names and dates require explicit correction, same-name other member can be chosen', async () => {
  const data = wire(); data.brief.checklist[0] = { ...data.brief.checklist[0], owner: null, assigneeText: '合成同名', dueOffsetDays: null };
  const h = harness({ wire: data, people: [{ id: 'alice', name: '合成同名' }, { id: 'bob', name: '合成同名' }] }); await h.flush();
  await h.click('出行成员：合成同名（我）'); await h.click('核对并继续编辑'); assert(!h.f.calls.some(c => c.path === '/journeys/preview'));
  await h.click('准备负责人 1'); await h.click('合成同名（另一位成员）'); await h.input('准备截止日期 1', '2027-09-28'); await h.click('核对并继续编辑');
  assert.equal(h.f.calls.find(c => c.path === '/journeys/preview').body.plan.checklist[0].owner, 'bob');
});

test('date editing updates relative deadline and add/remove never resurrects deleted tasks', async () => {
  const h = harness(); await h.flush(); await h.input('出发日期', '2027-10-02'); await h.input('抵达日期 1', '2027-10-02'); await h.input('距出发天数 1', '-2');
  assert(h.text().includes('截止：2027-09-30'));
  await h.click('移除准备事项 1'); assert(!h.byId('journey-brief-task-1')); await h.click('添加准备事项');
  await h.input('准备事项标题 1', '新的准备'); await h.click('准备负责人 1'); await h.click('一起'); await h.click('随出发日期调整 1'); await h.input('距出发天数 1', '-2');
  assert(h.text().includes('截止：2027-09-30')); await h.click('移除采购 1'); await h.click('添加采购');
  assert.equal(h.value('采购预算（元）1'), ''); assert.equal(h.value('采购数量 1'), '');
});

test('remove a middle row then add another keeps unique stable keys in the preview request', async () => {
  const h = harness(); await h.flush(); await h.click('添加准备事项'); await h.click('添加准备事项');
  await h.click('移除准备事项 2'); await h.click('添加准备事项');
  for (const i of [2, 3]) {
    await h.input(`准备事项标题 ${i}`, '新增准备' + i); await h.click(`准备负责人 ${i}`); await h.click('一起');
    await h.click(`随出发日期调整 ${i}`); await h.input(`距出发天数 ${i}`, '-3');
  }
  await h.click('出行成员：合成本人（我）'); await h.click('核对并继续编辑');
  const keys = h.f.calls.find(c => c.path === '/journeys/preview').body.plan.checklist.map(row => row.key);
  assert.deepEqual(keys, ['brief-task-1', 'manual-task-2', 'manual-task-3']); assert.equal(h.f.prepared.length, 1);
});

test('late extract success and failure cannot overwrite item edits or retry automatically', async () => {
  for (const fails of [false, true]) {
    const h = harness(); await h.flush(); let release; h.f.gate = new Promise(resolve => { release = resolve; }); if (fails) h.f.failure = new Error('STALE PRIVATE ERROR');
    await h.click('按当前文字重新整理'); await h.input('准备事项标题 1', '我刚修改的准备'); release(); await h.flush();
    assert.equal(h.value('准备事项标题 1'), '我刚修改的准备'); assert(!h.text().includes('STALE PRIVATE ERROR'));
    assert.equal(h.f.calls.filter(c => c.path === '/assistant/journey-brief').length, 2);
  }
});

test('background and offline hide all items; return only rechecks identity and keeps same draft', async () => {
  const h = harness(); await h.flush(); await h.input('采购名称 1', '保留私人草稿');
  await h.hide(true); assert(!h.byId('journey-brief-form')); assert(!h.text().includes('保留私人草稿'));
  await h.hide(false); assert.equal(h.value('采购名称 1'), '保留私人草稿');
  await h.offline(true); assert(!h.byId('journey-brief-form')); await h.offline(false); assert.equal(h.value('采购名称 1'), '保留私人草稿');
  assert.equal(h.f.calls.filter(c => c.path === '/assistant/journey-brief').length, 1);
});

test('member replacement drops in-flight brief and a changed name drops pending preview handoff', async () => {
  let release; const gate = new Promise(resolve => { release = resolve; }); const h = harness({ gate }); await h.flush(); await h.replaceMember(); release(); await h.flush();
  assert(!h.byId('journey-brief-form')); assert(!h.text().includes('核对护照')); assert.equal(h.f.prepared.length, 0);
  const second = harness(); await second.flush(); await second.click('出行成员：合成本人（我）'); let resume; second.f.previewGate = new Promise(resolve => { resume = resolve; });
  await second.click('核对并继续编辑'); await second.renamePerson(); resume(); await second.flush();
  assert.equal(second.f.prepared.length, 0); assert(second.text().includes('家庭成员列表已变化'));
});
