"""Loopback Flask/SQLite/Edge playback. Only fixture HTML wires the pending assets."""
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from flask import request
import pytest
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server, WSGIRequestHandler
from test_journey_documents import PASSWORD
from test_media_playback import setup, granted, command, device


class Quiet(WSGIRequestHandler):
    def log(self, *_args, **_kwargs):
        pass


def main():
    out = ROOT/'test-results/media-tv-playback'
    out.mkdir(parents=True, exist_ok=True)
    report = {'passed':False,'checks':[],'pageErrors':[],'serverErrors':[],'externalRequests':[],
        'realCloudWrites':0,'productionWrites':0,'realPrivateInputs':0,'realPhysicalTelevision':False,
        'scope':'Temporary SQLite and actual loopback Flask/Edge. Synthetic photos; explicit fixture registration/HTML injection. Network faults are deliberately injected.',
        'sourceHashes':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in (
            'media_playback.py','household_media.py','static/media-tv.js','static/media-tv.css',
            'static/tv-display.js','tests/browser_media_tv_check.py')}}
    changes = pytest.MonkeyPatch()
    servers, threads = [], []
    fault = {'blockState':False,'shortLease':False,'previewDelay':False,'memberDelay':False}
    gates = {key:(threading.Event(),threading.Event()) for key in ('preview','member')}
    def check(name):
        report['checks'].append(name)
    def attach(env):
        app = env[0]
        app.config['HOUSEHOLD_INFO'].update(name='Synthetic television household',slug='synthetic-tv-'+app.config['HOUSEHOLD_INFO']['id'])
        @app.after_request
        def fixture(response):
            if request.path in ('/','/tv') and response.status_code == 200:
                response.direct_passthrough = False
                text = response.get_data(as_text=True).replace('<link rel="stylesheet" href="/static/tv-display.css">',
                    '<link rel="stylesheet" href="/static/tv-display.css"><link rel="stylesheet" href="/static/media-tv.css">')
                text = text.replace('<script src="/static/tv-display.js" defer></script>',
                    '<script src="/static/media-tv.js" defer></script><script src="/static/tv-display.js" defer></script>')
                response.set_data(text)
            if request.path == '/api/media-tv/playback' and response.status_code == 200:
                if fault['blockState']:
                    time.sleep(5.5)  # Longer than the display request timeout.
                elif fault['shortLease']:
                    payload=response.get_json()
                    payload['validUntil']=(datetime.fromisoformat(payload['serverTime'])+timedelta(seconds=1)).isoformat()
                    response.set_data(json.dumps(payload))
            if request.path.endswith('/preview') and request.path.startswith('/api/media-tv/') and fault['previewDelay']:
                fault['previewDelay']=False
                gates['preview'][0].set()
                gates['preview'][1].wait(8)
            if request.path=='/api/me' and fault['memberDelay']:
                fault['memberDelay']=False
                gates['member'][0].set()
                gates['member'][1].wait(8)
            return response
        server=make_server('127.0.0.1',0,app,threaded=True,request_handler=Quiet)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        server.start_time=time.time()
        thread.start();servers.append(server);threads.append(thread)
        return 'http://127.0.0.1:'+str(server.server_port)
    try:
        with tempfile.TemporaryDirectory(prefix='media-tv-browser-') as folder:
            env, controller = setup(Path(folder)/'one',changes)
            other,_ = setup(Path(folder)/'two',changes,'b'*24)
            base, other_base = attach(env),attach(other)
            owner,headers,uid,_,secret,items = granted(env)
            second,_,second_secret = device(env)
            oc,oh,oid,_,other_secret,_ = granted(other,1)
            counts={}
            with sync_playwright() as pw:
                browser=pw.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
                def context(origin,**kwargs):
                    ctx=browser.new_context(**kwargs)
                    def route(r):
                        u=urlsplit(r.request.url)
                        if not r.request.url.startswith(origin+'/'):
                            report['externalRequests'].append({'method':r.request.method,'host':u.hostname,'path':u.path})
                            r.abort()
                        else:
                            key=r.request.method+' '+u.path
                            counts[key]=counts.get(key,0)+1
                            r.continue_()
                    ctx.route('**/*',route)
                    return ctx
                def page(ctx,origin,suffix='/'):
                    p=ctx.new_page()
                    p.on('pageerror',lambda exc:report['pageErrors'].append(str(exc)))
                    p.on('response',lambda response:report['serverErrors'].append({'status':response.status,'path':urlsplit(response.url).path}) if response.status>=500 else None)
                    p.goto(origin+suffix)
                    return p
                def tv_context(origin,secret):
                    ctx=context(origin,viewport={'width':1920,'height':1080})
                    ctx.add_cookies([{'name':'household_tv','value':secret,'url':origin,'httpOnly':True,'sameSite':'Lax'}])
                    screen=page(ctx,origin,'/tv')
                    expect(screen.locator('body.tv .board[data-tv-count]')).to_be_visible()
                    return ctx,screen
                phone=context(base,viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
                phone.request.get(base+'/api/me')
                assert phone.request.post(base+'/api/login',data={'username':'member1','password':PASSWORD}).status==200
                mobile=page(phone,base)
                mobile.wait_for_function("()=>user?.role==='member' && !!window.TVDisplay")
                mobile.evaluate('(id)=>TVDisplay.openDevice(id)',uid)
                controls=mobile.locator('.media-tv-controls')
                expect(controls.locator('[data-playback="start"]')).to_be_enabled()
                assert controls.evaluate('(n)=>n.scrollWidth<=n.clientWidth+2')
                assert mobile.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
                check('phone_390px_actual_tv_settings_mount_no_overflow')
                tv,screen=tv_context(base,secret)
                tv2,screen2=tv_context(base,second_secret)
                othertv,otherscreen=tv_context(other_base,other_secret)
                image=screen.locator('.media-tv-screen img')
                expect(screen.locator('.media-tv-screen')).to_be_hidden()
                controls.locator('[data-playback="start"]').click()
                expect(image).to_be_visible(timeout=10000)
                assert image.evaluate('(n)=>n.naturalWidth===20 && n.naturalHeight===12')
                expect(screen2.locator('.media-tv-screen')).to_be_hidden()
                expect(otherscreen.locator('.media-tv-screen')).to_be_hidden()
                check('start_only_selected_device_actual_encrypted_preview_other_household_unchanged')
                controls.locator('[data-playback="pause"]').click()
                expect(controls.locator('[data-playback="resume"]')).to_be_enabled()
                expect(screen.locator('.media-tv-progress')).to_contain_text('已暂停',timeout=6000)
                first=image.get_attribute('src')
                controls.locator('[data-playback="next"]').click()
                screen.wait_for_function('(src)=>document.querySelector(".media-tv-screen img").src!==src && !document.querySelector(".media-tv-screen img").hidden',arg=first)
                controls.locator('[data-playback="previous"]').click()
                expect(controls.locator('[data-playback-status]')).to_contain_text('已保存')
                controls.locator('select').select_option('5')
                controls.locator('[data-playback="interval"]').click()
                expect(controls.locator('select')).to_have_value('5')
                expect(controls.locator('[data-playback="resume"]')).to_be_enabled()
                controls.locator('[data-playback="resume"]').click()
                expect(controls.locator('[data-playback="pause"]')).to_be_enabled()
                env[2][0]+=6
                check('pause_resume_previous_next_interval_real_commands')
                screen.screenshot(path=str(out/'television-1920.png'))
                mobile.screenshot(path=str(out/'phone-390.png'),full_page=True)
                # Offline clears the actual displayed object URL immediately, then safely recovers.
                expect(image).to_be_visible(timeout=6000)
                tv.set_offline(True)
                expect(image).to_be_hidden(timeout=1500)
                assert image.get_attribute('src') is None
                tv.set_offline(False)
                expect(image).to_be_visible(timeout=9000)
                check('offline_immediate_clear_and_online_authorized_recovery')
                # Genuine server response, with a deliberately shorter valid lease.
                fault['shortLease']=True
                screen.wait_for_timeout(2200)
                fault['blockState']=True
                expect(image).to_be_hidden(timeout=4000)
                assert image.get_attribute('src') is None
                fault['shortLease']=False;fault['blockState']=False
                expect(image).to_be_visible(timeout=12000)
                check('short_lease_expiry_clears_while_next_state_request_stalls')
                # Hold an authorized image response, clear locally, then release its old bytes.
                fault['previewDelay']=True
                controls.locator('[data-playback="next"]').click()
                deadline=time.time()+7
                while not gates['preview'][0].is_set() and time.time()<deadline:
                    screen.wait_for_timeout(50)
                assert gates['preview'][0].is_set()
                tv.set_offline(True)
                gates['preview'][1].set()
                screen.wait_for_timeout(500)
                expect(image).to_be_hidden()
                assert image.get_attribute('src') is None
                tv.set_offline(False)
                expect(image).to_be_visible(timeout=9000)
                check('late_authorized_image_response_cannot_resurrect_after_offline_clear')
                # Actual grant revocation makes next snapshot empty and preview endpoint forbidden.
                for item in items:
                    result=owner.put('/api/media/items/'+item['id']+'/tv-grants',headers=headers,json={
                        'revision':item['revision'],'deviceIds':[]})
                    assert result.status_code==200
                expect(image).to_be_hidden(timeout=6000)
                expect(screen.locator('.media-tv-screen p')).to_contain_text('没有可播放')
                controls.locator('[data-playback="refresh"]').click()
                expect(controls.locator('[data-playback="start"]')).to_be_disabled()
                check('actual_grant_revocation_clears_and_phone_cannot_start_private_photos')
                controls.locator('[data-playback="dashboard"]').click()
                expect(screen.locator('.media-tv-screen')).to_be_hidden(timeout=6000)
                expect(screen.locator('.board')).to_be_visible()
                check('return_to_existing_dashboard_preserves_layout')
                # A delayed real /me response cannot issue control after local identity changes.
                prior=counts.get('PUT '+('/api/media-playback/devices/'+uid),0)
                fault['memberDelay']=True
                controls.locator('[data-playback="interval"]').click()
                deadline=time.time()+5
                while not gates['member'][0].is_set() and time.time()<deadline:
                    mobile.wait_for_timeout(50)
                assert gates['member'][0].is_set()
                mobile.evaluate("user={...user,id:'member2'};csrf='synthetic-changed-csrf'")
                expect(controls).to_contain_text('登录或家庭已变化')
                gates['member'][1].set()
                mobile.wait_for_timeout(300)
                assert counts.get('PUT '+('/api/media-playback/devices/'+uid),0)==prior
                check('identity_change_drops_delayed_me_and_sends_no_control_write')
                screen.evaluate("user={...user,householdId:'synthetic-different-household'}")
                expect(screen.locator('.media-tv-screen')).to_have_count(0)
                check('tv_identity_change_removes_display_surface')
                assert not report['pageErrors'],report['pageErrors']
                assert not report['serverErrors'],report['serverErrors']
                assert not report['externalRequests'],report['externalRequests']
                report['requestCounts']=counts
                report['passed']=True
                browser.close()
            # Threaded request handlers may still be finishing an injected timeout.
            for server in servers:
                server.shutdown();server.server_close()
            for thread in threads:
                thread.join(3)
            servers.clear()
    except Exception as error:
        report['failure']={'type':type(error).__name__,'message':str(error)}
        raise
    finally:
        for pair in gates.values():
            pair[1].set()
        for server in servers:
            server.shutdown();server.server_close()
        for thread in threads:
            thread.join(3)
        changes.undo()
        stamp=datetime.now().strftime('%Y%m%dT%H%M%S')
        target=out/('browser-'+stamp+'.json')
        target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'report':str(target)},ensure_ascii=False))


if __name__=='__main__':
    main()
