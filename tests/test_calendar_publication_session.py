"""Real session revocation between request auth and calendar locks/remote reads.

Only synthetic local databases and the existing fake provider transport are used.
The injection changes a second SQLite connection, not the authentication result.
"""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import sqlite3
from threading import Event

import pytest

from test_calendar_publish import env, queue


PREFIX = '/api/calendar-publish'


def snapshot(app):
    with app.extensions['cloud_accounts'].db() as con:
        return {table: sorted(tuple(row) for row in con.execute(f'SELECT * FROM {table}'))
                for table in ('calendar_publications', 'entities', 'journey_workflows',
                              'journey_links', 'audit', 'settings')}


def revoker(app, kind='session'):
    calls = []

    def revoke():
        if calls:
            return
        with sqlite3.connect(app.extensions['cloud_accounts'].path, timeout=5) as con:
            if kind == 'session':
                result = con.execute("UPDATE member_sessions SET revoked_at=1 WHERE owner='member1' AND revoked_at IS NULL")
            else:
                result = con.execute("UPDATE users SET auth_version=auth_version+1 WHERE id='member1'")
            assert result.rowcount > 0
        calls.append(kind)

    return revoke, calls


def at_boundary(monkeypatch, engine, boundary, revoke):
    if boundary == 'account_lock':
        original = engine.lock

        @contextmanager
        def locked(account_id):
            with original(account_id):
                revoke()
                yield

        monkeypatch.setattr(engine, 'lock', locked)
    else:
        original = engine.db

        class BeforeBegin:
            def __init__(self, connection):
                self.connection = connection

            def __getattr__(self, name):
                return getattr(self.connection, name)

            def execute(self, sql, *args):
                if sql == 'BEGIN IMMEDIATE':
                    revoke()
                return self.connection.execute(sql, *args)

        @contextmanager
        def database():
            with original() as con:
                yield BeforeBegin(con)

        monkeypatch.setattr(engine, 'db', database)


def prepare(env, operation):
    app, client, headers, remote, _ = env
    if operation in {'confirm', 'reconfirm'}:
        if operation == 'reconfirm':
            queue(env)
        payload = {'journeyId': 'journey-1', 'sourceId': 'source-1'}
        preview = client.post(PREFIX + '/preview', json=payload, headers=headers)
        assert preview.status_code == 200, preview.json
        return PREFIX + '/confirm', {**payload, 'previewToken': preview.json['previewToken']}
    rid = queue(env)
    if operation.startswith(('conflict-', 'review-')):
        app.extensions['calendar_publish'].process(rid)
    with app.extensions['cloud_accounts'].db() as con:
        status = ('conflict' if operation.startswith('conflict-') else
                  'needs_review' if operation.startswith('review-') else
                  'paused' if operation == 'resume' else 'retry')
        con.execute('UPDATE calendar_publications SET status=?,review_required=? WHERE id=?',
                    (status, int(operation.startswith('review-')), rid))
    path = PREFIX + '/publications/' + rid + '/' + operation
    if operation in {'conflict-confirm', 'review-confirm'}:
        preview = client.post(path.replace('-confirm', '-preview'), json={}, headers=headers)
        assert preview.status_code == 200, preview.json
        return path, {'previewToken': preview.json['previewToken']}
    return path, {}


@pytest.mark.parametrize('operation', ['confirm', 'reconfirm', 'retry', 'pause', 'resume', 'conflict-confirm', 'review-confirm'])
@pytest.mark.parametrize('boundary', ['account_lock', 'transaction_begin'])
def test_revoked_at_write_boundary_has_no_effect(env, monkeypatch, operation, boundary):
    app, client, headers, remote, _ = env
    path, payload = prepare(env, operation)
    before = snapshot(app)
    remote.calls.clear()
    revoke, revoked = revoker(app)
    with monkeypatch.context() as patch:
        at_boundary(patch, app.extensions['cloud_accounts'], boundary, revoke)
        response = client.post(path, json=payload, headers=headers)
    assert revoked == ['session']
    assert response.status_code == 401, response.json
    assert snapshot(app) == before
    assert not remote.calls
    assert client.get('/api/me').json['user'] is None


@pytest.mark.parametrize('operation', ['confirm', 'resume', 'review-confirm'])
def test_auth_version_change_blocks_queue_mutation(env, monkeypatch, operation):
    app, client, headers, remote, _ = env
    path, payload = prepare(env, operation)
    before = snapshot(app)
    remote.calls.clear()
    revoke, revoked = revoker(app, 'auth_version')
    with monkeypatch.context() as patch:
        at_boundary(patch, app.extensions['cloud_accounts'], 'transaction_begin', revoke)
        response = client.post(path, json=payload, headers=headers)
    assert revoked == ['auth_version']
    assert response.status_code == 401, response.json
    assert snapshot(app) == before
    assert not remote.calls


@pytest.mark.parametrize('operation', ['conflict-preview', 'review-preview'])
@pytest.mark.parametrize('boundary', ['account_lock', 'provider_ready', 'remote_response'])
def test_remote_preview_never_returns_after_revocation(env, monkeypatch, operation, boundary):
    app, client, headers, remote, _ = env
    path, payload = prepare(env, operation)
    before = snapshot(app)
    remote.calls.clear()
    revoke, revoked = revoker(app)
    engine = app.extensions['cloud_accounts']
    with monkeypatch.context() as patch:
        if boundary == 'account_lock':
            at_boundary(patch, engine, boundary, revoke)
        elif boundary == 'provider_ready':
            original = engine.active_provider

            def ready(*args, **kwargs):
                adapter = original(*args, **kwargs)
                revoke()
                return adapter

            patch.setattr(engine, 'active_provider', ready)
        else:
            def transport(*args, **kwargs):
                result = remote.transport(*args, **kwargs)
                revoke()
                return result

            patch.setitem(app.config, 'CLOUD_TRANSPORT', transport)
        response = client.post(path, json=payload, headers=headers)
    assert revoked == ['session']
    assert response.status_code == 401, response.json
    assert set(response.json) == {'error'}
    assert snapshot(app) == before
    if boundary == 'remote_response':
        assert remote.calls and all(call[0] == 'GET' for call in remote.calls)
    else:
        assert not remote.calls


@pytest.mark.parametrize('operation', ['state', 'preview', 'authorize'])
def test_late_read_or_authorization_url_is_hidden(env, monkeypatch, operation):
    app, client, headers, remote, _ = env
    engine = app.extensions['cloud_accounts']
    target = engine if operation == 'authorize' else app.extensions['calendar_publish']
    name = 'authorize' if operation == 'authorize' else 'state'
    original = getattr(target, name)
    revoke, revoked = revoker(app)

    def finish_then_revoke(*args, **kwargs):
        result = original(*args, **kwargs)
        revoke()
        return result

    monkeypatch.setattr(target, name, finish_then_revoke)
    if operation == 'state':
        response = client.get(PREFIX + '/journeys/journey-1')
    elif operation == 'preview':
        response = client.post(PREFIX + '/preview', json={'journeyId': 'journey-1', 'sourceId': 'source-1'}, headers=headers)
    else:
        response = client.post(PREFIX + '/authorize', json={'accountId': 'account-1'}, headers=headers)
    assert revoked == ['session']
    assert response.status_code == 401, response.json
    assert set(response.json) == {'error'}
    assert not remote.calls


def test_session_logout_does_not_revoke_previous_durable_consent(env):
    app, client, headers, remote, _ = env
    rid = queue(env)
    revoke, _ = revoker(app)
    revoke()
    app.extensions['calendar_publish'].process(rid)
    assert remote.created == 1
    with app.extensions['cloud_accounts'].db() as con:
        assert con.execute('SELECT status FROM calendar_publications WHERE id=?', (rid,)).fetchone()[0] == 'published'
    assert client.get(PREFIX + '/journeys/journey-1').status_code == 401


def test_revocation_committed_while_confirm_waits_for_sqlite_writer(env, monkeypatch):
    app, client, headers, remote, _ = env
    path, payload = prepare(env, 'confirm')
    before = snapshot(app)
    engine = app.extensions['cloud_accounts']
    original_lock, original_db = engine.lock, engine.db
    reached_lock, continue_request, beginning = Event(), Event(), Event()

    @contextmanager
    def locked(account_id):
        with original_lock(account_id):
            reached_lock.set()
            assert continue_request.wait(5)
            yield

    class BeginSignal:
        def __init__(self, con):
            self.con = con

        def __getattr__(self, name):
            return getattr(self.con, name)

        def execute(self, sql, *args):
            if sql == 'BEGIN IMMEDIATE':
                beginning.set()
            return self.con.execute(sql, *args)

    @contextmanager
    def database():
        with original_db() as con:
            yield BeginSignal(con)

    with monkeypatch.context() as patch, ThreadPoolExecutor(max_workers=1) as pool:
        patch.setattr(engine, 'lock', locked)
        patch.setattr(engine, 'db', database)
        future = pool.submit(client.post, path, json=payload, headers=headers)
        try:
            assert reached_lock.wait(5)  # The HTTP member guard has already succeeded.
            with sqlite3.connect(engine.path, timeout=5) as other:
                other.execute('BEGIN IMMEDIATE')
                continue_request.set()
                assert beginning.wait(5)
                assert not future.done()  # Request cannot own the SQLite writer yet.
                changed = other.execute("UPDATE member_sessions SET revoked_at=1 WHERE owner='member1' AND revoked_at IS NULL")
                assert changed.rowcount == 1
            response = future.result(timeout=10)
        finally:
            continue_request.set()
    assert response.status_code == 401, response.json
    assert snapshot(app) == before
    assert not remote.calls


def test_revocation_after_commit_hides_response_but_preserves_durable_queue(env, monkeypatch):
    app, client, headers, remote, _ = env
    path, payload = prepare(env, 'confirm')
    engine = app.extensions['cloud_accounts']
    original = engine.db
    revoke, revoked = revoker(app)

    class WriteMarker:
        def __init__(self, con):
            self.con, self.writing = con, False

        def __getattr__(self, name):
            return getattr(self.con, name)

        def execute(self, sql, *args):
            self.writing |= sql == 'BEGIN IMMEDIATE'
            return self.con.execute(sql, *args)

    @contextmanager
    def database():
        with original() as con:
            marker = WriteMarker(con)
            yield marker
        if marker.writing:
            revoke()  # The real connection above has successfully committed.

    with monkeypatch.context() as patch:
        patch.setattr(engine, 'db', database)
        response = client.post(path, json=payload, headers=headers)
    assert revoked == ['session']
    assert response.status_code == 401, response.json
    with original() as con:
        ids = [row[0] for row in con.execute('SELECT id FROM calendar_publications')]
    assert len(ids) == 1
    assert not remote.calls
    assert client.post('/api/login', json={'username': 'member1', 'password': 'testing-password-one'}).status_code == 200
    new_headers = {'X-CSRF-Token': client.get('/api/me').json['csrf']}
    state = client.get(PREFIX + '/journeys/journey-1')
    assert [row['id'] for row in state.json['publications']] == ids
    retried = client.post(path, json=payload, headers=new_headers)
    assert retried.status_code == 200, retried.json
    assert retried.json['publicationIds'] == ids
    with original() as con:
        assert con.execute('SELECT count(*) FROM calendar_publications').fetchone()[0] == 1
