"""Private synthetic reconciliation: no real ledger files or platform requests."""
import json
import sqlite3

import pytest

from test_finance_hub import hub, overview, payload, upload
from test_app import app, member
from test_household_spaces import create_space


BASE = '/api/finance-hub/reconciliation'


def seed(client, title='PAY', amount='100', flow='expense', category='购物', kind='payments', source='generic', currency='CNY', day='2026-09-02', uid='member1'):
    result = upload(client, payload(f'{day},{title},{amount},{currency},{flow},{category},{title},成功\n', source, kind), uid)
    assert result.status_code == 200, result.json
    rows = client.get('/api/finance-hub/overview?month='+day[:7], headers={'X-Test-Actor': uid}).json['transactions']
    return next(r for r in rows if r['externalId'] == title and r['source'] == source)


def preview(client, kind, left, right, amount=None, uid='member1'):
    value = {'kind': kind, 'leftId': left['id'], 'rightId': right['id']}
    if amount is not None:
        value['amount'] = amount
    return client.post(BASE+'/preview', json=value, headers={'X-Test-Actor': uid})


def confirm(client, p, uid='member1'):
    assert p.status_code == 200, p.json
    return client.post(BASE+'/confirm', json={'previewToken': p.json['previewToken']}, headers={'X-Test-Actor': uid})


def link(client, kind, left, right, amount=None):
    result = confirm(client, preview(client, kind, left, right, amount))
    assert result.status_code == 200, result.json
    return result.json['relation']


def revoke(client, relation, uid='member1'):
    return client.post(BASE+'/'+relation['id']+'/revoke', json={'revision': relation['revision']}, headers={'X-Test-Actor': uid})


def test_full_order_payment_refund_duplicate_loop_and_revoke(hub):
    client, target = hub
    order = seed(client, 'ORDER', kind='orders', source='taobao')
    pay = seed(client, 'PAY')
    duplicate = seed(client, 'DUPLICATE', source='alipay')
    refund = seed(client, 'REFUND', '30', 'refund', '原退款分类')
    assert overview(client)['totals'][0]['netSpendCents'] == 17000
    before = sqlite3.connect(target).execute('SELECT count(*) FROM hub_reconciliations').fetchone()[0]
    p = preview(client, 'duplicate', duplicate, pay)
    assert p.status_code == 200
    assert sqlite3.connect(target).execute('SELECT count(*) FROM hub_reconciliations').fetchone()[0] == before
    assert overview(client)['totals'][0]['netSpendCents'] == 17000
    relation = confirm(client, p).json['relation']
    assert confirm(client, p).json['replayed'] is True
    link(client, 'order_payment', order, pay)
    refund_link = link(client, 'refund_payment', refund, pay)
    result = overview(client)
    assert result['transactionCount'] == 4
    assert result['totals'][0]['netSpendCents'] == 7000
    assert result['totals'][0]['orderCents'] == 10000
    assert result['totals'][0]['duplicateCount'] == 1
    assert result['totals'][0]['categories']['购物'] == 7000
    pay_state = next(r for r in result['transactions'] if r['id'] == pay['id'])['reconciliation']
    assert pay_state['refundedCents'] == 3000 and pay_state['remainingAfterRefundCents'] == 7000
    assert revoke(client, relation).status_code == 200
    assert revoke(client, relation).json['replayed'] is True
    assert overview(client)['totals'][0]['netSpendCents'] == 17000
    assert revoke(client, refund_link).status_code == 200
    assert overview(client)['totals'][0]['categories']['原退款分类'] == -3000


def test_partial_allocations_split_orders_and_refunds_limits(hub):
    client, _ = hub
    pay = seed(client)
    order1, order2 = seed(client, 'ORDER1', '60', kind='orders'), seed(client, 'ORDER2', '60', kind='orders')
    link(client, 'order_payment', order1, pay, '60')
    assert preview(client, 'order_payment', order2, pay, '41').status_code == 400
    link(client, 'order_payment', order2, pay, '40')
    assert preview(client, 'order_payment', order2, pay, '1').status_code == 409
    refund = seed(client, 'REFUND', '80', 'refund', '退款原类')
    link(client, 'refund_payment', refund, pay, '30')
    r = next(r for r in overview(client)['transactions'] if r['id'] == refund['id'])
    assert r['amountCents'] == 8000 and r['reconciliation']['unallocatedCents'] == 5000
    assert overview(client)['totals'][0]['categories'] == {'购物': 7000, '退款原类': -5000}
    other_refund = seed(client, 'REFUND2', '80', 'refund')
    assert preview(client, 'refund_payment', other_refund, pay, '71').status_code == 400
    link(client, 'refund_payment', other_refund, pay, '70')
    assert next(r for r in overview(client)['transactions'] if r['id'] == pay['id'])['reconciliation']['refundedCents'] == 10000


def test_refund_categories_cross_month_and_currency_budgets(hub):
    client, _ = hub
    pay = seed(client, category='设备', day='2026-08-30')
    refund = seed(client, 'REFUND', '30', 'refund', '待核对退款')
    usd = seed(client, 'USD-PAY', currency='USD')
    assert preview(client, 'refund_payment', refund, usd).status_code == 400
    assert client.put('/api/finance-hub/budgets', json={'month':'2026-09','currency':'CNY','category':'设备','amount':'100'}).status_code == 200
    relation = link(client, 'refund_payment', refund, pay, '20')
    budget = overview(client)['budgets'][0]
    assert budget['spentCents'] == -2000 and budget['remainingCents'] == 12000
    assert revoke(client, relation).status_code == 200
    assert overview(client)['budgets'][0]['spentCents'] == 0


def test_stale_preview_rejected_after_other_relationship_or_record_edit(hub):
    client, _ = hub
    pay = seed(client)
    refund = seed(client, 'REFUND', '30', 'refund')
    duplicate = seed(client, 'DUP')
    pending = preview(client, 'refund_payment', refund, pay)
    link(client, 'duplicate', duplicate, pay)
    assert confirm(client, pending).status_code == 409
    pending = preview(client, 'refund_payment', refund, pay)
    current = next(r for r in overview(client)['transactions'] if r['id'] == pay['id'])
    assert client.patch('/api/finance-hub/transactions/'+pay['id'], json={'revision':current['revision'],'category':'新分类'}).status_code == 200
    assert confirm(client, pending).status_code == 409


def test_active_links_protect_directions_delete_and_duplicate_chains(hub):
    client, _ = hub
    pay, duplicate, another = seed(client), seed(client, 'DUP'), seed(client, 'ANOTHER')
    relation = link(client, 'duplicate', duplicate, pay)
    assert preview(client, 'duplicate', pay, duplicate).status_code == 400
    assert preview(client, 'duplicate', pay, another).status_code == 400
    assert preview(client, 'duplicate', another, duplicate).status_code == 400
    current = next(r for r in overview(client)['transactions'] if r['id'] == duplicate['id'])
    assert client.patch('/api/finance-hub/transactions/'+duplicate['id'], json={'revision':current['revision'],'flow':'transfer'}).status_code == 409
    assert client.delete('/api/finance-hub/transactions/'+duplicate['id'], json={'revision':current['revision']}).status_code == 409
    assert revoke(client, relation).status_code == 200
    current = next(r for r in overview(client)['transactions'] if r['id'] == duplicate['id'])
    assert client.delete('/api/finance-hub/transactions/'+duplicate['id'], json={'revision':current['revision']}).status_code == 200
    history = client.get(BASE+'?transactionId='+pay['id']).json['relations']
    assert history[0]['status'] == 'revoked' and history[0]['left'] is None


@pytest.mark.parametrize('uid,status', [('anonymous',401),('tv',403),('member2',404)])
def test_private_candidates_preview_and_revoke(hub, uid, status):
    client, _ = hub
    pay, duplicate = seed(client), seed(client, 'DUP')
    headers = {'X-Test-Actor':uid}
    assert client.get(BASE+'?transactionId='+pay['id'], headers=headers).status_code == status
    assert preview(client,'duplicate',duplicate,pay,uid=uid).status_code == status
    p = preview(client,'duplicate',duplicate,pay)
    assert confirm(client,p,uid).status_code == (403 if uid == 'member2' else status)
    relation = confirm(client,p).json['relation']
    assert revoke(client,relation,uid).status_code == status


def test_partner_record_cannot_be_linked_and_shared_is_aggregate_only(hub):
    client, _ = hub
    pay, duplicate = seed(client), seed(client, 'SECRET-DUP', uid='member2')
    assert preview(client,'duplicate',duplicate,pay).status_code == 404
    mine = seed(client,'OWN-DUP')
    for row in (pay,mine):
        assert client.patch('/api/finance-hub/transactions/'+row['id'], json={'revision':row['revision'],'visibility':'shared'}).status_code == 200
    link(client,'duplicate',mine,pay)
    shared = client.get('/api/finance-hub/shared?month=2026-09',headers={'X-Test-Actor':'member2'})
    assert shared.json['totals'][0]['netSpendCents'] == 10000 and shared.json['totals'][0]['count'] == 1
    assert set(shared.json['totals'][0]) == {'currency','expenseCents','refundCents','netSpendCents','count'}
    assert pay['id'] not in shared.text and 'OWN-DUP' not in shared.text


def test_identifier_candidates_search_partial_and_raw_ids_preserved(hub):
    client, _ = hub
    data = {'source':'alipay','csv':'日期,名称,金额,收支,交易号,商户订单号,支付单号,原交易号\n2026-09-02,PRIVATE_PAY,100,支出,TX001,ORDER001,PAYMENT001,ORIGINAL001\n'}
    assert upload(client,data).status_code == 200
    pay = overview(client)['transactions'][0]
    assert pay['merchantOrderId']=='ORDER001' and pay['paymentId']=='PAYMENT001' and pay['originalTransactionId']=='ORIGINAL001'
    order = seed(client,'ORDER001','50',kind='orders',day='2026-07-01')
    candidates = client.get(BASE+'?transactionId='+order['id']).json['candidates']
    assert len(candidates)==1 and candidates[0]['identifierMatch'] is True
    arbitrary = seed(client,'ARBITRARY','45',kind='orders',day='2026-01-01')
    assert not client.get(BASE+'?transactionId='+arbitrary['id']).json['candidates']
    candidates = client.get(BASE+'?transactionId='+arbitrary['id']+'&q=PRIVATE_PAY').json['candidates']
    assert len(candidates)==1 and not candidates[0]['identifierMatch']


def test_without_ids_preserves_distinct_rows_and_cross_file_duplicates(hub):
    client, _ = hub
    value = {'source':'generic','csv':'date,title,amount,currency,flow\n2026-09-02,SAME,10,CNY,expense\n2026-09-02,SAME,10,CNY,expense\n'}
    assert upload(client,value).json['imported']==2
    assert upload(client,value).json['imported']==0
    other = {**value,'csv':value['csv'].replace('date,title','日期,title')}
    assert upload(client,other).json['imported']==2
    assert overview(client)['transactionCount']==4
    row=overview(client)['transactions'][0]
    assert len(client.get(BASE+'?transactionId='+row['id']).json['candidates'])==3


@pytest.mark.parametrize('amount',[True,-1,0,'0.001','NaN','Infinity','101'])
def test_bad_allocation_amount_rejected(hub, amount):
    client, _=hub
    pay=seed(client)
    order=seed(client,'ORDER',kind='orders')
    assert preview(client,'order_payment',order,pay,amount).status_code==400


def test_revoked_preview_cannot_reactivate_and_fresh_confirmation_can(hub):
    client,_=hub
    pay,duplicate=seed(client),seed(client,'DUP')
    p=preview(client,'duplicate',duplicate,pay)
    relation=confirm(client,p).json['relation']
    assert revoke(client,relation).status_code==200
    assert confirm(client,p).status_code==409
    relation2=link(client,'duplicate',duplicate,pay)
    assert relation2['id']==relation['id'] and relation2['revision']==3
    assert revoke(client,relation).status_code==409


def test_duplicate_refund_and_changed_original_category_keep_exact_budget(hub):
    client,_=hub
    pay=seed(client,category='旧分类')
    refund=seed(client,'REFUND','30','refund','退款分类')
    repeated=seed(client,'REFUND-COPY','30','refund','另一退款分类',source='wechat')
    assert overview(client)['totals'][0]['netSpendCents']==4000
    link(client,'refund_payment',refund,pay)
    duplicate=link(client,'duplicate',repeated,refund)
    result=overview(client)
    assert result['totals'][0]['netSpendCents']==7000
    current=next(row for row in result['transactions'] if row['id']==pay['id'])
    assert client.patch('/api/finance-hub/transactions/'+pay['id'],json={'revision':current['revision'],'category':'新分类'}).status_code==200
    assert overview(client)['totals'][0]['categories']=={'新分类':7000}
    assert revoke(client,duplicate).status_code==200
    assert overview(client)['totals'][0]['netSpendCents']==4000
    assert overview(client)['totals'][0]['categories']=={'新分类':7000,'另一退款分类':-3000}


def test_same_user_id_another_household_cannot_reuse_preview(app):
    primary,headers=member(app)
    data=payload('2026-09-02,A,100,CNY,expense,购物,A001,成功\n2026-09-02,B,100,CNY,expense,购物,B001,成功\n')
    initial=primary.post('/api/finance-hub/imports/preview',json=data,headers=headers)
    assert primary.post('/api/finance-hub/imports/confirm',json={**data,'previewToken':initial.json['previewToken']},headers=headers).status_code==200
    rows=primary.get('/api/finance-hub/overview?month=2026-09').json['transactions']
    pair={'kind':'duplicate','leftId':rows[0]['id'],'rightId':rows[1]['id']}
    # The actual app's shared CSRF guard protects the newly registered endpoints.
    assert primary.post(BASE+'/preview',json=pair).status_code==403
    p=primary.post(BASE+'/preview',json=pair,headers=headers)
    assert p.status_code==200
    secondary,_,entry=create_space(app)
    assert secondary.get(entry['entry']).status_code==303
    assert secondary.post('/api/login',json={'username':'member1','password':'second-home-password-one'}).status_code==200
    other_headers={'X-CSRF-Token':secondary.get('/api/me').json['csrf']}
    assert secondary.get(BASE+'?transactionId='+rows[0]['id']).status_code==404
    assert secondary.post(BASE+'/preview',json=pair,headers=other_headers).status_code==404
    assert secondary.post(BASE+'/confirm',json={'previewToken':p.json['previewToken']},headers=other_headers).status_code==400
    assert secondary.get('/api/finance-hub/overview?month=2026-09').json['transactionCount']==0
    assert primary.get('/api/finance-hub/overview?month=2026-09').json['totals'][0]['netSpendCents']==20000
