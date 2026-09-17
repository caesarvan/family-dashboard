"""Synthetic files and real import HTTP/SQLite; no financial/provider fixtures."""
from contextlib import closing
import hashlib
import json
import sqlite3

from itsdangerous import URLSafeTimedSerializer
from itsdangerous.timed import TimestampSigner
import pytest

from finance_hub import FinanceHubError, parse_import
from test_app import app, member
from test_device_sessions import database
from test_financial_files import file_payload, workbook
from test_household_spaces import create_space


MAPPING = {'version': 1, 'headerLine': 1, 'date': 0, 'amount': 1, 'title': 2, 'currency': 3}
TEXT = '自定日,自定额,自定名,自定币\n2026-09-02,10.50,合成记录,CNY\n'


def value(text=TEXT, **extra):
    return {'source': 'generic', 'kind': 'payments', 'csv': text, 'mapping': dict(MAPPING), **extra}


def post(client, headers, route, payload):
    response = client.post('/api/finance-hub/imports/' + route, json=payload, headers=headers)
    assert response.status_code == 200, response.json
    return response.json


def confirm(client, headers, payload, key='a' * 32):
    preview = post(client, headers, 'preview', payload)
    assert preview['previewToken']
    body = {**payload, 'previewToken': preview['previewToken'], 'requestId': key}
    return post(client, headers, 'confirm', body), body


def state(app):
    with closing(sqlite3.connect(database(app))) as con:
        return {name: con.execute('SELECT * FROM ' + name + ' ORDER BY 1').fetchall()
                for name in ('hub_transactions', 'hub_imports', 'hub_import_receipts', 'audit')}


def test_inspect_preserves_empty_duplicate_labels_without_row_samples(app):
    client, headers = member(app)
    before = state(app)
    p = {'source': 'generic', 'csv': ',名称,名称,币种,日期,金额\nprivate,never,returned,CNY,2026-09-02,0\n',
         'inspectColumns': True}
    result = post(client, headers, 'preview', p)
    selection = result['columnSelection']
    assert [col['label'] for col in selection['columns']] == ['', '名称', '名称', '币种', '日期', '金额']
    assert [col['index'] for col in selection['columns']] == list(range(6))
    assert [col['columnLabel'] for col in selection['columns']] == list('ABCDEF')
    assert selection['suggestedMapping'] == {'date': 4, 'amount': 5, 'title': None, 'currency': 3}
    assert selection['lineKind'] == 'csv_lines' and selection['headerLine'] == 1
    assert result['rows'] == result['errors'] == [] and result['previewToken'] is None
    assert result['requiresColumnSelection'] and 'private' not in json.dumps(result)
    assert client.post('/api/finance-hub/imports/confirm', json={**p, 'previewToken': 'x'}, headers=headers).status_code == 400
    assert state(app) == before


@pytest.mark.parametrize('filename,encoding,sep', [('synthetic.csv', 'utf-8', ','), ('synthetic.txt', 'gb18030', '\t')])
def test_file_preview_and_confirm_exact_cents_with_original_receipt(app, filename, encoding, sep):
    client, headers = member(app)
    text = TEXT.replace(',', sep)
    p = {'source': 'generic', 'kind': 'payments', 'file': file_payload(text.encode(encoding), filename, encoding=encoding),
         'mapping': MAPPING}
    result, original = confirm(client, headers, p)
    assert result['imported'] == 1 and result['resultMonths'] == [{'month': '2026-09', 'recordCount': 1}]
    with closing(sqlite3.connect(database(app))) as con:
        data = json.loads(con.execute('SELECT data FROM hub_transactions').fetchone()[0])
    assert data['amountCents'] == 1050 and data['flow'] == 'unknown' and data['currency'] == 'CNY'
    assert data['visibility'] == 'private'
    assert data['provenance']['lineStart'] == data['provenance']['lineEnd'] == 2
    assert post(client, headers, 'confirm', original)['replayed'] is True
    assert client.get('/api/finance-hub/imports/results/' + 'a' * 32).json['receiptId'] == result['receiptId']


def test_xlsx_inspection_and_multiline_cells_use_real_worksheet_rows(app):
    client, headers = member(app)
    rows = [['前言\n仍在同一行'], [], ['任意日', '任意额', '任意名', '任意币'],
            ['2026-09-02', '0', '合成\n多行标题', 'USD']]
    p = {'source': 'generic', 'file': file_payload(workbook(rows))}
    sheets = post(client, headers, 'preview', {**p, 'inspectSheets': True})
    assert sheets['requiresSheetSelection'] and sheets['previewToken'] is None
    p['file']['sheet'] = '支付账单'
    inspected = post(client, headers, 'preview', {**p, 'inspectColumns': True, 'headerLine': 3})
    assert inspected['columnSelection']['headerLine'] == 3
    assert inspected['columnSelection']['lineKind'] == 'worksheet_rows'
    preview = post(client, headers, 'preview', {**p, 'mapping': {**MAPPING, 'headerLine': 3}})
    assert preview['rows'][0]['sourceLocation'] == {'lineStart': 4, 'lineEnd': 4, 'lineKind': 'worksheet_rows'}
    assert preview['rows'][0]['line'] == 4 and preview['rows'][0]['amountCents'] == 0
    assert preview['rows'][0]['title'] == '合成\n多行标题'


def test_csv_quoted_newline_header_and_data_are_physical_lines():
    text = '"前言\n第二物理行"\n\n"任意\n日",额,名,币\n2026-09-02,12.30,"合成\n多行",CNY\n2026-09-03,0,后行,USD\n'
    inspection = parse_import({'csv': text, 'inspectColumns': True, 'headerLine': 4})
    assert inspection['columnSelection']['headerLine'] == 4
    parsed = parse_import(value(text, mapping={**MAPPING, 'headerLine': 4}))
    assert parsed['rows'][0]['sourceLocation'] == {'lineKind': 'csv_lines', 'lineStart': 6, 'lineEnd': 7}
    assert parsed['rows'][1]['sourceLocation'] == {'lineKind': 'csv_lines', 'lineStart': 8, 'lineEnd': 8}
    assert parsed['rows'][0]['line'] == 7


@pytest.mark.parametrize('patch', [
    {'version': True}, {'version': 2}, {'headerLine': None}, {'headerLine': True}, {'headerLine': 0},
    {'headerLine': 61}, {'amount': False}, {'amount': -1}, {'amount': 80}, {'amount': 4},
    {'title': 0}, {'currency': None}, {'currency': 1.0}, {'extra': 1},
])
def test_mapping_rejects_bad_indices_versions_and_extra_keys(patch):
    with pytest.raises(FinanceHubError):
        parse_import(value(mapping={**MAPPING, **patch}))


@pytest.mark.parametrize('extra', [
    {'source': 'wechat'}, {'inspectColumns': False}, {'inspectColumns': True},
    {'inspectSheets': False}, {'amountColumn': 1}, {'headerLine': 1},
])
def test_mapping_rejects_incompatible_controls(extra):
    with pytest.raises(FinanceHubError):
        parse_import(value(**extra))


@pytest.mark.parametrize('text,message', [
    (TEXT.replace('10.50', '1,23'), '币种'),
    (TEXT.replace('10.50', '1e2'), '金额'),
    (TEXT.replace('2026-09-02', '02/09/2026'), '日期'),
    (TEXT.replace('2026-09-02', '2026-02-30'), '日期'),
    (TEXT.replace(',CNY\n', ',\n'), '币种'),
])
def test_invalid_rows_have_no_preview_token_and_no_partial_write(app, text, message):
    client, headers = member(app)
    before = state(app)
    result = post(client, headers, 'preview', value(text))
    assert result['errorCount'] == 1 and result['previewToken'] is None
    assert message in result['errors'][0]['message']
    assert state(app) == before


def test_canonical_mapping_signing_and_changed_payload_cannot_replay(app, monkeypatch):
    client, headers = member(app)
    p = value('日,额,名,币,另额\n2026-09-02,10.50,合成,CNY,20\n')
    first, original = confirm(client, headers, p)
    frozen = state(app)
    changed = {**original, 'mapping': {**MAPPING, 'amount': 4}}
    response = client.post('/api/finance-hub/imports/confirm', json=changed, headers=headers)
    assert response.status_code == 409 and response.json['code'] == 'import_request_conflict'
    changed['requestId'] = 'b' * 32
    assert client.post('/api/finance-hub/imports/confirm', json=changed, headers=headers).status_code == 400
    # Same mapping key order is canonical, and exact historical receipt outlives token age.
    original['mapping'] = dict(reversed(list(MAPPING.items())))
    now = TimestampSigner.get_timestamp
    monkeypatch.setattr(TimestampSigner, 'get_timestamp', lambda self: now(self) + 1201)
    replay = post(client, headers, 'confirm', original)
    assert replay['receiptId'] == first['receiptId'] and replay['replayed']
    assert state(app) == frozen


@pytest.mark.parametrize('field,new_index', [('date', 4), ('amount', 5), ('title', 6), ('currency', 7)])
def test_same_original_row_remapping_is_conflict_not_new_record(app, field, new_index):
    client, headers = member(app)
    p = value('日,额,名,币,备日,备额,备名,备币\n2026-09-02,10.50,原,CNY,2026-10-03,99,另,USD\n')
    first, _ = confirm(client, headers, p)
    with closing(sqlite3.connect(database(app))) as con:
        old = con.execute('SELECT data FROM hub_transactions').fetchone()[0]
    altered = {**p, 'mapping': {**MAPPING, field: new_index}}
    preview = post(client, headers, 'preview', altered)
    assert preview['duplicateCount'] == preview['conflictCount'] == 1 and preview['newCount'] == 0
    second, _ = confirm(client, headers, altered, 'b' * 32)
    assert second['imported'] == 0 and second['duplicates'] == second['conflicts'] == 1
    assert second['resultMonths'] == first['resultMonths']
    with closing(sqlite3.connect(database(app))) as con:
        assert con.execute('SELECT data FROM hub_transactions').fetchall() == [(old,)]


@pytest.mark.parametrize('historical', [False, True])
def test_old_automatic_rows_remain_deduplicated_when_mapping_changes(app, historical):
    client, headers = member(app)
    text = 'date,amount,title,currency,other\n2026-09-02,1.50,原,CNY,5.50\n'
    automatic = {'source': 'generic', 'csv': text}
    confirm(client, headers, automatic)
    if historical:
        with closing(sqlite3.connect(database(app))) as con:
            rid, raw = con.execute('SELECT id,data FROM hub_transactions').fetchone()
            data = json.loads(raw)
            data.pop('sourceRowKey')
            con.execute('UPDATE hub_transactions SET data=? WHERE id=?', (json.dumps(data), rid))
            con.commit()
    second, _ = confirm(client, headers, {**automatic, 'mapping': {**MAPPING, 'amount': 4}}, 'b' * 32)
    assert second['duplicates'] == second['conflicts'] == 1 and second['imported'] == 0


def test_mapping_first_then_automatic_same_source_is_not_double_counted(app):
    client, headers = member(app)
    text = 'date,amount,title,currency,other\n2026-09-02,1.50,原,CNY,5.50\n'
    confirm(client, headers, value(text, mapping={**MAPPING, 'amount': 4}))
    result, _ = confirm(client, headers, {'source': 'generic', 'csv': text}, 'b' * 32)
    assert result['duplicates'] == result['conflicts'] == 1 and result['imported'] == 0


def test_duplicate_json_fields_and_inspection_bounds_rejected(app):
    client, headers = member(app)
    raw = json.dumps(value()).replace('"version": 1', '"version": 1, "version": 1')
    response = client.post('/api/finance-hub/imports/preview', data=raw, content_type='application/json', headers=headers)
    assert response.status_code == 400
    for p in ({'csv': TEXT, 'inspectColumns': 1}, {'csv': TEXT, 'inspectColumns': True, 'headerLine': 61},
              {'csv': ','.join(['h'] * 81) + '\n', 'inspectColumns': True},
              {'csv': 'x' * 201 + ',b,c,d\n', 'inspectColumns': True}):
        assert client.post('/api/finance-hub/imports/preview', json=p, headers=headers).status_code == 400


def test_old_automatic_signed_digest_remains_identical(app):
    client, headers = member(app)
    p = {'csv': 'date,amount,title,currency\n2026-09-02,1,原,CNY\n'}
    preview = post(client, headers, 'preview', p)
    signed = URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='household-finance-preview-v1').loads(preview['previewToken'])
    content = {'source': 'generic', 'kind': 'payments', 'csv': p['csv'], 'file': ''}
    assert signed == {'owner': 'member1', 'digest': hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}


def test_file_rename_deduplicates_but_kind_is_distinct_and_currencies_stay_separate(app):
    client, headers = member(app)
    text = '日期自定,额自定,标题自定,币自定,另一额\n2026-09-02,1234,合成一,CNY,3\n2026-09-03,1,合成二,USD,4\n'
    p = {'source': 'generic', 'kind': 'payments', 'file': file_payload(text.encode(), 'one.csv'), 'mapping': MAPPING}
    first, _ = confirm(client, headers, p)
    assert first['imported'] == 2
    renamed = {**p, 'file': {**p['file'], 'name': 'renamed.csv'}}
    duplicate, _ = confirm(client, headers, renamed, 'b' * 32)
    assert duplicate['duplicates'] == 2 and duplicate['imported'] == duplicate['conflicts'] == 0
    conflict, _ = confirm(client, headers, {**renamed, 'mapping': {**MAPPING, 'amount': 4}}, 'c' * 32)
    assert conflict['conflicts'] == conflict['duplicates'] == 2 and conflict['imported'] == 0
    orders, _ = confirm(client, headers, {**p, 'kind': 'orders'}, 'd' * 32)
    assert orders['imported'] == 2 and orders['duplicates'] == 0
    with closing(sqlite3.connect(database(app))) as con:
        data = [json.loads(row[0]) for row in con.execute('SELECT data FROM hub_transactions')]
    assert {(row['currency'], row['amountCents']) for row in data} == {('CNY', 123400), ('USD', 100)}
    assert len({row['sourceRowKey'] for row in data}) == 4


def test_recognized_external_id_keeps_cross_file_dedup_for_custom_headers(app):
    client, headers = member(app)
    text = '任意日,任意额,任意名,任意币,id\n2026-09-02,1,合成,CNY,same-id\n'
    confirm(client, headers, value(text))
    second, _ = confirm(client, headers, value(text.replace(',1,合成,', ',2,合成,')), 'b' * 32)
    assert second['imported'] == 0 and second['conflicts'] == second['duplicates'] == 1


def test_mapping_receipts_and_rows_remain_owner_and_household_private(app):
    first, headers = member(app)
    original, _ = confirm(first, headers, value())
    partner, partner_headers = member(app, 2)
    assert partner.get('/api/finance-hub/imports/results/' + 'a' * 32).status_code == 404
    assert post(partner, partner_headers, 'preview', value())['newCount'] == 1
    other, _, invitation = create_space(app)
    assert other.get(invitation['entry']).status_code == 303
    assert other.post('/api/login', json={'username': 'member1', 'password': 'second-home-password-one'}).status_code == 200
    other_headers = {'X-CSRF-Token': other.get('/api/me').json['csrf']}
    assert other.get('/api/finance-hub/imports/results/' + 'a' * 32).status_code == 404
    accepted, _ = confirm(other, other_headers, value())
    assert accepted['imported'] == 1 and accepted['receiptId'] != original['receiptId']
    assert first.get('/api/finance-hub/imports/results/' + 'a' * 32).json['receiptId'] == original['receiptId']


def test_original_automatic_multiple_amount_receipt_remains_matchable_without_row_key(app):
    client, headers = member(app)
    text = 'date,amount,title,currency,amount\n2026-09-02,1.50,原,CNY,5.50\n'
    automatic = {'source': 'generic', 'csv': text, 'amountColumn': 4}
    confirm(client, headers, automatic)
    with closing(sqlite3.connect(database(app))) as con:
        rid, raw = con.execute('SELECT id,data FROM hub_transactions').fetchone()
        data = json.loads(raw)
        data.pop('sourceRowKey')
        con.execute('UPDATE hub_transactions SET data=? WHERE id=?', (json.dumps(data), rid))
        con.commit()
    result, _ = confirm(client, headers, value(text), 'b' * 32)
    assert result['imported'] == 0 and result['duplicates'] == result['conflicts'] == 1


@pytest.mark.parametrize('first', ['unreadable', '"1,23"'])
def test_old_selected_amount_survives_unreadable_or_legacy_ambiguous_original_column(app, first):
    client, headers = member(app)
    text = f'date,amount,title,currency,amount,arbitrary\n2026-09-02,{first},原,CNY,5.50,9.50\n'
    confirm(client, headers, {'source': 'generic', 'csv': text, 'amountColumn': 4})
    with closing(sqlite3.connect(database(app))) as con:
        rid, raw = con.execute('SELECT id,data FROM hub_transactions').fetchone()
        data = json.loads(raw)
        data.pop('sourceRowKey')
        con.execute('UPDATE hub_transactions SET data=? WHERE id=?', (json.dumps(data), rid))
        con.commit()
    result, _ = confirm(client, headers, value(text, mapping={**MAPPING, 'amount': 5}), 'b' * 32)
    assert result['imported'] == 0 and result['duplicates'] == result['conflicts'] == 1
    with closing(sqlite3.connect(database(app))) as con:
        assert json.loads(con.execute('SELECT data FROM hub_transactions').fetchone()[0])['amountCents'] == 550


@pytest.mark.parametrize('format', ['csv', 'xlsx'])
@pytest.mark.parametrize('currency_tail', [[], ['']])
def test_explicit_currency_missing_or_empty_blocks_preview_and_all_writes(app, format, currency_tail):
    client, headers = member(app)
    rows = [['任意日', '任意额', '任意名', '任意币'], ['2026-09-02', '12.30', '合成', *currency_tail]]
    if format == 'xlsx':
        p = {'source': 'generic', 'file': file_payload(workbook(rows)), 'mapping': MAPPING}
    else:
        p = value('\n'.join(','.join(row) for row in rows) + '\n')
    before = state(app)
    result = post(client, headers, 'preview', p)
    assert result['rows'] == [] and result['errorCount'] == 1
    assert result['previewToken'] is None and '币种' in result['errors'][0]['message']
    refused = client.post('/api/finance-hub/imports/confirm',
                          json={**p, 'previewToken': result['previewToken'], 'requestId': 'a' * 32}, headers=headers)
    assert refused.status_code == 400
    assert state(app) == before
