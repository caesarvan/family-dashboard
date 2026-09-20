"""Two real temporary HTTPS/SQLite/Edge trip-to-TV flows; no business DTO mocks."""
import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import importlib
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
import threading
import time
import traceback
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from flask import request
from playwright.sync_api import expect, sync_playwright
import browser_expo_media_video_check as video_fixture
import browser_finance_flow_mapping_check as build_fixture
from browser_expo_finance_check import button, sha
from browser_expo_local_photo_check import Run as LocalRun
from browser_expo_photo_duplicates_check import BrowserHttpGuard
from browser_expo_photo_suggestions_check import Run as SuggestionRun
from browser_expo_journey_routes_check import Run as RoutesRun
from scripts.check_expo_media_video_browser import tool_identity
from media_videos import VideoTools

HARNESS = 'tests/browser_tv_trip_playback_check.py'
DOCUMENT = 'docs/TV-TRIP-BROWSER.md'
CASES = ('trip_route_media_controls', 'lost_start_revocation_isolation')
CASE_SCREENSHOTS = dict(zip(CASES, (3, 3)))
TIMEOUT = 15000
TV_HEADERS = {'X-Display-Mode': 'tv'}
CONTROL = '/api/media-playback/devices/'
OPERATIONS = '/api/media-playback/operations/'
FACT_TABLES = ('entities', 'journey_workflows', 'journey_places', 'journey_routes',
               'journey_route_stops', 'media_items', 'media_video_cache', 'media_tv_grants')


class Run(video_fixture.Run):
    make_journey = SuggestionRun.make_journey
    place = RoutesRun.place
    record = LocalRun.record

    def __init__(self, root, bundle, folder, report, out, lifecycle, tools):
        self.serial, self.tv_pages, self.tv_requests = 0, [], []
        super().__init__(root, bundle, folder, report, out, lifecycle, tools)
        self.http_guard = BrowserHttpGuard(self.base, out.name, out, report)
        self.journal, self.journal_lock = [], threading.Lock()
        paths = {HARNESS: Path(__file__)}
        for name in ('browser_expo_media_video_check', 'browser_expo_local_photo_check',
                     'browser_expo_photo_duplicates_check', 'browser_expo_photo_suggestions_check', 'browser_expo_journey_routes_check',
                     'browser_finance_flow_mapping_check'):
            paths['tests/' + name + '.py'] = Path(sys.modules[name].__file__)
        paths['scripts/check_expo_media_video_browser.py'] = Path(sys.modules['scripts.check_expo_media_video_browser'].__file__)
        for name in ('media_trip_playback', 'journey_routes', 'journey_places', 'journey_workflows'):
            paths[name + '.py'] = Path(importlib.import_module(name).__file__)
        for name, path in paths.items():
            assert path.resolve() == (root / name).resolve(), name
        hashes = {name: sha(path) for name, path in paths.items()}
        assert report.setdefault('tripFixtureHashes', hashes) == hashes

        @self.application.after_request
        def journal(response):
            if request.path.startswith('/api/'):
                entry = dict(method=request.method, path=request.path, status=response.status_code,
                             monotonic=time.monotonic())
                if request.path.endswith('/journey-start') and request.method == 'POST':
                    entry['requestId'] = (request.get_json(silent=True) or {}).get('requestId')
                if request.path == '/api/media-tv/playback/progress' and request.method == 'POST':
                    body = request.get_json(silent=True) or {}
                    entry['progress'] = {k:body.get(k) for k in ('event','itemId','itemRevision','playId','sequence','positionMs')}
                with self.journal_lock:
                    self.journal.append(entry)
                    with (out / 'server-http.jsonl').open('a', encoding='utf-8', newline='\n') as stream:
                        stream.write(json.dumps(entry) + '\n'); stream.flush()
            return response

    def context(self, browser, member=1):
        ctx = super().context(browser, member)
        ctx.set_default_timeout(TIMEOUT); ctx.set_default_navigation_timeout(TIMEOUT)
        self.http_guard.attach(ctx)
        return ctx

    def evidence(self, name, value, group='httpEvidence'):
        self.serial += 1
        self.record(f'{self.serial:03}-{name}', value, group)

    def completed_json(self, page, name, method, path, trigger, expected_status=200):
        self.serial += 1
        return LocalRun.completed_json(self, page, f'{self.serial:03}-{name}', method,
                                       self.base + path, trigger, expected_status)

    def response_action(self, page, path, method, action, status=200, name=None):
        # Never inherit the older video's unbounded Response.finished().
        value, self.last_action_request = self.completed_json(page, name or 'control', method, path, action, status)
        return value

    def capture(self, page, name, focus=None):
        if focus is not None:
            expect(focus).to_be_visible(); focus.scroll_into_view_if_needed()
        page.evaluate('() => document.fonts.ready')
        page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
        width = page.viewport_size['width']
        assert width in (390, 1280, 1920)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2')
        path = self.out / (name + '.png'); page.screenshot(path=str(path), full_page=False)
        self.report['screenshots'].append(dict(path=path.relative_to(self.out.parent).as_posix(),
            sha256=sha(path), width=width, scope='Actual visible viewport, not physical television.'))

    def facts(self):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database)) as con:
            def encoded(value):
                if isinstance(value, bytes): return {'bytes': len(value), 'sha256': hashlib.sha256(value).hexdigest()}
                return value
            return {table: hashlib.sha256(json.dumps([[encoded(v) for v in row] for row in
                con.execute('SELECT * FROM "' + table + '" ORDER BY rowid')], ensure_ascii=False).encode()).hexdigest()
                for table in FACT_TABLES}

    def operations(self):
        with closing(sqlite3.connect(self.database)) as con:
            return [list(row) for row in con.execute('SELECT owner,request_id,device_id FROM media_playback_operations ORDER BY owner,request_id')]

    def bookkeeping(self):
        with closing(sqlite3.connect(self.database)) as con:
            return dict(meta=con.execute("SELECT revision FROM settings WHERE id='meta'").fetchone()[0],
                audit=[list(r) for r in con.execute('SELECT actor,action,target FROM audit ORDER BY rowid')])

    @contextmanager
    def flow(self, browser):
        with super().flow(browser) as value:
            try: yield value
            except Exception:
                for index, page in enumerate(self.tv_pages):
                    if not page.is_closed():
                        try:
                            page.screenshot(path=str(self.out / f'failure-tv-{index+1}.png'), full_page=False)
                            (self.out / f'failure-tv-{index+1}-aria.txt').write_text(page.locator('body').aria_snapshot(), encoding='utf-8')
                        except Exception: pass  # Preserve the original failure.
                raise

    def start_count(self, path):
        return sum(r['method'] == 'POST' and r['path'] == path for r in self.journal)

    def tv(self, ctx, status=200):
        response = ctx.request.get(self.base + '/api/media-tv/playback', headers=TV_HEADERS, timeout=TIMEOUT)
        assert response.status == status
        return response.json()

    def screen(self, ctx):
        page = ctx.new_page(); page.set_viewport_size({'width': 1920, 'height': 1080})
        page.on('request', lambda req: self.tv_requests.append(dict(method=req.method, path=urlsplit(req.url).path,
            displayMode=req.headers.get('x-display-mode'))))
        page.goto(self.base + '/tv'); self.tv_pages.append(page)
        expect(page.get_by_test_id('expo-tv-board')).to_be_visible(timeout=TIMEOUT)
        return page

    def pair(self, browser, owner, name):
        device, ctx = super().pair(browser, owner, name)
        cookie = next(c for c in ctx.cookies() if c['name'] == 'household_tv')
        assert cookie['httpOnly'] and cookie['secure'] and cookie['sameSite'] == 'Strict'
        actor = self.get(ctx, '/api/me')['user']
        assert actor['role'] == 'tv' and actor['id'] == device['id']
        self.evidence('paired-tv', dict(deviceId=device['id'], httpOnly=True, secure=True, sameSite='Strict'))
        return device, ctx

    def assert_tv_requests(self):
        requests = [r for r in self.tv_requests if r['path'].startswith('/api/')]
        assert requests and all(r['displayMode'] == 'tv' for r in requests)
        assert all(r['method'] == 'GET' or r['method'] == 'POST' and r['path'] == '/api/media-tv/playback/progress' for r in requests)
        assert not any(r['path'].startswith(('/api/accounts', '/api/media/imports', '/api/media-playback/operations')) for r in requests)
        self.evidence('tv-request-scope', requests)

    def withdraw_route(self, ctx, uid):
        route = self.get(ctx, '/api/journey-routes/' + uid)['route']
        journey = self.get(ctx, '/api/journeys/' + route['journeyId'])
        stops = []
        for stop in route['stops']:
            if stop['state'] == 'unavailable': stops.append({'keepUnavailableIndex': stop['index']})
            else:
                point = self.get(ctx, '/api/journey-places/' + stop['place']['id'])['place']
                stops.append(dict(placeId=point['id'], expectedRevision=point['revision']))
        return self.write(ctx, 'PUT', '/api/journey-routes/' + uid, dict(requestId=secrets.token_hex(16),
            revision=route['revision'], sourceVersion=route['sourceVersion'], title=route['title'],
            journeyId=journey['id'], expectedJourneyRevision=journey['revision'], stops=stops, visibility='private'))

    def bound_item(self, ctx, journey, caption, *, video=False, shared=True, device=None):
        item = self.video(ctx) if video else self.photo(ctx)
        item = self.write(ctx, 'PATCH', '/api/media/items/' + item['id'], dict(revision=item['revision'],
            journeyId=journey['id'], caption=caption, visibility='shared' if shared else 'private'))['item']
        return self.grant(ctx, item, device) if device else item

    def route(self, ctx, journey, title, *, count=9, shared=True):
        points = [self.place(ctx, journey, name=f'合成站点 {i+1}', visibility='shared' if shared else 'private',
            coordinateDisclosure=('coarse' if i == 1 else 'hidden' if i == 2 else 'exact'),
            coordinates={'latitude': 31.234567 + i / 10, 'longitude': 121.456789 + i / 10}) for i in range(count)]
        value = self.write(ctx, 'POST', '/api/journey-routes', dict(requestId=secrets.token_hex(16),
            title=title, journeyId=journey['id'], expectedJourneyRevision=journey['revision'],
            visibility='shared' if shared else 'private',
            stops=[dict(placeId=p['id'], expectedRevision=p['revision']) for p in points]), 201)
        return value['current']['route'], points

    def seed(self, browser, ctx, *, with_video=True):
        journey = self.make_journey(ctx, '合成电视旅行 A')
        other = self.make_journey(ctx, '不可串入的旅行 B')
        route_only = self.make_journey(ctx, '只有路线的旅行')
        first, tv1 = self.pair(browser, ctx, '合成客厅电视')
        second, tv2 = self.pair(browser, ctx, '合成书房电视')
        authorized = [self.bound_item(ctx, journey, '已授权照片 ' + str(n+1), device=first) for n in range(2)]
        if with_video: authorized.append(self.bound_item(ctx, journey, '已授权短视频', video=True, device=first))
        excluded = [self.bound_item(ctx, journey, '不应透露的私人照片', shared=False),
                    self.bound_item(ctx, journey, '本电视未获许可的照片'),
                    self.bound_item(ctx, other, '另一旅行已有电视许可的照片', device=first)]
        route, points = self.route(ctx, journey, '合成共享旅行路线')
        private_route, _ = self.route(ctx, journey, '不应透露的私人路线', count=1, shared=False)
        only_route, _ = self.route(ctx, route_only, '合成仅路线回顾', count=2)
        self.evidence('fixture-identities', dict(journey=journey['id'], otherJourney=other['id'],
            routeOnlyJourney=route_only['id'], devices=[first['id'], second['id']], route=route['id'],
            authorized=[i['id'] for i in authorized], excluded=[i['id'] for i in excluded]), 'databaseEvidence')
        return dict(journey=journey, other=other, routeOnly=route_only, route=route, points=points,
            privateRoute=private_route, onlyRoute=only_route, authorized=authorized, excluded=excluded,
            first=first, second=second, tv1=tv1, tv2=tv2)

    def open_preview(self, page, fixture, *, route=None, journey=None, device=None):
        journey, device = journey or fixture['journey'], device or fixture['first']
        self.open_panel(page, journey)
        page.get_by_test_id('trip-tv-entry').click()
        expect(page.get_by_test_id('trip-tv-panel')).to_be_visible()
        page.get_by_test_id('trip-tv-device-' + device['id']).get_by_role('radio').click()
        page.get_by_test_id('trip-tv-route-' + (route['id'] if route else 'none')).get_by_role('radio').click()
        before, operations, bookkeeping = self.facts(), self.operations(), self.bookkeeping()
        expect(page.get_by_test_id('trip-tv-preview')).to_be_enabled(timeout=TIMEOUT)
        result, body = self.completed_json(page, 'preview', 'POST', CONTROL + device['id'] + '/journey-preview',
            lambda: page.get_by_test_id('trip-tv-preview').click())
        assert body == dict(revision=self.get(page.context, CONTROL + device['id'])['revision'],
                            journeyId=journey['id'], routeId=route['id'] if route else None)
        assert result['canStart'] and result['journey']['id'] == journey['id']
        assert result['routeStatus'] == ('available' if route else 'not_selected')
        assert self.facts() == before and self.operations() == operations and self.bookkeeping() == bookkeeping, 'Preview must not modify business data'
        expect(page.get_by_test_id('trip-tv-start')).to_be_enabled()
        return result

    def start_ui(self, page, fixture, **selection):
        preview = self.open_preview(page, fixture, **selection)
        device = selection.get('device') or fixture['first']
        before, count, bookkeeping = self.facts(), len(self.operations()), self.bookkeeping()
        result, body = self.completed_json(page, 'start', 'POST', CONTROL + device['id'] + '/journey-start',
            lambda: page.get_by_test_id('trip-tv-start').click())
        assert set(body) == {'requestId', 'previewToken', 'confirmStart'} and body['confirmStart'] is True
        assert body['previewToken'] == preview['previewToken']
        assert result['operation']['requestId'] == body['requestId'] and result['operation']['deviceId'] == device['id']
        assert result['operation']['kind'] == 'journey_start' and result['replayed'] is False
        assert self.facts() == before and len(self.operations()) == count + 1, 'Start must not create media/route grants'
        after = self.bookkeeping()
        assert after == dict(meta=bookkeeping['meta'] + 1,
            audit=bookkeeping['audit'] + [['member1', 'media_playback_journey_start', device['id']]])
        return result

    def control(self, page, uid, action, label):
        page.bring_to_front(); expect(button(page, label)).to_be_enabled(timeout=TIMEOUT)
        value = self.response_action(page, CONTROL + uid, 'PUT', lambda: button(page, label).click(), name='phone-' + action)
        assert self.last_action_request['action'] == action
        return value

    def assert_projection(self, state, fixture):
        assert state['scope'] == 'journey' and state['journeyReview']['status'] == 'ready'
        assert state['journeyReview']['journey']['id'] == fixture['journey']['id']
        assert state['photoCount'] == len(fixture['authorized'])
        projection = state['journeyReview']['route']; points = fixture['points']
        assert projection['id'] == fixture['route']['id']
        stops = projection['stops']; assert len(stops) == len(points)
        assert stops[0]['place']['coordinates'] == points[0]['coordinates']
        assert stops[1]['place']['coordinates'] == points[1]['sharedCoordinates']
        assert stops[1]['place']['coordinatePrecision'] == 'approximate'
        assert stops[2]['place']['coordinates'] is None and stops[2]['place']['coordinatePrecision'] == 'hidden'
        assert all(s['fromIndex'] + 1 == s['toIndex'] and 2 not in (s['fromIndex'], s['toIndex']) for s in projection['segments'])
        for stop in stops:
            assert not set(stop['place']) & {'owner', 'canManage', 'coordinateDisclosure', 'sharedCoordinates'}
        raw = json.dumps(state, ensure_ascii=False)
        for item in fixture['excluded']: assert item['id'] not in raw and item['caption'] not in raw
        assert fixture['privateRoute']['id'] not in raw

    def trip_route_media_controls(self, browser):
        with self.flow(browser) as (ctx, phone):
            f = self.seed(browser, ctx); first, second = f['first']['id'], f['second']['id']
            self.start_ui(phone, f, journey=f['routeOnly'], route=f['onlyRoute'], device=f['second'])
            second_before = self.get(ctx, CONTROL + second)
            assert second_before['scope'] == 'journey' and second_before['photoCount'] == 0 and second_before['canStart']
            expect(phone.get_by_test_id('trip-tv-next')).to_have_count(0)
            expect(phone.get_by_test_id('trip-tv-previous')).to_have_count(0)
            self.start_ui(phone, f, route=f['route'])
            self.capture(phone, '390-explicit-trip-start', phone.get_by_test_id('trip-tv-status'))
            screen, other_screen = self.screen(f['tv1']), self.screen(f['tv2'])
            expect(screen.get_by_test_id('tv-trip-recap')).to_be_visible(timeout=TIMEOUT)
            expect(other_screen.get_by_test_id('tv-trip-route')).to_contain_text(f['onlyRoute']['title'], timeout=TIMEOUT)
            self.assert_projection(self.tv(f['tv1']), f)
            expect(screen.get_by_test_id('tv-trip-route')).to_contain_text(f['route']['title'])
            pager = screen.get_by_test_id('tv-trip-route-page')
            expect(pager).to_contain_text('第 2 / 2 页', timeout=20000)
            expect(screen.get_by_test_id('tv-trip-stop-8')).to_be_visible()
            # Observe real media decoding; never seek, dispatch ended, or advance browser clocks.
            screen.wait_for_function("() => {const v=document.querySelector('[data-testid=tv-media-video]'); return v && !v.hidden && !v.paused && v.currentTime>.3 && v.videoWidth>0}", timeout=40000)
            self.control(phone, first, 'pause', '暂停回顾')
            screen.wait_for_function("() => document.querySelector('[data-testid=tv-media-video]').paused", timeout=TIMEOUT)
            paused = screen.get_by_test_id('tv-media-video').evaluate('v=>v.currentTime')
            video_url = screen.get_by_test_id('tv-media-video').evaluate('v=>v.currentSrc')
            expect(pager).to_contain_text('翻页已暂停', timeout=TIMEOUT)
            paused_page = pager.inner_text()
            # Observe one complete real 15-second page interval while paused.
            # This is the behavior under test, not a sleep used to conceal a race.
            began = screen.evaluate('performance.now()')
            screen.wait_for_function('t=>performance.now()-t>=15500', arg=began, timeout=18000)
            assert pager.inner_text() == paused_page
            assert abs(screen.get_by_test_id('tv-media-video').evaluate('v=>v.currentTime') - paused) < .08
            self.capture(screen, '1920-route-and-real-video', screen.get_by_test_id('tv-trip-recap'))
            ended_before = len(screen.evaluate('window.__mediaEvidence.ended'))
            resumed_at = time.monotonic()
            self.control(phone, first, 'resume', '继续回顾')
            screen.wait_for_function("t=>{const v=document.querySelector('[data-testid=tv-media-video]');return v.currentTime>t+.2&&!v.paused}", arg=paused, timeout=TIMEOUT)
            screen.wait_for_function('n => window.__mediaEvidence.ended.length>n && window.__mediaEvidence.ended.at(-1).ended', arg=ended_before, timeout=TIMEOUT)
            native_ended = screen.evaluate('window.__mediaEvidence.ended')
            assert native_ended[-1]['src'] == video_url and native_ended[-1]['time'] >= native_ended[-1]['duration'] - .1
            expect(screen.get_by_test_id('tv-photo-image')).to_be_visible(timeout=TIMEOUT)
            screen.wait_for_function("() => {const i=document.querySelector('[data-testid=tv-photo-image]');return i && i.complete && i.naturalWidth>0}", timeout=TIMEOUT)
            video_id = next(i['id'] for i in f['authorized'] if i.get('mediaType') == 'video')
            accepted = [r for r in self.journal if r.get('progress', {}).get('event') == 'ended'
                and r['progress']['itemId'] == video_id and r['status'] == 200 and r['monotonic'] >= resumed_at]
            assert len(accepted) == 1
            self.control(phone, first, 'next', '下一项')
            assert self.tv(f['tv1'])['scope'] == 'journey'
            self.control(phone, first, 'pause', '暂停回顾')
            retained = self.get(ctx, CONTROL + first)
            screen.reload(); expect(screen.get_by_test_id('tv-trip-recap')).to_be_visible(timeout=TIMEOUT)
            current = self.tv(f['tv1']); assert current['paused'] and current['scope'] == 'journey'
            assert current['revision'] == retained['revision'] and current['journeyReview']['journey']['id'] == f['journey']['id']
            self.control(phone, first, 'dashboard', '返回家庭看板')
            expect(screen.get_by_test_id('tv-trip-recap')).to_be_hidden(timeout=TIMEOUT)
            expect(screen.get_by_test_id('expo-tv-board')).to_be_visible()
            assert self.get(ctx, CONTROL + second) == second_before
            self.capture(other_screen, '1920-independent-route-only', other_screen.get_by_test_id('tv-trip-route'))
            self.evidence('native-ended-and-independent-tv', dict(ended=native_ended,
                acceptedProgress=accepted,
                pausedPage=paused_page, second=second_before, firstAfter=self.get(ctx, CONTROL + first)))
            self.http_guard.assert_clean()
            self.assert_tv_requests()
            self.passed('Explicit trip start, real mixed photo/video and ended, pause/next/dashboard, reload and independent route-only TV')

    def lost_start_revocation_isolation(self, browser):
        with self.flow(browser) as (ctx, phone):
            phone.set_viewport_size({'width': 1280, 'height': 900})
            f = self.seed(browser, ctx, with_video=False); uid = f['first']['id']
            self.open_preview(phone, f, route=f['route'])
            path, lost = CONTROL + uid + '/journey-start', []
            before, operation_count, bookkeeping = self.facts(), len(self.operations()), self.bookkeeping()
            def lose(route):
                response = route.fetch(max_redirects=0, timeout=TIMEOUT)
                try:
                    assert response.status == 200
                    value, body = response.json(), route.request.post_data_json
                    self.evidence('committed-before-response-loss', dict(status=response.status, request=body, response=value), 'databaseEvidence')
                    lost.append((body, value)); route.abort('failed')
                finally: response.dispose()
            phone.route(self.base + path, lose, times=1)
            try:
                with phone.expect_event('requestfailed', predicate=lambda r:r.url == self.base + path and r.method == 'POST', timeout=TIMEOUT):
                    phone.get_by_test_id('trip-tv-start').click()
                expect(phone.get_by_test_id('trip-tv-unknown')).to_be_visible()
                expect(phone.get_by_test_id('trip-tv-recheck')).to_be_enabled()
            finally: phone.unroute(self.base + path, lose)
            assert len(lost) == 1 and self.facts() == before and len(self.operations()) == operation_count + 1
            after_commit = self.bookkeeping()
            assert after_commit == dict(meta=bookkeeping['meta'] + 1,
                audit=bookkeeping['audit'] + [['member1', 'media_playback_journey_start', uid]])
            request_id = lost[0][0]['requestId']; committed = self.operations()
            marker = phone.evaluate("JSON.parse(sessionStorage.getItem('family-dashboard:trip-tv-operation:v1'))")
            assert set(marker) == {'memberIdentity', 'deviceId', 'requestId'}
            assert marker['deviceId'] == uid and marker['requestId'] == request_id
            self.capture(phone, '1280-unknown-original-start', phone.get_by_test_id('trip-tv-unknown'))
            value, _ = self.completed_json(phone, 'get-original-operation', 'GET', OPERATIONS + request_id,
                lambda: phone.get_by_test_id('trip-tv-recheck').click())
            assert value['found'] and value['operation'] == lost[0][1]['operation']
            expect(phone.get_by_test_id('trip-tv-unknown')).to_have_count(0)
            assert phone.evaluate("sessionStorage.getItem('family-dashboard:trip-tv-operation:v1')") is None
            assert self.bookkeeping() == after_commit and self.operations() == committed and self.facts() == before
            # Reload recovery must observe the same scope; never generate another start.
            phone.reload(); self.open_panel(phone, f['journey']); phone.get_by_test_id('trip-tv-entry').click()
            expect(phone.get_by_test_id('trip-tv-panel')).to_be_visible()
            phone.get_by_test_id('trip-tv-device-' + uid).get_by_role('radio').click()
            expect(phone.get_by_test_id('trip-tv-current')).to_be_enabled(timeout=TIMEOUT)
            self.completed_json(phone, 'reload-current-scope', 'GET', CONTROL + uid,
                lambda: phone.get_by_test_id('trip-tv-current').click())
            expect(phone.get_by_test_id('trip-tv-controls')).to_contain_text(f['journey']['trip']['title'])
            assert self.operations() == committed and self.start_count(path) == 1
            self.late_member_preview(phone, f, request_id)
            self.login(ctx, 1)  # A new real owner session, never a browser-global user injection.
            phone.reload()
            screen = self.screen(f['tv1']); expect(screen.get_by_test_id('tv-trip-recap')).to_be_visible(timeout=TIMEOUT)
            self.assert_projection(self.tv(f['tv1']), f)
            # Every denial below is an actual current-authority response, not a substituted DTO.
            invitation = self.write(ctx, 'POST', '/api/spaces/invitations', {}, 201)['invitation']
            child_entry = self.write(ctx, 'POST', '/api/spaces/redeem', dict(invitation=invitation,
                name='合成另一家庭', slug='tv-trip-other', MEMBER1_PASSWORD='testing-password-one', MEMBER2_PASSWORD='testing-password-two'), 201)['entry']
            child = self.context(browser, None); self.lifecycle.callback(child.close)
            assert child.request.get(self.base + child_entry).status == 200; self.login(child)
            self.get(child, CONTROL + uid, 404)
            assert self.get(child, OPERATIONS + request_id) == {'found': False}
            self.write(child, 'POST', CONTROL + uid + '/journey-preview', dict(revision=0, journeyId=f['journey']['id'], routeId=None), 404)
            self.write(ctx, 'POST', CONTROL + uid + '/journey-preview', dict(revision=self.get(ctx, CONTROL + uid)['revision'],
                journeyId=f['journey']['id'], routeId=f['privateRoute']['id']), 404)
            for row in f['excluded']:
                # Other-trip media has an independent grant but must never be selected by this scope.
                if row['id'] != f['excluded'][-1]['id']:
                    assert f['tv1'].request.get(self.base + '/api/media-tv/items/' + row['id'] + '/preview', headers=TV_HEADERS).status == 404
                assert f['tv2'].request.get(self.base + '/api/media-tv/items/' + row['id'] + '/preview', headers=TV_HEADERS).status == 404
            middle = f['points'][4]
            self.write(ctx, 'PATCH', '/api/journey-places/' + middle['id'], dict(revision=middle['revision'], visibility='private'))
            expect(screen.get_by_test_id('tv-trip-stop-4')).to_contain_text('此站不可展示', timeout=20000)
            expect(screen.get_by_test_id('tv-trip-route')).not_to_contain_text(middle['name'])
            projected = self.tv(f['tv1'])['journeyReview']['route']
            assert projected['stops'][4] == {'index': 4, 'state': 'unavailable'}
            assert not any(s['fromIndex'] <= 4 <= s['toIndex'] for s in projected['segments'])
            assert middle['id'] not in json.dumps(projected)
            self.evidence('current-shared-gap', projected)
            # Withdraw route sharing while media still exists: keep the selected
            # journey and its authorized media, but no historical route DTO.
            self.withdraw_route(ctx, f['route']['id'])
            expect(screen.locator('body')).not_to_contain_text(f['route']['title'], timeout=TIMEOUT)
            state = self.tv(f['tv1'])
            assert state['journeyReview']['routeStatus'] == 'unavailable' and state['journeyReview']['route'] is None
            assert state['photoCount'] == len(f['authorized'])
            # A second independent route-only scope verifies that losing media
            # permissions does not require falling back to the global album.
            self.start_ui(phone, f, journey=f['routeOnly'], route=f['onlyRoute'], device=f['second'])
            other_screen = self.screen(f['tv2'])
            expect(other_screen.get_by_test_id('tv-trip-route')).to_contain_text(f['onlyRoute']['title'], timeout=TIMEOUT)
            f['tv2'].set_offline(True)
            expect(other_screen.get_by_test_id('tv-trip-recap')).to_be_hidden(timeout=TIMEOUT)
            f['tv2'].set_offline(False)
            expect(other_screen.get_by_test_id('tv-trip-route')).to_contain_text(f['onlyRoute']['title'], timeout=TIMEOUT)
            for item in f['authorized']:
                latest = self.media(ctx, item['id'])
                self.write(ctx, 'PUT', '/api/media/items/' + item['id'] + '/tv-grants', dict(revision=latest['revision'], deviceIds=[]))
            expect(screen.get_by_test_id('tv-photo-image')).to_be_hidden(timeout=TIMEOUT)
            state = self.tv(f['tv1']); assert state['scope'] == 'journey' and state['photoCount'] == 0 and state['item'] is None and state['progress'] is None
            for item in f['authorized']:
                assert f['tv1'].request.get(self.base + '/api/media-tv/items/' + item['id'] + '/preview', headers=TV_HEADERS).status == 404
            self.capture(other_screen, '1920-independent-route-only-after-withdrawal', other_screen.get_by_test_id('tv-trip-route'))
            self.write(ctx, 'DELETE', '/api/items/trips/' + f['journey']['tripId'], dict(revision=f['journey']['trip']['revision']))
            state = self.tv(f['tv1']); assert state['scope'] == 'journey' and state['journeyReview']['status'] == 'journey_unavailable'
            assert state['journeyReview']['journey'] is None and state['item'] is None and state['photoCount'] == 0 and not state['canStart']
            expect(screen.locator('body')).not_to_contain_text(f['journey']['trip']['title'], timeout=TIMEOUT)
            self.capture(screen, '1920-deleted-trip-no-album-fallback')
            self.write(ctx, 'DELETE', '/api/devices/' + uid, {})
            self.tv(f['tv1'], 401)
            expect(screen.get_by_test_id('tv-trip-recap')).to_be_hidden(timeout=TIMEOUT)
            receipt = self.get(ctx, OPERATIONS + request_id); assert receipt['found'] and receipt['playback'] is None
            assert self.start_count(path) == 1
            self.http_guard.assert_clean()
            self.assert_tv_requests()
            self.passed('Real committed response loss uses original GET receipt without duplicate start; current grants/routes/journey/device and foreign household deny stale content')

    def late_member_preview(self, page, fixture, request_id):
        """Release an actual old-owner projection after real login replaces its cookie."""
        uid = fixture['first']['id']; path = CONTROL + uid + '/journey-preview'
        page.get_by_test_id('trip-tv-route-' + fixture['route']['id']).get_by_role('radio').click()
        expect(page.get_by_test_id('trip-tv-preview-content')).to_have_count(0)
        expect(page.get_by_test_id('trip-tv-preview')).to_be_enabled(timeout=TIMEOUT)
        page.evaluate("""() => {window.__tripLeaks=[]; window.__tripWatch=new MutationObserver(() => {
          const p=document.querySelector('[data-testid=trip-tv-preview-content]');
          if(p) window.__tripLeaks.push(p.textContent);
        });window.__tripWatch.observe(document.body,{subtree:true,childList:true,characterData:true});}""")
        replies = []
        def late(route):
            reply = route.fetch(max_redirects=0, timeout=TIMEOUT)
            try:
                assert reply.status == 200
                raw = reply.body(); actual = json.loads(raw)
                assert actual['journey']['id'] == fixture['journey']['id']
                self.login(page.context, 2)
                assert self.get(page.context, '/api/me')['user']['id'] == 'member2'
                route.fulfill(status=reply.status, headers=reply.headers, body=raw)
                replies.append(actual)
            finally: reply.dispose()
        page.route(self.base + path, late, times=1)
        try:
            with page.expect_response(lambda r:r.url == self.base + '/api/me' and r.status == 200
                and (r.json().get('user') or {}).get('id') == 'member2', timeout=TIMEOUT):
                page.get_by_test_id('trip-tv-preview').click()
            expect(page.get_by_test_id('trip-tv-preview-content')).to_have_count(0)
            expect(page.get_by_test_id('trip-tv-controls')).to_have_count(0)
            assert len(replies) == 1 and page.evaluate('window.__tripLeaks') == []
            assert page.evaluate("sessionStorage.getItem('family-dashboard:trip-tv-operation:v1')") is None
            assert self.get(page.context, OPERATIONS + request_id) == {'found': False}
            self.evidence('real-late-member-preview', dict(delivered=True, newMember='member2',
                oldJourney=replies[0]['journey']['id'], leaks=page.evaluate('window.__tripLeaks')))
        finally:
            page.unroute(self.base + path, late)
            page.evaluate('window.__tripWatch.disconnect()')

    @classmethod
    def run_scenarios(cls, root, bundle, report, out, browser, temp_root, tools, cases=CASES):
        with patch.dict(video_fixture.CASE_SCREENSHOTS, CASE_SCREENSHOTS):
            super().run_scenarios(root, bundle, report, out, browser, temp_root, tools, cases)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source-root', 'bundle', 'temp-root', 'ffmpeg', 'ffprobe'):
        parser.add_argument('--' + name, required=True, type=Path)
    for name in ('expected-head', 'expected-build-evidence', 'ffmpeg-sha256', 'ffprobe-sha256'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--build-source-head')
    parser.add_argument('--case', action='append', choices=CASES, dest='cases')
    args = parser.parse_args()
    if not sys.dont_write_bytecode or sys.flags.optimize: raise RuntimeError('Use -B; optimization is forbidden')
    root, bundle, temp_root = args.source_root.resolve(), args.bundle.absolute(), args.temp_root.resolve()
    if os.name == 'nt' and not str(bundle).startswith('\\\\?\\'): bundle = Path('\\\\?\\' + str(bundle))
    assert temp_root.is_dir() and not temp_root.is_symlink() and not temp_root.is_junction()
    def git(*command): return subprocess.check_output(['git', '--no-replace-objects', *command], cwd=root).decode('utf-8').strip()
    head, tree = git('rev-parse', 'HEAD'), git('rev-parse', 'HEAD^{tree}')
    assert head == args.expected_head and re.fullmatch('[a-f0-9]{40}', head) and not git('status', '--porcelain=v1')
    assert Path(__file__).resolve() == (root / HARNESS).resolve()
    build_head = args.build_source_head or head
    assert re.fullmatch('[a-f0-9]{40}', build_head)
    git('merge-base', '--is-ancestor', build_head, head)
    changed = git('diff', '--no-renames', '--name-only', build_head, head).splitlines()
    assert set(changed) <= {HARNESS, DOCUMENT}, 'Only this harness/document may differ from the build source'
    assert git('rev-parse', build_head + ':frontend') == git('rev-parse', head + ':frontend')
    evidence_path = bundle.parent / 'build-evidence.json'
    assert sha(evidence_path) == args.expected_build_evidence
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    names = git('ls-files', '-z').rstrip('\0').split('\0')
    build_fixture.validate_build(git, root, build_head, evidence, names)
    for name, digest in evidence.get('additionalTestInputs', {}).items(): assert name in names and sha(root / name) == digest
    assert build_fixture.exports(bundle) == evidence['files']
    def hashes(): return {name: sha(root / name) for name in names}
    tools = VideoTools(str(args.ffmpeg.resolve()), str(args.ffprobe.resolve()))
    identities = {name: tool_identity(getattr(args, name), getattr(args, name + '_sha256')) for name in ('ffmpeg', 'ffprobe')}
    cases = tuple(dict.fromkeys(args.cases or CASES))
    out = root / 'test-results' / ('tv-trip-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True, exist_ok=False); shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], screenshots=[], pageErrors=[], externalRequests=[], unexpectedProviderAttempts=[],
        httpEvidence=[], databaseEvidence=[], scenarioResults=[], scenarioFailures=[], requestedCases=list(cases),
        head=head, sourceHead=head, tree=tree, buildSourceHead=build_head, buildSourceTree=evidence['sourceTree'],
        buildReusePaths=changed, buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(Path(__file__)), tools=identities,
        sourceHashesBefore=hashes(), bundleHashesBefore=build_fixture.exports(bundle), productionWrites=0,
        realCloud=False, realModel=False, physicalTelevision=False,
        scope='Real temporary HTTPS/Flask/SQLite/Edge, paired TV cookies, synthetic Picker transport and actual FFmpeg short video. Native media observations; no DTO success substitution or clock acceleration. Not physical TV, Google, production or resource acceptance.')
    original_connect = socket.socket.connect
    def local_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
            report['externalRequests'].append({'kind':'non-loopback socket'}); raise AssertionError('External network forbidden')
        return original_connect(sock, address)
    try:
        with patch.object(socket.socket, 'connect', local_connect), sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            try:
                Run.run_scenarios(root, bundle, report, out, browser, temp_root, tools, cases)
                assert len(report['checks']) == len(cases) and len(report['screenshots']) == 3 * len(cases)
                assert [r['name'] for r in report['scenarioResults']] == list(cases)
                assert not any(report[k] for k in ('scenarioFailures', 'pageErrors', 'externalRequests', 'unexpectedProviderAttempts', 'unexpectedHttpServerErrors', 'httpCaptureErrors'))
                report['passed'] = True
            finally: browser.close()
    except Exception:
        report['failure'] = traceback.format_exc(); print(report['failure'], flush=True)
    finally:
        try:
            report['sourceHashesAfter'], report['bundleHashesAfter'] = hashes(), build_fixture.exports(bundle)
            report['sourceUnchanged'] = report['sourceHashesBefore'] == report['sourceHashesAfter']
            report['bundleUnchanged'] = report['bundleHashesBefore'] == report['bundleHashesAfter']
            for key in ('fixtureHashes', 'tripFixtureHashes'):
                report[key + 'After'] = {name:sha(root / name) for name in report.get(key, {})}
                assert report.get(key) and report[key + 'After'] == report[key]
            report['toolsUnchanged'] = all(sha(Path(v['path'])) == v['sha256'] for v in identities.values())
            report['sourceStillFrozen'] = git('rev-parse', 'HEAD') == head and not git('status', '--porcelain=v1')
            report['temporaryFixtureRemoved'] = len(report['scenarioResults']) == len(cases) and all(r.get('listenerStopped') and r['temporaryFixtureRemoved'] for r in report['scenarioResults'])
            report['passed'] = report['passed'] and all(report[k] for k in ('sourceUnchanged','bundleUnchanged','toolsUnchanged','sourceStillFrozen','temporaryFixtureRemoved'))
        except Exception:
            report['passed'] = False; report['finalEvidenceFailure'] = traceback.format_exc()
        build_fixture.write_json(out / 'result.json', report)
        print(json.dumps(dict(passed=report['passed'], checks=len(report['checks']), report=str(out / 'result.json'))), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
