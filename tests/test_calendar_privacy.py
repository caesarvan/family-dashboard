"""Real Flask/SQLite local calendar authority; synthetic members/TV, no network."""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import json
from pathlib import Path
import socket
import sqlite3

import pytest
from app import create_app, TZ
from test_app import member
from test_data_portability import unpack
from test_household_spaces import create_space


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('No network in calendar privacy tests')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)


@pytest.fixture
def app(tmp_path):
    return create_app({'TESTING': True, 'DATA_DIR': str(tmp_path / 'data'),
        'SECRET_KEY': 'synthetic-calendar-privacy-only', 'SESSION_COOKIE_SECURE': False,
        'PUBLIC_ORIGIN': 'http://localhost', 'MEMBER1_PASSWORD': 'testing-password-one',
        'MEMBER2_PASSWORD': 'testing-password-two', 'NVIDIA_API_KEY': '', 'OPENAI_API_KEY': '',
        'MICROSOFT_CLIENT_ID': '', 'MICROSOFT_CLIENT_SECRET': '', 'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': ''})


def db(app):
    con = sqlite3.connect(Path(app.config['DATA_DIR']) / 'household.sqlite3')
    con.row_factory = sqlite3.Row
    return con


def fields(**extra):
    day = datetime.now(TZ).date().isoformat()
    return {'title': '合成私密日程独占标题', 'location': '合成私密地点', 'note': '合成个人备注',
            'start': day + 'T10:00:00+08:00', 'end': day + 'T11:00:00+08:00', **extra}


def create(c, h, **extra):
    response = c.post('/api/items/events', json=fields(**extra), headers=h)
    assert response.status_code == 201, response.json
    return response.json['id']


def events(c):
    response = c.get('/api/state'); assert response.status_code == 200
    return response.json['events']


def tv(app, c, h):
    viewer = app.test_client(); pair = viewer.post('/api/pair/start', json={}).json
    assert c.post('/api/pair/approve', json={'code': pair['code'], 'name': '合成电视', 'focus': 'member1'}, headers=h).status_code == 200
    assert viewer.post('/api/pair/poll', json={'secret': pair['secret']}).json['approved']
    return viewer


def raw(app):
    with closing(db(app)) as con:
        return {t: [tuple(r) for r in con.execute('SELECT * FROM '+t+' ORDER BY rowid')] for t in ('entities', 'audit', 'settings')}


@pytest.mark.parametrize('owner', ['member1', 'member2', 'shared'])
def test_new_private_creator_is_actual_member_not_participant(app, owner):
    c, h = member(app); partner, ph = member(app, 2); screen = tv(app, c, h)
    uid = create(c, h, owner=owner)
    own = events(c)[0]
    assert (own['id'], own['createdBy'], own['visibility'], own['owner']) == (uid, 'member1', 'private', owner)
    assert events(partner) == events(screen) == []
    before = raw(app)
    for revision in (1, 999):
        for verb in ('patch', 'delete'):
            response = getattr(partner, verb)('/api/items/events/'+uid, json={'revision': revision, 'title': '越权'}, headers=ph)
            assert response.status_code == 404 and response.json['code'] == 'calendar_event_unavailable'
            missing = getattr(partner, verb)('/api/items/events/nonexistent', json={'revision': revision}, headers=ph)
            assert missing.status_code == 404 and missing.json == response.json
    assert raw(app) == before
    assert screen.post('/api/items/events', json=fields(), headers=h).status_code == 403


@pytest.mark.parametrize('creator', ['member2', 'member1', None, {}, ''])
def test_create_rejects_any_client_supplied_creator(app, creator):
    c, h = member(app); before = raw(app)
    response = c.post('/api/items/events', json=fields(createdBy=creator), headers=h)
    assert response.status_code == 400 and response.json['code'] == 'invalid_calendar_privacy'
    assert raw(app) == before


@pytest.mark.parametrize('visibility', ['public', None, False, {}, []])
def test_invalid_privacy_not_silently_shared(app, visibility):
    c, h = member(app); before = raw(app)
    response = c.post('/api/items/events', json=fields(visibility=visibility), headers=h)
    assert response.status_code == 400 and raw(app) == before


def test_share_collaborative_edit_creator_only_revoke_and_revision(app):
    c, h = member(app); partner, ph = member(app, 2); screen = tv(app, c, h)
    uid = create(c, h); url = '/api/items/events/'+uid
    assert c.patch(url, json={'revision': 1, 'createdBy': 'member2'}, headers=h).status_code == 400
    assert c.patch(url, json={'revision': 1, 'visibility': 'shared'}, headers=h).status_code == 200
    assert events(partner)[0]['createdBy'] == 'member1' and events(screen)[0]['id'] == uid
    assert partner.patch(url, json={'revision': 2, 'visibility': 'private'}, headers=ph).status_code == 403
    assert partner.patch(url, json={'revision': 2, 'title': '合成协作修改', 'createdBy': 'member1'}, headers=ph).status_code == 200
    assert events(c)[0]['visibility'] == 'shared'
    assert c.patch(url, json={'revision': 2, 'visibility': 'private'}, headers=h).status_code == 409
    assert c.patch(url, json={'revision': 3, 'visibility': 'private', 'owner': 'member2'}, headers=h).status_code == 200
    assert events(partner) == events(screen) == [] and events(c)[0]['revision'] == 4
    assert partner.delete(url, json={'revision': 4}, headers=ph).status_code == 404
    assert c.delete(url, json={'revision': 3}, headers=h).status_code == 409
    assert c.delete(url, json={'revision': 4}, headers=h).status_code == 200


def legacy_seed(app, uid='legacy', **extra):
    value = fields(owner='member2', **extra)
    with closing(db(app)) as con:
        con.execute("INSERT INTO entities(id,kind,data,updated_at) VALUES(?,'events',?,?)", (uid, json.dumps(value), datetime.now(TZ).isoformat()))
        con.commit()
    return uid


def test_legacy_shared_not_reassigned_or_silently_migrated(app):
    c, h = member(app); partner, ph = member(app, 2); screen = tv(app, c, h)
    uid = legacy_seed(app); before = raw(app)
    assert all(events(x)[0]['id'] == uid for x in (c, partner, screen))
    assert raw(app) == before
    assert c.patch('/api/items/events/'+uid, json={'revision': 1, 'visibility': 'private'}, headers=h).status_code == 403
    assert partner.patch('/api/items/events/'+uid, json={'revision': 1, 'title': '旧共同日程修改'}, headers=ph).status_code == 200
    assert not {'createdBy', 'visibility'} & events(c)[0].keys()


def test_explicit_shared_creation_and_legacy_cloud_travel_remain_shared(app):
    c, h = member(app); partner, ph = member(app, 2); screen = tv(app, c, h)
    created = create(c, h, visibility='shared')
    legacy_seed(app, 'cloud', sync={'readOnly': True, 'sourceId': 'synthetic-source'})
    legacy_seed(app, 'journey', journeyId='synthetic-journey', travelTiming={'kind': 'allDay'})
    assert {r['id'] for r in events(partner)} == {created, 'cloud', 'journey'}
    assert {r['id'] for r in events(screen)} == {created, 'cloud', 'journey'}
    assert partner.patch('/api/items/events/cloud', json={'revision': 1, 'title': '拒绝云编辑'}, headers=ph).status_code == 403


@pytest.mark.parametrize('metadata', [{'visibility': 'private'}, {'createdBy': 'member1'}, {'createdBy': 'member1', 'visibility': 'invalid'}])
def test_partial_corrupt_metadata_is_fail_closed(app, metadata):
    c, h = member(app); partner, _ = member(app, 2); screen = tv(app, c, h)
    legacy_seed(app, **metadata)
    assert events(c) == events(partner) == events(screen) == []


def test_assistant_search_brief_plan_and_export_follow_same_acl(app):
    c, h = member(app); partner, ph = member(app, 2); uid = create(c, h)
    for client in (c, partner):
        allowed = client is c
        assert bool(client.get('/api/assistant/search?q=独占标题').json['matches']) is allowed
        assert bool(client.get('/api/assistant/brief').json['events']) is allowed
    result = partner.post('/api/assistant/plan', json={'prompt': '搜索 独占标题', 'useModel': False}, headers=ph)
    assert result.status_code == 200 and result.json['matches'] == []
    own, _ = unpack(c.post('/api/portability/export', json={}, headers=h))
    assert own['personal']['calendarEvents'][0]['id'] == uid
    for include in (False, True):
        other, archive = unpack(partner.post('/api/portability/export', json={'includeShared': include}, headers=ph))
        assert other['personal']['calendarEvents'] == []
        assert '独占标题'.encode() not in b''.join(archive.values())
        assert uid.encode() not in b''.join(archive.values())
    assert partner.get('/api/portability/summary').json['shared']['events'] == 0
    assert c.get('/api/portability/summary').json['personal']['calendarEvents'] == 1
    assert c.patch('/api/items/events/'+uid, json={'revision': 1, 'visibility': 'shared'}, headers=h).status_code == 200
    shared, _ = unpack(partner.post('/api/portability/export', json={'includeShared': True}, headers=ph))
    assert shared['shared']['entities']['events'][0]['createdBy'] == 'member1'
    assert c.patch('/api/items/events/'+uid, json={'revision': 2, 'visibility': 'private'}, headers=h).status_code == 200
    assert partner.get('/api/assistant/search?q=独占标题').json['total'] == 0
    assert partner.get('/api/assistant/brief').json['events'] == []


def ics():
    day = (datetime.now(TZ) + timedelta(days=2)).strftime('%Y%m%d')
    return '\r\n'.join(['BEGIN:VCALENDAR', 'VERSION:2.0', 'BEGIN:VEVENT', 'UID:privacy-synthetic',
        f'DTSTART;TZID=Asia/Shanghai:{day}T100000', f'DTEND;TZID=Asia/Shanghai:{day}T110000',
        'SUMMARY:合成导入私人安排', 'END:VEVENT', 'END:VCALENDAR'])


def test_ics_default_private_reimport_preserves_acl_and_cannot_overwrite_other_creator(app):
    c, h = member(app); partner, ph = member(app, 2)
    data = {'ics': ics(), 'owner': 'shared', 'source': 'Apple'}
    assert c.post('/api/calendar/import', json=data, headers=h).status_code == 200
    item = events(c)[0]; assert item['visibility'] == 'private' and events(partner) == []
    before = raw(app)
    assert partner.post('/api/calendar/import', json=data, headers=ph).status_code == 404
    assert raw(app) == before
    assert c.post('/api/calendar/import', json=data, headers=h).status_code == 200
    assert len(events(c)) == 1 and events(c)[0]['createdBy'] == 'member1'
    assert c.patch('/api/items/events/'+item['id'], json={'revision': 2, 'visibility': 'shared'}, headers=h).status_code == 200
    assert c.post('/api/calendar/import', json=data, headers=h).status_code == 200
    assert events(partner)[0]['visibility'] == 'shared' and events(partner)[0]['revision'] == 4


def test_same_member_id_in_second_household_is_not_creator_authority(app):
    c, h = member(app); uid = create(c, h)
    other, _, entry = create_space(app)
    assert other.get(entry['entry']).status_code == 303
    assert other.post('/api/login', json={'username': 'member1', 'password': 'second-home-password-one'}).status_code == 200
    oh = {'X-CSRF-Token': other.get('/api/me').json['csrf']}
    assert events(other) == []
    assert other.patch('/api/items/events/'+uid, json={'revision': 1, 'title': '跨户写入'}, headers=oh).status_code == 404
    own = create(other, oh, title='第二户私密日程')
    assert [r['id'] for r in events(c)] == [uid] and [r['id'] for r in events(other)] == [own]


def test_private_acl_persists_after_app_restart_and_session_logout(app):
    c, h = member(app); uid = create(c, h)
    restarted = create_app(dict(app.config))
    owner, _ = member(restarted); partner, _ = member(restarted, 2)
    assert events(owner)[0]['id'] == uid and events(partner) == []
    assert c.post('/api/logout', json={}, headers=h).status_code == 200
    assert c.get('/api/state').status_code == 401
    assert c.patch('/api/items/events/'+uid, json={'revision': 1, 'visibility': 'shared'}, headers=h).status_code == 401


def test_export_rechecks_share_revoked_during_zip_build(app, monkeypatch):
    import data_portability as portability
    c, h = member(app); partner, ph = member(app, 2); uid = create(c, h, visibility='shared')
    original = portability.ZipFile
    revoked = []
    class ChangingZip(original):
        def close(self):
            result = super().close()
            if not revoked:
                revoked.append(True)
                with ThreadPoolExecutor(max_workers=1) as pool:
                    response = pool.submit(lambda: c.patch('/api/items/events/'+uid,
                        json={'revision': 1, 'visibility': 'private'}, headers=h)).result(timeout=15)
                assert response.status_code == 200
            return result
    monkeypatch.setattr(portability, 'ZipFile', ChangingZip)
    result = partner.post('/api/portability/export', json={'includeShared': True}, headers=ph)
    assert revoked and result.status_code == 409 and result.mimetype == 'application/json'
    assert '独占标题' not in result.get_data(as_text=True)
    assert events(partner) == [] and events(c)[0]['visibility'] == 'private'


def test_ics_batch_failure_rolls_back_earlier_entries(app):
    c, h = member(app); partner, ph = member(app, 2)
    original = ics()
    assert c.post('/api/calendar/import', json={'ics': original, 'owner': 'shared'}, headers=h).status_code == 200
    # A new row is written first, then the existing private row is encountered.
    new_event = original.split('BEGIN:VEVENT', 1)[1].split('END:VEVENT', 1)[0].replace('privacy-synthetic', 'another-synthetic')
    batch = original.replace('BEGIN:VEVENT', 'BEGIN:VEVENT'+new_event+'END:VEVENT\r\nBEGIN:VEVENT', 1)
    before = raw(app)
    result = partner.post('/api/calendar/import', json={'ics': batch, 'owner': 'shared'}, headers=ph)
    assert result.status_code == 404 and raw(app) == before
