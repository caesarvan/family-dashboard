import assert from 'node:assert/strict';
import { test } from 'node:test';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { BaselineDiscarded, BaselineError, BaselineFence, baselineSignature, baselineRequest, baselinePage, formatBaselineMoney, formatBaselineTime, readFinanceBaseline } from '../frontend/src/lib/financeBaseline.ts';

// Business DTOs come from the real Flask routes and a temporary SQLite database.
// Only negative protocol/identity cases below use synthetic transport responses.
const root = resolve(process.env.BASELINE_MODEL_BACKEND_ROOT || fileURLToPath(new URL('..', import.meta.url)));
const python = process.env.BASELINE_TEST_PYTHON || 'python';
const setup = spawnSync(python, ['-B', '-X', 'utf8', '-c', String.raw`
import sys, os, json, tempfile, sqlite3, socket
from pathlib import Path
from copy import deepcopy
from contextlib import closing
from unittest.mock import patch
root=Path(sys.argv[1]).resolve()
sys.path[:0]=[str(root),str(root/'tests')]
from app import create_app
from finance_baseline import import_baseline
from test_finance_source_bridge import synthetic_candidate, normalize_candidate
from test_spending_observations import observation, preview, confirm
from test_app import member
def denied(*args,**kwargs): raise AssertionError('External connections forbidden')
with tempfile.TemporaryDirectory(prefix='expo-baseline-model-') as folder, patch.object(socket.socket,'connect',denied), patch('socket.create_connection',denied), patch.dict(os.environ,{'MEMBER1_PASSWORD':'testing-password-one','MEMBER2_PASSWORD':'testing-password-two'}):
    app=create_app({'TESTING':True,'SECRET_KEY':'synthetic-baseline-only','DATA_DIR':folder,'SESSION_COOKIE_SECURE':False})
    c,h=member(app); other,_=member(app,2); result={'empty':c.get('/api/finance-baseline/private').json,'session':c.get('/api/me').json}
    def read():
        response=c.get('/api/finance-baseline/private'); assert response.status_code==200,response.status_code
        return response.json
    def save(private,shared):
        with closing(sqlite3.connect(Path(folder)/'household.sqlite3')) as con:
            with con: import_baseline(con,private,shared)
    _,private,shared,_=normalize_candidate(synthetic_candidate(),'member1')
    private['spending']=observation('2026-09-14',1000)['spending']
    private['secret_extra']='SYNTHETIC_MUST_NOT_RENDER'
    private['assets'][0]['secret_extra']='SYNTHETIC_MUST_NOT_RENDER'
    unknown=deepcopy(private['assets'][0]); unknown.update(label='未估值美元账户 '+('很长的说明'*30),amountCents=None,currency='USD',includedInRecordedSubtotal=False,exclusionReason='尚未取得估值')
    zero=deepcopy(private['assets'][0]); zero.update(label='零余额记录',amountCents=0)
    private['assets'] += [unknown,zero]
    save(private,shared); result['modern']=read()
    assert other.get('/api/finance-baseline/private?owner=member1').json is None
    result['other']=other.get('/api/finance-baseline/private').json
    report=observation('2026-09-15',-100)
    planned=preview(c,h,report); written=confirm(c,h,planned,report); assert written.status_code==200,written.json
    result['observation']=read()
    assert result['observation']['spendingObservation']['origin']=='spending_observation'
    assert result['observation']['assets']==result['modern']['assets']
    # A complete source and an old import are both persisted through the real validator.
    full=deepcopy(private); complete=deepcopy(shared)
    for obj in [full['totals'],complete]: obj.update(complete=True,assetCents=12000,liabilityCents=4500,netCents=7500)
    save(full,complete); result['complete']=read()
    # Remove the independent report to exercise a genuine old baseline DTO.
    with closing(sqlite3.connect(Path(folder)/'household.sqlite3')) as con:
        with con:
            con.execute('DELETE FROM finance_spending_receipts'); con.execute('DELETE FROM finance_spending_observations')
    legacy=deepcopy(private); legacy.pop('sourceBridge'); legacy['spending']={'monthly':[{'period':'2026-09','netSpendCents':0,'transactionCount':0}],'note':'旧报告未提供币种与覆盖日期'}
    for kind in ['assets','liabilities','income']:
        for item in legacy[kind]: item.pop('id',None)
    legacy['income'][0].pop('includedInRecordedSubtotal',None)
    save(legacy,shared); result['legacy']=read()
    tv=app.test_client(); pair=tv.post('/api/pair/start',json={}).json
    assert c.post('/api/pair/approve',json={'code':pair['code'],'name':'合成电视','focus':'member1'},headers=h).status_code==200
    assert tv.post('/api/pair/poll',json={'secret':pair['secret']}).json['approved']
    result['tvStatus']=tv.get('/api/finance-baseline/private').status_code
    result['anonymousStatus']=app.test_client().get('/api/finance-baseline/private').status_code
print(json.dumps(result,ensure_ascii=False))
`, root], { cwd: root, encoding: 'utf8', timeout: 90000, maxBuffer: 4_000_000 });
assert.equal(setup.status, 0, setup.stderr || setup.error?.message || 'Real fixture failed');
const fixture = JSON.parse(setup.stdout), clone = value => structuredClone(value);

test('real owner-only route: null is empty; TV/anonymous denied; partner cannot query this owner', () => {
  assert.equal(readFinanceBaseline(fixture.empty, 'member1'), null); assert.equal(readFinanceBaseline(fixture.other, 'member2'), null);
  assert.equal(fixture.tvStatus, 403); assert.equal(fixture.anonymousStatus, 401);
  assert.throws(() => readFinanceBaseline(fixture.modern, 'member2'), BaselineError);
  assert.throws(() => readFinanceBaseline(undefined, 'member1'), BaselineError);
});
test('real source DTO projects bounded data and keeps unknown USD distinct from zero CNY', () => {
  const view = readFinanceBaseline(fixture.modern, 'member1');
  assert.equal(view.assets.length, 3); assert.equal(view.assets[1].amountCents, null); assert.equal(view.assets[1].currency, 'USD');
  assert.equal(view.assets[2].amountCents, 0); assert.equal(view.totals.recordedAssetCents, 12000); assert.equal(view.totals.netCents, null);
  assert(view.sourceBridge.files.length > 3); assert(view.assets[1].label.length > 100);
  assert(!JSON.stringify(view).includes('SYNTHETIC_MUST_NOT_RENDER')); assert(!JSON.stringify(view).includes('sourceDigest'));
});
test('real independent report changes consumption only, including negative net refunds', () => {
  const view = readFinanceBaseline(fixture.observation, 'member1');
  assert.equal(view.spendingObservation.origin, 'spending_observation'); assert.equal(view.spendingObservation.assetBaselineUnchanged, true);
  assert.equal(view.spending.monthly[0].netSpendCents, -100); assert.equal(view.spending.generatedAt, '2026-09-15T08:00:00+08:00');
  assert.equal(view.sourceBridge.generatedAt, fixture.modern.sourceBridge.manifest.run.generatedAt);
  assert.deepEqual(view.assets, readFinanceBaseline(fixture.modern, 'member1').assets);
});
test('real legacy DTO leaves missing metadata unknown while complete source keeps exact totals', () => {
  const old = readFinanceBaseline(fixture.legacy, 'member1'), complete = readFinanceBaseline(fixture.complete, 'member1');
  assert.equal(old.sourceBridge, null); assert.equal(old.spending.generatedAt, null); assert.equal(old.spending.quality, null);
  assert.equal(old.spending.monthly[0].currency, null); assert.equal(old.spending.monthly[0].grossSpendCents, null);
  assert.equal(old.spending.monthly[0].netSpendCents, 0); assert.equal(old.income[0].includedInRecordedSubtotal, null);
  assert.equal(complete.totals.complete, true); assert.equal(complete.totals.netCents, 7500);
});
test('malformed/unsafe amounts, subtotal changes, dates and missing core totals are rejected', () => {
  const mutations = [v => v.assets[0].amountCents = true, v => v.assets[0].amountCents = Number.MAX_SAFE_INTEGER + 1,
    v => v.assets[0].amountCents = 0.1, v => v.assets[0].currency = 'USD', v => v.totals.recordedAssetCents++,
    v => delete v.totals.netCents, v => v.totals.complete = true, v => v.asOf = '2026-02-30', v => v.importedAt = '2026-09-14',
    v => v.sourceDigest = 'unsafe', v => v.revision = false, v => v.spending.monthly[0].netSpendCents++, v => v.assets = Array(501).fill(v.assets[0])];
  for (const mutate of mutations) { const value = clone(fixture.modern); mutate(value); assert.throws(() => readFinanceBaseline(value, 'member1'), BaselineError); }
});
test('money display uses exact cents, nullable currency, signs and safe large integers', () => {
  assert.equal(formatBaselineMoney(null, 'USD'), '金额待核对'); assert.equal(formatBaselineMoney(0, 'CNY'), 'CNY 0.00');
  assert.equal(formatBaselineMoney(-101, 'USD'), 'USD -1.01'); assert.equal(formatBaselineMoney(100_000_000_000_000, 'CNY'), 'CNY 1,000,000,000,000.00');
  assert.equal(formatBaselineMoney(0, null), '币种待核对 0.00'); assert.throws(() => formatBaselineMoney(1.1, 'CNY'), BaselineError);
  assert.equal(formatBaselineTime(null), '日期待核对'); assert.match(formatBaselineTime('2026-09-14T16:30:00Z'), /2026\/09\/15 00:30/);
});
test('section pagination reaches every one of 500 rows and searches the entire section', () => {
  const rows = Array.from({ length: 500 }, (_, i) => ({ label: '合成来源 ' + i })); const seen = [];
  for (let p = 0; p < 50; p++) seen.push(...baselinePage(rows, '', p, x => x.label).rows);
  assert.deepEqual(seen, rows); assert.equal(baselinePage(rows, '来源 499', 49, x => x.label).rows[0].label, '合成来源 499');
  assert.equal(baselinePage([], '', 5, String).page, 0); assert.throws(() => baselinePage(rows, '', 0, String, 0), BaselineError);
});
test('fresh real session is required before and after reading every private DTO', async () => {
  const original = fixture.session;
  for (const changed of [null, { ...original, csrf: 'different' }, { ...original, user: null },
    ...['id','householdId','auth_version','role'].map(key => ({ ...original, user: { ...original.user, [key]: key === 'auth_version' ? 2 : 'different' } }))]) {
    let calls = 0;
    await assert.rejects(new BaselineFence(baselineSignature(original)).run(async () => ++calls === 1 ? original : changed, async () => fixture.modern, () => true), BaselineDiscarded);
    assert.equal(calls, 2);
  }
  let writes = 0; await assert.rejects(new BaselineFence(baselineSignature(original)).run(async () => ({ ...original, csrf: 'changed' }), async () => ++writes, () => true), BaselineDiscarded); assert.equal(writes, 0);
});
test('epoch/visibility changes discard late reads and a failed private read still checks identity', async () => {
  const session = fixture.session, fence = new BaselineFence(baselineSignature(session)); let release;
  const result = fence.run(async () => session, () => new Promise(resolve => { release = resolve; }), () => true);
  await new Promise(resolve => setImmediate(resolve)); fence.invalidate(); release(fixture.modern); await assert.rejects(result, BaselineDiscarded);
  let active = true; await assert.rejects(new BaselineFence(baselineSignature(session)).run(async () => session, async () => { active = false; return fixture.modern; }, () => active), BaselineDiscarded);
  let calls = 0; await assert.rejects(new BaselineFence(baselineSignature(session)).run(async () => { ++calls; return session; }, async () => { throw new BaselineError('read failed'); }, () => true), BaselineError); assert.equal(calls, 2);
});
test('transport is fixed GET only with same-origin/no-store/redirect refusal and no owner query', async () => {
  const original = globalThis.fetch; let requests = 0;
  try {
    globalThis.fetch = async (url, options) => { ++requests; assert.equal(url, '/api/finance-baseline/private'); assert.equal(options.method, 'GET');
      for (const [key,value] of Object.entries({mode:'same-origin',credentials:'same-origin',cache:'no-store',redirect:'error'})) assert.equal(options[key], value);
      assert.equal(options.body, undefined); return new Response(JSON.stringify(fixture.modern), {headers:{'Content-Type':'application/json'}}); };
    assert.equal(readFinanceBaseline(await baselineRequest('/finance-baseline/private', new AbortController().signal), 'member1').assets.length, 3);
    for (const path of ['https://example.com', '/finance-baseline/private?owner=member2', '/finance-baseline/imports/confirm']) await assert.rejects(baselineRequest(path, new AbortController().signal), BaselineError);
    assert.equal(requests, 1);
  } finally { globalThis.fetch = original; }
});
test('transport rejects authorization errors, non-JSON, invalid UTF-8 and oversized bodies', async () => {
  const original = globalThis.fetch;
  try {
    for (const status of [401,403,500]) { globalThis.fetch = async () => new Response('private diagnostics must not echo', {status}); await assert.rejects(baselineRequest('/me', new AbortController().signal), e => e instanceof BaselineError && e.status === status && !e.message.includes('diagnostics')); }
    for (const response of [new Response('<html>'), new Response(new Uint8Array([255]), {headers:{'Content-Type':'application/json'}}),
      new Response(' '.repeat(4_000_001), {headers:{'Content-Type':'application/json'}})]) {
      globalThis.fetch = async () => response; await assert.rejects(baselineRequest('/me', new AbortController().signal), BaselineError);
    }
  } finally { globalThis.fetch = original; }
});
test('external abort cancels in-flight transport and rejects late body completion', async () => {
  const original = globalThis.fetch, controller = new AbortController(); let started;
  try {
    globalThis.fetch = async (_url, options) => new Promise((_resolve,reject) => { started = true; options.signal.addEventListener('abort', () => reject(new Error('aborted')), {once:true}); });
    const pending = baselineRequest('/me', controller.signal); assert(started); controller.abort(); await assert.rejects(pending, BaselineDiscarded);
    let finish;
    globalThis.fetch = async () => new Response(new ReadableStream({start(control) { finish = () => { control.enqueue(new TextEncoder().encode('null')); control.close(); }; }}), {headers:{'Content-Type':'application/json'}});
    const other = new AbortController(), body = baselineRequest('/me', other.signal); await new Promise(resolve => setImmediate(resolve)); other.abort(); finish(); await assert.rejects(body, BaselineDiscarded);
  } finally { globalThis.fetch = original; }
});
