"""Synthetic reconciliation async/identity regression; loopback only."""
from contextlib import closing
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app import create_app,TZ
from playwright.sync_api import expect,sync_playwright
from werkzeug.serving import make_server,WSGIRequestHandler

class Quiet(WSGIRequestHandler):
    def log(self,*args,**kwargs):pass

def main():
    out=ROOT/'test-results';out.mkdir(exist_ok=True)
    source_names=['app.py','finance_hub.py','static/app.js','static/finance-hub.js']
    hashes={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in source_names}
    checks=[];details=[];external=[];errors=[];request_counts={};passed=False
    with tempfile.TemporaryDirectory(prefix='finance-reconciliation-guard-') as folder:
        app=create_app({'TESTING':True,'SECRET_KEY':'synthetic-reconciliation-guard-key','DATA_DIR':folder,
            'SESSION_COOKIE_SECURE':False,'MEMBER1_PASSWORD':'testing-password-one','MEMBER2_PASSWORD':'testing-password-two'})
        assert app.config['SESSION_REFRESH_EACH_REQUEST'] is False
        server=make_server('127.0.0.1',0,app,threaded=True,request_handler=Quiet)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        base='http://127.0.0.1:'+str(server.server_port)
        day=datetime.now(TZ).date().isoformat();month=day[:7];database=Path(folder)/'household.sqlite3'
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
                seed=browser.new_context()
                def login(context,member='member1',password=None):
                    response=context.request.post(base+'/api/login',data={'username':member,'password':password or
                        ('testing-password-one' if member=='member1' else 'testing-password-two')})
                    assert response.status==200,response.text()
                login(seed)
                headers={'X-CSRF-Token':seed.request.get(base+'/api/me').json()['csrf']}
                for kind,title in [('orders','SYNTHETIC_A_ORDER'),('payments','SYNTHETIC_A_PAYMENT')]:
                    payload={'source':'generic','kind':kind,'csv':'date,title,amount,currency,flow,id,status\n'+f'{day},{title},100,CNY,expense,{title},成功\n'}
                    preview=seed.request.post(base+'/api/finance-hub/imports/preview',headers=headers,data=payload)
                    assert preview.status==200,preview.text()
                    saved=seed.request.post(base+'/api/finance-hub/imports/confirm',headers=headers,data={**payload,'previewToken':preview.json()['previewToken']})
                    assert saved.status==200,saved.text()
                records=seed.request.get(base+'/api/finance-hub/overview?month='+month).json()['transactions']
                order=next(row for row in records if row['kind']=='orders')
                invitation=seed.request.post(base+'/api/spaces/invitations',headers=headers,data={})
                assert invitation.status==201
                redeemed=seed.request.post(base+'/api/spaces/redeem',headers=headers,data={
                    'name':'Synthetic Second Household','slug':'guard-second',
                    'invitation':invitation.json()['invitation'],
                    'MEMBER1_PASSWORD':'second-home-password-one','MEMBER2_PASSWORD':'second-home-password-two'})
                assert redeemed.status==201,redeemed.text()
                child_entry=redeemed.json()['entry']
                seed.close()
                with closing(sqlite3.connect(database)) as con: raw_before=dict(con.execute('SELECT id,data FROM hub_transactions'))

                def fixture():
                    with closing(sqlite3.connect(database)) as con:
                        con.execute('DELETE FROM hub_reconciliations')
                        con.execute('DELETE FROM attempts')
                        con.commit()

                def relation_state():
                    with closing(sqlite3.connect(database)) as con:
                        return list(con.execute('SELECT status,amount_cents,revision FROM hub_reconciliations'))

                class Flow:
                    def __init__(self):
                        fixture()
                        self.context=browser.new_context(viewport={'width':390,'height':844})
                        login(self.context)
                        self.held=[];self.gate=None;self.requests=[]
                        self.context.route('**/*',self.route)
                        self.page=self.context.new_page()
                        self.page.on('pageerror',lambda error:errors.append(str(error)))
                        self.page.goto(base)
                        expect(self.page.locator('.ps-welcome')).to_be_visible()
                        self.open_order()
                    def route(self,route):
                        request=route.request
                        if not request.url.startswith(base+'/'):
                            external.append({'url':request.url,'method':request.method});route.abort();return
                        path=urlsplit(request.url).path
                        count_key=request.method+' '+path
                        request_counts[count_key]=request_counts.get(count_key,0)+1
                        if path.startswith('/api/finance-hub/reconciliation'):
                            self.requests.append({'method':request.method,'path':path,'body':request.post_data})
                        if self.gate and self.gate(request.method,path):
                            self.gate=None
                            response=route.fetch()
                            assert response.status==200,response.text()
                            assert 'set-cookie' not in response.headers
                            self.held.append((route,response))
                        else:route.continue_()
                    def open_order(self):
                        self.page.evaluate('FinanceHub.open("ledger")')
                        expect(self.page.locator('.fh-transaction')).to_have_count(2)
                        self.page.locator('.fh-transaction').filter(has_text='SYNTHETIC_A_ORDER').locator('[data-fh=transaction]').click()
                        expect(self.page.locator('#fh-editor')).to_be_visible()
                    def read(self):
                        self.page.locator('[data-fh=reconcile]').click()
                        expect(self.page.locator('#fh-match-search')).to_be_visible()
                    def choice(self):
                        self.read()
                        self.page.locator('[data-fh=choose-reconciliation]').first.click()
                        expect(self.page.locator('#fh-reconciliation-form')).to_be_visible()
                    def preview(self):
                        self.choice()
                        self.page.locator('#fh-reconciliation-form [type=submit]').click()
                        expect(self.page.locator('[data-fh=confirm-reconciliation]')).to_be_visible()
                    def setup(self,operation):
                        if operation=='read':return
                        if operation=='preview':self.choice();return
                        self.preview()
                        if operation.startswith('revoke'):
                            self.page.locator('[data-fh=confirm-reconciliation]').click()
                            expect(self.page.locator('[data-fh=revoke-reconciliation]')).to_have_count(1)
                    def arm(self,operation):
                        if operation=='read' or operation.endswith('_readback'):
                            self.gate=lambda method,path:method=='GET' and path=='/api/finance-hub/reconciliation'
                        elif operation=='preview':
                            self.gate=lambda method,path:method=='POST' and path.endswith('/reconciliation/preview')
                        elif operation=='confirm':
                            self.gate=lambda method,path:method=='POST' and path.endswith('/reconciliation/confirm')
                        elif operation=='revoke':
                            self.gate=lambda method,path:method=='POST' and path.endswith('/revoke')
                        else:raise AssertionError(operation)
                    def trigger(self,operation):
                        if operation=='read':self.page.locator('[data-fh=reconcile]').click()
                        elif operation=='preview':self.page.locator('#fh-reconciliation-form [type=submit]').click()
                        elif operation.startswith('confirm'):self.page.locator('[data-fh=confirm-reconciliation]').click()
                        else:
                            self.page.once('dialog',lambda dialog:dialog.accept())
                            self.page.locator('[data-fh=revoke-reconciliation]').click()
                        for _ in range(200):
                            if self.held:break
                            self.page.wait_for_timeout(20)
                        assert len(self.held)==1,operation
                    def release(self,error=False):
                        route,response=self.held.pop()
                        if error:route.fulfill(status=503,content_type='application/json',body=json.dumps({'error':'SYNTHETIC_OLD_FAILURE'}))
                        else:route.fulfill(response=response)
                        self.page.wait_for_timeout(200)
                    def switch(self,kind):
                        if kind=='household':
                            assert self.context.request.get(base+child_entry).status==200
                            login(self.context,'member1','second-home-password-one')
                        else:login(self.context,'member2' if kind=='member' else 'member1')
                        self.page.evaluate('boot()')
                        me=self.context.request.get(base+'/api/me').json()['user']
                        actor=self.page.evaluate('({id:user.id,household:user.householdId})')
                        assert actor['id']==me['id']
                        if kind=='household':assert me['householdId']!='default'
                        elif kind=='member':assert me['id']=='member2'
                    def close(self):
                        for route,response in self.held:route.fulfill(response=response)
                        self.context.close()

                operations=['read','preview','confirm','confirm_readback','revoke','revoke_readback']
                variants=[('new_import',False),('new_import',True),('member',False),('close',False),('return',False)]
                for operation in operations:
                    for transition,error_response in variants:
                        label=f'{operation}:{transition}:{"503" if error_response else "success"}'
                        flow=Flow()
                        try:
                            flow.setup(operation);flow.arm(operation);flow.trigger(operation)
                            page=flow.page
                            if transition=='return':
                                back=page.locator('[data-fh=reconcile]').first if operation in ['preview','confirm','confirm_readback'] else page.locator('[data-fh=back]').first
                                back.click()
                                expected='#fh-match-search' if operation in ['preview','confirm','confirm_readback'] else '.fh-ledger'
                                expect(page.locator(expected)).to_be_visible()
                                page.evaluate('window.guardNewNode=document.querySelector("#dialog .dialog-content")')
                            else:
                                page.locator('#dialog [data-action=close]').click()
                                expect(page.locator('#dialog')).not_to_be_visible()
                                if transition=='member':
                                    flow.switch('member')
                                    page.evaluate('FinanceHub.open("ledger")')
                                    expect(page.locator('.fh-ledger')).to_be_visible()
                                    expect(page.locator('.fh-transaction')).to_have_count(0)
                                if transition!='close':
                                    page.evaluate('FinanceHub.open("import")')
                                    expect(page.locator('#fh-import-form')).to_be_visible()
                                    page.locator('[name=sheet]').fill('KEEP_NEW_DRAFT')
                                    page.evaluate('window.guardNewNode=document.querySelector("#fh-import-form")')
                            before_writes=sum(r['method']=='POST' and (r['path'].endswith('/confirm') or r['path'].endswith('/revoke')) for r in flow.requests)
                            flow.release(error_response)
                            if transition=='close':
                                expect(page.locator('#dialog')).not_to_be_visible()
                            else:
                                assert page.evaluate('window.guardNewNode.isConnected')
                                if transition!='return':
                                    expect(page.locator('#fh-import-form [name=sheet]')).to_have_value('KEEP_NEW_DRAFT')
                                    assert 'SYNTHETIC_A_' not in page.locator('#dialog').inner_text()
                                assert 'SYNTHETIC_OLD_FAILURE' not in page.locator('#dialog').inner_text()
                            after_writes=sum(r['method']=='POST' and (r['path'].endswith('/confirm') or r['path'].endswith('/revoke')) for r in flow.requests)
                            assert before_writes==after_writes
                            states=relation_state()
                            if operation in ['read','preview']:assert states==[]
                            elif operation.startswith('confirm'):assert len(states)==1 and states[0][0]=='active'
                            else:assert len(states)==1 and states[0][0]=='revoked'
                            if transition=='member':
                                assert flow.context.request.get(base+'/api/finance-hub/reconciliation?transactionId='+order['id']).status==404
                            if (operation,transition,error_response) in [('read','member',False),('confirm_readback','new_import',False),('revoke_readback','member',False)]:
                                page.screenshot(path=str(out/('reconciliation-guard-'+operation+'-'+transition+'.png')),full_page=True)
                            checks.append(label)
                            details.append({'case':label,'writesNotCancelled':operation not in ['read','preview'],'noAutomaticResend':True,'retainedNewNode':transition!='close','oldResponseSetCookie':False,'currentMember':page.evaluate('user.id'),'backendForeignRecordStatus':404 if transition=='member' else None})
                        finally:flow.close()

                # The same user with a newly issued CSRF and a real separate household.
                for kind,operation in [('csrf','preview'),('household','read'),('household','confirm_readback')]:
                    flow=Flow()
                    try:
                        flow.setup(operation);flow.arm(operation);flow.trigger(operation)
                        flow.page.locator('#dialog [data-action=close]').click()
                        flow.switch(kind)
                        flow.page.evaluate('FinanceHub.open("import")')
                        expect(flow.page.locator('#fh-import-form')).to_be_visible()
                        flow.page.locator('[name=sheet]').fill('KEEP_CHANGED_ACTOR')
                        flow.page.evaluate('window.guardNewNode=document.querySelector("#fh-import-form")')
                        flow.release()
                        assert flow.page.evaluate('window.guardNewNode.isConnected')
                        assert 'SYNTHETIC_A_' not in flow.page.locator('#dialog').inner_text()
                        checks.append(operation+':real_'+kind+'_switch')
                    finally:flow.close()

                # An unchanged DOM with an edited draft must also invalidate old preview.
                flow=Flow()
                try:
                    flow.setup('preview');flow.arm('preview');flow.trigger('preview')
                    flow.page.locator('#fh-reconciliation-form [name=amount]').fill('80')
                    flow.release()
                    expect(flow.page.locator('#fh-reconciliation-form [name=amount]')).to_have_value('80')
                    expect(flow.page.locator('#fh-reconciliation-form [type=submit]')).to_be_enabled()
                    flow.page.locator('#fh-reconciliation-form [type=submit]').click()
                    expect(flow.page.locator('[data-fh=confirm-reconciliation]')).to_be_visible()
                    flow.page.locator('[data-fh=confirm-reconciliation]').click()
                    expect(flow.page.locator('[data-fh=revoke-reconciliation]')).to_have_count(1)
                    assert relation_state()[0][1]==8000
                    checks.append('preview:same_form_edited_draft_preserved_then_saved80')
                finally:flow.close()

                # New preview B owns its original receipt even when old A returns.
                for failure in [False,True]:
                    flow=Flow()
                    try:
                        flow.setup('preview');flow.arm('preview');flow.trigger('preview')
                        flow.page.locator('[data-fh=reconcile]').click()
                        expect(flow.page.locator('#fh-match-search')).to_be_visible()
                        flow.page.locator('[data-fh=choose-reconciliation]').first.click()
                        expect(flow.page.locator('#fh-reconciliation-form')).to_be_visible()
                        flow.page.locator('[name=amount]').fill('70')
                        flow.page.locator('#fh-reconciliation-form [type=submit]').click()
                        expect(flow.page.locator('[data-fh=confirm-reconciliation]')).to_be_visible()
                        flow.page.evaluate('window.guardNewNode=document.querySelector("#dialog .fh-workspace")')
                        token=flow.page.evaluate('window.guardNewNode._fhReconciliation.preview.previewToken')
                        flow.release(failure)
                        assert flow.page.evaluate('window.guardNewNode.isConnected')
                        assert flow.page.evaluate('window.guardNewNode._fhReconciliation.preview.previewToken')==token
                        flow.page.locator('[data-fh=confirm-reconciliation]').click()
                        expect(flow.page.locator('[data-fh=revoke-reconciliation]')).to_have_count(1)
                        assert relation_state()[0][1]==7000
                        checks.append('preview:two_requests_new_receipt_kept:'+str(failure))
                    finally:flow.close()

                # Confirm/revoke may have completed despite a 503; retry exact receipt.
                for operation in ['confirm','confirm_readback','revoke','revoke_readback']:
                    flow=Flow()
                    try:
                        flow.setup(operation);flow.arm(operation);flow.trigger(operation);flow.release(True)
                        button='[data-fh=confirm-reconciliation]' if operation.startswith('confirm') else '[data-fh=revoke-reconciliation]'
                        expect(flow.page.locator(button)).to_be_enabled()
                        expect(flow.page.locator('#fh-reconciliation-error')).to_contain_text('请求已经发出')
                        posts=[r for r in flow.requests if r['method']=='POST' and r['path'].endswith('/'+('confirm' if operation.startswith('confirm') else 'revoke'))]
                        payload=posts[-1]['body']
                        if operation.startswith('revoke'):flow.page.once('dialog',lambda dialog:dialog.accept())
                        flow.page.locator(button).click()
                        if operation.startswith('confirm'):expect(flow.page.locator('[data-fh=revoke-reconciliation]')).to_have_count(1)
                        else:expect(flow.page.locator('[data-fh=revoke-reconciliation]')).to_have_count(0)
                        retry=[r for r in flow.requests if r['method']=='POST' and r['path'].endswith('/'+('confirm' if operation.startswith('confirm') else 'revoke'))]
                        assert retry[-1]['body']==payload and len(retry)==len(posts)+1
                        assert len(relation_state())==1
                        checks.append(operation+':503_exact_receipt_retry_no_duplicate')
                    finally:flow.close()

                # No new private rendering or writes when identity changes in old dialog.
                for stage in ['choose','confirm','revoke']:
                    flow=Flow()
                    try:
                        if stage=='choose':flow.read()
                        elif stage=='confirm':flow.preview()
                        else:flow.setup('revoke')
                        flow.switch('member')
                        if stage=='choose':button='[data-fh=choose-reconciliation]'
                        elif stage=='confirm':button='[data-fh=confirm-reconciliation]'
                        else:
                            button='[data-fh=revoke-reconciliation]'
                            flow.page.once('dialog',lambda dialog:dialog.accept())
                        before=len([r for r in flow.requests if r['method']=='POST'])
                        flow.page.locator(button).first.click()
                        expect(flow.page.locator('#dialog .error')).to_contain_text('登录成员或家庭已变化')
                        assert 'SYNTHETIC_A_' not in flow.page.locator('#dialog').inner_text()
                        assert len([r for r in flow.requests if r['method']=='POST'])==before
                        checks.append(stage+':boot_changed_actor_same_old_dialog_no_write')
                    finally:flow.close()
                # Old cached model cannot be re-rendered with the new actor's identity.
                for entry in ['tab','transaction','budget']:
                    flow=Flow()
                    try:
                        flow.page.evaluate('FinanceHub.open("overview")' if entry=='budget' else 'FinanceHub.open("ledger")')
                        expect(flow.page.locator('.fh-workspace')).to_be_visible()
                        flow.switch('member')
                        before=len([r for r in flow.requests if r['method']=='POST'])
                        selector='[data-fh-tab=ledger]' if entry=='tab' else '[data-fh=transaction]' if entry=='transaction' else '[data-fh=budget]'
                        flow.page.locator(selector).first.click()
                        expect(flow.page.locator('#dialog .error')).to_contain_text('登录成员或家庭已变化')
                        assert 'SYNTHETIC_A_' not in flow.page.locator('#dialog').inner_text()
                        assert len([r for r in flow.requests if r['method']=='POST'])==before
                        flow.page.locator('[data-fh=back]').click()
                        expect(flow.page.locator('.fh-workspace')).to_be_visible()
                        assert 'SYNTHETIC_A_' not in flow.page.locator('#dialog').inner_text()
                        checks.append(entry+':boot_changed_actor_cached_model_rejected')
                    finally:flow.close()
                # Another tab can change the real cookie while this page's globals stay A.
                for entry in ['tab','transaction','investment','budget']:
                    flow=Flow()
                    try:
                        start='ledger' if entry=='transaction' else 'investments' if entry=='investment' else 'overview'
                        flow.page.evaluate('FinanceHub.open('+json.dumps(start)+')')
                        expect(flow.page.locator('.fh-workspace')).to_be_visible()
                        if entry=='tab':assert 'SYNTHETIC_A_ORDER' not in flow.page.locator('#dialog').inner_text()
                        login(flow.context,'member2')
                        assert flow.context.request.get(base+'/api/me').json()['user']['id']=='member2'
                        assert flow.page.evaluate('user.id')=='member1'
                        before=len([r for r in flow.requests if r['method']=='POST'])
                        selector={'tab':'[data-fh-tab=ledger]','transaction':'[data-fh=transaction]',
                            'investment':'[data-fh=investment]','budget':'[data-fh=budget]'}[entry]
                        flow.page.locator(selector).first.click()
                        expect(flow.page.locator('#dialog .error')).to_contain_text('登录成员或家庭已变化')
                        assert 'SYNTHETIC_A_' not in flow.page.locator('#dialog').inner_text()
                        expect(flow.page.locator('#fh-editor')).to_have_count(0)
                        assert len([r for r in flow.requests if r['method']=='POST'])==before
                        assert flow.context.request.get(base+'/api/finance-hub/reconciliation?transactionId='+order['id']).status==404
                        if entry=='tab':flow.page.screenshot(path=str(out/'reconciliation-guard-cookie-only-neutral.png'),full_page=True)
                        flow.page.evaluate('boot()')
                        flow.page.locator('[data-fh=back]').click()
                        expect(flow.page.locator('.fh-workspace')).to_be_visible()
                        assert 'SYNTHETIC_A_' not in flow.page.locator('#dialog').inner_text()
                        checks.append(entry+':cookie_only_switch_cached_entry_rejected_before_render')
                    finally:flow.close()
                # Cached-entry identity checks cannot take over a newer modal or tab.
                for transition in ['new_import','member','cached_import']:
                    for failure in [False,True]:
                        flow=Flow()
                        try:
                            flow.page.evaluate('FinanceHub.open("overview")')
                            expect(flow.page.locator('[data-fh=budget]')).to_be_visible()
                            flow.gate=lambda method,path:method=='GET' and path=='/api/me'
                            flow.page.locator('[data-fh-tab=ledger]').click()
                            for _ in range(200):
                                if flow.held:break
                                flow.page.wait_for_timeout(20)
                            assert len(flow.held)==1
                            if transition=='cached_import':flow.page.locator('[data-fh-tab=import]').click()
                            else:
                                flow.page.locator('#dialog [data-action=close]').click()
                                if transition=='member':flow.switch('member')
                                flow.page.evaluate('FinanceHub.open("import")')
                            expect(flow.page.locator('#fh-import-form')).to_be_visible()
                            flow.page.locator('[name=sheet]').fill('KEEP_AFTER_CACHED_ENTRY')
                            flow.page.evaluate('window.guardNewNode=document.querySelector("#fh-import-form")')
                            flow.release(failure)
                            assert flow.page.evaluate('window.guardNewNode.isConnected')
                            expect(flow.page.locator('[name=sheet]')).to_have_value('KEEP_AFTER_CACHED_ENTRY')
                            assert 'SYNTHETIC_A_' not in flow.page.locator('#dialog').inner_text()
                            assert 'SYNTHETIC_OLD_FAILURE' not in flow.page.locator('#dialog').inner_text()
                            assert relation_state()==[]
                            checks.append('cached_entry:late_me:'+transition+':'+('503' if failure else 'success'))
                        finally:flow.close()
                # Different pending tab buttons release their own disabled state.
                flow=Flow()
                try:
                    flow.page.evaluate('FinanceHub.open("overview")')
                    expect(flow.page.locator('[data-fh=budget]')).to_be_visible()
                    for target in ['ledger','investments']:
                        flow.gate=lambda method,path:method=='GET' and path=='/api/me'
                        flow.page.locator('[data-fh-tab='+target+']').click()
                        required=1 if target=='ledger' else 2
                        for _ in range(200):
                            if len(flow.held)==required:break
                            flow.page.wait_for_timeout(20)
                        assert len(flow.held)==required
                    flow.release(True)
                    expect(flow.page.locator('[data-fh-tab=investments]')).to_be_enabled()
                    expect(flow.page.locator('#dialog .error')).to_contain_text('SYNTHETIC_OLD_FAILURE')
                    expect(flow.page.locator('[data-fh-tab=ledger]')).to_be_disabled()
                    flow.release()
                    expect(flow.page.locator('[data-fh-tab=ledger]')).to_be_enabled()
                    expect(flow.page.locator('.fh-ledger')).to_have_count(0)
                    flow.page.locator('[data-fh-tab=ledger]').click()
                    expect(flow.page.locator('.fh-transaction')).to_have_count(2)
                    assert relation_state()==[]
                    checks.append('cached_entry:two_different_tabs_new503_both_buttons_retryable')
                finally:flow.close()
                with closing(sqlite3.connect(database)) as con:assert dict(con.execute('SELECT id,data FROM hub_transactions'))==raw_before
                browser.close()
            assert not errors and not external,(errors,external)
            assert hashes=={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in source_names}
            passed=True
        finally:
            server.shutdown();server.server_close();worker.join(timeout=5)
            report={'passed':passed,'checks':checks,'details':details,'externalRequests':external,'pageErrors':errors,
                'sourceHashes':hashes,'requestCounts':request_counts,'realCloudWrites':0,'productionWrites':0,'realPrivateInputs':0,'syntheticSeedTransactions':2,
                'rawTransactionsPreserved':passed,'sessionRefreshOverride':False,
                'scope':'reconciliation original node/actor/receipt guards; other finance cached/editor async flows not comprehensively audited'}
            (out/'finance-reconciliation-guard-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()

