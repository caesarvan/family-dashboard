"""Frozen Expo photo suggestions: real isolated Flask/SQLite/Edge, synthetic JPEGs.

Cloud job completions are setup fixtures, never browser-facing business mocks.
Fault injection only delays or discards real GET/PATCH transport. No production.
"""
import argparse
from contextlib import ExitStack, closing
from datetime import datetime, timezone
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
import browser_expo_trip_recap_check as media_fixture
from browser_expo_trip_recap_check import Run as MediaRun
from browser_expo_finance_check import button, sha, visibility

CHECKS = 12
WIDTHS = (320, 390, 1280, 1920)
STAMP = '2026-12-01T16:30:00.123456789Z'
CAPTION = '本人合成照片：只记录来源时间，不推断拍摄地点'
LONG = '合成旅行：与家人沿河边步道散步后到社区花园喝咖啡，完整长名称应当换行并可核对；日期相符不证明照片的拍摄地点或实际到访'
VIEW = '查看旅行建议'
CONFIRM = '确认关联所选旅行'
RECHECK = '核对当前旅行关联'
CANCEL_DRAFT = '取消未保存的修改'
DIRTY_MESSAGE = '请先保存或取消未保存的修改，再查看旅行建议。'


class Run(MediaRun):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for actual, name in ((Path(__file__), 'tests/browser_expo_photo_suggestions_check.py'),
                             (Path(media_fixture.__file__), 'tests/browser_expo_trip_recap_check.py')):
            assert sha(actual) == sha(self.root / name), name
            self.report.setdefault('fixtureHashes', {})[name] = sha(actual)

    @staticmethod
    def item_path(item):
        return '/api/media/items/' + item['id']

    def suggestion_path(self, item):
        return self.item_path(item) + '/journey-suggestions'

    def make_journey(self, ctx, title='合成旅行', start='2026-12-02', end='2026-12-02', zone=None):
        plan = dict(title=title, start=start, end=end, checklist=[], shopping=[], segments=[],
                    destinations=[dict(key='city', city='合成城市', arrival=start, departure=end)])
        if zone:
            plan.update(schemaVersion=2, referenceTimezone=zone)
            plan['destinations'][0]['timeZone'] = zone
        preview = self.write(ctx, 'POST', '/api/journeys/preview', {'plan': plan})
        saved = self.write(ctx, 'POST', '/api/journeys/apply',
                           dict(previewToken=preview['previewToken'], idempotencyKey=secrets.token_hex(16)), 201)
        return self.get(ctx, '/api/journeys/' + saved['id'])

    def stage_photo(self, ctx, stamp=STAMP, member=1):
        imported = self.write(ctx, 'POST', '/api/media/imports', dict(requestId=secrets.token_hex(16),
            accountId=self.synthetic_accounts[member], consentVersion='media-v1', allowTemporaryProcessing=True), 202)['import']
        job = self.engine.claim_next(); assert job and job['action'] == 'create'
        assert self.engine.complete(job, self.media_fixture.session((None, None, [time.time()], None)))
        selected = self.media_fixture.selected(secrets.token_hex(12)); selected['createTime'] = stamp or STAMP
        job = self.engine.claim_next(); assert job['action'] == 'list'; assert self.engine.complete(job, [selected])
        while (job := self.engine.claim_next()) is not None:
            if job['action'] == 'cleanup':
                assert self.engine.complete(job, None); break
            assert job['action'] == 'download'
            stream = BytesIO(); Image.new('RGB', (24, 16), '#69774a').save(stream, 'PNG')
            jpeg = self.images.sanitize_media_preview(stream.getvalue(), 'image/png')
            assert self.engine.complete(job, dict(mediaId=job['media']['id'], manifest=[selected], preview=jpeg))
        detail = self.get(ctx, '/api/media/imports/' + imported['id'])
        assert detail['import']['state'] == 'awaiting_confirmation' and detail['import']['canConfirm']
        assert len(detail['items']) == 1
        return detail

    def make_photo(self, ctx, stamp=STAMP, caption=CAPTION, shared=False, member=1):
        detail = self.stage_photo(ctx, stamp, member)
        self.write(ctx, 'POST', '/api/media/imports/' + detail['import']['id'] + '/confirm',
                   dict(revision=detail['import']['revision'], confirmRequestId=secrets.token_hex(16),
                        itemIds=[i['id'] for i in detail['items']], consentVersion='media-v1', persistSelected=True))
        item = self.get(ctx, '/api/media/items/' + detail['items'][0]['id'])['item']
        item = self.write(ctx, 'PATCH', self.item_path(item), dict(revision=item['revision'], caption=caption,
                          visibility='shared' if shared else 'private'))['item']
        if stamp is None:
            # A real encrypted legacy row lacking recorded source time, not a DTO substitution.
            with self.engine.transaction(True) as con:
                row = con.execute('SELECT * FROM media_items WHERE id=?', (item['id'],)).fetchone()
                meta = self.engine._metadata(row); meta.pop('sourceCreatedAt', None)
                con.execute('UPDATE media_items SET metadata_cipher=? WHERE id=?',
                            (self.engine._seal('media-metadata', row, meta), item['id']))
            item = self.get(ctx, self.item_path(item))['item']
        return item

    def pair(self, browser, ctx, stack, name='合成电视'):
        tv = self.context(browser, member=None); stack.callback(tv.close)
        pair = tv.request.post(self.base + '/api/pair/start', data={}); assert pair.status == 200
        self.write(ctx, 'POST', '/api/pair/approve', dict(code=pair.json()['code'], name=name))
        assert tv.request.post(self.base + '/api/pair/poll', data={'secret': pair.json()['secret']}).json()['approved']
        device = next(d for d in self.get(ctx, '/api/devices') if d['name'] == name)
        return device, tv

    def stable_tables(self):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database)) as con:
            return {name: sorted(con.execute('SELECT * FROM ' + name).fetchall(), key=repr)
                    for name in ('entities', 'journey_workflows', 'journey_links', 'journey_actions',
                                 'journey_places', 'media_imports', 'media_tv_grants', 'media_playback')}

    def open_detail(self, page, item, navigate=True, shared=False):
        if navigate:
            page.goto(self.base + '/app/photos'); page.bring_to_front()
            expect(page.get_by_role('heading', name='相册', exact=True)).to_be_visible(timeout=15000)
        if shared:
            button(page, '家人共享').click()
        card = page.get_by_label('查看照片：' + item['caption'], exact=True)
        expect(card).to_have_count(1, timeout=15000); expect(card).to_be_visible(timeout=15000); card.click()
        if item['canManage']:
            expect(page.get_by_role('textbox', name='照片说明', exact=True)).to_have_value(item['caption'], timeout=15000)
            expect(button(page, VIEW)).to_be_enabled(timeout=15000)
        else:
            expect(page.get_by_text('由上传者管理，你可以查看当前共享的照片。', exact=True)).to_be_visible(timeout=15000)

    def suggestion_box(self, page):
        return page.get_by_test_id('photo-journey-suggestions')

    def load_suggestions(self, page):
        reads = sum(r['method'] == 'GET' and r['path'].endswith('/journey-suggestions') for r in self.requests)
        expect(button(page, VIEW)).to_be_enabled(timeout=15000); button(page, VIEW).click()
        self.settle(page, lambda: sum(r['method'] == 'GET' and r['path'].endswith('/journey-suggestions') for r in self.requests) == reads + 1)
        expect(self.suggestion_box(page)).to_be_visible(timeout=15000)
        expect(button(page, VIEW)).to_be_enabled(timeout=15000)

    def choose(self, page, journey, keyboard=False):
        radio = page.get_by_role('radio', name='选择旅行：' + journey['trip']['title'], exact=True)
        expect(radio).to_be_enabled(timeout=15000)
        if keyboard:
            radio.focus(); page.keyboard.press('Space')
        else:
            radio.click()
        expect(radio).to_have_attribute('aria-checked', 'true')
        expect(button(page, CONFIRM)).to_be_enabled()

    def confirm_real(self, page, item, status=200, before_fetch=None):
        path = self.base + self.item_path(item); received = []
        def capture(route):
            if route.request.method != 'PATCH':
                route.continue_(); return
            if before_fetch:
                before_fetch()
            response = route.fetch(max_redirects=0)
            raw = response.body(); data = json.loads(raw)
            received.append(dict(status=response.status, body=route.request.post_data_json, response=data))
            route.fulfill(status=response.status, headers=response.headers, body=raw)
        page.route(path, capture)
        try:
            button(page, CONFIRM).click()
            self.settle(page, lambda: len(received) == 1)
            expect(button(page, VIEW if status == 200 else RECHECK)).to_be_enabled(timeout=15000)
        finally:
            page.unroute(path, capture)
        assert len(received) == 1 and received[0]['status'] == status, received
        assert set(received[0]['body']) == {'revision', 'journeyId', 'expectedJourneyRevision', 'expectedTripRevision'}
        return received[0]

    def recheck(self, page):
        expect(button(page, RECHECK)).to_be_enabled(timeout=15000)
        self.touch_target(button(page, RECHECK)); button(page, RECHECK).click()
        expect(button(page, VIEW)).to_be_enabled(timeout=15000)
        self.no_selection(page)

    @staticmethod
    def touch_target(control):
        box = control.bounding_box()
        assert box and box['width'] >= 44 and box['height'] >= 44, box

    @staticmethod
    def no_selection(page):
        expect(page.get_by_role('radio', name=re.compile('^选择旅行：'))).to_have_count(0)
        expect(button(page, CONFIRM)).to_have_count(0)

    def no_writes(self, mark):
        writes = [r for r in self.requests[mark:] if r['method'] not in ('GET', 'HEAD', 'OPTIONS') and r['path'].startswith('/api/')]
        assert not writes, writes

    def entry_preservation(self, browser):
        with self.flow(browser) as (ctx, page), ExitStack() as stack:
            journey = self.make_journey(ctx); item = self.make_photo(ctx, shared=True)
            self.place(ctx, journey, '合成计划地点', status='planned')
            device, _ = self.pair(browser, ctx, stack)
            self.write(ctx, 'PUT', self.item_path(item) + '/tv-grants', dict(revision=item['revision'], deviceIds=[device['id']],
                consentVersion='media-v1', allowTvDisplay=True))
            item = self.get(ctx, self.item_path(item))['item']; before = self.stable_tables()
            self.open_detail(page, item); mark = len(self.requests)
            assert self.count_requests('GET', self.suggestion_path(item)) == 0
            self.load_suggestions(page); self.choose(page, journey, keyboard=True)
            self.no_writes(mark); assert self.stable_tables() == before
            result = self.confirm_real(page, item)
            assert result['body'] == dict(revision=item['revision'], journeyId=journey['id'],
                expectedJourneyRevision=journey['revision'], expectedTripRevision=journey['trip']['revision'])
            current = self.get(ctx, self.item_path(item))['item']
            assert current['journey']['id'] == journey['id'] and current['revision'] == item['revision'] + 1
            assert all(current[k] == item[k] for k in ('caption', 'visibility', 'sourceCreatedAt', 'previewUrl'))
            assert self.stable_tables() == before
            assert self.get(ctx, self.item_path(item) + '/tv-grants')['deviceIds'] == [device['id']]
            assert self.count_requests('PATCH', self.item_path(item)) == 1
            self.passed('Explicit owner GET, keyboard selection and one exact four-field PATCH persist association only; caption/shared/TV grants/places and journey records preserved')

    def empty_manual(self, browser):
        with self.flow(browser) as (ctx, page):
            journey = self.make_journey(ctx)
            for stamp, code, label in ((None, 'source_time_unknown', '合成旧照片'), ('2020-01-01T01:00:00Z', 'no_matching_journeys', '合成无匹配照片')):
                item = self.make_photo(ctx, stamp=stamp, caption=label); self.open_detail(page, item)
                mark = len(self.requests); self.load_suggestions(page)
                dto = self.get(ctx, self.suggestion_path(item)); assert dto['reason']['code'] == code and dto['suggestions'] == []
                expect(self.suggestion_box(page)).to_contain_text('没有已记录的来源时间' if stamp is None else '暂无日期相符的旅行')
                expect(self.suggestion_box(page)).to_contain_text('手动关联')
                expect(page.get_by_role('radio', name=re.compile('^选择旅行：'))).to_have_count(0)
                self.no_writes(mark)
                button(page, '关联旅行（可选）').click()
                page.get_by_role('menuitem', name=journey['trip']['title'], exact=True).click()
                expect(button(page, '保存照片设置')).to_be_enabled(); button(page, '保存照片设置').click()
                expect(page.get_by_text('照片设置已保存。', exact=True)).to_be_visible(timeout=15000)
                current = self.get(ctx, self.item_path(item))['item']; assert current['journey']['id'] == journey['id']
                assert current['sourceCreatedAt'] == stamp and current['caption'] == label
                button(page, '关闭').click()
            self.passed('Unknown legacy source and genuine no date match stay explicit/read-only; ordinary manual association still works without inventing source time')

    def timezone_current(self, browser):
        with self.flow(browser) as (ctx, page):
            item = self.make_photo(ctx)
            legacy = self.make_journey(ctx, title='旧版上海参考日')
            hawaii = self.make_journey(ctx, title='夏威夷参考日', start='2026-12-01', end='2026-12-01', zone='Pacific/Honolulu')
            edited = self.make_journey(ctx, title='原计划不应覆盖当前旅行', start='2026-11-01', end='2026-11-01')
            self.write(ctx, 'PATCH', '/api/items/trips/' + edited['tripId'], dict(revision=edited['trip']['revision'],
                title='当前独立修改的旅行', start='2026-12-02', end='2026-12-02'))
            before = self.snapshot(); self.open_detail(page, item); mark = len(self.requests); self.load_suggestions(page)
            dto = self.get(ctx, self.suggestion_path(item)); assert dto['sourceCreatedAt'] == STAMP
            matches = {r['journeyId']: r for r in dto['suggestions']}; assert set(matches) == {legacy['id'], hawaii['id'], edited['id']}
            assert matches[legacy['id']]['sourceDate'] == '2026-12-02' and matches[legacy['id']]['referenceTimezoneSource'] == 'legacy_default'
            assert matches[hawaii['id']]['sourceDate'] == '2026-12-01' and matches[hawaii['id']]['referenceTimezone'] == 'Pacific/Honolulu'
            assert matches[edited['id']]['title'] == '当前独立修改的旅行'
            expect(self.suggestion_box(page)).to_contain_text(STAMP)
            for match in matches.values():
                row = page.get_by_test_id('photo-journey-suggestion-' + match['journeyId'])
                for value in (match['title'], match['referenceTimezone'], match['sourceDate']): expect(row).to_contain_text(value)
            expect(self.suggestion_box(page)).to_contain_text('不代表拍摄地点或实际到访')
            self.no_writes(mark); assert self.snapshot() == before
            self.passed('Actual v1/v2 zone and current independent trip-date/title matches preserve nanosecond source text; no inferred capture location or writes')

    def capped_results(self, browser):
        with self.flow(browser) as (ctx, page):
            for number in range(21): self.make_journey(ctx, title=f'合成候选旅行 {number:02}')
            item = self.make_photo(ctx); self.open_detail(page, item); mark = len(self.requests); self.load_suggestions(page)
            dto = self.get(ctx, self.suggestion_path(item)); assert dto['limit'] == 20 and dto['hasMore'] is True and len(dto['suggestions']) == 20
            expect(page.get_by_role('radio', name=re.compile('^选择旅行：'))).to_have_count(20)
            ids = self.suggestion_box(page).locator('[data-testid^="photo-journey-suggestion-"]').evaluate_all('nodes => nodes.map(n => n.dataset.testid)')
            assert ids == ['photo-journey-suggestion-' + row['journeyId'] for row in dto['suggestions']]
            expect(self.suggestion_box(page)).to_contain_text('仅显示前 20 条匹配旅行')
            expect(self.suggestion_box(page)).to_contain_text('其他旅行可在上方手动选择')
            self.no_writes(mark)
            self.passed('Twenty actual ordered suggestions out of 21 current matching journeys; hasMore is visible and no fabricated pagination or auto-association')

    def conflicts(self, browser):
        with self.flow(browser) as (ctx, page):
            for kind in ('photo', 'journey', 'trip'):
                journey = self.make_journey(ctx, title='合成冲突旅行 ' + kind)
                item = self.make_photo(ctx, caption='合成冲突照片 ' + kind)
                self.open_detail(page, item); self.load_suggestions(page); self.choose(page, journey)
                stable = []
                def revise():
                    if kind == 'photo':
                        self.write(ctx, 'PATCH', self.item_path(item), dict(revision=item['revision'], caption='独立修改后 ' + kind))
                    elif kind == 'trip':
                        self.write(ctx, 'PATCH', '/api/items/trips/' + journey['tripId'], dict(revision=journey['trip']['revision'], title='独立修改的当前旅行'))
                    else:
                        plan = journey['plan']; plan['note'] = '独立修改 workflow'
                        preview = self.write(ctx, 'POST', '/api/journeys/preview', dict(journeyId=journey['id'], revision=journey['revision'], plan=plan))
                        self.write(ctx, 'POST', '/api/journeys/apply', dict(previewToken=preview['previewToken'], idempotencyKey=secrets.token_hex(16)))
                    stable.append(self.snapshot())
                result = self.confirm_real(page, item, 409, revise)
                assert result['response']['code'] == 'conflict' and self.snapshot() == stable[0]
                self.recheck(page); assert self.count_requests('PATCH', self.item_path(item)) == 1
                self.load_suggestions(page); current_journey = self.get(ctx, '/api/journeys/' + journey['id'])
                self.choose(page, current_journey); self.confirm_real(page, item)
                assert self.get(ctx, self.item_path(item))['item']['journey']['id'] == journey['id']
                assert self.count_requests('PATCH', self.item_path(item)) == 2
                button(page, '关闭').click()
            self.passed('Each actual photo/workflow/trip revision race yields real 409 with zero confirmation changes; GET review then new explicit selection/confirmation succeeds')

    def lost_write(self, browser, committed):
        with self.flow(browser) as (ctx, page):
            journey = self.make_journey(ctx); item = self.make_photo(ctx); before = self.snapshot()
            self.open_detail(page, item); self.load_suggestions(page); self.choose(page, journey)
            path = self.base + self.item_path(item); attempts = []
            def drop(route):
                if route.request.method != 'PATCH':
                    route.continue_(); return
                body = route.request.post_data_json
                assert set(body) == {'revision', 'journeyId', 'expectedJourneyRevision', 'expectedTripRevision'}
                if committed:
                    response = route.fetch(max_redirects=0); assert response.status == 200
                    assert response.json()['item']['journey']['id'] == journey['id']
                route.abort('failed'); attempts.append(body)
            page.route(path, drop)
            try:
                button(page, CONFIRM).click()
                expect(button(page, RECHECK)).to_be_enabled(timeout=15000)
                assert len(attempts) == 1
            finally:
                page.unroute(path, drop)
            current = self.get(ctx, self.item_path(item))['item']
            if committed:
                assert current['journey']['id'] == journey['id'] and current['revision'] == item['revision'] + 1
                lost_get = []
                def drop_read(route):
                    response = route.fetch(max_redirects=0); assert response.status == 200
                    route.abort('failed'); lost_get.append(True)
                page.route(path, drop_read, times=1); button(page, RECHECK).click()
                self.settle(page, lambda: lost_get == [True]); expect(button(page, RECHECK)).to_be_enabled(timeout=15000)
            else:
                assert current['journey'] is None and self.snapshot() == before
            assert self.count_requests('PATCH', self.item_path(item)) == 1
            self.recheck(page)
            expect(page.get_by_role('button', name=CONFIRM, exact=True)).to_have_count(0)
            assert self.count_requests('PATCH', self.item_path(item)) == 1
            if committed:
                expect(button(page, journey['trip']['title'])).to_be_visible()
            else:
                expect(button(page, '关联旅行（可选）')).to_be_visible()
            mark = len(self.requests); self.load_suggestions(page); self.no_writes(mark)
            assert self.count_requests('PATCH', self.item_path(item)) == 1
            self.passed(('Committed real PATCH with reply lost and first readback also lost' if committed else 'PATCH aborted before reaching server') +
                        ': unknown locks old choices, explicit GET recovers current association only, never automatically repeats PATCH or treats absence as a receipt')

    def lost_before(self, browser):
        self.lost_write(browser, False)

    def lost_after(self, browser):
        self.lost_write(browser, True)

    def readback_failure(self, browser):
        with self.flow(browser) as (ctx, page):
            journey = self.make_journey(ctx); item = self.make_photo(ctx)
            self.open_detail(page, item); self.load_suggestions(page); self.choose(page, journey)
            path = self.base + self.item_path(item); sent, dropped = [], []
            def transport(route):
                if route.request.method == 'PATCH':
                    response = route.fetch(max_redirects=0); raw = response.body()
                    assert response.status == 200 and json.loads(raw)['item']['journey']['id'] == journey['id']
                    sent.append(route.request.post_data_json)
                    route.fulfill(status=response.status, headers=response.headers, body=raw)
                elif route.request.method == 'GET' and sent and not dropped:
                    response = route.fetch(max_redirects=0); assert response.status == 200
                    dropped.append(True); route.abort('failed')
                else:
                    route.continue_()
            page.route(path, transport)
            try:
                button(page, CONFIRM).click()
                self.settle(page, lambda: len(sent) == len(dropped) == 1)
                expect(button(page, RECHECK)).to_be_enabled(timeout=15000)
            finally:
                page.unroute(path, transport)
            expect(button(page, CONFIRM)).to_have_count(0)
            assert self.get(ctx, self.item_path(item))['item']['journey']['id'] == journey['id']
            assert self.count_requests('PATCH', self.item_path(item)) == 1
            self.recheck(page)
            assert self.count_requests('PATCH', self.item_path(item)) == 1
            self.passed('Real 200 confirmation followed by lost current-photo GET disables old confirmation; explicit readback recovers without another write')

    def dirty_editor(self, browser):
        with self.flow(browser) as (ctx, page), ExitStack() as stack:
            journey = self.make_journey(ctx); item = self.make_photo(ctx, shared=True)
            self.pair(browser, ctx, stack, '合成可勾选电视')
            self.open_detail(page, item)
            def television():
                control = page.get_by_role('checkbox', name='合成可勾选电视', exact=True)
                if not control.is_visible():
                    page.get_by_role('button', name=re.compile('^电视展示')).click()
                expect(control).to_be_enabled()
            for kind in ('caption', 'visibility', 'journey', 'grants', 'consent'):
                before, mark = self.snapshot(), len(self.requests)
                reads = self.count_requests('GET', self.suggestion_path(item))
                if kind == 'caption':
                    page.get_by_role('textbox', name='照片说明', exact=True).fill('尚未保存的本人说明')
                elif kind == 'visibility':
                    button(page, '仅我自己').click()
                elif kind == 'journey':
                    button(page, '关联旅行（可选）').click()
                    page.get_by_role('menuitem', name=journey['trip']['title'], exact=True).click()
                else:
                    television()
                    page.get_by_role('checkbox', name='合成可勾选电视' if kind == 'grants' else '允许选中的电视展示这张照片。', exact=True).click()
                expect(page.get_by_text(DIRTY_MESSAGE, exact=True)).to_be_visible()
                expect(button(page, VIEW)).to_have_count(0)
                assert self.count_requests('GET', self.suggestion_path(item)) == reads
                expect(button(page, CANCEL_DRAFT)).to_be_enabled()
                self.touch_target(button(page, CANCEL_DRAFT)); button(page, CANCEL_DRAFT).click()
                expect(button(page, VIEW)).to_be_enabled(timeout=15000)
                self.no_writes(mark); assert self.snapshot() == before
                expect(page.get_by_role('textbox', name='照片说明', exact=True)).to_have_value(item['caption'])
            self.load_suggestions(page); self.choose(page, journey)
            result = self.confirm_real(page, item)
            assert set(result['body']) == {'revision', 'journeyId', 'expectedJourneyRevision', 'expectedTripRevision'}
            current = self.get(ctx, self.item_path(item))['item']
            assert current['caption'] == item['caption'] and current['visibility'] == 'shared'
            assert self.get(ctx, self.item_path(item) + '/tv-grants')['deviceIds'] == []
            self.passed('Five unsaved editor dimensions disable suggestions; local cancel writes nothing; final exact association never includes caption/visibility/journey draft/TV selection or consent')

    def access_boundaries(self, browser):
        with self.flow(browser) as (ctx, page), ExitStack() as stack:
            journey = self.make_journey(ctx); item = self.make_photo(ctx, shared=True)
            dto = self.get(ctx, self.suggestion_path(item)); chosen = dto['suggestions'][0]
            body = dict(revision=item['revision'], journeyId=chosen['journeyId'],
                        expectedJourneyRevision=chosen['journeyRevision'], expectedTripRevision=chosen['tripRevision'])
            partner = self.context(browser, member=2); stack.callback(partner.close)
            partner_item = self.get(partner, self.item_path(item))['item']; assert partner_item['canManage'] is False
            partner_page = partner.new_page(); self.open_detail(partner_page, partner_item, shared=True)
            expect(button(partner_page, VIEW)).to_have_count(0)
            self.get(partner, self.suggestion_path(item), 404)
            self.write(partner, 'PATCH', self.item_path(item), body, 403)
            family = self.create_family(ctx)
            other = self.context(browser, member=None); stack.callback(other.close)
            assert other.request.get(self.base + family['entry']).status == 200; self.login(other)
            self.get(other, self.suggestion_path(item), 404); self.write(other, 'PATCH', self.item_path(item), body, 404)
            _, tv = self.pair(browser, ctx, stack)
            self.get(tv, self.suggestion_path(item), 403)
            response = tv.request.patch(self.base + self.item_path(item), data=body, headers={'Origin': self.base})
            assert response.status == 403, response.text()
            tv_page = tv.new_page(); tv_page.goto(self.base + '/app/tv')
            expect(tv_page.get_by_test_id('expo-tv-board')).to_be_visible(timeout=15000)
            expect(tv_page.get_by_test_id('photo-journey-suggestions')).to_have_count(0)
            assert self.get(ctx, self.item_path(item))['item']['journey'] is None
            self.passed('Real partner shared detail has no suggestions; owner-only GET/PATCH reject partner, signed second household and paired TV without linking or granting photos')

    def import_resume_regression(self, browser, ctx, page):
        # Keep a genuine unknown confirm intent while another session cancels
        # the staged import. Foreground must read its detail before revealing it.
        detail = self.stage_photo(ctx)
        endpoint = '/api/media/imports/' + detail['import']['id']
        page.reload(); expect(button(page, '选择照片')).to_be_enabled(timeout=15000)
        button(page, '选择照片').click()
        page.get_by_text('最近的选择', exact=True).click()
        page.get_by_text('确认想留下的照片', exact=True).click()
        expect(page.get_by_role('checkbox', name='保留这张', exact=True)).to_be_enabled(timeout=15000)
        page.get_by_role('checkbox', name='同意将勾选照片的展示副本持久保存在相册中。之后另行设置家庭共享和电视展示。', exact=True).click()
        attempts = []
        def drop_confirm(route):
            assert route.request.method == 'POST'
            attempts.append(route.request.post_data_json); route.abort('failed')
        page.route(self.base + endpoint + '/confirm', drop_confirm)
        try:
            button(page, '保存选中的 1 张').click()
            expect(button(page, '核对 / 重试原保存请求')).to_be_enabled(timeout=15000)
            assert len(attempts) == 1 and attempts[0]['confirmRequestId']
            assert attempts[0]['itemIds'] == [detail['items'][0]['id']]
            visibility(page, True)
            expect(page.get_by_role('checkbox', name='保留这张', exact=True)).to_have_count(0)
            with ExitStack() as stack:
                other_device = self.context(browser); stack.callback(other_device.close)
                current = self.get(other_device, endpoint)['import']
                assert current['state'] == 'awaiting_confirmation'
                self.write(other_device, 'DELETE', endpoint, {'revision': current['revision']})
                cancelled = self.get(other_device, endpoint)
                assert cancelled['import']['state'] == 'cancelled' and cancelled['items'] == []
            held = []
            def hold_current(route):
                response = route.fetch(max_redirects=0)
                assert response.status == 200 and response.json()['import']['state'] == 'cancelled'
                held.append((route, response))
            page.route(self.base + endpoint, hold_current, times=1)
            mark = len(self.requests); visibility(page, False)
            self.settle(page, lambda: len(held) == 1)
            expect(page.get_by_role('heading', name='相册', exact=True)).to_have_count(0)
            expect(page.get_by_role('checkbox', name='保留这张', exact=True)).to_have_count(0)
            expect(button(page, '核对 / 重试原保存请求')).to_have_count(0)
            held[0][0].fulfill(response=held[0][1])
            expect(page.get_by_role('heading', name='已取消', exact=True)).to_be_visible(timeout=15000)
            expect(page.get_by_role('img', name='本次选择的照片', exact=True)).to_have_count(0)
            expect(page.get_by_role('checkbox', name='保留这张', exact=True)).to_have_count(0)
            expect(button(page, '核对 / 重试原保存请求')).to_have_count(0)
            expect(button(page, '保存选中的 1 张')).to_have_count(0)
            self.no_writes(mark)
            assert len(attempts) == self.count_requests('POST', endpoint + '/confirm') == 1
            with closing(sqlite3.connect(self.database)) as con:
                assert con.execute('SELECT state,confirm_request_id FROM media_imports WHERE id=?',
                                   (detail['import']['id'],)).fetchone() == ('cancelled', None)
            button(page, '收起').click()
        finally:
            page.unroute(self.base + endpoint + '/confirm', drop_confirm)

    def lifetime_isolation(self, browser):
        with self.flow(browser) as (ctx, page):
            journey = self.make_journey(ctx); item = self.make_photo(ctx)
            other = self.make_photo(ctx, caption='下一张合成照片')
            self.open_detail(page, item); self.load_suggestions(page); self.choose(page, journey)
            button(page, '关闭').click(); self.open_detail(page, other, navigate=False)
            self.no_selection(page)
            button(page, '关闭').click(); self.open_detail(page, item, navigate=False)
            before, mark = self.snapshot(), len(self.requests)
            self.load_suggestions(page)
            ctx.set_offline(True); expect(self.suggestion_box(page)).to_have_count(0)
            expect(page.get_by_role('textbox', name='照片说明', exact=True)).to_have_count(0)
            ctx.set_offline(False); expect(button(page, VIEW)).to_be_enabled(timeout=15000)
            self.no_selection(page)
            for mode in ('hidden', 'blur'):
                held = []
                def hold(route):
                    response = route.fetch(max_redirects=0); assert response.status == 200
                    held.append((route, response))
                path = self.base + self.suggestion_path(item)
                page.route(path, hold, times=1); button(page, VIEW).click()
                self.settle(page, lambda: len(held) == 1)
                if mode == 'hidden': visibility(page, True)
                else: page.evaluate("() => window.dispatchEvent(new Event('blur'))")
                expect(self.suggestion_box(page)).to_have_count(0)
                held[0][0].fulfill(response=held[0][1]); page.wait_for_timeout(300)
                expect(self.suggestion_box(page)).to_have_count(0)
                expect(page.get_by_role('textbox', name='照片说明', exact=True)).to_have_count(0)
                if mode == 'hidden': visibility(page, False)
                else:
                    page.evaluate("() => window.dispatchEvent(new Event('online'))"); page.wait_for_timeout(150)
                    expect(page.get_by_role('textbox', name='照片说明', exact=True)).to_have_count(0)
                    page.evaluate("() => window.dispatchEvent(new Event('focus'))")
                expect(button(page, VIEW)).to_be_enabled(timeout=15000)
                self.no_selection(page)
            self.no_writes(mark); assert self.snapshot() == before
            button(page, '关闭').click()
            self.import_resume_regression(browser, ctx, page)
            self.open_detail(page, item, navigate=False)
            # A genuine late success from the old owner must not survive fresh /me.
            sent = []
            def change_identity(route):
                response = route.fetch(max_redirects=0); assert response.status == 200
                self.login(ctx, 2); route.fulfill(response=response); sent.append(True)
            page.route(self.base + self.suggestion_path(item), change_identity, times=1)
            button(page, VIEW).click(); self.settle(page, lambda: sent == [True])
            expect(page.get_by_role('textbox', name='照片说明', exact=True)).to_have_count(0, timeout=15000)
            expect(self.suggestion_box(page)).to_have_count(0)
            expect(page.locator('body')).not_to_contain_text(CAPTION)
            assert self.get(ctx, '/api/media/items?scope=mine&limit=24&offset=0')['total'] == 0
            self.login(ctx); family = self.create_family(ctx); self.open_detail(page, item)
            switched = []
            def change_household(route):
                response = route.fetch(max_redirects=0); assert response.status == 200
                assert ctx.request.get(self.base + family['entry']).status == 200; self.login(ctx)
                route.fulfill(response=response); switched.append(True)
            page.route(self.base + self.suggestion_path(item), change_household, times=1)
            button(page, VIEW).click(); self.settle(page, lambda: switched == [True])
            expect(page.get_by_test_id('photo-editor')).to_have_count(0, timeout=15000)
            expect(self.suggestion_box(page)).to_have_count(0)
            expect(page.locator('body')).not_to_contain_text(CAPTION)
            self.get(ctx, self.suggestion_path(item), 404)
            self.passed('Switching photos discards selection; offline/hidden/blur reject delayed GETs; cancelled staged import stays hidden until fresh detail and never repeats unknown confirm; new member/household cookies discard old suggestions')

    def screenshot(self, page, name, width, target):
        page.set_viewport_size(dict(width=width, height=1080 if width >= 1280 else 844))
        page.evaluate('() => document.fonts.ready'); target.scroll_into_view_if_needed(); page.wait_for_timeout(800)
        page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
        metrics = self.suggestion_box(page).evaluate('''root => ({width:innerWidth,scroll:document.documentElement.scrollWidth,
          clipped:[...root.querySelectorAll('[role="button"],[role="radio"]')].filter(n=>{
            const r=n.getBoundingClientRect();return r.width>0&&r.height>0&&r.bottom>0&&r.top<innerHeight&&(r.right>innerWidth+2||r.left< -2);
          }).map(n=>({label:n.getAttribute('aria-label')||n.textContent,box:n.getBoundingClientRect().toJSON()}))})''')
        assert metrics['scroll'] <= width + 2 and not metrics['clipped'], metrics
        sizes = []
        for control in [button(page, VIEW), button(page, CONFIRM), *page.get_by_role('radio', name=re.compile('^选择旅行：')).all()]:
            box = control.bounding_box(); assert box and box['width'] >= 44 and box['height'] >= 44, box
            sizes.append(dict(label=control.get_attribute('aria-label') or control.inner_text(), box=box))
        path = self.out / f'{name}-{width}.png'; page.screenshot(path=str(path), full_page=False)
        self.report['screenshots'].append(dict(path=path.relative_to(self.out.parent).as_posix(), sha256=sha(path), width=width,
            metrics=metrics, controls=sizes, scope='Settled visible viewport after explicit dialog-internal scroll; not all content at once.'))

    def widths_keyboard(self, browser):
        with self.flow(browser) as (ctx, page):
            journey = self.make_journey(ctx, title=LONG)
            second = self.make_journey(ctx, title='另一个合成日期相符旅行')
            item = self.make_photo(ctx); self.open_detail(page, item); self.load_suggestions(page)
            radio = page.get_by_role('radio', name='选择旅行：' + LONG, exact=True)
            self.choose(page, journey, keyboard=True)
            for width in WIDTHS:
                self.screenshot(page, 'suggestions-light-title', width, radio)
                self.screenshot(page, 'suggestions-light-confirm', width, button(page, CONFIRM))
            pref = self.get(ctx, '/api/preferences')
            self.write(ctx, 'PUT', '/api/preferences', dict(revision=pref['revision'], changes=dict(colorMode='dark', density='compact')))
            self.open_detail(page, item); self.load_suggestions(page)
            page.wait_for_function("getComputedStyle(document.documentElement).colorScheme === 'dark'")
            self.choose(page, journey, keyboard=True)
            for width in WIDTHS:
                radio.focus(); self.screenshot(page, 'suggestions-dark-keyboard', width, radio)
            other = page.get_by_role('radio', name='选择旅行：' + second['trip']['title'], exact=True)
            other.focus(); expect(other).to_be_focused(); page.keyboard.press('Space')
            expect(other).to_have_attribute('aria-checked', 'true'); expect(radio).to_have_attribute('aria-checked', 'false')
            assert self.count_requests('PATCH', self.item_path(item)) == 0
            self.report['keyboard'] = dict(spaceSelects=True, focusChangesSelection=True, noImplicitWrite=True)
            self.passed('Twelve actual four-width light/dark dialog viewports including long titles, inner-scroll confirmation and keyboard focus; new suggestion controls at least 44px, Space never writes')

    @classmethod
    def run_scenarios(cls, root, bundle, report, out, browser):
        cases = ('entry_preservation', 'empty_manual', 'timezone_current', 'capped_results', 'conflicts',
                 'lost_before', 'lost_after', 'readback_failure', 'dirty_editor', 'access_boundaries', 'lifetime_isolation', 'widths_keyboard')
        for name in cases:
            case_out = out / name; case_out.mkdir(); folder = None
            before = (len(report['checks']), len(report['pageErrors']), len(report['externalRequests']))
            result = dict(name=name, passed=False, temporaryFixtureRemoved=False)
            try:
                with ExitStack() as resources:
                    folder = Path(resources.enter_context(tempfile.TemporaryDirectory(prefix='expo-photo-suggestions-')))
                    run = cls(root, bundle, folder, report, case_out, resources)
                    getattr(run, name)(browser)
                assert not folder.exists() and len(report['checks']) == before[0] + 1
                assert len(report['pageErrors']) == before[1] and len(report['externalRequests']) == before[2]
                result['passed'] = True
            except Exception:
                del report['checks'][before[0]:]
                failure = traceback.format_exc(); (case_out / 'failure.txt').write_text(failure, encoding='utf-8')
                report['scenarioFailures'].append(dict(scenario=name, traceback=failure, artifacts=name))
                print('FAIL ' + name + '\n' + failure, flush=True)
            finally:
                result['temporaryFixtureRemoved'] = folder is not None and not folder.exists()
                report['scenarioResults'].append(result)
        assert not report['scenarioFailures'], 'Independent failures retained; partial passes are not a full acceptance'

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
    assert sha(Path(__file__)) == sha(root / 'tests/browser_expo_photo_suggestions_check.py')
    out = Path(__file__).resolve().parents[1] / 'test-results' / ('expo-photo-suggestions-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True); shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], screenshots=[], scenarioResults=[], scenarioFailures=[], head=head,
        tree=evidence['sourceTree'], buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(out / 'executed-harness.py'),
        sourceHashesBefore=hashes(), bundleHashesBefore=exports(), productionWrites=0, realCloud=False, realAI=False, physicalTelevision=False,
        scope='Twelve independent real local Flask/SQLite/Edge scenarios with synthetic provider-job completions and sanitized JPEGs. Business success DTOs are never mocked. Faults only delay/drop actual transport. Offline is real network state; visibility/window focus events are simulated. Screenshots require independent visual review; no real cloud, photos, TV or production.')
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
