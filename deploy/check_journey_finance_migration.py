"""Stopped complete-group 73/9 -> 75/9 migration using the frozen journey finance initializer.

No app startup, network or restore writes. All production writers must already
be stopped; a failed attempt is retained and cannot be replayed.
"""
from contextlib import closing
import hashlib
import importlib
from pathlib import Path
import re
import sqlite3

from deploy import membership_release_data as shared
from deploy import media_video_release_data as baseline
from deploy import assistant_trip_change_release_data as backup_core
from deploy import check_media_video_migration as video

ROOT = Path(__file__).resolve().parents[1]
BASE_TABLES = video.BASE_TABLES | video.NEW_TABLES
NEW_TABLES = frozenset({'hub_journey_allocations', 'hub_journey_allocation_operations'})
NEW_INDEXES = frozenset({'hub_journey_allocations_active', 'hub_journey_allocations_payment',
                         'hub_journey_allocations_journey', 'hub_journey_allocations_created'})
SCHEMA_SHA256 = 'f936c9403df6c4ad888502a0fcd03574ccd876a5403bb003015b232833e71450'
MODULE_SHA256 = '750c3732fbfb0952d7ee01386d6a93529414098cfaa61f1428af2c09acf62a6e'
SOURCE_MODULES = ('journey_finance', 'finance_hub', 'financial_files', 'finance_source_bridge', 'finance_baseline')
MEMBERSHIP_MARKER_SHA256 = baseline.MEMBERSHIP_MARKER_SHA256
marker_digest = baseline.marker_digest
need = shared.need


def runtime_module(name):
    need(name in SOURCE_MODULES, 'unexpected_journey_finance_module')
    module = importlib.import_module(name)
    expected = shared.migration.checked_path(ROOT / (name + '.py'))
    actual = shared.migration.checked_path(module.__file__)
    allowed = {expected}
    if ROOT == Path('/release'):
        allowed.add(Path('/app') / (name + '.py'))
    need(actual in allowed and actual.read_bytes() == expected.read_bytes(), 'journey_finance_module_import_changed')
    return module


def _new_object(row):
    # In particular, retain the OLD media_video_deleted trigger on media_items.
    return row[2] in NEW_TABLES


def schema_definition():
    expected = shared.migration.checked_path(ROOT / 'journey_finance.py')
    need(shared.migration.file_digest(expected) == MODULE_SHA256, 'reviewed_initializer_changed')
    modules = {name: runtime_module(name) for name in SOURCE_MODULES}
    module = modules['journey_finance']
    sql = module.SCHEMA_SQL
    need(isinstance(sql, str) and hashlib.sha256(sql.encode()).hexdigest() == SCHEMA_SHA256,
         'reviewed_schema_changed')
    statements = [v.strip() for v in sql.split(';') if v.strip()]
    tables, indexes = [], []
    for statement in statements:
        match = re.match(r'CREATE TABLE IF NOT EXISTS ([a-z_]+)\s*\(', statement)
        if match:
            tables.append(match[1])
        else:
            match = re.match(r'CREATE (?:UNIQUE )?INDEX IF NOT EXISTS ([a-z_]+)\s+ON ([a-z_]+)\(', statement)
            need(match is not None and match[2] in NEW_TABLES, 'unexpected_schema_statement')
            indexes.append(match[1])
    need(len(tables) == 2 and set(tables) == NEW_TABLES and len(indexes) == 4 and
         set(indexes) == NEW_INDEXES, 'unexpected_journey_finance_schema')
    with closing(sqlite3.connect(':memory:')) as con:
        con.execute('PRAGMA foreign_keys=ON')
        con.execute('CREATE TABLE users(id TEXT PRIMARY KEY)')
        parents = shared.migration.objects(con)
        con.execute('BEGIN IMMEDIATE')
        module.init_schema(con)
        need(con.in_transaction, 'initializer_committed_transaction')
        objects = [row for row in shared.migration.objects(con) if row not in parents]
        need(all(row[0] in ('table', 'index') and row[2] in NEW_TABLES for row in objects),
             'unexpected_schema_object')
        columns = {name: con.execute('PRAGMA table_xinfo(' + name + ')').fetchall() for name in NEW_TABLES}
        con.rollback()
        need(shared.migration.objects(con) == parents, 'initializer_not_atomic')
    return {'profile': 'journey_finance75', 'sql': sql, 'sha256': SCHEMA_SHA256,
            'sourceHashes': {name + '.py': shared.migration.file_digest(ROOT / (name + '.py'))
                             for name in SOURCE_MODULES},
            'tables': sorted(NEW_TABLES), 'objects': objects, 'columns': columns}


def verify_baseline(value):
    need(len(BASE_TABLES) == 73, 'baseline_definition_changed')
    need(not any(_new_object(row) or row[1] in NEW_INDEXES | NEW_TABLES for row in value['schema']),
         'journey_finance_object_already_exists')
    video.verify_current(value, video.schema_definition())


def snapshot_baseline(root):
    result = baseline.snapshot_current(root)
    for name in result['databases']:
        if name != 'platform.sqlite3':
            verify_baseline(shared.migration._read(shared._relative(Path(root), name)))
    need(baseline.snapshot_current(root) == result, 'baseline_changed_during_snapshot')
    return result


BEGIN_SPEC = backup_core.DataSpec(baseline.SPEC.profile, snapshot_baseline, 'journey-finance-migration-attempt')


def verify_current(value, schema):
    need({n for n in value['rows'] if not n.startswith('sqlite_')} == BASE_TABLES | NEW_TABLES,
         'expected_75_table_profile')
    need([r for r in value['schema'] if _new_object(r)] == schema['objects'], 'journey_finance_schema_changed')
    need(all(value['columns'][n] == schema['columns'][n] for n in NEW_TABLES), 'journey_finance_columns_changed')
    old = dict(value, schema=[r for r in value['schema'] if not _new_object(r)],
               rows={n: v for n, v in value['rows'].items() if n not in NEW_TABLES},
               columns={n: v for n, v in value['columns'].items() if n not in NEW_TABLES})
    verify_baseline(old)


def verify_addition(before, after, schema):
    verify_baseline(before)
    verify_current(after, schema)
    need(not ({r[1] for r in before['schema']} & {r[1] for r in schema['objects']}), 'schema_name_collision')
    need(after['schema'] == sorted(before['schema'] + schema['objects'], key=lambda r: r[:2]),
         'schema_delta_not_exact')
    need(after['userVersion'] == before['userVersion'] and after['applicationId'] == before['applicationId'],
         'database_version_changed')
    for name, rows in before['rows'].items():
        need(after['columns'][name] == before['columns'][name] and
             shared.migration.rows_digest(after['rows'][name]) == shared.migration.rows_digest(rows),
             'old_rows_columns_or_sequences_changed')
    need(all(not after['rows'][n] for n in NEW_TABLES), 'new_tables_not_empty')
    return {'originalTablesPreserved': 73, 'newTables': 2, 'newTablesEmpty': True,
            'oldRowsSchemaAndSequencesPreserved': True}


def initialize_database(path, schema):
    need(schema_definition() == schema, 'journey_finance_source_changed')
    with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=0)) as con:
        con.execute('PRAGMA trusted_schema=OFF')
        con.execute('PRAGMA foreign_keys=ON')
        con.execute('BEGIN IMMEDIATE')
        try:
            runtime_module('journey_finance').init_schema(con)
            need(con.in_transaction, 'initializer_committed_transaction')
            con.commit()
        except BaseException:
            con.rollback()
            raise
    shared.migration.no_sidecars(path)


def begin(root, proof, **kwargs):
    # Existing backup core, distinct attempt kind, no app startup or data writes.
    return backup_core.begin(root, proof, spec=BEGIN_SPEC, **kwargs)


def evidence(root, proof, *, source_identity, plan_sha256, marker_sha256=MEMBERSHIP_MARKER_SHA256):
    root, proof = shared._directory(root), shared._directory(proof)
    need(not root.is_relative_to(proof) and not proof.is_relative_to(root), 'proof_must_be_external')
    before = shared._read_json(shared.migration.checked_path(proof / 'before.json'))
    identity = shared._source_identity(source_identity)
    attempt = shared._read_json(shared.migration.checked_path(proof / 'attempt.json'))
    need(attempt == {'kind': BEGIN_SPEC.attempt_kind, 'planSha256': plan_sha256,
        'beforeSha256': shared._digest(before), 'sourceIdentity': identity,
        'sourceIdentitySha256': shared._digest(identity), 'markerSha256': marker_sha256}, 'journey_finance_attempt_binding')
    need(marker_digest(root) == marker_sha256, 'successful_membership_marker_changed')
    receipt = shared._read_json(shared.migration.checked_path(proof / 'backup.json'))
    manifest = shared._relative(proof / 'backup-group/backups', receipt['manifest'])
    backup, paths = backup_core._backup(root, before, manifest, spec=BEGIN_SPEC)
    need(backup == shared._read_json(proof / 'backup-verified.json'), 'retained_backup_changed')
    schema = schema_definition()
    need(all(identity['sourceHashes'].get(n) == digest and identity['runtimeHashes'].get(n) == digest
             for n, digest in schema['sourceHashes'].items()), 'schema_source_identity_changed')
    return root, proof, before, identity, paths, schema


def verify_group(root, before, paths, schema):
    after = shared.snapshot(root)
    need(after['rootSha256'] == before['rootSha256'] and set(after['databases']) == set(before['databases']),
         'registry_group_changed')
    comparisons = {}
    for name, backup in paths.items():
        old = shared.migration._read(backup)
        new = shared.migration._read(shared._relative(root, name))
        if name == 'platform.sqlite3':
            need({k: v for k, v in old.items() if k != 'fileSha256'} ==
                 {k: v for k, v in new.items() if k != 'fileSha256'}, 'platform_changed')
        else:
            comparisons[name] = verify_addition(old, new, schema)
    need(shared.snapshot(root) == after, 'group_changed_during_verification')
    return after, comparisons


def migration_identity(before, identity, schema, plan_sha256):
    return {'planSha256': plan_sha256, 'beforeSha256': shared._digest(before),
            'sourceIdentitySha256': shared._digest(identity), 'schemaSha256': schema['sha256']}


def migrate(root, proof, **kwargs):
    root, proof, before, identity, paths, schema = evidence(root, proof, **kwargs)
    need(snapshot_baseline(root) == before, 'database_changed_after_backup')
    record = migration_identity(before, identity, schema, kwargs['plan_sha256'])
    shared._write_new(proof / 'migration-attempt.json', record)
    for name in sorted(paths):
        if name != 'platform.sqlite3':
            initialize_database(shared._relative(root, name), schema)
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
    need(attempt == migration_identity(before, identity, schema, kwargs['plan_sha256']), 'migration_binding_changed')
    migrated = shared._read_json(shared.migration.checked_path(proof / 'migrated.json'))
    result_before = shared._read_json(shared.migration.checked_path(proof / 'migration-result.json'))
    after, comparisons = verify_group(root, before, paths, schema)
    digest = shared._digest(shared._logical(after))
    need(shared._logical(after) == shared._logical(migrated) and result_before['logicalSha256'] == digest
         and result_before['verified'] is True
         and all(result_before.get(k) == v for k, v in attempt.items()), 'app_startup_changed_data')
    evidence(root, proof, **kwargs)
    result = {'verified': True, 'households': after['households'], 'databases': len(paths),
              'logicalSha256': digest, 'markerSha256': kwargs.get('marker_sha256', MEMBERSHIP_MARKER_SHA256),
              'planSha256': kwargs['plan_sha256'], 'sourceIdentitySha256': shared._digest(identity),
              'comparisons': comparisons}
    shared._write_new(proof / 'after.json', after)
    shared._write_new(proof / 'result.json', result)
    return result


def snapshot_current(root):
    """Read a complete populated 75/9 group; retain allocations, receipts and every previous record."""
    root = shared._directory(root)
    schema, result = schema_definition(), shared.snapshot(root)
    platform = result['databases']['platform.sqlite3']
    need(platform['membershipPhase'] == 'after' and platform['userVersion'] == 1, 'platform_profile_changed')
    for name in result['databases']:
        if name != 'platform.sqlite3':
            verify_current(shared.migration._read(shared._relative(root, name)), schema)
    need(shared.snapshot(root) == result, 'group_changed_during_snapshot')
    return result


def verify_restore(reference, restored_root, *, marker_sha256=MEMBERSHIP_MARKER_SHA256):
    current = snapshot_current(restored_root)
    need(shared._logical(current) == shared._logical(reference), 'restored_group_changed')
    need(marker_digest(restored_root) == marker_sha256, 'successful_membership_marker_changed')
    return {'verified': True, 'households': current['households'], 'databases': len(current['databases']),
            'completeGroupRestored': True, 'logicalSha256': shared._digest(shared._logical(current))}


def verify_rollback(proof, restored_root):
    """Read-only verification of full 73/9 rollback; never invalidate retained receipts."""
    proof = shared._directory(proof)
    before = shared._read_json(shared.migration.checked_path(proof / 'before.json'))
    baseline.SPEC.profile(before)
    attempt = shared._read_json(shared.migration.checked_path(proof / 'attempt.json'))
    need(attempt['beforeSha256'] == shared._digest(before), 'rollback_reference_changed')
    return baseline.verify_restore(before, restored_root, marker_sha256=attempt['markerSha256'])
