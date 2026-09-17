"""Owner-only manual accounts and dated original-currency valuations.

No source-report/holding linkage, exchange rates, bank access or physical deletes.
Registration is separate from app wiring and the explicit deployment migration.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import re
import secrets

from flask import jsonify, request

from finance_source_bridge import ImportSession


FINANCE_ACCOUNTS_SCHEMA_SQL = '''
CREATE TABLE IF NOT EXISTS finance_accounts(
  id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id),
  name TEXT NOT NULL, institution TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('asset','liability')),
  currency TEXT NOT NULL, note TEXT NOT NULL,
  archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)),
  revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>0),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(owner,id));
CREATE TABLE IF NOT EXISTS finance_account_valuations(
  owner TEXT NOT NULL, account_id TEXT NOT NULL, as_of TEXT NOT NULL,
  amount_cents INTEGER CHECK(amount_cents IS NULL OR (typeof(amount_cents)='integer' AND amount_cents BETWEEN 0 AND 100000000000000)),
  updated_at TEXT NOT NULL, PRIMARY KEY(owner,account_id,as_of),
  FOREIGN KEY(owner,account_id) REFERENCES finance_accounts(owner,id));
CREATE TABLE IF NOT EXISTS finance_account_operations(
  owner TEXT NOT NULL REFERENCES users(id), request_id TEXT NOT NULL,
  payload_hash TEXT NOT NULL, operation TEXT NOT NULL, account_id TEXT NOT NULL,
  result TEXT NOT NULL, completed_at TEXT NOT NULL, PRIMARY KEY(owner,request_id));
'''
MAX_ACCOUNTS = 300
MAX_VALUATIONS = 3660
MAX_OPERATIONS = 20_000
MAX_OPERATION_BYTES = 32 * 1024 * 1024
MAX_REQUEST_BYTES = 16 * 1024
MAX_AMOUNT = 100_000_000_000_000
PREFIX = '/api/finance-accounts'


def init_schema(con):
    """Initialize only these three tables; leave commit/rollback to the caller."""
    for statement in FINANCE_ACCOUNTS_SCHEMA_SQL.split(';'):
        if statement.strip():
            con.execute(statement)


class AccountError(Exception):
    def __init__(self, message, code='invalid_request', status=400):
        super().__init__(message)
        self.code, self.status = code, status


def fail(message='账户请求格式不正确', code='invalid_request', status=400):
    raise AccountError(message, code, status)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def exact(value, required, optional=()):
    if type(value) is not dict or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        fail()


def text(value, maximum, *, required=False, multiline=False):
    if type(value) is not str or len(value) > maximum or (required and not value.strip()):
        fail('账户文字为空或超过长度限制')
    if any((ord(c) < 32 and not (multiline and c in '\n\t')) or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        fail('账户文字含不支持的字符')
    return value


def day(value):
    if type(value) is not str or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
        fail('估值日期须为 YYYY-MM-DD')
    try:
        date.fromisoformat(value)
    except ValueError:
        fail('估值日期不是有效日历日期')
    return value


def amount(value):
    if value is not None and (type(value) is not int or not 0 <= value <= MAX_AMOUNT):
        fail('金额须为非负整数分；未知请填写 null')
    return value


def identifier(value, length):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{' + str(length) + '}', value):
        fail('账户或操作编号不正确')
    return value


def revision(value, *, create=False):
    if type(value) is not int or (value != 0 if create else not 1 <= value <= 9_007_199_254_740_990):
        fail('请提供有效的账户版本')
    return value


def account(row):
    return {'id': row['id'], 'owner': row['owner'], 'name': row['name'],
            'institution': row['institution'], 'kind': row['kind'], 'currency': row['currency'],
            'note': row['note'], 'archived': bool(row['archived']), 'revision': row['revision'],
            'createdAt': row['created_at'], 'updatedAt': row['updated_at'], 'visibility': 'private'}


def valuation(row):
    return {'asOf': row['as_of'], 'amountCents': row['amount_cents'],
            'source': 'manual', 'updatedAt': row['updated_at']} if row is not None else None


def export_owned_accounts(con, owner):
    """Pure read within the caller's authorized snapshot; explicit business fields only."""
    items = [account(row) for row in con.execute(
        'SELECT * FROM finance_accounts WHERE owner=? ORDER BY id', (owner,))]
    points = [{'accountId': row['account_id'], **valuation(row)} for row in con.execute(
        'SELECT v.* FROM finance_account_valuations v JOIN finance_accounts a '
        'ON a.owner=v.owner AND a.id=v.account_id WHERE v.owner=? ORDER BY v.account_id,v.as_of', (owner,))]
    operations = [{'operation': row['operation'], 'accountId': row['account_id'], 'completedAt': row['completed_at']}
        for row in con.execute('SELECT o.operation,o.account_id,o.completed_at FROM finance_account_operations o '
            'JOIN finance_accounts a ON a.owner=o.owner AND a.id=o.account_id '
            'WHERE o.owner=? ORDER BY o.completed_at,o.request_id', (owner,))]
    return {'accounts': items, 'valuations': points, 'operations': operations}


def totals(accounts, as_of):
    groups = {}
    for item in accounts:
        group = groups.setdefault(item['currency'], {'currency': item['currency'], 'assetCount': 0,
            'liabilityCount': 0, 'knownCount': 0, 'unknownCount': 0, 'missingCount': 0, 'olderCount': 0,
            'knownAssetCents': 0, 'knownLiabilityCents': 0})
        group[item['kind'] + 'Count'] += 1
        value = item['valuation']
        if value is None:
            group['missingCount'] += 1
        else:
            group['olderCount'] += int(value['asOf'] < as_of)
            if value['amountCents'] is None:
                group['unknownCount'] += 1
            else:
                group['knownCount'] += 1
                group['knownAssetCents' if item['kind'] == 'asset' else 'knownLiabilityCents'] += value['amountCents']
    for group in groups.values():
        group['knownNetCents'] = str(group['knownAssetCents'] - group['knownLiabilityCents'])
        for field in ('knownAssetCents', 'knownLiabilityCents'):
            group[field] = str(group[field])
    return [groups[key] for key in sorted(groups)]


def register_finance_accounts(app, db, Problem, body, require_member, audit, *, initialize=True):
    if initialize:
        with app.app_context():
            init_schema(db())
            db().commit()

    @app.errorhandler(AccountError)
    def account_error(exc):
        return jsonify(error=str(exc), code=exc.code), exc.status

    def session():
        return ImportSession(app, db, Problem, require_member)

    def query(allowed=()):
        if request.args.keys() - set(allowed) or any(len(request.args.getlist(key)) != 1 for key in request.args):
            fail('查询参数重复或不支持')

    def payload():
        query()
        request.max_content_length = MAX_REQUEST_BYTES
        raw = request.get_data(cache=True)
        if len(raw) > MAX_REQUEST_BYTES:
            fail('账户请求过大', status=413)
        def pairs(values):
            result = {}
            for key, value in values:
                if key in result:
                    fail('JSON 字段不能重复')
                result[key] = value
            return result
        try:
            parsed = json.loads(raw, object_pairs_hook=pairs,
                                parse_constant=lambda _: fail('JSON 数值不正确'))
        except (ValueError, UnicodeError, RecursionError):
            fail()
        if type(parsed) is not dict:
            fail()
        # Preserve the application's JSON-body dependency and its own checks.
        body()
        return parsed

    def owned(con, owner, rid):
        row = con.execute('SELECT * FROM finance_accounts WHERE owner=? AND id=?', (owner, rid)).fetchone()
        if row is None:
            fail('账户不存在', 'account_not_found', 404)
        return row

    @app.get(PREFIX)
    def finance_account_list():
        current = session()
        query({'asOf', 'status'})
        as_of, status = day(request.args.get('asOf')), request.args.get('status', 'active')
        if status not in {'active', 'archived', 'all'}:
            fail('请选择有效的账户范围')
        with current.read() as con:
            rows = con.execute('SELECT * FROM finance_accounts WHERE owner=?' +
                ('' if status == 'all' else ' AND archived=?') + ' ORDER BY created_at,id',
                (current.owner,) if status == 'all' else (current.owner, int(status == 'archived'))).fetchall()
            items = []
            for row in rows:
                point = con.execute('SELECT * FROM finance_account_valuations WHERE owner=? AND account_id=? AND as_of<=? '
                                    'ORDER BY as_of DESC LIMIT 1', (current.owner, row['id'], as_of)).fetchone()
                items.append({**account(row), 'valuation': valuation(point)})
            result = {'owner': current.owner, 'asOf': as_of, 'status': status,
                      'scope': 'manual_accounts_only', 'accounts': items, 'totals': totals(items, as_of)}
        return jsonify(result)

    @app.get(PREFIX + '/<rid>/valuations')
    def finance_account_history(rid):
        current = session()
        rid = identifier(rid, 24)
        query({'page', 'pageSize'})
        def page_value(key, default, maximum):
            raw = request.args.get(key, str(default))
            if not re.fullmatch('[1-9][0-9]{0,5}', raw) or int(raw) > maximum:
                fail('分页参数不正确')
            return int(raw)
        page, size = page_value('page', 1, MAX_VALUATIONS), page_value('pageSize', 50, 100)
        with current.read() as con:
            item = account(owned(con, current.owner, rid))
            count = con.execute('SELECT count(*) FROM finance_account_valuations WHERE owner=? AND account_id=?',
                                (current.owner, rid)).fetchone()[0]
            points = con.execute('SELECT * FROM finance_account_valuations WHERE owner=? AND account_id=? '
                                 'ORDER BY as_of DESC LIMIT ? OFFSET ?', (current.owner, rid, size, (page-1)*size)).fetchall()
            result = {'account': item, 'valuations': [valuation(row) for row in points],
                      'page': page, 'pageSize': size, 'total': count}
        return jsonify(result)

    @app.get(PREFIX + '/operations/<request_id>')
    def finance_account_operation(request_id):
        current = session()
        query()
        request_id = identifier(request_id, 32)
        with current.read() as con:
            row = con.execute('SELECT result FROM finance_account_operations WHERE owner=? AND request_id=?',
                              (current.owner, request_id)).fetchone()
            receipt = {**json.loads(row['result']), 'replayed': True} if row else None
        return jsonify(requestId=request_id, found=row is not None, receipt=receipt)

    def write(current, operation, rid, value, apply, *, as_of=None):
        request_id = value['requestId']
        # Bind every original JSON field, operation and target; no normalization
        # may silently change what a reused key means.
        fingerprint = hashlib.sha256(canonical({'operation': operation, 'accountId': rid,
            'asOf': as_of, 'payload': value}).encode('utf-8')).hexdigest()
        replayed = False
        with current.write() as con:
            old = con.execute('SELECT payload_hash,result FROM finance_account_operations WHERE owner=? AND request_id=?',
                              (current.owner, request_id)).fetchone()
            if old:
                if old['payload_hash'] != fingerprint:
                    fail('该操作编号已用于其他内容，请保留原操作核对', 'operation_request_conflict', 409)
                result, replayed = json.loads(old['result']), True
            else:
                used = con.execute('SELECT count(*),coalesce(sum(length(CAST(result AS BLOB))),0) '
                                   'FROM finance_account_operations WHERE owner=?', (current.owner,)).fetchone()
                if used[0] >= MAX_OPERATIONS or used[1] >= MAX_OPERATION_BYTES:
                    fail('账户操作回执已达到容量限制，原回执仍可读取', 'capacity_exceeded', 409)
                now = datetime.now(timezone.utc).isoformat(timespec='microseconds')
                data = apply(con, current.owner, now)
                result = {'requestId': request_id, 'operation': operation, 'accountId': data['account']['id'],
                          'completedAt': now, 'result': data}
                encoded = canonical(result)
                if used[1] + len(encoded.encode('utf-8')) > MAX_OPERATION_BYTES:
                    fail('账户操作回执已达到容量限制，原回执仍可读取', 'capacity_exceeded', 409)
                con.execute('INSERT INTO finance_account_operations VALUES(?,?,?,?,?,?,?)',
                            (current.owner, request_id, fingerprint, operation, data['account']['id'], encoded, now))
                audit('finance.account.' + operation, data['account']['id'])
        # Covers historical replay and revocation after COMMIT but before a
        # response is assembled; a rejected response does not undo committed data.
        current.fresh()
        return jsonify(**result, replayed=replayed), 201 if operation == 'create' else 200

    def expected(con, current, rid, value):
        row = owned(con, current, rid)
        if row['revision'] != value['revision']:
            fail('账户已变化，请保留草稿并核对最新版本', 'revision_conflict', 409)
        return row

    @app.post(PREFIX)
    def finance_account_create():
        current = session()
        value = payload()
        exact(value, {'requestId', 'revision', 'name', 'institution', 'kind', 'currency', 'note', 'valuation'})
        identifier(value['requestId'], 32)
        revision(value['revision'], create=True)
        text(value['name'], 120, required=True)
        text(value['institution'], 120)
        text(value['note'], 1000, multiline=True)
        if type(value['kind']) is not str or value['kind'] not in {'asset', 'liability'}:
            fail('请选择资产或负债')
        if type(value['currency']) is not str or not re.fullmatch('[A-Z]{3}', value['currency']):
            fail('原币币种须为三位大写字母代码')
        point = value['valuation']
        exact(point, {'asOf', 'amountCents'})
        day(point['asOf'])
        amount(point['amountCents'])
        def apply(con, owner, now):
            if con.execute('SELECT count(*) FROM finance_accounts WHERE owner=?', (owner,)).fetchone()[0] >= MAX_ACCOUNTS:
                fail('本人账户已达到容量限制（含归档）', 'capacity_exceeded', 409)
            rid = secrets.token_hex(12)
            con.execute('INSERT INTO finance_accounts(id,owner,name,institution,kind,currency,note,created_at,updated_at) '
                        'VALUES(?,?,?,?,?,?,?,?,?)', (rid, owner, value['name'], value['institution'], value['kind'],
                                                    value['currency'], value['note'], now, now))
            con.execute('INSERT INTO finance_account_valuations VALUES(?,?,?,?,?)',
                        (owner, rid, point['asOf'], point['amountCents'], now))
            return {'account': account(owned(con, owner, rid)),
                    'valuation': {'asOf': point['asOf'], 'amountCents': point['amountCents'], 'source': 'manual', 'updatedAt': now}}
        return write(current, 'create', None, value, apply)

    @app.patch(PREFIX + '/<rid>')
    def finance_account_update(rid):
        current = session()
        rid, value = identifier(rid, 24), payload()
        exact(value, {'requestId', 'revision', 'changes'})
        identifier(value['requestId'], 32)
        revision(value['revision'])
        changes = value['changes']
        exact(changes, (), {'name', 'institution', 'note', 'archived'})
        if not changes:
            fail('请选择要修改的账户字段')
        for key in ('name', 'institution', 'note'):
            if key in changes:
                text(changes[key], 1000 if key == 'note' else 120, required=key == 'name', multiline=key == 'note')
        if 'archived' in changes and type(changes['archived']) is not bool:
            fail('归档状态须为布尔值')
        def apply(con, owner, now):
            row = expected(con, owner, rid, value)
            fields = {key: changes.get(key, row[key]) for key in ('name', 'institution', 'note', 'archived')}
            updated = con.execute('UPDATE finance_accounts SET name=?,institution=?,note=?,archived=?,revision=revision+1,updated_at=? '
                'WHERE owner=? AND id=? AND revision=?', (fields['name'], fields['institution'], fields['note'],
                int(fields['archived']), now, owner, rid, value['revision']))
            if updated.rowcount != 1:
                fail('账户版本已变化', 'revision_conflict', 409)
            return {'account': account(owned(con, owner, rid)), 'valuation': None}
        return write(current, 'update', rid, value, apply)

    @app.put(PREFIX + '/<rid>/valuations/<as_of>')
    def finance_account_value(rid, as_of):
        current = session()
        rid, as_of, value = identifier(rid, 24), day(as_of), payload()
        exact(value, {'requestId', 'revision', 'amountCents'})
        identifier(value['requestId'], 32)
        revision(value['revision'])
        amount(value['amountCents'])
        def apply(con, owner, now):
            row = expected(con, owner, rid, value)
            if row['archived']:
                fail('请先恢复账户，再更新估值', 'account_archived', 409)
            exists = con.execute('SELECT 1 FROM finance_account_valuations WHERE owner=? AND account_id=? AND as_of=?',
                                 (owner, rid, as_of)).fetchone()
            if not exists and con.execute('SELECT count(*) FROM finance_account_valuations WHERE owner=? AND account_id=?',
                                         (owner, rid)).fetchone()[0] >= MAX_VALUATIONS:
                fail('账户估值历史已达到容量限制', 'capacity_exceeded', 409)
            con.execute('INSERT INTO finance_account_valuations VALUES(?,?,?,?,?) '
                        'ON CONFLICT(owner,account_id,as_of) DO UPDATE SET amount_cents=excluded.amount_cents,updated_at=excluded.updated_at',
                        (owner, rid, as_of, value['amountCents'], now))
            updated = con.execute('UPDATE finance_accounts SET revision=revision+1,updated_at=? WHERE owner=? AND id=? AND revision=?',
                                  (now, owner, rid, value['revision']))
            if updated.rowcount != 1:
                fail('账户版本已变化', 'revision_conflict', 409)
            return {'account': account(owned(con, owner, rid)),
                    'valuation': {'asOf': as_of, 'amountCents': value['amountCents'], 'source': 'manual', 'updatedAt': now}}
        return write(current, 'valuation', rid, value, apply, as_of=as_of)
