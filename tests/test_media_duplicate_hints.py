"""Exact display-copy hints through real member HTTP/encrypted SQLite; no cloud I/O."""
from contextlib import closing, contextmanager
from io import BytesIO
import secrets
import sqlite3

from PIL import Image
import pytest

import household_media as media
from media_images import sanitize_media_preview
from test_household_media import env, offline, create, session, selected, confirm, device, share
from test_journey_documents import login
from test_local_photo_import import saved as local_saved, put, finish, picture
from test_media_suggestion_sessions import snapshot
from test_device_sessions import ConnectionProxy, invalidate
from test_app import app as platform_app, member


def raw_photo():
    output = BytesIO()
    Image.new('RGB', (20, 12), '#496654').save(output, 'PNG')
    return output.getvalue()


def google_photos(env, raw=None, count=1, number=1, confirmed=True):
    raw = raw or raw_photo()
    client, headers, batch, _ = create(env, number)
    engine = env[1]
    assert engine.complete(engine.claim_next(), session(env))
    selections = [selected(secrets.token_hex(12)) for _ in range(count)]
    assert engine.complete(engine.claim_next(), selections)
    preview = sanitize_media_preview(raw, 'image/png' if raw.startswith(b'\x89PNG') else 'image/jpeg')
    while (job := engine.claim_next()) is not None:
        if job['action'] == 'cleanup':
            assert engine.complete(job, None)
            break
        assert job['action'] == 'download'
        assert engine.complete(job, {'mediaId': job['media']['id'], 'manifest': selections, 'preview': preview})
    detail = client.get('/api/media/imports/' + batch['id']).json
    if confirmed:
        confirm(client, headers, detail)
    return client, headers, [client.get('/api/media/items/' + item['id']).json['item'] for item in detail['items']]


def pair(env):
    client, headers, photos = google_photos(env)
    _, _, local = local_saved(env, raw_photo())
    return client, headers, photos[0], local


def url(item):
    return '/api/media/items/' + item['id'] + '/duplicates'


def read(client, item, query=''):
    response = client.get(url(item) + query)
    assert response.status_code == 200, response.json
    return response.json


def change_metadata(env, uid, changes=None, remove=()):
    engine = env[1]
    with engine.transaction(True) as con:
        row = con.execute('SELECT ' + media.ITEM_VIEW + ' FROM media_items WHERE id=?', (uid,)).fetchone()
        meta = engine._metadata(row)
        meta.update(changes or {})
        for key in remove:
            meta.pop(key, None)
        con.execute('UPDATE media_items SET metadata_cipher=?,revision=revision+1 WHERE id=?',
                    (engine._seal('media-metadata', row, meta), uid))


def read_boundary(env, item, change, *, final_identity=False):
    """Commit from a second real connection after the first read snapshot started."""
    original = env[1].sessions.db
    calls = []

    @contextmanager
    def connections():
        with original() as con:
            def after(sql):
                is_scan = ' FROM media_items WHERE owner=? AND id!=?' in sql
                if is_scan:
                    calls.append('scan')
                if is_scan and calls == ['scan'] and not final_identity:
                    with closing(sqlite3.connect(env[1].sessions.path)) as writer:
                        writer.row_factory = sqlite3.Row
                        writer.execute('PRAGMA foreign_keys=ON')
                        change(writer)
                        writer.commit()
            def before(sql):
                # Revoke just before the final reservation, never while its
                # writer lock is held (the real request must observe this commit).
                if final_identity and sql == 'BEGIN IMMEDIATE':
                    with closing(sqlite3.connect(env[1].sessions.path)) as writer:
                        change(writer)
                        writer.commit()
            yield ConnectionProxy(con, before, None if final_identity else after)
    return connections, calls


def test_cross_source_exact_copy_keeps_original_ids_private_and_is_read_only(env, monkeypatch):
    client, headers, google, local = pair(env)
    before = snapshot(env)
    reads, forbidden = [], []
    original = env[1].sessions.db

    @contextmanager
    def connections():
        with original() as con:
            def authorize(action, table, column, _database, _trigger):
                if action == sqlite3.SQLITE_READ:
                    reads.append((table, column))
                    if table == 'media_video_cache' or (table == 'media_items' and column == 'preview_cipher'):
                        forbidden.append((table, column))
                        return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            con.set_authorizer(authorize)
            yield con
    monkeypatch.setattr(env[1].sessions, 'db', connections)
    for anchor, expected in ((google, local), (local, google)):
        result = read(client, anchor)
        assert result['items'] == [expected]
        assert result['photoId'] == anchor['id'] and result['photoRevision'] == anchor['revision']
        assert result['total'] == 1 and result['limit'] == 20 and not result['hasMore']
        assert result['matchBasis'] == 'display-copy-sha256'
        assert result['label'] == '展示副本一致，原图未核验'
        assert result['coverage'] == {'scope': 'mine', 'scanLimit': 1000, 'scanned': 1,
                                      'capped': False, 'unverifiable': 0}
        assert expected['visibility'] == 'private' and expected['canManage']
        assert not any(key in result['items'][0] for key in ('sha256', 'sourceKey', 'previewKey', 'uploadSha256'))
    assert reads and not forbidden
    assert snapshot(env) == before
    for method in ('POST', 'PATCH', 'PUT', 'DELETE'):
        assert client.open(url(local), method=method, json={}, headers=headers).status_code == 405


def test_same_source_and_unequal_copies_do_not_match(env):
    client, _, photos = google_photos(env, count=2)
    _, _, local = local_saved(env, picture('blue'))
    assert read(client, photos[0])['total'] == 0
    assert read(client, local)['total'] == 0


def test_reencoded_visually_similar_photo_is_not_declared_equivalent(env):
    source = Image.new('RGB', (64, 48))
    source.putdata([(x % 256, (x * 7) % 256, (x * 13) % 256) for x in range(64 * 48)])
    png, jpeg = BytesIO(), BytesIO()
    source.save(png, 'PNG'); source.save(jpeg, 'JPEG', quality=70)
    client, _, photos = google_photos(env, jpeg.getvalue())
    _, _, local = local_saved(env, png.getvalue())
    assert sanitize_media_preview(png.getvalue(), 'image/png').sha256 != sanitize_media_preview(jpeg.getvalue(), 'image/jpeg').sha256
    assert read(client, photos[0])['items'] == []
    assert read(client, local)['label'] == '展示副本一致，原图未核验'


@pytest.mark.parametrize('changes', [{'width': 21}, {'height': 13}, {'bytes': 1}, {'sha256': '0' * 64}])
def test_all_fingerprint_fields_must_match(env, changes):
    client, _, google, local = pair(env)
    change_metadata(env, local['id'], changes)
    assert read(client, google)['total'] == 0


@pytest.mark.parametrize('changes', [{'sha256': 'invalid'}, {'width': True}, {'bytes': None}])
def test_legacy_or_invalid_metadata_is_explicitly_unverifiable(env, changes):
    client, _, google, local = pair(env)
    change_metadata(env, local['id'], changes)
    result = read(client, google)
    assert result['items'] == [] and result['coverage']['unverifiable'] == 1
    assert result['coverage']['scanned'] == 0
    assert client.get(url(local)).status_code == 503


def test_pending_deleted_video_and_unconfirmed_never_enter_results(env):
    client, headers, photos = google_photos(env, count=3)
    _, _, local = local_saved(env, raw_photo())
    assert client.delete('/api/media/items/' + photos[1]['id'], headers=headers,
                         json={'revision': photos[1]['revision']}).status_code == 200
    change_metadata(env, photos[2]['id'], {'mediaType': 'video'})  # metadata-only exclusion fixture
    _, _, pending = google_photos(env, confirmed=False)
    result = read(client, local)
    assert [item['id'] for item in result['items']] == [photos[0]['id']]
    assert result['coverage']['scanned'] == 1 and result['coverage']['unverifiable'] == 0
    for unavailable in (photos[1], photos[2], pending[0]):
        assert client.get(url(unavailable)).status_code == 404


def test_other_owner_shared_photo_and_real_tv_do_not_reveal_hints(env):
    client, headers, google, local = pair(env)
    shared = share(client, headers, google)
    partner, _ = login(env[0], 2)
    assert partner.get('/api/media/items/' + shared['id']).status_code == 200
    assert partner.get(url(shared)).status_code == 404
    device_id, tv, _ = device(env)
    assert client.put('/api/media/items/' + shared['id'] + '/tv-grants', headers=headers, json={
        'revision': shared['revision'], 'deviceIds': [device_id], 'consentVersion': 'media-v1',
        'allowTvDisplay': True}).status_code == 200
    assert tv.get(url(shared)).status_code == 403
    assert env[0].test_client().get(url(shared)).status_code == 401
    _, _, others = google_photos(env, count=3, number=2)
    result = read(client, local)
    assert result['total'] == 1 and result['coverage']['scanned'] == 1
    assert not any(item['id'] in str(result) for item in others)


def test_signed_space_cookie_isolates_real_household_routes(platform_app):
    from test_household_spaces import create_space
    from test_local_photo_import import URL, intent
    root, rh = member(platform_app)
    child, _, space = create_space(platform_app)
    assert child.get(space['entry']).status_code == 303
    assert child.post('/api/login', json={'username': 'member1', 'password': 'second-home-password-one'}).status_code == 200
    headers = {'X-CSRF-Token': child.get('/api/me').json['csrf']}
    raw = raw_photo()
    detail = child.post(URL, json=intent([raw]), headers=headers).json
    uploaded = put(child, headers, detail, raw)
    finished, _ = finish(child, headers, uploaded.json)
    confirm(child, headers, finished)
    item = finished['items'][0]['item']
    assert read(child, item)['total'] == 0
    response = root.get(url(item))
    assert response.status_code == 404 and 'coverage' not in response.json


@pytest.mark.parametrize('change', ['reauth', 'account_null', 'source_forged'])
def test_current_source_authority_is_required_without_removing_owned_copy(env, change):
    client, _, google, local = pair(env)
    if change == 'source_forged':
        change_metadata(env, local['id'], {'source': 'google-photos'})
        anchor, invalid = google, local
    else:
        with env[1].transaction(True) as con:
            if change == 'reauth':
                con.execute('UPDATE cloud_accounts SET needs_reauth=1 WHERE id=?', (env[3][1],))
            else:
                con.execute('UPDATE media_items SET account_id=NULL WHERE id=?', (google['id'],))
        anchor, invalid = local, google
    result = read(client, anchor)
    assert result['items'] == [] and result['coverage']['unverifiable'] == 1
    assert client.get(url(invalid)).status_code in (409, 503)
    if change == 'reauth':
        assert client.get('/api/media/items/' + google['id']).status_code == 200


@pytest.mark.parametrize('change', ['candidate_deleted', 'source_revoked', 'anchor_deleted', 'caption'])
def test_final_snapshot_reloads_original_rows_and_authority(env, monkeypatch, change):
    client, _, google, local = pair(env)
    def mutate(con):
        if change == 'candidate_deleted':
            env[1]._delete_item(con, google)
        elif change == 'source_revoked':
            con.execute('UPDATE cloud_accounts SET needs_reauth=1 WHERE id=?', (env[3][1],))
        elif change == 'anchor_deleted':
            env[1]._delete_item(con, local)
        else:
            row = con.execute('SELECT ' + media.ITEM_VIEW + ' FROM media_items WHERE id=?', (google['id'],)).fetchone()
            value = env[1]._metadata(row) | {'caption': '当前标题'}
            con.execute('UPDATE media_items SET metadata_cipher=?,revision=revision+1 WHERE id=?',
                        (env[1]._seal('media-metadata', row, value), google['id']))
    wrapper, calls = read_boundary(env, local, mutate)
    monkeypatch.setattr(env[1].sessions, 'db', wrapper)
    response = client.get(url(local))
    if change == 'anchor_deleted':
        assert response.status_code == 404
    else:
        assert response.status_code == 200, response.json
        assert calls == ['scan', 'scan']
        if change == 'caption':
            assert response.json['items'][0]['caption'] == '当前标题'
            assert response.json['items'][0]['revision'] == google['revision'] + 1
        else:
            assert response.json['total'] == 0 and response.json['items'] == []


@pytest.mark.parametrize('kind', ['session', 'auth_version', 'expired'])
def test_revoked_identity_before_final_projection_returns_no_photo_data(env, monkeypatch, kind):
    client, _, google, local = pair(env)
    wrapper, _ = read_boundary(env, local, lambda con: invalidate(con, kind), final_identity=True)
    monkeypatch.setattr(env[1].sessions, 'db', wrapper)
    response = client.get(url(local))
    assert response.status_code == 401 and 'items' not in response.json
    assert google['id'] not in response.get_data(as_text=True)


def test_deterministic_twenty_item_pagination_rechecks_each_page(env):
    client, _, first = google_photos(env, count=20)
    _, _, last = google_photos(env, count=1)
    _, _, local = local_saved(env, raw_photo())
    expected = sorted(item['id'] for item in first + last)
    one = read(client, local)
    two = read(client, local, '?offset=20')
    assert [item['id'] for item in one['items']] == expected[:20] and one['hasMore']
    assert [item['id'] for item in two['items']] == expected[20:] and not two['hasMore']
    assert one['total'] == two['total'] == 21
    assert read(client, local, '?offset=4000')['items'] == []


def test_real_lock_contention_returns_recoverable_failure_without_writes(env, monkeypatch):
    client, _, _, local = pair(env)
    before = snapshot(env)
    original = env[1].sessions.db
    writer = sqlite3.connect(env[1].sessions.path)
    acquired, scanned = [], []

    @contextmanager
    def connections():
        with original() as con:
            con.execute('PRAGMA busy_timeout=20')  # Test wait only; production timeout unchanged.
            def hold(sql):
                if ' FROM media_items WHERE owner=? AND id!=?' in sql:
                    scanned.append(True)
                if sql == 'BEGIN IMMEDIATE' and scanned:
                    writer.execute('BEGIN IMMEDIATE')
                    acquired.append(True)
            yield ConnectionProxy(con, before=hold)
    monkeypatch.setattr(env[1].sessions, 'db', connections)
    try:
        response = client.get(url(local))
        assert acquired == [True]
        assert response.status_code == 503 and response.json['code'] == 'unavailable'
        assert 'items' not in response.json and 'database' not in response.get_data(as_text=True)
    finally:
        writer.rollback()
        writer.close()
    monkeypatch.setattr(env[1].sessions, 'db', original)
    assert snapshot(env) == before
    assert read(client, local)['total'] == 1


def test_scan_cap_is_real_bounded_sql_and_does_not_claim_exhaustiveness(env):
    client, _, google, local = pair(env)
    engine = env[1]
    # Legacy over-cap fixture: real encrypted metadata and a small synthetic
    # preview ciphertext to satisfy schema; the endpoint never reads that BLOB.
    with engine.transaction(True) as con:
        template = dict(con.execute('SELECT ' + media.ITEM_VIEW + ',preview_cipher FROM media_items WHERE id=?', (google['id'],)).fetchone())
        metadata = engine._metadata(template)
        columns = (media.ITEM_VIEW + ',preview_cipher').split(',')
        for n in range(1001):
            row = template | {'id': f'{n:024x}', 'source_key': f'legacy-source-{n}'}
            value = metadata | {'sourceKey': row['source_key']}
            row['metadata_cipher'] = engine._seal('media-metadata', row, value)
            con.execute('INSERT INTO media_items (' + ','.join(columns) + ') VALUES (' + ','.join('?' for _ in columns) + ')',
                        [row[k] for k in columns])
    result = read(client, local)
    assert result['coverage'] == {'scope': 'mine', 'scanLimit': 1000, 'scanned': 1000,
                                  'capped': True, 'unverifiable': 0}
    assert result['total'] == 1000 and len(result['items']) == 20
    assert [item['id'] for item in result['items']] == [f'{n:024x}' for n in range(20)]


@pytest.mark.parametrize('query', ['?limit=21', '?limit=0', '?offset=-1', '?offset=4001',
                                   '?limit=1&limit=2', '?owner=member2', '?scope=shared'])
def test_strict_query_cannot_expand_scope_or_page(env, query):
    client, _ = login(env[0])
    response = client.get('/api/media/items/' + 'a' * 24 + '/duplicates' + query)
    assert response.status_code == 400 and response.json['code'] == 'invalid_input'
