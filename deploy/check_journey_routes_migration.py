"""Stopped complete-group 66/9 -> 69/9 migration using the route module's DDL.

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
from deploy import assistant_trip_change_release_data as baseline
from deploy import check_finance_analysis_migration as finance

ROOT = Path(__file__).resolve().parents[1]
BASE_TABLES = finance.BASE_TABLES | finance.NEW_TABLES
NEW_TABLES = frozenset({'journey_routes', 'journey_route_stops', 'journey_route_operations'})
NEW_INDEXES = frozenset({'journey_routes_owner', 'journey_routes_journey'})
SCHEMA_SHA256 = '2752b5ccc249cc78b84deb515bc6077452d9fc90606b6fd6bb14aac913038304'
MEMBERSHIP_MARKER_SHA256 = baseline.MEMBERSHIP_MARKER_SHA256
marker_digest = baseline.marker_digest
need = shared.need


def route_module():
    module = importlib.import_module('journey_routes')
    expected = shared.migration.checked_path(ROOT / 'journey_routes.py')
    actual = shared.migration.checked_path(module.__file__)
    # Production data_call binds /release and imports runtime from /app first.
    # Admit exactly that layout (or the local source), with identical bytes.
    allowed = {expected}
    if ROOT == Path('/release'):
        allowed.add(Path('/app/journey_routes.py'))
    need(actual in allowed and actual.read_bytes() == expected.read_bytes(), 'route_module_import_changed')
    return module


def schema_definition():
    """Use the actual module constant and initializer, never a copied DDL string."""
    module = route_module()
    sql = module.SCHEMA_SQL
    need(isinstance(sql, str) and bool(sql.strip()), 'schema_constant_missing')
    need(hashlib.sha256(sql.encode()).hexdigest() == SCHEMA_SHA256, 'reviewed_schema_changed')
    tables, indexes = [], []
    for statement in (s.strip() for s in sql.split(';') if s.strip()):
        table = re.match(r'CREATE TABLE IF NOT EXISTS ([a-z_]+)\s*\(', statement)
        index = re.match(r'CREATE INDEX IF NOT EXISTS ([a-z_]+)\s+ON\s+([a-z_]+)\s*\(', statement)
        need(table is not None or index is not None, 'unexpected_schema_statement')
        need((table[1] if table else index[2]) in NEW_TABLES, 'unexpected_schema_target')
        (tables if table else indexes).append(table[1] if table else index[1])
    need(len(tables) == 3 and set(tables) == NEW_TABLES and len(indexes) == 2
         and set(indexes) == NEW_INDEXES, 'unexpected_route_schema')
    with closing(sqlite3.connect(':memory:')) as con:
        con.execute('PRAGMA foreign_keys=ON')
        for parent in ('users', 'journey_workflows', 'journey_places'):
            con.execute('CREATE TABLE ' + parent + '(id TEXT PRIMARY KEY)')
        parents = shared.migration.objects(con)
        con.execute('BEGIN IMMEDIATE')
        module.initialize_journey_routes(con)
        need(con.in_transaction, 'initializer_committed_transaction')
        objects = [r for r in shared.migration.objects(con) if r not in parents]
        need(all(r[0] in ('table', 'index') and r[2] in NEW_TABLES for r in objects),
             'unexpected_schema_object')
        columns = {n: con.execute('PRAGMA table_xinfo(' + n + ')').fetchall() for n in NEW_TABLES}
        con.rollback()
        need(shared.migration.objects(con) == parents, 'initializer_not_atomic')
    return {'profile': 'journey_routes69', 'sql': sql, 'sha256': SCHEMA_SHA256,
            'sourceHashes': {'journey_routes.py': shared.migration.file_digest(ROOT / 'journey_routes.py')},
            'tables': sorted(NEW_TABLES), 'objects': objects, 'columns': columns}


def verify_baseline(value):
    need(len(BASE_TABLES) == 66, 'baseline_definition_changed')
    finance.verify_current(value, finance.schema_definition())


def verify_current(value, schema):
    need({n for n in value['rows'] if not n.startswith('sqlite_')} == BASE_TABLES | NEW_TABLES,
         'expected_69_table_profile')
    need([r for r in value['schema'] if r[2] in NEW_TABLES] == schema['objects'], 'route_schema_changed')
    need(all(value['columns'][n] == schema['columns'][n] for n in NEW_TABLES), 'route_columns_changed')
    old = dict(value, schema=[r for r in value['schema'] if r[2] not in NEW_TABLES],
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
    return {'originalTablesPreserved': 66, 'newTables': 3, 'newTablesEmpty': True,
            'oldRowsSchemaAndSequencesPreserved': True}


def initialize_database(path, schema):
    module = route_module()
    need(module.SCHEMA_SQL == schema['sql'] and
         shared.migration.file_digest(ROOT / 'journey_routes.py') == schema['sourceHashes']['journey_routes.py'],
         'route_source_changed')
    with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=0)) as con:
        con.execute('PRAGMA trusted_schema=OFF')
        con.execute('PRAGMA foreign_keys=ON')
        con.execute('BEGIN IMMEDIATE')
        try:
            module.initialize_journey_routes(con)
            need(con.in_transaction, 'initializer_committed_transaction')
            con.commit()
        except BaseException:
            con.rollback()
            raise
    shared.migration.no_sidecars(path)


def begin(root, proof, **kwargs):
    # The original exclusive source-update attempt is deliberately retained.
    # It admits populated 66/9, backs up every registry DB and closes only empty WAL.
    return baseline.begin(root, proof, **kwargs)


def evidence(root, proof, *, source_identity, plan_sha256, marker_sha256=MEMBERSHIP_MARKER_SHA256):
    root, proof = shared._directory(root), shared._directory(proof)
    need(not root.is_relative_to(proof) and not proof.is_relative_to(root), 'proof_must_be_external')
    before = shared._read_json(shared.migration.checked_path(proof / 'before.json'))
    identity = shared._source_identity(source_identity)
    attempt = shared._read_json(shared.migration.checked_path(proof / 'attempt.json'))
    need(attempt == {'kind': 'assistant-trip-change-release-attempt', 'planSha256': plan_sha256,
        'beforeSha256': shared._digest(before), 'sourceIdentity': identity,
        'sourceIdentitySha256': shared._digest(identity), 'markerSha256': marker_sha256}, 'route_attempt_binding')
    need(marker_digest(root) == marker_sha256, 'successful_membership_marker_changed')
    receipt = shared._read_json(shared.migration.checked_path(proof / 'backup.json'))
    manifest = shared._relative(proof / 'backup-group/backups', receipt['manifest'])
    backup, paths = baseline._backup(root, before, manifest)
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
    need(baseline.snapshot(root) == before, 'database_changed_after_backup')
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
    """Read a complete populated 69/9 group; retain routes and operation receipts."""
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
    """Read-only verification of full 66/9 rollback; never invalidate retained receipts."""
    proof = shared._directory(proof)
    before = shared._read_json(shared.migration.checked_path(proof / 'before.json'))
    baseline._profile(before)
    attempt = shared._read_json(shared.migration.checked_path(proof / 'attempt.json'))
    need(attempt['beforeSha256'] == shared._digest(before), 'rollback_reference_changed')
    return baseline.verify_restore(before, restored_root, marker_sha256=attempt['markerSha256'])
