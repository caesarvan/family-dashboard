"""Frozen complex itineraries against isolated real Flask/SQLite/Edge.

Each case owns its temporary household and HTTP server. Business successes are
never mocked: fault routes only forward, delay or discard actual requests/replies.
Visibility events are explicitly simulated; no real AI, cloud or production use.
"""
import argparse
from contextlib import ExitStack, closing
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import traceback
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright
import browser_expo_finance_check as fixture
from browser_expo_finance_check import Run as BaseRun, button, sha, visibility

PREVIEW = '/api/journeys/preview'
APPLY = '/api/journeys/apply'
OPERATIONS = '/api/journeys/operations/'
CHECKS = 15
SCREENSHOTS = 19
WIDTHS = (320, 390, 1280, 1920)


def field(page, name):
    return page.get_by_role('textbox', name=name, exact=True)


def radio(page, name):
    return page.get_by_role('radio', name=name, exact=True)


def versions(detail):
    return {row['id']: row['revision'] for row in
            [detail['trip'], *detail['tasks'], *detail['shopping'], *detail['events']] if row}


class Run(BaseRun):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        assert Path(self.source.__file__).resolve() == (self.root / 'app.py').resolve()
        files = [(Path(__file__), 'tests/browser_expo_segments_check.py'),
                 (Path(fixture.__file__), 'tests/browser_expo_finance_check.py')]
        files += [(Path(sys.modules[name].__file__), 'tests/' + name + '.py')
                  for name in ('test_financial_files', 'test_app')]
        for actual, name in files:
            assert sha(actual) == sha(self.root / name), name
            self.report.setdefault('fixtureHashes', {})[name] = sha(actual)

    def clear_finance(self):
        pass  # Inherit only temporary server/session utilities, no finance resets.

    def snapshot(self):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database)) as con:
            return {table: sorted(con.execute('SELECT * FROM ' + table).fetchall(), key=repr)
                    for table in ('journey_workflows', 'journey_links', 'journey_actions', 'entities', 'audit')}

    def screenshot(self, page, name, width, dialog=False):
        super().screenshot(page, name, width, dialog)
        # Per-case files must remain resolvable from the aggregate report folder.
        self.report['screenshots'][-1]['path'] = self.out.name + '/' + self.report['screenshots'][-1]['path']

    def detail(self, ctx, journey):
        return self.get(ctx, '/api/journeys/' + (journey if isinstance(journey, str) else journey['id']))

    def seed(self, ctx, v2=True, title='合成详细行程'):
        if v2:
            plan = json.loads((self.root / 'static/examples/journey-plan-v2.json').read_text(encoding='utf-8'))
            plan['title'] = title
        else:
            plan = dict(title=title, start='2027-10-01', end='2027-10-12', international=True,
                        destinations=[dict(key='old-city', country='日本', city='东京', arrival='2027-10-01', departure='2027-10-12')],
                        checklist=[dict(key='packing', title='合成待准备', owner='member1', due='2027-09-28')],
                        shopping=[dict(key='unknown', title='合成未知预算', owner='member2', quantity='2 件', budget=None),
                                  dict(key='zero', title='合成零预算', owner='shared', quantity='1 件', budget=0)],
                        segments=[dict(key='legacy-stable', title='合成原日期段', start='2027-10-02', end='2027-10-03', note='保留原日期含义')])
        plan.update(memberIds=['member1', 'member2'], budget=1234567, saved=23456, paid=7890)
        preview = self.write(ctx, 'POST', PREVIEW, {'plan': plan})
        receipt = self.write(ctx, 'POST', APPLY, dict(previewToken=preview['previewToken'], idempotencyKey=uuid4().hex), 201)
        return self.detail(ctx, receipt['id'])

    def open_panel(self, page, journey):
        page.goto(self.base + '/app/trips?request=1001&item=' + journey['tripId'])
        expect(button(page, '行程分段')).to_be_enabled(timeout=15000)
        button(page, '行程分段').click()
        expect(page.get_by_test_id('journey-segments-panel')).to_be_visible(timeout=15000)
        expect(field(page, '旅行参考时区')).to_be_enabled(timeout=15000)

    def edit(self, page, title):
        radio(page, '编辑行程分段').click()
        target = button(page, '编辑分段：' + title)
        for _ in range(20):
            if target.count():
                target.click(); expect(field(page, '分段标题')).to_have_value(title); return
            next_page = button(page, '分段下一页')
            assert next_page.count() and next_page.is_enabled(), title
            next_page.click()
        raise AssertionError('Segment missing from paginated UI: ' + title)

    def capture(self, page, path, action, expected=200):
        captured = []
        def forward(route):
            response = route.fetch(max_redirects=0)
            body = response.body()
            captured.append((response.status, json.loads(body), route.request.post_data_json))
            route.fulfill(response=response, body=body)
        endpoint = self.base + path
        page.route(endpoint, forward, times=1)
        try:
            with page.expect_response(lambda response: response.url == endpoint) as pending:
                action()
            assert len(captured) == 1
            status, result, sent = captured[0]
            assert pending.value.status == status == expected, (status, result)
            return result, sent
        finally:
            page.unroute(endpoint, forward)

    def preview(self, page, can_apply=True, label='预览详细行程'):
        before = self.snapshot(); count = self.count_requests('POST', APPLY)
        result, sent = self.capture(page, PREVIEW, lambda: button(page, label).click())
        expect(button(page, '预览详细行程')).to_be_enabled(timeout=15000)
        assert result['canApply'] is can_apply and self.snapshot() == before
        assert self.count_requests('POST', APPLY) == count
        assert sent['journeyId'] and sent['revision'] and sent['expectedEntities']
        expect(page.get_by_test_id('journey-segments-preview')).to_be_visible()
        if can_apply:
            expect(button(page, '确认保存详细行程')).to_be_enabled()
        else:
            expect(button(page, '确认保存详细行程')).to_have_count(0)
        return result

    def confirmed(self, page):
        expect(page.get_by_test_id('journey-segments-receipt')).to_be_visible(timeout=15000)
        expect(page.get_by_test_id('journey-segments-unknown')).to_have_count(0)
        expect(button(page, '继续编辑详细行程')).to_be_enabled(timeout=15000)

    def confirm(self, page):
        result, sent = self.capture(page, APPLY, lambda: button(page, '确认保存详细行程').click())
        self.confirmed(page)
        return result, sent

    def nav_lock(self, page):
        page.set_viewport_size({'width': 390, 'height': 844})
        old_url = page.url
        page.get_by_role('tab', name='首页', exact=True).click()
        notice = page.get_by_text('请先保存或放弃行程分段的修改；结果不明时，先核对再离开。', exact=True)
        expect(notice).to_be_visible()
        expect(page.get_by_test_id('journey-segments-panel')).to_be_visible()
        assert page.url == old_url
        # No delay is inserted between dismissing and retriggering this notice.
        button(page, '知道了').click(); button(page, '新建记录').click()
        page.get_by_role('menuitem', name=re.compile(r'(?:^|\s)添加待办$')).click()
        expect(notice).to_be_visible(); expect(field(page, '名称')).to_have_count(0)
        assert page.url == old_url
        button(page, '知道了').click()

    def v1_upgrade(self, browser):
        with self.flow(browser) as (ctx, page):
            original = self.seed(ctx, False); self.open_panel(page, original)
            expect(button(page, '确认保存详细行程')).to_have_count(0)
            field(page, '旅行参考时区').fill('Asia/Shanghai'); field(page, '城市时区：东京').fill('Asia/Tokyo')
            before = self.snapshot(); button(page, '明确升级为详细行程').click()
            expect(button(page, '添加航班')).to_be_enabled(); assert self.snapshot() == before
            self.screenshot(page, 'explicit-upgrade', 390)
            result = self.preview(page); assert result['plan']['segments'][0]['kind'] == 'legacy_day'
            self.confirm(page); after = self.detail(ctx, original)
            assert after['plan']['schemaVersion'] == 2 and after['plan']['segments'][0]['key'] == 'legacy-stable'
            for name in ('budget', 'paid', 'saved', 'memberIds', 'checklist', 'shopping'):
                assert after['plan'][name] == original['plan'][name], name
            assert {row['workflowKey']: row['id'] for row in after['events']} == {row['workflowKey']: row['id'] for row in original['events']}
            assert [row['budget'] for row in after['plan']['shopping']] == [None, 0]
            self.restart(); assert self.detail(ctx, original)['plan'] == after['plan']
            self.screenshot(page, 'upgrade-saved', 390)
            self.passed('Explicit v1 upgrade preserves legacy semantics, stable linked IDs, exact cents, owners and null/zero; real restart retains v2')

    def kinds(self, browser):
        with self.flow(browser) as (ctx, page):
            original = self.seed(ctx); self.open_panel(page, original)
            titles = {row['kind']: row['title'] for row in original['plan']['segments']}
            self.edit(page, original['plan']['segments'][0]['title'])
            field(page, '航班号（可留空）').fill('SYNTHETIC-101'); field(page, '起飞当地时间').fill('2027-10-01T09:30')
            for width in WIDTHS: self.screenshot(page, 'flight-editor', width)
            page.set_viewport_size({'width': 390, 'height': 844})
            button(page, '收起分段编辑').click(); self.edit(page, '东京住宿（虚构）')
            field(page, '住宿名称（可留空）').fill('合成东京住宿更新'); field(page, '入住时间（未知留空）').fill('15:00')
            expect(field(page, '退房时间（未知留空）')).to_have_value('')
            button(page, '收起分段编辑').click(); self.edit(page, '京都一日自由安排（虚构）')
            field(page, '活动结束日期（不含当天）').fill('2027-10-07')
            button(page, '收起分段编辑').click(); self.edit(page, '巴黎散步（虚构）')
            field(page, '活动结束当地时间').fill('2027-10-09T12:00')
            button(page, '收起分段编辑').click(); self.edit(page, titles['legacy_day'])
            field(page, '原日期段结束日期（包含当天）').fill('2027-10-07')
            result = self.preview(page); assert {row['kind'] for row in result['plan']['segments']} == {'flight', 'stay', 'activity', 'legacy_day'}
            stay = next(row for row in result['plan']['segments'] if row['key'] == 'tokyo-stay')
            assert stay['checkInInstant'] and stay['checkOutTime'] == '' and 'checkOutInstant' not in stay
            self.screenshot(page, 'four-kinds-preview', 390); self.confirm(page)
            changed = self.detail(ctx, original)
            assert changed['plan'] == result['plan']
            for name in ('budget', 'saved', 'paid', 'memberIds', 'checklist', 'shopping'):
                assert changed['plan'][name] == original['plan'][name]
            self.passed('Four segment kinds and both activity modes edit through actual fields, preserve unknown hotel clock and nonedited values; four viewport screenshots')

    def dst(self, browser):
        with self.flow(browser) as (ctx, page):
            original = self.seed(ctx); self.open_panel(page, original); self.edit(page, original['plan']['segments'][0]['title'])
            field(page, '起飞当地时间').fill('2026-11-01T01:30'); field(page, '起飞时区').fill('America/New_York')
            field(page, '抵达当地时间').fill('2026-11-01T10:00'); field(page, '抵达时区').fill('America/New_York')
            before = self.snapshot()
            issue, _ = self.capture(page, PREVIEW, lambda: button(page, '预览详细行程').click(), 400)
            expect(page.get_by_test_id('journey-segment-time-issue')).to_be_visible(); assert len(issue['choices']) == 2 and self.snapshot() == before
            self.screenshot(page, 'dst-choice', 390)
            choice = next(item for item in issue['choices'] if item['offsetMinutes'] == -240)
            button(page, '采用 UTC 偏移 -240 分钟').click(); result = self.preview(page)
            assert result['plan']['segments'][0]['departure']['instant'] == choice['instant']
            button(page, '返回修改详细行程').click(); self.edit(page, original['plan']['segments'][0]['title'])
            field(page, '起飞当地时间').fill('2026-03-08T02:30'); field(page, '抵达当地时间').fill('2026-03-08T10:00')
            invalid, _ = self.capture(page, PREVIEW, lambda: button(page, '预览详细行程').click(), 400)
            assert not invalid.get('choices'); expect(button(page, '确认保存详细行程')).to_have_count(0)
            expect(button(page, '预览详细行程')).to_be_enabled(); field(page, '起飞当地时间').fill('2026-03-08T03:30')
            fixed = self.preview(page); self.confirm(page)
            assert self.detail(ctx, original)['plan']['segments'][0]['departure'] == fixed['plan']['segments'][0]['departure']
            self.screenshot(page, 'dst-corrected', 390)
            self.passed('Actual DST overlap requires chosen server offset; nonexistent local time rejects without writes; explicit correction normalizes and saves')

    def removal(self, browser):
        with self.flow(browser) as (ctx, page):
            original = self.seed(ctx); self.open_panel(page, original)
            first = original['plan']['segments'][0]; detached = original['plan']['segments'][2]
            self.edit(page, first['title']); radio(page, '人工标记取消').click(); button(page, '收起分段编辑').click()
            button(page, '移出分段：' + detached['title']).click(); button(page, '确认移出草稿').click()
            result = self.preview(page); assert result['summary']['detach'] == 1
            self.screenshot(page, 'cancel-and-detach', 390); self.confirm(page); after = self.detail(ctx, original)
            old = {row['workflowKey']: row for row in original['events']}; now = {row['workflowKey']: row for row in after['events']}
            assert now['segment:' + first['key']]['id'] == old['segment:' + first['key']]['id']
            assert now['segment:' + first['key']]['title'].startswith('[已取消] ')
            standalone = next(row for row in self.get(ctx, '/api/state')['events'] if row['id'] == old['segment:' + detached['key']]['id'])
            assert not standalone.get('journeyId') and standalone['title'] == old['segment:' + detached['key']]['title']
            self.passed('Manual cancellation preserves stable event; explicit removal detaches and retains standalone history, with no remote cancellation')

    def conflict(self, browser):
        with self.flow(browser) as (ctx, page):
            original = self.seed(ctx); segment = original['plan']['segments'][0]
            event = next(row for row in original['events'] if row['workflowKey'] == 'segment:' + segment['key'])
            self.write(ctx, 'PATCH', '/api/items/events/' + event['id'], dict(revision=event['revision'], title='合成日历独立标题', owner='member2'))
            self.open_panel(page, original); self.edit(page, segment['title']); field(page, '分段标题').fill('合成本页冲突标题')
            result = self.preview(page, False); assert any(row['fieldGroup'] == 'owner' for row in result['summary']['preserved'])
            radio(page, '保留当前日程：合成本页冲突标题：标题').click()
            result = self.preview(page, label='按选择重新预览行程')
            assert result['summary']['resolved'][0]['resolution'] == 'current'
            self.screenshot(page, 'resolved-conflict', 390); self.confirm(page)
            current = next(row for row in self.detail(ctx, original)['events'] if row['id'] == event['id'])
            assert current['title'] == '合成日历独立标题' and current['owner'] == 'member2'
            self.passed('Actual three-way event title conflict and independently changed owner are readable; explicit current choice preserves both')

    def entity_cas(self, browser):
        with self.flow(browser) as (ctx, page):
            original = self.seed(ctx); self.open_panel(page, original); self.edit(page, original['plan']['segments'][0]['title'])
            field(page, '分段标题').fill('合成跨快照草稿'); replies = []
            def race(route):
                task = self.detail(ctx, original)['tasks'][0]
                self.write(ctx, 'PATCH', '/api/items/tasks/' + task['id'], dict(revision=task['revision'], title='合成外部准备更新', due='2027-09-25'))
                trip = self.detail(ctx, original)['trip']
                self.write(ctx, 'PATCH', '/api/items/trips/' + trip['id'], dict(revision=trip['revision'], paid=654321))
                response = route.fetch(max_redirects=0); replies.append((response.status, response.json())); route.fulfill(response=response)
            page.route(self.base + PREVIEW, race, times=1); count = self.count_requests('POST', APPLY)
            button(page, '预览详细行程').click(); expect(page.get_by_test_id('journey-segments-conflict')).to_be_visible(timeout=15000)
            assert len(replies) == 1 and replies[0][0] == 409 and replies[0][1]['code'] == 'stale_edit_source'
            expect(field(page, '分段标题')).to_have_value('合成跨快照草稿'); assert self.count_requests('POST', APPLY) == count
            page.unroute(self.base + PREVIEW, race); button(page, '读取最新行程').click()
            expect(button(page, '保留草稿重新核对行程')).to_be_enabled(timeout=15000); button(page, '保留草稿重新核对行程').click()
            result = self.preview(page); assert result['plan']['paid'] == 654321 and result['plan']['checklist'][0]['due'] == '2027-09-25'
            self.screenshot(page, 'source-cas-rebase', 390); self.confirm(page)
            assert self.detail(ctx, original)['plan']['segments'][0]['title'] == '合成跨快照草稿'
            self.passed('Real writes in the detail-to-preview gap trigger expectedEntities 409; explicit rebase keeps segment intent and latest unrelated money/task values')

    def lose(self, page, committed):
        attempts = []; replies = []
        def fault(route):
            attempts.append(route.request.post_data_json)
            if committed:
                response = route.fetch(max_redirects=0); assert response.status == 200; replies.append(response.json())
            route.abort('failed')
        page.route(self.base + APPLY, fault)
        button(page, '确认保存详细行程').click()
        expect(page.get_by_test_id('journey-segments-unknown')).to_be_visible(timeout=15000)
        expect(button(page, '核对行程保存结果')).to_be_enabled(timeout=15000)
        page.unroute(self.base + APPLY, fault); assert len(attempts) == 1 and len(replies) == int(committed)
        return attempts[0], replies[0] if replies else None

    def unknown(self, browser, committed):
        with self.flow(browser) as (ctx, page):
            original = self.seed(ctx); self.open_panel(page, original); self.edit(page, original['plan']['segments'][0]['title'])
            field(page, '分段标题').fill('合成未知结果'); preview = self.preview(page); before = self.snapshot()
            intent, receipt = self.lose(page, committed); assert intent['previewToken'] == preview['previewToken']
            self.nav_lock(page); expect(button(page, '返回旅行')).to_be_disabled()
            count = self.count_requests('POST', APPLY)
            self.screenshot(page, 'unknown-' + str(committed).lower(), 390)
            with page.expect_response(lambda r: urlsplit(r.url).path == OPERATIONS + intent['idempotencyKey']) as readback:
                button(page, '核对行程保存结果').click()
            assert readback.value.status == (200 if committed else 404)
            assert self.count_requests('POST', APPLY) == count
            if committed:
                self.confirmed(page)
            else:
                expect(button(page, '按原行程请求重试')).to_be_enabled(timeout=15000)
                assert self.snapshot() == before
                receipt, sent = self.capture(page, APPLY, lambda: button(page, '按原行程请求重试').click())
                assert sent == intent; self.confirmed(page)
            after = self.snapshot(); replay = self.write(ctx, 'POST', APPLY, intent)
            assert replay['replayed'] and replay['id'] == receipt['id'] and self.snapshot() == after
            assert len(after['journey_actions']) == len(before['journey_actions']) + 1
            assert self.detail(ctx, original)['revision'] == original['revision'] + 1
            self.passed(('Committed response lost' if committed else 'Request dropped before server') + ': locked unknown uses only original key; GET never writes, exact retry/replay changes journey once')

    def saved_read_failure(self, browser):
        with self.flow(browser) as (ctx, page):
            original = self.seed(ctx); self.open_panel(page, original); self.edit(page, original['plan']['segments'][0]['title'])
            field(page, '分段标题').fill('合成已保存但详情断线'); self.preview(page); receipts = []; dropped = []
            def drop(route):
                response = route.fetch(max_redirects=0); assert response.status == 200; dropped.append(response.json()); route.abort('failed')
            def save(route):
                response = route.fetch(max_redirects=0); assert response.status == 200; receipts.append(response.json())
                page.route(self.base + '/api/journeys/' + original['id'], drop, times=1); route.fulfill(response=response)
            page.route(self.base + APPLY, save, times=1); button(page, '确认保存详细行程').click()
            expect(button(page, '读取当前行程')).to_be_enabled(timeout=15000)
            assert len(receipts) == len(dropped) == 1
            expect(page.get_by_test_id('journey-segments-unknown')).to_have_count(0)
            expect(button(page, '确认保存详细行程')).to_have_count(0)
            self.screenshot(page, 'saved-read-failure', 390); count = self.count_requests('POST', APPLY)
            page.unroute(self.base + APPLY, save); page.unroute(self.base + '/api/journeys/' + original['id'], drop)
            button(page, '读取当前行程').click(); self.confirmed(page)
            assert self.count_requests('POST', APPLY) == count
            self.passed('Confirmed save plus lost subsequent real GET retains historical receipt, closes old write controls and recovers current detail without another apply')

    def lifecycle_case(self, browser):
        with self.flow(browser) as (ctx, page):
            original = self.seed(ctx); self.open_panel(page, original); self.edit(page, original['plan']['segments'][0]['title'])
            field(page, '分段标题').fill('合成仅内存草稿'); before = self.snapshot()
            ctx.set_offline(True); expect(field(page, '分段标题')).to_be_hidden()
            ctx.set_offline(False); expect(field(page, '分段标题')).to_have_value('合成仅内存草稿', timeout=15000)
            self.nav_lock(page); visibility(page, True); expect(field(page, '分段标题')).to_be_hidden(); held = []
            def hold(route):
                response = route.fetch(max_redirects=0); assert response.status == 200; held.append((route, response))
            endpoint = self.base + '/api/journeys/' + original['id']; page.route(endpoint, hold, times=1)
            visibility(page, False); self.settle(page, lambda: bool(held)); visibility(page, True)
            held[0][0].fulfill(response=held[0][1]); page.wait_for_timeout(100)
            expect(field(page, '分段标题')).to_be_hidden(); page.unroute(endpoint, hold)
            visibility(page, False); expect(field(page, '分段标题')).to_have_value('合成仅内存草稿', timeout=15000)
            assert self.snapshot() == before
            button(page, '返回旅行').click(); button(page, '放弃修改并返回旅行').click()
            expect(button(page, '行程分段')).to_be_enabled(timeout=15000)
            page.get_by_role('tab', name='首页', exact=True).click(); expect(button(page, '安排首页')).to_be_enabled(timeout=15000)
            self.passed('Real offline and simulated visibility conceal same-identity draft; delayed genuine detail cannot reopen hidden data; explicit discard releases navigation')

    def identity(self, browser):
        with self.flow(browser) as (ctx, page):
            original = self.seed(ctx); self.open_panel(page, original); self.edit(page, original['plan']['segments'][0]['title'])
            field(page, '分段标题').fill('合成旧成员草稿'); before = self.snapshot(); got = []
            def switch_preview(route):
                response = route.fetch(max_redirects=0); assert response.status == 200
                self.login(ctx, 2); got.append(response.json()); route.fulfill(response=response)
            page.route(self.base + PREVIEW, switch_preview, times=1); button(page, '预览详细行程').click()
            self.settle(page, lambda: len(got) == 1); expect(page.get_by_test_id('journey-segments-panel')).to_have_count(0, timeout=15000)
            expect(page.locator('body')).not_to_contain_text('合成旧成员草稿'); assert self.snapshot() == before
            page.unroute(self.base + PREVIEW, switch_preview); self.login(ctx, 1); self.open_panel(page, original)
            self.edit(page, original['plan']['segments'][0]['title']); field(page, '分段标题').fill('合成旧成员已保存'); self.preview(page); applied = []
            def switch_apply(route):
                response = route.fetch(max_redirects=0); assert response.status == 200
                applied.append(route.request.post_data_json); self.login(ctx, 2); route.fulfill(response=response)
            page.route(self.base + APPLY, switch_apply, times=1); button(page, '确认保存详细行程').click()
            self.settle(page, lambda: len(applied) == 1); expect(page.get_by_test_id('journey-segments-panel')).to_have_count(0, timeout=15000)
            expect(page.get_by_test_id('journey-segments-receipt')).to_have_count(0)
            assert self.get(ctx, OPERATIONS + applied[0]['idempotencyKey'], 404)['code'] == 'operation_not_found'
            assert self.detail(ctx, original)['plan']['segments'][0]['title'] == '合成旧成员已保存'
            self.passed('Real member-cookie switch discards late preview and committed response; partner sees legitimate shared trip but cannot read original actor receipt')

    def map_navigation(self, browser):
        with self.flow(browser) as (ctx, page):
            original = self.seed(ctx)
            self.write(ctx, 'POST', '/api/journey-places', dict(requestId=uuid4().hex, name='SEGMENT-MAP', journeyId=original['id'], status='planned', coordinates=dict(latitude=31.23, longitude=121.47)), 201)
            page.goto(self.base + '/app/map'); expect(button(page, '打开地点：SEGMENT-MAP')).to_be_enabled(timeout=15000)
            button(page, '打开地点：SEGMENT-MAP').click(); button(page, '查看旅行').click()
            expect(button(page, '行程分段')).to_be_enabled(); button(page, '行程分段').click()
            expect(field(page, '旅行参考时区')).to_be_enabled(); self.edit(page, original['plan']['segments'][0]['title'])
            field(page, '分段标题').fill('合成地图内草稿'); self.nav_lock(page); self.screenshot(page, 'map-nested', 390)
            assert urlsplit(page.url).path == '/app/map'
            button(page, '返回旅行').click(); button(page, '放弃修改并返回旅行').click()
            back = page.get_by_role('button', name=re.compile(r'(?:^|\s)返回足迹地图$'))
            expect(back).to_be_enabled(); back.click()
            expect(button(page, '打开地点：SEGMENT-MAP')).to_be_enabled(timeout=15000)
            self.passed('Real map-to-linked-trip segment editor holds parent navigation while dirty and returns through saved trip to original map')

    def assistant_navigation(self, browser):
        with self.flow(browser) as (ctx, page):
            page.goto(self.base + '/app/assistant'); expect(field(page, '告诉助理你的需求')).to_be_enabled(timeout=15000)
            field(page, '告诉助理你的需求').fill('旅行名称：合成助理分段旅行\n出发日期：2028-03-02\n返程日期：2028-03-04\n目的地：上海\n预算：1000元')
            expect(page.get_by_role('checkbox', name='使用已配置的 AI 整理', exact=True)).not_to_be_checked()
            button(page, '整理并预览').click(); expect(page.get_by_test_id('journey-brief-form')).to_be_visible()
            for name, value in [('旅行名称', '合成助理分段旅行'), ('出发日期', '2028-03-02'), ('返程日期', '2028-03-04'), ('旅行总预算（元）', '1000'), ('国家或地区 1', '中国'), ('城市 1', '上海'), ('抵达日期 1', '2028-03-02'), ('离开日期 1', '2028-03-04')]:
                field(page, name).fill(value)
            radio(page, '国内旅行').click(); person = self.get(ctx, '/api/state')['people'][0]
            selected = page.get_by_role('checkbox', name='出行成员：' + person['name'], exact=True)
            if selected.get_attribute('aria-checked') != 'true': selected.click()
            button(page, '核对并继续编辑').click(); expect(button(page, '预览变更')).to_be_enabled()
            button(page, '预览变更').click(); expect(button(page, '确认保存旅行')).to_be_enabled(); button(page, '确认保存旅行').click()
            expect(button(page, '行程分段')).to_be_enabled(timeout=15000); button(page, '行程分段').click()
            expect(field(page, '旅行参考时区')).to_be_enabled(); field(page, '旅行参考时区').fill('Asia/Shanghai')
            field(page, '城市时区：上海').fill('Asia/Shanghai'); button(page, '明确升级为详细行程').click()
            self.nav_lock(page); assert urlsplit(page.url).path == '/app/assistant'; self.screenshot(page, 'assistant-nested', 390)
            button(page, '返回旅行').click(); button(page, '放弃修改并返回旅行').click()
            expect(button(page, '行程分段')).to_be_enabled(); button(page, '返回助理').click()
            expect(field(page, '告诉助理你的需求')).to_be_enabled(timeout=15000)
            self.passed('Assistant local parser creates a real trip and opens nested explicit upgrade; dirty lock and explicit return work without invoking AI or cloud')

    def pagination(self, browser):
        with self.flow(browser) as (ctx, page):
            original = self.seed(ctx); plan = copy.deepcopy(original['plan']); sample = plan['destinations'][0]
            plan['destinations'] = [{**sample, 'key': 'city-' + str(i), 'city': '合成城市' + str(i)} for i in range(20)]
            plan['segments'] = [dict(key='segment-' + str(i), kind='legacy_day', title='合成分页分段' + str(i), start='2027-10-01', end='2027-10-01') for i in range(100)]
            preview = self.write(ctx, 'POST', PREVIEW, dict(plan=plan, journeyId=original['id'], revision=original['revision'], expectedEntities=versions(original)))
            self.write(ctx, 'POST', APPLY, dict(previewToken=preview['previewToken'], idempotencyKey=uuid4().hex)); self.open_panel(page, original)
            expect(button(page, '添加航班')).to_be_disabled()
            for _ in range(19): button(page, '分段下一页').click()
            button(page, '编辑分段：合成分页分段99').click(); field(page, '分段标题').fill('合成最后一段更新')
            radio(page, '编辑城市').click(); expect(button(page, '添加城市')).to_be_disabled()
            for _ in range(3): button(page, '城市下一页').click()
            button(page, '编辑城市：合成城市19').click(); field(page, '城市名称').fill('合成最后城市更新')
            result = self.preview(page); assert len(result['plan']['segments']) == 100 and len(result['plan']['destinations']) == 20
            for _ in range(19): button(page, '预览分段下一页').click()
            expect(page.get_by_test_id('journey-segments-preview')).to_contain_text('合成最后一段更新')
            for _ in range(3): button(page, '预览城市下一页').click()
            expect(page.get_by_test_id('journey-segments-preview')).to_contain_text('合成最后城市更新')
            self.screenshot(page, 'capacity-last-page', 320); self.confirm(page)
            after = self.detail(ctx, original); assert after['plan']['segments'][-1]['title'] == '合成最后一段更新'
            self.passed('Actual 20 cities and 100 segments remain accessible through edit/preview pagination; capacity prevents additions and final-page edits persist')

    def nonedited_guard(self, browser):
        with self.flow(browser) as (ctx, page):
            for index, mode in enumerate(('clear_due', 'delete', 'relink')):
                original = self.seed(ctx, title='合成保全检查' + str(index)); task = original['tasks'][0]
                if mode == 'delete': self.write(ctx, 'DELETE', '/api/items/tasks/' + task['id'], dict(revision=task['revision']))
                else: self.write(ctx, 'PATCH', '/api/items/tasks/' + task['id'], dict(revision=task['revision'], **({'due': ''} if mode == 'clear_due' else {'tripId': ''})))
                before = self.snapshot(); page.goto(self.base + '/app/trips?request=1001&item=' + original['tripId'])
                expect(button(page, '行程分段')).to_be_enabled(timeout=15000); button(page, '行程分段').click()
                expect(page.locator('body')).to_contain_text('请先核对旅行清单，再编辑详细行程', timeout=15000)
                expect(button(page, '确认保存详细行程')).to_have_count(0); assert self.snapshot() == before
                if index == 2: self.screenshot(page, 'nonedited-link-guard', 390)
            self.passed('Real separately cleared deadline, deleted task and cleared trip association fail closed with specific guidance; no stale plan value is restored')

    @classmethod
    def run_scenarios(cls, root, bundle, report, out, browser):
        cases = [('v1_upgrade', ()), ('kinds', ()), ('dst', ()), ('removal', ()), ('conflict', ()), ('entity_cas', ()),
                 ('unknown', (True,)), ('unknown', (False,)), ('saved_read_failure', ()), ('lifecycle_case', ()),
                 ('identity', ()), ('map_navigation', ()), ('assistant_navigation', ()), ('pagination', ()), ('nonedited_guard', ())]
        assert len(cases) == CHECKS
        for index, (method, args) in enumerate(cases):
            name = f'{index + 1:02d}-{method}'; case_out = out / name; case_out.mkdir()
            folder = None; checks = len(report['checks']); errors = len(report['pageErrors']); network = len(report['externalRequests'])
            result = dict(name=name, passed=False, temporaryFixtureRemoved=False)
            try:
                with ExitStack() as lifecycle:
                    folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='expo-segments-')))
                    run = cls(root, bundle, folder, report, case_out, lifecycle)
                    getattr(run, method)(browser, *args)
                assert not folder.exists() and len(report['checks']) == checks + 1
                assert len(report['pageErrors']) == errors and len(report['externalRequests']) == network
                result['passed'] = True
            except Exception:
                del report['checks'][checks:]
                failure = traceback.format_exc(); (case_out / 'failure.txt').write_text(failure, encoding='utf-8')
                report['scenarioFailures'].append(dict(scenario=name, traceback=failure, artifacts=name))
                print('FAIL ' + name + '\n' + failure, flush=True)
            finally:
                result['temporaryFixtureRemoved'] = folder is not None and not folder.exists()
                report['scenarioResults'].append(result)
        assert not report['scenarioFailures'], 'See all independent case results and preserved failure artifacts'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--expected-build-evidence', required=True)
    args = parser.parse_args(); root, bundle = args.source_root.resolve(), args.bundle.resolve()
    git = lambda *values: subprocess.check_output(['git', *values], cwd=root, text=True).strip()
    head = git('rev-parse', 'HEAD'); assert head == args.expected_head
    evidence_path = bundle.parent / 'build-evidence.json'; assert sha(evidence_path) == args.expected_build_evidence
    evidence = json.loads(evidence_path.read_text(encoding='utf-8')); assert evidence['sourceHead'] == head and evidence['sourceTree'] == git('rev-parse', 'HEAD^{tree}')
    assert not git('status', '--porcelain=v1', '--untracked-files=no')
    names = git('ls-files').splitlines(); hashes = lambda: {name: sha(root / name) for name in names}
    exports = lambda: {p.relative_to(bundle).as_posix(): sha(p) for p in bundle.rglob('*') if p.is_file()}
    assert exports() == evidence['files'] and len(evidence['files']) == 23
    assert all(sha(root / name) == digest for name, digest in evidence['inputFiles'].items())
    assert sha(Path(__file__)) == sha(root / 'tests/browser_expo_segments_check.py')
    out = Path(__file__).resolve().parents[1] / 'test-results' / ('expo-segments-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True); shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], screenshots=[], scenarioResults=[], scenarioFailures=[], head=head, tree=evidence['sourceTree'],
                  buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(out / 'executed-harness.py'), sourceHashesBefore=hashes(), bundleHashesBefore=exports(),
                  productionWrites=0, realCloud=False, realAI=False, physicalTelevision=False,
                  scope='Isolated real Flask/SQLite/Edge and synthetic plans. No successful response mock or real cloud/AI. Visibility events simulated; screenshots cover current scroll regions, not physical devices.')
    connect = socket.socket.connect
    def local_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
            report['externalRequests'].append({'kind': 'non-loopback socket'}); raise AssertionError('External network forbidden')
        return connect(sock, address)
    try:
        with patch.object(socket.socket, 'connect', local_connect), sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            try:
                Run.run_scenarios(root, bundle, report, out, browser)
                assert len(report['checks']) == CHECKS and len(report['screenshots']) == SCREENSHOTS
                assert not report['pageErrors'] and not report['externalRequests']; report['passed'] = True
            finally:
                browser.close()
    except Exception:
        report['passed'] = False; report['failure'] = traceback.format_exc(); print(report['failure'], flush=True)
    finally:
        report['sourceHashesAfter'] = hashes(); report['bundleHashesAfter'] = exports()
        report['sourceUnchanged'] = report['sourceHashesBefore'] == report['sourceHashesAfter']
        report['bundleUnchanged'] = report['bundleHashesBefore'] == report['bundleHashesAfter']
        report['cleanAfter'] = not git('status', '--porcelain=v1', '--untracked-files=no')
        report['headUnchanged'] = head == git('rev-parse', 'HEAD') and evidence['sourceTree'] == git('rev-parse', 'HEAD^{tree}')
        report['temporaryFixtureRemoved'] = len(report['scenarioResults']) == CHECKS and all(case['temporaryFixtureRemoved'] for case in report['scenarioResults'])
        report['passed'] = report['passed'] and all(report[key] for key in ('sourceUnchanged', 'bundleUnchanged', 'cleanAfter', 'headUnchanged', 'temporaryFixtureRemoved'))
        (out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(dict(passed=report['passed'], checks=len(report['checks']), report=str(out / 'result.json')), ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    raise SystemExit(main())
