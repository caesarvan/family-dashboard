"""Real app registration, sessions, SQLite and reschedule; only provider I/O faked."""
from contextlib import closing, contextmanager
from copy import deepcopy
import json
from pathlib import Path
import socket
import sqlite3
import time
from uuid import uuid4

from flask import g, request
from itsdangerous import TimestampSigner, URLSafeTimedSerializer
import pytest

import app as server
import assistant_trip_change_api as api
import home_assistant
from test_app import member
from test_device_sessions import install_connection, invalidate
from test_household_spaces import create_space
from test_journey_reschedule import create, plan, snapshot as journey_snapshot
from test_journey_workflows import apply, detail


URL = '/api/assistant/trip-change'
PROMPT = '把东京旅行推迟三天'


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError('Only synthetic provider functions are allowed')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket, 'create_connection', deny)


@pytest.fixture
def app(tmp_path):
    application = server.create_app({'TESTING': True, 'DATA_DIR': str(tmp_path / 'data'),
        'SECRET_KEY': 'synthetic-trip-intent-key', 'SESSION_COOKIE_SECURE': False,
        'PUBLIC_ORIGIN': 'http://localhost', 'MEMBER1_PASSWORD': 'testing-password-one',
        'MEMBER2_PASSWORD': 'testing-password-two', 'ASSISTANT_PROVIDER': 'openai',
        'OPENAI_API_KEY': '', 'OPENAI_MODEL': '', 'NVIDIA_API_KEY': '', 'NVIDIA_MODEL': '',
        'MICROSOFT_CLIENT_ID': '', 'MICROSOFT_CLIENT_SECRET': '',
        'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': ''})
    routes = [rule for rule in application.url_map.iter_rules() if rule.rule == URL]
    assert len(routes) == 1
    assert routes[0].endpoint == 'assistant_trip_change'
    assert routes[0].methods == {'POST', 'OPTIONS'}
    assert application.view_functions[routes[0].endpoint].__module__ == 'assistant_trip_change_api'
    return application


@contextmanager
def database(app):
    with closing(sqlite3.connect(Path(app.config['DATA_DIR']) / 'household.sqlite3', timeout=5)) as con:
        with con:
            yield con


def domain_snapshot(app):
    with database(app) as con:
        tables = [row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        excluded = {'users', 'member_sessions', 'member_session_browsers', 'attempts'}
        return {table: sorted(con.execute('SELECT * FROM "' + table + '"').fetchall(), key=repr)
                for table in tables if table not in excluded}


def trip(client, headers, title='东京旅行'):
    return create(client, headers, plan(title=title))


def submit(client, headers, **changes):
    return client.post(URL, json={'prompt': PROMPT, **changes}, headers=headers)


def choose(client, headers, value, ref=None):
    return client.post(URL, json={'selectionToken': value['selectionToken'],
        'selectedRef': ref or value['candidates'][0]['ref']}, headers=headers)


def advisory(payload, **changes):
    context = json.loads(payload['input'])
    return {'intent': 'reschedule_existing', 'targetText': '东京',
            'change': {'kind': 'shift_days', 'days': 3, 'startDate': None, 'monthDay': None},
            'candidateRefs': [row['ref'] for row in context['candidates']], **changes}


def model(app, monkeypatch, invoke=None):
    app.config.update(OPENAI_API_KEY='synthetic-provider-key', OPENAI_MODEL='synthetic-model')
    calls = []
    def fake(config, payload):
        assert not g.db.in_transaction
        calls.append(deepcopy(payload))
        return invoke(config, payload) if invoke else advisory(payload)
    monkeypatch.setattr(home_assistant, '_model_json', fake)
    return calls


def change_trip(app, journey, field='start', value='2028-03-03'):
    with database(app) as con:
        row = con.execute('SELECT data FROM entities WHERE id=?', (journey['tripId'],)).fetchone()
        data = json.loads(row[0]); data[field] = value
        con.execute('UPDATE entities SET data=?,revision=revision+1 WHERE id=?',
                    (json.dumps(data, ensure_ascii=False), journey['tripId']))


def test_local_ready_uses_live_trip_source_and_never_writes(app):
    client, headers = member(app)
    journey = trip(client, headers)
    change_trip(app, journey)
    before = domain_snapshot(app)
    result = submit(client, headers)
    assert result.status_code == 200, result.json
    value = result.json
    assert value['mode'] == 'local' and value['status'] == 'ready'
    assert value['source']['start'] == '2028-03-03' and value['source']['tripRevision'] == 2
    assert value['draft'] == {'journeyId': journey['id'], 'tripId': journey['tripId'],
        'revision': journey['revision'], 'start': '2028-03-06', 'end': '2028-03-07', 'calendarDays': True}
    assert len(value['source']['sourceVersion']) == 64 and value['requiresPreview'] is True
    assert value['selectionToken'] is None and value['selectionExpiresIn'] is None
    assert result.headers['Cache-Control'] == 'no-store'
    assert not {'previewToken', 'snapshotToken', 'selectedKeys', 'actions', 'canApply'} & value.keys()
    assert domain_snapshot(app) == before


def test_suggestion_enters_real_snapshot_preview_apply_and_receipt_recovery(app):
    client, headers = member(app)
    journey = trip(client, headers)
    before = journey_snapshot(app)
    suggested = submit(client, headers).json
    current = client.get('/api/journeys/' + journey['id'] + '/reschedule').json
    assert (current['journeyId'], current['revision'], current['start'], current['end']) == (
        suggested['source']['journeyId'], suggested['source']['revision'],
        suggested['source']['start'], suggested['source']['end'])
    proposed = client.post('/api/journeys/' + journey['id'] + '/reschedule-preview', json={
        'snapshotToken': current['snapshotToken'], 'start': suggested['draft']['start'],
        'end': suggested['draft']['end'], 'selectedKeys': ['task:pack'], 'timeOverrides': {}}, headers=headers)
    assert proposed.status_code == 200 and proposed.json['canApply'], proposed.json
    assert journey_snapshot(app) == before
    key = uuid4().hex
    saved = apply(client, headers, proposed.json, key)
    assert saved.status_code == 200 and saved.json['operation'] == 'reschedule', saved.json
    after = journey_snapshot(app)
    repeated = apply(client, headers, proposed.json, key)
    assert repeated.status_code == 200 and journey_snapshot(app) == after
    recovered = client.get('/api/journeys/operations/' + key)
    assert recovered.status_code == 200 and recovered.json['result']['id'] == journey['id']
    updated = detail(client, journey['id'])
    assert updated['trip']['start'] == '2028-03-05'
    assert next(row for row in updated['tasks'] if row['workflowKey'] == 'task:pack')['due'] == '2028-03-04'
    assert updated['shopping'] == journey['shopping']
    assert {row['id'] for row in updated['tasks']} == {row['id'] for row in journey['tasks']}


def test_shared_household_trips_are_selectable_by_partner_but_ticket_is_session_bound(app):
    client, headers = member(app)
    one = trip(client, headers, '东京一旅行')
    trip(client, headers, '东京二旅行')
    original = submit(client, headers).json
    partner, ph = member(app, 2)
    visible = submit(partner, ph)
    assert visible.status_code == 200 and visible.json['status'] == 'choose_trip'
    assert one['id'] in {row['journeyId'] for row in visible.json['candidates']}
    assert choose(partner, ph, original).status_code == 403
    second_browser, sh = member(app)
    assert choose(second_browser, sh, original).status_code == 403
    selected = choose(client, headers, original)
    assert selected.status_code == 200 and selected.json['status'] == 'ready'


def test_model_context_is_minimal_and_selection_reuses_exact_advisory_without_network(app, monkeypatch):
    client, headers = member(app)
    trip(client, headers, '东京一旅行')
    trip(client, headers, '东京二旅行')
    client.post('/api/items/tasks', json={'title': 'SYNTHETIC_PRIVATE_TASK', 'note': 'PRIVATE_NOTE'}, headers=headers)
    calls = model(app, monkeypatch, lambda _config, payload: advisory(payload,
        candidateRefs=[json.loads(payload['input'])['candidates'][0]['ref']]))
    before = domain_snapshot(app)
    result = submit(client, headers, useModel=True)
    assert result.status_code == 200, result.json
    assert result.json['status'] == 'choose_trip' and result.json['mode'] == 'model'
    assert len(result.json['candidates']) == 2 and len(calls) == 1
    context = json.loads(calls[0]['input'])
    assert set(context) == {'request', 'candidates'}
    assert all(set(row) == {'ref', 'title', 'start', 'end', 'timeZones'} for row in context['candidates'])
    sent = json.dumps(calls, ensure_ascii=False)
    for forbidden in ('PRIVATE_NOTE', 'SYNTHETIC_PRIVATE_TASK', 'budget', '123450', 'member1', 'journeyId', 'tripId'):
        assert forbidden not in sent
    assert result.json['selectionExpiresIn'] == 600
    selected = choose(client, headers, result.json, result.json['candidates'][1]['ref'])
    assert selected.status_code == 200 and selected.json['mode'] == 'model', selected.json
    assert selected.json['selected']['ref'] == result.json['candidates'][1]['ref']
    assert len(calls) == 1 and domain_snapshot(app) == before


@pytest.mark.parametrize('prompt', ['搜索东京旅行推迟三天', '待办：旅行推迟三天', '采购：旅行推迟三天', '安排一次东京旅行'])
def test_non_change_routes_do_not_invoke_provider_even_when_requested(app, monkeypatch, prompt):
    client, headers = member(app)
    calls = model(app, monkeypatch)
    result = submit(client, headers, prompt=prompt, useModel=True)
    assert result.status_code == 200 and result.json['status'] == 'not_applicable', result.json
    assert calls == []


@pytest.mark.parametrize('payload', [{}, {'prompt': True}, {'prompt': ''}, {'prompt': 'x' * 2001},
    {'prompt': PROMPT, 'useModel': 1}, {'prompt': PROMPT, 'includeTripContext': True},
    {'prompt': PROMPT, 'candidates': []}, {'prompt': PROMPT, 'model_output': {}},
    {'selectionToken': 'bad'}, {'selectedRef': 'trip_' + 'a' * 24},
    {'selectionToken': 'bad', 'selectedRef': 'trip_' + 'a' * 24, 'prompt': PROMPT}])
def test_request_cannot_supply_authorized_candidates_or_model_output(app, payload):
    client, headers = member(app)
    before = domain_snapshot(app)
    result = client.post(URL, json=payload, headers=headers)
    assert result.status_code == 400, result.json
    assert domain_snapshot(app) == before


@pytest.mark.parametrize('change', ['entity', 'workflow', 'deleted', 'added'])
def test_selection_rejects_changed_catalogue_including_same_dates_new_revision(app, change):
    client, headers = member(app)
    journey = trip(client, headers, '东京一旅行')
    trip(client, headers, '东京二旅行')
    result = submit(client, headers).json
    if change == 'added':
        trip(client, headers, '另一个旅行')
    else:
        with database(app) as con:
            if change == 'entity':
                con.execute('UPDATE entities SET revision=revision+1 WHERE id=?', (journey['tripId'],))
            elif change == 'workflow':
                con.execute('UPDATE journey_workflows SET revision=revision+1 WHERE id=?', (journey['id'],))
            else:
                con.execute('DELETE FROM journey_workflows WHERE id=?', (journey['id'],))
    before = domain_snapshot(app)
    rejected = choose(client, headers, result)
    assert rejected.status_code == 409 and rejected.json['code'] == 'stale_source', rejected.json
    assert domain_snapshot(app) == before


def test_ticket_tamper_expiry_unknown_and_nonmatching_refs_are_rejected(app, monkeypatch):
    client, headers = member(app)
    trip(client, headers, '东京一旅行'); trip(client, headers, '东京二旅行')
    other = trip(client, headers, '大阪旅行')
    result = submit(client, headers).json
    assert choose(client, headers, {**result, 'selectionToken': 'x' + result['selectionToken']}).status_code == 400
    assert choose(client, headers, result, 'trip_' + '0' * 24).status_code == 409
    other_ref = 'trip_' + api.hashlib.sha256(other['id'].encode()).hexdigest()[:24]
    mismatch = choose(client, headers, result, other_ref)
    assert mismatch.status_code == 400 and mismatch.json['code'] == 'selection_mismatch'
    original_clock = TimestampSigner.get_timestamp
    monkeypatch.setattr(TimestampSigner, 'get_timestamp', lambda self: original_clock(self) + 601)
    expired = choose(client, headers, result)
    assert expired.status_code == 409 and expired.json['code'] == 'selection_expired'


@pytest.mark.parametrize('kind', ['session', 'expired', 'auth_version'])
@pytest.mark.parametrize('provider_fails', [False, True])
def test_revocation_during_provider_discards_success_or_failure(app, monkeypatch, kind, provider_fails):
    client, headers = member(app)
    trip(client, headers)
    def remote(_config, payload):
        with database(app) as con:
            con.execute('BEGIN IMMEDIATE')
            invalidate(con, kind)
        if provider_fails:
            raise home_assistant.ModelProviderError('AI 服务暂不可用', 503)
        return advisory(payload)
    calls = model(app, monkeypatch, remote)
    before = journey_snapshot(app)
    result = submit(client, headers, useModel=True)
    assert result.status_code == 401 and set(result.json) == {'error'}, result.json
    assert len(calls) == 1 and journey_snapshot(app) == before


def test_model_source_changed_during_network_has_no_stale_suggestion(app, monkeypatch):
    client, headers = member(app)
    journey = trip(client, headers)
    def remote(_config, payload):
        change_trip(app, journey)
        return advisory(payload)
    calls = model(app, monkeypatch, remote)
    result = submit(client, headers, useModel=True)
    assert len(calls) == 1 and result.status_code == 409 and result.json['code'] == 'stale_source', result.json
    assert 'draft' not in result.json


def test_read_revocation_after_projection_is_checked_in_fresh_snapshot(app):
    client, headers = member(app)
    trip(client, headers)
    entered = []
    def after(sql):
        if 'FROM journey_workflows w' in sql and not entered:
            with database(app) as con:
                invalidate(con)
            entered.append(True)
    install_connection(app, URL, 'POST', after=after)
    result = submit(client, headers)
    assert entered == [True] and result.status_code == 401, result.json
    assert set(result.json) == {'error'}


@pytest.mark.parametrize('kind', ['malformed', 'foreign_ref', 'unsafe_exception'])
def test_model_errors_are_bounded_and_never_write(app, monkeypatch, kind):
    client, headers = member(app)
    trip(client, headers)
    def remote(_config, payload):
        if kind == 'unsafe_exception':
            raise ValueError('SYNTHETIC_SECRET_EXCEPTION')
        if kind == 'malformed':
            return 'SYNTHETIC_SECRET_PROVIDER_BODY'
        return advisory(payload, candidateRefs=['trip_' + '0' * 24])
    model(app, monkeypatch, remote)
    before = domain_snapshot(app)
    result = submit(client, headers, useModel=True)
    assert result.status_code == 502 and result.json['code'] == 'invalid_model_output', result.json
    assert 'SYNTHETIC_SECRET' not in result.get_data(as_text=True)
    assert domain_snapshot(app) == before


def test_auth_csrf_origin_json_and_tv_boundaries(app):
    client, headers = member(app)
    trip(client, headers)
    before = domain_snapshot(app)
    assert submit(app.test_client(), headers).status_code == 401
    assert submit(client, {}).status_code == 403
    assert submit(client, {**headers, 'Origin': 'https://foreign.invalid'}).status_code == 403
    assert client.post(URL, data='{}', headers=headers).status_code == 415
    tv = app.test_client()
    pairing = tv.post('/api/pair/start', json={}).json
    assert client.post('/api/pair/approve', json={'code': pairing['code'], 'name': 'Synthetic TV'}, headers=headers).status_code == 200
    assert tv.post('/api/pair/poll', json={'secret': pairing['secret']}).json['approved']
    tv_before = domain_snapshot(app)
    assert submit(tv, headers).status_code == 403
    assert domain_snapshot(app) == tv_before


def test_new_household_reads_own_catalogue_and_rejects_other_household_ticket(app):
    client, headers = member(app)
    trip(client, headers, '东京一旅行'); trip(client, headers, '东京二旅行')
    ticket = submit(client, headers).json
    child, _, space = create_space(app)
    assert child.get(space['entry']).status_code == 303
    assert child.post('/api/login', json={'username': 'member1', 'password': 'second-home-password-one'}).status_code == 200
    ch = {'X-CSRF-Token': child.get('/api/me').json['csrf']}
    empty = submit(child, ch)
    assert empty.status_code == 200 and empty.json['status'] == 'not_found', empty.json
    assert empty.json['candidates'] == [] and choose(child, ch, ticket).status_code in (400, 403)
    assert submit(client, headers).json['status'] == 'choose_trip'


def test_shared_assistant_rate_budget_and_separate_selection_budget(app, monkeypatch):
    client, headers = member(app)
    trip(client, headers, '东京一旅行'); trip(client, headers, '东京二旅行')
    ticket = submit(client, headers).json
    calls = model(app, monkeypatch)
    with database(app) as con:
        con.execute("DELETE FROM attempts WHERE category='assistant_plan'")
        con.executemany('INSERT INTO attempts VALUES(?,?,?)', [('127.0.0.1', 'assistant_plan', time.time())] * 30)
    assert submit(client, headers, useModel=True).status_code == 429
    old = client.post('/api/assistant/plan', json={'prompt': '待办：合成事项'}, headers=headers)
    assert old.status_code == 429 and calls == []
    assert choose(client, headers, ticket).status_code == 200
    with database(app) as con:
        con.execute("DELETE FROM attempts WHERE category='assistant_trip_selection'")
        con.executemany('INSERT INTO attempts VALUES(?,?,?)', [('127.0.0.1', 'assistant_trip_selection', time.time())] * 60)
    assert choose(client, headers, ticket).status_code == 429


def test_unconfigured_provider_and_candidate_bound_fail_without_network(app, monkeypatch):
    client, headers = member(app)
    trip(client, headers)
    unavailable = submit(client, headers, useModel=True)
    assert unavailable.status_code == 503 and unavailable.json['code'] == 'model_unavailable'
    trip(client, headers, '东京二旅行')
    monkeypatch.setattr(api, 'MAX_CANDIDATES', 1)
    before = domain_snapshot(app)
    result = submit(client, headers)
    assert result.status_code == 400 and result.json['code'] == 'candidate_limit'
    assert domain_snapshot(app) == before


def test_signed_ticket_contains_no_candidates_budget_or_full_workflow(app):
    client, headers = member(app)
    trip(client, headers, '东京一旅行'); trip(client, headers, '东京二旅行')
    result = submit(client, headers).json
    claim = URLSafeTimedSerializer(app.secret_key, salt=api.SELECTION_SALT).loads(result['selectionToken'])
    assert set(claim) == {'v', 'actor', 'household', 'identity', 'prompt', 'catalogueDigest', 'model'}
    assert claim['model'] is None and claim['prompt'] == PROMPT
    assert len(claim['identity']) == 64 and len(claim['catalogueDigest']) == 64
    assert 'budget' not in json.dumps(claim) and 'candidates' not in claim
