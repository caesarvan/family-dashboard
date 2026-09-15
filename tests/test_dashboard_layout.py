"""Private home layouts, optimistic concurrency and forward-compatible stored cards."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3

import pytest

from dashboard_preferences import CARD_ORDER
from test_app import app, member
from test_household_spaces import create_space


def layout(revision=0, order=None, hidden=None):
    return {'revision': revision, 'order': list(CARD_ORDER) if order is None else order,
            'hidden': [] if hidden is None else hidden}


def test_layout_round_trip_member_isolation_and_no_shared_payload(app):
    a, ah = member(app)
    b, _ = member(app, 2)
    assert a.get('/api/dashboard-layout').json == layout()
    custom = layout(order=['trips', 'tasks', 'shopping', 'calendar', 'finance'], hidden=['finance'])
    saved = a.put('/api/dashboard-layout', json=custom, headers=ah)
    assert saved.status_code == 200 and saved.json == {**custom, 'revision': 1}
    assert a.get('/api/dashboard-layout').json == saved.json
    assert b.get('/api/dashboard-layout?owner=member1').json == layout()
    assert 'dashboard' not in a.get('/api/state').get_data(as_text=True)
    assert a.get('/api/preferences').json == {'theme': 'forest', 'density': 'comfortable', 'homeView': 'today'}
    assert a.put('/api/dashboard-layout', json=saved.json, headers=ah).json['revision'] == 1


def test_layout_revision_conflict_and_default_restore(app):
    a, ah = member(app)
    custom = a.put('/api/dashboard-layout', json=layout(hidden=['finance']), headers=ah).json
    stale = a.put('/api/dashboard-layout', json=layout(hidden=['tasks']), headers=ah)
    assert stale.status_code == 409
    assert a.get('/api/dashboard-layout').json == custom
    reset = a.put('/api/dashboard-layout', json=layout(revision=1), headers=ah)
    assert reset.status_code == 200 and reset.json == layout(revision=2)


@pytest.mark.parametrize('payload', [
    {'revision': True, 'order': list(CARD_ORDER), 'hidden': []},
    {'revision': -1, 'order': list(CARD_ORDER), 'hidden': []},
    {'revision': '0', 'order': list(CARD_ORDER), 'hidden': []},
    {'revision': 0, 'order': 'calendar', 'hidden': []},
    {'revision': 0, 'order': ['unknown'], 'hidden': []},
    {'revision': 0, 'order': [None], 'hidden': []},
    {'revision': 0, 'order': list(CARD_ORDER), 'hidden': list(CARD_ORDER)},
    {'revision': 0, 'order': list(CARD_ORDER), 'hidden': ['unknown']},
    {'revision': 0, 'order': list(CARD_ORDER), 'hidden': [], 'owner': 'member2'},
    {'revision': 0, 'order': ['calendar'] * 51, 'hidden': []},
])
def test_layout_rejects_invalid_without_write(app, payload):
    a, ah = member(app)
    assert a.put('/api/dashboard-layout', json=payload, headers=ah).status_code == 400
    assert a.get('/api/dashboard-layout').json == layout()


def test_layout_deduplicates_and_appends_missing_known_cards(app):
    a, ah = member(app)
    saved = a.put('/api/dashboard-layout', json=layout(order=['trips', 'trips'], hidden=['tasks', 'tasks']), headers=ah)
    assert saved.status_code == 200
    assert saved.json == layout(1, ['trips', 'calendar', 'finance', 'tasks', 'shopping'], ['tasks'])


def test_layout_preserves_future_stored_keys_on_older_client_save(app):
    a, ah = member(app)
    future = {'order': ['calendar', 'future-weather', 'finance'], 'hidden': ['future-weather']}
    with sqlite3.connect(Path(app.config['DATA_DIR']) / 'household.sqlite3') as con:
        con.execute('INSERT INTO member_dashboard_layout VALUES(?,?,?)', ('member1', json.dumps(future), 5))
    read = a.get('/api/dashboard-layout').json
    assert read['order'] == ['calendar', 'future-weather', 'finance', 'tasks', 'shopping', 'trips']
    saved = a.put('/api/dashboard-layout', json=layout(5, hidden=['trips']), headers=ah)
    assert saved.status_code == 200
    assert saved.json['order'] == list(CARD_ORDER) + ['future-weather']
    assert saved.json['hidden'] == ['trips', 'future-weather']


def test_layout_denies_anonymous_tv_csrf_and_cross_origin(app):
    anonymous = app.test_client()
    assert anonymous.get('/api/dashboard-layout').status_code == 401
    a, ah = member(app)
    assert a.put('/api/dashboard-layout', json=layout()).status_code == 403
    assert a.put('/api/dashboard-layout', json=layout(), headers={**ah, 'Origin': 'https://other.example'}).status_code == 403
    tv = app.test_client()
    pair = tv.post('/api/pair/start', json={}).json
    assert a.post('/api/pair/approve', json={'code': pair['code'], 'name': 'Test TV', 'focus': 'member1'}, headers=ah).status_code == 200
    assert tv.post('/api/pair/poll', json={'secret': pair['secret']}).json['approved']
    assert tv.get('/api/dashboard-layout').status_code == 403
    assert tv.put('/api/dashboard-layout', json=layout(), headers=ah).status_code == 403


def test_layout_household_isolation(app):
    a, ah = member(app)
    a.put('/api/dashboard-layout', json=layout(hidden=['finance']), headers=ah)
    child, _, entry = create_space(app, 'layout-family')
    assert child.get(entry['entry']).status_code == 303
    assert child.post('/api/login', json={'username': 'member1', 'password': 'second-home-password-one'}).status_code == 200
    assert child.get('/api/dashboard-layout').json == layout()
    header = {'X-CSRF-Token': child.get('/api/me').json['csrf']}
    child.put('/api/dashboard-layout', json=layout(hidden=['trips']), headers=header)
    assert a.get('/api/dashboard-layout').json['hidden'] == ['finance']
    assert child.get('/api/dashboard-layout').json['hidden'] == ['trips']


def test_layout_concurrent_first_save_has_one_winner(app):
    a, ah = member(app)
    b, bh = member(app)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(c.put, '/api/dashboard-layout', json=layout(hidden=[key]), headers=h)
                   for c, h, key in [(a, ah, 'finance'), (b, bh, 'trips')]]
        results = [f.result() for f in futures]
    assert sorted(r.status_code for r in results) == [200, 409]
    assert a.get('/api/dashboard-layout').json['revision'] == 1
