"""Explicit stopped-writer 55 -> 58 manual-account migration.

Only the reviewed three-table schema is applied, atomically per household.
This command never starts an application, worker, backup or restore. Interrupted
groups require inspection and an explicit complete-group rollback, not replay.
"""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import finance_accounts
from deploy import check_investment_operation_migration as previous
from deploy import check_media_migration as media

ROOT = Path(__file__).resolve().parents[1]
BASE_TABLES = frozenset(previous.BASE_TABLES | previous.NEW_TABLES)
NEW_TABLES = frozenset({'finance_accounts', 'finance_account_valuations', 'finance_account_operations'})
need, snapshot, validate_backup = media.need, media.snapshot, media.validate_backup


def schema_definition():
    source = ROOT / 'finance_accounts.py'
    need(source.is_file() and not source.is_symlink(), 'schema_source_missing')
    need(Path(finance_accounts.__file__).resolve() == source.resolve(), 'schema_module_origin')
    sql = getattr(finance_accounts, 'FINANCE_ACCOUNTS_SCHEMA_SQL', None)
    need(isinstance(sql, str) and sql.strip(), 'account_schema_constant_missing')
    statements = [value.strip() for value in sql.split(';') if value.strip()]
    # This reviewed constant has three simple CREATE TABLE statements. Refuse
    # auxiliary SQL, including transactions, writes, PRAGMAs or extra objects.
    names = []
    for statement in statements:
        match = re.match(r'CREATE TABLE IF NOT EXISTS ([a-z_]+)\s*\(', statement)
        need(match is not None, 'unexpected_schema_statement')
        names.append(match[1])
    need(len(names) == 3 and set(names) == NEW_TABLES, 'unexpected_new_tables')
    with closing(sqlite3.connect(':memory:')) as con:
        for statement in statements:
            con.execute(statement)
        objects = con.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall()
        need({r[1] for r in objects if r[0] == 'table'} == NEW_TABLES, 'unexpected_new_tables')
        need(all(r[2] in NEW_TABLES and r[0] in ('table', 'index') for r in objects), 'unexpected_schema_target')
        columns = {name: [list(r) for r in con.execute('PRAGMA table_xinfo(' + name + ')')] for name in sorted(NEW_TABLES)}
        foreign_keys = {name: [list(r) for r in con.execute('PRAGMA foreign_key_list(' + name + ')')] for name in sorted(NEW_TABLES)}
    return {'profile': 'finance_accounts58', 'sql': sql,
            'sha256': hashlib.sha256(sql.encode('utf-8')).hexdigest(),
            'sourceSha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'tables': sorted(NEW_TABLES), 'objects': [list(r) for r in objects],
            'columns': columns, 'foreignKeys': foreign_keys}


def verify_baseline(before):
    need(len(BASE_TABLES) == 55, 'baseline_definition_changed')
    previous.verify_current(before, previous.schema_definition())
    need(before['households'], 'empty_household_group')
    for value in before['households'].values():
        need({n for n in value['tables'] if not n.startswith('sqlite_')} == BASE_TABLES, 'expected_55_table_baseline')


def verify_current(current, schema):
    """Validate the 58-table profile, including legitimately populated additions."""
    need(schema == schema_definition(), 'schema_changed_after_review')
    need(current['households'], 'empty_household_group')
    original = {'registry': current['registry'], 'households': {}}
    for uid, value in current['households'].items():
        need({n for n in value['tables'] if not n.startswith('sqlite_')} == BASE_TABLES | NEW_TABLES, 'expected_58_table_snapshot')
        need([r for r in value['schema'] if r[2] in NEW_TABLES] == schema['objects'], 'account_schema_changed')
        for name in NEW_TABLES:
            table = value['tables'][name]
            need(table['columns'] == schema['columns'][name] and table['foreignKeys'] == schema['foreignKeys'][name], 'account_columns_or_foreign_keys_changed')
        original['households'][uid] = {'tables': {k: v for k, v in value['tables'].items() if k not in NEW_TABLES},
            'schema': [r for r in value['schema'] if r[2] not in NEW_TABLES]}
    verify_baseline(original)
    return {'profile': 'finance_accounts58', 'households': len(current['households']), 'tablesPerHousehold': 58,
            'newTableRows': {name: sum(v['tables'][name]['count'] for v in current['households'].values()) for name in sorted(NEW_TABLES)}}


def verify_no_collisions(before, schema):
    addition = {r[1] for r in schema['objects']}
    for value in before['households'].values():
        need(not ({r[1] for r in value['schema']} & addition), 'new_object_name_collides')


def verify_addition(before, after, schema):
    verify_baseline(before)
    verify_no_collisions(before, schema)
    verify_current(after, schema)
    need(before['registry'] == after['registry'], 'registry_changed')
    need(set(before['households']) == set(after['households']), 'household_group_changed')
    addition = {r[1]: r for r in schema['objects']}
    for uid, old in before['households'].items():
        new = after['households'][uid]
        need(set(new['tables']) == set(old['tables']) | NEW_TABLES, 'table_set_changed')
        # Includes sqlite_sequence, all rows, column definitions and foreign keys.
        need(all(new['tables'][name] == value for name, value in old['tables'].items()), 'original_data_or_columns_changed')
        need({r[1]: r for r in new['schema']} == {**{r[1]: r for r in old['schema']}, **addition}, 'schema_change_not_exact_addition')
        need(all(new['tables'][name]['count'] == 0 for name in NEW_TABLES), 'new_tables_not_empty')
    return {'originalTablesPreserved': 55, 'newTables': 3, 'households': len(before['households']),
            'newTablesEmpty': True, 'oldRowsSchemaAndSequencesPreserved': True, 'registryPreserved': True}


def verify_restore(reference, restored, schema):
    profile = verify_current(reference, schema)
    verify_current(restored, schema)
    need(reference == restored, 'restored_data_schema_or_sequences_changed')
    return {**profile, 'completeGroupRestored': True, 'allRowsSchemaAndSequencesPreserved': True}


def verify_rollback(reference, restored):
    """Verify a complete restored 55-table group; does not perform the restore."""
    verify_baseline(reference)
    verify_baseline(restored)
    need(reference == restored, 'rolled_back_data_schema_or_sequences_changed')
    return {'profile': 'investment_operations55', 'households': len(reference['households']),
            'tablesPerHousehold': 55, 'completeGroupRestored': True, 'allRowsSchemaAndSequencesPreserved': True}


def migrate(root, before, backup, schema):
    root = Path(root).resolve(strict=True)
    need(schema == schema_definition(), 'schema_changed_after_review')
    verify_baseline(before)
    verify_no_collisions(before, schema)
    need(snapshot(root) == before, 'database_changed_after_snapshot')
    validate_backup(root, before, backup)
    for uid in sorted(before['households']):
        media.legacy.initialize_database(media.checked_path(root, media.relative_database(uid)), schema['sql'])
    result = verify_addition(before, snapshot(root), schema)
    validate_backup(root, before, backup)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('snapshot', 'snapshot-current', 'validate-backup', 'migrate', 'check', 'check-restored', 'check-rollback'))
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
        if before['households'] and all(NEW_TABLES <= value['tables'].keys() for value in before['households'].values()):
            verify_current(before, schema)
        else:
            verify_baseline(before)
        need(snapshot(args.data_root) == before, 'database_changed_after_snapshot')
        result = validate_backup(args.data_root, before, backup)
    elif args.action == 'migrate':
        need(before is not None and backup is not None, 'snapshot_and_backup_required')
        result = migrate(args.data_root, before, backup, schema)
    else:
        need(before is not None, 'snapshot_required')
        current = snapshot(args.data_root)
        if args.action == 'check-restored': result = verify_restore(before, current, schema)
        elif args.action == 'check-rollback': result = verify_rollback(before, current)
        else: result = verify_addition(before, current, schema)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    args.output.chmod(0o600)
    print(json.dumps({'action': args.action, 'profile': 'investment_operations55' if args.action in ('snapshot', 'check-rollback') else schema['profile'],
                      'schemaSha256': schema['sha256'], 'verified': True}))


if __name__ == '__main__':
    main()
