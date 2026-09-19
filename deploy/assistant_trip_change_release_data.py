"""Closed populated 66/9 source-update proof; never migrate or import an app.

Backup manifest/path/content and empty-WAL safeguards are the existing strict
membership adapter with an explicit current66 profile. Frozen old adapters are
not patched or reinterpreted as 66 tables. Recovery uses the analysis reader.
"""
from contextlib import closing
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat

from deploy import membership_release_data as shared
from deploy import finance_analysis_release_data as analysis
from deploy.backup import backup_all
from deploy.membership_release_data import (
    ReleaseDataError, migration, need, _directory, _relative, _read_json, _digest,
    _fingerprint, _registry_paths, _logical,
)

MEMBERSHIP_MARKER_SHA256 = analysis.MEMBERSHIP_MARKER_SHA256
marker_digest = analysis.marker_digest
snapshot = snapshot_current = analysis.snapshot_current
verify_restore = analysis.verify_restore


def _profile(value):
    need(isinstance(value, dict) and set(value) == {'format', 'rootSha256', 'households', 'databases'}
         and value['format'] == 'membership-database-group-v1', 'snapshot_shape')
    need(type(value['households']) is int and value['households'] >= 1 and
         len(value['databases']) == value['households'] + 1 and
         {'platform.sqlite3', 'household.sqlite3'} <= value['databases'].keys(), 'snapshot_group')
    for path, fingerprint in value['databases'].items():
        platform = path == 'platform.sqlite3'
        need(platform or path == 'household.sqlite3' or
             re.fullmatch('spaces/[0-9a-f]{24}/household.sqlite3', path), 'snapshot_path')
        expected = (migration.BASE_PLATFORM_TABLES | migration.NEW_PLATFORM_TABLES if platform else
                    analysis.migration.BASE_TABLES | analysis.migration.NEW_TABLES)
        tables = {n for n in fingerprint['tables'] if not n.startswith('sqlite_')}
        need(tables == expected and len(tables) == (9 if platform else 66), 'expected_66_9_profile')
        need(fingerprint['userVersion'] == (1 if platform else 0) and
             fingerprint['membershipPhase'] == ('after' if platform else 'partial_or_unknown'),
             'snapshot_version_profile')


def _backup(data_root, before, manifest_path, *, phase='current'):
    need(phase == 'current', 'backup_profile')
    root = _directory(data_root)
    _profile(before)
    need(before['rootSha256'] == _digest(str(root)), 'snapshot_root_binding')
    manifest = migration.checked_path(manifest_path)
    manifest_hash = migration.file_digest(manifest)
    need(manifest.parent.name == 'backups', 'manifest_layout')
    backup_root = _directory(manifest.parent.parent)
    record = _read_json(manifest)
    need(isinstance(record, dict) and set(record) == {'createdAt', 'snapshots'} and
         isinstance(record['createdAt'], str) and re.fullmatch('[0-9]{8}T[0-9]{12}Z', record['createdAt']), 'backup_manifest_shape')
    stamp = record['createdAt']
    need(manifest.name == 'manifest-' + stamp + '.json' and isinstance(record['snapshots'], list), 'backup_manifest_name')
    expected = {}
    for original in before['databases']:
        parent = PurePosixPath(original).parent
        prefix = 'platform' if original == 'platform.sqlite3' else 'household'
        expected[(parent / 'backups' / (prefix + '-' + stamp + '.sqlite3')).as_posix()] = original
    need(len(record['snapshots']) == len(expected), 'backup_group_incomplete')
    seen, paths, fingerprints = set(), {}, {}
    for entry in record['snapshots']:
        need(isinstance(entry, dict) and set(entry) == {'path', 'bytes', 'sha256'}, 'backup_entry_shape')
        relative = entry['path']
        need(isinstance(relative, str) and relative in expected and relative not in seen, 'backup_group_paths')
        seen.add(relative)
        target = _relative(backup_root, relative)
        need(type(entry['bytes']) is int and entry['bytes'] > 0 and target.stat().st_size == entry['bytes'] and
             isinstance(entry['sha256'], str) and re.fullmatch('[0-9a-f]{64}', entry['sha256']) and
             migration.file_digest(target) == entry['sha256'], 'backup_file_digest')
        original = expected[relative]
        fingerprint = _fingerprint(migration._read(target), original == 'platform.sqlite3')
        need({k: v for k, v in fingerprint.items() if k != 'fileSha256'} ==
             {k: v for k, v in before['databases'][original].items() if k != 'fileSha256'}, 'backup_logical_state')
        paths[original] = target
        fingerprints[original] = fingerprint
    need(seen == set(expected), 'backup_group_incomplete')
    # Bind the backup registry itself to exactly this complete group.
    need(set(_registry_paths(paths['platform.sqlite3'])) == set(paths), 'backup_registry_group')
    need(all(migration.file_digest(paths[p]) == v['fileSha256'] for p, v in fingerprints.items()), 'backup_changed_during_check')
    need(migration.file_digest(manifest) == manifest_hash, 'manifest_changed_during_check')
    proof = {'verified': True, 'manifestSha256': manifest_hash, 'databases': len(paths),
             'households': before['households'], 'files': {p: v['fileSha256'] for p, v in fingerprints.items()},
             'logicalSha256': _digest(_logical(before)), 'stoppedWriterRequirement': True}
    return proof, paths


def validate_backup(data_root, before, manifest_path, *, phase='current'):
    """Validate original deploy/backup.py manifest (also copied intact under proof/backup-group)."""
    return _backup(data_root, before, manifest_path, phase=phase)[0]


def finish_stopped_backup(data_root, before, manifest_path, *, phase='current'):
    """Close only empty WAL pairs created since the stopped, sidecar-free before.

    All writers must remain stopped. Never use this for a general WAL recovery:
    the original main-file bytes and complete backup must still equal before.
    SQLite owns checkpoint/sidecar removal; the migration reader stays strict.
    """
    root = _directory(data_root)
    backup = validate_backup(root, before, manifest_path, phase=phase)
    sources, pending = {}, []
    # Preflight the entire group before opening any source in read/write mode.
    for relative, fingerprint in before['databases'].items():
        path = root / relative  # The complete relative set was validated above.
        _directory(path.parent)
        try:
            attrs = path.lstat()
            need(stat.S_ISREG(attrs.st_mode) and not getattr(attrs, 'st_file_attributes', 0) & 0x400,
                 'backup_source_not_regular')
            need(migration.file_digest(path) == fingerprint['fileSha256'], 'backup_source_changed')
            present = {}
            for suffix in ('-wal', '-shm', '-journal'):
                sidecar = Path(str(path) + suffix)
                if sidecar.exists() or sidecar.is_symlink():
                    info = sidecar.lstat()
                    need(stat.S_ISREG(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
                         'backup_sidecar_not_regular')
                    present[suffix] = info.st_size
            need(not present or present == {'-wal': 0, '-shm': 32768}, 'backup_sidecar_not_empty_pair')
        except OSError:
            raise ReleaseDataError('backup_source_unavailable') from None
        sources[relative] = path
        if present:
            pending.append(path)
    for path in pending:
        try:
            with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=0)) as con:
                con.execute('PRAGMA trusted_schema=OFF')
                need(con.execute('PRAGMA journal_mode').fetchone() == ('wal',), 'backup_source_not_wal')
                need(con.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchall() == [(0, 0, 0)],
                     'backup_checkpoint_not_empty')
        except sqlite3.Error:
            raise ReleaseDataError('backup_checkpoint_failed') from None
        migration.no_sidecars(path)
    need(snapshot(root) == before, 'backup_finished_snapshot_drift')
    need(validate_backup(root, before, manifest_path, phase=phase) == backup, 'backup_changed_during_finish')
    return {'verified': True, 'databases': len(sources), 'emptyWalPairsClosed': len(pending),
            'beforeSha256': _digest(before), 'backup': backup}


def begin(root, proof, *, source_identity, plan_sha256, marker_sha256=MEMBERSHIP_MARKER_SHA256):
    """Stop all writers before calling; backup all registry DBs and retain copies."""
    root, proof = shared._directory(root), shared._directory(proof)
    shared.need(not root.is_relative_to(proof) and not proof.is_relative_to(root), 'proof_must_be_external')
    identity = shared._source_identity(source_identity)
    shared.need(isinstance(plan_sha256, str) and re.fullmatch('[0-9a-f]{64}', plan_sha256), 'assistant_plan_identity')
    shared.need(marker_digest(root) == marker_sha256, 'successful_membership_marker_changed')
    before = snapshot(root)
    # Exclusive first write prevents a repeated backup/startup after any failure.
    attempt = {'kind': 'assistant-trip-change-release-attempt', 'planSha256': plan_sha256,
               'beforeSha256': shared._digest(before), 'sourceIdentity': identity,
               'sourceIdentitySha256': shared._digest(identity), 'markerSha256': marker_sha256}
    shared._write_new(proof / 'attempt.json', attempt)
    shared._write_new(proof / 'before.json', before)
    receipt = backup_all(root)
    manifest = root / 'backups' / receipt['manifest']
    finished = finish_stopped_backup(root, before, manifest, phase='current')
    saved = proof / 'backup-group'
    saved.mkdir(mode=0o700)
    record = shared._read_json(manifest)
    for item in record['snapshots']:
        source = shared._relative(root, item['path'])
        target = saved / item['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target); target.chmod(0o600)
    retained_manifest = saved / 'backups' / receipt['manifest']
    retained_manifest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(manifest, retained_manifest); retained_manifest.chmod(0o600)
    backup = validate_backup(root, before, retained_manifest, phase='current')
    shared.need(snapshot(root) == before and marker_digest(root) == marker_sha256, 'backup_state_changed')
    for name, value in [('backup.json', receipt), ('backup-finish.json', finished), ('backup-verified.json', backup)]:
        shared._write_new(proof / name, value)
    return {'verified': True, 'databases': backup['databases'], 'households': backup['households'],
            'logicalSha256': backup['logicalSha256'], 'markerSha256': marker_sha256}


def check_stopped(root, proof, *, source_identity, plan_sha256, marker_sha256=MEMBERSHIP_MARKER_SHA256):
    """After real app initialization and clean stop, compare complete current group."""
    root, proof = shared._directory(root), shared._directory(proof)
    attempt = shared._read_json(shared.migration.checked_path(proof / 'attempt.json'))
    before = shared._read_json(shared.migration.checked_path(proof / 'before.json'))
    identity = shared._source_identity(source_identity)
    shared.need(attempt == {'kind': 'assistant-trip-change-release-attempt', 'planSha256': plan_sha256,
        'beforeSha256': shared._digest(before), 'sourceIdentity': identity,
        'sourceIdentitySha256': shared._digest(identity), 'markerSha256': marker_sha256}, 'assistant_attempt_binding')
    _profile(before)
    shared.need(marker_digest(root) == marker_sha256, 'successful_membership_marker_changed')
    receipt = shared._read_json(shared.migration.checked_path(proof / 'backup.json'))
    manifest = shared._relative(proof / 'backup-group/backups', receipt['manifest'])
    backup = validate_backup(root, before, manifest, phase='current')
    expected = shared._read_json(shared.migration.checked_path(proof / 'backup-verified.json'))
    shared.need(backup == expected, 'retained_backup_changed')
    after = snapshot(root)
    shared.need(after['rootSha256'] == before['rootSha256'] and
                shared._logical(after) == shared._logical(before), 'assistant_database_drift')
    shared.need(marker_digest(root) == marker_sha256, 'successful_membership_marker_changed')
    result = {'verified': True, 'databases': len(after['databases']), 'households': after['households'],
              'logicalSha256': shared._digest(shared._logical(after)), 'markerSha256': marker_sha256,
              'planSha256': plan_sha256, 'sourceIdentitySha256': shared._digest(identity)}
    shared._write_new(proof / 'after.json', after)
    shared._write_new(proof / 'result.json', result)
    return result
