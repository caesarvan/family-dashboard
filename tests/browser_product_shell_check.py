"""Real isolated Flask browser checks for the responsive product shell. No production reads/writes."""
import json
from pathlib import Path
import sys
import tempfile
import threading

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app import create_app
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server, WSGIRequestHandler

class Quiet(WSGIRequestHandler):
    def log(self,*_args,**_kwargs):
        pass

def main():
    out=ROOT/'test-results';out.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='household-product-ui-') as temp:
        app=create_app({'TESTING':True,'SECRET_KEY':'isolated-product-shell-test-key','DATA_DIR':temp,'SESSION_COOKIE_SECURE':False,'MEMBER1_PASSWORD':'testing-password-one','MEMBER2_PASSWORD':'testing-password-two'})
        server=make_server('127.0.0.1',0,app,threaded=True,request_handler=Quiet)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        records=[];errors=[]
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
                base=f'http://127.0.0.1:{server.server_port}'
                ctx=browser.new_context(viewport={'width':1440,'height':1100})
                page=ctx.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(base+'/demo');expect(page.locator('.ps-welcome')).to_be_visible()
                for name,width,height in [('desktop',1440,1100),('desktop-wide',1920,1080),('tablet',820,1180),('phone',390,844),('phone-small',360,800)]:
                    page.set_viewport_size({'width':width,'height':height})
                    page.evaluate('ProductShell.navigate("home")')
                    for route in ['home','calendar','tasks','shopping','trips','finance','assistant','connections','settings','household']:
                        page.evaluate('(route)=>ProductShell.navigate(route)',route)
                        expect(page.locator(f'[data-ps-page="{route}"]')).to_be_visible()
                        metrics=page.evaluate('''() => ({width:innerWidth,scroll:document.documentElement.scrollWidth,headings:[...document.querySelectorAll('.ps-page h1')].map(e=>e.textContent)})''')
                        assert metrics['scroll']<=width+1,(name,route,metrics)
                        records.append({'viewport':name,'route':route,'horizontalOverflow':False})
                        if name in ['desktop','phone'] and route in ['home','assistant','trips','connections']:
                            page.screenshot(path=str(out/f'product-{name}-{route}.png'),full_page=True)
                            if route=='home':page.screenshot(path=str(out/f'product-{name}-first-screen.png'))
                page.evaluate('ProductShell.navigate("shopping")');page.evaluate('ProductShell.navigate("trips")')
                page.go_back();expect(page.locator('[data-ps-page=shopping]')).to_be_visible()
                page.reload();expect(page.locator('[data-ps-page=shopping]')).to_be_visible()
                # Three themes use the same real card DOM. Settings persist locally in demo.
                page.set_viewport_size({'width':1440,'height':1100});page.evaluate('ProductShell.navigate("home")')
                for theme in ['light','ocean','forest']:
                    page.evaluate('ProductShell.openPreferences()')
                    page.locator(f'[name=theme][value={theme}]').check()
                    page.locator('[name=density]').select_option('compact' if theme=='ocean' else 'comfortable')
                    page.locator('#ps-preferences-form button[type=submit]').click()
                    expect(page.locator('html')).to_have_attribute('data-theme',theme)
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                    page.screenshot(path=str(out/f'product-theme-{theme}.png'),full_page=True)
                page.evaluate('ProductShell.openSearch()');page.locator('#ps-search-input').fill('咖啡')
                expect(page.locator('.ps-search-result')).to_have_count(1)
                page.locator('.ps-search-result').click();expect(page.locator('[data-ps-page=shopping]')).to_be_visible()
                page.locator('[data-ps-list-search]').fill('厨房');expect(page.locator('.ps-full-list .list-row')).to_have_count(1)
                page.locator('[data-ps-filter=done]').click();expect(page.locator('.ps-empty-state')).to_be_visible()
                # Mobile menu, actual controls and close behavior.
                page.set_viewport_size({'width':390,'height':844});page.locator('[data-ps-more]').click()
                expect(page.locator('.ps-mobile-menu')).to_be_visible();page.locator('.ps-mobile-menu [data-ps-route=trips]').click()
                expect(page.locator('[data-ps-page=trips]')).to_be_visible();expect(page.locator('.ps-mobile-menu')).to_have_count(0)
                # TV keeps five existing cards, independent of appearance preference writes.
                tv=browser.new_page();tv.on('pageerror',lambda error:errors.append(str(error)))
                pref_requests=[];tv.on('request',lambda req:pref_requests.append(req.url) if '/api/preferences' in req.url else None)
                for width,height in [(1280,720),(1920,1080),(3840,2160)]:
                    tv.set_viewport_size({'width':width,'height':height});tv.goto(base+'/demo?tv=1')
                    expect(tv.locator('.board>.card')).to_have_count(5)
                    for mode in ['today','week','around']:
                        tv.locator(f'[data-calendar-mode={mode}]').first.click()
                        m=tv.evaluate('''() => ({w:document.documentElement.scrollWidth,h:document.documentElement.scrollHeight,cards:[...document.querySelectorAll('.board>.card')].map(e=>({bottom:e.getBoundingClientRect().bottom,overflow:e.scrollHeight-e.clientHeight}))})''')
                        assert m['w']<=width+1 and m['h']<=height+1,(width,height,mode,m)
                        assert all(c['bottom']<=height+1 and c['overflow']<=2 for c in m['cards']),(width,height,mode,m)
                        records.append({'viewport':f'tv-{width}','mode':mode,'layout':'passed'})
                        if width==1920 and mode=='week':tv.screenshot(path=str(out/'product-tv.png'))
                assert not pref_requests,pref_requests
                # Actual login, task create/completion, settings persisted by backend and a fresh browser.
                page.set_viewport_size({'width':1440,'height':1100});page.goto(base)
                expect(page.locator('[data-household-redeem]')).to_be_visible()
                page.screenshot(path=str(out/'product-login.png'),full_page=True)
                page.locator('[name=password]').fill('testing-password-one');page.locator('#login-form [type=submit]').click()
                expect(page.locator('.ps-welcome')).to_be_visible()
                page.evaluate('ProductShell.navigate("tasks")');page.locator('[data-action=add][data-kind=tasks]').click()
                page.locator('[name=title]').fill('一起订周末晚餐');page.locator('#dialog [type=submit]').click()
                expect(page.locator('.ps-full-list .list-row')).to_have_count(1)
                page.locator('.ps-full-list [data-action=toggle]').click();expect(page.locator('.ps-full-list .list-row')).to_have_count(0)
                page.locator('[data-ps-filter=done]').click();expect(page.locator('.ps-full-list .list-row')).to_have_count(1)
                page.evaluate('ProductShell.openPreferences()');page.locator('[name=theme][value=light]').check()
                page.locator('[name=density]').select_option('compact');page.locator('[name=homeView]').select_option('week')
                page.locator('#ps-preferences-form [type=submit]').click();expect(page.locator('#dialog')).not_to_be_visible()
                actual=ctx.request.get(base+'/api/preferences').json();actual=actual.get('preferences',actual)
                assert actual['theme']=='light' and actual['density']=='compact' and actual['homeView']=='week',actual
                second=browser.new_context(viewport={'width':390,'height':844});second.request.post(base+'/api/login',data={'username':'member1','password':'testing-password-one'})
                mobile=second.new_page();mobile.on('pageerror',lambda error:errors.append(str(error)));mobile.goto(base)
                expect(mobile.locator('html')).to_have_attribute('data-theme','light')
                expect(mobile.locator('[data-calendar-mode=week]')).to_have_attribute('aria-pressed','true')
                # Failed persistence keeps settings form and draft, without a false success state.
                mobile.route('**/api/preferences',lambda route:route.fulfill(status=503,content_type='application/json',body='{"error":"同步暂不可用"}') if route.request.method=='PUT' else route.continue_())
                mobile.evaluate('ProductShell.openPreferences()');mobile.locator('[name=theme][value=ocean]').check();mobile.locator('#ps-preferences-form [type=submit]').click()
                expect(mobile.locator('#ps-preferences-form .error')).to_contain_text('同步暂不可用')
                expect(mobile.locator('#dialog')).to_be_visible();expect(mobile.locator('[name=theme][value=ocean]')).to_be_checked()
                # Shared name is always escaped, even if modified in a hostile fixture.
                page.evaluate('''() => {data.people[1].name='<img src=x onerror="window.BAD_NAME=true">';renderBoard()}''')
                assert not page.evaluate('Boolean(window.BAD_NAME)')
                assert not errors,errors
                result={'routes':records,'themes':['forest','light','ocean'],'backendPreferences':'saved and read in fresh browser','failureDraft':'preserved','realTaskCreateComplete':'passed','search':'passed','tvPreferenceRequests':len(pref_requests),'pageErrors':errors}
                (out/'product-shell-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps(result,ensure_ascii=False))
                browser.close()
        finally:
            server.shutdown();server.server_close();thread.join(timeout=5)

if __name__=='__main__':main()
