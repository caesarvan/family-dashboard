"""Temporary real Flask/session/SQLite accounts; no financial data or network."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from copy import deepcopy
from pathlib import Path
import json
import socket
import sqlite3
from threading import Barrier, Event
import time
from types import SimpleNamespace

from flask import g, request
import pytest

import app as server
import finance_accounts as accounts
import member_sessions
from test_app import app, member
from test_device_sessions import ConnectionProxy, install_connection, invalidate
from test_household_spaces import create_space
from test_member_sessions import clone, legacy


URL = '/api/finance-accounts'
DATE = '2026-09-17'
KEY = 'a' * 32


@pytest.fixture(autouse=True)
def register_for_real_apps(monkeypatch):
    original = server.register_finance_hub
    original_accounts = accounts.register_finance_accounts
    def register_accounts(app, db, Problem, body, require_member, audit, *, initialize=True):
        def checked_audit(action, target=''):
            audit(action, target)
            if app.config.get('ASSET_TEST_AUDIT_FAILURE'):
                raise RuntimeError('Synthetic audit failure')
        original_accounts(app, db, Problem, body, require_member, checked_audit, initialize=initialize)
    # The standalone author base has no app registration yet; the later wired
    # combination uses the same real dependency wrapper and never registers twice.
    monkeypatch.setattr(server, 'register_finance_accounts', register_accounts, raising=False)
    def register(app, db, Problem, body, require_member, audit):
        original(app, db, Problem, body, require_member, audit)
        if 'finance_account_list' not in app.view_functions:
            register_accounts(app, db, Problem, body, require_member, audit)
    monkeypatch.setattr(server, 'register_finance_hub', register)
    def deny(*_args, **_kwargs):
        raise AssertionError('No network in manual account tests')
    monkeypatch.setattr(socket.socket, 'connect', deny)


@contextmanager
def database(app, **kwargs):
    with closing(sqlite3.connect(Path(app.config['DATA_DIR'])/'household.sqlite3', **kwargs)) as con:
        with con:
            yield con


def snapshot(app):
    with database(app) as con:
        names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        excluded = {'users', 'member_sessions', 'member_session_browsers', 'attempts'}
        return {name: con.execute('SELECT * FROM "'+name+'" ORDER BY rowid').fetchall()
                for name in names if name not in excluded}


def payload(key=KEY, **changes):
    return {'requestId': key, 'revision': 0, 'name': 'SYNTHETIC_PRIVATE_ACCOUNT', 'institution': '',
            'kind': 'asset', 'currency': 'CNY', 'note': '',
            'valuation': {'asOf': DATE, 'amountCents': 1000000}, **changes}


def create(client, headers, key=KEY, **changes):
    result = client.post(URL, json=payload(key, **changes), headers=headers)
    assert result.status_code == 201, result.json
    return result.json


def listing(client, date=DATE, status='active'):
    result = client.get(URL, query_string={'asOf': date, 'status': status})
    assert result.status_code == 200, result.json
    return result.json


def operation(client, key=KEY):
    result = client.get(URL+'/operations/'+key)
    assert result.status_code == 200, result.json
    return result.json


def change(client, headers, rid, rev, key, **changes):
    return client.patch(URL+'/'+rid, json={'requestId': key, 'revision': rev, 'changes': changes}, headers=headers)


def value(client, headers, rid, rev, key, amount, day=DATE):
    return client.put(URL+'/'+rid+'/valuations/'+day,
                      json={'requestId': key, 'revision': rev, 'amountCents': amount}, headers=headers)


def denied(response, status=401):
    assert response.status_code == status, response.json
    assert 'error' in response.json and 'SYNTHETIC_PRIVATE' not in response.get_data(as_text=True)


def test_schema_is_only_three_tables_idempotent_and_transactional():
    with closing(sqlite3.connect(':memory:')) as con:
        con.execute('CREATE TABLE users(id TEXT PRIMARY KEY)')
        con.commit()
        con.execute('BEGIN')
        accounts.init_schema(con)
        assert con.in_transaction
        con.rollback()
        assert [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")] == ['users']
        accounts.init_schema(con)
        accounts.init_schema(con)
        assert {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")} == {
            'users', 'finance_accounts', 'finance_account_valuations', 'finance_account_operations'}


def test_dated_assets_liabilities_currency_unknown_zero_and_original_tables(app):
    client, headers = member(app)
    before = snapshot(app)
    asset = create(client, headers)['accountId']
    debt = create(client, headers, 'b'*32, kind='liability', valuation={'asOf': DATE, 'amountCents': 200000})['accountId']
    create(client, headers, 'c'*32, currency='USD', valuation={'asOf': DATE, 'amountCents': None})
    create(client, headers, 'd'*32, currency='USD', valuation={'asOf': DATE, 'amountCents': 0})
    assert value(client, headers, asset, 1, 'e'*32, 1100000, '2026-09-18').status_code == 200
    assert value(client, headers, debt, 1, 'f'*32, 180000, '2026-09-18').status_code == 200
    for day, net in [(DATE, '800000'), ('2026-09-18', '920000')]:
        view = listing(client, day)
        assert view['owner'] == 'member1' and view['scope'] == 'manual_accounts_only'
        assert view['totals'][0]['knownNetCents'] == net
        assert view['totals'][1]['unknownCount'] == view['totals'][1]['knownCount'] == 1
        assert view['totals'][1]['knownAssetCents'] == '0'
    earlier = listing(client, '2026-09-16')
    assert all(a['valuation'] is None for a in earlier['accounts'])
    assert earlier['totals'][0]['missingCount'] == 2
    assert listing(client, '2026-09-19')['totals'][0]['olderCount'] == 2
    after = snapshot(app)
    changed_tables = {'finance_accounts','finance_account_valuations','finance_account_operations','settings','audit','sqlite_sequence'}
    assert {t: rows for t, rows in after.items() if t not in changed_tables} == {
        t: rows for t, rows in before.items() if t not in changed_tables}
    before_sequence, after_sequence = dict(before['sqlite_sequence']), dict(after['sqlite_sequence'])
    assert after_sequence.pop('audit') == before_sequence.pop('audit', 0) + 6
    assert after_sequence == before_sequence
    assert len(after['audit']) == len(before['audit']) + 6
    assert 'SYNTHETIC_PRIVATE_ACCOUNT' not in client.get('/api/state').get_data(as_text=True)


def test_null_latest_does_not_fall_back_to_old_known_amount_and_same_day_corrects(app):
    client, headers = member(app)
    rid = create(client, headers)['accountId']
    assert value(client, headers, rid, 1, 'b'*32, None, '2026-09-18').status_code == 200
    assert listing(client, '2026-09-18')['totals'][0]['knownCount'] == 0
    assert value(client, headers, rid, 2, 'c'*32, 0, '2026-09-18').status_code == 200
    history = client.get(URL+'/'+rid+'/valuations').json
    assert history['total'] == 2 and history['account']['revision'] == 3
    assert [r['amountCents'] for r in history['valuations']] == [0, 1000000]
    assert all(r['source'] == 'manual' for r in history['valuations'])


def test_archive_restore_cas_history_and_old_receipts_never_restore_current(app):
    client, headers = member(app)
    first = create(client, headers)
    rid = first['accountId']
    archived = change(client, headers, rid, 1, 'b'*32, archived=True)
    assert archived.status_code == 200 and archived.json['result']['valuation'] is None
    assert listing(client)['accounts'] == []
    assert listing(client, status='archived')['accounts'][0]['archived'] is True
    assert client.get(URL+'/'+rid+'/valuations').json['total'] == 1
    rejected = value(client, headers, rid, 2, 'c'*32, 0)
    assert rejected.status_code == 409 and rejected.json['code'] == 'account_archived'
    assert not operation(client, 'c'*32)['found']
    before = snapshot(app)
    assert client.post(URL, json=payload(), headers=headers).json == {**first, 'replayed': True}
    assert operation(client)['receipt'] == {**first, 'replayed': True}
    assert snapshot(app) == before
    assert change(client, headers, rid, 1, 'd'*32, archived=False).json['code'] == 'revision_conflict'
    restored = change(client, headers, rid, 2, 'e'*32, archived=False, name='RESTORED')
    assert restored.status_code == 200 and restored.json['result']['account']['revision'] == 3
    assert listing(client)['accounts'][0]['name'] == 'RESTORED'
    before = snapshot(app)
    assert change(client, headers, rid, 1, 'b'*32, archived=True).json == {**archived.json, 'replayed': True}
    assert snapshot(app) == before
    assert client.delete(URL+'/'+rid, json={'revision': 3}, headers=headers).status_code == 405


def test_history_pagination_is_complete_and_list_asof_not_future(app):
    client, headers = member(app)
    rid = create(client, headers)['accountId']
    for index in range(1, 4):
        assert value(client, headers, rid, index, str(index)*32, index, '2026-09-'+str(17+index)).status_code == 200
    pages = [client.get(URL+'/'+rid+'/valuations', query_string={'page': p, 'pageSize': 2}).json for p in (1,2,3)]
    assert all(p['total'] == 4 for p in pages)
    assert [r['asOf'] for p in pages for r in p['valuations']] == ['2026-09-20','2026-09-19','2026-09-18',DATE]
    assert pages[2]['valuations'] == []
    assert listing(client)['accounts'][0]['valuation']['asOf'] == DATE


def test_totals_above_javascript_integer_limit_are_exact_decimal_strings(app):
    client, headers = member(app)
    # Real persisted rows, bounded synthetic seeding avoids 100 password/HTTP writes.
    with database(app) as con:
        for index in range(100):
            rid = f'{index:024x}'
            con.execute('INSERT INTO finance_accounts VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                        (rid, 'member1', 'BIG', '', 'asset', 'CNY', '', 0, 1, 't', 't'))
            con.execute('INSERT INTO finance_account_valuations VALUES(?,?,?,?,?)', ('member1', rid, DATE, 10**14, 't'))
    total = listing(client)['totals'][0]
    assert total['knownAssetCents'] == total['knownNetCents'] == '10000000000000000'
    assert total['knownCount'] == 100


def test_raw_payload_key_binding_conflicts_across_targets_and_semantic_whitespace(app):
    client, headers = member(app)
    first = create(client, headers)
    rid = first['accountId']
    before = snapshot(app)
    for altered in [payload(name='OTHER'), payload(name=' SYNTHETIC_PRIVATE_ACCOUNT'), payload(currency='USD')]:
        response = client.post(URL, json=altered, headers=headers)
        assert response.status_code == 409 and response.json['code'] == 'operation_request_conflict'
    assert change(client, headers, rid, 1, KEY, note='OTHER').json['code'] == 'operation_request_conflict'
    assert value(client, headers, rid, 1, KEY, 1).json['code'] == 'operation_request_conflict'
    assert snapshot(app) == before


def test_new_session_can_recover_receipt_without_installing_old_state(app):
    client, headers = member(app)
    first = create(client, headers)
    rid = first['accountId']
    assert change(client, headers, rid, 1, 'b'*32, name='CURRENT').status_code == 200
    assert client.post('/api/login', json={'username':'member1','password':'testing-password-one'}).status_code == 200
    headers = {'X-CSRF-Token': client.get('/api/me').json['csrf']}
    before = snapshot(app)
    assert operation(client)['receipt'] == {**first, 'replayed': True}
    assert client.post(URL, json=payload(), headers=headers).json == {**first, 'replayed': True}
    assert listing(client)['accounts'][0]['name'] == 'CURRENT' and snapshot(app) == before


def test_anonymous_partner_tv_csrf_and_cross_household_boundaries(app):
    client, headers = member(app)
    rid = create(client, headers)['accountId']
    paths = [URL+'?asOf='+DATE, URL+'/'+rid+'/valuations', URL+'/operations/'+KEY]
    for path in paths:
        denied(app.test_client().get(path))
    denied(client.post(URL, json=payload('b'*32)), 403)
    denied(client.post(URL, json=payload('b'*32), headers={**headers, 'Origin':'https://evil.example'}), 403)
    partner, ph = member(app, 2)
    assert listing(partner)['accounts'] == [] and not operation(partner)['found']
    denied(partner.get(URL+'/'+rid+'/valuations'), 404)
    denied(change(partner, ph, rid, 1, 'b'*32, note='OTHER'), 404)
    denied(value(partner, ph, rid, 1, 'b'*32, 1), 404)
    tv = app.test_client()
    pair = tv.post('/api/pair/start', json={}).json
    assert client.post('/api/pair/approve', json={'code':pair['code'],'name':'Synthetic TV'}, headers=headers).status_code == 200
    assert tv.post('/api/pair/poll', json={'secret':pair['secret']}).json['approved']
    for path in paths:
        denied(tv.get(path), 403)
    denied(tv.post(URL, json=payload(), headers=headers), 403)
    other, _, space = create_space(app)
    assert other.get(space['entry']).status_code == 303
    assert other.post('/api/login', json={'username':'member1','password':'second-home-password-one'}).status_code == 200
    oh = {'X-CSRF-Token': other.get('/api/me').json['csrf']}
    assert listing(other)['accounts'] == [] and not operation(other)['found']
    denied(other.get(URL+'/'+rid+'/valuations'), 404)
    denied(change(other, oh, rid, 1, 'b'*32, note='OTHER'), 404)
    # Identical member label and operation key in a different physical household
    # create a distinct record, never read the first household's receipt.
    other_rid = create(other, oh)['accountId']
    assert other_rid != rid and operation(client)['receipt']['accountId'] == rid


@pytest.mark.parametrize('field,bad', [
    ('requestId', True), ('requestId', 'A'*32), ('requestId', 'a'*31), ('revision', True), ('revision', 1),
    ('name',''), ('name',' '), ('name','x'*121), ('name','bad\x00text'), ('institution',None),
    ('institution','x'*121), ('note','x'*1001), ('note','\ud800'), ('kind',[]), ('kind','cash'),
    ('currency','usd'), ('currency','USDT'), ('owner','member2'), ('extra',None),
    ('valuation',{}), ('valuation',{'asOf': '2026-02-30', 'amountCents': 0}),
    ('valuation',{'asOf': DATE,'amountCents':True}), ('valuation',{'asOf': DATE,'amountCents':-1}),
    ('valuation',{'asOf': DATE,'amountCents':1.0}), ('valuation',{'asOf': DATE,'amountCents':'1'}),
    ('valuation',{'asOf': DATE,'amountCents':10**14+1}), ('valuation',{'asOf': DATE,'amountCents':0,'note':'extra'}),
])
def test_strict_create_boundaries_never_consume_operation(app, field, bad):
    client, headers = member(app)
    before = snapshot(app)
    response = client.post(URL, json={**payload(), field:bad}, headers=headers)
    assert response.status_code == 400, response.json
    assert response.json['code'] == 'invalid_request'
    assert not operation(client)['found'] and snapshot(app) == before


def test_valid_text_limits_null_zero_upper_amount_and_invalid_request_structure(app):
    client, headers = member(app)
    create(client, headers, name='字'*120, institution='字'*120, note='字'*998+'\n\t',
           valuation={'asOf':'2024-02-29','amountCents':10**14})
    before = snapshot(app)
    for raw in ['[]', '{"requestId":"a","requestId":"b"}', '{"valuation":{"asOf":"a","asOf":"b"}}',
                '{"number":NaN}', '{"number":Infinity}', '{bad']:
        assert client.post(URL, data=raw, content_type='application/json', headers=headers).status_code == 400
    assert client.post(URL, data=' '*17000, content_type='application/json', headers=headers).status_code == 413
    assert snapshot(app) == before


def test_strict_query_update_and_value_parameters(app):
    client, headers = member(app)
    rid = create(client, headers)['accountId']
    before = snapshot(app)
    for query in ['', '?asOf='+DATE+'&asOf='+DATE, '?asOf=2026-2-3', '?asOf='+DATE+'&owner=member2',
                  '?asOf='+DATE+'&status=foo', '?asOf='+DATE+'&status=active&status=active']:
        assert client.get(URL+query).status_code == 400
    for query in ['?page=0', '?page=true', '?page=01', '?page=1&page=2', '?pageSize=101', '?asOf='+DATE]:
        assert client.get(URL+'/'+rid+'/valuations'+query).status_code == 400
    for changes in [{}, {'currency':'USD'}, {'kind':'liability'}, {'archived':1}, {'name':None}, {'note':'\x00'}]:
        assert change(client, headers, rid, 1, 'b'*32, **changes).status_code == 400
    for rev in [0, True, '1', 1.0]:
        assert change(client, headers, rid, rev, 'b'*32, note='x').status_code == 400
    for cash in [True, -1, 1.0, '1', 10**14+1]:
        assert value(client, headers, rid, 1, 'b'*32, cash).status_code == 400
    assert value(client, headers, rid, 1, 'b'*32, 1, '2026-02-30').status_code == 400
    assert client.get(URL+'/operations/'+KEY+'?extra=1').status_code == 400
    assert client.post(URL+'?extra=1', json=payload('b'*32), headers=headers).status_code == 400
    assert client.get(URL+'/operations/'+'g'*32).status_code == 400
    assert snapshot(app) == before


@pytest.mark.parametrize('limit', ['accounts', 'valuations', 'operations', 'bytes'])
def test_capacity_preserves_existing_records_and_history_replay(app, monkeypatch, limit):
    client, headers = member(app)
    first = create(client, headers)
    rid = first['accountId']
    constant = {'accounts':'MAX_ACCOUNTS', 'valuations':'MAX_VALUATIONS', 'operations':'MAX_OPERATIONS', 'bytes':'MAX_OPERATION_BYTES'}[limit]
    monkeypatch.setattr(accounts, constant, 1)
    before = snapshot(app)
    response = (value(client, headers, rid, 1, 'b'*32, 1, '2026-09-18') if limit == 'valuations'
                else client.post(URL, json=payload('b'*32), headers=headers))
    assert response.status_code == 409 and response.json['code'] == 'capacity_exceeded'
    assert snapshot(app) == before
    assert client.post(URL, json=payload(), headers=headers).json == {**first, 'replayed': True}
    assert snapshot(app) == before


@pytest.mark.parametrize('route', ['list', 'history', 'receipt', 'missing_receipt'])
@pytest.mark.parametrize('kind', ['session', 'expired', 'auth_version'])
def test_read_snapshot_released_before_fresh_revocation_check(app, route, kind):
    client, headers = member(app)
    rid = create(client, headers)['accountId']
    paths = {'list':URL, 'history':URL+'/'+rid+'/valuations', 'receipt':URL+'/operations/'+KEY,
             'missing_receipt':URL+'/operations/'+'b'*32}
    calls, before = [], snapshot(app)
    def after(sql):
        trigger = 'FROM finance_account_operations WHERE' if 'receipt' in route else 'FROM finance_accounts WHERE'
        if trigger in sql and not calls:
            with database(app) as con:
                invalidate(con, kind)
            calls.append(True)
    install_connection(app, paths[route], 'GET', after=after)
    response = client.get(paths[route], query_string={'asOf':DATE} if route == 'list' else None)
    denied(response)
    assert calls == [True] and snapshot(app) == before


@pytest.mark.parametrize('operation_name', ['create', 'update', 'valuation', 'replay'])
@pytest.mark.parametrize('kind', ['session', 'expired', 'auth_version'])
def test_write_rechecks_actual_session_after_waiting_for_real_sqlite_lock(app, operation_name, kind):
    client, headers = member(app)
    rid = create(client, headers)['accountId']
    method, path, data = {
        'create':('POST', URL, payload('b'*32)), 'replay':('POST', URL, payload()),
        'update':('PATCH',URL+'/'+rid,{'requestId':'b'*32,'revision':1,'changes':{'note':'changed'}}),
        'valuation':('PUT',URL+'/'+rid+'/valuations/'+DATE,{'requestId':'b'*32,'revision':1,'amountCents':1})}[operation_name]
    entered, before = Event(), snapshot(app)
    with closing(sqlite3.connect(Path(app.config['DATA_DIR'])/'household.sqlite3', timeout=5, check_same_thread=False)) as writer:
        def hold(sql):
            if sql == 'BEGIN IMMEDIATE':
                writer.execute('BEGIN IMMEDIATE')
                invalidate(writer, kind)
                entered.set()
        install_connection(app, path, method, before=hold)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(client.open, path, method=method, json=data, headers=headers)
            try:
                assert entered.wait(10) and not future.done()
            finally:
                writer.commit()
            denied(future.result(timeout=10))
    assert snapshot(app) == before


@pytest.mark.parametrize('operation_name', ['create','update','valuation'])
@pytest.mark.parametrize('failure', ['audit','expiry'])
def test_complete_rollback_after_audit_failure_or_commit_time_expiry(app, monkeypatch, operation_name, failure):
    client, headers = member(app)
    rid = create(client, headers)['accountId']
    method, path, data = {
        'create':('POST',URL,payload('b'*32)),
        'update':('PATCH',URL+'/'+rid,{'requestId':'b'*32,'revision':1,'changes':{'archived':True}}),
        'valuation':('PUT',URL+'/'+rid+'/valuations/'+DATE,{'requestId':'b'*32,'revision':1,'amountCents':0})}[operation_name]
    before = snapshot(app)
    if failure == 'audit':
        app.config['ASSET_TEST_AUDIT_FAILURE'] = True
        with pytest.raises(RuntimeError, match='Synthetic audit failure'):
            client.open(path, method=method, json=data, headers=headers)
    else:
        with database(app) as con:
            expires = con.execute("SELECT max(expires_at) FROM member_sessions WHERE owner='member1'").fetchone()[0]
        clock = [time.time()]
        monkeypatch.setattr(member_sessions, 'time', SimpleNamespace(time=lambda:clock[0]))
        def after(sql):
            if sql.startswith('UPDATE settings SET revision'):
                clock[0] = expires+1
        install_connection(app, path, method, after=after)
        denied(client.open(path, method=method, json=data, headers=headers))
        assert clock[0] == expires+1
    assert snapshot(app) == before


@pytest.mark.parametrize('case', ['same_key', 'different_payload', 'same_revision'])
def test_real_concurrent_requests_have_one_effect_or_cas_winner(app, case):
    first, headers = member(app)
    second = clone(app, first)
    rid = create(first, headers, 'f'*32)['accountId'] if case == 'same_revision' else None
    clients, barrier = [first,second], Barrier(2)
    def send(index):
        barrier.wait(timeout=10)
        if rid:
            return value(clients[index], headers, rid, 1, str(index+1)*32, index+1)
        return clients[index].post(URL, json=payload(name='OTHER' if index and case == 'different_payload' else 'SYNTHETIC_PRIVATE_ACCOUNT'), headers=headers)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(send, [0,1]))
    codes = sorted(r.status_code for r in results)
    assert codes == ([201,201] if case == 'same_key' else [200,409] if rid else [201,409])
    if case == 'same_key':
        assert sorted(r.json['replayed'] for r in results) == [False,True]
    assert len(listing(first)['accounts']) == 1
    with database(app) as con:
        assert con.execute('SELECT count(*) FROM finance_account_operations').fetchone()[0] == (2 if rid else 1)


def test_unknown_operation_can_be_in_flight_and_new_session_replay_is_safe(app):
    client, headers = member(app)
    reader = clone(app, client)
    entered, release = Event(), Event()
    def pause(sql):
        if sql == 'BEGIN IMMEDIATE':
            entered.set()
            assert release.wait(10)
    install_connection(app, URL, 'POST', before=pause)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.post, URL, json=payload(), headers=headers)
        try:
            assert entered.wait(10)
            assert operation(reader) == {'requestId':KEY,'found':False,'receipt':None}
        finally:
            release.set()
        made = future.result(timeout=10)
    assert made.status_code == 201 and operation(reader)['found']


def test_old_cookie_is_not_accepted_after_new_login_and_legacy_cookie_has_no_nested_transaction(app, monkeypatch):
    client, headers = member(app)
    old = clone(app, client)
    assert client.post('/api/login', json={'username':'member1','password':'testing-password-one'}).status_code == 200
    denied(old.get(URL+'?asOf='+DATE))
    migrated, _, _ = legacy(app, app.extensions['member_sessions'], monkeypatch)
    # Existing legacy fixture returns a real signed HTTP client, not a fake actor.
    assert migrated.get(URL+'?asOf='+DATE).status_code == 200
    fresh_headers = {'X-CSRF-Token':migrated.get('/api/me').json['csrf']}
    assert migrated.post(URL, json=payload(), headers=fresh_headers).status_code == 201


def test_export_owner_whitelists_archived_and_history_without_private_operation_inputs(app):
    client, headers = member(app)
    rid = create(client, headers)['accountId']
    assert value(client, headers, rid, 1, 'b'*32, None, '2026-09-18').status_code == 200
    assert change(client, headers, rid, 2, 'c'*32, archived=True).status_code == 200
    partner, ph = member(app, 2)
    other_rid = create(partner, ph, name='PARTNER_SECRET')['accountId']
    before = snapshot(app)
    with database(app) as con:
        con.row_factory = sqlite3.Row
        exported = accounts.export_owned_accounts(con, 'member1')
        second = accounts.export_owned_accounts(con, 'member2')
    assert [a['id'] for a in exported['accounts']] == [rid] and exported['accounts'][0]['archived']
    assert len(exported['valuations']) == 2 and exported['valuations'][1]['amountCents'] is None
    assert len(exported['operations']) == 3
    assert all(set(o) == {'operation','accountId','completedAt'} for o in exported['operations'])
    assert all(set(v) == {'accountId','asOf','amountCents','source','updatedAt'} for v in exported['valuations'])
    encoded = json.dumps(exported)
    assert all(key not in encoded for key in ('payload_hash','requestId','credential','PARTNER_SECRET',other_rid))
    assert [a['id'] for a in second['accounts']] == [other_rid]
    assert snapshot(app) == before


def test_storage_limit_failure_after_business_changes_rolls_back_everything(app, monkeypatch):
    client, headers = member(app)
    create(client, headers)
    with database(app) as con:
        used = con.execute('SELECT sum(length(CAST(result AS BLOB))) FROM finance_account_operations').fetchone()[0]
    monkeypatch.setattr(accounts, 'MAX_OPERATION_BYTES', used + 10)
    before = snapshot(app)
    response = client.post(URL, json=payload('b'*32), headers=headers)
    assert response.status_code == 409 and response.json['code'] == 'capacity_exceeded'
    assert snapshot(app) == before


def test_committed_but_revoked_before_response_keeps_exact_recoverable_receipt(app):
    client, headers = member(app)
    fired = []
    class RevokeAfterCommit(ConnectionProxy):
        def commit(self):
            self.connection.commit()
            if not fired:
                with database(app) as con:
                    invalidate(con)
                fired.append(True)
    install_connection(app, URL, 'POST')
    def hook():
        if request.path == URL and request.method == 'POST':
            previous = g.db
            g.db = RevokeAfterCommit(previous)
    app.before_request_funcs[None].append(hook)
    denied(client.post(URL, json=payload(), headers=headers))
    assert fired == [True]
    with database(app) as con:
        assert con.execute('SELECT count(*) FROM finance_accounts').fetchone()[0] == 1
        assert con.execute('SELECT count(*) FROM finance_account_operations').fetchone()[0] == 1
    reader, _ = member(app)
    receipt = operation(reader)['receipt']
    assert receipt['result']['account']['name'] == 'SYNTHETIC_PRIVATE_ACCOUNT'
    assert receipt['replayed'] is True


def test_new_application_reads_persisted_history_without_schema_or_data_rewrite(app):
    client, headers = member(app)
    rid = create(client, headers)['accountId']
    assert value(client, headers, rid, 1, 'b'*32, 0, '2026-09-18').status_code == 200
    before = snapshot(app)
    restarted = server.create_app({'TESTING':True,'SECRET_KEY':app.secret_key,
        'DATA_DIR':app.config['DATA_DIR'],'SESSION_COOKIE_SECURE':False})
    reader, _ = member(restarted)
    history = reader.get(URL+'/'+rid+'/valuations').json
    assert history['total'] == 2 and history['account']['revision'] == 2
    assert history['valuations'][0]['amountCents'] == 0
    assert operation(reader)['found']
    assert snapshot(app) == before
