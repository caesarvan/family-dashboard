"""Photo export through real Flask/SQLite; source accounts remain synthetic."""
from io import BytesIO
import json
from zipfile import ZipFile

import pytest

import data_portability
from test_household_media import configured, saved, share, stage, device
from test_journey_documents import login


@pytest.fixture
def env(tmp_path,monkeypatch):
    return configured(tmp_path/'media-export',monkeypatch)


def snapshot(response):
    assert response.status_code==200,response.json
    with ZipFile(BytesIO(response.data)) as archive:
        assert set(archive.namelist())=={'data.json','transactions.csv','investments.csv','README.txt','manifest.json'}
        return json.loads(archive.read('data.json')),archive.read('README.txt').decode()


def test_personal_saved_only_and_explicit_shared(env):
    own,headers,item=saved(env)
    other,other_headers,shared=saved(env,2)
    shared=share(other,other_headers,shared)
    stage(env,2,[__import__('test_household_media').selected('unconfirmed-photo')])
    data,note=snapshot(own.post('/api/portability/export',json={},headers=headers))
    assert [r['id'] for r in data['personal']['householdMedia']]==[item['id']]
    assert 'shared' not in data
    assert data['coverage']['householdMedia']=='saved_metadata_only'
    assert '没有照片文件' in note
    data,_=snapshot(own.post('/api/portability/export',json={'includeShared':True},headers=headers))
    assert [r['id'] for r in data['shared']['householdMedia']]==[shared['id']]
    assert 'displayFilename' in data['personal']['householdMedia'][0]
    assert 'displayFilename' not in data['shared']['householdMedia'][0]
    combined=json.dumps(data['personal']['householdMedia']+data['shared']['householdMedia'])
    for forbidden in ('previewUrl','accountId','preview_cipher','sourceKey','synthetic-media-token','synthetic-subject','leaseToken','requestId','deviceIds','session_cipher'):
        assert forbidden not in combined
    counts=own.get('/api/portability/summary').json
    assert counts['personal']['householdMedia']==1 and counts['shared']['householdMedia']==1


def test_revoked_source_and_deleted_photos_are_excluded(env):
    own,headers,item=saved(env)
    other,other_headers,shared=saved(env,2)
    shared=share(other,other_headers,shared)
    with env[1].transaction(True) as con:
        con.execute('UPDATE cloud_accounts SET needs_reauth=1 WHERE id=?',(env[3][2],))
    assert own.delete('/api/media/items/'+item['id'],json={'revision':item['revision']},headers=headers).status_code==200
    data,_=snapshot(own.post('/api/portability/export',json={'includeShared':True},headers=headers))
    assert data['personal']['householdMedia']==[] and data['shared']['householdMedia']==[]


def test_share_revoked_while_zip_builds_is_not_sent(env,monkeypatch):
    own,headers=login(env[0])
    other,other_headers,shared=saved(env,2)
    shared=share(other,other_headers,shared)
    real=data_portability.ZipFile
    class RevokeOnClose(real):
        changed=False
        def close(self):
            super().close()
            if not self.changed:
                self.changed=True
                with env[1].transaction(True) as con:
                    con.execute("UPDATE media_items SET visibility='private',revision=revision+1 WHERE id=?",(shared['id'],))
    monkeypatch.setattr(data_portability,'ZipFile',RevokeOnClose)
    response=own.post('/api/portability/export',json={'includeShared':True},headers=headers)
    assert response.status_code==409
    assert response.mimetype=='application/json'


def test_cross_household_and_tv_cannot_export_member_photos(env,tmp_path,monkeypatch):
    _,_,item=saved(env)
    second=configured(tmp_path/'another-household',monkeypatch,'different-household')
    client,headers=login(second[0])
    data,_=snapshot(client.post('/api/portability/export',json={'includeShared':True},headers=headers))
    assert data['personal']['householdMedia']==[] and data['shared']['householdMedia']==[]
    _,television,_=device(env)
    response=television.post('/api/portability/export',json={})
    assert response.status_code==403


def test_sqlite_backup_keeps_encrypted_preview_with_no_plaintext(env):
    _,_,item=saved(env)
    import sqlite3
    with env[1].transaction() as con, sqlite3.connect(':memory:') as destination:
        # Use a separate read-only connection for SQLite's backup snapshot.
        database=con.execute('PRAGMA database_list').fetchone()[2]
        with sqlite3.connect(database) as source:
            source.backup(destination)
        row=destination.execute('SELECT metadata_cipher,preview_cipher FROM media_items WHERE id=?',(item['id'],)).fetchone()
        assert row and len(row[1])>100
        assert b'private-synthetic-filename' not in row[0]
        assert not row[1].startswith(b'\xff\xd8')
        assert destination.execute('PRAGMA quick_check').fetchone()[0]=='ok'
