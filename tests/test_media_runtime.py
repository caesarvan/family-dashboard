"""Real app factories, OAuth/member/pairing flows and SQLite; no live accounts."""
from io import BytesIO
from pathlib import Path
import secrets
import socket
import tarfile
import time

from flask import g, request
from PIL import Image
import pytest

from app import create_app
from cloud_providers import ProviderError
from deploy.prepare_release import FILES, prepare
from media_import_worker import MediaScheduler
from test_cloud_accounts import configured, login, begin, finish, select
from test_google_photos_oauth import bind_photos, expire, response_tokens, identity, SYNC, COMBINED, PICKER
from test_media_import_worker import worker, session, item, Response


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*_args,**_kwargs):
        raise AssertionError('No external network in runtime tests')
    monkeypatch.setattr(socket.socket,'connect',denied)
    monkeypatch.setattr(socket,'create_connection',denied)


def ready(app,client,headers,account_id):
    response=client.post('/api/media/imports',json={'requestId':secrets.token_hex(16),'accountId':account_id,
        'consentVersion':'media-v1','allowTemporaryProcessing':True},headers=headers)
    assert response.status_code==202,response.json
    uid=response.json['import']['id']
    out=BytesIO()
    Image.new('RGB',(12,8),'#567890').save(out,format='PNG')
    run,transport,_=worker(app.extensions['household_media'],session(),session(),{'mediaItems':[item()]},
        session(),{'mediaItems':[item()]},Response(out.getvalue(),mime='image/png'),Response(b'',status=204))
    for _ in range(4):
        assert run.tick()
    detail=client.get('/api/media/imports/'+uid).json
    response=client.post('/api/media/imports/'+uid+'/confirm',json={'revision':detail['import']['revision'],
        'confirmRequestId':secrets.token_hex(16),'itemIds':[c['id'] for c in detail['items']],
        'consentVersion':'media-v1','persistSelected':True},headers=headers)
    assert response.status_code==200,response.json
    photo=client.get('/api/media/items/'+response.json['itemIds'][0]).json['item']
    return photo


def paired(app,client,headers):
    tv=app.test_client()
    value=tv.post('/api/pair/start',json={}).json
    assert client.post('/api/pair/approve',json={'code':value['code'],'name':'Synthetic TV'},headers=headers).status_code==200
    assert tv.post('/api/pair/poll',json={'secret':value['secret']}).json['approved']
    devices=client.get('/api/devices').json
    return tv,devices[-1]['id'],value['secret']


def share_and_grant(app,client,headers,photo):
    path='/api/media/items/'+photo['id']
    photo=client.patch(path,json={'revision':photo['revision'],'visibility':'shared'},headers=headers).json['item']
    tv,device_id,cookie=paired(app,client,headers)
    grant=client.put(path+'/tv-grants',json={'revision':photo['revision'],'deviceIds':[device_id],
        'consentVersion':'media-v1','allowTvDisplay':True},headers=headers)
    assert grant.status_code==200,grant.json
    return tv,device_id,cookie


def test_factory_registers_exact_four_media_tables_and_real_vertical(configured):
    app,remote,_=configured
    client,headers,aid=bind_photos(app,remote)
    assert {'household_media','current_tv_device'} <= app.extensions.keys()
    photo=ready(app,client,headers,aid)
    assert client.get(photo['previewUrl']).status_code==200
    with app.extensions['member_sessions'].db() as con:
        tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        assert len(tables)==53
        assert {name for name in tables if name.startswith('media_')}=={'media_imports','media_items','media_tv_grants','media_playback'}


def test_real_household_invite_child_four_members_and_namespace_isolation(configured):
    app,remote,_=configured
    first,headers,aid=bind_photos(app,remote)
    photo=ready(app,first,headers,aid)
    invite=first.post('/api/spaces/invitations',json={},headers=headers).json['invitation']
    response=app.test_client().post('/api/spaces/redeem',json={'invitation':invite,'name':'合成第二家庭',
        'slug':'media-second','MEMBER1_PASSWORD':'testing-password-one','MEMBER2_PASSWORD':'testing-password-two'})
    assert response.status_code==201,response.json
    platform=app.extensions['household_platform']
    household=next(h for h in platform.households() if h['slug']=='media-second')
    child=platform.child(household)
    assert child.config['GOOGLE_CLIENT_ID']==app.config['GOOGLE_CLIENT_ID']
    assert child.config['GOOGLE_CLIENT_SECRET']==app.config['GOOGLE_CLIENT_SECRET']
    assert child.secret_key!=app.secret_key
    child.config['CLOUD_PROVIDER_FACTORY']=remote.factory
    child.config['OAUTH_TRANSPORT']=remote.tokens
    second,sh,sid=bind_photos(child,remote,subject='child-photo-subject')
    other_photo=ready(child,second,sh,sid)
    assert second.get('/api/media/items/'+photo['id']).status_code==404
    assert first.get('/api/media/items/'+other_photo['id']).status_code==404
    for application in (app,child):
        member2,_=login(application,2)
        assert member2.get('/api/media/items?scope=visible').json['total']==0
    with child.extensions['member_sessions'].db() as con:
        assert con.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone()[0]==53
    seen=[]
    class OnlyRecord:
        def __init__(self,engine): self.engine=engine
        def tick(self): seen.append(self.engine.household); return False
    scheduler=MediaScheduler(platform,worker_factory=OnlyRecord)
    scheduler.tick(); scheduler.tick()
    assert set(seen)=={'default',household['id']}


def test_restart_keeps_ciphertext_media_and_device_grants(configured):
    app,remote,cfg=configured
    c,h,aid=bind_photos(app,remote)
    photo=ready(app,c,h,aid)
    _,_,cookie=share_and_grant(app,c,h,photo)
    restarted=create_app(cfg)
    tv=restarted.test_client()
    tv.set_cookie('household_tv',cookie)
    assert tv.get('/api/media-tv/items').json['items'][0]['id']==photo['id']
    assert tv.get('/api/media-tv/items/'+photo['id']+'/preview').status_code==200
    owner,_=login(restarted)
    assert owner.get('/api/media/items').json['total']==1


def test_account_disconnect_is_one_transaction_and_removes_only_its_media(configured,monkeypatch):
    app,remote,_=configured
    c,h,aid=bind_photos(app,remote)
    photo=ready(app,c,h,aid)
    media=app.extensions['household_media']
    original=media.on_account_removed
    observed=[]
    def hook(con,account_id):
        observed.append(con.in_transaction and con.execute('SELECT 1 FROM cloud_accounts WHERE id=?',(account_id,)).fetchone() is not None)
        original(con,account_id)
    monkeypatch.setattr(media,'on_account_removed',hook)
    assert c.delete('/api/accounts/'+aid,json={},headers=h).status_code==200
    assert observed==[True]
    assert c.get(photo['previewUrl']).status_code==410
    assert c.get('/api/accounts').json['accounts']==[]


def test_account_disconnect_rolls_back_both_account_and_media_on_failure(configured,monkeypatch):
    app,remote,_=configured
    c,h,aid=bind_photos(app,remote)
    photo=ready(app,c,h,aid)
    media=app.extensions['household_media']
    original=media.on_account_removed
    def fail(con,account_id):
        original(con,account_id)
        raise RuntimeError('synthetic transaction failure')
    monkeypatch.setattr(media,'on_account_removed',fail)
    with pytest.raises(RuntimeError,match='synthetic transaction'):
        c.delete('/api/accounts/'+aid,json={},headers=h)
    assert len(c.get('/api/accounts').json['accounts'])==1
    assert c.get(photo['previewUrl']).status_code==200


def test_disconnect_after_session_revoked_waiting_for_lock_is_rejected(configured,monkeypatch):
    app,remote,_=configured
    c,h,aid=bind_photos(app,remote)
    accounts=app.extensions['cloud_accounts']
    original=accounts.disconnect
    def revoked(account_id,owner,auth_context=None):
        with app.extensions['member_sessions'].db() as con:
            con.execute('BEGIN IMMEDIATE')
            app.extensions['member_sessions'].revoke_browser(con,auth_context['browserHash'],time.time())
        return original(account_id,owner,auth_context)
    monkeypatch.setattr(accounts,'disconnect',revoked)
    assert c.delete('/api/accounts/'+aid,json={},headers=h).status_code==409
    assert accounts.account(aid)['owner']=='member1'


@pytest.mark.parametrize('refresh_path',['photos','sync'])
def test_explicit_picker_scope_loss_clears_media_in_refresh_transaction(configured,refresh_path):
    app,remote,_=configured
    c,h,aid=bind_photos(app,remote,scope=COMBINED)
    photo=ready(app,c,h,aid)
    tv,_,_=share_and_grant(app,c,h,photo)
    accounts=app.extensions['cloud_accounts']
    expire(accounts,aid)
    response_tokens(app,remote,SYNC)
    if refresh_path=='photos':
        with pytest.raises(ProviderError) as error:
            accounts.photos_access_token(aid,'member1')
        assert error.value.status==403
    else:
        accounts.active_provider(accounts.account(aid))
    assert c.get(photo['previewUrl']).status_code==410
    assert tv.get('/api/media-tv/items').json['items']==[]
    assert c.get('/api/accounts').json['accounts'][0]['capabilities']=={'photos':False,'sync':True}


@pytest.mark.parametrize('refresh_path',['photos','sync'])
def test_normal_refresh_omitted_scope_does_not_revoke_saved_media(configured,refresh_path):
    app,remote,_=configured
    c,h,aid=bind_photos(app,remote,scope=COMBINED)
    photo=ready(app,c,h,aid)
    tv,_,_=share_and_grant(app,c,h,photo)
    path='/api/media/items/'+photo['id']
    revision=c.get(path).json['item']['revision']
    accounts=app.extensions['cloud_accounts']
    expire(accounts,aid)
    response_tokens(app,remote,None)
    if refresh_path=='photos': accounts.photos_access_token(aid,'member1')
    else: accounts.active_provider(accounts.account(aid))
    assert c.get(path).json['item']['revision']==revision
    assert tv.get('/api/media-tv/items/'+photo['id']+'/preview').status_code==200


def test_oauth_new_sync_grant_without_picker_clears_copies_but_keeps_sync(configured):
    app,remote,_=configured
    c,h,aid=bind_photos(app,remote,scope=COMBINED)
    photo=ready(app,c,h,aid)
    select(c,h,aid,tasks=True,calendar=True)
    accounts=app.extensions['cloud_accounts']
    with accounts.db() as con:
        sources=[r[0] for r in con.execute('SELECT id FROM cloud_sources ORDER BY id')]
    response_tokens(app,remote,SYNC)
    code=identity(remote,code='new-sync-grant',subject='google-subject')
    state=begin(c,h,'google')['state'][0]
    assert finish(c,state,'google',code).location.endswith('auth=connected')
    assert c.get(photo['previewUrl']).status_code==410
    with accounts.db() as con:
        assert [r[0] for r in con.execute('SELECT id FROM cloud_sources ORDER BY id')]==sources
    assert c.get('/api/accounts/'+aid+'/sources').status_code==200


def test_reauth_retains_private_copy_and_never_restores_old_grants(configured):
    app,remote,_=configured
    c,h,aid=bind_photos(app,remote)
    photo=ready(app,c,h,aid)
    tv,_,_=share_and_grant(app,c,h,photo)
    accounts=app.extensions['cloud_accounts']
    accounts.failure(aid,ProviderError('synthetic invalid grant',401,reauth=True))
    assert c.get(photo['previewUrl']).status_code==200
    assert c.get('/api/media/items/'+photo['id']).json['item']['visibility']=='private'
    assert tv.get('/api/media-tv/items').json['items']==[]
    with accounts.db() as con:
        assert con.execute('SELECT needs_reauth FROM cloud_accounts WHERE id=?',(aid,)).fetchone()[0]==1


def test_transient_failure_keeps_shared_and_grants(configured):
    app,remote,_=configured
    c,h,aid=bind_photos(app,remote)
    photo=ready(app,c,h,aid)
    tv,_,_=share_and_grant(app,c,h,photo)
    app.extensions['cloud_accounts'].failure(aid,ProviderError('synthetic temporary',502))
    assert tv.get('/api/media-tv/items/'+photo['id']+'/preview').status_code==200


def test_identity_transition_hook_and_account_update_commit_together(configured):
    app,remote,_=configured
    c,h,aid=bind_photos(app,remote)
    photo=ready(app,c,h,aid)
    accounts=app.extensions['cloud_accounts']
    with accounts.db() as con:
        con.execute('BEGIN IMMEDIATE')
        before=con.execute('SELECT * FROM cloud_accounts WHERE id=?',(aid,)).fetchone()
        identity=dict(before)|{'subject':'different-synthetic-subject'}
        accounts.media_account_transition(con,before,identity=identity)
        con.execute('UPDATE cloud_accounts SET subject=? WHERE id=?',(identity['subject'],aid))
    assert c.get(photo['previewUrl']).status_code==410


def test_sync_refresh_cannot_replace_a_concurrently_changed_grant(configured):
    app,remote,_=configured
    _,_,aid=bind_photos(app,remote,scope=COMBINED)
    accounts=app.extensions['cloud_accounts']
    expire(accounts,aid)
    before=accounts.account(aid)
    def raced(provider,params):
        with accounts.db() as con:
            con.execute('UPDATE cloud_accounts SET subject=? WHERE id=?',('changed-during-refresh',aid))
        return remote.tokens(provider,params)
    app.config['OAUTH_TRANSPORT']=raced
    with pytest.raises(ProviderError) as error:
        accounts.active_provider(before)
    assert error.value.status==409
    assert accounts.account(aid)['tokens']==before['tokens']


def test_fresh_tv_resolver_rejects_rotated_secret_after_request_guard(configured):
    app,_,_=configured
    @app.before_request
    def rotate():
        if request.path=='/api/state' and request.headers.get('X-Synthetic-Rotate'):
            with app.extensions['member_sessions'].db() as con:
                con.execute('UPDATE devices SET secret_hash=? WHERE id=?',('0'*64,g.actor['id']))
    c,h=login(app)
    tv,uid,_=paired(app,c,h)
    assert tv.get('/api/state').status_code==200
    assert tv.get('/api/state',headers={'X-Synthetic-Rotate':'1'}).status_code==401


def test_factory_routes_keep_member_tv_csrf_and_photo_only_capability(configured):
    app,remote,_=configured
    c,h,aid=bind_photos(app,remote)
    assert c.get('/api/accounts').json['accounts'][0]['capabilities']=={'photos':True,'sync':False}
    assert c.get('/api/accounts/'+aid+'/sources').status_code==403
    assert c.post('/api/media/imports',json={}).status_code==403
    tv,_,_=paired(app,c,h)
    assert tv.get('/api/media/items').status_code==403
    assert c.get('/api/media-tv/items').status_code==401
    assert app.test_client().get('/api/media/items').status_code==401


def test_runtime_packaging_uses_same_image_volume_and_allowlist(tmp_path):
    root=Path(__file__).resolve().parents[1]
    required={'google_photos_picker.py','media_crypto.py','media_images.py','household_media.py','media_import_worker.py','media_playback.py'}
    assert required<=set(FILES)
    docker=(root/'Dockerfile').read_text()
    for name in required: assert name in docker
    compose=(root/'compose.yaml').read_text()
    section=compose.split('  media:\n',1)[1].split('  web:',1)[0]
    assert 'image: family-dashboard-app' in section
    assert 'command: [python, -B, media_import_worker.py]' in section
    assert 'env_file: .env' in section and 'household-data:/data' in section
    assert 'read_only: true' in section and 'no-new-privileges:true' in section
    result=prepare(root,access=tmp_path/'release')
    with tarfile.open(result['archive']) as archive:
        assert required<=set(archive.getnames())
        assert not any(name.startswith('test-results/') for name in archive.getnames())
