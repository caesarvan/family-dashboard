"""Frozen Expo journey routes against real loopback Flask/SQLite/Edge.

Four independent synthetic households cover order/persistence/photos, explicit
sharing, conflict and uncertain writes, and foreground/identity privacy. No
business success is mocked: response loss follows an actual server commit;
request loss is separately labelled and followed by a real operation 404.
Photo provider completions use the existing synthetic recap fixture, while the
browser reads actual saved metadata and sanitized image bytes over loopback
HTTPS with an ad hoc temporary certificate.

Run with -B -X utf8, --source-root, --expected-head, --bundle and
--expected-build-evidence. An earlier --build-source-head is accepted only when
it is an ancestor with an identical complete frontend tree and build inputs.
Do not run against a production data directory or use a partial frontend build.
"""
import argparse
from contextlib import ExitStack, closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import traceback
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import ThreadedWSGIServer
import browser_expo_finance_check as fixture
import browser_expo_trip_recap_check as recap
from browser_expo_finance_check import button, sha, visibility


HARNESS = 'tests/browser_expo_journey_routes_check.py'
URL = '/api/journey-routes'
CASES = ('private_order_restart_photos', 'shared_projection_withdrawal',
         'conflict_and_uncertain_writes', 'identity_hidden_offline')
PRIVATE = '合成私人往返路线'
NAMES = ('合成起点', '合成中间站', '合成终点')
FACT_TABLES = ('entities', 'journey_workflows', 'journey_links', 'journey_places', 'media_items', 'media_tv_grants')
ROUTE_TABLES = ('journey_routes', 'journey_route_stops', 'journey_route_operations')


def export_hashes(bundle):
    """Inventory every exported byte, including Windows paths beyond MAX_PATH."""
    assert bundle.is_dir() and not bundle.is_symlink() and not bundle.is_junction()
    extended = Path('\\\\?\\' + str(bundle)) if os.name == 'nt' else bundle
    files = {}
    def walk_error(error):
        raise error
    for current, directories, leaves in os.walk(extended, onerror=walk_error):
        for name in directories:
            directory = Path(current) / name
            assert not directory.is_symlink() and not directory.is_junction()
        for name in leaves:
            path = Path(current) / name
            assert path.is_file() and not path.is_symlink() and not path.is_junction()
            key = path.relative_to(extended).as_posix()
            assert key not in files
            files[key] = sha(path)
    return files


class Run(recap.Run):
    def __init__(self, root, bundle, folder, report, out, lifecycle):
        # Keep this patch until stop/server_close has joined every request. The
        # parent BaseRun registers stop after this context, before temp cleanup.
        assert ThreadedWSGIServer.block_on_close is True
        lifecycle.enter_context(patch.object(ThreadedWSGIServer, 'daemon_threads', False))
        super().__init__(root, bundle, folder, report, out, lifecycle)
        assert self.server.daemon_threads is False and self.server.block_on_close is True
        assert URL in {rule.rule for rule in self.application.url_map.iter_rules()}
        names = {HARNESS: Path(__file__), 'tests/browser_expo_finance_check.py': Path(fixture.__file__),
                 'tests/browser_expo_trip_recap_check.py': Path(recap.__file__)}
        for name in ('journey_routes', 'journey_places', 'journey_workflows', 'data_portability', 'home_assistant'):
            names[name + '.py'] = Path(sys.modules[name].__file__)
        for name in self.report['fixtureHashes']:
            names.setdefault(name, root / name)
        for name, path in names.items():
            digest = sha(path)
            assert digest == sha(root / name), name
            assert self.report.setdefault('fixtureActualPaths', {}).setdefault(name, str(path.resolve())) == str(path.resolve())
            assert self.report['fixtureHashes'].setdefault(name, digest) == digest
        assert sha(Path(__file__)) == report['harnessSha256']
        report['requestThreadShutdown'] = {'daemonThreads': False, 'blockOnClose': True}
        def forbidden_provider(*_args, **_kwargs):
            report['providerAttempts'].append(self.out.name)
            raise AssertionError('No model calls in route browser acceptance')
        lifecycle.enter_context(patch.object(sys.modules['home_assistant'], '_model_json', forbidden_provider))
        self.exchange_number = 0

    def facts(self):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database)) as con:
            return {table: sorted(con.execute('SELECT * FROM ' + table).fetchall(), key=repr) for table in FACT_TABLES}

    def database_proof(self, name):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database)) as con:
            value = {table: [list(row) for row in con.execute('SELECT * FROM ' + table + ' ORDER BY rowid')] for table in ROUTE_TABLES}
            assert con.execute('PRAGMA foreign_key_check').fetchall() == []
        path = self.out / (name + '.json')
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        self.report['databaseEvidence'].append({'path': path.relative_to(self.out.parent).as_posix(), 'sha256': sha(path)})
        return value

    def place(self, ctx, journey, name='合成地点', **changes):
        payload = dict(requestId=secrets.token_hex(16), name=name,
            journeyId=journey['id'], coordinates={'latitude': 31.234567, 'longitude': 121.456789})
        payload.update(changes)
        return self.write(ctx, 'POST', '/api/journey-places', payload, 201)['place']

    def setup_places(self, ctx, *, shared=False):
        journey = self.journey(ctx)
        points = [self.place(ctx, journey, name, visibility='shared' if shared else 'private',
            coordinateDisclosure='exact', coordinates={'latitude': 31.234567 + i, 'longitude': 121.456789 + i},
            status='planned') for i, name in enumerate(NAMES)]
        return journey, points

    def open_routes(self, page, journey, *, navigate=True):
        if navigate:
            page.goto(self.base + '/app/trips')
            page.bring_to_front()
            card = recap.heading(page, journey['trip']['title']).locator('xpath=ancestor::*[@data-testid="section-card-content"][1]')
            expect(button(card, '查看')).to_be_enabled(timeout=15000)
            button(card, '查看').click()
        expect(button(page, '旅行路线')).to_be_enabled(timeout=15000)
        button(page, '旅行路线').click()
        self.route_loaded(page)

    @staticmethod
    def route_loaded(page):
        expect(page.get_by_test_id('journey-routes-panel')).to_be_visible(timeout=15000)
        expect(page.get_by_label('正在核对路线', exact=True)).to_have_count(0, timeout=15000)

    def open_route(self, page, title, *, shared=False):
        if shared:
            button(page, '家庭共享路线').click()
        expect(button(page, '查看路线 ' + title)).to_be_enabled(timeout=15000)
        button(page, '查看路线 ' + title).click()
        expect(page.get_by_test_id('journey-route-map')).to_be_visible(timeout=15000)
        self.route_loaded(page)

    def new_route(self, page, title, names):
        button(page, '新建路线').click()
        editor = page.get_by_test_id('journey-route-editor')
        expect(editor).to_be_visible(timeout=15000)
        expect(page.get_by_role('textbox', name='路线名称', exact=True)).to_be_enabled(timeout=15000)
        page.get_by_role('textbox', name='路线名称', exact=True).fill(title)
        for index, name in enumerate(names):
            control = button(page, '添加站点 ' + name)
            expect(control).to_be_enabled(timeout=15000)
            if index == 0:
                control.focus(); expect(control).to_be_focused(); page.keyboard.press('Enter')
            else:
                control.click()

    def exchange(self, page, method, path, action, *, status=200, drop=None, before_fetch=None, after_response=None):
        """Completion is published only after the terminal fulfill/abort action."""
        self.exchange_number += 1
        stem = 'exchange-%02d' % self.exchange_number
        calls, url = [], self.base + path
        def intercept(route):
            assert route.request.method == method
            payload = route.request.post_data_json if method != 'GET' else None
            call = {'method': method, 'path': path, 'payload': payload, 'drop': drop,
                    'sentToServer': drop != 'request', 'status': None, 'result': None}
            if drop == 'request':
                route.abort('failed')
            else:
                if before_fetch:
                    before_fetch(payload)
                response = route.fetch(max_redirects=0)
                raw = response.body()
                saved = self.out / (stem + '.body')
                saved.write_bytes(raw)
                call.update(status=response.status, result=json.loads(raw), responseSha256=sha(saved))
                if after_response:
                    assert 'set-cookie' not in response.headers
                    after_response()
                if drop == 'response':
                    route.abort('failed')
                else:
                    route.fulfill(status=response.status, headers=response.headers, body=raw)
            calls.append(call)
        page.route(url, intercept, times=1)
        try:
            action()
            self.settle(page, lambda: bool(calls))
            assert len(calls) == 1 and calls[0]['status'] == (None if drop == 'request' else status), calls
            value = calls[0]
            saved = self.out / (stem + '.json')
            saved.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
            self.report['httpEvidence'].append({'path': saved.relative_to(self.out.parent).as_posix(), 'sha256': sha(saved)})
            return value
        finally:
            page.unroute(url, intercept)

    def save(self, page, method='POST', path=URL, **options):
        return self.exchange(page, method, path, lambda: button(page, '保存路线').click(),
                             status=201 if method == 'POST' else 200, **options)

    def current_detail(self, ctx, receipt):
        return self.get(ctx, URL + '/' + receipt['operation']['routeId'])

    def capture(self, page, name, width):
        page.set_viewport_size({'width': width, 'height': 1000 if width >= 1040 else 844})
        panel = page.get_by_test_id('journey-route-map')
        expect(panel).to_be_visible(timeout=15000)
        panel.scroll_into_view_if_needed()
        page.evaluate('() => document.fonts.ready')
        page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
        metrics = page.evaluate('''() => ({width:innerWidth,scroll:document.documentElement.scrollWidth,
          clipped:[...document.querySelectorAll('[data-testid="journey-routes-panel"] [role="button"], [data-testid="journey-routes-panel"] input')]
          .filter(n=>{const r=n.getBoundingClientRect();return r.width>0&&r.height>0&&r.bottom>0&&r.top<innerHeight&&(r.left< -2||r.right>innerWidth+2)})
          .map(n=>({label:n.getAttribute('aria-label')||n.textContent,box:n.getBoundingClientRect().toJSON()}))})''')
        assert metrics['scroll'] <= width + 2 and not metrics['clipped'], metrics
        path = self.out / (name + '-' + str(width) + '.png')
        page.screenshot(path=str(path), full_page=False)
        self.report['screenshots'].append({'path': path.relative_to(self.out.parent).as_posix(), 'sha256': sha(path),
            'width': width, 'metrics': metrics, 'scope': 'Settled visible viewport; not all internal scroll content or physical TV.'})

    @staticmethod
    def lines(page):
        return page.get_by_test_id('journey-route-map').locator('svg line[stroke-width="2"]')

    def private_order_restart_photos(self, browser):
        with self.flow(browser) as (ctx, page):
            journey, points = self.setup_places(ctx)
            self.photos(ctx, journey, caption='合成路线旅行照片')
            before = self.facts()
            self.open_routes(page, journey)
            self.new_route(page, PRIVATE, [NAMES[0], NAMES[1], NAMES[0]])
            button(page, '上移第 3 站').focus(); page.keyboard.press('Enter')
            expect(page.get_by_test_id('journey-route-stops')).to_contain_text('2. ' + NAMES[0])
            saved = self.save(page)['result']
            expect(button(page, '编辑路线')).to_be_enabled(timeout=15000)
            detail = self.current_detail(ctx, saved)
            assert detail['route']['visibility'] == 'private'
            assert [s['place']['id'] for s in detail['route']['stops']] == [points[0]['id'], points[0]['id'], points[1]['id']]
            assert detail['segments'] == [{'fromIndex': 0, 'toIndex': 1}, {'fromIndex': 1, 'toIndex': 2}]
            persisted = self.database_proof('after-private-save')
            page.reload()
            self.open_routes(page, journey)
            self.open_route(page, PRIVATE)
            assert self.current_detail(ctx, saved) == detail
            self.restart()  # Actual loopback listener and app recreate; same temporary SQLite and session cookies.
            self.open_routes(page, journey)
            self.open_route(page, PRIVATE)
            assert self.current_detail(ctx, saved) == detail
            assert self.database_proof('after-app-restart') == persisted
            for width in (390, 1280):
                self.capture(page, 'private-roundtrip', width)
            button(page, '查看旅行照片').focus(); page.keyboard.press('Enter')
            expect(page.get_by_test_id('trip-recap-content')).to_be_visible(timeout=15000)
            button(page, '查看照片 1').click()
            blob = self.image_loaded(page)
            button(page, '返回旅行路线').click()
            expect(page.get_by_test_id('journey-route-map')).to_be_visible(timeout=15000)
            self.assert_blob_revoked(page, blob)
            assert self.current_detail(ctx, saved) == detail and self.facts() == before
            self.passed('Private route: keyboard addition/reorder, repeated stops, true reload and listener/app restart, persistent SQLite receipt/order, real saved photo roundtrip without changing places or visits')

    def shared_projection_withdrawal(self, browser):
        with self.flow(browser) as (ctx, page):
            journey, points = self.setup_places(ctx, shared=True)
            self.open_routes(page, journey)
            self.new_route(page, '合成家庭共享路线', NAMES)
            private = self.save(page)['result']
            route_path = URL + '/' + private['operation']['routeId']
            expect(button(page, '编辑路线')).to_be_enabled(timeout=15000)
            button(page, '编辑路线').click()
            page.get_by_role('radio', name='家庭共享', exact=True).click()
            expect(button(page, '保存路线')).to_be_disabled()
            page.get_by_role('checkbox', name='已核对地点名称与坐标共享范围', exact=True).click()
            shared = self.save(page, 'PUT', route_path)['result']
            assert shared['current']['route']['visibility'] == 'shared'
            partner = self.context(browser, 2)
            try:
                other = partner.new_page()
                self.open_routes(other, journey)
                self.open_route(other, '合成家庭共享路线', shared=True)
                expect(button(other, '编辑路线')).to_have_count(0)
                expect(button(other, '删除路线')).to_have_count(0)
                expect(self.lines(other)).to_have_count(2)
                self.write(ctx, 'PATCH', '/api/journey-places/' + points[0]['id'], {'revision': 1, 'coordinateDisclosure': 'coarse'})
                coarse = self.exchange(other, 'GET', route_path, lambda: button(other, '刷新路线').click())['result']
                assert coarse['route']['stops'][0]['place']['coordinates'] == {'latitude': 31.2, 'longitude': 121.5}
                expect(self.lines(other).first).to_have_attribute('stroke-dasharray', '6 5')
                page.bring_to_front()
                self.route_loaded(page)
                expect(button(page, '刷新路线')).to_be_enabled(timeout=15000)
                author = self.exchange(page, 'GET', route_path, lambda: button(page, '刷新路线').click())['result']
                assert author['route']['stops'] == coarse['route']['stops']
                assert not author['route']['stops'][0]['place']['canManage']
                self.write(ctx, 'PATCH', '/api/journey-places/' + points[1]['id'], {'revision': 1, 'visibility': 'private'})
                missing = self.exchange(page, 'GET', route_path, lambda: button(page, '刷新路线').click())['result']
                assert missing['route']['stops'][1] == {'index': 1, 'state': 'unavailable'} and not missing['segments']
                expect(self.lines(page)).to_have_count(0)
                expect(page.get_by_test_id('journey-route-stops')).not_to_contain_text(NAMES[1])
                assert points[1]['id'] not in json.dumps(missing)
                for width in (390, 1280):
                    self.capture(page, 'shared-gap', width)
                other.bring_to_front()
                expect(button(other, '刷新路线')).to_be_enabled(timeout=15000)
                partner_missing = self.exchange(other, 'GET', route_path, lambda: button(other, '刷新路线').click())['result']
                assert partner_missing['route']['stops'] == missing['route']['stops']
                expect(self.lines(other)).to_have_count(0)
                expect(other.get_by_test_id('journey-route-stops')).not_to_contain_text(NAMES[1])
                # Route visibility is separate from point visibility. Withdraw
                # the route with the genuine owner API; the partner must clear.
                current = self.get(ctx, route_path)['route']
                self.write(ctx, 'PUT', route_path, {'requestId': secrets.token_hex(16),
                    'revision': current['revision'], 'sourceVersion': current['sourceVersion'], 'title': current['title'],
                    'journeyId': journey['id'], 'expectedJourneyRevision': journey['revision'], 'visibility': 'private',
                    'stops': [{'placeId': points[0]['id'], 'expectedRevision': 2}, {'keepUnavailableIndex': 1},
                              {'placeId': points[2]['id'], 'expectedRevision': 1}]})
                self.exchange(other, 'GET', route_path, lambda: button(other, '刷新路线').click(), status=404)
                expect(other.get_by_test_id('journey-route-map')).to_have_count(0)
                expect(other.get_by_test_id('journey-routes-panel')).not_to_contain_text('合成家庭共享路线')
                self.database_proof('after-explicit-sharing-and-withdrawal')
            finally:
                partner.close()
            self.passed('Explicit sharing needs reviewed public projection; partner is read-only; author/partner both coarse, withdrawn middle point has no identity or bridge, and route withdrawal clears partner view')

    def conflict_and_uncertain_writes(self, browser):
        with self.flow(browser) as (ctx, page):
            journey, points = self.setup_places(ctx)
            before = self.facts()
            self.open_routes(page, journey)
            self.new_route(page, '合成待核对路线', NAMES[:2])
            initial = self.save(page)['result']
            route_path = URL + '/' + initial['operation']['routeId']
            expect(button(page, '编辑路线')).to_be_enabled(timeout=15000)
            button(page, '编辑路线').click()
            title = page.get_by_role('textbox', name='路线名称', exact=True)
            expect(title).to_be_enabled(timeout=15000)
            title.fill('合成冲突后仍保留的草稿')
            def concurrent(payload):
                self.write(ctx, 'PUT', route_path, {**payload, 'requestId': secrets.token_hex(16), 'title': '合成另一浏览器已保存'})
            rejected = self.exchange(page, 'PUT', route_path, lambda: button(page, '保存路线').click(), status=409, before_fetch=concurrent)
            assert rejected['result']['code'] == 'revision_conflict'
            expect(title).to_have_value('合成冲突后仍保留的草稿')
            expect(button(page, '保存路线')).to_be_disabled()
            button(page, '读取最新内容').click()
            expect(button(page, '按当前地点核对草稿')).to_be_enabled(timeout=15000)
            button(page, '按当前地点核对草稿').click()
            lost = self.save(page, 'PUT', route_path, drop='response')
            key = lost['payload']['requestId']
            assert lost['result']['operation']['requestId'] == key and lost['result']['operation']['resultRevision'] == 3
            expect(page.get_by_test_id('journey-route-recovery')).to_be_visible(timeout=15000)
            expect(page.get_by_test_id('journey-route-map')).to_have_count(0)
            committed = self.database_proof('committed-before-recovery')
            recovered = self.exchange(page, 'GET', URL + '/operations/' + key, lambda: button(page, '核对原操作').click())
            assert recovered['result']['replayed'] and recovered['result']['operation'] == lost['result']['operation']
            expect(page.get_by_test_id('journey-route-recovery')).to_have_count(0)
            expect(button(page, '编辑路线')).to_be_enabled(timeout=15000)
            assert self.database_proof('after-recovery-no-second-write') == committed and self.facts() == before
            # Separate no-dispatch loss: receipt 404 is genuine. Change a real
            # place revision before retrying the identical body/key, not a mock
            # 409. Only an explicit final recheck may unlock a different intent.
            button(page, '返回路线列表').click()
            expect(button(page, '新建路线')).to_be_enabled(timeout=15000)
            self.new_route(page, '合成版本过期仍保留的草稿', NAMES[:1])
            unsent = self.save(page, drop='request')
            old_key = unsent['payload']['requestId']
            expect(page.get_by_test_id('journey-route-recovery')).to_be_visible(timeout=15000)
            expect(page.get_by_test_id('journey-route-map')).to_have_count(0)
            self.exchange(page, 'GET', URL + '/operations/' + old_key, lambda: button(page, '核对原操作').click(), status=404)
            self.write(ctx, 'PATCH', '/api/journey-places/' + points[0]['id'], {'revision': 1, 'city': '合成已核对新城市'})
            mark = len(self.requests)
            retry = self.exchange(page, 'POST', URL, lambda: button(page, '按原内容重试').click(), status=409)
            assert retry['payload'] == unsent['payload'] and retry['result']['code'] == 'source_changed'
            expect(button(page, '保留草稿并重新核对')).to_be_enabled(timeout=15000)
            proof_reads = [r['path'] for r in self.requests[mark:] if r['method'] == 'GET']
            assert '/api/journey-places/' + points[0]['id'] in proof_reads
            assert URL + '/operations/' + old_key in proof_reads
            assert self.get(ctx, URL + '/operations/' + old_key, 404)['code'] == 'not_found'
            button(page, '保留草稿并重新核对').click()
            expect(page.get_by_role('textbox', name='路线名称', exact=True)).to_have_value('合成版本过期仍保留的草稿')
            expect(page.get_by_test_id('journey-route-recovery')).to_have_count(0)
            button(page, '读取最新内容').click()
            expect(button(page, '按当前地点核对草稿')).to_be_enabled(timeout=15000)
            button(page, '按当前地点核对草稿').click()
            saved = self.save(page)
            assert saved['payload']['requestId'] != old_key and saved['payload']['stops'][0]['expectedRevision'] == 2
            assert saved['result']['operation']['kind'] == 'create'
            final = self.database_proof('after-explicit-new-version-save')
            assert len(final['journey_routes']) == 2 and len(final['journey_route_operations']) == 4
            self.passed('Real concurrent 409 preserves draft; real committed response loss recovers original receipt without rewriting; unsent loss plus actual place-version advance rejects identical retry and requires explicit draft recheck/save')

    def identity_hidden_offline(self, browser):
        with self.flow(browser) as (ctx, page):
            journey, _ = self.setup_places(ctx)
            self.open_routes(page, journey)
            self.new_route(page, PRIVATE, NAMES[:2])
            receipt = self.save(page)['result']
            route_path = URL + '/' + receipt['operation']['routeId']
            expect(button(page, '编辑路线')).to_be_enabled(timeout=15000)
            before = self.database_proof('before-privacy-events')
            def cleared():
                expect(page.get_by_test_id('journey-route-map')).to_have_count(0)
                expect(page.get_by_test_id('journey-route-stops')).to_have_count(0)
                expect(page.locator('body')).not_to_contain_text(PRIVATE)
                expect(page.locator('body')).not_to_contain_text(NAMES[0])
            visibility(page, True); cleared()
            visibility(page, False)
            expect(page.get_by_test_id('journey-route-map')).to_be_visible(timeout=15000)
            page.evaluate("window.dispatchEvent(new Event('blur'))"); cleared()
            page.evaluate("window.dispatchEvent(new Event('focus'))")
            expect(page.get_by_test_id('journey-route-map')).to_be_visible(timeout=15000)
            ctx.set_offline(True)
            try:
                cleared()
            finally:
                ctx.set_offline(False)
            visibility(page, False)
            expect(page.get_by_test_id('journey-route-map')).to_be_visible(timeout=15000)
            old = self.exchange(page, 'GET', route_path, lambda: button(page, '刷新路线').click(), after_response=lambda: self.login(ctx, 2))
            assert old['result']['route']['canManage'] and old['result']['route']['title'] == PRIVATE
            cleared()
            assert self.get(ctx, route_path, 404)['code'] == 'not_found'
            assert self.database_proof('after-privacy-events') == before
            self.passed('Real private detail is removed on browser hidden/blur/offline events; authentic delayed old-member HTTP response is discarded after actual member replacement, with no route writes')

    @classmethod
    def run_scenarios(cls, root, bundle, report, out, browser):
        for name in CASES:
            case_out = out / name; case_out.mkdir()
            folder = None
            before = len(report['checks'])
            case = {'name': name, 'passed': False}
            try:
                with ExitStack() as lifecycle:
                    folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='expo-journey-routes-')))
                    run = cls(root, bundle, folder, report, case_out, lifecycle)
                    getattr(run, name)(browser)
                assert len(report['checks']) == before + 1 and not folder.exists()
                assert run.server is None and not run.thread.is_alive()
                case['passed'] = True
                case['listenerStopped'] = True
            except Exception:
                del report['checks'][before:]
                failure = traceback.format_exc()
                (case_out / 'failure.txt').write_text(failure, encoding='utf-8')
                report['scenarioFailures'].append({'scenario': name, 'traceback': failure})
                print('FAIL ' + name + '\n' + failure, flush=True)
            finally:
                case['temporaryFixtureRemoved'] = folder is not None and not folder.exists()
                report['scenarioResults'].append(case)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--build-source-head')
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--expected-build-evidence', required=True)
    args = parser.parse_args()
    root, bundle = args.source_root.resolve(), args.bundle.absolute()
    assert sys.dont_write_bytecode and not sys.flags.optimize
    assert re.fullmatch('[a-f0-9]{40}', args.expected_head) and re.fullmatch('[a-f0-9]{64}', args.expected_build_evidence)
    def git(*command):
        return subprocess.check_output(['git', '--no-replace-objects', *command], cwd=root, text=True).strip()
    head, tree = git('rev-parse', 'HEAD'), git('rev-parse', 'HEAD^{tree}')
    assert head == args.expected_head and not git('status', '--porcelain=v1')
    evidence_path = bundle.parent / 'build-evidence.json'
    assert sha(evidence_path) == args.expected_build_evidence
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    build_head = args.build_source_head or head
    assert re.fullmatch('[a-f0-9]{40}', build_head)
    assert evidence['sourceHead'] == build_head and evidence['sourceTree'] == git('rev-parse', build_head + '^{tree}')
    if build_head != head:
        git('merge-base', '--is-ancestor', build_head, head)
        assert git('rev-parse', build_head + ':frontend') == git('rev-parse', head + ':frontend'), 'Reused build frontend differs'
    names = subprocess.check_output(['git', '--no-replace-objects', 'ls-files', '-z'], cwd=root).decode('utf-8').rstrip('\0').split('\0')
    def hashes():
        return {name: sha(root / name) for name in names}
    def exports():
        return export_hashes(bundle)
    assert exports() == evidence['files'] and all(sha(root / name) == value for name, value in evidence['inputFiles'].items())
    assert sha(Path(__file__)) == sha(root / HARNESS)
    out = root / 'test-results' / ('expo-journey-routes-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    shutil.copyfile(__file__, out / 'executed-harness.py')
    report = {'passed': False, 'checks': [], 'pageErrors': [], 'externalRequests': [], 'providerAttempts': [],
        'screenshots': [], 'scenarioResults': [], 'scenarioFailures': [], 'httpEvidence': [], 'databaseEvidence': [],
        'requestedChecks': len(CASES), 'head': head, 'tree': tree, 'buildEvidenceSha256': sha(evidence_path),
        'harnessSha256': sha(out / 'executed-harness.py'), 'buildSourceHead': build_head, 'buildSourceTree': evidence['sourceTree'],
        'reusedBuild': build_head != head, 'buildSourceDelta': git('diff', '--name-only', build_head, head).splitlines(),
        'sourceRoot': str(root), 'bundleRoot': str(bundle), 'sourceHashesBefore': hashes(), 'bundleHashesBefore': exports(),
        'productionWrites': 0, 'realModel': False, 'realCloud': False, 'physicalTelevision': False,
        'scope': 'Four synthetic real Flask/SQLite/loopback HTTPS/Edge route flows with an ad hoc temporary certificate; saved photo provider jobs are synthetic, business DTOs/image reads real. Visibility/blur events are simulated browser events, not physical-device acceptance.'}
    original_connect = socket.socket.connect
    def local_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
            report['externalRequests'].append({'kind': 'non-loopback socket'})
            raise AssertionError('External network forbidden')
        return original_connect(sock, address)
    try:
        with patch.object(socket.socket, 'connect', local_connect), sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            try:
                Run.run_scenarios(root, bundle, report, out, browser)
                assert len(report['checks']) == len(CASES) and len(report['screenshots']) == 4
                assert not report['scenarioFailures'] and not report['pageErrors'] and not report['externalRequests'] and not report['providerAttempts']
                report['passed'] = True
            finally:
                browser.close()
    except Exception:
        report['failure'] = traceback.format_exc()
        print(report['failure'], flush=True)
    finally:
        report['sourceHashesAfter'], report['bundleHashesAfter'] = hashes(), exports()
        report['sourceUnchanged'] = report['sourceHashesBefore'] == report['sourceHashesAfter']
        report['bundleUnchanged'] = report['bundleHashesBefore'] == report['bundleHashesAfter']
        report['fixtureHashesAfter'] = {name: sha(Path(path)) for name, path in report.get('fixtureActualPaths', {}).items()}
        report['fixturesUnchanged'] = bool(report.get('fixtureHashes')) and report['fixtureHashesAfter'] == report['fixtureHashes']
        report['sourceStillFrozen'] = git('rev-parse', 'HEAD') == head and git('rev-parse', 'HEAD^{tree}') == tree and not git('status', '--porcelain=v1')
        report['temporaryFixtureRemoved'] = len(report['scenarioResults']) == len(CASES) and all(c['temporaryFixtureRemoved'] for c in report['scenarioResults'])
        report['passed'] = report['passed'] and all(report[key] for key in ('sourceUnchanged', 'bundleUnchanged', 'fixturesUnchanged', 'sourceStillFrozen', 'temporaryFixtureRemoved'))
        (out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'report': str(out / 'result.json')}, ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
