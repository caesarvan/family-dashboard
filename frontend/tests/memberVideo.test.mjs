import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { runInNewContext } from 'node:vm';

const require = createRequire(import.meta.url), ts = require('typescript');
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../src');
function loader(mocks = {}, globals = {}) {
  const cache = new Map();
  function load(path) {
    path = resolve(path); if (!existsSync(path)) path += existsSync(path + '.ts') ? '.ts' : '.tsx';
    if (cache.has(path)) return cache.get(path);
    const exports = {}; cache.set(path, exports);
    const js = ts.transpileModule(readFileSync(path, 'utf8'), { compilerOptions: {
      module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true,
    } }).outputText;
    runInNewContext(js, { exports, require: name => name in mocks ? mocks[name] : load(resolve(dirname(path), name)),
      URL, Blob, Uint8Array, AbortController, Date, Error, setTimeout, clearTimeout, setInterval, clearInterval,
      process: { env: {} }, ...globals });
    return exports;
  }
  return load;
}
const load = loader(), photos = load(resolve(root, 'lib/photos.ts')), tripPhotos = load(resolve(root, 'lib/tripPhotos.ts'));
const id = 'a'.repeat(24), journeyId = 'b'.repeat(24), tripId = 'c'.repeat(24);
const item = { id, revision: 1, caption: '合成家庭视频', width: 160, height: 90,
  visibility: 'private', canManage: true, createdAt: '2026-09-20T00:00:00Z', journey: { id: journeyId, tripId, title: '合成旅行' },
  previewUrl: `/api/media/items/${id}/preview`, mediaType: 'video', videoUrl: `/api/media/items/${id}/video`, durationMs: 1400, hasAudio: true };
const session = { user: { role: 'member', id: 'alice', householdId: 'home', auth_version: 1 }, csrf: 'synthetic-only' };
const copy = value => JSON.parse(JSON.stringify(value));
const deferred = () => { let release; return { promise: new Promise(resolve => { release = resolve; }), release: () => release() }; };
const response = (chunks = [new Uint8Array([0, 1, 2, 3])], headers = {}, status = 200) => new Response(new ReadableStream({
  start(controller) { chunks.forEach(value => controller.enqueue(value)); controller.close(); },
}), { status, headers: { 'Content-Type': 'video/mp4', ...headers } });

test('video DTO is strict; legacy photos still work and travel projection retains only validated video fields', () => {
  const legacy = { ...item }; for (const key of ['mediaType', 'videoUrl', 'durationMs', 'hasAudio']) delete legacy[key];
  assert.equal(photos.validatePhoto(legacy), legacy);
  for (const patch of [{ videoUrl: 'https://private.invalid/video' }, { videoUrl: item.videoUrl + '?token=x' },
    { videoUrl: item.videoUrl.replace('/media/', '/media-tv/') }, { durationMs: 600251 }, { durationMs: 1.5 }, { hasAudio: undefined }, { mediaType: 'unknown' }]) {
    assert.throws(() => photos.validatePhoto({ ...item, ...patch }));
  }
  const projected = tripPhotos.readTripPhoto({ ...item, accountId: 'PRIVATE', displayFilename: 'PRIVATE' }, journeyId, id);
  assert.equal(projected.videoUrl, item.videoUrl); assert.equal(projected.durationMs, 1400); assert.equal(projected.hasAudio, true);
  assert(!('accountId' in projected)); assert(!('displayFilename' in projected));
  assert.equal(photos.videoDescription(item), '视频 · 0:02 · 有声音');
});
test('full video request is same-origin, no Range, no redirect and preserves MP4 bytes', async () => {
  let call; const blob = await photos.fetchMemberVideo(item, new AbortController().signal, async (...args) => { call = args; return response(); });
  assert.equal(call[0], item.videoUrl); assert.equal(call[1].mode, 'same-origin'); assert.equal(call[1].redirect, 'error');
  assert.equal(call[1].cache, 'no-store'); assert(!('Range' in call[1].headers));
  assert.equal(blob.type, 'video/mp4'); assert.deepEqual([...new Uint8Array(await blob.arrayBuffer())], [0, 1, 2, 3]);
});
test('invalid MIME, partial response, empty and truncated bodies fail without publishing a Blob', async () => {
  for (const make of [() => response([], {}, 200), () => response(undefined, {}, 206),
    () => response(undefined, { 'Content-Type': 'text/html' }), () => response(undefined, { 'Content-Length': '5' }),
    () => response(undefined, { 'Content-Length': '-1' }), () => response(undefined, { 'Content-Length': String(photos.MAX_VIDEO_BYTES + 1) })]) {
    await assert.rejects(photos.fetchMemberVideo(item, new AbortController().signal, async () => make()));
  }
});
test('unknown-length stream enforces 64 MiB and cancels unread data; abort cannot return a Blob', async () => {
  let cancelled = false, n = 0;
  const stream = new ReadableStream({ pull(controller) { controller.enqueue(new Uint8Array(1024 * 1024)); n++; }, cancel() { cancelled = true; } });
  await assert.rejects(photos.fetchMemberVideo(item, new AbortController().signal, async () => new Response(stream, { headers: { 'Content-Type': 'video/mp4' } })), /64 MiB/);
  assert(cancelled); assert(n <= 67);
  const controller = new AbortController(); controller.abort();
  await assert.rejects(photos.fetchMemberVideo(item, controller.signal, async () => response()));
});
test('video confirmation uses original immutable media IDs/revision/request receipt and remains explicit', () => {
  const row = { canConfirm: true, state: 'awaiting_confirmation', revision: 3 };
  const ids = [id], key = 'original-confirm-request'; const body = photos.confirmPhotos(row, ids, key); ids.length = 0;
  assert.equal(body.confirmRequestId, key); assert.deepEqual([...body.itemIds], [id]); assert.equal(body.revision, 3);
  assert.equal(body.persistSelected, true); assert(!('visibility' in body));
});

// Real component functions/hooks and PhotoReadFence, synthetic HTTP transport.
// This is not a browser/video decoder acceptance test.
function harness(options = {}) {
  const f = { session: copy(session), item: copy(item), calls: [], created: [], revoked: [], mutations: [],
    meCount: 0, detailCount: 0, videoCount: 0, pauseCount: 0, removed: 0, loads: 0, ...options };
  const household = { online: true, identityKey: photos.photoSignature(f.session) };
  const props = { item: copy(item), user: f.session.user, identityKey: household.identityKey, enabled: true };
  let values = [], cleanups = [], cursor = 0, dirty = true, tree, dead = false, timerId = 0;
  const effects = [], listeners = new Map(), timers = new Map();
  const same = (a, b) => a?.length === b?.length && a.every((v, i) => Object.is(v, b[i]));
  const react = {
    createElement(type, props, ...children) { return { type, props: { ...props, children: children.flat(Infinity) } }; },
    useRef(value) { const i = cursor++; return values[i] ||= { current: value }; },
    useState(value) { const i = cursor++; if (!(i in values)) values[i] = typeof value === 'function' ? value() : value;
      return [values[i], value => { const next = typeof value === 'function' ? value(values[i]) : value; if (!Object.is(next, values[i])) { values[i] = next; dirty = true; } }]; },
    useEffect(fn, deps) { const i = cursor++; if (!same(values[i], deps)) { values[i] = deps; effects.push(() => { cleanups[i]?.(); cleanups[i] = fn(); }); } },
  };
  const events = { addEventListener(name, fn) { if (!listeners.has(name)) listeners.set(name, new Set()); listeners.get(name).add(fn); }, removeEventListener(name, fn) { listeners.get(name)?.delete(fn); } };
  const document = { hidden: false, ...events }, navigator = { onLine: true };
  const timersApi = { setTimeout(fn, ms) { const id = ++timerId; timers.set(id, { fn, ms, interval: false }); return id; },
    clearTimeout(id) { timers.delete(id); }, setInterval(fn, ms) { const id = ++timerId; timers.set(id, { fn, ms, interval: true }); return id; }, clearInterval(id) { timers.delete(id); } };
  const element = { pause() { f.pauseCount++; }, removeAttribute(name) { assert.equal(name, 'src'); f.removed++; }, load() { f.loads++; } };
  async function request(path) {
    f.calls.push(path);
    if (path === '/me') { f.meCount++; if (f.changeOnMe === f.meCount) f.session = { ...f.session, user: { ...f.session.user, id: 'bob' } }; return copy(f.session); }
    if (path === '/media/items/' + id) { f.detailCount++; if (f.denied) throw new Error('synthetic denied'); return { item: copy(f.item) }; }
    throw new Error('unexpected request ' + path);
  }
  const ui = loader({ react, 'react-native': { Platform: { OS: options.native ? 'ios' : 'web' }, View: 'View',
    AppState: { currentState: 'active', addEventListener(_name, fn) { events.addEventListener('app', fn); return { remove() { events.removeEventListener('app', fn); } }; } } },
    'react-native-paper': { Text: 'Text', Button: 'Button' }, '../lib/household': { useHousehold: () => household }, '../lib/api': { request } },
    { document, window: events, navigator, ...timersApi,
      URL: { createObjectURL(blob) { f.created.push(blob); return 'blob:synthetic-' + f.created.length; }, revokeObjectURL(value) { f.revoked.push(value); } },
      fetch: async (path, init) => { f.calls.push(path); f.videoCount++; f.lastSignal = init.signal; if (f.gate) await f.gate.promise; return response(); } });
  const Component = ui(resolve(root, 'components/MemberVideoPlayer.tsx')).default;
  function nodes(node = tree) { if (!node || typeof node !== 'object') return []; return [node, ...node.props.children.flatMap(n => nodes(n))]; }
  const text = (node = tree) => typeof node === 'string' ? node : !node || typeof node !== 'object' ? '' : node.props.children.map(text).join(' ');
  async function flush() { for (let i = 0; i < 40; i++) { if (dirty && !dead) { dirty = false; cursor = 0; const oldPlayer = nodes().find(n => n.type === 'video'); tree = Component(props); const player = nodes().find(n => n.type === 'video'); if (oldPlayer && !player) oldPlayer.props.ref(null); if (player) player.props.ref(element); while (effects.length) effects.shift()(); } await new Promise(setImmediate); } }
  async function click(label) { const button = nodes().find(n => n.type === 'Button' && text(n).trim() === label); assert(button, label); assert(!button.props.disabled, label + ' disabled'); button.props.onPress(); await flush(); }
  function close() { dead = true; nodes().find(n => n.type === 'video')?.props.ref(null); cleanups.forEach(fn => fn?.()); }
  return { f, props, household, nodes, text, click, flush, close,
    async event(name) { if (name === 'offline') navigator.onLine = false; if (name === 'online') navigator.onLine = true; if (name === 'visibilitychange') document.hidden = true;
      for (const fn of listeners.get(name) || []) fn({}); await flush(); },
    async tick() { for (const timer of [...timers.values()]) if (timer.interval) timer.fn(); await flush(); },
    async change(fn) { fn(); dirty = true; await flush(); } };
}
test('actual player waits for explicit click, fences metadata and bytes, then offers browser controls', async t => {
  const h = harness(); t.after(h.close); await h.flush(); assert.equal(h.f.videoCount, 0); await h.click('播放视频');
  assert.equal(h.f.videoCount, 1); assert.deepEqual(h.f.calls, ['/me', '/media/items/' + id, item.videoUrl, '/media/items/' + id, '/me']);
  assert.equal(h.f.created.length, 1); const player = h.nodes().find(n => n.type === 'video');
  assert(player.props.controls && player.props.playsInline && player.props.disablePictureInPicture); assert(!player.props.autoPlay);
  await h.click('停止播放'); assert.deepEqual(h.f.revoked, ['blob:synthetic-1']); assert(h.f.pauseCount && h.f.removed && h.f.loads);
});
for (const event of ['offline', 'visibilitychange', 'pagehide']) test('actual player stops and releases bytes on ' + event, async t => {
  const h = harness(); t.after(h.close); await h.flush(); await h.click('播放视频'); await h.event(event);
  assert.equal(h.nodes().filter(n => n.type === 'video').length, 0); assert.equal(h.f.revoked.length, 1); assert.equal(h.f.videoCount, 1);
});
test('unmount and verified identity change revoke existing playback without a new download', async () => {
  for (const mode of ['unmount', 'identity']) {
    const h = harness(); await h.flush(); await h.click('播放视频');
    if (mode === 'unmount') h.close(); else { await h.change(() => { h.household.identityKey = 'another-user'; }); h.close(); }
    assert.equal(h.f.revoked.length, 1); assert.equal(h.f.videoCount, 1); assert(h.f.pauseCount > 0); assert(h.f.removed > 0);
  }
});
test('late video bytes after offline and post-read identity changes cannot publish any Blob URL', async t => {
  for (const mode of ['offline', 'identity']) {
    const gate = deferred(), h = harness({ gate, ...(mode === 'identity' ? { changeOnMe: 2 } : {}) }); t.after(h.close);
    await h.flush(); await h.click('播放视频'); assert.equal(h.f.created.length, 0);
    if (mode === 'offline') await h.event('offline'); gate.release(); await h.flush();
    assert.equal(h.f.created.length, 0); assert.equal(h.f.videoCount, 1);
  }
});
test('changed revision or revoked ACL during the next permission read stops the original Blob', async t => {
  for (const mode of ['revision', 'revoke']) {
    const h = harness(); t.after(h.close); await h.flush(); await h.click('播放视频');
    if (mode === 'revision') h.f.item.revision++; else h.f.denied = true;
    await h.tick(); assert.equal(h.f.revoked.length, 1); assert.equal(h.f.videoCount, 1); assert(h.text().includes('已停止'));
  }
});
test('native fallback is explicit and sends no media request', async t => {
  const h = harness({ native: true }); t.after(h.close); await h.flush(); assert(h.text().includes('浏览器')); assert.equal(h.f.calls.length, 0);
});
