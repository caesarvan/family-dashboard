import assert from 'node:assert/strict';
import { test } from 'node:test';
import { registerHooks } from 'node:module';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
const lib = new URL('../frontend/src/lib/', import.meta.url);
registerHooks({ resolve(specifier, context, next) { return next(context.parentURL?.startsWith(lib.href) && /^\.\/\w+$/.test(specifier) ? specifier + '.ts' : specifier, context); } });
const m = await import(new URL('tripImport.ts', lib));
const root = resolve(process.env.TRIP_IMPORT_BACKEND_ROOT || fileURLToPath(new URL('..', import.meta.url)));
const setup = spawnSync(process.env.TRIP_IMPORT_TEST_PYTHON || 'python', ['-B', '-X', 'utf8', '-c', String.raw`
import sys,json,tempfile,socket,secrets,sqlite3,time
from pathlib import Path
from contextlib import closing
from unittest.mock import patch
from pytest import MonkeyPatch
root=Path(sys.argv[1]).resolve(); sys.path[:0]=[str(root),str(root/'tests')]
from app import create_app
from test_journey_documents import login,PASSWORD
def denied(*a,**k): raise AssertionError('External network forbidden')
with tempfile.TemporaryDirectory(prefix='trip-import-model-') as folder,MonkeyPatch.context() as mp,patch.object(socket.socket,'connect',denied),patch('socket.create_connection',denied):
    mp.setenv('MEMBER1_PASSWORD',PASSWORD);mp.setenv('MEMBER2_PASSWORD',PASSWORD)
    config={'TESTING':True,'DATA_DIR':folder,'SECRET_KEY':'trip-import-synthetic','SESSION_COOKIE_SECURE':False,'PUBLIC_ORIGIN':'http://localhost',
        'OPENAI_API_KEY':'','OPENAI_MODEL':'','GOOGLE_CLIENT_ID':'','MICROSOFT_CLIENT_ID':''}
    app=create_app(config);c,h=login(app);other,oh=login(app,2)
    result={'templates':c.get('/api/journeys/templates').json,'session':c.get('/api/me').json,'examples':[]}
    def count():
        with closing(sqlite3.connect(Path(folder)/'household.sqlite3')) as con: return con.execute('SELECT count(*) FROM journey_workflows').fetchone()[0]
    def preview(p):
        r=c.post('/api/journeys/preview',json={'plan':p},headers=h);assert r.status_code==200,r.json;return r.json
    for version in [1,2]:
        raw=json.loads((root/'static/examples'/('journey-plan-v%d.json'%version)).read_text(encoding='utf-8'))
        n=count();p=preview(raw);assert count()==n
        key=secrets.token_hex(16);body={'previewToken':p['previewToken'],'idempotencyKey':key}
        written=c.post('/api/journeys/apply',json=body,headers=h);assert written.status_code==201,written.json
        replay=c.post('/api/journeys/apply',json=body,headers=h);assert replay.status_code==200 and replay.json['replayed'];assert count()==n+1
        operation=c.get('/api/journeys/operations/'+key);assert operation.status_code==200
        detail=c.get('/api/journeys/'+written.json['id']);assert detail.status_code==200
        assert other.get('/api/journeys/operations/'+key).status_code==404
        result['examples'].append({'raw':raw,'preview':p,'key':key,'receipt':written.json,'replay':replay.json,'operation':operation.json,'detail':detail.json})
    p0={'title':'服务端默认事项','start':'2027-10-01','end':'2027-10-03','destinations':[{'city':'合成城市'}]}
    result['defaults']={'raw':p0,'preview':preview(p0)}
    empty={**p0,'checklist':[],'shopping':[],'segments':[]};result['empty']={'raw':empty,'preview':preview(empty)}
    result['missingStatus']=c.get('/api/journeys/operations/'+'f'*32).status_code
    result['missing']=c.get('/api/journeys/operations/'+'f'*32).json
    key=result['examples'][0]['key'];original=result['examples'][0]['preview']['previewToken']
    with patch('itsdangerous.timed.time.time',return_value=time.time()+1801):
        expired=c.post('/api/journeys/apply',json={'previewToken':original,'idempotencyKey':key},headers=h)
        assert expired.status_code==409,expired.json;result['expiredStatus']=expired.status_code
        assert c.get('/api/journeys/operations/'+key).status_code==200
    # New session may read this member's historical receipt; original token is not treated as a session proof.
    nc,nh=login(app);result['newSessionOperation']=nc.get('/api/journeys/operations/'+key).json
    restarted=create_app(config);rc,rh=login(restarted);result['afterRestart']=rc.get('/api/journeys/'+result['examples'][0]['receipt']['id']).json
    result['list']=rc.get('/api/journeys').json
    result['invalid']=[]
    for changes in [{'memberIds':['foreign']},{'budget':None},{'budget':1.5},{'start':'2027-02-30'},{'checklist':[{'key':'x','title':'a'},{'key':'x','title':'b'}]}]:
        r=rc.post('/api/journeys/preview',json={'plan':{**p0,**changes}},headers=rh);result['invalid'].append(r.status_code);assert r.status_code==400,r.json
    dst={'schemaVersion':2,'referenceTimezone':'America/New_York','title':'真实DST歧义','start':'2027-11-07','end':'2027-11-07',
      'destinations':[{'key':'ny','city':'纽约','timeZone':'America/New_York'}],'checklist':[],'shopping':[],
      'segments':[{'key':'walk','kind':'activity','title':'合成活动','start':{'local':'2027-11-07T01:30','timeZone':'America/New_York'},'end':{'local':'2027-11-07T03:00','timeZone':'America/New_York'}}]}
    ambiguous=rc.post('/api/journeys/preview',json={'plan':dst},headers=rh);assert ambiguous.status_code==400,ambiguous.json;result['dst']=ambiguous.json
    result['dstPreviews']=[]
    for choice in ambiguous.json['choices']:
        dst['segments'][0]['start']['offsetMinutes']=choice['offsetMinutes']
        r=rc.post('/api/journeys/preview',json={'plan':dst},headers=rh);assert r.status_code==200,r.json;result['dstPreviews'].append(r.json)
    assert count()==2
print(json.dumps(result,ensure_ascii=False))
`, root], { cwd: root, encoding: 'utf8', timeout: 120000, maxBuffer: 5_000_000 });
assert.equal(setup.status, 0, setup.stderr || setup.error?.message || 'Real temporary API fixture failed');
const f = JSON.parse(setup.stdout), clone = v => structuredClone(v);

test('official v1/v2 inputs preserve omissions and consume real normalized previews', () => {
  for (const e of f.examples) {
    const body = m.tripImportPreviewBody(m.parseTripImport(JSON.stringify({ plan: e.raw })), m.tripImportVersions(f.templates));
    assert.deepEqual(body, { plan: e.raw }); assert.equal(body.plan.memberIds, undefined);
    const p = m.readTripImportPreview(e.preview); assert.equal(p.plan.schemaVersion ?? 1, e.raw.schemaVersion); assert.deepEqual(p.plan.memberIds, ['member1','member2']);
    assert.equal(p.plan.shopping[1].budget, null); assert.equal(p.plan.budget, 2000000); assert.equal(p.plan.checklist[0].key, 'budget-review');
    if (p.plan.schemaVersion === 2) { assert(p.plan.segments.some(s => s.kind === 'flight')); assert(p.plan.segments.some(s => s.kind === 'stay')); }
  }
});
test('server default checklist/segments and explicit empty collections remain distinct', () => {
  assert.equal(m.parseTripImport(JSON.stringify(f.defaults.raw)).plan.checklist, undefined);
  const defaults = m.readTripImportPreview(f.defaults.preview), empty = m.readTripImportPreview(f.empty.preview);
  assert(defaults.plan.checklist.length > 0); assert(defaults.plan.segments.length > 0); assert.equal(empty.plan.checklist.length, 0); assert.equal(empty.plan.segments.length, 0);
});
test('new-create receipt, replay, receipt lookup and real restarted current detail stay separate', () => {
  for (const e of f.examples) {
    const receipt = m.readTripImportReceipt(e.receipt); assert.equal(receipt.revision,1); assert.equal(receipt.replayed,false);
    assert.equal(m.readTripImportReceipt(e.replay).replayed,true); assert.equal(m.readTripImportOperation(e.operation,e.key).id,receipt.id);
    assert.equal(m.readTripImportCurrent(e.detail,receipt).tripId,receipt.tripId);
    assert.throws(()=>m.readTripImportReceipt(e.operation.result)); assert.throws(()=>m.readTripImportOperation(e.operation,'z'.repeat(32)));
  }
  assert.equal(m.readTripImportCurrent(f.afterRestart,m.readTripImportReceipt(f.examples[0].receipt)).id,f.afterRestart.id);
  assert.equal(m.readTripImportList(f.list).length,2); assert.equal(m.readTripImportOperation(f.newSessionOperation,f.examples[0].key).id,f.examples[0].receipt.id);
});
test('real DST choices differ; no local timezone/default offset is invented', () => {
  assert.equal(f.dst.choices.length,2);const previews=f.dstPreviews.map(m.readTripImportPreview);
  assert.notEqual(previews[0].plan.segments[0].start.instant,previews[1].plan.segments[0].start.instant);
  assert(f.invalid.every(s=>s===400));
});
test('input bounds, forbidden context and unsupported versions cannot reach preview', () => {
  assert.throws(()=>m.parseTripImport(''));assert.throws(()=>m.parseTripImport('x'.repeat(200001)));
  assert.throws(()=>m.parseTripImport(JSON.stringify({...f.examples[0].raw,note:'字'.repeat(70000)})));
  for(const key of ['journeyId','tripId','revision','previewToken','idempotencyKey','expectedEntities','conflictResolutions']) {
    assert.throws(()=>m.parseTripImport(JSON.stringify({plan:f.examples[0].raw,[key]:'external'})));
    assert.throws(()=>m.parseTripImport(JSON.stringify({...f.examples[0].raw,[key]:'external'})));
  }
  assert.throws(()=>m.parseTripImport('{"__proto__":{}}'));
  assert.throws(()=>m.tripImportPreviewBody({plan:f.examples[1].raw},[1]));
  assert.equal(m.parseTripImport('\uFEFF'+JSON.stringify(f.defaults.raw)).plan.schemaVersion,undefined);
});
test('UTF8 file decoding rejects invalid bytes and preserves content', () => {
  const bytes=new TextEncoder().encode(JSON.stringify(f.examples[1].raw));assert.deepEqual(m.parseTripImport(m.decodeTripImportFile(bytes.buffer)).plan,f.examples[1].raw);
  assert.throws(()=>m.decodeTripImportFile(new Uint8Array([0xc3,0x28]).buffer));assert.throws(()=>m.decodeTripImportFile(new ArrayBuffer(200001)));
});
test('malformed normalized successes and existing-edit summaries are fail-closed', () => {
  for(const patch of [{revision:2},{id:'../../me'},{replayed:'true'},{calendar:{local:'created',cloud:'not_requested',icsUrl:'https://outside/'}}]) assert.throws(()=>m.readTripImportReceipt({...f.examples[0].receipt,...patch}));
  const p=clone(f.examples[0].preview);p.summary.update={trips:1};assert.throws(()=>m.readTripImportPreview(p));
  const d=clone(f.examples[0].detail);d.tripId='e'.repeat(24);assert.throws(()=>m.readTripImportCurrent(d,m.readTripImportReceipt(f.examples[0].receipt)));
});
test('first known rejection may release intent; previously unknown never cleared by 409/404', () => {
  const intent=m.createTripImportIntent(m.readTripImportPreview(f.examples[0].preview),'a'.repeat(32));assert(Object.isFrozen(intent.body));
  const rejected=new m.TripImportRejected('expired',f.expiredStatus);
  assert.equal(m.failedTripImportIntent(intent,rejected),null);
  const unknown=m.failedTripImportIntent(intent,new Error('lost'));assert.equal(unknown.uncertain,true);
  assert.deepEqual(m.failedTripImportIntent(unknown,rejected).body,intent.body);
  assert.equal(f.missingStatus,404);assert(m.missingTripImportReceipt(new m.TripImportError('missing',404,f.missing)));
  assert.equal(m.missingTripImportReceipt(new m.TripImportError('missing',404,{code:'not_found'})),false);
});
test('false alone never ends review; stale identity/epoch proof cannot release it', () => {
  const proof={key:'a'.repeat(32),identity:'one',epoch:4};assert.equal(m.canEndTripImport(null,proof.key,'one',4),false);
  assert(m.canEndTripImport(proof,proof.key,'one',4));assert.equal(m.canEndTripImport(proof,proof.key,'two',4),false);assert.equal(m.canEndTripImport(proof,proof.key,'one',5),false);
});
test('opaque recovery is household/member scoped and late old finish cannot clear newer handle', () => {
  const memory=new m.TripImportRecoveryMemory(),actor=m.tripImportActor(f.session),key='a'.repeat(32),next='b'.repeat(32);
  memory.set(actor,key);memory.set(actor,next);memory.finish(actor,key);assert.deepEqual(memory.get(actor),{key:next,pending:true});
  memory.finish(actor,next);assert.deepEqual(memory.get(actor),{key:next,pending:false});
  assert.equal(memory.get(m.tripImportActor({...f.session,user:{...f.session.user,householdId:'another'}})),null);
  assert(!JSON.stringify(memory.get(actor)).includes('previewToken'));
});
test('full identity fence rejects postflight changes and invalidated old reads', async () => {
  const session=f.session, fence=new m.TripImportFence(m.tripImportSignature(session));let count=0;
  await assert.rejects(fence.run(async()=>++count===1?session:{...session,csrf:'new'},async()=>42,()=>true),m.TripImportDiscarded);
  await assert.rejects(fence.run(async()=>session,async()=>{fence.invalidate();return 42;},()=>true),m.TripImportDiscarded);
});
test('preflight failure never dispatches a write', async () => {
  const fence=new m.TripImportFence(m.tripImportSignature(f.session));let dispatched=0;
  await assert.rejects(m.checkedTripImportWrite(job=>fence.run(async()=>({...f.session,csrf:'other'}),job,()=>true),async()=>{dispatched++;return 1;}));assert.equal(dispatched,0);
});
test('fixed request paths reject credential forwarding and mutating list calls before fetch', async () => {
  const old=globalThis.fetch;let calls=0;globalThis.fetch=async()=>{calls++;throw Error('unexpected');};
  try { for(const path of ['https://outside/api/me','//outside','/journeys?owner=member2','/journeys/../me']) await assert.rejects(m.tripImportRequest(path,new AbortController().signal));
    await assert.rejects(m.tripImportRequest('/journeys',new AbortController().signal,{method:'POST',csrf:'x',payload:{}}));assert.equal(calls,0);
  } finally {globalThis.fetch=old;}
});
