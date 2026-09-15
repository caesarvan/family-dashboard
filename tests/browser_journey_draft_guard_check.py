"""Guard adjacent travel previews/apply against stale UI ownership using loopback only."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import create_app
from browser_journey_import_guard_check import synthetic_plan, Quiet
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server


def main():
    output=ROOT/'test-results';output.mkdir(exist_ok=True)
    report={'passed':False,'checks':[],'externalRequests':[],'pageErrors':[],
            'configurationBoundary':'No session-refresh configuration override. Requires and asserts reviewed backend default False; joint candidate remains unshipped.'}
    page=None
    def passed(name,**details):report['checks'].append({'name':name,'passed':True,**details})
    with tempfile.TemporaryDirectory(prefix='journey-draft-guard-') as temp:
        app=create_app({'TESTING':True,'DATA_DIR':temp,'SECRET_KEY':'synthetic-draft-guard','SESSION_COOKIE_SECURE':False,
                        'MEMBER1_PASSWORD':'testing-password-one','MEMBER2_PASSWORD':'testing-password-two',
                        'MICROSOFT_CLIENT_ID':'','GOOGLE_CLIENT_ID':'','OPENAI_API_KEY':''})
        assert app.config['SESSION_REFRESH_EACH_REQUEST'] is False, 'Requires reviewed backend session-default patch.'
        server=make_server('127.0.0.1',0,app,threaded=True,request_handler=Quiet)
        threading.Thread(target=server.serve_forever,daemon=True).start();base='http://127.0.0.1:'+str(server.server_port)
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
                ctx=browser.new_context(viewport={'width':390,'height':844})
                def guard(route):
                    if route.request.url.startswith(base+'/'):route.continue_()
                    else:report['externalRequests'].append(route.request.url);route.abort()
                ctx.route('**/*',guard);page=ctx.new_page()
                page.on('pageerror',lambda e:report['pageErrors'].append(str(e)))
                def login(member='member1',password='testing-password-one',reload=True):
                    assert ctx.request.post(base+'/api/login',data={'username':member,'password':password}).status==200
                    if reload:page.goto(base);expect(page.locator('.ps-welcome')).to_be_visible()
                def settle():page.evaluate('new Promise(r=>setTimeout(r,100))');page.wait_for_load_state('networkidle')
                def wait_for(test):
                    for _ in range(100):
                        if test():return
                        page.evaluate('new Promise(r=>setTimeout(r,20))')
                    raise AssertionError('Held request boundary not reached')
                def count():return len(ctx.request.get(base+'/api/journeys').json()['journeys'])
                def new(title='旧旅行草稿A'):
                    if page.locator('#dialog').is_visible():
                        page.locator('#dialog [data-action=close]').click()
                    page.evaluate('JourneyUI.create()');page.locator('#journey-core-fields [name=title]').fill(title)
                    page.locator('.journey-destination [name=city]').fill('虚构城市')
                def review():
                    page.locator('#journey-form [type=submit]').click();expect(page.locator('#journey-review-form')).to_be_visible()
                login()
                token=ctx.request.get(base+'/api/me').json()['csrf']
                plan=ctx.request.post(base+'/api/journeys/preview',data={'plan':synthetic_plan(1)},headers={'X-CSRF-Token':token}).json()
                seeded=ctx.request.post(base+'/api/journeys/apply',data={'previewToken':plan['previewToken'],'idempotencyKey':'synthetic-existing'},headers={'X-CSRF-Token':token}).json()['id']
                def prepare(mode):
                    if mode in ('latest','rebase'):
                        page.evaluate('(id)=>JourneyUI.open(id)',seeded);expect(page.locator('.journey-detail-top')).to_be_visible()
                        page.locator('[data-journey=edit]').click()
                        page.route('**/api/journeys/preview',lambda r:r.fulfill(status=409,json={'error':'合成版本冲突'}))
                        page.locator('#journey-form [type=submit]').click();expect(page.locator('[data-journey=latest-draft]')).to_be_visible()
                        page.unroute('**/api/journeys/preview')
                        if mode=='rebase':
                            page.locator('[data-journey=latest-draft]').click();expect(page.locator('[data-journey=rebase-draft]')).to_be_visible()
                    else:
                        new()
                        if mode in ('repreview','apply'):review()
                    endpoint='/journeys/templates' if mode=='enable' else '/journeys/'+seeded if mode=='latest' else '/journeys/apply' if mode=='apply' else '/journeys/preview'
                    selector={'normal':'#journey-form [type=submit]','repreview':'[data-journey=repreview]','enable':'[data-journey=enable-details]',
                              'latest':'[data-journey=latest-draft]','rebase':'[data-journey=rebase-draft]','apply':'#journey-apply'}[mode]
                    return '**/api'+endpoint,selector
                for mode in ('normal','repreview','enable','latest','rebase'):
                    for outcome,destination in [('success','new'),('error','new'),('success','edit'),('success','close')]:
                        pattern,selector=prepare(mode);before=count();held=[]
                        error_before=page.locator('.journey-error').text_content()
                        page.route(pattern,lambda route:held.append(route));page.locator(selector).click();wait_for(lambda:held)
                        response=held[0].fetch() if outcome=='success' else None
                        edit_selector='#journey-trip-note' if mode!='repreview' else '#journey-checklist [name=title]'
                        if destination=='new':new('后来新建草稿B')
                        elif destination=='edit':page.locator(edit_selector).first.fill('同表单后来编辑B')
                        else:page.locator('#dialog [aria-label=关闭]').click()
                        if response:held[0].fulfill(response=response)
                        else:held[0].fulfill(status=503,json={'error':'旧请求错误不应出现'})
                        page.unroute(pattern);settle()
                        if destination=='close':expect(page.locator('#dialog')).not_to_be_visible()
                        elif destination=='new':
                            expect(page.locator('#journey-core-fields [name=title]')).to_have_value('后来新建草稿B')
                            expect(page.locator('.journey-error')).to_have_text('')
                        else:
                            expect(page.locator(edit_selector).first).to_have_value('同表单后来编辑B')
                            expect(page.locator('.journey-error')).to_have_text(error_before)
                        assert count()==before
                        passed(mode+'_'+outcome+'_after_'+destination)
                page.screenshot(path=str(output/'journey-draft-guard-preserved-mobile.png'))

                # An apply already sent succeeds on the server but cannot take over a new/closed/edited form.
                for outcome,destination in [('success','new'),('error','new'),('success','edit'),('success','close')]:
                    pattern,selector=prepare('apply');before=count();held=[]
                    page.route(pattern,lambda route:held.append(route));page.locator(selector).click();wait_for(lambda:held)
                    response=held[0].fetch() if outcome=='success' else None
                    if destination=='new':new('已发提交后的新草稿B')
                    elif destination=='edit':page.locator('#journey-checklist [name=title]').first.fill('提交后继续编辑B')
                    else:page.locator('#dialog [aria-label=关闭]').click()
                    if response:held[0].fulfill(response=response)
                    else:held[0].fulfill(status=503,json={'error':'旧提交的合成错误'})
                    page.unroute(pattern);settle()
                    if destination=='new':
                        expect(page.locator('#journey-core-fields [name=title]')).to_have_value('已发提交后的新草稿B')
                        expect(page.locator('.journey-error')).to_have_text('')
                    elif destination=='edit':
                        expect(page.locator('#journey-checklist [name=title]').first).to_have_value('提交后继续编辑B')
                        expect(page.locator('#journey-apply')).to_be_disabled()
                    else:expect(page.locator('#dialog')).not_to_be_visible()
                    assert count()==before+(1 if outcome=='success' else 0)
                    passed('sent_apply_'+outcome+'_after_'+destination,serverCreated=outcome=='success')

                # The final open() list read is a separate asynchronous boundary after state readback.
                for outcome,destination in [('success','new'),('error','new'),('success','review'),('error','review')]:
                    prepare('apply');before=count();held=[];sent=[]
                    def record_apply(route):sent.append(route.request.post_data_json);route.continue_()
                    page.route('**/api/journeys/apply',record_apply)
                    page.route('**/api/journeys',lambda route:held.append(route))
                    page.locator('#journey-apply').click();wait_for(lambda:held)
                    response=held[0].fetch() if outcome=='success' else None
                    new('最后打开详情期间的新计划B')
                    if destination=='review':review()
                    if response:held[0].fulfill(response=response)
                    else:held[0].fulfill(status=503,json={'error':'旧详情列表读取的合成错误'})
                    page.unroute('**/api/journeys');settle()
                    if destination=='new':
                        expect(page.locator('#journey-core-fields [name=title]')).to_have_value('最后打开详情期间的新计划B')
                        expect(page.locator('.journey-error')).to_have_text('')
                        assert len(sent)==1 and count()==before+1
                    else:
                        expect(page.locator('.journey-review-hero h3')).to_have_text('最后打开详情期间的新计划B')
                        expect(page.locator('#journey-apply')).to_be_enabled()
                        expect(page.locator('.journey-error')).to_have_text('')
                        page.locator('#journey-apply').click();expect(page.locator('.journey-detail-top')).to_be_visible()
                        assert len(sent)==2 and sent[0]['previewToken']!=sent[1]['previewToken'] and sent[0]['idempotencyKey']!=sent[1]['idempotencyKey']
                        assert count()==before+2
                    page.unroute('**/api/journeys/apply')
                    passed('late_post_apply_open_list_'+outcome+'_preserves_'+destination,applyRequests=len(sent))

                prepare('apply');before=count();held=[];payloads=[]
                page.route('**/api/journeys/apply',lambda route:held.append(route))
                page.locator('#journey-apply').click();wait_for(lambda:held)
                payloads.append(held[0].request.post_data_json);created=held[0].fetch().json()
                held[0].fulfill(status=503,json={'error':'响应丢失的合成错误'});page.unroute('**/api/journeys/apply')
                expect(page.locator('.journey-error')).to_contain_text('响应丢失');expect(page.locator('#journey-apply')).to_be_enabled()
                def retry(route):payloads.append(route.request.post_data_json);route.continue_()
                page.route('**/api/journeys/apply',retry);page.locator('#journey-apply').click()
                expect(page.locator('.journey-detail-top')).to_be_visible();page.unroute('**/api/journeys/apply')
                assert payloads[0]==payloads[1] and count()==before+1
                passed('uncertain_apply_retry_reuses_original_receipt_key_and_entity',journeyId=created['id'])

                prepare('apply');held=[]
                page.route('**/api/state',lambda route:held.append(route))
                page.locator('#journey-apply').click();wait_for(lambda:held)
                responses=[route.fetch() for route in held];new('回读状态期间的新草稿B')
                for route,response in zip(held,responses):route.fulfill(response=response)
                page.unroute('**/api/state');settle()
                expect(page.locator('#journey-core-fields [name=title]')).to_have_value('回读状态期间的新草稿B')
                passed('late_post_apply_state_read_cannot_render_over_new_draft')

                prepare('apply');before=count();writes=[]
                page.on('request',lambda request:writes.append(request.url) if request.url.endswith('/api/journeys/apply') else None)
                login('member2','testing-password-two',reload=False)
                page.locator('#journey-apply').click();expect(page.locator('#dialog')).to_contain_text('登录成员或家庭已变化')
                assert not writes and count()==before
                passed('changed_member_before_apply_prevents_write_in_isolated_session_config')

                login();pattern,selector=prepare('normal');held=[]
                page.route(pattern,lambda route:held.append(route));page.locator(selector).click();wait_for(lambda:held)
                response=held[0].fetch();login(reload=False);held[0].fulfill(response=response);page.unroute(pattern)
                expect(page.locator('#dialog')).to_contain_text('登录成员或家庭已变化')
                passed('rotated_same_member_csrf_drops_old_normal_preview')
                assert not report['externalRequests'] and not report['pageErrors']
                report['passed']=True;browser.close()
        except Exception as error:
            report['failure']=repr(error)
            if page and not page.is_closed():
                try:page.screenshot(path=str(output/'journey-draft-guard-failure.png'))
                except Exception:pass
            raise
        finally:
            server.shutdown()
            report['sourceHashes']={path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in ('app.py','static/journey-ui.js','tests/browser_journey_draft_guard_check.py')}
            (output/'journey-draft-guard-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'failure':report.get('failure')},ensure_ascii=False))


if __name__=='__main__':main()
