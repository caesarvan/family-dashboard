import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { runInNewContext } from 'node:vm';
import { webcrypto } from 'node:crypto';
import { manualImportPayload, readImportColumnSelection, readImportPreview, confirmImportPayload } from '../src/lib/financeImport.ts';

const ts = createRequire(import.meta.url)('typescript');
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../src');
const file = { name: 'synthetic.csv', contentBase64: 'YWJj', encoding: 'auto' };
const selection = () => ({ headerLine: 1, lineKind: 'csv_lines', columns: ['日期', '金额', '标题', '币种', '方向', '备用'].map((label, index) => ({ index, label, columnLabel: String.fromCharCode(65 + index) })),
  suggestedMapping: { date: 0, amount: 1, title: 2, currency: 3 } });
const mapping = (flow = null) => ({ version: 2, headerLine: 1, date: 0, amount: 1, title: 2, currency: 3, flow });
const preview = (map = mapping()) => ({ rows: [{ line: 2, sourceLocation: { lineStart: 2, lineEnd: 2, lineKind: 'csv_lines' },
  title: '合成账单', date: '2026-09-20', amountCents: 2500, currency: 'CNY', flow: map.flow === null ? 'unknown' : 'expense', duplicate: false, conflict: false }],
  errors: [], errorCount: 0, warnings: [], newCount: 1, duplicateCount: 0, conflictCount: 0, previewToken: 'synthetic-preview',
  requiresSheetSelection: false, requiresAmountSelection: false, requiresColumnSelection: false, amountSelection: null,
  columnSelection: { ...selection(), mapping: map } });
const json = value => JSON.parse(JSON.stringify(value));

test('v2 auto and chosen direction preserve exact mapping; original v1 remains six fields', () => {
  for (const flow of [null, 4, 5]) {
    const payload = manualImportPayload('generic', 'payments', file, selection(), mapping(flow));
    assert.deepEqual(payload.mapping, mapping(flow));
    const shown = readImportPreview(preview(mapping(flow)));
    assert.deepEqual(shown.columnSelection.mapping, payload.mapping);
    assert.equal(shown.rows[0].flow, flow === null ? 'unknown' : 'expense');
    assert.equal('flowRaw' in shown.rows[0], false);
  }
  const old = { version: 1, headerLine: 1, date: 0, amount: 1, title: 2, currency: 3 };
  for (const kind of ['payments', 'orders']) assert.deepEqual(manualImportPayload('generic', kind, file, selection(), old).mapping, old);
  assert.deepEqual(Object.keys(readImportColumnSelection(selection()).suggestedMapping).sort(), ['amount', 'currency', 'date', 'title']);
});

test('v2 direction requires exact keys, a distinct actual header index or null', () => {
  for (const flow of [undefined, true, false, '4', -1, 1.5, 80, 79, 0, 1, 2, 3]) {
    assert.throws(() => manualImportPayload('generic', 'payments', file, selection(), { ...mapping(), flow }));
    assert.throws(() => readImportColumnSelection({ ...selection(), mapping: { ...mapping(), flow } }));
  }
  for (const map of [{ ...mapping(), extra: 0 }, { ...mapping(), version: 1 }, { ...mapping(), version: true },
    Object.fromEntries(Object.entries(mapping()).filter(([key]) => key !== 'flow'))]) {
    assert.throws(() => manualImportPayload('generic', 'payments', file, selection(), map));
  }
});

test('direction mapping cannot override known platforms or order imports, including auto-null', () => {
  for (const flow of [null, 4]) {
    for (const source of ['alipay', 'wechat', 'taobao', 'pinduoduo'])
      assert.throws(() => manualImportPayload(source, 'payments', file, selection(), mapping(flow)));
    assert.throws(() => manualImportPayload('generic', 'orders', file, selection(), mapping(flow)));
    const payload = manualImportPayload('generic', 'payments', file, selection(), mapping(flow));
    assert.throws(() => confirmImportPayload({ ...payload, kind: 'orders' }, readImportPreview(preview(mapping(flow))), 'a'.repeat(32)));
  }
});

test('confirmation rejects changed direction and freezes original file, mapping and request identity', () => {
  const payload = manualImportPayload('generic', 'payments', file, selection(), mapping(4));
  const shown = readImportPreview(preview(mapping(4))), id = 'a'.repeat(32);
  const intent = confirmImportPayload(payload, shown, id);
  payload.mapping.flow = 5; shown.columnSelection.mapping.flow = null;
  assert.deepEqual(intent.mapping, mapping(4)); assert.equal(intent.requestId, id);
  assert.equal(intent.file.contentBase64, file.contentBase64);
  assert.throws(() => confirmImportPayload(payload, readImportPreview(preview(mapping(4))), id));
  assert.throws(() => confirmImportPayload({ ...payload, mapping: mapping(null) }, readImportPreview(preview(mapping(4))), id));
});

// Real TSX + identity fence with synthetic host controls/HTTP DTOs. This is not
// browser, backend integration, or real statement import evidence.
function harness() {
  let cursor = 0, values = [], effects = [], tree, liveUser, heldPreview, releasePreview, unknownConfirm = false;
  const user = { id: 'member1', role: 'member', householdId: 'h1', auth_version: 1 }; liveUser = user;
  const calls = [], events = {}, session = () => ({ user: liveUser, csrf: 'synthetic-csrf' });
  const identityKey = JSON.stringify(['member', 'h1', 'member1', 1, null, null, null, null, 'synthetic-csrf']);
  class ApiError extends Error { constructor(message, status = 0, code = '') { super(message); this.status = status; this.code = code; } }
  const receipt = id => ({ requestId: id, receiptId: 'b'.repeat(64), batchId: 'c'.repeat(24), imported: 0, duplicates: 1, conflicts: 1,
    confirmedAt: '2026-09-20T10:00:00Z', resultMonths: [{ month: '2026-09', recordCount: 1 }], replayed: false });
  const context = { user, identityKey, online: true, refresh: async () => {}, mutate: async (path, method, body) => {
    calls.push({ path, method, body: json(body) });
    if (path.endsWith('/preview')) {
      if (body.inspectColumns) return { ...preview(), rows: [], previewToken: null, requiresColumnSelection: true, columnSelection: selection() };
      if (heldPreview) { heldPreview = false; await new Promise(resolve => { releasePreview = resolve; }); }
      return preview(body.mapping);
    }
    assert.equal(path, '/finance-hub/imports/confirm');
    if (unknownConfirm) throw new ApiError('synthetic connection lost');
    return receipt(body.requestId);
  } };
  async function request(path) {
    calls.push({ path, method: 'GET' });
    if (path === '/me') return session();
    if (path.startsWith('/finance-hub/imports/results/')) return receipt(path.split('/').at(-1));
    throw new Error('Unexpected read '+path);
  }
  const react = { createElement: (type, props, ...children) => ({ type, props: { ...props, children: children.flat(Infinity) } }),
    useRef(initial) { const n = cursor++; if (!(n in values)) values[n] = { current: initial }; return values[n]; },
    useState(initial) { const n = cursor++; if (!(n in values)) values[n] = typeof initial === 'function' ? initial() : initial;
      return [values[n], value => { values[n] = typeof value === 'function' ? value(values[n]) : value; }]; },
    useCallback: fn => fn, useEffect(fn, deps) { const n = cursor++;
      if (!(n in values) || deps.some((v, i) => v !== values[n].deps[i])) { const old = values[n]; values[n] = { deps };
        effects.push(() => { old?.cleanup?.(); values[n].cleanup = fn(); }); } } };
  const doc = { hidden: false, body: { appendChild() {} }, addEventListener: (name, fn) => { events[name] = fn; }, removeEventListener() {},
    createElement: () => { const handlers = {}; return { style: {}, setAttribute() {}, remove() {},
      files: [{ name: file.name, size: 3, arrayBuffer: async () => new Uint8Array([97, 98, 99]).buffer }],
      addEventListener: (name, fn) => { handlers[name] = fn; }, click: () => handlers.change() }; } };
  const paper = Object.fromEntries(['ActivityIndicator', 'Button', 'Divider', 'Portal', 'SegmentedButtons', 'Text', 'TextInput', 'TouchableRipple'].map(name => [name, name]));
  paper.Dialog = Object.assign('Dialog', { Title: 'Dialog.Title', ScrollArea: 'Dialog.ScrollArea', Content: 'Dialog.Content', Actions: 'Dialog.Actions' });
  paper.useTheme = () => ({ colors: {} });
  const cache = new Map();
  function load(path) {
    path = resolve(path); if (!existsSync(path)) path += existsSync(path+'.ts') ? '.ts' : '.tsx';
    if (cache.has(path)) return cache.get(path);
    const exports = {}; cache.set(path, exports);
    let source = readFileSync(path, 'utf8');
    if (path.endsWith('FinanceImportPanel.tsx')) source = source.replace('function ImportWorkspace(', 'export function ImportWorkspace(');
    const js = ts.transpileModule(source, { fileName: path, compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true } }).outputText;
    runInNewContext(js, { exports, require: name => {
      if (name === 'react') return react;
      if (name === 'react-native') return { View: 'View', ScrollView: 'ScrollView', Platform: { OS: 'web' }, StyleSheet: { create: v => v },
        useWindowDimensions: () => ({ width: 390, height: 850 }), AppState: { currentState: 'active', addEventListener: () => ({ remove() {} }) } };
      if (name === 'react-native-paper') return paper;
      if (name === 'expo-router') return { useFocusEffect: fn => react.useEffect(fn, []) };
      if (name === '../lib/api') return { ApiError, request };
      if (name === '../lib/household') return { useHousehold: () => context };
      if (name === '../ui/components') return { EmptyState: 'EmptyState', PageHeader: 'PageHeader', SectionCard: 'SectionCard' };
      if (name === '../ui/theme') return { useDisplayDensity: () => ({ sectionGap: 12 }) };
      return load(resolve(dirname(path), name));
    }, console, Error, AbortController, Uint8Array, btoa, crypto: webcrypto, setTimeout, clearTimeout,
    document: doc, navigator: { onLine: true }, window: { addEventListener: (name, fn) => { events[name] = fn; }, removeEventListener() {} } });
    return exports;
  }
  const { ImportWorkspace } = load(root+'/screens/FinanceImportPanel.tsx');
  const render = () => { cursor = 0; tree = ImportWorkspace({ identityKey, user, onClose() {}, onImported() {} }); effects.splice(0).forEach(fn => fn()); };
  const walk = (node = tree) => !node || typeof node !== 'object' || node.type === paper.Dialog && !node.props.visible ? []
    : [node, ...(node.props?.children || []).flatMap(child => child === undefined ? [] : walk(child))];
  const text = node => typeof node === 'string' || typeof node === 'number' ? String(node) : (node?.props?.children || []).map(text).join('');
  const button = label => walk().find(n => n.type === 'Button' && text(n) === label);
  async function settle() { for (let n = 0; n < 5; n++) { await new Promise(setImmediate); render(); } }
  async function press(label) { const b = button(label); assert.ok(b, label); assert.equal(!!b.props.disabled, false, label); b.props.onPress(); await settle(); }
  async function choose(label, item) { await press(label); const n = walk().find(n => n.type === 'TouchableRipple' && n.props.accessibilityLabel === item);
    assert.ok(n, item); assert.equal(!!n.props.disabled, false); n.props.onPress(); await settle(); }
  return { render, settle, press, choose, button, walk, text: () => text(tree), calls, context, events,
    hold: () => { heldPreview = true; }, release: () => releasePreview(), switchUser: () => { liveUser = { ...user, id: 'member2' }; },
    unknown: () => { unknownConfirm = true; } };
}
async function mapped() { const h = harness(); h.render(); await h.settle(); await h.press('选择账单文件'); await h.press('手动指定列'); await h.press('读取表头'); return h; }

test('real panel defaults auto, invalidates direction preview but keeps file/four-column draft', async () => {
  const h = await mapped(); assert.match(h.text(), /自动识别/);
  await h.press('按所选列预览'); assert.deepEqual(h.calls.at(-2)?.body?.mapping || h.calls.find(c => c.body?.mapping)?.body.mapping, mapping());
  assert.match(h.text(), /待核对/); assert.ok(h.button('确认导入 · 仅本人'));
  const before = h.calls.filter(c => c.method === 'POST').length;
  await h.choose('收支方向（可选）', 'E 列 · 方向');
  assert.equal(h.button('确认导入 · 仅本人'), undefined); assert.match(h.text(), /synthetic.csv/);
  assert.match(h.text(), /A 列 · 日期/); assert.match(h.text(), /B 列 · 金额/);
  assert.equal(h.calls.filter(c => c.method === 'POST').length, before);
  await h.press('按所选列预览'); assert.equal(h.calls.filter(c => c.body?.mapping).at(-1).body.mapping.flow, 4);
  await h.choose('收支方向（可选）', '自动识别'); assert.equal(h.button('确认导入 · 仅本人'), undefined);
});

test('real panel disallows a later column collision and does not offer direction for orders/platforms', async () => {
  const h = await mapped(); await h.choose('收支方向（可选）', 'E 列 · 方向'); await h.choose('日期列', 'E 列 · 方向');
  assert.equal(h.button('按所选列预览').props.disabled, true); assert.match(h.text(), /不能与日期/);
  h.walk().find(n => n.type === 'SegmentedButtons').props.onValueChange('orders'); await h.settle(); await h.press('读取表头');
  assert.equal(h.button('收支方向（可选）'), undefined); await h.press('按所选列预览');
  assert.equal(h.calls.filter(c => c.body?.mapping).at(-1).body.mapping.version, 1);
  await h.choose('文件来源：通用表格', '支付宝'); assert.equal(h.button('收支方向（可选）'), undefined); assert.equal(h.button('手动指定列'), undefined);
});

test('unknown v2 confirm keeps original direction/request and read-only receipt preserves conflicts', async () => {
  const h = await mapped(); await h.choose('收支方向（可选）', 'E 列 · 方向'); await h.press('按所选列预览');
  h.unknown(); await h.press('确认导入 · 仅本人');
  const submitted = h.calls.find(c => c.path.endsWith('/confirm')); assert.equal(submitted.body.mapping.flow, 4);
  assert.equal(h.button('收支方向（可选）'), undefined); assert.ok(h.button('核对保存结果'));
  await h.press('核对保存结果');
  assert.equal(h.calls.filter(c => c.path.endsWith('/confirm')).length, 1);
  assert.ok(h.calls.some(c => c.method === 'GET' && c.path.endsWith('/results/'+submitted.body.requestId)));
  assert.match(h.text(), /冲突 1 条（保留原记录）/);
});

test('a late mapped preview cannot display or confirm after identity/offline fence invalidation', async () => {
  for (const reason of ['member', 'offline']) {
    const h = await mapped(); h.hold(); h.button('按所选列预览').props.onPress(); await h.settle();
    if (reason === 'member') h.switchUser(); else { h.context.online = false; h.events.offline(); }
    h.release(); await h.settle();
    assert.equal(h.button('确认导入 · 仅本人'), undefined); assert.doesNotMatch(h.text(), /合成账单/);
    assert.equal(h.calls.some(c => c.path.endsWith('/confirm')), false);
  }
});
