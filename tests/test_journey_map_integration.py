"""Real factory, sessions, persistent places and member ZIP export integration."""
from io import BytesIO
import json
from zipfile import ZipFile

from flask import request
import pytest

from test_journey_places import app, create, login, no_network, path
from test_journey_documents import connection, create_journey


def download(client, headers, shared=False):
    response = client.post('/api/portability/export', json={'includeShared': shared}, headers=headers)
    assert response.status_code == 200, response.get_data(as_text=True) if response.status_code != 200 else ''
    # The application after-request guard applies no-store to every API response.
    assert response.cache_control.no_store and not response.cache_control.public
    with ZipFile(BytesIO(response.data)) as archive:
        return json.loads(archive.read('data.json'))


@pytest.mark.parametrize('disclosure,projected,precision', [
    ('hidden', None, 'hidden'),
    ('coarse', {'latitude': 31.2, 'longitude': 121.5}, 'approximate'),
    ('exact', {'latitude': 31.234567, 'longitude': 121.456789}, 'exact'),
])
def test_personal_export_and_shared_export_use_same_coordinate_projection(app, disclosure, projected, precision):
    owner, headers = login(app)
    partner, partner_headers = login(app, 2)
    point = {'latitude': 31.234567, 'longitude': 121.456789}
    shared, _ = create(owner, headers, visibility='shared', coordinates=point, coordinateDisclosure=disclosure)
    private, _ = create(owner, headers, name='PRIVATE-PLACE-MUST-STAY-PRIVATE', coordinates=point)
    other, _ = create(partner, partner_headers, name='PARTNER-OWNED-PLACE')
    deleted, deleted_request = create(owner, headers, name='DELETED-PLACE')
    assert owner.delete(path(deleted), json={'revision': 1}, headers=headers).status_code == 200
    own = download(owner, headers, True)
    assert {p['id'] for p in own['personal']['journeyPlaces']} == {private['id'], shared['id']}
    assert own['shared']['journeyPlaces'] == []
    assert all(p['coordinates'] == point for p in own['personal']['journeyPlaces'])
    assert 'PARTNER-OWNED-PLACE' not in json.dumps(own)
    basic = download(partner, partner_headers)
    assert 'shared' not in basic and [p['id'] for p in basic['personal']['journeyPlaces']] == [other['id']]
    exported = download(partner, partner_headers, True)
    assert len(exported['shared']['journeyPlaces']) == 1
    actual = exported['shared']['journeyPlaces'][0]
    assert actual['id'] == shared['id'] and actual['coordinates'] == projected
    assert actual['coordinatePrecision'] == precision
    assert not {'requestId', 'payloadDigest', 'request_id', 'payload_digest', 'latitude_e6', 'longitude_e6', 'sharedCoordinates'} & actual.keys()
    encoded = json.dumps(exported)
    assert private['id'] not in encoded and 'PRIVATE-PLACE-MUST-STAY-PRIVATE' not in encoded
    assert deleted['id'] not in encoded and deleted_request['requestId'] not in encoded
    if disclosure != 'exact':
        assert '31.234567' not in encoded and '121.456789' not in encoded
    counts = partner.get('/api/portability/summary').json
    assert counts['personal']['journeyPlaces'] == 1 and counts['shared']['journeyPlaces'] == 1
    assert owner.patch(path(shared), json={'revision': 1, 'visibility': 'private'}, headers=headers).status_code == 200
    assert download(partner, partner_headers, True)['shared']['journeyPlaces'] == []


def test_confirmed_place_export_survives_trip_removal(app):
    client, headers = login(app)
    journey = create_journey(client, headers)
    place, _ = create(client, headers, journeyId=journey['id'], status='visited', confirmVisited=True)
    trip = client.get('/api/journeys/' + journey['id']).json['trip']
    assert client.delete('/api/items/trips/' + journey['tripId'], json={'revision': trip['revision']}, headers=headers).status_code == 200
    exported = download(client, headers)['personal']['journeyPlaces'][0]
    assert exported['id'] == place['id'] and exported['journeyId'] is None
    assert exported['revision'] == 2 and exported['visitedConfirmedAt'] == place['visitedConfirmedAt']


def test_export_rechecks_revoked_session_in_snapshot_transaction(app):
    @app.before_request
    def revoke_after_guard():
        if request.headers.get('X-Synthetic-Export-Revoke'):
            with connection(app) as con:
                con.execute("UPDATE users SET auth_version=auth_version+1 WHERE id='member1'")
    client, headers = login(app)
    create(client, headers, name='NO-STALE-EXPORT')
    response = client.post('/api/portability/export', json={}, headers={**headers, 'X-Synthetic-Export-Revoke': '1'})
    assert response.status_code == 401 and 'NO-STALE-EXPORT' not in response.get_data(as_text=True)


def test_classic_map_entry_scripts_are_local_and_loaded_before_navigation(app):
    response = app.test_client().get('/classic')
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert '/static/journey-map.css' in page
    assert page.index('/static/journey-map.js') < page.index('/static/product-shell.js')
    assert 'maps.googleapis.com' not in page
