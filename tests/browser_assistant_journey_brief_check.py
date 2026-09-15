"""Real Edge/Flask travel-brief closure. Synthetic loopback data and fake models only."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import traceback
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app import create_app
import home_assistant
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server, WSGIRequestHandler

PROMPT='''旅行名称：东京京都与巴黎
出发日期：2027-10-01
返程日期：2027-10-12
旅行类型：境外
总预算：2万元
日本/东京 2027-10-01 至 2027-10-04
日本/京都 2027-10-04 至 2027-10-07
法国/巴黎 2027-10-07 至 2027-10-12'''

class Quiet(WSGIRequestHandler):
    def log(self,*_args,**_kwargs): pass

def main():
    out=ROOT/'test-results';out.mkdir(exist_ok=True)
    report={'passed':False,'scope':'Loopback Flask/temporary SQLite/real Edge/fake model; no production or external requests',
            'checks':[],'pageErrors':[],'externalRequests':[],'screenshots':[],'modelCalls':0}
    names=['home_assistant.py','static/home-assistant.js','static/home-assistant.css','static/journey-ui.js']
    report['sourceHashes']={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}
    page=None;browser=None
    def passed(name,**values): report['checks'].append({'name':name,'passed':True,**values})
    with tempfile.TemporaryDirectory(prefix='assistant-journey-browser-') as temp:
        app=create_app({'TESTING':True,'SECRET_KEY':'synthetic-journey-brief-browser','DATA_DIR':temp,'SESSION_COOKIE_SECURE':False,
            'MEMBER1_PASSWORD':'testing-password-one','MEMBER2_PASSWORD':'testing-password-two','OPENAI_API_KEY':'','OPENAI_MODEL':'',
            'MICROSOFT_CLIENT_ID':'','MICROSOFT_CLIENT_SECRET':'','GOOGLE_CLIENT_ID':'','GOOGLE_CLIENT_SECRET':''})
        admin=app.test_client()
        assert admin.post('/api/login',json={'username':'member1','password':'testing-password-one'}).status_code==200
        admin_headers={'X-CSRF-Token':admin.get('/api/me').json['csrf']}
        invite=admin.post('/api/spaces/invitations',json={},headers=admin_headers).json['invitation']
        child=app.test_client().post('/api/spaces/redeem',json={'invitation':invite,'name':'另一个合成家庭','slug':'brief-second-home',
            'MEMBER1_PASSWORD':'second-home-password-one','MEMBER2_PASSWORD':'second-home-password-two'})
        assert child.status_code==201
        second_entry=child.json['entry']
        model_response=home_assistant.local_journey_brief(PROMPT)
        def fake_model(config,prompt):
            report['modelCalls']+=1
            assert config['OPENAI_API_KEY']=='synthetic-key-never-sent'
            return json.loads(json.dumps(model_response))
        home_assistant.model_journey_brief=fake_model
        home_assistant.model_plan=lambda *_: (_ for _ in ()).throw(AssertionError('Travel must not use generic assistant apply'))
        server=make_server('127.0.0.1',0,app,threaded=True,request_handler=Quiet)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        writes=[]
        def counts():
            with closing(sqlite3.connect(Path(temp)/'household.sqlite3')) as con:
                return {t:con.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ['entities','assistant_plans','journey_workflows','journey_actions','calendar_publications','task_publications']}
        try:
            with sync_playwright() as play:
                browser=play.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
                ctx=browser.new_context(viewport={'width':1440,'height':1000})
                def guard(route):
                    if not route.request.url.startswith(base+'/'):
                        report['externalRequests'].append(route.request.url);route.abort()
                    else: route.continue_()
                ctx.route('**/*',guard)
                page=ctx.new_page();page.on('pageerror',lambda err:report['pageErrors'].append(str(err)))
                page.on('request',lambda req:writes.append(urlsplit(req.url).path) if req.method not in ['GET','HEAD'] else None)
                def login(number=1):
                    # Reuse a verified member session between independent UI cases.
                    # Actual identity-switch cases still authenticate the other member;
                    # no rate limiter is disabled or reset by this fixture.
                    current=ctx.request.get(base+'/api/me').json().get('user') or {}
                    if current.get('role')=='member' and current.get('id')==f'member{number}':return
                    result=ctx.request.post(base+'/api/login',data={'username':f'member{number}','password':'testing-password-'+('one' if number==1 else 'two')})
                    assert result.status==200, f'Synthetic login failed: HTTP {result.status}'
                def desk(prompt=PROMPT):
                    login();page.goto(base);page.wait_for_function("() => typeof user !== 'undefined' && user?.role==='member' && !!csrf");page.evaluate('() => HomeAssistant.open()')
                    expect(page.locator('#assistant-form')).to_be_visible()
                    page.locator('#assistant-form [name=prompt]').fill(prompt)
                def begin():
                    page.locator('#assistant-journey').click()
                    expect(page.locator('#assistant-journey-form')).to_be_visible()
                def next_step():
                    page.locator('#assistant-journey-form button[type=submit]').click()
                def step3():
                    next_step();expect(page.locator('.assistant-brief-stop')).to_have_count(3)
                    next_step();expect(page.locator('#assistant-journey-form [name=budgetYuan]')).to_be_visible()
                def enter():
                    page.locator('#assistant-journey-form [name=reviewed]').check();next_step()
                    expect(page.locator('#journey-form')).to_be_visible()
                def screenshot(name):
                    path=out/('assistant-journey-brief-'+name+'.png');page.screenshot(path=str(path));report['screenshots'].append(str(path))
                def hold(pattern):
                    pending=[];page.route(pattern,lambda route:pending.append(route));return pending
                def wait_hold(pending):
                    for _ in range(100):
                        if pending:return pending[0]
                        page.wait_for_timeout(20)
                    raise AssertionError('Expected request did not arrive')

                desk();before=counts();begin()
                expect(page.locator('#assistant-journey-form [name=title]')).to_have_value('东京京都与巴黎')
                step3();expect(page.locator('[name=budgetYuan]')).to_have_value('20000.00')
                screenshot('budget-review');enter()
                expect(page.locator('#journey-form [name=title]')).to_have_value('东京京都与巴黎')
                expect(page.locator('.journey-destination')).to_have_count(3)
                assert counts()==before
                passed('Local multi-country brief carries fields into editable wizard without creating records')
                page.locator('#journey-form button[type=submit]').click();expect(page.locator('#journey-review-form')).to_be_visible()
                assert counts()==before
                page.locator('#journey-apply').click();expect(page.locator('.journey-detail-top')).to_be_visible()
                saved=counts();assert saved['journey_workflows']==saved['journey_actions']==1
                assert saved['assistant_plans']==saved['calendar_publications']==saved['task_publications']==0
                passed('Only explicit existing journey confirmation creates one linked workflow; no cloud queue')
                page.locator('#assistant-return-bar [data-assistant-action=return]').click()
                expect(page.locator('#assistant-form [name=prompt]')).to_have_value(PROMPT)
                passed('Return from saved journey restores original assistant input')

                desk('今年想旅行去日本和法国，12天，两万左右');begin()
                expect(page.locator('[name=start]')).to_have_value('');expect(page.locator('[name=end]')).to_have_value('')
                next_step();expect(page.locator('[name=title]')).to_be_visible()
                page.locator('[name=title]').fill('待补日期的旅行')
                page.locator('[name=start]').fill('2027-10-01');page.locator('[name=end]').fill('2027-10-12')
                page.locator('[name=international]').select_option('true');next_step()
                expect(page.locator('.assistant-brief-stop [name=city]')).to_have_value('')
                page.locator('[data-assistant-brief=return]').click();expect(page.locator('#assistant-form [name=prompt]')).to_have_value('今年想旅行去日本和法国，12天，两万左右')
                page.locator('[data-assistant-action=journey-local]').click();expect(page.locator('.assistant-brief-stop')).to_have_count(1)
                passed('Unknown dates and destinations require input; returning retains partially completed brief')
                for index,(country,city,arrival,departure) in enumerate([('日本','东京','2027-10-01','2027-10-04'),('日本','京都','2027-10-04','2027-10-07'),('法国','巴黎','2027-10-07','2027-10-12')]):
                    if index:
                        page.locator('[data-assistant-brief=add]').click();expect(page.locator('.assistant-brief-stop')).to_have_count(index+1)
                    row=page.locator('.assistant-brief-stop').nth(index)
                    for name,value in [('country',country),('city',city),('arrival',arrival),('departure',departure)]:row.locator('[name='+name+']').fill(value)
                next_step();expect(page.locator('[name=budgetYuan]')).to_have_value('')
                page.locator('[name=budgetYuan]').fill('18500.75');page.locator('[name=memberIds][value=member1]').uncheck();enter()
                expect(page.locator('#journey-form [name=budget]')).to_have_value('18500.75')
                expect(page.locator('#journey-form [name=memberIds]:checked')).to_have_count(1)
                assert counts()==saved
                passed('Plain-language request can be completed manually without JSON/model and exact cents/member choice are carried')

                desk();begin()
                page.locator('#assistant-journey-form [name=title]').fill('手工修改的旧简报')
                page.locator('[data-assistant-brief=return]').click()
                updated_prompt=PROMPT.replace('东京京都与巴黎','另一趟家庭旅行').replace('2万元','32000元')
                page.locator('#assistant-form [name=prompt]').fill(updated_prompt)
                expect(page.locator('#assistant-form button[type=submit]')).to_have_text('按当前文字重新整理')
                previous_briefs=writes.count('/api/assistant/journey-brief')
                page.locator('#assistant-form button[type=submit]').click()
                expect(page.locator('#assistant-journey-form [name=title]')).to_have_value('另一趟家庭旅行')
                step3();expect(page.locator('[name=budgetYuan]')).to_have_value('32000.00')
                assert writes.count('/api/assistant/journey-brief')==previous_briefs+1 and counts()==saved
                passed('Changed input explicitly regenerates a new brief and budget instead of reusing the old editable brief')

                desk();begin()
                page.locator('#assistant-journey-form [name=title]').fill('失败时保留的手工简报')
                page.locator('[data-assistant-brief=return]').click()
                page.locator('#assistant-form [name=prompt]').fill(updated_prompt)
                pending=hold('**/api/assistant/journey-brief')
                page.locator('#assistant-form button[type=submit]').click();held=wait_hold(pending)
                held.fulfill(status=503,json={'error':'synthetic regeneration unavailable'});page.unroute('**/api/assistant/journey-brief')
                expect(page.locator('#assistant-form .error')).to_contain_text('synthetic regeneration unavailable')
                expect(page.locator('#assistant-form [name=prompt]')).to_have_value(updated_prompt)
                previous_briefs=writes.count('/api/assistant/journey-brief')
                page.locator('[data-assistant-action=journey-local]').click()
                expect(page.locator('#assistant-journey-form [name=title]')).to_have_value('失败时保留的手工简报')
                assert writes.count('/api/assistant/journey-brief')==previous_briefs and counts()==saved
                passed('Failed regeneration preserves edited old brief and new input; explicit resume sends no new brief/model request')

                for command in ['  待办：确认旅行酒店','采购：旅行转换插头','搜索：旅行']:
                    desk();page.evaluate('() => HomeAssistant.openJourney()')
                    expect(page.locator('#assistant-form button[type=submit]')).to_have_text('整理旅行简报')
                    page.locator('#assistant-form [name=prompt]').fill(command)
                    expect(page.locator('#assistant-form button[type=submit]')).to_have_text('生成可审阅方案')
                    previous_briefs=writes.count('/api/assistant/journey-brief');previous_plans=writes.count('/api/assistant/plan')
                    page.locator('#assistant-form button[type=submit]').click()
                    expect(page.locator('#assistant-result .assistant-answer')).to_be_visible()
                    assert writes.count('/api/assistant/journey-brief')==previous_briefs
                    assert writes.count('/api/assistant/plan')==previous_plans+1
                    assert page.locator('#assistant-journey-form').count()==0
                    after=counts()
                    assert {key:value for key,value in after.items() if key!='assistant_plans'}=={key:value for key,value in saved.items() if key!='assistant_plans'}
                    saved=after
                    passed('Explicit list/search command overrides travel entry without creating business records: '+command.strip().split('：')[0])

                app.config.update(OPENAI_API_KEY='synthetic-key-never-sent',OPENAI_MODEL='fake-model')
                model_response.update(owner='member2',previewToken='FORBIDDEN',remoteId='FORBIDDEN',publish=True)
                model_response['title']='东京京都与巴黎 <img src=x onerror=window.__briefInjection=1>'
                model_response['destinations'][0]['owner']='member2'
                desk(PROMPT);page.locator('#assistant-form [name=useModel]').check()
                page.locator('#assistant-form button[type=submit]').click();expect(page.locator('#assistant-journey-form')).to_be_visible()
                expect(page.locator('.assistant-brief-header')).to_contain_text('AI 整理')
                step3();enter()
                assert report['modelCalls']==1 and 'FORBIDDEN' not in page.locator('#dialog').inner_text()
                assert page.evaluate('() => !!window.__briefInjection') is False
                assert counts()==saved
                passed('Explicit fake model request enters travel brief and drops unauthorized fields')

                desk('请规划一次虚构旅行');page.locator('#assistant-form [name=useModel]').check()
                app.config.update(OPENAI_API_KEY='',OPENAI_MODEL='')
                page.locator('#assistant-journey').click()
                expect(page.locator('#assistant-form .error')).to_contain_text('AI 模型尚未配置')
                expect(page.locator('#assistant-form [name=prompt]')).to_have_value('请规划一次虚构旅行')
                calls_before=report['modelCalls'];page.locator('[data-assistant-action=journey-local]').click()
                expect(page.locator('#assistant-journey-form')).to_be_visible()
                assert report['modelCalls']==calls_before
                passed('Unavailable model retains original text and explicit local fallback opens editable steps')

                app.config.update(OPENAI_API_KEY='',OPENAI_MODEL='')
                desk();pending=hold('**/api/assistant/journey-brief');page.locator('#assistant-journey').click();held=wait_hold(pending);response=held.fetch()
                page.locator('#assistant-form [name=prompt]').fill('后来输入的旅行需求，必须保留')
                held.fulfill(response=response);page.unroute('**/api/assistant/journey-brief');page.wait_for_timeout(250)
                expect(page.locator('#assistant-form [name=prompt]')).to_have_value('后来输入的旅行需求，必须保留')
                assert page.locator('#assistant-journey-form').count()==0
                passed('Late brief success cannot replace newer input in the same form')

                desk();pending=hold('**/api/assistant/journey-brief');page.locator('#assistant-journey').click();held=wait_hold(pending)
                page.evaluate('() => JourneyUI.create()');page.locator('#journey-form [name=title]').fill('另一份手工旅行草稿')
                held.fulfill(status=503,json={'error':'synthetic unavailable'});page.unroute('**/api/assistant/journey-brief');page.wait_for_timeout(200)
                expect(page.locator('#journey-form [name=title]')).to_have_value('另一份手工旅行草稿')
                assert 'synthetic unavailable' not in page.locator('#dialog').inner_text()
                passed('Late brief error cannot overwrite a newly opened journey editor')

                desk();begin();step3();page.locator('[name=reviewed]').check()
                pending=hold('**/api/journeys/preview');next_step();held=wait_hold(pending)
                held.fulfill(status=503,json={'error':'synthetic preview unavailable'});page.unroute('**/api/journeys/preview')
                expect(page.locator('#assistant-journey-form .error')).to_contain_text('synthetic preview unavailable')
                expect(page.locator('[name=budgetYuan]')).to_have_value('20000.00')
                assert counts()==saved
                passed('503 bridge preview retains budget, review form and input with no entity writes')

                pending=hold('**/api/journeys/preview');next_step();held=wait_hold(pending);response=held.fetch()
                page.locator('[name=note]').fill('请求期间补充的备注')
                held.fulfill(response=response);page.unroute('**/api/journeys/preview');page.wait_for_timeout(200)
                expect(page.locator('#assistant-journey-form [name=note]')).to_have_value('请求期间补充的备注')
                assert page.locator('#journey-form').count()==0
                passed('Late bridge preview cannot discard edits made while preview is pending')

                desk();begin();step3();page.locator('[name=reviewed]').check()
                pending=hold('**/api/journeys/preview');next_step();held=wait_hold(pending)
                page.evaluate('() => JourneyUI.create()');page.locator('#journey-form [name=title]').fill('不能被旧桥接错误替换')
                held.fulfill(status=409,json={'error':'OLD_BRIDGE_CONFLICT'});page.unroute('**/api/journeys/preview');page.wait_for_timeout(200)
                expect(page.locator('#journey-form [name=title]')).to_have_value('不能被旧桥接错误替换')
                assert 'OLD_BRIDGE_CONFLICT' not in page.locator('#dialog').inner_text()
                passed('Late bridge failure cannot overwrite a newer manual journey draft')

                desk();begin();step3();page.locator('[name=reviewed]').check()
                pending=hold('**/api/journeys/preview');next_step();held=wait_hold(pending);response=held.fetch()
                login(2)
                held.fulfill(response=response);page.unroute('**/api/journeys/preview')
                expect(page.locator('#dialog')).to_contain_text('请重新进入家庭助理')
                assert page.locator('#assistant-journey-form,#journey-form').count()==0
                assert '东京京都与巴黎' not in page.locator('#dialog').inner_text()
                passed('Changed server member during bridge preview clears stale private draft before handoff')

                desk();pending=hold('**/api/assistant/journey-brief');page.locator('#assistant-journey').click();held=wait_hold(pending);response=held.fetch()
                login(2);held.fulfill(response=response);page.unroute('**/api/assistant/journey-brief')
                expect(page.locator('#dialog')).to_contain_text('请重新进入家庭助理')
                assert page.locator('#assistant-journey-form').count()==0
                passed('Changed member during brief generation cannot render old input or result')

                desk();begin();login(2);next_step()
                expect(page.locator('#dialog')).to_contain_text('请重新进入家庭助理')
                assert page.locator('.assistant-brief-stop').count()==0
                passed('Ordinary next-step navigation also rechecks the server member before rendering cached brief')

                desk();begin();step3();page.locator('[name=reviewed]').check()
                pending=hold('**/api/journeys/preview');next_step();held=wait_hold(pending);response=held.fetch()
                ctx.request.get(base+second_entry)
                assert ctx.request.post(base+'/api/login',data={'username':'member1','password':'second-home-password-one'}).status==200
                assert ctx.request.get(base+'/api/me').json()['user']['householdId']!='home'
                held.fulfill(response=response);page.unroute('**/api/journeys/preview')
                expect(page.locator('#dialog')).to_contain_text('请重新进入家庭助理')
                assert page.locator('#assistant-journey-form,#journey-form').count()==0
                ctx.request.get(base+'/space/home')
                passed('Real household switch with the same member ID cannot adopt the previous household brief')

                desk();page.evaluate('() => JourneyUI.create()');page.locator('#journey-form [name=title]').fill('保留这个已打开的草稿')
                message=page.evaluate('async () => {try{await JourneyUI.openDraft({});return "BAD"}catch(e){return e.message}}')
                assert '已有旅行草稿' in message
                expect(page.locator('#journey-form [name=title]')).to_have_value('保留这个已打开的草稿')
                passed('Direct bridge rejects an already open journey editing form')

                desk();page.evaluate('() => JourneyUI.open()');page.locator('[data-journey=assistant-brief]').click()
                expect(page.locator('#assistant-form button[type=submit]')).to_have_text('整理旅行简报')
                page.locator('#assistant-form [name=prompt]').fill('想去日本和法国，具体时间待定')
                page.locator('#assistant-form button[type=submit]').click();expect(page.locator('#assistant-journey-form')).to_be_visible()
                passed('Travel workspace opens an explicit text-planning assistant without requiring intent keywords')

                desk();page.evaluate('() => JourneyUI.open()');pending=[]
                page.route('**/api/assistant/brief',lambda route:pending.append(route) if not pending else route.continue_())
                page.locator('[data-journey=assistant-brief]').click();held=wait_hold(pending);response=held.fetch()
                page.evaluate('() => HomeAssistant.open()')
                expect(page.locator('#assistant-form button[type=submit]')).to_have_text('生成可审阅方案')
                held.fulfill(response=response);page.unroute('**/api/assistant/brief');page.wait_for_timeout(200)
                expect(page.locator('#assistant-form button[type=submit]')).to_have_text('生成可审阅方案')
                passed('Late travel-entry open cannot change the intent of a newer assistant page')

                desk();begin();page.set_viewport_size({'width':390,'height':844});screenshot('phone')
                assert page.evaluate('document.querySelector("#dialog").scrollWidth <= document.querySelector("#dialog").clientWidth+2')
                page.goto(base+'/demo');page.wait_for_function("() => typeof isDemo !== 'undefined' && isDemo");page.evaluate('() => HomeAssistant.open()');expect(page.locator('#assistant-demo')).to_be_visible()
                assert page.locator('#assistant-journey-form').count()==0
                passed('390px layout remains usable and demo never opens a live brief')
                assert not report['externalRequests'] and not report['pageErrors']
                assert counts()==saved
                report['passed']=True
        except Exception as error:
            report['error']=str(error)
            report['errorType']=type(error).__name__
            report['traceback']=traceback.format_exc()
            if page and not page.is_closed():
                try: screenshot('failure')
                except Exception: pass
        finally:
            if browser:
                try: browser.close()
                except Exception: pass
            server.shutdown();thread.join(timeout=5)
            report['sourceUnchanged']=all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in report['sourceHashes'].items())
            report['businessWrites']=writes
            (out/'assistant-journey-brief-browser-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
            print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'error':report.get('error'),'report':str(out/'assistant-journey-brief-browser-verification.json')},ensure_ascii=False))
    return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
