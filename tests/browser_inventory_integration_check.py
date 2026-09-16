"""Real inventory API/core/auth/SQLite in Edge; no substitute business endpoint."""
import argparse
from contextlib import ExitStack, closing
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
import traceback
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import app as app_module
from flask import Response, g
from inventory_api import register_inventory
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server, WSGIRequestHandler

HTML='''<!doctype html><html lang="zh-CN" data-theme="light"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="/static/inventory-ui.css"><style>body{margin:20px;background:#fafafa}main{max-width:1280px;margin:auto}</style><main id="inventory-fixture"></main>
<script src="/static/inventory-ui.js"></script><script src="/__inventory_fixture.js"></script></html>'''
BOOTSTRAP='''
let user=null,csrf='',isTV=false,isDemo=false;const canEdit=()=>user?.role==='member'&&!isTV&&!isDemo;
async function api(path,options={}){const response=await fetch('/api'+path,{credentials:'same-origin',cache:'no-store',...options,headers:{'Content-Type':'application/json','X-CSRF-Token':csrf}});const result=await response.json();if(!response.ok){const error=new Error(result.error);error.status=response.status;error.code=result.code;throw error;}return result;}
const write=(path,method,payload)=>api(path,{method,body:JSON.stringify(payload)});
api('/me').then(me=>{user=me.user;csrf=me.csrf;InventoryUI.mount(document.querySelector('#inventory-fixture'));});'''


class Quiet(WSGIRequestHandler):
    def log(self,*_args,**_kwargs):pass


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-factory',action='store_true',help='Refuse fixture API registration for every household/factory')
    parser.add_argument('--require-shell',action='store_true',help='Use actual index and ProductShell inventory navigation, and require factory')
    args=parser.parse_args();require_factory=args.require_factory or args.require_shell
    out=ROOT/'test-results'/('inventory-integration-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));out.mkdir(parents=True,exist_ok=False)
    names=set(subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0'))-{''}
    names.add(Path(__file__).relative_to(ROOT).as_posix())
    if (ROOT/'docs/INVENTORY-INTEGRATION.md').exists():names.add('docs/INVENTORY-INTEGRATION.md')
    hashes=lambda:{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in sorted(names)}
    report=dict(passed=False,checks=[],pageErrors=[],externalRequests=[],registration=[],screenshots=[],requireFactory=require_factory,requireShell=args.require_shell,
                gitHead=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),sourceHashesBefore=hashes(),
                scope='Real Flask application, current member cookies/CSRF/household routing, inventory API/core and SQLite. Fixture only registers missing API and serves HTML; no fake business responses. One committed real HTTP response is deliberately dropped.')
    def passed(message):report['checks'].append(message);print('PASS '+message,flush=True)
    original=app_module.create_app
    def create(config):
        application=original(config)
        if 'inventory' in application.extensions:mode='factory'
        else:
            if require_factory:raise AssertionError('Factory inventory registration required; fallback refused')
            assert not application._got_first_request
            def db():
                if 'inventory_browser_db' not in g:
                    con=sqlite3.connect((Path(application.config['DATA_DIR'])/'household.sqlite3').as_uri()+'?mode=rw',uri=True,timeout=15)
                    con.row_factory=sqlite3.Row;con.execute('PRAGMA foreign_keys=ON');g.inventory_browser_db=con
                return g.inventory_browser_db
            @application.teardown_appcontext
            def close(_error):
                con=g.pop('inventory_browser_db',None)
                if con is not None:con.close()
            register_inventory(application,db,app_module.Problem)
            mode='explicit fixture registration before first request'
        report['registration'].append({'mode':mode,'household':application.config.get('HOUSEHOLD_INFO',{}).get('id','default')})
        if not args.require_shell:
            application.add_url_rule('/__inventory_fixture',endpoint='inventory_browser_fixture',view_func=lambda:HTML)
            application.add_url_rule('/__inventory_fixture.js',endpoint='inventory_browser_bootstrap',view_func=lambda:Response(BOOTSTRAP,mimetype='application/javascript'))
        return application
    original_connect=socket.socket.connect
    def connect(sock,address):
        if isinstance(address,tuple) and address[0] not in ('127.0.0.1','::1','localhost'):
            report['externalRequests'].append('blocked non-loopback socket');raise AssertionError('External network forbidden')
        return original_connect(sock,address)
    server=None;thread=None
    def stop():
        nonlocal server
        if server:
            if thread and thread.is_alive():server.shutdown()
            server.server_close();server=None
        if thread:thread.join(timeout=5);assert not thread.is_alive()
    try:
        with ExitStack() as lifecycle:
            lifecycle.enter_context(patch.object(socket.socket,'connect',connect))
            lifecycle.enter_context(patch.object(app_module,'create_app',create))
            folder=Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='inventory-browser-')))
            server=make_server('127.0.0.1',0,None,threaded=True,request_handler=Quiet,ssl_context='adhoc');lifecycle.callback(stop)
            base=f'https://127.0.0.1:{server.server_port}'
            config=dict(TESTING=True,DATA_DIR=str(folder),SECRET_KEY='synthetic-inventory-browser-secret',SESSION_COOKIE_SECURE=True,PUBLIC_ORIGIN=base,
                        MEMBER1_PASSWORD='synthetic-inventory-one',MEMBER2_PASSWORD='synthetic-inventory-two',
                        GOOGLE_CLIENT_ID='',GOOGLE_CLIENT_SECRET='',MICROSOFT_CLIENT_ID='',MICROSOFT_CLIENT_SECRET='',ASSISTANT_PROVIDER='local',NVIDIA_API_KEY='',NVIDIA_MODEL='',OPENAI_API_KEY='',OPENAI_MODEL='')
            application=create(config);server.app=application;thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            with sync_playwright() as pw, ExitStack() as browsers:
                browser=pw.chromium.launch(channel='msedge',headless=True);browsers.callback(browser.close)
                def context():
                    ctx=browser.new_context(viewport={'width':390,'height':844},ignore_https_errors=True)
                    def route(handler):
                        if urlsplit(handler.request.url).hostname=='127.0.0.1':handler.continue_()
                        else:report['externalRequests'].append(urlsplit(handler.request.url).hostname);handler.abort()
                    ctx.route('**/*',route);ctx.on('page',lambda p:p.on('pageerror',lambda e:report['pageErrors'].append(str(e))))
                    return ctx
                def headers(ctx):
                    response=ctx.request.get(base+'/api/me');assert response.status==200
                    return {'X-CSRF-Token':response.json()['csrf'],'Origin':base}
                def login(ctx,number=1):
                    response=ctx.request.post(base+'/api/login',data={'username':f'member{number}','password':config[f'MEMBER{number}_PASSWORD']});assert response.status==200,response.text()
                def get(ctx,path):
                    response=ctx.request.get(base+path);assert response.status==200,response.text();return response.json()
                def open_inventory(page):
                    page.goto(base+('/' if args.require_shell else '/__inventory_fixture'))
                    if args.require_shell:
                        if page.viewport_size['width']<=760:
                            more=page.locator('[data-ps-more]');expect(more).to_be_visible();more.click()
                            entry=page.locator('#ps-more-menu [data-ps-route=inventory]')
                        else:entry=page.locator('.ps-sidebar [data-ps-route=inventory]')
                        expect(entry).to_be_visible();entry.click()
                    expect(page.locator('[data-iv=new-item]')).to_be_enabled()
                def choose_item(page,item_id):
                    page.locator(f'[data-iv=select-item][data-id="{item_id}"]').click();expect(page.locator('[data-iv=new-batch]')).to_be_enabled()
                def choose_batch(page,batch_id):
                    page.locator(f'[data-iv=select-batch][data-id="{batch_id}"]').click();expect(page.locator('[data-iv=new-movement]')).to_be_enabled()
                def movement(page,kind,quantity,*,expect_saved=True):
                    page.locator('[data-iv=new-movement]').click();form=page.locator('[data-iv-form]');form.locator('[name=kind]').select_option(kind);form.locator('[name=quantity]').fill(str(quantity));form.locator('[name=reason]').fill('合成真实实物动作')
                    form.locator('[name=confirmed]').check();form.locator('[type=submit]').click()
                    if expect_saved:expect(page.locator('[data-iv=new-movement]')).to_be_enabled()
                owner=context();login(owner);page=owner.new_page();open_inventory(page)
                partner=context();login(partner,2);partner_page=partner.new_page();open_inventory(partner_page)
                page.locator('[data-iv=new-item]').click();form=page.locator('[data-iv-form]');form.locator('[name=title]').fill('合成真实电池');form.locator('[name=unit]').fill('节');form.locator('[name=location]').fill('合成玄关');form.locator('[type=submit]').click();expect(page.locator('.iv-card')).to_have_count(1)
                item=get(owner,'/api/inventory/items')['items'][0];uid=item['id'];assert item['visibility']=='private' and item['onHandQty']==0
                assert get(partner,'/api/inventory/items')['total']==0 and partner.request.get(base+'/api/inventory/items/'+uid).status==404
                passed('actual member login and mobile UI create a private item with partner denied')
                page.locator('[data-iv=new-batch]').click();form=page.locator('[data-iv-form]');form.locator('[name=orderedQty]').fill('8');form.locator('[name=orderState]').select_option('in_transit');form.locator('[type=submit]').click();expect(page.locator('[data-iv=new-movement]')).to_be_enabled()
                batch=get(owner,f'/api/inventory/items/{uid}/acquisitions')['items'][0];bid=batch['id']
                assert (get(owner,'/api/inventory/items/'+uid)['item']['onHandQty'],batch['remainingExpectedQty'])==(0,8)
                movement(page,'receive',3);movement(page,'receive',2)
                item=get(owner,'/api/inventory/items/'+uid)['item'];assert (item['onHandQty'],item['inTransitQty'])==(5,3)
                events=get(owner,f'/api/inventory/acquisitions/{bid}/movements');assert events['total']==2 and sorted(m['deltaQty'] for m in events['items'])==[2,3]
                passed('actual batch and two explicit receipt clicks persist distinct movements and correct stock/in-transit totals')
                page.locator('[data-iv=edit-item]').click();form=page.locator('[data-iv-form]');form.locator('[name=visibility]').select_option('shared');form.locator('[type=submit]').click();expect(page.locator('[data-iv=edit-item]')).to_be_enabled()
                partner_page.locator('[data-iv=refresh]').click();expect(partner_page.locator('.iv-card')).to_have_count(1);choose_item(partner_page,uid);expect(partner_page.locator('[data-iv=edit-item]')).to_have_count(0);choose_batch(partner_page,bid)
                movement(partner_page,'consume',1)
                events=get(owner,f'/api/inventory/acquisitions/{bid}/movements');assert events['items'][0]['actor']=='member2' and events['items'][0]['kind']=='consume'
                assert get(owner,'/api/inventory/items/'+uid)['item']['onHandQty']==4
                passed('real second member can perform shared physical action without gaining owner management')
                page.locator('[data-iv=refresh]').click();expect(page.locator('[data-iv=edit-item]')).to_be_enabled();page.locator('[data-iv=edit-item]').click();form=page.locator('[data-iv-form]');form.locator('[name=visibility]').select_option('private');form.locator('[type=submit]').click();expect(page.locator('[data-iv=edit-item]')).to_be_enabled()
                partner_page.locator('[data-iv=refresh]').click();expect(partner_page.locator('.iv-detail,.iv-card')).to_have_count(0)
                for path in [f'/api/inventory/items/{uid}',f'/api/inventory/acquisitions/{bid}',f'/api/inventory/acquisitions/{bid}/movements']:assert partner.request.get(base+path).status==404
                passed('owner privacy withdrawal removes partner DOM and denies item, batch and movement readback')
                choose_batch(page,bid);dropped={};pattern='**/api/inventory/acquisitions/*/movements'
                def drop_response(handler):
                    if handler.request.method!='POST' or dropped:handler.continue_();return
                    response=handler.fetch();assert response.status==200,response.text()
                    dropped.update(requestId=handler.request.post_data_json['requestId'],result=response.json(),status=response.status)
                    handler.abort('failed')
                page.route(pattern,drop_response)
                movement(page,'receive',3,expect_saved=False);expect(page.locator('[data-iv=retry]')).to_be_enabled()
                assert dropped and get(owner,f'/api/inventory/acquisitions/{bid}/movements')['total']==4
                before=get(owner,'/api/inventory/items/'+uid)['item'];assert (before['onHandQty'],before['inTransitQty'])==(7,0)
                page.locator('[data-iv=retry]').click();expect(page.locator('[data-iv=new-movement]')).to_be_enabled();page.unroute(pattern,drop_response)
                assert get(owner,f'/api/inventory/acquisitions/{bid}/movements')['total']==4
                receipt=get(owner,'/api/inventory/operations/'+dropped['requestId']);assert receipt['operation']['replayed'] and receipt['item']==before
                with closing(sqlite3.connect(folder/'household.sqlite3')) as con:
                    assert con.execute('SELECT count(*) FROM inventory_operations WHERE request_id=?',(dropped['requestId'],)).fetchone()[0]==1
                    assert con.execute('SELECT count(*) FROM inventory_movements WHERE request_id=?',(dropped['requestId'],)).fetchone()[0]==1
                report['droppedResponse']={'status':dropped['status'],'requestId':dropped['requestId'],'movementId':dropped['result']['operation']['movementId'],'realServerCommit':True}
                passed('one actual committed response is dropped; original operation lookup recovers without duplicate SQL movement')
                page.locator('[data-iv=edit-item]').click();form=page.locator('[data-iv-form]');form.locator('[name=location]').fill('真实刷新保留的草稿');form.locator('[name=location]').focus()
                page.evaluate("()=>{window.savedInventoryInput=document.querySelector('[data-iv-form] [name=location]');savedInventoryInput.setSelectionRange(1,3)}")
                if args.require_shell:page.evaluate('async()=>{await refresh(true)}')
                else:page.evaluate("async()=>{await api('/state');InventoryUI.notifyStateChanged();await InventoryUI.mount(document.querySelector('#inventory-fixture'));}")
                assert page.evaluate('()=>document.activeElement===savedInventoryInput && savedInventoryInput.isConnected && savedInventoryInput.selectionStart===1 && savedInventoryInput.selectionEnd===3')
                expect(form.locator('[name=location]')).to_have_value('真实刷新保留的草稿');page.locator('[data-iv=cancel-form]').click()
                open_inventory(page);expect(page.locator('.iv-card')).to_have_count(1)
                server.app=create(config);open_inventory(page);expect(page.locator('.iv-card')).to_have_count(1)
                assert get(owner,'/api/inventory/items/'+uid)['item']==before
                assert get(owner,f'/api/inventory/acquisitions/{bid}/movements')['total']==4
                with closing(sqlite3.connect(folder/'household.sqlite3')) as con:
                    assert con.execute('PRAGMA foreign_key_check').fetchall()==[]
                    assert con.execute('SELECT count(*) FROM hub_transactions').fetchone()[0]==0
                    assert con.execute('SELECT count(*) FROM inventory_source_links').fetchone()[0]==0
                passed('current state refresh retains draft DOM; page reload and actual factory restart preserve SQLite quantities and receipts')
                choose_item(page,uid);page.locator('[data-iv=edit-item]').click();page.locator('[data-iv-form] [name=location]').fill('PRIVATE_OLD_MEMBER_DRAFT')
                assert owner.request.post(base+'/api/logout',headers=headers(owner),data={}).status==200
                login(owner,2);page.locator('[data-iv-form] [type=submit]').click();expect(page.locator('.iv-card,.iv-detail,[data-iv-form]')).to_have_count(0)
                assert owner.request.get(base+'/api/inventory/items/'+uid).status==404
                with closing(sqlite3.connect(folder/'household.sqlite3')) as con:
                    assert con.execute('SELECT location FROM inventory_items WHERE id=?',(uid,)).fetchone()[0]=='合成玄关'
                passed('actual cookie member switch clears private draft and me fence prevents its write')
                admin=context();login(admin)
                invitation=admin.request.post(base+'/api/spaces/invitations',headers=headers(admin),data={});assert invitation.status==201
                created=admin.request.post(base+'/api/spaces/redeem',headers=headers(admin),data={'invitation':invitation.json()['invitation'],'name':'合成库存第二家庭','slug':'inventory-browser-two','MEMBER1_PASSWORD':config['MEMBER1_PASSWORD'],'MEMBER2_PASSWORD':config['MEMBER2_PASSWORD']});assert created.status==201,created.text()
                child=context();child_page=child.new_page();child_page.goto(base+created.json()['entry']);login(child);open_inventory(child_page);expect(child_page.locator('.iv-card')).to_have_count(0)
                assert child.request.get(base+'/api/inventory/items/'+uid).status==404 and child.request.get(base+'/api/inventory/operations/'+dropped['requestId']).status==404
                child_page.locator('[data-iv=new-item]').click();form=child_page.locator('[data-iv-form]');form.locator('[name=title]').fill('仅第二家庭的合成库存');form.locator('[type=submit]').click();expect(child_page.locator('.iv-card')).to_have_count(1)
                child_id=get(child,'/api/inventory/items')['items'][0]['id'];assert admin.request.get(base+'/api/inventory/items/'+child_id).status==404
                assert get(child,'/api/me')['user']['householdId']!=get(admin,'/api/me')['user']['householdId']
                passed('actual invite/redeem and child factory use separate SQLite; same member ID cannot cross household objects or receipts')
                final_page=admin.new_page();open_inventory(final_page);choose_item(final_page,uid);choose_batch(final_page,bid)
                for width,height in [(390,844),(1440,1000)]:
                    final_page.set_viewport_size({'width':width,'height':height});assert final_page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                    shot=out/f'inventory-real-{width}.png';final_page.screenshot(path=str(shot),full_page=True);report['screenshots'].append(str(shot))
                assert not report['pageErrors'] and not report['externalRequests'];report['passed']=True
    except Exception:
        report['passed']=False;report['failure']=traceback.format_exc();print(report['failure'],flush=True)
    finally:
        stop();report['sourceHashesAfter']=hashes();report['sourceUnchanged']=report['sourceHashesBefore']==report['sourceHashesAfter'];report['passed']=report['passed'] and report['sourceUnchanged']
        target=out/'result.json';target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'report':str(target)},ensure_ascii=False),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
