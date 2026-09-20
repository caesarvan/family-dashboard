"""Real Flask/SQLite TV projections; synthetic encrypted metadata, no video decoder."""
from contextlib import closing, contextmanager
import hashlib
import sqlite3

import pytest

from household_media import ITEM_VIEW
from test_household_media import device, offline, share
from test_journey_documents import create_journey
from test_local_photo_import import saved as local_saved
from test_media_playback import command, env, granted
from test_media_trip_playback import link, preview, start


URL = '/api/media-tv/playback'
HEADERS = {'X-Display-Mode': 'tv'}


def prepared(env, scope, kind='photo', source='google'):
    if source == 'local':
        c, h, item = local_saved(env)
        uid, tv, _ = device(env)
        item = share(c, h, item)
        result = c.put('/api/media/items/' + item['id'] + '/tv-grants', headers=h, json={
            'revision': item['revision'], 'deviceIds': [uid],
            'consentVersion': 'media-v1', 'allowTvDisplay': True})
        assert result.status_code == 200, result.json
    else:
        c, h, uid, tv, _, items = granted(env, 1)
        item = items[0]
    if kind == 'video':
        # Exercise encrypted video metadata and a nonempty cache without making
        # any decoder or valid-MP4 claim. This endpoint must never fetch bytes.
        with env[1].transaction(True) as con:
            row = con.execute('SELECT ' + ITEM_VIEW + ' FROM media_items WHERE id=?', (item['id'],)).fetchone()
            meta = env[1]._metadata(row)
            raw = b'SYNTHETIC-CACHE-NOT-A-DECODE-FIXTURE'
            meta.update(mediaType='video', durationMs=8250, hasAudio=True,
                        videoKey='f' * 24, videoBytes=len(raw), videoSha256=hashlib.sha256(raw).hexdigest())
            con.execute('UPDATE media_items SET metadata_cipher=?,revision=revision+1 WHERE id=?',
                        (env[1]._seal('media-metadata', row, meta), item['id']))
            con.execute('INSERT INTO media_video_cache VALUES(?,?,?,?)',
                        (item['id'], meta['videoKey'], env[1].cipher.seal_bytes('media-video', raw), env[2][0]))
    if scope == 'journey':
        journey = create_journey(c, h)
        link(c, h, item, journey['id'])
        start(c, h, uid, preview(c, h, uid, journey['id']))
    else:
        command(c, h, uid, 'start')
    return uid, tv, item['id']


def observe(env, monkeypatch):
    original = env[1].sessions.db
    evidence = {'reads': [], 'blocked': [], 'scans': []}

    @contextmanager
    def connections():
        with original() as con:
            def authorize(action, table, column, _database, _trigger):
                if action == sqlite3.SQLITE_READ:
                    evidence['reads'].append((table, column))
                    if table == 'media_video_cache' or (table == 'media_items' and column == 'preview_cipher'):
                        evidence['blocked'].append((table, column))
                        return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            con.set_authorizer(authorize)
            con.set_trace_callback(lambda sql: evidence['scans'].append(sql)
                                   if 'JOIN media_tv_grants t' in sql else None)
            yield con
    monkeypatch.setattr(env[1].sessions, 'db', connections)
    return evidence


def saved_state(env):
    # Check only application state; request bookkeeping may update last_seen.
    with env[1].transaction() as con:
        return {name: [tuple(row) for row in con.execute('SELECT * FROM ' + name + ' ORDER BY rowid')]
                for name in ('media_items', 'media_video_cache', 'media_tv_grants', 'media_playback',
                             'media_playback_progress', 'media_playback_journeys', 'media_playback_operations',
                             'audit', 'settings')}


@pytest.mark.parametrize('scope', ['all', 'journey'])
@pytest.mark.parametrize('kind', ['photo', 'video'])
def test_get_metadata_uses_no_media_blob_in_either_snapshot(env, monkeypatch, scope, kind):
    uid, tv, item_id = prepared(env, scope, kind)
    expected = tv.get(URL, headers=HEADERS)
    assert expected.status_code == 200, expected.json
    before = saved_state(env)
    with monkeypatch.context() as patch:
        evidence = observe(env, patch)
        response = tv.get(URL, headers=HEADERS)
        assert response.status_code == 200, (response.json, evidence['blocked'])
        assert response.json == expected.json
        assert len(evidence['scans']) == 2  # Both real SQLite snapshots.
        assert ('media_items', 'metadata_cipher') in evidence['reads']
        assert ('media_tv_grants', 'device_id') in evidence['reads']
        assert not evidence['blocked']
    assert saved_state(env) == before
    value = response.json
    assert value['deviceId'] == uid and value['scope'] == scope and value['photoCount'] == 1
    assert value['item']['id'] == item_id and value['item']['mediaType'] == kind
    assert value['progress']['durationMs'] == (8250 if kind == 'video' else 10000)
    if kind == 'video':
        assert value['item']['hasAudio'] is True
        assert value['item']['videoUrl'] == '/api/media-tv/items/' + item_id + '/video'
    assert not {'owner', 'accountId', 'displayFilename', 'sourceKey'} & value['item'].keys()
    assert response.headers['Cache-Control'] == 'no-store'


def revoke(con, env, uid, item_id, change):
    if change == 'grant':
        con.execute('DELETE FROM media_tv_grants WHERE device_id=?', (uid,))
    elif change == 'private':
        con.execute("UPDATE media_items SET visibility='private',revision=revision+1 WHERE id=?", (item_id,))
    elif change == 'deleted':
        con.execute("UPDATE media_items SET state='deleted',metadata_cipher=NULL,preview_cipher=NULL,preview_key=NULL WHERE id=?", (item_id,))
    elif change == 'account':
        con.execute('DELETE FROM cloud_accounts WHERE id=?', (env[3][1],))
    elif change == 'scope':
        con.execute('UPDATE cloud_accounts SET tokens=? WHERE id=?',
                    (env[1].accounts.encrypt({'scope': 'openid'}), env[3][1]))
    elif change == 'reauth':
        con.execute('UPDATE cloud_accounts SET needs_reauth=1 WHERE id=?', (env[3][1],))
    elif change == 'membership':
        con.execute("UPDATE household_memberships SET state='removed' WHERE member_id='member1'")
    elif change == 'device':
        con.execute('UPDATE devices SET approved=0 WHERE id=?', (uid,))
    elif change == 'expired':
        con.execute('UPDATE devices SET expires=0 WHERE id=?', (uid,))
    else:
        raise AssertionError(change)


@pytest.mark.parametrize('scope', ['all', 'journey'])
@pytest.mark.parametrize('change', ['grant', 'private', 'deleted', 'account', 'scope', 'reauth',
                                   'membership', 'device', 'expired'])
def test_actual_revoke_between_snapshots_discards_old_item_and_stays_revoked(env, monkeypatch, scope, change):
    uid, tv, item_id = prepared(env, scope)
    assert tv.get(URL, headers=HEADERS).json['item']['id'] == item_id
    playback = env[0].extensions['media_playback']
    original = playback._tv_dto
    calls = []

    def after_snapshot(con, device_id):
        value = original(con, device_id)
        calls.append(value['item'])
        if len(calls) == 1:
            # Commit an actual source/grant/device change on a second database
            # connection after the first DTO, before television's fresh read.
            with closing(sqlite3.connect(env[1].sessions.path)) as writer:
                writer.execute('PRAGMA foreign_keys=ON')
                revoke(writer, env, uid, item_id, change)
                writer.commit()
        return value

    evidence = observe(env, monkeypatch)
    monkeypatch.setattr(playback, '_tv_dto', after_snapshot)
    response = tv.get(URL, headers=HEADERS)
    device_lost = change in ('device', 'expired')
    assert response.status_code == (401 if device_lost else 503), response.json
    assert response.json['code'] == ('unauthorized' if device_lost else 'unavailable')
    assert set(response.json) == {'error', 'code'} and item_id not in response.get_data(as_text=True)
    assert len(calls) == (1 if device_lost else 2)
    monkeypatch.setattr(playback, '_tv_dto', original)
    current = tv.get(URL, headers=HEADERS)
    assert current.status_code == (401 if device_lost else 200), current.json
    if not device_lost:
        assert current.json['item'] is None and current.json['progress'] is None
        assert current.json['photoCount'] == 0 and current.json['scope'] == scope
    assert not evidence['blocked']


@pytest.mark.parametrize('scope', ['all', 'journey'])
def test_local_source_requires_current_sealed_authority_without_blobs(env, monkeypatch, scope):
    uid, tv, item_id = prepared(env, scope, source='local')
    evidence = observe(env, monkeypatch)
    response = tv.get(URL, headers=HEADERS)
    assert response.status_code == 200 and response.json['item']['id'] == item_id
    # A NULL account does not authorize an altered/unbound local source.
    with env[1].transaction(True) as con:
        con.execute('UPDATE media_items SET source_key=? WHERE id=?', ('invalid-source-key', item_id))
    response = tv.get(URL, headers=HEADERS)
    assert response.status_code == 200 and response.json['item'] is None
    assert response.json['scope'] == scope and not evidence['blocked']
