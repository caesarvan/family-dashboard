"""Real two-household SQLite migration/backup/restore, with no external I/O."""
from contextlib import closing
import copy
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys

import pytest

import app as server
import household_members
from deploy import check_household_members_migration as migration
from deploy.backup import backup_all
from test_finance_receipt_migration import login, import_row
from test_finance_accounts_migration import restored_group

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    def offline(*_args, **_kwargs):
        raise AssertionError('No external network in synthetic migration')
    monkeypatch.setattr(socket.socket, 'connect', offline)
    monkeypatch.setattr(socket, 'create_connection', offline)


@pytest.fixture(scope='module')
def seed(tmp_path_factory):
    root = tmp_path_factory.mktemp('roles-old58')
    config = {'TESTING': True, 'DATA_DIR': str(root), 'SECRET_KEY': 'synthetic-role-migration',
        'SESSION_COOKIE_SECURE': False, 'PUBLIC_ORIGIN': 'http://localhost',
        'MEMBER1_PASSWORD': 'synthetic-receipt-password', 'MEMBER2_PASSWORD': 'synthetic-receipt-password',
        'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': '', 'MICROSOFT_CLIENT_ID': '', 'MICROSOFT_CLIENT_SECRET': '',
        'ASSISTANT_PROVIDER': 'local', 'NVIDIA_API_KEY': '', 'OPENAI_API_KEY': ''}
    def offline(*_a, **_kw):
        raise AssertionError('No network in seed factory')
    with pytest.MonkeyPatch.context() as historical:
        historical.setattr(socket.socket, 'connect', offline)
        historical.setattr(socket, 'create_connection', offline)
        # Reconstruct the immediately preceding 58-table factory; no dropping
        # columns and no substituting the new schema initializer under test.
        historical.setattr(server, 'register_members', lambda *_a, **_kw: None, raising=False)
        app = server.create_app(config)
        client, headers = login(app)
        invite = client.post('/api/spaces/invitations', json={}, headers=headers)
        assert invite.status_code == 201
        created = client.post('/api/spaces/redeem', json={'invitation': invite.json['invitation'],
            'name': '合成角色迁移家庭', 'slug': 'role-migration-two',
            'MEMBER1_PASSWORD': 'synthetic-receipt-password', 'MEMBER2_PASSWORD': 'synthetic-receipt-password'}, headers=headers)
        assert created.status_code == 201, created.json
        platform = app.extensions['household_platform']
        for entry in platform.households():
            client, headers = login(platform.child(entry))
            import_row(client, headers, '合成旧账单-'+entry['id'], request_id='c'*32)
            account = client.post('/api/finance-accounts', json={'requestId':'a'*32,'revision':0,
                'name':'合成账户','institution':'合成机构','kind':'asset','currency':'USD','note':'虚构资料',
                'valuation':{'asOf':'2026-09-17','amountCents':0}}, headers=headers)
            assert account.status_code == 201, account.json
            path = migration.media.checked_path(root, migration.media.relative_database(entry['id']))
            with closing(sqlite3.connect(path)) as con:
                con.execute("INSERT INTO journey_documents(id,owner,request_id,payload_digest,title,filename,mime_type,content,bytes,visibility,created_at,updated_at) VALUES('synthetic-doc','member1','synthetic-key','synthetic-digest','合成旧资料','sample.pdf','application/pdf',x'001122ff',4,'private','now','now')")
                con.execute("INSERT INTO audit(actor,action,target,stamp) VALUES('member1','synthetic_keep','gap','2026-09-18')")
                con.execute("DELETE FROM audit WHERE target='gap'")
                con.commit()
    return root, config


@pytest.fixture
def group(tmp_path, seed):
    source, config = seed
    root = tmp_path / 'group'
    original = migration.media.snapshot(source)
    paths = ['platform.sqlite3'] + [migration.media.relative_database(uid) for uid in original['households']]
    for name in paths:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect((source/name).as_uri()+'?mode=ro', uri=True)) as old, closing(sqlite3.connect(target)) as new:
            old.backup(new)
    before = migration.snapshot(root)
    migration.verify_baseline(before)
    assert len(before['households']) == 2
    return root, before, backup_all(root), migration.schema_definition(), {**config,'DATA_DIR':str(root)}


def test_exact_column_addition_preserves_all_old_values_and_complete_backups(group, monkeypatch):
    root, before, backup, schema, _ = group
    monkeypatch.setattr(server, 'create_app', lambda *_a, **_kw: pytest.fail('Migration must not start the app'))
    proof = migration.migrate(root, before, backup, schema)
    assert proof['originalTablesPreserved'] == 58 and proof['newTables'] == 0
    assert proof['originalUserColumnsPreserved'] == 5 and proof['initialRolesVerified']
    after = migration.snapshot(root)
    assert migration.validate_backup(root, before, backup)['databases'] == 3
    assert after['registry'] == before['registry']
    for uid, value in after['households'].items():
        assert all(value['tables'][n] == v for n,v in before['households'][uid]['tables'].items() if n != 'users')
        assert after['usersProjection'][uid]['roleCounts'] == {'admin':2,'member':0}
        assert value['tables']['journey_documents']['count'] == 1
        assert value['tables']['finance_accounts']['count'] == value['tables']['finance_account_valuations']['count'] == 1
        assert value['tables']['finance_account_operations']['count'] == value['tables']['hub_import_receipts']['count'] == 1
    with pytest.raises(RuntimeError, match='database_changed_after_snapshot'):
        migration.migrate(root, before, backup, schema)
    assert migration.snapshot(root) == after


def test_real_app_init_is_idempotent_and_preserves_later_member_role(group):
    root, before, backup, schema, config = group
    migration.migrate(root, before, backup, schema)
    for uid in before['households']:
        with closing(sqlite3.connect(root/migration.media.relative_database(uid))) as con:
            con.execute("UPDATE users SET household_role='member' WHERE id='member2'"); con.commit()
    reference = migration.snapshot(root)
    assert migration.verify_current(reference, schema)['profile'] == 'household_members58'
    for _ in range(2):
        platform = server.create_app(config).extensions['household_platform']
        for entry in platform.households(): platform.child(entry)
        assert migration.snapshot(root) == reference
    with pytest.raises(RuntimeError, match='initial_roles_not_exact'):
        migration.verify_addition(before, reference, schema)


@pytest.mark.parametrize('current', [False, True])
def test_two_household_documented_backup_restore_and_projection_preservation(group, tmp_path, monkeypatch, current):
    root, before, backup, schema, _ = group
    if current:
        migration.migrate(root, before, backup, schema)
        with closing(sqlite3.connect(root/'household.sqlite3')) as con:
            con.execute("UPDATE users SET household_role='member' WHERE id='member2'"); con.commit()
    reference = migration.snapshot(root)
    complete = backup_all(root)
    assert migration.validate_backup(root, reference, complete)['databases'] == 3
    destination = tmp_path/'restored'
    restored_group(root, complete, destination, monkeypatch)
    restored = migration.snapshot(destination)
    proof = migration.verify_restore(reference, restored, schema) if current else migration.verify_rollback(reference, restored)
    assert proof['completeGroupRestored'] and restored == reference
    assert migration.snapshot(root) == reference


def test_partial_group_failure_is_not_replayed_and_full_group_rollback_is_exact(group, tmp_path, monkeypatch):
    root, before, backup, schema, _ = group
    original, calls = household_members.init_schema, []
    def fail_second(con):
        calls.append(True)
        if len(calls) == 2: raise RuntimeError('synthetic interruption')
        original(con)
    monkeypatch.setattr(household_members, 'init_schema', fail_second)
    with pytest.raises(RuntimeError, match='synthetic interruption'):
        migration.migrate(root, before, backup, schema)
    partial = migration.snapshot(root)
    assert sorted(p['rolesSha256'] is not None for p in partial['usersProjection'].values()) == [False,True]
    with pytest.raises(RuntimeError, match='database_changed_after_snapshot'):
        migration.migrate(root, before, backup, schema)
    with pytest.raises(RuntimeError): migration.verify_current(partial, schema)
    with pytest.raises(RuntimeError): migration.validate_backup(root, partial, backup)
    assert len(calls) == 2 and migration.snapshot(root) == partial
    destination = tmp_path/'rollback'
    restored_group(root, backup, destination, monkeypatch)
    assert migration.verify_rollback(before, migration.snapshot(destination))['completeGroupRestored']
    assert migration.snapshot(root) == partial


def test_initializer_rolls_back_ddl_if_role_update_fails(group, monkeypatch):
    root, before, backup, schema, _ = group
    original = household_members.init_schema
    def fail_after_alter(con):
        def reject_update(action, _arg1, _arg2, _db, _trigger):
            return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_UPDATE and _arg1 == 'users' else sqlite3.SQLITE_OK
        con.set_authorizer(reject_update)
        original(con)
    monkeypatch.setattr(household_members, 'init_schema', fail_after_alter)
    with pytest.raises(sqlite3.DatabaseError): migration.migrate(root, before, backup, schema)
    assert migration.snapshot(root) == before


def test_snapshot_rejects_users_change_between_complete_and_projected_reads(group, monkeypatch):
    root, _, _, _, _ = group
    original = migration.users_projection
    def changed(path, expected, **kwargs):
        with closing(sqlite3.connect(path)) as con:
            con.execute("UPDATE users SET name='new synthetic name' WHERE id='member1'"); con.commit()
        return original(path, expected, **kwargs)
    monkeypatch.setattr(migration, 'users_projection', changed)
    with pytest.raises(RuntimeError, match='users_changed_during_snapshot'): migration.snapshot(root)


@pytest.mark.parametrize('damage', ['live-row','backup-row'])
def test_preflight_refuses_drift_before_any_initializer(group, monkeypatch, damage):
    root, before, backup, schema, _ = group
    target = root/'household.sqlite3'
    if damage == 'backup-row':
        manifest = json.loads((root/'backups'/backup['manifest']).read_text())
        target = root/next(x['path'] for x in manifest['snapshots'] if x['path'].startswith('backups/household-'))
    with closing(sqlite3.connect(target)) as con:
        con.execute("UPDATE users SET password='changed synthetic password' WHERE id='member1'"); con.commit()
    retained = migration.snapshot(root)
    monkeypatch.setattr(household_members, 'init_schema', lambda *_: pytest.fail('Preflight must finish before DDL'))
    with pytest.raises(RuntimeError): migration.migrate(root, before, backup, schema)
    assert migration.snapshot(root) == retained


@pytest.mark.parametrize('damage', ['user-row','audit-row','sequence','user-schema','other-schema','registry','missing-household','roles'])
def test_live_sql_tampering_is_rejected_by_exact_migration_or_restore(group, damage):
    root, before, backup, schema, _ = group
    migration.migrate(root, before, backup, schema)
    reference = migration.snapshot(root)
    target = root/('platform.sqlite3' if damage == 'registry' else 'household.sqlite3')
    sql = {'user-row':"UPDATE users SET password='different' WHERE id='member2'",
           'audit-row':"UPDATE audit SET target='changed'",'sequence':"UPDATE sqlite_sequence SET seq=seq+1 WHERE name='audit'",
           'user-schema':'CREATE INDEX extra_user_index ON users(name)', 'other-schema':'CREATE INDEX extra_audit_index ON audit(actor)',
           'registry':"UPDATE households SET name='changed'",'missing-household':"DELETE FROM users WHERE id='member2'",
           'roles':"UPDATE users SET household_role='member' WHERE id='member2'"}[damage]
    if damage == 'missing-household':
        altered = copy.deepcopy(reference)
        uid = next(u for u in altered['households'] if u != 'default')
        del altered['households'][uid]; del altered['usersProjection'][uid]
    else:
        with closing(sqlite3.connect(target)) as con:
            con.execute(sql); con.commit()
        altered = migration.snapshot(root)
    with pytest.raises(RuntimeError): migration.verify_addition(before, altered, schema)
    with pytest.raises(RuntimeError): migration.verify_restore(reference, altered, schema)


@pytest.mark.parametrize('damage', ['full-fingerprint','projection','missing-db','sidecar','content-with-new-hash'])
def test_backup_validates_full_immutable_fingerprint_and_extra_projection(group, damage):
    root, before, backup, schema, _ = group
    # Test the more demanding post-migration profile, including a member role.
    migration.migrate(root, before, backup, schema)
    reference = migration.snapshot(root); complete = backup_all(root)
    manifest_path = root/'backups'/complete['manifest']
    manifest = json.loads(manifest_path.read_text())
    entry = next(x for x in manifest['snapshots'] if x['path'].startswith('backups/household-'))
    if damage == 'full-fingerprint': reference['households']['default']['tables']['users']['rowsSha256'] = '0'*64
    elif damage == 'projection': reference['usersProjection']['default']['rowsSha256'] = '0'*64
    elif damage == 'missing-db': manifest['snapshots'].pop()
    elif damage == 'sidecar': Path(str(root/entry['path'])+'-wal').write_bytes(b'synthetic')
    else:
        path = root/entry['path']
        with closing(sqlite3.connect(path)) as con:
            con.execute("UPDATE users SET password='backup-changed' WHERE id='member1'"); con.commit()
        entry['sha256'] = migration.media.legacy.file_digest(path); entry['bytes'] = path.stat().st_size
    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(RuntimeError): migration.validate_backup(root, reference, complete)


@pytest.mark.parametrize('damage', ['sql','origin','column','constraint'])
def test_schema_contract_and_profile_reject_equal_table_count_drift(group, monkeypatch, damage):
    root, before, backup, schema, _ = group
    if damage == 'sql':
        monkeypatch.setattr(household_members, 'HOUSEHOLD_ROLE_COLUMN_SQL', schema['sql']+'; DROP TABLE users;')
        with pytest.raises(RuntimeError, match='unexpected_role_column_sql'): migration.schema_definition()
    elif damage == 'origin':
        monkeypatch.setattr(household_members, '__file__', str(ROOT/'app.py'))
        with pytest.raises(RuntimeError, match='schema_module_origin'): migration.schema_definition()
    else:
        sql = "ALTER TABLE users ADD COLUMN household_role TEXT NOT NULL DEFAULT 'member'"
        if damage == 'column': sql = sql.replace('TEXT', 'BLOB')
        with closing(sqlite3.connect(root/'household.sqlite3')) as con:
            con.execute(sql); con.execute("UPDATE users SET household_role='admin'"); con.commit()
        current = migration.snapshot(root)
        assert len([n for n in current['households']['default']['tables'] if not n.startswith('sqlite_')]) == 58
        with pytest.raises(RuntimeError): migration.verify_current(current, schema)


def test_cli_all_profiles_and_exclusive_output(group, tmp_path):
    root, _, backup, _, _ = group
    backup_path = tmp_path/'backup.json'; backup_path.write_text(json.dumps(backup), encoding='utf-8')
    def run(action, output, *args, success=True):
        script = ROOT/'deploy/check_household_members_migration.py'
        command = [sys.executable,'-B','-X','utf8',str(script)]
        result = subprocess.run(command+[action,'--data-root',str(root),'--output',str(output),*map(str,args)],
            cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=30)
        assert (result.returncode == 0) == success, result.stderr
        if success: assert json.loads(result.stdout)['verified']
    before = tmp_path/'before.json'; run('snapshot',before)
    run('validate-backup',tmp_path/'backup-proof.json','--before',before,'--backup',backup_path)
    run('check-rollback',tmp_path/'same-old.json','--before',before)
    run('migrate',tmp_path/'migration.json','--before',before,'--backup',backup_path)
    current = tmp_path/'current.json'; run('snapshot-current',current)
    run('check',tmp_path/'check.json','--before',before)
    run('check-restored',tmp_path/'restored.json','--before',current)
    original = current.read_bytes(); run('snapshot-current',current,success=False)
    assert current.read_bytes() == original
    invalid = tmp_path/'not-rollback.json'
    run('check-rollback',invalid,'--before',before,success=False)
    assert not invalid.exists()
