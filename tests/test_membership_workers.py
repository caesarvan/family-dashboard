"""Real temporary SQLite and provider adapters; synthetic transport, no cloud calls."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import socket
from types import SimpleNamespace

import pytest

from cloud_providers import ProviderError
from test_calendar_publish import env as calendar_fixture, queue as queue_calendar
from test_task_publish import env as task_fixture, queue as queue_task, change_remote


@pytest.fixture(scope='session')
def domain():
    try:
        import household_memberships
        return household_memberships
    except ModuleNotFoundError as error:
        if error.name != 'household_memberships':
            raise
    source = Path(os.environ['MEMBERSHIP_DOMAIN_SOURCE'])
    assert hashlib.sha256(source.read_bytes()).hexdigest() == 'dad3afb0efa5bd8aa5cd0670185d023fb18c00c5b02d8468b682fbaeb7c9e757'
    spec = importlib.util.spec_from_file_location('fixed_membership_domain', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(params=[('calendar', 'google'), ('calendar', 'microsoft'), ('task', 'google'), ('task', 'microsoft')])
def env(tmp_path, request, domain, monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('External network is forbidden in membership worker tests')
    monkeypatch.setattr(socket.socket, 'connect', blocked)
    kind, provider = request.param
    fixture = calendar_fixture if kind == 'calendar' else task_fixture
    value = fixture.__wrapped__(tmp_path, SimpleNamespace(param=provider))
    with value[0].extensions['cloud_accounts'].db() as con:
        con.execute('BEGIN IMMEDIATE')
        domain.schema_initialize(con)
    rid = (queue_calendar if kind == 'calendar' else queue_task)(value)
    return SimpleNamespace(value=value, kind=kind, app=value[0], remote=value[3], rid=rid,
                           queue=value[0].extensions[kind + '_publish'], domain=domain)


def record(env):
    with env.app.extensions['cloud_accounts'].db() as con:
        return dict(con.execute('SELECT * FROM ' + env.kind + '_publications WHERE id=?', (env.rid,)).fetchone())


def stop_member(env, member='member1'):
    with env.app.extensions['cloud_accounts'].db() as con:
        con.execute('BEGIN IMMEDIATE')
        env.domain.remove_membership(con, household_id='default', actor_member_id='member2' if member == 'member1' else 'member1',
            member_id=member, expected_auth_version=1, expected_revision=1,
            request_id=secrets.token_hex(16), intent_digest='1' * 64)


def hook_transport(env, monkeypatch, callback):
    original = env.app.config['CLOUD_TRANSPORT']
    def wrapped(method, url, token, body=None, headers=None):
        result = original(method, url, token, body, headers)
        callback(method, url, result)
        return result
    monkeypatch.setitem(env.app.config, 'CLOUD_TRANSPORT', wrapped)


def test_inactive_owner_prevents_any_provider_request(env):
    stop_member(env)
    before = record(env)
    env.queue.process(env.rid)
    assert env.remote.calls == []
    assert record(env) == before and before['status'] == 'paused'


def test_removal_during_read_prevents_following_external_write(env, monkeypatch):
    fired = []
    def callback(method, url, result):
        if not fired and method == 'GET':
            fired.append(True)
            stop_member(env)
    hook_transport(env, monkeypatch, callback)
    env.queue.process(env.rid)
    assert fired
    assert not any(call[0] in ('POST', 'PATCH') for call in env.remote.calls)
    assert record(env)['status'] == 'paused'


@pytest.mark.parametrize('failure', [False, True])
def test_inflight_create_cannot_revive_paused_queue_with_success_or_error(env, monkeypatch, failure):
    fired = []
    def callback(method, url, result):
        if method == 'POST':
            fired.append(len(env.remote.calls))
            stop_member(env)
            if failure:
                raise ProviderError('Synthetic lost response after committed external create', 502)
    hook_transport(env, monkeypatch, callback)
    env.queue.process(env.rid)
    row = record(env)
    assert fired and env.remote.created == 1
    assert len(env.remote.calls) == fired[0]  # No provider's implicit write-readback GET after removal.
    assert row['status'] == 'paused' and not row['remote_id']
    assert row['attempts'] == 0 and row['error'] == ''
    calls = len(env.remote.calls)
    env.queue.process(env.rid)
    assert len(env.remote.calls) == calls


def test_inflight_result_cannot_overwrite_changed_queue_binding(env, monkeypatch):
    changed = []
    def callback(method, url, result):
        if method == 'POST':
            with env.app.extensions['cloud_accounts'].db() as con:
                con.execute('BEGIN IMMEDIATE')
                con.execute('UPDATE ' + env.kind + '_publications SET source_id=? WHERE id=?', ('changed-source', env.rid))
            changed.append(record(env))
    hook_transport(env, monkeypatch, callback)
    env.queue.process(env.rid)
    assert changed and record(env) == changed[0]


def test_published_readback_cannot_revive_paused_or_apply_remote_done(env, monkeypatch):
    env.queue.process(env.rid)
    assert record(env)['status'] == 'published'
    if env.kind == 'task':
        change_remote(env.value, **({'status':'completed'} if env.value[4] == 'google' else {'status':'completed'}))
    with env.app.extensions['cloud_accounts'].db() as con:
        before_entities = [tuple(row) for row in con.execute('SELECT * FROM entities ORDER BY id')]
    fired = []
    def callback(method, url, result):
        if not fired and method == 'GET':
            fired.append(True)
            stop_member(env)
    hook_transport(env, monkeypatch, callback)
    env.queue.process(env.rid)
    assert fired and record(env)['status'] == 'paused'
    with env.app.extensions['cloud_accounts'].db() as con:
        assert [tuple(row) for row in con.execute('SELECT * FROM entities ORDER BY id')] == before_entities


def test_missing_membership_is_fail_closed_without_changing_the_queue(env):
    with env.app.extensions['cloud_accounts'].db() as con:
        con.execute("DELETE FROM household_memberships WHERE member_id='member1'")
    before = record(env)
    env.queue.process(env.rid)
    assert env.remote.calls == [] and record(env) == before


@pytest.mark.parametrize('version', ['auth_version', 'membership_revision'])
def test_inflight_result_is_bound_to_original_member_generation(env, monkeypatch, version):
    changed = []
    def callback(method, url, result):
        if method == 'POST':
            with env.app.extensions['cloud_accounts'].db() as con:
                con.execute('BEGIN IMMEDIATE')
                if version == 'auth_version':
                    con.execute("UPDATE users SET auth_version=auth_version+1 WHERE id='member1'")
                else:
                    con.execute("UPDATE household_memberships SET revision=revision+1 WHERE member_id='member1'")
            changed.append(record(env))
    hook_transport(env, monkeypatch, callback)
    env.queue.process(env.rid)
    assert changed and record(env) == changed[0]
    assert not record(env)['remote_id']


@pytest.mark.parametrize('env', [('task', 'google'), ('task', 'microsoft')], indirect=True)
def test_publication_owner_and_shared_account_owner_are_both_required(env, monkeypatch):
    with env.app.extensions['cloud_accounts'].db() as con:
        con.execute("UPDATE task_publications SET owner='member2' WHERE id=?", (env.rid,))
        con.execute("UPDATE cloud_sources SET is_primary=1 WHERE id='source-1'")
    fired = []
    def callback(method, url, result):
        if method == 'POST':
            fired.append(True)
            stop_member(env, 'member1')
    hook_transport(env, monkeypatch, callback)
    env.queue.process(env.rid)
    assert fired and record(env)['status'] == 'paused'
    assert not record(env)['remote_id']


def test_manual_conflict_read_cannot_return_or_apply_after_queue_pause(env, monkeypatch):
    env.queue.process(env.rid)
    raw = next(iter(env.remote.records.values()))
    raw['@odata.etag' if env.value[4] == 'microsoft' else 'etag'] = '"external-change"'
    raw['title' if env.kind == 'task' else 'subject' if env.value[4] == 'microsoft' else 'summary'] = 'Synthetic remote edit'
    env.queue.process(env.rid)
    assert record(env)['status'] == 'conflict'
    client, headers = env.value[1:3]
    base = '/api/' + env.kind + '-publish/publications/' + env.rid
    payload, action = {}, 'conflict-preview'
    if env.kind == 'task':
        preview = client.post(base + '/conflict-preview', json={}, headers=headers)
        assert preview.status_code == 200
        payload, action = {'previewToken': preview.json['previewToken'], 'resolution': 'remote'}, 'conflict-confirm'
    with env.app.extensions['cloud_accounts'].db() as con:
        original = [tuple(row) for row in con.execute('SELECT * FROM entities ORDER BY id')]
    fired = []
    def callback(method, url, result):
        if not fired and method == 'GET':
            fired.append(True)
            with env.app.extensions['cloud_accounts'].db() as con:
                con.execute('BEGIN IMMEDIATE')
                con.execute('UPDATE ' + env.kind + "_publications SET status='paused' WHERE id=?", (env.rid,))
    hook_transport(env, monkeypatch, callback)
    response = client.post(base + '/' + action, json=payload, headers=headers)
    assert fired and response.status_code == 409, response.json
    assert record(env)['status'] == 'paused'
    with env.app.extensions['cloud_accounts'].db() as con:
        assert [tuple(row) for row in con.execute('SELECT * FROM entities ORDER BY id')] == original


@pytest.mark.parametrize('env', [('task', 'google'), ('task', 'microsoft')], indirect=True)
def test_manual_resume_cannot_authorize_an_inactive_publication_owner(env):
    with env.app.extensions['cloud_accounts'].db() as con:
        con.execute("UPDATE task_publications SET owner='member2' WHERE id=?", (env.rid,))
        con.execute("UPDATE cloud_sources SET is_primary=1 WHERE id='source-1'")
    stop_member(env, 'member2')
    response = env.value[1].post('/api/task-publish/publications/' + env.rid + '/resume', json={}, headers=env.value[2])
    assert response.status_code == 409
    assert record(env)['status'] == 'paused' and not env.remote.calls
