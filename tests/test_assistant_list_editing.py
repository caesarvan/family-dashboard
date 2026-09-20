"""Real Flask/SQLite coverage for edited assistant confirmations and recovery."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date, timedelta
import json
from pathlib import Path
import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest

from app import create_app
import home_assistant
import member_sessions
from test_app import app, member
from test_household_spaces import create_space


def connection(app):
    return sqlite3.connect(Path(app.config['DATA_DIR']) / 'household.sqlite3')


def business(app):
    with closing(connection(app)) as con:
        return {table: con.execute('SELECT * FROM ' + table + ' ORDER BY 1').fetchall()
                for table in ('entities', 'assistant_plans', 'audit', 'settings')}


def plan(client, headers, prompt='采购：明天牛奶；后天面包'):
    response = client.post('/api/assistant/plan', json={'prompt': prompt}, headers=headers)
    assert response.status_code == 200, response.json
    return response.json


def apply(client, headers, draft, payload):
    return client.post('/api/assistant/plans/' + draft['id'] + '/apply', json=payload, headers=headers)


def read(client, draft):
    return client.get('/api/assistant/plans/' + draft['id'])


@pytest.mark.parametrize('model', [False, True])
def test_shopping_due_survives_plan_and_confirmation(app, monkeypatch, model):
    client, headers = member(app)
    today = date.fromisoformat(client.get('/api/assistant/brief').json['today'])
    due = (today + timedelta(days=1)).isoformat()
    app.config.update(OPENAI_API_KEY='synthetic-only', OPENAI_MODEL='synthetic-model')
    monkeypatch.setattr(home_assistant, 'model_plan', lambda *_: {'summary': '建议', 'actions': [
        {'kind': 'shopping', 'title': '牛奶', 'owner': 'shared', 'due': due, 'quantity': '2 件',
         'budget': 12345, 'actual': 67890, 'priority': 'high'}]})
    response = client.post('/api/assistant/plan', json={'prompt': '采购：明天牛奶', 'useModel': model}, headers=headers)
    assert response.status_code == 200
    draft = response.json
    assert draft['actions'][0]['data']['due'] == due
    assert draft['actions'][0]['data']['budget'] is None
    assert draft['actions'][0]['data']['actual'] is None
    assert draft['actions'][0]['data']['priority'] == 'normal'
    assert apply(client, headers, draft, {'selected': [0]}).status_code == 200
    assert client.get('/api/state').json['shopping'][0]['due'] == due


def test_override_fields_receipt_get_restart_and_canonical_replay(app):
    client, headers = member(app)
    draft = plan(client, headers)
    assert read(client, draft).json == {'id': draft['id'], 'status': 'pending', 'plan': draft, 'receipt': None}
    payload = {'selected': [1, 0], 'overrides': [
        {'index': 1, 'data': {'title': ' 全麦面包 ', 'owner': 'shared', 'due': '', 'note': ' 一份 ',
                              'quantity': ' 2 袋 ', 'priority': 'high', 'budget': 15990}},
        {'index': 0, 'data': {'owner': 'member2', 'due': '2028-02-29', 'budget': 0}}]}
    saved = apply(client, headers, draft, payload)
    assert saved.status_code == 200, saved.json
    rows = {row['title']: row for row in client.get('/api/state').json['shopping']}
    assert set(rows) == {'牛奶', '全麦面包'}
    assert rows['全麦面包']['note'] == '一份' and rows['全麦面包']['quantity'] == '2 袋'
    assert rows['全麦面包']['budget'] == 15990 and rows['全麦面包']['priority'] == 'high'
    assert rows['牛奶']['owner'] == 'member2' and rows['牛奶']['due'] == '2028-02-29' and rows['牛奶']['budget'] == 0
    assert all(not row['done'] and row['actual'] is None for row in rows.values())
    before = business(app)
    normalized = {'overrides': [{'data': dict(reversed(list(row['data'].items()))), 'index': row['index']}
                                for row in reversed(payload['overrides'])], 'selected': [0, 1]}
    assert apply(client, headers, draft, normalized).json == saved.json
    recovered = read(client, draft).json
    assert recovered['status'] == 'applied' and recovered['receipt'] == saved.json
    assert recovered['plan']['actions'][1]['data']['title'] == '全麦面包'
    assert recovered['plan']['actions'][1]['data']['budget'] == 15990
    assert '_confirmation' not in json.dumps(recovered)
    assert business(app) == before
    restarted = create_app(dict(app.config))
    fresh = restarted.test_client()
    fresh.set_cookie('session', client.get_cookie('session').value)
    assert read(fresh, draft).json == recovered
    changed = apply(fresh, headers, draft, {'selected': [0]})
    assert changed.status_code == 409 and business(app) == before


@pytest.mark.parametrize('budget', [None, 0, 100_000_000_000])
def test_budget_units_and_null(app, budget):
    client, headers = member(app); draft = plan(client, headers)
    result = apply(client, headers, draft, {'selected': [0], 'overrides': [{'index': 0, 'data': {'budget': budget}}]})
    assert result.status_code == 200
    assert client.get('/api/state').json['shopping'][0]['budget'] == budget


@pytest.mark.parametrize('payload', [
    {'selected': [True]}, {'selected': [0, 0]}, {'selected': [-1]}, {'selected': [2]},
    {'selected': [0], 'extra': True}, {'selected': [0], 'overrides': None},
    {'selected': [0], 'overrides': [{'index': True, 'data': {}}]},
    {'selected': [0], 'overrides': [{'index': 1, 'data': {}}]},
    {'selected': [0], 'overrides': [{'index': 0, 'data': {}}, {'index': 0, 'data': {}}]},
    {'selected': [0], 'overrides': [{'index': 0, 'data': {}, 'kind': 'tasks'}]},
    *({'selected': [0], 'overrides': [{'index': 0, 'data': {field: value}}]}
      for field, value in [('done', True), ('actual', 1), ('tripId', 'foreign'), ('photoIds', []),
                           ('budget', True), ('budget', 1.2), ('budget', -1), ('budget', 100_000_000_001),
                           ('priority', 'urgent'), ('due', False), ('due', None), ('due', '2028-02-30'),
                           ('owner', []), ('title', ''), ('quantity', ''), ('note', 'x' * 501)])
])
def test_invalid_confirmation_is_atomic(app, payload):
    client, headers = member(app); draft = plan(client, headers); before = business(app)
    response = apply(client, headers, draft, payload)
    assert response.status_code == 400, response.json
    assert business(app) == before


@pytest.mark.parametrize('due', [None, False, 0, []])
def test_task_due_rejects_non_string_instead_of_clearing(app, due):
    client, headers = member(app); draft = plan(client, headers, '待办：明天检查证件')
    before = business(app)
    assert apply(client, headers, draft, {'selected': [0], 'overrides': [{'index': 0, 'data': {'due': due}}]}).status_code == 400
    assert business(app) == before


def test_task_fields_and_shopping_only_keys_rejected(app):
    client, headers = member(app); draft = plan(client, headers, '待办：检查证件')
    for field in ('budget', 'quantity', 'priority', 'dependsOn', 'kind'):
        before = business(app)
        assert apply(client, headers, draft, {'selected': [0], 'overrides': [{'index': 0, 'data': {field: None}}]}).status_code == 400
        assert business(app) == before
    saved = apply(client, headers, draft, {'selected': [0], 'overrides': [{'index': 0, 'data': {
        'title': '检查签证', 'owner': 'member2', 'due': '2028-02-29', 'note': '确认有效期'}}]})
    assert saved.status_code == 200
    item = client.get('/api/state').json['tasks'][0]
    assert (item['title'], item['owner'], item['due'], item['note'], item['done']) == ('检查签证', 'member2', '2028-02-29', '确认有效期', False)


def test_bad_second_assignee_rolls_back_first_insert(app):
    client, headers = member(app); draft = plan(client, headers); before = business(app)
    response = apply(client, headers, draft, {'selected': [0, 1], 'overrides': [{'index': 1, 'data': {'owner': 'missing-member'}}]})
    assert response.status_code == 400 and business(app) == before


def test_completed_replay_survives_assignee_removal_and_expiry(app):
    client, headers = member(app); draft = plan(client, headers)
    payload = {'selected': [0], 'overrides': [{'index': 0, 'data': {'owner': 'member2'}}]}
    saved = apply(client, headers, draft, payload)
    with closing(connection(app)) as con:
        con.execute("UPDATE household_memberships SET state='left' WHERE member_id='member2'")
        con.execute('UPDATE assistant_plans SET created_at=? WHERE id=?', (time.time() - 90000, draft['id']))
        con.commit()
    before = business(app)
    assert apply(client, headers, draft, payload).json == saved.json
    assert read(client, draft).json['receipt'] == saved.json
    assert apply(client, headers, draft, {'selected': [0], 'overrides': [{'index': 0, 'data': {'owner': 'shared'}}]}).status_code == 409
    assert apply(client, headers, draft, {'selected': [0], 'overrides': [{'index': 0, 'data': {'done': True}}]}).status_code == 400
    assert business(app) == before


def test_legacy_completed_receipt_and_empty_override_compatibility(app):
    client, headers = member(app); draft = plan(client, headers)
    saved = apply(client, headers, draft, {'selected': [0]})
    assert apply(client, headers, draft, {'selected': [0], 'overrides': []}).json == saved.json
    with closing(connection(app)) as con:
        data = json.loads(con.execute('SELECT data FROM assistant_plans WHERE id=?', (draft['id'],)).fetchone()[0])
        data.pop('_confirmation')
        con.execute('UPDATE assistant_plans SET data=? WHERE id=?', (json.dumps(data), draft['id'])); con.commit()
    before = business(app)
    assert apply(client, headers, draft, {'selected': [1]}).json == saved.json
    assert read(client, draft).json['receipt'] == saved.json and business(app) == before


def test_pending_expiry_unknown_and_query_rejection(app):
    client, headers = member(app); draft = plan(client, headers)
    with closing(connection(app)) as con:
        con.execute('UPDATE assistant_plans SET created_at=? WHERE id=?', (time.time() - 90000, draft['id'])); con.commit()
    before = business(app)
    result = read(client, draft).json
    assert result['status'] == 'expired' and result['receipt'] is None
    assert apply(client, headers, draft, {'selected': [0]}).status_code == 409
    assert client.get('/api/assistant/plans/' + draft['id'] + '?owner=member2').status_code == 400
    assert client.get('/api/assistant/plans/' + '0' * 32).status_code == 404
    assert business(app) == before


def test_anonymous_partner_tv_csrf_and_other_household_denied(app):
    client, headers = member(app); draft = plan(client, headers); other, auth = member(app, 2)
    path = '/api/assistant/plans/' + draft['id']
    assert app.test_client().get(path).status_code == 401
    assert other.get(path).status_code == 404
    assert apply(other, auth, draft, {'selected': [0]}).status_code == 404
    assert client.post(path + '/apply', json={'selected': [0]}).status_code == 403
    tv = app.test_client(); pair = tv.post('/api/pair/start', json={}).json
    assert client.post('/api/pair/approve', json={'code': pair['code'], 'name': '合成电视', 'focus': 'member1'}, headers=headers).status_code == 200
    assert tv.post('/api/pair/poll', json={'secret': pair['secret']}).json['approved']
    assert tv.get(path).status_code == 403
    assert tv.post(path + '/apply', json={'selected': [0]}, headers=headers).status_code == 403
    child, _, space = create_space(app)
    assert child.get(space['entry']).status_code == 303
    assert child.post('/api/login', json={'username': 'member1', 'password': 'second-home-password-one'}).status_code == 200
    ch = {'X-CSRF-Token': child.get('/api/me').json['csrf']}
    assert child.get(path).status_code == 404
    assert child.post(path + '/apply', json={'selected': [0]}, headers=ch).status_code == 404
    assert read(client, draft).json['status'] == 'pending'


@pytest.mark.parametrize('applied', [False, True])
def test_get_rechecks_actual_session_after_projection(app, monkeypatch, applied):
    client, headers = member(app); draft = plan(client, headers)
    if applied:
        assert apply(client, headers, draft, {'selected': [0]}).status_code == 200
    real_loads = json.loads; revoked = []
    def decode(value, *args, **kwargs):
        result = real_loads(value, *args, **kwargs)
        if isinstance(result, dict) and result.get('id') == draft['id'] and 'actions' in result and not revoked:
            with closing(connection(app)) as con:
                con.execute("UPDATE member_sessions SET revoked_at=1 WHERE owner='member1'"); con.commit()
            revoked.append(True)
        return result
    monkeypatch.setattr(home_assistant, 'json', SimpleNamespace(loads=decode, dumps=json.dumps))
    response = read(client, draft)
    assert revoked and response.status_code == 401
    assert '牛奶' not in response.get_data(as_text=True) and 'receipt' not in response.json


def test_write_tail_expiry_rolls_back_entities_receipt_and_audit(app, monkeypatch):
    client, headers = member(app); draft = plan(client, headers, '待办：检查证件')
    before = business(app)
    with closing(connection(app)) as con:
        expiry = con.execute('SELECT max(expires_at) FROM member_sessions').fetchone()[0]
    original = home_assistant.dependencies.check_write
    def expire(*args, **kwargs):
        result = original(*args, **kwargs)
        monkeypatch.setattr(member_sessions, 'time', SimpleNamespace(time=lambda: expiry + 1))
        return result
    monkeypatch.setattr(home_assistant.dependencies, 'check_write', expire)
    assert apply(client, headers, draft, {'selected': [0]}).status_code == 401
    assert business(app) == before


def test_batch_limit_failure_has_no_partial_entities(app):
    client, headers = member(app); draft = plan(client, headers)
    with closing(connection(app)) as con:
        con.executemany('INSERT INTO entities(id,kind,data,updated_at) VALUES(?,?,?,?)',
                        [(f'{i:024x}', 'shopping', json.dumps({'title': '合成旧记录'}), '2026-01-01') for i in range(2499)])
        con.commit()
    before = business(app)
    assert apply(client, headers, draft, {'selected': [0, 1]}).status_code == 409
    assert business(app) == before


def test_concurrent_same_confirmation_creates_once(app):
    client, headers = member(app); draft = plan(client, headers)
    cookie = client.get_cookie('session').value; barrier = threading.Barrier(2)
    def send():
        current = app.test_client(); current.set_cookie('session', cookie)
        barrier.wait(timeout=10)
        result = apply(current, headers, draft, {'selected': [0, 1]})
        return result.status_code, result.json
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: send(), range(2)))
    assert results[0] == results[1] and results[0][0] == 200
    assert len(client.get('/api/state').json['shopping']) == 2
    with closing(connection(app)) as con:
        assert con.execute("SELECT count(*) FROM audit WHERE action='assistant_plan_applied'").fetchone()[0] == 1
