"""Exact stopped-writer 61/9 -> 66/9 schema addition; no application import."""
import ast
from contextlib import closing
import hashlib
from pathlib import Path
import re
import sqlite3

from deploy import membership_release_data as shared

ROOT = Path(__file__).resolve().parents[1]
BASE_TABLES = shared.migration.BASE_HOUSEHOLD_TABLES | shared.migration.NEW_HOUSEHOLD_TABLES
NEW_TABLES = frozenset({'finance_account_profiles', 'finance_account_cashflows',
    'finance_account_reviews', 'finance_analysis_operations', 'finance_fx_rates'})
SOURCES = {'finance_analysis.py': 'FINANCE_ANALYSIS_SCHEMA_SQL', 'finance_fx.py': 'FINANCE_FX_SCHEMA_SQL'}
need = shared.need


def schema_definition():
    """Read literal reviewed constants only; refuse any executable schema callback."""
    statements, hashes = [], {}
    for name, constant in SOURCES.items():
        source = shared.migration.checked_path(ROOT / name)
        raw = source.read_bytes()
        hashes[name] = hashlib.sha256(raw).hexdigest()
        values = [node.value for node in ast.parse(raw).body if isinstance(node, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == constant for t in node.targets)]
        need(len(values) == 1, 'schema_constant_missing_or_repeated')
        sql = ast.literal_eval(values[0])
        need(isinstance(sql, str) and bool(sql.strip()), 'schema_constant_not_literal')
        statements.extend(s.strip() for s in sql.split(';') if s.strip())
    tables = []
    for statement in statements:
        table = re.match(r'CREATE TABLE IF NOT EXISTS ([a-z_]+)\s*\(', statement)
        index = re.match(r'CREATE (?:UNIQUE )?INDEX IF NOT EXISTS ([a-z_]+)\s+ON\s+([a-z_]+)\s*\(', statement)
        need(table is not None or index is not None, 'unexpected_schema_statement')
        need((table[1] if table else index[2]) in NEW_TABLES, 'unexpected_schema_target')
        if table:
            tables.append(table[1])
    need(len(tables) == 5 and set(tables) == NEW_TABLES, 'unexpected_new_tables')
    with closing(sqlite3.connect(':memory:')) as con:
        for statement in statements:
            con.execute(statement)
        objects = shared.migration.objects(con)
        need(all(r[0] in ('table', 'index') and r[2] in NEW_TABLES for r in objects), 'unexpected_schema_object')
        columns = {name: con.execute('PRAGMA table_xinfo(' + name + ')').fetchall() for name in NEW_TABLES}
    sql = ';\n'.join(statements) + ';\n'
    return {'profile': 'finance_analysis66', 'sql': sql, 'sha256': hashlib.sha256(sql.encode()).hexdigest(),
            'sourceHashes': hashes, 'tables': sorted(NEW_TABLES), 'objects': objects, 'columns': columns}


def verify_baseline(value):
    need(len(BASE_TABLES) == 61, 'baseline_definition_changed')
    fingerprint = shared._fingerprint(value, False)
    need(fingerprint['membershipPhase'] == 'after' and value['userVersion'] == 0,
         'expected_61_table_baseline')


def verify_current(value, schema):
    need({n for n in value['rows'] if not n.startswith('sqlite_')} == BASE_TABLES | NEW_TABLES,
         'expected_66_table_profile')
    need([r for r in value['schema'] if r[2] in NEW_TABLES] == schema['objects'], 'analysis_schema_changed')
    need(all(value['columns'][n] == schema['columns'][n] for n in NEW_TABLES), 'analysis_columns_changed')
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
    return {'originalTablesPreserved': 61, 'newTables': 5, 'newTablesEmpty': True,
            'oldRowsSchemaAndSequencesPreserved': True}


def initialize_database(path, schema):
    """One transaction per household; callers first preserve the complete group."""
    with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=0)) as con:
        con.execute('PRAGMA trusted_schema=OFF')
        con.execute('BEGIN IMMEDIATE')
        try:
            for statement in schema['sql'].split(';'):
                if statement.strip():
                    con.execute(statement)
            con.commit()
        except BaseException:
            con.rollback()
            raise
    shared.migration.no_sidecars(path)
