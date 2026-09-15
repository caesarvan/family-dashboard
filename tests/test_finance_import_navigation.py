"""Persisted month navigation; synthetic SQLite only, no source/schema changes."""
import sqlite3
import pytest
from test_finance_hub import hub, payload, upload


def view(client, month='2026-09', actor='member1'):
    return client.get('/api/finance-hub/overview?month='+month, headers={'X-Test-Actor':actor})


def test_first_previous_month_is_discoverable_without_changing_selected_month(hub):
    client,_=hub
    result=upload(client,payload('2026-08-02,OLD,10,CNY,expense,Other,old,成功\n')).json
    assert result['imported']==1
    assert result['resultMonths']==[{'month':'2026-08','recordCount':1}]
    assert result['confirmedAt']
    state=view(client).json
    assert state['month']=='2026-09' and state['transactionCount']==0
    assert state['availableMonths']==result['resultMonths'] and state['totalRecordCount']==1


def test_multimonth_sorted_unique_persisted_counts_and_duplicate_lines(hub):
    client,_=hub
    rows='2026-07-01,JULY,1,CNY,expense,Other,j,成功\n2026-08-01,AUG,2,CNY,expense,Other,a,成功\n2026-08-01,AUG,2,CNY,expense,Other,a,成功\n2026-08-03,AUG2,3,USD,income,Other,a2,成功\n'
    first=upload(client,payload(rows)).json
    assert (first['imported'],first['duplicates'])==(3,1)
    assert first['resultMonths']==[{'month':'2026-08','recordCount':2},{'month':'2026-07','recordCount':1}]
    replay=upload(client,payload(rows)).json
    assert (replay['imported'],replay['duplicates'])==(0,4)
    assert replay['resultMonths']==first['resultMonths']==view(client).json['availableMonths']


def test_conflict_uses_retained_date_and_does_not_claim_proposed_month(hub):
    client,_=hub
    upload(client,payload('2026-07-01,KEEP,10,CNY,expense,Other,same,成功\n'))
    result=upload(client,payload('2026-08-01,CHANGE,20,USD,expense,Other,same,成功\n')).json
    assert (result['imported'],result['duplicates'],result['conflicts'])==(0,1,1)
    assert result['resultMonths']==[{'month':'2026-07','recordCount':1}]
    old=view(client,'2026-07').json['transactions'][0]
    assert old['title']=='KEEP' and old['amountCents']==1000 and old['currency']=='CNY'
    assert view(client,'2026-08').json['transactionCount']==0


def test_receipt_only_includes_rows_addressed_by_this_confirmation(hub):
    client,_=hub
    upload(client,payload('2026-07-01,OTHER,1,CNY,expense,Other,other,成功\n'))
    result=upload(client,payload('2026-08-01,NEW,1,CNY,expense,Other,new,成功\n')).json
    assert result['resultMonths']==[{'month':'2026-08','recordCount':1}]
    assert len(view(client).json['availableMonths'])==2


def test_delete_readback_is_current_and_does_not_reimport(hub):
    client,_=hub
    result=upload(client,payload()).json
    old=view(client).json['transactions'][0]
    assert client.delete('/api/finance-hub/transactions/'+old['id'],json={'revision':old['revision']}).status_code==200
    assert view(client).json['availableMonths']==[]
    assert view(client).json['totalRecordCount']==0
    assert result['resultMonths']==[{'month':'2026-09','recordCount':1}]  # Historical response, not live state.


def test_explicit_reconfirm_after_deletion_keeps_existing_backend_semantics(hub):
    client,_=hub
    value=payload()
    token=client.post('/api/finance-hub/imports/preview',json=value).json['previewToken']
    body={**value,'previewToken':token}
    assert client.post('/api/finance-hub/imports/confirm',json=body).json['imported']==1
    row=view(client).json['transactions'][0]
    client.delete('/api/finance-hub/transactions/'+row['id'],json={'revision':row['revision']})
    # This endpoint remains content-deduped, not a stored immutable receipt service.
    result=client.post('/api/finance-hub/imports/confirm',json=body).json
    assert result['imported']==1 and view(client).json['totalRecordCount']==1


def test_metadata_is_owner_only_and_has_no_record_details(hub):
    client,_=hub
    upload(client,payload('2026-07-01,PRIVATE_A,1,CNY,expense,Other,a,成功\n'))
    upload(client,payload('2026-08-01,PRIVATE_B,1,CNY,expense,Other,b,成功\n'),uid='member2')
    assert view(client,actor='member1').json['availableMonths']==[{'month':'2026-07','recordCount':1}]
    assert view(client,actor='member2').json['availableMonths']==[{'month':'2026-08','recordCount':1}]
    assert all(set(item)=={'month','recordCount'} for item in view(client).json['availableMonths'])


@pytest.mark.parametrize('actor,status',[('anonymous',401),('tv',403)])
def test_metadata_requires_member(hub,actor,status):
    client,_=hub
    assert view(client,actor=actor).status_code==status


def test_preview_does_not_create_receipt_or_months(hub):
    client,path=hub
    with sqlite3.connect(path) as con:
        schema=con.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name').fetchall()
    preview=client.post('/api/finance-hub/imports/preview',json=payload()).json
    assert preview['newCount']==1 and 'resultMonths' not in preview
    assert view(client).json['availableMonths']==[]
    upload(client)
    with sqlite3.connect(path) as con:
        assert schema==con.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name').fetchall()
