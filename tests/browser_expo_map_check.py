"""Real frozen Expo export, Flask/SQLite and Edge map/photo workflow acceptance.

Synthetic local media job results seed an encrypted library through the real
import/confirm API. No Google IO and no replacement browser success responses.
One committed place POST response is deliberately dropped to test idempotency.
"""
import argparse
from contextlib import ExitStack, closing
from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import traceback
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server, WSGIRequestHandler


class Quiet(WSGIRequestHandler):
    def log(self, *_args, **_kwargs):
        pass


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--expected-build-evidence', required=True)
    args = parser.parse_args()
    root, bundle = args.source_root.resolve(), args.bundle.resolve()
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    assert head == args.expected_head, 'Unexpected source commit'
    evidence_path = bundle.parent / 'build-evidence.json'
    assert sha(evidence_path) == args.expected_build_evidence
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    assert evidence['sourceHead'] == head
    assert evidence['sourceTree'] == subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=root, text=True).strip()
    assert not subprocess.check_output(['git', 'status', '--porcelain=v1', '--untracked-files=no'], cwd=root, text=True).strip()
    names = subprocess.check_output(['git', 'ls-files'], cwd=root, text=True).splitlines()
    hashes = lambda: {name: sha(root / name) for name in names}
    bundle_hashes = lambda: {p.relative_to(bundle).as_posix(): sha(p) for p in bundle.rglob('*') if p.is_file()}
    assert bundle_hashes() == evidence['files']
    assert all(sha(root / name) == digest for name, digest in evidence['inputFiles'].items())
    out = Path(__file__).resolve().parents[1] / 'test-results' / ('expo-map-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], httpErrors=[], screenshots=[],
        eventInjections=['document.hidden/visibilityState plus visibilitychange for background/foreground; real business API unchanged'],
        head=head, tree=evidence['sourceTree'], buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(out / 'executed-harness.py'),
        sourceHashesBefore=hashes(), bundleHashesBefore=bundle_hashes(), productionWrites=0, realGoogle=False, physicalTelevision=False,
        scope='Frozen Expo bundle, real factory/CSRF/member cookies/encrypted media/SQLite. Synthetic provider job results seed photos; one committed HTTP response dropped.')
    page = None

    def passed(message):
        report['checks'].append(message)
        print('PASS ' + message, flush=True)

    original_connect = socket.socket.connect

    def local_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
            report['externalRequests'].append('non-loopback socket')
            raise AssertionError('External network forbidden')
        return original_connect(sock, address)

    try:
        with ExitStack() as lifecycle:
            lifecycle.enter_context(patch.object(socket.socket, 'connect', local_connect))
            folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='expo-map-')))
            sys.path[:0] = [str(root), str(root / 'tests')]
            source = importlib.import_module('app')
            media_fixture = importlib.import_module('test_household_media')
            journeys_fixture = importlib.import_module('test_journey_documents')
            shutil.copytree(root / 'static', folder / 'static', ignore=shutil.ignore_patterns('experience'))
            shutil.copytree(bundle, folder / 'static' / 'experience')
            lifecycle.enter_context(patch.object(source, 'ROOT', folder))
            monkey = lifecycle.enter_context(pytest.MonkeyPatch.context())
            env = media_fixture.configured(folder / 'data', monkey)
            application, engine, _, _ = env
            application.config['HOUSEHOLD_INFO'].update(name='合成地图家庭', slug='home')
            owner_seed, seed_headers = journeys_fixture.login(application)
            journey = journeys_fixture.create_journey(owner_seed, seed_headers, '合成山海旅行')
            other_journey = journeys_fixture.create_journey(owner_seed, seed_headers, '其他旅行')
            assert journey['id'] != journey['tripId']

            def seed_photos(number, count, prefix, journey_id, visibility):
                client, headers, detail, _ = media_fixture.stage(env, number,
                    items=[media_fixture.selected(prefix + str(n)) for n in range(count)])
                media_fixture.confirm(client, headers, detail)
                ids = []
                for entry in detail['items']:
                    uid = entry['id']
                    item = client.get('/api/media/items/' + uid).json['item']
                    response = client.patch('/api/media/items/' + uid, headers=headers,
                        json={'revision': item['revision'], 'caption': prefix, 'journeyId': journey_id, 'visibility': visibility})
                    assert response.status_code == 200, response.json
                    ids.append(uid)
                while (job := engine.claim_next()) is not None:
                    assert job['action'] == 'cleanup' and engine.complete(job, None)
                return ids

            seed_photos(1, 20, 'OWNER-TARGET-A', journey['id'], 'private')
            seed_photos(1, 5, 'OWNER-TARGET-B', journey['id'], 'private')
            shared_photos = seed_photos(2, 1, 'PARTNER-SHARED', journey['id'], 'shared')
            seed_photos(2, 1, 'PARTNER-PRIVATE', journey['id'], 'private')
            seed_photos(1, 1, 'OTHER-JOURNEY', other_journey['id'], 'private')
            media_fixture.stage(env, 1, items=[media_fixture.selected('UNCONFIRMED')])
            _, _, tv_cookie = media_fixture.device(env)
            server = make_server('127.0.0.1', 0, application, threaded=True, request_handler=Quiet, ssl_context='adhoc')
            base = 'https://127.0.0.1:' + str(server.server_port)
            application.config.update(PUBLIC_ORIGIN=base, SESSION_COOKIE_SECURE=True)
            config = dict(application.config)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            def stop():
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
                assert not thread.is_alive()

            lifecycle.callback(stop)
            with sync_playwright() as pw, ExitStack() as browsers:
                browser = pw.chromium.launch(channel='msedge', headless=True)
                browsers.callback(browser.close)

                def failure_capture():
                    if not report['passed'] and page is not None and not page.is_closed():
                        try:
                            page.screenshot(path=str(out / 'failure.png'), full_page=True)
                            (out / 'failure-aria.txt').write_text(page.locator('body').aria_snapshot(), encoding='utf-8')
                        except Exception:
                            pass

                browsers.callback(failure_capture)

                def context(number=None):
                    ctx = browser.new_context(viewport={'width': 390, 'height': 844}, ignore_https_errors=True)

                    def route(handler):
                        if urlsplit(handler.request.url).hostname == '127.0.0.1':
                            handler.continue_()
                        else:
                            report['externalRequests'].append(urlsplit(handler.request.url).hostname)
                            handler.abort()

                    ctx.route('**/*', route)
                    ctx.on('page', lambda p: p.on('pageerror', lambda error: report['pageErrors'].append(str(error))))
                    ctx.on('response', lambda response: report['httpErrors'].append({'method': response.request.method,
                        'path': urlsplit(response.url).path, 'status': response.status}) if response.status >= 400 else None)
                    if number:
                        login(ctx, number)
                    return ctx

                def login(ctx, number=1):
                    response = ctx.request.post(base + '/api/login', data={'username': f'member{number}', 'password': journeys_fixture.PASSWORD})
                    assert response.status == 200, response.text()

                def headers(ctx):
                    return {'X-CSRF-Token': get(ctx, '/api/me')['csrf'], 'Origin': base}

                def get(ctx, path):
                    response = ctx.request.get(base + path)
                    assert response.status == 200, response.text()
                    return response.json()

                def write(ctx, method, path, body, status=200):
                    response = ctx.request.fetch(base + path, method=method, headers=headers(ctx), data=body)
                    assert response.status == status, response.text()
                    return response.json()

                def place_create(ctx, **data):
                    return write(ctx, 'POST', '/api/journey-places', {'requestId': secrets.token_hex(16), **data}, 201)['place']

                def button(p, name):
                    return p.get_by_role('button', name=re.compile(r'(?:^|\s)' + re.escape(name) + r'$'))

                def fill(p, name, value):
                    p.get_by_role('textbox', name=name, exact=True).fill(str(value))

                def visibility(p, hidden):
                    p.evaluate('''hidden => {
                      if (hidden) {
                        Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});
                        Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'hidden'});
                      } else { delete document.hidden; delete document.visibilityState; }
                      document.dispatchEvent(new Event('visibilitychange'));
                    }''', hidden)

                def assert_layout(p, width, name):
                    p.evaluate('() => document.fonts.ready')
                    metrics = p.evaluate('''() => ({width:innerWidth,scroll:document.documentElement.scrollWidth,
                      clipped:[...document.querySelectorAll('input,button,[role="button"]')].filter(e=>{const r=e.getBoundingClientRect();
                      return r.width>0&&r.height>0&&getComputedStyle(e).visibility!=='hidden'&&r.right>innerWidth+2&&r.left<innerWidth;})
                      .map(e=>({label:e.getAttribute('aria-label')||e.innerText,left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right}))})''')
                    assert metrics['scroll'] <= width + 2 and not metrics['clipped'], metrics
                    filename = f'{name}-{width}.png'
                    p.screenshot(path=str(out / filename), full_page=True)
                    report['screenshots'].append(filename)

                owner, partner = context(1), context(2)
                page, partner_page = owner.new_page(), partner.new_page()
                reads, writes = [], []
                page.on('request', lambda request: (reads if request.method == 'GET' else writes).append(request.url))

                def open_map(p):
                    p.goto(base + '/app/map')
                    expect(button(p, '添加地点')).to_be_enabled(timeout=15000)

                def open_place(p, name):
                    button(p, '打开地点：' + name).click()
                    expect(button(p, '编辑地点')).to_be_visible()

                def choice(p, prefix, label):
                    p.get_by_role('button', name=re.compile('^' + re.escape(prefix) + '：')).click()
                    p.get_by_text(label, exact=True).filter(visible=True).last.click()

                def photos(p):
                    return p.get_by_role('button', name=re.compile('^查看照片：'))

                title = '合成海边公园与跨城市周末旅行集合地点'
                open_map(page)
                button(page, '添加地点').click()
                fill(page, '地点名称', title)
                fill(page, '国家或地区', '合成地区')
                fill(page, '城市', '合成海滨城市')
                fill(page, '纬度', '31.234567')
                fill(page, '经度', '121.456789')
                button(page, '保存地点').click()
                expect(button(page, '编辑地点')).to_be_enabled()
                point = get(owner, '/api/journey-places')['items'][0]
                uid = point['id']
                assert point['visibility'] == 'private' and point['status'] == 'wish'
                assert point['coordinates'] == {'latitude': 31.234567, 'longitude': 121.456789}
                assert get(partner, '/api/journey-places')['total'] == 0
                assert partner.request.get(base + '/api/journey-places/' + uid).status == 404
                passed('real mobile Expo form persists a private place with exact owner coordinates; partner cannot list or read it')

                button(page, '编辑地点').click()
                choice(page, '状态', '已到访')
                before_confirm = len(writes)
                button(page, '保存地点').click()
                expect(page.get_by_text('请先明确确认实际到访；日期或照片不会自动证明到访。', exact=True)).to_be_visible()
                assert len(writes) == before_confirm
                confirmation = page.get_by_role('checkbox', name='我确认实际到访', exact=True)
                confirmation.focus()
                confirmation.press('Space')
                expect(confirmation).to_be_checked()
                button(page, '保存地点').click()
                expect(button(page, '编辑地点')).to_be_enabled()
                point = get(owner, '/api/journey-places/' + uid)['place']
                assert point['status'] == 'visited' and point['visitedConfirmedAt'] and point['visitedConfirmedBy'] == 'member1'
                passed('visited status requires a keyboard-accessible explicit checkbox and persists human confirmation')

                # A changed confirmed location requires reconfirmation. Change a
                # neutral name-independent field here only after returning to wish.
                point = write(owner, 'PATCH', '/api/journey-places/' + uid,
                    {'revision': point['revision'], 'status': 'wish'})['place']
                open_map(page)
                open_place(page, title)
                button(page, '编辑地点').click()
                draft_city = '保留中的合成城市草稿'
                fill(page, '城市', draft_city)
                held = []
                detail_pattern = '**/api/journey-places/' + uid

                def hold_background(handler):
                    if handler.request.method == 'GET' and not held:
                        held.append((handler, handler.fetch()))
                    else:
                        handler.continue_()

                page.route(detail_pattern, hold_background)
                # Wait for the real 15-second periodic permission check. The
                # response is genuine and only its delivery is delayed.
                for _ in range(360):
                    if held:
                        break
                    page.wait_for_timeout(50)
                assert held, 'Expected background permission recheck'
                draft_city += '续写'
                fill(page, '城市', draft_city)
                expect(page.get_by_role('textbox', name='城市', exact=True)).to_have_value(draft_city)
                for handler, response in held:
                    handler.fulfill(response=response)
                page.unroute(detail_pattern, hold_background)
                visibility(page, True)
                expect(page.get_by_role('textbox', name='城市', exact=True)).not_to_be_visible()
                visibility(page, False)
                expect(page.get_by_role('textbox', name='城市', exact=True)).to_have_value(draft_city)
                point = get(owner, '/api/journey-places/' + uid)['place']
                write(owner, 'PATCH', '/api/journey-places/' + uid,
                    {'revision': point['revision'], 'country': '另一设备更改的地区'})
                with page.expect_response(lambda response: urlsplit(response.url).path == '/api/journey-places/' + uid and response.request.method == 'PATCH') as conflict:
                    button(page, '保存地点').click()
                assert conflict.value.status == 409
                expect(button(page, '核对最新版本')).to_be_enabled()
                expect(page.get_by_role('textbox', name='城市', exact=True)).to_have_value(draft_city)
                button(page, '核对最新版本').click()
                expect(button(page, '保存地点')).to_be_enabled()
                expect(page.get_by_role('textbox', name='城市', exact=True)).to_have_value(draft_city)
                button(page, '保存地点').click()
                expect(button(page, '编辑地点')).to_be_enabled()
                assert get(owner, '/api/journey-places/' + uid)['place']['city'] == draft_city
                passed('typing during held genuine background check is retained; conceal/reveal preserves draft; real revision conflict requires fresh review and explicit resave')

                dropped, create_payloads = {}, []

                def drop_create(handler):
                    if handler.request.method != 'POST' or dropped:
                        handler.continue_()
                        return
                    response = handler.fetch()
                    assert response.status == 201, response.text()
                    dropped.update(body=handler.request.post_data_json, result=response.json(), status=response.status)
                    handler.abort('failed')

                def create_request(request):
                    if request.method == 'POST' and urlsplit(request.url).path == '/api/journey-places':
                        create_payloads.append(request.post_data_json)

                page.on('request', create_request)
                page.route('**/api/journey-places', drop_create)
                button(page, '添加地点').click()
                fill(page, '地点名称', '合成未知结果只创建一次')
                button(page, '保存地点').click()
                expect(button(page, '核对原创建')).to_be_enabled()
                visibility(page, True)
                expect(page.get_by_role('textbox', name='地点名称', exact=True)).not_to_be_visible()
                visibility(page, False)
                expect(button(page, '核对原创建')).to_be_enabled()
                assert len(create_payloads) == 1, 'Foreground must not automatically retry an unknown write'
                button(page, '核对原创建').click()
                expect(button(page, '编辑地点')).to_be_enabled()
                page.unroute('**/api/journey-places', drop_create)
                assert len(create_payloads) == 2 and create_payloads[0] == create_payloads[1] == dropped['body']
                duplicate_id = dropped['result']['place']['id']
                db_path = folder / 'data' / 'household.sqlite3'
                with closing(sqlite3.connect(db_path)) as con:
                    assert con.execute('SELECT count(*) FROM journey_places WHERE request_id=?', (dropped['body']['requestId'],)).fetchone()[0] == 1
                report['droppedResponse'] = {'status': dropped['status'], 'requestId': dropped['body']['requestId'], 'realServerCommit': True}
                passed('actual committed create response loss retains original payload and requestId across background; explicit retry produces one SQLite row')

                # Exercise native delete and then instantiate an actual second
                # production factory over the same database, with no fixture seed.
                button(page, '删除地点').click()
                button(page, '确认删除地点').click()
                expect(button(page, '添加地点')).to_be_enabled()
                assert owner.request.get(base + '/api/journey-places/' + duplicate_id).status == 404
                before_restart = get(owner, '/api/journey-places/' + uid)['place']
                server.app = source.create_app(config)
                open_map(page)
                assert get(owner, '/api/journey-places/' + uid)['place'] == before_restart
                assert get(owner, '/api/media/items?scope=visible&journeyId=' + journey['id'])['total'] == 26
                with closing(sqlite3.connect(db_path)) as con:
                    assert con.execute('PRAGMA foreign_key_check').fetchall() == []
                    assert con.execute('SELECT count(*) FROM media_tv_grants').fetchone()[0] == 0
                passed('native delete persists its tombstone; actual factory restart retains saved places and encrypted photos without TV grants')

                # Shared location still must not grant access to owner photos.
                point = write(owner, 'PATCH', '/api/journey-places/' + uid,
                    {'revision': before_restart['revision'], 'visibility': 'shared', 'coordinateDisclosure': 'hidden', 'journeyId': journey['id']})['place']
                open_map(partner_page)
                button(partner_page, '打开地点：' + title).click()
                expect(button(partner_page, '编辑地点')).to_have_count(0)
                hidden = get(partner, '/api/journey-places/' + uid)['place']
                assert hidden['coordinates'] is None and hidden['coordinatePrecision'] == 'hidden'
                expect(partner_page.locator('body')).not_to_contain_text('31.234567')
                expect(partner_page.locator('body')).not_to_contain_text('121.456789')
                point = write(owner, 'PATCH', '/api/journey-places/' + uid,
                    {'revision': point['revision'], 'coordinateDisclosure': 'coarse'})['place']
                open_map(partner_page)
                button(partner_page, '打开地点：' + title).click()
                coarse = get(partner, '/api/journey-places/' + uid)['place']
                assert coarse['coordinates'] == {'latitude': 31.2, 'longitude': 121.5} and coarse['coordinatePrecision'] == 'approximate'
                expect(partner_page.locator('body')).not_to_contain_text('31.234567')
                expect(partner_page.locator('body')).not_to_contain_text('121.456789')
                passed('shared native detail is read-only and uses hidden/coarse server projection without exposing owner precision')

                open_map(page)
                open_place(page, title)
                owner.set_offline(True)
                expect(page.get_by_role('button', name=re.compile('^打开地点：'))).to_have_count(0)
                expect(page.get_by_text(title, exact=True)).to_have_count(0)
                expect(page.get_by_text(re.compile('31\\.234567'))).to_have_count(0)
                owner.set_offline(False)
                expect(button(page, '编辑地点')).to_be_enabled()
                passed('offline event immediately conceals visible map names and exact coordinates; online rechecks current selection before reveal')

                for number in range(25):
                    place_create(owner, name='合成地图回忆 ' + str(number), journeyId=journey['id'], status='planned',
                        startDate='2026-12-01', endDate='2026-12-04', country='合成地区', city='合成海滨城市',
                        coordinates={'latitude': 20 + number / 10, 'longitude': 110 + number / 10})
                open_map(page)
                button(page, '筛选地点').click()
                choice(page, '范围', '仅我的')
                choice(page, '状态', '已计划')
                fill(page, '年份', '2026')
                choice(page, '成员', next(person['name'] for person in get(owner, '/api/state')['people'] if person['id'] == 'member1'))
                choice(page, '旅行', '合成山海旅行')
                button(page, '应用筛选').click()
                expect(page.get_by_role('button', name=re.compile('^打开地点：合成地图回忆 '))).to_have_count(24)
                button(page, '下一页').click()
                rows = page.get_by_role('button', name=re.compile('^打开地点：合成地图回忆 '))
                expect(rows).to_have_count(1)
                rows.first.focus()
                rows.first.press('Enter')
                expected_query = 'scope=mine&status=planned&year=2026&owner=member1&journeyId=' + journey['id'] + '&limit=24&offset=24'
                chosen = get(owner, '/api/journey-places?' + expected_query)['items'][0]
                expect(button(page, '查看旅行照片')).to_be_enabled()
                photo_read_start, photo_write_start = len(reads), len(writes)
                button(page, '查看旅行照片').click()
                expect(button(page, '返回地图')).to_be_enabled()
                expect(photos(page)).to_have_count(24)
                expect(page.locator('body')).not_to_contain_text('OTHER-JOURNEY')
                expect(page.locator('body')).not_to_contain_text('PARTNER-PRIVATE')
                button(page, '下一页').click()
                expect(photos(page)).to_have_count(2)
                photos(page).first.focus()
                photos(page).first.press('Enter')
                expect(page.get_by_text('照片详情', exact=True)).to_be_visible()
                button(page, '关闭').click()
                photo_reads = reads[photo_read_start:]
                queries = [parse_qs(urlsplit(url).query) for url in photo_reads if urlsplit(url).path == '/api/media/items']
                assert queries and all(value.get('journeyId') == [journey['id']] for value in queries)
                assert any(value.get('offset') == ['24'] for value in queries)
                assert not any(any(prefix in urlsplit(url).path for prefix in ('/accounts', '/devices', '/media/imports', '/tv-grants')) for url in photo_reads)
                assert not writes[photo_write_start:]
                passed('map filters and second page open only current workflow photos; readonly 24+2 pagination and detail make no import/device/grant requests or writes')

                return_start = len(reads)
                button(page, '返回地图').click()
                expect(button(page, '查看旅行照片')).to_be_enabled()
                expect(page.get_by_role('button', name=re.compile('^打开地点：合成地图回忆 '))).to_have_count(1)
                returned = [parse_qs(urlsplit(url).query) for url in reads[return_start:] if urlsplit(url).path == '/api/journey-places']
                assert any(value.get('scope') == ['mine'] and value.get('status') == ['planned'] and value.get('year') == ['2026']
                    and value.get('owner') == ['member1'] and value.get('journeyId') == [journey['id']] and value.get('offset') == ['24'] for value in returned)
                assert any(urlsplit(url).path == '/api/journey-places/' + chosen['id'] for url in reads[return_start:])
                button(page, '查看旅行').click()
                expect(button(page, '返回足迹地图')).to_be_enabled()
                expect(page.get_by_text('旅行详情', exact=True)).to_be_visible()
                expect(page.get_by_text('合成山海旅行', exact=True).filter(visible=True)).to_be_visible()
                button(page, '返回足迹地图').click()
                expect(button(page, '查看旅行照片')).to_be_enabled()
                assert urlsplit(page.url).path == '/app/map'
                pending_travel = []

                def hold_travel(handler):
                    pending_travel.append((handler, handler.fetch()))

                page.route('**/api/journeys', hold_travel)
                button(page, '查看旅行').click()
                for _ in range(100):
                    if pending_travel:
                        break
                    page.wait_for_timeout(30)
                assert pending_travel
                expect(button(page, '返回足迹地图')).to_be_enabled()
                page.unroute('**/api/journeys', hold_travel)
                button(page, '返回足迹地图').click()
                expect(button(page, '查看旅行照片')).to_be_enabled()
                for handler, response in pending_travel:
                    handler.fulfill(response=response)
                expect(page.get_by_text('旅行详情', exact=True)).to_have_count(0)
                expect(button(page, '查看旅行照片')).to_be_enabled()
                passed('photo/travel returns preserve all filters and selected ID with fresh reads; returning during held genuine travel read remains available and fences late response')

                # Background/offline reveal gates must clear data and recheck,
                # independently of a successful earlier gallery read.
                button(page, '查看旅行照片').click()
                expect(photos(page)).to_have_count(24)
                visibility(page, True)
                expect(photos(page)).to_have_count(0)
                expect(page.get_by_text('合成山海旅行', exact=True)).not_to_be_visible()
                visibility(page, False)
                expect(photos(page)).to_have_count(24)
                owner.set_offline(True)
                expect(photos(page)).to_have_count(0)
                expect(page.locator('img')).to_have_count(0)
                button(page, '返回地图').click()
                expect(page.get_by_role('button', name=re.compile('^打开地点：'))).to_have_count(0)
                owner.set_offline(False)
                expect(button(page, '查看旅行照片')).to_be_enabled()
                passed('readonly gallery background/offline hides title and previews; return while offline cannot repaint cached places and online reads restore selection')

                # A photo owner withdraws shared access while another reader has
                # opened its detail; the next refresh must erase that projection.
                button(page, '查看旅行照片').click()
                expect(photos(page)).to_have_count(24)
                button(page, '家人共享').click()
                expect(photos(page)).to_have_count(1)
                photos(page).first.click()
                expect(page.get_by_text('照片详情', exact=True)).to_be_visible()
                button(page, '关闭').click()
                shared_photo = get(partner, '/api/media/items/' + shared_photos[0])['item']
                write(partner, 'PATCH', '/api/media/items/' + shared_photos[0], {'revision': shared_photo['revision'], 'visibility': 'private'})
                button(page, '刷新相册').click()
                expect(photos(page)).to_have_count(0)
                assert owner.request.get(base + '/api/media/items/' + shared_photos[0]).status == 404
                expect(page.locator('body')).not_to_contain_text('PARTNER-SHARED')
                button(page, '返回地图').click()
                expect(button(page, '查看旅行照片')).to_be_enabled()
                # Place access can be withdrawn independently of photo ownership.
                button(partner_page, '查看旅行照片').click()
                expect(button(partner_page, '返回地图')).to_be_enabled()
                point = get(owner, '/api/journey-places/' + uid)['place']
                write(owner, 'PATCH', '/api/journey-places/' + uid, {'revision': point['revision'], 'visibility': 'private'})
                button(partner_page, '返回地图').click()
                expect(button(partner_page, '添加地点')).to_be_enabled()
                expect(button(partner_page, '打开地点：' + title)).to_have_count(0)
                expect(partner_page.locator('body')).not_to_contain_text(title)
                passed('photo and place revocations independently remove cached detail and prevent private data from reappearing on refresh or return')

                # Width checks use the actual land asset and business views, not a
                # static mock. All screenshots are retained for visual review.
                screenshot_place = next(item for item in get(owner, '/api/journey-places?limit=24&offset=0')['items']
                    if item['name'].startswith('合成地图回忆 ') and item['journeyId'] == journey['id'])
                for width in (320, 390, 1040, 1440):
                    page.set_viewport_size({'width': width, 'height': 900 if width >= 1000 else 844})
                    open_map(page)
                    expect(page.locator('svg path').first).to_be_visible()
                    assert_layout(page, width, 'map-overview')
                    button(page, '打开地点：' + screenshot_place['name']).click()
                    expect(button(page, '查看旅行照片')).to_be_enabled()
                    assert_layout(page, width, 'map-detail')
                    button(page, '编辑地点').click()
                    expect(page.get_by_role('textbox', name='地点名称', exact=True)).to_be_visible()
                    assert_layout(page, width, 'map-editor')
                    button(page, '取消编辑').click()
                    button(page, '放弃编辑').click()
                    button(page, '查看旅行照片').click()
                    expect(photos(page)).to_have_count(24)
                    assert_layout(page, width, 'trip-photos')
                    button(page, '返回地图').click()
                    expect(button(page, '查看旅行照片')).to_be_enabled()
                    passed(f'{width}px real map, place detail/editor and journey gallery fit viewport')

                invitation = write(owner, 'POST', '/api/spaces/invitations', {}, 201)['invitation']
                created = write(owner, 'POST', '/api/spaces/redeem', {'invitation': invitation, 'name': '合成地图第二家庭',
                    'slug': 'expo-map-two', 'MEMBER1_PASSWORD': journeys_fixture.PASSWORD, 'MEMBER2_PASSWORD': journeys_fixture.PASSWORD}, 201)
                child = context()
                child_page = child.new_page()
                child_page.goto(base + created['entry'])
                login(child)
                open_map(child_page)
                expect(child_page.get_by_role('button', name=re.compile('^打开地点：'))).to_have_count(0)
                assert child.request.get(base + '/api/journey-places/' + chosen['id']).status == 404
                assert child.request.get(base + '/api/media/items/' + shared_photos[0]).status == 404
                foreign = place_create(child, name='合成第二家庭独有地点', visibility='shared')
                assert owner.request.get(base + '/api/journey-places/' + foreign['id']).status == 404

                button(page, '查看旅行照片').click()
                expect(photos(page)).to_have_count(24)
                visibility(page, True)
                write(owner, 'POST', '/api/logout', {})
                login(owner, 2)
                visibility(page, False)
                expect(page.get_by_text('OWNER-TARGET-A', exact=True)).to_have_count(0)
                expect(page.get_by_text('OWNER-TARGET-B', exact=True)).to_have_count(0)
                expect(photos(page)).to_have_count(0)
                open_map(page)
                expect(page.get_by_role('button', name=re.compile('^打开地点：'))).to_have_count(0)
                tv = context()
                tv.add_cookies([{'name': 'household_tv', 'value': tv_cookie, 'url': base}])
                assert get(tv, '/api/me')['user']['role'] == 'tv'
                tv_page = tv.new_page()
                tv_reads = []
                tv_page.on('request', lambda request: tv_reads.append(urlsplit(request.url).path))
                tv_page.goto(base + '/app/map')
                tv_page.wait_for_load_state('networkidle')
                assert not any(path.startswith('/api/journey-places') or path.startswith('/api/media/items') for path in tv_reads)
                passed('real second-household IDs stay isolated; member switch discards gallery and return context; paired TV never reads member map/photos')
                assert not report['pageErrors'] and not report['externalRequests']
                report['passed'] = True
    except Exception:
        report['failure'] = traceback.format_exc()
        print(report['failure'], flush=True)
    finally:
        report['sourceHashesAfter'] = hashes()
        report['bundleHashesAfter'] = bundle_hashes()
        report['sourceUnchanged'] = report['sourceHashesBefore'] == report['sourceHashesAfter']
        report['bundleUnchanged'] = report['bundleHashesBefore'] == report['bundleHashesAfter']
        report['passed'] = report['passed'] and report['sourceUnchanged'] and report['bundleUnchanged']
        (out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'report': str(out / 'result.json')}, ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
