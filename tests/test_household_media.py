"""Real SQLite/member cookies/Fernet/Pillow; synthetic accounts, no provider I/O."""
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import hashlib
import secrets
import socket
import time

from flask import g
from PIL import Image
import pytest

from app import create_app, Problem
from cloud_accounts import GOOGLE_PHOTOS_SCOPE
import household_media as media
from media_images import sanitize_media_preview
from test_journey_documents import PASSWORD, clone, connection, create_journey, login


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*args,**kwargs):
        raise AssertionError('No external network in media library tests')
    monkeypatch.setattr(socket.socket,'connect',denied)
    monkeypatch.setattr(socket,'create_connection',denied)


def configured(tmp_path, monkeypatch, household='default'):
    monkeypatch.setenv('MEMBER1_PASSWORD',PASSWORD)
    monkeypatch.setenv('MEMBER2_PASSWORD',PASSWORD)
    app=create_app({'TESTING':True,'DATA_DIR':str(tmp_path),'SECRET_KEY':'media-library-synthetic-secret',
        'HOUSEHOLD_INFO':{'id':household},'SESSION_COOKIE_SECURE':False,'PUBLIC_ORIGIN':'http://localhost',
        'GOOGLE_CLIENT_ID':'synthetic-client','GOOGLE_CLIENT_SECRET':'synthetic-secret',
        'MICROSOFT_CLIENT_ID':'','MICROSOFT_CLIENT_SECRET':'','OPENAI_API_KEY':'','OPENAI_MODEL':'',
        'NVIDIA_API_KEY':'','NVIDIA_MODEL':''})
    def db():
        if 'media_test_db' not in g:
            g.media_test_db=connection(app)
        return g.media_test_db
    @app.teardown_appcontext
    def close(_error):
        con=g.pop('media_test_db',None)
        if con:
            con.close()
    def require():
        if g.actor['role']!='member':
            raise Problem('只限成员',403)
    engine=app.extensions.get('household_media') or media.register_media_library(app,db,Problem,None,require,None)
    clock=[time.time()]
    engine.clock=lambda:clock[0]
    ids={}
    with engine.accounts.db() as con:
        for number in (1,2):
            aid=secrets.token_hex(16)
            ids[number]=aid
            tokens=engine.accounts.encrypt({'access_token':'synthetic-media-token','scope':GOOGLE_PHOTOS_SCOPE,'expires_at':time.time()+3600})
            con.execute('INSERT INTO cloud_accounts(id,owner,provider,client_id,subject,name,email,tokens) VALUES(?,?,?,?,?,?,?,?)',
                        (aid,f'member{number}','google','synthetic-client',f'synthetic-subject-{number}','合成本人','test.invalid',tokens))
    return app,engine,clock,ids


@pytest.fixture
def env(tmp_path,monkeypatch):
    return configured(tmp_path/'one',monkeypatch)


def create(env,number=1,**changes):
    app,engine,clock,ids=env
    client,headers=login(app,number)
    value={'requestId':secrets.token_hex(16),'accountId':ids[number],
           'consentVersion':'media-v1','allowTemporaryProcessing':True,**changes}
    response=client.post('/api/media/imports',json=value,headers=headers)
    assert response.status_code==202,response.json
    return client,headers,response.json['import'],value


def session(env,ready=True):
    now=env[2][0]
    value={'id':'synthetic-session','expireTime':datetime.fromtimestamp(now+3600,timezone.utc).isoformat(),
           'mediaItemsSet':ready,'pickerUri':'https://photos.google.com/picker/synthetic'}
    if not ready:
        value['pollingConfig']={'pollInterval':'1s','timeoutIn':'600s'}
    return value


def selected(uid='synthetic-photo',kind='PHOTO'):
    return {'id':uid,'createTime':'2026-09-01T00:00:00Z','type':kind,
            'mediaFile':{'mimeType':'image/jpeg' if kind=='PHOTO' else 'video/mp4','filename':'private-synthetic-filename.jpg',
                         'mediaFileMetadata':{'width':20,'height':12}}}


def preview():
    output=BytesIO()
    Image.new('RGB',(20,12),'#496654').save(output,'PNG')
    return sanitize_media_preview(output.getvalue(),'image/png')


def stage(env,number=1,items=None):
    client,headers,item,value=create(env,number)
    engine=env[1]
    job=engine.claim_next()
    assert job['action']=='create'
    assert engine.complete(job,session(env))
    job=engine.claim_next()
    assert job['action']=='list'
    items=items or [selected()]
    assert engine.complete(job,items)
    while (job:=engine.claim_next()) is not None:
        if job['action']=='cleanup':
            assert engine.complete(job,None)
            break
        assert job['action']=='download'
        assert engine.complete(job,{'mediaId':job['media']['id'],'manifest':items,'preview':preview()})
    detail=client.get('/api/media/imports/'+item['id']).json
    return client,headers,detail,value


def confirm(client,headers,detail):
    value={'revision':detail['import']['revision'],'confirmRequestId':secrets.token_hex(16),
           'itemIds':[i['id'] for i in detail['items']],'consentVersion':'media-v1','persistSelected':True}
    response=client.post('/api/media/imports/'+detail['import']['id']+'/confirm',json=value,headers=headers)
    assert response.status_code==200,response.json
    return response.json,value


def saved(env,number=1):
    c,h,detail,_=stage(env,number)
    confirm(c,h,detail)
    item=c.get('/api/media/items/'+detail['items'][0]['id']).json['item']
    return c,h,item


def device(env):
    tv=env[0].test_client()
    pairing=tv.post('/api/pair/start',json={}).json
    owner,headers=login(env[0])
    assert owner.post('/api/pair/approve',json={'code':pairing['code'],'name':'合成电视'},headers=headers).status_code==200
    assert tv.post('/api/pair/poll',json={'secret':pairing['secret']}).json['approved']
    cookie=pairing['secret']
    with env[1].transaction() as con:
        uid=con.execute('SELECT id FROM devices WHERE secret_hash=?',(hashlib.sha256(cookie.encode()).hexdigest(),)).fetchone()[0]
    return uid,tv,cookie


def share(c,h,item):
    response=c.patch('/api/media/items/'+item['id'],json={'revision':item['revision'],'visibility':'shared'},headers=h)
    assert response.status_code==200,response.json
    return response.json['item']


def test_end_to_end_private_confirmation_encrypted_storage_and_restart(env):
    c,h,detail,_=stage(env)
    assert detail['import']['canConfirm'] and detail['items'][0]['status']=='successful'
    uid=detail['items'][0]['id']
    assert c.get('/api/media/items').json['total']==0
    other,_=login(env[0],2)
    assert other.get('/api/media/items/'+uid).status_code==404
    raw=c.get('/api/media/items/'+uid+'/preview')
    assert raw.status_code==200 and raw.content_type=='image/jpeg'
    first,receipt=confirm(c,h,detail)
    replay=c.post('/api/media/imports/'+detail['import']['id']+'/confirm',json=receipt,headers=h)
    assert replay.status_code==200 and replay.json['replayed']
    assert first['itemIds']==[uid]
    item=c.get('/api/media/items/'+uid).json['item']
    assert item['visibility']=='private' and item['canManage'] and item['journey'] is None
    assert c.get('/api/media/items').json['total']==1
    with env[1].transaction() as con:
        row=con.execute('SELECT * FROM media_items WHERE id=?',(uid,)).fetchone()
        assert b'private-synthetic' not in row['metadata_cipher']
        assert b'synthetic-photo' not in row['metadata_cipher']
        assert not row['preview_cipher'].startswith(b'\xff\xd8')
        assert con.execute('SELECT count(*) FROM media_tv_grants').fetchone()[0]==0
    replacement=media.MediaLibrary(env[0])
    with replacement.transaction() as con:
        assert replacement._metadata(con.execute('SELECT * FROM media_items WHERE id=?',(uid,)).fetchone())['displayFilename']=='private-synthetic-filename.jpg'


@pytest.mark.parametrize('changes',[
    {'allowTemporaryProcessing':False},{'consentVersion':'old'},{'owner':'member2'},
    {'requestId':'short'},{'accountId':'https://evil.invalid'},{'token':'synthetic-unwanted'},
    {'acknowledgePossibleExistingSession':{'unexpected':'x'*5000}},
])
def test_explicit_consent_and_strict_create(env,changes):
    c,h=login(env[0])
    value={'requestId':secrets.token_hex(16),'accountId':env[3][1],'consentVersion':'media-v1','allowTemporaryProcessing':True,**changes}
    assert c.post('/api/media/imports',json=value,headers=h).status_code==400


def test_request_replay_and_mismatched_intent(env):
    c,h,item,value=create(env)
    assert c.post('/api/media/imports',json=value,headers=h).json['replayed']
    changed=value|{'accountId':env[3][2]}
    assert c.post('/api/media/imports',json=changed,headers=h).status_code==409
    assert c.delete('/api/media/imports/'+item['id'],json={'revision':item['revision']},headers=h).status_code==200
    assert c.post('/api/media/imports',json=value,headers=h).json['import']['state']=='cancelled'
    assert env[1].claim_next() is None


def test_create_unknown_and_crashed_create_never_retry(env):
    c,h,item,value=create(env)
    job=env[1].claim_next()
    assert env[1].fail(job,'network',retryable=True,outcome_unknown=True)
    assert c.get('/api/media/imports/'+item['id']).json['import']['state']=='create_unknown'
    assert env[1].claim_next() is None
    assert c.post('/api/media/imports',json=value,headers=h).json['import']['state']=='create_unknown'
    c,h,item,_=create(env)
    env[1].claim_next()
    env[2][0]+=media.LEASE_SECONDS+1
    assert env[1].claim_next() is None
    assert c.get('/api/media/imports/'+item['id']).json['import']['state']=='create_unknown'


def test_create_arrives_after_cancel_only_cleanup_kept(env):
    c,h,item,_=create(env)
    job=env[1].claim_next()
    revision=c.get('/api/media/imports/'+item['id']).json['import']['revision']
    assert c.delete('/api/media/imports/'+item['id'],json={'revision':revision},headers=h).status_code==200
    assert not env[1].complete(job,session(env))
    detail=c.get('/api/media/imports/'+item['id']).json['import']
    assert detail['state']=='cancelled' and 'pickerUri' not in detail
    cleanup=env[1].claim_next()
    assert cleanup['action']=='cleanup'
    assert env[1].complete(cleanup,None)


def test_original_remote_deadline_and_local_24h_are_separate(env):
    c,h,item,_=create(env)
    assert env[1].complete(env[1].claim_next(),session(env,False))
    env[2][0]+=601
    job=env[1].claim_next()
    if job:
        assert not env[1].validate_job(job)
    assert c.get('/api/media/imports/'+item['id']).json['import']['state']=='expired'


def test_staged_expiry_clears_ciphertext_and_reservation(env):
    c,h,detail,_=stage(env)
    uid=detail['items'][0]['id']
    env[2][0]+=86401
    assert c.get('/api/media/items/'+uid+'/preview').status_code==410
    env[1].maintenance()
    with env[1].transaction() as con:
        row=con.execute('SELECT * FROM media_items WHERE id=?',(uid,)).fetchone()
        assert row['preview_cipher'] is None and row['metadata_cipher'] is None
        assert con.execute('SELECT sum(reserved_bytes) FROM media_imports').fetchone()[0]==0


def test_shared_readonly_and_tv_independent_grants(env):
    c,h,item=saved(env)
    other,oh=login(env[0],2)
    uid,tv,cookie=device(env)
    endpoint='/api/media/items/'+item['id']
    assert other.get(endpoint).status_code==404
    assert tv.get('/api/media-tv/items').json['items']==[]
    item=share(c,h,item)
    public=other.get(endpoint).json['item']
    assert not public['canManage'] and 'displayFilename' not in public and 'accountId' not in public
    assert other.patch(endpoint,json={'revision':item['revision'],'caption':'no'},headers=oh).status_code==403
    assert tv.get('/api/media-tv/items').json['items']==[]
    response=c.put(endpoint+'/tv-grants',json={'revision':item['revision'],'deviceIds':[uid],
                   'consentVersion':'media-v1','allowTvDisplay':True},headers=h)
    assert response.status_code==200,response.json
    assert tv.get('/api/media-tv/items').json['items'][0]['id']==item['id']
    assert tv.get('/api/media-tv/items/'+item['id']+'/preview').status_code==200
    # Even an authenticated owner cookie cannot substitute for a TV cookie.
    assert c.get('/api/media-tv/items').status_code==401
    c.set_cookie('household_tv',cookie)
    assert c.get('/api/media-tv/items/'+item['id']+'/preview').status_code==200
    with env[1].transaction(True) as con:
        con.execute('DELETE FROM devices WHERE id=?',(uid,))
    assert c.get('/api/media-tv/items/'+item['id']+'/preview').status_code==401
    assert tv.get('/api/media-tv/items').status_code==401


def test_private_change_revokes_tv_and_revision_conflicts(env):
    c,h,item=saved(env)
    uid,tv,_=device(env)
    endpoint='/api/media/items/'+item['id']
    item=share(c,h,item)
    grants=c.put(endpoint+'/tv-grants',json={'revision':item['revision'],'deviceIds':[uid],'consentVersion':'media-v1','allowTvDisplay':True},headers=h).json
    assert c.patch(endpoint,json={'revision':item['revision'],'visibility':'private'},headers=h).status_code==409
    assert c.patch(endpoint,json={'revision':grants['revision'],'visibility':'private'},headers=h).status_code==200
    assert tv.get('/api/media-tv/items').json['items']==[]
    assert c.get(endpoint+'/tv-grants').json['deviceIds']==[]


def test_deletion_is_idempotent_and_confirmation_does_not_resurrect(env):
    c,h,detail,_=stage(env)
    _,receipt=confirm(c,h,detail)
    uid=detail['items'][0]['id']
    endpoint='/api/media/items/'+uid
    item=c.get(endpoint).json['item']
    request={'revision':item['revision']}
    assert c.delete(endpoint,json=request,headers=h).json['deleted']
    assert c.delete(endpoint,json=request,headers=h).json['replayed']
    assert c.get(endpoint).status_code==410
    replay=c.post('/api/media/imports/'+detail['import']['id']+'/confirm',json=receipt,headers=h)
    assert replay.json['itemIds']==[] and replay.json['goneItemIds']==[uid]
    with env[1].transaction() as con:
        row=con.execute('SELECT preview_cipher,metadata_cipher FROM media_items WHERE id=?',(uid,)).fetchone()
        assert tuple(row)==(None,None)


def test_logout_during_download_fences_preview(env):
    c,h,item,_=create(env)
    engine=env[1]
    engine.complete(engine.claim_next(),session(env))
    engine.complete(engine.claim_next(),[selected()])
    job=engine.claim_next()
    assert c.post('/api/logout',json={},headers=h).status_code==200
    assert not engine.complete(job,{'mediaId':'synthetic-photo','manifest':[selected()],'preview':preview()})
    with engine.transaction() as con:
        assert con.execute('SELECT count(*) FROM media_items').fetchone()[0]==0
        assert con.execute('SELECT reserved_bytes FROM media_imports').fetchone()[0]==0


def test_source_delete_atomically_purges_and_preserves_receipt(env):
    c,h,item=saved(env)
    with env[1].transaction(True) as con:
        con.execute('DELETE FROM cloud_accounts WHERE id=?',(env[3][1],))
    assert c.get('/api/media/items/'+item['id']).status_code==410
    assert c.get('/api/media/items').json['total']==0
    with env[1].transaction() as con:
        assert con.execute('SELECT preview_cipher FROM media_items').fetchone()[0] is None
        assert con.execute('SELECT count(*) FROM media_imports').fetchone()[0]==1


def test_journey_unlink_keeps_owner_copy_and_removes_sharing(env):
    c,h,item=saved(env)
    journey=create_journey(c,h)
    endpoint='/api/media/items/'+item['id']
    response=c.patch(endpoint,json={'revision':item['revision'],'journeyId':journey['id'],'visibility':'shared'},headers=h)
    assert response.status_code==200,response.json
    revision=response.json['item']['revision']
    with env[1].transaction(True) as con:
        con.execute('DELETE FROM journey_workflows WHERE id=?',(journey['id'],))
    item=c.get(endpoint).json['item']
    assert item['journey'] is None and item['visibility']=='private' and item['revision']==revision+1
    assert c.get(endpoint+'/preview').status_code==200


def test_database_record_and_ciphertext_binding(env,monkeypatch):
    c,h,item=saved(env)
    with env[1].transaction(True) as con:
        con.execute('UPDATE media_items SET preview_key=? WHERE id=?',(secrets.token_hex(12),item['id']))
    assert c.get('/api/media/items/'+item['id']+'/preview').status_code==503


def test_preview_rechecks_revocation_after_decrypt(env,monkeypatch):
    c,h,item=saved(env)
    uid,tv,_=device(env)
    item=share(c,h,item)
    c.put('/api/media/items/'+item['id']+'/tv-grants',json={'revision':item['revision'],'deviceIds':[uid],
          'consentVersion':'media-v1','allowTvDisplay':True},headers=h)
    original=media.MediaCipher.open_bytes
    def revoked(cipher,*args):
        result=original(cipher,*args)
        with env[1].transaction(True) as con:
            con.execute('DELETE FROM devices WHERE id=?',(uid,))
        return result
    monkeypatch.setattr(media.MediaCipher,'open_bytes',revoked)
    assert tv.get('/api/media-tv/items/'+item['id']+'/preview').status_code==401


def test_owner_quota_reservations_cannot_overbook(env):
    c,h,item,_=create(env)
    value={'requestId':secrets.token_hex(16),'accountId':env[3][1],'consentVersion':'media-v1','allowTemporaryProcessing':True}
    assert c.post('/api/media/imports',json=value,headers=h).status_code==429
    with env[1].transaction() as con:
        assert con.execute('SELECT count(*) FROM media_imports').fetchone()[0]==1
    assert media.OWNER_BYTES==100*1024*1024 and media.HOUSEHOLD_BYTES==200*1024*1024


def test_duplicate_selection_reuses_private_copy_and_other_owner_does_not(env):
    c,h,item=saved(env)
    c,h,detail,_=stage(env)
    assert detail['items'][0]['status']=='duplicate' and detail['items'][0]['id']==item['id']
    confirm(c,h,detail)
    assert c.get('/api/media/items').json['total']==1
    other,oh,second=saved(env,2)
    assert second['id']!=item['id']
    assert other.get('/api/media/items').json['total']==1


def test_video_not_faked_as_photo_and_per_item_failure_preserves_photo(env):
    c,h,imp,_=create(env); engine=env[1]
    items=[selected(),selected('synthetic-video','VIDEO')]
    engine.complete(engine.claim_next(),session(env));engine.complete(engine.claim_next(),items)
    work=engine.claim_next();engine.complete(work,{'mediaId':work['media']['id'],'manifest':items,'preview':preview()})
    work=engine.claim_next()
    with pytest.raises(media.MediaError) as error:
        engine.complete(work,{'mediaId':work['media']['id'],'manifest':items,'preview':preview()})
    assert error.value.code=='video_invalid'
    assert engine.fail(work,'video_unsupported')
    detail=c.get('/api/media/imports/'+imp['id']).json
    assert len(detail['items'])==1
    assert detail['import']['counts']=={'selected':2,'ready':1,'skipped':0,'failed':1,'pending':0,'saved':0,'unselected':None}


def test_cross_household_isolation(env,tmp_path,monkeypatch):
    c,h,item=saved(env)
    second=configured(tmp_path/'other',monkeypatch,'a'*24)
    stranger,sh=login(second[0])
    assert stranger.get('/api/media/items/'+item['id']).status_code==404
    assert stranger.get('/api/media/items').json['total']==0
    c2,h2,item2=saved(second)
    assert env[1].cipher.source_key('member1','subject','photo')!=second[1].cipher.source_key('member1','subject','photo')


@pytest.mark.parametrize('query',['unknown=1','scope=mine&scope=visible','limit=0','offset=-1'])
def test_query_is_strict(env,query):
    c,_=login(env[0])
    assert c.get('/api/media/items?'+query).status_code==400


def test_json_duplicate_keys_and_nonfinite_rejected(env):
    c,h=login(env[0])
    for raw in ('{"requestId":"a","requestId":"b"}','{"bad":NaN}','{"bad":1e999}','[]'):
        assert c.post('/api/media/imports',data=raw,content_type='application/json',headers=h).status_code==400


def test_complete_rejects_changed_selection_and_stale_lease(env):
    c,h,item,_=create(env)
    engine=env[1]
    engine.complete(engine.claim_next(),session(env))
    engine.complete(engine.claim_next(),[selected()])
    job=engine.claim_next()
    with pytest.raises(media.MediaError,match='选择已变化'):
        engine.complete(job,{'mediaId':'synthetic-photo','manifest':[selected('different')],'preview':preview()})
    env[2][0]+=media.LEASE_SECONDS+1
    assert not engine.complete(job,{'mediaId':'synthetic-photo','manifest':[selected()],'preview':preview()})
    with engine.transaction() as con:
        assert con.execute('SELECT count(*) FROM media_items').fetchone()[0]==0


def test_cleanup_unknown_is_readback_only_then_terminal(env):
    c,h,item,_=create(env)
    engine=env[1]
    engine.complete(engine.claim_next(),session(env))
    engine.complete(engine.claim_next(),[selected('video','VIDEO')])
    assert engine.fail(engine.claim_next(),'video_unsupported')
    cleanup=engine.claim_next()
    assert cleanup['action']=='cleanup' and not cleanup['cleanupUnknown']
    assert engine.fail(cleanup,'network',outcome_unknown=True)
    readback=engine.claim_next()
    assert readback['action']=='cleanup' and readback['cleanupUnknown']
    assert engine.fail(readback,'cleanup_unknown',outcome_unknown=True)
    assert engine.claim_next() is None


def test_cleanup_crash_persists_readback_state(env):
    c,h,item,_=create(env)
    engine=env[1]
    engine.complete(engine.claim_next(),session(env))
    engine.complete(engine.claim_next(),[selected('video','VIDEO')])
    assert engine.fail(engine.claim_next(),'video_unsupported')
    first=engine.claim_next()
    assert first['action']=='cleanup' and not first['cleanupUnknown']
    env[2][0]+=media.LEASE_SECONDS+1
    recovered=engine.claim_next()
    assert recovered['action']=='cleanup' and recovered['cleanupUnknown']
    assert not engine.complete(first,None)
    assert engine.complete(recovered,None)


def test_create_response_after_expired_lease_retains_known_cleanup(env):
    c,h,item,_=create(env)
    job=env[1].claim_next()
    env[2][0]+=media.LEASE_SECONDS+1
    assert not env[1].complete(job,session(env))
    current=c.get('/api/media/imports/'+item['id']).json['import']
    assert current['state']=='create_unknown' and 'pickerUri' not in current
    assert env[1].claim_next()['action']=='cleanup'


def test_concurrent_create_same_request_uses_one_receipt(env):
    c,h=login(env[0])
    clients=[clone(env[0],c),clone(env[0],c)]
    value={'requestId':secrets.token_hex(16),'accountId':env[3][1],'consentVersion':'media-v1','allowTemporaryProcessing':True}
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies=list(pool.map(lambda client:client.post('/api/media/imports',json=value,headers=h),clients))
    assert sorted(r.status_code for r in replies)==[200,202]
    assert len({r.json['import']['id'] for r in replies})==1
    with env[1].transaction() as con:
        assert con.execute('SELECT count(*) FROM media_imports').fetchone()[0]==1


def test_household_quota_counts_other_owner_reservation(env,monkeypatch):
    monkeypatch.setattr(media,'HOUSEHOLD_BYTES',90*1024*1024)
    create(env)
    other,h=login(env[0],2)
    value={'requestId':secrets.token_hex(16),'accountId':env[3][2],'consentVersion':'media-v1','allowTemporaryProcessing':True}
    assert other.post('/api/media/imports',json=value,headers=h).status_code==429


def test_current_account_subject_change_discards_worker_output(env):
    c,h,item,_=create(env)
    engine=env[1]
    job=engine.claim_next()
    with engine.transaction(True) as con:
        con.execute('UPDATE cloud_accounts SET subject=? WHERE id=?',('different-trusted-subject',env[3][1]))
    assert not engine.complete(job,session(env))
    assert engine.claim_next() is None
    assert c.get('/api/media/imports/'+item['id']).json['import']['state']=='cancelled'


def test_account_reauth_hook_retains_owner_copy_but_removes_shared(env):
    c,h,item=saved(env)
    item=share(c,h,item)
    with env[1].transaction(True) as con:
        con.execute('UPDATE cloud_accounts SET needs_reauth=1 WHERE id=?',(env[3][1],))
        env[1].on_account_authority_changed(con,env[3][1],'reauth')
    other,_=login(env[0],2)
    endpoint='/api/media/items/'+item['id']
    assert other.get(endpoint).status_code==404
    assert c.get(endpoint+'/preview').status_code==200
    assert c.get(endpoint).json['item']['visibility']=='private'


def test_worker_reauth_marks_account_and_blocks_new_import(env):
    c,h,item,_=create(env)
    job=env[1].claim_next()
    assert env[1].fail(job,'reauth',reauth=True)
    with env[1].transaction() as con:
        assert con.execute('SELECT needs_reauth FROM cloud_accounts WHERE id=?',(env[3][1],)).fetchone()[0]==1
    value={'requestId':secrets.token_hex(16),'accountId':env[3][1],'consentVersion':'media-v1','allowTemporaryProcessing':True}
    assert c.post('/api/media/imports',json=value,headers=h).status_code==409


@pytest.mark.parametrize('code',['api_disabled','forbidden','reauth','invalid_token'])
def test_picker_error_preserves_only_disabled_service_existing_authority(env,code):
    c,h,item=saved(env);item=share(c,h,item)
    uid,tv,_=device(env)
    endpoint='/api/media/items/'+item['id']
    assert c.put(endpoint+'/tv-grants',json={'revision':item['revision'],'deviceIds':[uid],
        'consentVersion':'media-v1','allowTvDisplay':True},headers=h).status_code==200
    other,_=login(env[0],2)
    c,h,imported,request_value=create(env)
    job=env[1].claim_next();assert job['action']=='create'
    assert env[1].fail(job,code,reauth=code in ('reauth','invalid_token'))
    result=c.get('/api/media/imports/'+imported['id']).json['import']
    with env[1].transaction() as con:
        needs_reauth=con.execute('SELECT needs_reauth FROM cloud_accounts WHERE id=?',(env[3][1],)).fetchone()[0]
        grant_count=con.execute('SELECT count(*) FROM media_tv_grants WHERE media_id=?',(item['id'],)).fetchone()[0]
    if code=='api_disabled':
        assert result['state']=='failed' and result['error']['code']=='api_disabled'
        assert '无需重复授权' in result['error']['message']
        assert needs_reauth==0 and grant_count==1
        assert other.get(endpoint).status_code==200 and tv.get('/api/media-tv/items').json['items'][0]['id']==item['id']
        assert env[1].claim_next() is None  # no automatic second create
        replay=c.post('/api/media/imports',json=request_value,headers=h)
        assert replay.status_code==200 and replay.json['import']['state']=='failed'
        assert env[1].claim_next() is None
        fresh=dict(request_value,requestId=secrets.token_hex(16))
        assert c.post('/api/media/imports',json=fresh,headers=h).status_code==202
    else:
        assert result['state']=='cancelled' and result['error']['code']=='reauth'
        assert needs_reauth==int(code in ('reauth','invalid_token')) and grant_count==0
        assert other.get(endpoint).status_code==404 and tv.get('/api/media-tv/items').json['items']==[]
    assert c.get(endpoint+'/preview').status_code==200  # confirmed owner copy retained


def test_factory_media_tables_and_hooks_require_transaction(env):
    with env[1].sessions.db() as con:
        names={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'media_%'")}
        assert names=={'media_imports','media_items','media_tv_grants','media_playback','media_video_cache'}
        with pytest.raises(RuntimeError):
            env[1].on_account_removed(con,env[3][1])


def test_unlogged_tv_and_csrf_boundaries(env):
    anonymous=env[0].test_client()
    assert anonymous.get('/api/media/items').status_code==401
    uid,tv,_=device(env)
    assert tv.get('/api/media/items').status_code==403
    c,h=login(env[0])
    response=c.post('/api/media/imports',json={'requestId':secrets.token_hex(16),'accountId':env[3][1],
                       'consentVersion':'media-v1','allowTemporaryProcessing':True})
    assert response.status_code==403
