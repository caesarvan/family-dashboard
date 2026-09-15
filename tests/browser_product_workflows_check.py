"""End-to-end assistant + finance user flows against an isolated real server with synthetic records."""
from datetime import datetime
import json
from pathlib import Path
import sys
import tempfile
import threading

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app import create_app, TZ
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server, WSGIRequestHandler

class Quiet(WSGIRequestHandler):
    def log(self,*_args,**_kwargs):pass

def main():
    out=ROOT/'test-results';out.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='household-workflow-ui-') as temp:
        app=create_app({'TESTING':True,'SECRET_KEY':'isolated-workflow-test-secret','DATA_DIR':temp,'SESSION_COOKIE_SECURE':False,'MEMBER1_PASSWORD':'testing-password-one','MEMBER2_PASSWORD':'testing-password-two'})
        server=make_server('127.0.0.1',0,app,threaded=True,request_handler=Quiet)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
                ctx=browser.new_context(viewport={'width':1440,'height':1100});page=ctx.new_page();errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                base=f'http://127.0.0.1:{server.server_port}';day=datetime.now(TZ).date().isoformat();month=day[:7]
                page.goto(base);page.locator('[name=password]').fill('testing-password-one');page.locator('#login-form [type=submit]').click();expect(page.locator('.ps-welcome')).to_be_visible()
                csrf=ctx.request.get(base+'/api/me').json()['csrf'];headers={'X-CSRF-Token':csrf}
                before=ctx.request.get(base+'/api/state').json();assert not before['tasks']
                page.evaluate('ProductShell.navigate("assistant")');page.locator('.ps-assistant-prompt').click()
                expect(page.locator('#assistant-form')).to_be_visible()
                page.locator('#assistant-form textarea').fill('待办：明天预约保洁；确认旅行酒店')
                with page.expect_response(lambda r:r.url.endswith('/api/assistant/plan') and r.request.method=='POST') as planned:
                    page.locator('#assistant-form [type=submit]').click()
                plan=planned.value.json();expect(page.locator('[data-plan-index]')).to_have_count(2)
                assert not ctx.request.get(base+'/api/state').json()['tasks'],'planning must not write tasks'
                page.locator('[data-plan-index="1"]').uncheck()
                page.screenshot(path=str(out/'product-assistant-review-desktop.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                assert page.evaluate('document.querySelector("#dialog").scrollWidth<=document.querySelector("#dialog").clientWidth+1')
                page.screenshot(path=str(out/'product-assistant-review-phone.png'),full_page=True)
                page.locator('#assistant-apply').click();expect(page.locator('#assistant-apply')).to_have_text('已创建 1 项')
                expect(page.locator('#assistant-apply')).to_be_disabled()
                after=ctx.request.get(base+'/api/state').json();assert len(after['tasks'])==1,after['tasks']
                assert after['tasks'][0]['title']==plan['actions'][0]['data']['title']
                page.locator('#assistant-apply').evaluate('(button)=>button.click()')
                assert len(ctx.request.get(base+'/api/state').json()['tasks'])==1
                replay=ctx.request.post(base+'/api/assistant/plans/'+plan['id']+'/apply',headers=headers,data={'selected':[0]})
                assert replay.status==200,replay.text();assert len(ctx.request.get(base+'/api/state').json()['tasks'])==1
                page.locator('#dialog [data-action=close]').click()
                page.evaluate('ProductShell.navigate("finance")');page.locator('.ps-page-heading [data-ps-module=FinanceHub]').click()
                expect(page.locator('.fh-workspace')).to_be_visible();page.locator('[data-fh-tab=import]').first.click()
                expect(page.locator('#fh-import-form')).to_be_visible();page.locator('#fh-import-form [name=source]').select_option('generic')
                csv=f'date,title,amount,currency,flow,category,id,status\n{day},PRIVATE_UI_COFFEE,12.34,CNY,expense,餐饮,ui-payment-1,成功\n'
                page.locator('#fh-import-form [type=file]').set_input_files({'name':'synthetic-payments.csv','mimeType':'text/csv','buffer':csv.encode('utf-8')})
                page.locator('#fh-import-form [type=submit]').click()
                expect(page.locator('[data-fh=confirm]')).to_be_enabled();expect(page.locator('.fh-table')).to_contain_text('PRIVATE_UI_COFFEE')
                empty=ctx.request.get(base+'/api/finance-hub/overview?month='+month).json();assert empty['transactionCount']==0
                assert page.evaluate('document.querySelector("#dialog").scrollWidth<=document.querySelector("#dialog").clientWidth+1')
                page.screenshot(path=str(out/'product-finance-preview-phone.png'),full_page=True)
                page.locator('[data-fh=confirm]').click();expect(page.locator('.fh-ledger')).to_contain_text('PRIVATE_UI_COFFEE')
                records=ctx.request.get(base+'/api/finance-hub/overview?month='+month).json()
                assert records['transactionCount']==1 and records['transactions'][0]['amountCents']==1234,records
                assert records['transactions'][0]['visibility']=='private'
                page.locator('[data-fh=transaction]').first.click();expect(page.locator('#fh-editor')).to_be_visible()
                page.locator('#fh-editor [name=category]').fill('生活餐饮');page.locator('#fh-editor [type=submit]').click()
                expect(page.locator('.fh-ledger')).to_contain_text('生活餐饮')
                records=ctx.request.get(base+'/api/finance-hub/overview?month='+month).json()
                assert records['transactions'][0]['checkedAt'] and records['transactions'][0]['category']=='生活餐饮'
                page.locator('[data-fh-tab=investments]').click();page.locator('[data-fh=investment]').first.click()
                expect(page.locator('#fh-editor')).to_be_visible()
                for name,value in {'name':'PRIVATE_UI_FUND','institution':'PRIVATE_UI_BANK','assetType':'基金','currency':'USD','quantity':'12.5','cost':'1000','value':'1200','asOf':day}.items():
                    page.locator('#fh-editor [name='+name+']').fill(value)
                page.locator('#fh-editor [type=submit]').click();expect(page.locator('.fh-ledger')).to_contain_text('PRIVATE_UI_FUND')
                expect(page.locator('.fh-ledger')).to_contain_text('USD 1,200')
                actual=ctx.request.get(base+'/api/finance-hub/overview?month='+month).json()
                assert len(actual['investments'])==1 and actual['investments'][0]['valueCents']==120000,actual
                assert actual['investmentTotals'][0]['unrealizedGainCents']==20000
                page.screenshot(path=str(out/'product-investments-phone.png'),full_page=True)
                page.set_viewport_size({'width':1440,'height':1100});page.screenshot(path=str(out/'product-investments-desktop.png'),full_page=True)
                page.locator('[data-fh-tab=ledger]').click();page.screenshot(path=str(out/'product-ledger-desktop.png'),full_page=True)
                # Fresh second-member session: own empty ledger/investments, no shared detail.
                partner=browser.new_context(viewport={'width':390,'height':844});assert partner.request.post(base+'/api/login',data={'username':'member2','password':'testing-password-two'}).status==200
                private=partner.request.get(base+'/api/finance-hub/overview?month='+month).json();assert not private['transactions'] and not private['investments'],private
                assert 'PRIVATE_UI_' not in partner.request.get(base+'/api/state').text()
                assert 'PRIVATE_UI_' not in partner.request.get(base+'/api/finance-hub/shared?month='+month).text()
                partner_page=partner.new_page();partner_page.on('pageerror',lambda error:errors.append(str(error)));partner_page.goto(base)
                expect(partner_page.locator('.ps-welcome')).to_be_visible();partner_page.evaluate('ProductShell.navigate("finance")');partner_page.locator('.ps-page-heading [data-ps-module=FinanceHub]').click()
                expect(partner_page.locator('.fh-empty')).to_be_visible();expect(partner_page.locator('#dialog')).not_to_contain_text('PRIVATE_UI_')
                # No demo action may create any finance/assistant/journey write.
                demo=browser.new_page();demo.on('pageerror',lambda error:errors.append(str(error)));writes=[]
                demo.on('request',lambda req:writes.append(req.url) if '/api/' in req.url and req.method!='GET' else None)
                demo.goto(base+'/demo');expect(demo.locator('.ps-welcome')).to_be_visible()
                demo.evaluate('ProductShell.navigate("assistant")');demo.locator('.ps-assistant-prompt').click();expect(demo.locator('#dialog')).to_contain_text('演示')
                demo.locator('#dialog [data-action=close]').click();demo.evaluate('ProductShell.navigate("trips")');demo.locator('.ps-page-heading [data-ps-module=JourneyUI]').click();expect(demo.locator('.journey-workspace')).to_be_visible()
                assert not writes,writes;assert not errors,errors
                result={'assistant':{'draftActions':2,'selectedActions':1,'createdTasks':len(after['tasks']),'planningDoesNotWrite':True,'disabledRepeatClick':True,'apiReplayIdempotent':True},'finance':{'previewDoesNotWrite':True,'csvConfirmedRecords':actual['transactionCount'],'amountCents':actual['transactions'][0]['amountCents'],'reconciledCategory':actual['transactions'][0]['category'],'investmentRecords':len(actual['investments']),'investmentValueCents':actual['investments'][0]['valueCents'],'investmentGainCents':actual['investmentTotals'][0]['unrealizedGainCents'],'partnerIsolation':'API and browser passed'},'demoWrites':writes,'browserPageErrors':errors}
                (out/'product-workflows-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
                browser.close()
        finally:
            server.shutdown();server.server_close();thread.join(timeout=5)

if __name__=='__main__':main()
