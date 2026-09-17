"""Document access checks at real SQLite/session boundaries; synthetic files only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import sqlite3
from threading import Event
import time
from types import SimpleNamespace

import pytest
from flask import g, request

from test_journey_documents import app, no_network, setup, upload, payload, patch_value, path, login, PDF
from test_device_sessions import database, install_connection, invalidate
from test_member_sessions import legacy


def snapshot(app):
    with closing(sqlite3.connect(database(app))) as con:
        return {table: con.execute('SELECT * FROM ' + table + ' ORDER BY rowid').fetchall()
                for table in ('journey_documents', 'journey_workflows', 'entities', 'audit', 'settings')}


@pytest.mark.parametrize('operation', ['file', 'upload', 'replay'])
def test_legacy_document_session_can_start_the_next_transaction(app, setup, monkeypatch, operation):
    owner, headers, journey = setup
    document, original = upload(owner, headers, journey['id'])
    client, raw, cookie = legacy(app, app.extensions['member_sessions'], monkeypatch)
    legacy_headers = {'X-CSRF-Token': cookie['csrf'], 'Origin': 'http://localhost'}
    listing = client.get('/api/journey-documents')
    assert listing.status_code == 200 and listing.json['documents'][0]['id'] == document['id']
    if operation == 'file':
        response = client.get(document['downloadUrl'])
        assert response.status_code == 200 and response.data == PDF
    else:
        value = original if operation == 'replay' else payload(journey['id'])
        response = client.post('/api/journey-documents', json=value, headers=legacy_headers)
        assert response.status_code == (200 if operation == 'replay' else 201)
        assert response.json['replayed'] is (operation == 'replay')
    assert client.get_cookie('session').value == raw
    final = client.get('/api/journey-documents')
    assert final.status_code == 200
    assert len(final.json['documents']) == (2 if operation == 'upload' else 1)


def prepared(setup, operation):
    client, headers, journey = setup
    document, original = upload(client, headers, journey['id'])
    method, endpoint, body = {
        'list': ('GET', '/api/journey-documents', None),
        'file': ('GET', document['downloadUrl'], None),
        'replay': ('POST', '/api/journey-documents', original),
        'upload': ('POST', '/api/journey-documents', payload(journey['id'])),
        'edit': ('PATCH', path(document), patch_value(document, title='A changed synthetic title')),
        'delete': ('DELETE', path(document), {'revision': document['revision']}),
    }[operation]
    return client, headers, method, endpoint, body


@pytest.mark.parametrize('operation', ['list', 'file', 'replay'])
@pytest.mark.parametrize('kind', ['session', 'expired', 'auth_version'])
def test_document_read_releases_snapshot_before_rechecking_session(app, setup, operation, kind):
    client, headers, method, endpoint, body = prepared(setup, operation)
    before, observed = snapshot(app), []
    target = {'list': 'SELECT j.id,e.data', 'file': 'SELECT content FROM journey_documents',
              'replay': 'SELECT id,payload_digest,deleted_at'}[operation]

    def revoke_after_read(sql):
        if sql.startswith(target) and not observed:
            with sqlite3.connect(database(app)) as con:
                invalidate(con, kind)
            observed.append(kind)

    install_connection(app, endpoint, method, after=revoke_after_read)
    response = client.open(endpoint, method=method, json=body, headers=headers)
    assert observed == [kind]
    assert response.status_code == 401 and set(response.json) == {'error'}
    assert b'SYNTHETIC TICKET' not in response.data and snapshot(app) == before


@pytest.mark.parametrize('operation', ['list', 'file', 'upload', 'edit', 'delete'])
def test_document_routes_compare_the_actual_captured_session(app, setup, operation):
    client, headers, method, endpoint, body = prepared(setup, operation)
    before = snapshot(app)

    def mismatch():
        if request.path == endpoint and request.method == method:
            g.member_session['id'] = '0' * 32

    app.before_request_funcs[None].append(mismatch)
    response = client.open(endpoint, method=method, json=body, headers=headers)
    assert response.status_code == 401 and set(response.json) == {'error'}
    assert snapshot(app) == before


@pytest.mark.parametrize('operation', ['upload', 'edit', 'delete'])
def test_document_expiry_before_commit_rolls_back_content_metadata_and_audit(app, setup, monkeypatch, operation):
    import member_sessions
    client, headers, method, endpoint, body = prepared(setup, operation)
    before, observed = snapshot(app), []
    with closing(sqlite3.connect(database(app))) as con:
        expiry = con.execute("SELECT max(expires_at) FROM member_sessions WHERE owner='member1'").fetchone()[0]
    clock = {'now': time.time()}
    monkeypatch.setattr(member_sessions, 'time', SimpleNamespace(time=lambda: clock['now']))

    def expire_after_audit(sql):
        if sql.startswith('UPDATE settings SET revision'):
            clock['now'] = expiry + 1
            observed.append(True)

    install_connection(app, endpoint, method, after=expire_after_audit)
    response = client.open(endpoint, method=method, json=body, headers=headers)
    assert observed == [True]
    assert response.status_code == 401 and set(response.json) == {'error'}
    assert snapshot(app) == before


@pytest.mark.parametrize('kind', ['session', 'expired', 'auth_version'])
def test_upload_waiting_on_writer_lock_observes_real_revocation(app, setup, kind):
    client, headers, method, endpoint, body = prepared(setup, 'upload')
    before, waiting = snapshot(app), Event()
    writer = sqlite3.connect(database(app), timeout=10, check_same_thread=False)

    def before_begin(sql):
        if sql == 'BEGIN IMMEDIATE':
            writer.execute('BEGIN IMMEDIATE')
            invalidate(writer, kind)
            waiting.set()

    install_connection(app, endpoint, method, before=before_begin)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(client.post, endpoint, json=body, headers=headers)
            try:
                assert waiting.wait(10)
                time.sleep(0.05)
                assert not pending.done()
            finally:
                writer.commit()
            response = pending.result(timeout=10)
        assert response.status_code == 401 and set(response.json) == {'error'}
        assert snapshot(app) == before
    finally:
        writer.close()


@pytest.mark.parametrize('change', ['unshare', 'delete', 'metadata'])
def test_download_checks_current_file_access_after_blob_snapshot(app, setup, change):
    owner, headers, journey = setup
    document, _ = upload(owner, headers, journey['id'], visibility='shared')
    partner, _ = login(app, 2)
    endpoint, observed = document['downloadUrl'], []

    def change_after_blob_read(sql):
        if sql.startswith('SELECT content FROM journey_documents') and not observed:
            # A separate request context must not replace the reader's Flask g.
            with ThreadPoolExecutor(max_workers=1) as pool:
                if change == 'delete':
                    future = pool.submit(owner.delete, path(document), json={'revision': document['revision']}, headers=headers)
                else:
                    changes = {'visibility': 'private'} if change == 'unshare' else {'title': 'Updated synthetic title'}
                    future = pool.submit(owner.patch, path(document), json=patch_value(document, **changes), headers=headers)
                response = future.result(timeout=10)
            assert response.status_code == 200
            observed.append(change)

    install_connection(app, endpoint, 'GET', after=change_after_blob_read)
    response = partner.get(endpoint)
    assert observed == [change]
    assert response.status_code == (409 if change == 'metadata' else 404)
    assert set(response.json) == {'error'} and b'SYNTHETIC TICKET' not in response.data
