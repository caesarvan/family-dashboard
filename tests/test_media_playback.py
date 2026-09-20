"""Actual temporary SQLite/member+TV cookies; synthetic encrypted photo fixtures only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import socket
import sqlite3
import threading

import pytest

import media_playback as playback
from test_household_media import configured, confirm, device, selected, share, stage
from test_journey_documents import clone, login


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*_args, **_kwargs):
        raise AssertionError('Playback must never access external networks')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)


def setup(tmp_path, monkeypatch, household='default'):
    env = configured(tmp_path, monkeypatch, household)
    controller = env[0].extensions.get('media_playback') or playback.register_media_playback(env[0])
    controller.clock = lambda: env[2][0]
    return env, controller


@pytest.fixture
def env(tmp_path, monkeypatch):
    return setup(tmp_path/'one', monkeypatch)[0]


def path(uid):
    return '/api/media-playback/devices/'+uid


def granted(env, count=3):
    c, h, detail, _ = stage(env, items=[selected('synthetic-'+str(n)) for n in range(count)])
    confirm(c, h, detail)
    uid, tv, secret = device(env)
    items = []
    for item in detail['items']:
        item = c.get('/api/media/items/'+item['id']).json['item']
        item = share(c, h, item)
        response = c.put('/api/media/items/'+item['id']+'/tv-grants', headers=h, json={
            'revision':item['revision'], 'deviceIds':[uid], 'consentVersion':'media-v1', 'allowTvDisplay':True})
        assert response.status_code == 200, response.json
        item['revision'] = response.json['revision']
        items.append(item)
    return c, h, uid, tv, secret, items


def command(c, h, uid, action, **extra):
    before = c.get(path(uid)).json
    response = c.put(path(uid), headers=h, json={'revision':before['revision'], 'action':action, **extra})
    assert response.status_code == 200, response.json
    return response.json


def test_default_no_write_and_explicit_schema(env):
    uid, tv, _ = device(env)
    c, h = login(env[0])
    default = c.get(path(uid))
    assert default.status_code == 200
    assert default.json == dict(deviceId=uid, revision=0, mode='dashboard', paused=False,
        intervalSeconds=10, position=0, photoCount=0, canStart=False, updatedAt=None,
        scope='all', journeyReview=None)
    assert tv.get('/api/media-tv/playback').json['item'] is None
    with env[1].transaction() as con:
        assert con.execute('SELECT count(*) FROM media_playback').fetchone()[0] == 0
    with env[1].sessions.db() as con:
        playback.initialize_media_playback(con)
        con.execute('BEGIN IMMEDIATE')
        with pytest.raises(RuntimeError):
            playback.initialize_media_playback(con)
    assert c.put(path(uid), json={'revision':0, 'action':'start'}, headers=h).status_code == 403


def test_frozen_engine_photo_flow_persists_and_advances_only_on_actual_ended(env):
    c, h, uid, tv, _, items = granted(env)
    with env[1].transaction() as con:
        layout = tuple(con.execute('SELECT display_layout,revision FROM devices WHERE id=?',(uid,)).fetchone())
    assert command(c,h,uid,'start')['revision'] == 1
    first = tv.get('/api/media-tv/playback').json
    assert first['item']['id'] == sorted(i['id'] for i in items)[0]
    assert set(first['item']) == {'id','width','height','previewUrl','revision','mediaType'}
    assert 'filename' not in json.dumps(first) and 'account' not in json.dumps(first)
    assert tv.get(first['item']['previewUrl']).content_type == 'image/jpeg'
    def ended():
        current=tv.get('/api/media-tv/playback',headers={'X-Display-Mode':'tv'}).json
        progress=current['progress'];item=current['item']
        response=tv.post('/api/media-tv/playback/progress',headers={
            'X-Display-Mode':'tv','Origin':'http://localhost','X-TV-Playback-CSRF':current['playbackCsrf']},json={
            'revision':current['revision'],'playId':progress['playId'],'itemId':item['id'],
            'itemRevision':item['revision'],'sequence':progress['sequence']+1,
            'positionMs':progress['durationMs'],'event':'ended'})
        assert response.status_code==200,response.json
        return response.json
    env[2][0] += 10
    assert tv.get('/api/media-tv/playback').json['position'] == 0
    assert ended()['position'] == 1
    assert command(c,h,uid,'pause')['position'] == 1
    env[2][0] += 83
    assert tv.get('/api/media-tv/playback').json['position'] == 1
    assert command(c,h,uid,'previous')['position'] == 0
    assert command(c,h,uid,'previous')['position'] == 2
    assert command(c,h,uid,'next')['position'] == 0
    assert command(c,h,uid,'interval',intervalSeconds=5)['intervalSeconds'] == 5
    assert command(c,h,uid,'resume')['paused'] is False
    env[2][0] += 11
    assert tv.get('/api/media-tv/playback').json['position'] == 0
    assert ended()['position'] == 1
    assert ended()['position'] == 2
    # New service object reads committed state through new SQLite connections.
    replacement = playback.MediaPlayback(env[1], clock=lambda:env[2][0])
    with env[0].test_request_context(headers={'Cookie':'household_tv='+tv.get_cookie('household_tv').value}):
        assert replacement.television()['position'] == 2
    result = command(c,h,uid,'dashboard')
    assert result['mode'] == 'dashboard'
    assert tv.get('/api/media-tv/playback').json['item'] is None
    with env[1].transaction() as con:
        assert tuple(con.execute('SELECT display_layout,revision FROM devices WHERE id=?',(uid,)).fetchone()) == layout


def test_other_member_can_control_but_control_never_grants(env):
    c,h,uid,tv,_,items = granted(env,1)
    other,oh = login(env[0],2)
    assert command(other,oh,uid,'start')['photoCount'] == 1
    with env[1].transaction() as con:
        before = [tuple(r) for r in con.execute('SELECT * FROM media_tv_grants')]
    command(other,oh,uid,'pause')
    assert other.put('/api/media/items/'+items[0]['id']+'/tv-grants',headers=oh,json={
        'revision':items[0]['revision'],'deviceIds':[]}).status_code == 403
    with env[1].transaction() as con:
        assert [tuple(r) for r in con.execute('SELECT * FROM media_tv_grants')] == before


@pytest.mark.parametrize('changes',[
    {}, {'action':'start'}, {'revision':0}, {'revision':True,'action':'start'},
    {'revision':0.0,'action':'start'}, {'revision':-1,'action':'start'},
    {'revision':9007199254740991,'action':'start'}, {'revision':'0','action':'start'},
    {'revision':0,'action':[]}, {'revision':0,'action':'grant'},
    {'revision':0,'action':'start','deviceIds':[]}, {'revision':0,'action':'start','owner':'member2'},
    {'revision':0,'action':'start','intervalSeconds':5}, {'revision':0,'action':'interval'},
    *[{'revision':0,'action':'interval','intervalSeconds':v} for v in (True,4,121,5.0,'5',None)],
])
def test_strict_mutation_fields(env,changes):
    uid,_,_ = device(env)
    c,h = login(env[0])
    assert c.put(path(uid),json=changes,headers=h).status_code == 400
    assert c.get(path(uid)).json['revision'] == 0


@pytest.mark.parametrize('raw',['null','[]','{"revision":0,"revision":1,"action":"start"}',
    '{"revision":NaN,"action":"start"}','{"revision":1e999,"action":"start"}','x'*17000])
def test_raw_json_rejected(env,raw):
    uid,_,_ = device(env)
    c,h = login(env[0])
    assert c.put(path(uid),data=raw,content_type='application/json',headers=h).status_code == 400


def test_auth_csrf_member_tv_mix_and_query_rejection(env):
    c,h,uid,tv,_,_ = granted(env,1)
    anon = env[0].test_client()
    assert anon.get(path(uid)).status_code == 401
    assert anon.get('/api/media-tv/playback').status_code == 401
    assert c.get('/api/media-tv/playback').status_code == 401
    assert c.put(path(uid),json={'revision':0,'action':'start'}).status_code == 403
    assert c.put(path(uid),json={'revision':0,'action':'start'},headers=h|{'Origin':'https://evil.invalid'}).status_code == 403
    assert tv.get(path(uid)).status_code == 403
    assert tv.put(path(uid),json={'revision':0,'action':'start'}).status_code == 403
    assert c.get(path(uid)+'?deviceId='+uid).status_code == 400
    assert tv.get('/api/media-tv/playback?deviceId='+uid).status_code == 400
    assert c.get(path('bad')).status_code == 400
    assert c.get(path('a'*24)).status_code == 404
    # A member cookie cannot select a different device on this TV-only API.
    mixed = clone(env[0],c)
    mixed.set_cookie('household_tv',tv.get_cookie('household_tv').value)
    assert mixed.get('/api/media-tv/playback').json['deviceId'] == uid


@pytest.mark.parametrize('revoke',['grant','private','delete','account','scope','reauth','device_expired','device_deleted'])
def test_revoke_is_checked_again_on_every_tv_read(env,revoke):
    c,h,uid,tv,_,items = granted(env,1)
    item = items[0]
    command(c,h,uid,'start')
    old = tv.get('/api/media-tv/playback').json
    assert old['item'] is not None
    with env[1].transaction(True) as con:
        if revoke == 'grant':
            con.execute('DELETE FROM media_tv_grants WHERE device_id=?',(uid,))
        elif revoke == 'private':
            con.execute("UPDATE media_items SET visibility='private',revision=revision+1 WHERE id=?",(item['id'],))
        elif revoke == 'delete':
            con.execute("UPDATE media_items SET state='deleted',metadata_cipher=NULL,preview_cipher=NULL,preview_key=NULL WHERE id=?",(item['id'],))
        elif revoke == 'account':
            con.execute('DELETE FROM cloud_accounts WHERE id=?',(env[3][1],))
        elif revoke == 'scope':
            con.execute('UPDATE cloud_accounts SET tokens=? WHERE id=?',(env[1].accounts.encrypt({'scope':'openid'}),env[3][1]))
        elif revoke == 'reauth':
            con.execute('UPDATE cloud_accounts SET needs_reauth=1 WHERE id=?',(env[3][1],))
        elif revoke == 'device_expired':
            con.execute('UPDATE devices SET expires=0 WHERE id=?',(uid,))
        else:
            con.execute('DELETE FROM devices WHERE id=?',(uid,))
    result = tv.get('/api/media-tv/playback')
    assert result.status_code == (401 if revoke.startswith('device_') else 200)
    if result.status_code == 200:
        assert result.json['item'] is None and result.json['photoCount'] == 0
    assert tv.get(old['item']['previewUrl']).status_code >= 400
    if revoke == 'device_deleted':
        with env[1].transaction() as con:
            assert con.execute('SELECT count(*) FROM media_playback').fetchone()[0] == 0


def test_lease_bounded_by_device_expiry_and_server_clock(env):
    uid,tv,_ = device(env)
    result = tv.get('/api/media-tv/playback').json
    duration = lambda d:(datetime.fromisoformat(d['validUntil'])-datetime.fromisoformat(d['serverTime'])).total_seconds()
    assert duration(result) == 15
    with env[1].transaction(True) as con:
        con.execute('UPDATE devices SET expires=? WHERE id=?',(env[2][0]+3,uid))
    assert duration(tv.get('/api/media-tv/playback').json) == 3


def test_two_households_and_two_devices_are_independent(env,tmp_path,monkeypatch):
    c,h,uid,tv,secret,_ = granted(env,1)
    second,tv2,_ = device(env)
    command(c,h,uid,'start')
    assert tv2.get('/api/media-tv/playback').json['mode'] == 'dashboard'
    assert c.get(path(second)).json['photoCount'] == 0
    other,_ = setup(tmp_path/'other',monkeypatch,'b'*24)
    oc,oh,oid,otv,_,_ = granted(other,1)
    assert oc.get(path(uid)).status_code == 404
    assert oc.put(path(uid),json={'revision':1,'action':'dashboard'},headers=oh).status_code == 404
    assert c.get(path(oid)).status_code == 404
    forged = other[0].test_client()
    forged.set_cookie('household_tv',secret)
    assert forged.get('/api/media-tv/playback').status_code == 401
    assert otv.get('/api/media-tv/playback').json['mode'] == 'dashboard'


def test_parallel_controls_have_one_cas_winner_and_no_duplicate_effect(env):
    c,h,uid,tv,_,_ = granted(env,3)
    command(c,h,uid,'start')
    clients = [clone(env[0],c),clone(env[0],c)]
    gate = threading.Barrier(2)
    def write(client):
        gate.wait()
        return client.put(path(uid),json={'revision':1,'action':'next'},headers=h).status_code
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(write,clients)) == [200,409]
    assert tv.get('/api/media-tv/playback').json['position'] == 1
    assert c.get(path(uid)).json['revision'] == 2


def test_member_revalidated_inside_write_transaction(env,monkeypatch):
    c,h,uid,_,_,_ = granted(env,1)
    engine = env[1]
    original = engine._member
    def revoked(con):
        # Simulate a revocation after request actor resolution but before mutation.
        con.execute('UPDATE member_sessions SET revoked_at=1')
        return original(con)
    monkeypatch.setattr(engine,'_member',revoked)
    assert c.put(path(uid),json={'revision':0,'action':'start'},headers=h).status_code == 401
    with engine.transaction() as con:
        assert con.execute('SELECT count(*) FROM media_playback').fetchone()[0] == 0


def test_audit_failure_rolls_back_state(env,monkeypatch):
    c,h,uid,_,_,_ = granted(env,1)
    def failed(*_args):
        raise RuntimeError('synthetic audit failure')
    monkeypatch.setattr(env[1],'_audit',failed)
    with pytest.raises(RuntimeError,match='synthetic audit failure'):
        command(c,h,uid,'start')
    assert c.get(path(uid)).json['revision'] == 0


def test_factory_schema_registration_and_reject_partial(tmp_path,monkeypatch):
    env = configured(tmp_path,monkeypatch)
    assert 'media_playback' in env[0].extensions
    with env[1].sessions.db() as con:
        assert con.execute("SELECT name FROM sqlite_master WHERE name='media_playback'").fetchone() is not None
        playback.initialize_media_playback(con)
        con.execute('DROP TABLE media_playback')  # Only this disposable fixture.
        con.execute('CREATE TABLE media_playback(device_id TEXT)')
    with env[1].sessions.db() as con, pytest.raises(RuntimeError,match='schema mismatch'):
        playback.initialize_media_playback(con)


@pytest.mark.parametrize('assignment',["mode='video'",'paused=2','interval_seconds=4','interval_seconds=5.2',
    'cursor=-1','revision=0','anchor_at=-1','updated_at=-1',"device_id='missing'"])
def test_database_constraints(env,assignment):
    uid,_,_ = device(env)
    c,h = login(env[0])
    command(c,h,uid,'interval',intervalSeconds=10)
    with pytest.raises(sqlite3.IntegrityError), env[1].transaction(True) as con:
        con.execute('UPDATE media_playback SET '+assignment)
