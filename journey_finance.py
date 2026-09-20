"""Private allocations of existing net payments to original shared journeys.

This is a separate owner view, never another ledger or a shared paid projection.
Source/target IDs deliberately survive deletion; receipts never store their text.
"""
from datetime import datetime, timedelta, timezone
from functools import wraps
import hashlib
import json
import re
import secrets
import sqlite3

from flask import jsonify, request
from itsdangerous import BadSignature, URLSafeTimedSerializer

from finance_hub import reconciliation_rows
from finance_source_bridge import ImportSession

PREFIX = '/api/finance-hub/journey-allocations'
PAGE_SIZE = 40
PREVIEW_SECONDS = 600
MAX_AMOUNT = 100_000_000_000
MAX_REVISION = 9007199254740991
MAX_ALLOCATIONS = 20000
MAX_OPERATIONS = 40000
MAX_OPERATION_BYTES = 32 * 1024 * 1024
RECEIPT_RESERVE = 1024
SCHEMA_SQL = '''
CREATE TABLE IF NOT EXISTS hub_journey_allocations(
 id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id),
 journey_id TEXT NOT NULL, trip_id TEXT NOT NULL, payment_id TEXT NOT NULL,
 amount_cents INTEGER NOT NULL CHECK(typeof(amount_cents)='integer' AND amount_cents BETWEEN 1 AND 100000000000),
 status TEXT NOT NULL CHECK(status IN ('active','revoked')),
 revision INTEGER NOT NULL DEFAULT 1 CHECK(typeof(revision)='integer' AND revision>0),
 source_digest TEXT NOT NULL, accepted_net_cents INTEGER NOT NULL,
 accepted_refunded_cents INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS hub_journey_allocations_active
 ON hub_journey_allocations(owner,journey_id,payment_id) WHERE status='active';
CREATE INDEX IF NOT EXISTS hub_journey_allocations_payment ON hub_journey_allocations(owner,payment_id,status);
CREATE INDEX IF NOT EXISTS hub_journey_allocations_journey ON hub_journey_allocations(owner,journey_id,status);
CREATE INDEX IF NOT EXISTS hub_journey_allocations_created ON hub_journey_allocations(owner,created_at,id);
CREATE TABLE IF NOT EXISTS hub_journey_allocation_operations(
 owner TEXT NOT NULL REFERENCES users(id), request_id TEXT NOT NULL, payload_hash TEXT NOT NULL,
 operation TEXT NOT NULL, allocation_id TEXT NOT NULL, result TEXT NOT NULL, completed_at TEXT NOT NULL,
 PRIMARY KEY(owner,request_id));
'''


def init_schema(con):
    """Caller owns the DDL transaction; never commit or initialize on a GET."""
    if not con.in_transaction or con.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
        raise RuntimeError('Journey finance initialization requires a foreign-key transaction')
    for statement in SCHEMA_SQL.split(';'):
        if statement.strip():
            con.execute(statement)


class JourneyFinanceError(ValueError):
    def __init__(self, message, code='invalid_request', status=400):
        super().__init__(message)
        self.code, self.status = 'journey_finance_' + code, status


def fail(message='请求字段或格式不正确', code='invalid_request', status=400):
    raise JourneyFinanceError(message, code, status)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def identifier(value, length=None):
    pattern = '[a-f0-9]{%s}' % length if length else r'[A-Za-z0-9_-]{1,100}'
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        fail()
    return value


def integer(value, maximum=MAX_REVISION, minimum=1):
    if type(value) is not int or not minimum <= value <= maximum:
        fail('金额或版本须为有效整数')
    return value


def normalized(value):
    fields = {'apply': {'operation', 'journeyId', 'journeyRevision', 'tripRevision', 'paymentId', 'paymentRevision', 'amountCents'},
              'update': {'operation', 'allocationId', 'revision', 'journeyRevision', 'tripRevision', 'paymentRevision', 'amountCents'},
              'revoke': {'operation', 'allocationId', 'revision'}}
    operation = value.get('operation')
    if not isinstance(operation, str) or operation not in fields or set(value) != fields[operation]:
        fail()
    if operation == 'apply':
        identifier(value['journeyId'], 24)
        identifier(value['paymentId'])
    else:
        identifier(value['allocationId'], 32)
        integer(value['revision'])
    if operation != 'revoke':
        for key in ('journeyRevision', 'tripRevision', 'paymentRevision'):
            integer(value[key])
        integer(value['amountCents'], MAX_AMOUNT)
    return dict(value)


def stored_allocation(row):
    fields = {'id': 'id', 'revision': 'revision', 'journeyId': 'journey_id', 'tripId': 'trip_id',
              'paymentId': 'payment_id', 'amountCents': 'amount_cents', 'status': 'status',
              'acceptedNetCents': 'accepted_net_cents', 'acceptedRefundedCents': 'accepted_refunded_cents',
              'createdAt': 'created_at', 'updatedAt': 'updated_at'}
    return {key: row[column] for key, column in fields.items()}


def export_owned_allocations(con, owner):
    allocations = [stored_allocation(row) for row in con.execute(
        'SELECT * FROM hub_journey_allocations WHERE owner=? ORDER BY id', (owner,))]
    operations = []
    for row in con.execute('SELECT result FROM hub_journey_allocation_operations WHERE owner=? ORDER BY completed_at,request_id', (owner,)):
        value = json.loads(row['result'])
        operations.append({key: value[key] for key in ('operation', 'allocationId', 'revision', 'completedAt')})
    return {'allocations': allocations, 'operations': operations}


def load(con, owner):
    raw = {r['id']: dict(r) for r in con.execute(
        'SELECT id,data,revision FROM hub_transactions WHERE owner=? ORDER BY id', (owner,))}
    records = [{**json.loads(r['data']), 'id': r['id'], 'revision': r['revision']} for r in raw.values()]
    relations = [dict(r) for r in con.execute('SELECT * FROM hub_reconciliations WHERE owner=? ORDER BY id', (owner,))]
    invalid = {r['id'] for r in records if type(r.get('amountCents')) is not int or not 0 <= r['amountCents'] <= MAX_AMOUNT}
    for relation in relations:
        if relation['status'] == 'active' and (type(relation['amount_cents']) is not int or relation['amount_cents'] < 0):
            invalid.update((relation['left_id'], relation['right_id']))
    # A broken neighbor must not silently remove a refund from an otherwise
    # usable payment. Preserve raw rows for fingerprints, exclude unsafe math.
    neighbors = {}
    for relation in relations:
        if relation['status'] == 'active':
            neighbors.setdefault(relation['left_id'], set()).add(relation['right_id'])
            neighbors.setdefault(relation['right_id'], set()).add(relation['left_id'])
    pending = list(invalid)
    while pending:
        for rid in neighbors.get(pending.pop(), set()) - invalid:
            invalid.add(rid)
            pending.append(rid)
    safe_records = [r for r in records if r['id'] not in invalid]
    safe_relations = [r for r in relations if not invalid.intersection((r['left_id'], r['right_id']))]
    links = [dict(r) for r in con.execute('SELECT * FROM hub_journey_allocations WHERE owner=? ORDER BY id', (owner,))]
    sources, reserved = {}, {}
    for relation in relations:
        if relation['status'] == 'active':
            for rid in {relation['left_id'], relation['right_id']}:
                sources.setdefault(rid, []).append(relation)
    for link in links:
        if link['status'] == 'active':
            reserved[link['payment_id']] = reserved.get(link['payment_id'], 0) + link['amount_cents']
    journeys = {}
    for r in con.execute("SELECT j.id,j.trip_id,j.revision,t.revision AS trip_revision,t.data FROM journey_workflows j "
                         "JOIN entities t ON t.id=j.trip_id AND t.kind='trips' ORDER BY j.id"):
        trip = json.loads(r['data'])
        if trip.get('journeyId') != r['id']:
            continue
        journeys[r['id']] = {'id': r['id'], 'tripId': r['trip_id'], 'revision': r['revision'],
            'tripRevision': r['trip_revision'], 'title': trip['title'], 'sharedBudgetCents': trip['budget'],
            'sharedManualPaidCents': trip['paid'], 'sharedSavedCents': trip['saved']}
    return {'raw': raw, 'payments': {r['id']: r for r in reconciliation_rows(safe_records, safe_relations)}, 'invalid': invalid,
            'source_relations': sources, 'links': links, 'links_by_id': {r['id']: r for r in links},
            'reserved': reserved, 'journeys': journeys, 'digests': {}}


def source_digest(state, pid):
    if pid not in state['digests']:
        relations = state['source_relations'].get(pid, [])
        neighbors = {pid}
        for relation in relations:
            neighbors.update((relation['left_id'], relation['right_id']))
        state['digests'][pid] = digest({'records': [state['raw'].get(key) for key in sorted(neighbors)], 'relations': relations})
    return state['digests'][pid]


def payment(state, pid, excluding=None):
    if pid in state['invalid']:
        fail('来源金额异常，请先核对原账单', 'ineligible', 409)
    row = state['payments'].get(pid)
    if row is None or row['kind'] != 'payments':
        return None
    amount, refunded = row['amountCents'], row['reconciliation']['refundedCents']
    if (type(amount) is not int or type(refunded) is not int or not 0 <= refunded <= amount <= MAX_AMOUNT):
        fail('来源金额异常，请先核对原账单', 'ineligible', 409)
    reserved = state['reserved'].get(pid, 0)
    link = state['links_by_id'].get(excluding)
    if link and link['status'] == 'active' and link['payment_id'] == pid:
        reserved -= link['amount_cents']
    reason = ('not_expense' if row['flow'] != 'expense' else 'duplicate' if row['reconciliation']['duplicateOf']
              else 'unsupported_currency' if row['currency'] != 'CNY' else None)
    return {**{key: row[key] for key in ('id', 'revision', 'date', 'title', 'kind', 'flow', 'currency', 'amountCents')},
            'refundedCents': refunded, 'netCents': amount - refunded, 'reservedCents': reserved,
            'availableCents': max(0, amount - refunded - reserved), 'eligible': reason is None, 'reasonCode': reason}


def projection(state, row):
    value = stored_allocation(row)
    journey = state['journeys'].get(row['journey_id'])
    if journey and journey['tripId'] != row['trip_id']:
        journey = None
    reasons = []
    try:
        pay = payment(state, row['payment_id'])
    except JourneyFinanceError:
        pay = None
        if row['status'] == 'active':
            reasons.append('source_ineligible')
    if row['status'] == 'active':
        if journey is None:
            reasons.append('journey_missing')
        if pay is None:
            if 'source_ineligible' not in reasons:
                reasons.append('source_missing')
        else:
            if source_digest(state, pay['id']) != row['source_digest']:
                reasons.append('source_changed')
            if not pay['eligible']:
                reasons.append('source_ineligible')
            if pay['reservedCents'] > pay['netCents']:
                reasons.append('payment_overallocated')
    value.update(state='revoked' if row['status'] == 'revoked' else 'needs_review' if reasons else 'current',
                 reasonCodes=reasons, journey=journey, payment=pay)
    return value


def owned(state, rid):
    row = state['links_by_id'].get(rid)
    if row is None:
        fail('归集不存在', 'not_found', 404)
    return row


def assess(state, plan):
    operation = plan['operation']
    link = owned(state, plan['allocationId']) if operation != 'apply' else None
    if link and (link['status'] != 'active' or link['revision'] != plan['revision']):
        fail('归集已改变，请重新读取并预览', 'stale', 409)
    jid, pid = (link['journey_id'], link['payment_id']) if link else (plan['journeyId'], plan['paymentId'])
    journey = state['journeys'].get(jid)
    if link and journey and journey['tripId'] != link['trip_id']:
        journey = None
    try:
        pay = payment(state, pid, link['id'] if link else None)
    except JourneyFinanceError:
        if operation != 'revoke':
            raise
        pay = None
    if operation == 'revoke':
        dependencies = {'link': digest(link)}
    else:
        if journey is None or pay is None:
            fail('旅行或本人付款不存在', 'not_found', 404)
        if (journey['revision'] != plan['journeyRevision'] or journey['tripRevision'] != plan['tripRevision']
                or pay['revision'] != plan['paymentRevision']):
            fail('旅行或付款已改变，请重新读取并预览', 'stale', 409)
        if not pay['eligible']:
            fail('请选择本人有效的人民币实际消费付款', 'ineligible', 409)
        if not link and any(r['journey_id'] == jid and r['payment_id'] == pid and r['status'] == 'active' for r in state['links']):
            fail('已有有效归集，请更新或解除原关联', 'active_exists', 409)
        if plan['amountCents'] + pay['reservedCents'] > pay['netCents']:
            fail('所有旅行归集合计超过该付款净额，请调整或解除原关联', 'capacity', 409)
        reservations = [r for r in state['links'] if r['payment_id'] == pid and r['status'] == 'active']
        dependencies = {'source': source_digest(state, pid), 'reservations': digest(reservations),
                        'journey': digest(journey), 'link': digest(link)}
    output = {'version': 1, 'operation': operation, 'allocationId': link['id'] if link else None,
              'journey': journey, 'payment': pay, 'beforeAllocatedCents': link['amount_cents'] if link else 0,
              'afterAllocatedCents': 0 if operation == 'revoke' else plan['amountCents'],
              'beforeStatus': 'active' if link else None, 'afterStatus': 'revoked' if operation == 'revoke' else 'active',
              'unchanged': {'ledger': True, 'shopping': True, 'sharedTrip': True},
              'warnings': ['仅本人已归集，不代表家庭实际总费用；共享预算、手填已付和采购实付不相加。',
                           '净额仅扣除已明确关联的退款；未核对的退款与疑似重复不会自动处理。']}
    return link, jid, pid, dependencies, output


def register_journey_finance(app, db, Problem, body, require_member, audit, *, initialize=True):
    if initialize:
        with app.app_context():
            con = db()
            if con.in_transaction:
                raise RuntimeError('Journey finance registration requires a clean transaction')
            try:
                con.execute('BEGIN IMMEDIATE')
                init_schema(con)
                con.commit()
            except BaseException:
                con.rollback()
                raise
    signer = URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='journey-finance-preview-v1')

    def guarded(view):
        @wraps(view)
        def run(*args, **kwargs):
            current = None
            try:
                current = ImportSession(app, db, Problem, require_member)
                result = view(current, *args, **kwargs)
                current.fresh()
                return result
            except (JourneyFinanceError, Problem, sqlite3.OperationalError) as exc:
                if isinstance(exc, sqlite3.OperationalError):
                    if getattr(exc, 'sqlite_errorcode', 0) & 255 not in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
                        raise
                    exc = JourneyFinanceError('正在处理另一项操作，请稍后核对原请求', 'unavailable', 503)
                if current:
                    try:
                        current.fresh()
                    except Problem as changed:
                        exc = changed
                code = getattr(exc, 'code', {401: 'session_changed', 403: 'forbidden', 503: 'session_unavailable'}.get(exc.status, 'journey_finance_invalid_request'))
                return jsonify(error=str(exc) if isinstance(exc, JourneyFinanceError) else exc.message, code=code), exc.status
        return run

    @app.after_request
    def private_response(response):
        if request.path == PREFIX or request.path.startswith(PREFIX + '/'):
            response.headers['Cache-Control'] = 'private, no-store'
        return response

    def query(allowed):
        if set(request.args) - set(allowed) or any(len(request.args.getlist(k)) != 1 for k in request.args):
            fail()
        raw = request.args.get('page', '0')
        if not re.fullmatch(r'0|[1-9][0-9]{0,8}', raw):
            fail()
        return int(raw)

    def page_info(rows, page):
        return {'page': page, 'pageSize': PAGE_SIZE, 'hasMore': (page + 1) * PAGE_SIZE < len(rows)}

    @app.get(PREFIX)
    @guarded
    def journey_finance_allocations(current):
        page = query({'journeyId', 'paymentId', 'status', 'page'})
        jid, pid, status = request.args.get('journeyId'), request.args.get('paymentId'), request.args.get('status', 'active')
        if (jid is not None and pid is not None) or status not in {'active', 'all'}:
            fail()
        if jid is not None: identifier(jid, 24)
        if pid is not None: identifier(pid)
        with current.read() as con:
            state = load(con, current.owner)
            journey = state['journeys'].get(jid)
            if jid is not None and journey is None:
                fail('旅行不存在', 'not_found', 404)
            rows = [projection(state, r) for r in state['links'] if (jid is None or r['journey_id'] == jid)
                    and (pid is None or r['payment_id'] == pid) and (status == 'all' or r['status'] == 'active')]
            rows.sort(key=lambda r: r['id'])
            rows.sort(key=lambda r: r['createdAt'], reverse=True)
            summary = None
            if jid is not None:
                active = [r for r in rows if r['status'] == 'active']
                valid = [r for r in active if r['state'] == 'current']
                stale = [r for r in active if r['state'] == 'needs_review']
                summary = {'currency': 'CNY', 'coverage': 'owner_partial',
                    'currentAllocatedCents': sum(r['amountCents'] for r in valid), 'currentCount': len(valid),
                    'needsReviewAllocatedCents': sum(r['amountCents'] for r in stale), 'needsReviewCount': len(stale),
                    'activeAllocatedCents': sum(r['amountCents'] for r in active), 'sharedBudgetCents': journey['sharedBudgetCents']}
            result = {'version': 1, 'journey': journey, 'summary': summary, 'allocations': rows[page * PAGE_SIZE:(page + 1) * PAGE_SIZE],
                      'pageInfo': page_info(rows, page), 'readAt': now()}
        return jsonify(result)

    @app.get(PREFIX + '/payments')
    @guarded
    def journey_finance_payments(current):
        page = query({'journeyId', 'q', 'page', 'allocationId'})
        jid = identifier(request.args.get('journeyId'), 24)
        rid = identifier(request.args['allocationId'], 32) if 'allocationId' in request.args else None
        term = request.args.get('q', '')
        if len(term) > 80 or any(ord(c) < 32 for c in term): fail()
        with current.read() as con:
            state = load(con, current.owner)
            journey = state['journeys'].get(jid)
            if journey is None: fail('旅行不存在', 'not_found', 404)
            link = owned(state, rid) if rid else None
            if link and (link['journey_id'] != jid or link['status'] != 'active'):
                fail('有效归集不存在', 'not_found', 404)
            rows = [payment(state, key, rid) for key, row in state['payments'].items() if row['kind'] == 'payments']
            rows = [r for r in rows if term.strip().casefold() in r['title'].casefold()]
            rows.sort(key=lambda r: r['id'])
            rows.sort(key=lambda r: r['date'], reverse=True)
            result = {'version': 1, 'journey': journey, 'payments': rows[page * PAGE_SIZE:(page + 1) * PAGE_SIZE],
                'focus': payment(state, link['payment_id'], rid) if link else None,
                'pageInfo': page_info(rows, page), 'readAt': now()}
        return jsonify(result)

    @app.post(PREFIX + '/preview')
    @guarded
    def journey_finance_preview(current):
        plan = normalized(body())
        with current.read() as con:
            state = load(con, current.owner)
            *_, dependencies, output = assess(state, plan)
            token = signer.dumps({'version': 1, 'owner': current.owner, 'context': current.check(), 'plan': plan,
                                  'dependencies': dependencies, 'nonce': secrets.token_hex(16)})
            result = {**output, 'previewToken': token, 'expiresInSeconds': PREVIEW_SECONDS,
                      'expiresAt': (datetime.now(timezone.utc) + timedelta(seconds=PREVIEW_SECONDS)).isoformat()}
        return jsonify(result)

    @app.get(PREFIX + '/operations/<rid>')
    @guarded
    def journey_finance_operation(current, rid):
        query(set())
        identifier(rid, 32)
        with current.read() as con:
            old = con.execute('SELECT result FROM hub_journey_allocation_operations WHERE owner=? AND request_id=?', (current.owner, rid)).fetchone()
            result = {'version': 1, 'requestId': rid, 'found': old is not None, 'receipt': json.loads(old['result']) if old else None}
        return jsonify(result)

    @app.post(PREFIX + '/confirm')
    @guarded
    def journey_finance_confirm(current):
        value = body()
        if set(value) != {'requestId', 'previewToken'}: fail()
        identifier(value['requestId'], 32)
        token = value['previewToken']
        if not isinstance(token, str) or not 20 <= len(token) <= 12000: fail()
        fingerprint = digest(value)
        with current.write() as con:
            old = con.execute('SELECT payload_hash,result FROM hub_journey_allocation_operations WHERE owner=? AND request_id=?',
                              (current.owner, value['requestId'])).fetchone()
            if old:
                if old['payload_hash'] != fingerprint:
                    fail('操作编号已用于其他内容，请核对原请求', 'request_conflict', 409)
                receipt, replayed = json.loads(old['result']), True
            else:
                try:
                    signed, issued = signer.loads(token, return_timestamp=True)
                except BadSignature:
                    fail('预览凭据不正确')
                if (not isinstance(signed, dict) or set(signed) != {'version', 'owner', 'context', 'plan', 'dependencies', 'nonce'}
                        or signed['version'] != 1 or not isinstance(signed['plan'], dict)):
                    fail('预览凭据不正确')
                if signed['owner'] != current.owner or signed['context'] != current.check():
                    fail('预览身份已变化，请重新读取', 'stale', 409)
                age = signer.make_signer().get_timestamp() - int(issued.timestamp())
                if not 0 <= age <= PREVIEW_SECONDS:
                    fail('预览已过期且尚无回执，请重新预览', 'preview_expired', 409)
                plan = normalized(signed['plan'])
                state = load(con, current.owner)
                link, jid, pid, dependencies, output = assess(state, plan)
                if signed['dependencies'] != dependencies:
                    fail('来源或归集已变化，请重新读取并预览', 'stale', 409)
                kind, moment = plan['operation'], now()
                rid = link['id'] if link else secrets.token_hex(16)
                revision = link['revision'] + 1 if link else 1
                receipt = {'requestId': value['requestId'], 'operation': kind, 'allocationId': rid, 'revision': revision, 'completedAt': moment}
                encoded = canonical(receipt)
                used = con.execute('SELECT count(*),coalesce(sum(length(CAST(result AS BLOB))),0) FROM hub_journey_allocation_operations WHERE owner=?', (current.owner,)).fetchone()
                active_after = sum(r['status'] == 'active' for r in state['links']) + (1 if kind == 'apply' else -1 if kind == 'revoke' else 0)
                if (len(encoded.encode()) > RECEIPT_RESERVE or used[0] + 1 + active_after > MAX_OPERATIONS
                        or used[1] + len(encoded.encode()) + active_after * RECEIPT_RESERVE > MAX_OPERATION_BYTES
                        or kind == 'apply' and len(state['links']) >= MAX_ALLOCATIONS):
                    fail('归集或回执容量已满，请联系维护者整理；原回执仍可核对', 'storage_limit', 409)
                if kind == 'apply':
                    pay = output['payment']
                    con.execute('INSERT INTO hub_journey_allocations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (rid, current.owner, jid, output['journey']['tripId'], pid, plan['amountCents'], 'active', revision,
                         source_digest(state, pid), pay['netCents'], pay['refundedCents'], moment, moment))
                elif kind == 'update':
                    pay = output['payment']
                    con.execute('UPDATE hub_journey_allocations SET amount_cents=?,revision=?,source_digest=?,accepted_net_cents=?,accepted_refunded_cents=?,updated_at=? WHERE id=? AND owner=?',
                        (plan['amountCents'], revision, source_digest(state, pid), pay['netCents'], pay['refundedCents'], moment, rid, current.owner))
                else:
                    con.execute("UPDATE hub_journey_allocations SET status='revoked',revision=?,updated_at=? WHERE id=? AND owner=?", (revision, moment, rid, current.owner))
                con.execute('INSERT INTO hub_journey_allocation_operations VALUES(?,?,?,?,?,?,?)',
                    (current.owner, value['requestId'], fingerprint, kind, rid, encoded, moment))
                audit('finance.journey.' + kind, rid)
                replayed = False
        return jsonify(version=1, receipt=receipt, replayed=replayed)

    app.extensions['journey_finance'] = {'export_for_owner': export_owned_allocations}
