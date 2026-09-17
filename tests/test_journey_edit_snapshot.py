"""Editing snapshots use actual Flask routes and separate WAL connections."""
from contextlib import closing
from copy import deepcopy
import json
import sqlite3

from flask import g, request
from itsdangerous import URLSafeTimedSerializer
import pytest

from test_app import app, member
from test_device_sessions import database, install_connection, invalidate
from test_journey_workflows import apply, create, detail, plan, preview
from test_member_sessions import legacy


def snapshot(application):
    with closing(sqlite3.connect(database(application))) as con:
        return {table: con.execute('SELECT * FROM ' + table + ' ORDER BY rowid').fetchall()
                for table in ('entities', 'journey_workflows', 'journey_links', 'journey_actions', 'audit', 'settings')}


def entities(value):
    return {item['id']: item['revision'] for item in
            [value['trip'], *value['tasks'], *value['shopping'], *value['events']]}


def payload(value):
    return {'journeyId': value['id'], 'revision': value['revision'],
            'expectedEntities': entities(value), 'plan': deepcopy(value['plan'])}


@pytest.fixture
def saved(app):
    client, headers = member(app)
    result = create(client, headers)
    return client, headers, detail(client, result['id'])


def post(client, headers, value):
    return client.post('/api/journeys/preview', json=value, headers=headers)


def stale(response):
    assert response.status_code == 409, response.json
    assert set(response.json) == {'error', 'code'}
    assert response.json['code'] == 'stale_edit_source'


def test_complete_snapshot_is_read_only_until_explicit_apply_and_legacy_client_works(app, saved):
    client, headers, value = saved
    before = snapshot(app)
    assert client.get('/api/journeys/templates').json['capabilities'] == {'editSourceSnapshot': True}
    candidate = payload(value)
    candidate['plan']['title'] = 'An explicitly confirmed synthetic edit'
    result = post(client, headers, candidate)
    assert result.status_code == 200 and result.json['canApply']
    assert snapshot(app) == before
    committed = apply(client, headers, result.json, 'edit-snapshot-one')
    assert committed.status_code == 200
    current = detail(client, value['id'])
    assert current['trip']['title'] == candidate['plan']['title']
    old_client = payload(current)
    old_client.pop('expectedEntities')
    before = snapshot(app)
    assert post(client, headers, old_client).status_code == 200
    assert snapshot(app) == before


@pytest.mark.parametrize('kind', ['trips', 'tasks', 'shopping', 'events'])
def test_independent_entity_http_edit_rejects_old_source_without_workflow_revision_change(app, saved, kind):
    client, headers, value = saved
    row = value['trip'] if kind == 'trips' else value[kind][0]
    partner, partner_headers = member(app, 2)
    changed = partner.patch('/api/items/' + kind + '/' + row['id'],
                            json={'revision': row['revision'], 'title': 'Separate current edit'}, headers=partner_headers)
    assert changed.status_code == 200, changed.json
    assert detail(client, value['id'])['revision'] == value['revision']
    before = snapshot(app)
    stale(post(client, headers, payload(value)))
    assert snapshot(app) == before


@pytest.mark.parametrize('kind', ['trips', 'tasks', 'shopping', 'events'])
def test_deleted_entity_or_workflow_rejects_old_source(app, saved, kind):
    client, headers, value = saved
    row = value['trip'] if kind == 'trips' else value[kind][0]
    removed = client.delete('/api/items/' + kind + '/' + row['id'], json={'revision': row['revision']}, headers=headers)
    assert removed.status_code == 200, removed.json
    before = snapshot(app)
    stale(post(client, headers, payload(value)))
    assert snapshot(app) == before


@pytest.mark.parametrize('change', ['missing', 'extra', 'empty', 'new_link', 'removed_link', 'workflow'])
def test_exact_complete_link_set_and_workflow_revision_required(app, saved, change):
    client, headers, value = saved
    candidate = payload(value)
    if change == 'missing':
        candidate['expectedEntities'].pop(value['tasks'][0]['id'])
    elif change == 'extra':
        candidate['expectedEntities']['f' * 24] = 1
    elif change == 'empty':
        candidate['expectedEntities'] = {}
    else:
        with closing(sqlite3.connect(database(app))) as con:
            con.execute('PRAGMA foreign_keys=ON')
            if change == 'new_link':
                source = value['tasks'][0]
                con.execute('INSERT INTO entities(id,kind,data,updated_at) VALUES(?,?,?,?)',
                            ('e' * 24, 'tasks', json.dumps(source), '2026-09-17'))
                con.execute('INSERT INTO journey_links VALUES(?,?,?,?)', (value['id'], 'task:additional', 'e' * 24, 'tasks'))
            elif change == 'removed_link':
                con.execute('DELETE FROM journey_links WHERE entity_id=?', (value['tasks'][0]['id'],))
            else:
                con.execute('UPDATE journey_workflows SET revision=revision+1 WHERE id=?', (value['id'],))
            con.commit()
    before = snapshot(app)
    stale(post(client, headers, candidate))
    assert snapshot(app) == before


@pytest.mark.parametrize('invalid', [None, [], True, {'bad-id': 1}, {'A' * 24: 1},
                                  {'f' * 24: True}, {'f' * 24: 1.0}, {'f' * 24: '1'},
                                  {'f' * 24: 0}, {'f' * 24: -1}, {'f' * 24: 9007199254740992},
                                  {format(i, '024x'): 1 for i in range(303)}])
def test_malformed_entity_map_is_400_and_never_writes(app, saved, invalid):
    client, headers, value = saved
    candidate = payload(value)
    candidate['expectedEntities'] = invalid
    before = snapshot(app)
    response = post(client, headers, candidate)
    assert response.status_code == 400 and 'expectedEntities' in response.json['error']
    assert snapshot(app) == before


@pytest.mark.parametrize('uid', [None, '', True, 'not-a-journey'])
def test_entity_map_only_accepted_for_existing_journey_id(app, saved, uid):
    client, headers, value = saved
    candidate = payload(value)
    candidate['journeyId'] = uid
    before = snapshot(app)
    assert post(client, headers, candidate).status_code == 400
    assert snapshot(app) == before


@pytest.mark.parametrize('kind', ['trips', 'tasks', 'shopping', 'events'])
def test_writer_during_normalization_cannot_change_signed_source_or_be_overwritten(app, saved, kind):
    client, headers, value = saved
    row = value['trip'] if kind == 'trips' else value[kind][0]
    observed = []

    def write_while_normalizing(sql):
        if sql == 'SELECT id FROM users ORDER BY id' and not observed:
            with closing(sqlite3.connect(database(app))) as other:
                assert other.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
                current = json.loads(other.execute('SELECT data FROM entities WHERE id=?', (row['id'],)).fetchone()[0])
                current['title'] = 'Concurrent value must survive'
                other.execute('UPDATE entities SET data=?,revision=revision+1 WHERE id=?', (json.dumps(current), row['id']))
                other.commit()
            observed.append(True)

    install_connection(app, '/api/journeys/preview', 'POST', after=write_while_normalizing)
    response = post(client, headers, payload(value))
    assert observed == [True] and response.status_code == 200, response.json
    claims = URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='household-journey-preview-v1').loads(response.json['previewToken'])
    assert claims['entities'] == entities(value)
    before = snapshot(app)
    assert apply(client, headers, response.json, 'concurrent-edit-source').status_code == 409
    assert snapshot(app) == before
    with closing(sqlite3.connect(database(app))) as con:
        assert json.loads(con.execute('SELECT data FROM entities WHERE id=?', (row['id'],)).fetchone()[0])['title'] == 'Concurrent value must survive'


def test_detail_reads_workflow_and_entities_from_one_snapshot(app, saved):
    client, _, value = saved
    observed = []

    def update_between_reads(sql):
        if sql == 'SELECT * FROM journey_workflows WHERE id=?' and not observed:
            with closing(sqlite3.connect(database(app))) as other:
                new_plan = deepcopy(value['plan'])
                new_plan['title'] = 'New atomic title'
                trip = {key: item for key, item in value['trip'].items() if key not in ('id', 'revision', 'workflowKey')}
                trip['title'] = new_plan['title']
                other.execute('UPDATE journey_workflows SET plan=?,revision=revision+1 WHERE id=?', (json.dumps(new_plan), value['id']))
                other.execute('UPDATE entities SET data=?,revision=revision+1 WHERE id=?', (json.dumps(trip), value['tripId']))
                other.commit()
            observed.append(True)

    install_connection(app, '/api/journeys/' + value['id'], 'GET', after=update_between_reads)
    first = detail(client, value['id'])
    assert observed == [True]
    assert first == value
    latest = detail(client, value['id'])
    assert latest['plan']['title'] == latest['trip']['title'] == 'New atomic title'
    assert latest['revision'] == value['revision'] + 1


@pytest.mark.parametrize('operation', ['detail', 'preview', 'templates'])
@pytest.mark.parametrize('revocation', ['session', 'expired', 'auth_version'])
def test_read_releases_snapshot_then_rejects_real_session_revocation(app, saved, operation, revocation):
    client, headers, value = saved
    endpoint = '/api/journeys/' + (value['id'] if operation == 'detail' else operation)
    method = 'POST' if operation == 'preview' else 'GET'
    before, observed = snapshot(app), []
    target = {'detail': 'SELECT l.item_key', 'preview': 'SELECT id FROM users ORDER BY id', 'templates': 'SELECT s.*'}[operation]

    def revoke_after_read(sql):
        if sql.lstrip().startswith(target) and not observed:
            with closing(sqlite3.connect(database(app))) as other:
                invalidate(other, revocation)
                other.commit()
            observed.append(revocation)

    install_connection(app, endpoint, method, after=revoke_after_read)
    response = client.open(endpoint, method=method, json=payload(value) if method == 'POST' else None, headers=headers)
    assert observed == [revocation]
    assert response.status_code == 401 and set(response.json) == {'error'}
    assert snapshot(app) == before


@pytest.mark.parametrize('operation', ['detail', 'preview', 'templates'])
def test_actual_captured_session_must_match(app, saved, operation):
    client, headers, value = saved
    endpoint = '/api/journeys/' + (value['id'] if operation == 'detail' else operation)

    def mismatch():
        if request.path == endpoint:
            g.member_session['id'] = '0' * 32

    app.before_request_funcs[None].append(mismatch)
    before = snapshot(app)
    response = client.open(endpoint, method='POST' if operation == 'preview' else 'GET',
                           json=payload(value) if operation == 'preview' else None, headers=headers)
    assert response.status_code == 401
    assert snapshot(app) == before


@pytest.mark.parametrize('operation', ['detail', 'preview', 'templates'])
def test_legacy_cookie_implicit_update_does_not_break_read_transaction(app, saved, monkeypatch, operation):
    _, _, value = saved
    client, raw, cookie = legacy(app, app.extensions['member_sessions'], monkeypatch)
    headers = {'X-CSRF-Token': cookie['csrf']}
    endpoint = '/api/journeys/' + (value['id'] if operation == 'detail' else operation)
    before = snapshot(app)
    response = client.open(endpoint, method='POST' if operation == 'preview' else 'GET',
                           json=payload(value) if operation == 'preview' else None, headers=headers)
    assert response.status_code == 200, response.json
    assert client.get_cookie('session').value == raw
    assert detail(client, value['id']) == value
    assert snapshot(app) == before


def test_tv_retains_read_only_detail_but_cannot_preview_or_read_templates(app, saved):
    client, headers, value = saved
    tv = app.test_client()
    pair = tv.post('/api/pair/start', json={}).json
    assert client.post('/api/pair/approve', json={'code': pair['code'], 'name': 'Synthetic TV'}, headers=headers).status_code == 200
    assert tv.post('/api/pair/poll', json={'secret': pair['secret']}).json['approved']
    before = snapshot(app)
    assert tv.get('/api/journeys/' + value['id']).status_code == 200
    assert tv.get('/api/journeys/templates').status_code == 403
    assert post(tv, headers, payload(value)).status_code == 403
    assert snapshot(app) == before
