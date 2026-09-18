import assert from 'node:assert/strict';
import { test } from 'node:test';
import { existsSync } from 'node:fs';
import { registerHooks } from 'node:module';
import { resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Import reviewed TypeScript in place. Node's TS stripping does not resolve
// Metro's extensionless relative imports; this narrow local hook adds only .ts.
const source = resolve(process.env.EXPO_TV_SOURCE_ROOT || fileURLToPath(new URL('..', import.meta.url)));
const front = pathToFileURL(resolve(source, 'frontend')).href + '/';
registerHooks({ resolve(specifier, context, next) {
  if (context.parentURL?.startsWith(front) && /^\.\.?\//.test(specifier) && !/\.[a-z]+$/i.test(specifier)) {
    const candidate = new URL(specifier + '.ts', context.parentURL);
    if (existsSync(fileURLToPath(candidate))) return next(candidate.href, context);
  }
  return next(specifier, context);
} });
const from = name => import(pathToFileURL(resolve(source, name)).href);
const { readTVIdentity, tvIdentityKey, sameTVIdentity, readTVSpace, readTVPair, readTVPairPoll,
  readTVSnapshot, TVGeneration, TVDiscarded, TVError, tvRequest, isTVRoute } = await from('frontend/src/lib/tv.ts');
const { tvCalendarPages, tvBoardRows, tvMoney, tvPending, tvUpcoming, tvReadDuration, tvScrollOffset } = await from('frontend/src/ui/TVBoard.model.ts');
const { rangeDays } = await from('frontend/src/lib/calendar.ts');

const device = 'a'.repeat(24), otherDevice = 'b'.repeat(24), household = 'c'.repeat(24);
const actor = () => ({ id: device, householdId: 'default', name: '合成电视', role: 'tv' });
const layout = () => ({ order: ['calendar', 'finance', 'tasks', 'shopping', 'trips'], hidden: [], theme: 'light', density: 'comfortable' });
const day = '2026-09-17', now = Date.parse(day + 'T10:00:00+08:00');
const event = (id = 'event1', owner = 'member1', extra = {}) => ({ id, revision: 1, title: '合成安排', owner,
  start: day + 'T10:00:00+08:00', end: day + 'T11:00:00+08:00', location: '合成地点', allDay: false, ...extra });
const snapshot = () => ({ revision: 8, household: { id: 'default', name: '合成家庭', slug: 'home' },
  people: [{ id: 'member1', name: '合成甲' }, { id: 'member2', name: '合成乙' }],
  events: [event()], tasks: [{ id: 'task1', revision: 1, title: '准备出行', owner: 'shared', done: false, due: day }],
  shopping: [{ id: 'shop1', revision: 1, title: '添置咖啡豆', owner: 'shared', done: false, quantity: '2包', budget: null }],
  trips: [{ id: 'trip1', revision: 1, title: '合成旅行', owner: 'shared', start: day, end: '2026-09-20', budget: 10000, saved: 0, paid: 0 }],
  finance: { revision: 1, wallet: 0, livingSpent: 12345, livingBudget: 620000, reserveTarget: 1000000,
    travelSaved: 0, longterm: 0, contributionPercent: 50, confirmedAt: '' },
  display: { focus: 'member1', calendarView: 'week', layout: layout() } });
const clone = value => structuredClone(value);

test('TV identity admits only a genuine TV DTO and binds household plus device', () => {
  assert.equal(readTVIdentity({ user: null, csrf: null }), null);
  assert.deepEqual(readTVIdentity({ user: { ...actor(), secret: 'must-not-retain', focus: 'member1' }, csrf: null }), actor());
  for (const raw of [null, [], {}, { user: { ...actor(), role: 'member' }, csrf: null },
    { user: actor(), csrf: 'member-csrf' }, { user: { ...actor(), id: 'member1' }, csrf: null },
    { user: { ...actor(), householdId: '../../elsewhere' }, csrf: null }]) assert.throws(() => readTVIdentity(raw));
  assert.equal(tvIdentityKey(actor()), 'default:' + device);
  assert(sameTVIdentity(actor(), { ...actor(), name: '允许更名' }));
  assert(!sameTVIdentity(actor(), { ...actor(), id: otherDevice }));
  assert(!sameTVIdentity(actor(), { ...actor(), householdId: household }));
  assert(!sameTVIdentity(actor(), null));
});

test('pair and signed-space descriptors reject invalid code, lifetime and external routing', () => {
  const pair = { code: 'ABCD2345', secret: 'x'.repeat(43), expiresIn: 600 };
  assert.deepEqual(readTVPair({ ...pair, next: '//external.invalid' }), pair);
  for (const patch of [{ code: 'ABCD1234' }, { code: 'abcd2345' }, { code: 'ABCD23456' }, { secret: '../invalid' },
    { secret: 'x'.repeat(101) }, { expiresIn: 0 }, { expiresIn: 601 }, { expiresIn: true }, { expiresIn: 1.5 }]) {
    assert.throws(() => readTVPair({ ...pair, ...patch }));
  }
  assert.equal(readTVPairPoll({ approved: false }), false);
  assert.equal(readTVPairPoll({ approved: true }), true);
  for (const approved of [1, 'true', null, undefined]) assert.throws(() => readTVPairPoll({ approved }));
  const space = { id: household, name: '合成家庭', slug: 'second-home', entry: '/space/second-home' };
  assert.deepEqual(readTVSpace({ ...space, private: 'drop' }), space);
  for (const patch of [{ entry: '//external.invalid' }, { entry: '/space/home' }, { slug: '../home' },
    { id: 'unsigned' }, { slug: 'A-home' }]) assert.throws(() => readTVSpace({ ...space, ...patch }));
});

test('shared snapshot projects only required board fields and rejects another household', () => {
  const raw = snapshot();
  Object.assign(raw, { wealth: [{ private: 'secret' }], accounts: ['secret'], sync: { access_token: 'secret' }, privateFinance: 'secret' });
  Object.assign(raw.finance, { note: 'secret', account: 'secret' });
  Object.assign(raw.events[0], { note: 'secret', sync: { accessToken: 'secret' }, media: 'secret' });
  Object.assign(raw.shopping[0], { photoIds: ['secret'], actual: 99999 });
  const serialized = JSON.stringify(raw), result = readTVSnapshot(raw, actor());
  assert(!JSON.stringify(result).includes('secret'));
  assert.equal(result.state.finance.wallet, 0);
  assert.equal(result.state.shopping[0].budget, null);
  assert.equal(result.state.shopping[0].actual, undefined);
  assert.equal(JSON.stringify(raw), serialized, 'Projection must not mutate the source DTO');
  assert.throws(() => readTVSnapshot(raw, { ...actor(), householdId: household }));
  raw.people.push(raw.people[0]); assert.throws(() => readTVSnapshot(raw, actor()));
});

test('shared zero, unknown budget and integer cents stay distinct; malformed amounts reject the snapshot', () => {
  const raw = snapshot();
  raw.shopping[0].budget = 0;
  raw.finance.confirmedAt = day + 'T10:00:00+08:00';
  assert.equal(readTVSnapshot(raw, actor()).state.shopping[0].budget, 0);
  assert.equal(tvMoney(null), '待核对'); assert.equal(tvMoney(undefined), '待核对');
  assert.equal(tvMoney(0), '¥0.00'); assert.equal(tvMoney(12345), '¥123.45');
  assert.equal(tvMoney(Number.MAX_SAFE_INTEGER), '¥90,071,992,547,409.91');
  for (const money of [-1, 0.5, true, '123', NaN, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
    const next = snapshot(); next.finance.wallet = money;
    assert.throws(() => readTVSnapshot(next, actor()));
  }
  for (const value of [-1, 101, 1.5, true]) {
    const next = snapshot(); next.finance.contributionPercent = value;
    assert.throws(() => readTVSnapshot(next, actor()));
  }
});

test('full cloud title and location limits survive without truncation; invalid dates/duplicates fail closed', () => {
  const raw = snapshot(); raw.events[0].title = '标'.repeat(2048); raw.events[0].location = '址'.repeat(2048);
  assert.equal(readTVSnapshot(raw, actor()).state.events[0].title.length, 2048);
  assert.equal(readTVSnapshot(raw, actor()).state.events[0].location.length, 2048);
  for (const patch of [{ title: '长'.repeat(2049) }, { location: '长'.repeat(2049) }, { start: '2026-02-30T10:00:00Z' },
    { start: day }, { end: day + 'T09:00:00+08:00' }, { owner: 'invalid/member' }, { revision: 0 }, { allDay: 'false' }]) {
    const next = clone(raw); Object.assign(next.events[0], patch); assert.throws(() => readTVSnapshot(next, actor()));
  }
  raw.events.push(raw.events[0]); assert.throws(() => readTVSnapshot(raw, actor()));
  const next = snapshot(); next.tasks[0].due = '2026-02-29'; assert.throws(() => readTVSnapshot(next, actor()));
  const historical = snapshot(); historical.events[0].owner = 'm_' + 'a'.repeat(24);
  assert.equal(readTVSnapshot(historical, actor()).state.events[0].owner, historical.events[0].owner);
});

test('only complete valid device layouts and permitted focus/view reach the board', () => {
  for (const patch of [{ focus: 'foreign' }, { calendarView: 'month' }, { layout: { ...layout(), hidden: layout().order } },
    { layout: { ...layout(), theme: 'external-url' } }, { layout: { ...layout(), order: ['calendar', 'calendar'] } }]) {
    const raw = snapshot(); Object.assign(raw.display, patch); assert.throws(() => readTVSnapshot(raw, actor()));
  }
  const raw = snapshot(); raw.people = raw.people.filter(person => person.id !== raw.display.focus);
  assert.throws(() => readTVSnapshot(raw, actor()));
  for (const count of [1, 2, 3, 4, 5]) {
    const value = { ...layout(), order: [...layout().order].reverse(), hidden: layout().order.slice(count) };
    assert.deepEqual(tvBoardRows(value).flat(), value.order.filter(card => !value.hidden.includes(card)));
  }
});

test('calendar pagination includes all owners and every event, exclusive all-day end and correct date windows', () => {
  const days = rangeDays('week', day), events = [];
  for (const date of days) for (let n = 0; n < 9; n++) events.push(event(`${date}-${n}`, ['member1', 'member2', 'shared'][n % 3],
    { start: `${date}T10:00:00+08:00`, end: `${date}T11:00:00+08:00` }));
  const allDay = event('all-day', 'member2', { allDay: true, start: day, end: '2026-09-18' }); events.push(allDay);
  const original = JSON.stringify(events);
  const pages = tvCalendarPages(events, days, 'member1', now, 3, 2);
  for (const date of days) {
    const displayed = new Set(pages.flat().filter(row => row.day === date).flatMap(row => row.events.map(item => item.id)));
    const expected = new Set(events.filter(item => item.start.startsWith(date)).map(item => item.id));
    assert.deepEqual(displayed, expected);
    assert(pages.flat().filter(row => row.day === date).every(row => row.events.length <= 2));
  }
  assert(!pages.flat().filter(row => row.day === '2026-09-18').flatMap(row => row.events).some(item => item.id === 'all-day'));
  assert.equal(JSON.stringify(events), original);
  assert.deepEqual(rangeDays('around', '2026-01-01'), ['2025-12-29','2025-12-30','2025-12-31','2026-01-01','2026-01-02','2026-01-03','2026-01-04']);
});

test('upcoming and pending lists retain other members while excluding completed/history', () => {
  const tasks = ['member1','member2','shared'].map((owner, n) => ({ id: String(n), owner, title: owner, done: false, due: day }));
  assert.deepEqual(new Set(tvPending([...tasks, { ...tasks[0], id: 'done', done: true }], 'member1').map(item => item.id)), new Set(['0','1','2']));
  assert.equal(tvPending(tasks, 'member2')[0].owner, 'member2');
  const trips = [{ id:'old', start:'2026-01-01', end:'2026-01-02' }, { id:'current', start:'2026-09-16', end:day },
    { id:'next', start:'2026-09-18', end:'2026-09-20' }];
  assert.deepEqual(tvUpcoming(trips, day).map(trip => trip.id), ['current','next']);
});

test('reading duration covers the last long-content viewport before pagination; offsets never overscroll', () => {
  for (const [viewport, content] of [[300,250], [300,301], [300,2500], [520,16000]]) {
    const duration = tvReadDuration(viewport, content), end = Math.max(0, content - viewport);
    assert(duration >= 20000);
    assert.equal(tvScrollOffset(viewport, content, duration - 1000), end);
    assert.equal(tvScrollOffset(viewport, content, 0), 0);
    assert.equal(tvScrollOffset(viewport, content, duration * 10), end);
  }
});

test('closed/reopened generations reject every old ticket, including late failed reads', () => {
  const guard = new TVGeneration(); assert(!guard.current(guard.ticket()));
  const first = guard.open(); guard.check(first);
  guard.close(); assert.throws(() => guard.check(first), TVDiscarded);
  const resumed = guard.open(); guard.check(resumed);
  assert.throws(() => guard.check(first), TVDiscarded);
  const replacement = guard.open(); assert.throws(() => guard.check(resumed), TVDiscarded);
  guard.check(replacement); guard.close(); assert.throws(() => guard.check(replacement), TVDiscarded);
});

test('route gate matches only exact TV paths before a member provider can mount', () => {
  for (const path of ['/tv','/tv/','/app/tv','/app/tv/']) assert(isTVRoute(path));
  for (const path of ['/app/devices','/app/tv/settings','/app/tv-other','/TV','//tv','/app','/']) assert(!isTVRoute(path));
});

test('transport is TV-only no-store, finite read paths and only pair POST; response and abort errors stay errors', async () => {
  const originalFetch = globalThis.fetch, calls = [];
  try {
    globalThis.fetch = async (url, options) => {
      calls.push({ url, options });
      return new Response(JSON.stringify({ user:null, csrf:null }), { headers:{'Content-Type':'application/json'} });
    };
    await tvRequest('/me', new AbortController().signal);
    await tvRequest('/pair/poll', new AbortController().signal, { secret:'synthetic-only' });
    assert.equal(calls[0].url, '/api/me'); assert.equal(calls[0].options.method, 'GET');
    assert.equal(calls[1].options.method, 'POST');
    for (const { options } of calls) {
      assert.equal(options.headers['X-Display-Mode'], 'tv'); assert.equal(options.credentials, 'same-origin');
      assert.equal(options.cache, 'no-store'); assert.equal(options.redirect, 'error');
      assert.equal(options.headers['X-CSRF-Token'], undefined);
    }
    await assert.rejects(tvRequest('/accounts', new AbortController().signal));
    await assert.rejects(tvRequest('/state', new AbortController().signal, {}));
    assert.equal(calls.length, 2);
    globalThis.fetch = async () => new Response('{}', { status:401, headers:{'Content-Type':'application/json'} });
    await assert.rejects(tvRequest('/state', new AbortController().signal), error => error instanceof TVError && error.status === 401);
    globalThis.fetch = async () => new Response('<html>login</html>', { headers:{'Content-Type':'text/html'} });
    await assert.rejects(tvRequest('/state', new AbortController().signal), TVError);
    const controller = new AbortController(); controller.abort();
    await assert.rejects(tvRequest('/state', controller.signal), TVDiscarded);
    const late = new AbortController();
    globalThis.fetch = async () => { late.abort(); return new Response('{}', { headers:{'Content-Type':'application/json'} }); };
    await assert.rejects(tvRequest('/state', late.signal), TVDiscarded);
  } finally { globalThis.fetch = originalFetch; }
});
