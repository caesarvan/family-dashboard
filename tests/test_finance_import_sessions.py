"""Real HTTP/session/SQLite recovery boundaries; synthetic local inputs only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from copy import deepcopy
import json
from pathlib import Path
import socket
import sqlite3
from threading import Event
import time
from types import SimpleNamespace

from flask import g, request
from itsdangerous import TimestampSigner, URLSafeTimedSerializer
import pytest

import member_sessions
from finance_source_bridge import digest, normalize_candidate
from finance_baseline import import_baseline
from spending_observations import normalize_spending_candidate, encode
from test_app import app, member
from test_device_sessions import install_connection, invalidate
from test_household_spaces import create_space
from test_member_sessions import legacy
from test_finance_source_bridge import synthetic_candidate
from test_spending_observations import MODE, observation

BASE = '/api/finance-baseline/imports/'


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*_a, **_kw):
        raise AssertionError('No external finance calls')
    monkeypatch.setattr(socket.socket, 'connect', deny)


@contextmanager
def database(app, **kwargs):
    with closing(sqlite3.connect(Path(app.config['DATA_DIR'])/'household.sqlite3', **kwargs)) as con:
        with con:
            yield con


def snapshot(app):
    with database(app) as con:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {t: con.execute('SELECT * FROM "'+t+'" ORDER BY rowid').fetchall() for t in tables
                if t not in {'users', 'member_sessions', 'member_session_browsers', 'attempts'}}


def seed(app):
    _, private, shared, _ = normalize_candidate(synthetic_candidate(), 'member1')
    private['spending'] = observation('2026-09-14', 1000)['spending']
    with database(app) as con:
        import_baseline(con, private, shared)


def status(client, mode, operation=None):
    return client.get(BASE+'status', query_string={'mode': mode, **({'operationId': operation} if operation else {})})


def prepare(client, headers, mode, candidate=None):
    view = status(client, mode)
    assert view.status_code == 200, view.json
    candidate = candidate or (observation() if mode == MODE else synthetic_candidate())
    payload = ({'mode': mode, 'candidate': candidate, **view.json['expected'], 'acknowledgeUnknownPreviousCoverage': False}
               if mode == MODE else {'candidate': candidate, 'expectedRevision': view.json['current']['revision'] if view.json['current'] else 0,
                                      'expectedSourceDigest': view.json['current']['sourceDigest'] if view.json['current'] else None})
    response = client.post(BASE+'preview', json=payload, headers=headers)
    assert response.status_code == 200, response.json
    confirm = {'candidate': candidate, 'previewToken': response.json['previewToken']}
    if mode == MODE:
        confirm['mode'] = mode
    return response.json, payload, confirm


def setup(app, mode):
    seed(app)
    client, headers = member(app)
    preview, payload, confirm = prepare(client, headers, mode)
    return client, headers, preview, payload, confirm


def denied(response, code=401):
    assert response.status_code == code, response.json
    assert 'error' in response.json and 'SYNTHETIC_PRIVATE' not in response.get_data(as_text=True)


@pytest.mark.parametrize('mode', ['baseline', MODE])
@pytest.mark.parametrize('operation', ['status', 'preview', 'receipt'])
@pytest.mark.parametrize('kind', ['session', 'expired', 'auth_version'])
def test_read_drops_snapshot_after_concurrent_revocation(app, mode, operation, kind):
    client, headers, preview, payload, confirm = setup(app, mode)
    if operation == 'receipt':
        assert client.post(BASE+'confirm', json=confirm, headers=headers).status_code == 200
    before, calls = snapshot(app), []
    def after(sql):
        matched = ('FROM finance_' in sql and 'receipts WHERE id=' in sql) if operation == 'receipt' else sql.startswith('SELECT private_data,revision')
        if matched and not calls:
            with database(app) as con:
                invalidate(con, kind)
            calls.append(True)
    install_connection(app, BASE+('preview' if operation == 'preview' else 'status'),
                       'POST' if operation == 'preview' else 'GET', after=after)
    result = (client.post(BASE+'preview', json=payload, headers=headers) if operation == 'preview'
              else status(client, mode, preview['operationId'] if operation == 'receipt' else None))
    denied(result)
    assert calls == [True] and snapshot(app) == before


@pytest.mark.parametrize('mode', ['baseline', MODE])
@pytest.mark.parametrize('kind', ['session', 'expired', 'auth_version'])
@pytest.mark.parametrize('wait_for_lock', [False, True])
def test_confirm_checks_actual_session_after_guard_and_waited_lock(app, mode, kind, wait_for_lock):
    client, headers, _, _, confirm = setup(app, mode)
    before, entered = snapshot(app), Event()
    with closing(sqlite3.connect(Path(app.config['DATA_DIR'])/'household.sqlite3', timeout=5, check_same_thread=False)) as writer:
        def change(sql=None):
            if wait_for_lock and sql != 'BEGIN IMMEDIATE':
                return
            if not wait_for_lock and request.path != BASE+'confirm':
                return
            writer.execute('BEGIN IMMEDIATE')
            invalidate(writer, kind)
            if not wait_for_lock:
                writer.commit()
            # Signal only after this thread's commit, or while the lock stays held.
            entered.set()
        if wait_for_lock:
            install_connection(app, BASE+'confirm', 'POST', before=change)
        else:
            app.before_request_funcs[None].append(change)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(client.post, BASE+'confirm', json=confirm, headers=headers)
            try:
                assert entered.wait(10)
                assert writer.in_transaction is wait_for_lock
                if wait_for_lock:
                    assert not pending.done()
            finally:
                if wait_for_lock:
                    writer.commit()
            denied(pending.result(timeout=10))
    assert snapshot(app) == before


@pytest.mark.parametrize('mode', ['baseline', MODE])
def test_expiry_after_audit_rolls_back_all_business_rows(app, monkeypatch, mode):
    client, headers, _, _, confirm = setup(app, mode)
    before = snapshot(app)
    with database(app) as con:
        expires = con.execute("SELECT max(expires_at) FROM member_sessions WHERE owner='member1'").fetchone()[0]
    clock = [time.time()]
    monkeypatch.setattr(member_sessions, 'time', SimpleNamespace(time=lambda: clock[0]))
    def after(sql):
        if sql.startswith('UPDATE settings SET revision'):
            clock[0] = expires+1
    install_connection(app, BASE+'confirm', 'POST', after=after)
    denied(client.post(BASE+'confirm', json=confirm, headers=headers))
    assert clock[0] == expires+1 and snapshot(app) == before


@pytest.mark.parametrize('mode', ['baseline', MODE])
def test_token_aging_while_waiting_for_writer_lock_is_rejected(app, monkeypatch, mode):
    client, headers, _, _, confirm = setup(app, mode)
    before, entered, advance = snapshot(app), Event(), [0]
    original = TimestampSigner.get_timestamp
    monkeypatch.setattr(TimestampSigner, 'get_timestamp', lambda self: original(self)+advance[0])
    with closing(sqlite3.connect(Path(app.config['DATA_DIR'])/'household.sqlite3', timeout=5, check_same_thread=False)) as writer:
        def lock(sql):
            if sql == 'BEGIN IMMEDIATE':
                writer.execute('BEGIN IMMEDIATE')
                advance[0] = 1201
                entered.set()
        install_connection(app, BASE+'confirm', 'POST', before=lock)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(client.post, BASE+'confirm', json=confirm, headers=headers)
            try:
                assert entered.wait(10) and not pending.done()
            finally:
                writer.commit()
            response = pending.result(timeout=10)
    assert response.status_code == 410 and response.json['code'] == 'preview_expired'
    assert snapshot(app) == before


@pytest.mark.parametrize('mode', ['baseline', MODE])
@pytest.mark.parametrize('committed', [False, True])
def test_expired_operation_recovers_only_persisted_receipt_after_new_login(app, monkeypatch, mode, committed):
    client, headers, preview, _, confirm = setup(app, mode)
    if committed:
        first = client.post(BASE+'confirm', json=confirm, headers=headers)
        assert first.status_code == 200
        # A historical receipt remains available after the source row disappears.
        with database(app) as con:
            con.execute('DELETE FROM finance_baselines')
            con.execute('DELETE FROM finance_spending_observations')
    assert client.post('/api/login', json={'username':'member1', 'password':'testing-password-one'}).status_code == 200
    headers = {'X-CSRF-Token':client.get('/api/me').json['csrf']}
    before = snapshot(app)
    tick = TimestampSigner.get_timestamp
    monkeypatch.setattr(TimestampSigner, 'get_timestamp', lambda self: tick(self)+1201)
    read = status(client, mode, preview['operationId'])
    assert read.status_code == 200 and read.json['found'] is committed
    response = client.post(BASE+'confirm', json=confirm, headers=headers)
    if committed:
        assert response.status_code == 200 and response.json == {**first.json, 'replayed':True}
        assert read.json['receipt'] == response.json
    else:
        assert read.json['receipt'] is None
        assert response.status_code == 410 and response.json['code'] == 'preview_expired'
    assert snapshot(app) == before


@pytest.mark.parametrize('mode', ['baseline', MODE])
def test_uncommitted_preview_is_bound_to_actual_session(app, mode):
    client, headers, preview, _, confirm = setup(app, mode)
    assert client.post('/api/login', json={'username':'member1', 'password':'testing-password-one'}).status_code == 200
    headers = {'X-CSRF-Token':client.get('/api/me').json['csrf']}
    before = snapshot(app)
    denied(client.post(BASE+'confirm', json=confirm, headers=headers), 403)
    assert status(client, mode, preview['operationId']).json['found'] is False
    assert snapshot(app) == before


@pytest.mark.parametrize('mode', ['baseline', MODE])
@pytest.mark.parametrize('operation', ['preview', 'replay'])
def test_actual_cookie_rotation_during_read_discards_result(app, mode, operation):
    client, headers, _, payload, confirm = setup(app, mode)
    if operation == 'replay':
        assert client.post(BASE+'confirm', json=confirm, headers=headers).status_code == 200
    replacement = app.test_client()
    replacement.set_cookie('session', client.get_cookie('session').value)
    calls = []
    if operation == 'preview':
        def after(sql):
            if sql.startswith('SELECT private_data,revision') and not calls:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    r = pool.submit(replacement.post, '/api/login', json={'username':'member1','password':'testing-password-one'}).result(10)
                assert r.status_code == 200
                calls.append(True)
        install_connection(app, BASE+'preview', 'POST', after=after)
    else:
        # Hook the released write transaction, never ask a second writer to
        # commit while this request still owns BEGIN IMMEDIATE.
        from finance_source_bridge import ImportSession
        original = ImportSession.fresh
        def fresh(session):
            if not calls:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    r = pool.submit(replacement.post, '/api/login', json={'username':'member1','password':'testing-password-one'}).result(10)
                assert r.status_code == 200
                calls.append(True)
            return original(session)
        # Patching only the timing seam; authorization remains the actual engine.
        from unittest.mock import patch
        with patch.object(ImportSession, 'fresh', fresh):
            denied(client.post(BASE+'confirm', json=confirm, headers=headers))
        assert calls == [True]
        return
    denied(client.post(BASE+'preview', json=payload, headers=headers))
    assert calls == [True]


@pytest.mark.parametrize('mode', ['baseline', MODE])
def test_legacy_cookie_and_empty_status_keep_original_abi(app, monkeypatch, mode):
    client, _, value = legacy(app, app.extensions['member_sessions'], monkeypatch)
    headers = {'X-CSRF-Token':value['csrf']}
    view = status(client, mode)
    assert view.status_code == 200
    assert view.json['current'] is None
    if mode == MODE:
        seed(app)
    before = snapshot(app)
    preview, _, confirm = prepare(client, headers, mode)
    assert snapshot(app) == before
    result = client.post(BASE+'confirm', json=confirm, headers=headers)
    assert result.status_code == 200, result.json
    assert result.json['receiptId'] == preview['operationId']
    assert client.post(BASE+'confirm', json=confirm, headers=headers).json['replayed']


@pytest.mark.parametrize('mode', ['baseline', MODE])
def test_preview_uses_snapshot_and_external_write_causes_confirm_conflict(app, mode):
    client, headers, _, payload, _ = setup(app, mode)
    before, calls = snapshot(app), []
    def after(sql):
        if sql.startswith('SELECT private_data,revision') and not calls:
            with database(app) as con:
                con.execute('UPDATE finance_baselines SET revision=revision+1')
                if mode == MODE:
                    candidate, candidate_digest, source_digest = normalize_spending_candidate(observation())
                    con.execute('INSERT INTO finance_spending_observations VALUES(?,?,?,?,?,?)',
                                ('member1',1,source_digest,candidate_digest,encode(candidate),'2026-09-17T00:00:00Z'))
            calls.append(True)
    install_connection(app, BASE+'preview', 'POST', after=after)
    response = client.post(BASE+'preview', json=payload, headers=headers)
    assert response.status_code == 200 and calls == [True], response.json
    expected = response.json['expected']['expectedBaselineRevision'] if mode == MODE else response.json['expectedRevision']
    assert expected == 1
    if mode == MODE:
        assert response.json['expected']['expectedRevision'] == 0
    after_write = snapshot(app)
    for table in before:
        if table not in {'finance_baselines', 'finance_spending_observations'}:
            assert before[table] == after_write[table]
    body = {'candidate':payload['candidate'], 'previewToken':response.json['previewToken']}
    if mode == MODE: body['mode'] = mode
    denied(client.post(BASE+'confirm', json=body, headers=headers), 409)
    assert snapshot(app) == after_write


@pytest.mark.parametrize('mode', ['baseline', MODE])
def test_receipt_queries_are_private_and_strict(app, mode):
    client, headers, preview, _, confirm = setup(app, mode)
    assert client.post(BASE+'confirm', json=confirm, headers=headers).status_code == 200
    partner, _ = member(app, 2)
    assert status(partner, mode, preview['operationId']).json['found'] is False
    foreign, _, space = create_space(app)
    assert foreign.get(space['entry']).status_code == 303
    assert foreign.post('/api/login', json={'username':'member1','password':'second-home-password-one'}).status_code == 200
    assert status(foreign, mode, preview['operationId']).json['found'] is False
    foreign_headers = {'X-CSRF-Token':foreign.get('/api/me').json['csrf']}
    denied(foreign.post(BASE+'confirm', json=confirm, headers=foreign_headers), 409)
    tv = app.test_client()
    pair = tv.post('/api/pair/start', json={}).json
    assert client.post('/api/pair/approve', json={'code':pair['code'],'name':'Synthetic TV'}, headers=headers).status_code == 200
    assert tv.post('/api/pair/poll', json={'secret':pair['secret']}).json['approved']
    before = snapshot(app)
    denied(status(tv, mode, preview['operationId']), 403)
    denied(status(app.test_client(), mode, preview['operationId']))
    for value in ('', 'A'*64, '0'*63, '0'*65, '../receipt'):
        denied(client.get(BASE+'status', query_string={'mode':mode,'operationId':value}), 400)
    for query in (f'mode={mode}&mode={mode}', f'mode={mode}&operationId='+'0'*64+'&operationId='+'1'*64):
        denied(client.get(BASE+'status?'+query), 400)
    assert snapshot(app) == before


@pytest.mark.parametrize('mode', ['baseline', MODE])
def test_missing_engine_and_captured_session_mismatch_fail_closed(app, monkeypatch, mode):
    client, headers, _, payload, confirm = setup(app, mode)
    before = snapshot(app)
    engine = app.extensions.pop('member_sessions')
    for response in (status(client, mode), client.post(BASE+'preview', json=payload, headers=headers),
                     client.post(BASE+'confirm', json=confirm, headers=headers)):
        denied(response, 503)
    app.extensions['member_sessions'] = engine
    def mismatch():
        if request.path.startswith(BASE):
            g.member_session = {**g.member_session, 'id':'another-session'}
    app.before_request_funcs[None].append(mismatch)
    for response in (status(client, mode), client.post(BASE+'preview', json=payload, headers=headers),
                     client.post(BASE+'confirm', json=confirm, headers=headers)):
        denied(response)
    assert snapshot(app) == before


@pytest.mark.parametrize('mode', ['baseline', MODE])
def test_signed_malformed_claims_and_candidate_mismatch_do_not_mutate(app, mode):
    client, headers, preview, _, confirm = setup(app, mode)
    signer = URLSafeTimedSerializer(app.secret_key, salt='spending-observation-v1' if mode == MODE else 'finance-source-import-v1')
    good = signer.loads(preview['previewToken'])
    before = snapshot(app)
    invalid_source = '0'*64 if good['expectedRevision'] == 0 else None
    for bad in ([], None, {**good,'context':False}, {**good,'expectedRevision':True}, {**good,'expectedSourceDigest':invalid_source},
                {**good,'extra':1}, {**good,'owner':[]}, {**good,'candidateDigest':'wrong'}):
        denied(client.post(BASE+'confirm', json={**confirm,'previewToken':signer.dumps(bad)}, headers=headers), 400)
    changed = deepcopy(confirm)
    if mode == MODE:
        changed['candidate'] = observation(net=1200)
    else:
        changed['candidate'] = synthetic_candidate(amount_cents=13000)
    denied(client.post(BASE+'confirm', json=changed, headers=headers), 403)
    assert snapshot(app) == before


@pytest.mark.parametrize('mode', ['baseline', MODE])
def test_old_claims_recover_history_but_unbound_baseline_cannot_write(app, mode):
    client, headers, preview, _, confirm = setup(app, mode)
    signer = URLSafeTimedSerializer(app.secret_key, salt='spending-observation-v1' if mode == MODE else 'finance-source-import-v1')
    old = signer.loads(preview['previewToken'])
    del old['household' if mode == MODE else 'context']
    old_body = {**confirm, 'previewToken':signer.dumps(old)}
    before = snapshot(app)
    if mode == MODE:
        # The old spending binding remains valid for its original session.
        done = client.post(BASE+'confirm', json=old_body, headers=headers)
        assert done.status_code == 200
    else:
        response = client.post(BASE+'confirm', json=old_body, headers=headers)
        assert response.status_code == 409 and response.json['code'] == 'preview_repreview_required'
        assert snapshot(app) == before
        done = client.post(BASE+'confirm', json=confirm, headers=headers)
        assert done.status_code == 200
        # Seed an actual old-server receipt using the persisted result, without
        # claiming the new endpoint can execute an unbound legacy write.
        with database(app) as con:
            con.execute('UPDATE finance_source_receipts SET id=? WHERE id=?', (digest(old), preview['operationId']))
    assert client.post('/api/login', json={'username':'member1','password':'testing-password-one'}).status_code == 200
    headers = {'X-CSRF-Token':client.get('/api/me').json['csrf']}
    before = snapshot(app)
    result = client.post(BASE+'confirm', json=old_body, headers=headers)
    assert result.status_code == 200 and result.json['replayed']
    assert result.json['receiptId'] == digest(old)
    assert status(client, mode, digest(old)).json['receipt'] == result.json
    assert snapshot(app) == before
