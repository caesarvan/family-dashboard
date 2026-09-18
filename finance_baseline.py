"""Dated finance imports with an explicit aggregate-only sharing boundary."""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import re
import sqlite3

from flask import g, jsonify


MAX_AMOUNT = 100_000_000_000_000
MAX_PAYLOAD_BYTES = 2_000_000
TOTAL_KEYS = ('complete', 'assetCents', 'liabilityCents', 'netCents',
              'recordedAssetCents', 'recordedLiabilityCents')
SHARED_KEYS = ('schemaVersion', 'owner', 'asOf', 'importedAt', 'currency',
               'sourceDigest', 'balanceAsOfStart', 'balanceAsOfEnd', *TOTAL_KEYS,
               'coverage', 'coverageNote', 'excluded')
EXCLUDED_KEYS = ('missingValuations', 'unconfirmedTransfers',
                 'foreignCurrencyConversion', 'unvestedCompensation',
                 'unconfirmedCreditBalances')


class BaselineError(ValueError):
    """Only fixed diagnostics; never include source values or account labels."""


def _fail(message='财务基线格式不正确'):
    raise BaselineError(message)


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        _fail('财务基线日期格式不正确')
    try:
        date.fromisoformat(value)
    except ValueError:
        _fail('财务基线日期格式不正确')
    return value


def _timestamp(value):
    if not isinstance(value, str) or len(value) > 40:
        _fail('财务基线导入时间格式不正确')
    try:
        if datetime.fromisoformat(value.replace('Z', '+00:00')).utcoffset() is None:
            _fail('财务基线导入时间必须包含时区')
    except ValueError:
        _fail('财务基线导入时间格式不正确')


def _amount(value, *, nullable=False, signed=False):
    if nullable and value is None:
        return
    if type(value) is not int or abs(value) > MAX_AMOUNT or (not signed and value < 0):
        _fail('财务金额必须是有效的整数分')


def _check_amounts(value, depth=0):
    if depth > 20:
        _fail('财务基线结构过深')
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                _fail()
            if key.endswith('Cents'):
                _amount(item, nullable=True, signed=key in ('netCents', 'netSpendCents'))
            else:
                _check_amounts(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _check_amounts(item, depth + 1)
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        _fail()


def _ensure_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS finance_baselines(
        owner TEXT PRIMARY KEY REFERENCES users(id),
        private_data TEXT NOT NULL,
        shared_data TEXT NOT NULL,
        source_digest TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        revision INTEGER NOT NULL DEFAULT 1,
        updated_at TEXT NOT NULL
    )''')


def _shared_view(value):
    """The only serialization path for family/TV responses."""
    result = {key: value[key] for key in SHARED_KEYS if key in value}
    result['excluded'] = {key: value.get('excluded', {}).get(key, False) is True
                          for key in EXCLUDED_KEYS}
    result['coverage'] = 'complete_dated_records' if result.get('complete') is True else 'partial_dated_records'
    result['coverageNote'] = (
        '汇总来自已核对的导入记录，金额以记录日期为准。'
        if result.get('complete') is True else
        '仅为已有人民币记录小计。记录日期不同，部分资产估值、余额和负债仍待核对，暂不计算完整净资产。'
    )
    return result


def _validate(conn, private, shared):
    if not isinstance(private, dict) or not isinstance(shared, dict):
        _fail()
    try:
        if len(_json({'private': private, 'shared': shared}).encode('utf-8')) > MAX_PAYLOAD_BYTES:
            _fail('财务基线文件过大')
    except (TypeError, ValueError, RecursionError):
        _fail()
    for payload in (private, shared):
        if type(payload.get('schemaVersion')) is not int or payload['schemaVersion'] != 1:
            _fail('财务基线版本不支持')
        if not isinstance(payload.get('owner'), str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', payload['owner']):
            _fail('财务基线所属成员不正确')
        if payload.get('currency') != 'CNY':
            _fail('共享财务汇总必须以人民币记录')
        if not isinstance(payload.get('sourceDigest'), str) or not re.fullmatch(r'[0-9a-f]{64}', payload['sourceDigest']):
            _fail('财务基线来源摘要不正确')
        for key in ('asOf', 'balanceAsOfStart', 'balanceAsOfEnd'):
            _date(payload.get(key))
        _timestamp(payload.get('importedAt'))
        if not payload['balanceAsOfStart'] <= payload['balanceAsOfEnd'] <= payload['asOf']:
            _fail('财务基线日期范围不正确')
        _check_amounts(payload)
    for key in ('owner', 'currency', 'schemaVersion', 'sourceDigest', 'asOf',
                'balanceAsOfStart', 'balanceAsOfEnd', 'importedAt'):
        if private[key] != shared[key]:
            _fail('私有数据与共享汇总的身份或版本不一致')
    if not conn.execute('SELECT 1 FROM users WHERE id=?', (private['owner'],)).fetchone():
        _fail('财务基线所属成员不存在')
    if not conn.execute("SELECT 1 FROM settings WHERE id='meta'").fetchone():
        _fail('家庭看板数据库尚未初始化')
    totals = private.get('totals')
    if not isinstance(totals, dict) or type(shared.get('complete')) is not bool:
        _fail('财务汇总完整度不正确')
    for key in TOTAL_KEYS:
        if key not in totals or key not in shared or totals[key] != shared[key] or type(totals[key]) is not type(shared[key]):
            _fail('私有数据与共享汇总金额不一致')
    for key in ('recordedAssetCents', 'recordedLiabilityCents'):
        _amount(shared[key])
    if shared['complete']:
        for key in ('assetCents', 'liabilityCents', 'netCents'):
            _amount(shared[key], signed=key == 'netCents')
        if (shared['assetCents'] != shared['recordedAssetCents'] or
                shared['liabilityCents'] != shared['recordedLiabilityCents'] or
                shared['netCents'] != shared['assetCents'] - shared['liabilityCents']):
            _fail('完整财务汇总金额不一致')
    elif any(shared[key] is not None for key in ('assetCents', 'liabilityCents', 'netCents')):
        _fail('资料不完整时不可发布完整资产、负债或净资产')
    excluded = shared.get('excluded', {})
    if not isinstance(excluded, dict) or any(type(excluded.get(k, False)) is not bool for k in EXCLUDED_KEYS):
        _fail('财务基线排除项格式不正确')
    for kind, total_key in (('assets', 'recordedAssetCents'), ('liabilities', 'recordedLiabilityCents'), ('income', None)):
        entries = private.get(kind)
        if not isinstance(entries, list) or len(entries) > 500:
            _fail('财务明细格式不正确')
        subtotal = 0
        for item in entries:
            if not isinstance(item, dict):
                _fail('财务明细格式不正确')
            for key in ('label', 'category', 'status', 'source'):
                if not isinstance(item.get(key), str) or not 1 <= len(item[key]) <= 2000:
                    _fail('财务明细缺少来源或分类')
            _date(item.get('asOf'))
            _amount(item.get('amountCents'), nullable=True)
            if not isinstance(item.get('currency'), str) or not re.fullmatch('[A-Z]{3}', item['currency']):
                _fail('财务明细币种不正确')
            if total_key:
                include = item.get('includedInRecordedSubtotal')
                if type(include) is not bool:
                    _fail('财务明细缺少汇总口径')
                if include:
                    if item['currency'] != shared['currency'] or item['amountCents'] is None:
                        _fail('缺失或外币金额不可直接计入人民币汇总')
                    subtotal += item['amountCents']
        if total_key and subtotal != shared[total_key]:
            _fail('共享汇总与逐项金额不一致')
    return _shared_view(shared)


def import_baseline(conn, private, shared):
    """Atomically upsert one member; preserve every unrelated household record."""
    shared = _validate(conn, private, shared)
    # Regenerating an identical source payload only changes its import timestamp.
    comparable = {name: {k: v for k, v in value.items() if k != 'importedAt'}
                  for name, value in (('private', private), ('shared', shared))}
    fingerprint = hashlib.sha256(_json(comparable).encode('utf-8')).hexdigest()
    counts = {kind: len(private[kind]) for kind in ('assets', 'liabilities', 'income')}
    conn.execute('SAVEPOINT finance_baseline_import')
    try:
        _ensure_schema(conn)
        row = conn.execute('SELECT content_hash, revision FROM finance_baselines WHERE owner=?', (private['owner'],)).fetchone()
        if row and row[0] == fingerprint:
            conn.execute('RELEASE SAVEPOINT finance_baseline_import')
            return {'imported': False, 'counts': counts, 'revision': row[1]}
        revision = row[1] + 1 if row else 1
        conn.execute('''INSERT INTO finance_baselines(owner,private_data,shared_data,source_digest,content_hash,revision,updated_at)
                        VALUES(?,?,?,?,?,?,?) ON CONFLICT(owner) DO UPDATE SET
                        private_data=excluded.private_data, shared_data=excluded.shared_data,
                        source_digest=excluded.source_digest, content_hash=excluded.content_hash,
                        revision=excluded.revision, updated_at=excluded.updated_at''',
                     (private['owner'], _json(private), _json(shared), private['sourceDigest'],
                      fingerprint, revision, datetime.now(timezone.utc).isoformat(timespec='seconds')))
        conn.execute("UPDATE settings SET revision=revision+1 WHERE id='meta'")
        conn.execute('RELEASE SAVEPOINT finance_baseline_import')
        return {'imported': True, 'counts': counts, 'revision': revision}
    except Exception:
        conn.execute('ROLLBACK TO SAVEPOINT finance_baseline_import')
        conn.execute('RELEASE SAVEPOINT finance_baseline_import')
        raise


def shared_baselines(conn):
    rows = conn.execute('SELECT shared_data,revision FROM finance_baselines ORDER BY owner').fetchall()
    return [{**_shared_view(json.loads(row[0])), 'revision': row[1]} for row in rows]


def register_finance_baseline(app, db, require_member, bump=None):
    """Owner-scoped reader; optional preview/CAS imports register via finance_source_bridge."""
    with app.app_context():
        _ensure_schema(db())
        db().commit()

    @app.get('/api/finance-baseline/private')
    def private_baseline():
        require_member()
        sessions = app.extensions.get('member_sessions')
        if sessions is None:
            return jsonify(error='无法核对登录状态，请稍后重试'), 503
        actor, captured = dict(g.actor), dict(getattr(g, 'member_session', {}))
        con = db()

        def authenticated():
            current = sessions.current(con)
            if (current['id'] != captured.get('id')
                    or current['owner'] != captured.get('owner')
                    or current['owner'] != actor['id']
                    or current['auth_version'] != captured.get('auth_version')
                    or current['auth_version'] != actor.get('auth_version')
                    or actor.get('householdId') != app.config.get('HOUSEHOLD_INFO', {}).get('id', 'default')):
                raise sessions.Problem('会话已失效，请重新登录', 401)

        # Legacy-cookie resolution can open an implicit transaction. Neither
        # that snapshot nor the report snapshot may be reused for the last check.
        con.rollback()
        try:
            con.execute('BEGIN')
            authenticated()
            row = con.execute('SELECT private_data,revision FROM finance_baselines WHERE owner=?', (actor['id'],)).fetchone()
            result = None
            if row:
                from spending_observations import decorate_private_spending
                result = decorate_private_spending(con, actor['id'], {**json.loads(row[0]), 'revision': row[1]})
            con.rollback()
            authenticated()
            return jsonify(result)
        finally:
            # Also release any legacy-session bookkeeping opened by the fresh check.
            con.rollback()


def main(argv=None):
    """Bounded stdin import. Do not print data, exception details, or source paths."""
    import argparse
    from pathlib import Path
    import sys

    parser = argparse.ArgumentParser(description='从标准输入导入私有财务基线与共享汇总')
    parser.add_argument('--database', default='/data/household.sqlite3')
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.buffer.read(MAX_PAYLOAD_BYTES + 1)
        if len(raw) > MAX_PAYLOAD_BYTES:
            _fail('财务基线文件过大')
        payload = json.loads(raw.decode('utf-8-sig'))
        if not isinstance(payload, dict) or set(payload) != {'private', 'shared'}:
            _fail()
        target = Path(args.database).resolve()
        if not target.is_file():
            _fail('家庭看板数据库不存在')
        conn = sqlite3.connect(target.as_uri() + '?mode=rw', uri=True, timeout=15)
        try:
            conn.execute('PRAGMA foreign_keys=ON')
            result = import_baseline(conn, payload['private'], payload['shared'])
            conn.commit()
        finally:
            conn.close()
        print(json.dumps({'status': 'imported' if result['imported'] else 'unchanged', 'counts': result['counts']}, ensure_ascii=False))
        return 0
    except (BaselineError, json.JSONDecodeError, UnicodeError, sqlite3.Error, OSError):
        print('财务基线导入失败，请核对格式、成员及数据库状态。', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
