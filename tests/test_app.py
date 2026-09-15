from datetime import datetime, timedelta
import pytest
from app import create_app, TZ

@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv('MEMBER1_PASSWORD', 'testing-password-one')
    monkeypatch.setenv('MEMBER2_PASSWORD', 'testing-password-two')
    return create_app({'TESTING': True, 'SECRET_KEY': 'test-only-secret', 'DATA_DIR': str(tmp_path), 'SESSION_COOKIE_SECURE': False})

def member(app, number=1):
    client = app.test_client()
    assert client.post('/api/login', json={'username': f'member{number}', 'password': 'testing-password-'+('one' if number == 1 else 'two')}).status_code == 200
    token = client.get('/api/me').json['csrf']
    return client, {'X-CSRF-Token': token}

def test_auth_csrf_origin(app):
    anonymous = app.test_client()
    assert anonymous.get('/api/state').status_code == 401
    c, h = member(app)
    assert c.post('/api/items/tasks', json={'title':'买牛奶'}).status_code == 403
    assert c.post('/api/items/tasks', json={'title':'买牛奶'}, headers={**h,'Origin':'https://evil.example'}).status_code == 403
    assert c.get('/.env').status_code == 404
    assert c.get('/static/../app.py').status_code == 404

def test_shared_crud_conflict(app):
    a, ah = member(app)
    b, bh = member(app, 2)
    result = a.post('/api/items/tasks', json={'title':'预约保洁'}, headers=ah)
    assert result.status_code == 201
    item = b.get('/api/state').json['tasks'][0]
    assert item['title'] == '预约保洁'
    path = '/api/items/tasks/'+item['id']
    assert b.patch(path, json={'revision':1,'done':True}, headers=bh).status_code == 200
    assert a.patch(path, json={'revision':1,'title':'过期修改'}, headers=ah).status_code == 409
    assert a.delete(path, json={'revision':1}, headers=ah).status_code == 409
    assert a.get('/api/state').json['tasks'][0]['done'] is True
    assert a.delete(path, json={'revision':2}, headers=ah).status_code == 200

def test_private_finance_isolation(app):
    a, ah = member(app)
    b, bh = member(app, 2)
    private = {'income':1234567,'spent':45678,'budget':100000,'month':'2026-09','revision':0,'owner':'member2'}
    assert a.put('/api/private-finance', json=private, headers=ah).status_code == 200
    assert a.get('/api/private-finance').json['income'] == 1234567
    assert b.get('/api/private-finance?owner=member1').json['income'] == 0
    assert '1234567' not in b.get('/api/state').get_data(as_text=True)
    assert a.put('/api/private-finance', json=private, headers=ah).status_code == 409

def test_tv_pair_readonly_revocation(app):
    a, ah = member(app)
    tv = app.test_client()
    pair = tv.post('/api/pair/start', json={}).json
    assert tv.post('/api/pair/poll', json={'secret':pair['secret']}).json['approved'] is False
    assert a.post('/api/pair/approve', json={'code':pair['code'],'name':'家一电视','focus':'member1'}, headers=ah).status_code == 200
    assert tv.post('/api/pair/poll', json={'secret':pair['secret']}).json['approved'] is True
    assert tv.get('/api/state').status_code == 200
    assert tv.get('/api/private-finance').status_code == 403
    assert tv.get('/api/devices').status_code == 403
    assert tv.post('/api/items/tasks', json={'title':'越权'}, headers=ah).status_code == 403
    assert a.get('/api/me', headers={'X-Display-Mode':'tv'}).json['user'] is None
    device = a.get('/api/devices').json[0]
    assert a.delete('/api/devices/'+device['id'], json={}, headers=ah).status_code == 200
    assert tv.get('/api/state').status_code == 401

def test_finance_amounts_and_conflicts(app):
    c,h = member(app)
    f = c.get('/api/state').json['finance']
    assert f['confirmedAt'] == ''
    assert c.put('/api/finance', json={**f,'wallet':1.23}, headers=h).status_code == 400
    assert c.put('/api/finance', json={**f,'wallet':True}, headers=h).status_code == 400
    assert c.put('/api/finance', json={**f,'wallet':1000000}, headers=h).status_code == 200
    assert c.put('/api/finance', json=f, headers=h).status_code == 409

def test_ics_recurrence_and_dedup(app):
    c,h = member(app)
    day = (datetime.now(TZ)+timedelta(days=2)).strftime('%Y%m%d')
    ics = '\r\n'.join(['BEGIN:VCALENDAR','VERSION:2.0','BEGIN:VEVENT','UID:example-123',f'DTSTART;TZID=Asia/Shanghai:{day}T100000',f'DTEND;TZID=Asia/Shanghai:{day}T110000','SUMMARY:共同午餐','LOCATION:上海餐厅','RRULE:FREQ=DAILY;COUNT=3','END:VEVENT','END:VCALENDAR'])
    payload = {'ics':ics,'owner':'shared','source':'Apple'}
    assert c.post('/api/calendar/import', json=payload, headers=h).json['imported'] == 3
    assert c.post('/api/calendar/import', json={**payload,'source':'Google'}, headers=h).status_code == 200
    events = c.get('/api/state').json['events']
    assert len(events) == 3
    assert all(e['location'] == '上海餐厅' for e in events)
    assert c.post('/api/calendar/import', json={**payload,'ics':ics.replace('DAILY','SECONDLY')}, headers=h).status_code == 400

def test_trip_task_link(app):
    c,h = member(app)
    trip = c.post('/api/items/trips', json={'title':'京都','start':'2026-10-01','end':'2026-10-06','budget':2000000}, headers=h).json
    assert c.post('/api/items/tasks', json={'title':'订酒店','tripId':trip['id']}, headers=h).status_code == 201
    assert c.delete('/api/items/trips/'+trip['id'], json={'revision':1}, headers=h).status_code == 200
    assert c.get('/api/state').json['tasks'][0]['tripId'] == ''

def test_single_day_event_has_exclusive_next_day_end(app):
    c,h = member(app)
    assert c.post('/api/items/events',json={'title':'全天休假','start':'2026-09-14T09:00:00+08:00','end':'2026-09-14T10:00:00+08:00','allDay':True},headers=h).status_code == 201
    event=c.get('/api/state').json['events'][0]
    assert event['start']=='2026-09-14T00:00:00+08:00'
    assert event['end']=='2026-09-15T00:00:00+08:00'
