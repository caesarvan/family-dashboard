import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { webcrypto } from 'node:crypto';
import * as inventory from '../src/lib/inventory.ts';
import * as sources from '../src/lib/inventorySources.ts';

const require = createRequire(new URL('../package.json', import.meta.url));
const ts = require('typescript');
const source = readFileSync(new URL('../src/components/InventorySourcePanel.tsx', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022 } }).outputText;
const itemId = 'a'.repeat(24), acquisitionId = 'b'.repeat(24), orderId = 'c'.repeat(24), linkId = 'd'.repeat(24);
const clone = value => structuredClone(value);
const order = () => ({ id: orderId, revision: 1, title: 'PRIVATE ORDER', date: '2026-09-19', status: '原始订单状态' });
const line = () => ({ lineKey: 'item:0', title: 'PRIVATE PRODUCT', variant: '原商品规格', quantityText: '两盒共六节' });
const linked = () => ({ id: linkId, revision: 1, status: 'active', state: 'current', reviewReasons: [], orderId, lineKey: 'item:0', orderRevision: 1, order: order(), line: line() });
const orderPage = () => ({ order: order(), lines: [{ ...line(), linkState: 'none', link: null }], total: 1, limit: 50, offset: 0, nextOffset: null });
class ApiError extends Error { constructor(status, code = '') { super('synthetic API ' + status); this.status = status; this.code = code; } }

// Executes production TSX and real request fences with controlled hook/Paper/
// transport doubles. Browser layout and actual Flask transactions are separate.
function harness(options = {}) {
  const f = {
    session: { user: { id: 'member1', name: '甲', role: 'member', householdId: 'house-one', auth_version: 1 }, csrf: 'test-csrf' },
    item: { id: itemId, owner: 'member1', title: 'MANUAL STOCK', unit: '节', variant: '', location: '', visibility: 'private', reorderPoint: null, belowThreshold: false, revision: 1, onHandQty: 0, inTransitQty: 6, plannedQty: 0, canRead: true, canMutate: true, canManage: true },
    batch: { id: acquisitionId, itemId, kind: 'purchase', shoppingId: null, orderedQty: 6, orderState: 'in_transit', orderedOn: null, expectedOn: null, warrantyUntil: null, afterSalesState: 'none', note: '', revision: 1, itemRevision: 1, canMutate: true, canManageSources: true, canEditAllFields: true, editableFields: [], onHandQty: 0, receivedQty: 0, returnedQty: 0, remainingExpectedQty: 6 },
    source: { itemId, acquisitionId, link: options.link || null }, page: orderPage(), calls: [], receipt: null, postFailure: '', sourceFailure: 0, denied: false, gate: null, orderMissing: false,
  };
  const slots = [], effects = [], cleanups = [], lifecycle = new Map();
  let cursor = 0, dirty = true, tree, closed = false, navigation = null, saved = 0;
  const document = { hidden: false, addEventListener: (name, fn) => lifecycle.set(name, fn), removeEventListener: name => lifecycle.delete(name) };
  const useState = initial => { const i = cursor++; if (!(i in slots)) slots[i] = initial; return [slots[i], value => { slots[i] = typeof value === 'function' ? value(slots[i]) : value; dirty = true; }]; };
  const useRef = initial => { const i = cursor++; if (!(i in slots)) slots[i] = { current: initial }; return slots[i]; };
  const changed = (a, b) => !a || !b || a.length !== b.length || a.some((v, i) => v !== b[i]);
  const useEffect = (fn, deps) => { const i = cursor++; if (changed(slots[i], deps)) { slots[i] = deps; effects.push(() => { cleanups[i]?.(); cleanups[i] = fn(); }); } };
  const useCallback = (fn, deps) => { const i = cursor++; if (!slots[i] || changed(slots[i].deps, deps)) slots[i] = { deps, fn }; return slots[i].fn; };
  const react = { useState, useRef, useEffect, useCallback, Fragment: 'Fragment', createElement: (type, props, ...children) => ({ type, props: { ...props, children: children.flat(Infinity).filter(v => v !== undefined) } }) };
  const household = { user: f.session.user, online: true, identityKey: inventory.inventorySignature(f.session), refresh: async () => {} };
  async function request(path, options = {}, csrf) {
    f.calls.push({ path, method: options.method || 'GET', body: options.body ? JSON.parse(options.body) : null, csrf });
    if (path === '/me') return clone(f.session);
    if (f.denied) throw new ApiError(404);
    if (path === `/inventory/acquisitions/${acquisitionId}`) return { item: clone(f.item), acquisition: clone(f.batch) };
    if (path.endsWith('/source')) {
      if (f.gate) await f.gate;
      if (f.sourceFailure) { f.sourceFailure--; throw new ApiError(503); }
      return clone(f.source);
    }
    if (path.startsWith('/inventory/orders/')) { if (f.orderMissing) throw new ApiError(404); return clone(f.page); }
    if (path === '/inventory/sources/preview') {
      const body = JSON.parse(options.body); f.intent = body;
      return { requestId: body.requestId, operation: body.operation, item: clone(f.item), acquisition: clone(f.batch), order: f.source.link?.order || (f.orderMissing ? null : order()), line: f.source.link?.line || (f.orderMissing ? null : line()), link: clone(f.source.link), previewToken: 'signed-original-token', expiresInSeconds: 900 };
    }
    if (path === '/inventory/sources/confirm') {
      if (['expired', 'conflict'].includes(f.postFailure)) throw new ApiError(f.postFailure === 'expired' ? 400 : 409);
      f.item.revision++; f.batch.revision++; f.batch.itemRevision++;
      f.source.link = f.intent.operation === 'attach' ? linked() : { ...f.source.link, revision: f.source.link.revision + 1, status: 'detached', state: 'detached' };
      f.receipt = { operation: { itemId, itemRevision: f.item.revision, acquisitionId, acquisitionRevision: f.batch.revision, sourceLinkId: linkId, sourceRevision: f.source.link.revision, replayed: false }, item: clone(f.item), acquisition: clone(f.batch) };
      if (f.postFailure === 'lost') throw new Error('response lost after commit');
      const receipt = clone(f.receipt); if (f.postFailure === 'malformed') delete receipt.operation.sourceLinkId;
      return receipt;
    }
    if (path.startsWith('/inventory/operations/')) { if (!f.receipt) throw new ApiError(404); return { ...clone(f.receipt), operation: { ...f.receipt.operation, replayed: true } }; }
    throw new Error('Unexpected path ' + path);
  }
  const modules = {
    react,
    'react-native': { AppState: { currentState: 'active', addEventListener: (_name, fn) => { lifecycle.set('app', fn); return { remove() {} }; } }, StyleSheet: { create: v => v }, View: 'View' },
    'expo-router': { useFocusEffect: fn => useEffect(fn, [fn]) },
    'react-native-paper': Object.fromEntries(['ActivityIndicator', 'Button', 'Text'].map(k => [k, k])),
    '../lib/api': { ApiError, request }, '../lib/household': { useHousehold: () => household }, '../lib/inventory': inventory, '../lib/inventorySources': sources,
    '../ui/components': { EmptyState: 'EmptyState', PageHeader: 'PageHeader', SectionCard: 'SectionCard' },
  };
  const exports = {};
  runInNewContext(compiled, { exports, require: id => { assert(id in modules, id); return modules[id]; }, document, console, crypto: webcrypto });
  const props = { acquisitionId, ...(options.viewOnly ? {} : { orderId, lineKey: 'item:0' }), onBack() {}, onSaved: () => { saved++; }, onPendingChange: value => { navigation = value; } };
  function expand(node) {
    if (!node || typeof node !== 'object') return node;
    if (typeof node.type === 'function') return expand(node.type(node.props));
    return { ...node, props: { ...node.props, ...(node.props.action ? { action: expand(node.props.action) } : {}), children: (node.props.children || []).map(expand) } };
  }
  function render() { cursor = 0; dirty = false; tree = expand(exports.default(props)); for (const effect of effects.splice(0)) effect(); }
  async function settle() { for (let i = 0; i < 24; i++) { if (dirty && !closed) render(); await new Promise(resolve => setImmediate(resolve)); } }
  const nodes = (node = tree) => !node || typeof node !== 'object' ? [] : [node, ...(node.props.action ? nodes(node.props.action) : []), ...node.props.children.flatMap(child => nodes(child))];
  const text = (node = tree) => typeof node === 'string' || typeof node === 'number' ? String(node) : node && typeof node === 'object' ? [node.props.title || '', node.props.description || '', ...(node.props.children || []).map(text)].join(' ') : '';
  const button = label => nodes().find(node => node.type === 'Button' && (node.props.accessibilityLabel === label || text(node).trim() === label));
  async function click(label) { const node = button(label); assert(node, 'Missing control: ' + label + '\n' + text()); assert(!node.props.disabled, 'Disabled: ' + label); node.props.onPress(); await settle(); }
  return { f, settle, click, button, text, posts: () => f.calls.filter(c => c.method === 'POST'), get navigation() { return navigation; }, get saved() { return saved; }, async hide() { document.hidden = true; lifecycle.get('visibilitychange')(); await settle(); }, async show() { document.hidden = false; lifecycle.get('visibilitychange')(); await settle(); }, close() { closed = true; for (const cleanup of cleanups) cleanup?.(); } };
}

test('private order projection drops financial extras and keeps raw quantities as text', () => {
  const value = orderPage(); value.order.amountCents = 999; value.lines[0].account = 'PRIVATE ACCOUNT';
  const projected = sources.readOrderSources(value, orderId);
  assert.equal(projected.lines[0].quantityText, '两盒共六节'); assert(!('amountCents' in projected.order)); assert(!('account' in projected.lines[0]));
  for (const bad of [{ ...value, order: { ...value.order, id: itemId } }, { ...value, limit: 100 }, { ...value, lines: [{ ...line(), linkState: 'linked', link: null }] }, { ...value, lines: [value.lines[0], value.lines[0]], total: 2 }]) assert.throws(() => sources.readOrderSources(bad, orderId));
});
test('source projection binds both inventory targets, changed lines cannot silently remap', () => {
  const value = { itemId, acquisitionId, link: linked(), privateToken: 'extra' };
  assert(!('privateToken' in sources.readAcquisitionSource(value, itemId, acquisitionId)));
  assert.throws(() => sources.readAcquisitionSource({ ...value, itemId: orderId }, itemId, acquisitionId));
  assert.throws(() => sources.readAcquisitionSource({ ...value, link: { ...linked(), state: 'needs_review', reviewReasons: ['source_changed'] } }, itemId, acquisitionId));
  assert.equal(sources.readAcquisitionSource({ ...value, link: { ...linked(), state: 'needs_review', reviewReasons: ['source_changed'], line: null } }, itemId, acquisitionId).link.state, 'needs_review');
});
test('real panel previews only explicit source references and cancellation makes no confirm', async t => {
  const h = harness(); t.after(h.close); await h.settle(); await h.click('预览关联订单来源');
  assert.equal(h.posts().length, 1); assert(h.navigation); assert(h.button('返回库存批次').props.disabled);
  assert.deepEqual(Object.keys(h.posts()[0].body).sort(), ['requestId', 'operation', 'acquisitionId', 'itemRevision', 'revision', 'orderId', 'lineKey', 'orderRevision'].sort());
  assert.equal(h.posts()[0].csrf, 'test-csrf'); assert(h.text().includes('6')); assert(!h.text().includes('amountCents'));
  await h.click('取消来源预览'); assert.equal(h.navigation, null); assert.equal(h.posts().length, 1);
});
test('explicit source confirmation leaves physical quantities intact and enables detach', async t => {
  const h = harness(); t.after(h.close); await h.settle(); await h.click('预览关联订单来源'); await h.click('确认关联订单来源');
  assert.equal(h.f.batch.onHandQty, 0); assert.equal(h.f.batch.orderedQty, 6); assert.equal(h.saved, 1); assert.equal(h.navigation, null);
  assert(h.button('预览解除订单来源')); assert.deepEqual(h.posts()[1].body, { requestId: h.posts()[0].body.requestId, previewToken: 'signed-original-token', confirmSource: true });
});
for (const mode of ['lost', 'malformed']) test(`unknown ${mode} reply recovers the original receipt with no second confirmation`, async t => {
  const h = harness(); t.after(h.close); await h.settle(); await h.click('预览关联订单来源'); h.f.postFailure = mode; await h.click('确认关联订单来源');
  assert(h.navigation); assert(h.button('返回库存批次').props.disabled); const intent = h.posts()[1].body;
  await h.click('核对原来源操作'); assert.equal(h.posts().filter(c => c.path.endsWith('/confirm')).length, 1);
  assert.equal(h.f.calls.filter(c => c.path === '/inventory/operations/' + intent.requestId).length, 1); assert.equal(h.saved, 1); assert.equal(h.navigation, null);
});
for (const mode of ['expired', 'conflict']) test(`${mode} confirmation keeps saved inventory and requires a fresh explicit preview`, async t => {
  const h = harness(); t.after(h.close); await h.settle(); await h.click('预览关联订单来源'); h.f.postFailure = mode; await h.click('确认关联订单来源');
  assert.equal(h.f.item.revision, 1); assert.equal(h.f.source.link, null); assert.equal(h.saved, 0); assert.equal(h.navigation, null);
  assert(h.button('预览关联订单来源')); assert(!h.button('确认关联订单来源')); assert(h.text().includes('已保存的批次保留'));
});
test('deleted original order can still be explicitly detached, without recreating stock', async t => {
  const link = { ...linked(), state: 'needs_review', reviewReasons: ['source_missing'], order: null, line: null };
  const h = harness({ link }); t.after(h.close); h.f.orderMissing = true; await h.settle();
  assert(h.text().includes('原订单已删除或不可用')); await h.click('预览解除订单来源'); await h.click('确认解除订单来源');
  assert.equal(h.f.source.link.status, 'detached'); assert.equal(h.f.batch.orderedQty, 6); assert.equal(h.f.batch.onHandQty, 0); assert.equal(h.posts().length, 2);
});
test('only a purchase creator gets the source capability', () => {
  const batch = { kind: 'purchase', canMutate: true, canManageSources: true };
  assert.equal(sources.canManageSource(batch), true); for (const patch of [{ kind: 'opening' }, { canManageSources: false }, { canManageSources: undefined }, { canMutate: false }]) assert.equal(sources.canManageSource({ ...batch, ...patch }), false);
});
test('background hides private data, late read cannot restore it, resume rereads source', async t => {
  const h = harness(); t.after(h.close); await h.settle(); let release;
  h.f.gate = new Promise(resolve => { release = resolve; }); const action = h.click('刷新订单来源'); await h.settle(); await h.hide(); release(); await action;
  assert(!h.text().includes('PRIVATE PRODUCT')); assert(!h.text().includes('MANUAL STOCK')); h.f.gate = null; await h.show(); assert(h.text().includes('PRIVATE PRODUCT'));
});
test('full identity change before a late source result clears private data and blocks confirm', async t => {
  const h = harness(); t.after(h.close); await h.settle(); let release;
  h.f.gate = new Promise(resolve => { release = resolve; }); const action = h.click('刷新订单来源'); await h.settle(); h.f.session.user.auth_version++; release(); await action; await h.settle();
  assert(!h.text().includes('PRIVATE PRODUCT')); assert(!h.button('预览关联订单来源')); assert(h.text().includes('旧资料已隐藏'));
});
test('confirmed receipt followed by refresh failure remains confirmed and does not offer retry POST', async t => {
  const h = harness(); t.after(h.close); await h.settle(); await h.click('预览关联订单来源'); h.f.sourceFailure = 1; await h.click('确认关联订单来源');
  assert.equal(h.saved, 1); assert.equal(h.navigation, null); assert(!h.button('核对原来源操作')); await h.click('刷新订单来源'); assert(h.button('预览解除订单来源')); assert.equal(h.posts().filter(c => c.path.endsWith('/confirm')).length, 1);
});
