"""Real FFmpeg + Flask/SQLite/cipher, synthetic Google transport only."""
from copy import deepcopy
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import subprocess
from zipfile import ZipFile

import pytest

import household_media as media
import media_crypto
from media_import_worker import MediaImportWorker
from google_photos_picker import GooglePhotosPicker
from media_videos import VideoTools, sanitize_media_video
from media_video_storage import initialize_media_video_storage
from test_household_media import configured, create, confirm, device, share, selected, session, preview, offline
from test_journey_documents import login, clone
from test_google_photos_picker import Response, Transport, item, session as remote_session


@pytest.fixture(scope='module')
def tools():
    paths=[os.environ.get('MEDIA_TEST_'+n.upper()) or shutil.which(n) for n in ('ffmpeg','ffprobe')]
    assert all(paths), 'Real reviewed FFmpeg tools are required; do not skip.'
    return VideoTools(*paths)


@pytest.fixture(scope='module')
def clip(tmp_path_factory,tools):
    path=tmp_path_factory.mktemp('video-integration')/'synthetic.mp4'
    result=subprocess.run([tools.ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-y',
        '-f','lavfi','-i','testsrc2=size=160x90:rate=15:duration=1.4',
        '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=1.4',
        '-c:v','libx264','-threads:v','2','-pix_fmt','yuv420p','-c:a','aac',
        '-metadata','comment=SYNTHETIC-PRIVATE-VIDEO',str(path)],capture_output=True,timeout=60)
    assert result.returncode==0,result.stderr[-1000:]
    return path.read_bytes()


@pytest.fixture(scope='module')
def processed(clip,tools,tmp_path_factory):
    return sanitize_media_video(clip,'video/mp4',tools=tools,temp_root=tmp_path_factory.mktemp('video-normalize'))


@pytest.fixture
def env(tmp_path,monkeypatch):
    return configured(tmp_path/'household',monkeypatch)


def imported(env,clip,tools,*,owner=1,on_read=None,confirm_now=True):
    c,h,imp,_=create(env,owner)
    record=item('video-'+secrets.token_hex(4),'VIDEO')
    transport=Transport(remote_session(),remote_session(),{'mediaItems':[record]},
                        remote_session(),{'mediaItems':[record]},
                        Response(clip,mime='video/mp4',on_read=on_read),Response(b'',status=204))
    factory=lambda token:GooglePhotosPicker(token,transport=transport)
    worker=MediaImportWorker(env[1],picker_factory=factory,video_tools=tools,jitter=lambda:0)
    assert worker.tick() and worker.tick() and worker.tick()
    detail=c.get('/api/media/imports/'+imp['id']).json
    if confirm_now:
        assert detail['import']['state']=='awaiting_confirmation',detail
        assert len(detail['items'])==1
        before=detail['items'][0]['item']
        receipt,payload=confirm(c,h,detail)
        current=c.get('/api/media/items/'+before['id']).json['item']
        assert current['id']==before['id'] and current['revision']==before['revision']+1
        assert worker.tick()  # Real Picker cleanup boundary, only transport mocked.
        return c,h,current,receipt,payload,transport
    return c,h,imp,detail,worker,transport


def cache(env,uid):
    with env[1].transaction() as con:
        row=con.execute('SELECT * FROM media_video_cache WHERE media_id=?',(uid,)).fetchone()
        return dict(row) if row else None


def test_worker_video_confirm_original_receipt_private_encryption_and_restart(env,clip,tools):
    c,h,value,receipt,payload,transport=imported(env,clip,tools)
    uid=value['id']; url='/api/media/items/'+uid
    assert value['mediaType']=='video' and value['contentType']=='video/mp4'
    assert type(value['durationMs']) is int and 1300<=value['durationMs']<=1650 and value['hasAudio'] is True
    assert value['visibility']=='private' and value['videoUrl']==url+'/video' and value['previewUrl']==url+'/preview'
    assert sum(x['method']=='POST' for x in transport.calls)==1
    assert sum(x['method']=='DELETE' for x in transport.calls)==1
    assert [x for x in transport.calls if x['url'].endswith('=dv')]
    reply=c.get(value['videoUrl']); poster=c.get(value['previewUrl'])
    assert reply.status_code==200 and reply.content_type=='video/mp4'
    assert 'no-store' in reply.headers['Cache-Control'] and reply.headers['X-Content-Type-Options']=='nosniff'
    assert poster.status_code==200 and poster.content_type=='image/jpeg' and poster.data.startswith(b'\xff\xd8')
    row=cache(env,uid)
    assert row and clip not in row['cipher'] and reply.data not in row['cipher']
    assert b'SYNTHETIC-PRIVATE-VIDEO' not in reply.data
    assert media.MediaLibrary(env[0]).cipher.open_bytes('media-video',row['cipher'])==reply.data
    with pytest.raises(media_crypto.MediaCryptoError):env[1].cipher.open_bytes('media-preview',row['cipher'])
    other=media_crypto.MediaCipher(env[0].secret_key,'different-household')
    with pytest.raises(media_crypto.MediaCryptoError):other.open_bytes('media-video',row['cipher'])
    returned_video=reply.data
    reply.close()
    replay=c.post('/api/media/imports/'+receipt['import']['id']+'/confirm',json=payload,headers=h)
    assert replay.json['replayed'] and replay.json['itemIds']==[uid]
    with env[1].transaction() as con:
        assert con.execute('SELECT count(*) FROM media_items').fetchone()[0]==1
        assert con.execute('SELECT count(*) FROM media_video_cache').fetchone()[0]==1
        assert con.execute('SELECT reserved_bytes FROM media_imports').fetchone()[0]==0
    restarted=__import__('app').create_app(dict(env[0].config))
    recopy=clone(restarted,c)
    with recopy.get(value['videoUrl']) as restarted_reply:
        assert restarted_reply.data==returned_video


def test_video_sharing_tv_each_grant_and_unsharing_immediately_refuses(env,clip,tools):
    c,h,value,*_=imported(env,clip,tools)
    other,_=login(env[0],2); did,tv,_=device(env); did2,tv2,_=device(env)
    assert other.get(value['videoUrl']).status_code==404
    tvurl='/api/media-tv/items/'+value['id']+'/video'
    assert tv.get(tvurl).status_code==404
    value=share(c,h,value)
    with other.get(value['videoUrl']) as reply:
        assert reply.status_code==200 and tv.get(tvurl).status_code==404
    grant=c.put('/api/media/items/'+value['id']+'/tv-grants',json={'revision':value['revision'],
        'deviceIds':[did],'consentVersion':'media-v1','allowTvDisplay':True},headers=h)
    assert grant.status_code==200
    with tv.get(tvurl) as reply:
        assert reply.status_code==200 and tv2.get(tvurl).status_code==404
    listed=tv.get('/api/media-tv/items').json['items'][0]
    assert listed['mediaType']=='video' and listed['videoUrl']==tvurl
    assert all(k not in listed for k in ('accountId','displayFilename','sourceCreatedAt','owner','sourceKey'))
    changed=c.patch('/api/media/items/'+value['id'],json={'revision':grant.json['revision'],'visibility':'private'},headers=h)
    assert changed.status_code==200
    assert other.get(value['videoUrl']).status_code==404 and tv.get(tvurl).status_code==404
    with c.get(value['videoUrl']) as reply:
        assert reply.status_code==200 and cache(env,value['id']) is not None


@pytest.mark.parametrize('revoke',['share','device','delete','member'])
def test_video_rechecks_after_decryption_no_stale_bytes(env,clip,tools,monkeypatch,revoke):
    c,h,value,*_=imported(env,clip,tools,owner=2)
    value=share(c,h,value); reader,_=login(env[0],1)
    did,tv,_=device(env)
    grant=c.put('/api/media/items/'+value['id']+'/tv-grants',json={'revision':value['revision'],
        'deviceIds':[did],'consentVersion':'media-v1','allowTvDisplay':True},headers=h)
    assert grant.status_code==200
    latest=c.get('/api/media/items/'+value['id']).json['item']
    real=media_crypto.MediaCipher.open_bytes; observed=[]
    def decrypt(cipher,purpose,blob):
        raw=real(cipher,purpose,blob)
        if purpose=='media-video' and not observed:
            observed.append(True)
            if revoke=='share':
                assert c.patch('/api/media/items/'+value['id'],json={'revision':latest['revision'],'visibility':'private'},headers=h).status_code==200
            elif revoke=='delete':
                assert c.delete('/api/media/items/'+value['id'],json={'revision':latest['revision']},headers=h).status_code==200
            elif revoke=='device':
                manager,mh=login(env[0]);assert manager.delete('/api/devices/'+did,json={},headers=mh).status_code==200
            else:
                from household_memberships import remove_membership
                with env[1].sessions.db() as con:
                    con.execute('BEGIN IMMEDIATE')
                    remove_membership(con,household_id='default',actor_member_id='member1',member_id='member2',
                        expected_auth_version=1,expected_revision=1,request_id=secrets.token_hex(16),intent_digest='a'*64)
        return raw
    monkeypatch.setattr(media_crypto.MediaCipher,'open_bytes',decrypt)
    response=(tv.get('/api/media-tv/items/'+value['id']+'/video') if revoke=='device' else reader.get(value['videoUrl']))
    assert observed and response.status_code in (401,403,404,409,410) and response.content_type!='video/mp4'
    if revoke=='member':
        assert c.get(value['videoUrl']).status_code==401
        assert cache(env,value['id']) is not None  # Existing removed-member policy retains private owned data.


@pytest.mark.parametrize('end',['cancel','expired','account_hook','account_sql','delete'])
def test_all_existing_tombstone_paths_clear_video_cache_atomically(env,clip,tools,end):
    c,h,imp,detail,worker,_=imported(env,clip,tools,confirm_now=False)
    assert detail['import']['state']=='awaiting_confirmation'; uid=detail['items'][0]['id']
    assert cache(env,uid)
    if end=='cancel':
        assert c.delete('/api/media/imports/'+imp['id'],json={'revision':detail['import']['revision']},headers=h).status_code==200
    elif end=='expired':
        env[2][0]+=86401;env[1].maintenance()
    else:
        confirm(c,h,detail);value=c.get('/api/media/items/'+uid).json['item']
        if end=='delete':assert c.delete('/api/media/items/'+uid,json={'revision':value['revision']},headers=h).status_code==200
        else:
            with env[1].transaction(True) as con:
                if end=='account_hook':env[1].on_account_removed(con,env[3][1])
                else:con.execute('DELETE FROM cloud_accounts WHERE id=?',(env[3][1],))
    assert cache(env,uid) is None
    with env[1].transaction() as con:
        row=con.execute('SELECT state,metadata_cipher,preview_cipher FROM media_items WHERE id=?',(uid,)).fetchone()
        assert tuple(row)==('deleted',None,None)


def test_mixed_import_confirm_only_photo_discards_unselected_real_video(env,clip,tools):
    c,h,imp,_=create(env)
    records=[item('mixed-video','VIDEO'),item('mixed-photo')]
    photo=preview().data
    transport=Transport(remote_session(),remote_session(),{'mediaItems':records},
        remote_session(),{'mediaItems':records},Response(clip,mime='video/mp4'),
        remote_session(),{'mediaItems':records},Response(photo,mime='image/jpeg'),Response(b'',status=204))
    worker=MediaImportWorker(env[1],picker_factory=lambda token:GooglePhotosPicker(token,transport=transport),video_tools=tools)
    for _ in range(4):assert worker.tick()
    detail=c.get('/api/media/imports/'+imp['id']).json
    assert detail['import']['counts']['ready']==2 and detail['import']['canConfirm']
    video=next(x['item'] for x in detail['items'] if x['item']['mediaType']=='video')
    still=next(x['item'] for x in detail['items'] if x['item']['mediaType']=='photo')
    assert cache(env,video['id'])
    payload={'revision':detail['import']['revision'],'confirmRequestId':secrets.token_hex(16),'itemIds':[still['id']],
             'consentVersion':'media-v1','persistSelected':True}
    result=c.post('/api/media/imports/'+imp['id']+'/confirm',json=payload,headers=h)
    assert result.status_code==200 and result.json['itemIds']==[still['id']]
    assert result.json['import']['counts']['unselected']==1 and cache(env,video['id']) is None
    assert c.get(still['previewUrl']).status_code==200


def test_video_reservation_rejects_before_download_and_actual_cipher_is_counted(env,clip,tools,monkeypatch):
    monkeypatch.setattr(media,'OWNER_BYTES',media.VIDEO_RESERVATION-1)
    c,h,imp,_=create(env)
    r=item('big-video','VIDEO');t=Transport(remote_session(),remote_session(),{'mediaItems':[r]})
    w=MediaImportWorker(env[1],picker_factory=lambda token:GooglePhotosPicker(token,transport=t),video_tools=tools)
    assert w.tick() and w.tick()
    result=c.get('/api/media/imports/'+imp['id']).json['import']
    assert result['state']=='failed' and result['error']['code']=='quota'
    assert not any(x['url'].endswith('=dv') for x in t.calls)
    monkeypatch.setattr(media,'OWNER_BYTES',100*1024*1024)
    # Finish old remote cleanup without introducing unrelated downloads.
    assert env[1].complete(env[1].claim_next(),None)
    c,h,value,*_=imported(env,clip,tools)
    with env[1].transaction() as con:
        plain=con.execute('SELECT sum(coalesce(length(metadata_cipher),0)+coalesce(length(preview_cipher),0)) FROM media_items').fetchone()[0]
        imports=con.execute('SELECT sum(coalesce(length(context_cipher),0)+coalesce(length(session_cipher),0)+coalesce(length(manifest_cipher),0)+reserved_bytes) FROM media_imports').fetchone()[0]
        video_bytes=con.execute('SELECT length(cipher) FROM media_video_cache').fetchone()[0]
        monkeypatch.setattr(media,'OWNER_BYTES',plain+imports+video_bytes-1)
        with pytest.raises(media.MediaError) as error:env[1]._quota(con,'member1')
        assert error.value.code=='quota'


@pytest.mark.parametrize('expiry',[False,True])
def test_video_lease_allows_900_seconds_but_never_expired_source(env,processed,expiry):
    c,h,imp,_=create(env);engine=env[1]
    engine.complete(engine.claim_next(),session(env));records=[selected('clock-video','VIDEO')]
    engine.complete(engine.claim_next(),records);job=engine.claim_next()
    with engine.transaction() as con:
        assert con.execute('SELECT lease_until FROM media_imports WHERE id=?',(imp['id'],)).fetchone()[0]-env[2][0]==1200
    env[2][0]+=901
    if expiry:
        with engine.transaction(True) as con:con.execute('UPDATE media_imports SET expires_at=? WHERE id=?',(env[2][0]-1,imp['id']))
    assert engine.complete(job,dict(mediaId='clock-video',manifest=records,preview=processed.poster,video=processed)) is not expiry
    with engine.transaction() as con:assert con.execute('SELECT count(*) FROM media_video_cache').fetchone()[0]==(0 if expiry else 1)


def test_video_source_revocation_during_download_discards_result(env,clip,tools):
    done=[]
    def revoke():
        if not done:
            done.append(True)
            with env[1].transaction(True) as con:env[1].on_account_removed(con,env[3][1])
    _,_,_,_,_,transport=imported(env,clip,tools,on_read=revoke,confirm_now=False)
    assert done and any(x['url'].endswith('=dv') for x in transport.calls)
    with env[1].transaction() as con:
        assert con.execute('SELECT count(*) FROM media_items').fetchone()[0]==0
        assert con.execute('SELECT count(*) FROM media_video_cache').fetchone()[0]==0


def test_video_metadata_export_has_no_bytes_urls_or_capabilities(env,clip,tools):
    c,h,value,*_=imported(env,clip,tools)
    response=c.post('/api/portability/export',json={},headers=h)
    assert response.status_code==200
    with ZipFile(BytesIO(response.data)) as archive:
        assert not any(n.endswith(('.mp4','.jpg')) for n in archive.namelist())
        data=json.loads(archive.read('data.json'))
    exported=data['personal']['householdMedia'][0]
    assert exported['mediaType']=='video' and exported['durationMs']==value['durationMs'] and exported['hasAudio']
    assert all(k not in json.dumps(exported) for k in ('videoUrl','previewUrl','cipher','cache_key','sourceKey','deviceIds'))


def test_additive_71_to_72_preserves_all_old_objects_rows_and_restarts(tmp_path,monkeypatch):
    with monkeypatch.context() as before:
        before.setattr(media,'initialize_media_video_storage',lambda con:None)
        env=configured(tmp_path/'migration',before)
    database=Path(env[0].config['DATA_DIR'])/'household.sqlite3'
    with sqlite3.connect(database) as con:
        con.execute('PRAGMA foreign_keys=ON')
        tables=[r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        assert len(tables)==71
        objects=list(con.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"))
        rows={t:list(con.execute('SELECT * FROM "'+t+'"')) for t in tables}
        initialize_media_video_storage(con)
        assert len(list(con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")))==72
        assert all(row in list(con.execute("SELECT type,name,tbl_name,sql FROM sqlite_master")) for row in objects)
        assert rows=={t:list(con.execute('SELECT * FROM "'+t+'"')) for t in tables}
        assert con.execute('SELECT count(*) FROM media_video_cache').fetchone()[0]==0
        initialize_media_video_storage(con)
        assert con.execute('PRAGMA quick_check').fetchone()[0]=='ok'
        con.execute('BEGIN IMMEDIATE')
        with pytest.raises(RuntimeError):initialize_media_video_storage(con)
        assert con.in_transaction
        con.rollback()


@pytest.mark.parametrize('status',['PROCESSING','FAILED','UNSPECIFIED','READY'])
def test_video_processing_status_is_per_item_and_ready_transition_preserves_photo(env,clip,tools,status):
    c,h,imp,_=create(env)
    before=[item('keep-photo'),item('pending-video','VIDEO','PROCESSING')]
    after=[item('keep-photo'),item('pending-video','VIDEO',status)]
    photo=preview().data
    responses=[remote_session(),remote_session(),{'mediaItems':before},
        remote_session(),{'mediaItems':before},Response(photo,mime='image/jpeg'),
        remote_session(),{'mediaItems':after}]
    if status=='READY':responses.append(Response(clip,mime='video/mp4'))
    transport=Transport(*responses)
    worker=MediaImportWorker(env[1],picker_factory=lambda token:GooglePhotosPicker(token,transport=transport),video_tools=tools)
    for _ in range(3):assert worker.tick()
    prior=c.get('/api/media/imports/'+imp['id']).json
    saved=prior['items'][0]['item'];assert saved['mediaType']=='photo'
    saved_bytes=c.get(saved['previewUrl']).data
    assert worker.tick()
    detail=c.get('/api/media/imports/'+imp['id']).json
    assert detail['import']['state']=='awaiting_confirmation' and detail['import']['canConfirm']
    assert detail['import']['counts']['ready']==(2 if status=='READY' else 1)
    assert detail['import']['counts']['failed']==(0 if status=='READY' else 1)
    assert c.get(saved['previewUrl']).data==saved_bytes
    if status!='READY':
        result=next(r for r in detail['import']['results'] if r['status']=='failed')
        assert result['error']['code']=='video_not_ready'
        assert not any(call['url'].endswith('=dv') for call in transport.calls)
    receipt,payload=confirm(c,h,detail)
    assert saved['id'] in receipt['itemIds']
    replay=c.post('/api/media/imports/'+imp['id']+'/confirm',headers=h,json=payload)
    assert replay.json['replayed'] and replay.json['itemIds']==receipt['itemIds']


@pytest.mark.parametrize('change',['filename','width','session'])
def test_video_processing_fix_does_not_allow_real_selection_or_session_changes(env,tools,change):
    c,h,imp,_=create(env);before=[item('strict-video','VIDEO','PROCESSING')]
    after=[item('strict-video','VIDEO','READY')]
    if change=='filename':after[0]['mediaFile']['filename']='different.mp4'
    if change=='width':after[0]['mediaFile']['mediaFileMetadata']['width']+=1
    transport=Transport(remote_session(),remote_session(),{'mediaItems':before},
                        remote_session(ready=change!='session'),{'mediaItems':after})
    worker=MediaImportWorker(env[1],picker_factory=lambda token:GooglePhotosPicker(token,transport=transport),video_tools=tools)
    for _ in range(3):assert worker.tick()
    detail=c.get('/api/media/imports/'+imp['id']).json
    assert detail['import']['state']=='failed'
    assert detail['import']['error']['code']==('not_ready' if change=='session' else 'selection_changed')
    assert not any(call['url'].endswith('=dv') for call in transport.calls)
