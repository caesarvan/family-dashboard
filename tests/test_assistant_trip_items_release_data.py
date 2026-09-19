"""Real synthetic populated 69/9 and unchanged default 66/9 closed-group proofs."""
from dataclasses import FrozenInstanceError
import json
from pathlib import Path

import pytest
from deploy import assistant_trip_items_release_data as data
from deploy import assistant_trip_items_release_profile as profile
from deploy import assistant_trip_change_release_data as old
from deploy import membership_release_data as common
from test_membership_migration import materialize, startup, clone_databases
from test_assistant_trip_change_release_data import baseline66, execute
from test_finance_analysis_release_data import documented_restore

ROOT = Path(__file__).resolve().parents[1]
IDENTITY = {'head': 'a' * 40, 'tree': 'b' * 40, 'imageId': 'sha256:' + 'c' * 64,
            'sourceHashes': {'app.py': 'd' * 64}, 'runtimeHashes': {'app.py': 'd' * 64}}


@pytest.fixture(scope='module')
def baseline69(tmp_path_factory):
    base = tmp_path_factory.mktemp('trip-items-69')
    source = base / 'installed-source'
    materialize(source, profile.INSTALLED_SOURCE)
    assert startup(source, base / 'seed', 'seed')['households'] == 2
    root = base / 'closed69'
    clone_databases(base / 'seed', root)
    for path in root.rglob('household.sqlite3'):
        execute(path, """
          PRAGMA foreign_keys=ON;
          INSERT INTO finance_accounts VALUES('synthetic-account','member1','Synthetic','Synthetic',
            'asset','CNY','',0,1,'2026-09-19','2026-09-19');
          INSERT INTO finance_account_profiles VALUES('member1','synthetic-account','cash','immediate',1,'now');
          INSERT INTO finance_account_cashflows VALUES('synthetic-flow','member1','synthetic-account',
            '2026-09-18','in',12345,'synthetic',1,'now','now');
          INSERT INTO finance_account_reviews VALUES('member1','synthetic-account','2026-09-01',
            '2026-09-18','digest',1,'now');
          INSERT INTO finance_analysis_operations VALUES('member1','synthetic-request','digest',
            'cashflow','synthetic-account','{}','now');
          INSERT INTO finance_fx_rates VALUES('synthetic-version','2026-09-18','USD','1.2',
            'https://example.invalid/synthetic','digest','now','now');
          INSERT INTO journey_routes VALUES('active','member1','Synthetic',NULL,'private',1,'now','now',NULL);
          INSERT INTO journey_routes VALUES('deleted','member1','Deleted',NULL,'shared',2,'now','now','now');
          INSERT INTO journey_route_stops VALUES('active',0,NULL);
          INSERT INTO journey_route_stops VALUES('deleted',0,NULL);
          INSERT INTO journey_route_operations VALUES('member1','create-active','digest','create','active',1,'now');
          INSERT INTO journey_route_operations VALUES('member1','delete-route','digest','delete','deleted',2,'now');
        """)
    return root


def make_group(baseline, tmp_path):
    root = tmp_path / 'live'
    clone_databases(baseline, root)
    (root / common.ROOT_ATTEMPT).write_bytes(b'{"syntheticSuccessfulAttempt":true}\n')
    proof = tmp_path / 'proof'; proof.mkdir()
    return root, proof, {'source_identity': IDENTITY, 'plan_sha256': 'a' * 64,
                         'marker_sha256': data.marker_digest(root)}


@pytest.fixture
def group(baseline69, tmp_path):
    return make_group(baseline69, tmp_path)


def closed_cycle(adapter, group, source, tmp_path, monkeypatch, count):
    root, proof, kwargs = group
    before = adapter.begin(root, proof, **kwargs)
    assert before['databases'] == 3 and before['households'] == 2
    assert startup(source, root, 'restart')['households'] == 2
    result = adapter.check_stopped(root, proof, **kwargs)
    assert result['logicalSha256'] == before['logicalSha256']
    reference = adapter.snapshot_current(root)
    for name, db in reference['databases'].items():
        assert len([n for n in db['tables'] if not n.startswith('sqlite_')]) == (9 if name == 'platform.sqlite3' else count)
    receipt = json.loads((proof / 'backup.json').read_bytes())
    restored = tmp_path / 'restored'
    documented_restore(proof / 'backup-group', receipt['manifest'], restored,
                       (root / common.ROOT_ATTEMPT).read_bytes(), monkeypatch)
    restored_result = adapter.verify_restore(reference, restored, marker_sha256=kwargs['marker_sha256'])
    assert restored_result['completeGroupRestored'] and restored_result['logicalSha256'] == before['logicalSha256']
    originals = {p.name: p.read_bytes() for p in proof.glob('*.json')}
    with pytest.raises(FileExistsError): adapter.begin(root, proof, **kwargs)
    with pytest.raises(FileExistsError): adapter.check_stopped(root, proof, **kwargs)
    assert originals == {p.name: p.read_bytes() for p in proof.glob('*.json')}
    assert not (proof / 'migration-attempt.json').exists()
    return reference, restored


def test_populated69_real_startup_tombstones_receipts_full_restore(group, tmp_path, monkeypatch):
    reference, restored = closed_cycle(data, group, ROOT, tmp_path, monkeypatch, 69)
    for name, db in reference['databases'].items():
        if name != 'platform.sqlite3':
            assert all(db['tables'][t]['count'] == 2 for t in data.routes.NEW_TABLES)
            assert all(db['tables'][t]['count'] == 1 for t in old.analysis.migration.NEW_TABLES)
    execute(restored / 'household.sqlite3', "DELETE FROM journey_route_operations WHERE request_id='delete-route'")
    with pytest.raises(common.ReleaseDataError):
        data.verify_restore(reference, restored, marker_sha256=group[2]['marker_sha256'])


def test_default66_real_startup_and_full_restore_unchanged(baseline66, tmp_path, monkeypatch):
    closed_cycle(old, make_group(baseline66, tmp_path), baseline66.parent / 'old-source', tmp_path, monkeypatch, 66)
    assert old.SPEC.snapshot is old.analysis.snapshot_current
    assert old.SPEC.attempt_kind == 'assistant-trip-change-release-attempt'


@pytest.mark.parametrize('adapter_name', ['old66', 'new69'])
def test_profiles_cannot_reinterpret_each_other(adapter_name, group, baseline66, tmp_path):
    adapter = old if adapter_name == 'old66' else data
    if adapter_name == 'new69':
        other = tmp_path / 'other'; other.mkdir()
        root, proof, kwargs = make_group(baseline66, other)
    else:
        root, proof, kwargs = group
    with pytest.raises(common.ReleaseDataError): adapter.begin(root, proof, **kwargs)
    assert not list(proof.iterdir()) and not (root / 'backups').exists()
    with pytest.raises(FrozenInstanceError): adapter.SPEC.attempt_kind = 'other'


@pytest.mark.parametrize('target,sql', [
    ('default', "UPDATE journey_routes SET deleted_at=NULL WHERE id='deleted'"),
    ('child', "DELETE FROM journey_route_operations WHERE request_id='delete-route'"),
    ('child', 'DELETE FROM journey_route_stops'),
    ('child', 'CREATE INDEX unreviewed ON journey_routes(title)'),
    ('default', 'ALTER TABLE journey_route_stops ADD COLUMN unreviewed TEXT'),
    ('default', "UPDATE journey_route_stops SET place_id='missing'"),
    ('child', "UPDATE sqlite_sequence SET seq=seq+1 WHERE name='audit'"),
    ('default', "UPDATE finance_fx_rates SET units_per_eur='2'"),
    ('platform', "UPDATE households SET name='changed' WHERE id='default'"),
])
def test_group_row_schema_fk_sequence_drift_is_rejected(group, target, sql):
    root, proof, kwargs = group
    data.begin(root, proof, **kwargs)
    path = root / ('platform.sqlite3' if target == 'platform' else 'household.sqlite3')
    if target == 'child': path = next((root / 'spaces').glob('*/household.sqlite3'))
    execute(path, sql)
    with pytest.raises((common.ReleaseDataError, common.migration.MigrationCheckError)):
        data.check_stopped(root, proof, **kwargs)
    assert (proof / 'attempt.json').exists() and not (proof / 'result.json').exists()


@pytest.mark.parametrize('fault', ['marker', 'missing-backup', 'backup-bytes', 'plan', 'identity', 'manifest-path'])
def test_immutable_group_receipt_binding(group, fault):
    root, proof, kwargs = group
    data.begin(root, proof, **kwargs)
    if fault == 'marker': (root / common.ROOT_ATTEMPT).write_bytes(b'changed')
    elif fault == 'missing-backup': next((proof / 'backup-group/spaces').rglob('*.sqlite3')).unlink()
    elif fault == 'backup-bytes': execute(next((proof / 'backup-group/spaces').rglob('*.sqlite3')), 'DELETE FROM journey_route_operations')
    elif fault == 'plan': kwargs = dict(kwargs, plan_sha256='b' * 64)
    elif fault == 'identity': kwargs = dict(kwargs, source_identity={**IDENTITY, 'head': 'b' * 40})
    else:
        path = proof / 'backup.json'; record = json.loads(path.read_bytes())
        record['manifest'] = '../before.json'; path.write_text(json.dumps(record))
    with pytest.raises((common.ReleaseDataError, common.migration.MigrationCheckError)):
        data.check_stopped(root, proof, **kwargs)
    assert not (proof / 'result.json').exists()


def test_new_spec_threads_through_empty_wal_backup_and_partial_failure(group, monkeypatch):
    root, proof, kwargs = group
    for path in root.rglob('household.sqlite3'): execute(path, 'PRAGMA journal_mode=WAL')
    data.begin(root, proof, **kwargs)
    finish = json.loads((proof / 'backup-finish.json').read_bytes())
    assert finish['emptyWalPairsClosed'] == 2
    data.check_stopped(root, proof, **kwargs)
    failed = proof.parent / 'failed'; failed.mkdir()
    with monkeypatch.context() as patch:
        patch.setattr(old, 'backup_all', lambda root: (_ for _ in ()).throw(OSError('synthetic backup failure')))
        with pytest.raises(OSError, match='synthetic'): data.begin(root, failed, **kwargs)
    with pytest.raises(FileExistsError): data.begin(root, failed, **kwargs)
    assert not (failed / 'result.json').exists()
