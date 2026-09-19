"""Real synthetic two-household 66/9 -> 69/9 migration and complete restores."""
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import sys

import pytest
from deploy import check_journey_routes_migration as data
from deploy import build_journey_routes_release as profile
import test_assistant_trip_change_release_data as prior
from deploy import membership_release_data as shared
from deploy.backup import backup_all
from deploy.rehearse_restore import documented_programs
from test_membership_migration import clone_databases, startup

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def baseline66(tmp_path_factory):
    # Reuse the populated five-analysis-table seed, from the exact installed FQ commit.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(prior, 'profile', profile)
        return prior.baseline66.__wrapped__(tmp_path_factory)


@pytest.fixture(scope='module')
def source(tmp_path_factory):
    path = tmp_path_factory.mktemp('analysis-source')
    hashes = {}
    for p in ROOT.glob('*.py'):
        raw = p.read_bytes(); (path / p.name).write_bytes(raw)
        hashes[p.name] = shared.migration.file_digest(p)
    return path, {'head': 'a' * 40, 'tree': 'b' * 40, 'imageId': 'sha256:' + '0' * 64,
                  'sourceHashes': hashes, 'runtimeHashes': hashes}


@pytest.fixture
def group(baseline66, tmp_path, source):
    root = tmp_path / 'live'; clone_databases(baseline66, root)
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
    assert all(c['originalTablesPreserved'] == 66 and c['newTables'] == 3 for c in migrated['comparisons'].values())
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
    ('default', "INSERT INTO journey_routes VALUES('synthetic','member1','synthetic',NULL,'private',1,'now','now',NULL)"),
])
def test_any_old_data_or_new_table_drift_rejected_after_startup(group, target, sql):
    root, proof, kwargs = group
    data.begin(root, proof, **kwargs); data.migrate(root, proof, **kwargs)
    path = root / ('platform.sqlite3' if target == 'platform' else 'household.sqlite3')
    if target == 'child': path = next((root / 'spaces').rglob('household.sqlite3'))
    edit(path, sql)
    with pytest.raises(shared.ReleaseDataError):
        data.check_stopped(root, proof, **kwargs)
    assert not (proof / 'result.json').exists()


@pytest.mark.parametrize('fault', ['schema-hash', 'marker', 'backup-omitted', 'old-row', 'plan'])
def test_failed_preflight_never_creates_migration_attempt(group, fault):
    root, proof, kwargs = group
    data.begin(root, proof, **kwargs)
    if fault == 'schema-hash':
        kwargs = dict(kwargs, source_identity={**kwargs['source_identity'], 'sourceHashes': {'bad': '0' * 64}})
    elif fault == 'marker':
        (root / shared.ROOT_ATTEMPT).write_bytes(b'changed')
    elif fault == 'backup-omitted':
        next((proof / 'backup-group/spaces').rglob('*.sqlite3')).unlink()
    elif fault == 'old-row':
        edit(root / 'household.sqlite3', "UPDATE private_finance SET data='{}'")
    else:
        kwargs = dict(kwargs, plan_sha256='b' * 64)
    with pytest.raises((shared.ReleaseDataError, shared.migration.MigrationCheckError)):
        data.migrate(root, proof, **kwargs)
    assert not (proof / 'migration-attempt.json').exists()


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
        exec(compile(restore, '<synthetic-analysis-restore>', 'exec'), {'__name__': '__main__'})
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
    receipt = json.loads((proof / 'backup.json').read_bytes())
    restored = tmp_path / 'rollback'
    documented_restore(proof / 'backup-group', receipt['manifest'], restored,
                       (root / shared.ROOT_ATTEMPT).read_bytes(), monkeypatch)
    assert data.verify_rollback(proof, restored)['completeGroupRestored']


def test_populated_69_group_keeps_routes_and_operation_receipts_on_actual_restart_and_restore(group, source, tmp_path, monkeypatch):
    root, proof, kwargs = group
    data.begin(root, proof, **kwargs); data.migrate(root, proof, **kwargs)
    data.check_stopped(root, proof, **kwargs)
    for path in root.rglob('household.sqlite3'):
        if 'backups' in path.parts: continue
        prior.execute(path, """
          PRAGMA foreign_keys=ON;
          INSERT INTO journey_routes VALUES('aaaaaaaaaaaaaaaaaaaaaaaa','member1','Synthetic',NULL,'private',2,'now','now',NULL);
          INSERT INTO journey_route_stops VALUES('aaaaaaaaaaaaaaaaaaaaaaaa',0,NULL);
          INSERT INTO journey_routes VALUES('bbbbbbbbbbbbbbbbbbbbbbbb','member1','Synthetic deleted',NULL,'private',3,'now','now','now');
          INSERT INTO journey_route_operations VALUES('member1','synthetic-create','digest','create','aaaaaaaaaaaaaaaaaaaaaaaa',1,'now');
          INSERT INTO journey_route_operations VALUES('member1','synthetic-delete','digest','delete','bbbbbbbbbbbbbbbbbbbbbbbb',3,'now');
        """)
    reference = data.snapshot_current(root)
    for path in root.rglob('household.sqlite3'):
        if 'backups' not in path.parts:
            data.initialize_database(path, data.schema_definition())
    assert startup(source[0], root, 'restart')['households'] == 2
    assert shared._logical(data.snapshot_current(root)) == shared._logical(reference)
    replay = tmp_path / 'new-proof'; replay.mkdir()
    with pytest.raises(shared.ReleaseDataError): data.begin(root, replay, **kwargs)
    assert not (replay / 'attempt.json').exists()
    receipt = backup_all(root)
    restored = tmp_path / 'restored69'
    documented_restore(root, receipt['manifest'], restored, (root / shared.ROOT_ATTEMPT).read_bytes(), monkeypatch)
    result = data.verify_restore(reference, restored, marker_sha256=kwargs['marker_sha256'])
    assert result['completeGroupRestored'] and result['databases'] == 3
    child = next((restored / 'spaces').rglob('household.sqlite3'))
    edit(child, "DELETE FROM journey_route_operations WHERE request_id='synthetic-delete'")
    with pytest.raises(shared.ReleaseDataError, match='restored_group_changed'):
        data.verify_restore(reference, restored, marker_sha256=kwargs['marker_sha256'])


def test_actual_initializer_partial_ddl_failure_rolls_back_one_database(group, monkeypatch):
    root, _, _ = group
    path = root / 'household.sqlite3'; before = shared.migration._read(path)
    schema = data.schema_definition(); module = data.route_module()
    original = module.initialize_journey_routes
    def fail(con):
        original(con)
        raise RuntimeError('synthetic_initializer_failure')
    monkeypatch.setattr(module, 'initialize_journey_routes', fail)
    with pytest.raises(RuntimeError, match='synthetic_initializer_failure'):
        data.initialize_database(path, schema)
    assert shared.migration._read(path) == before


def test_baseline_reader_refuses_foreign_new_schema_before_backup(group):
    root, proof, kwargs = group
    edit(root / 'household.sqlite3', 'CREATE TABLE journey_routes(id TEXT)')
    with pytest.raises(shared.ReleaseDataError): data.begin(root, proof, **kwargs)
    assert not (proof / 'attempt.json').exists()
