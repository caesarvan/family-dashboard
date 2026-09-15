"""Synthetic real-Flask settlement flows; no personal files/provider calls."""
import csv
import io
import json
import socket
import sqlite3
from pathlib import Path

import pytest

from test_app import app, member
from test_household_spaces import create_space
from shopping_settlement import PREFIX, export_owned_settlements


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('This test must not use the network')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)


def database(app):
    con = sqlite3.connect(Path(app.config['DATA_DIR']) / 'household.sqlite3')
    con.row_factory = sqlite3.Row
    return con


def records(client, headers, rows=None, *, kind='payments', currency='CNY', flow='expense'):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['date', 'title', 'amount', 'currency', 'flow', 'category', 'id', 'status'])
    for title, value in rows or [('SYNTHETIC_PAYMENT', '100.00')]:
        writer.writerow(['2026-09-01', title, value, currency, flow, '购物', title, '成功'])
    payload = {'source': 'generic', 'kind': kind, 'csv': output.getvalue()}
    preview = client.post('/api/finance-hub/imports/preview', json=payload, headers=headers)
    assert preview.status_code == 200, preview.json
    confirm = client.post('/api/finance-hub/imports/confirm', json={**payload, 'previewToken': preview.json['previewToken']}, headers=headers)
    assert confirm.status_code == 200, confirm.json
    return client.get('/api/finance-hub/overview?month=2026-09').json['transactions']


def record(client, headers, title='SYNTHETIC_PAYMENT', amount='100.00', **kwargs):
    return next(r for r in records(client, headers, [(title, amount)], **kwargs) if r['title'] == title)


def shopping(client, headers, **fields):
    response = client.post('/api/items/shopping', json={'title': 'SYNTHETIC_SHOPPING', 'budget': 18000, **fields}, headers=headers)
    assert response.status_code == 201, response.json
    return item(client, response.json['id'])


def item(client, rid):
    return next(r for r in client.get('/api/state').json['shopping'] if r['id'] == rid)


def context(client, **query):
    response = client.get(PREFIX + '/context', query_string=query)
    assert response.status_code == 200, response.json
    return response.json


def plan(pay, shop, amount=10000, done=True):
    return {'operation': 'apply', 'paymentId': pay['id'], 'shoppingId': shop['id'],
            'shoppingRevision': shop['revision'], 'amountCents': amount, 'done': done}


def preview(client, headers, value):
    return client.post(PREFIX + '/preview', json=value, headers=headers)


def confirm(client, headers, proposal):
    assert proposal.status_code == 200, proposal.json
    return client.post(PREFIX + '/confirm', json={'previewToken': proposal.json['previewToken']}, headers=headers)


def settle(client, headers, pay, shop, amount=10000, done=True):
    result = confirm(client, headers, preview(client, headers, plan(pay, shop, amount, done)))
    assert result.status_code == 200, result.json
    return result.json


def revoke_plan(link, revision, mode='detach_keep_current'):
    return {'operation': 'revoke', 'linkId': link['id'], 'revision': link['revision'],
            'shoppingRevision': revision, 'mode': mode}


def reconcile(client, headers, kind, left, right, amount=None):
    payload = {'kind': kind, 'leftId': left['id'], 'rightId': right['id']}
    if amount is not None:
        payload['amount'] = amount
    p = client.post('/api/finance-hub/reconciliation/preview', json=payload, headers=headers)
    assert p.status_code == 200, p.json
    r = client.post('/api/finance-hub/reconciliation/confirm', json={'previewToken': p.json['previewToken']}, headers=headers)
    assert r.status_code == 200, r.json
    return r.json['relation']


def protected_rows(app):
    with database(app) as con:
        result = {table: [tuple(r) for r in con.execute('SELECT * FROM ' + table + ' ORDER BY rowid')]
                  for table in ('hub_transactions', 'hub_reconciliations', 'hub_imports', 'hub_budgets',
                                'hub_investments', 'private_finance', 'finance_baselines')}
        result['finance'] = tuple(con.execute("SELECT * FROM settings WHERE id='finance'").fetchone())
    return result


def test_preview_confirm_replace_only_shared_fields_and_replay(app):
    client, headers = member(app)
    pay = record(client, headers, title='PRIVATE_SYNTHETIC_MERCHANT_ID')
    shop = shopping(client, headers, actual=2300, done=False, note='KEEP_NOTE', quantity='2 件')
    baseline = protected_rows(app)
    state = client.get('/api/state').json
    p = preview(client, headers, plan(pay, shop, 7000, False))
    assert p.status_code == 200 and p.json['before']['actual'] == 2300 and p.json['after']['actual'] == 7000
    assert p.json['sharing'] == {'fields': ['actual', 'done'], 'ledgerUnchanged': True}
    with database(app) as con:
        assert con.execute('SELECT count(*) FROM hub_shopping_settlements').fetchone()[0] == 0
        assert con.execute('SELECT count(*) FROM hub_shopping_settlement_receipts').fetchone()[0] == 0
    assert item(client, shop['id']) == shop
    assert protected_rows(app) == baseline
    result = confirm(client, headers, p)
    assert result.status_code == 200 and result.json['changedFields'] == ['actual']
    current = item(client, shop['id'])
    assert current == {**shop, 'revision': shop['revision'] + 1, 'actual': 7000}
    assert protected_rows(app) == baseline
    assert client.get('/api/state').json['finance'] == state['finance']
    assert 'PRIVATE_SYNTHETIC_MERCHANT_ID' not in client.get('/api/state').get_data(as_text=True)
    assert confirm(client, headers, p).json['replayed'] is True
    assert item(client, shop['id']) == current
    with database(app) as con:
        assert con.execute('SELECT count(*) FROM hub_shopping_settlement_receipts').fetchone()[0] == 1


def test_partial_refund_uses_only_confirmed_allocation_and_does_not_double_count_orders(app):
    client, headers = member(app)
    pay = record(client, headers)
    order = record(client, headers, 'SYNTHETIC_ORDER', kind='orders')
    refund = record(client, headers, 'SYNTHETIC_REFUND', '40.00', flow='refund')
    reconcile(client, headers, 'order_payment', order, pay, '100.00')
    reconcile(client, headers, 'refund_payment', refund, pay, '30.00')
    shop = shopping(client, headers)
    source = next(r for r in context(client, transactionId=order['id'])['payments'] if r['id'] == pay['id'])
    assert source['netCents'] == 7000 and source['availableCents'] == 7000
    assert preview(client, headers, plan(order, shop)).status_code == 400
    assert preview(client, headers, plan(pay, shop, 7001)).status_code == 400
    baseline = protected_rows(app)
    settle(client, headers, pay, shop, 7000)
    assert protected_rows(app) == baseline
    assert item(client, shop['id'])['actual'] == 7000


@pytest.mark.parametrize('currency,flow,kind', [('USD', 'expense', 'payments'), ('CNY', 'transfer', 'payments'),
                                            ('CNY', 'refund', 'payments'), ('CNY', 'expense', 'orders')])
def test_ineligible_sources_never_project(app, currency, flow, kind):
    client, headers = member(app)
    pay = record(client, headers, currency=currency, flow=flow, kind=kind)
    shop = shopping(client, headers)
    assert preview(client, headers, plan(pay, shop)).status_code == 400
    assert item(client, shop['id']) == shop


def test_duplicate_source_and_unmatched_order_are_not_payment_candidates(app):
    client, headers = member(app)
    pay = record(client, headers)
    duplicate = record(client, headers, 'SYNTHETIC_DUPLICATE')
    order = record(client, headers, 'UNMATCHED_ORDER', kind='orders')
    reconcile(client, headers, 'duplicate', duplicate, pay)
    shop = shopping(client, headers)
    value = context(client, transactionId=duplicate['id'])
    row = next(r for r in value['payments'] if r['id'] == duplicate['id'])
    assert not row['eligible'] and row['reasonCode'] == 'duplicate'
    assert preview(client, headers, plan(duplicate, shop)).status_code == 400
    assert context(client, transactionId=order['id'])['payments'] == []


@pytest.mark.parametrize('value', [True, False, -1, 1.2, '100', None, 100_000_000_001, [], {}])
def test_integer_cents_are_strict_and_invalid_preview_has_no_side_effect(app, value):
    client, headers = member(app)
    pay = record(client, headers)
    shop = shopping(client, headers)
    assert preview(client, headers, plan(pay, shop, value)).status_code == 400
    assert item(client, shop['id']) == shop
    with database(app) as con:
        assert con.execute('SELECT count(*) FROM hub_shopping_settlements').fetchone()[0] == 0


@pytest.mark.parametrize('field,value', [('done', 1), ('done', 'true'), ('shoppingRevision', True), ('shoppingRevision', 0),
                                      ('paymentId', '../bad'), ('owner', 'member2')])
def test_payload_fields_and_types_are_explicit(app, field, value):
    client, headers = member(app)
    pay = record(client, headers)
    shop = shopping(client, headers)
    payload = plan(pay, shop)
    payload[field] = value
    assert preview(client, headers, payload).status_code == 400


def test_zero_and_unknown_previous_value_are_distinct_on_restore(app):
    client, headers = member(app)
    pay = record(client, headers)
    refund = record(client, headers, 'FULL_REFUND', flow='refund')
    reconcile(client, headers, 'refund_payment', refund, pay)
    shop = shopping(client, headers, actual=None)
    result = settle(client, headers, pay, shop, 0, False)
    assert result['shopping']['actual'] == 0
    p = preview(client, headers, revoke_plan(result['link'], result['shopping']['revision'], 'restore_if_unchanged'))
    assert p.json['after']['actual'] is None
    r = confirm(client, headers, p)
    assert r.status_code == 200 and r.json['link']['status'] == 'revoked'
    assert item(client, shop['id'])['actual'] is None


def test_multi_item_reservation_and_stale_second_confirmation(app):
    client, headers = member(app)
    pay = record(client, headers)
    first, second = shopping(client, headers), shopping(client, headers)
    p1, p2 = preview(client, headers, plan(pay, first, 6000)), preview(client, headers, plan(pay, second, 6000))
    a = confirm(client, headers, p1)
    assert a.status_code == 200
    assert confirm(client, headers, p2).status_code == 409
    assert preview(client, headers, plan(pay, second, 4001)).status_code == 400
    settle(client, headers, pay, second, 4000)
    assert next(r for r in context(client, transactionId=pay['id'])['payments'] if r['id'] == pay['id'])['reservedCents'] == 10000


def test_one_active_owner_target_but_partner_can_explicitly_replace_without_reading_link(app):
    a, ah = member(app)
    b, bh = member(app, 2)
    pa, pb = record(a, ah, 'A_PRIVATE_PAYMENT'), record(b, bh, 'B_PRIVATE_PAYMENT')
    shop = shopping(a, ah)
    first = settle(a, ah, pa, shop, 6000)
    assert preview(a, ah, plan(pa, item(a, shop['id']), 1000)).status_code == 409
    assert b.get(PREFIX + '/context', query_string={'linkId': first['link']['id']}).status_code == 404
    second = settle(b, bh, pb, item(b, shop['id']), 3000)
    ca, cb = context(a, linkId=first['link']['id']), context(b, linkId=second['link']['id'])
    assert ca['links'][0]['reviewReasons'] == ['shopping_changed']
    assert 'A_PRIVATE_PAYMENT' not in json.dumps(cb)
    assert all(r['id'] != second['link']['id'] for r in ca['links'])
    assert all(r['id'] != first['link']['id'] for r in cb['links'])
    assert preview(a, ah, revoke_plan(first['link'], second['shopping']['revision'], 'restore_if_unchanged')).status_code == 409
    assert confirm(a, ah, preview(a, ah, revoke_plan(first['link'], second['shopping']['revision']))).status_code == 200
    assert item(b, shop['id'])['actual'] == 3000


def test_update_restores_latest_before_value_and_does_not_overwrite_later_edits(app):
    client, headers = member(app)
    pay = record(client, headers)
    shop = shopping(client, headers, actual=1000)
    original = settle(client, headers, pay, shop, 6000)
    assert client.patch('/api/items/shopping/' + shop['id'], json={'revision': original['shopping']['revision'], 'actual': 4500, 'note': 'LATER_NOTE'}, headers=headers).status_code == 200
    edited = item(client, shop['id'])
    update = {'operation': 'update', 'linkId': original['link']['id'], 'revision': original['link']['revision'],
              'shoppingRevision': edited['revision'], 'amountCents': 7000, 'done': True}
    changed = confirm(client, headers, preview(client, headers, update))
    assert changed.status_code == 200
    p = preview(client, headers, revoke_plan(changed.json['link'], changed.json['shopping']['revision'], 'restore_if_unchanged'))
    assert p.json['after']['actual'] == 4500
    assert confirm(client, headers, p).status_code == 200
    assert item(client, shop['id'])['actual'] == 4500 and item(client, shop['id'])['note'] == 'LATER_NOTE'


def test_source_changed_and_deleted_links_can_detach_without_rebuilding(app):
    client, headers = member(app)
    pay = record(client, headers)
    shop = shopping(client, headers)
    p = preview(client, headers, plan(pay, shop))
    result = confirm(client, headers, p).json
    current = next(r for r in client.get('/api/finance-hub/overview?month=2026-09').json['transactions'] if r['id'] == pay['id'])
    assert client.patch('/api/finance-hub/transactions/' + pay['id'], json={'revision': current['revision'], 'flow': 'transfer'}, headers=headers).status_code == 200
    row = context(client, linkId=result['link']['id'])['links'][0]
    assert {'source_changed', 'source_ineligible'} <= set(row['reviewReasons'])
    assert item(client, shop['id'])['actual'] == 10000
    assert client.delete('/api/finance-hub/transactions/' + pay['id'], json={'revision': current['revision'] + 1}, headers=headers).status_code == 200
    row = context(client, linkId=result['link']['id'])['links'][0]
    assert row['reviewReasons'] == ['source_missing']
    assert client.delete('/api/items/shopping/' + shop['id'], json={'revision': result['shopping']['revision']}, headers=headers).status_code == 200
    revoke = confirm(client, headers, preview(client, headers, revoke_plan(result['link'], None)))
    assert revoke.status_code == 200 and revoke.json['shopping'] is None
    assert confirm(client, headers, p).json['replayed'] is True
    assert context(client, linkId=result['link']['id'])['links'][0]['status'] == 'revoked'
    assert client.get('/api/state').json['shopping'] == []
    assert client.get('/api/finance-hub/overview?month=2026-09').json['transactions'] == []


def test_new_refund_invalidates_snapshot_without_touching_shopping_and_allocation_remains_reserved(app):
    client, headers = member(app)
    pay = record(client, headers)
    shop = shopping(client, headers)
    result = settle(client, headers, pay, shop)
    refund = record(client, headers, 'LATER_REFUND', '30', flow='refund')
    reconcile(client, headers, 'refund_payment', refund, pay)
    state = context(client, linkId=result['link']['id'])
    assert state['links'][0]['state'] == 'needs_review'
    source = next(r for r in state['payments'] if r['id'] == pay['id'])
    assert source['netCents'] == 7000 and source['reservedCents'] == 10000 and source['availableCents'] == 0
    assert item(client, shop['id'])['actual'] == 10000
    update = {'operation': 'update', 'linkId': result['link']['id'], 'revision': result['link']['revision'],
              'shoppingRevision': result['shopping']['revision'], 'amountCents': 7000, 'done': True}
    assert confirm(client, headers, preview(client, headers, update)).json['link']['state'] == 'current'


@pytest.mark.parametrize('change', ['target', 'source', 'delete_target', 'delete_source'])
def test_changes_after_preview_fail_atomically(app, change):
    client, headers = member(app)
    pay = record(client, headers)
    shop = shopping(client, headers)
    p = preview(client, headers, plan(pay, shop))
    if change == 'target':
        r = client.patch('/api/items/shopping/' + shop['id'], json={'revision': shop['revision'], 'title': 'LATER_TITLE'}, headers=headers)
    elif change == 'source':
        r = client.patch('/api/finance-hub/transactions/' + pay['id'], json={'revision': pay['revision'], 'category': 'LATER_CATEGORY'}, headers=headers)
    elif change == 'delete_target':
        r = client.delete('/api/items/shopping/' + shop['id'], json={'revision': shop['revision']}, headers=headers)
    else:
        r = client.delete('/api/finance-hub/transactions/' + pay['id'], json={'revision': pay['revision']}, headers=headers)
    assert r.status_code == 200
    before = protected_rows(app)
    assert confirm(client, headers, p).status_code == 409
    assert protected_rows(app) == before
    with database(app) as con:
        assert con.execute('SELECT count(*) FROM hub_shopping_settlements').fetchone()[0] == 0
        assert con.execute('SELECT count(*) FROM hub_shopping_settlement_receipts').fetchone()[0] == 0


def test_revoke_replay_does_not_detach_new_link_and_restore_conflict_preserves_draft(app):
    client, headers = member(app)
    pay = record(client, headers)
    shop = shopping(client, headers)
    first = settle(client, headers, pay, shop)
    p = preview(client, headers, revoke_plan(first['link'], first['shopping']['revision'], 'restore_if_unchanged'))
    assert client.patch('/api/items/shopping/' + shop['id'], json={'revision': first['shopping']['revision'], 'note': 'LATER'}, headers=headers).status_code == 200
    assert confirm(client, headers, p).status_code == 409
    p = preview(client, headers, revoke_plan(first['link'], item(client, shop['id'])['revision']))
    assert confirm(client, headers, p).status_code == 200
    second = settle(client, headers, pay, item(client, shop['id']), 5000)
    assert confirm(client, headers, p).json['replayed'] is True
    assert context(client, linkId=second['link']['id'])['links'][-1]['status'] == 'active'
    assert item(client, shop['id'])['actual'] == 5000


def test_real_session_csrf_owner_tv_and_cross_household_guards(app):
    a, ah = member(app)
    b, bh = member(app, 2)
    pay, shop = record(a, ah), shopping(a, ah)
    p = preview(a, ah, plan(pay, shop))
    assert app.test_client().get(PREFIX + '/context').status_code == 401
    assert b.get(PREFIX + '/context', query_string={'transactionId': pay['id']}).status_code == 404
    assert preview(b, bh, plan(pay, shop)).status_code == 404
    assert confirm(b, bh, p).status_code == 403
    assert a.post(PREFIX + '/preview', json=plan(pay, shop)).status_code == 403
    assert a.post(PREFIX + '/confirm', json={'previewToken': p.json['previewToken']}, headers={**ah, 'Origin': 'https://external.invalid'}).status_code == 403
    tv = app.test_client()
    pair = tv.post('/api/pair/start', json={}).json
    assert a.post('/api/pair/approve', json={'code': pair['code'], 'name': 'SYNTHETIC_TV', 'focus': 'member1'}, headers=ah).status_code == 200
    assert tv.post('/api/pair/poll', json={'secret': pair['secret']}).json['approved']
    assert tv.get(PREFIX + '/context').status_code == 403
    assert tv.post(PREFIX + '/preview', json=plan(pay, shop), headers=ah).status_code == 403
    assert tv.post(PREFIX + '/confirm', json={'previewToken': p.json['previewToken']}, headers=ah).status_code == 403
    child, _, invitation = create_space(app)
    assert child.get(invitation['entry']).status_code == 303
    assert child.post('/api/login', json={'username': 'member1', 'password': 'second-home-password-one'}).status_code == 200
    ch = {'X-CSRF-Token': child.get('/api/me').json['csrf']}
    assert child.get(PREFIX + '/context', query_string={'transactionId': pay['id']}).status_code == 404
    assert child.post(PREFIX + '/confirm', json={'previewToken': p.json['previewToken']}, headers=ch).status_code in {400, 403}


def test_relogin_invalidates_preview_even_for_same_member_and_revocation_is_rechecked(app):
    client, headers = member(app)
    pay, shop = record(client, headers), shopping(client, headers)
    p = preview(client, headers, plan(pay, shop))
    assert client.post('/api/logout', json={}, headers=headers).status_code == 200
    assert client.post('/api/login', json={'username': 'member1', 'password': 'testing-password-one'}).status_code == 200
    headers = {'X-CSRF-Token': client.get('/api/me').json['csrf']}
    assert confirm(client, headers, p).status_code == 403
    p = preview(client, headers, plan(pay, shop))

    def revoke_after_actor():
        from flask import request
        if request.path == PREFIX + '/confirm':
            with database(app) as con:
                con.execute("UPDATE member_sessions SET revoked_at=1 WHERE owner='member1'")
    app.before_request_funcs[None].append(revoke_after_actor)
    assert confirm(client, headers, p).status_code == 401
    with database(app) as con:
        assert con.execute('SELECT count(*) FROM hub_shopping_settlements').fetchone()[0] == 0


@pytest.mark.parametrize('query', [{'page': '-1'}, {'page': '1.0'}, {'page': 'true'}, {'q': 'x' * 81},
                                 {'q': '\n'}, {'linkId': '../bad'}, {'owner': 'member2'}])
def test_context_query_limits(app, query):
    client, _ = member(app)
    assert client.get(PREFIX + '/context', query_string=query).status_code == 400


def test_context_pagination_focus_and_export_are_bounded_and_business_only(app):
    client, headers = member(app)
    payments = records(client, headers, [(f'SYNTHETIC_{i:03}', '1.00') for i in range(85)])
    shops = [shopping(client, headers, title=f'SYNTHETIC_SHOP_{i:03}') for i in range(43)]
    first = context(client)
    assert len(first['payments']) == 40 and len(first['shopping']) == 40
    assert first['pageInfo']['paymentsMore'] and first['pageInfo']['shoppingMore']
    second = context(client, page=1)
    assert not {r['id'] for r in first['payments']} & {r['id'] for r in second['payments']}
    assert len(second['payments']) == 40 and len(second['shopping']) == 3
    focused = context(client, page=999, q='not-present', transactionId=payments[0]['id'], shoppingId=shops[0]['id'])
    assert [r['id'] for r in focused['payments']] == [payments[0]['id']]
    assert [r['id'] for r in focused['shopping']] == [shops[0]['id']]
    result = settle(client, headers, payments[0], shops[0], 100)
    focus = context(client, linkId=result['link']['id'], page=999, q='not-present')
    assert len(focus['links']) == len(focus['payments']) == len(focus['shopping']) == 1
    with database(app) as con:
        exported = export_owned_settlements(con, 'member1')
        other = export_owned_settlements(con, 'member2')
    assert exported['links'][0]['id'] == result['link']['id']
    assert len(exported['receipts']) == 1 and other == {'links': [], 'receipts': []}
    assert not any(key in json.dumps(exported) for key in ('nonce', 'context', 'source_digest', 'previewToken', 'credential'))


def test_confirm_requires_original_untampered_explicit_preview(app):
    client, headers = member(app)
    pay, shop = record(client, headers), shopping(client, headers)
    p = preview(client, headers, plan(pay, shop))
    for payload in ({}, {'previewToken': 'invalid'}, {'previewToken': p.json['previewToken'] + 'tampered'},
                    {'previewToken': p.json['previewToken'], 'amountCents': 1}):
        assert client.post(PREFIX + '/confirm', json=payload, headers=headers).status_code == 400
    assert item(client, shop['id']) == shop
