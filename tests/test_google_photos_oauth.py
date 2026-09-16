"""Real HTTP/member sessions and temporary SQLite; all Google responses synthetic."""
import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlsplit

import pytest

from app import create_app
from cloud_accounts import GOOGLE_PHOTOS_SCOPE, AccountBusy, photos_allowed
from cloud_providers import ProviderError
from test_cloud_accounts import configured, login, begin, finish, bind, select


PICKER = GOOGLE_PHOTOS_SCOPE
CAL = 'https://www.googleapis.com/auth/calendar.readonly'
WRITE = 'https://www.googleapis.com/auth/calendar.events'
TASKS = 'https://www.googleapis.com/auth/tasks'
SYNC = CAL + ' ' + TASKS
COMBINED = PICKER + ' ' + SYNC + ' ' + WRITE


def response_tokens(app, remote, scope=PICKER, **changes):
    def transport(provider, params):
        result = remote.tokens(provider, params)
        if scope is not None:
            result['scope'] = scope
        result.update(changes)
        return result
    app.config['OAUTH_TRANSPORT'] = transport
    return transport


def photos_begin(c, h, aid=None):
    result = c.post('/api/accounts/google-photos/bind', json={} if aid is None else {'accountId': aid}, headers=h)
    assert result.status_code == 200, result.json
    return parse_qs(urlsplit(result.json['url']).query)


def identity(remote, code='photo-code', subject='google-subject'):
    remote.identities[code] = {'subject': subject, 'name': 'Synthetic Google', 'email': 'same@example.test'}
    return code


def bind_photos(app, remote, number=1, subject='google-subject', scope=PICKER):
    c, h = login(app, number)
    response_tokens(app, remote, scope)
    code = identity(remote, subject=subject)
    params = photos_begin(c, h)
    result = finish(c, params['state'][0], 'google', code)
    assert result.location.endswith('/?auth=photos-connected'), result.location
    aid = c.get('/api/accounts').json['accounts'][0]['id']
    return c, h, aid


def snapshot(engine, aid):
    with engine.db() as con:
        row = con.execute('SELECT * FROM cloud_accounts WHERE id=?', (aid,)).fetchone()
        return dict(row) if row else None


def expire(engine, aid, **changes):
    a = engine.account(aid)
    tokens = engine.decrypt(a['tokens']) | {'expires_at': 0} | changes
    with engine.db() as con:
        con.execute('UPDATE cloud_accounts SET tokens=? WHERE id=?', (engine.encrypt(tokens), aid))
    return tokens


def clone(app, client):
    other = app.test_client()
    for cookie in client._cookies.values():
        other.set_cookie(cookie.key, cookie.value, domain=cookie.domain, path=cookie.path)
    return other


def test_photos_request_is_explicit_minimal_pkce_offline_and_browser_bound(configured):
    app, remote, _ = configured
    c, h = login(app)
    params = photos_begin(c, h)
    assert set(params['scope'][0].split()) == {'openid', 'email', 'profile', PICKER}
    assert params['include_granted_scopes'] == ['true'] and params['access_type'] == ['offline']
    assert params['prompt'] == ['consent'] and params['response_type'] == ['code']
    assert params['redirect_uri'] == ['http://localhost/auth/google/callback']
    engine = app.extensions['cloud_accounts']
    with engine.db() as con:
        state = dict(con.execute('SELECT * FROM cloud_oauth_states').fetchone())
    verifier = engine.decrypt(state['verifier'])
    assert params['code_challenge_method'] == ['S256']
    assert params['code_challenge'][0] == base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    assert state['mode'] == 'bind_photos' and state['owner'] == 'member1'
    assert 0 < state['expires'] - time.time() <= 600
    assert params['state'][0] not in json.dumps(state) and verifier not in json.dumps(state)
    other, _ = login(app)
    assert 'invalid_state' in finish(other, params['state'][0], 'google').location
    assert 'invalid_state' in finish(c, params['state'][0], 'microsoft').location
    response_tokens(app, remote)
    code = identity(remote)
    assert finish(c, params['state'][0], 'google', code).location.endswith('auth=photos-connected')
    assert remote.token_calls[-1][1]['code_verifier'] == verifier
    calls = len(remote.token_calls)
    assert 'invalid_state' in finish(c, params['state'][0], 'google', code).location
    assert len(remote.token_calls) == calls


@pytest.mark.parametrize('payload', [{'accountId': None}, {'accountId': 2}, {'accountId': []}, {'accountId': ''},
                                     {'accountId': 'x'*129}, {'accountId': '../x'}, {'provider': 'google'},
                                     {'scope': PICKER}, {'owner': 'member2'}, [], None])
def test_photos_bind_strict_body(configured, payload):
    app, remote, _ = configured
    c, h = login(app)
    if payload is None:
        result = c.post('/api/accounts/google-photos/bind', data='null', content_type='application/json', headers=h)
    else:
        result = c.post('/api/accounts/google-photos/bind', json=payload, headers=h)
    assert result.status_code == 400
    assert remote.token_calls == []


def test_bind_requires_member_csrf_same_origin_and_rejects_tv(configured):
    app, remote, _ = configured
    anon = app.test_client()
    assert anon.post('/api/accounts/google-photos/bind', json={}).status_code == 401
    c, h = login(app)
    assert c.post('/api/accounts/google-photos/bind', json={}).status_code == 403
    assert c.post('/api/accounts/google-photos/bind', json={}, headers={**h, 'Origin': 'https://evil.test'}).status_code == 403
    assert c.post('/api/accounts/google-photos/bind', json={}, headers={**h, 'Host': 'evil.test'}).status_code in (400, 401)
    pair = anon.post('/api/pair/start', json={}).json
    assert c.post('/api/pair/approve', headers=h, json={'code': pair['code'], 'name': 'TV', 'focus': 'member1'}).status_code == 200
    anon.post('/api/pair/poll', json={'secret': pair['secret']})
    assert anon.post('/api/accounts/google-photos/bind', json={}).status_code == 403
    assert anon.get('/api/accounts').status_code == 403
    assert remote.token_calls == []


@pytest.mark.parametrize('scope', [None, '', 'openid email profile', SYNC, PICKER + '.extra', PICKER.upper(), [PICKER]])
def test_new_authorization_requires_actual_exact_picker_scope(configured, scope):
    app, remote, _ = configured
    c, h = login(app)
    response_tokens(app, remote, scope)
    code = identity(remote)
    p = photos_begin(c, h)
    assert 'insufficient_permissions' in finish(c, p['state'][0], 'google', code).location
    assert c.get('/api/accounts').json['accounts'] == []
    assert not photos_allowed('google', scope)


@pytest.mark.parametrize('refresh', [None, '', [], {'secret': 'bad'}, 99])
def test_new_photos_binding_requires_usable_offline_grant(configured, refresh):
    app, remote, _ = configured
    c, h = login(app)
    response_tokens(app, remote, refresh_token=refresh)
    code = identity(remote)
    p = photos_begin(c, h)
    assert 'missing_refresh_token' in finish(c, p['state'][0], 'google', code).location
    assert c.get('/api/accounts').json['accounts'] == []


def test_photo_only_capability_safe_projection_no_sync_discovery_and_restart(configured):
    app, remote, cfg = configured
    c, h, aid = bind_photos(app, remote)
    engine = app.extensions['cloud_accounts']
    public = c.get('/api/accounts').json['accounts'][0]
    assert public['capabilities'] == {'photos': True} and public['sources'] == [] and not public['needsReauth']
    assert set(public) == {'id', 'provider', 'name', 'email', 'needsReauth', 'capabilities', 'sources'}
    assert 'photo-code' not in json.dumps(public) and PICKER not in json.dumps(public)
    assert 'photo-code' not in snapshot(engine, aid)['tokens']
    assert engine.photos_access_token(aid, 'member1') == 'photo-code'
    app.config['CLOUD_PROVIDER_FACTORY'] = lambda *a, **k: pytest.fail('photo-only binding cannot discover sync sources')
    assert c.get('/api/accounts/' + aid + '/sources').status_code == 403
    assert c.post('/api/accounts/' + aid + '/sources', headers=h, json={'sources': [{'kind': 'calendar', 'remoteId': 'cal-1', 'owner': 'member1'}]}).status_code == 403
    assert c.post('/api/accounts/' + aid + '/sources', headers=h, json={'sources': []}).status_code == 200
    assert not c.get('/api/accounts').json['accounts'][0]['needsReauth']
    restarted = create_app(cfg)
    assert restarted.extensions['cloud_accounts'].photos_access_token(aid, 'member1') == 'photo-code'
    other, oh = login(app, 2)
    assert other.get('/api/accounts').json['accounts'] == []
    assert other.post('/api/accounts/google-photos/bind', json={'accountId': aid}, headers=oh).status_code == 404
    with pytest.raises(ProviderError) as error:
        engine.photos_access_token(aid, 'member2')
    assert error.value.status == 404


def test_upgrade_same_account_preserves_every_source_and_old_refresh(configured):
    app, remote, _ = configured
    response_tokens(app, remote, SYNC + ' ' + WRITE)
    c, h, aid = bind(app, remote, provider='google')
    select(c, h, aid, tasks=True, calendar=True)
    engine = app.extensions['cloud_accounts']
    with engine.db() as con:
        con.execute("UPDATE cloud_sources SET error='synthetic-old-error',failures=2,next_attempt=12345")
        sources = [dict(r) for r in con.execute('SELECT * FROM cloud_sources ORDER BY id')]
    old = engine.decrypt(snapshot(engine, aid)['tokens'])
    assert c.get('/api/accounts').json['accounts'][0]['capabilities'] == {'photos': False}
    response_tokens(app, remote, COMBINED, refresh_token=None)
    code = identity(remote, subject='person-1-google')
    p = photos_begin(c, h, aid)
    assert set(p['scope'][0].split()) == {'openid', 'email', 'profile', PICKER}
    assert finish(c, p['state'][0], 'google', code).location.endswith('auth=photos-connected')
    assert engine.decrypt(snapshot(engine, aid)['tokens'])['refresh_token'] == old['refresh_token']
    with engine.db() as con:
        assert [dict(r) for r in con.execute('SELECT * FROM cloud_sources ORDER BY id')] == sources
        assert con.execute('SELECT count(*) FROM cloud_accounts').fetchone()[0] == 1
    assert c.get('/api/accounts').json['accounts'][0]['id'] == aid
    assert c.get('/api/accounts').json['accounts'][0]['capabilities']['photos']
    assert c.get('/api/accounts/' + aid + '/sources').status_code == 200


@pytest.mark.parametrize('old_scope,new_scope,sources', [
    (SYNC, PICKER, False), (SYNC + ' ' + WRITE, PICKER + ' ' + SYNC, False),
    (SYNC, PICKER + ' ' + CAL, False), (SYNC, PICKER + ' ' + TASKS, False),
    (None, PICKER, True),
])
def test_upgrade_rejects_lost_sync_permissions_without_replacing_anything(configured, old_scope, new_scope, sources):
    app, remote, _ = configured
    response_tokens(app, remote, old_scope)
    c, h, aid = bind(app, remote, provider='google')
    if sources:
        select(c, h, aid, calendar=True)
    engine = app.extensions['cloud_accounts']
    before = snapshot(engine, aid)
    with engine.db() as con:
        before_sources = [dict(r) for r in con.execute('SELECT * FROM cloud_sources')]
    response_tokens(app, remote, new_scope)
    code = identity(remote, subject='person-1-google')
    p = photos_begin(c, h, aid)
    assert 'insufficient_permissions' in finish(c, p['state'][0], 'google', code).location
    assert snapshot(engine, aid) == before
    with engine.db() as con:
        assert [dict(r) for r in con.execute('SELECT * FROM cloud_sources')] == before_sources


def test_full_calendar_scope_covers_prior_read_and_write(configured):
    app, remote, _ = configured
    c, h, aid = bind_photos(app, remote, scope=COMBINED)
    response_tokens(app, remote, PICKER + ' https://www.googleapis.com/auth/calendar ' + TASKS)
    p = photos_begin(c, h, aid)
    assert finish(c, p['state'][0], 'google', 'photo-code').location.endswith('auth=photos-connected')


@pytest.mark.parametrize('kind', ['wrong_subject', 'other_member', 'microsoft', 'wrong_client', 'unknown'])
def test_upgrade_identity_is_subject_and_owned_account_not_email(configured, kind):
    app, remote, _ = configured
    if kind == 'unknown':
        c, h = login(app)
        assert c.post('/api/accounts/google-photos/bind', headers=h, json={'accountId': 'missing'}).status_code == 404
        return
    c, h, aid = bind(app, remote, number=2 if kind == 'other_member' else 1,
                     provider='microsoft' if kind == 'microsoft' else 'google')
    engine = app.extensions['cloud_accounts']
    before = snapshot(engine, aid)
    if kind == 'other_member':
        c, h = login(app)
    if kind == 'wrong_client':
        app.config['GOOGLE_CLIENT_ID'] = 'replacement-client'
    if kind != 'wrong_subject':
        result = c.post('/api/accounts/google-photos/bind', headers=h, json={'accountId': aid})
        assert result.status_code == (404 if kind == 'other_member' else 400)
    else:
        response_tokens(app, remote, COMBINED)
        code = identity(remote, subject='different-subject-with-same-email')
        p = photos_begin(c, h, aid)
        assert 'provider_error' in finish(c, p['state'][0], 'google', code).location
    assert snapshot(engine, aid) == before


def test_optional_account_id_still_cannot_steal_other_members_identity(configured):
    app, remote, _ = configured
    _, _, aid = bind_photos(app, remote, number=2)
    c, h = login(app)
    p = photos_begin(c, h)
    assert 'already_bound' in finish(c, p['state'][0], 'google', 'photo-code').location
    assert app.extensions['cloud_accounts'].account(aid)['owner'] == 'member2'


@pytest.mark.parametrize('change', ['logout', 'member_switch', 'household_switch', 'disconnect', 'new_flow', 'revoke', 'password'])
def test_callback_rechecks_session_and_account_after_network(configured, change):
    app, remote, _ = configured
    c, h, aid = bind_photos(app, remote)
    engine = app.extensions['cloud_accounts']
    p = photos_begin(c, h, aid)
    parallel = clone(app, c)
    before = snapshot(engine, aid)
    transport = app.config['OAUTH_TRANSPORT']

    def changed(provider, params):
        result = transport(provider, params)
        if change == 'logout':
            assert parallel.post('/api/logout', headers=h, json={}).status_code == 200
        elif change == 'member_switch':
            assert parallel.post('/api/login', json={'username': 'member2', 'password': 'testing-password-two'}).status_code == 200
        elif change == 'household_switch':
            assert parallel.get('/space/home').status_code == 303
        elif change == 'disconnect':
            assert parallel.delete('/api/accounts/' + aid, headers=h, json={}).status_code == 200
        elif change == 'new_flow':
            photos_begin(parallel, h, aid)
        elif change == 'revoke':
            with engine.db() as con:
                con.execute('UPDATE member_sessions SET revoked_at=?', (time.time(),))
        else:
            with engine.db() as con:
                con.execute("UPDATE users SET auth_version=auth_version+1 WHERE id='member1'")
        return result

    app.config['OAUTH_TRANSPORT'] = changed
    result = finish(c, p['state'][0], 'google', 'photo-code')
    assert 'auth=error' in result.location and not result.headers.getlist('Set-Cookie')
    assert snapshot(engine, aid) == (None if change == 'disconnect' else before)


@pytest.mark.parametrize('scope', [None, COMBINED])
def test_helper_refresh_retains_confirmed_scope_when_omitted_and_never_requests_scope(configured, scope):
    app, remote, _ = configured
    c, _, aid = bind_photos(app, remote, scope=COMBINED)
    engine = app.extensions['cloud_accounts']
    old = expire(engine, aid)
    response_tokens(app, remote, scope, access_token='fresh-access', refresh_token='rotated-refresh')
    assert engine.photos_access_token(aid, 'member1') == 'fresh-access'
    request = remote.token_calls[-1][1]
    assert request['refresh_token'] == old['refresh_token'] and 'scope' not in request
    current = engine.decrypt(snapshot(engine, aid)['tokens'])
    assert current['scope'] == COMBINED and current['refresh_token'] == 'rotated-refresh'
    assert c.get('/api/accounts').json['accounts'][0]['capabilities']['photos']
    calls = len(remote.token_calls)
    assert engine.photos_access_token(aid, 'member1') == 'fresh-access'
    assert len(remote.token_calls) == calls


@pytest.mark.parametrize('scope', ['', SYNC, None, [PICKER]])
def test_helper_does_not_invent_initial_grant(configured, scope):
    app, remote, _ = configured
    _, _, aid = bind(app, remote, provider='google')
    engine = app.extensions['cloud_accounts']
    expire(engine, aid, scope=scope)
    calls = len(remote.token_calls)
    with pytest.raises(ProviderError) as error:
        engine.photos_access_token(aid, 'member1')
    assert error.value.status == 403 and len(remote.token_calls) == calls


@pytest.mark.parametrize('scope', ['', SYNC, [PICKER]])
def test_explicit_refresh_downgrade_is_saved_but_not_used(configured, scope):
    app, remote, _ = configured
    c, _, aid = bind_photos(app, remote)
    engine = app.extensions['cloud_accounts']
    expire(engine, aid)
    response_tokens(app, remote, scope, access_token='narrow-token')
    with pytest.raises(ProviderError) as error:
        engine.photos_access_token(aid, 'member1')
    assert error.value.status == 403
    assert engine.decrypt(snapshot(engine, aid)['tokens'])['scope'] == scope
    assert c.get('/api/accounts').json['accounts'][0]['capabilities'] == {'photos': False}


@pytest.mark.parametrize('change', ['delete', 'owner', 'subject', 'client', 'tokens', 'reauth', 'config'])
def test_helper_checks_account_again_after_refresh_and_cannot_resurrect(configured, change):
    app, remote, _ = configured
    _, _, aid = bind_photos(app, remote)
    engine = app.extensions['cloud_accounts']
    expire(engine, aid)
    transport = app.config['OAUTH_TRANSPORT']
    after = []

    def changed(provider, params):
        result = transport(provider, params)
        with engine.db() as con:
            if change == 'delete':
                con.execute('DELETE FROM cloud_accounts WHERE id=?', (aid,))
            elif change == 'config':
                app.config['GOOGLE_CLIENT_SECRET'] = 'changed-secret'
            else:
                column, value = {'owner': ('owner', 'member2'), 'subject': ('subject', 'reassigned'),
                                 'client': ('client_id', 'new-client'), 'tokens': ('tokens', engine.encrypt({'access_token': 'replacement'})),
                                 'reauth': ('needs_reauth', 1)}[change]
                con.execute(f'UPDATE cloud_accounts SET {column}=? WHERE id=?', (value, aid))
        after.append(snapshot(engine, aid))
        return result

    app.config['OAUTH_TRANSPORT'] = changed
    with pytest.raises(ProviderError) as error:
        engine.photos_access_token(aid, 'member1')
    assert error.value.status == (404 if change in ('delete', 'owner') else 409)
    assert snapshot(engine, aid) == after[0]


def test_helper_lock_blocks_disconnect_and_parallel_refresh(configured):
    app, remote, _ = configured
    c, h, aid = bind_photos(app, remote)
    engine = app.extensions['cloud_accounts']
    expire(engine, aid)
    calls = len(remote.token_calls)
    with engine.lock(aid):
        with pytest.raises(AccountBusy):
            engine.photos_access_token(aid, 'member1')
        assert c.delete('/api/accounts/' + aid, headers=h, json={}).status_code == 409
    assert len(remote.token_calls) == calls and engine.account(aid)
    transport = app.config['OAUTH_TRANSPORT']

    def locked(provider, params):
        assert c.delete('/api/accounts/' + aid, headers=h, json={}).status_code == 409
        with pytest.raises(AccountBusy):
            engine.photos_access_token(aid, 'member1')
        return transport(provider, params)

    app.config['OAUTH_TRANSPORT'] = locked
    assert engine.photos_access_token(aid, 'member1') == 'photo-code'


@pytest.mark.parametrize('owner', [None, '', 0, [], 'member2'])
def test_helper_requires_explicit_owner(configured, owner):
    app, remote, _ = configured
    _, _, aid = bind_photos(app, remote)
    with pytest.raises(ProviderError) as error:
        app.extensions['cloud_accounts'].photos_access_token(aid, owner)
    assert error.value.status == 404


def test_photo_account_can_still_sign_in_without_replacing_grants(configured):
    app, remote, _ = configured
    _, _, aid = bind_photos(app, remote)
    engine = app.extensions['cloud_accounts']
    before = snapshot(engine, aid)
    c = app.test_client()
    p = parse_qs(urlsplit(c.get('/auth/google/login').location).query)
    response_tokens(app, remote, 'openid email profile')
    assert finish(c, p['state'][0], 'google', 'photo-code').location.endswith('auth=signed-in')
    assert snapshot(engine, aid) == before
    assert c.get('/api/me').json['user']['id'] == 'member1'


def test_ordinary_sync_upgrade_of_photo_account_still_works(configured):
    app, remote, _ = configured
    c, h, aid = bind_photos(app, remote)
    response_tokens(app, remote, COMBINED)
    p = begin(c, h, 'google')
    assert finish(c, p['state'][0], 'google', 'photo-code').location.endswith('auth=connected')
    select(c, h, aid, tasks=True, calendar=True)
    assert c.get('/api/accounts').json['accounts'][0]['capabilities']['photos']


def test_provider_failures_do_not_expose_credentials_or_replace_account(configured, caplog):
    app, remote, _ = configured
    c, h, aid = bind_photos(app, remote)
    engine = app.extensions['cloud_accounts']
    before = snapshot(engine, aid)
    p = photos_begin(c, h, aid)
    response_tokens(app, remote, error='invalid_grant', error_description='SYNTHETIC_SECRET_ECHO')
    result = finish(c, p['state'][0], 'google', 'photo-code')
    assert 'reason=invalid_grant' in result.location
    assert snapshot(engine, aid) == before
    assert 'SYNTHETIC_SECRET_ECHO' not in caplog.text + result.get_data(as_text=True)
    assert 'secret-google' not in caplog.text and 'refresh-photo-code' not in caplog.text


def test_household_routing_keeps_accounts_scopes_states_and_keys_isolated(configured):
    app, remote, _ = configured
    c, h, aid = bind_photos(app, remote)
    token = c.post('/api/spaces/invitations', headers=h, json={}).json['invitation']
    public = app.test_client()
    created = public.post('/api/spaces/redeem', json={'invitation': token, 'name': 'Synthetic Family', 'slug': 'photos-family',
                                                    'MEMBER1_PASSWORD': 'second-home-password-one', 'MEMBER2_PASSWORD': 'second-home-password-two'})
    assert created.status_code == 201
    platform = app.extensions['household_platform']
    household = next(x for x in platform.households() if x['slug'] == 'photos-family')
    child = platform.child(household)
    child.config.update(GOOGLE_CLIENT_ID=app.config['GOOGLE_CLIENT_ID'], GOOGLE_CLIENT_SECRET=app.config['GOOGLE_CLIENT_SECRET'],
                        CLOUD_PROVIDER_FACTORY=remote.factory)
    response_tokens(child, remote)
    assert public.get(created.json['entry']).status_code == 303
    assert public.post('/api/login', json={'username': 'member1', 'password': 'second-home-password-one'}).status_code == 200
    ph = {'X-CSRF-Token': public.get('/api/me').json['csrf']}
    assert public.get('/api/accounts').json['accounts'] == []
    assert public.post('/api/accounts/google-photos/bind', headers=ph, json={'accountId': aid}).status_code == 404
    p = photos_begin(c, h, aid)
    assert 'invalid_state' in finish(public, p['state'][0], 'google', 'photo-code').location
    q = photos_begin(public, ph)
    assert finish(public, q['state'][0], 'google', 'photo-code').location.endswith('auth=photos-connected')
    other_id = public.get('/api/accounts').json['accounts'][0]['id']
    assert other_id != aid
    child_engine = child.extensions['cloud_accounts']
    assert child_engine.photos_access_token(other_id, 'member1') == 'photo-code'
    with pytest.raises(ProviderError):
        child_engine.photos_access_token(aid, 'member1')
    with pytest.raises(ProviderError):
        child_engine.decrypt(app.extensions['cloud_accounts'].account(aid)['tokens'])
    assert finish(c, p['state'][0], 'google', 'photo-code').location.endswith('auth=photos-connected')
    assert [a['id'] for a in c.get('/api/accounts').json['accounts']] == [aid]


@pytest.mark.parametrize('mutation', ['expired', 'reauth', 'client', 'missing_secret', 'unreadable'])
def test_expired_state_and_invalid_account_configuration_fail_closed(configured, mutation):
    app, remote, _ = configured
    c, h, aid = bind_photos(app, remote)
    engine = app.extensions['cloud_accounts']
    if mutation == 'expired':
        p = photos_begin(c, h, aid)
        with engine.db() as con:
            con.execute('UPDATE cloud_oauth_states SET expires=0')
        calls = len(remote.token_calls)
        assert 'invalid_state' in finish(c, p['state'][0], 'google', 'photo-code').location
        assert len(remote.token_calls) == calls
        return
    if mutation == 'reauth':
        with engine.db() as con:
            con.execute('UPDATE cloud_accounts SET needs_reauth=1 WHERE id=?', (aid,))
    elif mutation == 'client':
        app.config['GOOGLE_CLIENT_ID'] = 'changed-client'
    elif mutation == 'missing_secret':
        app.config['GOOGLE_CLIENT_SECRET'] = ''
    else:
        with engine.db() as con:
            con.execute("UPDATE cloud_accounts SET tokens='invalid-ciphertext' WHERE id=?", (aid,))
    calls = len(remote.token_calls)
    with pytest.raises(ProviderError) as error:
        engine.photos_access_token(aid, 'member1')
    assert error.value.status == 401 and error.value.reauth
    assert len(remote.token_calls) == calls
    if mutation == 'unreadable':
        account = c.get('/api/accounts').json['accounts'][0]
        assert account['needsReauth'] and not account['capabilities']['photos']


def test_account_cap_and_bind_rate_limit_remain_bounded(configured):
    app, remote, _ = configured
    c, h = login(app)
    response_tokens(app, remote)
    for i in range(5):
        code = identity(remote, code='code-' + str(i), subject='subject-' + str(i))
        p = photos_begin(c, h)
        result = finish(c, p['state'][0], 'google', code)
        if i < 4:
            assert result.location.endswith('auth=photos-connected')
        else:
            assert 'account_limit' in result.location
    assert len(c.get('/api/accounts').json['accounts']) == 4
    for _ in range(15):
        photos_begin(c, h)
    assert c.post('/api/accounts/google-photos/bind', json={}, headers=h).status_code == 429


def test_refresh_provider_error_preserves_account_and_is_sanitized(configured):
    app, remote, _ = configured
    _, _, aid = bind_photos(app, remote)
    engine = app.extensions['cloud_accounts']
    expire(engine, aid)
    before = snapshot(engine, aid)
    response_tokens(app, remote, error='invalid_grant', error_description='SYNTHETIC_REFRESH_ECHO')
    with pytest.raises(ProviderError) as error:
        engine.photos_access_token(aid, 'member1')
    assert error.value.status == 401 and error.value.reauth
    assert 'SYNTHETIC_REFRESH_ECHO' not in str(error.value)
    assert snapshot(engine, aid) == before


def test_same_subject_refresh_lock_blocks_callback_commit(configured):
    app, remote, _ = configured
    c, h, aid = bind_photos(app, remote)
    engine = app.extensions['cloud_accounts']
    before = snapshot(engine, aid)
    p = photos_begin(c, h, aid)
    with engine.lock(aid):
        assert 'provider_error' in finish(c, p['state'][0], 'google', 'photo-code').location
    assert snapshot(engine, aid) == before
