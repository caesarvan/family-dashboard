"""A real second SQLite connection revokes auth after the HTTP guard ran."""
import sqlite3

from itsdangerous import URLSafeTimedSerializer
import pytest

from test_app import app, member
from test_journey_workflows import apply, connection, plan, preview


def business_snapshot(application):
    with connection(application) as con:
        return {table: sorted(tuple(row) for row in con.execute(f'SELECT * FROM {table}'))
                for table in ('entities', 'journey_workflows', 'journey_links', 'journey_actions', 'audit')}


@pytest.mark.parametrize('operation', ['create', 'update', 'replay'])
@pytest.mark.parametrize('revocation', ['session', 'auth_version'])
def test_revoked_during_preview_decode_cannot_write_or_replay(app, monkeypatch, operation, revocation):
    client, headers = member(app)
    value = preview(client, headers)
    if operation != 'create':
        saved = apply(client, headers, value)
        assert saved.status_code == 201
        if operation == 'update':
            value = preview(client, headers, plan(title='不能保存的新标题'),
                            journeyId=saved.json['id'], revision=saved.json['revision'])
    before = business_snapshot(app)
    token = value['previewToken']
    original = URLSafeTimedSerializer.loads
    revoked = []

    def decode_then_revoke(serializer, candidate, *args, **kwargs):
        result = original(serializer, candidate, *args, **kwargs)
        if candidate == token and not revoked:
            with sqlite3.connect(app.config['DATA_DIR'] + '/household.sqlite3') as other:
                if revocation == 'session':
                    changed = other.execute("UPDATE member_sessions SET revoked_at=1 WHERE owner='member1' AND revoked_at IS NULL")
                else:
                    changed = other.execute("UPDATE users SET auth_version=auth_version+1 WHERE id='member1'")
                assert changed.rowcount > 0
            revoked.append(True)
        return result

    monkeypatch.setattr(URLSafeTimedSerializer, 'loads', decode_then_revoke)
    response = apply(client, headers, value, key='update-key-123' if operation == 'update' else 'journey-key-123')
    assert revoked == [True]
    assert response.status_code == 401, response.json
    assert business_snapshot(app) == before
    assert client.get('/api/me').json['user'] is None
