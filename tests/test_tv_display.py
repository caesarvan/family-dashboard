"""Per-screen layout persistence, optimistic concurrency and data boundaries."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import copy
import json
import sqlite3
import threading
import time

import pytest
from flask import g, request

from app import create_app
from test_app import app, member
from test_household_spaces import create_space
from tv_display import default_layout


def database(app):
    return Path(app.config['DATA_DIR']) / 'household.sqlite3'


def paired(app, owner, headers, name='测试电视'):
    tv = app.test_client()
    pair = tv.post('/api/pair/start', json={}).json
    response = owner.post('/api/pair/approve', json={'code': pair['code'], 'name': name}, headers=headers)
    assert response.status_code == 200
    assert tv.post('/api/pair/poll', json={'secret': pair['secret']}).json['approved']
    row = next(row for row in owner.get('/api/devices').json if row['name'] == name)
    return tv, row


def customized(**fields):
    return {**default_layout(), 'order': ['trips', 'calendar', 'tasks', 'finance', 'shopping'],
            'hidden': ['shopping'], 'theme': 'ocean', 'density': 'compact', **fields}


def test_two_tvs_member_layout_and_restart_are_independent(app):
    owner, headers = member(app)
    partner, partner_headers = member(app, 2)
    tv1, d1 = paired(app, owner, headers, '家一')
    tv2, d2 = paired(app, owner, headers, '家二')
    assert d1['layout'] == d2['layout'] == default_layout()
    member_layout = owner.get('/api/dashboard-layout').json
    personal_preferences = owner.get('/api/preferences').json
    before_revision = tv1.get('/api/state').json['revision']
    value = customized()
    response = partner.patch('/api/devices/' + d1['id'], json={
        'revision': d1['revision'], 'layout': value, 'focus': 'member2', 'calendarView': 'week'}, headers=partner_headers)
    assert response.status_code == 200 and response.json == {'ok': True}
    assert tv1.get('/api/state').json['display'] == {'focus': 'member2', 'calendarView': 'week', 'layout': value}
    assert tv2.get('/api/state').json['display']['layout'] == default_layout()
    assert tv1.get('/api/state').json['revision'] == before_revision + 1
    assert owner.get('/api/dashboard-layout').json == member_layout
    assert owner.get('/api/preferences').json == personal_preferences
    restored = create_app(dict(app.config))
    owner2, _ = member(restored)
    d1_after = next(row for row in owner2.get('/api/devices').json if row['id'] == d1['id'])
    assert d1_after['layout'] == value and d1_after['revision'] == d1['revision'] + 1


def test_older_client_can_edit_name_without_erasing_layout(app):
    owner, headers = member(app)
    tv, device = paired(app, owner, headers)
    path = '/api/devices/' + device['id']
    layout = customized()
    assert owner.patch(path, json={'revision': 1, 'layout': layout}, headers=headers).status_code == 200
    with closing(sqlite3.connect(database(app))) as con:
        stored = con.execute('SELECT display_layout FROM devices WHERE id=?', (device['id'],)).fetchone()[0]
    assert owner.patch(path, json={'revision': 2, 'name': '新的电视名称', 'calendarView': 'around'}, headers=headers).status_code == 200
    assert tv.get('/api/state').json['display']['layout'] == layout
    with closing(sqlite3.connect(database(app))) as con:
        assert con.execute('SELECT display_layout FROM devices WHERE id=?', (device['id'],)).fetchone()[0] == stored


BAD_LAYOUTS = [
    None, [], '', {}, {**default_layout(), 'unexpected': 1},
    {**default_layout(), 'order': []}, {**default_layout(), 'order': ['calendar'] * 5},
    {**default_layout(), 'order': ['calendar', 'finance', 'tasks', 'shopping', 'private']},
    {**default_layout(), 'order': ['calendar', 'finance', 'tasks', 'shopping', {}]},
    {**default_layout(), 'hidden': ['calendar'] * 2},
    {**default_layout(), 'hidden': list(default_layout()['order'])},
    {**default_layout(), 'hidden': ['private-finance']},
    {**default_layout(), 'hidden': [True]}, {**default_layout(), 'hidden': 'finance'},
    {**default_layout(), 'theme': 'url(javascript:alert(1))'},
    {**default_layout(), 'theme': []}, {**default_layout(), 'density': False},
    {**default_layout(), 'density': 'small'},
]


@pytest.mark.parametrize('layout', BAD_LAYOUTS)
def test_invalid_layout_rejected_without_partial_change(app, layout):
    owner, headers = member(app)
    tv, device = paired(app, owner, headers)
    before = owner.get('/api/devices').json
    rev = tv.get('/api/state').json['revision']
    response = owner.patch('/api/devices/' + device['id'], json={
        'revision': 1, 'name': 'must-not-save', 'layout': copy.deepcopy(layout)}, headers=headers)
    assert response.status_code == 400
    assert owner.get('/api/devices').json == before
    assert tv.get('/api/state').json['revision'] == rev


@pytest.mark.parametrize('revision', [None, True, False, '1', 1.0, 0, -1])
def test_invalid_revision_cannot_bypass_conflict(app, revision):
    owner, headers = member(app)
    _, device = paired(app, owner, headers)
    assert owner.patch('/api/devices/' + device['id'], json={
        'revision': revision, 'layout': customized()}, headers=headers).status_code == 400
    assert owner.get('/api/devices').json[0]['revision'] == 1


@pytest.mark.parametrize('count', [1, 2, 3, 4, 5])
def test_one_through_five_visible_cards_supported(app, count):
    owner, headers = member(app)
    tv, device = paired(app, owner, headers)
    layout = customized(hidden=list(default_layout()['order'])[count:])
    assert owner.patch('/api/devices/' + device['id'], json={'revision': 1, 'layout': layout}, headers=headers).status_code == 200
    shown = tv.get('/api/state').json['display']['layout']
    assert len(set(shown['order']) - set(shown['hidden'])) == count


def test_concurrent_members_only_one_complete_layout_wins(app):
    first, h1 = member(app)
    second, h2 = member(app, 2)
    tv, device = paired(app, first, h1)
    barrier = threading.Barrier(2)
    values = [customized(theme='light'), customized(theme='ocean')]
    revision = tv.get('/api/state').json['revision']

    def save(client, headers, value):
        barrier.wait(timeout=10)
        return client.patch('/api/devices/' + device['id'], json={
            'revision': 1, 'layout': value, 'name': value['theme']}, headers=headers).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(save, first, h1, values[0]), pool.submit(save, second, h2, values[1])]
        outcomes = [future.result(timeout=20) for future in futures]
    assert sorted(outcomes) == [200, 409]
    device_after = first.get('/api/devices').json[0]
    winner = values[outcomes.index(200)]
    assert device_after['layout'] == winner and device_after['name'] == winner['theme']
    assert device_after['revision'] == 2
    assert tv.get('/api/state').json['revision'] == revision + 1


def test_tv_never_writes_and_hidden_finance_does_not_grant_private_access(app):
    owner, headers = member(app)
    tv, device = paired(app, owner, headers)
    path = '/api/devices/' + device['id']
    assert owner.patch(path, json={'revision': 1, 'layout': customized(hidden=['finance'])}, headers=headers).status_code == 200
    response = tv.patch(path, json={'revision': 2, 'layout': default_layout()}, headers=headers)
    assert response.status_code == 403
    assert owner.patch(path, json={'revision': 2, 'layout': default_layout()}).status_code == 403
    assert owner.patch(path, json={'revision': 2, 'layout': default_layout()}, headers={**headers, 'Origin': 'https://untrusted.example'}).status_code == 403
    assert tv.get('/api/private-finance').status_code == 403
    assert tv.get('/api/finance-hub/overview').status_code == 403
    # Hiding is presentation, not another authorization boundary.
    assert 'finance' in tv.get('/api/state').json
    assert set(owner.get('/api/devices').json[0]) == {'id', 'name', 'focus', 'calendarView', 'revision', 'created_at', 'layout'}


def test_revoked_expired_and_unapproved_screens_cannot_be_changed(app):
    owner, headers = member(app)
    tv, device = paired(app, owner, headers)
    path = '/api/devices/' + device['id']
    assert owner.delete(path, json={}, headers=headers).status_code == 200
    assert owner.patch(path, json={'revision': 1, 'layout': customized()}, headers=headers).status_code == 404
    assert tv.get('/api/state').status_code == 401
    _, device = paired(app, owner, headers, 'expired')
    with closing(sqlite3.connect(database(app))) as con:
        con.execute('UPDATE devices SET expires=? WHERE id=?', (time.time() - 1, device['id']))
        con.commit()
    assert owner.patch('/api/devices/' + device['id'], json={'revision': 1, 'layout': customized()}, headers=headers).status_code == 404
    pending = app.test_client().post('/api/pair/start', json={}).json
    with closing(sqlite3.connect(database(app))) as con:
        uid = con.execute('SELECT id FROM devices WHERE code=?', (pending['code'],)).fetchone()[0]
    assert owner.patch('/api/devices/' + uid, json={'revision': 1, 'layout': customized()}, headers=headers).status_code == 404


@pytest.mark.parametrize('raw', ['{}', 'not-json', 'null', '[]', '{"theme":"light"}'])
def test_invalid_legacy_layout_reads_default_without_database_rewrite(app, raw):
    owner, headers = member(app)
    tv, device = paired(app, owner, headers)
    with closing(sqlite3.connect(database(app))) as con:
        con.execute('UPDATE devices SET display_layout=? WHERE id=?', (raw, device['id']))
        con.commit()
    assert tv.get('/api/state').json['display']['layout'] == default_layout()
    assert owner.get('/api/devices').json[0]['layout'] == default_layout()
    with closing(sqlite3.connect(database(app))) as con:
        assert con.execute('SELECT display_layout,revision FROM devices WHERE id=?', (device['id'],)).fetchone() == (raw, 1)


def test_existing_devices_migrate_once_without_repairing_or_resetting_identity(app):
    owner, headers = member(app)
    _, device = paired(app, owner, headers)
    with closing(sqlite3.connect(database(app))) as con:
        con.row_factory = sqlite3.Row
        con.execute('ALTER TABLE devices DROP COLUMN display_layout')
        original = dict(con.execute('SELECT * FROM devices WHERE id=?', (device['id'],)).fetchone())
        users = con.execute('SELECT id,password,auth_version FROM users ORDER BY id').fetchall()
        con.commit()
    barrier = threading.Barrier(2)

    def initialize():
        barrier.wait(timeout=10)
        return create_app(dict(app.config))

    with ThreadPoolExecutor(max_workers=2) as pool:
        instances = [pool.submit(initialize) for _ in range(2)]
        for future in instances:
            future.result(timeout=30)
    with closing(sqlite3.connect(database(app))) as con:
        con.row_factory = sqlite3.Row
        migrated = dict(con.execute('SELECT * FROM devices WHERE id=?', (device['id'],)).fetchone())
        assert migrated.pop('display_layout') == '{}'
        assert migrated == original
        assert [tuple(row) for row in con.execute('SELECT id,password,auth_version FROM users ORDER BY id')] == [tuple(row) for row in users]
        assert con.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def test_routed_households_with_identical_device_ids_remain_isolated(app):
    owner, headers = member(app)
    tv1, device = paired(app, owner, headers, 'original-tv')
    child_owner, _, created = create_space(app, 'tv-layout-household')
    child_owner.get(created['entry'])
    assert child_owner.post('/api/login', json={
        'username': 'member1', 'password': 'second-home-password-one'}).status_code == 200
    ch = {'X-CSRF-Token': child_owner.get('/api/me').json['csrf']}
    tv2 = app.test_client()
    tv2.get(created['entry'])
    pair = tv2.post('/api/pair/start', json={}).json
    assert child_owner.post('/api/pair/approve', json={'code': pair['code'], 'name': 'child-tv'}, headers=ch).status_code == 200
    assert tv2.post('/api/pair/poll', json={'secret': pair['secret']}).json['approved']
    child_device = child_owner.get('/api/devices').json[0]
    assert child_owner.patch('/api/devices/' + device['id'], json={
        'revision': 1, 'layout': customized()}, headers=ch).status_code == 404
    platform = app.extensions['household_platform']
    household = next(h for h in platform.households() if h['id'] != 'default')
    child_app = platform.child(household)
    with closing(sqlite3.connect(database(child_app))) as con:
        con.execute('UPDATE devices SET id=? WHERE id=?', (device['id'], child_device['id']))
        con.commit()
    assert child_owner.patch('/api/devices/' + device['id'], json={
        'revision': 1, 'layout': customized()}, headers=ch).status_code == 200
    assert tv2.get('/api/state').json['display']['layout'] == customized()
    assert tv1.get('/api/state').json['display']['layout'] == default_layout()
    assert owner.get('/api/devices').json[0]['revision'] == 1


@pytest.mark.parametrize('revoke', [False, True])
def test_state_rechecks_display_after_authentication_hook(app, revoke):
    owner, headers = member(app)
    tv, device = paired(app, owner, headers)
    initial = tv.get('/api/state').json['revision']
    changed = customized()
    pending = [True]

    def update_between_authentication_and_state():
        if request.path != '/api/state' or g.actor['role'] != 'tv' or not pending:
            return
        pending.pop()
        with closing(sqlite3.connect(database(app))) as con:
            if revoke:
                con.execute('DELETE FROM devices WHERE id=?', (device['id'],))
            else:
                con.execute('UPDATE devices SET display_layout=?,focus=?,calendar_view=?,revision=revision+1 WHERE id=?',
                            (json.dumps(changed), 'member2', 'around', device['id']))
            con.execute("UPDATE settings SET revision=revision+1 WHERE id='meta'")
            con.commit()

    app.before_request_funcs.setdefault(None, []).append(update_between_authentication_and_state)
    response = tv.get('/api/state')
    if revoke:
        assert response.status_code == 401
        assert 'finance' not in response.json
    else:
        assert response.status_code == 200
        assert response.json['display'] == {'layout': changed, 'focus': 'member2', 'calendarView': 'around'}
        assert response.json['revision'] == initial + 1
        assert tv.get('/api/state').json['display'] == response.json['display']
