"""Frozen Expo travel documents: real isolated Flask, SQLite, files and Edge.

Reuse the existing local server/auth fixture, never its finance scenarios.
Faults only delay/drop genuine HTTP replies or switch a real login cookie.
No successful endpoint mock, injected UI, production, cloud, or real documents.
"""
import argparse
import base64
from contextlib import ExitStack, closing
from datetime import datetime, timezone
import hashlib
from io import BytesIO
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

from PIL import Image
from playwright.sync_api import expect, sync_playwright
import browser_expo_finance_check as fixture
from browser_expo_finance_check import Run as BaseRun, button, sha, visibility

PATH = '/api/journey-documents'
PDF = b'%PDF-1.7\n% SYNTHETIC DOCUMENT ONLY\n%%EOF\n'
WIDTHS = (320, 390, 1280, 1920)
CHECKS = 9


def textfield(page, label):
    return page.get_by_role('textbox', name=label, exact=True)


class Run(BaseRun):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        assert Path(self.source.__file__).resolve() == (self.root / 'app.py').resolve()
        self.report['fixtureHashes'] = {}
        for actual, name in ((Path(fixture.__file__), 'tests/browser_expo_finance_check.py'),
                             (Path(__file__), 'tests/browser_expo_journey_documents_check.py')):
            assert sha(actual) == sha(self.root / name), name
            self.report['fixtureHashes'][name] = sha(actual)

    def clear_finance(self):
        pass  # No inherited finance scenario/reset or unrelated synthetic write.

    def snapshot(self):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database)) as con:
            return {name: sorted(con.execute('SELECT * FROM ' + name).fetchall(), key=repr)
                    for name in ('journey_documents', 'journey_workflows', 'journey_actions', 'entities', 'audit')}

    def journey(self, ctx, title):
        plan = dict(title=title, start='2028-03-02', end='2028-03-04', budget=0,
                    memberIds=['member1', 'member2'], international=False, checklist=[], shopping=[],
                    destinations=[dict(key='city', country='中国', city='上海', arrival='2028-03-02', departure='2028-03-04')],
                    segments=[dict(key='hotel', title='合成酒店分段', start='2028-03-02', end='2028-03-04')])
        preview = self.write(ctx, 'POST', '/api/journeys/preview', {'plan': plan})
        result = self.write(ctx, 'POST', '/api/journeys/apply', {'previewToken': preview['previewToken'], 'idempotencyKey': uuid4().hex}, 201)
        return self.get(ctx, '/api/journeys/' + result['id'])

    def documents(self, ctx, journey=None):
        return self.get(ctx, PATH + ('?journeyId=' + journey['id'] if journey else ''))['documents']

    def seed_document(self, ctx, journey, title, visibility='private'):
        # Fixture setup only; the main PDF/image uploads below use filechooser UI.
        payload = dict(journeyId=journey['id'], requestId=uuid4().hex, title=title, visibility=visibility,
                       segmentKey='', file=dict(name='synthetic.pdf', mimeType='application/pdf', dataBase64=base64.b64encode(PDF).decode()))
        return self.write(ctx, 'POST', PATH, payload, 201)['document'], payload

    @staticmethod
    def metadata(record, **changes):
        return {key: changes.get(key, record[key]) for key in ('revision', 'title', 'visibility', 'journeyId', 'segmentKey')}

    def trip_panel(self, page, journey):
        page.goto(self.base + '/app/trips?request=1001&item=' + journey['tripId'])
        expect(button(page, '旅行资料')).to_be_enabled(timeout=15000)
        button(page, '旅行资料').click()
        expect(page.get_by_role('heading', name='旅行资料', exact=True)).to_be_visible()
        expect(button(page, '上传资料')).to_be_enabled(timeout=15000)

    def library(self, page):
        page.goto(self.base + '/app/more')
        expect(page.get_by_label('我的旅行资料', exact=True)).to_be_visible(timeout=15000)
        page.get_by_label('我的旅行资料', exact=True).click()
        expect(page.get_by_role('heading', name='我的旅行资料', exact=True)).to_be_visible()
        expect(button(page, '上传资料')).to_be_enabled(timeout=15000)

    def select(self, page, button_name, option):
        button(page, button_name).click()
        page.get_by_role('menuitem', name=option, exact=True).click()
        expect(button(page, button_name)).to_be_enabled(timeout=15000)

    def choose_file(self, page, title, content=PDF, name='synthetic.pdf', mime='application/pdf'):
        button(page, '上传资料').click()
        with page.expect_file_chooser() as picker:
            button(page, '选择资料文件').click()
        picker.value.set_files({'name': name, 'mimeType': mime, 'buffer': content})
        expect(button(page, '确认上传资料')).to_be_enabled(timeout=15000)
        textfield(page, '资料标题').fill(title)
        expect(page.get_by_role('radio', name='仅本人可见', exact=True)).to_be_checked()

    def upload(self, page):
        with page.expect_response(lambda r: urlsplit(r.url).path == PATH and r.request.method == 'POST') as pending:
            button(page, '确认上传资料').click()
        response = pending.value
        assert response.status == 201, response.text()
        expect(button(page, '上传资料')).to_be_enabled(timeout=15000)
        return response.json()['document']

    def detail(self, page, record):
        textfield(page, '搜索资料').fill(record['title'])
        button(page, '查看资料：' + record['title']).click()
        expect(button(page, '下载资料')).to_be_enabled()

    def save_metadata(self, page, record):
        with page.expect_response(lambda r: urlsplit(r.url).path == PATH + '/' + record['id'] and r.request.method == 'PATCH') as pending:
            button(page, '保存资料修改').click()
        response = pending.value
        assert response.status == 200, response.text()
        expect(button(page, '上传资料')).to_be_enabled(timeout=15000)
        return response.json()['document']

    def downloaded(self, page):
        with page.expect_download() as pending:
            button(page, '下载资料').click()
        download = pending.value
        assert download.failure() is None
        data = Path(download.path()).read_bytes()
        self.report.setdefault('downloads', []).append({'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'filename': download.suggested_filename})
        expect(button(page, '下载资料')).to_be_enabled()
        assert page.locator('iframe,embed,object').count() == 0
        return data

    def shot(self, page, label, width, target):
        page.set_viewport_size({'width': width, 'height': 1080 if width >= 1280 else 844})
        page.evaluate('() => document.fonts.ready')
        target.scroll_into_view_if_needed()
        page.wait_for_timeout(400)  # Paper label/focus/responsive transitions.
        expect(target).to_be_in_viewport()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2'), (label, width)
        dest = self.out / f'{label}-{width}.png'
        page.screenshot(path=str(dest), full_page=False)
        self.report['screenshots'].append({'path': dest.name, 'sha256': sha(dest), 'width': width,
            'scope': 'Actual scrolled current viewport; not all internal content or physical-device coverage.'})

    def nav_lock(self, page):
        page.set_viewport_size({'width': 390, 'height': 844})
        original = page.url
        page.get_by_role('tab', name='首页', exact=True).click()
        expect(page.get_by_text('请先保存或放弃旅行资料的修改；结果不明时，先核对再离开。', exact=True)).to_be_visible()
        assert page.url == original
        expect(page.get_by_test_id('journey-documents-panel')).to_be_visible()
        button(page, '知道了').click()
        button(page, '新建记录').click()
        page.get_by_role('menuitem', name=re.compile(r'(?:^|\s)添加待办$')).click()
        expect(page.get_by_text('请先保存或放弃旅行资料的修改；结果不明时，先核对再离开。', exact=True)).to_be_visible()
        assert page.url == original
        expect(textfield(page, '名称')).to_have_count(0)  # Actual ItemEditor input.
        button(page, '知道了').click()

    def core(self, browser):
        with self.flow(browser) as (ctx, page):
            journey = self.journey(ctx, '合成资料核心旅行')
            self.trip_panel(page, journey)
            before = self.snapshot()
            title = '合成长标题凭证：上海往返交通和酒店说明，请完整核对全部文字'
            self.choose_file(page, title)
            self.select(page, '选择关联分段', '合成酒店分段')
            for width in WIDTHS:
                self.shot(page, 'document-editor', width, textfield(page, '资料标题'))
                self.shot(page, 'document-confirm', width, button(page, '确认上传资料'))
                for name in ('确认上传资料', '返回资料列表'):
                    box = button(page, name).bounding_box()
                    assert box and box['height'] >= 44 and box['width'] >= 44, (name, box)
            assert self.snapshot() == before
            record = self.upload(page)
            assert record['visibility'] == 'private' and record['segmentKey'] == 'hotel'
            self.detail(page, record)
            assert self.downloaded(page) == PDF
            button(page, '返回资料列表').click()
            image = BytesIO(); picture = Image.new('RGB', (12, 8), '#729fa8')
            exif = Image.Exif(); exif[0x010E] = 'SYNTHETIC PRIVATE METADATA'
            picture.save(image, format='PNG', exif=exif)
            self.choose_file(page, '合成图片凭证', image.getvalue(), 'synthetic.png', 'image/png')
            photo = self.upload(page)
            assert photo['mimeType'] == 'image/jpeg' and photo['filename'].endswith('.jpg')
            self.detail(page, photo)
            sanitized = Image.open(BytesIO(self.downloaded(page)))
            assert sanitized.format == 'JPEG' and sanitized.size == (12, 8) and not sanitized.getexif()
            self.restart()
            assert next(d for d in self.documents(ctx) if d['id'] == record['id'])['title'] == title
            self.passed('Real PDF and PNG file pickers write only on explicit upload, enforce default private/segment, download actual PDF/JPEG bytes without embedded content and persist across app restart')

    def sharing(self, browser):
        with self.flow(browser) as (ctx, page):
            journey = self.journey(ctx, '合成共享资料旅行')
            record, _ = self.seed_document(ctx, journey, '合成隔离凭证')
            partner, child, tv = self.context(browser, 2), self.context(browser, None), self.context(browser, None)
            try:
                pp = partner.new_page(); self.trip_panel(pp, journey)
                expect(pp.locator('body')).not_to_contain_text(record['title'])
                self.get(partner, PATH + '/' + record['id'] + '/file', 404)
                self.trip_panel(page, journey); self.detail(page, record); button(page, '编辑资料').click()
                expect(page.get_by_role('radio', name='与家庭共享', exact=True)).to_be_enabled()
                page.get_by_role('radio', name='与家庭共享', exact=True).click()
                record = self.save_metadata(page, record)
                assert record['visibility'] == 'shared'
                button(pp, '刷新资料列表').click(); expect(button(pp, '上传资料')).to_be_enabled()
                self.detail(pp, record); assert self.downloaded(pp) == PDF
                expect(button(pp, '编辑资料')).to_have_count(0); expect(button(pp, '删除这份资料')).to_have_count(0)
                assert self.documents(partner) == []
                invitation = self.write(ctx, 'POST', '/api/spaces/invitations', {}, 201)['invitation']
                entry = self.write(ctx, 'POST', '/api/spaces/redeem', dict(invitation=invitation, name='合成资料第二家庭', slug='documents-other', MEMBER1_PASSWORD='testing-password-one', MEMBER2_PASSWORD='testing-password-two'), 201)['entry']
                assert child.request.get(self.base + entry).status == 200
                self.login(child); assert self.documents(child) == []
                self.get(child, PATH + '/' + record['id'] + '/file', 404)
                pair = tv.request.post(self.base + '/api/pair/start', data={}).json()
                self.write(ctx, 'POST', '/api/pair/approve', {'code': pair['code'], 'name': '合成资料电视'})
                assert tv.request.post(self.base + '/api/pair/poll', data={'secret': pair['secret']}).json()['approved']
                self.get(tv, PATH, 403); self.get(tv, PATH + '/' + record['id'] + '/file', 403)
                assert record['title'] not in json.dumps(self.get(tv, '/api/state'), ensure_ascii=False)
            finally:
                partner.close(); child.close(); tv.close()
            self.passed('UI explicit sharing allows partner download only; personal library, real second household and paired TV retain private document isolation')

    def conflicts(self, browser):
        with self.flow(browser) as (ctx, page):
            journey = self.journey(ctx, '合成版本资料旅行'); record, _ = self.seed_document(ctx, journey, '合成旧标题')
            self.trip_panel(page, journey); self.detail(page, record); button(page, '编辑资料').click()
            expect(textfield(page, '资料标题')).to_be_enabled(); textfield(page, '资料标题').fill('合成我保留的标题')
            newer = self.write(ctx, 'PATCH', PATH + '/' + record['id'], self.metadata(record, visibility='shared'))['document']
            with page.expect_response(lambda r: r.request.method == 'PATCH' and urlsplit(r.url).path == PATH + '/' + record['id']) as reply:
                button(page, '保存资料修改').click()
            assert reply.value.status == 409
            expect(textfield(page, '资料标题')).to_have_value('合成我保留的标题')
            before, writes = self.snapshot(), self.count_requests('PATCH', PATH + '/' + record['id'])
            button(page, '读取最新资料').click(); expect(button(page, '保留我的修改')).to_be_enabled()
            button(page, '保留我的修改').click(); expect(button(page, '保存资料修改')).to_be_enabled()
            expect(page.get_by_role('radio', name='与家庭共享', exact=True)).to_be_checked()
            assert self.snapshot() == before and self.count_requests('PATCH', PATH + '/' + record['id']) == writes
            saved = self.save_metadata(page, newer)
            assert saved['title'] == '合成我保留的标题' and saved['visibility'] == 'shared' and saved['revision'] == newer['revision'] + 1
            self.passed('Real metadata CAS409 preserves draft; latest GET and explicit keep merge only changed fields, and a separate save uses the new revision')

    def unknown_upload(self, browser):
        for committed in (True, False):
            with self.flow(browser) as (ctx, page):
                journey = self.journey(ctx, '合成未知上传' + str(committed)); self.trip_panel(page, journey)
                self.choose_file(page, '合成未知资料' + str(committed)); attempts = []
                def lose(route):
                    if route.request.method != 'POST': return route.continue_()
                    attempts.append(route.request.post_data_json)
                    if committed:
                        response = route.fetch(max_redirects=0); assert response.status == 201, response.text()
                    route.abort('failed')
                page.route(self.base + PATH, lose)
                button(page, '确认上传资料').click(); expect(button(page, '核对资料当前状态')).to_be_enabled(timeout=15000)
                page.unroute(self.base + PATH, lose); assert len(attempts) == 1
                self.nav_lock(page)
                before, writes = self.snapshot(), self.count_requests('POST', PATH)
                button(page, '核对资料当前状态').click(); expect(button(page, '结束本次上传并返回列表')).to_be_enabled()
                assert self.snapshot() == before and self.count_requests('POST', PATH) == writes
                with page.expect_response(lambda r: r.request.method == 'POST' and urlsplit(r.url).path == PATH) as retry:
                    button(page, '按原请求重试上传').click()
                response = retry.value
                assert response.status == (200 if committed else 201), response.text()
                assert response.request.post_data_json == attempts[0]
                assert response.json()['replayed'] is committed
                expect(button(page, '上传资料')).to_be_enabled()
                with closing(sqlite3.connect(self.database)) as con:
                    assert con.execute('SELECT count(*) FROM journey_documents WHERE owner=? AND request_id=?', ('member1', attempts[0]['requestId'])).fetchone()[0] == 1
                page.get_by_role('tab', name='首页', exact=True).click(); expect(button(page, '安排首页')).to_be_enabled()
        self.passed('Committed and unsent upload losses stay unknown; GET never resubmits, parent navigation stays locked, explicit retry preserves exact original payload/requestId and stores one document')

    def unknown_metadata(self, browser):
        with self.flow(browser) as (ctx, page):
            journey = self.journey(ctx, '合成元数据未知旅行'); record, original = self.seed_document(ctx, journey, '合成待改资料')
            self.trip_panel(page, journey); self.detail(page, record); button(page, '编辑资料').click()
            expect(textfield(page, '资料标题')).to_be_enabled(); textfield(page, '资料标题').fill('合成已真实保存标题')
            path = PATH + '/' + record['id']
            for method, action in (('PATCH', '保存资料修改'), ('DELETE', '确认删除资料')):
                if method == 'DELETE':
                    button(page, '删除这份资料').click()
                attempts = []
                def lose(route):
                    if route.request.method != method: return route.continue_()
                    attempts.append(route.request.post_data_json)
                    response = route.fetch(max_redirects=0); assert response.status == 200, response.text()
                    route.abort('failed')
                page.route(self.base + path, lose); button(page, action).click()
                expect(button(page, '核对资料当前状态')).to_be_enabled(timeout=15000)
                page.unroute(self.base + path, lose); assert len(attempts) == 1
                before, writes = self.snapshot(), self.count_requests(method, path)
                button(page, '核对资料当前状态').click(); expect(button(page, '采用当前资料状态')).to_be_enabled()
                button(page, '采用当前资料状态').click()
                expect(button(page, '下载资料') if method == 'PATCH' else button(page, '上传资料')).to_be_enabled()
                assert self.snapshot() == before and self.count_requests(method, path) == writes
            assert not any(d['id'] == record['id'] for d in self.documents(ctx))
            self.write(ctx, 'POST', PATH, original, 409)
            assert not any(d['id'] == record['id'] for d in self.documents(ctx))
            self.passed('Real PATCH/DELETE commit with lost reply recovers through GET plus explicit adoption without another mutation; tombstoned original upload cannot resurrect the file')

    def orphan_and_pages(self, browser):
        with self.flow(browser) as (ctx, page):
            source = self.journey(ctx, '合成将删除的旅行'); target = self.journey(ctx, '合成重新关联旅行')
            record, _ = self.seed_document(ctx, source, '合成保留孤立资料', visibility='shared')
            trip = self.get(ctx, '/api/journeys/' + source['id'])['trip']
            self.write(ctx, 'DELETE', '/api/items/trips/' + source['tripId'], {'revision': trip['revision']})
            orphan = next(d for d in self.documents(ctx) if d['id'] == record['id'])
            assert orphan['journeyId'] is None and orphan['visibility'] == 'private' and orphan['revision'] == record['revision'] + 1
            self.library(page); self.detail(page, orphan); button(page, '编辑资料').click()
            expect(button(page, '选择关联旅行')).to_be_enabled()
            self.select(page, '选择关联旅行', '合成重新关联旅行')
            self.select(page, '选择关联分段', '合成酒店分段')
            saved = self.save_metadata(page, orphan)
            assert saved['id'] == orphan['id'] and saved['journeyId'] == target['id'] and saved['visibility'] == 'private'
            for index in range(13): self.seed_document(ctx, target, f'合成分页资料 {index:02d}')
            self.library(page); textfield(page, '搜索资料').fill('合成分页资料 ')
            exact_rows = page.get_by_test_id(re.compile(r'^journey-document-[a-f0-9]{32}$'))
            expect(exact_rows).to_have_count(12); button(page, '下一页资料').click(); expect(exact_rows).to_have_count(1)
            for width in WIDTHS:
                if width == 390:
                    prefs = self.get(ctx, '/api/preferences')
                    self.write(ctx, 'PUT', '/api/preferences', {'revision': prefs['revision'], 'changes': {'colorMode': 'dark'}})
                    self.library(page); textfield(page, '搜索资料').fill('合成分页资料 ')
                self.shot(page, 'document-library', width, exact_rows.first)
            self.passed('Deleting a real journey preserves owner file privately; library re-associates it explicitly, and 13 real setup records search/page with actual light/dark four-width scrolled screenshots')

    def visibility_lifecycle(self, browser):
        with self.flow(browser) as (ctx, page):
            journey = self.journey(ctx, '合成草稿恢复旅行'); self.trip_panel(page, journey)
            self.choose_file(page, '合成离线私密草稿'); before = self.snapshot()
            ctx.set_offline(True); expect(textfield(page, '资料标题')).to_be_hidden()
            ctx.set_offline(False); expect(textfield(page, '资料标题')).to_have_value('合成离线私密草稿', timeout=15000)
            self.nav_lock(page)
            visibility(page, True); expect(textfield(page, '资料标题')).to_be_hidden()
            held = []
            def hold(route):
                response = route.fetch(max_redirects=0); assert response.status == 200
                held.append((route, response))
            page.route(self.base + PATH + '?journeyId=' + journey['id'], hold, times=1)
            visibility(page, False); self.settle(page, lambda: bool(held)); visibility(page, True)
            held[0][0].fulfill(response=held[0][1]); page.wait_for_timeout(300)
            expect(textfield(page, '资料标题')).to_be_hidden()
            visibility(page, False); expect(textfield(page, '资料标题')).to_have_value('合成离线私密草稿', timeout=15000)
            assert self.snapshot() == before
            button(page, '返回资料列表').click(); button(page, '确认放弃修改').click(); expect(button(page, '上传资料')).to_be_enabled()
            self.passed('Offline and simulated background conceal private drafts, preserve same-identity file/metadata and navigation lock, discard late GET, and explicit abandon leaves business state unchanged')

    def identity_and_download(self, browser):
        with self.flow(browser) as (ctx, page):
            journey = self.journey(ctx, '合成迟到下载旅行'); record, _ = self.seed_document(ctx, journey, '合成迟到私密文件')
            self.trip_panel(page, journey); self.detail(page, record); held, downloads = [], []
            page.on('download', lambda value: downloads.append(value))
            def hold(route):
                response = route.fetch(max_redirects=0); assert response.status == 200
                held.append((route, response))
            page.route(self.base + PATH + '/' + record['id'] + '/file', hold, times=1)
            button(page, '下载资料').click(); self.settle(page, lambda: bool(held))
            self.login(ctx, 2)
            held[0][0].fulfill(response=held[0][1])
            expect(page.get_by_test_id('journey-document-detail')).to_be_hidden(timeout=15000)
            page.wait_for_timeout(300)
            assert not downloads and record['title'] not in page.locator('body').inner_text()
            self.get(ctx, PATH + '/' + record['id'] + '/file', 404)
            self.login(ctx, 1); self.trip_panel(page, journey); self.choose_file(page, '合成旧身份上传回执')
            sent = []
            def switch(route):
                if route.request.method != 'POST': return route.continue_()
                response = route.fetch(max_redirects=0); assert response.status == 201
                sent.append(response.json()['document']['id']); self.login(ctx, 2); route.fulfill(response=response)
            page.route(self.base + PATH, switch); button(page, '确认上传资料').click()
            expect(page.get_by_test_id('journey-document-editor')).to_be_hidden(timeout=15000)
            page.unroute(self.base + PATH, switch); assert len(sent) == 1
            expect(page.locator('body')).not_to_contain_text('合成旧身份上传回执')
            self.get(ctx, PATH + '/' + sent[0] + '/file', 404)
            self.passed('Real identity change before download/post-upload final checks conceals private content, emits no old download and prevents the new member from reading either file')

    def nested_navigation(self, browser):
        with self.flow(browser) as (ctx, page):
            journey = self.journey(ctx, '合成地图资料旅行')
            self.write(ctx, 'POST', '/api/journey-places', dict(requestId=uuid4().hex, name='DOCUMENTS-MAP', journeyId=journey['id'], status='planned', coordinates={'latitude': 31.23, 'longitude': 121.47}), 201)
            page.goto(self.base + '/app/map'); expect(button(page, '打开地点：DOCUMENTS-MAP')).to_be_enabled(timeout=15000)
            button(page, '打开地点：DOCUMENTS-MAP').click(); button(page, '查看旅行').click()
            expect(button(page, '旅行资料')).to_be_enabled(); button(page, '旅行资料').click(); expect(button(page, '上传资料')).to_be_enabled()
            self.choose_file(page, '合成地图未保存草稿'); self.nav_lock(page)
            assert urlsplit(page.url).path == '/app/map'
            button(page, '返回旅行资料入口').click(); button(page, '确认放弃修改').click()
            expect(button(page, '旅行资料')).to_be_enabled()
            self.library(page); self.choose_file(page, '合成资料库未保存草稿'); self.nav_lock(page)
            button(page, '返回旅行资料入口').click(); button(page, '确认放弃修改').click()
            expect(page.get_by_role('heading', name='更多', exact=True)).to_be_visible()
            page.goto(self.base + '/app/assistant'); expect(textfield(page, '告诉助理你的需求')).to_be_enabled(timeout=15000)
            textfield(page, '告诉助理你的需求').fill('旅行名称：合成助理资料旅行\n出发日期：2028-03-02\n返程日期：2028-03-04\n目的地：上海\n预算：1000元')
            expect(page.get_by_role('checkbox', name='使用已配置的 AI 整理', exact=True)).not_to_be_checked()
            button(page, '整理并预览').click(); expect(page.get_by_test_id('journey-brief-form')).to_be_visible()
            for name, value in [('旅行名称', '合成助理资料旅行'), ('出发日期', '2028-03-02'), ('返程日期', '2028-03-04'), ('旅行总预算（元）', '1000'),
                                ('国家或地区 1', '中国'), ('城市 1', '上海'), ('抵达日期 1', '2028-03-02'), ('离开日期 1', '2028-03-04')]:
                textfield(page, name).fill(value)
            page.get_by_role('radio', name='国内旅行', exact=True).click()
            member = self.get(ctx, '/api/state')['people'][0]
            checkbox = page.get_by_role('checkbox', name='出行成员：' + member['name'], exact=True)
            if checkbox.get_attribute('aria-checked') != 'true': checkbox.click()
            expect(checkbox).to_be_checked(); button(page, '核对并继续编辑').click()
            expect(button(page, '预览变更')).to_be_enabled(); button(page, '预览变更').click()
            expect(button(page, '确认保存旅行')).to_be_enabled(); button(page, '确认保存旅行').click()
            expect(button(page, '旅行资料')).to_be_enabled(timeout=15000); button(page, '旅行资料').click()
            expect(button(page, '上传资料')).to_be_enabled(); self.choose_file(page, '合成助理未保存草稿'); self.nav_lock(page)
            assert urlsplit(page.url).path == '/app/assistant'
            button(page, '返回旅行资料入口').click(); button(page, '确认放弃修改').click(); expect(button(page, '旅行资料')).to_be_enabled()
            page.get_by_role('tab', name='首页', exact=True).click(); expect(button(page, '安排首页')).to_be_enabled()
            self.passed('Actual Map and local-parser Assistant nested trips plus More library preserve dirty document navigation; explicit discard returns and unlocks normal home navigation')

    def run_scenarios(self, browser):
        for scenario in (self.core, self.sharing, self.conflicts, self.unknown_upload, self.unknown_metadata, self.orphan_and_pages,
                         self.visibility_lifecycle, self.identity_and_download, self.nested_navigation):
            scenario(browser)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--expected-build-evidence', required=True)
    args = parser.parse_args(); root, bundle = args.source_root.resolve(), args.bundle.resolve()
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    assert head == args.expected_head
    evidence_path = bundle.parent / 'build-evidence.json'; assert sha(evidence_path) == args.expected_build_evidence
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    assert evidence['sourceHead'] == head
    assert evidence['sourceTree'] == subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=root, text=True).strip()
    assert not subprocess.check_output(['git', 'status', '--porcelain=v1', '--untracked-files=no'], cwd=root, text=True).strip()
    names = subprocess.check_output(['git', 'ls-files'], cwd=root, text=True).splitlines()
    hashes = lambda: {name: sha(root / name) for name in names}
    exports = lambda: {p.relative_to(bundle).as_posix(): sha(p) for p in bundle.rglob('*') if p.is_file()}
    assert exports() == evidence['files']
    assert all(sha(root / name) == digest for name, digest in evidence['inputFiles'].items())
    out = Path(__file__).resolve().parents[1] / 'test-results' / ('expo-journey-documents-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True); shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], screenshots=[], head=head, tree=evidence['sourceTree'],
                  buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(out / 'executed-harness.py'), sourceHashesBefore=hashes(), bundleHashesBefore=exports(),
                  productionWrites=0, realCloud=False, realAI=False, physicalTelevision=False, scope='Real local Flask/SQLite/Edge and synthetic files only; visibility is simulated. Setup records use real APIs, principal uploads use the real file picker. Viewport screenshots do not cover all scrolling or physical devices.')
    original_connect = socket.socket.connect
    def local_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
            report['externalRequests'].append({'kind': 'non-loopback socket'}); raise AssertionError('External network forbidden')
        return original_connect(sock, address)
    folder = None
    try:
        with patch.object(socket.socket, 'connect', local_connect), sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            try:
                with ExitStack() as lifecycle:
                    folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='expo-documents-')))
                    Run(root, bundle, folder, report, out, lifecycle).run_scenarios(browser)
                    assert len(report['checks']) == CHECKS and len(report['screenshots']) == 12
                    assert not report['pageErrors'] and not report['externalRequests']
                    report['passed'] = True
            finally:
                browser.close()
    except Exception:
        report['passed'] = False
        report['failure'] = traceback.format_exc(); print(report['failure'], flush=True)
    finally:
        report['sourceHashesAfter'] = hashes(); report['bundleHashesAfter'] = exports()
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
