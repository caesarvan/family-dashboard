"""Real 53-table factory/SQLite restore; synthetic data, no external services."""
from contextlib import closing
import hashlib
import json
import sqlite3

import pytest

from app import create_app
from deploy.backup import backup_all
import inventory_core as core
from test_inventory_api import P, acquisition, create, move, rid
from test_journey_documents import PASSWORD, connection, login
from test_media_restore import (INVENTORY_TABLES, MEDIA_TABLES, config, copy_group,
    database, media_rows, no_network, restore_program, seed_household)


def snapshot(path, expected_tables):
    with closing(sqlite3.connect(path)) as con:
        assert con.execute('PRAGMA quick_check').fetchone()[0]=='ok'
        assert not con.execute('PRAGMA foreign_key_check').fetchall()
        schema=con.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type,name").fetchall()
        tables=[r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        assert len([name for name in tables if not name.startswith('sqlite_')])==expected_tables
        return schema,{name:con.execute('SELECT * FROM "'+name+'" ORDER BY rowid').fetchall() for name in tables}


def strict_factory(root):
    app=create_app(config(root))
    assert {'inventory','household_media','media_playback'}<=app.extensions.keys()
    return app


def seed_inventory(app):
    c,h=login(app);partner,ph=login(app,2)
    private,_=create(c,h,title='Synthetic private inventory')
    partner_private,_=create(partner,ph,title='Synthetic partner private inventory')
    shopping=c.post('/api/items/shopping',headers=h,json={'title':'Synthetic recovery order','quantity':'8 pieces','owner':'member1'})
    assert shopping.status_code in (200,201)
    item,create_request=create(c,h,title='Synthetic shared inventory',reorderPoint=2)
    current,order_request=acquisition(c,h,item['item'],orderedQty=8,shoppingId=shopping.json['id'])
    current,receive_request=move(c,h,current,quantity=4)
    first_receive=current['operation']['movementId']
    current,_=move(c,h,current,quantity=2)
    current,_=move(c,h,current,'consume',2)
    consumed=current['operation']['movementId']
    item_id,lot_id=current['item']['id'],current['acquisition']['id']
    endpoint=P+'/acquisitions/'+lot_id+'/movements'
    reversal={'requestId':rid(),'itemRevision':current['item']['revision'],'revision':current['acquisition']['revision'],
        'data':{'occurredOn':'2026-09-16','reason':'Synthetic consumed quantity was not used'},'confirmReversal':True}
    reversed_response=c.post(endpoint+'/'+consumed+'/reverse',json=reversal,headers=h)
    assert reversed_response.status_code==200,reversed_response.json
    current=reversed_response.json
    assert (current['item']['onHandQty'],current['item']['inTransitQty'])==(6,2)
    shared=c.patch(P+'/items/'+item_id,headers=h,json={'requestId':rid(),'revision':current['item']['revision'],'patch':{'visibility':'shared'}})
    assert shared.status_code==200
    # There is no financial-source HTTP route. Seed only this synthetic link
    # through the trusted core transaction seam; do not invent a public API.
    current=c.get(P+'/acquisitions/'+lot_id).json
    source_id,source_request=rid()[:24],rid()
    with closing(connection(app)) as con:
        con.execute('BEGIN IMMEDIATE')
        def attach_source():
            con.execute('INSERT INTO inventory_source_links VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (source_id,'member1',lot_id,'synthetic-private-order','synthetic-private-line','a'*64,1,
                 'synthetic-private-settlement','active',1,'2026-09-16','2026-09-16'))
            return {'itemId':item_id,'itemRevision':current['item']['revision'],'acquisitionId':lot_id,
                    'acquisitionRevision':current['acquisition']['revision'],'sourceLinkId':source_id,'sourceRevision':1}
        core.apply_with_receipt(con,'member1',source_request,'attach_source',{'syntheticSource':source_id},attach_source,
            item_id=item_id,item_revision=current['item']['revision'],acquisition_id=lot_id,
            acquisition_revision=current['acquisition']['revision'])
        con.commit()
    return {'item':item_id,'lot':lot_id,'private':private['item']['id'],'partnerPrivate':partner_private['item']['id'],
        'shopping':shopping.json['id'],'firstReceive':first_receive,'consumed':consumed,'source':source_id,
        'requests':[(P+'/items',create_request),(P+'/items/'+item_id+'/acquisitions',order_request),
                    (endpoint,receive_request),(endpoint+'/'+consumed+'/reverse',reversal)],
        'sourceRequestId':source_request}


def verify_inventory(app,value,all_values,path):
    c,h=login(app);partner,_=login(app,2)
    item=c.get(P+'/items/'+value['item']).json['item']
    lot=c.get(P+'/acquisitions/'+value['lot']).json['acquisition']
    assert (item['onHandQty'],item['inTransitQty'],item['plannedQty'])==(6,2,0)
    assert (lot['receivedQty'],lot['remainingExpectedQty'],lot['onHandQty'],lot['shoppingId'])==(6,2,6,value['shopping'])
    assert partner.get(P+'/items/'+value['item']).status_code==200
    assert partner.get(P+'/items/'+value['private']).status_code==404
    assert c.get(P+'/items/'+value['partnerPrivate']).status_code==404
    events=c.get(P+'/acquisitions/'+value['lot']+'/movements').json['items']
    assert len(events)==4 and sum(row['deltaQty'] for row in events)==6
    original=next(row for row in events if row['id']==value['consumed'])
    reversal=next(row for row in events if row['kind']=='reverse')
    assert original['deltaQty']==-2 and not original['canReverse']
    assert reversal['reversesId']==original['id'] and reversal['deltaQty']==2 and not reversal['canReverse']
    with closing(connection(app)) as con:
        con.execute('BEGIN')
        own=core.export_inventory(con,'member1',True);other=core.export_inventory(con,'member2',True)
        assert [source['id'] for source in own['sources']]==[value['source']] and other['sources']==[]
        assert 'synthetic-private-order' not in json.dumps(other)
        con.rollback()
        # Restored immutable-history triggers still reject writes, not just reads.
        for sql in ("UPDATE inventory_movements SET reason='changed'",'DELETE FROM inventory_movements',
                    "UPDATE inventory_operations SET result='{}'",'DELETE FROM inventory_operations'):
            with pytest.raises(sqlite3.IntegrityError,match='inventory_history'):
                con.execute(sql)
            con.rollback()
    visible=partner.get(P+'/acquisitions/'+value['lot']).json
    assert not any(secret in json.dumps(visible) for secret in ('synthetic-private-order','synthetic-private-line','a'*64))
    before=media_rows(path)
    for endpoint,payload in value['requests']:
        replay=c.post(endpoint,json=payload,headers=h)
        assert replay.status_code==200 and replay.json['operation']['replayed'],replay.json
        assert c.get(P+'/operations/'+payload['requestId']).json==replay.json
        assert partner.get(P+'/operations/'+payload['requestId']).status_code==404
    assert media_rows(path)==before  # no duplicate event/receipt or media changes
    for other_value in all_values:
        if other_value['item']==value['item']:
            continue
        for endpoint in (P+'/items/'+other_value['item'],P+'/acquisitions/'+other_value['lot'],
                         P+'/operations/'+other_value['requests'][0][1]['requestId']):
            assert c.get(endpoint).status_code==404


def test_two_household_inventory_and_media_full_restore(tmp_path,monkeypatch):
    source,target=tmp_path/'source',tmp_path/'restored';source.mkdir();target.mkdir()
    app=strict_factory(source);owner,h=login(app)
    invitation=owner.post('/api/spaces/invitations',json={},headers=h).json['invitation']
    response=app.test_client().post('/api/spaces/redeem',json={'invitation':invitation,'slug':'inventory-recovery',
        'name':'Synthetic inventory recovery household','MEMBER1_PASSWORD':PASSWORD,'MEMBER2_PASSWORD':PASSWORD})
    assert response.status_code==201
    platform=app.extensions['household_platform'];household=next(row for row in platform.households() if row['id']!='default')
    child=platform.child(household)
    assert {'inventory','household_media','media_playback'}<=child.extensions.keys()
    apps={'default':app,household['id']:child}
    photos={uid:seed_household(application) for uid,application in apps.items()}
    inventory={uid:seed_inventory(application) for uid,application in apps.items()}
    for uid,application in apps.items():
        for cookie in photos[uid]['oldCookies']:
            active=application.test_client();active.set_cookie('session',cookie)
            assert active.get(P+'/items').status_code==active.get('/api/media/items').status_code==200
    before={uid:snapshot(database(source,uid),53) for uid in apps}
    registry=snapshot(source/'platform.sqlite3',2)
    domains={uid:media_rows(database(source,uid)) for uid in apps}
    assert all(set(rows)==set(MEDIA_TABLES+INVENTORY_TABLES) for rows in domains.values())
    backup=backup_all(source);assert backup['databases']==3
    copy_group(source,target,backup['manifest'])
    invalidate=restore_program(target,backup['manifest'],monkeypatch)
    assert snapshot(target/'platform.sqlite3',2)==registry
    for uid in apps:
        path=database(target,uid)
        assert snapshot(path,53)==before[uid]  # every schema object/table/row/BLOB/sequence
        with closing(sqlite3.connect(path)) as con:
            versions=dict(con.execute('SELECT id,auth_version FROM users'))
            con.executescript(invalidate)
            assert dict(con.execute('SELECT id,auth_version FROM users'))=={key:value+1 for key,value in versions.items()}
            assert con.execute('SELECT count(*) FROM member_sessions WHERE revoked_at IS NULL').fetchone()[0]==0
            assert con.execute('SELECT count(*) FROM cloud_oauth_states').fetchone()[0]==0
    restored=strict_factory(target);restored_platform=restored.extensions['household_platform']
    second=restored_platform.child(next(row for row in restored_platform.households() if row['id']==household['id']))
    assert {'inventory','household_media','media_playback'}<=second.extensions.keys()
    for uid,application in {'default':restored,household['id']:second}.items():
        value=photos[uid];path=database(target,uid)
        assert media_rows(path)==domains[uid]
        for cookie in value['oldCookies']:
            stale=application.test_client();stale.set_cookie('session',cookie)
            assert stale.get(P+'/items').status_code==stale.get('/api/media/items').status_code==401
        verify_inventory(application,inventory[uid],inventory.values(),path)
        c,h=login(application);partner,_=login(application,2)
        private='/api/media/items/'+value['private']+'/preview'
        assert hashlib.sha256(c.get(private).data).hexdigest()==value['previewSha256']
        assert partner.get(private).status_code==404 and c.get('/api/media/items/'+value['partner']).status_code==404
        shared=c.get('/api/media/items/'+value['shared']).json['item']
        assert shared['journey']['id']==value['journey'] and partner.get(shared['previewUrl']).status_code==200
        tv=application.test_client();tv.set_cookie('household_tv',value['tvCookie'])
        state=tv.get('/api/media-tv/playback').json
        assert state['paused'] and state['item']['id']==value['shared']
        assert tv.get(state['item']['previewUrl']).status_code==200 and tv.get(P+'/items').status_code==403
        ungranted=application.test_client();ungranted.set_cookie('household_tv',value['ungrantedTvCookie'])
        assert ungranted.get(state['item']['previewUrl']).status_code==404
        for other_uid,other_value in photos.items():
            if other_uid!=uid:assert c.get('/api/media/items/'+other_value['shared']).status_code==404
        assert c.put('/api/media/items/'+value['shared']+'/tv-grants',json={'revision':shared['revision'],'deviceIds':[]},headers=h).status_code==200
        assert tv.get('/api/media-tv/playback').json['item'] is None and tv.get(state['item']['previewUrl']).status_code==404
    print(json.dumps({'kind':'synthetic-local-inventory-media-restore','households':2,'databases':3,
        'householdTables':53,'platformTables':2,'oldCookiesRejected':4,'factoryFallback':False,
        'inventoryTables':5,'mediaTables':4,'realDocker':False,'productionWrites':0,
        'sourceLinkSeed':'trusted core fixture; no financial-source HTTP route','restoredTvGrantsRequireReview':True}))
