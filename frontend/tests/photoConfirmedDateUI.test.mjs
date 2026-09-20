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
const photo = n => ({ userConfirmedDate: null, id: id(n), revision: 2, caption: `合成照片 ${n}`, width: 600, height: 400,
  previewUrl: `/api/media/items/${id(n)}/preview`, visibility: 'private', canManage: true,
  source: n === 1 ? 'local-upload' : 'google-photos', accountId: n === 1 ? null : sourceId,
  journey: null, createdAt: '2026-09-20T00:00:00Z', mediaType: 'photo' });
const user = { id: 'member1', role: 'member', householdId: 'household1', auth_version: 1 };

// Execute the real screen date handlers and date panel with synthetic native/React surfaces
// and transport. These checks are not browser or real API integration proof.
function harness() {
  let cursor = 0, values = [], effects = [], tree, tick, held, liveUser = user, mode = 'ok', holdRead = false, postFailure = false;
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
    if (path === '/me') { if (postFailure) { postFailure = false; throw new api.ApiError('Identity read unavailable', 503); } return session(); }
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
      if (!item) throw new api.ApiError('Removed', 404); const result = { item: structuredClone(item) };
      if (holdRead) { holdRead = false; await new Promise(resolve => { held = resolve; }); } return result; }
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
    const js = ts.transpileModule(source, { fileName: path, compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true } }).outputText;
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
      const path = url.slice(4);
      if (init.method === 'PATCH') {
        const body = JSON.parse(init.body), old = rows.get(targetId); calls.push({ path, method: 'PATCH', body });
        assert.equal(init.headers['X-CSRF-Token'], 'synthetic-only');
        if (mode === 'conflict') return new Response(JSON.stringify({ code: 'revision_conflict' }), { status: 409, headers: { 'Content-Type': 'application/json' } });
        assert.equal(body.revision, old.revision);
        rows.set(targetId, { ...old, ...body, revision: old.revision + 1 });
        if (mode === 'drop') throw new Error('Synthetic lost response after commit');
        if (mode === 'postMe') postFailure = true;
        if (mode === 'late') await new Promise(resolve => { held = resolve; });
        return new Response(JSON.stringify({ item: rows.get(targetId) }), { headers: { 'Content-Type': 'application/json' } });
      }
      assert.equal(init.method, 'GET'); const data = await request(path);
      return new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } });
    } });
    return exports;
  }
  const api = load(root + '/lib/api.ts');
  const { PhotoWorkspace } = load(root + '/screens/PhotosScreen.tsx');
  const Panel = load(root + '/components/PhotoConfirmedDate.tsx').default;
  const Duplicates = load(root + '/components/PhotoDuplicateHints.tsx').default;
  const render = () => { cursor = 0; tree = PhotoWorkspace({ user, initialPhotoId: targetId, state: {}, onNavigate() {}, onBack: () => calls.push({ back: true }) }); effects.splice(0).forEach(fn => fn()); return tree; };
  const walk = (node = tree) => !node || typeof node !== 'object' ? [] : [node, ...(node.props?.children || []).flatMap(child => child === undefined ? [] : walk(child))];
  const text = node => typeof node === 'string' ? node : (node?.props?.children || []).map(text).join('');
  const button = label => walk().find(node => node.type === 'Button' && text(node) === label);
  const panel = () => walk().find(node => node.type === Panel);
  const field = () => walk().find(node => node.type === 'TextInput' && node.props.label === '照片说明');
  async function settle() { for (let i = 0; i < 6; i++) { await new Promise(setImmediate); render(); } }
  return { render, settle, panel, field, button, calls, rows, events, poll: () => tick(),
    hold: () => { holdRead = true; }, mode: next => { mode = next; }, release: () => held(), switchUser: next => { liveUser = next; },
    duplicates: () => walk().find(node => node.type === Duplicates),
    panelTree: () => panel() ? Panel(panel().props) : undefined, walk, text, get context() { return context; } };
}

const writes = h => h.calls.filter(c => c.method === 'PATCH');
const input = (h, value) => { h.panel().props.change(value); h.render(); };
test('real date controls send only date/revision, invalidate hints, clear date and keep original ID', async () => {
  const h = harness(); h.render(); await h.settle();
  h.duplicates().props.load(0); await h.settle(); assert.ok(h.duplicates().props.data);
  input(h, '2016-02-29');
  const buttons = h.walk(h.panelTree()).filter(n => n.type === 'Button');
  const save = buttons.find(n => n.props.testID === 'photo-confirmed-date-save'); assert.equal(save.props.disabled, false);
  save.props.onPress(); await h.settle();
  assert.deepEqual(writes(h).map(x => x.body), [{ revision: 2, userConfirmedDate: '2016-02-29' }]);
  assert.equal(h.rows.get(targetId).caption, '合成照片 1'); assert.equal(h.panel().props.saved, '2016-02-29');
  assert.equal(h.duplicates().props.data, null); assert.match(h.text(h.panelTree()), /照片日期已更新/);
  h.panel().props.save(null); await h.settle();
  assert.deepEqual(writes(h).at(-1).body, { revision: 3, userConfirmedDate: null });
  assert.equal(h.panel().props.saved, null); assert.equal(h.rows.get(targetId).revision, 4);
});
test('other draft blocks date write until explicit discard, and date draft blocks settings save', async () => {
  const h = harness(); h.render(); await h.settle(); h.field().props.onChangeText('未保存说明'); h.render();
  input(h, '2016-02-29'); h.panel().props.save('2016-02-29'); await h.settle(); assert.equal(writes(h).length, 0);
  assert.equal(h.field().props.value, '未保存说明'); assert.equal(h.panel().props.otherDraft, true);
  h.button('保存照片设置').props.onPress(); await h.settle(); assert.equal(writes(h).length, 0);
  h.panel().props.discardOther(); h.render(); assert.equal(h.field().props.value, '合成照片 1');
  h.panel().props.save('2016-02-29'); await h.settle(); assert.equal(writes(h).length, 1);
});
for (const mode of ['drop', 'postMe']) test(`real ${mode} after committed PATCH keeps draft; recheck is GET only, never automatic resend`, async () => {
  const h = harness(); h.render(); await h.settle(); input(h, '2016-02-29'); h.mode(mode);
  h.panel().props.save('2016-02-29'); await h.settle();
  assert.equal(writes(h).length, 1); assert.equal(h.rows.get(targetId).userConfirmedDate, '2016-02-29');
  assert.equal(h.panel().props.needsCheck, true); assert.match(h.text(h.panelTree()), /结果待核对，不会自动重发/);
  h.panel().props.save('2016-02-29'); await h.settle(); assert.equal(writes(h).length, 1);
  h.mode('ok'); h.panel().props.recheck(); await h.settle();
  assert.equal(writes(h).length, 1); assert.equal(h.panel().props.needsCheck, false); assert.equal(h.panel().props.value, '2016-02-29');
  assert.match(h.text(h.panelTree()), /不是上一请求的执行回执/);
});
test('409 then original GET retains failed input separately from current date; explicit click alone retries new CAS', async () => {
  const h = harness(); h.render(); await h.settle(); input(h, '2021-07-19');
  h.rows.set(targetId, { ...h.rows.get(targetId), revision: 3, userConfirmedDate: '2016-02-29' }); h.mode('conflict');
  h.panel().props.save('2021-07-19'); await h.settle(); assert.equal(h.panel().props.needsCheck, true);
  h.mode('ok'); h.panel().props.recheck(); await h.settle();
  assert.equal(h.panel().props.value, '2021-07-19'); assert.equal(h.panel().props.saved, '2016-02-29'); assert.equal(writes(h).length, 1);
  h.panel().props.save('2021-07-19'); await h.settle();
  assert.deepEqual(writes(h).at(-1).body, { revision: 3, userConfirmedDate: '2021-07-19' });
});
test('blur hides pending date data, same identity resume preserves unresolved draft and never resends', async () => {
  const h = harness(); h.render(); await h.settle(); input(h, '2016-02-29'); h.mode('late');
  h.panel().props.save('2016-02-29'); await h.settle(); h.events.blur(); h.render(); assert.equal(h.panel(), undefined);
  h.release(); await h.settle(); h.events.focus(); await h.settle();
  assert.equal(h.panel().props.value, '2016-02-29'); assert.equal(h.panel().props.needsCheck, true); assert.equal(writes(h).length, 1);
});
test('late write response under another member never installs owner date controls', async () => {
  const h = harness(); h.render(); await h.settle(); input(h, '2016-02-29'); h.mode('late');
  h.panel().props.save('2016-02-29'); await h.settle(); h.switchUser({ ...user, id: 'member2' }); h.release(); await h.settle();
  assert.equal(h.panel(), undefined); assert.equal(h.field(), undefined); assert.equal(writes(h).length, 1);
});
test('late original GET with changed identity clears date model and draft', async () => {
  const h = harness(); h.render(); await h.settle(); input(h, '2016-02-29'); h.mode('drop');
  h.panel().props.save('2016-02-29'); await h.settle(); h.hold(); h.panel().props.recheck(); await h.settle();
  h.switchUser({ ...user, id: 'member2' }); h.release(); await h.settle(); assert.equal(h.panel(), undefined); assert.equal(h.field(), undefined);
});
test('removed original while rechecking clears editor and cannot revive the draft', async () => {
  const h = harness(); h.render(); await h.settle(); input(h, '2016-02-29'); h.mode('drop');
  h.panel().props.save('2016-02-29'); await h.settle(); h.rows.delete(targetId);
  h.panel().props.recheck(); await h.settle(); assert.equal(h.panel(), undefined); assert.equal(writes(h).length, 1);
});
test('Google owner detail has no date controls', async () => {
  const h = harness(); h.rows.set(targetId, { ...h.rows.get(targetId), source: 'google-photos' });
  h.render(); await h.settle(); assert.equal(h.panel(), undefined);

});
