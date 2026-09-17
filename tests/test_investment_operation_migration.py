"""Stopped 54→55 migration, interrupted groups and full restore of real receipts.

Only disposable two-household SQLite data. No production, credentials or network.
"""
from contextlib import closing
import copy
import json
from pathlib import Path
import socket
import sqlite3
import sys

import pytest

import app as app_module
import investment_operations
from deploy import check_investment_operation_migration as migration
from deploy.backup import backup_all
from deploy.rehearse_restore import documented_programs
from test_finance_receipt_migration import login, import_row, copy_backup_group_to_new_root


@pytest.fixture(autouse=True)
def historical_without_manual_accounts(monkeypatch):
    """Keep both factories at the historical 54/55-table release boundary."""
    monkeypatch.setattr(app_module, 'register_finance_accounts', lambda *_args, **_kwargs: None)


@pytest.fixture
def group(tmp_path, monkeypatch):
    def offline(*_args, **_kwargs):
        raise AssertionError('Migration fixtures cannot use the network')
    monkeypatch.setattr(socket.socket, 'connect', offline)
    monkeypatch.setattr(socket, 'create_connection', offline)
    root = tmp_path / 'original'
    config = {'TESTING': True, 'DATA_DIR': str(root), 'SECRET_KEY': 'synthetic-investment-migration',
        'SESSION_COOKIE_SECURE': False, 'PUBLIC_ORIGIN': 'http://localhost',
        'MEMBER1_PASSWORD': 'synthetic-receipt-password', 'MEMBER2_PASSWORD': 'synthetic-receipt-password',
        'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': '', 'MICROSOFT_CLIENT_ID': '',
        'MICROSOFT_CLIENT_SECRET': '', 'ASSISTANT_PROVIDER': 'local', 'NVIDIA_API_KEY': '', 'OPENAI_API_KEY': ''}
    with monkeypatch.context() as historical:
        historical.setattr(investment_operations, 'INVESTMENT_OPERATIONS_SCHEMA_SQL', '')
        application = app_module.create_app(config)
        client, headers = login(application)
        invitation = client.post('/api/spaces/invitations', json={}, headers=headers)
        assert invitation.status_code == 201
        response = client.post('/api/spaces/redeem', json={'invitation': invitation.json['invitation'],
            'name': '合成第二家庭', 'slug': 'investment-migration-two',
            'MEMBER1_PASSWORD': 'synthetic-receipt-password', 'MEMBER2_PASSWORD': 'synthetic-receipt-password'}, headers=headers)
        assert response.status_code == 201, response.json
        platform = application.extensions['household_platform']
        for entry in platform.households():
            client, headers = login(platform.child(entry))
            import_row(client, headers, '合成旧回执-' + entry['id'], request_id='c' * 32)
            response = client.post('/api/finance-hub/investments', json=holding('旧持仓'), headers=headers)
            assert response.status_code == 201, response.json
    before = migration.snapshot(root)
    migration.verify_baseline(before)
    return root, before, backup_all(root), migration.schema_definition(), config


def holding(name):
    return {'name': name, 'institution': '合成机构', 'assetType': '基金', 'currency': 'USD',
        'quantity': '1.25', 'cost': '123.45', 'value': None, 'asOf': '2026-09-17', 'note': '虚构数据'}


def test_exact_addition_and_new_factory_preserve_original_rows_and_finance_receipts(group):
    root, before, backup, schema, config = group
    proof = migration.migrate(root, before, backup, schema)
    assert proof == {'originalTablesPreserved': 54, 'newTables': 1, 'households': 2,
        'newTableEmpty': True, 'oldRowsSchemaAndSequencesPreserved': True, 'registryPreserved': True}
    after = migration.snapshot(root)
    platform = app_module.create_app(config).extensions['household_platform']
    for entry in platform.households():
        platform.child(entry)
    assert migration.snapshot(root) == after
    assert all(v['tables']['hub_import_receipts']['count'] == 1 for v in after['households'].values())
    with pytest.raises(RuntimeError, match='database_changed_after_snapshot'):
        migration.migrate(root, before, backup, schema)


def test_documented_restore_preserves_deleted_record_receipt_and_replays_after_new_login(group, tmp_path, monkeypatch):
    root, before, backup, schema, config = group
    migration.migrate(root, before, backup, schema)
    application = app_module.create_app(config)
    platform = application.extensions['household_platform']
    results = {}
    for entry in platform.households():
        child = platform.child(entry)
        client, headers = login(child)
        payload = {**holding('合成新持仓-' + entry['id']), 'requestId': 'a' * 32}
        created = client.post('/api/finance-hub/investments', json=payload, headers=headers)
        assert created.status_code == 201, created.json
        rid = created.json['id']
        deleted = client.delete('/api/finance-hub/investments/' + rid,
            json={'requestId': 'b' * 32, 'revision': created.json['revision']}, headers=headers)
        assert deleted.status_code == 200 and deleted.json['deleted']
        results[entry['id']] = (rid, payload, client.get('/api/finance-hub/investments/operations/' + 'b' * 32).json)
    reference = migration.snapshot(root)
    assert migration.verify_current(reference, schema)['receiptRows'] == 4
    complete = backup_all(root)
    assert migration.validate_backup(root, reference, complete)['databases'] == 3
    destination = tmp_path / 'restored'
    copy_backup_group_to_new_root(root, complete, destination)
    restore, invalidate = documented_programs(Path(__file__).resolve().parents[1])
    literal = "root = Path('/data').resolve(strict=True)"
    assert restore.count(literal) == 1
    restore = restore.replace(literal, 'root = Path(' + repr(str(destination)) + ').resolve(strict=True)')
    with monkeypatch.context() as invocation:
        invocation.setattr(sys, 'argv', ['documented-restore', complete['manifest'], 'platform', 'default'])
        exec(compile(restore, '<synthetic-investment-restore>', 'exec'), {'__name__': '__main__'})
    assert migration.verify_restore(reference, migration.snapshot(destination), schema)['completeGroupRestored']
    assert migration.snapshot(root) == reference
    for uid in reference['households']:
        path = migration.media.checked_path(destination, migration.media.relative_database(uid))
        with closing(sqlite3.connect(path)) as con:
            con.executescript(invalidate)
    recovered = app_module.create_app({**config, 'DATA_DIR': str(destination)}).extensions['household_platform']
    for entry in recovered.households():
        client, headers = login(recovered.child(entry))
        rid, payload, deleted = results[entry['id']]
        assert client.get('/api/finance-hub/investments/operations/' + 'b' * 32).json == deleted
        replay = client.post('/api/finance-hub/investments', json=payload, headers=headers)
        assert replay.status_code == 201 and replay.json['id'] == rid and replay.json['replayed']
        assert rid not in {v['id'] for v in client.get('/api/finance-hub/investments').json['investments']}
        assert client.get('/api/finance-hub/imports/results/' + 'c' * 32).status_code == 200


@pytest.mark.parametrize('damage', ['missing-db', 'digest', 'count', 'duplicate', 'schema', 'row'])
def test_preflight_rejects_drift_or_incomplete_backup_before_any_ddl(group, damage):
    root, before, backup, schema, _ = group
    if damage in {'missing-db', 'digest', 'duplicate'}:
        path = root / 'backups' / backup['manifest']
        manifest = json.loads(path.read_text())
        if damage == 'missing-db': manifest['snapshots'].pop()
        elif damage == 'digest': manifest['snapshots'][0]['sha256'] = '0' * 64
        else: manifest['snapshots'].append(copy.deepcopy(manifest['snapshots'][0]))
        path.write_text(json.dumps(manifest))
    elif damage == 'count': backup = {**backup, 'databases': 1}
    elif damage == 'schema': schema = {**schema, 'sql': schema['sql'] + '; DROP TABLE users;'}
    else:
        with closing(sqlite3.connect(root / 'household.sqlite3')) as con:
            con.execute("UPDATE audit SET target='synthetic-drift'")
            con.commit()
    retained = migration.snapshot(root)
    with pytest.raises(RuntimeError): migration.migrate(root, before, backup, schema)
    assert migration.snapshot(root) == retained


def test_partial_group_interruption_retains_evidence_and_refuses_replay(group, monkeypatch):
    root, before, backup, schema, _ = group
    original = migration.media.legacy.initialize_database
    calls = []
    def interrupt(path, sql):
        calls.append(path)
        if len(calls) == 2: raise RuntimeError('synthetic-interruption')
        return original(path, sql)
    monkeypatch.setattr(migration.media.legacy, 'initialize_database', interrupt)
    with pytest.raises(RuntimeError, match='synthetic-interruption'): migration.migrate(root, before, backup, schema)
    retained = migration.snapshot(root)
    assert sorted('hub_investment_operations' in v['tables'] for v in retained['households'].values()) == [False, True]
    with pytest.raises(RuntimeError, match='database_changed_after_snapshot'): migration.migrate(root, before, backup, schema)
    assert migration.snapshot(root) == retained and len(calls) == 2
