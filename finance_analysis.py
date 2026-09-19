"""Owner-private analysis of explicitly selected manual accounts.

No ledger, holding, baseline or shared-wallet amounts enter these calculations.
Only an explicit, current period review permits cashflow attribution.
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction
from functools import wraps
from zoneinfo import ZoneInfo
import hashlib
import json
import re
import secrets

from flask import jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge

from finance_accounts import account, valuation
from finance_source_bridge import ImportSession
import finance_fx as fx


FINANCE_ANALYSIS_SCHEMA_SQL = '''
CREATE TABLE IF NOT EXISTS finance_account_profiles(
  owner TEXT NOT NULL, account_id TEXT NOT NULL,
  asset_class TEXT NOT NULL CHECK(asset_class IN ('unknown','cash','fixed_income','equity','fund','property','other')),
  liquidity TEXT NOT NULL CHECK(liquidity IN ('unknown','immediate','within_month','over_month','restricted')),
  revision INTEGER NOT NULL CHECK(revision>0), updated_at TEXT NOT NULL,
  PRIMARY KEY(owner,account_id),
  FOREIGN KEY(owner,account_id) REFERENCES finance_accounts(owner,id));
CREATE TABLE IF NOT EXISTS finance_account_cashflows(
  id TEXT PRIMARY KEY, owner TEXT NOT NULL, account_id TEXT NOT NULL, as_of TEXT NOT NULL,
  direction TEXT NOT NULL CHECK(direction IN ('in','out')),
  amount_cents INTEGER NOT NULL CHECK(typeof(amount_cents)='integer' AND amount_cents BETWEEN 0 AND 100000000000000),
  note TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>0), created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  FOREIGN KEY(owner,account_id) REFERENCES finance_accounts(owner,id));
CREATE TABLE IF NOT EXISTS finance_account_reviews(
  owner TEXT NOT NULL, account_id TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
  context_digest TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>0), confirmed_at TEXT NOT NULL,
  PRIMARY KEY(owner,account_id,start_date,end_date),
  FOREIGN KEY(owner,account_id) REFERENCES finance_accounts(owner,id));
CREATE TABLE IF NOT EXISTS finance_analysis_operations(
  owner TEXT NOT NULL REFERENCES users(id), request_id TEXT NOT NULL, payload_hash TEXT NOT NULL,
  operation TEXT NOT NULL, account_id TEXT, result TEXT NOT NULL, completed_at TEXT NOT NULL,
  PRIMARY KEY(owner,request_id),
  FOREIGN KEY(owner,account_id) REFERENCES finance_accounts(owner,id));
'''
PREFIX = '/api/finance-analysis'
CLASSES = ('unknown', 'cash', 'fixed_income', 'equity', 'fund', 'property', 'other')
LIQUIDITIES = ('unknown', 'immediate', 'within_month', 'over_month', 'restricted')
MIN_DATE = date(1999, 1, 4)
MAX_ACCOUNTS = 300
MAX_CASHFLOWS = 10_000
MAX_OPERATIONS = 20_000
MAX_OPERATION_BYTES = 32 * 1024 * 1024
MAX_REQUEST_BYTES = 16 * 1024
MAX_AMOUNT = 100_000_000_000_000
CHANGE_FIELDS = ('convertedChangeCents', 'convertedNetFlowCents',
                 'convertedValuationResidualCents', 'fxEffectCents', 'roundingCents')


def init_schema(con):
    """Create exactly four tables without committing the caller's transaction."""
    for statement in FINANCE_ANALYSIS_SCHEMA_SQL.split(';'):
        if statement.strip():
            con.execute(statement)


class AnalysisError(Exception):
    def __init__(self, message='分析请求格式不正确', code='invalid_request', status=400):
        super().__init__(message)
        self.code, self.status = code, status


def fail(message='分析请求格式不正确', code='invalid_request', status=400):
    raise AnalysisError(message, code, status)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def exact(value, fields):
    if type(value) is not dict or value.keys() != set(fields):
        fail()


def identifier(value, size=24):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{' + str(size) + '}', value):
        fail('账户、事件或操作编号不正确')
    return value


def revision(value, *, zero=False):
    if type(value) is not int or not (0 if zero else 1) <= value <= 9_007_199_254_740_990:
        fail('请提供有效版本')
    return value


def day(value):
    if type(value) is not str or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
        fail('日期须为 YYYY-MM-DD')
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        fail('日期不是有效日历日期')
    if parsed < MIN_DATE:
        fail('分析日期须从 1999-01-04 起')
    return value


def period(start, end):
    start, end = day(start), day(end)
    if not 0 < (date.fromisoformat(end) - date.fromisoformat(start)).days <= 365:
        fail('请选择起止不同且最多 366 天的区间')
    return start, end


def lookback(start):
    return max(MIN_DATE, date.fromisoformat(start) - timedelta(days=7)).isoformat()


def profile(row, rid=None):
    return {'accountId': row['account_id'] if row else rid,
            'assetClass': row['asset_class'] if row else 'unknown',
            'liquidity': row['liquidity'] if row else 'unknown',
            'revision': row['revision'] if row else 0, 'updatedAt': row['updated_at'] if row else None}


def cashflow(row):
    return {'id': row['id'], 'accountId': row['account_id'], 'date': row['as_of'],
            'direction': row['direction'], 'amountCents': row['amount_cents'], 'note': row['note'],
            'revision': row['revision'], 'createdAt': row['created_at'], 'updatedAt': row['updated_at']}


def signed_flow(row):
    return row['amount_cents'] * (1 if row['direction'] == 'in' else -1)


def owned(con, owner, rid, *, active=False):
    row = con.execute('SELECT * FROM finance_accounts WHERE owner=? AND id=?', (owner, rid)).fetchone()
    if row is None:
        fail('账户不存在', 'account_not_found', 404)
    if active and row['archived']:
        fail('请先恢复账户，再更改分析资料', 'account_archived', 409)
    return row


def period_data(con, owner, row, start, end):
    points = [con.execute('SELECT * FROM finance_account_valuations WHERE owner=? AND account_id=? AND as_of<=? '
                         'ORDER BY as_of DESC LIMIT 1', (owner, row['id'], at)).fetchone() for at in (start, end)]
    flows = con.execute('SELECT * FROM finance_account_cashflows WHERE owner=? AND account_id=? '
                        'AND as_of>? AND as_of<=? ORDER BY as_of,id', (owner, row['id'], start, end)).fetchall()
    return points, flows


def period_review(con, owner, row, start, end, points, flows):
    # The account revision is conservative: corrections, archive/restore and
    # metadata edits cannot silently reuse a previously accepted account state.
    # Receipt history prevents add/delete or move-out/move-back from resurrecting
    # an old accepted digest. Include both the former and new date for a moved
    # event, while keeping unrelated periods independent.
    event_dates, mutations = {}, []
    for operation in con.execute('SELECT operation,payload_hash,result FROM finance_analysis_operations '
                                 "WHERE owner=? AND account_id=? AND operation IN ('cashflow_create','cashflow_update','cashflow_delete') ORDER BY rowid",
                                 (owner, row['id'])):
        event = json.loads(operation['result'])['result']
        old_date = event_dates.get(event['id'])
        new_date = event.get('date')
        if any(at is not None and start < at <= end for at in (old_date, new_date)):
            mutations.append(operation['payload_hash'])
        if new_date is None:
            event_dates.pop(event['id'], None)
        else:
            event_dates[event['id']] = new_date
    context = digest({'version': 1, 'owner': owner, 'accountId': row['id'], 'accountRevision': row['revision'],
                      'currency': row['currency'], 'kind': row['kind'], 'start': start, 'end': end,
                      'points': [valuation(point) for point in points], 'cashflows': [cashflow(f) for f in flows],
                      'flowMutationDigest': digest(mutations)})
    old = con.execute('SELECT * FROM finance_account_reviews WHERE owner=? AND account_id=? '
                      'AND start_date=? AND end_date=?', (owner, row['id'], start, end)).fetchone()
    confirmable = all(p is not None and p['as_of'] == at and p['amount_cents'] is not None
                      for p, at in zip(points, (start, end)))
    return {'revision': old['revision'] if old else 0, 'contextDigest': context,
            'status': ('current' if old['context_digest'] == context else 'stale') if old else 'unreviewed',
            'confirmedAt': old['confirmed_at'] if old else None, 'cashflowCount': len(flows),
            'recordedNetFlowCents': str(sum(signed_flow(f) for f in flows)), 'canConfirm': confirmable}


def rounded(value):
    """Exact HALF_UP to cents, including negative components; no binary float."""
    absolute = abs(value)
    result = (absolute.numerator * 2 + absolute.denominator) // (2 * absolute.denominator)
    return result if value >= 0 else -result


def ratio(quote):
    return Fraction(quote['targetPerEur']) / Fraction(quote['sourcePerEur'])


def report_dates(start, end, step):
    current, last = date.fromisoformat(start), date.fromisoformat(end)
    result = [start]
    while current < last:
        current += timedelta(days=1)
        if step == 'day' or current == last or (current + timedelta(days=1)).month != current.month:
            result.append(current.isoformat())
    return result


def summary(rows, points):
    coverage = dict.fromkeys(('selectedCount', 'knownValuationCount', 'convertedCount', 'missingValuationCount',
                              'unknownValuationCount', 'olderValuationCount', 'missingFxCount'), 0)
    coverage['selectedCount'] = len(rows)
    assets = liabilities = 0
    for row, point in zip(rows, points):
        val = point['valuation']
        if val is None:
            coverage['missingValuationCount'] += 1
            continue
        coverage['olderValuationCount'] += int(val['asOf'] < point['date'])
        if val['amountCents'] is None:
            coverage['unknownValuationCount'] += 1
            continue
        coverage['knownValuationCount'] += 1
        if point['convertedCents'] is None:
            coverage['missingFxCount'] += 1
            continue
        coverage['convertedCount'] += 1
        if row['kind'] == 'asset':
            assets += int(point['convertedCents'])
        else:
            liabilities += int(point['convertedCents'])
    return {'knownAssetCents': str(assets), 'knownLiabilityCents': str(liabilities), 'knownNetCents': str(assets-liabilities),
            'complete': coverage['convertedCount'] == len(rows) and not coverage['olderValuationCount'], 'coverage': coverage}


def account_change(opening, closing, review, flows, quote_for):
    values = [p['valuation']['amountCents'] if p['valuation'] is not None else None for p in (opening, closing)]
    result = {'originalChangeCents': str(values[1]-values[0]) if None not in values else None,
              'recordedNetFlowCents': review['recordedNetFlowCents'], 'valuationResidualCents': None,
              **dict.fromkeys(CHANGE_FIELDS), 'status': 'unreviewed'}
    if opening['convertedCents'] is not None and closing['convertedCents'] is not None:
        result['convertedChangeCents'] = str(int(closing['convertedCents']) - int(opening['convertedCents']))
    if review['status'] != 'current':
        result['status'] = review['status']
        return result
    if not review['canConfirm']:
        result['status'] = 'missing_valuations'
        return result
    residual = values[1] - values[0] - int(review['recordedNetFlowCents'])
    result['valuationResidualCents'] = str(residual)
    flow_quotes = [quote_for(f['as_of']) for f in flows]
    if opening['fx'] is None or closing['fx'] is None or any(q is None for q in flow_quotes):
        result['status'] = 'missing_fx'
        return result
    r0, r1 = ratio(opening['fx']), ratio(closing['fx'])
    converted_flows = sum((signed_flow(f) * ratio(q) for f, q in zip(flows, flow_quotes)), Fraction())
    converted_residual = residual * r1
    fx_effect = values[0] * (r1-r0) + sum((signed_flow(f) * (r1-ratio(q))
                                         for f, q in zip(flows, flow_quotes)), Fraction())
    pieces = [rounded(converted_flows), rounded(converted_residual), rounded(fx_effect)]
    result.update(convertedNetFlowCents=str(pieces[0]), convertedValuationResidualCents=str(pieces[1]),
                  fxEffectCents=str(pieces[2]), roundingCents=str(int(result['convertedChangeCents'])-sum(pieces)), status='complete')
    return result


def build_report(con, owner, start, end, base, step, selected):
    rows = con.execute('SELECT * FROM finance_accounts WHERE owner=? ORDER BY id', (owner,)).fetchall()
    if selected is not None:
        if not selected <= {row['id'] for row in rows}:
            fail('账户不存在', 'account_not_found', 404)
        rows = [row for row in rows if row['id'] in selected]
    dates = report_dates(start, end, step)
    rates = fx.load_fx_rates(con, lookback(start), end)
    quotes = {}
    currency_rates = {}

    def quote_for(currency, at):
        key = currency, at
        if key not in quotes:
            if currency not in currency_rates:
                currency_rates[currency] = [rate for rate in rates if rate['currency'] in {currency, base}]
            quotes[key] = fx.resolve_fx_quote(currency_rates[currency], at, currency, base)
        return quotes[key]

    by_date = {at: [] for at in dates}
    items = []
    for row in rows:
        history = con.execute('SELECT * FROM finance_account_valuations WHERE owner=? AND account_id=? AND as_of<=? '
                              'ORDER BY as_of', (owner, row['id'], end)).fetchall()
        history_dates = [v['as_of'] for v in history]
        points = []
        raw_points = []
        for at in dates:
            index = bisect_right(history_dates, at) - 1
            val = history[index] if index >= 0 else None
            quote = quote_for(row['currency'], at)
            converted = str(fx.convert_cents(val['amount_cents'], quote['sourcePerEur'], quote['targetPerEur'])) \
                if val is not None and val['amount_cents'] is not None and quote is not None else None
            point = {'date': at, 'valuation': valuation(val), 'convertedCents': converted, 'fx': quote}
            points.append(point)
            raw_points.append(val)
            by_date[at].append(point)
        flows = con.execute('SELECT * FROM finance_account_cashflows WHERE owner=? AND account_id=? '
                            'AND as_of>? AND as_of<=? ORDER BY as_of,id', (owner, row['id'], start, end)).fetchall()
        review = period_review(con, owner, row, start, end, [raw_points[0], raw_points[-1]], flows)
        prof = profile(con.execute('SELECT * FROM finance_account_profiles WHERE owner=? AND account_id=?',
                                   (owner, row['id'])).fetchone(), row['id'])
        items.append({'account': account(row), 'profile': prof, 'opening': points[0], 'closing': points[-1],
                      'review': review, 'change': account_change(points[0], points[-1], review, flows,
                                                               lambda at: quote_for(row['currency'], at))})
    buckets = []
    for field, choices in (('assetClass', CLASSES), ('liquidity', LIQUIDITIES)):
        grouped = {key: {'key': key, 'knownCents': 0, 'count': 0} for key in choices}
        for item in items:
            if item['account']['kind'] == 'asset' and item['closing']['convertedCents'] is not None:
                bucket = grouped[item['profile'][field]]
                bucket['knownCents'] += int(item['closing']['convertedCents'])
                bucket['count'] += 1
        buckets.append([{**bucket, 'knownCents': str(bucket['knownCents'])} for bucket in grouped.values()])
    change = {}
    for field in CHANGE_FIELDS:
        change[field] = str(sum(int(item['change'][field]) * (1 if item['account']['kind'] == 'asset' else -1)
                                for item in items)) if all(item['change'][field] is not None for item in items) else None
    change.update(complete=all(item['change']['status'] == 'complete' for item in items),
                  reviewedCount=sum(item['review']['status'] == 'current' for item in items))
    return {'owner': owner, 'scope': 'private_accounts_only', 'start': start, 'end': end, 'baseCurrency': base,
            'step': step, 'accountIds': [row['id'] for row in rows], 'accounts': items,
            'summary': summary(rows, by_date[end]), 'series': [{'date': at, 'summary': summary(rows, by_date[at])} for at in dates],
            'allocation': buckets[0], 'liquidity': buckets[1], 'change': change}


def export_owned_analysis(con, owner):
    """Business-only export under the caller's existing authorized snapshot."""
    return {
        'profiles': [profile(row) for row in con.execute(
            'SELECT * FROM finance_account_profiles WHERE owner=? ORDER BY account_id', (owner,))],
        'cashflows': [cashflow(row) for row in con.execute(
            'SELECT * FROM finance_account_cashflows WHERE owner=? ORDER BY account_id,as_of,id', (owner,))],
        'reviews': [{'accountId': row['account_id'], 'start': row['start_date'], 'end': row['end_date'],
                     'contextDigest': row['context_digest'], 'revision': row['revision'], 'confirmedAt': row['confirmed_at']}
                    for row in con.execute('SELECT * FROM finance_account_reviews WHERE owner=? ORDER BY account_id,start_date,end_date', (owner,))],
        'operations': [{'operation': row['operation'], 'accountId': row['account_id'], 'completedAt': row['completed_at']}
                       for row in con.execute('SELECT operation,account_id,completed_at FROM finance_analysis_operations '
                                              'WHERE owner=? ORDER BY completed_at,request_id', (owner,))]}


def register_finance_analysis(app, db, Problem, body, require_member, audit, *, initialize=True):
    if initialize:
        with app.app_context():
            init_schema(db())
            fx.init_fx_schema(db())
            db().commit()

    def guarded(view):
        @wraps(view)
        def run(*args, **kwargs):
            current = None
            try:
                current = ImportSession(app, db, Problem, require_member)
                response = view(current, *args, **kwargs)
                current.fresh()
                return response
            except (AnalysisError, Problem, fx.FxError, RequestEntityTooLarge) as error:
                if current is not None:
                    try:
                        current.fresh()
                    except Problem as expired:
                        error = expired
                if isinstance(error, fx.FxError):
                    return jsonify(error='公共参考汇率暂不可用，已有缓存保持', code=error.code), 409 if error.code == 'fx_capacity' else 503
                if isinstance(error, RequestEntityTooLarge):
                    return jsonify(error='分析请求过大', code='invalid_request'), 413
                return jsonify(error=str(error) if isinstance(error, AnalysisError) else error.message,
                               code=getattr(error, 'code', 'access_denied' if error.status in (401, 403) else 'invalid_request')), error.status
        return run

    @app.after_request
    def finance_analysis_error_shape(response):
        # The application's guard runs before route wrappers (CSRF/anonymous).
        # Normalize only this namespace; all existing endpoint DTOs stay intact.
        if request.path.startswith(PREFIX + '/') and response.status_code >= 400:
            value = response.get_json(silent=True)
            if type(value) is dict and 'error' in value and 'code' not in value:
                value['code'] = 'access_denied' if response.status_code in (401, 403) else 'invalid_request'
                response.set_data(canonical(value))
                response.content_type = 'application/json'
        return response

    def query(allowed=()):
        if request.args.keys() - set(allowed) or any(len(request.args.getlist(k)) != 1 for k in request.args):
            fail('查询参数重复或不支持')

    def payload(fields):
        query()
        request.max_content_length = MAX_REQUEST_BYTES
        raw = request.get_data(cache=True)
        if len(raw) > MAX_REQUEST_BYTES:
            fail('分析请求过大', status=413)
        def pairs(entries):
            result = {}
            for key, value in entries:
                if key in result:
                    fail('JSON 字段不能重复')
                result[key] = value
            return result
        try:
            value = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: fail())
        except (ValueError, UnicodeError, RecursionError):
            fail()
        exact(value, fields)
        body()
        identifier(value['requestId'], 32)
        return value

    def fingerprint(operation, rid, value):
        return digest({'operation': operation, 'accountId': rid, 'path': request.path, 'payload': value})

    def recover(con, owner, key, expected_hash):
        old = con.execute('SELECT payload_hash,result FROM finance_analysis_operations WHERE owner=? AND request_id=?',
                          (owner, key)).fetchone()
        if old is not None:
            if old['payload_hash'] != expected_hash:
                fail('该操作编号已用于其他内容，请保留原操作核对', 'operation_request_conflict', 409)
            return json.loads(old['result'])
        return None

    def capacity(con, owner):
        used = con.execute('SELECT count(*),coalesce(sum(length(CAST(result AS BLOB))),0) '
                           'FROM finance_analysis_operations WHERE owner=?', (owner,)).fetchone()
        if used[0] >= MAX_OPERATIONS or used[1] >= MAX_OPERATION_BYTES:
            fail('分析操作回执已达到容量限制，原回执仍可读取', 'capacity_exceeded', 409)
        return used[1]

    def write(current, operation, rid, value, apply):
        expected_hash = fingerprint(operation, rid, value)
        replayed = False
        with current.write() as con:
            result = recover(con, current.owner, value['requestId'], expected_hash)
            if result is not None:
                replayed = True
            else:
                used = capacity(con, current.owner)
                now = datetime.now(timezone.utc).isoformat(timespec='microseconds')
                data = apply(con, current.owner, now)
                result = {'requestId': value['requestId'], 'operation': operation, 'accountId': rid,
                          'completedAt': now, 'result': data}
                encoded = canonical(result)
                if used + len(encoded.encode('utf-8')) > MAX_OPERATION_BYTES:
                    fail('分析操作回执已达到容量限制', 'capacity_exceeded', 409)
                con.execute('INSERT INTO finance_analysis_operations VALUES(?,?,?,?,?,?,?)',
                            (current.owner, value['requestId'], expected_hash, operation, rid, encoded, now))
                audit('finance.analysis.' + operation, rid or 'public-fx')
        return jsonify(**result, replayed=replayed)

    @app.get(PREFIX + '/report')
    @guarded
    def finance_analysis_report(current):
        query({'start', 'end', 'baseCurrency', 'step', 'accountIds'})
        start, end = period(request.args.get('start'), request.args.get('end'))
        base, step = request.args.get('baseCurrency', 'CNY'), request.args.get('step', 'month')
        if not re.fullmatch('[A-Z]{3}', base) or step not in {'day', 'month'}:
            fail('报告币种或取样方式不正确')
        raw = request.args.get('accountIds', 'all')
        selected = None
        if raw != 'all':
            parts = raw.split(',')
            if not 1 <= len(parts) <= MAX_ACCOUNTS:
                fail('选择账户数量不正确')
            selected = {identifier(part) for part in parts}
            if len(parts) != len(selected):
                fail('账户选择不能重复')
        with current.read() as con:
            result = build_report(con, current.owner, start, end, base, step, selected)
        return jsonify(result)

    @app.get(PREFIX + '/operations/<request_id>')
    @guarded
    def finance_analysis_operation(current, request_id):
        query()
        identifier(request_id, 32)
        with current.read() as con:
            row = con.execute('SELECT result FROM finance_analysis_operations WHERE owner=? AND request_id=?',
                              (current.owner, request_id)).fetchone()
            receipt = {**json.loads(row['result']), 'replayed': True} if row else None
        return jsonify(requestId=request_id, found=row is not None, receipt=receipt)

    @app.put(PREFIX + '/accounts/<rid>/profile')
    @guarded
    def finance_analysis_profile(current, rid):
        identifier(rid)
        value = payload({'requestId', 'revision', 'assetClass', 'liquidity'})
        revision(value['revision'], zero=True)
        if type(value['assetClass']) is not str or value['assetClass'] not in CLASSES or \
                type(value['liquidity']) is not str or value['liquidity'] not in LIQUIDITIES:
            fail('分类或流动性不正确')
        def apply(con, owner, now):
            owned(con, owner, rid, active=True)
            old = con.execute('SELECT * FROM finance_account_profiles WHERE owner=? AND account_id=?', (owner, rid)).fetchone()
            if (old['revision'] if old else 0) != value['revision']:
                fail('分类已变化，请保留草稿并重新核对', 'revision_conflict', 409)
            con.execute('INSERT INTO finance_account_profiles VALUES(?,?,?,?,?,?) '
                        'ON CONFLICT(owner,account_id) DO UPDATE SET asset_class=excluded.asset_class,liquidity=excluded.liquidity,'
                        'revision=excluded.revision,updated_at=excluded.updated_at',
                        (owner, rid, value['assetClass'], value['liquidity'], value['revision']+1, now))
            return profile(con.execute('SELECT * FROM finance_account_profiles WHERE owner=? AND account_id=?', (owner, rid)).fetchone())
        return write(current, 'profile', rid, value, apply)

    @app.get(PREFIX + '/accounts/<rid>/cashflows')
    @guarded
    def finance_analysis_cashflows(current, rid):
        identifier(rid)
        query({'start', 'end', 'page', 'pageSize'})
        start, end = period(request.args.get('start'), request.args.get('end'))
        def paging(key, default, maximum):
            raw = request.args.get(key, str(default))
            if not re.fullmatch('[1-9][0-9]{0,5}', raw) or int(raw) > maximum:
                fail('分页参数不正确')
            return int(raw)
        page, size = paging('page', 1, MAX_CASHFLOWS), paging('pageSize', 50, 100)
        with current.read() as con:
            owned(con, current.owner, rid)
            params = current.owner, rid, start, end
            where = ' WHERE owner=? AND account_id=? AND as_of>? AND as_of<=?'
            total = con.execute('SELECT count(*) FROM finance_account_cashflows' + where, params).fetchone()[0]
            rows = con.execute('SELECT * FROM finance_account_cashflows' + where + ' ORDER BY as_of,id LIMIT ? OFFSET ?',
                               (*params, size, (page-1)*size)).fetchall()
            result = {'owner': current.owner, 'accountId': rid, 'start': start, 'end': end,
                      'items': [cashflow(row) for row in rows], 'page': page, 'pageSize': size, 'total': total}
        return jsonify(result)

    def cashflow_write(current, rid, fid=None, deleting=False):
        identifier(rid)
        if fid is not None:
            identifier(fid)
        fields = {'requestId', 'revision'} | (set() if deleting else {'date', 'direction', 'amountCents', 'note'})
        value = payload(fields)
        revision(value['revision'], zero=fid is None)
        if fid is None and value['revision'] != 0:
            fail('新增现金流版本须为零')
        if not deleting:
            day(value['date'])
            if type(value['direction']) is not str or value['direction'] not in ('in', 'out'):
                fail('请选择转入或转出')
            if type(value['amountCents']) is not int or not 0 <= value['amountCents'] <= MAX_AMOUNT:
                fail('现金流金额须为非负整数分')
            note = value['note']
            if type(note) is not str or len(note) > 1000 or any((ord(c) < 32 and c not in '\n\t') or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in note):
                fail('现金流备注格式不正确')
        operation = 'cashflow_delete' if deleting else 'cashflow_update' if fid else 'cashflow_create'
        def apply(con, owner, now):
            owned(con, owner, rid, active=True)
            if fid is not None:
                old = con.execute('SELECT * FROM finance_account_cashflows WHERE owner=? AND account_id=? AND id=?', (owner, rid, fid)).fetchone()
                if old is None:
                    fail('现金流不存在', 'cashflow_not_found', 404)
                if old['revision'] != value['revision']:
                    fail('现金流已变化，请保留草稿并重新核对', 'revision_conflict', 409)
                if deleting:
                    con.execute('DELETE FROM finance_account_cashflows WHERE owner=? AND account_id=? AND id=?', (owner, rid, fid))
                    return {'deleted': True, 'id': fid}
                con.execute('UPDATE finance_account_cashflows SET as_of=?,direction=?,amount_cents=?,note=?,revision=revision+1,updated_at=? '
                            'WHERE owner=? AND account_id=? AND id=?',
                            (value['date'], value['direction'], value['amountCents'], value['note'], now, owner, rid, fid))
                event_id = fid
            else:
                if con.execute('SELECT count(*) FROM finance_account_cashflows WHERE owner=?', (owner,)).fetchone()[0] >= MAX_CASHFLOWS:
                    fail('本人现金流已达到容量限制', 'capacity_exceeded', 409)
                event_id = secrets.token_hex(12)
                con.execute('INSERT INTO finance_account_cashflows VALUES(?,?,?,?,?,?,?,?,?,?)',
                            (event_id, owner, rid, value['date'], value['direction'], value['amountCents'], value['note'], 1, now, now))
            return cashflow(con.execute('SELECT * FROM finance_account_cashflows WHERE owner=? AND id=?', (owner, event_id)).fetchone())
        return write(current, operation, rid, value, apply)

    @app.post(PREFIX + '/accounts/<rid>/cashflows')
    @guarded
    def finance_analysis_cashflow_create(current, rid):
        return cashflow_write(current, rid)

    @app.patch(PREFIX + '/accounts/<rid>/cashflows/<fid>')
    @guarded
    def finance_analysis_cashflow_update(current, rid, fid):
        return cashflow_write(current, rid, fid)

    @app.delete(PREFIX + '/accounts/<rid>/cashflows/<fid>')
    @guarded
    def finance_analysis_cashflow_delete(current, rid, fid):
        return cashflow_write(current, rid, fid, True)

    @app.put(PREFIX + '/accounts/<rid>/reviews/<start>/<end>')
    @guarded
    def finance_analysis_review(current, rid, start, end):
        identifier(rid)
        start, end = period(start, end)
        value = payload({'requestId', 'revision', 'contextDigest', 'confirmed'})
        revision(value['revision'], zero=True)
        identifier(value['contextDigest'], 64)
        if value['confirmed'] is not True:
            fail('请明确确认本区间估值和外部资金进出已完整核对')
        def apply(con, owner, now):
            row = owned(con, owner, rid)
            points, flows = period_data(con, owner, row, start, end)
            review = period_review(con, owner, row, start, end, points, flows)
            if review['revision'] != value['revision']:
                fail('区间核对已变化，请重新读取', 'revision_conflict', 409)
            if review['contextDigest'] != value['contextDigest']:
                fail('账户、估值或现金流已变化，请保留草稿并重新核对', 'context_conflict', 409)
            if not review['canConfirm']:
                fail('请先补齐起止日的已知估值', 'missing_valuations', 409)
            con.execute('INSERT INTO finance_account_reviews VALUES(?,?,?,?,?,?,?) '
                        'ON CONFLICT(owner,account_id,start_date,end_date) DO UPDATE SET context_digest=excluded.context_digest,'
                        'revision=excluded.revision,confirmed_at=excluded.confirmed_at',
                        (owner, rid, start, end, review['contextDigest'], review['revision']+1, now))
            return {**review, 'revision': review['revision']+1, 'status': 'current', 'confirmedAt': now}
        return write(current, 'review', rid, value, apply)

    @app.post(PREFIX + '/rates/refresh')
    @guarded
    def finance_analysis_refresh(current):
        value = payload({'requestId', 'start', 'end'})
        start, end = period(value['start'], value['end'])
        expected_hash = fingerprint('rates_refresh', None, value)
        with current.read() as con:
            old = recover(con, current.owner, value['requestId'], expected_hash)
            if old is None:
                capacity(con, current.owner)
        if old is not None:
            return jsonify(**old, replayed=True)
        # The UI selects calendar dates in Shanghai; between local midnight and
        # 08:00 that date is still tomorrow in UTC. Keep the original payload for
        # idempotency and request only observations that can already exist.
        instant = datetime.now(timezone.utc)
        if date.fromisoformat(end) > instant.astimezone(ZoneInfo('Asia/Shanghai')).date():
            fail('汇率刷新截止日不可晚于北京时间今天，请调整日期后重试')
        observed_end = min(date.fromisoformat(end), instant.date()).isoformat()
        # current.read has released every SQLite transaction before network I/O.
        try:
            batch = fx.fetch_ecb_rates(lookback(start), observed_end)
        except fx.FxError as error:
            if error.code == 'fx_invalid_range':
                fail('公开汇率日期范围不可用，请检查起止日期后重试')
            fail('公共参考汇率暂不可用，已有缓存保持', 'rates_unavailable', getattr(error, 'status', 502))
        return write(current, 'rates_refresh', None, value,
                     lambda con, _owner, _now: fx.save_fx_batch(con, batch))
