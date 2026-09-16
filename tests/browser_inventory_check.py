"""Real Edge, explicit synthetic inventory HTTP contract; no real household data."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import threading
import traceback

from flask import Flask, jsonify, request
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server, WSGIRequestHandler

ROOT=Path(__file__).resolve().parents[1]
FIELDS=['orderedQty','orderState','orderedOn','expectedOn','warrantyUntil','afterSalesState','note','shoppingId']
LIMITED=['orderState','expectedOn','afterSalesState','note']
CONFIRM={'receive':'confirmReceived','consume':'confirmConsumed','dispose':'confirmDisposed','return':'confirmReturned','adjust':'confirmCorrection'}
HTML='''<!doctype html><html lang="zh-CN" data-theme="light"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="/static/inventory-ui.css"><style>body{margin:20px;background:#fafafa}main{max-width:1280px;margin:auto}</style><main id="host"></main><script>
let user=null,csrf='',isTV=false,isDemo=false;const canEdit=()=>user?.role==='member'&&!isTV&&!isDemo;
async function api(path,options={}){const r=await fetch('/api'+path,{...options,credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf}});const value=await r.json();if(!r.ok){const e=new Error(value.error);e.status=r.status;e.code=value.code;throw e;}return value;}
const write=(path,method,payload)=>api(path,{method,body:JSON.stringify(payload)});
window.switchIdentity=()=>{user={...user,id:'member2',householdId:'other-home'};csrf='synthetic-other';InventoryUI.notifyIdentityChanged();};
</script><script src="/static/inventory-ui.js"></script><script>api('/me').then(me=>{user=me.user;csrf=me.csrf;InventoryUI.mount(document.querySelector('#host'));});</script></html>'''


class Quiet(WSGIRequestHandler):
    def log(self,*_args,**_kwargs): pass


class Fixture:
    def __init__(self):
        self.actor='member1';self.items={};self.batches={};self.movements={};self.receipts={};self.records=[]
        self.serial=0;self.lose_after=True;self.lose_before=False;self.conflict=False;self.hold=False
        self.started=threading.Event();self.release=threading.Event()

    def identifier(self):
        self.serial+=1;return f'{self.serial:024x}'

    def item(self,title='合成家居物品',owner='member1',visibility='private'):
        value=dict(id=self.identifier(),owner=owner,title=title,unit='个',variant='',location='',visibility=visibility,revision=1,
                   reorderPoint=None,onHandQty=0,inTransitQty=0,plannedQty=0,belowThreshold=False,canRead=True,canMutate=True,canManage=owner==self.actor)
        self.items[value['id']]=value;return value

    def permitted(self,item): return item['owner']==self.actor or item['visibility']=='shared'

    def project(self,item): return {**item,'canManage':item['owner']==self.actor}

    def batch(self,b):
        full=self.items[b['itemId']]['owner']==self.actor or b['creator']==self.actor
        return {k:v for k,v in {**b,'itemRevision':self.items[b['itemId']]['revision'],'canEditAllFields':full,'editableFields':FIELDS if full else LIMITED}.items() if k!='creator'}

    def recount(self,b):
        moves=[m for m in self.movements.values() if m['acquisitionId']==b['id']]
        reversed_ids={m['reversesId'] for m in moves if m['kind']=='reverse'}
        b['onHandQty']=sum(m['deltaQty'] for m in moves)
        b['receivedQty']=sum(m['deltaQty'] for m in moves if m['kind']=='receive' and m['id'] not in reversed_ids)
        b['returnedQty']=-sum(m['deltaQty'] for m in moves if m['kind']=='return' and m['id'] not in reversed_ids)
        b['remainingExpectedQty']=max(0,b['orderedQty']-b['receivedQty']) if b['orderState'] not in ('closed','cancelled') else 0
        b['fulfillmentState']='unreceived' if not b['receivedQty'] else 'received' if b['receivedQty']==b['orderedQty'] else 'partial'
        item=self.items[b['itemId']];batches=[x for x in self.batches.values() if x['itemId']==item['id']]
        item['onHandQty']=sum(x['onHandQty'] for x in batches)
        item['inTransitQty']=sum(x['remainingExpectedQty'] for x in batches if x['orderState'] in ('ordered','in_transit'))
        item['plannedQty']=sum(x['remainingExpectedQty'] for x in batches if x['orderState']=='planned')

    @staticmethod
    def paginated(values):
        offset=int(request.args.get('offset',0));limit=int(request.args.get('limit',24))
        return jsonify(items=values[offset:offset+limit],total=len(values),offset=offset,limit=limit,nextOffset=offset+limit if offset+limit<len(values) else None)

    def app(self):
        app=Flask(__name__,static_folder=str(ROOT/'static'))
        app.add_url_rule('/',view_func=lambda:HTML)

        @app.route('/api/<path:path>',methods=['GET','POST','PATCH','DELETE'])
        def route(path):
            body=request.get_json(silent=True) or {};self.records.append(dict(path=path,method=request.method,body=deepcopy(body)))
            if path=='me': return jsonify(user=dict(id=self.actor,role='member',householdId='synthetic-home',auth_version=1),csrf='synthetic-'+self.actor)
            parts=path.split('/');assert parts[0]=='inventory';parts=parts[1:]
            if self.hold and request.method=='GET' and parts==['items']:
                values=[self.project(x) for x in self.items.values() if self.permitted(x)]
                self.started.set();self.release.wait(10);return self.paginated(values)
            def error(code,status):return jsonify(error='合成契约：'+code,code=code),status
            if parts[0]=='operations':
                previous=self.receipts.get(parts[1]);
                if not previous:return error('not_found',404)
                result=deepcopy(previous['result']);item=self.items.get(result['operation']['itemId'])
                if not item:return error('gone',410)
                if not self.permitted(item):return error('not_found',404)
                result['item']=self.project(item);result['operation']['replayed']=True
                if 'acquisition' in result:result['acquisition']=self.batch(self.batches[result['acquisition']['id']])
                return jsonify(result)
            if parts==['items'] and request.method=='GET':
                scope=request.args.get('scope','all');q=request.args.get('q','').lower()
                values=[self.project(x) for x in self.items.values() if self.permitted(x) and (scope=='all' or scope=='mine' and x['owner']==self.actor or scope=='shared' and x['visibility']=='shared') and q in ' '.join(str(x[k]) for k in ('title','variant','location')).lower()]
                return self.paginated(values)
            item=None;batch=None
            if parts[0]=='items' and len(parts)>1:item=self.items.get(parts[1])
            if parts[0]=='acquisitions':
                batch=self.batches.get(parts[1]);item=self.items.get(batch['itemId']) if batch else None
            if len(parts)>1 and (not item or not self.permitted(item)):return error('not_found',404)
            if request.method=='GET':
                if parts[0]=='items' and len(parts)==2:return jsonify(item=self.project(item))
                if parts[-1]=='acquisitions':return self.paginated([self.batch(x) for x in self.batches.values() if x['itemId']==item['id']])
                if parts[-1]=='movements':return self.paginated(list(reversed([x for x in self.movements.values() if x['acquisitionId']==batch['id']])))
                return jsonify(item=self.project(item),acquisition=self.batch(batch))
            assert re.fullmatch('[a-f0-9]{32,64}',body['requestId'])
            previous=self.receipts.get(body['requestId'])
            if previous:assert previous['body']==body;return jsonify(previous['result'])
            if self.lose_before:self.lose_before=False;return error('storage',503)
            if self.conflict:
                self.conflict=False;item['revision']+=1;return error('conflict',409)
            if item:
                if body.get('itemRevision',body.get('revision'))!=item['revision']:return error('conflict',409)
                if batch and body['revision']!=batch['revision']:return error('conflict',409)
            movement=None
            if parts==['items']:
                item=self.item();item.update(body['data']);assert item['visibility'] in ('private','shared')
            elif parts[0]=='items' and len(parts)==2:
                assert item['owner']==self.actor
                if request.method=='DELETE':
                    assert body['confirmArchive'] and item['onHandQty']==0
                    del self.items[item['id']]
                else:item.update(body['patch'])
                item['revision']+=1
            elif parts[-1]=='acquisitions':
                batch=dict(id=self.identifier(),itemId=item['id'],creator=self.actor,shoppingId=None,revision=1,canMutate=True,canManageSources=True,
                           onHandQty=0,receivedQty=0,returnedQty=0,remainingExpectedQty=0,fulfillmentState='unreceived',**body['data'])
                assert type(batch['orderedQty']) is int and batch['orderedQty']>0
                self.batches[batch['id']]=batch;item['revision']+=1;self.recount(batch)
            elif parts[0]=='acquisitions' and len(parts)==2:
                assert set(body['patch'])<=set(self.batch(batch)['editableFields']);batch.update(body['patch']);batch['revision']+=1;item['revision']+=1;self.recount(batch)
            else:
                data=body['data'];kind=data.get('kind','reverse')
                assert body[CONFIRM[kind] if kind!='reverse' else 'confirmReversal'] is True
                assert set(k for k in body if k.startswith('confirm'))=={CONFIRM[kind] if kind!='reverse' else 'confirmReversal'}
                if kind=='reverse':
                    prior=self.movements[parts[-2]];assert prior['canReverse'];prior['canReverse']=False;delta=-prior['deltaQty'];reverse=prior['id']
                else:
                    assert type(data['quantity']) is int and data['quantity']!=0
                    if kind!='adjust':assert data['quantity']>0
                    delta=data['quantity']*(1 if kind in ('receive','adjust') else -1);reverse=None
                if kind!='receive':assert data['reason'].strip()
                assert batch['onHandQty']+delta>=0
                if kind=='receive':assert batch['receivedQty']+delta<=batch['orderedQty']
                movement=dict(id=self.identifier(),acquisitionId=batch['id'],actor=self.actor,kind=kind,deltaQty=delta,occurredOn=data['occurredOn'],reason=data.get('reason',''),reversesId=reverse,canReverse=kind!='reverse',createdAt='2026-09-16')
                self.movements[movement['id']]=movement;batch['revision']+=1;item['revision']+=1;self.recount(batch)
            operation=dict(itemId=item['id'],itemRevision=item['revision'],replayed=False)
            result=dict(operation=operation,item=self.project(item))
            if request.method=='DELETE':operation['deleted']=True;result.pop('item')
            if batch:result['acquisition']=self.batch(batch);operation.update(acquisitionId=batch['id'],acquisitionRevision=batch['revision'])
            if movement:operation['movementId']=movement['id']
            self.receipts[body['requestId']]={'body':deepcopy(body),'result':deepcopy(result)}
            if self.lose_after:self.lose_after=False;return error('storage',503)
            return jsonify(result)
        return app


def main():
    out=ROOT/'test-results'/('inventory-ui-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));out.mkdir(parents=True)
    report=dict(passed=False,checks=[],pageErrors=[],externalRequests=[],scope='Real Edge with synthetic inventory HTTP contract, not actual backend, production or physical TV.')
    paths=['static/inventory-ui.js','static/inventory-ui.css','tests/browser_inventory_check.py']
    digest=lambda:{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in paths}
    report['sourceHashesBefore']=digest();fixture=Fixture();server=make_server('127.0.0.1',0,fixture.app(),threaded=True,request_handler=Quiet)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base=f'http://127.0.0.1:{server.server_port}'
    def passed(text):report['checks'].append(text);print('PASS '+text,flush=True)
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(channel='msedge',headless=True)
            try:
                page=browser.new_page(viewport=dict(width=390,height=844));page.on('pageerror',lambda e:report['pageErrors'].append(str(e)))
                def route(r):
                    if r.request.url.startswith(base+'/'):r.continue_()
                    else:report['externalRequests'].append(r.request.url);r.abort()
                page.route('**/*',route);page.goto(base)
                expect(page.locator('[data-iv=new-item]')).to_be_enabled()
                page.locator('[data-iv=new-item]').click();form=page.locator('[data-iv-form]')
                form.locator('[name=title]').fill('合成电池 <img onerror=alert(1)>');form.locator('[name=unit]').fill('节');form.locator('[name=location]').fill('玄关抽屉');form.locator('[type=submit]').click()
                expect(page.locator('[data-iv=retry]')).to_be_enabled();expect(form.locator('[name=title]')).to_be_disabled();expect(page.locator('[data-iv=new-item]')).to_be_disabled()
                page.locator('[data-iv=retry]').click();expect(page.locator('.iv-card')).to_have_count(1)
                assert len([r for r in fixture.records if r['path']=='inventory/items' and r['method']=='POST'])==1
                item=next(iter(fixture.items.values()));assert item['visibility']=='private' and item['onHandQty']==0
                assert page.locator('img').count()==0
                passed('mobile private item; escaped text; lost committed response resolves receipt without second POST')
                page.locator('[data-iv=new-batch]').click();form=page.locator('[data-iv-form]');form.locator('[name=orderedQty]').fill('10');form.locator('[name=orderState]').select_option('in_transit');form.locator('[type=submit]').click()
                expect(page.locator('[data-iv=new-movement]')).to_be_enabled();batch=next(iter(fixture.batches.values()))
                assert item['onHandQty']==0 and item['inTransitQty']==10
                passed('purchase batch creates expectations only, never implicit stock')
                def movement(kind,quantity,reason='合成实际动作',conflict=False):
                    page.locator('[data-iv=new-movement]').click();form=page.locator('[data-iv-form]');form.locator('[name=kind]').select_option(kind);form.locator('[name=quantity]').fill(str(quantity));form.locator('[name=reason]').fill(reason)
                    form.locator('[type=submit]').click();expect(page.locator('[data-iv-message]')).to_contain_text('请明确确认')
                    form.locator('[name=confirmed]').check();fixture.conflict=conflict;form.locator('[type=submit]').click()
                    if conflict:
                        expect(page.locator('[data-iv=recheck]')).to_be_enabled();page.locator('[data-iv=recheck]').click();expect(form.locator('[name=confirmed]')).not_to_be_checked();expect(form.locator('[name=quantity]')).to_have_value(str(quantity))
                        form.locator('[name=confirmed]').check();form.locator('[type=submit]').click()
                    expect(page.locator('[data-iv=new-movement]')).to_be_enabled()
                movement('receive',4,conflict=True);assert (item['onHandQty'],item['inTransitQty'])==(4,6)
                movement('consume',2);movement('return',1);assert (batch['onHandQty'],batch['receivedQty'],batch['returnedQty'])==(1,4,1)
                passed('explicit partial receipt, consumption and return; movement conflict requires fresh physical confirmation')
                returned=next(m for m in fixture.movements.values() if m['kind']=='return')
                page.locator(f'[data-iv=reverse][data-id="{returned["id"]}"]').click();form=page.locator('[data-iv-form]');form.locator('[name=reason]').fill('退回记录有误');form.locator('[name=confirmed]').check();form.locator('[type=submit]').click();expect(page.locator('[data-iv=new-movement]')).to_be_enabled()
                assert batch['onHandQty']==2 and batch['returnedQty']==0 and not returned['canReverse']
                movement('receive',6);assert (item['onHandQty'],item['inTransitQty'])==(8,0)
                movement('adjust',-3);assert item['onHandQty']==5
                passed('reversal appends opposite record; remaining receipt and signed correction agree with batch totals')
                page.locator('[data-iv=edit-item]').click();form=page.locator('[data-iv-form]');form.locator('[name=visibility]').select_option('shared');form.locator('[type=submit]').click();expect(page.locator('[data-iv=edit-item]')).to_be_enabled();assert item['visibility']=='shared'
                page.locator('[data-iv=edit-item]').click();form=page.locator('[data-iv-form]');form.locator('[name=visibility]').select_option('private');form.locator('[name=location]').fill('冲突仍保留的草稿');fixture.conflict=True;form.locator('[type=submit]').click()
                expect(page.locator('[data-iv=recheck]')).to_be_enabled()
                expect(form.locator('[name=location]')).to_have_value('冲突仍保留的草稿');page.locator('[data-iv=recheck]').click();expect(form.locator('[name=location]')).to_be_enabled();expect(form.locator('[name=location]')).to_have_value('冲突仍保留的草稿')
                form.locator('[type=submit]').click();expect(page.locator('[data-iv=edit-item]')).to_be_enabled()
                patches=[r['body'] for r in fixture.records if r['method']=='PATCH' and r['path']=='inventory/items/'+item['id']]
                assert patches[-1]['requestId']!=patches[-2]['requestId'] and patches[-1]['revision']==patches[-2]['revision']+1 and item['visibility']=='private'
                passed('owner sharing and withdrawal; definite conflict keeps draft and needs fresh explicit request')
                page.locator('[data-iv=edit-item]').click();form=page.locator('[data-iv-form]');form.locator('[name=location]').fill('结果未知原样重试');fixture.lose_before=True;form.locator('[type=submit]').click();expect(page.locator('[data-iv=retry]')).to_be_enabled();page.locator('[data-iv=retry]').click();expect(page.locator('[data-iv=edit-item]')).to_be_enabled()
                patches=[r['body'] for r in fixture.records if r['method']=='PATCH' and r['path']=='inventory/items/'+item['id']];assert patches[-1]==patches[-2]
                passed('absent receipt after unknown failure retries identical payload and request ID')
                page.locator('[data-iv=edit-item]').click();form=page.locator('[data-iv-form]');form.locator('[name=title]').fill('DOM保留草稿');form.locator('[name=title]').focus()
                page.evaluate("()=>{window.ivInput=document.querySelector('[data-iv-form] [name=title]');ivInput.setSelectionRange(1,4);const n=document.querySelector('#host');n.remove();document.body.append(n);ivInput.focus();InventoryUI.notifyStateChanged();InventoryUI.mount(n)}")
                assert page.evaluate('()=>document.activeElement===ivInput && ivInput.isConnected && ivInput.selectionStart===1 && ivInput.selectionEnd===4')
                expect(form.locator('[name=title]')).to_have_value('DOM保留草稿');page.locator('[data-iv=cancel-form]').click()
                passed('same-tick root reattachment and repeated mount preserve draft node, focus and selection')
                for width,height in [(1440,1000),(820,1100),(390,844),(360,800)]:
                    page.set_viewport_size(dict(width=width,height=height));assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
                    page.screenshot(path=str(out/f'inventory-{width}.png'),full_page=True)
                passed('four viewport widths have no horizontal overflow')
                page.locator('[data-iv=close-detail]').click();page.locator('[data-iv=new-item]').click();form=page.locator('[data-iv-form]');form.locator('[name=title]').fill('合成已有空盒');form.locator('[type=submit]').click();expect(page.locator('[data-iv=new-batch]')).to_be_enabled()
                page.locator('[data-iv=new-batch]').click();form=page.locator('[data-iv-form]');form.locator('[name=kind]').select_option('opening');form.locator('[name=orderedQty]').fill('3');expect(form.locator('[name=orderState]')).to_be_disabled();expect(form.locator('[name=orderedOn]')).to_be_disabled();form.locator('[type=submit]').click();expect(page.locator('[data-iv=new-movement]')).to_be_enabled()
                opening=next(b for b in fixture.batches.values() if b['kind']=='opening');assert opening['onHandQty']==0 and opening['orderState']=='closed' and opening['orderedOn'] is None
                movement('receive',3);movement('dispose',3);fixture.lose_after=True
                page.once('dialog',lambda dialog:dialog.accept());page.locator('[data-iv=archive]').click();expect(page.locator('[data-iv=retry]')).to_be_enabled();page.locator('[data-iv=retry]').click();expect(page.locator('.iv-detail')).to_have_count(0)
                assert len([r for r in fixture.records if r['method']=='DELETE'])==1
                expect(page.locator('#host')).not_to_contain_text('合成已有空盒')
                passed('opening stock requires explicit receipt; disposal and lost archive response never resurrect an item')
                other=fixture.item('家人共享茶叶',owner='member2',visibility='shared')
                other_batch=deepcopy(batch);other_batch.update(id=fixture.identifier(),itemId=other['id'],creator='member2');fixture.batches[other_batch['id']]=other_batch
                page.locator('[data-iv=refresh]').click();expect(page.locator('.iv-card')).to_have_count(2);page.locator(f'[data-iv=select-item][data-id="{other["id"]}"]').click();expect(page.locator('[data-iv=edit-item]')).to_have_count(0)
                page.locator('[data-iv=select-batch]').click();page.locator('[data-iv=edit-batch]').click();form=page.locator('[data-iv-form]');expect(form.locator('[name=orderedQty]')).to_be_disabled();expect(form.locator('[name=warrantyUntil]')).to_be_disabled();form.locator('[name=note]').fill('共享成员实物备注');form.locator('[type=submit]').click();expect(page.locator('[data-iv=edit-batch]')).to_be_enabled()
                patch=next(r['body']['patch'] for r in reversed(fixture.records) if r['method']=='PATCH' and r['path']=='inventory/acquisitions/'+other_batch['id']);assert set(patch)==set(LIMITED)
                other['visibility']='private';page.locator('[data-iv=refresh]').click();expect(page.locator('.iv-detail')).to_have_count(0);expect(page.locator('#host')).not_to_contain_text('家人共享茶叶')
                passed('shared member edits only allowed batch fields; revoked item clears old DOM')
                for index in range(27):fixture.item('分页合成 '+str(index))
                page.locator('[data-iv=refresh]').click();expect(page.locator('.iv-card')).to_have_count(24);page.locator('[data-iv=items-next]').click();expect(page.locator('.iv-card')).to_have_count(4)
                page.locator('[data-iv-filters] [name=q]').fill('分页合成 26');page.locator('[data-iv-filters] [type=submit]').click();expect(page.locator('.iv-card')).to_have_count(1)
                passed('bounded pagination and search can reach item beyond first page')
                fixture.hold=True;page.locator('[data-iv=refresh]').click()
                for _ in range(60):
                    if fixture.started.is_set():break
                    page.wait_for_timeout(50)
                assert fixture.started.is_set()
                fixture.actor='member2';page.evaluate('switchIdentity()');fixture.release.set();expect(page.locator('#host')).to_contain_text('成员或家庭已变化');page.wait_for_timeout(200);expect(page.locator('.iv-card,.iv-detail,[data-iv-form]')).to_have_count(0)
                passed('late response cannot restore prior household private rows or draft')
                before=len(fixture.records);page.evaluate("()=>{isTV=true;InventoryUI.mount(document.querySelector('#host'));}");expect(page.locator('#host')).to_contain_text('不向电视展示明细');assert len(fixture.records)==before
                passed('TV mount refuses inventory reads and detail UI')
                assert not report['pageErrors'] and not report['externalRequests'];report['passed']=True
            finally:fixture.release.set();browser.close()
    except Exception:report['failure']=traceback.format_exc();print(report['failure'],flush=True)
    finally:
        fixture.release.set();server.shutdown();server.server_close();thread.join(timeout=5)
        report['sourceHashesAfter']=digest();report['sourceUnchanged']=report['sourceHashesBefore']==report['sourceHashesAfter'];report['passed']=report['passed'] and report['sourceUnchanged'] and not thread.is_alive()
        (out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(dict(passed=report['passed'],checks=len(report['checks']),report=str(out/'result.json')),ensure_ascii=False),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
