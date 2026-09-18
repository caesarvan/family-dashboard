"""Temporary real Flask/Cookie/SQLite administration; no external services."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from pathlib import Path
import socket
import sqlite3
from threading import Barrier, Event
import time
from types import SimpleNamespace

from flask import g, request
import pytest
from werkzeug.datastructures import ImmutableMultiDict

import app as server
import household_members as members
import member_sessions
from test_app import app, member
from test_device_sessions import ConnectionProxy, install_connection, invalidate
from test_household_spaces import create_space
from test_member_sessions import env, login, legacy, bind_account, begin, finish


URL = '/api/members'


@pytest.fixture(autouse=True)
def register_for_real_apps(monkeypatch):
    original = server.register_finance_hub

    def register(app, db, Problem, body, require_member, audit):
        def checked_audit(action, target=''):
            audit(action, target)
            if app.config.get('MEMBERS_TEST_AUDIT_FAILURE'):
                raise RuntimeError('Synthetic audit failure')
        members.register_members(app, db, Problem, body, require_member, checked_audit)

    monkeypatch.setattr(server, 'register_members', register, raising=False)

    def hub(app, db, Problem, body, require_member, audit):
        original(app, db, Problem, body, require_member, audit)
        if 'household_members_list' not in app.view_functions:
            register(app, db, Problem, body, require_member, audit)

    monkeypatch.setattr(server, 'register_finance_hub', hub)
    connect = socket.socket.connect
    def local_only(sock, address):
        assert isinstance(address, tuple) and address[0] in {'127.0.0.1', '::1'}, 'External network forbidden'
        return connect(sock, address)
    monkeypatch.setattr(socket.socket, 'connect', local_only)


@contextmanager
def database(app, **kwargs):
    with closing(sqlite3.connect(Path(app.config['DATA_DIR']) / 'household.sqlite3', **kwargs)) as con:
        with con:
            yield con


def snapshot(app, exclude=()):
    with database(app) as con:
        names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {name: sorted(con.execute('SELECT * FROM "' + name + '"').fetchall(), key=repr)
                for name in names if name not in exclude}


def unchanged_business(app):
    value = snapshot(app, {'users', 'member_sessions', 'member_session_browsers', 'attempts', 'audit', 'settings'})
    value['sqlite_sequence'] = [r for r in value['sqlite_sequence'] if r[0] != 'audit']
    return value


def operation(client, headers, *, target='member2', version=1, role=None):
    data = {'expectedAuthVersion': version}
    if role is not None:
        return client.patch(URL + '/' + target + '/role', json={**data, 'householdRole': role}, headers=headers)
    return client.post(URL + '/' + target + '/revoke-sessions', json=data, headers=headers)


def roster(client):
    response = client.get(URL)
    assert response.status_code == 200, response.json
    assert set(response.json) == {'currentMemberId', 'members'}
    assert [r['id'] for r in response.json['members']] == ['member1', 'member2']
    for row in response.json['members']:
        assert set(row) == {'id', 'name', 'householdRole', 'authVersion', 'activeSessionCount', 'capabilities'}
        assert set(row['capabilities']) == {'changeRole', 'revokeSessions'}
    return response.json['members']


def test_atomic_one_time_migration_preserves_existing_data_and_roles():
    with closing(sqlite3.connect(':memory:')) as con:
        con.execute('CREATE TABLE users(id TEXT PRIMARY KEY, name TEXT, auth_version INTEGER)')
        con.executemany('INSERT INTO users VALUES(?,?,?)', [('member1', 'A', 7), ('member2', 'B', 9)])
        con.commit()
        members.init_schema(con)
        assert con.execute('SELECT * FROM users ORDER BY id').fetchall() == [
            ('member1', 'A', 7, 'admin'), ('member2', 'B', 9, 'admin')]
        con.execute("UPDATE users SET household_role='member' WHERE id='member2'")
        con.commit()
        members.init_schema(con)
        assert con.execute("SELECT household_role FROM users WHERE id='member2'").fetchone()[0] == 'member'
        con.execute("INSERT INTO users(id,name,auth_version) VALUES('future-member','C',1)")
        assert con.execute("SELECT household_role FROM users WHERE id='future-member'").fetchone()[0] == 'member'
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("UPDATE users SET household_role='superuser'")


def test_migration_failure_rolls_back_ddl_and_rejects_nested_transaction():
    with closing(sqlite3.connect(':memory:')) as con:
        con.execute('CREATE TABLE users(id TEXT PRIMARY KEY)')
        con.execute("INSERT INTO users VALUES('member1')")
        with pytest.raises(RuntimeError, match='independent'):
            members.init_schema(con)
        con.commit()
        before = con.execute('SELECT sql FROM sqlite_master').fetchall()
        def fail(sql):
            if sql.startswith('UPDATE users'):
                raise RuntimeError('Synthetic failure after ALTER')
        with pytest.raises(RuntimeError, match='after ALTER'):
            members.init_schema(ConnectionProxy(con, before=fail))
        assert con.execute('SELECT sql FROM sqlite_master').fetchall() == before
        assert con.execute('SELECT * FROM users').fetchall() == [('member1',)]
        assert not con.in_transaction


def test_two_admins_roster_is_minimal_and_auth_role_unchanged(app):
    client, _ = member(app)
    other, _ = member(app, 2)
    rows = roster(client)
    assert [r['householdRole'] for r in rows] == ['admin', 'admin']
    assert [r['activeSessionCount'] for r in rows] == [1, 1]
    assert rows[0]['capabilities'] == {'changeRole': False, 'revokeSessions': False}
    assert rows[1]['capabilities'] == {'changeRole': True, 'revokeSessions': True}
    assert client.get('/api/me').json['user']['role'] == 'member'
    assert 'householdRole' not in client.get('/api/me').json['user']
    assert roster(other)[0]['capabilities']['changeRole'] is True
    with database(app) as con:
        from deploy.check_finance_accounts_migration import BASE_TABLES, NEW_TABLES
        original_tables = BASE_TABLES | NEW_TABLES
        membership_tables = {'household_memberships', 'member_invitations', 'membership_operations'}
        assert len(original_tables) == 58 and len(original_tables | membership_tables) == 61
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        assert tables == original_tables | membership_tables


def test_count_excludes_expired_revoked_and_old_auth_version(app):
    admin, _ = member(app)
    for _ in range(4):
        member(app, 2)
    with database(app) as con:
        ids = [r[0] for r in con.execute("SELECT id FROM member_sessions WHERE owner='member2' ORDER BY id")]
        con.execute('UPDATE member_sessions SET expires_at=1 WHERE id=?', (ids[0],))
        con.execute('UPDATE member_sessions SET revoked_at=1 WHERE id=?', (ids[1],))
        con.execute('UPDATE member_sessions SET auth_version=0 WHERE id=?', (ids[2],))
    assert roster(admin)[1]['activeSessionCount'] == 1


@pytest.mark.parametrize('role', [None, 'member'])
def test_revoke_or_role_change_invalidates_old_sessions_but_allows_new_login_and_cas(app, role):
    admin, headers = member(app)
    old, oh = member(app, 2)
    private = {'income': 1234567, 'spent': 45678, 'budget': 100000, 'month': '2026-09', 'revision': 0}
    assert old.put('/api/private-finance', json=private, headers=oh).status_code == 200
    assert admin.get('/api/private-finance').json.get('income') != private['income']
    copied = app.test_client()
    copied.set_cookie('session', old.get_cookie('session').value)
    second, _ = member(app, 2)
    before = unchanged_business(app)
    with database(app) as con:
        generations = dict(con.execute('SELECT browser_hash,generation FROM member_session_browsers'))
        hashes = {r[0] for r in con.execute("SELECT browser_hash FROM member_sessions WHERE owner='member2'")}
        audit_sequence = con.execute("SELECT seq FROM sqlite_sequence WHERE name='audit'").fetchone()[0]
    response = operation(admin, headers, role=role)
    assert response.status_code == 200, response.json
    assert response.json == {'ok': True, 'member': {'id': 'member2', 'householdRole': role or 'admin', 'authVersion': 2}, 'revoked': 2}
    for stale in (old, copied, second):
        assert stale.get(URL).status_code == 401
    with database(app) as con:
        assert not con.execute("SELECT 1 FROM member_sessions WHERE owner='member2' AND revoked_at IS NULL").fetchone()
        now = dict(con.execute('SELECT browser_hash,generation FROM member_session_browsers'))
        assert all(now[k] == generations[k] + (k in hashes) for k in generations)
        assert con.execute("SELECT seq FROM sqlite_sequence WHERE name='audit'").fetchone()[0] == audit_sequence+1
        assert con.execute('SELECT action,target FROM audit ORDER BY id DESC LIMIT 1').fetchone() == (
            'household_member_role' if role else 'household_member_sessions_revoke', 'member2')
    fresh, fh = member(app, 2)
    rows = roster(fresh)
    if role:
        assert all(row['activeSessionCount'] is None for row in rows)
        assert all(not any(row['capabilities'].values()) for row in rows)
        assert operation(fresh, fh, target='member1').status_code == 403
    assert operation(admin, headers, role=role).status_code == 409
    assert fresh.get(URL).status_code == 200
    assert fresh.get('/api/private-finance').json['income'] == private['income']
    assert admin.get('/api/private-finance?owner=member2').json.get('income') != private['income']
    assert unchanged_business(app) == before


def test_remaining_admin_can_restore_partner_admin_without_expanding_private_access(app):
    admin, headers = member(app)
    assert operation(admin, headers, role='member').status_code == 200
    partner, _ = member(app, 2)
    response = operation(admin, headers, role='admin', version=2)
    assert response.status_code == 200 and response.json == {
        'ok': True, 'member': {'id': 'member2', 'householdRole': 'admin', 'authVersion': 3}, 'revoked': 1}
    assert partner.get(URL).status_code == 401
    fresh, fh = member(app, 2)
    assert roster(fresh)[0]['capabilities']['revokeSessions'] is True
    assert fresh.post('/api/spaces/invitations', json={}, headers=fh).status_code == 403


def test_restart_preserves_explicit_demotion(app):
    admin, headers = member(app)
    assert operation(admin, headers, role='member').status_code == 200
    restarted = server.create_app(dict(app.config))
    other, _ = member(restarted, 2)
    assert roster(other)[1]['householdRole'] == 'member'


def test_zero_sessions_still_invalidates_unregistered_legacy_cookie(app, monkeypatch):
    admin, headers = member(app)
    stale, _, _ = legacy(app, app.extensions['member_sessions'], monkeypatch, uid='member2')
    response = operation(admin, headers)
    assert response.status_code == 200 and response.json['revoked'] == 0
    assert response.json['member']['authVersion'] == 2
    assert stale.get(URL).status_code == 401
    fresh, _ = member(app, 2)
    assert fresh.get(URL).status_code == 200


@pytest.mark.parametrize('route,method', [(URL, 'GET'), (URL+'/member2/role', 'PATCH'), (URL+'/member2/revoke-sessions', 'POST')])
def test_anonymous_and_tv_denied(app, route, method):
    admin, headers = member(app)
    tv = app.test_client()
    pair = tv.post('/api/pair/start', json={}).json
    assert admin.post('/api/pair/approve', json={'code': pair['code'], 'name': 'Synthetic TV'}, headers=headers).status_code == 200
    assert tv.post('/api/pair/poll', json={'secret': pair['secret']}).json['approved']
    data = {'expectedAuthVersion': 1, 'householdRole': 'member'} if method == 'PATCH' else {'expectedAuthVersion': 1}
    assert app.test_client().open(route, method=method, json=data).status_code == 401
    assert tv.open(route, method=method, json=data, headers={'X-CSRF-Token': tv.get('/api/me').json['csrf']}).status_code == 403


@pytest.mark.parametrize('value', [True, False, 0, -1, 1.5, '1', None, 9007199254740992])
def test_strict_expected_version(app, value):
    client, headers = member(app)
    before = snapshot(app)
    assert operation(client, headers, version=value).status_code == 400
    assert snapshot(app) == before


def test_body_query_and_permission_rejections_do_not_write(app):
    client, headers = member(app)
    before = snapshot(app)
    path = URL+'/member2/role'
    for data, status in [({}, 400), ({'expectedAuthVersion': 1, 'householdRole': []}, 400),
                         ({'expectedAuthVersion': 1, 'householdRole': 'tv'}, 403),
                         ({'expectedAuthVersion': 1, 'householdRole': 'member', 'owner': 'member1'}, 400)]:
        assert client.patch(path, json=data, headers=headers).status_code == status
    assert client.patch(path, data='{"expectedAuthVersion":1,"expectedAuthVersion":1,"householdRole":"member"}',
                        content_type='application/json', headers=headers).status_code == 400
    assert client.patch(path, json=[], headers=headers).status_code == 400
    assert client.get(URL+'?household=default&household=other').status_code == 400
    assert client.post(URL+'/member2/revoke-sessions?owner=member2', json={'expectedAuthVersion': 1}, headers=headers).status_code == 400
    assert operation(client, headers, target='member1').status_code == 403
    assert operation(client, headers, role='admin').status_code == 409
    assert operation(client, headers, target='missing').status_code == 404
    assert operation(client, {}).status_code == 403
    assert operation(client, {**headers, 'Origin': 'https://invalid.example'}).status_code == 403
    assert snapshot(app) == before


def test_auth_version_exhaustion_does_not_wrap(app):
    client, headers = member(app)
    with database(app) as con:
        con.execute("UPDATE users SET auth_version=? WHERE id='member2'", (members.MAX_AUTH_VERSION,))
    before = snapshot(app)
    assert operation(client, headers, version=members.MAX_AUTH_VERSION).status_code == 409
    assert snapshot(app) == before


def test_two_households_same_ids_are_isolated_and_admin_is_not_platform_privilege(app):
    primary, headers = member(app)
    partner, ph = member(app, 2)
    assert partner.post('/api/spaces/invitations', json={}, headers=ph).status_code == 403
    b, _, result = create_space(app)
    assert b.get(result['entry']).status_code == 303
    assert b.post('/api/login', json={'username': 'member1', 'password': 'second-home-password-one'}).status_code == 200
    bh = {'X-CSRF-Token': b.get('/api/me').json['csrf']}
    assert [r['householdRole'] for r in roster(b)] == ['admin', 'admin']
    assert operation(b, bh, role='member').status_code == 200
    assert roster(primary)[1]['householdRole'] == 'admin'
    assert roster(primary)[1]['authVersion'] == 1
    assert partner.get(URL).status_code == 200
    assert b.post('/api/spaces/invitations', json={}, headers=bh).status_code == 403
    b.set_cookie('session', primary.get_cookie('session').value)
    assert b.get(URL).status_code == 401


@pytest.mark.parametrize('kind', ['session', 'expired', 'auth_version', 'role'])
@pytest.mark.parametrize('method', ['GET', 'POST'])
def test_changes_after_guard_are_rechecked(app, kind, method):
    client, headers = member(app)
    path = URL if method == 'GET' else URL+'/member2/revoke-sessions'
    before = snapshot(app, {'users', 'member_sessions', 'attempts'})
    def change_after_guard():
        if request.path == path:
            assert g.actor['id'] == 'member1'
            with database(app) as con:
                if kind == 'role':
                    con.execute("UPDATE users SET household_role='member' WHERE id='member1'")
                else:
                    invalidate(con, kind)
    app.before_request_funcs[None].append(change_after_guard)
    response = client.open(path, method=method, json={'expectedAuthVersion': 1}, headers=headers)
    expected = 200 if kind == 'role' and method == 'GET' else 403 if kind == 'role' else 401
    assert response.status_code == expected, response.json
    if expected == 200:
        assert all(r['activeSessionCount'] is None for r in response.json['members'])
    assert snapshot(app, {'users', 'member_sessions', 'attempts'}) == before


@pytest.mark.parametrize('old_cookie', [False, True])
@pytest.mark.parametrize('kind', ['session', 'role'])
def test_read_snapshot_is_released_and_late_revocation_drops_result(app, monkeypatch, old_cookie, kind):
    if old_cookie:
        client, _, _ = legacy(app, app.extensions['member_sessions'], monkeypatch)
    else:
        client, _ = member(app)
    calls = []
    def after_rows(sql):
        if sql.lstrip().startswith('SELECT u.id,u.name,u.household_role'):
            with database(app, timeout=0.2) as writer:
                if kind == 'session':
                    invalidate(writer)
                else:
                    writer.execute("UPDATE users SET household_role='member' WHERE id='member1'")
            calls.append(True)
    install_connection(app, URL, 'GET', after=after_rows)
    response = client.get(URL)
    assert calls == [True]
    assert response.status_code == (401 if kind == 'session' else 403), response.json
    assert set(response.json) == {'error'}
    with database(app) as con:
        assert con.execute("SELECT count(*) FROM member_sessions WHERE owner='member1'").fetchone()[0] == 1


def test_legacy_first_read_persists_registration_and_bootstrap_users(app, monkeypatch):
    client, _, _ = legacy(app, app.extensions['member_sessions'], monkeypatch)
    assert roster(client)[0]['activeSessionCount'] == 1
    assert roster(client)[0]['activeSessionCount'] == 1
    with database(app) as con:
        assert con.execute('SELECT count(*) FROM users').fetchone()[0] == 2
        assert con.execute('SELECT legacy FROM member_sessions').fetchall() == [(1,)]


@pytest.mark.parametrize('kind', ['session', 'role'])
def test_write_rechecks_after_waiting_for_real_writer_lock(app, kind):
    client, headers = member(app)
    path = URL+'/member2/revoke-sessions'
    entered = Event()
    writer = sqlite3.connect(Path(app.config['DATA_DIR'])/'household.sqlite3', timeout=5, check_same_thread=False)
    before = snapshot(app, {'users', 'member_sessions', 'attempts'})
    def begin_write(sql):
        if sql == 'BEGIN IMMEDIATE':
            writer.execute('BEGIN IMMEDIATE')
            if kind == 'session':
                invalidate(writer)
            else:
                writer.execute("UPDATE users SET household_role='member' WHERE id='member1'")
            entered.set()
    install_connection(app, path, 'POST', before=begin_write)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(operation, client, headers)
            try:
                assert entered.wait(10) and not pending.done()
            finally:
                writer.commit()
            response = pending.result(timeout=10)
        assert response.status_code == (401 if kind == 'session' else 403), response.json
        assert snapshot(app, {'users', 'member_sessions', 'attempts'}) == before
    finally:
        writer.close()


@pytest.mark.parametrize('role', [None, 'member'])
def test_expiry_after_audit_rolls_back_roles_sessions_generations_and_audit(app, monkeypatch, role):
    client, headers = member(app)
    member(app, 2)
    with database(app) as con:
        expires = con.execute("SELECT max(expires_at) FROM member_sessions WHERE owner='member1'").fetchone()[0]
    before = snapshot(app)
    clock = {'now': time.time()}
    monkeypatch.setattr(member_sessions, 'time', SimpleNamespace(time=lambda: clock['now']))
    def after_audit(sql):
        if sql.startswith('UPDATE settings SET revision'):
            clock['now'] = expires + 1
    install_connection(app, URL+'/member2/'+('role' if role else 'revoke-sessions'), 'PATCH' if role else 'POST', after=after_audit)
    response = operation(client, headers, role=role)
    assert clock['now'] == expires+1 and response.status_code == 401, response.json
    assert snapshot(app) == before


def test_audit_failure_rolls_back_every_table(app):
    client, headers = member(app)
    member(app, 2)
    before = snapshot(app)
    app.config['MEMBERS_TEST_AUDIT_FAILURE'] = True
    with pytest.raises(RuntimeError, match='Synthetic audit'):
        operation(client, headers, role='member')
    assert snapshot(app) == before


@pytest.mark.parametrize('number', [1, 2])
@pytest.mark.parametrize('phase', ['after_guard', 'after_audit'])
def test_other_real_cookie_cannot_replace_captured_session(app, number, phase):
    client, headers = member(app)
    replacement, _ = member(app, number)
    raw = replacement.get_cookie('session').value
    assert raw != client.get_cookie('session').value
    before, seen = snapshot(app), []
    def replace_cookie():
        cookies = dict(request.cookies)
        cookies['session'] = raw
        request.__dict__['cookies'] = ImmutableMultiDict(cookies)
        seen.append(True)
    path = URL+'/member2/revoke-sessions'
    if phase == 'after_guard':
        def hook():
            if request.path == path:
                replace_cookie()
        app.before_request_funcs[None].append(hook)
    else:
        def after_audit(sql):
            if sql.startswith('UPDATE settings SET revision'):
                replace_cookie()
        install_connection(app, path, 'POST', after=after_audit)
    response = operation(client, headers)
    assert seen == [True] and response.status_code == 401, response.json
    assert snapshot(app) == before


def test_concurrent_admins_cannot_demote_each_other_to_zero_admins(app):
    one, h1 = member(app)
    two, h2 = member(app, 2)
    ready = Barrier(2)
    def both_authenticated():
        if request.path.endswith('/role'):
            assert g.actor['role'] == 'member'
            ready.wait(timeout=10)
    app.before_request_funcs[None].append(both_authenticated)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(operation, one, h1, role='member')
        second = pool.submit(operation, two, h2, target='member1', role='member')
        responses = [first.result(timeout=15), second.result(timeout=15)]
    assert sorted(r.status_code for r in responses) == [200, 401]
    with database(app) as con:
        assert con.execute("SELECT count(*) FROM users WHERE household_role='admin'").fetchone()[0] == 1
        assert sorted(r[0] for r in con.execute('SELECT auth_version FROM users')) == [1, 2]


def test_parallel_same_version_revoke_applies_once(app):
    one, h1 = member(app)
    another, h2 = member(app)
    member(app, 2)
    ready = Barrier(2)
    def both_authenticated():
        if request.path.endswith('/revoke-sessions'):
            ready.wait(timeout=10)
    app.before_request_funcs[None].append(both_authenticated)
    with ThreadPoolExecutor(max_workers=2) as pool:
        calls = [pool.submit(operation, one, h1), pool.submit(operation, another, h2)]
        responses = [c.result(timeout=15) for c in calls]
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert roster(one)[1]['authVersion'] == 2


def test_member_bound_oauth_is_invalidated_without_disconnecting_saved_account(env):
    app, _, remote, _ = env
    target, account_id = bind_account(app, remote)
    pending = begin(target)
    admin, headers = login(app, 'member2')
    response = operation(admin, headers, target='member1')
    assert response.status_code == 200
    def forbidden(*_args, **_kwargs):
        pytest.fail('Revoked member context must fail before provider exchange')
    app.config['OAUTH_TRANSPORT'] = forbidden
    result = finish(target, pending)
    assert 'auth=connected' not in result.location
    fresh, _ = login(app)
    assert [a['id'] for a in fresh.get('/api/accounts').json['accounts']] == [account_id]
    assert admin.get('/api/accounts').json['accounts'] == []
