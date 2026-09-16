"""Explicit 53 -> 54 finance-receipt migration after all writers stop.

Only the reviewed finance schema constant is used. No application factory,
worker, network request or automatic restore is started. Each household DDL
is atomic; an interrupted group requires inspection, never blind replay.
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

import finance_hub
from deploy import check_inventory_migration as inventory
from deploy import check_media_migration as media

ROOT = Path(__file__).resolve().parents[1]
BASE_TABLES = frozenset(inventory.BASE_TABLES | inventory.NEW_TABLES)
NEW_TABLES = frozenset({'hub_import_receipts'})
need, snapshot, validate_backup = media.need, media.snapshot, media.validate_backup


def schema_definition():
    source = ROOT / 'finance_hub.py'
    need(source.is_file() and not source.is_symlink(), 'schema_source_missing')
    need(Path(finance_hub.__file__).resolve() == source.resolve(), 'schema_module_origin')
    sql = getattr(finance_hub, 'FINANCE_IMPORT_RECEIPTS_SCHEMA_SQL', None)
    need(isinstance(sql, str) and sql.strip(), 'receipt_schema_constant_missing')
    with closing(sqlite3.connect(':memory:')) as con:
        # This addition contains one CREATE TABLE. execute refuses a second
        # statement, so an altered payload cannot run auxiliary SQL here.
        con.execute(sql)
        objects = con.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall()
        need({r[1] for r in objects if r[0] == 'table'} == NEW_TABLES, 'unexpected_new_tables')
        need(all(r[2] in NEW_TABLES for r in objects), 'unexpected_schema_target')
        columns = [list(row) for row in con.execute('PRAGMA table_xinfo(hub_import_receipts)')]
        foreign_keys = [list(row) for row in con.execute('PRAGMA foreign_key_list(hub_import_receipts)')]
    return {'profile': 'finance_receipts54', 'sql': sql,
            'sha256': hashlib.sha256(sql.encode('utf-8')).hexdigest(),
            'sourceSha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'tables': sorted(NEW_TABLES), 'objects': [list(r) for r in objects],
            'columns': columns, 'foreignKeys': foreign_keys}


def verify_baseline(before):
    need(len(BASE_TABLES) == 53, 'baseline_definition_changed')
    need(before['households'], 'empty_household_group')
    for value in before['households'].values():
        actual = {name for name in value['tables'] if not name.startswith('sqlite_')}
        need(actual == BASE_TABLES, 'expected_53_table_baseline')


def verify_current(current, schema):
    """Validate a populated 54-table snapshot, without requiring empty receipts."""
    need(schema == schema_definition(), 'schema_changed_after_review')
    need(current['households'], 'empty_household_group')
    for value in current['households'].values():
        actual = {name for name in value['tables'] if not name.startswith('sqlite_')}
        need(actual == BASE_TABLES | NEW_TABLES, 'expected_54_table_snapshot')
        addition = [row for row in value['schema'] if row[2] in NEW_TABLES]
        need(addition == schema['objects'], 'receipt_schema_changed')
        table = value['tables']['hub_import_receipts']
        need(table['columns'] == schema['columns'] and table['foreignKeys'] == schema['foreignKeys'], 'receipt_columns_or_foreign_keys_changed')
    return {'profile': 'finance_receipts54', 'households': len(current['households']),
            'tablesPerHousehold': 54, 'receiptRows': sum(v['tables']['hub_import_receipts']['count'] for v in current['households'].values())}


def verify_addition(before, after, schema):
    verify_baseline(before)
    verify_current(after, schema)
    need(before['registry'] == after['registry'], 'registry_changed')
    need(set(before['households']) == set(after['households']), 'household_group_changed')
    addition = {r[1]: r for r in schema['objects']}
    for uid, old in before['households'].items():
        new = after['households'][uid]
        need(set(new['tables']) == set(old['tables']) | NEW_TABLES, 'table_set_changed')
        # sqlite_sequence is part of this comparison, not merely table count.
        need(all(new['tables'][name] == value for name, value in old['tables'].items()), 'original_data_or_columns_changed')
        old_objects = {r[1]: r for r in old['schema']}
        new_objects = {r[1]: r for r in new['schema']}
        need(not (set(old_objects) & set(addition)), 'new_object_name_collides')
        need(new_objects == {**old_objects, **addition}, 'schema_change_not_exact_addition')
        need(new['tables']['hub_import_receipts']['count'] == 0, 'new_table_not_empty')
    return {'originalTablesPreserved': 53, 'newTables': 1, 'households': len(before['households']),
            'newTableEmpty': True, 'oldRowsSchemaAndSequencesPreserved': True, 'registryPreserved': True}


def verify_restore(reference, restored, schema):
    profile = verify_current(reference, schema)
    verify_current(restored, schema)
    need(reference['registry'] == restored['registry'], 'restored_registry_changed')
    need(set(reference['households']) == set(restored['households']), 'restored_household_group_changed')
    need(reference == restored, 'restored_data_schema_or_sequences_changed')
    return {**profile, 'completeGroupRestored': True, 'allRowsSchemaAndSequencesPreserved': True}


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
    parser.add_argument('action', choices=('snapshot', 'snapshot-current', 'validate-backup', 'migrate', 'check', 'check-restored'))
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--before', type=Path)
    parser.add_argument('--backup', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    need(not args.output.exists() and not args.output.is_symlink() and args.output.parent.is_dir(), 'output_must_be_new')
    schema = schema_definition()
    before = json.loads(args.before.read_text(encoding='utf-8')) if args.before else None
    backup = json.loads(args.backup.read_text(encoding='utf-8')) if args.backup else None
    if args.action in ('snapshot', 'snapshot-current'):
        result = snapshot(args.data_root)
        verify_baseline(result) if args.action == 'snapshot' else verify_current(result, schema)
    elif args.action == 'validate-backup':
        need(before is not None and backup is not None, 'snapshot_and_backup_required')
        if all('hub_import_receipts' in value['tables'] for value in before['households'].values()):
            verify_current(before, schema)
        else:
            verify_baseline(before)
        need(snapshot(args.data_root) == before, 'database_changed_after_snapshot')
        result = validate_backup(args.data_root, before, backup)
    elif args.action == 'migrate':
        need(before is not None and backup is not None, 'snapshot_and_backup_required')
        result = migrate(args.data_root, before, backup, schema)
    elif args.action == 'check-restored':
        need(before is not None, 'snapshot_required')
        result = verify_restore(before, snapshot(args.data_root), schema)
    else:
        need(before is not None, 'snapshot_required')
        result = verify_addition(before, snapshot(args.data_root), schema)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    args.output.chmod(0o600)
    print(json.dumps({'action': args.action, 'profile': schema['profile'], 'schemaSha256': schema['sha256'], 'verified': True}))


if __name__ == '__main__':
    main()
