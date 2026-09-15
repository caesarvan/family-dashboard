"""Known order-export headers with wholly synthetic CSV/OOXML and real local APIs.

No native archive, private input, provider, or network is used by these fixtures.
"""
import csv
import hashlib
import io
from pathlib import Path
import socket
import sqlite3

import pytest

from finance_hub import ALIASES, FinanceHubError, parse_import
from test_app import app, member
from test_financial_files import file_payload, workbook


HEADERS = {
    'taobao': ['订单号', '订单提交时间', '订单状态', '店铺名称', '商品名称',
               '商品链接', '型号款式', '商品数量', '商品金额', '实付金额', '运费'],
    'pinduoduo': ['下单时间', '订单号', '商品名', '规格', '数量', '实付金额',
                 '店铺名', '订单状态', '商品链接', '订单类型', '备注'],
}
VALUES = {
    '订单号': 'SYNTHETIC-ORDER-001', '订单提交时间': '2025-02-03 12:34:56',
    '下单时间': '2025-02-03 12:34:56', '订单状态': '交易成功',
    '店铺名称': 'SYNTHETIC_SHOP', '店铺名': 'SYNTHETIC_SHOP',
    '商品名称': 'SYNTHETIC_PRODUCT', '商品名': 'SYNTHETIC_PRODUCT',
    '商品链接': 'https://example.invalid/synthetic-product',
    '型号款式': 'SYNTHETIC_OPTION', '规格': 'SYNTHETIC_OPTION',
    '商品数量': '2', '数量': '2', '商品金额': '99.00', '实付金额': '12.34',
    '运费': '5.00', '订单类型': 'SYNTHETIC_TYPE', '备注': 'SYNTHETIC_NOTE',
}
PREFIX = '/api/finance-hub/'


@pytest.fixture(autouse=True)
def no_network_and_owned_sources_unchanged(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError('Network is forbidden in synthetic order-header tests')
    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr(socket.socket, 'connect_ex', blocked)
    monkeypatch.setattr(socket, 'create_connection', blocked)
    root = Path(__file__).resolve().parents[1]
    paths = [root / 'finance_hub.py', Path(__file__).resolve(), root / 'financial_files.py']
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    yield
    assert before == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def table_payload(source, format='csv', *, duplicate=False, extra=None, overrides=None):
    labels = HEADERS[source] + list(extra or {})
    values = {**VALUES, **(extra or {}), **(overrides or {})}
    row = [values[label] for label in labels]
    rows = [labels, row] + ([row] if duplicate else [])
    if format == 'xlsx':
        file = file_payload(workbook(rows=rows), 'synthetic-orders.xlsx', sheet='支付账单')
    else:
        buffer = io.StringIO(newline='')
        csv.writer(buffer).writerows(rows)
        file = file_payload(buffer.getvalue().encode('utf-8-sig'), 'synthetic-orders.csv')
    return {'source': source, 'kind': 'orders', 'file': file}


def database_snapshot(app, tables):
    target = Path(app.config['DATA_DIR']) / 'household.sqlite3'
    with sqlite3.connect(target) as con:
        # A confirmed import intentionally increments the app's refresh revision;
        # every other setting, including the shared wallet, must remain byte-identical.
        return {table: con.execute('SELECT * FROM "' + table + '"'
                                   + (" WHERE id != 'meta'" if table == 'settings' else '')
                                   + ' ORDER BY rowid').fetchall()
                for table in tables}


def preview(client, headers, value):
    response = client.post(PREFIX + 'imports/preview', json=value, headers=headers)
    assert response.status_code == 200, response.json
    return response.json


def confirm(client, headers, value, token):
    return client.post(PREFIX + 'imports/confirm',
                       json={**value, 'previewToken': token}, headers=headers)


@pytest.mark.parametrize('source', ['taobao', 'pinduoduo'])
@pytest.mark.parametrize('format', ['csv', 'xlsx'])
def test_known_order_table_parse_preview_confirm_month_readback_and_dedupe(app, source, format):
    client, headers = member(app)
    value = table_payload(source, format, duplicate=True)
    parsed = parse_import(value)
    assert parsed['errorCount'] == 0 and len(parsed['rows']) == 2
    assert parsed['amountSelection']['selectedIndex'] == HEADERS[source].index('实付金额')
    assert len(parsed['amountSelection']['columns']) == 1  # List price/freight are not paid aliases.
    expected = {'title': 'SYNTHETIC_PRODUCT', 'date': '2025-02-03', 'amountCents': 1234,
                'currency': 'CNY', 'externalId': 'SYNTHETIC-ORDER-001', 'source': source,
                'kind': 'orders', 'flow': 'unknown', 'visibility': 'private'}
    assert all(parsed['rows'][0][key] == val for key, val in expected.items())
    unchanged_tables = ['settings', 'entities', 'finance_baselines', 'private_finance',
                        'hub_budgets', 'hub_investments', 'hub_reconciliations']
    unchanged = database_snapshot(app, unchanged_tables)
    before = database_snapshot(app, ['hub_transactions', 'hub_imports', 'audit'])
    shown = preview(client, headers, value)
    assert shown['previewToken'] and shown['newCount'] == shown['duplicateCount'] == 1
    assert shown['totals'][0]['orderCents'] == 1234
    assert shown['totals'][0]['netSpendCents'] == 0
    assert before == database_snapshot(app, list(before))
    assert confirm(client, headers, value, None).status_code == 400
    changed_file = table_payload(source, format, duplicate=True, overrides={'实付金额': '12.35'})
    assert confirm(client, headers, changed_file, shown['previewToken']).status_code == 400
    result = confirm(client, headers, value, shown['previewToken'])
    assert result.status_code == 200, result.json
    assert {key: result.json[key] for key in ('imported', 'duplicates', 'conflicts')} == {
        'imported': 1, 'duplicates': 1, 'conflicts': 0}
    assert result.json['resultMonths'] == [{'month': '2025-02', 'recordCount': 1}]
    readback = client.get(PREFIX + 'overview?month=2025-02').json
    assert readback['availableMonths'] == result.json['resultMonths']
    assert readback['totalRecordCount'] == readback['transactionCount'] == 1
    record = readback['transactions'][0]
    assert all(record[key] == val for key, val in expected.items())
    assert record['checkedAt'] is None
    assert record['reconciliation']['relationCount'] == record['reconciliation']['allocatedCents'] == 0
    assert readback['totals'][0]['expenseCents'] == readback['totals'][0]['netSpendCents'] == 0
    assert client.get(PREFIX + 'overview?month=2025-03').json['transactions'] == []
    post_import = database_snapshot(app, ['hub_transactions', 'hub_imports', 'audit'])
    replay = confirm(client, headers, value, shown['previewToken']).json
    assert replay['imported'] == 0 and replay['duplicates'] == 2 and replay['conflicts'] == 0
    again = preview(client, headers, value)
    assert again['newCount'] == 0 and again['duplicateCount'] == 2
    assert confirm(client, headers, value, again['previewToken']).json['imported'] == 0
    assert post_import == database_snapshot(app, list(post_import))
    assert unchanged == database_snapshot(app, unchanged_tables)
    assert client.get(PREFIX + 'shared?month=2025-02').json['totals'] == []


@pytest.mark.parametrize('label', ['title', '商品名称', '商品说明', '交易对方'])
def test_pinduoduo_specific_title_does_not_replace_existing_title_columns(label):
    parsed = parse_import(table_payload('pinduoduo', extra={label: 'SYNTHETIC_PREFERRED'}))
    assert parsed['rows'][0]['title'] == 'SYNTHETIC_PREFERRED'


@pytest.mark.parametrize('source,kind', [('generic', 'orders'), ('taobao', 'orders'),
                                        ('wechat', 'orders'), ('alipay', 'orders'),
                                        ('pinduoduo', 'payments')])
def test_product_name_alias_is_only_for_pinduoduo_orders(source, kind):
    value = table_payload('pinduoduo', extra={'currency': 'CNY'})
    parsed = parse_import({**value, 'source': source, 'kind': kind})
    assert parsed['rows'][0]['title'] == 'SYNTHETIC_NOTE'
    assert '商品名' not in ALIASES['title']


@pytest.mark.parametrize('source,kind', [('generic', 'orders'), ('pinduoduo', 'orders'),
                                        ('wechat', 'payments'), ('alipay', 'payments'),
                                        ('taobao', 'payments')])
def test_submitted_date_alias_is_only_for_taobao_orders(source, kind):
    value = table_payload('taobao', extra={'currency': 'CNY'})
    with pytest.raises(FinanceHubError, match='未识别日期与金额列'):
        parse_import({**value, 'source': source, 'kind': kind})
    assert '订单提交时间' not in ALIASES['date']


def test_existing_date_precedes_submitted_date_and_invalid_submitted_date_is_not_guessed():
    parsed = parse_import(table_payload('taobao', extra={'付款时间': '2025-03-04'}))
    assert parsed['rows'][0]['date'] == '2025-03-04'
    invalid = parse_import(table_payload('taobao', overrides={'订单提交时间': '2025-02-30'}))
    assert invalid['errorCount'] == 1 and invalid['rows'] == []


@pytest.mark.parametrize('source', ['taobao', 'pinduoduo'])
def test_new_aliases_keep_explicit_amount_selection_and_signed_choice(app, source):
    client, headers = member(app)
    value = table_payload(source, extra={'订单金额': '88.00'})
    shown = preview(client, headers, value)
    assert shown['requiresAmountSelection'] and shown['previewToken'] is None
    assert shown['rows'] == shown['totals'] == []
    assert confirm(client, headers, value, None).status_code == 400
    selected = {**value, 'amountColumn': HEADERS[source].index('实付金额')}
    checked = preview(client, headers, selected)
    assert checked['rows'][0]['amountCents'] == 1234
    alternate = {**value, 'amountColumn': len(HEADERS[source])}
    assert confirm(client, headers, alternate, checked['previewToken']).status_code == 400
    assert confirm(client, headers, selected, checked['previewToken']).json['imported'] == 1
    reselected = preview(client, headers, alternate)
    conflict = confirm(client, headers, alternate, reselected['previewToken']).json
    assert conflict['imported'] == 0 and conflict['conflicts'] == 1
    readback = client.get(PREFIX + 'overview?month=2025-02').json
    assert readback['totalRecordCount'] == 1 and readback['totals'][0]['orderCents'] == 1234
    assert readback['totals'][0]['expenseCents'] == 0


@pytest.mark.parametrize('source', ['taobao', 'pinduoduo'])
def test_actual_members_and_paired_tv_cannot_read_or_confirm_others_orders(app, source):
    owner, headers = member(app)
    other, other_headers = member(app, 2)
    anonymous = app.test_client()
    tv = app.test_client()
    pair = tv.post('/api/pair/start', json={}).json
    assert owner.post('/api/pair/approve', json={'code': pair['code'], 'name': 'SYNTHETIC_TV',
                                               'focus': 'member1'}, headers=headers).status_code == 200
    assert tv.post('/api/pair/poll', json={'secret': pair['secret']}).json['approved']
    value = table_payload(source)
    shown = preview(owner, headers, value)
    assert confirm(other, other_headers, value, shown['previewToken']).status_code == 400
    assert confirm(owner, {}, value, shown['previewToken']).status_code == 403
    for reader, status in [(anonymous, 401), (tv, 403)]:
        assert reader.get(PREFIX + 'overview?month=2025-02').status_code == status
        assert reader.post(PREFIX + 'imports/preview', json=value, headers=headers).status_code == status
        assert confirm(reader, headers, value, shown['previewToken']).status_code == status
    assert confirm(owner, headers, value, shown['previewToken']).json['imported'] == 1
    assert other.get(PREFIX + 'overview?month=2025-02&owner=member1').json['transactions'] == []
    assert other.get(PREFIX + 'shared?month=2025-02').json['totals'] == []
    rid = owner.get(PREFIX + 'overview?month=2025-02').json['transactions'][0]['id']
    assert other.patch(PREFIX + 'transactions/' + rid, json={'revision': 1, 'category': 'SYNTHETIC'},
                       headers=other_headers).status_code == 404
    for reader in [other, tv]:
        state = reader.get('/api/state')
        assert state.status_code == 200
        assert 'SYNTHETIC_PRODUCT' not in state.get_data(as_text=True)
        assert 'SYNTHETIC-ORDER-001' not in state.get_data(as_text=True)


def test_imported_orders_do_not_duplicate_separate_payment_expense(app):
    client, headers = member(app)
    for source in ['taobao', 'pinduoduo']:
        value = table_payload(source)
        shown = preview(client, headers, value)
        assert confirm(client, headers, value, shown['previewToken']).json['imported'] == 1
    payment = {'source': 'generic', 'kind': 'payments',
               'csv': 'date,title,amount,currency,flow,id\n2025-02-03,SYNTHETIC_PAYMENT,12.34,CNY,expense,SYNTHETIC-PAYMENT\n'}
    shown = preview(client, headers, payment)
    assert confirm(client, headers, payment, shown['previewToken']).json['imported'] == 1
    readback = client.get(PREFIX + 'overview?month=2025-02').json
    assert readback['totalRecordCount'] == 3
    assert readback['totals'][0]['orderCents'] == 2468
    assert readback['totals'][0]['expenseCents'] == readback['totals'][0]['netSpendCents'] == 1234
    assert all(row['checkedAt'] is None and row['reconciliation']['relationCount'] == 0
               for row in readback['transactions'])
    assert database_snapshot(app, ['hub_reconciliations']) == {'hub_reconciliations': []}
    assert client.get(PREFIX + 'shared?month=2025-02').json['totals'] == []
