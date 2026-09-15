"""Microsoft callback compatibility using opaque tokens and real household routes."""
from urllib.parse import parse_qs, quote, urlsplit

import pytest

from cloud_providers import CloudProvider
from test_cloud_accounts import begin, configured, finish, login


GRAPH = 'https://graph.microsoft.com/'
REQUIRED = ['User.Read', 'Calendars.Read', 'Calendars.Read.Shared', 'Tasks.ReadWrite']
BARE = 'openid profile email ' + ' '.join(REQUIRED)
FULL = 'openid profile email ' + ' '.join(GRAPH + scope for scope in REQUIRED)
ABSENT = object()


def bind_with_response(configured, scope=ABSENT, *, refresh=True):
    app, remote, _ = configured

    def response(provider, params):
        tokens = remote.tokens(provider, params)
        if scope is not ABSENT:
            tokens['scope'] = scope
        if not refresh:
            tokens.pop('refresh_token', None)
        return tokens

    app.config['OAUTH_TRANSPORT'] = response
    remote.identities['person-a'] = {'subject': 'stable-ms-subject', 'name': 'Member'}
    client, headers = login(app)
    params = begin(client, headers)
    result = finish(client, params['state'][0])
    return client, headers, result


@pytest.mark.parametrize('scope', [
    BARE,
    FULL,
    BARE.swapcase(),
    FULL.upper(),
    'openid profile email ' + ' '.join(quote(GRAPH + s, safe='') for s in REQUIRED),
    quote(FULL, safe=''),  # Microsoft documents URL-encoded response scopes.
    'openid profile email User.Read Calendars.Read.Shared Tasks.ReadWrite',
    'openid profile email User.Read Calendars.Read Tasks.ReadWrite',  # Observed personal-account grant.
    ABSENT,  # Omitted scope means the scopes requested at authorization.
], ids=['bare', 'graph-url', 'bare-case', 'url-case', 'encoded-items',
        'encoded-whole', 'shared-includes-own-calendar', 'personal-account-grant', 'omitted-scope'])
def test_microsoft_granted_scope_forms_bind(configured, scope):
    client, _, result = bind_with_response(configured, scope)
    assert result.location.endswith('/?auth=connected'), result.location
    accounts = client.get('/api/accounts').json['accounts']
    assert len(accounts) == 1
    assert accounts[0]['provider'] == 'microsoft'
    # offline_access does not need to be echoed in the access-token scope.
    assert scope is ABSENT or 'offline_access' not in scope


@pytest.mark.parametrize('scope', [
    'openid profile email User.Read Calendars.Read Calendars.Read.Shared',
    'openid profile email User.Read Tasks.ReadWrite',
    'openid profile email Calendars.Read.Shared Tasks.ReadWrite',
    'openid profile email ' + ' '.join('https://evil.example/' + s for s in REQUIRED),
    'openid profile email ' + ' '.join('https://graph.microsoft.com.evil.example/' + s for s in REQUIRED),
    'openid profile email ' + ' '.join('http://graph.microsoft.com/' + s for s in REQUIRED),
    quote(quote(FULL, safe=''), safe=''),  # Do not recursively decode arbitrary input.
    ['User.Read', 'Calendars.Read.Shared', 'Tasks.ReadWrite'],
    {'scope': BARE},
    42,
    '',
    None,
], ids=['tasks-missing', 'calendar-missing', 'profile-missing', 'foreign-resource',
        'lookalike-resource', 'http-resource', 'double-encoded', 'list-type', 'dict-type', 'number-type',
        'empty-scope', 'null-scope'])
def test_microsoft_missing_or_invalid_permissions_fail_explicitly(configured, scope):
    client, _, result = bind_with_response(configured, scope)
    query = parse_qs(urlsplit(result.location).query)
    assert query['reason'] == ['insufficient_permissions']
    assert client.get('/api/accounts').json['accounts'] == []
    assert result.status_code == 302


def test_first_microsoft_binding_requires_refresh_token(configured):
    client, _, result = bind_with_response(configured, BARE, refresh=False)
    assert parse_qs(urlsplit(result.location).query)['reason'] == ['missing_refresh_token']
    assert client.get('/api/accounts').json['accounts'] == []


def test_rebinding_preserves_existing_refresh_token_when_not_reissued(configured):
    app, remote, _ = configured
    client, headers, first = bind_with_response(configured, BARE)
    assert first.location.endswith('/?auth=connected')
    engine = app.extensions['cloud_accounts']
    with engine.db() as con:
        stored = dict(con.execute('SELECT * FROM cloud_accounts').fetchone())
    old_refresh = engine.decrypt(stored['tokens'])['refresh_token']

    def response(provider, params):
        tokens = remote.tokens(provider, params)
        tokens.pop('refresh_token', None)
        tokens['scope'] = BARE
        return tokens

    app.config['OAUTH_TRANSPORT'] = response
    params = begin(client, headers)
    result = finish(client, params['state'][0])
    assert result.location.endswith('/?auth=connected')
    with engine.db() as con:
        rows = con.execute('SELECT * FROM cloud_accounts').fetchall()
    assert len(rows) == 1 and rows[0]['id'] == stored['id']
    assert engine.decrypt(rows[0]['tokens'])['refresh_token'] == old_refresh


def test_microsoft_userinfo_accepts_opaque_personal_account_token():
    calls = []

    def transport(method, url, token, body=None, headers=None):
        calls.append((method, url, token))
        return {'sub': 'verified-subject', 'name': 'Member'}

    provider = CloudProvider('microsoft', 'opaque-encrypted-token-not-a-jwt', transport=transport)
    identity = provider.identity()
    assert identity['subject'] == 'verified-subject'
    assert calls == [('GET', GRAPH + 'oidc/userinfo', 'opaque-encrypted-token-not-a-jwt')]
    assert identity['email'] == ''  # An email claim is not guaranteed or required.
