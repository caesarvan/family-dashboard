"""Travel v2 boundaries use synthetic plans, temporary SQLite and no cloud I/O."""
from copy import deepcopy
from datetime import datetime
import json

import pytest

from journey_time import TimeIssue, point
from test_app import app, member
from test_journey_workflows import plan, preview, apply, detail, connection


def flight(**values):
    return {'key': 'outbound', 'kind': 'flight', 'title': '东京 → 檀香山',
            'departure': {'airport': 'HND', 'city': '东京', 'local': '2026-10-03T00:30', 'timeZone': 'Asia/Tokyo'},
            'arrival': {'airport': 'HNL', 'city': '檀香山', 'local': '2026-10-02T13:00', 'timeZone': 'Pacific/Honolulu'}, **values}


def v2(**values):
    return plan(schemaVersion=2, referenceTimezone='Asia/Shanghai', start='2026-10-02', end='2026-10-08',
        destinations=[{'key': 'tokyo', 'country': '日本', 'city': '东京', 'arrival': '2026-10-02', 'departure': '2026-10-03', 'timeZone': 'Asia/Tokyo'},
                      {'key': 'honolulu', 'country': '美国', 'city': '檀香山', 'arrival': '2026-10-02', 'departure': '2026-10-08', 'timeZone': 'Pacific/Honolulu'}],
        segments=[flight(), {'key': 'hotel', 'kind': 'stay', 'title': '示意住宿', 'propertyName': '示意酒店', 'address': '测试地址',
                            'timeZone': 'Pacific/Honolulu', 'checkInDate': '2026-10-02', 'checkOutDate': '2026-10-08'}], **values)


def create_v2(client, headers, value=None):
    p = preview(client, headers, value or v2())
    result = apply(client, headers, p)
    assert result.status_code == 201, result.json
    return detail(client, result.json['id'])


def segment_event(d, key='outbound'):
    return next(row for row in d['events'] if row['workflowKey'] == 'segment:' + key)


def edit_direct(app, event, **values):
    with connection(app) as con:
        data = json.loads(con.execute('SELECT data FROM entities WHERE id=?', (event['id'],)).fetchone()[0])
        data.update(values)
        con.execute('UPDATE entities SET data=?,revision=revision+1 WHERE id=?', (json.dumps(data), event['id']))


def test_dateline_flight_stay_date_semantics_and_ics(app):
    c, h = member(app)
    d = create_v2(c, h)
    event, stay = segment_event(d), segment_event(d, 'hotel')
    assert event['allDay'] is False
    assert event['start'] == '2026-10-02T15:30:00Z'
    assert event['end'] == '2026-10-02T23:00:00Z'
    assert (datetime.fromisoformat(event['end']) - datetime.fromisoformat(event['start'])).total_seconds() == 7.5 * 3600
    assert event['travelTiming']['startLocal'][:10] > event['travelTiming']['endLocal'][:10]
    assert stay['startDate'] == '2026-10-02' and stay['endDateExclusive'] == '2026-10-08'
    assert stay['travelTiming']['nights'] == 6
    assert stay['travelTiming']['checkInTime'] == ''
    ics = c.get(d['calendar']['icsUrl']).get_data(as_text=True).replace('\r\n ', '')
    assert 'DTSTART:20261002T153000Z' in ics and 'DTEND:20261002T230000Z' in ics
    assert 'DTEND;VALUE=DATE:20261008' in ics
    assert 'Asia/Tokyo' in ics and 'Pacific/Honolulu' in ics
    assert 'UID:' + event['id'] + '@household-journey' in ics


@pytest.mark.parametrize('local,zone_name,code', [
    ('2026-03-29T02:30', 'Europe/Berlin', 'nonexistent_local_time'),
    ('2026-10-25T02:30', 'Europe/Berlin', 'ambiguous_local_time'),
    ('2026-03-08T02:30', 'America/New_York', 'nonexistent_local_time'),
    ('2026-11-01T01:30', 'America/New_York', 'ambiguous_local_time'),
    ('2026-10-25T02:30', 'Not/AZone', 'invalid_timezone'),
])
def test_dst_never_guesses(local, zone_name, code):
    with pytest.raises(TimeIssue) as err:
        point({'local': local, 'timeZone': zone_name}, 'segments[0].departure')
    assert err.value.code == code
    if code == 'ambiguous_local_time':
        assert len(err.value.choices) == 2
        assert len({row['instant'] for row in err.value.choices}) == 2


def test_fold_selected_offsets_and_inconsistent_client_instant():
    early = point({'local': '2026-10-25T02:30', 'timeZone': 'Europe/Berlin', 'offsetMinutes': 120}, 'p')
    late = point({'local': '2026-10-25T02:30', 'timeZone': 'Europe/Berlin', 'offsetMinutes': 60}, 'p')
    assert early['instant'] == '2026-10-25T00:30:00Z' and late['instant'] == '2026-10-25T01:30:00Z'
    with pytest.raises(TimeIssue, match='UTC'):
        point({**early, 'instant': late['instant']}, 'p')
    with pytest.raises(TimeIssue, match='偏移'):
        point({**early, 'offsetMinutes': True}, 'p')


def test_dst_api_exposes_choices_and_never_writes(app):
    c, h = member(app)
    p = v2()
    p['segments'][0]['departure'] = {'local': '2026-10-25T02:30', 'timeZone': 'Europe/Berlin'}
    r = c.post('/api/journeys/preview', json={'plan': p}, headers=h)
    assert r.status_code == 400 and r.json['code'] == 'ambiguous_local_time'
    assert r.json['field'] == 'segments[0].departure'
    assert {row['offsetMinutes'] for row in r.json['choices']} == {60, 120}
    with connection(app) as con:
        assert con.execute('SELECT count(*) FROM entities').fetchone()[0] == 0


@pytest.mark.parametrize('kind', ['timed', 'date'])
def test_activity_modes_and_cross_dst_stay_nights(app, kind):
    c, h = member(app)
    p = v2()
    activity = {'key': 'activity', 'kind': 'activity', 'title': '活动'}
    if kind == 'timed':
        activity.update(start={'local': '2026-10-25T01:30', 'timeZone': 'Europe/Berlin'},
                        end={'local': '2026-10-25T03:30', 'timeZone': 'Europe/Berlin'})
    else:
        activity.update(dateRange={'startDate': '2026-10-24', 'endDateExclusive': '2026-10-26'}, timeZone='Europe/Berlin')
    p['segments'] = [activity, {'key': 'hotel', 'kind': 'stay', 'title': '酒店', 'timeZone': 'Europe/Berlin',
                               'checkInDate': '2026-10-24', 'checkOutDate': '2026-10-26'}]
    d = create_v2(c, h, p)
    event = segment_event(d, 'activity')
    assert segment_event(d, 'hotel')['travelTiming']['nights'] == 2
    if kind == 'timed':
        assert (datetime.fromisoformat(event['end']) - datetime.fromisoformat(event['start'])).total_seconds() == 3 * 3600
    else:
        assert event['allDay'] and event['endDateExclusive'] == '2026-10-26'


@pytest.mark.parametrize('mutate', [
    lambda p: p.update(schemaVersion=3),
    lambda p: p['segments'][1].update(checkOutDate='2026-10-02'),
    lambda p: p['segments'][1].update(checkInTime='25:00'),
    lambda p: p['segments'][0].update(arrival=deepcopy(p['segments'][0]['departure'])),
    lambda p: p['destinations'][0].pop('timeZone'),
    lambda p: p['segments'].append(deepcopy(p['segments'][0])),
    lambda p: p['segments'][0].update(destinationKey='absent'),
])
def test_invalid_v2_rejects_without_partial_records(app, mutate):
    c, h = member(app)
    p = v2()
    mutate(p)
    assert c.post('/api/journeys/preview', json={'plan': p}, headers=h).status_code == 400
    with connection(app) as con:
        assert con.execute('SELECT count(*) FROM journey_workflows').fetchone()[0] == 0


def test_manual_before_preview_edit_preserved_and_conflicting_change_requires_choice(app):
    c, h = member(app)
    d = create_v2(c, h)
    event = segment_event(d)
    edit_direct(app, event, title='日历中独立改名', location='独立地点')
    p = deepcopy(d['plan'])
    p['budget'] += 100
    first = preview(c, h, p, journeyId=d['id'], revision=d['revision'])
    assert first['canApply'] and {row['fieldGroup'] for row in first['summary']['preserved']} == {'title', 'location'}
    assert apply(c, h, first, 'keep-manual-fields').status_code == 200
    fresh = detail(c, d['id'])
    assert segment_event(fresh)['title'] == '日历中独立改名'
    p = deepcopy(fresh['plan'])
    p['segments'][0]['title'] = '旅行里再改名'
    conflict = preview(c, h, p, journeyId=d['id'], revision=fresh['revision'])
    assert conflict['canApply'] is False and conflict['previewToken'] is None
    assert conflict['summary']['conflicts'][0]['fieldGroup'] == 'title'
    selected = preview(c, h, p, journeyId=d['id'], revision=fresh['revision'], conflictResolutions={'segment:outbound': {'title': 'plan'}})
    assert selected['canApply']
    assert apply(c, h, selected, 'choose-plan-title').status_code == 200
    final = segment_event(detail(c, d['id']))
    assert final['id'] == event['id'] and final['title'] == '旅行里再改名' and final['location'] == '独立地点'


def test_v1_upgrade_conflicting_time_current_preserved_and_later_revision_guard(app):
    c, h = member(app)
    raw = plan(segments=[{'key': 'outbound', 'title': '旧全天', 'start': '2026-12-03', 'end': '2026-12-03'}])
    first = apply(c, h, preview(c, h, raw)).json
    d = detail(c, first['id'])
    old = segment_event(d)
    edit_direct(app, old, start='2026-12-04T00:00:00+08:00', end='2026-12-05T00:00:00+08:00')
    p = v2()
    pending = preview(c, h, p, journeyId=d['id'], revision=d['revision'])
    assert not pending['canApply']
    assert any(row['fieldGroup'] == 'timing' for row in pending['summary']['conflicts'])
    approved = preview(c, h, p, journeyId=d['id'], revision=d['revision'], conflictResolutions={'segment:outbound': {'timing': 'current'}})
    assert approved['canApply']
    assert apply(c, h, approved, 'keep-legacy-edited-time').status_code == 200
    updated = detail(c, d['id'])
    assert segment_event(updated)['start'] == '2026-12-04T00:00:00+08:00'
    assert segment_event(updated)['id'] == old['id']
    assert segment_event(updated)['note'] == old['note']
    same = preview(c, h, updated['plan'], journeyId=d['id'], revision=updated['revision'])
    edit_direct(app, segment_event(updated), title='预览后编辑')
    assert apply(c, h, same, 'after-preview-conflict').status_code == 409


def test_reschedule_explicit_fixed_unchanged_reorder_stable_cancel_restore(app):
    c, h = member(app)
    d = create_v2(c, h)
    old_ids = {row['workflowKey']: row['id'] for row in d['events']}
    p = deepcopy(d['plan'])
    p.update(start='2026-10-03', end='2026-10-09')
    p['segments'].reverse()
    p['segments'][1]['bookingState'] = 'cancelled'
    confirm = preview(c, h, p, journeyId=d['id'], revision=d['revision'])
    assert any(row['code'] == 'outside_trip_dates' for row in confirm['summary']['warnings'])
    assert apply(c, h, confirm, 'reschedule-fixed-dates').status_code == 200
    fresh = detail(c, d['id'])
    assert {row['workflowKey']: row['id'] for row in fresh['events']} == old_ids
    assert segment_event(fresh)['start'] == segment_event(d)['start']
    assert segment_event(fresh)['title'].startswith('[已取消]')
    fresh['plan']['segments'][1]['bookingState'] = 'idea'
    again = preview(c, h, fresh['plan'], journeyId=d['id'], revision=fresh['revision'])
    assert apply(c, h, again, 'restore-cancelled-plan').status_code == 200
    assert segment_event(detail(c, d['id']))['id'] == old_ids['segment:outbound']


def test_capabilities_and_downgrade_rejected(app):
    c, h = member(app)
    assert c.get('/api/journeys/templates').json['supportedSchemaVersions'] == [1, 2]
    assert c.get('/api/journeys').json['capabilities']['schemaVersions'] == [1, 2]
    d = create_v2(c, h)
    assert c.post('/api/journeys/preview', json={'plan': plan(), 'journeyId': d['id'], 'revision': d['revision']}, headers=h).status_code == 409


@pytest.mark.parametrize('time_zone,offset,instant', [('Asia/Kolkata', 330, '2026-10-01T03:30:00Z'), ('Asia/Kathmandu', 345, '2026-10-01T03:15:00Z')])
def test_fractional_offsets(time_zone, offset, instant):
    result = point({'local': '2026-10-01T09:00', 'timeZone': time_zone}, 'start')
    assert result['offsetMinutes'] == offset and result['instant'] == instant


def test_note_edit_and_new_timing_are_one_conflict_group(app):
    c, h = member(app)
    d = create_v2(c, h)
    event = segment_event(d)
    edit_direct(app, event, note='独立的时间说明')
    p = deepcopy(d['plan'])
    p['segments'][0]['departure'].update(local='2026-10-03T01:30')
    p['segments'][0]['departure'].pop('instant')
    result = preview(c, h, p, journeyId=d['id'], revision=d['revision'])
    assert not result['canApply']
    assert result['summary']['conflicts'][0]['fieldGroup'] == 'timing'
    assert 'note' in result['summary']['conflicts'][0]['current']


def test_v2_preview_replay_has_one_stable_event_set(app):
    c, h = member(app)
    approved = preview(c, h, v2())
    saved = apply(c, h, approved, 'v2-first-save')
    assert saved.status_code == 201
    before = detail(c, saved.json['id'])
    assert apply(c, h, approved, 'v2-first-save').json['replayed']
    assert apply(c, h, approved, 'v2-lost-response-new-key').json['replayed']
    after = detail(c, saved.json['id'])
    assert before == after


def test_cloud_hold_preserves_pending_remote_ids_and_locks_before_write(app, monkeypatch):
    from contextlib import contextmanager
    c, h = member(app)
    d = create_v2(c, h)
    event = segment_event(d)
    with connection(app) as con:
        con.execute("INSERT INTO calendar_publications(id,owner,journey_id,entity_id,source_id,account_id,provider,calendar_id,remote_id,etag,last_hash,pending_data,pending_hash,pending_revision,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ('pub', 'member1', d['id'], event['id'], 'synthetic-source', 'synthetic-account', 'google', 'synthetic-calendar', 'remote-event', 'etag-1', 'old-hash', '{"title":"old pending"}', 'pending-hash', 7, 'paused', 'now', 'now'))
    order = []
    @contextmanager
    def lock(account_id):
        assert account_id == 'synthetic-account'
        # Acquiring a write transaction here succeeds only if journey apply has
        # not already started its own write transaction on a different connection.
        with connection(app) as probe:
            probe.execute('BEGIN IMMEDIATE')
            probe.rollback()
        order.append('acquired')
        yield
        order.append('released')
    monkeypatch.setattr(app.extensions['cloud_accounts'], 'lock', lock)
    p = deepcopy(d['plan'])
    dep = p['segments'][0]['departure']
    dep.update(local='2026-10-02T15:30', timeZone='UTC')
    dep.pop('instant')
    dep.pop('offsetMinutes')
    approved = preview(c, h, p, journeyId=d['id'], revision=d['revision'])
    assert approved['summary']['cloudReviews']
    assert apply(c, h, approved, 'review-required-timezone').status_code == 200
    assert order == ['acquired', 'released']
    with connection(app) as con:
        row = con.execute("SELECT * FROM calendar_publications WHERE id='pub'").fetchone()
        assert row['status'] == 'needs_review' and row['review_required'] == 1
        assert row['remote_id'] == 'remote-event' and row['etag'] == 'etag-1' and row['last_hash'] == 'old-hash'
        assert row['pending_data'] == '{"title":"old pending"}' and row['pending_hash'] == 'pending-hash' and row['pending_revision'] == 7
