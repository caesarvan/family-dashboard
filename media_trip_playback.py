"""Explicit per-TV journey scope and owner-only durable start receipts."""
import base64
from datetime import date
import hashlib
import hmac
import json
import re
import secrets
import sqlite3

from flask import g, jsonify, request
from household_media import MediaError, _request_object
import journey_routes
import media_playback_progress as progress

MAX_OPERATIONS = 10000
PREVIEW_SECONDS = 300

SCHEMA_SQL = '''
CREATE TABLE media_playback_journeys(
 device_id TEXT PRIMARY KEY NOT NULL REFERENCES media_playback(device_id) ON DELETE CASCADE,
 journey_id TEXT REFERENCES journey_workflows(id) ON DELETE SET NULL,
 route_id TEXT REFERENCES journey_routes(id) ON DELETE SET NULL,
 route_selected INTEGER NOT NULL CHECK(typeof(route_selected)='integer' AND route_selected IN (0,1)),
 started_by TEXT REFERENCES users(id) ON DELETE SET NULL,
 start_request_id TEXT NOT NULL CHECK(length(start_request_id)=32 AND start_request_id NOT GLOB '*[^0-9a-f]*'),
 created_at REAL NOT NULL CHECK(created_at>=0),
 updated_at REAL NOT NULL CHECK(updated_at>=0),
 CHECK(route_selected=1 OR route_id IS NULL));
CREATE TABLE media_playback_operations(
 owner TEXT NOT NULL REFERENCES users(id),
 request_id TEXT NOT NULL CHECK(length(request_id)=32 AND request_id NOT GLOB '*[^0-9a-f]*'),
 payload_digest TEXT NOT NULL CHECK(length(payload_digest)=64 AND payload_digest NOT GLOB '*[^0-9a-f]*'),
 device_id TEXT NOT NULL CHECK(length(device_id)=24 AND device_id NOT GLOB '*[^0-9a-f]*'),
 kind TEXT NOT NULL CHECK(kind='journey_start'),
 result_revision INTEGER NOT NULL CHECK(typeof(result_revision)='integer' AND result_revision BETWEEN 1 AND 9007199254740991),
 completed_at REAL NOT NULL CHECK(completed_at>=0),
 PRIMARY KEY(owner,request_id));
'''


def init_schema(con):
    """Caller owns an explicit foreign-key transaction, including atomic DDL."""
    if not con.in_transaction or con.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
        raise RuntimeError('Trip playback initialization requires an active foreign-key transaction')
    parents = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'users', 'media_playback', 'journey_workflows', 'journey_routes'} <= parents:
        raise RuntimeError('Trip playback initialization requires its parent tables')
    for statement in SCHEMA_SQL.split(';'):
        statement = statement.strip()
        if not statement:
            continue
        name = statement.split('(', 1)[0].split()[-1]
        row = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
        if row:
            if row[0].strip().rstrip(';') != statement:
                raise RuntimeError('Trip playback schema mismatch: '+name)
        else:
            con.execute(statement)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def identifier(value, length=24):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{'+str(length)+'}', value):
        raise MediaError('invalid_input')
    return value


def journey(con, uid):
    """A workflow and original trip must still refer to each other."""
    row = journey_routes.journey(con, uid)
    if row:
        try:
            value = json.loads(row['data'])
            if value.get('journeyId') != row['id'] or type(value.get('title')) is not str:
                return None
            for key in ('start', 'end'):
                if type(value.get(key)) is not str or date.fromisoformat(value[key]).isoformat() != value[key]:
                    return None
            return dict(id=row['id'], tripId=row['trip_id'], title=value['title'], start=value['start'],
                        end=value['end'], revision=row['revision'], tripRevision=row['trip_revision'])
        except (ValueError, TypeError, AttributeError):
            pass
    return None


class TripPlayback:
    def __init__(self, playback):
        self.playback, self.library = playback, playback.library

    def projection(self, con, uid, selection=None, *, all_photos=True):
        if selection is None:
            selection = con.execute('SELECT * FROM media_playback_journeys WHERE device_id=?', (uid,)).fetchone()
        if selection is None:
            return None, self.playback._photos(con, uid) if all_photos else []
        current = journey(con, selection['journey_id'])
        route, route_version = None, None
        status = 'unavailable' if selection['route_selected'] else 'not_selected'
        if current and selection['route_selected'] and selection['route_id']:
            row = con.execute("SELECT * FROM journey_routes WHERE id=? AND journey_id=? AND visibility='shared' AND deleted_at IS NULL",
                              (selection['route_id'], current['id'])).fetchone()
            if row:
                secret = self.library.app.secret_key
                if isinstance(secret, str):
                    secret = secret.encode('utf-8')
                # Always project the shared view, including for the route's author.
                detail, _ = journey_routes.route_context(con, row, '', self.library.household, secret)
                raw = detail['route']
                fields = ('id', 'name', 'country', 'city', 'coordinates', 'coordinatePrecision',
                          'coordinateGridDegrees', 'status', 'startDate', 'endDate')
                stops = []
                for stop in raw['stops']:
                    item = {'index': stop['index'], 'state': stop['state']}
                    if stop['state'] == 'available':
                        item['place'] = {key: stop['place'][key] for key in fields}
                    stops.append(item)
                route = dict(id=raw['id'], title=raw['title'], revision=raw['revision'],
                             stops=stops, segments=detail['segments'])
                route_version, status = raw['sourceVersion'], 'available'
        rows = self.playback._photos(con, uid, journey_id=current['id']) if current else []
        view = dict(status='ready' if current else 'journey_unavailable', journey=current,
                    routeStatus=status, route=route)
        view['sourceVersion'] = progress.mac(self.library, 'journey-source', uid, canonical({
            'view': view, 'routeVersion': route_version,
            'media': [(row['id'], row['revision']) for row in rows]}))
        return view, rows

    @staticmethod
    def can_start(review, rows):
        return bool(rows or review and review['route'] and
                    any(stop['state'] == 'available' for stop in review['route']['stops']))

    def control_dto(self, con, uid):
        self.playback._device(con, uid)
        state = self.playback._state(con, uid)
        review, rows = self.projection(con, uid)
        _, state['cursor'] = progress.resolve(self.library, con, state, rows)
        return self.playback._dto(state, len(rows), self.playback.clock(), review)

    def identity(self):
        actor, session = g.actor, g.member_session
        return progress.mac(self.library, 'journey-member', session['id'], actor['id'], actor['auth_version'])

    def preview(self, uid, value):
        identifier(uid)
        if type(value) is not dict or set(value) != {'revision', 'journeyId', 'routeId'}:
            raise MediaError('invalid_input')
        if type(value['revision']) is not int or not 0 <= value['revision'] < 9007199254740991:
            raise MediaError('invalid_input')
        identifier(value['journeyId'])
        if value['routeId'] is not None:
            identifier(value['routeId'])
        with self.library._suggestion_transaction() as con:
            self.playback._device(con, uid)
            state = self.playback._state(con, uid)
            if value['revision'] != state['revision']:
                raise MediaError('conflict')
            selection = dict(journey_id=value['journeyId'], route_id=value['routeId'], route_selected=int(value['routeId'] is not None))
            review, rows = self.projection(con, uid, selection)
            if not review['journey'] or review['routeStatus'] == 'unavailable':
                raise MediaError('not_found')
            now = self.playback.clock()
            payload = dict(deviceId=uid, identity=self.identity(), selection=value,
                           sourceVersion=review['sourceVersion'], issuedAt=now, expiresAt=now+PREVIEW_SECONDS)
            encoded = base64.urlsafe_b64encode(canonical(payload).encode()).decode().rstrip('=')
            token = encoded+'.'+progress.mac(self.library, 'journey-preview', encoded)
            return dict(previewToken=token, expiresAt=self.playback.iso(now+PREVIEW_SECONDS),
                        playbackRevision=state['revision'], sourceVersion=review['sourceVersion'],
                        journey=review['journey'], mediaCount=len(rows), routeStatus=review['routeStatus'],
                        route=review['route'], canStart=self.can_start(review, rows))

    def token(self, value, uid):
        encoded, signature = value.split('.')
        if not hmac.compare_digest(signature, progress.mac(self.library, 'journey-preview', encoded)):
            raise MediaError('invalid_input')
        try:
            token = json.loads(base64.urlsafe_b64decode(encoded+'='*(-len(encoded) % 4)))
        except (ValueError, UnicodeError):
            raise MediaError('invalid_input') from None
        if token['deviceId'] != uid or token['identity'] != self.identity():
            raise MediaError('forbidden')
        if not token['issuedAt'] <= self.playback.clock() < token['expiresAt']:
            raise MediaError('expired')
        return token

    def operation(self, row):
        return dict(requestId=row['request_id'], kind=row['kind'], deviceId=row['device_id'],
                    resultRevision=row['result_revision'], completedAt=self.playback.iso(row['completed_at']))

    def receipt_state(self, con, row):
        try:
            return self.control_dto(con, row['device_id'])
        except MediaError as error:
            if error.code == 'not_found':
                return None
            raise

    def start(self, uid, value):
        identifier(uid)
        if type(value) is not dict or set(value) != {'requestId', 'previewToken', 'confirmStart'}:
            raise MediaError('invalid_input')
        identifier(value['requestId'], 32)
        token = value['previewToken']
        if (value['confirmStart'] is not True or type(token) is not str or len(token) > 4096
                or not re.fullmatch(r'[A-Za-z0-9_-]+\.[0-9a-f]{64}', token)):
            raise MediaError('invalid_input')
        digest = hashlib.sha256(canonical(dict(deviceId=uid, **value)).encode()).hexdigest()
        with self.library._suggestion_transaction(True) as con:
            owner = self.library._member(con)
            prior = con.execute('SELECT * FROM media_playback_operations WHERE owner=? AND request_id=?',
                                (owner, value['requestId'])).fetchone()
            if prior:
                if not hmac.compare_digest(prior['payload_digest'], digest):
                    raise MediaError('conflict')
                return dict(operation=self.operation(prior), playback=self.receipt_state(con, prior), replayed=True)
            if con.execute('SELECT count(*) FROM media_playback_operations WHERE owner=?', (owner,)).fetchone()[0] >= MAX_OPERATIONS:
                raise MediaError('quota')
            payload = self.token(token, uid)
            self.playback._device(con, uid)
            state = self.playback._state(con, uid)
            selected = payload['selection']
            selection = dict(journey_id=selected['journeyId'], route_id=selected['routeId'], route_selected=int(selected['routeId'] is not None))
            review, rows = self.projection(con, uid, selection)
            if state['revision'] != selected['revision'] or review['sourceVersion'] != payload['sourceVersion']:
                raise MediaError('conflict')
            if not self.can_start(review, rows):
                raise MediaError('not_selected')
            now = self.playback.clock()
            state.update(mode='photos', paused=0, cursor=0, anchor_at=now, updated_at=now, revision=state['revision']+1)
            self.playback.save_state(con, state, state['revision']-1)
            con.execute('''INSERT INTO media_playback_journeys VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(device_id) DO UPDATE SET journey_id=excluded.journey_id,route_id=excluded.route_id,
                route_selected=excluded.route_selected,started_by=excluded.started_by,
                start_request_id=excluded.start_request_id,updated_at=excluded.updated_at''',
                (uid, selected['journeyId'], selected['routeId'], selection['route_selected'], owner, value['requestId'], now, now))
            if rows:
                row = rows[0]
                progress.save(con, dict(device_id=uid, item_id=row['id'], item_revision=row['revision'],
                    play_id=secrets.token_hex(12), position_ms=0, report_seq=0, reported_at=0))
            else:
                con.execute('DELETE FROM media_playback_progress WHERE device_id=?', (uid,))
            con.execute('INSERT INTO media_playback_operations VALUES(?,?,?,?,?,?,?)',
                        (owner, value['requestId'], digest, uid, 'journey_start', state['revision'], now))
            self.library._audit(con, owner, 'media_playback_journey_start', uid)
            row = con.execute('SELECT * FROM media_playback_operations WHERE owner=? AND request_id=?', (owner, value['requestId'])).fetchone()
            return dict(operation=self.operation(row), playback=self.control_dto(con, uid), replayed=False)

    def receipt(self, request_id):
        identifier(request_id, 32)
        with self.library._suggestion_transaction() as con:
            owner = self.library._member(con)
            row = con.execute('SELECT * FROM media_playback_operations WHERE owner=? AND request_id=?', (owner, request_id)).fetchone()
            if not row:
                return {'found': False}
            return dict(found=True, operation=self.operation(row), playback=self.receipt_state(con, row))


def register(app, playback):
    engine = playback.trip

    def call(method, *args):
        if request.args:
            raise MediaError('invalid_input')
        try:
            return jsonify(method(*args))
        except sqlite3.OperationalError as error:
            if 'locked' in str(error).lower() or 'busy' in str(error).lower():
                raise MediaError('unavailable') from None
            raise

    @app.post('/api/media-playback/devices/<uid>/journey-preview')
    def media_trip_preview(uid):
        return call(engine.preview, uid, _request_object())

    @app.post('/api/media-playback/devices/<uid>/journey-start')
    def media_trip_start(uid):
        return call(engine.start, uid, _request_object())

    @app.get('/api/media-playback/operations/<request_id>')
    def media_trip_operation(request_id):
        return call(engine.receipt, request_id)
