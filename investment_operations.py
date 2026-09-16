"""Private current holdings and durable, owner-scoped manual operation receipts."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re

from flask import g, jsonify, request


INVESTMENT_OPERATIONS_SCHEMA_SQL = '''
CREATE TABLE IF NOT EXISTS hub_investment_operations(
  owner TEXT NOT NULL REFERENCES users(id), request_id TEXT NOT NULL,
  kind TEXT NOT NULL, record_id TEXT NOT NULL, payload_digest TEXT NOT NULL,
  result TEXT NOT NULL, completed_at TEXT NOT NULL,
  PRIMARY KEY(owner,request_id));
'''
MAX_OPERATIONS = 20_000
MAX_RESULT_STORAGE = 32 * 1024 * 1024


class InvestmentOperationError(Exception):
    def __init__(self, message, code, status=409):
        self.message, self.code, self.status = message, code, status


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def register_investment_operations(app, db, Problem, require_member, identity):
    """Register owner-only readers and return the shared atomic write helper."""
    with app.app_context():
        db().executescript(INVESTMENT_OPERATIONS_SCHEMA_SQL)
        db().commit()

    @app.errorhandler(InvestmentOperationError)
    def operation_error(exc):
        return jsonify(error=exc.message, code=exc.code), exc.status

    def request_id(value):
        if type(value) is not str or not re.fullmatch('[0-9a-f]{32}', value):
            raise Problem('操作编号必须为 32 位小写十六进制字符', 400)
        return value

    def no_query():
        if request.args:
            raise Problem('该读取接口不接受查询参数', 400)

    def actor():
        require_member()
        return g.actor['id']

    @app.get('/api/finance-hub/investments')
    def investment_current():
        uid = actor()
        no_query()
        con = db()
        con.execute('BEGIN')
        try:
            expected = identity(con)
            rows = con.execute('''SELECT i.*,l.source_name,l.holding_key
                FROM hub_investments i LEFT JOIN hub_investment_links l
                  ON l.owner=i.owner AND l.investment_id=i.id
                WHERE i.owner=? ORDER BY i.updated_at DESC,i.id''', (uid,)).fetchall()
            investments = [{**json.loads(row['data']), 'id': row['id'], 'revision': row['revision'],
                            'updatedAt': row['updated_at'],
                            'source': {'sourceName': row['source_name'], 'holdingKey': row['holding_key']}
                            if row['source_name'] is not None else None} for row in rows]
            sources = [dict(row) for row in con.execute('''SELECT s.source_name AS sourceName,
                s.revision,s.updated_at AS updatedAt,count(i.id) AS holdingCount,
                sum(CASE WHEN l.investment_id IS NOT NULL AND i.id IS NULL THEN 1 ELSE 0 END) AS deletedCount
                FROM hub_investment_sources s LEFT JOIN hub_investment_links l
                  ON l.owner=s.owner AND l.source_name=s.source_name
                LEFT JOIN hub_investments i ON i.owner=l.owner AND i.id=l.investment_id
                WHERE s.owner=? GROUP BY s.source_name,s.revision,s.updated_at ORDER BY s.source_name''', (uid,))]
            con.commit()
            # A second read inside BEGIN would still see the old snapshot.
            # End it before checking revocation performed by another writer.
            if identity(con) != expected:
                raise Problem('登录成员或家庭已变化，请重新登录', 401)
            con.commit()
        except Exception:
            con.rollback()
            raise
        return jsonify(investments=investments, sources=sources)

    @app.get('/api/finance-hub/investments/operations/<rid>')
    def investment_operation_result(rid):
        uid = actor()
        no_query()
        rid = request_id(rid)
        con = db()
        con.execute('BEGIN')
        try:
            expected = identity(con)
            row = con.execute('SELECT kind,record_id,result,completed_at FROM hub_investment_operations '
                              'WHERE owner=? AND request_id=?', (uid, rid)).fetchone()
            value = ({'requestId': rid, 'kind': row['kind'], 'recordId': row['record_id'],
                      'result': json.loads(row['result']), 'completedAt': row['completed_at']} if row else None)
            con.commit()
            if identity(con) != expected:
                raise Problem('登录成员或家庭已变化，请重新登录', 401)
            con.commit()
        except Exception:
            con.rollback()
            raise
        if not row:
            return jsonify(error='暂未读到该操作结果，请保留原操作编号后再次核对',
                           code='investment_operation_not_found'), 404
        return jsonify(value)

    class Operations:
        def execute(self, kind, record_id, payload, value, apply):
            uid = actor()
            modern = 'requestId' in payload
            rid = request_id(payload['requestId']) if modern else None
            if modern and kind == 'delete' and set(payload) - {'revision', 'requestId'}:
                raise Problem('删除投资记录含不支持的字段', 400)
            # Bind a key to the complete normalized operation, including the
            # caller's original version. Replay never consults the current row.
            fingerprint = None
            if modern:
                try:
                    content = canonical({'kind': kind, 'recordId': record_id,
                                         'revision': payload.get('revision'), 'value': value})
                    fingerprint = hashlib.sha256(content.encode('utf-8')).hexdigest()
                except (TypeError, ValueError, UnicodeError, RecursionError):
                    raise Problem('投资操作内容格式不正确', 400) from None
            con = db()
            con.execute('BEGIN IMMEDIATE')
            try:
                expected = identity(con)
                used_bytes = 0
                if modern:
                    old = con.execute('SELECT payload_digest,result FROM hub_investment_operations '
                                      'WHERE owner=? AND request_id=?', (uid, rid)).fetchone()
                    if old:
                        if old['payload_digest'] != fingerprint:
                            con.rollback()
                            return jsonify(error='该操作编号已用于其他内容，请核对原操作结果',
                                           code='operation_request_conflict'), 409
                        result = json.loads(old['result'])
                        con.commit()
                        if identity(con) != expected:
                            raise Problem('登录成员或家庭已变化，请重新登录', 401)
                        con.commit()
                        return jsonify(**result, requestId=rid, replayed=True), 201 if kind == 'create' else 200
                    capacity = con.execute('SELECT count(*),coalesce(sum(length(CAST(result AS BLOB))),0) '
                                           'FROM hub_investment_operations WHERE owner=?', (uid,)).fetchone()
                    used_bytes = capacity[1]
                    if capacity[0] >= MAX_OPERATIONS or used_bytes >= MAX_RESULT_STORAGE:
                        raise InvestmentOperationError('投资操作回执容量已满；原回执仍可读取，请先联系维护者扩容', 'operation_capacity')
                result = apply(con, uid)
                if modern:
                    stored = canonical(result)
                    if used_bytes + len(stored.encode('utf-8')) > MAX_RESULT_STORAGE:
                        raise InvestmentOperationError('投资操作回执容量已满；原回执仍可读取，请先联系维护者扩容', 'operation_capacity')
                    completed = datetime.now(timezone.utc).isoformat(timespec='seconds')
                    con.execute('INSERT INTO hub_investment_operations VALUES(?,?,?,?,?,?,?)',
                                (uid, rid, kind, result.get('id', record_id), fingerprint, stored, completed))
                con.commit()
                if identity(con) != expected:
                    raise Problem('登录成员或家庭已变化，请重新登录', 401)
                con.commit()
            except Exception:
                con.rollback()
                raise
            return jsonify(**result, **({'requestId': rid, 'replayed': False} if modern else {})), 201 if kind == 'create' else 200

    return Operations()
