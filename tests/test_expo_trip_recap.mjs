import assert from 'node:assert/strict';
import { test } from 'node:test';
import { registerHooks } from 'node:module';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

const lib = new URL('../frontend/src/lib/', import.meta.url);
registerHooks({ resolve(specifier, context, next) {
  return next(context.parentURL?.startsWith(lib.href) && /^\.\/\w+$/.test(specifier) ? specifier + '.ts' : specifier, context);
} });
const { RecapError, RecapDiscarded, RecapFence, recapSignature, recapPagePath, recapRequest, readRecapJourney, readRecapPlaces, readRecapPhotos, readRecapPhoto } = await import(new URL('tripRecap.ts', lib));
const root = resolve(process.env.RECAP_MODEL_BACKEND_ROOT || fileURLToPath(new URL('..', import.meta.url)));
const setup = spawnSync(process.env.RECAP_TEST_PYTHON || 'python', ['-B', '-X', 'utf8', '-c', String.raw`
import sys,json,tempfile,socket,secrets,base64
from pathlib import Path
from io import BytesIO
from unittest.mock import patch
from pytest import MonkeyPatch
from PIL import Image
root=Path(sys.argv[1]).resolve(); sys.path[:0]=[str(root),str(root/'tests')]
from test_household_media import configured,stage,confirm,selected,device
from test_journey_documents import login,create_journey
from test_journey_places import create as create_place
from media_images import sanitize_media_preview
def denied(*a,**k): raise AssertionError('External network forbidden')
with tempfile.TemporaryDirectory(prefix='trip-recap-model-') as folder,MonkeyPatch.context() as mp,patch.object(socket.socket,'connect',denied),patch('socket.create_connection',denied):
    env=configured(Path(folder)/'one',mp); app=env[0]; c,h=login(app); other,oh=login(app,2)
    j=create_journey(c,h); jid=j['id']; result={'id':jid,'session':c.get('/api/me').json}
    def read(client,path):
        r=client.get(path); assert r.status_code==200,(path,r.status_code,r.json); return r.json
    jp='/api/journeys/'+jid
    result['original']=read(c,jp)
    original=next(e for e in result['original']['events'] if e['workflowKey']=='segment:hotel')
    assert c.patch('/api/items/events/'+original['id'],json={'revision':original['revision'],'title':'当前独立修改的日程','location':'当前地点','note':'记'*8000},headers=h).status_code==200
    result['edited']=read(c,jp)
    assert c.delete('/api/items/events/'+original['id'],json={'revision':original['revision']+1},headers=h).status_code==200
    result['deleted']=read(c,jp)
    for n in range(25): create_place(c,h,name='合成本人地点 '+str(n),journeyId=jid,coordinates={'latitude':31.234567,'longitude':121.456789},startDate='2026-12-01',endDate='2026-12-04')
    for policy in ['hidden','coarse','exact']:
        create_place(other,oh,name='伴侣共享 '+policy,journeyId=jid,visibility='shared',coordinateDisclosure=policy,coordinates={'latitude':31.234567,'longitude':121.456789},status='visited',confirmVisited=True)
    create_place(other,oh,name='PRIVATE_PARTNER_NOT_VISIBLE',journeyId=jid)
    pp='/api/journey-places?scope=visible&journeyId='+jid+'&limit=24&offset='
    result['places']=[read(c,pp+'0'),read(c,pp+'24')]
    assert sum(len(p['items']) for p in result['places'])==28
    assert 'PRIVATE_PARTNER_NOT_VISIBLE' not in json.dumps(result['places'])
    counter=[0]
    def image():
        counter[0]+=1; stream=BytesIO(); Image.new('RGB',(20,12),(counter[0]*7%256,counter[0]*11%256,counter[0]*13%256)).save(stream,'PNG')
        return sanitize_media_preview(stream.getvalue(),'image/png')
    with patch('test_household_media.preview',image):
        for count in [20,5]:
            pc,ph,detail,_=stage(env,items=[selected(secrets.token_hex(8)) for _ in range(count)]); confirm(pc,ph,detail)
            for row in detail['items']:
                item=read(pc,'/api/media/items/'+row['id'])['item']
                r=pc.patch('/api/media/items/'+item['id'],json={'revision':item['revision'],'journeyId':jid,'caption':'合成旅行照片 '+str(counter[0])},headers=ph)
                assert r.status_code==200,r.json
        pc,ph,detail,_=stage(env,number=2); confirm(pc,ph,detail)
        item=read(pc,'/api/media/items/'+detail['items'][0]['id'])['item']
        r=pc.patch('/api/media/items/'+item['id'],json={'revision':item['revision'],'journeyId':jid,'visibility':'shared','caption':'伴侣共享照片'},headers=ph); assert r.status_code==200,r.json
        shared=r.json['item']
    mpth='/api/media/items?scope=visible&journeyId='+jid+'&limit=24&offset='
    result['photos']=[read(c,mpth+'0'),read(c,mpth+'24')]; assert result['photos'][0]['total']==26
    result['photo']=read(c,'/api/media/items/'+shared['id'])
    raw=c.get('/api/media/items/'+shared['id']+'/preview'); assert raw.status_code==200
    result['jpeg']=base64.b64encode(raw.data).decode()
    assert other.patch('/api/media/items/'+shared['id'],json={'revision':shared['revision'],'visibility':'private'},headers=oh).status_code==200
    result['revokedPhotos']=read(c,mpth+'0'); result['revokedStatus']=c.get('/api/media/items/'+shared['id']+'/preview').status_code
    p={'schemaVersion':2,'referenceTimezone':'Asia/Shanghai','title':'合成跨时区回顾','start':'2026-12-01','end':'2026-12-04','budget':0,'memberIds':['member1'],
      'destinations':[{'key':'tokyo','country':'日本','city':'东京','arrival':'2026-12-01','departure':'2026-12-04','timeZone':'Asia/Tokyo'}],'checklist':[],'shopping':[],
      'segments':[{'key':'flight','kind':'flight','title':'合成航班','departure':{'local':'2026-12-01T09:00','timeZone':'Asia/Shanghai','airport':'PVG','city':'上海'},'arrival':{'local':'2026-12-01T13:00','timeZone':'Asia/Tokyo','airport':'NRT','city':'东京'}},
      {'key':'stay','kind':'stay','title':'合成住宿','propertyName':'合成旅馆','address':'合成街道','timeZone':'Asia/Tokyo','checkInDate':'2026-12-01','checkOutDate':'2026-12-04','checkInTime':'','checkOutTime':''},
      {'key':'cancelled','kind':'activity','title':'人工取消活动','bookingState':'cancelled','dateRange':{'startDate':'2026-12-02','endDateExclusive':'2026-12-03'},'timeZone':'Asia/Tokyo'}]}
    preview=c.post('/api/journeys/preview',json={'plan':p},headers=h); assert preview.status_code==200,preview.json
    written=c.post('/api/journeys/apply',json={'previewToken':preview.json['previewToken'],'idempotencyKey':secrets.token_hex(16)},headers=h); assert written.status_code==201,written.json
    result['v2']=read(c,'/api/journeys/'+written.json['id'])
    _,tv,_=device(env); result['tvPlaces']=tv.get(pp+'0').status_code; result['tvPhotos']=tv.get(mpth+'0').status_code
    # Different household cannot resolve this workflow; no global lookup fallback.
    foreign=configured(Path(folder)/'two',mp,'foreign'); fc,fh=login(foreign[0]); result['foreign']=fc.get(jp).status_code
print(json.dumps(result,ensure_ascii=False))
`, root], { cwd: root, encoding: 'utf8', timeout: 120000, maxBuffer: 4_000_000 });
assert.equal(setup.status, 0, setup.stderr || setup.error?.message || 'Real fixture failed');
const fixture = JSON.parse(setup.stdout), clone = value => structuredClone(value);
const journey = readRecapJourney(fixture.edited, fixture.id);

test('real current event titles replace old plan text; deleted events are not recreated', () => {
  assert(journey.events.some(e => e.title === '当前独立修改的日程' && e.location === '当前地点'));
  assert.equal(journey.events.find(e => e.title === '当前独立修改的日程').note, '记'.repeat(8000));
  assert(!readRecapJourney(fixture.deleted, fixture.id).events.some(e => e.title === '当前独立修改的日程'));
  assert(fixture.deleted.plan.segments.some(s => s.title === '合成酒店'));
  assert(!('budget' in journey)); assert(!('tasks' in journey)); assert(!('shopping' in journey));
  assert.throws(() => readRecapJourney(fixture.edited, 'f'.repeat(24)));
});
test('real v2 local time, hotel unknown clocks and manual cancelled state remain explicit', () => {
  const v = readRecapJourney(fixture.v2, fixture.v2.id);
  assert(v.events.find(e => e.kind === '航班').timing.join(' ').includes('Asia/Tokyo'));
  assert(v.events.find(e => e.kind === '住宿').timing.join(' ').includes('时刻未提供'));
  assert.equal(v.events.find(e => e.title === '[已取消] 人工取消活动').booking, '人工标记已取消');
  assert.equal(v.destinations[0].timeZone, 'Asia/Tokyo');
});
test('real projected places paginate; partner private rows and hidden coordinates stay absent', () => {
  const pages = fixture.places.map((p, i) => readRecapPlaces(p, journey, 'member1', i * 24));
  assert.equal(pages[0].items.length, 24); assert.equal(pages[1].items.length, 4); assert.equal(pages[0].total, 28);
  const all = pages.flatMap(p => p.items); assert.equal(all.find(p => p.name === '伴侣共享 hidden').coordinates, null);
  assert.deepEqual(all.find(p => p.name === '伴侣共享 coarse').coordinates, { latitude: 31.2, longitude: 121.5 });
  assert.equal(all.find(p => p.name === '伴侣共享 exact').coordinates.latitude, 31.234567);
  assert(!JSON.stringify(pages).includes('sharedCoordinates')); assert(!JSON.stringify(pages).includes('PRIVATE_PARTNER'));
});
test('real confirmed JPEG list, second page and revocation use current permissions', () => {
  const first = readRecapPhotos(fixture.photos[0], journey, 0), second = readRecapPhotos(fixture.photos[1], journey, 24);
  assert.equal(first.total, 26); assert.equal(second.items.length, 2);
  const p = readRecapPhoto(fixture.photo, journey, fixture.photo.item.id); assert.equal(p.caption, '伴侣共享照片'); assert(!('accountId' in p));
  assert.equal(readRecapPhotos(fixture.revokedPhotos, journey, 0).total, 25); assert.equal(fixture.revokedStatus, 404);
  assert.equal(fixture.tvPlaces, 403); assert.equal(fixture.tvPhotos, 403); assert.equal(fixture.foreign, 404);
});
test('mixed journey, duplicate pages, hidden exact coordinates and hostile previews are rejected', () => {
  const p = clone(fixture.places[0]); p.items[0].journeyId = 'a'.repeat(24); assert.throws(() => readRecapPlaces(p, journey, 'member1', 0));
  const duplicate = clone(fixture.photos[0]); duplicate.items[1] = duplicate.items[0]; assert.throws(() => readRecapPhotos(duplicate, journey, 0));
  const hidden = clone(fixture.places[0]); hidden.items[0].coordinatePrecision = 'hidden'; hidden.items[0].coordinates = { latitude: 1, longitude: 1 }; assert.throws(() => readRecapPlaces(hidden, journey, 'member1', 0));
  const photo = clone(fixture.photo); photo.item.previewUrl = 'https://evil.invalid/image'; assert.throws(() => readRecapPhoto(photo, journey, photo.item.id));
  const privatePartner = clone(fixture.photo); privatePartner.item.visibility = 'private'; privatePartner.item.canManage = false; assert.throws(() => readRecapPhoto(privatePartner, journey, privatePartner.item.id));
  const grid = clone(fixture.places[0]); grid.items[0].coordinateGridDegrees = { secret: 'not a number' }; assert.throws(() => readRecapPlaces(grid, journey, 'member1', 0));
  const other = { ...journey, tripId: 'f'.repeat(24) }; assert.throws(() => readRecapPhotos(fixture.photos[0], other, 0));
});
test('paths allow only exact workflow IDs, 24-row pages and bounded offsets', () => {
  assert.equal(recapPagePath('places', fixture.id, 24), `/journey-places?scope=visible&journeyId=${fixture.id}&limit=24&offset=24`);
  for (const [kind, id, offset] of [['places', fixture.id, 1], ['photos', fixture.id, 4008], ['places', '../accounts', 0], ['unknown', fixture.id, 0]]) assert.throws(() => recapPagePath(kind, id, offset));
});
test('before/after identity must match full household, role, member, auth version and csrf', async () => {
  const original = fixture.session, expected = recapSignature(original);
  for (const changed of [{ ...original, csrf: 'different' }, { ...original, user: { ...original.user, id: 'member2' } }, { ...original, user: { ...original.user, householdId: 'other' } }, { ...original, user: { ...original.user, role: 'tv' } }, { ...original, user: { ...original.user, auth_version: original.user.auth_version + 1 } }]) {
    const fence = new RecapFence(expected); let n = 0;
    await assert.rejects(fence.run(async () => ++n === 1 ? original : changed, async () => journey, () => true), /identity/);
  }
  let called = false; await assert.rejects(new RecapFence(expected).run(async () => ({ user: null }), async () => { called = true; }, () => true), RecapDiscarded); assert.equal(called, false);
});
test('invalidated or departed reads cannot publish success; post-me failure discards data', async () => {
  const fence = new RecapFence(recapSignature(fixture.session));
  await assert.rejects(fence.run(async () => fixture.session, async () => { fence.invalidate(); return journey; }, () => true), RecapDiscarded);
  let n = 0; await assert.rejects(fence.run(async () => { if (++n === 2) throw new RecapError('offline'); return fixture.session; }, async () => journey, () => true), /offline/);
  await assert.rejects(fence.run(async () => fixture.session, async () => journey, () => false), RecapDiscarded);
});
test('transport never forwards arbitrary origins, routes, query overrides or write methods', async () => {
  const old = globalThis.fetch; let calls = 0;
  globalThis.fetch = async () => { ++calls; throw new Error('must not fetch'); };
  try { for (const path of ['https://evil.invalid', '//evil.invalid', '/state', '/media/imports', '/journeys/../me', `/media/items?scope=mine&journeyId=${fixture.id}&limit=24&offset=0`, '/me?owner=member2']) await assert.rejects(recapRequest(path, new AbortController().signal)); assert.equal(calls, 0); }
  finally { globalThis.fetch = old; }
});
test('bounded transport consumes actual API JSON/JPEG bytes with same-origin no-store settings', async () => {
  const old = globalThis.fetch, seen = [];
  globalThis.fetch = async (path, init) => { seen.push({ path, init }); return path.endsWith('/preview') ? new Response(Buffer.from(fixture.jpeg, 'base64'), { headers: { 'Content-Type': 'image/jpeg' } }) : new Response(JSON.stringify(fixture.edited), { headers: { 'Content-Type': 'application/json' } }); };
  try {
    assert.equal(readRecapJourney(await recapRequest('/journeys/' + fixture.id, new AbortController().signal), fixture.id).title, journey.title);
    const blob = await recapRequest('/media/items/' + fixture.photo.item.id + '/preview', new AbortController().signal); assert.equal(blob.type, 'image/jpeg'); assert.equal(blob.size, Buffer.from(fixture.jpeg, 'base64').length);
    for (const { init } of seen) { assert.equal(init.method, 'GET'); assert.equal(init.mode, 'same-origin'); assert.equal(init.credentials, 'same-origin'); assert.equal(init.redirect, 'error'); assert.equal(init.cache, 'no-store'); assert(!init.body); }
  } finally { globalThis.fetch = old; }
});
test('malformed, non-JSON, oversized, revoked and aborted responses never become a snapshot', async () => {
  const old = globalThis.fetch;
  try {
    for (const response of [new Response('<html/>', { headers: { 'Content-Type': 'text/html' } }), new Response('{bad', { headers: { 'Content-Type': 'application/json' } }), new Response('x'.repeat(2_000_001), { headers: { 'Content-Type': 'application/json' } }), new Response('{}', { status: 403 })]) {
      globalThis.fetch = async () => response; await assert.rejects(recapRequest('/me', new AbortController().signal), RecapError);
    }
    globalThis.fetch = async () => { throw new Error('No automatic retry'); }; const abort = new AbortController(); abort.abort(); await assert.rejects(recapRequest('/me', abort.signal), RecapDiscarded);
  } finally { globalThis.fetch = old; }
});
