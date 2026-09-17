"""Real owner exports of manual accounts and dated valuations; synthetic only."""
from contextlib import closing
from pathlib import Path
import json
import sqlite3

import pytest

from test_app import app, member
from test_data_portability import unpack


TABLES = ('finance_accounts', 'finance_account_valuations', 'finance_account_operations')


def snapshot(application):
    with closing(sqlite3.connect(Path(application.config['DATA_DIR']) / 'household.sqlite3')) as con:
        return {name: con.execute('SELECT * FROM ' + name + ' ORDER BY rowid').fetchall() for name in TABLES}


def seed(application):
    clients = []
    for number in (1, 2):
        client, headers = member(application, number)
        clients.append((client, headers))
        response = client.post('/api/finance-accounts', headers=headers, json={
            'requestId': str(number) * 32, 'revision': 0, 'name': f'=PRIVATE_ACCOUNT_{number}',
            'institution': f'PRIVATE_INSTITUTION_{number}', 'note': f'PRIVATE_NOTE_{number}',
            'kind': 'asset' if number == 1 else 'liability', 'currency': 'USD',
            'valuation': {'asOf': '2026-09-01', 'amountCents': 0}})
        assert response.status_code == 201, response.json
        rid = response.json['accountId']
        response = client.put('/api/finance-accounts/' + rid + '/valuations/2026-09-17', headers=headers,
            json={'requestId': str(number + 2) * 32, 'revision': 1, 'amountCents': None})
        assert response.status_code == 200, response.json
        response = client.patch('/api/finance-accounts/' + rid, headers=headers,
            json={'requestId': str(number + 4) * 32, 'revision': 2, 'changes': {'archived': True}})
        assert response.status_code == 200, response.json
    # Future stored fields and receipt extensions must never enter an export.
    with closing(sqlite3.connect(Path(application.config['DATA_DIR']) / 'household.sqlite3')) as con:
        for name in TABLES:
            con.execute('ALTER TABLE ' + name + ' ADD COLUMN future_secret TEXT')
            con.execute('UPDATE ' + name + " SET future_secret='FORBIDDEN_FUTURE_VALUE'")
        con.execute("UPDATE finance_account_operations SET result=?", (json.dumps({'secret': 'FORBIDDEN_RECEIPT'}),))
        con.commit()
    return clients


@pytest.mark.parametrize('include_shared', [False, True])
def test_export_has_only_owner_accounts_all_dates_and_minimal_operations(app, include_shared):
    clients = seed(app)
    before = snapshot(app)
    for number, (client, headers) in enumerate(clients, 1):
        response = client.get('/api/portability/summary')
        assert response.status_code == 200
        assert response.json['personal']['financeAccounts'] == 1
        assert 'financeAccounts' not in response.json['shared']
        result, files = unpack(client.post('/api/portability/export', headers=headers,
                                          json={'includeShared': include_shared}))
        export = result['personal']['financeAccounts']
        assert set(export) == {'accounts', 'valuations', 'operations'}
        assert len(export['accounts']) == 1
        account = export['accounts'][0]
        assert set(account) == {'id', 'owner', 'name', 'institution', 'kind', 'currency', 'note',
                               'archived', 'revision', 'createdAt', 'updatedAt', 'visibility'}
        assert account['name'] == f'=PRIVATE_ACCOUNT_{number}'
        assert account['owner'] == f'member{number}' and account['archived'] is True
        assert account['visibility'] == 'private' and account['revision'] == 3
        assert len(export['valuations']) == 2
        assert [(p['asOf'], p['amountCents']) for p in export['valuations']] == [
            ('2026-09-01', 0), ('2026-09-17', None)]
        assert all(set(point) == {'accountId', 'asOf', 'amountCents', 'source', 'updatedAt'}
                   and point['accountId'] == account['id'] for point in export['valuations'])
        assert len(export['operations']) == 3
        assert all(set(operation) == {'operation', 'accountId', 'completedAt'}
                   and operation['accountId'] == account['id'] for operation in export['operations'])
        assert result['coverage']['financeAccounts'] == 'manual_accounts_and_dated_valuations'
        assert result['coverage']['completeFinancialCoverage'] is False
        assert 'financeAccounts' not in result.get('shared', {})
        combined = b''.join(files.values())
        for marker in ('FORBIDDEN_', f'PRIVATE_ACCOUNT_{3-number}', f'PRIVATE_INSTITUTION_{3-number}',
                       f'PRIVATE_NOTE_{3-number}'):
            assert marker.encode() not in combined
        # The financial group never includes operation request IDs or payload hashes.
        encoded = json.dumps(export)
        assert 'requestId' not in encoded and 'payload_hash' not in encoded
    assert snapshot(app) == before


def test_empty_account_export_is_explicit_and_other_finance_stays_separate(app):
    client, headers = member(app)
    result, _ = unpack(client.post('/api/portability/export', json={}, headers=headers))
    assert result['personal']['financeAccounts'] == {'accounts': [], 'valuations': [], 'operations': []}
    assert result['personal']['investments'] == []
    assert result['personal']['transactions'] == []
    assert result['personal']['financeBaselines'] == []
    assert client.get('/api/portability/summary').json['personal']['financeAccounts'] == 0
