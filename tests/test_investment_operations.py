"""Actual SQLite writes and Flask boundaries; synthetic holdings, no network."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from pathlib import Path
import socket
import sqlite3
from threading import Barrier, Event

import pytest

import finance_hub
import investment_operations
from test_app import app, member
from test_finance_hub import hub, investment
from test_household_spaces import create_space
from test_investment_import import csv_payload, holding, preview, confirm


URL = '/api/finance-hub/investments'
KEY = 'a' * 32


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError('Investment operation tests must not access external networks')
    monkeypatch.setattr(socket.socket, 'connect', deny)


def create(client, key=KEY, headers=None, **changes):
    value = investment(**changes)
    if key is not None:
        value['requestId'] = key
    return client.post(URL, json=value, headers=headers)


def current(client, headers=None):
    return client.get(URL, headers=headers)


def operation(client, key=KEY, headers=None):
    return client.get(URL + '/operations/' + key, headers=headers)


def receipt(client, planned, headers=None, **changes):
    query = {'sourceName': planned.json['sourceName'], 'sourceDigest': planned.json['sourceDigest'], **changes}
    return client.get(URL + '/imports/receipts', query_string=query, headers=headers)


def snapshot(target):
    with closing(sqlite3.connect(target)) as con:
        return {name: con.execute('SELECT * FROM ' + name + ' ORDER BY rowid').fetchall() for name in (
            'hub_investments', 'hub_investment_operations', 'hub_investment_sources', 'hub_investment_links',
            'hub_investment_import_receipts', 'hub_transactions', 'hub_budgets', 'audit')}


def test_legacy_crud_keeps_response_and_no_operation_receipts(hub):
    client, target = hub
    first = create(client, None)
    assert first.status_code == 201 and first.json['revision'] == 1
    assert 'requestId' not in first.json and 'replayed' not in first.json
    rid = first.json['id']
    edited = client.patch(URL + '/' + rid, json=investment(revision=1, value='130'))
    assert edited.status_code == 200 and edited.json['revision'] == 2
    assert 'requestId' not in edited.json
    assert client.delete(URL + '/' + rid, json={'revision': 1}).status_code == 409
    assert client.delete(URL + '/' + rid, json={'revision': 2}).json == {'deleted': True}
    assert snapshot(target)['hub_investment_operations'] == []


def test_create_update_delete_readback_replay_never_restores_old_state(hub):
    client, target = hub
    assert operation(client).status_code == 404
    made = create(client)
    assert made.status_code == 201 and made.json['replayed'] is False
    rid = made.json['id']
    creation = operation(client).json
    assert creation['kind'] == 'create' and creation['recordId'] == rid
    assert creation['result'] == {k: v for k, v in made.json.items() if k not in {'requestId', 'replayed'}}
    assert creation['completedAt'].endswith('+00:00')
    change = investment(value='180.25', revision=1, requestId='b' * 32)
    edited = client.patch(URL + '/' + rid, json=change)
    assert edited.status_code == 200 and edited.json['valueCents'] == 18025 and edited.json['revision'] == 2
    removed = client.delete(URL + '/' + rid, json={'revision': 2, 'requestId': 'c' * 32})
    assert removed.json == {'deleted': True, 'requestId': 'c' * 32, 'replayed': False}
    after = snapshot(target)
    assert create(client).json == {**made.json, 'replayed': True}
    assert client.patch(URL + '/' + rid, json=change).json == {**edited.json, 'replayed': True}
    assert client.delete(URL + '/' + rid, json={'revision': 2, 'requestId': 'c' * 32}).json == {**removed.json, 'replayed': True}
    assert operation(client).json == creation
    assert operation(client, 'b' * 32).json['result']['revision'] == 2
    assert operation(client, 'c' * 32).json['result'] == {'deleted': True}
    assert current(client).json == {'investments': [], 'sources': []}
    assert snapshot(target) == after
    assert create(client, 'd' * 32).json['id'] != rid  # New explicit operation may create another record.


@pytest.mark.parametrize('change', [
    {'name': 'OTHER'}, {'currency': 'CNY'}, {'cost': '120.00'}, {'quantity': '12.500'},
    {'asOf': '2026-09-05'}, {'revision': 1}, {'value': ''}, {'note': 'CHANGED'},
])
def test_same_key_changed_normalized_content_conflicts(hub, change):
    client, target = hub
    assert create(client).status_code == 201
    before = snapshot(target)
    response = create(client, **change)
    assert response.status_code == 409 and response.json['code'] == 'operation_request_conflict'
    assert snapshot(target) == before


def test_normalized_equivalent_amount_and_labels_replay(hub):
    client, target = hub
    first = create(client)
    before = snapshot(target)
    equivalent = create(client, cost='100.00', value=120, name=' PRIVATE_FUND ', currency='usd')
    assert equivalent.json == {**first.json, 'replayed': True}
    assert snapshot(target) == before


def test_operation_key_is_global_across_kind_and_record_id(hub):
    client, target = hub
    first = create(client).json
    other = create(client, 'b' * 32, name='OTHER').json
    before = snapshot(target)
    responses = [client.patch(URL + '/' + first['id'], json=investment(revision=1, requestId=KEY)),
                 client.delete(URL + '/' + first['id'], json={'revision': 1, 'requestId': KEY})]
    assert all(r.status_code == 409 and r.json['code'] == 'operation_request_conflict' for r in responses)
    assert snapshot(target) == before
    changed = investment(value='130', revision=1, requestId='c' * 32)
    assert client.patch(URL + '/' + first['id'], json=changed).status_code == 200
    after = snapshot(target)
    wrong_record = client.patch(URL + '/' + other['id'], json=changed)
    assert wrong_record.status_code == 409 and wrong_record.json['code'] == 'operation_request_conflict'
    assert snapshot(target) == after


@pytest.mark.parametrize('key', [None, '', 3, True, 'A' * 32, 'a' * 31, 'a' * 33, 'g' * 32, ['a' * 32]])
def test_invalid_request_ids_never_write(hub, key):
    client, target = hub
    before = snapshot(target)
    response = client.post(URL, json=investment(requestId=key))
    assert response.status_code == 400
    assert snapshot(target) == before


@pytest.mark.parametrize('revision', [None, True, '1', 0, 2, 1.0])
def test_revision_conflict_is_explicit_and_does_not_consume_key(hub, revision):
    client, target = hub
    item = create(client).json
    before = snapshot(target)
    response = client.patch(URL + '/' + item['id'], json=investment(revision=revision, requestId='b' * 32))
    assert response.status_code == 409 and response.json['code'] == 'revision_conflict'
    assert operation(client, 'b' * 32).status_code == 404
    assert snapshot(target) == before


@pytest.mark.parametrize('parallel', ['same_key', 'different_payload', 'different_keys_cas'])
def test_concurrent_operations_are_atomic_and_only_one_write_wins(hub, parallel):
    client, target = hub
    original = create(client, 'f' * 32).json if parallel == 'different_keys_cas' else None
    barrier = Barrier(2)
    def send(index):
        isolated = client.application.test_client()
        barrier.wait(timeout=10)
        if original:
            return isolated.patch(URL + '/' + original['id'], json=investment(
                value=str(130 + index), revision=1, requestId=str(index + 1) * 32))
        return create(isolated, name='CHANGED' if index and parallel == 'different_payload' else 'PRIVATE_FUND')
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(send, range(2)))
    if parallel == 'same_key':
        assert [r.status_code for r in responses] == [201, 201]
        assert sorted(r.json['replayed'] for r in responses) == [False, True]
        assert len({r.json['id'] for r in responses}) == 1
    else:
        assert sorted(r.status_code for r in responses) == ([200, 409] if original else [201, 409])
        failed = next(r for r in responses if r.status_code == 409)
        assert failed.json['code'] == ('revision_conflict' if original else 'operation_request_conflict')
    state = snapshot(target)
    assert len(state['hub_investments']) == 1
    assert len(state['hub_investment_operations']) == (2 if original else 1)
    assert len(state['audit']) == (2 if original else 1)


def test_committed_but_lost_response_can_be_read_and_retried(hub):
    client, target = hub
    lost = [False]
    @client.application.after_request
    def lose_once(response):
        if response.status_code == 201 and not lost[0]:
            lost[0] = True
            raise ConnectionError('synthetic response transport loss after commit')
        return response
    with pytest.raises(ConnectionError):
        create(client)
    after = snapshot(target)
    found = operation(client)
    assert found.status_code == 200 and found.json['result']['revision'] == 1
    assert create(client).json['replayed'] is True
    assert snapshot(target) == after


def test_404_can_precede_late_committed_request(hub, monkeypatch):
    client, target = hub
    entered, release = Event(), Event()
    original = finance_hub.secrets.token_hex
    def delayed_id(size):
        entered.set()
        assert release.wait(timeout=10)
        return original(size)
    monkeypatch.setattr(finance_hub.secrets, 'token_hex', delayed_id)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(create, client.application.test_client())
        assert entered.wait(timeout=10)
        try:
            response = operation(client)
            assert response.status_code == 404 and response.json['code'] == 'investment_operation_not_found'
        finally:
            release.set()
        assert future.result(timeout=10).status_code == 201
    assert operation(client).status_code == 200
    assert len(snapshot(target)['hub_investment_operations']) == 1


@pytest.mark.parametrize('phase', ['receipt', 'audit'])
def test_database_failure_rolls_back_holding_receipt_and_audit(hub, phase):
    client, target = hub
    table = 'hub_investment_operations' if phase == 'receipt' else 'audit'
    with closing(sqlite3.connect(target)) as con:
        con.execute(f"CREATE TRIGGER fail_operation BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        con.commit()
    before = snapshot(target)
    with pytest.raises(sqlite3.IntegrityError):
        create(client)
    assert snapshot(target) == before
    assert operation(client).status_code == 404


def test_capacity_keeps_old_results_and_rolls_back_new_writes(hub, monkeypatch):
    client, target = hub
    first = create(client).json
    before = snapshot(target)
    monkeypatch.setattr(investment_operations, 'MAX_OPERATIONS', 1)
    denied = create(client, 'b' * 32)
    assert denied.status_code == 409 and denied.json['code'] == 'operation_capacity'
    assert create(client).json == {**first, 'replayed': True}
    assert snapshot(target) == before
    monkeypatch.setattr(investment_operations, 'MAX_OPERATIONS', 2)
    with closing(sqlite3.connect(target)) as con:
        used = con.execute('SELECT sum(length(CAST(result AS BLOB))) FROM hub_investment_operations').fetchone()[0]
    monkeypatch.setattr(investment_operations, 'MAX_RESULT_STORAGE', used + 1)
    denied = create(client, 'b' * 32, name='多字节中文记录')
    assert denied.status_code == 409 and denied.json['code'] == 'operation_capacity'
    assert operation(client, 'b' * 32).status_code == 404
    assert snapshot(target) == before  # Capacity failed after apply; its business/audit rows rolled back.


def test_capacity_parallel_new_keys_cannot_overrun_limit(hub, monkeypatch):
    client, target = hub
    monkeypatch.setattr(investment_operations, 'MAX_OPERATIONS', 1)
    barrier = Barrier(2)
    def send(index):
        barrier.wait(timeout=10)
        return create(client.application.test_client(), str(index + 1) * 32)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(send, range(2)))
    assert sorted(r.status_code for r in responses) == [201, 409]
    assert next(r for r in responses if r.status_code == 409).json['code'] == 'operation_capacity'
    assert len(snapshot(target)['hub_investment_operations']) == 1
    assert len(snapshot(target)['hub_investments']) == 1


def test_success_replays_at_holding_limit_but_new_creation_rejects(hub):
    client, target = hub
    first = create(client).json
    # Populate valid synthetic existing holdings without invoking 299 unrelated HTTP writes.
    value = {k: v for k, v in first.items() if k not in {'id', 'revision', 'requestId', 'replayed'}}
    with closing(sqlite3.connect(target)) as con:
        con.executemany('INSERT INTO hub_investments(id,owner,data,updated_at) VALUES(?,?,?,?)',
                        [(f'synthetic-{i}', 'member1', json.dumps(value), '2026-09-04T00:00:00+00:00') for i in range(299)])
        con.commit()
    before = snapshot(target)
    assert create(client).json['replayed'] is True
    assert create(client, 'b' * 32).status_code == 400
    assert len(current(client).json['investments']) == 300
    assert snapshot(target) == before


def test_current_sources_mappings_tombstones_and_exact_individual_amounts(hub):
    client, _ = hub
    manual = create(client, value='', quantity='0').json
    rows = [holding(), holding(holdingKey='unknown', name='UNKNOWN', currency='EUR', value=''),
            holding(holdingKey='large', name='LARGE', currency='CNY', cost='999999999999.99', value='999999999999.99')]
    planned = preview(client, csv_payload(rows))
    assert confirm(client, planned).status_code == 200
    another = preview(client, csv_payload([holding(holdingKey='other', name='OTHER')], source='来源乙'))
    assert confirm(client, another).status_code == 200
    result = current(client).json
    assert set(result) == {'investments', 'sources'}  # No unsafe aggregate JSON numbers.
    standalone = next(r for r in result['investments'] if r['id'] == manual['id'])
    assert standalone['source'] is None and standalone['valueCents'] is None and standalone['quantity'] == '0'
    assert standalone['updatedAt'].endswith('+00:00')
    large = next(r for r in result['investments'] if r['name'] == 'LARGE')
    assert large['costCents'] == 99_999_999_999_999 and large['source']['holdingKey'] == 'large'
    source = next(s for s in result['sources'] if s['sourceName'] == planned.json['sourceName'])
    assert source['holdingCount'] == 3 and source['deletedCount'] == 0 and source['revision'] == 1
    assert client.delete(URL + '/' + large['id'], json={'revision': 1, 'requestId': 'c' * 32}).status_code == 200
    after = current(client).json
    source = next(s for s in after['sources'] if s['sourceName'] == planned.json['sourceName'])
    assert source['holdingCount'] == 2 and source['deletedCount'] == 1
    replay = receipt(client, planned)
    assert replay.status_code == 200 and replay.json['created'] == 3 and replay.json['replayed'] is True
    assert len(after['investments']) == 4  # Reading the original receipt does not resurrect its deleted row.


@pytest.mark.parametrize('amount', ['1,23', '1，23', '12,34.56', '1,234，567.89', '1e2', '-1', '+1', 'NaN', 'Infinity', '1.001', True, None])
def test_manual_investment_amount_rejects_ambiguity(hub, amount):
    client, target = hub
    before = snapshot(target)
    assert create(client, cost=amount).status_code == 400
    assert snapshot(target) == before


@pytest.mark.parametrize('amount,expected', [('1,234.56', 123456), ('1，234.56', 123456), ('¥ 1,234.56', 123456),
                                            ('0', 0), ('1000000000000.00', 100_000_000_000_000), (12.5, 1250)])
def test_manual_investment_amount_preserves_valid_grouping(hub, amount, expected):
    client, _ = hub
    response = create(client, cost=amount)
    assert response.status_code == 201 and response.json['costCents'] == expected
    # The unrelated manual ledger/financial cents parser was not silently changed.
    assert finance_hub.cents('1,23') == 12300


def test_import_receipt_exact_lookup_expiry_and_changed_record(hub, monkeypatch):
    client, target = hub
    planned = preview(client)
    assert receipt(client, planned).status_code == 404
    accepted = confirm(client, planned).json
    found = receipt(client, planned)
    assert found.json == {**accepted, 'replayed': True, 'sourceName': planned.json['sourceName'], 'sourceDigest': planned.json['sourceDigest']}
    assert receipt(client, planned, sourceName='OTHER').status_code == 404
    assert receipt(client, planned, sourceDigest='f' * 64).status_code == 404
    with closing(sqlite3.connect(target)) as con:
        con.execute('UPDATE hub_investment_import_previews SET expires_at=0')
        con.commit()
    before = snapshot(target)
    assert receipt(client, planned).json == found.json
    assert snapshot(target) == before
    assert confirm(client, planned).status_code == 409
    assert 'previewToken' not in found.get_data(as_text=True)


@pytest.mark.parametrize('query', [{}, {'sourceName': 'x'}, {'sourceName': 'x', 'sourceDigest': 'A' * 64},
                                 {'sourceName': 'x', 'sourceDigest': 'a' * 63},
                                 {'sourceName': 'x', 'sourceDigest': 'a' * 64, 'owner': 'member1'},
                                 [('sourceName', 'x'), ('sourceName', 'y'), ('sourceDigest', 'a' * 64)]])
def test_import_receipt_query_must_be_unambiguous(hub, query):
    client, _ = hub
    assert client.get(URL + '/imports/receipts', query_string=query).status_code == 400


def test_real_member_tv_csrf_and_household_isolation(app):
    first, headers = member(app)
    created = create(first, headers=headers).json
    planned = preview(first, headers=headers)
    assert confirm(first, planned, headers=headers).status_code == 200
    reads = [URL, URL + '/operations/' + KEY,
             URL + '/imports/receipts?sourceName=' + planned.json['sourceName'] + '&sourceDigest=' + planned.json['sourceDigest']]
    anonymous = app.test_client()
    assert all(anonymous.get(path).status_code == 401 for path in reads)
    other, other_headers = member(app, 2)
    assert current(other).json == {'investments': [], 'sources': []}
    assert operation(other).status_code == 404 and receipt(other, planned).status_code == 404
    assert other.patch(URL + '/' + created['id'], json=investment(revision=1, requestId=KEY), headers=other_headers).status_code == 404
    # The same request ID is independent for another owner, but never reads the first owner's result.
    second = create(other, headers=other_headers, name='SECOND_PRIVATE').json
    assert second['id'] != created['id'] and operation(other).json['result']['name'] == 'SECOND_PRIVATE'
    assert create(first, 'd' * 32).status_code == 403
    assert create(first, 'd' * 32, headers={**headers, 'Origin': 'https://invalid.example'}).status_code == 403
    tv = app.test_client()
    pair = tv.post('/api/pair/start', json={}).json
    assert first.post('/api/pair/approve', json={'code': pair['code'], 'name': 'synthetic tv', 'focus': 'member1'}, headers=headers).status_code == 200
    assert tv.post('/api/pair/poll', json={'secret': pair['secret']}).json['approved']
    assert all(tv.get(path).status_code == 403 for path in reads)
    assert 'PRIVATE_FUND' not in tv.get('/api/state').get_data(as_text=True)
    assert 'SECOND_PRIVATE' not in first.get('/api/state').get_data(as_text=True)
    child, _, space = create_space(app)
    assert child.get(space['entry']).status_code == 303
    assert child.post('/api/login', json={'username': 'member1', 'password': 'second-home-password-one'}).status_code == 200
    ch = {'X-CSRF-Token': child.get('/api/me').json['csrf']}
    assert current(child).json == {'investments': [], 'sources': []}
    assert operation(child).status_code == 404 and receipt(child, planned).status_code == 404
    assert create(child, headers=ch, name='CHILD_PRIVATE').status_code == 201
    assert operation(first).json['result']['name'] == 'PRIVATE_FUND'
    assert operation(child).json['result']['name'] == 'CHILD_PRIVATE'
    platform = app.extensions['household_platform']
    platform.cache.clear()
    assert operation(child).json['result']['name'] == 'CHILD_PRIVATE'  # Reload actual child app/database.


def test_revocation_after_request_guard_prevents_write(app, monkeypatch):
    client, headers = member(app)
    target = Path(app.config['DATA_DIR']) / 'household.sqlite3'
    original = finance_hub.clean
    once = [False]
    def revoke_during_normalization(value, *args, **kwargs):
        if not once[0]:
            once[0] = True
            with closing(sqlite3.connect(target)) as con:
                con.execute("UPDATE member_sessions SET revoked_at=1 WHERE owner='member1'")
                con.commit()
        return original(value, *args, **kwargs)
    monkeypatch.setattr(finance_hub, 'clean', revoke_during_normalization)
    response = create(client, headers=headers)
    assert response.status_code == 401
    with closing(sqlite3.connect(target)) as con:
        assert con.execute('SELECT count(*) FROM hub_investments').fetchone()[0] == 0
        assert con.execute('SELECT count(*) FROM hub_investment_operations').fetchone()[0] == 0


@pytest.mark.parametrize('endpoint', ['holdings', 'operation', 'import_receipt'])
def test_real_revocation_after_record_read_is_seen_outside_snapshot(app, monkeypatch, endpoint):
    client, headers = member(app)
    created = create(client, headers=headers)
    assert created.status_code == 201
    planned = preview(client, headers=headers)
    accepted = confirm(client, planned, headers=headers)
    assert accepted.status_code == 200
    target = Path(app.config['DATA_DIR']) / 'household.sqlite3'
    needle = accepted.json['receiptId'] if endpoint == 'import_receipt' else 'PRIVATE_FUND'
    original = json.loads
    revoked = [False]
    def decode_then_revoke(raw, *args, **kwargs):
        result = original(raw, *args, **kwargs)
        if not revoked[0] and isinstance(raw, str) and needle in raw:
            # Actual WAL writer commits while the reader retains its old
            # snapshot; a second identity check within that snapshot is stale.
            with closing(sqlite3.connect(target)) as con:
                con.execute("UPDATE member_sessions SET revoked_at=1 WHERE owner='member1'")
                con.commit()
            revoked[0] = True
        return result
    monkeypatch.setattr(json, 'loads', decode_then_revoke)
    response = current(client) if endpoint == 'holdings' else operation(client) if endpoint == 'operation' else receipt(client, planned)
    assert revoked[0]
    assert response.status_code == 401
    assert needle not in response.get_data(as_text=True)
    with closing(sqlite3.connect(target)) as con:
        assert con.execute("SELECT count(*) FROM member_sessions WHERE owner='member1' AND revoked_at=1").fetchone()[0] >= 1
        assert con.execute('SELECT count(*) FROM hub_investment_operations').fetchone()[0] == 1
