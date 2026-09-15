"""New authentication storage must stay out of personal business-data exports."""
from contextlib import closing
from io import BytesIO
import json
import re
import socket
import sqlite3
from zipfile import ZipFile

import pytest

from app import create_app


@pytest.mark.parametrize('include_shared', [False, True])
def test_session_credentials_and_registry_are_not_exported(tmp_path, monkeypatch, include_shared):
    def deny_network(*_args, **_kwargs):
        raise AssertionError('Network is forbidden in session export checks')

    monkeypatch.setattr(socket.socket, 'connect', deny_network)
    password = 'synthetic-session-export-password'
    application = create_app({
        'TESTING': True, 'SECRET_KEY': 'synthetic-session-export-key',
        'DATA_DIR': str(tmp_path), 'MEMBER1_PASSWORD': password, 'MEMBER2_PASSWORD': password,
        'SESSION_COOKIE_SECURE': False, 'PUBLIC_ORIGIN': 'https://home.example.test',
        'MICROSOFT_CLIENT_ID': '', 'MICROSOFT_CLIENT_SECRET': '',
        'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': '', 'OPENAI_API_KEY': '', 'OPENAI_MODEL': '',
    })
    clients, credentials = [], set()
    for member in ('member1', 'member2'):
        client = application.test_client()
        assert client.get('/api/me').status_code == 200
        assert client.post('/api/login', json={'username': member, 'password': password}).status_code == 200
        credentials.add(client.get_cookie(application.config['SESSION_COOKIE_NAME']).value)
        credentials.add(client.get('/api/me').json['csrf'])
        clients.append(client)

    with closing(sqlite3.connect(tmp_path / 'household.sqlite3')) as con:
        session_tables = [row[0] for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'member_session%'")]
        assert set(session_tables) == {'member_sessions', 'member_session_browsers'}
        for table in session_tables:
            columns = [r[1] for r in con.execute(f'PRAGMA table_info({table})')]
            rows = con.execute(f'SELECT * FROM {table}').fetchall()
            assert rows, 'The check must exercise populated session storage'
            for row in rows:
                for name, value in zip(columns, row):
                    if ('hash' in name or 'digest' in name) and isinstance(value, str):
                        assert re.fullmatch('[a-f0-9]{64}', value)
                        credentials.add(value)
    assert len(credentials) >= 8, 'Cookie, CSRF and both members\' stored hashes must be checked'

    client = clients[0]
    me = client.get('/api/me').json
    response = client.post('/api/portability/export', json={'includeShared': include_shared},
                           headers={'X-CSRF-Token': me['csrf']})
    assert response.status_code == 200 and response.mimetype == 'application/zip'
    with ZipFile(BytesIO(response.data)) as archive:
        assert archive.testzip() is None
        contents = [archive.read(name) for name in archive.namelist()]
        exported = json.loads(archive.read('data.json'))
    assert exported['member']['id'] == 'member1'
    assert ('shared' in exported) is include_shared
    for secret in credentials:
        assert all(secret.encode() not in content for content in contents)
    for name in session_tables:
        assert all(name.encode() not in content for content in contents)
    assert not any('session' in name.lower() for name in exported['personal'])
