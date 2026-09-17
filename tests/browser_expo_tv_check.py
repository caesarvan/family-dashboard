"""Expo television route against frozen source/export and real loopback APIs.

Synthetic households, imported-calendar fixture rows and sanitized JPEGs only.
No HTML injection or successful business-response substitution. Clock advances
exercise display timers, not provider sync; visibility events are explicitly
simulated and do not claim physical television background/freeze behavior.
"""
import argparse
from contextlib import ExitStack, closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
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
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright
import browser_expo_devices_check as devices_fixture
from browser_expo_devices_check import Run as DeviceRun, CARDS, DEVICES, PLAYBACK, textbox
from browser_expo_finance_check import button, sha, visibility


TV_HEADERS = {'X-Display-Mode': 'tv'}
BOARD = 'expo-tv-board'
PHOTO = 'tv-photo-image'
SHANGHAI = timezone(timedelta(hours=8))


class Run(DeviceRun):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for module, name in ((devices_fixture, 'tests/browser_expo_devices_check.py'),):
            assert sha(Path(module.__file__)) == sha(self.root / name)
            self.report['fixtureHashes'][name] = sha(Path(module.__file__))
        assert sha(Path(__file__)) == sha(self.root / 'tests/browser_expo_tv_check.py')
        self.engine.clock = time.time
        self.application.extensions['media_playback'].clock = time.time
        self.today = datetime.now(SHANGHAI).date()
        self.televisions, self.tv_requests = [], []

    def tv_get(self, ctx, path, status=200):
        response = ctx.request.get(self.base + path, headers=TV_HEADERS)
        assert response.status == status, (path, response.status)
        return response.json()

    def screen(self, ctx):
        page = ctx.new_page()
        page.set_default_timeout(15000)
        page.set_viewport_size({'width': 1920, 'height': 1080})
        # Only method/path/display mode are recorded, never cookies/pair secrets.
        page.on('request', lambda req: self.tv_requests.append({
            'method': req.method, 'path': urlsplit(req.url).path,
            'displayMode': req.headers.get('x-display-mode')}))
        self.televisions.append(page)
        return page

    def shot(self, page, name, width, height):
        page.set_viewport_size({'width': width, 'height': height})
        page.evaluate('() => document.fonts.ready')
        page.wait_for_timeout(450)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2')
        if page.get_by_test_id(BOARD).count():
            assert page.get_by_test_id(BOARD).evaluate('''n => {
                const r = n.getBoundingClientRect();
                return r.x >= -1 && r.y >= -1 && r.right <= innerWidth + 1 && r.bottom <= innerHeight + 1;
            }'''), 'Television board must fit the actual viewport'
        path = self.out / f'{name}-{width}.png'
        page.screenshot(path=str(path), full_page=False)
        self.report['screenshots'].append({'path': path.name, 'sha256': sha(path),
                                            'width': width, 'height': height})

    def board(self, page):
        expect(page.get_by_test_id(BOARD)).to_be_visible(timeout=20000)
        assert urlsplit(page.url).path == '/app/tv'
        assert page.locator('script[src="/static/app.js"]').count() == 0
        assert page.get_by_role('tab', name='首页', exact=True).count() == 0

    def no_photo(self, page, timeout=2500):
        expect(page.get_by_test_id(PHOTO)).to_be_hidden(timeout=timeout)
        assert page.get_by_test_id(PHOTO).evaluate_all(
            '(nodes)=>nodes.every(n=>!n.getAttribute("src"))')

    def create_pair_from_screen(self, browser, phone, name, focus, view, *, signed_entry=None, member_cookie=False):
        ctx = self.context(browser, member=1 if member_cookie else None)
        self.lifecycle.callback(ctx.close)
        if signed_entry:
            assert ctx.request.get(self.base + signed_entry).status == 200
            route_cookie = next(c for c in ctx.cookies() if c['name'] == 'household_space')
            assert route_cookie['httpOnly'] and route_cookie['secure']
        page = self.screen(ctx)
        captured = []
        def pair_response(response):
            if urlsplit(response.url).path == '/api/pair/start' and response.status == 200:
                captured.append(response.json())
        page.on('response', pair_response)
        request_start = len(self.tv_requests)
        page.goto(self.base + '/tv')
        expect(page.get_by_role('heading', name='连接这块电视', exact=True)).to_be_visible()
        expect(page.get_by_test_id('tv-pair-code')).to_contain_text(re.compile(r'[A-Z2-9]'), timeout=15000)
        self.settle(page, lambda: len(captured) == 1)
        pair = captured[0]
        assert re.fullmatch(r'[2-9A-HJ-NP-Z]{8}', pair['code'])
        displayed = re.sub(r'\s', '', page.get_by_test_id('tv-pair-code').inner_text())
        assert pair['code'] in displayed
        page.wait_for_timeout(300)
        assert len(captured) == 1, 'First entry must not duplicate pair/start under StrictMode'
        if member_cookie:
            self.shot(page, 'pairing', 640, 480)
            self.shot(page, 'pairing', 320, 568)
            expect(page.get_by_test_id(BOARD)).to_have_count(0)
            requested = self.tv_requests[request_start:]
            assert not [r for r in requested if r['path'] in ('/api/state', '/api/preferences', '/api/dashboard-layout', '/api/accounts')]
            assert all(r['displayMode'] == 'tv' for r in requested if r['path'].startswith('/api/'))
        self.open_list(phone)
        before_ids = {row['id'] for row in self.get(phone.context, DEVICES)}
        button(phone, '连接电视').click()
        textbox(phone, '电视配对码').fill(pair['code'])
        textbox(phone, '电视名称').fill(name)
        people = {p['id']: p['name'] for p in self.get(phone.context, '/api/state')['people']}
        phone.get_by_role('radio', name='侧重成员：' + people.get(focus, '共同'), exact=True).click()
        phone.get_by_role('radio', name='日程范围：' + {'today': '今天', 'week': '本周', 'around': '前后3天'}[view], exact=True).click()
        with phone.expect_response(lambda r: urlsplit(r.url).path == '/api/pair/approve' and r.request.method == 'POST') as approved:
            button(phone, '确认连接电视').click()
        assert approved.value.status == 200
        expect(button(phone, '显示设置：' + name)).to_be_visible()
        page.set_viewport_size({'width': 1920, 'height': 1080})
        self.board(page)
        cookie = next(c for c in ctx.cookies() if c['name'] == 'household_tv')
        assert cookie['httpOnly'] and cookie['secure'] and cookie['sameSite'] == 'Strict'
        assert self.tv_get(ctx, '/api/me')['user']['role'] == 'tv'
        uid = next(row['id'] for row in self.get(phone.context, DEVICES) if row['id'] not in before_ids)
        assert self.tv_get(ctx, '/api/me')['user']['id'] == uid
        page.remove_listener('response', pair_response)
        return ctx, page, uid

    def seed_shared(self, ctx):
        self.write(ctx, 'POST', '/api/profile', {'name': '合成甲'})
        self.write(ctx, 'PUT', '/api/private-finance', {'revision': 0, 'month': self.today.strftime('%Y-%m'),
            'income': 987654321, 'spent': 876543210, 'budget': 765432109})
        self.events = []
        for offset in range(-4, 5):
            day = (self.today + timedelta(days=offset)).isoformat()
            payload = {'title': f'合成跨日安排 {offset:+d}', 'owner': ['member1', 'member2', 'shared'][offset % 3],
                'start': day + 'T12:00:00+08:00', 'end': day + 'T13:00:00+08:00', 'location': '合成会议地点'}
            uid = self.write(ctx, 'POST', '/api/items/events', payload, 201)['id']
            self.events.append({**payload, 'id': uid, 'day': day})
        for owner in ('member1', 'member2', 'shared'):
            payload = {'title': '合成同日' + owner, 'owner': owner, 'allDay': True,
                'start': self.today.isoformat() + 'T00:00:00+08:00',
                'end': (self.today + timedelta(days=1)).isoformat() + 'T00:00:00+08:00'}
            uid = self.write(ctx, 'POST', '/api/items/events', payload, 201)['id']
            self.events.append({**payload, 'id': uid, 'day': self.today.isoformat()})
        for n in range(6):
            self.write(ctx, 'POST', '/api/items/tasks', {'title': f'合成准备事项 {n+1}',
                'owner': ['member1', 'member2', 'shared'][n % 3], 'due': self.today.isoformat()}, 201)
        self.write(ctx, 'POST', '/api/items/shopping', {'title': '添置合成咖啡豆', 'owner': 'shared', 'quantity': '2 包', 'budget': 0}, 201)
        self.write(ctx, 'POST', '/api/items/trips', {'title': '合成周末京都旅行', 'destination': '京都',
            'start': (self.today + timedelta(days=2)).isoformat(), 'end': (self.today + timedelta(days=5)).isoformat()}, 201)

    def configure(self, phone, uid, *, view=None, theme=None, density=None, hide_finance=False, tasks_first=False):
        self.open_settings(phone, uid)
        if view:
            phone.get_by_role('radio', name='日程范围：' + {'today': '今天', 'week': '本周', 'around': '前后3天'}[view], exact=True).click()
        if theme:
            phone.get_by_role('radio', name='电视主题：' + {'light': '晴日', 'forest': '森林', 'ocean': '海岸'}[theme], exact=True).click()
        if density:
            phone.get_by_role('radio', name='显示密度：' + {'compact': '紧凑', 'comfortable': '舒适'}[density], exact=True).click()
        if hide_finance:
            checkbox = phone.get_by_role('checkbox', name='显示卡片：家庭财务', exact=True)
            expect(checkbox).to_be_checked(); checkbox.focus(); checkbox.press('Space')
            expect(checkbox).not_to_be_checked()
        if tasks_first:
            button(phone, '上移：共同待办').click(); button(phone, '上移：共同待办').click()
        assert self.save_settings(phone, uid).status == 200

    def layouts_and_finance(self, phone, first, second, screen1, screen2):
        before_second = self.device(phone.context, second)
        member_layout = self.get(phone.context, '/api/dashboard-layout')
        expect(screen1.get_by_test_id('tv-card-finance')).to_contain_text('共同资金待核对')
        self.configure(phone, first, theme='light', density='compact', hide_finance=True, tasks_first=True)
        # No television reload: observe actual polling installing the phone change.
        expect(screen1.get_by_test_id('tv-card-finance')).to_have_count(0, timeout=16000)
        # Paper Card also emits <testID>-container/-outer-layer wrappers.
        # Compare the five real card contents, not their implementation layers.
        actual_order = screen1.get_by_test_id(re.compile(r'^tv-card-(calendar|finance|tasks|shopping|trips)$')).evaluate_all(
            '(nodes)=>nodes.map(n=>n.dataset.testid)')
        assert actual_order == ['tv-card-tasks', 'tv-card-calendar', 'tv-card-shopping', 'tv-card-trips'], actual_order
        assert screen1.get_by_test_id(BOARD).evaluate('(n)=>getComputedStyle(n).backgroundColor') == 'rgb(255, 255, 255)'
        assert self.device(phone.context, second) == before_second
        assert self.get(phone.context, '/api/dashboard-layout') == member_layout
        self.shot(screen1, 'board-light-compact', 1920, 1080)
        self.shot(screen1, 'board-light-compact', 3840, 2160)
        screen1.reload(); self.board(screen1)
        expect(screen1.get_by_test_id('tv-card-finance')).to_have_count(0)
        self.configure(phone, second, theme='ocean', density='comfortable')
        self.settle(screen2, lambda: screen2.get_by_test_id(BOARD).evaluate('(n)=>getComputedStyle(n).backgroundColor') == 'rgb(14, 32, 48)', timeout=16000)
        self.shot(screen2, 'board-ocean-comfortable', 1920, 1080)
        self.passed('Phone saves real independent two-TV layout/order/hidden/theme/density; television polling and reload retain settings without changing member layout')
        finance = self.get(phone.context, '/api/state')['finance']
        self.write(phone.context, 'PUT', '/api/finance', {**finance, 'wallet': 0, 'livingSpent': 12345,
            'livingBudget': 620000, 'reserveTarget': 1000000, 'travelSaved': 240000, 'longterm': 880000})
        expect(screen2.get_by_test_id('tv-card-finance')).to_contain_text('¥0.00', timeout=16000)
        expect(screen2.get_by_test_id('tv-card-finance')).to_contain_text('¥123.45')
        raw = self.tv_get(screen2.context, '/api/state')
        assert not any(str(value) in json.dumps(raw) for value in (987654321, 876543210, 765432109))
        for path in ('/api/private-finance', '/api/finance-hub/transactions', '/api/finance-hub/investments', '/api/accounts', '/api/sessions'):
            self.tv_get(screen2.context, path, 403)
        assert not any(str(value) in screen2.locator('body').inner_text() for value in ('9,876,543.21', '8,765,432.10'))
        self.passed('Unconfirmed shared-money empty state becomes confirmed exact zero and cents; TV state and private endpoints exclude synthetic personal finance')

    def collect_calendar(self, page, expected_ids):
        observed = set()
        for _ in range(18):
            values = page.locator('[data-testid^="tv-event-"]').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.testid.slice(9))')
            observed.update(values)
            assert observed <= expected_ids, 'TV rendered event outside selected date range'
            if observed == expected_ids:
                return
            self.advance_display_time(page, 21000)
        assert observed == expected_ids, 'Automatic pages omitted real events'

    @staticmethod
    def advance_display_time(page, milliseconds):
        # Move Date only. Real 1-second ticks paint the next reading position;
        # monotonic fetch/decode/lease deadlines remain unaccelerated, so a
        # virtual timer jump cannot manufacture a network timeout.
        next_time = datetime.fromtimestamp((page.evaluate('Date.now()') + milliseconds) / 1000, timezone.utc)
        page.clock.set_system_time(next_time)
        page.wait_for_timeout(1150)

    def dates_and_long_reading(self, phone, uid, screen):
        screen.set_viewport_size({'width': 1920, 'height': 1080})
        screen.clock.install(time=datetime.now(timezone.utc))
        for mode in ('today', 'week', 'around'):
            self.configure(phone, uid, view=mode, theme='forest')
            screen.reload(); self.board(screen)
            lower = self.today if mode == 'today' else self.today - timedelta(days=self.today.weekday() if mode == 'week' else 3)
            days = {(lower + timedelta(days=n)).isoformat() for n in range(1 if mode == 'today' else 7)}
            expected = {event['id'] for event in self.events if event['day'] in days}
            self.collect_calendar(screen, expected)
            assert {'member1', 'member2', 'shared'} <= {event['owner'] for event in self.events if event['id'] in expected}
            if mode != 'today':
                assert screen.get_by_test_id('tv-week-overview').get_by_role('progressbar').count() == 7
        self.shot(screen, 'board-forest-around', 3840, 2160)
        self.passed('Today/week/around automatic pages include every in-range event and all owners; per-day overview retains seven days, focus is not a visibility filter')
        # Acquisition fixture only: imported title/location bounds exceed the
        # local editor's shorter limit. The server still returns its real state.
        title = '合成远端长标题完整保留' * 90 + '标题末尾标记'
        location = '合成长地点逐字核对' * 120 + '地点末尾标记'
        uid_long = 'cloud-' + uuid4().hex
        payload = {'title': title, 'location': location, 'owner': 'shared', 'allDay': True,
            'start': self.today.isoformat() + 'T00:00:00+08:00',
            'end': (self.today + timedelta(days=1)).isoformat() + 'T00:00:00+08:00',
            'sync': {'provider': 'microsoft', 'readOnly': True, 'sourceId': 'synthetic-no-provider'}}
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database)) as con:
            con.execute('INSERT INTO entities(id,kind,data,updated_at) VALUES(?,?,?,?)',
                (uid_long, 'events', json.dumps(payload), datetime.now(timezone.utc).isoformat()))
            con.commit()
        self.configure(phone, uid, view='today')
        screen.set_viewport_size({'width': 1920, 'height': 1080})
        screen.reload(); self.board(screen)
        event = screen.get_by_test_id('tv-event-' + uid_long)
        for _ in range(18):
            if event.count(): break
            self.advance_display_time(screen, 21000)
        expect(event).to_contain_text(title)
        expect(event).to_contain_text(location)
        pane = screen.get_by_label(self.today.isoformat() + ' 日程详情', exact=True)
        initial = pane.evaluate('(n)=>({y:n.scrollTop,max:n.scrollHeight-n.clientHeight})')
        assert initial['max'] > 10, 'Long-text fixture must genuinely overflow the reading viewport'
        bottom_seen = False
        for _ in range(90):
            self.advance_display_time(screen, 5000)
            if not event.count(): break
            position = pane.evaluate('(n)=>({y:n.scrollTop,max:n.scrollHeight-n.clientHeight})')
            if position['y'] >= position['max'] - 2:
                bottom_seen = True; break
        assert bottom_seen, 'Long item advanced before the final text was reachable without touch'
        self.shot(screen, 'long-reading-last-position', 1920, 1080)
        self.passed('Full imported long title/location remain in real TV DOM and automatic read positions reach the last content before advancing; no touch required')

    def photo_controls(self, phone, first, second, screen1, screen2):
        self.seed_photos(phone.context, first)
        # Start at real current wall time; imported fixture acquired no cloud data.
        self.open_playback(phone, first)
        other = self.playback(phone.context, second)
        layout = self.device(phone.context, first)
        self.command(phone, first, '开始照片播放', 'start', mode='photos', paused=False)
        image = screen1.get_by_test_id(PHOTO)
        expect(image).to_be_visible(timeout=12000)
        assert image.evaluate('(n)=>n.naturalWidth===20 && n.naturalHeight===12 && n.src.startsWith("blob:")')
        self.no_photo(screen2)
        self.command(phone, first, '暂停播放', 'pause', paused=True)
        expect(screen1.get_by_test_id('tv-photo-position')).to_contain_text('暂停', timeout=7000)
        old_src = image.get_attribute('src')
        position = self.playback(phone.context, first)['position']
        self.command(phone, first, '下一张照片', 'next', position=(position + 1) % 3)
        self.settle(screen1, lambda: image.count() and image.get_attribute('src') not in (None, old_src), timeout=7000)
        self.command(phone, first, '上一张照片', 'previous', position=position)
        textbox(phone, '轮播间隔（秒）').fill('5')
        self.command(phone, first, '保存轮播间隔', 'interval', intervalSeconds=5, paused=True)
        self.command(phone, first, '继续播放', 'resume', paused=False)
        initial = self.playback(phone.context, first)['position']
        self.settle(screen1, lambda: self.playback(phone.context, first)['position'] != initial, timeout=6500)
        self.command(phone, first, '暂停播放', 'pause', paused=True)
        expect(image).to_be_visible()
        self.shot(screen1, 'authorized-photo', 1920, 1080)
        self.shot(screen1, 'authorized-photo', 3840, 2160)
        assert self.playback(phone.context, second) == other and self.device(phone.context, first) == layout
        self.passed('Actual sanitized/encrypted JPEG displays only on its granted TV; phone pause/next/previous/interval/resume persist, second TV and layout stay unchanged')

    def photo_lifecycle(self, screen):
        image = screen.get_by_test_id(PHOTO)
        screen.context.set_offline(True)
        self.no_photo(screen)
        expect(screen.get_by_test_id(BOARD)).to_be_hidden()
        screen.context.set_offline(False)
        expect(image).to_be_visible(timeout=15000)
        visibility(screen, True)
        self.no_photo(screen)
        expect(screen.get_by_test_id(BOARD)).to_be_hidden()
        visibility(screen, False)
        expect(image).to_be_visible(timeout=15000)
        self.passed('Browser offline and explicitly simulated visibilitychange clear image src and shared board; returning online/visible revalidates before rendering')

    def delayed_photo(self, phone, uid, screen):
        held = []
        def hold(route):
            reply = route.fetch(max_redirects=0)
            assert reply.status == 200 and reply.headers['content-type'].startswith('image/jpeg')
            held.append((route, reply))
        pattern = self.base + '/api/media-tv/items/*/preview'
        screen.route(pattern, hold)
        self.command(phone, uid, '下一张照片', 'next')
        self.settle(screen, lambda: bool(held), timeout=8000)
        screen.context.set_offline(True)
        self.no_photo(screen)
        for route, reply in held:
            try: route.fulfill(response=reply)
            except Exception as error:
                assert 'closed' in str(error).lower() or 'interception' in str(error).lower() or 'invalid' in str(error).lower()
        screen.wait_for_timeout(350)
        self.no_photo(screen)
        screen.unroute(pattern, hold)
        screen.context.set_offline(False)
        expect(screen.get_by_test_id(PHOTO)).to_be_visible(timeout=15000)
        self.passed('A delayed real authorized JPEG cannot reinstall old pixels after offline invalidates its generation; reconnect requires fresh authorization')

    def expires_lease(self, uid, screen):
        short, held = [], []
        with closing(sqlite3.connect(self.database)) as con:
            original_expiry = con.execute('SELECT expires FROM devices WHERE id=?', (uid,)).fetchone()[0]
            con.execute('UPDATE devices SET expires=? WHERE id=?', (time.time() + 5, uid)); con.commit()
        def stall(route):
            path = urlsplit(route.request.url).path
            if path == '/api/media-tv/playback' and not short:
                reply = route.fetch(max_redirects=0)
                assert reply.status == 200
                value = reply.json()
                lease = (datetime.fromisoformat(value['validUntil']) - datetime.fromisoformat(value['serverTime'])).total_seconds()
                assert 0 < lease <= 5 and value['item']
                short.append(lease)
                route.fulfill(response=reply)
            elif path in ('/api/media-tv/playback', '/api/me', '/api/state'):
                held.append(route)
            else: route.continue_()
        screen.route(self.base + '/api/**', stall)
        try:
            self.settle(screen, lambda: bool(short), timeout=4000)
            self.no_photo(screen, timeout=6000)
            assert short and held, 'Lease test must encounter a real shortened lease plus a stalled next request'
        finally:
            with closing(sqlite3.connect(self.database)) as con:
                con.execute('UPDATE devices SET expires=? WHERE id=?', (original_expiry, uid)); con.commit()
            for route in held:
                try: route.abort('failed')
                except Exception: pass
            screen.unroute(self.base + '/api/**', stall)
        screen.reload(); self.board(screen)
        expect(screen.get_by_test_id(PHOTO)).to_be_visible(timeout=12000)
        self.report['shortLease'] = {'serverGenerated': True, 'deviceExpiryFixtureOnly': True,
                                     'leaseSeconds': short[0], 'responseJsonChanged': False}
        self.passed('Real device expiry caps server lease; actual image src clears while subsequent reads stall, without a fabricated lease response')

    def grant_and_dashboard(self, phone, uid, screen):
        for item_id in self.photos:
            item = self.get(phone.context, '/api/media/items/' + item_id)['item']
            self.write(phone.context, 'PUT', '/api/media/items/' + item_id + '/tv-grants', {'revision': item['revision'], 'deviceIds': []})
        self.no_photo(screen, timeout=7000)
        expect(screen.get_by_test_id('tv-photo-status')).to_contain_text('没有', timeout=7000)
        for item_id in self.photos:
            assert screen.context.request.get(self.base + '/api/media-tv/items/' + item_id + '/preview', headers=TV_HEADERS).status >= 400
        self.open_playback(phone, uid)
        expect(button(phone, '开始照片播放')).to_be_disabled()
        self.command(phone, uid, '显示家庭看板', 'dashboard', mode='dashboard')
        expect(screen.get_by_test_id('tv-photo-player')).to_be_hidden(timeout=7000)
        self.board(screen)
        self.passed('Real grant removal denies old photo URLs and clears pixels; explicit phone dashboard command returns to the independently configured Expo board')

    def cross_household_late_state(self, browser, phone, uid, screen):
        invitation = self.write(phone.context, 'POST', '/api/spaces/invitations', {}, 201)['invitation']
        entry = self.write(phone.context, 'POST', '/api/spaces/redeem', {'invitation': invitation,
            'name': '合成签名家庭', 'slug': 'expo-tv-signed', 'MEMBER1_PASSWORD': 'testing-password-one',
            'MEMBER2_PASSWORD': 'testing-password-two'}, 201)['entry']
        child = self.context(browser, member=None); self.lifecycle.callback(child.close)
        assert child.request.get(self.base + entry).status == 200
        self.login(child)
        child_phone = child.new_page(); self.page = child_phone
        other_tv, other_screen, other_uid = self.create_pair_from_screen(browser, child_phone, '合成另一家庭电视', 'member1', 'today', signed_entry=entry)
        assert self.tv_get(other_tv, '/api/state')['tasks'] == []
        self.get(child, PLAYBACK + uid, 404)
        self.write(child, 'PUT', PLAYBACK + uid, {'revision': 0, 'action': 'start'}, 404)
        self.tv_get(other_tv, '/api/media-playback/devices/' + uid, 403)
        self.passed('Signed household entry pairs a genuine separate TV; foreign device controls are denied and its shared board does not contain the first household')
        self.page = phone
        captured = []
        def late(route):
            reply = route.fetch(max_redirects=0)
            assert reply.status == 200
            captured.append(True)
            # Genuine WSGI routing switch deletes old TV cookie and changes the
            # signed household. The old successful response is released last.
            assert screen.context.request.get(self.base + entry).status == 200
            assert self.tv_get(screen.context, '/api/me')['user'] is None
            route.fulfill(response=reply)
        screen.route(self.base + '/api/state', late, times=1)
        self.settle(screen, lambda: bool(captured), timeout=16000)
        expect(screen.get_by_test_id(BOARD)).to_be_hidden(timeout=12000)
        expect(screen.locator('body')).not_to_contain_text('合成准备事项')
        self.no_photo(screen)
        assert all(c['name'] != 'household_tv' for c in screen.context.cookies())
        self.passed('A real old-household state response released after signed routing changes cannot restore the old board or photos; post-read identity rejects it')

    def revoke(self, phone, uid, screen):
        self.open_settings(phone, uid)
        button(phone, '撤销这台电视').click()
        with phone.expect_response(lambda r: urlsplit(r.url).path == DEVICES + '/' + uid and r.request.method == 'DELETE') as response:
            button(phone, '确认撤销电视').click()
        assert response.value.status == 200
        self.tv_get(screen.context, '/api/state', 401)
        self.tv_get(screen.context, '/api/media-tv/playback', 401)
        expect(screen.get_by_test_id(BOARD)).to_be_hidden(timeout=16000)
        self.no_photo(screen)
        self.passed('Phone revokes the second real TV cookie; actual state/playback return 401 and its previously visible shared board is removed')

    def run_scenarios(self, browser):
        with self.flow(browser) as (ctx, phone):
            self.seed_shared(ctx)
            first_tv, first_screen, first = self.create_pair_from_screen(browser, phone, '合成客厅电视', 'member1', 'today', member_cookie=True)
            second_tv, second_screen, second = self.create_pair_from_screen(browser, phone, '合成书房电视', 'member2', 'week')
            self.passed('Normal /tv enters Expo directly; a member cookie cannot mount member providers or authorize TV; two approved HttpOnly TV cookies reach the real board')
            self.layouts_and_finance(phone, first, second, first_screen, second_screen)
            self.dates_and_long_reading(phone, second, second_screen)
            self.photo_controls(phone, first, second, first_screen, second_screen)
            self.photo_lifecycle(first_screen)
            self.delayed_photo(phone, first, first_screen)
            self.expires_lease(first, first_screen)
            self.grant_and_dashboard(phone, first, first_screen)
            self.cross_household_late_state(browser, phone, first, first_screen)
            self.revoke(phone, second, second_screen)
            api_requests = [r for r in self.tv_requests if r['path'].startswith('/api/')]
            assert all(r['displayMode'] == 'tv' for r in api_requests), 'TV API request fell back to member authority'
            assert not [r for r in api_requests if r['method'] != 'GET' and r['path'] not in ('/api/pair/start', '/api/pair/poll')]
            assert not [r for r in api_requests if r['path'] in ('/api/preferences', '/api/dashboard-layout', '/api/accounts', '/api/devices')]
            self.report['televisionRequests'] = api_requests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--expected-build-evidence', required=True)
    args = parser.parse_args()
    root, bundle = args.source_root.resolve(), args.bundle.resolve()
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    assert head == args.expected_head
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
    out = Path(__file__).resolve().parents[1] / 'test-results' / ('expo-tv-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], screenshots=[],
        head=head, tree=evidence['sourceTree'], buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(out / 'executed-harness.py'),
        sourceHashesBefore=hashes(), bundleHashesBefore=bundle_hashes(), productionWrites=0, realCloud=False,
        realAI=False, physicalTelevision=False,
        scope='Actual temporary Flask/SQLite/Edge and approved HttpOnly TV cookies. Synthetic calendar acquisition and sanitized/encrypted JPEGs. No successful business mocks or HTML injection. Display Date advances without accelerating monotonic network/lease deadlines; visibilitychange is explicitly simulated. No physical TV/native/real-provider acceptance; screenshots show current viewports.')
    original_connect = socket.socket.connect
    def local_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
            report['externalRequests'].append({'kind': 'non-loopback socket'})
            raise AssertionError('External network forbidden')
        return original_connect(sock, address)
    folder, run = None, None
    try:
        with patch.object(socket.socket, 'connect', local_connect), sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            try:
                with ExitStack() as lifecycle:
                    folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='expo-tv-')))
                    run = Run(root, bundle, folder, report, out, lifecycle)
                    try:
                        run.run_scenarios(browser)
                        assert not report['pageErrors'] and not report['externalRequests']
                        report['passed'] = True
                    except Exception:
                        for n, screen in enumerate(run.televisions):
                            if not screen.is_closed():
                                try:
                                    screen.screenshot(path=str(out / f'failure-tv-{n+1}.png'), full_page=False)
                                    (out / f'failure-tv-{n+1}-aria.txt').write_text(screen.locator('body').aria_snapshot(), encoding='utf-8')
                                    (out / f'failure-tv-{n+1}-card-ids.json').write_text(json.dumps(
                                        screen.locator('[data-testid^="tv-card-"]').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.testid)'),
                                        ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                                except Exception:
                                    pass  # Preserve the original failure if a closed page cannot be captured.
                        raise
            finally:
                browser.close()
    except Exception:
        report['failure'] = traceback.format_exc()
        print(report['failure'], flush=True)
    finally:
        report['sourceHashesAfter'] = hashes()
        report['bundleHashesAfter'] = bundle_hashes()
        report['sourceUnchanged'] = report['sourceHashesBefore'] == report['sourceHashesAfter']
        report['bundleUnchanged'] = report['bundleHashesBefore'] == report['bundleHashesAfter']
        report['temporaryFixtureRemoved'] = folder is not None and not folder.exists()
        if run:
            report['televisionRequests'] = run.tv_requests
        report['passed'] = report['passed'] and report['sourceUnchanged'] and report['bundleUnchanged'] and report['temporaryFixtureRemoved']
        (out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'report': str(out / 'result.json')}, ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    raise SystemExit(main())
