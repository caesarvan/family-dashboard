"""Explicit 44 -> 47/48 additive media migration, with whole-group preservation.

The caller must stop all writers before snapshot/backup/migrate/check. This tool
never starts applications or restores a database. Each household is atomic;
an interrupted multi-household migration requires operator inspection.
"""
import argparse
import ast
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys

if __package__ in (None, ''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from deploy import check_journey_places_migration as legacy

ROOT = Path(__file__).resolve().parents[1]
BASE_TABLES = frozenset(legacy.BASE_TABLES | {'journey_places'})
PROFILES = {
    'media47': ('household_media.py',),
    'media48': ('household_media.py','media_playback.py'),
}
NEW_TABLES = {'media_imports','media_items','media_tv_grants'}
need = legacy.need
row_digest = legacy.row_digest
checked_path = legacy.checked_path
relative_database = legacy.relative_database


def schema_definition(root=ROOT, profile='media48'):
    need(profile in PROFILES, 'unknown_media_profile')
    root = Path(root).resolve(strict=True)
    statements = []
    for name in PROFILES[profile]:
        path = root / name
        need(path.is_file() and not path.is_symlink(), 'schema_source_missing')
        tree = ast.parse(path.read_text(encoding='utf-8'))
        values = [ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign)
                  and any(isinstance(target,ast.Name) and target.id=='SCHEMA_SQL' for target in node.targets)]
        need(len(values)==1 and isinstance(values[0],str), 'schema_literal_missing')
        statements.append(values[0])
    sql = '\n'.join(statements)
    expected = NEW_TABLES | ({'media_playback'} if profile=='media48' else set())
    with closing(sqlite3.connect(':memory:')) as con:
        # The account-removal trigger targets an existing parent. Dummy parents
        # allow validation of only the reviewed addition without importing app.
        for parent in ('users','devices','cloud_accounts','journey_workflows'):
            con.execute(f'CREATE TABLE {parent}(id TEXT PRIMARY KEY)')
        before = {r[0] for r in con.execute('SELECT name FROM sqlite_master')}
        con.executescript(sql)
        objects = [tuple(r) for r in con.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name') if r[1] not in before]
        need({r[1] for r in objects if r[0]=='table'}==expected, 'unexpected_new_tables')
        need(all(r[2] in expected or (r[0],r[1],r[2])==('trigger','media_account_removed','cloud_accounts') for r in objects), 'unexpected_schema_target')
    return {'profile':profile,'sql':sql,'sha256':hashlib.sha256(sql.encode()).hexdigest(),
            'tables':sorted(expected),'objects':[list(r) for r in objects]}


def fingerprint(path, *, immutable=False):
    path = Path(path).resolve(strict=True)
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro'+('&immutable=1' if immutable else ''),uri=True)) as con:
        con.execute('BEGIN')
        need(con.execute('PRAGMA quick_check').fetchall()==[('ok',)], 'database_integrity')
        need(con.execute('PRAGMA foreign_key_check').fetchall()==[], 'database_foreign_keys')
        objects = con.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall()
        tables = {}
        for kind,name,_,_ in objects:
            if kind != 'table':
                continue
            quoted = '"'+name.replace('"','""')+'"'
            rows = con.execute('SELECT * FROM '+quoted).fetchall()
            tables[name] = {'count':len(rows),'rowsSha256':row_digest(rows),
                            'columns':[list(r) for r in con.execute('PRAGMA table_xinfo('+quoted+')')],
                            'foreignKeys':[list(r) for r in con.execute('PRAGMA foreign_key_list('+quoted+')')]}
        return {'tables':tables,'schema':[list(r) for r in objects]}


def snapshot(root):
    root = Path(root).resolve(strict=True)
    registry_path = checked_path(root,'platform.sqlite3')
    registry = fingerprint(registry_path)
    need(set(registry['tables'])=={'households','household_invitations'},'registry_tables')
    with closing(sqlite3.connect(registry_path.as_uri()+'?mode=ro',uri=True)) as con:
        ids = sorted(row[0] for row in con.execute('SELECT id FROM households'))
    need(ids and 'default' in ids and len(ids)==len(set(ids)), 'household_registry')
    return {'registry':registry,'households':{uid:fingerprint(checked_path(root,relative_database(uid))) for uid in ids}}


def verify_baseline(before):
    need(before['households'], 'empty_household_group')
    for value in before['households'].values():
        actual = {name for name in value['tables'] if not name.startswith('sqlite_')}
        need(actual==BASE_TABLES, 'expected_44_table_baseline')


def verify_addition(before, after, schema):
    verify_baseline(before)
    need(before['registry']==after['registry'], 'registry_changed')
    need(set(before['households'])==set(after['households']), 'household_group_changed')
    addition = {r[1]:r for r in schema['objects']}
    for uid,old in before['households'].items():
        new = after['households'][uid]
        need(set(new['tables'])==set(old['tables'])|set(schema['tables']), 'table_set_changed')
        need(all(new['tables'][name]==value for name,value in old['tables'].items()), 'original_data_or_columns_changed')
        old_objects = {r[1]:r for r in old['schema']}
        new_objects = {r[1]:r for r in new['schema']}
        need(not (set(old_objects)&set(addition)), 'new_object_name_collides')
        need(new_objects=={**old_objects,**addition}, 'schema_change_not_exact_addition')
        need(all(new['tables'][name]['count']==0 for name in schema['tables']), 'new_table_not_empty')
    return {'originalTablesPreserved':44,'newTables':len(schema['tables']),
            'households':len(before['households']),'newTablesEmpty':True,'oldRowsSchemaAndSequencesPreserved':True}


def validate_backup(root,before,backup):
    root = Path(root).resolve(strict=True)
    name = backup['manifest']
    need(isinstance(name,str) and re.fullmatch(r'manifest-[0-9TZ]+\.json',name), 'backup_manifest_path')
    manifest_path = checked_path(root,'backups/'+name)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    expected = {'platform.sqlite3':before['registry'],**{relative_database(uid):value for uid,value in before['households'].items()}}
    found = set()
    for item in manifest['snapshots']:
        match = re.fullmatch(r'(backups|spaces/([a-f0-9]{24})/backups)/(household|platform)-[0-9TZ]+\.sqlite3',item['path'])
        need(match and not(match[2] and match[3]=='platform'), 'backup_mapping')
        target = 'platform.sqlite3' if match[3]=='platform' else relative_database(match[2] or 'default')
        need(target in expected and target not in found, 'backup_duplicate_or_extra')
        path = checked_path(root,item['path'])
        need(path.stat().st_nlink==1, 'backup_hardlink')
        need(all(not Path(str(path)+suffix).exists() and not Path(str(path)+suffix).is_symlink() for suffix in ('-wal','-shm','-journal')), 'backup_sidecar')
        need(path.stat().st_size==item['bytes'] and legacy.file_digest(path)==item['sha256'], 'backup_digest')
        need(fingerprint(path,immutable=True)==expected[target], 'backup_contents')
        found.add(target)
    need(found==set(expected) and type(backup['databases']) is int and backup['databases']==len(found), 'incomplete_backup_group')
    return {'groupVerified':True,'databases':len(found),'manifestSha256':legacy.file_digest(manifest_path)}


def migrate(root, before, backup, schema, *, source_root=ROOT):
    root = Path(root).resolve(strict=True)
    need(schema==schema_definition(source_root,schema.get('profile')), 'schema_changed_after_review')
    verify_baseline(before)
    need(snapshot(root)==before, 'database_changed_after_snapshot')
    validate_backup(root,before,backup)
    # No application imports, cloud calls or process starts. Refuse an already
    # migrated or mixed group instead of replaying an interrupted migration.
    for uid in sorted(before['households']):
        legacy.initialize_database(checked_path(root,relative_database(uid)),schema['sql'])
    return verify_addition(before,snapshot(root),schema)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('snapshot','validate-backup','migrate','check'))
    parser.add_argument('--data-root',type=Path,required=True)
    parser.add_argument('--profile',choices=tuple(PROFILES),default='media48')
    parser.add_argument('--source-root',type=Path,default=ROOT)
    parser.add_argument('--before',type=Path)
    parser.add_argument('--backup',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    need(not args.output.exists() and not args.output.is_symlink() and args.output.parent.is_dir(), 'output_must_be_new')
    schema=schema_definition(args.source_root,args.profile)
    before=json.loads(args.before.read_text(encoding='utf-8')) if args.before else None
    backup=json.loads(args.backup.read_text(encoding='utf-8')) if args.backup else None
    if args.action=='snapshot':
        result=snapshot(args.data_root);verify_baseline(result)
    elif args.action=='validate-backup':
        need(before is not None and backup is not None,'snapshot_and_backup_required')
        result=validate_backup(args.data_root,before,backup)
    elif args.action=='migrate':
        need(before is not None and backup is not None,'snapshot_and_backup_required')
        result=migrate(args.data_root,before,backup,schema,source_root=args.source_root)
    else:
        need(before is not None,'snapshot_required')
        result=verify_addition(before,snapshot(args.data_root),schema)
    with args.output.open('x',encoding='utf-8') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2)
    args.output.chmod(0o600)
    print(json.dumps({'action':args.action,'profile':args.profile,'schemaSha256':schema['sha256'],'verified':True}))


if __name__=='__main__':
    main()
