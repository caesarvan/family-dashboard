"""Focused personal-ledger UI on synthetic Flask/SQLite and local Edge.

contract injects only the new GET page response; imports, edits, deletes,
reconciliation, shopping return and authentication use the unchanged real API.
api uses the integrated GET implementation without injecting a route.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app import create_app
import finance_hub
from flask import g, jsonify, request
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server, WSGIRequestHandler

class Quiet(WSGIRequestHandler):
    def log(self,*args,**kwargs): pass


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=['contract','api'],default='contract')
    mode=parser.parse_args().mode
    out=ROOT/'test-results';out.mkdir(exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target=out/f'finance-ledger-{mode}-{stamp}.json'
    names=set(subprocess.check_output(['git','-C',str(ROOT),'ls-files','-z']).decode().split('\0'))-{''}
    names.add(Path(__file__).relative_to(ROOT).as_posix())
    hashes=lambda:{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in sorted(names)}
    report={'passed':False,'mode':mode,'checks':[],'sourceHashesBefore':hashes(),'pageErrors':[],
        'externalRequests':[],'providerCalls':0,'productionWrites':0,'realCloudWrites':0,'realPrivateInputs':0,
        'scope':'Synthetic Flask/SQLite/local Edge. Contract mode injects only GET transactions; api mode is unmodified integrated backend.',
        'ledgerRequests':[],'writes':[],'screenshots':[]}
    def passed(name):report['checks'].append({'name':name,'passed':True});print('PASS '+name,flush=True)
    def deny(*args,**kwargs):report['providerCalls']+=1;raise AssertionError('No provider access')
    original_connect=socket.socket.connect
    def connect(sock,address):
        if isinstance(address,tuple) and address[0] not in ('127.0.0.1','::1','localhost'):
            report['externalRequests'].append(str(address));raise AssertionError('External socket forbidden')
        return original_connect(sock,address)
    with patch.object(socket.socket,'connect',connect),tempfile.TemporaryDirectory(prefix='finance-ledger-') as folder:
        app=create_app({'TESTING':True,'DATA_DIR':folder,'SECRET_KEY':'synthetic-ledger-only','SESSION_COOKIE_SECURE':False,
            'MEMBER1_PASSWORD':'testing-password-one','MEMBER2_PASSWORD':'testing-password-two',
            'MICROSOFT_CLIENT_ID':'','MICROSOFT_CLIENT_SECRET':'','GOOGLE_CLIENT_ID':'','GOOGLE_CLIENT_SECRET':'',
            'OPENAI_API_KEY':'','OPENAI_MODEL':'','CLOUD_TRANSPORT':deny,'OAUTH_TRANSPORT':deny})
        database=Path(folder)/'household.sqlite3'
        if mode=='contract':
            @app.before_request
            def page_contract():
                if request.method!='GET' or request.path!='/api/finance-hub/transactions':return None
                assert g.actor and g.actor['role']=='member'
                with closing(sqlite3.connect(database)) as con:
                    con.row_factory=sqlite3.Row
                    rows=[finance_hub._row(r) for r in con.execute('SELECT * FROM hub_transactions WHERE owner=?',(g.actor['id'],))]
                    links=[dict(r) for r in con.execute('SELECT * FROM hub_reconciliations WHERE owner=?',(g.actor['id'],))]
                snapshot=hashlib.sha256(json.dumps([rows,links],sort_keys=True).encode()).hexdigest()
                if request.args.get('snapshot') and request.args['snapshot']!=snapshot:
                    return jsonify(error='账本已变化，请刷新后重新查看',code='ledger_changed'),409
                month=request.args['month'];q=request.args.get('q','').strip();size=int(request.args.get('pageSize','50'))
                rows=[r for r in finance_hub.reconciliation_rows(rows,links) if r['date'].startswith(month)]
                rows.sort(key=lambda r:(r['date'],r['id']),reverse=True);count=len(rows)
                def matches(r):return any(q.casefold() in str(v or '').casefold() for v in [r.get(k) for k in ('title','category','externalId','merchantOrderId','paymentId','originalTransactionId')]+[v for item in r.get('orderItems',[]) for v in (item.get('title'),item.get('variant'))])
                rows=[r for r in rows if matches(r)];pages=max(1,(len(rows)+size-1)//size);page=max(1,min(pages,int(request.args.get('page','1'))))
                return jsonify(month=month,q=q,page=page,pageSize=size,transactionCount=count,filteredCount=len(rows),totalPages=pages,
                    hasNext=page<pages,hasPrevious=page>1,snapshot=snapshot,transactions=rows[(page-1)*size:page*size])
        seed=app.test_client();assert seed.post('/api/login',json={'username':'member1','password':'testing-password-one'}).status_code==200
        headers={'X-CSRF-Token':seed.get('/api/me').json['csrf']}
        csv='date,title,amount,currency,flow,category,id,status\n'+''.join(f'2026-08-12,Synthetic batch {i:04d},10.00,CNY,expense,Other,LEDGER-{i:04d},成功\n' for i in range(550))
        payload={'source':'generic','kind':'payments','csv':csv}
        preview=seed.post('/api/finance-hub/imports/preview',json=payload,headers=headers);assert preview.status_code==200,preview.json
        result=seed.post('/api/finance-hub/imports/confirm',json={**payload,'previewToken':preview.json['previewToken']},headers=headers);assert result.status_code==200 and result.json['imported']==550,result.json
        order_payload={'source':'generic','kind':'orders','csv':'date,title,amount,currency,flow,category,id,status\n2026-08-01,Synthetic batch order,10.00,CNY,expense,Other,LEDGER-ORDER,交易成功\n'}
        order_preview=seed.post('/api/finance-hub/imports/preview',json=order_payload,headers=headers);assert order_preview.status_code==200,order_preview.json
        order_result=seed.post('/api/finance-hub/imports/confirm',json={**order_payload,'previewToken':order_preview.json['previewToken']},headers=headers);assert order_result.status_code==200 and order_result.json['imported']==1
        overview=seed.get('/api/finance-hub/overview?month=2026-08').json;assert len(overview['transactions'])==500
        with closing(sqlite3.connect(database)) as con:
            oldest=con.execute("SELECT id,data FROM hub_transactions ORDER BY json_extract(data, '$.date'),id LIMIT 1").fetchone()
        oldest_id=oldest[0];oldest_title=json.loads(oldest[1])['title'];assert oldest_id not in {r['id'] for r in overview['transactions']}
        invitation=seed.post('/api/spaces/invitations',json={},headers=headers).json['invitation']
        child=seed.post('/api/spaces/redeem',json={'invitation':invitation,'name':'Synthetic Ledger Child','slug':'ledger-child','MEMBER1_PASSWORD':'child-password-one','MEMBER2_PASSWORD':'child-password-two'},headers=headers)
        assert child.status_code==201
        server=make_server('127.0.0.1',0,app,threaded=True,request_handler=Quiet)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();origin=f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
                class Flow:
                    def __init__(self,path='/',width=1440):
                        self.ctx=browser.new_context(viewport={'width':width,'height':950});self.held=[];self.gate=False;self.requests=[]
                        self.ctx.route('**/*',self.route)
                        if path=='/':self.login()
                        self.page=self.ctx.new_page();self.page.on('pageerror',lambda e:report['pageErrors'].append(str(e)))
                        self.page.on('dialog',lambda dialog:dialog.accept())
                        self.page.goto(origin+path);self.page.wait_for_function('()=>typeof data!=="undefined"&&data!==null');self.page.evaluate('()=>clearInterval(pollTimer)')
                    def login(self,member=1):
                        r=self.ctx.request.post(origin+'/api/login',data={'username':f'member{member}','password':'testing-password-'+('one' if member==1 else 'two')});assert r.status==200
                    def route(self,route):
                        req=route.request;path=urlsplit(req.url).path;self.requests.append(req.url)
                        if not req.url.startswith(origin+'/'):report['externalRequests'].append(req.url);route.abort();return
                        if path=='/api/finance-hub/transactions':
                            report['ledgerRequests'].append(parse_qs(urlsplit(req.url).query))
                            if self.gate:self.gate=False;self.held.append((route,route.fetch()));return
                        if req.method in ('PATCH','DELETE'):report['writes'].append({'path':path,'method':req.method,'body':req.post_data_json})
                        route.continue_()
                    def open(self):
                        self.page.evaluate('FinanceHub.open("ledger")');expect(self.page.locator('#fh-month')).to_be_visible()
                        self.page.locator('#fh-month').fill('2026-08');self.page.locator('#fh-month').dispatch_event('change');self.ready()
                    def ready(self,page=None):
                        expect(self.page.locator('#fh-ledger-panel')).to_have_attribute('aria-busy','false')
                        if page:expect(self.page.locator('.fh-ledger-status')).to_contain_text(f'第 {page} /')
                    def search(self,q):
                        self.page.locator('#fh-ledger-search input').fill(q);self.page.locator('#fh-ledger-search [type=submit]').click();self.ready()
                    def next(self):self.page.locator('[data-fh=ledger-next]').click();self.ready()
                    def held_ready(self):
                        until=time.monotonic()+10
                        while not self.held and time.monotonic()<until:self.page.wait_for_timeout(20)
                        assert self.held
                    def release(self):
                        route,response=self.held.pop();route.fulfill(response=response)
                    def close(self):
                        for route,_ in self.held:route.abort()
                        self.ctx.close()
                f=Flow();p=f.page;f.open();f.ready(1)
                assert p.locator('.fh-ledger>.fh-transaction').count()==50
                assert 'snapshot' not in report['ledgerRequests'][-1]
                passed('first-page-50-of-551-without-snapshot')
                f.search('batch');assert 'snapshot' not in report['ledgerRequests'][-1]
                for page in range(2,13):f.next();f.ready(page)
                assert 'snapshot' in report['ledgerRequests'][-1]
                expect(p.locator('.fh-ledger')).to_contain_text(oldest_title)
                p.locator('[data-fh=transaction]').click();expect(p.locator('#fh-editor')).to_contain_text(oldest_title)
                p.locator('#fh-editor [name=category]').fill('Reviewed');p.locator('#fh-editor [type=submit]').click();f.ready(12)
                expect(p.locator('#fh-ledger-search input')).to_have_value('batch');expect(p.locator('.fh-ledger')).to_contain_text('Reviewed')
                assert 'snapshot' not in report['ledgerRequests'][-1]
                passed('record-beyond-overview-500-edit-and-fresh-return-preserves-search-page')
                p.locator('[data-fh=shopping-settlement]').click();expect(p.locator('[data-ss=reconcile]')).to_be_visible();p.locator('[data-ss=reconcile]').click()
                expect(p.locator('[data-fh=return-shopping-settlement]')).to_be_visible();p.locator('[data-fh=return-shopping-settlement]').click()
                expect(p.locator('[data-ss=back-ledger]')).to_be_visible();p.locator('[data-ss=back-ledger]').click();f.ready(12)
                expect(p.locator('#fh-ledger-search input')).to_have_value('batch')
                passed('ledger-shopping-reconciliation-shopping-ledger-return-keeps-page-and-query')
                p.locator('[data-fh=transaction]').click();p.locator('[data-fh=delete-transaction]').click();f.ready(11)
                assert report['writes'][-1]['method']=='DELETE' and report['writes'][-1]['body']['revision']==2
                expect(p.locator('.fh-ledger-status')).to_contain_text('550 条匹配');assert 'snapshot' not in report['ledgerRequests'][-1]
                p.locator('[data-fh-tab=overview]').click();expect(p.locator('.fh-currency')).to_contain_text('5,500')
                p.locator('[data-fh-tab=ledger]').click();f.ready(11)
                passed('delete-last-page-clamps-with-original-revision-and-full-month-total-updates')
                f.search('LEDGER-0001');expect(p.locator('.fh-ledger-status')).to_contain_text('1 条匹配')
                p.locator('[data-fh-tab=overview]').click();expect(p.locator('.fh-currency')).to_contain_text('5,500')
                p.locator('[data-fh-tab=ledger]').click();f.ready(1);expect(p.locator('#fh-ledger-search input')).to_have_value('LEDGER-0001')
                passed('narrow-original-id-search-does-not-change-full-month-spending')
                f.search('no-such-synthetic-record');expect(p.locator('.fh-ledger')).to_contain_text('没有匹配');expect(p.locator('#fh-ledger-panel')).to_contain_text('全月 550')
                p.locator('[data-fh=ledger-clear]').click();f.ready(1);expect(p.locator('#fh-ledger-search input')).to_have_value('')
                p.locator('#fh-month').fill('2026-07');p.locator('#fh-month').dispatch_event('change');f.ready(1);expect(p.locator('.fh-ledger')).to_contain_text('这个月没有记录')
                p.locator('[data-fh=month][data-month="2026-08"]').click();expect(p.locator('#fh-month')).to_have_value('2026-08');f.ready(1)
                passed('empty-search-empty-month-clear-and-recorded-month-navigation')
                f.search('batch')
                mutate=seed.get('/api/finance-hub/overview?month=2026-08').json['transactions'][0]
                assert seed.patch('/api/finance-hub/transactions/'+mutate['id'],json={'revision':mutate['revision'],'category':'changed'},headers=headers).status_code==200
                f.next();expect(p.locator('#fh-ledger-panel .error')).to_contain_text('账本已变化');assert p.locator('[data-fh=transaction]').count()==0
                expect(p.locator('#fh-ledger-search input')).to_have_value('batch');p.locator('[data-fh=ledger-refresh]').click();f.ready(2)
                assert 'snapshot' not in report['ledgerRequests'][-1]
                passed('snapshot-conflict-removes-stale-rows-and-explicit-refresh-retains-query')
                f.gate=True;p.locator('[data-fh=ledger-next]').click();f.held_ready();f.search('no-match-after-held');f.release();p.wait_for_timeout(150)
                expect(p.locator('#fh-ledger-search input')).to_have_value('no-match-after-held');expect(p.locator('.fh-ledger')).to_contain_text('没有匹配')
                passed('late-page-cannot-replace-new-search')
                f.search('batch');f.gate=True;p.locator('[data-fh=ledger-next]').click();f.held_ready();p.locator('#fh-month').fill('2026-07');p.locator('#fh-month').dispatch_event('change');f.ready();f.release();p.wait_for_timeout(150)
                expect(p.locator('#fh-month')).to_have_value('2026-07');expect(p.locator('.fh-ledger')).to_contain_text('这个月没有记录')
                passed('late-page-cannot-replace-new-month')
                f.open();f.gate=True;p.locator('[data-fh=ledger-next]').click();f.held_ready();p.locator('#dialog [data-action=close]').click();f.release();p.wait_for_timeout(150);expect(p.locator('#dialog')).not_to_be_visible()
                passed('closed-dialog-rejects-late-page')
                f.open();f.gate=True;p.locator('[data-fh=ledger-next]').click();f.held_ready();f.login(2);f.release();expect(p.locator('#dialog')).to_contain_text('登录成员或家庭已变化');assert p.locator('.fh-transaction').count()==0
                passed('changed-member-cookie-rejects-old-page-and-clears-records');f.close()
                f=Flow();p=f.page;f.open();f.gate=True;p.locator('[data-fh=ledger-next]').click();f.held_ready();f.ctx.request.get(origin+child.json['entry']);assert f.ctx.request.post(origin+'/api/login',data={'username':'member1','password':'child-password-one'}).status==200;f.release()
                expect(p.locator('#dialog')).to_contain_text('登录成员或家庭已变化');assert p.locator('.fh-transaction').count()==0
                passed('same-member-other-household-rejects-old-page');f.close()
                f=Flow();p=f.page;f.open();p.locator('[data-fh=transaction]').first.click();expect(p.locator('#fh-editor')).to_be_visible();f.login(2)
                writes=len(report['writes']);p.locator('[data-fh=delete-transaction]').click();expect(p.locator('#dialog')).to_contain_text('登录成员或家庭已变化');assert len(report['writes'])==writes
                passed('changed-member-before-delete-sends-no-mutation');f.close()
                f=Flow(width=360);p=f.page;f.open();f.search('batch');assert p.locator('#fh-ledger-search').evaluate('(el)=>el.scrollWidth<=el.clientWidth+1')
                assert p.locator('#dialog').evaluate('(el)=>el.scrollWidth<=el.clientWidth+1')
                screenshot=out/f'finance-ledger-mobile-{stamp}.png';p.screenshot(path=str(screenshot));report['screenshots'].append(str(screenshot));passed('mobile-search-and-pagination-fit-with-accessible-controls');f.close()
                f=Flow('/demo#finance');p=f.page
                p.locator('[data-ps-module=FinanceHub][data-ps-id=ledger]').click() if p.locator('[data-ps-module=FinanceHub][data-ps-id=ledger]').count() else p.locator('[data-ps-module=FinanceHub]').first.click()
                f.ready(1);assert p.locator('.fh-ledger>.fh-transaction').count()==50;f.next();f.ready(2);f.search('DEMO-1');expect(p.locator('.fh-ledger-status')).to_contain_text('34 条匹配')
                assert not [u for u in f.requests if '/api/' in u];assert p.locator('[data-fh=transaction]').count()==0
                passed('actual-demo-route-local-only-search-pagination-no-api-or-write-controls');f.close()
                f=Flow('/demo?tv=1');f.page.evaluate('FinanceHub.open("ledger")');assert f.page.locator('#fh-ledger-panel').count()==0;assert not [u for u in f.requests if '/api/' in u];passed('tv-demo-has-no-private-ledger-entry');f.close()
                browser.close()
            assert not report['pageErrors'] and not report['externalRequests'] and not report['providerCalls']
            report['passed']=True
        except Exception:
            report['error']=traceback.format_exc();raise
        finally:
            server.shutdown();thread.join(timeout=5)
            report['sourceHashesAfter']=hashes();report['sourceFilesUnchanged']=report['sourceHashesAfter']==report['sourceHashesBefore']
            target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print('REPORT '+str(target),flush=True)

if __name__=='__main__':main()
