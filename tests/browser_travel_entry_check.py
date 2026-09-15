"""Real synthetic Flask/SQLite/Edge checks for unified travel creation entries.

Only loopback HTTP and synthetic inputs. Delayed responses are fetched from the
real temporary server before release; no real provider or production is used.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import traceback
from urllib.parse import urlsplit
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import create_app
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server, WSGIRequestHandler


class Quiet(WSGIRequestHandler):
    def log(self, *_args, **_kwargs): pass


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def sources():
    paths = set(ROOT.glob('*.py')) | {Path(__file__)}
    for folder in ('static', 'deploy'):
        paths.update(p for p in (ROOT / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    paths.update(ROOT / name for name in ('Dockerfile', 'compose.yaml', 'requirements.txt', 'pytest.ini'))
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(paths)}


def main():
    out = ROOT / 'test-results'; out.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target = out / 'travel-entry-browser-verification.json'
    if target.exists(): shutil.copy2(target, out / ('travel-entry-browser-history-' + stamp + '.json'))
    report = {'passed': False, 'checks': [], 'screenshots': [], 'sourceHashesBefore': sources(),
              'pageErrors': [], 'externalRequests': [], 'providerCalls': [], 'requestCounts': {},
              'realPrivateInputs': 0, 'productionWrites': 0, 'realCloudWrites': 0,
              'scope': 'Actual temporary Flask/SQLite and Edge, synthetic two households. No provider or production.',
              'knownBoundary': 'A cookie-only change after the final identity response is not atomic. Already-sent writes are not cancelled by closing a dialog.'}
    def passed(name):
        report['checks'].append({'name': name, 'passed': True}); print('PASS ' + name, flush=True)
    def deny(*args, **kwargs):
        report['providerCalls'].append('blocked'); raise AssertionError('Provider forbidden')
    original_connect, original_dns = socket.socket.connect, socket.getaddrinfo
    def local(host): return host in ('127.0.0.1', '::1', 'localhost', b'127.0.0.1', b'::1', b'localhost')
    def connect(sock, address):
        if isinstance(address, tuple) and not local(address[0]):
            report['externalRequests'].append('socket'); raise AssertionError('External socket')
        return original_connect(sock, address)
    def dns(host, *args, **kwargs):
        if host is not None and not local(host):
            report['externalRequests'].append('dns'); raise AssertionError('External DNS')
        return original_dns(host, *args, **kwargs)
    started = time.monotonic()
    try:
        with patch.object(socket.socket, 'connect', connect), patch.object(socket, 'getaddrinfo', dns), tempfile.TemporaryDirectory(prefix='travel-entry-') as folder:
            app = create_app({'TESTING': True, 'DATA_DIR': folder, 'SECRET_KEY': 'synthetic-travel-entry',
                              'SESSION_COOKIE_SECURE': False, 'PUBLIC_ORIGIN': 'http://localhost',
                              'MEMBER1_PASSWORD': 'testing-password-one', 'MEMBER2_PASSWORD': 'testing-password-two',
                              'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': '', 'MICROSOFT_CLIENT_ID': '',
                              'MICROSOFT_CLIENT_SECRET': '', 'OPENAI_API_KEY': '', 'OPENAI_MODEL': '',
                              'CLOUD_TRANSPORT': deny, 'OAUTH_TRANSPORT': deny})
            db = Path(folder) / 'household.sqlite3'
            def counts():
                with sqlite3.connect(db) as con:
                    return {kind: con.execute('SELECT COUNT(*) FROM ' + kind).fetchone()[0]
                            for kind in ('journey_workflows', 'entities', 'journey_actions')}
            server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=Quiet)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            base = 'http://127.0.0.1:' + str(server.server_port)
            try:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
                    def login(ctx, member=1, child=False):
                        with sqlite3.connect(db) as con: con.execute('DELETE FROM attempts')
                        ctx.request.get(base + '/api/me')
                        r = ctx.request.post(base + '/api/login', data={'username': 'member' + str(member),
                            'password': ('child-password-' if child else 'testing-password-') + ('one' if member == 1 else 'two')})
                        assert r.status == 200
                    def headers(ctx): return {'X-CSRF-Token': ctx.request.get(base + '/api/me').json()['csrf']}
                    admin = browser.new_context(); login(admin)
                    invitation = admin.request.post(base + '/api/spaces/invitations', headers=headers(admin), data={})
                    assert invitation.status == 201
                    child = admin.request.post(base + '/api/spaces/redeem', data={'invitation': invitation.json()['invitation'],
                        'name': '虚构旅行第二家庭', 'slug': 'synthetic-travel-entry',
                        'MEMBER1_PASSWORD': 'child-password-one', 'MEMBER2_PASSWORD': 'child-password-two'})
                    assert child.status == 201
                    child_entry = child.json()['entry']

                    class Flow:
                        def __init__(self, path='/'):
                            self.ctx = browser.new_context(viewport={'width': 1440, 'height': 1050})
                            self.calls = []; self.held = []; self.holding = None
                            self.ctx.route('**/*', self.route)
                            self.ctx.add_init_script('window.entryPending=0;const originalFetch=fetch;window.fetch=async(...args)=>{window.entryPending++;try{return await originalFetch(...args)}finally{window.entryPending--}};')
                            if path == '/': login(self.ctx)
                            self.page = self.ctx.new_page(); self.page.on('pageerror', lambda e: report['pageErrors'].append(str(e)))
                            self.page.goto(base + path); self.page.wait_for_function('()=>data!==null')
                        def route(self, route):
                            req = route.request; path = urlsplit(req.url).path; key = (req.method, path)
                            if not req.url.startswith(base + '/'):
                                report['externalRequests'].append(path); route.abort(); return
                            self.calls.append(key); label = ' '.join(key)
                            report['requestCounts'][label] = report['requestCounts'].get(label, 0) + 1
                            if self.holding == key:
                                self.holding = None; self.held.append((route, route.fetch())); return
                            route.continue_()
                        def hold(self, path='/api/me', method='GET'): self.holding = (method, path)
                        def waiting(self):
                            end = time.monotonic() + 15
                            while not self.held and time.monotonic() < end: self.page.wait_for_timeout(25)
                            assert self.held, 'expected actual held response'
                        def release(self, error=False):
                            route, response = self.held.pop(0)
                            if error: route.fulfill(status=503, json={'error': 'synthetic delayed failure'})
                            else: route.fulfill(response=response)
                            self.page.wait_for_function('()=>window.entryPending===0', timeout=15000)
                        def begin(self): self.page.evaluate('()=>{void JourneyUI.create()}')
                        def ready(self): expect(self.page.locator('#journey-form')).to_be_visible()
                        def close(self): self.page.locator('[data-action=close]').click()
                        def fill(self, title):
                            self.page.locator('#journey-form [name=title]').fill(title)
                            self.page.locator('#journey-form [name=city]').fill('虚构城市')
                        def dispose(self): self.ctx.close()

                    f = Flow(); page = f.page; initial = counts()
                    page.locator('[data-ps-create]').click()
                    page.locator('.ps-create-grid [data-kind=trips]').click(); f.ready()
                    passed('Home quick-create opens linked wizard, not legacy trip form')
                    f.close()
                    for label, setup, selector in (
                        ('home travel plus', 'ProductShell.navigate("home")', '.travel-card [data-action=add][data-kind=trips]'),
                        ('home travel empty action', 'ProductShell.navigate("home")', '.travel-card [data-action=add-trip]'),
                        ('legacy manager add', 'manage("trips")', '.manager-toolbar [data-action=add][data-kind=trips]'),
                        ('trips heading', 'ProductShell.navigate("trips")', '.ps-page-heading [data-action=add][data-kind=trips]'),
                        ('trips empty action', 'ProductShell.navigate("trips")', '.ps-empty-state [data-action=add][data-kind=trips]')):
                        page.evaluate(setup); page.locator(selector).click(); f.ready(); f.close(); passed(label + ' reaches same wizard; cancellation writes nothing')
                    assert counts() == initial
                    f.begin(); f.ready(); f.fill('虚构首旅 · 入口联动')
                    form = page.locator('#journey-form'); node = form.element_handle()
                    page.evaluate('()=>JourneyUI.create()')
                    assert node.evaluate('(n)=>n===document.querySelector("#journey-form")')
                    expect(form.locator('[name=title]')).to_have_value('虚构首旅 · 入口联动')
                    passed('Existing wizard draft is preserved when create is requested again')
                    form.locator('[type=submit]').click(); expect(page.locator('#journey-apply')).to_be_enabled()
                    review = page.locator('#journey-review-form').element_handle()
                    page.evaluate('()=>JourneyUI.create()')
                    assert review.evaluate('(n)=>n===document.querySelector("#journey-review-form")')
                    passed('Existing preview and confirmation remain intact on new-create reentry')
                    page.locator('[data-journey=purchase]').click()
                    purchase = page.locator('#journey-purchases .purchase').last
                    purchase.locator('[name=title]').fill('虚构首旅采购'); purchase.locator('[name=budget]').fill('88')
                    purchase.locator('[name=owner]').select_option('member2')
                    expect(page.locator('#journey-apply')).to_be_disabled()
                    page.locator('[data-journey=repreview]').click(); expect(page.locator('#journey-apply')).to_be_enabled()
                    assert counts() == initial
                    shot = out / ('travel-entry-preview-' + stamp + '.png'); page.screenshot(path=str(shot), full_page=True)
                    report['screenshots'].append({'path': str(shot), 'sha256': sha(shot)})
                    page.locator('#journey-apply').click(); expect(page.locator('.journey-detail-top')).to_be_visible()
                    result = f.ctx.request.get(base + '/api/journeys').json()['journeys']
                    assert len(result) == 1
                    j = result[0]; assert j['tasks'] and j['shopping'] and j['events']
                    assert j['shopping'][0]['budget'] == 8800 and j['shopping'][0]['owner'] == 'member2'
                    state = f.ctx.request.get(base + '/api/state').json()
                    for kind in ('tasks', 'shopping', 'events'):
                        assert {x['id'] for x in j[kind]} <= {x['id'] for x in state[kind]}
                    assert all(x['tripId'] == j['tripId'] and x['journeyId'] == j['id'] for kind in ('tasks','shopping','events') for x in j[kind])
                    assert ('POST','/api/items/trips') not in f.calls
                    passed('Exactly one first journey confirms real linked preparation, purchase and calendar, with stable IDs and owner')
                    page.set_viewport_size({'width':360,'height':800})
                    assert page.evaluate('document.querySelector("#dialog").scrollWidth<=document.querySelector("#dialog").clientWidth+2')
                    shot = out / ('travel-entry-phone-' + stamp + '.png'); page.screenshot(path=str(shot),full_page=True)
                    report['screenshots'].append({'path':str(shot),'sha256':sha(shot)})
                    passed('Saved first journey is readable at360px')
                    f.close(); page.set_viewport_size({'width':1440,'height':1050})
                    page.evaluate('()=>{window.savedJourneyUI=JourneyUI;window.JourneyUI=undefined;editItem("trips")}')
                    expect(page.locator('#toast')).to_contain_text('没有创建旅行')
                    expect(page.locator('#dialog')).not_to_be_visible(); page.evaluate('window.JourneyUI=window.savedJourneyUI')
                    passed('Missing module refuses new creation without legacy fallback')
                    legacy = f.ctx.request.post(base+'/api/items/trips',headers=headers(f.ctx),data={'title':'旧旅行编辑样本','destination':'虚构旧城','start':'2027-01-01','end':'2027-01-02','budget':10000,'saved':0,'paid':0})
                    assert legacy.status in (200,201)
                    page.evaluate('()=>refresh(true)'); page.evaluate('(id)=>editItem("trips",id)',legacy.json()['id'])
                    expect(page.locator('#dialog-title')).to_have_text('编辑旅行')
                    page.locator('#dialog [name=title]').fill('旧旅行保持原编辑'); page.locator('#dialog [type=submit]').click()
                    expect(page.locator('#dialog')).not_to_be_visible()
                    assert len(f.ctx.request.get(base+'/api/journeys').json()['journeys']) == 1
                    passed('Existing legacy trip still uses original PATCH editor and does not duplicate a journey')
                    f.dispose()

                    f=Flow(); me_before=f.calls.count(('GET','/api/me')); f.hold(); f.begin(); f.waiting(); f.begin()
                    f.release(); f.ready(); assert f.calls.count(('GET','/api/me')) == me_before+1
                    before=f.page.locator('#journey-form').element_handle(); f.fill('双击仍为一个草稿')
                    assert before.evaluate('(n)=>n===document.querySelector("#journey-form")')
                    passed('Repeated create while identity read pending shares one loading flow'); f.dispose()
                    f=Flow(); snapshot=counts(); f.hold(); f.begin(); f.waiting(); f.release(True)
                    expect(f.page.locator('.journey-error')).to_contain_text('没有创建旅行')
                    f.page.locator('[data-journey=create]').click(); f.ready(); f.close(); assert counts()==snapshot
                    passed('Identity-read failure keeps an actionable retry and does not create a trip'); f.dispose()
                    for change in ('close','new-shopping','member','household'):
                        for failed in (False,True):
                            f=Flow(); f.hold(); f.begin(); f.waiting()
                            if change=='close': f.close()
                            elif change=='new-shopping': f.page.evaluate('()=>ShoppingUI.openEditor()')
                            else:
                                if change=='household': f.ctx.request.get(base+child_entry)
                                login(f.ctx,2,change=='household'); f.page.evaluate('()=>boot()')
                                f.page.evaluate('()=>ShoppingUI.openEditor()')
                            other=f.page.locator('#dialog .dialog-content').element_handle()
                            f.release(failed)
                            if change=='close': expect(f.page.locator('#dialog')).not_to_be_visible()
                            else: assert other.evaluate('(n)=>n===document.querySelector("#dialog .dialog-content")')
                            expect(f.page.locator('#journey-form')).to_have_count(0)
                            passed('Late identity '+('503' if failed else '200')+' cannot replace '+change); f.dispose()
                    f=Flow(); login(f.ctx,2); f.begin()
                    expect(f.page.locator('.journey-error')).to_contain_text('登录成员或家庭已变化')
                    expect(f.page.locator('#journey-form')).to_have_count(0)
                    passed('Cookie-only member switch before entry is detected by fresh session read'); f.dispose()
                    f=Flow(); f.hold('/api/journeys'); f.page.evaluate('()=>{void JourneyUI.open()}'); f.waiting()
                    f.page.evaluate('()=>JourneyUI.create()'); f.ready(); f.fill('新草稿不被旧列表覆盖')
                    f.release(); expect(f.page.locator('#journey-form [name=title]')).to_have_value('新草稿不被旧列表覆盖')
                    passed('Earlier journey list read cannot replace a new draft'); f.dispose()
                    f=Flow(); f.begin(); f.ready(); f.fill('取消的旧预览'); f.hold('/api/journeys/preview','POST')
                    f.page.locator('#journey-form [type=submit]').click(); f.waiting(); f.close()
                    f.page.evaluate('()=>JourneyUI.create()'); f.ready(); f.fill('保留后来的旅行草稿')
                    f.release(); expect(f.page.locator('#journey-form [name=title]')).to_have_value('保留后来的旅行草稿')
                    passed('Cancelled old preview cannot replace a later new-travel draft'); f.dispose()
                    f=Flow('/demo'); f.page.evaluate('ProductShell.navigate("trips")')
                    f.page.locator('.ps-page-heading [data-action=add][data-kind=trips]').click(); f.ready(); f.fill('虚构演示首旅')
                    f.page.locator('#journey-form [type=submit]').click(); expect(f.page.locator('#journey-apply')).to_be_disabled()
                    assert not [c for c in f.calls if c[1].startswith('/api/journeys') or c[1]=='/api/me']
                    passed('Demo entry previews locally with no private API and confirmation disabled'); f.dispose()
                    f=Flow('/demo?tv=1'); f.page.evaluate('()=>JourneyUI.create()')
                    expect(f.page.locator('#journey-form')).to_have_count(0)
                    expect(f.page.locator('[data-action=add][data-kind=trips],[data-action=add-trip]')).to_have_count(0)
                    assert not [c for c in f.calls if c[1].startswith('/api/journeys')]
                    passed('TV has no creation controls and direct create is refused'); f.dispose()
                    assert not report['pageErrors'] and not report['externalRequests'] and not report['providerCalls']
                    report['passed']=True; browser.close()
            finally: server.shutdown(); server.server_close(); thread.join(timeout=5)
    except Exception:
        report['failure']=traceback.format_exc(); raise
    finally:
        report['sourceHashesAfter']=sources(); report['sourceUnchanged']=report['sourceHashesBefore']==report['sourceHashesAfter']
        report['elapsedSeconds']=round(time.monotonic()-started,2); report['checkCount']=len(report['checks'])
        report['passed']=report['passed'] and report['sourceUnchanged']
        target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'report':str(target),'passed':report['passed'],'checks':report['checkCount'],'sourceUnchanged':report['sourceUnchanged']}),flush=True)
    assert report['passed']


if __name__=='__main__': main()
