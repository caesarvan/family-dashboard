"""Real Flask + SQLite + real provider adapters, synthetic HTTP only."""
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import time
import threading
from types import SimpleNamespace
from urllib.parse import unquote, urlsplit

import pytest

from app import create_app
from cloud_accounts import task_write_allowed
from cloud_providers import ProviderError
from task_publish import TaskPublicationQueue


class Remote:
    def __init__(self):
        self.records = {}; self.calls = []; self.created = 0; self.patched = 0
        self.lose_create = False; self.lose_patch = False; self.race_patch = False
        self.reject_post = 0; self.hide = False; self.bad_etag = False

    def fail(self, code):
        error = ProviderError('合成远端错误', 409 if code == 412 else code)
        error.upstream_status = code
        raise error

    def transport(self, method, url, token, body=None, headers=None):
        self.calls.append((method, url, deepcopy(body), deepcopy(headers)))
        parsed = urlsplit(url); path = unquote(parsed.path)
        microsoft = parsed.hostname == 'graph.microsoft.com'
        tag = '@odata.etag' if microsoft else 'etag'
        if path.endswith('/lists'):
            return {'value' if microsoft else 'items': [{'id': 'list-1', 'displayName': '测试主清单', 'title': '测试主清单'}]}
        if path.endswith('/calendars') or path.endswith('/calendarList'):
            return {'value' if microsoft else 'items': []}
        assert '/tasks' in path, path
        task_id = path.rsplit('/tasks', 1)[1].lstrip('/')
        if method == 'GET' and not task_id:
            return {'value' if microsoft else 'items': [] if self.hide else list(deepcopy(self.records).values())}
        if method == 'GET':
            if task_id not in self.records:
                self.fail(404)
            result = deepcopy(self.records[task_id])
            if self.bad_etag:
                result.pop(tag, None)
            return result
        if method == 'POST':
            if self.reject_post:
                self.fail(self.reject_post)
            self.created += 1; uid = 'task-' + str(self.created)
            raw = {**deepcopy(body), 'id': uid, tag: '"v1"'}
            self.records[uid] = raw
            if self.lose_create:
                self.lose_create = False; self.fail(502)
            return deepcopy(raw)
        if method == 'PATCH':
            if task_id not in self.records:
                self.fail(404)
            raw = self.records[task_id]
            if self.race_patch:
                self.race_patch = False; raw[tag] = '"race"'
            if headers.get('If-Match') != raw[tag]:
                self.fail(412)
            self.patched += 1; raw.update(deepcopy(body)); raw[tag] = '"v' + str(self.patched + 1) + '"'
            if self.lose_patch:
                self.lose_patch = False; self.fail(502)
            return deepcopy(raw)
        raise AssertionError((method, url))


@pytest.fixture(params=['microsoft', 'google'])
def env(tmp_path, request):
    remote = Remote(); provider = request.param
    app = create_app({'TESTING': True, 'SECRET_KEY': 'task-publication-test', 'DATA_DIR': str(tmp_path),
                      'SESSION_COOKIE_SECURE': False, 'PUBLIC_ORIGIN': 'http://localhost',
                      'MEMBER1_PASSWORD': 'testing-password-one', 'MEMBER2_PASSWORD': 'testing-password-two',
                      'GOOGLE_CLIENT_ID': 'test-client', 'GOOGLE_CLIENT_SECRET': 'test-secret',
                      'MICROSOFT_CLIENT_ID': 'test-client', 'MICROSOFT_CLIENT_SECRET': 'test-secret',
                      'CLOUD_TRANSPORT': remote.transport})
    accounts = app.extensions['cloud_accounts']
    scope = 'User.Read Calendars.Read Tasks.ReadWrite' if provider == 'microsoft' else 'https://www.googleapis.com/auth/tasks https://www.googleapis.com/auth/calendar.readonly'
    token = accounts.encrypt({'access_token': 'synthetic', 'scope': scope, 'expires_at': time.time() + 3600})
    with accounts.db() as con:
        for aid, owner in [('account-1', 'member1'), ('account-2', 'member2')]:
            con.execute('INSERT INTO cloud_accounts(id,owner,provider,client_id,subject,name,email,tokens) VALUES(?,?,?,?,?,?,?,?)', (aid, owner, provider, 'test-client', aid, aid, aid + '@example.invalid', token))
            con.execute("INSERT INTO cloud_sources(id,account_id,remote_id,kind,name,owner) VALUES(?,?,?,'tasks',?,'shared')", ('source-' + aid[-1], aid, 'list-' + aid[-1], '清单-' + aid[-1]))
        con.execute("INSERT INTO entities(id,kind,data,updated_at) VALUES('trip-1','trips','{}','now')")
        con.execute("INSERT INTO journey_workflows(id,trip_id,plan,created_by,created_at,updated_at) VALUES('journey-1','trip-1','{}','member1','now','now')")
        for i in range(1, 3):
            value = {'title': '准备护照' if i == 1 else '未选择的待办', 'done': False, 'owner': 'member2', 'due': '2026-10-01', 'note': '合成备注 <安全>', 'tripId': 'trip-1', 'journeyId': 'journey-1'}
            con.execute("INSERT INTO entities(id,kind,data,updated_at) VALUES(?,'tasks',?,'now')", ('local-' + str(i), json.dumps(value)))
            con.execute("INSERT INTO journey_links VALUES('journey-1',?,?, 'tasks')", ('task:' + str(i), 'local-' + str(i)))
    client = app.test_client()
    assert client.post('/api/login', json={'username': 'member1', 'password': 'testing-password-one'}).status_code == 200
    headers = {'X-CSRF-Token': client.get('/api/me').json['csrf']}
    return app, client, headers, remote, provider


def queue(env, source='source-1'):
    app, client, headers, remote, provider = env
    p = client.post('/api/task-publish/preview', json={'entityIds': ['local-1'], 'sourceId': source}, headers=headers)
    assert p.status_code == 200, p.json
    r = client.post('/api/task-publish/confirm', json={'previewToken': p.json['previewToken']}, headers=headers)
    assert r.status_code == 200, r.json
    return r.json['publicationIds'][0]


def row(env):
    with env[0].extensions['cloud_accounts'].db() as con:
        r = con.execute('SELECT * FROM task_publications ORDER BY created_at LIMIT 1').fetchone()
        return dict(r) if r else None


def local(env):
    with env[0].extensions['cloud_accounts'].db() as con:
        r = con.execute("SELECT * FROM entities WHERE id='local-1'").fetchone()
        return dict(r) | {'data': json.loads(r['data'])} if r else None


def change_local(env, **changes):
    value = local(env)['data']; value.update(changes)
    with env[0].extensions['cloud_accounts'].db() as con:
        con.execute("UPDATE entities SET data=?,revision=revision+1 WHERE id='local-1'", (json.dumps(value),))


def change_remote(env, **changes):
    raw = next(iter(env[3].records.values())); raw.update(changes)
    raw['@odata.etag' if env[4] == 'microsoft' else 'etag'] = '"remote-' + str(len(env[3].calls)) + '"'


def process(env, rid=None):
    env[0].extensions['task_publish'].process(rid or row(env)['id'])


def action(env, name, payload=None):
    return env[1].post('/api/task-publish/publications/' + row(env)['id'] + '/' + name, json=payload or {}, headers=env[2])


def test_preview_is_readonly_idempotent_confirm_and_persistent_restart(env):
    p = env[1].post('/api/task-publish/preview', json={'entityIds': ['local-1'], 'sourceId': 'source-1'}, headers=env[2])
    assert p.status_code == 200 and row(env) is None and not env[3].calls
    rid = queue(env); assert queue(env) == rid
    env[0].extensions['task_publish'] = TaskPublicationQueue(env[0])
    process(env); assert row(env)['status'] == 'published' and env[3].created == 1
    process(env); assert env[3].created == 1 and env[3].patched == 0
    with env[0].extensions['cloud_accounts'].db() as con:
        assert con.execute('SELECT count(*) FROM task_publications').fetchone()[0] == 1
        assert con.execute("SELECT count(*) FROM entities WHERE kind='tasks'").fetchone()[0] == 2
    assert local(env)['data']['owner'] == 'member2' and local(env)['data']['tripId'] == 'trip-1'
    assert 'sync' not in local(env)['data']


def test_lost_create_recovers_no_duplicate_even_after_source_poll(env):
    queue(env); env[3].lose_create = True; process(env)
    assert row(env)['status'] == 'uncertain' and env[3].created == 1
    accounts = env[0].extensions['cloud_accounts']
    with accounts.db() as con:
        src = dict(con.execute("SELECT * FROM cloud_sources WHERE id='source-1'").fetchone())
    provider = accounts.active_provider(accounts.account('account-1'))
    records = provider.snapshot(accounts.adapter_source(src), datetime.now(timezone.utc), datetime.now(timezone.utc))
    accounts.publish(src, accounts.account('account-1'), records)
    process(env)
    assert row(env)['status'] == 'published' and env[3].created == 1
    with accounts.db() as con:
        assert con.execute("SELECT count(*) FROM entities WHERE id LIKE 'cloud-%'").fetchone()[0] == 0


def test_unknown_post_never_blindly_reposts(env):
    queue(env); env[3].lose_create = True; process(env); env[3].hide = True
    for _ in range(14):
        process(env)
    assert row(env)['status'] == 'needs_review' and env[3].created == 1
    assert action(env, 'retry').status_code == 200; process(env)
    assert env[3].created == 1
    env[3].hide = False; process(env)
    assert row(env)['status'] == 'published'


def test_explicit_post_rejection_can_retry_after_permissions_fixed(env):
    queue(env); env[3].reject_post = 403; process(env)
    assert row(env)['status'] == 'permission_denied' and row(env)['attempted'] == 0
    env[3].reject_post = 0; assert action(env, 'retry').status_code == 200; process(env)
    assert row(env)['status'] == 'published' and env[3].created == 1


def test_local_updates_due_clear_done_and_lost_patch_recovery(env):
    queue(env); process(env); change_local(env, title='新标题', due='', done=True)
    env[3].lose_patch = True; process(env); assert row(env)['status'] == 'retry'
    process(env); assert row(env)['status'] == 'published' and env[3].patched == 1
    value = next(iter(env[3].records.values()))
    assert value['title'] == '新标题' and value['status'] == 'completed'
    assert value['dueDateTime' if env[4] == 'microsoft' else 'due'] is None


def test_remote_completion_and_reopen_flow_back_original_entity(env):
    queue(env); process(env); change_remote(env, status='completed'); process(env)
    assert local(env)['data']['done'] is True
    assert local(env)['data']['owner'] == 'member2' and local(env)['data']['journeyId'] == 'journey-1'
    assert local(env)['revision'] == 2 and env[3].patched == 0
    change_remote(env, status='notStarted' if env[4] == 'microsoft' else 'needsAction'); process(env)
    assert local(env)['data']['done'] is False and local(env)['revision'] == 3


@pytest.mark.parametrize('remote_change', ['title', 'due', 'note'])
def test_remote_content_changes_require_comparison(env, remote_change):
    queue(env); process(env)
    if remote_change == 'title': changes = {'title': '云端新标题'}
    elif remote_change == 'due': changes = {'dueDateTime': {'dateTime': '2026-10-05T00:00:00', 'timeZone': 'China Standard Time'}} if env[4] == 'microsoft' else {'due': '2026-10-05T00:00:00Z'}
    else:
        raw = next(iter(env[3].records.values()))
        changes = {'body': {**raw['body'], 'content': '云端备注<br>' + raw['body']['content']}} if env[4] == 'microsoft' else {'notes': '云端备注\n' + raw['notes']}
    change_remote(env, **changes); process(env)
    assert row(env)['status'] == 'conflict' and env[3].patched == 0
    assert action(env, 'retry').status_code == 409
    preview = action(env, 'conflict-preview'); assert preview.status_code == 200, preview.json
    adopted = action(env, 'conflict-confirm', {'previewToken': preview.json['previewToken'], 'resolution': 'remote'})
    assert adopted.status_code == 200, adopted.json
    assert row(env)['status'] == 'published' and local(env)['data']['tripId'] == 'trip-1'
    assert local(env)['data'][remote_change] == preview.json['remote'][remote_change]


def test_dual_change_conflict_and_explicit_local_resolution(env):
    queue(env); process(env); change_local(env, title='本地新标题'); change_remote(env, status='completed'); process(env)
    assert row(env)['status'] == 'conflict' and local(env)['data']['done'] is False
    p = action(env, 'conflict-preview')
    r = action(env, 'conflict-confirm', {'previewToken': p.json['previewToken'], 'resolution': 'local'})
    assert r.status_code == 200; process(env)
    assert row(env)['status'] == 'published' and env[3].patched == 1


def test_remote_changes_after_comparison_and_if_match_race_are_rejected(env):
    queue(env); process(env); change_remote(env, title='第一版'); process(env)
    p = action(env, 'conflict-preview'); change_remote(env, title='第二版')
    assert action(env, 'conflict-confirm', {'previewToken': p.json['previewToken'], 'resolution': 'local'}).status_code == 409
    p = action(env, 'conflict-preview')
    assert action(env, 'conflict-confirm', {'previewToken': p.json['previewToken'], 'resolution': 'local'}).status_code == 200
    env[3].race_patch = True; process(env)
    assert row(env)['status'] == 'conflict' and env[3].patched == 0


def test_pause_resume_still_detects_remote_edit(env):
    queue(env); process(env); assert action(env, 'pause').status_code == 200
    change_local(env, title='本地暂停后变更'); process(env); assert env[3].patched == 0
    change_remote(env, title='云端暂停后变更'); assert action(env, 'resume').status_code == 200
    process(env); assert row(env)['status'] == 'conflict' and env[3].patched == 0


def test_remote_delete_and_local_delete_do_not_delete_other_side(env):
    queue(env); process(env); env[3].records.clear(); process(env)
    assert row(env)['status'] == 'remote_deleted' and local(env)
    assert action(env, 'retry').status_code == 409


def test_local_deletion_is_not_resurrected_by_cloud_poll(env):
    queue(env); process(env)
    accounts = env[0].extensions['cloud_accounts']
    with accounts.db() as con:
        con.execute("DELETE FROM entities WHERE id='local-1'")
        con.execute("UPDATE cloud_sources SET next_attempt=? WHERE id='source-2'", (time.time() + 1000,))
    process(env); assert row(env)['status'] == 'local_deleted' and len(env[3].records) == 1
    assert env[1].get('/api/task-publish/state').json['publications'][0]['status'] == 'local_deleted'
    accounts.tick()
    assert local(env) is None
    with accounts.db() as con:
        assert con.execute("SELECT count(*) FROM entities WHERE id LIKE 'cloud-%'").fetchone()[0] == 0


def test_disconnect_preserves_workflow_task(env):
    queue(env); process(env); env[0].extensions['cloud_accounts'].disconnect('account-1', 'member1')
    assert row(env)['status'] == 'disconnected' and local(env)['data']['tripId'] == 'trip-1'
    assert len(env[3].records) == 1


def test_wrong_member_sources_hidden_but_explicit_primary_available(env):
    client = env[1]; headers = env[2]
    assert [s['id'] for s in client.get('/api/task-publish/state').json['sources']] == ['source-1']
    assert client.post('/api/task-publish/preview', json={'sourceId': 'source-2', 'entityIds': ['local-1']}, headers=headers).status_code == 404
    with env[0].extensions['cloud_accounts'].db() as con:
        con.execute("UPDATE cloud_sources SET is_primary=1 WHERE id='source-2'")
    queue(env, 'source-2'); process(env)
    assert row(env)['status'] == 'published' and row(env)['account_owner'] == 'member2' and row(env)['owner'] == 'member1'
    with env[0].extensions['cloud_accounts'].db() as con:
        con.execute("UPDATE cloud_sources SET is_primary=0 WHERE id='source-2'")
    process(env); assert row(env)['status'] == 'disconnected'


def test_preview_actor_revision_csrf_anonymous_and_tv_boundaries(env):
    client, headers = env[1:3]
    p = client.post('/api/task-publish/preview', json={'sourceId': 'source-1', 'entityIds': ['local-1']}, headers=headers)
    change_local(env, title='预览后变化')
    assert client.post('/api/task-publish/confirm', json={'previewToken': p.json['previewToken']}, headers=headers).status_code == 409
    assert client.post('/api/task-publish/preview', json={'sourceId': 'source-1', 'entityIds': ['local-1']}).status_code == 403
    other = env[0].test_client(); assert other.get('/api/task-publish/state').status_code == 401
    other.post('/api/login', json={'username': 'member2', 'password': 'testing-password-two'})
    h = {'X-CSRF-Token': other.get('/api/me').json['csrf']}
    assert other.post('/api/task-publish/confirm', json={'previewToken': p.json['previewToken']}, headers=h).status_code == 409
    tv = env[0].test_client(); pairing = tv.post('/api/pair/start', json={}).json
    assert client.post('/api/pair/approve', json={'code': pairing['code'], 'name': '合成电视', 'focus': 'member1'}, headers=headers).status_code == 200
    assert tv.post('/api/pair/poll', json={'secret': pairing['secret']}).json['approved']
    assert tv.get('/api/task-publish/state').status_code == 403
    assert tv.post('/api/task-publish/confirm', json={'previewToken': p.json['previewToken']}).status_code == 403
    assert not env[3].created


def test_missing_scope_queue_requires_owner_reauthorization(env):
    accounts = env[0].extensions['cloud_accounts']
    with accounts.db() as con:
        tokens = accounts.decrypt(con.execute("SELECT tokens FROM cloud_accounts WHERE id='account-1'").fetchone()[0]); tokens['scope'] = 'openid'
        con.execute("UPDATE cloud_accounts SET tokens=? WHERE id='account-1'", (accounts.encrypt(tokens),))
    queue(env); process(env)
    assert row(env)['status'] == 'needs_authorization' and not env[3].created


def test_entity_cannot_be_uploaded_to_second_source(env):
    queue(env)
    with env[0].extensions['cloud_accounts'].db() as con:
        con.execute("UPDATE cloud_sources SET is_primary=1 WHERE id='source-2'")
    r = env[1].post('/api/task-publish/preview', json={'sourceId': 'source-2', 'entityIds': ['local-1']}, headers=env[2])
    assert r.status_code == 409


def test_missing_marker_and_missing_etag_pause_without_writes(env):
    queue(env); process(env); env[3].bad_etag = True; process(env)
    assert row(env)['status'] == 'conflict' and env[3].patched == 0


def test_task_scope_only_exact_official_resource():
    assert task_write_allowed('microsoft', 'https://graph.microsoft.com/Tasks.ReadWrite')
    assert task_write_allowed('google', 'https://www.googleapis.com/auth/tasks')
    assert not task_write_allowed('microsoft', 'https://evil.test/Tasks.ReadWrite')
    assert not task_write_allowed('google', 'https://www.googleapis.com/auth/tasks.readonly')


def test_preview_cannot_cross_household_even_if_test_secret_matches(env, tmp_path):
    p = env[1].post('/api/task-publish/preview', json={'sourceId': 'source-1', 'entityIds': ['local-1']}, headers=env[2])
    other = globals()['env'].__wrapped__(tmp_path / 'another-household', SimpleNamespace(param=env[4]))
    r = other[1].post('/api/task-publish/confirm', json={'previewToken': p.json['previewToken']}, headers=other[2])
    assert r.status_code == 400 and row(other) is None and not other[3].calls


def test_incomplete_pagination_never_proves_task_absent_or_creates(env):
    queue(env); original_transport = env[3].transport
    def transport(method, url, token, body=None, headers=None):
        if method == 'GET' and urlsplit(url).path.endswith('/tasks'):
            if env[4] == 'microsoft':
                return {'value': [], '@odata.nextLink': 'https://untrusted.invalid/tasks'}
            return {'items': [], 'nextPageToken': 'repeated-token'}
        return original_transport(method, url, token, body, headers)
    env[0].config['CLOUD_TRANSPORT'] = transport
    process(env)
    assert row(env)['status'] == 'retry' and row(env)['attempted'] == 0 and env[3].created == 0


def test_duplicate_recovery_markers_pause_without_more_posts(env):
    queue(env); env[3].lose_create = True; process(env)
    original = deepcopy(next(iter(env[3].records.values())))
    original['id'] = 'duplicate'; env[3].records['duplicate'] = original
    process(env)
    assert row(env)['status'] == 'conflict' and env[3].created == 1 and env[3].patched == 0


def test_batch_confirm_changed_item_is_atomic(env):
    p = env[1].post('/api/task-publish/preview', json={'sourceId': 'source-1', 'entityIds': ['local-1', 'local-2']}, headers=env[2])
    with env[0].extensions['cloud_accounts'].db() as con:
        con.execute("DELETE FROM entities WHERE id='local-2'")
    r = env[1].post('/api/task-publish/confirm', json={'previewToken': p.json['previewToken']}, headers=env[2])
    assert r.status_code == 409 and row(env) is None and not env[3].calls


def test_late_failure_cannot_resume_paused_publication(env):
    queue(env)
    assert action(env, 'pause').status_code == 200
    env[0].extensions['task_publish'].fail(row(env)['id'], ProviderError('迟到的合成网络错误'))
    assert row(env)['status'] == 'paused'


def reselect(env, remote_id='list-1'):
    accounts = env[0].extensions['cloud_accounts']
    accounts.select_sources('account-1', 'member1', [])
    accounts.select_sources('account-1', 'member1', [{'kind': 'tasks', 'remoteId': remote_id}])
    with accounts.db() as con:
        return con.execute("SELECT id FROM cloud_sources WHERE account_id='account-1'").fetchone()[0]


def test_same_account_list_reconnect_keeps_identity_no_new_cloud_task(env):
    rid = queue(env); process(env); before = row(env)
    sid = reselect(env)
    assert sid != 'source-1' and row(env)['status'] == 'disconnected'
    state = env[1].get('/api/task-publish/state').json
    assert state['publications'][0]['reconnectSourceIds'] == [sid]
    # Polling can precede the explicit reconnection; final recovery removes it.
    accounts = env[0].extensions['cloud_accounts']
    with accounts.db() as con:
        con.execute("UPDATE cloud_sources SET next_attempt=? WHERE id='source-2'", (time.time()+1000,))
    accounts.tick()
    p = env[1].post('/api/task-publish/preview', json={'sourceId': sid, 'entityIds': ['local-1']}, headers=env[2])
    assert p.status_code == 200 and p.json['tasks'][0]['reconnect']
    for _ in range(2):
        r = env[1].post('/api/task-publish/confirm', json={'previewToken': p.json['previewToken']}, headers=env[2])
        assert r.status_code == 200 and r.json['publicationIds'] == [rid]
    process(env)
    assert row(env)['status'] == 'published' and env[3].created == 1
    assert row(env)['remote_id'] == before['remote_id'] and row(env)['attempted'] == before['attempted']
    with accounts.db() as con:
        assert con.execute("SELECT count(*) FROM entities WHERE id LIKE 'cloud-%'").fetchone()[0] == 0


def test_uncertain_create_reconnect_keeps_attempted_and_only_recovers(env):
    rid = queue(env); env[3].lose_create = True; process(env)
    sid = reselect(env); env[3].hide = True
    assert queue(env, sid) == rid and row(env)['attempted'] == 1
    process(env); assert row(env)['status'] == 'uncertain' and env[3].created == 1
    env[3].hide = False; process(env)
    assert row(env)['status'] == 'published' and env[3].created == 1


def test_reconnect_preserves_conflict_and_different_list_rejected(env):
    queue(env); process(env); change_remote(env, title='未解决的云端变更'); process(env)
    assert row(env)['status'] == 'conflict'
    sid = reselect(env)
    assert queue(env, sid) and row(env)['status'] == 'conflict'
    process(env); assert env[3].patched == 0
    with env[0].extensions['cloud_accounts'].db() as con:
        con.execute("UPDATE cloud_sources SET remote_id='different-list' WHERE id=?", (sid,))
        con.execute("UPDATE task_publications SET status='disconnected' WHERE entity_id='local-1'")
    r = env[1].post('/api/task-publish/preview', json={'sourceId': sid, 'entityIds': ['local-1']}, headers=env[2])
    # Same local source ID is not enough; stable remote target must match.
    assert r.status_code == 409


def test_remote_completion_transaction_serializes_concurrent_title_edit(env):
    queue(env); process(env); change_remote(env, status='completed')
    accounts = env[0].extensions['cloud_accounts']; original_db = accounts.db
    worker = []; errors = []; fired = []; waiting = threading.Event()
    def writer():
        try:
            # Entering db now acquires platform authority before its PRAGMA;
            # signal readiness before that real lock can block this writer.
            waiting.set()
            with original_db() as con:
                con.execute("UPDATE entities SET data=json_set(data,'$.title','CONCURRENT_LOCAL_TITLE'),revision=revision+1 WHERE id='local-1'")
        except Exception as error:
            errors.append(str(error))
    class Proxy:
        def __init__(self, con): self.con = con
        def __getattr__(self, key): return getattr(self.con, key)
        def execute(self, sql, args=()):
            cursor = self.con.execute(sql, args)
            if sql == 'SELECT * FROM entities WHERE id=?' and self.con.in_transaction and not fired:
                fired.append(True)
                class Cursor:
                    def fetchone(inner):
                        found = cursor.fetchone()
                        t = threading.Thread(target=writer); worker.append(t); t.start()
                        assert waiting.wait(2)
                        return found
                return Cursor()
            return cursor
    @contextmanager
    def wrapped_db():
        with original_db() as con: yield Proxy(con)
    accounts.db = wrapped_db
    try: process(env)
    finally:
        accounts.db = original_db
        for thread in worker: thread.join(timeout=5)
    assert fired and not errors and not any(t.is_alive() for t in worker)
    assert local(env)['data']['title'] == 'CONCURRENT_LOCAL_TITLE' and local(env)['data']['done'] is True
    assert local(env)['revision'] == 3 and row(env)['status'] == 'published'


def test_old_account_lock_snapshot_cannot_write_after_reconnection(env):
    rid = queue(env); accounts = env[0].extensions['cloud_accounts']; original_lock = accounts.lock
    @contextmanager
    def swapped_lock(account_id):
        with original_lock(account_id):
            with accounts.db() as con:
                con.execute("UPDATE task_publications SET account_id='reconnected-account' WHERE id=?", (rid,))
            yield
    accounts.lock = swapped_lock
    try: process(env)
    finally: accounts.lock = original_lock
    assert not env[3].calls and row(env)['attempted'] == 0
