"""Journey execution in temporary Flask/SQLite/Edge; only synthetic provider IO.

No production inputs, real credentials or external network are used. Backend
provider adapters and publication queues remain real; their transport is the
existing in-memory test provider. Read races hold actual HTTP responses.
"""
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import traceback
from urllib.parse import urlsplit
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from app import create_app, TZ
from test_task_publish import Remote as TaskRemote
from test_calendar_publish import Remote as CalendarRemote
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server, WSGIRequestHandler


class Quiet(WSGIRequestHandler):
    def log(self, *_args, **_kwargs):
        pass


def source_hashes():
    paths = set(ROOT.glob('*.py')) | {Path(__file__), ROOT/'tests/test_task_publish.py', ROOT/'tests/test_calendar_publish.py'}
    for folder in ('static', 'deploy'):
        paths.update(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    paths.update(ROOT/name for name in ('Dockerfile', 'compose.yaml', 'requirements.txt', 'pytest.ini') if (ROOT/name).is_file())
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


class Fixture:
    def __init__(self, folder, report):
        self.report = report
        self.tasks = {provider: TaskRemote() for provider in ('microsoft', 'google')}
        self.calendar = CalendarRemote()
        self.app = create_app({'TESTING': True, 'DATA_DIR': str(folder), 'SECRET_KEY': 'synthetic-journey-execution-key',
                              'SESSION_COOKIE_SECURE': False, 'PUBLIC_ORIGIN': 'http://localhost',
                              'MEMBER1_PASSWORD': 'testing-password-one', 'MEMBER2_PASSWORD': 'testing-password-two',
                              'MICROSOFT_CLIENT_ID': 'test-client', 'MICROSOFT_CLIENT_SECRET': 'synthetic-secret',
                              'GOOGLE_CLIENT_ID': 'test-client', 'GOOGLE_CLIENT_SECRET': 'synthetic-secret',
                              'CLOUD_TRANSPORT': self.transport, 'OAUTH_TRANSPORT': self.deny,
                              'OPENAI_API_KEY': '', 'OPENAI_MODEL': ''})
        assert self.app.config['SESSION_REFRESH_EACH_REQUEST'] is False
        self.database = Path(folder)/'household.sqlite3'
        self.cloud = self.app.extensions['cloud_accounts']
        self.client = self.app.test_client()
        assert self.client.post('/api/login', json={'username':'member1','password':'testing-password-one'}).status_code == 200
        self.headers = {'X-CSRF-Token':self.client.get('/api/me').json['csrf']}
        now = datetime.now(TZ).date()
        start, end = (now+timedelta(days=10)).isoformat(), (now+timedelta(days=13)).isoformat()
        plan = {'schemaVersion':2, 'referenceTimezone':'Asia/Shanghai', 'title':'虚构旅行 A · 执行核对',
                'start':start, 'end':end, 'international':False, 'memberIds':['member1','member2'],
                'budget':100000, 'saved':10000, 'paid':5000,
                'destinations':[{'key':'coast','country':'中国','city':'虚构海滨','arrival':start,'departure':end,'timeZone':'Asia/Shanghai'}],
                'checklist':[{'key':owner,'title':label+' · 合成准备','owner':owner,'due':start,'note':'虚构记录'}
                             for owner,label in [('member1','我'),('member2','伴侣'),('shared','共同')]],
                'shopping':[{'key':owner,'title':label+' · 合成采购','owner':owner,'quantity':'1 件','budget':1000}
                            for owner,label in [('member1','我'),('member2','伴侣'),('shared','共同')]],
                'segments':[{'key':'walk','kind':'activity','title':'虚构海边活动','location':'合成步道',
                             'start':{'local':start+'T10:00','timeZone':'Asia/Shanghai'},
                             'end':{'local':start+'T11:00','timeZone':'Asia/Shanghai'}}]}
        self.journey = self.create(plan, 'synthetic-execution-a')
        self.other = self.create({**deepcopy(plan),'title':'虚构旅行 B · 后来页面'}, 'synthetic-execution-b')
        detail = self.detail()
        self.task_ids = {item['owner']:item['id'] for item in detail['tasks']}
        self.shopping_ids = {item['owner']:item['id'] for item in detail['shopping']}
        self.trip_id = detail['tripId']
        self.owners = {item['id']:item['owner'] for kind in ('tasks','shopping','events') for item in detail[kind]}
        with self.cloud.db() as con:
            for provider in ('microsoft','google'):
                scopes = 'User.Read Calendars.ReadWrite Tasks.ReadWrite' if provider=='microsoft' else 'https://www.googleapis.com/auth/tasks https://www.googleapis.com/auth/calendar.readonly'
                tokens = self.cloud.encrypt({'access_token':'synthetic-token','refresh_token':'synthetic-refresh','scope':scopes,'expires_at':time.time()+7200})
                aid = 'synthetic-'+provider
                con.execute('INSERT INTO cloud_accounts(id,owner,provider,client_id,subject,name,email,tokens) VALUES(?,?,?,?,?,?,?,?)',
                            (aid,'member1',provider,'test-client',aid,'合成账户 '+provider,aid+'@example.invalid',tokens))
                con.execute("INSERT INTO cloud_sources(id,account_id,remote_id,kind,name,owner) VALUES(?,?,?,'tasks',?,'shared')",
                            ('tasks-'+provider,aid,'list-1','合成主清单 '+provider))
            con.execute("INSERT INTO cloud_sources(id,account_id,remote_id,kind,name,owner) VALUES('calendar-ms','synthetic-microsoft','calendar-1','calendar','合成旅行日历','member1')")
        self.publications = {}
        for provider, owner in [('microsoft','member1'),('google','member2')]:
            value = self.post('/api/task-publish/preview', {'entityIds':[self.task_ids[owner]],'sourceId':'tasks-'+provider})
            confirmed = self.post('/api/task-publish/confirm', {'previewToken':value['previewToken']})
            rid = confirmed['publicationIds'][0]
            self.app.extensions['task_publish'].process(rid)
            assert self.task_publication(rid)['status']=='published'
            self.publications[provider] = rid
        value = self.post('/api/calendar-publish/preview', {'journeyId':self.journey,'sourceId':'calendar-ms'})
        confirmed = self.post('/api/calendar-publish/confirm', {'journeyId':self.journey,'sourceId':'calendar-ms','previewToken':value['previewToken']})
        self.calendar_ids = confirmed['publicationIds']
        for rid in self.calendar_ids:
            self.app.extensions['calendar_publish'].process(rid)
        self.initial_ids = self.link_identity()
        self.business_private = self.private_snapshot()

    def deny(self, *_args, **_kwargs):
        self.report['unexpectedProviderCalls'].append('unexpected OAuth/model transport')
        raise AssertionError('Unexpected provider operation')

    def transport(self, method, url, token, body=None, headers=None):
        parsed = urlsplit(url)
        assert parsed.hostname in {'graph.microsoft.com','www.googleapis.com','tasks.googleapis.com'}, parsed.hostname
        self.report['fakeProviderCalls'].append({'method':method,'host':parsed.hostname,'path':parsed.path})
        if '/tasks' in parsed.path:
            provider = 'microsoft' if parsed.hostname=='graph.microsoft.com' else 'google'
            return self.tasks[provider].transport(method,url,token,body,headers)
        return self.calendar.transport(method,url,token,body,headers)

    def sql(self, statement, args=()):
        with closing(sqlite3.connect(self.database)) as con:
            rows = con.execute(statement,args).fetchall(); con.commit(); return rows

    def post(self, path, value):
        r=self.client.post(path,json=value,headers=self.headers)
        assert r.status_code in (200,201), (path,r.status_code,r.json)
        return r.json

    def create(self, plan, key):
        p=self.post('/api/journeys/preview',{'plan':plan})
        return self.post('/api/journeys/apply',{'previewToken':p['previewToken'],'idempotencyKey':key})['id']

    def detail(self):
        response=self.client.get('/api/journeys/'+self.journey)
        assert response.status_code==200
        return response.json

    def item(self, kind, uid):
        return next(row for row in self.detail()[kind] if row['id']==uid)

    def update(self, kind, uid, **changes):
        row=self.item(kind,uid)
        response=self.client.patch('/api/items/'+kind+'/'+uid,json={'revision':row['revision'],**changes},headers=self.headers)
        assert response.status_code==200,(response.status_code,response.json)

    def task_publication(self, rid):
        with self.cloud.db() as con:
            return dict(con.execute('SELECT * FROM task_publications WHERE id=?',(rid,)).fetchone())

    def remote_done(self, provider, done=True):
        rid=self.publications[provider]; row=self.task_publication(rid); raw=self.tasks[provider].records[row['remote_id']]
        raw['status']='completed' if done else ('notStarted' if provider=='microsoft' else 'needsAction')
        raw['@odata.etag' if provider=='microsoft' else 'etag']='"synthetic-change-'+str(time.monotonic_ns())+'"'
        self.app.extensions['task_publish'].process(rid)
        assert self.item('tasks',row['entity_id'])['done'] is done

    def link_identity(self):
        detail=self.detail()
        return {'journey':detail['id'],'trip':detail['tripId'],
                'links':self.sql('SELECT journey_id,item_key,entity_id,kind FROM journey_links WHERE journey_id=? ORDER BY item_key',(self.journey,)),
                'taskPublications':self.sql('SELECT id,entity_id,journey_id,owner,source_id,remote_id FROM task_publications ORDER BY id'),
                'calendarPublications':self.sql('SELECT id,entity_id,journey_id,owner,source_id,remote_id FROM calendar_publications ORDER BY id'),
                'owners':{item['id']:item['owner'] for kind in ('tasks','shopping','events') for item in detail[kind]}}

    def private_snapshot(self):
        return {table:self.sql('SELECT * FROM '+table+' ORDER BY 1') for table in ('hub_transactions','hub_investments','finance_baselines','finance_spending_observations','private_finance')}


def main():
    out=ROOT/'test-results';out.mkdir(exist_ok=True)
    report={'passed':False,'checks':[],'screenshots':[],'pageErrors':[],'externalRequests':[],
            'unexpectedProviderCalls':[],'fakeProviderCalls':[],'requestCounts':{},'sourceHashes':source_hashes(),
            'realCloudWrites':0,'productionWrites':0,'realPrivateInputs':0,
            'scope':'Temporary real Flask/SQLite/Edge; synthetic transport only, actual publication queues; no real provider or production verification.'}
    run_stamp=datetime.now().strftime('%Y%m%dT%H%M%S%f');report['runId']=run_stamp
    active_page=None; fixture=None
    def passed(name, **details):
        assert all(row['name']!=name for row in report['checks'])
        report['checks'].append({'name':name,'passed':True,**details})
        print('PASS '+name,flush=True)
    def shot(page,name):
        path=out/('journey-execution-'+name+'-'+run_stamp+'.png');page.screenshot(path=str(path),full_page=True)
        report['screenshots'].append({'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    original_connect=socket.socket.connect; original_connect_ex=socket.socket.connect_ex; original_dns=socket.getaddrinfo
    def allowed(host):return host in {'127.0.0.1','::1','localhost',b'127.0.0.1',b'::1',b'localhost'}
    def guarded_connect(sock,address):
        if isinstance(address,tuple) and not allowed(address[0]):
            report['externalRequests'].append({'socket':'connect','host':str(address[0])});raise AssertionError('External socket denied')
        return original_connect(sock,address)
    def guarded_connect_ex(sock,address):
        if isinstance(address,tuple) and not allowed(address[0]):
            report['externalRequests'].append({'socket':'connect_ex','host':str(address[0])});raise AssertionError('External socket denied')
        return original_connect_ex(sock,address)
    def guarded_dns(host,*args,**kwargs):
        if host is not None and not allowed(host):
            report['externalRequests'].append({'socket':'DNS','host':str(host)});raise AssertionError('External DNS denied')
        return original_dns(host,*args,**kwargs)
    try:
        with patch.object(socket.socket,'connect',guarded_connect), patch.object(socket.socket,'connect_ex',guarded_connect_ex), patch.object(socket,'getaddrinfo',guarded_dns), tempfile.TemporaryDirectory(prefix='journey-execution-browser-') as folder:
            fixture=Fixture(folder,report)
            server=make_server('127.0.0.1',0,fixture.app,threaded=True,request_handler=Quiet)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{server.server_port}'
            try:
                with sync_playwright() as pw:
                    browser=pw.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
                    def login(ctx, number=1, child=False):
                        fixture.sql('DELETE FROM attempts')
                        ctx.request.get(base+'/api/me')
                        password=('child-password-' if child else 'testing-password-')+('one' if number==1 else 'two')
                        r=ctx.request.post(base+'/api/login',data={'username':f'member{number}','password':password});assert r.status==200,(r.status,r.text())
                    def auth(ctx):return {'X-CSRF-Token':ctx.request.get(base+'/api/me').json()['csrf']}
                    admin=browser.new_context();login(admin)
                    inv=admin.request.post(base+'/api/spaces/invitations',headers=auth(admin),data={});assert inv.status==201
                    child=admin.request.post(base+'/api/spaces/redeem',headers=auth(admin),data={'invitation':inv.json()['invitation'],'name':'虚构旅行第二家庭','slug':'synthetic-execution-child','MEMBER1_PASSWORD':'child-password-one','MEMBER2_PASSWORD':'child-password-two'})
                    assert child.status==201;child_entry=child.json()['entry']

                    class Flow:
                        def __init__(self,width=1440,number=1):
                            self.ctx=browser.new_context(viewport={'width':width,'height':1000});self.calls=[];self.gate=None;self.held=[];self.fail=set()
                            self.ctx.add_init_script('''const originalFetch=window.fetch; window.executionPendingFetches=new Set(); let serial=0;
                                window.fetch=async function(...args){const id=++serial;executionPendingFetches.add(id);try{return await originalFetch.apply(this,args);}finally{executionPendingFetches.delete(id);}};''')
                            self.ctx.route('**/*',self.route);login(self.ctx,number)
                            self.page=self.ctx.new_page();self.page.on('pageerror',lambda error:report['pageErrors'].append(str(error)))
                            self.page.goto(base+'/#trips');expect(self.page.locator('.ps-trip-grid')).to_be_visible()
                        def route(self,route):
                            req=route.request;path=urlsplit(req.url).path
                            if not req.url.startswith(base+'/'):
                                report['externalRequests'].append({'method':req.method,'path':path});route.abort();return
                            key=req.method+' '+path;self.calls.append(key);report['requestCounts'][key]=report['requestCounts'].get(key,0)+1
                            if key in self.fail:route.fulfill(status=503,json={'error':'SYNTHETIC_READ_FAILURE'});return
                            if self.gate and self.gate(req.method,path):
                                self.gate=None;response=route.fetch()
                                if req.method=='GET':assert 'set-cookie' not in response.headers
                                self.held.append((route,response));return
                            route.continue_()
                        def hold(self,path,method='GET',occurrence=1):
                            count=[0]
                            def match(actual_method,actual_path):
                                if (actual_method,actual_path)==(method,path):count[0]+=1;return count[0]==occurrence
                                return False
                            self.gate=match
                        def wait_held(self):
                            deadline=time.monotonic()+15
                            while not self.held and time.monotonic()<deadline:self.page.wait_for_timeout(25)
                            assert self.held,'Expected delayed actual request'
                        def release(self,error=False):
                            route,response=self.held.pop(0)
                            if error:route.fulfill(status=503,json={'error':'SYNTHETIC_LATE_FAILURE'})
                            else:route.fulfill(response=response)
                            deadline=time.monotonic()+15;settled=False
                            while time.monotonic()<deadline:
                                settled=self.page.evaluate('window.executionPendingFetches.size===0')
                                if settled:break
                                self.page.wait_for_timeout(25)
                            # Cache the observed settled state: a new ordinary
                            # ten-second poll may begin after that observation.
                            assert settled,'Actual delayed request chain did not finish'
                            self.page.wait_for_timeout(50)
                        def open(self,journey=None):
                            self.page.evaluate('(id)=>JourneyUI.open(id)',journey or fixture.journey)
                            expect(self.page.locator('#journey-execution')).to_be_visible()
                            expect(self.page.locator('[data-journey=refresh-execution]')).to_be_enabled()
                        def refresh(self):self.page.locator('[data-journey=refresh-execution]').click()
                        def close(self):
                            if sys.exc_info()[0] is not None:
                                try:
                                    shot(self.page,'failure-'+str(len(report['checks'])))
                                    report['failureView']={'urlPath':urlsplit(self.page.url).path,'dialogText':self.page.locator('#dialog').inner_text()[:5000]}
                                except Exception:pass
                            self.gate=None
                            for route,response in self.held:
                                try:route.fulfill(response=response)
                                except Exception:pass
                            self.held=[]
                            try:self.ctx.request.post(base+'/api/logout',headers=auth(self.ctx),data={})
                            except Exception:pass
                            self.ctx.close()

                    # Scenarios are filled below only against the frozen real UI.
                    flow=Flow();active_page=flow.page
                    try:
                        run_execution(flow,fixture,passed,shot,login,auth,child_entry,base)
                    finally:flow.close()
                    run_races(Flow,fixture,passed,login,auth,child_entry,base)
                    viewer=Flow(number=2)
                    try:
                        viewer.open();viewer.page.locator('[data-journey-owner-filter]').select_option('mine')
                        expect(viewer.page.locator(f'[data-journey-item="{fixture.task_ids["member2"]}"]')).to_be_visible()
                        expect(viewer.page.locator(f'[data-journey-item="{fixture.task_ids["member1"]}"]')).to_have_count(0)
                        expect(viewer.page.locator('#journey-execution')).not_to_contain_text('合成账户 microsoft')
                        passed('second_member_mine_filter_uses_actual_member_without_other_account_details')
                    finally:viewer.close()
                    for mode in ('demo','tv'):
                        ctx=browser.new_context(viewport={'width':1280,'height':800});calls=[]
                        def public_guard(route):
                            req=route.request;path=urlsplit(req.url).path
                            if not req.url.startswith(base+'/'):
                                report['externalRequests'].append({'method':req.method,'path':path});route.abort();return
                            calls.append((req.method,path));route.continue_()
                        ctx.route('**/*',public_guard)
                        if mode=='tv':
                            login(admin)
                            pair=ctx.request.post(base+'/api/pair/start',data={}).json()
                            approved=admin.request.post(base+'/api/pair/approve',headers=auth(admin),data={'code':pair['code'],'name':'虚构执行验收电视','focus':'member1','calendarView':'today'})
                            assert approved.status==200
                            assert ctx.request.post(base+'/api/pair/poll',data={'secret':pair['secret']}).json()['approved']
                        page=ctx.new_page();page.on('pageerror',lambda error:report['pageErrors'].append(str(error)))
                        page.goto(base+('/demo' if mode=='demo' else '/tv'))
                        expect(page.locator('.ps-welcome' if mode=='demo' else '.board')).to_be_visible()
                        before=len(calls);page.evaluate('(id)=>JourneyUI.open(id)',fixture.journey);page.wait_for_timeout(200)
                        assert not any('/api/journeys' in path or '/api/task-publish' in path or '/api/calendar-publish' in path for _,path in calls[before:])
                        assert not any(method not in ('GET','HEAD') for method,_ in calls[before:])
                        passed(mode+'_execution_entry_has_no_new_private_reads_or_member_writes')
                        ctx.close()
                    report['identitiesPreserved']=fixture.link_identity()==fixture.initial_ids
                    report['privateFinanceUnchanged']=fixture.private_snapshot()==fixture.business_private
                    assert report['identitiesPreserved'] and report['privateFinanceUnchanged']
                    assert not report['externalRequests'] and not report['pageErrors'] and not report['unexpectedProviderCalls']
                    admin.close();browser.close()
            finally:
                server.shutdown();server.server_close();thread.join(timeout=5)
            report['passed']=True
    except BaseException as error:
        report['failure']={'type':type(error).__name__,'message':str(error),'traceback':traceback.format_exc()}
        if active_page is not None:
            try:shot(active_page,'failure')
            except Exception:pass
        traceback.print_exc()
    finally:
        report['sourceHashesAfter']=source_hashes();report['sourceUnchanged']=report['sourceHashes']==report['sourceHashesAfter']
        report['passed']=report['passed'] and report['sourceUnchanged']
        report['exitCode']=0 if report['passed'] else 1
        (out/'journey-execution-browser-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'sourceUnchanged':report['sourceUnchanged'],'failure':report.get('failure',{}).get('message')},ensure_ascii=False))
    return report['exitCode']


def run_execution(flow, fixture, passed, shot, login, auth, child_entry, base):
    page=flow.page;flow.open()
    root=page.locator('#journey-execution')
    expect(root).to_have_attribute('data-journey-id',fixture.journey)
    expect(page.locator('[data-journey-region=tasks] [data-journey-item]')).to_have_count(3)
    expect(page.locator('[data-journey-region=shopping] [data-journey-item]')).to_have_count(3)
    passed('actual_journey_detail_contains_original_three_owner_tasks_and_shopping')
    owner_filter=page.locator('[data-journey-owner-filter]')
    for value,owner in [('mine','member1'),('partner','member2'),('shared','shared')]:
        owner_filter.select_option(value)
        for kind,ids in [('tasks',fixture.task_ids),('shopping',fixture.shopping_ids)]:
            expect(page.locator(f'[data-journey-region={kind}] [data-journey-item]:visible')).to_have_count(1)
            expect(page.locator(f'[data-journey-item="{ids[owner]}"]')).to_be_visible()
        passed('owner_filter_'+value+'_includes_only_matching_shared_entities')
    owner_filter.select_option('mine')
    owner_filter.focus()
    page.evaluate('window.executionOriginalRoot=document.getElementById("journey-execution");window.executionOriginalFilter=document.querySelector("[data-journey-owner-filter]")')
    before=len(flow.calls)
    fixture.remote_done('microsoft');fixture.remote_done('google')
    # Let the real foreground ten-second timer run; no refresh, close or reopen.
    expect(page.locator(f'[data-journey-item="{fixture.task_ids["member1"]}"] [data-journey=toggle]')).to_have_attribute('aria-pressed','true',timeout=22000)
    expect(page.locator('[data-journey-region=tasks]')).to_contain_text('2 / 3')
    assert any(call=='GET /api/journeys/'+fixture.journey for call in flow.calls[before:])
    assert page.evaluate('executionOriginalRoot===document.getElementById("journey-execution") && executionOriginalFilter===document.querySelector("[data-journey-owner-filter]")')
    expect(owner_filter).to_have_value('mine');expect(owner_filter).to_be_focused()
    passed('real_MS_and_Google_completion_roundtrip_auto_updates_original_detail_filter_and_focus_without_reopen')
    for provider,owner in [('microsoft','member1'),('google','member2')]:
        assert fixture.task_publication(fixture.publications[provider])['entity_id']==fixture.task_ids[owner]
    owner_filter.select_option('all')
    local=fixture.task_ids['member1'];remote=fixture.tasks['microsoft'];rid=fixture.publications['microsoft']
    fixture.remote_done('microsoft',False)
    flow.refresh();expect(page.locator(f'[data-journey=toggle][data-id="{local}"]')).to_have_attribute('aria-pressed','false')
    before_patch=remote.patched
    page.locator(f'[data-journey=toggle][data-id="{local}"]').click()
    expect(page.locator(f'[data-journey=toggle][data-id="{local}"]')).to_have_attribute('aria-pressed','true')
    assert fixture.item('tasks',local)['done'] is True
    assert remote.records[fixture.task_publication(rid)['remote_id']]['status']=='notStarted' and remote.patched==before_patch
    publications=fixture.client.get('/api/task-publish/state?journeyId='+fixture.journey).json['publications']
    publication=next(row for row in publications if row['id']==rid)
    assert publication['status']=='published' and publication['localChangesPending'] is True
    task_status=page.locator(f'[data-journey-task-status="{local}"]')
    expect(task_status).to_contain_text('等待')
    assert '已同步完成' not in task_status.inner_text()
    passed('local_completion_state_and_last_cloud_success_are_distinct_before_worker')
    fixture.app.extensions['task_publish'].process(rid)
    assert remote.records[fixture.task_publication(rid)['remote_id']]['status']=='completed'
    publication=next(row for row in fixture.client.get('/api/task-publish/state?journeyId='+fixture.journey).json['publications'] if row['id']==rid)
    assert publication['localChangesPending'] is False
    flow.refresh();expect(task_status).to_contain_text('上次同步成功')
    passed('worker_acknowledgement_clears_real_localChangesPending_without_new_publication')
    shared=fixture.shopping_ids['shared'];fixture.update('shopping',shared,actual=2500)
    flow.refresh();expect(page.locator('[data-journey=refresh-execution]')).to_be_enabled()
    page.locator(f'[data-journey=toggle][data-id="{shared}"]').click()
    expect(page.locator(f'[data-journey=toggle][data-id="{shared}"]')).to_have_attribute('aria-pressed','true')
    assert fixture.item('shopping',shared)['done'] and fixture.detail()['budget']['purchaseActual']==2500
    expect(page.locator('[data-journey-region=shopping]')).to_contain_text('1 / 3')
    passed('inline_purchase_completion_reads_actual_progress_and_budget_without_new_entities')
    # A changed revision is detected by the actual preflight read.
    partner=fixture.shopping_ids['member2'];fixture.update('shopping',partner,title='伴侣 · 合成采购已被另一页面修改')
    page.locator(f'[data-journey=toggle][data-id="{partner}"]').click()
    expect(page.locator(f'[data-journey-item="{partner}"]')).to_contain_text('已被另一页面修改')
    assert fixture.item('shopping',partner)['done'] is False
    passed('changed_inline_toggle_preflight_reads_latest_without_overwriting_concurrent_item')
    # Hold the actual preflight snapshot, then commit a competing update. The
    # subsequent PATCH must get 409 and read the true newest version back.
    flow.hold('/api/journeys/'+fixture.journey)
    page.locator(f'[data-journey=toggle][data-id="{partner}"]').click();flow.wait_held()
    fixture.update('shopping',partner,title='伴侣 · 合成采购实际409的新版本')
    flow.release()
    expect(page.locator(f'[data-journey-item="{partner}"]')).to_contain_text('实际409的新版本')
    assert fixture.item('shopping',partner)['done'] is False
    expect(page.locator('#journey-execution-status')).to_contain_text('新的修改')
    passed('actual_inline_toggle_409_reads_latest_without_repeating_the_write')
    for theme in ('forest','light','ocean'):
        page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
        for width,height in [(360,900),(768,1024),(1440,1000)]:
            page.set_viewport_size({'width':width,'height':height})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1 && document.getElementById("dialog").scrollWidth<=document.getElementById("dialog").clientWidth+1')
            shot(page,f'{theme}-{width}')
        passed('three_resolutions_no_horizontal_overflow_'+theme)
    page.set_viewport_size({'width':1440,'height':1000})
    flow.refresh();expect(page.locator('#journey-execution-status')).to_contain_text('已读取')
    for width,height in [(1440,1000),(360,900)]:
        page.set_viewport_size({'width':width,'height':height})
        page.evaluate('''() => { for(const node of document.querySelectorAll('#dialog, #dialog *')) if(node.scrollHeight>node.clientHeight) node.scrollTop=0; }''')
        expect(page.locator('[data-journey-owner-filter]')).to_be_in_viewport()
        expect(page.locator('#journey-execution-status')).to_be_in_viewport()
        shot(page,'top-'+str(width))
    page.set_viewport_size({'width':1440,'height':1000})
    # A real task conflict, then use the original conflict viewer and its back.
    fixture.update('tasks',local,title='本地准备内容 · 合成冲突')
    raw=remote.records[fixture.task_publication(rid)['remote_id']]
    raw['title']='远端准备内容 · 合成冲突';raw['@odata.etag']='"synthetic-conflict"'
    fixture.app.extensions['task_publish'].process(rid)
    assert fixture.task_publication(rid)['status']=='conflict'
    flow.refresh();expect(task_status).to_contain_text('需要处理')
    owner_filter.select_option('mine')
    writes_before=len([x for x in fixture.report['fakeProviderCalls'] if x['method']!='GET'])
    page.locator(f'[data-journey=task-publication][data-id="{local}"]').click()
    expect(page.locator('#task-publish-root')).to_be_visible()
    expect(page.locator('#task-publish-form input:checked')).to_have_count(0)
    assert len([x for x in fixture.report['fakeProviderCalls'] if x['method']!='GET'])==writes_before
    page.locator(f'[data-tp=conflict-preview][data-id="{rid}"]').click()
    expect(page.locator('#dialog-title')).to_have_text('核对两边待办内容')
    page.locator('[data-tp=resolve][data-resolution=remote]').click()
    expect(page.locator('#task-publish-root')).to_be_visible()
    page.locator('[data-tp=back]').click();expect(root).to_be_visible()
    expect(page.locator(f'[data-journey-item="{local}"]')).to_contain_text('远端准备内容')
    expect(owner_filter).to_have_value('mine')
    assert fixture.item('tasks',local)['owner']=='member1'
    passed('task_conflict_original_resolution_returns_same_journey_filter_and_owner_without_auto_selection')
    # Change v2 time via actual preview/apply; backend creates review hold.
    detail=fixture.detail();plan=detail['plan'];plan['segments'][0]['start']['local']=plan['start']+'T12:00'
    plan['segments'][0]['end']['local']=plan['start']+'T13:00'
    for point in ('start','end'):
        plan['segments'][0][point].pop('instant',None);plan['segments'][0][point].pop('offsetMinutes',None)
        plan['segments'][0][point]['timeZone']='UTC'
    preview=fixture.post('/api/journeys/preview',{'journeyId':fixture.journey,'revision':detail['revision'],'plan':plan})
    assert preview['summary']['cloudReviews'],preview['summary']
    fixture.post('/api/journeys/apply',{'previewToken':preview['previewToken'],'idempotencyKey':'synthetic-execution-time-review'})
    held=fixture.sql("SELECT id FROM calendar_publications WHERE journey_id=? AND review_required=1",(fixture.journey,));assert held
    flow.refresh();expect(page.locator('#journey-calendar-publications')).to_contain_text('需要核对后继续')
    page.locator('[data-journey=calendar-publication]').first.click();expect(page.locator('#calendar-publish-root')).to_be_visible()
    before=len([x for x in fixture.report['fakeProviderCalls'] if x['method']!='GET'])
    page.locator(f'[data-cp=review-preview][data-id="{held[0][0]}"]').click()
    expect(page.locator('#dialog-title')).to_have_text('核对旅行时间变化')
    assert len([x for x in fixture.report['fakeProviderCalls'] if x['method']!='GET'])==before
    page.locator('[data-cp=review-confirm]').click();expect(page.locator('#calendar-publish-root')).to_be_visible()
    page.locator('[data-cp=back]').click();expect(root).to_be_visible()
    for row in held:fixture.app.extensions['calendar_publish'].process(row[0])
    flow.refresh();expect(page.locator('#journey-calendar-publications')).not_to_contain_text('需要核对后继续')
    passed('real_v2_timing_review_uses_original_calendar_confirmation_and_returns_same_trip')
    # Reading failure keeps the settled last detail, with visible stale state and retry.
    expect(page.locator('[data-journey=refresh-execution]')).to_be_enabled()
    owner_filter.select_option('all')
    before=page.locator('#journey-detail-body').inner_text()
    flow.fail.add('GET /api/journeys/'+fixture.journey);flow.refresh()
    expect(page.locator('#journey-execution-status')).to_contain_text('上次')
    assert page.locator('#journey-detail-body').inner_text()==before, {'before':before,'after':page.locator('#journey-detail-body').inner_text()}
    flow.fail.clear();flow.refresh();expect(page.locator('[data-journey=refresh-execution]')).to_be_enabled()
    expect(page.locator('#journey-execution-status')).not_to_contain_text('失败')
    passed('503_read_keeps_previous_detail_marks_stale_and_explicit_retry_recovers')
    for path,selector,tag in [('/api/task-publish/state',f'[data-journey-task-status="{local}"]','task'),
                              ('/api/calendar-publish/journeys/'+fixture.journey,'#journey-calendar-publications','calendar')]:
        flow.fail.add('GET '+path);flow.refresh()
        expect(page.locator(selector)).to_contain_text('读取失败')
        expect(page.locator('[data-journey-region=tasks]')).to_be_visible()
        flow.fail.clear();flow.refresh()
        expect(page.locator(selector)).not_to_contain_text('读取失败')
        passed(tag+'_publication_read_failure_is_explicitly_stale_with_local_detail_retained_and_retry')
    uid=fixture.shopping_ids['shared']
    page.locator(f'[data-journey=linked-edit][data-id="{uid}"]').click()
    expect(page.locator('#journey-return-bar')).to_be_visible()
    page.locator('#dialog form [name=note]').fill('从执行页保存的合成备注')
    page.locator('#dialog form [type=submit]').click()
    result=page.locator('[data-journey-region=shopping] .journey-return-result')
    expect(result).to_be_visible()
    expect(page.locator(f'[data-journey=linked-edit][data-id="{uid}"]')).to_be_focused()
    expect(page.locator('[data-journey=refresh-execution]')).to_be_enabled()
    expect(result).to_be_visible()
    notice=result.inner_text()
    other=fixture.shopping_ids['member2'];fixture.update('shopping',other,quantity='2 件')
    expect(page.locator(f'[data-journey-item="{other}"]')).to_contain_text('2 件',timeout=22000)
    expect(result).to_have_text(notice)
    expect(page.locator(f'[data-journey=linked-edit][data-id="{uid}"]')).to_be_focused()
    flow.refresh();expect(page.locator('[data-journey=refresh-execution]')).to_be_enabled()
    expect(result).to_have_text(notice)
    expect(root).to_have_attribute('data-journey-id',fixture.journey)
    assert fixture.item('shopping',uid)['note']=='从执行页保存的合成备注'
    passed('saved_original_purchase_returns_same_region_with_receipt_retained_after_execution_refresh')
    uid=fixture.task_ids['member1'];owner_filter.select_option('mine')
    page.locator(f'[data-journey=linked-edit][data-id="{uid}"]').click()
    expect(page.locator('#journey-return-bar')).to_be_visible()
    page.locator('#dialog form [name=owner]').select_option('shared')
    # First GET loads the saved journey for the return bridge; the second is
    # the new execution panel's initial automatic refresh.
    flow.hold('/api/journeys/'+fixture.journey,occurrence=2)
    page.locator('#dialog form [type=submit]').click();flow.wait_held();flow.release(error=True)
    try:
        expect(owner_filter).to_have_value('mine')
        expect(page.locator('#journey-execution-status')).to_contain_text('读取失败')
        result=page.locator('[data-journey-region=tasks] .journey-return-result')
        expect(result).to_contain_text('当前负责人筛选未显示')
        expect(result).not_to_contain_text('已移除')
        assert fixture.item('tasks',uid)['owner']=='shared'
        expect(page.locator(f'[data-journey-item="{uid}"]')).to_have_count(0)
        owner_filter.select_option('all')
        expect(page.locator(f'[data-journey-item="{uid}"]')).to_be_visible()
        passed('owner_changed_to_shared_and_initial_auto_read_503_reports_filtered_target_not_deleted')
    finally:
        fixture.update('tasks',uid,owner='member1')




def run_races(Flow, fixture, passed, login, auth, child_entry, base):
    detail_path='/api/journeys/'+fixture.journey
    def replace(flow,destination):
        page=flow.page
        if destination=='draft':
            page.evaluate('JourneyUI.create()');expect(page.locator('#journey-form')).to_be_visible()
            page.locator('#journey-core-fields [name=title]').fill('后来草稿 B · 不可覆盖')
            selector='#journey-form'
        elif destination=='other':
            flow.open(fixture.other);selector='#journey-execution'
        elif destination=='editor':
            page.evaluate('(id)=>ShoppingUI.openEditor(id)',fixture.shopping_ids['shared'])
            expect(page.locator('#dialog form')).to_be_visible()
            page.locator('#dialog form [name=title]').fill('后来采购草稿 B · 不可覆盖')
            selector='#dialog form'
        elif destination=='close':
            page.evaluate('closeModal()');expect(page.locator('#dialog')).not_to_be_visible();return None
        else:raise AssertionError(destination)
        page.evaluate('(selector)=>window.executionReplacement=document.querySelector(selector)',selector)
        return selector
    def assert_replacement(flow,destination,selector):
        page=flow.page
        if destination=='close':expect(page.locator('#dialog')).not_to_be_visible();return
        assert page.evaluate('(selector)=>executionReplacement===document.querySelector(selector)',selector)
        if destination=='draft':expect(page.locator('#journey-core-fields [name=title]')).to_have_value('后来草稿 B · 不可覆盖')
        elif destination=='editor':expect(page.locator('#dialog form [name=title]')).to_have_value('后来采购草稿 B · 不可覆盖')
        else:expect(page.locator('#journey-execution')).to_have_attribute('data-journey-id',fixture.other)
        expect(page.locator('#dialog')).not_to_contain_text('SYNTHETIC_LATE_FAILURE')
    for path,tag in [(detail_path,'detail'),('/api/task-publish/state','tasks'),('/api/calendar-publish/journeys/'+fixture.journey,'calendar')]:
        for error in (False,True):
            flow=Flow()
            try:
                flow.open();flow.hold(path);flow.refresh();flow.wait_held()
                selector=replace(flow,'draft');flow.release(error);assert_replacement(flow,'draft',selector)
                passed('late_'+tag+('_503' if error else '_200')+'_does_not_replace_new_journey_draft')
            finally:flow.close()
    for destination in ('other','editor','close'):
        for error in (False,True):
            flow=Flow()
            try:
                flow.open();flow.hold(detail_path);flow.refresh();flow.wait_held()
                selector=replace(flow,destination);flow.release(error);assert_replacement(flow,destination,selector)
                passed('late_detail_'+('503' if error else '200')+'_preserves_'+destination)
            finally:flow.close()
    for identity_change in ('member','household','same_member_new_csrf'):
        for delayed in ('detail','last_me'):
            flow=Flow()
            try:
                flow.open()
                flow.hold(detail_path if delayed=='detail' else '/api/me',occurrence=1 if delayed=='detail' else 2)
                flow.refresh();flow.wait_held()
                if identity_change=='household':
                    response=flow.ctx.request.get(base+child_entry);assert response.status==200
                    login(flow.ctx,1,True)
                else:login(flow.ctx,2 if identity_change=='member' else 1)
                real=flow.ctx.request.get(base+'/api/me').json()
                flow.page.evaluate('boot()')
                assert flow.page.evaluate('user.id')==real['user']['id']
                assert flow.page.evaluate('csrf')==real['csrf']
                selector=replace(flow,'draft');flow.release();assert_replacement(flow,'draft',selector)
                assert flow.ctx.request.get(base+'/api/me').json()['user']['id']==real['user']['id']
                passed('actual_'+identity_change+'_boot_with_old_'+delayed+'_cannot_replace_new_draft')
            finally:flow.close()
    # The existing editor bridge reads /state. Old success or failure must not
    # publish staged state into global data or take a later editor over.
    for destination in ('draft','member','household'):
        for error in (False,True):
            flow=Flow()
            try:
                flow.open();flow.hold('/api/state')
                flow.page.locator(f'[data-journey=linked-edit][data-id="{fixture.shopping_ids["shared"]}"]').click();flow.wait_held()
                if destination!='draft':
                    if destination=='household':
                        assert flow.ctx.request.get(base+child_entry).status==200
                        login(flow.ctx,1,True)
                    else:login(flow.ctx,2)
                    real=flow.ctx.request.get(base+'/api/me').json()
                    flow.page.evaluate('boot()')
                    assert flow.page.evaluate('user.id')==real['user']['id']
                    assert flow.page.evaluate('csrf')==real['csrf']
                selector=replace(flow,'draft')
                flow.page.evaluate('window.executionKeptData=data;window.executionKeptDataJSON=JSON.stringify(data)')
                flow.release(error);assert_replacement(flow,'draft',selector)
                assert flow.page.evaluate('data===executionKeptData && JSON.stringify(data)===executionKeptDataJSON')
                passed('late_linked_edit_state_'+('503' if error else '200')+'_cannot_publish_globals_or_take_'+destination+'_draft')
            finally:flow.close()
    flow=Flow()
    try:
        flow.open();uid=fixture.shopping_ids['shared'];flow.hold('/api/state')
        flow.page.locator(f'[data-journey=linked-edit][data-id="{uid}"]').click();flow.wait_held()
        fixture.update('shopping',uid,title='同成员新版本采购 · 不回退')
        flow.page.evaluate('refresh(true)')
        flow.page.evaluate('window.executionKeptData=data;window.executionKeptDataJSON=JSON.stringify(data)')
        flow.release()
        expect(flow.page.locator('#dialog form [name=title]')).to_have_value('同成员新版本采购 · 不回退')
        assert flow.page.evaluate('data===executionKeptData && JSON.stringify(data)===executionKeptDataJSON')
        passed('same_actor_linked_edit_old_state_cannot_roll_back_already_newer_global_revision')
    finally:flow.close()
    # Cookie-only switch is checked before stale content can be re-used; globals
    # intentionally remain A until the product detects the new server identity.
    for error in (False,True):
        flow=Flow()
        try:
            flow.open();flow.hold(detail_path);flow.refresh();flow.wait_held()
            login(flow.ctx,2)
            assert flow.page.evaluate('user.id')=='member1'
            assert flow.ctx.request.get(base+'/api/me').json()['user']['id']=='member2'
            flow.release(error)
            expect(flow.page.locator('#journey-detail-body')).to_have_count(0)
            expect(flow.page.locator('#dialog')).not_to_contain_text('虚构旅行 A')
            passed('cookie_only_member_change_during_'+('failed' if error else 'successful')+'_read_clears_old_detail')
        finally:flow.close()
    # A real profile password update increments auth_version and replaces the
    # current browser session; no page-global identity is fabricated.
    flow=Flow(number=2)
    changed_password='synthetic-changed-password-two'
    try:
        flow.open();before=flow.ctx.request.get(base+'/api/me').json()['user']['auth_version']
        flow.hold(detail_path);flow.refresh();flow.wait_held()
        response=flow.ctx.request.post(base+'/api/profile',headers=auth(flow.ctx),data={'name':'合成成员二','currentPassword':'testing-password-two','password':changed_password})
        assert response.status==200
        assert flow.ctx.request.get(base+'/api/me').json()['user']['auth_version']==before+1
        flow.release();expect(flow.page.locator('#journey-detail-body')).to_have_count(0)
        expect(flow.page.locator('#dialog')).not_to_contain_text('虚构旅行 A')
        passed('actual_password_auth_version_change_invalidates_inflight_old_detail_without_boot')
    finally:
        response=flow.ctx.request.post(base+'/api/profile',headers=auth(flow.ctx),data={'name':'合成成员二','currentPassword':changed_password,'password':'testing-password-two'})
        assert response.status==200
        flow.close()
    # A PATCH may already have committed. Losing ownership stops UI takeover,
    # never claims that the accepted write was cancelled or retries it.
    for error in (False,True):
        flow=Flow()
        try:
            flow.open();uid=fixture.shopping_ids['member1'];before=fixture.item('shopping',uid)
            path='/api/items/shopping/'+uid;flow.hold(path,method='PATCH')
            flow.page.locator(f'[data-journey=toggle][data-id="{uid}"]').click();flow.wait_held()
            assert fixture.item('shopping',uid)['done'] is not before['done']
            selector=replace(flow,'draft');flow.release(error);assert_replacement(flow,'draft',selector)
            assert flow.calls.count('PATCH '+path)==1
            assert fixture.item('shopping',uid)['revision']==before['revision']+1
            passed('already_committed_toggle_'+('response_lost' if error else 'late_success')+'_does_not_take_over_new_draft_or_retry')
        finally:flow.close()


if __name__=='__main__':
    raise SystemExit(main())
