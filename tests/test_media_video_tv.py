"""Synthetic local Flask/SQLite and real video processor; no real Google or TV."""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import sqlite3
import threading

import pytest

import media_playback
import media_playback_progress as progress
from test_media_playback import env, granted, command, path, setup
from test_media_video_integration import clip, tools, imported
from test_journey_documents import login, clone
from test_household_media import offline


def snapshot(tv):
    response=tv.get('/api/media-tv/playback',headers={'X-Display-Mode':'tv'})
    assert response.status_code==200,response.json
    return response.json


def report(tv,state,event='ready',position=None,**patch):
    p=state['progress'];item=state['item']
    payload=dict(revision=state['revision'],playId=p['playId'],itemId=item['id'],itemRevision=item['revision'],
                 sequence=p['sequence']+1,positionMs=p['positionMs'] if position is None else position,event=event)
    payload.update(patch)
    return tv.post('/api/media-tv/playback/progress',json=payload,headers={
        'X-Display-Mode':'tv','Origin':'http://localhost','X-TV-Playback-CSRF':state['playbackCsrf']})


def test_actual_photo_time_pause_restart_and_ended_only_once(env):
    c,h,uid,tv,_,_=granted(env,2);command(c,h,uid,'start')
    first=snapshot(tv);assert first['progress']['positionMs']==0
    env[2][0]+=70  # Download/not-ready time is not displayed time.
    unchanged=snapshot(tv);assert unchanged['item']['id']==first['item']['id']
    assert report(tv,unchanged).status_code==200
    state=snapshot(tv);assert report(tv,state,'checkpoint',4100).status_code==200
    command(c,h,uid,'pause');state=snapshot(tv)
    assert state['progress']['positionMs']==4100 and state['paused']
    assert report(tv,state,'paused',4300).status_code==200
    env[2][0]+=99
    replacement=media_playback.MediaPlayback(env[1],clock=lambda:env[2][0])
    with env[0].test_request_context(headers={'Cookie':'household_tv='+tv.get_cookie('household_tv').value}):
        assert replacement.television()['progress']['positionMs']==4300
    command(c,h,uid,'resume');state=snapshot(tv)
    assert report(tv,state,'ended',9999).status_code==409
    accepted=report(tv,state,'ended',10000);assert accepted.status_code==200
    assert accepted.json['item']['id']!=state['item']['id']
    assert accepted.json['progress']['positionMs']==0
    assert report(tv,state,'ended',10000).status_code==409
    assert snapshot(tv)['item']['id']==accepted.json['item']['id']


def test_real_video_mixed_playlist_ignores_photo_interval_and_handles_pause_next(env,clip,tools):
    c,h,uid,tv,_,_=granted(env,1)
    owner,oh,video,*_=imported(env,clip,tools)
    video=owner.patch('/api/media/items/'+video['id'],json={'revision':video['revision'],'visibility':'shared'},headers=oh).json['item']
    assert owner.put('/api/media/items/'+video['id']+'/tv-grants',json={'revision':video['revision'],
        'deviceIds':[uid],'consentVersion':'media-v1','allowTvDisplay':True},headers=oh).status_code==200
    command(c,h,uid,'start');state=snapshot(tv)
    if state['item']['mediaType']!='video':command(c,h,uid,'next');state=snapshot(tv)
    assert state['item']['id']==video['id'] and state['progress']['durationMs']==video['durationMs']
    env[2][0]+=150;assert snapshot(tv)['item']['id']==video['id']
    state=snapshot(tv);assert report(tv,state).status_code==200
    state=snapshot(tv);assert report(tv,state,'checkpoint',500).status_code==200
    command(c,h,uid,'interval',intervalSeconds=5);state=snapshot(tv)
    assert state['progress']['durationMs']==video['durationMs'] and state['progress']['positionMs']==500
    command(c,h,uid,'pause');state=snapshot(tv)
    assert report(tv,state,'ended',state['progress']['durationMs']).status_code==409
    assert report(tv,state,'paused',700).status_code==200
    command(c,h,uid,'resume');state=snapshot(tv)
    assert state['progress']['positionMs']==700
    assert report(tv,state,'ended',state['progress']['durationMs']).status_code==200
    assert snapshot(tv)['item']['mediaType']=='photo'
    command(c,h,uid,'previous');assert snapshot(tv)['progress']['positionMs']==0
    response=tv.get('/api/media-tv/items/'+video['id']+'/video')
    assert response.status_code==200 and response.content_type=='video/mp4'


def test_narrow_tv_post_requires_real_cookie_origin_header_and_bound_csrf(env):
    c,h,uid,tv,_,_=granted(env,1);command(c,h,uid,'start');state=snapshot(tv)
    body=dict(revision=state['revision'],playId=state['progress']['playId'],itemId=state['item']['id'],
        itemRevision=state['item']['revision'],sequence=1,positionMs=0,event='ready')
    headers={'Origin':'http://localhost','X-Display-Mode':'tv','X-TV-Playback-CSRF':state['playbackCsrf']}
    url='/api/media-tv/playback/progress'
    for patch in ({'Origin':None},{'Origin':'null'},{'Origin':'https://elsewhere.test'},
                  {'X-Display-Mode':None},{'X-TV-Playback-CSRF':None},{'X-TV-Playback-CSRF':state['playbackCsrf'][:-1]+'x'}):
        attempt={**headers,**patch};attempt={k:v for k,v in attempt.items() if v is not None}
        assert tv.post(url,json=body,headers=attempt).status_code==403
    assert c.post(url,json=body,headers=headers).status_code==401
    assert tv.put(url,json=body,headers=headers).status_code==403
    assert tv.post('/api/items/tasks',json={},headers=headers).status_code==403
    assert tv.post(url,data='{}',headers=headers).status_code==415
    mixed=clone(env[0],c);mixed.set_cookie('household_tv',tv.get_cookie('household_tv').value)
    assert mixed.post(url,json=body,headers={k:v for k,v in headers.items() if k!='X-Display-Mode'}).status_code==403
    assert mixed.post(url,json=body,headers=headers).status_code==200
    env[2][0]+=16
    assert report(tv,state).status_code==403
    assert snapshot(tv)['progress']['sequence']==1


def test_two_device_household_replay_and_current_grant_revocation(env,tmp_path,monkeypatch):
    c,h,uid,tv,_,_=granted(env,1);command(c,h,uid,'start');state=snapshot(tv)
    _,_,other_id,other_tv,_,_=granted(env,1)
    command(c,h,other_id,'start')
    assert report(other_tv,state).status_code==403
    other,_=setup(tmp_path/'other',monkeypatch,'b'*24)
    _,_,_,foreign_tv,_,_=granted(other,1)
    assert report(foreign_tv,state).status_code==403
    item=c.get('/api/media/items/'+state['item']['id']).json['item']
    assert c.put('/api/media/items/'+item['id']+'/tv-grants',json={'revision':item['revision'],'deviceIds':[]},headers=h).status_code==200
    assert report(tv,state,'ended',10000).status_code==409
    assert snapshot(tv)['item'] is None
    assert tv.get(state['item']['previewUrl']).status_code==404
    assert c.delete('/api/devices/'+uid,json={},headers=h).status_code==200
    assert report(tv,state).status_code==401
    with env[1].transaction() as con:
        assert con.execute('SELECT count(*) FROM media_playback_progress WHERE device_id=?',(uid,)).fetchone()[0]==0


def test_report_duplicate_sequence_and_concurrent_phone_next_have_one_winner(env):
    c,h,uid,tv,_,_=granted(env,2);command(c,h,uid,'start');state=snapshot(tv)
    assert report(tv,state).status_code==200
    assert report(tv,state).status_code==409
    state=snapshot(tv);barrier=threading.Barrier(2)
    def send(kind):
        barrier.wait()
        if kind=='tv':
            copied=env[0].test_client();copied.set_cookie('household_tv',tv.get_cookie('household_tv').value)
            return report(copied,state,'ended',10000).status_code
        return clone(env[0],c).put(path(uid),headers=h,json={'revision':state['revision'],'action':'next'}).status_code
    with ThreadPoolExecutor(2) as pool:assert sorted(pool.map(send,['tv','phone']))==[200,409]
    final=snapshot(tv);assert final['revision']==state['revision']+1 and final['position']==1
    assert final['progress']['playId']!=state['progress']['playId']


def test_ready_checkpoint_validation_and_atomic_failure(env,monkeypatch):
    c,h,uid,tv,_,_=granted(env,1);command(c,h,uid,'start');state=snapshot(tv)
    for patch in ({'positionMs':True},{'sequence':0},{'positionMs':600251},{'event':'grant'},{'itemId':'f'*24},
                  {'deviceId':uid},{'revision':state['revision']+1},{'playId':'f'*24}):
        assert report(tv,state,**patch).status_code in (400,409)
    with env[1].transaction(True) as con:
        con.execute("CREATE TRIGGER reject_playhead BEFORE INSERT ON media_playback_progress BEGIN SELECT RAISE(ABORT,'synthetic'); END")
    before=snapshot(tv)
    with pytest.raises(sqlite3.IntegrityError):report(tv,before,'ended',10000)
    assert snapshot(tv)==before


def test_additive_progress_preserves_old_eight_column_schema_and_complete_group(tmp_path,monkeypatch):
    with monkeypatch.context() as before:
        before.setattr(progress,'initialize_progress',lambda con:None)
        legacy,_=setup(tmp_path/'old',before)
        c,h,uid,tv,_,_=granted(legacy,1)
        # Parent persisted row without executing a new progress writer.
        with legacy[1].transaction(True) as con:
            con.execute('INSERT INTO media_playback VALUES(?,?,?,?,?,?,?,?)',(uid,'photos',1,10,0,1,3,1))
    with legacy[1].sessions.db() as con:
        names=[r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        assert len(names)==72
        old={n:[tuple(r) for r in con.execute('SELECT * FROM "'+n+'"')] for n in names}
        ddl=con.execute("SELECT sql FROM sqlite_master WHERE name='media_playback'").fetchone()[0]
        progress.initialize_progress(con)
        assert con.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone()[0]==73
        assert con.execute("SELECT sql FROM sqlite_master WHERE name='media_playback'").fetchone()[0]==ddl
        assert old=={n:[tuple(r) for r in con.execute('SELECT * FROM "'+n+'"')] for n in names}
        progress.initialize_progress(con)
    state=snapshot(tv);assert state['paused'] and state['progress']['positionMs']==0
    assert report(tv,state,'ready').status_code==200
    backup=tmp_path/'backup.sqlite3'
    with legacy[1].sessions.db() as con,sqlite3.connect(backup) as destination:con.backup(destination)
    with sqlite3.connect(backup) as con:
        con.execute('PRAGMA foreign_keys=ON');progress.initialize_progress(con)
        assert con.execute('PRAGMA quick_check').fetchone()[0]=='ok'
        assert con.execute('SELECT count(*) FROM media_playback_progress').fetchone()[0]==1


def test_csp_only_adds_local_blob_media_attachment_sandbox_stays(env):
    response=env[0].test_client().get('/healthz')
    policy=response.headers['Content-Security-Policy']
    assert "media-src 'self' blob:" in policy and "script-src 'self';" in policy
    assert "script-src 'self' 'unsafe-inline'" not in policy
