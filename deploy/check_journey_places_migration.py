"""Bounded, explicit 43-to-44 migration; never start an app, worker or network.

The caller stops all writers and binds source/image/inputs. Only warm writes.
Each household DDL transaction is atomic; the whole group is not. Mixed or
already migrated groups are rejected, including after an interrupted warm.
"""
import argparse
import ast
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3


SOURCE_ROOT = Path(__file__).resolve().parents[1]
BASE_TABLES = set('assistant_plans attempts audit calendar_publications cloud_accounts cloud_items cloud_oauth_states cloud_sources cloud_writes devices entities finance_baselines finance_source_receipts finance_spending_observations finance_spending_receipts household_routines hub_budgets hub_imports hub_investment_import_previews hub_investment_import_receipts hub_investment_links hub_investment_sources hub_investments hub_reconciliations hub_shopping_settlement_receipts hub_shopping_settlements hub_transactions journey_actions journey_documents journey_links journey_workflows member_dashboard_layout member_preferences member_session_browsers member_sessions photo_refs photos private_finance routine_occurrences routine_receipts settings task_publications users'.split())
NEW_TABLES = {'journey_places'}


def need(value, label):
    if not value:
        raise RuntimeError(label)


def schema_definition():
    tree = ast.parse((SOURCE_ROOT / 'journey_places.py').read_text(encoding='utf-8'))
    values = [ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Name) and target.id == 'SCHEMA_SQL' for target in node.targets)]
    need(len(values) == 1 and isinstance(values[0], str), 'schema_literal_missing')
    sql = values[0]
    return {'sql': sql, 'sha256': hashlib.sha256(sql.encode('utf-8')).hexdigest()}


def row_digest(rows):
    def blob(value):
        need(isinstance(value, bytes), 'unsupported_database_value')
        return {'blobSha256': hashlib.sha256(value).hexdigest()}
    values = sorted(json.dumps(row, ensure_ascii=False, separators=(',', ':'), default=blob) for row in rows)
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def file_digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def checked_path(root, relative):
    root = Path(root).resolve(strict=True)
    need(isinstance(relative, str) and relative and '\\' not in relative and ':' not in relative, 'unsafe_path')
    parts = PurePosixPath(relative)
    need(not parts.is_absolute() and parts.as_posix() == relative
         and all(part not in ('.', '..') for part in parts.parts), 'unsafe_path')
    path = root
    for part in parts.parts:
        path = path / part
        need(not path.is_symlink(), 'symlink_path')
    need(path.resolve(strict=True).is_relative_to(root) and path.is_file() and path.stat().st_size > 0, 'missing_file')
    return path


def fingerprint(path, *, immutable=False):
    path = Path(path).resolve(strict=True)
    uri = path.as_uri() + '?mode=ro' + ('&immutable=1' if immutable else '')
    with closing(sqlite3.connect(uri, uri=True)) as con:
        con.execute('BEGIN')
        need(con.execute('PRAGMA quick_check').fetchall() == [('ok',)], 'database_integrity')
        need(con.execute('PRAGMA foreign_key_check').fetchall() == [], 'database_foreign_keys')
        objects = con.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall()
        tables, internal = {}, {}
        for kind, name, _, _ in objects:
            if kind != 'table':
                continue
            quote = '"' + name.replace('"', '""') + '"'
            rows = con.execute('SELECT * FROM ' + quote).fetchall()
            value = {'count': len(rows), 'rowsSha256': row_digest(rows),
                     'columns': [list(x) for x in con.execute('PRAGMA table_xinfo(' + quote + ')')],
                     'foreignKeys': [list(x) for x in con.execute('PRAGMA foreign_key_list(' + quote + ')')]}
            (internal if name.startswith('sqlite_') else tables)[name] = value
        return {'tables': tables, 'internal': internal,
                'baseSchemaSha256': row_digest([x for x in objects if x[2] not in NEW_TABLES]),
                'newSchemaSha256': row_digest([x for x in objects if x[2] in NEW_TABLES])}


def relative_database(uid):
    need(uid == 'default' or isinstance(uid, str) and re.fullmatch(r'[0-9a-f]{24}', uid), 'household_id')
    return 'household.sqlite3' if uid == 'default' else 'spaces/' + uid + '/household.sqlite3'


def snapshot(root, allow_new=False):
    root = Path(root).resolve(strict=True)
    registry_path = checked_path(root, 'platform.sqlite3')
    registry = fingerprint(registry_path)
    need(set(registry['tables']) == {'households', 'household_invitations'}, 'registry_tables')
    with closing(sqlite3.connect(registry_path.as_uri() + '?mode=ro', uri=True)) as con:
        ids = sorted(r[0] for r in con.execute('SELECT id FROM households'))
    need(ids and 'default' in ids and len(ids) == len(set(ids)), 'household_registry')
    households = {uid: fingerprint(checked_path(root, relative_database(uid))) for uid in ids}
    expected = BASE_TABLES | NEW_TABLES if allow_new else BASE_TABLES
    need(all(set(value['tables']) == expected for value in households.values()), 'household_table_set')
    return {'registry': registry, 'households': households}


def expected_addition(sql):
    need(sql == schema_definition()['sql'], 'schema_source_mismatch')
    with closing(sqlite3.connect(':memory:')) as con:
        con.executescript(sql)
        objects = con.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall()
        need({x[1] for x in objects if x[0] == 'table'} == NEW_TABLES, 'schema_table_set')
        need(all(x[2] in NEW_TABLES for x in objects), 'schema_object_target')
        tables = {}
        for name in NEW_TABLES:
            tables[name] = {'count': 0, 'rowsSha256': row_digest([]),
                            'columns': [list(x) for x in con.execute('PRAGMA table_xinfo(' + name + ')')],
                            'foreignKeys': [list(x) for x in con.execute('PRAGMA foreign_key_list(' + name + ')')]}
        return row_digest(objects), tables


def preserved(before, after, sql):
    need(before['registry'] == after['registry'], 'registry_changed')
    need(set(before['households']) == set(after['households']), 'households_changed')
    expected_schema, expected_tables = expected_addition(sql)
    for uid, old in before['households'].items():
        new = after['households'][uid]
        need(set(old['tables']) == BASE_TABLES and set(new['tables']) == BASE_TABLES | NEW_TABLES, 'table_set_changed')
        need(old['baseSchemaSha256'] == new['baseSchemaSha256'], 'original_schema_changed')
        need(old['internal'] == new['internal'], 'internal_sequence_changed')
        need(all(old['tables'][name] == new['tables'][name] for name in BASE_TABLES), 'original_data_changed')
        need(new['newSchemaSha256'] == expected_schema, 'new_schema_changed')
        need(all(new['tables'][name] == expected_tables[name] for name in NEW_TABLES), 'new_table_not_empty_or_invalid')
    return {'households': len(before['households']), 'originalTablesPreserved': 43, 'newTables': 1,
            'newTableEmpty': True, 'schemaIndexesAndTriggersVerified': True,
            'allOriginalRowsAndSequencesPreserved': True}


def validated_backup(root, before, backup):
    root = Path(root).resolve(strict=True)
    name = backup['manifest']
    need(isinstance(name, str) and re.fullmatch(r'manifest-[0-9TZ]+\.json', name), 'backup_manifest_path')
    manifest_path = checked_path(root, 'backups/' + name)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    expected = {'platform.sqlite3': before['registry'],
                **{relative_database(uid): value for uid, value in before['households'].items()}}
    found = set()
    for item in manifest['snapshots']:
        match = re.fullmatch(r'(backups|spaces/([0-9a-f]{24})/backups)/(household|platform)-[0-9TZ]+\.sqlite3', item['path'])
        need(match and not (match[2] and match[3] == 'platform'), 'backup_mapping')
        target = 'platform.sqlite3' if match[3] == 'platform' else relative_database(match[2] or 'default')
        need(target in expected and target not in found, 'backup_duplicate_or_extra')
        path = checked_path(root, item['path'])
        need(path.stat().st_nlink == 1, 'backup_hardlink')
        for suffix in ('-wal', '-shm', '-journal'):
            sidecar = Path(str(path) + suffix)
            need(not sidecar.exists() and not sidecar.is_symlink(), 'backup_sidecar')
        need(path.stat().st_size == item['bytes'] and file_digest(path) == item['sha256'], 'backup_digest')
        # A restore copies the manifest's main file only, never an unbound WAL.
        need(fingerprint(path, immutable=True) == expected[target], 'backup_contents')
        found.add(target)
    need(found == set(expected) and type(backup['databases']) is int and backup['databases'] == len(found), 'backup_group_incomplete')
    return {'databases': len(found), 'manifestSha256': file_digest(manifest_path), 'groupVerified': True}


def initialize_database(path, sql):
    """No app import; one explicit transaction and no network per household."""
    with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True)) as con:
        con.execute('PRAGMA foreign_keys=ON')
        need(con.execute('PRAGMA foreign_keys').fetchone()[0] == 1, 'foreign_keys_disabled')
        try:
            con.executescript('BEGIN IMMEDIATE;\n' + sql + '\nCOMMIT;')
        except Exception:
            con.rollback()
            raise


def run(action, root, inputs):
    need(action in ('snapshot', 'validate-backup', 'warm', 'check'), 'unknown_action')
    root, inputs = Path(root).resolve(strict=True), Path(inputs).resolve(strict=True)

    def read(name):
        return json.loads(checked_path(inputs, name).read_bytes())

    definition = read('schema.json')
    need(definition == schema_definition(), 'schema_input_changed')
    sql = definition['sql']
    expected_addition(sql)
    if action == 'snapshot':
        return snapshot(root)
    before = read('before.json')
    if action in ('validate-backup', 'warm'):
        need(snapshot(root) == before, 'pre_migration_drift')
        backup = validated_backup(root, before, read('backup.json'))
        if action == 'validate-backup':
            return backup
        need(read('backup-verification.json') == backup, 'backup_proof_changed')
        for uid in sorted(before['households']):
            initialize_database(checked_path(root, relative_database(uid)), sql)
        result = preserved(before, snapshot(root, True), sql)
        need(validated_backup(root, before, read('backup.json')) == backup, 'backup_changed_during_warm')
        result.update(cloudTicks=0, modelRequests=0, backup=backup)
        return result
    backup = validated_backup(root, before, read('backup.json'))
    need(read('backup-verification.json') == backup, 'backup_proof_changed')
    result = preserved(before, snapshot(root, True), sql)
    result['backup'] = backup
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('snapshot', 'validate-backup', 'warm', 'check'))
    parser.add_argument('--data-dir', default=os.environ.get('DATA_DIR'))
    parser.add_argument('--inputs-dir', default='/release-check')
    args = parser.parse_args(argv)
    if not args.data_dir:
        parser.error('--data-dir or DATA_DIR is required')
    try:
        result = run(args.action, args.data_dir, args.inputs_dir)
    except Exception:
        raise SystemExit('places_database_verification_failed') from None
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
