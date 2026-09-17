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
const { readPhotoJourneySuggestions: read, photoSuggestionBody: body } = await import(new URL('photoJourneySuggestions.ts', lib));
const { PhotoReadFence, PhotoReadDiscarded, photoSignature } = await import(new URL('photos.ts', lib));
const root = resolve(process.env.PHOTO_SUGGESTIONS_BACKEND_ROOT || fileURLToPath(new URL('..', import.meta.url)));
const setup = spawnSync(process.env.PHOTO_SUGGESTIONS_TEST_PYTHON || 'python', ['-B', '-X', 'utf8', '-c', String.raw`
import json,sys,tempfile,socket
from pathlib import Path
from unittest.mock import patch
from pytest import MonkeyPatch
root=Path(sys.argv[1]);sys.path[:0]=[str(root),str(root/'tests')]
from test_household_media import configured,share,device
from test_journey_documents import login
from test_media_journey_suggestions import photo,journey,suggestions,payload,metadata
def denied(*a,**k): raise AssertionError('External network forbidden')
with tempfile.TemporaryDirectory(prefix='photo-suggestions-model-') as folder,MonkeyPatch.context() as mp,patch.object(socket.socket,'connect',denied),patch('socket.create_connection',denied):
    env=configured(Path(folder)/'one',mp)
    c,h,item,_=photo(env,'2026-12-01T08:30:00.123456789-08:00')
    result={'photo':item,'session':c.get('/api/me').json,'empty':suggestions(c,item)}
    legacy=journey(c,h,title='合成旧版旅行')
    modern=journey(c,h,title='合成新版旅行',tz='America/Los_Angeles',start='2026-12-01',end='2026-12-01')
    result['legacyId']=legacy['id'];result['modernId']=modern['id'];result['initial']=suggestions(c,item)
    stale=payload(result['initial'],next(i for i,r in enumerate(result['initial']['suggestions']) if r['journeyId']==legacy['id']))
    changed=c.patch('/api/items/trips/'+legacy['tripId'],headers=h,json={'revision':legacy['trip']['revision'],'title':'当前单独修改的旅行','end':'2026-12-03'})
    assert changed.status_code==200,changed.json
    result['staleStatus']=c.patch('/api/media/items/'+item['id'],headers=h,json=stale).status_code
    assert result['staleStatus']==409
    result['current']=suggestions(c,item)
    selected=next(i for i,r in enumerate(result['current']['suggestions']) if r['journeyId']==modern['id'])
    result['submitted']=payload(result['current'],selected)
    linked=c.patch('/api/media/items/'+item['id'],headers=h,json=result['submitted']);assert linked.status_code==200,linked.json
    item=linked.json['item'];result['linkedPhoto']=item;result['linked']=suggestions(c,item)
    result['repeatStatus']=c.patch('/api/media/items/'+item['id'],headers=h,json=result['submitted']).status_code
    assert result['repeatStatus']==409
    for n in range(18): journey(c,h,title='合成重叠旅行 '+str(n))
    result['twenty']=suggestions(c,item);assert len(result['twenty']['suggestions'])==20 and not result['twenty']['hasMore']
    journey(c,h,title='第 21 项');result['more']=suggestions(c,item);assert result['more']['hasMore']
    metadata(env,item['id'],remove=True)
    result['unknownPhoto']=c.get('/api/media/items/'+item['id']).json['item'];result['unknown']=suggestions(c,item)
    shared=share(c,h,result['unknownPhoto']);partner,ph=login(env[0],2)
    result['partnerPhoto']=partner.get('/api/media/items/'+item['id']).json['item']
    path='/api/media/items/'+item['id']+'/journey-suggestions'
    result['partnerStatus']=partner.get(path).status_code
    _,tv,_=device(env);result['tvStatus']=tv.get(path).status_code
    result['anonymousStatus']=env[0].test_client().get(path).status_code
    foreign=configured(Path(folder)/'two',mp,'foreign');fc,fh=login(foreign[0]);result['foreignStatus']=fc.get(path).status_code
print(json.dumps(result,ensure_ascii=False))
`, root], { cwd: root, encoding: 'utf8', timeout: 120000, maxBuffer: 4_000_000 });
assert.equal(setup.status, 0, setup.stderr || setup.error?.message || 'Real fixture failed');
const f = JSON.parse(setup.stdout), clone = value => structuredClone(value);
const mutate = change => { const value = clone(f.current); change(value); return value; };

test('real v1/v2 dates use server zones; original nanoseconds and offset are preserved', () => {
  const parsed = read(f.initial, f.photo);
  assert.equal(parsed.sourceCreatedAt, '2026-12-01T08:30:00.123456789-08:00');
  const legacy = parsed.suggestions.find(r => r.journeyId === f.legacyId), modern = parsed.suggestions.find(r => r.journeyId === f.modernId);
  assert.equal(legacy.sourceDate, '2026-12-02'); assert.equal(legacy.referenceTimezone, 'Asia/Shanghai'); assert.equal(legacy.referenceTimezoneSource, 'legacy_default');
  assert.equal(modern.sourceDate, '2026-12-01'); assert.equal(modern.referenceTimezone, 'America/Los_Angeles'); assert.equal(modern.referenceTimezoneSource, 'plan');
});
test('real current trip title and revision override old plan; stale confirm is rejected', () => {
  const old = read(f.initial, f.photo).suggestions.find(r => r.journeyId === f.legacyId);
  const current = read(f.current, f.photo).suggestions.find(r => r.journeyId === f.legacyId);
  assert.equal(current.title, '当前单独修改的旅行'); assert.equal(current.end, '2026-12-03');
  assert.equal(current.tripRevision, old.tripRevision + 1); assert.equal(current.journeyRevision, old.journeyRevision); assert.equal(f.staleStatus, 409);
});
test('real known no-match and unknown legacy time remain distinct without import-time fallback', () => {
  const empty = read(f.empty, f.photo), unknown = read(f.unknown, f.unknownPhoto);
  assert.equal(empty.reason.code, 'no_matching_journeys'); assert.equal(empty.sourceTimeState, 'known');
  assert.equal(unknown.reason.code, 'source_time_unknown'); assert.equal(unknown.sourceCreatedAt, null); assert.deepEqual(unknown.suggestions, []);
  assert.notEqual(f.unknownPhoto.createdAt, null);
});
test('real 20 and 21 matches keep limit and hasMore without inventing pagination', () => {
  const last = read(f.twenty, f.linkedPhoto), more = read(f.more, f.linkedPhoto);
  assert.equal(last.suggestions.length, 20); assert.equal(last.hasMore, false);
  assert.equal(more.suggestions.length, 20); assert.equal(more.hasMore, true); assert.equal(more.limit, 20);
});
test('body equals the exact four-field request accepted by the actual API', () => {
  assert.deepEqual(body(f.photo, read(f.current, f.photo), f.modernId), f.submitted);
  assert.deepEqual(Object.keys(f.submitted).sort(), ['expectedJourneyRevision', 'expectedTripRevision', 'journeyId', 'revision']);
  assert.equal(f.linkedPhoto.revision, f.photo.revision + 1); assert.equal(f.linkedPhoto.journey.id, f.modernId);
  assert.equal(f.linkedPhoto.caption, f.photo.caption); assert.equal(f.linkedPhoto.visibility, 'private'); assert.equal(f.repeatStatus, 409);
  assert.throws(() => body(f.linkedPhoto, read(f.linked, f.linkedPhoto), f.modernId));
  assert.throws(() => body(f.photo, read(f.current, f.photo), 'f'.repeat(24)));
});
test('real owner-only API denies partner, TV, anonymous and another household', () => {
  assert.deepEqual([f.partnerStatus, f.tvStatus, f.anonymousStatus, f.foreignStatus], [404, 403, 401, 404]);
  assert.equal(f.partnerPhoto.canManage, false); assert(!('sourceCreatedAt' in f.partnerPhoto));
  assert.throws(() => read(f.unknown, f.partnerPhoto));
});
test('photo ID, revision, current journey and manage permission must match', () => {
  for (const patch of [{ id: 'f'.repeat(24) }, { revision: f.photo.revision + 1 }, { canManage: false }, { journey: f.linkedPhoto.journey }, { journey: undefined }]) assert.throws(() => read(f.current, { ...f.photo, ...patch }));
  assert.throws(() => body(f.linkedPhoto, read(f.current, f.photo), f.modernId));
  assert.throws(() => read(mutate(v => { v.currentJourneyId = f.modernId; }), f.photo));
});
test('all original origin fields, if present, must match; older Photo types may omit both', () => {
  const older = clone(f.photo); delete older.sourceCreatedAt; delete older.sourceTimeState;
  assert.deepEqual(read(f.current, older), read(f.current, f.photo));
  for (const patch of [{ sourceTimeState: 'unknown' }, { sourceCreatedAt: null }, { sourceCreatedAt: undefined }]) assert.throws(() => read(f.current, { ...f.photo, ...patch }));
});
test('malformed source instants are rejected without Date normalization or zone conversion', () => {
  const photo = clone(f.photo); delete photo.sourceCreatedAt; delete photo.sourceTimeState;
  for (const stamp of ['2026-02-30T00:00:00Z', '0000-01-01T00:00:00Z', '2026-12-01 00:00:00Z', '2026-12-01T24:00:00Z', '2026-12-01T00:00:60Z', '2026-12-01T00:00:00.1234567890Z', '2026-12-01T00:00:00+24:00', null, 123]) assert.throws(() => read(mutate(v => { v.sourceCreatedAt = stamp; }), photo));
});
test('strict shape, unique bounded list, state/reason and linked marker reject inconsistent data', () => {
  const changes = [v => { v.extra = true; }, v => { delete v.reason; }, v => { v.limit = 21; }, v => { v.hasMore = 1; }, v => { v.hasMore = true; },
    v => { v.suggestions.push(v.suggestions[0]); }, v => { v.suggestions = Array(21).fill(v.suggestions[0]); }, v => { v.sourceTimeState = 'unknown'; },
    v => { v.reason.code = 'no_matching_journeys'; }, v => { v.suggestions[0].alreadyLinked = true; }, v => { v.suggestions[0].reason.extra = true; },
    v => { v.suggestions[0].title = {}; }, v => { v.suggestions[0].referenceTimezoneSource = new String('plan'); }];
  for (const change of changes) assert.throws(() => read(mutate(change), f.photo));
  for (const bad of [null, [], false]) assert.throws(() => read(bad, f.photo));
});
test('row IDs, revisions, valid dates, timezone provenance and inclusive range are strict', () => {
  for (const patch of [{ journeyId: '../x' }, { journeyRevision: true }, { tripRevision: 0 }, { tripRevision: 2 ** 53 }, { start: '2026-02-30' },
    { end: '2026-01-01' }, { sourceDate: '2026-12-04' }, { referenceTimezone: '' }, { referenceTimezone: 'https://host.invalid' },
    { referenceTimezone: 'UTC', referenceTimezoneSource: 'legacy_default' }, { reason: { code: 'unknown', message: '' } }]) {
    assert.throws(() => read(mutate(v => { Object.assign(v.suggestions[0], patch); }), f.photo));
  }
});
test('projected snapshots do not alias response objects and bodies revalidate mutated selections', () => {
  const raw = clone(f.current), parsed = read(raw, f.photo), original = clone(parsed);
  raw.suggestions[0].title = 'mutated'; raw.reason.message = 'mutated'; assert.deepEqual(parsed, original);
  parsed.suggestions[0].tripRevision = -1; assert.throws(() => body(f.photo, parsed, parsed.suggestions[0].journeyId));
  assert(!('accountId' in original)); assert(!('previewUrl' in original));
});
test('existing PhotoReadFence rejects every changed identity component after a real DTO read', async () => {
  const original = f.session;
  for (const changed of [{ ...original, csrf: 'different' }, ...['id', 'householdId', 'role', 'auth_version'].map(key => ({ ...original, user: { ...original.user, [key]: key === 'auth_version' ? original.user.auth_version + 1 : 'different' } }))]) {
    let calls = 0;
    const fence = new PhotoReadFence(async () => ++calls === 1 ? original : changed, original.user, photoSignature(original));
    await assert.rejects(fence.read(async () => read(f.current, f.photo), () => true), PhotoReadDiscarded);
  }
});
test('invalidated, departed and failed post-read session checks cannot publish suggestions', async () => {
  const make = me => new PhotoReadFence(me, f.session.user, photoSignature(f.session));
  const fence = make(async () => f.session);
  await assert.rejects(fence.read(async () => { fence.invalidate(); return read(f.current, f.photo); }, () => true), PhotoReadDiscarded);
  let active = true; await assert.rejects(fence.read(async () => { active = false; return read(f.current, f.photo); }, () => active), PhotoReadDiscarded);
  let count = 0; await assert.rejects(make(async () => { if (++count === 2) throw new Error('offline'); return f.session; }).read(async () => read(f.current, f.photo), () => true), /offline/);
});
