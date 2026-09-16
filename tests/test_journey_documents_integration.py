"""Synthetic Flask/SQLite export, projection and documented recovery integration."""
from contextlib import contextmanager
from copy import deepcopy
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import socket
import sqlite3
import sys
import threading
import time
from types import SimpleNamespace
import uuid

import pytest
from werkzeug.serving import make_server, WSGIRequestHandler

from app import create_app
from test_app import app, member
from test_data_portability import unpack
from test_household_spaces import create_space
from test_platform_backup import backup_module
from test_calendar_publish import Remote as CalendarRemote
from test_task_publish import Remote as TaskRemote
import restore_rehearsal_fixture as recovery

PREFIX = '/api/journey-documents'
METADATA = set(recovery.DOCUMENT_METADATA)


@pytest.fixture(autouse=True)
def synthetic_network_only():
    audit = recovery.Audit('integration')
    with recovery.only_loopback(audit):
        yield
    assert audit.external == []


def journey(client, headers):
    plan = {'title': 'Synthetic journey', 'start': '2026-12-03', 'end': '2026-12-05',
            'international': False, 'memberIds': ['member1', 'member2'], 'budget': 0,
            'destinations': [{'key': 'city', 'country': 'Synthetic', 'city': 'City',
                              'arrival': '2026-12-03', 'departure': '2026-12-05'}],
            'checklist': [{'key': 'prepare', 'title': 'Synthetic preparation', 'due': '2026-12-02'}],
            'shopping': [], 'segments': []}
    preview = client.post('/api/journeys/preview', json={'plan': plan}, headers=headers)
    assert preview.status_code == 200, preview.json
    result = client.post('/api/journeys/apply', json={'previewToken': preview.json['previewToken'],
                         'idempotencyKey': uuid.uuid4().hex}, headers=headers)
    assert result.status_code == 201, result.json
    return result.json


def upload(client, headers, journey_id, title='DOCUMENT_PRIVATE_SENTINEL', visibility='private', image=False):
    raw = base64.b64decode(recovery.png(3).split(',', 1)[1]) if image else recovery.synthetic_pdf()
    payload = {'journeyId': journey_id, 'title': title, 'visibility': visibility,
               'requestId': uuid.uuid4().hex, 'file': {'name': 'synthetic.png' if image else 'synthetic.pdf',
               'mimeType': 'image/png' if image else 'application/pdf', 'dataBase64': base64.b64encode(raw).decode()}}
    result = client.post(PREFIX, json=payload, headers=headers)
    assert result.status_code == 201, result.json
    return result.json['document'], payload, raw


def update(client, headers, doc, **changes):
    value = {key: doc[key] for key in ('revision', 'title', 'visibility', 'segmentKey', 'journeyId')}
    result = client.patch(PREFIX + '/' + doc['id'], json={**value, **changes}, headers=headers)
    assert result.status_code == 200, result.json
    return result.json['document']


def db_path(app):
    return Path(app.config['DATA_DIR']) / 'household.sqlite3'


def tv_client(app, member_client, headers):
    client = app.test_client()
    pair = client.post('/api/pair/start', json={}).json
    assert member_client.post('/api/pair/approve', json={'code': pair['code']}, headers=headers).status_code == 200
    assert client.post('/api/pair/poll', json={'secret': pair['secret']}).json['approved']
    return client


@pytest.mark.parametrize('number', [1, 2])
def test_export_owner_once_partner_shared_explicit_and_metadata_only(app, number):
    clients = {n: member(app, n) for n in (1, 2)}
    c, h = clients[number]
    other, oh = clients[3 - number]
    trip = journey(c, h)
    own_private, key, raw = upload(c, h, trip['id'])
    own_shared, _, _ = upload(c, h, trip['id'], 'OWN_SHARED', 'shared', True)
    partner_private, _, _ = upload(other, oh, trip['id'], 'PARTNER_PRIVATE_SENTINEL')
    partner_shared, _, _ = upload(other, oh, trip['id'], 'PARTNER_SHARED_SENTINEL', 'shared')
    orphan, _, _ = upload(other, oh, trip['id'], 'PARTNER_ORPHAN_SENTINEL', 'shared')
    update(other, oh, orphan, journeyId=None, visibility='private', segmentKey='')
    own, files = unpack(c.post('/api/portability/export', json={}, headers=h))
    assert 'shared' not in own
    assert {x['id'] for x in own['personal']['journeyDocuments']} == {own_private['id'], own_shared['id']}
    shared, files = unpack(c.post('/api/portability/export', json={'includeShared': True}, headers=h))
    assert {x['id'] for x in shared['personal']['journeyDocuments']} == {own_private['id'], own_shared['id']}
    assert {x['id'] for x in shared['shared']['journeyDocuments']} == {partner_shared['id']}
    assert all(set(row) == METADATA for row in shared['personal']['journeyDocuments'] + shared['shared']['journeyDocuments'])
    assert shared['coverage']['journeyDocuments'] == 'metadata_only'
    assert set(files) == {'data.json', 'transactions.csv', 'investments.csv', 'README.txt', 'manifest.json'}
    joined = b''.join(files.values())
    for forbidden in (partner_private['title'], partner_private['id'], orphan['title'], key['requestId'],
                      hashlib.sha256(raw).hexdigest(), '/api/journey-documents/', base64.b64encode(raw).decode()):
        assert forbidden.encode() not in joined
    summary = c.get('/api/portability/summary').json
    assert summary['personal']['journeyDocuments'] == 2
    assert summary['shared']['journeyDocuments'] == 1


def test_export_never_reads_document_blob_request_or_digest_columns(app, monkeypatch):
    import data_portability
    c, h = member(app)
    trip = journey(c, h)
    upload(c, h, trip['id'])
    original = data_portability.exported_documents
    accesses = []
    def guarded(con, owner, include_shared=False):
        def authorize(action, table, column, database, context):
            if action == sqlite3.SQLITE_READ and table == 'journey_documents':
                accesses.append(column)
                if column in {'content', 'request_id', 'payload_digest'}:
                    return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        con.set_authorizer(authorize)
        try:
            return original(con, owner, include_shared)
        finally:
            con.set_authorizer(None)
    monkeypatch.setattr(data_portability, 'exported_documents', guarded)
    unpack(c.post('/api/portability/export', json={'includeShared': True}, headers=h))
    assert c.get('/api/portability/summary').status_code == 200
    assert accesses and not {'content', 'request_id', 'payload_digest'}.intersection(accesses)


def test_missing_document_table_exports_empty_without_initialization(app, monkeypatch):
    import data_portability
    c, h = member(app)
    with sqlite3.connect(db_path(app)) as con:
        con.execute('DROP TABLE journey_documents')
    def forbidden(*args, **kwargs):
        raise AssertionError('No document hook for a missing table')
    monkeypatch.setattr(data_portability, 'exported_documents', forbidden)
    value, _ = unpack(c.post('/api/portability/export', json={'includeShared': True}, headers=h))
    assert value['personal']['journeyDocuments'] == value['shared']['journeyDocuments'] == []
    assert c.get('/api/portability/summary').json['personal']['journeyDocuments'] == 0
    with sqlite3.connect(db_path(app)) as con:
        assert con.execute("SELECT name FROM sqlite_master WHERE name='journey_documents'").fetchall() == []


def test_deleted_trip_revokes_partner_access_owner_retains_blob_and_export(app):
    c, h = member(app)
    partner, ph = member(app, 2)
    trip = journey(c, h)
    doc, payload, raw = upload(c, h, trip['id'], visibility='shared')
    assert partner.get(PREFIX + '/' + doc['id'] + '/file').data == raw
    revision = c.get('/api/journeys/' + trip['id']).json['trip']['revision']
    assert c.delete('/api/items/trips/' + trip['tripId'], json={'revision': revision}, headers=h).status_code == 200
    assert partner.get(PREFIX + '/' + doc['id'] + '/file').status_code == 404
    current = next(x for x in c.get(PREFIX).json['documents'] if x['id'] == doc['id'])
    assert current['journeyId'] is None and current['unlinked'] and current['visibility'] == 'private'
    assert current['revision'] > doc['revision']
    assert c.get(PREFIX + '/' + doc['id'] + '/file').data == raw
    own, _ = unpack(c.post('/api/portability/export', json={'includeShared': True}, headers=h))
    other, _ = unpack(partner.post('/api/portability/export', json={'includeShared': True}, headers=ph))
    assert own['personal']['journeyDocuments'][0]['id'] == doc['id']
    assert other['shared']['journeyDocuments'] == []
    replay = c.post(PREFIX, json=payload, headers=h)
    assert replay.status_code in (200, 409)
    assert c.get('/api/journeys').json['journeys'] == []


@pytest.mark.parametrize('image', [False, True])
def test_individual_download_is_attachment_and_personal_zip_excludes_file_bytes(app, image):
    c, h = member(app)
    trip = journey(c, h)
    document, _, original = upload(c, h, trip['id'], image=image)
    downloaded = c.get(PREFIX + '/' + document['id'] + '/file')
    assert downloaded.status_code == 200
    assert downloaded.headers['Content-Disposition'].startswith('attachment;')
    assert 'no-store' in downloaded.headers['Cache-Control']
    assert 'sandbox' in downloaded.headers['Content-Security-Policy']
    assert downloaded.headers['X-Content-Type-Options'] == 'nosniff'
    assert downloaded.mimetype == ('image/jpeg' if image else 'application/pdf')
    assert len(downloaded.data) == document['bytes']
    assert downloaded.data != original if image else downloaded.data == original
    _, files = unpack(c.post('/api/portability/export', json={}, headers=h))
    assert all(downloaded.data not in body for body in files.values())


@pytest.mark.parametrize('number', [1, 2])
def test_two_household_member_and_tv_isolation(app, number):
    c, h = member(app, number)
    trip = journey(c, h)
    doc, _, _ = upload(c, h, trip['id'], 'ORIGINAL_HOUSEHOLD_DOCUMENT', 'shared')
    child, _, entry = create_space(app)
    assert child.get(entry['entry']).status_code == 303
    assert child.post('/api/login', json={'username': 'member' + str(number),
                 'password': 'second-home-password-' + ('one' if number == 1 else 'two')}).status_code == 200
    ch = {'X-CSRF-Token': child.get('/api/me').json['csrf']}
    child_trip = journey(child, ch)
    child_doc, _, _ = upload(child, ch, child_trip['id'], 'CHILD_HOUSEHOLD_DOCUMENT', 'shared')
    data, files = unpack(child.post('/api/portability/export', json={'includeShared': True}, headers=ch))
    assert [x['id'] for x in data['personal']['journeyDocuments']] == [child_doc['id']]
    assert b'ORIGINAL_HOUSEHOLD_DOCUMENT' not in b''.join(files.values())
    for reader, target in ((c, child_doc), (child, doc)):
        assert reader.get(PREFIX + '/' + target['id'] + '/file').status_code == 404
        assert reader.get(PREFIX, query_string={'journeyId': target['journeyId']}).status_code == 404
    tv = tv_client(app, c, h)
    for reader, denied in ((app.test_client(), 401), (tv, 403)):
        assert reader.get(PREFIX).status_code == denied
        assert reader.get(PREFIX + '/' + doc['id'] + '/file').status_code == denied
        assert reader.post('/api/portability/export', json={}).status_code == denied


@pytest.mark.parametrize('provider', ['microsoft', 'google'])
def test_documents_never_project_to_state_ics_cloud_or_model_context(app, monkeypatch, provider):
    import home_assistant
    c, h = member(app)
    trip = journey(c, h)
    doc, _, _ = upload(c, h, trip['id'], 'NEVER_PROJECT_DOCUMENT_METADATA', 'shared')
    private_doc, _, _ = upload(c, h, trip['id'], 'NEVER_PROJECT_PRIVATE_DOCUMENT')
    cal, task = CalendarRemote(), TaskRemote()
    def transport(method, url, token, body=None, headers=None):
        target = task if '/tasks' in url or '/lists' in url else cal
        return target.transport(method, url, token, body=body, headers=headers)
    app.config.update(CLOUD_TRANSPORT=transport, OPENAI_API_KEY='synthetic-only', OPENAI_MODEL='synthetic-only',
                      **{provider.upper() + '_CLIENT_ID': 'synthetic-client', provider.upper() + '_CLIENT_SECRET': 'synthetic-secret'})
    engine = app.extensions['cloud_accounts']
    scope = 'User.Read Calendars.ReadWrite Tasks.ReadWrite' if provider == 'microsoft' else 'https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/tasks'
    token = engine.encrypt({'access_token': 'synthetic', 'scope': scope, 'expires_at': time.time() + 3600})
    with engine.db() as con:
        con.execute('INSERT INTO cloud_accounts(id,owner,provider,client_id,subject,name,email,tokens) VALUES(?,?,?,?,?,?,?,?)',
                    ('documents-account','member1',provider,'synthetic-client','synthetic','Synthetic','synthetic@example.invalid',token))
        for kind, remote_id in [('calendar', 'calendar-1'), ('tasks', 'list-1')]:
            con.execute('INSERT INTO cloud_sources(id,account_id,remote_id,kind,name,owner) VALUES(?,?,?,?,?,?)',
                        ('documents-' + kind,'documents-account',remote_id,kind,'Synthetic','shared'))
    detail = c.get('/api/journeys/' + trip['id']).json
    calendar_payload = {'journeyId': trip['id'], 'sourceId': 'documents-calendar'}
    preview = c.post('/api/calendar-publish/preview', json=calendar_payload, headers=h)
    assert preview.status_code == 200, preview.json
    confirm = c.post('/api/calendar-publish/confirm', json={**calendar_payload, 'previewToken': preview.json['previewToken']}, headers=h)
    assert confirm.status_code == 200, confirm.json
    app.extensions['calendar_publish'].tick()
    preview = c.post('/api/task-publish/preview', json={'entityIds': [detail['tasks'][0]['id']], 'sourceId': 'documents-tasks'}, headers=h)
    assert preview.status_code == 200, preview.json
    confirm = c.post('/api/task-publish/confirm', json={'previewToken': preview.json['previewToken']}, headers=h)
    assert confirm.status_code == 200, confirm.json
    app.extensions['task_publish'].tick()
    with engine.db() as con:
        statuses = [tuple(row) for row in con.execute('SELECT status,error,next_attempt FROM task_publications')]
    assert cal.created == task.created == 1, (statuses, task.calls, cal.created)
    captures = []
    def model(config, prompt, context):
        captures.append(deepcopy(context))
        return {'summary': 'Synthetic summary', 'actions': []}
    monkeypatch.setattr(home_assistant, 'model_plan', model)
    response = c.post('/api/assistant/plan', json={'prompt': 'Synthetic request', 'useModel': True,
                      'includeHouseholdContext': True}, headers=h)
    assert response.status_code == 200, response.json
    assert len(captures) == 1
    outputs = [c.get('/api/state').get_data(as_text=True), c.get('/api/assistant/brief').get_data(as_text=True),
               c.get('/api/journeys/' + trip['id'] + '/calendar.ics').get_data(as_text=True),
               json.dumps(cal.calls), json.dumps(task.calls), json.dumps(captures), json.dumps(detail)]
    for value in (doc['title'], doc['id'], private_doc['title'], private_doc['id'], doc['filename'], '/api/journey-documents/'):
        assert all(value not in text for text in outputs)


class QuietHandler(WSGIRequestHandler):
    def log(self, *args, **kwargs):
        pass


@contextmanager
def serve(app):
    server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:' + str(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)
        assert not thread.is_alive()


def test_documented_two_household_restore_fixture_over_real_loopback(tmp_path, monkeypatch, record_testsuite_property):
    """Synthetic historical 43-table schema; current 44-table recovery has its own test."""
    # Keep the historical gate exact. Disable only places registration for both
    # original and restored factories (including child households in this scope).
    import app as application
    monkeypatch.setattr(application, 'register_journey_places', lambda *_args, **_kwargs: None)
    run_id = uuid.uuid4().hex
    source, target, proof = [tmp_path / name for name in ('source', 'restored', 'proof')]
    for path in (source, target, proof):
        path.mkdir()
    config = {'TESTING': True, 'DATA_DIR': str(source), 'SECRET_KEY': 'synthetic-recovery-document-key',
              'SESSION_COOKIE_SECURE': False, 'PUBLIC_ORIGIN': 'https://127.0.0.1:8000',
              'MEMBER1_PASSWORD': 'synthetic-password-one', 'MEMBER2_PASSWORD': 'synthetic-password-two',
              'MICROSOFT_CLIENT_ID': 'synthetic-client', 'MICROSOFT_CLIENT_SECRET': 'synthetic-secret',
              'OPENAI_API_KEY': '', 'OPENAI_MODEL': ''}
    for key in ('SECRET_KEY', 'MEMBER1_PASSWORD', 'MEMBER2_PASSWORD', 'MICROSOFT_CLIENT_ID'):
        monkeypatch.setenv(key, config[key])
    original = create_app(config)
    with serve(original) as base:
        seeded = recovery.Audit('seed')
        counts = recovery.seed(SimpleNamespace(base_url=base, profile='legacy43'), seeded, source, proof / 'expected.json', run_id)
    assert counts['journeyDocuments'] == 8 and counts['journeys'] == 2
    result = backup_module().backup_all(source)
    assert result['databases'] == 3
    manifest = json.loads((source / 'backups' / result['manifest']).read_text())
    for item in manifest['snapshots']:
        destination = target / item['path']
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / item['path'], destination)
        assert hashlib.sha256(destination.read_bytes()).hexdigest() == item['sha256']
    shutil.copyfile(source / 'backups' / result['manifest'], target / 'backups' / result['manifest'])
    spec = importlib.util.spec_from_file_location('document_recovery_controller', Path(__file__).parents[1] / 'deploy/rehearse_restore.py')
    controller = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(controller)
    restore, sql = controller.documented_programs(Path(__file__).parents[1])
    marker = "root = Path('/data').resolve(strict=True)"
    assert restore.count(marker) == 1
    adapted = restore.replace(marker, 'root = Path(' + repr(str(target)) + ').resolve(strict=True)')
    monkeypatch.setattr(sys, 'argv', ['restore', result['manifest'], 'platform', 'default'])
    exec(compile(adapted, '<documented-restore-with-temp-root>', 'exec'), {})
    for household in recovery.registry(target):
        path = recovery.database_path(target, household['id'])
        with sqlite3.connect(path) as con:
            con.executescript(sql)
    restored = create_app({**config, 'DATA_DIR': str(target)})
    with serve(restored) as base:
        verified = recovery.Audit('verify')
        counts = recovery.verify(SimpleNamespace(base_url=base, profile='legacy43'), verified, target, proof / 'expected.json', run_id)
    assert counts['journeyDocuments'] == 8 and counts['householdTablesEach'] == 43
    assert seeded.external == verified.external == []
    assert all(item['passed'] for item in seeded.checks + verified.checks)
    assert len(verified.checks) > 202
    record_testsuite_property('seedChecks', len(seeded.checks))
    record_testsuite_property('verifyChecks', len(verified.checks))
    record_testsuite_property('journeyDocuments', counts['journeyDocuments'])
    record_testsuite_property('householdTablesEach', counts['householdTablesEach'])
    record_testsuite_property('dockerExecuted', False)
