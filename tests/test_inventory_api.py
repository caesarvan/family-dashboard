"""Real HTTP cookies/CSRF/household routing, SQLite and immutable inventory receipts."""
from concurrent.futures import ThreadPoolExecutor
import json
import secrets
import socket
import threading

from flask import g, jsonify, request
import pytest

import app as app_module
import inventory_api as api
from test_journey_documents import PASSWORD, clone, connection, login

P = '/api/inventory'


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*_args,**_kwargs):
        raise AssertionError('Inventory must never call the network')
    monkeypatch.setattr(socket.socket,'connect',denied)
    monkeypatch.setattr(socket,'create_connection',denied)


@pytest.fixture
def factory(monkeypatch):
    original = app_module.create_app
    def create(config):
        app = original(config)
        if 'inventory' in app.extensions:
            return app
        def db():
            if 'inventory_test_db' not in g:
                g.inventory_test_db = connection(app)
            return g.inventory_test_db
        @app.teardown_appcontext
        def close(_error):
            con = g.pop('inventory_test_db',None)
            if con:
                con.close()
        api.register_inventory(app,db,app_module.Problem)
        return app
    # Child HouseholdPlatform factories use this same explicit fixture registration.
    monkeypatch.setattr(app_module,'create_app',create)
    return create


@pytest.fixture
def app(tmp_path,monkeypatch,factory):
    monkeypatch.setenv('MEMBER1_PASSWORD',PASSWORD)
    monkeypatch.setenv('MEMBER2_PASSWORD',PASSWORD)
    return factory({'TESTING':True,'DATA_DIR':str(tmp_path/'home'),
        'SECRET_KEY':'synthetic-inventory-http-secret','SESSION_COOKIE_SECURE':False,
        'PUBLIC_ORIGIN':'http://localhost','GOOGLE_CLIENT_ID':'','GOOGLE_CLIENT_SECRET':'',
        'MICROSOFT_CLIENT_ID':'','MICROSOFT_CLIENT_SECRET':'','OPENAI_API_KEY':'','OPENAI_MODEL':'',
        'NVIDIA_API_KEY':'','NVIDIA_MODEL':''})


def rid():
    return secrets.token_hex(16)


def create(c,h,**data):
    value = {'requestId':rid(),'data':{'title':'合成电池','unit':'节',**data}}
    response = c.post(P+'/items',json=value,headers=h)
    assert response.status_code==201,response.json
    return response.json,value


def acquisition(c,h,item,**data):
    value = {'requestId':rid(),'itemRevision':item['revision'],
             'data':{'orderedQty':6,'orderState':'in_transit',**data}}
    response = c.post(P+'/items/'+item['id']+'/acquisitions',json=value,headers=h)
    assert response.status_code==201,response.json
    return response.json,value


def move(c,h,current,kind='receive',quantity=2,**extra):
    value = {'requestId':rid(),'itemRevision':current['item']['revision'],
        'revision':current['acquisition']['revision'],'data':{'kind':kind,'quantity':quantity,
        'occurredOn':'2026-09-16','reason':'合成明确实物动作'},api.CONFIRM[kind]:True,**extra}
    response = c.post(P+'/acquisitions/'+current['acquisition']['id']+'/movements',json=value,headers=h)
    assert response.status_code==200,response.json
    return response.json,value


def counts(app):
    with connection(app) as con:
        return {table:con.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in
            ['inventory_items','inventory_acquisitions','inventory_movements','inventory_operations','audit']} | {
            'meta':con.execute("SELECT revision FROM settings WHERE id='meta'").fetchone()[0]}


def test_private_create_receipt_current_projection_and_restart(app,factory):
    c,h = login(app)
    result,value = create(c,h,reorderPoint=3)
    item = result['item']
    assert item['visibility']=='private' and item['canManage'] and item['belowThreshold']
    assert item['onHandQty']==item['inTransitQty']==item['plannedQty']==0
    before = counts(app)
    replay = c.post(P+'/items',json=value,headers=h)
    assert replay.status_code==200 and replay.json['operation']['replayed']
    assert counts(app)==before
    assert c.get(P+'/operations/'+value['requestId']).json==replay.json
    assert c.get(P+'/items/'+item['id']).headers['Cache-Control']=='no-store'
    renamed = c.patch(P+'/items/'+item['id'],headers=h,json={'requestId':rid(),'revision':1,'patch':{'title':'当前名称'}})
    assert renamed.status_code==200
    receipt = c.get(P+'/operations/'+value['requestId']).json
    assert receipt['operation']['itemRevision']==1 and receipt['item']['revision']==2
    restarted = factory(dict(app.config))
    resumed = clone(restarted,c)
    assert resumed.get(P+'/operations/'+value['requestId']).json==receipt
    assert 'inventory' not in c.get('/api/state').json


def test_purchase_partial_receive_return_reverse_never_double_books(app):
    c,h = login(app)
    shopping = c.post('/api/items/shopping',headers=h,json={'title':'合成采购','quantity':'两盒六节',
        'actual':2300,'budget':3000,'done':False,'owner':'member2'}).json
    with connection(app) as con:
        before = [tuple(r) for r in con.execute('SELECT id,kind,data,revision FROM entities')]
        financial = [tuple(r) for r in con.execute('SELECT * FROM settings ORDER BY id') if r['id']!='meta']
    item,_ = create(c,h,reorderPoint=4)
    current,_ = acquisition(c,h,item['item'],shoppingId=shopping['id'])
    assert current['item']['inTransitQty']==6 and current['item']['onHandQty']==0
    current,receipt = move(c,h,current,quantity=2)
    assert (current['acquisition']['fulfillmentState'],current['acquisition']['remainingExpectedQty'])==('partial',4)
    old_counts = counts(app)
    endpoint = P+'/acquisitions/'+current['acquisition']['id']+'/movements'
    assert c.post(endpoint,json=receipt,headers=h).json['operation']['replayed']
    assert counts(app)==old_counts
    current,_ = move(c,h,current,quantity=4)
    assert current['acquisition']['fulfillmentState']=='received'
    current,_ = move(c,h,current,'consume',1)
    current,_ = move(c,h,current,'return',1)
    assert (current['acquisition']['onHandQty'],current['acquisition']['receivedQty'],current['acquisition']['returnedQty'])==(4,6,1)
    returned = current['operation']['movementId']
    value = {'requestId':rid(),'itemRevision':current['item']['revision'],'revision':current['acquisition']['revision'],
             'data':{'occurredOn':'2026-09-16','reason':'退回未实际完成，明确反转'},'confirmReversal':True}
    result = c.post(endpoint+'/'+returned+'/reverse',json=value,headers=h)
    assert result.status_code==200 and result.json['acquisition']['onHandQty']==5
    assert result.json['acquisition']['returnedQty']==0 and result.json['acquisition']['remainingExpectedQty']==0
    events = c.get(endpoint+'?limit=2').json
    assert events['total']==5 and events['nextOffset']==2 and len(events['items'])==2
    assert events['items'][0]['kind']=='reverse' and not events['items'][0]['canReverse']
    assert events['items'][1]['id']==returned and not events['items'][1]['canReverse']
    assert set(events['items'][0])=={'id','acquisitionId','actor','kind','deltaQty','occurredOn','reason','reversesId','createdAt','canReverse'}
    with connection(app) as con:
        assert [tuple(r) for r in con.execute('SELECT id,kind,data,revision FROM entities')]==before
        assert [tuple(r) for r in con.execute('SELECT * FROM settings ORDER BY id') if r['id']!='meta']==financial
        assert con.execute('SELECT count(*) FROM hub_transactions').fetchone()[0]==0
        assert con.execute('SELECT count(*) FROM inventory_source_links').fetchone()[0]==0


def test_shared_acl_batch_capabilities_revoke_all_reads_receipts_and_writes(app):
    c,h = login(app);other,oh = login(app,2)
    original,_ = create(c,h)
    uid = original['item']['id']
    assert other.get(P+'/items').json['total']==0
    assert other.get(P+'/items/'+uid).status_code==404
    shared = c.patch(P+'/items/'+uid,headers=h,json={'requestId':rid(),'revision':1,'patch':{'visibility':'shared'}}).json
    current,_ = acquisition(c,h,shared['item'])
    lot = current['acquisition']['id']
    detail = other.get(P+'/acquisitions/'+lot).json
    assert not detail['item']['canManage'] and not detail['acquisition']['canEditAllFields']
    assert set(detail['acquisition']['editableFields'])=={'orderState','expectedOn','afterSalesState','note'}
    current,receipt = move(other,oh,current,quantity=2)
    rejected = other.patch(P+'/acquisitions/'+lot,headers=oh,json={'requestId':rid(),'itemRevision':current['item']['revision'],
        'revision':current['acquisition']['revision'],'patch':{'orderedQty':8}})
    assert rejected.status_code==403
    assert other.patch(P+'/items/'+uid,headers=oh,json={'requestId':rid(),'revision':current['item']['revision'],'patch':{'title':'不应改名'}}).status_code==403
    private = c.patch(P+'/items/'+uid,headers=h,json={'requestId':rid(),'revision':current['item']['revision'],'patch':{'visibility':'private'}})
    assert private.status_code==200
    for endpoint in [P+'/items/'+uid,P+'/items/'+uid+'/acquisitions',P+'/acquisitions/'+lot,
        P+'/acquisitions/'+lot+'/movements',P+'/operations/'+receipt['requestId']]:
        assert other.get(endpoint).status_code==404,endpoint
    assert other.get(P+'/items?scope=shared').json['total']==0
    assert other.post(P+'/acquisitions/'+lot+'/movements',headers=oh,json=receipt).status_code==404


def test_current_household_routing_and_foreign_ids_never_cross(app):
    c,h = login(app)
    item,value = create(c,h,visibility='shared')
    invitation = c.post('/api/spaces/invitations',headers=h,json={}).json['invitation']
    created = c.post('/api/spaces/redeem',headers=h,json={'name':'合成第二家庭','slug':'inventory-synthetic-two',
        'invitation':invitation,'MEMBER1_PASSWORD':PASSWORD,'MEMBER2_PASSWORD':PASSWORD})
    assert created.status_code==201
    child = app.test_client()
    assert child.get(created.json['entry']).status_code==303
    child,ch = login(app,client=child)
    assert child.get(P+'/items').json['total']==0
    assert child.get(P+'/items/'+item['item']['id']).status_code==404
    assert child.get(P+'/operations/'+value['requestId']).status_code==404
    other,_ = create(child,ch,visibility='shared',title='另一家庭库存')
    assert c.get(P+'/items/'+other['item']['id']).status_code==404
    assert child.patch(P+'/items/'+item['item']['id'],headers=ch,json={'requestId':rid(),'revision':1,'patch':{'title':'不应跨户'}}).status_code==404
    assert c.get(P+'/items').json['total']==child.get(P+'/items').json['total']==1


def test_list_acl_search_literal_wildcards_and_pagination(app):
    c,h = login(app);other,oh = login(app,2)
    create(c,h,title='PRIVATE_NEVER_COUNT')
    create(other,oh,title='AA_100%',visibility='shared')
    create(other,oh,title='AAx100z',visibility='shared')
    assert other.get(P+'/items?q=PRIVATE_NEVER_COUNT').json['total']==0
    assert c.get(P+'/items?scope=mine').json['total']==1
    assert c.get(P+'/items?scope=shared').json['total']==2
    assert c.get(P+'/items?q=AA_100%25').json['total']==1
    first = c.get(P+'/items?limit=2').json
    assert first['total']==3 and first['nextOffset']==2
    last = c.get(P+'/items?limit=2&offset=2').json
    assert len(last['items'])==1 and last['nextOffset'] is None
    assert [x['id'] for x in first['items']+last['items']]==sorted(x['id'] for x in first['items']+last['items'])
    assert c.get(P+'/items?offset=100000').json['items']==[]


@pytest.mark.parametrize('query',['limit=0','limit=101','limit=true','limit=1.0','offset=-1','offset=100001',
    'limit=1&limit=2','owner=member2','scope=private','q='+('a'*101),'q=%00'])
def test_bad_queries_rejected(app,query):
    c,_ = login(app)
    assert c.get(P+'/items?'+query).status_code==400


@pytest.mark.parametrize('value',[
    {},{'requestId':'short','data':{'title':'x','unit':'u'}},
    {'requestId':'a'*32,'data':{'title':'x','unit':'u'},'owner':'member2'},
    {'requestId':'a'*32,'data':{'title':'x','unit':'u','onHandQty':5}},
    {'requestId':'a'*32,'data':[]},{'requestId':'a'*32,'data':{}},
    {'requestId':'a'*32,'data':{'title':'x','unit':'u','reorderPoint':True}},
])
def test_strict_create_envelopes(app,value):
    c,h = login(app)
    assert c.post(P+'/items',json=value,headers=h).status_code==400
    assert counts(app)['inventory_operations']==0


@pytest.mark.parametrize('raw',['null','[]','{"requestId":"a","requestId":"b","data":{}}',
    '{"requestId":"'+('a'*32)+'","data":{"title":"x","unit":"u","reorderPoint":NaN}}','x'*17000],
    ids=['null-root','array-root','duplicate-keys','nonfinite-number','oversized-payload'])
def test_json_limits_duplicates_and_nonfinite(app,raw):
    c,h = login(app)
    assert c.post(P+'/items',data=raw,headers=h,content_type='application/json').status_code==400


@pytest.mark.parametrize('kind',list(api.CONFIRM))
@pytest.mark.parametrize('confirmation',[False,1,'true',None])
def test_each_movement_requires_its_exact_true_confirmation(app,kind,confirmation):
    c,h = login(app);item,_ = create(c,h);current,_ = acquisition(c,h,item['item'])
    value = {'requestId':rid(),'itemRevision':current['item']['revision'],'revision':1,
        'data':{'kind':kind,'quantity':1,'occurredOn':'2026-09-16','reason':'合成'},api.CONFIRM[kind]:confirmation}
    response = c.post(P+'/acquisitions/'+current['acquisition']['id']+'/movements',json=value,headers=h)
    assert response.status_code==400 and response.json['code']=='confirmation_required'
    assert counts(app)['inventory_movements']==0


def test_wrong_confirmation_unknown_kind_and_numeric_bool(app):
    c,h = login(app);item,_ = create(c,h);current,_ = acquisition(c,h,item['item'])
    endpoint = P+'/acquisitions/'+current['acquisition']['id']+'/movements'
    value = {'requestId':rid(),'itemRevision':2,'revision':1,
        'data':{'kind':'receive','quantity':1,'occurredOn':'2026-09-16'},'confirmReceived':True}
    for patch in [{'confirmReturned':True},{'revision':True},{'itemRevision':2.0},
                  {'data':value['data']|{'kind':[]}},{'data':value['data']|{'quantity':True}}]:
        assert c.post(endpoint,json=value|patch,headers=h).status_code==400


def test_opening_dispose_adjust_and_archive_tombstone(app):
    c,h = login(app);item,value = create(c,h)
    current,_ = acquisition(c,h,item['item'],kind='opening',orderState='closed',orderedQty=4)
    current,_ = move(c,h,current,quantity=4)
    current,_ = move(c,h,current,'dispose',1)
    current,_ = move(c,h,current,'adjust',-3)
    assert current['item']['onHandQty']==0 and current['acquisition']['receivedQty']==4
    target = P+'/items/'+item['item']['id']
    request = {'requestId':rid(),'revision':current['item']['revision'],'confirmArchive':True}
    response = c.delete(target,json=request,headers=h)
    assert response.status_code==200 and response.json['operation']['deleted']
    assert set(response.json)=={'operation'}
    before=counts(app)
    for endpoint in [target,P+'/operations/'+request['requestId'],P+'/operations/'+value['requestId']]:
        assert c.get(endpoint).status_code==410
    assert c.delete(target,json=request,headers=h).status_code==410
    assert counts(app)==before and c.get(P+'/items').json['total']==0


def test_receipt_before_mutable_shopping_dependency_and_source_unlink_revision(app):
    c,h = login(app);item,_ = create(c,h)
    shopping = c.post('/api/items/shopping',headers=h,json={'title':'合成购物'}).json
    current,value = acquisition(c,h,item['item'],shoppingId=shopping['id'])
    assert c.delete('/api/items/shopping/'+shopping['id'],headers=h,json={'revision':1}).status_code==200
    response = c.post(P+'/items/'+item['item']['id']+'/acquisitions',headers=h,json=value)
    assert response.status_code==200 and response.json['operation']['replayed']
    assert response.json['operation']['acquisitionRevision']==1
    assert response.json['acquisition']['revision']==2 and response.json['item']['revision']==3
    assert response.json['acquisition']['shoppingId'] is None
    _,mutation = move(c,h,response.json)
    changed = value|{'data':value['data']|{'orderedQty':7}}
    assert c.post(P+'/items/'+item['item']['id']+'/acquisitions',headers=h,json=changed).json['code']=='request_conflict'


def test_shopping_association_rejects_missing_foreign_kind_and_finance_fields(app):
    c,h = login(app);item,_ = create(c,h)
    task=c.post('/api/items/tasks',json={'title':'合成待办'},headers=h).json
    for sid in ['a'*24,task['id']]:
        value={'requestId':rid(),'itemRevision':1,'data':{'orderedQty':1,'shoppingId':sid}}
        assert c.post(P+'/items/'+item['item']['id']+'/acquisitions',json=value,headers=h).status_code==404
    value={'requestId':rid(),'itemRevision':1,'data':{'orderedQty':1,'paymentId':'private'}}
    assert c.post(P+'/items/'+item['item']['id']+'/acquisitions',json=value,headers=h).status_code==400


def test_two_connections_same_revision_or_requestid_single_effect(app):
    c,h = login(app);item,_ = create(c,h);current,_ = acquisition(c,h,item['item'])
    endpoint=P+'/acquisitions/'+current['acquisition']['id']+'/movements'
    original={'requestId':rid(),'itemRevision':2,'revision':1,
        'data':{'kind':'receive','quantity':1,'occurredOn':'2026-09-16'},'confirmReceived':True}
    for same in (True,False):
        state=c.get(P+'/acquisitions/'+current['acquisition']['id']).json
        value=original|{'requestId':rid(),'itemRevision':state['item']['revision'],'revision':state['acquisition']['revision']}
        payloads=[value,value if same else value|{'requestId':rid()}]
        clients=[clone(app,c),clone(app,c)];gate=threading.Barrier(2)
        before=counts(app)
        def write(pair):
            client,payload=pair;gate.wait(timeout=5)
            return client.post(endpoint,json=payload,headers=h)
        with ThreadPoolExecutor(2) as pool:
            results=list(pool.map(write,zip(clients,payloads)))
        assert sorted(r.status_code for r in results)==([200,200] if same else [200,409])
        if same:
            assert sorted(r.json['operation']['replayed'] for r in results)==[False,True]
        after=counts(app)
        for key in ('inventory_movements','inventory_operations','audit','meta'):
            assert after[key]==before[key]+1


def test_audit_failure_rolls_back_receipt_state_and_safe_error(app):
    captured=[]
    @app.errorhandler(api.InventoryAPIError)
    def safe(error):
        captured.append(error)
        return jsonify(error=error.message,code=error.code),error.status
    c,h = login(app)
    with connection(app) as con:
        con.execute("CREATE TRIGGER reject_inventory_audit BEFORE INSERT ON audit WHEN NEW.action LIKE 'inventory.%' BEGIN SELECT RAISE(ABORT,'SYNTHETIC_PRIVATE_SQL_DETAIL'); END")
    before=counts(app)
    response=c.post(P+'/items',headers=h,json={'requestId':rid(),'data':{'title':'合成','unit':'件'}})
    assert response.status_code==503 and response.json['code']=='storage'
    assert 'SYNTHETIC_PRIVATE_SQL_DETAIL' not in response.get_data(as_text=True)
    assert counts(app)==before
    assert captured[0].__context__ is None and captured[0].__cause__ is None


def test_explicit_member_tv_csrf_origin_guard_for_every_route(app):
    c,h=login(app);item,_=create(c,h);current,_=acquisition(c,h,item['item'])
    tv=app.test_client();pair=tv.post('/api/pair/start',json={}).json
    assert c.post('/api/pair/approve',json={'code':pair['code'],'name':'合成电视'},headers=h).status_code==200
    assert tv.post('/api/pair/poll',json={'secret':pair['secret']}).json['approved']
    uid,lot=item['item']['id'],current['acquisition']['id']
    reads=[P+'/items',P+'/items?owner=member2',P+'/items/'+uid,P+'/items/'+uid+'/acquisitions',
        P+'/acquisitions/'+lot,P+'/acquisitions/'+lot+'/movements',P+'/operations/'+rid()]
    for endpoint in reads:
        assert tv.get(endpoint).status_code==403
        assert app.test_client().get(endpoint).status_code==401
    writes=[('post',P+'/items'),('patch',P+'/items/'+uid),('delete',P+'/items/'+uid),
        ('post',P+'/items/'+uid+'/acquisitions'),('patch',P+'/acquisitions/'+lot),
        ('post',P+'/acquisitions/'+lot+'/movements'),('post',P+'/acquisitions/'+lot+'/movements/'+'a'*24+'/reverse')]
    for method,endpoint in writes:
        assert getattr(tv,method)(endpoint,json={},headers=h).status_code==403
    value={'requestId':rid(),'data':{'title':'x','unit':'u'}}
    assert c.post(P+'/items',json=value).status_code==403
    assert c.post(P+'/items',json=value,headers=h|{'Origin':'https://evil.invalid'}).status_code==403
    assert c.post(P+'/items',data='{}',headers=h).status_code==415


@pytest.mark.parametrize('fault',['revoke','household','owner','missing_engine'])
def test_current_session_checked_after_initial_guard(app,fault):
    @app.before_request
    def mutate():
        if not request.headers.get('X-Synthetic-Fault'):
            return
        if fault=='revoke':
            with connection(app) as con:
                con.execute('UPDATE member_sessions SET revoked_at=1')
        elif fault=='household':
            g.actor['householdId']='b'*24
        elif fault=='owner':
            g.actor['id']='member2'
        else:
            # The global SQL guard validates the captured request before this
            # adapter runs. Keep its indexed engine access real; simulate only
            # the inventory adapter's optional dependency lookup being absent.
            # This does not claim a globally missing engine returns HTTP 503.
            class MissingInventoryEngine(dict):
                def get(self, key, default=None):
                    return None if key=='member_sessions' else super().get(key,default)
            app.extensions = MissingInventoryEngine(app.extensions)
    c,h=login(app)
    response=c.post(P+'/items',headers=h|{'X-Synthetic-Fault':'1'},json={'requestId':rid(),'data':{'title':'x','unit':'u'}})
    assert response.status_code==(503 if fault=='missing_engine' else 401)
    assert counts(app)['inventory_items']==0


def test_batch_edit_capabilities_and_positive_actual_http_update(app):
    c,h=login(app);other,oh=login(app,2)
    item,_=create(c,h,visibility='shared')
    current,_=acquisition(other,oh,item['item'])
    uid=current['acquisition']['id']
    assert current['acquisition']['canEditAllFields'] and current['acquisition']['canManageSources']
    owner=c.get(P+'/acquisitions/'+uid).json
    assert owner['acquisition']['canEditAllFields'] and not owner['acquisition']['canManageSources']
    value={'requestId':rid(),'itemRevision':2,'revision':1,'patch':{'orderedQty':8,'warrantyUntil':'2027-09-16','orderState':'ordered'}}
    updated=c.patch(P+'/acquisitions/'+uid,json=value,headers=h)
    assert updated.status_code==200 and updated.json['acquisition']['orderedQty']==8
    assert updated.json['item']['inTransitQty']==8 and updated.json['item']['revision']==3
    before=counts(app)
    assert c.patch(P+'/acquisitions/'+uid,json=value,headers=h).json['operation']['replayed']
    assert counts(app)==before
    assert c.patch(P+'/acquisitions/'+uid,json=value|{'requestId':rid(),'patch':{'kind':'opening'}},headers=h).status_code==400
    assert c.get(P+'/items/'+item['item']['id']+'/acquisitions?limit=1').json['total']==1


@pytest.mark.parametrize('kind,quantity,expected',[('receive',7,'quantity'),('consume',1,'quantity'),
    ('return',1,'quantity'),('adjust',-1,'quantity'),('receive',0,'invalid'),('receive',1.5,'invalid')])
def test_domain_errors_map_without_partial_receipt_or_audit(app,kind,quantity,expected):
    c,h=login(app);item,_=create(c,h);current,_=acquisition(c,h,item['item'])
    before=counts(app)
    value={'requestId':rid(),'itemRevision':2,'revision':1,'data':{'kind':kind,'quantity':quantity,
        'occurredOn':'2026-09-16','reason':'合成边界'},api.CONFIRM[kind]:True}
    result=c.post(P+'/acquisitions/'+current['acquisition']['id']+'/movements',json=value,headers=h)
    assert result.status_code==(400 if expected=='invalid' else 409) and result.json['code']==expected
    assert counts(app)==before


def test_reverse_archive_require_confirmation_and_reject_repeated_reversal(app):
    c,h=login(app);item,_=create(c,h);current,_=acquisition(c,h,item['item'])
    current,_=move(c,h,current,quantity=1)
    movement=current['operation']['movementId']
    endpoint=P+'/acquisitions/'+current['acquisition']['id']+'/movements/'+movement+'/reverse'
    value={'requestId':rid(),'itemRevision':3,'revision':2,'data':{'occurredOn':'2026-09-16','reason':'明确反转'},'confirmReversal':False}
    assert c.post(endpoint,json=value,headers=h).json['code']=='confirmation_required'
    value['confirmReversal']=True
    reversed=c.post(endpoint,json=value,headers=h)
    assert reversed.status_code==200 and reversed.json['item']['onHandQty']==0
    assert c.post(endpoint,json=value,headers=h).json['operation']['replayed']
    assert c.post(endpoint,json=value|{'requestId':rid(),'itemRevision':4,'revision':3},headers=h).json['code']=='conflict'
    archived={'requestId':rid(),'revision':4,'confirmArchive':False}
    assert c.delete(P+'/items/'+item['item']['id'],json=archived,headers=h).json['code']=='confirmation_required'
    archived['confirmArchive']=True
    assert c.delete(P+'/items/'+item['item']['id'],json=archived,headers=h).json['code']=='conflict'


def test_operation_is_only_current_actor_and_safe_projection(app):
    c,h=login(app);other,oh=login(app,2)
    result,value=create(c,h,visibility='shared')
    assert other.get(P+'/operations/'+value['requestId']).status_code==404
    assert other.get(P+'/items/'+result['item']['id']).status_code==200
    assert set(c.get(P+'/operations/'+value['requestId']).json)=={'operation','item'}
    for endpoint in [P+'/operations/short',P+'/items/bad',P+'/acquisitions/bad']:
        assert c.get(endpoint).status_code==400
    assert c.get(P+'/operations/'+value['requestId']+'?extra=x').status_code==400
