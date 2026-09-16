"""Actual factory/SQLite/cookies and ZIP fences; only synthetic inventory sources."""
import json
import secrets
import socket

import pytest

import data_portability as portability
from test_data_portability import unpack
from test_inventory_runtime import app
from test_inventory_api import create, acquisition, move, rid, P
from test_journey_documents import connection, login


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('No external requests in inventory export checks')
    monkeypatch.setattr(socket.socket,'connect',denied)
    monkeypatch.setattr(socket,'create_connection',denied)


def source(app, lot, owner, marker):
    # No source HTTP workflow is claimed: fill its approved schema with synthetic
    # owner data to prove export isolation, including fields that must stay private.
    uid = secrets.token_hex(12)
    with connection(app) as con:
        con.execute('INSERT INTO inventory_source_links VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            (uid,owner,lot['acquisition']['id'],marker+'_ORDER',marker+'_LINE','d'*64,1,
             marker+'_SETTLEMENT','active',1,'synthetic','synthetic'))
    return uid


@pytest.fixture
def stocked(app):
    own,h = login(app)
    peer,ph = login(app,2)
    private,_ = create(own,h,title='OWNER_PRIVATE')
    personal,_ = acquisition(own,h,private['item'])
    personal,_ = move(own,h,personal,quantity=2)
    mine_source = source(app,personal,'member1','OWNER_SOURCE')
    shared,_ = create(peer,ph,title='PARTNER_SHARED',visibility='shared')
    peer_lot,_ = acquisition(peer,ph,shared['item'])
    peer_source = source(app,peer_lot,'member2','PARTNER_SOURCE')
    # A shared item may contain acquisitions from both members. Only the exporting
    # actor's source/operation records can accompany it, under personal.inventory.
    on_shared,_ = acquisition(own,h,peer_lot['item'])
    on_shared_source = source(app,on_shared,'member1','OWN_ON_SHARED')
    hidden,_ = create(peer,ph,title='PARTNER_PRIVATE')
    hidden_lot,_ = acquisition(peer,ph,hidden['item'])
    source(app,hidden_lot,'member2','HIDDEN_PARTNER_SOURCE')
    return dict(app=app,own=own,h=h,peer=peer,ph=ph,personal=personal,shared=on_shared,
        mine_source=mine_source,peer_source=peer_source,on_shared_source=on_shared_source)


def export(client, headers, shared=False):
    return client.post('/api/portability/export',json={'includeShared':shared},headers=headers)


def on_zip_close(monkeypatch, callback):
    real = portability.ZipFile
    calls = []
    class ChangedOnClose(real):
        def close(self):
            super().close()
            if self.mode == 'w' and not calls:
                calls.append(True)
                callback()
    monkeypatch.setattr(portability,'ZipFile',ChangedOnClose)
    return calls


def test_personal_shared_sources_and_operation_allowlists(stocked):
    env = stocked
    data,files = unpack(export(env['own'],env['h']))
    own = data['personal']['inventory']
    assert set(own) == {'items','sources','operations'} and 'shared' not in data
    assert [item['id'] for item in own['items']] == [env['personal']['item']['id']]
    assert [row['id'] for row in own['sources']] == [env['mine_source']]
    assert own['items'][0]['onHandQty'] == 2
    assert own['items'][0]['movements'][0]['deltaQty'] == 2
    combined,files = unpack(export(env['own'],env['h'],True))
    personal,shared = combined['personal']['inventory'],combined['shared']['inventory']
    assert set(shared) == {'items'}
    assert [row['id'] for row in shared['items']] == [env['shared']['item']['id']]
    assert {r['id'] for r in personal['sources']} == {env['mine_source'],env['on_shared_source']}
    assert {r['itemId'] for r in personal['operations']} == {env['personal']['item']['id'],env['shared']['item']['id']}
    with connection(env['app']) as con:
        peer_ops = {r[0] for r in con.execute("SELECT id FROM inventory_operations WHERE actor='member2'")}
    assert not peer_ops & {r['id'] for r in personal['operations']}
    all_inventory = json.dumps([personal,shared],ensure_ascii=False)
    for hidden in ['PARTNER_PRIVATE','PARTNER_SOURCE_ORDER','PARTNER_SOURCE_SETTLEMENT',
        'OWNER_SOURCE_LINE','OWN_ON_SHARED_LINE','HIDDEN_PARTNER_SOURCE','d'*64,
        'request_id','requestId','payload_digest','source_digest','source_revision','line_key','result','canManage']:
        assert hidden not in all_inventory
    assert all(set(r)==portability.INVENTORY_SOURCE_FIELDS for r in personal['sources'])
    assert all(set(r)==portability.INVENTORY_OPERATION_FIELDS for r in personal['operations'])
    assert combined['coverage']['inventory'] == 'manual_records'
    assert len(files) == 5 and 'personal.inventory' in files['README.txt'].decode()
    summary = env['own'].get('/api/portability/summary')
    assert summary.status_code == 200
    assert summary.json['personal']['inventoryItems'] == 1
    assert summary.json['shared']['inventoryItems'] == 1


def test_archive_excludes_item_and_immutable_receipts_from_download(app):
    c,h = login(app)
    item,_ = create(c,h,title='ARCHIVED_ITEM')
    response = c.delete(P+'/items/'+item['item']['id'],json={'requestId':rid(),'revision':1,'confirmArchive':True},headers=h)
    assert response.status_code == 200
    data,_ = unpack(export(c,h,True))
    assert data['personal']['inventory'] == {'items':[],'sources':[],'operations':[]}
    assert c.get('/api/portability/summary').json['personal']['inventoryItems'] == 0
    with connection(app) as con:
        assert con.execute('SELECT count(*) FROM inventory_operations').fetchone()[0] == 2


@pytest.mark.parametrize('change',['withdraw','rename','batch','movement','source','archive','aba'])
def test_inventory_change_after_zip_compression_discards_whole_zip(stocked,monkeypatch,change):
    env = stocked
    # An empty owner item is independently archivable without deleting history.
    empty,_ = create(env['own'],env['h'],title='EMPTY_ARCHIVABLE')
    def mutate():
        if change in ('withdraw','rename','aba'):
            path = P+'/items/'+env['shared']['item']['id']
            value = env['peer'].get(path).json['item']
            patch = {'title':'CHANGED_SHARED'} if change=='rename' else {'visibility':'private'}
            response = env['peer'].patch(path,json={'requestId':rid(),'revision':value['revision'],'patch':patch},headers=env['ph'])
            assert response.status_code == 200
            if change=='aba':
                assert env['peer'].patch(path,json={'requestId':rid(),'revision':response.json['item']['revision'],
                    'patch':{'visibility':'shared'}},headers=env['ph']).status_code == 200
        elif change=='batch':
            current = env['personal']
            assert env['own'].patch(P+'/acquisitions/'+current['acquisition']['id'],json={'requestId':rid(),
                'itemRevision':current['item']['revision'],'revision':current['acquisition']['revision'],
                'patch':{'note':'CHANGED_BATCH'}},headers=env['h']).status_code == 200
        elif change=='movement':
            move(env['own'],env['h'],env['personal'],'consume',1)
        elif change=='source':
            with connection(env['app']) as con:
                con.execute("UPDATE inventory_source_links SET status='detached',revision=revision+1 WHERE id=?",(env['mine_source'],))
        else:
            assert env['own'].delete(P+'/items/'+empty['item']['id'],json={'requestId':rid(),'revision':1,'confirmArchive':True},headers=env['h']).status_code == 200
    calls = on_zip_close(monkeypatch,mutate)
    response = export(env['own'],env['h'],True)
    assert calls and response.status_code == 409 and response.mimetype == 'application/json'
    assert '物品或共享范围已变化' in response.json['error']
    assert 'Content-Disposition' not in response.headers
    assert portability.EXPORT_SLOT.acquire(blocking=False)
    portability.EXPORT_SLOT.release()
    with connection(env['app']) as con:
        assert con.execute("SELECT count(*) FROM audit WHERE action='personal_data_export'").fetchone()[0] == 0


def test_unincluded_partner_changes_do_not_invalidate_personal_export(stocked,monkeypatch):
    env = stocked
    def mutate():
        item = env['shared']['item']
        assert env['peer'].patch(P+'/items/'+item['id'],json={'requestId':rid(),'revision':item['revision'],
            'patch':{'visibility':'private'}},headers=env['ph']).status_code == 200
    on_zip_close(monkeypatch,mutate)
    data,_ = unpack(export(env['own'],env['h']))
    assert 'shared' not in data and len(data['personal']['inventory']['items']) == 1


def test_actual_logout_during_zip_is_401_and_summary_revalidates_current(app,monkeypatch):
    c,h = login(app)
    create(c,h)
    def logout():
        assert c.post('/api/logout',json={},headers=h).status_code == 200
    calls = on_zip_close(monkeypatch,logout)
    response = export(c,h)
    assert calls and response.status_code == 401 and response.mimetype == 'application/json'
    assert 'Content-Disposition' not in response.headers
    assert c.get('/api/portability/summary').status_code == 401


def test_summary_fences_session_revoked_after_actor_guard(app):
    from flask import request
    @app.before_request
    def revoke():
        if request.path == '/api/portability/summary':
            with connection(app) as con:
                con.execute('UPDATE member_sessions SET revoked_at=1')
    c,_ = login(app)
    response = c.get('/api/portability/summary')
    assert response.status_code == 401 and 'personal' not in response.json


def test_actual_invited_household_export_has_no_original_inventory(stocked):
    env = stocked
    invite = env['own'].post('/api/spaces/invitations',json={},headers=env['h']).json['invitation']
    child = env['app'].test_client()
    result = child.post('/api/spaces/redeem',json={'invitation':invite,'name':'合成导出第二户',
        'slug':'inventory-export-child','MEMBER1_PASSWORD':'synthetic-child-password','MEMBER2_PASSWORD':'synthetic-child-password'})
    assert result.status_code == 201
    child.get(result.json['entry'])
    assert child.post('/api/login',json={'username':'member1','password':'synthetic-child-password'}).status_code == 200
    headers = {'X-CSRF-Token':child.get('/api/me').json['csrf'],'Origin':'http://localhost'}
    create(child,headers,title='ONLY_CHILD_ITEM')
    data,files = unpack(export(child,headers,True))
    assert [r['title'] for r in data['personal']['inventory']['items']] == ['ONLY_CHILD_ITEM']
    assert data['shared']['inventory'] == {'items':[]}
    contents = b''.join(files.values())
    for marker in (b'OWNER_PRIVATE',b'PARTNER_SHARED',b'OWNER_SOURCE',b'PARTNER_SOURCE'):
        assert marker not in contents
    original,_ = unpack(export(env['own'],env['h'],True))
    assert 'ONLY_CHILD_ITEM' not in json.dumps(original)
