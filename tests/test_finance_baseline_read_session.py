"""Private-report read fences: actual Flask sessions and temporary SQLite only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import socket
import sqlite3

import pytest
from flask import g, request

from finance_baseline import import_baseline
from test_app import app, member
from test_device_sessions import install_connection, invalidate
from test_finance_baseline import payload
from test_household_spaces import create_space
from test_member_sessions import legacy
from test_spending_observations import observation, preview, confirm


PATH = '/api/finance-baseline/private'


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*_args, **_kwargs):
        raise AssertionError('Synthetic read tests must not access the network')
    monkeypatch.setattr(socket.socket, 'connect', denied)


def database(app):
    return Path(app.config['DATA_DIR']) / 'household.sqlite3'


def seed(app, payload, owner='member1'):
    value = deepcopy(payload)
    for item in value.values():
        item['owner'] = owner
    with closing(sqlite3.connect(database(app))) as con:
        import_baseline(con, **value)
        con.commit()
    return value['private']


def business_snapshot(app):
    # Auth bookkeeping is outside the business-data guarantee. Include every
    # other household table, including receipts, observations, settings/audit.
    with closing(sqlite3.connect(database(app))) as con:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {t: con.execute('SELECT * FROM "' + t.replace('"', '""') + '" ORDER BY rowid').fetchall()
                for t in tables if t not in {'users', 'member_sessions', 'member_session_browsers', 'attempts'}}


def change_auth(app, kind):
    with closing(sqlite3.connect(database(app))) as con:
        invalidate(con, kind)
        con.commit()


def assert_denied(response):
    assert response.status_code == 401, response.json
    assert set(response.json) == {'error'}
    assert 'PRIVATE_' not in response.get_data(as_text=True)


@pytest.mark.parametrize('has_baseline', [False, True])
@pytest.mark.parametrize('kind', ['session', 'expired', 'auth_version'])
@pytest.mark.parametrize('stage', ['after_guard', 'after_snapshot_read'])
def test_invalidated_credential_never_returns_report(app, payload, has_baseline, kind, stage):
    if has_baseline:
        seed(app, payload)
    client, _ = member(app)
    before, calls = business_snapshot(app), []

    def revoke_once():
        assert not calls
        change_auth(app, kind)
        calls.append(kind)

    if stage == 'after_guard':
        def hook():
            if request.path == PATH:
                assert g.member_session['owner'] == 'member1'
                revoke_once()
        app.before_request_funcs[None].append(hook)
    else:
        def after(sql):
            if sql.startswith('SELECT private_data,revision'):
                revoke_once()
        install_connection(app, PATH, 'GET', after=after)
    assert_denied(client.get(PATH))
    assert calls == [kind]
    assert business_snapshot(app) == before


@pytest.mark.parametrize('kind', ['session', 'expired', 'auth_version'])
def test_revoked_during_observation_read_discards_entire_projection(app, payload, kind):
    seed(app, payload)
    client, headers = member(app)
    assert confirm(client, headers, preview(client, headers)).status_code == 200
    before, calls = business_snapshot(app), []

    def after(sql):
        if sql.startswith('SELECT revision,source_digest,candidate_digest,candidate_json'):
            change_auth(app, kind)
            calls.append(kind)
    install_connection(app, PATH, 'GET', after=after)
    assert_denied(client.get(PATH))
    assert calls == [kind] and business_snapshot(app) == before


@pytest.mark.parametrize('field', ['session_id', 'session_owner', 'session_version', 'actor_owner', 'actor_version', 'household'])
def test_captured_request_must_match_real_session(app, payload, field):
    seed(app, payload)
    client, _ = member(app)
    before = business_snapshot(app)

    def hook():
        if request.path != PATH:
            return
        if field.startswith('session_'):
            key, value = {'session_id': ('id', 'other-session'), 'session_owner': ('owner', 'member2'),
                          'session_version': ('auth_version', 999)}[field]
            g.member_session = {**g.member_session, key: value}
        else:
            key, value = {'actor_owner': ('id', 'member2'), 'actor_version': ('auth_version', 999),
                          'household': ('householdId', 'another-household')}[field]
            g.actor = {**g.actor, key: value}
    app.before_request_funcs[None].append(hook)
    assert_denied(client.get(PATH))
    assert business_snapshot(app) == before


def test_actual_login_rotates_session_while_private_read_is_in_flight(app, payload):
    seed(app, payload)
    client, _ = member(app)
    replacement = app.test_client()
    replacement.set_cookie('session', client.get_cookie('session').value)
    before, calls = business_snapshot(app), []

    def after(sql):
        if sql.startswith('SELECT private_data,revision') and not calls:
            with ThreadPoolExecutor(max_workers=1) as pool:
                response = pool.submit(replacement.post, '/api/login', json={
                    'username': 'member1', 'password': 'testing-password-one'}).result(timeout=10)
            assert response.status_code == 200, response.json
            calls.append(True)
    install_connection(app, PATH, 'GET', after=after)
    assert_denied(client.get(PATH))
    assert calls == [True] and business_snapshot(app) == before
    assert replacement.get(PATH).status_code == 200


@pytest.mark.parametrize('newer_baseline', [False, True])
def test_complete_private_projection_and_observation_precedence_remain_unchanged(app, payload, newer_baseline):
    original = seed(app, payload)
    client, headers = member(app)
    assert client.get(PATH).json == {**original, 'revision': 1}
    assert confirm(client, headers, preview(client, headers)).status_code == 200
    if newer_baseline:
        payload['private']['spending'] = observation('2026-09-16', 1700)['spending']
        original = seed(app, payload)
    before = business_snapshot(app)
    value = client.get(PATH).json
    with closing(sqlite3.connect(database(app))) as con:
        row = con.execute('SELECT revision,source_digest,accepted_at FROM finance_spending_observations').fetchone()
    expected_spending = payload['private']['spending'] if newer_baseline else observation()['spending']
    assert {k: v for k, v in value.items() if k not in {'spending', 'spendingObservation', 'revision'}} == {
        k: v for k, v in original.items() if k != 'spending'}
    assert value['revision'] == (2 if newer_baseline else 1)
    assert value['spending'] == expected_spending
    meta = value['spendingObservation']
    assert (meta['revision'], meta['sourceDigest'], meta['acceptedAt']) == tuple(row)
    assert meta['origin'] == ('baseline' if newer_baseline else 'spending_observation')
    assert bool(meta['warnings']) is newer_baseline and meta['assetBaselineUnchanged'] is True
    assert business_snapshot(app) == before


def test_baseline_and_observation_use_one_wal_snapshot(app, payload):
    seed(app, payload)
    client, headers = member(app)
    assert confirm(client, headers, preview(client, headers)).status_code == 200
    old, calls = client.get(PATH).json, []

    def after(sql):
        if not sql.startswith('SELECT private_data,revision') or calls:
            return
        # Commit both lanes from a second real connection after the baseline
        # SELECT, before decoration reads the observation. No mocked DTOs.
        with closing(sqlite3.connect(database(app))) as con:
            con.execute('BEGIN IMMEDIATE')
            payload['private']['income'][0]['label'] = 'PRIVATE_NEW_SNAPSHOT'
            import_baseline(con, **payload)
            candidate = observation(net=1900)
            con.execute('UPDATE finance_spending_observations SET revision=revision+1,candidate_json=?', (json.dumps(candidate),))
            con.commit()
        calls.append(True)
    install_connection(app, PATH, 'GET', after=after)
    assert client.get(PATH).json == old
    current = client.get(PATH).json
    assert current['income'][0]['label'] == 'PRIVATE_NEW_SNAPSHOT'
    assert current['revision'] == current['spendingObservation']['revision'] == 2
    assert current['spending']['monthly'][0]['netSpendCents'] == 1900
    assert calls == [True]


@pytest.mark.parametrize('has_baseline', [False, True])
def test_legacy_credential_read_releases_implicit_transactions(app, payload, monkeypatch, has_baseline):
    expected = seed(app, payload) if has_baseline else None
    client, _, _ = legacy(app, app.extensions['member_sessions'], monkeypatch)
    before, open_transactions = business_snapshot(app), []

    def record(_exception):
        if request.path == PATH:
            open_transactions.append(g.db.in_transaction)
    app.teardown_request_funcs[None].append(record)
    for _ in range(2):
        response = client.get(PATH)
        assert response.status_code == 200, response.json
        assert response.json == ({**expected, 'revision': 1} if has_baseline else None)
    assert open_transactions == [False, False]
    assert business_snapshot(app) == before


def test_members_tv_and_tenants_keep_private_scope(app, payload):
    owner_value = seed(app, payload)
    payload['private']['assets'][0]['label'] = 'PRIVATE_PARTNER_ACCOUNT'
    partner_value = seed(app, payload, 'member2')
    owner, headers = member(app)
    partner, _ = member(app, 2)
    tv = app.test_client()
    pair = tv.post('/api/pair/start', json={}).json
    assert owner.post('/api/pair/approve', json={'code': pair['code']}, headers=headers).status_code == 200
    assert tv.post('/api/pair/poll', json={'secret': pair['secret']}).json['approved']
    other, _, result = create_space(app)
    assert other.get(result['entry']).status_code == 303
    assert other.post('/api/login', json={'username': 'member1', 'password': 'second-home-password-one'}).status_code == 200
    before = business_snapshot(app)
    assert owner.get(PATH + '?owner=member2').json == {**owner_value, 'revision': 1}
    assert partner.get(PATH + '?owner=member1').json == {**partner_value, 'revision': 1}
    assert tv.get(PATH).status_code == 403
    assert app.test_client().get(PATH).status_code == 401
    assert other.get(PATH + '?owner=member1&householdId=default').json is None
    other.set_cookie('session', owner.get_cookie('session').value)
    assert_denied(other.get(PATH))
    assert business_snapshot(app) == before
