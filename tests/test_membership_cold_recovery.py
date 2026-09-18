"""Actual cold Flask/SQLite recovery; no provider or successful-response mocks."""
from contextlib import closing
import hashlib
from pathlib import Path
import secrets
import socket
import sqlite3

import pytest

import app as source
from media_import_worker import MediaScheduler
from sync_worker import sync_household
from test_membership_integration import PASSWORD, PERSONAL_PASSWORD, legacy, read, post, register_old, invite, join, switch


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('No external calls in cold recovery tests')
    monkeypatch.setattr(socket.socket, 'connect', denied)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    static = tmp_path / 'static'
    (static / 'experience').mkdir(parents=True)
    (static / 'index.html').write_text('synthetic classic', encoding='utf-8')
    (static / 'app.js').write_text('/* synthetic public classic asset */', encoding='utf-8')
    (static / 'experience/index.html').write_text('<html>synthetic Expo shell</html>', encoding='utf-8')
    (static / 'experience/entry.js').write_text('/* synthetic Expo asset */', encoding='utf-8')
    (static / 'experience/metadata.json').write_text('{}', encoding='utf-8')
    monkeypatch.setattr(source, 'ROOT', tmp_path)
    data = tmp_path / 'data'
    config = {'TESTING': True, 'DATA_DIR': str(data), 'SECRET_KEY': 'cold-recovery-synthetic-key',
              'SESSION_COOKIE_SECURE': False, 'MEMBER1_PASSWORD': PASSWORD, 'MEMBER2_PASSWORD': PASSWORD}
    app = source.create_app(config)
    admin = legacy(app)
    first = register_old(admin, 'cold.recovery')
    old_cookie = admin.get_cookie('session').value
    invitation = post(admin, '/api/spaces/invitations', {}, member=True, expected=201)
    other = app.test_client()
    made = post(other, '/api/spaces/redeem', {'invitation': invitation['invitation'], 'name': 'Available synthetic home',
        'slug': 'available-home', 'MEMBER1_PASSWORD': PASSWORD, 'MEMBER2_PASSWORD': PASSWORD}, expected=201)
    assert other.get(made['entry']).status_code == 303
    legacy(app, client=other)
    second = join(admin, invite(other)['token'], slug='available-home')
    switch(admin, second)
    task = post(admin, '/api/items/tasks', {'title': 'Synthetic target task', 'owner': second['memberId']}, member=True, expected=201)
    post(admin, '/api/account/logout', {'requestId': secrets.token_hex(16)}, account=True)
    database = data / 'household.sqlite3'
    with closing(sqlite3.connect(database)) as con:
        con.execute("UPDATE users SET name='preserved original member' WHERE id='member1'")
        con.execute("INSERT INTO private_finance(owner,data) VALUES('member1','{\"private\":\"original-only\"}') ON CONFLICT(owner) DO UPDATE SET data=excluded.data")
        con.commit()
        con.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    return {'config': config, 'data': data, 'database': database, 'first': first, 'second': second,
            'task': task, 'oldCookie': old_cookie, 'app': app}


def remove_default(fixture):
    original = fixture['database'].with_suffix('.unavailable')
    fixture['database'].rename(original)
    return original, digest(original)


def test_cold_missing_default_keeps_old_database_and_recovers_to_child(fixture):
    original, before = remove_default(fixture)
    cold = source.create_app(fixture['config'])
    assert not fixture['database'].exists(), 'Cold startup recreated the missing default DB'
    client = cold.test_client()
    assert client.get('/api/me').status_code == 503
    assert read(client, '/api/account/me')['account'] is None
    signed = post(client, '/api/account/login', {'login': 'cold.recovery', 'password': PERSONAL_PASSWORD}, account=True)
    assert signed['account']['login'] == 'cold.recovery'
    homes = read(client, '/api/account/households')
    assert homes['unavailable'] == [{'householdId': 'default', 'code': 'temporarily_unavailable'}]
    assert [h['id'] for h in homes['memberships']] == [fixture['second']['id']]
    switch(client, fixture['second'])
    me = read(client, '/api/me')['user']
    assert me['householdId'] == fixture['second']['householdId'] and me['id'] == fixture['second']['memberId']
    assert me['accountId'] == signed['account']['id']
    assert any(t['id'] == fixture['task']['id'] for t in read(client, '/api/state')['tasks'])
    assert not fixture['database'].exists() and digest(original) == before


@pytest.mark.parametrize('path', ['/api/me', '/api/state', '/api/login', '/api/spaces/redeem', '/healthz'])
def test_default_api_and_health_unavailable_without_initialization(fixture, path):
    original, before = remove_default(fixture)
    cold = source.create_app(fixture['config'])
    client = cold.test_client()
    response = client.post(path, json={}) if path in ('/api/login', '/api/spaces/redeem') else client.get(path)
    assert response.status_code == 503
    assert response.headers['Cache-Control'] == 'no-store'
    assert not fixture['database'].exists() and digest(original) == before


def test_public_recovery_shell_uses_the_existing_asset_allowlist(fixture):
    original, before = remove_default(fixture)
    client = source.create_app(fixture['config']).test_client()
    client.set_cookie('household_space', 'invalid-signed-route')
    for path in ('/app', '/app/more', '/app/entry.js', '/static/app.js'):
        for method in ('get', 'head'):
            response = getattr(client, method)(path)
            assert response.status_code == 200
            assert response.headers['X-Content-Type-Options'] == 'nosniff'
            assert not response.headers.getlist('Set-Cookie')
            assert b'original-only' not in response.data
    assert client.get('/').status_code == 302
    for path in ('/static/experience/entry.js', '/app/metadata.json', '/app/.env', '/app/assets/missing.js'):
        assert client.get(path).status_code == 404
    assert not fixture['database'].exists() and digest(original) == before


@pytest.mark.parametrize('route', ['/space/home', '/space/available-home'])
def test_old_member_cookie_space_change_is_503_without_session_extension(fixture, route):
    original, before = remove_default(fixture)
    client = source.create_app(fixture['config']).test_client()
    client.set_cookie('session', fixture['oldCookie'])
    response = client.get(route)
    assert response.status_code == 503
    assert not response.headers.getlist('Set-Cookie')
    assert not fixture['database'].exists() and digest(original) == before


def test_workers_skip_missing_default_but_can_load_the_real_child(fixture):
    original, before = remove_default(fixture)
    cold = source.create_app(fixture['config'])
    platform = cold.extensions['household_platform']
    default = next(h for h in platform.households() if h['id'] == 'default')
    with pytest.raises(RuntimeError, match='unavailable'):
        platform.child(default)
    sync_household(platform, default)
    scheduler = MediaScheduler(platform)
    ids = sorted(h['id'] for h in platform.households())
    scheduler.cursor = ids[ids.index('default') - 1]  # The actual predecessor selects default next.
    assert scheduler.tick() is False
    child = platform.child(next(h for h in platform.households() if h['id'] == fixture['second']['householdId']))
    assert {'task_publish', 'calendar_publish', 'cloud_accounts', 'household_routines', 'household_media'} <= child.extensions.keys()
    assert not fixture['database'].exists() and digest(original) == before


def test_restored_default_requires_restart_and_preserves_old_users(fixture):
    original, before = remove_default(fixture)
    cold = source.create_app(fixture['config'])
    original.rename(fixture['database'])
    with pytest.raises(RuntimeError, match='unavailable'):
        cold.extensions['household_platform'].child({'id': 'default'})
    # The recovery instance never begins serving a restored DB implicitly.
    assert cold.test_client().get('/api/me').status_code == 503
    with closing(sqlite3.connect(fixture['database'])) as con:
        users = con.execute('SELECT * FROM users ORDER BY id').fetchall()
        private = con.execute('SELECT * FROM private_finance ORDER BY owner').fetchall()
    restarted = source.create_app(fixture['config'])
    assert read(legacy(restarted), '/api/me')['user']['name'] == 'preserved original member'
    with closing(sqlite3.connect(fixture['database'])) as con:
        assert con.execute('SELECT * FROM users ORDER BY id').fetchall() == users
        assert con.execute('SELECT * FROM private_finance ORDER BY owner').fetchall() == private


def test_fresh_install_without_registry_still_initializes_default(tmp_path):
    config = {'TESTING': True, 'DATA_DIR': str(tmp_path / 'fresh'), 'SECRET_KEY': 'fresh-synthetic',
              'SESSION_COOKIE_SECURE': False, 'MEMBER1_PASSWORD': PASSWORD, 'MEMBER2_PASSWORD': PASSWORD}
    first = source.create_app(config)
    assert read(legacy(first), '/api/me')['user']['id'] == 'member1'
    assert (Path(config['DATA_DIR']) / 'platform.sqlite3').is_file()
    again = source.create_app(config)
    assert read(legacy(again), '/api/me')['user']['id'] == 'member1'


@pytest.mark.parametrize('cookies', ['none', 'legacy', 'tv', 'both'])
def test_restored_file_personal_recovery_stays_partial_until_restart(fixture, cookies):
    original, before = remove_default(fixture)
    cold = source.create_app(fixture['config'])
    original.rename(fixture['database'])
    client = cold.test_client()
    if cookies in ('legacy', 'both'):
        client.set_cookie('session', fixture['oldCookie'])
    if cookies in ('tv', 'both'):
        client.set_cookie('household_tv', 'old-unavailable-household-tv-cookie')
    assert read(client, '/api/account/me')['account'] is None
    assert client.get('/api/account/me', headers={'X-Display-Mode': 'tv'}).status_code == 403
    signed = post(client, '/api/account/login', {'login': 'cold.recovery', 'password': PERSONAL_PASSWORD}, account=True)
    homes = read(client, '/api/account/households')
    assert homes['unavailable'] == [{'householdId': 'default', 'code': 'temporarily_unavailable'}]
    assert [h['id'] for h in homes['memberships']] == [fixture['second']['id']]
    post(client, '/api/account/switch-household', {'requestId': secrets.token_hex(16),
        'membershipId': fixture['first']['id'], 'expectedRevision': fixture['first']['revision']}, account=True, expected=503)
    assert client.get('/api/me').status_code == 503
    assert read(client, '/api/account/me')['account']['id'] == signed['account']['id']
    switch(client, fixture['second'])
    me = read(client, '/api/me')['user']
    assert me['householdId'] == fixture['second']['householdId'] and me['accountId'] == signed['account']['id']
    assert digest(fixture['database']) == before, 'Recovery must not open or change the restored default DB'
