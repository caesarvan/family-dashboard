import assert from 'node:assert/strict';
import { test } from 'node:test';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { registerHooks } from 'node:module';
// Resolve the application's extensionless pure helper import without copying it.
registerHooks({ resolve(specifier, context, next) { if (specifier === './financeBaseline' && context.parentURL?.endsWith('/financeSourceImport.ts')) return next('./financeBaseline.ts', context); return next(specifier, context); } });
const model = await import('../frontend/src/lib/financeSourceImport.ts');
const { readSourceStatus, readSourcePreview, readSourceReceipt, readSourceOperation, parseSourceJSON, sourcePreviewBody, sourceStatusPath, sourceIntent,
  SourceError, SourceDiscarded, SourceRejected, SourceFence, sourceSignature, sourceActor, checkedSourceConfirm, permitsSourceRepreview, sourceRequest } = model;
const root = resolve(process.env.SOURCE_IMPORT_BACKEND_ROOT || fileURLToPath(new URL('..', import.meta.url)));
const setup = spawnSync(process.env.SOURCE_IMPORT_TEST_PYTHON || 'python', ['-B', '-X', 'utf8', '-c', String.raw`
import sys, os, json, tempfile, socket, sqlite3
from pathlib import Path
from contextlib import closing
from unittest.mock import patch
root=Path(sys.argv[1]).resolve();sys.path[:0]=[str(root),str(root/'tests')]
from app import create_app
from test_app import member
from test_finance_source_bridge import synthetic_candidate
from test_spending_observations import observation
from test_finance_import_sessions import prepare, status
from itsdangerous import TimestampSigner
def deny(*a,**kw):raise AssertionError('No external financial connections')
with tempfile.TemporaryDirectory(prefix='expo-source-import-model-') as folder, patch.object(socket.socket,'connect',deny), patch('socket.create_connection',deny), patch.dict(os.environ,{'MEMBER1_PASSWORD':'testing-password-one','MEMBER2_PASSWORD':'testing-password-two'}):
    app=create_app({'TESTING':True,'SECRET_KEY':'synthetic-source-ui-only','DATA_DIR':folder,'SESSION_COOKIE_SECURE':False})
    c,h=member(app);out={'session':c.get('/api/me').json,'baselineEmpty':status(c,'baseline').json,'spendingEmpty':status(c,'spending_observation').json}
    def counts():
        with closing(sqlite3.connect(Path(folder)/'household.sqlite3')) as con:
            return {t:con.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ['finance_baselines','finance_source_receipts','finance_spending_observations','finance_spending_receipts','hub_transactions','hub_investments']}
    candidate=synthetic_candidate(amount_cents=0)
    unknown=dict(candidate['assets'][0]);unknown.update(id='unknown-usd',label='尚未估值美元来源',amountCents=None,currency='USD',includedInRecordedSubtotal=False,exclusionReason='unconfirmed_foreign_record')
    candidate['assets'].append(unknown)
    before=counts();p,payload,body=prepare(c,h,'baseline',candidate);assert counts()==before
    out.update(candidate=candidate,baselinePreview=p,baselinePayload=payload,baselineBody=body)
    out['notFound']=status(c,'baseline',p['operationId']).json
    saved=c.post('/api/finance-baseline/imports/confirm',json=body,headers=h);assert saved.status_code==200,saved.json
    out['baselineReceipt']=saved.json
    first=counts();again=c.post('/api/finance-baseline/imports/confirm',json=body,headers=h);assert again.status_code==200 and counts()==first
    out['baselineReplay']=again.json;out['baselineStatus']=status(c,'baseline').json
    # New real login can find only its own history; no response substitute.
    renewed,renewed_h=member(app);out['baselineFound']=status(renewed,'baseline',p['operationId']).json
    partner,_=member(app,2);out['partnerFound']=status(partner,'baseline',p['operationId']).json
    candidate=observation(net=-100);candidate['spending']['monthly'].insert(0,{'period':'2026-08','currency':'CNY','grossSpendCents':1200,'refundCents':200,'netSpendCents':1000,'transactionCount':3})
    out['spendingBefore']=status(renewed,'spending_observation').json
    before=counts();p,payload,body=prepare(renewed,renewed_h,'spending_observation',candidate);assert counts()==before
    out.update(spendingCandidate=candidate,spendingPreview=p,spendingPayload=payload,spendingBody=body)
    saved=renewed.post('/api/finance-baseline/imports/confirm',json=body,headers=renewed_h);assert saved.status_code==200,saved.json
    out['spendingReceipt']=saved.json;out['spendingFound']=status(renewed,'spending_observation',p['operationId']).json
    out['spendingStatus']=status(renewed,'spending_observation').json
    after=counts();assert after['finance_baselines']==first['finance_baselines'] and after['finance_source_receipts']==first['finance_source_receipts']
    assert after['hub_transactions']==before['hub_transactions'] and after['hub_investments']==before['hub_investments']
    out['counts']=after
    # Real lock-side expiry has an exact recovery code; no new write or fabricated success.
    pending_candidate=synthetic_candidate(amount_cents=100)
    pending_candidate['assets'].append(unknown)
    pending,_,pending_body=prepare(renewed,renewed_h,'baseline',pending_candidate)
    tick=TimestampSigner.get_timestamp
    with patch.object(TimestampSigner,'get_timestamp',lambda self:tick(self)+1201):
        expired=renewed.post('/api/finance-baseline/imports/confirm',json=pending_body,headers=renewed_h)
    assert expired.status_code==410 and counts()==after
    out['expired']={'status':expired.status_code,'body':expired.json}
    tv=app.test_client();pair=tv.post('/api/pair/start',json={}).json
    assert renewed.post('/api/pair/approve',headers=renewed_h,json={'code':pair['code'],'name':'合成电视'}).status_code==200
    assert tv.post('/api/pair/poll',json={'secret':pair['secret']}).json['approved']
    out['tvDenied']=tv.get('/api/finance-baseline/imports/status?mode=baseline').status_code
    out['anonymousDenied']=app.test_client().get('/api/finance-baseline/imports/status?mode=baseline').status_code
print(json.dumps(out,ensure_ascii=False))
`, root], { cwd: root, encoding: 'utf8', timeout: 90_000, maxBuffer: 4_000_000 });
assert.equal(setup.status, 0, setup.stderr || setup.error?.message || 'Real fixture failed');
const f = JSON.parse(setup.stdout), clone = x => structuredClone(x);

test('real empty status preserves missing baseline and exact two-lane CAS inputs', () => {
  const baseline = readSourceStatus(f.baselineEmpty, 'baseline'), spending = readSourceStatus(f.spendingEmpty, 'spending_observation');
  assert.equal(baseline.baselineExists, false); assert.equal(spending.baselineExists, false);
  assert.deepEqual(sourcePreviewBody(baseline, parseSourceJSON(JSON.stringify(f.candidate), 'baseline'), false), f.baselinePayload);
  assert.throws(() => sourcePreviewBody(spending, f.spendingCandidate, true), SourceError);
  const before = readSourceStatus(f.spendingBefore, 'spending_observation');
  assert.deepEqual(sourcePreviewBody(before, f.spendingCandidate, false), f.spendingPayload);
  assert.throws(() => sourcePreviewBody({ ...before, unknownCoverage: true }, f.spendingCandidate, false), SourceError);
});
test('real baseline preview retains null/zero/currency and exposes only server-approved shared subtotal', () => {
  const view = readSourcePreview(f.baselinePreview, 'baseline', 'member1');
  assert.equal(view.rows.find(r => r.title === 'SYNTHETIC_PRIVATE_bank-one').amountCents, 0);
  assert.equal(view.rows.find(r => r.title === '尚未估值美元来源').amountCents, null);
  assert.equal(view.rows.find(r => r.title === '尚未估值美元来源').currency, 'USD');
  assert.equal(view.shared.assets, 0); assert.equal(view.shared.liabilities, 4500); assert.equal(view.changes.added, 4);
  assert(view.files.length > 3); assert.equal(view.coverage.quality.knownGapsCount, 1);
  assert.throws(() => readSourcePreview(f.baselinePreview, 'baseline', 'member2'), SourceError);
});
test('real spending preview keeps negative net refunds and baseline unchanged semantics', () => {
  const view = readSourcePreview(f.spendingPreview, 'spending_observation', 'member1');
  assert.equal(view.shared, null); assert.equal(view.rows.find(r => r.date === '2026-09').amountCents, -100);
  assert.equal(view.rows.find(r => r.date === '2026-09').gross, 100); assert.equal(view.rows.find(r => r.date === '2026-09').refund, 200);
  assert.equal(f.counts.finance_source_receipts, 1); assert.equal(f.counts.finance_spending_receipts, 1);
});
test('frozen original bodies match the exact real confirm schema for both lanes', () => {
  for (const [mode, candidate, preview, body] of [['baseline', f.candidate, f.baselinePreview, f.baselineBody], ['spending_observation', f.spendingCandidate, f.spendingPreview, f.spendingBody]]) {
    const parsed = parseSourceJSON(JSON.stringify(candidate), mode), intent = sourceIntent(readSourcePreview(preview, mode, 'member1'), parsed, sourceSignature(f.session));
    assert.deepEqual(intent.body, body); assert(Object.isFrozen(intent.body)); assert(Object.isFrozen(parsed)); assert(Object.isFrozen(parsed.sourceManifest));
    assert.equal(intent.operationId, preview.operationId); assert(!('expectedRevision' in intent.body));
    assert.deepEqual(model.sourceOperation(intent), {mode,operationId:preview.operationId}); // Background memory must never retain the body/token/identity.
  }
});
test('real committed response, exact GET and replay preserve one receipt; not-found stays inconclusive', () => {
  const operation = {mode:'baseline',operationId:f.baselinePreview.operationId};
  assert.equal(readSourceOperation(f.notFound, operation), null);
  assert.equal(readSourceOperation(f.partnerFound, operation), null);
  assert.equal(readSourceReceipt(f.baselineReceipt, operation, f.baselinePreview.candidateDigest).replayed, false);
  assert.equal(readSourceOperation(f.baselineFound, operation).receiptId, f.baselineReceipt.receiptId);
  assert.equal(readSourceReceipt(f.baselineReplay, operation).replayed, true);
  assert.equal(readSourceOperation(f.spendingFound, {mode:'spending_observation',operationId:f.spendingPreview.operationId}).receiptId, f.spendingReceipt.receiptId);
  assert.equal(f.tvDenied,403); assert.equal(f.anonymousDenied,401);
});
test('invalid scope/receipt/amount/token/calendar DTOs fail closed without leaking extras', () => {
  for (const change of [v=>v.private.owner='member2',v=>v.private.assets[0].amountCents=0.2,v=>v.private.asOf='2026-02-30',v=>v.private.spending.generatedAt='nonsense+08:00',v=>v.operationId='../unsafe',v=>v.previewToken='',v=>v.private.assets=Array(501).fill(v.private.assets[0])]) {
    const value=clone(f.baselinePreview);change(value);assert.throws(()=>readSourcePreview(value,'baseline','member1'),SourceError);
  }
  const operation={mode:'baseline',operationId:f.baselinePreview.operationId};
  assert.throws(()=>readSourceOperation({...f.baselineFound,mode:'spending_observation'},operation),SourceError);
  assert.throws(()=>readSourceReceipt({...f.baselineReceipt,receiptId:'b'.repeat(64)},operation),SourceError);
  const extra=clone(f.baselinePreview);extra.private.secret='DO_NOT_RENDER';assert(!JSON.stringify(readSourcePreview(extra,'baseline','member1')).includes('DO_NOT_RENDER'));
});
test('candidate limits reject malformed/unsafe/deep content and wrong lane without repairing financial values', () => {
  for (const raw of ['', '{bad', '[]', '{"__proto__":{}}', '{"x":9007199254740992}', ' '.repeat(model.MAX_SOURCE_BYTES), JSON.stringify({x:'😀'.repeat(600_000)})]) assert.throws(()=>parseSourceJSON(raw,'baseline'),SourceError);
  assert.throws(()=>parseSourceJSON(JSON.stringify(f.spendingCandidate),'baseline'),SourceError);
  const parsed=parseSourceJSON(JSON.stringify({...f.candidate,assets:[{amountCents:1.1}]}),'baseline');assert.equal(parsed.assets[0].amountCents,1.1); // The real server diagnoses business errors.
});
test('exact paths never accept owner scope, foreign host or ambiguous operation identifier', () => {
  assert.equal(sourceStatusPath('baseline','a'.repeat(64)),'/finance-baseline/imports/status?mode=baseline&operationId='+'a'.repeat(64));
  for (const id of ['a'.repeat(63),'A'.repeat(64),'../secret','a'.repeat(64)+'&owner=member2']) assert.throws(()=>sourceStatusPath('baseline',id),SourceError);
  assert.notEqual(sourceActor(f.session),sourceActor({...f.session,user:{...f.session.user,householdId:'other'}}));
});
test('real found=false never unlocks alone: guarded status plus explicit same-identity decision is required', () => {
  const operation={mode:'baseline',operationId:f.baselinePreview.operationId}, identity=sourceSignature(f.session), status=readSourceStatus(f.baselineStatus,'baseline');
  const receipt=readSourceOperation(f.notFound,operation), review=model.sourceEndReview(operation,status,receipt,identity);
  assert.equal(receipt,null);assert.equal(model.canEndSourceReview(null,operation,identity,true),false);
  assert.equal(model.canEndSourceReview(review,operation,identity,false),false);
  assert.equal(model.canEndSourceReview(review,operation,identity,true),true);
  assert.equal(model.canEndSourceReview(review,operation,sourceSignature({...f.session,csrf:'new'}),true),false);
  assert.equal(model.canEndSourceReview(review,{...operation,operationId:'a'.repeat(64)},identity,true),false);
  assert.equal(model.sourceEndReview(operation,status,readSourceReceipt(f.baselineReceipt,operation),identity),null);
});
test('opaque memory isolates household/member and a stale handle cannot clear a newer recovery', () => {
  const memory=new model.SourceRecoveryMemory(), actor=sourceActor(f.session), other=sourceActor({...f.session,user:{...f.session.user,householdId:'other'}});
  const original={mode:'baseline',operationId:f.baselinePreview.operationId}, next={mode:'spending_observation',operationId:f.spendingPreview.operationId};
  memory.set(actor,{...original,body:f.baselineBody,secret:'NEVER_RETAIN'});memory.set(other,next);
  assert.deepEqual(memory.get(actor),original);assert.equal(memory.clear(other,original),false);assert.deepEqual(memory.get(other),next);
  memory.set(actor,next);assert.equal(memory.clear(actor,original),false);assert.deepEqual(memory.get(actor),next);
  assert.equal(memory.clear(actor,next),true);assert.equal(memory.get(actor),null);assert.deepEqual(memory.get(other),next);
});
test('preflight identity failure dispatches no write; after-identity failure never becomes a definitive rejection', async () => {
  let writes=0;const changed={...f.session,csrf:'different'};
  const before=new SourceFence(sourceSignature(f.session));
  await assert.rejects(checkedSourceConfirm(job=>before.run(async()=>changed,job,()=>true),async()=>++writes),SourceDiscarded);assert.equal(writes,0);
  for(const status of [401,403,429]) {let reads=0;const fence=new SourceFence(sourceSignature(f.session));
    await assert.rejects(checkedSourceConfirm(job=>fence.run(async()=>{if(++reads===2)throw new SourceError('after',status);return f.session;},job,()=>true),async()=>{++writes;throw new SourceError('mutation',409);}), e=>e instanceof SourceError && !(e instanceof SourceRejected) && e.status===status);
  }
});
test('epoch/visibility and every complete identity field reject late private results', async () => {
  for(const key of ['id','householdId','auth_version','role']) {let reads=0;const changed={...f.session,user:{...f.session.user,[key]:key==='auth_version'?999:'other'}};
    await assert.rejects(new SourceFence(sourceSignature(f.session)).run(async()=>++reads===1?f.session:changed,async()=>f.baselinePreview,()=>true),SourceDiscarded);
  }
  const fence=new SourceFence(sourceSignature(f.session));let release;
  const response=fence.run(async()=>f.session,()=>new Promise(resolve=>release=resolve),()=>true);await new Promise(resolve=>setImmediate(resolve));fence.invalidate();release(f.baselinePreview);await assert.rejects(response,SourceDiscarded);
});
test('only proven exact expired/legacy no-receipt errors release a prior unknown operation', async () => {
  const actual=f.expired;assert.equal(actual.body.code,'preview_expired');
  assert(permitsSourceRepreview(new SourceRejected(actual.body.error,actual.status,actual.body.code)));
  for(const [status,code,allowed] of [[410,'preview_expired',true],[409,'preview_repreview_required',true],[410,'anything',false],[409,'stale',false],[404,'preview_expired',false]]) {
    let error;try{await checkedSourceConfirm(job=>job('csrf'),async()=>{throw new SourceError('rejected',status,code);});}catch(e){error=e;}
    assert.equal(permitsSourceRepreview(error),allowed);
  }
  assert.equal(permitsSourceRepreview(new SourceError('after-me',410,'preview_expired')),false);
});
test('transport is bounded same-origin, no-store, no redirects, strict methods and exact paths', async () => {
  const original=globalThis.fetch;let calls=0;
  try {globalThis.fetch=async(url,options)=>{calls++;assert.equal(url,'/api'+sourceStatusPath('baseline'));for(const [key,value] of Object.entries({method:'GET',mode:'same-origin',credentials:'same-origin',cache:'no-store',redirect:'error'}))assert.equal(options[key],value);assert.equal(options.body,undefined);return new Response(JSON.stringify(f.baselineStatus),{headers:{'Content-Type':'application/json'}});};
    assert(readSourceStatus(await sourceRequest(sourceStatusPath('baseline'),new AbortController().signal),'baseline').baselineExists);
    for(const path of ['https://external.invalid','/finance-baseline/private','/finance-baseline/imports/status?owner=member2','/finance-baseline/imports/confirm'])await assert.rejects(sourceRequest(path,new AbortController().signal),SourceError);
    assert.equal(calls,1);
  }finally{globalThis.fetch=original;}
});
test('transport retains auth status but never renders non-JSON errors; oversized and late bodies rejected',async()=>{
  const original=globalThis.fetch;try{
    for(const status of [401,403,500]) {globalThis.fetch=async()=>new Response('PRIVATE SERVER DETAILS',{status});await assert.rejects(sourceRequest('/me',new AbortController().signal),e=>e instanceof SourceError&&e.status===status&&!e.message.includes('PRIVATE'));}
    for(const response of [new Response(new Uint8Array([255]),{headers:{'Content-Type':'application/json'}}),new Response(' '.repeat(4_000_001),{headers:{'Content-Type':'application/json'}})]) {globalThis.fetch=async()=>response;await assert.rejects(sourceRequest('/me',new AbortController().signal),SourceError);}
    const controller=new AbortController();globalThis.fetch=async()=>{controller.abort();return new Response(JSON.stringify(f.session),{headers:{'Content-Type':'application/json'}});};await assert.rejects(sourceRequest('/me',controller.signal),SourceDiscarded);
  }finally{globalThis.fetch=original;}
});
