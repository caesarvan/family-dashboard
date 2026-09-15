"""Real synthetic Flask/SQLite/Edge import receipts and month/identity recovery."""
from collections import Counter
from contextlib import closing
from datetime import datetime
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
from browser_financial_files_check import Quiet
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server


def main():
    out=ROOT/'test-results';out.mkdir(exist_ok=True)
    names=sorted({str(p.relative_to(ROOT)).replace('\\','/') for pattern in ['*.py','static/**/*','requirements*.txt','Dockerfile','docker-compose*.yml'] for p in ROOT.glob(pattern) if p.is_file()}|{'tests/browser_finance_import_navigation_check.py'})
    hashes=lambda:{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}
    report={'passed':False,'checks':[],'sourceHashes':hashes(),'externalRequests':[],'pageErrors':[],
        'providerCalls':0,'productionWrites':0,'realCloudWrites':0,'realPrivateInputs':0,'screenshots':[],
        'requestCounts':{},'scope':'Temporary actual Flask/SQLite/Edge, synthetic CSV only. All browser URLs limited to the local test origin. Confirm responses are historical; readback is current.'}
    passed=lambda name:report['checks'].append({'name':name,'passed':True})
    with tempfile.TemporaryDirectory(prefix='import-navigation-browser-') as folder:
        app=create_app({'TESTING':True,'SECRET_KEY':'synthetic-navigation-browser','DATA_DIR':folder,
            'SESSION_COOKIE_SECURE':False,'MEMBER1_PASSWORD':'testing-password-one','MEMBER2_PASSWORD':'testing-password-two',
            'MICROSOFT_CLIENT_ID':'','GOOGLE_CLIENT_ID':'','OPENAI_API_KEY':''})
        assert app.config['SESSION_REFRESH_EACH_REQUEST'] is False
        server=make_server('127.0.0.1',0,app,threaded=True,request_handler=Quiet)
        threading.Thread(target=server.serve_forever,daemon=True).start();origin='http://127.0.0.1:'+str(server.server_port)
        database=Path(folder)/'household.sqlite3'
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
                def login(ctx,member='member1',child=False):
                    pwd=('second-home-password-one' if member=='member1' else 'second-home-password-two') if child else ('testing-password-one' if member=='member1' else 'testing-password-two')
                    r=ctx.request.post(origin+'/api/login',data={'username':member,'password':pwd});assert r.status==200,r.text()
                seed=browser.new_context();login(seed)
                headers={'X-CSRF-Token':seed.request.get(origin+'/api/me').json()['csrf']}
                invitation=seed.request.post(origin+'/api/spaces/invitations',headers=headers,data={});assert invitation.status==201
                child=seed.request.post(origin+'/api/spaces/redeem',headers=headers,data={'name':'Synthetic Navigation Household','slug':'navigation-child','invitation':invitation.json()['invitation'],
                    'MEMBER1_PASSWORD':'second-home-password-one','MEMBER2_PASSWORD':'second-home-password-two'});assert child.status==201,child.text()
                child_entry=child.json()['entry'];seed.close()

                class Flow:
                    def __init__(self):
                        with closing(sqlite3.connect(database)) as con:
                            con.execute('DELETE FROM hub_transactions');con.execute('DELETE FROM hub_imports');con.execute('DELETE FROM attempts');con.commit()
                        self.ctx=browser.new_context(viewport={'width':360,'height':844});login(self.ctx)
                        self.gate=None;self.held=[];self.counts=Counter()
                        self.ctx.route('**/*',self.route)
                        self.page=self.ctx.new_page();self.page.on('pageerror',lambda e:report['pageErrors'].append(str(e)))
                        self.page.goto(origin);expect(self.page.locator('.ps-welcome')).to_be_visible();self.page.evaluate('()=>clearInterval(pollTimer)')
                    def route(self,route):
                        req=route.request
                        if not req.url.startswith(origin+'/'):
                            report['externalRequests'].append(req.url);route.abort();return
                        key=req.method+' '+urlsplit(req.url).path;self.counts[key]+=1
                        if self.gate and self.gate(req):
                            self.gate=None;self.held.append((route,route.fetch()));return
                        route.continue_()
                    def close(self):
                        assert not self.held
                        for key,n in self.counts.items():report['requestCounts'][key]=report['requestCounts'].get(key,0)+n
                        self.ctx.close()
                    def overview(self,month='2026-08'):
                        r=self.ctx.request.get(origin+'/api/finance-hub/overview?month='+month);assert r.status==200,r.text();return r.json()
                    def write(self,path,body):
                        me=self.ctx.request.get(origin+'/api/me').json()
                        return self.ctx.request.post(origin+path,headers={'X-CSRF-Token':me['csrf']},data=body)
                    def upload_api(self,rows):
                        value={'source':'generic','kind':'payments','csv':self.csv(rows).decode()}
                        preview=self.write('/api/finance-hub/imports/preview',value);assert preview.status==200
                        result=self.write('/api/finance-hub/imports/confirm',{**value,'previewToken':preview.json()['previewToken']});assert result.status==200,result.text();return result.json()
                    def csv(self,rows):
                        return ('date,title,amount,currency,flow,category,id,status\n'+''.join(f'{day},{title},{amount},CNY,expense,Other,{rid},成功\n' for day,title,amount,rid in rows)).encode()
                    def prepare(self,rows):
                        self.page.evaluate('FinanceHub.open("import")');form=self.page.locator('#fh-import-form');expect(form).to_be_visible()
                        form.locator('[name=source]').select_option('generic')
                        form.locator('[name=file]').set_input_files({'name':'synthetic.csv','mimeType':'text/csv','buffer':self.csv(rows)})
                        form.locator('[type=submit]').click();expect(self.page.locator('[data-fh=confirm]')).to_be_enabled()
                    def confirm(self):self.page.locator('[data-fh=confirm]').click()
                    def ledger(self,title=None):
                        expect(self.page.locator('.fh-ledger')).to_be_visible()
                        if title:expect(self.page.locator('.fh-ledger')).to_contain_text(title)
                    def hold(self,suffix):self.gate=lambda req:req.url.split('?')[0].endswith(suffix)
                    def waitheld(self):
                        for _ in range(300):
                            if self.held:return
                            self.page.wait_for_timeout(20)
                        raise AssertionError('Expected held response')
                    def release(self,failed=False):
                        route,response=self.held.pop(0)
                        if failed:route.fulfill(status=503,content_type='application/json',body=json.dumps({'error':'SYNTHETIC_READ_FAILURE'}))
                        else:route.fulfill(response=response)
                        self.page.wait_for_timeout(200)
                    def posts(self):return self.counts['POST /api/finance-hub/imports/confirm']
                    def newdraft(self):
                        self.page.evaluate('FinanceHub.open("import")');form=self.page.locator('#fh-import-form');expect(form).to_be_visible()
                        form.locator('[name=sheet]').fill('NEW_DRAFT_B');return form.element_handle()
                    def switch(self,kind,boot=True):
                        if kind=='household':
                            r=self.ctx.request.get(origin+child_entry);assert r.status==200;login(self.ctx,child=True)
                        else:login(self.ctx,'member2')
                        me=self.ctx.request.get(origin+'/api/me').json()
                        assert me['user']['id']==('member1' if kind=='household' else 'member2')
                        if boot:self.page.evaluate('boot()');self.page.evaluate('()=>clearInterval(pollTimer)')
                    def screenshot(self,name):
                        assert self.page.locator('#dialog').evaluate('(n)=>n.scrollWidth<=n.clientWidth+1')
                        path=out/(name+'.png');self.page.screenshot(path=str(path),full_page=True)
                        report['screenshots'].append({'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})

                old=[('2026-08-02','SYNTHETIC_OLD_MONTH',10,'old')]
                multi=old+[('2026-07-02','SYNTHETIC_JULY',20,'july')]
                f=Flow();f.prepare(old);assert f.overview()['totalRecordCount']==0;passed('preview_is_readonly')
                f.confirm();f.ledger('SYNTHETIC_OLD_MONTH');expect(f.page.locator('#fh-month')).to_have_value('2026-08')
                expect(f.page.locator('[data-fh-import-receipt]')).to_contain_text('新增 1 条');assert f.posts()==1
                passed('first_previous_month_import_opens_actual_month_with_receipt');f.screenshot('finance-import-receipt-360')
                f.page.locator('#fh-month').fill('2026-09');f.page.locator('#fh-month').dispatch_event('change');f.ledger()
                f.page.locator('[data-fh-tab=overview]').click();expect(f.page.locator('.fh-empty')).to_contain_text('账本中已有')
                expect(f.page.locator('.fh-empty')).not_to_contain_text('导入第一份')
                f.page.locator('.fh-empty [data-fh=month]').click();f.ledger('SYNTHETIC_OLD_MONTH');passed('empty_current_month_discovers_existing_month')
                f.close()

                f=Flow();f.prepare(multi);f.confirm();f.ledger('SYNTHETIC_OLD_MONTH')
                expect(f.page.locator('[data-fh-import-receipt] [data-fh=month]')).to_have_count(2)
                f.page.locator('[data-fh-import-receipt] [data-month="2026-07"]').click();f.ledger('SYNTHETIC_JULY');assert f.posts()==1
                passed('cross_month_receipt_buttons_query_actual_month_without_confirm')
                for width,theme in [(768,'light'),(1440,'ocean')]:
                    f.page.set_viewport_size({'width':width,'height':1000});f.page.evaluate('(t)=>document.documentElement.dataset.theme=t',theme)
                    f.screenshot(f'finance-import-receipt-{width}-{theme}')
                f.prepare(multi);f.confirm();f.ledger();expect(f.page.locator('[data-fh-import-receipt]')).to_contain_text('新增 0 条 · 跳过 2 条重复')
                assert f.overview()['totalRecordCount']==2;passed('all_duplicate_import_still_locates_existing_months')
                f.prepare([('2026-06-02','PROPOSED_CONFLICT',99,'old')]);f.confirm();f.ledger('SYNTHETIC_OLD_MONTH')
                expect(f.page.locator('#fh-month')).to_have_value('2026-08');expect(f.page.locator('[data-fh-import-receipt]')).to_contain_text('1 条冲突保留原记录')
                expect(f.page.locator('[data-fh-import-receipt]')).not_to_contain_text('2026-06');passed('conflict_receipt_uses_original_month_and_retains_record');f.close()

                for deleted in [False,True]:
                    f=Flow();f.prepare(old);f.hold('/overview');f.confirm();f.waitheld();assert f.posts()==1
                    if deleted:
                        row=f.overview()['transactions'][0];me=f.ctx.request.get(origin+'/api/me').json()
                        r=f.ctx.request.delete(origin+'/api/finance-hub/transactions/'+row['id'],headers={'X-CSRF-Token':me['csrf']},data={'revision':row['revision']});assert r.status==200
                    f.release(True);expect(f.page.locator('[data-fh=receipt-retry]')).to_be_enabled()
                    expect(f.page.locator('[data-fh-import-receipt]')).to_contain_text('确认已经完成')
                    assert f.posts()==1
                    f.page.locator('[data-fh=receipt-retry]').click();f.ledger()
                    assert f.posts()==1
                    if deleted:
                        expect(f.page.locator('.fh-ledger')).to_contain_text('不会自动重新导入');assert f.overview()['totalRecordCount']==0
                    else:expect(f.page.locator('.fh-ledger')).to_contain_text('SYNTHETIC_OLD_MONTH')
                    passed('successful_confirm_readback_failure_get_only_retry'+('_after_delete_no_resurrection' if deleted else ''));f.close()

                f=Flow();f.prepare(old);f.hold('/imports/confirm');f.confirm();f.waitheld();f.hold('/me');f.release();f.waitheld();f.release(True)
                expect(f.page.locator('[data-fh=receipt-retry]')).to_be_enabled();assert f.posts()==1
                f.page.locator('[data-fh=receipt-retry]').click();f.ledger('SYNTHETIC_OLD_MONTH');assert f.posts()==1
                passed('known_confirm_success_following_me_failure_retains_get_only_retry');f.close()

                f=Flow();f.prepare(old);f.hold('/imports/confirm');f.confirm();f.waitheld();f.release(True)
                expect(f.page.locator('[data-fh=confirm]')).to_be_enabled();f.confirm();f.ledger('SYNTHETIC_OLD_MONTH')
                assert f.posts()==2 and f.overview()['totalRecordCount']==1
                expect(f.page.locator('[data-fh-import-receipt]')).to_contain_text('新增 0 条');passed('unknown_confirm_result_manual_same_payload_retry_is_deduped');f.close()

                # Real responses held after their server work, never substitute a fake business API.
                for phase in ['confirm','readback','month']:
                    for action in ['new','member','household']:
                        for failed in [False,True]:
                            f=Flow();f.prepare(multi)
                            if phase=='month':
                                f.confirm();f.ledger();f.hold('/overview');f.page.locator('[data-fh-import-receipt] [data-month="2026-07"]').click()
                            else:f.hold('/imports/confirm' if phase=='confirm' else '/overview');f.confirm()
                            f.waitheld();before=f.posts()
                            if action!='new':f.switch(action)
                            node=f.newdraft();f.release(failed)
                            assert node.evaluate('(n)=>n.isConnected')
                            expect(f.page.locator('#fh-import-form [name=sheet]')).to_have_value('NEW_DRAFT_B')
                            expect(f.page.locator('[data-fh-import-receipt]')).to_have_count(0)
                            expect(f.page.locator('#dialog')).not_to_contain_text('SYNTHETIC_OLD_MONTH')
                            expect(f.page.locator('#fh-import-form .error')).to_have_text('')
                            assert f.posts()==before
                            passed(f'late_{phase}_{"error" if failed else "success"}_cannot_replace_{action}_draft');f.close()

                for phase in ['confirm','readback']:
                    f=Flow();f.prepare(old);f.hold('/imports/confirm' if phase=='confirm' else '/overview');f.confirm();f.waitheld()
                    f.page.evaluate('document.querySelector("#dialog").close()');f.release()
                    assert not f.page.locator('#dialog').evaluate('(node)=>node.open')
                    assert f.posts()==1 and f.overview()['totalRecordCount']==1
                    passed(f'close_after_{phase}_sent_does_not_reopen_or_cancel_saved_import');f.close()

                # Cookie-only switch leaves globals stale; fresh /me must guard the original receipt.
                for action in ['member','household']:
                    f=Flow();f.prepare(old);f.hold('/overview');f.confirm();f.waitheld();f.switch(action,boot=False);f.release()
                    expect(f.page.locator('#dialog')).to_contain_text('登录成员或家庭已变化')
                    expect(f.page.locator('[data-fh-import-receipt]')).to_have_count(0)
                    assert f.posts()==1 and f.overview()['totalRecordCount']==0
                    passed(f'cookie_only_{action}_change_redacts_old_receipt');f.close()

                f=Flow();f.prepare(multi);f.confirm();f.ledger()
                f.hold('/overview');f.page.locator('[data-fh-import-receipt] [data-month="2026-07"]').click();f.waitheld()
                f.page.locator('[data-fh-import-receipt] [data-month="2026-08"]').click();f.ledger('SYNTHETIC_OLD_MONTH')
                f.release(True);expect(f.page.locator('#fh-month')).to_have_value('2026-08')
                expect(f.page.locator('#dialog')).not_to_contain_text('SYNTHETIC_READ_FAILURE');passed('two_month_requests_latest_wins_and_old_error_is_silent');f.close()

                f=Flow();f.prepare(old);f.hold('/imports/confirm');f.confirm();f.waitheld()
                f.page.locator('[data-fh=confirm]').dispatch_event('click');f.page.wait_for_timeout(100);assert f.posts()==1
                f.release();f.ledger();passed('duplicate_confirm_event_while_inflight_sends_one_write');f.close()

                # A late original identity check cannot mutate an already confirmed new receipt.
                f=Flow();f.prepare(old);f.hold('/overview');f.confirm();f.waitheld()
                f.prepare([('2026-07-03','SYNTHETIC_NEW_RECEIPT',4,'new-receipt')]);f.confirm();f.ledger('SYNTHETIC_NEW_RECEIPT')
                f.release();expect(f.page.locator('#fh-month')).to_have_value('2026-07')
                expect(f.page.locator('[data-fh-import-receipt] [data-month="2026-08"]')).to_have_count(0)
                assert f.posts()==2 and f.overview()['totalRecordCount']==2;passed('late_original_readback_cannot_replace_new_confirmed_receipt');f.close()
                browser.close()
            report['passed']=not report['externalRequests'] and not report['pageErrors']
        except Exception:
            report['failure']=traceback.format_exc();print(report['failure'])
        finally:
            server.shutdown();report['sourceHashesAfter']=hashes();report['sourceUnchanged']=report['sourceHashes']==report['sourceHashesAfter']
            report['passed']=report['passed'] and report['sourceUnchanged'];report['exitCode']=0 if report['passed'] else 1
            (out/'finance-import-navigation-browser-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'sourceUnchanged':report['sourceUnchanged'],'externalRequests':len(report['externalRequests']),'pageErrors':report['pageErrors']},ensure_ascii=False))
    return report['exitCode']


if __name__=='__main__':raise SystemExit(main())
