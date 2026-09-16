"""Synthetic SQLite only; no production input or migration replay."""
import copy
import json
from pathlib import Path
import sqlite3

import pytest
import finance_hub

from app import create_app
from deploy.backup import backup_all
from deploy import check_media_migration as migration


@pytest.fixture(autouse=True)
def historical_without_investment_operations(monkeypatch):
    """This suite models schemas predating the 55th operation-receipt table."""
    import investment_operations
    monkeypatch.setattr(investment_operations, "INVESTMENT_OPERATIONS_SCHEMA_SQL", "")


@pytest.fixture(params=['media47','media48'])
def group(tmp_path,monkeypatch,request):
    # Historical 44->47/48 fixture: the later inventory registrar is excluded
    # only here; current 53-table factory/restore tests keep it enabled.
    monkeypatch.setattr('app.register_inventory',lambda *_args,**_kwargs:None)
    password='synthetic-migration-password'
    monkeypatch.setenv('MEMBER1_PASSWORD',password);monkeypatch.setenv('MEMBER2_PASSWORD',password)
    with monkeypatch.context() as historical:
        historical.setattr(finance_hub, 'FINANCE_IMPORT_RECEIPTS_SCHEMA_SQL', '')
        app=create_app({'TESTING':True,'DATA_DIR':str(tmp_path),'SECRET_KEY':'synthetic-media-migration-secret',
                        'SESSION_COOKIE_SECURE':False,'GOOGLE_CLIENT_ID':'','GOOGLE_CLIENT_SECRET':'',
                        'MICROSOFT_CLIENT_ID':'','MICROSOFT_CLIENT_SECRET':'','NVIDIA_API_KEY':'','OPENAI_API_KEY':''})
    registry=tmp_path/'platform.sqlite3'
    with sqlite3.connect(registry) as con:
        default=con.execute("SELECT * FROM households WHERE id='default'").fetchone()
        columns=[r[1] for r in con.execute('PRAGMA table_info(households)')]
        item=dict(zip(columns,default));item.update(id='b'*24,slug='synthetic-second',name='合成家庭二')
        con.execute('INSERT INTO households('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')',tuple(item[k] for k in columns))
    source=tmp_path/'household.sqlite3'
    for path in [source,tmp_path/'spaces'/('b'*24)/'household.sqlite3']:
        if path!=source:
            path.parent.mkdir(parents=True)
            with sqlite3.connect(source) as original,sqlite3.connect(path) as target:
                original.backup(target)
        with sqlite3.connect(path) as con:
            # If app already initializes media, derive the old schema only in
            # this disposable fixture. No tool entrypoint removes tables.
            con.execute('PRAGMA foreign_keys=OFF')
            con.execute('DROP TRIGGER IF EXISTS media_account_removed')
            for table in ('media_playback','media_tv_grants','media_items','media_imports'):
                con.execute('DROP TABLE IF EXISTS '+table)
            con.execute("INSERT INTO audit(actor,action,target,stamp) VALUES('member1','synthetic_old_row','keep','2026-09-16')")
    before=migration.snapshot(tmp_path);migration.verify_baseline(before)
    return tmp_path,before,backup_all(tmp_path),migration.schema_definition(profile=request.param)


def test_real_two_household_addition_preserves_all_old_rows_and_trigger_parent(group):
    root,before,backup,schema=group
    result=migration.migrate(root,before,backup,schema)
    assert result['households']==2 and result['originalTablesPreserved']==44 and result['newTables']==len(schema['tables'])
    after=migration.snapshot(root)
    for value in after['households'].values():
        assert len([n for n in value['tables'] if not n.startswith('sqlite_')])==44+len(schema['tables'])
        assert any(r[:3]==['trigger','media_account_removed','cloud_accounts'] for r in value['schema'])
    assert migration.verify_addition(before,after,schema)==result
    with pytest.raises(RuntimeError,match='database_changed_after_snapshot'):
        migration.migrate(root,before,backup,schema)


def test_missing_backup_or_tamper_fails_before_any_ddl(group):
    root,before,backup,schema=group
    broken=copy.deepcopy(backup);broken['databases']=1
    with pytest.raises(RuntimeError,match='incomplete_backup_group'):
        migration.migrate(root,before,broken,schema)
    assert migration.snapshot(root)==before
    manifest=root/'backups'/backup['manifest']
    data=json.loads(manifest.read_text());data['snapshots'][0]['sha256']='0'*64
    manifest.write_text(json.dumps(data))
    with pytest.raises(RuntimeError,match='backup_digest'):
        migration.migrate(root,before,backup,schema)
    assert migration.snapshot(root)==before


def test_modified_schema_input_cannot_bypass_source_binding(group):
    root,before,backup,schema=group
    changed=copy.deepcopy(schema);changed['sql']+='\nDROP TABLE users;'
    with pytest.raises(RuntimeError,match='schema_changed_after_review'):
        migration.migrate(root,before,backup,changed)
    assert migration.snapshot(root)==before


def test_changed_old_data_and_extra_schema_are_detected(group):
    root,before,backup,schema=group
    migration.migrate(root,before,backup,schema)
    with sqlite3.connect(root/'household.sqlite3') as con:
        con.execute("UPDATE audit SET target='unexpected' WHERE action='synthetic_old_row'")
    with pytest.raises(RuntimeError,match='original_data_or_columns_changed'):
        migration.verify_addition(before,migration.snapshot(root),schema)


def test_added_object_on_old_parent_must_be_exact(group):
    root,before,backup,schema=group
    migration.migrate(root,before,backup,schema)
    with sqlite3.connect(root/'household.sqlite3') as con:
        con.execute('CREATE INDEX unexpected_parent_index ON cloud_accounts(owner)')
    with pytest.raises(RuntimeError,match='schema_change_not_exact_addition'):
        migration.verify_addition(before,migration.snapshot(root),schema)


def test_mixed_group_is_rejected_without_replay(group):
    root,before,backup,schema=group
    migration.legacy.initialize_database(root/'household.sqlite3',schema['sql'])
    mixed=migration.snapshot(root)
    with pytest.raises(RuntimeError,match='database_changed_after_snapshot'):
        migration.migrate(root,before,backup,schema)
    assert migration.snapshot(root)==mixed


def test_schema_profiles_are_explicit_and_require_real_playback_source(tmp_path):
    with pytest.raises(RuntimeError,match='unknown_media_profile'):
        migration.schema_definition(profile='anything')
    (tmp_path/'household_media.py').write_text("SCHEMA_SQL='CREATE TABLE other(id);'")
    with pytest.raises(RuntimeError,match='unexpected_new_tables'):
        migration.schema_definition(tmp_path,'media47')
    with pytest.raises(RuntimeError,match='schema_source_missing'):
        migration.schema_definition(tmp_path,'media48')
