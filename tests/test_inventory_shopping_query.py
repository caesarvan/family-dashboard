"""Read-only shopping-to-stock lookup through real household APIs and SQLite."""
from contextlib import closing
import json
import socket
import sqlite3
import time

from flask import g, request
import pytest

from app import create_app
import inventory_core
from test_inventory_api import acquisition, counts, create, move, rid
from test_journey_documents import PASSWORD, clone, connection, login

P = '/api/inventory'


@pytest.fixture
def app(tmp_path, monkeypatch):
    def offline(*_args, **_kwargs):
        raise AssertionError('External network forbidden in shopping inventory query')
    monkeypatch.setattr(socket.socket, 'connect', offline)
    monkeypatch.setattr(socket, 'create_connection', offline)
    monkeypatch.setenv('MEMBER1_PASSWORD', PASSWORD)
    monkeypatch.setenv('MEMBER2_PASSWORD', PASSWORD)
    value = create_app({'TESTING': True, 'DATA_DIR': str(tmp_path/'home'),
        'SECRET_KEY': 'synthetic-shopping-stock-secret', 'SESSION_COOKIE_SECURE': False,
        'PUBLIC_ORIGIN': 'http://localhost', 'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': '',
        'MICROSOFT_CLIENT_ID': '', 'MICROSOFT_CLIENT_SECRET': '', 'ASSISTANT_PROVIDER': 'local',
        'OPENAI_API_KEY': '', 'OPENAI_MODEL': '', 'NVIDIA_API_KEY': '', 'NVIDIA_MODEL': ''})
    assert 'inventory' in value.extensions  # Actual factory, no fallback registration.
    return value


def shopping(c, h, **data):
    response = c.post('/api/items/shopping', headers=h,
                      json={'title': '合成电池采购', 'quantity': '两盒六节',
                            'budget': 3200, 'actual': 2800, 'done': True, **data})
    assert response.status_code == 201, response.json
    return next(row for row in c.get('/api/state').json['shopping'] if row['id'] == response.json['id'])


def path(sid):
    return P+'/shopping/'+sid+'/acquisitions'


def lookup(c, sid, **paging):
    response = c.get(path(sid), query_string=paging)
    assert response.status_code == 200, response.json
    assert response.headers['Cache-Control'] == 'no-store'
    return response.json


def linked(c, h, sid, *, title='合成物品', visibility='private', **batch):
    item = create(c, h, title=title, visibility=visibility)[0]['item']
    return acquisition(c, h, item, shoppingId=sid, **batch)[0]


def test_current_projections_quantities_and_no_financial_or_receipt_reads(app, monkeypatch):
    c, h = login(app)
    source = shopping(c, h, note='SHOPPING_NOTE_EXCLUDED', owner='member2')
    batch = linked(c, h, source['id'], afterSalesState='open', warrantyUntil='2027-09-18')
    batch = move(c, h, batch, quantity=4)[0]
    batch = move(c, h, batch, 'return', 1)[0]
    expected = c.get(P+'/acquisitions/'+batch['acquisition']['id']).json
    before = counts(app)
    with closing(connection(app)) as con:
        entities = [tuple(row) for row in con.execute('SELECT * FROM entities ORDER BY id')]
    original_current = app.extensions['member_sessions'].current
    denied = []

    def restricted(con):
        assert con.in_transaction
        actor = original_current(con)
        def authorize(op, table, column, *_):
            if op == sqlite3.SQLITE_READ and (table.startswith('hub_') or table in
                    {'inventory_source_links', 'inventory_operations', 'shopping_settlement_links',
                     'shopping_settlement_receipts', 'private_finance'}):
                denied.append((table, column))
                return sqlite3.SQLITE_DENY
            if op in {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}:
                denied.append(('write', table))
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        con.set_authorizer(authorize)
        return actor

    monkeypatch.setattr(app.extensions['member_sessions'], 'current', restricted)
    result = lookup(c, source['id'])
    assert result == {'shopping': {key: source[key] for key in ('id', 'revision', 'title', 'quantity')},
                      'items': [expected], 'total': 1, 'limit': 12, 'offset': 0, 'nextOffset': None}
    assert result['items'][0]['item']['onHandQty'] == 3
    assert result['items'][0]['acquisition']['remainingExpectedQty'] == 2
    assert result['items'][0]['acquisition']['afterSalesState'] == 'open'
    assert 'SHOPPING_NOTE_EXCLUDED' not in json.dumps(result)
    assert denied == [] and counts(app) == before
    with closing(connection(app)) as con:
        assert [tuple(row) for row in con.execute('SELECT * FROM entities ORDER BY id')] == entities


def test_acl_before_count_page_and_current_share_revocation(app):
    c, h = login(app)
    other, oh = login(app, 2)
    source = shopping(c, h)
    mine = linked(c, h, source['id'], title='我的私密')
    hidden = linked(other, oh, source['id'], title='伙伴私密')
    shared = linked(other, oh, source['id'], title='伙伴共享', visibility='shared')
    expected = sorted([mine['acquisition']['id'], shared['acquisition']['id']])
    first = lookup(c, source['id'], limit=1)
    second = lookup(c, source['id'], limit=1, offset=first['nextOffset'])
    assert first['total'] == second['total'] == 2
    assert first['nextOffset'] == 1 and second['nextOffset'] is None
    assert [first['items'][0]['acquisition']['id'], second['items'][0]['acquisition']['id']] == expected
    assert hidden['item']['id'] not in json.dumps([first, second])
    shared_projection = next(row for row in [first['items'][0], second['items'][0]]
                             if row['item']['id'] == shared['item']['id'])
    assert not shared_projection['item']['canManage']
    assert set(shared_projection['acquisition']['editableFields']) == {'orderState', 'expectedOn', 'afterSalesState', 'note'}
    response = other.patch(P+'/items/'+shared['item']['id'], headers=oh,
        json={'requestId': rid(), 'revision': shared['item']['revision'], 'patch': {'visibility': 'private'}})
    assert response.status_code == 200, response.json
    result = lookup(c, source['id'], limit=1)
    assert result['total'] == 1 and result['nextOffset'] is None
    assert result['items'][0]['item']['id'] == mine['item']['id']
    assert lookup(c, source['id'], offset=1)['items'] == []
    assert lookup(other, source['id'])['total'] == 2


def test_closed_cancelled_visible_archived_and_unlinked_excluded(app):
    c, h = login(app)
    source = shopping(c, h)
    closed = linked(c, h, source['id'], orderState='closed')
    cancelled = linked(c, h, source['id'], orderState='cancelled')
    archived = linked(c, h, source['id'], orderState='closed')
    response = c.delete(P+'/items/'+archived['item']['id'], headers=h,
        json={'requestId': rid(), 'revision': archived['item']['revision'], 'confirmArchive': True})
    assert response.status_code == 200, response.json
    # There is no HTTP batch archive operation. Model an existing valid tombstone.
    batch_archived = linked(c, h, source['id'], orderState='closed')
    with closing(connection(app)) as con, con:
        con.execute('UPDATE inventory_acquisitions SET deleted_at=? WHERE id=?',
                    ('2026-09-18T00:00:00+00:00', batch_archived['acquisition']['id']))
    unlinked = linked(c, h, source['id'])
    response = c.patch(P+'/acquisitions/'+unlinked['acquisition']['id'], headers=h,
        json={'requestId': rid(), 'itemRevision': unlinked['item']['revision'],
              'revision': unlinked['acquisition']['revision'], 'patch': {'shoppingId': None}})
    assert response.status_code == 200, response.json
    rows = lookup(c, source['id'])
    assert rows['total'] == 2
    assert {row['acquisition']['id'] for row in rows['items']} == {
        closed['acquisition']['id'], cancelled['acquisition']['id']}
    assert lookup(c, source['id'], offset=100000)['items'] == []


def test_default_limit_multiple_batches_and_restart(app):
    c, h = login(app)
    source = shopping(c, h)
    item = create(c, h)[0]['item']
    ids = []
    for _ in range(13):
        result = acquisition(c, h, item, shoppingId=source['id'])[0]
        ids.append(result['acquisition']['id'])
        item = result['item']
    first = lookup(c, source['id'])
    second = lookup(c, source['id'], offset=first['nextOffset'])
    assert first['limit'] == second['limit'] == 12
    assert first['total'] == second['total'] == 13
    assert first['nextOffset'] == 12 and second['nextOffset'] is None
    assert [row['acquisition']['id'] for row in first['items']+second['items']] == sorted(ids)
    restarted = create_app(dict(app.config))
    assert lookup(clone(restarted, c), source['id']) == first


def test_source_empty_missing_wrong_kind_deleted_and_recreated(app):
    c, h = login(app)
    source = shopping(c, h)
    empty = lookup(c, source['id'])
    assert empty['items'] == [] and empty['total'] == 0 and empty['nextOffset'] is None
    assert c.get(path('a'*24)).status_code == 404
    task = c.post('/api/items/tasks', headers=h, json={'title': '不是采购'}).json
    assert c.get(path(task['id'])).status_code == 404
    batch = linked(c, h, source['id'])
    response = c.patch('/api/items/shopping/'+source['id'], headers=h,
                       json={'revision': source['revision'], 'title': '更新后的采购', 'quantity': '4 盒'})
    assert response.status_code == 200, response.json
    updated = lookup(c, source['id'])['shopping']
    assert updated['title'] == '更新后的采购' and updated['quantity'] == '4 盒'
    assert updated['revision'] == source['revision']+1
    response = c.delete('/api/items/shopping/'+source['id'], headers=h,
                        json={'revision': updated['revision']})
    assert response.status_code == 200, response.json
    assert c.get(path(source['id'])).status_code == 404
    fresh = shopping(c, h, title=source['title'])
    assert fresh['id'] != source['id'] and lookup(c, fresh['id'])['total'] == 0
    assert c.get(P+'/acquisitions/'+batch['acquisition']['id']).json['acquisition']['shoppingId'] is None


@pytest.mark.parametrize('query', ['limit=0', 'limit=101', 'limit=true', 'limit=1.5',
    'offset=-1', 'offset=100001', 'limit=1&limit=2', 'offset=0&offset=1',
    'owner=member2', 'scope=all', 'q=x', 'shoppingId='+'a'*24])
def test_reject_query_not_in_contract(app, query):
    c, h = login(app)
    source = shopping(c, h)
    response = c.get(path(source['id'])+'?'+query)
    assert response.status_code == 400 and response.json['code'] == 'invalid'


@pytest.mark.parametrize('sid', ['short', 'A'*24, 'g'*24, "x' OR 1=1"])
def test_reject_non_id(app, sid):
    c, _ = login(app)
    assert c.get(path(sid)).status_code == 400


def test_anonymous_tv_display_mode_logout(app):
    c, h = login(app)
    source = shopping(c, h)
    linked(c, h, source['id'], visibility='shared')
    assert app.test_client().get(path(source['id'])).status_code == 401
    tv = app.test_client()
    pair = tv.post('/api/pair/start', json={}).json
    assert c.post('/api/pair/approve', headers=h,
                  json={'code': pair['code'], 'name': '合成库存电视'}).status_code == 200
    assert tv.post('/api/pair/poll', json={'secret': pair['secret']}).json['approved']
    assert tv.get(path(source['id'])).status_code == 403
    # Display mode chooses the device credential at the outer application guard;
    # a member cookie without a paired device is therefore unauthenticated.
    assert c.get(path(source['id']), headers={'X-Display-Mode': 'tv'}).status_code == 401
    previous = clone(app, c)
    assert c.post('/api/logout', headers=h, json={}).status_code == 200
    assert previous.get(path(source['id'])).status_code == 401


def test_two_real_households_same_member_names_and_foreign_cookie(app):
    c, h = login(app)
    source = shopping(c, h)
    linked(c, h, source['id'], visibility='shared')
    invitation = c.post('/api/spaces/invitations', headers=h, json={}).json['invitation']
    child = app.test_client()
    response = child.post('/api/spaces/redeem', json={'invitation': invitation,
        'name': '第二合成查询家庭', 'slug': 'shopping-query-two',
        'MEMBER1_PASSWORD': PASSWORD, 'MEMBER2_PASSWORD': PASSWORD})
    assert response.status_code == 201, response.json
    assert child.get(response.json['entry']).status_code == 303
    child, ch = login(app, client=child)
    child_source = shopping(child, ch)
    linked(child, ch, child_source['id'], visibility='shared')
    assert lookup(child, child_source['id'])['total'] == lookup(c, source['id'])['total'] == 1
    assert child.get(path(source['id'])).status_code == c.get(path(child_source['id'])).status_code == 404
    child.set_cookie('session', c.get_cookie('session').value)
    assert child.get(path(child_source['id'])).status_code == 401


@pytest.mark.parametrize('fault', ['revoked', 'auth_version', 'household', 'owner'])
def test_fresh_session_inside_query_transaction(app, monkeypatch, fault):
    @app.before_request
    def after_initial_guard():
        if not request.headers.get('X-Synthetic-Fault'):
            return
        if fault in ('revoked', 'auth_version'):
            with closing(connection(app)) as con, con:
                if fault == 'revoked':
                    con.execute('UPDATE member_sessions SET revoked_at=?', (time.time(),))
                else:
                    con.execute("UPDATE users SET auth_version=auth_version+1 WHERE id='member1'")
        else:
            g.actor['householdId' if fault == 'household' else 'id'] = 'b'*24 if fault == 'household' else 'member2'
    c, h = login(app)
    source = shopping(c, h, title='QUERY_MUST_NOT_RETURN')
    linked(c, h, source['id'])
    monkeypatch.setattr(inventory_core, 'project_item', lambda *_: pytest.fail('Read inventory after revoked identity'))
    response = c.get(path(source['id']), headers={'X-Synthetic-Fault': '1'})
    assert response.status_code == 401, response.json
    assert 'QUERY_MUST_NOT_RETURN' not in response.get_data(as_text=True)
