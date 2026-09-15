"""Exercise real auth/DB/HTTP routes with controlled provider responses."""
import json
import time
from urllib.parse import parse_qs, urlsplit

import pytest

from app import create_app
from cloud_providers import ProviderError


class Remote:
    def __init__(self):
        self.identities = {}
        self.records = {}
        self.fail_snapshot = False
        self.fail_write = False
        self.token_calls = []
        self.next_id = 0

    def tokens(self, provider, params):
        self.token_calls.append((provider, params))
        access = params.get('code') or params['refresh_token'].removeprefix('refresh-')
        return {'access_token': access, 'refresh_token': 'refresh-'+access, 'expires_in': 3600}

    def factory(self, name, token, transport=None):
        remote = self

        class Provider:
            def identity(self):
                return remote.identities[token]

            def list_sources(self):
                return [{'id': 'cal-1', 'kind': 'calendar', 'name': '私人日历', 'writable': False},
                        {'id': 'list-1', 'kind': 'tasks', 'name': '共同待办', 'writable': True},
                        {'id': 'list-2', 'kind': 'tasks', 'name': '可选清单', 'writable': True}]

            def snapshot(self, source, start, end):
                assert 394 <= (end-start).days <= 396
                if remote.fail_snapshot:
                    raise ProviderError('模拟第二页读取失败')
                return json.loads(json.dumps(list(remote.records.get((name, source['id']), {}).values())))

            def write_task(self, source, changes, remote_id=None, version=None):
                if remote.fail_write:
                    raise ProviderError('云端请求超时，结果待核对', 502)
                bucket = remote.records.setdefault((name, source['id']), {})
                if remote_id:
                    record = bucket.get(remote_id)
                    if not record or record['version'] != version:
                        raise ProviderError('远端已修改', 409)
                    record['version'] += 'next'
                    record['data']['done'] = changes['done']
                else:
                    remote.next_id += 1
                    remote_id = 'task-' + str(remote.next_id)
                    record = {'id': remote_id, 'version': 'v1', 'data': {
                        'title': changes['title'], 'done': False, 'note': changes.get('note', ''),
                        'due': changes.get('due', ''), 'owner': 'shared', 'tripId': ''}}
                    bucket[remote_id] = record
                return json.loads(json.dumps(record))

        return Provider()


@pytest.fixture
def configured(tmp_path):
    remote = Remote()
    cfg = {'TESTING': True, 'SECRET_KEY': 'cloud-test-only', 'DATA_DIR': str(tmp_path),
           'SESSION_COOKIE_SECURE': False, 'PUBLIC_ORIGIN': 'http://localhost',
           'MEMBER1_PASSWORD': 'testing-password-one', 'MEMBER2_PASSWORD': 'testing-password-two',
           'MICROSOFT_CLIENT_ID': 'test-ms-client', 'MICROSOFT_CLIENT_SECRET': 'secret-ms',
           'GOOGLE_CLIENT_ID': 'test-google-client', 'GOOGLE_CLIENT_SECRET': 'secret-google',
           'OAUTH_TRANSPORT': remote.tokens, 'CLOUD_PROVIDER_FACTORY': remote.factory}
    return create_app(cfg), remote, cfg


def login(app, number=1):
    client = app.test_client()
    assert client.post('/api/login', json={'username': f'member{number}',
        'password': 'testing-password-' + ('one' if number == 1 else 'two')}).status_code == 200
    return client, {'X-CSRF-Token': client.get('/api/me').json['csrf']}


def begin(client, headers, provider='microsoft'):
    result = client.post('/api/accounts/bind', headers=headers, json={'provider': provider})
    assert result.status_code == 200, result.json
    return parse_qs(urlsplit(result.json['url']).query)


def finish(client, state, provider='microsoft', code='person-a'):
    return client.get(f'/auth/{provider}/callback', query_string={'state': state, 'code': code})


def bind(app, remote, number=1, provider='microsoft', subject=None):
    client, headers = login(app, number)
    code = subject or f'person-{number}-{provider}'
    remote.identities[code] = {'subject': code, 'name': f'Member {number}', 'email': 'same@example.test'}
    params = begin(client, headers, provider)
    result = finish(client, params['state'][0], provider, code)
    assert result.location.endswith('/?auth=connected'), result.location
    account = client.get('/api/accounts').json['accounts'][-1]
    # Caller tests may contain multiple providers/accounts; select by stable name/token.
    engine = app.extensions['cloud_accounts']
    with engine.db() as con:
        aid = con.execute('SELECT id FROM cloud_accounts WHERE subject=?', (code,)).fetchone()[0]
    return client, headers, aid


def select(client, headers, aid, *, tasks=True, calendar=False, primary=True):
    sources = []
    if tasks:
        sources.append({'remoteId': 'list-1', 'kind': 'tasks', 'owner': 'shared', 'primary': primary})
    if calendar:
        sources.append({'remoteId': 'cal-1', 'kind': 'calendar', 'owner': 'member1'})
    response = client.post(f'/api/accounts/{aid}/sources', headers=headers, json={'sources': sources})
    assert response.status_code == 200, response.json
    return client.get('/api/accounts').json['accounts'][0]['sources']


def due(engine):
    with engine.db() as con:
        con.execute('UPDATE cloud_sources SET next_attempt=0')


def test_binding_requires_member_csrf_and_does_not_share_before_selection(configured):
    app, remote, _ = configured
    anon = app.test_client()
    assert anon.get('/api/auth/providers').status_code == 200
    assert anon.get('/api/accounts').status_code == 401
    c, h = login(app)
    assert c.post('/api/accounts/bind', json={'provider': 'google'}).status_code == 403
    assert c.post('/api/accounts/bind', headers={**h, 'Origin': 'https://evil.test'}, json={'provider': 'google'}).status_code == 403
    c, h, aid = bind(app, remote)
    assert c.get('/api/state').json['sync']['selectedSources'] == 0
    discovery = c.get(f'/api/accounts/{aid}/sources').json
    assert len(discovery['sources']) == 3 and discovery['selected'] == []
    state = c.get('/api/state').get_data(as_text=True)
    assert 'same@example.test' not in state and 'person-1-microsoft' not in state


def test_pkce_browser_binding_provider_mixup_expiry_and_replay(configured):
    app, remote, _ = configured
    c, h = login(app)
    params = begin(c, h)
    assert params['code_challenge_method'] == ['S256']
    assert 'offline_access' in params['scope'][0]
    assert params['redirect_uri'] == ['http://localhost/auth/microsoft/callback']
    remote.identities['a'] = {'subject': 'A'}
    outsider = app.test_client()
    assert 'invalid_state' in finish(outsider, params['state'][0], code='a').location
    assert 'invalid_state' in finish(c, params['state'][0], 'google', 'a').location
    assert not remote.token_calls
    result = finish(c, params['state'][0], code='a')
    assert 'auth=connected' in result.location
    assert 'code=' not in result.location and 'state=' not in result.location
    assert result.headers['Cache-Control'] == 'no-store'
    assert result.headers['Referrer-Policy'] == 'no-referrer'
    assert 'invalid_state' in finish(c, params['state'][0], code='a').location
    verifier = remote.token_calls[0][1]['code_verifier']
    assert len(verifier) >= 43
    params = begin(c, h)
    with app.extensions['cloud_accounts'].db() as con:
        con.execute('UPDATE cloud_oauth_states SET expires=0')
    assert 'invalid_state' in finish(c, params['state'][0], code='a').location


def test_binding_session_change_and_unbound_external_login(configured):
    app, remote, _ = configured
    c, h = login(app)
    params = begin(c, h)
    with c.session_transaction() as sess:
        sess['uid'] = 'member2'
    assert 'bind_session_changed' in finish(c, params['state'][0]).location
    assert not remote.token_calls
    c = app.test_client()
    p = parse_qs(urlsplit(c.get('/auth/google/login').location).query)
    assert 'calendar' not in p['scope'][0] and 'tasks' not in p['scope'][0]
    remote.identities['unbound'] = {'subject': 'unbound', 'email': 'same@example.test'}
    assert 'unbound_account' in finish(c, p['state'][0], 'google', 'unbound').location
    assert c.get('/api/state').status_code == 401


def test_subject_bound_login_and_no_email_linking_or_cross_member_rebind(configured):
    app, remote, _ = configured
    a, ah, aid = bind(app, remote, subject='stable-a')
    b, bh = login(app, 2)
    p = begin(b, bh)
    assert 'already_bound' in finish(b, p['state'][0], code='stable-a').location
    assert b.get('/api/accounts').json['accounts'] == []
    remote.identities['other-a'] = {'subject': 'other-a', 'email': 'same@example.test'}
    c = app.test_client()
    p = parse_qs(urlsplit(c.get('/auth/microsoft/login').location).query)
    assert 'unbound_account' in finish(c, p['state'][0], code='other-a').location
    p = parse_qs(urlsplit(c.get('/auth/microsoft/login').location).query)
    assert 'auth=signed-in' in finish(c, p['state'][0], code='stable-a').location
    assert c.get('/api/me').json['user']['id'] == 'member1'
    assert c.get('/api/me').json['csrf']


def test_encrypted_tokens_refresh_restart_and_private_account_access(configured):
    app, remote, cfg = configured
    a, ah, aid = bind(app, remote)
    engine = app.extensions['cloud_accounts']
    with engine.db() as con:
        row = dict(con.execute('SELECT * FROM cloud_accounts').fetchone())
        assert 'refresh-person' not in row['tokens'] and 'access_token' not in row['tokens']
        tokens = engine.decrypt(row['tokens'])
        tokens['expires_at'] = 0
        con.execute('UPDATE cloud_accounts SET tokens=?', (engine.encrypt(tokens),))
    assert a.get(f'/api/accounts/{aid}/sources').status_code == 200
    assert remote.token_calls[-1][1]['grant_type'] == 'refresh_token'
    restarted = create_app(cfg)
    assert len(restarted.extensions['cloud_accounts'].accounts_json('member1')) == 1
    b, bh = login(app, 2)
    assert b.get(f'/api/accounts/{aid}/sources').status_code == 404
    assert b.post(f'/api/accounts/{aid}/sync', headers=bh, json={}).status_code == 404
    assert b.delete(f'/api/accounts/{aid}', headers=bh, json={}).status_code == 404
    assert b.get('/api/accounts').json['accounts'] == []


def test_selection_validation_single_primary_and_google_optional(configured):
    app, remote, _ = configured
    a, ah, aid = bind(app, remote)
    path = f'/api/accounts/{aid}/sources'
    assert a.post(path, headers=ah, json={'sources':[{'kind':'calendar','remoteId':'guess'}]}).status_code == 400
    assert a.post(path, headers=ah, json={'sources':[{'kind':'tasks','remoteId':'list-1','owner':'member1'}]}).status_code == 400
    select(a, ah, aid)
    b, bh, bid = bind(app, remote, 2)
    assert b.post(f'/api/accounts/{bid}/sources', headers=bh, json={'sources':[{'kind':'tasks','remoteId':'list-2','primary':True}]}).status_code == 409
    g, gh, gid = bind(app, remote, 2, 'google')
    assert g.post(f'/api/accounts/{gid}/sources', headers=gh, json={'sources':[{'kind':'tasks','remoteId':'list-1','primary':True}]}).status_code == 409
    assert g.post(f'/api/accounts/{gid}/sources', headers=gh, json={'sources':[{'kind':'tasks','remoteId':'list-1'}]}).status_code == 200
    assert len(a.get('/api/state').json['sync']['taskSources']) == 2
    assert a.post(path, headers=ah, json={'sources':[{'kind':'tasks','remoteId':'list-1','primary':False}]}).status_code == 200
    assert g.post(f'/api/accounts/{gid}/sources', headers=gh, json={'sources':[{'kind':'tasks','remoteId':'list-1','primary':True}]}).status_code == 200


def test_atomic_sync_deletion_failure_and_disconnect_preserve_manual(configured):
    app, remote, _ = configured
    a, ah, aid = bind(app, remote)
    a.post('/api/items/tasks', headers=ah, json={'title':'本地记录','sourceId':''})
    select(a, ah, aid, calendar=True)
    remote.records[('microsoft','list-1')] = {'r':{'id':'r','version':'v1','data':{'title':'云端任务','done':False,'note':'','due':'','tripId':''}}}
    remote.records[('microsoft','cal-1')] = {'e':{'id':'e','version':'v1','data':{'title':'未来日程','start':'2026-10-01T10:00:00+08:00','end':'2026-10-01T11:00:00+08:00','allDay':False,'location':'上海'}}}
    engine = app.extensions['cloud_accounts']
    engine.tick()
    state = a.get('/api/state').json
    assert len(state['tasks']) == 2 and len(state['events']) == 1
    event = state['events'][0]
    assert event['owner'] == 'member1'
    assert a.patch('/api/items/events/'+event['id'], headers=ah, json={'revision':event['revision'],'title':'改'}).status_code == 403
    revision = state['revision']
    remote.fail_snapshot = True
    due(engine)
    engine.tick()
    assert len(a.get('/api/state').json['tasks']) == 2
    assert a.get('/api/state').json['sync']['error']
    assert a.get('/api/state').json['revision'] > revision
    remote.fail_snapshot = False
    remote.records[('microsoft','list-1')] = {}
    due(engine)
    engine.tick()
    assert len(a.get('/api/state').json['tasks']) == 1
    assert not a.get('/api/state').json['sync']['error']
    assert a.delete(f'/api/accounts/{aid}', headers=ah, json={}).status_code == 200
    state = a.get('/api/state').json
    assert len(state['tasks']) == 1 and state['tasks'][0]['title'] == '本地记录'
    assert state['events'] == [] and state['finance']['revision'] == 1


def test_remote_write_ack_conflict_failure_and_local_override(configured):
    app, remote, _ = configured
    a, ah, aid = bind(app, remote)
    select(a, ah, aid)
    response = a.post('/api/items/tasks', headers=ah, json={'title':'写回云端'})
    assert response.status_code == 201
    task = a.get('/api/state').json['tasks'][0]
    assert task['sync']['provider'] == 'microsoft'
    b, bh = login(app, 2)
    path = '/api/items/tasks/' + task['id']
    assert b.patch(path, headers=bh, json={'done':True,'revision':task['revision']}).status_code == 200
    record = remote.records[('microsoft','list-1')][task['sync']['remoteId']]
    assert record['data']['done'] is True
    latest = a.get('/api/state').json['tasks'][0]
    record['version'] = 'changed-elsewhere'
    assert a.patch(path, headers=ah, json={'done':False,'revision':latest['revision']}).status_code == 409
    assert a.delete(path, headers=ah, json={'revision':latest['revision']}).status_code == 403
    assert a.patch(path, headers=ah, json={'title':'更名','revision':latest['revision']}).status_code == 400
    remote.fail_write = True
    assert a.post('/api/items/tasks', headers=ah, json={'title':'失败不虚构成功'}).status_code == 502
    assert len(a.get('/api/state').json['tasks']) == 1
    assert a.post('/api/items/tasks', headers=ah, json={'title':'仍可本地添加','sourceId':''}).status_code == 201


def test_stale_snapshot_after_write_retains_ack_and_os_lock_prevents_overlap(configured):
    app, remote, _ = configured
    a, ah, aid = bind(app, remote)
    select(a, ah, aid)
    a.post('/api/items/tasks', headers=ah, json={'title':'刚写入的任务'})
    remote.records[('microsoft','list-1')] = {}
    engine = app.extensions['cloud_accounts']
    engine.tick()
    assert len(a.get('/api/state').json['tasks']) == 1
    with engine.lock(aid):
        assert a.get(f'/api/accounts/{aid}/sources').status_code == 409
        assert a.delete(f'/api/accounts/{aid}', headers=ah, json={}).status_code == 409
    with engine.db() as con:
        con.execute('UPDATE cloud_writes SET expires=0')
    due(engine)
    engine.tick()
    assert a.get('/api/state').json['tasks'] == []


def test_tv_cannot_discover_or_bind_accounts(configured):
    app, remote, _ = configured
    a, ah, aid = bind(app, remote)
    tv = app.test_client()
    pair = tv.post('/api/pair/start', json={}).json
    assert a.post('/api/pair/approve', headers=ah, json={'code':pair['code'],'name':'TV','focus':'member1'}).status_code == 200
    tv.post('/api/pair/poll', json={'secret':pair['secret']})
    assert tv.get('/api/accounts').status_code == 403
    assert tv.get(f'/api/accounts/{aid}/sources').status_code == 403
    assert tv.post('/api/accounts/bind', headers=ah, json={'provider':'google'}).status_code == 403
    assert tv.get('/api/state').status_code == 200
