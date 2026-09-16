"""Actual stopped two-household SQLite migration and documented group restore.

All credentials, financial rows and directories are disposable test fixtures.
No network, cloud service, production data or application-based migration.
"""
import copy
from contextlib import closing
import json
from pathlib import Path
import shutil
import socket
import sqlite3
import sys

import pytest

import app as app_module
import finance_hub
from deploy.backup import backup_all
from deploy import check_finance_receipt_migration as migration
from deploy.rehearse_restore import documented_programs


ROOT = Path(__file__).resolve().parents[1]


def login(application, member='member1'):
    client = application.test_client()
    response = client.post('/api/login', json={'username': member, 'password': 'synthetic-receipt-password'})
    assert response.status_code == 200, response.json
    return client, {'X-CSRF-Token': client.get('/api/me').json['csrf'], 'Origin': 'http://localhost'}


def import_row(client, headers, name, *, request_id=None):
    payload = {'source': 'generic', 'kind': 'payments', 'csv':
        'date,title,amount,currency,flow,category,id,status\n2026-08-12,' + name + ',12.34,CNY,expense,测试,' + name + ',成功\n'}
    preview = client.post('/api/finance-hub/imports/preview', json=payload, headers=headers)
    assert preview.status_code == 200 and preview.json['previewToken'], preview.json
    body = {**payload, 'previewToken': preview.json['previewToken']}
    if request_id:
        body['requestId'] = request_id
    confirmed = client.post('/api/finance-hub/imports/confirm', json=body, headers=headers)
    assert confirmed.status_code == 200 and confirmed.json['imported'] == 1, confirmed.json
    return body, confirmed.json


@pytest.fixture
def group(tmp_path, monkeypatch):
    def offline(*_args, **_kwargs):
        raise AssertionError('Synthetic migration must never access the network')
    monkeypatch.setattr(socket.socket, 'connect', offline)
    monkeypatch.setattr(socket, 'create_connection', offline)
    root = tmp_path / 'original'
    config = {'TESTING': True, 'DATA_DIR': str(root), 'SECRET_KEY': 'synthetic-finance-receipt-migration',
        'SESSION_COOKIE_SECURE': False, 'PUBLIC_ORIGIN': 'http://localhost',
        'MEMBER1_PASSWORD': 'synthetic-receipt-password', 'MEMBER2_PASSWORD': 'synthetic-receipt-password',
        'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': '', 'MICROSOFT_CLIENT_ID': '', 'MICROSOFT_CLIENT_SECRET': '',
        'ASSISTANT_PROVIDER': 'local', 'NVIDIA_API_KEY': '', 'OPENAI_API_KEY': ''}
    # Reconstruct only the immediately preceding 53-table factory. No DDL is
    # removed, and this patch ends before migrating or opening the new factory.
    with monkeypatch.context() as historical:
        historical.setattr(finance_hub, 'FINANCE_IMPORT_RECEIPTS_SCHEMA_SQL', '')
        app = app_module.create_app(config)
        client, headers = login(app)
        import_row(client, headers, '合成旧户流水')
        invited = client.post('/api/spaces/invitations', json={}, headers=headers)
        assert invited.status_code == 201
        redeemed = client.post('/api/spaces/redeem', json={'invitation': invited.json['invitation'],
            'name': '合成第二家庭', 'slug': 'receipt-migration-two',
            'MEMBER1_PASSWORD': 'synthetic-receipt-password', 'MEMBER2_PASSWORD': 'synthetic-receipt-password'}, headers=headers)
        assert redeemed.status_code == 201, redeemed.json
        platform = app.extensions['household_platform']
        child_info = next(v for v in platform.households() if v['id'] != 'default')
        child = platform.child(child_info)
        second, second_headers = login(child)
        import_row(second, second_headers, '合成第二户旧流水')
    for uid in ('default', child_info['id']):
        path = migration.media.checked_path(root, migration.media.relative_database(uid))
        with closing(sqlite3.connect(path)) as con:
            con.execute("INSERT INTO journey_documents(id,owner,request_id,payload_digest,title,filename,mime_type,content,bytes,visibility,created_at,updated_at) VALUES('preserved-document','member1','synthetic-request','synthetic-digest','合成旧资料','sample.pdf','application/pdf',x'001122ff',4,'private','now','now')")
            con.execute("INSERT INTO audit(actor,action,target,stamp) VALUES('member1','synthetic_keep','preserve-audit-sequence','2026-09-17')")
            con.commit()
    before = migration.snapshot(root)
    migration.verify_baseline(before)
    return root, before, backup_all(root), migration.schema_definition(), config, child_info['id']


def test_two_real_households_migrate_atomically_per_database_and_restart(group):
    root, before, backup, schema, config, _ = group
    result = migration.migrate(root, before, backup, schema)
    assert result == {'originalTablesPreserved': 53, 'newTables': 1, 'households': 2,
        'newTableEmpty': True, 'oldRowsSchemaAndSequencesPreserved': True, 'registryPreserved': True}
    after = migration.snapshot(root)
    assert migration.verify_addition(before, after, schema) == result
    application = app_module.create_app(config)
    platform = application.extensions['household_platform']
    for entry in platform.households():
        platform.child(entry)
    assert migration.snapshot(root) == after, 'The new factory must not further mutate the stopped group'
    for uid, value in after['households'].items():
        assert value['tables']['hub_transactions']['count'] == 1
        assert value['tables']['journey_documents']['count'] == 1
        assert value['tables']['sqlite_sequence'] == before['households'][uid]['tables']['sqlite_sequence']
    with pytest.raises(RuntimeError, match='database_changed_after_snapshot'):
        migration.migrate(root, before, backup, schema)


def copy_backup_group_to_new_root(root, backup, destination):
    assert not destination.exists()
    destination.mkdir()
    manifest = json.loads((root / 'backups' / backup['manifest']).read_text(encoding='utf-8'))
    for relative in [value['path'] for value in manifest['snapshots']] + ['backups/' + backup['manifest']]:
        source = migration.media.checked_path(root, relative)
        target = destination / relative
        assert target.resolve().is_relative_to(destination.resolve())
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def test_documented_full_group_restore_keeps_real_receipts_and_provenance(group, tmp_path, monkeypatch):
    root, before, backup, schema, config, child_id = group
    migration.migrate(root, before, backup, schema)
    application = app_module.create_app(config)
    platform = application.extensions['household_platform']
    receipts, originals, old_cookie = {}, {}, None
    for entry in platform.households():
        app = platform.child(entry)
        client, headers = login(app)
        request_id = ('a' if entry['id'] == 'default' else 'b') * 32
        body, result = import_row(client, headers, '合成新回执-' + entry['id'], request_id=request_id)
        receipts[entry['id']] = (request_id, body, result)
        originals[entry['id']] = client.get('/api/finance-hub/overview?month=2026-08').json['transactions']
        if entry['id'] == 'default':
            old_cookie = client.get_cookie(app.config['SESSION_COOKIE_NAME'])
    reference = migration.snapshot(root)
    assert migration.verify_current(reference, schema)['receiptRows'] == 2
    backup54 = backup_all(root)
    assert migration.validate_backup(root, reference, backup54)['databases'] == 3
    destination = tmp_path / 'restored'
    copy_backup_group_to_new_root(root, backup54, destination)
    restore_program, invalidate_program = documented_programs(ROOT)
    literal = "root = Path('/data').resolve(strict=True)"
    assert restore_program.count(literal) == 1
    restore_program = restore_program.replace(literal, 'root = Path(' + repr(str(destination)) + ').resolve(strict=True)')
    with monkeypatch.context() as invocation:
        invocation.setattr(sys, 'argv', ['documented-restore', backup54['manifest'], 'platform', 'default'])
        exec(compile(restore_program, '<documented-full-group-restore>', 'exec'), {'__name__': '__main__'})
    restored = migration.snapshot(destination)
    proof = migration.verify_restore(reference, restored, schema)
    assert proof['completeGroupRestored'] and proof['receiptRows'] == 2 and proof['households'] == 2
    assert migration.snapshot(root) == reference, 'Recovery rehearsal must not modify the original data directory'
    # Follow the documented recovery sequence: revoke restored login/OAuth
    # state before starting the recovered factory, then use fresh real login.
    for uid in reference['households']:
        with closing(sqlite3.connect(migration.media.checked_path(destination, migration.media.relative_database(uid)))) as con:
            con.executescript(invalidate_program)
    recovered = app_module.create_app({**config, 'DATA_DIR': str(destination)})
    stale = recovered.test_client()
    assert old_cookie
    stale.set_cookie(recovered.config['SESSION_COOKIE_NAME'], old_cookie.value)
    assert stale.get('/api/finance-hub/overview?month=2026-08').status_code == 401
    recovered_platform = recovered.extensions['household_platform']
    for entry in recovered_platform.households():
        client, headers = login(recovered_platform.child(entry))
        request_id, body, result = receipts[entry['id']]
        read = client.get('/api/finance-hub/imports/results/' + request_id)
        assert read.status_code == 200 and read.json == {**result, 'replayed': True}
        assert client.get('/api/finance-hub/overview?month=2026-08').json['transactions'] == originals[entry['id']]
        replay = client.post('/api/finance-hub/imports/confirm', json=body, headers=headers)
        assert replay.status_code == 200 and replay.json == read.json
        foreign_request = ('b' if entry['id'] == 'default' else 'a') * 32
        assert client.get('/api/finance-hub/imports/results/' + foreign_request).status_code == 404
    assert set(receipts) == {'default', child_id}


@pytest.mark.parametrize('damage', ['missing-database', 'digest', 'contents', 'count', 'duplicate'])
def test_invalid_whole_group_backup_is_rejected_before_ddl(group, damage):
    root, before, backup, schema, _, _ = group
    manifest_path = root / 'backups' / backup['manifest']
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if damage == 'missing-database':
        manifest['snapshots'].pop()
        code = 'incomplete_backup_group'
    elif damage == 'digest':
        manifest['snapshots'][0]['sha256'] = '0' * 64
        code = 'backup_digest'
    elif damage == 'count':
        backup = {**backup, 'databases': 1}
        code = 'incomplete_backup_group'
    elif damage == 'duplicate':
        manifest['snapshots'].append(copy.deepcopy(manifest['snapshots'][0]))
        code = 'backup_duplicate_or_extra'
    else:
        item = next(v for v in manifest['snapshots'] if 'household-' in v['path'])
        path = root / item['path']
        with closing(sqlite3.connect(path)) as con:
            con.execute("UPDATE audit SET target='tampered' WHERE action='synthetic_keep'")
            con.commit()
        item['sha256'] = migration.media.legacy.file_digest(path)
        item['bytes'] = path.stat().st_size
        code = 'backup_contents'
    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(RuntimeError, match=code):
        migration.migrate(root, before, backup, schema)
    assert migration.snapshot(root) == before


def test_changed_schema_payload_is_rejected_before_ddl(group):
    root, before, backup, schema, _, _ = group
    changed = copy.deepcopy(schema)
    changed['sql'] += '\nDROP TABLE users;'
    with pytest.raises(RuntimeError, match='schema_changed_after_review'):
        migration.migrate(root, before, backup, changed)
    assert migration.snapshot(root) == before


def test_migration_never_uses_application_factory(group, monkeypatch):
    root, before, backup, schema, _, _ = group
    def forbidden(*_args, **_kwargs):
        raise AssertionError('Application factory must not perform the migration')
    monkeypatch.setattr(app_module, 'create_app', forbidden)
    assert migration.migrate(root, before, backup, schema)['newTableEmpty']


@pytest.mark.parametrize('damage', ['row', 'sequence', 'index', 'registry'])
def test_drift_after_snapshot_is_rejected_before_any_ddl(group, damage):
    root, before, backup, schema, _, _ = group
    path = root / ('platform.sqlite3' if damage == 'registry' else 'household.sqlite3')
    with closing(sqlite3.connect(path)) as con:
        if damage == 'row':
            con.execute("UPDATE audit SET target='changed' WHERE action='synthetic_keep'")
        elif damage == 'sequence':
            con.execute("UPDATE sqlite_sequence SET seq=seq+1 WHERE name='audit'")
        elif damage == 'index':
            con.execute('CREATE INDEX synthetic_unreviewed ON hub_transactions(owner,created_at)')
        else:
            con.execute("UPDATE households SET name='Changed household' WHERE id='default'")
        con.commit()
    drifted = migration.snapshot(root)
    with pytest.raises(RuntimeError, match='database_changed_after_snapshot'):
        migration.migrate(root, before, backup, schema)
    assert migration.snapshot(root) == drifted


def test_mixed_and_already_migrated_group_cannot_be_used_as_a_baseline(group):
    root, before, backup, schema, _, _ = group
    migration.media.legacy.initialize_database(root / 'household.sqlite3', schema['sql'])
    mixed = migration.snapshot(root)
    with pytest.raises(RuntimeError, match='database_changed_after_snapshot'):
        migration.migrate(root, before, backup, schema)
    with pytest.raises(RuntimeError, match='expected_53_table_baseline'):
        migration.migrate(root, mixed, backup, schema)
    assert migration.snapshot(root) == mixed
    for uid in before['households']:
        if uid != 'default':
            migration.media.legacy.initialize_database(migration.media.checked_path(root, migration.media.relative_database(uid)), schema['sql'])
    complete = migration.snapshot(root)
    with pytest.raises(RuntimeError, match='expected_53_table_baseline'):
        migration.migrate(root, complete, backup, schema)
    assert migration.snapshot(root) == complete


def test_partial_group_failure_is_retained_and_never_replayed_or_restored(group, monkeypatch):
    root, before, backup, schema, _, _ = group
    original = migration.media.legacy.initialize_database
    calls = []
    def stop_after_one(path, sql):
        calls.append(path)
        if len(calls) == 2:
            raise RuntimeError('synthetic_interrupt')
        return original(path, sql)
    monkeypatch.setattr(migration.media.legacy, 'initialize_database', stop_after_one)
    with pytest.raises(RuntimeError, match='synthetic_interrupt'):
        migration.migrate(root, before, backup, schema)
    partial = migration.snapshot(root)
    assert sorted('hub_import_receipts' in value['tables'] for value in partial['households'].values()) == [False, True]
    with pytest.raises(RuntimeError, match='database_changed_after_snapshot'):
        migration.migrate(root, before, backup, schema)
    assert len(calls) == 2 and migration.snapshot(root) == partial


@pytest.mark.parametrize('damage,code', [('row', 'original_data_or_columns_changed'), ('index', 'schema_change_not_exact_addition'),
    ('receipt-index', 'receipt_schema_changed'), ('receipt-row', 'new_table_not_empty')])
def test_post_migration_damage_is_detected(group, damage, code):
    root, before, backup, schema, _, _ = group
    migration.migrate(root, before, backup, schema)
    with closing(sqlite3.connect(root / 'household.sqlite3')) as con:
        if damage == 'row':
            con.execute("UPDATE audit SET target='changed' WHERE action='synthetic_keep'")
        elif damage == 'index':
            con.execute('CREATE INDEX unexpected_original_index ON hub_transactions(owner,created_at)')
        elif damage == 'receipt-index':
            con.execute('CREATE INDEX unexpected_receipt_index ON hub_import_receipts(created_at)')
        else:
            con.execute("INSERT INTO hub_import_receipts VALUES('member1',?,?,?,'{}','now')", ('c' * 32, 'd' * 64, 'e' * 64))
        con.commit()
    with pytest.raises(RuntimeError, match=code):
        migration.verify_addition(before, migration.snapshot(root), schema)


def test_cli_generates_new_reports_and_refuses_overwrite(group, monkeypatch):
    root, before, backup, schema, _, _ = group
    output = root / 'before-review.json'
    monkeypatch.setattr(sys, 'argv', ['check_finance_receipt_migration', 'snapshot', '--data-root', str(root), '--output', str(output)])
    migration.main()
    assert json.loads(output.read_text(encoding='utf-8')) == before
    with pytest.raises(RuntimeError, match='output_must_be_new'):
        migration.main()
    backup_path = root / 'backup-review.json'
    backup_path.write_text(json.dumps(backup), encoding='utf-8')
    for action in ('validate-backup', 'migrate', 'check', 'snapshot-current'):
        target = root / (action + '.json')
        monkeypatch.setattr(sys, 'argv', ['check_finance_receipt_migration', action, '--data-root', str(root),
            '--before', str(output), '--backup', str(backup_path), '--output', str(target)])
        migration.main()
        assert json.loads(target.read_text(encoding='utf-8'))
    assert migration.verify_addition(before, migration.snapshot(root), schema)['newTableEmpty']
