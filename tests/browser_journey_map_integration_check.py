"""Real map navigation, API and SQLite on loopback, with synthetic household data.

Run only after the fixed map UI and land candidates are Git-merged with wiring.
No contract double, external services, production data or model calls.
"""
from datetime import datetime, timezone
from contextlib import closing, ExitStack
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import create_app
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server, WSGIRequestHandler


class Quiet(WSGIRequestHandler):
    def log(self, *_args, **_kwargs):
        pass


def main():
    out = ROOT / 'test-results'
    out.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target = out / ('journey-map-real-' + stamp + '.json')
    names = set(subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')) - {''}
    names.add(Path(__file__).relative_to(ROOT).as_posix())
    def hashes():
        return {n: hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in sorted(names)}
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], providerCalls=0,
                  productionWrites=0, realCloudWrites=0, sourceHashesBefore=hashes(), screenshots=[],
                  scope='Real Flask factory, SQLite, full application HTML and Edge; synthetic data on loopback only.')
    def passed(name):
        report['checks'].append(name)
        print('PASS ' + name, flush=True)
    def deny(*_args, **_kwargs):
        report['providerCalls'] += 1
        raise AssertionError('Provider IO forbidden')
    original = socket.socket.connect
    def connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
            report['externalRequests'].append('blocked socket')
            raise AssertionError('External socket forbidden')
        return original(sock, address)
    server = None
    def stop_server():
        nonlocal server
        if server:
            server.shutdown(); server.server_close(); server = None
    try:
        with patch.object(socket.socket, 'connect', connect), ExitStack() as lifecycle:
            folder = lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='real-map-'))
            assert Path(folder).resolve().parent == Path(tempfile.gettempdir()).resolve()
            assert Path(folder).name.startswith('real-map-')
            config = dict(TESTING=True, DATA_DIR=folder, SECRET_KEY='synthetic-map-integration', SESSION_COOKIE_SECURE=False,
                          MEMBER1_PASSWORD='synthetic-map-password-one', MEMBER2_PASSWORD='synthetic-map-password-two',
                          MICROSOFT_CLIENT_ID='', MICROSOFT_CLIENT_SECRET='', GOOGLE_CLIENT_ID='', GOOGLE_CLIENT_SECRET='',
                          ASSISTANT_PROVIDER='local', NVIDIA_API_KEY='', NVIDIA_MODEL='', OPENAI_API_KEY='', OPENAI_MODEL='',
                          CLOUD_TRANSPORT=deny, OAUTH_TRANSPORT=deny)
            application = create_app(config)
            fixture = application.test_client()
            assert fixture.post('/api/login', json={'username':'member1','password':config['MEMBER1_PASSWORD']}).status_code == 200
            headers = {'X-CSRF-Token':fixture.get('/api/me').json['csrf']}
            plan = json.loads((ROOT/'static/examples/journey-plan-v2.json').read_text(encoding='utf-8'))
            plan['title'] = '合成地图关联旅行'
            preview = fixture.post('/api/journeys/preview', json={'plan':plan}, headers=headers)
            assert preview.status_code == 200
            applied = fixture.post('/api/journeys/apply', json={'previewToken':preview.json['previewToken'], 'idempotencyKey':'synthetic-map-trip'}, headers=headers)
            assert applied.status_code in (200, 201)
            journey_id = applied.json['id']
            seeded = fixture.post('/api/journey-places', json={'requestId':'synthetic-private-place','name':'OWNER-PRIVATE-PLACE','coordinates':{'latitude':10.123456,'longitude':20.654321}}, headers=headers)
            assert seeded.status_code == 201
            server = make_server('127.0.0.1', 0, application, threaded=True, request_handler=Quiet)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            lifecycle.callback(stop_server)
            base = 'http://127.0.0.1:' + str(server.server_port)
            with sync_playwright() as pw:
                browser = pw.chromium.launch(channel='msedge', headless=True)
                def context(width=1440):
                    ctx = browser.new_context(viewport={'width':width,'height':1000})
                    def route(handler):
                        if urlsplit(handler.request.url).hostname != '127.0.0.1':
                            report['externalRequests'].append(handler.request.url)
                            handler.abort()
                        else:
                            handler.continue_()
                    ctx.route('**/*', route)
                    ctx.on('page', lambda p:p.on('pageerror', lambda e:report['pageErrors'].append(str(e))))
                    return ctx
                def auth(ctx):
                    me = ctx.request.get(base+'/api/me')
                    assert me.status == 200
                    return {'X-CSRF-Token':me.json()['csrf']}
                def get_places(ctx):
                    response = ctx.request.get(base+'/api/journey-places')
                    assert response.status == 200
                    return response.json()['items']
                ctx = context()
                page = ctx.new_page()
                page.goto(base)
                page.locator('#login-form [name=password]').fill(config['MEMBER1_PASSWORD'])
                page.locator('#login-form [type=submit]').click()
                page.locator('.ps-sidebar [data-ps-route=map]').click()
                expect(page.locator('[data-jm=new]')).to_be_enabled()
                expect(page.locator('.jm-land')).to_have_count(1)
                expect(page.locator('.jm-place').filter(has_text='OWNER-PRIVATE-PLACE')).to_have_count(1)
                passed('member login and real map route/local basemap')
                page.locator('[data-jm=new]').click()
                form = page.locator('[data-jm-editor]')
                form.locator('[name=name]').fill('合成地图新地点')
                form.locator('[name=country]').fill('合成地区')
                form.locator('[name=city]').fill('合成城市')
                form.locator('[name=latitude]').fill('31.234567')
                form.locator('[name=longitude]').fill('121.456789')
                form.locator('[name=journeyId]').select_option(journey_id)
                form.locator('[name=name]').focus()
                page.evaluate("()=>{window.mapDraftNode=document.querySelector('[data-jm-editor] [name=name]');mapDraftNode.setSelectionRange(2,5);}")
                page.evaluate('async()=>{await refresh(true)}')
                assert page.evaluate("()=>document.activeElement===mapDraftNode && mapDraftNode.isConnected && mapDraftNode.selectionStart===2 && mapDraftNode.selectionEnd===5")
                expect(form.locator('[name=name]')).to_have_value('合成地图新地点')
                passed('real state refresh preserves draft node, focus and text selection')
                form.locator('[name=status]').select_option('visited')
                form.locator('[type=submit]').click()
                expect(form.locator('.jm-error')).to_contain_text('确认')
                assert len(get_places(ctx)) == 1
                form.locator('[name=confirmVisited]').check()
                form.locator('[type=submit]').click()
                expect(page.locator('[data-jm-editor]')).to_have_count(0)
                saved = next(p for p in get_places(ctx) if p['name']=='合成地图新地点')
                assert saved['status']=='visited' and saved['visitedConfirmedAt'] and saved['visibility']=='private'
                assert saved['journeyId']==journey_id
                passed('UI explicit visit confirmation persists one real private place')
                page.reload()
                row = page.locator('.jm-place[data-id="'+saved['id']+'"]')
                expect(row).to_be_visible()
                row.click()
                page.locator('[data-jm=journey]').click()
                expect(page.locator('#dialog')).to_be_visible()
                expect(page.locator('#dialog')).to_contain_text('合成地图关联旅行')
                page.evaluate('()=>closeModal()')
                expect(row).to_be_visible()
                passed('reload and linked real journey dialog return to same map')
                page.locator('[data-jm=edit]').click()
                form = page.locator('[data-jm-editor]')
                form.locator('[name=visibility]').select_option('shared')
                form.locator('[name=coordinateDisclosure]').select_option('coarse')
                form.locator('[type=submit]').click()
                expect(page.locator('[data-jm-editor]')).to_have_count(0)
                partner = context(390)
                assert partner.request.post(base+'/api/login', data={'username':'member2','password':config['MEMBER2_PASSWORD']}).status == 200
                other = partner.new_page()
                other.goto(base+'/#map')
                shared_row = other.locator('.jm-place[data-id="'+saved['id']+'"]')
                expect(shared_row).to_be_visible()
                shared_row.click()
                expect(other.locator('[data-jm=edit]')).to_have_count(0)
                body = other.locator('#ps-map-workspace').inner_text()
                assert 'OWNER-PRIVATE-PLACE' not in body and '31.234567' not in body
                projected = get_places(partner)
                assert len(projected)==1 and projected[0]['coordinates']=={'latitude':31.2,'longitude':121.5}
                passed('partner UI and server response enforce private/approximate projection')
                other.evaluate("()=>document.documentElement.dataset.theme='light'")
                assert other.evaluate('()=>document.documentElement.scrollWidth <= innerWidth+1')
                image = out/('journey-map-real-'+stamp+'-mobile.png')
                other.screenshot(path=str(image), full_page=True)
                report['screenshots'].append(str(image))
                passed('390px actual application navigation and map without horizontal overflow')
                page.locator('[data-jm=edit]').click()
                form = page.locator('[data-jm-editor]')
                form.locator('[name=visibility]').select_option('private')
                form.locator('[type=submit]').click()
                expect(page.locator('[data-jm-editor]')).to_have_count(0)
                other.locator('[data-jm=refresh]').click()
                expect(other.locator('.jm-place')).to_have_count(0)
                assert partner.request.get(base+'/api/journey-places/'+saved['id']).status == 404
                passed('unshare removes partner record on next read and denies server detail')
                page.locator('[data-jm=edit]').click()
                form = page.locator('[data-jm-editor]')
                form.locator('[name=name]').fill('保留的并发草稿')
                current = next(p for p in get_places(ctx) if p['id']==saved['id'])
                assert ctx.request.patch(base+'/api/journey-places/'+saved['id'], headers=auth(ctx), data={'revision':current['revision'],'name':'并发服务器名称','confirmVisited':True}).status == 200
                form.locator('[name=confirmVisited]').check()
                form.locator('[type=submit]').click()
                expect(page.locator('[data-jm=retry-pending]')).to_be_enabled()
                page.locator('[data-jm=retry-pending]').click()
                expect(page.locator('[data-jm=keep-draft]')).to_be_visible()
                expect(form.locator('[name=name]')).to_have_value('保留的并发草稿')
                page.locator('[data-jm=keep-draft]').click()
                form.locator('[type=submit]').click()
                expect(page.locator('[data-jm-editor]')).to_have_count(0)
                assert next(p for p in get_places(ctx) if p['id']==saved['id'])['name']=='保留的并发草稿'
                passed('real revision conflict preserves draft and requires explicit resave')
                shot = out/('journey-map-real-'+stamp+'-desktop.png')
                page.screenshot(path=str(shot), full_page=True)
                report['screenshots'].append(str(shot))
                page.locator('[data-jm=new]').click()
                page.locator('[data-jm-editor] [name=name]').fill('PRIVATE-UNSAVED-DRAFT')
                assert ctx.request.post(base+'/api/logout', headers=auth(ctx), data={}).status == 200
                assert ctx.request.post(base+'/api/login', data={'username':'member2','password':config['MEMBER2_PASSWORD']}).status == 200
                page.evaluate('async()=>{await boot()}')
                expect(page.locator('#ps-map-workspace')).not_to_contain_text('PRIVATE-UNSAVED-DRAFT')
                expect(page.locator('.jm-place')).to_have_count(0)
                passed('actual cookie/account switch clears old map and private draft')
                page.close()
                other.close()
                server.app = create_app(config)
                restarted = partner.new_page()
                restarted.goto(base+'/#map')
                expect(restarted.locator('[data-jm=new]')).to_be_enabled()
                with closing(sqlite3.connect(Path(folder)/'household.sqlite3')) as con:
                    assert con.execute('SELECT count(*) FROM journey_places WHERE deleted_at IS NULL').fetchone()[0]==2
                    assert con.execute('PRAGMA foreign_key_check').fetchall()==[]
                passed('factory restart preserves real SQLite places and session privacy')
                browser.close()
                assert not report['pageErrors'] and not report['externalRequests'] and report['providerCalls']==0
                report['passed']=True
    except Exception:
        report['passed']=False
        report['failure']=traceback.format_exc()
        print(report['failure'], flush=True)
    finally:
        stop_server()
        report['sourceHashesAfter']=hashes()
        report['sourceUnchanged']=report['sourceHashesAfter']==report['sourceHashesBefore']
        report['passed']=report['passed'] and report['sourceUnchanged']
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'report':str(target)}), flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
