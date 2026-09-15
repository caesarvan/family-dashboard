"""Task start: actual temporary Flask/SQLite/Edge, synthetic inputs and loopback only.

Provider source discovery is an in-process fake; OAuth is tested only by a
same-origin callback simulation. No real provider, credentials or production.
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
    target = out / 'task-start-browser-verification.json'
    if target.exists(): shutil.copy2(target, out / ('task-start-browser-history-' + stamp + '.json'))
    report = {'passed': False, 'checks': [], 'screenshots': [], 'sourceHashesBefore': sources(),
              'pageErrors': [], 'externalRequests': [], 'providerCalls': [], 'syntheticDiscoveryCalls': [],
              'requestCounts': {}, 'realPrivateInputs': 0, 'productionWrites': 0, 'realCloudWrites': 0,
              'scope': 'Actual temporary Flask/SQLite/Edge. Fake source discovery; no provider website or production.',
              'knownBoundary': 'Cookie change after final identity response is not atomic; already-sent writes cannot be cancelled. OAuth callback is same-origin simulation only.'}
    def passed(name):
        report['checks'].append({'name': name, 'passed': True}); print('PASS ' + name, flush=True)
    def deny(*_args, **_kwargs):
        report['providerCalls'].append('blocked'); raise AssertionError('Real provider forbidden')
    def transport(method, url, _token, body=None, headers=None):
        assert method == 'GET', 'No provider writes permitted'
        path = urlsplit(url).path
        report['syntheticDiscoveryCalls'].append({'method': method, 'path': path})
        if path.endswith('/calendars'):
            return {'value': [{'id': 'calendar-1', 'name': '虚构日历'}]}
        if path.endswith('/lists'):
            return {'value': [{'id': 'list-1', 'displayName': '虚构家庭清单'}]}
        raise AssertionError('Unexpected synthetic discovery')
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
        with patch.object(socket.socket, 'connect', connect), patch.object(socket, 'getaddrinfo', dns), tempfile.TemporaryDirectory(prefix='task-start-') as folder:
            app = create_app({'TESTING': True, 'DATA_DIR': folder, 'SECRET_KEY': 'synthetic-task-start',
                              'SESSION_COOKIE_SECURE': False, 'PUBLIC_ORIGIN': 'http://localhost',
                              'MEMBER1_PASSWORD': 'testing-password-one', 'MEMBER2_PASSWORD': 'testing-password-two',
                              'MICROSOFT_CLIENT_ID': 'test-client', 'MICROSOFT_CLIENT_SECRET': 'test-secret',
                              'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': '', 'OPENAI_API_KEY': '', 'OPENAI_MODEL': '',
                              'CLOUD_TRANSPORT': transport, 'OAUTH_TRANSPORT': deny})
            accounts = app.extensions['cloud_accounts']; db = Path(folder) / 'household.sqlite3'
            def entities():
                with sqlite3.connect(db) as con:
                    return [(row[0], json.loads(row[1])) for row in con.execute("SELECT id,data FROM entities WHERE kind='tasks'")]
            def publications():
                with sqlite3.connect(db) as con: return con.execute('SELECT count(*) FROM task_publications').fetchone()[0]
            def reset_tasks():
                # Synthetic scenario fixture only; no production data or remote writes.
                with sqlite3.connect(db) as con:
                    con.execute('DELETE FROM task_publications')
                    con.execute("DELETE FROM entities WHERE kind='tasks'")
            server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=Quiet)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            base = 'http://127.0.0.1:' + str(server.server_port)
            try:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
                    def login(ctx, member=1, child=False):
                        with sqlite3.connect(db) as con: con.execute('DELETE FROM attempts')
                        r = ctx.request.post(base + '/api/login', data={'username': 'member' + str(member),
                            'password': ('child-password-' if child else 'testing-password-') + ('one' if member == 1 else 'two')})
                        assert r.status == 200
                    def headers(ctx): return {'X-CSRF-Token': ctx.request.get(base + '/api/me').json()['csrf']}
                    admin = browser.new_context(); admin.request.get(base + '/api/me'); login(admin)
                    invitation = admin.request.post(base + '/api/spaces/invitations', headers=headers(admin), data={})
                    assert invitation.status == 201
                    child = admin.request.post(base + '/api/spaces/redeem', data={'invitation': invitation.json()['invitation'],
                        'name': '虚构起步第二家庭', 'slug': 'synthetic-task-start',
                        'MEMBER1_PASSWORD': 'child-password-one', 'MEMBER2_PASSWORD': 'child-password-two'})
                    assert child.status == 201
                    child_entry = child.json()['entry']

                    class Flow:
                        def __init__(self, demo=False):
                            self.ctx = browser.new_context(viewport={'width': 1440, 'height': 1000})
                            self.calls = []; self.held = []; self.holding = None
                            self.ctx.route('**/*', self.route)
                            self.ctx.add_init_script('window.taskStartPending=0;const realFetch=fetch;window.fetch=async(...a)=>{window.taskStartPending++;try{return await realFetch(...a)}finally{window.taskStartPending--}};')
                            if not demo: self.ctx.request.get(base + '/api/me'); login(self.ctx)
                            self.page = self.ctx.new_page(); self.page.on('pageerror', lambda e: report['pageErrors'].append(str(e)))
                            self.page.goto(base + ('/demo' if demo else '/') + '#tasks')
                            self.page.wait_for_function('()=>typeof data!=="undefined"&&data!==null')
                        def route(self, route):
                            req=route.request; path=urlsplit(req.url).path; key=(req.method,path)
                            if not req.url.startswith(base + '/'):
                                report['externalRequests'].append(path); route.abort(); return
                            self.calls.append(key); label=' '.join(key)
                            report['requestCounts'][label]=report['requestCounts'].get(label,0)+1
                            if self.holding==key:
                                self.holding=None;self.held.append((route,route.fetch()));return
                            route.continue_()
                        def start(self):
                            self.page.locator('[data-task-publish-open]').click()
                            expect(self.page.locator('[data-task-start]')).to_be_visible()
                        def setup(self):
                            self.start(); self.page.locator('[data-tp=task-setup]').click()
                            expect(self.page.locator('#account-return')).to_have_text('返回待办')
                        def hold(self,path='/api/me'):self.holding=('GET',path)
                        def waiting(self):
                            end=time.monotonic()+15
                            while not self.held and time.monotonic()<end:self.page.wait_for_timeout(25)
                            assert self.held,'expected actual held response'
                        def release(self,error=False):
                            route,response=self.held.pop(0)
                            if error:route.fulfill(status=503,json={'error':'synthetic delayed failure'})
                            else:route.fulfill(response=response)
                            self.page.wait_for_function('()=>window.taskStartPending===0',timeout=15000)
                        def close_dialog(self):
                            self.page.locator('#dialog [data-action=close]').first.click()
                            expect(self.page.locator('#dialog')).not_to_be_visible()
                            self.page.wait_for_timeout(30)
                        def close(self):
                            for route,_response in self.held:route.abort()
                            self.ctx.close()
                    f=Flow();page=f.page
                    try:
                        expect(page.locator('[data-task-publish-open]')).to_have_text('开始安排待办')
                        f.start();assert page.locator('#task-publish-form').count()==0
                        assert not entities() and not publications()
                        passed('empty-household-has-two-actionable-start-options-and-no-empty-preview')
                        page.locator('[data-tp=task-setup]').click()
                        expect(page.locator('#account-return')).to_have_text('返回待办')
                        expect(page.locator('#dialog')).to_contain_text('还没有绑定账户')
                        expect(page.locator('[data-account-bind=google]')).to_be_disabled()
                        assert not [c for c in f.calls if c[0]=='POST']
                        page.locator('#account-return').click()
                        expect(page.locator('#dialog')).not_to_be_visible()
                        assert page.evaluate('ProductShell.getRoute()')=='tasks'
                        passed('zero-account-setup-opens-and-can-return-without-binding-or-publishing')
                        f.start();page.locator('[data-tp=add-first]').click()
                        expect(page.locator('#dialog [name=title]')).to_be_visible()
                        page.locator('#dialog [name=title]').fill('取消的虚构首项')
                        f.close_dialog();assert not entities()
                        passed('first-local-task-cancel-does-not-write')
                        with accounts.db() as con:
                            for owner,name in [('member1','本人虚构账户'),('member2','OTHER_PRIVATE_ACCOUNT')]:
                                con.execute('INSERT INTO cloud_accounts(id,owner,provider,client_id,subject,name,email,tokens) VALUES(?,?,?,?,?,?,?,?)',
                                    ('account-'+owner,owner,'microsoft','test-client',owner,name,owner+'@example.invalid',
                                     accounts.encrypt({'access_token':'synthetic-only','scope':'User.Read Calendars.Read Tasks.ReadWrite','expires_at':time.time()+3600})))
                        f.setup();expect(page.locator('#dialog')).not_to_contain_text('OTHER_PRIVATE_ACCOUNT')
                        page.locator('[data-account-select=account-member1]').click()
                        expect(page.locator('#account-sources-form')).to_be_visible()
                        page.locator('[name=source-1]').check();page.locator('[name=primary][value="1"]').check();page.locator('[name=consent]').check()
                        page.locator('#account-sources-form button[type=submit]').click()
                        expect(page.locator('#account-return')).to_have_text('返回待办')
                        assert not entities() and not publications()
                        page.locator('#account-return').click();expect(page.locator('#dialog')).not_to_be_visible()
                        assert page.evaluate('!!data.sync.primaryTaskSource')
                        passed('actual-source-selection-consent-primary-save-and-explicit-return-no-publication')
                        f.start();expect(page.locator('[data-task-start]')).to_contain_text('已有可用清单')
                        assert page.locator('#task-publish-form').count()==0
                        for theme,width in [('forest',360),('light',768),('ocean',1440)]:
                            page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                            page.set_viewport_size({'width':width,'height':950})
                            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                            assert page.locator('#dialog').evaluate('(node)=>node.scrollWidth<=node.clientWidth+1')
                            shot=out/f'task-start-{theme}-{width}.png';page.screenshot(path=str(shot),full_page=True)
                            report['screenshots'].append({'path':str(shot),'sha256':sha(shot)})
                        passed('empty-configured-source-start-readable-at-three-widths-and-themes')
                        page.locator('[data-tp=add-first]').click()
                        expect(page.locator('#dialog [name=sourceId]')).to_have_value('')
                        page.locator('#dialog [name=title]').fill('第一件虚构家庭待办')
                        page.locator('#dialog [name=owner]').select_option('member1')
                        page.locator('#dialog [name=note]').fill('本地保存后再单独确认同步')
                        page.locator('#dialog button[type=submit]').click()
                        expect(page.locator('#dialog')).not_to_be_visible()
                        expect(page.locator('.ps-full-list')).to_contain_text('第一件虚构家庭待办')
                        rows=entities();assert len(rows)==1 and not rows[0][1].get('sync') and rows[0][1]['owner']=='member1'
                        entity_id=rows[0][0];assert not publications()
                        passed('first-item-stays-local-despite-configured-primary-and-reads-back-on-task-page')
                        # Existing nonempty target still uses its exact-ID return bridge.
                        accounts.select_sources('account-member1','member1',[])
                        page.locator('[data-task-publish-open]').click();expect(page.locator('[data-tp=connect]')).to_be_visible()
                        page.locator('[data-tp=connect]').click();expect(page.locator('#account-return')).to_have_text('返回待办发布')
                        page.locator('[data-account-select=account-member1]').click()
                        page.locator('[name=source-1]').check();page.locator('[name=consent]').check()
                        page.locator('#account-sources-form button[type=submit]').click();expect(page.locator('#account-return')).to_be_visible()
                        page.locator('#account-return').click();expect(page.locator('#task-publish-form')).to_be_visible()
                        assert page.locator('[name=entityId]').count()==1
                        expect(page.locator('[name=entityId]')).to_have_value(entity_id)
                        assert not page.locator('[name=entityId]').is_checked()
                        passed('nonempty-connection-return-retains-only-original-id-and-no-autoselection')
                        page.locator('[name=entityId]').check();page.locator('#task-publish-form button[type=submit]').click()
                        expect(page.locator('[data-tp=confirm]')).to_be_visible();assert not publications()
                        page.locator('[data-tp=confirm]').click();expect(page.locator('#task-publish-root')).to_be_visible()
                        assert publications()==1 and entities()[0][0]==entity_id
                        passed('first-record-continues-through-existing-preview-confirm-with-stable-id')
                    finally:f.close()

                    reset_tasks()
                    f=Flow();page=f.page
                    try:
                        f.setup();page.evaluate('()=>AccountsReturn.prepareOAuth()')
                        intent=page.evaluate('JSON.parse(sessionStorage.getItem("family-dashboard.connection-return.v1"))')
                        assert intent['target']=={'kind':'task-setup'}
                        assert not any(key in json.dumps(intent) for key in ['csrf','token','email','title','password'])
                        page.goto(base+'/?auth=connected')
                        expect(page.locator('#account-return')).to_have_text('返回待办')
                        assert page.locator('[data-tp=confirm],#task-publish-form').count()==0
                        assert page.evaluate('sessionStorage.getItem("family-dashboard.connection-return.v1")') is None
                        page.locator('#account-return').click();expect(page.locator('#dialog')).not_to_be_visible()
                        assert page.evaluate('ProductShell.getRoute()')=='tasks'
                        passed('setup-oauth-same-origin-restart-has-no-entity-payload-or-publication')
                        f.setup();f.hold('/api/state');page.locator('#account-return').click();f.waiting();f.release(error=True)
                        expect(page.locator('#account-return-error')).not_to_be_empty();expect(page.locator('#account-return')).to_be_enabled()
                        assert page.locator('#account-refresh').count()==1
                        before=len([c for c in f.calls if c[0]=='POST'])
                        page.locator('#account-return').click();expect(page.locator('#dialog')).not_to_be_visible()
                        assert len([c for c in f.calls if c[0]=='POST'])==before
                        passed('failed-return-read-keeps-configuration-and-retries-only-get')
                    finally:f.close()

                    for stage in ['add-first','setup-begin','setup-return']:
                        for mutation in ['new-draft','new-page','member','household','csrf']:
                            f=Flow();page=f.page
                            try:
                                if stage=='setup-return':f.setup();f.hold('/api/state');page.locator('#account-return').click()
                                else:
                                    f.start();f.hold();page.locator('[data-tp='+('add-first' if stage=='add-first' else 'task-setup')+']').click()
                                f.waiting()
                                if mutation in ['new-draft','new-page']:
                                    f.close_dialog()
                                    if mutation=='new-draft':
                                        page.locator('.ps-page-heading [data-action=add][data-kind=tasks]').click()
                                        page.locator('#dialog [name=title]').fill('不得覆盖的后来草稿')
                                    else:
                                        page.locator('.ps-sidebar [data-ps-route=shopping]').click()
                                elif mutation=='member':
                                    login(f.ctx,2);page.evaluate('()=>boot()')
                                elif mutation=='csrf':
                                    page.evaluate('()=>{csrf="synthetic-changed-csrf"}')
                                else:
                                    assert f.ctx.request.get(base+child_entry).status==200
                                    login(f.ctx,child=True);page.evaluate('()=>boot()')
                                identity=page.evaluate('JSON.stringify([user,data.revision,data.tasks.map(x=>x.id)])')
                                f.release(error=mutation=='new-page')
                                if mutation=='new-draft':expect(page.locator('#dialog [name=title]')).to_have_value('不得覆盖的后来草稿')
                                elif mutation=='new-page':assert page.evaluate('ProductShell.getRoute()')=='shopping';expect(page.locator('#dialog')).not_to_be_visible()
                                else:
                                    assert page.evaluate('JSON.stringify([user,data.revision,data.tasks.map(x=>x.id)])')==identity
                                    assert page.locator('#dialog [name=title]').count()==0
                                    assert page.locator('[data-account-select=account-member1]').count()==0
                                assert not [c for c in f.calls if c[0]=='POST' and c[1].startswith('/api/task-publish/')]
                                passed(stage+'-late-response-cannot-take-over-'+mutation)
                            finally:f.close()
                    f=Flow();page=f.page
                    try:
                        f.start();f.hold('/api/state');button=page.locator('[data-tp=add-first]');button.click();f.waiting()
                        button.evaluate('(b)=>b.dispatchEvent(new MouseEvent("click",{bubbles:true}))')
                        f.release();expect(page.locator('#dialog [name=title]')).to_be_visible()
                        assert len([x for x in f.calls if x==('GET','/api/state')])==2  # boot + one first-item read
                        passed('repeat-first-item-click-uses-one-navigation-read')
                    finally:f.close()
                    f=Flow(demo=True);page=f.page
                    try:
                        assert page.locator('[data-task-publish-open]').count()==0
                        before=len(f.calls);page.evaluate('()=>TaskPublish.open()')
                        expect(page.locator('#dialog')).to_contain_text('演示模式')
                        assert not [x for x in f.calls[before:] if x[1].startswith('/api/')]
                        passed('demo-has-explanation-with-no-new-private-request')
                    finally:f.close()
                    # Actual TV cookie is created through pairing APIs in the temporary household.
                    tv=browser.new_context();tv.request.get(base+'/api/me')
                    start=tv.request.post(base+'/api/pair/start',data={});assert start.status==200
                    pair=admin.request.post(base+'/api/pair/approve',headers=headers(admin),data={'code':start.json()['code']})
                    assert pair.status==200
                    status=tv.request.post(base+'/api/pair/poll',data={'secret':start.json()['secret']});assert status.status==200 and status.json()['approved']
                    def tv_route(route):
                        if route.request.url.startswith(base+'/'):route.continue_()
                        else:report['externalRequests'].append('tv');route.abort()
                    tv.route('**/*',tv_route)
                    tvpage=tv.new_page();tvpage.on('pageerror',lambda e:report['pageErrors'].append(str(e)));tvpage.goto(base+'/tv');tvpage.wait_for_function('()=>isTV&&data!==null')
                    assert tvpage.locator('[data-task-publish-open],[data-tp=task-setup],[data-tp=add-first]').count()==0
                    assert tv.request.get(base+'/api/task-publish/state').status==403
                    passed('paired-tv-hides-task-start-and-server-denies-private-publication-read')
                    tv.close();admin.close();browser.close()
            finally:server.shutdown();thread.join(timeout=5)
        assert not report['pageErrors'] and not report['externalRequests'] and not report['providerCalls']
        report['passed']=True
    except Exception:
        report['traceback']=traceback.format_exc();print(report['traceback'],flush=True)
    finally:
        report['sourceHashesAfter']=sources();report['sourceUnchanged']=report['sourceHashesBefore']==report['sourceHashesAfter']
        report['passed']=report['passed'] and report['sourceUnchanged'];report['checkCount']=len(report['checks'])
        report['durationSeconds']=round(time.monotonic()-started,2);report['exitCode']=0 if report['passed'] else 1
        target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'report':str(target),'passed':report['passed'],'checks':report['checkCount'],'exitCode':report['exitCode']},ensure_ascii=False),flush=True)
    raise SystemExit(report['exitCode'])


if __name__=='__main__':main()
