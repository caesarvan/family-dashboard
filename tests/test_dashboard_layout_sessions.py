"""Homepage layouts recheck real credentials at SQLite transaction boundaries.

Only synthetic households and real sessions are used. A separate SQLite writer
revokes credentials; no authentication helper is stubbed to accept or reject.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import sqlite3
from threading import Event
import time
from types import SimpleNamespace

import pytest
from flask import g, request

from test_app import app, member
from test_dashboard_layout import layout
from test_device_sessions import database, install_connection, invalidate


PATH = '/api/dashboard-layout'


def snapshot(app):
    with closing(sqlite3.connect(database(app))) as con:
        return {table: con.execute('SELECT * FROM ' + table + ' ORDER BY 1').fetchall()
                for table in ('member_dashboard_layout', 'member_preferences',
                              'audit', 'settings', 'devices')}


def prepared(app, operation='save'):
    client, headers = member(app)
    saved = client.put(PATH, json=layout(hidden=['finance']), headers=headers)
    assert saved.status_code == 200 and saved.json['revision'] == 1
    payload = {'save': layout(1, hidden=['tasks']), 'noop': saved.json,
               'conflict': layout(0, hidden=['trips']), 'read': None}[operation]
    return client, headers, payload


@pytest.mark.parametrize('operation', ['read', 'save', 'noop', 'conflict'])
@pytest.mark.parametrize('kind', ['session', 'expired', 'auth_version'])
def test_layout_rejects_revocation_after_request_guard(app, operation, kind):
    client, headers, payload = prepared(app, operation)
    before, calls = snapshot(app), []
    method = 'GET' if operation == 'read' else 'PUT'

    def revoke_after_guard():
        if request.path == PATH and request.method == method:
            assert g.actor['id'] == 'member1'
            with sqlite3.connect(database(app)) as con:
                invalidate(con, kind)
            calls.append(kind)

    app.before_request_funcs[None].append(revoke_after_guard)
    response = client.open(PATH, method=method, json=payload, headers=headers)
    assert calls == [kind]
    assert response.status_code == 401, response.json
    assert set(response.json) == {'error'}
    assert snapshot(app) == before


@pytest.mark.parametrize('kind', ['session', 'expired', 'auth_version'])
def test_layout_waiting_for_real_writer_lock_observes_revocation(app, kind):
    client, headers, payload = prepared(app)
    before, entered = snapshot(app), Event()
    writer = sqlite3.connect(database(app), timeout=5, check_same_thread=False)

    def before_begin(sql):
        if sql == 'BEGIN IMMEDIATE':
            writer.execute('BEGIN IMMEDIATE')
            invalidate(writer, kind)
            entered.set()

    install_connection(app, PATH, 'PUT', before=before_begin)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(client.put, PATH, json=payload, headers=headers)
            try:
                assert entered.wait(10)
                # The authenticated request really waits behind a different
                # SQLite writer, rather than a stubbed authorization result.
                time.sleep(0.05)
                assert not pending.done()
            finally:
                writer.commit()
            response = pending.result(timeout=10)
        assert response.status_code == 401, response.json
        assert snapshot(app) == before
    finally:
        writer.close()


@pytest.mark.parametrize('kind', ['session', 'expired', 'auth_version'])
def test_layout_get_releases_snapshot_before_post_read_recheck(app, monkeypatch, kind):
    import dashboard_preferences as module
    client, _, _ = prepared(app, 'read')
    before, calls = snapshot(app), []
    original = module._stored

    def decode_and_revoke(value):
        with sqlite3.connect(database(app)) as con:
            invalidate(con, kind)
        calls.append(kind)
        return original(value)

    monkeypatch.setattr(module, '_stored', decode_and_revoke)
    response = client.get(PATH)
    assert calls == [kind]
    assert response.status_code == 401, response.json
    assert set(response.json) == {'error'} and snapshot(app) == before


@pytest.mark.parametrize('operation', ['save', 'noop'])
def test_layout_expiring_before_commit_rolls_back_including_audit(app, monkeypatch, operation):
    import member_sessions as sessions_module
    client, headers, payload = prepared(app, operation)
    before, calls = snapshot(app), []
    with closing(sqlite3.connect(database(app))) as con:
        expires = con.execute("SELECT max(expires_at) FROM member_sessions WHERE owner='member1'").fetchone()[0]
    clock = {'now': time.time()}
    monkeypatch.setattr(sessions_module, 'time', SimpleNamespace(time=lambda: clock['now']))

    def expire(sql):
        target = 'UPDATE settings SET revision' if operation == 'save' else 'SELECT data,revision FROM member_dashboard_layout'
        if sql.startswith(target):
            clock['now'] = expires + 1
            calls.append(True)

    install_connection(app, PATH, 'PUT', after=expire)
    response = client.put(PATH, json=payload, headers=headers)
    assert calls == [True] and response.status_code == 401, response.json
    assert snapshot(app) == before


@pytest.mark.parametrize('method', ['GET', 'PUT'])
@pytest.mark.parametrize('field', ['owner', 'auth_version', 'session', 'household'])
def test_layout_rechecks_captured_actor_and_session_context(app, method, field):
    client, headers, payload = prepared(app)
    before = snapshot(app)

    def mismatch_after_guard():
        if request.path != PATH or request.method != method:
            return
        if field == 'owner':
            g.actor['id'] = 'member2'
        elif field == 'auth_version':
            g.actor['auth_version'] += 1
        elif field == 'session':
            g.member_session['id'] = '0' * 32
        else:
            g.actor['householdId'] = 'foreign-household'

    app.before_request_funcs[None].append(mismatch_after_guard)
    response = client.open(PATH, method=method, json=payload if method == 'PUT' else None, headers=headers)
    assert response.status_code == 401, response.json
    assert set(response.json) == {'error'} and snapshot(app) == before


def test_layout_audit_failure_explicitly_rolls_back(app):
    client, headers, payload = prepared(app)
    with sqlite3.connect(database(app)) as con:
        con.execute("CREATE TRIGGER reject_layout_audit BEFORE INSERT ON audit "
                    "WHEN NEW.action='dashboard_layout_update' "
                    "BEGIN SELECT RAISE(ABORT,'synthetic layout audit failure'); END")
    before, rollbacks = snapshot(app), []
    install_connection(app, PATH, 'PUT')

    def observe_rollback():
        if request.path == PATH and request.method == 'PUT':
            original = g.db.rollback

            def rollback():
                rollbacks.append(True)
                return original()

            g.db.rollback = rollback

    app.before_request_funcs[None].append(observe_rollback)
    with pytest.raises(sqlite3.DatabaseError, match='synthetic layout audit failure'):
        client.put(PATH, json=payload, headers=headers)
    assert rollbacks == [True] and snapshot(app) == before


def test_layout_read_decode_failure_explicitly_releases_transaction(app, monkeypatch):
    import dashboard_preferences as module
    client, _, _ = prepared(app, 'read')
    before, rollbacks = snapshot(app), []
    install_connection(app, PATH, 'GET')

    def observe_rollback():
        if request.path == PATH and request.method == 'GET':
            original = g.db.rollback

            def rollback():
                rollbacks.append(True)
                return original()

            g.db.rollback = rollback

    def cannot_decode(value):
        raise ValueError('synthetic layout decode failure')

    app.before_request_funcs[None].append(observe_rollback)
    monkeypatch.setattr(module, '_stored', cannot_decode)
    with pytest.raises(ValueError, match='synthetic layout decode failure'):
        client.get(PATH)
    assert rollbacks == [True] and snapshot(app) == before
