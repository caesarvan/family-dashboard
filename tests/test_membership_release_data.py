"""Synthetic whole-registry backups and one real fixed-source warm callback."""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
from threading import Event

import pytest

from deploy import membership_release_data as release
from deploy import membership_migration as migration
from deploy.backup import backup_all
from test_membership_migration import historical, clone_databases, materialize, startup

FIXED = '7b5b2c3b14b5727484fa6558e4e3a21074c4435a'


@pytest.fixture(scope='module')
def frozen_source(tmp_path_factory):
    directory = tmp_path_factory.mktemp('membership-warm-source') / 'source'
    hashes = materialize(directory, FIXED)
    tree = subprocess.check_output(['git', '--no-replace-objects', 'rev-parse', FIXED + '^{tree}'], cwd=Path(__file__).resolve().parents[1]).decode().strip()
    # Synthetic image identity only: no container is built/run by this suite.
    identity = {'head': FIXED, 'tree': tree, 'imageId': 'sha256:' + '0' * 64,
                'sourceHashes': hashes, 'runtimeHashes': hashes}
    return directory, identity


@pytest.fixture
def group(historical, tmp_path):
    live = tmp_path / 'live'
    clone_databases(historical['before'], live)
    before = release.snapshot(live)
    generated = backup_all(live)
    source_manifest = live / 'backups' / generated['manifest']
    manifest = json.loads(source_manifest.read_text())
    proof = tmp_path / 'proof-group'
    for entry in manifest['snapshots']:
        target = proof / entry['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(live / entry['path'], target)
    target_manifest = proof / 'backups' / source_manifest.name
    shutil.copy2(source_manifest, target_manifest)
    return {'root': live, 'before': before, 'manifest': target_manifest,
            'proof': proof, 'attempt': tmp_path / 'attempt', 'parent': tmp_path}


def edit(path, sql):
    with closing(sqlite3.connect(path)) as con:
        con.execute(sql)
        con.commit()


def change_manifest(group, transform):
    path = group['manifest']
    value = json.loads(path.read_text())
    transform(value)
    path.write_text(json.dumps(value), encoding='utf-8')


def warm(group, frozen_source, callback=None):
    source, identity = frozen_source
    return release.warm_once(group['root'], group['before'], group['manifest'], group['attempt'],
                             source_identity=identity, warm=callback or (lambda: startup(source, group['root'], 'upgrade')))


def test_complete_group_real_warm_restart_and_no_replay(group, frozen_source):
    root = group['root']
    paths = release.enumerate_databases(root)
    assert len(paths) == 3 and paths[:2] == ('platform.sqlite3', 'household.sqlite3')
    proof = release.validate_backup(root, group['before'], group['manifest'])
    assert proof['databases'] == 3 and proof['households'] == 2
    # Simulate backup rotation; only the retained proof group remains.
    for path in root.rglob('backups'):
        if path.is_dir():
            shutil.rmtree(path)
    calls = []
    def actual():
        calls.append(1)
        assert startup(frozen_source[0], root, 'upgrade')['households'] == 2
    result = warm(group, frozen_source, actual)
    assert result['state'] == 'completed' and result['databases'] == 3 and calls == [1]
    assert set(result['comparisons']) == set(paths)
    assert result['comparisons']['household.sqlite3']['afterTableCount'] == 61
    assert result['comparisons']['platform.sqlite3']['afterTableCount'] == 9
    assert release.check_current_after(group['attempt'], root)['verified']
    assert startup(frozen_source[0], root, 'restart')['households'] == 2
    assert release.check_current_after(group['attempt'], root)['verified']
    with pytest.raises(release.ReleaseDataError, match='attempt_already_exists'):
        warm(group, frozen_source, actual)
    group['attempt'] = group['parent'] / 'different-attempt'
    with pytest.raises(release.ReleaseDataError, match='root_attempt_locked'):
        warm(group, frozen_source, actual)
    assert calls == [1]


@pytest.mark.parametrize('case', ['missing_child', 'invalid_registry', 'orphan_child', 'sidecar', 'missing_registry'])
def test_registry_enumeration_fail_closed(group, case):
    root = group['root']
    child = next(root.glob('spaces/*/household.sqlite3'))
    if case == 'missing_child':
        child.unlink()
    elif case == 'missing_registry':
        (root / 'platform.sqlite3').unlink()
    elif case == 'invalid_registry':
        edit(root / 'platform.sqlite3', "INSERT INTO households VALUES('../escape','invalid','synthetic','now')")
    elif case == 'sidecar':
        Path(str(child) + '-wal').touch()
    else:
        extra = root / 'spaces' / ('e' * 24) / 'household.sqlite3'
        extra.parent.mkdir()
        shutil.copyfile(child, extra)
    with pytest.raises((release.ReleaseDataError, migration.MigrationCheckError)):
        release.snapshot(root)


@pytest.mark.parametrize('case', ['omit', 'duplicate', 'escape', 'bytes', 'hash', 'changed_rows', 'extra_field', 'wrong_stamp'])
def test_backup_proof_is_complete_and_exact(group, case):
    if case == 'omit':
        change_manifest(group, lambda x: x['snapshots'].pop())
    elif case == 'duplicate':
        change_manifest(group, lambda x: x['snapshots'].__setitem__(1, x['snapshots'][0]))
    elif case == 'escape':
        change_manifest(group, lambda x: x['snapshots'][0].update(path='../outside.sqlite3'))
    elif case == 'bytes':
        change_manifest(group, lambda x: x['snapshots'][0].update(bytes=1))
    elif case == 'hash':
        change_manifest(group, lambda x: x['snapshots'][0].update(sha256='0' * 64))
    elif case == 'extra_field':
        change_manifest(group, lambda x: x.update(ignore=True))
    elif case == 'wrong_stamp':
        change_manifest(group, lambda x: x.update(createdAt='20260101T000000000000Z'))
    else:
        value = json.loads(group['manifest'].read_text())
        entry = next(x for x in value['snapshots'] if x['path'].startswith('backups/household-'))
        path = group['proof'] / entry['path']
        edit(path, "UPDATE users SET password='different-synthetic-hash' WHERE id='member1'")
        entry['sha256'] = migration.file_digest(path)
        entry['bytes'] = path.stat().st_size
        group['manifest'].write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises((release.ReleaseDataError, migration.MigrationCheckError)):
        release.validate_backup(group['root'], group['before'], group['manifest'])


@pytest.mark.parametrize('mode', ['no_change', 'platform_only', 'old_row_changed'])
def test_failure_is_persistent_and_replay_cannot_use_new_directory(group, frozen_source, mode):
    calls = []
    def failure():
        calls.append(1)
        if mode == 'platform_only':
            with closing(sqlite3.connect(group['root'] / 'platform.sqlite3')) as con:
                for sql in migration.PLATFORM_SQL:
                    con.execute(sql)
                con.execute('PRAGMA user_version=1')
                con.commit()
        elif mode == 'old_row_changed':
            startup(frozen_source[0], group['root'], 'upgrade')
            edit(group['root'] / 'household.sqlite3', "UPDATE users SET password='unexpected synthetic write'")
            return
        raise RuntimeError('DO_NOT_STORE_SYNTHETIC_SECRET')
    with pytest.raises(release.ReleaseDataError, match='warm_or_verification_failed'):
        warm(group, frozen_source, failure)
    assert calls == [1]
    assert (group['root'] / release.ROOT_ATTEMPT).is_file()
    assert 'DO_NOT_STORE_SYNTHETIC_SECRET' not in (group['attempt'] / 'failed.json').read_text()
    assert not (group['attempt'] / 'result.json').exists()
    with pytest.raises(release.ReleaseDataError, match='failed_attempt'):
        release.check_current_after(group['attempt'], group['root'])
    group['attempt'] = group['parent'] / 'different-attempt'
    with pytest.raises(release.ReleaseDataError, match='root_attempt_locked'):
        warm(group, frozen_source, failure)
    assert calls == [1]


@pytest.mark.parametrize('case', ['drift', 'half_migrated', 'source_identity', 'attempt_inside_root'])
def test_preconditions_do_not_call_warm(group, frozen_source, case):
    calls = []
    identity = dict(frozen_source[1])
    if case == 'drift':
        edit(group['root'] / 'household.sqlite3', "UPDATE settings SET revision=revision+1 WHERE id='meta'")
    elif case == 'half_migrated':
        edit(group['root'] / 'household.sqlite3', migration.PERSONAL_IDENTITY_SQL)
        group['before'] = release.snapshot(group['root'])
    elif case == 'source_identity':
        identity['runtimeHashes'] = {}
    else:
        group['attempt'] = group['root'] / 'attempt'
    with pytest.raises(release.ReleaseDataError):
        release.warm_once(group['root'], group['before'], group['manifest'], group['attempt'],
                          source_identity=identity, warm=lambda: calls.append(1))
    assert calls == [] and not (group['root'] / release.ROOT_ATTEMPT).exists()


def test_post_start_drift_and_full_group_restore(group, frozen_source):
    warm(group, frozen_source)
    edit(group['root'] / 'household.sqlite3', "UPDATE private_finance SET data='{}'")
    with pytest.raises(release.ReleaseDataError, match='post_start_database_drift'):
        release.check_current_after(group['attempt'], group['root'])
    # Restoration here is explicit test/controller work, not a helper action.
    restored = group['parent'] / 'restored'
    restored.mkdir()
    manifest = json.loads(group['manifest'].read_text())
    for item in manifest['snapshots']:
        relative = Path(item['path'])
        destination = restored / relative.parent.parent / ('platform.sqlite3' if relative.name.startswith('platform-') else 'household.sqlite3')
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(group['proof'] / relative, destination)
    assert release.verify_restored(group['before'], restored)['verified']
    next(restored.glob('spaces/*/household.sqlite3')).unlink()
    with pytest.raises((release.ReleaseDataError, migration.MigrationCheckError)):
        release.verify_restored(group['before'], restored)


def test_tampered_attempt_is_not_valid_post_start_evidence(group, frozen_source):
    warm(group, frozen_source)
    path = group['attempt'] / 'after.json'
    value = json.loads(path.read_text())
    value['households'] += 1
    path.write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises(release.ReleaseDataError, match='attempt_evidence_binding'):
        release.check_current_after(group['attempt'], group['root'])


def test_inflight_warm_cannot_be_duplicated_from_another_attempt(group, frozen_source):
    entered, proceed = Event(), Event()
    calls = []
    def delayed():
        calls.append(1)
        entered.set()
        assert proceed.wait(15)
        startup(frozen_source[0], group['root'], 'upgrade')
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(warm, group, frozen_source, delayed)
        try:
            assert entered.wait(15)
            second = dict(group, attempt=group['parent'] / 'concurrent-attempt')
            with pytest.raises(release.ReleaseDataError, match='root_attempt_locked'):
                warm(second, frozen_source, lambda: calls.append(2))
        finally:
            proceed.set()
        assert first.result(timeout=30)['state'] == 'completed'
    assert calls == [1]
