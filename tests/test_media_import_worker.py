"""Synthetic transport, real Picker/Pillow, and the shared MediaLibrary SQLite engine."""
from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace
import json
import time
from urllib.error import URLError

import pytest
from PIL import Image

import google_photos_picker as picker_module
from cloud_accounts import AccountBusy
from cloud_providers import ProviderError
from google_photos_picker import GooglePhotosPicker
from media_crypto import MediaCipher
from media_images import sanitize_media_preview
from media_import_worker import MediaImportWorker, MediaScheduler, StopRequest
from test_google_photos_picker import Response, Transport, item, session
from test_cloud_accounts import configured
from test_google_photos_oauth import bind_photos


def public(raw):
    result = deepcopy(raw)
    result['mediaFile'].pop('baseUrl')
    return result


def job(action='download'):
    media = public(item())
    return {'id': 'a' * 24, 'owner': 'member1', 'accountId': 'synthetic-account',
            'action': action, 'leaseToken': 'synthetic-fence', 'revision': 2,
            'expiresAt': 1900000000, 'session': session(), 'manifest': [media],
            'media': media, 'attempts': 0, 'cleanupUnknown': False}


class Accounts:
    def __init__(self):
        self.calls = []
        self.callback = None

    def photos_access_token(self, account_id, owner):
        self.calls.append((account_id, owner))
        if self.callback:
            self.callback()
        return 'synthetic-token-' + str(len(self.calls))


class Engine:
    """Only the public engine protocol: no duplicate SQL/state machine."""
    def __init__(self, work):
        self.work, self.valid = work, True
        self.accounts = Accounts()
        self.completed, self.failed = [], []
        self.maintenance_calls = 0
        self.validation_calls = 0

    def maintenance(self):
        self.maintenance_calls += 1

    def claim_next(self):
        result, self.work = self.work, None
        return result

    def validate_job(self, work):
        self.validation_calls += 1
        return self.valid

    def complete(self, work, value):
        self.completed.append((work, value))
        return self.valid

    def fail(self, work, code, **options):
        self.failed.append((code, options))
        return self.valid


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError('Real network is not allowed')
    monkeypatch.setattr(picker_module, '_transport', forbidden)


@pytest.fixture
def png():
    out = BytesIO()
    Image.new('RGB', (80, 40), (1, 40, 200)).save(out, format='PNG')
    return out.getvalue()


def worker(engine, *responses, sanitizer=sanitize_media_preview):
    transport = Transport(*responses)
    clients = []
    def factory(token):
        client = GooglePhotosPicker(token, transport=transport)
        clients.append(client)
        return client
    value = MediaImportWorker(engine, picker_factory=factory, sanitizer=sanitizer, jitter=lambda: 2)
    return value, transport, clients


def test_download_real_picker_pillow_and_household_cipher(png):
    engine = Engine(job())
    run, transport, clients = worker(engine, session(), {'mediaItems': [item()]}, Response(png, mime='image/png'))
    assert run.tick()
    assert engine.accounts.calls == [('synthetic-account', 'member1')]
    assert not engine.failed and len(engine.completed) == 1
    result = engine.completed[0][1]
    preview = result['preview']
    assert preview.width == 80 and preview.height == 40 and preview.content_type == 'image/jpeg'
    assert result['manifest'] == job()['manifest'] and result['mediaId'] == 'media-1'
    assert len(transport.calls) == 3 and transport.calls[-1]['url'].endswith('=w1600-h1600')
    assert 'pageSize=100' in transport.calls[1]['url']
    assert clients[0]._token == '' and not clients[0]._selected
    cipher = MediaCipher('synthetic-media-secret', 'synthetic-household')
    sealed = cipher.seal_bytes('media-preview', preview.data)
    assert preview.data not in sealed and cipher.open_bytes('media-preview', sealed) == preview.data


def test_fresh_token_and_new_capabilities_for_each_download(png):
    engine = Engine(job())
    run, transport, clients = worker(engine, session(), {'mediaItems': [item()]}, Response(png, mime='image/png'),
                                     session(), {'mediaItems': [item()]}, Response(png, mime='image/png'))
    assert run.tick()
    engine.work = job()
    assert run.tick()
    assert len(clients) == 2 and len(engine.accounts.calls) == 2 and len(transport.calls) == 6
    assert transport.calls[0]['headers']['Authorization'] == 'Bearer synthetic-token-1'
    assert transport.calls[3]['headers']['Authorization'] == 'Bearer synthetic-token-2'
    assert all(not c._token and not c._selected for c in clients)


@pytest.mark.parametrize('change', ['add', 'remove', 'filename', 'created', 'dimensions', 'duplicate-stored'])
def test_changed_complete_manifest_never_downloads(change):
    work = job(); incoming = [item()]
    if change == 'add': incoming.append(item('media-2'))
    elif change == 'remove': incoming = []
    elif change == 'filename': incoming[0]['mediaFile']['filename'] = 'different.png'
    elif change == 'created': incoming[0]['createTime'] = '2025-02-03T00:00:00Z'
    elif change == 'dimensions': incoming[0]['mediaFile']['mediaFileMetadata']['width'] = 201
    else: work['manifest'].append(deepcopy(work['media']))
    engine = Engine(work)
    run, transport, clients = worker(engine, session(), {'mediaItems': incoming})
    assert run.tick()
    assert len(transport.calls) == 2 and not engine.completed
    assert engine.failed[0][0] == 'selection_changed' and not clients[0]._selected


def test_reordered_manifest_and_rotated_base_url_are_accepted(png):
    work = job(); work['manifest'].append(public(item('media-2')))
    one = item(); one['mediaFile']['baseUrl'] = 'https://lh3.googleusercontent.com/rotated-capability'
    engine = Engine(work)
    run, transport, _ = worker(engine, session(), {'mediaItems': [item('media-2'), one]}, Response(png, mime='image/png'))
    assert run.tick() and engine.completed and not engine.failed
    assert transport.calls[-1]['url'].startswith('https://lh3.googleusercontent.com/rotated-capability=')


@pytest.mark.parametrize('boundary', ['before-token', 'token', 'list', 'download', 'sanitize'])
def test_revocation_at_each_io_boundary_discards_result(png, boundary):
    engine = Engine(job())
    def revoke(): engine.valid = False
    if boundary == 'before-token': revoke()
    if boundary == 'token': engine.accounts.callback = revoke
    listing = Response({'mediaItems': [item()]}, on_read=revoke if boundary == 'list' else None)
    download = Response(png, mime='image/png', on_read=revoke if boundary == 'download' else None)
    def sanitize(raw, mime):
        value = sanitize_media_preview(raw, mime)
        if boundary == 'sanitize': revoke()
        return value
    run, transport, clients = worker(engine, session(), listing, download, sanitizer=sanitize)
    assert run.tick() and not engine.completed
    assert len(transport.calls) == {'before-token': 0, 'token': 0, 'list': 2, 'download': 3, 'sanitize': 3}[boundary]
    assert all(not c._token for c in clients)


def test_create_sends_one_post_max_twenty_and_preserves_known_session_for_cleanup():
    engine = Engine(job('create'))
    def revoke(): engine.valid = False
    run, transport, _ = worker(engine, Response(session(), on_read=revoke))
    assert run.tick() and not run.tick()
    assert [c['method'] for c in transport.calls] == ['POST']
    assert json.loads(transport.calls[0]['body']) == {'pickingConfig': {'maxItemCount': '20'}}
    assert engine.completed[0][1]['id'] == session()['id'] and not engine.valid


@pytest.mark.parametrize('error', [URLError('synthetic-private-url'), RuntimeError('synthetic-token-secret')])
def test_create_unknown_never_retries_or_exposes_error(error, capsys, caplog):
    engine = Engine(job('create'))
    run, transport, _ = worker(engine, error)
    assert run.tick() and not run.tick()
    assert len(transport.calls) == 1 and not engine.completed
    assert engine.failed[0][1]['outcome_unknown'] and not engine.failed[0][1]['retryable']
    assert 'synthetic-' not in caplog.text + str(capsys.readouterr())


@pytest.mark.parametrize('action', ['poll', 'list'])
def test_poll_and_list_forward_only_valid_complete_results(action):
    engine = Engine(job(action))
    responses = [session()] if action == 'poll' else [session(), {'mediaItems': [item()]}]
    run, _, _ = worker(engine, *responses)
    assert run.tick() and len(engine.completed) == 1
    assert engine.completed[0][1] == (session() if action == 'poll' else job()['manifest'])


def test_partial_pagination_never_completes_or_downloads():
    engine = Engine(job('list'))
    run, transport, _ = worker(engine, session(), {'mediaItems': [item()], 'nextPageToken': 'page-two'}, URLError('secret'))
    assert run.tick() and not engine.completed and len(transport.calls) == 3
    assert engine.failed[0][0] == 'network' and engine.failed[0][1]['retryable']


def test_invalid_picture_records_only_fixed_item_failure():
    engine = Engine(job())
    run, _, _ = worker(engine, session(), {'mediaItems': [item()]}, Response(b'\x89PNG\r\n\x1a\nbroken', mime='image/png'))
    assert run.tick() and not engine.completed and engine.failed[0][0] == 'invalid_image'


@pytest.mark.parametrize('status,code,retry', [(429, 'rate_limited', True), (503, 'unavailable', True), (403, 'forbidden', False)])
def test_safe_failure_and_bounded_retry_floor(status, code, retry):
    engine = Engine(job('poll'))
    run, _, _ = worker(engine, Response({}, status=status))
    assert run.tick()
    assert engine.failed[0][0] == code and engine.failed[0][1]['retryable'] is retry
    assert engine.failed[0][1]['retry_after'] == (32 if status == 429 else 7)


@pytest.mark.parametrize('error,code', [(ProviderError('private', 401, reauth=True), 'reauth'), (AccountBusy(), 'unavailable')])
def test_token_failure_does_not_construct_picker(error, code):
    engine = Engine(job())
    def fail(): raise error
    engine.accounts.callback = fail
    run, transport, clients = worker(engine)
    assert run.tick() and not transport.calls and not clients and engine.failed[0][0] == code


@pytest.mark.parametrize('unknown,status', [(False, 204), (False, 404), (True, 404)])
def test_cleanup_success_or_readback_absence(unknown, status):
    work = job('cleanup'); work['cleanupUnknown'] = unknown
    engine = Engine(work)
    run, transport, _ = worker(engine, Response(b'', status=status))
    assert run.tick() and engine.completed[0][1] is None
    assert [r['method'] for r in transport.calls] == ['GET' if unknown else 'DELETE']


def test_cleanup_unknown_existing_session_is_not_deleted_again():
    work = job('cleanup'); work['cleanupUnknown'] = True
    engine = Engine(work)
    run, transport, _ = worker(engine, session())
    assert run.tick() and not engine.completed and engine.failed[0][0] == 'cleanup_unknown'
    assert [r['method'] for r in transport.calls] == ['GET']
    assert not engine.failed[0][1]['retryable']


def test_delete_transport_unknown_is_recorded_for_get_readback():
    engine = Engine(job('cleanup'))
    run, transport, _ = worker(engine, URLError('secret'))
    assert run.tick() and engine.failed[0][1]['outcome_unknown']
    assert [r['method'] for r in transport.calls] == ['DELETE']


def test_scheduler_fairness_error_isolation_added_removed_households_and_stop(caplog):
    seen = []; stop = StopRequest()
    class Platform:
        ids = ['c', 'a', 'b']
        def households(self): return [{'id': n} for n in self.ids]
        def child(self, household):
            seen.append(household['id'])
            if household['id'] == 'b': raise RuntimeError('do-not-log-token-or-path')
            return SimpleNamespace(extensions={'household_media': household['id']})
    platform = Platform()
    scheduler = MediaScheduler(platform, stop=stop, worker_factory=lambda engine: SimpleNamespace(tick=lambda: True))
    for _ in range(5): scheduler.tick()
    assert seen == ['a', 'b', 'c', 'a', 'b']
    platform.ids = ['a', 'd']; scheduler.tick(); scheduler.tick()
    assert seen[-2:] == ['d', 'a']
    stop.requested = True; assert not scheduler.tick() and len(seen) == 7
    assert 'do-not-log' not in caplog.text


def test_stop_during_household_loading_does_not_claim_job():
    stop = StopRequest()
    class Platform:
        def households(self): return [{'id': 'a'}]
        def child(self, household):
            stop.requested = True
            return SimpleNamespace(extensions={})
    assert not MediaScheduler(Platform(), stop=stop).tick()


@pytest.fixture
def sqlite_library(configured):
    # Explicit dependency: these tests must run with the separately authored
    # household_media candidate. No substitute schema or SQL engine is copied.
    from household_media import MediaLibrary, initialize_media_library
    app, remote, _ = configured
    with app.extensions['member_sessions'].db() as con:
        initialize_media_library(con)
    now = [time.time()]
    engine = MediaLibrary(app, clock=lambda: now[0])
    client, headers, account_id = bind_photos(app, remote)
    def start(request_id='synthetic-import-request-01'):
        with client:
            assert client.get('/api/me').status_code == 200
            result = engine.create_import({'requestId': request_id, 'accountId': account_id,
                'consentVersion': 'media-v1', 'allowTemporaryProcessing': True})
        return result['import']['id']
    return engine, now, client, headers, start


def import_row(engine, uid):
    with engine.transaction() as con:
        return dict(con.execute('SELECT * FROM media_imports WHERE id=?', (uid,)).fetchone())


def test_sqlite_vertical_create_poll_list_download_cleanup_encrypted_restart(sqlite_library, png):
    engine, now, _, _, start = sqlite_library
    uid = start()
    waiting = session(False)
    run, transport, _ = worker(engine, waiting, session(), session(), {'mediaItems': [item()]},
        session(), {'mediaItems': [item()]}, Response(png, mime='image/png'), Response(b'', status=204))
    assert run.tick() and import_row(engine, uid)['state'] == 'waiting_selection'
    assert not run.tick()
    now[0] += 6
    assert run.tick() and import_row(engine, uid)['state'] == 'listing'
    assert run.tick() and import_row(engine, uid)['state'] == 'staging'
    assert run.tick() and import_row(engine, uid)['state'] == 'awaiting_confirmation'
    assert run.tick() and import_row(engine, uid)['cleanup_state'] == 'done'
    assert sum(c['method'] == 'POST' for c in transport.calls) == 1
    assert sum(c['method'] == 'DELETE' for c in transport.calls) == 1
    with engine.transaction() as con:
        rows = con.execute('SELECT * FROM media_items').fetchall()
    assert len(rows) == 1 and rows[0]['state'] == 'staged' and rows[0]['visibility'] == 'private'
    row = dict(rows[0])
    assert png not in row['preview_cipher'] and item()['mediaFile']['filename'].encode() not in row['metadata_cipher']
    from household_media import MediaLibrary
    restarted = MediaLibrary(engine.app, clock=lambda: now[0])
    metadata = restarted._open('media-metadata', row, row['metadata_cipher'])
    image = restarted.cipher.open_bytes('media-preview', bytes(row['preview_cipher']))
    assert metadata['previewKey'] == row['preview_key'] and metadata['bytes'] == len(image)
    assert metadata['width'] == 80 and metadata['height'] == 40
    assert Image.open(BytesIO(image)).format == 'JPEG'
    assert import_row(restarted, uid)['reserved_bytes'] == 0


def test_sqlite_unknown_create_and_expired_claim_never_post_twice(sqlite_library):
    engine, now, _, _, start = sqlite_library
    uid = start()
    run, transport, _ = worker(engine, URLError('synthetic-private-error'))
    assert run.tick() and import_row(engine, uid)['state'] == 'create_unknown'
    for _ in range(3):
        now[0] += 1000
        assert not run.tick()
    assert len(transport.calls) == 1


def test_sqlite_claim_before_send_crash_stays_unknown_without_post(sqlite_library):
    engine, now, _, _, start = sqlite_library
    uid = start()
    assert engine.claim_next()['action'] == 'create'
    assert import_row(engine, uid)['create_attempted'] == 1
    now[0] += 601
    run, transport, _ = worker(engine)
    assert not run.tick() and not transport.calls
    assert import_row(engine, uid)['state'] == 'create_unknown'


def test_sqlite_real_session_revocation_during_download_discards_ciphertext(sqlite_library, png):
    engine, now, client, headers, start = sqlite_library
    uid = start()
    revoked = []
    def logout():
        if not revoked:
            revoked.append(True)
            assert client.post('/api/logout', json={}, headers=headers).status_code == 200
    run, transport, _ = worker(engine, session(), session(), {'mediaItems': [item()]},
        session(), {'mediaItems': [item()]}, Response(png, mime='image/png', on_read=logout))
    assert run.tick() and run.tick() and run.tick()
    assert import_row(engine, uid)['state'] == 'cancelled'
    with engine.transaction() as con:
        assert con.execute('SELECT count(*) FROM media_items').fetchone()[0] == 0
    assert len(transport.calls) == 6


def test_sqlite_original_poll_deadline_cannot_be_extended(sqlite_library):
    engine, now, _, _, start = sqlite_library
    uid = start()
    waiting = session(False, pollingConfig={'pollInterval': '1s', 'timeoutIn': '2s'})
    run, transport, _ = worker(engine, waiting)
    assert run.tick()
    now[0] += 3
    # The pre-I/O fence expires the claimed poll without sending another GET.
    assert run.tick()
    assert import_row(engine, uid)['state'] == 'expired'
    assert len(transport.calls) == 1


def test_sqlite_local_twenty_four_hour_expiry_clears_staged_blobs(sqlite_library, png):
    engine, now, _, _, start = sqlite_library
    uid = start()
    run, _, _ = worker(engine, session(), session(), {'mediaItems': [item()]},
        session(), {'mediaItems': [item()]}, Response(png, mime='image/png'))
    assert run.tick() and run.tick() and run.tick()
    now[0] += 86401
    engine.maintenance()
    assert import_row(engine, uid)['state'] == 'expired'
    with engine.transaction() as con:
        row = con.execute('SELECT * FROM media_items').fetchone()
    assert row['state'] == 'deleted' and row['preview_cipher'] is None and row['metadata_cipher'] is None
    assert import_row(engine, uid)['reserved_bytes'] == 0


def test_sqlite_known_create_session_after_logout_only_queues_cleanup(sqlite_library):
    engine, _, client, headers, start = sqlite_library
    uid = start(); revoked = []
    def logout_once():
        if not revoked:
            revoked.append(True)
            assert client.post('/api/logout', json={}, headers=headers).status_code == 200
    run, transport, _ = worker(engine, Response(session(), on_read=logout_once), Response(b'', status=204))
    assert run.tick()
    row = import_row(engine, uid)
    assert row['state'] == 'cancelled' and row['session_cipher'] is not None
    assert row['cleanup_state'] == 'pending'
    assert run.tick() and import_row(engine, uid)['cleanup_state'] == 'done'
    assert [call['method'] for call in transport.calls] == ['POST', 'DELETE']


def test_sqlite_partial_staging_selection_change_clears_all_staged(sqlite_library, png):
    engine, _, _, _, start = sqlite_library
    uid = start(); selected = [item(), item('media-2')]
    run, transport, _ = worker(engine, session(), session(), {'mediaItems': selected},
        session(), {'mediaItems': selected}, Response(png, mime='image/png'),
        session(), {'mediaItems': selected + [item('media-3')]})
    assert run.tick() and run.tick() and run.tick()
    with engine.transaction() as con:
        assert con.execute("SELECT count(*) FROM media_items WHERE state='staged'").fetchone()[0] == 1
    assert run.tick() and import_row(engine, uid)['state'] == 'failed'
    with engine.transaction() as con:
        assert con.execute('SELECT count(*) FROM media_items WHERE preview_cipher IS NOT NULL').fetchone()[0] == 0
    assert len(transport.calls) == 8


def test_sqlite_scope_removed_during_fresh_token_prevents_picker_io(sqlite_library, monkeypatch):
    engine, _, _, _, start = sqlite_library
    uid = start(); original = engine.accounts.photos_access_token
    def reduced(account_id, owner):
        token = original(account_id, owner)
        row = engine.accounts.account(account_id, owner)
        tokens = engine.accounts.decrypt(row['tokens'])
        tokens['scope'] = 'https://www.googleapis.com/auth/calendar.readonly'
        with engine.accounts.db() as con:
            con.execute('UPDATE cloud_accounts SET tokens=? WHERE id=?', (engine.accounts.encrypt(tokens), account_id))
        return token
    monkeypatch.setattr(engine.accounts, 'photos_access_token', reduced)
    run, transport, _ = worker(engine)
    assert run.tick() and not transport.calls
    assert import_row(engine, uid)['state'] == 'cancelled'


def test_sqlite_read_retry_backoff_persists_and_stops_at_five_attempts(sqlite_library):
    engine, now, _, _, start = sqlite_library
    uid = start()
    run, transport, _ = worker(engine, session(False), *[Response({}, status=503) for _ in range(5)])
    assert run.tick()
    now[0] += 6
    for attempt in range(5):
        assert run.tick()
        row = import_row(engine, uid)
        if attempt < 4:
            assert row['state'] == 'waiting_selection' and row['attempts'] == attempt + 1
            assert row['next_attempt_at'] - now[0] >= 30 * 2 ** attempt
            assert not run.tick()
            now[0] = row['next_attempt_at']
        else:
            assert row['state'] == 'failed'
    assert [c['method'] for c in transport.calls] == ['POST'] + ['GET'] * 5
