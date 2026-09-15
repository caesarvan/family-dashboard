"""Synthetic settlement -> journey/shared-state/private-ZIP integration only."""
from contextlib import closing
from copy import deepcopy
import csv
from datetime import date, timedelta
from io import StringIO
from pathlib import Path
import socket
import sqlite3

import pytest

from app import create_app
from test_app import member
from test_data_portability import unpack
from test_journey_workflows import apply as apply_journey, detail, plan, preview as preview_journey
from test_shopping_media import pair_tv, upload


PREFIX = '/api/finance-hub/shopping-settlements'


@pytest.fixture
def app(tmp_path, monkeypatch):
    def deny_network(*_args, **_kwargs):
        raise AssertionError('No external access in shopping settlement integration tests')

    monkeypatch.setattr(socket.socket, 'connect', deny_network)
    return create_app({
        'TESTING': True, 'SECRET_KEY': 'synthetic-shopping-settlement-integration',
        'DATA_DIR': str(tmp_path), 'SESSION_COOKIE_SECURE': False,
        'MEMBER1_PASSWORD': 'testing-password-one', 'MEMBER2_PASSWORD': 'testing-password-two',
        'MICROSOFT_CLIENT_ID': '', 'MICROSOFT_CLIENT_SECRET': '',
        'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': '', 'OPENAI_API_KEY': '', 'OPENAI_MODEL': '',
    })


def db_path(app):
    return Path(app.config['DATA_DIR']) / 'household.sqlite3'


def shopping(client, uid):
    return next(row for row in client.get('/api/state').json['shopping'] if row['id'] == uid)


def create_journey(client, headers):
    pending = preview_journey(client, headers, plan(saved=500000, paid=250000))
    result = apply_journey(client, headers, pending, 'synthetic-linked-shopping')
    assert result.status_code == 201, result.json
    return detail(client, result.json['id'])


def import_payment(client, headers, marker='PRIVATE_SETTLEMENT_MEMBER1', amount='100.00'):
    stream = StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(['date', 'title', 'amount', 'currency', 'flow', 'category', 'id', 'status'])
    writer.writerow(['2026-09-15', marker + '_MERCHANT', amount, 'CNY', 'expense',
                     marker + '_CATEGORY', marker + '_ORDER', '成功'])
    value = {'source': 'generic', 'kind': 'payments', 'csv': stream.getvalue()}
    pending = client.post('/api/finance-hub/imports/preview', json=value, headers=headers)
    assert pending.status_code == 200 and pending.json['previewToken'], pending.json
    result = client.post('/api/finance-hub/imports/confirm',
                         json={**value, 'previewToken': pending.json['previewToken']}, headers=headers)
    assert result.status_code == 200 and result.json['imported'] == 1, result.json
    rows = client.get('/api/finance-hub/overview?month=2026-09').json['transactions']
    return next(row for row in rows if row['externalId'] == marker + '_ORDER')


def preview_settlement(client, headers, purchase, payment, amount=7900, done=True):
    result = client.post(PREFIX + '/preview', json={
        'operation': 'apply', 'paymentId': payment['id'], 'shoppingId': purchase['id'],
        'shoppingRevision': purchase['revision'], 'amountCents': amount, 'done': done,
    }, headers=headers)
    assert result.status_code == 200 and result.json['previewToken'], result.json
    return result.json


def confirm(client, headers, pending):
    return client.post(PREFIX + '/confirm', json={'previewToken': pending['previewToken']}, headers=headers)


def settled(client, headers, purchase, payment, **options):
    pending = preview_settlement(client, headers, purchase, payment, **options)
    result = confirm(client, headers, pending)
    assert result.status_code == 200 and result.json['replayed'] is False, result.json
    return pending, result.json


def seed_finance(client, headers):
    public = client.get('/api/state').json['finance']
    public.update(wallet=123456, livingSpent=34567)
    result = client.put('/api/finance', json=public, headers=headers)
    assert result.status_code == 200, result.json
    result = client.put('/api/private-finance', json={
        'revision': 0, 'income': 500000, 'spent': 12000, 'budget': 200000, 'month': '2026-09',
    }, headers=headers)
    assert result.status_code == 200, result.json
    result = client.put('/api/finance-hub/budgets', json={
        'month': '2026-09', 'currency': 'CNY', 'category': 'total', 'amount': '5000',
    }, headers=headers)
    assert result.status_code == 200, result.json


def monetary_snapshot(app):
    with closing(sqlite3.connect(db_path(app))) as con:
        return {name: con.execute('SELECT * FROM ' + name +
                                 (" WHERE id='finance'" if name == 'settings' else '') +
                                 ' ORDER BY rowid').fetchall()
                for name in ('settings', 'private_finance', 'hub_transactions', 'hub_reconciliations', 'hub_budgets')}


def later_plan(value):
    moved = deepcopy(value)
    shift = lambda stamp: (date.fromisoformat(stamp) + timedelta(days=5)).isoformat()
    moved['start'], moved['end'] = shift(moved['start']), shift(moved['end'])
    for row in moved['destinations']:
        row['arrival'], row['departure'] = shift(row['arrival']), shift(row['departure'])
    for row in moved['segments']:
        row['start'], row['end'] = shift(row['start']), shift(row['end'])
    for row in moved['checklist']:
        row['due'] = shift(row['due'])
    return moved


@pytest.mark.parametrize('done', [False, True])
def test_settlement_reschedule_preserves_actual_done_photos_ids_and_money(app, done):
    client, headers = member(app)
    value = create_journey(client, headers)
    purchase = value['shopping'][0]
    photo = upload(client, headers)
    assert client.patch('/api/items/shopping/' + purchase['id'], json={
        'revision': purchase['revision'], 'photoIds': [photo],
    }, headers=headers).status_code == 200
    purchase = shopping(client, purchase['id'])
    payment = import_payment(client, headers)
    seed_finance(client, headers)
    baseline = monetary_snapshot(app)
    _, result = settled(client, headers, purchase, payment, done=done)
    assert result['shopping']['actual'] == 7900 and result['shopping']['done'] is done
    after = detail(client, value['id'])
    pending = preview_journey(client, headers, later_plan(after['plan']), journeyId=value['id'], revision=after['revision'])
    assert apply_journey(client, headers, pending, 'reschedule-settled-shopping').status_code == 200
    current = detail(client, value['id'])
    row = current['shopping'][0]
    assert row['id'] == purchase['id'] and row['tripId'] == value['tripId'] and row['journeyId'] == value['id']
    assert row['workflowKey'] == value['shopping'][0]['workflowKey']
    assert row['owner'] == purchase['owner'] and row['title'] == purchase['title']
    assert row['budget'] == purchase['budget'] and row['quantity'] == purchase['quantity']
    assert row['actual'] == 7900 and row['done'] is done and row['photoIds'] == [photo]
    assert current['budget']['purchaseActual'] == (7900 if done else 0)
    assert current['trip']['paid'] == 250000 and current['trip']['saved'] == 500000
    assert current['trip']['budget'] == 2000000
    assert monetary_snapshot(app) == baseline
    with closing(sqlite3.connect(db_path(app))) as con:
        assert con.execute('SELECT photo_id,entity_id FROM photo_refs').fetchall() == [(photo, purchase['id'])]
        assert con.execute("SELECT count(*) FROM entities WHERE kind='shopping'").fetchone()[0] == 1


def test_settlement_invalidates_old_journey_preview_without_partial_changes(app):
    client, headers = member(app)
    original = create_journey(client, headers)
    payment = import_payment(client, headers)
    changed = later_plan(original['plan'])
    waiting = preview_journey(client, headers, changed, journeyId=original['id'], revision=original['revision'])
    settled(client, headers, original['shopping'][0], payment)
    assert apply_journey(client, headers, waiting, 'stale-after-settlement').status_code == 409
    current = detail(client, original['id'])
    assert current['revision'] == original['revision'] and current['trip']['start'] == original['trip']['start']
    assert current['shopping'][0]['actual'] == 7900 and current['shopping'][0]['done'] is True
    fresh = preview_journey(client, headers, changed, journeyId=current['id'], revision=current['revision'])
    assert apply_journey(client, headers, fresh, 'fresh-after-settlement').status_code == 200
    assert detail(client, current['id'])['shopping'][0]['actual'] == 7900


@pytest.mark.parametrize('include_shared', [False, True])
def test_private_origins_stay_out_of_partner_tv_state_and_zip(app, include_shared):
    clients = [member(app), member(app, 2)]
    value = create_journey(*clients[0])
    purchase_id = value['shopping'][0]['id']
    tv = pair_tv(app, *clients[0])
    payments, results, tokens = [], [], []
    for number, (client, headers) in enumerate(clients, 1):
        pay = import_payment(client, headers, 'PRIVATE_SETTLEMENT_MEMBER' + str(number))
        pending, result = settled(client, headers, shopping(client, purchase_id), pay, amount=number * 1100)
        payments.append(pay)
        results.append(result)
        tokens.append(pending['previewToken'])
    sensitive = [p['id'] for p in payments] + [r['link']['id'] for r in results] + tokens
    for client in [clients[0][0], clients[1][0], tv]:
        state = client.get('/api/state')
        assert state.status_code == 200
        raw = state.get_data(as_text=True)
        for marker in ['PRIVATE_SETTLEMENT_MEMBER', *sensitive]:
            assert marker not in raw
        visible = next(r for r in state.json['shopping'] if r['id'] == purchase_id)
        assert visible['actual'] == 2200 and visible['done'] is True
    assert tv.get(PREFIX + '/context').status_code == 403
    assert tv.post('/api/portability/export', json={}).status_code == 403
    for number, (client, headers) in enumerate(clients):
        context = client.get(PREFIX + '/context', query_string={'shoppingId': purchase_id})
        assert context.status_code == 200, context.json
        assert results[number]['link']['id'] in {r['id'] for r in context.json['links']}
        assert results[1-number]['link']['id'] not in context.get_data(as_text=True)
        forbidden_context = client.get(PREFIX + '/context', query_string={'linkId': results[1-number]['link']['id']})
        assert forbidden_context.status_code == 404
        auth = client.get('/api/me').json
        before_export = monetary_snapshot(app)
        response = client.post('/api/portability/export', json={'includeShared': include_shared}, headers=headers)
        assert 'Set-Cookie' not in response.headers
        exported, files = unpack(response)
        own = exported['personal']['shoppingSettlements']
        assert {r['id'] for r in own['links']} == {results[number]['link']['id']}
        assert own['receipts']
        raw = b''.join(files.values())
        for marker in ['PRIVATE_SETTLEMENT_MEMBER' + str(2-number), payments[1-number]['id'],
                       results[1-number]['link']['id'], 'previewToken', 'context_hash',
                       'source_digest', 'nonce', headers['X-CSRF-Token'], *tokens]:
            assert marker.encode() not in raw
        assert ('shared' in exported) is include_shared
        if include_shared:
            assert exported['shared']['entities']['shopping'][0]['actual'] == 2200
        after_auth = client.get('/api/me').json
        assert after_auth['user']['id'] == auth['user']['id'] and after_auth['csrf'] == auth['csrf']
        assert monetary_snapshot(app) == before_export


def test_deleted_trip_preserves_settled_purchase_photo_and_private_history(app):
    client, headers = member(app)
    original = create_journey(client, headers)
    purchase = original['shopping'][0]
    photo = upload(client, headers)
    assert client.patch('/api/items/shopping/' + purchase['id'], json={
        'revision': purchase['revision'], 'photoIds': [photo],
    }, headers=headers).status_code == 200
    payment = import_payment(client, headers)
    _, result = settled(client, headers, shopping(client, purchase['id']), payment)
    assert client.delete('/api/items/trips/' + original['tripId'],
                         json={'revision': original['trip']['revision']}, headers=headers).status_code == 200
    assert client.get('/api/journeys/' + original['id']).status_code == 404
    retained = shopping(client, purchase['id'])
    assert not retained.get('tripId') and not retained.get('journeyId')
    assert retained['actual'] == 7900 and retained['done'] is True and retained['photoIds'] == [photo]
    context = client.get(PREFIX + '/context', query_string={'shoppingId': retained['id']})
    assert context.status_code == 200 and context.json['links'][0]['id'] == result['link']['id']
    assert client.patch('/api/items/shopping/' + retained['id'], json={
        'revision': retained['revision'], 'title': '保留的独立采购',
    }, headers=headers).status_code == 200


@pytest.mark.parametrize('confirmed_before_delete', [False, True])
def test_deleted_shopping_old_confirmation_never_recreates_original(app, confirmed_before_delete):
    client, headers = member(app)
    original = create_journey(client, headers)
    purchase = original['shopping'][0]
    payment = import_payment(client, headers)
    pending = preview_settlement(client, headers, purchase, payment)
    first = None
    if confirmed_before_delete:
        first = confirm(client, headers, pending)
        assert first.status_code == 200, first.json
    current = shopping(client, purchase['id'])
    assert client.delete('/api/items/shopping/' + current['id'],
                         json={'revision': current['revision']}, headers=headers).status_code == 200
    baseline = monetary_snapshot(app)
    replay = confirm(client, headers, pending)
    if confirmed_before_delete:
        assert replay.status_code == 200 and replay.json['replayed'] is True, replay.json
        exported, _ = unpack(client.post('/api/portability/export', json={}, headers=headers))
        assert exported['personal']['shoppingSettlements']['links'][0]['shoppingId'] == purchase['id']
    else:
        assert replay.status_code in (404, 409), replay.json
    assert client.get('/api/state').json['shopping'] == []
    assert detail(client, original['id'])['shopping'] == []
    assert monetary_snapshot(app) == baseline
    # A later explicit workflow edit may create a new item with the same key;
    # replay still targets the old identity, never the replacement entity.
    refreshed = detail(client, original['id'])
    next_plan = preview_journey(client, headers, refreshed['plan'], journeyId=refreshed['id'], revision=refreshed['revision'])
    assert apply_journey(client, headers, next_plan, 'new-shopping-after-delete').status_code == 200
    replacement = detail(client, original['id'])['shopping'][0]
    assert replacement['id'] != purchase['id'] and replacement['actual'] is None and replacement['done'] is False
    again = confirm(client, headers, pending)
    assert again.status_code == (200 if confirmed_before_delete else replay.status_code)
    assert shopping(client, replacement['id'])['actual'] is None


def test_deleted_private_payment_leaves_purchase_and_historical_receipt(app):
    client, headers = member(app)
    original = create_journey(client, headers)
    payment = import_payment(client, headers)
    pending, result = settled(client, headers, original['shopping'][0], payment)
    before = shopping(client, original['shopping'][0]['id'])
    deleted = client.delete('/api/finance-hub/transactions/' + payment['id'],
                            json={'revision': payment['revision']}, headers=headers)
    assert deleted.status_code == 200, deleted.json
    context = client.get(PREFIX + '/context', query_string={'linkId': result['link']['id']})
    assert context.status_code == 200, context.json
    assert context.json['links'][0]['state'] == 'needs_review'
    replay = confirm(client, headers, pending)
    assert replay.status_code == 200 and replay.json['replayed'] is True, replay.json
    assert shopping(client, before['id']) == before
    with closing(sqlite3.connect(db_path(app))) as con:
        assert con.execute('SELECT count(*) FROM hub_transactions WHERE id=?', (payment['id'],)).fetchone()[0] == 0
    exported, _ = unpack(client.post('/api/portability/export', json={}, headers=headers))
    assert exported['personal']['transactions'] == []
    assert exported['personal']['shoppingSettlements']['links'][0]['paymentId'] == payment['id']
    assert exported['personal']['shoppingSettlements']['receipts']


def test_photo_edit_prevents_restore_but_explicit_detach_retains_current_value(app):
    client, headers = member(app)
    original = create_journey(client, headers)
    payment = import_payment(client, headers)
    _, applied = settled(client, headers, original['shopping'][0], payment)
    current = shopping(client, original['shopping'][0]['id'])
    photo = upload(client, headers)
    assert client.patch('/api/items/shopping/' + current['id'], json={
        'revision': current['revision'], 'photoIds': [photo],
    }, headers=headers).status_code == 200
    changed = shopping(client, current['id'])
    request = {'operation': 'revoke', 'linkId': applied['link']['id'],
               'revision': applied['link']['revision'], 'shoppingRevision': changed['revision'],
               'mode': 'restore_if_unchanged'}
    rejected = client.post(PREFIX + '/preview', json=request, headers=headers)
    assert rejected.status_code == 409, rejected.json
    assert shopping(client, current['id']) == changed
    pending = client.post(PREFIX + '/preview', json={**request, 'mode': 'detach_keep_current'}, headers=headers)
    assert pending.status_code == 200, pending.json
    result = confirm(client, headers, pending.json)
    assert result.status_code == 200 and result.json['link']['status'] == 'revoked', result.json
    assert shopping(client, current['id']) == changed
    assert detail(client, original['id'])['shopping'][0]['photoIds'] == [photo]
