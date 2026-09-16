"""OAuth results enter the app with fixed status, never provider credentials."""
from urllib.parse import parse_qs, urlsplit

import pytest

from test_frontend_runtime import export


@pytest.mark.parametrize('built', [False, True])
@pytest.mark.parametrize('status', ['connected', 'error', 'photos-connected'])
def test_result_routes_keep_no_provider_parameters(export, built, status):
    client, _, dist = export
    if not built:
        (dist / 'index.html').unlink()
    response = client.get('/', query_string={
        'auth': status, 'reason': 'provider_denied', 'code': 'SYNTHETIC-PRIVATE-CODE',
        'state': 'SYNTHETIC-PRIVATE-STATE', 'error_description': 'PRIVATE-DESCRIPTION',
        'next': 'https://elsewhere.invalid', 'redirect_uri': '//elsewhere.invalid',
    })
    target = urlsplit(response.location)
    assert response.status_code == 302 and not target.netloc
    expected = '/app/photos' if built and status == 'photos-connected' else '/app/connections' if built else '/classic'
    assert target.path == expected
    query = {} if expected == '/app/photos' else {'auth': [status]}
    if status == 'error':
        query['reason'] = ['provider_denied']
    assert parse_qs(target.query) == query
    assert response.headers['Cache-Control'] == 'no-store'
    assert all(value not in response.location for value in ['PRIVATE', 'elsewhere'])


@pytest.mark.parametrize('reason', ['https://private.invalid?token=SECRET', 'SECRET', '__proto__', 'constructor', '', 'x' * 1000])
def test_unknown_reason_is_replaced_instead_of_forwarded(export, reason):
    client, _, _ = export
    response = client.get('/', query_string={'auth': 'error', 'reason': reason})
    assert response.location == '/app/connections?auth=error&reason=provider_error'


@pytest.mark.parametrize('reason', ['not_configured', 'unbound_account', 'invalid_state', 'bind_session_changed', 'session_changed', 'insufficient_permissions'])
def test_actionable_known_error_is_preserved(export, reason):
    client, _, _ = export
    response = client.get('/', query_string={'auth': 'error', 'reason': reason})
    assert parse_qs(urlsplit(response.location).query) == {'auth': ['error'], 'reason': [reason]}


def test_native_connections_deep_link_and_signed_in_keep_working(export):
    client, _, _ = export
    response = client.get('/app/connections')
    assert response.status_code == 200 and response.data == b'<html>Expo synthetic export</html>'
    assert client.get('/?auth=signed-in').location == '/app'
