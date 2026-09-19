"""Real Flask sessions and SQLite transactions; synthetic local tasks, no cloud."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import threading

from flask import g, request
import pytest

from test_inventory_api import app, factory, offline, acquisition, counts, create, move, rid
from test_journey_documents import PASSWORD, clone, connection, login


P = '/api/inventory'
TABLES = ('entities','inventory_items','inventory_acquisitions','inventory_operations',
          'inventory_movements','inventory_source_links','audit','settings','private_finance','hub_transactions')


def snapshot(app):
    with closing(connection(app)) as con:
        return {table:[tuple(row) for row in con.execute('SELECT * FROM '+table+' ORDER BY rowid')]
                for table in TABLES}


def setup(c, h, *, shared=False, **lot):
    item,_ = create(c,h,title='PRIVATE_ITEM_NOT_TASK_TEXT',visibility='shared' if shared else 'private')
    current,_ = acquisition(c,h,item['item'],afterSalesState='open',note='PRIVATE_ACQUISITION_NOTE',**lot)
    return current


def endpoint(current):
    return P+'/acquisitions/'+current['acquisition']['id']+'/followup'


def payload(current, **data):
    return dict(requestId=rid(),itemRevision=current['item']['revision'],
                revision=current['acquisition']['revision'],data={'title':'明确售后跟进',**data})


def changed(c, h, current, **patch):
    response = c.patch(P+'/acquisitions/'+current['acquisition']['id'],headers=h,json={
        'requestId':rid(),'itemRevision':current['item']['revision'],
        'revision':current['acquisition']['revision'],'patch':patch})
    assert response.status_code==200,response.json
    return response.json


def test_explicit_local_task_current_projection_audit_and_sentinels(app,monkeypatch,factory):
    c,h = login(app); other,oh = login(app,2)
    def forbidden_cloud(*args,**kwargs):
        pytest.fail('Followup must not dispatch through cloud task_write')
    monkeypatch.setattr(app.extensions['cloud_accounts'],'task_write',forbidden_cloud)
    shopping = c.post('/api/items/shopping',headers=h,json={
        'title':'SYNTHETIC_SHOPPING','budget':4200,'actual':3100,'quantity':'两盒','done':False}).json
    current = setup(c,h,shared=True,shoppingId=shopping['id'])
    current,_ = move(c,h,current,quantity=2)
    with closing(connection(app)) as con,con:
        con.execute("UPDATE private_finance SET data=? WHERE owner='member1'",('{"synthetic":"PRIVATE_FINANCE"}',))
        schema = [tuple(row) for row in con.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name')]
    before = snapshot(app); before_counts = counts(app)
    assert c.get(endpoint(current)).json==dict(itemId=current['item']['id'],
        acquisitionId=current['acquisition']['id'],state='none',task=None)
    value = payload(current,title='  联系售后  ',owner='member2',due='2026-10-02',note='  仅明确填写的内容  ')
    response = c.post(endpoint(current),headers=h,json=value)
    assert response.status_code==201,response.json
    result = response.json; task_id = result['operation']['entityId']
    assert not result['operation']['replayed']
    assert result['item']['revision']==current['item']['revision']+1
    assert result['acquisition']['revision']==current['acquisition']['revision']+1
    for part,keys in [('item',('onHandQty','inTransitQty','plannedQty','belowThreshold')),
                      ('acquisition',('orderedQty','receivedQty','returnedQty','onHandQty',
                       'remainingExpectedQty','fulfillmentState','orderState','afterSalesState','shoppingId'))]:
        assert {k:result[part][k] for k in keys}=={k:current[part][k] for k in keys}
    projection = c.get(endpoint(current))
    assert projection.headers['Cache-Control']=='no-store'
    assert projection.json==dict(itemId=current['item']['id'],acquisitionId=current['acquisition']['id'],
        state='linked',task=dict(id=task_id,revision=1,title='联系售后',owner='member2',due='2026-10-02',
                                 done=False,note='仅明确填写的内容'))
    assert other.get(endpoint(current)).json==projection.json
    assert other.get(P+'/operations/'+value['requestId']).status_code==404
    assert c.get(P+'/operations/'+value['requestId']).json==result|{'operation':result['operation']|{'replayed':True}}
    after = snapshot(app)
    assert [row for row in after['entities'] if row[0]!=task_id]==before['entities']
    for table in ('inventory_movements','inventory_source_links','private_finance','hub_transactions'):
        assert after[table]==before[table]
    assert [row for row in after['settings'] if row[0]!='meta']==[row for row in before['settings'] if row[0]!='meta']
    for key in ('inventory_operations','audit','meta'):
        assert counts(app)[key]==before_counts[key]+1
    with closing(connection(app)) as con:
        task = json.loads(con.execute('SELECT data FROM entities WHERE id=?',(task_id,)).fetchone()[0])
        assert task==dict(title='联系售后',owner='member2',due='2026-10-02',done=False,note='仅明确填写的内容',tripId='')
        assert con.execute('SELECT action FROM audit ORDER BY id DESC LIMIT 1').fetchone()[0]=='inventory.create_followup'
        assert [tuple(row) for row in con.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name')]==schema
    edited = other.patch('/api/items/tasks/'+task_id,headers=oh,json={
        'revision':1,'title':'已联系并等待答复','done':True})
    assert edited.status_code==200,edited.json
    latest = c.get(endpoint(current)).json
    assert latest['task']['revision']==2 and latest['task']['done'] and latest['task']['title']=='已联系并等待答复'
    restarted = factory(dict(app.config))
    assert clone(restarted,c).get(endpoint(current)).json==latest


def test_original_key_replays_before_status_assignee_capacity_and_deleted_task(app):
    c,h = login(app); current = setup(c,h)
    value = payload(current,owner='member2')
    created = c.post(endpoint(current),headers=h,json=value)
    assert created.status_code==201,created.json
    task_id = created.json['operation']['entityId']
    current = changed(c,h,created.json,afterSalesState='closed')
    assert c.get(endpoint(current)).json['state']=='linked'
    assert c.delete('/api/items/tasks/'+task_id,headers=h,json={'revision':1}).status_code==200
    with closing(connection(app)) as con,con:
        con.execute("UPDATE household_memberships SET state='removed',revision=revision+1 WHERE member_id='member2'")
        con.executemany("INSERT INTO entities(id,kind,data,updated_at) VALUES(?,'tasks',?,?)",
            [(format(i,'024x'),json.dumps(dict(title='合成容量',owner='shared',due='',done=False,note='',tripId='')),
              '2026-09-18T00:00:00+00:00') for i in range(2500)])
    before = snapshot(app)
    replay = c.post(endpoint(current),headers=h,json=value)
    assert replay.status_code==200 and replay.json['operation']==created.json['operation']|{'replayed':True}
    assert replay.json['acquisition']['afterSalesState']=='closed'
    assert snapshot(app)==before
    assert c.get(endpoint(current)).json==dict(itemId=current['item']['id'],
        acquisitionId=current['acquisition']['id'],state='deleted',task=None)
    receipt = c.get(P+'/operations/'+value['requestId'])
    assert receipt.status_code==200 and receipt.json['operation']['entityId']==task_id
    assert c.post(endpoint(current),headers=h,json=value|{'data':{'title':'不同意图'}}).json['code']=='request_conflict'
    reopened = changed(c,h,current,afterSalesState='open')
    before = snapshot(app)
    duplicate = c.post(endpoint(current),headers=h,json=payload(reopened))
    assert duplicate.status_code==409 and duplicate.json['code']=='conflict'
    assert snapshot(app)==before and c.get(endpoint(current)).json['state']=='deleted'


@pytest.mark.parametrize('mode',['same_actor_same_key','other_actor_new_key','other_actor_same_key'])
def test_concurrent_connections_single_task_and_cross_member_uniqueness(app,mode):
    c,h = login(app); other,oh = login(app,2); current = setup(c,h,shared=True)
    value = payload(current)
    second = value if mode!='other_actor_new_key' else value|{'requestId':rid()}
    clients = [(clone(app,c),h,value),
               (clone(app,c),h,second) if mode=='same_actor_same_key' else (clone(app,other),oh,second)]
    gate = threading.Barrier(2); before = counts(app)
    def write(args):
        client,headers,data = args
        gate.wait(timeout=10)
        return client.post(endpoint(current),headers=headers,json=data)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(write,clients))
    assert sorted(r.status_code for r in results)==([200,201] if mode=='same_actor_same_key' else [201,409])
    successful = next(r.json for r in results if r.status_code==201)
    for key in ('inventory_operations','audit','meta'):
        assert counts(app)[key]==before[key]+1
    with closing(connection(app)) as con:
        assert con.execute("SELECT count(*) FROM entities WHERE kind='tasks'").fetchone()[0]==1
    assert c.get(endpoint(current)).json==other.get(endpoint(current)).json
    # Fresh CAS values and a different actor/key must still see the durable link.
    before_all = snapshot(app)
    rejected = other.post(endpoint(current),headers=oh,json=payload(successful,title='另一人重复创建'))
    assert rejected.status_code==409 and rejected.json['code']=='conflict'
    assert snapshot(app)==before_all


def test_private_shared_revoke_replay_and_household_task_visibility(app):
    c,h = login(app); other,oh = login(app,2); current = setup(c,h)
    value = payload(current)
    before = snapshot(app)
    assert other.get(endpoint(current)).status_code==404
    assert other.post(endpoint(current),headers=oh,json=value).status_code==404
    assert snapshot(app)==before
    shared = c.patch(P+'/items/'+current['item']['id'],headers=h,json={
        'requestId':rid(),'revision':current['item']['revision'],'patch':{'visibility':'shared'}})
    assert shared.status_code==200
    current['item'] = shared.json['item']; value = payload(current,owner='member1')
    made = other.post(endpoint(current),headers=oh,json=value)
    assert made.status_code==201,made.json
    task_id = made.json['operation']['entityId']
    assert c.get(endpoint(current)).json['task']['id']==task_id
    assert c.get(P+'/operations/'+value['requestId']).status_code==404
    private = c.patch(P+'/items/'+current['item']['id'],headers=h,json={
        'requestId':rid(),'revision':made.json['item']['revision'],'patch':{'visibility':'private'}})
    assert private.status_code==200
    before = snapshot(app)
    assert other.get(endpoint(current)).status_code==404
    assert other.post(endpoint(current),headers=oh,json=value).status_code==404
    assert other.get(P+'/operations/'+value['requestId']).status_code==404
    assert snapshot(app)==before
    # The explicitly created household task is shared; owner is an assignee.
    tasks = other.get('/api/state').json['tasks']
    task = next(t for t in tasks if t['id']==task_id)
    assert task['title']=='明确售后跟进' and 'PRIVATE_' not in json.dumps(task)


def test_archived_inventory_hides_link_but_preserves_task(app):
    c,h = login(app); current = setup(c,h,orderState='closed')
    value = payload(current); made = c.post(endpoint(current),headers=h,json=value)
    assert made.status_code==201
    archived = c.delete(P+'/items/'+current['item']['id'],headers=h,json={
        'requestId':rid(),'revision':made.json['item']['revision'],'confirmArchive':True})
    assert archived.status_code==200,archived.json
    before = snapshot(app)
    assert c.get(endpoint(current)).status_code==410
    assert c.post(endpoint(current),headers=h,json=value).status_code==410
    assert snapshot(app)==before
    assert any(t['id']==made.json['operation']['entityId'] for t in c.get('/api/state').json['tasks'])


@pytest.mark.parametrize('state',['none','closed'])
def test_first_creation_requires_open_after_sales(app,state):
    c,h = login(app); current = setup(c,h); current = changed(c,h,current,afterSalesState=state)
    before = snapshot(app)
    response = c.post(endpoint(current),headers=h,json=payload(current))
    assert response.status_code==409 and response.json['code']=='conflict'
    assert snapshot(app)==before and c.get(endpoint(current)).json['state']=='none'


@pytest.mark.parametrize('version',['itemRevision','revision'])
def test_both_inventory_revisions_are_checked(app,version):
    c,h = login(app); current = setup(c,h); value = payload(current)
    value[version] += 1
    before = snapshot(app)
    response = c.post(endpoint(current),headers=h,json=value)
    assert response.status_code==409 and response.json['code']=='conflict'
    assert snapshot(app)==before


@pytest.mark.parametrize('data',[
    {'title':''},{'title':'x'*101},{'title':True},{'title':'售后','owner':'not-a-member'},
    {'title':'售后','due':'2026-02-30'},{'title':'售后','due':False},
    {'title':'售后','note':'x'*501},{'title':'售后','done':True},
    {'title':'售后','sourceId':'cloud'},{'title':'售后','tripId':''},
    {'title':'售后','sync':{}},{'title':'售后','entityId':'a'*24},
    {'owner':'shared'}])
def test_explicit_task_validation_rejects_invalid_or_hidden_fields_atomically(app,data):
    c,h = login(app); current = setup(c,h); before = snapshot(app)
    response = c.post(endpoint(current),headers=h,json=payload(current)|{'data':data})
    assert response.status_code==400 and response.json['code']=='invalid',response.json
    assert snapshot(app)==before


def test_inactive_assignee_rejected_without_half_write(app):
    c,h = login(app); current = setup(c,h)
    with closing(connection(app)) as con,con:
        con.execute("UPDATE household_memberships SET state='removed',revision=revision+1 WHERE member_id='member2'")
    before = snapshot(app)
    response = c.post(endpoint(current),headers=h,json=payload(current,owner='member2'))
    assert response.status_code==400 and response.json['code']=='invalid'
    assert snapshot(app)==before


def test_task_capacity_rejected_without_inventory_changes(app):
    c,h = login(app); current = setup(c,h)
    with closing(connection(app)) as con,con:
        con.executemany("INSERT INTO entities(id,kind,data,updated_at) VALUES(?,'tasks','{}','synthetic')",
                        [(format(i,'024x'),) for i in range(2500)])
    before = snapshot(app)
    response = c.post(endpoint(current),headers=h,json=payload(current))
    assert response.status_code==409 and response.json['code']=='capacity'
    assert snapshot(app)==before


@pytest.mark.parametrize('table,event,expected',[
    ('entities','INSERT',409),('inventory_items','UPDATE',409),
    ('inventory_acquisitions','UPDATE',409),('inventory_operations','INSERT',409),
    ('audit','INSERT',503),('settings','UPDATE',503)])
def test_each_write_boundary_failure_rolls_back_task_receipt_versions_and_audit(app,table,event,expected):
    c,h = login(app); current = setup(c,h); value = payload(current)
    with closing(connection(app)) as con,con:
        con.execute(f"CREATE TRIGGER synthetic_followup_failure BEFORE {event} ON {table} "
                    "BEGIN SELECT RAISE(ABORT,'PRIVATE_SYNTHETIC_SQL_FAILURE'); END")
    before = snapshot(app)
    response = c.post(endpoint(current),headers=h,json=value)
    assert response.status_code==expected,response.json
    assert 'PRIVATE_SYNTHETIC_SQL_FAILURE' not in response.get_data(as_text=True)
    assert snapshot(app)==before
    with closing(connection(app)) as con,con:
        con.execute('DROP TRIGGER synthetic_followup_failure')
    retry = c.post(endpoint(current),headers=h,json=value)
    assert retry.status_code==201 and not retry.json['operation']['replayed'],retry.json


@pytest.mark.parametrize('fault',['revoked','removed','auth_version','household','actor'])
@pytest.mark.parametrize('method',['get','post'])
def test_current_identity_rechecked_inside_followup_transaction(app,fault,method):
    @app.before_request
    def after_initial_guard():
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
        else:
            g.actor['householdId' if fault=='household' else 'id'] = 'b'*24 if fault=='household' else 'member2'
    c,h = login(app); current = setup(c,h); value = payload(current)
    made = c.post(endpoint(current),headers=h,json=value)
    assert made.status_code==201
    before = snapshot(app)
    response = getattr(c,method)(endpoint(current),headers=h|{'X-Synthetic-Fault':'1'},
                                **({'json':value} if method=='post' else {}))
    assert response.status_code==401,response.json
    assert snapshot(app)==before


def test_followup_auth_tv_csrf_origin_and_strict_routes(app):
    c,h = login(app); current = setup(c,h); value = payload(current)
    tv = app.test_client(); pair = tv.post('/api/pair/start',json={}).json
    assert c.post('/api/pair/approve',json={'code':pair['code'],'name':'合成电视'},headers=h).status_code==200
    assert tv.post('/api/pair/poll',json={'secret':pair['secret']}).json['approved']
    before = snapshot(app)
    assert app.test_client().get(endpoint(current)).status_code==401
    assert app.test_client().post(endpoint(current),json=value).status_code==401
    assert tv.get(endpoint(current)).status_code==403
    assert tv.post(endpoint(current),json=value,headers=h).status_code==403
    assert c.post(endpoint(current),json=value).status_code==403
    assert c.post(endpoint(current),json=value,headers=h|{'Origin':'https://evil.invalid'}).status_code==403
    for path in (P+'/acquisitions/bad/followup',endpoint(current)+'?extra=1'):
        assert c.get(path).status_code==400
        assert c.post(path,json=value,headers=h).status_code==400
    assert c.get(P+'/acquisitions/'+'f'*24+'/followup').status_code==404
    assert c.post(endpoint(current),json=value|{'owner':'member2'},headers=h).status_code==400
    assert snapshot(app)==before


def test_two_households_never_share_followup_or_receipt(app):
    c,h = login(app); current = setup(c,h,shared=True); value = payload(current)
    assert c.post(endpoint(current),headers=h,json=value).status_code==201
    invitation = c.post('/api/spaces/invitations',headers=h,json={}).json['invitation']
    child = app.test_client()
    response = child.post('/api/spaces/redeem',json={'invitation':invitation,
        'name':'合成售后第二家庭','slug':'inventory-followup-two',
        'MEMBER1_PASSWORD':PASSWORD,'MEMBER2_PASSWORD':PASSWORD})
    assert response.status_code==201,response.json
    assert child.get(response.json['entry']).status_code==303
    child,ch = login(app,client=child)
    assert child.get(endpoint(current)).status_code==404
    assert child.post(endpoint(current),headers=ch,json=value).status_code==404
    assert child.get(P+'/operations/'+value['requestId']).status_code==404
    other = setup(child,ch,shared=True)
    child_value = payload(other)|{'requestId':value['requestId']}
    made = child.post(endpoint(other),headers=ch,json=child_value)
    assert made.status_code==201,made.json
    assert c.get(endpoint(other)).status_code==404
    assert c.post(endpoint(other),headers=h,json=child_value).status_code==404
    child.set_cookie('session',c.get_cookie('session').value)
    assert child.get(endpoint(other)).status_code==401


def test_optional_validator_absence_fails_closed_without_disabling_inventory(app):
    c,h = login(app); current = setup(c,h)
    app.extensions['inventory'].validate = None
    before = snapshot(app)
    response = c.post(endpoint(current),headers=h,json=payload(current))
    assert response.status_code==503 and response.json['code']=='storage'
    assert snapshot(app)==before
    assert c.get(endpoint(current)).json['state']=='none'
    assert c.get(P+'/items/'+current['item']['id']).status_code==200
    create(c,h,title='未注入校验器时仍可登记物品')


def test_separate_acquisitions_of_same_item_can_each_have_one_followup(app):
    c,h = login(app); current = setup(c,h)
    first = c.post(endpoint(current),headers=h,json=payload(current))
    assert first.status_code==201
    next_lot,_ = acquisition(c,h,first.json['item'],afterSalesState='open')
    second = c.post(endpoint(next_lot),headers=h,json=payload(next_lot))
    assert second.status_code==201
    assert first.json['operation']['entityId']!=second.json['operation']['entityId']
    assert c.get(endpoint(current)).json['task']['id']==first.json['operation']['entityId']
    assert c.get(endpoint(next_lot)).json['task']['id']==second.json['operation']['entityId']
