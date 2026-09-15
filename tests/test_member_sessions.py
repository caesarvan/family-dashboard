"""Revocation, legacy migration and late auth decisions: synthetic DB/HTTP only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import socket
import sqlite3
import threading
import time
from urllib.parse import parse_qs, urlsplit

import pytest
from flask import request
from itsdangerous.timed import TimestampSigner

from app import create_app
from member_sessions import digest, LEGACY_SETTING
from test_cloud_accounts import Remote
from test_session_refresh import delayed_server, PASSWORD


@pytest.fixture
def env(tmp_path, monkeypatch):
    connect = socket.socket.connect

    def local_only(sock, address):
        assert isinstance(address, tuple) and address[0] in {'127.0.0.1', '::1'}, 'Network outside loopback forbidden'
        return connect(sock, address)

    monkeypatch.setattr(socket.socket, 'connect', local_only)
    remote = Remote()
    config = {'TESTING': True, 'DATA_DIR': str(tmp_path / 'data'),
              'SECRET_KEY': 'synthetic-revocation-test-key', 'SESSION_COOKIE_SECURE': False,
              'PUBLIC_ORIGIN': 'http://localhost', 'MEMBER1_PASSWORD': PASSWORD, 'MEMBER2_PASSWORD': PASSWORD,
              'MICROSOFT_CLIENT_ID': 'fake-ms-client', 'MICROSOFT_CLIENT_SECRET': 'fake-secret',
              'GOOGLE_CLIENT_ID': 'fake-google-client', 'GOOGLE_CLIENT_SECRET': 'fake-secret',
              'OAUTH_TRANSPORT': remote.tokens, 'CLOUD_PROVIDER_FACTORY': remote.factory,
              'OPENAI_API_KEY': '', 'OPENAI_MODEL': ''}
    app = create_app(config)
    return app, app.extensions['member_sessions'], remote, config


def login(app, member='member1', client=None):
    client = client or app.test_client()
    client.get('/api/me')
    result = client.post('/api/login', json={'username': member, 'password': PASSWORD})
    assert result.status_code == 200, result.json
    return client, headers(client)


def headers(client):
    return {'X-CSRF-Token': client.get('/api/me').json['csrf'], 'Origin': 'http://localhost'}


def clone(app, client):
    other = app.test_client()
    for name in ('session', 'household_space'):
        cookie = client.get_cookie(name)
        if cookie:
            other.set_cookie(name, cookie.value)
    return other


def legacy(app, engine, monkeypatch, *, csrf=None, issued=None, **extra):
    value = {'uid': 'member1', 'av': 1, 'csrf': csrf or secrets.token_urlsafe(32), '_permanent': True, **extra}
    with monkeypatch.context() as change:
        change.setattr(TimestampSigner, 'get_timestamp', lambda _: int(issued if issued is not None else engine.legacy_cutoff - 1))
        raw = app.session_interface.get_signing_serializer(app).dumps(value)
    client = app.test_client()
    client.set_cookie('session', raw)
    return client, raw, value


def begin(client, provider='google', mode='bind'):
    response = (client.post('/api/accounts/bind', headers=headers(client), json={'provider': provider})
                if mode == 'bind' else client.get('/auth/' + provider + '/login'))
    assert response.status_code == (200 if mode == 'bind' else 302)
    url = response.json['url'] if mode == 'bind' else response.location
    return parse_qs(urlsplit(url).query)['state'][0]


def finish(client, state, provider='google'):
    return client.get('/auth/' + provider + '/callback', query_string={'state': state, 'code': 'person'})


def bind_account(app, remote, provider='google'):
    client, _ = login(app)
    remote.identities['person'] = {'subject': 'synthetic-subject', 'name': 'Fictional'}
    assert finish(client, begin(client, provider), provider).location.endswith('auth=connected')
    aid = client.get('/api/accounts').json['accounts'][0]['id']
    return client, aid


def test_bootstrap_only_anonymous_and_public_ids_are_not_credentials(env):
    app, engine, _, _ = env
    client = app.test_client()
    assert not client.get('/api/auth/providers').headers.getlist('Set-Cookie')
    first = client.get('/api/me')
    assert first.json == {'user': None, 'csrf': None} and first.headers.getlist('Set-Cookie')
    assert not client.get('/api/me').headers.getlist('Set-Cookie')
    client, _ = login(app, client=client)
    value = client.get('/api/sessions')
    assert value.status_code == 200 and value.json['lastSeenIntervalSeconds'] == 300
    assert not value.headers.getlist('Set-Cookie')
    assert len(value.json['sessions']) == 1
    item = value.json['sessions'][0]
    assert set(item) == {'id','device','createdAt','lastSeenAt','expiresAt','current'} and item['current']
    for field in ('createdAt', 'lastSeenAt', 'expiresAt'):
        assert datetime.fromisoformat(item[field]).tzinfo
    with engine.db() as con:
        row = con.execute('SELECT * FROM member_sessions').fetchone()
    assert row['id'] != row['credential_hash'] and row['credential_hash'] not in value.get_data(as_text=True)
    assert row['browser_hash'] not in value.get_data(as_text=True)


@pytest.mark.parametrize('action', ['logout', 'delete-current'])
def test_copied_cookie_cannot_revive_after_revocation(env, action):
    app, engine, _, _ = env
    client, h = login(app)
    stolen = clone(app, client)
    if action == 'logout':
        result = client.post('/api/logout', json={}, headers=h)
    else:
        sid = client.get('/api/sessions').json['sessions'][0]['id']
        result = client.delete('/api/sessions/' + sid, json={}, headers=h)
        assert result.json['current']
    assert result.status_code == 200
    assert stolen.get('/api/finance-hub').status_code == 401
    assert stolen.get('/api/me').json['user'] is None
    with client.session_transaction() as cookie:
        assert set(cookie) == {'_permanent', 'browser_id'}
    with engine.db() as con:
        assert con.execute('SELECT revoked_at FROM member_sessions').fetchone()[0] is not None


def test_revoke_others_ownership_csrf_and_current_preserved(env):
    app, _, _, _ = env
    current, h = login(app)
    other, _ = login(app)
    partner, ph = login(app, 'member2')
    item = other.get('/api/sessions').json['sessions']
    other_id = next(x['id'] for x in item if x['current'])
    assert partner.delete('/api/sessions/' + other_id, json={}, headers=ph).status_code == 404
    assert current.delete('/api/sessions/missing', json={}, headers=h).status_code == 404
    assert current.post('/api/sessions/revoke-others', json={}).status_code == 403
    assert current.post('/api/sessions/revoke-others', json={}, headers={**h, 'Origin': 'https://other.example.test'}).status_code == 403
    result = current.post('/api/sessions/revoke-others', json={}, headers=h)
    assert result.json == {'ok': True, 'revoked': 1}
    assert current.get('/api/me').json['user']['id'] == 'member1'
    assert other.get('/api/sessions').status_code == 401
    assert partner.get('/api/me').json['user']['id'] == 'member2'
    assert current.post('/api/sessions/revoke-others', json={}, headers=h).json['revoked'] == 0


@pytest.mark.parametrize('field,value', [('session_v', True), ('uid', 'member2'), ('av', 2), ('csrf', 'missing-row-credential-00000')])
def test_signed_cookie_requires_matching_live_row(env, field, value):
    app, engine, _, _ = env
    client, _ = login(app)
    with client.session_transaction() as cookie:
        cookie[field] = value
    assert client.get('/api/sessions').status_code == 401
    with engine.db() as con:
        assert con.execute('SELECT count(*) FROM member_sessions').fetchone()[0] == 1


def test_missing_v1_row_does_not_fall_back_to_legacy(env):
    app, engine, _, _ = env
    client, _ = login(app)
    with engine.db() as con:
        con.execute('DELETE FROM member_sessions')
    assert client.get('/api/me').json['user'] is None
    assert client.get('/api/sessions').status_code == 401
    with engine.db() as con:
        assert con.execute('SELECT count(*) FROM member_sessions').fetchone()[0] == 0


def test_legacy_lazy_registration_read_does_not_mutate_cookie_and_restart_is_fixed(env, monkeypatch):
    app, engine, _, config = env
    old, raw, _ = legacy(app, engine, monkeypatch)
    result = old.get('/api/me')
    assert result.json['user']['id'] == 'member1' and not result.headers.getlist('Set-Cookie')
    assert old.get_cookie('session').value == raw
    second = create_app(config).extensions['member_sessions']
    assert (second.legacy_cutoff, second.legacy_until) == (engine.legacy_cutoff, engine.legacy_until)
    with engine.db() as con:
        assert con.execute('SELECT count(*) FROM member_sessions').fetchone()[0] == 1
        assert con.execute('SELECT auth_version FROM users WHERE id="member1"').fetchone()[0] == 1


@pytest.mark.parametrize('invalid', ['after-cutoff', 'expired', 'bad-signature'])
def test_legacy_rejects_invalid_signature_or_introduction_time(env, monkeypatch, invalid):
    app, engine, _, _ = env
    issued = engine.legacy_cutoff + 1 if invalid == 'after-cutoff' else engine.legacy_cutoff - engine.legacy_ttl - 10 if invalid == 'expired' else None
    client, raw, _ = legacy(app, engine, monkeypatch, issued=issued)
    if invalid == 'bad-signature':
        client.set_cookie('session', raw + 'tampered')
    assert client.get('/api/sessions').status_code == 401
    with engine.db() as con:
        assert con.execute('SELECT count(*) FROM member_sessions').fetchone()[0] == 0


def test_legacy_later_signed_variant_cannot_resurrect_after_cleanup(env, monkeypatch):
    app, engine, _, _ = env
    old, _, value = legacy(app, engine, monkeypatch, issued=engine.legacy_cutoff - engine.legacy_ttl + 60)
    old_h = headers(old)
    assert old_h['X-CSRF-Token']
    assert old.post('/api/logout', json={}, headers=old_h).status_code == 200
    # Oldest observed signature expires, but another pre-cutoff signature with
    # the same CSRF could still be valid for another month. Keep the tombstone.
    future = engine.legacy_cutoff + 120
    monkeypatch.setattr(time, 'time', lambda: future)
    with engine.db() as con:
        engine.clean(con, future)
        assert con.execute('SELECT count(*) FROM member_sessions WHERE revoked_at IS NOT NULL').fetchone()[0] == 1
    later, _, _ = legacy(app, engine, monkeypatch, csrf=value['csrf'], issued=engine.legacy_cutoff)
    assert later.get('/api/sessions').status_code == 401
    with engine.db() as con:
        engine.clean(con, engine.legacy_until + 1)
        assert con.execute('SELECT count(*) FROM member_sessions').fetchone()[0] == 0


def test_active_legacy_accepts_its_later_valid_precutoff_signature(env, monkeypatch):
    app, engine, _, _ = env
    old, _, value = legacy(app, engine, monkeypatch, issued=engine.legacy_cutoff - engine.legacy_ttl + 60)
    assert old.get('/api/sessions').status_code == 200
    future = engine.legacy_cutoff + 120
    monkeypatch.setattr(time, 'time', lambda: future)
    later, _, _ = legacy(app, engine, monkeypatch, csrf=value['csrf'], issued=engine.legacy_cutoff)
    assert later.get('/api/sessions').status_code == 200
    assert old.get('/api/sessions').status_code == 401


def test_password_rotation_preserves_current_rotates_csrf_and_revokes_all_other_devices(env):
    app, engine, _, _ = env
    first, h = login(app)
    copied = clone(app, first)
    other, _ = login(app)
    partner, _ = login(app, 'member2')
    before = first.get('/api/me').json['csrf']
    result = first.post('/api/profile', headers=h, json={'name': 'Updated', 'currentPassword': PASSWORD, 'password': PASSWORD + '-new'})
    assert result.status_code == 200
    assert first.get('/api/me').json['csrf'] != before
    assert first.get('/api/me').json['user']['auth_version'] == 2
    assert other.get('/api/sessions').status_code == copied.get('/api/sessions').status_code == 401
    assert partner.get('/api/me').json['user']['id'] == 'member2'
    assert first.post('/api/sessions/revoke-others', headers=h, json={}).status_code == 403
    with engine.db() as con:
        assert con.execute('SELECT count(*) FROM member_sessions WHERE owner="member1" AND revoked_at IS NULL').fetchone()[0] == 1


def test_failed_password_does_not_revoke_existing_member(env):
    app, _, _, _ = env
    client, _ = login(app)
    before = client.get_cookie('session').value
    result = client.post('/api/login', json={'username': 'member2', 'password': 'bad-password'})
    assert result.status_code == 401 and not result.headers.getlist('Set-Cookie')
    assert client.get_cookie('session').value == before
    assert client.get('/api/me').json['user']['id'] == 'member1'


@pytest.mark.parametrize('next_action', ['member2', 'logout'])
def test_delayed_real_login_response_cannot_revive_replaced_member(env, next_action):
    app, _, _, _ = env
    with delayed_server(app) as (call, ready, release, captured):
        assert call('/api/me')[0] == 200  # one browser identity before racing logins
        with ThreadPoolExecutor(max_workers=1) as pool:
            late = pool.submit(call, '/api/login', {'username': 'member1', 'password': PASSWORD}, {'X-Synthetic-Delay': '1'})
            try:
                assert ready.wait(5)
                assert call('/api/login', {'username': 'member2', 'password': PASSWORD})[0] == 200
                if next_action == 'logout':
                    csrf = call('/api/me')[1]['csrf']
                    assert call('/api/logout', {}, {'X-CSRF-Token': csrf})[0] == 200
                release.set()
                assert late.result(timeout=5)[0] == 200
                assert any(k.lower() == 'set-cookie' for k, _ in captured['headers'])
                # HTTP delivery can still install the old cookie, so availability
                # is anonymous rather than falsely claiming the new login survives.
                assert call('/api/me')[1]['user'] is None
                assert call('/api/sessions')[0] == 401
            finally:
                release.set()


@pytest.mark.parametrize('cancel', ['new-login', 'logout', 'password'])
def test_password_verification_inflight_is_cancelled_before_auth_commit(env, monkeypatch, cancel):
    import app as app_module
    app, _, _, _ = env
    client, h = login(app)
    delayed = clone(app, client)
    ready, release = threading.Event(), threading.Event()
    real_check = app_module.check_password_hash

    def check(stored, password):
        valid = real_check(stored, password)
        if request.headers.get('X-Pause-Password'):
            ready.set()
            assert release.wait(10)
        return valid

    monkeypatch.setattr(app_module, 'check_password_hash', check)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(delayed.post, '/api/login', json={'username': 'member1', 'password': PASSWORD}, headers={'X-Pause-Password': '1'})
        try:
            assert ready.wait(5)
            if cancel == 'new-login':
                login(app, 'member2', client)
            elif cancel == 'logout':
                assert client.post('/api/logout', json={}, headers=h).status_code == 200
            else:
                assert client.post('/api/profile', json={'name': 'New', 'password': PASSWORD + '-changed', 'currentPassword': PASSWORD}, headers=h).status_code == 200
            release.set()
            result = future.result(timeout=5)
            assert result.status_code in (401, 409) and not result.headers.getlist('Set-Cookie')
        finally:
            release.set()


@pytest.mark.parametrize('provider', ['google', 'microsoft'])
@pytest.mark.parametrize('mode', ['bind', 'login'])
@pytest.mark.parametrize('stage', ['tokens', 'identity'])
@pytest.mark.parametrize('cancel', ['logout', 'new-login'])
def test_oauth_after_network_rechecks_live_session_and_browser_generation(env, provider, mode, stage, cancel):
    app, _, remote, _ = env
    client, aid = bind_account(app, remote, provider)
    state = begin(client, provider, mode)
    parallel = clone(app, client)
    h = headers(parallel)
    engine = app.extensions['cloud_accounts']
    with engine.db() as con:
        before = dict(con.execute('SELECT * FROM cloud_accounts WHERE id=?', (aid,)).fetchone())
    tokens, factory = remote.tokens, remote.factory

    def cancel_now():
        if cancel == 'logout':
            assert parallel.post('/api/logout', json={}, headers=h).status_code == 200
        else:
            login(app, 'member2', parallel)

    def token_hook(*args):
        answer = tokens(*args)
        if stage == 'tokens':
            cancel_now()
        return answer

    def factory_hook(*args, **kwargs):
        provider_object = factory(*args, **kwargs)
        identity = provider_object.identity

        def lookup():
            answer = identity()
            if stage == 'identity':
                cancel_now()
            return answer

        provider_object.identity = lookup
        return provider_object

    app.config.update(OAUTH_TRANSPORT=token_hook, CLOUD_PROVIDER_FACTORY=factory_hook)
    response = finish(client, state, provider)
    assert 'auth=error' in response.location and not response.headers.getlist('Set-Cookie')
    with engine.db() as con:
        assert dict(con.execute('SELECT * FROM cloud_accounts WHERE id=?', (aid,)).fetchone()) == before
    assert client.get('/api/sessions').status_code == 401
    assert parallel.get('/api/me').json['user'] is None if cancel == 'logout' else parallel.get('/api/me').json['user']['id'] == 'member2'


@pytest.mark.parametrize('provider', ['google', 'microsoft'])
@pytest.mark.parametrize('mode', ['bind', 'login'])
def test_oauth_disconnect_during_network_does_not_recreate_account_or_login(env, provider, mode):
    app, _, remote, _ = env
    client, aid = bind_account(app, remote, provider)
    state = begin(client, provider, mode)
    parallel = clone(app, client)
    token = remote.tokens

    def disconnect(*args):
        result = token(*args)
        assert parallel.delete('/api/accounts/' + aid, json={}, headers=headers(parallel)).status_code == 200
        return result

    app.config['OAUTH_TRANSPORT'] = disconnect
    response = finish(client, state, provider)
    assert 'auth=error' in response.location and not response.headers.getlist('Set-Cookie')
    assert client.get('/api/accounts').json['accounts'] == []


@pytest.mark.parametrize('provider', ['google', 'microsoft'])
def test_legacy_oauth_state_without_auth_context_fails_without_touching_bound_tokens(env, provider):
    app, _, remote, _ = env
    client, aid = bind_account(app, remote, provider)
    state = begin(client, provider)
    engine = app.extensions['cloud_accounts']
    with engine.db() as con:
        con.execute("UPDATE cloud_oauth_states SET auth_context='' WHERE state_hash=?", (digest(state),))
        before = con.execute('SELECT tokens FROM cloud_accounts WHERE id=?', (aid,)).fetchone()[0]
    calls = len(remote.token_calls)
    assert 'session_changed' in finish(client, state, provider).location
    assert len(remote.token_calls) == calls
    with engine.db() as con:
        assert con.execute('SELECT tokens FROM cloud_accounts WHERE id=?', (aid,)).fetchone()[0] == before


def test_tv_cannot_enumerate_or_revoke_member_sessions(env):
    app, _, _, _ = env
    member, h = login(app)
    tv = app.test_client()
    pair = tv.post('/api/pair/start', json={}).json
    assert member.post('/api/pair/approve', json={'code': pair['code'], 'name': 'TV', 'focus': 'member1'}, headers=h).status_code == 200
    tv.post('/api/pair/poll', json={'secret': pair['secret']})
    assert tv.get('/api/sessions').status_code == 403
    assert tv.post('/api/sessions/revoke-others', json={}).status_code == 403
    assert member.get('/api/sessions', headers={'X-Display-Mode': 'tv'}).status_code == 401


def test_household_switch_revokes_only_original_household_and_preserves_other_browser(env):
    app, engine, _, _ = env
    current, h = login(app)
    other, _ = login(app)
    token = current.post('/api/spaces/invitations', headers=h, json={}).json['invitation']
    created = current.post('/api/spaces/redeem', json={'invitation': token, 'name': 'Synthetic Other', 'slug': 'synthetic-other',
                                                    'MEMBER1_PASSWORD': PASSWORD, 'MEMBER2_PASSWORD': PASSWORD})
    assert created.status_code == 201
    stale = clone(app, current)
    assert current.get(created.json['entry']).status_code == 303
    assert stale.get('/api/sessions').status_code == 401
    assert other.get('/api/sessions').status_code == 200
    current, ch = login(app, client=current)
    child_copy = clone(app, current)
    child_sessions = current.get('/api/sessions').json['sessions']
    assert len(child_sessions) == 1
    parent_id = other.get('/api/sessions').json['sessions'][0]['id']
    assert current.delete('/api/sessions/' + parent_id, json={}, headers=ch).status_code == 404
    assert current.get('/space/home').status_code == 303
    assert child_copy.get('/api/sessions').status_code == 401
    assert other.get('/api/sessions').status_code == 200
    with engine.db() as con:
        assert con.execute('SELECT count(*) FROM member_sessions WHERE revoked_at IS NULL').fetchone()[0] == 1


def test_lastseen_throttled_device_summary_and_sixteen_session_cap(env, monkeypatch):
    app, engine, _, _ = env
    client = app.test_client()
    client.environ_base['HTTP_USER_AGENT'] = 'SENSITIVE-RAW Mozilla Windows Edg/999 secret'
    client, _ = login(app, client=client)
    with engine.db() as con:
        row = dict(con.execute('SELECT * FROM member_sessions').fetchone())
    assert row['device'] == 'Edge · Windows' and 'SENSITIVE' not in json.dumps(row)
    assert client.get('/api/sessions').status_code == 200
    with engine.db() as con:
        assert con.execute('SELECT last_seen_at FROM member_sessions WHERE id=?', (row['id'],)).fetchone()[0] == row['last_seen_at']
    monkeypatch.setattr(time, 'time', lambda: row['last_seen_at'] + 301)
    assert client.get('/api/sessions').status_code == 200
    with engine.db() as con:
        assert con.execute('SELECT last_seen_at FROM member_sessions WHERE id=?', (row['id'],)).fetchone()[0] > row['last_seen_at']
    for _ in range(16):
        latest, _ = login(app)
    assert len(latest.get('/api/sessions').json['sessions']) == 16
    assert client.get('/api/sessions').status_code == 401
    with engine.db() as con:
        assert con.execute('SELECT count(*) FROM member_sessions WHERE revoked_at IS NOT NULL').fetchone()[0] == 1


@pytest.mark.parametrize('stale_kind', ['member', 'anonymous'])
def test_stale_cookie_household_switch_cannot_revoke_newer_member(env, stale_kind):
    app, engine, _, _ = env
    client = app.test_client()
    client.get('/api/me')
    if stale_kind == 'member':
        client, _ = login(app, client=client)
    stale = clone(app, client)
    client, _ = login(app, 'member2', client)
    with engine.db() as con:
        generation = con.execute('SELECT generation FROM member_session_browsers').fetchone()[0]
    assert stale.get('/space/home').status_code == 303
    assert client.get('/api/me').json['user']['id'] == 'member2'
    with engine.db() as con:
        assert con.execute('SELECT generation FROM member_session_browsers').fetchone()[0] == generation


@pytest.mark.parametrize('provider', ['google', 'microsoft'])
def test_anonymous_oauth_login_and_legacy_bind_upgrade_keep_expected_cookie_behavior(env, monkeypatch, provider):
    app, engine, remote, _ = env
    old, _, _ = legacy(app, engine, monkeypatch)
    remote.identities['person'] = {'subject': 'synthetic-subject', 'name': 'Fictional'}
    old_csrf = headers(old)['X-CSRF-Token']
    state = begin(old, provider)
    with old.session_transaction() as value:
        assert value['session_v'] == 1 and value['csrf'] == old_csrf
    assert finish(old, state, provider).location.endswith('auth=connected')
    assert headers(old)['X-CSRF-Token'] == old_csrf
    login_client = app.test_client()
    login_client.get('/api/me')
    state = begin(login_client, provider, 'login')
    response = finish(login_client, state, provider)
    assert response.location.endswith('auth=signed-in') and response.headers.getlist('Set-Cookie')
    assert login_client.get('/api/me').json['user']['id'] == 'member1'
    assert len(login_client.get('/api/sessions').json['sessions']) == 2


def test_space_switch_cancels_inflight_anonymous_oauth_without_revoking_account(env):
    app, _, remote, _ = env
    member, aid = bind_account(app, remote)
    anonymous = app.test_client()
    anonymous.get('/api/me')
    state = begin(anonymous, mode='login')
    parallel = clone(app, anonymous)
    tokens = remote.tokens

    def changed(*args):
        answer = tokens(*args)
        assert parallel.get('/space/home').status_code == 303
        return answer

    app.config['OAUTH_TRANSPORT'] = changed
    assert 'auth=error' in finish(anonymous, state).location
    assert anonymous.get('/api/me').json['user'] is None
    assert member.get('/api/accounts').json['accounts'][0]['id'] == aid


@pytest.mark.parametrize('provider', ['google', 'microsoft'])
def test_oauth_password_change_during_identity_preserves_new_current_session(env, provider):
    app, _, remote, _ = env
    client, aid = bind_account(app, remote, provider)
    state = begin(client, provider)
    parallel = clone(app, client)
    original = remote.factory

    def changed(*args, **kwargs):
        obj = original(*args, **kwargs)
        identity = obj.identity

        def lookup():
            answer = identity()
            assert parallel.post('/api/profile', json={'name': 'New', 'password': PASSWORD + '-new', 'currentPassword': PASSWORD}, headers=headers(parallel)).status_code == 200
            return answer

        obj.identity = lookup
        return obj

    app.config['CLOUD_PROVIDER_FACTORY'] = changed
    response = finish(client, state, provider)
    assert 'auth=error' in response.location and not response.headers.getlist('Set-Cookie')
    assert parallel.get('/api/me').json['user']['auth_version'] == 2
    assert client.get('/api/sessions').status_code == 401
    assert parallel.get('/api/accounts').json['accounts'][0]['id'] == aid


@pytest.mark.parametrize('provider', ['google', 'microsoft'])
def test_new_write_authorization_cancels_older_inflight_bind_without_losing_permissions(env, provider):
    from cloud_accounts import PROVIDERS, calendar_write_allowed
    app, _, remote, _ = env
    client, aid = bind_account(app, remote, provider)
    old_state = begin(client, provider)
    newer = clone(app, client)
    remote.identities['upgraded'] = {'subject': 'synthetic-subject', 'name': 'Fictional'}
    original = remote.tokens

    def tokens(name, params):
        answer = original(name, params)
        if params['code'] == 'person':
            upgrade = newer.post('/api/calendar-publish/authorize', json={'accountId': aid}, headers=headers(newer))
            assert upgrade.status_code == 200, upgrade.json
            new_state = parse_qs(urlsplit(upgrade.json['url']).query)['state'][0]
            response = newer.get('/auth/' + provider + '/callback', query_string={'state': new_state, 'code': 'upgraded'})
            assert response.location.endswith('auth=connected')
        else:
            write_scope = 'Calendars.ReadWrite' if provider == 'microsoft' else 'https://www.googleapis.com/auth/calendar.events'
            answer['scope'] = ' '.join(PROVIDERS[provider]['sync'] + [write_scope])
        return answer

    app.config['OAUTH_TRANSPORT'] = tokens
    response = finish(client, old_state, provider)
    assert 'auth=error' in response.location and not response.headers.getlist('Set-Cookie')
    cloud = app.extensions['cloud_accounts']
    with cloud.db() as con:
        kept = cloud.decrypt(con.execute('SELECT tokens FROM cloud_accounts WHERE id=?', (aid,)).fetchone()[0])
    assert kept['access_token'] == 'upgraded' and calendar_write_allowed(provider, kept['scope'])
    assert client.get('/api/me').json['user']['id'] == 'member1'


@pytest.mark.parametrize('provider', ['google', 'microsoft'])
def test_failed_new_authorization_keeps_member_live_and_other_browser_authorization_valid(env, provider):
    app, _, remote, _ = env
    client, aid = bind_account(app, remote, provider)
    separate, _ = login(app)
    independent_state = begin(separate, provider)
    old_state = begin(client, provider)
    new_state = begin(client, provider)
    denied = client.get('/auth/' + provider + '/callback', query_string={'state': new_state, 'error': 'access_denied'})
    assert 'provider_denied' in denied.location
    assert client.get('/api/me').json['user']['id'] == 'member1'
    before = len(remote.token_calls)
    assert 'session_changed' in finish(client, old_state, provider).location
    assert len(remote.token_calls) == before
    assert finish(separate, independent_state, provider).location.endswith('auth=connected')
    assert client.get('/api/accounts').json['accounts'][0]['id'] == aid


@pytest.mark.parametrize('operation', ['connection', 'revocation'])
def test_member_auth_missing_database_never_creates_replacement(env, operation):
    app, engine, _, _ = env
    client, _ = login(app)
    raw = client.get_cookie('session').value
    path = Path(engine.path)
    saved = path.with_suffix('.saved')
    path.rename(saved)
    original = saved.read_bytes()
    with pytest.raises(sqlite3.OperationalError, match='unable to open database file'):
        if operation == 'connection':
            with engine.db():
                pytest.fail('Missing authentication storage was opened')
        else:
            engine.revoke_cookie(raw)
    assert not path.exists() and saved.read_bytes() == original


def test_member_auth_rw_open_protects_removal_after_an_existence_check(env, monkeypatch):
    app, engine, _, _ = env
    client, _ = login(app)
    raw = client.get_cookie('session').value
    path = Path(engine.path)
    saved = path.with_suffix('.saved')
    connect = sqlite3.connect
    calls = []

    def race(database, *args, **kwargs):
        calls.append(database)
        assert database == path.resolve().as_uri() + '?mode=rw'
        assert kwargs.get('uri') is True
        assert path.is_file()  # Earlier routing/storage checks can succeed.
        path.rename(saved)    # Removal immediately before the actual SQLite open.
        return connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, 'connect', race)
    with pytest.raises(sqlite3.OperationalError, match='unable to open database file'):
        engine.revoke_cookie(raw)
    assert len(calls) == 1 and saved.is_file() and not path.exists()
