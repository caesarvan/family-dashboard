"""Frozen Expo trip recap against independent real Flask/SQLite/Edge fixtures.

Only synthetic records and sanitized synthetic JPEGs. Provider job completions
are fixtures; all browser-facing business DTOs and image bytes come from the
real application. Fault routes only delay or discard real responses.
"""
import argparse
from contextlib import ExitStack, closing
from datetime import datetime, timezone
import importlib
from io import BytesIO
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
import time
import traceback
from unittest.mock import patch
from urllib.parse import urlsplit

from PIL import Image
from playwright.sync_api import expect, sync_playwright
import browser_expo_finance_check as fixture
from browser_expo_finance_check import Run as BaseRun, button, sha, visibility

CHECKS = 10
WIDTHS = (320, 390, 1280, 1920)
TITLE = '合成旅行回顾'
PRIVATE = '仅本人可见的合成照片'
LONG = '合成长名称地点：沿河步道与社区公共花园，旅行成员手动记录的位置与到访状态仍需分别核对，不代表照片的拍摄位置'


def heading(page, name):
    return page.get_by_role('heading', name=name, exact=True)


class Run(BaseRun):
    def start(self, port=0):
        self.cfg.update(GOOGLE_CLIENT_ID='synthetic-recap-client', GOOGLE_CLIENT_SECRET='synthetic-recap-secret')
        super().start(port)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        assert Path(self.source.__file__).resolve() == (self.root / 'app.py').resolve()
        self.media_fixture = importlib.import_module('test_household_media')
        self.images = importlib.import_module('media_images')
        self.engine = self.application.extensions['household_media']
        self.photo_serial = 0
        files = [(Path(__file__), 'tests/browser_expo_trip_recap_check.py'),
                 (Path(fixture.__file__), 'tests/browser_expo_finance_check.py'),
                 (Path(self.media_fixture.__file__), 'tests/test_household_media.py'),
                 (Path(self.images.__file__), 'media_images.py')]
        files += [(Path(sys.modules[name].__file__), 'tests/' + name + '.py')
                  for name in ('test_financial_files', 'test_app', 'test_journey_documents')]
        for actual, name in files:
            assert sha(actual) == sha(self.root / name), name
            prior = self.report.setdefault('fixtureHashes', {}).get(name)
            assert prior is None or prior == sha(actual)
            self.report['fixtureHashes'][name] = sha(actual)
        self.synthetic_accounts = {}
        with self.engine.accounts.db() as con:
            for member in (1, 2):
                account = secrets.token_hex(16); self.synthetic_accounts[member] = account
                token = self.engine.accounts.encrypt(dict(access_token='synthetic-only',
                    scope=importlib.import_module('cloud_accounts').GOOGLE_PHOTOS_SCOPE, expires_at=time.time() + 3600))
                con.execute('INSERT INTO cloud_accounts(id,owner,provider,client_id,subject,name,email,tokens) VALUES(?,?,?,?,?,?,?,?)',
                    (account, f'member{member}', 'google', 'synthetic-recap-client', f'synthetic-{member}', '虚构照片账户', 'synthetic.invalid', token))

    def clear_finance(self):
        pass  # Independent new DB per case; no reset of inherited finance tables.

    def snapshot(self):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        tables = ('entities', 'journey_workflows', 'journey_links', 'journey_actions', 'journey_places', 'media_items', 'media_tv_grants')
        with closing(sqlite3.connect(self.database)) as con:
            return {name: sorted(con.execute('SELECT * FROM ' + name).fetchall(), key=repr) for name in tables}

    def read_only(self, mark, before):
        assert self.snapshot() == before, 'Recap must not change a business record or TV grant'
        calls = self.requests[mark:]
        assert any(r['path'].startswith('/api/journey-places') for r in calls)
        assert all(r['method'] == 'GET' for r in calls if r['path'].startswith('/api/')), calls
        assert not any(r['path'].startswith(('/api/media/imports', '/api/accounts', '/api/media-tv', '/api/media-playback')) or '/tv-grants' in r['path'] for r in calls), calls

    def journey(self, ctx, count=1, v2=False):
        plan = dict(title=TITLE, start='2026-12-01', end='2026-12-04', budget=123456,
            memberIds=['member1', 'member2'], checklist=[], shopping=[],
            destinations=[dict(key='city', city='合成城市', country='合成地区', arrival='2026-12-01', departure='2026-12-04')],
            segments=[dict(key=f'day-{n}', title=f'原日程 {n:02}', start='2026-12-01', end='2026-12-02') for n in range(count)])
        if v2:
            plan.update(schemaVersion=2, referenceTimezone='Asia/Shanghai',
                destinations=[dict(key='tokyo', city='东京', country='日本', arrival='2026-12-01', departure='2026-12-04', timeZone='Asia/Tokyo')],
                segments=[dict(key='flight', kind='flight', title='合成航班',
                    departure=dict(local='2026-12-01T09:00', timeZone='Asia/Shanghai', airport='PVG', city='上海'),
                    arrival=dict(local='2026-12-01T13:00', timeZone='Asia/Tokyo', airport='NRT', city='东京')),
                    dict(key='stay', kind='stay', title='合成住宿', propertyName='合成旅馆', address='合成街道', timeZone='Asia/Tokyo',
                         checkInDate='2026-12-01', checkOutDate='2026-12-04', checkInTime='', checkOutTime=''),
                    dict(key='cancelled', kind='activity', title='人工取消活动', bookingState='cancelled',
                         dateRange=dict(startDate='2026-12-02', endDateExclusive='2026-12-03'), timeZone='Asia/Tokyo')])
        preview = self.write(ctx, 'POST', '/api/journeys/preview', {'plan': plan})
        receipt = self.write(ctx, 'POST', '/api/journeys/apply', {'previewToken': preview['previewToken'], 'idempotencyKey': secrets.token_hex(16)}, 201)
        return self.get(ctx, '/api/journeys/' + receipt['id'])

    def place(self, ctx, journey, name='合成地点', **changes):
        return self.write(ctx, 'POST', '/api/journey-places', dict(requestId=secrets.token_hex(16), name=name,
            journeyId=journey['id'], coordinates={'latitude': 31.234567, 'longitude': 121.456789}, **changes), 201)['place']

    def photos(self, ctx, journey, count=1, member=1, shared=False, caption=PRIVATE):
        saved = []
        while len(saved) < count:
            size = min(20, count - len(saved))
            imported = self.write(ctx, 'POST', '/api/media/imports', dict(requestId=secrets.token_hex(16),
                accountId=self.synthetic_accounts[member], consentVersion='media-v1', allowTemporaryProcessing=True), 202)['import']
            job = self.engine.claim_next(); assert job and job['action'] == 'create'
            assert self.engine.complete(job, self.media_fixture.session((None, None, [time.time()], None)))
            selected = [self.media_fixture.selected(secrets.token_hex(8)) for _ in range(size)]
            job = self.engine.claim_next(); assert job and job['action'] == 'list'; assert self.engine.complete(job, selected)
            while (job := self.engine.claim_next()) is not None:
                if job['action'] == 'cleanup':
                    assert self.engine.complete(job, None); break
                assert job['action'] == 'download'
                self.photo_serial += 1; n = self.photo_serial; stream = BytesIO()
                Image.new('RGB', (20, 12), (n * 7 % 256, n * 11 % 256, n * 13 % 256)).save(stream, 'PNG')
                jpeg = self.images.sanitize_media_preview(stream.getvalue(), 'image/png')
                assert self.engine.complete(job, dict(mediaId=job['media']['id'], manifest=selected, preview=jpeg))
            detail = self.get(ctx, '/api/media/imports/' + imported['id'])
            self.write(ctx, 'POST', '/api/media/imports/' + imported['id'] + '/confirm', dict(revision=detail['import']['revision'],
                confirmRequestId=secrets.token_hex(16), itemIds=[i['id'] for i in detail['items']], consentVersion='media-v1', persistSelected=True))
            for row in detail['items']:
                item = self.get(ctx, '/api/media/items/' + row['id'])['item']
                saved.append(self.write(ctx, 'PATCH', '/api/media/items/' + row['id'], dict(revision=item['revision'], journeyId=journey['id'],
                    visibility='shared' if shared else 'private', caption=caption + (' ' + str(len(saved) + 1) if count > 1 else '')))['item'])
        return saved

    @staticmethod
    def list_path(journey, kind='photos', offset=0):
        return '/api/' + ('media/items' if kind == 'photos' else 'journey-places') + '?scope=visible&journeyId=' + journey['id'] + '&limit=24&offset=' + str(offset)

    def create_family(self, ctx):
        invitation = self.write(ctx, 'POST', '/api/spaces/invitations', {}, 201)['invitation']
        return self.write(ctx, 'POST', '/api/spaces/redeem', dict(invitation=invitation, name='合成回顾另一家庭', slug='recap-other',
            MEMBER1_PASSWORD='testing-password-one', MEMBER2_PASSWORD='testing-password-two'), 201)

    def open_panel(self, page, journey, navigate=True):
        if navigate:
            page.goto(self.base + '/app/trips'); page.bring_to_front()
            card = heading(page, journey['trip']['title']).locator('xpath=ancestor::*[@data-testid="section-card-content"][1]')
            expect(button(card, '查看')).to_be_enabled(timeout=15000); button(card, '查看').click()
        expect(button(page, '旅行回顾')).to_be_enabled(timeout=15000); button(page, '旅行回顾').click()
        self.loaded(page)

    def loaded(self, page):
        expect(page.get_by_test_id('trip-recap-content')).to_be_visible(timeout=15000)
        expect(button(page, '刷新旅行回顾')).to_be_enabled(timeout=15000)
        expect(page.get_by_label('正在核对旅行回顾', exact=True)).to_have_count(0)

    def category(self, page, name):
        button(page, name).click(); self.loaded(page)

    def image_loaded(self, page):
        expect(page.get_by_test_id('recap-photo-image')).to_be_visible(timeout=15000)
        page.wait_for_function('''() => {const root=document.querySelector('[data-testid="recap-photo-image"]');
          const img=root?.matches('img')?root:root?.querySelector('img');return img?.complete&&img.naturalWidth>0&&img.src.startsWith('blob:');}''')
        return page.get_by_test_id('recap-photo-image').evaluate("n => (n.matches('img')?n:n.querySelector('img')).src")

    def open_photo(self, page, number=1):
        self.category(page, '旅行照片'); button(page, f'查看照片 {number}').click(); self.loaded(page)
        return self.image_loaded(page)

    def assert_cleared(self, page):
        expect(page.get_by_test_id('trip-recap-content')).to_have_count(0)
        expect(page.get_by_test_id('recap-photo-image')).to_have_count(0)
        expect(page.locator('body')).not_to_contain_text(PRIVATE)

    @staticmethod
    def assert_blob_revoked(page, url):
        assert page.evaluate('''async url => {try {await fetch(url); return false;} catch {return true;}}''', url), 'Old private blob remains readable'

    def entry_current_return(self, browser):
        with self.flow(browser) as (ctx, page):
            journey = self.journey(ctx, count=10)
            event = next(e for e in journey['events'] if e['workflowKey'] == 'segment:day-0')
            removed = next(e for e in journey['events'] if e['workflowKey'] == 'segment:day-1')
            self.write(ctx, 'PATCH', '/api/items/events/' + event['id'], dict(revision=event['revision'], title='当前独立修改的日程', location='当前合成地点', note='记' * 8000,
                start='2026-11-30T00:00:00+08:00', end='2026-12-01T00:00:00+08:00'))
            self.write(ctx, 'DELETE', '/api/items/events/' + removed['id'], {'revision': removed['revision']})
            before, mark = self.snapshot(), len(self.requests); self.open_panel(page, journey)
            expect(page.get_by_test_id('recap-events')).to_contain_text('当前独立修改的日程')
            expect(page.get_by_test_id('recap-events')).to_contain_text('记' * 8000)
            expect(page.locator('body')).not_to_contain_text(removed['title'])
            button(page, '下一页行程').click(); expect(page.get_by_test_id('recap-events')).to_contain_text('第 2 / 2 页')
            expect(button(page, '下一页行程')).to_be_disabled(); button(page, '上一页行程').click()
            self.read_only(mark, before)
            trip = self.get(ctx, '/api/journeys/' + journey['id'])['trip']
            self.write(ctx, 'PATCH', '/api/items/trips/' + trip['id'], dict(revision=trip['revision'], title='返回后读取的最新旅行'))
            button(page, '返回旅行详情').click(); expect(page.get_by_test_id('trip-recap-panel')).to_have_count(0)
            expect(heading(page, '返回后读取的最新旅行')).to_be_visible(timeout=15000)
            self.passed('Real details entry, current event edits including 8000-char note/deletion, eight-event pagination and fresh return to the same trip; recap emits GET only')

    def timing_empty_missing_trip(self, browser):
        with self.flow(browser) as (ctx, page):
            journey = self.journey(ctx, v2=True); self.open_panel(page, journey)
            events = page.get_by_test_id('recap-events')
            expect(events).to_contain_text('Asia/Shanghai'); expect(events).to_contain_text('Asia/Tokyo')
            expect(events).to_contain_text('3 晚'); expect(events).to_contain_text('时刻未提供'); expect(events).to_contain_text('人工标记已取消')
            self.category(page, '关联地点'); expect(page.get_by_text('这一页没有可见地点', exact=True)).to_be_visible()
            self.category(page, '旅行照片'); expect(page.get_by_text('这一页没有可见照片', exact=True)).to_be_visible()
            trip = self.get(ctx, '/api/journeys/' + journey['id'])['trip']
            self.write(ctx, 'DELETE', '/api/items/trips/' + trip['id'], {'revision': trip['revision']})
            assert self.get(ctx, '/api/journeys/' + journey['id'])['trip'] is None
            self.get(ctx, self.list_path(journey, 'places'), 404)
            button(page, '刷新旅行回顾').click(); expect(page.get_by_role('alert')).to_be_visible(timeout=15000); self.assert_cleared(page)
            expect(button(page, '返回旅行详情')).to_be_enabled()
            self.passed('Real v2 local times/unknown hotel clocks/manual cancellation and empty lists; deleted trip makes the real place endpoint 404 and clears recap instead of fabricating coverage')

    def pagination(self, browser):
        with self.flow(browser) as (ctx, page):
            journey = self.journey(ctx)
            for n in range(25): self.place(ctx, journey, f'分页地点 {n:02}')
            self.photos(ctx, journey, count=25); before, mark = self.snapshot(), len(self.requests)
            self.open_panel(page, journey); self.category(page, '关联地点')
            expect(page.get_by_test_id('recap-places').get_by_role('heading')).to_have_count(24)
            button(page, '下一页地点').click(); self.loaded(page)
            expect(page.get_by_test_id('recap-places').get_by_role('heading')).to_have_count(1)
            expect(button(page, '下一页地点')).to_be_disabled(); button(page, '上一页地点').click(); self.loaded(page)
            self.category(page, '旅行照片'); expect(page.get_by_test_id('recap-photos').get_by_role('button', name=re.compile('^查看照片 [0-9]+$'))).to_have_count(24)
            button(page, '下一页照片').click(); self.loaded(page); expect(button(page, '查看照片 25')).to_be_visible()
            button(page, '查看照片 25').click(); self.loaded(page); self.image_loaded(page)
            button(page, '关闭照片详情').click(); self.loaded(page); expect(page.get_by_test_id('recap-photo-image')).to_have_count(0)
            expect(button(page, '下一页照片')).to_be_disabled(); self.read_only(mark, before)
            self.passed('Two actual 24-row API pages for 25 places/photos, authorized JPEG on page two and explicit close without sharing or TV writes')

    def member_family_tv(self, browser):
        with self.flow(browser) as (ctx, page), ExitStack() as stack:
            journey = self.journey(ctx); self.photos(ctx, journey)
            partner = self.context(browser, member=2); stack.callback(partner.close)
            self.photos(partner, journey, member=2, shared=True, caption='伴侣明确共享照片')
            self.photos(partner, journey, member=2, caption='伴侣私密照片不可见')
            for policy in ('hidden', 'coarse', 'exact'):
                self.place(partner, journey, '伴侣位置 ' + policy, visibility='shared', coordinateDisclosure=policy, status='visited', confirmVisited=True)
            self.place(partner, journey, '伴侣私密地点不可见')
            self.open_panel(page, journey); self.category(page, '关联地点')
            expect(page.locator('body')).to_contain_text('记录者未共享坐标'); expect(page.locator('body')).to_contain_text('大致位置：31.2，121.5')
            expect(page.locator('body')).to_contain_text('已记录坐标：31.234567，121.456789')
            expect(page.locator('body')).not_to_contain_text('伴侣私密地点不可见')
            self.category(page, '旅行照片'); expect(heading(page, '伴侣明确共享照片')).to_be_visible()
            expect(page.locator('body')).not_to_contain_text('伴侣私密照片不可见')
            partner_page = partner.new_page(); self.open_panel(partner_page, journey); self.category(partner_page, '旅行照片')
            expect(partner_page.locator('body')).not_to_contain_text(PRIVATE)
            family = self.create_family(ctx); child = self.context(browser, member=None); stack.callback(child.close)
            assert child.request.get(self.base + family['entry']).status == 200; self.login(child)
            assert self.get(child, '/api/me')['user']['householdId'] != self.get(ctx, '/api/me')['user']['householdId']
            self.get(child, '/api/journeys/' + journey['id'], 404)
            self.get(child, self.list_path(journey, 'places'), 404)
            assert self.get(child, self.list_path(journey))['total'] == 0
            tv = self.context(browser, member=None); stack.callback(tv.close)
            pair = tv.request.post(self.base + '/api/pair/start', data={}); assert pair.status == 200
            self.write(ctx, 'POST', '/api/pair/approve', {'code': pair.json()['code'], 'name': '合成回顾电视'})
            assert tv.request.post(self.base + '/api/pair/poll', data={'secret': pair.json()['secret']}).json()['approved']
            self.get(tv, self.list_path(journey, 'places'), 403); self.get(tv, self.list_path(journey), 403)
            tv_page = tv.new_page(); calls = []; tv_page.on('request', lambda req: calls.append(urlsplit(req.url).path))
            tv_page.goto(self.base + '/app/tv'); expect(tv_page.get_by_test_id('expo-tv-board')).to_be_visible(timeout=15000)
            expect(tv_page.get_by_test_id('trip-recap-panel')).to_have_count(0)
            assert '/api/journey-places' not in calls and '/api/media/items' not in calls
            self.passed('Real partner private/shared projections and coordinate policies, signed second household 404 and paired TV 403 without recap reads')

    def revoked_image(self, browser):
        with self.flow(browser) as (ctx, page), ExitStack() as stack:
            journey = self.journey(ctx); partner = self.context(browser, member=2); stack.callback(partner.close)
            photo = self.photos(partner, journey, member=2, shared=True, caption='随后撤回的共享照片')[0]
            place = self.place(partner, journey, '随后撤回的共享地点', visibility='shared')
            self.open_panel(page, journey); old_url = self.open_photo(page)
            self.write(partner, 'PATCH', '/api/media/items/' + photo['id'], dict(revision=photo['revision'], visibility='private'))
            self.write(partner, 'PATCH', '/api/journey-places/' + place['id'], dict(revision=place['revision'], visibility='private'))
            assert ctx.request.get(self.base + '/api/media/items/' + photo['id'] + '/preview').status == 404
            button(page, '刷新旅行回顾').click(); expect(page.get_by_role('alert')).to_be_visible(timeout=15000); self.assert_cleared(page)
            self.assert_blob_revoked(page, old_url)
            expect(button(page, '重新读取旅行回顾')).to_be_enabled(); button(page, '重新读取旅行回顾').click(); self.loaded(page)
            expect(page.get_by_text('这一页没有可见照片', exact=True)).to_be_visible()
            self.category(page, '关联地点'); expect(page.get_by_text('这一页没有可见地点', exact=True)).to_be_visible()
            own = self.photos(ctx, journey)[0]; old_url = self.open_photo(page); removed = []
            def remove_before_image(route):
                self.write(ctx, 'DELETE', '/api/media/items/' + own['id'], {'revision': own['revision']})
                response = route.fetch(max_redirects=0); assert response.status == 410
                route.fulfill(response=response); removed.append(True)
            page.route(self.base + '/api/media/items/' + own['id'] + '/preview', remove_before_image, times=1)
            button(page, '刷新旅行回顾').click(); expect(page.get_by_role('alert')).to_be_visible(timeout=15000); self.assert_cleared(page)
            self.settle(page, lambda: len(removed) == 1); self.assert_blob_revoked(page, old_url)
            button(page, '重新读取旅行回顾').click(); self.loaded(page)
            expect(page.get_by_text('这一页没有可见照片', exact=True)).to_be_visible()
            self.passed('Real partner unsharing and own deletion remove authenticated JPEG, clear selected blob, then explicit same-page GET recovers empty gallery and place list')

    def late_identity(self, browser, household):
        with self.flow(browser) as (ctx, page):
            journey = self.journey(ctx); self.photos(ctx, journey); family = self.create_family(ctx) if household else None
            self.open_panel(page, journey); self.open_photo(page); sent = []
            def switch(route):
                response = route.fetch(max_redirects=0); assert response.status == 200
                assert response.json()['total'] == 1
                if household:
                    assert ctx.request.get(self.base + family['entry']).status == 200; self.login(ctx)
                else: self.login(ctx, 2)
                route.fulfill(response=response); sent.append(True)
            page.route(self.base + self.list_path(journey), switch, times=1)
            button(page, '刷新旅行回顾').click(); self.settle(page, lambda: len(sent) == 1)
            expect(page.get_by_test_id('trip-recap-panel')).to_have_count(0, timeout=15000)
            expect(page.locator('body')).not_to_contain_text(PRIVATE)
            expect(page.get_by_test_id('recap-photo-image')).to_have_count(0)
            if household: self.get(ctx, '/api/journeys/' + journey['id'], 404)
            else: assert self.get(ctx, self.list_path(journey))['total'] == 0
            self.passed('Late genuine photo list after real ' + ('signed-household' if household else 'member') + ' cookie change is discarded through post-/me actor remount, never restoring private content')

    def privacy_lifecycle(self, browser):
        with self.flow(browser) as (ctx, page):
            journey = self.journey(ctx); self.photos(ctx, journey); before, mark = self.snapshot(), len(self.requests)
            self.open_panel(page, journey); old_url = self.open_photo(page)
            ctx.set_offline(True); self.assert_cleared(page); ctx.set_offline(False); self.loaded(page); self.image_loaded(page)
            self.assert_blob_revoked(page, old_url)
            visibility(page, True); self.assert_cleared(page); held = []
            def hold(route):
                response = route.fetch(max_redirects=0); assert response.status == 200; held.append((route, response))
            path = self.base + self.list_path(journey)
            page.route(path, hold, times=1); visibility(page, False); self.settle(page, lambda: len(held) == 1)
            visibility(page, True); held[0][0].fulfill(response=held[0][1]); page.wait_for_timeout(300); self.assert_cleared(page)
            visibility(page, False); self.loaded(page); self.image_loaded(page)
            page.evaluate("() => window.dispatchEvent(new Event('blur'))"); self.assert_cleared(page)
            reads = self.count_requests('GET', '/api/journeys/' + journey['id'])
            visibility(page, False); page.evaluate("() => window.dispatchEvent(new Event('online'))")
            page.wait_for_timeout(300); self.assert_cleared(page)
            assert self.count_requests('GET', '/api/journeys/' + journey['id']) == reads
            page.evaluate("() => window.dispatchEvent(new Event('focus'))"); self.loaded(page); self.image_loaded(page)
            assert self.count_requests('GET', '/api/journeys/' + journey['id']) > reads
            # Do not accelerate performance.now: wait for the actual 15-second recheck/lease.
            expired = []
            def hold_expiry(route):
                response = route.fetch(max_redirects=0); assert response.status == 200; expired.append((route, response))
            old_url = self.image_loaded(page)
            page.route(self.base + '/api/journeys/' + journey['id'], hold_expiry, times=1)
            self.settle(page, lambda: len(expired) == 1, timeout=18000); self.assert_cleared(page); self.assert_blob_revoked(page, old_url)
            expired[0][0].fulfill(response=expired[0][1]); self.loaded(page); self.image_loaded(page)
            button(page, '返回旅行详情').click(); expect(page.get_by_test_id('trip-recap-panel')).to_have_count(0)
            page.evaluate("() => window.dispatchEvent(new Event('focus'))"); expect(page.get_by_test_id('recap-photo-image')).to_have_count(0)
            self.read_only(mark, before)
            self.passed('Real browser offline plus simulated visibility/window blur hide image and content; late actual response/online cannot reopen blurred view; focus rechecks and return stays closed')

    def failed_read_return(self, browser):
        with self.flow(browser) as (ctx, page):
            journey = self.journey(ctx); self.photos(ctx, journey); self.open_panel(page, journey); self.open_photo(page)
            before, mark, dropped = self.snapshot(), len(self.requests), []
            def lose(route):
                response = route.fetch(max_redirects=0); assert response.status == 200; route.abort('failed'); dropped.append(True)
            path = self.base + '/api/journeys/' + journey['id']
            page.route(path, lose, times=1); button(page, '刷新旅行回顾').click(); self.settle(page, lambda: len(dropped) == 1)
            expect(page.get_by_role('alert')).to_be_visible(timeout=15000); self.assert_cleared(page)
            button(page, '重新读取旅行回顾').click(); self.loaded(page); self.image_loaded(page)
            held = []
            def hold(route):
                response = route.fetch(max_redirects=0); assert response.status == 200; held.append((route, response))
            page.route(path, hold, times=1); button(page, '刷新旅行回顾').click(); self.settle(page, lambda: len(held) == 1)
            button(page, '返回旅行详情').click(); expect(page.get_by_test_id('trip-recap-panel')).to_have_count(0)
            held[0][0].fulfill(response=held[0][1]); expect(button(page, '旅行回顾')).to_be_enabled(timeout=15000)
            expect(page.locator('body')).not_to_contain_text(PRIVATE); expect(page.get_by_test_id('recap-photo-image')).to_have_count(0)
            self.open_panel(page, journey, navigate=False); self.read_only(mark, before)
            self.passed('Dropped real GET clears old content and supports explicit retry; return during a held GET cancels recap and delayed bytes cannot reopen it')

    def capture(self, page, name, width, target):
        page.set_viewport_size(dict(width=width, height=1080 if width >= 1280 else 844))
        page.evaluate('() => document.fonts.ready'); target.scroll_into_view_if_needed(); page.wait_for_timeout(800)
        page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
        self.loaded(page)
        metrics = page.evaluate('''() => ({width:innerWidth,scroll:document.documentElement.scrollWidth,
          clipped:[...document.querySelectorAll('[data-testid="trip-recap-panel"] [role="button"]')]
          .filter(n=>{const r=n.getBoundingClientRect();return r.width>0&&r.height>0&&r.bottom>0&&r.top<innerHeight&&(r.right>innerWidth+2||r.left< -2)})
          .map(n=>({label:n.getAttribute('aria-label')||n.textContent,box:n.getBoundingClientRect().toJSON()}))})''')
        assert metrics['scroll'] <= width + 2 and not metrics['clipped'], metrics
        for name_control in ('返回旅行详情', '行程安排', '关联地点', '旅行照片', '刷新旅行回顾'):
            box = button(page, name_control).bounding_box(); assert box and box['height'] >= 44 and box['width'] >= 44, (name_control, box)
        path = self.out / f'{name}-{width}.png'; page.screenshot(path=str(path), full_page=False)
        self.report['screenshots'].append(dict(path=path.relative_to(self.out.parent).as_posix(), sha256=sha(path), width=width,
            metrics=metrics, scope='Settled visible viewport after explicit scroll; not all inner ScrollView content.'))

    def widths_and_themes(self, browser):
        with self.flow(browser) as (ctx, page):
            journey = self.journey(ctx, v2=True); self.place(ctx, journey, LONG, status='planned'); self.photos(ctx, journey)
            self.open_panel(page, journey)
            for width in WIDTHS: self.capture(page, 'recap-itinerary-light', width, heading(page, '当前关联日程'))
            self.category(page, '关联地点')
            for width in WIDTHS:
                self.capture(page, 'recap-places-light', width, heading(page, LONG))
                if width <= 390:
                    box = heading(page, LONG).bounding_box(); assert box and box['height'] > 40
            pref = self.get(ctx, '/api/preferences')
            self.write(ctx, 'PUT', '/api/preferences', dict(revision=pref['revision'], changes=dict(colorMode='dark', density='compact')))
            self.open_panel(page, journey); self.open_photo(page)
            page.wait_for_function("getComputedStyle(document.documentElement).colorScheme === 'dark'")
            for width in WIDTHS:
                self.image_loaded(page); self.capture(page, 'recap-photo-dark', width, heading(page, '照片详情'))
            button(page, '关闭照片详情').focus(); expect(button(page, '关闭照片详情')).to_be_focused()
            page.keyboard.press('Enter'); self.loaded(page); expect(page.get_by_test_id('recap-photo-detail')).to_have_count(0)
            page.keyboard.press('Tab'); focused = page.evaluate("() => ({role:document.activeElement?.getAttribute('role'),label:document.activeElement?.getAttribute('aria-label')})")
            assert focused['role'] == 'button', focused
            self.report['keyboard'] = dict(closeByEnter=True, nextFocus=focused)
            self.passed('Twelve settled visible viewports across four widths: light itinerary/long places and dark compact real JPEG; 44px recap actions and keyboard close/focus')

    @classmethod
    def run_scenarios(cls, root, bundle, report, out, browser):
        cases = [('entry_current_return', ()), ('timing_empty_missing_trip', ()), ('pagination', ()), ('member_family_tv', ()),
                 ('revoked_image', ()), ('late_member', (False,)), ('late_household', (True,)), ('privacy_lifecycle', ()), ('failed_read_return', ()), ('widths_and_themes', ())]
        for name, args in cases:
            case_out = out / name; case_out.mkdir(); folder = None
            before = (len(report['checks']), len(report['pageErrors']), len(report['externalRequests']))
            result = dict(name=name, passed=False, temporaryFixtureRemoved=False)
            try:
                with ExitStack() as lifecycle:
                    folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='expo-trip-recap-')))
                    run = cls(root, bundle, folder, report, case_out, lifecycle)
                    getattr(run, 'late_identity' if name.startswith('late_') else name)(browser, *args)
                assert not folder.exists() and len(report['checks']) == before[0] + 1
                assert len(report['pageErrors']) == before[1] and len(report['externalRequests']) == before[2]
                result['passed'] = True
            except Exception:
                del report['checks'][before[0]:]
                failure = traceback.format_exc(); (case_out / 'failure.txt').write_text(failure, encoding='utf-8')
                report['scenarioFailures'].append(dict(scenario=name, traceback=failure, artifacts=name)); print('FAIL ' + name + '\n' + failure, flush=True)
            finally:
                result['temporaryFixtureRemoved'] = folder is not None and not folder.exists(); report['scenarioResults'].append(result)
        assert not report['scenarioFailures'], 'See all independent case failures; a failed group never counts as passed'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path); parser.add_argument('--expected-head', required=True)
    parser.add_argument('--bundle', required=True, type=Path); parser.add_argument('--expected-build-evidence', required=True)
    args = parser.parse_args(); root, bundle = args.source_root.resolve(), args.bundle.resolve()
    assert re.fullmatch('[a-f0-9]{40}', args.expected_head) and re.fullmatch('[a-f0-9]{64}', args.expected_build_evidence)
    def git(*command): return subprocess.check_output(['git', '--no-replace-objects', *command], cwd=root, text=True).strip()
    head = git('rev-parse', 'HEAD'); assert head == args.expected_head and not git('status', '--porcelain=v1')
    evidence_path = bundle.parent / 'build-evidence.json'; assert sha(evidence_path) == args.expected_build_evidence
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    assert evidence['sourceHead'] == head and evidence['sourceTree'] == git('rev-parse', 'HEAD^{tree}')
    names = subprocess.check_output(['git', '--no-replace-objects', 'ls-files', '-z'], cwd=root).decode('utf-8').rstrip('\0').split('\0')
    def hashes(): return {name: sha(root / name) for name in names}
    def exports(): return {p.relative_to(bundle).as_posix(): sha(p) for p in bundle.rglob('*') if p.is_file()}
    assert exports() == evidence['files'] and all(sha(root / name) == digest for name, digest in evidence['inputFiles'].items())
    assert sha(Path(__file__)) == sha(root / 'tests/browser_expo_trip_recap_check.py')
    out = Path(__file__).resolve().parents[1] / 'test-results' / ('expo-trip-recap-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True); shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], screenshots=[], scenarioResults=[], scenarioFailures=[], head=head,
        tree=evidence['sourceTree'], buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(out / 'executed-harness.py'),
        sourceHashesBefore=hashes(), bundleHashesBefore=exports(), productionWrites=0, realCloud=False, physicalTelevision=False,
        scope='Ten independent real local Flask/SQLite/Edge scenarios, synthetic media-provider job completions and sanitized images only. Browser DTOs are never mocked. Offline is real network state; visibility/window focus events are simulated. Screenshots require separate visual review; no actual travel or route inference.')
    original_connect = socket.socket.connect
    def local_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
            report['externalRequests'].append({'kind': 'non-loopback socket'}); raise AssertionError('External network forbidden')
        return original_connect(sock, address)
    try:
        with patch.object(socket.socket, 'connect', local_connect), sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            try:
                Run.run_scenarios(root, bundle, report, out, browser)
                assert len(report['checks']) == CHECKS and len(report['screenshots']) == 12
                assert not report['pageErrors'] and not report['externalRequests']; report['passed'] = True
            finally: browser.close()
    except Exception:
        report['passed'] = False; report['failure'] = traceback.format_exc(); print(report['failure'], flush=True)
    finally:
        report['sourceHashesAfter'] = hashes(); report['bundleHashesAfter'] = exports()
        report['sourceUnchanged'] = report['sourceHashesBefore'] == report['sourceHashesAfter']
        report['bundleUnchanged'] = report['bundleHashesBefore'] == report['bundleHashesAfter']
        report['sourceStillFrozen'] = git('rev-parse', 'HEAD') == head and not git('status', '--porcelain=v1')
        report['temporaryFixtureRemoved'] = len(report['scenarioResults']) == CHECKS and all(case['temporaryFixtureRemoved'] for case in report['scenarioResults'])
        report['passed'] = report['passed'] and all(report[k] for k in ('sourceUnchanged', 'bundleUnchanged', 'sourceStillFrozen', 'temporaryFixtureRemoved'))
        (out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(dict(passed=report['passed'], checks=len(report['checks']), report=str(out / 'result.json')), ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    raise SystemExit(main())
