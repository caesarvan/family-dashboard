"""Real HTTPS/photo metadata flows. Only provider setup and legacy rows are fixtures."""
from contextlib import ExitStack, closing
from io import BytesIO
import hashlib
import importlib
import json
from pathlib import Path
import re
import secrets
import sqlite3
import sys
import tempfile
import time
import traceback
from unittest.mock import patch

from PIL import Image
from playwright.sync_api import expect
from werkzeug.serving import ThreadedWSGIServer
from browser_expo_finance_check import button, sha
from browser_expo_trip_recap_check import Run as MediaRun
from browser_expo_local_photo_check import Run as LocalRun
from scripts.check_expo_calendar_conflicts_browser import Run as CalendarRun

HARNESS = 'tests/browser_expo_photo_duplicates_check.py'
CASES = ('cross_source_pages', 'coverage_and_draft', 'identity_and_revocation')
CASE_SCREENSHOTS = dict(zip(CASES, (3, 3, 4)))
LABEL = '展示副本一致，原图未核验'


def picture(color='#496654'):
    stream = BytesIO()
    with Image.new('RGB', (48, 32), color) as image:
        image.save(stream, 'JPEG', quality=91)
    return stream.getvalue()


def scan_button(scope, refresh=False):
    # Paper's icon may prefix the accessible name. No Python-only regexp escapes.
    name = '重新查找重复照片' if refresh else '查找重复照片'
    result = scope.get_by_role('button', name=re.compile(name + '$'))
    expect(result).to_have_count(1)
    return result


class Run(MediaRun):
    capture = CalendarRun.capture
    record = LocalRun.record
    completed_json = LocalRun.completed_json

    def __init__(self, root, bundle, folder, report, out, lifecycle):
        assert ThreadedWSGIServer.block_on_close is True
        lifecycle.enter_context(patch.object(ThreadedWSGIServer, 'daemon_threads', False))
        super().__init__(root, bundle, folder, report, out, lifecycle)
        modules = ('app', 'household_media', 'media_images', 'media_crypto', 'media_local_upload',
                   'member_sessions', 'membership_storage', 'home_assistant', 'google_photos_picker')
        for name in modules:
            actual = Path(importlib.import_module(name).__file__).resolve()
            assert actual == (root / (name + '.py')).resolve()
            report.setdefault('fixtureHashes', {})[name + '.py'] = sha(actual)
        for name in ('browser_expo_photo_duplicates_check', 'browser_expo_local_photo_check'):
            actual = Path(sys.modules[name].__file__).resolve()
            assert actual == (root / 'tests' / (name + '.py')).resolve()
            report['fixtureHashes']['tests/' + name + '.py'] = sha(actual)
        report['fixtureHashes']['scripts/check_expo_calendar_conflicts_browser.py'] = sha(root / 'scripts/check_expo_calendar_conflicts_browser.py')
        def forbidden(*_args, **_kwargs):
            report['unexpectedProviderAttempts'].append('external provider/model')
            raise AssertionError('Provider/model forbidden')
        lifecycle.enter_context(patch.object(sys.modules['google_photos_picker'], '_transport', forbidden))
        lifecycle.enter_context(patch.object(self.engine.accounts, 'active_provider', forbidden))
        for name in ('_model_json', 'model_plan', 'model_journey_brief'):
            lifecycle.enter_context(patch.object(sys.modules['home_assistant'], name, forbidden))

    def snapshot(self):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        tables = ('media_items', 'media_imports', 'media_tv_grants', 'audit', 'settings')
        with closing(sqlite3.connect(self.database)) as con:
            return {name: hashlib.sha256(repr(sorted(con.execute('SELECT * FROM ' + name).fetchall(), key=repr)).encode()).hexdigest() for name in tables}

    def assert_readonly(self, mark, before):
        assert self.snapshot() == before
        assert not [r for r in self.requests[mark:] if r['path'].startswith('/api/') and r['method'] != 'GET'], self.requests[mark:]

    def confirm(self, ctx, detail):
        uid = detail['import']['id']
        self.write(ctx, 'POST', '/api/media/imports/' + uid + '/confirm', {
            'revision': detail['import']['revision'], 'confirmRequestId': secrets.token_hex(16),
            'itemIds': [r['id'] for r in detail['items']], 'consentVersion': 'media-v1', 'persistSelected': True})
        return [self.get(ctx, '/api/media/items/' + r['id'])['item'] for r in detail['items']]

    def google(self, ctx, raw, count=1):
        saved = []
        while len(saved) < count:
            size = min(20, count - len(saved))
            batch = self.write(ctx, 'POST', '/api/media/imports', {
                'requestId': secrets.token_hex(16), 'accountId': self.synthetic_accounts[1],
                'consentVersion': 'media-v1', 'allowTemporaryProcessing': True}, 202)['import']
            job = self.engine.claim_next(); assert job['action'] == 'create'
            assert self.engine.complete(job, self.media_fixture.session((None, None, [time.time()], None)))
            selected = [self.media_fixture.selected(secrets.token_hex(12)) for _ in range(size)]
            job = self.engine.claim_next(); assert job['action'] == 'list'
            assert self.engine.complete(job, selected)
            preview = self.images.sanitize_media_preview(raw, 'image/jpeg')
            while (job := self.engine.claim_next()) is not None:
                if job['action'] == 'cleanup':
                    assert self.engine.complete(job, None); break
                assert job['action'] == 'download'
                assert self.engine.complete(job, {'mediaId': job['media']['id'], 'manifest': selected, 'preview': preview})
            for item in self.confirm(ctx, self.get(ctx, '/api/media/imports/' + batch['id'])):
                saved.append(self.write(ctx, 'PATCH', '/api/media/items/' + item['id'], {
                    'revision': item['revision'], 'caption': '合成云来源副本 ' + str(len(saved) + 1)})['item'])
        return saved

    def local(self, ctx, raw, caption='合成本人本地原项'):
        detail = self.write(ctx, 'POST', '/api/media/local-imports', {
            'requestId': secrets.token_hex(16), 'consentVersion': 'media-v1', 'allowTemporaryProcessing': True,
            'files': [{'clientFileId': secrets.token_hex(16), 'filename': '合成同源字节.jpg',
                       'contentType': 'image/jpeg', 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}]}, 201)
        response = ctx.request.put(self.base + '/api/media/local-imports/' + detail['import']['id'] + '/files/' + detail['upload']['files'][0]['slotId'],
            data=raw, headers={'Content-Type': 'image/jpeg', 'Origin': self.base,
                              'X-CSRF-Token': self.get(ctx, '/api/me')['csrf'], 'X-Import-Revision': str(detail['import']['revision'])})
        assert response.status == 200
        uploaded = response.json()
        finished = self.write(ctx, 'POST', '/api/media/local-imports/' + detail['import']['id'] + '/finish', {
            'revision': uploaded['import']['revision'], 'requestId': secrets.token_hex(16)})
        item = self.confirm(ctx, finished)[0]
        return self.write(ctx, 'PATCH', '/api/media/items/' + item['id'], {'revision': item['revision'], 'caption': caption})['item']

    def fixture(self, ctx, count=1, different=False):
        raw = picture(); google = self.google(ctx, raw, count)
        local = self.local(ctx, picture('#f18a31') if different else raw)
        previews = [ctx.request.get(self.base + '/api/media/items/' + p['id'] + '/preview').body() for p in (google[0], local)]
        assert (previews[0] == previews[1]) is not different
        self.record('real-source-fixture', {'originalSha256': hashlib.sha256(raw).hexdigest(),
            'googleIds': [x['id'] for x in google], 'localId': local['id'], 'sameDisplayBytes': not different,
            'previewSha256': [hashlib.sha256(x).hexdigest() for x in previews], 'providerSetupSynthetic': True}, 'databaseEvidence')
        return google, local

    def legacy_cap(self, template):
        """Over-cap legacy fixture: genuine encrypted copies, no fake match hashes."""
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with self.engine.transaction(True) as con:
            source = dict(con.execute('SELECT * FROM media_items WHERE id=?', (template['id'],)).fetchone())
            meta = self.engine._metadata(source)
            columns = list(source)
            for n in range(1001):
                row = source | {'id': f'{n:024x}', 'source_key': f'synthetic-legacy-source-{n}'}
                value = meta | {'sourceKey': row['source_key'], 'caption': f'合成历史展示副本 {n:04}'}
                if n == 0:
                    value.pop('sha256')  # An old absent fingerprint, not a fabricated different image.
                row['metadata_cipher'] = self.engine._seal('media-metadata', row, value)
                con.execute('INSERT INTO media_items (' + ','.join(columns) + ') VALUES (' + ','.join('?' for _ in columns) + ')', [row[k] for k in columns])

    @staticmethod
    def path(uid, offset=0):
        return '/api/media/items/' + uid + '/duplicates?limit=20&offset=' + str(offset)

    def editor(self, page):
        return page.get_by_test_id('photo-editor')

    def panel(self, page):
        return page.get_by_test_id('photo-duplicate-hints')

    def open_photo(self, page, item):
        page.goto(self.base + '/app/photos'); page.bring_to_front()
        expect(page.get_by_role('heading', name='相册', exact=True)).to_be_visible(timeout=15000)
        page.get_by_label('查看照片：' + item['caption'], exact=True).click()
        expect(self.editor(page).get_by_role('textbox', name='照片说明', exact=True)).to_have_value(item['caption'], timeout=15000)
        expect(scan_button(self.panel(page))).to_be_enabled(timeout=15000)

    def scan(self, page, item, name, offset=0, trigger=None):
        action = trigger or (lambda: scan_button(self.panel(page), bool(self.panel(page).get_by_text(LABEL, exact=True).count())).click())
        value, _ = self.completed_json(page, name, 'GET', self.base + self.path(item['id'], offset), action)
        assert value['photoId'] == item['id'] and value['photoRevision'] == item['revision']
        assert value['offset'] == offset and value['label'] == LABEL and value['matchBasis'] == 'display-copy-sha256'
        expect(self.panel(page).get_by_text(LABEL, exact=True)).to_be_visible(timeout=15000)
        expect(scan_button(self.panel(page), True)).to_be_enabled(timeout=15000)
        rows = self.panel(page).locator('[data-testid^="photo-duplicate-"]:not([data-testid="photo-duplicate-hints"])').filter(has=page.get_by_role('button', name=re.compile('^打开原照片 ')))
        expect(rows).to_have_count(len(value['items']))
        assert rows.evaluate_all("nodes => nodes.map(n => n.dataset.testid)") == ['photo-duplicate-' + r['id'] for r in value['items']]
        return value

    def cross_source_pages(self, browser):
        with self.flow(browser) as (ctx, page):
            google, local = self.fixture(ctx, 21)
            before, mark = self.snapshot(), len(self.requests)
            self.open_photo(page, local)
            assert not any(r['path'].endswith('/duplicates') for r in self.requests[mark:])
            first = self.scan(page, local, 'explicit-first')
            assert first['total'] == 21 and first['hasMore'] and len(first['items']) == 20
            assert [r['id'] for r in first['items']] == sorted(x['id'] for x in google)[:20]
            self.capture(page, 'first-page-390', self.panel(page).get_by_text(LABEL, exact=True))
            second = self.scan(page, local, 'explicit-second', 20, lambda: button(self.panel(page), '下一页').click())
            target = second['items'][0]; assert target['id'] == sorted(x['id'] for x in google)[20]
            button(self.panel(page), '打开原照片 ' + target['caption']).click()
            expect(self.editor(page).get_by_role('textbox', name='照片说明', exact=True)).to_have_value(target['caption'])
            assert self.get(ctx, '/api/media/items/' + target['id'])['item'] == target
            self.capture(page, 'original-id-detail-390', self.editor(page))
            back = self.scan(page, local, 'return-original-page', 20, lambda: button(page, '返回重复提示').click())
            assert back == second
            self.capture(page, 'return-page-two-390', self.panel(page))
            self.assert_readonly(mark, before)
            self.record('original-ids-readonly', {'before': before, 'after': self.snapshot(), 'first': first, 'second': second, 'returned': back}, 'databaseEvidence')
            self.passed('390px explicit cross-source scan, exact original IDs, second-page detail and fresh same-page return; no business mutation')

    def coverage_and_draft(self, browser):
        with self.flow(browser) as (ctx, page):
            page.set_viewport_size({'width': 1280, 'height': 900})
            google, different = self.fixture(ctx, different=True)
            self.open_photo(page, different)
            before, mark = self.snapshot(), len(self.requests)
            empty = self.scan(page, different, 'different-display-zero')
            assert empty['total'] == 0
            expect(self.panel(page).get_by_text('本次检查未找到展示副本一致的照片', exact=True)).to_be_visible()
            self.capture(page, 'no-match-1280', self.panel(page))
            self.assert_readonly(mark, before)
            button(page, '关闭').click()
            # This new local upload uses exactly the Google JPEG; no fingerprint is substituted.
            anchor = self.local(ctx, picture(), '合成上限检查原项')
            self.legacy_cap(google[0]); self.open_photo(page, anchor)
            before, mark = self.snapshot(), len(self.requests)
            capped = self.scan(page, anchor, 'bounded-partial')
            assert capped['coverage'] == {'scope': 'mine', 'scanLimit': 1000, 'scanned': 999, 'capped': True, 'unverifiable': 1}
            assert capped['total'] == 999
            expect(self.panel(page).get_by_text(re.compile('^仅检查了部分已保存照片。'))).to_be_visible()
            self.capture(page, 'partial-coverage-1280', self.panel(page).get_by_text(re.compile('^仅检查了部分已保存照片。')))
            target = capped['items'][0]
            button(self.panel(page), '打开原照片 ' + target['caption']).click()
            field = self.editor(page).get_by_role('textbox', name='照片说明', exact=True)
            expect(field).to_have_value(target['caption']); field.fill('合成未保存草稿仍保留')
            button(page, '返回重复提示').click()
            expect(page.get_by_text('离开照片详情？', exact=True)).to_be_visible()
            button(page, '返回').click()
            expect(field).to_have_value('合成未保存草稿仍保留')
            self.capture(page, 'dirty-return-kept-1280', field)
            assert self.get(ctx, '/api/media/items/' + target['id'])['item'] == target
            field.fill(target['caption'])
            returned = self.scan(page, anchor, 'clean-return', trigger=lambda: button(page, '返回重复提示').click())
            assert returned == capped
            self.assert_readonly(mark, before)
            self.record('partial-and-draft-no-write', {'before': before, 'after': self.snapshot(), 'partial': capped, 'originalItem': target}, 'databaseEvidence')
            self.passed('1280px honest zero/1000-cap/unverifiable scope and original-detail dirty return preserves draft without writing')

    def identity_and_revocation(self, browser):
        with self.flow(browser) as (owner, page):
            google, local = self.fixture(owner)
            local = self.write(owner, 'PATCH', '/api/media/items/' + local['id'], {'revision': local['revision'], 'visibility': 'shared'})['item']
            peer = self.context(browser, 2); self.lifecycle.callback(peer.close)
            family = self.create_family(owner)
            child = self.context(browser, None); self.lifecycle.callback(child.close)
            assert child.request.get(self.base + family['entry']).status == 200; self.login(child)
            tv = self.context(browser, None); self.lifecycle.callback(tv.close)
            pair = tv.request.post(self.base + '/api/pair/start', data={}); assert pair.status == 200
            self.write(owner, 'POST', '/api/pair/approve', {'code': pair.json()['code'], 'name': '合成重复提示电视'})
            assert tv.request.post(self.base + '/api/pair/poll', data={'secret': pair.json()['secret']}).json()['approved']
            statuses = {name: ctx.request.get(self.base + self.path(local['id'])).status for name, ctx in [('peer', peer), ('otherHousehold', child), ('tv', tv)]}
            assert statuses == {'peer': 404, 'otherHousehold': 404, 'tv': 403}
            peer_page = peer.new_page(); peer_page.goto(self.base + '/app/photos')
            button(peer_page, '家人共享').click(); peer_page.get_by_label('查看照片：' + local['caption'], exact=True).click()
            expect(self.editor(peer_page)).to_be_visible(); expect(self.panel(peer_page)).to_have_count(0)
            local = self.write(owner, 'PATCH', '/api/media/items/' + local['id'], {'revision': local['revision'], 'visibility': 'private'})['item']
            expect(self.editor(peer_page)).not_to_be_visible(timeout=15000)
            expect(peer_page.get_by_label('查看照片：' + local['caption'], exact=True)).to_have_count(0)
            assert peer.request.get(self.base + '/api/media/items/' + local['id']).status == 404
            self.capture(peer_page, 'shared-revoked-cleared-390', peer_page.locator('body'))
            self.open_photo(page, local); self.scan(page, local, 'owner-authorized')
            before, mark = self.snapshot(), len(self.requests)
            owner.set_offline(True); page.evaluate("() => window.dispatchEvent(new Event('offline'))")
            expect(self.panel(page)).to_have_count(0); expect(self.editor(page)).not_to_be_visible()
            self.capture(page, 'offline-content-hidden-390', page.get_by_text('照片内容已隐藏', exact=True))
            owner.set_offline(False); page.evaluate("() => window.dispatchEvent(new Event('online'))")
            expect(scan_button(self.panel(page))).to_be_enabled(timeout=15000)
            self.scan(page, local, 'online-explicit-rescan')
            # A real source-permission change; metadata polling must invalidate,
            # without starting another expensive duplicate scan.
            scan_count = self.count_requests('GET', '/api/media/items/' + local['id'] + '/duplicates')
            with self.engine.transaction(True) as con:
                con.execute('UPDATE cloud_accounts SET needs_reauth=1 WHERE id=?', (self.synthetic_accounts[1],))
            expect(self.panel(page).get_by_text(LABEL, exact=True)).to_have_count(0, timeout=15000)
            expect(page.get_by_test_id('photo-duplicate-' + google[0]['id'])).to_have_count(0)
            assert self.count_requests('GET', '/api/media/items/' + local['id'] + '/duplicates') == scan_count
            self.capture(page, 'source-revoked-hints-cleared-390', self.panel(page))
            with self.engine.transaction(True) as con:
                con.execute('UPDATE cloud_accounts SET needs_reauth=0 WHERE id=?', (self.synthetic_accounts[1],))
            late = []
            endpoint = self.base + self.path(local['id'])
            def switch(route):
                response = route.fetch(max_redirects=0, timeout=15000)
                try:
                    assert response.status == 200
                    value = response.json(); assert value['items'][0]['id'] == google[0]['id']
                    self.record('late-original-before-login', value)
                    self.login(owner, 2)
                    route.fulfill(response=response)
                    late.append(value)
                finally:
                    response.dispose()
            page.route(endpoint, switch, times=1)
            try:
                scan_button(self.panel(page)).click()
                self.settle(page, lambda: len(late) == 1)
                expect(self.panel(page)).to_have_count(0, timeout=15000)
                expect(self.editor(page)).not_to_be_visible()
                expect(page.locator('body')).not_to_contain_text(local['caption'])
                expect(page.locator('body')).not_to_contain_text(google[0]['caption'])
                assert self.get(owner, '/api/me')['user']['id'] == 'member2'
                self.capture(page, 'late-identity-cleared-390', page.locator('body'))
            finally:
                page.unroute(endpoint, switch)
            assert before == self.snapshot()
            assert not [r for r in self.requests[mark:] if r['path'].startswith('/api/') and r['method'] != 'GET' and r['path'] != '/api/login']
            self.record('acl-late-no-write', {'status': statuses, 'originalAuthorizedResponse': late,
                'before': before, 'after': self.snapshot(), 'accountRevocationWasRealSqlite': True}, 'databaseEvidence')
            self.passed('Owner-only endpoint denies peer/household/TV, shared withdrawal hides detail; offline/source revocation/late actual identity switch clear stale hints without rescanning or writing')

    @classmethod
    def run_scenarios(cls, root, bundle, report, out, browser, temp_root, cases=CASES):
        for name in cases:
            case_out = out / name; case_out.mkdir()
            folder, run, before = None, None, len(report['checks'])
            count = len(report['screenshots']); case = {'name': name, 'passed': False}
            try:
                with ExitStack() as lifecycle:
                    folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='pd-', dir=temp_root)))
                    run = cls(root, bundle, folder, report, case_out, lifecycle)
                    getattr(run, name)(browser)
                assert len(report['checks']) == before + 1 and not folder.exists()
                assert len(report['screenshots']) - count == CASE_SCREENSHOTS[name]
                assert run.server is None and not run.thread.is_alive()
                case['passed'] = True
            except Exception:
                del report['checks'][before:]
                failure = traceback.format_exc(); (case_out / 'failure.txt').write_text(failure, encoding='utf-8')
                report['scenarioFailures'].append({'scenario': name, 'traceback': failure})
                print('FAIL ' + name + '\n' + failure, flush=True)
            finally:
                case['temporaryFixtureRemoved'] = folder is not None and not folder.exists()
                case['listenerStopped'] = run is not None and run.server is None and not run.thread.is_alive()
                report['scenarioResults'].append(case)
