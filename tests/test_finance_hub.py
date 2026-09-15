"""Synthetic records only. Standalone registration exercises actual SQLite writes."""
import json
import sqlite3

import pytest
from flask import Flask, g, jsonify, request

from finance_hub import FinanceHubError, parse_import, register_finance_hub


class Problem(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


@pytest.fixture
def hub(tmp_path):
    app = Flask(__name__)
    app.config.update(SECRET_KEY='synthetic-testing-secret', TESTING=True, MAX_CONTENT_LENGTH=600000)
    target = tmp_path / 'synthetic.sqlite3'
    def db():
        if 'db' not in g:
            g.db = sqlite3.connect(target)
            g.db.row_factory = sqlite3.Row
            g.db.execute('PRAGMA foreign_keys=ON')
        return g.db
    @app.teardown_appcontext
    def close(_error):
        con = g.pop('db', None)
        if con:
            con.close()
    with app.app_context():
        db().executescript('''CREATE TABLE users(id TEXT PRIMARY KEY); INSERT INTO users VALUES('member1'),('member2');
            CREATE TABLE settings(id TEXT PRIMARY KEY,data TEXT); INSERT INTO settings VALUES('finance','{"wallet":100}');
            CREATE TABLE audit(action TEXT,target TEXT);''')
        db().commit()
    @app.before_request
    def guard():
        uid = request.headers.get('X-Test-Actor', 'member1')
        g.actor = None if uid == 'anonymous' else {'id': uid, 'role': 'tv' if uid == 'tv' else 'member'}
    @app.errorhandler(Problem)
    def error(exc):
        return jsonify(error=exc.message), exc.status
    def member():
        if not g.actor:
            raise Problem('login', 401)
        if g.actor['role'] != 'member':
            raise Problem('member only', 403)
    def body():
        obj = request.get_json(silent=True)
        if not isinstance(obj, dict):
            raise Problem('JSON object required')
        return obj
    def audit(action, rid):
        db().execute('INSERT INTO audit VALUES(?,?)', (action, rid))
    register_finance_hub(app, db, Problem, body, member, audit)
    return app.test_client(), target


def payload(rows=None, source='generic', kind='payments'):
    return {'source': source, 'kind': kind,
            'csv': 'date,title,amount,currency,flow,category,id,status\n' + (rows or '2026-09-02,PRIVATE_COFFEE,10.50,CNY,expense,餐饮,a-1,成功\n')}


def upload(client, value=None, uid='member1'):
    value = value or payload()
    headers = {'X-Test-Actor': uid}
    preview = client.post('/api/finance-hub/imports/preview', json=value, headers=headers)
    assert preview.status_code == 200, preview.json
    assert preview.json['previewToken']
    return client.post('/api/finance-hub/imports/confirm', json={**value, 'previewToken': preview.json['previewToken']}, headers=headers)


def overview(client, uid='member1'):
    r = client.get('/api/finance-hub/overview?month=2026-09', headers={'X-Test-Actor': uid})
    assert r.status_code == 200
    return r.json


def investment(**kwargs):
    return {'name': 'PRIVATE_FUND', 'institution': 'PRIVATE_BANK', 'assetType': '基金', 'currency': 'USD',
            'quantity': '12.5', 'cost': '100', 'value': '120', 'asOf': '2026-09-04', 'note': '', **kwargs}


def test_preview_is_stateless_and_requires_confirm(hub):
    client, target = hub
    r = client.post('/api/finance-hub/imports/preview', json=payload())
    assert r.status_code == 200 and r.json['newCount'] == 1
    con = sqlite3.connect(target)
    assert con.execute('SELECT count(*) FROM hub_transactions').fetchone()[0] == 0
    assert con.execute('SELECT count(*) FROM hub_imports').fetchone()[0] == 0
    assert con.execute('SELECT count(*) FROM audit').fetchone()[0] == 0
    con.close()
    assert client.post('/api/finance-hub/imports/confirm', json=payload()).status_code == 400
    changed = {**payload(), 'csv': payload()['csv'].replace('10.50', '20.50'), 'previewToken': r.json['previewToken']}
    assert client.post('/api/finance-hub/imports/confirm', json=changed).status_code == 400
    assert client.post('/api/finance-hub/imports/confirm', json={**payload(), 'previewToken': r.json['previewToken']}, headers={'X-Test-Actor': 'member2'}).status_code == 400
    assert upload(client).json['imported'] == 1
    con = sqlite3.connect(target)
    assert con.execute("SELECT data FROM settings WHERE id='finance'").fetchone()[0] == '{"wallet":100}'
    con.close()


def test_reimport_duplicate_file_and_duplicate_rows(hub):
    client, _ = hub
    repeated = payload('2026-09-02,Same,10,CNY,expense,餐饮,a-1,成功\n' * 2)
    result = upload(client, repeated).json
    assert result['imported'] == 1 and result['duplicates'] == 1
    result = upload(client, repeated).json
    assert result['imported'] == 0 and result['duplicates'] == 2
    changed = payload('2026-09-02,Same,15,CNY,expense,餐饮,a-1,成功\n')
    result = upload(client, changed).json
    assert result['conflicts'] == 1
    assert overview(client)['totals'][0]['expenseCents'] == 1000
    assert len(overview(client)['imports']) == 1


def test_owner_and_tv_boundaries_on_every_route(hub):
    client, _ = hub
    upload(client)
    rid = overview(client)['transactions'][0]['id']
    invest = client.post('/api/finance-hub/investments', json=investment()).json
    assert overview(client, 'member2')['transactions'] == []
    assert overview(client, 'member2')['investments'] == []
    for path in ['overview', 'template', 'shared']:
        assert client.get('/api/finance-hub/'+path, headers={'X-Test-Actor': 'tv'}).status_code == 403
        assert client.get('/api/finance-hub/'+path, headers={'X-Test-Actor': 'anonymous'}).status_code == 401
    for entity, item in [('transactions', rid), ('investments', invest['id'])]:
        for method in ['patch', 'delete']:
            assert getattr(client, method)('/api/finance-hub/'+entity+'/'+item, json={'revision': 1}, headers={'X-Test-Actor':'member2'}).status_code == 404
            assert getattr(client, method)('/api/finance-hub/'+entity+'/'+item, json={'revision': 1}, headers={'X-Test-Actor':'tv'}).status_code == 403
    for path in ['imports/preview','imports/confirm','investments']:
        assert client.post('/api/finance-hub/'+path, json=payload(), headers={'X-Test-Actor':'tv'}).status_code == 403
    assert client.put('/api/finance-hub/budgets', json={}, headers={'X-Test-Actor':'tv'}).status_code == 403


def test_explicit_sharing_only_whitelisted_aggregates(hub):
    client, _ = hub
    upload(client)
    r = overview(client)['transactions'][0]
    shared = lambda: client.get('/api/finance-hub/shared?month=2026-09', headers={'X-Test-Actor':'member2'}).json
    assert shared()['totals'] == []
    updated = client.patch('/api/finance-hub/transactions/'+r['id'], json={'revision':1,'visibility':'shared'})
    assert updated.status_code == 200 and updated.json['checkedAt']
    assert shared()['totals'][0]['expenseCents'] == 1050
    assert 'PRIVATE_' not in json.dumps(shared())
    assert 'member1' not in json.dumps(shared())
    assert client.patch('/api/finance-hub/transactions/'+r['id'], json={'revision':2,'flow':'income'}).status_code == 400
    assert client.patch('/api/finance-hub/transactions/'+r['id'], json={'revision':2,'flow':'income','visibility':'private'}).status_code == 200
    assert shared()['totals'] == []


def test_conservative_refunds_transfers_orders_and_currency(hub):
    client, _ = hub
    value = payload('2026-09-01,Buy,100,CNY,支出,餐饮,a1,成功\n'
                    '2026-09-02,Refund,20,CNY,收入,退款,a2,退款成功\n'
                    '2026-09-03,Transfer,200,CNY,支出,转账,a3,成功\n'
                    '2026-09-04,Salary,500,CNY,income,工资,a4,成功\n'
                    '2026-09-05,Original refund state,90,CNY,支出,餐饮,a5,已退款\n'
                    '2026-09-06,Unknown,15,USD,,其他,a6,成功\n'
                    '2026-09-07,Failed,50,CNY,expense,餐饮,a7,交易关闭\n')
    upload(client, value)
    upload(client, payload('2026-09-01,Order,100,CNY,expense,餐饮,o1,成功\n', source='taobao', kind='orders'))
    groups = {t['currency']:t for t in overview(client)['totals']}
    assert groups['CNY']['netSpendCents'] == 8000
    assert groups['CNY']['incomeCents'] == 50000
    assert groups['CNY']['transferCents'] == 20000
    assert groups['CNY']['unknownCents'] == 9000
    assert groups['CNY']['orderCents'] == 10000
    assert groups['CNY']['excludedCents'] == 5000
    assert groups['USD']['unknownCents'] == 1500


def test_chinese_header_preamble_and_aliases():
    parsed = parse_import({'source':'wechat', 'csv':'微信支付账单\n导出日期：示例\n交易时间,交易类型,交易对方,商品,收/支,金额(元),支付方式,当前状态,交易单号\n2026/9/2 12:00:00,商户消费,店铺,咖啡,支出,￥10.50,零钱,支付成功,xx\n'})
    assert parsed['rows'][0]['amountCents'] == 1050
    assert parsed['rows'][0]['date'] == '2026-09-02'
    assert parsed['rows'][0]['flow'] == 'expense'
    assert parsed['rows'][0]['externalId'] == 'xx'
    assert parsed['rows'][0]['title'] == '咖啡'
    assert parsed['warnings']  # missing currency explicit assumption
    alipay = parse_import({'source':'alipay','csv':'交易号,商家订单号,交易创建时间,商品名称,金额（元）,收支,交易状态\na1,o1,2026-09-01 12:00:00,测试,12.00,支出,交易成功\n'})
    assert alipay['rows'][0]['externalId'] == 'a1'
    assert alipay['rows'][0]['title'] == '测试'


@pytest.mark.parametrize('value', [[], None, 5, {'csv':'a'*400001}, {'csv':'\x00'}, {'csv':'\ufffd'}, {'csv':'date,title,amount\n2026-09-01,x,2'}, {'source':[],'csv':'x'}, {'kind':{},'csv':'x'}])
def test_malformed_preview_is_4xx(hub, value):
    client, _ = hub
    r = client.post('/api/finance-hub/imports/preview', json=value)
    assert 400 <= r.status_code < 500


@pytest.mark.parametrize('amount', ['NaN','Infinity','-1','1.001','1e100','true',''])
def test_invalid_amount_prevents_entire_confirmation(hub, amount):
    client, _ = hub
    value=payload('2026-09-01,Invalid,'+amount+',CNY,expense,餐饮,a1,成功\n2026-09-01,Valid,2,CNY,expense,餐饮,a2,成功\n')
    r=client.post('/api/finance-hub/imports/preview',json=value)
    assert r.status_code == 200 and r.json['errorCount'] == 1 and r.json['previewToken'] is None
    assert overview(client)['transactions'] == []


def test_investments_valued_subset_revision_and_unvalued(hub):
    client, _=hub
    a=client.post('/api/finance-hub/investments',json=investment())
    assert a.status_code == 201
    b=client.post('/api/finance-hub/investments',json=investment(name='Unvalued',cost='70',value=''))
    assert b.status_code == 201
    client.post('/api/finance-hub/investments',json=investment(name='CNY deposit',currency='CNY',cost='500',value='500'))
    groups={t['currency']:t for t in overview(client)['investmentTotals']}
    assert groups['USD']['costCents'] == 17000
    assert groups['USD']['valuedCostCents'] == 10000
    assert groups['USD']['valueCents'] == 12000
    assert groups['USD']['unrealizedGainCents'] == 2000
    assert groups['USD']['unvaluedCount'] == 1
    assert groups['USD']['allocation'][0]['percent'] == 100
    rid=a.json['id']
    assert client.patch('/api/finance-hub/investments/'+rid,json=investment(revision=2)).status_code==409
    assert client.patch('/api/finance-hub/investments/'+rid,json=investment(revision=1,value='150')).json['revision']==2
    assert client.delete('/api/finance-hub/investments/'+rid,json={'revision':1}).status_code==409
    assert client.delete('/api/finance-hub/investments/'+rid,json={'revision':2}).status_code==200


@pytest.mark.parametrize('field,value', [('cost',True),('value',-1),('asOf','2026-02-30'),('asOf',None),('currency','not_currency'),('name',[]),('quantity','NaN'),('quantity',3),('visibility','shared')])
def test_investments_reject_malformed_fields(hub, field, value):
    client, _=hub
    assert client.post('/api/finance-hub/investments',json=investment(**{field:value})).status_code==400
    assert overview(client)['investments']==[]


def test_month_budget_and_category_revision(hub):
    client,_=hub
    upload(client)
    budget={'month':'2026-09','currency':'CNY','category':'餐饮','amount':'100','revision':0}
    assert client.put('/api/finance-hub/budgets',json=budget).status_code==200
    assert client.put('/api/finance-hub/budgets',json=budget).status_code==409
    b=overview(client)['budgets'][0]
    assert b['spentCents']==1050 and b['remainingCents']==8950
    assert overview(client,'member2')['budgets']==[]
    assert client.put('/api/finance-hub/budgets',json={**budget,'revision':1,'amount':'50'}).json['revision']==2
    assert client.get('/api/finance-hub/overview?month=2026-13').status_code==400
    assert client.get('/api/finance-hub/overview?month=2026-08').json['budgets']==[]


def test_record_updates_are_versioned_and_owner_bound(hub):
    client,_=hub
    upload(client)
    r=overview(client)['transactions'][0]
    assert client.patch('/api/finance-hub/transactions/'+r['id'],json={'revision':1,'flow':[]}).status_code==400
    assert client.patch('/api/finance-hub/transactions/'+r['id'],json={'revision':1,'visibility':[]}).status_code==400
    assert client.patch('/api/finance-hub/transactions/'+r['id'],json={'revision':1,'amountCents':0}).status_code==400
    assert client.patch('/api/finance-hub/transactions/'+r['id'],json={'revision':1,'category':'购物'}).json['revision']==2
    assert client.delete('/api/finance-hub/transactions/'+r['id'],json={'revision':1}).status_code==409
    assert client.delete('/api/finance-hub/transactions/'+r['id'],json={'revision':2}).status_code==200
    assert overview(client)['transactions']==[]


def test_header_and_row_limits(hub):
    client,_=hub
    assert client.post('/api/finance-hub/imports/preview',json=payload('2026-09-01,A,1,CNY,expense,餐饮,a,成功\n'*5001)).status_code==400
    assert client.post('/api/finance-hub/imports/preview',json=payload('2026-09-01,"unterminated,1,CNY,expense,餐饮,a,成功\n')).status_code==400
    assert client.post('/api/finance-hub/imports/preview',json={'source':'generic','csv':'date,title,amount\n2026-09-01,x,1'}).status_code==400
    assert client.post('/api/finance-hub/imports/preview',json=payload('2026-09-01,\ud800,1,CNY,expense,餐饮,a,成功\n')).status_code==400
    assert client.post('/api/finance-hub/investments',json=investment(name='\ud800')).status_code==400
