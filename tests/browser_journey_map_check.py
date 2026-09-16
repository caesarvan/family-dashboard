"""Real Edge/DOM against a synthetic loopback API contract, NOT the new backend.

Uses only the candidate JS/CSS and a read-only git copy of the reviewed-by-root
land candidate. No real accounts, household database, providers or outside IO.
The in-memory fixture deliberately accepts writes before returning failures.
Root must separately combine this UI with the actual journey-places backend.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import threading
import traceback
from unittest.mock import patch
from urllib.parse import urlsplit

from flask import Flask, Response, jsonify, request, send_file
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server, WSGIRequestHandler

ROOT = Path(__file__).resolve().parents[1]
LAND_COMMIT = '05855471f407d41337a842e1fea05c76dddc03f0'
TRIP = 'a' * 24
OWN, SHARED, UNLOCATED = '1' * 24, '2' * 24, '3' * 24
HTML = '''<!doctype html><html lang="zh-CN" data-theme="light"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="/static/journey-map.css">
<style>body{margin:16px}dialog{width:min(1200px,95vw);max-width:95vw;padding:0}</style>
<main id="host"></main><dialog id="dialog"><div id="modal-body"></div></dialog>
<script>
let user=null,csrf='',isTV=new URLSearchParams(location.search).has('tv'),isDemo=false;
const canEdit=()=>user?.role==='member'&&!isTV&&!isDemo;
async function api(path,options={}){const response=await fetch('/api'+path,{credentials:'same-origin',cache:'no-store',...options,
 headers:{'Content-Type':'application/json','X-CSRF-Token':csrf,...(isTV?{'X-Display-Mode':'tv'}:{})}});
 const result=await response.json();if(!response.ok){const error=new Error(result.error);error.status=response.status;throw error;}return result;}
function openModal(title,html){document.querySelector('#modal-body').innerHTML=html;document.querySelector('#dialog').showModal();}
window.opened=[];
window.mountMap=()=>JourneyMap.mount(document.querySelector('#host'),{openJourney:(id,context)=>{opened.push({id,...context});}});
window.switchLocal=(id,household='synthetic-home')=>{user={id,householdId:household,role:'member',auth_version:1};csrf='synthetic-'+id;JourneyMap.notifyIdentityChanged();};
</script><script src="/static/journey-map.js"></script><script>
api('/me').then(me=>{user=me.user;csrf=me.csrf;mountMap();});
</script></html>'''


class Quiet(WSGIRequestHandler):
    def log(self, *_args, **_kwargs):
        pass


def place(identifier, name, owner='member1', **changes):
    value = dict(id=identifier, name=name, owner=owner, country='合成国家', city='合成城市',
                 coordinates={'latitude':31.234567,'longitude':121.456789},
                 coordinateDisclosure='hidden', status='wish', journeyId=None, journey=None,
                 startDate=None, endDate=None, visibility='private', visitedConfirmedAt=None,
                 visitedConfirmedBy=None, revision=1, createdAt='2026-09-16T00:00:00Z',
                 updatedAt='2026-09-16T00:00:00Z')
    value.update(changes)
    return value


class Fixture:
    """Small contract double; intentionally not an implementation of auth/schema."""
    def __init__(self):
        self.actor = 'member1'
        self.rows = {
            OWN: place(OWN,'合成私密到访',status='visited',visibility='shared',coordinateDisclosure='coarse',
                       startDate='2026-09-01',endDate='2026-09-03',journeyId=TRIP,
                       journey={'id':TRIP,'tripId':'trip-synthetic','title':'合成旅行'},
                       visitedConfirmedAt='2026-09-16T00:00:00Z',visitedConfirmedBy='member1'),
            SHARED: place(SHARED,'合成共享心愿','member2',visibility='shared',coordinateDisclosure='coarse'),
            UNLOCATED: place(UNLOCATED,'合成无坐标计划',coordinates=None,status='planned')}
        self.requests, self.receipts, self.tombstones = [], {}, {}
        self.fail_post_after_commit = False
        self.fail_detail = 0
        self.fail_list = 0
        self.fail_journeys = False
        self.fail_patch_after_commit = False
        self.fail_delete_after_commit = False
        self.hold_list = False
        self.hold_post = False
        self.started, self.release = threading.Event(), threading.Event()
        self.counter = 10

    def projection(self, value):
        p = deepcopy(value)
        coordinate = p['coordinates']
        disclosure = p['coordinateDisclosure']
        shared = None if not coordinate or disclosure == 'hidden' else {
            k:round(v,1) if disclosure == 'coarse' else v for k,v in coordinate.items()}
        precision = 'none' if not coordinate else 'hidden' if disclosure == 'hidden' else 'approximate' if disclosure == 'coarse' else 'exact'
        manage = p['owner'] == self.actor
        p.update(canManage=manage,coordinatePrecision='exact' if coordinate else 'none',coordinateGridDegrees=None)
        if manage:
            p.update(sharedCoordinates=shared,sharedCoordinatePrecision=precision,
                     sharedCoordinateGridDegrees=0.1 if precision=='approximate' else None)
        else:
            p.update(coordinates=shared,coordinatePrecision=precision,coordinateGridDegrees=0.1 if precision=='approximate' else None)
        return p

    def wait(self):
        self.started.set()
        if not self.release.wait(15):
            raise AssertionError('Fixture hold timed out')

    def app(self):
        app = Flask(__name__,static_folder=None)
        static_asset = ROOT/'static/journey-map-land.geojson'
        land = static_asset.read_bytes() if static_asset.exists() else subprocess.check_output(
            ['git','show',LAND_COMMIT+':static/journey-map-land.geojson'],cwd=ROOT)
        self.land_hash = hashlib.sha256(land).hexdigest()

        @app.route('/')
        def index():
            return Response(HTML,mimetype='text/html')

        @app.route('/static/<name>')
        def assets(name):
            if name == 'journey-map-land.geojson':
                return Response(land,mimetype='application/geo+json')
            if name in ('journey-map.js','journey-map.css'):
                return send_file(ROOT/'static'/name)
            return '',404

        @app.before_request
        def count():
            if request.path.startswith('/api/'):
                self.requests.append({'method':request.method,'path':request.full_path,
                                      'body':request.get_json(silent=True),'actor':self.actor})

        @app.route('/api/me')
        def me():
            return jsonify(user={'id':self.actor,'role':'member','householdId':'synthetic-home','auth_version':1},
                           csrf='synthetic-'+self.actor)

        @app.route('/api/state')
        def state():
            return jsonify(people=[{'id':'member1','name':'合成成员一'},{'id':'member2','name':'合成成员二'}])

        @app.route('/api/journeys')
        def journeys():
            if self.fail_journeys:
                return jsonify(error='合成旅行选项暂不可用'),503
            return jsonify(journeys=[{'id':TRIP,'tripId':'trip-synthetic','trip':{'title':'合成旅行'}}])

        @app.route('/api/journey-places',methods=['GET','POST'])
        def places():
            if request.headers.get('X-Display-Mode') == 'tv':
                return jsonify(error='电视不可访问'),403
            if request.method == 'GET':
                if self.fail_list:
                    self.fail_list -= 1
                    return jsonify(error='合成暂时故障'),503
                rows = [self.projection(p) for p in self.rows.values() if p['owner']==self.actor or p['visibility']=='shared']
                for key in ('status','owner','journeyId'):
                    if request.args.get(key):
                        rows = [p for p in rows if p[key]==request.args[key]]
                year = request.args.get('year')
                if year:
                    rows = [p for p in rows if p['startDate'] and p['startDate'][:4]<=year<=(p['endDate'] or p['startDate'])[:4]]
                if request.args.get('scope')=='mine':
                    rows = [p for p in rows if p['owner']==self.actor]
                if request.args.get('scope')=='shared':
                    rows = [p for p in rows if p['visibility']=='shared']
                offset,limit = int(request.args.get('offset',0)),int(request.args.get('limit',100))
                result = {'items':rows[offset:offset+limit],'total':len(rows),'offset':offset,'limit':limit,'hasMore':offset+limit<len(rows)}
                if self.hold_list:
                    self.hold_list = False
                    self.wait()
                return jsonify(result)
            data = request.get_json()
            receipt = (self.actor,data['requestId'])
            if receipt in self.receipts:
                identifier, original = self.receipts[receipt]
                if data != original:
                    return jsonify(error='请求标识已用于不同内容'),409
                if identifier not in self.rows:
                    return jsonify(error='记录已删除'),410
                return jsonify(place=self.projection(self.rows[identifier]),replayed=True)
            self.counter += 1
            identifier = format(self.counter,'024x')
            value = place(identifier,data['name'],self.actor)
            value.update({k:v for k,v in data.items() if k not in ('requestId','confirmVisited')})
            if data['status']=='visited':
                assert data['confirmVisited']
                value.update(visitedConfirmedAt='2026-09-16T00:00:00Z',visitedConfirmedBy=self.actor)
            self.rows[identifier] = value
            self.receipts[receipt] = identifier,deepcopy(data)
            if self.hold_post:
                self.hold_post = False
                self.wait()
            if self.fail_post_after_commit:
                self.fail_post_after_commit = False
                return jsonify(error='合成响应中断，提交结果未知'),503
            return jsonify(place=self.projection(value),replayed=False),201

        @app.route('/api/journey-places/<identifier>',methods=['GET','PATCH','DELETE'])
        def item(identifier):
            if request.method=='DELETE' and identifier in self.tombstones:
                revision=request.get_json()['revision']
                assert revision==self.tombstones[identifier]
                return jsonify(deleted=True,id=identifier,revision=revision+1,replayed=True)
            p = self.rows.get(identifier)
            if not p or p['owner']!=self.actor and p['visibility']!='shared':
                return jsonify(error='地点不可访问'),404
            if request.method=='GET':
                if self.fail_detail:
                    self.fail_detail -= 1
                    return jsonify(error='合成读回失败'),503
                return jsonify(place=self.projection(p))
            if p['owner']!=self.actor:
                return jsonify(error='仅记录者可修改'),403
            data = request.get_json()
            if data['revision']!=p['revision']:
                return jsonify(error='版本冲突，请重新读取'),409
            if request.method=='DELETE':
                self.tombstones[identifier] = data['revision']
                del self.rows[identifier]
                if self.fail_delete_after_commit:
                    self.fail_delete_after_commit=False
                    return jsonify(error='合成删除响应中断'),503
                return jsonify(deleted=True,id=identifier,revision=data['revision']+1,replayed=False)
            p.update({k:v for k,v in data.items() if k not in ('revision','confirmVisited')})
            p['revision'] += 1
            if self.fail_patch_after_commit:
                self.fail_patch_after_commit=False
                return jsonify(error='合成修改响应中断'),503
            return jsonify(place=self.projection(p))

        return app


def sources():
    paths = list(ROOT.glob('*.py'))
    for folder in ('static','deploy'):
        paths += [p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    paths += [Path(__file__)]
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def main():
    out = ROOT/'test-results/journey-map-ui'
    out.mkdir(parents=True,exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%dT%H%M%S%f')
    report_path = out/(stamp+'-report.json')
    report = {'passed':False,'scope':'Real Edge DOM with synthetic in-memory loopback API; actual new backend NOT tested',
              'checks':[],'pageErrors':[],'externalRequests':[],'screenshots':[],
              'sourceHashes':sources(),'realPrivateInputs':0,'productionWrites':0,'providerCalls':0}
    fixture, server, browser = Fixture(), None, None
    original_connect, original_dns = socket.socket.connect,socket.getaddrinfo
    def allowed(host):
        return host in ('127.0.0.1','localhost','::1',b'127.0.0.1',b'localhost',b'::1')
    def connect(sock,address):
        if isinstance(address,tuple) and not allowed(address[0]):
            report['externalRequests'].append('socket'); raise AssertionError('Outside socket')
        return original_connect(sock,address)
    def dns(host,*args,**kwargs):
        if host is not None and not allowed(host):
            report['externalRequests'].append('dns'); raise AssertionError('Outside DNS')
        return original_dns(host,*args,**kwargs)
    def passed(name):
        report['checks'].append(name);print('PASS '+name,flush=True)
    def writes(method):
        return [r for r in fixture.requests if r['method']==method]
    try:
        app = fixture.app()
        report['landAssetSha256'] = fixture.land_hash
        with patch.object(socket.socket,'connect',connect),patch.object(socket,'getaddrinfo',dns),sync_playwright() as playwright:
            server = make_server('127.0.0.1',0,app,threaded=True,request_handler=Quiet)
            threading.Thread(target=server.serve_forever,daemon=True).start()
            base = 'http://127.0.0.1:'+str(server.server_port)
            browser = playwright.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True)
            context = browser.new_context(viewport={'width':1440,'height':1100},reduced_motion='reduce')
            def route(r):
                if urlsplit(r.request.url).hostname not in ('127.0.0.1','localhost'):
                    report['externalRequests'].append(r.request.url);r.abort()
                else:
                    r.continue_()
            context.route('**/*',route)
            page = context.new_page()
            page.on('pageerror',lambda e:report['pageErrors'].append(str(e)))
            page.on('dialog',lambda dialog:dialog.accept())
            def ready():
                expect(page.locator('.jm-status')).not_to_contain_text('正在读取')
                expect(page.locator('[data-jm=new]')).to_be_enabled()
            def select(identifier):
                page.locator('.jm-list [data-id="'+identifier+'"]').click()
            def new(name):
                page.locator('[data-jm=new]').click()
                page.locator('[data-jm-editor] [name=name]').fill(name)
            def save():
                page.locator('[data-jm-editor] button[type=submit]').click()
            def cancel():
                page.locator('[data-jm=cancel]').click()
            def held():
                # Keep Playwright's route callbacks pumping while HTTP is held.
                for _ in range(50):
                    if fixture.started.is_set():
                        return
                    page.wait_for_timeout(100)
                raise AssertionError('Fixture request did not start')
            page.goto(base)
            expect(page.locator('.jm-list .jm-place')).to_have_count(3)
            ready()
            expect(page.locator('.jm-land')).to_have_count(1)
            expect(page.locator('.jm-status')).to_contain_text('其中 1 条无可见坐标')
            assert page.locator('.jm-marker').count()==2
            passed('same-origin real Natural Earth asset; three statuses; explicit current-page and no-coordinate counts')

            select(SHARED)
            expect(page.locator('.jm-detail')).to_contain_text('31.200000, 121.500000')
            expect(page.locator('.jm-detail')).not_to_contain_text('31.234567')
            expect(page.locator('[data-jm=edit]')).to_have_count(0)
            passed('shared other member is read-only and renders only projected coarse coordinate')
            select(OWN)
            expect(page.locator('.jm-detail')).to_contain_text('31.234567, 121.456789')
            expect(page.locator('.jm-detail')).to_contain_text('31.200000, 121.500000')
            page.locator('[data-jm=journey]').click()
            page.wait_for_function('opened.length===1')
            assert page.evaluate('opened[0]')=={'id':TRIP,'placeId':OWN}
            passed('owner retains exact coordinate and shared preview; bridge receives workflow ID and place ID')

            new('合成新增已到访')
            form = page.locator('[data-jm-editor]')
            expect(form.locator('[name=visibility]')).to_have_value('private')
            expect(form.locator('[name=coordinateDisclosure]')).to_have_value('hidden')
            page.locator('[data-jm=pick]').click()
            svg = page.locator('[data-jm-map] svg')
            expect(svg).to_be_focused()
            page.keyboard.press('ArrowRight');page.keyboard.press('ArrowUp');page.keyboard.press('Enter')
            expect(form.locator('[name=latitude]')).to_have_value('1')
            expect(form.locator('[name=longitude]')).to_have_value('1')
            form.locator('[name=status]').select_option('visited')
            before = len(writes('POST'));save()
            expect(form.locator('.jm-error')).to_contain_text('明确确认')
            assert len(writes('POST'))==before
            form.locator('[name=confirmVisited]').check();save()
            expect(page.locator('[data-jm-editor]')).to_have_count(0);ready()
            assert len(writes('POST'))==before+1
            created = next(p for p in fixture.rows.values() if p['name']=='合成新增已到访')
            assert created['coordinates']=={'latitude':1,'longitude':1}
            page.reload();ready();expect(page.locator('.jm-list')).to_contain_text('合成新增已到访')
            passed('private/hidden defaults; keyboard point picking; explicit visited confirmation; API write survives browser reload')

            fixture.fail_post_after_commit=True
            new('合成创建未知结果');save()
            expect(form.locator('.jm-error')).to_contain_text('合成响应中断')
            expect(page.locator('[data-jm=retry-pending]')).to_be_enabled()
            expect(page.locator('[data-jm-editor] [name=name]')).to_be_disabled()
            sent = deepcopy(writes('POST')[-1]['body'])
            page.locator('[data-jm=retry-pending]').click()
            expect(page.locator('[data-jm-editor]')).to_have_count(0);ready()
            assert writes('POST')[-1]['body']==sent
            assert len([p for p in fixture.rows.values() if p['name']=='合成创建未知结果'])==1
            passed('accepted create followed by 503 retries exact payload/requestId without duplicate fixture record')

            fixture.fail_detail=1
            new('合成保存后读回失败');before=len(writes('POST'));save()
            expect(page.locator('[data-jm=read-saved]')).to_be_visible()
            expect(page.locator('[data-jm-editor] .jm-error')).to_contain_text('不会再次创建')
            page.locator('[data-jm=read-saved]').click()
            expect(page.locator('[data-jm-editor]')).to_have_count(0);ready()
            assert len(writes('POST'))==before+1
            passed('confirmed create plus failed readback offers GET-only retry')

            select(UNLOCATED);page.locator('[data-jm=edit]').click()
            form.locator('[name=name]').fill('合成保留的修改草稿')
            fixture.rows[UNLOCATED].update(name='合成别处更新',revision=2)
            before=len(writes('PATCH'));save()
            expect(form.locator('.jm-error')).to_contain_text('版本冲突')
            expect(page.locator('[data-jm=retry-pending]')).to_be_enabled()
            page.locator('[data-jm=retry-pending]').click()
            expect(page.locator('.jm-conflict')).to_contain_text('合成别处更新')
            expect(form.locator('[name=name]')).to_have_value('合成保留的修改草稿')
            expect(form.locator('button[type=submit]')).to_be_disabled()
            assert len(writes('PATCH'))==before+1
            page.locator('[data-jm=keep-draft]').click()
            expect(form.locator('[name=name]')).to_have_value('合成保留的修改草稿')
            save();expect(page.locator('[data-jm-editor]')).to_have_count(0);ready()
            assert writes('PATCH')[-1]['body']['revision']==2
            assert fixture.rows[UNLOCATED]['name']=='合成保留的修改草稿'
            passed('revision conflict reads latest; retains draft; no save until explicit choice; explicit second PATCH')

            select(UNLOCATED);page.locator('[data-jm=edit]').click()
            form.locator('[name=city]').fill('合成更新城市')
            fixture.fail_patch_after_commit=True;save()
            expect(form.locator('.jm-error')).to_contain_text('合成修改响应中断')
            expect(page.locator('[data-jm=retry-pending]')).to_be_enabled()
            before=len(writes('PATCH'));page.locator('[data-jm=retry-pending]').click()
            expect(page.locator('[data-jm=use-latest]')).to_be_visible()
            assert len(writes('PATCH'))==before
            page.locator('[data-jm=use-latest]').click()
            expect(form.locator('[name=city]')).to_have_value('合成更新城市')
            cancel()
            passed('uncertain PATCH reads current version without automatically repeating a mutation')

            filters=page.locator('[data-jm-filters]')
            filters.locator('[name=status]').select_option('visited')
            filters.locator('[name=year]').fill('2026')
            filters.locator('[name=owner]').select_option('member1')
            filters.locator('[name=journeyId]').select_option(TRIP)
            filters.locator('[name=scope]').select_option('mine')
            filters.locator('button[type=submit]').click();ready()
            expect(page.locator('.jm-list .jm-place')).to_have_count(1)
            assert 'year=2026' in next(r['path'] for r in reversed(fixture.requests) if r['path'].startswith('/api/journey-places?'))
            page.locator('[data-jm=reset]').click();ready()
            fixture.fail_list=1
            new('合成筛选失败保留草稿')
            filters.locator('button[type=submit]').click();ready()
            expect(page.locator('.jm-error').first).to_contain_text('合成暂时故障')
            expect(page.locator('.jm-list .jm-place')).to_have_count(0)
            expect(form.locator('[name=name]')).to_have_value('合成筛选失败保留草稿')
            page.locator('[data-jm=refresh]').click();ready();cancel()
            passed('all five filter values reach API; failed filter clears stale page and preserves editor draft')

            for n in range(101):
                identifier=format(1000+n,'024x')
                fixture.rows[identifier]=place(identifier,'合成分页地点 '+str(n),coordinates=None)
            page.evaluate('mountMap()');ready()
            expect(page.locator('.jm-list .jm-place')).to_have_count(100)
            page.locator('[data-jm=next]').click();ready()
            expect(page.locator('.jm-pagination')).to_contain_text('第 2 页')
            assert page.locator('.jm-list .jm-place').count()==len(fixture.rows)-100
            expect(page.locator('.jm-marker')).to_have_count(0)
            page.locator('[data-jm=previous]').click();ready()
            passed('pagination replaces current map/list instead of presenting unrequested points')

            select(UNLOCATED);page.locator('[data-jm=edit]').click()
            page.locator('[data-jm=delete]').click()
            expect(page.locator('.jm-conflict')).to_contain_text('关联旅行保留')
            fixture.fail_delete_after_commit=True
            page.locator('[data-jm=confirm-delete]').click()
            expect(form.locator('.jm-error')).to_contain_text('合成删除响应中断')
            original_delete=deepcopy(writes('DELETE')[-1]['body'])
            page.locator('[data-jm=retry-pending]').click()
            expect(page.locator('[data-jm-editor]')).to_have_count(0);ready()
            assert UNLOCATED not in fixture.rows
            assert writes('DELETE')[-1]['body']==original_delete
            assert page.locator('[data-jm-filters] [name=journeyId] option[value="'+TRIP+'"]').count()==1
            passed('explicit delete retries original revision after accepted-but-failed response, removes only place and keeps trip option')

            desktop=out/(stamp+'-desktop.png');page.screenshot(path=str(desktop),full_page=True)
            report['screenshots'].append(str(desktop))
            page.set_viewport_size({'width':390,'height':844})
            page.evaluate("document.documentElement.dataset.theme='forest'")
            new('合成手机草稿')
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.locator('[data-jm=pick]').click();page.keyboard.press('Escape')
            expect(page.locator('[data-jm=pick]')).to_be_focused()
            assert page.locator('[data-jm=new]').bounding_box()['height']>=44
            mobile=out/(stamp+'-mobile.png');page.screenshot(path=str(mobile),full_page=True)
            report['screenshots'].append(str(mobile))
            page.evaluate('JourneyMap.notifyStateChanged()')
            expect(form.locator('[name=name]')).to_have_value('合成手机草稿')
            page.evaluate("()=>{const host=document.querySelector('#host');host.remove();document.body.prepend(host);JourneyMap.notifyStateChanged();}")
            expect(form.locator('[name=name]')).to_have_value('合成手机草稿')
            cancel()
            passed('390px dark theme has no horizontal overflow; 44px control; focus return; polling and synchronous detach/reattach preserve draft')

            fixture.fail_journeys=True
            page.evaluate('mountMap()');ready();select(OWN)
            page.locator('[data-jm=edit]').click()
            expect(form.locator('[name=journeyId]')).to_have_value(TRIP)
            expect(form.locator('[name=journeyId] option:checked')).to_have_text('合成旅行')
            cancel();fixture.fail_journeys=False
            passed('failed journey options preserve the existing visible association instead of silently showing unlinked')

            fixture.started.clear();fixture.release.clear();fixture.hold_list=True
            page.evaluate('mountMap()')
            held()
            fixture.actor='member2'
            page.evaluate("switchLocal('member2')")
            expect(page.locator('#host')).not_to_contain_text('合成私密到访')
            expect(page.locator('[data-jm-editor]')).to_have_count(0)
            fixture.release.set();page.wait_for_timeout(200)
            expect(page.locator('#host')).to_contain_text('登录成员或家庭已变化')
            page.evaluate('mountMap()');ready()
            expect(page.locator('.jm-list')).not_to_contain_text('合成新增已到访')
            passed('identity callback clears private DOM/draft immediately and rejects held old-member list response')

            fixture.started.clear();fixture.release.clear();fixture.hold_post=True
            new('合成写入途中换身份');save()
            held()
            fixture.actor='member1';page.evaluate("switchLocal('member1')")
            fixture.release.set();page.wait_for_timeout(200)
            expect(page.locator('#host')).to_contain_text('登录成员或家庭已变化')
            assert any(p['name']=='合成写入途中换身份' and p['owner']=='member2' for p in fixture.rows.values())
            passed('identity change hides accepted in-flight write response without pretending the server write was cancelled')

            page.evaluate('mountMap()');ready();new('合成卸载草稿')
            page.evaluate("document.querySelector('#host').remove()")
            page.wait_for_timeout(50)
            page.evaluate("document.body.insertAdjacentHTML('afterbegin','<main id=host></main>');mountMap()")
            ready();expect(page.locator('[data-jm-editor]')).to_have_count(0)
            page.evaluate('JourneyMap.openView()')
            expect(page.locator('#dialog')).to_be_visible()
            ready();page.evaluate("document.querySelector('#dialog').close()")
            expect(page.locator('[data-journey-map-host]')).to_be_empty()
            passed('node removal and dialog close clear module state and nodes')

            fixture.actor='member2'
            before=len(fixture.requests)
            page.evaluate('mountMap()')
            expect(page.locator('#host')).to_contain_text('登录成员或家庭已变化')
            assert not any(r['path'].startswith('/api/journey-places') for r in fixture.requests[before:])
            passed('server-only session change is detected before fetching private map data')

            before=len(fixture.requests)
            page.goto(base+'/?tv')
            expect(page.locator('#host')).to_contain_text('电视没有访问权限')
            assert all(r['path'].startswith('/api/me') for r in fixture.requests[before:])
            page.evaluate('JourneyMap.openView()')
            expect(page.locator('#dialog')).not_to_be_visible()
            passed('TV mount/openView refuse data loading and dialog access')
            assert not report['pageErrors'],report['pageErrors']
            assert not report['externalRequests'],report['externalRequests']
            report['passed']=True
    except Exception:
        report['failure']=traceback.format_exc()
        print(report['failure'],flush=True)
    finally:
        fixture.release.set()
        if browser:
            try: browser.close()
            except Exception: pass
        if server:
            server.shutdown()
        report['requestCount']=len(fixture.requests)
        report['syntheticApiRequests']=fixture.requests
        report['sourceHashesAfter']=sources()
        report['sourcesUnchanged']=report['sourceHashes']==report['sourceHashesAfter']
        report['passed']=report['passed'] and report['sourcesUnchanged']
        report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(str(report_path),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
