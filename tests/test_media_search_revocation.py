"""Real HTTP/SQLite commits between assistant metadata snapshots; no cloud I/O."""
from contextlib import closing

import pytest

from test_household_media import env, offline, saved as google_saved, share
from test_local_photo_import import saved as local_saved
from test_journey_documents import login, connection
from test_device_sessions import install_connection


def prepare(env, source):
    c, h, item = (local_saved if source == 'local' else google_saved)(env)
    response = c.patch('/api/media/items/' + item['id'], headers=h,
                       json={'revision': item['revision'], 'caption': 'needle PRIVATE_MEDIA_CANARY'})
    assert response.status_code == 200, response.json
    item = share(c, h, response.json['item'])
    partner, ph = login(env[0], 2)
    return c, h, partner, ph, item


def between_snapshots(app, action, endpoint='search'):
    observed = []
    def after(sql):
        if ' FROM media_items WHERE state=' in sql:
            assert 'preview_cipher' not in sql and 'SELECT *' not in sql
            observed.append(sql)
            if len(observed) == 1:
                with closing(connection(app)) as con:
                    action(con)
                    con.commit()
    install_connection(app, '/api/assistant/' + endpoint,
                       'GET' if endpoint == 'search' else 'POST', after=after)
    return observed


def search(client, headers=None, endpoint='search'):
    response = (client.get('/api/assistant/search?q=needle') if endpoint == 'search' else
                client.post('/api/assistant/plan', headers=headers, json={'prompt': '搜索 needle'}))
    assert response.status_code == 200, response.json
    return response, response.json if endpoint == 'search' else response.json['search']


@pytest.mark.parametrize('source', ['local', 'google'])
@pytest.mark.parametrize('change', ['unshare', 'delete'])
def test_shared_photo_removed_during_search_is_not_returned(env, source, change):
    _, _, partner, _, item = prepare(env, source)
    def withdraw(con):
        if change == 'unshare':
            con.execute("UPDATE media_items SET visibility='private',revision=revision+1 WHERE id=?", (item['id'],))
        else:
            env[1]._delete_item(con, con.execute('SELECT id FROM media_items WHERE id=?', (item['id'],)).fetchone())
    observed = between_snapshots(env[0], withdraw)
    response, result = search(partner)
    assert observed and result['total'] == 0 and result['matches'] == []
    assert item['id'] not in response.get_data(as_text=True)
    assert 'PRIVATE_MEDIA_CANARY' not in response.get_data(as_text=True)


@pytest.mark.parametrize('change', ['needs_reauth', 'delete_account', 'null_account'])
def test_google_source_revoked_during_search_is_not_local_permission(env, change):
    _, _, partner, _, item = prepare(env, 'google')
    def revoke(con):
        if change == 'needs_reauth':
            con.execute('UPDATE cloud_accounts SET needs_reauth=1 WHERE id=?', (env[3][1],))
        elif change == 'delete_account':
            con.execute('DELETE FROM cloud_accounts WHERE id=?', (env[3][1],))
        else:
            con.execute('UPDATE media_items SET account_id=NULL WHERE id=?', (item['id'],))
    observed = between_snapshots(env[0], revoke)
    response, result = search(partner)
    assert len(observed) == 2 and result['total'] == 0 and result['matches'] == []
    assert item['id'] not in response.get_data(as_text=True)
    assert 'PRIVATE_MEDIA_CANARY' not in response.get_data(as_text=True)


def test_local_owner_removed_during_search_hides_shared_photo(env):
    _, _, partner, _, item = prepare(env, 'local')
    observed = between_snapshots(env[0], lambda con: con.execute(
        "UPDATE household_memberships SET state='removed' WHERE member_id='member1'"))
    response, result = search(partner)
    assert len(observed) == 2 and result['total'] == 0 and result['matches'] == []
    assert item['id'] not in response.get_data(as_text=True)


@pytest.mark.parametrize('source', ['local', 'google'])
def test_unchanged_source_retains_original_id_revision_and_projection(env, source):
    owner, _, partner, _, item = prepare(env, source)
    observed = between_snapshots(env[0], lambda con: None)
    response, result = search(partner)
    assert len(observed) == 2 and result['total'] == 1 and result['nextOffset'] is None
    assert result['matches'] == [{'id': item['id'], 'kind': 'media',
        'title': 'needle PRIVATE_MEDIA_CANARY', 'journey': None,
        'visibility': 'shared', 'revision': item['revision']}]
    assert not any(key in response.get_data(as_text=True) for key in ['displayFilename', 'sourceKey', 'accountId'])
    assert search(owner)[1]['matches'] == result['matches']


def test_owned_confirmed_google_photo_stays_private_after_connection_revocation(env):
    owner, headers, _, _, item = prepare(env, 'google')
    private = owner.patch('/api/media/items/' + item['id'], headers=headers,
                          json={'revision': item['revision'], 'visibility': 'private'})
    assert private.status_code == 200
    observed = between_snapshots(env[0], lambda con: con.execute(
        'UPDATE cloud_accounts SET needs_reauth=1 WHERE id=?', (env[3][1],)))
    _, result = search(owner)
    assert len(observed) == 2 and result['total'] == 1
    assert result['matches'][0]['id'] == item['id'] and result['matches'][0]['visibility'] == 'private'


def test_final_projection_reads_current_encrypted_caption_and_revision(env):
    _, _, partner, _, item = prepare(env, 'local')
    def edit(con):
        row = con.execute('SELECT * FROM media_items WHERE id=?', (item['id'],)).fetchone()
        metadata = env[1]._metadata(row)
        metadata['caption'] = 'needle CURRENT_MEDIA_CAPTION'
        encrypted = env[1]._seal('media-metadata', row, metadata)
        con.execute('UPDATE media_items SET metadata_cipher=?,revision=revision+1 WHERE id=?',
                    (encrypted, item['id']))
    observed = between_snapshots(env[0], edit)
    response, result = search(partner)
    assert len(observed) == 2 and result['total'] == 1
    assert result['matches'][0]['title'] == 'needle CURRENT_MEDIA_CAPTION'
    assert result['matches'][0]['revision'] == item['revision'] + 1
    assert 'PRIVATE_MEDIA_CANARY' not in response.get_data(as_text=True)


def test_final_snapshot_session_revocation_returns_no_metadata(env):
    _, _, partner, _, _ = prepare(env, 'local')
    observed = []
    def revoke(sql):
        if ' FROM media_items WHERE state=' in sql:
            observed.append(sql)
            if len(observed) == 2:
                with closing(connection(env[0])) as con:
                    con.execute("UPDATE member_sessions SET revoked_at=1 WHERE owner='member2'")
                    con.commit()
    install_connection(env[0], '/api/assistant/search', 'GET', after=revoke)
    response = partner.get('/api/assistant/search?q=needle')
    assert len(observed) == 2 and response.status_code == 401
    assert set(response.json) == {'error'} and 'PRIVATE_MEDIA_CANARY' not in response.get_data(as_text=True)


def test_local_search_plan_uses_same_final_media_gate(env):
    _, _, partner, headers, item = prepare(env, 'local')
    observed = between_snapshots(env[0], lambda con: con.execute(
        "UPDATE media_items SET visibility='private',revision=revision+1 WHERE id=?", (item['id'],)), 'plan')
    response, result = search(partner, headers, 'plan')
    assert len(observed) == 2 and result['total'] == 0 and response.json['matches'] == []
    assert item['id'] not in response.get_data(as_text=True)
    assert 'PRIVATE_MEDIA_CANARY' not in response.get_data(as_text=True)
