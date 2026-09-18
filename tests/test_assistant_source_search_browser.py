"""Real Edge source-search acceptance, separate from server-only test selection."""
import json
import time
from pathlib import Path

import pytest

import home_assistant
from test_assistant_source_search import PASSWORD, create_place, env, photo


def test_browser_source_detail_paging_revocation_and_local_preview(env,monkeypatch):
    """Actual Edge + real loopback Flask; only malformed URL response is injected."""
    import threading
    from playwright.sync_api import sync_playwright, expect
    from werkzeug.serving import make_server, WSGIRequestHandler

    env[0].config['HOUSEHOLD_INFO'].update(name='合成家庭',slug='default')
    c,h,p=photo(env,caption='检索照片 <img src=x onerror=window.INJECTED=1>')
    env[0].config.update(ASSISTANT_PROVIDER='openai',OPENAI_API_KEY='synthetic-only',OPENAI_MODEL='synthetic-only')
    monkeypatch.setattr(home_assistant,'model_plan',lambda *_:pytest.fail('Explicit search must stay local'))
    places=[]
    for index in range(21):
        places.append(create_place(c,h,name=f'检索地点{index}',city='城市说明',coordinates={'latitude':31.2345,'longitude':121.4567})[0])
    class Quiet(WSGIRequestHandler):
        def log(self,*args,**kwargs):pass
    server=make_server('127.0.0.1',0,env[0],threaded=True,request_handler=Quiet)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    output=Path(__file__).resolve().parents[1]/'test-results'/'assistant-source-search'/f'browser-{time.time_ns()}'
    output.mkdir(parents=True)
    report={'passed':False,'actualBrowser':'Edge','actualAPI':True,'externalRequests':[],'pageErrors':[],'checks':[]}
    def passed(name):report['checks'].append(name)
    try:
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(channel='msedge',headless=True)
            context=browser.new_context(viewport={'width':390,'height':844})
            def guard(route):
                if not route.request.url.startswith(base+'/'):
                    report['externalRequests'].append(route.request.url);route.abort()
                else:route.continue_()
            context.route('**/*',guard)
            assert context.request.post(base+'/api/login',data={'username':'member1','password':PASSWORD}).status==200
            token=context.request.get(base+'/api/me').json()['csrf']
            page=context.new_page();page.on('pageerror',lambda error:report['pageErrors'].append(str(error)))
            page.goto(base);expect(page.locator('.ps-welcome')).to_be_visible()
            def run_search(text='检索'):
                page.evaluate('HomeAssistant.open()')
                expect(page.locator('#assistant-refresh')).to_be_enabled()
                page.locator('#assistant-form textarea').fill('搜索 '+text)
                page.locator('[name=useModel]').check()
                page.locator('#assistant-form button[type=submit]').click()
                expect(page.locator('#assistant-result')).to_contain_text('当前可见')
                expect(page.locator('#assistant-refresh')).to_be_enabled()
            run_search()
            expect(page.locator('.assistant-search-record')).to_have_count(20)
            page.locator('[data-assistant-action=search-page]').click()
            expect(page.locator('.assistant-search-record')).to_have_count(2)
            passed('local_model_checkbox_search_and_paging')
            run_search('检索照片')
            page.locator('[data-assistant-action=source]').click()
            expect(page.locator('#assistant-source-preview')).to_be_visible()
            page.wait_for_function('document.querySelector("#assistant-source-preview")?.naturalWidth > 0')
            assert page.evaluate('window.INJECTED') is None
            expect(page.locator('#assistant-source-detail')).to_contain_text('<img src=x')
            page.screenshot(path=str(output/'phone-photo.png'))
            page.locator('[data-assistant-action=source-page]').click()
            page.wait_for_url('**/#photos');passed('sanitized_local_photo_and_album_navigation')
            run_search('城市说明')
            page.locator('[data-assistant-action=source]').first.click()
            expect(page.locator('#assistant-source-detail')).to_contain_text('城市说明')
            expect(page.locator('#assistant-source-detail')).not_to_contain_text('31.2345')
            page.locator('[data-assistant-action=source-page]').click()
            page.wait_for_url('**/#map');passed('place_safe_detail_and_map_navigation')
            run_search('检索照片')
            page.locator('[data-assistant-action=source]').click()
            expect(page.locator('#assistant-source-preview')).to_be_visible()
            page.evaluate('window.dispatchEvent(new Event("offline"))')
            expect(page.locator('#assistant-source-preview')).to_have_count(0)
            expect(page.locator('.assistant-search-record')).to_have_count(0)
            passed('offline_clears_preview_and_matches')
            run_search('检索照片')
            page.locator('[data-assistant-action=source]').click()
            expect(page.locator('#assistant-source-preview')).to_be_visible()
            held=[]
            def stall(route):held.append(route)
            context.route('**/api/media/items/'+p['id'],stall)
            expect(page.locator('#assistant-source-preview')).to_have_count(0,timeout=18000)
            expect(page.locator('.assistant-search-record')).to_have_count(0)
            assert held
            for delayed in held:delayed.abort()
            context.unroute('**/api/media/items/'+p['id'],stall)
            passed('stalled_recheck_expires_at_15_seconds')
            run_search('检索照片')
            def malicious(route):
                response=route.fetch();value=response.json();value['item']['previewUrl']='https://invalid.example/private.jpg'
                route.fulfill(response=response,json=value)
            context.route('**/api/media/items/'+p['id'],malicious)
            page.locator('[data-assistant-action=source]').click()
            expect(page.locator('.assistant-desk-error')).to_contain_text('照片预览地址无效')
            expect(page.locator('#assistant-source-preview')).to_have_count(0)
            context.unroute('**/api/media/items/'+p['id'],malicious)
            passed('reject_nonlocal_preview_without_request')
            # Share to the second real member; then revoke between search and detail.
            assert c.patch('/api/media/items/'+p['id'],json={'revision':p['revision'],'visibility':'shared'},headers=h).status_code==200
            assert context.request.post(base+'/api/login',data={'username':'member2','password':PASSWORD}).status==200
            page.goto(base);expect(page.locator('.ps-welcome')).to_be_visible()
            run_search('检索照片')
            assert c.patch('/api/media/items/'+p['id'],json={'revision':p['revision']+1,'visibility':'private'},headers=h).status_code==200
            page.locator('[data-assistant-action=source]').click()
            expect(page.locator('.assistant-search-record')).to_have_count(0)
            expect(page.locator('#assistant-source-detail')).to_have_count(0)
            passed('shared_revocation_clears_search_and_detail')
            assert context.request.post(base+'/api/login',data={'username':'member1','password':PASSWORD}).status==200
            page.goto(base);expect(page.locator('.ps-welcome')).to_be_visible();run_search('检索照片')
            token=context.request.get(base+'/api/me').json()['csrf']
            def logout_during_preview(route):
                response=route.fetch()
                assert context.request.post(base+'/api/logout',data={},headers={'X-CSRF-Token':token}).status==200
                route.fulfill(response=response)
            context.route('**/api/media/items/'+p['id']+'/preview',logout_during_preview)
            page.locator('[data-assistant-action=source]').click()
            expect(page.locator('#assistant-source-preview')).to_have_count(0)
            expect(page.locator('#dialog')).to_contain_text('登录成员或家庭已变化')
            passed('late_preview_discarded_after_real_logout')
            assert not report['externalRequests'] and not report['pageErrors'],report
            report['passed']=True
            context.close();browser.close()
    finally:
        server.shutdown();thread.join(timeout=5)
        (output/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
