"""Real local sessions/SQLite at suggestion read and confirmation boundaries."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
import json
import sqlite3
from threading import Event
import time
from types import SimpleNamespace

from flask import g, request
import pytest
from werkzeug.datastructures import ImmutableMultiDict

from test_household_media import env, offline
from test_media_journey_suggestions import photo, journey, suggestions, payload, metadata
from test_device_sessions import invalidate, ConnectionProxy
from test_journey_documents import login
from test_member_sessions import legacy


def database(env):
    return env[1].sessions.path


def snapshot(env):
    with closing(sqlite3.connect(database(env))) as con:
        return {name: con.execute('SELECT * FROM ' + name + ' ORDER BY rowid').fetchall()
                for name in ('media_items', 'media_imports', 'media_tv_grants',
                             'journey_workflows', 'entities', 'audit', 'settings')}


def prepared(env, operation):
    client, headers, item, _ = photo(env)
    journey(client, headers)
    value = payload(suggestions(client, item))
    endpoint = '/api/media/items/' + item['id']
    if operation == 'read':
        return client, headers, endpoint + '/journey-suggestions', 'GET', None
    return client, headers, endpoint, 'PATCH', value


@pytest.mark.parametrize('kind', ['session', 'expired', 'auth_version'])
@pytest.mark.parametrize('unknown', [False, True])
def test_read_releases_snapshot_before_revocation_check(env, monkeypatch, kind, unknown):
    client, headers, endpoint, method, value = prepared(env, 'read')
    if unknown:
        metadata(env, endpoint.split('/')[-2], remove=True)
    before, observed = snapshot(env), []
    original = env[1]._metadata

    def revoke(row):
        result = original(row)
        with closing(sqlite3.connect(database(env))) as writer:
            invalidate(writer, kind)
            writer.commit()
        observed.append(True)
        return result

    monkeypatch.setattr(env[1], '_metadata', revoke)
    response = client.open(endpoint, method=method, headers=headers, json=value)
    assert observed == [True]
    assert response.status_code == 401, response.json
    assert 'suggestions' not in response.json
    assert snapshot(env) == before


def test_confirmation_expiry_after_audit_rolls_back(env, monkeypatch):
    import member_sessions
    client, headers, endpoint, method, value = prepared(env, 'confirm')
    before, observed = snapshot(env), []
    with closing(sqlite3.connect(database(env))) as con:
        expiry = con.execute('SELECT max(expires_at) FROM member_sessions').fetchone()[0]
    original = env[1]._audit

    def expire(con, *args):
        original(con, *args)
        monkeypatch.setattr(member_sessions, 'time', SimpleNamespace(time=lambda: expiry + 1))
        observed.append(True)

    monkeypatch.setattr(env[1], '_audit', expire)
    response = client.open(endpoint, method=method, headers=headers, json=value)
    assert observed == [True]
    assert response.status_code == 401, response.json
    assert snapshot(env) == before


@pytest.mark.parametrize('kind', ['session', 'expired', 'auth_version'])
def test_confirmation_waiting_for_writer_observes_committed_revocation(env, monkeypatch, kind):
    client, headers, endpoint, method, value = prepared(env, 'confirm')
    before, waiting, armed = snapshot(env), Event(), []
    original = env[1].sessions.db

    def arm():
        if request.path == endpoint and request.method == method:
            armed.append(True)

    env[0].before_request_funcs[None].append(arm)
    with closing(sqlite3.connect(database(env), timeout=10, check_same_thread=False)) as writer:
        def before_begin(sql):
            if armed and sql == 'BEGIN IMMEDIATE':
                writer.execute('BEGIN IMMEDIATE')
                invalidate(writer, kind)
                waiting.set()

        @contextmanager
        def connections():
            with original() as con:
                yield ConnectionProxy(con, before=before_begin)

        monkeypatch.setattr(env[1].sessions, 'db', connections)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(client.open, endpoint, method=method, headers=headers, json=value)
            try:
                assert waiting.wait(10)
                time.sleep(0.05)
                assert not pending.done()
            finally:
                # Only the main thread commits, after the other connection waits.
                writer.commit()
            response = pending.result(timeout=10)
    assert armed == [True] and response.status_code == 401
    assert snapshot(env) == before


@pytest.mark.parametrize('operation', ['read', 'confirm'])
@pytest.mark.parametrize('number', [1, 2])
def test_mid_request_valid_cookie_cannot_replace_captured_session(env, monkeypatch, operation, number):
    client, headers, endpoint, method, value = prepared(env, operation)
    replacement, _ = login(env[0], number)
    raw = replacement.get_cookie('session').value
    assert raw != client.get_cookie('session').value
    before, observed = snapshot(env), []

    def swap():
        cookies = dict(request.cookies)
        cookies['session'] = raw
        request.__dict__['cookies'] = ImmutableMultiDict(cookies)
        observed.append(True)

    if operation == 'read':
        original = env[1]._metadata

        def during_read(row):
            result = original(row)
            swap()
            return result

        monkeypatch.setattr(env[1], '_metadata', during_read)
    else:
        original = env[1]._audit

        def after_write(con, *args):
            original(con, *args)
            swap()

        monkeypatch.setattr(env[1], '_audit', after_write)
    response = client.open(endpoint, method=method, headers=headers, json=value)
    assert observed == [True] and response.status_code == 401, response.json
    assert snapshot(env) == before


@pytest.mark.parametrize('operation', ['read', 'confirm'])
def test_legacy_cookie_keeps_read_and_confirm_compatible(env, monkeypatch, operation):
    _, _, endpoint, method, value = prepared(env, operation)
    client, raw, signed = legacy(env[0], env[1].sessions, monkeypatch)
    headers = {'X-CSRF-Token': signed['csrf'], 'Origin': 'http://localhost'}
    before = snapshot(env)
    response = client.open(endpoint, method=method, headers=headers, json=value)
    assert response.status_code == 200, response.json
    assert client.get_cookie('session').value == raw
    if operation == 'read':
        assert response.json['suggestions'] and snapshot(env) == before
    else:
        assert response.json['item']['journey']['id'] == value['journeyId']
        assert response.json['item']['revision'] == value['revision'] + 1
    # A following request also starts a new transaction successfully.
    assert client.get(endpoint if operation == 'read' else endpoint + '/journey-suggestions').status_code == 200


def test_legacy_read_does_not_keep_resolution_write_lock(env, monkeypatch):
    _, _, endpoint, method, value = prepared(env, 'read')
    client, _, signed = legacy(env[0], env[1].sessions, monkeypatch)
    headers = {'X-CSRF-Token': signed['csrf'], 'Origin': 'http://localhost'}
    before, original, observed = snapshot(env), env[1]._metadata, []

    def revoke(row):
        result = original(row)
        with closing(sqlite3.connect(database(env), timeout=1)) as con:
            invalidate(con)
            con.commit()
        observed.append(True)
        return result

    monkeypatch.setattr(env[1], '_metadata', revoke)
    response = client.open(endpoint, method=method, headers=headers, json=value)
    assert observed == [True] and response.status_code == 401
    assert snapshot(env) == before


def test_read_is_one_domain_snapshot_and_original_versions_still_conflict(env, monkeypatch):
    client, headers, item, _ = photo(env)
    trip = journey(client, headers, title='Synthetic original title')
    original, changed = env[1]._metadata, []

    def change_trip(row):
        result = original(row)
        with closing(sqlite3.connect(database(env))) as writer:
            data = json.loads(writer.execute('SELECT data FROM entities WHERE id=?', (trip['tripId'],)).fetchone()[0])
            data['title'] = 'Synthetic newer title'
            writer.execute('UPDATE entities SET data=?,revision=revision+1 WHERE id=?',
                           (json.dumps(data), trip['tripId']))
            writer.commit()
        changed.append(True)
        return result

    with monkeypatch.context() as local:
        local.setattr(env[1], '_metadata', change_trip)
        result = suggestions(client, item)
    assert changed == [True]
    assert result['suggestions'][0]['title'] == 'Synthetic original title'
    assert result['suggestions'][0]['tripRevision'] == trip['trip']['revision']
    before = snapshot(env)
    response = client.patch('/api/media/items/' + item['id'], headers=headers, json=payload(result))
    assert response.status_code == 409 and response.json['code'] == 'conflict'
    assert snapshot(env) == before


def test_exception_after_audit_rolls_back_photo_grants_and_audit(env, monkeypatch):
    client, headers, endpoint, method, value = prepared(env, 'confirm')
    before, original = snapshot(env), env[1]._audit

    def fail(con, *args):
        original(con, *args)
        raise RuntimeError('Synthetic exception after actual audit')

    monkeypatch.setattr(env[1], '_audit', fail)
    with pytest.raises(RuntimeError, match='Synthetic exception'):
        client.open(endpoint, method=method, headers=headers, json=value)
    assert snapshot(env) == before


@pytest.mark.parametrize('operation', ['read', 'confirm'])
def test_changed_actual_session_id_after_request_guard_is_rejected(env, operation):
    client, headers, endpoint, method, value = prepared(env, operation)
    before, observed = snapshot(env), []

    def replace_session():
        if request.path == endpoint and request.method == method:
            original = g.member_session['id']
            with closing(sqlite3.connect(database(env))) as writer:
                assert writer.execute('UPDATE member_sessions SET id=? WHERE id=?',
                                      ('f' * 32, original)).rowcount == 1
                writer.commit()
            observed.append(original)

    env[0].before_request_funcs[None].append(replace_session)
    response = client.open(endpoint, method=method, headers=headers, json=value)
    assert len(observed) == 1
    assert response.status_code == 401, response.json
    assert snapshot(env) == before
