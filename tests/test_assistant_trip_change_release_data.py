"""Real populated two-household 66/9 preservation and restore; no network."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3

import pytest

from deploy import assistant_trip_change_release_data as data
from deploy import assistant_trip_change_release_profile as profile
from deploy import membership_release_data as shared
from test_membership_migration import materialize, startup, clone_databases
from test_finance_analysis_release_data import documented_restore

ROOT = Path(__file__).resolve().parents[1]


def execute(path, sql):
    with closing(sqlite3.connect(path)) as con:
        con.executescript(sql)
        con.commit()


@pytest.fixture(scope='module')
def baseline66(tmp_path_factory):
    base = tmp_path_factory.mktemp('assistant-release-baseline66')
    source = base / 'old-source'
    materialize(source, profile.INSTALLED_SOURCE)
    assert startup(source, base / 'seed', 'seed')['households'] == 2
    clone_databases(base / 'seed', base / 'closed66')
    for path in (base / 'closed66').rglob('household.sqlite3'):
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
        """)
    return base / 'closed66'


@pytest.fixture(scope='module')
def candidate(tmp_path_factory):
    source = tmp_path_factory.mktemp('assistant-release-candidate')
    hashes = {}
    for path in ROOT.glob('*.py'):
        raw = path.read_bytes()
        (source / path.name).write_bytes(raw)
        hashes[path.name] = shared.migration.file_digest(path)
    return source, {'head': 'a' * 40, 'tree': 'b' * 40, 'imageId': 'sha256:' + 'c' * 64,
                    'sourceHashes': hashes, 'runtimeHashes': hashes}


@pytest.fixture
def group(baseline66, candidate, tmp_path):
    root = tmp_path / 'live'
    clone_databases(baseline66, root)
    (root / shared.ROOT_ATTEMPT).write_bytes(b'{"syntheticSuccessfulAttempt":true}\n')
    proof = tmp_path / 'proof'
    proof.mkdir()
    kwargs = {'source_identity': candidate[1], 'plan_sha256': 'a' * 64,
              'marker_sha256': data.marker_digest(root)}
    return root, proof, kwargs


def test_populated_two_households_survive_actual_candidate_startup(group, candidate):
    root, proof, kwargs = group
    before = data.begin(root, proof, **kwargs)
    assert before['databases'] == 3 and before['households'] == 2
    assert startup(candidate[0], root, 'restart')['households'] == 2
    after = data.check_stopped(root, proof, **kwargs)
    assert after['logicalSha256'] == before['logicalSha256']
    assert len(list((proof / 'backup-group').rglob('*.sqlite3'))) == 3
    snap = json.loads((proof / 'before.json').read_bytes())
    for name, fingerprint in snap['databases'].items():
        if name != 'platform.sqlite3':
            for table in data.analysis.migration.NEW_TABLES:
                assert fingerprint['tables'][table]['count'] == 1
    assert data.marker_digest(root) == kwargs['marker_sha256']
    assert not (proof / 'migration-attempt.json').exists()
    originals = {p.name: p.read_bytes() for p in proof.glob('*.json')}
    with pytest.raises(FileExistsError):
        data.begin(root, proof, **kwargs)
    with pytest.raises(FileExistsError):
        data.check_stopped(root, proof, **kwargs)
    assert {p.name: p.read_bytes() for p in proof.glob('*.json')} == originals


@pytest.mark.parametrize('target,sql', [
    ('default', "UPDATE private_finance SET data='{}'"),
    ('child', "UPDATE sqlite_sequence SET seq=seq+1 WHERE name='audit'"),
    ('child', 'CREATE INDEX unexpected ON users(name)'),
    ('child', 'ALTER TABLE users ADD COLUMN unexpected TEXT'),
    ('platform', "UPDATE households SET name='changed' WHERE id='default'"),
    ('platform', 'PRAGMA user_version=2'),
    ('default', 'UPDATE finance_account_profiles SET revision=2'),
    ('child', 'UPDATE finance_account_cashflows SET amount_cents=54321'),
    ('child', "UPDATE finance_account_reviews SET context_digest='changed'"),
    ('child', 'DELETE FROM finance_analysis_operations'),
    ('default', "UPDATE finance_fx_rates SET units_per_eur='2'"),
    ('default', 'DROP TABLE finance_fx_rates'),
])
def test_any_old_or_finance_analysis_data_and_schema_drift_rejected(group, target, sql):
    root, proof, kwargs = group
    data.begin(root, proof, **kwargs)
    path = root / ('platform.sqlite3' if target == 'platform' else 'household.sqlite3')
    if target == 'child':
        path = next((root / 'spaces').glob('*/household.sqlite3'))
    execute(path, sql)
    with pytest.raises(shared.ReleaseDataError):
        data.check_stopped(root, proof, **kwargs)
    assert not (proof / 'result.json').exists()


@pytest.mark.parametrize('fault', ['marker', 'omitted-household', 'backup-bytes', 'plan', 'identity', 'manifest-path'])
def test_bound_proof_failures_are_retained_without_result(group, fault):
    root, proof, kwargs = group
    data.begin(root, proof, **kwargs)
    if fault == 'marker':
        (root / shared.ROOT_ATTEMPT).write_bytes(b'changed')
    elif fault == 'omitted-household':
        next((proof / 'backup-group/spaces').rglob('*.sqlite3')).unlink()
    elif fault == 'backup-bytes':
        execute(next((proof / 'backup-group/spaces').rglob('*.sqlite3')), 'DELETE FROM finance_analysis_operations')
    elif fault == 'plan':
        kwargs = dict(kwargs, plan_sha256='b' * 64)
    elif fault == 'identity':
        kwargs = dict(kwargs, source_identity={**kwargs['source_identity'], 'head': 'b' * 40})
    else:
        receipt = proof / 'backup.json'
        value = json.loads(receipt.read_bytes())
        value['manifest'] = '../before.json'
        receipt.write_text(json.dumps(value))
    with pytest.raises((shared.ReleaseDataError, shared.migration.MigrationCheckError)):
        data.check_stopped(root, proof, **kwargs)
    assert (proof / 'attempt.json').exists() and not (proof / 'result.json').exists()


def test_61_table_baseline_refused_before_backup_or_attempt(group):
    root, proof, kwargs = group
    for path in [root / 'household.sqlite3', *list((root / 'spaces').glob('*/household.sqlite3'))]:
        execute(path, ';'.join('DROP TABLE ' + table for table in data.analysis.migration.NEW_TABLES))
    with pytest.raises(shared.ReleaseDataError, match='expected_66_table_profile'):
        data.begin(root, proof, **kwargs)
    assert not list(proof.iterdir()) and not (root / 'backups').exists()


def test_partial_backup_failure_cannot_begin_again(group, monkeypatch):
    root, proof, kwargs = group
    with monkeypatch.context() as changed:
        changed.setattr(data, 'backup_all', lambda root: (_ for _ in ()).throw(OSError('synthetic backup failure')))
        with pytest.raises(OSError, match='synthetic'):
            data.begin(root, proof, **kwargs)
    assert (proof / 'attempt.json').exists()
    with pytest.raises(FileExistsError):
        data.begin(root, proof, **kwargs)
    assert not (root / 'backups').exists()


def test_backup_closes_only_empty_wal_pairs_for_populated66_group(group):
    root, proof, kwargs = group
    for relative in shared.enumerate_databases(root):
        if relative != 'platform.sqlite3':
            execute(root / relative, 'PRAGMA journal_mode=WAL')
    result = data.begin(root, proof, **kwargs)
    finished = json.loads((proof / 'backup-finish.json').read_bytes())
    assert result['verified'] and finished['emptyWalPairsClosed'] == 2
    assert not list(root.rglob('*-wal')) and not list(root.rglob('*-shm'))


def test_nonempty_wal_is_not_checkpointed_by_backup_finisher(group, monkeypatch):
    root, proof, kwargs = group
    for relative in shared.enumerate_databases(root):
        if relative != 'platform.sqlite3':
            execute(root / relative, 'PRAGMA journal_mode=WAL')
    original = data.backup_all
    def after_backup(path):
        result = original(path)
        (path / 'household.sqlite3-wal').write_bytes(b'synthetic nonempty WAL')
        return result
    monkeypatch.setattr(data, 'backup_all', after_backup)
    with pytest.raises(shared.ReleaseDataError, match='backup_sidecar_not_empty_pair'):
        data.begin(root, proof, **kwargs)
    assert (root / 'household.sqlite3-wal').read_bytes() == b'synthetic nonempty WAL'
    assert (proof / 'attempt.json').exists() and not (proof / 'backup-finish.json').exists()


def test_complete_retained66_group_restore_reuses_current_reader(group, tmp_path, monkeypatch):
    root, proof, kwargs = group
    before = data.begin(root, proof, **kwargs)
    reference = data.snapshot_current(root)
    receipt = json.loads((proof / 'backup.json').read_bytes())
    restored = tmp_path / 'restored66'
    documented_restore(proof / 'backup-group', receipt['manifest'], restored,
                       (root / shared.ROOT_ATTEMPT).read_bytes(), monkeypatch)
    result = data.verify_restore(reference, restored, marker_sha256=kwargs['marker_sha256'])
    assert result['completeGroupRestored'] and result['logicalSha256'] == before['logicalSha256']
    execute(restored / 'household.sqlite3', 'DELETE FROM finance_analysis_operations')
    with pytest.raises(shared.ReleaseDataError, match='restored_group_changed'):
        data.verify_restore(reference, restored, marker_sha256=kwargs['marker_sha256'])
