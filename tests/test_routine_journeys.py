"""Real local routine/queue/journey/settlement/export flows; synthetic inputs only."""
from contextlib import closing
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import time
from types import SimpleNamespace

import pytest

from app import create_app
import household_routines
from test_app import member
from test_data_portability import unpack
from test_household_spaces import create_space
from test_journey_workflows import apply as apply_journey, detail, plan, preview as preview_journey
from test_shopping_media import pair_tv, upload
from test_shopping_settlement_journeys import import_payment, later_plan, monetary_snapshot, settled
from test_task_publish import Remote


PREFIX = '/api/routines'
ROOT = Path(__file__).resolve().parents[1]
DEPENDENCIES = [
    'app.py', 'household_routines.py', 'household_spaces.py', 'member_sessions.py',
    'journey_workflows.py', 'journey_time.py', 'shopping_media.py', 'shopping_settlement.py',
    'finance_hub.py', 'financial_files.py', 'task_publish.py', 'cloud_accounts.py',
    'cloud_providers.py', 'data_portability.py', 'sync_worker.py', 'home_assistant.py',
    'tests/test_routine_journeys.py', 'tests/test_app.py', 'tests/test_data_portability.py',
    'tests/test_household_spaces.py', 'tests/test_journey_workflows.py',
    'tests/test_shopping_media.py', 'tests/test_shopping_settlement_journeys.py',
    'tests/test_task_publish.py', 'requirements.txt', 'pytest.ini',
]


@pytest.fixture(scope='module', autouse=True)
def source_provenance():
    before = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in DEPENDENCIES}
    yield
    after = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in DEPENDENCIES}
    assert before == after, 'Routine integration dependencies changed during verification'
    print(json.dumps({'routineJourneySourceHashes': after, 'sourceUnchanged': True}, sort_keys=True))


@pytest.fixture
def world(tmp_path, monkeypatch):
    def deny_network(*_args, **_kwargs):
        raise AssertionError('External network is forbidden in routine integration verification')

    monkeypatch.setattr(socket.socket, 'connect', deny_network)
    clock = [date(2026, 9, 15)]
    monkeypatch.setattr(household_routines, 'today', lambda: clock[0])
    remote = Remote()
    config = {
        'TESTING': True, 'SECRET_KEY': 'synthetic-routine-cross-workflow-secret',
        'DATA_DIR': str(tmp_path), 'SESSION_COOKIE_SECURE': False, 'PUBLIC_ORIGIN': 'http://localhost',
        'MEMBER1_PASSWORD': 'testing-password-one', 'MEMBER2_PASSWORD': 'testing-password-two',
        'MICROSOFT_CLIENT_ID': '', 'MICROSOFT_CLIENT_SECRET': '',
        'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': '', 'OPENAI_API_KEY': '', 'OPENAI_MODEL': '',
        'CLOUD_TRANSPORT': remote.transport,
    }
    app = create_app(config)
    client, headers = member(app)
    return SimpleNamespace(app=app, client=client, headers=headers, clock=clock, config=config, remote=remote)


def template(kind='tasks', **changes):
    value = {'title': '每期合成家务', 'owner': 'member2', 'note': '固定模板说明'}
    if kind == 'shopping':
        value.update(title='每期合成补货', quantity='2 件', budget=8000)
    return {**value, **changes}


def schedule(**changes):
    return {'frequency': 'weekly', 'interval': 1, 'anchor': '2026-09-19',
            'timeZone': 'Asia/Shanghai', 'monthEnd': 'clamp', **changes}


def preview(client, headers, payload):
    response = client.post(PREFIX + '/preview', json=payload, headers=headers)
    assert response.status_code == 200, response.json
    assert response.json['previewToken']
    return response.json


def confirm(client, headers, pending):
    response = client.post(PREFIX + '/confirm', json={'previewToken': pending['previewToken']}, headers=headers)
    assert response.status_code == 200, response.json
    return response.json


def create(world, kind='tasks', **changes):
    payload = {'operation': 'create', 'kind': kind, 'template': template(kind), 'schedule': schedule(), **changes}
    return confirm(world.client, world.headers, preview(world.client, world.headers, payload))


def current(client, plan_id):
    response = client.get(PREFIX + '/context', query_string={'planId': plan_id, 'includeArchived': 'true'})
    assert response.status_code == 200, response.json
    return next(value for value in response.json['plans'] if value['id'] == plan_id)


def entity(client, kind, uid):
    return next(value for value in client.get('/api/state').json[kind] if value['id'] == uid)


def edit(client, headers, kind, uid, **changes):
    value = entity(client, kind, uid)
    response = client.patch('/api/items/' + kind + '/' + uid,
                            json={'revision': value['revision'], **changes}, headers=headers)
    assert response.status_code == 200, response.json
    return entity(client, kind, uid)


def action(world, plan_id, operation, **changes):
    row = current(world.client, plan_id)
    pending = preview(world.client, world.headers,
                      {'operation': operation, 'planId': plan_id, 'revision': row['revision'], **changes})
    return confirm(world.client, world.headers, pending)


def tick(world, on=None):
    if on:
        world.clock[0] = date.fromisoformat(on)
    world.app.extensions['household_routines'].tick()


def rows(world, table):
    with closing(sqlite3.connect(Path(world.app.config['DATA_DIR']) / 'household.sqlite3')) as con:
        return con.execute('SELECT * FROM ' + table + ' ORDER BY rowid').fetchall()


@pytest.mark.parametrize('kind', ['tasks', 'shopping'])
def test_local_completion_after_absence_generates_one_next_period_and_survives_restart(world, kind):
    created = create(world, kind)
    plan_id, first_id = created['plan']['id'], created['generated']['id']
    first = current(world.client, plan_id)['current']
    assert first['scheduledOn'] == '2026-09-19'
    edit(world.client, world.headers, kind, first_id, done=True)
    original = entity(world.client, kind, first_id)
    tick(world, '2026-10-06')
    following = current(world.client, plan_id)
    assert following['current']['scheduledOn'] == '2026-10-10'
    assert following['current']['entityId'] != first_id
    assert entity(world.client, kind, first_id) == original
    assert len(world.client.get('/api/state').json[kind]) == 2
    stable = rows(world, 'routine_occurrences')
    tick(world)
    world.app = create_app(world.config)
    tick(world)
    assert rows(world, 'routine_occurrences') == stable
    assert len(world.client.get('/api/state').json[kind]) == 2
    assert rows(world, 'task_publications') == []
    assert world.remote.calls == []


@pytest.mark.parametrize('provider', ['microsoft', 'google'])
def test_confirmed_cloud_completion_flows_back_then_generates_unpublished_local_period(world, provider):
    world.app.config[provider.upper() + '_CLIENT_ID'] = 'synthetic-routine-client'
    world.app.config[provider.upper() + '_CLIENT_SECRET'] = 'synthetic-routine-secret'
    accounts = world.app.extensions['cloud_accounts']
    scope = 'User.Read Calendars.Read Tasks.ReadWrite' if provider == 'microsoft' else 'https://www.googleapis.com/auth/tasks'
    token = accounts.encrypt({'access_token': 'synthetic-routine-token', 'scope': scope,
                              'expires_at': time.time() + 3600})
    with accounts.db() as con:
        con.execute('INSERT INTO cloud_accounts(id,owner,provider,client_id,subject,name,email,tokens) VALUES(?,?,?,?,?,?,?,?)',
                    ('routine-account', 'member1', provider, 'synthetic-routine-client', 'synthetic-subject',
                     '合成主清单账户', 'synthetic@example.invalid', token))
        con.execute("INSERT INTO cloud_sources(id,account_id,remote_id,kind,name,owner,is_primary) VALUES(?,?,?,'tasks',?,'shared',1)",
                    ('routine-source', 'routine-account', 'list-1', '合成主清单'))
    created = create(world)
    first_id = created['generated']['id']
    assert not rows(world, 'task_publications') and not world.remote.calls
    pending = world.client.post('/api/task-publish/preview', json={'entityIds': [first_id], 'sourceId': 'routine-source'}, headers=world.headers)
    assert pending.status_code == 200, pending.json
    result = world.client.post('/api/task-publish/confirm', json={'previewToken': pending.json['previewToken']}, headers=world.headers)
    assert result.status_code == 200, result.json
    publication_id = result.json['publicationIds'][0]
    queue = world.app.extensions['task_publish']
    queue.process(publication_id)
    assert world.remote.created == 1
    remote_row = next(iter(world.remote.records.values()))
    remote_row['status'] = 'completed'
    remote_row['@odata.etag' if provider == 'microsoft' else 'etag'] = '"completed-remote"'
    queue.process(publication_id)
    assert entity(world.client, 'tasks', first_id)['done'] is True
    tick(world, '2026-09-19')
    following = current(world.client, created['plan']['id'])['current']
    assert following['scheduledOn'] == '2026-09-26' and following['entityId'] != first_id
    assert entity(world.client, 'tasks', following['entityId'])['done'] is False
    assert entity(world.client, 'tasks', following['entityId'])['owner'] == 'member2'
    assert len(rows(world, 'task_publications')) == 1
    with accounts.db() as con:
        assert con.execute('SELECT entity_id FROM task_publications').fetchone()[0] == first_id
        assert con.execute("SELECT count(*) FROM entities WHERE id LIKE 'cloud-%'").fetchone()[0] == 0
    queue.process(publication_id)
    tick(world)
    assert world.remote.created == 1 and world.remote.patched == 0


def test_settlement_completion_preserves_private_receipts_photos_and_money_but_cleans_next_purchase(world):
    created = create(world, 'shopping')
    uid = created['generated']['id']
    photo = upload(world.client, world.headers)
    purchase = edit(world.client, world.headers, 'shopping', uid, photoIds=[photo])
    payment = import_payment(world.client, world.headers, marker='PRIVATE_ROUTINE_PAYMENT')
    _, settlement = settled(world.client, world.headers, purchase, payment, amount=7900, done=True)
    original = entity(world.client, 'shopping', uid)
    money = monetary_snapshot(world.app)
    private_rows = {name: rows(world, name) for name in ('hub_shopping_settlements', 'hub_shopping_settlement_receipts', 'photo_refs')}
    tick(world, '2026-09-19')
    following = current(world.client, created['plan']['id'])['current']
    next_item = entity(world.client, 'shopping', following['entityId'])
    assert next_item['id'] != uid and next_item['actual'] is None and next_item['done'] is False
    assert next_item['photoIds'] == [] and next_item['budget'] == 8000 and next_item['quantity'] == '2 件'
    assert not any(next_item.get(key) for key in ('tripId', 'journeyId', 'workflowKey', 'paymentId', 'sync'))
    assert entity(world.client, 'shopping', uid) == original
    assert original['actual'] == 7900 and original['photoIds'] == [photo] and original['done']
    assert private_rows == {name: rows(world, name) for name in private_rows}
    assert monetary_snapshot(world.app) == money
    partner, partner_headers = member(world.app, 2)
    tv = pair_tv(world.app, world.client, world.headers)
    for observer in (partner, tv):
        shared = observer.get('/api/state')
        assert shared.status_code == 200 and 'PRIVATE_ROUTINE_PAYMENT' not in shared.get_data(as_text=True)
        assert observer.get('/api/photos/' + photo).status_code == 200
    assert partner.get('/api/finance-hub/shopping-settlements/context', query_string={'linkId': settlement['link']['id']}).status_code == 404
    assert tv.get(PREFIX + '/context').status_code == 403
    assert tv.get('/api/finance-hub/shopping-settlements/context').status_code == 403


def test_adopted_travel_task_rescheduling_does_not_rewrite_rule_or_next_period(world):
    created = create(world)
    uid, rule_id = created['generated']['id'], created['plan']['id']
    original_rule = current(world.client, rule_id)
    trip = world.client.post('/api/items/trips', json={
        'title': '合成旅程', 'destination': '东京', 'start': '2026-12-03', 'end': '2026-12-09',
        'budget': 2000000, 'saved': 500000, 'paid': 250000,
    }, headers=world.headers)
    assert trip.status_code == 201, trip.json
    trip_id = trip.json['id']
    edit(world.client, world.headers, 'tasks', uid, title='本期为旅行临时改名', due='2026-12-01', tripId=trip_id)
    value = plan(checklist=[{'key': 'existing-' + uid, 'title': '被旅行采用的本期任务',
                            'owner': 'member1', 'due': '2026-12-01', 'note': '只影响本期'}])
    pending = preview_journey(world.client, world.headers, value, tripId=trip_id, tripRevision=1)
    accepted = apply_journey(world.client, world.headers, pending, 'routine-adopt-travel-task')
    assert accepted.status_code == 201, accepted.json
    journey = detail(world.client, accepted.json['id'])
    assert any(row['id'] == uid for row in journey['tasks'])
    pending = preview_journey(world.client, world.headers, later_plan(journey['plan']),
                              journeyId=journey['id'], revision=journey['revision'])
    assert apply_journey(world.client, world.headers, pending, 'routine-reschedule-travel').status_code == 200
    original_period = edit(world.client, world.headers, 'tasks', uid, done=True)
    tick(world, '2026-09-19')
    following = current(world.client, rule_id)
    assert following['template'] == original_rule['template'] and following['schedule'] == original_rule['schedule']
    assert following['current']['scheduledOn'] == '2026-09-26'
    next_item = entity(world.client, 'tasks', following['current']['entityId'])
    assert next_item['title'] == template()['title'] and next_item['owner'] == 'member2'
    assert next_item['due'] == '2026-09-26'
    assert not any(next_item.get(key) for key in ('tripId', 'journeyId', 'workflowKey'))
    assert entity(world.client, 'tasks', uid) == original_period
    trip_entity = entity(world.client, 'trips', trip_id)
    deleted = world.client.delete('/api/items/trips/' + trip_id, json={'revision': trip_entity['revision']}, headers=world.headers)
    assert deleted.status_code == 200
    assert entity(world.client, 'tasks', uid)['done'] is True
    assert current(world.client, rule_id)['current']['entityId'] == next_item['id']
    tick(world)
    assert current(world.client, rule_id)['current']['entityId'] == next_item['id']


@pytest.mark.parametrize('kind', ['tasks', 'shopping'])
def test_pause_future_update_and_resume_preserve_current_manual_values(world, kind):
    created = create(world, kind)
    uid, plan_id = created['generated']['id'], created['plan']['id']
    changes = {'title': '本期手工标题', 'done': True}
    changes.update({'due': '2030-01-01'} if kind == 'tasks' else {'actual': 4321})
    action(world, plan_id, 'pause')
    original = edit(world.client, world.headers, kind, uid, **changes)
    tick(world, '2026-10-06')
    assert current(world.client, plan_id)['current']['entityId'] == uid
    future_template = template(kind, title='今后模板')
    action(world, plan_id, 'update', template=future_template,
           schedule=schedule(frequency='monthly', anchor='2026-09-30'))
    assert entity(world.client, kind, uid) == original
    assert current(world.client, plan_id)['current']['entityId'] == uid
    resumed = action(world, plan_id, 'resume')
    following = current(world.client, plan_id)['current']
    assert resumed['generated']['id'] == following['entityId'] != uid
    assert following['scheduledOn'] == '2026-10-30'
    assert entity(world.client, kind, following['entityId'])['title'] == '今后模板'
    assert entity(world.client, kind, uid) == original
    archived = action(world, plan_id, 'archive')
    next_original = entity(world.client, kind, following['entityId'])
    tick(world, '2027-01-01')
    assert current(world.client, plan_id)['state'] == 'archived'
    assert entity(world.client, kind, following['entityId']) == next_original


@pytest.mark.parametrize('kind', ['tasks', 'shopping'])
def test_deleted_current_never_reappears_and_explicit_skip_generates_only_next_period(world, kind):
    created = create(world, kind)
    uid, plan_id = created['generated']['id'], created['plan']['id']
    original = entity(world.client, kind, uid)
    assert world.client.delete('/api/items/' + kind + '/' + uid, json={'revision': original['revision']}, headers=world.headers).status_code == 200
    tick(world, '2026-10-06')
    assert world.client.get('/api/state').json[kind] == []
    assert current(world.client, plan_id)['current']['state'] == 'missing'
    action(world, plan_id, 'pause')
    action(world, plan_id, 'resume')
    tick(world)
    assert world.client.get('/api/state').json[kind] == []
    pending = preview(world.client, world.headers, {'operation': 'skip', 'planId': plan_id,
                       'revision': current(world.client, plan_id)['revision']})
    skipped = confirm(world.client, world.headers, pending)
    assert skipped['generated']['id'] != uid and skipped['generated']['scheduledOn'] == '2026-10-10'
    assert confirm(world.client, world.headers, pending)['replayed'] is True
    tick(world)
    assert len(world.client.get('/api/state').json[kind]) == 1
    assert not any(item['id'] == uid for item in world.client.get('/api/state').json[kind])


@pytest.mark.parametrize('kind', ['tasks', 'shopping'])
def test_skip_keeps_original_entity_and_its_history_does_not_become_completed_later(world, kind):
    created = create(world, kind)
    uid, plan_id = created['generated']['id'], created['plan']['id']
    old = entity(world.client, kind, uid)
    action(world, plan_id, 'skip')
    assert entity(world.client, kind, uid) == old
    next_id = current(world.client, plan_id)['current']['entityId']
    edit(world.client, world.headers, kind, uid, done=True)
    tick(world, '2026-10-06')
    value = current(world.client, plan_id)
    assert value['current']['entityId'] == next_id
    assert next(row for row in value['history'] if row['entityId'] == uid)['state'] == 'skipped'
    assert len(world.client.get('/api/state').json[kind]) == 2


def test_shared_member_management_tv_rejection_and_real_household_routing(world):
    created = create(world)
    plan_id = created['plan']['id']
    partner, ph = member(world.app, 2)
    original = current(partner, plan_id)
    pending = preview(partner, ph, {'operation': 'pause', 'planId': plan_id, 'revision': original['revision']})
    assert confirm(partner, ph, pending)['plan']['state'] == 'paused'
    assert current(world.client, plan_id)['state'] == 'paused'
    tv = pair_tv(world.app, world.client, world.headers)
    assert tv.get(PREFIX + '/context').status_code == 403
    assert tv.post(PREFIX + '/preview', json={'operation': 'pause', 'planId': plan_id, 'revision': 1}).status_code == 403
    assert tv.post(PREFIX + '/confirm', json={'previewToken': pending['previewToken']}).status_code == 403
    assert world.app.test_client().get(PREFIX + '/context').status_code == 401
    other, _, joined = create_space(world.app, 'routine-other-family')
    assert other.get(joined['entry']).status_code == 303
    assert other.post('/api/login', json={'username': 'member1', 'password': 'second-home-password-one'}).status_code == 200
    oh = {'X-CSRF-Token': other.get('/api/me').json['csrf']}
    assert other.get(PREFIX + '/context').json['plans'] == []
    denied = other.post(PREFIX + '/preview', json={'operation': 'pause', 'planId': plan_id, 'revision': current(world.client, plan_id)['revision']}, headers=oh)
    assert denied.status_code == 404, denied.json
    assert other.post(PREFIX + '/confirm', json={'previewToken': pending['previewToken']}, headers=oh).status_code in (400, 403)
    fresh = preview(other, oh, {'operation': 'create', 'kind': 'shopping',
                              'template': template('shopping', title='另一家庭补货'), 'schedule': schedule()})
    own = confirm(other, oh, fresh)
    assert own['plan']['id'] != plan_id
    assert '另一家庭补货' not in world.client.get(PREFIX + '/context').get_data(as_text=True)
    assert current(world.client, plan_id)['state'] == 'paused'


@pytest.mark.parametrize('member_number', [1, 2])
def test_only_explicit_shared_export_includes_routine_business_history_without_confirmation_secrets(world, member_number):
    pending = preview(world.client, world.headers, {'operation': 'create', 'kind': 'tasks',
                      'template': template(title='SHARED_ROUTINE_EXPORT_MARKER'), 'schedule': schedule()})
    created = confirm(world.client, world.headers, pending)
    edit(world.client, world.headers, 'tasks', created['generated']['id'], done=True)
    tick(world, '2026-09-19')
    observer, headers = member(world.app, member_number)
    before = {table: rows(world, table) for table in ('household_routines', 'routine_occurrences', 'routine_receipts')}
    personal, files = unpack(observer.post('/api/portability/export', json={'includeShared': False}, headers=headers))
    assert 'shared' not in personal
    assert b'SHARED_ROUTINE_EXPORT_MARKER' not in b''.join(files.values())
    shared, _ = unpack(observer.post('/api/portability/export', json={'includeShared': True}, headers=headers))
    exported = shared['shared']['routines']
    assert set(exported) == {'plans', 'occurrences', 'receipts'}
    assert len(exported['plans']) == 1 and len(exported['occurrences']) == 2 and len(exported['receipts']) >= 1
    serialized = json.dumps(exported)
    assert 'SHARED_ROUTINE_EXPORT_MARKER' in serialized
    assert pending['previewToken'] not in serialized and headers['X-CSRF-Token'] not in serialized
    for denied_key in ('nonce_digest', 'context_hash', 'credential_hash', 'browser_hash', 'previewToken'):
        assert denied_key not in serialized
    assert {table: rows(world, table) for table in before} == before


def test_assistant_missing_period_hint_is_readonly_and_explicit_skip_returns_next_local_item(world):
    created = create(world, schedule=schedule(frequency='daily', anchor='2026-09-15'))
    plan_id, uid = created['plan']['id'], created['generated']['id']
    payment = import_payment(world.client, world.headers, marker='PRIVATE_ROUTINE_BRIEF_PAYMENT')
    original = entity(world.client, 'tasks', uid)
    assert world.client.delete('/api/items/tasks/' + uid, json={'revision': original['revision']}, headers=world.headers).status_code == 200
    watched = ('entities', 'household_routines', 'routine_occurrences', 'routine_receipts', 'audit', 'settings')
    before = {name: rows(world, name) for name in watched}
    for _ in range(2):
        response = world.client.get('/api/assistant/brief')
        assert response.status_code == 200, response.json
        summary = response.json['routines']
        assert summary == {'items': [{'id': plan_id, 'title': template()['title'], 'kind': 'tasks',
                                     'owner': 'member2', 'scheduledOn': '2026-09-15', 'status': 'missing'}],
                           'dueCount': 1, 'issueCount': 1, 'limit': 8}
        assert 'PRIVATE_ROUTINE_BRIEF_PAYMENT' not in response.get_data(as_text=True)
        assert payment['id'] not in response.get_data(as_text=True)
    assert before == {name: rows(world, name) for name in watched}
    skipped = action(world, plan_id, 'skip')
    generated = skipped['generated']
    assert generated['id'] != uid and generated['scheduledOn'] == '2026-09-16'
    assert entity(world.client, 'tasks', generated['id'])['done'] is False
    assert not any(item['id'] == uid for item in world.client.get('/api/state').json['tasks'])
    summary = world.client.get('/api/assistant/brief').json['routines']
    assert summary['issueCount'] == 0 and summary['dueCount'] == 0
    assert summary['items'][0]['id'] == plan_id and summary['items'][0]['status'] == 'pending'
    assert summary['items'][0]['scheduledOn'] == '2026-09-16'
    assert not rows(world, 'task_publications') and not world.remote.calls


def test_assistant_routine_hints_prioritize_issues_count_beyond_limit_and_exclude_paused_archived(world):
    plans = [create(world, template=template(title='合成例行 ' + str(index)),
                    schedule=schedule(frequency='daily', anchor='2026-09-15')) for index in range(11)]
    action(world, plans[0]['plan']['id'], 'pause')
    action(world, plans[1]['plan']['id'], 'archive')
    missing_id = plans[-1]['generated']['id']
    original = entity(world.client, 'tasks', missing_id)
    assert world.client.delete('/api/items/tasks/' + missing_id, json={'revision': original['revision']}, headers=world.headers).status_code == 200
    watched = ('entities', 'household_routines', 'routine_occurrences', 'routine_receipts', 'audit', 'settings')
    before = {name: rows(world, name) for name in watched}
    summary = world.client.get('/api/assistant/brief').json['routines']
    assert summary['dueCount'] == 9 and summary['issueCount'] == 1 and summary['limit'] == 8
    assert len(summary['items']) == 8
    assert summary['items'][0]['id'] == plans[-1]['plan']['id']
    assert summary['items'][0]['status'] == 'missing'
    assert all(set(item) == {'id', 'title', 'kind', 'owner', 'scheduledOn', 'status'} for item in summary['items'])
    assert not {plans[0]['plan']['id'], plans[1]['plan']['id']} & {item['id'] for item in summary['items']}
    assert before == {name: rows(world, name) for name in watched}
