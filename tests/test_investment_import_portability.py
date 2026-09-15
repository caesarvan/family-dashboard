"""Real synthetic import -> private ZIP checks; no financial files or services."""
import base64
from contextlib import closing
import csv
from io import StringIO
import json
from pathlib import Path
import socket
import sqlite3

import pytest

from app import create_app
from test_data_portability import unpack
from test_household_spaces import create_space


PREFIX = '/api/finance-hub/investments/imports'
SOURCE = '两位成员分别使用的同名来源'
BUSINESS_TABLES = (
    'hub_investments', 'hub_investment_sources', 'hub_investment_links',
    'hub_investment_import_previews', 'hub_investment_import_receipts',
    'entities', 'finance_baselines', 'private_finance', 'settings',
    'users', 'member_sessions', 'member_session_browsers', 'devices',
)


@pytest.fixture
def app(tmp_path, monkeypatch):
    def deny_network(*_args, **_kwargs):
        raise AssertionError('External access is forbidden in investment portability tests')

    monkeypatch.setattr(socket.socket, 'connect', deny_network)
    return create_app({
        'TESTING': True, 'SECRET_KEY': 'synthetic-investment-export-key',
        'DATA_DIR': str(tmp_path), 'SESSION_COOKIE_SECURE': False,
        'MEMBER1_PASSWORD': 'testing-password-one', 'MEMBER2_PASSWORD': 'testing-password-two',
        'MICROSOFT_CLIENT_ID': '', 'MICROSOFT_CLIENT_SECRET': '',
        'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': '', 'OPENAI_API_KEY': '', 'OPENAI_MODEL': '',
    })


def login(app, number=1):
    client = app.test_client()
    assert client.get('/api/me').status_code == 200
    response = client.post('/api/login', json={
        'username': f'member{number}', 'password': 'testing-password-' + ('one' if number == 1 else 'two')})
    assert response.status_code == 200, response.json
    return client, {'X-CSRF-Token': client.get('/api/me').json['csrf']}


def file_payload(marker, *, key='same-holding-key', value='123.45'):
    stream = StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(['holdingKey', 'name', 'institution', 'assetType', 'currency', 'quantity',
                     'cost', 'value', 'asOf', 'note', 'recordId'])
    writer.writerow([key, marker + '_HOLDING', marker + '_BANK', '基金', 'USD', '2.50',
                     '120.01', value, '2026-09-15', marker + '_NOTE', ''])
    return {'sourceName': SOURCE, 'file': {'name': 'synthetic.csv',
            'contentBase64': base64.b64encode(stream.getvalue().encode('utf-8')).decode('ascii')}}


def import_holding(client, headers, marker, **options):
    preview = client.post(PREFIX + '/preview', json=file_payload(marker, **options), headers=headers)
    assert preview.status_code == 200, preview.json
    assert preview.json['errorCount'] == 0 and preview.json['previewToken'], preview.json
    result = client.post(PREFIX + '/confirm', json={'previewToken': preview.json['previewToken']}, headers=headers)
    assert result.status_code == 200, result.json
    assert result.json['created'] == 1 and result.json['updated'] == 0
    return preview.json, result.json


def db_path(app):
    return Path(app.config['DATA_DIR']) / 'household.sqlite3'


def storage_snapshot(app):
    with closing(sqlite3.connect(db_path(app))) as con:
        # Export deliberately appends an audit entry and advances settings.meta;
        # every actual business, sharing, authentication and staging row stays put.
        return {table: con.execute(f'SELECT * FROM {table}' +
                                  (" WHERE id!='meta'" if table == 'settings' else '') + ' ORDER BY rowid').fetchall()
                for table in BUSINESS_TABLES}


def credentials_and_staging(app, clients):
    secrets = []
    for client, headers in clients:
        secrets.extend([client.get_cookie(app.config['SESSION_COOKIE_NAME']).value, headers['X-CSRF-Token']])
    with closing(sqlite3.connect(db_path(app))) as con:
        for row in con.execute('SELECT credential_hash,browser_hash FROM member_sessions'):
            secrets.extend(row)
        for row in con.execute('SELECT id,context_hash,snapshot FROM hub_investment_import_previews'):
            secrets.extend(row)
    return secrets


@pytest.mark.parametrize('include_shared', [False, True])
def test_both_members_real_import_zip_is_private_and_export_does_not_mutate(app, include_shared):
    clients = [login(app, 1), login(app, 2)]
    receipts, tokens, cookies = {}, [], []
    for number, (client, headers) in enumerate(clients, 1):
        marker = f'PRIVATE_MEMBER_{number}'
        manual = client.post('/api/finance-hub/investments', json={
            'name': marker + '_MANUAL', 'institution': marker + '_MANUAL_BANK', 'assetType': '基金',
            'currency': 'CNY', 'cost': '0', 'value': None, 'asOf': '2026-09-14'}, headers=headers)
        assert manual.status_code == 201, manual.json
        preview, receipts[number] = import_holding(client, headers, marker, value='' if number == 1 else '0')
        tokens.append(preview['previewToken'])
        pending = client.post(PREFIX + '/preview', json=file_payload(
            f'UNCONFIRMED_MEMBER_{number}', key='pending-holding'), headers=headers)
        assert pending.status_code == 200 and pending.json['previewToken'], pending.json
        tokens.append(pending.json['previewToken'])
        cookies.append(client.get_cookie(app.config['SESSION_COOKIE_NAME']).value)

    shared = clients[0][0].post('/api/items/tasks', json={'title': 'EXPLICIT_SHARED_TASK'}, headers=clients[0][1])
    assert shared.status_code == 201, shared.json
    # Test explicit nested projection against a possible future receipt extension.
    # The successful API result itself still contains only the real business fields.
    with closing(sqlite3.connect(db_path(app))) as con:
        for number in (1, 2):
            result = {**receipts[number], 'context_hash': f'RECEIPT_CONTEXT_SECRET_{number}',
                      'snapshot': {'token': f'RECEIPT_TOKEN_SECRET_{number}'}, 'nonce': f'RECEIPT_NONCE_{number}'}
            con.execute('UPDATE hub_investment_import_receipts SET result=? WHERE id=?',
                        (json.dumps(result), receipts[number]['receiptId']))
        con.commit()
    secrets = credentials_and_staging(app, clients) + tokens
    before = storage_snapshot(app)
    for number, (client, headers) in enumerate(clients, 1):
        response = client.post('/api/portability/export', json={'includeShared': include_shared}, headers=headers)
        exported, files = unpack(response)
        assert 'Set-Cookie' not in response.headers
        assert client.get_cookie(app.config['SESSION_COOKIE_NAME']).value == cookies[number - 1]
        assert exported['member']['id'] == f'member{number}'
        assert ('shared' in exported) is include_shared
        personal = exported['personal']
        assert len(personal['investments']) == 2
        investment = next(row for row in personal['investments'] if row['name'].endswith('_HOLDING'))
        assert investment['name'] == f'PRIVATE_MEMBER_{number}_HOLDING'
        assert investment['costCents'] == 12001
        assert investment['valueCents'] == (None if number == 1 else 0)
        assert type(investment['valueCents']) is (type(None) if number == 1 else int)
        assert len(personal['investmentSources']) == 1
        assert personal['investmentSources'][0]['sourceName'] == SOURCE
        assert personal['investmentSources'][0]['revision'] == 1
        assert personal['investmentSources'][0]['updatedAt']
        assert personal['investmentLinks'] == [{
            'sourceName': SOURCE, 'holdingKey': 'same-holding-key', 'investmentId': investment['id'],
            'createdAt': receipts[number]['confirmedAt']}]
        receipt = personal['investmentImportReceipts'][0]
        assert len(personal['investmentImportReceipts']) == 1
        assert receipt['id'] == receipts[number]['receiptId']
        assert receipt['sourceName'] == SOURCE and len(receipt['sourceDigest']) == 64
        assert receipt['confirmedAt'] == receipts[number]['confirmedAt']
        assert receipt['result'] == receipts[number]
        assert set(receipt) == {'id', 'sourceName', 'sourceDigest', 'result', 'confirmedAt'}
        csv_rows = list(csv.DictReader(StringIO(files['investments.csv'].decode('utf-8-sig'))))
        imported_csv = next(row for row in csv_rows if row['id'] == investment['id'])
        assert imported_csv['cost'] == '120.01'
        assert imported_csv['value'] == ('' if number == 1 else '0.00')
        joined = b''.join(files.values())
        assert (b'EXPLICIT_SHARED_TASK' in joined) is include_shared
        for forbidden in [f'PRIVATE_MEMBER_{3-number}', 'UNCONFIRMED_MEMBER_',
                          'RECEIPT_CONTEXT_SECRET_', 'RECEIPT_TOKEN_SECRET_', 'RECEIPT_NONCE_',
                          'hub_investment_import_previews', 'member_session_browsers', 'credential_hash',
                          'context_hash', 'previewToken', 'nonce', 'scrypt:', *secrets]:
            assert forbidden.encode('utf-8') not in joined, 'A private staging or credential value leaked'
    assert storage_snapshot(app) == before
    for number, (client, headers) in enumerate(clients, 1):
        me = client.get('/api/me')
        assert me.json['user']['id'] == f'member{number}' and me.json['csrf'] == headers['X-CSRF-Token']


def test_deleted_imported_holding_keeps_business_link_in_zip_without_resurrection(app):
    client, headers = login(app)
    preview, result = import_holding(client, headers, 'DELETED_PRIVATE')
    with closing(sqlite3.connect(db_path(app))) as con:
        rid, revision = con.execute('SELECT id,revision FROM hub_investments WHERE owner=?', ('member1',)).fetchone()
    deleted = client.delete('/api/finance-hub/investments/' + rid, json={'revision': revision}, headers=headers)
    assert deleted.status_code == 200, deleted.json
    before = storage_snapshot(app)
    exported, files = unpack(client.post('/api/portability/export', json={}, headers=headers))
    assert exported['personal']['investments'] == []
    assert exported['personal']['investmentLinks'][0]['investmentId'] == rid
    assert exported['personal']['investmentImportReceipts'][0]['result'] == result
    assert list(csv.DictReader(StringIO(files['investments.csv'].decode('utf-8-sig')))) == []
    assert preview['previewToken'].encode() not in b''.join(files.values())
    assert storage_snapshot(app) == before


def test_import_export_authentication_and_shared_permissions_remain_unchanged(app):
    client, headers = login(app)
    import_holding(client, headers, 'PROTECTED_PRIVATE')
    public = app.test_client()
    assert public.post('/api/portability/export', json={}).status_code == 401
    assert client.post('/api/portability/export', json={}).status_code == 403
    assert client.post('/api/portability/export', json={}, headers={**headers, 'Origin': 'https://other.invalid'}).status_code == 403
    assert client.post('/api/portability/export', json={'owner': 'member2'}, headers=headers).status_code == 400
    assert client.post('/api/portability/export', json={'includeShared': 'true'}, headers=headers).status_code == 400
    pair = public.post('/api/pair/start', json={}).json
    assert client.post('/api/pair/approve', json={'code': pair['code']}, headers=headers).status_code == 200
    assert public.post('/api/pair/poll', json={'secret': pair['secret']}).status_code == 200
    assert public.get('/api/portability/summary').status_code == 403
    assert public.post('/api/portability/export', json={}, headers=headers).status_code == 403
    assert public.get('/api/state').status_code == 200
    tv_state = public.get('/api/state').get_data(as_text=True)
    assert 'PROTECTED_PRIVATE' not in tv_state
    before = storage_snapshot(app)
    exported, _ = unpack(client.post('/api/portability/export', json={'includeShared': True}, headers=headers))
    assert exported['personal']['investments'][0]['name'] == 'PROTECTED_PRIVATE_HOLDING'
    assert storage_snapshot(app) == before


def test_new_household_same_member_and_keys_cannot_export_original_holdings(app):
    original, headers = login(app)
    _, receipt = import_holding(original, headers, 'ORIGINAL_FAMILY_PRIVATE')
    child, _, result = create_space(app)
    assert child.get(result['entry']).status_code == 303
    assert child.post('/api/login', json={'username': 'member1', 'password': 'second-home-password-one'}).status_code == 200
    child_headers = {'X-CSRF-Token': child.get('/api/me').json['csrf']}
    _, child_receipt = import_holding(child, child_headers, 'SECOND_FAMILY_PRIVATE')
    exported, files = unpack(child.post('/api/portability/export', json={'includeShared': True}, headers=child_headers))
    assert exported['household']['slug'] == 'second-home'
    assert exported['personal']['investments'][0]['name'] == 'SECOND_FAMILY_PRIVATE_HOLDING'
    assert exported['personal']['investmentImportReceipts'][0]['id'] == child_receipt['receiptId']
    joined = b''.join(files.values())
    assert b'ORIGINAL_FAMILY_PRIVATE' not in joined and receipt['receiptId'].encode() not in joined
    own, files = unpack(original.post('/api/portability/export', json={'includeShared': True}, headers=headers))
    assert own['personal']['investments'][0]['name'] == 'ORIGINAL_FAMILY_PRIVATE_HOLDING'
    assert b'SECOND_FAMILY_PRIVATE' not in b''.join(files.values())


def test_export_remains_compatible_when_optional_investment_import_tables_are_absent(app):
    client, headers = login(app)
    with closing(sqlite3.connect(db_path(app))) as con:
        for table in ('hub_investment_import_previews', 'hub_investment_import_receipts',
                      'hub_investment_links', 'hub_investment_sources'):
            con.execute('DROP TABLE ' + table)
        con.commit()
    exported, _ = unpack(client.post('/api/portability/export', json={}, headers=headers))
    assert exported['personal']['investments'] == []
    assert not {'investmentSources', 'investmentLinks', 'investmentImportReceipts'} & exported['personal'].keys()
