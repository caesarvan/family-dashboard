"""Synthetic real HTTP/SQLite allocation, replay and source drift checks."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
import json
from pathlib import Path
import secrets
import socket
import sqlite3

import pytest
from itsdangerous.timed import TimestampSigner

import journey_finance as jf
from app import create_app
from test_app import app, member
from test_journey_documents import create_journey, clone
from test_shopping_settlement import record, records, reconcile, shopping, settle

P = jf.PREFIX
TABLES = ('hub_journey_allocations', 'hub_journey_allocation_operations')


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError('Synthetic allocation tests cannot contact a network')
    monkeypatch.setattr(socket.socket, 'connect', deny)


@contextmanager
def database(app):
    with closing(sqlite3.connect(Path(app.config['DATA_DIR']) / 'household.sqlite3', timeout=10)) as con:
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON')
        with con:
            yield con


def protected(app):
    with database(app) as con:
        result = {t: [tuple(r) for r in con.execute('SELECT * FROM ' + t + ' ORDER BY 1')]
                  for t in ('entities', 'journey_workflows', 'journey_links', 'journey_actions',
                            'hub_transactions', 'hub_reconciliations', 'hub_shopping_settlements', 'hub_budgets')}
        result['finance'] = tuple(con.execute("SELECT * FROM settings WHERE id='finance'").fetchone())
        return result


def setup(app):
    client, headers = member(app)
    journey = create_journey(client, headers)
    pay = record(client, headers, 'PRIVATE_SYNTHETIC_TRAVEL_PAYMENT')
    return client, headers, journey, pay


def apply_plan(journey, pay, amount=7000):
    return {'operation': 'apply', 'journeyId': journey['id'], 'journeyRevision': 1,
            'tripRevision': 1, 'paymentId': pay['id'], 'paymentRevision': pay['revision'], 'amountCents': amount}


def preview(client, headers, plan):
    return client.post(P + '/preview', json=plan, headers=headers)


def request_body(client, headers, plan):
    p = preview(client, headers, plan)
    assert p.status_code == 200, p.json
    return {'requestId': secrets.token_hex(16), 'previewToken': p.json['previewToken']}


def confirm(client, headers, payload):
    return client.post(P + '/confirm', json=payload, headers=headers)


def create(client, headers, journey, pay, amount=7000):
    value = request_body(client, headers, apply_plan(journey, pay, amount))
    r = confirm(client, headers, value)
    assert r.status_code == 200, r.json
    return r.json['receipt'], value


def listing(client, **query):
    r = client.get(P, query_string=query)
    assert r.status_code == 200, r.json
    return r.json


def update_plan(link, amount, payment_revision=1, journey_revision=1, trip_revision=1):
    return {'operation': 'update', 'allocationId': link['allocationId'], 'revision': link['revision'],
            'journeyRevision': journey_revision, 'tripRevision': trip_revision,
            'paymentRevision': payment_revision, 'amountCents': amount}


def test_real_preview_confirmation_receipt_restart_and_no_original_mutation(app):
    c, h, j, p = setup(app)
    before = protected(app)
    payload = request_body(c, h, apply_plan(j, p))
    with database(app) as con:
        assert all(con.execute('SELECT count(*) FROM '+t).fetchone()[0] == 0 for t in TABLES)
    result = confirm(c, h, payload)
    assert result.status_code == 200 and result.json['replayed'] is False
    receipt = result.json['receipt']
    assert set(receipt) == {'requestId', 'operation', 'allocationId', 'revision', 'completedAt'}
    page = listing(c, journeyId=j['id'])
    assert page['summary'] == {'currency': 'CNY', 'coverage': 'owner_partial', 'currentAllocatedCents': 7000,
        'currentCount': 1, 'needsReviewAllocatedCents': 0, 'needsReviewCount': 0, 'activeAllocatedCents': 7000, 'sharedBudgetCents': 100000}
    assert page['allocations'][0]['state'] == 'current'
    assert confirm(c, h, payload).json == {**result.json, 'replayed': True}
    restarted = create_app(dict(app.config))
    reopened = clone(restarted, c)
    assert reopened.get(P + '/operations/' + payload['requestId']).json['receipt'] == receipt
    assert confirm(reopened, h, payload).json['replayed'] is True
    assert protected(app) == before
    with database(app) as con:
        assert con.execute('SELECT count(*) FROM hub_journey_allocation_operations').fetchone()[0] == 1
        assert con.execute("SELECT count(*) FROM audit WHERE action='finance.journey.apply'").fetchone()[0] == 1
    missing = c.get(P + '/operations/' + 'f' * 32)
    assert missing.status_code == 200 and missing.json['found'] is False and missing.json['receipt'] is None


def test_order_and_shopping_are_not_added_or_deducted_from_travel_net(app):
    c, h, j, p = setup(app)
    order = record(c, h, 'SYNTHETIC_ORDER', kind='orders')
    reconcile(c, h, 'order_payment', order, p, '100.00')
    settle(c, h, p, shopping(c, h), 10000)
    p = next(r for r in c.get(P + '/payments', query_string={'journeyId': j['id']}).json['payments'] if r['id'] == p['id'])
    before = protected(app)
    create(c, h, j, p, 10000)
    assert listing(c, journeyId=j['id'])['summary']['currentAllocatedCents'] == 10000
    assert protected(app) == before
    assert preview(c, h, apply_plan(j, order)).status_code == 404


@pytest.mark.parametrize('flow,currency,reason', [('refund', 'CNY', 'not_expense'), ('income', 'CNY', 'not_expense'),
    ('transfer', 'CNY', 'not_expense'), ('unknown', 'CNY', 'not_expense'), ('expense', 'USD', 'unsupported_currency')])
def test_noneligible_payment_reason_and_no_write(app, flow, currency, reason):
    c, h = member(app); j = create_journey(c, h)
    p = record(c, h, flow=flow, currency=currency)
    page = c.get(P + '/payments', query_string={'journeyId': j['id']})
    assert page.status_code == 200 and page.json['payments'][0]['reasonCode'] == reason
    assert preview(c, h, apply_plan(j, p)).json['code'] == 'journey_finance_ineligible'


@pytest.mark.parametrize('amount', [True, 1.5, '100', 0, -1, 100000000001])
def test_amount_is_strict_integer_cents(app, amount):
    c, h, j, p = setup(app)
    assert preview(c, h, apply_plan(j, p, amount)).status_code == 400


def test_refund_drift_preserves_reservation_until_explicit_update(app):
    c, h, j, p = setup(app)
    receipt, _ = create(c, h, j, p, 7000)
    refund = record(c, h, 'SYNTHETIC_REFUND', '40.00', flow='refund')
    reconcile(c, h, 'refund_payment', refund, p, '40.00')
    page = listing(c, journeyId=j['id'])
    assert page['summary']['currentAllocatedCents'] == 0
    assert page['summary']['needsReviewAllocatedCents'] == 7000
    assert {'source_changed', 'payment_overallocated'} <= set(page['allocations'][0]['reasonCodes'])
    p = page['allocations'][0]['payment']
    other = create_journey(c, h, 'SYNTHETIC_SECOND')
    assert preview(c, h, apply_plan(other, p, 1)).json['code'] == 'journey_finance_capacity'
    before = protected(app)
    r = confirm(c, h, request_body(c, h, update_plan(receipt, 6000, payment_revision=p['revision'])))
    assert r.status_code == 200 and r.json['receipt']['revision'] == 2
    row = listing(c, journeyId=j['id'])['allocations'][0]
    assert row['state'] == 'current' and row['acceptedNetCents'] == 6000 and row['acceptedRefundedCents'] == 4000
    assert protected(app) == before


def test_duplicate_drift_and_deleted_target_can_be_revoked_without_recreating(app):
    c, h, j, p = setup(app)
    receipt, old = create(c, h, j, p)
    keeper = record(c, h, 'SYNTHETIC_KEEPER')
    reconcile(c, h, 'duplicate', p, keeper)
    row = listing(c)['allocations'][0]
    assert 'source_ineligible' in row['reasonCodes'] and row['payment']['reasonCode'] == 'duplicate'
    assert c.delete('/api/items/trips/' + j['tripId'], json={'revision': 1}, headers=h).status_code == 200
    row = listing(c)['allocations'][0]
    assert row['journey'] is None and 'journey_missing' in row['reasonCodes']
    assert c.get(P, query_string={'journeyId': j['id']}).status_code == 404
    before = protected(app)
    revoke = request_body(c, h, {'operation': 'revoke', 'allocationId': receipt['allocationId'], 'revision': 1})
    assert confirm(c, h, revoke).status_code == 200
    assert confirm(c, h, old).json['replayed'] is True
    history = listing(c, status='all')['allocations'][0]
    assert history['status'] == 'revoked' and history['amountCents'] == 7000
    assert protected(app) == before


def test_source_deleted_and_new_token_replay_conflict(app):
    c, h, j, p = setup(app)
    receipt, old = create(c, h, j, p)
    new_token = request_body(c, h, update_plan(receipt, 6000))['previewToken']
    assert confirm(c, h, {**old, 'previewToken': new_token}).json['code'] == 'journey_finance_request_conflict'
    assert c.delete('/api/finance-hub/transactions/' + p['id'], json={'revision': p['revision']}, headers=h).status_code == 200
    row = listing(c, paymentId=p['id'])['allocations'][0]
    assert row['payment'] is None and 'source_missing' in row['reasonCodes']
    assert confirm(c, h, old).json['replayed'] is True
    assert confirm(c, h, request_body(c, h, {'operation': 'revoke', 'allocationId': receipt['allocationId'], 'revision': 1})).status_code == 200


def test_expired_saved_receipt_replays_but_unsaved_preview_rejects(app, monkeypatch):
    c, h, j, p = setup(app)
    receipt, committed = create(c, h, j, p)
    pending = request_body(c, h, update_plan(receipt, 5000))
    old_clock = TimestampSigner.get_timestamp
    monkeypatch.setattr(TimestampSigner, 'get_timestamp', lambda self: old_clock(self) + 601)
    assert confirm(c, h, committed).json['replayed'] is True
    assert c.get(P + '/operations/' + committed['requestId']).json['found'] is True
    rejected = confirm(c, h, pending)
    assert rejected.status_code == 409 and rejected.json['code'] == 'journey_finance_preview_expired'


def test_parallel_different_journeys_cannot_overallocate_same_payment(app):
    c, h, j, p = setup(app)
    other = create_journey(c, h, 'SYNTHETIC_SECOND')
    bodies = [request_body(c, h, apply_plan(target, p)) for target in (j, other)]
    clients = [clone(app, c), clone(app, c)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda pair: confirm(pair[0], h, pair[1]), zip(clients, bodies)))
    assert sorted(r.status_code for r in results) == [200, 409]
    with database(app) as con:
        assert con.execute('SELECT sum(amount_cents) FROM hub_journey_allocations').fetchone()[0] == 7000


def test_parallel_same_request_commits_once_and_duplicate_pair_rejects(app):
    c, h, j, p = setup(app)
    payload = request_body(c, h, apply_plan(j, p))
    clients = [clone(app, c), clone(app, c)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda client: confirm(client, h, payload), clients))
    assert all(r.status_code == 200 for r in results)
    assert sorted(r.json['replayed'] for r in results) == [False, True]
    assert preview(c, h, apply_plan(j, p, 1)).json['code'] == 'journey_finance_active_exists'


def test_previews_bind_versions_source_and_reservations_but_revoke_ignores_source(app):
    c, h, j, p = setup(app)
    waiting = request_body(c, h, apply_plan(j, p))
    assert c.patch('/api/finance-hub/transactions/' + p['id'], json={'revision': 1, 'category': '餐饮'}, headers=h).status_code == 200
    assert confirm(c, h, waiting).json['code'] == 'journey_finance_stale'
    p['revision'] = 2
    receipt, _ = create(c, h, j, p)
    token = request_body(c, h, {'operation': 'revoke', 'allocationId': receipt['allocationId'], 'revision': 1})
    assert c.patch('/api/items/trips/' + j['tripId'], json={'revision': 1, 'budget': 90000, 'title': 'CHANGED_TITLE'}, headers=h).status_code == 200
    row = listing(c)['allocations'][0]
    assert row['state'] == 'current' and row['journey']['sharedBudgetCents'] == 90000
    assert c.patch('/api/finance-hub/transactions/' + p['id'], json={'revision': 2, 'category': '住宿'}, headers=h).status_code == 200
    assert confirm(c, h, token).status_code == 200


def test_pagination_summary_all_pages_and_focus_not_appended(app):
    c, h, j, p = setup(app)
    receipt, _ = create(c, h, j, p)
    # Real stored rows exercise read pagination independently of repeated costly login/import.
    with database(app) as con:
        original = dict(con.execute('SELECT * FROM hub_journey_allocations').fetchone())
        original_payment = dict(con.execute('SELECT * FROM hub_transactions WHERE id=?', (p['id'],)).fetchone())
        for i in range(42):
            pid = f'synthetic-extra-{i:02d}'
            row = {**original_payment, 'id': pid, 'fingerprint': pid}
            con.execute('INSERT INTO hub_transactions('+','.join(row)+') VALUES('+','.join('?' for _ in row)+')', tuple(row.values()))
            state = jf.load(con, 'member1')
            allocation = {**original, 'id': f'{i:032x}', 'payment_id': pid, 'amount_cents': 1, 'source_digest': jf.source_digest(state, pid)}
            con.execute('INSERT INTO hub_journey_allocations('+','.join(allocation)+') VALUES('+','.join('?' for _ in allocation)+')', tuple(allocation.values()))
    pages = [listing(c, journeyId=j['id'], page=n) for n in (0, 1)]
    assert [len(x['allocations']) for x in pages] == [40, 3]
    assert all(x['summary']['currentAllocatedCents'] == 7042 for x in pages)
    paypage = c.get(P + '/payments', query_string={'journeyId': j['id'], 'allocationId': receipt['allocationId'], 'q': 'NO_MATCH'}).json
    assert paypage['payments'] == [] and paypage['focus']['id'] == p['id'] and paypage['focus']['reservedCents'] == 0


def test_receipt_capacity_reserves_revoke_and_replay_survives_capacity(app, monkeypatch):
    c, h, j, p = setup(app)
    monkeypatch.setattr(jf, 'MAX_OPERATIONS', 2)
    receipt, old = create(c, h, j, p)
    update = request_body(c, h, update_plan(receipt, 6000))
    assert confirm(c, h, update).json['code'] == 'journey_finance_storage_limit'
    assert confirm(c, h, old).json['replayed'] is True
    revoke = request_body(c, h, {'operation': 'revoke', 'allocationId': receipt['allocationId'], 'revision': 1})
    assert confirm(c, h, revoke).status_code == 200
    assert listing(c)['allocations'] == []


def test_request_fields_and_legacy_trip_are_not_silently_accepted(app):
    c, h, j, p = setup(app)
    assert preview(c, h, {**apply_plan(j, p), 'owner': 'member2'}).status_code == 400
    assert c.get(P + '?page=0&page=1').status_code == 400
    assert c.get(P + '?journeyId=' + j['id'] + '&paymentId=' + p['id']).status_code == 400
    assert c.get(P + '/payments?journeyId=' + j['tripId']).status_code == 404
    assert preview(c, {}, apply_plan(j, p)).status_code == 403
    assert preview(c, {**h, 'Origin': 'https://outside.invalid'}, apply_plan(j, p)).status_code == 403
    assert c.get(P).headers['Cache-Control'].find('no-store') >= 0


def test_schema_exact_new_tables_and_atomic_initialization(app):
    with database(app) as con:
        names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        assert len(names) == 75 and set(TABLES) <= names
        assert not any(r[2] in {'journey_workflows', 'entities', 'hub_transactions'} for r in con.execute('PRAGMA foreign_key_list(hub_journey_allocations)'))
    with closing(sqlite3.connect(':memory:')) as con:
        con.execute('PRAGMA foreign_keys=ON')
        con.execute('CREATE TABLE users(id TEXT PRIMARY KEY)')
        con.execute('BEGIN IMMEDIATE')
        jf.init_schema(con)
        con.rollback()
        assert con.execute("SELECT count(*) FROM sqlite_master WHERE name LIKE 'hub_journey_%'").fetchone()[0] == 0


@pytest.mark.parametrize('damage', ['negative_net', 'boolean_amount', 'string_amount'])
def test_bad_source_is_reviewable_and_revocable_without_blocking_other_history(app, damage):
    c, h, j, p = setup(app)
    receipt, _ = create(c, h, j, p)
    other = record(c, h, 'OTHER_HEALTHY_PAYMENT')
    create(c, h, j, other, 2000)
    if damage == 'negative_net':
        refund = record(c, h, 'SYNTHETIC_REFUND', '40.00', flow='refund')
        relation = reconcile(c, h, 'refund_payment', refund, p, '40.00')
        with database(app) as con:
            con.execute('UPDATE hub_reconciliations SET amount_cents=11000 WHERE id=?', (relation['id'],))
    else:
        with database(app) as con:
            value = json.loads(con.execute('SELECT data FROM hub_transactions WHERE id=?', (p['id'],)).fetchone()[0])
            value['amountCents'] = True if damage == 'boolean_amount' else '10000'
            con.execute('UPDATE hub_transactions SET data=? WHERE id=?', (json.dumps(value), p['id']))
    page = listing(c, journeyId=j['id'])
    bad = next(r for r in page['allocations'] if r['id'] == receipt['allocationId'])
    assert bad['state'] == 'needs_review' and bad['payment'] is None and 'source_ineligible' in bad['reasonCodes']
    assert page['summary']['currentAllocatedCents'] == 2000
    assert preview(c, h, update_plan(receipt, 1)).json['code'] == 'journey_finance_ineligible'
    revoke = request_body(c, h, {'operation': 'revoke', 'allocationId': receipt['allocationId'], 'revision': 1})
    assert confirm(c, h, revoke).status_code == 200
    assert listing(c, status='all')['allocations']


def test_broken_trip_backreference_does_not_attach_other_journey_budget(app):
    c, h, j, p = setup(app)
    receipt, _ = create(c, h, j, p)
    with database(app) as con:
        value = json.loads(con.execute('SELECT data FROM entities WHERE id=?', (j['tripId'],)).fetchone()[0])
        value['journeyId'] = 'f' * 24
        con.execute('UPDATE entities SET data=? WHERE id=?', (json.dumps(value), j['tripId']))
    assert c.get(P, query_string={'journeyId': j['id']}).status_code == 404
    row = listing(c)['allocations'][0]
    assert row['journey'] is None and 'journey_missing' in row['reasonCodes']
    assert confirm(c, h, request_body(c, h, {'operation': 'revoke', 'allocationId': receipt['allocationId'], 'revision': 1})).status_code == 200


def test_receipt_byte_capacity_keeps_reserved_revoke_space(app, monkeypatch):
    c, h, j, p = setup(app)
    receipt, _ = create(c, h, j, p)
    with database(app) as con:
        used = con.execute('SELECT sum(length(CAST(result AS BLOB))) FROM hub_journey_allocation_operations').fetchone()[0]
    monkeypatch.setattr(jf, 'MAX_OPERATION_BYTES', used + jf.RECEIPT_RESERVE)
    assert confirm(c, h, request_body(c, h, update_plan(receipt, 1))).json['code'] == 'journey_finance_storage_limit'
    assert confirm(c, h, request_body(c, h, {'operation': 'revoke', 'allocationId': receipt['allocationId'], 'revision': 1})).status_code == 200
