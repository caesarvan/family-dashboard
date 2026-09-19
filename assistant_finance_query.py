"""Read-only, session-bound finance questions; models never receive ledger data."""
from __future__ import annotations

from datetime import date, datetime
from http.client import HTTPException
import json
import re
import unicodedata
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo

from flask import jsonify, request

import home_assistant
from finance_hub import reconciliation_rows, transaction_totals
from finance_source_bridge import ImportSession


MAX_SAFE_INTEGER = 9007199254740991
MAX_REQUEST_BYTES = 16000
CATEGORIES = ('餐饮', '交通', '购物', '住房', '医疗', '教育', '娱乐', '旅行', '日用', '其他', '未分类')
CURRENCIES = {'人民币': 'CNY', 'RMB': 'CNY', '美元': 'USD', '港币': 'HKD',
              '欧元': 'EUR', '日元': 'JPY', '英镑': 'GBP', '澳元': 'AUD',
              '加元': 'CAD', '新加坡元': 'SGD',
              **{code: code for code in ('CNY', 'USD', 'HKD', 'EUR', 'JPY', 'GBP', 'AUD', 'CAD', 'SGD')}}
TOTAL_FIELDS = ('currency', 'expenseCents', 'refundCents', 'netSpendCents', 'count')
MODEL_FIELDS = {'scope', 'month', 'metric', 'currency', 'category'}


class FinanceQueryError(Exception):
    def __init__(self, message, code, status=400):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


def today():
    return datetime.now(ZoneInfo('Asia/Shanghai')).date()


def empty(status, message, mode='local'):
    return {'status': status, 'mode': mode, 'message': message, 'query': None,
            'totals': [], 'budgets': [], 'snapshot': None,
            'coverage': {'status': 'no_records', 'note': '尚未查询财务数据。',
                         'recordCount': 0, 'unknownCount': 0, 'orderCount': 0, 'duplicateCount': 0},
            'navigation': None}


def _alternatives(values):
    return '|'.join(re.escape(value) for value in sorted(values, key=len, reverse=True))


def parse_question(prompt, current_date, *, allow_model=False):
    """A conservative local interpretation is authoritative over model output.

    Unconsumed words, quoted instructions, unsupported date ranges or identities
    cannot silently turn into the default personal/current-month query.
    """
    text = unicodedata.normalize('NFKC', prompt).strip()
    clarify = lambda message: empty('clarify', message)
    unsupported = lambda message: empty('unsupported', message)
    if re.search(r'[\"\'“”‘’「」『』`]', text):
        return clarify('引号或代码中的文字不会作为查询指令；请直接写明要查询的财务范围。')
    if re.search(r'搜索|查找|找一下|(?:^|\s)search\b', text, re.I):
        return unsupported('这是查找指令，请使用原搜索入口；此接口只回答支出与预算问题。')
    if re.search(r'创建|新建|新增|添加|修改|删除|保存|设置|调整|转账|导入|记账|记一笔|扣款|支付|执行|取消|清空|清除|归零|更新|重置|增加|减少|设为|改|删|添|调高|调低|建立|安排|create|delete|update|set\b', text, re.I):
        return clarify('需求包含修改或执行动作。这里只读查询，请单独提出要查看的支出或预算问题。')
    if re.search(r'不要|不用|无需|不必|不想|不查|不看|不统计|别|禁止|不能|不可以|不准|排除|除了', text):
        return clarify('需求包含否定或排除条件，请明确单一要查看的范围。')
    if re.search(r'我和|我与|和我|与我|本人和|本人及|两人|两个人|所有人|每个人|各自|双方|分别', text):
        return clarify('请一次查询本人或明确共享的消费，不合并多人的私人账本。')
    if re.search(r'伴侣|老婆|老公|妻子|丈夫|对方|别人|他人|她的|他的|成员\s*\d|member\s*\d', text, re.I):
        return unsupported('不能查询伴侣或其他成员的私人账本；可明确查询成员已共享的消费。')

    public_words = ('公共荷包', '公共余额', '公共资金', '共同长期储蓄')
    shared_words = ('共享消费', '共同消费', '共享支出', '共同支出', '已共享')
    public = any(word in text for word in public_words)
    shared = any(word in text for word in shared_words)
    personal_tokens = re.findall(r'本人|我的|个人|自己|我', text)
    # "帮我查共同消费" describes the requester, not a request to combine scopes.
    personal = bool(re.search(r'本人|我的|个人|自己|我本月|我上月|我消费|我花', text))
    if sum((public, shared, personal)) > 1:
        return clarify('请只选择本人账本、共享消费或公共荷包中的一个范围。')
    if not shared and not public and re.search(r'家庭|我们|共同|共享', text):
        return clarify('请明确是本人账本、成员已共享的消费，还是公共荷包当前快照。')
    scope = 'public' if public else 'shared' if shared else 'personal'

    date_parts = list(re.finditer(r'(?<!\d)\d{4}-\d{2}(?![\d-])|上个月|这个月|本月|当月|上月', text))
    if len(date_parts) > 1:
        return clarify('请一次指定一个月份，不合并多个月份或日期。')
    without_date = text
    month = current_date.strftime('%Y-%m')
    if date_parts:
        match = date_parts[0]
        value = match.group()
        without_date = text[:match.start()] + text[match.end():]
        if value in {'上月', '上个月'}:
            previous = current_date.replace(day=1).toordinal() - 1
            month = date.fromordinal(previous).strftime('%Y-%m')
        elif value not in {'本月', '这个月', '当月'}:
            try:
                date.fromisoformat(value + '-01')
            except ValueError:
                return clarify('月份无效，请使用实际存在的 YYYY-MM。')
            month = value
    if re.search(r'\d|今年|去年|明年|今天|昨天|明天|本周|上周|季度|年度|[一二三四五六七八九十]+月|最近|过去|以来|截至|历史|至今|期间', without_date):
        return clarify('请写本月、上月或一个完整 YYYY-MM；不猜测年份、日期或多月范围。')
    if public and date_parts:
        return clarify('公共荷包只有手工确认的当前快照，没有月份历史账；请去掉月份后查询。')

    work = without_date
    currency_hits, currency_tokens = [], []
    currency_pattern = re.compile(_alternatives(CURRENCIES), re.I)
    def currency_match(match):
        token = match.group()
        currency_tokens.append(token)
        currency_hits.append(CURRENCIES.get(token, CURRENCIES.get(token.upper())))
        return ''
    work = currency_pattern.sub(currency_match, work)
    if len(set(currency_hits)) > 1:
        return clarify('请不指定币种以分别查看原币，或只指定一个币种；不合并或换汇。')
    currency = currency_hits[0] if currency_hits else None
    categories = []
    def category_match(match):
        categories.append(match.group())
        return ''
    work = re.sub(_alternatives(CATEGORIES), category_match, work)
    if len(set(categories)) > 1:
        return clarify('请一次指定一个分类，或不指定分类查看各预算；全部预算不与分类预算相加。')
    category = categories[0] if categories else None
    if category and re.search(r'全部|所有|各分类', text):
        return clarify('请只指定一个分类，或不指定分类查看全部；不会把全部与分类预算混在一起。')
    if scope == 'shared' and (category or '预算' in text):
        return unsupported('共享范围只提供成员已共享的消费总计，不提供分类或私人预算。')
    if scope == 'public' and (currency or category):
        return clarify('公共荷包为手工人民币当前快照，不支持币种或分类筛选。')

    has_budget = '预算' in text
    has_spending = bool(re.search(r'消费|支出|花了|花费|花销|退款', text))
    metric = 'summary' if re.search(r'概况|概览|汇总|总结|情况', text) or (has_budget and has_spending) else (
        'budget' if has_budget else 'spending')
    financial_language = has_budget or has_spending or public or metric == 'summary' or bool(re.search(r'钱|开销|用了|用掉', text))
    if not financial_language:
        return unsupported('目前只支持本人支出、退款后净支出、预算余额、明确共享消费和公共荷包快照。')
    words = (*public_words, *shared_words, '退款后净支出', '净支出', '退款后', '生活预算', '生活支出',
             '本人', '个人', '我的', '我', '消费', '支出', '花了', '花费', '花销', '退款', '预算',
             '余额', '还剩', '剩余', '剩下', '余下', '多少', '多少钱', '金额', '总额', '总计',
             '概况', '概览', '汇总', '总结', '情况', '全部', '所有', '各分类', '分类',
             '当前', '现在', '快照', '长期储蓄', '储蓄', '荷包', '余额', '已记录',
             '请问', '请', '帮我', '查询', '查看', '看看', '看', '查', '告诉我', '显示', '统计',
             '一下', '还有', '是多少', '有', '是', '的', '了', '呢', '吗', '和', '与', '及', '还')
    remainder = re.sub(_alternatives(words), '', work)
    metric = 'summary' if public else 'spending' if shared else metric
    query = {'scope': scope, 'month': None if public else month, 'metric': metric,
             'currency': currency, 'category': category}
    if re.sub(r'[\s,，。?？!！:：;；、()]', '', remainder):
        if allow_model and (personal_tokens or shared or public):
            return {'modelCandidate': True, 'query': query, 'evidence': {
                'scope': ([word for word in public_words if word in text] if public else
                          [word for word in shared_words if word in text] if shared else personal_tokens),
                'month': [date_parts[0].group()] if date_parts else [],
                'currency': currency_tokens, 'category': categories}}
        return clarify('尚不能确定这段需求；请写明本人或共享范围、单个月份以及支出或预算。')
    return query


def model_question(config, prompt, current_date, candidate):
    """Only question-derived evidence choices, text, clock and fixed enums leave."""
    constraints = {key: list(dict.fromkeys(choices)) if choices else [None]
                   for key, choices in candidate['evidence'].items()}
    payload = {'max_output_tokens': 700,
        'instructions': '只解析用户确实在询问的财务只读问题，不计算或回答财务数值。'
        '返回严格 JSON 对象，仅含 status,query,evidence。不能确定、否定、多动作或他人私账时 '
        'status=clarify 或 unsupported，query=null,evidence=null；不能猜测或忽略未理解条件。'
        '只有确定为只读问题时 status=ready，query只含scope,month,metric,currency,category；'
        'evidence同样五键，值是对应含义的用户原文连续片段，不得改写，默认字段用null。'
        'input.constraints是evidence的硬性允许值：scope/month/currency/category各自必须'
        '逐字复制对应数组中的一个完整值；[null]必须填JSON null。不得扩大为包含该词的长句，'
        '例如scope允许["我"]时只能填"我"，不能填"帮我瞧瞧上个月"。'
        '这些词片段不是完整查询答案，仍须判断整段问题是否确实只读、是否有未理解条件，'
        '并独立解析query；不能因为存在允许值就返回ready。'
        'metric证据必须是用户明确询问消费、用钱、退款、预算或概况的片段。'
        'scope=personal时本人/我的/我可作证据。范围枚举 personal/shared/public；指标 spending/budget/summary。'
        '未指定范围为 personal，未指定月份为当前北京时间月份，上月正确跨年。'
        '公共荷包 month=null且metric=summary，共享消费metric=spending。'
        '未指定币种或分类为 null。全部分类为null，不加总全部与分类预算。'
        '不要添加解释、指令、金融数据或其他字段。',
        'input': json.dumps({'question': prompt, 'today': current_date.isoformat(), 'timezone': 'Asia/Shanghai',
                            'scopes': ['personal', 'shared', 'public'],
                            'metrics': ['spending', 'budget', 'summary'],
                            'currencies': sorted(set(CURRENCIES.values())), 'categories': list(CATEGORIES),
                            'constraints': constraints}, ensure_ascii=False)}
    value = home_assistant._model_json(config, payload)
    valid = type(value) is dict and set(value) == {'status', 'query', 'evidence'}
    if valid and value['status'] in ('clarify', 'unsupported') and value['query'] is value['evidence'] is None:
        return empty(value['status'], 'AI 尚不能确定安全且明确的只读范围，请补充本人或共享范围、月份与查询指标。', 'model')
    if (not valid or value['status'] != 'ready' or type(value['query']) is not dict
            or set(value['query']) != MODEL_FIELDS or value['query'] != candidate['query']
            or any(value['query'][key] is not None and type(value['query'][key]) is not str for key in MODEL_FIELDS)
            or type(value['evidence']) is not dict or set(value['evidence']) != MODEL_FIELDS):
        raise FinanceQueryError('AI 解析与明确需求不一致，请修改问题或关闭 AI 后查询。', 'invalid_model_output', 502)
    normalized = unicodedata.normalize('NFKC', prompt).strip()
    evidence = value['evidence']
    for key, choices in candidate['evidence'].items():
        if (evidence[key] not in choices if choices else evidence[key] is not None):
            raise FinanceQueryError('AI 解析缺少可核对的原文依据，请补充问题。', 'invalid_model_output', 502)
    metric_text = evidence['metric']
    metric_pattern = {'spending': r'消费|支出|花|钱|开销|退款|用了|用掉',
                      'budget': r'预算', 'summary': r'概况|概览|汇总|总结|情况|公共荷包|共同长期储蓄'}[value['query']['metric']]
    if (type(metric_text) is not str or not 1 <= len(metric_text) <= 160 or metric_text not in normalized
            or not re.search(metric_pattern, metric_text)):
        raise FinanceQueryError('AI 解析缺少可核对的指标依据，请补充问题。', 'invalid_model_output', 502)
    return value['query']


def _ledger(con, owner=None):
    clause, args = (' WHERE owner=?', (owner,)) if owner is not None else ('', ())
    rows = [{**json.loads(row['data']), 'id': row['id']} for row in con.execute('SELECT * FROM hub_transactions' + clause, args)]
    links = [dict(row) for row in con.execute('SELECT * FROM hub_reconciliations' + clause, args)]
    return reconciliation_rows(rows, links)


def _category_rows(rows, category):
    if category is None:
        return rows
    selected = []
    for row in rows:
        if row['kind'] == 'payments' and row['flow'] == 'refund' and not row['reconciliation']['duplicateOf']:
            parts = [part for part in row['reconciliation']['categoryAllocations'] if part['category'] == category]
            if parts:
                selected.append({**row, 'amountCents': sum(part['amountCents'] for part in parts),
                    'reconciliation': {**row['reconciliation'], 'categoryAllocations': parts}})
        elif row['category'] == category:
            selected.append(row)
    return selected


def _safe(value):
    return type(value) is int and abs(value) <= MAX_SAFE_INTEGER


def answer(con, owner, query, mode):
    scope, month = query['scope'], query['month']
    result = empty('ready', '', mode)
    result['query'] = query
    if scope == 'public':
        row = con.execute("SELECT data FROM settings WHERE id='finance'").fetchone()
        data = json.loads(row['data']) if row else {}
        confirmed = data.get('confirmedAt')
        if not isinstance(confirmed, str) or not confirmed.strip():
            confirmed = None
        result['snapshot'] = {target: data.get(source) if confirmed and _safe(data.get(source)) else None
            for target, source in [('walletCents', 'wallet'), ('livingSpentCents', 'livingSpent'),
                                   ('livingBudgetCents', 'livingBudget'), ('savingsCents', 'longterm')]}
        result['snapshot']['confirmedAt'] = confirmed
        result['coverage'].update(status='manual_snapshot', note='手工确认的人民币当前快照；共同长期储蓄单列，未与旅行准备金相加。')
        result['message'] = ('公共荷包的手工确认当前快照，不代表任何月份的历史账。' if confirmed
                             else '公共荷包尚无手工确认的当前快照；所有金额未知，不能按零计算。')
        result['navigation'] = {'screen': 'finance', 'tab': 'shared', 'month': None}
        return result

    rows = _ledger(con, owner if scope == 'personal' else None)
    rows = [row for row in rows if row['date'].startswith(month)
            and (query['currency'] is None or row['currency'] == query['currency'])]
    if scope == 'shared':
        rows = [row for row in rows if row.get('visibility') == 'shared' and row['kind'] == 'payments'
                and row['flow'] in {'expense', 'refund'} and not row['reconciliation']['duplicateOf']]
    else:
        rows = _category_rows(rows, query['category'])
    totals = sorted(transaction_totals(rows), key=lambda row: row['currency'])
    result['totals'] = [{key: total[key] for key in TOTAL_FIELDS} for total in totals]
    if scope == 'personal' and query['metric'] in {'budget', 'summary'}:
        budgets = con.execute('SELECT currency,category,amount_cents FROM hub_budgets WHERE owner=? AND month=? ORDER BY currency,category', (owner, month))
        for budget in budgets:
            if query['currency'] is not None and budget['currency'] != query['currency']:
                continue
            if query['category'] is not None and budget['category'] != query['category']:
                continue
            subtotal = next((total for total in totals if total['currency'] == budget['currency']), {})
            spent = subtotal.get('netSpendCents', 0) if budget['category'] == '全部' else subtotal.get('categories', {}).get(budget['category'], 0)
            result['budgets'].append({'currency': budget['currency'], 'category': budget['category'],
                'amountCents': budget['amount_cents'], 'spentCents': spent, 'remainingCents': budget['amount_cents'] - spent})
    if any(not _safe(value) for collection in (result['totals'], result['budgets']) for row in collection
           for key, value in row.items() if key.endswith('Cents') or key == 'count'):
        return empty('unsupported', '当前汇总超出界面可精确表示的整数分范围，请缩小月份、币种或分类范围。', mode)
    unknown = sum(row['kind'] == 'payments' and row['flow'] == 'unknown' and not row['reconciliation']['duplicateOf'] for row in rows)
    orders = sum(row['kind'] == 'orders' for row in rows)
    duplicates = sum(bool(row['reconciliation']['duplicateOf']) for row in rows)
    note = ('仅成员逐笔确认的共享消费；不含私人分类、预算、明细或计数，不自动写公共荷包。' if scope == 'shared'
            else '仅已记录账本；订单与转账不计支出，确认重复已排除。退款按退款发生月计入，分类按已确认关联分摊；不代表完整财务。')
    if scope == 'personal' and (unknown or orders):
        note += f'本范围有 {unknown} 条待核对付款、{orders} 条订单，未代表已核实支出；净额为零不能据此认定实际消费为零。'
    result['coverage'] = {'status': 'no_records' if not rows else 'partial' if unknown or orders else 'recorded',
                          'note': note, 'recordCount': len(rows), 'unknownCount': unknown,
                          'orderCount': orders, 'duplicateCount': duplicates}
    result['message'] = ('本人' if scope == 'personal' else '成员已明确共享的消费') + '，月份 ' + month + '（北京时间月份）。'
    result['message'] += '各币种独立显示，不换汇；支出与退款分列，净支出为支出减退款。'
    if not rows:
        result['message'] += '此范围没有已记录账本，不能据此认定实际消费为零。'
    if scope == 'personal' and query['metric'] in {'budget', 'summary'}:
        result['message'] += ('全部与分类预算分别显示，不相加；余额仅扣除已记录净支出。' if result['budgets']
                              else '此范围尚未设置预算，未把缺少预算当作零额度。')
    result['navigation'] = {'screen': 'finance', 'tab': 'shared' if scope == 'shared' else (
        'budgets' if query['metric'] == 'budget' else 'ledger'), 'month': month}
    return result


def register_assistant_finance_query(app, db, Problem, body, require_member, limited):
    """Register after finance_hub/member sessions; no initialization or DDL."""
    @app.errorhandler(FinanceQueryError)
    def finance_query_error(error):
        response = jsonify(error=error.message, code=error.code)
        response.headers['Cache-Control'] = 'no-store'
        return response, error.status

    @app.post('/api/assistant/finance-query')
    def assistant_finance_query():
        current = ImportSession(app, db, Problem, require_member)
        current.fresh()
        if request.args:
            raise FinanceQueryError('查询不接受 URL 参数，请只提交问题。', 'invalid_request')
        if request.content_length is not None and request.content_length > MAX_REQUEST_BYTES:
            raise FinanceQueryError('问题过长，请精简后重试。', 'request_too_large', 413)
        value = body()
        if (not {'prompt'} <= set(value) <= {'prompt', 'useModel'} or type(value['prompt']) is not str
                or not 1 <= len(value['prompt'].strip()) <= 2000 or type(value.get('useModel', False)) is not bool
                or any(ord(char) < 32 and char not in '\n\r\t' for char in value['prompt'])):
            raise FinanceQueryError('请填写 1～2000 字的问题，useModel 须为布尔值。', 'invalid_request')
        prompt, clock = value['prompt'].strip(), today()
        query = parse_question(prompt, clock, allow_model=value.get('useModel', False))
        if 'status' in query:
            current.fresh()
            response = jsonify(query)
            response.headers['Cache-Control'] = 'no-store'
            return response
        mode = 'local'
        # Rate limiting commits only its existing attempts bookkeeping. Never
        # retain a finance/authorization read transaction over provider I/O.
        needs_model = query.get('modelCandidate', False)
        limited('assistant_plan' if needs_model else 'assistant_finance_query',
                30 if needs_model else 60, 3600 if needs_model else 600)
        if needs_model:
            current.fresh()
            try:
                query = model_question(app.config, prompt, clock, query)
                mode = 'model'
            except home_assistant.ModelProviderError as error:
                raise FinanceQueryError('AI 解析暂不可用；可关闭 AI 后使用本地查询。', 'model_unavailable', error.status) from None
            except (HTTPError, URLError, HTTPException, TimeoutError, OSError, ValueError, KeyError,
                    TypeError, OverflowError, RecursionError):
                raise FinanceQueryError('AI 解析格式无效或暂不可用；未查询财务。', 'invalid_model_output', 502) from None
            finally:
                current.fresh()
            if 'status' in query:
                response = jsonify(query)
                response.headers['Cache-Control'] = 'no-store'
                return response
        with current.read() as con:
            result = answer(con, current.owner, query, mode)
        response = jsonify(result)
        response.headers['Cache-Control'] = 'no-store'
        return response
