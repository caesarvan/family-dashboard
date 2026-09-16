"""Real Edge UI against a synthetic API contract; no Google or production access.

Deliberately simulates committed requests with lost responses. Backend permission,
storage and provider verification are separate from these browser checks.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from pathlib import Path
import threading

from flask import Flask, jsonify, request, send_file
from PIL import Image
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server, WSGIRequestHandler

ROOT = Path(__file__).resolve().parents[1]
OWN, SHARED, IMPORT, CANDIDATE, JOURNEY, TV = [str(i)*24 for i in range(1,7)]
ACCOUNT = 'a'*32
HTML = '''<!doctype html><html lang="zh-CN" data-theme="light"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="/static/household-media.css">
<style>body{margin:20px;background:#fafafa}main{max-width:1280px;margin:auto}</style>
<main id="host"></main><script>
let user=null,csrf='',isTV=false,isDemo=false;
const canEdit=()=>user?.role==='member'&&!isTV&&!isDemo;
async function api(path,options={}){const response=await fetch('/api'+path,{credentials:'same-origin',cache:'no-store',...options,
headers:{'Content-Type':'application/json','X-CSRF-Token':csrf}});const result=await response.json();
if(!response.ok){const error=new Error(result.error);error.status=response.status;throw error;}return result;}
const write=(path,method,payload)=>api(path,{method,body:JSON.stringify(payload)});
window.switchLocal=()=>{user={id:'member2',householdId:'synthetic-home',auth_version:1,role:'member'};csrf='synthetic-member2';HouseholdMedia.notifyIdentityChanged();};
</script><script src="/static/household-media.js"></script><script>
api('/me').then(me=>{user=me.user;csrf=me.csrf;HouseholdMedia.mount(document.querySelector('#host'));});
</script></html>'''


class Quiet(WSGIRequestHandler):
    def log(self, *_args, **_kwargs):
        pass


def photo(identifier, own=True, **changes):
    value = dict(id=identifier, revision=1, caption='合成私密回忆' if own else '合成共享照片',
                 canManage=own, visibility='private' if own else 'shared', journey=None,
                 width=600, height=400, contentType='image/jpeg', previewUrl=f'/api/media/items/{identifier}/preview')
    value.update(changes)
    return value


class Fixture:
    def __init__(self):
        self.actor = 'member1'
        self.items = {OWN:photo(OWN), SHARED:photo(SHARED,False)}
        self.imports = {}
        self.receipts = {}
        self.confirm_receipts = {}
        self.records = []
        self.grants = {OWN:[]}
        self.fail_create = True
        self.fail_confirm = True
        self.conflict_patch = False
        self.hold_gallery = False
        self.started = threading.Event()
        self.release = threading.Event()
        image = Image.new('RGB',(600,400),(157,184,180))
        stream = BytesIO(); image.save(stream,format='JPEG'); self.jpeg = stream.getvalue()

    def create_app(self):
        app = Flask(__name__,static_folder=str(ROOT/'static'))

        @app.get('/')
        def index():
            return HTML

        @app.route('/api/<path:path>',methods=['GET','POST','PATCH','DELETE','PUT'])
        def api(path):
            body = request.get_json(silent=True) or {}
            self.records.append(dict(path=path,method=request.method,body=deepcopy(body)))
            if path=='me':
                return jsonify(user=dict(id=self.actor,householdId='synthetic-home',role='member',auth_version=1),csrf='synthetic-'+self.actor)
            if path=='accounts':
                return jsonify(accounts=[dict(id=ACCOUNT,provider='google',name='合成照片账户',needsReauth=False,capabilities=dict(photos=True))])
            if path=='journeys':
                return jsonify(journeys=[dict(id=JOURNEY,trip=dict(id='trip-synthetic',title='合成旅行'))])
            if path=='devices':
                return jsonify([dict(id=TV,name='合成客厅电视')])
            if path=='media/imports' and request.method=='GET':
                return jsonify(items=list(self.imports.values()),total=len(self.imports))
            if path=='media/imports' and request.method=='POST':
                assert body['accountId']==ACCOUNT and body['allowTemporaryProcessing'] and body['consentVersion']=='media-v1'
                if body['requestId'] not in self.receipts:
                    now=datetime.now(timezone.utc)
                    self.imports[IMPORT]=dict(id=IMPORT,revision=1,state='awaiting_confirmation',createdAt=now.isoformat(),expiresAt=(now+timedelta(hours=24)).isoformat(),nextPollAt=(now+timedelta(minutes=1)).isoformat(),counts=dict(selected=1,ready=1,skipped=0,failed=0),canConfirm=True)
                    self.receipts[body['requestId']]=IMPORT
                if self.fail_create:
                    self.fail_create=False
                    return jsonify(error='合成测试：创建结果未收到，请重试。'),503
                return jsonify({'import':self.imports[IMPORT],'replayed':True})
            if path==f'media/imports/{IMPORT}' and request.method=='GET':
                return jsonify({'import':self.imports[IMPORT], 'items':[dict(id=CANDIDATE,status='successful',item=photo(CANDIDATE,caption='待确认合成照片'))]})
            if path==f'media/imports/{IMPORT}/confirm':
                assert body['persistSelected'] and body['itemIds']==[CANDIDATE]
                if body['confirmRequestId'] not in self.confirm_receipts:
                    self.items[CANDIDATE]=photo(CANDIDATE,caption='已保存合成照片')
                    self.grants[CANDIDATE]=[]
                    self.confirm_receipts[body['confirmRequestId']]=deepcopy(body)
                    self.imports[IMPORT].update(state='confirmed',revision=2,canConfirm=False)
                else:
                    assert body==self.confirm_receipts[body['confirmRequestId']]
                if self.fail_confirm:
                    self.fail_confirm=False
                    return jsonify(error='合成测试：保存结果未收到，请重试。'),503
                return jsonify({'import':self.imports[IMPORT],'itemIds':[CANDIDATE],'replayed':True})
            if path=='media/items':
                if self.hold_gallery:
                    self.started.set(); self.release.wait(10)
                scope=request.args.get('scope')
                values=[v for v in self.items.values() if scope=='visible' or (scope=='mine' and v['canManage']) or (scope=='shared' and v['visibility']=='shared')]
                return jsonify(items=values,total=len(values),hasMore=False)
            if path.startswith('media/items/'):
                parts=path.split('/');uid=parts[2]
                if len(parts)==4 and parts[3]=='preview':
                    return send_file(BytesIO(self.jpeg),mimetype='image/jpeg',max_age=0)
                item=self.items.get(uid)
                if not item:
                    return jsonify(error='照片已移除或不再共享。'),404
                if len(parts)==4 and parts[3]=='tv-grants':
                    if request.method=='PUT':
                        assert body['revision']==item['revision']
                        if body['deviceIds']:
                            assert body['allowTvDisplay'] and body['consentVersion']=='media-v1'
                        self.grants[uid]=body['deviceIds'];item['revision']+=1
                    return jsonify(deviceIds=self.grants.get(uid,[]),revision=item['revision'])
                if request.method=='PATCH':
                    if self.conflict_patch:
                        self.conflict_patch=False;item['revision']+=1
                        return jsonify(error='合成测试：其他设备已修改。'),409
                    assert body['revision']==item['revision']
                    unlinked=item['journey'] is not None and body['journeyId'] is None
                    item.update(caption=body['caption'],visibility='private' if unlinked else body['visibility'],journey=dict(id=JOURNEY,tripId='trip-synthetic',title='合成旅行') if body['journeyId'] else None,revision=item['revision']+1)
                    if item['visibility']=='private': self.grants[uid]=[]
                if request.method=='DELETE':
                    del self.items[uid]
                    return jsonify(deleted=True)
                return jsonify(item=item)
            return jsonify(error='合成接口未实现。'),404
        return app


def main():
    out=ROOT/'test-results'/'media-ui';out.mkdir(parents=True,exist_ok=True)
    fixture=Fixture();server=make_server('127.0.0.1',0,fixture.create_app(),threaded=True,request_handler=Quiet)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    results=[];errors=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
            context=browser.new_context(viewport=dict(width=1440,height=1000))
            page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}/')
            expect(page.locator('.hm-card')).to_have_count(1)
            expect(page.locator('[data-hm-temporary]')).not_to_be_checked()
            page.locator('[data-hm=create]').click()
            expect(page.locator('[data-hm-message]')).to_contain_text('请先确认临时处理')
            assert not any(r['method']=='POST' for r in fixture.records)
            results.append('temporary consent required before creating selection')
            page.locator('[data-hm-temporary]').check();page.locator('[data-hm=create]').click()
            expect(page.locator('[data-hm-message]')).to_contain_text('创建结果未收到')
            page.locator('[data-hm=create]').click()
            expect(page.locator('[data-hm-import]')).to_contain_text('等待你确认保存')
            posts=[r for r in fixture.records if r['path']=='media/imports' and r['method']=='POST']
            assert len(posts)==2 and posts[0]['body']==posts[1]['body'] and len(fixture.receipts)==1
            results.append('uncertain create retries original id and payload')
            page.locator('[data-hm-candidate]').check();page.locator('[data-hm=confirm]').click()
            expect(page.locator('[data-hm-message]')).to_contain_text('确认保存到私密相册')
            assert not fixture.confirm_receipts
            page.locator('[data-hm-persist]').check();page.locator('[data-hm=confirm]').click()
            expect(page.locator('[data-hm-message]')).to_contain_text('保存结果未收到')
            expect(page.locator('[data-hm-candidate]')).to_be_disabled()
            page.locator('[data-hm=confirm]').click()
            expect(page.locator('.hm-card')).to_have_count(2)
            assert len(fixture.confirm_receipts)==1
            confirms=[r for r in fixture.records if r['path'].endswith('/confirm')]
            assert len(confirms)==2 and confirms[0]['body']==confirms[1]['body']
            results.append('persist consent and same confirmation receipt after lost response')
            page.locator(f'[data-hm=detail][data-id="{OWN}"]').click()
            expect(page.locator('[data-hm-editor]')).to_be_visible()
            page.locator('[data-hm-editor] [name=caption]').fill('<img src=x onerror=alert(1)> 我的草稿')
            fixture.conflict_patch=True
            page.locator('[data-hm-editor] [type=submit]').click()
            expect(page.locator('[data-hm=reload-detail]')).to_be_visible()
            expect(page.locator('[data-hm-editor] [name=caption]')).to_have_value('<img src=x onerror=alert(1)> 我的草稿')
            page.locator('[data-hm=reload-detail]').click()
            expect(page.locator('[data-hm=reload-detail]')).to_have_count(0)
            expect(page.locator('[data-hm-editor] [name=caption]')).to_have_value('<img src=x onerror=alert(1)> 我的草稿')
            page.locator('[data-hm-editor] [name=journeyId]').select_option(JOURNEY)
            page.locator('[data-hm-editor] [name=visibility]').select_option('shared')
            page.locator('[data-hm-editor] [type=submit]').click()
            expect(page.locator('[data-hm-message]')).to_contain_text('照片信息已保存')
            assert fixture.items[OWN]['visibility']=='shared' and fixture.items[OWN]['journey']['id']==JOURNEY
            assert not page.locator('img[onerror]').count()
            results.append('409 keeps draft; explicit reload preserves input and escapes caption')
            page.locator('[data-hm-device]').check();page.locator('[data-hm=save-grants]').click()
            expect(page.locator('[data-hm-message]')).to_contain_text('请确认允许')
            assert fixture.grants[OWN]==[]
            page.locator('[data-hm-tv-consent]').check();page.locator('[data-hm=save-grants]').click()
            expect(page.locator('[data-hm-message]')).to_contain_text('电视展示范围已保存')
            assert fixture.grants[OWN]==[TV]
            results.append('TV consent is separate from household sharing')
            page.locator('[data-hm-editor] [name=journeyId]').select_option('')
            page.locator('[data-hm-editor] [type=submit]').click()
            expect(page.locator('[data-hm-editor] [name=visibility]')).to_have_value('private')
            expect(page.locator('[data-hm-device]')).not_to_be_checked()
            assert fixture.grants[OWN]==[]
            results.append('unlink response updates private state and revoked TV selection')
            page.locator('[data-hm-editor] [name=caption]').fill('刷新后保留草稿')
            page.locator('[data-hm=refresh]').click()
            expect(page.locator('[data-hm-editor] [name=caption]')).to_have_value('刷新后保留草稿')
            results.append('refresh preserves in-memory editor draft')
            page.locator('[data-hm=close-detail]').click()
            for width,height in [(1440,1000),(820,1100),(390,844),(360,800)]:
                page.set_viewport_size(dict(width=width,height=height))
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
                page.screenshot(path=str(out/f'media-{width}.png'),full_page=True)
            results.append('four viewport widths have no horizontal overflow')
            page.set_viewport_size(dict(width=1440,height=1000))
            page.locator('[data-hm-filters] [name=scope]').select_option('shared')
            page.locator('[data-hm-filters] [type=submit]').click()
            expect(page.locator('.hm-card')).to_have_count(1)
            page.locator('[data-hm=detail]').click()
            expect(page.locator('.hm-detail')).to_contain_text('由上传者管理')
            expect(page.locator('[data-hm-editor]')).to_have_count(0)
            del fixture.items[SHARED]
            page.locator('[data-hm=refresh]').click()
            expect(page.locator('.hm-detail')).to_have_count(0)
            expect(page.locator('.hm-card')).to_have_count(0)
            results.append('shared item read only; revocation clears old detail')
            fixture.items[OWN]['previewUrl']='https://untrusted.invalid/private.jpg'
            page.locator('[data-hm-filters] [name=scope]').select_option('mine')
            page.locator('[data-hm-filters] [type=submit]').click()
            expect(page.locator('.hm-card')).to_have_count(2)
            expect(page.locator('img[src^="https:"]')).to_have_count(0)
            results.append('only exact same-origin local preview URLs are loaded')
            fixture.hold_gallery=True
            page.locator('[data-hm=refresh]').click()
            assert fixture.started.wait(3)
            fixture.actor='member2';page.evaluate('switchLocal()');fixture.release.set()
            expect(page.locator('#host')).to_contain_text('登录成员或家庭已变化')
            page.wait_for_timeout(200)
            assert not page.locator('.hm-card,.hm-detail,.hm-candidate').count()
            results.append('late response cannot restore private DOM after identity change')
            assert not errors,errors
            browser.close()
    finally:
        fixture.release.set();server.shutdown();thread.join(timeout=3)
        (out/'result.json').write_text(json.dumps(dict(checks=results,pageErrors=errors,coverage='Synthetic API contract in real Edge; no actual backend, Google grant or television.'),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(passed=len(results),checks=results),ensure_ascii=False))


if __name__=='__main__':
    main()
