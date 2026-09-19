"""Explicit private/shared journey routes and durable, metadata-only receipts."""
from datetime import datetime, timezone
from functools import wraps
import hashlib
import hmac
import json
import re
import secrets
import unicodedata

from flask import jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge

from finance_source_bridge import ImportSession
from journey_places import project_place


PREFIX = '/api/journey-routes'
MAX_STOPS = 100
MAX_ROUTES = 1000  # Per owner, including tombstones; successful receipts survive.
MAX_OPERATIONS = 10000
MAX_REQUEST_BYTES = 32 * 1024
SCHEMA_SQL = '''
CREATE TABLE IF NOT EXISTS journey_routes(
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    journey_id TEXT REFERENCES journey_workflows(id) ON DELETE SET NULL,
    visibility TEXT NOT NULL CHECK(visibility IN ('private','shared')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(typeof(revision)='integer' AND revision>=1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);
CREATE INDEX IF NOT EXISTS journey_routes_owner ON journey_routes(owner,updated_at,id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS journey_routes_journey ON journey_routes(journey_id,visibility) WHERE deleted_at IS NULL;
CREATE TABLE IF NOT EXISTS journey_route_stops(
    route_id TEXT NOT NULL REFERENCES journey_routes(id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK(typeof(position)='integer' AND position BETWEEN 0 AND 99),
    place_id TEXT REFERENCES journey_places(id) ON DELETE SET NULL,
    PRIMARY KEY(route_id,position)
);
CREATE TABLE IF NOT EXISTS journey_route_operations(
    owner TEXT NOT NULL REFERENCES users(id),
    request_id TEXT NOT NULL,
    payload_digest TEXT NOT NULL,
    operation TEXT NOT NULL CHECK(operation IN ('create','update','delete')),
    route_id TEXT NOT NULL REFERENCES journey_routes(id),
    result_revision INTEGER NOT NULL CHECK(typeof(result_revision)='integer' AND result_revision>=1),
    completed_at TEXT NOT NULL,
    PRIMARY KEY(owner,request_id)
);
'''


def initialize_journey_routes(con):
    """Three tables, no implicit transaction/commit; caller owns atomic DDL."""
    if con.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
        raise RuntimeError('Route initialization requires foreign keys')
    parents = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'users', 'journey_workflows', 'journey_places'} <= parents:
        raise RuntimeError('Route initialization requires users, journeys and places')
    for statement in SCHEMA_SQL.split(';'):
        if statement.strip():
            con.execute(statement)


class RouteError(Exception):
    def __init__(self, message='路线请求格式不正确', code='invalid_request', status=400):
        super().__init__(message)
        self.code, self.status = code, status


def fail(message='路线请求格式不正确', code='invalid_request', status=400):
    raise RouteError(message, code, status)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def identifier(value, length=24):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{' + str(length) + '}', value):
        fail('路线、地点或操作编号不正确')
    return value


def revision(value):
    if type(value) is not int or not 1 <= value < 2**53:
        fail('请提供有效版本')
    return value


def normalized(value, kind):
    required = {'requestId'}
    if kind != 'create':
        required |= {'revision', 'sourceVersion'}
    if kind != 'delete':
        required |= {'title', 'journeyId', 'expectedJourneyRevision', 'stops'}
        if kind == 'update':
            required.add('visibility')
    allowed = required | ({'visibility'} if kind == 'create' else set())
    if type(value) is not dict or not required <= value.keys() or value.keys() - allowed:
        fail()
    result = dict(value)
    identifier(result['requestId'], 32)
    if kind != 'create':
        revision(result['revision'])
        identifier(result['sourceVersion'], 64)
    if kind == 'delete':
        return result
    title = result['title']
    if (type(title) is not str or not 1 <= len(title.strip()) <= 160
            or any(unicodedata.category(char).startswith('C') for char in title)):
        fail('路线名称须为 1 至 160 字且不包含控制字符')
    result['title'] = title.strip()
    identifier(result['journeyId'])
    revision(result['expectedJourneyRevision'])
    result.setdefault('visibility', 'private')
    if result['visibility'] not in ('private', 'shared'):
        fail('请选择私人或家庭共享路线')
    stops = result['stops']
    if type(stops) is not list or not 1 <= len(stops) <= MAX_STOPS:
        fail('路线需要 1 至 100 个地点，可以重复往返')
    kept = set()
    for stop in stops:
        if type(stop) is not dict:
            fail()
        if stop.keys() == {'placeId', 'expectedRevision'}:
            identifier(stop['placeId'])
            revision(stop['expectedRevision'])
        elif kind == 'update' and stop.keys() == {'keepUnavailableIndex'}:
            index = stop['keepUnavailableIndex']
            if type(index) is not int or not 0 <= index < MAX_STOPS or index in kept:
                fail('不可用地点只能按原位置保留一次')
            kept.add(index)
        else:
            fail()
    return result


def journey(con, uid):
    if uid is None:
        return None
    row = con.execute("SELECT j.id,j.trip_id,j.revision,e.revision AS trip_revision,e.data "
                      "FROM journey_workflows j JOIN entities e ON e.id=j.trip_id AND e.kind='trips' WHERE j.id=?",
                      (uid,)).fetchone()
    return dict(row) if row else None


def visible_route(con, uid, owner, *, manage=False):
    row = con.execute('SELECT * FROM journey_routes WHERE id=?', (uid,)).fetchone()
    if not row or row['deleted_at'] or not (row['owner'] == owner or row['visibility'] == 'shared'):
        fail('路线不存在或不可见', 'not_found', 404)
    if manage and row['owner'] != owner:
        fail('只有路线创建者可以修改或删除', 'forbidden', 403)
    return row


def available(place, route, owner, source):
    return bool(source and place and not place['deleted_at']
                and place['journey_id'] == route['journey_id']
                and (place['visibility'] == 'shared'
                     or route['visibility'] == 'private' and place['owner'] == owner))


def route_context(con, row, owner, household, secret):
    """Resolve every stop in one DB snapshot; never retain a historic place DTO."""
    source = journey(con, row['journey_id'])
    stops = con.execute('SELECT * FROM journey_route_stops WHERE route_id=? ORDER BY position', (row['id'],)).fetchall()
    points = {stop['place_id']: con.execute('SELECT * FROM journey_places WHERE id=?', (stop['place_id'],)).fetchone()
              for stop in stops if stop['place_id'] is not None}
    # HMAC prevents hidden identifiers/low-entropy coordinates becoming guessable.
    content = {'owner': owner, 'household': household, 'route': dict(row), 'journey': source,
               'stops': [dict(stop) for stop in stops],
               'places': {key: dict(point) if point else None for key, point in points.items()}}
    version = hmac.new(secret, canonical(content).encode('utf-8'), hashlib.sha256).hexdigest()
    projected = []
    summary = {'id': source['id'], 'tripId': source['trip_id'], 'title': json.loads(source['data'])['title']} if source else None
    for stop in stops:
        point = points.get(stop['place_id'])
        value = {'index': stop['position'], 'state': 'unavailable'}
        if available(point, row, owner, source):
            value.update(state='available', place=project_place(point, owner, summary, shared=row['visibility'] == 'shared'))
        projected.append(value)
    segments = [{'fromIndex': left['index'], 'toIndex': right['index']} for left, right in zip(projected, projected[1:])
                if right['index'] == left['index'] + 1 and left['state'] == right['state'] == 'available'
                and left['place']['coordinates'] is not None and right['place']['coordinates'] is not None]
    result = {'route': {'id': row['id'], 'title': row['title'], 'journeyId': row['journey_id'],
                       'visibility': row['visibility'], 'revision': row['revision'], 'canManage': row['owner'] == owner,
                       'sourceVersion': version, 'stops': projected}, 'segments': segments}
    return result, stops


def operation(row):
    return {'requestId': row['request_id'], 'kind': row['operation'], 'routeId': row['route_id'],
            'resultRevision': row['result_revision'], 'completedAt': row['completed_at']}


def register_journey_routes(app, db, Problem, body, require_member):
    with app.app_context():
        con = db()
        if con.in_transaction:
            raise RuntimeError('Route registration requires a clean transaction')
        try:
            con.execute('BEGIN IMMEDIATE')
            initialize_journey_routes(con)
            con.commit()
        except BaseException:
            con.rollback()
            raise
    secret = app.config['SECRET_KEY']
    secret = secret.encode('utf-8') if isinstance(secret, str) else secret

    def guarded(view):
        @wraps(view)
        def run(*args, **kwargs):
            current = None
            try:
                current = ImportSession(app, db, Problem, require_member)
                response = view(current, *args, **kwargs)
                current.fresh()
                return response
            except (RouteError, Problem, RequestEntityTooLarge) as error:
                if current:
                    try:
                        current.fresh()
                    except Problem as changed:
                        error = changed
                status = getattr(error, 'status', 413)
                code = getattr(error, 'code', None) if isinstance(error, RouteError) else {
                    401: 'session_changed', 403: 'forbidden', 413: 'request_too_large', 503: 'session_unavailable'
                }.get(status, 'invalid_request')
                return jsonify(error=str(error) if isinstance(error, RouteError) else getattr(error, 'message', '请求过大'), code=code), status
        return run

    @app.after_request
    def journey_route_response(response):
        if request.path == PREFIX or request.path.startswith(PREFIX + '/'):
            response.headers['Cache-Control'] = 'no-store'
            if response.status_code >= 400 and response.is_json:
                value = response.get_json()
                if isinstance(value, dict) and 'error' in value and 'code' not in value:
                    value['code'] = {401: 'session_changed', 403: 'forbidden', 404: 'not_found',
                                     413: 'request_too_large', 415: 'invalid_request'}.get(response.status_code, 'invalid_request')
                    response.set_data(app.json.dumps(value))
        return response

    def context(con, row, current):
        return route_context(con, row, current.owner, current.household, secret)

    def receipt_response(con, receipt, current, replayed):
        row = con.execute('SELECT * FROM journey_routes WHERE id=? AND owner=?',
                          (receipt['route_id'], current.owner)).fetchone()
        result = context(con, row, current)[0] if row and not row['deleted_at'] else None
        return {'operation': operation(receipt), 'replayed': replayed, 'current': result}

    @app.get(PREFIX)
    @guarded
    def list_journey_routes(current):
        if set(request.args) - {'scope', 'journeyId', 'limit', 'offset'} or any(len(request.args.getlist(key)) != 1 for key in request.args):
            fail()
        scope = request.args.get('scope', 'visible')
        if scope not in ('visible', 'mine', 'shared'):
            fail()
        numbers = {}
        for key, default, low, high in (('limit', '100', 1, 100), ('offset', '0', 0, 10000)):
            value = request.args.get(key, default)
            if not re.fullmatch(r'0|[1-9]\d{0,5}', value) or not low <= int(value) <= high:
                fail('路线分页参数不正确')
            numbers[key] = int(value)
        clauses, args = ["deleted_at IS NULL", "(owner=? OR visibility='shared')"], [current.owner]
        if scope == 'mine':
            clauses.append('owner=?'); args.append(current.owner)
        elif scope == 'shared':
            clauses.append("visibility='shared'")
        if 'journeyId' in request.args:
            clauses.append('journey_id=?'); args.append(identifier(request.args['journeyId']))
        where = ' AND '.join(clauses)
        with current.read() as con:
            total = con.execute('SELECT count(*) FROM journey_routes WHERE ' + where, args).fetchone()[0]
            rows = con.execute('SELECT * FROM journey_routes WHERE ' + where + ' ORDER BY updated_at DESC,id LIMIT ? OFFSET ?',
                               [*args, numbers['limit'], numbers['offset']]).fetchall()
            items = []
            for row in rows:
                detail = context(con, row, current)[0]['route']
                items.append({**{key: detail[key] for key in ('id', 'title', 'journeyId', 'visibility', 'revision', 'canManage')},
                              'stopCount': len(detail['stops']),
                              'unavailableCount': sum(stop['state'] == 'unavailable' for stop in detail['stops'])})
        return jsonify(items=items, total=total, **numbers, hasMore=numbers['offset'] + len(items) < total)

    @app.get(PREFIX + '/operations/<request_id>')
    @guarded
    def journey_route_operation(current, request_id):
        identifier(request_id, 32)
        with current.read() as con:
            receipt = con.execute('SELECT * FROM journey_route_operations WHERE owner=? AND request_id=?',
                                  (current.owner, request_id)).fetchone()
            if not receipt:
                fail('操作记录不存在', 'not_found', 404)
            result = receipt_response(con, receipt, current, True)
        return jsonify(result)

    @app.get(PREFIX + '/<uid>')
    @guarded
    def journey_route_detail(current, uid):
        identifier(uid)
        with current.read() as con:
            result = context(con, visible_route(con, uid, current.owner), current)[0]
        return jsonify(result)

    def mutate(current, kind, uid=None):
        if uid is not None:
            identifier(uid)
        request.max_content_length = MAX_REQUEST_BYTES
        value = normalized(body(), kind)
        payload_digest = hashlib.sha256(canonical({'kind': kind, 'routeId': uid, 'value': value}).encode('utf-8')).hexdigest()
        replayed = False
        with current.write() as con:
            receipt = con.execute('SELECT * FROM journey_route_operations WHERE owner=? AND request_id=?',
                                  (current.owner, value['requestId'])).fetchone()
            if receipt:
                if not hmac.compare_digest(receipt['payload_digest'], payload_digest):
                    fail('此操作编号已用于不同请求，请核对原结果', 'request_conflict', 409)
                replayed = True
            else:
                previous, previous_stops, before = None, [], None
                if kind != 'create':
                    previous = visible_route(con, uid, current.owner, manage=True)
                    if previous['revision'] != value['revision']:
                        fail('路线已更新，请重新读取后核对', 'revision_conflict', 409)
                    before, previous_stops = context(con, previous, current)
                    if not hmac.compare_digest(before['route']['sourceVersion'], value['sourceVersion']):
                        fail('旅行或地点已变化，请重新读取后核对', 'source_changed', 409)
                if con.execute('SELECT count(*) FROM journey_route_operations WHERE owner=?', (current.owner,)).fetchone()[0] >= MAX_OPERATIONS:
                    fail('路线操作记录已达上限，已有成功操作仍可核对', 'limit_reached', 409)
                if kind == 'create' and con.execute('SELECT count(*) FROM journey_routes WHERE owner=?', (current.owner,)).fetchone()[0] >= MAX_ROUTES:
                    fail('路线记录已达上限，已有成功操作仍可核对', 'limit_reached', 409)
                stops = []
                if kind != 'delete':
                    source = journey(con, value['journeyId'])
                    if not source:
                        fail('旅行不存在或不可关联', 'not_found', 404)
                    if source['revision'] != value['expectedJourneyRevision']:
                        fail('旅行计划已更新，请重新核对', 'source_changed', 409)
                    target = {'journey_id': value['journeyId'], 'visibility': value['visibility']}
                    for stop in value['stops']:
                        if 'keepUnavailableIndex' in stop:
                            index = stop['keepUnavailableIndex']
                            if (previous['journey_id'] != value['journeyId'] or index >= len(previous_stops)
                                    or before['route']['stops'][index]['state'] != 'unavailable'
                                    or previous['visibility'] == 'private' and value['visibility'] == 'shared'):
                                fail('请重新核对不可用地点；首次共享须移除不可用地点', 'source_changed', 409)
                            stops.append(previous_stops[index]['place_id'])
                        else:
                            point = con.execute('SELECT * FROM journey_places WHERE id=?', (stop['placeId'],)).fetchone()
                            if not available(point, target, current.owner, source):
                                fail('地点不存在、已隐藏或未关联该旅行，请重新核对', 'source_changed', 409)
                            if point['revision'] != stop['expectedRevision']:
                                fail('地点已更新，请重新核对', 'source_changed', 409)
                            stops.append(point['id'])
                at = datetime.now(timezone.utc).isoformat(timespec='microseconds')
                result_revision = previous['revision'] + 1 if previous else 1
                if kind == 'create':
                    uid = secrets.token_hex(12)
                    con.execute('INSERT INTO journey_routes(id,owner,title,journey_id,visibility,revision,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                                (uid, current.owner, value['title'], value['journeyId'], value['visibility'], result_revision, at, at))
                elif kind == 'update':
                    con.execute('UPDATE journey_routes SET title=?,journey_id=?,visibility=?,revision=?,updated_at=? WHERE id=?',
                                (value['title'], value['journeyId'], value['visibility'], result_revision, at, uid))
                else:
                    con.execute("UPDATE journey_routes SET title='',journey_id=NULL,visibility='private',revision=?,updated_at=?,deleted_at=? WHERE id=?",
                                (result_revision, at, at, uid))
                con.execute('DELETE FROM journey_route_stops WHERE route_id=?', (uid,))
                con.executemany('INSERT INTO journey_route_stops(route_id,position,place_id) VALUES(?,?,?)',
                                [(uid, index, point) for index, point in enumerate(stops)])
                con.execute('INSERT INTO journey_route_operations(owner,request_id,payload_digest,operation,route_id,result_revision,completed_at) VALUES(?,?,?,?,?,?,?)',
                            (current.owner, value['requestId'], payload_digest, kind, uid, result_revision, at))
        # The receipt and changes committed together. Recovery always renders a
        # new authorized snapshot, even if the first response was lost.
        with current.read() as con:
            receipt = con.execute('SELECT * FROM journey_route_operations WHERE owner=? AND request_id=?',
                                  (current.owner, value['requestId'])).fetchone()
            result = receipt_response(con, receipt, current, replayed)
        return jsonify(result), 201 if kind == 'create' and not replayed else 200

    @app.post(PREFIX)
    @guarded
    def create_journey_route(current):
        return mutate(current, 'create')

    @app.put(PREFIX + '/<uid>')
    @guarded
    def update_journey_route(current, uid):
        return mutate(current, 'update', uid)

    @app.delete(PREFIX + '/<uid>')
    @guarded
    def delete_journey_route(current, uid):
        return mutate(current, 'delete', uid)
