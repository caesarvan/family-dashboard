"""Real member/TV Flask requests, SQLite, synthetic media and explicit route ACL."""
from concurrent.futures import ThreadPoolExecutor
import json
import secrets
import sqlite3
from threading import Barrier

import pytest

import media_trip_playback as trips
from app import create_app
from test_household_media import device, offline
from test_journey_documents import clone, create_journey, login
from test_journey_places import create as create_place
from test_journey_routes import create as create_route, update as update_route
from test_media_playback import env, granted, command, path, setup
from test_media_video_tv import report, snapshot as tv_state
from test_media_video_integration import clip, tools, imported


def preview(c, h, uid, journey_id, route_id=None):
    revision = c.get(path(uid)).json['revision']
    response = c.post(path(uid)+'/journey-preview', headers=h,
                      json=dict(revision=revision, journeyId=journey_id, routeId=route_id))
    assert response.status_code == 200, response.json
    return response.json


def start(c, h, uid, value):
    payload = dict(requestId=secrets.token_hex(16), previewToken=value['previewToken'], confirmStart=True)
    response = c.post(path(uid)+'/journey-start', headers=h, json=payload)
    assert response.status_code == 200, response.json
    return response.json, payload


def link(c, h, item, journey_id):
    current = c.get('/api/media/items/'+item['id']).json['item']
    reply = c.patch('/api/media/items/'+item['id'], headers=h,
                    json=dict(revision=current['revision'], journeyId=journey_id))
    assert reply.status_code == 200, reply.json
    return reply.json['item']


def route(c, h, trip, *, private=False, count=3):
    points = [create_place(c, h, name='SYNTHETIC-POINT-'+str(i), journeyId=trip['id'],
              expectedJourneyRevision=1, visibility='shared', coordinateDisclosure='coarse',
              coordinates=dict(latitude=31.234567+i, longitude=121.456789))[0] for i in range(count)]
    detail, _ = create_route(c, h, trip, points, title='SYNTHETIC-ROUTE', visibility='private' if private else 'shared')
    return detail['current'], points


def seeded(env, count=3):
    c, h, uid, tv, secret, items = granted(env, count)
    trip = create_journey(c, h)
    for item in items[:2]:
        link(c, h, item, trip['id'])
    detail, points = route(c, h, trip)
    return c, h, uid, tv, items, trip, detail, points


def snapshot(env):
    with env[1].transaction() as con:
        return {name: [tuple(r) for r in con.execute('SELECT * FROM '+name+' ORDER BY rowid')]
                for name in ('media_items', 'media_tv_grants', 'media_playback', 'media_playback_progress',
                             'media_playback_journeys', 'media_playback_operations', 'journey_places',
                             'journey_routes', 'audit', 'settings')}


def test_preview_start_scope_persist_receipt_and_explicit_exit(env):
    c, h, uid, tv, items, trip, detail, _ = seeded(env)
    before = snapshot(env)
    value = preview(c, h, uid, trip['id'], detail['route']['id'])
    assert snapshot(env) == before and value['mediaCount'] == 2 and value['canStart']
    assert value['journey'] == dict(id=trip['id'], tripId=trip['tripId'], title='合成旅行',
        start='2026-12-01', end='2026-12-04', revision=1, tripRevision=1)
    assert value['route']['stops'][0]['place']['coordinates']['latitude'] == 31.2
    result, payload = start(c, h, uid, value)
    after = snapshot(env)
    for table in ('media_items', 'media_tv_grants', 'journey_places', 'journey_routes'):
        assert after[table] == before[table]
    assert len(after['media_playback_operations']) == len(after['media_playback_journeys']) == 1
    assert after['audit'][-1][2] == 'media_playback_journey_start'
    assert result['playback']['scope'] == 'journey' and not result['replayed']
    current = tv_state(tv)
    assert current['photoCount'] == 2 and current['journeyReview']['journey'] == value['journey']
    allowed = {i['id'] for i in items[:2]}
    assert current['item']['id'] in allowed
    current = report(tv, current, 'ended', current['progress']['durationMs']).json
    assert current['item']['id'] in allowed
    restarted = create_app(dict(env[0].config))
    recovered = clone(restarted, c).get('/api/media-playback/operations/'+payload['requestId'])
    assert recovered.status_code == 200 and recovered.json['operation'] == result['operation']
    env[2][0] += 301
    before_replay = snapshot(env)
    replay = c.post(path(uid)+'/journey-start', headers=h, json=payload)
    assert replay.status_code == 200 and replay.json['replayed']
    assert replay.json['operation'] == result['operation'] and snapshot(env) == before_replay
    assert c.post(path(uid)+'/journey-start', headers=h, json={**payload, 'previewToken':value['previewToken']+'a'}).status_code == 400
    changed = {**payload, 'previewToken':preview(c,h,uid,trip['id'])['previewToken']}
    assert c.post(path(uid)+'/journey-start', headers=h, json=changed).status_code == 409
    assert command(c,h,uid,'pause')['scope'] == 'journey'
    assert command(c,h,uid,'resume')['scope'] == 'journey'
    assert command(c,h,uid,'start')['scope'] == 'all'
    assert tv_state(tv)['photoCount'] == 3
    start(c,h,uid,preview(c,h,uid,trip['id']))
    assert command(c,h,uid,'dashboard')['journeyReview'] is None


def test_route_only_private_route_denied_gaps_and_no_inferred_route(env):
    uid,tv,_ = device(env); c,h=login(env[0]); trip=create_journey(c,h)
    empty = preview(c,h,uid,trip['id'])
    assert not empty['canStart'] and empty['route'] is None and empty['routeStatus']=='not_selected'
    assert c.post(path(uid)+'/journey-start',headers=h,json=dict(requestId=secrets.token_hex(16),
        previewToken=empty['previewToken'],confirmStart=True)).status_code==403
    detail,points=route(c,h,trip,private=True)
    assert c.post(path(uid)+'/journey-preview',headers=h,json=dict(revision=0,journeyId=trip['id'],routeId=detail['route']['id'])).status_code==404
    shared=c.put('/api/journey-routes/'+detail['route']['id'],headers=h,json=update_route(detail,visibility='shared'))
    assert shared.status_code==200,shared.json
    # A shared route must not expose the author's now-private middle point.
    mid=c.patch('/api/journey-places/'+points[1]['id'],headers=h,
                json=dict(revision=points[1]['revision'],visibility='private'))
    assert mid.status_code==200,mid.json
    value=preview(c,h,uid,trip['id'],detail['route']['id'])
    assert value['route']['stops'][1]==dict(index=1,state='unavailable')
    assert value['route']['segments']==[] and value['canStart']
    start(c,h,uid,value)
    state=tv_state(tv)
    assert state['photoCount']==0 and state['item'] is None and state['progress'] is None and state['canStart']
    assert command(c,h,uid,'pause')['paused'] and not command(c,h,uid,'resume')['paused']
    assert c.put(path(uid),headers=h,json=dict(revision=c.get(path(uid)).json['revision'],action='next')).status_code==403
    assert 'owner' not in json.dumps(state) and '31.234567' not in json.dumps(state)


@pytest.mark.parametrize('change',['route_private','route_deleted','route_moved','place_private','place_deleted','coordinates_hidden',
                                   'media_grant','media_source','journey_deleted','journey_broken'])
def test_fresh_source_changes_never_broaden_scope(env,change):
    c,h,uid,tv,items,trip,detail,points=seeded(env)
    start(c,h,uid,preview(c,h,uid,trip['id'],detail['route']['id']))
    original=tv_state(tv)
    if change=='route_deleted':
        response=c.delete('/api/journey-routes/'+detail['route']['id'],headers=h,json={
            'requestId':secrets.token_hex(16),'revision':detail['route']['revision'],
            'sourceVersion':detail['route']['sourceVersion']})
        assert response.status_code==200,response.json
    with env[1].transaction(True) as con:
        if change=='route_private':con.execute("UPDATE journey_routes SET visibility='private' WHERE id=?",(detail['route']['id'],))
        elif change=='route_deleted':pass  # Original delete retains its durable route receipt.
        elif change=='route_moved':con.execute('UPDATE journey_routes SET journey_id=NULL WHERE id=?',(detail['route']['id'],))
        elif change=='place_private':con.execute("UPDATE journey_places SET visibility='private' WHERE id=?",(points[1]['id'],))
        elif change=='place_deleted':con.execute('DELETE FROM journey_places WHERE id=?',(points[1]['id'],))
        elif change=='coordinates_hidden':con.execute("UPDATE journey_places SET coordinate_disclosure='hidden' WHERE id=?",(points[1]['id'],))
        elif change=='media_grant':con.execute('DELETE FROM media_tv_grants WHERE device_id=?',(uid,))
        elif change=='media_source':con.execute('UPDATE cloud_accounts SET needs_reauth=1')
        elif change=='journey_deleted':con.execute('DELETE FROM entities WHERE id=?',(trip['tripId'],))
        else:
            value=json.loads(con.execute('SELECT data FROM entities WHERE id=?',(trip['tripId'],)).fetchone()[0])
            value['journeyId']='f'*24
            con.execute('UPDATE entities SET data=? WHERE id=?',(json.dumps(value),trip['tripId']))
    current=tv_state(tv); review=current['journeyReview']
    assert current['scope']=='journey' and review['sourceVersion']!=original['journeyReview']['sourceVersion']
    assert items[2]['id'] not in json.dumps(current)
    if change.startswith('journey_'):
        assert review['status']=='journey_unavailable' and review['journey'] is None and review['route'] is None
        assert current['item'] is None and current['photoCount']==0 and not current['canStart']
        with env[1].transaction() as con:assert con.execute('SELECT count(*) FROM media_playback_journeys').fetchone()[0]==1
    elif change.startswith('route_'):
        assert review['routeStatus']=='unavailable' and review['route'] is None and current['photoCount']==2
    elif change.startswith('media_'):
        assert current['item'] is None and current['photoCount']==0 and current['canStart']
    else:
        assert review['route']['segments']==[]
        if change=='coordinates_hidden':assert review['route']['stops'][1]['place']['coordinates'] is None
        else:assert review['route']['stops'][1]==dict(index=1,state='unavailable')


def test_token_session_device_revision_source_binding_and_empty_preview(env):
    c,h,uid,tv,items,trip,detail,_=seeded(env)
    value=preview(c,h,uid,trip['id'],detail['route']['id'])
    payload=dict(requestId=secrets.token_hex(16),previewToken=value['previewToken'],confirmStart=True)
    other,oh=login(env[0],2); second,tv2,_=device(env)
    assert other.post(path(uid)+'/journey-start',headers=oh,json=payload).status_code==403
    assert c.post(path(second)+'/journey-start',headers=h,json=payload).status_code==403
    tampered=dict(payload,previewToken=value['previewToken'][:-1]+('0' if value['previewToken'][-1]!='0' else '1'))
    assert c.post(path(uid)+'/journey-start',headers=h,json=tampered).status_code==400
    command(c,h,uid,'interval',intervalSeconds=9)
    assert c.post(path(uid)+'/journey-start',headers=h,json=payload).status_code==409
    payload['previewToken']=preview(c,h,uid,trip['id'],detail['route']['id'])['previewToken']
    link(c,h,items[0],create_journey(c,h,'Another')['id'])
    assert c.post(path(uid)+'/journey-start',headers=h,json=payload).status_code==409
    payload['previewToken']=preview(c,h,uid,trip['id'])['previewToken'];env[2][0]+=301
    assert c.post(path(uid)+'/journey-start',headers=h,json=payload).status_code==410
    assert tv_state(tv2)['scope']=='all'


def test_receipt_owner_only_device_deleted_and_quota_replay(env,monkeypatch):
    c,h,uid,tv,_,trip,_,_=seeded(env)
    result,payload=start(c,h,uid,preview(c,h,uid,trip['id']))
    url='/api/media-playback/operations/'+payload['requestId']
    other,_=login(env[0],2)
    assert other.get(url).json==dict(found=False)
    assert tv.get(url).status_code==403
    assert c.get('/api/media-playback/operations/'+'f'*32).json==dict(found=False)
    monkeypatch.setattr(trips,'MAX_OPERATIONS',1)
    assert c.post(path(uid)+'/journey-start',headers=h,json=payload).json['replayed']
    assert c.post(path(uid)+'/journey-start',headers=h,json={**payload,'requestId':secrets.token_hex(16)}).status_code==429
    with env[1].transaction(True) as con:con.execute('DELETE FROM devices WHERE id=?',(uid,))
    receipt=c.get(url)
    assert receipt.status_code==200 and receipt.json==dict(found=True,operation=result['operation'],playback=None)
    assert c.post(path(uid)+'/journey-start',headers=h,json=payload).json['playback'] is None


@pytest.mark.parametrize('same_request',[False,True])
def test_parallel_start_has_one_effect_and_durable_owner_receipt(env,same_request):
    c,h,uid,_,_,trip,_,_=seeded(env)
    value=preview(c,h,uid,trip['id'])
    payload=dict(requestId=secrets.token_hex(16),previewToken=value['previewToken'],confirmStart=True)
    payloads=[payload,dict(payload,requestId=payload['requestId'] if same_request else secrets.token_hex(16))]
    clients=[clone(env[0],c),clone(env[0],c)];gate=Barrier(2)
    def run(index):
        gate.wait()
        return clients[index].post(path(uid)+'/journey-start',headers=h,json=payloads[index])
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(run,range(2)))
    assert sorted(r.status_code for r in results)==([200,200] if same_request else [200,409])
    if same_request:assert sorted(r.json['replayed'] for r in results)==[False,True]
    with env[1].transaction() as con:
        assert con.execute('SELECT count(*) FROM media_playback_operations').fetchone()[0]==1
        assert con.execute('SELECT revision FROM media_playback WHERE device_id=?',(uid,)).fetchone()[0]==1
        assert con.execute("SELECT count(*) FROM audit WHERE action='media_playback_journey_start'").fetchone()[0]==1


def test_atomic_schema_requires_transaction_and_rollback_keeps_original_tables(env):
    with env[1].sessions.db() as con:
        with pytest.raises(RuntimeError):trips.init_schema(con)
        con.execute('BEGIN IMMEDIATE');trips.init_schema(con);assert con.in_transaction;con.rollback()
        before={r[0]:r[1] for r in con.execute("SELECT name,sql FROM sqlite_master WHERE name IN ('media_playback','media_playback_progress')")}
        con.execute('BEGIN IMMEDIATE');con.execute('DROP TABLE media_playback_operations');con.execute('DROP TABLE media_playback_journeys')
        trips.init_schema(con);con.rollback()
        assert before=={r[0]:r[1] for r in con.execute("SELECT name,sql FROM sqlite_master WHERE name IN ('media_playback','media_playback_progress')")}


def test_audit_failure_rolls_back_selection_receipt_and_progress(env,monkeypatch):
    c,h,uid,_,_,trip,_,_=seeded(env)
    value=preview(c,h,uid,trip['id']);before=snapshot(env)
    def fail(*_args):raise RuntimeError('synthetic audit failure')
    monkeypatch.setattr(env[1],'_audit',fail)
    with pytest.raises(RuntimeError,match='synthetic audit failure'):start(c,h,uid,value)
    assert snapshot(env)==before


@pytest.mark.parametrize('payload',[
    {}, {'revision':True,'journeyId':'a'*24,'routeId':None},
    {'revision':0,'journeyId':'a'*24}, {'revision':0,'journeyId':'a'*24,'routeId':''},
    {'revision':0,'journeyId':'a'*24,'routeId':None,'owner':'member1'},
    {'revision':9007199254740991,'journeyId':'a'*24,'routeId':None},
])
def test_strict_preview_input_and_tv_csrf_denial(env,payload):
    uid,tv,_=device(env);c,h=login(env[0]);url=path(uid)+'/journey-preview'
    assert c.post(url,headers=h,json=payload).status_code==400
    assert c.post(url,json=payload).status_code==403
    assert tv.post(url,json=payload,headers={'X-Display-Mode':'tv'}).status_code==403


def test_two_signed_households_cannot_read_or_start_original_scope(env):
    c,h,uid,tv,_,trip,_,_=seeded(env)
    _,payload=start(c,h,uid,preview(c,h,uid,trip['id']))
    invite=c.post('/api/spaces/invitations',headers=h,json={})
    assert invite.status_code==201,invite.json
    child=env[0].test_client()
    redeemed=child.post('/api/spaces/redeem',json=dict(invitation=invite.json['invitation'],name='SYNTHETIC-OTHER',
        slug='trip-second-home',MEMBER1_PASSWORD='second-home-password-one',MEMBER2_PASSWORD='second-home-password-two'))
    assert redeemed.status_code==201,redeemed.json
    space=redeemed.json
    assert child.get(space['entry']).status_code==303
    assert child.post('/api/login',json={'username':'member1','password':'second-home-password-one'}).status_code==200
    headers={'X-CSRF-Token':child.get('/api/me').json['csrf'],'Origin':'http://localhost'}
    assert child.get('/api/media-playback/operations/'+payload['requestId']).json==dict(found=False)
    assert child.post(path(uid)+'/journey-preview',headers=headers,json=dict(revision=0,journeyId=trip['id'],routeId=None)).status_code==404
    assert child.post(path(uid)+'/journey-start',headers=headers,json=payload).status_code==400
    child.set_cookie('household_tv',tv.get_cookie('household_tv').value)
    assert child.get('/api/media-tv/playback',headers={'X-Display-Mode':'tv'}).status_code==401


@pytest.mark.parametrize('old_first',[False,True])
def test_unknown_old_start_and_new_preview_share_cas_in_both_orders(env,old_first):
    c,h,uid,_,_,trip,_,_=seeded(env)
    other=create_journey(c,h,'SYNTHETIC-NEW-INTENT')
    other_route,_=route(c,h,other)
    old=preview(c,h,uid,trip['id'])
    new=preview(c,h,uid,other['id'],other_route['route']['id'])
    bodies=[dict(requestId=secrets.token_hex(16),previewToken=v['previewToken'],confirmStart=True) for v in (old,new)]
    first,late=(0,1) if old_first else (1,0)
    assert c.post(path(uid)+'/journey-start',headers=h,json=bodies[first]).status_code==200
    before=snapshot(env)
    assert c.post(path(uid)+'/journey-start',headers=h,json=bodies[late]).status_code==409
    assert snapshot(env)==before
    assert c.get('/api/media-playback/operations/'+bodies[late]['requestId']).json==dict(found=False)
    # A deliberately new preview AFTER that committed result is a new intent.
    next_value=preview(c,h,uid,other['id'],other_route['route']['id'])
    result,_=start(c,h,uid,next_value)
    assert result['operation']['resultRevision']==2


def test_dashboard_tv_does_not_scan_album_and_selection_query_has_no_blobs(env,monkeypatch):
    c,h,uid,tv,_,trip,_,_=seeded(env)
    controller=env[0].extensions['media_playback'];original=controller._photos
    def forbidden(*_args,**_kwargs):raise AssertionError('Dashboard must not scan media')
    monkeypatch.setattr(controller,'_photos',forbidden)
    assert tv_state(tv)['scope']=='all'
    monkeypatch.setattr(controller,'_photos',original)
    with env[1].transaction() as con:
        queries=[]
        def authorize(action,table,column,*_args):
            if action==sqlite3.SQLITE_READ and (column in ('preview_cipher','cipher') or table=='media_video_cache'):
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        con.set_authorizer(authorize);con.set_trace_callback(queries.append)
        rows=controller._photos(con,uid,journey_id=trip['id'])
        assert len(rows)==2
        query=next(q for q in queries if 'JOIN media_tv_grants' in q)
        assert query.index('m.journey_id=')<query.index('LIMIT 2001')


def test_real_video_in_scoped_playlist_preserves_native_progress(env,clip,tools):
    c,h,uid,tv,_,trip,_,_=seeded(env)
    vc,vh,video,*_=imported(env,clip,tools)
    video=link(vc,vh,video,trip['id'])
    video=vc.patch('/api/media/items/'+video['id'],headers=vh,json=dict(revision=video['revision'],visibility='shared')).json['item']
    assert vc.put('/api/media/items/'+video['id']+'/tv-grants',headers=vh,json=dict(revision=video['revision'],
        deviceIds=[uid],consentVersion='media-v1',allowTvDisplay=True)).status_code==200
    start(c,h,uid,preview(c,h,uid,trip['id']))
    for _ in range(3):
        state=tv_state(tv)
        if state['item']['mediaType']=='video':break
        command(c,h,uid,'next')
    assert state['item']['id']==video['id']
    response=tv.get(state['item']['videoUrl'])
    assert response.status_code==200 and response.content_type=='video/mp4';response.close()
    ended=report(tv,state,'ended',state['progress']['durationMs'])
    assert ended.status_code==200 and ended.json['scope']=='journey' and ended.json['item']['mediaType']=='photo'
