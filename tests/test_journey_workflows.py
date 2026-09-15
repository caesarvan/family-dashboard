"""Travel workflow tests exercise real auth, SQLite and linked entity updates."""
from copy import deepcopy
from datetime import date, timedelta
import json
import sqlite3

import pytest

from app import create_app
from test_app import app, member


def plan(**values):
    return {'title': '东京与京都', 'start': '2026-12-03', 'end': '2026-12-09',
            'international': True, 'memberIds': ['member1', 'member2'], 'budget': 2000000,
            'destinations': [
                {'key': 'tokyo', 'country': '日本', 'city': '东京', 'arrival': '2026-12-03', 'departure': '2026-12-06'},
                {'key': 'kyoto', 'country': '日本', 'city': '京都', 'arrival': '2026-12-06', 'departure': '2026-12-09'}],
            'shopping': [{'key': 'adapter', 'title': '转换插头', 'quantity': '1 件', 'owner': 'member2', 'budget': 8000}],
            **values}


def preview(client, headers, value=None, **extras):
    response = client.post('/api/journeys/preview', json={'plan': value or plan(), **extras}, headers=headers)
    assert response.status_code == 200, response.json
    return response.json


def apply(client, headers, value, key='journey-key-123'):
    return client.post('/api/journeys/apply', json={'previewToken': value['previewToken'], 'idempotencyKey': key}, headers=headers)


def create(client, headers):
    response = apply(client, headers, preview(client, headers))
    assert response.status_code == 201, response.json
    return response.json


def detail(client, uid):
    response = client.get('/api/journeys/' + uid)
    assert response.status_code == 200, response.json
    return response.json


def connection(app):
    con = sqlite3.connect(app.config['DATA_DIR'] + '/household.sqlite3')
    con.row_factory = sqlite3.Row
    return con


def test_preview_has_no_entity_or_workflow_writes_and_generates_relevant_plan(app):
    client, headers = member(app)
    value = preview(client, headers)
    assert value['summary']['create'] == {'trips': 1, 'tasks': 7, 'shopping': 1, 'events': 3}
    assert value['plan']['checklist'][0]['due'] == '2026-10-19'
    assert '不代表已核实' in value['summary']['policyNotice']
    assert '签证' in value['plan']['checklist'][0]['title']
    with connection(app) as con:
        assert con.execute('SELECT count(*) FROM entities').fetchone()[0] == 0
        assert con.execute('SELECT count(*) FROM journey_workflows').fetchone()[0] == 0
        assert con.execute('SELECT count(*) FROM journey_actions').fetchone()[0] == 0


def test_apply_links_actual_tasks_purchases_and_inclusive_trip_calendar(app):
    client, headers = member(app)
    partner, _ = member(app, 2)
    result = create(client, headers)
    value = detail(partner, result['id'])
    assert value['tripId'] == result['tripId']
    assert value['progress'] == {'done': 0, 'total': 7, 'purchased': 0, 'purchaseCount': 1}
    assert value['budget']['purchaseBudget'] == 8000
    assert value['calendar']['cloud'] == 'not_requested'
    assert all(item['tripId'] == result['tripId'] for key in ('tasks', 'shopping', 'events') for item in value[key])
    overview = next(event for event in value['events'] if event['workflowKey'] == 'event:overview')
    assert overview['start'] == '2026-12-03T00:00:00+08:00'
    assert overview['end'] == '2026-12-10T00:00:00+08:00'
    assert all(event['allDay'] for event in value['events'])
    assert client.get('/api/state').json['finance']['livingSpent'] == 0
    assert len(partner.get('/api/journeys').json['journeys']) == 1


def test_idempotency_same_key_or_new_key_same_preview_never_duplicates(app):
    client, headers = member(app)
    value = preview(client, headers)
    first = apply(client, headers, value)
    for retry in (apply(client, headers, value), apply(client, headers, value, 'another-valid-key')):
        assert retry.status_code == 200
        assert retry.json['id'] == first.json['id']
        assert retry.json['replayed'] is True
    with connection(app) as con:
        assert con.execute('SELECT count(*) FROM entities').fetchone()[0] == 12
        assert con.execute('SELECT count(*) FROM journey_actions').fetchone()[0] == 1
        assert con.execute("SELECT count(*) FROM audit WHERE action='journey_apply'").fetchone()[0] == 1
    assert apply(client, headers, preview(client, headers)).status_code == 409


def test_preview_actor_binding_and_tv_authorization(app):
    client, headers = member(app)
    partner, partner_headers = member(app, 2)
    token = preview(client, headers)
    assert apply(partner, partner_headers, token).status_code == 403
    tv = app.test_client()
    pairing = tv.post('/api/pair/start', json={}).json
    assert client.post('/api/pair/approve', json={'code': pairing['code'], 'name': '旅行测试电视', 'focus': 'member1'}, headers=headers).status_code == 200
    assert tv.post('/api/pair/poll', json={'secret': pairing['secret']}).json['approved']
    assert apply(tv, headers, token).status_code == 403
    assert tv.get('/api/journeys/templates').status_code == 403
    result = apply(client, headers, token).json
    assert tv.get('/api/journeys/' + result['id']).status_code == 200
    assert tv.get('/api/journeys/' + result['id'] + '/calendar').status_code == 403
    assert tv.get('/api/journeys/' + result['id'] + '/calendar.ics').status_code == 403
    assert client.get('/api/journeys/' + result['id'] + '/calendar.ics', headers={'X-Display-Mode': 'tv'}).status_code in (401, 403)


def test_auth_csrf_origin_and_tampering(app):
    client, headers = member(app)
    assert app.test_client().get('/api/journeys').status_code == 401
    assert client.post('/api/journeys/preview', json={'plan': plan()}).status_code == 403
    assert client.post('/api/journeys/preview', json={'plan': plan()}, headers={**headers, 'Origin': 'https://other.invalid'}).status_code == 403
    value = preview(client, headers)
    value['previewToken'] = value['previewToken'][:-4] + 'hack'
    assert apply(client, headers, value).status_code == 400
    assert client.get('/api/journeys').json['journeys'] == []


def test_preview_cannot_cross_household_database_even_with_same_signing_secret(app, tmp_path):
    client, headers = member(app)
    value = preview(client, headers)
    other_app = create_app({'TESTING': True, 'SECRET_KEY': app.config['SECRET_KEY'],
                            'DATA_DIR': str(tmp_path / 'another-household'), 'SESSION_COOKIE_SECURE': False})
    other, other_headers = member(other_app)
    assert apply(other, other_headers, value).status_code == 403
    assert other.get('/api/journeys').json['journeys'] == []


def test_conflict_if_task_changed_after_preview_then_repreview_preserves_done(app):
    client, headers = member(app)
    partner, partner_headers = member(app, 2)
    created = create(client, headers)
    value = detail(client, created['id'])
    next_plan = deepcopy(value['plan'])
    next_plan['title'] = '东京与京都 · 已调整'
    pending = preview(client, headers, next_plan, journeyId=value['id'], revision=value['revision'])
    task = value['tasks'][0]
    assert partner.patch('/api/items/tasks/' + task['id'], json={'revision': task['revision'], 'done': True}, headers=partner_headers).status_code == 200
    assert apply(client, headers, pending, 'update-plan-one').status_code == 409
    assert detail(client, value['id'])['trip']['title'] == '东京与京都'
    pending = preview(client, headers, next_plan, journeyId=value['id'], revision=value['revision'])
    response = apply(client, headers, pending, 'update-plan-two')
    assert response.status_code == 200, response.json
    updated = detail(client, value['id'])
    assert updated['progress']['done'] == 1
    assert updated['trip']['title'].endswith('已调整')
    assert updated['revision'] == 2
    assert client.post('/api/journeys/preview', json={'plan': next_plan, 'journeyId': value['id'], 'revision': 1}, headers=headers).status_code == 409


def test_reschedule_uses_same_entity_ids_and_preserves_purchase_actual(app):
    client, headers = member(app)
    result = create(client, headers)
    original = detail(client, result['id'])
    shopping = original['shopping'][0]
    assert client.patch('/api/items/shopping/' + shopping['id'], json={'revision': 1, 'done': True, 'actual': 7900}, headers=headers).status_code == 200
    value = deepcopy(original['plan'])
    def later(value):
        return (date.fromisoformat(value) + timedelta(days=5)).isoformat()
    value['start'], value['end'] = later(value['start']), later(value['end'])
    for dest in value['destinations']:
        dest['arrival'], dest['departure'] = later(dest['arrival']), later(dest['departure'])
    for segment in value['segments']:
        segment['start'], segment['end'] = later(segment['start']), later(segment['end'])
    for item in value['checklist']:
        item['due'] = later(item['due'])
    pending = preview(client, headers, value, journeyId=result['id'], revision=1)
    assert not pending['summary']['create']
    assert pending['summary']['update'] == {'trips': 1, 'tasks': 7, 'shopping': 1, 'events': 3}
    assert apply(client, headers, pending, 'reschedule-123').status_code == 200
    changed = detail(client, result['id'])
    for collection in ('tasks', 'shopping', 'events'):
        assert {item['id'] for item in changed[collection]} == {item['id'] for item in original[collection]}
    assert changed['shopping'][0]['actual'] == 7900
    assert changed['shopping'][0]['done'] is True
    assert changed['events'][0]['revision'] == 2
    assert changed['trip']['start'] == '2026-12-08'


def test_removed_items_are_detached_and_completed_history_is_retained(app):
    client, headers = member(app)
    created = create(client, headers)
    original = detail(client, created['id'])
    removed = original['tasks'][0]
    value = deepcopy(original['plan'])
    value['checklist'] = [item for item in value['checklist'] if 'task:' + item['key'] != removed['workflowKey']]
    pending = preview(client, headers, value, journeyId=created['id'], revision=1)
    assert pending['summary']['detach'] == 1
    assert apply(client, headers, pending, 'detach-item-123').status_code == 200
    assert len(detail(client, created['id'])['tasks']) == 6
    retained = next(item for item in client.get('/api/state').json['tasks'] if item['id'] == removed['id'])
    assert retained['tripId'] == ''
    assert 'journeyId' not in retained


def test_upgrade_legacy_trip_adopts_existing_tasks_without_duplicate(app):
    client, headers = member(app)
    trip = client.post('/api/items/trips', json={'title': '旧旅行', 'destination': '京都', 'start': '2026-12-03', 'end': '2026-12-09'}, headers=headers).json
    task = client.post('/api/items/tasks', json={'title': '已有机票', 'tripId': trip['id'], 'done': True, 'owner': 'member1'}, headers=headers).json
    value = plan(checklist=[{'key': 'existing-' + task['id'], 'title': '已有机票', 'owner': 'member1', 'dueOffsetDays': -14}])
    pending = preview(client, headers, value, tripId=trip['id'], tripRevision=1)
    assert pending['summary']['update'] == {'trips': 1, 'tasks': 1}
    assert pending['summary']['create'] == {'shopping': 1, 'events': 3}
    result = apply(client, headers, pending)
    assert result.status_code == 201, result.json
    actual = detail(client, result.json['id'])
    assert actual['tripId'] == trip['id']
    assert actual['tasks'][0]['id'] == task['id']
    assert actual['tasks'][0]['done'] is True
    assert len(client.get('/api/state').json['tasks']) == 1


def test_transaction_failure_rolls_back_all_generated_records(app):
    client, headers = member(app)
    value = preview(client, headers)
    with connection(app) as con:
        con.execute("CREATE TRIGGER fail_journey_audit BEFORE INSERT ON audit WHEN NEW.action='journey_apply' BEGIN SELECT RAISE(ABORT,'test abort'); END")
    with pytest.raises(sqlite3.IntegrityError, match='test abort'):
        apply(client, headers, value)
    with connection(app) as con:
        for table in ('entities', 'journey_workflows', 'journey_links', 'journey_actions'):
            assert con.execute('SELECT count(*) FROM ' + table).fetchone()[0] == 0
        con.execute('DROP TRIGGER fail_journey_audit')
    assert apply(client, headers, value).status_code == 201


@pytest.mark.parametrize('changes', [
    {'budget': True}, {'budget': 1.5}, {'budget': -1}, {'budget': 100000000001},
    {'memberIds': ['someone-else']}, {'memberIds': []}, {'memberIds': ['member1', 'member1']},
    {'start': '2026-02-30'}, {'end': '2026-12-01'}, {'international': 'true'},
    {'destinations': []}, {'destinations': [{'city': '京都', 'arrival': '2027-01-01'}]},
    {'checklist': [{'title': '事项', 'owner': 'someone-else'}]},
    {'checklist': [{'key': 'same', 'title': '事项 1'}, {'key': 'same', 'title': '事项 2'}]},
    {'shopping': [{'title': '物品', 'budget': '100'}]},
    {'segments': [{'title': '行程', 'start': '2026-12-10'}]},
    {'segments': [{'title': '行程', 'start': '2026-12-08', 'end': '2026-12-07'}]},
])
def test_invalid_inputs_never_create_partial_records(app, changes):
    client, headers = member(app)
    response = client.post('/api/journeys/preview', json={'plan': plan(**changes)}, headers=headers)
    assert response.status_code == 400, response.json
    assert client.get('/api/journeys').json['journeys'] == []
    assert client.get('/api/state').json['trips'] == []


def test_ics_folding_escape_date_and_member_only_cloud_contract(app):
    client, headers = member(app)
    pending = preview(client, headers, plan(title='旅行' * 40 + '\nBEGIN:VEVENT', note='酒店,交通;核对\\完成\n不插入新属性'))
    result = apply(client, headers, pending).json
    response = client.get('/api/journeys/' + result['id'] + '/calendar.ics')
    assert response.status_code == 200
    assert response.mimetype == 'text/calendar'
    text = response.data.decode()
    assert 'DTEND;VALUE=DATE:20261210' in text
    assert text.count('\r\nBEGIN:VEVENT\r\n') == 3
    assert all(len(line.encode()) <= 75 for line in text.split('\r\n'))
    unfolded = text.replace('\r\n ', '')
    assert '\\nBEGIN:VEVENT' in unfolded
    assert '酒店\\,交通\\;核对\\\\完成\\n' in unfolded
    assert response.headers['Cache-Control'] == 'no-store'
    contract = client.get('/api/journeys/' + result['id'] + '/calendar').json
    assert len(contract['events']) == 3
    assert contract['cloudStatus'] == 'not_requested'
    assert all(event['id'] for event in contract['events'])


def test_schema_cleanup_when_trip_is_deleted_does_not_drop_preparation_history(app):
    client, headers = member(app)
    result = create(client, headers)
    assert client.delete('/api/items/trips/' + result['tripId'], json={'revision': 1}, headers=headers).status_code == 200
    assert client.get('/api/journeys/' + result['id']).status_code == 404
    state = client.get('/api/state').json
    for kind in ('tasks', 'shopping', 'events'):
        for record in state[kind]:
            assert not record.get('tripId')
            assert not record.get('journeyId')
        sample = state[kind][0]
        response = client.patch('/api/items/' + kind + '/' + sample['id'],
                                json={'revision': sample['revision'], 'title': sample['title'] + ' · 保留记录'}, headers=headers)
        assert response.status_code == 200, response.json
    with connection(app) as con:
        assert con.execute('SELECT count(*) FROM journey_workflows').fetchone()[0] == 0
        assert con.execute('SELECT count(*) FROM journey_links').fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM entities WHERE kind='tasks'").fetchone()[0] == 7
