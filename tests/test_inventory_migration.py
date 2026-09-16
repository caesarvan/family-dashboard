"""Stopped, disposable two-household 48 -> 53 databases only."""
import copy
from contextlib import closing
import json
import sqlite3
import socket

import pytest

import app as app_module
import finance_hub
from deploy.backup import backup_all
from deploy import check_inventory_migration as migration


@pytest.fixture(autouse=True)
def historical_without_investment_operations(monkeypatch):
    """This suite models schemas predating the 55th operation-receipt table."""
    import investment_operations
    monkeypatch.setattr(investment_operations, "INVESTMENT_OPERATIONS_SCHEMA_SQL", "")


@pytest.fixture
def group(tmp_path, monkeypatch):
    def offline(*args, **kwargs):
        raise AssertionError('Migration validation must not access the network')
    monkeypatch.setattr(socket.socket, 'connect', offline)
    monkeypatch.setattr(socket, 'create_connection', offline)
    config = {'TESTING': True, 'DATA_DIR': str(tmp_path),
              'SECRET_KEY': 'synthetic-inventory-migration-key', 'SESSION_COOKIE_SECURE': False,
              'MEMBER1_PASSWORD': 'synthetic-password', 'MEMBER2_PASSWORD': 'synthetic-password',
              'PUBLIC_ORIGIN': 'http://localhost', 'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': '',
              'MICROSOFT_CLIENT_ID': '', 'MICROSOFT_CLIENT_SECRET': '', 'ASSISTANT_PROVIDER': 'local',
              'NVIDIA_API_KEY': '', 'OPENAI_API_KEY': ''}
    # Build the actual immediately preceding factory, without ever dropping
    # inventory history or teaching the production helper to remove tables.
    with monkeypatch.context() as fixture:
        fixture.setattr(app_module, 'register_inventory', lambda *args, **kwargs: None)
        fixture.setattr(finance_hub, 'FINANCE_IMPORT_RECEIPTS_SCHEMA_SQL', '')
        app_module.create_app(config)
    with sqlite3.connect(tmp_path/'platform.sqlite3') as con:
        con.row_factory = sqlite3.Row
        row = dict(con.execute("SELECT * FROM households WHERE id='default'").fetchone())
        row.update(id='b'*24, slug='migration-second', name='合成迁移第二户')
        con.execute('INSERT INTO households('+','.join(row)+') VALUES('+','.join('?' for _ in row)+')', tuple(row.values()))
    child = tmp_path/'spaces'/('b'*24)/'household.sqlite3'
    child.parent.mkdir(parents=True)
    with sqlite3.connect(tmp_path/'household.sqlite3') as source, sqlite3.connect(child) as target:
        source.backup(target)
    for path in (tmp_path/'household.sqlite3', child):
        with sqlite3.connect(path) as con:
            con.execute("INSERT INTO audit(actor,action,target,stamp) VALUES('member1','synthetic_keep','existing-sequence','2026-09-16')")
    before = migration.snapshot(tmp_path)
    migration.verify_baseline(before)
    return tmp_path, before, backup_all(tmp_path), migration.schema_definition(), config


def test_two_households_migrate_then_factory_restart_preserves_48_tables(group, monkeypatch):
    root, before, backup, schema, config = group
    result = migration.migrate(root, before, backup, schema)
    assert result == {'originalTablesPreserved': 48, 'newTables': 5, 'households': 2,
                      'newTablesEmpty': True, 'oldRowsSchemaAndSequencesPreserved': True}
    # This historical restart targets 53 tables, preceding finance receipts.
    # The current 54-table factory is exercised by its own migration suite.
    with monkeypatch.context() as historical:
        historical.setattr(finance_hub, 'FINANCE_IMPORT_RECEIPTS_SCHEMA_SQL', '')
        app = app_module.create_app(config)
        platform = app.extensions['household_platform']
        child = platform.child(next(h for h in platform.households() if h['id'] != 'default'))
    assert 'inventory' in app.extensions and 'inventory' in child.extensions
    assert migration.verify_addition(before, migration.snapshot(root), schema) == result
    for uid in before['households']:
        with sqlite3.connect(migration.media.checked_path(root, migration.media.relative_database(uid))) as con:
            triggers = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
            assert {t+'_capacity' for t in migration.NEW_TABLES} <= triggers
            assert con.execute('PRAGMA foreign_key_check').fetchall() == []
    with pytest.raises(RuntimeError, match='database_changed_after_snapshot'):
        migration.migrate(root, before, backup, schema)


@pytest.mark.parametrize('damage', ['missing-database', 'digest', 'contents'])
def test_invalid_whole_group_backup_refused_before_ddl(group, damage):
    root, before, backup, schema, _ = group
    manifest_path = root/'backups'/backup['manifest']
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if damage == 'missing-database':
        manifest['snapshots'].pop()
        code = 'incomplete_backup_group'
    elif damage == 'digest':
        manifest['snapshots'][0]['sha256'] = '0'*64
        code = 'backup_digest'
    else:
        part = next(v for v in manifest['snapshots'] if 'household-' in v['path'])
        path = root/part['path']
        with closing(sqlite3.connect(path)) as con:
            con.execute("UPDATE audit SET target='changed' WHERE action='synthetic_keep'")
            con.commit()
        part['sha256'] = migration.media.legacy.file_digest(path)
        part['bytes'] = path.stat().st_size
        code = 'backup_contents'
    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(RuntimeError, match=code):
        migration.migrate(root, before, backup, schema)
    assert migration.snapshot(root) == before


def test_schema_payload_cannot_add_arbitrary_sql(group):
    root, before, backup, schema, _ = group
    modified = copy.deepcopy(schema)
    modified['sql'] += '\nDROP TABLE users;'
    with pytest.raises(RuntimeError, match='schema_changed_after_review'):
        migration.migrate(root, before, backup, modified)
    assert migration.snapshot(root) == before


def test_mixed_group_and_already_migrated_baseline_refuse_replay(group):
    root, before, backup, schema, _ = group
    migration.media.legacy.initialize_database(root/'household.sqlite3', schema['sql'])
    mixed = migration.snapshot(root)
    with pytest.raises(RuntimeError, match='database_changed_after_snapshot'):
        migration.migrate(root, before, backup, schema)
    with pytest.raises(RuntimeError, match='expected_48_table_baseline'):
        migration.migrate(root, mixed, backup, schema)
    assert migration.snapshot(root) == mixed


@pytest.mark.parametrize('damage,code', [('old-row', 'original_data_or_columns_changed'),
                                       ('extra-index', 'schema_change_not_exact_addition')])
def test_post_migration_old_rows_and_schema_change_detected(group, damage, code):
    root, before, backup, schema, _ = group
    migration.migrate(root, before, backup, schema)
    with sqlite3.connect(root/'household.sqlite3') as con:
        if damage == 'old-row':
            con.execute("UPDATE audit SET target='changed' WHERE action='synthetic_keep'")
        else:
            con.execute('CREATE INDEX unexpected_inventory_index ON inventory_items(title)')
    with pytest.raises(RuntimeError, match=code):
        migration.verify_addition(before, migration.snapshot(root), schema)


def test_cli_snapshot_and_existing_output_guard(group, monkeypatch):
    root, before, _, _, _ = group
    output = root/'before-review.json'
    monkeypatch.setattr('sys.argv', ['check_inventory_migration', 'snapshot',
                        '--data-root', str(root), '--output', str(output)])
    migration.main()
    assert json.loads(output.read_text(encoding='utf-8')) == before
    with pytest.raises(RuntimeError, match='output_must_be_new'):
        migration.main()
