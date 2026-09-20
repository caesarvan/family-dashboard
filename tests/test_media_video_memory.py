"""Real Flask/SQLite/cipher and WSGI lifetimes; small synthetic decoder output.

This suite tests admission and object ownership, not codec or peak-memory limits.
No Google, FFmpeg, Linux or production requests are made.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import gc
import hashlib
import secrets
import sqlite3
from threading import Event
import weakref

import pytest

import household_media as media
from media_crypto import MediaCipher, MediaCryptoError
from media_import_worker import MediaImportWorker
from media_videos import VideoPreview
from google_photos_picker import DownloadedMedia
from test_household_media import configured, create, confirm, device, preview, selected, session, share, offline
from test_journey_documents import clone, login


def assert_free():
    assert media._VIDEO_READ_SLOT.acquire(blocking=False), 'video permit leaked'
    media._VIDEO_READ_SLOT.release()


@pytest.fixture(autouse=True)
def no_leaked_permit():
    gc.collect()
    assert_free()
    yield
    gc.collect()
    assert_free()


@pytest.fixture
def env(tmp_path, monkeypatch):
    return configured(tmp_path/'one', monkeypatch)


def staged_video(env):
    c, h, imp, _ = create(env)
    engine = env[1]
    assert engine.complete(engine.claim_next(), session(env))
    record = selected('synthetic-video', 'VIDEO')
    record['mediaFile']['mediaFileMetadata']['videoMetadata'] = {'processingStatus':'READY'}
    assert engine.complete(engine.claim_next(), [record])
    job = engine.claim_next()
    raw = b'synthetic already-normalized MP4 bytes for ownership tests'
    video = VideoPreview(raw, 'video/mp4', 20, 12, 1000, False, hashlib.sha256(raw).hexdigest(), preview())
    return c, h, imp, job, record, video


def saved_video(env, raw=None):
    c, h, imp, job, record, video = staged_video(env)
    if raw is not None:
        video = replace(video, data=raw, sha256=hashlib.sha256(raw).hexdigest())
    assert env[1].complete(job, {'mediaId':record['id'], 'manifest':[record], 'preview':video.poster, 'video':video})
    detail = c.get('/api/media/imports/'+imp['id']).json
    confirm(c, h, detail)
    value = c.get('/api/media/items/'+detail['items'][0]['id']).json['item']
    return c, h, value, video.data


def test_concurrent_read_holds_one_process_slot_until_wsgi_close(env, tmp_path, monkeypatch):
    c, h, item, raw = saved_video(env)
    other_env = configured(tmp_path/'two', monkeypatch, household='other-household')
    other, _, second, _ = saved_video(other_env)
    reader = clone(env[0], c)
    entered, proceed = Event(), Event()
    original = MediaCipher.open_bytes
    calls = []

    def decrypt(cipher, purpose, blob):
        if purpose == 'media-video':
            calls.append(cipher)
            entered.set()
            assert proceed.wait(10)
        return original(cipher, purpose, blob)

    monkeypatch.setattr(MediaCipher, 'open_bytes', decrypt)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(reader.get, item['videoUrl'])
        try:
            assert entered.wait(10)
            busy = other.get(second['videoUrl'])
            assert busy.status_code == 503 and busy.json['code'] == 'video_busy'
            assert busy.headers['Retry-After'] == '1' and len(calls) == 1
            assert c.get(item['previewUrl']).status_code == 200
            assert c.get('/healthz').status_code == 200
        finally:
            proceed.set()
        reply = pending.result(timeout=10)
    try:
        assert reply.status_code == 200 and reply.data == raw
        assert other.get(second['videoUrl']).json['code'] == 'video_busy'
    finally:
        reply.close()
        reply.close()  # Idempotent even if server/error cleanup both call close.
    with other.get(second['videoUrl']) as reply:
        assert reply.status_code == 200


@pytest.mark.parametrize('release', ['close', 'disconnect', 'finalize', 'head'])
def test_actual_response_lifetime_releases_without_route_return_release(env, release):
    c, _, item, _ = saved_video(env)
    reply = c.open(item['videoUrl'], method='HEAD' if release == 'head' else 'GET', buffered=False)
    assert reply.status_code == 200
    assert not media._VIDEO_READ_SLOT.acquire(blocking=False)
    if release == 'disconnect':
        # WSGI server's finally closes the iterable when socket writing fails.
        reply.response.close()
    elif release == 'finalize':
        reference = weakref.ref(reply)
        del reply
        gc.collect()
        assert reference() is None
    else:
        reply.close()
    assert_free()
    with c.get(item['videoUrl']) as recovered:
        assert recovered.status_code == 200
        if release != 'finalize':
            reply.close()  # Old cleanup cannot release the next response's slot.
            assert not media._VIDEO_READ_SLOT.acquire(blocking=False)


@pytest.mark.parametrize('failure', ['crypto', 'unexpected', 'missing_cache', 'wrong_digest', 'response'])
def test_errors_before_handoff_release_the_slot(env, monkeypatch, failure):
    c, _, item, _ = saved_video(env)
    original = MediaCipher.open_bytes
    if failure in ('crypto', 'unexpected'):
        def broken(cipher, purpose, blob):
            if purpose == 'media-video':
                raise MediaCryptoError() if failure == 'crypto' else RuntimeError('synthetic')
            return original(cipher, purpose, blob)
        monkeypatch.setattr(MediaCipher, 'open_bytes', broken)
    elif failure == 'response':
        def broken(*args, **kwargs):
            raise RuntimeError('synthetic response construction')
        monkeypatch.setattr(media, 'Response', broken)
    else:
        with env[1].transaction(True) as con:
            if failure == 'missing_cache':
                con.execute('DELETE FROM media_video_cache WHERE media_id=?', (item['id'],))
            else:
                con.execute('UPDATE media_video_cache SET cipher=? WHERE media_id=?',
                            (env[1].cipher.seal_bytes('media-video', b'wrong'), item['id']))
    if failure in ('unexpected', 'response'):
        with pytest.raises(RuntimeError):
            c.get(item['videoUrl'])
    else:
        response = c.get(item['videoUrl'])
        assert response.status_code == 503 and response.json['code'] == 'unavailable'
    assert_free()


def test_tv_and_member_share_slot_but_unauthorized_reads_stay_hidden(env):
    c, h, item, _ = saved_video(env)
    other, _ = login(env[0], 2)
    did, tv, _ = device(env)
    tvurl = '/api/media-tv/items/'+item['id']+'/video'
    held = c.get(item['videoUrl'])
    try:
        assert held.status_code == 200
        assert other.get(item['videoUrl']).status_code == 404
        assert tv.get(tvurl).status_code == 404
        item = share(c, h, item)
        grant = c.put('/api/media/items/'+item['id']+'/tv-grants', json={
            'revision':item['revision'], 'deviceIds':[did], 'consentVersion':'media-v1', 'allowTvDisplay':True}, headers=h)
        assert grant.status_code == 200
        assert tv.get(tvurl).json['code'] == 'video_busy'
    finally:
        held.close()
    with tv.get(tvurl) as response:
        assert response.status_code == 200


def test_authority_is_rechecked_after_admission_before_blob_decryption(env, monkeypatch):
    c, h, item, _ = saved_video(env)
    item = share(c, h, item)
    reader, _ = login(env[0], 2)
    acquire = media._VideoReadPermit.__init__
    original = MediaCipher.open_bytes
    decoded = []

    def racing(permit):
        acquire(permit)
        # A separate request thread must not replace this request's Flask g.
        with ThreadPoolExecutor(max_workers=1) as pool:
            changed = pool.submit(c.patch, '/api/media/items/'+item['id'],
                                  json={'revision':item['revision'], 'visibility':'private'}, headers=h).result(timeout=10)
        assert changed.status_code == 200

    def decrypt(cipher, purpose, blob):
        if purpose == 'media-video':
            decoded.append(True)
        return original(cipher, purpose, blob)

    monkeypatch.setattr(media._VideoReadPermit, '__init__', racing)
    monkeypatch.setattr(MediaCipher, 'open_bytes', decrypt)
    response = reader.get(item['videoUrl'])
    assert response.status_code == 404 and not decoded
    assert_free()


@pytest.mark.parametrize('revoke', ['share', 'device', 'session'])
def test_postdecrypt_authority_change_returns_no_video_and_releases(env, monkeypatch, revoke):
    c, h, item, _ = saved_video(env)
    item = share(c, h, item)
    reader, _ = login(env[0], 2)
    did, tv, _ = device(env)
    granted = c.put('/api/media/items/'+item['id']+'/tv-grants', json={
        'revision':item['revision'], 'deviceIds':[did], 'consentVersion':'media-v1', 'allowTvDisplay':True}, headers=h)
    assert granted.status_code == 200
    original = MediaCipher.open_bytes
    changed = []

    def decrypt(cipher, purpose, blob):
        result = original(cipher, purpose, blob)
        if purpose == 'media-video' and not changed:
            changed.append(True)
            if revoke == 'share':
                assert c.patch('/api/media/items/'+item['id'], json={'revision':granted.json['revision'], 'visibility':'private'}, headers=h).status_code == 200
            elif revoke == 'device':
                assert c.delete('/api/devices/'+did, json={}, headers=h).status_code == 200
            else:
                cookie = reader.get_cookie(env[0].config['SESSION_COOKIE_NAME'])
                env[1].sessions.revoke_cookie(cookie.value)
        return result

    monkeypatch.setattr(MediaCipher, 'open_bytes', decrypt)
    response = (tv.get('/api/media-tv/items/'+item['id']+'/video') if revoke == 'device' else reader.get(item['videoUrl']))
    assert changed and response.status_code in (401,403,404,409,410)
    assert response.content_type != 'video/mp4'
    assert_free()


def test_worker_drops_download_object_before_real_seal_and_commit(env, monkeypatch):
    c, _, imp, job, record, video = staged_video(env)
    references = []

    class Picker:
        def download_media(self, *args, **kwargs):
            value = DownloadedMedia(b'synthetic input', 'video/mp4', 'synthetic.mp4', 'video')
            references.append(weakref.ref(value))
            return value

    def sanitize(raw, content_type, **kwargs):
        assert references[0]() is not None
        return video

    monkeypatch.setattr('media_videos.sanitize_media_video', sanitize)
    original = env[1].complete
    observed = []

    def complete(work, result):
        assert references[0]() is None
        observed.append(True)
        return original(work, result)

    monkeypatch.setattr(env[1], 'complete', complete)
    MediaImportWorker(env[1])._download_video(Picker(), job, record, [record], job['session']['id'])
    assert observed
    detail = c.get('/api/media/imports/'+imp['id']).json
    assert detail['import']['state'] == 'awaiting_confirmation'
    assert len(detail['items']) == 1


def video_error_buffers(error, response_type):
    """Inspect only the video call and completed callees, never test/caller state."""
    found, pending, visited = [], [error], set()

    def large(value, seen):
        if id(value) in seen:
            return False
        seen.add(id(value))
        if isinstance(value, (bytes, bytearray, memoryview)):
            return len(value) >= 1024 * 1024
        if isinstance(value, response_type):
            return large(value.response, seen)
        if isinstance(value, sqlite3.Row):
            return any(large(part, seen) for part in value)
        if isinstance(value, dict):
            return any(large(part, seen) for part in value.values())
        if isinstance(value, (list, tuple)):
            return any(large(part, seen) for part in value)
        return False

    while pending:
        current = pending.pop()
        if id(current) in visited:
            continue
        visited.add(id(current))
        trace, within_video = current.__traceback__, False
        while trace:
            frame = trace.tb_frame
            within_video |= frame.f_code is media.MediaLibrary.video.__code__
            # Chained exceptions begin inside a completed callee and need the
            # same check; the outer error's Flask/test prefixes are excluded.
            if within_video or current is not error:
                for name, value in frame.f_locals.items():
                    if large(value, set()):
                        found.append((frame.f_code.co_name, name))
            trace = trace.tb_next
        pending.extend(value for value in (current.__cause__, current.__context__) if value is not None)
    return found


@pytest.mark.parametrize('failure', ['metadata', 'decrypt', 'constructor', 'close_registration'])
def test_failure_tracebacks_drop_video_buffers_before_error_handoff(env, monkeypatch, failure):
    raw = b'x' * (1024 * 1024)
    c, _, item, _ = saved_video(env, raw)
    real_response = media.Response
    original_open = MediaCipher.open_bytes
    observed = []
    with env[1].transaction() as con:
        original_cipher = bytes(con.execute('SELECT cipher FROM media_video_cache WHERE media_id=?', (item['id'],)).fetchone()[0])

    def inspect(error):
        assert_free()  # Check inside the actual Flask error handler/catcher.
        assert video_error_buffers(error, real_response) == []
        observed.append(error)

    if failure == 'metadata':
        with env[1].transaction(True) as con:
            con.execute('UPDATE media_video_cache SET cipher=? WHERE media_id=?',
                        (env[1].cipher.seal_bytes('media-video', raw + b'changed'), item['id']))
        handlers = env[0].error_handler_spec[None][None]
        original_handler = handlers[media.MediaError]

        def handler(error):
            inspect(error)
            return original_handler(error)

        monkeypatch.setitem(handlers, media.MediaError, handler)
        response = c.get(item['videoUrl'])
        assert response.status_code == 503 and response.json['code'] == 'unavailable'
        with env[1].transaction(True) as con:
            con.execute('UPDATE media_video_cache SET cipher=? WHERE media_id=?', (original_cipher, item['id']))
    else:
        if failure == 'decrypt':
            def broken(cipher, purpose, blob):
                if purpose != 'media-video':
                    return original_open(cipher, purpose, blob)
                try:
                    raise ValueError('inner decoder failure')
                except ValueError as cause:
                    raise RuntimeError('synthetic decrypt failure') from cause
            monkeypatch.setattr(MediaCipher, 'open_bytes', broken)
        else:
            class BrokenResponse(real_response):
                def __init__(self, data, *args, **kwargs):
                    super().__init__(data, *args, **kwargs)
                    if failure == 'constructor':
                        raise RuntimeError('synthetic constructor failure')

                def call_on_close(self, function):
                    raise RuntimeError('synthetic close registration failure')
            monkeypatch.setattr(media, 'Response', BrokenResponse)
        with pytest.raises(RuntimeError, match='synthetic') as caught:
            c.get(item['videoUrl'])
        inspect(caught.value)
        if failure == 'decrypt':
            assert isinstance(caught.value.__cause__, ValueError)
            assert str(caught.value.__cause__) == 'inner decoder failure'
        monkeypatch.setattr(MediaCipher, 'open_bytes', original_open)
        monkeypatch.setattr(media, 'Response', real_response)
    assert len(observed) == 1 and len(raw) == 1024 * 1024 and len(original_cipher) > len(raw)
    # Holding the exception and caller-owned fixtures must not block a new read;
    # cleanup clears callee references, never the caller's objects or exception.
    with c.get(item['videoUrl']) as recovered:
        assert recovered.status_code == 200 and recovered.data == raw
        assert not media._VIDEO_READ_SLOT.acquire(blocking=False)
    assert_free()
