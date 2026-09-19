"""Real route registration and ZIP projection, including mid-export revocation."""
from contextlib import closing
import json
import secrets

import pytest

import app as application
import data_portability
from test_data_portability import unpack
from test_journey_documents import clone, connection, create_journey, login
from test_journey_places import app, create, no_network


def save_route(client, headers, journey, stops, title, visibility='private'):
    revision = client.get('/api/journeys/' + journey['id']).json['revision']
    payload = {'requestId': secrets.token_hex(16), 'title': title, 'journeyId': journey['id'],
               'expectedJourneyRevision': revision, 'visibility': visibility,
               'stops': [{'placeId': item['id'], 'expectedRevision': item['revision']} for item in stops]}
    result = client.post('/api/journey-routes', json=payload, headers=headers)
    assert result.status_code == 201, result.json
    return result.json['current'], payload


@pytest.mark.parametrize('include_shared', [False, True])
def test_route_export_uses_current_projection_and_explicit_shared_opt_in(app, include_shared):
    owner, headers = login(app)
    partner, ph = login(app, 2)
    journey = create_journey(owner, headers)
    private, _ = create(owner, headers, name='OWN_PRIVATE_POINT', journeyId=journey['id'],
                        coordinates={'latitude': 31.23456, 'longitude': 121.45678})
    shared, _ = create(owner, headers, name='COARSE_POINT', journeyId=journey['id'],
        visibility='shared', coordinateDisclosure='coarse', coordinates={'latitude': 30.12345, 'longitude': 120.12345})
    secret, _ = create(partner, ph, name='PARTNER_PRIVATE_POINT', journeyId=journey['id'])
    revoked, _ = create(partner, ph, name='REVOKED_POINT', journeyId=journey['id'],
        visibility='shared', coordinateDisclosure='exact', coordinates={'latitude': 52.12345, 'longitude': 2.12345})
    own_private, private_request = save_route(owner, headers, journey, [private, private], 'OWN_PRIVATE_ROUTE')
    own_shared, shared_request = save_route(owner, headers, journey, [shared, revoked, shared], 'OWN_SHARED_ROUTE', 'shared')
    partner_shared, _ = save_route(partner, ph, journey, [shared], 'PARTNER_SHARED_ROUTE', 'shared')
    partner_private, _ = save_route(partner, ph, journey, [secret], 'PARTNER_PRIVATE_ROUTE')
    removed, _ = save_route(owner, headers, journey, [private], 'REMOVED_ROUTE')
    deleted = owner.delete('/api/journey-routes/' + removed['route']['id'], headers=headers, json={
        'requestId': secrets.token_hex(16), 'revision': removed['route']['revision'],
        'sourceVersion': removed['route']['sourceVersion']})
    assert deleted.status_code == 200, deleted.json
    hidden = partner.patch('/api/journey-places/' + revoked['id'], headers=ph,
                           json={'revision': revoked['revision'], 'visibility': 'private'})
    assert hidden.status_code == 200, hidden.json
    summary = owner.get('/api/portability/summary')
    assert summary.status_code == 200
    assert summary.json['personal']['journeyRoutes'] == 2
    assert summary.json['shared']['journeyRoutes'] == 1
    snapshot, files = unpack(owner.post('/api/portability/export', json={'includeShared': include_shared}, headers=headers))
    mine = {item['title']: item for item in snapshot['personal']['journeyRoutes']}
    assert set(mine) == {'OWN_PRIVATE_ROUTE', 'OWN_SHARED_ROUTE'}
    assert mine['OWN_PRIVATE_ROUTE']['stops'][0]['place']['coordinates'] == private['coordinates']
    assert len(mine['OWN_PRIVATE_ROUTE']['stops']) == 2
    assert mine['OWN_PRIVATE_ROUTE']['segments'] == [{'fromIndex': 0, 'toIndex': 1}]
    route = mine['OWN_SHARED_ROUTE']
    assert route['stops'][1] == {'index': 1, 'state': 'unavailable'}
    assert route['stops'][0]['place']['coordinates'] == {'latitude': 30.1, 'longitude': 120.1}
    assert route['segments'] == []
    assert set(route) == {'id', 'title', 'journeyId', 'visibility', 'revision', 'stops', 'segments'}
    if include_shared:
        assert [item['id'] for item in snapshot['shared']['journeyRoutes']] == [partner_shared['route']['id']]
    else:
        assert 'shared' not in snapshot
    joined = b''.join(files.values())
    for forbidden in ('PARTNER_PRIVATE_ROUTE', 'PARTNER_PRIVATE_POINT', 'REVOKED_POINT', revoked['id'],
                      'REMOVED_ROUTE', removed['route']['id'], partner_private['route']['id'],
                      private_request['requestId'], shared_request['requestId'],
                      own_shared['route']['sourceVersion'], own_private['route']['sourceVersion']):
        assert forbidden.encode() not in joined
    assert 'sourceVersion' not in json.dumps(snapshot['personal']['journeyRoutes'])
    assert 'canManage' not in json.dumps(snapshot['personal']['journeyRoutes'])
    assert 'sharedCoordinates' not in json.dumps(snapshot['personal']['journeyRoutes'])
    assert snapshot['coverage']['journeyRoutes'] == 'current_visible_ordered_stops_without_receipts'


@pytest.mark.parametrize('change', ['route_private', 'point_private', 'point_coordinates', 'route_delete', 'session_revoke'])
def test_export_rechecks_current_route_places_and_session_before_return(app, monkeypatch, change):
    owner, headers = login(app)
    partner, ph = login(app, 2)
    journey = create_journey(owner, headers)
    point, _ = create(partner, ph, name='LATER_WITHDRAWN', journeyId=journey['id'],
        visibility='shared', coordinateDisclosure='exact', coordinates={'latitude': 31.23, 'longitude': 121.45})
    route, _ = save_route(partner, ph, journey, [point], 'LATER_WITHDRAWN_ROUTE', 'shared')
    original = data_portability.json.JSONEncoder.iterencode
    changed = []

    def encode(encoder, value, *args, **kwargs):
        for chunk in original(encoder, value, *args, **kwargs):
            if isinstance(value, dict) and 'personal' in value and not changed:
                with closing(connection(app)) as con:
                    if change == 'route_private':
                        con.execute("UPDATE journey_routes SET visibility='private',revision=revision+1 WHERE id=?", (route['route']['id'],))
                    elif change == 'point_private':
                        con.execute("UPDATE journey_places SET visibility='private',revision=revision+1 WHERE id=?", (point['id'],))
                    elif change == 'point_coordinates':
                        con.execute("UPDATE journey_places SET coordinate_disclosure='hidden',revision=revision+1 WHERE id=?", (point['id'],))
                    elif change == 'route_delete':
                        con.execute("UPDATE journey_routes SET deleted_at='now',revision=revision+1 WHERE id=?", (route['route']['id'],))
                    else:
                        con.execute("DELETE FROM member_sessions WHERE owner='member1'")
                    con.commit()
                changed.append(True)
            yield chunk

    monkeypatch.setattr(data_portability.json.JSONEncoder, 'iterencode', encode)
    response = owner.post('/api/portability/export', json={'includeShared': True}, headers=headers)
    assert changed == [True]
    assert response.status_code == (401 if change == 'session_revoke' else 409), response.json
    assert response.mimetype == 'application/json'
    assert 'LATER_WITHDRAWN' not in response.get_data(as_text=True)
    assert data_portability.EXPORT_SLOT.acquire(blocking=False)
    data_portability.EXPORT_SLOT.release()


def test_production_registration_restarts_with_route_order_and_receipt_intact(app):
    client, headers = login(app)
    journey = create_journey(client, headers)
    first, _ = create(client, headers, name='FIRST_STOP', journeyId=journey['id'])
    second, _ = create(client, headers, name='SECOND_STOP', journeyId=journey['id'])
    detail, request = save_route(client, headers, journey, [second, first, second], 'ROUND_TRIP')
    with closing(connection(app)) as con:
        before = {table: [tuple(row) for row in con.execute('SELECT * FROM ' + table + ' ORDER BY rowid')]
                  for table in ('journey_routes', 'journey_route_stops', 'journey_route_operations')}
    restarted = application.create_app(dict(app.config))
    resumed = clone(restarted, client)
    assert resumed.get('/api/journey-routes/' + detail['route']['id']).json == detail
    receipt = resumed.get('/api/journey-routes/operations/' + request['requestId'])
    assert receipt.status_code == 200 and receipt.json['replayed'] is True
    assert receipt.json['current'] == detail
    with closing(connection(restarted)) as con:
        for table, rows in before.items():
            assert [tuple(row) for row in con.execute('SELECT * FROM ' + table + ' ORDER BY rowid')] == rows
