"""Inventory search and real shell navigation; temporary SQLite and loopback only."""
import json
import socket
import sqlite3
import threading
import time
from pathlib import Path

import pytest
from flask import request

import home_assistant
import inventory_core
from app import create_app
from test_inventory_api import create, acquisition, move, counts, rid
from test_journey_documents import PASSWORD, login, clone, connection


@pytest.fixture
def app(tmp_path, monkeypatch):
    original = socket.socket.connect
    def guarded(sock, address):
        if not isinstance(address, tuple) or address[0] not in ('127.0.0.1', '::1', 'localhost'):
            raise AssertionError('External network forbidden')
        return original(sock, address)
    monkeypatch.setattr(socket.socket, 'connect', guarded)
    monkeypatch.setenv('MEMBER1_PASSWORD', PASSWORD)
    monkeypatch.setenv('MEMBER2_PASSWORD', PASSWORD)
    result = create_app({'TESTING':True, 'DATA_DIR':str(tmp_path/'home'),
        'SECRET_KEY':'synthetic-inventory-search', 'SESSION_COOKIE_SECURE':False,
        'PUBLIC_ORIGIN':'http://localhost', 'GOOGLE_CLIENT_ID':'', 'GOOGLE_CLIENT_SECRET':'',
        'MICROSOFT_CLIENT_ID':'', 'MICROSOFT_CLIENT_SECRET':'', 'ASSISTANT_PROVIDER':'local',
        'OPENAI_API_KEY':'', 'OPENAI_MODEL':'', 'NVIDIA_API_KEY':'', 'NVIDIA_MODEL':''})
    return result


def search(c, q, **paging):
    response = c.get('/api/assistant/search', query_string={'q':q, **paging})
    assert response.status_code == 200, response.json
    return response.json


def patch(c, h, item, **values):
    response = c.patch('/api/inventory/items/'+item['id'], headers=h,
                       json={'requestId':rid(), 'revision':item['revision'], 'patch':values})
    assert response.status_code == 200, response.json
    return response.json['item']


def test_projection_local_only_no_source_receipt_or_model(app, monkeypatch):
    c,h = login(app)
    item = create(c,h,title='检索物品 <img src=x>',variant='DESCRIPTION_ONLY',location='LOCATION_ONLY')[0]['item']
    acquisition(c,h,item,note='BATCH_NOTE_PRIVATE')
    before = counts(app)
    calls=[]; original=inventory_core.project_item
    def projected(con, actor, item_id):
        assert con.in_transaction
        calls.append((actor,item_id))
        return original(con,actor,item_id)
    monkeypatch.setattr(inventory_core,'project_item',projected)
    monkeypatch.setattr(home_assistant,'model_plan',lambda *_:pytest.fail('Local search called model'))
    result=search(c,'description_only')
    assert calls==[('member1',item['id'])]
    assert result['matches']==[{'kind':'inventory','id':item['id'],'title':item['title'],
        'variant':item['variant'],'location':item['location'],'unit':item['unit'],
        'visibility':'private','revision':2,'onHandQty':0,'inTransitQty':6,'plannedQty':0}]
    for term in ('BATCH_NOTE_PRIVATE',"%' OR 1=1 --"):
        assert search(c,term)['total']==0
    assert search(c,'location_only')['matches']==result['matches']
    response=c.post('/api/assistant/plan',headers=h,json={'prompt':'搜索 检索物品','useModel':True,'includeHouseholdContext':True})
    assert response.status_code==200,response.json
    assert response.json['matches']==result['matches'] and response.json['actions']==[] and response.json['id'] is None
    assert counts(app)==before
    with connection(app) as con:
        assert con.execute('SELECT count(*) FROM assistant_plans').fetchone()[0]==0


def test_own_partner_shared_revoked_archived_and_restart(app):
    c,h=login(app);other,oh=login(app,2)
    mine=create(c,h,title='物品边界我的')[0]['item']
    hidden=create(other,oh,title='物品边界私密')[0]['item']
    shared=create(other,oh,title='物品边界共享',visibility='shared')[0]['item']
    assert {v['id'] for v in search(c,'物品边界')['matches']}=={mine['id'],shared['id']}
    assert {v['id'] for v in search(other,'物品边界')['matches']}=={hidden['id'],shared['id']}
    shared=patch(other,oh,shared,visibility='private')
    assert [v['id'] for v in search(c,'物品边界')['matches']]==[mine['id']]
    response=c.delete('/api/inventory/items/'+mine['id'],headers=h,
        json={'requestId':rid(),'revision':mine['revision'],'confirmArchive':True})
    assert response.status_code==200,response.json
    assert search(c,'物品边界')['total']==0
    restarted=create_app(dict(app.config))
    assert search(clone(restarted,other),'物品边界')==search(other,'物品边界')
    assert c.get('/api/inventory/items/'+shared['id']).status_code==404
    assert c.get('/api/inventory/items/'+mine['id']).status_code==410


def test_paging_is_global_stable_and_literal(app):
    c,h=login(app)
    ids={create(c,h,title='页面共同词',variant=str(n))[0]['item']['id'] for n in range(4)}
    response=c.post('/api/items/tasks',headers=h,json={'title':'页面共同词'})
    assert response.status_code==201,response.json
    ids.add(response.json['id'])
    offset=0;actual=[]
    while offset is not None:
        result=search(c,'页面共同词',limit=2,offset=offset)
        assert result['total']==5 and len(result['matches'])<=2
        actual.extend((v['kind'],v['id']) for v in result['matches']);offset=result['nextOffset']
    assert actual==sorted(actual) and {v[1] for v in actual}==ids
    assert search(c,'页面共同词',offset=20)['matches']==[]
    assert c.get('/api/assistant/search?q=x&limit=31').status_code==400
    assert c.get('/api/assistant/search?q=x&q=y').status_code==400


def test_cross_household_and_foreign_cookie(app):
    c,h=login(app);create(c,h,title='ROOT_INVENTORY_ONLY')
    invitation=c.post('/api/spaces/invitations',json={},headers=h).json['invitation']
    child=app.test_client()
    response=child.post('/api/spaces/redeem',json={'invitation':invitation,'name':'第二合成库存户','slug':'inventory-search-two',
        'MEMBER1_PASSWORD':PASSWORD,'MEMBER2_PASSWORD':PASSWORD})
    assert response.status_code==201,response.json
    assert child.get(response.json['entry']).status_code==303
    child,ch=login(app,client=child);create(child,ch,title='CHILD_INVENTORY_ONLY')
    assert search(c,'CHILD_INVENTORY_ONLY')['total']==search(child,'ROOT_INVENTORY_ONLY')['total']==0
    assert search(child,'CHILD_INVENTORY_ONLY')['total']==1
    child.set_cookie('session',c.get_cookie('session').value)
    assert child.get('/api/assistant/search?q=INVENTORY').status_code==401


def test_tv_anonymous_and_logged_out_session(app):
    c,h=login(app);create(c,h,title='PRIVATE_INVENTORY')
    assert app.test_client().get('/api/assistant/search?q=PRIVATE').status_code==401
    tv=app.test_client();pair=tv.post('/api/pair/start',json={}).json
    assert c.post('/api/pair/approve',json={'code':pair['code'],'name':'合成搜索电视'},headers=h).status_code==200
    assert tv.post('/api/pair/poll',json={'secret':pair['secret']}).json['approved']
    assert tv.get('/api/assistant/search?q=PRIVATE').status_code==403
    assert c.get('/api/assistant/search?q=PRIVATE',headers={'X-Display-Mode':'tv'}).status_code in (401,403)
    old=clone(app,c)
    assert c.post('/api/logout',json={},headers=h).status_code==200
    assert old.get('/api/assistant/search?q=PRIVATE').status_code==401


@pytest.mark.parametrize('revoke',['auth_version','session'])
def test_fresh_session_inside_search_transaction(app,revoke):
    @app.before_request
    def changed_after_guard():
        if request.path=='/api/assistant/search':
            with connection(app) as con:
                if revoke=='auth_version':con.execute("UPDATE users SET auth_version=auth_version+1 WHERE id='member1'")
                else:con.execute('UPDATE member_sessions SET revoked_at=?',(time.time(),))
    c,h=login(app);create(c,h,title='MUST_NOT_RETURN')
    response=c.get('/api/assistant/search?q=MUST_NOT_RETURN')
    assert response.status_code in (401,409)
    assert 'MUST_NOT_RETURN' not in response.get_data(as_text=True)


def test_inventory_never_enters_model_context(app,monkeypatch):
    c,h=login(app);create(c,h,title='INVENTORY_PRIVATE_NAME',variant='INVENTORY_PRIVATE_SPEC')
    app.config.update(ASSISTANT_PROVIDER='openai',OPENAI_API_KEY='synthetic',OPENAI_MODEL='synthetic')
    calls=[]
    def fake(_config,prompt,context):
        calls.append((prompt,context));return {'summary':'合成草案','actions':[]}
    monkeypatch.setattr(home_assistant,'model_plan',fake)
    response=c.post('/api/assistant/plan',headers=h,json={'prompt':'安排本周事项','useModel':True,'includeHouseholdContext':True})
    assert response.status_code==200,response.json
    assert len(calls)==1 and 'INVENTORY_PRIVATE' not in json.dumps(calls)
    assert set(calls[0][1])=={'today','events','tasks'}



def test_search_quantities_use_current_inventory_projection_without_financial_sources(app,monkeypatch):
    c,h=login(app)
    shopping=c.post('/api/items/shopping',headers=h,json={'title':'普通采购',
        'actual':9900,'budget':10000,'done':True}).json
    item=create(c,h,title='数量物品',location='卧室抽屉',unit='节')[0]['item']
    current,_=acquisition(c,h,item,shoppingId=shopping['id'],orderedQty=6)
    current,_=move(c,h,current,quantity=4)
    current,_=move(c,h,current,'consume',1)
    current,_=move(c,h,current,'return',1)
    current,_=acquisition(c,h,current['item'],orderState='planned',orderedQty=3)
    before=counts(app)
    with connection(app) as con:
        entities_before=[tuple(row) for row in con.execute('SELECT * FROM entities ORDER BY id')]
    current_member=app.extensions['member_sessions'].current
    projections=[]
    original=inventory_core.project_item
    forbidden_reads=[]
    def restricted(con):
        assert con.in_transaction
        result=current_member(con)
        def authorize(op,table,column,*_):
            if op==sqlite3.SQLITE_READ and (table.startswith('hub_') or table in
                    {'inventory_source_links','inventory_operations','media_previews'}):
                forbidden_reads.append((table,column))
                return sqlite3.SQLITE_DENY
            if op in {sqlite3.SQLITE_INSERT,sqlite3.SQLITE_UPDATE,sqlite3.SQLITE_DELETE}:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        con.set_authorizer(authorize)
        return result
    def projection(con,actor,uid):
        assert con.in_transaction
        value=original(con,actor,uid)
        projections.append(value)
        return value
    monkeypatch.setattr(app.extensions['member_sessions'],'current',restricted)
    monkeypatch.setattr(inventory_core,'project_item',projection)
    response=c.get('/api/assistant/search?q=卧室抽屉')
    assert response.status_code==200,response.json
    assert response.headers['Cache-Control']=='no-store'
    match=response.json['matches'][0]
    expected={'kind','id','title','variant','location','unit','visibility','revision',
              'onHandQty','inTransitQty','plannedQty'}
    assert set(match)==expected
    assert len(projections)==1 and {k:v for k,v in match.items() if k!='kind'}=={
        k:projections[0][k] for k in expected-{'kind'}}
    assert (match['onHandQty'],match['inTransitQty'],match['plannedQty'])==(2,2,3)
    assert not forbidden_reads
    assert counts(app)==before
    with connection(app) as con:
        assert [tuple(row) for row in con.execute('SELECT * FROM entities ORDER BY id')]==entities_before


@pytest.mark.parametrize('method',['get','post'])
def test_search_rechecks_browser_generation_after_capture(app,monkeypatch,method):
    c,h=login(app);create(c,h,title='GENERATION_MUST_NOT_RETURN')
    sessions=app.extensions['member_sessions'];original=sessions.capture
    def changed(*args,**kwargs):
        result=original(*args,**kwargs)
        with connection(app) as con:
            con.execute('UPDATE member_session_browsers SET generation=generation+1')
        return result
    monkeypatch.setattr(sessions,'capture',changed)
    monkeypatch.setattr(inventory_core,'project_item',lambda *_:pytest.fail('Read inventory after stale generation'))
    if method=='get':response=c.get('/api/assistant/search?q=GENERATION_MUST_NOT_RETURN')
    else:response=c.post('/api/assistant/plan',headers=h,json={'prompt':'搜索 GENERATION_MUST_NOT_RETURN'})
    assert response.status_code==409,response.json
    assert 'GENERATION_MUST_NOT_RETURN' not in response.get_data(as_text=True)


def test_plan_search_preserves_capture_until_search_transaction(app,monkeypatch):
    c,h=login(app);create(c,h,title='CAPTURE_MUST_NOT_RETURN')
    sessions=app.extensions['member_sessions'];original=sessions.validate_context
    checks=[]
    def validate(con,context,**kwargs):
        checks.append(con.in_transaction)
        if len(checks)==2:
            # Same read transaction must reject a changed generation before any inventory read.
            con.execute('UPDATE member_session_browsers SET generation=generation+1')
        return original(con,context,**kwargs)
    monkeypatch.setattr(sessions,'validate_context',validate)
    monkeypatch.setattr(inventory_core,'project_item',lambda *_:pytest.fail('Read inventory after stale generation'))
    response=c.post('/api/assistant/plan',headers=h,json={'prompt':'搜索 CAPTURE_MUST_NOT_RETURN'})
    assert response.status_code==409 and checks==[True,True],response.json
    assert 'CAPTURE_MUST_NOT_RETURN' not in response.get_data(as_text=True)


def test_unicode_literal_location_and_private_pagination(app):
    c,h=login(app);other,oh=login(app,2)
    item=create(c,h,title='普通名称',variant='Straße',location='抽屉 100%_')[0]['item']
    for n in range(3):create(other,oh,title='普通名称隐藏'+str(n),location='抽屉 100%_')
    assert search(c,'STRASSE')['matches'][0]['id']==item['id']
    assert search(c,'100%_')['total']==1
    assert search(c,'100%_ ',limit=1)['nextOffset'] is None
    assert search(c,'普通名称隐藏')['total']==0
    assert search(c,'100%_',offset=1)['matches']==[]

def test_browser_real_inventory_navigation_and_fences(app,monkeypatch):
    from playwright.sync_api import sync_playwright, expect
    from werkzeug.serving import make_server, WSGIRequestHandler
    c,h=login(app);other,oh=login(app,2)
    candidates=[create(c,h,title='分页物品'+str(n))[0]['item'] for n in range(26)]
    target=patch(c,h,max(candidates,key=lambda item:item['id']),
        title='目标物品 <img src=x onerror=window.INJECTED=1>',variant='安全规格')
    shared=create(other,oh,title='伙伴物品',visibility='shared')[0]['item']
    app.config.update(ASSISTANT_PROVIDER='openai',OPENAI_API_KEY='synthetic',OPENAI_MODEL='synthetic')
    monkeypatch.setattr(home_assistant,'model_plan',lambda *_:pytest.fail('Search called model'))
    class Quiet(WSGIRequestHandler):
        def log(self,*_a,**_k):pass
    server=make_server('127.0.0.1',0,app,threaded=True,request_handler=Quiet)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    out=Path(__file__).resolve().parents[1]/'test-results'/'assistant-inventory-search'/str(time.time_ns());out.mkdir(parents=True)
    report={'passed':False,'actualAPI':True,'actualBrowser':'Edge','checks':[],'pageErrors':[],'externalRequests':[]}
    def passed(value):report['checks'].append(value)
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True)
            ctx=browser.new_context(viewport={'width':390,'height':844})
            def route(r):
                if r.request.url.startswith(base+'/'):r.continue_()
                else:report['externalRequests'].append(r.request.url);r.abort()
            ctx.route('**/*',route)
            assert ctx.request.post(base+'/api/login',data={'username':'member1','password':PASSWORD}).status==200
            page=ctx.new_page();page.on('pageerror',lambda e:report['pageErrors'].append(str(e)))
            page.goto(base+'/classic');expect(page.locator('.ps-welcome')).to_be_visible()
            def run_search(text):
                page.evaluate('HomeAssistant.open()');expect(page.locator('#assistant-refresh')).to_be_enabled()
                page.locator('#assistant-form textarea').fill('搜索 '+text)
                page.locator('[name=useModel]').check();page.locator('#assistant-form button[type=submit]').click()
                expect(page.locator('#assistant-result')).to_contain_text('当前可见')
                expect(page.locator('#assistant-refresh')).to_be_enabled()
            run_search('物品')
            expect(page.locator('.assistant-search-record')).to_have_count(20)
            page.locator('[data-assistant-action=search-page]').click();expect(page.locator('.assistant-search-record')).to_have_count(7)
            passed('real_combined_search_pagination')
            run_search('目标物品');expect(page.locator('.assistant-search-record')).to_contain_text('安全规格')
            page.locator('[data-assistant-action=inventory]').click();page.wait_for_url('**/classic#inventory')
            expect(page.locator('.iv-detail')).to_contain_text(target['title']);expect(page.locator('[data-iv=edit-item]')).to_be_enabled()
            assert page.locator('.iv-card[data-id="'+target['id']+'"]').count()==0  # Beyond initial 24-item page.
            assert page.evaluate('window.INJECTED') is None
            page.screenshot(path=str(out/'phone-detail.png'));passed('escaped_search_opens_real_detail_outside_first_page')
            page.locator('[data-iv=edit-item]').click();page.locator('[data-iv-form] [name=title]').fill('尚未保存的库存草稿')
            run_search('伙伴物品')
            with page.expect_event('dialog') as dialog:
                page.locator('[data-assistant-action=inventory]').click()
            dialog.value.dismiss()
            expect(page.locator('#dialog')).not_to_be_visible()
            expect(page.locator('[data-iv-form] [name=title]')).to_have_value('尚未保存的库存草稿')
            passed('declining_navigation_preserves_inventory_draft')
            run_search('伙伴物品')
            with page.expect_event('dialog') as dialog:
                page.locator('[data-assistant-action=inventory]').click()
            dialog.value.accept()
            expect(page.locator('.iv-detail')).to_contain_text('伙伴物品');expect(page.locator('[data-iv=edit-item]')).to_have_count(0)
            passed('confirmed_navigation_reads_shared_detail_without_owner_controls')
            run_search('目标物品');page.locator('[data-assistant-action=inventory]').click()
            expect(page.locator('[data-iv=edit-item]')).to_be_enabled()
            page.set_viewport_size({'width':1440,'height':900});page.screenshot(path=str(out/'desktop-detail.png'))
            page.locator('[data-iv=edit-item]').click()
            page.locator('[data-iv-form] [name=title]').fill('目标物品 已实际保存')
            dropped=[]
            def drop_write(r):
                if r.request.method!='PATCH':r.continue_();return
                response=r.fetch();assert response.status==200
                dropped.append(r.request.post_data_json);r.abort()
            ctx.route('**/api/inventory/items/'+target['id'],drop_write)
            page.locator('[data-iv-form] [type=submit]').click()
            expect(page.locator('[data-iv=retry]')).to_be_enabled()
            assert len(dropped)==1
            run_search('伙伴物品');page.locator('[data-assistant-action=inventory]').click()
            expect(page.locator('#dialog')).not_to_be_visible()
            expect(page.locator('[data-iv-message]')).to_contain_text('核对保留的库存操作')
            expect(page.locator('[data-iv-form] [name=title]')).to_have_value('目标物品 已实际保存')
            ctx.unroute('**/api/inventory/items/'+target['id'],drop_write)
            page.locator('[data-iv=retry]').click()
            expect(page.locator('[data-iv=edit-item]')).to_be_enabled()
            expect(page.locator('.iv-detail')).to_contain_text('目标物品 已实际保存')
            with connection(app) as con:
                assert con.execute('SELECT count(*) FROM inventory_operations WHERE request_id=?',(dropped[0]['requestId'],)).fetchone()[0]==1
            passed('unknown_real_write_blocks_navigation_and_original_receipt_recovers_once')
            run_search('伙伴物品');shared=patch(other,oh,shared,visibility='private')
            page.locator('[data-assistant-action=inventory]').click()
            expect(page.locator('.iv-detail')).to_have_count(0);expect(page.locator('[data-iv-message]')).to_contain_text('不再可见')
            passed('revoked_share_between_search_and_click_never_displays_cached_detail')
            run_search('目标物品')
            token=ctx.request.get(base+'/api/me').json()['csrf']
            def revoked_late(r):
                response=r.fetch()
                assert ctx.request.post(base+'/api/logout',data={},headers={'X-CSRF-Token':token}).status==200
                r.fulfill(response=response)
            ctx.route('**/api/inventory/items/'+target['id'],revoked_late)
            page.locator('[data-assistant-action=inventory]').click()
            expect(page.locator('.iv-detail')).to_have_count(0)
            expect(page.locator('#ps-inventory-workspace')).to_contain_text('成员或家庭已变化')
            passed('late_real_detail_discarded_after_logout')
            assert not report['pageErrors'] and not report['externalRequests'],report
            report['passed']=True;ctx.close();browser.close()
    finally:
        server.shutdown();thread.join(timeout=5);server.server_close()
        (out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
