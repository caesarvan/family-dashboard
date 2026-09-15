"""Synthetic data only: HTTP fixture for an independently controlled restore rehearsal.

Run seed or verify inside the isolated app container. This script never backs up,
restores, migrates or invalidates a database. The controller owns those steps.
Only seed inserts fake encrypted accounts and pending OAuth states; the shared
entities, photos, private finance, members and TVs use the actual HTTP API.
expected.json contains synthetic secrets and is 0600.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import hashlib
import hmac
from http.cookiejar import Cookie, CookieJar
from io import BytesIO
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import sys
import time
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, ProxyHandler, Request, build_opener
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# The controller mounts tests at /rehearsal/tests; image modules live at /app.
# Accept that one fixed image location, never a caller-selected import root.
if os.name == 'posix' and Path('/app/cloud_accounts.py').is_file():
    sys.path.insert(0, '/app')


class FixtureFailure(Exception):
    """Deliberately excludes response bodies, cookie values and private data."""


def require(value):
    if not value:
        raise FixtureFailure()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value).encode()).hexdigest()


class Audit:
    def __init__(self, phase):
        self.phase, self.stage = phase, 'environment'
        self.checks, self.requests = [], 0
        self.external = []

    def check(self, name, condition=True):
        self.stage = name
        require(condition)
        self.checks.append({'name': name, 'passed': True})


def loopback_url(value):
    parsed = urlsplit(value)
    require(parsed.scheme in {'http', 'https'} and not parsed.username and not parsed.password)
    require(parsed.hostname in {'localhost', '127.0.0.1', '::1'})
    return parsed


@contextmanager
def only_loopback(audit):
    old_connect, old_connect_ex, old_dns = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo

    def allowed(host):
        if isinstance(host, bytes):
            host = host.decode('ascii')
        if host == 'localhost':
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def guard_address(address):
        if isinstance(address, tuple) and not allowed(address[0]):
            audit.external.append({'blocked': True})
            raise FixtureFailure()

    def connect(sock, address):
        guard_address(address)
        return old_connect(sock, address)

    def connect_ex(sock, address):
        guard_address(address)
        return old_connect_ex(sock, address)

    def dns(host, *args, **kwargs):
        if host is not None and not allowed(host):
            audit.external.append({'blocked': True})
            raise FixtureFailure()
        rows = old_dns(host, *args, **kwargs)
        require(all(allowed(row[4][0]) for row in rows))
        return rows

    with patch.object(socket.socket, 'connect', connect), patch.object(socket.socket, 'connect_ex', connect_ex), patch.object(socket, 'getaddrinfo', dns):
        yield


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        loopback_url(newurl)
        return None  # Even same-origin routing redirects are never followed.


class Client:
    def __init__(self, base, audit, cookies=()):
        self.base, self.audit, self.jar, self.csrf = base, audit, CookieJar(), None
        for item in cookies:
            require(item['name'] in {'session', 'household_space', 'household_tv'})
            require(item['domain'] in {'127.0.0.1', 'localhost.local', 'localhost', '::1'})
            require(item['path'] == '/')
            self.jar.set_cookie(Cookie(0, item['name'], item['value'], None, False, item['domain'], False, False,
                                       '/', True, item['secure'], item['expires'], False, None, None, {'HttpOnly': None}, False))
        self.opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(self.jar), NoRedirect())

    def request(self, method, path, payload=None, status=200, raw=False):
        require(path.startswith('/') and not path.startswith('//') and '\\' not in path)
        require(loopback_url(self.base + path).netloc == urlsplit(self.base).netloc)
        headers = {'Accept': 'application/json', 'User-Agent': 'SyntheticRestoreRehearsal/1', 'Origin': self.base}
        if payload is not None:
            headers['Content-Type'] = 'application/json'
        if self.csrf:
            headers['X-CSRF-Token'] = self.csrf
        req = Request(self.base + path, data=None if payload is None else canonical(payload).encode(), headers=headers, method=method)
        self.audit.requests += 1
        try:
            response = self.opener.open(req, timeout=20)
        except HTTPError as error:
            response = error
        with response:
            content = response.read(16_000_001)
            require(len(content) <= 16_000_000)
            require(response.code == status)
            if 300 <= response.code < 400:
                location = response.headers.get('Location', '')
                loopback_url(self.base + location if location.startswith('/') else location)
                return {'location': location}
            if raw:
                return content
            return json.loads(content)

    def route(self, entry):
        require(entry in {'/space/home', '/space/rehearsal-child'})
        self.request('GET', entry, status=303)

    def login(self, entry, number, password):
        self.route(entry)
        self.request('GET', '/api/me')
        self.request('POST', '/api/login', {'username': 'member' + str(number), 'password': password})
        me = self.request('GET', '/api/me')
        require(me['user']['id'] == 'member' + str(number))
        self.csrf = me['csrf']
        return me

    def cookies(self):
        return [{key: getattr(item, key) for key in ('name', 'value', 'domain', 'path', 'secure', 'expires')} for item in self.jar]


def encoded(value):
    if isinstance(value, bytes):
        return {'blob': base64.b64encode(value).decode('ascii')}
    return value


@contextmanager
def read_db(path):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size > 0)
    con = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=20)
    try:
        con.execute('PRAGMA query_only=ON')
        con.execute('BEGIN')
        require(con.execute('PRAGMA quick_check').fetchone() == ('ok',))
        yield con
    finally:
        con.close()


def quoted(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def snapshot(path):
    with read_db(path) as con:
        schema = [list(row) for row in con.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name')]
        tables = {}
        for name, in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            indexes = [list(row) for row in con.execute('PRAGMA index_list(' + quoted(name) + ')')]
            tables[name] = {
                'columns': [list(row) for row in con.execute('PRAGMA table_xinfo(' + quoted(name) + ')')],
                'foreignKeys': [list(row) for row in con.execute('PRAGMA foreign_key_list(' + quoted(name) + ')')],
                'indexes': indexes,
                'indexColumns': {row[1]: [list(v) for v in con.execute('PRAGMA index_xinfo(' + quoted(row[1]) + ')')] for row in indexes},
                'rows': sorted(([encoded(v) for v in row] for row in con.execute('SELECT * FROM ' + quoted(name))), key=canonical),
            }
        return {'schema': schema, 'tables': tables,
                'userVersion': con.execute('PRAGMA user_version').fetchone()[0],
                'applicationId': con.execute('PRAGMA application_id').fetchone()[0]}


def row_objects(table):
    names = [column[1] for column in table['columns']]
    return [dict(zip(names, row)) for row in table['rows']]


def registry(data_dir):
    with read_db(data_dir / 'platform.sqlite3') as con:
        columns = [row[1] for row in con.execute('PRAGMA table_info(households)')]
        houses = [dict(zip(columns, row)) for row in con.execute('SELECT * FROM households ORDER BY id')]
    require(houses and any(x['id'] == 'default' and x['slug'] == 'home' for x in houses))
    for house in houses:
        require(house['id'] == 'default' or re.fullmatch('[0-9a-f]{24}', house['id']))
    return houses


def database_path(data_dir, hid):
    require(hid == 'default' or re.fullmatch('[0-9a-f]{24}', hid))
    path = data_dir / ('household.sqlite3' if hid == 'default' else 'spaces/' + hid + '/household.sqlite3')
    require(path.resolve().is_relative_to(data_dir.resolve()))
    return path


def password(hid, number, run_id):
    return os.environ['MEMBER' + str(number) + '_PASSWORD'] if hid == 'default' else 'synthetic-child-' + str(number) + '-' + run_id


def household_secret(hid):
    secret = os.environ['SECRET_KEY']
    return secret if hid == 'default' else hmac.new(secret.encode(), ('household|' + hid).encode(), hashlib.sha256).hexdigest()


def cloud_cipher(hid):
    # Use the actual encrypt/decrypt methods without constructing an app or
    # CloudAccounts (both constructors initialize storage).
    from cryptography.fernet import Fernet
    from cloud_accounts import CloudAccounts
    secret = household_secret(hid)
    engine = object.__new__(CloudAccounts)
    engine.cipher = Fernet(base64.urlsafe_b64encode(hashlib.sha256((secret + '|cloud-accounts-v1').encode()).digest()))
    return engine


def seed_oauth(data_dir, hid, uid, client):
    # HTTP loopback deliberately differs from the HTTPS OAuth public origin,
    # so /accounts/bind correctly refuses it. Seed only the allowed synthetic
    # OAuth fixture, mirroring the current authenticated browser claim. Never
    # initialize production storage or relax the application's origin guard.
    from flask import Flask
    from flask.sessions import SecureCookieSessionInterface
    signing_app = Flask('synthetic-oauth-cookie')
    signing_app.secret_key = household_secret(hid)
    serializer = SecureCookieSessionInterface().get_signing_serializer(signing_app)
    cookie = next(c for c in client.jar if c.name == 'session')
    signed = serializer.loads(cookie.value)
    require(signed['uid'] == uid and signed['csrf'] == client.csrf)
    signed['oauth_browser'] = secrets.token_urlsafe(32)
    cookie.value = serializer.dumps(signed)
    state, control = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    engine = cloud_cipher(hid)
    with sqlite3.connect(database_path(data_dir, hid)) as con:
        con.row_factory = sqlite3.Row
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT * FROM member_sessions WHERE credential_hash=? AND revoked_at IS NULL',
                          (hashlib.sha256(client.csrf.encode()).hexdigest(),)).fetchone()
        require(row and row['owner'] == uid)
        con.execute('UPDATE member_session_browsers SET generation=generation+1 WHERE browser_hash=?', (row['browser_hash'],))
        generation = con.execute('SELECT generation FROM member_session_browsers WHERE browser_hash=?', (row['browser_hash'],)).fetchone()[0]
        context = {'browserHash': row['browser_hash'], 'generation': generation, 'credentialHash': row['credential_hash'],
                   'owner': uid, 'av': row['auth_version'], 'accounts': []}
        for value in (state, control):
            con.execute('INSERT INTO cloud_oauth_states '
                        '(state_hash,browser_hash,provider,mode,owner,auth_version,verifier,client_id,expires,auth_context) VALUES(?,?,?,?,?,?,?,?,?,?)',
                        (hashlib.sha256(value.encode()).hexdigest(), hashlib.sha256(signed['oauth_browser'].encode()).hexdigest(),
                         'microsoft', 'bind', uid, row['auth_version'], engine.encrypt(secrets.token_urlsafe(48)),
                         os.environ['MICROSOFT_CLIENT_ID'], time.time() + 600, canonical(context)))
    # A separate control state must be consumed by the real callback before
    # backup. Explicit provider denial exits before any provider exchange.
    result = client.request('GET', '/auth/microsoft/callback?' + urlencode({'state': control, 'error': 'access_denied'}), status=302)
    require(parse_qs(urlsplit(result['location']).query).get('reason') == ['provider_denied'])
    return state


def png(number):
    from PIL import Image
    target = BytesIO()
    Image.new('RGB', (8 + number, 9 + number), ((31 * number) % 255, (83 * number) % 255, (151 * number) % 255)).save(target, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(target.getvalue()).decode()


def synthetic_pdf():
    """Small valid PDF assembled from fixed synthetic objects, with no input file."""
    content = b'BT /F1 12 Tf 20 40 Td (Synthetic recovery document) Tj ET\n'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               b'<< /Length ' + str(len(content)).encode() + b' >>\nstream\n' + content + b'endstream']
    output, offsets = bytearray(b'%PDF-1.4\n'), [0]
    for index, value in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(str(index).encode() + b' 0 obj\n' + value + b'\nendobj\n')
    start = len(output)
    output.extend(b'xref\n0 6\n0000000000 65535 f \n')
    for offset in offsets[1:]:
        output.extend(f'{offset:010d} 00000 n \n'.encode())
    output.extend(b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n' + str(start).encode() + b'\n%%EOF\n')
    return bytes(output)


def seed_journey(client, run_id, household_id):
    plan = {'title': 'Synthetic recovery journey', 'start': '2026-12-03', 'end': '2026-12-05',
            'international': False, 'memberIds': ['member1', 'member2'], 'budget': 0,
            'destinations': [{'key': 'synthetic-city', 'country': 'Synthetic', 'city': 'Recovery',
                              'arrival': '2026-12-03', 'departure': '2026-12-05'}],
            'checklist': [], 'shopping': [], 'segments': []}
    preview = client.request('POST', '/api/journeys/preview', {'plan': plan})
    return client.request('POST', '/api/journeys/apply',
                          {'previewToken': preview['previewToken'], 'idempotencyKey': run_id + '-' + household_id}, status=201)


DOCUMENT_METADATA = ('id', 'journeyId', 'owner', 'title', 'filename', 'mimeType', 'bytes',
                     'visibility', 'segmentKey', 'unlinked', 'createdAt', 'updatedAt', 'revision')


def seed_documents(client, journey_id, marker, number):
    documents = []
    for visibility in ('private', 'shared'):
        raw = synthetic_pdf() if visibility == 'private' else base64.b64decode(png(number).split(',', 1)[1])
        mime = 'application/pdf' if visibility == 'private' else 'image/png'
        result = client.request('POST', '/api/journey-documents', {
            'journeyId': journey_id, 'requestId': secrets.token_hex(16), 'visibility': visibility,
            'title': marker + '-' + visibility + '-document',
            'file': {'name': 'synthetic.pdf' if visibility == 'private' else 'synthetic.png',
                     'mimeType': mime, 'dataBase64': base64.b64encode(raw).decode()}}, status=201)
        document = result['document']
        content = client.request('GET', '/api/journey-documents/' + document['id'] + '/file', raw=True)
        require(content == raw if visibility == 'private' else document['mimeType'] == 'image/jpeg' and content != raw)
        require(document['bytes'] == len(content))
        documents.append({'metadata': {key: document[key] for key in DOCUMENT_METADATA},
                          'sha256': digest(content), 'bytes': len(content)})
    return documents


def seed(args, audit, data_dir, expected_path, run_id):
    audit.stage = 'empty_isolated_seed_target'
    require(not expected_path.exists())
    houses = registry(data_dir)
    require(len(houses) == 1 and houses[0]['id'] == 'default')
    initial = snapshot(database_path(data_dir, 'default'))
    require(all(not value['rows'] for name, value in initial['tables'].items() if name not in {'users', 'settings', 'sqlite_sequence'}))
    require(not snapshot(data_dir / 'platform.sqlite3')['tables']['household_invitations']['rows'])
    audit.check('seed_target_has_no_existing_business_or_accounts')
    clients = {}
    admin = Client(args.base_url, audit)
    admin.login('/space/home', 1, password('default', 1, run_id))
    invitation = admin.request('POST', '/api/spaces/invitations', {}, status=201)
    child = Client(args.base_url, audit)
    child.request('POST', '/api/spaces/redeem', {'invitation': invitation['invitation'], 'slug': 'rehearsal-child',
                  'name': 'Synthetic recovery household',
                  'MEMBER1_PASSWORD': password('child', 1, run_id), 'MEMBER2_PASSWORD': password('child', 2, run_id)}, status=201)
    houses = registry(data_dir)
    require(len(houses) == 2)
    expected = {'version': 1, 'runId': run_id, 'seededAt': time.time(), 'households': [],
                'configurationDigest': digest([os.environ[x] for x in ('SECRET_KEY', 'MEMBER1_PASSWORD', 'MEMBER2_PASSWORD')])}
    for index, house in enumerate(houses):
        hid, slug = house['id'], house['slug']
        entry = '/space/' + slug
        item = {'id': hid, 'slug': slug, 'entry': entry, 'members': {}, 'tasks': [], 'shopping': [], 'photos': [], 'documents': []}
        for number in (1, 2):
            audit.stage = 'seed_shared_private_and_photos'
            client = admin if hid == 'default' and number == 1 else Client(args.base_url, audit)
            if client is not admin:
                client.login(entry, number, password(hid, number, run_id))
            uid = 'member' + str(number)
            clients[(hid, uid)] = client
            if number == 1:
                created_journey = seed_journey(client, run_id, hid)
                item['journeyId'] = created_journey['id']
                item['tripId'] = created_journey['tripId']
                audit.check('seed_' + slug + '_journey_created_by_actual_api')
            marker = 'SYNTHETIC-' + hid + '-' + uid
            item['documents'].extend(seed_documents(client, item['journeyId'], marker, index * 2 + number))
            audit.check('seed_' + slug + '_' + uid + '_private_pdf_shared_sanitized_image')
            task = client.request('POST', '/api/items/tasks', {'title': marker + '-task', 'owner': 'shared', 'note': 'Synthetic recovery fixture'}, status=201)
            item['tasks'].append(task['id'])
            photos = []
            for attached in (True, False):
                photo = client.request('POST', '/api/photos', {'dataUrl': png(index * 4 + number * 2 + int(attached))}, status=201)
                content = client.request('GET', photo['url'], raw=True)
                photos.append(photo['id'])
                item['photos'].append({'id': photo['id'], 'owner': uid, 'attached': attached, 'sha256': digest(content), 'bytes': len(content)})
            shopping = client.request('POST', '/api/items/shopping', {'title': marker + '-shopping', 'owner': 'shared', 'quantity': '1 synthetic item',
                                      'budget': 12300 + number, 'actual': 1000 + number, 'photoIds': [photos[0]]}, status=201)
            item['shopping'].append(shopping['id'])
            private = {'income': 111000 + index * 1000 + number, 'spent': 1200 + number, 'budget': 2200 + number, 'month': '2026-09', 'revision': 0}
            client.request('PUT', '/api/private-finance', private)
            ledger = {'source': 'generic', 'kind': 'payments', 'csv': 'date,title,amount,currency,flow,category,id,status\n2026-09-02,' + marker + '-private-payment,12.34,CNY,expense,Synthetic,' + marker + ',成功\n'}
            preview = client.request('POST', '/api/finance-hub/imports/preview', ledger)
            confirmation = client.request('POST', '/api/finance-hub/imports/confirm', {**ledger, 'previewToken': preview['previewToken']})
            require(confirmation['imported'] == 1)
            model = client.request('GET', '/api/finance-hub/overview?month=2026-09')
            require(len(model['transactions']) == 1)
            transaction_id = model['transactions'][0]['id']
            state = seed_oauth(data_dir, hid, uid, client)
            me = client.request('GET', '/api/me')
            require(me['user']['id'] == uid and me['user']['householdId'] == hid)
            item['members'][uid] = {'cookies': client.cookies(), 'oldOAuthState': state, 'private': client.request('GET', '/api/private-finance'),
                                    'transactionId': transaction_id, 'transactionTitle': marker + '-private-payment'}
            audit.check('seed_' + slug + '_' + uid + '_shared_private_photo_and_oauth')
        tv = Client(args.base_url, audit)
        tv.route(entry)
        pair = tv.request('POST', '/api/pair/start', {})
        clients[(hid, 'member1')].request('POST', '/api/pair/approve', {'code': pair['code'], 'name': 'Synthetic restore TV', 'focus': 'shared'})
        require(tv.request('POST', '/api/pair/poll', {'secret': pair['secret']})['approved'])
        tv_me = tv.request('GET', '/api/me')
        require(tv_me['user']['role'] == 'tv')
        item['tv'] = {'cookies': tv.cookies(), 'id': tv_me['user']['id']}
        # A valid encrypted fake credential preserves
        # encrypted-storage/key semantics without calling a provider transport.
        aid = 'synthetic-rehearsal-' + hid
        token = {'access_token': 'synthetic-access-' + run_id, 'refresh_token': 'synthetic-refresh-' + hid,
                 'scope': 'User.Read Calendars.Read Tasks.ReadWrite', 'expires_at': time.time() + 7200, 'fixtureRunId': run_id}
        engine = cloud_cipher(hid)
        ciphertext = engine.encrypt(token)
        with sqlite3.connect(database_path(data_dir, hid)) as con:
            con.execute('PRAGMA foreign_keys=ON')
            con.execute('INSERT INTO cloud_accounts(id,owner,provider,client_id,subject,name,email,tokens) VALUES(?,?,?,?,?,?,?,?)',
                        (aid, 'member1', 'microsoft', os.environ['MICROSOFT_CLIENT_ID'], aid, 'Synthetic encrypted credential', 'rehearsal@example.invalid', ciphertext))
            require(con.execute('PRAGMA foreign_key_check').fetchall() == [])
        item['cloud'] = {'accountId': aid, 'tokenDigest': digest(token), 'ciphertextSha256': digest(ciphertext.encode())}
        expected['households'].append(item)
        audit.check('seed_' + slug + '_tv_and_encrypted_fake_credential')
    # No more HTTP after this snapshot: it is the controller's backup baseline.
    audit.stage = 'seed_all_database_snapshot'
    expected['registry'] = snapshot(data_dir / 'platform.sqlite3')
    expected['databases'] = {house['id']: snapshot(database_path(data_dir, house['id'])) for house in houses}
    expected['fingerprints'] = {hid: digest(value) for hid, value in expected['databases'].items()}
    require(all(sum(not name.startswith('sqlite_') for name in value['tables']) == 43 for value in expected['databases'].values()))
    require(len(expected['registry']['tables']) == 2)
    require(all(len(value['tables']['cloud_oauth_states']['rows']) == 2 for value in expected['databases'].values()))
    audit.check('seed_snapshot_contains_two_43_table_households_and_two_registry_tables')
    descriptor = os.open(expected_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
        output.write(canonical(expected) + '\n')
        output.flush()
        os.fsync(output.fileno())
    audit.check('seed_expected_written_exclusively')
    return {'households': 2, 'members': 4, 'tasks': 4, 'shopping': 4, 'photos': 8, 'tvs': 2, 'oauthStates': 4, 'fakeAccounts': 2,
            'journeys': 2, 'journeyDocuments': 8}


def compare_restored(old, new, audit, label, seeded_at):
    audit.check(label + '_schema_and_table_set', old['schema'] == new['schema'] and set(old['tables']) == set(new['tables'])
                and old['userVersion'] == new['userVersion'] and old['applicationId'] == new['applicationId'])
    for name, before in old['tables'].items():
        after = new['tables'][name]
        audit.check(label + '_' + name + '_columns_foreign_keys_indexes', {k: v for k, v in before.items() if k != 'rows'} == {k: v for k, v in after.items() if k != 'rows'})
        if name == 'cloud_oauth_states':
            audit.check(label + '_oauth_states_cleared', bool(before['rows']) and not after['rows'])
        elif name in {'users', 'member_sessions', 'member_session_browsers'}:
            key = 'browser_hash' if name == 'member_session_browsers' else 'id'
            left, right = ({row[key]: row for row in row_objects(table)} for table in (before, after))
            require(left and set(left) == set(right))
            for uid, row in left.items():
                actual, wanted = right[uid], dict(row)
                if name == 'users':
                    wanted['auth_version'] += 1
                elif name == 'member_session_browsers':
                    wanted['generation'] += 1
                elif row['revoked_at'] is None:
                    stamp = actual['revoked_at']
                    require(type(stamp) in {int, float} and math.isfinite(stamp) and float(stamp).is_integer() and math.floor(seeded_at) <= stamp <= time.time() + 5)
                    wanted['revoked_at'] = stamp
                require(actual == wanted)
            audit.check(label + '_' + name + '_exact_documented_invalidation_only')
        else:
            audit.check(label + '_' + name + '_all_rows_preserved', before['rows'] == after['rows'])


def verify(args, audit, data_dir, expected_path, run_id):
    audit.stage = 'expected_proof_binding'
    require(expected_path.is_file() and not expected_path.is_symlink() and expected_path.stat().st_size < 20_000_000)
    expected = json.loads(expected_path.read_text(encoding='utf-8'))
    require(expected['version'] == 1 and expected['runId'] == run_id)
    require(expected['configurationDigest'] == digest([os.environ[x] for x in ('SECRET_KEY', 'MEMBER1_PASSWORD', 'MEMBER2_PASSWORD')]))
    audit.check('proof_run_and_original_configuration_bound')
    # Must finish all DB/registry checks before any HTTP, including /me.
    audit.stage = 'pre_login_database_comparison'
    houses = registry(data_dir)
    require({(h['id'], h['slug']) for h in houses} == {(h['id'], h['slug']) for h in expected['households']})
    actual_children = {p.parent.name for p in (data_dir / 'spaces').glob('*/household.sqlite3')}
    require(actual_children == {h['id'] for h in houses if h['id'] != 'default'})
    audit.check('registered_household_ids_slugs_and_storage_mapping_preserved')
    audit.check('platform_all_schema_tables_and_rows_preserved', snapshot(data_dir / 'platform.sqlite3') == expected['registry'])
    for house in expected['households']:
        hid = house['id']
        require(digest(expected['databases'][hid]) == expected['fingerprints'][hid])
        compare_restored(expected['databases'][hid], snapshot(database_path(data_dir, hid)), audit, house['slug'], expected['seededAt'])
    audit.check('all_database_checks_completed_before_first_http_request', audit.requests == 0)
    clients = {}
    for house in expected['households']:
        hid, slug = house['id'], house['slug']
        for uid, member in house['members'].items():
            audit.stage = 'old_cookie_and_oauth_rejected'
            old = Client(args.base_url, audit, member['cookies'])
            old.request('GET', '/api/state', status=401)
            old.request('GET', '/api/private-finance', status=401)
            result = old.request('GET', '/auth/microsoft/callback?' + urlencode({'state': member['oldOAuthState'], 'error': 'access_denied'}), status=302)
            require(parse_qs(urlsplit(result['location']).query).get('reason') == ['invalid_state'])
            audit.check(slug + '_' + uid + '_old_cookie_401_and_old_oauth_invalid_without_exchange')
            number = int(uid[-1])
            client = Client(args.base_url, audit)
            me = client.login(house['entry'], number, password(hid, number, run_id))
            require(me['user']['householdId'] == hid)
            clients[(hid, uid)] = client
            state = client.request('GET', '/api/state')
            require({x['id'] for x in state['tasks']} == set(house['tasks']))
            require({x['id'] for x in state['shopping']} == set(house['shopping']))
            require(client.request('GET', '/api/private-finance') == member['private'])
            model = client.request('GET', '/api/finance-hub/overview?month=2026-09')
            require(len(model['transactions']) == 1 and model['transactions'][0]['id'] == member['transactionId']
                    and model['transactions'][0]['title'] == member['transactionTitle'])
            require(member['transactionTitle'] not in canonical(state))
            other_uid = 'member2' if uid == 'member1' else 'member1'
            foreign = house['members'][other_uid]
            require(foreign['transactionTitle'] not in canonical(model))
            client.request('GET', '/api/finance-hub/reconciliation?transactionId=' + foreign['transactionId'], status=404)
            audit.check(slug + '_' + uid + '_fresh_login_shared_ids_and_owner_only_finance')
            for photo in house['photos']:
                allowed = photo['attached'] or photo['owner'] == uid
                content = client.request('GET', '/api/photos/' + photo['id'], status=200 if allowed else 404, raw=allowed)
                if allowed:
                    require(digest(content) == photo['sha256'] and len(content) == photo['bytes'])
            audit.check(slug + '_' + uid + '_attached_shared_unattached_owner_only_photos')
            documents = client.request('GET', '/api/journey-documents?journeyId=' + house['journeyId'])['documents']
            expected_documents = [doc for doc in house['documents'] if doc['metadata']['owner'] == uid or doc['metadata']['visibility'] == 'shared']
            require({doc['id'] for doc in documents} == {doc['metadata']['id'] for doc in expected_documents})
            own_documents = client.request('GET', '/api/journey-documents')['documents']
            require({doc['id'] for doc in own_documents} == {doc['metadata']['id'] for doc in house['documents'] if doc['metadata']['owner'] == uid})
            for document in house['documents']:
                meta = document['metadata']
                allowed = meta['owner'] == uid or meta['visibility'] == 'shared'
                content = client.request('GET', '/api/journey-documents/' + meta['id'] + '/file', status=200 if allowed else 404, raw=allowed)
                require(meta['title'] not in canonical(state) and meta['id'] not in canonical(state))
                if allowed:
                    actual = next(doc for doc in documents if doc['id'] == meta['id'])
                    require({key: actual[key] for key in DOCUMENT_METADATA} == meta)
                    require(actual['canManage'] == (meta['owner'] == uid))
                    require(digest(content) == document['sha256'] and len(content) == document['bytes'])
            audit.check(slug + '_' + uid + '_document_metadata_file_hash_private_shared_and_state_isolation')
        audit.stage = 'restored_tv_and_key_verification'
        tv = Client(args.base_url, audit, house['tv']['cookies'])
        state = tv.request('GET', '/api/state')
        require({x['id'] for x in state['tasks']} == set(house['tasks']))
        require(tv.request('GET', '/api/me')['user']['id'] == house['tv']['id'])
        tv.request('POST', '/api/items/tasks', {'title': 'MUST_NOT_BE_CREATED'}, status=403)
        tv.request('GET', '/api/private-finance', status=403)
        tv.request('GET', '/api/finance-hub/overview', status=403)
        for photo in house['photos']:
            content = tv.request('GET', '/api/photos/' + photo['id'], status=200 if photo['attached'] else 404, raw=photo['attached'])
            if photo['attached']:
                require(digest(content) == photo['sha256'])
        audit.check(slug + '_original_tv_read_only_and_photo_permissions_preserved')
        tv.request('GET', '/api/journey-documents', status=403)
        tv.request('GET', '/api/journey-documents?journeyId=' + house['journeyId'], status=403)
        for document in house['documents']:
            tv.request('GET', '/api/journey-documents/' + document['metadata']['id'] + '/file', status=403)
        audit.check(slug + '_original_tv_cannot_read_journey_document_metadata_or_files')
        with read_db(database_path(data_dir, hid)) as con:
            token = con.execute('SELECT tokens FROM cloud_accounts WHERE id=?', (house['cloud']['accountId'],)).fetchone()
        require(token and digest(token[0].encode()) == house['cloud']['ciphertextSha256'])
        require(digest(cloud_cipher(hid).decrypt(token[0])) == house['cloud']['tokenDigest'])
        account_model = clients[(hid, 'member1')].request('GET', '/api/accounts')
        require(house['cloud']['accountId'] in canonical(account_model))
        require(house['cloud']['accountId'] not in canonical(clients[(hid, 'member2')].request('GET', '/api/accounts')))
        audit.check(slug + '_fake_token_decrypts_with_preserved_household_key_and_account_owner')
    audit.stage = 'cross_household_isolation'
    for house in expected['households']:
        other = next(h for h in expected['households'] if h['id'] != house['id'])
        for uid in ('member1', 'member2'):
            client = clients[(house['id'], uid)]
            # This PATCH is deliberately unauthorized and must be 404. The
            # pre-login all-table proof was completed before any verification IO.
            client.request('PATCH', '/api/items/tasks/' + other['tasks'][0], {'revision': 1, 'title': 'MUST_NOT_BE_CHANGED'}, status=404)
            client.request('GET', '/api/photos/' + other['photos'][0]['id'], status=404)
            client.request('GET', '/api/finance-hub/reconciliation?transactionId=' + other['members'][uid]['transactionId'], status=404)
            audit.check(house['slug'] + '_' + uid + '_cross_household_entity_photo_finance_404')
            client.request('GET', '/api/journey-documents?journeyId=' + other['journeyId'], status=404)
            for document in other['documents']:
                client.request('GET', '/api/journey-documents/' + document['metadata']['id'] + '/file', status=404)
            audit.check(house['slug'] + '_' + uid + '_cross_household_journey_documents_404')
    # Authentication verification necessarily creates fresh sessions/attempts.
    # Every other table, including audit and sqlite_sequence, must still match
    # the original synthetic business snapshot after the denied write probes.
    auth_tables = {'users', 'member_sessions', 'member_session_browsers', 'cloud_oauth_states', 'attempts'}
    for house in expected['households']:
        before = expected['databases'][house['id']]
        after = snapshot(database_path(data_dir, house['id']))
        require(before['schema'] == after['schema'] and set(before['tables']) == set(after['tables']))
        audit.check(house['slug'] + '_all_business_tables_unchanged_after_http_permission_probes',
                    all(before['tables'][name] == after['tables'][name] for name in before['tables'] if name not in auth_tables))
    audit.check('platform_unchanged_after_http_permission_probes', snapshot(data_dir / 'platform.sqlite3') == expected['registry'])
    audit.check('fixture_used_only_loopback_http_and_no_provider_endpoint', not audit.external)
    return {'households': 2, 'members': 4, 'householdTablesEach': 43, 'registryTables': 2, 'photos': 8, 'tvs': 2,
            'journeys': 2, 'journeyDocuments': 8,
            'oldCookiesRejected': 4, 'oldOAuthStatesRejected': 4, 'fakeTokensDecrypted': 2}


def main(argv=None):
    audit = Audit('unknown')
    try:
        parser = argparse.ArgumentParser(description='Isolated synthetic restore-rehearsal fixture')
        parser.add_argument('phase', choices=['seed', 'verify'])
        parser.add_argument('--proof-dir', default='/proof')
        parser.add_argument('--base-url', default='http://127.0.0.1:8000')
        args = parser.parse_args(argv)
        audit.phase = args.phase
        require(os.environ.get('FAMILY_DASHBOARD_SYNTHETIC_REHEARSAL') == '1')
        run_id = os.environ.get('REHEARSAL_RUN_ID', '')
        require(re.fullmatch('[0-9a-f]{32}', run_id))
        for name in ('DATA_DIR', 'SECRET_KEY', 'MEMBER1_PASSWORD', 'MEMBER2_PASSWORD', 'MICROSOFT_CLIENT_ID', 'MICROSOFT_CLIENT_SECRET'):
            require(bool(os.environ.get(name)))
        require(not os.environ.get('OPENAI_API_KEY') and not os.environ.get('OPENAI_MODEL'))
        require(os.environ.get('COOKIE_SECURE') == '0')
        origin = loopback_url(os.environ.get('PUBLIC_ORIGIN', ''))
        require(origin.scheme == 'https')
        parsed = loopback_url(args.base_url)
        require(parsed.scheme == 'http' and parsed.path in {'', '/'} and not parsed.query and not parsed.fragment)
        args.base_url = args.base_url.rstrip('/')
        data_dir, proof_dir = Path(os.environ['DATA_DIR']).resolve(), Path(args.proof_dir).resolve()
        require(data_dir.is_dir() and proof_dir.is_dir() and data_dir != proof_dir)
        expected_path = proof_dir / 'expected.json'
        with only_loopback(audit):
            counts = (seed if args.phase == 'seed' else verify)(args, audit, data_dir, expected_path, run_id)
        output = {'phase': audit.phase, 'passed': True, 'checks': audit.checks, 'checkCount': len(audit.checks), 'counts': counts,
                  'httpRequests': audit.requests, 'externalRequests': audit.external, 'providerRequestsInitiatedByFixture': 0,
                  'networkBoundary': 'Loopback-only client; callback uses error=access_denied and never follows redirects. Controller enforces Docker --network none.',
                  'restorePerformedByFixture': False, 'productionInputs': 0}
        print(json.dumps(output, ensure_ascii=False))
        return 0
    except BaseException as error:
        print(json.dumps({'phase': audit.phase, 'passed': False, 'stage': audit.stage, 'errorType': type(error).__name__,
                          'checks': audit.checks, 'checkCount': len(audit.checks), 'httpRequests': audit.requests,
                          'externalRequests': audit.external, 'restorePerformedByFixture': False}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
