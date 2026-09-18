"""Read-only comparison of stopped SQLite copies for the membership migration.

No application imports, migration, backup, network, or production operator.
The only writable SQLite connection is an in-memory schema reference.
"""
import argparse
from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat


SOURCE_PINS = {
    'domainCommit': '754d2e1552c8953b9d490df246d1328bdf3abf43',
    'domainSha256': 'dad3afb0efa5bd8aa5cd0670185d023fb18c00c5b02d8468b682fbaeb7c9e757',
    'personalCommit': 'e5a39274076607e89b9df6c2052d9565018e6ad1',
    'personalSha256': '147caff1154c8568ccd60d066312d67598830bb7e6aeeb227a8393bd6dc680ad',
    'wiringCommit': 'ae8c5698f055f3a0a384bf23ab1d0ece0a3e5069',
}
BASE_HOUSEHOLD_TABLES = frozenset('assistant_plans attempts audit calendar_publications cloud_accounts cloud_items cloud_oauth_states cloud_sources cloud_writes devices entities finance_account_operations finance_account_valuations finance_accounts finance_baselines finance_source_receipts finance_spending_observations finance_spending_receipts household_routines hub_budgets hub_import_receipts hub_imports hub_investment_import_previews hub_investment_import_receipts hub_investment_links hub_investment_operations hub_investment_sources hub_investments hub_reconciliations hub_shopping_settlement_receipts hub_shopping_settlements hub_transactions inventory_acquisitions inventory_items inventory_movements inventory_operations inventory_source_links journey_actions journey_documents journey_links journey_places journey_workflows media_imports media_items media_playback media_tv_grants member_dashboard_layout member_preferences member_session_browsers member_sessions photo_refs photos private_finance routine_occurrences routine_receipts settings task_publications users'.split())
BASE_PLATFORM_TABLES = frozenset({'households', 'household_invitations'})
PERSONAL_IDENTITY_SQL = 'ALTER TABLE member_sessions ADD COLUMN personal_identity TEXT'
MARKER = ('membership_schema_v1', '{"version":1}', 1)

# Exact literals from the fixed sources above; verified independently in tests.
HOUSEHOLD_SQL = (
    """CREATE TABLE household_memberships(
        id TEXT PRIMARY KEY, member_id TEXT NOT NULL UNIQUE REFERENCES users(id),
        account_id TEXT UNIQUE, state TEXT NOT NULL CHECK(state IN ('active','left','removed')),
        revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 9007199254740991),
        created_at REAL NOT NULL, updated_at REAL NOT NULL)""",
    """CREATE TABLE member_invitations(
        id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE,
        creator_member_id TEXT NOT NULL REFERENCES users(id), creator_auth_version INTEGER NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('pending','used','revoked')),
        revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 9007199254740991),
        created_at REAL NOT NULL, expires_at REAL NOT NULL, revoked_at REAL,
        used_at REAL, used_by_account_id TEXT)""",
    """CREATE TABLE membership_operations(
        subject TEXT NOT NULL, request_id TEXT NOT NULL, kind TEXT NOT NULL,
        intent_digest TEXT NOT NULL, member_id TEXT REFERENCES users(id),
        result_json TEXT NOT NULL, created_at REAL NOT NULL,
        PRIMARY KEY(subject,request_id))""",
)
PLATFORM_SQL = (
    """CREATE TABLE personal_accounts(
      id TEXT PRIMARY KEY, login TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
      auth_version INTEGER NOT NULL CHECK(auth_version>0), created_at REAL NOT NULL)""",
    """CREATE TABLE personal_browsers(
      browser_hash TEXT PRIMARY KEY, generation INTEGER NOT NULL,
      csrf_hash TEXT NOT NULL, expires_at REAL NOT NULL)""",
    """CREATE TABLE personal_sessions(
      id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES personal_accounts(id),
      credential_hash TEXT UNIQUE NOT NULL, csrf_hash TEXT NOT NULL,
      browser_hash TEXT NOT NULL REFERENCES personal_browsers(browser_hash),
      generation INTEGER NOT NULL, auth_version INTEGER NOT NULL,
      created_at REAL NOT NULL, expires_at REAL NOT NULL, verified_at REAL NOT NULL,
      revoked_at REAL)""",
    """CREATE TABLE account_memberships(
      membership_id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES personal_accounts(id),
      household_id TEXT NOT NULL REFERENCES households(id), member_id TEXT NOT NULL,
      UNIQUE(account_id,household_id), UNIQUE(household_id,member_id))""",
    """CREATE TABLE account_operations(
      subject TEXT NOT NULL, request_id TEXT NOT NULL, account_id TEXT,
      browser_hash TEXT NOT NULL, browser_generation INTEGER NOT NULL,
      browser_csrf_hash TEXT NOT NULL, kind TEXT NOT NULL, household_id TEXT,
      intent_digest TEXT NOT NULL, details TEXT NOT NULL,
      state TEXT NOT NULL CHECK(state IN ('pending','completed','not_committed')),
      result TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL,
      PRIMARY KEY(subject,request_id), UNIQUE(account_id,request_id))""",
    """CREATE TABLE account_qualifications(
      token_hash TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('member','invitation')),
      browser_hash TEXT NOT NULL, generation INTEGER NOT NULL, account_id TEXT,
      proof TEXT NOT NULL, expires_at REAL NOT NULL, used_request TEXT, used_account TEXT)""",
    """CREATE TABLE personal_limits(
      id TEXT PRIMARY KEY, window INTEGER NOT NULL, attempts INTEGER NOT NULL)""",
)
NEW_HOUSEHOLD_TABLES = frozenset({'household_memberships', 'member_invitations', 'membership_operations'})
NEW_PLATFORM_TABLES = frozenset({'personal_accounts', 'personal_browsers', 'personal_sessions', 'account_memberships', 'account_operations', 'account_qualifications', 'personal_limits'})


class MigrationCheckError(RuntimeError):
    """Only fixed error codes: never echo SQLite values, SQL, or input paths."""


def need(condition, code):
    if not condition:
        raise MigrationCheckError(code)


def digest(value):
    def blob(item):
        need(isinstance(item, bytes), 'unsupported_value')
        return {'blobSha256': hashlib.sha256(item).hexdigest()}
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), default=blob, allow_nan=False).encode()).hexdigest()


def rows_digest(rows):
    # Order independent, type preserving, and duplicate preserving.
    return digest(sorted(digest(tuple(row)) for row in rows))


def file_digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def checked_path(value):
    path = Path(os.path.abspath(value))
    for part in (path, *path.parents):
        try:
            attrs = part.lstat()
        except OSError:
            raise MigrationCheckError('missing_input') from None
        need(not stat.S_ISLNK(attrs.st_mode) and not getattr(attrs, 'st_file_attributes', 0) & 0x400,
             'linked_input')
    need(path.is_file() and path.stat().st_size > 0, 'invalid_input')
    no_sidecars(path)
    return path


def no_sidecars(path):
    need(not any(Path(str(path) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')), 'sqlite_sidecar_present')


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def objects(con):
    return con.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall()


def _read(path):
    before = file_digest(path)
    try:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)) as con:
            con.execute('PRAGMA query_only=ON')
            con.execute('PRAGMA trusted_schema=OFF')
            con.execute('BEGIN')
            need(con.execute('PRAGMA quick_check').fetchall() == [('ok',)], 'database_integrity')
            need(con.execute('PRAGMA foreign_key_check').fetchall() == [], 'database_foreign_keys')
            schema = objects(con)
            rows, columns = {}, {}
            for kind, name, _, _ in schema:
                if kind == 'table':
                    rows[name] = con.execute('SELECT * FROM ' + quote(name)).fetchall()
                    columns[name] = con.execute('PRAGMA table_xinfo(' + quote(name) + ')').fetchall()
            result = {'schema': schema, 'rows': rows, 'columns': columns,
                      'userVersion': con.execute('PRAGMA user_version').fetchone()[0],
                      'applicationId': con.execute('PRAGMA application_id').fetchone()[0], 'fileSha256': before}
    except (sqlite3.Error, ValueError, OverflowError):
        raise MigrationCheckError('unreadable_database') from None
    no_sidecars(path)
    need(before == file_digest(path), 'input_changed_during_read')
    return result


def _summary(value):
    return {'fileSha256': value['fileSha256'], 'schemaSha256': digest(value['schema']),
            'userVersion': value['userVersion'], 'applicationId': value['applicationId'],
            'tables': {name: {'count': len(rows), 'rowsSha256': rows_digest(rows),
                              'columnsSha256': digest(value['columns'][name])}
                       for name, rows in sorted(value['rows'].items())}}


def _expected_schema(before, kind):
    expected = list(before['schema'])
    with closing(sqlite3.connect(':memory:')) as con:
        if kind == 'household':
            old = next(row for row in expected if row[:3] == ('table', 'member_sessions', 'member_sessions'))
            con.execute(old[3])
            con.execute(PERSONAL_IDENTITY_SQL)
            updated = next(row for row in objects(con) if row[:3] == old[:3])
            expected[expected.index(old)] = updated
            expected_columns = con.execute('PRAGMA table_xinfo(member_sessions)').fetchall()
        else:
            expected_columns = None
    with closing(sqlite3.connect(':memory:')) as con:
        for statement in HOUSEHOLD_SQL if kind == 'household' else PLATFORM_SQL:
            con.execute(statement)
        additions = objects(con)
    need(not ({r[1] for r in expected} & {r[1] for r in additions}), 'schema_name_collision')
    return sorted(expected + additions, key=lambda row: row[:2]), expected_columns


def _verify(before, after, kind):
    base = BASE_HOUSEHOLD_TABLES if kind == 'household' else BASE_PLATFORM_TABLES
    added = NEW_HOUSEHOLD_TABLES if kind == 'household' else NEW_PLATFORM_TABLES
    need({n for n in before['rows'] if not n.startswith('sqlite_')} == base, 'baseline_table_set')
    need(set(after['rows']) == set(before['rows']) | added, 'after_table_set')
    need(before['applicationId'] == after['applicationId'], 'application_id_changed')
    expected_schema, session_columns = _expected_schema(before, kind)
    need(after['schema'] == expected_schema, 'schema_delta_not_exact')
    allowed = {'member_sessions', 'settings'} if kind == 'household' else set()
    for name in before['rows']:
        if name not in allowed:
            need(before['columns'][name] == after['columns'][name], 'old_columns_changed')
            need(rows_digest(before['rows'][name]) == rows_digest(after['rows'][name]), 'old_rows_or_sequence_changed')
    if kind == 'platform':
        need((before['userVersion'], after['userVersion']) == (0, 1), 'platform_user_version')
        need(all(not after['rows'][name] for name in added), 'platform_additions_not_empty')
    else:
        need(before['userVersion'] == after['userVersion'], 'household_user_version_changed')
        need(after['columns']['member_sessions'] == session_columns and
             [r[1] for r in before['columns']['member_sessions']] == [r[1] for r in session_columns[:-1]], 'session_columns_changed')
        need(rows_digest(before['rows']['member_sessions']) == rows_digest([r[:-1] for r in after['rows']['member_sessions']]) and
             all(r[-1] is None for r in after['rows']['member_sessions']), 'old_sessions_changed_or_bound')
        need([r[1] for r in before['columns']['settings']] == ['id', 'data', 'revision'] and
             before['columns']['settings'] == after['columns']['settings'], 'settings_columns_changed')
        need(not any(r[0] == MARKER[0] for r in before['rows']['settings']), 'marker_already_present')
        need([r for r in after['rows']['settings'] if r[0] == MARKER[0]] == [MARKER] and
             rows_digest(before['rows']['settings']) == rows_digest([r for r in after['rows']['settings'] if r[0] != MARKER[0]]), 'settings_delta_not_exact')
        need([r[1] for r in before['columns']['users']] == ['id', 'username', 'name', 'password', 'auth_version', 'household_role'], 'baseline_users_columns')
        users = {r[0] for r in before['rows']['users']}
        memberships = after['rows']['household_memberships']
        need(len(memberships) == len(users) and {r[1] for r in memberships} == users, 'initial_membership_coverage')
        need(all(isinstance(r[0], str) and re.fullmatch('[0-9a-f]{32}', r[0]) and r[2] is None and
                 r[3] == 'active' and type(r[4]) is int and r[4] == 1 and
                 isinstance(r[5], (int, float)) and math.isfinite(r[5]) and r[5] >= 0 and r[5] == r[6]
                 for r in memberships), 'initial_membership_values')
        need(not after['rows']['member_invitations'] and not after['rows']['membership_operations'], 'household_additions_not_empty')
    return {'kind': kind, 'verified': True, 'beforeTableCount': len(base), 'afterTableCount': len(base | added),
            'before': _summary(before), 'after': _summary(after)}


def _pair(before_path, after_path, kind):
    before_path, after_path = checked_path(before_path), checked_path(after_path)
    need(not os.path.samefile(before_path, after_path), 'same_input_file')
    try:
        before, after = _read(before_path), _read(after_path)
        result = _verify(before, after, kind)
        for path, value in ((before_path, before), (after_path, after)):
            no_sidecars(path)
            need(file_digest(path) == value['fileSha256'], 'input_changed_during_comparison')
        return result
    except (sqlite3.Error, ValueError, OverflowError, OSError):
        raise MigrationCheckError('unreadable_database') from None


def verify_household(before_path, after_path):
    """Compare one household pair; does not certify all registry households."""
    return _pair(before_path, after_path, 'household')


def verify_platform(before_path, after_path):
    """Compare the registry/platform pair; no household side effects."""
    return _pair(before_path, after_path, 'platform')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--household-pair', nargs=2, action='append', required=True, metavar=('BEFORE', 'AFTER'))
    parser.add_argument('--platform-pair', nargs=2, required=True, metavar=('BEFORE', 'AFTER'))
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    pairs = [*args.household_pair, args.platform_pair]
    # Even a missing input must never become our output or acquire a sidecar.
    # Output lives outside every input directory, including resolved aliases.
    output = Path(args.output).resolve()
    if any(output.is_relative_to(Path(p).resolve().parent) for pair in pairs for p in pair):
        raise SystemExit('output_inside_input_directory')
    try:
        # Reserve the output exclusively first. Failures are preserved, never overwritten.
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError:
        raise SystemExit('output_not_new') from None
    with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
        try:
            paths = [checked_path(p) for pair in pairs for p in pair]
            need(len({(p.stat().st_dev, p.stat().st_ino) for p in paths}) == len(paths), 'reused_input_file')
            hashes = [file_digest(p) for p in paths]
            result = {'verified': True, 'readOnly': True, 'scope': 'explicit_pairs_not_registry_completeness',
                      'sourcePins': SOURCE_PINS,
                      'households': [verify_household(*pair) for pair in args.household_pair],
                      'platform': verify_platform(*args.platform_pair)}
            need(hashes == [file_digest(p) for p in paths], 'input_changed_during_group')
            for path in paths:
                no_sidecars(path)
        except (MigrationCheckError, OSError):
            import sys
            error = sys.exc_info()[1]
            result = {'verified': False, 'readOnly': True,
                      'code': str(error) if isinstance(error, MigrationCheckError) else 'unreadable_input'}
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            return 1
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
