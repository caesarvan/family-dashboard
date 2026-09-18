import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { webcrypto } from 'node:crypto';
import * as model from '../src/lib/inventory.ts';

const require = createRequire(new URL('../package.json', import.meta.url));
const ts = require('typescript');
const source = readFileSync(new URL('../src/screens/InventoryScreen.tsx', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022 } }).outputText;
const itemId = 'a'.repeat(24), acquisitionId = 'b'.repeat(24), taskId = 'c'.repeat(24);
const clone = value => structuredClone(value);
const page = (items, limit) => ({ items, total: items.length, offset: 0, limit, nextOffset: null });
const task = () => ({ id: taskId, revision: 1, title: '跟进售后', owner: 'shared', due: '', done: false, note: '' });
const association = (state = 'none') => ({ itemId, acquisitionId, state, task: state === 'linked' ? task() : null });
class ApiError extends Error { constructor(status, text = 'synthetic transport failure') { super(text); this.status = status; } }

// Execute the production TSX and its real InventoryFence/validators. Hooks,
// Paper/native elements, lifecycle and HTTP below are explicit recording doubles;
// this is not a browser, React reconciler or real Flask/SQLite acceptance test.
function harness() {
  const f = {
    session: { user: { id: 'member1', name: '甲', role: 'member', householdId: 'house-one', auth_version: 1 }, csrf: 'synthetic-csrf' },
    item: { id: itemId, owner: 'member1', title: 'PRIVATE ITEM', unit: '件', variant: '', location: '', visibility: 'private', reorderPoint: null, belowThreshold: false, revision: 1, onHandQty: 0, inTransitQty: 0, plannedQty: 1, canRead: true, canMutate: true, canManage: true },
    batch: { id: acquisitionId, itemId, kind: 'purchase', shoppingId: null, orderedQty: 1, orderState: 'ordered', orderedOn: null, expectedOn: null, warrantyUntil: null, afterSalesState: 'open', note: 'PRIVATE ORDER AND AMOUNT', revision: 1, itemRevision: 1, canMutate: true, canEditAllFields: true, editableFields: ['afterSalesState', 'note'], onHandQty: 0, receivedQty: 0, returnedQty: 0, remainingExpectedQty: 1 },
    link: association(), calls: [], receipt: null, getFailure: 0, postFailure: '', denied: false, gate: null,
  };
  const slots = [], effects = [], cleanups = [], lifecycle = new Map();
  let cursor = 0, dirty = true, tree, closed = false, navigation = null;
  const document = { hidden: false, addEventListener: (name, fn) => lifecycle.set(name, fn), removeEventListener: name => lifecycle.delete(name) };
  const useState = initial => { const i = cursor++; if (!(i in slots)) slots[i] = initial; return [slots[i], value => { slots[i] = typeof value === 'function' ? value(slots[i]) : value; dirty = true; }]; };
  const useRef = initial => { const i = cursor++; if (!(i in slots)) slots[i] = { current: initial }; return slots[i]; };
  const changed = (previous, next) => !previous || !next || previous.length !== next.length || previous.some((v, i) => v !== next[i]);
  const useEffect = (fn, deps) => { const i = cursor++; if (changed(slots[i], deps)) { slots[i] = deps; effects.push(() => { cleanups[i]?.(); cleanups[i] = fn(); }); } };
  const useCallback = (fn, deps) => { const i = cursor++; if (!slots[i] || changed(slots[i].deps, deps)) slots[i] = { deps, fn }; return slots[i].fn; };
  const react = { useState, useRef, useEffect, useLayoutEffect: useEffect, useCallback, Fragment: 'Fragment', createElement: (type, props, ...children) => ({ type, props: { ...props, children: children.flat(Infinity).filter(v => v !== undefined) } }) };
  const household = { online: true, identityKey: model.inventorySignature(f.session), refresh: async () => {} };
  async function request(path, options = {}, csrf) {
    f.calls.push({ path, method: options.method || 'GET', body: options.body ? JSON.parse(options.body) : null, csrf });
    if (path === '/me') return clone(f.session);
    if (f.denied) throw new ApiError(404);
    if (path.endsWith('/followup') && !options.method) {
      if (f.gate) await f.gate;
      if (f.getFailure > 0) { f.getFailure--; throw new ApiError(503); }
      return clone(f.link);
    }
    if (path.endsWith('/followup') && options.method === 'POST') {
      const body = JSON.parse(options.body);
      if (f.postFailure === 'conflict') throw new ApiError(409);
      f.item.revision++; f.batch.revision++; f.batch.itemRevision++;
      f.link = { ...association('linked'), task: { ...task(), ...body.data } };
      f.receipt = { operation: { itemId, acquisitionId, itemRevision: f.item.revision, acquisitionRevision: f.batch.revision, entityId: taskId, replayed: false }, item: clone(f.item), acquisition: clone(f.batch) };
      if (f.postFailure === 'lost') throw new Error('response dropped after simulated commit');
      const result = clone(f.receipt);
      if (f.postFailure === 'malformed') delete result.operation.entityId;
      return result;
    }
    if (path.startsWith('/inventory/operations/')) { if (!f.receipt) throw new ApiError(404); return { ...clone(f.receipt), operation: { ...f.receipt.operation, replayed: true } }; }
    if (path === `/inventory/acquisitions/${acquisitionId}`) return { item: clone(f.item), acquisition: clone(f.batch) };
    if (path.startsWith(`/inventory/items/${itemId}/acquisitions?`)) return page([clone(f.batch)], 12);
    if (path === `/inventory/items/${itemId}`) return { item: clone(f.item) };
    if (path.startsWith('/inventory/items?')) return page([clone(f.item)], 24);
    throw new Error('Unexpected request ' + path);
  }
  const modules = {
    react,
    'react-native': { AppState: { addEventListener: (_name, fn) => { lifecycle.set('app', fn); return { remove() {} }; } }, Platform: { OS: 'web' }, StyleSheet: { create: v => v }, View: 'View' },
    'expo-router': { useFocusEffect: fn => useEffect(fn, [fn]) },
    'react-native-paper': { ...Object.fromEntries(['ActivityIndicator', 'Button', 'Divider', 'Icon', 'Portal', 'Searchbar', 'Text', 'TextInput', 'TouchableRipple'].map(k => [k, k])), Dialog: Object.assign(props => props.visible ? react.createElement('Dialog', props, ...props.children) : null, { Title: 'DialogTitle', Content: 'DialogContent', Actions: 'DialogActions' }), List: { Accordion: 'Accordion' }, useTheme: () => ({ colors: {} }) },
    '../lib/api': { ApiError, request }, '../lib/calendar': { dayKey: () => '2026-09-18' }, '../lib/household': { useHousehold: () => household }, '../lib/inventory': model,
    '../ui/components': { EmptyState: 'EmptyState', PageHeader: 'PageHeader', SectionCard: 'SectionCard' },
  };
  const exports = {};
  runInNewContext(compiled, { exports, require: id => { assert(id in modules, id); return modules[id]; }, document, crypto: webcrypto, setInterval: fn => { lifecycle.set('timer', fn); return 1; }, clearInterval() {}, console });
  const props = { user: clone(f.session.user), state: { people: [{ id: 'member1', name: '甲' }, { id: 'member2', name: '乙' }], shopping: [] }, onInventoryPending: value => { navigation = value; } };
  function expand(node) {
    if (!node || typeof node !== 'object') return node;
    if (node.type === 'Dialog' && !node.props.visible) return null;
    if (typeof node.type === 'function') return expand(node.type(node.props));
    return { ...node, props: { ...node.props, children: (node.props.children || []).map(expand) } };
  }
  function render() { cursor = 0; dirty = false; tree = expand(exports.default(props)); for (const effect of effects.splice(0)) effect(); }
  async function settle() { for (let i = 0; i < 30; i++) { if (dirty && !closed) render(); await new Promise(resolve => setImmediate(resolve)); } }
  const nodes = (node = tree) => !node || typeof node !== 'object' ? [] : [node, ...node.props.children.flatMap(child => nodes(child))];
  const text = (node = tree) => typeof node === 'string' || typeof node === 'number' ? String(node) : node && typeof node === 'object' ? [node.props.title || '', node.props.description || '', ...(node.props.children || []).map(text)].join(' ') : '';
  const find = (type, label) => nodes().find(node => node.type === type && (node.props.accessibilityLabel === label || text(node).trim() === label));
  async function click(label) { const node = find('Button', label) || find('TouchableRipple', label); assert(node, 'Missing control: ' + label + '\n' + text()); assert(!node.props.disabled, 'Disabled: ' + label); node.props.onPress(); await settle(); }
  async function edit(label, value) { const node = find('TextInput', label); assert(node && !node.props.disabled); node.props.onChangeText(value); await settle(); }
  async function open() { await settle(); await click('查看物品 PRIVATE ITEM'); await click('打开批次 ' + acquisitionId); }
  return { f, open, settle, click, edit, find, text, get navigation() { return navigation; }, posts: () => f.calls.filter(c => c.method === 'POST'), async hide() { document.hidden = true; lifecycle.get('visibilitychange')(); await settle(); }, async show() { document.hidden = false; lifecycle.get('visibilitychange')(); await settle(); }, close() { closed = true; for (const cleanup of cleanups) cleanup?.(); } };
}

test('followup validator binds both targets, distinguishes deleted and strips source extras', () => {
  const raw = { ...association('linked'), privateSource: 'secret' }; raw.task.privateOrder = 'secret';
  const value = model.validateFollowup(raw, itemId, acquisitionId);
  assert(!('privateSource' in value)); assert(!('privateOrder' in value.task));
  assert.equal(model.validateFollowup(association('deleted'), itemId, acquisitionId).state, 'deleted');
  for (const bad of [{ ...raw, itemId: taskId }, { ...raw, acquisitionId: taskId }, { ...raw, task: null }, { ...association(), task: task() }, { ...raw, task: { ...task(), done: 'true' } }, { ...raw, task: { ...task(), due: '2026-02-30' } }]) assert.throws(() => model.validateFollowup(bad, itemId, acquisitionId));
});
test('explicit task payload contains only shared input and checks owner/date/length', () => {
  const input = { title: ' 跟进售后 ', owner: 'shared', due: '', note: '', privateSource: 'must not be sent' };
  assert.deepEqual(model.followupInput(input, ['member1']), { title: '跟进售后', owner: 'shared', due: '', note: '' });
  for (const patch of [{ title: ' ' }, { owner: 'removed' }, { due: '2026-02-30' }, { note: 'x'.repeat(501) }]) assert.throws(() => model.followupInput({ ...input, ...patch }, ['member1']));
});
test('real TSX form defaults generic, shares explicitly, cancels without writes', async t => {
  const h = harness(); t.after(() => h.close()); await h.open(); await h.click('创建售后待办');
  assert.equal(h.find('TextInput', '售后待办标题').props.value, '跟进售后');
  assert.equal(h.find('TextInput', '待办备注（可选，共享）').props.value, '');
  assert(h.text().includes('这条待办会在家庭清单中共享')); assert(!h.text().includes('PRIVATE ORDER')); assert(h.navigation);
  assert.equal(h.find('TouchableRipple', '售后待办负责人 共同').props['aria-checked'], true);
  await h.click('取消编辑'); await h.click('放弃这次编辑'); assert.equal(h.posts().length, 0); assert.equal(h.navigation, null);
});
test('real TSX submits one explicit task payload then reads current changed/completed task', async t => {
  const h = harness(); t.after(() => h.close()); await h.open(); await h.click('创建售后待办');
  await h.click('售后待办负责人 乙'); await h.edit('待办截止日（可选，YYYY-MM-DD）', '2026-10-01'); await h.click('创建家庭待办');
  assert.equal(h.posts().length, 1); assert.deepEqual(h.posts()[0].body.data, { title: '跟进售后', owner: 'member2', due: '2026-10-01', note: '' }); assert.match(h.posts()[0].body.requestId, /^[a-f0-9]{32}$/);
  assert.equal(h.posts()[0].body.itemRevision, 1); assert.equal(h.posts()[0].csrf, 'synthetic-csrf'); assert.equal(h.navigation, null);
  h.f.link.task = { ...task(), title: '清单中已改名', done: true, revision: 2 }; await h.click('刷新物品');
  assert(h.text().includes('清单中已改名')); assert(h.text().includes('已完成')); assert.equal(h.f.batch.afterSalesState, 'open'); assert(!h.find('Button', '创建售后待办'));
});
test('failed/mismatched association GET never enables create; retry can show deleted', async t => {
  const h = harness(); t.after(() => h.close()); h.f.getFailure = 1; await h.open(); assert(!h.find('Button', '创建售后待办')); assert(h.find('Button', '重新读取售后待办'));
  h.f.link = { ...association(), acquisitionId: taskId }; await h.click('重新读取售后待办'); assert(!h.find('Button', '创建售后待办'));
  h.f.link = association('deleted'); await h.click('重新读取售后待办'); assert(h.text().includes('这条售后待办已删除')); assert.equal(h.posts().length, 0);
});
for (const mode of ['lost', 'malformed']) test(`unknown ${mode} response queries original receipt without second POST`, async t => {
  const h = harness(); t.after(() => h.close()); h.f.postFailure = mode; await h.open(); await h.click('创建售后待办'); await h.click('创建家庭待办');
  assert(h.navigation); assert(h.find('Button', '创建家庭待办').props.disabled); const original = h.posts()[0];
  await h.click('核对并重试本次操作'); assert.equal(h.posts().length, 1); assert(h.f.calls.some(call => call.path === '/inventory/operations/' + original.body.requestId)); assert.equal(h.navigation, null); assert(h.text().includes('跟进售后'));
});
test('conflict reread adopts existing or deleted association instead of creating another', async t => {
  const h = harness(); t.after(() => h.close()); h.f.postFailure = 'conflict'; await h.open(); await h.click('创建售后待办'); await h.click('创建家庭待办');
  h.f.link = association('deleted'); await h.click('重新核对并修改草稿'); assert(h.text().includes('这条售后待办已删除')); assert.equal(h.posts().length, 1); assert.equal(h.navigation, null); assert(!h.find('Button', '创建家庭待办'));
});
test('permission withdrawal on resume clears private details and followup draft', async t => {
  const h = harness(); t.after(() => h.close()); await h.open(); await h.click('创建售后待办'); await h.edit('售后待办标题', 'SHARED DRAFT');
  await h.hide(); assert(!h.text().includes('SHARED DRAFT')); h.f.denied = true; await h.show(); assert(!h.text().includes('PRIVATE ITEM')); assert(!h.find('TextInput', '售后待办标题')); assert.equal(h.navigation, null); assert.equal(h.posts().length, 0);
});
test('identity change rejects a late association response and clears its projection', async t => {
  const h = harness(); t.after(() => h.close()); await h.open(); let finish; h.f.gate = new Promise(resolve => { finish = resolve; });
  const refresh = h.click('刷新物品'); await h.settle(); h.f.session.user.auth_version = 2; finish(); await refresh; await h.settle();
  assert(!h.text().includes('PRIVATE ITEM')); assert(!h.find('Button', '创建售后待办')); assert.equal(h.posts().length, 0);
});
test('confirmed receipt followed by GET failure stays confirmed and never enables a new create', async t => {
  const h = harness(); t.after(() => h.close()); await h.open(); await h.click('创建售后待办'); h.f.getFailure = 1; await h.click('创建家庭待办');
  assert.equal(h.posts().length, 1); assert.equal(h.navigation, null); assert(!h.find('Button', '核对并重试本次操作')); assert(!h.find('Button', '创建售后待办'));
  h.f.link = association('deleted'); await h.click('重新读取售后待办'); assert(h.text().includes('这条售后待办已删除')); assert.equal(h.posts().length, 1);
});
test('closed aftersales never enables creation but still reads a linked task', async t => {
  const h = harness(); t.after(() => h.close()); h.f.batch.afterSalesState = 'closed'; await h.open(); assert(!h.find('Button', '创建售后待办'));
  h.f.link = association('linked'); await h.click('刷新物品'); assert(h.text().includes('跟进售后')); assert(h.text().includes('售后已结束')); assert(!h.find('Button', '创建售后待办'));
});
test('background discards late GET and resume rereads the current association', async t => {
  const h = harness(); t.after(() => h.close()); await h.open(); let finish; h.f.gate = new Promise(resolve => { finish = resolve; });
  const refresh = h.click('刷新物品'); await h.settle(); await h.hide(); finish(); await refresh; await h.settle(); assert.equal(h.text(), '');
  h.f.gate = null; h.f.link = association('linked'); h.f.link.task.title = '恢复后的当前待办'; await h.show(); assert(h.text().includes('恢复后的当前待办')); assert(!h.find('Button', '创建售后待办')); assert.equal(h.posts().length, 0);
});
