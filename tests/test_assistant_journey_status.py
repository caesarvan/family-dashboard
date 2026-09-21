"""Real session/Flask/SQLite reads; synthetic household records, no provider."""
from contextlib import closing
import json
import socket
import sqlite3
from types import SimpleNamespace
from uuid import uuid4

from flask import request
import pytest

import app as app_module
import journey_workflows
from test_app import app, member
from test_household_spaces import create_space
from test_journey_workflows import plan, preview, apply, detail


PATH = '/api/assistant/journey-status'


@pytest.fixture(autouse=True)
def no_provider(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('This read-only slice must not call a provider')
    monkeypatch.setattr(socket.socket, 'connect', denied)


def connection(app):
    con = sqlite3.connect(app.config['DATA_DIR'] + '/household.sqlite3', timeout=2)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    return con


def create(client, headers, count=3, title='冰岛旅行'):
    value = plan(title=title, checklist=[{'key': f't{i}', 'title': f'准备{i}', 'owner': 'member1',
                                         'due': '2026-12-01'} for i in range(count)],
                 shopping=[{'key': 's0', 'title': '采购0', 'owner': 'shared', 'quantity': '2 件',
                            'budget': 12345, 'priority': 'high', 'due': ''}], segments=[])
    response = apply(client, headers, preview(client, headers, value), uuid4().hex)
    assert response.status_code == 201, response.json
    return detail(client, response.json['id'])


def get(client, trip=None, **query):
    if trip:
        query['tripId'] = trip['tripId']
    return client.get(PATH, query_string=query)


def business(app):
    with closing(connection(app)) as con:
        tables = ('entities', 'journey_workflows', 'journey_links', 'journey_actions',
                  'assistant_plans', 'audit', 'settings', 'sqlite_master')
        return {table: sorted((tuple(row) for row in con.execute('SELECT * FROM ' + table)), key=repr)
                for table in tables}


def patch_raw(app, uid, **values):
    with closing(connection(app)) as con:
        data = json.loads(con.execute('SELECT data FROM entities WHERE id=?', (uid,)).fetchone()[0])
        data.update(values)
        con.execute('UPDATE entities SET data=?,revision=revision+1 WHERE id=?', (json.dumps(data), uid))
        con.commit()


def test_real_trip_progress_original_mutations_and_no_business_writes(app):
    client, headers = member(app)
    trip = create(client, headers)
    first, second, third = trip['tasks']
    assert client.patch('/api/items/tasks/' + second['id'], headers=headers,
                        json={'revision': second['revision'], 'dependsOn': [first['id']]}).status_code == 200
    assert client.patch('/api/items/tasks/' + third['id'], headers=headers,
                        json={'revision': third['revision'], 'done': True, 'due': ''}).status_code == 200
    before = business(app)
    response = get(client, trip)
    assert response.status_code == 200 and response.headers['Cache-Control'] == 'no-store'
    result = response.json
    assert result['state'] == 'ready' and result['coverage']['complete']
    assert result['summary'] == {'tasks': {'done': 1, 'total': 3, 'remaining': 2, 'blocked': 1},
                                 'shopping': {'done': 0, 'total': 1, 'remaining': 1}}
    blocked = next(item for item in result['items'] if item['id'] == second['id'])
    assert blocked['blockers'] == [{'id': first['id'], 'title': first['title'], 'reason': 'unfinished'}]
    assert blocked['owner'] == {'id': 'member1', 'name': '我'}
    shopping = get(client, trip, section='shopping').json['items'][0]
    assert shopping['quantity'] == '2 件' and shopping['priority'] == 'high' and shopping['due'] == ''
    assert shopping['owner'] == {'id': 'shared', 'name': '一起'}
    assert not {'note', 'budget', 'actual', 'sync', 'blockers'} & shopping.keys()
    assert business(app) == before
    assert client.patch('/api/items/tasks/' + first['id'], headers=headers,
                        json={'revision': first['revision'], 'done': True}).status_code == 200
    refreshed = get(client, trip).json
    assert refreshed['summary']['tasks'] == {'done': 2, 'total': 3, 'remaining': 1, 'blocked': 0}
    assert refreshed['sourceVersion'] != result['sourceVersion']


def test_same_name_disambiguation_unicode_destination_and_plain_legacy(app):
    client, headers = member(app)
    first = create(client, headers)
    second = create(client, headers)
    patch_raw(app, first['tripId'], destination='ÍSLAND')
    response = get(client, q=' 冰岛 ').json
    assert len(response['items']) == 2 and {item['tripId'] for item in response['items']} == {first['tripId'], second['tripId']}
    assert [item['tripId'] for item in response['items']] == sorted([first['tripId'], second['tripId']])
    assert get(client, q='ísland').json['items'][0]['tripId'] == first['tripId']
    legacy = client.post('/api/items/trips', headers=headers, json={
        'title': '旧旅行', 'start': '1999-01-01', 'end': '1999-01-02'}).json
    result = get(client, {'tripId': legacy['id']}).json
    assert result['state'] == 'legacy' and result['summary'] is None and result['items'] == []
    assert result['coverage'] == {'complete': False, 'unverifiable': 0, 'reasonCodes': ['legacy_without_workflow']}
    patch_raw(app, legacy['id'], journeyId='f' * 24)
    assert get(client, {'tripId': legacy['id']}).json['state'] == 'needs_review'


def test_scan_cap_is_raw_trip_coverage_and_original_id_bypasses_it(app):
    client, headers = member(app)
    trip = create(client, headers)
    data = {'title': '合成旧旅行', 'destination': '', 'start': '2028-01-01', 'end': '2028-01-01'}
    with closing(connection(app)) as con:
        con.executemany('INSERT INTO entities(id,kind,data,updated_at) VALUES(?,\'trips\',?,\'synthetic\')',
                        [(f'{i:024x}', json.dumps(data)) for i in range(1001)])
        con.execute('UPDATE entities SET data=? WHERE id=?', ('[]', f'{0:024x}'))
        con.commit()
    response = get(client, q='冰岛').json
    assert response['items'] == [] and response['coverage'] == {
        'scannedTrips': 1000, 'scanLimit': 1000, 'capped': True, 'unverifiable': 1}
    page = get(client, offset=980).json
    assert len(page['items']) == 19 and page['nextOffset'] is None
    assert get(client, trip).json['state'] == 'ready'


@pytest.mark.parametrize('query', [
    {'owner': 'member2'}, {'limit': '21'}, {'offset': '01'}, {'offset': '1'}, {'offset': '1000'},
    {'q': 'x' * 101}, {'q': '\x00'}, [('q', '一'), ('q', '二')],
    {'tripId': 'bad'}, {'tripId': 'a' * 24, 'q': '一'}, {'tripId': 'a' * 24, 'section': 'events'},
    {'tripId': 'a' * 24, 'offset': '20'}, {'tripId': 'a' * 24, 'sourceVersion': 'B' * 64},
    {'tripId': 'a' * 24, 'offset': '100', 'sourceVersion': 'a' * 64},
])
def test_strict_query_parameters(app, query):
    client, _ = member(app)
    response = client.get(PATH, query_string=query)
    assert response.status_code == 400 and response.json['code'] == 'invalid_journey_status_query'


def test_item_pagination_source_version_covers_nonpage_and_dependency_changes(app):
    client, headers = member(app)
    trip = create(client, headers, 25)
    first = get(client, trip).json
    assert len(first['items']) == 20 and first['nextOffset'] == 20
    second = get(client, trip, offset=20, sourceVersion=first['sourceVersion']).json
    assert len(second['items']) == 5 and second['nextOffset'] is None
    assert not {x['id'] for x in first['items']} & {x['id'] for x in second['items']}
    assert first['summary']['tasks']['total'] == second['summary']['tasks']['total'] == 25
    patch_raw(app, second['items'][0]['id'], title='后页真实修改')
    stale = get(client, trip, offset=20, sourceVersion=first['sourceVersion'])
    assert stale.status_code == 409 and stale.json['code'] == 'stale_journey_status'
    external = client.post('/api/items/tasks', headers=headers, json={'title': '前置原任务'}).json
    patch_raw(app, trip['tasks'][0]['id'], dependsOn=[external['id']])
    before = get(client, trip).json
    assert client.patch('/api/items/tasks/' + external['id'], headers=headers,
                        json={'revision': external['revision'], 'done': True}).status_code == 200
    after = get(client, trip).json
    assert after['sourceVersion'] != before['sourceVersion'] and after['summary']['tasks']['blocked'] == 0


@pytest.mark.parametrize('damage', ['missing_entity', 'wrong_kind', 'wrong_journey', 'missing_link', 'bad_json', 'bad_done', 'bad_dependencies'])
def test_corrupt_or_missing_item_never_becomes_all_prepared(app, damage):
    client, headers = member(app)
    trip = create(client, headers, 1)
    item = trip['tasks'][0]
    with closing(connection(app)) as con:
        if damage == 'missing_entity':
            con.execute('DELETE FROM entities WHERE id=?', (item['id'],))
        elif damage == 'missing_link':
            con.execute('DELETE FROM journey_links WHERE entity_id=?', (item['id'],))
        elif damage == 'wrong_kind':
            con.execute("UPDATE entities SET kind='shopping' WHERE id=?", (item['id'],))
        elif damage == 'bad_json':
            con.execute("UPDATE entities SET data='{' WHERE id=?", (item['id'],))
        else:
            value = json.loads(con.execute('SELECT data FROM entities WHERE id=?', (item['id'],)).fetchone()[0])
            value.update({'wrong_journey': {'journeyId': 'f' * 24}, 'bad_done': {'done': 1},
                          'bad_dependencies': {'dependsOn': ['a' * 24] * 21}}[damage])
            con.execute('UPDATE entities SET data=? WHERE id=?', (json.dumps(value), item['id']))
        con.commit()
    response = get(client, trip)
    assert response.status_code == 200 and response.json['state'] == 'needs_review'
    assert not response.json['coverage']['complete'] and response.json['coverage']['unverifiable'] >= 1
    assert response.json['items'] == []


@pytest.mark.parametrize('damage', ['trip_pointer', 'link_pointer', 'bad_plan', 'bad_revision'])
def test_broken_workflow_never_loads_another_trip_or_repairs_storage(app, damage):
    client, headers = member(app)
    trip = create(client, headers)
    if damage == 'trip_pointer':
        patch_raw(app, trip['tripId'], journeyId='f' * 24)
    else:
        with closing(connection(app)) as con:
            if damage == 'link_pointer':
                con.execute("UPDATE journey_links SET kind='tasks' WHERE journey_id=? AND item_key='trip'", (trip['id'],))
            elif damage == 'bad_plan':
                con.execute("UPDATE journey_workflows SET plan='[]' WHERE id=?", (trip['id'],))
            else:
                con.execute('UPDATE journey_workflows SET revision=0 WHERE id=?', (trip['id'],))
            con.commit()
    before = business(app)
    response = get(client, trip).json
    assert response['state'] == 'needs_review' and response['summary'] is None and response['items'] == []
    assert business(app) == before


def test_observed_item_overflow_is_partial_and_never_reads_unbounded_graph(app):
    client, headers = member(app)
    trip = create(client, headers, 100)
    with closing(connection(app)) as con:
        value = {'title': '超限合成任务', 'owner': 'shared', 'done': False, 'due': '',
                 'journeyId': trip['id'], 'tripId': trip['tripId']}
        con.execute('INSERT INTO entities(id,kind,data,updated_at) VALUES(?,\'tasks\',?,\'synthetic\')', ('f' * 24, json.dumps(value)))
        con.execute('INSERT INTO journey_links VALUES(?,?,?,?)', (trip['id'], 'task:extra', 'f' * 24, 'tasks'))
        con.commit()
    result = get(client, trip).json
    assert result['state'] == 'needs_review' and not result['coverage']['complete']
    assert 'item_limit' in result['coverage']['reasonCodes'] and result['summary']['tasks']['total'] <= 100


def test_unavailable_blockers_and_removed_owner_do_not_leak_or_guess(app):
    client, headers = member(app)
    trip = create(client, headers, 1)
    cloud = client.post('/api/items/tasks', headers=headers, json={'title': '不可核对云前置'}).json
    patch_raw(app, cloud['id'], sync={'readOnly': True})
    patch_raw(app, trip['tasks'][0]['id'], owner='former-member', dependsOn=['f' * 24, cloud['id']])
    result = get(client, trip).json['items'][0]
    assert result['owner'] == {'id': None, 'name': None}
    assert result['dependencyStatus'] == 'blocked'
    assert result['blockers'] == [{'id': None, 'title': None, 'reason': 'unavailable'}] * 2
    assert '不可核对云前置' not in json.dumps(result, ensure_ascii=False)


def test_corrupt_predecessor_id_and_title_are_unavailable_without_projection(app):
    client, headers = member(app)
    trip = create(client, headers, 1)
    bad_id, bad_title_id = 'broken-id', 'd' * 24
    with closing(connection(app)) as con:
        con.executemany('INSERT INTO entities(id,kind,data,updated_at) VALUES(?,\'tasks\',?,\'synthetic\')', [
            (bad_id, json.dumps({'title': '隐藏的坏编号来源', 'done': False})),
            (bad_title_id, json.dumps({'title': ['隐藏的坏标题来源'], 'done': False})),
        ])
        con.commit()
    patch_raw(app, trip['tasks'][0]['id'], dependsOn=[bad_id, bad_title_id])
    response = get(client, trip)
    assert response.status_code == 200
    item = response.json['items'][0]
    assert item['dependencyStatus'] == 'blocked'
    assert item['blockers'] == [{'id': None, 'title': None, 'reason': 'unavailable'}] * 2
    assert bad_id not in response.get_data(as_text=True) and '隐藏的' not in response.get_data(as_text=True)


def test_real_member_household_and_tv_isolation(app):
    client, headers = member(app)
    trip = create(client, headers)
    partner, _ = member(app, 2)
    assert get(partner, trip).status_code == 200  # Household trips are shared; owner is assignment.
    assert get(app.test_client(), trip).status_code == 401
    tv = app.test_client()
    pair = tv.post('/api/pair/start', json={}).json
    assert client.post('/api/pair/approve', headers=headers, json={'code': pair['code'], 'name': '测试电视'}).status_code == 200
    assert tv.post('/api/pair/poll', json={'secret': pair['secret']}).json['approved']
    assert get(tv, trip).status_code == 403
    assert client.get(PATH, headers={'X-Display-Mode': 'tv'}).status_code in (401, 403)
    child, _, household = create_space(app)
    assert child.get(household['entry']).status_code == 303
    assert child.post('/api/login', json={'username': 'member1', 'password': 'second-home-password-one'}).status_code == 200
    assert get(child).json['items'] == []
    response = get(child, trip)
    assert response.status_code == 404 and response.json['code'] == 'journey_status_unavailable'
    assert '冰岛' not in response.get_data(as_text=True)
    assert client.post('/api/logout', json={}, headers=headers).status_code == 200
    assert get(client, trip).status_code == 401


@pytest.mark.parametrize('mode', ['candidates', 'detail'])
@pytest.mark.parametrize('pass_number', [1, 2])
def test_real_session_revoked_during_either_snapshot_returns_no_data(app, monkeypatch, mode, pass_number):
    client, headers = member(app)
    trip = create(client, headers)
    original = json.loads
    count = []
    def loads(raw, *args, **kwargs):
        value = original(raw, *args, **kwargs)
        if type(value) is dict and value.get('title') == '冰岛旅行':
            count.append(1)
            if len(count) == pass_number:
                with closing(connection(app)) as con:
                    con.execute("UPDATE member_sessions SET revoked_at=1 WHERE owner='member1'")
                    con.commit()
        return value
    monkeypatch.setattr(journey_workflows, 'json', SimpleNamespace(loads=loads, dumps=json.dumps))
    response = get(client, trip if mode == 'detail' else None)
    assert len(count) >= pass_number and response.status_code == 401
    assert '冰岛' not in response.get_data(as_text=True) and 'items' not in response.json


@pytest.mark.parametrize('change', ['rename', 'delete', 'dependency'])
def test_second_snapshot_rechecks_actual_source_after_first_read(app, monkeypatch, change):
    client, headers = member(app)
    trip = create(client, headers)
    original = json.loads
    changed = []
    def loads(raw, *args, **kwargs):
        value = original(raw, *args, **kwargs)
        if type(value) is dict and value.get('title') == '冰岛旅行' and not changed:
            changed.append(True)
            if change == 'rename':
                patch_raw(app, trip['tripId'], title='最新旅行')
            elif change == 'dependency':
                patch_raw(app, trip['tasks'][0]['id'], dependsOn=['f' * 24])
            else:
                with closing(connection(app)) as con:
                    con.execute('DELETE FROM entities WHERE id=?', (trip['tripId'],)); con.commit()
        return value
    monkeypatch.setattr(journey_workflows, 'json', SimpleNamespace(loads=loads, dumps=json.dumps))
    response = get(client, trip)
    assert changed
    if change == 'delete':
        assert response.status_code == 404 and response.json['code'] == 'journey_status_unavailable'
    else:
        assert response.status_code == 200
        if change == 'rename':
            assert response.json['trip']['title'] == '最新旅行'
        else:
            assert response.json['summary']['tasks']['blocked'] == 1


def test_query_authorizer_denies_all_business_writes_and_unrelated_tables(app, monkeypatch):
    client, headers = member(app)
    trip = create(client, headers)
    sql = []
    def authorize(action, table, column, *_):
        if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE):
            return sqlite3.SQLITE_OK if table == 'member_sessions' else sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_READ:
            assert table in {'entities', 'journey_workflows', 'journey_links', 'users', 'household_memberships',
                             'member_sessions', 'member_session_browsers'}, (table, column)
        return sqlite3.SQLITE_OK
    original = app_module.connect_household
    def inspect_connection(*args, **kwargs):
        con = original(*args, **kwargs)
        con.set_authorizer(authorize)
        con.set_trace_callback(sql.append)
        return con
    monkeypatch.setattr(app_module, 'connect_household', inspect_connection)
    assert get(client).status_code == 200
    assert get(client, trip).status_code == 200
    assert not any('sqlite_master' in query for query in sql)
    assert not any("WHERE kind='tasks'" in query and ' IN (' not in query for query in sql)


@pytest.mark.parametrize('table', ['entities', 'journey_workflows'])
def test_binary_corrupt_metadata_is_partial_not_server_error(app, table):
    client, headers = member(app)
    trip = create(client, headers, 1)
    with closing(connection(app)) as con:
        if table == 'entities':
            con.execute('UPDATE entities SET data=? WHERE id=?', (b'{}', trip['tasks'][0]['id']))
        else:
            con.execute('UPDATE journey_workflows SET plan=? WHERE id=?', (b'{}', trip['id']))
        con.commit()
    response = get(client, trip)
    assert response.status_code == 200 and response.json['state'] == 'needs_review'
    assert not response.json['coverage']['complete'] and response.json['items'] == []


def test_full_page_unicode_blockers_fit_wire_budget_without_truncation(app):
    client, headers = member(app)
    trip = create(client, headers, 20)
    title = '🧳' * 100
    with closing(connection(app)) as con:
        for i, item in enumerate(trip['tasks']):
            ids = [f'{10000 + i * 20 + j:024x}' for j in range(20)]
            con.executemany('INSERT INTO entities(id,kind,data,updated_at) VALUES(?,\'tasks\',?,\'synthetic\')',
                            [(uid, json.dumps({'title': title, 'owner': 'shared', 'done': False})) for uid in ids])
            value = json.loads(con.execute('SELECT data FROM entities WHERE id=?', (item['id'],)).fetchone()[0])
            value['dependsOn'] = ids
            con.execute('UPDATE entities SET data=? WHERE id=?', (json.dumps(value), item['id']))
        con.commit()
    response = get(client, trip)
    assert response.status_code == 200 and len(response.data) <= 256 * 1024
    assert len(response.json['items']) == 20
    assert sum(len(item['blockers']) for item in response.json['items']) == 400
    assert all(blocker['title'] == title for item in response.json['items'] for blocker in item['blockers'])


def test_sqlite_lock_contention_returns_recoverable_failure(app):
    client, headers = member(app)
    trip = create(client, headers)
    # A real exclusive lock after the global auth guard, before this handler's
    # read, proves its busy mapping. DELETE journal is only this synthetic DB.
    with closing(connection(app)) as con:
        assert con.execute('PRAGMA journal_mode=DELETE').fetchone()[0] == 'delete'
    blocker = connection(app)
    def lock():
        if request.path == PATH:
            blocker.execute('BEGIN EXCLUSIVE')
    app.before_request_funcs[None].append(lock)
    try:
        response = get(client, trip)
        assert response.status_code == 503 and response.json['code'] == 'unavailable'
    finally:
        blocker.rollback(); blocker.close()
        app.before_request_funcs[None].remove(lock)
    assert get(client, trip).status_code == 200
