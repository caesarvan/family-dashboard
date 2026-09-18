"""Real synthetic SQLite full-group backup/startup, drift and marker guards."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3

import pytest
from deploy import steady_release_data as steady
from deploy import membership_release_data as shared
from test_membership_migration import historical, clone_databases, materialize, startup

FIXED = 'f96eab526b7530a5ec487a778b19c197293a59da'


@pytest.fixture(scope='module')
def source(tmp_path_factory):
    path = tmp_path_factory.mktemp('steady-source') / 'source'
    hashes = materialize(path, FIXED)
    return path, {'head': FIXED, 'tree': 'b32851b2345e3345d03f0f65239e88bd71cfa0f6',
                  'imageId': 'sha256:' + '0' * 64, 'sourceHashes': hashes, 'runtimeHashes': hashes}


@pytest.fixture
def group(historical, tmp_path, source):
    root = tmp_path / 'live'
    clone_databases(historical['after'], root)
    marker = root / shared.ROOT_ATTEMPT
    marker.write_bytes(b'{"syntheticSuccessfulMembershipAttempt":true}\n')
    proof = tmp_path / 'proof'; proof.mkdir()
    kwargs = {'source_identity': source[1], 'plan_sha256': 'a' * 64, 'marker_sha256': steady.marker_digest(root)}
    return root, proof, kwargs


def edit(path, sql):
    with closing(sqlite3.connect(path)) as con:
        con.execute(sql); con.commit()


def test_real_current_group_backup_normal_startup_and_marker_preserved(group, source):
    root, proof, kwargs = group
    # Current business changes are valid: do not compare old migration rows.
    edit(root / 'household.sqlite3', "UPDATE users SET name='Current synthetic display' WHERE id='member1'")
    marker = (root / shared.ROOT_ATTEMPT).read_bytes()
    before = steady.begin(root, proof, **kwargs)
    assert before['households'] == 2 and before['databases'] == 3
    assert startup(source[0], root, 'restart')['households'] == 2
    after = steady.check_stopped(root, proof, **kwargs)
    assert after['logicalSha256'] == before['logicalSha256']
    assert (root / shared.ROOT_ATTEMPT).read_bytes() == marker
    assert len(list((proof / 'backup-group').rglob('*.sqlite3'))) == 3
    with pytest.raises(FileExistsError):
        steady.begin(root, proof, **kwargs)


@pytest.mark.parametrize('target,sql', [
    ('default', "UPDATE private_finance SET data='{}'"),
    ('child', "UPDATE users SET household_role='admin' WHERE id='member2'"),
    ('child', "UPDATE sqlite_sequence SET seq=seq+1 WHERE name='audit'"),
    ('child', 'CREATE INDEX accidental ON users(name)'),
    ('default', 'ALTER TABLE users ADD COLUMN accidental TEXT'),
    ('platform', "UPDATE households SET name='changed' WHERE id='default'"),
    ('platform', 'PRAGMA user_version=2'),
])
def test_any_database_schema_row_or_sequence_drift_is_rejected(group, target, sql):
    root, proof, kwargs = group
    steady.begin(root, proof, **kwargs)
    path = root / ('platform.sqlite3' if target == 'platform' else 'household.sqlite3')
    if target == 'child':
        path = next((root / 'spaces').rglob('household.sqlite3'))
    edit(path, sql)
    with pytest.raises(shared.ReleaseDataError):
        steady.check_stopped(root, proof, **kwargs)
    assert not (proof / 'result.json').exists()


@pytest.mark.parametrize('when,change', [('before', 'missing'), ('before', 'different'), ('after', 'different')])
def test_success_marker_must_exist_and_remain_identical(group, when, change):
    root, proof, kwargs = group
    if when == 'after':
        steady.begin(root, proof, **kwargs)
    marker = root / shared.ROOT_ATTEMPT
    if change == 'missing':
        marker.unlink()
    else:
        marker.write_bytes(b'changed')
    with pytest.raises((shared.ReleaseDataError, shared.migration.MigrationCheckError)):
        (steady.begin if when == 'before' else steady.check_stopped)(root, proof, **kwargs)
    assert not (proof / 'result.json').exists()
    assert not marker.exists() if change == 'missing' else marker.read_bytes() == b'changed'


def test_legacy_default_rejects_61_9_backup(group):
    root, proof, kwargs = group
    steady.begin(root, proof, **kwargs)
    before = json.loads((proof / 'before.json').read_bytes())
    receipt = json.loads((proof / 'backup.json').read_bytes())
    with pytest.raises(shared.ReleaseDataError, match='mixed_or_partial'):
        shared.validate_backup(root, before, proof / 'backup-group/backups' / receipt['manifest'])


@pytest.mark.parametrize('change', ['missing-child', 'backup-omitted', 'backup-row-rehashed', 'proof-plan', 'proof-before'])
def test_complete_registry_retained_backup_and_attempt_binding(group, change):
    root, proof, kwargs = group
    steady.begin(root, proof, **kwargs)
    receipt = json.loads((proof / 'backup.json').read_bytes())
    manifest = proof / 'backup-group/backups' / receipt['manifest']
    value = json.loads(manifest.read_bytes())
    if change == 'missing-child':
        next((root / 'spaces').rglob('household.sqlite3')).unlink()
    elif change == 'backup-omitted':
        value['snapshots'].pop(); manifest.write_text(json.dumps(value))
    elif change == 'backup-row-rehashed':
        entry = next(v for v in value['snapshots'] if v['path'].startswith('spaces/'))
        path = proof / 'backup-group' / entry['path']
        edit(path, "UPDATE users SET name='tampered' WHERE id='member1'")
        entry.update(sha256=shared.migration.file_digest(path), bytes=path.stat().st_size)
        manifest.write_text(json.dumps(value))
    elif change == 'proof-plan':
        kwargs = dict(kwargs, plan_sha256='b' * 64)
    else:
        path = proof / 'before.json'; record = json.loads(path.read_bytes()); record['households'] = 1
        path.write_text(json.dumps(record))
    with pytest.raises((shared.ReleaseDataError, shared.migration.MigrationCheckError)):
        steady.check_stopped(root, proof, **kwargs)
    assert not (proof / 'result.json').exists()


def test_old_58_2_profile_refused_before_backup(historical, tmp_path, source):
    root = tmp_path / 'old'; clone_databases(historical['before'], root)
    (root / shared.ROOT_ATTEMPT).write_bytes(b'synthetic marker')
    proof = tmp_path / 'proof'; proof.mkdir()
    with pytest.raises(shared.ReleaseDataError, match='mixed_or_partial'):
        steady.begin(root, proof, source_identity=source[1], plan_sha256='a' * 64,
                     marker_sha256=steady.marker_digest(root))
    assert not (proof / 'attempt.json').exists()
