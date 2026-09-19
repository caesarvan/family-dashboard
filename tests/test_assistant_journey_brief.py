"""Travel briefs remain untrusted drafts; real Flask auth, synthetic models only."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3

import pytest
import home_assistant
from test_app import app, member


PROMPT = '''旅行名称：东京京都与巴黎
出发日期：2027-10-01
返程日期：2027-10-12
旅行类型：境外
总预算：2万元
日本/东京 2027-10-01 至 2027-10-04
日本/京都 2027-10-04 至 2027-10-07
法国/巴黎 2027-10-07 至 2027-10-12'''


def counts(app):
    with closing(sqlite3.connect(Path(app.config['DATA_DIR']) / 'household.sqlite3')) as con:
        return {table: con.execute('SELECT count(*) FROM ' + table).fetchone()[0]
                for table in ('entities', 'assistant_plans', 'journey_workflows', 'journey_actions', 'calendar_publications', 'task_publications')}


def test_local_brief_preserves_explicit_values_and_has_no_writes(app, monkeypatch):
    c, h = member(app)
    monkeypatch.setattr(home_assistant, 'model_journey_brief', lambda *_: pytest.fail('Local mode called model'))
    before = counts(app)
    result = c.post('/api/assistant/journey-brief', json={'prompt': PROMPT}, headers=h)
    assert result.status_code == 200, result.json
    value = result.json
    assert value['mode'] == 'local' and value['missingFields'] == []
    assert value['brief']['budgetCents'] == 2000000
    assert [row['city'] for row in value['brief']['destinations']] == ['东京', '京都', '巴黎']
    assert value['brief']['note'] == PROMPT
    assert counts(app) == before


@pytest.mark.parametrize('prompt', ['', '今年想去日本和法国，大约12天，两万左右', '总预算：约2万元', '总预算：2万元左右', '出发日期：今年10月1日\n返程日期：12天后'])
def test_unknown_and_approximate_values_are_not_invented(app, prompt):
    c, h = member(app)
    result = c.post('/api/assistant/journey-brief', json={'prompt': prompt}, headers=h)
    assert result.status_code == 200
    b = result.json['brief']
    assert b['start'] == b['end'] == '' and b['budgetCents'] is None and b['destinations'] == []
    assert {'start', 'end', 'budgetCents', 'destinations'} <= set(result.json['missingFields'])


@pytest.mark.parametrize('use_model', [False, True])
@pytest.mark.parametrize('prompt', [
    '总预算：2000元\n币种：日元',
    '日元总预算：2000元',
    '人均计划投入的总预算：2000元',
    '总预算：2000元；这是每个人准备投入的额度',
    '总预算：2000元\n币种：JPY',
    '总预算：2000元\n币种：待定',
    '总预算：2000元，这个数字只是目前的大概想法',
    '总预算：2000元；总预算：3000元',
])
def test_ambiguous_budget_remains_missing_without_business_writes(app, monkeypatch, prompt, use_model):
    app.config.update(OPENAI_API_KEY='fake-test-key', OPENAI_MODEL='fake-model')
    def fake(*_):
        if not use_model:
            pytest.fail('Local budget parsing called a model')
        return {'budgetCents': 200000}
    monkeypatch.setattr(home_assistant, 'model_journey_brief', fake)
    c, h = member(app)
    before = counts(app)
    response = c.post('/api/assistant/journey-brief', json={'prompt': prompt, 'useModel': use_model}, headers=h)
    assert response.status_code == 200, response.json
    assert response.json['brief']['budgetCents'] is None
    assert 'budgetCents' in response.json['missingFields']
    assert response.json['brief']['note'] == prompt
    assert counts(app) == before


@pytest.mark.parametrize('use_model', [False, True])
@pytest.mark.parametrize('prompt,amount', [
    ('总预算：2000.25元', 200025),
    ('家庭总预算（人民币）：2000.25元', 200025),
    ('共同总预算：CNY 2000.25元', 200025),
    ('机票人均100美元；家庭总预算（人民币）：2000.25元', 200025),
    ('家庭总预算（RMB）：0元', 0),
])
def test_explicit_cny_family_total_is_preserved_without_conversion_or_writes(app, monkeypatch, prompt, amount, use_model):
    app.config.update(OPENAI_API_KEY='fake-test-key', OPENAI_MODEL='fake-model')
    def fake(*_):
        if not use_model:
            pytest.fail('Local budget parsing called a model')
        return {'budgetCents': amount}
    monkeypatch.setattr(home_assistant, 'model_journey_brief', fake)
    c, h = member(app)
    before = counts(app)
    response = c.post('/api/assistant/journey-brief', json={'prompt': prompt, 'useModel': use_model}, headers=h)
    assert response.status_code == 200, response.json
    assert response.json['brief']['budgetCents'] == amount
    assert 'budgetCents' not in response.json['missingFields']
    assert response.json['brief']['note'] == prompt
    assert counts(app) == before


def test_brief_only_enters_existing_preview_then_explicit_idempotent_apply(app):
    c, h = member(app)
    b = c.post('/api/assistant/journey-brief', json={'prompt': PROMPT}, headers=h).json['brief']
    plan = {key: b[key] for key in ('title', 'start', 'end', 'international', 'note')}
    plan.update(budget=b['budgetCents'], memberIds=['member1', 'member2'], destinations=[dict(row, key=f'stop-{i}') for i, row in enumerate(b['destinations'])])
    p = c.post('/api/journeys/preview', json={'plan': plan}, headers=h)
    assert p.status_code == 200 and p.json['canApply']
    assert not any(counts(app).values())
    request = {'previewToken': p.json['previewToken'], 'idempotencyKey': 'assistant-journey-synthetic'}
    a = c.post('/api/journeys/apply', json=request, headers=h)
    assert a.status_code == 201
    again = c.post('/api/journeys/apply', json=request, headers=h)
    assert again.status_code == 200 and again.json['id'] == a.json['id']
    assert counts(app)['journey_workflows'] == counts(app)['journey_actions'] == 1
    assert counts(app)['calendar_publications'] == counts(app)['task_publications'] == 0


def test_model_whitelist_and_context_excludes_household_and_tokens(app, monkeypatch):
    app.config.update(OPENAI_API_KEY='fake-test-key', OPENAI_MODEL='fake-model')
    c, h = member(app)
    b = home_assistant.local_journey_brief(PROMPT)
    b.update(owner='member2', memberIds=['member2'], previewToken='injected', remoteId='remote',
             id='existing', paid=100, saved=100, actions=[{'kind':'trips'}], publish=True)
    b['destinations'][0].update(key='existing', owner='member2', remoteId='remote')
    calls = []
    def fake(config, prompt):
        calls.append(prompt)
        return b
    monkeypatch.setattr(home_assistant, 'model_journey_brief', fake)
    before = counts(app)
    r = c.post('/api/assistant/journey-brief', json={'prompt': PROMPT, 'useModel': True, 'includeHouseholdContext': True}, headers=h)
    assert r.status_code == 200 and r.json['mode'] == 'model'
    assert set(r.json['brief']) == {'title','start','end','international','budgetCents','destinations','note','checklist','shopping'}
    assert r.json['brief']['checklist'] == r.json['brief']['shopping'] == r.json['warnings'] == []
    assert set(r.json['brief']['destinations'][0]) == {'country','city','arrival','departure'}
    assert calls == [PROMPT] and counts(app) == before
    assert r.json['brief']['budgetCents']==2000000


def test_model_cannot_fill_absent_dates_destinations_budget_or_booking_note(app, monkeypatch):
    app.config.update(OPENAI_API_KEY='fake-test-key',OPENAI_MODEL='fake-model')
    c,h=member(app)
    fabricated=home_assistant.local_journey_brief(PROMPT)
    fabricated['note']='酒店已订妥，实际报价20000元'
    monkeypatch.setattr(home_assistant,'model_journey_brief',lambda *_:fabricated)
    prompt='今年想去日本，大约12天，两万左右，酒店还没有订'
    response=c.post('/api/assistant/journey-brief',json={'prompt':prompt,'useModel':True},headers=h)
    assert response.status_code==200
    brief=response.json['brief']
    assert brief['start']==brief['end']=='' and brief['budgetCents'] is None and brief['international'] is None
    assert all(row['arrival']==row['departure']==row['city']=='' for row in brief['destinations'])
    assert brief['destinations'][2]['country']=='' and brief['note']==prompt


@pytest.mark.parametrize('bad', [[], {'budgetCents': True}, {'budgetCents': 1.1}, {'budgetCents': -1},
    {'international':'true'}, {'start':'2027-02-29'}, {'end':'2027年10月1日'}, {'destinations': [{}] * 21},
    {'destinations': [{'city': {'owner':'member2'}}]}, {'title':'x'*101}])
def test_bad_model_values_fail_closed_without_writes(app, monkeypatch, bad):
    app.config.update(OPENAI_API_KEY='fake-test-key', OPENAI_MODEL='fake-model')
    c,h=member(app)
    monkeypatch.setattr(home_assistant,'model_journey_brief',lambda *_:bad)
    before=counts(app)
    response=c.post('/api/assistant/journey-brief',json={'prompt':'虚构旅行','useModel':True},headers=h)
    assert response.status_code==502 and counts(app)==before


def test_configuration_input_and_permission_failures(app):
    c,h=member(app)
    url='/api/assistant/journey-brief'
    assert app.test_client().post(url,json={'prompt':PROMPT}).status_code==401
    assert c.post(url,json={'prompt':PROMPT}).status_code==403
    assert c.post(url,json={'prompt':PROMPT,'useModel':True},headers=h).status_code==503
    for request in ({'prompt':{}}, {'prompt':'x'*2001}, {'prompt':'旅行','useModel':'true'}, {'prompt':'出发日期：2027-02-29'}):
        assert c.post(url,json=request,headers=h).status_code==400
    tv=app.test_client()
    pairing=tv.post('/api/pair/start',json={}).json
    assert c.post('/api/pair/approve',json={'code':pairing['code'],'name':'Synthetic TV','focus':'member1'},headers=h).status_code==200
    assert tv.post('/api/pair/poll',json={'secret':pairing['secret']}).json['approved']
    assert tv.post(url,json={'prompt':PROMPT},headers=h).status_code==403
