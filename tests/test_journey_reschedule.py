"""Explicit rescheduling against real Flask sessions and temporary SQLite.

Only calendar provider HTTP is simulated. Product routes, signing, transactions,
receipts and worker logic are real. No real account, file or network is used.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
import json
import socket
import sqlite3
from threading import Barrier
import time
from uuid import uuid4

from itsdangerous import URLSafeTimedSerializer
import pytest

from app import create_app
from test_app import member
from test_calendar_publish import Remote
from test_journey_documents import clone
from test_journey_workflows import preview, apply, detail


TABLES = ('entities', 'journey_workflows', 'journey_links', 'journey_actions',
          'journey_places', 'calendar_publications', 'task_publications', 'audit')


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*_args, **_kwargs):
        raise AssertionError('Reschedule tests permit no external network')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)


@pytest.fixture
def app(tmp_path):
    return create_app({'TESTING': True, 'DATA_DIR': str(tmp_path / 'data'),
        'SECRET_KEY': 'synthetic-reschedule-secret', 'SESSION_COOKIE_SECURE': False,
        'PUBLIC_ORIGIN': 'http://localhost', 'MEMBER1_PASSWORD': 'testing-password-one',
        'MEMBER2_PASSWORD': 'testing-password-two', 'OPENAI_API_KEY': '', 'NVIDIA_API_KEY': '',
        'MICROSOFT_CLIENT_ID': '', 'MICROSOFT_CLIENT_SECRET': '',
        'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': ''})


def connection(app):
    con = sqlite3.connect(app.config['DATA_DIR'] + '/household.sqlite3', timeout=15)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    return con


def snapshot(app):
    with closing(connection(app)) as con:
        return {name: sorted((tuple(row) for row in con.execute('SELECT * FROM ' + name)), key=repr)
                for name in TABLES}


def plan(**changes):
    return {'title': '合成改期旅行', 'start': '2028-03-02', 'end': '2028-03-04',
        'budget': 123450, 'paid': 10000, 'saved': 20000, 'international': True,
        'memberIds': ['member1', 'member2'],
        'destinations': [{'key': 'tokyo', 'country': '日本', 'city': '东京',
                          'arrival': '2028-03-02', 'departure': '2028-03-04'}],
        'checklist': [
            {'key': 'pack', 'title': '合成待准备', 'owner': 'member1', 'due': '2028-03-01', 'note': '保留备注'},
            {'key': 'done', 'title': '合成已完成', 'owner': 'member2', 'due': '2028-02-28'},
            {'key': 'manual', 'title': '合成独立修改', 'owner': 'shared', 'due': '2028-02-29'}],
        'shopping': [{'key': 'purchase', 'title': '合成采购', 'owner': 'member2', 'quantity': '2 件', 'budget': None}],
        'segments': [], **changes}


def create(client, headers, value=None):
    saved = apply(client, headers, preview(client, headers, value or plan()), uuid4().hex)
    assert saved.status_code == 201, saved.json
    return detail(client, saved.json['id'])


def source(client, journey):
    response = client.get('/api/journeys/' + journey + '/reschedule')
    assert response.status_code == 200, response.json
    value = response.json
    assert value['journeyId'] == journey and value['snapshotToken'] and value['expiresIn'] == 1800
    assert len({row['key'] for row in value['items']}) == len(value['items'])
    return value


def reschedule(client, headers, current, selected=(), **changes):
    body = {'snapshotToken': current['snapshotToken'], 'start': '2028-03-05',
            'end': '2028-03-07', 'selectedKeys': list(selected), **changes}
    response = client.post('/api/journeys/' + current['journeyId'] + '/reschedule-preview', json=body, headers=headers)
    assert response.status_code == 200, response.json
    return response.json


def task(journey, key):
    return next(row for row in journey['tasks'] if row['workflowKey'] == 'task:' + key)


def place(client, headers, journey, **changes):
    response = client.post('/api/journey-places', json={'requestId': uuid4().hex,
        'name': '合成计划地点', 'journeyId': journey, 'status': 'planned',
        'startDate': '2028-03-02', 'endDate': '2028-03-04', **changes}, headers=headers)
    assert response.status_code == 201, response.json
    return response.json['place']


def get_place(client, uid):
    response = client.get('/api/journey-places/' + uid)
    assert response.status_code == 200, response.json
    return response.json['place']


def test_snapshot_and_default_preview_never_write_and_optional_dates_stay(app):
    c, h = member(app)
    d = create(c, h)
    p = place(c, h, d['id'])
    before = snapshot(app)
    current = source(c, d['id'])
    assert snapshot(app) == before
    assert current['capabilities']['shoppingDue'] is False
    overview = next(row for row in current['items'] if row['key'] == 'trip')
    assert not overview['eligible'] and overview['reason'] == 'always_updated'
    proposed = reschedule(c, h, current)
    assert proposed['canApply'] and proposed['previewToken'] and not proposed['blockingIssues']
    assert snapshot(app) == before
    assert all(row['after'] == row['before'] for row in proposed['items'] if row['key'] != 'trip')
    result = apply(c, h, proposed, uuid4().hex)
    assert result.status_code == 200, result.json
    changed = detail(c, d['id'])
    assert changed['trip']['start'] == '2028-03-05'
    assert changed['events'][0]['id'] == d['events'][0]['id']
    assert changed['events'][0]['start'].startswith('2028-03-05')
    assert changed['tasks'] == d['tasks'] and changed['shopping'] == d['shopping']
    assert changed['plan']['destinations'] == d['plan']['destinations']
    assert get_place(c, p['id']) == p


def test_selected_dates_move_once_and_completed_visited_manual_records_are_preserved(app):
    c, h = member(app)
    d = create(c, h)
    done, manual = task(d, 'done'), task(d, 'manual')
    assert c.patch('/api/items/tasks/' + done['id'], json={'revision': done['revision'], 'done': True}, headers=h).status_code == 200
    assert c.patch('/api/items/tasks/' + manual['id'], json={'revision': manual['revision'], 'due': '2028-02-20', 'title': '手工改名仍保留'}, headers=h).status_code == 200
    p = place(c, h, d['id'], coordinates={'latitude': 35.68, 'longitude': 139.76})
    visited = place(c, h, d['id'], name='合成已到访', status='visited', confirmVisited=True)
    partner, ph = member(app, 2)
    hidden = place(partner, ph, d['id'], name='PARTNER-PRIVATE-PLACE')
    original = detail(c, d['id'])
    current = source(c, d['id'])
    assert hidden['id'] not in json.dumps(current) and 'PARTNER-PRIVATE-PLACE' not in json.dumps(current)
    choices = {row['key']: row for row in current['items']}
    for key in ('task:done', 'place:' + visited['id'], 'shopping:purchase'):
        assert not choices[key]['eligible'] and choices[key]['reason']
    selected = ['task:pack', 'destination:tokyo', 'place:' + p['id']]
    before = snapshot(app)
    proposed = reschedule(c, h, current, selected)
    assert snapshot(app) == before and proposed['canApply']
    key = uuid4().hex
    first = apply(c, h, proposed, key)
    assert first.status_code == 200 and first.json['operation'] == 'reschedule', first.json
    assert set(first.json['reschedule']['changedKeys']) == {'trip', *selected}
    changed = detail(c, d['id'])
    assert task(changed, 'pack')['due'] == '2028-03-04'
    assert task(changed, 'pack')['owner'] == 'member1' and task(changed, 'pack')['note'] == '保留备注'
    assert task(changed, 'done') == task(original, 'done')
    assert task(changed, 'manual') == task(original, 'manual')
    assert changed['shopping'] == original['shopping'] and changed['budget'] == original['budget']
    assert get_place(c, visited['id']) == visited and get_place(partner, hidden['id']) == hidden
    shifted = get_place(c, p['id'])
    assert (shifted['startDate'], shifted['endDate']) == ('2028-03-05', '2028-03-07')
    for name in ('coordinates', 'visibility', 'coordinateDisclosure', 'owner', 'status'):
        assert shifted[name] == p[name]
    committed = snapshot(app)
    assert apply(c, h, proposed, key).json['replayed'] is True
    assert snapshot(app) == committed
    receipt = c.get('/api/journeys/operations/' + key)
    assert receipt.status_code == 200 and receipt.json['found'] is True
    assert receipt.json['result']['id'] == d['id'] and snapshot(app) == committed
    assert c.delete('/api/journey-places/' + p['id'], json={'revision': shifted['revision']}, headers=h).status_code == 200
    deleted = snapshot(app)
    assert apply(c, h, proposed, key).json['replayed'] is True
    assert snapshot(app) == deleted and c.get('/api/journey-places/' + p['id']).status_code == 404


@pytest.mark.parametrize('stage', ['preview', 'apply'])
@pytest.mark.parametrize('changed_kind', ['journey', 'task', 'place'])
def test_every_snapshot_revision_is_checked_and_conflict_changes_nothing(app, stage, changed_kind):
    c, h = member(app)
    d = create(c, h)
    p = place(c, h, d['id'])
    current = source(c, d['id'])
    proposed = reschedule(c, h, current, ['task:pack', 'place:' + p['id']]) if stage == 'apply' else None
    if changed_kind == 'journey':
        changed = deepcopy(d['plan']); changed['title'] = '他处更新的旅行'
        assert apply(c, h, preview(c, h, changed, journeyId=d['id'], revision=d['revision']), uuid4().hex).status_code == 200
    elif changed_kind == 'task':
        row = task(d, 'manual')  # Even an unselected linked task participates in the CAS.
        assert c.patch('/api/items/tasks/' + row['id'], json={'revision': row['revision'], 'done': True}, headers=h).status_code == 200
    else:
        assert c.patch('/api/journey-places/' + p['id'], json={'revision': p['revision'], 'name': '预览后独立改名'}, headers=h).status_code == 200
    before = snapshot(app)
    result = (apply(c, h, proposed, uuid4().hex) if proposed else c.post('/api/journeys/' + d['id'] + '/reschedule-preview',
        json={'snapshotToken': current['snapshotToken'], 'start': '2028-03-05', 'end': '2028-03-07', 'selectedKeys': []}, headers=h))
    assert result.status_code == 409, result.json
    assert snapshot(app) == before


def test_failure_at_receipt_insert_rolls_back_entities_places_and_audit(app):
    c, h = member(app)
    d = create(c, h)
    p = place(c, h, d['id'])
    proposed = reschedule(c, h, source(c, d['id']), ['task:pack', 'place:' + p['id']])
    with connection(app) as con:
        con.execute("CREATE TRIGGER reject_reschedule_receipt BEFORE INSERT ON journey_actions BEGIN SELECT RAISE(ABORT,'synthetic final receipt failure'); END")
    before = snapshot(app)
    key = uuid4().hex
    with pytest.raises(sqlite3.IntegrityError, match='synthetic final receipt failure'):
        apply(c, h, proposed, key)
    assert snapshot(app) == before
    with connection(app) as con:
        con.execute('DROP TRIGGER reject_reschedule_receipt')
    assert apply(c, h, proposed, key).status_code == 200
    assert task(detail(c, d['id']), 'pack')['due'] == '2028-03-04'


def test_concurrent_same_intent_never_double_shifts_and_different_intent_conflicts(app):
    c, h = member(app)
    d = create(c, h)
    proposed = reschedule(c, h, source(c, d['id']), ['task:pack'])
    clients = [clone(app, c), clone(app, c)]
    barrier = Barrier(2)
    key = uuid4().hex
    def submit(client):
        barrier.wait(timeout=10)
        return apply(client, h, proposed, key)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, clients))
    assert [r.status_code for r in results] == [200, 200]
    assert sorted(r.json['replayed'] for r in results) == [False, True]
    changed = detail(c, d['id'])
    assert changed['revision'] == d['revision'] + 1 and task(changed, 'pack')['due'] == '2028-03-04'
    newer = reschedule(c, h, source(c, d['id']), ['task:pack'], start='2028-03-08', end='2028-03-10')
    before = snapshot(app)
    assert apply(c, h, newer, key).status_code == 409
    assert snapshot(app) == before


@pytest.mark.parametrize('operation', ['preview', 'apply', 'replay'])
@pytest.mark.parametrize('revocation', ['session', 'auth_version'])
def test_real_revocation_after_http_guard_blocks_preview_save_and_replay(app, monkeypatch, operation, revocation):
    c, h = member(app)
    d = create(c, h)
    current = source(c, d['id'])
    proposed = reschedule(c, h, current, ['task:pack'])
    key = uuid4().hex
    if operation == 'replay':
        assert apply(c, h, proposed, key).status_code == 200
    candidate = current['snapshotToken'] if operation == 'preview' else proposed['previewToken']
    original = URLSafeTimedSerializer.loads
    revoked = []
    def decode_then_revoke(signer, value, *args, **kwargs):
        result = original(signer, value, *args, **kwargs)
        if value == candidate and not revoked:
            with connection(app) as other:
                statement = ("UPDATE member_sessions SET revoked_at=1 WHERE owner='member1' AND revoked_at IS NULL"
                    if revocation == 'session' else "UPDATE users SET auth_version=auth_version+1 WHERE id='member1'")
                assert other.execute(statement).rowcount > 0
            revoked.append(True)
        return result
    before = snapshot(app)
    monkeypatch.setattr(URLSafeTimedSerializer, 'loads', decode_then_revoke)
    response = (c.post('/api/journeys/' + d['id'] + '/reschedule-preview', json={
        'snapshotToken': current['snapshotToken'], 'start': '2028-03-05', 'end': '2028-03-07', 'selectedKeys': []}, headers=h)
        if operation == 'preview' else apply(c, h, proposed, key))
    assert revoked == [True] and response.status_code == 401, response.json
    assert snapshot(app) == before and c.get('/api/me').json['user'] is None


def test_member_household_tv_csrf_and_receipt_boundaries(app):
    c, h = member(app)
    partner, ph = member(app, 2)
    d = create(c, h)
    private = place(c, h, d['id'], name='OWNER-PRIVATE-ONLY')
    own = source(c, d['id'])
    assert private['id'] not in json.dumps(source(partner, d['id']))
    body = {'snapshotToken': own['snapshotToken'], 'start': '2028-03-05', 'end': '2028-03-07', 'selectedKeys': []}
    endpoint = '/api/journeys/' + d['id'] + '/reschedule-preview'
    before = snapshot(app)
    assert partner.post(endpoint, json=body, headers=ph).status_code == 403
    assert c.post(endpoint, json=body).status_code == 403
    assert c.post(endpoint, json=body, headers={**h, 'Origin': 'https://outside.invalid'}).status_code == 403
    assert app.test_client().get('/api/journeys/' + d['id'] + '/reschedule').status_code == 401
    assert snapshot(app) == before
    proposed = reschedule(c, h, own)
    key = uuid4().hex
    assert apply(c, h, proposed, key).status_code == 200
    missing = partner.get('/api/journeys/operations/' + key)
    assert missing.status_code == 404 and missing.json['code'] == 'operation_not_found'
    tv = app.test_client()
    pair = tv.post('/api/pair/start', json={}).json
    assert c.post('/api/pair/approve', json={'code': pair['code'], 'name': '合成电视', 'focus': 'shared'}, headers=h).status_code == 200
    assert tv.post('/api/pair/poll', json={'secret': pair['secret']}).json['approved']
    assert tv.get('/api/journeys/' + d['id'] + '/reschedule').status_code == 403
    assert tv.get('/api/journeys/operations/' + key).status_code == 403
    invitation = c.post('/api/spaces/invitations', json={}, headers=h).json['invitation']
    child = app.test_client()
    redeemed = child.post('/api/spaces/redeem', json={'invitation': invitation, 'name': '合成改期隔离家庭', 'slug': 'reschedule-child',
        'MEMBER1_PASSWORD': 'testing-password-one', 'MEMBER2_PASSWORD': 'testing-password-two'})
    assert redeemed.status_code == 201 and child.get(redeemed.json['entry']).status_code == 303
    assert child.post('/api/login', json={'username': 'member1', 'password': 'testing-password-one'}).status_code == 200
    ch = {'X-CSRF-Token': child.get('/api/me').json['csrf']}
    assert child.get('/api/journeys/' + d['id'] + '/reschedule').status_code == 404
    assert child.get('/api/journeys/operations/' + key).status_code == 404
    before = snapshot(app)
    rejected = child.post(endpoint, json=body, headers=ch)
    # Independent households have different signing keys: reject before looking up any source data.
    assert rejected.status_code == 400 and rejected.json['code'] == 'invalid_reschedule'
    assert snapshot(app) == before and child.get('/api/journeys').json['journeys'] == []


@pytest.mark.parametrize('bad', [None, 'task:pack', ['trip'], ['unknown:key'], ['task:pack', 'task:pack']])
def test_invalid_selection_never_writes(app, bad):
    c, h = member(app)
    d = create(c, h)
    current = source(c, d['id'])
    before = snapshot(app)
    response = c.post('/api/journeys/' + d['id'] + '/reschedule-preview', json={
        'snapshotToken': current['snapshotToken'], 'start': '2028-03-05', 'end': '2028-03-07', 'selectedKeys': bad}, headers=h)
    assert response.status_code == 400, response.json
    assert snapshot(app) == before


def test_more_than_one_hundred_linked_places_are_not_truncated(app):
    c, h = member(app)
    d = create(c, h)
    places = [place(c, h, d['id'], name=f'合成边界地点 {i:03}') for i in range(101)]
    before = snapshot(app)
    current = source(c, d['id'])
    keys = {r['key'] for r in current['items'] if r['kind'] == 'place'}
    assert keys == {'place:' + p['id'] for p in places}
    last = max(places, key=lambda row: row['id'])  # Last in the server's stable ID order.
    proposed = reschedule(c, h, current, ['place:' + last['id']])
    assert proposed['canApply'] and snapshot(app) == before
    assert apply(c, h, proposed, uuid4().hex).status_code == 200
    for p in places:
        saved = get_place(c, p['id'])
        if p['id'] == last['id']:
            assert saved['startDate'] == '2028-03-05' and saved['endDate'] == '2028-03-07'
        else:
            assert saved == p


@pytest.mark.parametrize('field,value', [('title', '提前改期后仍能编辑'), ('budget', 234560)])
def test_earlier_reschedule_keeps_historical_dates_editable_but_rejects_new_outliers(app, field, value):
    c, h = member(app)
    d = create(c, h, plan(segments=[{'key': 'retained', 'title': '保留原日期段',
                                  'start': '2028-03-03', 'end': '2028-03-04'}]))
    done = task(d, 'done')
    assert c.patch('/api/items/tasks/' + done['id'], json={'revision': done['revision'], 'done': True}, headers=h).status_code == 200
    proposed = reschedule(c, h, source(c, d['id']), start='2028-02-20', end='2028-02-22')
    assert proposed['canApply'] and apply(c, h, proposed, uuid4().hex).status_code == 200
    current = detail(c, d['id'])
    historical_task = task(current, 'done')
    assert historical_task['due'] > current['trip']['end'] and historical_task['done']
    draft = deepcopy(current['plan'])
    draft[field] = value
    before = snapshot(app)
    ordinary = preview(c, h, draft, journeyId=d['id'], revision=current['revision'])
    assert snapshot(app) == before
    assert apply(c, h, ordinary, uuid4().hex).status_code == 200
    edited = detail(c, d['id'])
    assert edited['trip'][field] == value
    saved_task = task(edited, 'done')
    # The existing ordinary editor revises all linked entities, even unchanged payloads.
    assert saved_task['revision'] == historical_task['revision'] + 1
    assert {k: v for k, v in saved_task.items() if k != 'revision'} == {
        k: v for k, v in historical_task.items() if k != 'revision'}
    assert edited['plan']['destinations'] == current['plan']['destinations']
    assert edited['plan']['segments'] == current['plan']['segments']
    for collection, date_field in [('destinations', 'departure'), ('segments', 'end'), ('checklist', 'due')]:
        changed = deepcopy(edited['plan'])
        changed[collection][0][date_field] = '2028-03-10'
        before = snapshot(app)
        response = c.post('/api/journeys/preview', json={'plan': changed, 'journeyId': d['id'],
                                                       'revision': edited['revision']}, headers=h)
        assert response.status_code == 400, response.json
        assert snapshot(app) == before


@pytest.mark.parametrize('offset', [10**20, -(10**20), 367, -731])
def test_new_plan_missing_due_cannot_bypass_offset_bounds(app, offset):
    c, h = member(app)
    before = snapshot(app)
    response = c.post('/api/journeys/preview', json={'plan': plan(checklist=[{
        'key': 'new', 'title': '新任务不享受历史豁免', 'dueOffsetDays': offset}])}, headers=h)
    assert response.status_code == 400, response.json
    assert snapshot(app) == before


def v2_plan(day='2026-03-28', **changes):
    return plan(schemaVersion=2, referenceTimezone='Europe/Berlin', start=day, end=day,
        destinations=[{'key': 'berlin', 'country': '德国', 'city': '柏林', 'arrival': day, 'departure': day, 'timeZone': 'Europe/Berlin'}],
        checklist=[], shopping=[], segments=[{'key': 'walk', 'kind': 'activity', 'title': '合成当地活动',
            'start': {'local': day + 'T02:30', 'timeZone': 'Europe/Berlin'},
            'end': {'local': day + 'T04:00', 'timeZone': 'Europe/Berlin'}, **changes}])


@pytest.mark.parametrize('change', [{'bookingState': 'booked'}, {'bookingState': 'cancelled'}, {'datePolicy': 'fixed'}])
def test_booked_cancelled_and_fixed_segments_cannot_be_selected(app, change):
    c, h = member(app)
    d = create(c, h, v2_plan(**change))
    current = source(c, d['id'])
    row = next(r for r in current['items'] if r['key'] == 'segment:walk')
    assert not row['eligible'] and row['reason']
    before = snapshot(app)
    response = c.post('/api/journeys/' + d['id'] + '/reschedule-preview', json={
        'snapshotToken': current['snapshotToken'], 'start': '2026-03-29', 'end': '2026-03-29', 'selectedKeys': ['segment:walk']}, headers=h)
    assert response.status_code == 400 and snapshot(app) == before


@pytest.mark.parametrize('old,new,code', [('2026-03-28', '2026-03-29', 'nonexistent_local_time'),
                                        ('2026-10-24', '2026-10-25', 'ambiguous_local_time')])
def test_dst_requires_explicit_correction_and_never_guesses_offset(app, old, new, code):
    c, h = member(app)
    d = create(c, h, v2_plan(old))
    current = source(c, d['id'])
    before = snapshot(app)
    blocked = reschedule(c, h, current, ['segment:walk'], start=new, end=new)
    assert not blocked['canApply'] and blocked['previewToken'] is None
    issue = next(r for r in blocked['blockingIssues'] if r['code'] == code)
    assert issue['key'] == 'segment:walk' and issue['field'] == 'start' and snapshot(app) == before
    correction = ({'local': new + 'T03:30'} if code == 'nonexistent_local_time'
                  else {'local': new + 'T02:30', 'offsetMinutes': issue['choices'][0]['offsetMinutes']})
    confirmed = reschedule(c, h, current, ['segment:walk'], start=new, end=new,
        timeOverrides={'segment:walk': {'start': correction}})
    assert confirmed['canApply'] and snapshot(app) == before
    row = next(r for r in confirmed['items'] if r['key'] == 'segment:walk')
    assert row['timeBefore']['start']['local'].startswith(old + 'T02:30')
    assert row['timeAfter']['start']['local'].startswith(correction['local'])
    assert row['timeAfter']['start']['timeZone'] == 'Europe/Berlin'
    assert row['timeAfter']['start']['offsetMinutes'] == correction.get('offsetMinutes', 120)
    saved = apply(c, h, confirmed, uuid4().hex)
    assert saved.status_code == 200 and 'segment:walk' in saved.json['reschedule']['changedKeys']
    changed = detail(c, d['id'])
    original_event = next(e for e in d['events'] if e['workflowKey'] == 'segment:walk')
    event = next(e for e in changed['events'] if e['workflowKey'] == 'segment:walk')
    assert event['id'] == original_event['id'] and event['travelTiming']['startLocal'].startswith(correction['local'])


@pytest.mark.parametrize('clock_only', [True, False])
def test_same_day_clock_or_offset_change_is_reported_and_updates_the_original_event(app, clock_only):
    c, h = member(app)
    day = '2026-10-25'
    d = create(c, h, v2_plan(day, start={'local': day + 'T02:30', 'timeZone': 'Europe/Berlin', 'offsetMinutes': 120}))
    original = next(e for e in d['events'] if e['workflowKey'] == 'segment:walk')
    correction = {'local': day + ('T02:45' if clock_only else 'T02:30'), 'offsetMinutes': 120 if clock_only else 60}
    before = snapshot(app)
    proposed = reschedule(c, h, source(c, d['id']), ['segment:walk'], start=day, end=day,
                          timeOverrides={'segment:walk': {'start': correction}})
    row = next(r for r in proposed['items'] if r['key'] == 'segment:walk')
    assert proposed['canApply'] and row['before'] == row['after'] and snapshot(app) == before
    assert row['timeBefore']['start']['offsetMinutes'] == 120
    assert row['timeAfter']['start']['local'].startswith(correction['local'])
    assert row['timeAfter']['start']['offsetMinutes'] == correction['offsetMinutes']
    result = apply(c, h, proposed, uuid4().hex)
    assert result.status_code == 200 and 'segment:walk' in result.json['reschedule']['changedKeys']
    changed = next(e for e in detail(c, d['id'])['events'] if e['workflowKey'] == 'segment:walk')
    assert changed['id'] == original['id'] and changed['start'] != original['start']


@pytest.mark.parametrize('provider', ['microsoft', 'google'])
def test_published_overview_updates_same_remote_once_after_lost_patch(app, provider):
    remote = Remote()
    app.config.update(CLOUD_TRANSPORT=remote.transport,
        **{provider.upper() + '_CLIENT_ID': 'synthetic-client', provider.upper() + '_CLIENT_SECRET': 'synthetic-secret'})
    engine = app.extensions['cloud_accounts']
    scope = ('User.Read Calendars.ReadWrite Tasks.ReadWrite' if provider == 'microsoft' else
        'https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/tasks')
    with engine.db() as con:
        tokens = engine.encrypt({'access_token': 'synthetic', 'refresh_token': 'synthetic', 'scope': scope, 'expires_at': time.time() + 3600})
        con.execute('INSERT INTO cloud_accounts(id,owner,provider,client_id,subject,name,email,tokens) VALUES(?,?,?,?,?,?,?,?)',
            ('reschedule-account', 'member1', provider, 'synthetic-client', 'synthetic-subject', '合成账户', 'synthetic@example.invalid', tokens))
        con.execute('INSERT INTO cloud_sources(id,account_id,remote_id,kind,name,owner) VALUES(?,?,?,?,?,?)',
            ('reschedule-source', 'reschedule-account', 'synthetic-calendar', 'calendar', '合成日历', 'member1'))
    c, h = member(app)
    d = create(c, h)
    payload = {'journeyId': d['id'], 'sourceId': 'reschedule-source'}
    q = c.post('/api/calendar-publish/preview', json=payload, headers=h)
    assert q.status_code == 200
    result = c.post('/api/calendar-publish/confirm', json={**payload, 'previewToken': q.json['previewToken']}, headers=h)
    assert result.status_code == 200 and len(result.json['publicationIds']) == 1
    rid = result.json['publicationIds'][0]
    worker = app.extensions['calendar_publish']
    worker.process(rid)
    def publication():
        with closing(connection(app)) as con:
            return dict(con.execute('SELECT * FROM calendar_publications WHERE id=?', (rid,)).fetchone())
    before_row = publication()
    assert before_row['status'] == 'published' and remote.created == 1
    before, calls = snapshot(app), len(remote.calls)
    proposed = reschedule(c, h, source(c, d['id']), ['task:pack'])
    assert snapshot(app) == before and len(remote.calls) == calls
    assert apply(c, h, proposed, uuid4().hex).status_code == 200
    assert len(remote.calls) == calls
    remote.lose_patch = True
    worker.process(rid)
    assert publication()['status'] == 'retry' and remote.patched == 1
    worker.process(rid)
    assert publication()['status'] == 'published' and remote.created == remote.patched == 1
    assert publication()['remote_id'] == before_row['remote_id']
    assert publication()['entity_id'] == before_row['entity_id']
