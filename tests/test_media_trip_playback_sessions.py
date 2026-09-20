"""Real signed-session fences and TV/source rechecks; no forged g.actor."""
from contextlib import closing
import secrets
import sqlite3
from types import SimpleNamespace

import pytest

from test_device_sessions import invalidate
from test_household_media import offline
from test_media_playback import env, path
from test_media_trip_playback import seeded, preview, start, snapshot


@pytest.mark.parametrize('operation',['preview','receipt','control'])
@pytest.mark.parametrize('kind',['session','expired','auth_version'])
def test_member_read_discards_response_when_actual_session_changes(env,monkeypatch,operation,kind):
    c,h,uid,_,_,trip,_,_=seeded(env)
    _,payload=start(c,h,uid,preview(c,h,uid,trip['id']))
    before=snapshot(env);engine=env[0].extensions['media_playback'].trip
    original=engine.projection;observed=[]
    def revoke(*args,**kwargs):
        value=original(*args,**kwargs)
        if not observed:
            with closing(sqlite3.connect(env[1].sessions.path)) as con:
                invalidate(con,kind);con.commit()
            observed.append(True)
        return value
    monkeypatch.setattr(engine,'projection',revoke)
    if operation=='preview':
        response=c.post(path(uid)+'/journey-preview',headers=h,json=dict(revision=1,journeyId=trip['id'],routeId=None))
    else:
        response=c.get(path(uid) if operation=='control' else '/api/media-playback/operations/'+payload['requestId'])
    assert observed==[True] and response.status_code==401 and set(response.json)=={'error'}
    assert snapshot(env)==before


def test_start_session_expires_after_audit_rolls_back_all_writes(env,monkeypatch):
    import member_sessions
    c,h,uid,_,_,trip,_,_=seeded(env)
    value=preview(c,h,uid,trip['id']);before=snapshot(env)
    with env[1].transaction() as con:
        expiry=con.execute('SELECT max(expires_at) FROM member_sessions').fetchone()[0]
    original=env[1]._audit;seen=[]
    def expire(con,*args):
        original(con,*args);seen.append(True)
        monkeypatch.setattr(member_sessions,'time',SimpleNamespace(time=lambda:expiry+1))
    monkeypatch.setattr(env[1],'_audit',expire)
    response=c.post(path(uid)+'/journey-start',headers=h,json=dict(requestId=secrets.token_hex(16),
        previewToken=value['previewToken'],confirmStart=True))
    assert seen==[True] and response.status_code==401 and snapshot(env)==before


@pytest.mark.parametrize('change',['route','device'])
def test_tv_rechecks_fresh_snapshot_before_releasing_projection(env,monkeypatch,change):
    c,h,uid,tv,_,trip,detail,_=seeded(env)
    start(c,h,uid,preview(c,h,uid,trip['id'],detail['route']['id']))
    engine=env[0].extensions['media_playback'].trip;original=engine.projection;seen=[]
    def revoke(*args,**kwargs):
        result=original(*args,**kwargs)
        if not seen:
            with closing(sqlite3.connect(env[1].sessions.path)) as con:
                if change=='route':con.execute("UPDATE journey_routes SET visibility='private' WHERE id=?",(detail['route']['id'],))
                else:con.execute('UPDATE devices SET approved=0 WHERE id=?',(uid,))
                con.commit()
            seen.append(True)
        return result
    monkeypatch.setattr(engine,'projection',revoke)
    response=tv.get('/api/media-tv/playback')
    assert seen==[True] and response.status_code==(503 if change=='route' else 401)
    assert set(response.json)=={'error','code'}
    assert response.json['code']==('unavailable' if change=='route' else 'unauthorized')
