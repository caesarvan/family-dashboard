"""Both real provider adapters against fake HTTP; no real calendar is changed."""
import json

import pytest

from calendar_publish import event_snapshot
from cloud_providers import ProviderError
from test_calendar_publish import env, queue, publication, update_local


def hold_timing(app):
    with app.extensions['cloud_accounts'].db() as con:
        original = json.loads(con.execute("SELECT data FROM entities WHERE id='event-1'").fetchone()[0])
        original.update(start='2026-10-01T01:00:00+00:00', end='2026-10-01T04:00:00+00:00', allDay=False,
                        note='Departure 10:00 Asia/Tokyo; arrival 12:00 Asia/Shanghai',
                        journeyId='journey-1', tripId='trip-1', workflowKey='event:overview',
                        travelTiming={'schemaVersion': 2, 'kind': 'flight', 'segmentKey': 'flight-1'})
        con.execute("UPDATE entities SET data=?,revision=revision+1 WHERE id='event-1'", (json.dumps(original),))
        con.execute("UPDATE calendar_publications SET status='needs_review',review_required=1,next_attempt=0")
        return original


def review(env, rid):
    result = env[1].post('/api/calendar-publish/publications/' + rid + '/review-preview', json={}, headers=env[2])
    assert result.status_code == 200, result.json
    return result.json


def confirm_review(env, rid, payload):
    return env[1].post('/api/calendar-publish/publications/' + rid + '/review-confirm', json={'previewToken': payload['previewToken']}, headers=env[2])


def test_timing_change_requires_explicit_review_even_after_pause(env):
    app, client, headers, remote, _ = env
    rid = queue(env)
    publisher = app.extensions['calendar_publish']
    publisher.process(rid)
    hold_timing(app)
    before = len(remote.calls)
    publisher.process(rid)
    assert len(remote.calls) == before
    assert client.post(f'/api/calendar-publish/publications/{rid}/retry', json={}, headers=headers).status_code == 409
    assert client.post(f'/api/calendar-publish/publications/{rid}/pause', json={}, headers=headers).status_code == 200
    assert client.post(f'/api/calendar-publish/publications/{rid}/resume', json={}, headers=headers).status_code == 409
    assert queue(env) == rid
    assert publication(env)['reviewRequired'] == 1
    preview = review(env, rid)
    assert preview['remote']['allDay'] is True and preview['local']['allDay'] is False
    assert not any(call[0] in {'POST', 'PATCH', 'DELETE'} for call in remote.calls[before:])
    assert confirm_review(env, rid, preview).status_code == 200
    publisher.process(rid)
    assert publication(env)['status'] == 'published'
    assert publication(env)['reviewRequired'] == 0
    assert remote.created == 1 and remote.patched == 1


def test_uncertain_old_create_is_recovered_before_new_timing(env):
    app, _, _, remote, _ = env
    rid = queue(env)
    remote.lose_create = True
    publisher = app.extensions['calendar_publish']
    publisher.process(rid)
    assert remote.created == 1 and publication(env)['status'] == 'retry'
    hold_timing(app)
    preview = review(env, rid)
    assert preview['previous']['allDay'] is True
    assert preview['remote']['allDay'] is True
    assert confirm_review(env, rid, preview).status_code == 200
    publisher.process(rid)
    assert publication(env)['status'] == 'published'
    assert remote.created == 1 and remote.patched == 1


def test_review_rejects_stale_local_revision_and_other_member(env):
    app, client, headers, remote, _ = env
    rid = queue(env)
    hold_timing(app)
    preview = review(env, rid)
    update_local(app, 'Independent latest edit')
    assert confirm_review(env, rid, preview).status_code == 409
    assert publication(env)['reviewRequired'] == 1
    assert not remote.created and not remote.patched
    other = app.test_client()
    assert other.post('/api/login', json={'username': 'member2', 'password': 'testing-password-two'}).status_code == 200
    other_headers = {'X-CSRF-Token': other.get('/api/me').json['csrf']}
    assert other.post(f'/api/calendar-publish/publications/{rid}/review-preview', json={}, headers=other_headers).status_code == 404
    assert other.post(f'/api/calendar-publish/publications/{rid}/review-confirm', json={'previewToken': preview['previewToken']}, headers=other_headers).status_code == 409
    assert client.post(f'/api/calendar-publish/publications/{rid}/review-confirm', json={'previewToken': 'forged'}, headers=headers).status_code == 400


def test_review_of_not_yet_created_event_preserves_stable_publication_id(env):
    app, _, _, remote, _ = env
    rid = queue(env)
    hold_timing(app)
    preview = review(env, rid)
    assert preview['remote'] is None
    assert confirm_review(env, rid, preview).status_code == 200
    app.extensions['calendar_publish'].process(rid)
    assert publication(env)['id'] == rid and publication(env)['status'] == 'published'
    assert remote.created == 1 and remote.patched == 0


def test_late_worker_error_cannot_remove_timing_review(env):
    app, _, _, _, _ = env
    rid = queue(env)
    hold_timing(app)
    app.extensions['calendar_publish']._set_error(rid, ProviderError('delayed synthetic failure', 502), 1)
    assert publication(env)['status'] == 'needs_review' and publication(env)['reviewRequired'] == 1


def test_remote_changes_after_review_are_not_silently_overwritten(env):
    app, _, _, remote, provider = env
    rid = queue(env)
    app.extensions['calendar_publish'].process(rid)
    hold_timing(app)
    preview = review(env, rid)
    record = next(iter(remote.records.values()))
    record['@odata.etag' if provider == 'microsoft' else 'etag'] = '"someone-edited"'
    assert confirm_review(env, rid, preview).status_code == 200
    app.extensions['calendar_publish'].process(rid)
    assert publication(env)['status'] == 'conflict'
    assert remote.created == 1 and remote.patched == 0


@pytest.mark.parametrize('local_changed', [False, True])
def test_deleted_remote_is_not_recreated_by_polling_or_local_update(env, local_changed):
    app, _, _, remote, _ = env
    rid = queue(env)
    app.extensions['calendar_publish'].process(rid)
    remote.records.clear()
    if local_changed:
        update_local(app, 'Local change after remote deletion')
    app.extensions['calendar_publish'].process(rid)
    assert publication(env)['status'] == 'conflict'
    assert remote.created == 1 and remote.patched == 0 and not remote.records


def test_all_day_projection_uses_local_dates_and_exclusive_checkout(env):
    app, _, _, _, provider = env
    event = {'title': 'Synthetic two-night stay', 'location': 'Hotel', 'note': 'Check-out is exclusive', 'allDay': True,
             'start': '2026-10-01T00:00:00+14:00', 'end': '2026-10-03T00:00:00+14:00',
             'startDate': '2026-10-01', 'endDateExclusive': '2026-10-03'}
    snapshot = event_snapshot(event)
    assert snapshot['start'] == '2026-10-01T00:00:00+08:00'
    assert snapshot['end'] == '2026-10-03T00:00:00+08:00'
    account = app.extensions['cloud_accounts'].account('account-1', 'member1')
    adapter = app.extensions['cloud_accounts'].active_provider(account)
    payload = adapter.publication_payload(snapshot, 'a' * 64, 'b' * 64, creating=True)
    if provider == 'google':
        assert payload['start'] == {'date': '2026-10-01'} and payload['end'] == {'date': '2026-10-03'}
    else:
        assert payload['start']['dateTime'].startswith('2026-10-01T00:00:00')
        assert payload['end']['dateTime'].startswith('2026-10-03T00:00:00')


def test_ordinary_event_edits_preserve_managed_timing_and_reject_injection(env):
    app, client, headers, _, _ = env
    queue(env)
    original = hold_timing(app)
    changed = client.patch('/api/items/events/event-1', json={'revision': 2, 'title': 'Independent title', 'note': 'My note'}, headers=headers)
    assert changed.status_code == 200, changed.json
    with app.extensions['cloud_accounts'].db() as con:
        row = con.execute("SELECT data,revision FROM entities WHERE id='event-1'").fetchone()
        saved = json.loads(row['data'])
        assert saved['travelTiming'] == original['travelTiming']
        assert saved['start'] == original['start'] and saved['end'] == original['end']
        assert saved['note'] == 'My note' and saved['workflowKey'] == 'event:overview'
        revision = row['revision']
    for patch in [{'start': '2026-10-01T03:00:00Z'}, {'allDay': True}, {'travelTiming': {}}, {'tripId': ''}, {'endDateExclusive': '2026-10-04'}]:
        result = client.patch('/api/items/events/event-1', json={'revision': revision, **patch}, headers=headers)
        assert result.status_code == 409, result.json
    result = client.post('/api/items/events', json={**original, 'travelTiming': {'schemaVersion': 2}}, headers=headers)
    assert result.status_code == 400


def test_detached_travel_event_becomes_editable_without_stale_timing_metadata(env):
    app, client, headers, _, _ = env
    queue(env)
    hold_timing(app)
    with app.extensions['cloud_accounts'].db() as con:
        con.execute("DELETE FROM journey_links WHERE entity_id='event-1'")
        row = con.execute("SELECT data FROM entities WHERE id='event-1'").fetchone()
        value = json.loads(row['data'])
        value.pop('journeyId', None)
        value['tripId'] = ''
        con.execute("UPDATE entities SET data=? WHERE id='event-1'", (json.dumps(value),))
    result = client.patch('/api/items/events/event-1', json={'revision': 2, 'start': '2026-10-01T02:00:00Z'}, headers=headers)
    assert result.status_code == 200, result.json
    with app.extensions['cloud_accounts'].db() as con:
        saved = json.loads(con.execute("SELECT data FROM entities WHERE id='event-1'").fetchone()[0])
        assert 'travelTiming' not in saved and 'startDate' not in saved and 'endDateExclusive' not in saved
        assert saved['start'] == '2026-10-01T10:00:00+08:00'
