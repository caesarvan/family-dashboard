import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { runInNewContext } from 'node:vm';
import { webcrypto } from 'node:crypto';

const require = createRequire(import.meta.url), ts = require('typescript');
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../src');
const copy = value => JSON.parse(JSON.stringify(value));
const gate = () => { let release; const promise = new Promise(resolve => { release = resolve; }); return { promise, release }; };
const id = 'a'.repeat(24);
const session = () => ({ user: { role: 'member', id: 'member1', householdId: 'home', auth_version: 1 }, csrf: 'synthetic' });
const signature = s => JSON.stringify([s.user.role, s.user.householdId, s.user.id, s.user.auth_version, null, null, null, null, s.csrf]);
const layout = () => ({ order: ['calendar', 'finance', 'tasks', 'shopping', 'trips'], hidden: [], theme: 'forest', density: 'comfortable' });
const playback = () => ({ deviceId: id, revision: 1, mode: 'photos', paused: false, intervalSeconds: 10, position: 0, photoCount: 2, canStart: true, updatedAt: '2026-09-20T00:00:00Z' });
class ApiError extends Error { constructor(message, status = 0) { super(message); this.status = status; } }

// Execute the real screen and its identity fence; only platform surfaces and HTTP are synthetic.
// This cannot establish browser layout, actual media decoding or provider behavior.
function harness(screen = 'DevicesScreen') {
  const f = { session: session(), play: playback(), calls: [], writes: [], readHook: null, putHook: null };
  const household = { user: f.session.user, online: true, identityKey: signature(f.session), refresh: async () => {}, mutate: async () => { throw new Error('unexpected mutation'); } };
  const props = { user: f.session.user, state: { people: [{ id: 'member1', name: '本人' }] }, onNavigate() {} };
  let values = [], cleanups = [], cursor = 0, dirty = true, tree, dead = false, timerId = 0;
  const effects = [], listeners = new Map(), timers = new Map();
  const same = (a, b) => a?.length === b?.length && a.every((v, i) => Object.is(v, b[i]));
  const react = {
    createElement(type, props, ...children) { return { type, props: { ...props, children: children.flat(Infinity) } }; },
    useRef(value) { const i = cursor++; return values[i] ||= { current: value }; },
    useState(value) { const i = cursor++; if (!(i in values)) values[i] = typeof value === 'function' ? value() : value;
      return [values[i], value => { const next = typeof value === 'function' ? value(values[i]) : value; if (!Object.is(next, values[i])) { values[i] = next; dirty = true; } }]; },
    useEffect(fn, deps) { const i = cursor++; if (!same(values[i], deps)) { values[i] = deps; effects.push(() => { cleanups[i]?.(); cleanups[i] = fn(); }); } },
    useCallback(fn, deps) { const i = cursor++; if (!same(values[i]?.deps, deps)) values[i] = { deps, fn }; return values[i].fn; },
  };
  const events = { addEventListener(name, fn) { if (!listeners.has(name)) listeners.set(name, new Set()); listeners.get(name).add(fn); }, removeEventListener(name, fn) { listeners.get(name)?.delete(fn); } };
  const document = { hidden: false, hasFocus: () => true, ...events }, navigator = { onLine: true };
  const timersApi = { setTimeout(fn, ms) { const key = ++timerId; timers.set(key, { fn, ms }); return key; }, clearTimeout(key) { timers.delete(key); },
    setInterval(fn, ms) { const key = ++timerId; timers.set(key, { fn, ms, interval: true }); return key; }, clearInterval(key) { timers.delete(key); } };
  async function request(path, options = {}) {
    const method = options.method || 'GET'; f.calls.push({ path, method });
    if (path === '/me') return copy(f.session);
    if (path === '/devices') return [{ id, name: '合成电视', focus: 'member1', calendarView: 'today', revision: 1, created_at: '2026-09-20', layout: layout() }];
    if (path === '/media-playback/devices/' + id) {
      if (method === 'GET') { if (f.readHook) await f.readHook(); return copy(f.play); }
      assert.equal(method, 'PUT'); const body = JSON.parse(options.body); f.writes.push(body);
      if (f.putHook) await f.putHook(body);
      if (body.revision !== f.play.revision) throw new ApiError('synthetic conflict', 409);
      f.play = { ...f.play, revision: f.play.revision + 1, ...(body.action === 'pause' ? { paused: true } : body.action === 'resume' ? { paused: false } : {}),
        ...(body.action === 'interval' ? { intervalSeconds: body.intervalSeconds } : {}) };
      if (f.losePut) throw new ApiError('synthetic response lost', 503);
      return copy(f.play);
    }
    if (path === '/accounts') return { accounts: [{ id: 'b'.repeat(32), provider: 'google', name: '合成来源', capabilities: { photos: true } }] };
    if (path === '/journeys') return { journeys: [] };
    if (path.startsWith('/media/items?')) return { items: [], total: 0, hasMore: false };
    if (path.startsWith('/media/imports?')) return { items: [] };
    throw new Error('unexpected request ' + path);
  }
  const compound = name => Object.assign(name === 'Dialog' ? () => null : {}, { Title: name + '.Title', ScrollArea: name + '.ScrollArea', Actions: name + '.Actions', Content: name + '.Content', Item: name + '.Item', Accordion: name + '.Accordion' });
  const paper = { useTheme: () => ({ colors: { error: '#a00', onSurfaceVariant: '#666', onSurface: '#111', surface: '#fff', primary: '#06f' } }),
    ...Object.fromEntries(['ActivityIndicator', 'Button', 'Divider', 'Portal', 'Text', 'TextInput', 'Icon', 'TouchableRipple', 'ProgressBar', 'SegmentedButtons'].map(name => [name, name])),
    Dialog: compound('Dialog'), List: compound('List'), Menu: compound('Menu'), Card: compound('Card') };
  const mocks = { react, 'react-native': { AppState: { currentState: 'active', addEventListener(name, fn) { events.addEventListener(name, fn); return { remove() { events.removeEventListener(name, fn); } }; } },
    Platform: { OS: 'web' }, useWindowDimensions: () => ({ width: 390, height: 844 }), StyleSheet: { create: value => value }, View: 'View', ScrollView: 'ScrollView', Image: 'Image' },
    'expo-router': { useFocusEffect: fn => react.useEffect(fn, [fn]) }, 'react-native-paper': paper,
    '../lib/household': { useHousehold: () => household }, '../lib/api': { ApiError, request },
    '../lib/navigation': { openPhotosProvider() { throw new Error('no provider'); } }, '../ui/components': { EmptyState: 'EmptyState', PageHeader: 'PageHeader', SectionCard: 'SectionCard' },
    '../components/PhotoJourneySuggestions': { default: 'PhotoJourneySuggestions' }, '../components/MemberVideoPlayer': { default: 'MemberVideoPlayer' } };
  const cache = new Map();
  function load(path) {
    path = resolve(path); if (!existsSync(path)) path += existsSync(path + '.ts') ? '.ts' : '.tsx';
    if (cache.has(path)) return cache.get(path);
    const exports = {}; cache.set(path, exports);
    const js = ts.transpileModule(readFileSync(path, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true } }).outputText;
    runInNewContext(js, { exports, require: name => name in mocks ? mocks[name] : load(resolve(dirname(path), name)),
      URL, Blob, Uint8Array, TextDecoder, AbortController, Date, Error, crypto: webcrypto, process: { env: {} }, document, navigator, window: events, ...timersApi });
    return exports;
  }
  const exported = load(resolve(root, 'screens/' + screen + '.tsx')).default;
  const workspace = exported(props), Component = workspace.type, componentProps = workspace.props;
  function walk(node) {
    if (!node || typeof node !== 'object') return [];
    if (typeof node.type === 'function' && node.type.name === 'SelectionRow') return walk(node.type(node.props));
    return [node, ...(node.props.children || []).flatMap(n => walk(n)), ...['action', 'anchor'].flatMap(key => walk(node.props[key]))];
  }
  const nodes = (node = tree) => walk(node);
  const text = (node = tree) => typeof node === 'string' ? node : !node || typeof node !== 'object' ? '' : (node.props.children || []).map(text).join(' ');
  async function flush() { for (let i = 0; i < 35; i++) { if (dirty && !dead) { dirty = false; cursor = 0; tree = Component(componentProps); while (effects.length) effects.shift()(); } await new Promise(setImmediate); } }
  const button = label => { const found = nodes().find(n => n.type === 'Button' && (n.props.accessibilityLabel || text(n).trim()) === label); assert(found, 'missing button: ' + label + ' in ' + text()); return found; };
  async function click(label) { const found = button(label); assert(!found.props.disabled, label + ' disabled'); found.props.onPress(); await flush(); }
  function close() { dead = true; cleanups.forEach(fn => fn?.()); }
  return { f, household, props, nodes, text, click, button, flush, close,
    async event(name) { if (name === 'offline') navigator.onLine = false; if (name === 'online') navigator.onLine = true; for (const fn of listeners.get(name) || []) fn({}); await flush(); },
    async tick() { for (const timer of [...timers.values()]) if (timer.interval) timer.fn(); await flush(); },
    async interval(value) { const input = nodes().find(n => n.type === 'TextInput' && n.props.accessibilityLabel === '照片间隔（秒）'); assert(input); input.props.onChangeText(value); await flush(); } };
}

async function opened(t) { const h = harness(); t.after(h.close); await h.flush(); await h.click('播放控制：合成电视'); return h; }

test('automatic TV advance is read before the first explicit pause without requiring manual refresh', async t => {
  const h = await opened(t); h.f.play = { ...h.f.play, revision: 2, position: 1 };
  h.f.calls.length = 0; await h.click('暂停播放');
  assert.deepEqual(h.f.writes, [{ revision: 2, action: 'pause' }]); assert.equal(h.f.play.paused, true);
  assert.deepEqual(h.f.calls.slice(0, 6), [
    { path: '/me', method: 'GET' }, { path: '/media-playback/devices/' + id, method: 'GET' }, { path: '/me', method: 'GET' },
    { path: '/me', method: 'GET' }, { path: '/media-playback/devices/' + id, method: 'PUT' }, { path: '/me', method: 'GET' }]);
  assert(!h.nodes().some(n => n.props.testID === 'device-operation-unknown'));
});

test('preflight locks duplicate clicks and keeps the explicit pause even if the fresh state is already paused', async t => {
  const h = await opened(t), delayed = gate(); const oldPress = h.button('暂停播放').props.onPress;
  h.f.readHook = () => delayed.promise; h.f.play = { ...h.f.play, revision: 4, paused: true };
  oldPress(); oldPress(); await h.flush(); assert.equal(h.f.writes.length, 0); assert(h.button('暂停播放').props.disabled);
  delayed.release(); await h.flush(); assert.deepEqual(h.f.writes, [{ revision: 4, action: 'pause' }]);
});

for (const mode of ['read-error', 'identity', 'offline']) test('preflight ' + mode + ' sends no write and does not invent an unknown command', async t => {
  const h = await opened(t), delayed = gate(); h.f.readHook = async () => {
    if (mode === 'read-error') throw new ApiError('synthetic unavailable', 503);
    if (mode === 'identity') h.f.session.user = { ...h.f.session.user, id: 'member2' };
    if (mode === 'offline') await delayed.promise;
  };
  await h.click('暂停播放');
  if (mode === 'offline') { await h.event('offline'); delayed.release(); await h.flush(); }
  assert.equal(h.f.writes.length, 0); assert(!h.nodes().some(n => n.props.testID === 'device-operation-unknown'));
  if (mode === 'read-error') { h.f.readHook = null; await h.click('暂停播放'); assert.equal(h.f.writes.length, 1); }
});

test('concurrent change after the fresh read still returns a single CAS conflict without retry', async t => {
  const h = await opened(t); h.f.putHook = () => { ++h.f.play.revision; };
  await h.click('暂停播放'); assert(h.text().includes('未自动重发'));
  await h.tick(); assert.equal(h.f.writes.length, 1); assert(h.button('暂停播放').props.disabled);
  assert(h.text().includes('请先刷新，再明确操作'));
});

test('committed response loss keeps the original unknown operation; recovery only reads until acknowledgment', async t => {
  const h = await opened(t); h.f.losePut = true; await h.click('暂停播放');
  assert.equal(h.f.play.paused, true); assert.equal(h.f.writes.length, 1);
  assert(h.nodes().some(n => n.props.testID === 'device-operation-unknown'));
  await h.tick(); assert.equal(h.f.writes.length, 1);
  await h.click('核对操作结果'); assert.equal(h.f.writes.length, 1);
  await h.click('我已核对当前状态'); assert.equal(h.f.writes.length, 1); assert(h.button('继续播放'));
});

test('interval save preserves the explicit input through the guarded playback preflight', async t => {
  const h = await opened(t); await h.interval('27'); h.f.play.revision = 3;
  const delayed = gate(); h.f.readHook = () => delayed.promise; await h.click('保存照片间隔');
  assert.equal(h.f.writes.length, 0); delayed.release(); await h.flush();
  assert.deepEqual(h.f.writes, [{ revision: 3, action: 'interval', intervalSeconds: 27 }]);
});

test('PhotosScreen uses real SelectionRow checked and disabled state with its original consent label', async t => {
  const h = harness('PhotosScreen'); t.after(h.close); await h.flush(); await h.click('选择照片');
  const consent = () => h.nodes().find(n => n.props.accessibilityRole === 'checkbox' && n.props.accessibilityLabel.startsWith('允许临时处理'));
  assert(consent()); assert.equal(consent().props['aria-checked'], false); assert.equal(consent().props['aria-disabled'], false);
  consent().props.onPress(); await h.flush(); assert.equal(consent().props['aria-checked'], true);
  const pending = gate(); h.household.mutate = () => pending.promise; await h.click('开始选择照片');
  assert.equal(consent().props['aria-disabled'], true); consent().props.onPress(); await h.flush(); assert.equal(consent().props['aria-checked'], true);
});
