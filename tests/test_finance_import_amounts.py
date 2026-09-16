"""Unambiguous imported money, synthetic CSV/OOXML and historical identity."""
import csv
import io

import pytest

from finance_hub import cents
from test_finance_hub import hub, overview, upload
from test_financial_files import workbook, file_payload
from test_taobao_order_groups import payload as grouped_order

PREFIX = '/api/finance-hub/imports/'


def money_payload(amount, format='csv', **extras):
    rows = [['date', 'title', 'amount', 'currency', 'flow', 'category', 'id'],
            ['2026-09-01', 'SYNTHETIC_AMOUNT', amount, 'CNY', 'expense', '合成分类', 'synthetic-id']]
    if format == 'xlsx':
        value = {'file': file_payload(workbook(rows=rows))}
    else:
        stream = io.StringIO(newline='')
        csv.writer(stream, lineterminator='\n').writerows(rows)
        value = {'csv': stream.getvalue()} if format == 'csv' else {
            'file': file_payload(stream.getvalue().encode(), 'synthetic.csv')}
    return {'source': 'generic', 'kind': 'payments', **value, **extras}


@pytest.mark.parametrize('format', ['csv', 'csv-file', 'xlsx'])
@pytest.mark.parametrize('amount', ['1,23', '12,34.56', '1，23', '1,234，567.89', '1,,234',
                                   ',123', '123,', '1.2,3', '1e2', '+1', '-1', '1.001', 'NaN'])
def test_ambiguous_file_amount_blocks_preview_and_all_writes(hub, format, amount):
    client, _ = hub
    value = money_payload(amount, format)
    shown = client.post(PREFIX + 'preview', json=value)
    assert shown.status_code == 200 and shown.json['errorCount'] == 1
    assert shown.json['previewToken'] is None and shown.json['rows'] == []
    assert client.post(PREFIX + 'confirm', json={**value, 'previewToken': None}).status_code == 400
    assert overview(client)['totalRecordCount'] == 0


@pytest.mark.parametrize('format', ['csv', 'xlsx'])
@pytest.mark.parametrize('amount,expected', [('0', 0), ('0.01', 1), ('1234.56', 123456),
    ('1,234.56', 123456), ('1，234.56', 123456), ('￥1,234.56', 123456), ('¥10.50', 1050),
    (' 10.50 ', 1050), ('1000000000000.00', 100000000000000)])
def test_valid_money_preserves_cents_dedup_and_budget(hub, format, amount, expected):
    client, _ = hub
    value = money_payload(amount, format)
    assert upload(client, value).json['imported'] == 1
    assert upload(client, value).json['duplicates'] == 1
    state = overview(client)
    assert state['transactions'][0]['amountCents'] == expected
    assert state['totals'][0]['netSpendCents'] == expected
    assert client.put('/api/finance-hub/budgets', json={'month': '2026-09', 'currency': 'CNY',
                      'category': '全部', 'amount': '2000', 'revision': 0}).status_code == 200
    assert overview(client)['budgets'][0]['spentCents'] == expected


def test_one_bad_row_blocks_other_valid_rows_and_token(hub):
    client, _ = hub
    value = money_payload('10.00')
    value['csv'] += '2026-09-02,SYNTHETIC_BAD,"1,23",CNY,expense,合成分类,bad-id\n'
    shown = client.post(PREFIX + 'preview', json=value).json
    assert len(shown['rows']) == 1 and shown['errorCount'] == 1 and shown['previewToken'] is None
    assert overview(client)['transactions'] == []


def test_selected_money_strict_but_legacy_default_identity_remains_read_only(hub, monkeypatch):
    client, _ = hub
    value = {'source': 'generic', 'kind': 'payments', 'amountColumn': 0,
             'csv': 'amount,date,title,amount,currency,flow\n"1,23",2026-09-02,SYNTHETIC_LEGACY,80.00,CNY,expense\n'}
    # Seed only this temporary DB using the actual former parser, as a previous
    # release could have saved the ambiguous default. Never rewrite old rows.
    with monkeypatch.context() as previous_release:
        previous_release.setattr('finance_hub.import_cents', cents)
        assert upload(client, value).json['imported'] == 1
    old = overview(client)['transactions'][0]
    assert old['amountCents'] == 12300
    invalid = client.post(PREFIX + 'preview', json=value).json
    assert invalid['errorCount'] == 1 and invalid['previewToken'] is None
    chosen = {**value, 'amountColumn': 3}
    shown = client.post(PREFIX + 'preview', json=chosen).json
    assert shown['rows'][0]['amountCents'] == 8000 and shown['duplicateCount'] == shown['conflictCount'] == 1
    receipt = client.post(PREFIX + 'confirm', json={**chosen, 'previewToken': shown['previewToken']}).json
    assert receipt['imported'] == 0 and receipt['duplicates'] == receipt['conflicts'] == 1
    assert overview(client)['transactions'] == [old]


@pytest.mark.parametrize('amount', ['1,23', '12,34.56', '1，23', '1,234，567.89'])
def test_grouped_taobao_anchor_rejects_ambiguous_paid_amount(hub, amount):
    client, _ = hub
    def modify(rows, refs):
        rows[1][9] = amount
    value = grouped_order((('SYNTHETIC_ORDER', 2),), mutate=modify)
    shown = client.post(PREFIX + 'preview', json=value).json
    assert shown['amountSelection']['selectedIndex'] == 9
    assert shown['errorCount'] == 1 and shown['previewToken'] is None
    assert overview(client)['transactions'] == []


def test_grouped_taobao_counts_paid_once_and_does_not_parse_item_price_text(hub):
    client, _ = hub
    def modify(rows, refs):
        rows[1][9] = '￥1,234.56'
        rows[1][8] = '1,23'
        rows[2][8] = '12,34.56 / 套'
        rows[1][10] = '5,00（原文）'
    value = grouped_order((('SYNTHETIC_ORDER', 2),), mutate=modify)
    assert upload(client, value).json['imported'] == 1
    row = overview(client)['transactions'][0]
    assert row['amountCents'] == 123456 and len(row['orderItems']) == 2
    assert row['orderItems'][0]['listedAmountText'] == '1,23'
    assert row['orderGroup']['shippingAmountText'] == '5,00（原文）'
    assert overview(client)['totals'][0]['orderCents'] == 123456
    assert overview(client)['totals'][0]['netSpendCents'] == 0


def test_manual_money_parser_is_unchanged():
    assert cents('1,23') == 12300 and cents('1e2') == 10000
