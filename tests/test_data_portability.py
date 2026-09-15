import csv
import hashlib
from io import BytesIO, StringIO
import json
from pathlib import Path
import sqlite3
from zipfile import ZipFile

from test_app import app, member
from test_household_spaces import create_space


def seed(app):
    con = sqlite3.connect(Path(app.config['DATA_DIR']) / 'household.sqlite3')
    for uid in ('member1','member2'):
        record={'date':'2026-09-15','title':uid+'_PRIVATE', 'amountCents':12345,'currency':'USD',
                'kind':'payments','flow':'expense','category':'旅行','source':'generic','externalId':'ext-'+uid,'visibility':'private'}
        con.execute('INSERT INTO hub_transactions(id,owner,fingerprint,data,created_at) VALUES(?,?,?,?,?)',
                    ('tx-'+uid,uid,'fingerprint-'+uid,json.dumps(record),'2026-09-15T00:00:00Z'))
        con.execute('INSERT INTO private_finance(owner,data) VALUES(?,?)',(uid,json.dumps({'private':uid+'_MONTHLY'})))
        con.execute('INSERT INTO finance_baselines(owner,private_data,shared_data,source_digest,content_hash,updated_at) VALUES(?,?,?,?,?,?)',
                    (uid,json.dumps({'private':uid+'_BASELINE'}),json.dumps({'owner':uid,'complete':False,'recordedAssetCents':100}),uid,uid,'2026-09-15'))
        con.execute('INSERT INTO cloud_accounts(id,owner,provider,client_id,subject,name,email,tokens) VALUES(?,?,?,?,?,?,?,?)',
                    ('account-'+uid,uid,'google','PRIVATE_CLIENT_ID','PRIVATE_SUBJECT_'+uid,uid+'_ACCOUNT_LABEL',uid+'@example.invalid','PRIVATE_TOKEN_'+uid))
    con.execute('INSERT INTO entities(id,kind,data,updated_at) VALUES(?,?,?,?)',
                ('shared-event','events',json.dumps({'title':'SHARED_EVENT','owner':'member2','sync':{'privateInternal':'SHOULD_NOT_EXPORT_SYNC'},'start':'2026-10-01T00:00:00+08:00','end':'2026-10-02T00:00:00+08:00'}),'2026-09-15'))
    con.commit()
    con.close()


def unpack(response):
    assert response.status_code == 200, response.get_data(as_text=True) if response.status_code!=200 else ''
    assert response.mimetype=='application/zip'
    assert 'no-store' in response.headers['Cache-Control']
    with ZipFile(BytesIO(response.data)) as archive:
        assert archive.testzip() is None
        values={n:archive.read(n) for n in archive.namelist()}
    manifest=json.loads(values['manifest.json'])
    for name,meta in manifest['files'].items():
        assert len(values[name])==meta['bytes']
        assert hashlib.sha256(values[name]).hexdigest()==meta['sha256']
    return json.loads(values['data.json']), values


def test_export_is_owner_scoped_and_shared_is_explicit(app):
    seed(app)
    c,h=member(app)
    original=c.get('/api/state').json['revision']
    data,files=unpack(c.post('/api/portability/export',json={},headers=h))
    assert 'shared' not in data
    assert data['member']['id']=='member1'
    assert data['personal']['transactions'][0]['title']=='member1_PRIVATE'
    assert len(data['personal']['financeBaselines'])==1
    joined=b''.join(files.values())
    for secret in [b'member2_PRIVATE',b'member2_MONTHLY',b'member2_BASELINE',b'member2_ACCOUNT_LABEL',
                   b'PRIVATE_TOKEN_',b'PRIVATE_CLIENT_ID',b'PRIVATE_SUBJECT_',b'SHOULD_NOT_EXPORT_SYNC',b'SHARED_EVENT']:
        assert secret not in joined
    assert 'scrypt:' not in joined.decode('utf-8-sig')
    shared,files=unpack(c.post('/api/portability/export',json={'includeShared':True},headers=h))
    assert shared['shared']['entities']['events'][0]['title']=='SHARED_EVENT'
    assert len(shared['shared']['financeBaselines'])==2
    assert b'member2_PRIVATE' not in b''.join(files.values())
    assert b'member2_BASELINE' not in b''.join(files.values())
    assert b'SHOULD_NOT_EXPORT_SYNC' not in b''.join(files.values())
    other,oh=member(app,2)
    own,_=unpack(other.post('/api/portability/export',json={},headers=oh))
    assert own['personal']['transactions'][0]['title']=='member2_PRIVATE'
    assert c.get('/api/portability/summary').json['personal']['transactions']==1
    assert len(c.get('/api/state').json['events'])==1


def test_export_contains_all_rows_beyond_dashboard_page_and_spreadsheet_safe_text(app):
    c,h=member(app)
    title='  =HYPERLINK("https://example.invalid","x")'
    records=[]
    for i in range(501):
        row={'date':'2026-09-15','title':title if i==0 else str(i),'amountCents':99999999999999,'currency':'USD',
             'kind':'payments','flow':'expense','category':'测试','source':'generic','externalId':str(i),'visibility':'private'}
        records.append((f'tx-{i}','member1',str(i),json.dumps(row),'2026-09-15'))
    with sqlite3.connect(Path(app.config['DATA_DIR'])/'household.sqlite3') as con:
        con.executemany('INSERT INTO hub_transactions(id,owner,fingerprint,data,created_at) VALUES(?,?,?,?,?)',records)
    investment=c.post('/api/finance-hub/investments',json={'name':'待估值','institution':'示例机构','assetType':'基金','currency':'USD','cost':'123.45','value':None,'asOf':'2026-09-15'},headers=h)
    assert investment.status_code==201,investment.json
    snapshot,files=unpack(c.post('/api/portability/export',json={},headers=h))
    assert len(snapshot['personal']['transactions'])==501
    assert snapshot['personal']['transactions'][0]['title']==title
    csv_rows=list(csv.DictReader(StringIO(files['transactions.csv'].decode('utf-8-sig'))))
    assert len(csv_rows)==501 and csv_rows[0]['title']=="'"+title
    assert csv_rows[0]['amount']=='999999999999.99'
    values=list(csv.DictReader(StringIO(files['investments.csv'].decode('utf-8-sig'))))
    assert values[0]['cost']=='123.45' and values[0]['value']==''
    assert snapshot['personal']['investments'][0]['valueCents'] is None


def test_export_rejects_unauthenticated_tv_cross_origin_and_other_owner(app):
    c,h=member(app)
    public=app.test_client()
    assert public.get('/api/portability/summary').status_code==401
    assert public.post('/api/portability/export',json={}).status_code==401
    assert c.post('/api/portability/export',json={}).status_code==403
    assert c.post('/api/portability/export',json={},headers={**h,'Origin':'https://other.invalid'}).status_code==403
    assert c.post('/api/portability/export',json={'owner':'member2'},headers=h).status_code==400
    assert c.post('/api/portability/export',json={'includeShared':'true'},headers=h).status_code==400
    pair=public.post('/api/pair/start',json={}).json
    assert c.post('/api/pair/approve',json={'code':pair['code']},headers=h).status_code==200
    assert public.post('/api/pair/poll',json={'secret':pair['secret']}).status_code==200
    assert public.get('/api/portability/summary').status_code==403
    assert public.post('/api/portability/export',json={}).status_code==403


def test_export_other_household_cannot_include_original_records(app):
    seed(app)
    child,_,result=create_space(app)
    child.get(result['entry'])
    assert child.post('/api/login',json={'username':'member1','password':'second-home-password-one'}).status_code==200
    headers={'X-CSRF-Token':child.get('/api/me').json['csrf']}
    data,files=unpack(child.post('/api/portability/export',json={'includeShared':True},headers=headers))
    assert data['household']['slug']=='second-home'
    assert data['personal']['transactions']==[]
    assert data['shared']['financeBaselines']==[]
    assert b'member1_PRIVATE' not in b''.join(files.values())
    assert b'SHARED_EVENT' not in b''.join(files.values())


def test_export_failed_limit_releases_slot_and_does_not_return_partial_zip(app,monkeypatch):
    import data_portability
    c,h=member(app)
    monkeypatch.setattr(data_portability,'MAX_EXPORT_BYTES',16)
    result=c.post('/api/portability/export',json={},headers=h)
    assert result.status_code==413 and result.mimetype=='application/json'
    monkeypatch.setattr(data_portability,'MAX_EXPORT_BYTES',64*1024*1024)
    assert data_portability.EXPORT_SLOT.acquire(blocking=False)
    try:
        assert c.post('/api/portability/export',json={},headers=h).status_code==429
    finally:
        data_portability.EXPORT_SLOT.release()
    unpack(c.post('/api/portability/export',json={},headers=h))
