"""Real synthetic two-household 69/9 -> 71/9 migration and complete restores."""
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import sys

import pytest
from deploy import check_task_reminders_migration as data
from deploy import assistant_trip_items_release_profile as profile
import test_assistant_trip_items_release_data as prior
from test_assistant_trip_change_release_data import execute
from deploy.git_blobs import read_git_blobs
from deploy import membership_release_data as shared
from deploy.backup import backup_all
from deploy.rehearse_restore import documented_programs
from test_membership_migration import clone_databases, startup

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def baseline69(tmp_path_factory):
    # Historical 69/9 source, synthetic private data, analysis and route receipts.
    root = prior.baseline69.__wrapped__(tmp_path_factory)
    source = root.parent / 'installed-source'
    names = sorted(p.name for p in source.glob('*.py'))
    blobs = read_git_blobs(ROOT, profile.INSTALLED_SOURCE, names)
    assert all((source / n).read_bytes() == raw for n, raw in blobs.items())
    identity = {'sourceHead': profile.INSTALLED_SOURCE,
                'sourceHashes': {n: shared.migration.file_digest(source / n) for n in names},
                'snapshot': data.baseline.snapshot_current(root)}
    (root.parent / 'baseline69-identity.json').write_text(json.dumps(identity, indent=2), encoding='utf-8')
    return root


@pytest.fixture(scope='module')
def source(tmp_path_factory):
    path = tmp_path_factory.mktemp('reminder-source')
    hashes = {}
    for p in ROOT.glob('*.py'):
        raw = p.read_bytes(); (path / p.name).write_bytes(raw)
        hashes[p.name] = shared.migration.file_digest(p)
    return path, {'head': 'a' * 40, 'tree': 'b' * 40, 'imageId': 'sha256:' + '0' * 64,
                  'sourceHashes': hashes, 'runtimeHashes': hashes}


@pytest.fixture
def group(baseline69, tmp_path, source):
    root = tmp_path / 'live'; clone_databases(baseline69, root)
    (root / shared.ROOT_ATTEMPT).write_bytes(b'{"syntheticSuccessfulAttempt":true}\n')
    proof = tmp_path / 'proof'; proof.mkdir()
    kwargs = {'source_identity': source[1], 'plan_sha256': 'a' * 64, 'marker_sha256': data.marker_digest(root)}
    return root, proof, kwargs


def edit(path, sql):
    with closing(sqlite3.connect(path)) as con:
        con.execute(sql); con.commit()


def test_two_household_exact_addition_real_startup_and_marker(group, source):
    root, proof, kwargs = group
    before = data.begin(root, proof, **kwargs)
    migrated = data.migrate(root, proof, **kwargs)
    assert before['databases'] == migrated['databases'] == 3 and migrated['households'] == 2
    assert all(c['originalTablesPreserved'] == 69 and c['newTables'] == 2 for c in migrated['comparisons'].values())
    assert startup(source[0], root, 'restart')['households'] == 2
    after = data.check_stopped(root, proof, **kwargs)
    assert after['logicalSha256'] == migrated['logicalSha256']
    assert data.marker_digest(root) == kwargs['marker_sha256']
    assert len(list((proof / 'backup-group').rglob('*.sqlite3'))) == 3
    with pytest.raises((shared.ReleaseDataError, FileExistsError)):
        data.migrate(root, proof, **kwargs)


@pytest.mark.parametrize('target,sql', [
    ('default', "UPDATE private_finance SET data='{}'"),
    ('child', "UPDATE users SET household_role='admin' WHERE id='member2'"),
    ('child', "UPDATE sqlite_sequence SET seq=seq+1 WHERE name='audit'"),
    ('child', 'CREATE INDEX accidental ON users(name)'),
    ('default', 'ALTER TABLE users ADD COLUMN accidental TEXT'),
    ('platform', "UPDATE households SET name='changed' WHERE id='default'"),
    ('platform', 'PRAGMA user_version=2'),
    ('default', "UPDATE finance_fx_rates SET units_per_eur='2'"),
    ('default', "INSERT INTO task_reminders VALUES('member1','synthetic','2026-09-20',NULL,NULL,0,1,'now','now')"),
    ('child', "INSERT INTO task_reminder_operations VALUES('member1','synthetic','digest','{}','now')"),
    ('default', "INSERT INTO settings(id,data) VALUES('task-reminders-worker','{}')"),
    ('child', 'CREATE INDEX unexpected_reminders ON task_reminders(task_id)'),
    ('child', 'ALTER TABLE task_reminders ADD COLUMN unexpected TEXT'),
    ('default', "INSERT INTO task_reminders VALUES('missing-user','synthetic','2026-09-20',NULL,NULL,0,1,'now','now')"),
])
def test_any_old_data_or_new_table_drift_rejected_after_startup(group, target, sql):
    root, proof, kwargs = group
    data.begin(root, proof, **kwargs); data.migrate(root, proof, **kwargs)
    path = root / ('platform.sqlite3' if target == 'platform' else 'household.sqlite3')
    if target == 'child': path = next((root / 'spaces').rglob('household.sqlite3'))
    edit(path, sql)
    with pytest.raises((shared.ReleaseDataError, shared.migration.MigrationCheckError)):
        data.check_stopped(root, proof, **kwargs)
    assert not (proof / 'result.json').exists()


@pytest.mark.parametrize('fault', ['schema-hash', 'marker', 'backup-omitted', 'backup-bytes', 'old-row', 'child-row', 'plan', 'manifest-path'])
def test_failed_preflight_never_creates_migration_attempt(group, fault):
    root, proof, kwargs = group
    data.begin(root, proof, **kwargs)
    if fault == 'schema-hash':
        kwargs = dict(kwargs, source_identity={**kwargs['source_identity'], 'sourceHashes': {'bad': '0' * 64}})
    elif fault == 'marker':
        (root / shared.ROOT_ATTEMPT).write_bytes(b'changed')
    elif fault == 'backup-omitted':
        next((proof / 'backup-group/spaces').rglob('*.sqlite3')).unlink()
    elif fault == 'backup-bytes':
        path = next((proof / 'backup-group/spaces').rglob('*.sqlite3'))
        raw = bytearray(path.read_bytes()); raw[-1] ^= 1; path.write_bytes(raw)
    elif fault == 'manifest-path':
        path = proof / 'backup.json'; value = json.loads(path.read_bytes())
        value['manifest'] = '../before.json'; path.write_text(json.dumps(value))
    elif fault == 'old-row':
        edit(root / 'household.sqlite3', "UPDATE private_finance SET data='{}'")
    elif fault == 'child-row':
        edit(next((root / 'spaces').rglob('household.sqlite3')), "UPDATE private_finance SET data='{}'")
    else:
        kwargs = dict(kwargs, plan_sha256='b' * 64)
    original = shared.snapshot(root)
    with pytest.raises((shared.ReleaseDataError, shared.migration.MigrationCheckError)):
        data.migrate(root, proof, **kwargs)
    assert shared.snapshot(root) == original
    assert not (proof / 'migration-attempt.json').exists()
    assert all(not (set(shared.migration._read(root / n)['rows']) & data.NEW_TABLES)
               for n in shared.enumerate_databases(root) if n != 'platform.sqlite3')


def documented_restore(backup_root, manifest_name, destination, marker, monkeypatch):
    destination.mkdir()
    manifest = json.loads((backup_root / 'backups' / manifest_name).read_bytes())
    for relative in ['backups/' + manifest_name, *[x['path'] for x in manifest['snapshots']]]:
        target = destination / relative; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(backup_root / relative, target)
    restore, _ = documented_programs(ROOT)
    restore = restore.replace("root = Path('/data').resolve(strict=True)", 'root = Path(' + repr(str(destination)) + ').resolve(strict=True)')
    with monkeypatch.context() as invocation:
        invocation.setattr(sys, 'argv', ['documented-restore', manifest_name, 'platform', 'default'])
        exec(compile(restore, '<synthetic-reminder-restore>', 'exec'), {'__name__': '__main__'})
    (destination / shared.ROOT_ATTEMPT).write_bytes(marker)


@pytest.mark.parametrize('partial', [False, True])
def test_complete_old_group_rollback_after_full_or_partial_migration(group, tmp_path, monkeypatch, partial):
    root, proof, kwargs = group
    data.begin(root, proof, **kwargs)
    if partial:
        original = data.initialize_database
        calls = []
        def initialize(path, schema):
            calls.append(path)
            if len(calls) == 2: raise RuntimeError('synthetic_second_household_failure')
            original(path, schema)
        with monkeypatch.context() as invocation:
            invocation.setattr(data, 'initialize_database', initialize)
            with pytest.raises(RuntimeError, match='synthetic_second'):
                data.migrate(root, proof, **kwargs)
        assert (proof / 'migration-attempt.json').exists() and not (proof / 'migration-result.json').exists()
        with pytest.raises(shared.ReleaseDataError): data.migrate(root, proof, **kwargs)
    else:
        data.migrate(root, proof, **kwargs)
    assert (proof / 'migration-attempt.json').exists()
    receipt = json.loads((proof / 'backup.json').read_bytes())
    restored = tmp_path / 'rollback'
    documented_restore(proof / 'backup-group', receipt['manifest'], restored,
                       (root / shared.ROOT_ATTEMPT).read_bytes(), monkeypatch)
    assert data.verify_rollback(proof, restored)['completeGroupRestored']


def test_populated_71_restart_and_complete_restore_keep_states_and_receipts(group, source, tmp_path, monkeypatch):
    root, proof, kwargs = group
    data.begin(root, proof, **kwargs); data.migrate(root, proof, **kwargs)
    data.check_stopped(root, proof, **kwargs)
    for relative in shared.enumerate_databases(root):
        if relative == 'platform.sqlite3': continue
        execute(root / relative, """
          PRAGMA foreign_keys=ON;
          INSERT INTO task_reminders VALUES('member1','deleted-task','2026-09-20','2026-09-20T01:00:00+00:00',NULL,3,0,'now','now');
          INSERT INTO task_reminders VALUES('member2','active-task','2026-09-21',NULL,'2026-09-21T01:00:00+00:00',4,1,'now','now');
          INSERT INTO task_reminder_operations VALUES('member1','historical-read','digest','{"revision":3}','now');
          INSERT INTO task_reminder_operations VALUES('member2','historical-snooze','digest','{"revision":4}','now');
        """)
    reference = data.snapshot_current(root)
    assert startup(source[0], root, 'restart')['households'] == 2
    assert shared._logical(data.snapshot_current(root)) == shared._logical(reference)
    for name, value in reference['databases'].items():
        if name != 'platform.sqlite3':
            assert len([n for n in value['tables'] if not n.startswith('sqlite_')]) == 71
            assert all(value['tables'][t]['count'] == 2 for t in data.NEW_TABLES)
    replay = tmp_path / 'new-proof'; replay.mkdir()
    with pytest.raises(shared.ReleaseDataError): data.begin(root, replay, **kwargs)
    assert not (replay / 'attempt.json').exists()
    receipt = backup_all(root)
    restored = tmp_path / 'restored71'
    documented_restore(root, receipt['manifest'], restored, (root / shared.ROOT_ATTEMPT).read_bytes(), monkeypatch)
    result = data.verify_restore(reference, restored, marker_sha256=kwargs['marker_sha256'])
    assert result['completeGroupRestored'] and result['databases'] == 3
    child = next((restored / 'spaces').rglob('household.sqlite3'))
    edit(child, "DELETE FROM task_reminder_operations WHERE request_id='historical-read'")
    with pytest.raises(shared.ReleaseDataError, match='restored_group_changed'):
        data.verify_restore(reference, restored, marker_sha256=kwargs['marker_sha256'])


def test_actual_initializer_partial_ddl_failure_rolls_back_one_database(group, monkeypatch):
    root, _, _ = group
    path = root / 'household.sqlite3'; before = shared.migration._read(path)
    schema = data.schema_definition()
    def fail(con, sql):
        con.execute(sql.split(';')[0])
        raise RuntimeError('synthetic_initializer_failure')
    monkeypatch.setattr(data, '_execute_schema', fail)
    with pytest.raises(RuntimeError, match='synthetic_initializer_failure'):
        data.initialize_database(path, schema)
    assert shared.migration._read(path) == before


def test_baseline_reader_refuses_foreign_new_schema_before_backup(group):
    root, proof, kwargs = group
    edit(root / 'household.sqlite3', 'CREATE TABLE task_reminders(id TEXT)')
    with pytest.raises(shared.ReleaseDataError): data.begin(root, proof, **kwargs)
    assert not (proof / 'attempt.json').exists()


@pytest.mark.parametrize('fault', ['sql', 'import-path', 'source-identity'])
def test_schema_constant_import_and_runtime_source_are_closed(group, monkeypatch, fault):
    root, proof, kwargs = group
    data.begin(root, proof, **kwargs)
    if fault == 'sql':
        module = data.reminder_module()
        monkeypatch.setattr(module, 'SCHEMA_SQL', module.SCHEMA_SQL + 'CREATE TABLE extra(id TEXT);')
    elif fault == 'import-path':
        monkeypatch.setattr(data.reminder_module(), '__file__', str(ROOT / 'app.py'))
    else:
        # Make attempt internally consistent with an unreviewed schema source;
        # actual module binding must still fail before any database write.
        identity = dict(kwargs['source_identity'], runtimeHashes={**kwargs['source_identity']['runtimeHashes'], 'task_reminders.py': '0' * 64})
        kwargs = dict(kwargs, source_identity=identity)
        path = proof / 'attempt.json'; value = json.loads(path.read_bytes())
        value['sourceIdentity'] = identity; value['sourceIdentitySha256'] = shared._digest(identity)
        path.write_text(json.dumps(value))
    original = shared.snapshot(root)
    with pytest.raises(shared.ReleaseDataError): data.migrate(root, proof, **kwargs)
    assert shared.snapshot(root) == original
    assert not (proof / 'migration-attempt.json').exists()


def test_unregistered_household_is_rejected_before_attempt(group):
    root, proof, kwargs = group
    rogue = root / 'spaces' / ('f' * 24); rogue.mkdir()
    shutil.copyfile(root / 'household.sqlite3', rogue / 'household.sqlite3')
    with pytest.raises(shared.ReleaseDataError, match='unregistered_household_database'):
        data.begin(root, proof, **kwargs)
    assert not list(proof.iterdir())


def test_nonempty_wal_is_rejected_without_checkpoint_or_attempt(group):
    root, proof, kwargs = group
    path = root / 'household.sqlite3'
    with closing(sqlite3.connect(path)) as con:
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('PRAGMA wal_autocheckpoint=0')
        con.execute("UPDATE private_finance SET data='{}'"); con.commit()
        wal = Path(str(path) + '-wal')
        assert wal.stat().st_size > 0
        hashes = (shared.migration.file_digest(path), shared.migration.file_digest(wal))
        with pytest.raises(shared.migration.MigrationCheckError): data.begin(root, proof, **kwargs)
        assert (shared.migration.file_digest(path), shared.migration.file_digest(wal)) == hashes
        assert not list(proof.iterdir()) and not (root / 'backups').exists()
