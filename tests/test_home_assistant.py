import json
import sqlite3
from pathlib import Path
from test_app import app, member
import home_assistant


def test_preview_apply_idempotent_and_owner(app):
    c,h=member(app)
    before=c.get('/api/state').json['tasks']
    result=c.post('/api/assistant/plan',json={'prompt':'待办：明天预约保洁；确认酒店'},headers=h)
    assert result.status_code==200,result.json
    p=result.json
    assert p['mode']=='local' and len(p['actions'])==2
    assert c.get('/api/state').json['tasks']==before
    other,oh=member(app,2)
    assert other.post('/api/assistant/plans/'+p['id']+'/apply',json={'selected':[0]},headers=oh).status_code==404
    applied=c.post('/api/assistant/plans/'+p['id']+'/apply',json={'selected':[0]},headers=h)
    assert applied.status_code==200
    assert len(c.get('/api/state').json['tasks'])==len(before)+1
    retry=c.post('/api/assistant/plans/'+p['id']+'/apply',json={'selected':[0]},headers=h)
    assert retry.json==applied.json
    assert len(c.get('/api/state').json['tasks'])==len(before)+1


def test_no_model_no_claim_and_bad_inputs(app):
    c,h=member(app)
    assert not c.get('/api/assistant/brief').json['modelConfigured']
    assert c.post('/api/assistant/plan',json={'prompt':'请规划旅行','useModel':True},headers=h).status_code==503
    assert c.post('/api/assistant/plan',json={'prompt':{}},headers=h).status_code==400
    result=c.post('/api/assistant/plan',json={'prompt':'看看这周安排'},headers=h).json
    assert result['actions']==[]
    assert c.post('/api/assistant/plans/'+result['id']+'/apply',json={'selected':[True]},headers=h).status_code==400
    assert c.post('/api/assistant/plan',json={'prompt':'待办：2026-99-99 无效日期'},headers=h).status_code==400


def test_model_context_is_allowlisted_and_actions_not_executed(app,monkeypatch):
    app.config.update(OPENAI_API_KEY='fake-key-test-only',OPENAI_MODEL='test-model')
    c,h=member(app)
    c.put('/api/private-finance',json={'income':98989899,'spent':777,'budget':999,'month':'2026-09','revision':0},headers=h)
    c.post('/api/items/tasks',json={'title':'预约保洁','due':'2026-09-15','note':'PRIVATE_NOTE_SHOULD_NOT_SEND'},headers=h)
    calls=[]
    def fake(config,prompt,context):
        calls.append(context)
        return {'summary':'建议准备', 'actions':[{'kind':'shopping','title':'收纳袋','owner':'shared','quantity':'2 件','budget':999999}]}
    monkeypatch.setattr(home_assistant,'model_plan',fake)
    draft=c.post('/api/assistant/plan',json={'prompt':'整理采购','useModel':True,'includeHouseholdContext':True},headers=h).json
    assert draft['mode']=='model'
    assert '98989899' not in json.dumps(calls) and 'PRIVATE_NOTE_SHOULD_NOT_SEND' not in json.dumps(calls)
    assert draft['actions'][0]['data']['budget'] is None
    assert c.get('/api/state').json['shopping']==[]
    c.post('/api/assistant/plan',json={'prompt':'整理采购','useModel':True},headers=h)
    assert set(calls[-1])=={'today'}


def test_search_and_conflicts(app):
    c,h=member(app)
    today=c.get('/api/assistant/brief').json['today']
    for owner,title in [('member1','会议A'),('shared','酒店入住')]:
        c.post('/api/items/events',json={'title':title,'owner':owner,'start':today+'T10:00:00+08:00','end':today+'T11:00:00+08:00'},headers=h)
    assert len(c.get('/api/assistant/brief').json['conflicts'])==1
    found=c.post('/api/assistant/plan',json={'prompt':'搜索：酒店'},headers=h).json
    assert len(found['matches'])==1 and found['actions']==[]


def test_invalid_model_enum_fields_fail_without_writes(app,monkeypatch):
    app.config.update(OPENAI_API_KEY='fake-test-key',OPENAI_MODEL='test-model')
    c,h=member(app)
    for action in ({'kind':[],'title':'invalid'}, {'kind':'tasks','owner':{},'title':'invalid'}):
        monkeypatch.setattr(home_assistant,'model_plan',lambda *_args: {'summary':'bad','actions':[action]})
        result=c.post('/api/assistant/plan',json={'prompt':'生成计划','useModel':True},headers=h)
        assert result.status_code==400
    assert c.get('/api/state').json['tasks']==[]
