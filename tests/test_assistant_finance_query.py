"""Synthetic records, real registered Flask/session/SQLite paths; provider I/O mocked."""
from contextlib import closing, contextmanager
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import socket
import sqlite3
import time

from flask import g
import pytest

import app as server
import assistant_finance_query as api
import home_assistant
from test_app import member
from test_device_sessions import install_connection, invalidate
from test_household_spaces import create_space


URL = '/api/assistant/finance-query'
MONTH = '2026-09'
MODEL_PROMPT = '帮我瞧瞧本月本人消费和预算情况'


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError('External network forbidden in synthetic finance tests')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket, 'create_connection', deny)
    monkeypatch.setattr(api, 'today', lambda: date(2026, 9, 19))


@pytest.fixture
def app(tmp_path):
    application = server.create_app({'TESTING': True, 'DATA_DIR': str(tmp_path / 'data'),
        'SECRET_KEY': 'synthetic-finance-query-key', 'SESSION_COOKIE_SECURE': False,
        'PUBLIC_ORIGIN': 'http://localhost', 'MEMBER1_PASSWORD': 'testing-password-one',
        'MEMBER2_PASSWORD': 'testing-password-two', 'ASSISTANT_PROVIDER': 'openai',
        'OPENAI_API_KEY': '', 'OPENAI_MODEL': '', 'NVIDIA_API_KEY': '', 'NVIDIA_MODEL': '',
        'MICROSOFT_CLIENT_ID': '', 'MICROSOFT_CLIENT_SECRET': '',
        'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': ''})
    routes = [rule for rule in application.url_map.iter_rules() if rule.rule == URL]
    assert len(routes) == 1 and routes[0].methods == {'POST', 'OPTIONS'}
    assert application.view_functions[routes[0].endpoint].__module__ == 'assistant_finance_query'
    return application


@contextmanager
def database(app):
    with closing(sqlite3.connect(Path(app.config['DATA_DIR']) / 'household.sqlite3', timeout=5)) as con:
        with con:
            yield con


def domain_snapshot(app):
    with database(app) as con:
        names = [row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        excluded = {'users', 'member_sessions', 'member_session_browsers', 'attempts'}
        return {name: sorted(con.execute('SELECT * FROM "' + name + '"').fetchall(), key=repr)
                for name in names if name not in excluded}


def seed(app, rid='expense', *, owner='member1', amount=10000, currency='CNY', flow='expense',
         kind='payments', category='餐饮', month=MONTH, visibility='private'):
    data = {'source': 'generic', 'kind': kind, 'date': month + '-03', 'title': 'PRIVATE_SYNTHETIC_TITLE',
            'amountCents': amount, 'currency': currency, 'flow': flow, 'category': category,
            'visibility': visibility, 'externalId': 'PRIVATE_SYNTHETIC_ORDER', 'status': '成功'}
    with database(app) as con:
        con.execute('INSERT INTO hub_transactions(id,owner,fingerprint,data,created_at) VALUES(?,?,?,?,?)',
                    (rid, owner, rid, json.dumps(data), '2026-09-19T00:00:00+00:00'))


def link(app, kind, left, right, amount=0, owner='member1'):
    with database(app) as con:
        con.execute('INSERT INTO hub_reconciliations(id,owner,kind,left_id,right_id,amount_cents,confirm_digest,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                    (left + right, owner, kind, left, right, amount, 'synthetic', 'synthetic', 'synthetic'))


def budget(app, amount=20000, *, currency='CNY', category='全部', month=MONTH, owner='member1'):
    with database(app) as con:
        con.execute('INSERT INTO hub_budgets(owner,month,currency,category,amount_cents) VALUES(?,?,?,?,?)',
                    (owner, month, currency, category, amount))


def submit(client, headers, prompt=None, **fields):
    prompt = prompt or (MODEL_PROMPT if fields.get('useModel') else '本月本人消费和预算')
    return client.post(URL, json={'prompt': prompt, **fields}, headers=headers)


def assert_no_finance(value, status=None):
    if status:
        assert value['status'] == status
    assert value['query'] is value['navigation'] is value['snapshot'] is None
    assert value['totals'] == value['budgets'] == []
    assert value['coverage']['recordCount'] == 0


def advisory(payload):
    context = json.loads(payload['input'])
    candidate = api.parse_question(context['question'], date.fromisoformat(context['today']), allow_model=True)
    assert candidate['modelCandidate']
    return {'status': 'ready', 'query': candidate['query'],
            'evidence': {**{key: choices[0] if choices else None for key, choices in candidate['evidence'].items()},
                         'metric': context['question']}}


def model(app, monkeypatch, invoke=None):
    app.config.update(OPENAI_API_KEY='synthetic-provider-key', OPENAI_MODEL='synthetic-model')
    calls = []
    def remote(config, payload):
        assert not g.db.in_transaction
        calls.append(deepcopy(payload))
        if invoke:
            return invoke(config, payload)
        return advisory(payload)
    monkeypatch.setattr(home_assistant, '_model_json', remote)
    return calls


@pytest.mark.parametrize(('prompt', 'scope', 'month', 'metric', 'currency', 'category'), [
    ('消费多少', 'personal', MONTH, 'spending', None, None),
    ('本月我花了多少', 'personal', MONTH, 'spending', None, None),
    ('上月预算还剩多少', 'personal', '2026-08', 'budget', None, None),
    ('2025-12退款后的净支出', 'personal', '2025-12', 'spending', None, None),
    ('查询本人 2026-08 CNY 餐饮 支出与预算', 'personal', '2026-08', 'summary', 'CNY', '餐饮'),
    ('查询本人日元日用预算', 'personal', MONTH, 'budget', 'JPY', '日用'),
    ('查询2026-09共享消费', 'shared', MONTH, 'spending', None, None),
    ('上个月美元共同消费', 'shared', '2026-08', 'spending', 'USD', None),
    ('查询公共荷包', 'public', None, 'summary', None, None),
    ('共同长期储蓄', 'public', None, 'summary', None, None),
])
def test_supported_local_interpretations(prompt, scope, month, metric, currency, category):
    assert api.parse_question(prompt, date(2026, 9, 19)) == dict(
        scope=scope, month=month, metric=metric, currency=currency, category=category)


def test_previous_month_crosses_year():
    assert api.parse_question('上月预算', date(2026, 1, 1))['month'] == '2025-12'


@pytest.mark.parametrize('prompt', [
    '9月消费', '九月消费', '2026-09-01消费', '2026-13消费', '本月和上月消费',
    '上月到本月消费', '2026-08和2026-09预算', '最近消费', '今年预算', '昨天花了多少',
    '我的家庭消费', '我和伴侣本月消费', '分别查询两个人支出', '本人和共享消费',
    '本月公共荷包', '公共荷包 USD', '人民币美元消费', '餐饮购物预算',
    '不要查询本月消费', '不看预算只看支出', '排除退款后支出',
    '查询预算然后改成100', '本月支出并创建待办', '新增预算', '帮我删除退款',
    '请解释“查询本月消费”', '查询「伴侣消费」', '`本月支出`',
    '不明分类预算', '张三本月消费', '未来消费', '全部和餐饮预算',
])
def test_ambiguous_or_mixed_directions_do_not_default_to_private_query(prompt):
    assert_no_finance(api.parse_question(prompt, date(2026, 9, 19)), 'clarify')


@pytest.mark.parametrize('prompt', ['老婆本月消费', '他人预算', 'member2消费', '共享消费餐饮',
                                    '共享消费预算', '搜索本月账单', '查找预算', '找一下消费', '资产多少'])
def test_unsupported_privacy_or_other_intent(prompt):
    assert_no_finance(api.parse_question(prompt, date(2026, 9, 19)), 'unsupported')


def test_expected_finance_math_owner_scope_and_no_business_writes(app):
    client, headers = member(app)
    seed(app)
    seed(app, 'refund', flow='refund', amount=2000)
    seed(app, 'duplicate', amount=10000)
    seed(app, 'order', kind='orders', flow='unknown', amount=50000)
    seed(app, 'transfer', flow='transfer', amount=30000)
    seed(app, 'partner-secret', owner='member2', amount=87654321, category='SECRET_PARTNER_CATEGORY')
    link(app, 'duplicate', 'duplicate', 'expense')
    link(app, 'refund_payment', 'refund', 'expense', 2000)
    budget(app)
    budget(app, 50000, owner='member2')
    before = domain_snapshot(app)
    response = submit(client, headers)
    assert response.status_code == 200, response.json
    value = response.json
    assert set(value) == {'status', 'mode', 'message', 'query', 'totals', 'budgets', 'snapshot', 'coverage', 'navigation'}
    assert value['totals'] == [{'currency': 'CNY', 'expenseCents': 10000, 'refundCents': 2000, 'netSpendCents': 8000, 'count': 5}]
    assert value['budgets'] == [{'currency': 'CNY', 'category': '全部', 'amountCents': 20000, 'spentCents': 8000, 'remainingCents': 12000}]
    assert value['coverage']['status'] == 'partial' and value['coverage']['orderCount'] == 1
    assert '1 条订单' in value['coverage']['note'] and '未代表已核实支出' in value['coverage']['note']
    assert value['coverage']['duplicateCount'] == 1
    assert '本人' in value['message'] and MONTH in value['message']
    assert response.headers['Cache-Control'] == 'no-store'
    assert 'PRIVATE_SYNTHETIC' not in response.get_data(as_text=True)
    assert 'SECRET_PARTNER' not in response.get_data(as_text=True)
    assert domain_snapshot(app) == before
    partner, ph = member(app, 2)
    assert submit(partner, ph).json['totals'][0]['netSpendCents'] == 87654321


def test_real_import_and_budget_routes_feed_registered_query(app):
    client, headers = member(app)
    payload = {'source': 'generic', 'kind': 'payments',
               'csv': 'date,title,amount,currency,flow,category,id,status\n2026-09-02,SYNTHETIC,100,CNY,expense,餐饮,synthetic,成功\n'}
    preview = client.post('/api/finance-hub/imports/preview', json=payload, headers=headers)
    assert preview.status_code == 200, preview.json
    assert client.post('/api/finance-hub/imports/confirm', json={**payload, 'previewToken': preview.json['previewToken']}, headers=headers).status_code == 200
    saved = client.put('/api/finance-hub/budgets', json={'month': MONTH, 'currency': 'CNY', 'category': '全部', 'amount': '200'}, headers=headers)
    assert saved.status_code == 200, saved.json
    before = domain_snapshot(app)
    value = submit(client, headers).json
    assert value['totals'][0]['netSpendCents'] == 10000
    assert value['budgets'][0]['remainingCents'] == 10000
    assert domain_snapshot(app) == before


def test_full_ledger_over_500_and_separate_currencies(app):
    client, headers = member(app)
    with database(app) as con:
        for index in range(601):
            value = dict(date=MONTH + '-02', kind='payments', flow='expense', currency='CNY',
                         amountCents=101, category='餐饮', visibility='private')
            con.execute('INSERT INTO hub_transactions(id,owner,fingerprint,data,created_at) VALUES(?,?,?,?,?)',
                        (str(index), 'member1', str(index), json.dumps(value), 'synthetic'))
    seed(app, 'usd', amount=233, currency='USD')
    budget(app, 100000)
    budget(app, 1000, currency='USD')
    value = submit(client, headers).json
    assert [(x['currency'], x['netSpendCents'], x['count']) for x in value['totals']] == [('CNY', 60701, 601), ('USD', 233, 1)]
    assert value['coverage']['recordCount'] == 602
    assert [x['remainingCents'] for x in value['budgets']] == [39299, 767]
    assert len(submit(client, headers, '本月本人美元消费').json['totals']) == 1


def test_cross_month_partial_refund_allocations_and_independent_budgets(app):
    client, headers = member(app)
    seed(app, 'prior-food', month='2026-08', category='餐饮', amount=7000)
    seed(app, 'prior-travel', month='2026-08', category='旅行', amount=3000)
    seed(app, 'refund', flow='refund', category='其他', amount=4000)
    link(app, 'refund_payment', 'refund', 'prior-food', 2000)
    link(app, 'refund_payment', 'refund', 'prior-travel', 1000)
    budget(app, 20000)
    budget(app, 5000, category='餐饮')
    budget(app, 6000, category='旅行')
    value = submit(client, headers).json
    assert value['totals'][0]['netSpendCents'] == -4000
    assert [(x['category'], x['spentCents'], x['remainingCents']) for x in value['budgets']] == [
        ('全部', -4000, 24000), ('旅行', -1000, 7000), ('餐饮', -2000, 7000)]
    selected = submit(client, headers, '本月餐饮消费与预算').json
    assert selected['totals'][0]['refundCents'] == 2000
    assert selected['budgets'] == [{'currency': 'CNY', 'category': '餐饮', 'amountCents': 5000, 'spentCents': -2000, 'remainingCents': 7000}]
    august = submit(client, headers, '上月消费').json
    assert august['totals'][0]['netSpendCents'] == 10000


def test_no_records_unknown_zero_and_missing_budget_are_distinct(app):
    client, headers = member(app)
    empty = submit(client, headers).json
    assert empty['totals'] == empty['budgets'] == [] and empty['coverage']['status'] == 'no_records'
    assert '尚未设置预算' in empty['message']
    seed(app, 'unknown', flow='unknown', amount=50000)
    partial = submit(client, headers).json
    assert partial['coverage']['status'] == 'partial' and partial['coverage']['unknownCount'] == 1
    assert '1 条待核对付款' in partial['coverage']['note']
    assert partial['totals'][0]['netSpendCents'] == 0 and partial['budgets'] == []
    seed(app, 'zero', amount=0, currency='USD')
    zero = submit(client, headers, '本月美元消费').json
    assert zero['coverage']['status'] == 'recorded' and zero['totals'][0]['netSpendCents'] == 0
    budget(app, 0, currency='USD')
    assert submit(client, headers, '本月美元预算').json['budgets'][0]['remainingCents'] == 0


def test_shared_projects_only_the_existing_allowlist(app):
    client, headers = member(app)
    seed(app, 'private', amount=87654321, category='SECRET_PRIVATE_CAT')
    seed(app, 'expense', amount=10000, visibility='shared')
    seed(app, 'refund', amount=2000, flow='refund', visibility='shared', owner='member2')
    seed(app, 'duplicate', amount=10000, visibility='shared')
    seed(app, 'order', kind='orders', flow='unknown', amount=888, visibility='shared')
    seed(app, 'income', flow='income', amount=555, visibility='shared')
    link(app, 'duplicate', 'duplicate', 'expense')
    budget(app, 50000)
    response = submit(client, headers, '共享消费')
    value = response.json
    existing = client.get('/api/finance-hub/shared?month=' + MONTH).json
    assert value['totals'] == existing['totals']
    assert value['totals'][0]['netSpendCents'] == 8000
    assert value['budgets'] == [] and value['snapshot'] is None and value['query']['category'] is None
    assert value['coverage']['recordCount'] == 2
    assert [value['coverage'][k] for k in ('unknownCount', 'orderCount', 'duplicateCount')] == [0, 0, 0]
    assert 'SECRET_PRIVATE' not in response.get_data(as_text=True) and '87654321' not in response.get_data(as_text=True)


def test_public_snapshot_requires_confirmation_and_never_sums_savings(app):
    client, headers = member(app)
    value = submit(client, headers, '公共荷包').json
    assert all(v is None for v in value['snapshot'].values())
    assert value['coverage']['status'] == 'manual_snapshot'
    assert 'longterm' not in value['coverage']['note']
    confirmed = '2026-08-04T00:00:00+00:00'
    with database(app) as con:
        con.execute("UPDATE settings SET data=? WHERE id='finance'", (json.dumps({
            'wallet': 100, 'livingSpent': 200, 'livingBudget': 300, 'longterm': 400,
            'travelSaved': 999999, 'confirmedAt': confirmed, 'note': 'PRIVATE_NOTE'}),))
    value = submit(client, headers, '公共荷包').json
    assert value['snapshot'] == dict(walletCents=100, livingSpentCents=200, livingBudgetCents=300, savingsCents=400, confirmedAt=confirmed)
    assert value['query']['month'] is None and value['navigation'] == {'screen': 'finance', 'tab': 'shared', 'month': None}
    assert value['totals'] == value['budgets'] == []
    assert_no_finance(submit(client, headers, '上月公共荷包').json, 'clarify')


def test_model_payload_has_only_question_clock_and_fixed_enums_reads_latest_after_network(app, monkeypatch):
    client, headers = member(app)
    seed(app, amount=100)
    budget(app, 7654321, category='SECRET_PRIVATE_CATEGORY')
    sql = []
    install_connection(app, URL, 'POST', before=sql.append)
    def remote(_config, payload):
        assert not any('FROM hub_' in query for query in sql)
        context = json.loads(payload['input'])
        assert set(context) == {'question', 'today', 'timezone', 'scopes', 'metrics', 'currencies', 'categories'}
        assert context['question'] == MODEL_PROMPT
        assert 'SECRET_PRIVATE' not in json.dumps(payload) and '7654321' not in json.dumps(payload)
        seed(app, 'arrived-during-network', amount=200)
        return advisory(payload)
    calls = model(app, monkeypatch, remote)
    value = submit(client, headers, useModel=True).json
    assert value['mode'] == 'model' and value['totals'][0]['netSpendCents'] == 300 and len(calls) == 1


def test_model_permission_does_not_spend_a_call_on_already_clear_local_query(app, monkeypatch):
    client, headers = member(app)
    calls = model(app, monkeypatch)
    seed(app)
    value = submit(client, headers, '本月本人消费和预算', useModel=True).json
    assert value['mode'] == 'local' and value['totals'][0]['netSpendCents'] == 10000 and calls == []


def test_colloquial_question_gains_grounded_interpretation_only_with_model_permission(app, monkeypatch):
    client, headers = member(app)
    seed(app, 'last-food', month='2026-08', amount=10000)
    seed(app, 'last-refund', month='2026-08', flow='refund', amount=2000, category='其他')
    seed(app, 'current-secret', amount=87654321)
    link(app, 'refund_payment', 'last-refund', 'last-food', 2000)
    prompt = '帮我瞧瞧上个月餐饮方面用了多少钱'
    assert_no_finance(submit(client, headers, prompt).json, 'clarify')
    calls = model(app, monkeypatch)
    before = domain_snapshot(app)
    response = submit(client, headers, prompt, useModel=True)
    assert response.status_code == 200, response.json
    value = response.json
    assert value['mode'] == 'model' and value['query'] == {
        'scope': 'personal', 'month': '2026-08', 'metric': 'spending', 'currency': None, 'category': '餐饮'}
    assert value['totals'][0]['netSpendCents'] == 8000 and len(calls) == 1
    assert domain_snapshot(app) == before


@pytest.mark.parametrize('status', ['clarify', 'unsupported'])
def test_model_can_decline_without_any_financial_read(app, monkeypatch, status):
    client, headers = member(app)
    model(app, monkeypatch, lambda _config, _payload: {'status': status, 'query': None, 'evidence': None})
    sql = []
    install_connection(app, URL, 'POST', before=sql.append)
    response = submit(client, headers, useModel=True)
    assert_no_finance(response.json, status)
    assert response.json['mode'] == 'model' and not any('FROM hub_' in query for query in sql)


@pytest.mark.parametrize('key', ['scope', 'month', 'metric', 'currency', 'category'])
def test_model_evidence_cannot_invent_or_drop_explicit_constraints(app, monkeypatch, key):
    client, headers = member(app)
    def remote(_config, payload):
        value = advisory(payload)
        value['evidence'][key] = 'MODEL_INVENTED_WORDS'
        return value
    model(app, monkeypatch, remote)
    response = submit(client, headers, '帮我瞧瞧上个月美元餐饮方面用了多少钱', useModel=True)
    assert response.status_code == 502 and response.json['code'] == 'invalid_model_output'
    assert 'MODEL_INVENTED' not in response.get_data(as_text=True)


@pytest.mark.parametrize('fails', [False, True])
def test_household_membership_revoked_during_model_discards_result(app, monkeypatch, fails):
    client, headers = member(app)
    seed(app)
    def remote(_config, payload):
        with database(app) as con:
            con.execute("UPDATE household_memberships SET state='left',revision=revision+1 WHERE member_id='member1'")
        if fails:
            raise home_assistant.ModelProviderError('synthetic provider failure', 503)
        return advisory(payload)
    model(app, monkeypatch, remote)
    result = submit(client, headers, useModel=True)
    assert result.status_code == 401 and set(result.json) == {'error'}


@pytest.mark.parametrize('prompt', ['本月和上月消费', '删除本月预算', '老婆消费', '搜索预算', '“本人消费”'])
def test_local_rejection_precedes_model_and_ledger(app, monkeypatch, prompt):
    client, headers = member(app)
    calls = model(app, monkeypatch)
    sql = []
    install_connection(app, URL, 'POST', before=sql.append)
    value = submit(client, headers, prompt, useModel=True).json
    assert_no_finance(value)
    assert calls == [] and not any('FROM hub_' in query for query in sql)


@pytest.mark.parametrize('bad', ['foreign_scope', 'foreign_month', 'extra_values', 'wrong_type', 'unsafe_exception'])
def test_model_cannot_change_authorized_intent_or_echo_unsafe_content(app, monkeypatch, bad):
    client, headers = member(app)
    seed(app)
    def remote(_config, payload):
        value = advisory(payload)
        if bad == 'foreign_scope':
            value['query']['scope'] = 'shared'
        elif bad == 'foreign_month':
            value['query']['month'] = '2026-08'
        elif bad == 'extra_values':
            value['query']['balance'] = 'SECRET_PROVIDER_BODY'
        elif bad == 'wrong_type':
            return 'SECRET_PROVIDER_BODY'
        else:
            raise ValueError('SECRET_PROVIDER_BODY')
        return value
    model(app, monkeypatch, remote)
    before = domain_snapshot(app)
    response = submit(client, headers, useModel=True)
    assert response.status_code == 502 and response.json['code'] == 'invalid_model_output'
    assert 'SECRET_PROVIDER' not in response.get_data(as_text=True)
    assert domain_snapshot(app) == before


@pytest.mark.parametrize('kind', ['session', 'expired', 'auth_version'])
@pytest.mark.parametrize('fails', [False, True])
def test_revocation_during_model_wins_over_success_or_failure(app, monkeypatch, kind, fails):
    client, headers = member(app)
    seed(app)
    def remote(_config, payload):
        with database(app) as con:
            con.execute('BEGIN IMMEDIATE')
            invalidate(con, kind)
        if fails:
            raise home_assistant.ModelProviderError('SECRET_PROVIDER_BODY', 503)
        return advisory(payload)
    calls = model(app, monkeypatch, remote)
    before = domain_snapshot(app)
    response = submit(client, headers, useModel=True)
    assert response.status_code == 401 and set(response.json) == {'error'}
    assert len(calls) == 1 and domain_snapshot(app) == before


def test_revocation_after_read_discards_projected_finance(app):
    client, headers = member(app)
    seed(app)
    entered = []
    def after(sql):
        if 'FROM hub_transactions' in sql and not entered:
            with database(app) as con:
                invalidate(con)
            entered.append(True)
    install_connection(app, URL, 'POST', after=after)
    response = submit(client, headers)
    assert entered == [True] and response.status_code == 401 and set(response.json) == {'error'}


def test_member_identity_changed_during_model_cannot_return_prior_owner(app, monkeypatch):
    client, headers = member(app)
    seed(app)
    def remote(_config, payload):
        g.actor = {**g.actor, 'id': 'member2'}
        return advisory(payload)
    model(app, monkeypatch, remote)
    assert submit(client, headers, useModel=True).status_code == 401


def test_cross_household_same_member_and_record_id_are_isolated(app):
    client, headers = member(app)
    seed(app, 'same-record-id', amount=100)
    child, _, space = create_space(app)
    assert child.get(space['entry']).status_code == 303
    assert child.post('/api/login', json={'username': 'member1', 'password': 'second-home-password-one'}).status_code == 200
    ch = {'X-CSRF-Token': child.get('/api/me').json['csrf']}
    value = submit(child, ch).json
    assert value['totals'] == [] and value['coverage']['status'] == 'no_records'
    platform = app.extensions['household_platform']
    child_app = next(value for value in platform.cache.values() if hasattr(value, 'config'))
    seed(child_app, 'same-record-id', amount=200)
    assert submit(child, ch).json['totals'][0]['netSpendCents'] == 200
    assert submit(client, headers).json['totals'][0]['netSpendCents'] == 100


def test_auth_tv_csrf_origin_and_injected_parameters(app):
    client, headers = member(app)
    assert submit(app.test_client(), headers).status_code == 401
    assert submit(client, {}).status_code == 403
    assert submit(client, {**headers, 'Origin': 'https://foreign.invalid'}).status_code == 403
    assert client.post(URL, data='{}', headers=headers).status_code == 415
    assert client.post(URL + '?owner=member2', json={'prompt': '消费'}, headers=headers).status_code == 400
    assert submit(client, headers, owner='member2').status_code == 400
    tv = app.test_client()
    pair = tv.post('/api/pair/start', json={}).json
    assert client.post('/api/pair/approve', json={'code': pair['code'], 'name': 'Synthetic TV'}, headers=headers).status_code == 200
    assert tv.post('/api/pair/poll', json={'secret': pair['secret']}).json['approved']
    assert submit(tv, headers).status_code == 403


@pytest.mark.parametrize('payload', [{'prompt': ''}, {'prompt': []}, {'prompt': True},
    {'prompt': '消费', 'useModel': 'true'}, {'prompt': '消费', 'owner': 'member2'},
    {'prompt': '消费\x00'}, {'prompt': '消' * 2001}])
def test_request_shape_is_strict(app, payload):
    client, headers = member(app)
    response = client.post(URL, json=payload, headers=headers)
    assert response.status_code == 400


def test_model_disabled_rate_limit_and_safe_integer_boundary(app, monkeypatch):
    client, headers = member(app)
    unavailable = submit(client, headers, useModel=True)
    assert unavailable.status_code == 503 and unavailable.json['code'] == 'model_unavailable'
    seed(app, amount=api.MAX_SAFE_INTEGER)
    seed(app, 'overflow', amount=1)
    result = submit(client, headers).json
    assert_no_finance(result, 'unsupported')
    calls = model(app, monkeypatch)
    with database(app) as con:
        con.executemany('INSERT INTO attempts VALUES(?,?,?)', [('127.0.0.1', 'assistant_plan', time.time())] * 30)
    assert submit(client, headers, useModel=True).status_code == 429 and calls == []
