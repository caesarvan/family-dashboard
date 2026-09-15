"""Verify the one-time 42-to-43 journey-document migration without exposing rows.

The caller stops all writers and pins source, image, inputs and configuration.
Only ``warm`` initializes databases; it rechecks the complete backup first and
never starts the worker. This module does not deploy, restore or stop services.
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
import sys


if not __debug__:
    raise RuntimeError('Migration verification requires Python assertions enabled')

SOURCE_ROOT = Path(__file__).resolve().parents[1]
BASE_TABLES = set('assistant_plans attempts audit calendar_publications cloud_accounts cloud_items cloud_oauth_states cloud_sources cloud_writes devices entities finance_baselines finance_source_receipts finance_spending_observations finance_spending_receipts household_routines hub_budgets hub_imports hub_investment_import_previews hub_investment_import_receipts hub_investment_links hub_investment_sources hub_investments hub_reconciliations hub_shopping_settlement_receipts hub_shopping_settlements hub_transactions journey_actions journey_links journey_workflows member_dashboard_layout member_preferences member_session_browsers member_sessions photo_refs photos private_finance routine_occurrences routine_receipts settings task_publications users'.split())
NEW_TABLES = {'journey_documents'}


def schema_definition():
    """Read the current module's literal DDL without importing or initializing it."""
    tree = ast.parse((SOURCE_ROOT / 'journey_documents.py').read_text(encoding='utf-8'))
    values = [ast.literal_eval(node.value) for node in tree.body
              if isinstance(node, ast.Assign) and any(
                  isinstance(target, ast.Name) and target.id == 'SCHEMA_SQL'
                  for target in node.targets)]
    assert len(values) == 1 and isinstance(values[0], str), 'Expected one literal SCHEMA_SQL'
    sql = values[0]
    return {'sql': sql, 'sha256': hashlib.sha256(sql.encode('utf-8')).hexdigest()}


def row_digest(rows):
    def blob(value):
        assert isinstance(value, bytes)
        return {'blobSha256': hashlib.sha256(value).hexdigest()}
    values = sorted(json.dumps(row, ensure_ascii=False, separators=(',', ':'), default=blob) for row in rows)
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def file_digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def checked_path(root, relative):
    root = Path(root).resolve(strict=True)
    parts = PurePosixPath(relative)
    assert not parts.is_absolute() and '..' not in parts.parts and '\\' not in relative
    path = root
    for part in parts.parts:
        path = path / part
        assert not path.is_symlink(), 'Symlink outside input boundary'
    assert path.resolve(strict=True).is_relative_to(root) and path.is_file() and path.stat().st_size > 0
    return path


def fingerprint(path):
    path = Path(path).resolve(strict=True)
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as con:
        con.execute('BEGIN')
        assert con.execute('PRAGMA quick_check').fetchall() == [('ok',)]
        assert con.execute('PRAGMA foreign_key_check').fetchall() == []
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
    return 'household.sqlite3' if uid == 'default' else 'spaces/' + uid + '/household.sqlite3'


def snapshot(root, allow_new=False):
    root = Path(root).resolve(strict=True)
    registry_path = checked_path(root, 'platform.sqlite3')
    registry = fingerprint(registry_path)
    assert set(registry['tables']) == {'households', 'household_invitations'}
    with closing(sqlite3.connect(registry_path.as_uri() + '?mode=ro', uri=True)) as con:
        ids = sorted(r[0] for r in con.execute('SELECT id FROM households'))
    assert ids and 'default' in ids and len(ids) == len(set(ids))
    assert all(uid == 'default' or re.fullmatch(r'[0-9a-f]{24}', uid) for uid in ids)
    households = {uid: fingerprint(checked_path(root, relative_database(uid))) for uid in ids}
    expected = BASE_TABLES | NEW_TABLES if allow_new else BASE_TABLES
    assert all(set(value['tables']) == expected for value in households.values()), 'Unexpected household table set'
    return {'registry': registry, 'households': households}


def expected_addition(sql):
    assert sql == schema_definition()['sql'], 'DDL differs from current journey_documents.SCHEMA_SQL'
    with closing(sqlite3.connect(':memory:')) as con:
        con.executescript(sql)
        objects = con.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall()
        assert {x[1] for x in objects if x[0] == 'table'} == NEW_TABLES
        assert all(x[2] in NEW_TABLES for x in objects), 'Unexpected schema object target'
        tables = {}
        for name in NEW_TABLES:
            tables[name] = {'count': 0, 'rowsSha256': row_digest([]),
                            'columns': [list(x) for x in con.execute('PRAGMA table_xinfo(' + name + ')')],
                            'foreignKeys': [list(x) for x in con.execute('PRAGMA foreign_key_list(' + name + ')')]}
        return row_digest(objects), tables


def preserved(before, after, sql):
    assert before['registry'] == after['registry'], 'Registry changed'
    assert set(before['households']) == set(after['households']), 'Household set changed'
    expected_schema, expected_tables = expected_addition(sql)
    for uid, old in before['households'].items():
        new = after['households'][uid]
        assert set(old['tables']) == BASE_TABLES and set(new['tables']) == BASE_TABLES | NEW_TABLES
        assert old['baseSchemaSha256'] == new['baseSchemaSha256'], 'Existing schema objects changed'
        assert old['internal'] == new['internal'], 'Internal sequence changed'
        assert all(old['tables'][name] == new['tables'][name] for name in BASE_TABLES), 'Existing rows or columns changed'
        assert new['newSchemaSha256'] == expected_schema, 'New schema differs from frozen DDL'
        assert all(new['tables'][name] == expected_tables[name] for name in NEW_TABLES), 'New table not empty or wrong columns'
    return {'households': len(before['households']), 'originalTablesPreserved': 42, 'newTables': 1,
            'newTableEmpty': True, 'schemaIndexesAndTriggersVerified': True,
            'allOriginalRowsAndSequencesPreserved': True}


def validated_backup(root, before, backup):
    root = Path(root).resolve(strict=True)
    name = backup['manifest']
    assert re.fullmatch(r'manifest-[0-9TZ]+\.json', name)
    manifest_path = checked_path(root, 'backups/' + name)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    expected = {'platform.sqlite3': before['registry'],
                **{relative_database(uid): value for uid, value in before['households'].items()}}
    found = set()
    for item in manifest['snapshots']:
        match = re.fullmatch(r'(backups|spaces/([0-9a-f]{24})/backups)/(household|platform)-[0-9TZ]+\.sqlite3', item['path'])
        assert match and not (match[2] and match[3] == 'platform')
        target = 'platform.sqlite3' if match[3] == 'platform' else relative_database(match[2] or 'default')
        assert target in expected and target not in found
        path = checked_path(root, item['path'])
        assert path.stat().st_size == item['bytes'] and file_digest(path) == item['sha256']
        assert fingerprint(path) == expected[target], 'Backup contents differ from stopped state'
        found.add(target)
    assert found == set(expected) and backup['databases'] == len(found)
    return {'databases': len(found), 'manifestSha256': file_digest(manifest_path), 'groupVerified': True}


def run(action, root, inputs):
    """Use bound inputs; warm alone writes, after rechecking the old state/backup."""
    assert action in ('snapshot', 'validate-backup', 'warm', 'check'), 'Unknown verifier action'
    root = Path(root).resolve(strict=True)
    inputs = Path(inputs).resolve(strict=True)

    def read(name):
        return json.loads(checked_path(inputs, name).read_text(encoding='utf-8'))

    definition = read('schema.json')
    assert definition == schema_definition(), 'Schema input differs from current source DDL or digest'
    sql = definition['sql']
    expected_addition(sql)
    if action == 'snapshot':
        return snapshot(root)
    before = read('before.json')
    if action in ('validate-backup', 'warm'):
        assert snapshot(root) == before, 'Pre-migration database drift'
        backup = validated_backup(root, before, read('backup.json'))
        if action == 'validate-backup':
            return backup
        # The CLI adds the source root to sys.path, never imports a different app.
        from app import create_app
        application = create_app({'DATA_DIR': str(root)})
        platform = application.extensions['household_platform']
        households = platform.households()
        assert sorted(item['id'] for item in households) == sorted(before['households'])
        for household in households:
            platform.child(household)
        result = preserved(before, snapshot(root, True), sql)
        result.update(cloudTicks=0, backup=backup)
        return result
    return preserved(before, snapshot(root, True), sql)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('snapshot', 'validate-backup', 'warm', 'check'))
    parser.add_argument('--data-dir', default=os.environ.get('DATA_DIR'))
    parser.add_argument('--inputs-dir', default='/release-check')
    args = parser.parse_args(argv)
    if not args.data_dir:
        parser.error('--data-dir or DATA_DIR is required')
    print(json.dumps(run(args.action, args.data_dir, args.inputs_dir), ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    sys.path.insert(0, str(SOURCE_ROOT))
    main()
