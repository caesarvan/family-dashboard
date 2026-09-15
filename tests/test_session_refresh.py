"""Real session cookies and delayed HTTP responses; synthetic local data only.

The forced-refresh control verifies that stale cookies lose server authority.
It may discard a newer login in the browser, but cannot revive a revoked member.
Mutation races beyond the dedicated member-session suite are not generalized.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, closing
from datetime import datetime, timezone, timedelta
from http.cookiejar import CookieJar
from http.cookies import SimpleCookie
import json
from pathlib import Path
import socket
import sqlite3
import threading
import time
from urllib.error import HTTPError
from urllib.request import build_opener, HTTPCookieProcessor, Request

import pytest
from itsdangerous.timed import TimestampSigner
from werkzeug.http import parse_date
from werkzeug.serving import make_server, WSGIRequestHandler

from app import create_app


PASSWORD = 'Synthetic-session-password-42'


@pytest.fixture
def application(tmp_path, monkeypatch):
    original_connect = socket.socket.connect

    def local_only(sock, address):
        if not isinstance(address, tuple) or address[0] not in {'127.0.0.1', '::1'}:
            raise AssertionError('External network forbidden in session tests')
        return original_connect(sock, address)

    monkeypatch.setattr(socket.socket, 'connect', local_only)
    return create_app({'TESTING': True, 'DATA_DIR': str(tmp_path / 'data'),
                       'SECRET_KEY': 'synthetic-session-key-not-for-production',
                       'MEMBER1_PASSWORD': PASSWORD, 'MEMBER2_PASSWORD': PASSWORD,
                       'SESSION_COOKIE_SECURE': False,
                       'PUBLIC_ORIGIN': 'https://home.example.test',
                       'MICROSOFT_CLIENT_ID': '', 'MICROSOFT_CLIENT_SECRET': '',
                       'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': '',
                       'OPENAI_API_KEY': '', 'OPENAI_MODEL': ''})


def login(client, member='member1'):
    result = client.post('/api/login', json={'username': member, 'password': PASSWORD})
    assert result.status_code == 200
    return result


def member_headers(client):
    return {'X-CSRF-Token': client.get('/api/me').json['csrf']}


def session_cookies(response):
    return [value for value in response.headers.getlist('Set-Cookie')
            if value.startswith('session=')]


def plan_payload():
    return {'plan': {'title': 'Synthetic journey', 'start': '2026-12-03',
                    'end': '2026-12-05', 'international': False,
                    'memberIds': ['member1', 'member2'], 'budget': 0,
                    'destinations': [{'key': 'city', 'country': '示例国家',
                                      'city': '示例城市', 'arrival': '2026-12-03',
                                      'departure': '2026-12-05'}]}}


class QuietHandler(WSGIRequestHandler):
    def log(self, *args, **kwargs):
        pass


@contextmanager
def delayed_server(application):
    """Hold a fully generated response, including real Flask Set-Cookie.

    New logins can finish on another server thread before the old response
    reaches the same browser-like CookieJar. No response header is fabricated.
    """
    ready, release = threading.Event(), threading.Event()
    captured = {}

    def wrapper(environ, start_response):
        if environ.get('HTTP_X_SYNTHETIC_DELAY') != '1':
            return application(environ, start_response)
        headers = []

        def capture(status, values, exc_info=None):
            captured['status'], captured['headers'] = status, values
            headers[:] = [status, values, exc_info]

        response = application(environ, capture)
        try:
            output = list(response)
        finally:
            if hasattr(response, 'close'):
                response.close()
        ready.set()
        if not release.wait(8):
            raise AssertionError('Synthetic delayed response was not released')
        start_response(*headers)
        return output

    server = make_server('127.0.0.1', 0, wrapper, threaded=True, request_handler=QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))
    origin = f'http://127.0.0.1:{server.server_port}'

    def request(path, payload=None, headers=None):
        data = json.dumps(payload).encode() if payload is not None else None
        outgoing = {'Content-Type': 'application/json', **(headers or {})}
        call = Request(origin + path, data=data, headers=outgoing)
        try:
            result = opener.open(call, timeout=10)
        except HTTPError as error:
            result = error
        with result:
            return result.status, json.loads(result.read())

    try:
        yield request, ready, release, captured
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.mark.parametrize('path', ['/api/me', '/api/journeys/preview'])
@pytest.mark.parametrize('next_action', ['member2', 'logout'])
@pytest.mark.parametrize('legacy_refresh', [False, True], ids=['fixed-default', 'forced-refresh-revoked-cookie'])
def test_late_http_read_cannot_replace_new_login_or_logout(application, path, next_action, legacy_refresh):
    assert application.config['SESSION_REFRESH_EACH_REQUEST'] is False
    if legacy_refresh:
        application.config['SESSION_REFRESH_EACH_REQUEST'] = True
    with delayed_server(application) as (request, ready, release, captured):
        assert request('/api/login', {'username': 'member1', 'password': PASSWORD})[0] == 200
        csrf = request('/api/me')[1]['csrf']
        headers = {'X-CSRF-Token': csrf, 'X-Synthetic-Delay': '1'}
        with ThreadPoolExecutor(max_workers=1) as pool:
            late = pool.submit(request, path, plan_payload() if path.endswith('/preview') else None, headers)
            try:
                assert ready.wait(5), 'Old member response was not generated'
                if next_action == 'logout':
                    assert request('/api/logout', {}, {'X-CSRF-Token': csrf})[0] == 200
                    expected = None
                else:
                    assert request('/api/login', {'username': next_action, 'password': PASSWORD})[0] == 200
                    expected = next_action
                actor = request('/api/me')[1]['user']
                assert (actor['id'] if actor else None) == expected
                release.set()
                assert late.result(timeout=5)[0] == 200
                actor = request('/api/me')[1]['user']
                actual = actor['id'] if actor else None
                assert actual == (None if legacy_refresh else expected)
                cookie_sent = any(k.lower() == 'set-cookie' and v.startswith('session=')
                                  for k, v in captured['headers'])
                assert cookie_sent is legacy_refresh
            finally:
                release.set()


@pytest.mark.parametrize('path', ['/api/me', '/api/state', '/api/journeys/templates',
                                  '/api/finance-baseline/private', '/api/accounts'])
def test_member_reads_do_not_refresh_or_change_cookie(application, path):
    client = application.test_client()
    login(client)
    original = client.get_cookie('session').value
    response = client.get(path)
    assert response.status_code == 200
    assert not session_cookies(response)
    assert client.get_cookie('session').value == original


def test_preview_success_validation_error_and_csrf_failure_do_not_refresh(application):
    client = application.test_client()
    login(client)
    for payload, headers, status in [(plan_payload(), member_headers(client), 200),
                                      ({'plan': {}}, member_headers(client), 400),
                                      (plan_payload(), {'X-CSRF-Token': 'invalid'}, 403)]:
        result = client.post('/api/journeys/preview', json=payload, headers=headers)
        assert result.status_code == status
        assert not session_cookies(result)
    with closing(sqlite3.connect(Path(application.config['DATA_DIR']) / 'household.sqlite3')) as con:
        assert con.execute('SELECT count(*) FROM entities').fetchone()[0] == 0
        assert con.execute('SELECT count(*) FROM journey_workflows').fetchone()[0] == 0


def test_login_sets_secure_permanent_cookie_and_rotates_identity_and_csrf(application):
    application.config['SESSION_COOKIE_SECURE'] = True
    client = application.test_client()
    result = login(client)
    parsed = SimpleCookie()
    parsed.load(session_cookies(result)[0])
    cookie = parsed['session']
    assert cookie['httponly'] and cookie['secure'] and cookie['samesite'] == 'Lax'
    assert cookie['path'] == '/'
    remaining = parse_date(cookie['expires']) - datetime.now(timezone.utc)
    assert timedelta(days=30) - timedelta(seconds=5) < remaining <= timedelta(days=30)
    first = client.get('/api/me').json
    assert first['user']['id'] == 'member1'
    old_cookie = client.get_cookie('session').value
    result = login(client, 'member2')
    assert session_cookies(result)
    second = client.get('/api/me').json
    assert second['user']['id'] == 'member2' and second['csrf'] != first['csrf']
    assert client.get_cookie('session').value != old_cookie
    denied = client.post('/api/profile', json={'name': 'Synthetic'}, headers={'X-CSRF-Token': first['csrf']})
    assert denied.status_code == 403 and not session_cookies(denied)


def test_logout_deletes_session_and_failed_login_does_not_replace_it(application):
    client = application.test_client()
    login(client)
    result = client.post('/api/login', json={'username': 'member2', 'password': 'incorrect'})
    assert result.status_code == 401 and not session_cookies(result)
    assert client.get('/api/me').json['user']['id'] == 'member1'
    result = client.post('/api/logout', json={}, headers=member_headers(client))
    assert result.status_code == 200 and session_cookies(result)
    with client.session_transaction() as anonymous:
        assert set(anonymous) == {'browser_id', '_permanent'}
    assert client.get_cookie('session') is not None  # anonymous browser identity only
    assert client.get('/api/me').json == {'user': None, 'csrf': None}
    assert client.get('/api/state').status_code == 401


def test_read_activity_does_not_extend_30_day_signature_lifetime(application, monkeypatch):
    clock = [int(time.time())]
    monkeypatch.setattr(TimestampSigner, 'get_timestamp', lambda self: clock[0])
    client = application.test_client()
    login(client)
    original = client.get_cookie('session').value
    clock[0] += 29 * 86400
    response = client.get('/api/state')
    assert response.status_code == 200 and not session_cookies(response)
    assert client.get_cookie('session').value == original
    clock[0] += 2 * 86400
    response = client.get('/api/state')
    assert response.status_code == 401 and not session_cookies(response)
    assert client.get('/api/me').json == {'user': None, 'csrf': None}


def test_password_change_still_sets_session_and_revokes_old_auth_version(application):
    client = application.test_client()
    login(client)
    original_cookie = client.get_cookie('session').value
    original_actor = client.get('/api/me').json['user']
    response = client.post('/api/profile', json={'name': 'Synthetic updated',
                           'currentPassword': PASSWORD, 'password': PASSWORD + '-new'},
                           headers=member_headers(client))
    assert response.status_code == 200 and session_cookies(response)
    assert client.get('/api/me').json['user']['auth_version'] == original_actor['auth_version'] + 1
    old_client = application.test_client()
    old_client.set_cookie('session', original_cookie)
    denied = old_client.get('/api/state')
    assert denied.status_code == 401 and not session_cookies(denied)
    assert old_client.get('/api/me').json['user'] is None


def test_genuine_session_write_starts_a_new_30_day_signature_window(application, monkeypatch):
    clock = [int(time.time())]
    monkeypatch.setattr(TimestampSigner, 'get_timestamp', lambda self: clock[0])
    client = application.test_client()
    login(client)
    first_cookie = client.get_cookie('session').value
    clock[0] += 29 * 86400
    response = client.post('/api/profile', json={'name': 'Synthetic updated',
                           'currentPassword': PASSWORD, 'password': PASSWORD + '-new'},
                           headers=member_headers(client))
    assert response.status_code == 200 and session_cookies(response)
    renewed_cookie = client.get_cookie('session').value
    assert renewed_cookie != first_cookie
    clock[0] += 2 * 86400
    response = client.get('/api/state')
    assert response.status_code == 200 and not session_cookies(response)
    assert client.get_cookie('session').value == renewed_cookie
    clock[0] += 29 * 86400
    response = client.get('/api/state')
    assert response.status_code == 401 and not session_cookies(response)


def test_display_name_only_update_does_not_refresh_cookie(application):
    client = application.test_client()
    login(client)
    response = client.post('/api/profile', json={'name': 'Synthetic renamed'}, headers=member_headers(client))
    assert response.status_code == 200 and not session_cookies(response)
    assert client.get('/api/me').json['user']['name'] == 'Synthetic renamed'


def test_invalid_signature_is_rejected_without_replacement_cookie(application):
    client = application.test_client()
    login(client)
    client.set_cookie('session', client.get_cookie('session').value + '-tampered')
    result = client.get('/api/state')
    assert result.status_code == 401 and not session_cookies(result)
    assert client.get('/api/me').json['user'] is None


def test_oauth_start_nonce_is_still_saved_but_reused_nonce_does_not_refresh(application):
    application.config.update(GOOGLE_CLIENT_ID='synthetic-client', GOOGLE_CLIENT_SECRET='synthetic-secret')
    client = application.test_client()
    assert client.post('/api/login', json={'username': 'member1', 'password': PASSWORD},
                       base_url='https://home.example.test').status_code == 200
    headers = {'X-CSRF-Token': client.get('/api/me', base_url='https://home.example.test').json['csrf']}
    first = client.post('/api/accounts/bind', json={'provider': 'google'}, headers=headers,
                        base_url='https://home.example.test')
    assert first.status_code == 200 and session_cookies(first)
    second = client.post('/api/accounts/bind', json={'provider': 'google'}, headers=headers,
                         base_url='https://home.example.test')
    assert second.status_code == 200 and not session_cookies(second)
    # Only local authorization URLs and state records; no OAuth navigation/callback.
    assert first.json['url'] != second.json['url']


def test_new_households_receive_safe_default_and_routing_still_clears_login(application):
    platform = application.extensions['household_platform']
    household = {'id': 'a' * 24, 'slug': 'synthetic', 'name': 'Synthetic household'}
    child = platform.child(household, {'MEMBER1_PASSWORD': PASSWORD, 'MEMBER2_PASSWORD': PASSWORD})
    assert child.config['SESSION_REFRESH_EACH_REQUEST'] is False
    client = application.test_client()
    login(client)
    response = client.get('/space/home')
    assert response.status_code == 303
    assert 'Max-Age=0' in session_cookies(response)[0]
    assert client.get('/api/me').json['user'] is None
