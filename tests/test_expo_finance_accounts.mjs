import assert from 'node:assert/strict';
import { test } from 'node:test';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import * as model from '../frontend/src/lib/financeAccounts.ts';

const root = resolve(process.env.FINANCE_ACCOUNTS_BACKEND_ROOT || fileURLToPath(new URL('..', import.meta.url)));
// One fixed backend tree; only route registration is adapted until app wiring lands.
// Every financial DTO below is produced by real HTTP handlers + temporary SQLite.
const setup = spawnSync(process.env.FINANCE_ACCOUNTS_TEST_PYTHON || 'python', ['-B', '-X', 'utf8', '-c', String.raw`
import sys, os, json, tempfile, socket, sqlite3
from pathlib import Path
from contextlib import closing
from unittest.mock import patch
root=Path(sys.argv[1]).resolve();sys.path[:0]=[str(root),str(root/'tests')]
import app as server
from finance_accounts import register_finance_accounts
from test_app import member
def deny(*a,**kw):raise AssertionError('No external finance or network')
original=server.register_finance_hub
def register(app,db,Problem,body,require_member,audit):
    original(app,db,Problem,body,require_member,audit)
    if '/api/finance-accounts' not in {r.rule for r in app.url_map.iter_rules()}:
        register_finance_accounts(app,db,Problem,body,require_member,audit)
with tempfile.TemporaryDirectory(prefix='expo-accounts-model-') as folder, patch.object(socket.socket,'connect',deny), patch('socket.create_connection',deny), patch.dict(os.environ,{'MEMBER1_PASSWORD':'testing-password-one','MEMBER2_PASSWORD':'testing-password-two'}), patch.object(server,'register_finance_hub',register):
    app=server.create_app({'TESTING':True,'SECRET_KEY':'synthetic-accounts-ui-only','DATA_DIR':folder,'SESSION_COOKIE_SECURE':False})
    c,h=member(app);url='/api/finance-accounts';seq=0
    def key():
        global seq
        seq+=1;return format(seq,'032x')
    def counts():
        with closing(sqlite3.connect(Path(folder)/'household.sqlite3')) as con:
            return {t:con.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ['finance_accounts','finance_account_valuations','finance_account_operations','finance_baselines','hub_transactions','hub_investments']}
    def listing(day='2026-09-17',status='all',client=None):
        r=(client or c).get(url,query_string={'asOf':day,'status':status});assert r.status_code==200,r.json;return r.json
    def create(name,amount=0,currency='CNY',kind='asset'):
        body={'requestId':key(),'revision':0,'name':name,'institution':'合成机构','kind':kind,'currency':currency,'note':'仅测试\n第二行','valuation':{'asOf':'2026-09-17','amountCents':amount}}
        r=c.post(url,json=body,headers=h);assert r.status_code==201,r.json;return body,r.json
    out={'session':c.get('/api/me').json,'empty':listing()};before=counts()
    body,receipt=create('合成零余额账户');out.update(createBody=body,created=receipt)
    rid=receipt['accountId'];first=receipt['result']['account'];out['beforeUpdate']=first
    patch_body={'requestId':key(),'revision':first['revision'],'changes':{'name':'合成更名账户','institution':'','note':'可换行\n和\t制表'}}
    r=c.patch(url+'/'+rid,json=patch_body,headers=h);assert r.status_code==200,r.json;out.update(updateBody=patch_body,updated=r.json)
    valuation_body={'requestId':key(),'revision':r.json['result']['account']['revision'],'amountCents':None}
    r=c.put(url+'/'+rid+'/valuations/2026-09-18',json=valuation_body,headers=h);assert r.status_code==200,r.json;out.update(valuationBody=valuation_body,valued=r.json)
    create('合成未知美元',None,'USD');create('合成零美元',0,'USD');create('合成负债',12345,'CNY','liability')
    # Actual API writes produce a subtotal beyond Number.MAX_SAFE_INTEGER.
    for n in range(91):create('合成大额'+str(n),100000000000000)
    out['list']=listing();out['earlier']=listing('2026-09-16');out['later']=listing('2026-09-19')
    rev=r.json['result']['account']['revision']
    from datetime import date,timedelta
    for n in range(51):
        point=(date(2026,1,1)+timedelta(days=n)).isoformat()
        r=c.put(url+'/'+rid+'/valuations/'+point,json={'requestId':key(),'revision':rev,'amountCents':n},headers=h)
        assert r.status_code==200,r.json;rev=r.json['result']['account']['revision']
    def history(page):
        r=c.get(url+'/'+rid+'/valuations',query_string={'page':page,'pageSize':50});assert r.status_code==200,r.json;return r.json
    out['history1']=history(1);out['history2']=history(2)
    stale=c.patch(url+'/'+rid,json={'requestId':key(),'revision':1,'changes':{'name':'不应写入'}},headers=h);assert stale.status_code==409
    out['conflict']={'status':stale.status_code,'body':stale.json}
    archive_body={'requestId':key(),'revision':rev,'changes':{'archived':True}}
    r=c.patch(url+'/'+rid,json=archive_body,headers=h);assert r.status_code==200;out['archived']=r.json
    out['active']=listing(status='active');out['archiveList']=listing(status='archived')
    blocked=c.put(url+'/'+rid+'/valuations/2026-09-19',json={'requestId':key(),'revision':r.json['result']['account']['revision'],'amountCents':100},headers=h);assert blocked.status_code==409
    out['archiveBlocked']={'status':blocked.status_code,'body':blocked.json}
    r=c.patch(url+'/'+rid,json={'requestId':key(),'revision':r.json['result']['account']['revision'],'changes':{'archived':False}},headers=h);assert r.status_code==200;out['restored']=r.json
    # Same owner in a fresh real session can read/replay an old original request.
    renewed,renewed_h=member(app);stable=counts();r=renewed.post(url,json=body,headers=renewed_h);assert r.status_code==201,r.json;assert counts()==stable
    out['replay']=r.json;out['found']=renewed.get(url+'/operations/'+body['requestId']).json
    out['notFound']=renewed.get(url+'/operations/'+'f'*32).json
    partner,_=member(app,2);out['partner']=listing(client=partner);out['partnerFound']=partner.get(url+'/operations/'+body['requestId']).json
    out['partnerHistory']=partner.get(url+'/'+rid+'/valuations').status_code
    tv=app.test_client();pair=tv.post('/api/pair/start',json={}).json
    assert renewed.post('/api/pair/approve',headers=renewed_h,json={'code':pair['code'],'name':'合成电视'}).status_code==200
    assert tv.post('/api/pair/poll',json={'secret':pair['secret']}).json['approved']
    out['tvDenied']=tv.get(url+'?asOf=2026-09-17').status_code;out['anonymousDenied']=app.test_client().get(url+'?asOf=2026-09-17').status_code
    after=counts();assert all(before[t]==after[t] for t in ['finance_baselines','hub_transactions','hub_investments']);out['counts']=after
print(json.dumps(out,ensure_ascii=False))
`, root], { cwd: root, encoding: 'utf8', timeout: 120_000, maxBuffer: 4_000_000 });
assert.equal(setup.status, 0, setup.stderr || setup.error?.message || 'Real account fixture failed');
const f = JSON.parse(setup.stdout), clone = value => structuredClone(value);
const { AccountError, AccountDiscarded, AccountRejected, AccountFence, accountSignature, readAccountList, readAccountHistory, readAccountReceipt, readAccountOperation } = model;

test('real empty list and per-owner projection are strict', () => {
  assert.deepEqual(readAccountList(f.empty, 'member1', '2026-09-17', 'all').accounts, []);
  assert.deepEqual(readAccountList(f.partner, 'member2', '2026-09-17', 'all').accounts, []);
  assert.throws(() => readAccountList(f.list, 'member2', '2026-09-17', 'all'), AccountError);
  const raw = clone(f.list);raw.extraSecret = 'ignored';raw.accounts[0].secret='ignored';const view=readAccountList(raw,'member1','2026-09-17','all');assert(!('extraSecret' in view));assert(!('secret' in view.accounts[0]));
});
test('real date views distinguish zero, unknown, missing and older valuations', () => {
  const current=readAccountList(f.list,'member1','2026-09-17','all'), earlier=readAccountList(f.earlier,'member1','2026-09-16','all'), later=readAccountList(f.later,'member1','2026-09-19','all');
  assert.equal(current.accounts.find(a=>a.id===f.created.accountId).valuation.amountCents,0);
  assert.equal(later.accounts.find(a=>a.id===f.created.accountId).valuation.amountCents,null);
  assert(earlier.accounts.every(a=>a.valuation===null));assert(earlier.totals.every(t=>t.knownCount===0));
  const usd=current.totals.find(t=>t.currency==='USD');assert.equal(usd.unknownCount,1);assert.equal(usd.knownCount,1);assert.equal(usd.knownAssetCents,'0');assert.equal(later.totals[0].olderCount,later.totals[0].assetCount+later.totals[0].liabilityCount);
});
test('real large total stays exact beyond JS safe number and currencies stay separate', () => {
  const view=readAccountList(f.list,'member1','2026-09-17','all'), cny=view.totals.find(t=>t.currency==='CNY');
  assert(BigInt(cny.knownAssetCents)>BigInt(Number.MAX_SAFE_INTEGER));assert.equal(cny.knownAssetCents,'9100000000000000');assert.equal(cny.knownNetCents,'9099999999987655');
  assert.equal(model.formatAccountMoney(cny.knownNetCents,'CNY'),'CNY 90,999,999,999,876.55');assert.equal(model.formatAccountMoney('-12345','USD'),'USD −123.45');
  assert.equal(model.formatAccountMoney(null,'USD'),'金额未知');assert.equal(model.formatAccountMoney(0,'USD'),'USD 0.00');
});
test('malformed totals, future values and duplicate records reject the whole unsafe view', () => {
  for (const mutate of [v=>v.accounts.push(v.accounts[0]),v=>v.accounts[0].valuation.asOf='2027-01-01',v=>v.totals[0].knownAssetCents='9e15',v=>v.totals[0].knownCount+=1,v=>v.totals[0].knownNetCents='0',v=>v.accounts[0].visibility='shared',v=>v.accounts[0].revision=Number.MAX_SAFE_INTEGER+1]) {const raw=clone(f.list);mutate(raw);assert.throws(()=>readAccountList(raw,'member1','2026-09-17','all'),AccountError);}
});
test('forms construct exactly the real create/update/valuation requests with frozen bodies', () => {
  const draft={name:f.createBody.name,institution:f.createBody.institution,kind:'asset',currency:'CNY',note:f.createBody.note,asOf:'2026-09-17',amount:'0',unknown:false};
  const create=model.createAccountIntent(draft,f.createBody.requestId);assert.deepEqual(create.body,f.createBody);assert(Object.isFrozen(create.body));assert(Object.isFrozen(create.body.valuation));
  assert.deepEqual(model.updateAccountIntent(f.beforeUpdate,f.updateBody.changes,f.updateBody.requestId).body,f.updateBody);
  assert.deepEqual(model.valuationAccountIntent(f.updated.result.account,'2026-09-18','',true,f.valuationBody.requestId).body,f.valuationBody);
  assert.throws(()=>model.updateAccountIntent(f.beforeUpdate,{currency:'USD'}),AccountError);assert.throws(()=>model.valuationAccountIntent(f.archived.result.account,'2026-09-19','1',false),AccountError);
  assert.equal(model.createAccountIntent({...draft,name:'😀'.repeat(120)}).body.name.length,240);assert.throws(()=>model.createAccountIntent({...draft,name:'😀'.repeat(121)}),AccountError);assert.throws(()=>model.createAccountIntent({...draft,name:'\ud800'}),AccountError);
});
test('decimal parsing preserves cents, zero, unknown and inclusive cap without rounding', () => {
  assert.equal(model.parseAccountAmount('0.01',false),1);assert.equal(model.parseAccountAmount('1000000000000.00',false),100000000000000);assert.equal(model.parseAccountAmount('',true),null);
  for (const value of ['','-1','1.001','1e3','01','1,000','1000000000000.01','9'.repeat(10000)]) assert.throws(()=>model.parseAccountAmount(value,false),AccountError);
  for(const value of ['2026-02-29','0000-01-01','2026-13-01'])assert.throws(()=>model.accountDay(value),AccountError);
});
test('real server history pagination retains every actual point and no synthetic missing points', () => {
  const first=readAccountHistory(f.history1,'member1',f.created.accountId,1), second=readAccountHistory(f.history2,'member1',f.created.accountId,2);
  assert.equal(first.total,53);assert.equal(first.valuations.length,50);assert.equal(second.valuations.length,3);assert.equal(new Set([...first.valuations,...second.valuations].map(v=>v.asOf)).size,53);
  const invalid=clone(f.history1);invalid.valuations.reverse();assert.throws(()=>readAccountHistory(invalid,'member1',f.created.accountId,1),AccountError);
  assert.throws(()=>readAccountHistory(f.history1,'member2',f.created.accountId,1),AccountError);
});
test('real current archived filters and reversible restore keep history', () => {
  const archive=readAccountList(f.archiveList,'member1','2026-09-17','archived'),active=readAccountList(f.active,'member1','2026-09-17','active');
  assert.equal(archive.accounts.length,1);assert.equal(archive.accounts[0].id,f.created.accountId);assert(!active.accounts.some(a=>a.id===f.created.accountId));assert.equal(f.archiveBlocked.body.code,'account_archived');assert.equal(f.restored.result.account.archived,false);
});
test('real historical receipt and same-key replay do not masquerade as current account', () => {
  const receipt=readAccountReceipt(f.replay,'member1',f.createBody.requestId),found=readAccountOperation(f.found,'member1',f.createBody.requestId);
  assert.equal(receipt.replayed,true);assert.equal(found.result.account.revision,1);assert.equal(found.result.account.name,'合成零余额账户');assert(f.history1.account.revision>found.result.account.revision);
  assert.equal(readAccountOperation(f.notFound,'member1','f'.repeat(32)),null);assert.equal(readAccountOperation(f.partnerFound,'member2',f.createBody.requestId),null);
  assert.throws(()=>readAccountReceipt(f.created,'member2',f.createBody.requestId),AccountError);assert.throws(()=>readAccountReceipt(f.updated,'member1',f.createBody.requestId),AccountError);
  assert.equal(f.partnerHistory,404);assert.equal(f.tvDenied,403);assert.equal(f.anonymousDenied,401);
});
test('before/after identity fences stop preflight writes and discard late private results', async () => {
  const session=clone(f.session), identity=accountSignature(session);let writes=0;
  const fence=new AccountFence(identity);
  await assert.rejects(fence.run(async()=>({...session,csrf:'other'}),async()=>{writes++;},()=>true),AccountDiscarded);assert.equal(writes,0);
  let reads=0;await assert.rejects(fence.run(async()=>++reads===1?session:{...session,user:{...session.user,householdId:'different'}},async()=>f.list,()=>true),AccountDiscarded);
  await assert.rejects(fence.run(async()=>session,async()=>{fence.invalidate();return f.list;},()=>true),AccountDiscarded);
  await assert.rejects(fence.run(async()=>({...session,user:{...session.user,role:'tv'}}),async()=>{writes++;},()=>true),AccountDiscarded);assert.equal(writes,0);
});
test('only a rejected mutation with successful post-me is a known failure; old unknown remains', async () => {
  const identity=accountSignature(f.session), intent=model.createAccountIntent({name:'合成',institution:'',kind:'asset',currency:'CNY',note:'',asOf:'2026-09-17',amount:'0',unknown:false});
  const guard=job=>new AccountFence(identity).run(async()=>f.session,job,()=>true);
  let failure;try{await model.checkedAccountWrite(guard,async()=>{throw new AccountError('版本冲突',409,'revision_conflict');});}catch(error){failure=error;}
  assert(failure instanceof AccountRejected);assert.equal(model.failedAccountIntent(intent,failure),null);assert(model.failedAccountIntent({...intent,uncertain:true},failure));
  let n=0;await assert.rejects(model.checkedAccountWrite(job=>new AccountFence(identity).run(async()=>{if(++n>1)throw new Error('post identity network loss');return f.session;},job,()=>true),async()=>{throw new AccountError('版本冲突',409,'revision_conflict');}),error=>!(error instanceof AccountRejected));
  const uncertain=model.failedAccountIntent(intent,new AccountError('response lost'));assert.equal(uncertain.requestId,intent.requestId);assert.equal(uncertain.body,intent.body);assert.equal(uncertain.uncertain,true);
});
test('opaque recovery keys cannot cross actors or be cleared by an older callback', () => {
  const memory=new model.AccountRecoveryMemory(), own=model.accountActor(f.session), other=JSON.stringify(['other','member1']);
  memory.set(own,'a'.repeat(32));memory.set(other,'b'.repeat(32));memory.set(own,'c'.repeat(32));assert.equal(memory.clear(own,'a'.repeat(32)),false);assert.equal(memory.get(own),'c'.repeat(32));assert.equal(memory.get(other),'b'.repeat(32));assert.equal(memory.clear(own,'c'.repeat(32)),true);
});
test('exact not-found needs fresh all-accounts review and explicit matching decision to unlock', () => {
  const identity=accountSignature(f.session), list=readAccountList(f.list,'member1','2026-09-17','all'), requestId='f'.repeat(32);
  assert.equal(model.canEndAccountReview(null,requestId,identity,true),false);
  const review=model.accountEndReview(list,f.notFound,'member1',requestId,identity);
  assert(review);assert.equal(model.canEndAccountReview(review,requestId,identity,false),false);
  assert.equal(model.canEndAccountReview(review,requestId,identity,true),true);
  assert.equal(model.canEndAccountReview(review,'a'.repeat(32),identity,true),false);
  assert.equal(model.canEndAccountReview(review,requestId,'new-identity',true),false);
  assert.equal(model.accountEndReview({...list,status:'active'},f.notFound,'member1',requestId,identity),null);
  assert.equal(model.accountEndReview(list,f.found,'member1',f.createBody.requestId,identity),null);
  assert.equal(review.requestId,requestId); // Still available for copy/readback, never a new request ID.
});
test('transport rejects external/malformed paths before fetch and uses exact bounded same-origin protocol', async () => {
  const original=globalThis.fetch,calls=[];globalThis.fetch=async(path,options)=>{calls.push({path,options});return new Response(JSON.stringify({error:'精确拒绝',code:'invalid_request'}),{status:400,headers:{'Content-Type':'application/json'}});};
  try {for(const path of ['https://other.test/api/finance-accounts','/finance-accounts?owner=member2','/finance-accounts/../me','/finance-accounts/operations/'+'A'.repeat(32)])await assert.rejects(model.accountRequest(path,new AbortController().signal),AccountError);assert.equal(calls.length,0);
    await assert.rejects(model.accountRequest(model.accountListPath('2026-09-17','all'),new AbortController().signal),error=>error.status===400&&error.code==='invalid_request');
    assert.equal(calls[0].options.mode,'same-origin');assert.equal(calls[0].options.credentials,'same-origin');assert.equal(calls[0].options.cache,'no-store');assert.equal(calls[0].options.redirect,'error');assert(!('body' in calls[0].options));assert(!('X-CSRF-Token' in calls[0].options.headers));
    const aborted=new AbortController();aborted.abort();await assert.rejects(model.accountRequest('/me',aborted.signal),AccountDiscarded);assert.equal(calls.length,1);
  }finally{globalThis.fetch=original;}
});
test('transport rejects HTML, oversized success and malformed JSON without exposing it', async () => {
  const original=globalThis.fetch;
  try {for(const response of [new Response('<html>private</html>',{headers:{'Content-Type':'text/html'}}),new Response('x'.repeat(2_000_001),{headers:{'Content-Type':'application/json'}}),new Response('{"unfinished":',{headers:{'Content-Type':'application/json'}})]){globalThis.fetch=async()=>response;await assert.rejects(model.accountRequest('/me',new AbortController().signal),AccountError);}}
  finally{globalThis.fetch=original;}
});
