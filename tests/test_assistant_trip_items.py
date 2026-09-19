"""Brief suggestions -> actual journey preview/apply, with no external network."""
from contextlib import closing, contextmanager
from copy import deepcopy
import json
from pathlib import Path
import socket
import sqlite3

import pytest

from app import create_app
import home_assistant as assistant
from test_app import member
from test_household_spaces import create_space


URL = '/api/assistant/journey-brief'
TRIP = ('旅行名称：冰岛旅行\n出发日期：2027-10-01\n返程日期：2027-10-07\n'
        '旅行类型：境外\n总预算：20000元\n冰岛/雷克雅未克 2027-10-01 至 2027-10-07')
TASK = '准备：核对护照 | 负责人：我 | 出发前：3天'
PURCHASE = '采购：转换插头 | 负责人：小林 | 数量：两只 | 预算：200元'
PROSE = '2027-10-01至2027-10-07去冰岛境外，总预算20000元；我在出发前三天核对护照；小林买两只转换插头，预算200元'


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*_args, **_kwargs):
        pytest.fail('External network is forbidden; use only synthetic provider values')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket, 'create_connection', deny)


@pytest.fixture
def app(tmp_path):
    return create_app({'TESTING': True, 'DATA_DIR': str(tmp_path / 'data'),
        'SECRET_KEY': 'synthetic-trip-items-only', 'SESSION_COOKIE_SECURE': False,
        'PUBLIC_ORIGIN': 'http://localhost', 'MEMBER1_PASSWORD': 'testing-password-one',
        'MEMBER2_PASSWORD': 'testing-password-two', 'ASSISTANT_PROVIDER': 'openai',
        'OPENAI_API_KEY': '', 'OPENAI_MODEL': '', 'NVIDIA_API_KEY': '', 'NVIDIA_MODEL': '',
        'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': '',
        'MICROSOFT_CLIENT_ID': '', 'MICROSOFT_CLIENT_SECRET': ''})


@contextmanager
def database(app):
    with closing(sqlite3.connect(Path(app.config['DATA_DIR']) / 'household.sqlite3', timeout=2)) as con:
        with con:
            yield con


def business(app):
    with database(app) as con:
        return {table: list(con.execute('SELECT * FROM ' + table + ' ORDER BY rowid'))
                for table in ('entities', 'assistant_plans', 'journey_workflows', 'journey_links',
                              'journey_actions', 'calendar_publications', 'task_publications', 'audit')}


def named_members(app):
    client, headers = member(app)
    partner, ph = member(app, 2)
    assert client.post('/api/profile', json={'name': '合成本人'}, headers=headers).status_code == 200
    assert partner.post('/api/profile', json={'name': '小林'}, headers=ph).status_code == 200
    return client, headers, partner, ph


def submit(client, headers, prompt, **kwargs):
    return client.post(URL, json={'prompt': prompt, **kwargs}, headers=headers)


def advisory(source=PROSE):
    return {'title': '冰岛旅行', 'start': '2027-10-01', 'end': '2027-10-07',
            'international': True, 'budgetCents': 2000000,
            'destinations': [{'country': '冰岛', 'city': '', 'arrival': '2027-10-01', 'departure': '2027-10-07'}],
            'checklist': [{'title': '核对护照', 'assigneeText': '我', 'sourceText': source.split('；')[1],
                           'due': '', 'dueOffsetDays': -3}],
            'shopping': [{'title': '转换插头', 'assigneeText': '小林', 'sourceText': source.split('；')[2],
                          'quantity': '两只', 'budgetCents': 20000}]}


def model(app, monkeypatch, raw, callback=None):
    app.config.update(OPENAI_API_KEY='synthetic-test-key', OPENAI_MODEL='synthetic-model')
    calls = []
    def fake(config, payload):
        calls.append(deepcopy(payload))
        if callback:
            callback()
        return deepcopy(raw)
    monkeypatch.setattr(assistant, '_model_json', fake)
    return calls


def to_plan(brief):
    plan = {k: brief[k] for k in ('title', 'start', 'end', 'international', 'note')}
    plan.update(memberIds=['member1', 'member2'], budget=brief['budgetCents'],
                destinations=[dict(row, key=f'stop-{i}') for i, row in enumerate(brief['destinations'])])
    if brief['checklist']:
        plan['checklist'] = [{**{k: row[k] for k in ('key', 'title', 'owner', 'note')},
                              **({'due': row['due']} if row['due'] else {'dueOffsetDays': row['dueOffsetDays']})}
                             for row in brief['checklist']]
    if brief['shopping']:
        plan['shopping'] = [{**{k: row[k] for k in ('key', 'title', 'owner', 'note', 'quantity')},
                             'budget': row['budgetCents']} for row in brief['shopping']]
    return plan


@pytest.mark.parametrize('use_model', [False, True])
def test_actual_preview_apply_replay_and_recreated_app_preserve_items(app, monkeypatch, use_model):
    client, headers, _, _ = named_members(app)
    prompt = TRIP + '\n' + TASK + '\n' + PURCHASE
    raw = assistant.local_journey_brief(prompt)
    calls = model(app, monkeypatch, raw)
    before = business(app)
    response = submit(client, headers, prompt, useModel=use_model)
    assert response.status_code == 200, response.json
    brief = response.json['brief']
    assert brief['budgetCents'] == 2000000 and response.json['warnings'] == []
    assert brief['checklist'][0]['owner'] == 'member1' and brief['checklist'][0]['dueOffsetDays'] == -3
    assert brief['shopping'][0]['owner'] == 'member2' and brief['shopping'][0]['budgetCents'] == 20000
    assert len(calls) == int(use_model) and business(app) == before
    preview = client.post('/api/journeys/preview', json={'plan': to_plan(brief)}, headers=headers)
    assert preview.status_code == 200 and preview.json['canApply'], preview.json
    assert preview.json['plan']['checklist'][0]['due'] == '2027-09-28'
    assert business(app) == before
    body = {'previewToken': preview.json['previewToken'], 'idempotencyKey': 'trip-items-real-save'}
    saved = client.post('/api/journeys/apply', json=body, headers=headers)
    assert saved.status_code == 201, saved.json
    persisted = business(app)
    replay = client.post('/api/journeys/apply', json=body, headers=headers)
    assert replay.status_code == 200 and replay.json['id'] == saved.json['id'] and business(app) == persisted
    detail = client.get('/api/journeys/' + saved.json['id']).json
    assert [(x['title'], x['owner'], x['due']) for x in detail['tasks']] == [('核对护照', 'member1', '2027-09-28')]
    assert [(x['title'], x['owner'], x['budget'], x['quantity']) for x in detail['shopping']] == [('转换插头', 'member2', 20000, '两只')]
    assert detail['trip']['budget'] == 2000000 and detail['trip']['paid'] == 0
    assert persisted['calendar_publications'] == persisted['task_publications'] == []
    # App/DB reconstruction, not an OS process restart.
    rebuilt = create_app(dict(app.config))
    again, _ = member(rebuilt)
    assert again.get('/api/journeys/' + saved.json['id']).json['plan'] == detail['plan']
    assert business(rebuilt) == persisted


def test_natural_language_model_sample_is_grounded_without_sending_household(app, monkeypatch):
    client, headers, _, _ = named_members(app)
    assert client.post('/api/items/tasks', json={'title': 'HOUSEHOLD_CONTEXT_MUST_NOT_LEAVE'}, headers=headers).status_code == 201
    raw = advisory()
    raw.update(owner='member2', key='attack', previewToken='forged', paid=20000, bookings=['confirmed'])
    for collection in ('checklist', 'shopping'):
        raw[collection][0].update(owner='member2', key='forged', id='existing', paid=100, publish=True, note='酒店已订妥')
    calls = model(app, monkeypatch, raw)
    before = business(app)
    response = submit(client, headers, PROSE, useModel=True, includeHouseholdContext=True)
    assert response.status_code == 200, response.json
    b = response.json['brief']
    assert b['budgetCents'] == 2000000 and b['shopping'][0]['budgetCents'] == 20000
    assert b['checklist'][0]['owner'] == 'member1' and b['shopping'][0]['owner'] == 'member2'
    assert b['checklist'][0]['key'] == 'brief-task-1' and b['shopping'][0]['key'] == 'brief-purchase-1'
    common = {'key', 'title', 'assigneeText', 'owner', 'note', 'sourceText'}
    assert set(b['checklist'][0]) == common | {'due', 'dueOffsetDays'}
    assert set(b['shopping'][0]) == common | {'quantity', 'budgetCents'}
    assert '酒店已订妥' not in json.dumps(b, ensure_ascii=False)
    assert len(calls) == 1 and json.loads(calls[0]['input']) == {'request': PROSE}
    assert not any(x in json.dumps(calls, ensure_ascii=False) for x in ('member1', 'member2', 'HOUSEHOLD_CONTEXT_MUST_NOT_LEAVE', headers['X-CSRF-Token']))
    assert business(app) == before


@pytest.mark.parametrize('use_model', [False, True])
@pytest.mark.parametrize('source,collection,owner,quantity,offset', [
    ('准备：预约接送 | 负责人：我 | 出发前：3天', 'checklist', 'member1', None, -3),
    ('准备：预约接送 | 负责人：我 | 出发前：约3天', 'checklist', 'member1', None, None),
    ('采购：转换插头 | 负责人：小林 | 数量：两只 | 预算：约200元', 'shopping', 'member2', '两只', None),
    ('采购：转换插头 | 负责人：小林 | 数量：两只 | 预算：不超过200元', 'shopping', 'member2', '两只', None),
    ('采购：转换插头 | 负责人：小林 | 数量：两只 | 单价：200元', 'shopping', 'member2', '两只', None),
    ('采购：转换插头 | 负责人：小林 | 数量：约两只 | 预算：200元', 'shopping', 'member2', '', None),
])
def test_item_qualifiers_do_not_erase_independent_labelled_facts(app, monkeypatch, use_model,
                                                              source, collection, owner, quantity, offset):
    client, headers, _, _ = named_members(app)
    prompt = TRIP + '\n' + source
    raw = assistant.local_journey_brief(prompt)
    # Simulate a model omitting a qualifier, not just the local parser's nulls.
    if collection == 'shopping':
        raw[collection][0].update(budgetCents=20000, quantity='两只')
    else:
        raw[collection][0]['dueOffsetDays'] = -3
    calls = model(app, monkeypatch, raw)
    before = business(app)
    response = submit(client, headers, prompt, useModel=use_model)
    assert response.status_code == 200, response.json
    brief = response.json['brief']; row = brief[collection][0]
    assert row['owner'] == owner and row['sourceText'] == row['note'] == source
    assert brief['budgetCents'] == 2000000
    if collection == 'shopping':
        assert row['quantity'] == quantity and row['budgetCents'] is None
    else:
        assert row['due'] == '' and row['dueOffsetDays'] == offset
    assert len(calls) == int(use_model) and business(app) == before


def test_natural_booking_and_approximate_budget_keep_separate_facts(app, monkeypatch):
    client, headers, _, _ = named_members(app)
    prompt = PROSE.replace('核对护照', '预约接送').replace('预算200元', '预算约200元')
    raw = advisory(prompt); raw['checklist'][0]['title'] = '预约接送'
    calls = model(app, monkeypatch, raw)
    before = business(app)
    response = submit(client, headers, prompt, useModel=True)
    assert response.status_code == 200, response.json
    brief = response.json['brief']; task, purchase = brief['checklist'][0], brief['shopping'][0]
    assert task['owner'] == 'member1' and task['dueOffsetDays'] == -3 and task['due'] == ''
    assert purchase['owner'] == 'member2' and purchase['quantity'] == '两只'
    assert purchase['budgetCents'] is None and brief['budgetCents'] == 2000000
    assert purchase['sourceText'] == purchase['note'] == '小林买两只转换插头，预算约200元'
    assert len(calls) == 1 and json.loads(calls[0]['input']) == {'request': prompt}
    assert business(app) == before


@pytest.mark.parametrize('source', [
    '不要小林买两只转换插头，预算200元',
    '小林买两只转换插头，预算200元，改由合成本人负责',
    '采购：转换插头 | 负责人：小林 | 数量：两只 | 预算：200元 | 备注：取消本项采购',
])
def test_item_wide_negation_or_reassignment_still_blocks_model_facts(app, monkeypatch, source):
    client, headers, _, _ = named_members(app)
    raw = advisory(); raw['shopping'][0]['sourceText'] = source
    model(app, monkeypatch, raw)
    response = submit(client, headers, PROSE.rsplit('；', 1)[0] + '；' + source, useModel=True)
    assert response.status_code == 200, response.json
    row = response.json['brief']['shopping'][0]
    assert row['owner'] is None and row['quantity'] == '' and row['budgetCents'] is None
    assert row['sourceText'] == row['note'] == source


@pytest.mark.parametrize('name,owner', [('我', 'member1'), ('共同', 'shared'), ('我们', 'shared'), ('一起', 'shared'),
                                        ('小林', 'member2'), ('不存在', None), ('member2', None), ('', 'shared')])
def test_exact_active_member_resolution(app, name, owner):
    client, headers, _, _ = named_members(app)
    response = submit(client, headers, f'准备：核对护照 | 负责人：{name} | 出发前：3天')
    assert response.status_code == 200
    row = response.json['brief']['checklist'][0]
    assert row['owner'] == owner and row['assigneeText'] == name
    assert ('checklist[0].owner' in response.json['missingFields']) == (owner is None)
    assert all(warning.startswith('准备第 1 项：') and 'brief-task-' not in warning
               for warning in response.json['warnings'])


def test_duplicate_or_departed_name_never_resolves_to_historical_member(app):
    client, headers, partner, ph = named_members(app)
    assert client.post('/api/profile', json={'name': '小林'}, headers=headers).status_code == 200
    prompt = '准备：核对护照 | 负责人：小林 | 出发前：3天'
    assert submit(client, headers, prompt).json['brief']['checklist'][0]['owner'] is None
    assert client.post('/api/profile', json={'name': '合成本人'}, headers=headers).status_code == 200
    with database(app) as con:
        con.execute("UPDATE household_memberships SET state='left',revision=revision+1 WHERE member_id='member2'")
    assert submit(client, headers, prompt).json['brief']['checklist'][0]['owner'] is None


@pytest.mark.parametrize('mutation', ['actor_session', 'actor_membership', 'browser_generation', 'other_member_left', 'other_member_renamed'])
def test_authorization_and_candidate_names_are_rechecked_after_model(app, monkeypatch, mutation):
    client, headers, _, _ = named_members(app)
    def during_model():
        # A second real connection must be able to write while provider I/O runs.
        with database(app) as con:
            con.execute('BEGIN IMMEDIATE')
            if mutation == 'actor_session':
                con.execute("UPDATE member_sessions SET revoked_at=1 WHERE owner='member1'")
            elif mutation == 'actor_membership':
                con.execute("UPDATE household_memberships SET state='left',revision=revision+1 WHERE member_id='member1'")
            elif mutation == 'browser_generation':
                con.execute('UPDATE member_session_browsers SET generation=generation+1')
            elif mutation == 'other_member_left':
                con.execute("UPDATE household_memberships SET state='left',revision=revision+1 WHERE member_id='member2'")
            else:
                con.execute("UPDATE users SET name='合成新名字' WHERE id='member2'")
    calls = model(app, monkeypatch, advisory(), during_model)
    before = business(app)
    result = submit(client, headers, PROSE, useModel=True)
    if mutation.startswith('other_member'):
        assert result.status_code == 200 and result.json['brief']['shopping'][0]['owner'] is None
    else:
        assert result.status_code in (401, 409) and 'brief' not in result.json
    assert len(calls) == 1 and business(app) == before


def test_household_switch_and_same_member_ids_do_not_share_names(app):
    client, headers, _, _ = named_members(app)
    prompt = '准备：核对护照 | 负责人：小林 | 出发前：3天'
    assert submit(client, headers, prompt).json['brief']['checklist'][0]['owner'] == 'member2'
    child, _, space = create_space(app)
    assert child.get(space['entry']).status_code == 303
    child.set_cookie('session', client.get_cookie('session').value)
    assert submit(child, headers, prompt).status_code == 401
    assert child.post('/api/login', json={'username': 'member1', 'password': 'second-home-password-one'}).status_code == 200
    ch = {'X-CSRF-Token': child.get('/api/me').json['csrf']}
    assert submit(child, ch, prompt).json['brief']['checklist'][0]['owner'] is None
    assert submit(client, headers, prompt).json['brief']['checklist'][0]['owner'] == 'member2'


@pytest.mark.parametrize('source,amount', [
    ('采购：转换插头 | 预算：200.25元', 20025), ('采购：转换插头 | 预算：0元', 0),
    ('采购：转换插头 | 预算：人民币200元', 20000), ('采购：转换插头 | 预算：200元左右', None),
    ('采购：转换插头 | 数量：2 | 预算：不超过200元', None),
    ('采购：转换插头 | 数量：2 | 预算：约200元', None),
    ('采购：转换插头 | 数量：2 | 单价：200元', None),
    ('采购：转换插头 | 预算：200美元', None), ('采购：转换插头 | 人均预算：200元', None),
    ('采购：转换插头 | 单价预算：200元', None), ('采购：转换插头 | 预算：200元/只', None),
    ('采购：转换插头 | 预算：200元 | 备注：预算300元才对', None),
    ('采购：转换插头 | 总预算：200元', None), ('采购：转换插头', None),
])
def test_local_item_amount_is_exact_and_never_becomes_total(app, source, amount):
    client, headers = member(app)
    r = submit(client, headers, '总预算：20000元\n' + source)
    assert r.status_code == 200, r.json
    b = r.json['brief']
    assert b['budgetCents'] == 2000000 and b['shopping'][0]['budgetCents'] == amount
    assert b['shopping'][0]['sourceText'] == source


@pytest.mark.parametrize('source', ['小林买两只转换插头，预算200元左右', '不要小林买两只转换插头，预算200元',
    '小林买两只转换插头，预算200美元', '小林买两只转换插头，单价预算200元',
    '小林买两只转换插头，预算200元/只', '小林买两只转换插头，预算200元，人均支出',
    '小林买两只转换插头，预算200元，预算300元才对'])
def test_model_cannot_cherry_pick_money_qualifiers(app, monkeypatch, source):
    client, headers, _, _ = named_members(app)
    raw = advisory()
    raw['shopping'][0]['sourceText'] = '转换插头，预算200元' if '转换插头，预算200元' in source else source
    model(app, monkeypatch, raw)
    response = submit(client, headers, PROSE.split('；')[0] + '；我在出发前三天核对护照；' + source, useModel=True)
    assert response.status_code == 200
    assert response.json['brief']['shopping'][0]['budgetCents'] is None
    assert response.json['brief']['budgetCents'] in (None, 2000000)


def test_model_other_item_amount_or_nonexistent_source_has_no_factual_authority(app, monkeypatch):
    client, headers, _, _ = named_members(app)
    raw = advisory(); raw['shopping'][0]['sourceText'] = '小林买相机，预算200元'
    model(app, monkeypatch, raw)
    prompt = PROSE.replace('预算200元', '金额待定') + '；小林买相机，预算200元'
    row = submit(client, headers, prompt, useModel=True).json['brief']['shopping'][0]
    assert row['budgetCents'] is None and row['owner'] is None and row['sourceText'] == row['note'] == row['quantity'] == ''


@pytest.mark.parametrize('source', ['采购：转换插头 | 总预算：200元', '小林买两只转换插头，总预算200元'])
def test_purchase_total_is_never_a_trip_total(app, monkeypatch, source):
    client, headers = member(app)
    model(app, monkeypatch, {'budgetCents': 20000})
    assert submit(client, headers, source).json['brief']['budgetCents'] is None
    assert submit(client, headers, source, useModel=True).json['brief']['budgetCents'] is None


@pytest.mark.parametrize('source', ['小林买两只转换插头，预算200美元', '小林买两只转换插头，人均预算200元'])
def test_model_keeps_explicit_trip_total_despite_separate_ambiguous_purchase(app, monkeypatch, source):
    client, headers, _, _ = named_members(app)
    raw = advisory();raw['shopping'][0]['sourceText'] = source
    model(app, monkeypatch, raw)
    prompt = PROSE.rsplit('；', 1)[0] + '；' + source
    brief = submit(client, headers, prompt, useModel=True).json['brief']
    assert brief['budgetCents'] == 2000000 and brief['shopping'][0]['budgetCents'] is None


@pytest.mark.parametrize('phrase,offset', [('出发前：3天', -3), ('出发前三天', -3), ('出发前二十一天', -21),
    ('出发后：366天', 366), ('出发前：730天', -730), ('出发当天', 0), ('出发前三天半', None),
    ('大约出发前三天', None), ('出发前三天或出发前四天', None)])
def test_exact_relative_dates_and_unknown_dates(app, phrase, offset):
    client, headers = member(app)
    response = submit(client, headers, '准备：核对护照 | ' + phrase)
    assert response.status_code == 200, response.json
    row = response.json['brief']['checklist'][0]
    assert row['due'] == '' and row['dueOffsetDays'] == offset


def test_absolute_date_purchase_deadline_and_unrecognized_text_survive(app):
    client, headers = member(app)
    prompt = ('准备：打印行程 | 截止日期：2027-09-30\n'
              '准备：核对护照 | 截止：今年十月前\n'
              '采购：转换插头 | 数量：2 件 | 截止：出发前3天\n想在天气好的时候看极光')
    result = submit(client, headers, prompt).json
    assert result['brief']['note'] == prompt
    assert result['brief']['checklist'][0]['due'] == '2027-09-30'
    assert result['brief']['checklist'][1]['due'] == '' and result['brief']['checklist'][1]['dueOffsetDays'] is None
    purchase = result['brief']['shopping'][0]
    assert '出发前3天' in purchase['note'] and 'due' not in purchase and 'dueOffsetDays' not in purchase
    assert any('采购尚无截止日期字段' in x for x in result['warnings'])


@pytest.mark.parametrize('collection,change', [
    ('checklist', {'title': ''}), ('checklist', {'title': 'a' * 101}),
    ('checklist', {'assigneeText': []}), ('checklist', {'sourceText': 'a' * 501}),
    ('checklist', {'note': {}}), ('checklist', {'due': '2027-02-29'}),
    ('checklist', {'due': '1999-10-01'}), ('checklist', {'dueOffsetDays': True}),
    ('checklist', {'dueOffsetDays': 1.5}), ('checklist', {'dueOffsetDays': -731}),
    ('checklist', {'dueOffsetDays': 367}), ('checklist', {'due': '2027-09-30', 'dueOffsetDays': -3}),
    ('shopping', {'quantity': 'x' * 31}), ('shopping', {'budgetCents': True}),
    ('shopping', {'budgetCents': 0.5}), ('shopping', {'budgetCents': -1}),
    ('shopping', {'budgetCents': 100000000001}),
])
def test_item_type_and_boundary_validation(collection, change):
    with pytest.raises(ValueError):
        assistant.normalize_journey_brief({collection: [{'title': '合成事项', **change}]})


@pytest.mark.parametrize('collection', ['checklist', 'shopping'])
def test_list_limit_stable_keys_and_model_privilege_fields(collection):
    raw = {collection: [{'title': f'合成事项{i}', 'key': 'collision', 'owner': 'member2', 'paid': 900} for i in range(100)]}
    rows = assistant.normalize_journey_brief(raw)[collection]
    assert len(rows) == len({row['key'] for row in rows}) == 100
    assert all(row['owner'] is None and 'paid' not in row for row in rows)
    with pytest.raises(ValueError):
        assistant.normalize_journey_brief({collection: raw[collection] + [raw[collection][0]]})
    with pytest.raises(ValueError):
        assistant.normalize_journey_brief({collection: None})


def test_invalid_model_items_fail_http_closed_no_writes_or_retry(app, monkeypatch):
    client, headers = member(app)
    calls = model(app, monkeypatch, {'checklist': [{'title': '合成事项', 'dueOffsetDays': True}]})
    before = business(app)
    response = submit(client, headers, '准备：合成事项', useModel=True)
    assert response.status_code == 502 and len(calls) == 1 and business(app) == before


def test_no_items_keeps_template_and_local_never_uses_model(app, monkeypatch):
    client, headers = member(app)
    monkeypatch.setattr(assistant, '_model_json', lambda *_: pytest.fail('Local mode called model'))
    response = submit(client, headers, TRIP).json
    assert response['brief']['checklist'] == response['brief']['shopping'] == response['warnings'] == []
    value = to_plan(response['brief'])
    assert 'checklist' not in value
    preview = client.post('/api/journeys/preview', json={'plan': value}, headers=headers)
    assert preview.status_code == 200 and len(preview.json['plan']['checklist']) == 7


def test_brief_does_not_bypass_preview_membership_or_allow_tv(app):
    client, headers, _, _ = named_members(app)
    b = submit(client, headers, TRIP + '\n' + TASK + '\n' + PURCHASE).json['brief']
    with database(app) as con:
        con.execute("UPDATE household_memberships SET state='left',revision=revision+1 WHERE member_id='member2'")
    value = to_plan(b);value['memberIds'] = ['member1']
    assert client.post('/api/journeys/preview', json={'plan': value}, headers=headers).status_code == 400
    assert submit(app.test_client(), headers, TASK).status_code == 401
    assert submit(client, {}, TASK).status_code == 403
    assert submit(client, {**headers, 'Origin': 'https://invalid.example'}, TASK).status_code == 403
    tv = app.test_client(); pair = tv.post('/api/pair/start', json={}).json
    assert client.post('/api/pair/approve', json={'code': pair['code'], 'name': 'Synthetic TV'}, headers=headers).status_code == 200
    assert tv.post('/api/pair/poll', json={'secret': pair['secret']}).json['approved']
    assert submit(tv, headers, TASK).status_code == 403
