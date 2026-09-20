"""Local originals through real member HTTP, Pillow, encrypted SQLite and restart."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from io import BytesIO
import hashlib
from pathlib import Path
import secrets
from threading import Event

from PIL import Image
import pytest

from app import create_app
import household_media as media
import media_local_upload as upload
from test_household_media import env, offline, confirm, device, share, stage
from test_journey_documents import login
from test_app import app as platform_app, member


URL = '/api/media/local-imports'


def picture(color='red'):
    output = BytesIO()
    Image.new('RGB', (40, 25), color).save(output, 'PNG')
    return output.getvalue()


def intent(raws, **changes):
    return {'requestId': secrets.token_hex(16), 'consentVersion': 'media-v1',
            'allowTemporaryProcessing': True, 'files': [
                {'clientFileId': secrets.token_hex(16), 'filename': f'合成-{n}.png',
                 'contentType': 'image/png', 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                for n, raw in enumerate(raws)], **changes}


def start(env, raws=None, number=1):
    client, headers = login(env[0], number)
    value = intent(raws or [picture()])
    response = client.post(URL, json=value, headers=headers)
    assert response.status_code == 201, response.json
    return client, headers, value, response.json


def put(client, headers, detail, raw, position=0, **changes):
    slot = detail['upload']['files'][position]
    return client.put(URL + '/' + detail['import']['id'] + '/files/' + slot['slotId'],
                      data=raw, content_type=slot['contentType'],
                      headers={**headers, 'X-Import-Revision': str(detail['import']['revision']), **changes})


def finish(client, headers, detail):
    value = {'revision': detail['import']['revision'], 'requestId': secrets.token_hex(16)}
    response = client.post(URL + '/' + detail['import']['id'] + '/finish', headers=headers, json=value)
    assert response.status_code == 200, response.json
    return response.json, value


def saved(env, raw=None):
    raw = raw or picture()
    c, h, v, detail = start(env, [raw])
    response = put(c, h, detail, raw)
    assert response.status_code == 200, response.json
    detail, _ = finish(c, h, response.json)
    confirm(c, h, detail)
    return c, h, c.get('/api/media/items/' + detail['items'][0]['id']).json['item']


def test_no_google_complete_private_encrypted_schema_and_restart(env):
    app, engine, *_ = env
    with engine.transaction(True) as con:
        con.execute('DELETE FROM cloud_accounts')
        schema = list(con.execute('SELECT type,name,sql FROM sqlite_master ORDER BY name'))
    app.config.update(GOOGLE_CLIENT_ID='', GOOGLE_CLIENT_SECRET='')
    c, h, value, detail = start(env)
    assert engine.claim_next() is None  # No token or provider access for local batches.
    assert detail['import']['source'] == 'local-upload'
    assert detail['import']['state'] == 'staging' and detail['upload']['canUpload']
    response = put(c, h, detail, picture())
    assert response.status_code == 200, response.json
    detail, close_intent = finish(c, h, response.json)
    assert detail['import']['canConfirm'] and not detail['upload']['canUpload']
    original = detail['items'][0]['item']
    assert original['visibility'] == 'private'
    assert original['accountId'] is None and original['source'] == 'local-upload'
    assert original['sourceCreatedAt'] is None and original['sourceTimeState'] == 'unknown'
    confirm(c, h, detail)
    result = c.get('/api/media/imports/' + detail['import']['id']).json
    assert result['upload'] == {'files': [], 'canUpload': False}
    assert result['import']['source'] == 'local-upload'
    assert c.post(URL, headers=h, json=value).json['replayed']
    assert c.post(URL + '/' + detail['import']['id'] + '/finish', headers=h, json=close_intent).json['replayed']
    with engine.transaction() as con:
        assert [tuple(x) for x in con.execute('SELECT type,name,sql FROM sqlite_master ORDER BY name')] == [tuple(x) for x in schema]
        row = con.execute('SELECT * FROM media_items WHERE id=?', (original['id'],)).fetchone()
        assert picture() not in bytes(row['preview_cipher'])
        assert b'local-upload' not in bytes(row['metadata_cipher'])
        assert row['account_id'] is None and row['state'] == 'ready'
    restarted = create_app(dict(app.config))
    later, _ = login(restarted)
    assert later.get('/api/media/items/' + original['id']).json['item']['id'] == original['id']
    display = later.get('/api/media/items/' + original['id'] + '/preview')
    assert display.status_code == 200 and display.mimetype == 'image/jpeg'
    assert Image.open(BytesIO(display.data)).info == {}
    display.close()


def test_partial_failure_and_finish_preserves_success_original_confirm(env):
    raws = [picture(), b'not-an-image', picture('blue')]
    c, h, _, detail = start(env, raws)
    detail = put(c, h, detail, raws[0]).json
    response = put(c, h, detail, raws[1], 1)
    assert response.status_code == 200, response.json
    assert response.json['upload']['files'][1]['status'] == 'failed'
    detail, _ = finish(c, h, response.json)
    assert detail['import']['counts'] == dict(selected=3, ready=1, failed=1, skipped=1, pending=0, saved=0, unselected=None)
    assert detail['upload']['files'][2]['error']['code'] == 'local_upload_incomplete'
    confirm(c, h, detail)
    assert len(c.get('/api/media/items').json['items']) == 1


def test_lost_create_and_upload_response_same_intent_no_duplicate(env, monkeypatch):
    c, h, value, detail = start(env)
    replay = c.post(URL, json=value, headers=h)
    assert replay.status_code == 200 and replay.json['import']['id'] == detail['import']['id']
    changed = {**value, 'files': [{**value['files'][0], 'filename': 'different.png'}]}
    assert c.post(URL, json=changed, headers=h).status_code == 409
    first = put(c, h, detail, picture())
    assert first.status_code == 200
    def no_decode(*args):
        raise AssertionError('Acknowledged slot must not decode twice')
    monkeypatch.setattr(upload, 'sanitize_media_preview', no_decode)
    again = put(c, h, detail, picture())
    assert again.status_code == 200 and again.json['replayed']
    assert again.json['import']['revision'] == first.json['import']['revision']
    assert len(again.json['items']) == 1
    wrong = put(c, h, detail, picture('blue'))
    assert wrong.status_code == 422 and wrong.json['code'] == 'local_upload_mismatch'


@pytest.mark.parametrize('change', [
    {'files': []}, {'allowTemporaryProcessing': False}, {'accountId': 'a' * 32},
    {'file': {'filename': '../bad.png'}}, {'file': {'contentType': 'video/mp4'}},
    {'file': {'contentType': []}}, {'file': {'bytes': True}}, {'file': {'bytes': 8388609}},
    {'file': {'sha256': '0' * 63}}, {'file': {'filename': 'x\x00.png'}},
])
def test_strict_declarations_without_rows(env, change):
    c, h = login(env[0])
    value = intent([picture()])
    if 'file' in change:
        value['files'][0].update(change['file'])
    else:
        value.update(change)
    response = c.post(URL, json=value, headers=h)
    assert response.status_code == 400, response.json
    with env[1].transaction() as con:
        assert con.execute('SELECT COUNT(*) FROM media_imports').fetchone()[0] == 0


def test_ten_file_limit_and_existing_quota_reservation(env, monkeypatch):
    c, h = login(env[0])
    assert c.post(URL, json=intent([picture()] * 11), headers=h).status_code == 400
    monkeypatch.setattr(media, 'OWNER_BYTES', 2 * media.ITEM_RESERVATION)
    assert c.post(URL, json=intent([picture()] * 2), headers=h).status_code == 429
    with env[1].transaction() as con:
        assert con.execute('SELECT COUNT(*) FROM media_imports').fetchone()[0] == 0


def test_raw_exact_route_csrf_origin_size_and_other_json_rules(env):
    c, h, _, detail = start(env)
    slot = detail['upload']['files'][0]
    path = URL + '/' + detail['import']['id'] + '/files/' + slot['slotId']
    assert c.put(path, data=picture(), content_type='image/png').status_code == 403
    assert put(c, h, detail, picture(), Origin='https://invalid.example').status_code == 403
    assert c.put(path, data=b'x' * 8388609, content_type='image/png', headers={**h, 'X-Import-Revision': '1'}).status_code == 413
    assert c.post('/api/items/tasks', data=picture(), content_type='image/png', headers=h).status_code == 415
    assert c.put(path.replace(slot['slotId'], 'invalid'), data=picture(), content_type='image/png', headers=h).status_code == 415
    assert put(c, h, detail, picture(), **{'Content-Encoding': 'gzip'}).status_code == 415


def test_busy_no_body_consumption_and_exception_release(env, monkeypatch):
    c, h, _, detail = start(env)
    assert upload._UPLOAD_SLOT.acquire(False)
    try:
        result = put(c, h, detail, picture())
        assert result.status_code == 503 and result.headers['Retry-After'] == '1'
    finally:
        upload._UPLOAD_SLOT.release()
    original = upload.sanitize_media_preview
    def broken(*args):
        raise RuntimeError('synthetic decoder failure')
    monkeypatch.setattr(upload, 'sanitize_media_preview', broken)
    with pytest.raises(RuntimeError):
        put(c, h, detail, picture())
    monkeypatch.setattr(upload, 'sanitize_media_preview', original)
    assert put(c, h, detail, picture()).status_code == 200


def test_revoke_during_decode_cannot_persist_and_cleanup_clears(env, monkeypatch):
    c, h, _, detail = start(env)
    original = upload.sanitize_media_preview
    def revoke(raw, mime):
        with env[1].transaction(True) as con:
            con.execute("UPDATE member_sessions SET revoked_at=? WHERE owner='member1'", (env[1].clock(),))
        return original(raw, mime)
    monkeypatch.setattr(upload, 'sanitize_media_preview', revoke)
    assert put(c, h, detail, picture()).status_code in (401, 410)
    env[1].maintenance()
    with env[1].transaction() as con:
        assert con.execute('SELECT COUNT(*) FROM media_items').fetchone()[0] == 0
        row = con.execute('SELECT * FROM media_imports').fetchone()
        assert row['state'] == 'cancelled' and row['reserved_bytes'] == 0 and row['manifest_cipher'] is None


def test_cancel_and_expiry_deny_late_body_and_confirm(env):
    c, h, _, detail = start(env)
    assert c.delete('/api/media/imports/' + detail['import']['id'], headers=h,
                    json={'revision': detail['import']['revision']}).status_code == 200
    assert put(c, h, detail, picture()).status_code == 410
    c, h, _, detail = start(env)
    detail = put(c, h, detail, picture()).json
    env[2][0] += 86401
    assert env[1].maintenance() == 1
    current = c.get('/api/media/imports/' + detail['import']['id'])
    if current.status_code == 200:
        assert current.json['upload'] == {'files': [], 'canUpload': False}
    with env[1].transaction() as con:
        assert not con.execute("SELECT id FROM media_items WHERE state!='deleted'").fetchall()


def test_duplicate_bytes_same_batch_and_restart_use_original_id(env):
    c, h, _, detail = start(env, [picture(), picture()])
    detail = put(c, h, detail, picture()).json
    detail = put(c, h, detail, picture(), 1).json
    assert len(detail['items']) == 1
    assert [s['status'] for s in detail['upload']['files']] == ['successful', 'duplicate']
    detail, _ = finish(c, h, detail)
    confirm(c, h, detail)
    c2, h2, _, second = start(env)
    second = put(c2, h2, second, picture()).json
    assert second['items'][0]['id'] == detail['items'][0]['id']
    assert second['upload']['files'][0]['status'] == 'duplicate'


def test_sharing_tv_revoke_source_metadata_and_private_original(env):
    c, h, item = saved(env)
    partner, ph = login(env[0], 2)
    assert partner.get('/api/media/items/' + item['id']).status_code == 404
    shared = share(c, h, item)
    visible = partner.get('/api/media/items/' + item['id']).json['item']
    assert visible['id'] == item['id'] and 'displayFilename' not in visible and 'source' not in visible
    uid, television, _ = device(env)
    assert television.get('/api/media-tv/items').json['items'] == []
    grant = c.put('/api/media/items/' + item['id'] + '/tv-grants', headers=h,
                  json={'revision': shared['revision'], 'deviceIds': [uid], 'consentVersion': 'media-v1', 'allowTvDisplay': True})
    assert grant.status_code == 200, grant.json
    assert television.get('/api/media-tv/items').json['items'][0]['id'] == item['id']
    playback = env[0].extensions['media_playback']
    with env[1].transaction() as con:
        assert [r['id'] for r in playback._photos(con, uid)] == [item['id']]
    assert television.post(URL, json=intent([picture()])).status_code == 403
    private = c.patch('/api/media/items/' + item['id'], headers=h,
                      json={'revision': grant.json['revision'], 'visibility': 'private'})
    assert private.status_code == 200
    assert television.get('/api/media-tv/items').json['items'] == []
    assert partner.get('/api/media/items/' + item['id']).status_code == 404


def test_google_null_account_is_not_local_authority(env):
    c, h, detail, _ = stage(env)
    confirm(c, h, detail)
    item = share(c, h, c.get('/api/media/items/' + detail['items'][0]['id']).json['item'])
    with env[1].transaction(True) as con:
        con.execute('UPDATE media_items SET account_id=NULL WHERE id=?', (item['id'],))
        row = con.execute('SELECT * FROM media_items WHERE id=?', (item['id'],)).fetchone()
        assert not env[1]._media_authority(con, row)
    partner, _ = login(env[0], 2)
    assert partner.get('/api/media/items/' + item['id']).status_code == 404
    assert partner.get('/api/media/items?scope=shared').json['items'] == []


def test_local_inactive_owner_immediately_hides_shared(env):
    c, h, item = saved(env)
    share(c, h, item)
    other, _ = login(env[0], 2)
    with env[1].transaction(True) as con:
        con.execute("UPDATE household_memberships SET state='removed' WHERE member_id='member1'")
    assert other.get('/api/media/items?scope=shared').json['items'] == []


def test_nginx_exact_raw_location_without_general_limit_expansion():
    text = (Path(__file__).parents[1] / 'deploy/nginx.conf').read_text()
    assert text.count('location ~ "^/api/media/local-imports/[a-f0-9]{24}/files/[a-f0-9]{24}$"') == 2
    assert text.count('proxy_request_buffering off;') == 2
    assert text.count('proxy_http_version 1.1;') == 2
    assert 'client_max_body_size 100m' not in text and '/space/.*/api' not in text


def test_actual_space_cookie_uses_same_raw_path_and_isolates_ids(platform_app):
    from test_household_spaces import create_space
    root, rh = member(platform_app)
    child, _, space = create_space(platform_app)
    assert child.get(space['entry']).status_code == 303
    assert child.post('/api/login', json={'username': 'member1', 'password': 'second-home-password-one'}).status_code == 200
    headers = {'X-CSRF-Token': child.get('/api/me').json['csrf']}
    detail = child.post(URL, json=intent([picture()]), headers=headers).json
    assert root.get('/api/media/imports/' + detail['import']['id']).status_code == 404
    assert put(root, rh, detail, picture()).status_code == 404
    result = put(child, headers, detail, picture())
    assert result.status_code == 200, result.json
    final, _ = finish(child, headers, result.json)
    confirm(child, headers, final)
    assert root.get('/api/media/items').json['items'] == []
    assert len(child.get('/api/media/items').json['items']) == 1


def test_search_and_export_share_exact_source_acl(env):
    from test_media_portability import snapshot
    c, h, item = saved(env)
    current = c.patch('/api/media/items/' + item['id'], headers=h,
                      json={'revision': item['revision'], 'caption': 'LOCAL_SEARCH_CANARY', 'visibility': 'shared'})
    assert current.status_code == 200
    other, oh = login(env[0], 2)
    assert item['id'] in other.get('/api/assistant/search?q=LOCAL_SEARCH_CANARY').get_data(as_text=True)
    own, _ = snapshot(c.post('/api/portability/export', json={}, headers=h))
    shared, _ = snapshot(other.post('/api/portability/export', json={'includeShared': True}, headers=oh))
    assert own['personal']['householdMedia'][0]['source'] == 'local-upload'
    assert own['personal']['householdMedia'][0]['sourceCreatedAt'] is None
    projected = shared['shared']['householdMedia'][0]
    assert projected['id'] == item['id'] and 'source' not in projected and 'displayFilename' not in projected
    assert c.patch('/api/media/items/' + item['id'], headers=h,
                   json={'revision': current.json['item']['revision'], 'visibility': 'private'}).status_code == 200
    assert item['id'] not in other.get('/api/assistant/search?q=LOCAL_SEARCH_CANARY').get_data(as_text=True)


def test_actual_concurrent_decode_does_not_hold_transaction_or_admit_second(env, monkeypatch):
    entered, release = Event(), Event()
    original = upload.sanitize_media_preview
    c, h, _, detail = start(env)
    def held(raw, mime):
        entered.set()
        assert release.wait(10), 'coordinator failed to release synthetic decoder'
        return original(raw, mime)
    monkeypatch.setattr(upload, 'sanitize_media_preview', held)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(put, c, h, detail, picture())
        try:
            assert entered.wait(10)
            other, oh, _, second = start(env, number=2)
            assert put(other, oh, second, picture()).status_code == 503
            result = other.post(URL + '/' + second['import']['id'] + '/finish', headers=oh,
                                json={'revision': second['import']['revision'], 'requestId': secrets.token_hex(16)})
            assert result.status_code == 200  # A real writer proceeds while decoding.
        finally:
            release.set()
        assert future.result(timeout=10).status_code == 200
