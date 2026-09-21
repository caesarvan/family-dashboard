import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { runInNewContext } from 'node:vm';
const require = createRequire(import.meta.url), ts = require('typescript');
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../src');
const copy = v => JSON.parse(JSON.stringify(v));
function loader(mocks = {}, globals = {}) {
  const cache = new Map();
  function load(file) {
    file = resolve(file); if (!existsSync(file)) file += existsSync(file + '.ts') ? '.ts' : '.tsx';
    if (cache.has(file)) return cache.get(file);
    const exports = {}; cache.set(file, exports);
    const code = ts.transpileModule(readFileSync(file, 'utf8'), { fileName: file, compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true } }).outputText;
    runInNewContext(code, { exports, require: n => n in mocks ? mocks[n] : load(resolve(dirname(file), n)), Date, Error, URL, URLSearchParams, AbortController, TextEncoder, TextDecoder, setTimeout, clearTimeout, process: { env: {} }, ...globals });
    return exports;
  } return load;
}
const read = loader(), lib = read(resolve(root, 'lib/assistantJourneyStatus.ts')), intent = read(resolve(root, 'lib/assistantJourney.ts'));
const { ApiError } = read(resolve(root, 'lib/api.ts')), { sessionIdentity } = read(resolve(root, 'lib/sessionIdentity.ts'));
const tid = 'a'.repeat(24), jid = 'b'.repeat(24), v1 = 'c'.repeat(64), v2 = 'd'.repeat(64), itemId = n => n.toString(16).padStart(24, '0');
const session = () => ({ user: { id: 'member1', name: '本人', role: 'member', householdId: 'home', auth_version: 1 }, csrf: 'synthetic' });
const candidate = (tripId = tid) => ({ tripId, journeyId: jid, tripRevision: 2, title: '冰岛旅行', destination: '冰岛', start: '2026-10-01', end: '2026-10-07', status: 'available' });
const candidates = (query = '冰岛', offset = 0) => ({ version: 1, view: 'candidates', query, items: [candidate()], limit: 20, offset, nextOffset: null, coverage: { scannedTrips: 1, scanLimit: 1000, capped: false, unverifiable: 0 } });
const status = (section = 'tasks', offset = 0, version = v1) => ({ version: 1, view: 'status', state: 'ready', trip: { ...candidate(), journeyRevision: 4 }, sourceVersion: version,
  summary: { tasks: { done: 0, total: 23, remaining: 23, blocked: 1 }, shopping: { done: 0, total: 1, remaining: 1 } }, section, offset, limit: 20, nextOffset: section === 'tasks' && !offset ? 20 : null,
  items: section === 'shopping' ? [{ kind: 'shopping', id: itemId(99), revision: 1, title: '转换插头', owner: { id: 'shared', name: '一起' }, due: '', quantity: '2 件', priority: 'high' }]
    : Array.from({ length: offset ? 3 : 20 }, (_, i) => ({ kind: 'tasks', id: itemId(offset + i + 1), revision: 1, title: '准备事项' + (offset + i + 1), owner: { id: 'member1', name: '本人' }, due: '', dependencyStatus: offset + i ? 'ready' : 'blocked', blockers: offset + i ? [] : [{ id: null, title: null, reason: 'unavailable' }] })),
  coverage: { complete: true, unverifiable: 0, reasonCodes: [] } });
function fixture(options = {}, library = lib, ErrorType = ApiError) {
  const f = { session: session(), calls: [], observed: [], version: v1, gate: null, meCount: 0, failMe: 0, failAt: 0, failStatus: null, expired: 0, current: true, ...options };
  async function get(path, signal) {
    f.calls.push({ path, signal });
    if (path === '/me') { f.meCount++; if (f.failAt === f.meCount) throw new ErrorType('me error', f.failMe, 'journey_status_unavailable'); return copy(f.session); }
    assert(path.startsWith('/assistant/journey-status?'));
    if (f.failStatus) { const fail = f.failStatus; f.failStatus = null; throw new ErrorType('status error', ...fail); }
    const p = new URL('https://synthetic.invalid' + path).searchParams;
    const value = p.has('tripId') ? status(p.get('section'), Number(p.get('offset')), f.version) : candidates(p.get('q'), Number(p.get('offset')));
    if (f.gate) { const gate = f.gate; f.gate = null; await gate; } return value;
  }
  const flow = new library.JourneyStatusFlow(sessionIdentity(f.session), '冰岛旅行还有哪些没做', { read: get, current: () => f.current, expired: () => f.expired++ }, state => f.observed.push(copy(state)));
  return { f, flow, get, async ready() { await flow.resume(); await flow.select(tid); } };
}
test('routing requires travel context and preserves search, list, changes and new planning', () => {
  for (const text of ['冰岛旅行准备得怎么样？', '冰岛行程准备进度', '旅行还有哪些没做']) { assert(intent.isJourneyStatusRequest(text)); assert(!intent.isJourneyRequest(text)); }
  for (const text of ['还有哪些没做', '还有什么未完成', '搜索：冰岛旅行准备情况', '查找旅行准备进度', '待办：旅行准备情况', '采购：旅行准备情况', '任务：旅行准备进度', '旅行推迟一天，准备情况']) assert(!intent.isJourneyStatusRequest(text), text);
  assert(intent.isJourneyRequest('计划一趟冰岛旅行')); assert(intent.isExistingTripChangeRequest('冰岛旅行提前一天'));
  assert.deepEqual(copy(intent.journeyStatusIntent('冰岛旅行准备得怎么样？')), { query: '冰岛', clarification: '' });
  assert.equal(intent.journeyStatusIntent('还有哪些没做').query, ''); assert.equal(intent.journeyStatusIntent('不确定的说法').query, '');
  assert.match(intent.journeyStatusIntent('添加一趟旅行，准备情况').clarification, /同时/);
});
test('projection validates counts, bounds, privacy and stale page versions', () => {
  assert.equal(lib.readStatusCandidates(candidates(), '冰岛', 0).items[0].tripId, tid);
  assert.equal(lib.readJourneyStatus(status(), { tripId: tid, section: 'tasks', offset: 0 }).summary.tasks.total, 23);
  for (const change of [v => { v.summary.tasks.remaining = 2; }, v => { v.items[0].blockers[0].title = 'hidden'; }, v => { v.coverage.complete = false; }, v => { v.items[1].id = v.items[0].id; }, v => { v.trip.start = '2025-02-29'; }, v => { v.items[0].owner.name = null; }]) { const v = status(); change(v); assert.throws(() => lib.readJourneyStatus(v, { tripId: tid, section: 'tasks', offset: 0 })); }
  assert.throws(() => lib.readJourneyStatus(status('tasks', 20), { tripId: tid, section: 'tasks', offset: 20, sourceVersion: v2 }));
  assert.throws(() => lib.statusPath({ query: '', offset: 0, target: { tripId: tid, section: 'tasks', offset: 20 } }));
  assert.throws(() => lib.statusPath({ query: '', offset: 1, target: null }));
});
test('legacy and partial results do not invent preparation totals', () => {
  const v = status(); Object.assign(v, { state: 'legacy', summary: null, items: [], nextOffset: null }); v.trip.journeyId = null; v.trip.journeyRevision = null; v.coverage = { complete: false, unverifiable: 0, reasonCodes: ['legacy_without_workflow'] };
  assert.equal(lib.readJourneyStatus(v, { tripId: tid, section: 'tasks', offset: 0 }).summary, null);
  const p = status(); p.state = 'needs_review'; p.coverage = { complete: false, unverifiable: 1, reasonCodes: ['linked_source_unavailable'] };
  assert.equal(lib.readJourneyStatus(p, { tripId: tid, section: 'tasks', offset: 0 }).state, 'needs_review');
});
test('Unicode code-point limits accept valid long titles without truncation', () => {
  const value=status(); value.trip.title='🧭'.repeat(100);value.items[0].title='🧳'.repeat(100);value.items[0].owner.name='🙂'.repeat(20);
  assert.equal(lib.readJourneyStatus(value,{tripId:tid,section:'tasks',offset:0}).trip.title,value.trip.title);
  assert.equal(intent.journeyStatusIntent('🧭'.repeat(100)+'旅行准备情况').query,'🧭'.repeat(100));
  value.items[0].title+='x';assert.throws(()=>lib.readJourneyStatus(value,{tripId:tid,section:'tasks',offset:0}));
});
test('single candidate still requires explicit selection and every request has two identity checks', async () => {
  const h = fixture(); await h.flow.resume(); assert.equal(h.flow.state.result.view, 'candidates'); assert.equal(h.f.calls.length, 3);
  assert.deepEqual(h.f.calls.map(x => x.path.split('?')[0]), ['/me', '/assistant/journey-status', '/me']);
  await h.flow.select(tid); assert.equal(h.flow.state.result.view, 'status'); assert.equal(h.f.calls.length, 6);
});
test('in-panel generic status phrase means candidate selection, never a guessed trip', async () => {
  const h = fixture(); await h.flow.resume(); h.flow.editQuery('还有哪些没做'); await h.flow.search(); assert.equal(h.flow.state.result.query, ''); assert.equal(h.flow.state.selection.target, null);
});
test('same-version return restores original page after fresh page zero; changed version returns zero', async () => {
  const h = fixture(); await h.ready(); await h.flow.page(true); assert.equal(h.flow.state.result.offset, 20);
  const start = h.f.calls.length; await h.flow.load(true); assert.equal(h.flow.state.result.offset, 20);
  assert.deepEqual(h.f.calls.slice(start).filter(x => x.path !== '/me').map(x => new URL('https://local' + x.path).searchParams.get('offset')), ['0', '20']);
  h.f.version = v2; await h.flow.load(true); assert.equal(h.flow.state.result.offset, 0); assert.match(h.flow.state.notice, /第一页/);
});
test('stale page clears old counts and retries from same section zero only on explicit read', async () => {
  const h = fixture(); await h.ready(); h.f.failStatus = [409, 'stale_journey_status']; await h.flow.page(true);
  assert.equal(h.flow.state.result, null); assert.equal(h.flow.state.selection.target.offset, 0); assert.match(h.flow.state.error, /变化/); assert(!h.flow.state.visible);
  await h.flow.resume(); assert.equal(h.flow.state.result.offset, 0);
});
for (const code of [404, 410]) for (const position of ['before', 'after']) test(position + ' /me ' + code + ' keeps original choice but hides contents', async () => {
  const h = fixture(); await h.ready(); h.f.failMe = code; h.f.failAt = h.f.meCount + (position === 'before' ? 1 : 2); await h.flow.load(true);
  assert.equal(h.flow.state.selection.target.tripId, tid); assert.equal(h.flow.state.result, null); assert(!h.flow.state.visible); assert.match(h.flow.state.error, /身份/);
  await h.flow.resume(); assert.equal(h.flow.state.result.trip.tripId, tid);
});
for (const code of [404, 410]) test('actual status ' + code + ' closes only unavailable original trip', async () => {
  const h = fixture(); await h.ready(); h.f.failStatus = [code, 'journey_status_unavailable']; await h.flow.load(true);
  assert.equal(h.flow.state.selection.target, null); assert.equal(h.flow.state.result, null); assert.match(h.flow.state.error, /原旅行/);
});
for (const code of [401, 403]) test('authorization ' + code + ' clears query, choice and response', async () => {
  const h = fixture(); await h.ready(); h.f.failStatus = [code, 'denied']; await h.flow.load(true);
  assert(h.flow.state.expired); assert.equal(h.flow.state.prompt, ''); assert.equal(h.flow.state.query, ''); assert.equal(h.flow.state.selection.target, null); assert.equal(h.f.expired, 1);
});
test('late successful response after member switch never enters visible state', async () => {
  const h = fixture(); await h.ready(); let release; h.f.gate = new Promise(r => { release = r; }); const p = h.flow.load(); await new Promise(r => setImmediate(r));
  h.f.session.user.id = 'member2'; release(); await p; assert(h.flow.state.expired); assert.equal(h.flow.state.result, null); assert.equal(h.flow.state.query, '');
});
test('conceal aborts old generation; same identity resumes fresh without overlap', async () => {
  const h = fixture(); await h.ready(); let release; h.f.gate = new Promise(r => { release = r; }); const p = h.flow.load(); await new Promise(r => setImmediate(r));
  const n = h.f.calls.length; await h.flow.load(); assert.equal(h.f.calls.length, n); h.flow.conceal(); assert(h.f.calls.at(-1).signal.aborted); release(); await p;
  assert(!h.flow.state.visible); assert.equal(h.flow.state.result, null); await h.flow.resume(); assert.equal(h.flow.state.result.trip.tripId, tid);
});
test('one total 15 second deadline cancels a stalled identity read and discards late results', async () => {
  let timeout, release; const timed = loader({}, { setTimeout: (fn, ms) => { assert.equal(ms, 15000); timeout = fn; return 1; }, clearTimeout() {} })(resolve(root, 'lib/assistantJourneyStatus.ts'));
  const flow = new timed.JourneyStatusFlow(sessionIdentity(session()), '', { read: () => new Promise(r => { release = r; }), current: () => true, expired() {} }, () => {});
  const p = flow.resume(); timeout(); await p; assert(!flow.state.visible); assert(!flow.state.busy); assert.match(flow.state.error, /身份/); release(session()); await Promise.resolve(); assert.equal(flow.state.result, null);
});
for (const code of [401, 403]) test('actual transport rejects authorization ' + code + ' even without a JSON body', async () => {
  const x = loader({}, { fetch: async () => new Response('not JSON', { status: code }) })(resolve(root, 'lib/assistantJourneyStatus.ts'));
  await assert.rejects(x.statusRead('/me', new AbortController().signal), error => error.status === code);
});
test('bounded GET streams enforce bytes and never use write method or credentials elsewhere', async () => {
  let calls = [], huge = false;
  const x = loader({}, { fetch: async (url, opts) => { calls.push({ url, opts }); return new Response(huge ? 'x'.repeat(262145) : JSON.stringify(candidates()), { status: 200 }); } })(resolve(root, 'lib/assistantJourneyStatus.ts'));
  const signal = new AbortController().signal; assert.equal((await x.statusRead('/assistant/journey-status?q=x', signal)).view, 'candidates');
  assert.equal(calls[0].url, '/api/assistant/journey-status?q=x'); assert.equal(calls[0].opts.method, 'GET'); assert.equal(calls[0].opts.credentials, 'include'); assert.equal(calls[0].opts.signal, signal);
  huge = true; await assert.rejects(x.statusRead('/me', signal), /过大/);
});

// Actual screen/component callbacks; React host and network are controlled substitutes.
function screen(entry = false) {
  let holder, cursor = 0, dirty = true, tree; const slots = new Map(), effects = [], listeners = new Map(), intervals = [];
  const changed = (a,b) => !a || !b || a.length !== b.length || a.some((v,i) => v !== b[i]);
  const react = { createElement: (type, props, ...children) => ({ type, props: { ...props, children: children.flat(Infinity).filter(x => x !== null && x !== undefined && x !== false) } }),
    useState(v) { const h = holder, i = cursor++; if (!(i in h)) h[i] = typeof v === 'function' ? v() : v; return [h[i], v => { h[i] = typeof v === 'function' ? v(h[i]) : v; dirty = true; }]; },
    useRef(v) { const i = cursor++; return holder[i] ||= { current: v }; },
    useEffect(fn,deps) { const h = holder, i = cursor++; if (changed(h[i]?.deps,deps)) { const old=h[i]; h[i]={ deps }; effects.push(() => { old?.cleanup?.(); h[i].cleanup=fn(); }); } },
    useCallback(fn,deps) { const i=cursor++; if (changed(holder[i]?.deps,deps)) holder[i]={deps,fn}; return holder[i].fn; } };
  const f=fixture(), events={ addEventListener(n,fn) { if (!listeners.has(n)) listeners.set(n,new Set()); listeners.get(n).add(fn); }, removeEventListener(n,fn) { listeners.get(n)?.delete(fn); } };
  const document={hidden:false,...events}, navigator={onLine:true}, window={...events};
  const household={identityKey:sessionIdentity(f.f.session),user:f.f.session.user,online:true,refresh:async()=>{},mutate:async()=>{throw Error('No writes');}};
  const mocks={react,'expo-router':{useFocusEffect:fn=>react.useEffect(fn,[fn])},'react-native':{View:'View',StyleSheet:{create:x=>x},AppState:{currentState:'active',addEventListener:()=>({remove(){}})}},
    'react-native-paper':Object.fromEntries(['ActivityIndicator','Button','Chip','Text','TextInput','Divider','HelperText'].map(x=>[x,x])),
    '../lib/household':{useHousehold:()=>household},'../ui/components':{SectionCard:'SectionCard',PageHeader:'PageHeader'},
    '../screens/TripsScreen':{__esModule:true,default:'TripsScreen'},'../lib/assistantJourneyStatus':{...lib,statusRead:f.get},
    '../ui/SelectionRow':{SelectionRow:'SelectionRow'},'../lib/trips':{shoppingScheduleText:()=>''}};
  mocks['react-native-paper'].useTheme=()=>({colors:{onSurfaceVariant:'#555'}});
  const dispatch=[];
  if(entry){
    class FakeFlow { constructor(user,io,emit) {this.emit=emit;this.state={ready:true,visible:true,busy:false,expired:false,modelConfigured:true,selected:[],edits:{}};}async load(){this.emit(this.state);}setForeground(){}close(){}async plan(...v){dispatch.push(['plan',...v]);} }
    mocks['../lib/assistant']={AssistantFlow:FakeFlow,memberKey:()=> 'member',assistantContentRequest:()=>null};
    for(const n of ['./JourneyBriefPanel','./TripsScreen','./JourneyDocumentsPanel','./PhotosScreen','./MapWorkspace','../components/ExistingTripChangePanel','../components/AssistantFinanceQueryPanel','../components/AssistantActionEditor'])mocks[n]={__esModule:true,default:n};
    mocks['../components/AssistantJourneyStatusPanel']={__esModule:true,default:'StatusPanel'};
  }
  const actual=loader(mocks,{document,navigator,window,setTimeout:()=>1,clearTimeout(){},setInterval:(fn,ms)=>{intervals.push({fn,ms});return intervals.length;},clearInterval(){}});
  const Component=actual(resolve(root,entry?'screens/AssistantScreen.tsx':'components/AssistantJourneyStatusPanel.tsx'))[entry?'AssistantScreen':'default'];
  const screenProps={user:household.user,state:{people:[],tasks:[],shopping:[],trips:[]},onNavigate(){},onEdit(){}};
  const props=entry?screenProps:{initialPrompt:'冰岛旅行还有哪些没做',screenProps,onBack:p=>dispatch.push(['back',p])};
  function render(n,path='root') { if(!n||typeof n!=='object')return n; if(typeof n.type==='function'){holder=slots.get(path)||{};slots.set(path,holder);cursor=0;return render(n.type(n.props),path+'/render');} return {...n,props:{...n.props,children:(n.props.children||[]).map((c,i)=>render(c,path+'/'+(c?.props?.key??i)))}}; }
  async function flush(){for(let t=0;t<3;t++){for(let i=0;i<30;i++){if(dirty){dirty=false;tree=render({type:Component,props});}while(effects.length)effects.shift()();await Promise.resolve();}await new Promise(r=>setImmediate(r));}}
  const nodes=()=>{const out=[];function walk(n){if(!n||typeof n!=='object')return;out.push(n);n.props.children?.forEach(walk);}walk(tree);return out;};
  const text=(n=tree)=>n==null||typeof n==='boolean'?'':typeof n!=='object'?String(n):(n.props.children||[]).map(text).join(' ');
  const find=id=>{const n=nodes().filter(n=>n.props.testID===id||n.props.accessibilityLabel===id);assert.equal(n.length,1,id);return n[0];};
  return {f:f.f,household,props,dispatch,flush,nodes,text,find,intervals,
    async click(id){const n=find(id);assert(!n.props.disabled,id);n.props.onPress();await flush();},
    async press(label){const n=nodes().find(n=>n.type==='Button'&&text(n)===label);assert(n&&!n.props.disabled,label);n.props.onPress();await flush();},
    async fill(id,value){find(id).props.onChangeText(value);await flush();},
    async offline(){navigator.onLine=false;household.online=false;listeners.get('offline')?.forEach(fn=>fn());dirty=true;await flush();},
    async online(){navigator.onLine=true;household.online=true;listeners.get('online')?.forEach(fn=>fn());dirty=true;await flush();}};
}
test('actual TSX selects original ID, shows current blockers/shopping and returns with fresh same page', async () => {
  const h=screen();await h.flush();assert(h.find('assistant-journey-status-candidate-'+tid));assert(!h.nodes().some(n=>n.type==='TripsScreen'));
  await h.press('查看这趟准备');assert.match(h.text(),/准备：已完成\s+0\s+\/\s+23/);assert.match(h.text(),/前置事项当前不可核对/);
  await h.click('assistant-journey-status-shopping');assert.match(h.text(),/转换插头/);assert.match(h.text(),/不代表已经下单、付款或入库/);
  await h.click('assistant-journey-status-tasks');await h.click('assistant-journey-status-items-next');await h.click('assistant-journey-status-open');
  const trip=h.nodes().find(n=>n.type==='TripsScreen');assert.equal(trip.props.tripRequest.id,tid);
  for(const callback of ['onReschedulePending','onDocumentsPending','onSegmentsPending','onTripImportPending','onJourneyFinancePending']) {
    trip.props[callback](true);trip.props.onExitPlanning();await h.flush();assert(h.nodes().some(n=>n.type==='TripsScreen'));trip.props[callback](false);
  }
  h.f.version=v2;trip.props.onExitPlanning();await h.flush();assert.match(h.text(),/第一页/);assert.match(h.text(),/原问题：/);
});
test('actual TSX unavailable trip after background has explicit local exit without bypassing pending writes', async () => {
  const h=screen();await h.flush();await h.press('查看这趟准备');await h.click('assistant-journey-status-open');
  const trip=h.nodes().find(n=>n.type==='TripsScreen');trip.props.onReschedulePending(true);await h.offline();
  let button=h.nodes().find(n=>n.type==='Button'&&h.text(n)==='放弃未提交编辑，返回准备查询');assert(button.props.disabled);button.props.onPress();await h.flush();assert(h.nodes().some(n=>n.type==='TripsScreen'));
  trip.props.onReschedulePending(false);h.f.failStatus=[404,'journey_status_unavailable'];await h.online();
  await h.press('放弃未提交编辑，返回准备查询');assert(!h.nodes().some(n=>n.type==='TripsScreen'));assert(h.find('assistant-journey-status-candidate-'+tid));
});
test('actual TSX hides offline and post-me failure, then rechecks same selection', async () => {
  const h=screen();await h.flush();await h.press('查看这趟准备');await h.offline();assert(!h.text().includes('冰岛'));await h.online();assert(h.find('assistant-journey-status-status'));
  h.f.failMe=404;h.f.failAt=h.f.meCount+2;await h.click('assistant-journey-status-refresh');assert(!h.text().includes('冰岛'));assert.match(h.text(),/身份/);
  await h.click('assistant-journey-status-refresh');assert(h.find('assistant-journey-status-status'));
});
test('actual assistant routes status before new journey with AI enabled, while ordinary task phrase stays old flow', async () => {
  const h=screen(true);await h.flush();await h.fill('告诉助理你的需求','还有哪些没做');await h.press('整理并预览');assert.equal(h.dispatch[0][0],'plan');
  await h.fill('告诉助理你的需求','冰岛旅行准备得怎么样');const ai=h.nodes().find(n=>n.type==='SelectionRow'&&n.props.label==='使用已配置的 AI 整理');ai.props.onPress();await h.flush();
  assert.match(h.text(),/不会发送给 AI/);await h.press('查询');const panel=h.nodes().find(n=>n.type==='StatusPanel');assert(panel);assert.equal(panel.props.initialPrompt,'冰岛旅行准备得怎么样');assert.equal(h.dispatch.length,1);
});
