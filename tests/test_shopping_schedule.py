"""Shopping schedule through real Flask/SQLite; no model, cloud or network."""
from contextlib import closing
from copy import deepcopy
import json
import socket
from uuid import uuid4

import pytest

from app import create_app
from test_app import member
from test_data_portability import unpack
from test_household_spaces import create_space
from test_inventory_shopping_query import linked as link_inventory
from test_journey_details import v2
from test_journey_reschedule import connection, snapshot, source, reschedule
from test_journey_workflows import plan, preview, apply, detail
from test_shopping_media import pair_tv, upload
from test_shopping_settlement_journeys import import_payment, settled


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*_args, **_kwargs):
        raise AssertionError('Shopping schedule tests forbid external calls')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)


@pytest.fixture
def app(tmp_path):
    return create_app({'TESTING': True, 'DATA_DIR': str(tmp_path),
        'SECRET_KEY': 'synthetic-shopping-schedule', 'SESSION_COOKIE_SECURE': False,
        'PUBLIC_ORIGIN': 'http://localhost', 'MEMBER1_PASSWORD': 'testing-password-one',
        'MEMBER2_PASSWORD': 'testing-password-two', 'ASSISTANT_PROVIDER': 'local',
        'OPENAI_API_KEY': '', 'NVIDIA_API_KEY': '', 'MICROSOFT_CLIENT_ID': '',
        'MICROSOFT_CLIENT_SECRET': '', 'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': ''})


def purchase(c, uid):
    return next(row for row in c.get('/api/state').json['shopping'] if row['id'] == uid)


def create(c, h, version=1, shopping=None):
    value = (v2 if version == 2 else plan)(checklist=[], shopping=shopping if shopping is not None else [
        {'key': 'adapter', 'title': '合成转换插头', 'quantity': '2 件', 'owner': 'member2',
         'budget': 12000, 'note': '合成采购备注', 'due': '2026-09-28', 'priority': 'high'}])
    result = apply(c, h, preview(c, h, value), uuid4().hex)
    assert result.status_code == 201, result.json
    return detail(c, result.json['id'])


def edit(c, h, d, value):
    return preview(c, h, value, journeyId=d['id'], revision=d['revision'])


def associations(app):
    with closing(connection(app)) as con:
        names = [row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
                 if row[0].startswith(('inventory_', 'hub_shopping_', 'hub_transactions')) or row[0] == 'photo_refs']
        return {name: sorted(map(tuple, con.execute('SELECT * FROM "' + name + '"')), key=repr) for name in names}


@pytest.mark.parametrize('due,priority', [('', 'normal'), ('2000-01-01', 'low'), ('2100-12-31', 'high')])
def test_crud_strict_fields_persist_and_omission_differs_from_clear(app, due, priority):
    c, h = member(app)
    result = c.post('/api/items/shopping', json={'title': '合成采购', 'due': due, 'priority': priority}, headers=h)
    assert result.status_code == 201, result.json
    uid = result.json['id']
    assert (purchase(c, uid)['due'], purchase(c, uid)['priority']) == (due, priority)
    assert c.patch('/api/items/shopping/' + uid, json={'revision': 1, 'title': '改名保持安排'}, headers=h).status_code == 200
    assert (purchase(c, uid)['due'], purchase(c, uid)['priority']) == (due, priority)
    other = create_app(dict(app.config))
    fresh, fh = member(other)
    assert (purchase(fresh, uid)['due'], purchase(fresh, uid)['priority']) == (due, priority)
    assert fresh.patch('/api/items/shopping/' + uid, json={'revision': 2, 'due': '', 'priority': 'normal'}, headers=fh).status_code == 200
    assert (purchase(fresh, uid)['due'], purchase(fresh, uid)['priority']) == ('', 'normal')
    before = snapshot(other)
    assert fresh.patch('/api/items/shopping/' + uid, json={'revision': 2, 'priority': 'high'}, headers=fh).status_code == 409
    assert snapshot(other) == before


@pytest.mark.parametrize('change', [
    {'due': None}, {'due': False}, {'due': 20260928}, {'due': []}, {'due': '2026-02-29'},
    {'due': '1999-12-31'}, {'due': '2101-01-01'}, {'due': '2026-9-28'}, {'due': '20260928'},
    {'due': '2026-09-28T00:00:00Z'}, {'due': ' 2026-09-28'},
    {'priority': None}, {'priority': True}, {'priority': 1}, {'priority': []},
    {'priority': 'urgent'}, {'priority': 'HIGH'}, {'priority': ''},
])
def test_bad_fields_rejected_consistently_by_item_and_journey_without_writes(app, change):
    c, h = member(app)
    before = snapshot(app)
    response = c.post('/api/items/shopping', json={'title': '合成采购', **change}, headers=h)
    assert response.status_code == 400, response.json
    value = plan(shopping=[{'key': 'bad', 'title': '合成采购', **change}])
    response = c.post('/api/journeys/preview', json={'plan': value}, headers=h)
    assert response.status_code == 400, response.json
    assert snapshot(app) == before


@pytest.mark.parametrize('version', [1, 2])
def test_old_plan_omissions_keep_actual_metadata_and_explicit_clear_roundtrips(app, version):
    c, h = member(app)
    d = create(c, h, version)
    original = d['shopping'][0]
    changed = c.patch('/api/items/shopping/' + original['id'], json={
        'revision': original['revision'], 'due': '2026-10-01', 'priority': 'low'}, headers=h)
    assert changed.status_code == 200
    legacy = deepcopy(d['plan'])
    legacy['shopping'][0].pop('due')
    legacy['shopping'][0].pop('priority')
    before = snapshot(app)
    pending = edit(c, h, d, legacy)
    assert snapshot(app) == before
    assert (pending['plan']['shopping'][0]['due'], pending['plan']['shopping'][0]['priority']) == ('2026-10-01', 'low')
    assert apply(c, h, pending, uuid4().hex).status_code == 200
    saved = detail(c, d['id'])
    assert saved['shopping'][0]['id'] == original['id'] and saved['shopping'][0]['workflowKey'] == original['workflowKey']
    clear = deepcopy(saved['plan'])
    clear['shopping'][0].update(due='', priority='normal')
    assert apply(c, h, edit(c, h, saved, clear), uuid4().hex).status_code == 200
    cleared = detail(c, d['id'])
    assert (cleared['shopping'][0]['due'], cleared['shopping'][0]['priority']) == ('', 'normal')
    assert (cleared['plan']['shopping'][0]['due'], cleared['plan']['shopping'][0]['priority']) == ('', 'normal')
    # Old request omission must also keep a *cleared* live value, not revive its stale plan.
    current = deepcopy(cleared['plan'])
    current['shopping'][0].pop('due')
    current['shopping'][0].pop('priority')
    assert edit(c, h, cleared, current)['plan']['shopping'][0]['due'] == ''


@pytest.mark.parametrize('version', [1, 2])
def test_new_and_preexisting_legacy_json_need_no_database_backfill(app, version):
    c, h = member(app)
    d = create(c, h, version, shopping=[{'key': 'old', 'title': '旧采购'}])
    row = d['shopping'][0]
    assert row['due'] == '' and row['priority'] == 'normal'
    # Model an old database by removing fields exactly as stored before this feature.
    with connection(app) as con:
        raw = json.loads(con.execute('SELECT data FROM entities WHERE id=?', (row['id'],)).fetchone()[0])
        raw.pop('due'); raw.pop('priority')
        old_plan = deepcopy(d['plan'])
        old_plan['shopping'][0].pop('due'); old_plan['shopping'][0].pop('priority')
        con.execute('UPDATE entities SET data=? WHERE id=?', (json.dumps(raw), row['id']))
        con.execute('UPDATE journey_workflows SET plan=? WHERE id=?', (json.dumps(old_plan), d['id']))
        schema = list(map(tuple, con.execute('SELECT type,name,sql FROM sqlite_master ORDER BY name')))
    before = snapshot(app)
    other = create_app(dict(app.config))
    fresh, _ = member(other)
    old = detail(fresh, d['id'])
    assert 'due' not in old['shopping'][0] and 'priority' not in old['plan']['shopping'][0]
    current = source(fresh, d['id'])
    item = next(x for x in current['items'] if x['kind'] == 'shopping')
    assert not item['eligible'] and item['reason'] == 'no_date' and current['capabilities']['shoppingDue'] is True
    assert snapshot(other) == before
    with closing(connection(other)) as con:
        assert list(map(tuple, con.execute('SELECT type,name,sql FROM sqlite_master ORDER BY name'))) == schema


def test_selected_shopping_moves_once_preserving_money_media_and_real_associations(app):
    c, h = member(app)
    d = create(c, h, shopping=[{'key': key, 'title': '合成采购-' + key, 'owner': 'member2',
        'quantity': '2 件', 'budget': 12000, 'due': '' if key == 'unknown' else '2026-09-28', 'priority': 'high'}
        for key in ('selected', 'unselected', 'completed', 'unknown', 'cloud')])
    rows = {row['workflowKey'].split(':')[1]: row for row in d['shopping']}
    selected = rows['selected']
    photo = upload(c, h)
    assert c.patch('/api/items/shopping/' + selected['id'], json={
        'revision': selected['revision'], 'photoIds': [photo], 'note': '实际采购备注'}, headers=h).status_code == 200
    payment = import_payment(c, h)
    settled(c, h, purchase(c, selected['id']), payment, done=False)
    link_inventory(c, h, selected['id'])
    assert c.patch('/api/items/shopping/' + rows['completed']['id'], json={
        'revision': rows['completed']['revision'], 'done': True}, headers=h).status_code == 200
    with connection(app) as con:
        cloud = json.loads(con.execute('SELECT data FROM entities WHERE id=?', (rows['cloud']['id'],)).fetchone()[0])
        cloud['sync'] = {'provider': 'synthetic'}
        con.execute('UPDATE entities SET data=?,revision=revision+1 WHERE id=?', (json.dumps(cloud), rows['cloud']['id']))
    original, related = detail(c, d['id']), associations(app)
    current = source(c, d['id'])
    choices = {x['key']: x for x in current['items']}
    assert choices['shopping:selected']['eligible']
    for key, reason in [('completed', 'completed'), ('unknown', 'no_date'), ('cloud', 'cloud_managed')]:
        assert not choices['shopping:' + key]['eligible'] and choices['shopping:' + key]['reason'] == reason
    before = snapshot(app)
    default = reschedule(c, h, current, start='2026-12-06', end='2026-12-12')
    assert all(x['before'] == x['after'] for x in default['items'] if x['kind'] == 'shopping')
    proposed = reschedule(c, h, current, ['shopping:selected'], start='2026-12-06', end='2026-12-12')
    assert snapshot(app) == before
    impact = next(x for x in proposed['items'] if x['key'] == 'shopping:selected')
    assert impact['before'] == {'start': '2026-09-28', 'end': '2026-09-28'}
    assert impact['after'] == {'start': '2026-10-01', 'end': '2026-10-01'}
    key = uuid4().hex
    first = apply(c, h, proposed, key)
    assert first.status_code == 200 and set(first.json['reschedule']['changedKeys']) == {'trip', 'shopping:selected'}
    saved = detail(c, d['id'])
    by_id = {row['id']: row for row in saved['shopping']}
    for old in original['shopping']:
        expected = {**old, 'due': '2026-10-01', 'revision': old['revision'] + 1} if old['id'] == selected['id'] else old
        assert by_id[old['id']] == expected
    assert saved['budget'] == original['budget'] and associations(app) == related
    plan_row = next(row for row in saved['plan']['shopping'] if row['key'] == 'selected')
    assert plan_row['due'] == '2026-10-01' and plan_row['priority'] == 'high'
    committed = snapshot(app)
    assert apply(c, h, proposed, key).json['replayed'] is True
    assert apply(c, h, proposed, uuid4().hex).json['replayed'] is True
    receipt = c.get('/api/journeys/operations/' + key)
    assert receipt.status_code == 200 and receipt.json['found'] is True
    assert snapshot(app) == committed and associations(app) == related


@pytest.mark.parametrize('stage', ['preview', 'apply'])
def test_live_schedule_edits_invalidate_old_reschedule_and_latest_clear_wins(app, stage):
    c, h = member(app)
    d = create(c, h)
    current = source(c, d['id'])
    pending = reschedule(c, h, current, ['shopping:adapter'], start='2026-12-06', end='2026-12-12')
    row = d['shopping'][0]
    assert c.patch('/api/items/shopping/' + row['id'], json={'revision': row['revision'], 'due': '', 'priority': 'low'}, headers=h).status_code == 200
    before = snapshot(app)
    response = (apply(c, h, pending, uuid4().hex) if stage == 'apply' else c.post('/api/journeys/' + d['id'] + '/reschedule-preview',
        json={'snapshotToken': current['snapshotToken'], 'start': '2026-12-06', 'end': '2026-12-12', 'selectedKeys': ['shopping:adapter']}, headers=h))
    assert response.status_code == 409 and snapshot(app) == before
    latest = source(c, d['id'])
    assert next(x for x in latest['items'] if x['key'] == 'shopping:adapter')['reason'] == 'no_date'
    actual = reschedule(c, h, latest, start='2026-12-06', end='2026-12-12')
    assert apply(c, h, actual, uuid4().hex).status_code == 200
    result = detail(c, d['id'])
    assert result['shopping'][0]['due'] == result['plan']['shopping'][0]['due'] == ''
    assert result['shopping'][0]['priority'] == result['plan']['shopping'][0]['priority'] == 'low'


@pytest.mark.parametrize('due,start,end', [('2000-01-01', '2026-12-02', '2026-12-08'), ('2100-12-31', '2026-12-04', '2026-12-10')])
def test_shift_outside_supported_years_rejected_without_any_write(app, due, start, end):
    c, h = member(app)
    d = create(c, h, shopping=[{'key': 'edge', 'title': '边界采购', 'due': due}])
    current = source(c, d['id'])
    before = snapshot(app)
    response = c.post('/api/journeys/' + d['id'] + '/reschedule-preview', json={
        'snapshotToken': current['snapshotToken'], 'start': start, 'end': end, 'selectedKeys': ['shopping:edge']}, headers=h)
    assert response.status_code == 400 and snapshot(app) == before


def test_due_after_return_warns_without_changing_date_and_export_stays_scoped(app):
    c, h = member(app)
    pending = preview(c, h, plan(shopping=[{'key': 'later', 'title': '合成返程采购', 'due': '2027-01-01', 'priority': 'low'}]))
    assert any(w['code'] == 'shopping_due_after_trip' for w in pending['summary']['warnings'])
    saved = apply(c, h, pending, uuid4().hex)
    assert saved.status_code == 201
    d = detail(c, saved.json['id'])
    partner, ph = member(app, 2)
    import_payment(partner, ph, marker='PRIVATE_PARTNER_PURCHASE')
    ordinary, _ = unpack(c.post('/api/portability/export', json={}, headers=h))
    assert 'shared' not in ordinary
    exported, files = unpack(c.post('/api/portability/export', json={'includeShared': True}, headers=h))
    row = exported['shared']['entities']['shopping'][0]
    assert (row['due'], row['priority']) == ('2027-01-01', 'low')
    assert row['id'] == d['shopping'][0]['id']
    assert b'PRIVATE_PARTNER_PURCHASE' not in b''.join(files.values())


def test_member_household_tv_csrf_and_original_preview_permissions(app):
    c, h = member(app)
    d = create(c, h)
    row = d['shopping'][0]
    endpoint = '/api/items/shopping/' + row['id']
    body = {'revision': row['revision'], 'priority': 'low'}
    before = snapshot(app)
    assert app.test_client().patch(endpoint, json=body).status_code == 401
    assert c.patch(endpoint, json=body).status_code == 403
    assert c.patch(endpoint, json=body, headers={**h, 'Origin': 'https://other.invalid'}).status_code == 403
    assert snapshot(app) == before
    tv = pair_tv(app, c, h)
    before = snapshot(app)  # Pairing itself legitimately writes its audit row.
    assert tv.patch(endpoint, json=body, headers=h).status_code == 403
    current = source(c, d['id'])
    pending = reschedule(c, h, current, ['shopping:adapter'], start='2026-12-06', end='2026-12-12')
    partner, ph = member(app, 2)
    assert apply(partner, ph, pending, uuid4().hex).status_code == 403
    assert apply(tv, h, pending, uuid4().hex).status_code == 403
    assert snapshot(app) == before
    child, _, result = create_space(app, 'shopping-schedule-child')
    assert child.get(result['entry']).status_code == 303
    assert child.post('/api/login', json={'username': 'member1', 'password': 'second-home-password-one'}).status_code == 200
    ch = {'X-CSRF-Token': child.get('/api/me').json['csrf']}
    assert child.patch(endpoint, json=body, headers=ch).status_code == 404
    assert child.get('/api/journeys/' + d['id'] + '/reschedule').status_code == 404
    assert apply(child, ch, pending, uuid4().hex).status_code == 400
    assert snapshot(app) == before
