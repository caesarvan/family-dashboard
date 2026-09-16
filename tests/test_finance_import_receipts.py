"""Durable import recovery and source provenance, entirely synthetic and local."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
from threading import Barrier

import pytest
from itsdangerous import TimestampSigner

import finance_hub
from test_finance_hub import hub, payload, overview
from test_financial_files import workbook, file_payload
from test_app import app, member
from test_data_portability import unpack
from test_household_spaces import create_space


ROOT = '/api/finance-hub'
REQUEST_ID = 'a' * 32


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError('No external network in financial receipt tests')
    monkeypatch.setattr(socket.socket, 'connect', deny)


def prepared(client, value=None, headers=None, request_id=REQUEST_ID):
    value = value or payload()
    preview = client.post(ROOT + '/imports/preview', json=value, headers=headers)
    assert preview.status_code == 200 and preview.json['previewToken'], preview.json
    return {**value, 'previewToken': preview.json['previewToken'], 'requestId': request_id}


def confirm(client, value, headers=None):
    return client.post(ROOT + '/imports/confirm', json=value, headers=headers)


def result(client, request_id=REQUEST_ID, headers=None):
    return client.get(ROOT + '/imports/results/' + request_id, headers=headers)


def snapshot(target):
    with closing(sqlite3.connect(target)) as con:
        return {name: con.execute('SELECT * FROM ' + name + ' ORDER BY rowid').fetchall()
                for name in ('hub_transactions', 'hub_imports', 'hub_import_receipts', 'hub_budgets', 'audit')}


def test_exact_readback_replay_after_delete_and_explicit_new_operation(hub):
    client, target = hub
    value = prepared(client)
    assert result(client).status_code == 404
    accepted = confirm(client, value)
    assert accepted.status_code == 200 and accepted.json['imported'] == 1
    assert accepted.json['replayed'] is False
    saved = snapshot(target)
    assert result(client).json == {**accepted.json, 'replayed': True}
    assert confirm(client, value).json == result(client).json
    assert snapshot(target) == saved
    row = overview(client)['transactions'][0]
    assert row['provenance']['batchId'] == accepted.json['batchId']
    assert client.delete(ROOT + '/transactions/' + row['id'], json={'revision': row['revision']}).status_code == 200
    deleted = snapshot(target)
    assert result(client).json['imported'] == 1  # Historical outcome, not current count.
    assert confirm(client, value).json['replayed'] is True
    assert snapshot(target) == deleted
    assert not overview(client)['transactions']
    again = confirm(client, prepared(client, request_id='b' * 32))
    assert again.json['imported'] == 1 and again.json['batchId'] != accepted.json['batchId']


def test_same_id_rejects_changed_payload_or_token_and_missing_token(hub):
    client, target = hub
    value = prepared(client)
    assert confirm(client, value).status_code == 200
    before = snapshot(target)
    for changed in ({**value, 'csv': value['csv'].replace('10.50', '12.50')},
                    {**value, 'previewToken': 'not-the-original-token'}):
        response = confirm(client, changed)
        assert response.status_code == 409 and response.json['code'] == 'import_request_conflict'
    missing = dict(value); missing.pop('previewToken')
    assert confirm(client, missing).status_code == 400
    assert snapshot(target) == before


@pytest.mark.parametrize('request_id', [None, '', True, 123, 'A' * 32, 'a' * 31, 'a' * 65, 'g' * 32])
def test_request_id_is_strict_and_invalid_requests_never_write(hub, request_id):
    client, target = hub
    value = prepared(client, request_id=request_id)
    before = snapshot(target)
    assert confirm(client, value).status_code == 400
    assert snapshot(target) == before


def test_expired_exact_original_token_recovers_only_existing_operation(hub, monkeypatch):
    client, target = hub
    value = prepared(client)
    assert confirm(client, value).status_code == 200
    timestamp = TimestampSigner.get_timestamp
    monkeypatch.setattr(TimestampSigner, 'get_timestamp', lambda self: timestamp(self) + 7200)
    before = snapshot(target)
    assert confirm(client, value).json['replayed'] is True
    assert result(client).json['imported'] == 1
    assert confirm(client, {**value, 'requestId': 'b' * 32}).status_code == 400
    assert snapshot(target) == before


def test_readback_and_confirm_are_owner_scoped_and_tv_forbidden(hub):
    client, target = hub
    value = prepared(client)
    accepted = confirm(client, value).json
    before = snapshot(target)
    for actor, status in [('member2', 404), ('tv', 403), ('anonymous', 401)]:
        assert result(client, headers={'X-Test-Actor': actor}).status_code == status
    assert confirm(client, value, {'X-Test-Actor': 'member2'}).status_code == 400
    assert result(client, REQUEST_ID + '?owner=member2').status_code == 400
    assert snapshot(target) == before
    other = prepared(client, headers={'X-Test-Actor': 'member2'})
    assert confirm(client, other, {'X-Test-Actor': 'member2'}).json['receiptId'] != accepted['receiptId']


def test_duplicate_only_receipt_is_stable_and_keeps_creation_batch(hub):
    client, target = hub
    first = confirm(client, prepared(client)).json
    before_row = overview(client)['transactions'][0]
    second = confirm(client, prepared(client, request_id='b' * 32)).json
    assert second['imported'] == 0 and second['duplicates'] == 1 and second['batchId'] is None
    assert second['resultMonths'] == first['resultMonths']
    assert overview(client)['transactions'][0] == before_row
    with closing(sqlite3.connect(target)) as con:
        assert con.execute('SELECT count(*) FROM hub_imports').fetchone()[0] == 1
        assert con.execute('SELECT count(*) FROM hub_import_receipts').fetchone()[0] == 2


def test_provenance_preserves_csv_multiline_range_and_xlsx_physical_row(hub):
    client, _target = hub
    text = 'date,title,amount,currency,flow,id\n2026-09-02,"line one\nline two",10.00,CNY,expense,multi\n'
    accepted = confirm(client, prepared(client, {'source': 'generic', 'kind': 'payments', 'csv': text})).json
    first = overview(client)['transactions'][0]['provenance']
    assert first == {'status': 'recorded', 'batchId': accepted['batchId'], 'source': 'generic', 'kind': 'payments',
                     'fileName': None, 'format': 'csv', 'sheet': None, 'lineStart': 2, 'lineEnd': 3,
                     'lineKind': 'csv_lines', 'importedAt': accepted['confirmedAt']}
    rows = [['date', 'title', 'amount', 'currency', 'flow', 'id'],
            ['2026-09-03', 'multiline\ncell', '20.00', 'CNY', 'expense', 'xlsx-1'],
            ['2026-09-04', 'next', '30.00', 'CNY', 'expense', 'xlsx-2']]
    value = {'source': 'generic', 'kind': 'payments', 'file': file_payload(workbook(rows=rows), name='synthetic.xlsx')}
    response = confirm(client, prepared(client, value, request_id='b' * 32))
    assert response.status_code == 200, response.json
    indexed = {row['externalId']: row for row in overview(client)['transactions']}
    for name, line in [('xlsx-1', 2), ('xlsx-2', 3)]:
        origin = indexed[name]['provenance']
        assert origin['lineStart'] == origin['lineEnd'] == line
        assert origin['lineKind'] == 'worksheet_rows' and origin['fileName'] == 'synthetic.xlsx'


def test_legacy_has_no_receipt_and_historical_missing_provenance_is_unknown(hub):
    client, target = hub
    value = prepared(client); value.pop('requestId')
    accepted = confirm(client, value)
    assert accepted.status_code == 200 and 'requestId' not in accepted.json
    row = overview(client)['transactions'][0]
    assert row['provenance']['status'] == 'recorded'
    with closing(sqlite3.connect(target)) as con:
        assert not con.execute('SELECT * FROM hub_import_receipts').fetchall()
        data = json.loads(con.execute('SELECT data FROM hub_transactions').fetchone()[0]); data.pop('provenance')
        con.execute('UPDATE hub_transactions SET data=?', (json.dumps(data),)); con.commit()
    before = snapshot(target)
    assert overview(client)['transactions'][0]['provenance'] == {'status': 'unknown'}
    assert client.get(ROOT + '/transactions?month=2026-09').json['transactions'][0]['provenance'] == {'status': 'unknown'}
    assert snapshot(target) == before


@pytest.mark.parametrize('limit', ['MAX_IMPORT_RECEIPTS', 'MAX_IMPORT_RECEIPT_BYTES', 'MAX_IMPORT_RECEIPT_STORAGE'])
def test_capacity_rolls_back_entire_new_operation_but_preserves_old_and_legacy(hub, monkeypatch, limit):
    client, target = hub
    value = prepared(client)
    assert confirm(client, value).status_code == 200
    changed = payload(rows='2026-09-04,new,15.00,CNY,expense,餐饮,new,成功\n')
    next_value = prepared(client, changed, request_id='b' * 32)
    monkeypatch.setattr(finance_hub, limit, 0)
    before = snapshot(target)
    assert confirm(client, next_value).status_code == 400
    assert snapshot(target) == before
    assert confirm(client, value).json['replayed'] is True
    assert result(client).status_code == 200
    next_value.pop('requestId')
    assert confirm(client, next_value).json['imported'] == 1


def test_two_concurrent_identical_operations_commit_once(hub, monkeypatch):
    client, target = hub
    value = prepared(client)
    actual_parse = finance_hub.parse_import
    barrier = Barrier(2)
    def waiting_parse(body):
        parsed = actual_parse(body)
        barrier.wait(timeout=10)
        return parsed
    monkeypatch.setattr(finance_hub, 'parse_import', waiting_parse)
    def run(_number):
        return confirm(client.application.test_client(), value)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(run, [1, 2]))
    assert [response.status_code for response in responses] == [200, 200]
    assert sorted(response.json['replayed'] for response in responses) == [False, True]
    assert len({response.json['receiptId'] for response in responses}) == 1
    with closing(sqlite3.connect(target)) as con:
        for table in ('hub_transactions', 'hub_imports', 'hub_import_receipts'):
            assert con.execute('SELECT count(*) FROM ' + table).fetchone()[0] == 1


def test_two_concurrent_different_payloads_cannot_claim_same_request_id(hub, monkeypatch):
    client, target = hub
    first = prepared(client)
    second = prepared(client, payload(rows='2026-09-04,OTHER,18.00,CNY,expense,餐饮,other,成功\n'))
    actual_parse, barrier = finance_hub.parse_import, Barrier(2)
    def waiting_parse(body):
        parsed = actual_parse(body); barrier.wait(timeout=10)
        return parsed
    monkeypatch.setattr(finance_hub, 'parse_import', waiting_parse)
    def run(value):
        return confirm(client.application.test_client(), value)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(run, [first, second]))
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert next(response for response in responses if response.status_code == 409).json['code'] == 'import_request_conflict'
    with closing(sqlite3.connect(target)) as con:
        for table in ('hub_transactions', 'hub_imports', 'hub_import_receipts'):
            assert con.execute('SELECT count(*) FROM ' + table).fetchone()[0] == 1


@pytest.mark.parametrize('token', ['', 'forged-preview', '\ud800', '非签名内容'])
def test_unsigned_or_malformed_preview_cannot_create_receipt(hub, token):
    client, target = hub
    before = snapshot(target)
    response = confirm(client, {**payload(), 'requestId': REQUEST_ID, 'previewToken': token})
    assert response.status_code == 400
    assert snapshot(target) == before


def test_additive_schema_constant_preserves_existing_tables_and_is_idempotent(hub):
    client, target = hub
    value = prepared(client); value.pop('requestId')
    assert confirm(client, value).status_code == 200
    with closing(sqlite3.connect(target)) as con:
        con.execute('DROP TABLE hub_import_receipts'); con.commit()
        tables = [row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        before = {name: con.execute('SELECT * FROM ' + name + ' ORDER BY rowid').fetchall() for name in tables}
        schema = con.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        con.executescript(finance_hub.FINANCE_IMPORT_RECEIPTS_SCHEMA_SQL)
        con.executescript(finance_hub.FINANCE_IMPORT_RECEIPTS_SCHEMA_SQL)
        assert before == {name: con.execute('SELECT * FROM ' + name + ' ORDER BY rowid').fetchall() for name in tables}
        assert schema == con.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name!='hub_import_receipts' ORDER BY name").fetchall()
        assert not con.execute('SELECT * FROM hub_import_receipts').fetchall()
        assert [row[1] for row in con.execute('PRAGMA table_info(hub_imports)')] == ['id', 'owner', 'digest', 'source', 'kind', 'imported_count', 'created_at']


def test_real_session_revoked_during_parse_cannot_commit(app, monkeypatch):
    client, headers = member(app)
    value = prepared(client, headers=headers)
    actual_parse = finance_hub.parse_import
    target = Path(app.config['DATA_DIR']) / 'household.sqlite3'
    def revoke_then_parse(body):
        parsed = actual_parse(body)
        with closing(sqlite3.connect(target)) as con:
            con.execute('UPDATE member_sessions SET revoked_at=1 WHERE owner=?', ('member1',)); con.commit()
        return parsed
    monkeypatch.setattr(finance_hub, 'parse_import', revoke_then_parse)
    response = confirm(client, value, headers)
    assert response.status_code == 401, response.json
    with closing(sqlite3.connect(target)) as con:
        for table in ('hub_transactions', 'hub_imports', 'hub_import_receipts'):
            assert con.execute('SELECT count(*) FROM ' + table).fetchone()[0] == 0


def test_real_household_isolation_export_and_private_receipt_whitelist(app):
    clients = [member(app, 1), member(app, 2)]
    accepted, tokens = [], []
    for index, (client, headers) in enumerate(clients, 1):
        value = prepared(client, payload(rows=f'2026-09-04,PRIVATE_{index},15.00,CNY,expense,餐饮,member-{index},成功\n'), headers)
        tokens.append(value['previewToken'])
        accepted.append(confirm(client, value, headers).json)
    client, headers = clients[0]
    target = Path(app.config['DATA_DIR']) / 'household.sqlite3'
    with closing(sqlite3.connect(target)) as con:
        row = con.execute('SELECT result FROM hub_import_receipts WHERE owner=?', ('member1',)).fetchone()
        expanded = json.loads(row[0]); expanded['previewToken'] = 'NEVER_EXPORT_SIGNATURE'
        expanded['resultMonths'][0]['internal'] = 'NEVER_EXPORT_INTERNAL'
        con.execute('UPDATE hub_import_receipts SET result=? WHERE owner=?', (json.dumps(expanded), 'member1')); con.commit()
    data, files = unpack(client.post('/api/portability/export', json={'includeShared': True}, headers=headers))
    receipt = data['personal']['transactionImportReceipts'][0]
    assert receipt['receiptId'] == accepted[0]['receiptId']
    assert receipt['batchId'] == data['personal']['transactions'][0]['provenance']['batchId']
    output = b''.join(files.values()).decode('utf-8-sig')
    for forbidden in ['PRIVATE_2', accepted[1]['receiptId'], 'NEVER_EXPORT_', *tokens,
                      hashlib.sha256(tokens[0].encode()).hexdigest()]:
        assert forbidden not in output
    assert 'transactionImportReceipts' not in data['shared']
    child, _, space = create_space(app)
    assert child.get(space['entry']).status_code == 303
    assert child.post('/api/login', json={'username': 'member1', 'password': 'second-home-password-one'}).status_code == 200
    assert result(child).status_code == 404
    child_headers = {'X-CSRF-Token': child.get('/api/me').json['csrf']}
    original = prepared(client, headers=headers, request_id='c' * 32)
    assert confirm(child, original, child_headers).status_code == 400
    assert child.get(ROOT + '/overview').json['totalRecordCount'] == 0
