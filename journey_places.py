"""Member-owned manual places with explicit visit confirmation and safe projection.

Registration and schema initialization are explicit. No geocoding, external
requests, AI inference, TV projection or application wiring is performed here.
"""
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
import re
import secrets
import unicodedata

from flask import g, jsonify, request


MAX_PLACE_RECORDS = 3000  # Includes tombstones; receipts are never discarded.
SCHEMA_SQL = '''
CREATE TABLE IF NOT EXISTS journey_places(
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL REFERENCES users(id),
    request_id TEXT NOT NULL,
    payload_digest TEXT NOT NULL,
    name TEXT NOT NULL,
    country TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    latitude_e6 INTEGER,
    longitude_e6 INTEGER,
    status TEXT NOT NULL CHECK(status IN ('visited','planned','wish')),
    journey_id TEXT REFERENCES journey_workflows(id) ON DELETE SET NULL,
    start_date TEXT,
    end_date TEXT,
    visibility TEXT NOT NULL CHECK(visibility IN ('private','shared')),
    coordinate_disclosure TEXT NOT NULL CHECK(coordinate_disclosure IN ('hidden','coarse','exact')),
    visited_confirmed_at TEXT,
    visited_confirmed_by TEXT REFERENCES users(id),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>=1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT,
    UNIQUE(owner,request_id),
    CHECK((latitude_e6 IS NULL)=(longitude_e6 IS NULL)),
    CHECK(latitude_e6 IS NULL OR (typeof(latitude_e6)='integer' AND latitude_e6 BETWEEN -90000000 AND 90000000)),
    CHECK(longitude_e6 IS NULL OR (typeof(longitude_e6)='integer' AND longitude_e6 BETWEEN -180000000 AND 180000000)),
    CHECK(status!='visited' OR (visited_confirmed_at IS NOT NULL AND visited_confirmed_by IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS journey_places_owner
    ON journey_places(owner,updated_at,id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS journey_places_visibility
    ON journey_places(visibility,status,start_date) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS journey_places_journey
    ON journey_places(journey_id) WHERE deleted_at IS NULL;
CREATE TRIGGER IF NOT EXISTS journey_places_unlinked_revision
AFTER UPDATE OF journey_id ON journey_places
WHEN OLD.journey_id IS NOT NULL AND NEW.journey_id IS NULL
     AND NEW.revision=OLD.revision AND NEW.deleted_at IS NULL
BEGIN
    UPDATE journey_places SET revision=revision+1,
        updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=NEW.id;
END;
'''
BUSINESS_FIELDS = {'name', 'country', 'city', 'coordinates', 'status', 'journeyId',
                   'startDate', 'endDate', 'visibility', 'coordinateDisclosure'}
VISIT_FIELDS = ('name', 'country', 'city', 'latitude_e6', 'longitude_e6', 'journey_id', 'start_date', 'end_date')


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def initialize_journey_places(con):
    """Initialize only when explicitly called, after users/journey_workflows.

    Future deployment migration may use SCHEMA_SQL inside its own reviewed
    transaction. This helper owns a transaction and never commits caller work.
    """
    if con.in_transaction:
        raise RuntimeError('Place initialization requires a clean transaction')
    if con.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
        raise RuntimeError('Place initialization requires foreign keys enabled')
    parents = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('users','journey_workflows')")}
    if parents != {'users', 'journey_workflows'}:
        raise RuntimeError('Place initialization requires users and journeys')
    try:
        con.executescript('BEGIN IMMEDIATE;\n' + SCHEMA_SQL + '\nCOMMIT;')
    except Exception:
        con.rollback()
        raise


def coordinate_projection(row, disclosure):
    if row['latitude_e6'] is None:
        return None, 'none', None
    if disclosure == 'hidden':
        return None, 'hidden', None
    if disclosure == 'coarse':
        values = [float((Decimal(row[key]) / 100000).quantize(Decimal('1'), rounding=ROUND_HALF_UP) / 10)
                  for key in ('latitude_e6', 'longitude_e6')]
        return {'latitude': values[0], 'longitude': values[1]}, 'approximate', 0.1
    return {'latitude': row['latitude_e6'] / 1000000, 'longitude': row['longitude_e6'] / 1000000}, 'exact', None


def project_place(row, owner, journey_value, *, shared=False):
    own = row['owner'] == owner and not shared
    point, precision, grid = coordinate_projection(row, 'exact' if own else row['coordinate_disclosure'])
    result = {'id': row['id'], 'owner': row['owner'], 'name': row['name'], 'country': row['country'], 'city': row['city'],
              'coordinates': point, 'coordinatePrecision': precision, 'coordinateGridDegrees': grid,
              'coordinateDisclosure': row['coordinate_disclosure'], 'status': row['status'], 'journeyId': row['journey_id'],
              'journey': journey_value, 'startDate': row['start_date'], 'endDate': row['end_date'],
              'visibility': row['visibility'], 'visitedConfirmedAt': row['visited_confirmed_at'],
              'visitedConfirmedBy': row['visited_confirmed_by'], 'revision': row['revision'],
              'createdAt': row['created_at'], 'updatedAt': row['updated_at'], 'canManage': own}
    if own:
        shared, shared_precision, shared_grid = coordinate_projection(row, row['coordinate_disclosure'])
        result.update(sharedCoordinates=shared, sharedCoordinatePrecision=shared_precision, sharedCoordinateGridDegrees=shared_grid)
    return result


def register_journey_places(app, db, Problem, body, require_member, audit):
    with app.app_context():
        initialize_journey_places(db())

    @contextmanager
    def transaction(write=False):
        con = db()
        try:
            con.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            require_member()
            engine = app.extensions.get('member_sessions')
            if engine is None:
                raise Problem('暂时无法核对登录状态，请稍后重试', 503)
            current = engine.current(con)
            household = app.config.get('HOUSEHOLD_INFO', {}).get('id', 'default')
            if (current['owner'] != g.actor['id'] or current['auth_version'] != g.actor.get('auth_version')
                    or household != g.actor.get('householdId')):
                raise Problem('登录或家庭已变化，请重新打开', 401)
            yield con, current['owner']
            con.commit()
        except Exception:
            con.rollback()
            raise

    def fields(value, allowed, required=()):
        if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
            raise Problem('地点字段不完整或包含不支持的字段')

    def text(value, label, maximum, empty=False):
        if not isinstance(value, str) or any(unicodedata.category(c).startswith('C') for c in value):
            raise Problem(label + '格式不正确')
        value = value.strip()
        if len(value) > maximum or not empty and not value:
            raise Problem(label + '长度不正确')
        return value

    def enum(value, choices, label):
        if not isinstance(value, str) or value not in choices:
            raise Problem(label + '不正确')
        return value

    def identifier(value, nullable=False):
        if nullable and value is None:
            return None
        if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{24}', value):
            raise Problem('地点或旅行编号不正确')
        return value

    def revision(value):
        if type(value) is not int or not 1 <= value <= 2**53 - 1:
            raise Problem('地点版本不正确')
        return value

    def day(value, label):
        if value in (None, ''):
            return None
        if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            raise Problem(label + '应为 YYYY-MM-DD')
        try:
            date.fromisoformat(value)
        except ValueError:
            raise Problem(label + '不正确') from None
        return value

    def coordinates(value):
        if value is None:
            return None, None
        fields(value, {'latitude', 'longitude'}, {'latitude', 'longitude'})
        result = []
        for key, bound in (('latitude', 90), ('longitude', 180)):
            incoming = value[key]
            if type(incoming) not in (int, float):
                raise Problem('坐标须为有限数字，最多六位小数')
            try:
                number = Decimal(str(incoming))
                scaled = number * 1000000
                if not number.is_finite() or abs(number) > bound or scaled != scaled.to_integral_value():
                    raise ValueError
                result.append(int(scaled))
            except (InvalidOperation, ValueError, OverflowError):
                raise Problem('坐标超出范围或超过六位小数') from None
        return tuple(result)

    def normalized(value, previous=None):
        if previous is None:
            defaults = {'name': '', 'country': '', 'city': '', 'coordinates': None, 'status': 'wish',
                        'journeyId': None, 'startDate': None, 'endDate': None,
                        'visibility': 'private', 'coordinateDisclosure': 'hidden'}
        else:
            defaults = {'name': previous['name'], 'country': previous['country'], 'city': previous['city'],
                        'coordinates': coordinate_projection(previous, 'exact')[0], 'status': previous['status'],
                        'journeyId': previous['journey_id'], 'startDate': previous['start_date'], 'endDate': previous['end_date'],
                        'visibility': previous['visibility'], 'coordinateDisclosure': previous['coordinate_disclosure']}
        merged = {**defaults, **{key: value[key] for key in BUSINESS_FIELDS if key in value}}
        lat, lng = coordinates(merged['coordinates'])
        start, end = day(merged['startDate'], '开始日期'), day(merged['endDate'], '结束日期')
        if end is not None and (start is None or end < start):
            raise Problem('结束日期须不早于开始日期，且需要开始日期')
        confirm = value.get('confirmVisited', False)
        if type(confirm) is not bool:
            raise Problem('到访确认须为布尔值')
        clean = {'name': text(merged['name'], '地点名称', 160), 'country': text(merged['country'], '国家或地区', 100, True),
                 'city': text(merged['city'], '城市', 100, True), 'latitude_e6': lat, 'longitude_e6': lng,
                 'status': enum(merged['status'], ('visited', 'planned', 'wish'), '地点状态'),
                 'journey_id': identifier(merged['journeyId'], True), 'start_date': start, 'end_date': end,
                 'visibility': enum(merged['visibility'], ('private', 'shared'), '共享范围'),
                 'coordinate_disclosure': enum(merged['coordinateDisclosure'], ('hidden', 'coarse', 'exact'), '坐标共享方式')}
        if confirm and clean['status'] != 'visited':
            raise Problem('只有已到访状态可以确认到访')
        needs_confirmation = clean['status'] == 'visited' and (previous is None or previous['status'] != 'visited'
                            or any(clean[key] != previous[key] for key in VISIT_FIELDS))
        if needs_confirmation and not confirm:
            raise Problem('请明确确认到访事实；地点或日期改变后需要重新确认')
        return clean, confirm

    def journey(con, uid):
        if uid is None:
            return None
        row = con.execute("SELECT j.id,j.trip_id,e.data FROM journey_workflows j JOIN entities e ON e.id=j.trip_id AND e.kind='trips' WHERE j.id=?", (uid,)).fetchone()
        if not row:
            raise Problem('旅行不存在或不可关联', 404)
        data = json.loads(row['data'])
        return {'id': row['id'], 'tripId': row['trip_id'], 'title': data['title']}

    def source_revision(value):
        if 'expectedJourneyRevision' not in value:
            return None
        return revision(value['expectedJourneyRevision'])

    def check_source_revision(con, uid, expected):
        if expected is None:
            return
        if uid is None:
            raise Problem('旅行版本核对必须指定关联旅行')
        row = con.execute('SELECT revision FROM journey_workflows WHERE id=?', (uid,)).fetchone()
        if row is None:
            raise Problem('旅行不存在或不可关联', 404)
        if row['revision'] != expected:
            raise Problem('旅行计划已更新，请核对最新旅行后再保存地点', 409)

    def visible_row(con, uid, owner, manage=False, include_deleted=False):
        identifier(uid)
        row = con.execute('SELECT * FROM journey_places WHERE id=?', (uid,)).fetchone()
        if (row is None or not (row['owner'] == owner or row['visibility'] == 'shared')
                or row['deleted_at'] and (not include_deleted or row['owner'] != owner)):
            raise Problem('地点不存在或不可见', 404)
        if manage and row['owner'] != owner:
            raise Problem('只有创建者可以修改或删除地点', 403)
        return row

    def serialize(con, row, owner):
        return project_place(row, owner, journey(con, row['journey_id']))

    @app.get('/api/journey-places')
    def list_journey_places():
        require_member()
        allowed = {'status', 'year', 'owner', 'journeyId', 'scope', 'limit', 'offset'}
        if set(request.args) - allowed or any(len(request.args.getlist(key)) != 1 for key in request.args):
            raise Problem('地点筛选参数不正确')
        scope = enum(request.args.get('scope', 'visible'), ('mine', 'shared', 'visible'), '列表范围')
        numeric = {}
        for key, default, low, high in (('limit', '100', 1, 200), ('offset', '0', 0, MAX_PLACE_RECORDS)):
            value = request.args.get(key, default)
            if not re.fullmatch(r'0|[1-9]\d{0,5}', value) or not low <= int(value) <= high:
                raise Problem('地点分页参数不正确')
            numeric[key] = int(value)
        with transaction() as (con, owner):
            clauses, args = ["deleted_at IS NULL", "(owner=? OR visibility='shared')"], [owner]
            if scope == 'mine':
                clauses.append('owner=?'); args.append(owner)
            elif scope == 'shared':
                clauses.append("visibility='shared'")
            if 'status' in request.args:
                clauses.append('status=?'); args.append(enum(request.args['status'], ('visited', 'planned', 'wish'), '地点状态'))
            if 'owner' in request.args:
                member = request.args['owner']
                if not con.execute('SELECT 1 FROM users WHERE id=?', (member,)).fetchone():
                    raise Problem('成员筛选不正确')
                clauses.append('owner=?'); args.append(member)
            if 'journeyId' in request.args:
                uid = identifier(request.args['journeyId'])
                journey(con, uid)
                clauses.append('journey_id=?'); args.append(uid)
            if 'year' in request.args:
                year = request.args['year']
                if not re.fullmatch(r'\d{4}', year) or int(year) < 1:
                    raise Problem('年份筛选不正确')
                clauses.extend(('start_date<=?', 'COALESCE(end_date,start_date)>=?'))
                args.extend((year + '-12-31', year + '-01-01'))
            where = ' AND '.join(clauses)
            total = con.execute('SELECT count(*) FROM journey_places WHERE ' + where, args).fetchone()[0]
            rows = con.execute('SELECT * FROM journey_places WHERE ' + where + ' ORDER BY updated_at DESC,id LIMIT ? OFFSET ?',
                               args + [numeric['limit'], numeric['offset']]).fetchall()
            return jsonify(items=[serialize(con, row, owner) for row in rows], total=total, **numeric,
                           hasMore=numeric['offset'] + len(rows) < total)

    @app.get('/api/journey-places/<uid>')
    def get_journey_place(uid):
        with transaction() as (con, owner):
            return jsonify(place=serialize(con, visible_row(con, uid, owner), owner))

    @app.post('/api/journey-places')
    def create_journey_place():
        value = body()
        fields(value, BUSINESS_FIELDS | {'requestId', 'confirmVisited', 'expectedJourneyRevision'}, {'requestId', 'name'})
        key = value['requestId']
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,100}', key):
            raise Problem('创建请求标识不正确')
        clean, confirm = normalized(value)
        expected = source_revision(value)
        if expected is not None and clean['journey_id'] is None:
            raise Problem('旅行版本核对必须指定关联旅行')
        intent = {'place': clean, 'confirmVisited': confirm}
        # Do not change legacy digests. The optional source revision is part of
        # a new intent, so a retry cannot silently adopt a different plan.
        if expected is not None:
            intent['expectedJourneyRevision'] = expected
        digest = hashlib.sha256(json.dumps(intent, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        with transaction(True) as (con, owner):
            # The receipt precedes mutable parent validation: unlink cannot
            # invalidate replay or cause the original request to create again.
            existing = con.execute('SELECT * FROM journey_places WHERE owner=? AND request_id=?', (owner, key)).fetchone()
            if existing:
                if existing['payload_digest'] != digest:
                    raise Problem('相同创建请求不能使用不同的地点内容', 409)
                if existing['deleted_at']:
                    raise Problem('该创建请求对应的地点已删除，不能重复创建', 410)
                return jsonify(place=serialize(con, existing, owner), replayed=True)
            journey(con, clean['journey_id'])
            check_source_revision(con, clean['journey_id'], expected)
            if con.execute('SELECT count(*) FROM journey_places').fetchone()[0] >= MAX_PLACE_RECORDS:
                raise Problem('地点记录及历史创建回执已达上限，请联系维护者处理', 409)
            uid, now = secrets.token_hex(12), stamp()
            data = {**clean, 'id': uid, 'owner': owner, 'request_id': key, 'payload_digest': digest,
                    'visited_confirmed_at': now if confirm else None, 'visited_confirmed_by': owner if confirm else None,
                    'created_at': now, 'updated_at': now}
            keys = list(data)
            con.execute('INSERT INTO journey_places(' + ','.join(keys) + ') VALUES(' + ','.join('?' for _ in keys) + ')', [data[k] for k in keys])
            audit('journey_place_created', uid)
            return jsonify(place=serialize(con, visible_row(con, uid, owner), owner), replayed=False), 201

    @app.patch('/api/journey-places/<uid>')
    def update_journey_place(uid):
        value = body()
        fields(value, BUSINESS_FIELDS | {'revision', 'confirmVisited', 'expectedJourneyRevision'}, {'revision'})
        incoming_revision = revision(value['revision'])
        expected = source_revision(value)
        if not (set(value) & BUSINESS_FIELDS or value.get('confirmVisited') is True):
            raise Problem('请提供要修改的地点内容')
        with transaction(True) as (con, owner):
            row = visible_row(con, uid, owner, manage=True)
            if row['revision'] != incoming_revision:
                raise Problem('地点已更新，请重新读取后再保存', 409)
            clean, confirm = normalized(value, row)
            journey(con, clean['journey_id'])
            check_source_revision(con, clean['journey_id'], expected)
            now = stamp()
            confirmed_at, confirmed_by = row['visited_confirmed_at'], row['visited_confirmed_by']
            if clean['status'] != 'visited':
                confirmed_at, confirmed_by = None, None
            elif confirm:
                confirmed_at, confirmed_by = now, owner
            changed = {**clean, 'visited_confirmed_at': confirmed_at, 'visited_confirmed_by': confirmed_by}
            if any(changed[key] != row[key] for key in changed):
                columns = list(changed)
                con.execute('UPDATE journey_places SET ' + ','.join(key + '=?' for key in columns) + ',revision=revision+1,updated_at=? WHERE id=? AND owner=? AND revision=?',
                            [changed[key] for key in columns] + [now, uid, owner, incoming_revision])
                audit('journey_place_updated', uid)
            return jsonify(place=serialize(con, visible_row(con, uid, owner), owner))

    @app.delete('/api/journey-places/<uid>')
    def delete_journey_place(uid):
        value = body()
        fields(value, {'revision'}, {'revision'})
        incoming_revision = revision(value['revision'])
        with transaction(True) as (con, owner):
            row = visible_row(con, uid, owner, manage=True, include_deleted=True)
            if row['deleted_at']:
                if incoming_revision != row['revision'] - 1:
                    raise Problem('地点删除版本不匹配', 409)
                return jsonify(deleted=True, id=uid, revision=row['revision'], replayed=True)
            if row['revision'] != incoming_revision:
                raise Problem('地点已更新，请重新读取后再删除', 409)
            now = stamp()
            # Only the durable request receipt remains; location data is erased.
            con.execute("UPDATE journey_places SET name='',country='',city='',latitude_e6=NULL,longitude_e6=NULL,status='wish',"
                        "journey_id=NULL,start_date=NULL,end_date=NULL,visibility='private',coordinate_disclosure='hidden',"
                        "visited_confirmed_at=NULL,visited_confirmed_by=NULL,revision=revision+1,updated_at=?,deleted_at=? WHERE id=? AND owner=? AND revision=?",
                        (now, now, uid, owner, incoming_revision))
            audit('journey_place_deleted', uid)
            return jsonify(deleted=True, id=uid, revision=incoming_revision + 1, replayed=False)
