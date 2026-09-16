"""Explicit 48 -> 53 inventory addition after all writers have been stopped.

Only the inventory domain schema is imported; no Flask factory, cloud service,
worker or restore is started. An interrupted multi-household run needs operator
inspection, never automatic replay or backup restoration.
"""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import inventory_core as core
from deploy import check_media_migration as media

ROOT = Path(__file__).resolve().parents[1]
BASE_TABLES = media.BASE_TABLES | {'media_imports', 'media_items', 'media_tv_grants', 'media_playback'}
NEW_TABLES = frozenset(core.LIMITS)
need, snapshot, validate_backup = media.need, media.snapshot, media.validate_backup


def schema_definition():
    source = ROOT / 'inventory_core.py'
    need(source.is_file() and not source.is_symlink(), 'schema_source_missing')
    # The domain builds capacity triggers from LIMITS; using only its initial
    # literal SCHEMA_SQL would silently omit those reviewed constraints.
    sql = core.SCHEMA_SQL
    with closing(sqlite3.connect(':memory:')) as con:
        con.executescript(sql)
        objects = con.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall()
        need({r[1] for r in objects if r[0] == 'table'} == NEW_TABLES, 'unexpected_new_tables')
        need(all(r[2] in NEW_TABLES for r in objects), 'unexpected_schema_target')
    return {'profile': 'inventory53', 'sql': sql, 'sha256': hashlib.sha256(sql.encode()).hexdigest(),
            'sourceSha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'tables': sorted(NEW_TABLES), 'objects': [list(r) for r in objects]}


def verify_baseline(before):
    need(before['households'], 'empty_household_group')
    for value in before['households'].values():
        actual = {name for name in value['tables'] if not name.startswith('sqlite_')}
        need(actual == BASE_TABLES, 'expected_48_table_baseline')


def verify_addition(before, after, schema):
    verify_baseline(before)
    need(schema == schema_definition(), 'schema_changed_after_review')
    need(before['registry'] == after['registry'], 'registry_changed')
    need(set(before['households']) == set(after['households']), 'household_group_changed')
    addition = {r[1]: r for r in schema['objects']}
    for uid, old in before['households'].items():
        new = after['households'][uid]
        need(set(new['tables']) == set(old['tables']) | NEW_TABLES, 'table_set_changed')
        need(all(new['tables'][name] == value for name, value in old['tables'].items()), 'original_data_or_columns_changed')
        old_objects = {r[1]: r for r in old['schema']}
        new_objects = {r[1]: r for r in new['schema']}
        need(not (set(old_objects) & set(addition)), 'new_object_name_collides')
        need(new_objects == {**old_objects, **addition}, 'schema_change_not_exact_addition')
        need(all(new['tables'][name]['count'] == 0 for name in NEW_TABLES), 'new_table_not_empty')
    return {'originalTablesPreserved': 48, 'newTables': 5, 'households': len(before['households']),
            'newTablesEmpty': True, 'oldRowsSchemaAndSequencesPreserved': True}


def migrate(root, before, backup, schema):
    root = Path(root).resolve(strict=True)
    need(schema == schema_definition(), 'schema_changed_after_review')
    verify_baseline(before)
    need(snapshot(root) == before, 'database_changed_after_snapshot')
    validate_backup(root, before, backup)
    for uid in sorted(before['households']):
        media.legacy.initialize_database(media.checked_path(root, media.relative_database(uid)), schema['sql'])
    return verify_addition(before, snapshot(root), schema)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('snapshot', 'validate-backup', 'migrate', 'check'))
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--before', type=Path)
    parser.add_argument('--backup', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    need(not args.output.exists() and not args.output.is_symlink() and args.output.parent.is_dir(), 'output_must_be_new')
    schema = schema_definition()
    before = json.loads(args.before.read_text(encoding='utf-8')) if args.before else None
    backup = json.loads(args.backup.read_text(encoding='utf-8')) if args.backup else None
    if args.action == 'snapshot':
        result = snapshot(args.data_root)
        verify_baseline(result)
    elif args.action == 'validate-backup':
        need(before is not None and backup is not None, 'snapshot_and_backup_required')
        verify_baseline(before)
        need(snapshot(args.data_root) == before, 'database_changed_after_snapshot')
        result = validate_backup(args.data_root, before, backup)
    elif args.action == 'migrate':
        need(before is not None and backup is not None, 'snapshot_and_backup_required')
        result = migrate(args.data_root, before, backup, schema)
    else:
        need(before is not None, 'snapshot_required')
        result = verify_addition(before, snapshot(args.data_root), schema)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    args.output.chmod(0o600)
    print(json.dumps({'action': args.action, 'profile': schema['profile'], 'schemaSha256': schema['sha256'], 'verified': True}))


if __name__ == '__main__':
    main()
