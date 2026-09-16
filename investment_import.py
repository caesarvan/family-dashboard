"""Private, explicitly confirmed holdings snapshots. No bank or market access."""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import re
import secrets
import time
from datetime import datetime, timezone

from flask import g, jsonify, request, session
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from financial_files import read_financial_file


PREFIX = '/api/finance-hub/investments/imports'
COLUMNS = ['holdingKey', 'name', 'institution', 'assetType', 'currency', 'quantity', 'cost', 'value', 'asOf', 'note', 'recordId']
REQUIRED = {'holdingKey', 'name', 'institution', 'assetType', 'currency', 'cost', 'asOf'}
TEXT_COLUMNS = {'holdingKey', 'name', 'institution', 'assetType', 'currency', 'asOf', 'note', 'recordId'}
PREVIEW_SECONDS = 900
MAX_PREVIEWS = 20
MAX_HOLDINGS = 300
MAX_SOURCES = 300
MAX_RECEIPTS = 20_000


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def register_investment_import(app, db, Problem, body, require_member, audit, normalize, *, identity=None):
    with app.app_context():
        db().executescript('''
        CREATE TABLE IF NOT EXISTS hub_investment_sources(
            owner TEXT NOT NULL REFERENCES users(id), source_name TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL,
            PRIMARY KEY(owner,source_name));
        CREATE TABLE IF NOT EXISTS hub_investment_links(
            owner TEXT NOT NULL REFERENCES users(id), source_name TEXT NOT NULL,
            holding_key TEXT NOT NULL, investment_id TEXT NOT NULL, created_at TEXT NOT NULL,
            PRIMARY KEY(owner,source_name,holding_key), UNIQUE(owner,investment_id),
            FOREIGN KEY(owner,source_name) REFERENCES hub_investment_sources(owner,source_name));
        CREATE TABLE IF NOT EXISTS hub_investment_import_previews(
            id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), context_hash TEXT NOT NULL,
            source_name TEXT NOT NULL, source_digest TEXT NOT NULL, snapshot TEXT NOT NULL,
            expires_at REAL NOT NULL, created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS hub_investment_previews_owner ON hub_investment_import_previews(owner,expires_at);
        CREATE TABLE IF NOT EXISTS hub_investment_import_receipts(
            id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), source_name TEXT NOT NULL,
            source_digest TEXT NOT NULL, result TEXT NOT NULL, confirmed_at TEXT NOT NULL,
            UNIQUE(owner,source_name,source_digest));
        ''')
        db().commit()
    signer = URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='investment-import-preview-v1')

    def owner():
        require_member()
        return g.actor['id']

    def text(value, label, limit=120, required=True):
        if not isinstance(value, str):
            raise Problem(f'{label}须为文本')
        value = value.strip()
        try:
            value.encode('utf-8')
        except UnicodeError:
            raise Problem(f'{label}编码不正确') from None
        if len(value) > limit or (required and not value) or any(ord(c) < 32 for c in value):
            raise Problem(f'{label}为空、过长或含控制字符')
        return value

    def context(uid):
        # A token cannot be reused by another member, household, or login session.
        return digest({'owner': uid, 'household': app.config.get('HOUSEHOLD_INFO', {}).get('id', 'default'),
                       'csrf': session.get('csrf', '')})

    def portfolio(uid):
        return {'investments': [dict(r) for r in db().execute(
                    'SELECT id,data,revision FROM hub_investments WHERE owner=? ORDER BY id', (uid,))],
                'links': [dict(r) for r in db().execute(
                    'SELECT source_name,holding_key,investment_id FROM hub_investment_links WHERE owner=? ORDER BY source_name,holding_key', (uid,))],
                'sources': [dict(r) for r in db().execute(
                    'SELECT source_name,revision FROM hub_investment_sources WHERE owner=? ORDER BY source_name', (uid,))]}

    def investment(row):
        return {**json.loads(row['data']), 'id': row['id'], 'revision': row['revision']}

    def response_base(source, info):
        return {'sourceName': source, 'fileInfo': info, 'requiresSheetSelection': False, 'rows': [],
                'counts': {'create': 0, 'update': 0, 'unchanged': 0}, 'preservedCount': 0,
                'warnings': [], 'errors': [], 'errorCount': 0, 'previewToken': None}

    def add_error(result, line, message):
        result['errors'].append({'line': line, 'message': message})
        result['errorCount'] += 1

    def read_rows(content, result):
        reader = csv.reader(io.StringIO(content, newline=''), strict=True)
        rows, keys, ids = [], set(), set()
        try:
            header = next(reader, None)
            if not header:
                add_error(result, 1, '文件为空，请使用持仓整理表模板')
                return []
            header = [v.strip().lstrip('\ufeff') for v in header]
            if len(header) != len(set(header)) or '' in header:
                add_error(result, 1, '列名重复或为空，请使用持仓整理表模板')
                return []
            if set(header) - set(COLUMNS) - {'csvTextEncoding'} or not REQUIRED <= set(header):
                add_error(result, 1, '列名不符合持仓整理表模板；必需列：' + ', '.join(sorted(REQUIRED)))
                return []
            for values in reader:
                line = reader.line_num
                if not values or not any(v.strip() for v in values):
                    continue
                if len(rows) + result['errorCount'] >= MAX_HOLDINGS:
                    add_error(result, line, '每个文件最多 300 项持仓；没有截取或导入部分记录')
                    break
                if len(values) != len(header):
                    add_error(result, line, '该行列数与表头不同；请补全空列或检查引号')
                    continue
                item = dict(zip(header, values))
                encoding = item.pop('csvTextEncoding', '')
                if encoding not in {'', 'apostrophe-v1'}:
                    add_error(result, line, 'csvTextEncoding 只能为空或 apostrophe-v1')
                    continue
                if encoding:
                    if any(not item[k].startswith("'") for k in TEXT_COLUMNS if k in item):
                        add_error(result, line, '当前持仓导出表的文本保护前缀缺失，请重新导出')
                        continue
                    item = {k: v[1:] if k in TEXT_COLUMNS else v for k, v in item.items()}
                try:
                    key = text(item.pop('holdingKey'), '持仓编号')
                    record = text(item.pop('recordId', ''), 'recordId', 64, False)
                    if record and not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', record):
                        raise Problem('recordId 格式不正确')
                    if key in keys or (record and record in ids):
                        raise Problem('同一文件内持仓编号或 recordId 重复，请逐项核对')
                    keys.add(key)
                    if record:
                        ids.add(record)
                    for field in ('cost', 'value'):
                        raw_money = item.get(field, '').strip()
                        if not raw_money:
                            continue  # The common validator enforces required cost.
                        # Removing arbitrary commas silently changes European
                        # decimal commas or mistyped groups into larger amounts.
                        # This standard template explicitly uses decimal points;
                        # optional grouping must consist of complete triples.
                        if (',' in raw_money and '，' in raw_money) or not re.fullmatch(
                                r'(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]{1,2})?',
                                raw_money.replace('，', ',')):
                            raise Problem(f'{field} 金额须用小数点，逗号仅可为每三位一组的千分隔符；请核对原币种金额')
                    value = normalize(item)
                    value['valuationSource'] = 'file_import'
                    rows.append({'line': line, 'holdingKey': key, 'recordId': record, 'value': value})
                except ValueError as exc:
                    add_error(result, line, str(exc))
                except Problem as exc:
                    add_error(result, line, getattr(exc, 'message', str(exc)))
        except csv.Error:
            add_error(result, reader.line_num, 'CSV 引号或分隔格式不正确')
        if not rows and not result['errorCount']:
            add_error(result, 2, '文件没有持仓记录')
        return rows

    def assess(uid, source, rows, state, result):
        current = {r['id']: investment(r) for r in state['investments']}
        links = {(r['source_name'], r['holding_key']): r['investment_id'] for r in state['links']}
        by_id = {r['investment_id']: (r['source_name'], r['holding_key']) for r in state['links']}
        claimed = set()
        for item in rows:
            key, requested, after = item['holdingKey'], item['recordId'], item['value']
            linked = links.get((source, key))
            rid = linked or requested
            message = None
            before = current.get(rid) if rid else None
            if linked and requested and requested != linked:
                message = '该持仓编号已关联另一记录，不能通过文件更换关联'
            elif rid and not before:
                message = '指定记录不存在、不可访问或已删除；不会自动重新创建'
            elif requested and requested in by_id and by_id[requested] != (source, key):
                message = '该记录已属于另一来源或持仓编号，请保持原有来源和编号'
            elif rid and rid in claimed:
                message = '多行指向同一持仓，请先合并或修正编号'
            elif before and before['currency'] != after['currency']:
                message = '已有持仓币种不同，不能用导入更换币种或自动换汇'
            elif before and after['asOf'] < before['asOf']:
                message = '核对日期早于已有记录，旧日期不能覆盖新记录'
            elif before and before['valueCents'] is not None and after['valueCents'] is None:
                message = '已有估值时不能用空估值覆盖；请补充该日期估值或在投资编辑器明确调整'
            elif not before and any(all(x[k] == after[k] for k in ('name', 'institution', 'currency')) for x in current.values()):
                message = '存在同名称、机构和币种的持仓；请导出当前整理表并用 recordId 明确关联，不能自动新增'
            if message:
                add_error(result, item['line'], message)
                continue
            if rid:
                claimed.add(rid)
            comparison = {k: v for k, v in (before or {}).items() if k not in {'id', 'revision', 'valuationSource'}}
            comparable_after = {k: v for k, v in after.items() if k != 'valuationSource'}
            action = 'create' if before is None else 'unchanged' if comparison == comparable_after else 'update'
            entry = {'line': item['line'], 'holdingKey': key, 'action': action, 'before': before, 'after': after,
                     'warnings': [] if after['valueCents'] is not None else ['现值未知，保留待估值状态，不按零计算']}
            result['rows'].append(entry)
            result['counts'][action] += 1
        result['preservedCount'] = sum(1 for r in state['links'] if r['source_name'] == source and r['investment_id'] in current and r['investment_id'] not in claimed)
        if result['preservedCount']:
            result['warnings'].append(f'本次文件未包含该来源的 {result["preservedCount"]} 项已有持仓，将保留原值，不视为已清仓。')
        if len(current) + result['counts']['create'] > MAX_HOLDINGS:
            add_error(result, 0, '确认后将超过每人 300 项持仓上限，请先整理已有记录')
        if source not in {r['source_name'] for r in state['sources']} and len(state['sources']) >= MAX_SOURCES:
            add_error(result, 0, '来源数量已达到上限')

    def stage(uid, source, source_digest, snapshot):
        now = time.time()
        db().execute('DELETE FROM hub_investment_import_previews WHERE expires_at<=?', (now,))
        if db().execute('SELECT count(*) FROM hub_investment_import_previews WHERE owner=?', (uid,)).fetchone()[0] >= MAX_PREVIEWS:
            raise Problem('待确认预览已达 20 份，请稍后重试；预览在 15 分钟后过期', 429)
        pid = secrets.token_hex(16)
        db().execute('INSERT INTO hub_investment_import_previews VALUES(?,?,?,?,?,?,?,?)',
                     (pid, uid, context(uid), source, source_digest, canonical(snapshot), now + PREVIEW_SECONDS, stamp()))
        return signer.dumps({'id': pid, 'owner': uid, 'context': context(uid)})

    @app.get(PREFIX + '/template')
    def investment_import_template():
        uid = owner()
        if set(request.args) - {'mode', 'sourceName'} or request.args.get('mode', 'sample') not in {'sample', 'current'}:
            raise Problem('模板模式须为 sample 或 current')
        mode = request.args.get('mode', 'sample')
        warnings, output = [], io.StringIO(newline='')
        writer = csv.writer(output, lineterminator='\n')
        if mode == 'sample':
            writer.writerow(COLUMNS)
            writer.writerow(['sample-holding-001', '合成示例基金', '合成示例机构', '基金', 'CNY', '10', '100.00', '105.00', '2026-01-01', '虚构示例，请替换为本人核对的数据', ''])
            return jsonify(filename='investment-holdings-template.csv', csv=output.getvalue(), warnings=warnings, rowCount=1)
        source = text(request.args.get('sourceName', ''), '来源名称', 80)
        state = portfolio(uid)
        by_id = {r['investment_id']: r for r in state['links']}
        writer.writerow(COLUMNS + ['csvTextEncoding'])
        count, excluded = 0, 0
        for raw in state['investments']:
            value = investment(raw)
            link = by_id.get(value['id'])
            if link and link['source_name'] != source:
                excluded += 1
                continue
            row = {'holdingKey': link['holding_key'] if link else value['id'], 'recordId': value['id'],
                   **{k: value[k] for k in ('name', 'institution', 'assetType', 'currency', 'asOf', 'note')},
                   'quantity': value['quantity'] or '', 'cost': f'{value["costCents"] // 100}.{value["costCents"] % 100:02d}',
                   'value': '' if value['valueCents'] is None else f'{value["valueCents"] // 100}.{value["valueCents"] % 100:02d}'}
            # Explicit reversible encoding keeps spreadsheet formula-like labels inert.
            writer.writerow(["'" + str(row[k]) if k in TEXT_COLUMNS else row[k] for k in COLUMNS] + ['apostrophe-v1'])
            count += 1
        if excluded:
            warnings.append(f'已排除属于其他来源的 {excluded} 项持仓；请用对应来源名称分别导出。')
        warnings.append('包含该来源及尚未关联来源的本人记录；请删除不属于该账户的行。缺行会保留。文本保护列用于安全回导，请保留。')
        return jsonify(filename='investment-holdings-current.csv', csv=output.getvalue(), warnings=warnings, rowCount=count, sourceName=source)

    @app.post(PREFIX + '/preview')
    def investment_import_preview():
        uid, payload = owner(), body()
        if set(payload) - {'sourceName', 'file', 'inspectSheets'}:
            raise Problem('持仓预览包含不支持的字段')
        source = text(payload.get('sourceName'), '来源名称', 80)
        inspect = payload.get('inspectSheets', False)
        if type(inspect) is not bool:
            raise Problem('inspectSheets 必须为布尔值')
        file = payload.get('file')
        # A workbook cover may contain explanatory formulas. With no selected
        # sheet, perform only the existing safe structural discovery; never
        # parse that cover as holdings before the user can choose another tab.
        automatic_discovery = (isinstance(file, dict) and isinstance(file.get('name'), str)
                               and file['name'].lower().endswith('.xlsx') and file.get('sheet', '') == '')
        content, info = read_financial_file(file, inspect_sheets=inspect or automatic_discovery)
        result = response_base(source, info)
        if inspect or automatic_discovery:
            result['requiresSheetSelection'] = True
            result['warnings'] = ['仅发现工作表并检查工作簿结构，尚未解析或验证持仓记录。请选表后重新预览。']
            return jsonify(result)
        rows = read_rows(content, result)
        file_digest = hashlib.sha256(base64.b64decode(payload['file']['contentBase64'], validate=True)).hexdigest()
        source_digest = digest({'sourceName': source, 'fileSha256': file_digest, 'sheet': info['sheet'], 'encoding': info['encoding']})
        result['sourceDigest'] = source_digest
        db().execute('BEGIN IMMEDIATE')
        try:
            state = portfolio(uid)
            receipt = db().execute('SELECT id FROM hub_investment_import_receipts WHERE owner=? AND source_name=? AND source_digest=?', (uid, source, source_digest)).fetchone()
            if not result['errorCount'] and receipt:
                # A replay must not resurrect subsequently deleted or edited holdings.
                result['counts']['unchanged'] = len(rows)
                result['warnings'].append('这份文件此前已确认；再次确认只返回原回执，不会重写当前持仓或恢复已删除记录。')
                result['replayed'] = True
                result['previewToken'] = stage(uid, source, source_digest, {'receiptId': receipt['id']})
            else:
                assess(uid, source, rows, state, result)
                if not result['errorCount']:
                    if db().execute('SELECT count(*) FROM hub_investment_import_receipts WHERE owner=?', (uid,)).fetchone()[0] >= MAX_RECEIPTS:
                        raise Problem('持仓导入回执已达到上限', 409)
                    result['previewToken'] = stage(uid, source, source_digest,
                        {'portfolioDigest': digest(state), 'rows': result['rows'], 'counts': result['counts']})
            db().commit()
        except Exception:
            db().rollback()
            raise
        return jsonify(result)

    @app.get(PREFIX + '/receipts')
    def investment_import_receipt():
        uid = owner()
        if set(request.args) != {'sourceName', 'sourceDigest'} or any(len(request.args.getlist(k)) != 1 for k in request.args):
            raise Problem('请提供唯一的来源名称和来源摘要', 400)
        source = text(request.args.get('sourceName'), '来源名称', 80)
        source_digest = request.args.get('sourceDigest')
        if not re.fullmatch('[0-9a-f]{64}', source_digest):
            raise Problem('来源摘要必须为 64 位小写十六进制字符', 400)
        con = db()
        con.execute('BEGIN')
        try:
            expected = identity(con) if identity else uid
            row = con.execute('SELECT result FROM hub_investment_import_receipts '
                              'WHERE owner=? AND source_name=? AND source_digest=?', (uid, source, source_digest)).fetchone()
            value = {**json.loads(row['result']), 'replayed': True} if row else None
            con.commit()
            if identity and identity(con) != expected:
                raise Problem('登录成员或家庭已变化，请重新登录', 401)
            con.commit()
        except Exception:
            con.rollback()
            raise
        if not row:
            return jsonify(error='暂未读到这份持仓导入的结果，请保留原文件和预览后再次核对',
                           code='investment_import_receipt_not_found'), 404
        return jsonify(**value, sourceName=source, sourceDigest=source_digest)

    @app.post(PREFIX + '/confirm')
    def investment_import_confirm():
        uid, payload = owner(), body()
        if set(payload) != {'previewToken'} or not isinstance(payload.get('previewToken'), str) or len(payload['previewToken']) > 2048:
            raise Problem('请提交有效预览凭据；发现工作表或错误预览不能确认')
        try:
            signed = signer.loads(payload['previewToken'], max_age=PREVIEW_SECONDS)
        except (BadSignature, SignatureExpired):
            raise Problem('预览已过期或无效，请重新预览', 409) from None
        if not isinstance(signed, dict) or signed.get('owner') != uid or signed.get('context') != context(uid):
            raise Problem('预览不属于当前会话，请重新预览', 409)
        db().execute('BEGIN IMMEDIATE')
        try:
            row = db().execute('SELECT * FROM hub_investment_import_previews WHERE id=? AND owner=? AND context_hash=? AND expires_at>?',
                               (signed.get('id'), uid, context(uid), time.time())).fetchone()
            if not row:
                raise Problem('预览已过期或不存在，请重新预览', 409)
            receipt = db().execute('SELECT result FROM hub_investment_import_receipts WHERE owner=? AND source_name=? AND source_digest=?',
                                   (uid, row['source_name'], row['source_digest'])).fetchone()
            if receipt:
                result = {**json.loads(receipt['result']), 'replayed': True}
                db().commit()
                return jsonify(result)
            snapshot = json.loads(row['snapshot'])
            if snapshot.get('portfolioDigest') != digest(portfolio(uid)):
                raise Problem('持仓或来源已变化，请保留文件并重新预览；本次没有写入', 409)
            source, now = row['source_name'], stamp()
            db().execute('INSERT INTO hub_investment_sources(owner,source_name,updated_at) VALUES(?,?,?) '
                         'ON CONFLICT(owner,source_name) DO UPDATE SET revision=revision+1,updated_at=excluded.updated_at', (uid, source, now))
            for item in snapshot['rows']:
                before, value = item['before'], item['after']
                rid = before['id'] if before else secrets.token_hex(12)
                if item['action'] == 'create':
                    db().execute('INSERT INTO hub_investments(id,owner,data,updated_at) VALUES(?,?,?,?)', (rid, uid, canonical(value), now))
                elif item['action'] == 'update':
                    changed = db().execute('UPDATE hub_investments SET data=?,revision=revision+1,updated_at=? WHERE id=? AND owner=? AND revision=?',
                                           (canonical(value), now, rid, uid, before['revision']))
                    if changed.rowcount != 1:
                        raise Problem('持仓已变化，请重新预览', 409)
                db().execute('INSERT INTO hub_investment_links VALUES(?,?,?,?,?) ON CONFLICT(owner,source_name,holding_key) DO NOTHING',
                             (uid, source, item['holdingKey'], rid, now))
            rid = secrets.token_hex(16)
            counts = snapshot['counts']
            result = {'created': counts['create'], 'updated': counts['update'], 'unchanged': counts['unchanged'],
                      'replayed': False, 'receiptId': rid, 'confirmedAt': now}
            db().execute('INSERT INTO hub_investment_import_receipts VALUES(?,?,?,?,?,?)',
                         (rid, uid, source, row['source_digest'], canonical(result), now))
            audit('finance.investment.import', rid)
            db().commit()
        except Exception:
            db().rollback()
            raise
        return jsonify(result)

    app.extensions['investment_import'] = {'previewTTL': PREVIEW_SECONDS, 'maxHoldings': MAX_HOLDINGS}
