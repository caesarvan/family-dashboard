"""Real Flask/SQLite task graph contracts; synthetic records, no network."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import socket
import sqlite3
from threading import Barrier, Event

from flask import has_request_context, request
import pytest

from app import create_app
import home_assistant
import household_routines
from membership_storage import HouseholdConnection
import task_dependencies as dependencies
from test_app import member
from test_household_spaces import create_space
from test_data_portability import unpack
import test_household_routines as routines
import test_journey_workflows as journeys
import test_journey_reschedule as rescheduling
import test_inventory_followup as followups
from test_task_publish import env, queue, process, row, local, change_remote, action


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*_args, **_kwargs):
        raise AssertionError('Task dependency tests permit no network')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)


@pytest.fixture
def app(tmp_path):
    return create_app({'TESTING': True, 'DATA_DIR': str(tmp_path / 'data'),
        'SECRET_KEY': 'synthetic-dependency-secret', 'SESSION_COOKIE_SECURE': False,
        'PUBLIC_ORIGIN': 'http://localhost', 'MEMBER1_PASSWORD': 'testing-password-one',
        'MEMBER2_PASSWORD': 'testing-password-two', 'OPENAI_API_KEY': '', 'NVIDIA_API_KEY': '',
        'MICROSOFT_CLIENT_ID': '', 'MICROSOFT_CLIENT_SECRET': '',
        'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': ''})


def database(app):
    con = sqlite3.connect(Path(app.config['DATA_DIR']) / 'household.sqlite3', timeout=10)
    con.row_factory = sqlite3.Row
    return con


def task(client, uid):
    return next(t for t in client.get('/api/state').json['tasks'] if t['id'] == uid)


def create(client, headers, **fields):
    r = client.post('/api/items/tasks', json={'title': '合成事项', 'sourceId': '', **fields}, headers=headers)
    assert r.status_code == 201, r.json
    return task(client, r.json['id'])


def patch(client, headers, value, **fields):
    return client.patch('/api/items/tasks/' + value['id'],
                        json={'revision': value['revision'], **fields}, headers=headers)


def snapshot(app):
    with closing(database(app)) as con:
        return {table: [tuple(r) for r in con.execute('SELECT * FROM ' + table + ' ORDER BY rowid')]
                for table in ('entities', 'audit', 'settings')}


def test_legacy_reads_are_pure_and_restart_preserves_graph(app):
    c, h = member(app)
    first = create(c, h, title='前置')
    second = create(c, h, title='后续', dependsOn=[first['id']])
    before = snapshot(app)
    assert first['dependsOn'] == first['blockedBy'] == [] and first['dependencyStatus'] == 'ready'
    assert second['blockedBy'] == [first['id']] and second['dependencyStatus'] == 'blocked'
    partner, _ = member(app, 2)
    assert task(partner, second['id'])['blockedBy'] == [first['id']]
    with closing(database(app)) as con:
        raw = json.loads(con.execute('SELECT data FROM entities WHERE id=?', (first['id'],)).fetchone()[0])
        assert 'dependsOn' not in raw and 'blockedBy' not in raw
    # Login itself changes session tables, but graph GETs change none of these tables.
    assert snapshot(app) == before
    restarted = create_app(dict(app.config))
    fresh, _ = member(restarted)
    assert task(fresh, second['id'])['blockedBy'] == [first['id']]


@pytest.mark.parametrize('value', [None, 'id', True, {}, [None], [1], [''], [' a'], ['a '], ['x' * 129], ['a', 'a'], ['x' + str(i) for i in range(21)]])
def test_invalid_dependency_input_is_atomic(app, value):
    c, h = member(app)
    item = create(c, h)
    before = snapshot(app)
    r = patch(c, h, item, dependsOn=value)
    assert r.status_code == 400 and r.json['code'] == 'invalid_task_dependencies', r.json
    assert snapshot(app) == before


def test_completion_old_client_clear_delete_and_historical_reopen(app):
    c, h = member(app)
    a = create(c, h); b = create(c, h, dependsOn=[a['id']])
    before = snapshot(app)
    r = patch(c, h, b, done=True, blockedBy=[], dependencyStatus='ready')
    assert r.status_code == 409 and r.json['code'] == 'task_dependencies_incomplete'
    assert snapshot(app) == before
    assert patch(c, h, b, title='旧客户端只改标题').status_code == 200
    b = task(c, b['id']); assert b['dependsOn'] == [a['id']]
    assert patch(c, h, a, done=True).status_code == 200
    assert task(c, b['id'])['dependencyStatus'] == 'ready'
    assert patch(c, h, b, done=True).status_code == 200
    a = task(c, a['id']); b = task(c, b['id'])
    assert patch(c, h, a, done=False).status_code == 200
    completed = task(c, b['id'])
    assert completed['done'] is True and completed['dependencyStatus'] == 'done'
    assert completed['blockedBy'] == [a['id']]
    assert patch(c, h, completed, note='已完成的历史仍可编辑').status_code == 200
    a = task(c, a['id'])
    r = c.delete('/api/items/tasks/' + a['id'], json={'revision': a['revision']}, headers=h)
    assert r.status_code == 409 and r.json['code'] == 'task_has_dependents'
    b = task(c, b['id'])
    assert patch(c, h, b, dependsOn=[]).status_code == 200
    assert c.delete('/api/items/tasks/' + a['id'], json={'revision': a['revision']}, headers=h).status_code == 200


def test_self_indirect_cycle_stale_revision_and_diamond(app):
    c, h = member(app)
    a = create(c, h); b = create(c, h, dependsOn=[a['id']]); d = create(c, h, dependsOn=[a['id']])
    e = create(c, h, dependsOn=[b['id'], d['id']])
    assert patch(c, h, a, dependsOn=[a['id']]).status_code == 400
    before = snapshot(app)
    r = patch(c, h, a, dependsOn=[e['id']])
    assert r.status_code == 409 and r.json['code'] == 'task_dependency_cycle'
    assert snapshot(app) == before
    assert patch(c, h, b, dependsOn=[]).status_code == 200
    assert patch(c, h, b, done=True).status_code == 409
    assert task(c, b['id'])['done'] is False


def test_twenty_dependencies_and_long_graph_are_bounded_without_recursion(app):
    c, h = member(app)
    with closing(database(app)) as con, con:
        con.executemany("INSERT INTO entities(id,kind,data,updated_at) VALUES(?,'tasks',?,'now')", [
            ('chain-' + str(i), json.dumps({'title': '合成长链', 'owner': 'shared', 'due': '', 'tripId': '',
                'note': '', 'done': False, 'dependsOn': [] if i == 0 else ['chain-' + str(i - 1)]}))
            for i in range(1100)])
    value = create(c, h, dependsOn=['chain-' + str(i) for i in range(1080, 1100)])
    assert len(value['blockedBy']) == 20
    first = task(c, 'chain-0'); before = snapshot(app)
    r = patch(c, h, first, dependsOn=[value['id']])
    assert r.status_code == 409 and r.json['code'] == 'task_dependency_cycle'
    assert snapshot(app) == before


def test_create_already_complete_cannot_bypass_prerequisites(app):
    c, h = member(app); a = create(c, h); before = snapshot(app)
    r = c.post('/api/items/tasks', json={'title': '不能越过前置', 'sourceId': '', 'done': True,
                                      'dependsOn': [a['id']]}, headers=h)
    assert r.status_code == 409 and r.json['code'] == 'task_dependencies_incomplete'
    assert snapshot(app) == before


def test_missing_cloud_foreign_references_do_not_disclose_other_households(app):
    c, h = member(app)
    local_task = create(c, h)
    with closing(database(app)) as con, con:
        con.execute("INSERT INTO entities(id,kind,data,updated_at) VALUES('cloud-synthetic','tasks',?,'now')",
                    (json.dumps({'title': '合成云镜像', 'done': False, 'sync': {'sourceId': 'unavailable'}}),))
    other, _, entry = create_space(app)
    assert other.get(entry['entry']).status_code == 303
    assert other.post('/api/login', json={'username': 'member1', 'password': 'second-home-password-one'}).status_code == 200
    oh = {'X-CSRF-Token': other.get('/api/me').json['csrf']}
    foreign = create(other, oh, title='OTHER_HOUSEHOLD_NOT_VISIBLE')
    errors = []
    for uid in ('does-not-exist', 'cloud-synthetic', foreign['id']):
        r = patch(c, h, local_task, dependsOn=[uid])
        assert r.status_code == 409
        errors.append(r.json)
    assert errors[0] == errors[1] == errors[2]
    assert 'OTHER_HOUSEHOLD_NOT_VISIBLE' not in c.get('/api/state').get_data(as_text=True)


def test_missing_historical_reference_can_be_removed(app):
    c, h = member(app); item = create(c, h)
    with closing(database(app)) as con, con:
        raw = json.loads(con.execute('SELECT data FROM entities WHERE id=?', (item['id'],)).fetchone()[0])
        con.execute('UPDATE entities SET data=? WHERE id=?', (json.dumps({**raw, 'dependsOn': ['lost-record']}), item['id']))
    value = task(c, item['id'])
    assert value['blockedBy'] == ['lost-record']
    assert patch(c, h, value, done=True).status_code == 409
    assert patch(c, h, value, dependsOn=[]).status_code == 200


def test_explicit_shared_export_preserves_edges_without_derived_state(app):
    c, h = member(app); a = create(c, h); b = create(c, h, dependsOn=[a['id']])
    before = snapshot(app)
    private, _ = unpack(c.post('/api/portability/export', json={}, headers=h))
    assert 'shared' not in private
    shared, _ = unpack(c.post('/api/portability/export', json={'includeShared': True}, headers=h))
    saved = next(t for t in shared['shared']['entities']['tasks'] if t['id'] == b['id'])
    assert saved['dependsOn'] == [a['id']]
    assert 'blockedBy' not in saved and 'dependencyStatus' not in saved
    # Export intentionally records its existing audit; it must not rewrite tasks.
    after = snapshot(app)
    assert after['entities'] == before['entities']
    assert len(after['audit']) == len(before['audit']) + 2


def begin_barrier(monkeypatch):
    original = HouseholdConnection.execute; barrier = Barrier(2)
    def execute(con, sql, *args, **kwargs):
        if sql == 'BEGIN IMMEDIATE' and has_request_context() and request.path.startswith('/api/items/tasks/'):
            barrier.wait(timeout=10)
        return original(con, sql, *args, **kwargs)
    monkeypatch.setattr(HouseholdConnection, 'execute', execute)


def test_two_members_cannot_concurrently_create_cycle(app, monkeypatch):
    c, h = member(app); other, oh = member(app, 2)
    a = create(c, h); b = create(c, h)
    begin_barrier(monkeypatch)
    with ThreadPoolExecutor(2) as executor:
        f1 = executor.submit(patch, c, h, a, dependsOn=[b['id']])
        f2 = executor.submit(patch, other, oh, b, dependsOn=[a['id']])
        results = [f1.result(timeout=20), f2.result(timeout=20)]
    assert sorted(r.status_code for r in results) == [200, 409]
    assert next(r for r in results if r.status_code == 409).json['code'] == 'task_dependency_cycle'
    assert sum(bool(task(c, t['id'])['dependsOn']) for t in (a, b)) == 1


def test_dependency_add_and_delete_serialize_without_dangling_edge(app, monkeypatch):
    c, h = member(app); other, oh = member(app, 2)
    a = create(c, h); b = create(c, h)
    begin_barrier(monkeypatch)
    with ThreadPoolExecutor(2) as executor:
        f1 = executor.submit(patch, c, h, b, dependsOn=[a['id']])
        f2 = executor.submit(other.delete, '/api/items/tasks/' + a['id'], json={'revision': a['revision']}, headers=oh)
        results = [f1.result(timeout=20), f2.result(timeout=20)]
    assert sorted(r.status_code for r in results) == [200, 409]
    items = {t['id']: t for t in c.get('/api/state').json['tasks']}
    assert not items[b['id']]['dependsOn'] or a['id'] in items


def test_completion_waits_for_concurrent_predecessor_reopen(app, monkeypatch):
    c, h = member(app); other, oh = member(app, 2)
    a = create(c, h, done=True); b = create(c, h, dependsOn=[a['id']])
    entered, attempted, release = Event(), Event(), Event()
    original_check = dependencies.check_write; original_execute = HouseholdConnection.execute
    def check(con, uid, value, original=None):
        if uid == a['id'] and value['done'] is False:
            assert con.in_transaction; entered.set(); assert release.wait(10)
        return original_check(con, uid, value, original)
    def execute(con, sql, *args, **kwargs):
        if sql == 'BEGIN IMMEDIATE' and has_request_context() and request.path.endswith(b['id']):
            attempted.set()
        return original_execute(con, sql, *args, **kwargs)
    monkeypatch.setattr(dependencies, 'check_write', check)
    monkeypatch.setattr(HouseholdConnection, 'execute', execute)
    with ThreadPoolExecutor(2) as executor:
        first = executor.submit(patch, c, h, a, done=False)
        assert entered.wait(10)
        second = executor.submit(patch, other, oh, b, done=True)
        # The household authority can serialize even before the initial read.
        release.set()
        assert first.result(timeout=20).status_code == 200
        result = second.result(timeout=20)
    assert attempted.is_set() and result.status_code == 409
    assert result.json['code'] == 'task_dependencies_incomplete'
    assert task(c, b['id'])['done'] is False


def test_tv_can_read_graph_but_cannot_mutate_it(app):
    c, h = member(app); a = create(c, h); b = create(c, h, dependsOn=[a['id']])
    tv = app.test_client(); pair = tv.post('/api/pair/start', json={}).json
    assert c.post('/api/pair/approve', json={'code': pair['code'], 'name': '合成电视', 'focus': 'member1'}, headers=h).status_code == 200
    assert tv.post('/api/pair/poll', json={'secret': pair['secret']}).json['approved']
    assert task(tv, b['id'])['blockedBy'] == [a['id']]
    before = snapshot(app)
    assert patch(tv, h, b, dependsOn=[]).status_code == 403
    assert snapshot(app) == before


@pytest.mark.parametrize('operation', ['add', 'patch', 'delete', 'read'])
def test_session_revoked_after_request_guard_cannot_read_or_change_graph(app, operation):
    c, h = member(app); a = create(c, h); b = create(c, h, dependsOn=[a['id']])
    method, path, payload = {
        'add': ('POST', '/api/items/tasks', {'title': '不应创建', 'sourceId': '', 'dependsOn': [a['id']]}),
        'patch': ('PATCH', '/api/items/tasks/' + b['id'], {'revision': b['revision'], 'dependsOn': []}),
        'delete': ('DELETE', '/api/items/tasks/' + b['id'], {'revision': b['revision']}),
        'read': ('GET', '/api/state', None),
    }[operation]
    before, observed = snapshot(app), []
    def revoke():
        if request.path == path and request.method == method:
            with closing(database(app)) as con, con:
                n = con.execute("UPDATE member_sessions SET revoked_at=1 WHERE owner='member1' AND revoked_at IS NULL").rowcount
                assert n; observed.append(n)
    app.before_request_funcs[None].append(revoke)
    result = c.open(path, method=method, json=payload, headers=h)
    assert observed and result.status_code == 401, result.json
    assert set(result.json) == {'error'} and snapshot(app) == before


def test_journey_replan_reschedule_and_detach_preserve_live_dependencies(app):
    c, h = member(app)
    detail = rescheduling.create(c, h)
    a, b = detail['tasks'][:2]
    assert patch(c, h, b, dependsOn=[a['id']]).status_code == 200
    current = journeys.detail(c, detail['id'])
    assert next(t for t in current['tasks'] if t['id'] == b['id'])['blockedBy'] == [a['id']]
    value = deepcopy(current['plan']); value['title'] = '改名仍保留依赖'
    p = journeys.preview(c, h, value, journeyId=current['id'], revision=current['revision'])
    result = journeys.apply(c, h, p, 'dependencies-replan-1')
    assert result.status_code == 200, result.json
    assert task(c, b['id'])['dependsOn'] == [a['id']]
    source = rescheduling.source(c, current['id'])
    key = next(t['key'] for t in source['items'] if t['key'] == b['workflowKey'])
    p = rescheduling.reschedule(c, h, source, [key])
    result = journeys.apply(c, h, p, 'dependencies-reschedule-1')
    assert result.status_code == 200, result.json
    assert task(c, b['id'])['dependsOn'] == [a['id']]
    current = journeys.detail(c, current['id']); value = deepcopy(current['plan']); value['checklist'] = []
    p = journeys.preview(c, h, value, journeyId=current['id'], revision=current['revision'])
    assert journeys.apply(c, h, p, 'dependencies-detach-1').status_code == 200
    assert task(c, b['id'])['dependsOn'] == [a['id']]
    assert patch(c, h, task(c, b['id']), done=True).status_code == 409


def test_routine_occurrence_uses_live_dependency_and_successor_starts_empty(app, monkeypatch):
    monkeypatch.setattr(household_routines, 'today', lambda: date(2026, 9, 15))
    c, h = member(app); a = create(c, h)
    result = routines.create(c, h)
    rule = result['plan']; b = routines.entity(c, rule)
    assert patch(c, h, b, dependsOn=[a['id']]).status_code == 200
    current = routines.plan(c, rule['id'])
    assert current['current']['entity']['blockedBy'] == [a['id']]
    assert patch(c, h, task(c, b['id']), done=True).status_code == 409
    assert app.extensions['household_routines'].tick()['generated'] == 0
    assert patch(c, h, a, done=True).status_code == 200
    assert patch(c, h, task(c, b['id']), done=True).status_code == 200
    assert app.extensions['household_routines'].tick()['generated'] == 1
    current = routines.plan(c, rule['id'])
    assert current['current']['entity']['id'] != b['id']
    assert current['current']['entity']['dependsOn'] == []
    assert task(c, b['id'])['dependsOn'] == [a['id']]
    with closing(database(app)) as con:
        for raw in con.execute('SELECT result FROM routine_receipts'):
            assert 'blockedBy' not in raw[0] and 'dependencyStatus' not in raw[0]


def test_inventory_followup_is_local_and_subsequent_completion_uses_same_graph(app):
    c, h = member(app); a = create(c, h)
    current = followups.setup(c, h)
    invalid = c.post(followups.endpoint(current), json=followups.payload(current, dependsOn=[a['id']]), headers=h)
    assert invalid.status_code == 400
    created = c.post(followups.endpoint(current), json=followups.payload(current), headers=h)
    assert created.status_code == 201, created.json
    b = task(c, created.json['operation']['entityId'])
    assert b['dependsOn'] == [] and b.get('sync') is None
    assert patch(c, h, b, dependsOn=[a['id']]).status_code == 200
    assert patch(c, h, task(c, b['id']), done=True).status_code == 409
    assert c.get(followups.endpoint(current)).json['task']['done'] is False


def test_assistant_projection_creation_and_model_context_do_not_infer_dependencies(app, monkeypatch):
    c, h = member(app)
    due = c.get('/api/assistant/brief').json['today']
    a = create(c, h, due=due); b = create(c, h, due=due, dependsOn=[a['id']])
    brief = c.get('/api/assistant/brief').json
    assert next(t for t in brief['tasks'] if t['id'] == b['id'])['blockedBy'] == [a['id']]
    app.config.update(ASSISTANT_PROVIDER='openai', OPENAI_API_KEY='synthetic', OPENAI_MODEL='synthetic')
    contexts = []
    def model(_config, _prompt, context):
        contexts.append(context)
        return {'summary': '合成草案', 'actions': [{'kind': 'tasks', 'title': '模型草案', 'dependsOn': [b['id']], 'done': True}]}
    monkeypatch.setattr(home_assistant, 'model_plan', model)
    p = c.post('/api/assistant/plan', json={'prompt': '新增测试待办', 'useModel': True, 'includeHouseholdContext': True}, headers=h)
    assert p.status_code == 200, p.json
    assert all(set(t) <= {'title', 'due', 'owner'} for t in contexts[0]['tasks'])
    applied = c.post('/api/assistant/plans/' + p.json['id'] + '/apply', json={'selected': [0]}, headers=h)
    assert applied.status_code == 200, applied.json
    created = next(t for t in c.get('/api/state').json['tasks'] if t['title'] == '模型草案')
    assert created['dependsOn'] == [] and created['done'] is False
    assert patch(c, h, created, dependsOn=[b['id']]).status_code == 200
    assert patch(c, h, task(c, created['id']), done=True).status_code == 409


def test_default_or_explicit_cloud_source_rejects_dependencies_before_provider(env):
    app, c, h, remote, _ = env
    with app.extensions['cloud_accounts'].db() as con:
        con.execute("UPDATE cloud_sources SET is_primary=1 WHERE id='source-1'")
    for source in ({}, {'sourceId': 'source-1'}):
        r = c.post('/api/items/tasks', json={'title': '不应到云端', 'dependsOn': ['local-2'], **source}, headers=h)
        assert r.status_code == 400 and '本地' in r.json['error']
        assert remote.calls == []
    assert create(c, h, dependsOn=['local-2'])['blockedBy'] == ['local-2']


def test_remote_completed_state_conflicts_until_local_predecessor_complete(env):
    app, c, h, remote, provider = env
    b = task(c, 'local-1')
    assert patch(c, h, b, dependsOn=['local-2']).status_code == 200
    queue(env); process(env)
    change_remote(env, status='completed'); process(env)
    assert row(env)['status'] == 'conflict'
    assert local(env)['data']['done'] is False and local(env)['data']['dependsOn'] == ['local-2']
    assert next(iter(remote.records.values()))['status'] == 'completed' and remote.patched == 0
    p = action(env, 'conflict-preview')
    assert p.status_code == 200 and p.json['remote']['done'] is True
    rejected = action(env, 'conflict-confirm', {'previewToken': p.json['previewToken'], 'resolution': 'remote'})
    assert rejected.status_code == 409 and rejected.json['code'] == 'task_dependencies_incomplete'
    assert row(env)['status'] == 'conflict' and local(env)['data']['done'] is False
    assert patch(c, h, task(c, 'local-2'), done=True).status_code == 200
    p = action(env, 'conflict-preview')
    accepted = action(env, 'conflict-confirm', {'previewToken': p.json['previewToken'], 'resolution': 'remote'})
    assert accepted.status_code == 200, accepted.json
    assert local(env)['data']['done'] is True and local(env)['data']['dependsOn'] == ['local-2']
    assert remote.patched == 0
