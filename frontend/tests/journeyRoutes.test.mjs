import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { runInNewContext } from 'node:vm';
const require = createRequire(import.meta.url), ts = require('typescript');
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../src');
const clone = v => JSON.parse(JSON.stringify(v));
function loader(mocks = {}, globals = {}) {
  const cache = new Map();
  function load(path) {
    path = resolve(path); if (!existsSync(path)) path += existsSync(path + '.ts') ? '.ts' : '.tsx';
    if (cache.has(path)) return cache.get(path);
    const exports = {}; cache.set(path, exports);
    const js = ts.transpileModule(readFileSync(path, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
    runInNewContext(js, { exports, require: name => name in mocks ? mocks[name] : load(resolve(dirname(path), name)), Date, Intl, Error, URLSearchParams, AbortController, setTimeout, clearTimeout, ...globals });
    return exports;
  }
  return load;
}
const load = loader(), api = load(resolve(root, 'lib/journeyRoutes.ts')), placeApi = load(resolve(root, 'lib/places.ts'));
const journeyId = '1'.repeat(24), tripId = '2'.repeat(24), routeId = '3'.repeat(24), requestId = 'a'.repeat(32);
const source = { id: journeyId, tripId, revision: 4, plan: { title: '合成旅行', start: '2026-09-01', end: '2026-09-10', destinations: [{ key: 'city', city: '合成城市', country: '', arrival: '2026-09-01', departure: '2026-09-10' }] } };
function place(n = 4, lng = 12.345678, disclosure = 'coarse') {
  return { id: String(n).repeat(24), owner: 'member1', name: '地点' + n, country: '', city: '城市', coordinates: { latitude: 45.123456, longitude: lng }, coordinatePrecision: 'exact', coordinateGridDegrees: null,
    sharedCoordinates: disclosure === 'hidden' ? null : { latitude: 45.1, longitude: Math.round(lng * 10) / 10 }, sharedCoordinatePrecision: disclosure === 'hidden' ? 'hidden' : 'approximate',
    coordinateDisclosure: disclosure, status: 'planned', visibility: 'shared', journeyId, journey: { id: journeyId, tripId, title: '合成旅行' }, startDate: null, endDate: null, revision: 1, canManage: true,
    visitedConfirmedAt: null, visitedConfirmedBy: null, createdAt: '2026-09-01T00:00:00Z', updatedAt: '2026-09-01T00:00:00Z' };
}
function detail(stops = [place(), place(5, -170)], shared = false, manage = true) {
  const values = stops.map((p, index) => p === null ? { index, state: 'unavailable' } : { index, state: 'available', place: shared ? api.publicRoutePlace(p) : p });
  return { route: { id: routeId, title: '往返路线', journeyId, visibility: shared ? 'shared' : 'private', revision: 1, canManage: manage, sourceVersion: 'b'.repeat(64), stops: values }, segments: clone(api.adjacentRouteSegments(values)) };
}
function receipt(intent, current, replayed = false) { return { operation: { requestId: intent.body.requestId, kind: intent.method === 'DELETE' ? 'delete' : intent.method === 'PUT' ? 'update' : 'create', routeId, resultRevision: intent.method === 'DELETE' ? 2 : current?.route.revision || 1, completedAt: '2026-09-19T12:00:00Z' }, replayed, current }; }

test('DTO preserves repeated stations and opaque unavailable slots; rejects non-adjacent/missing-coordinate segments', () => {
  const d = detail([place(), null, place(), place(5)]); const parsed = api.readRouteDetail(d, journeyId, routeId);
  assert.deepEqual(clone(parsed.route.stops.map(s => s.state)), ['available', 'unavailable', 'available', 'available']); assert.equal(parsed.route.stops[0].place.id, parsed.route.stops[2].place.id);
  for (const mutate of [r => r.segments.push({ fromIndex: 0, toIndex: 2 }), r => r.route.stops[1].placeId = 'secret', r => r.route.stops[0].index = 8, r => r.route.sourceVersion = 'x', r => r.route.canManage = false]) {
    const r = clone(d); mutate(r); assert.throws(() => api.readRouteDetail(r, journeyId));
  }
});
test('shared projections never retain author precision/extras; reject exact coordinate smuggling', () => {
  const d = detail([place(), place(5, 90, 'hidden')], true);
  const r = api.readRouteDetail(d, journeyId); assert.equal(r.route.stops[0].place.coordinates.latitude, 45.1); assert.equal(r.route.stops[1].place.coordinates, null);
  assert(!JSON.stringify(r).includes('45.123456')); assert(!('sharedCoordinates' in r.route.stops[0].place));
  for (const modify of [p => p.canManage = true, p => p.coordinates.latitude = 45.123456, p => p.coordinatePrecision = 'exact']) { const v = clone(d); modify(v.route.stops[0].place); assert.throws(() => api.readRouteDetail(v, journeyId)); }
});
test('geometry splits both antimeridian directions and never bridges a hidden or unavailable station', () => {
  for (const [a, b] of [[170, -170], [-170, 170]]) {
    const d = detail([place(4, a), place(5, b)]); const map = api.routeGeometry(d.route.stops, d.segments);
    assert.equal(map.lines.length, 2); assert(map.lines.every(l => Math.abs(l.to.longitude - l.from.longitude) <= 10));
    assert.equal(Math.abs(map.lines[0].to.longitude), 180); assert.equal(map.lines[0].to.longitude, -map.lines[1].from.longitude);
  }
  const hidden = { ...place(5), coordinates: null, coordinatePrecision: 'hidden' }, d = detail([place(), hidden, place(6), null, place(7)]);
  assert.equal(api.routeGeometry(d.route.stops, [{ fromIndex: 0, toIndex: 2 }, { fromIndex: 2, toIndex: 4 }, { fromIndex: 0, toIndex: 1 }]).lines.length, 0);
});
test('geometry numbers repeated coordinates together, marks coarse lines, and handles equal ±180 meridians', () => {
  const d = detail([place(4, 180), place(5, -180), place(4, 180)], true), map = api.routeGeometry(d.route.stops, d.segments);
  assert.deepEqual(clone(map.markers[0].indices), [0, 2]); assert(map.lines.every(l => l.approximate && Number.isFinite(l.to.latitude) && l.from.longitude === l.to.longitude));
});

test('route viewport separates nearby roundtrip stations at phone and desktop CSS sizes', () => {
  const a = { ...place(), coordinates: { latitude: 31.234567, longitude: 121.456789 } }, b = { ...place(5), coordinates: { latitude: 32.234567, longitude: 122.456789 } };
  const d = detail([a, a, b]), map = api.routeGeometry(d.route.stops, d.segments), original = clone(map);
  for (const [width, height] of [[318, 240], [1176, 360]]) {
    const focused = api.routeMapLayout(map, width, height), world = api.routeMapLayout(map, width, height, true);
    assert(focused.viewport.width < 30); assert(focused.scale > world.scale * 20);
    assert.deepEqual(clone(focused.markers.map(m => m.label)), ['1、2', '3']);
    assert(Math.abs(focused.markers[0].point.y - focused.markers[1].point.y) >= 120);
    for (const marker of focused.markers) {
      assert(marker.point.x - marker.width / 2 >= 0 && marker.point.x + marker.width / 2 <= width);
      assert(marker.point.y >= 18 && marker.point.y <= height - 18);
    }
  }
  assert.deepEqual(clone(map), original);
});

test('route viewport fits both antimeridian directions without reversing or lengthening split lines', () => {
  for (const [a, b] of [[179, -179], [-179, 179], [180, -180]]) {
    const d = detail([place(4, a), place(5, b)]), map = api.routeGeometry(d.route.stops, d.segments), fit = api.routeMapLayout(map, 318, 240);
    assert(!fit.global); assert(fit.viewport.width < 30); assert.equal(fit.lines.length, map.lines.length);
    for (const line of fit.lines) for (const point of [line.from, line.to]) assert(point.x >= 55 && point.x <= 263 && point.y >= 55 && point.y <= 185);
    if (a !== 180) { assert.equal(fit.lines.length, 2); assert(Math.abs(fit.lines[0].to.x - fit.lines[1].from.x) < 1e-7); }
    else assert.equal(fit.markers.length, 1);
  }
  const d = detail([place(4, 170), place(5, 0), place(6, -170)]), map = api.routeGeometry(d.route.stops, d.segments), world = api.routeMapLayout(map, 318, 240);
  assert(world.global); // A line traverses the otherwise empty cut: do not attach it to another copy.
  assert(Math.abs(world.lines[0].to.x - world.markers[1].point.x) < 1e-7);
});

test('route viewport keeps empty, singleton, polar and close-point badges finite and never invents gap lines', () => {
  const empty = api.routeMapLayout({ markers: [], lines: [] }, 318, 240); assert(empty.global); assert.equal(empty.markers.length, 0);
  for (const latitude of [-90, 90]) {
    const p = { ...place(), coordinates: { latitude, longitude: 20 } }, d = detail([p, p, p]), map = api.routeGeometry(d.route.stops, d.segments), fit = api.routeMapLayout(map, 318, 240);
    assert(fit.viewport.height >= 500 / 180); assert.equal(fit.markers[0].label, '1、2、3'); assert(Math.abs(fit.markers[0].point.y - 120) < 1e-7);
  }
  const a = place(), b = { ...place(5), coordinates: { ...place().coordinates, longitude: place().coordinates.longitude + 0.00001 } };
  const d = detail([a, null, b]), fit = api.routeMapLayout(api.routeGeometry(d.route.stops, d.segments), 318, 240);
  assert.equal(fit.lines.length, 0); assert.equal(fit.markers.length, 1); assert.equal(fit.markers[0].label, '1、3');
  const hidden = detail([{ ...place(), coordinates: null, coordinatePrecision: 'hidden' }, a]);
  const visible = api.routeMapLayout(api.routeGeometry(hidden.route.stops, hidden.segments), 318, 240);
  assert.deepEqual(clone(visible.markers[0].indices), [1]); assert.equal(visible.lines.length, 0);
  const hundred = detail(Array.from({ length: 100 }, () => a)), grouped = api.routeMapLayout(api.routeGeometry(hundred.route.stops, hundred.segments), 318, 240);
  assert.equal(grouped.markers[0].label, '1 +99'); assert.equal(grouped.markers[0].indices.length, 100); assert(grouped.markers[0].width < 100);
  const shared = detail([place(), place(5, 90, 'hidden')], true), sharedMap = api.routeGeometry(shared.route.stops, shared.segments), sharedFit = api.routeMapLayout(sharedMap, 318, 240);
  const publicOnly = api.routeMapLayout(api.routeGeometry([shared.route.stops[0]], []), 318, 240);
  assert.deepEqual(clone(sharedFit.viewport), clone(publicOnly.viewport)); assert(sharedFit.markers[0].approximate); assert.equal(sharedFit.lines.length, 0);
});

test('route web map uses CSS-sized numbers, capped height, keyboard selection and reversible focus; ordinary map unchanged', () => {
  let index = 0; const state = [], selected = [];
  const react = { useState(initial) { const i = index++; if (!(i in state)) state[i] = initial; return [state[i], value => { state[i] = value; }]; },
    useRef: () => ({ current: null }), useEffect: () => {}, createElement: (type, props, ...children) => ({ type, props: { ...props, children: children.flat(Infinity).filter(c => c !== null && c !== undefined && c !== false) } }) };
  const web = loader({ react, 'react-native': { View: 'View' }, 'react-native-paper': { Button: 'Button', Text: 'Text', useTheme: () => ({ colors: {} }) } })(resolve(root, 'ui/WorldMap.web.tsx')).default;
  const a = place(), b = { ...place(5), coordinates: { latitude: 46.123456, longitude: 13.345678 } }, d = detail([a, a, b]), map = api.routeGeometry(d.route.stops, d.segments);
  const render = (routeMap = map, selectedRouteIndex) => { index = 0; return web({ places: [], onSelect() {}, onPick() {}, routeMap, selectedRouteIndex, onRouteSelect: n => selected.push(n) }); };
  const nodes = tree => typeof tree !== 'object' || !tree ? [] : [tree, ...(tree.props?.children || []).flatMap(nodes)];
  let tree = render(); tree.props.onLayout({ nativeEvent: { layout: { width: 318 } } }); tree = render();
  let all = nodes(tree), svg = all.find(n => n.type === 'svg'); assert.equal(svg.props.viewBox, '0 0 318 240'); assert.equal(svg.props.style.height, 240);
  assert.deepEqual(all.filter(n => n.type === 'text').map(n => n.props.children.join('')), ['1、2', '3']); assert(all.filter(n => n.type === 'text').every(n => n.props.fontSize === '14'));
  all.find(n => n.type === 'g' && n.props.role === 'button').props.onKeyDown({ key: 'Enter', preventDefault() {} });
  nodes(render(map, 0)).find(n => n.type === 'g' && n.props.role === 'button').props.onKeyDown({ key: ' ', preventDefault() {} }); assert.deepEqual(selected, [0, 1]);
  all.find(n => n.type === 'Button').props.onPress(); tree = render(); assert.equal(nodes(tree).find(n => n.type === 'Button').props.children.join(''), '聚焦路线');
  nodes(tree).find(n => n.type === 'Button').props.onPress(); tree = render(); assert.equal(nodes(tree).filter(n => n.type === 'text').length, 2);
  tree.props.onLayout({ nativeEvent: { layout: { width: 1176 } } }); tree = render(); assert.equal(nodes(tree).find(n => n.type === 'svg').props.style.height, 360);
  const ordinary = nodes(render(null)), normalSvg = ordinary.find(n => n.type === 'svg'); assert.equal(normalSvg.props.viewBox, '0 0 1000 500'); assert.equal(normalSvg.props.style.aspectRatio, '2 / 1'); assert.equal(normalSvg.props.style.height, undefined); assert(!ordinary.some(n => n.type === 'Button'));
});
test('editing preserves unavailable original index through reorder and never stores place snapshots in draft', () => {
  const r = api.readRouteDetail(detail([place(), null, place(5)]), journeyId).route, draft = api.routeDraft(r, 4);
  assert(!JSON.stringify(draft.original).includes('coordinates')); assert(!JSON.stringify(draft.original).includes('地点'));
  draft.stops = [draft.stops[1], draft.stops[2], draft.stops[0]]; const intent = api.routeWriteIntent(draft, journeyId, requestId);
  assert.deepEqual(clone(intent.body.stops[0]), { keepUnavailableIndex: 1 }); assert.equal(intent.body.sourceVersion, r.sourceVersion);
  draft.stops.push(draft.stops[0]); assert.throws(() => api.routeWriteIntent(draft, journeyId, requestId));
  draft.stops.pop(); draft.visibility = 'shared'; assert.throws(() => api.routeWriteIntent(draft, journeyId, requestId));
});
test('receipt must bind original operation and route, accepts newer current projection and deleted current', () => {
  const d = api.routeDraft(null, 4); d.title = '新路线'; d.stops = [{ placeId: place().id, expectedRevision: 1 }]; const intent = api.routeWriteIntent(d, journeyId, requestId);
  const r = receipt({ body: intent.body, method: 'POST' }, detail()); r.current.route.revision = 3;
  assert.equal(api.readRouteReceipt(r, intent, journeyId).current.route.revision, 3);
  r.current.route.journeyId = 'f'.repeat(24); assert.equal(api.readRouteReceipt(r, intent, journeyId).current, null);
  r.current.route.journeyId = null; assert.equal(api.readRouteReceipt(r, intent, journeyId).current, null);
  r.current = null; assert.equal(api.readRouteReceipt(r, intent, journeyId).current, null);
  r.operation.requestId = 'f'.repeat(32); assert.throws(() => api.readRouteReceipt(r, intent, journeyId));
});
test('identity fence discards late reads and rejects mutation when post-write /me changes', async () => {
  const s = { user: { role: 'member', id: 'one', householdId: 'home', auth_version: 1 }, csrf: 'csrf' };
  const fence = new placeApi.PlaceFence(async () => clone(s), placeApi.placeSignature(s));
  await assert.rejects(fence.run(async () => { s.user.householdId = 'other'; return 'secret'; }, () => true));
  const next = new placeApi.PlaceFence(async () => clone(s), placeApi.placeSignature(s));
  await assert.rejects(next.run(async () => { next.invalidate(); return 'secret'; }, () => true));
});

// Executes production TSX with an in-memory synthetic transport. It is not an API or browser substitute.
function harness(options = {}) {
  const f = { session: { user: { role: 'member', id: 'member1', householdId: 'home1', auth_version: 1 }, csrf: 'synthetic-csrf' }, route: options.route || null, places: [place(), place(5, -170)], calls: [], receipts: new Map(), ...options };
  let dirty = true, closed = false, tree, instance, cursor = 0, typeSequence = 0, back = false;
  const instances = new Map(), typeIds = new Map(), effects = [], listeners = new Map(), timers = new Map();
  const target = { addEventListener(key, fn) { if (!listeners.has(key)) listeners.set(key, new Set()); listeners.get(key).add(fn); }, removeEventListener(key, fn) { listeners.get(key)?.delete(fn); } };
  const document = { hidden: false, hasFocus: () => true, ...target }, window = { ...target }, navigator = { onLine: true };
  const changed = (a, b) => !a || !b || a.length !== b.length || a.some((v, i) => v !== b[i]);
  function useState(initial) { const holder = instance, i = cursor++; if (!(i in holder.slots)) holder.slots[i] = typeof initial === 'function' ? initial() : initial; return [holder.slots[i], value => { if (!holder.dead) { holder.slots[i] = typeof value === 'function' ? value(holder.slots[i]) : value; dirty = true; } }]; }
  function useRef(initial) { const i = cursor++; if (!(i in instance.slots)) instance.slots[i] = { current: initial }; return instance.slots[i]; }
  function useEffect(fn, deps) { const holder = instance, i = cursor++; if (changed(holder.slots[i], deps)) { holder.slots[i] = deps; effects.push(() => { holder.cleanups[i]?.(); if (!holder.dead) holder.cleanups[i] = fn(); }); } }
  function useCallback(fn, deps) { const i = cursor++; if (!instance.slots[i] || changed(instance.slots[i].deps, deps)) instance.slots[i] = { deps, fn }; return instance.slots[i].fn; }
  const react = { useState, useRef, useEffect, useCallback, Fragment: 'Fragment', createElement: (type, props, ...children) => ({ type, props: { ...props, children: children.flat(Infinity).filter(v => v !== undefined && v !== null && v !== false) } }) };
  class ApiError extends Error { constructor(message, status = 0, code = '') { super(message); this.status = status; this.code = code; } }
  const household = { user: f.session.user, identityKey: placeApi.placeSignature(f.session), online: true, refresh: async () => {} };
  async function request(path, init = {}, csrf) {
    const body = init.body ? JSON.parse(init.body) : null, method = init.method || 'GET'; f.calls.push({ path, method, body, csrf });
    if (path === '/me') { if (f.failAfterWrite && f.wrote) throw new ApiError('SESSION DETAILS'); return clone(f.session); }
    if (path === '/journeys/' + journeyId) { if (f.journeyDeleted) throw new ApiError('not found', 404); return { ...clone(source), revision: f.journeyRevision || source.revision }; }
    const url = new URL('https://synthetic.invalid' + path);
    if (url.pathname === '/journey-places') return { items: clone(f.places), offset: 0, limit: 24, total: f.places.length, hasMore: false };
    if (path.startsWith('/journey-places/')) {
      const p = f.places.find(p => p.id === path.split('/').at(-1)); if (!p) throw new ApiError('not found', 404);
      if (f.probeReceipt && f.rejection) { f.route = clone(f.probeReceipt.current); f.receipts.set(f.probeReceipt.operation.requestId, clone(f.probeReceipt)); f.probeReceipt = null; }
      if (f.identityOnProbe && f.rejection) f.session.user.auth_version++;
      return { place: clone(p) };
    }
    if (path.startsWith('/journey-routes/operations/')) { const saved = f.receipts.get(path.split('/').at(-1)); if (!saved) throw new ApiError('not found', 404); return { ...clone(saved), replayed: true, current: clone(f.route) }; }
    if (method !== 'GET') {
      if (f.rejection) throw new ApiError('private server message', f.rejection, f.rejectionCode || '');
      if (f.dropBeforeWrite) throw new ApiError('connection lost before observed acceptance');
      f.wrote = true;
      if (method === 'DELETE') f.route = null;
      else { const chosen = body.stops.map(s => 'placeId' in s ? f.places.find(p => p.id === s.placeId) : null); f.route = detail(chosen, body.visibility === 'shared'); f.route.route.title = body.title; f.route.route.revision = method === 'PUT' ? body.revision + 1 : 1; }
      const value = receipt({ method, body }, f.route); f.receipts.set(body.requestId, clone(value));
      if (f.gate) await f.gate;
      if (f.identityAfterWrite) f.session.user.auth_version++;
      if (f.dropReply) throw new ApiError('lost response');
      return clone(value);
    }
    if (url.pathname === '/journey-routes') { const r = f.route?.route, scope = url.searchParams.get('scope'); const items = r && (scope === 'shared' ? r.visibility === 'shared' : r.canManage) ? [{ id: r.id, title: r.title, journeyId, visibility: r.visibility, revision: r.revision, canManage: r.canManage, stopCount: r.stops.length, unavailableCount: r.stops.filter(s => s.state === 'unavailable').length }] : []; return { items: clone(items), total: items.length, limit: 24, offset: 0, hasMore: false }; }
    if (path === '/journey-routes/' + routeId) { if (!f.route) throw new ApiError('not found', 404); return clone(f.route); }
    throw new Error('Unexpected ' + path);
  }
  const mocks = { react, 'react-native': { AppState: { currentState: 'active', addEventListener: (_key, fn) => { target.addEventListener('app', fn); return { remove: () => target.removeEventListener('app', fn) }; } }, StyleSheet: { create: v => v }, View: 'View' },
    'react-native-paper': { ...Object.fromEntries(['ActivityIndicator', 'Button', 'Divider', 'Text', 'TextInput'].map(k => [k, k])), useTheme: () => ({ colors: { error: 'red' } }) },
    'expo-router': { useFocusEffect: fn => useEffect(fn, [fn]) }, '../lib/api': { ApiError, request }, './api': { ApiError, request }, '../lib/household': { useHousehold: () => household },
    '../lib/trips': { newKey: () => (++f.keys || (f.keys = 1)).toString(16).padStart(32, '0') },
    '../ui/components': { EmptyState: 'EmptyState', SectionCard: 'SectionCard', PageHeader: 'PageHeader' }, '../ui/SelectionRow': { SelectionRow: 'SelectionRow' },
    '../ui/WorldMap': { __esModule: true, default: 'WorldMap' }, './TripRecapPanel': { __esModule: true, default: 'TripRecapPanel' } };
  const uiLoad = loader(mocks, { document, window, navigator, setInterval: fn => { const id = timers.size + 1; timers.set(id, fn); return id; }, clearInterval: id => timers.delete(id) });
  const entry = uiLoad(resolve(root, 'components/JourneyRoutesPanel.tsx')).default;
  const props = { journeyId, onBack: () => { back = true; }, onPlaces: () => { f.openedPlaces = true; } };
  function expand(node, path, seen) {
    if (!node || typeof node !== 'object') return node;
    if (typeof node.type === 'function') {
      if (!typeIds.has(node.type)) typeIds.set(node.type, ++typeSequence); const key = path + ':' + typeIds.get(node.type) + ':' + (node.props.key ?? ''); seen.add(key);
      if (!instances.has(key)) instances.set(key, { slots: [], cleanups: [], dead: false }); instance = instances.get(key); cursor = 0; return expand(node.type(node.props), key, seen);
    }
    // Shared UI components render their action prop too.
    return { ...node, props: { ...node.props, children: [...(node.props.children || []), node.props.action].filter(v => v != null).map((child, i) => expand(child, path + '/' + i, seen)) } };
  }
  function render() { dirty = false; const seen = new Set(); tree = expand(react.createElement(entry, props), 'root', seen); for (const [key, holder] of instances) if (!seen.has(key)) { holder.dead = true; holder.cleanups.forEach(fn => fn?.()); instances.delete(key); } for (const effect of effects.splice(0)) effect(); }
  async function settle() { for (let i = 0; i < 30; i++) { if (dirty && !closed) render(); await new Promise(resolve => setImmediate(resolve)); } }
  function nodes(node = tree) { return !node || typeof node !== 'object' ? [] : [node, ...node.props.children.flatMap(child => nodes(child))]; }
  function text(node = tree) { return typeof node === 'string' || typeof node === 'number' ? String(node) : !node || typeof node !== 'object' ? '' : [node.props.title || '', node.props.description || '', ...node.props.children.map(child => text(child))].join(' '); }
  const control = label => nodes().find(node => ['Button', 'SelectionRow', 'TextInput'].includes(node.type) && (node.props.label === label || node.props.accessibilityLabel === label || text(node).trim().replace(/\s+/g, ' ') === label));
  async function click(label) { const node = control(label); assert(node, 'Missing ' + label + '\n' + text()); assert(!node.props.disabled, 'Disabled ' + label); node.props.onPress(); await settle(); }
  async function input(label, value) { const node = control(label); assert(node && !node.props.disabled, label); node.props.onChangeText(value); await settle(); }
  async function emit(event, value) { for (const fn of [...(listeners.get(event) || [])]) fn(value); await settle(); }
  return { f, household, settle, click, input, nodes, control, text, writes: () => f.calls.filter(c => c.method !== 'GET'), get back() { return back; },
    async hide() { document.hidden = true; await emit('visibilitychange'); }, async show() { document.hidden = false; await emit('visibilitychange'); },
    async blur() { await emit('blur'); }, async focus() { await emit('focus'); },
    async offline() { navigator.onLine = false; household.online = false; await emit('offline'); }, async online() { navigator.onLine = true; household.online = true; await emit('online'); },
    async tick() { for (const fn of [...timers.values()]) fn(); await settle(); },
    close() { closed = true; for (const holder of instances.values()) { holder.dead = true; holder.cleanups.forEach(fn => fn?.()); } } };
}
async function newRoute(h) { await h.settle(); await h.click('新建路线'); await h.input('路线名称', '合成往返'); await h.click('添加站点 地点4'); await h.click('添加站点 地点5'); await h.click('添加站点 地点4'); }

test('new private route supports a repeated stop, reorders then saves exactly that order without altering places', async t => {
  const h = harness(); t.after(h.close); await newRoute(h); await h.click('上移第 3 站'); await h.click('保存路线');
  assert.equal(h.writes().length, 1); const body = h.writes()[0].body; assert.equal(body.visibility, 'private'); assert.deepEqual(body.stops.map(s => s.placeId), [place().id, place().id, place(5).id]);
  assert(!('coordinates' in body)); assert(!('confirmVisited' in body)); assert(!h.control('路线名称')); assert.match(h.text(), /已确认保存/);
  const map = h.nodes().find(n => n.type === 'WorldMap'); assert.deepEqual(clone(map.props.routeMap.markers[0].indices), [0, 1]);
});
test('sharing uses public precision before confirmation and only author can edit/delete', async t => {
  const h = harness(); t.after(h.close); await newRoute(h); await h.click('家庭共享'); assert(h.control('保存路线').props.disabled);
  const map = h.nodes().find(n => n.type === 'WorldMap'); assert.equal(map.props.routeMap.markers[0].point.latitude, 45.1); assert(!JSON.stringify(map).includes('45.123456'));
  await h.click('已核对地点名称与坐标共享范围'); await h.click('保存路线'); assert.equal(h.writes()[0].body.visibility, 'shared');
  const reader = harness({ route: detail([place()], true, false) }); t.after(reader.close); await reader.settle(); await reader.click('家庭共享路线'); await reader.click('查看路线 往返路线');
  assert(!reader.control('编辑路线')); assert(!reader.control('删除路线')); assert.match(reader.text(), /只读/); assert.equal(reader.writes().length, 0);
});
test('lost successful response recovers original request only and renders freshly projected receipt', async t => {
  const h = harness({ dropReply: true }); t.after(h.close); await newRoute(h); await h.click('保存路线'); assert(h.control('核对原操作')); assert(h.control('返回旅行详情').props.disabled);
  h.f.route.route.stops[1] = { index: 1, state: 'unavailable' }; h.f.route.segments = []; await h.click('核对原操作');
  assert.equal(h.writes().length, 1); assert.match(h.text(), /地点已不可用/); assert(!h.control('核对原操作'));
  assert(h.f.calls.some(c => c.path === '/journey-routes/operations/' + h.writes()[0].body.requestId));
});
test('unknown-key retry preserves exact original body and requestId, including after a second rejection', async t => {
  const h = harness({ dropReply: true }); t.after(h.close); await newRoute(h); await h.click('保存路线'); h.f.receipts.clear(); await h.click('核对原操作');
  h.f.rejection = 409; await h.click('按原内容重试'); assert.deepEqual(h.writes()[1].body, h.writes()[0].body); assert(h.control('核对原操作')); assert(!h.control('保存路线') || h.control('保存路线').props.disabled);
});
test('unknown retry 409 plus newer same-place revision and final absent receipt offers explicit draft recovery only', async t => {
  const h = harness({ dropBeforeWrite: true }); t.after(h.close); await newRoute(h); await h.click('保存路线'); await h.click('核对原操作');
  h.f.dropBeforeWrite = false; h.f.rejection = 409; h.f.rejectionCode = 'source_changed'; h.f.places[0].revision++;
  await h.click('按原内容重试'); assert.match(h.text(), /原内容的版本已过期；这次重试未保存/); assert(h.control('保留草稿并重新核对')); assert.equal(h.writes().length, 2);
  assert.deepEqual(h.writes()[1].body, h.writes()[0].body); assert(!h.control('保存路线') || h.control('保存路线').props.disabled);
  await h.click('保留草稿并重新核对'); assert.equal(h.writes().length, 2); assert.equal(h.control('路线名称').props.value, '合成往返'); assert(!h.control('核对原操作')); assert(h.control('保存路线').props.disabled);
  await h.click('按当前地点核对草稿'); h.f.rejection = 0; await h.click('保存路线'); assert.equal(h.writes().length, 3); assert.notEqual(h.writes()[2].body.requestId, h.writes()[0].body.requestId); assert.equal(h.writes()[2].body.stops[0].expectedRevision, 2);
});
test('newer same-route revision can resolve an unknown update without changing its original request', async t => {
  const h = harness({ route: detail(), dropBeforeWrite: true }); t.after(h.close); await h.settle(); await h.click('查看路线 往返路线'); await h.click('编辑路线'); await h.input('路线名称', '保留的修改'); await h.click('保存路线'); await h.click('核对原操作');
  h.f.route.route.revision++; h.f.route.route.sourceVersion = 'c'.repeat(64); h.f.rejection = 409; h.f.rejectionCode = 'revision_conflict'; await h.click('按原内容重试');
  assert(h.control('保留草稿并重新核对')); assert.deepEqual(h.writes()[0].body, h.writes()[1].body); await h.click('保留草稿并重新核对'); assert.equal(h.control('路线名称').props.value, '保留的修改'); assert.equal(h.writes().length, 2);
});
test('equal/lower place versions and newer journey alone cannot release unknown intent', async t => {
  for (const revision of [1, 2]) {
    const h = harness({ dropBeforeWrite: true, places: [ { ...place(), revision: 2 }, { ...place(5, -170), revision: 2 } ] }); t.after(h.close); await newRoute(h); await h.click('保存路线'); await h.click('核对原操作');
    h.f.rejection = 409; h.f.rejectionCode = 'source_changed'; h.f.journeyRevision = 100; h.f.places.forEach(p => { p.revision = revision; }); await h.click('按原内容重试');
    assert(!h.control('保留草稿并重新核对')); assert(h.control('核对原操作')); assert(h.control('返回旅行详情').props.disabled); assert.equal(h.writes().length, 2);
  }
});
test('request_conflict and generic 409 cannot release unknown intent even with a newer place', async t => {
  for (const code of ['', 'request_conflict', 'limit_reached']) {
    const h = harness({ dropBeforeWrite: true }); t.after(h.close); await newRoute(h); await h.click('保存路线'); await h.click('核对原操作'); h.f.rejection = 409; h.f.rejectionCode = code; h.f.places[0].revision++;
    await h.click('按原内容重试'); assert(!h.control('保留草稿并重新核对')); assert(h.control('核对原操作')); assert.equal(h.writes().length, 2);
  }
});
test('receipt appearing during version observation wins over expired inference', async t => {
  const h = harness({ dropBeforeWrite: true }); t.after(h.close); await newRoute(h); await h.click('保存路线'); await h.click('核对原操作');
  h.f.rejection = 409; h.f.rejectionCode = 'source_changed'; h.f.places[0].revision++;
  const written = h.writes()[0], current = detail([h.f.places[0], h.f.places[1], h.f.places[0]]); current.route.title = written.body.title;
  h.f.probeReceipt = receipt(written, current, true); await h.click('按原内容重试');
  assert(!h.control('保留草稿并重新核对')); assert(!h.control('核对原操作')); assert.match(h.text(), /已确认保存/); assert.equal(h.writes().length, 2);
});
test('identity change during expired-version observation clears draft and cannot authorize a new save', async t => {
  const h = harness({ dropBeforeWrite: true }); t.after(h.close); await newRoute(h); await h.click('保存路线'); await h.click('核对原操作');
  h.f.rejection = 409; h.f.rejectionCode = 'source_changed'; h.f.places[0].revision++; h.f.identityOnProbe = true;
  await h.click('按原内容重试'); assert(!h.control('保留草稿并重新核对')); assert(!h.control('路线名称')); assert(!h.control('核对原操作')); assert(!h.nodes().some(n => n.type === 'WorldMap'));
});
test('409 keeps draft and requires current-source review rather than silently resubmitting', async t => {
  const h = harness({ rejection: 409 }); t.after(h.close); await newRoute(h); await h.click('保存路线'); assert.equal(h.control('路线名称').props.value, '合成往返'); assert(h.control('保存路线').props.disabled);
  h.f.rejection = 0; h.f.places[0].revision = 2; await h.click('读取最新内容'); await h.click('按当前地点核对草稿'); await h.click('保存路线');
  assert.equal(h.writes()[1].body.stops[0].expectedRevision, 2); assert.notEqual(h.writes()[0].body.requestId, h.writes()[1].body.requestId);
});
test('background and offline hide coordinates, foreground rechecks latest projection and invalidates sharing review', async t => {
  const h = harness(); t.after(h.close); await newRoute(h); await h.click('家庭共享'); await h.click('已核对地点名称与坐标共享范围'); await h.hide(); assert(!h.control('路线名称')); assert(!h.nodes().some(n => n.type === 'WorldMap'));
  h.f.places[0].coordinateDisclosure = 'hidden'; h.f.places[0].sharedCoordinates = null; h.f.places[0].sharedCoordinatePrecision = 'hidden'; h.f.places[0].revision++;
  await h.show(); assert(h.control('路线名称')); assert(!h.control('已核对地点名称与坐标共享范围').props.checked); assert.equal(h.nodes().find(n => n.type === 'WorldMap').props.routeMap.markers.length, 1);
  await h.offline(); assert(!h.control('路线名称')); await h.online(); assert(h.control('路线名称'));
});
test('late write cannot show data or offer original-key retry after identity changes', async t => {
  const h = harness({ identityAfterWrite: true }); t.after(h.close); await newRoute(h); await h.click('保存路线'); assert(!h.control('路线名称')); assert(!h.control('核对原操作')); assert(!h.nodes().some(n => n.type === 'WorldMap')); assert.match(h.text(), /身份或查看权限已变化|登录或查看权限已变化/);
});
test('post-write identity read failure remains recoverable only after the same identity is checked again', async t => {
  const h = harness({ failAfterWrite: true }); t.after(h.close); await newRoute(h); await h.click('保存路线'); assert(!h.control('核对原操作')); assert(!h.nodes().some(n => n.type === 'WorldMap'));
  h.f.failAfterWrite = false; await h.click('重新读取路线'); await h.click('核对原操作'); assert.equal(h.writes().length, 1); assert.match(h.text(), /已确认保存/);
});
test('a write denied with 403 clears private content and draft immediately', async t => {
  const h = harness({ rejection: 403 }); t.after(h.close); await newRoute(h); await h.click('保存路线'); assert(!h.control('路线名称')); assert(!h.nodes().some(n => n.type === 'WorldMap')); assert(!h.control('核对原操作'));
});
test('a response arriving while hidden stays concealed and is recovered without resubmission', async t => {
  let release; const gate = new Promise(resolve => { release = resolve; }); const h = harness({ gate }); t.after(h.close); await newRoute(h); await h.click('保存路线'); await h.hide(); release(); await h.settle(); assert(!h.nodes().some(n => n.type === 'WorldMap'));
  await h.show(); await h.click('核对原操作'); assert.equal(h.writes().length, 1); assert.match(h.text(), /已确认保存/);
});
test('unknown operation remains recoverable after source journey disappears; unreadable draft can be cancelled', async t => {
  const h = harness({ dropReply: true }); t.after(h.close); await newRoute(h); await h.click('保存路线'); await h.hide(); h.f.journeyDeleted = true;
  h.f.route = null; await h.show(); await h.click('核对原操作'); assert.equal(h.writes().length, 1); assert(!h.control('核对原操作')); assert.match(h.text(), /已确认原操作完成/); assert(!h.control('返回旅行详情').props.disabled);
  const d = harness(); t.after(d.close); await newRoute(d); d.f.journeyDeleted = true; await d.hide(); await d.show(); await d.click('取消编辑'); assert(!d.control('返回旅行详情').props.disabled);
});
test('photo return reopens same route and deletion has explicit confirmation', async t => {
  const h = harness({ route: detail() }); t.after(h.close); await h.settle(); await h.click('查看路线 往返路线'); await h.click('查看旅行照片');
  const photo = h.nodes().find(n => n.type === 'TripRecapPanel'); assert.equal(photo.props.initialTab, 'photos'); assert.equal(photo.props.backLabel, '返回旅行路线'); photo.props.onBack(); await h.settle(); assert.match(h.text(), /往返路线/);
  await h.click('删除路线'); assert.equal(h.writes().length, 0); await h.click('确认删除路线'); assert.equal(h.writes()[0].method, 'DELETE'); assert.match(h.text(), /路线已删除/);
});

// Optional author-run seam check consumes unmodified actual Flask JSON saved by
// the API author. Normal builds need no sibling worktree or private fixtures.
if (process.env.JOURNEY_ROUTES_WIRE_FIXTURE) test('actual Flask synthetic route DTOs decode without replacing HTTP responses', () => {
  const wire = JSON.parse(readFileSync(process.env.JOURNEY_ROUTES_WIRE_FIXTURE, 'utf8')), jid = wire.detailPrivate.route.journeyId;
  for (const key of ['detailPrivate', 'detailSharedOwner', 'detailSharedOther', 'detailUnavailable']) assert.equal(api.readRouteDetail(wire[key], jid).route.id, wire[key].route.id);
  for (const [key, scope] of [['listOwner', 'mine'], ['listOther', 'shared']]) assert.deepEqual(clone(api.readRoutePage(wire[key], jid, scope, wire[key].offset, wire[key].limit)), wire[key]);
  for (const key of ['createPrivate', 'createShared', 'operationCurrent', 'delete', 'operationAfterDelete']) {
    const raw = wire[key], o = raw.operation, method = { create: 'POST', update: 'PUT', delete: 'DELETE' }[o.kind];
    const parsed = api.readRouteReceipt(raw, { requestId: o.requestId, method, routeId: o.routeId, body: {}, path: '', uncertain: true }, jid);
    assert.deepEqual(clone(parsed.operation), raw.operation); assert.equal(parsed.current?.route.id || null, raw.current?.route.id || null);
  }
  const r = wire.createPrivate; const moved = { ...r, current: wire.detailJourneyDeleted }; moved.operation = { ...r.operation, routeId: wire.detailJourneyDeleted.route.id };
  const parsed = api.readRouteReceipt(moved, { requestId: moved.operation.requestId, method: 'POST', body: {}, path: '', uncertain: true }, jid); assert.equal(parsed.current, null);
  assert.throws(() => api.readRouteDetail(wire.detailJourneyDeleted, jid));
});
