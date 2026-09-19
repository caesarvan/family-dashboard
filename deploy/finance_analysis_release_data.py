"""Preserve a complete stopped 61/9 group, add five tables, verify real startup."""
from pathlib import Path

from deploy import membership_release_data as shared
from deploy import steady_release_data as steady
from deploy import check_finance_analysis_migration as migration

MEMBERSHIP_MARKER_SHA256 = steady.MEMBERSHIP_MARKER_SHA256
marker_digest = steady.marker_digest


def begin(root, proof, **kwargs):
    # The existing full-group backup routine admits exactly 61/9 and preserves
    # the successful membership marker. Its exclusive attempt is also retained.
    return steady.begin(root, proof, **kwargs)


def evidence(root, proof, *, source_identity, plan_sha256, marker_sha256=MEMBERSHIP_MARKER_SHA256):
    root, proof = shared._directory(root), shared._directory(proof)
    before = shared._read_json(shared.migration.checked_path(proof / 'before.json'))
    identity = shared._source_identity(source_identity)
    attempt = shared._read_json(shared.migration.checked_path(proof / 'attempt.json'))
    shared.need(attempt == {'kind': 'steady-release-attempt', 'planSha256': plan_sha256,
        'beforeSha256': shared._digest(before), 'sourceIdentity': identity,
        'sourceIdentitySha256': shared._digest(identity), 'markerSha256': marker_sha256}, 'analysis_attempt_binding')
    shared.need(marker_digest(root) == marker_sha256, 'successful_membership_marker_changed')
    receipt = shared._read_json(shared.migration.checked_path(proof / 'backup.json'))
    manifest = shared._relative(proof / 'backup-group/backups', receipt['manifest'])
    backup, paths = shared._backup(root, before, manifest, phase='after')
    shared.need(backup == shared._read_json(proof / 'backup-verified.json'), 'retained_backup_changed')
    schema = migration.schema_definition()
    shared.need(all(identity['sourceHashes'].get(n) == digest and identity['runtimeHashes'].get(n) == digest
                    for n, digest in schema['sourceHashes'].items()), 'schema_source_identity_changed')
    return root, proof, before, identity, paths, schema


def verify_group(root, before, paths, schema):
    after = shared.snapshot(root)
    shared.need(after['rootSha256'] == before['rootSha256'] and set(after['databases']) == set(before['databases']),
                'registry_group_changed')
    comparisons = {}
    for name, backup in paths.items():
        old = shared.migration._read(backup)
        new = shared.migration._read(shared._relative(root, name))
        if name == 'platform.sqlite3':
            shared.need({k: v for k, v in old.items() if k != 'fileSha256'} ==
                        {k: v for k, v in new.items() if k != 'fileSha256'}, 'platform_changed')
        else:
            comparisons[name] = migration.verify_addition(old, new, schema)
    shared.need(shared.snapshot(root) == after, 'group_changed_during_verification')
    return after, comparisons


def migrate(root, proof, **kwargs):
    root, proof, before, identity, paths, schema = evidence(root, proof, **kwargs)
    shared.need(steady.snapshot(root) == before, 'database_changed_after_backup')
    # Exclusive before the first write: failures remain inspectable and cannot
    # resume or retry a partly migrated group, even with IF NOT EXISTS SQL.
    record = {'planSha256': kwargs['plan_sha256'], 'beforeSha256': shared._digest(before),
              'sourceIdentitySha256': shared._digest(identity), 'schemaSha256': schema['sha256']}
    shared._write_new(proof / 'migration-attempt.json', record)
    for name in sorted(paths):
        if name != 'platform.sqlite3':
            migration.initialize_database(shared._relative(root, name), schema)
    after, comparisons = verify_group(root, before, paths, schema)
    evidence(root, proof, **kwargs)
    result = {**record, 'verified': True, 'households': after['households'], 'databases': len(paths),
              'logicalSha256': shared._digest(shared._logical(after)), 'comparisons': comparisons}
    shared._write_new(proof / 'migrated.json', after)
    shared._write_new(proof / 'migration-result.json', result)
    return result


def check_stopped(root, proof, **kwargs):
    root, proof, before, identity, paths, schema = evidence(root, proof, **kwargs)
    attempt = shared._read_json(shared.migration.checked_path(proof / 'migration-attempt.json'))
    shared.need(attempt == {'planSha256': kwargs['plan_sha256'], 'beforeSha256': shared._digest(before),
        'sourceIdentitySha256': shared._digest(identity), 'schemaSha256': schema['sha256']}, 'migration_binding_changed')
    migrated = shared._read_json(shared.migration.checked_path(proof / 'migrated.json'))
    result_before = shared._read_json(shared.migration.checked_path(proof / 'migration-result.json'))
    after, comparisons = verify_group(root, before, paths, schema)
    digest = shared._digest(shared._logical(after))
    shared.need(shared._logical(after) == shared._logical(migrated) and result_before['logicalSha256'] == digest,
                'app_startup_changed_data')
    evidence(root, proof, **kwargs)
    result = {'verified': True, 'households': after['households'], 'databases': len(paths),
              'logicalSha256': digest, 'markerSha256': kwargs.get('marker_sha256', MEMBERSHIP_MARKER_SHA256),
              'planSha256': kwargs['plan_sha256'], 'sourceIdentitySha256': shared._digest(identity),
              'comparisons': comparisons}
    shared._write_new(proof / 'after.json', after)
    shared._write_new(proof / 'result.json', result)
    return result


def snapshot_current(root):
    """A populated 66/9 reference for explicit backup/restore verification."""
    root = shared._directory(root)
    schema = migration.schema_definition()
    result = shared.snapshot(root)
    platform = result['databases']['platform.sqlite3']
    shared.need(platform['membershipPhase'] == 'after' and platform['userVersion'] == 1, 'platform_profile_changed')
    for name in result['databases']:
        if name != 'platform.sqlite3':
            migration.verify_current(shared.migration._read(shared._relative(root, name)), schema)
    shared.need(shared.snapshot(root) == result, 'group_changed_during_snapshot')
    return result


def verify_restore(reference, restored_root, *, marker_sha256=MEMBERSHIP_MARKER_SHA256):
    """Compare a whole restored 66/9 group before any session invalidation."""
    current = snapshot_current(restored_root)
    shared.need(shared._logical(current) == shared._logical(reference), 'restored_group_changed')
    shared.need(marker_digest(restored_root) == marker_sha256, 'successful_membership_marker_changed')
    return {'verified': True, 'households': current['households'], 'databases': len(current['databases']),
            'completeGroupRestored': True, 'logicalSha256': shared._digest(shared._logical(current))}


def verify_rollback(proof, restored_root):
    """Read-only proof of a complete 61/9 rollback, including its original marker."""
    proof = shared._directory(proof)
    before = shared._read_json(shared.migration.checked_path(proof / 'before.json'))
    shared._profile(before, 'after')
    attempt = shared._read_json(shared.migration.checked_path(proof / 'attempt.json'))
    shared.need(attempt['beforeSha256'] == shared._digest(before), 'rollback_reference_changed')
    current = steady.snapshot(restored_root)
    shared.need(shared._logical(current) == shared._logical(before), 'rolled_back_group_changed')
    shared.need(marker_digest(restored_root) == attempt['markerSha256'], 'successful_membership_marker_changed')
    return {'verified': True, 'households': current['households'], 'databases': len(current['databases']),
            'completeGroupRestored': True, 'logicalSha256': shared._digest(shared._logical(current))}
