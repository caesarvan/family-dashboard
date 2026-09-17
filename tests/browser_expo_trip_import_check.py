"""Frozen Expo trip import: real isolated Flask/SQLite/HTTPS/Edge acceptance.

Only synthetic JSON is used. Transport faults discard/delay real responses;
no successful business DTO is mocked. Run after source review and frozen build.
"""
import argparse
from contextlib import ExitStack, closing, contextmanager
from copy import deepcopy
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

from itsdangerous import TimestampSigner
from playwright.sync_api import expect, sync_playwright
import browser_expo_finance_check as fixture
from browser_expo_finance_check import Run as BaseRun, button, sha, visibility

PREVIEW = '/api/journeys/preview'
APPLY = '/api/journeys/apply'
OPERATIONS = '/api/journeys/operations/'
CHECKS = 12
WIDTHS = (320, 390, 1280, 1920)
TITLE = '合成导入旅行：东京京都巴黎，日期和预算均待本人核对'
LONG = '合成长名称：与家人一起安排东京京都巴黎的城市停留、航班和住宿，所有班次时间仅为虚构格式示例，需要本人逐项核对后明确保存'


class Run(BaseRun):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        assert Path(self.source.__file__).resolve() == (self.root / 'app.py').resolve()
        files = [(Path(__file__), 'tests/browser_expo_trip_import_check.py'),
                 (Path(fixture.__file__), 'tests/browser_expo_finance_check.py')]
        files += [(Path(sys.modules[name].__file__), 'tests/' + name + '.py')
                  for name in ('test_financial_files', 'test_app')]
        files += [(self.root / f'static/examples/journey-plan-v{v}.json',
                   f'static/examples/journey-plan-v{v}.json') for v in (1, 2)]
        for actual, name in files:
            digest = sha(actual)
            assert digest == sha(self.root / name), name
            previous = self.report.setdefault('fixtureHashes', {}).get(name)
            assert previous is None or previous == digest
            self.report['fixtureHashes'][name] = digest

    def clear_finance(self):
        pass  # Every scenario owns a fresh DB; never reset another scenario.

    def snapshot(self):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database)) as con:
            names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            return {name: sorted(con.execute('SELECT * FROM "' + name + '"').fetchall(), key=repr)
                    for name in names if name not in {'users', 'member_sessions', 'member_session_browsers', 'attempts'}}

    def plan(self, version=1, title=TITLE):
        plan = json.loads((self.root / f'static/examples/journey-plan-v{version}.json').read_text(encoding='utf-8'))
        plan.update(title=title, memberIds=['member1', 'member2'], budget=1234567, saved=23456, paid=7890)
        plan['checklist'][0]['owner'] = 'member1'
        plan['shopping'][0].update(owner='member2', budget=0)
        plan['shopping'][1].update(owner='shared', budget=None)
        return plan

    @staticmethod
    def field(page):
        return page.get_by_role('textbox', name='旅行 JSON', exact=True)

    def ready(self, page):
        expect(page.get_by_test_id('trip-import-panel')).to_be_visible(timeout=15000)
        expect(self.field(page)).to_be_editable(timeout=15000)
        expect(button(page, '选择 JSON 文件')).to_be_enabled(timeout=15000)

    def open_import(self, page):
        page.goto(self.base + '/app/trips')
        expect(button(page, '导入旅行')).to_be_enabled(timeout=15000)
        button(page, '导入旅行').click(); self.ready(page)

    def paste(self, page, plan):
        expect(self.field(page)).to_be_editable(timeout=15000)
        self.field(page).fill(plan if isinstance(plan, str) else json.dumps(plan, ensure_ascii=False))

    def choose_file(self, page, raw, name='合成旅行.json'):
        with page.expect_file_chooser() as chosen:
            button(page, '选择 JSON 文件').click()
        chosen.value.set_files({'name': name, 'mimeType': 'application/json', 'buffer': raw})

    def post(self, page, path, action, expected=200, drop=False, unsent=False):
        captured = []; url = self.base + path
        def forward(route):
            assert route.request.method == 'POST' and route.request.url == url
            body = route.request.post_data_json
            if unsent:
                route.abort('failed'); captured.append(dict(body=body, status=None, result=None)); return
            response = route.fetch(max_redirects=0); raw = response.body(); result = json.loads(raw)
            if drop: route.abort('failed')
            else: route.fulfill(status=response.status, headers=response.headers, body=raw)
            captured.append(dict(body=body, status=response.status, result=result))
        page.route(url, forward)
        try:
            action(); self.settle(page, lambda: len(captured) == 1)
            assert len(captured) == 1 and captured[0]['status'] == (None if unsent else expected), captured
            return captured[0]
        finally:
            page.unroute(url, forward)

    def preview(self, page):
        before = self.snapshot()
        packet = self.post(page, PREVIEW, lambda: button(page, '预览导入').click())
        assert set(packet['body']) == {'plan'} and self.snapshot() == before
        result = packet['result']; assert result['canApply'] and result['previewToken'] and result['expiresIn'] == 1800
        expect(page.get_by_test_id('trip-import-preview')).to_be_visible(timeout=15000)
        expect(button(page, '确认创建旅行')).to_be_enabled(timeout=15000)
        return result, packet['body']['plan']

    def modify(self, page):
        button(page, '修改输入').click(); self.ready(page)
        expect(page.get_by_test_id('trip-import-preview')).to_have_count(0)

    def confirm(self, page, **fault):
        packet = self.post(page, APPLY, lambda: button(page, '确认创建旅行').click(), expected=fault.pop('expected', 201), **fault)
        assert set(packet['body']) == {'previewToken', 'idempotencyKey'}
        assert re.fullmatch(r'[A-Za-z0-9_-]{8,80}', packet['body']['idempotencyKey'])
        return packet

    def current_ready(self, page, title):
        expect(page.get_by_test_id('trip-import-panel')).to_have_count(0, timeout=15000)
        expect(button(page, '行程分段')).to_be_enabled(timeout=15000)
        expect(page.locator('body')).to_contain_text(title)

    def unknown_ready(self, page, key):
        expect(page.get_by_test_id('trip-import-unknown')).to_contain_text(key, timeout=15000)
        expect(button(page, '核对保存结果')).to_be_enabled(timeout=15000)
        expect(button(page, '确认创建旅行')).to_have_count(0)

    @contextmanager
    def lost_receipt_reads(self, page):
        seen = []; pattern = self.base + OPERATIONS + '*'
        def discard(route):
            assert route.request.method == 'GET'
            response = route.fetch(max_redirects=0); raw = response.body()
            assert response.status in (200, 404), (response.status, raw)
            route.abort('failed'); seen.append((response.status, json.loads(raw)))
        page.route(pattern, discard)
        try: yield seen
        finally: page.unroute(pattern, discard)

    def persisted(self, ctx, packet, preview):
        result = packet['result']; assert result['replayed'] is False and result['revision'] == 1
        detail = self.get(ctx, '/api/journeys/' + result['id'])
        assert detail['plan'] == preview['plan'] and detail['tripId'] == result['tripId']
        assert detail['trip']['budget'] == preview['plan']['budget']
        assert len(detail['tasks']) == len(preview['plan']['checklist'])
        assert len(detail['shopping']) == len(preview['plan']['shopping'])
        assert len(detail['events']) == len(preview['plan']['segments']) + 1
        assert detail['calendar']['cloud'] == 'not_requested'
        with closing(sqlite3.connect(self.database)) as con:
            stored = con.execute('SELECT plan FROM journey_workflows WHERE id=?', (result['id'],)).fetchone()
            assert json.loads(stored[0]) == detail['plan']
            assert con.execute('SELECT count(*) FROM journey_links WHERE journey_id=?', (result['id'],)).fetchone()[0] == 1 + len(detail['tasks']) + len(detail['shopping']) + len(detail['events'])
        receipt = self.get(ctx, OPERATIONS + packet['body']['idempotencyKey'])
        assert receipt['found'] and receipt['result']['id'] == result['id'] and 'replayed' not in receipt['result']
        return detail

    def v1_defaults_file_restart(self, browser):
        with self.flow(browser) as (ctx, page):
            self.open_import(page); original = self.plan()
            for key in ('schemaVersion', 'memberIds', 'checklist', 'segments'): original.pop(key)
            raw = '\ufeff' + json.dumps({'plan': original}, ensure_ascii=False)
            self.choose_file(page, raw.encode('utf-8'))
            expect(self.field(page)).to_have_value(re.compile('合成导入旅行'))
            preview, sent = self.preview(page)
            assert all(key not in sent for key in ('schemaVersion', 'memberIds', 'checklist', 'segments'))
            assert preview['plan']['checklist'] and len(preview['plan']['segments']) == 3
            packet = self.confirm(page); self.current_ready(page, TITLE); detail = self.persisted(ctx, packet, preview)
            snapshot = self.snapshot(); self.restart(); page.reload()
            expect(page.locator('body')).to_contain_text(TITLE, timeout=15000)
            assert self.get(ctx, '/api/journeys/' + detail['id']) == detail and self.snapshot() == snapshot
            self.open_import(page); empty = self.plan(title='合成显式空清单')
            empty.update(checklist=[], shopping=[], segments=[]); self.paste(page, empty)
            preview2, sent2 = self.preview(page); assert sent2['checklist'] == sent2['segments'] == []
            packet2 = self.confirm(page); self.current_ready(page, empty['title'])
            detail2 = self.persisted(ctx, packet2, preview2)
            assert not detail2['tasks'] and not detail2['shopping'] and len(detail2['events']) == 1
            self.passed('Real BOM v1 file preserves omitted defaults; explicit empty arrays create no checklist or segment extras; actual links and plan survive server restart')

    def v2_paste_full_detail(self, browser):
        with self.flow(browser) as (ctx, page):
            self.open_import(page); original = self.plan(2)
            original['segments'][0]['bookingState'] = 'booked'
            original['segments'][-1]['bookingState'] = 'cancelled'
            self.choose_file(page, json.dumps(original, ensure_ascii=False).encode(), '合成详细行程.json')
            file_preview, file_sent = self.preview(page); assert file_sent == original
            self.modify(page); self.paste(page, original)
            preview, sent = self.preview(page); assert sent == original
            assert preview['plan'] == file_preview['plan']
            button(page, '展开目的地').click(); button(page, '展开行程分段').click(); button(page, '展开采购').click()
            for text in ('Asia/Tokyo', 'Europe/Paris', 'PVG', 'HND'):
                expect(page.get_by_test_id('trip-import-preview')).to_contain_text(text)
            expect(page.get_by_test_id('trip-import-preview')).to_contain_text('预算未知')
            expect(page.get_by_test_id('trip-import-preview')).to_contain_text('预算：¥0.00')
            expect(page.get_by_test_id('trip-import-preview')).to_contain_text('时刻未知')
            expect(page.get_by_test_id('trip-import-preview')).to_contain_text('人工标记已预订')
            button(page, '行程分段下一页').click()
            expect(page.get_by_test_id('trip-import-preview')).to_contain_text(original['segments'][-1]['title'])
            expect(page.get_by_test_id('trip-import-preview')).to_contain_text('人工标记已取消')
            packet = self.confirm(page); self.current_ready(page, TITLE); detail = self.persisted(ctx, packet, preview)
            purchases = {r['workflowKey']: r for r in detail['shopping']}
            assert purchases['shopping:adapter']['budget'] == 0 and purchases['shopping:organizer']['budget'] is None
            assert detail['budget']['unknownPurchaseBudgets'] == 1 and detail['budget']['total'] == 1234567
            assert {s['kind'] for s in detail['plan']['segments']} == {'flight', 'stay', 'activity', 'legacy_day'}
            stay = next(s for s in detail['plan']['segments'] if s['kind'] == 'stay')
            assert stay['checkInTime'] == stay['checkOutTime'] == '' and 'checkInInstant' not in stay
            assert next(t for t in detail['tasks'] if t['workflowKey'] == 'task:budget-review')['owner'] == 'member1'
            assert purchases['shopping:adapter']['owner'] == 'member2'
            assert not self.snapshot()['calendar_publications'] and not self.snapshot()['hub_transactions']
            button(page, '行程分段').click(); expect(page.get_by_test_id('journey-segments-panel')).to_be_visible(timeout=15000)
            self.passed('Pasted real v2 preserves local zones, unknown stay clocks, all-day boundaries, booking states, exact cents and null/zero; saved trip opens existing segment editor')

    def invalid_and_dst(self, browser):
        with self.flow(browser) as (ctx, page):
            self.open_import(page); before = self.snapshot(); posts = self.count_requests('POST', PREVIEW)
            for raw, error in (('', None), ('{invalid', '有效的 JSON'), ('界' * 66667, '200,000'),
                (json.dumps({'plan': self.plan(), 'journeyId': '0' * 24}), '仅支持新建旅行，请移除已有旅行编号、版本、令牌或操作选项'),
                (json.dumps({'plan': self.plan(), 'previewToken': 'forbidden'}), '仅支持新建旅行，请移除已有旅行编号、版本、令牌或操作选项')):
                self.paste(page, raw)
                if button(page, '预览导入').is_enabled(): button(page, '预览导入').click()
                if error: expect(page.get_by_role('alert')).to_contain_text(error)
                expect(page.get_by_test_id('trip-import-preview')).to_have_count(0)
            for raw, name, error in ((b'', 'empty.json', '非空'), (b' ' * 200001, 'oversize.json', '200,000'),
                                     (b'\xff\xfeinvalid', 'invalid-utf8.json', 'UTF-8')):
                self.choose_file(page, raw, name); expect(page.get_by_role('alert')).to_contain_text(error)
                expect(button(page, '选择 JSON 文件')).to_be_enabled()
            assert self.count_requests('POST', PREVIEW) == posts and self.snapshot() == before
            bad = self.plan(); bad['memberIds'] = ['outsider']; self.paste(page, bad)
            error = self.post(page, PREVIEW, lambda: button(page, '预览导入').click(), expected=400)
            assert error['result']['error'] and self.snapshot() == before
            plan = self.plan(2); flight = plan['segments'][0]
            flight['departure'].update(local='2026-11-01T01:30:00', timeZone='America/New_York')
            flight['arrival'].update(local='2026-11-01T10:00:00', timeZone='America/New_York')
            self.paste(page, plan)
            issue = self.post(page, PREVIEW, lambda: button(page, '预览导入').click(), expected=400)['result']
            assert len(issue['choices']) == 2 and issue['field'] and self.snapshot() == before
            expect(page.locator('body')).to_contain_text(issue['field'])
            expect(button(page, '确认创建旅行')).to_have_count(0)
            assert json.loads(self.field(page).input_value()) == plan, 'DST silently rewrote the input'
            selected = next(x for x in issue['choices'] if x['offsetMinutes'] == -240)
            flight['departure']['offsetMinutes'] = selected['offsetMinutes']; self.paste(page, plan)
            preview, _ = self.preview(page)
            assert preview['plan']['segments'][0]['departure']['instant'] == selected['instant']
            self.modify(page); flight['departure'].pop('offsetMinutes'); flight['departure']['local'] = '2026-03-08T02:30:00'
            flight['arrival']['local'] = '2026-03-08T10:00:00'; self.paste(page, plan)
            missing = self.post(page, PREVIEW, lambda: button(page, '预览导入').click(), expected=400)['result']
            assert not missing.get('choices') and self.snapshot() == before
            self.passed('Malformed/oversized/invalid-UTF8 and context-bearing imports never preview; real invalid-member and DST errors preserve raw input and write nothing; only explicit server-offset correction normalizes')

    def committed_get_recovery(self, browser):
        with self.flow(browser) as (ctx, page):
            self.open_import(page); self.paste(page, self.plan()); preview, _ = self.preview(page)
            packet = self.confirm(page, drop=True); key = packet['body']['idempotencyKey']; self.unknown_ready(page, key)
            detail = self.persisted(ctx, packet, preview); saved = self.snapshot()
            with self.lost_receipt_reads(page) as reads:
                button(page, '核对保存结果').click(); self.settle(page, lambda: len(reads) == 1)
                self.unknown_ready(page, key); assert reads[0][0] == 200
            button(page, '核对保存结果').click(); self.current_ready(page, TITLE)
            assert self.snapshot() == saved and self.count_requests('POST', APPLY) == 1
            assert self.get(ctx, '/api/journeys/' + detail['id']) == detail
            self.passed('Real apply commits before its response is lost; lost genuine receipt GET keeps unknown; explicit second GET recovers current trip without another apply')

    def original_retry(self, browser):
        with self.flow(browser) as (ctx, page):
            self.open_import(page); self.paste(page, self.plan()); preview, _ = self.preview(page)
            packet = self.post(page, APPLY, lambda: button(page, '确认创建旅行').dblclick(), expected=201, drop=True)
            key = packet['body']['idempotencyKey']; self.unknown_ready(page, key); saved = self.snapshot()
            with self.lost_receipt_reads(page) as reads:
                button(page, '核对保存结果').click(); self.settle(page, lambda: len(reads) == 1)
                expect(button(page, '按原请求重试')).to_be_enabled(timeout=15000)
            replay = self.post(page, APPLY, lambda: button(page, '按原请求重试').click())
            assert replay['body'] == packet['body'] and replay['result']['replayed'] is True
            assert replay['result']['id'] == packet['result']['id'] and self.snapshot() == saved
            self.current_ready(page, TITLE); assert self.count_requests('POST', APPLY) == 2
            assert len(saved['journey_workflows']) == len(saved['journey_actions']) == 1
            self.passed('Double-click produces one initial real apply; after failed GET explicit retry uses identical token/key and historical 200, never duplicates workflow or entities')

    def unsent_404_explicit_end(self, browser):
        with self.flow(browser) as (ctx, page):
            self.open_import(page); self.paste(page, self.plan()); self.preview(page); before = self.snapshot()
            packet = self.confirm(page, unsent=True); key = packet['body']['idempotencyKey']; self.unknown_ready(page, key)
            old_url = page.url; page.get_by_role('tab', name='首页', exact=True).click()
            self.unknown_ready(page, key); assert page.url == old_url
            if button(page, '知道了').count(): button(page, '知道了').click()
            button(page, '返回旅行计划').click(); self.unknown_ready(page, key)
            assert self.get(ctx, OPERATIONS + key, 404)['code'] == 'operation_not_found'
            button(page, '核对保存结果').click(); expect(button(page, '结束本次核对')).to_be_enabled(timeout=15000)
            expect(page.locator('body')).to_contain_text('原请求仍可能完成')
            self.unknown_ready(page, key); assert self.snapshot() == before and self.count_requests('POST', APPLY) == 1
            button(page, '结束本次核对').click(); expect(page.get_by_role('heading', name='结束本次核对？', exact=True)).to_be_visible()
            expect(page.locator('body')).to_contain_text(key)
            button(page, '结束核对并清空输入').click(); self.ready(page); expect(self.field(page)).to_have_value('')
            expect(page.locator('body')).to_contain_text(key)
            assert self.snapshot() == before and self.count_requests('POST', APPLY) == 1
            self.paste(page, self.plan(title='合成明确另建旅行')); self.preview(page); fresh = self.confirm(page)
            assert fresh['body']['idempotencyKey'] != key; self.current_ready(page, '合成明确另建旅行')
            assert len(self.snapshot()['journey_workflows']) == 1
            self.passed('Unsent apply and real receipt 404 stay unknown; fresh read plus second explicit end decision clear input without writes; only independent new preview/confirm creates a trip')

    def expiry_and_new_session_receipt(self, browser):
        with self.flow(browser) as (ctx, page), ExitStack() as extra:
            self.open_import(page); self.paste(page, self.plan()); self.preview(page); before = self.snapshot()
            clock = TimestampSigner.get_timestamp
            with patch.object(TimestampSigner, 'get_timestamp', lambda signer: clock(signer) + 1801):
                rejected = self.confirm(page, expected=409)
            assert rejected['result']['error'] == '预览已过期，请重新预览' and self.snapshot() == before
            expect(page.get_by_test_id('trip-import-unknown')).to_have_count(0)
            if button(page, '修改输入').count(): self.modify(page)
            self.paste(page, self.plan()); self.preview(page); packet = self.confirm(page, drop=True)
            key = packet['body']['idempotencyKey']; self.unknown_ready(page, key); saved = self.snapshot()
            with self.lost_receipt_reads(page) as reads:
                button(page, '核对保存结果').click(); self.settle(page, lambda: len(reads) == 1)
                expect(button(page, '按原请求重试')).to_be_enabled(timeout=15000)
            newer = self.context(browser); extra.callback(newer.close)
            assert self.get(newer, OPERATIONS + key)['result']['id'] == packet['result']['id']
            newer_page = newer.new_page(); self.open_import(newer_page)
            newer_page.get_by_role('textbox', name='原操作编号', exact=True).fill(key)
            button(newer_page, '查询原操作').click(); self.unknown_ready(newer_page, key)
            expect(button(newer_page, '按原请求重试')).to_have_count(0)
            with patch.object(TimestampSigner, 'get_timestamp', lambda signer: clock(signer) + 1801):
                # Existing ABI checks expiry before ordinary apply replay, even after commit.
                refused = self.post(page, APPLY, lambda: button(page, '按原请求重试').click(), expected=409)
                assert refused['body'] == packet['body'] and refused['result']['error'] == '预览已过期，请重新预览'
                self.unknown_ready(page, key); assert self.snapshot() == saved
                button(newer_page, '核对保存结果').click(); self.current_ready(newer_page, TITLE)
                button(page, '核对保存结果').click(); self.current_ready(page, TITLE)
            assert self.snapshot() == saved and self.count_requests('POST', APPLY) == 3
            self.passed('Unwritten expired preview rejects with zero writes; committed expired apply still 409, but original-key GET recovers history for a new genuine member session and UI without re-creation')

    def saved_detail_failure(self, browser):
        with self.flow(browser) as (ctx, page):
            pattern = re.compile(re.escape(self.base) + r'/api/journeys/[a-f0-9]{24}$')
            # Distinguish the child fresh read from the parent's independent second read.
            for fail_at in (1, 2):
                self.open_import(page); title = f'合成第{fail_at}次详情读取失败'
                self.paste(page, self.plan(title=title)); preview, _ = self.preview(page); reads = []
                def lose_detail(route):
                    response = route.fetch(max_redirects=0); raw = response.body(); assert response.status == 200
                    reads.append(json.loads(raw))
                    if len(reads) == fail_at: route.abort('failed')
                    else: route.fulfill(status=response.status, headers=response.headers, body=raw)
                page.route(pattern, lose_detail)
                try:
                    packet = self.confirm(page)
                    expect(page.get_by_test_id('trip-import-saved')).to_be_visible(timeout=15000)
                    expect(button(page, '重新读取旅行')).to_be_enabled(timeout=15000)
                    assert len(reads) == fail_at and all(d['id'] == packet['result']['id'] for d in reads)
                    expect(button(page, '确认创建旅行')).to_have_count(0)
                    expect(page.get_by_test_id('trip-import-preview')).to_have_count(0)
                finally: page.unroute(pattern, lose_detail)
                saved = self.snapshot(); writes = self.count_requests('POST', APPLY)
                button(page, '重新读取旅行').click(); self.current_ready(page, title); self.persisted(ctx, packet, preview)
                assert self.snapshot() == saved and self.count_requests('POST', APPLY) == writes
            self.open_import(page); self.paste(page, self.plan(title='合成父读取途中隐藏')); self.preview(page)
            reads = []; held = []
            def hold_parent(route):
                response = route.fetch(max_redirects=0); raw = response.body(); assert response.status == 200
                reads.append(json.loads(raw))
                if len(reads) == 2: held.append((route, response.status, response.headers, raw))
                else: route.fulfill(status=response.status, headers=response.headers, body=raw)
            page.route(pattern, hold_parent)
            try:
                self.confirm(page); self.settle(page, lambda: len(held) == 1)
                saved = self.snapshot(); writes = self.count_requests('POST', APPLY)
                visibility(page, True); expect(page.get_by_test_id('trip-import-saved')).to_have_count(0)
                route, status, headers, raw = held[0]; route.fulfill(status=status, headers=headers, body=raw)
                expect(button(page, '行程分段')).to_have_count(0)
                visibility(page, False)
                expect(button(page, '重新读取旅行')).to_be_enabled(timeout=15000)
                expect(button(page, '行程分段')).to_have_count(0)
            finally: page.unroute(pattern, hold_parent)
            button(page, '重新读取旅行').click(); self.current_ready(page, '合成父读取途中隐藏')
            assert self.snapshot() == saved and self.count_requests('POST', APPLY) == writes
            self.passed('Confirmed save survives loss of either child or parent fresh detail; parent late GET while hidden cannot navigate; only explicit fresh read recovers without another apply')

    def create_family(self, ctx):
        invitation = self.write(ctx, 'POST', '/api/spaces/invitations', {}, 201)['invitation']
        return self.write(ctx, 'POST', '/api/spaces/redeem', dict(invitation=invitation, name='合成导入第二家庭', slug='trip-import-other',
                         MEMBER1_PASSWORD='testing-password-one', MEMBER2_PASSWORD='testing-password-two'), 201)

    def boundaries(self, browser):
        with self.flow(browser) as (ctx, page), ExitStack() as extra:
            self.open_import(page); self.paste(page, self.plan()); preview, _ = self.preview(page); packet = self.confirm(page)
            self.current_ready(page, TITLE); key = packet['body']['idempotencyKey']
            partner = self.context(browser, member=2); extra.callback(partner.close)
            assert self.get(partner, OPERATIONS + key, 404)['code'] == 'operation_not_found'
            assert self.get(partner, '/api/journeys/' + packet['result']['id'])['id'] == packet['result']['id'], 'Shared household trip remains readable'
            self.write(partner, 'POST', APPLY, packet['body'], 403)
            family = self.create_family(ctx); foreign = self.context(browser, member=None); extra.callback(foreign.close)
            assert foreign.request.get(self.base + family['entry']).status == 200; self.login(foreign)
            self.get(foreign, '/api/journeys/' + packet['result']['id'], 404)
            assert self.get(foreign, OPERATIONS + key, 404)['code'] == 'operation_not_found'
            assert self.write(foreign, 'POST', APPLY, packet['body'], 400)['error'] == '预览凭证无效，请重新预览'
            tv = self.context(browser, member=None); extra.callback(tv.close)
            pair = tv.request.post(self.base + '/api/pair/start', data={}).json()
            self.write(ctx, 'POST', '/api/pair/approve', dict(code=pair['code'], name='合成导入只读电视'))
            assert tv.request.post(self.base + '/api/pair/poll', data={'secret': pair['secret']}).json()['approved']
            self.get(tv, '/api/journeys/templates', 403); self.get(tv, OPERATIONS + key, 403)
            for path, body in ((PREVIEW, {'plan': self.plan()}), (APPLY, packet['body'])):
                assert tv.request.post(self.base + path, data=body).status == 403
            tv_page = tv.new_page(); tv_page.goto(self.base + '/app/tv')
            expect(tv_page.get_by_test_id('expo-tv-board')).to_be_visible(timeout=15000)
            expect(tv_page.get_by_test_id('trip-import-panel')).to_have_count(0)
            anonymous = self.context(browser, member=None); extra.callback(anonymous.close)
            self.get(anonymous, OPERATIONS + key, 401)
            assert len(self.snapshot()['journey_workflows']) == len(self.snapshot()['journey_actions']) == 1
            self.passed('Original actor receipt and token reject partner/cross-household/anonymous/paired TV as specified; household shared detail remains readable and TV cannot enter the member importer')

    def late_identity(self, browser):
        for switch in ('member', 'household'):
            with self.flow(browser) as (ctx, page):
                family = self.create_family(ctx) if switch == 'household' else None
                self.open_import(page); self.paste(page, self.plan(title='合成旧身份秘密输入')); before = self.snapshot(); sent = []
                def change(route):
                    response = route.fetch(max_redirects=0); raw = response.body(); assert response.status == 200
                    if family:
                        assert ctx.request.get(self.base + family['entry']).status == 200
                    self.login(ctx, 1 if family else 2)
                    route.fulfill(status=response.status, headers=response.headers, body=raw); sent.append(json.loads(raw))
                page.route(self.base + PREVIEW, change)
                try:
                    button(page, '预览导入').click(); self.settle(page, lambda: len(sent) == 1)
                    expect(page.get_by_test_id('trip-import-panel')).to_have_count(0, timeout=15000)
                finally: page.unroute(self.base + PREVIEW, change)
                expect(page.locator('body')).not_to_contain_text('合成旧身份秘密输入')
                assert self.snapshot() == before and self.count_requests('POST', APPLY) == 0
                self.open_import(page); expect(self.field(page)).to_have_value('')
        self.passed('Real successful preview arriving after actual member or household cookie replacement is discarded; old raw JSON/token cannot enter the replacement identity')

    def lifecycle_and_late_file(self, browser):
        with self.flow(browser) as (ctx, page):
            self.open_import(page); plan = self.plan(); self.paste(page, plan); before = self.snapshot()
            old_url = page.url; page.get_by_role('tab', name='首页', exact=True).click()
            expect(page.get_by_test_id('trip-import-panel')).to_be_visible(); assert page.url == old_url
            if button(page, '知道了').count(): button(page, '知道了').click()
            button(page, '返回旅行计划').click(); expect(page.get_by_role('heading', name='放弃导入草稿？', exact=True)).to_be_visible()
            button(page, '继续编辑').click(); expect(self.field(page)).to_have_value(json.dumps(plan, ensure_ascii=False))
            for mode in ('hidden', 'blur', 'offline'):
                if mode == 'hidden': visibility(page, True)
                elif mode == 'blur': page.evaluate("window.dispatchEvent(new Event('blur'))")
                else: ctx.set_offline(True)
                expect(self.field(page)).to_have_count(0); expect(page.locator('body')).not_to_contain_text(TITLE)
                if mode == 'hidden': visibility(page, False)
                elif mode == 'blur': page.evaluate("window.dispatchEvent(new Event('focus'))")
                else: ctx.set_offline(False)
                self.ready(page); assert json.loads(self.field(page).input_value()) == plan
            # Delay the native file reader, then run that same native operation on the original File.
            page.evaluate('''() => {const native=FileReader.prototype.readAsArrayBuffer;
              window.__tripReads=[]; window.__tripReadCompleted=0; FileReader.prototype.readAsArrayBuffer=function(file){
                window.__tripReads.push(()=>{this.addEventListener('loadend',()=>window.__tripReadCompleted++,{once:true});native.call(this,file);});};
              window.__restoreTripReader=()=>{FileReader.prototype.readAsArrayBuffer=native;};}''')
            self.choose_file(page, json.dumps(self.plan(title='合成迟到旧文件'), ensure_ascii=False).encode())
            page.wait_for_function('window.__tripReads.length === 1')
            visibility(page, True); expect(self.field(page)).to_have_count(0)
            visibility(page, False); self.ready(page); replacement = self.plan(title='合成新的粘贴输入'); self.paste(page, replacement)
            page.evaluate('window.__restoreTripReader(); window.__tripReads.shift()()')
            page.wait_for_function('window.__tripReadCompleted === 1')
            assert json.loads(self.field(page).input_value()) == replacement
            held = []
            def hold(route):
                response = route.fetch(max_redirects=0); raw = response.body(); assert response.status == 200
                held.append((route, response.status, response.headers, raw))
            page.route(self.base + PREVIEW, hold)
            try:
                button(page, '预览导入').click(); self.settle(page, lambda: len(held) == 1)
                visibility(page, True); expect(self.field(page)).to_have_count(0)
                route, status, headers, raw = held[0]; route.fulfill(status=status, headers=headers, body=raw)
                visibility(page, False); self.ready(page)
                expect(page.get_by_test_id('trip-import-preview')).to_have_count(0)
                assert json.loads(self.field(page).input_value()) == replacement
            finally: page.unroute(self.base + PREVIEW, hold)
            assert self.snapshot() == before and self.count_requests('POST', APPLY) == 0
            button(page, '返回旅行计划').click(); button(page, '放弃草稿并返回').click()
            expect(page.get_by_test_id('trip-import-panel')).to_have_count(0)
            expect(button(page, '导入旅行')).to_be_enabled(); page.get_by_role('tab', name='首页', exact=True).click()
            self.settle(page, lambda: urlsplit(page.url).path != '/app/trips')
            self.passed('Dirty navigation requires explicit abandon; hidden/blur/offline conceal but retain same-identity input; actual late native file and server preview cannot replace fresh draft; abandon releases navigation')

    def capture(self, page, name, width, target):
        page.set_viewport_size(dict(width=width, height=1080 if width >= 1280 else 844))
        page.evaluate('() => document.fonts.ready'); target.scroll_into_view_if_needed()
        page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
        metrics = page.evaluate('''() => ({width:innerWidth,scroll:document.documentElement.scrollWidth,
          clipped:[...document.querySelectorAll('[data-testid="trip-import-panel"] input,[data-testid="trip-import-panel"] textarea,[data-testid="trip-import-panel"] [role="button"]')]
          .filter(n=>{const r=n.getBoundingClientRect();return r.width>0&&r.height>0&&r.bottom>0&&r.top<innerHeight&&(r.right>innerWidth+2||r.left< -2)})
          .map(n=>({label:n.getAttribute('aria-label')||n.textContent,box:n.getBoundingClientRect().toJSON()}))})''')
        assert metrics['scroll'] <= width + 2 and not metrics['clipped'], metrics
        controls = []
        for label in ('确认创建旅行', '修改输入', '返回旅行计划'):
            box = button(page, label).bounding_box(); assert box and box['height'] >= 44 and box['width'] >= 44, (label, box)
            controls.append(dict(label=label, box=box))
        path = self.out / f'{name}-{width}.png'; page.screenshot(path=str(path), full_page=False)
        self.report['screenshots'].append(dict(path=path.relative_to(self.out.parent).as_posix(), sha256=sha(path), width=width,
            metrics=metrics, controls=controls, scope='Visible viewport after explicit inner scroll; not entire long preview at once.'))

    def widths_keyboard(self, browser):
        with self.flow(browser) as (ctx, page):
            self.open_import(page); plan = self.plan(2, LONG); self.paste(page, plan)
            action = button(page, '预览导入'); action.focus(); expect(action).to_be_focused()
            before = self.snapshot(); result = self.post(page, PREVIEW, lambda: action.press('Enter'))['result']
            expect(button(page, '确认创建旅行')).to_be_enabled(); assert result['canApply'] and self.snapshot() == before
            for width in WIDTHS:
                self.capture(page, 'trip-import-light-title', width, page.get_by_text(LONG, exact=True).first)
                self.capture(page, 'trip-import-light-confirm', width, button(page, '确认创建旅行'))
            self.modify(page); button(page, '返回旅行计划').click(); button(page, '放弃草稿并返回').click()
            prefs = self.get(ctx, '/api/preferences')
            self.write(ctx, 'PUT', '/api/preferences', dict(revision=prefs['revision'], changes=dict(colorMode='dark', density='compact')))
            self.open_import(page); page.wait_for_function("getComputedStyle(document.documentElement).colorScheme === 'dark'")
            self.paste(page, plan); self.preview(page); before = self.snapshot()
            for width in WIDTHS:
                control = button(page, '确认创建旅行'); control.focus(); expect(control).to_be_focused()
                self.capture(page, 'trip-import-dark-keyboard', width, control)
            packet = self.post(page, APPLY, lambda: button(page, '确认创建旅行').press('Enter'), expected=201)
            self.current_ready(page, LONG); assert self.count_requests('POST', APPLY) == 1 and self.snapshot() != before
            self.passed('Twelve four-width populated light/dark screenshots include long preview and inner-scroll confirm; real new controls are at least 44px and keyboard confirms exactly once')

    @classmethod
    def run_scenarios(cls, root, bundle, report, out, browser):
        names = ('v1_defaults_file_restart', 'v2_paste_full_detail', 'invalid_and_dst', 'committed_get_recovery',
                 'original_retry', 'unsent_404_explicit_end', 'expiry_and_new_session_receipt', 'saved_detail_failure',
                 'boundaries', 'late_identity', 'lifecycle_and_late_file', 'widths_keyboard')
        assert len(names) == CHECKS
        for name in names:
            case_out = out / name; case_out.mkdir(); folder = None
            before = (len(report['checks']), len(report['pageErrors']), len(report['externalRequests']))
            case = dict(name=name, passed=False, temporaryFixtureRemoved=False)
            try:
                with ExitStack() as resources:
                    folder = Path(resources.enter_context(tempfile.TemporaryDirectory(prefix='expo-trip-import-')))
                    case['temporaryDirectory'] = str(folder)
                    run = cls(root, bundle, folder, report, case_out, resources)
                    getattr(run, name)(browser)
                assert not folder.exists() and len(report['checks']) == before[0] + 1
                assert len(report['pageErrors']) == before[1] and len(report['externalRequests']) == before[2]
                case['passed'] = True
            except Exception:
                del report['checks'][before[0]:]
                failure = traceback.format_exc(); (case_out / 'failure.txt').write_text(failure, encoding='utf-8')
                report['scenarioFailures'].append(dict(scenario=name, traceback=failure, artifacts=name))
                print('FAIL ' + name + '\n' + failure, flush=True)
            finally:
                case['temporaryFixtureRemoved'] = folder is not None and not folder.exists()
                report['scenarioResults'].append(case)
        assert not report['scenarioFailures'], 'Independent failures retained; partial passes are not full acceptance'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path); parser.add_argument('--expected-head', required=True)
    parser.add_argument('--bundle', required=True, type=Path); parser.add_argument('--expected-build-evidence', required=True)
    args = parser.parse_args(); root, bundle = args.source_root.resolve(), args.bundle.resolve()
    assert re.fullmatch('[a-f0-9]{40}', args.expected_head) and re.fullmatch('[a-f0-9]{64}', args.expected_build_evidence)
    def git(*command):
        return subprocess.check_output(['git', '--no-replace-objects', *command], cwd=root, text=True).strip()
    head = git('rev-parse', 'HEAD'); assert head == args.expected_head and not git('status', '--porcelain=v1')
    evidence_path = bundle.parent / 'build-evidence.json'; assert sha(evidence_path) == args.expected_build_evidence
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    assert evidence['sourceHead'] == head and evidence['sourceTree'] == git('rev-parse', 'HEAD^{tree}')
    names = subprocess.check_output(['git', '--no-replace-objects', 'ls-files', '-z'], cwd=root).decode('utf-8').rstrip('\0').split('\0')
    def hashes(): return {name: sha(root / name) for name in names}
    def exports(): return {p.relative_to(bundle).as_posix(): sha(p) for p in bundle.rglob('*') if p.is_file()}
    assert exports() == evidence['files'] and all(sha(root / name) == digest for name, digest in evidence['inputFiles'].items())
    assert sha(Path(__file__)) == sha(root / 'tests/browser_expo_trip_import_check.py')
    out = Path(__file__).resolve().parents[1] / 'test-results' / ('expo-trip-import-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True); shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], screenshots=[], scenarioResults=[], scenarioFailures=[], head=head, tree=evidence['sourceTree'],
        buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(out / 'executed-harness.py'), sourceHashesBefore=hashes(), bundleHashesBefore=exports(),
        productionWrites=0, realFinancialData=False, realCloud=False, realAI=False, physicalTelevision=False,
        scope='Twelve independent real local Flask/SQLite/HTTPS/Edge fixtures; synthetic travel JSON only. Interception drops or delays actual requests/responses. One native FileReader call is delayed without changing its bytes. Signer time advances only for expiry; no real clock-duration or cloud acceptance. Visibility/blur events are simulated, offline uses browser network state. Screenshots require separate actual human review.')
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
        report['passed'] = report['passed'] and report['sourceUnchanged'] and report['bundleUnchanged'] and report['sourceStillFrozen'] and report['temporaryFixtureRemoved']
        (out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'report': str(out / 'result.json')}, ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    raise SystemExit(main())
