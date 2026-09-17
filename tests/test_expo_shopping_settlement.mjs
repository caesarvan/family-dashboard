import assert from 'node:assert/strict';
import { test } from 'node:test';
import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as m from '../frontend/src/lib/shoppingSettlement.ts';
import { decimalInput } from '../frontend/src/lib/finance.ts';

const root = resolve(process.env.SETTLEMENT_BACKEND_ROOT || fileURLToPath(new URL('..', import.meta.url)));
// Real installed handlers and synthetic temporary SQLite. No copied business
// module, fake success response, personal input, provider or running server.
const execution = spawnSync(process.env.SETTLEMENT_TEST_PYTHON || 'python', ['-B', '-X', 'utf8', '-c', String.raw`
import sys, os, json, tempfile, socket, sqlite3, subprocess
from pathlib import Path
from contextlib import closing
from unittest.mock import patch
root=Path(sys.argv[1]).resolve();sys.path[:0]=[str(root),str(root/'tests')]
import app as server
from test_app import member
from test_shopping_settlement import record, shopping, context, plan, item
from shopping_settlement import PREFIX
def link_context(client, link):
    # The same pure query builder used by Panel generates the URL dispatched to
    # the real temporary Flask app, including stale original entry/draft IDs.
    focus={'shoppingId':link['shoppingId'],'transactionId':link['paymentId']}
    draft={'shoppingId':link['shoppingId'],'paymentId':link['paymentId'],'linkId':link['id']}
    script="import{readFileSync}from'node:fs';const m=await import(process.argv[1]);const x=JSON.parse(readFileSync(0,'utf8'));const q=m.settlementReadQuery(x.focus,x.draft,{q:'',page:0});process.stdout.write(JSON.stringify({query:q,path:m.settlementQuery(q)}));"
    generated=subprocess.run([sys.argv[2],'--experimental-transform-types','--input-type=module','-e',script,sys.argv[3]],input=json.dumps({'focus':focus,'draft':draft}),capture_output=True,text=True,encoding='utf-8',timeout=20)
    assert generated.returncode==0,generated.stderr
    selected=json.loads(generated.stdout)
    stale=client.get(PREFIX+'/context',query_string={**focus,'linkId':link['id'],'page':0})
    response=client.get('/api'+selected['path'])
    assert stale.status_code==404,(stale.status_code,stale.json)
    assert response.status_code==200,(response.status_code,response.json)
    return {**selected,'staleStatus':stale.status_code,'status':response.status_code,'context':response.json}
def deny(*a,**kw):raise AssertionError('No network')
with tempfile.TemporaryDirectory(prefix='expo-settlement-model-') as folder, patch.object(socket.socket,'connect',deny), patch('socket.create_connection',deny), patch.dict(os.environ,{'MEMBER1_PASSWORD':'testing-password-one','MEMBER2_PASSWORD':'testing-password-two'}):
    app=server.create_app({'TESTING':True,'SECRET_KEY':'synthetic-settlement-model','DATA_DIR':folder,'SESSION_COOKIE_SECURE':False})
    c,h=member(app);out={'session':c.get('/api/me').json,'empty':context(c)}
    pay=record(c,h,'合成付款', '100.00');foreign=record(c,h,'合成外币','5.00',currency='USD')
    record(c,h,'合成账本最大金额','1000000000000.00')
    order=record(c,h,'合成订单','100.00',kind='orders')
    shop=shopping(c,h,title='合成旅行插头',actual=None);zero=shopping(c,h,title='合成零实付',actual=0)
    def post(path,body,status=200):
        r=c.post(PREFIX+path,json=body,headers=h);assert r.status_code==status,(r.status_code,r.json);return r.json
    def snapshot():
        with closing(sqlite3.connect(Path(folder)/'household.sqlite3')) as con:
            return {name:con.execute('SELECT * FROM '+name+' ORDER BY rowid').fetchall() for name in ['hub_transactions','hub_budgets','hub_reconciliations']}
    unchanged=snapshot();out.update(shop=shop,pay=pay,zero=zero,initial=context(c,shoppingId=shop['id']),orderContext=context(c,transactionId=order['id']))
    p=plan(pay,shop,7000,False);preview=post('/preview',p);receipt=post('/confirm',{'previewToken':preview['previewToken']})
    out.update(applyPlan=p,applyPreview=preview,applied=receipt,replay=post('/confirm',{'previewToken':preview['previewToken']}),afterApply=context(c,shoppingId=shop['id']))
    p={'operation':'update','linkId':receipt['link']['id'],'revision':receipt['link']['revision'],'shoppingRevision':receipt['shopping']['revision'],'amountCents':5000,'done':True}
    preview=post('/preview',p);receipt=post('/confirm',{'previewToken':preview['previewToken']});out.update(updatePlan=p,updatePreview=preview,updated=receipt,afterUpdate=context(c,shoppingId=shop['id']))
    assert snapshot()==unchanged
    refund=record(c,h,'合成部分退款','10.00',flow='refund')
    rp=c.post('/api/finance-hub/reconciliation/preview',headers=h,json={'kind':'refund_payment','leftId':refund['id'],'rightId':pay['id'],'amount':'10.00'});assert rp.status_code==200,rp.json
    rr=c.post('/api/finance-hub/reconciliation/confirm',headers=h,json={'previewToken':rp.json['previewToken']});assert rr.status_code==200,rr.json
    out['needsReview']=context(c,shoppingId=shop['id']);p={'operation':'revoke','linkId':receipt['link']['id'],'revision':receipt['link']['revision'],'shoppingRevision':receipt['shopping']['revision'],'mode':'detach_keep_current'}
    preview=post('/preview',p);receipt=post('/confirm',{'previewToken':preview['previewToken']});out.update(revokePlan=p,revokePreview=preview,revoked=receipt,afterRevoke=context(c,shoppingId=shop['id']))
    # A second, explicitly new operation has its own receipt, then the shopping
    # record is deleted. Detach must not resurrect it or invent zero values.
    p=plan(pay,item(c,shop['id']),4000,True);preview=post('/preview',p);receipt=post('/confirm',{'previewToken':preview['previewToken']})
    assert c.delete('/api/items/shopping/'+shop['id'],headers=h,json={'revision':receipt['shopping']['revision']}).status_code==200
    out['deletedShoppingRead']=link_context(c,receipt['link']);ctx=out['deletedShoppingRead']['context'];p={'operation':'revoke','linkId':receipt['link']['id'],'revision':receipt['link']['revision'],'shoppingRevision':None,'mode':'detach_keep_current'}
    preview=post('/preview',p);receipt=post('/confirm',{'previewToken':preview['previewToken']});out.update(deletedContext=ctx,deletedPlan=p,deletedPreview=preview,deletedReceipt=receipt)
    other,_=member(app,2);out['partner']=context(other);out['partnerFocus']=other.get(PREFIX+'/context?transactionId='+pay['id']).status_code
    for n in range(41):shopping(c,h,title='合成分页'+str(n))
    out['page0']=context(c);out['page1']=context(c,page=1,shoppingId=zero['id'])
    missing_pay=record(c,h,'合成已移除付款','4.00');p=plan(missing_pay,item(c,zero['id']),100,False)
    preview=post('/preview',p);receipt=post('/confirm',{'previewToken':preview['previewToken']})
    assert c.delete('/api/finance-hub/transactions/'+missing_pay['id'],headers=h,json={'revision':missing_pay['revision']}).status_code==200
    out['deletedPaymentRead']=link_context(c,receipt['link'])
    p={'operation':'revoke','linkId':receipt['link']['id'],'revision':receipt['link']['revision'],'shoppingRevision':receipt['shopping']['revision'],'mode':'detach_keep_current'}
    preview=post('/preview',p);receipt=post('/confirm',{'previewToken':preview['previewToken']})
    out.update(deletedPaymentPlan=p,deletedPaymentPreview=preview,deletedPaymentReceipt=receipt)
    assert item(c,zero['id'])['actual']==100
    out['counts']={'receipts':0}
    with closing(sqlite3.connect(Path(folder)/'household.sqlite3')) as con:out['counts']['receipts']=con.execute('SELECT count(*) FROM hub_shopping_settlement_receipts').fetchone()[0]
print(json.dumps(out,ensure_ascii=False))
`, root, process.execPath, new URL('../frontend/src/lib/shoppingSettlement.ts', import.meta.url).href], { cwd: root, encoding: 'utf8', timeout: 120000, maxBuffer: 3000000 });
assert.equal(execution.status, 0, execution.stderr || execution.error?.message || 'Real temporary API fixture failed');
const f = JSON.parse(execution.stdout), clone = v => structuredClone(v);
const initial = () => m.readSettlementContext(f.initial, { shoppingId: f.shop.id });
const intent = () => m.readSettlementPreview(f.applyPreview, f.applyPlan, initial(), 1000);
const draft = () => ({ operation: 'apply', shoppingId: f.shop.id, paymentId: f.pay.id, linkId: '', amount: '70.00', done: false, mode: 'detach_keep_current', dirty: true });

test('real context keeps null, zero, CNY eligibility, order-only sources and owner isolation', () => {
  assert.equal(m.readSettlementContext(f.empty).payments.length, 0);
  const c = initial(); assert.equal(c.shopping.find(s=>s.id===f.shop.id).actual,null);assert.equal(c.shopping.find(s=>s.id===f.zero.id).actual,0);
  assert.equal(c.payments.find(p=>p.currency==='USD').reasonCode,'unsupported_currency');
  assert.equal(c.payments.find(p=>p.title==='合成账本最大金额').amountCents,100000000000000);
  assert.equal(m.readSettlementContext(f.orderContext,{transactionId:f.orderContext.transaction.id}).payments.length,0);
  assert.equal(m.readSettlementContext(f.partner).payments.length,0);assert.equal(f.partnerFocus,404);
  assert.equal(m.readSettlementContext(f.partner).links.length,0);
});
test('real independent page flags and pinned records are accepted, wrong pages/focus rejected', () => {
  assert.equal(m.readSettlementContext(f.page0).pageInfo.shoppingMore,true);
  const c=m.readSettlementContext(f.page1,{page:1,shoppingId:f.zero.id});assert(c.shopping.some(s=>s.id===f.zero.id));
  assert.throws(()=>m.readSettlementContext(f.page1));assert.throws(()=>m.readSettlementContext(f.page1,{page:1,transactionId:'foreign'}));
});
test('DTO projects only allowed fields and rejects duplicate rows, unsafe amounts and false eligibility', () => {
  const raw=clone(f.initial);raw.privateToken='never render';raw.payments[0].secret='never render';const c=m.readSettlementContext(raw);
  assert(!('privateToken'in c));assert(!('secret'in c.payments[0]));
  for(const mutate of [r=>r.payments.push(r.payments[0]),r=>r.shopping[0].actual=-1,r=>r.shopping[0].done='true',r=>r.payments[0].availableCents=Number.MAX_SAFE_INTEGER+1,r=>r.payments.find(p=>p.currency==='USD').eligible=true]){
    const r=clone(f.initial);mutate(r);assert.throws(()=>m.readSettlementContext(r));
  }
});
test('exact decimal helper plus integer payload admits zero and maximum without float multiplication', () => {
  for(const [text,expected]of [['0',0],['0.01',1],['70.10',7010],['1000000000.00',100000000000]]){
    const cents=Number(BigInt(decimalInput(text,false,1000000000n).replace('.','')));
    assert.equal(m.settlementPlan(initial(),draft(),cents).amountCents,expected);
  }
  for(const text of ['1e2','0.001','-1','1,000','1000000000.01'])assert.throws(()=>decimalInput(text,false,1000000000n));
  assert.deepEqual(m.settlementPlan(initial(),draft(),7000),f.applyPlan);
  assert.throws(()=>m.settlementPlan(initial(),draft(),100000000001));
});
test('existing active relation cannot accidentally create another; updates keep original identities', () => {
  const c=m.readSettlementContext(f.afterApply);assert.throws(()=>m.settlementPlan(c,draft(),100));
  const d={...draft(),operation:'update',linkId:f.applied.link.id,done:true};assert.deepEqual(m.settlementPlan(c,d,5000),f.updatePlan);
  assert.throws(()=>m.settlementPlan(c,{...d,paymentId:'other'},5000));
  assert.throws(()=>m.settlementPlan(initial(),{...draft(),paymentId:initial().payments.find(p=>p.currency==='USD').id},500));
});
test('actual preview and immediate receipt match exact target/fields; same token replay changes nothing', () => {
  const i=intent();assert.equal(i.expiresAt,601000);assert(Object.isFrozen(i.plan));
  const receipt=m.readSettlementReceipt(f.applied,i);assert.equal(receipt.shopping.actual,7000);assert.equal(receipt.shopping.done,false);
  assert(m.readSettlementReceipt(f.replay,i).replayed);assert.equal(f.counts.receipts,7);
  assert.throws(()=>m.readSettlementReceipt(f.afterApply,i));
  for(const mutate of [r=>r.shopping.id='different',r=>r.shopping.actual++,r=>r.link.paymentId='other',r=>r.operation='revoke',r=>r.changedFields=[],r=>r.link.revision++]){
    const raw=clone(f.applied);mutate(raw);assert.throws(()=>m.readSettlementReceipt(raw,i));
  }
});
test('preview mismatched amount, target, sharing fields or versions fails closed', () => {
  for(const mutate of [r=>r.after.actual++,r=>r.after.shoppingId='foreign',r=>r.before.revision++,r=>r.payment.currency='USD',r=>r.sharing.fields.push('title'),r=>r.sharing.ledgerUnchanged=false,r=>r.expiresInSeconds=1800]){
    const raw=clone(f.applyPreview);mutate(raw);assert.throws(()=>m.readSettlementPreview(raw,f.applyPlan,initial()));
  }
});
test('real refund warnings, update, revoke and deleted-target detach are read without revival', () => {
  const u=m.readSettlementPreview(f.updatePreview,f.updatePlan,m.readSettlementContext(f.afterApply));assert.equal(m.readSettlementReceipt(f.updated,u).shopping.done,true);
  const c=m.readSettlementContext(f.needsReview);assert(c.links[0].reviewReasons.includes('source_changed'));assert.equal(c.payments.find(p=>p.id===f.pay.id).refundedCents,1000);
  const r=m.readSettlementPreview(f.revokePreview,f.revokePlan,c);assert.equal(m.readSettlementReceipt(f.revoked,r).link.status,'revoked');
  const deleted=m.readSettlementPreview(f.deletedPreview,f.deletedPlan,m.readSettlementContext(f.deletedContext));assert.equal(deleted.preview.before,null);assert.equal(m.readSettlementReceipt(f.deletedReceipt,deleted).shopping,null);
});
test('Panel query builder reads stale linked objects through real link-only context and explicit detach', () => {
  for (const [entry, reason] of [[f.deletedShoppingRead, 'shopping_missing'], [f.deletedPaymentRead, 'source_missing']]) {
    assert.equal(entry.staleStatus,404);assert.equal(entry.status,200);
    assert.deepEqual(Object.keys(entry.query).sort(),['linkId','page','q']);
    const c=m.readSettlementContext(entry.context,entry.query), link=c.links.find(v=>v.id===entry.query.linkId);
    assert(link.reviewReasons.includes(reason));assert(!new URLSearchParams(entry.path.split('?')[1]).has('shoppingId'));
    assert(!new URLSearchParams(entry.path.split('?')[1]).has('transactionId'));
  }
  const c=m.readSettlementContext(f.deletedPaymentRead.context,f.deletedPaymentRead.query);
  const i=m.readSettlementPreview(f.deletedPaymentPreview,f.deletedPaymentPlan,c);
  assert.equal(m.readSettlementReceipt(f.deletedPaymentReceipt,i).link.status,'revoked');
  const focus={shoppingId:f.shop.id,transactionId:f.pay.id}, d={...draft(),linkId:f.deletedPlan.linkId}, original=clone(focus), unknown=intent();
  m.settlementReadQuery(focus,d,{q:'字',page:2});assert.deepEqual(focus,original);assert.equal(unknown.plan.shoppingId,f.shop.id);
  assert.deepEqual(m.settlementReadQuery(focus,d,{q:'字',page:2,unscoped:true}),{q:'',page:0});
  assert.deepEqual(m.settlementReadQuery(focus,{...d,linkId:''},{q:'',page:0}),{...focus,q:'',page:0});
  assert.equal(m.settlementReadQuery(focus,d,{q:'',page:0,receiptLinkId:f.applied.link.id}).linkId,f.applied.link.id);
});

test('only exact original unknown handle with current actor/lifetime can end local review', () => {
  const i=intent(),identity=m.settlementSignature(f.session),review={intent:i,identity,epoch:4};
  assert(m.canEndSettlementReview(review,i,identity,4));assert(!m.canEndSettlementReview(null,i,identity,4));
  assert(!m.canEndSettlementReview(review,intent(),identity,4));assert(!m.canEndSettlementReview(review,i,identity,5));assert(!m.canEndSettlementReview(review,i,'other',4));
});
test('fresh preflight blocks identity changes without dispatch; postflight rejects all late identities', async () => {
  for(const field of ['role','id','householdId','auth_version','csrf']){
    const changed=clone(f.session);if(field==='csrf')changed.csrf+='different';else changed.user[field]=field==='auth_version'?changed.user.auth_version+1:'different';
    const fence=new m.SettlementFence(m.settlementSignature(f.session));let writes=0;
    await assert.rejects(fence.run(async()=>changed,async()=>++writes,()=>true),m.SettlementDiscarded);assert.equal(writes,0);
    let calls=0;await assert.rejects(fence.run(async()=>++calls===1?f.session:changed,async()=>++writes,()=>true),m.SettlementDiscarded);assert.equal(writes,1);
  }
});
test('conceal invalidation discards late responses and definite rejection requires successful after-me',async()=>{
  const fence=new m.SettlementFence(m.settlementSignature(f.session));let release;const wait=new Promise(r=>release=r);
  const pending=fence.run(async()=>f.session,async()=>{await wait;return f.applied;},()=>true);await Promise.resolve();fence.invalidate();release();await assert.rejects(pending,m.SettlementDiscarded);
  const guard=job=>fence.run(async()=>f.session,job,()=>true);
  await assert.rejects(m.checkedSettlementWrite(guard,async()=>{throw new m.SettlementError('conflict',409);}),m.SettlementRejected);
  for(const status of [0,401,500])await assert.rejects(m.checkedSettlementWrite(guard,async()=>{throw new m.SettlementError('unknown',status);}),e=>!(e instanceof m.SettlementRejected));
  let calls=0;await assert.rejects(m.checkedSettlementWrite(job=>fence.run(async()=>{if(++calls===2)throw new Error('lost after-me');return f.session;},job,()=>true),async()=>{throw new m.SettlementError('conflict',409);}),e=>!(e instanceof m.SettlementRejected));
});
test('transport permits only original three routes, exact write fields, and no owner or invented operations',async()=>{
  const old=globalThis.fetch;let calls=0;globalThis.fetch=async()=>{calls++;throw Error('unexpected');};
  try{const signal=new AbortController().signal;
    for(const [path,options]of [['https://example.test',{}],[m.SETTLEMENT_PATH+'/operations/key',{}],[m.SETTLEMENT_PATH+'/context?owner=member2',{}],[m.SETTLEMENT_PATH+'/context?page=1&page=2',{}],
      [m.SETTLEMENT_PATH+'/confirm',{payload:{previewToken:f.applyPreview.previewToken,owner:'member2'},csrf:'x'}],[m.SETTLEMENT_PATH+'/preview',{payload:{...f.applyPlan,title:'private'},csrf:'x'}]])
      await assert.rejects(m.settlementRequest(path,signal,options));
    assert.equal(calls,0);assert(m.settlementQuery({shoppingId:f.shop.id,q:'合成 & 字',page:2}).includes('page=2'));
  }finally{globalThis.fetch=old;}
});
test('transport bounds responses, refuses redirects/non-JSON and preserves status without raw errors',async()=>{
  const old=globalThis.fetch, signal=new AbortController().signal;
  try{
    globalThis.fetch=async(path,options)=>{assert.equal(path,'/api'+m.SETTLEMENT_PATH+'/confirm');assert.equal(options.cache,'no-store');assert.equal(options.redirect,'error');assert.equal(options.credentials,'same-origin');
      assert.deepEqual(JSON.parse(options.body),{previewToken:f.applyPreview.previewToken});return new Response(JSON.stringify(f.applied),{headers:{'Content-Type':'application/json'}});};
    assert.deepEqual(await m.settlementRequest(m.SETTLEMENT_PATH+'/confirm',signal,{payload:{previewToken:f.applyPreview.previewToken},csrf:'x'}),f.applied);
    for(const response of [new Response('x',{headers:{'Content-Type':'text/html'}}),new Response('x',{headers:{'Content-Type':'application/json','Content-Length':'512001'}}),new Response('x'.repeat(512001),{headers:{'Content-Type':'application/json'}}),new Response('{',{headers:{'Content-Type':'application/json'}})]){
      globalThis.fetch=async()=>response;await assert.rejects(m.settlementRequest('/me',signal),m.SettlementError);
    }
    globalThis.fetch=async()=>new Response('sensitive failure',{status:409});await assert.rejects(m.settlementRequest('/me',signal),e=>e.status===409&&!e.message.includes('sensitive'));
  }finally{globalThis.fetch=old;}
});
