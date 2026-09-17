"""Source revision checks use actual SQLite, sessions and existing place receipts."""
import hashlib
import json
from contextlib import closing

import pytest
import journey_places
from test_journey_places import app, no_network, PREFIX, create, path, payload
from test_journey_documents import connection, create_journey, login


def snapshot(application):
    with closing(connection(application)) as con:
        return {name: [tuple(row) for row in con.execute('SELECT * FROM ' + name + ' ORDER BY rowid')]
                for name in ('journey_places', 'audit')}


def bump(client, headers, journey):
    current = client.get('/api/journeys/' + journey['id']).json
    plan = current['plan']; plan['title'] += '已变更'
    preview = client.post('/api/journeys/preview', json={'journeyId': current['id'], 'revision': current['revision'], 'plan': plan}, headers=headers)
    assert preview.status_code == 200, preview.json
    response = client.post('/api/journeys/apply', json={'previewToken': preview.json['previewToken'], 'idempotencyKey': 'new-plan-revision-key'}, headers=headers)
    assert response.status_code == 200, response.json
    return response.json


@pytest.mark.parametrize('method', ['POST', 'PATCH'])
def test_source_revision_conflict_preserves_place_and_audit(app, method):
    client, headers = login(app); journey = create_journey(client, headers)
    item, original = create(client, headers, journeyId=journey['id'], expectedJourneyRevision=journey['revision'])
    bump(client, headers, journey)
    before = snapshot(app)
    data = payload(name='不能写入', journeyId=journey['id'], expectedJourneyRevision=1)
    if method == 'PATCH': data = {'name': '不能写入', 'revision': item['revision'], 'expectedJourneyRevision': 1}
    result = client.open(path(item) if method == 'PATCH' else PREFIX, method=method, json=data, headers=headers)
    assert result.status_code == 409, result.json
    assert snapshot(app) == before


def test_matching_revision_create_update_and_replay_after_plan_change(app):
    client, headers = login(app); journey = create_journey(client, headers)
    item, original = create(client, headers, journeyId=journey['id'], expectedJourneyRevision=1)
    updated = client.patch(path(item), json={'revision': 1, 'expectedJourneyRevision': 1, 'city': '核对后的城市'}, headers=headers)
    assert updated.status_code == 200 and updated.json['place']['revision'] == 2
    bump(client, headers, journey); before = snapshot(app)
    replay = client.post(PREFIX, json=original, headers=headers)
    assert replay.status_code == 200 and replay.json['replayed'] is True
    assert replay.json['place']['city'] == '核对后的城市'
    assert snapshot(app) == before
    assert client.post(PREFIX, json={**original, 'expectedJourneyRevision': 2}, headers=headers).status_code == 409
    assert client.post(PREFIX, json={k: v for k, v in original.items() if k != 'expectedJourneyRevision'}, headers=headers).status_code == 409
    assert snapshot(app) == before


def test_old_digest_and_receipt_remain_byte_compatible(app):
    client, headers = login(app); journey = create_journey(client, headers)
    item, original = create(client, headers, journeyId=journey['id'])
    with closing(connection(app)) as con:
        row = dict(con.execute('SELECT * FROM journey_places WHERE id=?', (item['id'],)).fetchone())
    fields = ('name', 'country', 'city', 'latitude_e6', 'longitude_e6', 'status', 'journey_id', 'start_date', 'end_date', 'visibility', 'coordinate_disclosure')
    legacy_digest = hashlib.sha256(json.dumps({'place': {k: row[k] for k in fields}, 'confirmVisited': False}, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert row['payload_digest'] == legacy_digest
    bump(client, headers, journey)
    replay = client.post(PREFIX, json=original, headers=headers)
    assert replay.status_code == 200 and replay.json['replayed'] is True
    assert client.post(PREFIX, json={**original, 'expectedJourneyRevision': 1}, headers=headers).status_code == 409
    assert client.patch(path(item), json={'revision': 1, 'name': '普通手填仍可修改'}, headers=headers).status_code == 200


@pytest.mark.parametrize('value', [None, True, False, 0, -1, 1.5, '1', 2**53])
@pytest.mark.parametrize('method', ['POST', 'PATCH'])
def test_source_revision_requires_positive_safe_integer(app, value, method):
    client, headers = login(app); journey = create_journey(client, headers)
    item, _ = create(client, headers, journeyId=journey['id'])
    before = snapshot(app)
    data = payload(expectedJourneyRevision=value, journeyId=journey['id']) if method == 'POST' else {'revision': 1, 'name': '禁止', 'expectedJourneyRevision': value}
    result = client.open(PREFIX if method == 'POST' else path(item), method=method, json=data, headers=headers)
    assert result.status_code == 400 and snapshot(app) == before


@pytest.mark.parametrize('method', ['POST', 'PATCH'])
def test_source_revision_requires_linked_journey(app, method):
    client, headers = login(app); item, _ = create(client, headers); before = snapshot(app)
    data = payload(expectedJourneyRevision=1) if method == 'POST' else {'revision': 1, 'name': '禁止', 'expectedJourneyRevision': 1}
    result = client.open(PREFIX if method == 'POST' else path(item), method=method, json=data, headers=headers)
    assert result.status_code == 400 and snapshot(app) == before


def test_successful_creation_replays_after_parent_deletion_but_never_resurrects_place(app):
    client, headers = login(app); journey = create_journey(client, headers)
    item, original = create(client, headers, journeyId=journey['id'], expectedJourneyRevision=1)
    trip = client.get('/api/journeys/' + journey['id']).json['trip']
    result = client.delete('/api/items/trips/' + trip['id'], json={'revision': trip['revision']}, headers=headers)
    assert result.status_code == 200, result.json
    replay = client.post(PREFIX, json=original, headers=headers)
    assert replay.status_code == 200 and replay.json['place']['journeyId'] is None
    version = replay.json['place']['revision']
    assert client.delete(path(item), json={'revision': version}, headers=headers).status_code == 200
    before = snapshot(app)
    assert client.post(PREFIX, json=original, headers=headers).status_code == 410
    assert snapshot(app) == before


def test_changed_plan_committed_before_transaction_is_rejected(app, monkeypatch):
    client, headers = login(app); journey = create_journey(client, headers)
    original = journey_places.hashlib.sha256; changed = []
    def digest_then_change(value=b'', *args, **kwargs):
        result = original(value, *args, **kwargs)
        if b'"expectedJourneyRevision":1' in value and not changed:
            with closing(connection(app)) as other:
                other.execute('UPDATE journey_workflows SET revision=revision+1 WHERE id=?', (journey['id'],)); other.commit()
            changed.append(True)
        return result
    monkeypatch.setattr(journey_places.hashlib, 'sha256', digest_then_change)
    before = snapshot(app)
    response = client.post(PREFIX, json=payload(journeyId=journey['id'], expectedJourneyRevision=1), headers=headers)
    assert changed == [True] and response.status_code == 409
    assert snapshot(app) == before
