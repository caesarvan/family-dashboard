"""Synthetic two-household, three-database restore; no Docker or production I/O."""
import ast
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import sys
import time

import pytest
from flask import g

from app import create_app, Problem
from cloud_accounts import GOOGLE_PHOTOS_SCOPE
from deploy.backup import backup_all
from deploy.rehearse_restore import documented_programs
from household_media import register_media_library
from media_playback import register_media_playback
from test_household_media import stage, selected, confirm, device
from test_journey_documents import PASSWORD, connection, create_journey, login

ROOT = Path(__file__).resolve().parents[1]
MEDIA_TABLES = ('media_imports', 'media_items', 'media_tv_grants', 'media_playback')
INVENTORY_TABLES = ('inventory_items', 'inventory_acquisitions', 'inventory_movements',
                    'inventory_source_links', 'inventory_operations')
HOUSEHOLD_TABLES = 53


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*_args, **_kwargs):
        raise AssertionError('External network forbidden in media restore test')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)


def attach(app):
    """Pending factory registration is explicit; strict mode rejects the fallback."""
    missing = [name for name in ('household_media', 'media_playback') if name not in app.extensions]
    if os.environ.get('MEDIA_RESTORE_REQUIRE_FACTORY') == '1':
        assert not missing, 'Run strict recovery against the final factory wiring'
    if 'household_media' in missing:
        def db():
            if 'restore_fixture_db' not in g:
                g.restore_fixture_db = connection(app)
            return g.restore_fixture_db
        @app.teardown_appcontext
        def close(_error):
            con = g.pop('restore_fixture_db', None)
            if con:
                con.close()
        def require_member():
            if g.actor['role'] != 'member':
                raise Problem('Only members', 403)
        register_media_library(app, db, Problem, None, require_member, None)
    if 'media_playback' in missing:
        register_media_playback(app)
    return missing


def config(root):
    return {'TESTING': True, 'DATA_DIR': str(root), 'SECRET_KEY': 'synthetic-media-recovery-key',
        'SESSION_COOKIE_SECURE': False, 'PUBLIC_ORIGIN': 'http://localhost',
        'MEMBER1_PASSWORD': PASSWORD, 'MEMBER2_PASSWORD': PASSWORD,
        'GOOGLE_CLIENT_ID': 'synthetic-client', 'GOOGLE_CLIENT_SECRET': 'synthetic-secret',
        'MICROSOFT_CLIENT_ID': '', 'MICROSOFT_CLIENT_SECRET': '', 'ASSISTANT_PROVIDER': 'local',
        'OPENAI_API_KEY': '', 'OPENAI_MODEL': '', 'NVIDIA_API_KEY': '', 'NVIDIA_MODEL': ''}


def database(root, household):
    return root / ('household.sqlite3' if household == 'default' else f'spaces/{household}/household.sqlite3')


def media_rows(path):
    with closing(sqlite3.connect(path)) as con:
        assert con.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
        assert not con.execute('PRAGMA foreign_key_check').fetchall()
        names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        assert len(names) == HOUSEHOLD_TABLES and set(MEDIA_TABLES+INVENTORY_TABLES) <= names
        return {table: sorted(con.execute('SELECT * FROM '+table).fetchall()) for table in MEDIA_TABLES+INVENTORY_TABLES}


def seed_household(app):
    engine = app.extensions['household_media']
    clock = [time.time()]
    engine.clock = lambda: clock[0]
    app.extensions['media_playback'].clock = lambda: clock[0]
    ids = {}
    with engine.accounts.db() as con:
        for n in (1, 2):
            ids[n] = secrets.token_hex(16)
            tokens = engine.accounts.encrypt({'access_token': 'synthetic-recovery-token', 'scope': GOOGLE_PHOTOS_SCOPE,
                'expires_at': time.time()+3600})
            con.execute('INSERT INTO cloud_accounts(id,owner,provider,client_id,subject,name,email,tokens) VALUES(?,?,?,?,?,?,?,?)',
                (ids[n], f'member{n}', 'google', 'synthetic-client', f'synthetic-subject-{n}', 'Synthetic', 'test.invalid', tokens))
    env = (app, engine, clock, ids)
    c, h, detail, _ = stage(env, items=[selected('private'), selected('shared')])
    confirm(c, h, detail)
    private_id, shared_id = [item['id'] for item in detail['items']]
    journey = create_journey(c, h, 'Synthetic recovery journey')
    row = c.get('/api/media/items/'+shared_id).json['item']
    row = c.patch('/api/media/items/'+shared_id, json={'revision': row['revision'], 'caption': 'Synthetic saved caption',
        'visibility': 'shared', 'journeyId': journey['id']}, headers=h).json['item']
    tv_id, tv, secret = device(env)
    _, _, other_secret = device(env)
    grant = c.put('/api/media/items/'+shared_id+'/tv-grants', json={'revision': row['revision'], 'deviceIds': [tv_id],
        'consentVersion': 'media-v1', 'allowTvDisplay': True}, headers=h)
    assert grant.status_code == 200
    endpoint = '/api/media-playback/devices/'+tv_id
    assert c.put(endpoint, json={'revision': 0, 'action': 'start'}, headers=h).status_code == 200
    assert c.put(endpoint, json={'revision': 1, 'action': 'pause'}, headers=h).status_code == 200
    other, other_h, other_detail, _ = stage(env, 2, [selected('partner-private')])
    confirm(other, other_h, other_detail)
    partner_id = other_detail['items'][0]['id']
    preview = c.get('/api/media/items/'+private_id+'/preview')
    assert preview.status_code == 200 and preview.content_type == 'image/jpeg'
    assert tv.get('/api/media-tv/playback').json['item']['id'] == shared_id
    return {'private': private_id, 'shared': shared_id, 'partner': partner_id, 'journey': journey['id'],
        'tv': tv_id, 'tvCookie': secret, 'ungrantedTvCookie': other_secret,
        'oldCookies': [c.get_cookie('session').value, other.get_cookie('session').value],
        'previewSha256': hashlib.sha256(preview.data).hexdigest()}


def copy_group(source, target, name):
    manifest_path = source/'backups'/name
    manifest = json.loads(manifest_path.read_text())
    assert len(manifest['snapshots']) == 3
    for item in manifest['snapshots']:
        origin = (source/item['path']).resolve(strict=True)
        destination = target/item['path']
        assert origin.is_relative_to(source.resolve()) and destination.resolve().is_relative_to(target.resolve())
        assert hashlib.sha256(origin.read_bytes()).hexdigest() == item['sha256']
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, destination)
    shutil.copy2(manifest_path, target/'backups'/name)


def restore_program(target, name, monkeypatch):
    program, invalidate = documented_programs(ROOT)
    replaced = []
    class TemporaryRoot(ast.NodeTransformer):
        def visit_Constant(self, node):
            if node.value == '/data':
                replaced.append(True)
                return ast.copy_location(ast.Constant(str(target)), node)
            return node
    tree = TemporaryRoot().visit(ast.parse(program))
    assert replaced == [True]  # Only the documented fixed container path changes.
    monkeypatch.setattr(sys, 'argv', ['synthetic-local-restore', name, 'platform', 'default'])
    exec(compile(ast.fix_missing_locations(tree), '<documented-restore-temporary-path-only>', 'exec'), {})
    return invalidate


def test_two_household_media_backup_restore_and_authorization(tmp_path, monkeypatch):
    source, target = tmp_path/'source', tmp_path/'restored'
    source.mkdir(); target.mkdir()
    app = create_app(config(source))
    fallback = {'source-default': attach(app)}
    owner, h = login(app)
    invitation = owner.post('/api/spaces/invitations', json={}, headers=h).json['invitation']
    response = app.test_client().post('/api/spaces/redeem', json={'invitation': invitation, 'slug': 'media-recovery',
        'name': 'Synthetic recovery household', 'MEMBER1_PASSWORD': PASSWORD, 'MEMBER2_PASSWORD': PASSWORD})
    assert response.status_code == 201
    platform = app.extensions['household_platform']
    household = next(row for row in platform.households() if row['id'] != 'default')
    child = platform.child(household)
    fallback['source-child'] = attach(child)
    apps = {'default': app, household['id']: child}
    expected = {uid: seed_household(application) for uid, application in apps.items()}
    before = {uid: media_rows(database(source, uid)) for uid in apps}
    backed = backup_all(source)
    assert backed['databases'] == 3
    # A later source revocation cannot magically change the older backup group.
    for uid, application in apps.items():
        c, headers = login(application)
        row = c.get('/api/media/items/'+expected[uid]['shared']).json['item']
        assert c.put('/api/media/items/'+row['id']+'/tv-grants', json={'revision': row['revision'], 'deviceIds': []}, headers=headers).status_code == 200
    copy_group(source, target, backed['manifest'])
    invalidate = restore_program(target, backed['manifest'], monkeypatch)
    for uid in apps:
        path = database(target, uid)
        assert media_rows(path) == before[uid]  # All encrypted BLOBs, grants and playback bytes/values survive.
        with closing(sqlite3.connect(path)) as con:
            previous = dict(con.execute('SELECT id,auth_version FROM users'))
            con.executescript(invalidate)
            assert dict(con.execute('SELECT id,auth_version FROM users')) == {k:v+1 for k,v in previous.items()}
            assert con.execute('SELECT count(*) FROM member_sessions WHERE revoked_at IS NULL').fetchone()[0] == 0
            assert con.execute('SELECT count(*) FROM cloud_oauth_states').fetchone()[0] == 0
    restored = create_app(config(target))
    fallback['restored-default'] = attach(restored)
    restored_platform = restored.extensions['household_platform']
    restored_child = restored_platform.child(next(h for h in restored_platform.households() if h['id'] == household['id']))
    fallback['restored-child'] = attach(restored_child)
    restored_apps = {'default': restored, household['id']: restored_child}
    for uid, application in restored_apps.items():
        value = expected[uid]
        assert media_rows(database(target, uid)) == before[uid]
        for cookie in value['oldCookies']:
            stale = application.test_client(); stale.set_cookie('session', cookie)
            assert stale.get('/api/media/items').status_code == 401
        c, headers = login(application)
        partner, _ = login(application, 2)
        private = c.get('/api/media/items/'+value['private']).json['item']
        assert private['visibility'] == 'private'
        preview = c.get(private['previewUrl'])
        assert hashlib.sha256(preview.data).hexdigest() == value['previewSha256']
        assert partner.get(private['previewUrl']).status_code == 404
        assert c.get('/api/media/items/'+value['partner']).status_code == 404
        shared = c.get('/api/media/items/'+value['shared']).json['item']
        assert shared['caption'] == 'Synthetic saved caption' and shared['journey']['id'] == value['journey']
        assert partner.get(shared['previewUrl']).status_code == 200
        for other_uid, other_value in expected.items():
            if other_uid != uid:
                assert c.get('/api/media/items/'+other_value['shared']).status_code == 404
        tv = application.test_client(); tv.set_cookie('household_tv', value['tvCookie'])
        ungranted = application.test_client(); ungranted.set_cookie('household_tv', value['ungrantedTvCookie'])
        state = tv.get('/api/media-tv/playback').json
        assert state['paused'] and state['item']['id'] == value['shared']
        assert tv.get(state['item']['previewUrl']).status_code == 200
        assert ungranted.get(state['item']['previewUrl']).status_code == 404
        # Offline operator review is required: the original session SQL leaves TV grants intact.
        assert c.put('/api/media/items/'+value['shared']+'/tv-grants', json={'revision': shared['revision'], 'deviceIds': []}, headers=headers).status_code == 200
        assert tv.get('/api/media-tv/playback').json['item'] is None
        assert tv.get(state['item']['previewUrl']).status_code == 404
        assert c.get(private['previewUrl']).status_code == 200
    print(json.dumps({'kind':'synthetic-local-sqlite-restore','realDocker':False,'productionWrites':0,
        'households':2,'databases':3,'householdTables':HOUSEHOLD_TABLES,'oldCookiesRejected':4,'factoryFallback':fallback,
        'restoredTvGrantsRequireReview':True,'mediaWorkerStarted':False}))
