"""Synthetic static exports plus the real Flask member/CSRF/CRUD boundary."""
import importlib
import os
from pathlib import Path

from flask import Flask
import pytest

from frontend_runtime import register_frontend_runtime


@pytest.fixture
def export(tmp_path):
    static = tmp_path / 'static'
    static.mkdir()
    (static / 'index.html').write_text('<html>classic fixture</html>', encoding='utf-8')
    dist = static / 'experience'
    dist.mkdir()
    (dist / 'index.html').write_text('<html>Expo synthetic export</html>', encoding='utf-8')
    (dist / '_expo' / 'static' / 'js' / 'web').mkdir(parents=True)
    (dist / '_expo' / 'static' / 'js' / 'web' / 'entry-123.js').write_text('window.synthetic = true;', encoding='utf-8')
    (dist / 'assets').mkdir()
    (dist / 'assets' / 'font.woff2').write_bytes(b'synthetic-font')
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.add_url_rule('/', 'index', register_frontend_runtime(app, static))
    return app.test_client(), static, dist


@pytest.mark.parametrize('url', ['/app', '/app/', '/app/index.html', '/app/tasks', '/app/settings/account'])
def test_spa_entry_and_deep_links(export, url):
    client, _, _ = export
    response = client.get(url, follow_redirects=True)
    assert response.status_code == 200
    assert response.data == b'<html>Expo synthetic export</html>'
    assert response.mimetype == 'text/html'
    assert response.headers['Cache-Control'] == 'no-store'


def test_only_completed_export_switches_home_and_classic_remains(export):
    client, _, dist = export
    response = client.get('/')
    assert response.status_code == 302 and response.location == '/app'
    assert b'classic fixture' in client.get('/classic').data
    (dist / 'index.html').unlink()
    assert client.get('/').status_code == 200
    assert b'classic fixture' in client.get('/').data
    assert client.get('/app').status_code == 404
    assert client.get('/app/tasks').status_code == 404


@pytest.mark.parametrize('name,mimetype,content', [
    ('_expo/static/js/web/entry-123.js', 'text/javascript', b'window.synthetic = true;'),
    ('assets/font.woff2', 'font/woff2', b'synthetic-font'),
])
def test_exact_export_bytes_and_mime(export, name, mimetype, content):
    client, _, _ = export
    response = client.get('/app/' + name)
    assert response.status_code == 200
    assert response.mimetype == mimetype and response.data == content
    assert response.headers['Cache-Control'] == 'no-store'


@pytest.mark.parametrize('name', [
    '_expo/static/js/web/missing.js', 'missing.css', 'assets/missing', '_expo/missing',
    '.env', 'config.json', 'entry.js.map', 'secret.py', 'extra.html',
    '../index.html', '%2e%2e/index.html', '%252e%252e/index.html',
    '..%5cindex.html', 'C:%5cWindows%5cwin.ini', 'assets/../index.html',
    'assets/.private.js', 'assets/trailing./file.js', 'assets/trailing%20/file.js',
])
def test_unsafe_or_missing_asset_is_not_html_fallback(export, name):
    client, _, dist = export
    for filename in ('config.json', 'entry.js.map', 'secret.py', 'extra.html', '.env'):
        (dist / filename).write_text('PRIVATE FIXTURE', encoding='utf-8')
    response = client.get('/app/' + name)
    assert response.status_code == 404
    assert b'PRIVATE FIXTURE' not in response.data
    assert b'Expo synthetic export' not in response.data


@pytest.mark.parametrize('directory', [False, True])
def test_external_symlink_is_rejected(export, tmp_path, directory):
    client, _, dist = export
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'secret.js').write_text('PRIVATE FIXTURE', encoding='utf-8')
    if directory:
        (dist / 'linked').symlink_to(outside, target_is_directory=True)
        url = '/app/linked/secret.js'
    else:
        (dist / 'linked.js').symlink_to(outside / 'secret.js')
        url = '/app/linked.js'
    response = client.get(url)
    assert response.status_code == 404 and b'PRIVATE FIXTURE' not in response.data


def test_export_root_symlink_cannot_replace_bundle(export, tmp_path):
    client, static, dist = export
    moved = tmp_path / 'moved-export'
    dist.rename(moved)
    (static / 'experience').symlink_to(moved, target_is_directory=True)
    assert client.get('/app').status_code == 404
    assert client.get('/').status_code == 404


@pytest.mark.skipif(os.name != 'nt', reason='Windows junction semantics')
def test_windows_junction_rejected(export, tmp_path):
    import _winapi
    client, _, dist = export
    outside = tmp_path / 'junction-target'
    outside.mkdir()
    (outside / 'secret.js').write_text('PRIVATE FIXTURE', encoding='utf-8')
    _winapi.CreateJunction(str(outside), str(dist / 'linked'))
    response = client.get('/app/linked/secret.js')
    assert response.status_code == 404 and b'PRIVATE FIXTURE' not in response.data


@pytest.fixture(scope='module')
def real_app(tmp_path_factory):
    source = importlib.import_module('app')
    root = tmp_path_factory.mktemp('expo-real-app')
    static = root / 'static'
    (static / 'experience').mkdir(parents=True)
    (static / 'index.html').write_text('<html>classic real factory fixture</html>', encoding='utf-8')
    (static / 'experience' / 'index.html').write_text('<html>Expo real factory fixture</html>', encoding='utf-8')
    (static / 'experience' / 'secret.json').write_text('PRIVATE FIXTURE', encoding='utf-8')
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(source, 'ROOT', root)
        for key in ('GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET', 'MICROSOFT_CLIENT_ID',
                    'MICROSOFT_CLIENT_SECRET', 'NVIDIA_API_KEY', 'OPENAI_API_KEY'):
            monkeypatch.setenv(key, '')
        app = source.create_app({
            'TESTING': True, 'SECRET_KEY': 'expo-synthetic-only-secret',
            'DATA_DIR': str(root / 'data'), 'SESSION_COOKIE_SECURE': False,
            'MEMBER1_PASSWORD': 'testing-password-one',
            'MEMBER2_PASSWORD': 'testing-password-two', 'ASSISTANT_PROVIDER': 'local',
        })
        yield app


def test_real_factory_csp_legacy_routes_and_no_static_bypass(real_app):
    client = real_app.test_client()
    assert client.get('/').location == '/app'
    response = client.get('/app')
    assert response.status_code == 200
    assert "script-src 'self'" in response.headers['Content-Security-Policy']
    assert "connect-src 'self'" in response.headers['Content-Security-Policy']
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    for url in ('/classic', '/tv', '/demo'):
        assert client.get(url).data == b'<html>classic real factory fixture</html>'
    for name in ('experience/secret.json', './experience/secret.json', 'EXPERIENCE/secret.json',
                 'experience./secret.json', 'experience%5csecret.json'):
        assert client.get('/static/' + name).status_code == 404


def test_real_auth_csrf_local_crud_and_conflict_are_unchanged(real_app):
    client = real_app.test_client()
    assert client.get('/api/state').status_code == 401
    assert client.get('/api/me').json == {'user': None, 'csrf': None}
    assert client.post('/api/login', json={'username': 'member1', 'password': 'testing-password-one'}).status_code == 200
    me = client.get('/api/me').json
    headers = {'X-CSRF-Token': me['csrf'], 'Origin': 'http://localhost'}
    payload = {'title': 'Expo synthetic task', 'sourceId': ''}
    assert client.post('/api/items/tasks', json=payload).status_code == 403
    assert client.post('/api/items/tasks', json=payload, headers={**headers, 'Origin': 'https://other.invalid'}).status_code == 403
    assert client.post('/api/items/tasks', data='{}', headers=headers).status_code == 415
    created = client.post('/api/items/tasks', json=payload, headers=headers)
    assert created.status_code == 201
    entity = created.json
    path = '/api/items/tasks/' + entity['id']
    assert client.patch(path, json={'revision': entity['revision'], 'done': True}, headers=headers).status_code == 200
    assert client.patch(path, json={'revision': entity['revision'], 'done': False}, headers=headers).status_code == 409
    current = next(v for v in client.get('/api/state').json['tasks'] if v['id'] == entity['id'])
    assert current['done'] is True and current['revision'] == 2
    assert client.delete(path, json={'revision': current['revision']}, headers=headers).status_code == 200
    assert client.post('/api/logout', json={}, headers=headers).status_code == 200
    assert client.get('/api/state').status_code == 401


def test_frontend_routes_do_not_accept_write_requests(real_app):
    client = real_app.test_client()
    for url in ('/app', '/app/tasks', '/classic'):
        assert client.post(url, json={}).status_code == 405
