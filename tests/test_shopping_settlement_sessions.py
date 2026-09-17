"""Real cookie/SQLite fences for the three shopping-settlement routes."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import socket
import sqlite3
from threading import Event
from types import SimpleNamespace

from flask import g, request
import pytest
from werkzeug.datastructures import ImmutableMultiDict

from test_app import app, member
from test_device_sessions import ConnectionProxy, database, install_connection, invalidate
from test_member_sessions import legacy
from test_shopping_settlement import record, shopping, plan, preview, confirm, revoke_plan
from shopping_settlement import PREFIX


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Synthetic settlement tests cannot use the network')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)


def snapshot(app):
    with closing(sqlite3.connect(database(app))) as con:
        return {name: con.execute('SELECT * FROM '+name+' ORDER BY 1').fetchall()
                for name in ('entities', 'hub_transactions', 'hub_imports', 'hub_import_receipts',
                             'hub_reconciliations', 'hub_shopping_settlements',
                             'hub_shopping_settlement_receipts', 'audit', 'settings')}


def prepared(app, operation, client_headers=None):
    client, headers = client_headers or member(app)
    pay, shop = record(client, headers), shopping(client, headers, actual=1300, done=False)
    value = plan(pay, shop, 4200, True)
    proposal = preview(client, headers, value)
    assert proposal.status_code == 200, proposal.json
    if operation == 'replay':
        assert confirm(client, headers, proposal).status_code == 200
    path = PREFIX + ('/context' if operation == 'context' else '/preview' if operation == 'preview' else '/confirm')
    payload = value if operation == 'preview' else {'previewToken': proposal.json['previewToken']}
    return client, headers, path, 'GET' if operation == 'context' else 'POST', payload, value


@pytest.mark.parametrize('operation', ['context', 'preview', 'confirm', 'replay'])
def test_captured_cookie_cannot_be_replaced_by_same_owner_session(app, operation):
    client, headers, path, method, payload, value = prepared(app, 'confirm')
    other, other_headers = member(app)
    # Confirm/replay use a genuine token issued to the replacement session.
    # A mismatch with the original token is already rejected by the old API.
    proposal = preview(other, other_headers, value)
    assert proposal.status_code == 200
    if operation == 'replay':
        assert confirm(other, other_headers, proposal).status_code == 200
    path = PREFIX + ('/context' if operation == 'context' else '/preview' if operation == 'preview' else '/confirm')
    method = 'GET' if operation == 'context' else 'POST'
    payload = value if operation == 'preview' else {'previewToken': proposal.json['previewToken']}
    cookie = other.get_cookie('session').value
    before, seen = snapshot(app), []
    def swap():
        if request.path == path and request.method == method:
            assert g.actor['id'] == 'member1' and g.member_session['owner'] == 'member1'
            request.__dict__['cookies'] = ImmutableMultiDict({**dict(request.cookies), 'session': cookie})
            seen.append(True)
    app.before_request_funcs[None].append(swap)
    response = client.open(path, method=method, json=payload, headers=headers)
    assert seen == [True] and response.status_code == 401, response.json
    assert set(response.json) == {'error'} and snapshot(app) == before


@pytest.mark.parametrize('operation', ['context', 'preview'])
def test_revocation_after_business_read_drops_result(app, operation):
    client, headers, path, method, payload, _ = prepared(app, operation)
    before, seen = snapshot(app), []
    def revoke(sql):
        if sql.startswith('SELECT id,data,revision FROM hub_transactions WHERE owner=') and not seen:
            with closing(sqlite3.connect(database(app), timeout=1)) as writer:
                invalidate(writer)
                writer.commit()
            seen.append(True)
    install_connection(app, path, method, after=revoke)
    response = client.open(path, method=method, json=payload, headers=headers)
    assert seen == [True] and response.status_code == 401, response.json
    assert set(response.json) == {'error'} and snapshot(app) == before


def test_replay_releases_snapshot_before_final_session_check(app):
    client, headers, path, method, payload, _ = prepared(app, 'replay')
    before, seen = snapshot(app), []
    class ReleaseProxy(ConnectionProxy):
        receipt_read = False
        def execute(self, sql, *args):
            result = super().execute(sql, *args)
            if sql.startswith('SELECT result FROM hub_shopping_settlement_receipts'):
                self.receipt_read = True
            return result
        def release(self, operation):
            getattr(self.connection, operation)()
            if self.receipt_read and not seen:
                with closing(sqlite3.connect(database(app), timeout=1)) as writer:
                    invalidate(writer)
                    writer.commit()
                seen.append(True)
        def commit(self):
            self.release('commit')
        def rollback(self):
            self.release('rollback')
    def hook():
        if request.path == path:
            con = sqlite3.connect(database(app), timeout=5)
            con.row_factory = sqlite3.Row
            con.execute('PRAGMA foreign_keys=ON')
            previous = getattr(g, 'db', None)
            if previous is not None:
                previous.close()
            g.db = ReleaseProxy(con)
    app.before_request_funcs[None].append(hook)
    response = client.post(path, json=payload, headers=headers)
    assert seen == [True] and response.status_code == 401, response.json
    assert snapshot(app) == before


@pytest.mark.parametrize('operation', ['apply', 'update', 'revoke'])
def test_expiry_after_audit_rolls_back_shopping_links_receipt_and_audit(app, monkeypatch, operation):
    import member_sessions
    client, headers, path, method, payload, _ = prepared(app, 'confirm')
    if operation != 'apply':
        applied = client.post(path, json=payload, headers=headers)
        assert applied.status_code == 200
        value = ({'operation':'update', 'linkId':applied.json['link']['id'], 'revision':1,
                  'shoppingRevision':applied.json['shopping']['revision'], 'amountCents':3000, 'done':False}
                 if operation == 'update' else revoke_plan(applied.json['link'], applied.json['shopping']['revision'], 'restore_if_unchanged'))
        proposed = preview(client, headers, value)
        assert proposed.status_code == 200, proposed.json
        payload = {'previewToken':proposed.json['previewToken']}
    before, seen = snapshot(app), []
    with closing(sqlite3.connect(database(app))) as con:
        expiry = con.execute('SELECT max(expires_at) FROM member_sessions').fetchone()[0]
    def expire(sql):
        if sql.startswith('UPDATE settings SET revision=revision+1'):
            monkeypatch.setattr(member_sessions, 'time', SimpleNamespace(time=lambda: expiry + 1))
            seen.append(True)
    install_connection(app, path, method, after=expire)
    response = client.post(path, json=payload, headers=headers)
    assert seen == [True] and response.status_code == 401, response.json
    assert snapshot(app) == before


@pytest.mark.parametrize('operation,kind', [('context','session'), ('preview','auth_version'),
                                          ('confirm','expired'), ('replay','session')])
def test_revoked_after_global_actor_is_rejected(app, operation, kind):
    client, headers, path, method, payload, _ = prepared(app, operation)
    before, seen = snapshot(app), []
    def revoke():
        if request.path == path and request.method == method:
            assert g.actor['id'] == 'member1'
            with closing(sqlite3.connect(database(app))) as writer:
                invalidate(writer, kind)
                writer.commit()
            seen.append(True)
    app.before_request_funcs[None].append(revoke)
    response = client.open(path, method=method, json=payload, headers=headers)
    assert seen == [True] and response.status_code == 401, response.json
    assert snapshot(app) == before


@pytest.mark.parametrize('kind', ['session', 'auth_version', 'ordinary_activity'])
def test_confirm_checks_after_actual_writer_lock_wait(app, kind):
    client, headers, path, method, payload, _ = prepared(app, 'confirm')
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
            pending = pool.submit(client.open, path, method=method, json=payload, headers=headers)
            try:
                assert waiting.wait(5) and not pending.done()
            finally:
                writer.commit()
            response = pending.result(timeout=10)
    assert seen == [True]
    assert response.status_code == (200 if kind == 'ordinary_activity' else 401), response.json
    if kind != 'ordinary_activity':
        assert snapshot(app) == before
    else:
        assert response.json['shopping']['actual'] == 4200 and response.json['shopping']['done'] is True


@pytest.mark.parametrize('operation', ['context', 'preview'])
def test_ordinary_session_activity_during_read_is_not_identity_change(app, operation):
    client, headers, path, method, payload, _ = prepared(app, operation)
    before, seen = snapshot(app), []
    def activity(sql):
        if sql.startswith('SELECT id,data,revision FROM hub_transactions WHERE owner=') and not seen:
            with closing(sqlite3.connect(database(app), timeout=1)) as writer:
                writer.execute("UPDATE member_sessions SET last_seen_at=last_seen_at+1 WHERE owner='member1'")
                writer.commit()
            seen.append(True)
    install_connection(app, path, method, after=activity)
    response = client.open(path, method=method, json=payload, headers=headers)
    assert seen == [True] and response.status_code == 200, response.json
    assert snapshot(app) == before


@pytest.mark.parametrize('operation', ['context', 'preview'])
def test_first_legacy_read_preserves_committed_session_registration(app, monkeypatch, operation):
    _, _, path, method, payload, _ = prepared(app, operation)
    client, cookie, signed = legacy(app, app.extensions['member_sessions'], monkeypatch)
    credential = hashlib.sha256(signed['csrf'].encode()).hexdigest()
    with closing(sqlite3.connect(database(app))) as con:
        assert not con.execute('SELECT 1 FROM member_sessions WHERE credential_hash=?', (credential,)).fetchone()
    response = client.open(path, method=method, json=payload, headers={'X-CSRF-Token':signed['csrf']})
    assert response.status_code == 200, response.json
    with closing(sqlite3.connect(database(app))) as con:
        assert con.execute('SELECT legacy,revoked_at FROM member_sessions WHERE credential_hash=?', (credential,)).fetchone() == (1, None)
    assert client.get_cookie('session').value == cookie
    assert client.get('/api/me').json['user']['id'] == 'member1'


@pytest.mark.parametrize('operation', ['context', 'preview'])
def test_legacy_cookie_resolution_does_not_hold_read_writer_lock(app, monkeypatch, operation):
    _, _, path, method, payload, _ = prepared(app, operation)
    client, _, signed = legacy(app, app.extensions['member_sessions'], monkeypatch)
    before, seen = snapshot(app), []
    def revoke(sql):
        if sql.startswith('SELECT id,data,revision FROM hub_transactions WHERE owner=') and not seen:
            with closing(sqlite3.connect(database(app), timeout=0.2)) as writer:
                invalidate(writer)
                writer.commit()
            seen.append(True)
    install_connection(app, path, method, after=revoke)
    response = client.open(path, method=method, json=payload, headers={'X-CSRF-Token':signed['csrf']})
    assert seen == [True] and response.status_code == 401, response.json
    assert snapshot(app) == before


def test_legacy_preview_confirm_and_same_receipt_replay(app, monkeypatch):
    modern, modern_headers = member(app)
    pay, shop = record(modern, modern_headers), shopping(modern, modern_headers)
    client, _, signed = legacy(app, app.extensions['member_sessions'], monkeypatch)
    headers = {'X-CSRF-Token':signed['csrf']}
    proposal = preview(client, headers, plan(pay, shop))
    result = confirm(client, headers, proposal)
    assert result.status_code == 200 and result.json['replayed'] is False
    before = snapshot(app)
    replayed = confirm(client, headers, proposal)
    assert replayed.status_code == 200 and replayed.json == {**result.json,'replayed':True}
    assert snapshot(app) == before


def test_cookie_swapped_after_audit_rolls_back_entire_confirmation(app):
    client, headers, path, method, payload, _ = prepared(app, 'confirm')
    other, _ = member(app)
    cookie = other.get_cookie('session').value
    before, seen = snapshot(app), []
    def swap(sql):
        if sql.startswith('UPDATE settings SET revision=revision+1'):
            request.__dict__['cookies'] = ImmutableMultiDict({**dict(request.cookies), 'session':cookie})
            seen.append(True)
    install_connection(app, path, method, after=swap)
    response = client.post(path, json=payload, headers=headers)
    assert seen == [True] and response.status_code == 401, response.json
    assert snapshot(app) == before


def test_real_audit_error_rolls_back_shared_values_and_receipt(app):
    client, headers, path, _, payload, _ = prepared(app, 'confirm')
    with closing(sqlite3.connect(database(app))) as con:
        con.execute("CREATE TRIGGER reject_settlement_audit BEFORE INSERT ON audit "
                    "WHEN NEW.action LIKE 'finance.shopping.%' "
                    "BEGIN SELECT RAISE(ABORT,'synthetic settlement audit failure'); END")
        con.commit()
    before = snapshot(app)
    with pytest.raises(sqlite3.DatabaseError, match='synthetic settlement audit failure'):
        client.post(path, json=payload, headers=headers)
    assert snapshot(app) == before


@pytest.mark.parametrize('operation', ['confirm', 'replay'])
def test_original_token_expiry_still_precedes_receipt_lookup(app, monkeypatch, operation):
    from itsdangerous import TimestampSigner
    client, headers, path, _, payload, _ = prepared(app, operation)
    before = snapshot(app)
    original = TimestampSigner.get_timestamp
    monkeypatch.setattr(TimestampSigner, 'get_timestamp', lambda self: original(self) + 601)
    response = client.post(path, json=payload, headers=headers)
    assert response.status_code == 400 and set(response.json) == {'error'}
    assert snapshot(app) == before
