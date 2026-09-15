"""Owner-scoped household ledger, explicit CSV ingestion, and dated investments.

No platform credentials, web scraping, live quotes, or implicit balance writes.
The signed import preview is stateless: preview never writes a ledger row.
"""
from __future__ import annotations

from collections import Counter
import csv
import hashlib
import io
import json
import re
import secrets
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from flask import g, jsonify, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from financial_files import FinancialFileError, read_financial_file

SOURCES = {'generic', 'alipay', 'wechat', 'taobao', 'pinduoduo'}
KINDS = {'payments', 'orders'}
FLOWS = {'expense', 'income', 'refund', 'transfer', 'unknown', 'excluded'}
MAX_CSV_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000
MAX_RECORDS = 20_000
MAX_MONEY = 100_000_000_000_000
ALIASES = {
    'date': ['date', '日期', '交易时间', '交易创建时间', '创建时间', '付款时间', '支付时间', '订单创建时间', '下单时间', '订单支付时间'],
    'amount': ['amount', '金额', '金额(元)', '金额（元）', '交易金额', '交易金额(元)', '订单金额', '实付款', '买家实际支付金额', '实付金额', '订单实付金额', '总金额'],
    'title': ['title', '名称', '商品', '商品名称', '商品说明', '商品标题', '交易对方', '订单商品', '商品信息', '备注'],
    'flow': ['flow', '收/支', '收支', '收支类型', '收支分类', '资金流向'],
    'externalId': ['id', 'externalid', '交易号', '交易单号', '交易订单号', '订单号', '订单编号', '商户单号', '商家订单号'],
    'merchantOrderId': ['merchantorderid', '商户订单号', '商家订单号', '商户单号', '商家单号'],
    'paymentId': ['paymentid', '支付交易号', '支付单号', '支付宝交易号', '微信支付单号'],
    'originalTransactionId': ['originaltransactionid', '原交易号', '原交易单号', '原支付单号'],
    'category': ['category', '分类', '类别', '交易分类', '交易类型'],
    'currency': ['currency', '币种', '货币', '货币种类'],
    'status': ['status', '状态', '当前状态', '交易状态', '订单状态'],
}


class FinanceHubError(ValueError):
    pass


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def current_month():
    return datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m')


def clean(value, limit=200, required=False):
    if not isinstance(value, str):
        raise FinanceHubError('文本字段格式不正确')
    value = value.strip().strip('\ufeff').strip()
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:
        raise FinanceHubError('文本编码不正确') from None
    if len(value) > limit or '\x00' in value or (required and not value):
        raise FinanceHubError('文本字段为空或超过长度限制')
    return value


def valid_date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise FinanceHubError('日期应为 YYYY-MM-DD')
    try:
        date.fromisoformat(value)
    except ValueError:
        raise FinanceHubError('日期不存在') from None
    return value


def valid_month(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}', value):
        raise FinanceHubError('月份应为 YYYY-MM')
    valid_date(value + '-01')
    return value


def currency_code(value):
    value = clean(value, 10).upper()
    value = {'人民币': 'CNY', 'RMB': 'CNY', '美元': 'USD', '日元': 'JPY', '港币': 'HKD', '欧元': 'EUR'}.get(value, value)
    if not re.fullmatch('[A-Z]{3}', value):
        raise FinanceHubError('币种须为 CNY、USD 等三位字母代码')
    return value


def cents(value, optional=False):
    if optional and (value is None or value == ''):
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise FinanceHubError('金额格式不正确')
    raw = str(value).strip().replace(',', '').replace('，', '')
    raw = re.sub(r'^[¥￥]', '', raw)
    try:
        number = Decimal(raw)
    except InvalidOperation:
        raise FinanceHubError('金额格式不正确') from None
    if not number.is_finite() or number < 0 or number > MAX_MONEY // 100:
        raise FinanceHubError('金额必须为有限的非负金额')
    if number != number.quantize(Decimal('.01')):
        raise FinanceHubError('金额最多保留两位小数')
    return int(number * 100)


def header_key(value):
    return re.sub(r'\s+', '', value).strip('\ufeff').lower()


def column_label(index):
    """Human-readable spreadsheet position; API indices stay zero based."""
    result = ''
    while index >= 0:
        index, remainder = divmod(index, 26)
        result = chr(65 + remainder) + result
        index -= 1
    return result


def normalized_flow(raw, category, status, kind):
    """Conservative: transfers and ambiguous refunds cannot inflate income/spend."""
    text = ' '.join([raw, category, status]).lower()
    if any(word in text for word in ['交易关闭', '交易失败', '已关闭', '已取消', '待付款', '等待买家付款', '未支付', 'failed', 'cancelled']):
        return 'excluded'
    if any(word in category.lower() for word in ['转账', '还款', '提现', '充值', '余额宝', '零钱通', '理财申购', '理财赎回', 'transfer']):
        return 'transfer'
    if raw.lower() in FLOWS:
        return raw.lower()
    if '退款' in text or 'refund' in text:
        # Exporters sometimes attach refund state to the ORIGINAL expense. It is
        # not safe to reverse that full amount without an explicit refund row.
        if raw in {'收入', '收', '退款'} or raw.lower() in {'refund', 'credit'}:
            return 'refund'
        return 'unknown'
    if kind == 'orders':
        return 'unknown'
    if raw in {'支出', '支', '付款'} or raw.lower() in {'debit', 'expense'}:
        return 'expense'
    if raw in {'收入', '收', '收款'} or raw.lower() in {'credit', 'income'}:
        return 'income'
    if raw in {'不计收支', '其他', '不计收入支出', '/'}:
        return 'transfer' if raw != '其他' else 'unknown'
    return 'unknown'


def parse_import(payload):
    source = payload.get('source', 'generic')
    kind = payload.get('kind', 'payments')
    if not isinstance(source, str) or not isinstance(kind, str) or source not in SOURCES or kind not in KINDS:
        raise FinanceHubError('请选择有效的来源和账单类型')
    inspect_sheets = payload.get('inspectSheets', False)
    if type(inspect_sheets) is not bool:
        raise FinanceHubError('inspectSheets 必须为布尔值')
    if inspect_sheets and ('file' not in payload or 'amountColumn' in payload):
        raise FinanceHubError('请先选择 XLSX 工作表，再选择金额列并预览')
    file_info = None
    if 'file' in payload:
        if 'csv' in payload:
            raise FinanceHubError('请仅提交一个文件或 CSV 文本')
        text, file_info = read_financial_file(payload['file'], inspect_sheets=inspect_sheets)
    else:
        text = payload.get('csv')
    if inspect_sheets:
        return {'source': source, 'kind': kind, 'rows': [], 'errors': [], 'fileInfo': file_info,
                'errorCount': 0, 'warnings': [], 'amountSelection': None,
                'requiresAmountSelection': False, 'requiresSheetSelection': True}
    if not isinstance(text, str) or not text.strip() or '\x00' in text or '\ufffd' in text:
        raise FinanceHubError('请提交可读的 CSV 文本；乱码文件请改用 GB18030 编码读取')
    try:
        text_size = len(text.encode('utf-8'))
    except UnicodeEncodeError:
        raise FinanceHubError('CSV 文本编码不正确') from None
    if text_size > MAX_CSV_BYTES:
        raise FinanceHubError('表格文本最多 2 MB，请按月份拆分')
    lines = text.lstrip('\ufeff').splitlines()
    if len(lines) > MAX_ROWS * 5 + 100:
        raise FinanceHubError('文件行数过多，请按月份拆分')
    field_aliases = ALIASES
    if kind == 'orders' and source == 'taobao':
        field_aliases = {**ALIASES, 'date': [*ALIASES['date'], '订单提交时间']}
    elif kind == 'orders' and source == 'pinduoduo':
        # Keep existing product/title columns ahead of this exporter-specific
        # label, but prefer its product name to the generic notes fallback.
        titles = ALIASES['title']
        field_aliases = {**ALIASES, 'title': [*titles[:-1], '商品名', titles[-1]]}
    mapping = None
    start = None
    delimiter = ','
    for index, line in enumerate(lines[:60]):
        for sep in [',', '\t', ';']:
            try:
                columns = next(csv.reader([line], delimiter=sep, strict=True))
            except csv.Error:
                continue
            fields = {}
            for name, aliases in field_aliases.items():
                matches = [i for alias in aliases for i, label in enumerate(columns) if header_key(label) == header_key(alias)]
                if matches:
                    fields[name] = matches[0]
            if all(name in fields for name in ['date', 'amount']):
                mapping, start, delimiter = fields, index, sep
                break
        if mapping:
            break
    if mapping is None:
        raise FinanceHubError('未识别日期与金额列。请下载通用模板，或检查 CSV 列名')
    if len(columns) > 80:
        raise FinanceHubError('表头最多 80 列，请移除无关列')
    amount_indices = sorted({i for i, label in enumerate(columns)
                             if header_key(label) in {header_key(alias) for alias in ALIASES['amount']}})
    selected = amount_indices[0] if len(amount_indices) == 1 else None
    if 'amountColumn' in payload:
        selected = payload['amountColumn']
        if type(selected) is not int or selected not in amount_indices:
            raise FinanceHubError('金额列选择无效，请从当前文件识别到的金额列中重新选择')
    amount_selection = {'required': len(amount_indices) > 1, 'selectedIndex': selected,
                        'headerLine': start + 1,
                        'columns': [{'index': i, 'label': clean(columns[i], 200, required=True),
                                     'columnLabel': column_label(i)} for i in amount_indices]}
    result, errors, warnings, fingerprints = [], [], [], set()
    file_digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
    if 'currency' not in mapping:
        if source == 'generic':
            raise FinanceHubError('通用模板必须包含 currency / 币种列，不能推断币种')
        warnings.append('文件没有币种列；所选国内平台按 CNY 读取，请确认原账单币种。')
    if 'externalId' not in mapping:
        warnings.append('没有交易编号；按原文件和行位置保留记录，同一文件重传去重。其他文件中的相似支付需在关联与对账中确认，不自动合并。')
    if selected is None:
        return {'source': source, 'kind': kind, 'rows': [], 'errors': [], 'fileInfo': file_info,
                'errorCount': 0, 'warnings': warnings,
                'amountSelection': amount_selection, 'requiresAmountSelection': True}
    original_amount_column = mapping['amount']
    mapping['amount'] = selected
    try:
        reader = csv.reader(io.StringIO('\n'.join(lines[start + 1:])), delimiter=delimiter, strict=True)
        for row in reader:
            line_number = start + 1 + reader.line_num
            if not row or not any(value.strip() for value in row):
                continue
            if len(result) + len(errors) >= MAX_ROWS:
                raise FinanceHubError('每次最多导入 5000 行，请拆分文件')
            if len(row) > 80:
                errors.append({'line': line_number, 'message': '列数过多'})
                continue
            def cell(name, default=''):
                ix = mapping.get(name)
                return clean(row[ix].strip().lstrip("'`"), 500) if ix is not None and ix < len(row) else default
            try:
                raw_date = cell('date').replace('/', '-').replace('年', '-').replace('月', '-').replace('日', '')
                match = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T].*)?$', raw_date)
                if not match:
                    raise FinanceHubError('日期格式不正确')
                when = valid_date(f'{int(match[1]):04}-{int(match[2]):02}-{int(match[3]):02}')
                amount = cents(cell('amount'))
                currency = currency_code(cell('currency', 'CNY'))
                title = clean(cell('title') or '未命名记录', 200)
                category = clean(cell('category') or '未分类', 60)
                external = clean(cell('externalId'), 160)
                status = clean(cell('status'), 80)
                flow = normalized_flow(cell('flow'), category, status, kind)
                # Preserve the pre-selection fingerprint of this file/row. Choosing
                # another amount column must report a conflict, not create a second
                # payment. A malformed former default never produced a legacy row.
                identity_amount = amount
                if not external and selected != original_amount_column:
                    try:
                        identity_amount = cents(clean(row[original_amount_column].strip().lstrip("'`"), 500))
                    except (FinanceHubError, IndexError):
                        identity_amount = None
                identity = ([source, kind, external, flow] if external else
                            [source, kind, file_digest, line_number, when, title, identity_amount, currency, flow]
                            if identity_amount is not None else [source, kind, file_digest, line_number, 'amount-column-independent'])
                fingerprint = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
                if fingerprint in fingerprints:
                    warnings.append(f'第 {line_number} 行与本文件中已有记录编号/内容相同，确认时会跳过重复。')
                fingerprints.add(fingerprint)
                result.append({'date': when, 'amountCents': amount, 'currency': currency, 'title': title,
                               'category': category, 'externalId': external, 'status': status, 'flow': flow,
                               'merchantOrderId': clean(cell('merchantOrderId'), 160),
                               'paymentId': clean(cell('paymentId'), 160),
                               'originalTransactionId': clean(cell('originalTransactionId'), 160),
                               'source': source, 'kind': kind, 'fingerprint': fingerprint,
                               'visibility': 'private', 'line': line_number})
            except FinanceHubError as exc:
                errors.append({'line': line_number, 'message': str(exc)})
    except csv.Error:
        raise FinanceHubError('CSV 引号或分隔符不完整，请检查文件') from None
    if not result and not errors:
        raise FinanceHubError('没有可导入的记录')
    unknown = sum(r['flow'] == 'unknown' for r in result)
    if unknown:
        warnings.append(f'{unknown} 行方向或退款状态待核对，不计入支出或收入。')
    if kind == 'orders':
        warnings.append('订单单独统计采购金额，不再次计入支付账单支出，避免双重记账。')
    return {'source': source, 'kind': kind, 'rows': result, 'errors': errors[:50], 'fileInfo': file_info,
            'errorCount': len(errors), 'warnings': list(dict.fromkeys(warnings))[:30],
            'amountSelection': amount_selection, 'requiresAmountSelection': False}


def _schema(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS hub_transactions(
      id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), fingerprint TEXT NOT NULL,
      data TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
      UNIQUE(owner,fingerprint));
    CREATE INDEX IF NOT EXISTS hub_transactions_owner ON hub_transactions(owner);
    CREATE TABLE IF NOT EXISTS hub_imports(
      id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), digest TEXT NOT NULL,
      source TEXT NOT NULL, kind TEXT NOT NULL, imported_count INTEGER NOT NULL, created_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS hub_imports_owner ON hub_imports(owner);
    CREATE TABLE IF NOT EXISTS hub_investments(
      id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), data TEXT NOT NULL,
      revision INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS hub_investments_owner ON hub_investments(owner);
    CREATE TABLE IF NOT EXISTS hub_budgets(
      owner TEXT NOT NULL REFERENCES users(id), month TEXT NOT NULL, currency TEXT NOT NULL,
      category TEXT NOT NULL, amount_cents INTEGER NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
      PRIMARY KEY(owner,month,currency,category));
    CREATE TABLE IF NOT EXISTS hub_reconciliations(
      id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), kind TEXT NOT NULL,
      left_id TEXT NOT NULL, right_id TEXT NOT NULL, amount_cents INTEGER NOT NULL,
      status TEXT NOT NULL DEFAULT 'active', revision INTEGER NOT NULL DEFAULT 1,
      confirm_digest TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      UNIQUE(owner,kind,left_id,right_id));
    CREATE INDEX IF NOT EXISTS hub_reconciliations_owner ON hub_reconciliations(owner,status);
    ''')


def _row(row):
    return {**json.loads(row['data']), 'id': row['id'], 'revision': row['revision']}


def transaction_totals(rows):
    totals = {}
    for row in rows:
        cur = row['currency']
        group = totals.setdefault(cur, {'currency': cur, 'expenseCents': 0, 'incomeCents': 0,
                                      'refundCents': 0, 'transferCents': 0, 'unknownCents': 0,
                                      'orderCents': 0, 'excludedCents': 0, 'count': 0, 'categories': {},
                                      'duplicateCents': 0, 'duplicateCount': 0})
        amount, flow = row['amountCents'], row['flow']
        group['count'] += 1
        if row.get('reconciliation', {}).get('duplicateOf'):
            group['duplicateCents'] += amount
            group['duplicateCount'] += 1
        elif row['kind'] == 'orders':
            if flow != 'excluded':
                group['orderCents'] += amount
        else:
            group[flow + 'Cents'] += amount
            if flow in {'expense', 'refund'}:
                allocations = row.get('reconciliation', {}).get('categoryAllocations') if flow == 'refund' else None
                for part in allocations or [{'category': row['category'], 'amountCents': amount}]:
                    cat = part['category']
                    group['categories'][cat] = group['categories'].get(cat, 0) + (part['amountCents'] if flow == 'expense' else -part['amountCents'])
        group['netSpendCents'] = group['expenseCents'] - group['refundCents']
        group['recordedSurplusCents'] = group['incomeCents'] - group['netSpendCents']
    return list(totals.values())


def reconciliation_rows(rows, links):
    """Derived view only: immutable imported amounts remain in transaction data."""
    indexed = {row['id']: {**row, 'reconciliation': {'duplicateOf': None, 'relationCount': 0,
               'allocatedCents': 0, 'refundedCents': 0, 'categoryAllocations': []}} for row in rows}
    active = [link for link in links if link['status'] == 'active']
    for link in active:
        left, right = indexed.get(link['left_id']), indexed.get(link['right_id'])
        if not left or not right:
            continue
        left['reconciliation']['relationCount'] += 1
        right['reconciliation']['relationCount'] += 1
        amount = link['amount_cents']
        if link['kind'] == 'duplicate':
            left['reconciliation']['duplicateOf'] = right['id']
        elif link['kind'] == 'order_payment':
            left['reconciliation']['allocatedCents'] += amount
            right['reconciliation']['allocatedCents'] += amount
        elif link['kind'] == 'refund_payment':
            left['reconciliation']['allocatedCents'] += amount
            right['reconciliation']['refundedCents'] += amount
            left['reconciliation']['categoryAllocations'].append({'category': right['category'], 'amountCents': amount})
    for row in indexed.values():
        state = row['reconciliation']
        if row['flow'] == 'refund':
            remaining = row['amountCents'] - state['allocatedCents']
            if remaining:
                state['categoryAllocations'].append({'category': row['category'], 'amountCents': remaining})
        state['unallocatedCents'] = row['amountCents'] - state['allocatedCents']
        if row['kind'] == 'payments' and row['flow'] == 'expense':
            state['remainingAfterRefundCents'] = row['amountCents'] - state['refundedCents']
    return list(indexed.values())


def investment_totals(rows):
    totals = {}
    for row in rows:
        cur = row['currency']
        group = totals.setdefault(cur, {'currency': cur, 'costCents': 0, 'valuedCostCents': 0,
                                       'valueCents': 0, 'unvaluedCount': 0, 'count': 0, 'allocation': {}})
        group['count'] += 1
        group['costCents'] += row['costCents']
        if row['valueCents'] is None:
            group['unvaluedCount'] += 1
        else:
            group['valuedCostCents'] += row['costCents']
            group['valueCents'] += row['valueCents']
            kind = row['assetType']
            group['allocation'][kind] = group['allocation'].get(kind, 0) + row['valueCents']
        group['unrealizedGainCents'] = group['valueCents'] - group['valuedCostCents']
    for group in totals.values():
        group['allocation'] = [{'assetType': k, 'valueCents': v,
                                'percent': round(v / group['valueCents'] * 100, 2) if group['valueCents'] else None}
                               for k, v in group['allocation'].items()]
    return list(totals.values())


def register_finance_hub(app, db, Problem, body, require_member, audit):
    with app.app_context():
        _schema(db())
        db().commit()
    signer = URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='household-finance-preview-v1')

    @app.errorhandler(FinanceHubError)
    def handle_hub_error(exc):
        return jsonify(error=str(exc)), 400

    @app.errorhandler(FinancialFileError)
    def handle_file_error(exc):
        return jsonify(error=str(exc)), exc.status

    def owner():
        require_member()
        return g.actor['id']

    def fingerprint_payload(payload):
        content = {k: payload.get(k, 'generic' if k == 'source' else 'payments' if k == 'kind' else '')
                   for k in ('source', 'kind', 'csv', 'file')}
        if 'amountColumn' in payload:
            content['amountColumn'] = payload['amountColumn']
        if 'inspectSheets' in payload:
            content['inspectSheets'] = payload['inspectSheets']
        return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def get_owned(table, rid):
        uid = owner()
        row = db().execute(f'SELECT * FROM {table} WHERE id=? AND owner=?', (rid, uid)).fetchone()
        if not row:
            raise Problem('记录不存在', 404)
        return row

    def check_revision(payload, row):
        if type(payload.get('revision')) is not int or payload['revision'] != row['revision']:
            raise Problem('记录已更新，请刷新后重试', 409)

    reconciliation_signer = URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='finance-reconciliation-v1')

    def ledger(uid):
        rows = [_row(r) for r in db().execute('SELECT * FROM hub_transactions WHERE owner=?', (uid,))]
        links = [dict(r) for r in db().execute('SELECT * FROM hub_reconciliations WHERE owner=?', (uid,))]
        indexed, usage, touched, suppressed, parents = {r['id']: r for r in rows}, {}, {}, set(), set()
        pairs = set()
        for link in links:
            if link['status'] != 'active':
                continue
            pairs.add((link['kind'], link['left_id'], link['right_id']))
            for side in ('left', 'right'):
                rid = link[side + '_id']
                key = (link['kind'], side, rid)
                usage[key] = usage.get(key, 0) + link['amount_cents']
                touched[rid] = touched.get(rid, 0) + 1
            if link['kind'] == 'duplicate':
                suppressed.add(link['left_id'])
                parents.add(link['right_id'])
        return {'rows': rows, 'indexed': indexed, 'links': links, 'usage': usage,
                'touched': touched, 'suppressed': suppressed, 'parents': parents, 'pairs': pairs}

    def owned_pair(state, left_id, right_id):
        if not isinstance(left_id, str) or not isinstance(right_id, str):
            raise FinanceHubError('请选择两条本人记录')
        left, right = state['indexed'].get(left_id), state['indexed'].get(right_id)
        if not left or not right:
            raise Problem('记录不存在', 404)
        return left, right

    def pair_limit(state, kind, left, right):
        if kind not in {'order_payment', 'refund_payment', 'duplicate'}:
            raise FinanceHubError('对账关系类型不正确')
        if left['id'] == right['id'] or left['currency'] != right['currency']:
            raise FinanceHubError('只能关联两条不同的同币种记录')
        if left['id'] in state['suppressed'] or right['id'] in state['suppressed']:
            raise FinanceHubError('已确认为重复的记录不能再关联，请先撤销重复关系')
        if (kind, left['id'], right['id']) in state['pairs']:
            raise Problem('这两条记录已经关联，请先查看或撤销原关系', 409)
        if kind == 'duplicate':
            if left['kind'] != 'payments' or right['kind'] != 'payments' or left['flow'] != right['flow'] or left['flow'] not in {'expense', 'refund'} or left['amountCents'] != right['amountCents']:
                raise FinanceHubError('重复核对仅支持同币种、同金额、同方向的支付消费或退款')
            if state['touched'].get(left['id']):
                raise FinanceHubError('将排除的记录已有关联，请先撤销这些关系；保留记录的关系不受影响')
            limit = left['amountCents']
        else:
            if right['kind'] != 'payments' or right['flow'] != 'expense':
                raise FinanceHubError('右侧须为已核对的实际支付消费')
            if kind == 'order_payment' and (left['kind'] != 'orders' or left['flow'] == 'excluded'):
                raise FinanceHubError('左侧须为有效的购物订单')
            if kind == 'refund_payment' and (left['kind'] != 'payments' or left['flow'] != 'refund'):
                raise FinanceHubError('左侧须为独立退款记录，不能用原消费的退款状态代替')
            left_remaining = left['amountCents'] - state['usage'].get((kind, 'left', left['id']), 0)
            right_remaining = right['amountCents'] - state['usage'].get((kind, 'right', right['id']), 0)
            limit = min(left_remaining, right_remaining)
        if limit <= 0:
            raise FinanceHubError('可分配金额已用完，不能超出订单、付款或退款的原始金额')
        return limit

    def pair_evidence(kind, left, right):
        def identifiers(row):
            return {row.get(k, '') for k in ('externalId', 'merchantOrderId', 'paymentId', 'originalTransactionId')
                    if len(row.get(k, '')) >= 3 and row.get(k) not in {'unknown', '无编号'}}
        same_id = bool(identifiers(left) & identifiers(right))
        days = abs((date.fromisoformat(left['date']) - date.fromisoformat(right['date'])).days)
        same_amount = left['amountCents'] == right['amountCents']
        reasons = ['币种一致']
        if same_id:
            reasons.append('原交易号或商户订单号存在完全相同的值')
        reasons.append('原始金额相同' if same_amount else '金额不同，可核对部分付款或部分退款')
        reasons.append(f'记录日期相差 {days} 天')
        uncertainty = ['候选来自文件字段，尚未向原平台验证；相同金额和日期不能证明是同一笔交易。']
        if not same_id:
            uncertainty.append('没有相同的原始编号，请在原账单或订单中核实。')
        if left['visibility'] != right['visibility']:
            uncertainty.append('两条记录共享范围不同；关联不会改变任一原记录的可见范围。')
        if kind == 'refund_payment':
            uncertainty.append('仅分配输入的退款金额；剩余退款保留原分类，不会把原付款标成全额退款。')
        if kind == 'duplicate':
            uncertainty.append('确认后仅右侧保留记录计入收支，左侧原始记录保留且可撤销。')
        return {'reasons': reasons, 'uncertainty': uncertainty, 'identifierMatch': same_id,
                'dateDistanceDays': days, 'sameAmount': same_amount,
                'score': (100 if same_id else 0) + (20 if same_amount else 0) + max(0, 14 - days)}

    def public_link(link):
        return {'id': link['id'], 'kind': link['kind'], 'leftId': link['left_id'], 'rightId': link['right_id'],
                'amountCents': link['amount_cents'], 'status': link['status'], 'revision': link['revision'],
                'createdAt': link['created_at'], 'updatedAt': link['updated_at']}

    @app.get('/api/finance-hub/reconciliation')
    def hub_reconciliation():
        uid = owner()
        state = ledger(uid)
        focus = state['indexed'].get(request.args.get('transactionId', ''))
        if not focus:
            raise Problem('记录不存在', 404)
        query = clean(request.args.get('q', ''), 160).lower()
        candidates = []
        for other in state['rows']:
            if focus['id'] == other['id'] or focus['currency'] != other['currency']:
                continue
            if query and query not in ' '.join(str(other.get(k, '')) for k in ('title', 'externalId', 'merchantOrderId', 'paymentId', 'originalTransactionId')).lower():
                continue
            pairs = []
            for left, right in ((focus, other), (other, focus)):
                if left['kind'] == 'orders' and right['kind'] == 'payments':
                    pairs.append(('order_payment', left, right))
                if left['kind'] == 'payments' and left['flow'] == 'refund' and right['kind'] == 'payments' and right['flow'] == 'expense':
                    pairs.append(('refund_payment', left, right))
            if focus['kind'] == other['kind'] == 'payments' and focus['flow'] == other['flow']:
                pairs.append(('duplicate', focus, other))
            for kind, left, right in pairs:
                try:
                    maximum = pair_limit(state, kind, left, right)
                except (FinanceHubError, Problem):
                    continue
                evidence = pair_evidence(kind, left, right)
                nearby = evidence['dateDistanceDays'] <= (30 if kind == 'refund_payment' else 7)
                if not query and not evidence['identifierMatch'] and not (nearby and (evidence['sameAmount'] or kind == 'refund_payment')):
                    continue
                candidates.append({'kind': kind, 'left': left, 'right': right, 'maxAmountCents': maximum,
                                   'suggestedAmountCents': maximum, **evidence})
        candidates.sort(key=lambda item: (-item['score'], item['right']['id'], item['left']['id']))
        links = [r for r in state['links'] if focus['id'] in {r['left_id'], r['right_id']}]
        links.sort(key=lambda r: r['updated_at'], reverse=True)
        view = {row['id']: row for row in reconciliation_rows(state['rows'], state['links'])}
        return jsonify(transaction=view[focus['id']], candidates=candidates[:40], candidateCount=len(candidates),
                       truncated=len(candidates) > 40, relations=[{**public_link(r), 'left': state['indexed'].get(r['left_id']),
                       'right': state['indexed'].get(r['right_id'])} for r in links[:100]],
                       note='只搜索本人已导入记录。候选不是确认；可输入标题或原始编号查找其他同币种记录。')

    @app.post('/api/finance-hub/reconciliation/preview')
    def hub_reconciliation_preview():
        uid = owner()
        payload = body()
        if set(payload) - {'kind', 'leftId', 'rightId', 'amount'}:
            raise FinanceHubError('对账预览含不支持的字段')
        state = ledger(uid)
        left, right = owned_pair(state, payload.get('leftId'), payload.get('rightId'))
        kind = payload.get('kind')
        if not isinstance(kind, str):
            raise FinanceHubError('对账关系类型不正确')
        maximum = pair_limit(state, kind, left, right)
        amount = cents(payload['amount']) if 'amount' in payload else maximum
        if not 0 < amount <= maximum or (kind == 'duplicate' and amount != maximum):
            raise FinanceHubError('分配金额须大于零且不超过可用金额；重复记录须按完整金额核对')
        signed = {'owner': uid, 'kind': kind, 'leftId': left['id'], 'rightId': right['id'],
                  'leftRevision': left['revision'], 'rightRevision': right['revision'], 'amountCents': amount}
        return jsonify(**signed, left=left, right=right, **pair_evidence(kind, left, right),
                       previewToken=reconciliation_signer.dumps(signed), expiresInSeconds=1200,
                       effect='重复记录将从有效收支与预算中排除，原始记录保留。' if kind == 'duplicate' else
                       '关联退款按分配金额使用原付款的预算分类，退款仍按自身日期计入；原始金额和共享范围不变。' if kind == 'refund_payment' else
                       '记录订单对应的付款金额；订单不再次计入收支，付款原始金额和分类不变。')

    @app.post('/api/finance-hub/reconciliation/confirm')
    def hub_reconciliation_confirm():
        uid = owner()
        payload = body()
        token = payload.get('previewToken')
        if set(payload) != {'previewToken'} or not isinstance(token, str) or len(token) > 3000:
            raise FinanceHubError('请先预览对账关系')
        try:
            signed = reconciliation_signer.loads(token, max_age=1200)
        except (BadSignature, SignatureExpired):
            raise FinanceHubError('对账预览已过期，请重新核对') from None
        if signed.get('owner') != uid:
            raise Problem('对账预览不属于当前成员', 403)
        conn = db()
        conn.execute('BEGIN IMMEDIATE')
        try:
            digest = hashlib.sha256(token.encode()).hexdigest()
            existing = conn.execute('SELECT * FROM hub_reconciliations WHERE owner=? AND kind=? AND left_id=? AND right_id=?',
                                    (uid, signed['kind'], signed['leftId'], signed['rightId'])).fetchone()
            if existing and existing['status'] == 'active' and existing['confirm_digest'] == digest:
                conn.commit()
                return jsonify(relation=public_link(existing), replayed=True)
            state = ledger(uid)
            left, right = owned_pair(state, signed['leftId'], signed['rightId'])
            if left['revision'] != signed['leftRevision'] or right['revision'] != signed['rightRevision']:
                raise Problem('记录或关联已变化，请重新预览', 409)
            maximum = pair_limit(state, signed['kind'], left, right)
            if not 0 < signed['amountCents'] <= maximum:
                raise Problem('可分配金额已变化，请重新预览', 409)
            if not existing and len(state['links']) >= MAX_RECORDS:
                raise FinanceHubError('对账关系已达到 20000 条上限')
            rid, when = existing['id'] if existing else secrets.token_hex(12), stamp()
            if existing:
                conn.execute("UPDATE hub_reconciliations SET amount_cents=?,status='active',revision=revision+1,confirm_digest=?,updated_at=? WHERE id=? AND owner=?",
                             (signed['amountCents'], digest, when, rid, uid))
            else:
                conn.execute('INSERT INTO hub_reconciliations(id,owner,kind,left_id,right_id,amount_cents,confirm_digest,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                             (rid, uid, signed['kind'], left['id'], right['id'], signed['amountCents'], digest, when, when))
            conn.execute('UPDATE hub_transactions SET revision=revision+1 WHERE owner=? AND id IN (?,?)', (uid, left['id'], right['id']))
            audit('finance.reconciliation.confirm', rid)
            value = public_link(conn.execute('SELECT * FROM hub_reconciliations WHERE id=? AND owner=?', (rid, uid)).fetchone())
            conn.commit()
            return jsonify(relation=value, replayed=False)
        except Exception:
            conn.rollback()
            raise

    @app.post('/api/finance-hub/reconciliation/<rid>/revoke')
    def hub_reconciliation_revoke(rid):
        uid = owner()
        payload = body()
        conn = db()
        conn.execute('BEGIN IMMEDIATE')
        try:
            row = get_owned('hub_reconciliations', rid)
            if row['status'] == 'revoked' and type(payload.get('revision')) is int and payload['revision'] == row['revision'] - 1:
                conn.commit()
                return jsonify(relation=public_link(row), replayed=True)
            check_revision(payload, row)
            if row['status'] != 'active':
                raise Problem('关系已撤销，请刷新', 409)
            conn.execute("UPDATE hub_reconciliations SET status='revoked',revision=revision+1,updated_at=? WHERE id=? AND owner=?", (stamp(), rid, uid))
            conn.execute('UPDATE hub_transactions SET revision=revision+1 WHERE owner=? AND id IN (?,?)', (uid, row['left_id'], row['right_id']))
            audit('finance.reconciliation.revoke', rid)
            value = public_link(conn.execute('SELECT * FROM hub_reconciliations WHERE id=? AND owner=?', (rid, uid)).fetchone())
            conn.commit()
            return jsonify(relation=value, replayed=False)
        except Exception:
            conn.rollback()
            raise

    @app.get('/api/finance-hub/template')
    def hub_template():
        owner()
        kind = request.args.get('kind', 'payments')
        if kind not in KINDS:
            raise FinanceHubError('类型不正确')
        return jsonify(filename=f'household-{kind}-template.csv', csv='date,title,amount,currency,flow,category,id,status\n2026-09-01,示例记录（请替换）,100.00,CNY,expense,餐饮,example-001,已完成\n',
                       encoding='UTF-8', note='金额为非负数，flow 使用 expense/income/refund/transfer/unknown/excluded。订单不计入支付支出。')

    @app.post('/api/finance-hub/imports/preview')
    def hub_preview():
        uid = owner()
        payload = body()
        parsed = parse_import(payload)
        parsed.setdefault('requiresSheetSelection', False)
        existing = {r[0] for r in db().execute('SELECT fingerprint FROM hub_transactions WHERE owner=?', (uid,))}
        seen = set(existing)
        for row in parsed['rows']:
            row['duplicate'] = row['fingerprint'] in seen
            seen.add(row['fingerprint'])
        parsed['duplicateCount'] = sum(row['duplicate'] for row in parsed['rows'])
        parsed['newCount'] = len(parsed['rows']) - parsed['duplicateCount']
        parsed['totals'] = transaction_totals([row for row in parsed['rows'] if not row['duplicate']])
        parsed['previewToken'] = signer.dumps({'owner': uid, 'digest': fingerprint_payload(payload)}) if not parsed['errorCount'] and not parsed['requiresAmountSelection'] and not parsed['requiresSheetSelection'] else None
        parsed['expiresInSeconds'] = 1200
        return jsonify(parsed)

    @app.post('/api/finance-hub/imports/confirm')
    def hub_confirm():
        uid = owner()
        payload = body()
        if 'inspectSheets' in payload and type(payload['inspectSheets']) is not bool:
            raise FinanceHubError('inspectSheets 必须为布尔值')
        if payload.get('inspectSheets'):
            raise FinanceHubError('工作表列表不能确认入账，请选择工作表并重新预览')
        token = payload.get('previewToken')
        if not isinstance(token, str) or len(token) > 2000:
            raise FinanceHubError('请先预览文件')
        try:
            signed = signer.loads(token, max_age=1200)
        except (BadSignature, SignatureExpired):
            raise FinanceHubError('预览已过期或无效，请重新预览') from None
        digest = fingerprint_payload(payload)
        if signed != {'owner': uid, 'digest': digest}:
            raise FinanceHubError('文件或账户已变化，请重新预览')
        parsed = parse_import(payload)
        if parsed['requiresAmountSelection']:
            raise FinanceHubError('请先选择金额列并重新预览')
        if parsed['errorCount']:
            raise FinanceHubError('文件含无效行，请修正后重新预览')
        conn = db()
        conn.execute('BEGIN IMMEDIATE')
        try:
            existing = {r['fingerprint']: _row(r) for r in conn.execute('SELECT * FROM hub_transactions WHERE owner=?', (uid,))}
            inserted, duplicates, conflicts = 0, 0, 0
            for row in parsed['rows']:
                key = row['fingerprint']
                if key in existing:
                    duplicates += 1
                    old = existing[key]
                    if any(old.get(k) != row.get(k) for k in ['amountCents', 'currency', 'date']):
                        conflicts += 1
                    continue
                if len(existing) >= MAX_RECORDS:
                    raise FinanceHubError('每位成员最多保存 20000 条流水，请先清理历史数据')
                row.pop('line', None)
                row['importedAt'] = stamp()
                row['checkedAt'] = None
                rid = secrets.token_hex(12)
                conn.execute('INSERT INTO hub_transactions(id,owner,fingerprint,data,created_at) VALUES(?,?,?,?,?)',
                             (rid, uid, key, json.dumps(row, ensure_ascii=False), stamp()))
                existing[key] = row
                inserted += 1
            # Count unique persisted records, including the retained version of a conflict.
            result_keys = {row['fingerprint'] for row in parsed['rows']}
            result_counts = Counter(existing[key]['date'][:7] for key in result_keys)
            result_months = [{'month': value, 'recordCount': result_counts[value]} for value in sorted(result_counts, reverse=True)]
            if inserted:
                bid = secrets.token_hex(12)
                conn.execute('INSERT INTO hub_imports VALUES(?,?,?,?,?,?,?)',
                             (bid, uid, digest, parsed['source'], parsed['kind'], inserted, stamp()))
                audit('finance.import', bid)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return jsonify(imported=inserted, duplicates=duplicates, conflicts=conflicts,
                       confirmedAt=stamp(), resultMonths=result_months,
                       note='导入仅保存到本人账本。未修改公共余额；编号冲突的旧记录保持原值，请在原文件核对。')

    @app.get('/api/finance-hub/overview')
    def hub_overview():
        uid = owner()
        month = valid_month(request.args.get('month', current_month()))
        state = ledger(uid)
        rows = reconciliation_rows(state['rows'], state['links'])
        month_counts = Counter(row['date'][:7] for row in rows)
        available_months = [{'month': value, 'recordCount': month_counts[value]} for value in sorted(month_counts, reverse=True)]
        selected = [r for r in rows if r['date'].startswith(month)]
        selected.sort(key=lambda r: (r['date'], r['id']), reverse=True)
        investments = [_row(r) for r in db().execute('SELECT * FROM hub_investments WHERE owner=? ORDER BY updated_at DESC', (uid,))]
        budgets = [dict(r) for r in db().execute('SELECT month,currency,category,amount_cents AS amountCents,revision FROM hub_budgets WHERE owner=? AND month=? ORDER BY currency,category', (uid, month))]
        totals = transaction_totals(selected)
        for budget in budgets:
            subtotal = next((v for v in totals if v['currency'] == budget['currency']), {})
            budget['spentCents'] = subtotal.get('netSpendCents', 0) if budget['category'] == '全部' else subtotal.get('categories', {}).get(budget['category'], 0)
            budget['remainingCents'] = budget['amountCents'] - budget['spentCents']
        batches = [dict(r) for r in db().execute('SELECT id,source,kind,imported_count AS importedCount,created_at AS createdAt FROM hub_imports WHERE owner=? ORDER BY created_at DESC LIMIT 12', (uid,))]
        return jsonify(month=month, transactions=selected[:500], transactionCount=len(selected), totalRecordCount=len(rows),
                       availableMonths=available_months, truncated=len(selected) > 500, totals=totals, investments=investments,
                       investmentTotals=investment_totals(investments), budgets=budgets, imports=batches,
                       coverage='仅已导入记录；候选关联须本人确认，已确认重复才排除，不能视为全部财务资产。',
                       connectors=[{'id': s, 'mode': 'csv', 'status': 'manual_import'} for s in sorted(SOURCES - {'generic'})],
                       institutionsStatus='manual_dated_records')

    @app.get('/api/finance-hub/shared')
    def hub_shared():
        # This route deliberately omits account identifiers, sources, titles,
        # external IDs, owners, categories, investment holdings, and incomes.
        owner()
        month = valid_month(request.args.get('month', current_month()))
        rows = reconciliation_rows([_row(r) for r in db().execute('SELECT * FROM hub_transactions')],
                                   [dict(r) for r in db().execute('SELECT * FROM hub_reconciliations')])
        selected = [r for r in rows if r.get('visibility') == 'shared' and r['date'].startswith(month)
                    and r['kind'] == 'payments' and r['flow'] in {'expense', 'refund'}
                    and not r['reconciliation']['duplicateOf']]
        totals = [{k: row[k] for k in ['currency', 'expenseCents', 'refundCents', 'netSpendCents', 'count']}
                  for row in transaction_totals(selected)]
        return jsonify(month=month, totals=totals, note='仅成员逐笔确认的共同消费，不自动写入公共荷包余额。')

    @app.patch('/api/finance-hub/transactions/<rid>')
    def hub_patch_transaction(rid):
        row = get_owned('hub_transactions', rid)
        payload = body()
        check_revision(payload, row)
        if set(payload) - {'revision', 'category', 'flow', 'visibility'}:
            raise FinanceHubError('仅可修改分类、收支方向及共享范围')
        value = json.loads(row['data'])
        if 'flow' in payload and payload['flow'] != value['flow'] and db().execute(
                "SELECT 1 FROM hub_reconciliations WHERE owner=? AND status='active' AND (left_id=? OR right_id=?) LIMIT 1",
                (g.actor['id'], rid, rid)).fetchone():
            raise Problem('这条记录仍有关联，请先撤销关联再修改收支方向', 409)
        if 'category' in payload:
            value['category'] = clean(payload['category'], 60, True)
        if 'flow' in payload:
            if not isinstance(payload['flow'], str) or payload['flow'] not in FLOWS:
                raise FinanceHubError('收支方向不正确')
            value['flow'] = payload['flow']
        if 'visibility' in payload:
            if not isinstance(payload['visibility'], str) or payload['visibility'] not in {'private', 'shared'}:
                raise FinanceHubError('共享范围不正确')
            value['visibility'] = payload['visibility']
        if value['visibility'] == 'shared' and (value['kind'] != 'payments' or value['flow'] not in {'expense', 'refund'}):
            raise FinanceHubError('只有消费与退款可纳入共同汇总；请先改为仅本人可见')
        value['checkedAt'] = stamp()
        updated = db().execute('UPDATE hub_transactions SET data=?,revision=revision+1 WHERE id=? AND owner=? AND revision=?',
                               (json.dumps(value, ensure_ascii=False), rid, g.actor['id'], row['revision']))
        if updated.rowcount != 1:
            db().rollback()
            raise Problem('记录已更新，请刷新后重试', 409)
        audit('finance.transaction.update', rid)
        db().commit()
        return jsonify({**value, 'id': rid, 'revision': row['revision'] + 1})

    @app.delete('/api/finance-hub/transactions/<rid>')
    def hub_delete_transaction(rid):
        row = get_owned('hub_transactions', rid)
        payload = body()
        check_revision(payload, row)
        if db().execute("SELECT 1 FROM hub_reconciliations WHERE owner=? AND status='active' AND (left_id=? OR right_id=?) LIMIT 1",
                        (g.actor['id'], rid, rid)).fetchone():
            raise Problem('这条记录仍有关联，请先撤销关联再删除', 409)
        deleted = db().execute('DELETE FROM hub_transactions WHERE id=? AND owner=? AND revision=?', (rid, g.actor['id'], row['revision']))
        if deleted.rowcount != 1:
            db().rollback()
            raise Problem('记录已更新，请刷新后重试', 409)
        audit('finance.transaction.delete', rid)
        db().commit()
        return jsonify(deleted=True)

    def investment_value(payload):
        allowed = {'name', 'institution', 'assetType', 'currency', 'quantity', 'cost', 'value', 'asOf', 'note', 'revision'}
        if set(payload) - allowed:
            raise FinanceHubError('投资记录含不支持的字段')
        raw_quantity = payload.get('quantity', '')
        if raw_quantity == '':
            quantity = None
        else:
            if not isinstance(raw_quantity, str) or not re.fullmatch(r'\d{1,15}(?:\.\d{1,8})?', raw_quantity):
                raise FinanceHubError('数量必须为非负数字，最多八位小数')
            quantity = raw_quantity
        return {'name': clean(payload.get('name', ''), 120, True),
                'institution': clean(payload.get('institution', ''), 120, True),
                'assetType': clean(payload.get('assetType', ''), 60, True),
                'currency': currency_code(payload.get('currency', '')),
                'quantity': quantity, 'costCents': cents(payload.get('cost')),
                'valueCents': cents(payload.get('value'), True), 'asOf': valid_date(payload.get('asOf')),
                'note': clean(payload.get('note', ''), 1000), 'valuationSource': 'manual', 'visibility': 'private'}

    @app.post('/api/finance-hub/investments')
    def hub_create_investment():
        uid = owner()
        value = investment_value(body())
        db().execute('BEGIN IMMEDIATE')
        if db().execute('SELECT count(*) FROM hub_investments WHERE owner=?', (uid,)).fetchone()[0] >= 300:
            db().rollback()
            raise FinanceHubError('每位成员最多 300 项投资记录')
        rid = secrets.token_hex(12)
        db().execute('INSERT INTO hub_investments(id,owner,data,updated_at) VALUES(?,?,?,?)', (rid, uid, json.dumps(value, ensure_ascii=False), stamp()))
        audit('finance.investment.create', rid)
        db().commit()
        return jsonify({**value, 'id': rid, 'revision': 1}), 201

    @app.patch('/api/finance-hub/investments/<rid>')
    def hub_update_investment(rid):
        row = get_owned('hub_investments', rid)
        payload = body()
        check_revision(payload, row)
        value = investment_value(payload)
        updated = db().execute('UPDATE hub_investments SET data=?,revision=revision+1,updated_at=? WHERE id=? AND owner=? AND revision=?',
                               (json.dumps(value, ensure_ascii=False), stamp(), rid, g.actor['id'], row['revision']))
        if updated.rowcount != 1:
            db().rollback()
            raise Problem('记录已更新，请刷新后重试', 409)
        audit('finance.investment.update', rid)
        db().commit()
        return jsonify({**value, 'id': rid, 'revision': row['revision'] + 1})

    @app.delete('/api/finance-hub/investments/<rid>')
    def hub_delete_investment(rid):
        row = get_owned('hub_investments', rid)
        check_revision(body(), row)
        deleted = db().execute('DELETE FROM hub_investments WHERE id=? AND owner=? AND revision=?', (rid, g.actor['id'], row['revision']))
        if deleted.rowcount != 1:
            db().rollback()
            raise Problem('记录已更新，请刷新后重试', 409)
        audit('finance.investment.delete', rid)
        db().commit()
        return jsonify(deleted=True)

    @app.put('/api/finance-hub/budgets')
    def hub_put_budget():
        uid = owner()
        payload = body()
        month, currency = valid_month(payload.get('month')), currency_code(payload.get('currency', ''))
        category = clean(payload.get('category', '全部'), 60, True)
        amount = cents(payload.get('amount'))
        db().execute('BEGIN IMMEDIATE')
        existing = db().execute('SELECT revision FROM hub_budgets WHERE owner=? AND month=? AND currency=? AND category=?', (uid, month, currency, category)).fetchone()
        expected = payload.get('revision', 0)
        if type(expected) is not int or expected != (existing['revision'] if existing else 0):
            db().rollback()
            raise Problem('预算已更新，请刷新后重试', 409)
        if not existing and db().execute('SELECT count(*) FROM hub_budgets WHERE owner=?', (uid,)).fetchone()[0] >= 1200:
            db().rollback()
            raise FinanceHubError('预算记录已达到上限')
        db().execute('INSERT INTO hub_budgets(owner,month,currency,category,amount_cents) VALUES(?,?,?,?,?) '
                     'ON CONFLICT(owner,month,currency,category) DO UPDATE SET amount_cents=excluded.amount_cents,revision=hub_budgets.revision+1',
                     (uid, month, currency, category, amount))
        audit('finance.budget.update', month)
        db().commit()
        return jsonify(saved=True, revision=expected + 1)

    # Share the existing money/date/private-record validator without changing
    # the payment/order parser or the semantics of manual investment editing.
    from investment_import import register_investment_import
    register_investment_import(app, db, Problem, body, require_member, audit, investment_value)
