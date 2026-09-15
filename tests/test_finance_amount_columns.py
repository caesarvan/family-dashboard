"""Amount-column choice with synthetic CSV/OOXML and isolated real API writes."""
import hashlib
import json
import sqlite3

import pytest
from itsdangerous import URLSafeTimedSerializer

from finance_hub import parse_import
from test_finance_hub import hub, overview
from test_financial_files import workbook, import_payload
from test_app import app, member
from test_household_spaces import create_space


def ambiguous(*, numbered=True, source='generic', kind='payments', first='100.00', second='80.00'):
    return {'source': source, 'kind': kind,
            'csv': 'amount,date,title,amount,currency,flow' + (',id' if numbered else '') + '\n'
                   + f'{first},2026-09-02,SYNTHETIC_ONLY,{second},CNY,expense'
                   + (',synthetic-001' if numbered else '') + '\n'}


def preview(client, payload, member='member1'):
    return client.post('/api/finance-hub/imports/preview', json=payload, headers={'X-Test-Actor': member})


def confirm(client, payload, token, member='member1'):
    return client.post('/api/finance-hub/imports/confirm', json={**payload, 'previewToken': token}, headers={'X-Test-Actor': member})


def test_duplicate_headers_require_choice_without_preview_or_ledger_writes(hub):
    client, database = hub
    r = preview(client, ambiguous())
    assert r.status_code == 200
    assert r.json['requiresAmountSelection'] is True
    assert r.json['amountSelection'] == {
        'required': True, 'selectedIndex': None, 'headerLine': 1,
        'columns': [{'index': 0, 'label': 'amount', 'columnLabel': 'A'},
                    {'index': 3, 'label': 'amount', 'columnLabel': 'D'}]}
    assert r.json['rows'] == r.json['totals'] == []
    assert r.json['newCount'] == r.json['duplicateCount'] == r.json['errorCount'] == 0
    assert r.json['previewToken'] is None
    assert confirm(client, ambiguous(), None).status_code == 400
    with sqlite3.connect(database) as con:
        assert con.execute('SELECT count(*) FROM hub_transactions').fetchone()[0] == 0
        assert con.execute('SELECT count(*) FROM hub_imports').fetchone()[0] == 0


@pytest.mark.parametrize('choice', [None, True, False, 0.0, '0', -1, 1, 2, 4, 80, [], {}])
def test_invalid_or_non_amount_index_is_rejected(hub, choice):
    client, _ = hub
    r = preview(client, {**ambiguous(), 'amountColumn': choice})
    assert r.status_code == 400
    assert '金额列选择无效' in r.json['error']
    assert overview(client)['totalRecordCount'] == 0


def test_first_column_zero_and_single_column_preserve_integer_cents(hub):
    client, _ = hub
    p = {'source': 'generic', 'csv': 'amount,date,title,currency,flow,id\n0.01,2026-09-02,SYNTHETIC,CNY,expense,single\n'}
    r = preview(client, p)
    assert r.status_code == 200 and r.json['previewToken']
    assert not r.json['requiresAmountSelection']
    assert r.json['amountSelection']['selectedIndex'] == 0
    assert not r.json['amountSelection']['required']
    assert r.json['rows'][0]['amountCents'] == 1
    assert confirm(client, p, r.json['previewToken']).json['imported'] == 1
    p = {**ambiguous(), 'amountColumn': 0}
    r = preview(client, p)
    assert r.json['rows'][0]['amountCents'] == 10000


@pytest.mark.parametrize('encoding', ['utf-8-sig', 'gb18030'])
def test_chinese_alias_candidates_csv_and_xlsx_keep_positions(hub, encoding):
    from test_financial_files import file_payload
    client, _ = hub
    header = ['订单创建时间', '商品名称', '订单金额', '实付款', '币种', '订单号']
    row = ['2026-09-02', '合成采购', '100.00', '80.00', 'CNY', 'synthetic-order']
    text = ','.join(header) + '\n' + ','.join(row) + '\n'
    files = [file_payload(text.encode(encoding), 'synthetic.csv'),
             file_payload(workbook(rows=[['SYNTHETIC_PREAMBLE'], header, row]), 'synthetic.xlsx')]
    for file in files:
        p = {'source': 'taobao', 'kind': 'orders', 'file': file}
        r = preview(client, p)
        assert r.status_code == 200 and r.json['requiresAmountSelection']
        assert [c['index'] for c in r.json['amountSelection']['columns']] == [2, 3]
        selected = preview(client, {**p, 'amountColumn': 3})
        assert selected.status_code == 200
        assert selected.json['rows'][0]['amountCents'] == 8000
        assert selected.json['totals'][0]['orderCents'] == 8000
        assert selected.json['totals'][0]['netSpendCents'] == 0
    assert overview(client)['totalRecordCount'] == 0


@pytest.mark.parametrize('change', ['column', 'file', 'source', 'kind'])
def test_confirmation_token_binds_choice_and_original_input(hub, change):
    client, _ = hub
    p = {**ambiguous(), 'amountColumn': 3}
    token = preview(client, p).json['previewToken']
    changed = dict(p)
    if change == 'column': changed['amountColumn'] = 0
    elif change == 'file': changed['csv'] = changed['csv'].replace('80.00', '81.00')
    elif change == 'source': changed['source'] = 'alipay'
    else: changed['kind'] = 'orders'
    assert confirm(client, changed, token).status_code == 400
    assert overview(client)['totalRecordCount'] == 0
    r = preview(client, changed)
    assert r.json['previewToken']
    assert confirm(client, changed, r.json['previewToken']).json['imported'] == 1


@pytest.mark.parametrize('numbered', [True, False])
def test_reselecting_same_file_reports_conflict_without_creating_another_payment(hub, numbered):
    client, _ = hub
    p = {**ambiguous(numbered=numbered), 'amountColumn': 3}
    token = preview(client, p).json['previewToken']
    assert confirm(client, p, token).json['imported'] == 1
    assert confirm(client, p, token).json['duplicates'] == 1
    other = {**p, 'amountColumn': 0}
    r = preview(client, other)
    assert r.json['newCount'] == 0 and r.json['duplicateCount'] == 1
    receipt = confirm(client, other, r.json['previewToken']).json
    assert receipt['imported'] == 0 and receipt['conflicts'] == 1
    state = overview(client)
    assert state['totalRecordCount'] == 1
    assert state['transactions'][0]['amountCents'] == 8000
    assert state['totals'][0]['netSpendCents'] == 8000


def test_unparseable_former_default_does_not_block_valid_choice_or_create_duplicates(hub):
    client, _ = hub
    p = {**ambiguous(numbered=False, first='unavailable'), 'amountColumn': 3}
    r = preview(client, p)
    assert r.json['errorCount'] == 0 and r.json['rows'][0]['amountCents'] == 8000
    assert confirm(client, p, r.json['previewToken']).json['imported'] == 1
    assert confirm(client, p, r.json['previewToken']).json['duplicates'] == 1
    invalid = preview(client, {**p, 'amountColumn': 0})
    assert invalid.json['errorCount'] == 1 and invalid.json['previewToken'] is None


@pytest.mark.parametrize('former_default', ['100.00', 'unavailable'])
def test_three_aliases_preserve_identity_when_legacy_default_is_middle_column(hub, former_default):
    client, _ = hub
    payload = {'source': 'generic', 'kind': 'payments',
               'csv': '实付款,date,amount,title,currency,总金额,flow\n'
                      f'80.00,2026-09-02,{former_default},SYNTHETIC_THREE,CNY,70.00,expense\n'}
    initial = preview(client, payload).json
    assert [column['index'] for column in initial['amountSelection']['columns']] == [0, 2, 5]
    first = {**payload, 'amountColumn': 0}
    token = preview(client, first).json['previewToken']
    assert confirm(client, first, token).json['imported'] == 1
    second = {**payload, 'amountColumn': 5}
    changed = preview(client, second).json
    assert changed['duplicateCount'] == 1 and changed['newCount'] == 0
    receipt = confirm(client, second, changed['previewToken']).json
    assert receipt['conflicts'] == 1 and receipt['imported'] == 0
    assert overview(client)['totalRecordCount'] == 1
    assert overview(client)['transactions'][0]['amountCents'] == 8000


def test_legacy_unsigned_choice_cannot_confirm_ambiguous_file_and_legacy_identity_is_kept(hub):
    client, _ = hub
    p = ambiguous(numbered=False)
    digest = hashlib.sha256(json.dumps({k: p.get(k, 'generic' if k == 'source' else 'payments' if k == 'kind' else '')
                                      for k in ('source', 'kind', 'csv', 'file')}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    signer = URLSafeTimedSerializer('synthetic-testing-secret', salt='household-finance-preview-v1')
    old = signer.dumps({'owner': 'member1', 'digest': digest})
    assert confirm(client, p, old).status_code == 400
    selected = parse_import({**p, 'amountColumn': 3})['rows'][0]
    file_digest = hashlib.sha256(p['csv'].encode()).hexdigest()
    old_identity = ['generic', 'payments', file_digest, 2, '2026-09-02', 'SYNTHETIC_ONLY', 10000, 'CNY', 'expense']
    assert selected['fingerprint'] == hashlib.sha256(json.dumps(old_identity, ensure_ascii=False).encode()).hexdigest()


def test_selected_preview_is_owner_only_and_tv_cannot_preview_or_confirm(hub):
    client, _ = hub
    p = {**ambiguous(), 'amountColumn': 3}
    token = preview(client, p).json['previewToken']
    assert confirm(client, p, token, 'member2').status_code == 400
    assert preview(client, p, 'tv').status_code == 403
    assert confirm(client, p, token, 'tv').status_code == 403
    assert preview(client, p, 'anonymous').status_code == 401
    assert confirm(client, p, token).json['imported'] == 1
    assert overview(client, 'member2')['totalRecordCount'] == 0
    assert client.get('/api/finance-hub/shared?month=2026-09', headers={'X-Test-Actor': 'member2'}).json['totals'] == []


@pytest.mark.parametrize('value', ['-1', '0.001', 'NaN', 'Infinity'])
def test_selected_invalid_money_still_blocks_confirmation(hub, value):
    client, _ = hub
    r = preview(client, {**ambiguous(second=value), 'amountColumn': 3})
    assert r.status_code == 200 and r.json['errorCount'] == 1
    assert r.json['previewToken'] is None


def test_sheet_change_requires_reselection_and_cannot_reuse_signed_preview(hub):
    client, _ = hub
    raw = workbook(rows=[['交易时间', '商品', '金额(元)', '实付款', '收/支', '交易单号'],
                         ['2026-09-02', '合成', '100', '80', '支出', 'synthetic']], second_sheet=True)
    p = {**import_payload(raw), 'amountColumn': 3}
    r = preview(client, p)
    changed = {**p, 'file': {**p['file'], 'sheet': '订单'}}
    assert confirm(client, changed, r.json['previewToken']).status_code == 400
    assert preview(client, changed).status_code == 400  # column D is flow in the other sheet
    del changed['amountColumn']
    assert preview(client, changed).json['amountSelection']['selectedIndex'] == 2


def test_actual_household_router_and_member_sessions_reject_foreign_selection_token(app):
    parent, headers = member(app)
    p = {**ambiguous(), 'amountColumn': 3}
    token = parent.post('/api/finance-hub/imports/preview', json=p, headers=headers).json['previewToken']
    child, _, space = create_space(app)
    assert child.get(space['entry']).status_code == 303
    assert child.post('/api/login', json={'username': 'member1', 'password': 'second-home-password-one'}).status_code == 200
    child_headers = {'X-CSRF-Token': child.get('/api/me').json['csrf']}
    assert child.post('/api/finance-hub/imports/confirm', json={**p, 'previewToken': token}, headers=child_headers).status_code == 400
    assert child.get('/api/finance-hub/overview?month=2026-09').json['totalRecordCount'] == 0
    assert parent.post('/api/finance-hub/imports/confirm', json={**p, 'previewToken': token}, headers=headers).json['imported'] == 1
    assert child.get('/api/finance-hub/overview?month=2026-09').json['totalRecordCount'] == 0
