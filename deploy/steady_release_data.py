"""Closed 61/9 group preservation. Never initializes apps or rewrites migration markers."""
from pathlib import Path
import re
import shutil

from deploy import membership_release_data as shared
from deploy.backup import backup_all

# Reconstructed from the independently audited successful R3 attempt receipt.
# This identifies the successful migration only; its old database rows are not
# a baseline for this release. Capture current, stopped rows at release time.
MEMBERSHIP_MARKER_SHA256 = 'd223842c531e115b21430e860ffa8e742b1fbf0616942a228d04009e66dedb93'


def marker_digest(root):
    return shared.migration.file_digest(shared.migration.checked_path(Path(root) / shared.ROOT_ATTEMPT))


def snapshot(root):
    value = shared.snapshot(root)
    shared._profile(value, 'after')
    shared.need(all(v['userVersion'] == (1 if n == 'platform.sqlite3' else 0)
                    for n, v in value['databases'].items()), 'steady_schema_version')
    return value


def begin(root, proof, *, source_identity, plan_sha256, marker_sha256=MEMBERSHIP_MARKER_SHA256):
    """Stop all writers before calling; backup all registry DBs and retain copies."""
    root, proof = shared._directory(root), shared._directory(proof)
    shared.need(not root.is_relative_to(proof) and not proof.is_relative_to(root), 'proof_must_be_external')
    identity = shared._source_identity(source_identity)
    shared.need(isinstance(plan_sha256, str) and re.fullmatch('[0-9a-f]{64}', plan_sha256), 'steady_plan_identity')
    shared.need(marker_digest(root) == marker_sha256, 'successful_membership_marker_changed')
    before = snapshot(root)
    # Exclusive first write prevents a repeated backup/startup after any failure.
    attempt = {'kind': 'steady-release-attempt', 'planSha256': plan_sha256,
               'beforeSha256': shared._digest(before), 'sourceIdentity': identity,
               'sourceIdentitySha256': shared._digest(identity), 'markerSha256': marker_sha256}
    shared._write_new(proof / 'attempt.json', attempt)
    shared._write_new(proof / 'before.json', before)
    receipt = backup_all(root)
    manifest = root / 'backups' / receipt['manifest']
    finished = shared.finish_stopped_backup(root, before, manifest, phase='after')
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
    backup = shared.validate_backup(root, before, retained_manifest, phase='after')
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
    shared.need(attempt == {'kind': 'steady-release-attempt', 'planSha256': plan_sha256,
        'beforeSha256': shared._digest(before), 'sourceIdentity': identity,
        'sourceIdentitySha256': shared._digest(identity), 'markerSha256': marker_sha256}, 'steady_attempt_binding')
    shared._profile(before, 'after')
    shared.need(marker_digest(root) == marker_sha256, 'successful_membership_marker_changed')
    receipt = shared._read_json(shared.migration.checked_path(proof / 'backup.json'))
    manifest = shared._relative(proof / 'backup-group/backups', receipt['manifest'])
    backup = shared.validate_backup(root, before, manifest, phase='after')
    expected = shared._read_json(shared.migration.checked_path(proof / 'backup-verified.json'))
    shared.need(backup == expected, 'retained_backup_changed')
    after = snapshot(root)
    shared.need(after['rootSha256'] == before['rootSha256'] and
                shared._logical(after) == shared._logical(before), 'steady_database_drift')
    shared.need(marker_digest(root) == marker_sha256, 'successful_membership_marker_changed')
    result = {'verified': True, 'databases': len(after['databases']), 'households': after['households'],
              'logicalSha256': shared._digest(shared._logical(after)), 'markerSha256': marker_sha256,
              'planSha256': plan_sha256, 'sourceIdentitySha256': shared._digest(identity)}
    shared._write_new(proof / 'after.json', after)
    shared._write_new(proof / 'result.json', result)
    return result
