"""Real SQLite/two synthetic households; no Docker, Git, provider or production."""
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

import pytest

from tests.test_journey_documents_migration import NETWORK_GUARD, isolated_env


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('places_migration', ROOT / 'deploy/check_journey_places_migration.py')
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)
SQL = verify.schema_definition()['sql']
SEED = NETWORK_GUARD + r'''
import json, sqlite3
from contextlib import closing
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import app as app_module
# Explicitly disable only the new registrar after root's later app wiring.
if hasattr(app_module, 'register_journey_places'):
    app_module.register_journey_places = lambda *a, **k: None
application = app_module.create_app({'TESTING':True})
platform = application.extensions['household_platform']
client = application.test_client()
client.get('/api/me')
assert client.post('/api/login', json={'username':'member1','password':'synthetic-migration-one'}).status_code == 200
csrf = client.get('/api/me').json['csrf']
headers = {'X-CSRF-Token':csrf,'Origin':'http://localhost'}
assert client.post('/api/items/tasks', json={'title':'Synthetic original task','owner':'shared'}, headers=headers).status_code == 201
invitation = client.post('/api/spaces/invitations', json={}, headers=headers)
assert invitation.status_code == 201
response = client.post('/api/spaces/redeem', json={
    'invitation':invitation.json['invitation'],'name':'Synthetic child','slug':'migration-child',
    'MEMBER1_PASSWORD':'synthetic-child-one','MEMBER2_PASSWORD':'synthetic-child-two'},
    headers={'Origin':'http://localhost'})
assert response.status_code == 201
for household in platform.households():
    platform.child(household)
    path = Path(application.config['DATA_DIR'])
    if household['id'] != 'default':
        path = path / 'spaces' / household['id']
    with closing(sqlite3.connect(path/'household.sqlite3')) as con:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        assert len(tables) == 43 and 'journey_documents' in tables and 'journey_places' not in tables
        con.execute("INSERT INTO journey_documents(id,owner,request_id,payload_digest,title,filename,mime_type,content,bytes,visibility,created_at,updated_at) VALUES('doc','member1','request','digest','synthetic','x.pdf','application/pdf',x'001122ff',4,'private','now','now')")
        con.commit()
print(json.dumps({'households':len(platform.households()),'tablesPerHousehold':43}))
'''
CLI = NETWORK_GUARD + r'''
import runpy
from pathlib import Path
source = Path(sys.argv.pop(1));sys.path.insert(0,str(source))
sys.argv[0] = str(source/'deploy/check_journey_places_migration.py')
runpy.run_path(sys.argv[0], run_name='__main__')
'''


def process(code, args, data, optimized=False):
    return subprocess.run([sys.executable, '-B', *(['-O'] if optimized else []), '-X', 'utf8', '-c', code, *map(str, args)],
                          env=isolated_env(data), cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=90)


def write(inputs, name, value):
    (inputs / name).write_text(json.dumps(value), encoding='utf-8')


@pytest.fixture(scope='module')
def seed(tmp_path_factory):
    data = tmp_path_factory.mktemp('places-seed') / 'data'
    result = process(SEED, [ROOT], data)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'households': 2, 'tablesPerHousehold': 43}
    return data


@pytest.fixture
def old_state(tmp_path, seed):
    data, inputs = tmp_path / 'data', tmp_path / 'inputs'
    shutil.copytree(seed, data); inputs.mkdir()
    write(inputs, 'schema.json', verify.schema_definition())
    before = verify.run('snapshot', data, inputs)
    write(inputs, 'before.json', before)
    from deploy.backup import backup_all
    backup = backup_all(data)
    write(inputs, 'backup.json', backup)
    proof = verify.run('validate-backup', data, inputs)
    assert proof['databases'] == 3
    write(inputs, 'backup-verification.json', proof)
    return data, inputs, before, backup


@pytest.fixture
def migrated(old_state):
    data, inputs, _, _ = old_state
    result = verify.run('warm', data, inputs)
    assert result['cloudTicks'] == result['modelRequests'] == 0
    assert result['backup']['groupVerified'] is True
    return old_state


def change(data, statement):
    with closing(sqlite3.connect(data / 'household.sqlite3')) as con:
        con.execute(statement); con.commit()


def test_two_households_preserve_all_original_rows_blobs_schema_and_sequences(migrated):
    data, inputs, before, _ = migrated
    proof = verify.run('check', data, inputs)
    assert proof['households'] == 2 and proof['originalTablesPreserved'] == 43 and proof['newTables'] == 1
    assert proof['newTableEmpty'] and proof['schemaIndexesAndTriggersVerified']
    after = verify.snapshot(data, True)
    assert before['registry'] == after['registry']
    assert all(h['tables']['journey_documents']['count'] == 1 for h in after['households'].values())
    assert verify.preserved(before, after, SQL) == {k:v for k,v in proof.items() if k != 'backup'}


def test_cli_migrates_with_socket_denial_and_optimized_python(old_state):
    data, inputs, _, _ = old_state
    result = process(CLI, [ROOT, 'warm', '--data-dir', data, '--inputs-dir', inputs], data, optimized=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['households'] == 2
    result = process(CLI, [ROOT, 'warm', '--data-dir', data, '--inputs-dir', inputs], data, optimized=True)
    assert result.returncode != 0 and result.stderr.strip() == 'places_database_verification_failed'
    assert not result.stdout


@pytest.mark.parametrize('statement', [
    "UPDATE users SET name='changed' WHERE id='member1'",
    "UPDATE journey_documents SET content=x'12345678'",
    'CREATE INDEX unexpected_original ON entities(updated_at)',
    'CREATE INDEX unexpected_new ON journey_places(name)',
    'DROP TRIGGER journey_places_unlinked_revision',
    'ALTER TABLE journey_places ADD COLUMN surprise TEXT',
    "UPDATE sqlite_sequence SET seq=seq+1 WHERE name='audit'",
    "INSERT INTO journey_places(id,owner,request_id,payload_digest,name,status,visibility,coordinate_disclosure,created_at,updated_at) VALUES('x','member1','request','digest','secret','wish','private','hidden','now','now')",
])
def test_rejects_any_old_or_new_drift(migrated, statement):
    data, inputs, _, _ = migrated
    change(data, statement)
    with pytest.raises(RuntimeError):
        verify.run('check', data, inputs)


def test_foreign_key_corruption_fails_readback(migrated):
    data, inputs, _, _ = migrated
    change(data, "UPDATE journey_documents SET owner='missing'")
    with pytest.raises(RuntimeError, match='foreign_keys'):
        verify.run('check', data, inputs)


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'checksum', 'content', 'proof', 'map', 'missing_file'])
def test_backup_group_tampering_blocks_all_initialization(old_state, mutation):
    data, inputs, before, backup = old_state
    path = data / 'backups' / backup['manifest']
    manifest = json.loads(path.read_text())
    if mutation == 'missing': manifest['snapshots'].pop()
    if mutation == 'duplicate': manifest['snapshots'].append(manifest['snapshots'][0])
    if mutation == 'checksum': manifest['snapshots'][-1]['sha256'] = '0'*64
    if mutation == 'map': manifest['snapshots'][-1]['path'] = '../escape.sqlite3'
    if mutation == 'proof': write(inputs, 'backup-verification.json', {'groupVerified': True})
    if mutation == 'missing_file': (data / manifest['snapshots'][-1]['path']).unlink()
    if mutation == 'content':
        item = manifest['snapshots'][-1]; target = data / item['path']
        with closing(sqlite3.connect(target)) as con:
            con.execute("UPDATE users SET name='tampered'"); con.commit()
        item['bytes'] = target.stat().st_size; item['sha256'] = verify.file_digest(target)
    path.write_text(json.dumps(manifest))
    with pytest.raises((RuntimeError, FileNotFoundError)):
        verify.run('warm', data, inputs)
    assert verify.snapshot(data) == before


def test_registry_drift_and_original_data_drift_block_warm(old_state):
    data, inputs, _, _ = old_state
    change(data, "UPDATE users SET name='late edit'")
    with pytest.raises(RuntimeError, match='pre_migration_drift'):
        verify.run('warm', data, inputs)
    assert all('journey_places' not in h['tables'] for h in verify.snapshot(data)['households'].values())


def test_household_registry_change_is_not_silently_ignored(migrated):
    data, inputs, _, _ = migrated
    with closing(sqlite3.connect(data/'platform.sqlite3')) as con:
        con.execute("DELETE FROM households WHERE id!='default'"); con.commit()
    with pytest.raises(RuntimeError, match='registry_changed'):
        verify.run('check', data, inputs)


def test_self_consistent_replaced_schema_input_is_rejected(old_state):
    data, inputs, before, _ = old_state
    sql = SQL.replace('revision>=1', 'revision>=0')
    write(inputs, 'schema.json', {'sql':sql, 'sha256':hashlib.sha256(sql.encode()).hexdigest()})
    with pytest.raises(RuntimeError, match='schema_input_changed'):
        verify.run('warm', data, inputs)
    assert verify.snapshot(data) == before


def test_partial_household_failure_is_not_retried_or_restored(old_state, monkeypatch):
    data, inputs, before, _ = old_state
    original = verify.initialize_database; calls = []
    def fail_second(path, sql):
        calls.append(path)
        if len(calls) == 2: raise OSError('synthetic interrupted write')
        original(path, sql)
    monkeypatch.setattr(verify, 'initialize_database', fail_second)
    with pytest.raises(OSError): verify.run('warm', data, inputs)
    migrated_count = sum('journey_places' in verify.fingerprint(verify.checked_path(data, verify.relative_database(uid)))['tables'] for uid in before['households'])
    assert migrated_count == 1
    for action in ('warm', 'snapshot', 'check'):
        with pytest.raises(RuntimeError, match='household_table_set'):
            verify.run(action, data, inputs)
    assert len(calls) == 2


def test_per_household_ddl_failure_rolls_back_all_new_objects(old_state):
    data, _, before, _ = old_state
    path = data/'household.sqlite3'
    with pytest.raises(sqlite3.OperationalError):
        verify.initialize_database(path, SQL + '\ninvalid SQL;')
    assert verify.snapshot(data) == before


@pytest.mark.parametrize('relative', ['../household.sqlite3', '/household.sqlite3', 'a\\b', 'C:/db', './household.sqlite3', 'a//b'])
def test_input_paths_cannot_escape(old_state, relative):
    data, _, _, _ = old_state
    with pytest.raises(RuntimeError): verify.checked_path(data, relative)


def test_check_requires_original_backup_group_even_after_success(migrated):
    data, inputs, _, _ = migrated
    (inputs/'backup-verification.json').unlink()
    with pytest.raises(FileNotFoundError): verify.run('check', data, inputs)


def test_hardlinked_live_backup_is_rejected_before_any_ddl(old_state):
    data, inputs, before, backup = old_state
    manifest_path = data/'backups'/backup['manifest']
    manifest = json.loads(manifest_path.read_text())
    item = next(x for x in manifest['snapshots'] if x['path'].startswith('backups/household-'))
    target = data/item['path']; target.unlink()
    os.link(data/'household.sqlite3', target)
    item.update(bytes=target.stat().st_size, sha256=verify.file_digest(target))
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(RuntimeError, match='backup_hardlink'):
        verify.run('warm', data, inputs)
    assert verify.snapshot(data) == before


def test_unbound_wal_cannot_make_incomplete_backup_look_restorable(old_state):
    data, inputs, before, backup = old_state
    manifest_path = data/'backups'/backup['manifest']
    manifest = json.loads(manifest_path.read_text())
    item = next(x for x in manifest['snapshots'] if x['path'].startswith('backups/household-'))
    target = data/item['path']
    with closing(sqlite3.connect(target)) as con:
        original = con.execute("SELECT name FROM users WHERE id='member1'").fetchone()[0]
        con.execute("UPDATE users SET name='incomplete-main' WHERE id='member1'"); con.commit()
        con.execute('PRAGMA journal_mode=WAL'); con.execute('PRAGMA wal_autocheckpoint=0')
        con.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        con.execute("UPDATE users SET name=? WHERE id='member1'", (original,)); con.commit()
        assert verify.fingerprint(target) == before['households']['default']
        assert verify.fingerprint(target, immutable=True) != before['households']['default']
        item.update(bytes=target.stat().st_size, sha256=verify.file_digest(target))
        manifest_path.write_text(json.dumps(manifest))
        with pytest.raises(RuntimeError, match='backup_sidecar'):
            verify.run('warm', data, inputs)
    assert verify.snapshot(data) == before


def test_backup_tampering_after_ddl_cannot_return_success(old_state, monkeypatch):
    data, inputs, _, backup = old_state
    original = verify.initialize_database
    def tamper(path, sql):
        original(path, sql)
        manifest = data/'backups'/backup['manifest']
        value = json.loads(manifest.read_text()); value['snapshots'].pop()
        manifest.write_text(json.dumps(value))
    monkeypatch.setattr(verify, 'initialize_database', tamper)
    with pytest.raises(RuntimeError, match='backup_group_incomplete'):
        verify.run('warm', data, inputs)
    assert all('journey_places' in h['tables'] for h in verify.snapshot(data, True)['households'].values())
