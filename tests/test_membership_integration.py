"""Real Flask cookies, SQLite membership changes and cross-household isolation."""
import json
from pathlib import Path
import secrets
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from flask import g, request

from app import Problem, create_app
from membership_storage import connect_household


PASSWORD = 'temporary-family-password-111'
PERSONAL_PASSWORD = 'temporary-personal-password-111'


@pytest.fixture
def system(tmp_path):
    app = create_app({'TESTING': True, 'DATA_DIR': str(tmp_path), 'SECRET_KEY': 'membership-test-only-key',
                      'SESSION_COOKIE_SECURE': False, 'MEMBER1_PASSWORD': PASSWORD, 'MEMBER2_PASSWORD': PASSWORD})
    return app


def read(client, url):
    response = client.get(url)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def post(client, url, value, *, member=False, account=False, expected=200):
    headers = {}
    if member:
        headers['X-Member-CSRF-Token' if url.startswith('/api/account/') else 'X-CSRF-Token'] = read(client, '/api/me')['csrf']
    if account:
        headers['X-CSRF-Token' if url.startswith('/api/account/') else 'X-Account-CSRF-Token'] = read(client, '/api/account/me')['csrf']
    response = client.post(url, json=value, headers=headers)
    assert response.status_code == expected, response.get_json()
    return response.get_json()


def legacy(app, name='member1', password=PASSWORD, client=None):
    client = client or app.test_client()
    post(client, '/api/login', {'username': name, 'password': password})
    return client


def register_old(client, login):
    proof = post(client, '/api/account/eligibility', {'memberPassword': PASSWORD}, member=True, account=True)
    post(client, '/api/account/register', {'requestId': secrets.token_hex(16), 'login': login,
        'password': PERSONAL_PASSWORD, 'eligibilityToken': proof['eligibilityToken']}, member=True, account=True, expected=201)
    member = read(client, '/api/me')['user']
    return post(client, '/api/membership-links', {'requestId': secrets.token_hex(16), 'memberPassword': PASSWORD,
        'expectedAuthVersion': member['auth_version'], 'expectedRevision': member['membershipRevision']}, member=True, account=True)


def invite(client):
    member = read(client, '/api/me')['user']
    return post(client, '/api/member-invitations', {'requestId': secrets.token_hex(16), 'expectedAuthVersion': member['auth_version']}, member=True)


def join(client, token, *, login=None, slug='home'):
    value = {'householdSlug': slug, 'token': token}
    inspected = post(client, '/api/account/invitations/inspect', value, account=True)
    if login:
        post(client, '/api/account/register', {'requestId': secrets.token_hex(16), 'login': login,
            'password': PERSONAL_PASSWORD, 'eligibilityToken': inspected['eligibilityToken']}, account=True, expected=201)
        # Registration rotates the browser generation. Inspect the invitation
        # again rather than replaying an old qualification across identities.
        inspected = post(client, '/api/account/invitations/inspect', value, account=True)
    return post(client, '/api/account/invitations/accept', {'requestId': secrets.token_hex(16), 'joinTicket': inspected['joinTicket']}, account=True)


def switch(client, relation):
    return post(client, '/api/account/switch-household', {'requestId': secrets.token_hex(16),
        'membershipId': relation['id'], 'expectedRevision': relation['revision']}, account=True)


def test_legacy_bind_keeps_owner_and_logout_revokes_derived(system):
    client = legacy(system)
    before = read(client, '/api/me')
    task = post(client, '/api/items/tasks', {'title': 'Existing personal assignment', 'owner': 'member1'}, member=True, expected=201)
    relation = register_old(client, 'first.account')
    after = read(client, '/api/me')
    assert relation['memberId'] == 'member1'
    assert before['csrf'] == after['csrf']
    assert after['user']['membershipRevision'] == before['user']['membershipRevision'] + 1
    switch(client, relation)
    derived_cookie = client.get_cookie('session').value
    me = read(client, '/api/me')
    assert me['user']['accountId'] == read(client, '/api/account/me')['account']['id']
    assert any(row['id'] == task['id'] and row['owner'] == 'member1' for row in read(client, '/api/state')['tasks'])
    post(client, '/api/account/logout', {'requestId': secrets.token_hex(16)}, account=True)
    client.set_cookie('session', derived_cookie)
    assert read(client, '/api/me')['user'] is None
    assert client.get('/api/state').status_code == 401
    assert read(legacy(system), '/api/me')['user']['id'] == 'member1'


def test_third_member_remove_rejoin_same_private_owner(system):
    admin, newcomer = legacy(system), system.test_client()
    relation = join(newcomer, invite(admin)['token'], login='third.account')
    assert relation['memberId'].startswith('m_') and relation['householdRole'] == 'member'
    switch(newcomer, relation)
    owner = relation['memberId']
    assert owner in {person['id'] for person in read(newcomer, '/api/state')['people']}
    post(newcomer, '/api/items/tasks', {'title': 'New member assignment', 'owner': owner}, member=True, expected=201)
    with sqlite3.connect(Path(system.config['DATA_DIR']) / 'household.sqlite3') as con:
        con.execute('INSERT INTO private_finance(owner,data) VALUES(?,?)', (owner, json.dumps({'private-marker': 'kept-original-owner'})))
    old_cookie = newcomer.get_cookie('session').value
    removed = post(admin, '/api/memberships/' + owner + '/remove', {'requestId': secrets.token_hex(16),
        'expectedAuthVersion': read(admin, '/api/me')['user']['auth_version'], 'expectedRevision': relation['revision']}, member=True)
    assert removed['state'] == 'removed'
    assert read(newcomer, '/api/me')['user'] is None
    assert owner not in {person['id'] for person in read(admin, '/api/state')['people']}
    assert read(newcomer, '/api/account/households')['memberships'] == []
    rejoined = join(newcomer, invite(admin)['token'])
    assert rejoined['memberId'] == owner and rejoined['id'] == relation['id'] and rejoined['householdRole'] == 'member'
    newcomer.set_cookie('session', old_cookie)
    assert read(newcomer, '/api/me')['user'] is None
    switch(newcomer, rejoined)
    with sqlite3.connect(Path(system.config['DATA_DIR']) / 'household.sqlite3') as con:
        assert json.loads(con.execute('SELECT data FROM private_finance WHERE owner=?', (owner,)).fetchone()[0])['private-marker'] == 'kept-original-owner'
        assert con.execute('SELECT count(*) FROM users').fetchone()[0] == 3


def test_last_admin_and_dual_proof_enforced(system):
    client = legacy(system)
    relation = register_old(client, 'admin.account')
    headers = {'X-CSRF-Token': read(client, '/api/me')['csrf']}
    assert client.post('/api/membership-links', json={'requestId': secrets.token_hex(16), 'memberPassword': PASSWORD,
        'expectedAuthVersion': 1, 'expectedRevision': relation['revision']}, headers=headers).status_code == 403
    response = client.patch('/api/members/member2/role', json={'expectedAuthVersion': 1, 'householdRole': 'member'}, headers=headers)
    assert response.status_code == 200
    post(client, '/api/memberships/self/leave', {'requestId': secrets.token_hex(16), 'expectedAuthVersion': 1,
        'expectedRevision': relation['revision']}, member=True, account=True, expected=409)
    assert read(client, '/api/me')['user']['id'] == 'member1'


def test_two_households_switch_does_not_merge_legacy_ids(system):
    admin = legacy(system)
    first = register_old(admin, 'multi.account')
    invitation = post(admin, '/api/spaces/invitations', {}, member=True, expected=201)
    public = system.test_client()
    created = post(public, '/api/spaces/redeem', {'invitation': invitation['invitation'], 'name': 'Second test family',
        'slug': 'second-family', 'MEMBER1_PASSWORD': PASSWORD, 'MEMBER2_PASSWORD': PASSWORD}, expected=201)
    assert public.get(created['entry']).status_code == 303
    second_admin = legacy(system, client=public)
    second = join(admin, invite(second_admin)['token'], slug='second-family')
    assert second['memberId'] != 'member1'
    assert len(read(admin, '/api/account/households')['memberships']) == 2
    switch(admin, first)
    original_cookie = admin.get_cookie('session').value
    item = post(admin, '/api/items/tasks', {'title': 'First household only'}, member=True, expected=201)
    switch(admin, second)
    assert read(admin, '/api/me')['user']['householdId'] == second['householdId']
    assert item['id'] not in {row['id'] for row in read(admin, '/api/state')['tasks']}
    # A late cookie from the previous successful switch has been invalidated
    # by personal browser generation, even after routing back to its family.
    admin.set_cookie('session', original_cookie)
    admin.set_cookie('household_space', system.extensions['household_platform'].signer.dumps('default'))
    assert read(admin, '/api/me')['user'] is None


def test_revocation_between_request_auth_and_item_write_is_denied(tmp_path):
    captured, revoked = Event(), Event()
    app = create_app({'TESTING': True, 'DATA_DIR': str(tmp_path), 'SECRET_KEY': 'revocation-test-only-key',
                      'SESSION_COOKIE_SECURE': False, 'MEMBER1_PASSWORD': PASSWORD, 'MEMBER2_PASSWORD': PASSWORD})
    @app.before_request
    def pause_after_authentication():
        if request.path == '/api/items/tasks' and g.actor and g.actor['id'] == 'member2':
            captured.set()
            assert revoked.wait(5), 'revocation must finish without a household lock held by the request'
    admin, target = legacy(app), legacy(app, 'member2')
    csrf = read(target, '/api/me')['csrf']
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(target.post, '/api/items/tasks', json={'title': 'Must not be stored'}, headers={'X-CSRF-Token': csrf})
        assert captured.wait(5)
        try:
            post(admin, '/api/memberships/member2/remove', {'requestId': secrets.token_hex(16),
                'expectedAuthVersion': 1, 'expectedRevision': 1}, member=True)
        finally:
            revoked.set()
        assert future.result(timeout=5).status_code == 401
    assert read(admin, '/api/state')['tasks'] == []


@pytest.mark.parametrize('old_route', ['invalid_cookie', 'missing_database'])
def test_personal_switch_recovers_without_the_old_household(system, old_route):
    client = legacy(system)
    first = register_old(client, 'recovery.account')
    invitation = post(client, '/api/spaces/invitations', {}, member=True, expected=201)
    other = system.test_client()
    created = post(other, '/api/spaces/redeem', {'invitation': invitation['invitation'], 'name': 'Recovery target',
        'slug': 'recovery-target', 'MEMBER1_PASSWORD': PASSWORD, 'MEMBER2_PASSWORD': PASSWORD}, expected=201)
    assert other.get(created['entry']).status_code == 303
    legacy(system, client=other)
    second = join(client, invite(other)['token'], slug='recovery-target')
    switch(client, first)
    original = Path(system.config['DATA_DIR']) / 'household.sqlite3'
    if old_route == 'invalid_cookie':
        client.set_cookie('household_space', 'invalid-signed-route')
    else:
        original.rename(original.with_suffix('.test-unavailable'))
    listed = read(client, '/api/account/households')
    assert second['id'] in {item['id'] for item in listed['memberships']}
    if old_route == 'missing_database':
        assert listed['unavailable'] == [{'householdId': 'default', 'code': 'temporarily_unavailable'}]
    switch(client, second)
    assert read(client, '/api/me')['user']['householdId'] == second['householdId']
    assert read(client, '/api/state')['household']['id'] == second['householdId']
    if old_route == 'missing_database':
        assert not original.exists()


def test_missing_migrated_tables_do_not_reactivate_old_members(system):
    with sqlite3.connect(Path(system.config['DATA_DIR']) / 'household.sqlite3') as con:
        for name in ('membership_operations', 'member_invitations', 'household_memberships'):
            con.execute('DROP TABLE ' + name)
    with pytest.raises(Problem) as failure:
        create_app(dict(system.config))
    assert getattr(failure.value, 'status', None) == 503
    with sqlite3.connect(Path(system.config['DATA_DIR']) / 'household.sqlite3') as con:
        assert con.execute("SELECT count(*) FROM sqlite_master WHERE name='household_memberships'").fetchone()[0] == 0


@pytest.mark.parametrize('mode', ['explicit', 'implicit', 'cursor', 'close'])
def test_platform_lock_precedes_household_transaction_and_releases(system, mode):
    platform = system.extensions['household_platform']
    con = connect_household(system, Path(system.config['DATA_DIR']) / 'household.sqlite3')
    try:
        if mode == 'explicit':
            con.execute('BEGIN IMMEDIATE')
        elif mode == 'cursor':
            con.cursor().execute("UPDATE settings SET revision=revision+1 WHERE id='meta'")
        else:
            con.execute("UPDATE settings SET revision=revision+1 WHERE id='meta'")
        assert con.in_transaction and platform.personal_accounts.guard_con is not None
        with sqlite3.connect(platform.path, timeout=0) as competing:
            with pytest.raises(sqlite3.OperationalError, match='locked'):
                competing.execute('BEGIN IMMEDIATE')
        con.close() if mode == 'close' else con.commit()
        assert platform.personal_accounts.guard_con is None
        with sqlite3.connect(platform.path, timeout=0) as competing:
            competing.execute('BEGIN IMMEDIATE')
    finally:
        con.close()


def test_overlapping_connections_keep_platform_guard_until_last_transaction(system, tmp_path):
    platform = system.extensions['household_platform']
    first = connect_household(system, tmp_path / 'first-test.sqlite3')
    second = connect_household(system, tmp_path / 'second-test.sqlite3')
    try:
        first.execute('BEGIN IMMEDIATE')
        second.execute('BEGIN IMMEDIATE')
        first.commit()
        assert platform.personal_accounts.guard_con is not None
        with sqlite3.connect(platform.path, timeout=0) as competing:
            with pytest.raises(sqlite3.OperationalError, match='locked'):
                competing.execute('BEGIN IMMEDIATE')
        second.commit()
        assert platform.personal_accounts.guard_con is None
        with sqlite3.connect(platform.path, timeout=0) as competing:
            competing.execute('BEGIN IMMEDIATE')
    finally:
        first.close()
        second.close()
