from test_app import app, member


def test_device_view_is_independent_persists_and_is_readonly(app):
    owner, headers = member(app)
    first, second = app.test_client(), app.test_client()
    for tv, name, focus, view in [(first, '家一', 'member1', 'week'), (second, '家二', 'member2', 'around')]:
        pair = tv.post('/api/pair/start', json={}).json
        assert owner.post('/api/pair/approve', json={'code': pair['code'], 'name': name,
                                                   'focus': focus, 'calendarView': view}, headers=headers).status_code == 200
        tv.post('/api/pair/poll', json={'secret': pair['secret']})
        shown = tv.get('/api/state').json['display']
        assert shown['focus'] == focus and shown['calendarView'] == view
        assert shown['layout']['hidden'] == []
    device = next(d for d in owner.get('/api/devices').json if d['name'] == '家一')
    path = '/api/devices/' + device['id']
    revision = owner.get('/api/state').json['revision']
    assert first.patch(path, json={'calendarView': 'today', 'revision': 1}, headers=headers).status_code == 403
    assert owner.patch(path, json={'calendarView': 'invalid', 'revision': 1}, headers=headers).status_code == 400
    assert owner.patch(path, json={'calendarView': 'today', 'focus': 'member2', 'revision': 1}, headers=headers).status_code == 200
    assert owner.patch(path, json={'calendarView': 'week', 'revision': 1}, headers=headers).status_code == 409
    shown = first.get('/api/state').json['display']
    assert shown['focus'] == 'member2' and shown['calendarView'] == 'today'
    assert shown['layout']['theme'] == 'forest'
    assert second.get('/api/state').json['display']['calendarView'] == 'around'
    assert owner.get('/api/state').json['revision'] == revision + 1
