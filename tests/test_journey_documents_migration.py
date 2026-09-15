"""Portable synthetic migration tests: no Git, historical checkout or private paths.

The old fixture uses this source factory with only document registration disabled.
This tests the isolated structural transition, not an actual historical release.
"""
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('documents_migration', ROOT / 'deploy/check_journey_documents_migration.py')
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)
SQL = verify.schema_definition()['sql']

NETWORK_GUARD = r'''
import sys
def deny_network(event, args):
    if event.startswith('socket.'):
        raise AssertionError('Network forbidden in synthetic migration test')
sys.addaudithook(deny_network)
'''

SEED = NETWORK_GUARD + r'''
import json, sqlite3
from contextlib import closing
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import app as app_module
# Exactly one new registrar is disabled. All 42 old tables use the real factory.
app_module.register_journey_documents = lambda *args, **kwargs: None
application = app_module.create_app({'TESTING':True})
platform = application.extensions['household_platform']
client = application.test_client()
client.get('/api/me')
assert client.post('/api/login', json={'username':'member1','password':'synthetic-migration-one'}).status_code == 200
csrf = client.get('/api/me').json['csrf']
headers = {'X-CSRF-Token':csrf,'Origin':'http://localhost'}
assert client.post('/api/items/tasks', json={'title':'Synthetic migration task','owner':'shared'}, headers=headers).status_code == 201
invitation = client.post('/api/spaces/invitations', json={}, headers=headers)
assert invitation.status_code == 201
response = client.post('/api/spaces/redeem', json={
    'invitation':invitation.json['invitation'],'name':'Synthetic migration child','slug':'migration-child',
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
        assert len(tables) == 42 and 'journey_documents' not in tables
print(json.dumps({'households':len(platform.households()),'tablesPerHousehold':42}))
'''

CLI = NETWORK_GUARD + r'''
import runpy
from pathlib import Path
source = Path(sys.argv.pop(1))
sys.path.insert(0, str(source))
sys.argv[0] = str(source/'deploy/check_journey_documents_migration.py')
runpy.run_path(sys.argv[0], run_name='__main__')
'''


def isolated_env(data):
    # Do not pass provider credentials, app config or Python path from the host.
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATH', 'TEMP', 'TMP', 'TMPDIR'}}
    env.update(DATA_DIR=str(data), SECRET_KEY='synthetic-migration-master',
               MEMBER1_PASSWORD='synthetic-migration-one', MEMBER2_PASSWORD='synthetic-migration-two',
               PUBLIC_ORIGIN='https://synthetic-migration.invalid', COOKIE_SECURE='0', TRUST_PROXY='0',
               FLASK_SKIP_DOTENV='1', PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1',
               MICROSOFT_CLIENT_ID='', MICROSOFT_CLIENT_SECRET='', GOOGLE_CLIENT_ID='',
               GOOGLE_CLIENT_SECRET='', OPENAI_API_KEY='', OPENAI_MODEL='')
    return env


def subprocess_check(code, args, data):
    result = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-c', code, *map(str, args)],
                            env=isolated_env(data), cwd=ROOT, capture_output=True, text=True,
                            encoding='utf-8', timeout=90)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def cli(action, data, inputs):
    return subprocess_check(CLI, [ROOT, action, '--data-dir', data, '--inputs-dir', inputs], data)


@pytest.fixture
def old_state(tmp_path):
    data, inputs = tmp_path / 'data', tmp_path / 'inputs'
    inputs.mkdir()
    result = subprocess_check(SEED, [ROOT], data)
    assert result == {'households': 2, 'tablesPerHousehold': 42}
    (inputs / 'schema.json').write_text(json.dumps(verify.schema_definition()), encoding='utf-8')
    before = cli('snapshot', data, inputs)
    assert len(before['households']) == 2
    assert all(set(item['tables']) == verify.BASE_TABLES for item in before['households'].values())
    (inputs / 'before.json').write_text(json.dumps(before), encoding='utf-8')
    backup_spec = importlib.util.spec_from_file_location('migration_backup', ROOT / 'deploy/backup.py')
    backup_module = importlib.util.module_from_spec(backup_spec)
    backup_spec.loader.exec_module(backup_module)
    backup = backup_module.backup_all(data)
    (inputs / 'backup.json').write_text(json.dumps(backup), encoding='utf-8')
    assert cli('validate-backup', data, inputs)['databases'] == 3
    return data, inputs, before, backup


@pytest.fixture
def migrated(old_state):
    data, inputs, before, backup = old_state
    result = cli('warm', data, inputs)
    assert result['cloudTicks'] == 0 and result['backup']['groupVerified'] is True
    return data, inputs, before, backup


def test_actual_two_household_migration_preserves_every_old_table(migrated):
    data, inputs, before, _ = migrated
    result = cli('check', data, inputs)
    assert result['households'] == 2 and result['originalTablesPreserved'] == 42
    assert result['newTableEmpty'] and result['allOriginalRowsAndSequencesPreserved']
    assert verify.preserved(before, verify.snapshot(data, True), SQL) == result


@pytest.mark.parametrize('change', [
    "UPDATE users SET name='changed' WHERE id='member1'",
    'CREATE INDEX unexpected_document_index ON journey_documents(title)',
    'DROP TRIGGER journey_documents_unlinked_revision',
    "INSERT INTO journey_documents(id,owner,request_id,payload_digest,title,filename,mime_type,content,bytes,visibility,created_at,updated_at) VALUES('doc','member1','request','digest','sample','x.pdf','application/pdf',x'78',1,'private','now','now')",
    'ALTER TABLE journey_documents ADD COLUMN unexpected TEXT',
    'CREATE INDEX unexpected_original_index ON entities(updated_at)',
    "UPDATE sqlite_sequence SET seq=seq+1 WHERE name='audit'",
])
def test_rejects_existing_data_or_new_schema_drift(migrated, change):
    data, _, before, _ = migrated
    with closing(sqlite3.connect(data / 'household.sqlite3')) as con:
        con.execute(change)
        con.commit()
    with pytest.raises(AssertionError):
        verify.preserved(before, verify.snapshot(data, True), SQL)


def test_rejects_household_set_change(migrated):
    data, _, before, _ = migrated
    with closing(sqlite3.connect(data / 'platform.sqlite3')) as con:
        con.execute("DELETE FROM households WHERE id!='default'")
        con.commit()
    with pytest.raises(AssertionError):
        verify.preserved(before, verify.snapshot(data, True), SQL)


def test_rejects_accidental_rerun_as_fresh_migration(migrated):
    data, _, _, _ = migrated
    with pytest.raises(AssertionError):
        verify.snapshot(data)


@pytest.mark.parametrize('tamper', [None, 'checksum', 'missing_mapping'])
def test_verifies_all_three_original_backup_snapshots(migrated, tamper):
    data, _, before, backup = migrated
    path = data / 'backups' / backup['manifest']
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if tamper == 'checksum':
        manifest['snapshots'][-1]['sha256'] = '0' * 64
    if tamper == 'missing_mapping':
        manifest['snapshots'].pop()
    if tamper:
        path.write_text(json.dumps(manifest), encoding='utf-8')
        with pytest.raises(AssertionError):
            verify.validated_backup(data, before, backup)
    else:
        assert verify.validated_backup(data, before, backup)['databases'] == 3


def test_self_consistent_but_different_ddl_cannot_authorize_warm(old_state):
    data, inputs, before, _ = old_state
    other_sql = SQL.replace('revision>=1', 'revision>=0')
    assert other_sql != SQL
    (inputs / 'schema.json').write_text(json.dumps({
        'sql': other_sql, 'sha256': hashlib.sha256(other_sql.encode('utf-8')).hexdigest()}), encoding='utf-8')
    with pytest.raises(AssertionError, match='Schema input'):
        verify.run('warm', data, inputs)
    assert verify.snapshot(data) == before


def test_warm_requires_verified_backup_before_any_initialization(old_state):
    data, inputs, before, backup = old_state
    path = data / 'backups' / backup['manifest']
    manifest = json.loads(path.read_text(encoding='utf-8'))
    manifest['snapshots'].pop()
    path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(AssertionError):
        verify.run('warm', data, inputs)
    assert verify.snapshot(data) == before


def test_same_source_ddl_is_the_only_reference():
    from journey_documents import SCHEMA_SQL
    assert SQL == SCHEMA_SQL
    expected, tables = verify.expected_addition(SQL)
    assert len(expected) == 64 and set(tables) == {'journey_documents'}
