"""Temporary real Flask/SQLite only; no provider, production or private data."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from flask import g
import pytest

import app as app_module
import sync_health as health


NOW = datetime(2026, 9, 15, 2, 0, 0, tzinfo=timezone.utc)
CLIENTS = {'google': 'synthetic-google-client', 'microsoft': 'synthetic-ms-client'}
SENTINEL = 'SYNTHETIC_PRIVATE_CREDENTIAL_NEVER_RETURN'


def no_network(*args, **kwargs):
    pytest.fail('sync-health attempted a provider/network operation')


def wire(application):
    """Keep this isolated test runnable before root wires the new registration."""
    if any(rule.rule == '/api/sync-health' for rule in application.url_map.iter_rules()):
        return application

    def db():
        if 'db' not in g:
            g.db = sqlite3.connect(Path(application.config['DATA_DIR']) / 'household.sqlite3')
            g.db.row_factory = sqlite3.Row
        return g.db

    def require_member():
        if not g.actor:
            raise app_module.Problem('请先登录', 401)
        if g.actor['role'] != 'member':
            raise app_module.Problem('电视是只读设备，请在手机或电脑上操作', 403)

    health.register_sync_health(application, db, require_member)
    return application


@pytest.fixture
def app(tmp_path, monkeypatch):
    original = app_module.create_app

    def factory(config=None):
        return wire(original(config))

    # HouseholdPlatform captures this factory for children as well, exercising
    # the actual signed routing cookie and each household's separate database.
    monkeypatch.setattr(app_module, 'create_app', factory)
    original_clock = health._clock
    monkeypatch.setattr(health, '_clock', lambda now=None: NOW if now is None else original_clock(now))
    return factory({
        'TESTING': True, 'SECRET_KEY': 'synthetic-sync-health-test-secret',
        'DATA_DIR': str(tmp_path), 'SESSION_COOKIE_SECURE': False,
        'PUBLIC_ORIGIN': 'http://localhost',
        'MEMBER1_PASSWORD': 'testing-password-one', 'MEMBER2_PASSWORD': 'testing-password-two',
        'GOOGLE_CLIENT_ID': CLIENTS['google'], 'GOOGLE_CLIENT_SECRET': 'synthetic-secret',
        'MICROSOFT_CLIENT_ID': CLIENTS['microsoft'], 'MICROSOFT_CLIENT_SECRET': 'synthetic-secret',
        'CLOUD_TRANSPORT': no_network, 'OAUTH_TRANSPORT': no_network,
        'CLOUD_PROVIDER_FACTORY': no_network,
    })


def login(app, number=1, password=None):
    client = app.test_client()
    response = client.post('/api/login', json={
        'username': f'member{number}',
        'password': password or 'testing-password-' + ('one' if number == 1 else 'two'),
    })
    assert response.status_code == 200
    return client, {'X-CSRF-Token': client.get('/api/me').json['csrf']}


def account(app, uid='account-1', owner='member1', provider='google', *, reauth=0, client_id=None, label=None):
    with app.extensions['cloud_accounts'].db() as con:
        con.execute('''INSERT INTO cloud_accounts(id,owner,provider,client_id,subject,name,email,tokens,needs_reauth)
            VALUES(?,?,?,?,?,?,?,?,?)''', (uid, owner, provider, client_id or CLIENTS[provider],
            SENTINEL + '-subject-' + uid, label or '合成账户-' + uid,
            SENTINEL + '@example.invalid', SENTINEL + '-tokens', reauth))
    return uid


def source(app, uid='source-1', aid='account-1', *, success=None, error='', failures=0, primary=0, kind='calendar'):
    with app.extensions['cloud_accounts'].db() as con:
        con.execute('''INSERT INTO cloud_sources(id,account_id,remote_id,kind,name,owner,is_primary,
            last_success,next_attempt,error,failures) VALUES(?,?,?,?,?,?,?,?,?,?,?)''', (
            uid, aid, SENTINEL + '-remote-' + uid, kind, '合成来源-' + uid, 'shared', primary,
            NOW.isoformat() if success is None else success, NOW.timestamp() + 30, error, failures))
    return uid


def publication(app, uid, *, kind='calendar', owner='member1', account_owner='member1',
                status='pending', review=0, title=None, entity=True):
    eid = 'entity-' + uid
    with app.extensions['cloud_accounts'].db() as con:
        con.execute("INSERT OR IGNORE INTO entities(id,kind,data,updated_at) VALUES('trip-health','trips','{}','now')")
        con.execute('''INSERT OR IGNORE INTO journey_workflows(id,trip_id,plan,created_by,created_at,updated_at)
            VALUES('journey-health','trip-health','{}','member1','now','now')''')
        if entity:
            con.execute('INSERT INTO entities(id,kind,data,updated_at) VALUES(?,?,?,?)', (
                eid, 'events' if kind == 'calendar' else 'tasks',
                json.dumps({'title': title or '合成发布-' + uid, 'note': SENTINEL}), NOW.isoformat()))
        if kind == 'calendar':
            con.execute('''INSERT INTO calendar_publications(id,owner,journey_id,entity_id,source_id,account_id,
                provider,calendar_id,remote_id,pending_data,error,status,review_required,next_attempt,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
                uid, owner, 'journey-health', eid, 'source-1', 'account-1', 'google', SENTINEL,
                SENTINEL, SENTINEL, SENTINEL, status, review, NOW.timestamp() + 60, NOW.isoformat(), NOW.isoformat()))
        else:
            con.execute('''INSERT INTO task_publications(id,entity_id,owner,source_id,account_id,account_owner,
                provider,list_id,journey_id,remote_id,baseline_data,pending_data,error,status,next_attempt,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
                uid, eid, owner, 'source-1', 'account-1', account_owner, 'google', SENTINEL,
                'journey-health', SENTINEL, SENTINEL, SENTINEL, SENTINEL, status,
                NOW.timestamp() + 60, NOW.isoformat(), NOW.isoformat()))
    return eid


def summary(app):
    with app.extensions['cloud_accounts'].db() as con:
        return health.household_health(con, CLIENTS, NOW)


def dump_hash(app):
    with app.extensions['cloud_accounts'].db() as con:
        return hashlib.sha256('\n'.join(con.iterdump()).encode()).hexdigest()


@pytest.mark.parametrize('success,error,failures,reauth,client_id,state', [
    ('', '', 0, 0, None, 'waiting'),
    (' ', '', 0, 0, None, 'unknown'),
    ('not-a-date', '', 0, 0, None, 'unknown'),
    ('2026-09-15T01:59:00', '', 0, 0, None, 'unknown'),
    ('2026-09-15', '', 0, 0, None, 'unknown'),
    ((NOW + timedelta(microseconds=1)).isoformat(), '', 0, 0, None, 'unknown'),
    ((NOW - timedelta(seconds=301)).isoformat(), '', 0, 0, None, 'delayed'),
    ((NOW - timedelta(seconds=300, microseconds=1)).isoformat(), '', 0, 0, None, 'delayed'),
    ((NOW - timedelta(seconds=300)).isoformat(), '', 0, 0, None, 'current'),
    ('2026-09-15T10:00:00+08:00', '', 0, 0, None, 'current'),
    ('2026-09-15T02:00:00Z', '', 0, 0, None, 'current'),
    ('', SENTINEL, 0, 0, None, 'error'),
    ('not-a-date', '', 1, 0, None, 'error'),
    ('', SENTINEL, 2, 1, None, 'needs_authorization'),
    (NOW.isoformat(), '', 0, 0, 'old-client', 'needs_authorization'),
])
def test_source_states_and_priority(app, success, error, failures, reauth, client_id, state):
    account(app, reauth=reauth, client_id=client_id)
    source(app, success=success, error=error, failures=failures)
    client, _ = login(app)
    response = client.get('/api/sync-health')
    assert response.status_code == 200
    result = response.json
    item = result['accounts'][0]['sources'][0]
    assert item['state'] == state
    assert result['household']['sourceCounts'][state] == 1
    assert (result['household']['lastCompleteSuccess'] is not None) == (state == 'current')
    if state == 'unknown':
        assert item['lastSuccess'] is None and item['ageSeconds'] is None
        assert result['household']['latestSuccess'] is None
    assert SENTINEL not in response.get_data(as_text=True)


@pytest.mark.parametrize('provider', ['google', 'microsoft'])
def test_removed_client_configuration_requires_authorization(app, provider):
    account(app, provider=provider)
    source(app)
    app.config[provider.upper() + '_CLIENT_ID'] = ''
    client, _ = login(app)
    value = client.get('/api/sync-health').json
    assert value['household']['state'] == 'needs_attention'
    assert value['household']['reauthAccounts'] == 1
    assert value['accounts'][0]['sources'][0]['reasonCode'] == 'client_configuration_changed'


def test_new_success_cannot_hide_stale_error_or_waiting_source(app):
    account(app)
    source(app, uid='fresh')
    stale = (NOW - timedelta(minutes=20)).isoformat()
    source(app, uid='stale', success=stale)
    source(app, uid='failed', success=NOW.isoformat(), error=SENTINEL)
    source(app, uid='awaiting', success='')
    result = summary(app)
    assert result['latestSuccess'] == NOW.isoformat()
    assert result['oldestSuccess'] == stale
    assert result['lastCompleteSuccess'] is None
    assert result['state'] == 'needs_attention'
    assert result['sourceCounts'] == dict(current=1, waiting=1, delayed=1, error=1, needs_authorization=0, unknown=0)
    assert set(result) == {'state', 'connectedAccounts', 'selectedSources', 'sourceCounts',
                           'reauthAccounts', 'latestSuccess', 'oldestSuccess', 'lastCompleteSuccess'}


def test_complete_success_uses_oldest_actual_success_not_account_or_queue_time(app):
    account(app)
    source(app, uid='one', success=(NOW - timedelta(seconds=10)).isoformat())
    source(app, uid='two', success=(NOW - timedelta(seconds=120)).isoformat())
    publication(app, 'recent-queue-edit', status='published')
    result = summary(app)
    assert result['state'] == 'current'
    assert result['lastCompleteSuccess'] == result['oldestSuccess'] == (NOW - timedelta(seconds=120)).isoformat()
    with app.extensions['cloud_accounts'].db() as con:
        con.execute("UPDATE cloud_sources SET last_success=''")
    value = summary(app)
    assert value['state'] == 'waiting'
    assert value['latestSuccess'] is None and value['lastCompleteSuccess'] is None


def test_empty_unselected_and_unselected_reauth(app):
    assert summary(app)['state'] == 'not_connected'
    account(app)
    assert summary(app)['state'] == 'not_selected'
    client, _ = login(app)
    assert client.get('/api/sync-health').json['accounts'][0]['state'] == 'not_selected'
    with app.extensions['cloud_accounts'].db() as con:
        con.execute('UPDATE cloud_accounts SET needs_reauth=1')
    result = client.get('/api/sync-health').json
    assert result['household']['state'] == 'needs_attention'
    assert result['household']['reauthAccounts'] == 1


def test_member_details_scope_names_and_publication_manage_permissions(app):
    account(app, owner='member1', label='FIRST_MEMBER_ACCOUNT')
    source(app, uid='FIRST_MEMBER_SOURCE')
    account(app, uid='account-2', owner='member2', label='SECOND_MEMBER_ACCOUNT')
    source(app, uid='SECOND_MEMBER_SOURCE', aid='account-2', error=SENTINEL)
    publication(app, 'calendar-own', owner='member1', title='FIRST_CALENDAR')
    publication(app, 'calendar-other', owner='member2', title='SECOND_CALENDAR')
    publication(app, 'task-owner', kind='tasks', owner='member1', account_owner='member2')
    publication(app, 'task-account-owner', kind='tasks', owner='member2', account_owner='member1')
    publication(app, 'task-other', kind='tasks', owner='member2', account_owner='member2', title='SECOND_PRIVATE_QUEUE')
    one, _ = login(app)
    two, _ = login(app, 2)
    first, second = one.get('/api/sync-health').json, two.get('/api/sync-health').json
    assert first['household'] == second['household']
    assert first['household']['connectedAccounts'] == 2
    assert [row['label'] for row in first['accounts']] == ['FIRST_MEMBER_ACCOUNT']
    assert [row['id'] for row in first['accounts'][0]['sources']] == ['FIRST_MEMBER_SOURCE']
    assert {row['id'] for row in first['publications']['calendar']['items']} == {'calendar-own'}
    assert {row['id'] for row in first['publications']['tasks']['items']} == {'task-owner', 'task-account-owner'}
    serialized = json.dumps(first)
    for private in ('SECOND_MEMBER_ACCOUNT', 'SECOND_MEMBER_SOURCE', 'SECOND_CALENDAR', 'SECOND_PRIVATE_QUEUE', SENTINEL):
        assert private not in serialized
    assert first['publications']['calendar']['items'][0]['action'] == {'kind': 'calendar', 'target': 'journey-health'}
    for row in first['publications']['tasks']['items']:
        assert row['action'] == {'kind': 'tasks', 'target': row['entityId']}


def test_priority_counts_truncation_and_published_not_in_items(app):
    for index in range(105):
        publication(app, 'ordinary-' + str(index), status='pending')
    publication(app, 'published', status='published')
    publication(app, 'review-paused', status='paused', review=1)
    publication(app, 'auth', status='needs_authorization')
    publication(app, 'failed', status='error')
    client, _ = login(app)
    value = client.get('/api/sync-health').json['publications']['calendar']
    assert value['truncated'] is True and len(value['items']) == 100
    assert value['counts'] == {'pending': 105, 'published': 1, 'paused': 1, 'needs_authorization': 1, 'error': 1}
    assert [row['id'] for row in value['items'][:3]] == ['review-paused', 'auth', 'failed']
    assert value['items'][0]['reviewRequired'] is True
    assert all(row['status'] != 'published' for row in value['items'])


@pytest.mark.parametrize('kind', ['calendar', 'tasks'])
def test_removed_local_target_and_malformed_timestamps_have_no_action(app, kind):
    publication(app, 'deleted', kind=kind, entity=False, status='local_deleted')
    with app.extensions['cloud_accounts'].db() as con:
        table = 'calendar_publications' if kind == 'calendar' else 'task_publications'
        con.execute(f"UPDATE {table} SET updated_at='naive-invalid',next_attempt=1e999")
    client, _ = login(app)
    item = client.get('/api/sync-health').json['publications'][kind]['items'][0]
    assert item['action'] is None and item['updatedAt'] is None and item['nextAttemptAt'] is None
    assert SENTINEL not in json.dumps(item)


def test_get_is_read_only_and_sensitive_columns_and_provider_access_are_forbidden(app, monkeypatch):
    account(app)
    source(app, error=SENTINEL)
    publication(app, 'one')
    client, _ = login(app)
    before = dump_hash(app)
    operations = []
    original = health._source_snapshot
    denied_writes = {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE,
                     sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_DROP_TABLE, sqlite3.SQLITE_ALTER_TABLE}

    def authorizer(action, first, second, database, caller):
        operations.append((action, first, second))
        if action in denied_writes:
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_READ:
            if first == 'cloud_accounts' and second in {'tokens', 'email', 'subject'}:
                return sqlite3.SQLITE_DENY
            if first in {'calendar_publications', 'task_publications'} and second in {
                    'error', 'pending_data', 'baseline_data', 'remote_id', 'etag'}:
                return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def checked(con, *args):
        con.set_authorizer(authorizer)
        return original(con, *args)

    monkeypatch.setattr(health, '_source_snapshot', checked)
    monkeypatch.setattr(app.extensions['cloud_accounts'], 'active_provider', no_network)
    monkeypatch.setattr(app.extensions['cloud_accounts'], 'decrypt', no_network)
    response = client.get('/api/sync-health')
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-store'
    assert not response.headers.getlist('Set-Cookie')
    assert dump_hash(app) == before
    assert not any(action in denied_writes for action, _, _ in operations)


def test_api_uses_one_snapshot_when_sync_commits_between_selects(app, monkeypatch):
    account(app, label='BEFORE_ACCOUNT')
    source(app, success='')
    publication(app, 'before', status='pending')
    client, _ = login(app)
    original = health._rows
    changed = False

    def interleaved(con, sql, parameters=()):
        nonlocal changed
        rows = original(con, sql, parameters)
        if not changed and sql.startswith('SELECT id,provider,client_id,needs_reauth'):
            changed = True
            with app.extensions['cloud_accounts'].db() as writer:
                writer.execute("UPDATE cloud_accounts SET name='AFTER_ACCOUNT'")
                writer.execute('UPDATE cloud_sources SET last_success=?', (NOW.isoformat(),))
                writer.execute("UPDATE calendar_publications SET status='published'")
        return rows

    monkeypatch.setattr(health, '_rows', interleaved)
    first = client.get('/api/sync-health').json
    assert changed
    assert first['household']['state'] == 'waiting'
    assert first['accounts'][0]['label'] == 'BEFORE_ACCOUNT'
    assert first['publications']['calendar']['counts'] == {'pending': 1}
    second = client.get('/api/sync-health').json
    assert second['household']['state'] == 'current'
    assert second['accounts'][0]['label'] == 'AFTER_ACCOUNT'
    assert second['publications']['calendar']['counts'] == {'published': 1}


def test_summary_owns_only_its_transaction_and_reads_aware_clock(app):
    account(app)
    source(app)
    with app.extensions['cloud_accounts'].db() as con:
        statements = []
        con.set_trace_callback(statements.append)
        result = health.household_health(con, CLIENTS, NOW.timestamp())
        assert result['state'] == 'current' and not con.in_transaction
        assert statements[0] == 'BEGIN' and statements[-1] == 'ROLLBACK'
        con.execute('BEGIN')
        con.execute('UPDATE cloud_sources SET failures=1')
        statements.clear()
        assert health.household_health(con, CLIENTS, NOW)['state'] == 'needs_attention'
        assert con.in_transaction
        assert not any(sql in {'BEGIN', 'COMMIT', 'ROLLBACK'} for sql in statements)
        con.rollback()
    assert summary(app)['state'] == 'current'
    with pytest.raises(ValueError):
        with app.extensions['cloud_accounts'].db() as con:
            health.household_health(con, CLIENTS, datetime(2026, 1, 1))


def test_storage_failure_never_returns_partial_private_response_or_raw_error(app, monkeypatch):
    account(app, label='PRIVATE_LABEL')
    source(app)
    client, _ = login(app)

    def unavailable(*args):
        raise sqlite3.OperationalError(SENTINEL)

    monkeypatch.setattr(health, '_publications', unavailable)
    response = client.get('/api/sync-health')
    assert response.status_code == 503
    assert response.json == {'error': '同步状态暂时无法读取，请稍后刷新', 'reasonCode': 'sync_health_unavailable'}
    assert SENTINEL not in response.get_data(as_text=True) and 'PRIVATE_LABEL' not in response.get_data(as_text=True)


def test_anonymous_tv_rejected_and_mutation_methods_not_registered(app):
    anonymous = app.test_client()
    assert anonymous.get('/api/sync-health').status_code == 401
    member, headers = login(app)
    television = app.test_client()
    pair = television.post('/api/pair/start', json={}).json
    assert member.post('/api/pair/approve', json={'code': pair['code'], 'name': '合成电视', 'focus': 'member1'}, headers=headers).status_code == 200
    assert television.post('/api/pair/poll', json={'secret': pair['secret']}).json['approved']
    response = television.get('/api/sync-health')
    assert response.status_code == 403 and 'accounts' not in response.json
    for method in ('post', 'patch', 'put', 'delete'):
        assert getattr(member, method)('/api/sync-health', json={}, headers=headers).status_code == 405


def test_actual_household_routing_isolated_even_same_member_account_source_and_publication_ids(app):
    account(app, label='FIRST_HOUSEHOLD_ACCOUNT')
    source(app, error=SENTINEL)
    publication(app, 'same-id', title='FIRST_HOUSEHOLD_TITLE')
    primary, headers = login(app)
    invitation = primary.post('/api/spaces/invitations', json={}, headers=headers).json['invitation']
    second = app.test_client()
    redeemed = second.post('/api/spaces/redeem', json={
        'invitation': invitation, 'name': '合成第二户', 'slug': 'health-other',
        'MEMBER1_PASSWORD': 'other-health-password-one', 'MEMBER2_PASSWORD': 'other-health-password-two',
    })
    assert redeemed.status_code == 201
    assert second.get(redeemed.json['entry']).status_code == 303
    assert second.get('/api/sync-health').status_code == 401
    assert second.post('/api/login', json={'username': 'member1', 'password': 'other-health-password-one'}).status_code == 200
    platform = app.extensions['household_platform']
    child = next(value for value in platform.cache.values() if value.config['DATA_DIR'] != app.config['DATA_DIR'])
    account(child, label='SECOND_HOUSEHOLD_ACCOUNT')
    source(child)
    publication(child, 'same-id', title='SECOND_HOUSEHOLD_TITLE')
    first_value, second_value = primary.get('/api/sync-health').json, second.get('/api/sync-health').json
    assert first_value['household']['state'] == 'needs_attention'
    assert second_value['household']['state'] == 'current'
    assert second_value['household']['connectedAccounts'] == 1
    assert second_value['accounts'][0]['id'] == first_value['accounts'][0]['id'] == 'account-1'
    assert 'FIRST_HOUSEHOLD' not in json.dumps(second_value)
    assert 'SECOND_HOUSEHOLD' not in json.dumps(first_value)
    second.set_cookie('session', primary.get_cookie('session').value)
    assert second.get('/api/sync-health').status_code == 401


@pytest.mark.parametrize('role', ['member', 'tv'])
def test_state_health_is_aggregate_and_age_changes_without_meta_revision(app, monkeypatch, role):
    account(app, label='ACCOUNT_NAME_NOT_IN_HEALTH')
    source(app, uid='SOURCE_ID_NOT_IN_HEALTH')
    member, headers = login(app)
    client = member
    if role == 'tv':
        client = app.test_client()
        pair = client.post('/api/pair/start', json={}).json
        assert member.post('/api/pair/approve', json={
            'code': pair['code'], 'name': '合成电视', 'focus': 'member1',
        }, headers=headers).status_code == 200
        assert client.post('/api/pair/poll', json={'secret': pair['secret']}).json['approved']
    first = client.get('/api/state')
    assert first.status_code == 200
    first_health = first.json['sync']['health']
    assert first_health['state'] == 'current'
    assert first_health['lastCompleteSuccess'] == NOW.isoformat()
    assert all(value not in json.dumps(first_health) for value in (
        'ACCOUNT_NAME_NOT_IN_HEALTH', 'SOURCE_ID_NOT_IN_HEALTH', SENTINEL))
    assert set(first_health) == {'state', 'connectedAccounts', 'selectedSources', 'sourceCounts',
                                'reauthAccounts', 'latestSuccess', 'oldestSuccess', 'lastCompleteSuccess'}
    # The additive aggregate does not remove the existing source-picker fields.
    assert {'mode', 'taskIntervalSeconds', 'calendarIntervalSeconds', 'configured', 'connectedAccounts',
            'selectedSources', 'lastSuccess', 'error', 'primaryTaskSource', 'taskSources'} <= first.json['sync'].keys()
    before = dump_hash(app)
    monkeypatch.setattr(health, '_clock', lambda now=None: NOW + timedelta(seconds=301))
    second = client.get('/api/state')
    assert second.status_code == 200
    assert second.json['revision'] == first.json['revision']
    assert second.json['sync']['health']['state'] == 'needs_attention'
    assert second.json['sync']['health']['sourceCounts']['delayed'] == 1
    assert second.json['sync']['health']['lastCompleteSuccess'] is None
    assert dump_hash(app) == before
    if role == 'tv':
        assert client.get('/api/sync-health').status_code == 403


def test_summary_supports_plain_sqlite_rows_and_pure_read_transaction(app):
    account(app)
    source(app)
    with sqlite3.connect(Path(app.config['DATA_DIR']) / 'household.sqlite3') as con:
        assert con.row_factory is None
        result = health.household_health(con, CLIENTS, NOW)
        assert result['state'] == 'current'
        assert not con.in_transaction and con.total_changes == 0
