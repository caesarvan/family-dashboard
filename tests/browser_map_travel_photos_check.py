"""Real factory/SQLite/Edge map-to-photo navigation; synthetic data, no provider IO."""
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import traceback
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pytest
from playwright.sync_api import expect, sync_playwright
from test_household_media import configured, stage, confirm, selected, device
from test_journey_documents import PASSWORD, create_journey, login
from werkzeug.serving import make_server, WSGIRequestHandler


class Quiet(WSGIRequestHandler):
    def log(self, *_args, **_kwargs):
        pass


def main():
    out = ROOT/'test-results'/('map-travel-photos-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    names = ['static/journey-map.js', 'static/household-media.js', 'static/product-shell.js',
             'tests/browser_map_travel_photos_check.py']
    def hashes():
        return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], screenshots=[],
                  realGoogle=False, physicalTelevision=False, productionWrites=0,
                  gitHead=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                  sourceHashesBefore=hashes(), scope='Real Flask factory, encrypted media engine, SQLite, member cookies and Edge; synthetic seed only.')
    def passed(name):
        report['checks'].append(name)
        print('PASS '+name, flush=True)
    original = socket.socket.connect
    def local_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1','::1','localhost'):
            report['externalRequests'].append('blocked external socket')
            raise AssertionError('External network forbidden')
        return original(sock,address)
    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(socket.socket,'connect',local_connect))
            folder = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='map-photos-')))
            monkey = stack.enter_context(pytest.MonkeyPatch.context())
            env = configured(folder/'data',monkey)
            app,engine,_,_ = env
            app.config['HOUSEHOLD_INFO'].update(name='合成家庭',slug='home')
            owner,headers = login(app)
            journey = create_journey(owner,headers,'合成山海旅行')
            other_journey = create_journey(owner,headers,'其他旅行')
            assert journey['id'] != journey['tripId']
            def seed_photos(number, count, prefix, journey_id):
                client,h,detail,_ = stage(env,number,items=[selected(prefix+str(n)) for n in range(count)])
                confirm(client,h,detail)
                ids=[]
                for entry in detail['items']:
                    uid=entry['id']; current=client.get('/api/media/items/'+uid).json['item']
                    response=client.patch('/api/media/items/'+uid,headers=h,json={
                        'revision':current['revision'],'caption':prefix,'journeyId':journey_id,
                        'visibility':'private' if prefix=='PARTNER-PRIVATE' else 'shared' if number==2 else 'private'})
                    assert response.status_code==200,response.json
                    ids.append(uid)
                while (job:=engine.claim_next()) is not None:
                    assert job['action']=='cleanup'
                    assert engine.complete(job,None)
                return client,h,ids
            seed_photos(1,20,'OWNER-TARGET-A',journey['id'])
            seed_photos(1,5,'OWNER-TARGET-B',journey['id'])
            partner,ph,shared = seed_photos(2,1,'PARTNER-SHARED',journey['id'])
            seed_photos(2,1,'PARTNER-PRIVATE',journey['id'])
            seed_photos(1,1,'OTHER-JOURNEY',other_journey['id'])
            stage(env,1,items=[selected('UNCONFIRMED')])
            for number in range(101):
                response=owner.post('/api/journey-places',headers=headers,json={
                    'requestId':secrets.token_hex(16),'name':'地图回忆 '+str(number),'journeyId':journey['id'],
                    'status':'planned','startDate':'2026-12-01','endDate':'2026-12-04'})
                assert response.status_code==201,response.json
            query={'scope':'mine','owner':'member1','status':'planned','year':'2026','journeyId':journey['id'],'limit':100,'offset':100}
            chosen=owner.get('/api/journey-places',query_string=query).json['items'][0]
            # Shared place lets the partner exercise post-read ACL removal as well.
            shared_place=owner.post('/api/journey-places',headers=headers,json={
                'requestId':secrets.token_hex(16),'name':'SHARED-MAP-PLACE','visibility':'shared','journeyId':journey['id']}).json['place']
            _,_,tv_cookie=device(env)
            with engine.transaction() as con:
                before=[tuple(row) for row in con.execute('SELECT id,revision,visibility,journey_id FROM media_items ORDER BY id')]
                assert con.execute('SELECT count(*) FROM media_tv_grants').fetchone()[0]==0
            server=make_server('127.0.0.1',0,app,threaded=True,request_handler=Quiet)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            def stop():
                server.shutdown();server.server_close();thread.join(timeout=5)
            stack.callback(stop)
            base='http://127.0.0.1:'+str(server.server_port)
            with sync_playwright() as pw, ExitStack() as browser_stack:
                browser=pw.chromium.launch(channel='msedge',headless=True)
                browser_stack.callback(browser.close)
                def context(number=1,width=390):
                    ctx=browser.new_context(viewport={'width':width,'height':844})
                    def local_route(route):
                        if urlsplit(route.request.url).hostname=='127.0.0.1':
                            route.continue_()
                        else:
                            report['externalRequests'].append(urlsplit(route.request.url).hostname)
                            route.abort()
                    ctx.route('**/*',local_route)
                    ctx.on('page',lambda page:page.on('pageerror',lambda error:report['pageErrors'].append(str(error))))
                    result=ctx.request.post(base+'/api/login',data={'username':'member'+str(number),'password':PASSWORD})
                    assert result.status==200
                    return ctx
                ctx=context(); page=ctx.new_page(); reads=[];writes=[]
                page.on('request',lambda request:reads.append(request.url) if request.method=='GET' else writes.append(request.url))
                page.goto(base+'/#map')
                expect(page.locator('[data-jm=refresh]')).to_be_enabled()
                form=page.locator('[data-jm-filters]')
                form.locator('[name=status]').select_option('planned'); form.locator('[name=year]').fill('2026')
                form.locator('[name=scope]').select_option('mine');form.locator('[name=owner]').select_option('member1')
                form.locator('[name=journeyId]').select_option(journey['id']);form.locator('[type=submit]').click()
                expect(page.locator('.jm-place')).to_have_count(100)
                page.locator('[data-jm=next]').click();expect(page.locator('.jm-place')).to_have_count(1)
                page.locator('.jm-place').click();page.locator('[data-jm=photos]').click()
                expect(page.locator('[data-hm=return-map]')).to_be_visible()
                expect(page.locator('.hm-card')).to_have_count(24)
                expect(page.locator('[data-hm-filters] [name=journeyId]')).to_have_value(journey['id'])
                expect(page.locator('[data-hm-filters] [name=journeyId]')).to_be_disabled()
                expect(page.locator('[data-hm-filters] [name=scope]')).to_have_value('visible')
                assert '/api/media/items?scope=visible' in '\n'.join(reads)
                assert 'journeyId='+journey['id'] in '\n'.join(reads)
                assert 'journeyId='+journey['tripId'] not in '\n'.join(reads)
                expect(page.locator('[data-hm=create],[data-hm=connect]')).to_have_count(0)
                page.locator('[data-hm=next]').click();expect(page.locator('.hm-card')).to_have_count(2)
                expect(page.locator('#ps-media-workspace')).not_to_contain_text('OTHER-JOURNEY')
                expect(page.locator('#ps-media-workspace')).not_to_contain_text('PARTNER-PRIVATE')
                page.screenshot(path=str(out/'phone.png'),full_page=True);report['screenshots'].append(str(out/'phone.png'))
                passed('phone_map_workflow_id_visible_ready_only_and_24_item_pagination')
                before_reads=len(reads)
                page.locator('[data-hm=return-map]').click()
                expect(page.locator('.jm-place.is-selected')).to_have_attribute('data-id',chosen['id'])
                expect(page.locator('[data-jm-filters] [name=year]')).to_have_value('2026')
                expect(page.locator('[data-jm-filters] [name=status]')).to_have_value('planned')
                expect(page.locator('[data-jm-filters] [name=owner]')).to_have_value('member1')
                expect(page.locator('[data-jm-filters] [name=scope]')).to_have_value('mine')
                assert any('/api/journey-places?' in url and 'offset=100' in url for url in reads[before_reads:])
                assert any('/api/me' in url for url in reads[before_reads:])
                with engine.transaction() as con:
                    assert before==[tuple(row) for row in con.execute('SELECT id,revision,visibility,journey_id FROM media_items ORDER BY id')]
                    assert con.execute('SELECT count(*) FROM media_tv_grants').fetchone()[0]==0
                assert not writes
                passed('return_refetches_server_preserving_all_filters_offset_selection_without_writes')
                page.locator('[data-jm=photos]').click();expect(page.locator('.hm-card')).to_have_count(24)
                page.go_back();expect(page.locator('.jm-place.is-selected')).to_have_attribute('data-id',chosen['id'])
                passed('browser_back_also_remounts_and_restores_only_query_state')
                # Explicit ordinary album navigation must leave the focused read-only view.
                for width in (390,1440):
                    page.set_viewport_size({'width':width,'height':900})
                    page.locator('[data-jm=photos]').click();expect(page.locator('[data-hm=return-map]')).to_be_visible()
                    if width==390:
                        page.locator('[data-ps-more]').click()
                        page.locator('#ps-more-menu [data-ps-route=photos]').click()
                    else:
                        page.locator('.ps-sidebar [data-ps-route=photos]').click()
                    expect(page.locator('[data-hm=create]')).to_be_enabled()
                    expect(page.locator('[data-hm=return-map]')).to_have_count(0)
                    expect(page.locator('[data-hm-filters] [name=journeyId]')).to_have_value('')
                    expect(page.locator('[data-hm-filters] [name=journeyId]')).to_be_enabled()
                    page.locator('.hm-card').first.click();expect(page.locator('[data-hm-editor]')).to_be_visible()
                    page.go_back();expect(page.locator('.jm-place.is-selected')).to_have_attribute('data-id',chosen['id'])
                    expect(page.locator('[data-jm-filters] [name=year]')).to_have_value('2026')
                passed('phone_and_sidebar_ordinary_album_exits_readonly_import_edit_available_back_refetches_map')
                page.set_viewport_size({'width':390,'height':844})
                # Hold a real place response while the user begins a different action.
                navigation=[]
                def delay_place(route):
                    navigation.append((route,route.fetch()))
                pattern='**/api/journey-places/'+chosen['id']
                page.route(pattern,delay_place)
                page.locator('[data-jm=photos]').click()
                for _ in range(100):
                    if navigation: break
                    page.wait_for_timeout(50)
                assert navigation
                page.locator('[data-jm=new]').click()
                page.locator('[data-jm-editor] [name=name]').fill('NEW-DRAFT-MUST-SURVIVE')
                for route,response in navigation:route.fulfill(response=response)
                page.unroute(pattern,delay_place);page.wait_for_load_state('networkidle')
                expect(page.locator('[data-jm-editor] [name=name]')).to_have_value('NEW-DRAFT-MUST-SURVIVE')
                expect(page.locator('#ps-media-workspace')).to_have_count(0)
                assert urlsplit(page.url).fragment=='map'
                page.once('dialog',lambda dialog:dialog.accept())
                page.locator('[data-jm=cancel]').click()
                expect(page.locator('[data-jm-editor]')).to_have_count(0)
                passed('late_place_navigation_abandoned_after_new_draft_without_losing_edit')
                page.locator('[data-jm=photos]').click();expect(page.locator('.hm-card')).to_have_count(24)
                ctx.set_offline(True);expect(page.locator('#ps-media-workspace img')).to_have_count(0)
                page.locator('[data-hm=return-map]').click();expect(page.locator('.jm-place')).to_have_count(0)
                expect(page.locator('.jm-detail')).not_to_contain_text(chosen['name'])
                ctx.set_offline(False);expect(page.locator('.jm-place.is-selected')).to_have_attribute('data-id',chosen['id'])
                passed('offline_clears_photos_return_never_repaints_cached_places_online_refetches')
                # Delay a real server response; returning while it is pending must fence it.
                pending=[]
                def delay(route):
                    pending.append((route,route.fetch()))
                page.route('**/api/media/items?*',delay)
                page.locator('[data-jm=photos]').click();expect(page.locator('[data-hm=return-map]')).to_be_visible()
                page.wait_for_timeout(300);assert pending
                page.locator('[data-hm=return-map]').click();expect(page.locator('.jm-place.is-selected')).to_have_count(1)
                for route,response in pending:route.fulfill(response=response)
                page.unroute('**/api/media/items?*',delay);page.wait_for_timeout(100)
                expect(page.locator('#ps-media-workspace')).to_have_count(0)
                passed('late_real_gallery_response_cannot_resurrect_after_return')
                # Revocation on the server while away: a fresh map, not saved DTOs.
                partner_ctx=context(2,1440); partner_page=partner_ctx.new_page();partner_page.goto(base+'/#map')
                expect(partner_page.locator('.jm-place')).to_have_count(1)
                partner_page.locator('.jm-place').click();partner_page.locator('[data-jm=photos]').click()
                expect(partner_page.locator('.hm-card')).to_have_count(2)
                changed=owner.patch('/api/journey-places/'+shared_place['id'],headers=headers,json={'revision':shared_place['revision'],'visibility':'private'})
                assert changed.status_code==200
                partner_page.locator('[data-hm=return-map]').click();expect(partner_page.locator('.jm-place')).to_have_count(0)
                expect(partner_page.locator('#ps-map-workspace')).not_to_contain_text('SHARED-MAP-PLACE')
                passed('place_acl_revoked_while_away_removes_selection_and_private_text')
                restored=owner.patch('/api/journey-places/'+shared_place['id'],headers=headers,json={'revision':changed.json['place']['revision'],'visibility':'shared'})
                assert restored.status_code==200
                partner_page.locator('[data-jm=refresh]').click();expect(partner_page.locator('.jm-place')).to_have_count(1)
                partner_page.locator('.jm-place').click()
                assert owner.patch('/api/journey-places/'+shared_place['id'],headers=headers,json={'revision':restored.json['place']['revision'],'visibility':'private'}).status_code==200
                partner_page.locator('[data-jm=photos]').click();expect(partner_page.locator('.jm-place')).to_have_count(0)
                expect(partner_page.locator('#ps-media-workspace')).to_have_count(0)
                expect(partner_page.locator('#ps-map-workspace')).not_to_contain_text('SHARED-MAP-PLACE')
                partner_page.screenshot(path=str(out/'desktop-denied.png'),full_page=True);report['screenshots'].append(str(out/'desktop-denied.png'))
                passed('stale_place_button_rechecks_real_acl_before_navigation')
                page.locator('[data-jm=photos]').click();expect(page.locator('.hm-card')).to_have_count(24)
                # Restrict to shared photos so a real revocation has an unambiguous empty result.
                page.locator('[data-hm-filters] [name=scope]').select_option('shared')
                page.locator('[data-hm-filters] [type=submit]').click();expect(page.locator('.hm-card')).to_have_count(1)
                page.locator('.hm-card').click();expect(page.locator('.hm-detail')).to_be_visible()
                current=partner.get('/api/media/items/'+shared[0]).json['item']
                assert partner.patch('/api/media/items/'+shared[0],headers=ph,json={'revision':current['revision'],'visibility':'private'}).status_code==200
                page.locator('[data-hm=refresh]').click();expect(page.locator('.hm-card')).to_have_count(0)
                expect(page.locator('.hm-detail')).to_have_count(0)
                expect(page.locator('.hm-empty')).to_contain_text('这次旅行还没有可见照片')
                passed('photo_acl_revoked_refresh_clears_detail_preview_and_shows_honest_empty')
                # Real cookie switch while holding a response from the previous owner.
                page.locator('[data-hm=return-map]').click();expect(page.locator('.jm-place.is-selected')).to_have_count(1)
                pending.clear();page.route('**/api/media/items?*',delay)
                page.locator('[data-jm=photos]').click();page.wait_for_timeout(300);assert pending
                token=ctx.request.get(base+'/api/me').json()['csrf']
                assert ctx.request.post(base+'/api/logout',headers={'X-CSRF-Token':token,'Origin':base},data={}).status==200
                assert ctx.request.post(base+'/api/login',data={'username':'member2','password':PASSWORD}).status==200
                for route,response in pending:route.fulfill(response=response)
                page.unroute('**/api/media/items?*',delay)
                expect(page.locator('#ps-media-workspace')).to_contain_text('登录成员或家庭已变化')
                expect(page.locator('[data-hm=return-map],.hm-card')).to_have_count(0)
                page.evaluate('async()=>{await boot()}')
                expect(page.locator('[data-hm=create]')).to_be_visible()
                expect(page.locator('[data-hm=return-map]')).to_have_count(0)
                passed('real_cookie_change_fences_delayed_response_and_discards_return_context')
                # A real invited second household cannot read either source ID.
                admin=context();csrf=admin.request.get(base+'/api/me').json()['csrf']
                invitation=admin.request.post(base+'/api/spaces/invitations',headers={'X-CSRF-Token':csrf,'Origin':base},data={})
                assert invitation.status==201
                created=admin.request.post(base+'/api/spaces/redeem',data={'invitation':invitation.json()['invitation'],'name':'合成另一家庭','slug':'map-photo-other','MEMBER1_PASSWORD':PASSWORD,'MEMBER2_PASSWORD':PASSWORD})
                assert created.status==201,created.text()
                page.goto(base+created.json()['entry']);page.locator('#login-form [name=password]').fill(PASSWORD);page.locator('#login-form [type=submit]').click()
                expect(page.locator('#login-form')).to_have_count(0)
                expect(page.locator('#ps-page')).to_be_visible()
                assert ctx.request.get(base+'/api/me').json()['user']['householdId']!='default'
                page.evaluate("ProductShell.navigate('map')");expect(page.locator('[data-jm=refresh]')).to_be_enabled()
                expect(page.locator('.jm-place')).to_have_count(0)
                assert ctx.request.get(base+'/api/journey-places/'+chosen['id']).status==404
                assert ctx.request.get(base+'/api/media/items/'+shared[0]).status==404
                expect(page.locator('[data-jm=photos],[data-hm=return-map]')).to_have_count(0)
                passed('real_second_household_navigation_and_api_deny_prior_ids')
                tv=browser.new_context();tv.add_cookies([{'name':'household_tv','value':tv_cookie,'url':base}])
                assert tv.request.get(base+'/api/me').json()['user']['role']=='tv'
                tv_page=tv.new_page();tv_reads=[];tv_page.on('request',lambda req:tv_reads.append(req.url))
                tv_page.goto(base+'/#map');tv_page.wait_for_timeout(250)
                assert not any('/api/journey-places' in url or '/api/media/items' in url for url in tv_reads)
                expect(tv_page.locator('[data-jm=photos],[data-hm=return-map]')).to_have_count(0)
                passed('television_never_mounts_member_map_photo_bridge')
                assert not report['pageErrors'] and not report['externalRequests']
                report['passed']=True
    except Exception:
        report['failure']=traceback.format_exc();print(report['failure'],flush=True)
    finally:
        report['sourceHashesAfter']=hashes();report['sourceUnchanged']=report['sourceHashesBefore']==report['sourceHashesAfter']
        report['passed']=report['passed'] and report['sourceUnchanged']
        (out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'report':str(out/'result.json')}),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
