"""Explicit stopped-writer 58 -> 58 users role-column migration.

Each household uses the reviewed API's own atomic initializer. All writers
must remain stopped; a partial group requires inspection and complete-group
rollback, never replay. No app, worker, backup, restore or network is started.
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

import household_members
from deploy import check_finance_accounts_migration as previous
from deploy import check_media_migration as media

ROOT = Path(__file__).resolve().parents[1]
BASE_TABLES = frozenset(previous.BASE_TABLES | previous.NEW_TABLES)
need = media.need
BASE_USERS_SQL = ('CREATE TABLE users(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,\n'
                  '          name TEXT NOT NULL, password TEXT NOT NULL, auth_version INTEGER NOT NULL DEFAULT 1)')
ROLE_SQL = "ALTER TABLE users ADD COLUMN household_role TEXT NOT NULL DEFAULT 'member' CHECK(household_role IN ('admin','member'))"
OLD_COLUMNS = ('id', 'username', 'name', 'password', 'auth_version')


def schema_definition():
    source = ROOT / 'household_members.py'
    need(source.is_file() and not source.is_symlink(), 'schema_source_missing')
    need(Path(household_members.__file__).resolve() == source.resolve(), 'schema_module_origin')
    sql = getattr(household_members, 'HOUSEHOLD_ROLE_COLUMN_SQL', None)
    need(sql == ROLE_SQL, 'unexpected_role_column_sql')
    with closing(sqlite3.connect(':memory:')) as con:
        con.execute(BASE_USERS_SQL)
        old_columns = [list(r) for r in con.execute('PRAGMA table_xinfo(users)')]
        con.execute(sql)
        columns = [list(r) for r in con.execute('PRAGMA table_xinfo(users)')]
        users_sql = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()[0]
    return {'profile': 'household_members58', 'sql': sql,
            'sha256': hashlib.sha256(sql.encode('utf-8')).hexdigest(),
            'sourceSha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'baseUsersSql': BASE_USERS_SQL, 'usersSql': users_sql,
            'baseColumns': old_columns, 'columns': columns, 'foreignKeys': []}


def _users_projection(path, expected, *, immutable=False):
    """Bind an extra projection to the unchanged complete users fingerprint."""
    uri = Path(path).resolve(strict=True).as_uri() + '?mode=ro' + ('&immutable=1' if immutable else '')
    with closing(sqlite3.connect(uri, uri=True)) as con:
        con.execute('BEGIN')
        columns = [list(r) for r in con.execute('PRAGMA table_xinfo(users)')]
        names = [r[1] for r in columns]
        need(tuple(names[:5]) == OLD_COLUMNS and len(names) in (5, 6), 'unexpected_users_columns')
        need(len(names) == 5 or names[5] == 'household_role', 'unexpected_users_columns')
        rows = con.execute('SELECT * FROM users').fetchall()
        full = {'count': len(rows), 'rowsSha256': media.row_digest(rows), 'columns': columns,
                'foreignKeys': [list(r) for r in con.execute('PRAGMA foreign_key_list(users)')]}
        need(full == expected, 'users_changed_during_snapshot')
        has_role = len(names) == 6
        return {'count': len(rows), 'columns': columns[:5],
                'rowsSha256': media.row_digest([r[:5] for r in rows]),
                'initialRolesSha256': media.row_digest([(r[0], 'admin' if r[0] in ('member1', 'member2') else 'member') for r in rows]),
                'rolesSha256': media.row_digest([(r[0], r[5]) for r in rows]) if has_role else None,
                'roleCounts': {role: sum(r[5] == role for r in rows) for role in ('admin', 'member')} if has_role else None}


def snapshot(root):
    root = Path(root).resolve(strict=True)
    result = media.snapshot(root)
    # The existing registry/tables/schema/rows fingerprints remain intact.
    # Only hashes and counts of the original columns/roles are added, no PII.
    result['usersProjection'] = {uid: _users_projection(media.checked_path(root, media.relative_database(uid)), value['tables']['users'])
                                 for uid, value in result['households'].items()}
    return result


def _verify_profile(value, schema, *, roles):
    need(schema == schema_definition(), 'schema_changed_after_review')
    need(len(BASE_TABLES) == 58, 'baseline_definition_changed')
    previous.verify_current(value, previous.schema_definition())
    need(set(value.get('usersProjection', {})) == set(value['households']), 'users_projection_group')
    for uid, item in value['households'].items():
        need({n for n in item['tables'] if not n.startswith('sqlite_')} == BASE_TABLES, 'expected_58_table_snapshot')
        users, projected = item['tables']['users'], value['usersProjection'][uid]
        need(users['columns'] == schema['columns' if roles else 'baseColumns'] and users['foreignKeys'] == [], 'users_columns_or_foreign_keys_changed')
        statements = [r[3] for r in item['schema'] if r[:3] == ['table', 'users', 'users']]
        expected_sql = schema['usersSql' if roles else 'baseUsersSql']
        need(len(statements) == 1 and re.sub(r'\s+', ' ', statements[0]).strip() == re.sub(r'\s+', ' ', expected_sql).strip(), 'users_schema_changed')
        need(projected['count'] == users['count'] and projected['columns'] == schema['baseColumns'], 'users_projection_shape')
        if roles:
            counts = projected['roleCounts']
            need(isinstance(counts, dict) and set(counts) == {'admin', 'member'} and
                 all(type(n) is int and n >= 0 for n in counts.values()) and
                 counts['admin'] >= 1 and sum(counts.values()) == users['count'], 'invalid_household_roles')
            need(isinstance(projected['rolesSha256'], str) and re.fullmatch('[0-9a-f]{64}', projected['rolesSha256']), 'missing_roles_digest')
        else:
            need(projected['rolesSha256'] is None and projected['roleCounts'] is None and
                 projected['rowsSha256'] == users['rowsSha256'], 'baseline_users_projection_changed')
    return {'profile': schema['profile'] if roles else 'finance_accounts58',
            'households': len(value['households']), 'tablesPerHousehold': 58}


def verify_baseline(before):
    return _verify_profile(before, schema_definition(), roles=False)


def verify_current(current, schema):
    """Permit legitimate later member roles; never reset them to admin."""
    return _verify_profile(current, schema, roles=True)


def verify_addition(before, after, schema):
    verify_baseline(before)
    verify_current(after, schema)
    need(before['registry'] == after['registry'], 'registry_changed')
    need(set(before['households']) == set(after['households']), 'household_group_changed')
    for uid, old in before['households'].items():
        new = after['households'][uid]
        need(set(old['tables']) == set(new['tables']), 'table_set_changed')
        need(all(new['tables'][n] == v for n,v in old['tables'].items() if n != 'users'), 'other_tables_rows_schema_or_sequences_changed')
        old_projection, new_projection = before['usersProjection'][uid], after['usersProjection'][uid]
        need(all(old_projection[k] == new_projection[k] for k in ('count','columns','rowsSha256','initialRolesSha256')), 'original_user_columns_or_rows_changed')
        need(new_projection['rolesSha256'] == old_projection['initialRolesSha256'], 'initial_roles_not_exact')
        expected = [list(r) for r in old['schema']]
        with closing(sqlite3.connect(':memory:')) as con:
            user_row = next(r for r in expected if r[:3] == ['table','users','users'])
            con.execute(user_row[3]); con.execute(schema['sql'])
            user_row[3] = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()[0]
        need(new['schema'] == expected, 'schema_change_not_exact_users_column')
    return {'profile': schema['profile'], 'originalTablesPreserved': 58, 'newTables': 0,
            'addedColumns': ['users.household_role'], 'households': len(before['households']),
            'originalUserColumnsPreserved': 5, 'initialRolesVerified': True,
            'otherRowsSchemaAndSequencesPreserved': True, 'registryPreserved': True}


def validate_backup(root, before, backup):
    """Retain immutable full fingerprints, then also verify the extra projection."""
    schema = schema_definition()
    states = {v['rolesSha256'] is not None for v in before.get('usersProjection', {}).values()}
    need(len(states) == 1, 'mixed_or_missing_role_profile')
    _verify_profile(before, schema, roles=states.pop())
    proof = media.validate_backup(root, before, backup)
    root = Path(root).resolve(strict=True)
    manifest = json.loads(media.checked_path(root, 'backups/'+backup['manifest']).read_text(encoding='utf-8'))
    for item in manifest['snapshots']:
        match = re.fullmatch(r'(backups|spaces/([a-f0-9]{24})/backups)/(household|platform)-[0-9TZ]+\.sqlite3', item['path'])
        if match[3] == 'household':
            uid = match[2] or 'default'
            projected = _users_projection(media.checked_path(root, item['path']), before['households'][uid]['tables']['users'], immutable=True)
            need(projected == before['usersProjection'][uid], 'backup_users_projection_changed')
    return proof


def verify_restore(reference, restored, schema):
    profile = verify_current(reference, schema)
    verify_current(restored, schema)
    need(reference == restored, 'restored_data_schema_or_sequences_changed')
    return {**profile, 'completeGroupRestored': True, 'allRowsSchemaAndSequencesPreserved': True}


def verify_rollback(reference, restored):
    profile = verify_baseline(reference)
    verify_baseline(restored)
    need(reference == restored, 'rolled_back_data_schema_or_sequences_changed')
    return {**profile, 'completeGroupRestored': True, 'allRowsSchemaAndSequencesPreserved': True}


def migrate(root, before, backup, schema):
    root = Path(root).resolve(strict=True)
    need(schema == schema_definition(), 'schema_changed_after_review')
    verify_baseline(before)
    need(snapshot(root) == before, 'database_changed_after_snapshot')
    validate_backup(root, before, backup)
    for uid in sorted(before['households']):
        path = media.checked_path(root, media.relative_database(uid))
        with closing(sqlite3.connect(path.as_uri()+'?mode=rw', uri=True)) as con:
            con.execute('PRAGMA foreign_keys=ON')
            need(con.execute('PRAGMA foreign_keys').fetchone()[0] == 1, 'foreign_keys_disabled')
            household_members.init_schema(con)
    proof = verify_addition(before, snapshot(root), schema)
    validate_backup(root, before, backup)
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('snapshot','snapshot-current','validate-backup','migrate','check','check-restored','check-rollback'))
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--before', type=Path)
    parser.add_argument('--backup', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    need(not args.output.exists() and not args.output.is_symlink() and args.output.parent.is_dir(), 'output_must_be_new')
    schema = schema_definition()
    before = json.loads(args.before.read_text(encoding='utf-8')) if args.before else None
    backup = json.loads(args.backup.read_text(encoding='utf-8')) if args.backup else None
    if args.action in ('snapshot','snapshot-current'):
        result = snapshot(args.data_root)
        verify_baseline(result) if args.action == 'snapshot' else verify_current(result, schema)
    elif args.action == 'validate-backup':
        need(before is not None and backup is not None, 'snapshot_and_backup_required')
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
    print(json.dumps({'action': args.action, 'profile': 'finance_accounts58' if args.action in ('snapshot','check-rollback') else schema['profile'],
                      'schemaSha256': schema['sha256'], 'verified': True}))


if __name__ == '__main__':
    main()
