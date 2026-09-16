"""Complete private ledger browsing with synthetic records and temporary SQLite."""
import sqlite3

import pytest

from test_app import app, member
from test_finance_hub import hub, overview, payload, upload
from test_finance_reconciliation import seed, link, revoke
from test_household_spaces import create_space
from test_taobao_order_groups import payload as grouped_order

BASE = '/api/finance-hub/transactions'


def browse(client, **query):
    response = client.get(BASE, query_string={'month': '2026-09', **query})
    assert response.status_code == 200, response.json
    return response.json


@pytest.mark.parametrize('count', [501, 1001])
def test_complete_pages_and_hidden_record_edit_leave_overview_totals_complete(hub, count):
    client, _ = hub
    expected = set()
    for source, kind in [('alipay', 'payments'), ('wechat', 'payments'), ('taobao', 'orders'), ('pinduoduo', 'orders')]:
        indices = range(['alipay', 'wechat', 'taobao', 'pinduoduo'].index(source), count, 4)
        rows = ''.join(f'2026-09-{i % 28 + 1:02d},SYNTHETIC_{i},1.00,CNY,expense,原分类,id-{i},成功\n' for i in indices)
        expected.update(f'id-{i}' for i in indices)
        assert upload(client, payload(rows, source, kind)).status_code == 200
    initial = browse(client)
    seen = []
    all_rows = []
    for page in range(1, initial['totalPages'] + 1):
        result = browse(client, page=page, snapshot=initial['snapshot'])
        assert result['transactionCount'] == result['filteredCount'] == count
        assert result['pageSize'] == 50 and len(result['transactions']) <= 50
        assert result['hasPrevious'] == (page > 1)
        assert result['hasNext'] == (page < initial['totalPages'])
        seen.extend(row['externalId'] for row in result['transactions'])
        all_rows.extend(result['transactions'])
    assert len(seen) == len(set(seen)) == count and set(seen) == expected
    assert all_rows == sorted(all_rows, key=lambda row: (row['date'], row['id']), reverse=True)
    assert browse(client, page=999999)['page'] == initial['totalPages']
    old = overview(client)
    assert len(old['transactions']) == 500 and old['transactionCount'] == count and old['truncated']
    visible = {row['id'] for row in old['transactions']}
    hidden = next(row for row in all_rows if row['kind'] == 'payments' and row['id'] not in visible)
    assert client.patch(BASE + '/' + hidden['id'], json={'revision': hidden['revision'], 'category': '已核对'}).status_code == 200
    refreshed = browse(client, q=hidden['externalId'])
    assert next(row for row in refreshed['transactions'] if row['id'] == hidden['id'])['category'] == '已核对'
    new = overview(client)
    assert new['totals'][0]['netSpendCents'] == old['totals'][0]['netSpendCents']
    assert new['totals'][0]['categories']['已核对'] == 100
    assert client.put('/api/finance-hub/budgets', json={'month': '2026-09', 'currency': 'CNY',
                      'category': '已核对', 'amount': '10', 'revision': 0}).status_code == 200
    assert overview(client)['budgets'][0]['spentCents'] == 100


def test_search_all_identifiers_items_casefold_month_and_metadata(hub):
    client, _ = hub
    value = {'source': 'generic', 'csv': 'date,title,amount,currency,flow,category,id,merchantOrderId,paymentId,originalTransactionId\n'
             '2026-09-01,AlphaStraße,2,CNY,expense,FoodCategory,extUnique,merchantUnique,paymentUnique,originalUnique\n'
             '2026-08-01,AlphaStraße,2,CNY,expense,FoodCategory,other-month,m2,p2,o2\n'}
    assert upload(client, value).status_code == 200
    assert upload(client, grouped_order((('SYNTHETIC_ORDER', 2),))).status_code == 200
    for query in ['ALPHASTRASSE', 'foodcategory', 'EXTUNIQUE', 'merchantunique', 'paymentunique', 'originalunique',
                  'PRIVATE_ITEM_SYNTHETIC_ORDER_1', 'synthetic_variant']:
        result = browse(client, q=' ' + query + ' ', pageSize=1, page=99)
        assert result['q'] == query and result['filteredCount'] == 1
        assert result['transactionCount'] == 2 and result['page'] == result['totalPages'] == 1
        assert not result['hasPrevious'] and not result['hasNext']
    row = browse(client, q='PRIVATE_ITEM_SYNTHETIC_ORDER_1')['transactions'][0]
    assert len(row['orderItems']) == 2 and row['orderGroup']['itemCount'] == 2
    assert 'reconciliation' in row
    empty = browse(client, q='NO_SYNTHETIC_MATCH', page=999)
    assert empty['transactions'] == [] and empty['filteredCount'] == 0
    assert empty['transactionCount'] == 2 and empty['page'] == empty['totalPages'] == 1
    assert browse(client, month='2025-01')['transactionCount'] == 0
    assert browse(client, q='x' * 160)['filteredCount'] == 0
    first = browse(client)
    assert browse(client, q='Alpha', pageSize=1)['snapshot'] == first['snapshot']
    assert browse(client, snapshot=first['snapshot'].upper())['snapshot'] == first['snapshot']


@pytest.mark.parametrize('query', [
    {'month': '2026-13'}, {'q': 'x' * 161}, {'q': 'a\0b'}, {'page': '0'}, {'page': '-1'},
    {'page': '1.5'}, {'page': 'true'}, {'page': '+1'}, {'page': '01'}, {'page': '9' * 5000},
    {'pageSize': '0'}, {'pageSize': '101'}, {'pageSize': '1.0'}, {'pageSize': '-1'},
    {'snapshot': ''}, {'snapshot': 'f' * 63}, {'snapshot': 'g' * 64}, {'owner': 'member2'},
])
def test_invalid_query_is_400(hub, query):
    client, _ = hub
    assert client.get(BASE, query_string={'month': '2026-09', **query}).status_code == 400


def test_duplicate_parameters_and_current_month_default(hub, monkeypatch):
    client, _ = hub
    assert client.get(BASE + '?page=1&page=2').status_code == 400
    monkeypatch.setattr('finance_hub.current_month', lambda: '2026-09')
    assert client.get(BASE).json['month'] == '2026-09'


def test_snapshot_changes_for_owner_rows_all_months_and_revoked_links_only(hub):
    client, _ = hub
    pay = seed(client, 'SYNTHETIC_PAYMENT')
    refund = seed(client, 'SYNTHETIC_REFUND', '20', 'refund', day='2026-10-01')
    original = browse(client)['snapshot']
    seed(client, 'OTHER_MEMBER', uid='member2')
    assert browse(client, snapshot=original)['snapshot'] == original
    relation = link(client, 'refund_payment', refund, pay)
    stale = client.get(BASE, query_string={'snapshot': original})
    assert stale.status_code == 409 and stale.json['code'] == 'ledger_changed'
    current = browse(client)
    assert current['transactions'][0]['reconciliation']['refundedCents'] == 2000
    assert browse(client, month='2026-10')['transactions'][0]['reconciliation']['categoryAllocations'] == [
        {'category': '购物', 'amountCents': 2000}]
    assert revoke(client, relation).status_code == 200
    assert client.get(BASE, query_string={'snapshot': current['snapshot']}).status_code == 409
    changed = browse(client)['snapshot']
    # Revision-only edits in another month still invalidate this owner's digest.
    revision = browse(client, month='2026-10')['transactions'][0]['revision']
    assert client.patch(BASE + '/' + refund['id'], json={'revision': revision, 'category': '退款已核对'}).status_code == 200
    assert client.get(BASE, query_string={'snapshot': changed}).status_code == 409


def test_read_is_stable_and_does_not_mutate_database(hub):
    client, path = hub
    seed(client)
    with sqlite3.connect(path) as con:
        before = list(con.iterdump())
    snapshot = browse(client)['snapshot']
    assert browse(client, snapshot=snapshot)['snapshot'] == snapshot
    with sqlite3.connect(path) as con:
        assert list(con.iterdump()) == before


def test_rows_and_links_use_one_read_transaction_during_concurrent_write(hub, monkeypatch):
    client, path = hub
    first, second = seed(client, 'FIRST'), seed(client, 'SECOND')
    old = browse(client)
    connect = sqlite3.connect
    with connect(path) as con:
        con.execute('PRAGMA journal_mode=WAL')
    pending = [True]

    class ConcurrentConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            cursor = super().execute(sql, parameters)
            if sql == 'SELECT * FROM hub_transactions WHERE owner=?' and pending:
                def rows_then_write():
                    yield from cursor
                    pending.pop()
                    with connect(path) as writer:
                        writer.execute('UPDATE hub_transactions SET revision=revision+1 WHERE id=?', (first['id'],))
                        writer.execute('INSERT INTO hub_reconciliations VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                                       ('synthetic-link', 'member1', 'duplicate', second['id'], first['id'], 10000,
                                        'active', 1, 'synthetic-digest', '2026-09-01', '2026-09-01'))
                return rows_then_write()
            return cursor

    monkeypatch.setattr(sqlite3, 'connect', lambda *a, **kw: connect(*a, **kw, factory=ConcurrentConnection))
    raced = browse(client)
    assert raced == old  # Never return old rows combined with the new relation.
    fresh = browse(client)
    assert fresh['snapshot'] != old['snapshot']
    assert any(row['reconciliation']['duplicateOf'] == first['id'] for row in fresh['transactions'])


def test_real_sessions_member_tv_and_household_isolation(app):
    primary, headers = member(app)
    value = payload('2026-09-02,PRIVATE_FIRST_HOUSEHOLD,1,CNY,expense,测试,private-id,成功\n')
    preview = primary.post('/api/finance-hub/imports/preview', json=value, headers=headers).json
    assert primary.post('/api/finance-hub/imports/confirm', json={**value, 'previewToken': preview['previewToken']}, headers=headers).status_code == 200
    own = browse(primary)
    partner, _ = member(app, 2)
    assert browse(partner)['transactions'] == []
    assert partner.get(BASE, query_string={'snapshot': own['snapshot']}).status_code == 409
    assert app.test_client().get(BASE).status_code == 401
    tv = app.test_client()
    pair = tv.post('/api/pair/start', json={}).json
    assert primary.post('/api/pair/approve', json={'code': pair['code'], 'name': '合成电视', 'focus': 'member1'}, headers=headers).status_code == 200
    assert tv.post('/api/pair/poll', json={'secret': pair['secret']}).json['approved']
    assert tv.get(BASE).status_code == 403
    secondary, _, entry = create_space(app)
    assert secondary.get(entry['entry']).status_code == 303
    assert secondary.post('/api/login', json={'username': 'member1', 'password': 'second-home-password-one'}).status_code == 200
    assert browse(secondary)['transactions'] == []
    assert secondary.get(BASE, query_string={'snapshot': own['snapshot']}).status_code == 409
    assert 'PRIVATE_FIRST_HOUSEHOLD' not in secondary.get(BASE).get_data(as_text=True)
    assert browse(primary)['transactions'] == own['transactions']
