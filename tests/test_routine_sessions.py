"""Real SQLite/session boundaries and durable routine recovery; synthetic only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import re
import sqlite3
from threading import Event
import time
from types import SimpleNamespace

from flask import g, request
from itsdangerous.timed import TimestampSigner
import pytest

from test_app import app, member
from test_device_sessions import database, install_connection, invalidate
from test_household_routines import (PREFIX, confirm, context, create,
                                    isolated_clock_and_network, make_payload, operation, plan, preview)
from test_household_spaces import create_space
from test_member_sessions import legacy


def snapshot(app):
    with closing(sqlite3.connect(database(app))) as con:
        return {table: con.execute('SELECT * FROM ' + table + ' ORDER BY rowid').fetchall()
                for table in ('household_routines', 'routine_occurrences', 'routine_receipts',
                              'entities', 'audit', 'settings')}


def receipt_path(pending):
    return PREFIX + '/operations/' + pending.json['operationKey']


@pytest.fixture
def token_clock(monkeypatch):
    clock = {'now': int(time.time())}
    monkeypatch.setattr(TimestampSigner, 'get_timestamp', lambda _: clock['now'])
    return clock


def test_receipt_read_is_owner_only_stable_whitelist_and_not_current_plan(app, token_clock):
    client, headers = member(app)
    before = snapshot(app)
    pending = preview(client, headers, make_payload('shopping', budget=None))
    key = pending.json['operationKey']
    assert re.fullmatch('[a-f0-9]{64}', key)
    assert snapshot(app) == before
    absent = client.get(receipt_path(pending))
    assert absent.status_code == 404 and absent.json['code'] == 'routine_receipt_not_found'
    saved = confirm(client, headers, pending).json
    assert saved['operationKey'] == key
    result = client.get(receipt_path(pending))
    assert result.status_code == 200 and result.headers['Cache-Control'] == 'no-store'
    assert result.json == dict(found=True, operationKey=key, operation='create', planId=saved['plan']['id'],
                               revision=saved['plan']['revision'], generated=saved['generated'],
                               createdAt=saved['plan']['createdAt'])
    partner, partner_headers = member(app, 2)
    hidden = partner.get(receipt_path(pending))
    assert hidden.status_code == 404 and hidden.json == absent.json
    # The plan itself is shared and independently manageable by either member.
    rule = plan(partner, saved['plan']['id'])
    assert confirm(partner, partner_headers, operation(partner, partner_headers, rule, 'archive')).status_code == 200
    assert client.delete('/api/items/shopping/' + saved['generated']['id'],
                         json={'revision': 1}, headers=headers).status_code == 200
    token_clock['now'] += 601
    state = snapshot(app)
    historical = client.get(receipt_path(pending))
    replay = confirm(client, headers, pending)
    assert historical.json == result.json and replay.status_code == 200
    assert replay.json == {**saved, 'replayed': True}
    assert snapshot(app) == state
    assert saved['generated']['id'] not in {row['id'] for row in client.get('/api/state').json['shopping']}
    assert plan(client, saved['plan']['id'])['state'] == 'archived'


def test_expired_unapplied_and_fresh_explicit_preview_have_distinct_keys(app, token_clock):
    client, headers = member(app)
    pending = preview(client, headers, make_payload())
    before = snapshot(app)
    token_clock['now'] += 601
    for _ in range(2):
        response = confirm(client, headers, pending)
        assert response.status_code == 410
        assert set(response.json) == {'error', 'code'} and response.json['code'] == 'preview_expired_unapplied'
    assert snapshot(app) == before
    assert client.get(receipt_path(pending)).status_code == 404
    fresh = preview(client, headers, make_payload())
    assert fresh.json['operationKey'] != pending.json['operationKey']
    assert confirm(client, headers, fresh).status_code == 200
    assert confirm(client, headers, pending).status_code == 410
    assert len(context(client)['plans']) == 1


def test_expiry_is_checked_after_waiting_for_writer_lock(app, token_clock):
    client, headers = member(app)
    pending = preview(client, headers, make_payload())
    before, waiting = snapshot(app), Event()
    writer = sqlite3.connect(database(app), timeout=10, check_same_thread=False)
    def block(sql):
        if sql == 'BEGIN IMMEDIATE':
            writer.execute('BEGIN IMMEDIATE')
            waiting.set()
    install_connection(app, PREFIX + '/confirm', 'POST', before=block)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(confirm, client, headers, pending)
            try:
                assert waiting.wait(10)
                assert not future.done()
                token_clock['now'] += 601
            finally:
                writer.commit()
            response = future.result(timeout=10)
        assert response.status_code == 410 and response.json['code'] == 'preview_expired_unapplied'
        assert snapshot(app) == before
    finally:
        writer.close()


def test_receipt_after_new_login_is_readable_but_old_session_cannot_write(app, token_clock):
    client, headers = member(app)
    done = preview(client, headers, make_payload())
    assert confirm(client, headers, done).status_code == 200
    pending = preview(client, headers, make_payload(title='UNAPPLIED'))
    expected = client.get(receipt_path(done)).json
    assert client.post('/api/logout', json={}, headers=headers).status_code == 200
    assert client.post('/api/login', json={'username': 'member1', 'password': 'testing-password-one'}).status_code == 200
    fresh_headers = {'X-CSRF-Token': client.get('/api/me').json['csrf']}
    token_clock['now'] += 601
    assert client.get(receipt_path(done)).json == expected
    assert confirm(client, fresh_headers, done).status_code == 403
    assert confirm(client, fresh_headers, pending).status_code == 403
    assert len(context(client)['plans']) == 1


def test_expired_retry_waits_for_inflight_commit_and_replays_instead_of_410(app, token_clock):
    client, headers = member(app)
    pending = preview(client, headers, make_payload())
    cookie = client.get_cookie(app.config['SESSION_COOKIE_NAME']).value
    second = app.test_client()
    second.set_cookie(app.config['SESSION_COOKIE_NAME'], cookie)
    inserted, release, started = Event(), Event(), Event()
    def hold_commit(sql):
        if sql.startswith('INSERT INTO routine_receipts'):
            inserted.set()
            assert release.wait(10)
    install_connection(app, PREFIX + '/confirm', 'POST', after=hold_commit)
    def retry():
        started.set()
        return confirm(second, headers, pending)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(confirm, client, headers, pending)
        try:
            assert inserted.wait(10)
            token_clock['now'] += 601
            replay = pool.submit(retry)
            assert started.wait(10) and not replay.done()
        finally:
            release.set()
        original, repeated = first.result(timeout=10), replay.result(timeout=10)
    assert original.status_code == repeated.status_code == 200
    assert repeated.json == {**original.json, 'replayed': True}
    with closing(sqlite3.connect(database(app))) as con:
        assert con.execute('SELECT count(*) FROM routine_receipts').fetchone()[0] == 1
        assert con.execute('SELECT count(*) FROM routine_occurrences').fetchone()[0] == 1


def test_receipt_scope_input_tv_and_csrf(app):
    client, headers = member(app)
    pending = preview(client, headers, make_payload())
    assert confirm(client, headers, pending).status_code == 200
    path = receipt_path(pending)
    assert app.test_client().get(path).status_code == 401
    assert client.get(path + '?owner=member2').status_code == 400
    assert client.get(PREFIX + '/operations/not-a-key').status_code == 400
    assert client.post(PREFIX + '/confirm', json={'previewToken': pending.json['previewToken']}).status_code == 403
    assert client.post(PREFIX + '/confirm', json={'operationKey': pending.json['operationKey']}, headers=headers).status_code == 400
    child, _, space = create_space(app)
    assert child.get(space['entry']).status_code == 303
    assert child.post('/api/login', json={'username': 'member1', 'password': 'second-home-password-one'}).status_code == 200
    assert child.get(path).status_code == 404
    tv = app.test_client()
    pairing = tv.post('/api/pair/start', json={}).json
    assert client.post('/api/pair/approve', json={'code': pairing['code'], 'name': 'Synthetic TV'}, headers=headers).status_code == 200
    assert tv.post('/api/pair/poll', json={'secret': pairing['secret']}).json['approved']
    assert tv.get(path).status_code == 403


def prepared(app, route):
    client, headers = member(app)
    pending = preview(client, headers, make_payload())
    if route in {'receipt', 'replay'}:
        assert confirm(client, headers, pending).status_code == 200
    method, path, payload = {
        'context': ('GET', PREFIX + '/context', None),
        'preview': ('POST', PREFIX + '/preview', make_payload()),
        'receipt': ('GET', receipt_path(pending), None),
        'confirm': ('POST', PREFIX + '/confirm', {'previewToken': pending.json['previewToken']}),
        'replay': ('POST', PREFIX + '/confirm', {'previewToken': pending.json['previewToken']}),
    }[route]
    return client, headers, method, path, payload


@pytest.mark.parametrize('route', ['context', 'preview', 'receipt'])
@pytest.mark.parametrize('kind', ['session', 'expired', 'auth_version'])
def test_read_releases_snapshot_and_freshly_checks_real_session(app, route, kind):
    client, headers, method, path, payload = prepared(app, route)
    before, observed = snapshot(app), []
    target = {'context': 'SELECT * FROM household_routines ',
              'preview': 'SELECT count(*) FROM household_routines ',
              'receipt': 'SELECT operation,plan_id,result,created_at FROM routine_receipts '}[route]
    def revoke(sql):
        if sql.startswith(target) and not observed:
            with sqlite3.connect(database(app)) as con:
                invalidate(con, kind)
            observed.append(True)
    install_connection(app, path, method, after=revoke)
    result = client.open(path, method=method, json=payload, headers=headers)
    assert observed == [True]
    assert result.status_code == 401 and set(result.json) == {'error'}
    assert b'SYNTHETIC_ROUTINE' not in result.data and snapshot(app) == before


@pytest.mark.parametrize('route', ['context', 'preview', 'receipt', 'confirm', 'replay'])
def test_all_routes_reject_a_different_captured_session_id(app, route):
    client, headers, method, path, payload = prepared(app, route)
    before = snapshot(app)
    def mismatch():
        if request.path == path and request.method == method:
            g.member_session['id'] = '0' * 32
    app.before_request_funcs[None].append(mismatch)
    result = client.open(path, method=method, json=payload, headers=headers)
    assert result.status_code == 401 and snapshot(app) == before


@pytest.mark.parametrize('operation_name', ['create', 'update', 'pause', 'resume', 'skip', 'archive'])
def test_all_mutations_recheck_expiry_after_audit_before_commit(app, monkeypatch, operation_name):
    import member_sessions
    client, headers = member(app)
    rule = create(client, headers)['plan']
    if operation_name == 'resume':
        rule = confirm(client, headers, operation(client, headers, rule, 'pause')).json['plan']
    value = make_payload(title='CHANGED')
    pending = (preview(client, headers, value) if operation_name == 'create' else
               operation(client, headers, rule, operation_name,
                         **({'template': value['template'], 'schedule': value['schedule']} if operation_name == 'update' else {})))
    assert pending.status_code == 200
    before, observed = snapshot(app), []
    with closing(sqlite3.connect(database(app))) as con:
        expiry = con.execute("SELECT max(expires_at) FROM member_sessions WHERE owner='member1'").fetchone()[0]
    clock = {'now': time.time()}
    monkeypatch.setattr(member_sessions, 'time', SimpleNamespace(time=lambda: clock['now']))
    def expire(sql):
        if sql.startswith('UPDATE settings SET revision'):
            clock['now'] = expiry + 1
            observed.append(True)
    install_connection(app, PREFIX + '/confirm', 'POST', after=expire)
    result = confirm(client, headers, pending)
    assert observed == [True] and result.status_code == 401
    assert snapshot(app) == before


@pytest.mark.parametrize('kind', ['session', 'expired', 'auth_version'])
def test_confirm_waiting_on_real_writer_observes_revocation(app, kind):
    client, headers = member(app)
    pending = preview(client, headers, make_payload())
    before, waiting = snapshot(app), Event()
    writer = sqlite3.connect(database(app), timeout=10, check_same_thread=False)
    def block(sql):
        if sql == 'BEGIN IMMEDIATE':
            writer.execute('BEGIN IMMEDIATE')
            invalidate(writer, kind)
            waiting.set()
    install_connection(app, PREFIX + '/confirm', 'POST', before=block)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(confirm, client, headers, pending)
            try:
                assert waiting.wait(10)
                assert not future.done()
            finally:
                writer.commit()
            response = future.result(timeout=10)
        assert response.status_code == 401 and snapshot(app) == before
    finally:
        writer.close()


@pytest.mark.parametrize('route', ['context', 'preview', 'receipt', 'replay'])
def test_legacy_cookie_read_and_replay_release_implicit_transaction(app, monkeypatch, route):
    client, raw, cookie = legacy(app, app.extensions['member_sessions'], monkeypatch)
    headers = {'X-CSRF-Token': cookie['csrf'], 'Origin': 'http://localhost'}
    pending = preview(client, headers, make_payload())
    assert confirm(client, headers, pending).status_code == 200
    result = {'context': lambda: client.get(PREFIX + '/context'),
              'preview': lambda: preview(client, headers, make_payload()),
              'receipt': lambda: client.get(receipt_path(pending)),
              'replay': lambda: confirm(client, headers, pending)}[route]()
    assert result.status_code == 200
    fresh = preview(client, headers, make_payload(title='SECOND_LEGACY_RULE'))
    assert confirm(client, headers, fresh).status_code == 200
    assert len(context(client)['plans']) == 2 and client.get_cookie('session').value == raw


def test_audit_failure_rolls_back_then_original_token_can_retry_once(app):
    client, headers = member(app)
    pending = preview(client, headers, make_payload())
    before, observed = snapshot(app), []
    def fail_audit(sql):
        if sql.startswith('INSERT INTO audit') and not observed:
            observed.append(True)
            raise RuntimeError('synthetic audit failure')
    install_connection(app, PREFIX + '/confirm', 'POST', before=fail_audit)
    with pytest.raises(RuntimeError, match='synthetic audit failure'):
        confirm(client, headers, pending)
    assert snapshot(app) == before
    assert client.get(receipt_path(pending)).status_code == 404
    saved = confirm(client, headers, pending)
    assert saved.status_code == 200 and not saved.json['replayed']
    assert confirm(client, headers, pending).json['replayed'] is True
    assert len(context(client)['plans']) == 1
