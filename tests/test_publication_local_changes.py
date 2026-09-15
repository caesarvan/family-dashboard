"""Read-only publication freshness; real SQLite/Flask with fake provider HTTP."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

import pytest

from calendar_publish import digest, event_snapshot, pack, _local_changes_pending as event_changes
from task_publish import task_snapshot, _local_changes_pending as task_changes
from test_task_publish import env as task_env, queue as task_queue
from test_calendar_publish import env as calendar_env, queue as calendar_queue


TASK_URL = '/api/task-publish/state'
CALENDAR_URL = '/api/calendar-publish/journeys/journey-1'


@pytest.fixture(autouse=True)
def local_only_and_owned_hashes(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError('No real network is allowed in publication freshness tests')
    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr(socket.socket, 'connect_ex', blocked)
    monkeypatch.setattr(socket, 'create_connection', blocked)
    root = Path(__file__).resolve().parents[1]
    paths = [root / 'task_publish.py', root / 'calendar_publish.py', Path(__file__).resolve()]
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    yield
    assert before == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def state(env, kind):
    result = env[1].get(TASK_URL if kind == 'tasks' else CALENDAR_URL)
    assert result.status_code == 200, result.json
    return result.json


def publication(env, kind):
    return state(env, kind)['publications'][0]


def create_published(env, kind):
    rid = task_queue(env) if kind == 'tasks' else calendar_queue(env)
    queue = env[0].extensions['task_publish' if kind == 'tasks' else 'calendar_publish']
    assert publication(env, kind)['localChangesPending'] is None
    queue.process(rid)
    assert publication(env, kind)['status'] == 'published'
    assert publication(env, kind)['localChangesPending'] is False
    return rid, queue


def edit(env, kind, changes):
    eid = 'local-1' if kind == 'tasks' else 'event-1'
    with env[0].extensions['cloud_accounts'].db() as con:
        row = con.execute('SELECT data FROM entities WHERE id=?', (eid,)).fetchone()
        value = json.loads(row['data'])
        value.update(changes)
        con.execute('UPDATE entities SET data=?,revision=revision+1 WHERE id=?', (pack(value), eid))
    return value


@pytest.mark.parametrize('change', [{'title': 'Synthetic changed title'}, {'due': '2026-11-04'},
                                    {'note': 'Synthetic changed note'}, {'done': True}])
def test_task_published_local_change_then_successful_worker_clears_flag(task_env, change):
    rid, queue = create_published(task_env, 'tasks')
    edit(task_env, 'tasks', change)
    calls = deepcopy(task_env[3].calls)
    row = publication(task_env, 'tasks')
    assert row['status'] == 'published' and row['localChangesPending'] is True
    assert task_env[3].calls == calls
    queue.process(rid)
    row = publication(task_env, 'tasks')
    assert row['status'] == 'published' and row['localChangesPending'] is False
    assert task_env[3].created == 1 and task_env[3].patched == 1


@pytest.mark.parametrize('change', [{'title': 'Synthetic changed title'}, {'location': 'Synthetic changed city'},
                                    {'start': '2026-10-02T00:00:00+08:00', 'end': '2026-10-05T00:00:00+08:00'}])
def test_calendar_published_local_change_then_successful_worker_clears_flag(calendar_env, change):
    rid, queue = create_published(calendar_env, 'calendar')
    edit(calendar_env, 'calendar', change)
    calls = deepcopy(calendar_env[3].calls)
    row = publication(calendar_env, 'calendar')
    assert row['status'] == 'published' and row['localChangesPending'] is True
    assert calendar_env[3].calls == calls
    queue.process(rid)
    row = publication(calendar_env, 'calendar')
    assert row['status'] == 'published' and row['localChangesPending'] is False
    assert calendar_env[3].created == 1 and calendar_env[3].patched == 1


def assert_unmanaged_edits(env, kind):
    create_published(env, kind)
    edit(env, kind, {'owner': 'member1'})
    assert publication(env, kind)['localChangesPending'] is False
    edit(env, kind, {'tripId': 'synthetic-other-trip', 'journeyId': 'synthetic-other-journey',
                     'workflowKey': 'synthetic-local-key'})
    assert publication(env, kind)['localChangesPending'] is False


def test_task_owner_and_workflow_metadata_do_not_count_as_cloud_changes(task_env):
    assert_unmanaged_edits(task_env, 'tasks')


def test_calendar_owner_and_workflow_metadata_do_not_count_as_cloud_changes(calendar_env):
    assert_unmanaged_edits(calendar_env, 'calendar')


@pytest.mark.parametrize('case', ['absent', 'bad-json', 'missing-field', 'invalid-snapshot', 'deleted'])
def test_task_unavailable_or_invalid_baseline_and_missing_local_are_unknown(task_env, case):
    rid, _ = create_published(task_env, 'tasks')
    with task_env[0].extensions['cloud_accounts'].db() as con:
        if case == 'deleted':
            con.execute("DELETE FROM entities WHERE id='local-1'")
        else:
            value = {'title': 'Synthetic', 'note': '', 'due': '', 'done': False}
            if case == 'missing-field':
                del value['done']
            elif case == 'invalid-snapshot':
                value['done'] = 'false'
            baseline = None if case == 'absent' else '{broken' if case == 'bad-json' else pack(value)
            con.execute('UPDATE task_publications SET baseline_data=? WHERE id=?', (baseline, rid))
    row = publication(task_env, 'tasks')
    assert row['status'] == 'published' and row['localChangesPending'] is None
    if case == 'deleted':
        assert task_env[1].get(TASK_URL + '?entityIds=local-1').status_code == 409


@pytest.mark.parametrize('case', ['absent', 'invalid-hash', 'deleted'])
def test_calendar_unavailable_hash_and_missing_local_are_unknown(calendar_env, case):
    rid, _ = create_published(calendar_env, 'calendar')
    accounts = calendar_env[0].extensions['cloud_accounts']
    with accounts.db() as con:
        if case == 'deleted':
            original = con.execute("SELECT data FROM entities WHERE id='event-1'").fetchone()[0]
            con.execute("INSERT INTO entities(id,kind,data,updated_at) VALUES('event-2','events',?,'now')", (original,))
            con.execute("INSERT INTO journey_links VALUES('journey-1','event:second','event-2','events')")
            con.execute("DELETE FROM entities WHERE id='event-1'")
        else:
            con.execute('UPDATE calendar_publications SET last_hash=? WHERE id=?',
                        ('' if case == 'absent' else 'invalid-confirmed-hash', rid))
    row = publication(calendar_env, 'calendar')
    assert row['status'] == 'published' and row['localChangesPending'] is None
    if case == 'deleted':
        with accounts.db() as con:
            con.execute("DELETE FROM entities WHERE id='event-2'")
        assert calendar_env[1].get(CALENDAR_URL).status_code == 400


def guarded_read_and_privacy(env, kind, monkeypatch):
    create_published(env, kind)
    app, owner, headers, remote, _ = env
    accounts = app.extensions['cloud_accounts']
    original = accounts.db
    queries = []

    def snapshot():
        with original() as con:
            names = ['entities', 'task_publications', 'calendar_publications', 'settings', 'audit',
                     'cloud_accounts', 'cloud_sources']
            return {name: con.execute('SELECT * FROM ' + name + ' ORDER BY rowid').fetchall() for name in names}

    before, calls = snapshot(), deepcopy(remote.calls)

    @contextmanager
    def readonly():
        with original() as con:
            con.execute('PRAGMA query_only=ON')
            con.set_trace_callback(queries.append)
            changes = con.total_changes
            yield con
            assert con.total_changes == changes

    monkeypatch.setattr(accounts, 'db', readonly)
    value = state(env, kind)
    assert snapshot() == before and remote.calls == calls
    assert any(sql == 'BEGIN' for sql in queries)
    row = value['publications'][0]
    common = {'id', 'entityId', 'sourceId', 'provider', 'status', 'error', 'updatedAt', 'localChangesPending'}
    expected = common | ({'owner', 'accountOwner', 'reconnectSourceIds', 'canManage'} if kind == 'tasks'
                         else {'reviewRequired', 'localRevision'})
    assert set(row) == expected
    assert not any(key in json.dumps(value) for key in ['baseline_data', 'last_hash', 'remote_id', 'current_data', 'pending_data'])
    other = app.test_client()
    assert other.post('/api/login', json={'username': 'member2', 'password': 'testing-password-two'}).status_code == 200
    other_value = other.get(TASK_URL if kind == 'tasks' else CALENDAR_URL)
    assert other_value.status_code == 200
    if kind == 'tasks':
        assert other_value.json['publications'][0]['localChangesPending'] is False
        assert other_value.json['publications'][0]['canManage'] is False
    else:
        assert other_value.json['publications'] == other_value.json['sources'] == []
    tv = app.test_client()
    pair = tv.post('/api/pair/start', json={}).json
    assert owner.post('/api/pair/approve', json={'code': pair['code'], 'name': 'Synthetic display',
                                               'focus': 'member1'}, headers=headers).status_code == 200
    assert tv.post('/api/pair/poll', json={'secret': pair['secret']}).json['approved']
    url = TASK_URL if kind == 'tasks' else CALENDAR_URL
    assert tv.get(url).status_code == 403
    assert app.test_client().get(url).status_code == 401
    assert remote.calls == calls


def test_task_state_readonly_and_existing_visibility_scope(task_env, monkeypatch):
    guarded_read_and_privacy(task_env, 'tasks', monkeypatch)


def test_calendar_state_readonly_and_owner_only(calendar_env, monkeypatch):
    guarded_read_and_privacy(calendar_env, 'calendar', monkeypatch)


def snapshot_race(env, kind, monkeypatch):
    """Commit a new generation between local SELECT and publication SELECT."""
    rid, _ = create_published(env, kind)
    accounts = env[0].extensions['cloud_accounts']
    original = accounts.db
    with original() as con:
        assert con.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
    triggered = []
    eid = 'local-1' if kind == 'tasks' else 'event-1'

    class Connection:
        def __init__(self, con):
            self.con = con

        def execute(self, sql, args=()):
            if 'FROM cloud_sources s JOIN cloud_accounts a' in sql and not triggered:
                triggered.append(True)
                with original() as writer:
                    value = json.loads(writer.execute('SELECT data FROM entities WHERE id=?', (eid,)).fetchone()[0])
                    value['title'] = 'Synthetic later generation'
                    writer.execute('UPDATE entities SET data=?,revision=revision+1 WHERE id=?', (pack(value), eid))
                    if kind == 'tasks':
                        writer.execute("UPDATE task_publications SET baseline_data=?,status='paused' WHERE id=?", (pack(task_snapshot(value)), rid))
                    else:
                        writer.execute("UPDATE calendar_publications SET last_hash=?,status='paused' WHERE id=?", (digest(event_snapshot(value)), rid))
            return self.con.execute(sql, args)

    @contextmanager
    def with_interleaving():
        with original() as con:
            yield Connection(con)

    monkeypatch.setattr(accounts, 'db', with_interleaving)
    value = state(env, kind)
    assert triggered == [True]
    row = value['publications'][0]
    assert row['status'] == 'published' and row['localChangesPending'] is False
    items = value['tasks' if kind == 'tasks' else 'events']
    assert next(item for item in items if item['id'] == eid)['title'] != 'Synthetic later generation'
    fresh = state(env, kind)
    assert fresh['publications'][0]['status'] == 'paused'
    assert fresh['publications'][0]['localChangesPending'] is False
    assert next(item for item in fresh['tasks' if kind == 'tasks' else 'events'] if item['id'] == eid)['title'] == 'Synthetic later generation'


def test_task_state_uses_one_sqlite_read_snapshot(task_env, monkeypatch):
    snapshot_race(task_env, 'tasks', monkeypatch)


def test_calendar_state_uses_one_sqlite_read_snapshot(calendar_env, monkeypatch):
    snapshot_race(calendar_env, 'calendar', monkeypatch)


def test_task_comparison_invalid_local_evidence_is_unknown():
    baseline = pack({'title': 'Synthetic', 'note': '', 'due': '', 'done': False})
    for raw in [None, '', 'null', '[]', '{}', '{bad', pack({'title': 'Synthetic', 'done': 'false'})]:
        assert task_changes(raw, baseline) is None


def test_calendar_comparison_invalid_local_evidence_is_unknown():
    valid = {'title': 'Synthetic', 'start': '2026-10-01T00:00:00Z', 'end': '2026-10-02T00:00:00Z'}
    baseline = digest(event_snapshot(valid))
    for value in [None, [], {}, {**valid, 'end': 'invalid'}]:
        assert event_changes(value, baseline) is None
