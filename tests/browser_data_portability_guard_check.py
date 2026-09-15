"""Actual local export flows under delayed HTTP/blob/session responses; fictional inputs only."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from app import create_app
from test_data_portability import seed
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server,WSGIRequestHandler


class Quiet(WSGIRequestHandler):
    def log(self,*_args,**_kwargs):pass


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


INSTRUMENTATION=r"""(() => {
  const review=window.exportReview={created:[],revoked:[],releaseTimers:[],blobWaiting:false};
  const realFetch=window.fetch.bind(window), realSetTimeout=window.setTimeout.bind(window);
  const create=URL.createObjectURL.bind(URL), revoke=URL.revokeObjectURL.bind(URL);
  URL.createObjectURL=value=>{const url=create(value);review.created.push(url);return url;};
  URL.revokeObjectURL=url=>{review.revoked.push(url);return revoke(url);};
  window.setTimeout=(fn,delay,...args)=>{
    if(review.created.length && typeof fn==='function' && delay>=1000 && delay<=60000) review.releaseTimers.push(()=>fn(...args));
    return realSetTimeout(fn,delay,...args);
  };
  window.fetch=async (url,options={})=>{
    const path=new URL(typeof url==='string'?url:url.url,location.href).pathname;
    // Force the best-effort abort to be insufficient: the guard must also reject
    // late successful results by identity, node and operation generation.
    const response=await realFetch(url,(path==='/api/me'||path.startsWith('/api/portability/'))?{...options,signal:undefined}:options);
    if(path==='/api/portability/export' && review.holdBlob){
      review.holdBlob=false;const original=response.blob.bind(response);
      response.blob=async()=>{const value=await original();review.blobWaiting=true;
        return new Promise(resolve=>{review.releaseBlob=()=>{review.blobWaiting=false;resolve(value);};});};
    }
    return response;
  };
})();"""


def main():
    out=ROOT/'test-results';out.mkdir(exist_ok=True)
    names={p.relative_to(ROOT).as_posix() for p in ROOT.glob('*.py')}
    for folder in ('static','deploy'):
        names.update(p.relative_to(ROOT).as_posix() for p in (ROOT/folder).rglob('*')
                     if p.is_file() and '__pycache__' not in p.parts)
    names.update(('Dockerfile','compose.yaml','requirements.txt','pytest.ini',
                  'tests/browser_data_portability_guard_check.py','tests/test_data_portability.py'))
    before={name:sha(ROOT/name) for name in sorted(names)}
    checks=[];observations=[];errors=[];external=[];provider_calls=[];screenshots=[];request_counts={}
    failed=[];completed=False;started=time.monotonic()
    logfile=out/'data-portability-guard-browser.log'
    def log(name):
        with logfile.open('a',encoding='utf-8') as stream:stream.write(name+'\n')
        print(name,flush=True)
    logfile.write_text('Fictional loopback export guard verification\n',encoding='utf-8')
    original_connect=socket.socket.connect
    def local_connect(sock,address):
        if isinstance(address,tuple) and address[0] not in ('127.0.0.1','localhost','::1'):
            external.append('blocked-python-external');raise AssertionError('External network forbidden')
        return original_connect(sock,address)
    socket.socket.connect=local_connect
    try:
        with tempfile.TemporaryDirectory(prefix='synthetic-export-guard-') as folder:
            dbpath=Path(folder)/'household.sqlite3'
            def no_provider(*_args,**_kwargs):
                provider_calls.append('unexpected-provider');raise AssertionError('No provider calls authorized')
            app=create_app({'TESTING':True,'SECRET_KEY':'synthetic-export-guard-key','DATA_DIR':folder,
                            'SESSION_COOKIE_SECURE':False,'MEMBER1_PASSWORD':'testing-password-one',
                            'MEMBER2_PASSWORD':'testing-password-two','MICROSOFT_CLIENT_ID':'','MICROSOFT_CLIENT_SECRET':'',
                            'GOOGLE_CLIENT_ID':'','GOOGLE_CLIENT_SECRET':'','OPENAI_API_KEY':'','OPENAI_MODEL':'',
                            'CLOUD_TRANSPORT':no_provider})
            seed(app)
            with closing(sqlite3.connect(dbpath)) as con,con:
                con.execute("INSERT INTO hub_transactions(id,owner,fingerprint,data,created_at) SELECT 'synthetic-extra','member1','synthetic-extra',data,created_at FROM hub_transactions WHERE id='tx-member1'")
            server=make_server('127.0.0.1',0,app,threaded=True,request_handler=Quiet)
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            base=f'http://127.0.0.1:{server.server_port}'
            try:
                with sync_playwright() as playwright:
                    browser=playwright.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
                    def clear_limits():
                        with closing(sqlite3.connect(dbpath)) as con,con:con.execute('DELETE FROM attempts')
                    def me(context):
                        result=context.request.get(base+'/api/me');assert result.status==200
                        return result.json()
                    def headers(context):return {'X-CSRF-Token':me(context)['csrf']}
                    def login(context,member='member1',password=None):
                        me(context)
                        result=context.request.post(base+'/api/login',data={'username':member,'password':password or (
                            'testing-password-one' if member=='member1' else 'testing-password-two')})
                        assert result.status==200,result.text()
                        return me(context)
                    admin=browser.new_context()
                    clear_limits();login(admin)
                    invitation=admin.request.post(base+'/api/spaces/invitations',headers=headers(admin),data={})
                    assert invitation.status==201
                    joined=admin.request.post(base+'/api/spaces/redeem',data={
                        'invitation':invitation.json()['invitation'],'name':'Synthetic Export Family','slug':'export-guard-second',
                        'MEMBER1_PASSWORD':'second-home-password-one','MEMBER2_PASSWORD':'second-home-password-two'})
                    assert joined.status==201,joined.text()
                    child_entry=joined.json()['entry'];admin.close()

                    class Flow:
                        def __init__(self,opened=True):
                            clear_limits()
                            self.context=browser.new_context(accept_downloads=True,viewport={'width':390,'height':844})
                            self.actor=login(self.context)
                            assert self.actor['user']['role']=='member'
                            assert {'id','householdId','auth_version'}<=set(self.actor['user']) and self.actor['csrf']
                            assert self.context.request.post(base+'/api/sessions/revoke-others',headers=headers(self.context),data={}).status==200
                            self.context.add_init_script(INSTRUMENTATION)
                            self.context.route('**/*',self.route)
                            self.gate=None;self.held=[];self.downloads=[];self.posts=[];self.closed=False
                            self.page=self.context.new_page()
                            self.page.on('pageerror',lambda error:errors.append(str(error)))
                            self.page.on('download',lambda download:self.downloads.append(download))
                            self.page.goto(base);expect(self.page.locator('.ps-welcome')).to_be_visible()
                            self.page.evaluate('clearInterval(pollTimer);ProductShell.navigate("settings")')
                            if opened:self.open()
                        def route(self,route):
                            req=route.request
                            if not req.url.startswith(base+'/'):
                                external.append('blocked-browser-external');route.abort();return
                            path=urlsplit(req.url).path;key=req.method+' '+path
                            request_counts[key]=request_counts.get(key,0)+1
                            if path=='/api/portability/export' and req.method=='POST':self.posts.append(req.post_data_json)
                            if self.gate and self.gate['path']==path:
                                gate=self.gate;self.gate=None
                                if gate['kind']=='network':route.abort('failed');return
                                response=route.fetch()
                                self.held.append((route,response,gate))
                            else:route.continue_()
                        def arm(self,path,kind='success'):
                            assert self.gate is None and not self.held
                            self.gate={'path':path,'kind':kind}
                        def wait(self,predicate):
                            for _ in range(250):
                                if predicate():return
                                self.page.wait_for_timeout(20)
                            raise AssertionError('Expected delayed phase did not become ready')
                        def pending(self):self.wait(lambda:bool(self.held))
                        def release(self):
                            route,response,gate=self.held.pop(0);kind=gate['kind']
                            if kind=='success':route.fulfill(response=response)
                            elif kind=='bad-type':route.fulfill(status=200,content_type='text/plain',body='synthetic invalid archive')
                            elif kind=='bad-json':route.fulfill(status=500,content_type='application/json',body='{invalid')
                            else:route.fulfill(status=int(kind),content_type='application/json',body=json.dumps({'error':'SYNTHETIC_OLD_EXPORT_ERROR'}))
                            self.page.wait_for_timeout(180)
                        def open(self):
                            self.page.evaluate('void DataPortability.open()')
                            expect(self.page.locator('#portability-form')).to_be_visible()
                        def submit(self):self.page.locator('#portability-form button[type=submit]').click()
                        def neutral(self):
                            self.page.wait_for_timeout(150)
                            assert not self.page.locator('#dialog .info-box').is_visible()
                            assert '2 条账单与订单' not in self.page.locator('#dialog').inner_text()
                        def draft(self):
                            self.page.evaluate('profileForm()')
                            self.page.locator('#dialog input[name=name]').fill('KEEP_NEW_DRAFT')
                            self.page.evaluate('window.exportNewDraft=document.querySelector("#dialog form")')
                        def assert_draft(self):
                            assert self.page.evaluate('window.exportNewDraft.isConnected')
                            expect(self.page.locator('#dialog input[name=name]')).to_have_value('KEEP_NEW_DRAFT')
                            assert 'SYNTHETIC_OLD_EXPORT_ERROR' not in self.page.locator('#dialog').inner_text()
                            assert 'SYNTHETIC_OLD_EXPORT_ERROR' not in self.page.locator('#toast').inner_text()
                        def switch(self,kind,boot=False):
                            if kind=='household':
                                assert self.context.request.get(base+child_entry).status==200
                                changed=login(self.context,password='second-home-password-one')
                                assert changed['user']['id']==self.actor['user']['id']
                                assert changed['user']['householdId']!=self.actor['user']['householdId']
                            elif kind=='logout':
                                assert self.context.request.post(base+'/api/logout',headers=headers(self.context),data={}).status==200
                                changed=me(self.context);assert changed['user'] is None
                            elif kind=='revoke':
                                listing=self.context.request.get(base+'/api/sessions').json()
                                uid=next(row['id'] for row in listing['sessions'] if row['current'])
                                assert self.context.request.delete(base+'/api/sessions/'+uid,headers=headers(self.context),data={}).status==200
                                changed=me(self.context);assert changed['user'] is None
                            else:
                                changed=login(self.context,'member2' if kind=='member' else 'member1')
                                if kind=='same-member':
                                    assert changed['user']['id']==self.actor['user']['id']
                                    assert changed['user']['auth_version']==self.actor['user']['auth_version']
                                    assert changed['csrf']!=self.actor['csrf']
                            if boot:self.page.evaluate('async()=>{await boot();clearInterval(pollTimer)}')
                            return changed
                        def replace(self,target):
                            if target=='close':self.page.evaluate('closeModal()')
                            elif target=='navigate':self.page.evaluate('ProductShell.navigate("tasks")')
                            elif target=='profile':self.draft()
                            elif target=='new-export':
                                self.draft();self.open()
                                self.page.locator('#portability-form [name=includeShared]').check()
                                self.page.evaluate('window.exportNewForm=document.querySelector("#portability-form")')
                            else:self.switch(target)
                        def assert_replacement(self,target):
                            if target=='profile':self.assert_draft()
                            elif target=='new-export':
                                assert self.page.evaluate('window.exportNewForm===document.querySelector("#portability-form")')
                                expect(self.page.locator('#portability-form [name=includeShared]')).to_be_checked()
                                expect(self.page.locator('#portability-form button[type=submit]')).to_be_enabled()
                                assert 'SYNTHETIC_OLD_EXPORT_ERROR' not in self.page.locator('#dialog').inner_text()
                            elif target in ('close','navigate'):assert not self.page.evaluate('document.querySelector("#dialog").open')
                            else:self.neutral()
                            assert not self.downloads
                        def close(self):
                            if not self.closed:self.context.close();self.closed=True

                    active=[]
                    def case(name,action):
                        log('RUN '+name)
                        flow=None
                        try:
                            flow=action()
                            checks.append({'name':name,'passed':True});log('PASS '+name)
                        finally:
                            for item in active:item.close()
                            active.clear()
                    def flow(opened=True):
                        value=Flow(opened);active.append(value);return value
                    def check_summary_delay(target,kind):
                        f=flow(False);f.arm('/api/portability/summary',kind)
                        f.page.evaluate('void DataPortability.open()');f.pending()
                        f.replace(target);f.release();f.assert_replacement(target)
                        assert not f.posts
                    for target in ('close','profile','navigate','new-export'):
                        for kind in ('success','503'):
                            case('late_summary_'+kind+'_preserves_'+target,lambda target=target,kind=kind:check_summary_delay(target,kind))
                    for target in ('member','same-member','household','logout','revoke'):
                        case('cookie_only_late_summary_'+target,lambda target=target:check_summary_delay(target,'success'))

                    def check_before_submit(target):
                        f=flow();f.switch(target);f.submit()
                        f.wait(lambda:f.page.evaluate('()=>{const button=document.querySelector("#portability-form button[type=submit]");return !button||!button.disabled;}'))
                        f.neutral();assert not f.posts and not f.downloads
                    for target in ('member','same-member','household','logout','revoke'):
                        case('fresh_identity_before_submit_blocks_'+target,lambda target=target:check_before_submit(target))

                    def check_export_delay(stage,target):
                        f=flow();f.page.locator('#portability-form [name=includeShared]').check()
                        if stage=='response':f.arm('/api/portability/export')
                        else:f.page.evaluate('exportReview.holdBlob=true')
                        f.submit()
                        if stage=='response':f.pending()
                        else:f.wait(lambda:f.page.evaluate('exportReview.blobWaiting'))
                        assert len(f.posts)==1 and f.posts[0]=={'includeShared':True}
                        expect(f.page.locator('#portability-form [name=includeShared]')).to_be_disabled()
                        if stage=='final-me':
                            f.arm('/api/me');f.page.evaluate('exportReview.releaseBlob()');f.pending()
                        if stage=='final-me' and target in ('member','same-member','household','logout','revoke'):
                            # The final HTTP response already contains A. Here boot
                            # delivers the actual new identity into this page; the
                            # cookie-only after-last-read limit is recorded below.
                            f.switch(target,boot=True)
                        else:f.replace(target)
                        if stage in ('response','final-me'):f.release()
                        else:f.page.evaluate('exportReview.releaseBlob()');f.page.wait_for_timeout(180)
                        f.assert_replacement(target)
                        assert len(f.posts)==1
                        assert f.page.evaluate('exportReview.created.length')==0
                    for stage in ('response','blob','final-me'):
                        for target in ('close','profile','navigate','new-export','member','same-member','household','logout','revoke'):
                            suffix='_local_boot' if stage=='final-me' and target in ('member','same-member','household','logout','revoke') else ''
                            case('late_export_'+stage+'_blocks_'+target+suffix,lambda stage=stage,target=target:check_export_delay(stage,target))

                    # This is an observed limitation, deliberately excluded from
                    # protected checks: the browser has no atomic identity view
                    # after the last /me has already been read on the server.
                    def observe_last_identity_window():
                        f=flow();f.page.evaluate('exportReview.holdBlob=true');f.submit()
                        f.wait(lambda:f.page.evaluate('exportReview.blobWaiting'))
                        f.arm('/api/me');f.page.evaluate('exportReview.releaseBlob()');f.pending()
                        changed=f.switch('member')
                        assert changed['user']['id']=='member2'
                        assert f.page.evaluate('user.id')=='member1'
                        with f.page.expect_download() as event:f.release()
                        with ZipFile(event.value.path()) as archive:
                            exported=json.loads(archive.read('data.json'))
                        assert exported['member']['id']=='member1'
                        assert me(f.context)['user']['id']=='member2'
                        observations.append({'name':'cookie_only_change_after_final_me_server_read',
                            'classification':'observed_limitation','downloadCount':len(f.downloads),
                            'exportedSyntheticMember':'member1','actualSyntheticMember':'member2',
                            'pageIdentityRemainedOld':True,'countedAsProtectedCheck':False,
                            'boundary':'The final /me was fetched as A before a cookie-only B login; no local boot/event reached the A page. Fresh reads are not atomic with the download click.'})
                        log('OBSERVED limitation: cookie-only change after final /me read permits one old-identity download')
                    try:observe_last_identity_window()
                    finally:
                        for item in active:item.close()
                        active.clear()

                    def password_rotation():
                        f=flow();f.page.evaluate('exportReview.holdBlob=true');f.submit()
                        f.wait(lambda:f.page.evaluate('exportReview.blobWaiting'))
                        changed=f.context.request.post(base+'/api/profile',headers=headers(f.context),data={
                            'name':f.actor['user']['name'],'currentPassword':'testing-password-one',
                            'password':'synthetic-replacement-password'})
                        assert changed.status==200,changed.text()
                        try:
                            current=me(f.context)
                            assert current['user']['id']==f.actor['user']['id']
                            assert current['user']['auth_version']>f.actor['user']['auth_version']
                            assert current['csrf']!=f.actor['csrf']
                            f.page.evaluate('exportReview.releaseBlob()');f.page.wait_for_timeout(180)
                            f.neutral();assert not f.downloads and f.page.evaluate('exportReview.created.length')==0
                        finally:
                            restored=f.context.request.post(base+'/api/profile',headers=headers(f.context),data={
                                'name':f.actor['user']['name'],'currentPassword':'synthetic-replacement-password',
                                'password':'testing-password-one'})
                            assert restored.status==200,restored.text()
                    case('real_password_auth_version_rotation_blocks_old_blob',password_rotation)

                    def check_error(kind):
                        f=flow();f.page.locator('#portability-form [name=includeShared]').check()
                        f.arm('/api/portability/export',kind);f.submit()
                        if kind!='network':f.pending();f.release()
                        expect(f.page.locator('#portability-form .error')).not_to_be_empty()
                        expect(f.page.locator('#portability-form [name=includeShared]')).to_be_checked()
                        expect(f.page.locator('#portability-form [name=includeShared]')).to_be_enabled()
                        expect(f.page.locator('#portability-form button[type=submit]')).to_be_enabled()
                        assert not f.downloads
                        assert f.page.evaluate('exportReview.created.length')==0
                    for kind in ('500','503','429','bad-type','bad-json','network'):
                        case('current_export_'+kind+'_keeps_choice_and_retry',lambda kind=kind:check_error(kind))

                    def late_error(target):
                        f=flow();f.arm('/api/portability/export','503');f.submit();f.pending()
                        f.replace(target);f.release();f.assert_replacement(target)
                    for target in ('profile','new-export','member'):
                        case('late_export_error_does_not_contaminate_'+target,lambda target=target:late_error(target))

                    def accepted_download(f,shared):
                        f.page.locator('#portability-form [name=includeShared]').set_checked(shared)
                        with f.page.expect_download() as event:f.submit()
                        download=event.value;assert download.failure() is None
                        with ZipFile(download.path()) as archive:
                            files={name:archive.read(name) for name in archive.namelist()}
                        value=json.loads(files['data.json']);manifest=json.loads(files['manifest.json'])
                        assert value['member']['id']=='member1' and value['coverage']['includesShared'] is shared
                        assert ('shared' in value) is shared
                        assert 'member2_PRIVATE' not in ''.join(v.decode('utf-8-sig') for v in files.values())
                        assert all(len(files[name])==info['bytes'] and hashlib.sha256(files[name]).hexdigest()==info['sha256']
                                   for name,info in manifest['files'].items())
                        expect(f.page.locator('#portability-status')).to_contain_text('已开始下载')
                        expect(f.page.locator('#portability-form [name=includeShared]')).to_be_enabled()
                        return value
                    def normal_retry():
                        f=flow();f.page.locator('#portability-form [name=includeShared]').check()
                        f.arm('/api/portability/export','503');f.submit();f.pending();f.release()
                        expect(f.page.locator('#portability-form button[type=submit]')).to_be_enabled()
                        accepted_download(f,True)
                        assert len(f.posts)==2 and len(f.downloads)==1
                        f.page.evaluate('exportReview.releaseTimers.splice(0).forEach(fn=>fn())')
                        assert f.page.evaluate('exportReview.created.every(url=>exportReview.revoked.includes(url))')
                    case('503_retry_has_one_valid_shared_zip_and_releases_object_url',normal_retry)

                    def duplicate_submit():
                        f=flow();f.arm('/api/portability/export');f.submit();f.pending()
                        expect(f.page.locator('#portability-form [name=includeShared]')).to_be_disabled()
                        f.page.evaluate('document.querySelector("#portability-form").dispatchEvent(new Event("submit",{bubbles:true,cancelable:true}))')
                        f.page.wait_for_timeout(100);assert len(f.posts)==1
                        with f.page.expect_download():f.release()
                        assert len(f.downloads)==1
                    case('duplicate_submit_and_shared_checkbox_locked_until_completion',duplicate_submit)

                    def final_verify_unavailable():
                        f=flow();f.page.locator('#portability-form [name=includeShared]').check()
                        f.page.evaluate('exportReview.holdBlob=true');f.submit()
                        f.wait(lambda:f.page.evaluate('exportReview.blobWaiting'))
                        f.arm('/api/me','503');f.page.evaluate('exportReview.releaseBlob()');f.pending();f.release()
                        expect(f.page.locator('#portability-form [name=includeShared]')).to_be_checked()
                        expect(f.page.locator('#portability-form button[type=submit]')).to_be_enabled()
                        expect(f.page.locator('#portability-form .error')).not_to_be_empty()
                        assert not f.downloads and f.page.evaluate('exportReview.created.length')==0
                    case('final_identity_503_never_downloads_and_preserves_retry_choice',final_verify_unavailable)

                    def phone_and_desktop():
                        f=flow()
                        for width,height in ((390,844),(1440,1000)):
                            f.page.set_viewport_size({'width':width,'height':height})
                            assert f.page.evaluate('document.querySelector("#dialog").scrollWidth<=document.querySelector("#dialog").clientWidth+1')
                            name=f'data-portability-guard-{width}.png';f.page.screenshot(path=str(out/name),full_page=True)
                            screenshots.append(name)
                        accepted_download(f,False);assert len(f.posts)==len(f.downloads)==1
                    case('normal_personal_zip_and_phone_desktop_layout',phone_and_desktop)
                    assert not errors and not external and not provider_calls
                    browser.close();completed=True
            finally:
                server.shutdown();server.server_close();worker.join(timeout=5)
    except BaseException as error:
        failed.append({'type':type(error).__name__,'message':str(error)})
        log('FAIL '+type(error).__name__+': '+str(error))
        raise
    finally:
        socket.socket.connect=original_connect
        after={name:sha(ROOT/name) for name in before}
        unchanged=before==after
        result={'passed':completed and unchanged and not failed and not errors and not external and not provider_calls,
                'checks':checks,'observedLimitations':observations,'failures':failed,'sourceHashes':before,'sourceHashesAfter':after,'sourceUnchanged':unchanged,
                'pageErrors':errors,'externalRequests':external,'providerCalls':provider_calls,'screenshots':screenshots,
                'requestCounts':request_counts,'elapsedSeconds':round(time.monotonic()-started,2),
                'realCloudWrites':0,'productionWrites':0,'realPrivateInputs':0,
                'scope':'Actual loopback Flask/SQLite/Edge and fictional two-member/two-household HTTP. Portability abort signal is deliberately ignored in the test transport; blob and HTTP can arrive late. No real providers or production.',
                'limitations':['Download cancellation covers responses not yet handed to the browser; an already started download cannot be recalled.',
                               'Fresh identity reads and local guards are not an atomic guarantee over every possible cross-tab timing.']}
        path=out/'data-portability-guard-browser-verification.json'
        path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        network={'completed':completed,'blockedExternalRequests':external,'providerCalls':provider_calls,
                 'requestCounts':request_counts,'productionWrites':0}
        (out/'data-portability-guard-network-verification.json').write_text(json.dumps(network,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'passed':result['passed'],'checks':len(checks),'sourceUnchanged':unchanged,'report':str(path),'reportSha256':sha(path)},indent=2),flush=True)
        if not unchanged:raise AssertionError('Dependencies changed during browser verification')


if __name__=='__main__':main()
