"""Actual Flask/SQLite 43-table fixtures; no Docker, Git, private input or network."""
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


ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


C = module('static_database_check', 'deploy/check_static_release.py')
B = module('static_database_backup', 'deploy/backup.py')
GUARD = """
import sys
def guard(event, args):
    if event.startswith('socket.'): raise AssertionError('Network forbidden')
sys.addaudithook(guard)
"""
SEED = GUARD + r'''
import sqlite3
from contextlib import closing
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from app import create_app
application=create_app({'TESTING':True})
platform=application.extensions['household_platform']
client=application.test_client();client.get('/api/me')
assert client.post('/api/login',json={'username':'member1','password':'synthetic-one'}).status_code==200
headers={'X-CSRF-Token':client.get('/api/me').json['csrf'],'Origin':'http://localhost'}
assert client.post('/api/items/tasks',json={'title':'Synthetic retained task','owner':'shared'},headers=headers).status_code==201
inv=client.post('/api/spaces/invitations',json={},headers=headers)
assert inv.status_code==201
assert client.post('/api/spaces/redeem',json={'invitation':inv.json['invitation'],'name':'Synthetic second home',
    'slug':'second-home','MEMBER1_PASSWORD':'synthetic-child-one','MEMBER2_PASSWORD':'synthetic-child-two'},
    headers={'Origin':'http://localhost'}).status_code==201
for household in platform.households():
    platform.child(household)
    folder=Path(application.config['DATA_DIR'])
    if household['id']!='default':folder=folder/'spaces'/household['id']
    with closing(sqlite3.connect(folder/'household.sqlite3')) as con:
        assert len(con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall())==43
        for i,owner in enumerate(('member1','member2')):
            content=b'%PDF-1.7\nSynthetic retained private BLOB\n%%EOF\n'+owner.encode()
            con.execute('INSERT INTO journey_documents(id,owner,request_id,payload_digest,title,filename,mime_type,content,bytes,visibility,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                ('document-'+owner,owner,'synthetic-request-'+owner,'synthetic-digest','Synthetic private metadata','synthetic.pdf','application/pdf',content,len(content),'private','2026-01-01','2026-01-01'))
        con.commit()
print('seeded-two-households')
'''
START = GUARD + r'''
sys.path.insert(0,sys.argv[1])
from app import create_app
application=create_app({'TESTING':True})
platform=application.extensions['household_platform']
for household in platform.households():platform.child(household)
assert application.test_client().get('/healthz').status_code==200
print('started-without-worker')
'''


def isolated_env(data):
    env={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','COMSPEC','PATH','TEMP','TMP','TMPDIR'}}
    env.update(DATA_DIR=str(data),SECRET_KEY='synthetic-static-master',MEMBER1_PASSWORD='synthetic-one',
        MEMBER2_PASSWORD='synthetic-two',PUBLIC_ORIGIN='https://synthetic.invalid',COOKIE_SECURE='0',TRUST_PROXY='0',
        FLASK_SKIP_DOTENV='1',PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1',MICROSOFT_CLIENT_ID='',
        MICROSOFT_CLIENT_SECRET='',GOOGLE_CLIENT_ID='',GOOGLE_CLIENT_SECRET='',OPENAI_API_KEY='',OPENAI_MODEL='')
    return env


def child(code,data):
    result=subprocess.run([sys.executable,'-B','-X','utf8','-c',code,str(ROOT)],env=isolated_env(data),
                          cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=90)
    assert result.returncode==0,result.stderr
    return result.stdout


@pytest.fixture(scope='module')
def template(tmp_path_factory):
    path=tmp_path_factory.mktemp('static-template')/'data'
    assert child(SEED,path).strip()=='seeded-two-households'
    return path


@pytest.fixture
def state(template,tmp_path):
    data=tmp_path/'data';shutil.copytree(template,data)
    inputs=tmp_path/'inputs';inputs.mkdir()
    before=C.run('snapshot',data,inputs)
    assert len(before['households'])==2
    (inputs/'before.json').write_text(json.dumps(before),encoding='utf-8')
    backup=B.backup_all(data)
    (inputs/'backup.json').write_text(json.dumps(backup),encoding='utf-8')
    proof=C.run('validate-backup',data,inputs)
    (inputs/'backup-verification.json').write_text(json.dumps(proof),encoding='utf-8')
    return data,inputs,before,backup


def execute(path,sql,args=()):
    with closing(sqlite3.connect(path)) as con:
        con.execute(sql,args);con.commit()


def test_real_startup_preserves_two_household_blobs_rows_schema_and_backup_group(state):
    data,inputs,before,_=state
    assert child(START,data).strip()=='started-without-worker'
    result=C.run('check',data,inputs)
    assert result=={'households':2,'originalTablesPreserved':43,'newTables':0,
        'schemaIndexesAndTriggersVerified':True,'allOriginalRowsAndSequencesPreserved':True,
        'backup':C.run('validate-backup',data,inputs)}
    assert result['backup']['databases']==3
    assert C.snapshot(data)==before
    encoded=json.dumps(before)
    assert 'Synthetic retained private BLOB' not in encoded and 'Synthetic private metadata' not in encoded
    for uid,h in before['households'].items():
        assert h['tables']['journey_documents']['count']==2
        assert len(h['tables'])==43


@pytest.mark.parametrize('sql',[
 "UPDATE journey_documents SET content=zeroblob(bytes)",
 "UPDATE journey_documents SET title='later change'",
 "DELETE FROM journey_documents",
 "UPDATE users SET name='later member'",
 "UPDATE settings SET data='{}' WHERE id='meta'",
 'CREATE INDEX unexpected_document_index ON journey_documents(title)',
 'DROP TRIGGER journey_documents_unlinked_revision',
 'DROP INDEX journey_documents_owner',
 'CREATE TABLE unexpected(id TEXT)',
 'ALTER TABLE journey_documents ADD COLUMN extra TEXT',
 "UPDATE sqlite_sequence SET seq=seq+100",
])
def test_any_original_data_schema_blob_or_sequence_change_is_rejected(state,sql):
    data,inputs,_,_=state
    execute(data/'household.sqlite3',sql)
    damaged={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in data.rglob('*.sqlite3')}
    with pytest.raises((AssertionError,RuntimeError)):C.run('check',data,inputs)
    assert damaged=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in data.rglob('*.sqlite3')}


@pytest.mark.parametrize('problem',['missing-child','zero-child','registry-change','extra-household'])
def test_household_mapping_or_missing_database_does_not_create_replacements(state,problem):
    data,inputs,before,_=state
    uid=next(x for x in before['households'] if x!='default');path=data/'spaces'/uid/'household.sqlite3'
    if problem=='missing-child':path.unlink()
    elif problem=='zero-child':path.write_bytes(b'')
    elif problem=='registry-change':execute(data/'platform.sqlite3',"UPDATE households SET name='changed' WHERE id=?",(uid,))
    else:execute(data/'platform.sqlite3','DELETE FROM households WHERE id=?',(uid,))
    with pytest.raises((AssertionError,RuntimeError,FileNotFoundError)):C.run('check',data,inputs)
    if problem=='missing-child':assert not path.exists()
    if problem=='zero-child':assert path.stat().st_size==0


@pytest.mark.parametrize('problem',['manifest-sha','snapshot-bytes','missing-mapping','duplicate-mapping','proof'])
def test_all_backup_members_and_exact_original_manifest_are_rechecked(state,problem):
    data,inputs,_,backup=state;path=data/'backups'/backup['manifest']
    manifest=json.loads(path.read_bytes())
    if problem=='manifest-sha':path.write_bytes(path.read_bytes()+b'\n')
    elif problem=='snapshot-bytes':(data/manifest['snapshots'][0]['path']).write_bytes(b'damaged')
    elif problem=='missing-mapping':manifest['snapshots'].pop();path.write_text(json.dumps(manifest))
    elif problem=='duplicate-mapping':manifest['snapshots'].append(manifest['snapshots'][0]);path.write_text(json.dumps(manifest))
    else:(inputs/'backup-verification.json').write_text('{}')
    with pytest.raises((AssertionError,RuntimeError)):C.run('check',data,inputs)


def test_legacy_42_table_database_is_not_accepted_as_static_release(state):
    data,inputs,_,_=state
    execute(data/'household.sqlite3','DROP TABLE journey_documents')
    with pytest.raises(AssertionError):C.run('snapshot',data,inputs)


def test_verifier_has_no_warm_operation(state):
    data,inputs,before,_=state
    with pytest.raises(RuntimeError,match='unknown_static_check'):C.run('warm',data,inputs)
    assert C.snapshot(data)==before
