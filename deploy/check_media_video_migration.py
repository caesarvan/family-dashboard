"""Stopped complete-group 71/9 -> 73/9 migration using both video runtime DDL constants.

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
from deploy import calendar_privacy_release_data as baseline
from deploy import assistant_trip_change_release_data as backup_core
from deploy import check_task_reminders_migration as reminders

ROOT = Path(__file__).resolve().parents[1]
BASE_TABLES = reminders.BASE_TABLES | reminders.NEW_TABLES
NEW_TABLES = frozenset({'media_video_cache', 'media_playback_progress'})
TRIGGER = 'media_video_deleted'
SCHEMA_HASHES = {
    'media_video_storage': 'a36509e46c9baaa1a780ac7cd2e9951f63c04ba5df3a6f29e0c37fad7b15284f',
    'media_playback_progress': 'a9302203d12100c21e6a93c839b1c3444c26e781e8cee1646494b21375a4fbee',
}
SOURCE_MODULES = (*SCHEMA_HASHES, 'media_crypto')
MEMBERSHIP_MARKER_SHA256 = baseline.MEMBERSHIP_MARKER_SHA256
marker_digest = baseline.marker_digest
need = shared.need


def runtime_module(name):
    need(name in SOURCE_MODULES, 'unexpected_video_module')
    module = importlib.import_module(name)
    expected = shared.migration.checked_path(ROOT / (name + '.py'))
    actual = shared.migration.checked_path(module.__file__)
    allowed = {expected}
    if ROOT == Path('/release'):
        allowed.add(Path('/app') / (name + '.py'))
    need(actual in allowed and actual.read_bytes() == expected.read_bytes(), 'video_module_import_changed')
    return module


def _statements(sql):
    # A trigger contains an internal semicolon: never split SQL on ';'.
    pending, result = '', []
    for line in sql.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            result.append(pending.strip())
            pending = ''
    need(not pending.strip(), 'incomplete_video_schema')
    return result


def _execute_schema(con, sql):
    for statement in _statements(sql):
        con.execute(statement)


def _new_object(row):
    # The tombstone trigger belongs to OLD media_items, not a new table.
    return row[2] in NEW_TABLES or row[1] == TRIGGER


def schema_definition():
    modules = {name: runtime_module(name) for name in SOURCE_MODULES}
    sqls = {name: modules[name].SCHEMA_SQL for name in SCHEMA_HASHES}
    need(all(isinstance(sql, str) and hashlib.sha256(sql.encode()).hexdigest() == SCHEMA_HASHES[name]
             for name, sql in sqls.items()), 'reviewed_schema_changed')
    sql = '\n'.join(sqls.values())
    statements = _statements(sql)
    names = []
    for statement in statements:
        match = re.match(r'CREATE (TABLE|TRIGGER)(?: IF NOT EXISTS)? ([a-z_]+)\b', statement)
        need(match is not None, 'unexpected_schema_statement')
        names.append((match[1], match[2]))
    need(names == [('TABLE', 'media_video_cache'), ('TRIGGER', TRIGGER),
                   ('TABLE', 'media_playback_progress')], 'unexpected_video_schema')
    with closing(sqlite3.connect(':memory:')) as con:
        con.execute('PRAGMA foreign_keys=ON')
        con.execute('CREATE TABLE media_items(id TEXT PRIMARY KEY, state TEXT)')
        con.execute('CREATE TABLE media_playback(device_id TEXT PRIMARY KEY)')
        parents = shared.migration.objects(con)
        con.execute('BEGIN IMMEDIATE')
        _execute_schema(con, sql)
        need(con.in_transaction, 'initializer_committed_transaction')
        objects = [row for row in shared.migration.objects(con) if row not in parents]
        need(all((row[0] in ('table', 'index') and row[2] in NEW_TABLES) or
                 (row[0], row[1], row[2]) == ('trigger', TRIGGER, 'media_items') for row in objects),
             'unexpected_schema_object')
        need(sum(row[0] == 'trigger' for row in objects) == 1, 'tombstone_trigger_missing')
        columns = {name: con.execute('PRAGMA table_xinfo(' + name + ')').fetchall() for name in NEW_TABLES}
        con.rollback()
        need(shared.migration.objects(con) == parents, 'initializer_not_atomic')
    return {'profile': 'media_video73', 'sql': sql, 'sha256': shared._digest(SCHEMA_HASHES),
            'sourceHashes': {name + '.py': shared.migration.file_digest(ROOT / (name + '.py'))
                             for name in SOURCE_MODULES},
            'tables': sorted(NEW_TABLES), 'objects': objects, 'columns': columns}


def verify_baseline(value):
    need(len(BASE_TABLES) == 71, 'baseline_definition_changed')
    need(not any(_new_object(row) for row in value['schema']), 'video_object_already_exists')
    reminders.verify_current(value, reminders.schema_definition())


def snapshot_baseline(root):
    result = baseline.snapshot_current(root)
    for name in result['databases']:
        if name != 'platform.sqlite3':
            verify_baseline(shared.migration._read(shared._relative(Path(root), name)))
    need(baseline.snapshot_current(root) == result, 'baseline_changed_during_snapshot')
    return result


BEGIN_SPEC = backup_core.DataSpec(baseline.SPEC.profile, snapshot_baseline, 'media-video-migration-attempt')


def verify_current(value, schema):
    need({n for n in value['rows'] if not n.startswith('sqlite_')} == BASE_TABLES | NEW_TABLES,
         'expected_73_table_profile')
    need([r for r in value['schema'] if _new_object(r)] == schema['objects'], 'video_schema_changed')
    need(all(value['columns'][n] == schema['columns'][n] for n in NEW_TABLES), 'video_columns_changed')
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
    return {'originalTablesPreserved': 71, 'newTables': 2, 'newTablesEmpty': True,
            'oldRowsSchemaAndSequencesPreserved': True}


def initialize_database(path, schema):
    need(schema_definition() == schema, 'video_source_changed')
    with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=0)) as con:
        con.execute('PRAGMA trusted_schema=OFF')
        con.execute('PRAGMA foreign_keys=ON')
        con.execute('BEGIN IMMEDIATE')
        try:
            _execute_schema(con, schema['sql'])
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
        'sourceIdentitySha256': shared._digest(identity), 'markerSha256': marker_sha256}, 'video_attempt_binding')
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
    """Read a complete populated 73/9 group; retain caches, playheads and all previous records."""
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
    """Read-only verification of full 71/9 rollback; never invalidate retained receipts."""
    proof = shared._directory(proof)
    before = shared._read_json(shared.migration.checked_path(proof / 'before.json'))
    baseline.SPEC.profile(before)
    attempt = shared._read_json(shared.migration.checked_path(proof / 'attempt.json'))
    need(attempt['beforeSha256'] == shared._digest(before), 'rollback_reference_changed')
    return baseline.verify_restore(before, restored_root, marker_sha256=attempt['markerSha256'])
