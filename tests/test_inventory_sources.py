"""Synthetic imported XLSX, real HTTP member sessions and isolated SQLite only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import threading
import time
from types import SimpleNamespace

from flask import g, request
import pytest

import inventory_sources as sources
from test_inventory_api import app, factory, offline, acquisition, counts, create, rid
from test_inventory_followup import snapshot
from test_journey_documents import PASSWORD, clone, connection, login
from test_taobao_order_groups import payload as workbook_payload, save as import_orders


P = '/api/inventory'
FINANCE = '/api/finance-hub'


def setup(c,h, *, shared=False):
    value = workbook_payload((('SOURCE_ORDER',2),))
    import_orders(c,h,value)
    order = c.get(FINANCE+'/transactions?month=2026-09').json['transactions'][0]
    item,_ = create(c,h,title='明确填写的物品',visibility='shared' if shared else 'private')
    current,_ = acquisition(c,h,item['item'],orderedQty=7)
    return current,order,value


def attach(current,order,**changes):
    return dict(requestId=rid(),operation='attach',acquisitionId=current['acquisition']['id'],
                itemRevision=current['item']['revision'],revision=current['acquisition']['revision'],
                orderId=order['id'],orderRevision=order['revision'],lineKey='item:0')|changes


def prepare(c,h,plan):
    shown = c.post(P+'/sources/preview',headers=h,json=plan)
    assert shown.status_code==200,shown.json
    return shown.json,dict(requestId=plan['requestId'],previewToken=shown.json['previewToken'],confirmSource=True)


def confirm(c,h,body):
    response = c.post(P+'/sources/confirm',headers=h,json=body)
    assert response.status_code==200,response.json
    return response.json


def source(c,current):
    response = c.get(P+'/acquisitions/'+current['acquisition']['id']+'/source')
    assert response.status_code==200,response.json
    return response.json


def detach(current,link):
    return dict(requestId=rid(),operation='detach',acquisitionId=current['acquisition']['id'],
                itemRevision=current['item']['revision'],revision=current['acquisition']['revision'],
                sourceLinkId=link['id'],sourceRevision=link['revision'])


def financial_snapshot(app):
    with closing(connection(app)) as con:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND "
            "(name LIKE 'hub_%' OR name LIKE 'finance_%' OR name IN ('private_finance','entities','inventory_movements'))")]
        return {table:[tuple(row) for row in con.execute('SELECT * FROM '+table+' ORDER BY rowid')]
                for table in tables} | {'settings':[tuple(row) for row in con.execute("SELECT * FROM settings WHERE id!='meta' ORDER BY id")]}


def test_real_grouped_import_selection_attach_reimport_detach_preserve_money_and_stock(app,factory):
    c,h = login(app); current,order,file = setup(c,h,shared=True)
    other,oh = login(app,2)
    with closing(connection(app)) as con:
        schema = [tuple(row) for row in con.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name')]
    before_finance,before_counts = financial_snapshot(app),counts(app)
    first = c.get(P+'/orders/'+order['id']+'?limit=1').json
    second = c.get(P+'/orders/'+order['id']+'?limit=1&offset=1').json
    assert first['total']==2 and first['nextOffset']==1 and second['nextOffset'] is None
    assert [first['lines'][0]['lineKey'],second['lines'][0]['lineKey']]==['item:0','item:1']
    assert first['lines'][0]['quantityText']=='2' and current['acquisition']['orderedQty']==7
    assert set(first['order'])=={'id','revision','title','date','status'}
    assert set(first['lines'][0])=={'lineKey','title','variant','quantityText','linkState','link'}
    assert c.get(P+'/orders/'+order['id']).headers['Cache-Control']=='no-store'
    assert source(c,current)['link'] is None
    plan = attach(current,order,lineKey='item:1')
    shown,body = prepare(c,h,plan)
    assert shown['line']['title']=='PRIVATE_ITEM_SOURCE_ORDER_1' and shown['link'] is None
    assert counts(app)==before_counts and financial_snapshot(app)==before_finance
    made = confirm(c,h,body)
    assert made['item']['title']=='明确填写的物品' and made['item']['revision']==current['item']['revision']+1
    assert made['acquisition']['orderedQty']==7 and made['acquisition']['receivedQty']==made['acquisition']['onHandQty']==0
    assert made['acquisition']['revision']==current['acquisition']['revision']+1
    assert financial_snapshot(app)==before_finance
    link = source(c,made)['link']
    assert link['state']=='current' and link['line']['lineKey']=='item:1' and link['reviewReasons']==[]
    assert made['operation']['sourceLinkId']==link['id'] and made['operation']['sourceRevision']==1
    linked = c.get(P+'/orders/'+order['id']).json['lines'][1]
    assert linked['linkState']=='linked' and linked['link']['acquisitionId']==made['acquisition']['id']
    public = other.get(P+'/acquisitions/'+made['acquisition']['id']).json
    assert 'PRIVATE_ITEM_' not in json.dumps(public) and 'orderId' not in json.dumps(public)
    assert 'PRIVATE_ITEM_' not in json.dumps(made) and 'source_digest' not in json.dumps(made)
    assert other.get(P+'/acquisitions/'+made['acquisition']['id']+'/source').status_code==403
    assert other.get(P+'/orders/'+order['id']).status_code==404
    assert other.get(P+'/operations/'+plan['requestId']).status_code==404
    before = snapshot(app)
    replay = confirm(c,h,body)
    assert replay['operation']['replayed'] and snapshot(app)==before
    assert c.get(P+'/operations/'+plan['requestId']).json==replay
    restarted = factory(dict(app.config)); resumed = clone(restarted,c)
    assert source(resumed,made)==source(c,made)
    _,imported = import_orders(c,h,file)
    assert imported['duplicates']==1 and imported['imported']==0 and source(c,made)['link']['state']=='current'
    before_detach = financial_snapshot(app)
    _,remove_body = prepare(c,h,detach(made,link))
    removed = confirm(c,h,remove_body)
    assert financial_snapshot(app)==before_detach
    assert source(c,removed)['link']['state']=='detached'
    assert c.get(P+'/orders/'+order['id']).json['lines'][1]['linkState']=='none'
    # Re-linking is a new retained history row, never resurrection/deletion.
    _,body2 = prepare(c,h,attach(removed,order,lineKey='item:1'))
    again = confirm(c,h,body2)
    assert again['operation']['sourceLinkId']!=link['id']
    with closing(connection(app)) as con:
        assert con.execute('SELECT count(*) FROM inventory_source_links').fetchone()[0]==2
        assert [tuple(row) for row in con.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name')]==schema


def test_official_finance_patch_and_delete_mark_review_without_remapping_or_cascading(app):
    c,h = login(app); current,order,_ = setup(c,h)
    _,body = prepare(c,h,attach(current,order))
    made = confirm(c,h,body)
    changed = c.patch(FINANCE+'/transactions/'+order['id'],headers=h,json={'revision':1,'category':'明确分类'})
    assert changed.status_code==200,changed.json
    link = source(c,made)['link']
    assert link['state']=='needs_review' and link['reviewReasons']==['source_changed'] and link['line'] is None
    assert c.get(P+'/orders/'+order['id']).json['lines'][0]['linkState']=='unavailable'
    assert confirm(c,h,body)['operation']['replayed']
    deleted = c.delete(FINANCE+'/transactions/'+order['id'],headers=h,json={'revision':2})
    assert deleted.status_code==200,deleted.json
    link = source(c,made)['link']
    assert link['reviewReasons']==['source_missing'] and link['order'] is link['line'] is None
    assert c.get(P+'/orders/'+order['id']).status_code==404
    _,remove_body = prepare(c,h,detach(made,link))
    removed = confirm(c,h,remove_body)
    assert source(c,removed)['link']['state']=='detached'
    assert removed['acquisition']['orderedQty']==7 and removed['acquisition']['receivedQty']==0
    assert confirm(c,h,body)['operation']['replayed']


@pytest.mark.parametrize('change',['item','acquisition','order','digest','delete'])
def test_changed_dependency_after_preview_rejects_atomically(app,change):
    c,h = login(app); current,order,_ = setup(c,h)
    _,body = prepare(c,h,attach(current,order))
    if change=='item':
        result = c.patch(P+'/items/'+current['item']['id'],headers=h,json={
            'requestId':rid(),'revision':current['item']['revision'],'patch':{'location':'明确调整'}})
    elif change=='acquisition':
        result = c.patch(P+'/acquisitions/'+current['acquisition']['id'],headers=h,json={
            'requestId':rid(),'itemRevision':current['item']['revision'],'revision':current['acquisition']['revision'],
            'patch':{'note':'明确调整'}})
    elif change=='order':
        result = c.patch(FINANCE+'/transactions/'+order['id'],headers=h,json={'revision':1,'category':'明确调整'})
    elif change=='delete':
        result = c.delete(FINANCE+'/transactions/'+order['id'],headers=h,json={'revision':1})
    else:
        with closing(connection(app)) as con,con:
            row = json.loads(con.execute('SELECT data FROM hub_transactions WHERE id=?',(order['id'],)).fetchone()[0])
            row['orderItems'].reverse()
            con.execute('UPDATE hub_transactions SET data=? WHERE id=?',(json.dumps(row),order['id']))
        result = SimpleNamespace(status_code=200)
    assert result.status_code==200
    before = snapshot(app)
    rejected = c.post(P+'/sources/confirm',headers=h,json=body)
    assert rejected.status_code in (404,409),rejected.json
    assert snapshot(app)==before
    assert c.get(P+'/operations/'+body['requestId']).status_code==404


def test_expiry_unknown_result_request_conflict_and_session_token_binding(app,monkeypatch):
    c,h = login(app); current,order,_ = setup(c,h)
    plan = attach(current,order); _,body = prepare(c,h,plan)
    monkeypatch.setattr(sources,'time',SimpleNamespace(time=lambda:time.time()+901))
    before = snapshot(app)
    assert c.post(P+'/sources/confirm',headers=h,json=body).status_code==400
    assert snapshot(app)==before
    monkeypatch.setattr(sources,'time',time)
    made = confirm(c,h,body)
    monkeypatch.setattr(sources,'time',SimpleNamespace(time=lambda:time.time()+901))
    assert confirm(c,h,body)['operation']['replayed']
    assert c.get(P+'/operations/'+plan['requestId']).json['operation']['sourceLinkId']==made['operation']['sourceLinkId']
    assert c.post(P+'/sources/confirm',headers=h,json=body|{'requestId':rid()}).json['code']=='request_conflict'
    other_session,other_headers = login(app)
    assert other_session.post(P+'/sources/confirm',headers=other_headers,json=body).status_code==403
    # Receipt recovery is owner-scoped and survives an intentional new login.
    assert other_session.get(P+'/operations/'+plan['requestId']).status_code==200


@pytest.mark.parametrize('same_key',[True,False])
def test_concurrent_confirm_single_link_receipt_audit_and_meta(app,same_key):
    c,h = login(app); current,order,_ = setup(c,h)
    _,first = prepare(c,h,attach(current,order))
    second = first if same_key else prepare(c,h,attach(current,order))[1]
    before = counts(app); gate = threading.Barrier(2)
    def apply(body):
        client = clone(app,c); gate.wait(timeout=10)
        return client.post(P+'/sources/confirm',headers=h,json=body)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(apply,[first,second]))
    assert sorted(r.status_code for r in results)==([200,200] if same_key else [200,409])
    if same_key:
        assert sorted(r.json['operation']['replayed'] for r in results)==[False,True]
    for key in ('inventory_operations','audit','meta'):
        assert counts(app)[key]==before[key]+1
    with closing(connection(app)) as con:
        assert con.execute('SELECT count(*) FROM inventory_source_links').fetchone()[0]==1


@pytest.mark.parametrize('table,event,status',[
    ('inventory_source_links','INSERT',409),('inventory_items','UPDATE',409),
    ('inventory_acquisitions','UPDATE',409),('inventory_operations','INSERT',409),
    ('audit','INSERT',503),('settings','UPDATE',503)])
def test_each_attach_write_failure_rolls_back_and_original_key_retries(app,table,event,status):
    c,h = login(app); current,order,_ = setup(c,h)
    _,body = prepare(c,h,attach(current,order))
    with closing(connection(app)) as con,con:
        con.execute(f"CREATE TRIGGER source_test_failure BEFORE {event} ON {table} "
                    "BEGIN SELECT RAISE(ABORT,'PRIVATE_SOURCE_SQL'); END")
    before = snapshot(app)
    rejected = c.post(P+'/sources/confirm',headers=h,json=body)
    assert rejected.status_code==status,rejected.json
    assert 'PRIVATE_SOURCE_SQL' not in rejected.get_data(as_text=True) and snapshot(app)==before
    with closing(connection(app)) as con,con:
        con.execute('DROP TRIGGER source_test_failure')
    assert not confirm(c,h,body)['operation']['replayed']


def test_owner_private_acl_revoke_and_no_hidden_link_target(app):
    c,h = login(app); other,oh = login(app,2)
    _,order,_ = setup(c,h)
    item,_ = create(other,oh,visibility='shared')
    current,_ = acquisition(c,h,item['item'])
    _,body = prepare(c,h,attach(current,order))
    made = confirm(c,h,body)
    assert other.get(P+'/acquisitions/'+made['acquisition']['id']+'/source').status_code==403
    assert other.post(P+'/sources/preview',headers=oh,json=attach(made,order)).status_code==403
    private = other.patch(P+'/items/'+made['item']['id'],headers=oh,json={
        'requestId':rid(),'revision':made['item']['revision'],'patch':{'visibility':'private'}})
    assert private.status_code==200
    before = snapshot(app)
    assert c.get(P+'/acquisitions/'+made['acquisition']['id']+'/source').status_code==404
    assert c.post(P+'/sources/confirm',headers=h,json=body).status_code==404
    assert c.get(P+'/operations/'+body['requestId']).status_code==404
    line = c.get(P+'/orders/'+order['id']).json['lines'][0]
    assert line['linkState']=='unavailable' and line['link'] is None
    assert made['item']['id'] not in json.dumps(line) and snapshot(app)==before


@pytest.mark.parametrize('fault',['revoked','removed','auth_version','household','actor','captured_session'])
@pytest.mark.parametrize('route',['order','source','preview','confirm'])
def test_identity_rechecked_inside_every_source_transaction(app,fault,route):
    @app.before_request
    def after_guard():
        if not request.headers.get('X-Synthetic-Fault'):
            return
        if fault in ('revoked','removed','auth_version'):
            with closing(connection(app)) as con,con:
                if fault=='revoked':
                    con.execute('UPDATE member_sessions SET revoked_at=1')
                elif fault=='removed':
                    con.execute("UPDATE household_memberships SET state='removed',revision=revision+1 WHERE member_id='member1'")
                else:
                    con.execute("UPDATE users SET auth_version=auth_version+1 WHERE id='member1'")
        elif fault=='captured_session':
            g.member_session['id'] = 'f'*32
        else:
            g.actor['householdId' if fault=='household' else 'id'] = 'wrong-household' if fault=='household' else 'member2'
    c,h = login(app); current,order,_ = setup(c,h)
    plan = attach(current,order); _,body = prepare(c,h,plan)
    paths = {'order':P+'/orders/'+order['id'],'source':P+'/acquisitions/'+current['acquisition']['id']+'/source',
             'preview':P+'/sources/preview','confirm':P+'/sources/confirm'}
    before = snapshot(app)
    response = getattr(c,'post' if route in ('preview','confirm') else 'get')(paths[route],
        headers=h|{'X-Synthetic-Fault':'1'},**({'json':plan if route=='preview' else body} if route in ('preview','confirm') else {}))
    assert response.status_code==401,response.json
    assert snapshot(app)==before


def test_auth_tv_csrf_query_and_body_strictness(app):
    c,h = login(app); current,order,_ = setup(c,h)
    plan = attach(current,order); _,body = prepare(c,h,plan)
    tv = app.test_client(); pair = tv.post('/api/pair/start',json={}).json
    assert c.post('/api/pair/approve',headers=h,json={'code':pair['code'],'name':'合成电视'}).status_code==200
    assert tv.post('/api/pair/poll',json={'secret':pair['secret']}).json['approved']
    paths = [P+'/orders/'+order['id'],P+'/acquisitions/'+current['acquisition']['id']+'/source']
    before = snapshot(app)
    for path in paths:
        assert app.test_client().get(path).status_code==401
        assert tv.get(path).status_code==403
        # Existing global guard selects TV identity and rejects this member
        # cookie before the inventory adapter runs.
        assert c.get(path,headers={'X-Display-Mode':'tv'}).status_code==401
        assert c.get(path+'?owner=member2').status_code==400
    for action,value in [('preview',plan),('confirm',body)]:
        path = P+'/sources/'+action
        assert app.test_client().post(path,json=value).status_code==401
        assert tv.post(path,headers=h,json=value).status_code==403
        assert c.post(path,json=value).status_code==403
        assert c.post(path,headers=h|{'Origin':'https://other.invalid'},json=value).status_code==403
        assert c.post(path,headers=h,json=value|{'owner':'member2'}).status_code==400
    for query in ['limit=101','limit=1&limit=2','offset=-1']:
        assert c.get(paths[0]+'?'+query).status_code==400
    assert c.post(P+'/sources/confirm',headers=h,json=body|{'confirmSource':False}).status_code==400
    for token in ['bad-token-signature-123456', '\ud800'*20, '中'*20]:
        assert c.post(P+'/sources/confirm',headers=h,json=body|{'previewToken':token}).status_code==400
    for field,value in [('lineKey','sourceLine:2'),('orderRevision',True),('sourceLine',2),('revision',True)]:
        assert c.post(P+'/sources/preview',headers=h,json=plan|{field:value}).status_code==400
    assert snapshot(app)==before


def test_two_households_and_same_request_key_remain_separate(app):
    c,h = login(app); current,order,_ = setup(c,h)
    plan = attach(current,order); _,body = prepare(c,h,plan); confirm(c,h,body)
    invitation = c.post('/api/spaces/invitations',headers=h,json={}).json['invitation']
    child = app.test_client()
    response = child.post('/api/spaces/redeem',json={'invitation':invitation,
        'name':'合成来源第二家庭','slug':'inventory-source-two','MEMBER1_PASSWORD':PASSWORD,'MEMBER2_PASSWORD':PASSWORD})
    assert response.status_code==201,response.json
    assert child.get(response.json['entry']).status_code==303
    child,ch = login(app,client=child)
    assert child.get(P+'/orders/'+order['id']).status_code==404
    assert child.get(P+'/acquisitions/'+current['acquisition']['id']+'/source').status_code==404
    # Every household has its own secret; the other signature is invalid.
    assert child.post(P+'/sources/confirm',headers=ch,json=body).status_code==400
    assert child.get(P+'/operations/'+plan['requestId']).status_code==404
    other,other_order,_ = setup(child,ch)
    _,other_body = prepare(child,ch,attach(other,other_order,requestId=plan['requestId']))
    assert not confirm(child,ch,other_body)['operation']['replayed']
    assert c.get(P+'/orders/'+other_order['id']).status_code==404


def test_same_line_or_acquisition_cannot_be_relinked_without_explicit_detach(app):
    c,h = login(app); current,order,_ = setup(c,h)
    another_item,_ = create(c,h); another,_ = acquisition(c,h,another_item['item'])
    plan = attach(current,order); _,body = prepare(c,h,plan)
    _,other_body = prepare(c,h,attach(another,order,requestId=plan['requestId'],lineKey='item:1'))
    made = confirm(c,h,body)
    assert c.post(P+'/sources/confirm',headers=h,json=other_body).json['code']=='request_conflict'
    assert c.post(P+'/sources/preview',headers=h,json=attach(made,order,lineKey='item:1')).status_code==409
    assert c.post(P+'/sources/preview',headers=h,json=attach(another,order)).status_code==409


def test_ungrouped_order_is_one_explicit_line_payment_is_ineligible_and_opening_has_no_source(app):
    c,h = login(app)
    for kind in ('orders','payments'):
        value = {'source':'generic','kind':kind,'csv':'日期,金额,名称,币种\n2026-09-18,12,合成单行,CNY\n'}
        import_orders(c,h,value)
    rows = c.get(FINANCE+'/transactions?month=2026-09').json['transactions']
    order = next(r for r in rows if r['kind']=='orders'); payment = next(r for r in rows if r['kind']=='payments')
    context = c.get(P+'/orders/'+order['id']).json
    assert context['lines']==[dict(lineKey='order',title='合成单行',variant='',quantityText='',linkState='none',link=None)]
    assert c.get(P+'/orders/'+payment['id']).status_code==404
    item,_ = create(c,h); opening,_ = acquisition(c,h,item['item'],kind='opening',orderState='closed')
    assert c.get(P+'/acquisitions/'+opening['acquisition']['id']+'/source').status_code==400
    assert c.post(P+'/sources/preview',headers=h,json=attach(opening,order,lineKey='order')).status_code==400


def test_other_order_owner_rejected_even_on_own_or_shared_batch(app):
    c,h = login(app); other,oh = login(app,2)
    _,order,_ = setup(c,h)
    other_item,_ = create(other,oh,visibility='shared')
    other_batch,_ = acquisition(other,oh,other_item['item'])
    before = snapshot(app)
    assert other.post(P+'/sources/preview',headers=oh,json=attach(other_batch,order)).status_code==404
    assert snapshot(app)==before


@pytest.mark.parametrize('table,event,status',[
    ('inventory_source_links','UPDATE',409),('inventory_acquisitions','UPDATE',409),
    ('inventory_operations','INSERT',409),('audit','INSERT',503),('settings','UPDATE',503)])
def test_detach_failures_preserve_active_link_and_receipt(app,table,event,status):
    c,h = login(app); current,order,_ = setup(c,h)
    _,body = prepare(c,h,attach(current,order)); made = confirm(c,h,body)
    _,remove = prepare(c,h,detach(made,source(c,made)['link']))
    with closing(connection(app)) as con,con:
        con.execute(f"CREATE TRIGGER source_test_failure BEFORE {event} ON {table} "
                    "BEGIN SELECT RAISE(ABORT,'PRIVATE_DETACH_SQL'); END")
    before = snapshot(app)
    rejected = c.post(P+'/sources/confirm',headers=h,json=remove)
    assert rejected.status_code==status,rejected.json
    assert 'PRIVATE_DETACH_SQL' not in rejected.get_data(as_text=True) and snapshot(app)==before
    with closing(connection(app)) as con,con:
        con.execute('DROP TRIGGER source_test_failure')
    removed = confirm(c,h,remove)
    assert source(c,removed)['link']['state']=='detached'
    assert confirm(c,h,remove)['operation']['replayed']


def test_archive_hides_source_and_original_receipt_without_deleting_history(app):
    c,h = login(app); current,order,_ = setup(c,h)
    closed = c.patch(P+'/acquisitions/'+current['acquisition']['id'],headers=h,json={
        'requestId':rid(),'itemRevision':current['item']['revision'],'revision':current['acquisition']['revision'],
        'patch':{'orderState':'closed'}})
    assert closed.status_code==200
    _,body = prepare(c,h,attach(closed.json,order)); made = confirm(c,h,body)
    archived = c.delete(P+'/items/'+made['item']['id'],headers=h,json={
        'requestId':rid(),'revision':made['item']['revision'],'confirmArchive':True})
    assert archived.status_code==200
    before = snapshot(app)
    assert c.get(P+'/acquisitions/'+made['acquisition']['id']+'/source').status_code==410
    assert c.get(P+'/operations/'+body['requestId']).status_code==410
    assert c.post(P+'/sources/confirm',headers=h,json=body).status_code==410
    assert c.get(P+'/orders/'+order['id']).json['lines'][0]['linkState']=='unavailable'
    assert snapshot(app)==before
