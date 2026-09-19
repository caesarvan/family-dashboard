"""Real Flask/SQLite reminder state, clock, races and authority; no network."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket
import sqlite3
from threading import Barrier

from flask import has_request_context, request
import pytest
from app import create_app
from membership_storage import HouseholdConnection
import household_memberships
import task_reminders as reminders
from test_app import member
from test_household_spaces import create_space


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs): raise AssertionError('No network in reminder tests')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)


@pytest.fixture
def app(tmp_path, monkeypatch):
    moment = [datetime(2026, 10, 10, 1, tzinfo=timezone.utc)]
    monkeypatch.setattr(reminders, 'clock', lambda: moment[0])
    app = create_app({'TESTING': True, 'DATA_DIR': str(tmp_path / 'data'),
        'SECRET_KEY': 'synthetic-reminder-secret', 'SESSION_COOKIE_SECURE': False,
        'PUBLIC_ORIGIN': 'http://localhost', 'MEMBER1_PASSWORD': 'testing-password-one',
        'MEMBER2_PASSWORD': 'testing-password-two', 'OPENAI_API_KEY': '', 'NVIDIA_API_KEY': '',
        'MICROSOFT_CLIENT_ID': '', 'MICROSOFT_CLIENT_SECRET': '', 'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': ''})
    app.test_clock = moment
    return app


def db(app):
    con = sqlite3.connect(Path(app.config['DATA_DIR'])/'household.sqlite3', timeout=10)
    con.row_factory = sqlite3.Row
    return con


def create(c, h, **fields):
    r = c.post('/api/items/tasks', json={'title': '合成提醒事项', 'owner': 'shared', 'due': '2026-10-10', 'sourceId': '', **fields}, headers=h)
    assert r.status_code == 201, r.json
    return r.json['id']


def inbox(c, mode='all'):
    r = c.get('/api/task-reminders?filter='+mode)
    assert r.status_code == 200, r.json
    return r.json


def item(c, uid):
    return next(x for x in inbox(c)['items'] if x['task']['id'] == uid)


def value(entry, key='a', action='read', **kwargs):
    return {'requestId': key*32, 'occurrence': entry['occurrence'], 'revision': entry['revision'], 'action': action, **kwargs}


def act(c, h, uid, data):
    return c.post('/api/task-reminders/'+uid+'/actions', json=data, headers=h)


def patch(c, h, uid, **fields):
    original = next(x for x in c.get('/api/state').json['tasks'] if x['id'] == uid)
    r = c.patch('/api/items/tasks/'+uid, json={'revision': original['revision'], **fields}, headers=h)
    assert r.status_code == 200, r.json


def snapshot(app):
    with closing(db(app)) as con:
        return {t: [tuple(r) for r in con.execute('SELECT * FROM '+t+' ORDER BY rowid')]
                for t in ('entities', 'settings', 'audit', 'task_reminders', 'task_reminder_operations')}


def test_threshold_overdue_routing_pure_reads_and_worker_initial_revision(app):
    c, h = member(app); partner, _ = member(app, 2)
    shared = create(c, h); mine = create(c, h, owner='member1'); overdue = create(c, h, due='2026-01-01')
    create(c, h, due=''); create(c, h, done=True); create(c, h, due='2026-10-11')
    app.test_clock[0] -= timedelta(microseconds=1)
    assert {x['task']['id'] for x in inbox(c)['items']} == {overdue}
    app.test_clock[0] += timedelta(microseconds=1)
    before = snapshot(app)
    assert {x['task']['id'] for x in inbox(c)['items']} == {shared, mine, overdue}
    assert {x['task']['id'] for x in inbox(partner)['items']} == {shared, overdue}
    assert snapshot(app) == before and inbox(c)['worker']['lastCheckedAt'] is None
    first = item(c, shared); assert first['revision'] == 0
    engine = app.extensions['task_reminders']; assert engine.tick()['generated'] == 5
    after = snapshot(app); assert engine.tick()['generated'] == 0 and snapshot(app) == after
    assert item(c, shared) == first and inbox(c)['worker']['stale'] is False
    assert act(c, h, shared, value(first)).status_code == 200
    app.test_clock[0] += timedelta(seconds=61)
    assert inbox(c)['worker']['stale'] is True


def test_private_state_read_snooze_expiry_replay_unknown_receipt_restart(app):
    c, h = member(app); partner, ph = member(app, 2); uid = create(c, h)
    original = snapshot(app)['entities']; first = item(c, uid)
    data = value(first); saved = act(c, h, uid, data)
    assert saved.status_code == 200 and saved.json['operation']['revision'] == 1
    assert inbox(c)['unreadCount'] == 0 and inbox(partner)['unreadCount'] == 1
    assert partner.get('/api/task-reminders/operations/'+'a'*32).status_code == 404
    until = reminders.iso(app.test_clock[0]+timedelta(hours=1))
    snooze = value(item(c, uid), 'b', 'snooze', snoozedUntil=until)
    receipt = act(c, h, uid, snooze).json
    assert receipt['operation']['readAt'] is None and item(c, uid)['status'] == 'snoozed'
    app.test_clock[0] += timedelta(hours=2)
    assert item(c, uid)['status'] == 'unread'  # no worker required
    before = snapshot(app)
    assert c.get('/api/task-reminders/operations/'+'b'*32).json == receipt
    assert act(c, h, uid, snooze).json == receipt and snapshot(app) == before
    assert act(c, h, uid, {**snooze, 'snoozedUntil': reminders.iso(app.test_clock[0]+timedelta(hours=1))}).json['code'] == 'reminder_request_conflict'
    again = act(c, h, uid, value(item(c, uid), 'c'))
    assert again.json['operation']['snoozedUntil'] is None and snapshot(app)['entities'] == original
    restarted = create_app(dict(app.config)); fresh, _ = member(restarted)
    assert item(fresh, uid)['status'] == 'read'
    assert fresh.get('/api/task-reminders/operations/'+'b'*32).json == receipt
    assert act(partner, ph, uid, value(item(partner, uid))).status_code == 200  # same key independently owned


def test_live_filter_reopen_same_due_history_new_due_and_dependencies(app):
    c, h = member(app); predecessor = create(c, h, due=''); uid = create(c, h, dependsOn=[predecessor])
    initial = item(c, uid); assert initial['task']['blockedBy'] == [predecessor]
    assert act(c, h, uid, value(initial)).status_code == 200
    patch(c, h, uid, title='改名', dependsOn=[])
    assert item(c, uid)['occurrence'] == initial['occurrence'] and item(c, uid)['status'] == 'read'
    patch(c, h, uid, done=True); assert not inbox(c)['items']
    committed = c.get('/api/task-reminders/operations/'+'a'*32).json
    before = snapshot(app)
    assert act(c, h, uid, value(initial)).json == committed and snapshot(app) == before
    app.extensions['task_reminders'].tick()
    patch(c, h, uid, done=False); assert item(c, uid)['status'] == 'read'
    patch(c, h, uid, owner='member2'); assert not inbox(c)['items']
    assert act(c, h, uid, value(initial, 'b')).json['code'] == 'reminder_unavailable'
    patch(c, h, uid, owner='member1', due='2026-10-09')
    new = item(c, uid); assert new['occurrence'] != initial['occurrence'] and new['revision'] == 0
    assert act(c, h, uid, value(initial, 'b')).json['code'] == 'reminder_stale'
    patch(c, h, uid, due='2026-10-10'); assert item(c, uid)['status'] == 'read'
    original = next(x for x in c.get('/api/state').json['tasks'] if x['id'] == uid)
    assert c.delete('/api/items/tasks/'+uid, json={'revision': original['revision']}, headers=h).status_code == 200
    assert not inbox(c)['items']; app.extensions['task_reminders'].tick()
    receipt = c.get('/api/task-reminders/operations/'+'a'*32)
    assert receipt.status_code == 200 and 'task' not in receipt.json['operation'] and '改名' not in receipt.get_data(as_text=True)
    before = snapshot(app)
    assert act(c, h, uid, value(initial)).json == committed and snapshot(app) == before


def test_read_rechecks_session_revocation_after_projection_and_schema_is_minimal(app, monkeypatch):
    c, h = member(app); uid = create(c, h)
    with closing(db(app)) as con:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        assert len(tables) == 71
        columns = {r['name'] for r in con.execute('PRAGMA table_info(task_reminders)')}
        assert columns == {'owner', 'task_id', 'due', 'read_at', 'snoozed_until', 'revision', 'active', 'created_at', 'updated_at'}
    project = reminders.live_tasks
    def revoke_after_projection(con, moment):
        result = project(con, moment)
        assert uid in result
        with closing(db(app)) as other, other:
            other.execute("UPDATE member_sessions SET revoked_at=1 WHERE owner='member1'")
        return result
    monkeypatch.setattr(reminders, 'live_tasks', revoke_after_projection)
    before = snapshot(app)
    response = c.get('/api/task-reminders')
    assert response.status_code == 401 and '合成提醒事项' not in response.get_data(as_text=True)
    assert snapshot(app) == before


@pytest.mark.parametrize('bad', [{'revision': True}, {'revision': -1}, {'requestId': 'bad'}, {'occurrence': 'bad'},
    {'action': 'complete'}, {'action': 'snooze'}, {'action': 'snooze', 'snoozedUntil': '2026-10-11T09:00:00'},
    {'action': 'snooze', 'snoozedUntil': '2026-10-10T01:00:00Z'},
    {'action': 'snooze', 'snoozedUntil': '2027-10-10T01:00:00Z'}, {'owner': 'member2'}, {'snoozedUntil': None}])
def test_invalid_actions_are_atomic(app, bad):
    c, h = member(app); uid = create(c, h); before = snapshot(app)
    r = act(c, h, uid, {**value(item(c, uid)), **bad})
    assert r.status_code == 400 and r.json['code'] == 'invalid_reminder_request'
    assert snapshot(app) == before


@pytest.mark.parametrize('query', ['owner=member2', 'filter=snoozed', 'page=-1', 'page=01', 'page=0&page=1'])
def test_query_is_strict(app, query):
    c, _ = member(app)
    assert c.get('/api/task-reminders?'+query).status_code == 400


def test_auth_tv_csrf_recipient_and_household_boundaries(app):
    c, h = member(app); partner, ph = member(app, 2); uid = create(c, h, owner='member1'); data = value(item(c, uid))
    assert app.test_client().get('/api/task-reminders').status_code == 401
    assert act(c, {}, uid, data).status_code == 403
    assert act(c, {**h, 'Origin': 'https://invalid.test'}, uid, data).status_code == 403
    assert act(partner, ph, uid, data).status_code == 409
    tv = app.test_client(); pair = tv.post('/api/pair/start', json={}).json
    assert c.post('/api/pair/approve', json={'code':pair['code'],'name':'合成电视','focus':'member1'},headers=h).status_code == 200
    assert tv.post('/api/pair/poll',json={'secret':pair['secret']}).json['approved']
    for path in ('/api/task-reminders','/api/task-reminders/operations/'+'a'*32): assert tv.get(path).status_code == 403
    assert act(tv, h, uid, data).status_code == 403
    assert 'readAt' not in tv.get('/api/state').get_data(as_text=True)
    other, _, space = create_space(app)
    other.get(space['entry']); assert other.post('/api/login', json={'username':'member1','password':'second-home-password-one'}).status_code == 200
    oh = {'X-CSRF-Token': other.get('/api/me').json['csrf']}
    assert not inbox(other)['items'] and act(other,oh,uid,data).status_code == 409


@pytest.mark.parametrize('operation', ['read', 'action', 'receipt'])
def test_revoked_after_request_guard_is_denied(app, operation):
    c, h = member(app); uid = create(c, h); data = value(item(c, uid))
    assert act(c,h,uid,data).status_code == 200
    path={'read':'/api/task-reminders','action':'/api/task-reminders/'+uid+'/actions','receipt':'/api/task-reminders/operations/'+'a'*32}[operation]
    before=snapshot(app)
    def revoke():
        if request.path == path:
            with closing(db(app)) as con, con:con.execute("UPDATE member_sessions SET revoked_at=1 WHERE owner='member1'")
    app.before_request_funcs[None].append(revoke)
    r=c.open(path,method='POST' if operation=='action' else 'GET',json=data if operation=='action' else None,headers=h)
    assert r.status_code == 401 and snapshot(app)==before


def test_concurrent_same_request_different_request_and_tick_initialization(app, monkeypatch):
    c,h=member(app); second,sh=member(app); uid=create(c,h); data=value(item(c,uid))
    original=HouseholdConnection.execute; barrier=Barrier(2)
    def execute(con,sql,*args,**kwargs):
        if sql=='BEGIN IMMEDIATE' and has_request_context() and request.path.endswith('/actions'):barrier.wait(timeout=10)
        return original(con,sql,*args,**kwargs)
    monkeypatch.setattr(HouseholdConnection,'execute',execute)
    with ThreadPoolExecutor(2) as pool:
        a=pool.submit(act,c,h,uid,data);b=pool.submit(act,second,sh,uid,data)
        results=[a.result(timeout=20),b.result(timeout=20)]
    assert [r.status_code for r in results]==[200,200] and results[0].json==results[1].json
    with ThreadPoolExecutor(2) as pool:
        a=pool.submit(act,c,h,uid,value(item(c,uid),'b'));b=pool.submit(act,second,sh,uid,value(item(second,uid),'c'))
        results=[a.result(timeout=20),b.result(timeout=20)]
    assert sorted(r.status_code for r in results)==[200,409]
    monkeypatch.setattr(HouseholdConnection,'execute',original)
    fresh=create(c,h); prior=item(c,fresh)
    with ThreadPoolExecutor(2) as pool:
        a=pool.submit(app.extensions['task_reminders'].tick);b=pool.submit(act,c,h,fresh,value(prior,'d'))
        a.result(timeout=20);assert b.result(timeout=20).status_code==200
    with closing(db(app)) as con:
        assert con.execute('SELECT count(*) FROM task_reminders WHERE owner=? AND task_id=?',('member1',fresh)).fetchone()[0]==1


def test_membership_stop_clears_both_tables_atomically_logout_preserves(app):
    c,h=member(app); partner,ph=member(app,2);uid=create(c,h)
    assert act(partner,ph,uid,value(item(partner,uid))).status_code==200
    before=snapshot(app)
    assert partner.post('/api/logout',json={},headers=ph).status_code==200
    assert snapshot(app)==before
    partner,ph=member(app,2);assert item(partner,uid)['status']=='read'
    with closing(db(app)) as con:
        con.execute('BEGIN IMMEDIATE')
        household_memberships._stop(con,'default','member2',1,1,'removed',1234)
        assert con.execute("SELECT count(*) FROM task_reminders WHERE owner='member2'").fetchone()[0]==0
        assert con.execute("SELECT count(*) FROM task_reminder_operations WHERE owner='member2'").fetchone()[0]==0
        con.rollback()
    assert item(partner,uid)['status']=='read'
    with closing(db(app)) as con,con:
        con.execute('BEGIN IMMEDIATE');household_memberships._stop(con,'default','member2',1,1,'removed',1234)
    assert partner.get('/api/task-reminders').status_code==401
    with closing(db(app)) as con,con:con.execute("UPDATE household_memberships SET state='active' WHERE member_id='member2'")
    rejoined,_=member(app,2);assert item(rejoined,uid)['revision']==0 and item(rejoined,uid)['status']=='unread'


def test_cloud_mirrors_require_real_selected_shared_source_and_active_account_owner(app):
    c,h=member(app);uid=create(c,h)
    with closing(db(app)) as con,con:
        con.execute("INSERT INTO cloud_accounts(id,owner,provider,client_id,subject,name,email,tokens) VALUES('a','member1','microsoft','c','s','Synthetic','','none')")
        con.execute("INSERT INTO cloud_sources(id,account_id,remote_id,kind,name,owner) VALUES('s','a','remote-list','tasks','Synthetic','shared')")
        raw=json.loads(con.execute('SELECT data FROM entities WHERE id=?',(uid,)).fetchone()[0])
        raw['sync']={'sourceId':'s','remoteId':'r','provider':'microsoft','version':'v1','readOnly':False}
        con.execute('UPDATE entities SET data=? WHERE id=?',(json.dumps(raw),uid))
    assert not inbox(c)['items']  # forged/stale sync without an actual mirror link
    with closing(db(app)) as con,con:con.execute('INSERT INTO cloud_items VALUES(?,?,?)',(uid,'s','r'))
    partner,ph=member(app,2);assert item(partner,uid)['task']['sync']['sourceId']=='s'
    before=snapshot(app)['entities'];assert act(partner,ph,uid,value(item(partner,uid))).status_code==200
    assert snapshot(app)['entities']==before
    with closing(db(app)) as con,con:con.execute("UPDATE cloud_sources SET owner='member1' WHERE id='s'")
    assert not inbox(partner)['items']
    with closing(db(app)) as con,con:
        con.execute("UPDATE cloud_sources SET owner='shared' WHERE id='s'")
        con.execute("UPDATE household_memberships SET state='removed' WHERE member_id='member1'")
    assert not inbox(partner)['items']


def test_capacity_preserves_history_and_receipts_and_pagination(app,monkeypatch):
    c,h=member(app)
    with closing(db(app)) as con,con:
        for i in range(41):
            con.execute("INSERT INTO entities(id,kind,data,updated_at) VALUES(?,'tasks',?,'synthetic')",(f't-{i:03}',json.dumps({'title':f'合成{i}','owner':'member1','due':'2026-10-10','done':False})))
    first=inbox(c);assert len(first['items'])==40 and first['total']==41 and first['hasMore']
    assert len(c.get('/api/task-reminders?filter=all&page=1').json['items'])==1
    monkeypatch.setattr(reminders,'MAX_STATES',1);engine=app.extensions['task_reminders'];assert engine.tick()['capacityBlocked']
    assert act(c,h,'t-000',value(item(c,'t-000'))).status_code==200
    before=snapshot(app)
    assert act(c,h,'t-001',value(item(c,'t-001'),'b')).json['code']=='reminder_capacity'
    assert snapshot(app)==before
    monkeypatch.setattr(reminders,'MAX_OPERATIONS',1)
    assert act(c,h,'t-000',value(item(c,'t-000'),'c')).json['code']=='reminder_capacity'
    assert snapshot(app)==before and c.get('/api/task-reminders/operations/'+'a'*32).status_code==200


def test_worker_runs_reminder_phase_before_cloud_and_continues_after_error(monkeypatch):
    import sync_worker
    calls=[]
    class Phase:
        def __init__(self,name):self.name=name
        def tick(self):
            calls.append(self.name)
            if self.name=='task_reminders':raise RuntimeError('synthetic')
    class App:extensions={n:Phase(n) for n in ('task_reminders','task_publish','calendar_publish','cloud_accounts','household_routines')}
    class Platform:
        def child(self,_):return App()
    sync_worker.sync_household(Platform(),{})
    assert calls==['task_reminders','task_publish','calendar_publish','cloud_accounts','household_routines']
