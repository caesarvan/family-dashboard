"""Real temporary Flask/session/SQLite routes; synthetic records, no network."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from pathlib import Path
import secrets
import socket
import sqlite3
from threading import Barrier, Event

from flask import g, request
import pytest

import app as server
import journey_routes as routes
from test_device_sessions import install_connection, invalidate
from test_journey_documents import PASSWORD, clone, create_journey, login
from test_journey_places import create as place_create, path as place_path


URL = '/api/journey-routes'
TABLES = ('journey_routes', 'journey_route_stops', 'journey_route_operations')
PROTECTED = ('journey_places', 'journey_workflows', 'journey_links', 'journey_actions', 'entities', 'audit')


@pytest.fixture(autouse=True)
def isolated_registration_and_network(monkeypatch):
    # This author branch deliberately does not own app.py. Once production
    # wiring exists, exercise that registration without this fallback wrapper.
    if not hasattr(server, 'register_journey_routes'):
        original = server.register_journey_places
        def places(application, db, Problem, body, require_member, audit):
            original(application, db, Problem, body, require_member, audit)
            routes.register_journey_routes(application, db, Problem, body, require_member)
        monkeypatch.setattr(server, 'register_journey_places', places)
    def deny(*_args, **_kwargs):
        raise AssertionError('Network forbidden in route tests')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket, 'create_connection', deny)


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv('MEMBER1_PASSWORD', PASSWORD)
    monkeypatch.setenv('MEMBER2_PASSWORD', PASSWORD)
    return server.create_app({'TESTING': True, 'DATA_DIR': str(tmp_path / 'data'),
        'SECRET_KEY': 'synthetic-route-test-key', 'SESSION_COOKIE_SECURE': False,
        'PUBLIC_ORIGIN': 'http://localhost', 'OPENAI_API_KEY': '', 'OPENAI_MODEL': '',
        'NVIDIA_API_KEY': '', 'NVIDIA_MODEL': '', 'MICROSOFT_CLIENT_ID': '',
        'MICROSOFT_CLIENT_SECRET': '', 'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': ''})


@contextmanager
def database(app):
    with closing(sqlite3.connect(Path(app.config['DATA_DIR']) / 'household.sqlite3', timeout=10)) as con:
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON')
        with con:
            yield con


def snapshot(app, tables=TABLES):
    with database(app) as con:
        return {table: sorted([tuple(row) for row in con.execute('SELECT * FROM ' + table)], key=repr) for table in tables}


def seed(app, *, shared=False, owner=1, count=3):
    client, headers = login(app, owner)
    trip = create_journey(client, headers)
    points = [place_create(client, headers, name='SYNTHETIC-PLACE-' + str(index), journeyId=trip['id'],
                           expectedJourneyRevision=1, visibility='shared' if shared else 'private',
                           coordinateDisclosure='coarse', coordinates={'latitude': 31.234567 + index, 'longitude': 121.456789},
                           status='visited', confirmVisited=True)[0] for index in range(count)]
    return client, headers, trip, points


def payload(trip, points, **extra):
    return {'requestId': secrets.token_hex(16), 'title': 'SYNTHETIC-ROUTE-PRIVATE', 'journeyId': trip['id'],
            'expectedJourneyRevision': 1, 'stops': [{'placeId': point['id'], 'expectedRevision': point['revision']} for point in points], **extra}


def create(client, headers, trip, points, **extra):
    value = payload(trip, points, **extra)
    response = client.post(URL, json=value, headers=headers)
    assert response.status_code == 201, response.json
    return response.json, value


def path(detail):
    return URL + '/' + detail['route']['id']


def update(detail, **extra):
    item = detail['route']
    return {'requestId': secrets.token_hex(16), **{key: item[key] for key in
        ('title', 'journeyId', 'revision', 'sourceVersion', 'visibility')}, 'expectedJourneyRevision': 1,
        'stops': [{'placeId': stop['place']['id'], 'expectedRevision': stop['place']['revision']}
                  if stop['state'] == 'available' else {'keepUnavailableIndex': stop['index']} for stop in item['stops']], **extra}


def deletion(detail):
    return {'requestId': secrets.token_hex(16), **{key: detail['route'][key] for key in ('revision', 'sourceVersion')}}


def test_private_roundtrip_duplicates_restart_receipt_and_no_public_side_effects(app):
    client, headers, trip, points = seed(app)
    protected = snapshot(app, PROTECTED)
    receipt, value = create(client, headers, trip, [points[0], points[1], points[0]])
    detail = receipt['current']
    assert detail['route']['visibility'] == 'private'
    assert [s['place']['id'] for s in detail['route']['stops']] == [points[0]['id'], points[1]['id'], points[0]['id']]
    assert detail['segments'] == [{'fromIndex': 0, 'toIndex': 1}, {'fromIndex': 1, 'toIndex': 2}]
    assert detail['route']['stops'][0]['place'] == points[0]
    assert receipt['operation']['resultRevision'] == 1 and not receipt['replayed']
    assert snapshot(app, PROTECTED) == protected
    partner, _ = login(app, 2)
    assert partner.get(URL).json['total'] == 0
    assert partner.get(path(detail)).status_code == 404
    for endpoint in ('/api/state', '/api/assistant/brief'):
        text = partner.get(endpoint).get_data(as_text=True)
        assert detail['route']['id'] not in text and value['title'] not in text
    before = snapshot(app)
    restarted = server.create_app(dict(app.config))
    resumed = clone(restarted, client)
    assert resumed.get(path(detail)).json == detail
    assert resumed.get(URL + '/operations/' + value['requestId']).json == {**receipt, 'replayed': True}
    replay = resumed.post(URL, json=value, headers=headers)
    assert replay.status_code == 200 and replay.json['replayed']
    assert snapshot(app) == before
    with database(app) as con:
        raw = repr([tuple(row) for row in con.execute('SELECT * FROM journey_route_operations')])
        assert 'SYNTHETIC' not in raw and '31.234567' not in raw
        assert con.execute('PRAGMA foreign_key_check').fetchall() == []


@pytest.mark.parametrize('disclosure,precision,coordinates', [
    ('coarse', 'approximate', {'latitude': 31.2, 'longitude': 121.5}),
    ('hidden', 'hidden', None), ('exact', 'exact', {'latitude': 31.234567, 'longitude': 121.456789}),
])
def test_shared_author_gets_same_public_place_projection(app, disclosure, precision, coordinates):
    client, headers, trip, points = seed(app, shared=True, count=1)
    points[0] = client.patch(place_path(points[0]), json={'revision': 1, 'coordinateDisclosure': disclosure}, headers=headers).json['place']
    receipt, _ = create(client, headers, trip, points * 2, visibility='shared')
    detail = receipt['current']
    partner, ph = login(app, 2)
    public = partner.get(place_path(points[0])).json['place']
    for c in (client, partner):
        got = c.get(path(detail)).json
        assert got['route']['stops'][0]['place'] == public
        assert public['coordinates'] == coordinates and public['coordinatePrecision'] == precision
        assert not public['canManage'] and 'sharedCoordinates' not in public
        assert len(got['segments']) == (0 if coordinates is None else 1)
    assert partner.put(path(detail), json=update(detail), headers=ph).status_code == 403
    assert partner.delete(path(detail), json=deletion(detail), headers=ph).status_code == 403
    assert partner.get(URL + '/operations/' + receipt['operation']['requestId']).status_code == 404


@pytest.mark.parametrize('change', ['private', 'delete', 'unlink', 'other_journey', 'hard_delete'])
def test_hidden_middle_slot_has_no_details_no_bridge_and_receipt_is_live(app, change):
    client, headers, trip, points = seed(app, shared=True)
    receipt, original = create(client, headers, trip, points, visibility='shared')
    detail, middle = receipt['current'], points[1]
    if change == 'delete':
        assert client.delete(place_path(middle), json={'revision': 1}, headers=headers).status_code == 200
    elif change == 'hard_delete':
        with database(app) as con:
            con.execute('DELETE FROM journey_places WHERE id=?', (middle['id'],))
    else:
        edit = {'revision': 1, 'confirmVisited': True}
        edit.update({'visibility': 'private'} if change == 'private' else
                    {'journeyId': None if change == 'unlink' else create_journey(client, headers)['id']})
        assert client.patch(place_path(middle), json=edit, headers=headers).status_code == 200
    partner, _ = login(app, 2)
    for c in (client, partner):
        response = c.get(path(detail))
        current = response.json
        assert current['route']['stops'][1] == {'index': 1, 'state': 'unavailable'}
        assert current['segments'] == []
        assert middle['id'] not in response.text and middle['name'] not in response.text
        assert str(middle['coordinates']['latitude']) not in response.text
        assert current['route']['sourceVersion'] != detail['route']['sourceVersion']
    response = client.post(URL, json=original, headers=headers)
    assert response.status_code == 200 and response.json['replayed']
    assert response.json['current']['route']['stops'][1] == {'index': 1, 'state': 'unavailable'}
    assert client.put(path(detail), json=update(detail), headers=headers).json['code'] == 'source_changed'
    current = client.get(path(detail)).json
    value = update(current)
    value['stops'] = [value['stops'][1], value['stops'][0], value['stops'][2]]
    saved = client.put(path(detail), json=value, headers=headers)
    assert saved.status_code == 200, saved.json
    assert saved.json['current']['route']['stops'][0] == {'index': 0, 'state': 'unavailable'}
    assert saved.json['current']['segments'] == [{'fromIndex': 1, 'toIndex': 2}]


def test_private_other_owner_place_revocation_keep_rules_and_first_share(app):
    client, headers, trip, points = seed(app, shared=True, owner=2, count=1)
    primary, ph = login(app)
    receipt, _ = create(primary, ph, trip, points)
    detail = receipt['current']
    assert client.patch(place_path(points[0]), json={'revision': 1, 'visibility': 'private'}, headers=headers).status_code == 200
    current = primary.get(path(detail)).json
    assert current['route']['stops'] == [{'index': 0, 'state': 'unavailable'}]
    bad = update(current, visibility='shared')
    assert primary.put(path(detail), json=bad, headers=ph).json['code'] == 'source_changed'
    assert primary.put(path(detail), json=update(current, stops=[{'keepUnavailableIndex': 0}] * 2), headers=ph).status_code == 400
    assert primary.put(path(detail), json=update(current, stops=[{'keepUnavailableIndex': 1}]), headers=ph).status_code == 409
    other = create_journey(primary, ph)
    assert primary.put(path(detail), json=update(current, journeyId=other['id']), headers=ph).status_code == 409
    saved = primary.put(path(detail), json=update(current, title='保留缺口'), headers=ph)
    assert saved.status_code == 200
    assert points[0]['id'] not in saved.text


def test_new_references_must_be_current_same_journey_and_public_on_share(app):
    client, headers, trip, points = seed(app, count=1)
    assert client.post(URL, json=payload(trip, points, visibility='shared'), headers=headers).json['code'] == 'source_changed'
    other = create_journey(client, headers)
    assert client.post(URL, json=payload(other, points), headers=headers).status_code == 409
    receipt, _ = create(client, headers, trip, points)
    detail = receipt['current']
    assert client.put(path(detail), json=update(detail, stops=[{'keepUnavailableIndex': 0}]), headers=headers).status_code == 409
    points[0] = client.patch(place_path(points[0]), json={'revision': 1, 'visibility': 'shared'}, headers=headers).json['place']
    current = client.get(path(detail)).json
    assert client.put(path(detail), json=update(current, visibility='shared'), headers=headers).status_code == 200


def test_source_changes_include_journey_entity_and_even_hidden_points(app):
    client, headers, trip, points = seed(app, shared=True, count=1)
    receipt, _ = create(client, headers, trip, points, visibility='shared')
    detail = receipt['current']
    for table, identity in [('journey_workflows', trip['id']), ('entities', trip['tripId']), ('journey_places', points[0]['id'])]:
        with database(app) as con:
            con.execute('UPDATE ' + table + ' SET revision=revision+1 WHERE id=?', (identity,))
        response = client.put(path(detail), json=update(detail), headers=headers)
        assert response.status_code == 409 and response.json['code'] == 'source_changed'
        next_detail = client.get(path(detail)).json
        assert next_detail['route']['sourceVersion'] != detail['route']['sourceVersion']
        detail = next_detail
    assert client.post(URL, json=payload(trip, points), headers=headers).json['code'] == 'source_changed'


def test_delete_and_old_receipt_never_restore_route_or_stops(app):
    client, headers, trip, points = seed(app)
    receipt, original = create(client, headers, trip, points)
    detail = receipt['current']
    value = deletion(detail)
    response = client.delete(path(detail), json=value, headers=headers)
    assert response.status_code == 200 and response.json['current'] is None
    before = snapshot(app)
    for response in (client.delete(path(detail), json=value, headers=headers), client.post(URL, json=original, headers=headers),
                     client.get(URL + '/operations/' + original['requestId'])):
        assert response.status_code == 200 and response.json['replayed'] and response.json['current'] is None
    assert snapshot(app) == before
    assert client.get(path(detail)).status_code == 404
    with database(app) as con:
        row = con.execute('SELECT * FROM journey_routes').fetchone()
        assert row['title'] == '' and row['journey_id'] is None and row['deleted_at']
        assert con.execute('SELECT count(*) FROM journey_route_stops').fetchone()[0] == 0


def test_trip_deletion_keeps_slots_and_receipt_but_no_foreign_key_leaks(app):
    client, headers, trip, points = seed(app, shared=True)
    receipt, original = create(client, headers, trip, points, visibility='shared')
    detail = receipt['current']
    live = client.get('/api/journeys/' + trip['id']).json['trip']
    assert client.delete('/api/items/trips/' + trip['tripId'], json={'revision': live['revision']}, headers=headers).status_code == 200
    current = client.get(path(detail)).json
    assert current['route']['journeyId'] is None and current['segments'] == []
    assert current['route']['stops'] == [{'index': index, 'state': 'unavailable'} for index in range(3)]
    assert client.post(URL, json=original, headers=headers).json['current'] == current
    assert client.delete(path(detail), json=deletion(current), headers=headers).status_code == 200


def test_receipt_digest_cross_operation_owner_and_limit_recovery(app, monkeypatch):
    client, headers, trip, points = seed(app, shared=True, count=1)
    receipt, original = create(client, headers, trip, points)
    detail = receipt['current']
    changed = client.post(URL, json={**original, 'title': '不同'}, headers=headers)
    assert changed.status_code == 409 and changed.json['code'] == 'request_conflict'
    assert client.put(path(detail), json=update(detail, requestId=original['requestId']), headers=headers).json['code'] == 'request_conflict'
    partner, ph = login(app, 2)
    second, _ = create(partner, ph, trip, points, requestId=original['requestId'])
    assert second['operation']['routeId'] != receipt['operation']['routeId']
    monkeypatch.setattr(routes, 'MAX_ROUTES', 1)
    monkeypatch.setattr(routes, 'MAX_OPERATIONS', 1)
    assert client.post(URL, json=payload(trip, points), headers=headers).json['code'] == 'limit_reached'
    assert client.post(URL, json=original, headers=headers).json['replayed']


def test_list_filters_pagination_private_counts_and_shared_withdrawal(app):
    client, headers, trip, points = seed(app, shared=True, count=1)
    private, _ = create(client, headers, trip, points)
    public, _ = create(client, headers, trip, points, visibility='shared', title='SHARED')
    partner, _ = login(app, 2)
    assert partner.get(URL).json['items'] == [{'id': public['operation']['routeId'], 'title': 'SHARED', 'journeyId': trip['id'],
        'visibility': 'shared', 'revision': 1, 'canManage': False, 'stopCount': 1, 'unavailableCount': 0}]
    assert partner.get(URL + '?scope=mine').json['total'] == 0
    assert client.get(URL + '?scope=shared').json['total'] == 1
    first = client.get(URL + '?limit=1').json
    second = client.get(URL + '?limit=1&offset=1').json
    assert first['total'] == 2 and first['hasMore'] and not second['hasMore']
    assert first['items'][0]['id'] != second['items'][0]['id']
    assert client.get(URL + '?journeyId=' + trip['id']).json['total'] == 2
    assert client.put(path(public['current']), json=update(public['current'], visibility='private'), headers=headers).status_code == 200
    assert partner.get(path(public['current'])).status_code == 404 and partner.get(URL).json['total'] == 0
    assert client.get(path(private['current'])).headers['Cache-Control'] == 'no-store'


@pytest.mark.parametrize('change', [
    {'owner': 'member2'}, {'title': ''}, {'title': 'x' * 161}, {'title': 'a\nb'}, {'title': []},
    {'requestId': 'A' * 32}, {'expectedJourneyRevision': True}, {'visibility': {}},
    {'stops': []}, {'stops': [{'keepUnavailableIndex': 0}]}, {'stops': [{'placeId': 'a' * 24, 'expectedRevision': True}]},
])
def test_invalid_create_has_no_writes(app, change):
    client, headers, trip, points = seed(app, count=1)
    before = snapshot(app)
    response = client.post(URL, json=payload(trip, points, **change), headers=headers)
    assert response.status_code == 400 and response.json['code'] == 'invalid_request'
    assert snapshot(app) == before


@pytest.mark.parametrize('query', ['scope=all', 'extra=x', 'limit=0', 'limit=101', 'offset=10001', 'journeyId=', 'scope=mine&scope=shared'])
def test_bad_list_query(app, query):
    client, _ = login(app)
    assert client.get(URL + '?' + query).status_code == 400


def test_stop_and_body_limits(app):
    client, headers, trip, points = seed(app, count=1)
    assert client.post(URL, json=payload(trip, points * 101), headers=headers).status_code == 400
    receipt, _ = create(client, headers, trip, points * 100)
    assert len(receipt['current']['route']['stops']) == 100 and len(receipt['current']['segments']) == 99
    too_big = client.post(URL, json=payload(trip, points, title='x' * (routes.MAX_REQUEST_BYTES + 1)), headers=headers)
    assert too_big.status_code == 413 and too_big.json['code'] == 'request_too_large'


def test_anonymous_tv_csrf_and_wrong_origin_all_routes(app):
    client, headers, trip, points = seed(app, shared=True, count=1)
    receipt, original = create(client, headers, trip, points, visibility='shared')
    detail = receipt['current']
    tv = app.test_client()
    pair = tv.post('/api/pair/start', json={}).json
    assert client.post('/api/pair/approve', json={'code': pair['code'], 'name': '合成电视', 'focus': 'shared'}, headers=headers).status_code == 200
    assert tv.post('/api/pair/poll', json={'secret': pair['secret']}).json['approved']
    targets = [('get', URL, None), ('get', path(detail), None), ('get', URL + '/operations/' + original['requestId'], None),
               ('post', URL, original), ('put', path(detail), update(detail)), ('delete', path(detail), deletion(detail))]
    for method, url, data in targets:
        assert getattr(tv, method)(url, json=data, headers=headers).status_code == 403
        assert getattr(app.test_client(), method)(url, json=data, headers=headers).status_code == 401
    assert client.post(URL, json=original).status_code == 403
    assert client.post(URL, json=original, headers={**headers, 'Origin': 'https://outside.invalid'}).status_code == 403
    assert receipt['operation']['routeId'] not in tv.get('/api/state').text


@pytest.mark.parametrize('method', ['get', 'post', 'put', 'delete', 'receipt'])
def test_revoked_after_guard_cannot_read_or_write(app, method):
    client, headers, trip, points = seed(app, count=1)
    receipt, original = create(client, headers, trip, points)
    detail = receipt['current']
    before = snapshot(app)
    def revoke():
        if request.headers.get('X-Test-Revoke'):
            with database(app) as con:
                invalidate(con)
    app.before_request_funcs[None].append(revoke)
    url = URL if method == 'post' else URL + '/operations/' + original['requestId'] if method == 'receipt' else path(detail)
    value = original if method == 'post' else deletion(detail) if method == 'delete' else update(detail)
    result = getattr(client, 'get' if method == 'receipt' else method)(url, json=value, headers={**headers, 'X-Test-Revoke': '1'})
    assert result.status_code == 401 and result.json['code'] == 'session_changed'
    assert snapshot(app) == before


def test_identity_rechecked_after_snapshot_before_response(app, monkeypatch):
    client, headers, trip, points = seed(app, count=1)
    receipt, _ = create(client, headers, trip, points)
    original, calls = routes.ImportSession.fresh, []
    def revoke(current):
        if not calls:
            calls.append(True)
            with database(app) as con:
                invalidate(con)
        return original(current)
    monkeypatch.setattr(routes.ImportSession, 'fresh', revoke)
    response = client.get(path(receipt['current']))
    assert response.status_code == 401 and 'SYNTHETIC' not in response.text


def test_household_actor_mismatch_is_denied(app):
    client, headers, trip, points = seed(app, count=1)
    def change():
        if request.headers.get('X-Test-Household'):
            g.actor = {**g.actor, 'householdId': 'wrong-household'}
    app.before_request_funcs[None].append(change)
    response = client.post(URL, json=payload(trip, points), headers={**headers, 'X-Test-Household': '1'})
    assert response.status_code == 401 and snapshot(app)[TABLES[0]] == []


def test_two_real_households_cannot_see_foreign_route_or_receipt(app):
    client, headers, trip, points = seed(app, shared=True, count=1)
    receipt, original = create(client, headers, trip, points, visibility='shared')
    invitation = client.post('/api/spaces/invitations', json={}, headers=headers).json['invitation']
    child = app.test_client()
    response = child.post('/api/spaces/redeem', json={'invitation': invitation, 'name': '合成第二家庭', 'slug': 'routes-second',
        'MEMBER1_PASSWORD': PASSWORD, 'MEMBER2_PASSWORD': PASSWORD})
    assert response.status_code == 201 and child.get(response.json['entry']).status_code == 303
    child, ch = login(app, client=child)
    assert child.get(URL).json['total'] == 0
    assert child.get(path(receipt['current'])).status_code == 404
    assert child.get(URL + '/operations/' + original['requestId']).status_code == 404
    assert child.post(URL, json=original, headers=ch).status_code == 404
    child_trip = create_journey(child, ch)
    child_point = place_create(child, ch, journeyId=child_trip['id'])[0]
    other, _ = create(child, ch, child_trip, [child_point], requestId=original['requestId'])
    assert other['operation']['routeId'] != receipt['operation']['routeId']
    child.set_cookie('session', client.get_cookie('session').value)
    assert child.get(URL).status_code == 401


def test_failure_in_receipt_insert_rolls_back_route_and_sequence(app):
    client, headers, trip, points = seed(app)
    receipt, _ = create(client, headers, trip, points)
    before = snapshot(app, TABLES + PROTECTED)
    with database(app) as con:
        con.execute("CREATE TRIGGER reject_route_receipt BEFORE INSERT ON journey_route_operations BEGIN SELECT RAISE(ABORT,'synthetic rollback'); END")
    with pytest.raises(sqlite3.IntegrityError, match='synthetic rollback'):
        client.put(path(receipt['current']), json=update(receipt['current'], title='MUST ROLLBACK', stops=[{'placeId': points[2]['id'], 'expectedRevision': 1}]), headers=headers)
    assert snapshot(app, TABLES + PROTECTED) == before


def test_committed_but_lost_response_recovers_once_after_app_recreation(app, monkeypatch):
    client, headers, trip, points = seed(app, count=1)
    original = payload(trip, points)
    project = routes.route_context
    def lost(*_args, **_kwargs):
        raise RuntimeError('synthetic connection lost after commit')
    with monkeypatch.context() as change:
        change.setattr(routes, 'route_context', lost)
        with pytest.raises(RuntimeError, match='after commit'):
            client.post(URL, json=original, headers=headers)
    assert routes.route_context is project
    before = snapshot(app)
    assert len(before['journey_routes']) == len(before['journey_route_operations']) == 1
    restarted = server.create_app(dict(app.config))
    resumed = clone(restarted, client)
    receipt = resumed.get(URL + '/operations/' + original['requestId'])
    assert receipt.status_code == 200 and receipt.json['operation']['resultRevision'] == 1
    replay = resumed.post(URL, json=original, headers=headers)
    assert replay.status_code == 200 and replay.json == receipt.json
    assert snapshot(app) == before


def test_second_session_check_rolls_back_business_writes(app, monkeypatch):
    client, headers, trip, points = seed(app, count=1)
    original = routes.ImportSession.check
    calls = []
    def revoke(current):
        if current.con.in_transaction and current.con.execute('SELECT count(*) FROM journey_routes').fetchone()[0]:
            # Revoke in this real transaction immediately before the second
            # session fence. Both the synthetic revocation and business writes
            # must roll back; no success receipt can escape.
            invalidate(current.con)
            calls.append(True)
        return original(current)
    before = snapshot(app)
    monkeypatch.setattr(routes.ImportSession, 'check', revoke)
    response = client.post(URL, json=payload(trip, points), headers=headers)
    assert calls == [True] and response.status_code == 401
    assert snapshot(app) == before


def test_place_revocation_after_guard_before_write_uses_new_snapshot(app):
    client, headers, trip, points = seed(app, shared=True, count=1)
    def withdraw(sql):
        if sql == 'BEGIN IMMEDIATE':
            with database(app) as con:
                con.execute("UPDATE journey_places SET visibility='private',revision=revision+1 WHERE id=?", (points[0]['id'],))
    install_connection(app, URL, 'POST', before=withdraw)
    response = client.post(URL, json=payload(trip, points, visibility='shared'), headers=headers)
    assert response.status_code == 409 and response.json['code'] == 'source_changed'
    assert snapshot(app)['journey_routes'] == []


def test_concurrent_create_replay_and_update_cas(app):
    client, headers, trip, points = seed(app, count=1)
    copies = [clone(app, client), clone(app, client)]
    original, barrier = payload(trip, points), Barrier(2)
    def submit(c):
        barrier.wait(10)
        return c.post(URL, json=original, headers=headers)
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(submit, copies))
    assert sorted(r.status_code for r in responses) == [200, 201]
    assert len({r.json['operation']['routeId'] for r in responses}) == 1
    detail, barrier = responses[0].json['current'], Barrier(2)
    def change(pair):
        index, c = pair
        barrier.wait(10)
        return c.put(path(detail), json=update(detail, title='并发' + str(index)), headers=headers)
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(change, enumerate(copies)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert client.get(path(detail)).json['route']['revision'] == 2
    with database(app) as con:
        assert con.execute('SELECT count(*) FROM journey_route_operations').fetchone()[0] == 2


def test_revocation_committed_while_waiting_for_write_lock(app):
    client, headers, trip, points = seed(app, count=1)
    before, entered = snapshot(app), Event()
    writer = sqlite3.connect(Path(app.config['DATA_DIR']) / 'household.sqlite3', timeout=10, check_same_thread=False)
    def begin(sql):
        if sql == 'BEGIN IMMEDIATE':
            writer.execute('BEGIN IMMEDIATE')
            invalidate(writer)
            entered.set()
    install_connection(app, URL, 'POST', before=begin)
    try:
        with ThreadPoolExecutor(1) as pool:
            pending = pool.submit(client.post, URL, json=payload(trip, points), headers=headers)
            try:
                assert entered.wait(10) and not pending.done()
            finally:
                writer.commit()
            response = pending.result(10)
        assert response.status_code == 401 and snapshot(app) == before
    finally:
        writer.close()


def test_init_joins_caller_transaction_and_schema_is_idempotent(app):
    client, headers, trip, points = seed(app, count=1)
    create(client, headers, trip, points)
    before = snapshot(app)
    with database(app) as con:
        con.execute('BEGIN IMMEDIATE')
        con.execute("UPDATE journey_routes SET title='ROLLBACK'")
        routes.initialize_journey_routes(con)
        assert con.in_transaction
        con.rollback()
    assert snapshot(app) == before
    with sqlite3.connect(':memory:') as con:
        con.execute('PRAGMA foreign_keys=ON')
        con.executescript('CREATE TABLE users(id TEXT PRIMARY KEY); CREATE TABLE journey_workflows(id TEXT PRIMARY KEY); CREATE TABLE journey_places(id TEXT PRIMARY KEY);')
        con.execute('BEGIN IMMEDIATE')
        routes.initialize_journey_routes(con)
        con.rollback()
        assert con.execute("SELECT count(*) FROM sqlite_master WHERE name LIKE 'journey_route%'").fetchone()[0] == 0
