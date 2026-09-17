"""Device management uses real sessions at the transaction boundary.

Only temporary households, actual Flask routes and separate SQLite connections
are used. Authentication results are never stubbed as valid or revoked.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3
from threading import Barrier, Event
import time
from types import SimpleNamespace

import pytest
from flask import g, request

from test_app import app, member
from test_household_spaces import create_space


def database(app):
    return Path(app.config['DATA_DIR']) / 'household.sqlite3'


def snapshot(app):
    with closing(sqlite3.connect(database(app))) as con:
        return {table: con.execute('SELECT * FROM ' + table + ' ORDER BY 1').fetchall()
                for table in ('devices', 'media_playback', 'media_tv_grants', 'audit', 'settings')}


def setup(app, operation):
    client, headers = member(app)
    tv = app.test_client()
    pair = tv.post('/api/pair/start', json={}).json
    with closing(sqlite3.connect(database(app))) as con:
        uid = con.execute('SELECT id FROM devices WHERE code=?', (pair['code'],)).fetchone()[0]
    if operation != 'approve':
        assert client.post('/api/pair/approve', json={'code': pair['code'], 'name': 'Synthetic TV'}, headers=headers).status_code == 200
        assert tv.post('/api/pair/poll', json={'secret': pair['secret']}).json['approved']
    method, path, payload = {
        'approve': ('POST', '/api/pair/approve', {'code': pair['code'], 'name': 'Approved'}),
        'list': ('GET', '/api/devices', None),
        'edit': ('PATCH', '/api/devices/' + uid, {'revision': 1, 'name': 'Updated'}),
        'revoke': ('DELETE', '/api/devices/' + uid, {}),
    }[operation]
    return client, headers, tv, pair, uid, method, path, payload


def invalidate(con, kind='session'):
    if kind == 'session':
        result = con.execute("UPDATE member_sessions SET revoked_at=1 WHERE owner='member1' AND revoked_at IS NULL")
    elif kind == 'expired':
        result = con.execute("UPDATE member_sessions SET expires_at=1 WHERE owner='member1'")
    else:
        result = con.execute("UPDATE users SET auth_version=auth_version+1 WHERE id='member1'")
    assert result.rowcount > 0


@pytest.mark.parametrize('operation', ['approve', 'list', 'edit', 'revoke'])
@pytest.mark.parametrize('kind', ['session', 'expired', 'auth_version'])
def test_revoked_after_auth_cannot_manage_devices(app, operation, kind):
    client, headers, _, _, _, method, path, payload = setup(app, operation)
    before, calls = snapshot(app), []

    def revoke_after_guard():
        if request.path == path and request.method == method:
            assert g.actor['id'] == 'member1'
            with sqlite3.connect(database(app)) as con:
                invalidate(con, kind)
            calls.append(kind)

    app.before_request_funcs[None].append(revoke_after_guard)
    response = client.open(path, method=method, json=payload, headers=headers)
    assert calls == [kind]
    assert response.status_code == 401, response.json
    assert set(response.json) == {'error'}
    assert snapshot(app) == before


class ConnectionProxy:
    def __init__(self, connection, before=None, after=None):
        self.connection, self.before, self.after = connection, before, after

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def execute(self, sql, *args):
        if self.before:
            self.before(sql)
        result = self.connection.execute(sql, *args)
        if self.after:
            self.after(sql)
        return result


def install_connection(app, path, method, before=None, after=None):
    def hook():
        if request.path == path and request.method == method:
            con = sqlite3.connect(database(app), timeout=5)
            con.row_factory = sqlite3.Row
            con.execute('PRAGMA foreign_keys=ON')
            previous = getattr(g, 'db', None)
            if previous is not None:
                previous.close()
            g.db = ConnectionProxy(con, before, after)
    app.before_request_funcs[None].append(hook)


@pytest.mark.parametrize('operation', ['approve', 'edit', 'revoke'])
def test_revoke_committed_while_write_waits_for_sqlite_lock(app, operation):
    client, headers, _, _, _, method, path, payload = setup(app, operation)
    before, entered = snapshot(app), Event()
    writer = sqlite3.connect(database(app), timeout=5, check_same_thread=False)

    def begin(sql):
        if sql == 'BEGIN IMMEDIATE':
            # This real second connection owns the writer lock before the
            # endpoint attempts BEGIN. Authentication has already completed.
            writer.execute('BEGIN IMMEDIATE')
            invalidate(writer)
            entered.set()

    install_connection(app, path, method, before=begin)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(client.open, path, method=method, json=payload, headers=headers)
            try:
                assert entered.wait(10)
                assert not pending.done()
            finally:
                writer.commit()
            response = pending.result(timeout=10)
        assert response.status_code == 401, response.json
        assert snapshot(app) == before
    finally:
        writer.close()


def test_list_drops_snapshot_if_session_revoked_during_row_decode(app, monkeypatch):
    import app as app_module
    client, _, _, _, _, _, _, _ = setup(app, 'list')
    before, calls = snapshot(app), []
    original = app_module.stored_layout

    def revoke_while_decoding(value):
        if not calls:
            with sqlite3.connect(database(app)) as con:
                invalidate(con)
            calls.append(True)
        return original(value)

    monkeypatch.setattr(app_module, 'stored_layout', revoke_while_decoding)
    response = client.get('/api/devices')
    assert calls == [True] and response.status_code == 401
    assert set(response.json) == {'error'} and snapshot(app) == before


@pytest.mark.parametrize('operation', ['approve', 'edit', 'revoke'])
def test_session_expiring_before_commit_rolls_back_the_whole_change(app, operation, monkeypatch):
    import member_sessions as sessions_module
    client, headers, _, _, _, method, path, payload = setup(app, operation)
    before = snapshot(app)
    with closing(sqlite3.connect(database(app))) as con:
        expires = con.execute("SELECT max(expires_at) FROM member_sessions WHERE owner='member1'").fetchone()[0]
    clock = {'now': time.time()}
    monkeypatch.setattr(sessions_module, 'time', SimpleNamespace(time=lambda: clock['now']))

    def after_audit(sql):
        if sql.startswith('UPDATE settings SET revision'):
            clock['now'] = expires + 1

    install_connection(app, path, method, after=after_audit)
    response = client.open(path, method=method, json=payload, headers=headers)
    assert clock['now'] == expires + 1
    assert response.status_code == 401, response.json
    assert snapshot(app) == before


@pytest.mark.parametrize('operation', ['approve', 'edit', 'revoke'])
def test_audit_failure_rolls_back_device_and_shared_revision(app, operation):
    client, headers, _, _, uid, method, path, payload = setup(app, operation)
    with sqlite3.connect(database(app)) as con:
        if operation == 'revoke':
            con.execute('INSERT INTO media_playback(device_id,anchor_at,revision,updated_at) VALUES(?,0,1,0)', (uid,))
        con.execute("CREATE TRIGGER reject_device_audit BEFORE INSERT ON audit "
                    "WHEN NEW.action IN ('pair_device','update_device','revoke_device') "
                    "BEGIN SELECT RAISE(ABORT,'synthetic audit failure'); END")
    before = snapshot(app)
    with pytest.raises(sqlite3.DatabaseError, match='synthetic audit failure'):
        client.open(path, method=method, json=payload, headers=headers)
    assert snapshot(app) == before


def test_concurrent_approval_consumes_code_once_and_cannot_change_winner(app):
    first, h1, tv, pair, uid, _, _, payload = setup(app, 'approve')
    second, h2 = member(app, 2)
    gate = Barrier(2)
    before = snapshot(app)

    def after_auth():
        if request.path == '/api/pair/approve':
            gate.wait(timeout=10)

    app.before_request_funcs[None].append(after_auth)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(client.post, '/api/pair/approve', json={**payload, 'name': name, 'focus': focus}, headers=headers)
                   for client, headers, name, focus in ((first, h1, 'First', 'member1'), (second, h2, 'Second', 'member2'))]
        responses = [future.result(timeout=15) for future in futures]
    app.before_request_funcs[None].remove(after_auth)
    assert sorted(response.status_code for response in responses) == [200, 400]
    assert tv.post('/api/pair/poll', json={'secret': pair['secret']}).json == {'approved': True}
    values = first.get('/api/devices').json
    assert len(values) == 1 and values[0]['id'] == uid and values[0]['revision'] == 1
    winner = next(i for i, result in enumerate(responses) if result.status_code == 200)
    assert (values[0]['name'], values[0]['focus']) == [('First', 'member1'), ('Second', 'member2')][winner]
    after = snapshot(app)
    assert sum(row[2] == 'pair_device' for row in after['audit']) == sum(row[2] == 'pair_device' for row in before['audit']) + 1
    assert first.post('/api/pair/approve', json=payload, headers=h1).status_code == 400
    assert snapshot(app) == after


def test_expired_code_cannot_be_approved_or_refresh_its_expiry(app):
    client, headers, tv, pair, uid, _, path, payload = setup(app, 'approve')
    with sqlite3.connect(database(app)) as con:
        con.execute('UPDATE devices SET expires=? WHERE id=?', (time.time() - 1, uid))
    before = snapshot(app)
    assert client.post(path, json=payload, headers=headers).status_code == 400
    assert tv.post('/api/pair/poll', json={'secret': pair['secret']}).status_code == 410
    assert snapshot(app) == before


def test_code_expiring_after_lookup_is_not_approved(app, monkeypatch):
    import app as app_module
    client, headers, _, _, uid, method, path, payload = setup(app, 'approve')
    before = snapshot(app)
    with closing(sqlite3.connect(database(app))) as con:
        expires = con.execute('SELECT expires FROM devices WHERE id=?', (uid,)).fetchone()[0]
    clock = {'now': time.time()}
    monkeypatch.setattr(app_module, 'time', SimpleNamespace(time=lambda: clock['now']))

    def after_lookup(sql):
        if sql.startswith('SELECT id FROM devices WHERE code='):
            clock['now'] = expires + 1

    install_connection(app, path, method, after=after_lookup)
    response = client.post(path, json=payload, headers=headers)
    assert clock['now'] == expires + 1
    assert response.status_code == 400 and snapshot(app) == before


@pytest.mark.parametrize('operation', ['approve', 'edit', 'revoke'])
def test_missing_csrf_and_foreign_origin_never_write(app, operation):
    client, headers, _, _, _, method, path, payload = setup(app, operation)
    before = snapshot(app)
    assert client.open(path, method=method, json=payload).status_code == 403
    assert client.open(path, method=method, json=payload, headers={**headers, 'Origin': 'https://invalid.example'}).status_code == 403
    assert client.open(path, method=method, data='{}', headers=headers).status_code == 415
    assert snapshot(app) == before


def test_tv_is_readonly_even_with_member_cookie_and_csrf(app):
    client, headers, tv, _, uid, _, _, _ = setup(app, 'edit')
    tv.set_cookie(app.config['SESSION_COOKIE_NAME'], client.get_cookie(app.config['SESSION_COOKIE_NAME']).value)
    headers = {**headers, 'X-Display-Mode': 'tv'}
    before = snapshot(app)
    for method, path, payload in [('GET', '/api/devices', None), ('POST', '/api/pair/approve', {}),
                                  ('PATCH', '/api/devices/' + uid, {'revision': 1}), ('DELETE', '/api/devices/' + uid, {})]:
        assert tv.open(path, method=method, json=payload, headers=headers).status_code == 403
    assert snapshot(app) == before


def test_cross_household_code_and_device_id_have_no_authority(app):
    client, headers, tv, pair, uid, _, _, payload = setup(app, 'approve')
    other, _, space = create_space(app)
    assert other.get(space['entry']).status_code == 303
    assert other.post('/api/login', json={'username': 'member1', 'password': 'second-home-password-one'}).status_code == 200
    oh = {'X-CSRF-Token': other.get('/api/me').json['csrf']}
    before = snapshot(app)
    assert other.post('/api/pair/approve', json=payload, headers=oh).status_code == 400
    assert other.get('/api/devices').json == []
    assert other.patch('/api/devices/' + uid, json={'revision': 1, 'name': 'No'}, headers=oh).status_code == 404
    assert other.delete('/api/devices/' + uid, json={}, headers=oh).json == {'ok': True}
    assert snapshot(app) == before
    assert client.post('/api/pair/approve', json=payload, headers=headers).status_code == 200
    assert tv.post('/api/pair/poll', json={'secret': pair['secret']}).json['approved']
    assert client.delete('/api/devices/' + uid, json={}, headers=headers).json == {'ok': True}
    assert client.delete('/api/devices/' + uid, json={}, headers=headers).json == {'ok': True}
    assert tv.get('/api/state').status_code == 401
    assert client.get('/api/devices').json == []
