"""Real synthetic two-household 71/9 -> 73/9 SQLite and complete-group restores.

Historical app startup creates only the baseline fixture; migration never starts
an app, worker, decoder or network client. No real user data is used.
"""
from contextlib import closing
import json
from pathlib import Path
import shutil
import socket
import sqlite3

import pytest
from deploy import check_media_video_migration as data
from deploy import media_video_release_data as current
from deploy import membership_release_data as shared
from test_membership_migration import materialize, startup, clone_databases
from test_task_reminders_migration import documented_restore
from test_assistant_trip_change_release_data import execute

ROOT = Path(__file__).resolve().parents[1]
PARENT = '8d3e6376a606155ff66a0388e43d04cb7562fe9f'
ERRORS = (shared.ReleaseDataError, shared.migration.MigrationCheckError)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError('No external network in migration tests')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket, 'create_connection', deny)


@pytest.fixture(scope='module')
def baseline71(tmp_path_factory):
    base = tmp_path_factory.mktemp('video-parent71')
    source = base / 'source'
    hashes = materialize(source, PARENT)
    assert startup(source, base / 'seed', 'seed')['households'] == 2
    root = base / 'closed'; clone_databases(base / 'seed', root)
    for path in root.rglob('household.sqlite3'):
        execute(path, """
          PRAGMA foreign_keys=ON;
          INSERT INTO task_reminders VALUES('member1','gone-task','2026-09-20','read',NULL,3,0,'now','now');
          INSERT INTO task_reminders VALUES('member2','live-task','2026-09-21',NULL,'later',4,1,'now','now');
          INSERT INTO task_reminder_operations VALUES('member1','retained-read','digest','{"revision":3}','now');
          INSERT INTO task_reminder_operations VALUES('member2','retained-snooze','digest','{"revision":4}','now');
          INSERT INTO settings(id,data) VALUES('task-reminders-worker','{"heartbeat":"retained"}');
          INSERT INTO entities(id,kind,data,updated_at) VALUES
            ('private-calendar','events','{"title":"synthetic private","visibility":"private","createdBy":"member1"}','now');
          INSERT INTO media_imports(id,owner,request_id,request_key,state,created_at,updated_at,expires_at,
            confirm_request_id,confirm_key,context_cipher) VALUES
            ('import','member1','selection','digest','confirmed',1,2,3,'confirmation','confirm-digest',X'ABCD');
          INSERT INTO media_items(id,owner,import_id,source_key,state,visibility,metadata_cipher,preview_cipher,
            preview_key,created_at,updated_at,confirmed_at) VALUES
            ('legacy-private','member1','import','source1','ready','private',X'AB',X'CD','preview1',1,2,2),
            ('legacy-shared','member1','import','source2','ready','shared',X'EF',X'12','preview2',1,2,2);
          INSERT INTO media_items(id,owner,import_id,source_key,state,visibility,created_at,updated_at,deleted_at,delete_revision)
            VALUES('legacy-deleted','member1','import','source3','deleted','private',1,2,2,1);
          INSERT INTO devices(id,secret_hash,name,approved,expires,created_at) VALUES
            ('tv1','synthetic','One',1,9999999999,'now'),('tv2','synthetic','Two',1,9999999999,'now');
          INSERT INTO media_tv_grants VALUES('legacy-shared','tv1','member1',1);
          INSERT INTO media_playback VALUES('tv1','photos',0,10,0,1,1,1),('tv2','photos',1,10,0,1,2,1);
        """)
    baseline = data.snapshot_baseline(root)
    (base / 'source-identity.json').write_text(json.dumps({'head': PARENT, 'hashes': hashes, 'snapshot': baseline}), encoding='utf8')
    return root


@pytest.fixture(scope='module')
def identity():
    hashes = {p.name: shared.migration.file_digest(p) for p in ROOT.glob('*.py')}
    return {'head': 'a' * 40, 'tree': 'b' * 40, 'imageId': 'sha256:' + 'c' * 64,
            'sourceHashes': hashes, 'runtimeHashes': hashes}


@pytest.fixture
def group(baseline71, tmp_path, identity):
    root = tmp_path / 'live'; clone_databases(baseline71, root)
    (root / shared.ROOT_ATTEMPT).write_bytes(b'{"syntheticSuccessfulAttempt":true}\n')
    proof = tmp_path / 'proof'; proof.mkdir()
    return root, proof, {'source_identity': identity, 'plan_sha256': 'a' * 64,
                         'marker_sha256': data.marker_digest(root)}


def edit(path, sql):
    with closing(sqlite3.connect(path)) as con:
        con.execute(sql); con.commit()


def child(root):
    return next((root / 'spaces').rglob('household.sqlite3'))


def migrate(group):
    root, proof, kwargs = group
    data.begin(root, proof, **kwargs)
    return data.migrate(root, proof, **kwargs)


def populate(root):
    for relative in shared.enumerate_databases(root):
        if relative == 'platform.sqlite3': continue
        execute(root / relative, """
          PRAGMA foreign_keys=ON;
          INSERT INTO media_video_cache VALUES('legacy-private','video1',X'010203',1),('legacy-shared','video2',X'040506',2);
          INSERT INTO media_playback_progress VALUES
            ('tv1','legacy-shared',1,'111111111111111111111111',2500,3,2),
            ('tv2','legacy-private',1,'222222222222222222222222',3000,4,3);
        """)


def test_exact_two_household_addition_and_complete_stopped_proof(group):
    root, proof, kwargs = group
    before = data.snapshot_baseline(root)
    result = migrate(group)
    assert (result['households'], result['databases']) == (2, 3)
    assert all(v == {'originalTablesPreserved':71, 'newTables':2, 'newTablesEmpty':True,
                     'oldRowsSchemaAndSequencesPreserved':True} for v in result['comparisons'].values())
    after = data.check_stopped(root, proof, **kwargs)
    assert after['logicalSha256'] == result['logicalSha256']
    assert data.marker_digest(root) == kwargs['marker_sha256']
    assert len(list((proof / 'backup-group').rglob('*.sqlite3'))) == 3
    schema = data.schema_definition()
    assert any(row[:3] == ('trigger','media_video_deleted','media_items') for row in schema['objects'])
    assert len(data._statements(schema['sql'])) == 3
    for name in before['databases']:
        if name != 'platform.sqlite3':
            live = shared.migration._read(root / name)
            assert set(live['rows']) - {'sqlite_sequence'} == data.BASE_TABLES | data.NEW_TABLES
            assert all(not live['rows'][n] for n in data.NEW_TABLES)
            assert len(live['rows']['media_items']) == 3 and len(live['rows']['task_reminder_operations']) == 2
    evidence = {p.name:p.read_bytes() for p in proof.glob('*.json')}
    with pytest.raises(ERRORS + (FileExistsError,)): data.migrate(root, proof, **kwargs)
    with pytest.raises(FileExistsError): data.check_stopped(root, proof, **kwargs)
    assert evidence == {p.name:p.read_bytes() for p in proof.glob('*.json')}


@pytest.mark.parametrize('target,sql', [
    ('default', "UPDATE private_finance SET data='{}'"),
    ('child', "UPDATE sqlite_sequence SET seq=seq+1 WHERE name='audit'"),
    ('child', 'CREATE INDEX accidental ON users(name)'),
    ('default', 'ALTER TABLE users ADD COLUMN accidental TEXT'),
    ('platform', "UPDATE households SET name='changed' WHERE id='default'"),
    ('child', "DELETE FROM task_reminder_operations WHERE request_id='retained-read'"),
    ('default', "UPDATE settings SET revision=revision+1 WHERE id='task-reminders-worker'"),
    ('child', 'DROP TRIGGER media_video_deleted'),
    ('default', "INSERT INTO media_video_cache VALUES('legacy-private','video',X'01',1)"),
])
def test_any_old_data_schema_or_new_table_drift_is_rejected(group, target, sql):
    root, proof, kwargs = group; migrate(group)
    path = child(root) if target == 'child' else root / ('platform.sqlite3' if target == 'platform' else 'household.sqlite3')
    edit(path, sql)
    with pytest.raises(ERRORS): data.check_stopped(root, proof, **kwargs)
    assert not (proof / 'result.json').exists()


@pytest.mark.parametrize('fault', ['marker','backup-omitted','backup-bytes','old-row','plan','manifest-path'])
def test_preflight_failure_never_writes_migration_attempt_or_ddl(group, fault):
    root, proof, kwargs = group; data.begin(root, proof, **kwargs)
    if fault == 'marker': (root / shared.ROOT_ATTEMPT).write_bytes(b'changed')
    elif fault == 'backup-omitted': next((proof / 'backup-group/spaces').rglob('*.sqlite3')).unlink()
    elif fault == 'backup-bytes':
        path = next((proof / 'backup-group/spaces').rglob('*.sqlite3'))
        raw = bytearray(path.read_bytes()); raw[-1] ^= 1; path.write_bytes(raw)
    elif fault == 'old-row': edit(child(root), "UPDATE private_finance SET data='{}'")
    elif fault == 'plan': kwargs = dict(kwargs, plan_sha256='b' * 64)
    else:
        path = proof / 'backup.json'; value = json.loads(path.read_bytes()); value['manifest'] = '../before.json'; path.write_text(json.dumps(value))
    original = shared.snapshot(root)
    with pytest.raises(ERRORS): data.migrate(root, proof, **kwargs)
    assert shared.snapshot(root) == original and not (proof / 'migration-attempt.json').exists()


@pytest.mark.parametrize('partial', [False, True])
def test_full71_rollback_after_complete_or_partial_migration_is_not_replay(group, tmp_path, monkeypatch, partial):
    root, proof, kwargs = group; data.begin(root, proof, **kwargs)
    if partial:
        original = data.initialize_database; calls = []
        def fail_second(path, schema):
            calls.append(path)
            if len(calls) == 2: raise RuntimeError('synthetic second household failure')
            original(path, schema)
        with monkeypatch.context() as patch:
            patch.setattr(data, 'initialize_database', fail_second)
            with pytest.raises(RuntimeError, match='second household'): data.migrate(root, proof, **kwargs)
        assert (proof / 'migration-attempt.json').exists() and not (proof / 'migration-result.json').exists()
    else: data.migrate(root, proof, **kwargs)
    with pytest.raises(ERRORS + (FileExistsError,)): data.migrate(root, proof, **kwargs)
    receipt = json.loads((proof / 'backup.json').read_bytes()); restored = tmp_path / 'rollback'
    documented_restore(proof / 'backup-group', receipt['manifest'], restored, (root / shared.ROOT_ATTEMPT).read_bytes(), monkeypatch)
    assert data.verify_rollback(proof, restored)['completeGroupRestored']
    # Even a restored old group cannot reuse the retained migration attempt.
    with pytest.raises(ERRORS + (FileExistsError,)): data.migrate(restored, proof, **kwargs)


def test_populated73_backup_preservation_and_actual_complete_restore(group, tmp_path, monkeypatch):
    root, proof, kwargs = group; migrate(group); data.check_stopped(root, proof, **kwargs); populate(root)
    reference = current.snapshot_current(root)
    next_proof = tmp_path / 'current-proof'; next_proof.mkdir()
    before = current.begin(root, next_proof, **kwargs)
    after = current.check_stopped(root, next_proof, **kwargs)
    assert before['logicalSha256'] == after['logicalSha256'] and after['databases'] == 3
    receipt = json.loads((next_proof / 'backup.json').read_bytes())
    validated = current.validate_backup(root, reference, next_proof / 'backup-group/backups' / receipt['manifest'])
    assert validated['databases'] == 3
    restored = tmp_path / 'restored73'
    documented_restore(next_proof / 'backup-group', receipt['manifest'], restored, (root / shared.ROOT_ATTEMPT).read_bytes(), monkeypatch)
    assert current.verify_restore(reference, restored, marker_sha256=kwargs['marker_sha256'])['completeGroupRestored']
    for value in reference['databases'].values():
        if value['membershipPhase'] != 'after':
            assert all(value['tables'][name]['count'] == 2 for name in data.NEW_TABLES)
    edit(child(restored), 'UPDATE media_playback_progress SET report_seq=report_seq+1')
    with pytest.raises(shared.ReleaseDataError, match='restored_group_changed'):
        current.verify_restore(reference, restored, marker_sha256=kwargs['marker_sha256'])
    with pytest.raises(FileExistsError): current.begin(root, next_proof, **kwargs)


@pytest.mark.parametrize('sql', ['DELETE FROM media_video_cache', 'UPDATE media_playback_progress SET position_ms=position_ms+1', 'DROP TRIGGER media_video_deleted'])
def test_current73_has_no_video_exemptions(group, tmp_path, sql):
    root, proof, kwargs = group; migrate(group); populate(root)
    next_proof = tmp_path / 'current-proof'; next_proof.mkdir(); current.begin(root, next_proof, **kwargs)
    edit(child(root), sql)
    with pytest.raises(ERRORS): current.check_stopped(root, next_proof, **kwargs)
    assert not (next_proof / 'result.json').exists()


def test_partial_ddl_rolls_back_table_and_trigger_in_one_database(group, monkeypatch):
    path = group[0] / 'household.sqlite3'; before = shared.migration._read(path); schema = data.schema_definition()
    def fail(con, sql):
        for statement in data._statements(sql)[:2]: con.execute(statement)
        raise RuntimeError('synthetic after trigger')
    monkeypatch.setattr(data, '_execute_schema', fail)
    # Build schema before injection: initialize preflight independently derives
    # the same schema before touching disk, so inject only on the disk connection.
    monkeypatch.setattr(data, 'schema_definition', lambda: schema)
    with pytest.raises(RuntimeError, match='after trigger'): data.initialize_database(path, schema)
    assert shared.migration._read(path) == before


@pytest.mark.parametrize('fault', ['cache-sql','progress-sql','import-path','source-identity'])
def test_reviewed_schema_and_import_identity_are_closed(group, monkeypatch, fault):
    root, proof, kwargs = group; data.begin(root, proof, **kwargs)
    if fault.endswith('-sql'):
        module = data.runtime_module('media_video_storage' if fault == 'cache-sql' else 'media_playback_progress')
        monkeypatch.setattr(module, 'SCHEMA_SQL', module.SCHEMA_SQL + 'CREATE TABLE extra(id TEXT);')
    elif fault == 'import-path': monkeypatch.setattr(data.runtime_module('media_video_storage'), '__file__', str(ROOT / 'app.py'))
    else:
        identity = dict(kwargs['source_identity'], runtimeHashes={**kwargs['source_identity']['runtimeHashes'], 'media_crypto.py':'0' * 64})
        kwargs = dict(kwargs, source_identity=identity)
        path = proof / 'attempt.json'; attempt = json.loads(path.read_bytes()); attempt['sourceIdentity'] = identity; attempt['sourceIdentitySha256'] = shared._digest(identity); path.write_text(json.dumps(attempt))
    before = shared.snapshot(root)
    with pytest.raises(ERRORS): data.migrate(root, proof, **kwargs)
    assert shared.snapshot(root) == before and not (proof / 'migration-attempt.json').exists()


@pytest.mark.parametrize('fault', ['foreign-trigger','old69','partial72','unregistered'])
def test_wrong_baseline_rejected_before_backup(group, fault):
    root, proof, kwargs = group
    if fault == 'unregistered':
        rogue = root / 'spaces' / ('f' * 24); rogue.mkdir(); shutil.copyfile(root / 'household.sqlite3', rogue / 'household.sqlite3')
    else:
        sql = {'foreign-trigger': 'CREATE TRIGGER media_video_deleted AFTER UPDATE OF state ON media_items BEGIN SELECT 1; END;',
               'old69': 'DROP TABLE task_reminder_operations; DROP TABLE task_reminders;',
               'partial72': 'CREATE TABLE media_video_cache(id TEXT);'}[fault]
        execute(root / 'household.sqlite3', sql)
    with pytest.raises(ERRORS): data.begin(root, proof, **kwargs)
    assert not list(proof.iterdir()) and not (root / 'backups').exists()


def test_nonempty_wal_refused_without_checkpoint(group):
    root, proof, kwargs = group; path = root / 'household.sqlite3'
    with closing(sqlite3.connect(path)) as con:
        con.execute('PRAGMA journal_mode=WAL'); con.execute('PRAGMA wal_autocheckpoint=0')
        con.execute("UPDATE private_finance SET data='{}'"); con.commit()
        wal = Path(str(path) + '-wal'); assert wal.stat().st_size > 0
        hashes = (shared.migration.file_digest(path), shared.migration.file_digest(wal))
        with pytest.raises(ERRORS): data.begin(root, proof, **kwargs)
        assert (shared.migration.file_digest(path), shared.migration.file_digest(wal)) == hashes
        assert not list(proof.iterdir())


def test_actual_tombstone_and_parent_cascade_with_retained_receipt(group):
    root, _, _ = group; migrate(group); populate(root)
    path = root / 'household.sqlite3'
    with closing(sqlite3.connect(path)) as con:
        con.execute('PRAGMA foreign_keys=ON')
        original = con.execute('SELECT context_cipher,confirm_request_id,confirm_key FROM media_imports').fetchall()
        con.execute("UPDATE media_items SET state='deleted',metadata_cipher=NULL,preview_cipher=NULL,preview_key=NULL WHERE id='legacy-shared'")
        assert con.execute("SELECT count(*) FROM media_video_cache WHERE media_id='legacy-shared'").fetchone()[0] == 0
        con.execute("DELETE FROM media_playback WHERE device_id='tv2'")
        assert con.execute("SELECT count(*) FROM media_playback_progress WHERE device_id='tv2'").fetchone()[0] == 0
        assert con.execute('SELECT context_cipher,confirm_request_id,confirm_key FROM media_imports').fetchall() == original
        assert con.execute('PRAGMA foreign_key_check').fetchall() == []
        con.commit()
