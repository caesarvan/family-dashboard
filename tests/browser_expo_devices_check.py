"""Frozen Expo TV management and shipped 1920px viewer against real local APIs.

Only source-photo acquisition is synthetic: the existing media worker fixture
receives generated images, then real sanitization, encryption, confirmation and
grants are exercised. Pairing uses real cookies. No provider or production I/O.
This does not run the older finance/media browser suites or claim physical TV.
"""
import argparse
from contextlib import ExitStack, closing
from datetime import datetime, timezone
import importlib
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
import browser_expo_finance_check as base_fixture
from browser_expo_finance_check import Run as BaseRun, button, sha


DEVICES = '/api/devices'
PLAYBACK = '/api/media-playback/devices/'
CARDS = ['calendar', 'finance', 'tasks', 'shopping', 'trips']
NAMES = dict(calendar='日程安排', finance='家庭财务', tasks='共同待办', shopping='采购清单', trips='下一趟旅行')
DEFAULT = dict(order=CARDS, hidden=[], theme='forest', density='comfortable')
LONG_NAME = '合成客厅电视用于长名称换行与键盘操作核对'


def textbox(page, label):
    return page.get_by_role('textbox', name=label, exact=True)


class Run(BaseRun):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.media_fixture = importlib.import_module('test_household_media')
        for module, name in ((base_fixture, 'tests/browser_expo_finance_check.py'),
                             (self.media_fixture, 'tests/test_household_media.py')):
            assert sha(Path(module.__file__)) == sha(self.root / name)
            self.report.setdefault('fixtureHashes', {})[name] = sha(Path(module.__file__))
        assert sha(Path(__file__)) == sha(self.root / 'tests/browser_expo_devices_check.py')
        assert Path(self.source.__file__).resolve() == (self.root / 'app.py').resolve()
        # No fallback registration or test HTML injection is allowed.
        assert 'household_media' in self.application.extensions
        assert 'media_playback' in self.application.extensions
        self.clock = [time.time()]
        self.engine = self.application.extensions['household_media']
        self.engine.clock = lambda: self.clock[0]
        self.application.extensions['media_playback'].clock = lambda: self.clock[0]
        self.photos = []

    def start(self, port=0):
        self.cfg.update(GOOGLE_CLIENT_ID='synthetic-devices-client', GOOGLE_CLIENT_SECRET='synthetic-devices-secret')
        super().start(port)

    def clear_finance(self):
        pass

    def snapshot(self):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database)) as con:
            return {table: sorted(con.execute('SELECT * FROM "' + table + '"').fetchall(), key=repr)
                    for table in ('devices', 'media_playback', 'media_tv_grants', 'entities', 'settings')}

    def device(self, ctx, uid):
        return next(row for row in self.get(ctx, DEVICES) if row['id'] == uid)

    def playback(self, ctx, uid):
        return self.get(ctx, PLAYBACK + uid)

    def open_list(self, page):
        page.goto(self.base + '/app/devices')
        expect(page.get_by_role('heading', name='电视与播放', exact=True)).to_be_visible(timeout=15000)
        expect(button(page, '连接电视')).to_be_enabled()

    def open_settings(self, page, uid):
        self.open_list(page)
        name = self.device(page.context, uid)['name']
        button(page, '显示设置：' + name).click()
        expect(page.get_by_role('heading', name='电视显示设置', exact=True)).to_be_visible()
        expect(textbox(page, '电视名称')).to_be_editable()
        expect(textbox(page, '电视名称')).to_have_value(name)

    def open_playback(self, page, uid):
        self.open_list(page)
        name = self.device(page.context, uid)['name']
        button(page, '播放控制：' + name).click()
        expect(button(page, '刷新播放状态')).to_be_enabled()

    def shots(self, page, name):
        for width in (320, 390, 1440):
            page.set_viewport_size({'width': width, 'height': 1000 if width == 1440 else 844})
            page.wait_for_timeout(400)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2')
            self.screenshot(page, name, width)
        page.set_viewport_size({'width': 390, 'height': 844})

    def tv_shot(self, page, name):
        page.set_viewport_size({'width': 1920, 'height': 1080})
        page.wait_for_timeout(400)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2')
        path = self.out / (name + '-1920.png')
        page.screenshot(path=str(path), full_page=False)
        self.report['screenshots'].append({'path': path.name, 'sha256': sha(path), 'width': 1920, 'height': 1080})

    def cannot_leave_unknown(self, page, method, path):
        original_url, before, count = page.url, self.snapshot(), self.count_requests(method, path)
        page.get_by_role('tab', name='首页', exact=True).click()
        expect(page.get_by_test_id('device-operation-unknown')).to_be_visible()
        expect(page.get_by_text('电视操作结果尚未核对，请先核对当前状态。', exact=True)).to_be_visible()
        button(page, '知道了').click()
        assert page.url == original_url and self.snapshot() == before
        assert self.count_requests(method, path) == count

    def create_pair(self, browser, owner, page, name, focus, view):
        tv = self.context(browser, member=None)
        tv.set_default_timeout(15000)
        tv_request = tv.request.post(self.base + '/api/pair/start', data={})
        assert tv_request.status == 200
        pairing = tv_request.json()
        assert not tv.request.post(self.base + '/api/pair/poll', data={'secret': pairing['secret']}).json()['approved']
        before_ids = {d['id'] for d in self.get(owner, DEVICES)}
        button(page, '连接电视').click()
        textbox(page, '电视配对码').fill(pairing['code'][:4] + ' ' + pairing['code'][4:])
        textbox(page, '电视名称').fill(name)
        people = {p['id']: p['name'] for p in self.get(owner, '/api/state')['people']}
        page.get_by_role('radio', name='侧重成员：' + people.get(focus, '共同'), exact=True).click()
        page.get_by_role('radio', name='日程范围：' + {'today': '今天', 'week': '本周', 'around': '前后3天'}[view], exact=True).click()
        with page.expect_response(lambda r: urlsplit(r.url).path == '/api/pair/approve' and r.request.method == 'POST') as approved:
            button(page, '确认连接电视').click()
        assert approved.value.status == 200, approved.value.text()
        expect(button(page, '显示设置：' + name)).to_be_visible()
        result = tv.request.post(self.base + '/api/pair/poll', data={'secret': pairing['secret']})
        assert result.status == 200 and result.json()['approved']
        assert any(c['name'] == 'household_tv' and c['httpOnly'] for c in tv.cookies())
        device = next(row for row in self.get(owner, DEVICES) if row['id'] not in before_ids)
        assert device['name'] == name and device['focus'] == focus and device['calendarView'] == view
        assert device['layout'] == DEFAULT
        assert self.get(tv, '/api/me')['user']['role'] == 'tv'
        screen = tv.new_page()
        screen.set_viewport_size({'width': 1920, 'height': 1080})
        screen.goto(self.base + '/tv')
        expect(screen.locator('body.tv .board[data-tv-count]')).to_be_visible()
        assert screen.locator('script[src="/static/media-tv.js"]').count() == 1
        assert screen.locator('link[href="/static/media-tv.css"]').count() == 1
        return tv, screen, device['id']

    def seed_photos(self, ctx, device_id):
        scope = importlib.import_module('cloud_accounts').GOOGLE_PHOTOS_SCOPE
        account_id = uuid4().hex
        with self.engine.accounts.db() as con:
            tokens = self.engine.accounts.encrypt({'access_token': 'synthetic-never-sent', 'scope': scope,
                                                  'expires_at': time.time() + 3600})
            con.execute('INSERT INTO cloud_accounts(id,owner,provider,client_id,subject,name,email,tokens) VALUES(?,?,?,?,?,?,?,?)',
                (account_id, 'member1', 'google', 'synthetic-devices-client', 'synthetic-device-owner',
                 '合成照片账户', 'synthetic@example.invalid', tokens))
        result = self.write(ctx, 'POST', '/api/media/imports', {'requestId': uuid4().hex, 'accountId': account_id,
            'consentVersion': 'media-v1', 'allowTemporaryProcessing': True}, 202)
        iid = result['import']['id']
        manifest = [self.media_fixture.selected('synthetic-tv-photo-' + str(n)) for n in range(3)]
        job = self.engine.claim_next()
        assert job['action'] == 'create'
        assert self.engine.complete(job, self.media_fixture.session((self.application, self.engine, self.clock, {})))
        job = self.engine.claim_next()
        assert job['action'] == 'list' and self.engine.complete(job, manifest)
        while (job := self.engine.claim_next()) is not None:
            if job['action'] == 'cleanup':
                assert self.engine.complete(job, None)
                break
            assert job['action'] == 'download'
            sanitized = self.media_fixture.preview()
            assert sanitized.content_type == 'image/jpeg' and sanitized.width == 20 and sanitized.height == 12
            assert self.engine.complete(job, {'mediaId': job['media']['id'], 'manifest': manifest, 'preview': sanitized})
        detail = self.get(ctx, '/api/media/imports/' + iid)
        assert len(detail['items']) == 3 and detail['import']['canConfirm']
        self.write(ctx, 'POST', '/api/media/imports/' + iid + '/confirm', {
            'revision': detail['import']['revision'], 'confirmRequestId': uuid4().hex,
            'itemIds': [i['id'] for i in detail['items']], 'consentVersion': 'media-v1', 'persistSelected': True})
        for row in detail['items']:
            item = self.get(ctx, '/api/media/items/' + row['id'])['item']
            item = self.write(ctx, 'PATCH', '/api/media/items/' + item['id'], {'revision': item['revision'], 'visibility': 'shared'})['item']
            self.write(ctx, 'PUT', '/api/media/items/' + item['id'] + '/tv-grants', {'revision': item['revision'],
                'deviceIds': [device_id], 'consentVersion': 'media-v1', 'allowTvDisplay': True})
            self.photos.append(item['id'])
        assert self.playback(ctx, device_id)['photoCount'] == 3

    def unknown_pair(self, browser, page, committed):
        self.open_list(page)
        before = self.get(page.context, DEVICES)
        television = self.context(browser, member=None)
        try:
            response = television.request.post(self.base + '/api/pair/start', data={})
            assert response.status == 200
            pairing = response.json()
            name = '合成配对' + ('响应丢失' if committed else '请求未送达')
            button(page, '连接电视').click()
            textbox(page, '电视配对码').fill(pairing['code'])
            textbox(page, '电视名称').fill(name)
            attempts, path = [], '/api/pair/approve'
            def lose(route):
                attempts.append(route.request.post_data_json)
                if committed:
                    result = route.fetch(max_redirects=0)
                    assert result.status == 200
                route.abort('failed')
            page.route(self.base + path, lose)
            button(page, '确认连接电视').click()
            expect(page.get_by_test_id('device-operation-unknown')).to_be_visible()
            page.unroute(self.base + path, lose)
            assert len(attempts) == 1
            assert television.request.post(self.base + '/api/pair/poll', data={'secret': pairing['secret']}).json()['approved'] is committed
            count, stored = self.count_requests('POST', path), self.snapshot()
            button(page, '核对操作结果').click()
            expect(page.get_by_test_id('pair-current-devices')).to_be_visible()
            actual = self.get(page.context, DEVICES)
            assert len(actual) == len(before) + int(committed)
            if committed:
                added = next(d for d in actual if d['name'] == name)
                expect(page.get_by_test_id('pair-current-device-' + added['id'])).to_contain_text(name)
            else:
                expect(page.get_by_test_id('pair-current-devices')).not_to_contain_text(name)
            assert self.count_requests('POST', path) == count and self.snapshot() == stored
            button(page, '核对完成，返回设备列表').click()
            expect(page.get_by_role('heading', name='电视与播放', exact=True)).to_be_visible()
            expect(textbox(page, '电视配对码')).to_have_count(0)
            assert self.count_requests('POST', path) == count and self.snapshot() == stored
            self.passed(('Committed pairing reply loss' if committed else 'Pairing request loss') + ': explicit GET displays the real current device list, completion clears the old pair draft without another approve POST')
            if committed:
                self.write(page.context, 'DELETE', DEVICES + '/' + added['id'], {})
        finally:
            television.close()

    def save_settings(self, page, uid):
        with page.expect_response(lambda r: urlsplit(r.url).path == DEVICES + '/' + uid and r.request.method == 'PATCH') as response:
            button(page, '保存到这台电视').click()
        result = response.value
        expect(page.get_by_test_id('device-operation-unknown')).to_be_hidden()
        if result.status == 200:
            expect(button(page, '保存到这台电视')).to_be_enabled()
        return result

    def layouts(self, page, first, second, screen1, screen2):
        ctx = page.context
        self.open_settings(page, first)
        original_second = self.device(ctx, second)
        before = self.snapshot()
        textbox(page, '电视名称').fill(LONG_NAME)
        page.get_by_role('radio', name='电视主题：晴日', exact=True).click()
        page.get_by_role('radio', name='显示密度：紧凑', exact=True).click()
        check = page.get_by_role('checkbox', name='显示卡片：家庭财务', exact=True)
        expect(check).to_be_checked()
        check.focus(); check.press('Space')
        expect(check).not_to_be_checked()
        button(page, '上移：共同待办').click(); button(page, '上移：共同待办').click()
        assert self.snapshot() == before, 'Local settings draft mutated persisted rows'
        self.shots(page, 'device-layout-draft')
        response = self.save_settings(page, first)
        assert response.status == 200
        expected = dict(order=['tasks', 'calendar', 'finance', 'shopping', 'trips'], hidden=['finance'], theme='light', density='compact')
        actual = self.device(ctx, first)
        assert actual['layout'] == expected and actual['name'] == LONG_NAME
        assert self.device(ctx, second) == original_second
        page.reload()
        self.open_settings(page, first)
        expect(textbox(page, '电视名称')).to_have_value(LONG_NAME)
        expect(page.get_by_role('checkbox', name='显示卡片：家庭财务', exact=True)).not_to_be_checked()
        expect(page.get_by_role('radio', name='电视主题：晴日', exact=True)).to_be_checked()
        self.open_settings(page, second)
        page.get_by_role('radio', name='电视主题：海岸', exact=True).click()
        assert self.save_settings(page, second).status == 200
        for screen, uid, theme, density, order, hidden in (
                (screen1, first, 'light', 'compact', expected['order'], ['finance']),
                (screen2, second, 'ocean', 'comfortable', CARDS, [])):
            screen.reload()
            expect(screen.locator('body')).to_have_attribute('data-tv-theme', theme)
            expect(screen.locator('body')).to_have_attribute('data-tv-density', density)
            actual_order = screen.locator('.board > [data-tv-card]').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.tvCard)')
            assert actual_order == order
            for key in CARDS:
                assert screen.locator('.board [data-tv-card="' + key + '"]').is_visible() is (key not in hidden)
            display = self.get(screen.context, '/api/state')['display']
            assert display['layout'] == self.device(ctx, uid)['layout']
            assert display['focus'] == ('member1' if uid == first else 'member2')
            assert display['calendarView'] == ('week' if uid == first else 'around')
        self.tv_shot(screen1, 'television-layout')
        self.passed('Two independently paired TV cookies persist separate focus/range/order/hidden/theme/density; keyboard draft is zero-write and real 1920 viewer applies saved settings after reload')

    def conflict(self, page, uid):
        self.open_settings(page, uid)
        original = self.device(page.context, uid)
        draft_name = '合成我保留的草稿名称'
        textbox(page, '电视名称').fill(draft_name)
        self.write(page.context, 'PATCH', DEVICES + '/' + uid, {'revision': original['revision'], 'name': '合成另一窗口已保存'})
        before = self.snapshot()
        assert self.save_settings(page, uid).status == 409
        assert self.snapshot() == before
        expect(textbox(page, '电视名称')).to_have_value(draft_name)
        expect(button(page, '保存到这台电视')).to_be_disabled()
        button(page, '读取最新设置').click()
        expect(button(page, '保留我的草稿，使用最新版本')).to_be_enabled()
        expect(textbox(page, '电视名称')).to_have_value(draft_name)
        assert self.snapshot() == before
        self.shots(page, 'device-version-conflict')
        button(page, '保留我的草稿，使用最新版本').click()
        assert self.snapshot() == before
        assert self.save_settings(page, uid).status == 200
        assert self.device(page.context, uid)['revision'] == original['revision'] + 2
        assert self.device(page.context, uid)['name'] == draft_name
        self.passed('Actual concurrent device revision rejects stale save without writes; read latest preserves draft and only explicit rebase plus save replaces configuration')

    def unknown_settings(self, page, uid, committed):
        self.open_settings(page, uid)
        original = self.device(page.context, uid)
        target_name = '合成' + ('已提交丢响应' if committed else '未送达请求')
        textbox(page, '电视名称').fill(target_name)
        attempts = []
        def lose(route):
            attempts.append(route.request.post_data_json)
            if committed:
                reply = route.fetch(max_redirects=0)
                assert reply.status == 200
            route.abort('failed')
        path = DEVICES + '/' + uid
        page.route(self.base + path, lose)
        button(page, '保存到这台电视').click()
        expect(page.get_by_test_id('device-operation-unknown')).to_be_visible()
        page.unroute(self.base + path, lose)
        assert len(attempts) == 1
        persisted = self.device(page.context, uid)
        assert persisted['revision'] == original['revision'] + int(committed)
        assert persisted['name'] == (target_name if committed else original['name'])
        self.cannot_leave_unknown(page, 'PATCH', path)
        before, count = self.snapshot(), self.count_requests('PATCH', path)
        button(page, '核对操作结果').click()
        expect(button(page, '我已核对当前状态')).to_be_enabled()
        assert self.count_requests('PATCH', path) == count and self.snapshot() == before
        button(page, '我已核对当前状态').click()
        assert self.count_requests('PATCH', path) == count
        if not committed:
            button(page, '保留我的草稿，使用最新版本').click()
            expect(textbox(page, '电视名称')).to_have_value(target_name)
            expect(button(page, '保存到这台电视')).to_be_enabled()
            assert self.save_settings(page, uid).status == 200
            assert self.device(page.context, uid)['revision'] == original['revision'] + 1
        else:
            button(page, '采用最新设置').click()
            expect(textbox(page, '电视名称')).to_have_value(target_name)
            assert self.count_requests('PATCH', path) == count
        self.passed(('Committed reply loss' if committed else 'Request loss') + ': device update stays unknown, explicit readback is GET-only and acknowledgement never blindly resends PATCH')

    def command(self, page, uid, label, action, **expected):
        before = self.playback(page.context, uid)
        with page.expect_response(lambda r: urlsplit(r.url).path == PLAYBACK + uid and r.request.method == 'PUT') as result:
            button(page, label).click()
        response = result.value
        assert response.status == 200, response.text()
        assert response.request.post_data_json['action'] == action
        expect(page.get_by_test_id('device-operation-unknown')).to_be_hidden()
        expect(button(page, '刷新播放状态')).to_be_enabled()
        saved = self.playback(page.context, uid)
        assert saved['revision'] == before['revision'] + 1
        assert all(saved[key] == value for key, value in expected.items()), saved
        return saved

    def playback_controls(self, page, first, second, screen1, screen2):
        self.open_playback(page, first)
        layout = self.device(page.context, first)
        other = self.playback(page.context, second)
        self.shots(page, 'device-playback')
        self.command(page, first, '开始照片播放', 'start', mode='photos', paused=False)
        image = screen1.locator('.media-tv-screen img')
        expect(image).to_be_visible(timeout=10000)
        assert image.evaluate('(n)=>n.naturalWidth===20 && n.naturalHeight===12')
        expect(screen2.locator('.media-tv-screen')).to_be_hidden()
        self.command(page, first, '暂停播放', 'pause', paused=True)
        expect(screen1.locator('.media-tv-progress')).to_contain_text('已暂停', timeout=6000)
        first_src = image.get_attribute('src')
        initial_position = self.playback(page.context, first)['position']
        self.command(page, first, '下一张照片', 'next', position=(initial_position + 1) % 3)
        screen1.wait_for_function('(old)=>{const n=document.querySelector(".media-tv-screen img");return n && !n.hidden && n.getAttribute("src")!==old}', arg=first_src)
        self.command(page, first, '上一张照片', 'previous', position=initial_position)
        textbox(page, '轮播间隔（秒）').fill('5')
        self.command(page, first, '保存轮播间隔', 'interval', intervalSeconds=5, paused=True)
        self.command(page, first, '继续播放', 'resume', paused=False)
        self.clock[0] += 6
        assert self.playback(page.context, first)['position'] == (initial_position + 1) % 3
        self.command(page, first, '暂停播放', 'pause', paused=True)
        self.tv_shot(screen1, 'television-photo')
        assert self.device(page.context, first) == layout and self.playback(page.context, second) == other
        self.passed('Real encrypted JPEG appears only on granted TV; start/pause/next/previous/5-second interval/resume persist and advance one deterministic server-clock step without changing layout or second TV')
        screen1.context.set_offline(True)
        expect(image).to_be_hidden(timeout=1500)
        assert image.get_attribute('src') is None
        screen1.context.set_offline(False)
        expect(image).to_be_visible(timeout=10000)
        self.passed('Shipped TV viewer clears its actual object URL on offline and reloads only after authorized online readback')

    def unknown_playback(self, page, uid, committed):
        self.open_playback(page, uid)
        original = self.playback(page.context, uid)
        assert original['paused'] and original['photoCount'] == 3
        path, attempts = PLAYBACK + uid, []
        def lose(route):
            if route.request.method != 'PUT':
                route.continue_(); return
            attempts.append(route.request.post_data_json)
            if committed:
                reply = route.fetch(max_redirects=0)
                assert reply.status == 200
            route.abort('failed')
        page.route(self.base + path, lose)
        button(page, '下一张照片').click()
        expect(page.get_by_test_id('device-operation-unknown')).to_be_visible()
        page.unroute(self.base + path, lose)
        assert len(attempts) == 1
        actual = self.playback(page.context, uid)
        assert actual['position'] == (original['position'] + int(committed)) % 3
        assert actual['revision'] == original['revision'] + int(committed)
        self.cannot_leave_unknown(page, 'PUT', path)
        before, count = self.snapshot(), self.count_requests('PUT', path)
        button(page, '核对操作结果').click()
        expect(button(page, '我已核对当前状态')).to_be_enabled()
        assert self.count_requests('PUT', path) == count and self.snapshot() == before
        button(page, '我已核对当前状态').click()
        assert self.count_requests('PUT', path) == count
        if not committed:
            self.command(page, uid, '下一张照片', 'next', position=(original['position'] + 1) % 3)
        assert self.playback(page.context, uid)['revision'] == original['revision'] + 1
        self.passed(('Committed reply loss' if committed else 'Request loss') + ': playback advances at most once; unknown recovery reads state and requires explicit acknowledgement/action, never auto-resends next')

    def playback_conflict(self, page, uid):
        self.open_playback(page, uid)
        original = self.playback(page.context, uid)
        textbox(page, '轮播间隔（秒）').fill('17')
        self.write(page.context, 'PUT', PLAYBACK + uid, {'revision': original['revision'], 'action': 'interval', 'intervalSeconds': 20})
        before = self.snapshot()
        with page.expect_response(lambda r: urlsplit(r.url).path == PLAYBACK + uid and r.request.method == 'PUT') as reply:
            button(page, '保存轮播间隔').click()
        assert reply.value.status == 409 and self.snapshot() == before
        expect(textbox(page, '轮播间隔（秒）')).to_have_value('17')
        button(page, '刷新播放状态').click()
        expect(button(page, '保存轮播间隔')).to_be_enabled()
        assert self.snapshot() == before
        expect(textbox(page, '轮播间隔（秒）')).to_have_value('17')
        self.command(page, uid, '保存轮播间隔', 'interval', intervalSeconds=17)
        self.passed('Playback 409 preserves interval draft; explicit fresh read precedes a new explicitly saved command')

    def grant_revoke(self, page, uid, screen):
        self.open_playback(page, uid)
        for item_id in self.photos:
            item = self.get(page.context, '/api/media/items/' + item_id)['item']
            self.write(page.context, 'PUT', '/api/media/items/' + item_id + '/tv-grants', {'revision': item['revision'], 'deviceIds': []})
        image = screen.locator('.media-tv-screen img')
        expect(image).to_be_hidden(timeout=6000)
        assert image.get_attribute('src') is None
        expect(screen.locator('.media-tv-screen p')).to_contain_text('没有可播放')
        button(page, '刷新播放状态').click()
        expect(button(page, '开始照片播放')).to_be_disabled()
        assert self.playback(page.context, uid)['photoCount'] == 0
        for item_id in self.photos:
            response = screen.context.request.get(self.base + '/api/media-tv/items/' + item_id + '/preview')
            assert response.status >= 400
        self.command(page, uid, '显示家庭看板', 'dashboard', mode='dashboard')
        expect(screen.locator('.media-tv-screen')).to_be_hidden(timeout=6000)
        expect(screen.locator('.board')).to_be_visible()
        self.passed('Actual photo-grant revocation clears displayed bytes and forbids old previews; explicit dashboard command returns to independently saved layout')

    def cross_household_and_late_identity(self, browser, owner, uid):
        invitation = self.write(owner, 'POST', '/api/spaces/invitations', {}, 201)['invitation']
        created = self.write(owner, 'POST', '/api/spaces/redeem', {'invitation': invitation,
            'name': '合成电视第二家庭', 'slug': 'expo-devices-other',
            'MEMBER1_PASSWORD': 'testing-password-one', 'MEMBER2_PASSWORD': 'testing-password-two'}, 201)
        entry = created['entry']
        with ExitStack() as stack:
            child = self.context(browser, member=None); stack.callback(child.close)
            assert child.request.get(self.base + entry).status == 200
            self.login(child)
            assert self.get(child, DEVICES) == []
            before = self.snapshot()
            self.get(child, PLAYBACK + uid, 404)
            self.write(child, 'PATCH', DEVICES + '/' + uid, {'revision': 1, 'name': '不得跨户'}, 404)
            self.write(child, 'PUT', PLAYBACK + uid, {'revision': 0, 'action': 'start'}, 404)
            self.write(child, 'DELETE', DEVICES + '/' + uid, {})
            assert self.snapshot() == before
            self.passed('Actual invited household cannot read/control a foreign TV; idempotent foreign DELETE leaves the owning household unchanged')
            ctx = self.context(browser); stack.callback(ctx.close)
            page = ctx.new_page(); self.page = page
            self.open_playback(page, uid)
            original_name = self.device(ctx, uid)['name']
            intercepted = []
            def late(route):
                response = route.fetch(max_redirects=0)
                assert response.status == 200
                intercepted.append(True)
                assert ctx.request.get(self.base + entry).status == 200
                self.login(ctx)
                assert self.get(ctx, '/api/me')['user']['householdId'] != 'default'
                route.fulfill(response=response)
            before, request_start = self.snapshot(), len(self.requests)
            page.route(self.base + PLAYBACK + uid, late, times=1)
            button(page, '刷新播放状态').click()
            expect(page.locator('body')).not_to_contain_text(original_name, timeout=15000)
            assert intercepted and self.snapshot() == before
            assert not [r for r in self.requests[request_start:] if r['method'] in ('PUT', 'PATCH', 'DELETE')]
            self.passed('A real old-household playback response delivered after a genuine household/session switch cannot install old device content or issue a command')

    def revoke_device(self, page, uid, tv, screen):
        self.open_settings(page, uid)
        button(page, '撤销这台电视').click()
        with page.expect_response(lambda r: urlsplit(r.url).path == DEVICES + '/' + uid and r.request.method == 'DELETE') as reply:
            button(page, '确认撤销电视').click()
        assert reply.value.status == 200
        assert uid not in {row['id'] for row in self.get(page.context, DEVICES)}
        self.get(tv, '/api/state', 401)
        self.get(tv, '/api/media-tv/playback', 401)
        self.get(page.context, PLAYBACK + uid, 404)
        self.write(page.context, 'PATCH', DEVICES + '/' + uid, {'revision': 1, 'name': '不可恢复'}, 404)
        expect(screen.locator('.media-tv-screen img')).to_be_hidden(timeout=6000)
        with closing(sqlite3.connect(self.database)) as con:
            assert con.execute('SELECT count(*) FROM media_playback WHERE device_id=?', (uid,)).fetchone()[0] == 0
        self.passed('Explicit Expo revoke removes pairing and cascades playback; old TV cookie is rejected and an old device ID cannot restore access')

    def run_scenarios(self, browser):
        with self.flow(browser) as (ctx, page), ExitStack() as televisions:
            self.unknown_pair(browser, page, committed=False)
            self.unknown_pair(browser, page, committed=True)
            self.open_list(page)
            first_tv, screen1, first = self.create_pair(browser, ctx, page, LONG_NAME, 'member1', 'week')
            televisions.callback(first_tv.close)
            second_tv, screen2, second = self.create_pair(browser, ctx, page, '合成书房电视', 'member2', 'around')
            televisions.callback(second_tv.close)
            self.shots(page, 'paired-devices')
            self.get(first_tv, DEVICES, 403)
            self.get(first_tv, PLAYBACK + first, 403)
            response = first_tv.request.patch(self.base + DEVICES + '/' + first, data={'revision': 1, 'name': '不得写入'})
            assert response.status == 403
            self.passed('Expo pairing approves two actual TV cookies; list handles long text at three widths and TV role cannot enter member management APIs')
            self.layouts(page, first, second, screen1, screen2)
            self.conflict(page, first)
            self.unknown_settings(page, first, committed=True)
            self.unknown_settings(page, first, committed=False)
            self.seed_photos(ctx, first)
            self.playback_controls(page, first, second, screen1, screen2)
            self.unknown_playback(page, first, committed=True)
            self.unknown_playback(page, first, committed=False)
            self.playback_conflict(page, first)
            self.grant_revoke(page, first, screen1)
            self.cross_household_and_late_identity(browser, ctx, first)
            self.page = page
            self.revoke_device(page, first, first_tv, screen1)
            assert len(self.get(ctx, DEVICES)) == 1 and self.device(ctx, second)['name'] == '合成书房电视'


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
    out = Path(__file__).resolve().parents[1] / 'test-results' / ('expo-devices-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], screenshots=[],
        head=head, tree=evidence['sourceTree'], buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(out / 'executed-harness.py'),
        sourceHashesBefore=hashes(), bundleHashesBefore=bundle_hashes(), productionWrites=0, realCloud=False,
        realAI=False, physicalTelevision=False,
        scope='Actual temporary Flask/SQLite/member and pairing cookies/Edge. Generated photos enter the real sanitization/encryption/confirmation/grant pipeline through synthetic media-worker acquisition. No HTML injection, API response mocks, real Google or physical TV. Delayed/dropped real responses are explicit faults. Screenshots cover current visible internal scroll positions only.')
    original_connect = socket.socket.connect
    def local_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
            report['externalRequests'].append({'kind': 'non-loopback socket'})
            raise AssertionError('External network forbidden')
        return original_connect(sock, address)
    folder = None
    try:
        with patch.object(socket.socket, 'connect', local_connect), sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            try:
                with ExitStack() as lifecycle:
                    folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='expo-devices-')))
                    run = Run(root, bundle, folder, report, out, lifecycle)
                    run.run_scenarios(browser)
                    report['requestCounts'] = {key: sum(1 for row in run.requests if row['method'] + ' ' + row['path'] == key)
                        for key in sorted({row['method'] + ' ' + row['path'] for row in run.requests})}
                    assert not report['pageErrors'] and not report['externalRequests']
                    report['passed'] = True
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
        report['passed'] = report['passed'] and report['sourceUnchanged'] and report['bundleUnchanged'] and report['temporaryFixtureRemoved']
        (out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'report': str(out / 'result.json')}, ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    raise SystemExit(main())
