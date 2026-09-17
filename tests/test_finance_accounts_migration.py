"""Real disposable two-household 55→58 migration, rollback and populated restore."""
from contextlib import closing
import copy
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys

import pytest

import app as app_module
import finance_accounts
from deploy import check_finance_accounts_migration as migration
from deploy.backup import backup_all
from deploy.rehearse_restore import documented_programs
from test_finance_receipt_migration import login, import_row, copy_backup_group_to_new_root

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def group(tmp_path, monkeypatch):
    def offline(*_args, **_kwargs):
        raise AssertionError('Synthetic migration cannot use the network')
    monkeypatch.setattr(socket.socket, 'connect', offline)
    monkeypatch.setattr(socket, 'create_connection', offline)
    root = tmp_path / 'original'
    config = {'TESTING': True, 'DATA_DIR': str(root), 'SECRET_KEY': 'synthetic-account-migration',
        'SESSION_COOKIE_SECURE': False, 'PUBLIC_ORIGIN': 'http://localhost',
        'MEMBER1_PASSWORD': 'synthetic-receipt-password', 'MEMBER2_PASSWORD': 'synthetic-receipt-password',
        'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': '', 'MICROSOFT_CLIENT_ID': '',
        'MICROSOFT_CLIENT_SECRET': '', 'ASSISTANT_PROVIDER': 'local', 'NVIDIA_API_KEY': '', 'OPENAI_API_KEY': ''}
    # Reconstruct the real immediately preceding factory. No tables are dropped,
    # and the patch ends before the migration or any new-factory restart.
    with monkeypatch.context() as historical:
        historical.setattr(app_module, 'register_finance_accounts', lambda *_a, **_kw: None)
        app = app_module.create_app(config)
        client, headers = login(app)
        invited = client.post('/api/spaces/invitations', json={}, headers=headers)
        assert invited.status_code == 201
        redeemed = client.post('/api/spaces/redeem', json={'invitation': invited.json['invitation'],
            'name': '合成账户迁移家庭', 'slug': 'accounts-migration-two',
            'MEMBER1_PASSWORD': 'synthetic-receipt-password', 'MEMBER2_PASSWORD': 'synthetic-receipt-password'}, headers=headers)
        assert redeemed.status_code == 201, redeemed.json
        platform = app.extensions['household_platform']
        for entry in platform.households():
            client, headers = login(platform.child(entry))
            import_row(client, headers, '合成流水-' + entry['id'], request_id='c' * 32)
            created = client.post('/api/finance-hub/investments', json={'requestId': 'd' * 32,
                'name': '合成旧持仓', 'institution': '合成机构', 'assetType': '基金', 'currency': 'USD',
                'quantity': '1.25', 'cost': '123.45', 'value': None, 'asOf': '2026-09-17', 'note': '虚构数据'}, headers=headers)
            assert created.status_code == 201, created.json
            path = migration.media.checked_path(root, migration.media.relative_database(entry['id']))
            with closing(sqlite3.connect(path)) as con:
                con.execute("INSERT INTO journey_documents(id,owner,request_id,payload_digest,title,filename,mime_type,content,bytes,visibility,created_at,updated_at) VALUES('synthetic-doc','member1','synthetic-key','synthetic-digest','合成旧资料','sample.pdf','application/pdf',x'001122ff',4,'private','now','now')")
                con.execute("INSERT INTO audit(actor,action,target,stamp) VALUES('member1','synthetic_keep','sequence-gap','2026-09-17')")
                con.execute("DELETE FROM audit WHERE target='sequence-gap'")
                con.commit()
    before = migration.snapshot(root)
    migration.verify_baseline(before)
    assert len(before['households']) == 2
    return root, before, backup_all(root), migration.schema_definition(), config


def restored_group(root, backup, destination, monkeypatch):
    copy_backup_group_to_new_root(root, backup, destination)
    restore, invalidate = documented_programs(ROOT)
    literal = "root = Path('/data').resolve(strict=True)"
    assert restore.count(literal) == 1
    restore = restore.replace(literal, 'root = Path(' + repr(str(destination)) + ').resolve(strict=True)')
    with monkeypatch.context() as invocation:
        invocation.setattr(sys, 'argv', ['documented-restore', backup['manifest'], 'platform', 'default'])
        exec(compile(restore, '<synthetic-accounts-restore>', 'exec'), {'__name__': '__main__'})
    return invalidate


def test_exact_addition_preserves_55_tables_blobs_receipts_sequences_and_factory_restart(group):
    root, before, backup, schema, config = group
    proof = migration.migrate(root, before, backup, schema)
    assert proof == {'originalTablesPreserved': 55, 'newTables': 3, 'households': 2,
        'newTablesEmpty': True, 'oldRowsSchemaAndSequencesPreserved': True, 'registryPreserved': True}
    after = migration.snapshot(root)
    assert migration.verify_current(after, schema)['newTableRows'] == {name: 0 for name in migration.NEW_TABLES}
    for uid, current in after['households'].items():
        assert all(current['tables'][name] == value for name, value in before['households'][uid]['tables'].items())
        assert current['tables']['journey_documents']['count'] == 1
        assert current['tables']['hub_import_receipts']['count'] == 1
        assert current['tables']['hub_investment_operations']['count'] == 1
    platform = app_module.create_app(config).extensions['household_platform']
    for entry in platform.households(): platform.child(entry)
    assert migration.snapshot(root) == after
    with pytest.raises(RuntimeError, match='database_changed_after_snapshot'):
        migration.migrate(root, before, backup, schema)


def test_populated_58_backup_documented_restore_and_original_receipt_recovery(group, tmp_path, monkeypatch):
    root, before, backup, schema, config = group
    migration.migrate(root, before, backup, schema)
    platform = app_module.create_app(config).extensions['household_platform']
    results = {}
    for entry in platform.households():
        client, headers = login(platform.child(entry))
        payload = {'requestId': 'a' * 32, 'revision': 0, 'name': '合成账户-' + entry['id'],
            'institution': '本人填写', 'kind': 'asset' if entry['id'] == 'default' else 'liability',
            'currency': 'USD', 'note': '仅合成数据', 'valuation': {'asOf': '2026-09-17', 'amountCents': 0}}
        response = client.post('/api/finance-accounts', json=payload, headers=headers)
        assert response.status_code == 201, response.json
        account_id = response.json['accountId']
        value = client.put('/api/finance-accounts/' + account_id + '/valuations/2026-09-16',
            json={'requestId': 'b' * 32, 'revision': 1, 'amountCents': None}, headers=headers)
        assert value.status_code == 200, value.json
        archived = client.patch('/api/finance-accounts/' + account_id,
            json={'requestId': 'e' * 32, 'revision': 2, 'changes': {'archived': True}}, headers=headers)
        assert archived.status_code == 200, archived.json
        results[entry['id']] = (payload, account_id, client.get('/api/finance-accounts/operations/' + 'e' * 32).json)
    reference = migration.snapshot(root)
    assert migration.verify_current(reference, schema)['newTableRows'] == {
        'finance_accounts': 2, 'finance_account_valuations': 4, 'finance_account_operations': 6}
    complete = backup_all(root)
    assert migration.validate_backup(root, reference, complete)['databases'] == 3
    destination = tmp_path / 'restored58'
    invalidate = restored_group(root, complete, destination, monkeypatch)
    assert migration.verify_restore(reference, migration.snapshot(destination), schema)['completeGroupRestored']
    assert migration.snapshot(root) == reference
    for uid in reference['households']:
        with closing(sqlite3.connect(migration.media.checked_path(destination, migration.media.relative_database(uid)))) as con:
            con.executescript(invalidate)
    recovered = app_module.create_app({**config, 'DATA_DIR': str(destination)}).extensions['household_platform']
    for entry in recovered.households():
        client, headers = login(recovered.child(entry))
        payload, account_id, receipt = results[entry['id']]
        assert client.get('/api/finance-accounts/operations/' + 'e' * 32).json == receipt
        replay = client.post('/api/finance-accounts', json=payload, headers=headers)
        assert replay.status_code == 201 and replay.json['replayed'] and replay.json['accountId'] == account_id
        assert client.get('/api/finance-accounts?asOf=2026-09-17').json['accounts'] == []
        history = client.get('/api/finance-accounts/' + account_id + '/valuations').json
        assert history['account']['archived'] and history['account']['revision'] == 3
        assert [v['amountCents'] for v in history['valuations']] == [0, None]
        assert client.get('/api/finance-hub/imports/results/' + 'c' * 32).status_code == 200


@pytest.mark.parametrize('interrupted', [False, True])
def test_documented_complete_55_rollback_after_full_or_partial_migration(group, tmp_path, monkeypatch, interrupted):
    root, before, backup, schema, _ = group
    original = migration.media.legacy.initialize_database
    calls = []
    def initialize(path, sql):
        calls.append(path)
        if interrupted and len(calls) == 2: raise RuntimeError('synthetic-interruption')
        original(path, sql)
    monkeypatch.setattr(migration.media.legacy, 'initialize_database', initialize)
    if interrupted:
        with pytest.raises(RuntimeError, match='synthetic-interruption'): migration.migrate(root, before, backup, schema)
    else:
        migration.migrate(root, before, backup, schema)
    retained = migration.snapshot(root)
    assert sorted('finance_accounts' in v['tables'] for v in retained['households'].values()) == ([False, True] if interrupted else [True, True])
    with pytest.raises(RuntimeError, match='database_changed_after_snapshot'): migration.migrate(root, before, backup, schema)
    assert len(calls) == 2 and migration.snapshot(root) == retained
    destination = tmp_path / 'rolled-back55'
    restored_group(root, backup, destination, monkeypatch)
    assert migration.verify_rollback(before, migration.snapshot(destination))['completeGroupRestored']
    assert migration.snapshot(root) == retained
    assert migration.validate_backup(root, before, backup)['databases'] == 3


@pytest.mark.parametrize('damage', ['missing-db', 'digest', 'bytes', 'count', 'duplicate', 'path', 'contents', 'sidecar', 'schema', 'row', 'registry'])
def test_preflight_rejects_backup_or_source_drift_before_any_ddl(group, monkeypatch, damage):
    root, before, backup, schema, _ = group
    manifest_path = root / 'backups' / backup['manifest']
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if damage in {'missing-db', 'digest', 'bytes', 'duplicate', 'path', 'contents', 'sidecar'}:
        entry = next(v for v in manifest['snapshots'] if 'household-' in v['path'])
        if damage == 'missing-db': manifest['snapshots'].pop()
        elif damage == 'digest': entry['sha256'] = '0' * 64
        elif damage == 'bytes': entry['bytes'] += 1
        elif damage == 'duplicate': manifest['snapshots'].append(copy.deepcopy(entry))
        elif damage == 'path': entry['path'] = '../household.sqlite3'
        elif damage == 'sidecar': Path(str(root / entry['path']) + '-wal').write_bytes(b'synthetic')
        else:
            path = root / entry['path']
            with closing(sqlite3.connect(path)) as con:
                con.execute("UPDATE audit SET target='synthetic-backup-drift'"); con.commit()
            entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            entry['bytes'] = path.stat().st_size
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
    elif damage == 'count': backup = {**backup, 'databases': 1}
    elif damage == 'schema': schema = {**schema, 'sql': schema['sql'] + 'DROP TABLE users;'}
    else:
        path = root / ('platform.sqlite3' if damage == 'registry' else 'household.sqlite3')
        with closing(sqlite3.connect(path)) as con:
            con.execute("UPDATE households SET name='synthetic-drift'" if damage == 'registry' else "UPDATE audit SET target='synthetic-drift'")
            con.commit()
    retained = migration.snapshot(root)
    monkeypatch.setattr(migration.media.legacy, 'initialize_database', lambda *_: pytest.fail('DDL must not start'))
    with pytest.raises(RuntimeError): migration.migrate(root, before, backup, schema)
    assert migration.snapshot(root) == retained


@pytest.mark.parametrize('sql', ['CREATE INDEX finance_accounts ON audit(actor)', 'CREATE VIEW finance_account_valuations AS SELECT actor FROM audit'])
def test_colliding_object_is_rejected_before_any_household_changes(group, monkeypatch, sql):
    root, _, _, schema, _ = group
    with closing(sqlite3.connect(root / 'household.sqlite3')) as con:
        con.execute(sql); con.commit()
    before = migration.snapshot(root)
    migration.verify_baseline(before)
    backup = backup_all(root)
    monkeypatch.setattr(migration.media.legacy, 'initialize_database', lambda *_: pytest.fail('DDL must not start'))
    with pytest.raises(RuntimeError, match='new_object_name_collides'): migration.migrate(root, before, backup, schema)
    assert migration.snapshot(root) == before


def test_failed_third_statement_rolls_back_all_additions_in_one_household(group, monkeypatch):
    root, before, backup, schema, _ = group
    original = migration.media.legacy.initialize_database
    def fail_inside_transaction(path, sql):
        return original(path, sql + '\nSELECT deliberately_missing_function();')
    monkeypatch.setattr(migration.media.legacy, 'initialize_database', fail_inside_transaction)
    with pytest.raises(sqlite3.OperationalError): migration.migrate(root, before, backup, schema)
    assert migration.snapshot(root) == before


@pytest.mark.parametrize('suffix', ['PRAGMA user_version=99;', 'DROP TABLE users;', 'BEGIN;', 'CREATE TABLE extra(id);',
    'CREATE VIEW extra AS SELECT 1;', 'INSERT INTO finance_accounts(id) VALUES(1);'])
def test_schema_constant_refuses_auxiliary_sql(monkeypatch, suffix):
    monkeypatch.setattr(finance_accounts, 'FINANCE_ACCOUNTS_SCHEMA_SQL', finance_accounts.FINANCE_ACCOUNTS_SCHEMA_SQL + suffix)
    with pytest.raises(RuntimeError): migration.schema_definition()


@pytest.mark.parametrize('damage', ['row', 'sequence', 'index', 'column', 'registry', 'household', 'new-column', 'new-row'])
def test_exact_addition_rejects_changed_old_or_new_profile(group, damage):
    root, before, backup, schema, _ = group
    migration.migrate(root, before, backup, schema)
    altered = copy.deepcopy(migration.snapshot(root))
    value = altered['households']['default']
    if damage == 'row': value['tables']['audit']['rowsSha256'] = '0' * 64
    elif damage == 'sequence': value['tables']['sqlite_sequence']['rowsSha256'] = '0' * 64
    elif damage == 'column': value['tables']['audit']['columns'][0][2] = 'TEXT'
    elif damage == 'index': value['schema'].append(['index', 'extra', 'audit', 'CREATE INDEX extra ON audit(actor)'])
    elif damage == 'registry': altered['registry']['tables']['households']['rowsSha256'] = '0' * 64
    elif damage == 'household': altered['households'].pop(next(k for k in altered['households'] if k != 'default'))
    elif damage == 'new-column': value['tables']['finance_accounts']['columns'][0][2] = 'INTEGER'
    else: value['tables']['finance_account_operations']['count'] = 1
    with pytest.raises(RuntimeError): migration.verify_addition(before, altered, schema)
    with pytest.raises(RuntimeError): migration.verify_restore(migration.snapshot(root), altered, schema)


def test_cli_snapshot_backup_migrate_current_check_restore_and_output_collision(group, tmp_path):
    root, _, backup, _, _ = group
    backup_file = tmp_path / 'backup.json'; backup_file.write_text(json.dumps(backup), encoding='utf-8')
    def run(action, output, *arguments, success=True):
        process = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(ROOT / 'deploy/check_finance_accounts_migration.py'),
            action, '--data-root', str(root), '--output', str(output), *map(str, arguments)], capture_output=True, text=True, encoding='utf-8', timeout=30)
        assert (process.returncode == 0) == success, process.stderr
        if success: assert json.loads(process.stdout)['verified'] is True
        return process
    before = tmp_path / 'before.json'
    run('snapshot', before)
    run('validate-backup', tmp_path / 'backup-proof.json', '--before', before, '--backup', backup_file)
    run('migrate', tmp_path / 'migration.json', '--before', before, '--backup', backup_file)
    current = tmp_path / 'current.json'; run('snapshot-current', current)
    run('check', tmp_path / 'check.json', '--before', before)
    run('check-restored', tmp_path / 'same58.json', '--before', current)
    original = current.read_bytes()
    run('snapshot-current', current, success=False)
    assert current.read_bytes() == original
    invalid = tmp_path / 'not-rolled-back.json'
    run('check-rollback', invalid, '--before', before, success=False)
    assert not invalid.exists()
