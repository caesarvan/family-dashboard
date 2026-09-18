"""Stopped membership database-group safeguards; no service/container control.

The controller owns stop/backup/source-image verification and supplies one warm
callback. This module never loads configuration or starts an application itself.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

from deploy import membership_migration as migration

ROOT_ATTEMPT = 'membership-release-attempt.json'


class ReleaseDataError(RuntimeError):
    """Fixed error code, never database/configuration contents."""


def need(value, code):
    if not value:
        raise ReleaseDataError(code)


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _directory(value):
    path = Path(os.path.abspath(value))
    try:
        for item in (path, *path.parents):
            info = item.lstat()
            need(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400, 'linked_directory')
        need(path.is_dir(), 'missing_directory')
    except OSError:
        raise ReleaseDataError('missing_directory') from None
    return path


def _relative(root, value):
    need(isinstance(value, str) and value and '\\' not in value and ':' not in value, 'unsafe_relative_path')
    parsed = PurePosixPath(value)
    need(not parsed.is_absolute() and parsed.as_posix() == value and
         all(p not in ('', '.', '..') for p in parsed.parts), 'unsafe_relative_path')
    return migration.checked_path(root / value)


def _read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            need(key not in result, 'duplicate_json_field')
            result[key] = value
        return result
    try:
        return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique)
    except (OSError, ValueError, UnicodeError):
        raise ReleaseDataError('invalid_evidence_json') from None


def _write_new(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
        stream.write(_json(value) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def _registry_paths(registry):
    value = migration._read(registry)
    columns = value['columns'].get('households', [])
    need([r[1] for r in columns] == ['id', 'slug', 'name', 'created_at'], 'registry_columns')
    ids = [row[0] for row in value['rows']['households']]
    need(ids and ids.count('default') == 1 and len(ids) == len(set(ids)), 'registry_households')
    need(all(uid == 'default' or isinstance(uid, str) and re.fullmatch('[0-9a-f]{24}', uid) for uid in ids), 'registry_household_id')
    return ['platform.sqlite3', 'household.sqlite3',
            *['spaces/' + uid + '/household.sqlite3' for uid in sorted(ids) if uid != 'default']]


def enumerate_databases(data_root):
    """Return the complete registry-bound relative database list, never IDs/names from other tables."""
    root = _directory(data_root)
    registry = _relative(root, 'platform.sqlite3')
    expected = _registry_paths(registry)
    for relative in expected:
        _relative(root, relative)
    spaces = root / 'spaces'
    if spaces.exists():
        _directory(spaces)
        for child in spaces.iterdir():
            if child.is_dir():
                _directory(child)
                if (child / 'household.sqlite3').exists():
                    need('spaces/' + child.name + '/household.sqlite3' in expected, 'unregistered_household_database')
    return tuple(expected)


def _fingerprint(value, platform):
    result = migration._summary(value)
    tables = {n for n in value['rows'] if not n.startswith('sqlite_')}
    if platform:
        before = tables == migration.BASE_PLATFORM_TABLES and value['userVersion'] == 0
        after = tables == migration.BASE_PLATFORM_TABLES | migration.NEW_PLATFORM_TABLES and value['userVersion'] == 1
    else:
        columns = value['columns'].get('member_sessions', [])
        markers = [r for r in value['rows'].get('settings', []) if r[0] == migration.MARKER[0]]
        before = tables == migration.BASE_HOUSEHOLD_TABLES and not markers and all(r[1] != 'personal_identity' for r in columns)
        after = tables == migration.BASE_HOUSEHOLD_TABLES | migration.NEW_HOUSEHOLD_TABLES and markers == [migration.MARKER] and bool(columns) and columns[-1] == (len(columns)-1, 'personal_identity', 'TEXT', 0, None, 0, 0)
    result['membershipPhase'] = 'before' if before else 'after' if after else 'partial_or_unknown'
    return result


def snapshot(data_root):
    """Read stopped copies only; all rows/schema/sequence plus file hashes, no plaintext records."""
    root = _directory(data_root)
    paths = enumerate_databases(root)
    databases = {relative: _fingerprint(migration._read(_relative(root, relative)), relative == 'platform.sqlite3') for relative in paths}
    need(enumerate_databases(root) == paths, 'registry_changed_during_snapshot')
    need(all(migration.file_digest(_relative(root, p)) == v['fileSha256'] for p, v in databases.items()), 'group_changed_during_snapshot')
    return {'format': 'membership-database-group-v1', 'rootSha256': _digest(str(root)),
            'households': len(paths) - 1, 'databases': databases}


def _logical(value):
    return {'households': value['households'], 'databases': {
        name: {key: item for key, item in fingerprint.items() if key != 'fileSha256'}
        for name, fingerprint in value['databases'].items()}}


def _profile(value, phase):
    need(isinstance(value, dict) and set(value) == {'format', 'rootSha256', 'households', 'databases'} and
         value['format'] == 'membership-database-group-v1', 'snapshot_shape')
    need(type(value['households']) is int and value['households'] >= 1 and
         len(value['databases']) == value['households'] + 1 and 'platform.sqlite3' in value['databases'], 'snapshot_group')
    for path, fingerprint in value['databases'].items():
        need(fingerprint['membershipPhase'] == phase, 'mixed_or_partial_migration')
        platform = path == 'platform.sqlite3'
        need(platform or path == 'household.sqlite3' or re.fullmatch('spaces/[0-9a-f]{24}/household.sqlite3', path), 'snapshot_path')
        tables = set(fingerprint['tables'])
        user_tables = {name for name in tables if not name.startswith('sqlite_')}
        expected = migration.BASE_PLATFORM_TABLES if platform else migration.BASE_HOUSEHOLD_TABLES
        if phase == 'after':
            expected = expected | (migration.NEW_PLATFORM_TABLES if platform else migration.NEW_HOUSEHOLD_TABLES)
        need(user_tables == expected, 'unexpected_schema_profile')
        if platform:
            need(fingerprint['userVersion'] == (0 if phase == 'before' else 1), 'platform_version_profile')


def _backup(data_root, before, manifest_path):
    root = _directory(data_root)
    _profile(before, 'before')
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


def validate_backup(data_root, before, manifest_path):
    """Validate original deploy/backup.py manifest (also copied intact under proof/backup-group)."""
    return _backup(data_root, before, manifest_path)[0]


def _source_identity(value):
    need(isinstance(value, dict) and set(value) == {'head', 'tree', 'imageId', 'sourceHashes', 'runtimeHashes'}, 'source_identity_shape')
    need(all(isinstance(value[k], str) and re.fullmatch('[0-9a-f]{40}', value[k]) for k in ('head', 'tree')) and
         isinstance(value['imageId'], str) and re.fullmatch('sha256:[0-9a-f]{64}', value['imageId']), 'source_identity_values')
    for field in ('sourceHashes', 'runtimeHashes'):
        values = value[field]
        need(isinstance(values, dict) and values, 'source_identity_hashes')
        for path, digest in values.items():
            need(isinstance(path, str) and path and not path.startswith('/') and '\\' not in path and ':' not in path and
                 all(p not in ('', '.', '..') for p in path.split('/')) and
                 isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest), 'source_identity_hash_entry')
    return json.loads(_json(value))


def warm_once(data_root, before, manifest_path, attempt_directory, *, source_identity, warm):
    """One callback invocation, with a persistent exclusive attempt and no automatic rollback/retry."""
    root = _directory(data_root)
    identity = _source_identity(source_identity)
    need(callable(warm), 'warm_callback_required')
    attempt = Path(os.path.abspath(attempt_directory))
    _directory(attempt.parent)
    need(not attempt.is_relative_to(root) and not root.is_relative_to(attempt), 'attempt_must_be_external')
    need(not attempt.exists(), 'attempt_already_exists')
    need(not (root / ROOT_ATTEMPT).exists(), 'root_attempt_locked')
    current = snapshot(root)
    _profile(before, 'before')
    need(current == before, 'before_snapshot_drift')
    backup, paths = _backup(root, before, manifest_path)
    # Exact backups are retained by the controller outside rotating history.
    attempt.mkdir(mode=0o700, exist_ok=False)
    _write_new(attempt / 'attempt.json', {'state': 'started', 'startedAt': datetime.now(timezone.utc).isoformat(),
        'rootSha256': before['rootSha256'], 'beforeSha256': _digest(before), 'sourceIdentity': identity,
        'sourceIdentitySha256': _digest(identity), 'backup': backup})
    _write_new(attempt / 'before.json', before)
    try:
        _write_new(root / ROOT_ATTEMPT, {'attemptSha256': migration.file_digest(attempt / 'attempt.json'),
            'rootSha256': before['rootSha256'], 'sourceIdentitySha256': _digest(identity)})
        need(snapshot(root) == before, 'before_snapshot_drift')
        need(_backup(root, before, manifest_path)[0] == backup, 'backup_changed_before_warm')
        # The controller's network-none process/container executes its frozen
        # source once, initializes every registry household and closes all DBs.
        warm()
        after = snapshot(root)
        _profile(after, 'after')
        need(set(after['databases']) == set(before['databases']), 'registry_group_changed')
        comparisons = {}
        for relative in before['databases']:
            live = _relative(root, relative)
            verify = migration.verify_platform if relative == 'platform.sqlite3' else migration.verify_household
            comparisons[relative] = verify(paths[relative], live)
        need(all(migration.file_digest(paths[p]) == backup['files'][p] for p in paths), 'backup_changed_during_warm')
        need(migration.file_digest(migration.checked_path(manifest_path)) == backup['manifestSha256'], 'manifest_changed_during_warm')
        need(snapshot(root) == after, 'after_snapshot_drift')
        _write_new(attempt / 'after.json', after)
        result = {'state': 'completed', 'households': after['households'], 'databases': len(after['databases']),
                  'afterSha256': _digest(after), 'afterLogicalSha256': _digest(_logical(after)),
                  'sourceIdentitySha256': _digest(identity), 'comparisons': comparisons,
                  'completedAt': datetime.now(timezone.utc).isoformat()}
        _write_new(attempt / 'result.json', result)
        return result
    except BaseException:
        # Preserve the started marker even if this secondary write itself fails.
        # Exception details may contain secrets, so never store them here.
        _write_new(attempt / 'failed.json', {'state': 'failed', 'code': 'warm_or_verification_failed',
            'automaticRetryAllowed': False, 'automaticRollbackPerformed': False})
        raise ReleaseDataError('warm_or_verification_failed') from None


def check_current_after(attempt_directory, data_root):
    """Read-only check after the new app first starts and is stopped again."""
    attempt = _directory(attempt_directory)
    need(not (attempt / 'failed.json').exists(), 'failed_attempt')
    marker = _read_json(migration.checked_path(attempt / 'attempt.json'))
    before = _read_json(migration.checked_path(attempt / 'before.json'))
    after = _read_json(migration.checked_path(attempt / 'after.json'))
    result = _read_json(migration.checked_path(attempt / 'result.json'))
    need(marker['state'] == 'started' and result['state'] == 'completed' and
         marker['beforeSha256'] == _digest(before) and result['afterSha256'] == _digest(after) and
         marker['sourceIdentitySha256'] == result['sourceIdentitySha256'] == _digest(_source_identity(marker['sourceIdentity'])), 'attempt_evidence_binding')
    current = snapshot(data_root)
    lock = _read_json(migration.checked_path(_directory(data_root) / ROOT_ATTEMPT))
    need(lock == {'attemptSha256': migration.file_digest(attempt / 'attempt.json'),
                  'rootSha256': marker['rootSha256'], 'sourceIdentitySha256': marker['sourceIdentitySha256']}, 'root_attempt_binding')
    _profile(current, 'after')
    need(current['rootSha256'] == after['rootSha256'] == marker['rootSha256'] and
         _logical(current) == _logical(after), 'post_start_database_drift')
    return {'verified': True, 'households': current['households'], 'databases': len(current['databases']),
            'logicalSha256': _digest(_logical(current)), 'snapshot': current}


def verify_restored(before, restored_root):
    """Only verify a controller-restored whole group; never copy/delete databases."""
    _profile(before, 'before')
    restored = snapshot(restored_root)
    _profile(restored, 'before')
    need(_logical(before) == _logical(restored), 'restored_group_drift')
    return {'verified': True, 'households': restored['households'], 'databases': len(restored['databases']),
            'logicalSha256': _digest(_logical(restored))}
