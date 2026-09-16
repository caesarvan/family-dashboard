"""Real temporary SQLite, synthetic records; no Flask or external services."""
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import threading

import pytest

import inventory_core as core


def request_id(number):
    return f'{number:032x}'


def connect(path):
    con = sqlite3.connect(path,timeout=3)
    con.execute('PRAGMA foreign_keys=ON')
    return con


def setup(con):
    con.executescript('''CREATE TABLE users(id TEXT PRIMARY KEY);
      INSERT INTO users VALUES('member1'),('member2');
      CREATE TABLE entities(id TEXT PRIMARY KEY,kind TEXT NOT NULL,data TEXT,revision INTEGER DEFAULT 1);
      CREATE TABLE synthetic_finance(id TEXT PRIMARY KEY,amount_cents INTEGER);
      INSERT INTO synthetic_finance VALUES('payment',10000),('refund',2000);''')
    core.initialize_inventory(con)
    con.execute('BEGIN IMMEDIATE')


@pytest.fixture
def db(tmp_path):
    con = connect(tmp_path/'household.sqlite3')
    setup(con)
    yield con
    con.close()


def item(con, *, shared=False):
    return core.create_item(con,'member1',{'title':'Battery','unit':'piece',
                            'visibility':'shared' if shared else 'private'},request_id(1))


def lot(con, *, shared=False, qty=6, shopping=None, opening=False):
    created = item(con,shared=shared)
    data = {'orderedQty':qty,'orderState':'closed' if opening else 'in_transit',
            'kind':'opening' if opening else 'purchase','shoppingId':shopping}
    return core.create_acquisition(con,'member1',created['itemId'],1,data,request_id(2))


def move(con, current, kind, qty, req=3, actor='member1', reason='Synthetic explicit action'):
    return core.append_movement(con,actor,current['acquisitionId'],current['itemRevision'],
          current['acquisitionRevision'],{'kind':kind,'quantity':qty,'occurredOn':'2026-09-16','reason':reason},request_id(req))


def fail(code, function, *args, **kwargs):
    with pytest.raises(core.InventoryError) as caught:
        function(*args,**kwargs)
    assert caught.value.code==code
    assert caught.value.__context__ is None and caught.value.__cause__ is None


def counts(con):
    return {table:con.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in core.LIMITS}


def test_explicit_initialization_five_tables_idempotent_and_drift_rejected(db):
    assert len(db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name GLOB 'inventory_*'").fetchall())==5
    db.commit()
    core.initialize_inventory(db)
    db.execute('DROP INDEX inventory_sources_line')
    fail('schema',core.initialize_inventory,db)


def test_partial_schema_is_never_silently_repaired(tmp_path):
    con=connect(tmp_path/'partial.db')
    con.execute('CREATE TABLE inventory_items(id TEXT)')
    fail('schema',core.initialize_inventory,con)
    assert len(con.execute("SELECT name FROM sqlite_master WHERE name GLOB 'inventory_*'").fetchall())==1
    con.close()


def test_require_external_transaction_and_actor_is_not_authentication(db):
    db.commit()
    fail('transaction_required',item,db)
    db.execute('BEGIN IMMEDIATE')
    fail('transaction_required',core.create_item,db,'television',{'title':'x','unit':'piece'},request_id(5))
    db.rollback()
    db.execute('PRAGMA foreign_keys=OFF')
    db.execute('BEGIN IMMEDIATE')
    fail('transaction_required',item,db)


@pytest.mark.parametrize('value',[True,False,0,-1,1.5,'1',None,1000001])
def test_quantity_domain_rejects_bool_nonintegers_and_bounds(value):
    fail('invalid',core.normalize_acquisition,{'orderedQty':value})


@pytest.mark.parametrize('data',[
    {'title':'','unit':'piece'}, {'title':'x'*101,'unit':'piece'}, {'title':'x','unit':''},
    {'title':'x','unit':'u'*21}, {'title':'x','unit':'piece','owner':'member2'},
    {'title':'x','unit':'piece','onHandQty':2}, {'title':'x\0','unit':'piece'},
    {'title':'x','unit':'piece','visibility':'public'}, {'title':'x','unit':'piece','reorderPoint':True},
    {'title':'x','unit':'piece','reorderPoint':-1}, {'title':'x','unit':'piece','location':'x'*101}])
def test_item_validation_strict_allowlist(data):
    fail('invalid',core.normalize_item,data)


@pytest.mark.parametrize('patch',[
    {'orderedOn':'2026-02-30'}, {'expectedOn':'2026-1-01'}, {'warrantyUntil':False},
    {'orderedOn':'2026-09-20','expectedOn':'2026-09-19'}, {'shoppingId':'not-an-id'},
    {'kind':'order'}, {'kind':'opening'}, {'orderState':'received'}, {'afterSalesState':'refunded'},
    {'paymentId':'PRIVATE'}, {'note':'x'*501}])
def test_acquisition_validation_dates_kind_and_finance_rejection(patch):
    fail('invalid',core.normalize_acquisition,{'orderedQty':1,**patch})


def test_receipts_partial_receiving_return_and_no_financial_or_shopping_changes(db):
    sid='a'*24
    raw=json.dumps({'done':False,'actual':None,'quantity':'2 boxes x 3 items','photoIds':[]})
    db.execute('INSERT INTO entities VALUES(?,?,?,?)',(sid,'shopping',raw,1))
    finance=list(db.execute('SELECT * FROM synthetic_finance'))
    current=lot(db,shopping=sid)
    first=move(db,current,'receive',4)
    state=core.project_acquisition(db,'member1',current['acquisitionId'])
    assert (state['receivedQty'],state['onHandQty'],state['remainingExpectedQty'],state['fulfillmentState'])==(4,4,2,'partial')
    assert move(db,current,'receive',4)=={**first,'replayed':True}
    second=move(db,first,'receive',2,4)
    returned=move(db,second,'return',1,5)
    state=core.project_acquisition(db,'member1',current['acquisitionId'])
    assert (state['receivedQty'],state['onHandQty'],state['returnedQty'],state['remainingExpectedQty'],state['fulfillmentState'])==(6,5,1,0,'received')
    assert list(db.execute('SELECT * FROM synthetic_finance'))==finance
    assert db.execute('SELECT data,revision FROM entities WHERE id=?',(sid,)).fetchone()==(raw,1)
    assert returned['itemRevision']==5
    assert db.execute('SELECT count(*) FROM inventory_movements').fetchone()[0]==3
    assert core.get_operation(db,'member1',request_id(5))['movementId']==returned['movementId']


def test_unit_and_owner_immutable_after_first_event(db):
    current=move(db,lot(db),'receive',1)
    fail('conflict',core.update_item,db,'member1',current['itemId'],current['itemRevision'],{'unit':'box'},request_id(4))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE inventory_items SET unit='box' WHERE id=?",(current['itemId'],))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE inventory_items SET owner='member2' WHERE id=?",(current['itemId'],))


@pytest.mark.parametrize('kind,qty',[('receive',7),('consume',1),('dispose',1),('return',1),('adjust',-1)])
def test_excess_or_negative_quantity_is_atomic(db,kind,qty):
    current=lot(db)
    before=counts(db)
    fail('quantity',move,db,current,kind,qty)
    assert counts(db)==before
    assert core.project_item(db,'member1',current['itemId'])['revision']==2


@pytest.mark.parametrize('kind,qty',[('receive',True),('consume',False),('return',0),('receive',-1),
                                   ('adjust',0),('adjust',1000001),('receive','2'),('receive',2.0)])
def test_movement_rejects_invalid_quantity_without_receipt(db,kind,qty):
    current=lot(db)
    before=counts(db)
    fail('invalid',move,db,current,kind,qty)
    assert counts(db)==before


def test_reversal_once_and_original_remains(db):
    received=move(db,lot(db),'receive',4)
    reverse=core.reverse_movement(db,'member1',received['acquisitionId'],received['movementId'],
         received['itemRevision'],received['acquisitionRevision'],{'occurredOn':'2026-09-16','reason':'Wrong receipt count'},request_id(4))
    state=core.project_acquisition(db,'member1',received['acquisitionId'])
    assert (state['onHandQty'],state['receivedQty'],state['remainingExpectedQty'])==(0,0,6)
    assert reverse['quantityDelta']==-4
    assert db.execute('SELECT delta_qty FROM inventory_movements WHERE id=?',(received['movementId'],)).fetchone()[0]==4
    for original in (received['movementId'],reverse['movementId']):
        fail('conflict',core.reverse_movement,db,'member1',reverse['acquisitionId'],original,reverse['itemRevision'],reverse['acquisitionRevision'],
             {'occurredOn':'2026-09-16','reason':'Again'},request_id(5))


def test_reverse_receipt_after_consumption_cannot_make_negative(db):
    received=move(db,lot(db),'receive',4)
    consumed=move(db,received,'consume',3,4)
    fail('quantity',core.reverse_movement,db,'member1',consumed['acquisitionId'],received['movementId'],
         consumed['itemRevision'],consumed['acquisitionRevision'],{'occurredOn':'2026-09-16','reason':'Wrong'},request_id(5))
    restored=core.reverse_movement(db,'member1',consumed['acquisitionId'],consumed['movementId'],
         consumed['itemRevision'],consumed['acquisitionRevision'],{'occurredOn':'2026-09-16','reason':'Consumption correction'},request_id(6))
    assert core.quantity_summary(db,'member1',restored['itemId'])['onHandQty']==4


def test_opening_batch_no_order_or_in_transit_and_quantity_is_explicit(db):
    current=lot(db,opening=True)
    assert core.quantity_summary(db,'member1',current['itemId'])=={'onHandQty':0,'inTransitQty':0,'plannedQty':0}
    current=move(db,current,'receive',6)
    assert core.quantity_summary(db,'member1',current['itemId'])['onHandQty']==6


def test_planned_quantity_not_mistaken_for_transit(db):
    first=item(db)
    current=core.create_acquisition(db,'member1',first['itemId'],1,{'orderedQty':3},request_id(2))
    assert core.quantity_summary(db,'member1',first['itemId'])=={'onHandQty':0,'inTransitQty':0,'plannedQty':3}
    current=core.update_acquisition(db,'member1',current['acquisitionId'],2,1,{'orderState':'ordered'},request_id(3))
    assert core.quantity_summary(db,'member1',first['itemId'])['inTransitQty']==3


def test_acl_shared_physical_actions_owner_only_management_and_revocation(db):
    current=lot(db)
    fail('not_found',core.project_item,db,'member2',current['itemId'])
    shared=core.update_item(db,'member1',current['itemId'],2,{'visibility':'shared'},request_id(3))
    current={**current,'itemRevision':shared['itemRevision']}
    received=move(db,current,'receive',1,4,actor='member2')
    assert core.project_item(db,'member2',current['itemId'])['canManage'] is False
    fail('forbidden',core.update_item,db,'member2',current['itemId'],received['itemRevision'],{'visibility':'private'},request_id(5))
    fail('forbidden',core.update_acquisition,db,'member2',current['acquisitionId'],received['itemRevision'],received['acquisitionRevision'],{'orderedQty':10},request_id(5))
    core.update_item(db,'member1',current['itemId'],received['itemRevision'],{'visibility':'private'},request_id(6))
    fail('not_found',move,db,current,'receive',1,4,actor='member2')
    fail('not_found',core.get_operation,db,'member2',request_id(4))
    assert core.export_inventory(db,'member2',True)=={'personal':[],'shared':[],'sources':[],'operations':[]}


def test_other_actor_cannot_read_receipt(db):
    item(db,shared=True)
    fail('not_found',core.get_operation,db,'member2',request_id(1))


def test_revision_and_idempotency_conflict_before_changed_dependency(db):
    current=lot(db)
    first=move(db,current,'receive',1)
    fail('conflict',move,db,current,'receive',1,4)
    fail('request_conflict',move,db,current,'receive',2,3)
    assert move(db,current,'receive',1)=={**first,'replayed':True}


def test_deleted_item_keeps_receipt_and_never_replays_creation(db):
    first=item(db)
    core.archive_item(db,'member1',first['itemId'],1,request_id(2))
    fail('gone',item,db)
    fail('gone',core.get_operation,db,'member1',request_id(1))
    assert counts(db)['inventory_items']==1 and counts(db)['inventory_operations']==2
    assert not core.export_inventory(db,'member1')['personal']
    with pytest.raises(sqlite3.IntegrityError):
        db.execute('UPDATE inventory_items SET deleted_at=NULL')


def test_archive_requires_no_stock_or_open_order(db):
    current=lot(db)
    fail('conflict',core.archive_item,db,'member1',current['itemId'],2,request_id(4))
    received=move(db,current,'receive',1)
    closed=core.update_acquisition(db,'member1',current['acquisitionId'],3,2,{'orderState':'closed'},request_id(5))
    fail('conflict',core.archive_item,db,'member1',current['itemId'],closed['itemRevision'],request_id(6))
    fail('conflict',move,db,closed,'receive',1,7)


def test_shopping_unlink_increments_both_versions_and_retains_history(db):
    sid='b'*24
    db.execute('INSERT INTO entities VALUES(?,?,?,?)',(sid,'shopping','{}',1))
    current=move(db,lot(db,shopping=sid),'receive',2)
    db.execute('DELETE FROM entities WHERE id=?',(sid,))
    after=core.project_acquisition(db,'member1',current['acquisitionId'])
    assert after['shoppingId'] is None and after['revision']==current['acquisitionRevision']+1
    assert core.project_item(db,'member1',current['itemId'])['revision']==current['itemRevision']+1
    assert after['onHandQty']==2
    fail('conflict',move,db,current,'receive',1,4)


@pytest.mark.parametrize('table',['inventory_movements','inventory_operations'])
def test_history_cannot_be_deleted_or_edited_even_by_direct_sql(db,table):
    move(db,lot(db),'receive',1)
    for sql in (f'DELETE FROM {table}',f'UPDATE {table} SET created_at=created_at'):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(sql)


def test_direct_sql_does_not_bypass_negative_stock_or_lot_match(db):
    current=lot(db)
    values=('f'*24,current['itemId'],current['acquisitionId'],'member1','return',-1,'2026-09-16','return',None,request_id(9),'now')
    with pytest.raises(sqlite3.IntegrityError):
        db.execute('INSERT INTO inventory_movements VALUES(?,?,?,?,?,?,?,?,?,?,?)',values)
    assert counts(db)['inventory_movements']==0


def source(con,current,actor='member1',rid='c'*24,order='PRIVATE_ORDER',line='PRIVATE_LINE'):
    con.execute('INSERT INTO inventory_source_links VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
       (rid,actor,current['acquisitionId'],order,line,'d'*64,1,'PRIVATE_SETTLEMENT','active',1,'now','now'))


def test_source_acl_unique_and_shared_export_never_contains_private_identifiers(db):
    current=lot(db,shared=True)
    source(db,current)
    own=core.export_inventory(db,'member1')
    assert own['sources'][0]['orderId']=='PRIVATE_ORDER'
    assert 'PRIVATE_LINE' not in json.dumps(own) and 'payload_digest' not in json.dumps(own)
    shared=core.export_inventory(db,'member2',True)
    assert len(shared['shared'])==1 and not shared['sources'] and not shared['operations']
    assert 'PRIVATE_' not in json.dumps(shared)
    assert 'PRIVATE_' not in json.dumps(core.project_acquisition(db,'member2',current['acquisitionId']))
    with pytest.raises(sqlite3.IntegrityError):
        source(db,current,actor='member2',rid='e'*24)
    with pytest.raises(sqlite3.IntegrityError):
        source(db,current,rid='f'*24)


def test_capacity_counts_tombstones_and_preserves_receipts(db,monkeypatch):
    first=item(db)
    core.archive_item(db,'member1',first['itemId'],1,request_id(2))
    monkeypatch.setitem(core.LIMITS,'inventory_items',1)
    fail('capacity',core.create_item,db,'member1',{'title':'Other','unit':'piece'},request_id(3))
    assert counts(db)['inventory_operations']==2


def test_public_receipt_seam_rolls_back_unsafe_result_and_preserves_outer_transaction(db):
    first=item(db)
    def unsafe():
        db.execute("UPDATE inventory_items SET title='changed'")
        return {'itemId':first['itemId'],'itemRevision':1,'orderId':'PRIVATE'}
    fail('invalid',core.apply_with_receipt,db,'member1',request_id(3),'create_followup',{},unsafe,
         item_id=first['itemId'],item_revision=1)
    assert core.project_item(db,'member1',first['itemId'])['title']=='Battery'
    assert db.in_transaction and counts(db)['inventory_operations']==1


def test_caller_rollback_removes_all_effects(db):
    current=move(db,lot(db),'receive',1)
    db.rollback()
    db.execute('BEGIN IMMEDIATE')
    assert counts(db)=={key:0 for key in core.LIMITS}


def test_two_connections_one_wins_same_revision_and_replay_is_exactly_once(tmp_path):
    path=tmp_path/'race.sqlite3'
    con=connect(path); setup(con); current=lot(con,shared=True); con.commit(); con.close()
    barrier=threading.Barrier(2)
    def worker(actor,req):
        db=connect(path)
        barrier.wait()
        try:
            db.execute('BEGIN IMMEDIATE')
            result=move(db,current,'receive',4,req,actor)
            db.commit()
            return result
        except core.InventoryError as error:
            db.rollback(); return error.code
        finally:
            db.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(worker,'member1',3),pool.submit(worker,'member2',4)]
        results=[f.result() for f in futures]
    assert sum(isinstance(r,dict) for r in results)==1 and 'conflict' in results
    con=connect(path); con.execute('BEGIN IMMEDIATE')
    assert core.project_acquisition(con,'member1',current['acquisitionId'])['onHandQty']==4
    assert counts(con)['inventory_movements']==1
    con.close()


def test_same_actor_concurrent_same_request_returns_one_movement(tmp_path):
    path=tmp_path/'same-request.sqlite3'
    con=connect(path); setup(con); current=lot(con); con.commit(); con.close()
    barrier=threading.Barrier(2)
    def worker():
        con=connect(path); barrier.wait(); con.execute('BEGIN IMMEDIATE')
        result=move(con,current,'receive',4); con.commit(); con.close(); return result
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs=[pool.submit(worker),pool.submit(worker)]
        results=[job.result() for job in jobs]
    assert results[0]['movementId']==results[1]['movementId']
    assert sorted(r['replayed'] for r in results)==[False,True]


def test_separate_households_same_member_and_request_have_separate_state(tmp_path):
    a,b=connect(tmp_path/'a.db'),connect(tmp_path/'b.db')
    try:
        setup(a);setup(b)
        first=item(a);second=item(b)
        assert first['itemId']!=second['itemId']
        fail('not_found',core.project_item,b,'member1',first['itemId'])
        assert len(core.export_inventory(a,'member1')['personal'])==1
        assert len(core.export_inventory(b,'member1')['personal'])==1
    finally:
        a.close();b.close()


@pytest.mark.parametrize('field,value',[('ordered_qty',0),('ordered_qty',1.25),('ordered_qty',1000001),
    ('expected_on','2026-02-30'),('ordered_on','not-a-date'),('warranty_until','2026-1-01')])
def test_direct_sql_domain_checks(db,field,value):
    current=lot(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(f'UPDATE inventory_acquisitions SET {field}=? WHERE id=?',(value,current['acquisitionId']))


def test_raw_sql_overreceipt_and_reverse_are_guarded(db):
    current=move(db,lot(db),'receive',4)
    values=('f'*24,current['itemId'],current['acquisitionId'],'member1','receive',3,'2026-09-16','',None,request_id(9),'now')
    with pytest.raises(sqlite3.IntegrityError):
        db.execute('INSERT INTO inventory_movements VALUES(?,?,?,?,?,?,?,?,?,?,?)',values)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute('INSERT INTO inventory_movements VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                   ('e'*24,current['itemId'],current['acquisitionId'],'member1','reverse',-3,'2026-09-16','correction',current['movementId'],request_id(10),'now'))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute('UPDATE inventory_acquisitions SET ordered_qty=3 WHERE id=?',(current['acquisitionId'],))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE inventory_items SET deleted_at='now' WHERE id=?",(current['itemId'],))


def test_sql_event_acl_rejects_other_member_private_item(db):
    current=lot(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute('INSERT INTO inventory_movements VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            ('f'*24,current['itemId'],current['acquisitionId'],'member2','receive',1,'2026-09-16','',None,request_id(10),'now'))


def test_sql_source_cannot_bind_opening_or_reassign_owner(db):
    current=lot(db,opening=True)
    with pytest.raises(sqlite3.IntegrityError):
        source(db,current)
    db.rollback();db.execute('BEGIN IMMEDIATE')
    current=lot(db,shared=True);source(db,current)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE inventory_source_links SET owner='member2'")


def test_empty_actor_missing_item_and_nonshopping_reference(db):
    fail('transaction_required',core.project_item,db,'','a'*24)
    first=item(db)
    sid='b'*24
    db.execute('INSERT INTO entities VALUES(?,?,?,?)',(sid,'tasks','{}',1))
    fail('not_found',core.create_acquisition,db,'member1',first['itemId'],1,{'orderedQty':2,'shoppingId':sid},request_id(2))
    assert counts(db)['inventory_acquisitions']==0


def test_operations_survive_connection_restart_and_do_not_reapply(tmp_path):
    path=tmp_path/'durable.sqlite3'
    con=connect(path);setup(con)
    current=lot(con);received=move(con,current,'receive',4);con.commit();con.close()
    con=connect(path);core.initialize_inventory(con);con.execute('BEGIN IMMEDIATE')
    replay=move(con,current,'receive',4)
    assert replay['movementId']==received['movementId'] and replay['replayed']
    assert core.project_acquisition(con,'member1',current['acquisitionId'])['onHandQty']==4
    con.close()


def test_adjustments_are_explicit_signed_and_returns_do_not_reopen_order(db):
    current=move(db,lot(db,qty=4),'receive',4)
    current=move(db,current,'return',2,4)
    assert core.project_acquisition(db,'member1',current['acquisitionId'])['remainingExpectedQty']==0
    current=move(db,current,'adjust',-1,5)
    current=move(db,current,'adjust',1,6)
    assert core.project_acquisition(db,'member1',current['acquisitionId'])['onHandQty']==2
    fail('invalid',move,db,current,'adjust',1,7,reason='')


def test_threshold_does_not_count_merely_planned_and_no_title_merging(db):
    first=core.create_item(db,'member1',{'title':'Battery','unit':'piece','reorderPoint':4},request_id(1))
    current=core.create_acquisition(db,'member1',first['itemId'],1,{'orderedQty':4},request_id(2))
    assert core.project_item(db,'member1',first['itemId'])['belowThreshold']
    core.update_acquisition(db,'member1',current['acquisitionId'],2,1,{'orderState':'ordered'},request_id(3))
    assert not core.project_item(db,'member1',first['itemId'])['belowThreshold']
    second=core.create_item(db,'member1',{'title':'Battery','unit':'piece','reorderPoint':4},request_id(4))
    assert second['itemId']!=first['itemId']
    assert core.project_item(db,'member1',second['itemId'])['inTransitQty']==0


def test_invalid_callback_failure_sanitized_and_atomic(db):
    first=item(db)
    def failed():
        db.execute("UPDATE inventory_items SET title='wrong'")
        raise RuntimeError('PRIVATE_FINANCIAL_METADATA')
    fail('storage',core.apply_with_receipt,db,'member1',request_id(2),'create_followup',{},failed,
         item_id=first['itemId'],item_revision=1)
    assert core.project_item(db,'member1',first['itemId'])['title']=='Battery'


@pytest.mark.parametrize('req',['',True,'g'*32,'a'*31,'a'*65,'a\n'+'b'*31])
def test_request_id_bounds(db,req):
    fail('invalid',core.create_item,db,'member1',{'title':'A','unit':'piece'},req)


def test_sqlite_row_factory_and_outer_transaction_compatibility(db):
    db.row_factory=sqlite3.Row
    current=lot(db)
    assert core.project_acquisition(db,'member1',current['acquisitionId'])['orderedQty']==6
    assert db.in_transaction


def test_extension_seam_checks_acl_and_revision_before_trusted_callback(db):
    first=item(db)
    called=[]
    def callback():
        called.append(True)
        return first
    fail('not_found',core.apply_with_receipt,db,'member2',request_id(4),'create_followup',{},callback,
         item_id=first['itemId'],item_revision=1)
    fail('conflict',core.apply_with_receipt,db,'member1',request_id(4),'create_followup',{},callback,
         item_id=first['itemId'],item_revision=2)
    assert not called
