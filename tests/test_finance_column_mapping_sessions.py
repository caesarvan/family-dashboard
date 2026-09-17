"""Actual cookie/SQLite boundaries for the file-import entrypoints only."""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import hashlib
import sqlite3
from threading import Event
from types import SimpleNamespace

from flask import g, request
import pytest
from werkzeug.datastructures import ImmutableMultiDict

from test_app import app, member
from test_device_sessions import database, install_connection, invalidate
from test_finance_hub import payload
from test_member_sessions import legacy


def snapshot(app):
    with closing(sqlite3.connect(database(app))) as con:
        return {name: con.execute('SELECT * FROM ' + name + ' ORDER BY 1').fetchall()
                for name in ('hub_transactions', 'hub_imports', 'hub_import_receipts', 'audit', 'settings')}


def prepared(app, operation):
    client, headers = member(app)
    value = payload()
    preview = client.post('/api/finance-hub/imports/preview', json=value, headers=headers)
    assert preview.status_code == 200, preview.json
    value.update(previewToken=preview.json['previewToken'], requestId='a' * 32)
    if operation in ('replay', 'receipt'):
        assert client.post('/api/finance-hub/imports/confirm', json=value, headers=headers).status_code == 200
    path = '/api/finance-hub/imports/' + ('preview' if operation == 'preview' else 'confirm')
    method = 'POST'
    if operation in ('receipt', 'missing'):
        path, method = '/api/finance-hub/imports/results/' + 'a' * 32, 'GET'
    return client, headers, path, method, value


@pytest.mark.parametrize('operation', ['preview', 'confirm', 'replay', 'receipt', 'missing'])
def test_captured_cookie_cannot_be_replaced_by_same_owner_new_session(app, operation):
    client, headers, path, method, value = prepared(app, operation)
    other, _ = member(app)
    raw = other.get_cookie('session').value
    before, seen = snapshot(app), []
    def swap():
        if request.path == path and request.method == method:
            assert g.actor['id'] == 'member1'
            request.__dict__['cookies'] = ImmutableMultiDict({**dict(request.cookies), 'session': raw})
            seen.append(True)
    app.before_request_funcs[None].append(swap)
    response = client.open(path, method=method, json=value, headers=headers)
    assert seen == [True]
    assert response.status_code == 401, response.json
    assert snapshot(app) == before


@pytest.mark.parametrize('operation', ['preview', 'replay', 'receipt', 'missing'])
def test_revocation_after_business_read_is_checked_outside_snapshot(app, operation):
    client, headers, path, method, value = prepared(app, operation)
    before, seen = snapshot(app), []
    target = ('SELECT * FROM hub_transactions WHERE owner=' if operation == 'preview' else
              'SELECT payload_digest,token_digest,result FROM hub_import_receipts WHERE owner=')
    def revoke(sql):
        if sql.startswith(target) and not seen:
            with closing(sqlite3.connect(database(app), timeout=1)) as writer:
                invalidate(writer)
                writer.commit()
            seen.append(True)
    install_connection(app, path, method, after=revoke)
    response = client.open(path, method=method, json=value, headers=headers)
    assert seen == [True]
    assert response.status_code == 401, response.json
    assert snapshot(app) == before


@pytest.mark.parametrize('operation', ['preview', 'confirm', 'replay', 'receipt', 'missing'])
def test_first_legacy_visit_keeps_committed_registration(app, monkeypatch, operation):
    _, _, path, method, value = prepared(app, operation)
    client, raw, signed = legacy(app, app.extensions['member_sessions'], monkeypatch)
    credential = hashlib.sha256(signed['csrf'].encode()).hexdigest()
    with closing(sqlite3.connect(database(app))) as con:
        assert not con.execute('SELECT 1 FROM member_sessions WHERE credential_hash=?', (credential,)).fetchone()
    response = client.open(path, method=method, json=value, headers={'X-CSRF-Token': signed['csrf']})
    assert response.status_code == (404 if operation == 'missing' else 200), response.json
    with closing(sqlite3.connect(database(app))) as con:
        assert con.execute('SELECT legacy,revoked_at FROM member_sessions WHERE credential_hash=?', (credential,)).fetchone() == (1, None)
    assert client.get_cookie('session').value == raw
    assert client.get('/api/me').json['user']['id'] == 'member1'


@pytest.mark.parametrize('operation', ['preview', 'replay', 'receipt'])
def test_legacy_resolution_does_not_hold_write_lock_during_read(app, monkeypatch, operation):
    _, _, path, method, value = prepared(app, operation)
    client, _, signed = legacy(app, app.extensions['member_sessions'], monkeypatch)
    target = ('SELECT * FROM hub_transactions WHERE owner=' if operation == 'preview' else
              'SELECT payload_digest,token_digest,result FROM hub_import_receipts WHERE owner=')
    seen = []
    def revoke(sql):
        if sql.startswith(target) and not seen:
            with closing(sqlite3.connect(database(app), timeout=0.2)) as writer:
                invalidate(writer)
                writer.commit()
            seen.append(True)
    install_connection(app, path, method, after=revoke)
    response = client.open(path, method=method, json=value, headers={'X-CSRF-Token': signed['csrf']})
    assert seen == [True] and response.status_code == 401, response.json


@pytest.mark.parametrize('kind', ['session', 'auth_version', 'ordinary_activity'])
def test_confirmation_checks_identity_after_actual_writer_lock_wait(app, kind):
    client, headers, path, method, value = prepared(app, 'confirm')
    before, waiting, seen = snapshot(app), Event(), []
    with closing(sqlite3.connect(database(app), timeout=5, check_same_thread=False)) as writer:
        def acquire(sql):
            if sql == 'BEGIN IMMEDIATE':
                writer.execute('BEGIN IMMEDIATE')
                if kind == 'ordinary_activity':
                    writer.execute("UPDATE member_sessions SET last_seen_at=last_seen_at+1 WHERE owner='member1'")
                else:
                    invalidate(writer, kind)
                seen.append(True)
                waiting.set()
        install_connection(app, path, method, before=acquire)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(client.open, path, method=method, json=value, headers=headers)
            try:
                assert waiting.wait(5)
                assert not pending.done()
            finally:
                writer.commit()
            response = pending.result(timeout=10)
    assert seen == [True]
    assert response.status_code == (200 if kind == 'ordinary_activity' else 401), response.json
    if kind != 'ordinary_activity':
        assert snapshot(app) == before


def test_expiry_after_import_audit_rolls_back_rows_receipt_and_all_audit(app, monkeypatch):
    import member_sessions
    client, headers, path, method, value = prepared(app, 'confirm')
    before, seen = snapshot(app), []
    with closing(sqlite3.connect(database(app))) as con:
        expiry = con.execute('SELECT max(expires_at) FROM member_sessions').fetchone()[0]
    def expire(sql):
        if sql.startswith('UPDATE settings SET revision=revision+1'):
            monkeypatch.setattr(member_sessions, 'time', SimpleNamespace(time=lambda: expiry + 1))
            seen.append(True)
    install_connection(app, path, method, after=expire)
    response = client.open(path, method=method, json=value, headers=headers)
    assert seen and response.status_code == 401, response.json
    assert snapshot(app) == before
