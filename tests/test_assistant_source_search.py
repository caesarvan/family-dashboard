"""Local source search: real SQLite, sessions, encryption and loopback browser only."""
import json
import time
from pathlib import Path

import pytest
from flask import request

import home_assistant
from app import create_app
from test_household_media import configured, saved, device, stage
from test_journey_documents import PASSWORD, login, clone, connection, create_journey
from test_journey_places import create as create_place


@pytest.fixture
def env(tmp_path, monkeypatch):
    return configured(tmp_path/'household', monkeypatch)


def search(client, query, **paging):
    response = client.get('/api/assistant/search', query_string={'q':query, **paging})
    assert response.status_code == 200, response.json
    return response.json


def photo(env, caption='合成照片', **values):
    c,h,item=saved(env)
    response=c.patch('/api/media/items/'+item['id'],json={'revision':item['revision'],'caption':caption,**values},headers=h)
    assert response.status_code==200,response.json
    return c,h,response.json['item']


def counts(app):
    with connection(app) as con:
        return {table:con.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in ('assistant_plans','entities','audit')}


def test_search_local_even_model_requested_and_no_private_matches_persisted(env,monkeypatch):
    c,h,p=photo(env,caption='绝密检索标记 <img src=x onerror=alert(1)>')
    place,_=create_place(c,h,name='绝密检索标记地点',coordinates={'latitude':31.2345,'longitude':121.4567})
    monkeypatch.setattr(home_assistant,'model_plan',lambda *_:pytest.fail('search called model'))
    before=counts(env[0])
    result=c.post('/api/assistant/plan',json={'prompt':'搜索 绝密检索标记','useModel':True,'includeHouseholdContext':True},headers=h)
    assert result.status_code==200,result.json
    assert result.json['mode']=='local' and result.json['id'] is None and result.json['actions']==[]
    assert {row['id'] for row in result.json['matches']}=={p['id'],place['id']}
    assert counts(env[0])==before
    text=json.dumps(result.json,ensure_ascii=False)
    for forbidden in ('accountId','displayFilename','coordinates','31.2345','121.4567',env[3][1],'private-synthetic-filename'):
        assert forbidden not in text
    assert search(c,'private-synthetic-filename')['total']==0
    assert c.get('/api/media/items/'+p['id']).status_code==200
    assert c.get('/api/journey-places/'+place['id']).status_code==200


def test_acl_shared_revoke_delete_and_provider_permission(env):
    c,h,p=photo(env,'检索照片')
    other,oh=login(env[0],2)
    place,_=create_place(c,h,name='检索地点')
    assert search(other,'检索')['total']==0
    assert c.patch('/api/media/items/'+p['id'],json={'revision':p['revision'],'visibility':'shared'},headers=h).status_code==200
    assert c.patch('/api/journey-places/'+place['id'],json={'revision':1,'visibility':'shared'},headers=h).status_code==200
    assert search(other,'检索')['total']==2
    with connection(env[0]) as con:
        con.execute('UPDATE cloud_accounts SET needs_reauth=1 WHERE id=?',(env[3][1],))
    assert [i['kind'] for i in search(other,'检索')['matches']]==['places']
    assert search(c,'检索')['total']==2  # Confirmed local owner copy follows media API.
    assert c.patch('/api/journey-places/'+place['id'],json={'revision':2,'visibility':'private'},headers=h).status_code==200
    assert search(other,'检索')['total']==0
    assert c.delete('/api/media/items/'+p['id'],json={'revision':p['revision']+1},headers=h).status_code==200
    assert c.delete('/api/journey-places/'+place['id'],json={'revision':3},headers=h).status_code==200
    assert search(c,'检索')['total']==0


def test_journey_text_literal_pagination_and_restart(env):
    c,h=login(env[0]); journey=create_journey(c,h,title='旅程关联索引')
    c,h,p=photo(env,'不含关键词',journeyId=journey['id'])
    place,_=create_place(c,h,name='另一地点',journeyId=journey['id'])
    result=search(c,'旅程关联索引',limit=1)
    assert result['total']==4  # Trip, generated travel event, photo and place.
    all_ids=[]; offset=0
    while offset is not None:
        page=search(c,'旅程关联索引',limit=1,offset=offset)
        all_ids.extend(i['id'] for i in page['matches']);offset=page['nextOffset']
    assert len(set(all_ids))==4
    assert search(c,"%' OR 1=1 --")['total']==0
    restarted=create_app(dict(env[0].config))
    assert search(clone(restarted,c),'旅程关联索引')==search(c,'旅程关联索引')
    trip=c.get('/api/journeys/'+journey['id']).json['trip']
    assert c.delete('/api/items/trips/'+journey['tripId'],json={'revision':trip['revision']},headers=h).status_code==200
    assert not {'media','places'} & {i['kind'] for i in search(c,'旅程关联索引')['matches']}


@pytest.mark.parametrize('params',[{}, {'q':''},{'q':'x'*101},{'q':'x','limit':'31'},{'q':'x','limit':'true'},
    {'q':'x','offset':'-1'},{'q':'x','offset':'20001'},{'q':'x','extra':'no'}, [('q','x'),('q','y')]])
def test_search_input_bounds(env,params):
    c,_=login(env[0])
    assert c.get('/api/assistant/search',query_string=params).status_code==400


def test_staged_media_never_searchable_and_tv_denied(env):
    c,h,detail,_=stage(env)
    assert search(c,'synthetic')['total']==0
    _,tv,_=device(env)
    assert tv.get('/api/assistant/search?q=anything').status_code==403
    assert tv.get('/api/assistant/brief').status_code==403
    assert c.get('/api/assistant/search?q=anything',headers={'X-Display-Mode':'tv'}).status_code in (401,403)
    assert c.post('/api/assistant/plan',json={'prompt':'搜索 x'}).status_code==403


def test_two_household_routing_and_foreign_cookie(env):
    app=env[0];c,h=login(app)
    create_place(c,h,name='ROOT_ONLY_SECRET')
    invitation=c.post('/api/spaces/invitations',json={},headers=h).json['invitation']
    child=app.test_client()
    result=child.post('/api/spaces/redeem',json={'invitation':invitation,'name':'搜索第二家庭','slug':'search-two','MEMBER1_PASSWORD':PASSWORD,'MEMBER2_PASSWORD':PASSWORD})
    assert result.status_code==201,result.json
    assert child.get(result.json['entry']).status_code==303
    child,ch=login(app,client=child)
    create_place(child,ch,name='CHILD_ONLY_SECRET')
    assert search(child,'ROOT_ONLY_SECRET')['total']==0
    assert search(c,'CHILD_ONLY_SECRET')['total']==0
    assert search(child,'CHILD_ONLY_SECRET')['total']==1
    child.set_cookie('session',c.get_cookie('session').value)
    assert child.get('/api/assistant/search?q=SECRET').status_code==401


@pytest.mark.parametrize('endpoint', ['plan','journey-brief'])
@pytest.mark.parametrize('revoke',['logout','auth_version','generation'])
def test_model_return_rechecks_original_session_without_saving(env,monkeypatch,endpoint,revoke):
    app=env[0];app.config.update(ASSISTANT_PROVIDER='openai',OPENAI_API_KEY='synthetic-key',OPENAI_MODEL='synthetic-model')
    c,h=login(app);old=clone(app,c);before=counts(app)
    def fake(*_):
        if revoke=='logout':
            assert old.post('/api/logout',json={},headers=h).status_code==200
        else:
            with connection(app) as con:
                if revoke=='auth_version':con.execute("UPDATE users SET auth_version=auth_version+1 WHERE id='member1'")
                else:con.execute('UPDATE member_session_browsers SET generation=generation+1')
        return {'summary':'MUST_NOT_RETURN','actions':[{'kind':'tasks','title':'MUST_NOT_SAVE'}]} if endpoint=='plan' else {'title':'MUST_NOT_RETURN'}
    monkeypatch.setattr(home_assistant,'model_plan' if endpoint=='plan' else 'model_journey_brief',fake)
    response=c.post('/api/assistant/'+endpoint,json={'prompt':'安排旅行','useModel':True},headers=h)
    assert response.status_code in (401,409),response.json
    assert 'MUST_NOT' not in response.get_data(as_text=True)
    assert counts(app)['assistant_plans']==before['assistant_plans'] and counts(app)['entities']==before['entities']


@pytest.mark.parametrize('already_applied',[False,True])
def test_apply_rechecks_after_capture_including_replayed_result(env,monkeypatch,already_applied):
    app=env[0];c,h=login(app)
    draft=c.post('/api/assistant/plan',json={'prompt':'待办：明确的新事项'},headers=h).json
    path='/api/assistant/plans/'+draft['id']+'/apply'
    if already_applied: assert c.post(path,json={'selected':[0]},headers=h).status_code==200
    before=counts(app);sessions=app.extensions['member_sessions'];original=sessions.capture
    def race(*args,**kwargs):
        snapshot=original(*args,**kwargs)
        with connection(app) as con:con.execute('UPDATE member_session_browsers SET generation=generation+1')
        return snapshot
    monkeypatch.setattr(sessions,'capture',race)
    assert c.post(path,json={'selected':[0]},headers=h).status_code==409
    assert counts(app)==before


def test_plan_current_member_matches_guard_and_retry_stays_exactly_once(env,monkeypatch):
    app=env[0];c,h=login(app)
    draft=c.post('/api/assistant/plan',json={'prompt':'采购：虚构收纳盒'},headers=h).json
    before=counts(app)
    path='/api/assistant/plans/'+draft['id']+'/apply'
    first=c.post(path,json={'selected':[0]},headers=h)
    second=c.post(path,json={'selected':[0]},headers=h)
    assert first.status_code==200 and second.json==first.json
    assert counts(app)['entities']==before['entities']+1
    assert counts(app)['audit']==before['audit']+1
    old=clone(app,c)
    assert c.post('/api/logout',json={},headers=h).status_code==200
    for method,url,value in [('get','/api/assistant/search?q=虚构',None),('post',path,{'selected':[0]})]:
        assert getattr(old,method)(url,json=value,headers=h).status_code==401


def test_model_context_never_includes_photo_or_place_metadata(env,monkeypatch):
    c,h,p=photo(env,'PHOTO_PRIVATE_MARKER')
    create_place(c,h,name='PLACE_PRIVATE_MARKER')
    env[0].config.update(ASSISTANT_PROVIDER='openai',OPENAI_API_KEY='synthetic-key',OPENAI_MODEL='synthetic-model')
    calls=[]
    def fake(_config,prompt,context):
        calls.append((prompt,context));return {'summary':'合成规划','actions':[]}
    monkeypatch.setattr(home_assistant,'model_plan',fake)
    response=c.post('/api/assistant/plan',json={'prompt':'安排本周事项','useModel':True,'includeHouseholdContext':True},headers=h)
    assert response.status_code==200,response.json
    assert 'PRIVATE_MARKER' not in json.dumps(calls)
    assert set(calls[0][1])=={'today','events','tasks'}




@pytest.mark.parametrize('path',['/api/assistant/brief','/api/assistant/search?q=private'])
def test_read_rechecks_member_after_global_guard(env,path):
    app=env[0]
    @app.before_request
    def changed_after_guard():
        if request.path==path.split('?')[0]:
            with connection(app) as con:
                con.execute("UPDATE users SET auth_version=auth_version+1 WHERE id='member1'")
    c,h=login(app)
    assert c.get(path).status_code==401


@pytest.mark.parametrize('prompt',['搜索','查找：','找一下 '+ '词'*101])
def test_invalid_explicit_search_does_not_call_model_or_save(env,monkeypatch,prompt):
    c,h=login(env[0]);before=counts(env[0])
    monkeypatch.setattr(home_assistant,'model_plan',lambda *_:pytest.fail('Invalid search called model'))
    assert c.post('/api/assistant/plan',json={'prompt':prompt,'useModel':True},headers=h).status_code==400
    assert counts(env[0])==before
