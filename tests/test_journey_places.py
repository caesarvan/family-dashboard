"""Manual-place API against real sessions, household routing and temporary SQLite."""
from concurrent.futures import ThreadPoolExecutor
import secrets
import socket
import sqlite3
import threading

from flask import g, request
import pytest

import app as app_module
import journey_places as places
from test_journey_documents import PASSWORD, clone, connection, create_journey, login, upload as upload_document


PREFIX = '/api/journey-places'


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*_args, **_kwargs):
        raise AssertionError('No network in manual place tests')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv('MEMBER1_PASSWORD', PASSWORD)
    monkeypatch.setenv('MEMBER2_PASSWORD', PASSWORD)
    # Exercise production registration, including the child household factory.
    return app_module.create_app({'TESTING': True, 'DATA_DIR': str(tmp_path / 'data'),
        'SECRET_KEY': 'synthetic-place-test-secret', 'SESSION_COOKIE_SECURE': False,
        'PUBLIC_ORIGIN': 'http://localhost', 'OPENAI_API_KEY': '', 'OPENAI_MODEL': '',
        'MICROSOFT_CLIENT_ID': '', 'MICROSOFT_CLIENT_SECRET': '', 'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': ''})


def payload(**changes):
    return {'requestId': secrets.token_hex(16), 'name': '合成公园', **changes}


def create(client, headers, **changes):
    value = payload(**changes)
    result = client.post(PREFIX, json=value, headers=headers)
    assert result.status_code == 201, result.json
    return result.json['place'], value


def path(place):
    return PREFIX + '/' + place['id']


def snapshot(app):
    with connection(app) as con:
        return {table: [tuple(r) for r in con.execute('SELECT * FROM ' + table + ' ORDER BY rowid')]
                for table in ('journey_places', 'journey_workflows', 'journey_documents', 'entities', 'audit')}


def test_private_default_exact_owner_projection_and_persistence(app):
    client, headers = login(app)
    item, value = create(client, headers, country='合成地区', city='合成城市', coordinates={'latitude': 31.2304, 'longitude': 121.4737})
    assert item['visibility'] == 'private' and item['status'] == 'wish'
    assert item['coordinates'] == value['coordinates'] and item['coordinatePrecision'] == 'exact'
    assert item['sharedCoordinates'] is None and item['sharedCoordinatePrecision'] == 'hidden'
    assert item['coordinateDisclosure'] == 'hidden' and item['canManage']
    assert item['journey'] is None and item['journeyId'] is None
    assert item['visitedConfirmedAt'] is None and item['visitedConfirmedBy'] is None
    assert item['revision'] == 1 and len(item['id']) == 24
    assert client.get(path(item)).json == {'place': item}
    response = client.get(PREFIX)
    assert response.json == {'items': [item], 'total': 1, 'limit': 100, 'offset': 0, 'hasMore': False}
    assert response.headers['Cache-Control'] == 'no-store'
    assert not {'requestId', 'payloadDigest', 'latitude_e6', 'longitude_e6'} & item.keys()
    with connection(app) as con:
        row = con.execute('SELECT latitude_e6,longitude_e6 FROM journey_places').fetchone()
        assert tuple(row) == (31230400, 121473700)
    restarted = app_module.create_app(dict(app.config))
    resumed = clone(restarted, client)
    assert resumed.get(path(item)).json == {'place': item}
    for endpoint in ('/api/state', '/api/assistant/brief'):
        text = client.get(endpoint).get_data(as_text=True)
        assert item['id'] not in text and '31.2304' not in text


@pytest.mark.parametrize('disclosure,coordinates,precision,grid', [
    ('hidden', None, 'hidden', None),
    ('coarse', {'latitude': -31.2, 'longitude': -121.5}, 'approximate', 0.1),
    ('exact', {'latitude': -31.2304, 'longitude': -121.4737}, 'exact', None),
])
def test_shared_projection_same_for_detail_list_and_owner_preview(app, disclosure, coordinates, precision, grid):
    owner, headers = login(app)
    partner, ph = login(app, 2)
    item, _ = create(owner, headers, visibility='shared', coordinateDisclosure=disclosure,
                     coordinates={'latitude': -31.2304, 'longitude': -121.4737})
    other = partner.get(path(item)).json['place']
    assert other['coordinates'] == coordinates and other['coordinatePrecision'] == precision
    assert other['coordinateGridDegrees'] == grid and not other['canManage']
    assert item['sharedCoordinates'] == coordinates and item['sharedCoordinatePrecision'] == precision
    assert item['sharedCoordinateGridDegrees'] == grid
    assert not {'sharedCoordinates', 'sharedCoordinatePrecision', 'sharedCoordinateGridDegrees'} & other.keys()
    assert partner.get(PREFIX).json['items'] == [other]
    assert partner.patch(path(item), json={'revision': 1, 'name': '越权'}, headers=ph).status_code == 403
    assert partner.delete(path(item), json={'revision': 1}, headers=ph).status_code == 403
    if disclosure != 'exact':
        text = partner.get(PREFIX).get_data(as_text=True)
        assert '-31.2304' not in text and '-121.4737' not in text
    hidden = owner.patch(path(item), json={'revision': 1, 'visibility': 'private'}, headers=headers)
    assert hidden.status_code == 200
    assert partner.get(path(item)).status_code == 404
    assert partner.get(PREFIX).json['total'] == 0


def test_no_coordinates_and_clear_coordinates(app):
    client, headers = login(app)
    item, _ = create(client, headers, visibility='shared', coordinateDisclosure='exact')
    assert item['coordinates'] is None and item['coordinatePrecision'] == 'none'
    item = client.patch(path(item), json={'revision': 1, 'coordinates': {'latitude': 90, 'longitude': -180}}, headers=headers).json['place']
    assert item['coordinates'] == {'latitude': 90.0, 'longitude': -180.0}
    item = client.patch(path(item), json={'revision': 2, 'coordinates': None}, headers=headers).json['place']
    assert item['coordinates'] is None and item['revision'] == 3


def test_private_rows_never_in_filter_counts_or_metadata(app):
    client, headers = login(app)
    partner, ph = login(app, 2)
    journey = create_journey(client, headers)
    secret, _ = create(client, headers, name='PRIVATE-PLACE-ONLY', country='HIDDEN-COUNTRY', city='HIDDEN-CITY',
        journeyId=journey['id'], status='visited', confirmVisited=True, startDate='2024-12-30', endDate='2025-01-02')
    for query in ({}, {'owner': 'member1'}, {'journeyId': journey['id']}, {'year': '2025'}, {'status': 'visited'}, {'scope': 'shared'}):
        result = partner.get(PREFIX, query_string=query)
        assert result.status_code == 200 and result.json['total'] == 0 and result.json['items'] == []
        assert 'PRIVATE-PLACE' not in result.get_data(as_text=True)
    for method, data in [('get', None), ('patch', {'revision': 1, 'name': '越权'}), ('delete', {'revision': 1})]:
        assert getattr(partner, method)(path(secret), json=data, headers=ph).status_code == 404
    public, _ = create(partner, ph, visibility='shared', startDate='2024-12-30', endDate='2025-01-02', status='planned')
    assert client.get(PREFIX, query_string={'year': '2025'}).json['total'] == 2
    assert partner.get(PREFIX, query_string={'year': '2025'}).json['total'] == 1
    assert client.get(PREFIX, query_string={'scope': 'mine'}).json['total'] == 1
    assert client.get(PREFIX, query_string={'scope': 'shared'}).json['items'][0]['id'] == public['id']
    assert client.get(PREFIX, query_string={'limit': 1}).json['hasMore']
    second = client.get(PREFIX, query_string={'limit': 1, 'offset': 1}).json
    assert len(second['items']) == 1 and not second['hasMore']
    assert client.get(PREFIX, query_string={'offset': 2}).json['items'] == []


def test_visited_requires_confirmation_and_never_follows_dates(app):
    client, headers = login(app)
    value = payload(status='visited', startDate='2020-01-01')
    assert client.post(PREFIX, json=value, headers=headers).status_code == 400
    item, _ = create(client, headers, status='planned', startDate='2020-01-01')
    assert item['status'] == 'planned' and item['visitedConfirmedAt'] is None
    assert client.patch(path(item), json={'revision': 1, 'status': 'visited'}, headers=headers).status_code == 400
    confirmed = client.patch(path(item), json={'revision': 1, 'status': 'visited', 'confirmVisited': True}, headers=headers).json['place']
    assert confirmed['visitedConfirmedAt'] and confirmed['visitedConfirmedBy'] == 'member1'
    changed = client.patch(path(item), json={'revision': 2, 'visibility': 'shared', 'coordinateDisclosure': 'coarse'}, headers=headers).json['place']
    assert changed['visitedConfirmedAt'] == confirmed['visitedConfirmedAt'] and changed['revision'] == 3
    planned = client.patch(path(item), json={'revision': 3, 'status': 'wish'}, headers=headers).json['place']
    assert planned['visitedConfirmedAt'] is None and planned['visitedConfirmedBy'] is None


@pytest.mark.parametrize('changes', [
    {'name': '新的公园'}, {'country': '另一个国家'}, {'city': '另一个城市'},
    {'coordinates': {'latitude': 30, 'longitude': 120}}, {'startDate': '2024-04-01'},
    {'endDate': '2024-06-01'}, {'journeyId': 'new-journey-placeholder'},
])
def test_visited_location_changes_require_reconfirmation(app, changes):
    client, headers = login(app)
    if 'journeyId' in changes:
        changes = {'journeyId': create_journey(client, headers)['id']}
    item, _ = create(client, headers, status='visited', confirmVisited=True, startDate='2024-05-01')
    before = snapshot(app)
    assert client.patch(path(item), json={'revision': 1, **changes}, headers=headers).status_code == 400
    assert snapshot(app) == before
    result = client.patch(path(item), json={'revision': 1, **changes, 'confirmVisited': True}, headers=headers)
    assert result.status_code == 200, result.json
    assert result.json['place']['revision'] == 2
    assert result.json['place']['visitedConfirmedAt'] != item['visitedConfirmedAt']


@pytest.mark.parametrize('changes', [
    {'name': ''}, {'name': 'x' * 161}, {'name': None}, {'name': 'bad\nname'}, {'country': []}, {'city': 'x' * 101},
    {'requestId': 'short'}, {'requestId': True}, {'owner': 'member2'}, {'extra': 1}, {'status': []},
    {'status': 'visited'}, {'status': 'gone'}, {'visibility': 'public'}, {'visibility': {}},
    {'coordinateDisclosure': 'private'}, {'confirmVisited': 'yes'}, {'confirmVisited': True},
    {'coordinates': {'latitude': 90.1, 'longitude': 0}}, {'coordinates': {'latitude': 0, 'longitude': -180.1}},
    {'coordinates': {'latitude': True, 'longitude': 0}}, {'coordinates': {'latitude': '30', 'longitude': 0}},
    {'coordinates': {'latitude': 0}}, {'coordinates': []}, {'coordinates': {'latitude': 30.1234567, 'longitude': 0}},
    {'coordinates': {'latitude': float('nan'), 'longitude': 0}}, {'coordinates': {'latitude': 0, 'longitude': float('inf')}},
    {'startDate': '2025-02-29'}, {'startDate': True}, {'endDate': '2025-01-01'},
    {'startDate': '2025-02-01', 'endDate': '2025-01-31'}, {'journeyId': []}, {'journeyId': ''},
])
def test_invalid_create_has_no_business_writes(app, changes):
    client, headers = login(app)
    before = snapshot(app)
    result = client.post(PREFIX, json=payload(**changes), headers=headers)
    assert result.status_code == 400, result.json
    assert snapshot(app) == before


@pytest.mark.parametrize('query', ['extra=x', 'scope=all', 'owner=unknown', 'status=bad', 'year=0', 'year=0000',
    'year=2026&year=2025', 'limit=0', 'limit=201', 'limit=true', 'offset=-1', 'offset=3001', 'journeyId=', 'owner=member1&owner=member2'])
def test_invalid_filter_query(app, query):
    client, _ = login(app)
    assert client.get(PREFIX + '?' + query).status_code == 400


def test_create_replay_conflict_deleted_gone_and_bound_tombstones(app, monkeypatch):
    client, headers = login(app)
    item, original = create(client, headers)
    changed = client.patch(path(item), json={'revision': 1, 'name': '新的名称'}, headers=headers).json['place']
    before = snapshot(app)
    replay = client.post(PREFIX, json=original, headers=headers)
    assert replay.json == {'place': changed, 'replayed': True} and replay.status_code == 200
    assert snapshot(app) == before
    assert client.post(PREFIX, json={**original, 'name': '不一致'}, headers=headers).status_code == 409
    deletion = client.delete(path(item), json={'revision': 2}, headers=headers)
    assert deletion.json == {'deleted': True, 'id': item['id'], 'revision': 3, 'replayed': False}
    assert client.get(path(item)).status_code == 404
    assert client.post(PREFIX, json=original, headers=headers).status_code == 410
    assert client.delete(path(item), json={'revision': 2}, headers=headers).json['replayed']
    assert client.delete(path(item), json={'revision': 1}, headers=headers).status_code == 409
    with connection(app) as con:
        row = con.execute('SELECT * FROM journey_places').fetchone()
        assert row['name'] == row['city'] == row['country'] == ''
        assert row['latitude_e6'] is None and row['journey_id'] is None and row['deleted_at']
        assert row['request_id'] == original['requestId'] and len(row['payload_digest']) == 64
    monkeypatch.setattr(places, 'MAX_PLACE_RECORDS', 1)
    assert client.post(PREFIX, json=payload(), headers=headers).status_code == 409
    assert client.post(PREFIX, json=original, headers=headers).status_code == 410


@pytest.mark.parametrize('bad', [True, False, 0, -1, 1.0, '1', None])
def test_revision_is_strict_and_cas_conflicts(app, bad):
    client, headers = login(app)
    item, _ = create(client, headers)
    before = snapshot(app)
    assert client.patch(path(item), json={'revision': bad, 'name': '改名'}, headers=headers).status_code == 400
    assert client.delete(path(item), json={'revision': bad}, headers=headers).status_code == 400
    assert snapshot(app) == before


def test_trip_delete_unlinks_increments_revision_preserves_visit_and_replay(app):
    client, headers = login(app)
    journey = create_journey(client, headers)
    document, _ = upload_document(client, headers, journey['id'])
    item, original = create(client, headers, journeyId=journey['id'], status='visited', confirmVisited=True,
        visibility='shared', coordinates={'latitude': 30, 'longitude': 120})
    trip = client.get('/api/journeys/' + journey['id']).json['trip']
    assert client.delete('/api/items/trips/' + journey['tripId'], json={'revision': trip['revision']}, headers=headers).status_code == 200
    current = client.get(path(item)).json['place']
    assert current['journeyId'] is None and current['journey'] is None and current['revision'] == 2
    assert current['visitedConfirmedAt'] == item['visitedConfirmedAt'] and current['visitedConfirmedBy'] == 'member1'
    assert current['status'] == 'visited' and current['visibility'] == 'shared'
    assert client.patch(path(item), json={'revision': 1, 'visibility': 'private'}, headers=headers).status_code == 409
    assert client.delete(path(item), json={'revision': 1}, headers=headers).status_code == 409
    replay = client.post(PREFIX, json=original, headers=headers)
    assert replay.status_code == 200 and replay.json == {'place': current, 'replayed': True}
    assert client.post(PREFIX, json={**original, 'requestId': secrets.token_hex(16)}, headers=headers).status_code == 404
    assert client.get(document['downloadUrl']).status_code == 200


def test_delete_place_does_not_delete_journey_or_document_and_explicit_unlink_once(app):
    client, headers = login(app)
    journey = create_journey(client, headers)
    document, _ = upload_document(client, headers, journey['id'])
    item, _ = create(client, headers, journeyId=journey['id'])
    detached = client.patch(path(item), json={'revision': 1, 'journeyId': None}, headers=headers).json['place']
    assert detached['revision'] == 2
    assert client.delete(path(item), json={'revision': 2}, headers=headers).status_code == 200
    assert client.get('/api/journeys/' + journey['id']).status_code == 200
    assert client.get(document['downloadUrl']).status_code == 200


def test_concurrent_create_and_update_are_serialized(app):
    client, headers = login(app)
    clients = [clone(app, client), clone(app, client)]
    value = payload()
    barrier = threading.Barrier(2)
    def write(c):
        barrier.wait(timeout=5)
        return c.post(PREFIX, json=value, headers=headers)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(write, clients))
    assert sorted(r.status_code for r in results) == [200, 201]
    item = results[0].json['place']
    assert len({r.json['place']['id'] for r in results}) == 1
    barrier = threading.Barrier(2)
    def update(pair):
        index, c = pair
        barrier.wait(timeout=5)
        return c.patch(path(item), json={'revision': 1, 'name': '并发' + str(index)}, headers=headers)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(update, enumerate(clients)))
    assert sorted(r.status_code for r in results) == [200, 409]
    assert client.get(path(item)).json['place']['revision'] == 2
    with connection(app) as con:
        assert con.execute("SELECT count(*) FROM audit WHERE action='journey_place_created'").fetchone()[0] == 1


def test_concurrent_trip_delete_and_place_edit_preserve_fk_and_confirmation(app):
    client, headers = login(app)
    journey = create_journey(client, headers)
    item, _ = create(client, headers, journeyId=journey['id'], status='visited', confirmVisited=True)
    trip = client.get('/api/journeys/' + journey['id']).json['trip']
    delete_client, edit_client = clone(app, client), clone(app, client)
    barrier = threading.Barrier(2)
    def remove_trip():
        barrier.wait(timeout=5)
        return delete_client.delete('/api/items/trips/' + journey['tripId'], json={'revision': trip['revision']}, headers=headers)
    def edit_place():
        barrier.wait(timeout=5)
        return edit_client.patch(path(item), json={'revision': 1, 'name': '已确认的新名称', 'confirmVisited': True}, headers=headers)
    with ThreadPoolExecutor(2) as pool:
        deletion, change = pool.submit(remove_trip), pool.submit(edit_place)
        deletion, change = deletion.result(), change.result()
    assert deletion.status_code == 200 and change.status_code in (200, 409)
    current = client.get(path(item)).json['place']
    assert current['journeyId'] is None and current['journey'] is None and current['status'] == 'visited'
    if change.status_code == 200:
        assert current['revision'] == 3 and current['name'] == '已确认的新名称'
        assert current['visitedConfirmedAt'] == change.json['place']['visitedConfirmedAt']
    else:
        assert current['revision'] == 2 and current['name'] == item['name']
        assert current['visitedConfirmedAt'] == item['visitedConfirmedAt']
    with connection(app) as con:
        assert con.execute('PRAGMA foreign_key_check').fetchall() == []


def test_shared_visibility_revoked_after_guard_is_not_returned(app):
    @app.before_request
    def unshare():
        if request.headers.get('X-Synthetic-Unshare'):
            with connection(app) as con:
                con.execute("UPDATE journey_places SET visibility='private',revision=revision+1 WHERE owner='member1'")
    client, headers = login(app)
    partner, ph = login(app, 2)
    item, _ = create(client, headers, visibility='shared')
    assert partner.get(path(item)).status_code == 200
    assert partner.get(path(item), headers={**ph, 'X-Synthetic-Unshare': '1'}).status_code == 404
    assert partner.get(PREFIX).json['total'] == 0


@pytest.mark.parametrize('change', [{'requestId': 'a' * 32}, {'owner': 'member2'}, {'coordinatePrecision': 'exact'}, {'force': True}])
def test_patch_rejects_receipt_owner_and_projection_fields(app, change):
    client, headers = login(app)
    item, _ = create(client, headers)
    before = snapshot(app)
    assert client.patch(path(item), json={'revision': 1, 'name': '改变', **change}, headers=headers).status_code == 400
    assert snapshot(app) == before


def test_quota_check_is_atomic(app, monkeypatch):
    client, headers = login(app)
    monkeypatch.setattr(places, 'MAX_PLACE_RECORDS', 1)
    clients = [clone(app, client), clone(app, client)]
    barrier = threading.Barrier(2)
    def write(c):
        value = payload()
        barrier.wait(timeout=5)
        return c.post(PREFIX, json=value, headers=headers)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(write, clients))
    assert sorted(r.status_code for r in results) == [201, 409]
    assert client.get(PREFIX).json['total'] == 1


def test_audit_failure_rolls_back_place_and_receipt(app):
    client, headers = login(app)
    with connection(app) as con:
        con.execute("CREATE TRIGGER reject_place_audit BEFORE INSERT ON audit WHEN NEW.action='journey_place_created' BEGIN SELECT RAISE(ABORT,'synthetic rollback'); END")
    value = payload()
    before = snapshot(app)
    with pytest.raises(sqlite3.IntegrityError, match='synthetic rollback'):
        client.post(PREFIX, json=value, headers=headers)
    assert snapshot(app) == before
    with connection(app) as con:
        con.execute('DROP TRIGGER reject_place_audit')
    assert client.post(PREFIX, json=value, headers=headers).status_code == 201


def test_all_routes_reject_tv_anonymous_csrf_and_wrong_origin(app):
    client, headers = login(app)
    item, _ = create(client, headers, visibility='shared')
    tv = app.test_client()
    pairing = tv.post('/api/pair/start', json={}).json
    assert client.post('/api/pair/approve', json={'code': pairing['code'], 'name': '合成电视', 'focus': 'shared'}, headers=headers).status_code == 200
    assert tv.post('/api/pair/poll', json={'secret': pairing['secret']}).json['approved']
    routes = [('get', PREFIX, None), ('get', PREFIX + '?extra=x', None), ('get', path(item), None),
              ('post', PREFIX, payload()), ('patch', path(item), {'revision': 1, 'name': '改名'}), ('delete', path(item), {'revision': 1})]
    for method, endpoint, data in routes:
        assert getattr(tv, method)(endpoint, json=data, headers=headers).status_code == 403
        assert getattr(app.test_client(), method)(endpoint, json=data, headers=headers).status_code == 401
    assert client.post(PREFIX, json=payload()).status_code == 403
    assert client.post(PREFIX, json=payload(), headers={**headers, 'Origin': 'https://outside.invalid'}).status_code == 403
    assert client.post(PREFIX, data='not-json', headers=headers).status_code == 415
    assert item['id'] not in tv.get('/api/state').get_data(as_text=True)


@pytest.mark.parametrize('method', ['get-list', 'get', 'post', 'patch', 'delete'])
def test_revoke_after_global_guard_is_rechecked_in_transaction(app, method):
    @app.before_request
    def revoke():
        if request.headers.get('X-Synthetic-Revoke') == '1':
            with connection(app) as con:
                con.execute("UPDATE users SET auth_version=auth_version+1 WHERE id='member1'")
    client, headers = login(app)
    item, _ = create(client, headers)
    before = snapshot(app)
    endpoint = PREFIX if method in {'get-list', 'post'} else path(item)
    data = payload() if method == 'post' else {'revision': 1, **({'name': '撤销后'} if method == 'patch' else {})}
    verb = 'get' if method == 'get-list' else method
    result = getattr(client, verb)(endpoint, json=data, headers={**headers, 'X-Synthetic-Revoke': '1'})
    assert result.status_code == 401
    assert snapshot(app) == before


def test_guard_household_mismatch_is_denied(app):
    @app.before_request
    def changed_household():
        if request.headers.get('X-Synthetic-Household'):
            g.actor = {**g.actor, 'householdId': 'wrong-household'}
    client, headers = login(app)
    assert client.post(PREFIX, json=payload(), headers={**headers, 'X-Synthetic-Household': '1'}).status_code == 401
    assert client.get(PREFIX).json['total'] == 0


def test_two_households_same_place_id_and_request_key_remain_isolated(app, monkeypatch):
    primary, headers = login(app)
    invitation = primary.post('/api/spaces/invitations', json={}, headers=headers).json['invitation']
    child = app.test_client()
    result = child.post('/api/spaces/redeem', json={'invitation': invitation, 'name': '合成第二家庭', 'slug': 'places-second',
        'MEMBER1_PASSWORD': PASSWORD, 'MEMBER2_PASSWORD': PASSWORD})
    assert result.status_code == 201
    assert child.get(result.json['entry']).status_code == 303
    child, child_headers = login(app, client=child)
    main_journey = create_journey(primary, headers)
    assert child.post(PREFIX, json=payload(journeyId=main_journey['id']), headers=child_headers).status_code == 404
    assert child.get(PREFIX, query_string={'journeyId': main_journey['id']}).status_code == 404
    original = secrets.token_hex
    with monkeypatch.context() as change:
        change.setattr(places.secrets, 'token_hex', lambda n: 'e' * 24 if n == 12 else original(n))
        first, _ = create(primary, headers, requestId='a' * 32, name='MAIN-PRIVATE-PLACE')
        second, _ = create(child, child_headers, requestId='a' * 32, name='CHILD-PRIVATE-PLACE')
    assert first['id'] == second['id']
    assert 'MAIN-PRIVATE-PLACE' not in child.get(PREFIX).get_data(as_text=True)
    assert 'CHILD-PRIVATE-PLACE' not in primary.get(PREFIX).get_data(as_text=True)
    assert child.get(path(first)).json['place']['name'] == 'CHILD-PRIVATE-PLACE'
    child.set_cookie('session', primary.get_cookie('session').value)
    assert child.get(PREFIX).status_code == 401


def test_schema_initialization_is_explicit_repeatable_and_preserves_receipts(app, tmp_path):
    client, headers = login(app)
    active, _ = create(client, headers)
    deleted, original = create(client, headers)
    assert client.delete(path(deleted), json={'revision': 1}, headers=headers).status_code == 200
    with connection(app) as con:
        before = [tuple(r) for r in con.execute('SELECT * FROM journey_places ORDER BY id')]
        places.initialize_journey_places(con)
        assert [tuple(r) for r in con.execute('SELECT * FROM journey_places ORDER BY id')] == before
        backup = sqlite3.connect(tmp_path / 'places-backup.sqlite3')
        con.backup(backup)
        assert backup.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert backup.execute('PRAGMA foreign_key_check').fetchall() == []
        assert backup.execute('SELECT count(*) FROM journey_places').fetchone()[0] == 2
        assert backup.execute('SELECT request_id FROM journey_places WHERE id=?', (deleted['id'],)).fetchone()[0] == original['requestId']
        backup.close()
        con.execute('BEGIN IMMEDIATE')
        with pytest.raises(RuntimeError, match='clean transaction'):
            places.initialize_journey_places(con)
        con.rollback()
    assert client.get(path(active)).status_code == 200


def test_module_is_registered_and_initialized_by_production_factory(tmp_path):
    from deploy.check_finance_accounts_migration import BASE_TABLES, NEW_TABLES
    application = app_module.create_app({'TESTING': True, 'DATA_DIR': str(tmp_path / 'unwired'),
        'SECRET_KEY': 'synthetic-unwired-place-secret', 'SESSION_COOKIE_SECURE': False,
        'MEMBER1_PASSWORD': PASSWORD, 'MEMBER2_PASSWORD': PASSWORD})
    assert sum(rule.rule.startswith(PREFIX) for rule in application.url_map.iter_rules()) == 5
    with connection(application) as con:
        assert con.execute("SELECT 1 FROM sqlite_master WHERE name='journey_places'").fetchone() is not None
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        assert len(BASE_TABLES | NEW_TABLES) == 58
        assert tables == BASE_TABLES | NEW_TABLES


def test_initializer_requires_foreign_keys_and_existing_parent_schema():
    con = sqlite3.connect(':memory:')
    with pytest.raises(RuntimeError, match='foreign keys'):
        places.initialize_journey_places(con)
    con.execute('PRAGMA foreign_keys=ON')
    with pytest.raises(RuntimeError, match='users and journeys'):
        places.initialize_journey_places(con)
    assert con.execute('SELECT count(*) FROM sqlite_master').fetchone()[0] == 0
    con.close()
