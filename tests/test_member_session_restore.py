"""An older backup must not silently revive sessions revoked after that backup."""
from contextlib import closing
from urllib.parse import parse_qs, urlsplit
import socket
import sqlite3

from app import create_app


RECOVERY_SQL = """
BEGIN IMMEDIATE;
UPDATE users SET auth_version = auth_version + 1;
UPDATE member_sessions
  SET revoked_at = CAST(strftime('%s', 'now') AS REAL)
  WHERE revoked_at IS NULL;
UPDATE member_session_browsers SET generation = generation + 1;
DELETE FROM cloud_oauth_states;
COMMIT;
"""


def test_offline_restore_invalidates_old_sessions_and_preserves_connections(tmp_path, monkeypatch):
    def no_network(*_args, **_kwargs):
        raise AssertionError('Restoration checks must not access the network')
    monkeypatch.setattr(socket.socket, 'connect', no_network)
    password = 'synthetic-restore-session-password'
    config = {'TESTING': True, 'DATA_DIR': str(tmp_path / 'data'),
              'SECRET_KEY': 'synthetic-restore-session-key', 'SESSION_COOKIE_SECURE': False,
              'PUBLIC_ORIGIN': 'http://localhost', 'MEMBER1_PASSWORD': password, 'MEMBER2_PASSWORD': password,
              'MICROSOFT_CLIENT_ID': '', 'MICROSOFT_CLIENT_SECRET': '',
              'GOOGLE_CLIENT_ID': 'synthetic-client', 'GOOGLE_CLIENT_SECRET': 'synthetic-secret',
              'OPENAI_API_KEY': '', 'OPENAI_MODEL': ''}
    app = create_app(config)
    database = tmp_path / 'data' / 'household.sqlite3'
    cookie_name = app.config['SESSION_COOKIE_NAME']

    def login(application, member):
        client = application.test_client()
        assert client.get('/api/me').status_code == 200
        assert client.post('/api/login', json={'username': member, 'password': password}).status_code == 200
        return client

    def headers(client):
        return {'X-CSRF-Token': client.get('/api/me').json['csrf'], 'Origin': 'http://localhost'}

    def replay(application, raw):
        client = application.test_client()
        client.set_cookie(cookie_name, raw)
        return client

    clients = [login(app, member) for member in ('member1', 'member2')]
    tv = app.test_client()
    pair = tv.post('/api/pair/start', json={}).json
    assert clients[0].post('/api/pair/approve', json={
        'code': pair['code'], 'name': 'Synthetic screen', 'focus': 'member1'},
        headers=headers(clients[0])).status_code == 200
    assert tv.post('/api/pair/poll', json={'secret': pair['secret']}).json['approved']
    tv_cookie = tv.get_cookie('household_tv').value

    # A provider start stores a real context, but no provider callback is exchanged.
    launch = clients[0].post('/api/accounts/bind', json={'provider': 'google'}, headers=headers(clients[0]))
    assert launch.status_code == 200
    state = parse_qs(urlsplit(launch.json['url']).query)['state'][0]
    cookies = [client.get_cookie(cookie_name).value for client in clients]
    with closing(sqlite3.connect(database)) as con:
        con.execute("INSERT INTO cloud_accounts(id,owner,provider,client_id,subject,name,email,tokens) "
                    "VALUES('synthetic-account','member1','google','synthetic-client','synthetic-subject','Synthetic','','encrypted-fixture-only')")
        con.execute("INSERT INTO cloud_sources(id,account_id,remote_id,kind,name,owner) "
                    "VALUES('synthetic-source','synthetic-account','synthetic-calendar','calendar','Synthetic','member1')")
        con.commit()
        protected = {name: con.execute('SELECT * FROM ' + name).fetchall()
                     for name in ('cloud_accounts', 'cloud_sources', 'devices')}
        versions = dict(con.execute('SELECT id,auth_version FROM users'))
        assert con.execute('SELECT count(*) FROM cloud_oauth_states').fetchone()[0] == 1
        snapshot = tmp_path / 'snapshot.sqlite3'
        with closing(sqlite3.connect(snapshot)) as destination:
            con.backup(destination)

    for client, raw in zip(clients, cookies):
        assert client.post('/api/logout', json={}, headers=headers(client)).status_code == 200
        assert replay(app, raw).get('/api/finance-baseline/private').status_code == 401

    # No server is running: restore the exact older SQLite snapshot offline.
    with closing(sqlite3.connect(snapshot)) as source, closing(sqlite3.connect(database)) as destination:
        source.backup(destination)
    restored = create_app(config)
    assert all(replay(restored, raw).get('/api/finance-baseline/private').status_code == 200 for raw in cookies)

    # This is the documented offline invalidation transaction, not an HTTP endpoint.
    with closing(sqlite3.connect(database)) as con:
        con.executescript(RECOVERY_SQL)
        assert dict(con.execute('SELECT id,auth_version FROM users')) == {k: v + 1 for k, v in versions.items()}
        assert con.execute('SELECT count(*) FROM member_sessions WHERE revoked_at IS NULL').fetchone()[0] == 0
        assert con.execute('SELECT count(*) FROM cloud_oauth_states').fetchone()[0] == 0
        assert con.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
        assert not con.execute('PRAGMA foreign_key_check').fetchall()
        assert protected == {name: con.execute('SELECT * FROM ' + name).fetchall() for name in protected}

    ready = create_app(config)
    assert all(replay(ready, raw).get('/api/finance-baseline/private').status_code == 401 for raw in cookies)
    rejected = replay(ready, cookies[0]).get('/auth/google/callback', query_string={'state': state, 'code': 'synthetic'})
    assert rejected.status_code == 302 and 'auth=error&reason=invalid_state' in rejected.location
    screen = ready.test_client()
    screen.set_cookie('household_tv', tv_cookie)
    assert screen.get('/api/state').status_code == 200
    assert screen.get('/api/finance-baseline/private').status_code == 403
    assert screen.get('/api/sessions').status_code == 403
    for member in ('member1', 'member2'):
        assert login(ready, member).get('/api/finance-baseline/private').status_code == 200
