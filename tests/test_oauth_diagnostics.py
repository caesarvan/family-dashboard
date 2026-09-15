"""OAuth diagnostics must identify stages without copying provider payloads."""
from io import BytesIO
import json
from urllib.error import HTTPError, URLError

import pytest
import cloud_accounts
from cloud_providers import ProviderError
from test_cloud_accounts import configured, login, begin, finish


def test_token_error_logs_only_allowlisted_code_and_numeric_sts(configured, monkeypatch, caplog):
    app, _, _ = configured
    app.config.pop('OAUTH_TRANSPORT')
    secret = 'never-print-private-token-or-email@example.test'

    class Endpoint:
        def open(self, request, timeout):
            raw = json.dumps({'error':'invalid_client', 'error_codes':[7000215, secret],
                              'error_description':secret, 'access_token':secret}).encode()
            raise HTTPError(request.full_url, 401, secret, {}, BytesIO(raw))

    monkeypatch.setattr(cloud_accounts, 'build_opener', lambda *a: Endpoint())
    c, h = login(app)
    params = begin(c, h)
    result = finish(c, params['state'][0], code=secret)
    assert result.location.endswith('reason=invalid_client')
    assert 'stage=token_exchange' in caplog.text
    assert 'status=401' in caplog.text and '7000215' in caplog.text
    assert secret not in caplog.text and secret not in result.location
    assert c.get('/api/accounts').json['accounts'] == []


def test_network_failure_is_token_stage_without_exception_payload(configured, caplog):
    app, _, _ = configured
    def fail(provider, params):
        raise URLError('never-print-private-endpoint-details')
    app.config['OAUTH_TRANSPORT'] = fail
    c, h = login(app)
    params = begin(c, h)
    result = finish(c, params['state'][0])
    assert result.location.endswith('reason=token_failed')
    assert 'stage=token_exchange' in caplog.text
    assert 'never-print' not in caplog.text


def test_identity_failure_is_distinguished_without_personal_details(configured, caplog):
    app, _, _ = configured
    class IdentityFailure:
        def __init__(self, *args, **kwargs):
            pass
        def identity(self):
            raise ProviderError('never-print-person@example.test', 403)
    app.config['CLOUD_PROVIDER_FACTORY'] = IdentityFailure
    c, h = login(app)
    params = begin(c, h)
    result = finish(c, params['state'][0])
    assert result.location.endswith('reason=identity_failed')
    assert 'stage=identity_lookup' in caplog.text and 'status=403' in caplog.text
    assert 'never-print' not in caplog.text


def test_authorization_denial_preserves_safe_error_category(configured, caplog):
    app, _, _ = configured
    c, h = login(app)
    params = begin(c, h)
    result = c.get('/auth/microsoft/callback', query_string={
        'state':params['state'][0], 'error':'access_denied',
        'error_description':'AADSTS65001: never-print-person@example.test has not consented'})
    assert result.location.endswith('reason=provider_denied')
    assert 'authorization_return' in caplog.text and '65001' in caplog.text
    assert 'never-print' not in caplog.text


def test_untrusted_error_metadata_cannot_become_logs():
    error = cloud_accounts.OAuthFailure({'error':'private@example.test\nspoofed',
                                       'error_codes':['private', {'token':'private'}]})
    assert error.oauth_error == 'unknown' and error.aadsts_codes == []
