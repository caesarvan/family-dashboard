"""Real application/SQLite/Edge/worker; only Google transport is synthetic."""
from contextlib import ExitStack, closing
from datetime import datetime, timezone
from io import BytesIO
import argparse
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
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import create_app, Problem
from cloud_accounts import GOOGLE_PHOTOS_SCOPE
from flask import g
from google_photos_picker import GooglePhotosPicker
from household_media import register_media_library
from media_import_worker import MediaImportWorker
from PIL import Image, PngImagePlugin
from playwright.sync_api import expect, sync_playwright
from test_google_photos_picker import Response, item, session
from werkzeug.serving import make_server, WSGIRequestHandler


class Quiet(WSGIRequestHandler):
    def log(self, *_args, **_kwargs):
        pass


class SyntheticGoogle:
    """Fake provider boundary, never a substitute household business endpoint."""
    def __init__(self):
        self.selected = False
        self.deleted = False
        self.calls = []
        self.oauth_calls = 0
        self.identity_calls = 0
        output = BytesIO()
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text('private-source-marker', 'synthetic-original-metadata')
        Image.new('RGB', (600, 400), '#729c99').save(output, 'PNG', pnginfo=metadata)
        self.png = output.getvalue()

    def tokens(self, provider, params):
        assert provider == 'google'
        assert params.get('code') == 'synthetic-photo-code' or params.get('refresh_token') == 'synthetic-refresh'
        self.oauth_calls += 1
        return {'access_token':'synthetic-access', 'refresh_token':'synthetic-refresh',
                'expires_in':3600, 'scope':GOOGLE_PHOTOS_SCOPE}

    def provider(self, provider, token, transport=None):
        assert provider == 'google' and token == 'synthetic-access'
        outer = self
        class Identity:
            def identity(self):
                outer.identity_calls += 1
                return {'subject':'synthetic-photo-owner', 'name':'合成照片账户', 'email':'synthetic@example.test'}
        return Identity()

    def picker(self, method, url, *, headers, body, timeout):
        assert headers['Authorization'] == 'Bearer synthetic-access'
        parsed = urlsplit(url)
        self.calls.append({'method':method, 'host':parsed.hostname, 'path':parsed.path})
        if method == 'POST' and parsed.path == '/v1/sessions':
            assert json.loads(body)['pickingConfig']['maxItemCount'] == '20'
            value = session(False, pollingConfig={'pollInterval':'1s','timeoutIn':'600s'})
        elif method == 'GET' and parsed.path.startswith('/v1/sessions/'):
            value = session(self.selected, pollingConfig={'pollInterval':'1s','timeoutIn':'600s'})
        elif method == 'GET' and parsed.path == '/v1/mediaItems':
            assert self.selected
            value = {'mediaItems':[item()]}
        elif method == 'GET' and parsed.hostname == 'lh3.googleusercontent.com':
            assert self.selected and not self.deleted
            value = Response(self.png, mime='image/png')
        elif method == 'DELETE' and parsed.path.startswith('/v1/sessions/'):
            self.deleted = True
            value = Response(b'', status=204)
        else:
            raise AssertionError('Unexpected synthetic provider operation')
        result = value if isinstance(value, Response) else Response(value)
        result.url = url
        return result


def install_if_missing(application, *, require_factory=False):
    """Remove the need for this fallback once reviewed factory wiring is merged."""
    if 'household_media' in application.extensions:
        return 'factory'
    if require_factory:
        raise AssertionError('Factory media registration is required; fixture fallback refused')
    assert not application._got_first_request
    def db():
        if 'media_integration_db' not in g:
            con = sqlite3.connect(Path(application.config['DATA_DIR'])/'household.sqlite3')
            con.row_factory = sqlite3.Row
            con.execute('PRAGMA foreign_keys=ON')
            g.media_integration_db = con
        return g.media_integration_db
    @application.teardown_appcontext
    def close(_error):
        con = g.pop('media_integration_db', None)
        if con is not None:
            con.close()
    def member():
        if not getattr(g, 'actor', None) or g.actor['role'] != 'member':
            raise Problem('Only current household members', 403)
    register_media_library(application, db, Problem, None, member, None)
    return 'explicit fixture registration before first request'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-factory', action='store_true', help='Refuse explicit fixture registration; verify actual app/child/restart wiring')
    options = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out = ROOT/'test-results'/('media-integration-'+stamp)
    out.mkdir(parents=True, exist_ok=False)
    names = set(subprocess.check_output(['git','ls-files','-z'], cwd=ROOT).decode().split('\0'))-{''}
    names.add(Path(__file__).relative_to(ROOT).as_posix())
    if (ROOT/'docs/MEDIA-INTEGRATION-CHECK.md').exists():
        names.add('docs/MEDIA-INTEGRATION-CHECK.md')
    def hashes():
        return {n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in sorted(names)}
    report = {'passed':False, 'checks':[], 'pageErrors':[], 'externalRequests':[], 'registration':[],
              'sourceHashesBefore':hashes(), 'screenshots':[], 'realGoogle':False, 'physicalTelevision':False,
              'gitHead':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
              'requireFactory':options.require_factory,
              'scope':'Real Flask factory, household routing/auth, media API, SQLite, worker, Picker, Pillow, crypto and full application shell in Edge. Google OAuth/identity/Picker network only is synthetic.'}
    def passed(name):
        report['checks'].append(name)
        print('PASS '+name, flush=True)
    original_connect = socket.socket.connect
    def connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1','::1','localhost'):
            report['externalRequests'].append('blocked non-loopback socket')
            raise AssertionError('External socket forbidden')
        return original_connect(sock, address)
    google = SyntheticGoogle()
    server = None
    thread = None
    def stop():
        nonlocal server
        if server:
            if thread and thread.is_alive():
                server.shutdown()
            server.server_close(); server = None
        if thread:
            thread.join(timeout=5)
            assert not thread.is_alive()
    try:
        with ExitStack() as lifecycle:
            lifecycle.enter_context(patch.object(socket.socket, 'connect', connect))
            folder = lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='media-browser-'))
            # Allocate the loopback TLS listener first so the actual OAuth host
            # check uses its exact configured origin, with no bypass or rewrite.
            server = make_server('127.0.0.1', 0, None, threaded=True, request_handler=Quiet, ssl_context='adhoc')
            lifecycle.callback(stop)
            base = 'https://127.0.0.1:'+str(server.server_port)
            config = dict(TESTING=True, DATA_DIR=folder, SECRET_KEY='synthetic-media-browser-key', SESSION_COOKIE_SECURE=True,
                          MEMBER1_PASSWORD='synthetic-media-password-one', MEMBER2_PASSWORD='synthetic-media-password-two',
                          PUBLIC_ORIGIN=base, GOOGLE_CLIENT_ID='synthetic-client', GOOGLE_CLIENT_SECRET='synthetic-secret',
                          MICROSOFT_CLIENT_ID='', MICROSOFT_CLIENT_SECRET='', ASSISTANT_PROVIDER='local', NVIDIA_API_KEY='',
                          NVIDIA_MODEL='', OPENAI_API_KEY='', OPENAI_MODEL='', OAUTH_TRANSPORT=google.tokens, CLOUD_PROVIDER_FACTORY=google.provider)
            application = create_app(config)
            report['registration'].append(install_if_missing(application, require_factory=options.require_factory))
            server.app = application
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            with sync_playwright() as pw, ExitStack() as browser_lifecycle:
                browser = pw.chromium.launch(channel='msedge', headless=True)
                browser_lifecycle.callback(browser.close)
                def context():
                    ctx = browser.new_context(viewport={'width':1440,'height':1000}, ignore_https_errors=True)
                    def route(handler):
                        url = urlsplit(handler.request.url)
                        if url.hostname == '127.0.0.1':
                            handler.continue_()
                        elif url.hostname == 'accounts.google.com':
                            params = parse_qs(url.query)
                            assert GOOGLE_PHOTOS_SCOPE in params['scope'][0]
                            assert 'calendar' not in params['scope'][0]
                            target = base+'/auth/google/callback?'+urlencode({'state':params['state'][0], 'code':'synthetic-photo-code'})
                            handler.fulfill(status=302, headers={'Location':target}, body='')
                        elif url.hostname == 'photos.google.com' and url.path == '/picker/synthetic':
                            google.selected = True
                            handler.fulfill(content_type='text/html', body='<p>Synthetic Google selection complete.</p>')
                        else:
                            report['externalRequests'].append(url.hostname)
                            handler.abort()
                    ctx.route('**/*', route)
                    ctx.on('page', lambda p:p.on('pageerror', lambda e:report['pageErrors'].append(str(e))))
                    return ctx
                def auth(ctx):
                    result = ctx.request.get(base+'/api/me'); assert result.status == 200
                    return {'X-CSRF-Token':result.json()['csrf']}
                def api(ctx, path):
                    response = ctx.request.get(base+path); assert response.status == 200, response.text()
                    return response.json()
                def login(ctx, number=1):
                    response = ctx.request.post(base+'/api/login', data={'username':f'member{number}','password':config[f'MEMBER{number}_PASSWORD']})
                    assert response.status == 200
                owner = context(); page = owner.new_page(); page.goto(base)
                page.locator('#login-form [name=password]').fill(config['MEMBER1_PASSWORD'])
                page.locator('#login-form [type=submit]').click()
                expect(page.locator('.ps-sidebar [data-ps-route=photos]')).to_be_visible()
                plan = json.loads((ROOT/'static/examples/journey-plan-v2.json').read_text(encoding='utf-8'))
                plan['title'] = '合成相册关联旅行'
                proposed = owner.request.post(base+'/api/journeys/preview', headers=auth(owner), data={'plan':plan})
                assert proposed.status == 200, proposed.text()
                journey = owner.request.post(base+'/api/journeys/apply', headers=auth(owner), data={'previewToken':proposed.json()['previewToken'],'idempotencyKey':'synthetic-media-journey'})
                assert journey.status == 201, journey.text()
                journey_id = journey.json()['id']
                televisions = []
                for name in ('合成客厅屏幕','合成卧室屏幕'):
                    tv = context()
                    pairing = tv.request.post(base+'/api/pair/start', data={}).json()
                    approved = owner.request.post(base+'/api/pair/approve', headers=auth(owner), data={'code':pairing['code'],'name':name})
                    assert approved.status == 200
                    assert tv.request.post(base+'/api/pair/poll', data={'secret':pairing['secret']}).json()['approved']
                    device = next(x for x in api(owner,'/api/devices') if x['name']==name)
                    televisions.append((device['id'],tv))
                page.locator('.ps-sidebar [data-ps-route=photos]').click()
                expect(page.locator('[data-hm=connect]')).to_be_enabled()
                page.locator('[data-hm=connect]').click()
                expect(page.locator('[data-hm-account]')).to_contain_text('合成照片账户')
                expect(page.locator('#ps-media-workspace')).to_be_visible()
                assert page.url.endswith('#photos')
                assert not page.locator('#dialog[open]').count()
                accounts = api(owner,'/api/accounts')['accounts']; assert len(accounts)==1 and len(accounts[0]['id'])==32
                assert google.oauth_calls == 1 and google.identity_calls == 1
                passed('real Photos OAuth callback opens photo shell without calendar selection')
                page.locator('[data-hm=create]').click()
                assert api(owner,'/api/media/imports')['total']==0
                page.locator('[data-hm-temporary]').check(); page.locator('[data-hm=create]').click()
                expect(page.locator('[data-hm-import]')).to_contain_text('正在准备')
                engine = application.extensions['household_media']
                worker = MediaImportWorker(engine, picker_factory=lambda token:GooglePhotosPicker(token, transport=google.picker))
                assert worker.tick()
                page.locator('[data-hm=poll]').click()
                expect(page.locator('[data-hm-import] a[target=_blank]')).to_be_visible()
                with page.expect_popup() as selected:
                    page.locator('[data-hm-import] a[target=_blank]').click()
                selected.value.wait_for_load_state(); selected.value.close(); assert google.selected
                time.sleep(1.1)
                for _ in range(4): assert worker.tick()
                assert google.deleted and not worker.tick()
                page.locator('[data-hm=poll]').click()
                expect(page.locator('[data-hm-candidate]')).to_have_count(1)
                assert api(owner,'/api/media/items')['total']==0
                with engine.transaction() as con:
                    row = dict(con.execute('SELECT * FROM media_items').fetchone())
                    assert row['state']=='staged' and row['visibility']=='private'
                    assert b'synthetic-original-metadata' not in bytes(row['metadata_cipher'])
                    assert not bytes(row['preview_cipher']).startswith(b'\xff\xd8')
                media_id = row['id']; preview_path = '/api/media/items/'+media_id+'/preview'
                response = owner.request.get(base+preview_path); assert response.status==200
                jpeg = response.body()
                assert jpeg!=google.png and b'synthetic-original-metadata' not in jpeg
                with Image.open(BytesIO(jpeg)) as image:
                    assert image.format=='JPEG' and image.size==(600,400) and not image.getexif()
                passed('real worker produces sanitized encrypted private staging from explicit synthetic Picker selection')
                page.locator('[data-hm-candidate]').check(); page.locator('[data-hm=confirm]').click()
                assert api(owner,'/api/media/items')['total']==0
                page.locator('[data-hm-persist]').check(); page.locator('[data-hm=confirm]').click()
                expect(page.locator('.hm-card')).to_have_count(1)
                assert api(owner,'/api/media/items')['items'][0]['visibility']=='private'
                partner = context(); login(partner,2)
                assert partner.request.get(base+preview_path).status==404
                assert all(api(tv,'/api/media-tv/items')['items']==[] for _,tv in televisions)
                passed('explicit persistence consent saves one private photo; partner and both TVs remain denied')
                page.locator('[data-hm=detail]').click(); form=page.locator('[data-hm-editor]')
                expect(form).to_be_visible(); form.locator('[name=caption]').fill('合成照片说明')
                form.locator('[name=journeyId]').select_option(journey_id)
                form.locator('[name=visibility]').select_option('shared'); form.locator('[type=submit]').click()
                expect(page.locator('[data-hm-message]')).to_contain_text('照片信息已保存')
                assert api(partner,'/api/media/items?scope=visible')['total']==1
                assert partner.request.get(base+preview_path).status==200
                assert all(api(tv,'/api/media-tv/items')['items']==[] for _,tv in televisions)
                passed('journey association and household sharing do not implicitly grant television')
                first_id,first_tv=televisions[0]; _,second_tv=televisions[1]
                page.locator(f'[data-hm-device="{first_id}"]').check(); page.locator('[data-hm=save-grants]').click()
                assert api(first_tv,'/api/media-tv/items')['items']==[]
                page.locator('[data-hm-tv-consent]').check(); page.locator('[data-hm=save-grants]').click()
                expect(page.locator('[data-hm-message]')).to_contain_text('电视展示范围已保存')
                tv_projection=api(first_tv,'/api/media-tv/items')['items']
                assert len(tv_projection)==1 and set(tv_projection[0])=={'id','width','height','previewUrl'}
                assert first_tv.request.get(base+tv_projection[0]['previewUrl']).status==200
                assert api(second_tv,'/api/media-tv/items')['items']==[]
                assert first_tv.request.get(base+'/api/media/items').status==403
                passed('separate explicit per-device grant permits only chosen paired TV and minimal projection')
                form.locator('[name=caption]').fill('PRIVATE-UNSAVED-MEDIA-DRAFT')
                form.locator('[name=caption]').focus()
                page.evaluate("()=>{window.savedMediaNode=document.querySelector('[data-hm-editor] [name=caption]');savedMediaNode.setSelectionRange(2,6)}")
                page.evaluate('async()=>{await refresh(true)}')
                assert page.evaluate('()=>document.activeElement===savedMediaNode && savedMediaNode.isConnected && savedMediaNode.selectionStart===2 && savedMediaNode.selectionEnd===6')
                expect(form.locator('[name=caption]')).to_have_value('PRIVATE-UNSAVED-MEDIA-DRAFT')
                passed('real shell state refresh preserves same draft node focus and selection')
                form.locator('[name=caption]').fill('合成照片说明'); form.locator('[name=visibility]').select_option('private');form.locator('[type=submit]').click()
                expect(page.locator('[data-hm-message]')).to_contain_text('照片信息已保存')
                assert partner.request.get(base+preview_path).status==404
                assert api(first_tv,'/api/media-tv/items')['items']==[]
                assert first_tv.request.get(base+'/api/media-tv/items/'+media_id+'/preview').status==404
                passed('privacy withdrawal immediately denies partner and formerly granted TV on real API')
                page.reload(); expect(page.locator('.hm-card')).to_have_count(1)
                page.locator('[data-hm=detail]').click();expect(page.locator('[data-hm-editor]')).to_be_visible()
                page.screenshot(path=str(out/'desktop.png'), full_page=True);report['screenshots'].append(str(out/'desktop.png'))
                # Restart the real factory over the same SQLite and retain browser cookies.
                replacement = create_app(config)
                report['registration'].append(install_if_missing(replacement, require_factory=options.require_factory))
                server.app=replacement
                page.reload();expect(page.locator('.hm-card')).to_have_count(1)
                assert owner.request.get(base+preview_path).body()==jpeg
                persisted = api(owner, '/api/media/items/'+media_id)['item']
                assert persisted['caption']=='合成照片说明' and persisted['visibility']=='private'
                assert persisted['journey']['id']==journey_id
                assert partner.request.get(base+preview_path).status==404
                assert api(first_tv,'/api/media-tv/items')['items']==[]
                with closing(sqlite3.connect(Path(folder)/'household.sqlite3')) as con:
                    assert con.execute('PRAGMA foreign_key_check').fetchall()==[]
                    assert con.execute("SELECT count(*) FROM media_items WHERE state='ready'").fetchone()[0]==1
                passed('browser reload and factory restart preserve encrypted preview, journey and private ACL')
                page.locator('[data-hm=detail]').click();expect(page.locator('[data-hm-editor]')).to_be_visible()
                page.locator('[data-hm-editor] [name=caption]').fill('PRIVATE-ACCOUNT-SWITCH-DRAFT')
                assert owner.request.post(base+'/api/logout',headers=auth(owner),data={}).status==200
                login(owner,2);page.evaluate('async()=>{await boot()}')
                expect(page.locator('#ps-media-workspace')).not_to_contain_text('PRIVATE-ACCOUNT-SWITCH-DRAFT')
                expect(page.locator('.hm-card')).to_have_count(0)
                assert owner.request.get(base+preview_path).status==404
                passed('real member cookie switch clears old private media and draft')
                # Real invitation/redemption creates a second SQLite household, not a route double.
                admin=context();login(admin)
                invitation=admin.request.post(base+'/api/spaces/invitations',headers=auth(admin),data={})
                assert invitation.status==201,invitation.text()
                created=admin.request.post(base+'/api/spaces/redeem',data={'invitation':invitation.json()['invitation'],'name':'合成第二家庭','slug':'media-synthetic-two','MEMBER1_PASSWORD':config['MEMBER1_PASSWORD'],'MEMBER2_PASSWORD':config['MEMBER2_PASSWORD']})
                assert created.status==201,created.text()
                platform=replacement.extensions['household_platform']
                household=next(h for h in platform.households() if h['slug']=='media-synthetic-two')
                report['registration'].append(install_if_missing(platform.child(household), require_factory=options.require_factory))
                page.goto(base+created.json()['entry']);expect(page.locator('#login-form')).to_be_visible()
                page.locator('#login-form [name=password]').fill(config['MEMBER1_PASSWORD']);page.locator('#login-form [type=submit]').click()
                page.locator('.ps-sidebar [data-ps-route=photos]').click();expect(page.locator('[data-hm=connect]')).to_be_enabled()
                expect(page.locator('.hm-card')).to_have_count(0)
                assert api(owner,'/api/me')['user']['householdId']==household['id']
                assert owner.request.get(base+preview_path).status==404
                passed('real household route and independent SQLite deny previous household photo')
                report['providerOperations']=google.calls
                report['oauthCalls']=google.oauth_calls;report['identityCalls']=google.identity_calls
                assert not report['pageErrors'] and not report['externalRequests']
                report['passed']=True
    except Exception:
        report['passed']=False;report['failure']=traceback.format_exc();print(report['failure'],flush=True)
    finally:
        stop()
        report['sourceHashesAfter']=hashes();report['sourceUnchanged']=report['sourceHashesBefore']==report['sourceHashesAfter']
        report['passed']=report['passed'] and report['sourceUnchanged']
        target=out/'result.json';target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'report':str(target)}),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
