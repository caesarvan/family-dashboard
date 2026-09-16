"""Real member sessions, SQLite transactions and HTTP with synthetic cloud reads."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import re
import socket
import threading
import time

import pytest

from cloud_providers import ProviderError
from test_cloud_accounts import bind, configured, login, select


TASK = {'kind': 'tasks', 'remoteId': 'list-1', 'owner': 'shared', 'primary': True}
CAL = {'kind': 'calendar', 'remoteId': 'cal-1', 'owner': 'member1', 'primary': False}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Source version tests must not contact external services')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)


def path(aid):
    return f'/api/accounts/{aid}/sources'


def account(client, aid):
    response = client.get('/api/accounts')
    assert response.status_code == 200, response.json
    return next(row for row in response.json['accounts'] if row['id'] == aid)


def post(client, headers, aid, choices, version):
    return client.post(path(aid), headers=headers, json={'sources': choices, 'selectionVersion': version})


def snapshot(engine):
    with engine.db() as con:
        return {table: [tuple(row) for row in con.execute(f'SELECT * FROM {table} ORDER BY 1')]
                for table in ('cloud_accounts', 'cloud_sources', 'cloud_items', 'cloud_writes', 'entities', 'settings')}


def revoke(engine, mode='revoke'):
    with engine.db() as con:
        if mode == 'generation':
            con.execute('UPDATE member_session_browsers SET generation=generation+1')
        elif mode == 'auth_version':
            con.execute("UPDATE users SET auth_version=auth_version+1 WHERE id='member1'")
        elif mode == 'expire':
            con.execute('UPDATE member_sessions SET expires_at=0')
        else:
            con.execute('UPDATE member_sessions SET revoked_at=?', (time.time(),))


def discovery_hook(app, callback):
    original = app.config['CLOUD_PROVIDER_FACTORY']

    def factory(*args, **kwargs):
        provider = original(*args, **kwargs)
        read = provider.list_sources

        def wrapped():
            callback()
            return read()

        provider.list_sources = wrapped
        return provider

    app.config['CLOUD_PROVIDER_FACTORY'] = factory


def test_two_devices_stale_full_replacement_preserves_winner(configured):
    app, remote, _ = configured
    first, h1, aid = bind(app, remote)
    second, h2 = login(app)
    initial = account(first, aid)['selectionVersion']
    assert re.fullmatch('[0-9a-f]{64}', initial)
    assert second.get(path(aid)).json['selectionVersion'] == initial
    saved = post(first, h1, aid, [TASK, CAL], initial)
    assert saved.status_code == 200 and saved.json['queued'] is True
    engine = app.extensions['cloud_accounts']
    winner = snapshot(engine)
    conflict = post(second, h2, aid, [CAL], initial)
    assert conflict.status_code == 409 and conflict.json['code'] == 'selection_conflict'
    assert snapshot(engine) == winner
    refreshed = second.get(path(aid)).json
    assert saved.json['selectionVersion'] == refreshed['selectionVersion'] != initial
    applied = post(second, h2, aid, [CAL], refreshed['selectionVersion'])
    assert applied.status_code == 200
    assert [row['kind'] for row in account(first, aid)['sources']] == ['calendar']


def test_compare_occurs_after_slow_discovery_and_before_any_selection_write(configured):
    app, remote, _ = configured
    client, headers, aid = bind(app, remote)
    select(client, headers, aid, calendar=True)
    version = account(client, aid)['selectionVersion']
    engine = app.extensions['cloud_accounts']
    entered, release = threading.Event(), threading.Event()

    def hold():
        entered.set()
        assert release.wait(10)

    discovery_hook(app, hold)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(post, client, headers, aid, [TASK], version)
        try:
            assert entered.wait(10)
            # Independent SQLite writer commits a competing owner selection while
            # the first HTTP request is waiting on the provider.
            with engine.db() as con:
                con.execute('BEGIN IMMEDIATE')
                con.execute("UPDATE cloud_sources SET owner='shared' WHERE account_id=? AND kind='calendar'", (aid,))
            winner = snapshot(engine)
        finally:
            release.set()
        response = future.result(timeout=10)
    assert response.status_code == 409 and response.json['code'] == 'selection_conflict'
    assert snapshot(engine) == winner


def test_progress_is_not_configuration_and_remove_readd_changes_local_id(configured):
    app, remote, cfg = configured
    client, headers, aid = bind(app, remote)
    select(client, headers, aid, calendar=True)
    old = account(client, aid)
    engine = app.extensions['cloud_accounts']
    with engine.db() as con:
        con.execute("UPDATE cloud_sources SET last_success='2026-09-17T00:00:00Z',error='temporary',failures=2,next_attempt=123,name='Renamed remotely' WHERE account_id=?", (aid,))
    assert account(client, aid)['selectionVersion'] == old['selectionVersion']
    assert client.get(path(aid)).json['selectionVersion'] == old['selectionVersion']
    removed = post(client, headers, aid, [], old['selectionVersion'])
    assert removed.status_code == 200 and removed.json['queued'] is False
    recreated = post(client, headers, aid, [TASK, CAL], removed.json['selectionVersion'])
    fresh = account(client, aid)
    assert recreated.status_code == 200 and fresh['selectionVersion'] != old['selectionVersion']
    assert not {row['id'] for row in old['sources']} & {row['id'] for row in fresh['sources']}
    assert post(client, headers, aid, [], old['selectionVersion']).json['code'] == 'selection_conflict'
    # A new application instance reads the same persisted configuration digest.
    from app import create_app
    reopened = create_app(cfg)
    assert reopened.extensions['cloud_accounts'].accounts_json('member1')[0]['selectionVersion'] == fresh['selectionVersion']


@pytest.mark.parametrize('value', [None, '', 5, [], {}, 'A' * 64, 'a' * 63, 'a' * 65, 'a' * 64 + '\n'])
def test_explicit_malformed_versions_are_rejected_without_cloud_or_mutation(configured, value):
    app, remote, _ = configured
    client, headers, aid = bind(app, remote)
    engine = app.extensions['cloud_accounts']
    before = snapshot(engine)
    discovery_hook(app, lambda: pytest.fail('Malformed version must fail before discovery'))
    response = post(client, headers, aid, [TASK], value)
    assert response.status_code == 400
    assert snapshot(engine) == before


def test_legacy_selection_cloud_revocation_cleanup_and_queue_truth(configured):
    app, remote, _ = configured
    client, headers, aid = bind(app, remote)
    engine = app.extensions['cloud_accounts']
    assert client.post(f'/api/accounts/{aid}/sync', headers=headers, json={}).json == {'ok': True, 'queued': False}
    chosen = client.post(path(aid), headers=headers, json={'sources': [TASK]})
    assert chosen.status_code == 200 and chosen.json['queued'] is True
    with engine.db() as con:
        con.execute('UPDATE cloud_sources SET next_attempt=10000000000 WHERE account_id=?', (aid,))
    queued = client.post(f'/api/accounts/{aid}/sync', headers=headers, json={})
    assert queued.json == {'ok': True, 'queued': True}
    with engine.db() as con:
        assert con.execute('SELECT next_attempt FROM cloud_sources WHERE account_id=?', (aid,)).fetchone()[0] == 0
        con.execute('UPDATE cloud_accounts SET needs_reauth=1 WHERE id=?', (aid,))
    discovery_hook(app, lambda: pytest.fail('Empty selection does not require live cloud authorization'))
    cleared = client.post(path(aid), headers=headers, json={'sources': []})
    assert cleared.status_code == 200 and cleared.json['queued'] is False
    assert account(client, aid)['sources'] == []


@pytest.mark.parametrize('method', ['GET', 'POST'])
@pytest.mark.parametrize('mode', ['revoke', 'generation', 'auth_version', 'expire'])
def test_revocation_during_discovery_discards_read_and_write(configured, method, mode):
    app, remote, _ = configured
    client, headers, aid = bind(app, remote)
    select(client, headers, aid)
    engine = app.extensions['cloud_accounts']
    version = account(client, aid)['selectionVersion']
    before = snapshot(engine)
    entered, release = threading.Event(), threading.Event()

    def hold():
        entered.set()
        assert release.wait(10)

    discovery_hook(app, hold)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.open, path(aid), method=method, headers=headers,
                             json={'sources': [CAL], 'selectionVersion': version} if method == 'POST' else None)
        try:
            assert entered.wait(10)
            revoke(engine, mode)
        finally:
            release.set()
        response = future.result(timeout=10)
    assert response.status_code == (409 if mode == 'generation' else 401)
    assert not {'sources', 'selected', 'selectionVersion', 'ok'} & response.json.keys()
    assert snapshot(engine) == before


@pytest.mark.parametrize('method', ['GET', 'POST'])
def test_late_reauth_error_cannot_mark_account_after_revocation(configured, method):
    app, remote, _ = configured
    client, headers, aid = bind(app, remote)
    select(client, headers, aid)
    engine = app.extensions['cloud_accounts']
    version = account(client, aid)['selectionVersion']
    before = snapshot(engine)

    def late_failure():
        revoke(engine)
        raise ProviderError('Synthetic expired cloud grant', 401, reauth=True)

    discovery_hook(app, late_failure)
    response = client.open(path(aid), method=method, headers=headers,
                           json={'sources': [CAL], 'selectionVersion': version} if method == 'POST' else None)
    assert response.status_code == 401
    assert snapshot(engine) == before


def test_current_reauth_failure_and_worker_failure_still_record_health(configured):
    app, remote, _ = configured
    client, headers, aid = bind(app, remote)
    select(client, headers, aid)
    engine = app.extensions['cloud_accounts']

    def fail():
        raise ProviderError('Synthetic expired cloud grant', 401, reauth=True)

    discovery_hook(app, fail)
    assert client.get(path(aid)).status_code == 401
    with engine.db() as con:
        assert con.execute('SELECT needs_reauth FROM cloud_accounts WHERE id=?', (aid,)).fetchone()[0] == 1
        failures = con.execute('SELECT failures FROM cloud_sources WHERE account_id=?', (aid,)).fetchone()[0]
    engine.failure(aid, ProviderError('worker failure', 502))
    with engine.db() as con:
        assert con.execute('SELECT failures FROM cloud_sources WHERE account_id=?', (aid,)).fetchone()[0] == failures + 1


def test_late_reauth_error_cannot_revoke_replacement_grant(configured):
    app, remote, _ = configured
    client, headers, aid = bind(app, remote)
    select(client, headers, aid)
    engine = app.extensions['cloud_accounts']
    expected = {}

    def grant_replaced():
        with engine.db() as con:
            tokens = engine.encrypt({'access_token': 'new-synthetic-grant', 'refresh_token': 'new-refresh',
                                     'expires_at': time.time() + 3600})
            con.execute('UPDATE cloud_accounts SET tokens=? WHERE id=?', (tokens, aid))
        expected.update(snapshot(engine))
        raise ProviderError('Failure from the previous grant', 401, reauth=True)

    discovery_hook(app, grant_replaced)
    response = client.get(path(aid))
    assert response.status_code == 409 and snapshot(engine) == expected


def test_direct_legacy_engine_call_remains_usable_without_http_session(configured):
    app, remote, _ = configured
    client, headers, aid = bind(app, remote)
    engine = app.extensions['cloud_accounts']
    first = engine.select_sources(aid, 'member1', [TASK])
    assert first['ok'] is True and first['queued'] is True
    second = engine.select_sources(aid, 'member1', [TASK], selection_version=first['selectionVersion'])
    assert second['selectionVersion'] == first['selectionVersion']
    assert engine.queue_sync(aid, 'member1')['queued'] is True
    assert account(client, aid)['selectionVersion'] == second['selectionVersion']


@pytest.mark.parametrize('operation', ['empty', 'sync'])
def test_no_cloud_io_paths_validate_entry_context_in_commit_transaction(configured, monkeypatch, operation):
    app, remote, _ = configured
    client, headers, aid = bind(app, remote)
    select(client, headers, aid)
    engine = app.extensions['cloud_accounts']
    before = snapshot(engine)
    if operation == 'empty':
        original = engine.lock

        @contextmanager
        def late_lock(account_id):
            with original(account_id):
                revoke(engine)
                yield

        monkeypatch.setattr(engine, 'lock', late_lock)
        response = client.post(path(aid), headers=headers, json={'sources': []})
    else:
        original = engine.queue_sync

        def late_queue(*args, **kwargs):
            revoke(engine)
            return original(*args, **kwargs)

        monkeypatch.setattr(engine, 'queue_sync', late_queue)
        response = client.post(f'/api/accounts/{aid}/sync', headers=headers, json={})
    assert response.status_code == 401 and snapshot(engine) == before


@pytest.mark.parametrize('route,method', [('/api/accounts', 'accounts_json'), ('sources', 'discovery')])
def test_success_response_fence_drops_dto_revoked_after_read(configured, monkeypatch, route, method):
    app, remote, _ = configured
    client, headers, aid = bind(app, remote)
    select(client, headers, aid)
    engine = app.extensions['cloud_accounts']
    original = getattr(engine, method)

    def late_result(*args, **kwargs):
        value = original(*args, **kwargs)
        revoke(engine)
        return value

    monkeypatch.setattr(engine, method, late_result)
    response = client.get(path(aid) if route == 'sources' else route)
    assert response.status_code == 401 and set(response.json) == {'error'}
    assert response.cache_control.no_store
    assert 'same@example.test' not in response.get_data(as_text=True)


def test_token_refresh_cannot_commit_after_member_revocation(configured):
    app, remote, _ = configured
    client, headers, aid = bind(app, remote)
    select(client, headers, aid)
    engine = app.extensions['cloud_accounts']
    with engine.db() as con:
        row = con.execute('SELECT tokens FROM cloud_accounts WHERE id=?', (aid,)).fetchone()
        tokens = engine.decrypt(row['tokens'])
        tokens['expires_at'] = 0
        con.execute('UPDATE cloud_accounts SET tokens=? WHERE id=?', (engine.encrypt(tokens), aid))
    before = snapshot(engine)

    def delayed_tokens(provider, params):
        revoke(engine)
        return remote.tokens(provider, params)

    app.config['OAUTH_TRANSPORT'] = delayed_tokens
    response = client.get(path(aid))
    assert response.status_code == 401 and snapshot(engine) == before


def test_owner_household_and_tv_denial_without_cloud_access(configured):
    app, remote, _ = configured
    client, headers, aid = bind(app, remote)
    select(client, headers, aid)
    engine = app.extensions['cloud_accounts']
    discovery_hook(app, lambda: pytest.fail('Unauthorized caller must not read cloud sources'))
    partner, ph = login(app, 2)
    assert partner.get('/api/accounts').json['accounts'] == []
    before = snapshot(engine)
    assert partner.get(path(aid)).status_code == 404
    assert partner.post(path(aid), headers=ph, json={'sources': []}).status_code == 404
    assert partner.post(f'/api/accounts/{aid}/sync', headers=ph, json={}).status_code == 404
    assert snapshot(engine) == before
    tv = app.test_client()
    pairing = tv.post('/api/pair/start', json={}).json
    assert client.post('/api/pair/approve', headers=headers, json={'code': pairing['code'], 'name': 'TV', 'focus': 'member1'}).status_code == 200
    tv.post('/api/pair/poll', json={'secret': pairing['secret']})
    before = snapshot(engine)
    assert tv.get('/api/accounts').status_code == 403
    assert tv.get(path(aid)).status_code == 403
    assert tv.post(path(aid), json={'sources': []}).status_code == 403
    assert tv.post(f'/api/accounts/{aid}/sync', json={}).status_code == 403
    invite = client.post('/api/spaces/invitations', json={}, headers=headers).json['invitation']
    other = app.test_client()
    redeemed = other.post('/api/spaces/redeem', json={'invitation': invite, 'name': 'Other household', 'slug': 'source-other',
        'MEMBER1_PASSWORD': 'second-household-one', 'MEMBER2_PASSWORD': 'second-household-two'})
    assert redeemed.status_code == 201, redeemed.json
    assert other.get(redeemed.json['entry']).status_code == 303
    assert other.post('/api/login', json={'username': 'member1', 'password': 'second-household-one'}).status_code == 200
    oh = {'X-CSRF-Token': other.get('/api/me').json['csrf']}
    assert other.get('/api/accounts').json['accounts'] == []
    assert other.get(path(aid)).status_code == 404
    assert other.post(path(aid), headers=oh, json={'sources': []}).status_code == 404
    assert other.post(f'/api/accounts/{aid}/sync', headers=oh, json={}).status_code == 404
    assert snapshot(engine) == before
