"""Real temporary household SQLite; no platform, production, or provider calls."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import socket
import sqlite3
from threading import Barrier
from types import SimpleNamespace
import time

import pytest
from werkzeug.security import check_password_hash

import household_memberships as domain
from test_app import app, member


ACCOUNT1, ACCOUNT2, ACCOUNT3 = '1' * 32, '2' * 32, '3' * 32
SECRET = b'only-synthetic-operation-hmac-key-32'


@pytest.fixture(autouse=True)
def no_external_connections(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('No network belongs to this household-only domain test')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)


def path(app):
    return Path(app.config['DATA_DIR']) / 'household.sqlite3'


@contextmanager
def connection(app, write=True):
    con = sqlite3.connect(path(app).resolve().as_uri() + '?mode=rw', uri=True, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    con.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
    try:
        yield con
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()


def fingerprint(con, exclude=()):
    result = {}
    for row in con.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
        name, sql = row
        if name not in exclude:
            result[name] = {'sql': sql, 'rows': sorted([tuple(r) for r in con.execute('SELECT * FROM "' + name + '"')], key=repr)}
    return result


@pytest.fixture
def legacy_app(app, tmp_path):
    # Build an independent pre-membership schema projection. Never remove live
    # app membership tables or its startup marker to bypass migration checks.
    folder = tmp_path / 'legacy-domain-only'
    folder.mkdir()
    legacy = SimpleNamespace(config={'DATA_DIR': str(folder)})
    with closing(sqlite3.connect(path(app).resolve().as_uri() + '?mode=ro', uri=True)) as source:
        original = fingerprint(source)
        tables = {name: value for name, value in original.items() if name not in domain.TABLES}
        with closing(sqlite3.connect(path(legacy))) as target:
            for name, value in tables.items():
                if name != 'sqlite_sequence':
                    target.execute(value['sql'])
            for name, value in tables.items():
                if name == 'sqlite_sequence':
                    continue
                for row in value['rows']:
                    if name == 'settings' and row[0] == 'membership_schema_v1':
                        continue
                    target.execute('INSERT INTO "' + name + '" VALUES(' + ','.join('?' for _ in row) + ')', row)
            for name, sequence in tables.get('sqlite_sequence', {}).get('rows', []):
                if not target.execute('UPDATE sqlite_sequence SET seq=? WHERE name=?', (sequence, name)).rowcount:
                    target.execute('INSERT INTO sqlite_sequence VALUES(?,?)', (name, sequence))
            target.commit()
            expected = {name: {'sql': value['sql'], 'rows': [row for row in value['rows']
                        if not (name == 'settings' and row[0] == 'membership_schema_v1')]}
                        for name, value in tables.items()}
            assert fingerprint(target) == expected
        assert fingerprint(source) == original
    yield legacy
    with closing(sqlite3.connect(path(app).resolve().as_uri() + '?mode=ro', uri=True)) as source:
        assert fingerprint(source) == original


def intent(kind, values):
    raw = json.dumps({'kind': kind, 'values': values}, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hmac.new(SECRET, raw.encode(), hashlib.sha256).hexdigest()


def command(function, con, *, request_id=None, intent_digest=None, **kwargs):
    key = request_id or secrets.token_hex(16)
    digest = intent_digest or intent(function.__name__, {k: v for k, v in kwargs.items() if k != 'now'})
    return function(con, request_id=key, intent_digest=digest, **kwargs)


@pytest.fixture
def initialized(app):
    with connection(app) as con:
        domain.schema_initialize(con)
    return app


def invite(con, **kwargs):
    return command(domain.create_invitation, con, household_id='default', actor_member_id='member1', expected_auth_version=1, **kwargs)


def accept(con, invitation, account=ACCOUNT3, **kwargs):
    return command(domain.accept_invitation, con, household_id='default', account_id=account,
                   invitation_id=invitation['invitation']['id'], expected_revision=invitation['invitation']['revision'], **kwargs)


def bind(con, member_id='member1', account=ACCOUNT1, **kwargs):
    return command(domain.bind_account, con, household_id='default', member_id=member_id, account_id=account,
                   member_password='testing-password-' + ('one' if member_id == 'member1' else 'two'),
                   expected_auth_version=1, expected_revision=1, **kwargs)


def remove(con, target, *, actor='member1', revision=1, av=1, **kwargs):
    return command(domain.remove_membership, con, household_id='default', actor_member_id=actor,
                   member_id=target, expected_auth_version=av, expected_revision=revision, **kwargs)


def assert_error(code, function, *args, **kwargs):
    with pytest.raises(domain.MembershipError) as caught:
        function(*args, **kwargs)
    assert caught.value.code == code
    return caught.value


def test_one_time_initialization_preserves_all_existing_tables_passwords_and_actual_roles(legacy_app):
    app = legacy_app
    with connection(app) as con:
        con.execute("UPDATE users SET household_role='member',auth_version=9 WHERE id='member2'")
        before = fingerprint(con)
        domain.schema_initialize(con)
        first = [tuple(r) for r in con.execute('SELECT * FROM household_memberships ORDER BY member_id')]
        assert len(first) == 2 and all(re.fullmatch('[0-9a-f]{32}', r[0]) and r[2] is None and r[3:5] == ('active', 1) for r in first)
        assert fingerprint(con, domain.TABLES) == before
    with connection(app) as con:
        domain.schema_initialize(con)
        assert [tuple(r) for r in con.execute('SELECT * FROM household_memberships ORDER BY member_id')] == first
        assert fingerprint(con, domain.TABLES) == before
        assert domain.active_member(con, 'member2')['householdRole'] == 'member'
        assert domain.active_member(con, 'member2')['authVersion'] == 9


def test_schema_initialization_never_commits_and_partial_schema_is_rejected(legacy_app):
    app = legacy_app
    con = sqlite3.connect(path(app))
    try:
        assert_error('membership_transaction_required', domain.schema_initialize, con)
        con.execute('BEGIN IMMEDIATE')
        domain.schema_initialize(con)
        assert con.in_transaction
        con.rollback()
        assert not (set(domain.TABLES) & {r[0] for r in con.execute("SELECT name FROM sqlite_master")})
        con.execute(domain.SCHEMA_STATEMENTS[0])
        con.commit()
        con.execute('BEGIN IMMEDIATE')
        assert_error('membership_schema_incomplete', domain.schema_initialize, con)
        assert {r[0] for r in con.execute("SELECT name FROM sqlite_master")} & set(domain.TABLES) == {'household_memberships'}
        con.rollback()
    finally:
        con.close()


def test_missing_membership_is_not_recreated_at_restart_or_read(initialized):
    with connection(initialized) as con:
        con.execute("DELETE FROM household_memberships WHERE member_id='member2'")
    with connection(initialized) as con:
        assert domain.active_member(con, 'member2') is None
        assert_error('membership_missing', domain.schema_initialize, con)
        assert con.execute('SELECT count(*) FROM household_memberships').fetchone()[0] == 1


def test_bind_requires_actual_member_password_and_never_reassigns_existing_identity(initialized):
    with connection(initialized) as con:
        before = fingerprint(con)
        args = dict(household_id='default', member_id='member1', account_id=ACCOUNT1,
                    member_password='testing-password-two', expected_auth_version=1, expected_revision=1)
        assert_error('membership_password_required', command, domain.bind_account, con, **args)
        assert fingerprint(con) == before
        first = bind(con)
        assert first == domain.snapshot(con, 'default', 'member1')
        assert first['revision'] == 2
        args.update(member_password='testing-password-one', account_id=ACCOUNT2, expected_revision=2)
        assert_error('membership_already_bound', command, domain.bind_account, con, **args)
        assert_error('membership_already_bound', bind, con, 'member2', ACCOUNT1)
        assert domain.membership_record(con, account_id=ACCOUNT1)['member_id'] == 'member1'


def test_invitation_returns_secret_once_and_receipt_cannot_recover_token(initialized):
    key = 'a' * 32
    with connection(initialized) as con:
        first = invite(con, request_id=key)
        assert set(first) == {'invitation', 'token'} and len(first['token']) == 43
        assert first['invitation']['householdRole'] == 'member'
        second = invite(con, request_id=key)
        assert second == {'invitation': first['invitation']}
        raw = '\n'.join(con.iterdump())
        assert first['token'] not in raw
        stored = con.execute('SELECT token_hash FROM member_invitations').fetchone()[0]
        assert stored == hashlib.sha256(first['token'].encode()).hexdigest()
        receipt = domain.member_operation(con, member_id='member1', request_id=key)
        assert receipt == {'requestId': key, 'found': True, 'state': 'completed', 'result': second}
        assert not domain.member_operation(con, member_id='member2', request_id=key)['found']
        assert_error('membership_request_conflict', invite, con, request_id=key, intent_digest='f' * 64)
        assert len(domain.list_invitations(con, 'default', 'member1')) == 1


def test_third_person_joins_once_as_member_and_gets_unique_local_owner(initialized):
    with connection(initialized) as con:
        con.execute('INSERT OR REPLACE INTO private_finance(owner,data,revision) VALUES(?,?,3)', ('member1', '{"income":123,"unknown":null}'))
        private_before = [tuple(r) for r in con.execute('SELECT * FROM private_finance')]
        invitation = invite(con)
        proof = domain.inspect_invitation(con, invitation['token'])
        assert proof == invitation['invitation']
        joined = accept(con, invitation, request_id='b' * 32)
        assert re.fullmatch(r'm_[0-9a-f]{24}', joined['memberId'])
        assert joined['householdRole'] == 'member' and joined['revision'] == 1 and joined['state'] == 'active'
        assert set(joined) == {'id','householdId','memberId','memberName','householdRole','state','revision'}
        user = con.execute('SELECT username,password FROM users WHERE id=?', (joined['memberId'],)).fetchone()
        assert user[0] == joined['memberId'] and not check_password_hash(user[1], 'testing-password-one')
        assert accept(con, invitation, request_id='b' * 32) == joined
        assert_error('invitation_stale', accept, con, invitation, ACCOUNT2)
        assert len(domain.active_members(con)) == 3
        assert [tuple(r) for r in con.execute('SELECT * FROM private_finance')] == private_before
        assert not con.execute('SELECT 1 FROM private_finance WHERE owner=?', (joined['memberId'],)).fetchone()


@pytest.mark.parametrize('change', ['expired', 'revoked', 'role', 'version', 'inactive'])
def test_invitation_rechecks_expiry_revocation_and_original_inviter(initialized, change):
    with connection(initialized) as con:
        invitation = invite(con, now=1000)
        args = dict(invitation_id=invitation['invitation']['id'], expected_revision=1, now=1001)
        if change == 'expired':
            args['now'] = 1000 + domain.INVITATION_TTL
        elif change == 'revoked':
            command(domain.revoke_invitation, con, household_id='default', actor_member_id='member2',
                    invitation_id=args['invitation_id'], expected_revision=1, now=1001)
        elif change == 'role':
            con.execute("UPDATE users SET household_role='member' WHERE id='member1'")
        elif change == 'version':
            con.execute("UPDATE users SET auth_version=auth_version+1 WHERE id='member1'")
        else:
            remove(con, 'member1', actor='member2', now=1001)
        before = fingerprint(con)
        assert_error('invitation_stale' if change == 'revoked' else 'invitation_unavailable', domain.validate_invitation, con, **args)
        assert fingerprint(con) == before
        if change in ('role', 'version', 'inactive'):
            assert domain.list_invitations(con, 'default', 'member2', now=1001)[0]['state'] == 'invalid'


def test_pending_invitation_limit_and_used_invitation_cannot_be_revoked(initialized):
    with connection(initialized) as con:
        invites = [invite(con) for _ in range(20)]
        assert_error('invitation_limit', invite, con)
        accept(con, invites[0])
        invite(con)
        assert_error('invitation_unavailable', command, domain.revoke_invitation, con, household_id='default',
                     actor_member_id='member1', invitation_id=invites[0]['invitation']['id'], expected_revision=2)


def test_active_member_limit_uses_current_members_not_historical_slots(initialized):
    with connection(initialized) as con:
        invitation = invite(con)
        password = con.execute("SELECT password FROM users WHERE id='member1'").fetchone()[0]
        for n in range(98):
            uid = 'm_' + f'{n:024x}'
            con.execute("INSERT INTO users VALUES(?,?,?,?,1,'member')", (uid, uid, '合成成员', password))
            con.execute("INSERT INTO household_memberships VALUES(?,?,NULL,'active',1,0,0)", (f'{n:032x}', uid))
        before = fingerprint(con)
        assert_error('membership_limit', accept, con, invitation)
        assert fingerprint(con) == before
        remove(con, 'm_' + '0' * 24)
        assert accept(con, invitation)['state'] == 'active'
        assert len(domain.active_members(con)) == 100


def test_remove_revokes_real_cookies_browsers_and_preserves_private_owner(initialized):
    a, _ = member(initialized)
    b, _ = member(initialized, 2)
    b2, _ = member(initialized, 2)
    with connection(initialized) as con:
        old_member = tuple(con.execute("SELECT id,username,name,password FROM users WHERE id='member2'").fetchone())
        con.execute("INSERT OR REPLACE INTO private_finance VALUES('member2','{\"amount\":0,\"unknown\":null}',7)")
        old_finance = tuple(con.execute("SELECT * FROM private_finance WHERE owner='member2'").fetchone())
        generations = dict(con.execute('SELECT DISTINCT b.browser_hash,b.generation FROM member_session_browsers b JOIN member_sessions s ON s.browser_hash=b.browser_hash WHERE s.owner=\'member2\''))
        result = remove(con, 'member2', request_id='c' * 32)
        assert result['state'] == 'removed' and result['revision'] == 2
        assert domain.active_member(con, 'member2') is None
        assert not con.execute("SELECT 1 FROM member_sessions WHERE owner='member2' AND revoked_at IS NULL").fetchone()
        assert all(con.execute('SELECT generation FROM member_session_browsers WHERE browser_hash=?', (key,)).fetchone()[0] == value+1 for key, value in generations.items())
        assert tuple(con.execute("SELECT id,username,name,password FROM users WHERE id='member2'").fetchone()) == old_member
        assert tuple(con.execute("SELECT * FROM private_finance WHERE owner='member2'").fetchone()) == old_finance
        assert remove(con, 'member2', request_id='c' * 32) == result
    assert b.get('/api/state').status_code == 401 and b2.get('/api/state').status_code == 401
    assert b.get('/api/me').json['user'] is None and b2.get('/api/me').json['user'] is None
    assert a.get('/api/me').status_code == 200


def test_restore_same_account_keeps_id_private_data_and_does_not_restore_admin_or_cloud_work(initialized):
    with connection(initialized) as con:
        linked = bind(con, 'member2', ACCOUNT2)
        con.execute("INSERT OR REPLACE INTO private_finance VALUES('member2','{\"income\":345}',4)")
        con.execute("INSERT INTO cloud_accounts VALUES('synthetic','member2','google','client','subject','name','email','opaque-token-cipher',0)")
        for table, sql in (
            ('calendar_publications', "INSERT INTO calendar_publications(id,owner,journey_id,entity_id,source_id,account_id,provider,calendar_id,status,pending_data,created_at,updated_at) VALUES('p','member2','j','e','s','synthetic','google','cal','pending','private-payload','a','a')"),
            ('task_publications', "INSERT INTO task_publications(id,entity_id,owner,source_id,account_id,account_owner,provider,list_id,status,pending_data,created_at,updated_at) VALUES('p','e','member2','s','synthetic','member2','google','list','uncertain','private-payload','a','a')"),
        ):
            con.execute(sql)
        removed = remove(con, 'member2', revision=2)
        invitation = invite(con)
        restored = accept(con, invitation, ACCOUNT2)
        assert restored['id'] == linked['id'] and restored['memberId'] == 'member2'
        assert restored['revision'] == removed['revision'] + 1 and restored['householdRole'] == 'member'
        assert tuple(con.execute("SELECT tokens,needs_reauth FROM cloud_accounts WHERE id='synthetic'").fetchone()) == ('opaque-token-cipher', 1)
        for table in ('calendar_publications', 'task_publications'):
            assert tuple(con.execute('SELECT status,pending_data FROM ' + table + " WHERE id='p'").fetchone()) == ('paused', 'private-payload')
        assert con.execute("SELECT data FROM private_finance WHERE owner='member2'").fetchone()[0] == '{"income":345}'
        assert con.execute("SELECT auth_version FROM users WHERE id='member2'").fetchone()[0] == 3
        assert_error('membership_admin_required', command, domain.create_invitation, con, household_id='default', actor_member_id='member2', expected_auth_version=3)


def test_new_account_cannot_take_removed_members_private_identity(initialized):
    with connection(initialized) as con:
        original = bind(con, 'member2', ACCOUNT2)
        remove(con, 'member2', revision=2)
        different = accept(con, invite(con), ACCOUNT3)
        assert different['id'] != original['id'] and different['memberId'] != 'member2'
        assert domain.membership_record(con, account_id=ACCOUNT2)['state'] == 'removed'


def test_deactivation_also_pauses_other_owners_using_members_cloud_account(initialized):
    with connection(initialized) as con:
        con.execute("INSERT INTO cloud_accounts VALUES('synthetic','member2','google','client','subject','name','email','opaque-token-cipher',0)")
        con.execute("INSERT INTO calendar_publications(id,owner,journey_id,entity_id,source_id,account_id,provider,calendar_id,status,created_at,updated_at) VALUES('p','member1','j','e','s','synthetic','google','cal','publishing','a','a')")
        con.execute("INSERT INTO task_publications(id,entity_id,owner,source_id,account_id,account_owner,provider,list_id,status,created_at,updated_at) VALUES('p','e','member1','s','synthetic','member2','google','list','retry','a','a')")
        remove(con, 'member2')
        for table in ('calendar_publications', 'task_publications'):
            assert tuple(con.execute('SELECT owner,status,account_id FROM ' + table + " WHERE id='p'").fetchone()) == ('member1', 'paused', 'synthetic')
        assert domain.active_member(con, 'member1') is not None


def test_member_receipt_does_not_guess_when_two_owned_subjects_use_the_same_id(initialized):
    with connection(initialized) as con:
        key = '8' * 32
        bound = bind(con, request_id=key)
        created = invite(con, request_id=key)
        assert_error('membership_request_conflict', domain.member_operation, con, member_id='member1', request_id=key)
        assert domain.operation(con, subject='account:'+ACCOUNT1, request_id=key)['result'] == bound
        assert domain.operation(con, subject='member:member1', request_id=key)['result'] == {'invitation': created['invitation']}


def test_leave_requires_binding_and_historical_receipt_does_not_install_current_state(initialized):
    with connection(initialized) as con:
        args = dict(household_id='default', member_id='member1', account_id=ACCOUNT1, expected_auth_version=1, expected_revision=1)
        assert_error('membership_binding_required', command, domain.leave_membership, con, **args)
        bind(con)
        args['expected_revision'] = 2
        first = command(domain.leave_membership, con, request_id='d' * 32, **args)
        assert first['state'] == 'left'
        assert command(domain.leave_membership, con, request_id='d' * 32, **args) == first
        assert_error('membership_inactive', domain.member_operation, con, member_id='member1', request_id='d' * 32)
        account_receipt = domain.operation(con, subject='account:' + ACCOUNT1, request_id='d' * 32)
        assert account_receipt['result'] == first
        fresh_invite = command(domain.create_invitation, con, household_id='default', actor_member_id='member2', expected_auth_version=1)
        accept(con, fresh_invite, ACCOUNT1)
        assert command(domain.leave_membership, con, request_id='d' * 32, **args) == first
        assert domain.active_member(con, 'member1')['householdRole'] == 'member'
        assert len(domain.list_memberships(con, 'default', 'member1')) == 2
        assert_error('membership_admin_required', domain.list_memberships, con, 'default', 'member1', status='all')


def test_remove_checks_actor_version_and_member_revision_not_target_auth_version(initialized):
    with connection(initialized) as con:
        con.execute("UPDATE users SET auth_version=7 WHERE id='member2'")
        assert_error('membership_stale', remove, con, 'member2', av=2)
        assert_error('membership_stale', remove, con, 'member2', revision=2)
        assert remove(con, 'member2')['state'] == 'removed'
        assert con.execute("SELECT auth_version FROM users WHERE id='member2'").fetchone()[0] == 8


def test_last_active_admin_is_protected_even_when_inactive_admin_row_remains(initialized):
    with connection(initialized) as con:
        bind(con)
        remove(con, 'member2')
        before = fingerprint(con)
        assert_error('membership_last_admin', command, domain.leave_membership, con, household_id='default', member_id='member1', account_id=ACCOUNT1,
                     expected_auth_version=1, expected_revision=2)
        assert fingerprint(con) == before
        assert_error('membership_self_remove', remove, con, 'member1', revision=2)


def test_two_admin_leaves_serialize_and_exactly_one_is_refused(initialized):
    with connection(initialized) as con:
        bind(con); bind(con, 'member2', ACCOUNT2)
    barrier = Barrier(2)
    def worker(number):
        barrier.wait(timeout=10)
        try:
            with connection(initialized) as con:
                return command(domain.leave_membership, con, household_id='default', member_id='member'+str(number),
                               account_id=ACCOUNT1 if number == 1 else ACCOUNT2, expected_auth_version=1, expected_revision=2)['state']
        except domain.MembershipError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(worker, (1, 2))) == ['left', 'membership_last_admin']
    with connection(initialized) as con:
        assert len(domain.active_members(con)) == 1


@pytest.mark.parametrize('same_account', [False, True])
def test_concurrent_accept_and_retry_create_one_member(initialized, same_account):
    with connection(initialized) as con:
        invitation = invite(con)
    barrier = Barrier(2)
    def worker(number):
        barrier.wait(timeout=10)
        try:
            with connection(initialized) as con:
                result = accept(con, invitation, ACCOUNT3 if same_account or number == 1 else ACCOUNT2,
                                request_id='e' * 32 if same_account else str(number) * 32)
                return ('ok', result['id'])
        except domain.MembershipError as error:
            return ('error', error.code)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, (1, 2)))
    assert sum(r[0] == 'ok' for r in results) == (2 if same_account else 1)
    if same_account:
        assert results[0] == results[1]
    with connection(initialized) as con:
        assert con.execute('SELECT count(*) FROM users').fetchone()[0] == 3
        assert con.execute("SELECT count(*) FROM membership_operations WHERE kind='accept'").fetchone()[0] == 1


def test_failed_audit_rolls_back_membership_user_sessions_and_keeps_outer_transaction(initialized, monkeypatch):
    member(initialized, 2)
    with connection(initialized) as con:
        con.execute("INSERT INTO settings(id,data) VALUES('outer-owned','kept')")
        before = fingerprint(con)
        def fail(*args):
            raise RuntimeError('Synthetic audit failure')
        monkeypatch.setattr(domain, '_audit', fail)
        with pytest.raises(RuntimeError, match='Synthetic audit'):
            remove(con, 'member2')
        assert con.in_transaction and fingerprint(con) == before


def test_membership_audit_advances_state_revision_once_and_rolls_back_together(initialized, monkeypatch):
    with connection(initialized) as con:
        initial = con.execute("SELECT revision FROM settings WHERE id='meta'").fetchone()[0]
        invitation = invite(con, request_id='6' * 32)
        assert con.execute("SELECT revision FROM settings WHERE id='meta'").fetchone()[0] == initial + 1
        invite(con, request_id='6' * 32)
        assert con.execute("SELECT revision FROM settings WHERE id='meta'").fetchone()[0] == initial + 1
        accept(con, invitation)
        assert con.execute("SELECT revision FROM settings WHERE id='meta'").fetchone()[0] == initial + 2
        before = fingerprint(con)
        def fail(*args):
            raise RuntimeError('Synthetic receipt failure after audit and revision update')
        monkeypatch.setattr(domain, '_record', fail)
        with pytest.raises(RuntimeError, match='Synthetic receipt'):
            remove(con, 'member2')
        assert fingerprint(con) == before


def test_outer_rollback_removes_operation_and_retry_is_a_new_known_transaction(initialized):
    original = None
    with pytest.raises(RuntimeError):
        with connection(initialized) as con:
            original = invite(con, request_id='f' * 32)
            raise RuntimeError('Caller intentionally rolls back')
    with connection(initialized) as con:
        assert not domain.operation(con, subject='member:member1', request_id='f' * 32)['found']
        assert_error('invitation_not_found', domain.inspect_invitation, con, original['token'])
        fresh = invite(con, request_id='f' * 32)
        assert fresh['invitation']['id'] != original['invitation']['id']


@pytest.mark.parametrize('field,value', [('expected_auth_version', True), ('expected_auth_version', 0), ('request_id', 'A'*32),
                                        ('request_id', '0'*31), ('intent_digest', 'x'*64), ('now', float('inf'))])
def test_invalid_input_is_rejected_without_partial_writes(initialized, field, value):
    with connection(initialized) as con:
        before = fingerprint(con)
        args = dict(household_id='default', actor_member_id='member1', expected_auth_version=1,
                    request_id='a'*32, intent_digest='b'*64)
        args[field] = value
        assert_error('invalid_membership_request', domain.create_invitation, con, **args)
        assert fingerprint(con) == before


def test_coordinator_switch_receipt_is_bounded_and_not_reapplied(initialized):
    with connection(initialized) as con:
        bind(con)
        result = {'ok': True, 'householdId': 'default', 'memberId': 'member1', 'entry': '/app/home'}
        args = dict(subject='account:'+ACCOUNT1, request_id='9'*32, intent_digest='c'*64, result=result)
        assert domain.record_operation(con, **args) == result
        con.execute("UPDATE household_memberships SET state='left',revision=revision+1 WHERE member_id='member1'")
        assert domain.record_operation(con, **args) == result
        assert domain.active_member(con, 'member1') is None
        assert_error('membership_request_conflict', domain.record_operation, con, **{**args,'intent_digest':'d'*64})
        assert_error('invalid_membership_request', domain.record_operation, con, **{**args,'result':{**result,'cookie':'forbidden'}})
        assert not domain.operation(con, subject='account:'+ACCOUNT2, request_id='9'*32)['found']


def test_two_real_households_do_not_merge_same_local_ids_or_account_relationships(initialized, tmp_path, monkeypatch):
    from app import create_app
    other = create_app({'TESTING':True,'SECRET_KEY':'other-test-only','DATA_DIR':str(tmp_path/'other'), 'SESSION_COOKIE_SECURE':False})
    with connection(other) as con:
        domain.schema_initialize(con)
        second = bind(con)
    with connection(initialized) as con:
        first = bind(con)
        assert first['id'] != second['id']
        assert domain.membership_record(con, account_id=ACCOUNT1)['member_id'] == 'member1'
        remove(con, 'member2')
    with connection(other) as con:
        assert domain.active_member(con, 'member2') is not None
        assert domain.membership_record(con, account_id=ACCOUNT1)['id'] == second['id']
