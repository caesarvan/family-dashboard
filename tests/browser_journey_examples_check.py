"""Real local browser downloads of synthetic examples; no external data or accounts."""
import hashlib,json
from pathlib import Path
import sys,tempfile,threading
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app import create_app
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server,WSGIRequestHandler
class Quiet(WSGIRequestHandler):
    def log(self,*_args,**_kwargs):pass


def main():
    output=ROOT/'test-results';output.mkdir(exist_ok=True)
    report={'passed':False,'checks':[],'screenshots':[],'externalRequests':[],'pageErrors':[]}
    def passed(name,**values):report['checks'].append({'name':name,'passed':True,**values})
    with tempfile.TemporaryDirectory(prefix='journey-examples-') as temp:
        app=create_app({'TESTING':True,'DATA_DIR':temp,'SECRET_KEY':'synthetic-examples','SESSION_COOKIE_SECURE':False,
                        'MEMBER1_PASSWORD':'testing-password-one','MEMBER2_PASSWORD':'testing-password-two','MICROSOFT_CLIENT_ID':'','GOOGLE_CLIENT_ID':'','OPENAI_API_KEY':''})
        assert app.config['SESSION_REFRESH_EACH_REQUEST'] is False
        server=make_server('127.0.0.1',0,app,threaded=True,request_handler=Quiet)
        threading.Thread(target=server.serve_forever,daemon=True).start();base='http://127.0.0.1:'+str(server.server_port)
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
                ctx=browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True)
                def guard(route):
                    if route.request.url.startswith(base+'/'):route.continue_()
                    else:report['externalRequests'].append(route.request.url);route.abort()
                ctx.route('**/*',guard)
                assert ctx.request.post(base+'/api/login',data={'username':'member1','password':'testing-password-one'}).status==200
                page=ctx.new_page();page.on('pageerror',lambda error:report['pageErrors'].append(str(error)))
                writes=[];page.on('request',lambda r:writes.append(r.url) if r.method not in ('GET','HEAD') else None)
                page.goto(base);expect(page.locator('.ps-welcome')).to_be_visible()
                def new():
                    page.evaluate('JourneyUI.create()');page.locator('#journey-core-fields [name=title]').fill('应保留的自建草稿')
                    page.locator('.journey-import>summary').click();page.locator('#journey-import-json').fill('保留原粘贴内容')
                def count():return len(ctx.request.get(base+'/api/journeys').json()['journeys'])
                def shot(name):
                    path=output/(name+'.png');page.screenshot(path=str(path));report['screenshots'].append(str(path))
                downloaded={};new();start_writes=len(writes)
                for version in [1,2]:
                    link=page.locator(f'[data-journey-example="{version}"]')
                    with page.expect_download() as waiting:link.click()
                    download=waiting.value
                    assert download.suggested_filename==f'journey-plan-v{version}.json'
                    target=Path(temp)/download.suggested_filename;download.save_as(target);downloaded[version]=target
                    assert target.read_bytes()==(ROOT/f'static/examples/journey-plan-v{version}.json').read_bytes()
                    expect(page.locator('#journey-core-fields [name=title]')).to_have_value('应保留的自建草稿')
                    expect(page.locator('#journey-import-json')).to_have_value('保留原粘贴内容')
                assert len(writes)==start_writes and count()==0
                page.locator('.journey-example-downloads').scroll_into_view_if_needed();shot('journey-examples-desktop')
                passed('desktop_two_real_downloads_match_static_bytes_and_preserve_draft_without_writes')
                page.locator('[data-journey=sample]').click()
                assert json.loads(page.locator('#journey-import-json').input_value())['destinations']
                assert len(writes)==start_writes and count()==0
                passed('existing_fill_example_button_keeps_manual_review_and_creates_nothing')
                for version in [1,2]:
                    new();page.locator('#journey-import-file').set_input_files(str(downloaded[version]))
                    expect(page.locator('#journey-import-json')).to_have_value(downloaded[version].read_text(encoding='utf-8'))
                    page.locator('[data-journey=import]').click()
                    expect(page.locator('#journey-core-fields [name=title]')).to_have_value('虚构示例 · 东京京都巴黎三城旅行')
                    expect(page.locator('#journey-core-fields [name=budget]')).to_have_value('20000')
                    expect(page.locator('#journey-core-fields [name=saved]')).to_have_value('5000')
                    expect(page.locator('#journey-core-fields [name=paid]')).to_have_value('3000')
                    assert page.locator('.journey-destination').count()==3 and count()==0
                    page.locator('#journey-form [type=submit]').click();expect(page.locator('#journey-review-form')).to_be_visible()
                    expect(page.locator('#journey-apply')).to_be_enabled();assert count()==0
                    assert page.locator('#journey-checklist .journey-review-row').count()==3
                    assert page.locator('#journey-purchases .journey-review-row').count()==2
                    if version==2:
                        page.locator('#journey-apply').click();expect(page.locator('.journey-detail-top')).to_be_visible();assert count()==1
                        saved=ctx.request.get(base+'/api/journeys').json()['journeys'][0]
                        assert saved['budget']['purchaseBudget']==8000 and saved['budget']['unknownPurchaseBudgets']==1
                        assert len(saved['events'])==8
                    passed(f'downloaded_v{version}_file_uses_existing_review_and_confirmation_flow',confirmed=version==2)
                page.set_viewport_size({'width':390,'height':844});new()
                link=page.locator('[data-journey-example="2"]');link.focus()
                start_writes=len(writes)
                with page.expect_download() as waiting:page.keyboard.press('Enter')
                assert waiting.value.suggested_filename=='journey-plan-v2.json'
                expect(page.locator('#journey-import-json')).to_have_value('保留原粘贴内容')
                assert len(writes)==start_writes and page.locator('#dialog').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
                page.locator('.journey-example-downloads').scroll_into_view_if_needed();shot('journey-examples-mobile')
                passed('mobile_keyboard_download_preserves_draft_and_has_no_horizontal_overflow')
                page.locator('.journey-import-format>summary').click()
                expect(page.locator('.journey-import-format')).to_contain_text('人民币整数分')
                expect(page.locator('.journey-import-format')).to_contain_text('endDateExclusive')
                expect(page.locator('.journey-import-format')).to_contain_text('Asia/Shanghai')
                assert page.locator('#dialog').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
                page.locator('.journey-import-format').scroll_into_view_if_needed();shot('journey-examples-format-mobile')
                passed('mobile_format_explains_minor_units_inclusive_exclusive_dates_and_zones')
                page.goto(base+'/demo');expect(page.locator('.ps-welcome')).to_be_visible();new()
                before=len(writes)
                with page.expect_download() as waiting:page.locator('[data-journey-example="1"]').click()
                assert waiting.value.suggested_filename=='journey-plan-v1.json'
                assert len(writes)==before
                expect(page.locator('#journey-core-fields [name=title]')).to_have_value('应保留的自建草稿')
                passed('demo_download_is_static_and_has_no_apply_or_private_request')
                tv_context=browser.new_context(viewport={'width':1920,'height':1080});tv_context.route('**/*',guard)
                pair=tv_context.request.post(base+'/api/pair/start',data={}).json()
                token=ctx.request.get(base+'/api/me').json()['csrf']
                assert ctx.request.post(base+'/api/pair/approve',data={'code':pair['code'],'name':'虚构示例电视','focus':'member1'},headers={'X-CSRF-Token':token}).status==200
                assert tv_context.request.post(base+'/api/pair/poll',data={'secret':pair['secret']}).json()['approved']
                tv=tv_context.new_page();tv.goto(base+'/tv');expect(tv.locator('.board')).to_be_visible();tv.evaluate('JourneyUI.create()')
                expect(tv.locator('.journey-import')).to_have_count(0)
                passed('paired_tv_stays_readonly_without_import_controls')
                with app.extensions['cloud_accounts'].db() as con:
                    assert con.execute('SELECT count(*) FROM task_publications').fetchone()[0]==0
                    assert con.execute('SELECT count(*) FROM calendar_publications').fetchone()[0]==0
                assert not report['externalRequests'] and not report['pageErrors']
                report['passed']=True;browser.close()
        except Exception as error:
            report['failure']=repr(error);raise
        finally:
            server.shutdown()
            paths=['app.py','static/journey-ui.js','static/journey-ui.css','static/examples/journey-plan-v1.json','static/examples/journey-plan-v2.json','tests/browser_journey_examples_check.py']
            report['sourceHashes']={path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in paths}
            (output/'journey-examples-browser-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'failure':report.get('failure')},ensure_ascii=False))


if __name__=='__main__':main()
