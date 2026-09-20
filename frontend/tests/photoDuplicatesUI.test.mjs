import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { runInNewContext } from 'node:vm';
const ts = createRequire(import.meta.url)('typescript');
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../src');
const id = n => n.toString(16).padStart(24, '0');
const targetId = id(1), sourceId = 'f'.repeat(32);
const photo = n => ({ id: id(n), revision: 2, caption: `合成照片 ${n}`, width: 600, height: 400,
  previewUrl: `/api/media/items/${id(n)}/preview`, visibility: 'private', canManage: true,
  source: n === 1 ? 'local-upload' : 'google-photos', accountId: n === 1 ? null : sourceId,
  journey: null, createdAt: '2026-09-20T00:00:00Z', mediaType: 'photo' });
const user = { id: 'member1', role: 'member', householdId: 'household1', auth_version: 1 };

// Execute the real screen and new panel with synthetic native/React surfaces
// and transport. These checks are not browser or real API integration proof.
function harness() {
  let cursor = 0, values = [], effects = [], tree, tick, pendingFetch, held, liveUser = user;
  const calls = [], rows = new Map(Array.from({ length: 22 }, (_, n) => [id(n + 1), photo(n + 1)]));
  const events = {}, context = { online: true, refresh: async () => {},
    mutate: async (path, method, body) => { calls.push({ path, method, body }); const old = rows.get(path.split('/').at(-1));
      assert.equal(body.revision, old.revision); rows.set(old.id, { ...old, ...body, revision: old.revision + 1 }); return { item: rows.get(old.id) }; } };
  const react = { createElement: (type, props, ...children) => ({ type, props: { ...props, children: children.flat(Infinity) } }),
    useRef(initial) { const i = cursor++; if (!(i in values)) values[i] = { current: initial }; return values[i]; },
    useState(initial) { const i = cursor++; if (!(i in values)) values[i] = initial; return [values[i], value => { values[i] = typeof value === 'function' ? value(values[i]) : value; }]; },
    useCallback: fn => fn,
    useEffect(fn, deps) { const i = cursor++; if (!(i in values) || deps.some((value, n) => value !== values[i].deps[n])) {
      const old = values[i]; values[i] = { deps }; effects.push(() => { old?.cleanup?.(); values[i].cleanup = fn(); }); } } };
  const session = () => ({ user: liveUser, csrf: 'synthetic-only' });
  async function request(path) {
    calls.push({ path, method: 'GET' });
    if (path === '/me') return session();
    if (path === '/accounts') return { accounts: [{ id: sourceId, provider: 'google', needsReauth: false, capabilities: { photos: true } }] };
    if (path === '/devices') return [];
    if (path === '/journeys') return { journeys: [] };
    if (path.startsWith('/media/imports?')) return { items: [] };
    if (path.startsWith('/media/items?')) return { items: [rows.get(targetId)], total: 1, hasMore: false };
    if (path.endsWith('/tv-grants')) { const row = rows.get(path.split('/').at(-2)); return { revision: row.revision, deviceIds: [] }; }
    if (path.includes('/duplicates?')) {
      const offset = Number(new URL('https://fixture.invalid' + path).searchParams.get('offset'));
      const items = [...rows.values()].filter(row => row.id !== targetId).slice(offset, offset + 20);
      return { photoId: targetId, photoRevision: rows.get(targetId).revision, matchBasis: 'display-copy-sha256', label: '展示副本一致，原图未核验',
        items, total: 21, limit: 20, offset, hasMore: offset + 20 < 21,
        coverage: { scope: 'mine', scanLimit: 1000, scanned: 21, capped: true, unverifiable: 2 } };
    }
    if (path.startsWith('/media/items/')) { const item = rows.get(path.split('/').at(-1));
      if (!item) throw new api.ApiError('Removed', 404); return { item: structuredClone(item) }; }
    throw new Error(`Unexpected route ${path}`);
  }
  const mocks = {
    react, 'react-native': { Image: 'Image', View: 'View', ScrollView: 'ScrollView', Platform: { OS: 'web' },
      StyleSheet: { create: value => value }, useWindowDimensions: () => ({ width: 390, height: 900 }),
      AppState: { currentState: 'active', addEventListener: () => ({ remove() {} }) } },
    'react-native-paper': Object.fromEntries(['ActivityIndicator', 'Button', 'Card', 'Dialog', 'Divider', 'List', 'Menu', 'Portal', 'ProgressBar', 'SegmentedButtons', 'Text', 'TextInput'].map(key => [key, key])),
    'expo-router': { useFocusEffect: fn => react.useEffect(fn, []) },
  };
  mocks['react-native-paper'].useTheme = () => ({ colors: {} });
  class Upload { view = { busy: false }; subscribe() { return () => {}; } dispose() {} suspend() {} resumeSelection() {} observe() {} }
  const cache = new Map();
  function load(path) {
    path = resolve(path); if (!existsSync(path)) path += existsSync(path + '.ts') ? '.ts' : '.tsx';
    if (cache.has(path)) return cache.get(path);
    const exports = {}; cache.set(path, exports);
    let source = readFileSync(path, 'utf8');
    if (path.endsWith('PhotosScreen.tsx')) source = source.replace('function PhotoWorkspace(', 'export function PhotoWorkspace(');
    const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true } }).outputText;
    runInNewContext(js, { exports, require: name => {
      if (name in mocks) return mocks[name];
      if (name === '../lib/household') return { useHousehold: () => context };
      if (name === '../lib/localPhotoUpload') return { LocalPhotoUpload: Upload };
      if (name === '../lib/api') return { ...api, request };
      if (name === '../lib/navigation') return { openPhotosProvider() { throw new Error('Provider call forbidden'); } };
      if (name === '../ui/components') return { EmptyState: 'EmptyState', PageHeader: 'PageHeader', SectionCard: 'SectionCard' };
      if (['../components/PhotoJourneySuggestions', '../components/MemberVideoPlayer', '../components/LocalPhotoImportPanel', '../ui/SelectionRow'].includes(name)) return { __esModule: true, default: name, SelectionRow: 'SelectionRow' };
      return load(resolve(dirname(path), name));
    }, process, console, AbortController, TextDecoder, Response, URL, Error,
    setTimeout, clearTimeout, setInterval: fn => { tick = fn; return 1; }, clearInterval() {},
    window: { addEventListener: (name, fn) => { events[name] = fn; }, removeEventListener() {} },
    fetch: async (url, init) => {
      assert.equal(init.method, 'GET'); const path = url.slice(4); const data = await request(path);
      if (pendingFetch && path.includes('/duplicates?')) { pendingFetch = false; await new Promise(resolve => { held = resolve; }); }
      return new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } });
    } });
    return exports;
  }
  const api = load(root + '/lib/api.ts');
  const { PhotoWorkspace } = load(root + '/screens/PhotosScreen.tsx');
  const Panel = load(root + '/components/PhotoDuplicateHints.tsx').default;
  const render = () => { cursor = 0; tree = PhotoWorkspace({ user, initialPhotoId: targetId, state: {}, onNavigate() {}, onBack: () => calls.push({ back: true }) }); effects.splice(0).forEach(fn => fn()); return tree; };
  const walk = (node = tree) => !node || typeof node !== 'object' ? [] : [node, ...(node.props?.children || []).flatMap(child => child === undefined ? [] : walk(child))];
  const text = node => typeof node === 'string' ? node : (node?.props?.children || []).map(text).join('');
  const button = label => walk().find(node => node.type === 'Button' && text(node) === label);
  const panel = () => walk().find(node => node.type === Panel);
  const field = () => walk().find(node => node.type === 'TextInput' && node.props.label === '照片说明');
  async function settle() { for (let i = 0; i < 6; i++) { await new Promise(setImmediate); render(); } }
  return { render, settle, panel, field, button, calls, rows, events, poll: () => tick(),
    hold: () => { pendingFetch = true; }, release: () => held(), switchUser: next => { liveUser = next; },
    panelTree: () => Panel(panel().props), walk, text, get context() { return context; } };
}

test('real screen scan is explicit, respects dirty draft, and panel discloses exact/partial scope', async () => {
  const h = harness(); h.render(); await h.settle();
  assert.equal(h.calls.some(c => c.path?.includes('/duplicates?')), false);
  h.field().props.onChangeText('未保存'); h.render(); h.panel().props.load(0); await h.settle();
  assert.equal(h.calls.some(c => c.path?.includes('/duplicates?')), false); assert.equal(h.field().props.value, '未保存');
  h.field().props.onChangeText('合成照片 1'); h.render(); h.panel().props.load(0); await h.settle();
  assert.equal(h.panel().props.data.items.length, 20);
  assert.match(h.text(h.panelTree()), /展示副本一致，原图未核验/);
  assert.match(h.text(h.panelTree()), /仅检查了部分已保存照片/);
});
test('page two opens original photo; dirty back uses existing decision and preserves return page/ID', async () => {
  const h = harness(); h.render(); await h.settle(); h.panel().props.load(20); await h.settle();
  const item = h.panel().props.data.items[0]; h.panel().props.open(item); await h.settle();
  assert.equal(h.field().props.value, '合成照片 22'); assert.equal(h.panel(), undefined);
  h.field().props.onChangeText('保留原照片草稿'); h.render(); h.button('返回重复提示').props.onPress(); await h.settle();
  assert.equal(h.field().props.value, '保留原照片草稿');
  h.button('返回').props.onPress(); h.render(); assert.equal(h.field().props.value, '保留原照片草稿');
  h.button('保存照片设置').props.onPress(); await h.settle();
  const write = h.calls.find(c => c.method === 'PATCH'); assert.equal(write.path, `/media/items/${item.id}`); assert.equal(write.body.revision, 2);
  h.button('返回重复提示').props.onPress(); await h.settle();
  assert.equal(h.field().props.value, '合成照片 1'); assert.equal(h.panel().props.data.offset, 20);
  assert.equal(h.calls.some(c => c.back), false); assert.equal(h.calls.filter(c => c.method !== 'GET').length, 1);
});
test('source/revision changes prevent opening old result and clear visible hints on poll', async () => {
  const h = harness(); h.render(); await h.settle(); h.panel().props.load(20); await h.settle();
  const item = h.panel().props.data.items[0]; h.rows.set(item.id, { ...item, revision: item.revision + 1 });
  h.panel().props.open(item); await h.settle(); assert.equal(h.field().props.value, '合成照片 1'); assert.equal(h.panel().props.data, null);
  h.panel().props.load(20); await h.settle(); h.rows.delete(item.id); h.poll(); await h.settle();
  assert.equal(h.panel()?.props.data ?? null, null);
});
test('late scan cannot survive offline concealment or a different member session', async () => {
  for (const reason of ['offline', 'member']) {
    const h = harness(); h.render(); await h.settle(); h.hold(); h.panel().props.load(0); await h.settle();
    if (reason === 'offline') { h.context.online = false; h.events.offline(); }
    else h.switchUser({ ...user, id: 'member2' });
    h.release(); await h.settle(); assert.equal(h.panel(), undefined);
  }
});
