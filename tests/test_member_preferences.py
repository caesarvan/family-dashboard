"""Real Flask/SQLite appearance CAS, projection and credential boundaries.

All data is synthetic. Session outcomes are never mocked; timing hooks mutate
real credential rows or advance the clock beyond a stored expiry.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import sqlite3
from threading import Barrier, Event
import time
from types import SimpleNamespace

import pytest
from flask import g, request

from test_app import app, member
from test_device_sessions import database, install_connection, invalidate
from test_household_spaces import create_space


PATH = '/api/preferences'
MAX_REVISION = 9007199254740991
DEFAULTS = {'theme': 'forest', 'density': 'comfortable', 'homeView': 'today',
            'colorMode': 'light', 'revision': 0}


def save(client, headers, revision=0, **changes):
    return client.put(PATH, json={'revision': revision, 'changes': changes}, headers=headers)


def snapshot(app):
    with closing(sqlite3.connect(database(app))) as con:
        return {table: con.execute('SELECT * FROM ' + table + ' ORDER BY 1').fetchall()
                for table in ('member_preferences', 'member_dashboard_layout', 'audit', 'settings', 'devices')}


def seed(app, value):
    with closing(sqlite3.connect(database(app))) as con:
        con.execute('INSERT INTO member_preferences VALUES(?,?)', ('member1', json.dumps(value)))
        con.commit()


def test_defaults_noop_and_partial_merge_preserve_other_settings(app):
    client, headers = member(app)
    before = snapshot(app)
    assert client.get(PATH).json == DEFAULTS
    assert save(client, headers, colorMode='light').json == DEFAULTS
    assert snapshot(app) == before  # no row, audit or global revision for a no-op
    first = save(client, headers, theme='ocean', homeView='around')
    assert first.status_code == 200 and first.json == {**DEFAULTS, 'theme': 'ocean', 'homeView': 'around', 'revision': 1}
    second = save(client, headers, 1, density='compact', colorMode='dark')
    assert second.status_code == 200
    assert second.json == {**first.json, 'density': 'compact', 'colorMode': 'dark', 'revision': 2}
    saved = snapshot(app)
    assert save(client, headers, 2, colorMode='dark').json == second.json
    assert snapshot(app) == saved
    assert save(client, headers, 1, colorMode='dark').status_code == 409  # stale no-op is still stale
    assert snapshot(app) == saved
    assert saved['devices'] == before['devices'] and saved['member_dashboard_layout'] == before['member_dashboard_layout']
    assert sum(row[2] == 'preferences_update' for row in saved['audit']) == 2


def test_legacy_row_future_fields_projection_and_noop_byte_preservation(app):
    client, headers = member(app)
    legacy = {'theme': 'light', 'density': 'compact', 'homeView': 'week',
              'futurePrivate': {'opaque': ['PRIVATE-FUTURE-VALUE', 4]}}
    seed(app, legacy)
    before = snapshot(app)
    expected = {**DEFAULTS, 'theme': 'light', 'density': 'compact', 'homeView': 'week'}
    assert client.get(PATH).json == expected
    assert save(client, headers, colorMode='light').json == expected
    assert snapshot(app) == before
    result = save(client, headers, colorMode='dark')
    assert result.status_code == 200 and result.json == {**expected, 'colorMode': 'dark', 'revision': 1}
    with closing(sqlite3.connect(database(app))) as con:
        stored = json.loads(con.execute('SELECT data FROM member_preferences WHERE owner=?', ('member1',)).fetchone()[0])
    assert stored == {**legacy, 'colorMode': 'dark', 'revision': 1}
    assert 'PRIVATE-FUTURE-VALUE' not in client.get(PATH).get_data(as_text=True)
    assert 'PRIVATE-FUTURE-VALUE' not in client.get('/api/state').get_data(as_text=True)


@pytest.mark.parametrize('payload', [
    {'theme': 'light', 'density': 'compact', 'homeView': 'week'},
    {'changes': {'colorMode': 'dark'}},
    {'revision': True, 'changes': {'colorMode': 'dark'}},
    {'revision': 0.0, 'changes': {'colorMode': 'dark'}},
    {'revision': '0', 'changes': {'colorMode': 'dark'}},
    {'revision': -1, 'changes': {'colorMode': 'dark'}},
    {'revision': MAX_REVISION + 1, 'changes': {'colorMode': 'dark'}},
    {'revision': 0, 'changes': {}},
    {'revision': 0, 'changes': []},
    {'revision': 0, 'changes': {'owner': 'member2'}},
    {'revision': 0, 'changes': {'revision': 1}},
    {'revision': 0, 'changes': {'colorMode': 'system'}},
    {'revision': 0, 'changes': {'theme': None}},
    {'revision': 0, 'changes': {'density': {'bad': True}}},
    {'revision': 0, 'changes': {'homeView': False}},
    {'revision': 0, 'changes': {'colorMode': 'dark'}, 'owner': 'member2'},
])
def test_invalid_and_old_payloads_never_write(app, payload):
    client, headers = member(app)
    before = snapshot(app)
    response = client.put(PATH, json=payload, headers=headers)
    assert response.status_code == 400, response.json
    if 'revision' not in payload:
        assert '刷新' in response.json['error']
    assert snapshot(app) == before


def test_safe_integer_limit_allows_noop_but_refuses_increment(app):
    client, headers = member(app)
    seed(app, {**DEFAULTS, 'revision': MAX_REVISION - 1})
    assert save(client, headers, MAX_REVISION - 1, colorMode='dark').json['revision'] == MAX_REVISION
    before = snapshot(app)
    assert save(client, headers, MAX_REVISION, colorMode='dark').status_code == 200
    assert save(client, headers, MAX_REVISION, colorMode='light').status_code == 409
    assert client.get(PATH).json == {**DEFAULTS, 'colorMode': 'dark', 'revision': MAX_REVISION}
    assert snapshot(app) == before


@pytest.mark.parametrize('stored', [{'revision': True}, {'revision': 1.0}, {'revision': -1},
                                   {'revision': MAX_REVISION + 1}, {'colorMode': 'system'}, []])
def test_corrupt_stored_data_is_not_reset_or_exposed(app, stored):
    client, headers = member(app)
    seed(app, stored)
    before = snapshot(app)
    assert client.get(PATH).status_code == 503
    assert save(client, headers, colorMode='dark').status_code == 503
    assert snapshot(app) == before


def test_member_household_and_real_tv_boundaries(app):
    first, fh = member(app)
    second, sh = member(app, 2)
    assert save(first, fh, colorMode='dark').status_code == 200
    assert second.get(PATH + '?owner=member1').json == DEFAULTS
    assert save(second, sh, density='compact').status_code == 200
    child, _, entry = create_space(app, 'preferences-family')
    assert child.get(entry['entry']).status_code == 303
    assert child.post('/api/login', json={'username': 'member1', 'password': 'second-home-password-one'}).status_code == 200
    ch = {'X-CSRF-Token': child.get('/api/me').json['csrf']}
    assert child.get(PATH).json == DEFAULTS
    assert save(child, ch, homeView='week').status_code == 200
    assert first.get(PATH).json == {**DEFAULTS, 'colorMode': 'dark', 'revision': 1}
    assert second.get(PATH).json == {**DEFAULTS, 'density': 'compact', 'revision': 1}
    child.set_cookie('session', first.get_cookie('session').value)
    assert child.get(PATH).status_code == 401
    assert app.test_client().get(PATH).status_code == 401
    assert first.put(PATH, json={'revision': 1, 'changes': {'density': 'compact'}}).status_code == 403
    assert save(first, {**fh, 'Origin': 'https://foreign.example'}, 1, density='compact').status_code == 403
    tv = app.test_client()
    pair = tv.post('/api/pair/start', json={}).json
    assert first.post('/api/pair/approve', json={'code': pair['code'], 'name': 'Synthetic TV'}, headers=fh).status_code == 200
    assert tv.post('/api/pair/poll', json={'secret': pair['secret']}).json['approved']
    assert tv.get(PATH).status_code == 403
    assert save(tv, fh, colorMode='dark').status_code == 403


def test_two_real_writers_have_one_cas_winner(app):
    first, fh = member(app)
    second, sh = member(app)
    gate = Barrier(2)

    def after_guard():
        if request.path == PATH and request.method == 'PUT':
            gate.wait(timeout=10)

    app.before_request_funcs[None].append(after_guard)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(save, c, h, 0, colorMode=mode, density=density)
                   for c, h, mode, density in [(first, fh, 'dark', 'comfortable'), (second, sh, 'light', 'compact')]]
        results = [f.result(timeout=15) for f in futures]
    assert sorted(r.status_code for r in results) == [200, 409]
    winner = next(r.json for r in results if r.status_code == 200)
    assert first.get(PATH).json == winner and winner['revision'] == 1
    assert sum(row[2] == 'preferences_update' for row in snapshot(app)['audit']) == 1


@pytest.mark.parametrize('method', ['GET', 'PUT'])
@pytest.mark.parametrize('kind', ['session', 'expired', 'auth_version'])
def test_revoke_after_request_guard_cannot_read_or_write(app, method, kind):
    client, headers = member(app)
    before = snapshot(app)

    def revoke():
        if request.path == PATH and request.method == method:
            with closing(sqlite3.connect(database(app))) as con:
                invalidate(con, kind)
                con.commit()

    app.before_request_funcs[None].append(revoke)
    response = client.open(PATH, method=method, json={'revision': 0, 'changes': {'colorMode': 'dark'}}, headers=headers)
    assert response.status_code == 401 and set(response.json) == {'error'}
    assert snapshot(app) == before


def test_waiting_for_sqlite_write_lock_observes_actual_revocation(app):
    client, headers = member(app)
    before, entered = snapshot(app), Event()
    with closing(sqlite3.connect(database(app), timeout=5, check_same_thread=False)) as writer:
        def lock_and_revoke(sql):
            if sql == 'BEGIN IMMEDIATE':
                writer.execute('BEGIN IMMEDIATE')
                invalidate(writer)
                entered.set()

        install_connection(app, PATH, 'PUT', before=lock_and_revoke)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(save, client, headers, 0, colorMode='dark')
            try:
                assert entered.wait(10)
                time.sleep(0.05)
                assert not pending.done()
            finally:
                writer.commit()
            assert pending.result(timeout=10).status_code == 401
    assert snapshot(app) == before


def test_get_releases_snapshot_after_decode_before_fresh_session_check(app, monkeypatch):
    import household_spaces as module
    client, headers = member(app)
    assert save(client, headers, colorMode='dark').status_code == 200
    before, calls = snapshot(app), []
    original = module._stored_preferences

    def decode_then_revoke(raw, problem):
        result = original(raw, problem)
        with closing(sqlite3.connect(database(app))) as con:
            invalidate(con)
            con.commit()
        calls.append(True)
        return result

    monkeypatch.setattr(module, '_stored_preferences', decode_then_revoke)
    response = client.get(PATH)
    assert calls == [True] and response.status_code == 401 and set(response.json) == {'error'}
    assert snapshot(app) == before


@pytest.mark.parametrize('noop', [False, True])
def test_expiry_before_commit_rolls_back_preferences_audit_and_global_revision(app, monkeypatch, noop):
    import member_sessions as sessions
    client, headers = member(app)
    before, calls = snapshot(app), []
    with closing(sqlite3.connect(database(app))) as con:
        expiry = con.execute("SELECT max(expires_at) FROM member_sessions WHERE owner='member1'").fetchone()[0]
    clock = {'now': time.time()}
    monkeypatch.setattr(sessions, 'time', SimpleNamespace(time=lambda: clock['now']))

    def expire(sql):
        target = 'SELECT data FROM member_preferences' if noop else 'UPDATE settings SET revision'
        if sql.startswith(target):
            clock['now'] = expiry + 1
            calls.append(True)

    install_connection(app, PATH, 'PUT', after=expire)
    response = save(client, headers, colorMode='light' if noop else 'dark')
    assert calls == [True] and response.status_code == 401
    assert snapshot(app) == before


def test_audit_failure_explicitly_rolls_back(app):
    client, headers = member(app)
    with closing(sqlite3.connect(database(app))) as con:
        con.execute("CREATE TRIGGER reject_preferences_audit BEFORE INSERT ON audit "
                    "WHEN NEW.action='preferences_update' BEGIN SELECT RAISE(ABORT,'synthetic preference audit failure'); END")
        con.commit()
    before, rollbacks = snapshot(app), []
    install_connection(app, PATH, 'PUT')

    def observe():
        if request.path == PATH and request.method == 'PUT':
            original = g.db.rollback
            def rollback():
                rollbacks.append(True)
                return original()
            g.db.rollback = rollback

    app.before_request_funcs[None].append(observe)
    with pytest.raises(sqlite3.DatabaseError, match='synthetic preference audit failure'):
        save(client, headers, colorMode='dark')
    assert rollbacks == [True] and snapshot(app) == before
