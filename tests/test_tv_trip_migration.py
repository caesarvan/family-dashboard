"""Stopped synthetic two-household 75/9 -> 77/9 and complete-group restores.

Fixed local Git supplies the real parent app; no historical DDL is copied.
Production writers, Linux service management and real data are out of scope.
"""
from contextlib import closing
import json
from pathlib import Path
import shutil
import socket
import sqlite3

import pytest
from deploy import check_tv_trip_migration as data
from deploy import tv_trip_release_data as current
from deploy import membership_release_data as shared
from test_membership_migration import materialize, startup, clone_databases
from test_task_reminders_migration import documented_restore
from test_assistant_trip_change_release_data import execute
from test_journey_finance_migration import populate as populate_allocations

ROOT = Path(__file__).resolve().parents[1]
PARENT = 'e8f0427b35157074d179bc4de86a7c5c4db0a755'
ERRORS = (shared.ReleaseDataError, shared.migration.MigrationCheckError)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError('No external network in migration tests')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket, 'create_connection', deny)


@pytest.fixture(scope='module')
def baseline75(tmp_path_factory):
    base = tmp_path_factory.mktemp('tv-trip-parent75')
    source = base / 'source'
    hashes = materialize(source, PARENT)
    assert startup(source, base / 'seed', 'seed')['households'] == 2
    root = base / 'closed'; clone_databases(base / 'seed', root)
    for path in root.rglob('household.sqlite3'):
        execute(path, """
          PRAGMA foreign_keys=ON;
          INSERT INTO hub_transactions VALUES('payment','member1','fingerprint','{"amountCents":5000,"kind":"payments","flow":"expense"}',1,'now');
          INSERT INTO hub_import_receipts VALUES('member1','import-request','digest','token','{}','now');
          INSERT INTO hub_shopping_settlements VALUES('shopping-link','member1','payment','gone-shopping',1000,'active',1,'{}','{}',1,'{}','digest','now','now');
          INSERT INTO hub_shopping_settlement_receipts VALUES('shopping-receipt','member1','nonce','apply','shopping-link','{}','now');
          INSERT INTO entities(id,kind,data,updated_at) VALUES('trip','trips','{"journeyId":"journey","budget":100,"paid":7,"saved":8}','now');
          INSERT INTO journey_workflows VALUES('journey','trip','{}',1,'member1','now','now');
          INSERT INTO task_reminders VALUES('member1','gone-task','2026-09-20','read',NULL,3,0,'now','now');
          INSERT INTO task_reminder_operations VALUES('member1','retained-read','digest','{}','now');
          INSERT INTO settings(id,data) VALUES('task-reminders-worker','{"heartbeat":"retained"}');
          INSERT INTO media_imports(id,owner,request_id,request_key,state,created_at,updated_at,expires_at,confirm_request_id,confirm_key,context_cipher)
            VALUES('import','member1','selection','digest','confirmed',1,2,3,'confirmation','confirm-digest',X'ABCD');
          INSERT INTO media_items(id,owner,import_id,source_key,state,visibility,metadata_cipher,preview_cipher,preview_key,created_at,updated_at,confirmed_at)
            VALUES('private','member1','import','source','ready','private',X'AB',X'CD','preview',1,2,2);
          INSERT INTO devices(id,secret_hash,name,approved,expires,created_at) VALUES('tv','synthetic','TV',1,9999999999,'now');
          INSERT INTO media_tv_grants VALUES('private','tv','member1',1);
          INSERT INTO media_playback VALUES('tv','photos',0,10,0,1,1,1);
          INSERT INTO media_video_cache VALUES('private','video',X'010203',1);
          INSERT INTO media_playback_progress VALUES('tv','private',1,'111111111111111111111111',2500,3,2);
        """)
    populate_allocations(root)  # Nonempty old allocation and receipt tables must survive.
    snapshot = data.snapshot_baseline(root)
    (base / 'identity.json').write_text(json.dumps({'head':PARENT,'sourceHashes':hashes,'snapshot':snapshot}), encoding='utf8')
    return root


@pytest.fixture(scope='module')
def source(tmp_path_factory):
    path = tmp_path_factory.mktemp('tv-trip-candidate')
    hashes = {}
    for p in ROOT.glob('*.py'):
        raw = p.read_bytes(); (path / p.name).write_bytes(raw)
        hashes[p.name] = shared.migration.file_digest(p)
    identity = {'head':'a'*40,'tree':'b'*40,'imageId':'sha256:'+'c'*64,
                'sourceHashes':hashes,'runtimeHashes':hashes}
    return path, identity


@pytest.fixture
def group(baseline75, tmp_path, source):
    root = tmp_path / 'live'; clone_databases(baseline75, root)
    (root / shared.ROOT_ATTEMPT).write_bytes(b'{"syntheticSuccessfulAttempt":true}\n')
    proof = tmp_path / 'proof'; proof.mkdir()
    return root, proof, {'source_identity':source[1],'plan_sha256':'a'*64,
                         'marker_sha256':data.marker_digest(root)}


def child(root):
    return next((root / 'spaces').rglob('household.sqlite3'))


def edit(path, sql):
    with closing(sqlite3.connect(path)) as con:
        con.execute(sql); con.commit()


def migrate(group):
    root, proof, kwargs = group
    data.begin(root, proof, **kwargs)
    return data.migrate(root, proof, **kwargs)


def populate(root):
    for path in root.rglob('household.sqlite3'):
        execute(path,"""
          PRAGMA foreign_keys=ON;
          INSERT INTO devices(id,secret_hash,name,approved,expires,created_at)
            VALUES('dddddddddddddddddddddddd','synthetic-second','Second TV',1,9999999999,'now');
          INSERT INTO media_playback VALUES('dddddddddddddddddddddddd','photos',1,15,0,1,4,1);
          INSERT INTO media_playback_journeys VALUES
            ('tv','journey',NULL,0,'member1','11111111111111111111111111111111',1,2),
            ('dddddddddddddddddddddddd',NULL,NULL,1,NULL,'22222222222222222222222222222222',1,2);
          INSERT INTO media_playback_operations VALUES
            ('member1','11111111111111111111111111111111','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
             'dddddddddddddddddddddddd','journey_start',1,2),
            ('member1','22222222222222222222222222222222','bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
             'cccccccccccccccccccccccc','journey_start',2,3),
            ('member2','33333333333333333333333333333333','cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
             'dddddddddddddddddddddddd','journey_start',3,4);
        """)


def test_two_household_exact_addition_actual_app_only_restart_and_empty_tables(group, source):
    root, proof, kwargs = group
    result = migrate(group)
    assert (result['households'],result['databases']) == (2,3)
    assert all(c == {'originalTablesPreserved':75,'newTables':2,'newTablesEmpty':True,
                     'oldRowsSchemaAndSequencesPreserved':True} for c in result['comparisons'].values())
    assert startup(source[0], root, 'restart')['households'] == 2
    after = data.check_stopped(root, proof, **kwargs)
    assert after['logicalSha256'] == result['logicalSha256']
    assert len(list((proof / 'backup-group').rglob('*.sqlite3'))) == 3
    definition = data.schema_definition()
    assert len(definition['objects']) == 4  # Two tables and their automatic PK indexes
    assert not any(r[0] == 'trigger' for r in definition['objects'])
    for path in root.rglob('household.sqlite3'):
        value = shared.migration._read(path)
        assert len(set(value['rows']) - {'sqlite_sequence'}) == 77
        assert all(not value['rows'][n] for n in data.NEW_TABLES)
        assert any(r[:3] == ('trigger','media_video_deleted','media_items') for r in value['schema'])
    originals = {p.name:p.read_bytes() for p in proof.glob('*.json')}
    with pytest.raises(ERRORS + (FileExistsError,)): data.migrate(root, proof, **kwargs)
    with pytest.raises(FileExistsError): data.check_stopped(root, proof, **kwargs)
    assert originals == {p.name:p.read_bytes() for p in proof.glob('*.json')}


@pytest.mark.parametrize('target,sql', [
    ('default',"UPDATE private_finance SET data='{}'"),
    ('child',"UPDATE sqlite_sequence SET seq=seq+1 WHERE name='audit'"),
    ('child','CREATE INDEX accidental ON users(name)'),
    ('platform',"UPDATE households SET name='changed' WHERE id='default'"),
    ('default',"UPDATE settings SET revision=revision+1 WHERE id='task-reminders-worker'"),
    ('child','DELETE FROM task_reminder_operations'),
    ('child','DROP TRIGGER media_video_deleted'),
    ('default','UPDATE media_playback_progress SET position_ms=position_ms+1'),
    ('default','DROP INDEX hub_journey_allocations_payment'),
    ('child',"INSERT INTO media_playback_operations VALUES('member1','44444444444444444444444444444444','dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd','dddddddddddddddddddddddd','journey_start',1,1)"),
])
def test_stopped_check_rejects_old_schema_rows_sequences_and_new_table_drift(group, target, sql):
    root, proof, kwargs = group; migrate(group)
    path = child(root) if target == 'child' else root / ('platform.sqlite3' if target == 'platform' else 'household.sqlite3')
    edit(path, sql)
    with pytest.raises(ERRORS): data.check_stopped(root, proof, **kwargs)
    assert not (proof / 'result.json').exists()


@pytest.mark.parametrize('fault', ['marker','backup-missing','backup-bytes','old-row','plan','manifest-path','runtime-identity'])
def test_preflight_failure_preserves_all_databases_without_migration_attempt(group, fault):
    root, proof, kwargs = group; data.begin(root, proof, **kwargs)
    if fault == 'marker': (root / shared.ROOT_ATTEMPT).write_bytes(b'changed')
    elif fault == 'backup-missing': next((proof / 'backup-group/spaces').rglob('*.sqlite3')).unlink()
    elif fault == 'backup-bytes':
        p = next((proof / 'backup-group/spaces').rglob('*.sqlite3')); raw=bytearray(p.read_bytes()); raw[-1]^=1; p.write_bytes(raw)
    elif fault == 'old-row': edit(child(root),"UPDATE hub_transactions SET revision=revision+1")
    elif fault == 'plan': kwargs = dict(kwargs, plan_sha256='b'*64)
    elif fault == 'manifest-path':
        p=proof/'backup.json'; r=json.loads(p.read_bytes());r['manifest']='../before.json';p.write_text(json.dumps(r))
    else:
        identity=dict(kwargs['source_identity'],runtimeHashes={**kwargs['source_identity']['runtimeHashes'],'media_trip_playback.py':'0'*64})
        kwargs=dict(kwargs,source_identity=identity)
        p=proof/'attempt.json';r=json.loads(p.read_bytes());r['sourceIdentity']=identity;r['sourceIdentitySha256']=shared._digest(identity);p.write_text(json.dumps(r))
    before=shared.snapshot(root)
    with pytest.raises(ERRORS): data.migrate(root, proof, **kwargs)
    assert shared.snapshot(root)==before and not (proof/'migration-attempt.json').exists()


@pytest.mark.parametrize('partial',[False,True])
def test_real_second_household_lock_partial_failure_and_complete_75_rollback(group,tmp_path,monkeypatch,partial):
    root,proof,kwargs=group;data.begin(root,proof,**kwargs)
    if partial:
        # An actual SQLite shared lock allows the first household commit but
        # denies the second commit. No replacement of migration/backup methods.
        with closing(sqlite3.connect(child(root))) as reader:
            reader.execute('BEGIN');reader.execute('SELECT count(*) FROM users').fetchone()
            with pytest.raises(sqlite3.OperationalError,match='locked'): data.migrate(root,proof,**kwargs)
        assert data.NEW_TABLES <= set(shared.migration._read(root/'household.sqlite3')['rows'])
        assert not (data.NEW_TABLES & set(shared.migration._read(child(root))['rows']))
        assert (proof/'migration-attempt.json').exists() and not (proof/'migration-result.json').exists()
    else: data.migrate(root,proof,**kwargs)
    with pytest.raises(ERRORS+(FileExistsError,)):data.migrate(root,proof,**kwargs)
    receipt=json.loads((proof/'backup.json').read_bytes());restored=tmp_path/'rollback'
    documented_restore(proof/'backup-group',receipt['manifest'],restored,(root/shared.ROOT_ATTEMPT).read_bytes(),monkeypatch)
    assert data.verify_rollback(proof,restored)['completeGroupRestored']
    with pytest.raises(ERRORS+(FileExistsError,)):data.migrate(restored,proof,**kwargs)
    edit(child(restored),"UPDATE hub_transactions SET revision=revision+1")
    with pytest.raises(ERRORS):data.verify_rollback(proof,restored)


def test_populated77_restart_backup_and_documented_complete_restore_preserve_orphans(group,source,tmp_path,monkeypatch):
    root,proof,kwargs=group;migrate(group);data.check_stopped(root,proof,**kwargs);populate(root)
    for path in root.rglob('household.sqlite3'):
        execute(path,"PRAGMA foreign_keys=ON; DELETE FROM entities WHERE id='trip'; DELETE FROM hub_transactions WHERE id='payment';")
    reference=current.snapshot_current(root)
    proof77=tmp_path/'current77-proof';proof77.mkdir();current.begin(root,proof77,**kwargs)
    assert startup(source[0],root,'restart')['households']==2
    checked=current.check_stopped(root,proof77,**kwargs)
    assert checked['logicalSha256']==shared._digest(shared._logical(reference))
    receipt=json.loads((proof77/'backup.json').read_bytes())
    assert current.validate_backup(root,reference,proof77/'backup-group/backups'/receipt['manifest'])['databases']==3
    restored=tmp_path/'restored77'
    documented_restore(proof77/'backup-group',receipt['manifest'],restored,(root/shared.ROOT_ATTEMPT).read_bytes(),monkeypatch)
    assert current.verify_restore(reference,restored,marker_sha256=kwargs['marker_sha256'])['completeGroupRestored']
    for name,value in reference['databases'].items():
        if name!='platform.sqlite3':
            assert value['tables']['media_playback_journeys']['count']==2
            assert value['tables']['media_playback_operations']['count']==3
    edit(child(restored),'DELETE FROM media_playback_operations')
    with pytest.raises(ERRORS):current.verify_restore(reference,restored,marker_sha256=kwargs['marker_sha256'])
    with pytest.raises(FileExistsError):current.begin(root,proof77,**kwargs)


def test_second_table_ddl_error_rolls_back_actual_initializer(group,monkeypatch):
    path=group[0]/'household.sqlite3';before=shared.migration._read(path);schema=data.schema_definition()
    original=sqlite3.connect;observed=[]
    def connect(*args,**kwargs):
        con=original(*args,**kwargs)
        if args[0]==path.as_uri()+'?mode=rw':
            def gate(code,a,b,*rest):
                observed.append((code,a,b))
                return sqlite3.SQLITE_DENY if code==sqlite3.SQLITE_CREATE_TABLE and a=='media_playback_operations' else sqlite3.SQLITE_OK
            con.set_authorizer(gate)
        return con
    monkeypatch.setattr(sqlite3,'connect',connect)
    with pytest.raises(sqlite3.DatabaseError,match='authorized'):data.initialize_database(path,schema)
    assert any(code==sqlite3.SQLITE_CREATE_TABLE and a=='media_playback_journeys' for code,a,b in observed)
    assert shared.migration._read(path)==before


@pytest.mark.parametrize('fault',['schema','import','initializer-hash'])
def test_fixed_initializer_schema_and_import_closure_reject_drift(group,monkeypatch,fault):
    root,proof,kwargs=group;data.begin(root,proof,**kwargs)
    if fault=='schema':
        m=data.runtime_module('media_trip_playback');monkeypatch.setattr(m,'SCHEMA_SQL',m.SCHEMA_SQL+'CREATE TABLE extra(id);')
    elif fault.endswith('import'):
        m=data.runtime_module('media_trip_playback')
        monkeypatch.setattr(m,'__file__',str(ROOT/'app.py'))
    else:monkeypatch.setattr(data,'MODULE_SHA256','0'*64)
    before=shared.snapshot(root)
    with pytest.raises(ERRORS):data.migrate(root,proof,**kwargs)
    assert shared.snapshot(root)==before and not (proof/'migration-attempt.json').exists()


@pytest.mark.parametrize('fault',['old73','partial76','name-collision','unregistered'])
def test_wrong_baseline_or_name_collision_rejected_before_backup(group,fault):
    root,proof,kwargs=group
    if fault=='unregistered':
        p=root/'spaces'/('f'*24);p.mkdir();shutil.copyfile(root/'household.sqlite3',p/'household.sqlite3')
    else:
        execute(root/'household.sqlite3',{
            'old73':'DROP TABLE hub_journey_allocation_operations; DROP TABLE hub_journey_allocations;',
            'partial76':'CREATE TABLE media_playback_journeys(id TEXT);',
            'name-collision':'CREATE INDEX media_playback_operations ON users(name);'}[fault])
    with pytest.raises(ERRORS):data.begin(root,proof,**kwargs)
    assert not list(proof.iterdir()) and not (root/'backups').exists()


def test_active_nonempty_wal_is_not_checkpointed(group):
    root,proof,kwargs=group;path=root/'household.sqlite3'
    with closing(sqlite3.connect(path)) as con:
        con.execute('PRAGMA journal_mode=WAL');con.execute('PRAGMA wal_autocheckpoint=0')
        con.execute("UPDATE private_finance SET data='{}'");con.commit()
        wal=Path(str(path)+'-wal');assert wal.stat().st_size>0
        before=(shared.migration.file_digest(path),shared.migration.file_digest(wal))
        with pytest.raises(ERRORS):data.begin(root,proof,**kwargs)
        assert before==(shared.migration.file_digest(path),shared.migration.file_digest(wal))
        assert not list(proof.iterdir())


@pytest.mark.parametrize('which',['platform','second'])
def test_restore_missing_group_member_cannot_pass(group,tmp_path,monkeypatch,which):
    root,proof,kwargs=group;migrate(group)
    receipt=json.loads((proof/'backup.json').read_bytes());restored=tmp_path/'restore'
    documented_restore(proof/'backup-group',receipt['manifest'],restored,(root/shared.ROOT_ATTEMPT).read_bytes(),monkeypatch)
    (restored/'platform.sqlite3' if which=='platform' else child(restored)).unlink()
    with pytest.raises(ERRORS):data.verify_rollback(proof,restored)
