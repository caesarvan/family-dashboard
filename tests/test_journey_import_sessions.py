"""Import session boundaries against actual Flask authentication and SQLite."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import sqlite3
from threading import Event
import time
from types import SimpleNamespace

from flask import g, request
from itsdangerous import TimestampSigner
import pytest
from werkzeug.datastructures import ImmutableMultiDict

from test_app import app, member
from test_device_sessions import database, install_connection, invalidate, ConnectionProxy
from test_journey_workflows import plan, preview, apply, create
from test_journey_edit_snapshot import snapshot
from test_member_sessions import legacy


KEY = 'import-session-original'


def prepared(app, operation):
    client, headers = member(app)
    candidate = preview(client, headers)
    if operation in ('replay', 'receipt'):
        assert apply(client, headers, candidate, KEY).status_code == 201
    path = '/api/journeys/operations/' + KEY if operation in ('receipt', 'missing') else '/api/journeys/' + operation
    if operation == 'replay':
        path = '/api/journeys/apply'
    method = 'GET' if operation in ('receipt', 'missing') else 'POST'
    value = {'plan': plan()} if operation == 'preview' else {
        'previewToken': candidate['previewToken'], 'idempotencyKey': KEY}
    return client, headers, path, method, value


def replace_cookie(raw):
    cookies = dict(request.cookies)
    cookies['session'] = raw
    request.__dict__['cookies'] = ImmutableMultiDict(cookies)


@pytest.mark.parametrize('operation', ['preview', 'apply', 'replay', 'receipt', 'missing'])
def test_original_session_cannot_be_replaced_by_other_valid_same_owner_cookie(app, operation):
    client, headers, path, method, value = prepared(app, operation)
    replacement, _ = member(app)
    raw = replacement.get_cookie('session').value
    assert raw != client.get_cookie('session').value
    before, seen = snapshot(app), []

    def swap_after_auth():
        if request.path == path and request.method == method:
            assert g.actor['id'] == 'member1'
            replace_cookie(raw)
            seen.append(True)

    app.before_request_funcs[None].append(swap_after_auth)
    response = client.open(path, method=method, json=value, headers=headers)
    assert seen == [True]
    assert response.status_code == 401, response.json
    assert snapshot(app) == before


@pytest.mark.parametrize('operation', ['apply', 'reschedule'])
def test_expiry_after_audit_rolls_back_all_domain_rows(app, monkeypatch, operation):
    import member_sessions
    client, headers, path, method, value = prepared(app, 'apply')
    if operation == 'reschedule':
        from test_journey_reschedule import source, reschedule
        saved = create(client, headers)
        candidate = reschedule(client, headers, source(client, saved['id']), start='2026-12-04', end='2026-12-10')
        value = {'previewToken': candidate['previewToken'], 'idempotencyKey': KEY}
    before, seen = snapshot(app), []
    with closing(sqlite3.connect(database(app))) as con:
        expiry = con.execute('SELECT max(expires_at) FROM member_sessions').fetchone()[0]

    def after_audit(sql):
        if sql.startswith('UPDATE settings SET revision=revision+1'):
            monkeypatch.setattr(member_sessions, 'time', SimpleNamespace(time=lambda: expiry + 1))
            seen.append(True)

    install_connection(app, path, method, after=after_audit)
    response = client.open(path, method=method, json=value, headers=headers)
    assert seen == [True]
    assert response.status_code == 401, response.json
    assert snapshot(app) == before


@pytest.mark.parametrize('alternate_key', [False, True])
def test_replay_releases_snapshot_then_rechecks_session(app, alternate_key):
    client, headers, path, method, value = prepared(app, 'replay')
    if alternate_key:
        value['idempotencyKey'] = 'import-other-original-key'
    before, seen = snapshot(app), []

    class ReplayConnection(ConnectionProxy):
        def rollback(self):
            self.connection.rollback()
            if seen == ['receipt']:
                with closing(sqlite3.connect(database(app))) as writer:
                    invalidate(writer)
                    writer.commit()
                seen.append('revoked')

    def hook():
        if request.path == path:
            con = sqlite3.connect(database(app), timeout=5)
            con.row_factory = sqlite3.Row
            con.execute('PRAGMA foreign_keys=ON')
            def after(sql):
                target = 'SELECT * FROM journey_actions WHERE ' + ('operation_id' if alternate_key else 'actor')
                if sql.startswith(target):
                    seen.append('receipt')
            if getattr(g, 'db', None) is not None:
                g.db.close()
            g.db = ReplayConnection(con, after=after)

    app.before_request_funcs[None].append(hook)
    response = client.open(path, method=method, json=value, headers=headers)
    assert seen == ['receipt', 'revoked']
    assert response.status_code == 401, response.json
    assert snapshot(app) == before


@pytest.mark.parametrize('operation', ['preview', 'receipt', 'missing'])
def test_legacy_read_holds_no_resolution_write_lock(app, monkeypatch, operation):
    _, _, path, method, value = prepared(app, operation)
    client, raw, signed = legacy(app, app.extensions['member_sessions'], monkeypatch)
    headers = {'X-CSRF-Token': signed['csrf']}
    before, seen = snapshot(app), []
    target = 'SELECT id FROM users ORDER BY id' if operation == 'preview' else 'SELECT result FROM journey_actions'

    def revoke_during_read(sql):
        if sql.startswith(target) and not seen:
            with closing(sqlite3.connect(database(app), timeout=0.2)) as writer:
                invalidate(writer)
                writer.commit()
            seen.append(True)

    install_connection(app, path, method, after=revoke_during_read)
    response = client.open(path, method=method, json=value, headers=headers)
    assert seen == [True]
    assert response.status_code == 401, response.json
    assert client.get_cookie('session').value == raw
    assert snapshot(app) == before


@pytest.mark.parametrize('operation', ['preview', 'receipt', 'missing'])
@pytest.mark.parametrize('kind', ['session', 'expired', 'auth_version'])
def test_read_uses_fresh_auth_after_domain_snapshot(app, operation, kind):
    client, headers, path, method, value = prepared(app, operation)
    before, seen = snapshot(app), []
    target = 'SELECT id FROM users ORDER BY id' if operation == 'preview' else 'SELECT result FROM journey_actions'

    def revoke_after_read(sql):
        if sql.startswith(target) and not seen:
            with closing(sqlite3.connect(database(app))) as writer:
                invalidate(writer, kind)
                writer.commit()
            seen.append(True)

    install_connection(app, path, method, after=revoke_after_read)
    response = client.open(path, method=method, json=value, headers=headers)
    assert seen == [True] and response.status_code == 401, response.json
    assert snapshot(app) == before


@pytest.mark.parametrize('operation', ['apply', 'replay'])
@pytest.mark.parametrize('kind', ['session', 'expired', 'auth_version', 'ordinary_activity'])
def test_write_lock_wait_checks_committed_identity_without_rejecting_normal_activity(app, operation, kind):
    client, headers, path, method, value = prepared(app, operation)
    before, waiting, seen = snapshot(app), Event(), []
    with closing(sqlite3.connect(database(app), timeout=5, check_same_thread=False)) as writer:
        def before_begin(sql):
            if sql == 'BEGIN IMMEDIATE':
                writer.execute('BEGIN IMMEDIATE')
                if kind == 'ordinary_activity':
                    writer.execute("UPDATE member_sessions SET last_seen_at=last_seen_at+1 WHERE owner='member1'")
                else:
                    invalidate(writer, kind)
                seen.append(True)
                waiting.set()

        install_connection(app, path, method, before=before_begin)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(client.open, path, method=method, json=value, headers=headers)
            try:
                assert waiting.wait(5)
                time.sleep(0.05)
                assert not pending.done()
            finally:
                writer.commit()
            response = pending.result(timeout=10)
    assert seen == [True]
    if kind == 'ordinary_activity':
        assert response.status_code == (201 if operation == 'apply' else 200), response.json
        assert response.json['replayed'] == (operation == 'replay')
    else:
        assert response.status_code == 401, response.json
        assert snapshot(app) == before


@pytest.mark.parametrize('number', [1, 2])
def test_cookie_replacement_after_audit_rolls_back(app, number):
    client, headers, path, method, value = prepared(app, 'apply')
    replacement, _ = member(app, number)
    raw = replacement.get_cookie('session').value
    before, seen = snapshot(app), []

    def after_audit(sql):
        if sql.startswith('UPDATE settings SET revision=revision+1'):
            replace_cookie(raw)
            seen.append(True)

    install_connection(app, path, method, after=after_audit)
    response = client.open(path, method=method, json=value, headers=headers)
    assert seen == [True] and response.status_code == 401, response.json
    assert snapshot(app) == before


@pytest.mark.parametrize('operation', ['preview', 'receipt', 'missing', 'apply', 'replay', 'reschedule'])
def test_first_legacy_visit_preserves_registered_session_and_compatible_operations(app, monkeypatch, operation):
    import hashlib
    original, original_headers, path, method, value = prepared(app, 'apply' if operation == 'reschedule' else operation)
    saved = create(original, original_headers) if operation == 'reschedule' else None
    client, raw, signed = legacy(app, app.extensions['member_sessions'], monkeypatch)
    credential = hashlib.sha256(signed['csrf'].encode()).hexdigest()
    headers = {'X-CSRF-Token': signed['csrf']}
    with closing(sqlite3.connect(database(app))) as con:
        assert not con.execute('SELECT 1 FROM member_sessions WHERE credential_hash=?', (credential,)).fetchone()
    if operation == 'reschedule':
        from test_journey_reschedule import source, reschedule
        candidate = reschedule(client, headers, source(client, saved['id']), start='2026-12-04', end='2026-12-10')
        value = {'previewToken': candidate['previewToken'], 'idempotencyKey': KEY}
    response = client.open(path, method=method, json=value, headers=headers)
    expected = 404 if operation == 'missing' else 201 if operation == 'apply' else 200
    assert response.status_code == expected, response.json
    with closing(sqlite3.connect(database(app))) as con:
        row = con.execute('SELECT id,legacy,revoked_at FROM member_sessions WHERE credential_hash=?', (credential,)).fetchone()
        assert row and row[1:] == (1, None)
        assert con.execute("SELECT 1 FROM settings WHERE id='journey_namespace'").fetchone()
    assert client.get_cookie('session').value == raw
    assert client.get('/api/journeys/templates').status_code == 200
    if operation in ('apply', 'replay', 'reschedule'):
        assert client.get('/api/journeys/operations/' + KEY).status_code == 200
        repeated = client.post('/api/journeys/apply', json=value, headers=headers)
        assert repeated.status_code == 200 and repeated.json['replayed'] is True
    with closing(sqlite3.connect(database(app))) as con:
        assert con.execute('SELECT id FROM member_sessions WHERE credential_hash=?', (credential,)).fetchone()[0] == row[0]


def test_new_request_same_owner_session_can_recover_but_partner_cannot(app):
    client, headers = member(app)
    candidate = preview(client, headers)
    second, second_headers = member(app)
    committed = apply(second, second_headers, candidate, KEY)
    assert committed.status_code == 201, committed.json
    before = snapshot(app)
    assert apply(client, headers, candidate, KEY).json['replayed'] is True
    assert client.get('/api/journeys/operations/' + KEY).json['result']['id'] == committed.json['id']
    partner, partner_headers = member(app, 2)
    assert partner.get('/api/journeys/operations/' + KEY).status_code == 404
    assert apply(partner, partner_headers, candidate, KEY).status_code == 403
    assert snapshot(app) == before


@pytest.mark.parametrize('committed', [False, True])
def test_ordinary_expired_preview_stays_409_while_operation_read_is_independent(app, monkeypatch, committed):
    client, headers = member(app)
    original_clock = TimestampSigner.get_timestamp

    def journey_clock(signer):
        now = original_clock(signer)
        # Age only the actual journey signature, not the login cookie.
        return now - 1801 if signer.salt == b'household-journey-preview-v1' else now

    with monkeypatch.context() as old:
        old.setattr(TimestampSigner, 'get_timestamp', journey_clock)
        candidate = preview(client, headers)
        if committed:
            saved = apply(client, headers, candidate, KEY)
            assert saved.status_code == 201
    before = snapshot(app)
    response = apply(client, headers, candidate, KEY)
    assert response.status_code == 409 and '过期' in response.json['error']
    receipt = client.get('/api/journeys/operations/' + KEY)
    assert receipt.status_code == (200 if committed else 404)
    if committed:
        assert receipt.json['result']['id'] == saved.json['id']
    else:
        assert receipt.json['code'] == 'operation_not_found'
    assert snapshot(app) == before
