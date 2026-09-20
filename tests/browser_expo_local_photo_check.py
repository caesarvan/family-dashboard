"""Actual selected local files -> HTTP/Pillow/encrypted SQLite -> explicit save.

No cloud accounts are seeded and no successful business responses are fabricated.
"""
from contextlib import ExitStack, closing
from io import BytesIO
import hashlib
import importlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import traceback
from unittest.mock import patch

from PIL import Image
from playwright.sync_api import expect
from werkzeug.serving import ThreadedWSGIServer
from browser_expo_finance_check import Run as BaseRun, button, sha
from scripts.check_expo_calendar_conflicts_browser import Run as CalendarRun

HARNESS = 'tests/browser_expo_local_photo_check.py'
URL = '/api/media/local-imports'
CASES = ('mobile_private_save', 'lost_responses_partial_skip', 'identity_and_acl')
CASE_SCREENSHOTS = dict(zip(CASES, (3, 3, 3)))
TEMPORARY = '允许临时处理本次设备照片，供我预览确认；未保存内容最迟 24 小时后清理。'
PERSIST = '同意将勾选照片或视频的展示副本持久保存在私密相册中。之后另行设置家庭共享和电视展示。'


def make_picture(path, kind, color):
    assert kind in ('JPEG', 'PNG', 'WEBP') and not path.exists()
    with Image.new('RGB', (96, 64), color) as image:
        image.save(path, kind)
    return {'name': path.name, 'bytes': path.stat().st_size, 'sha256': sha(path), 'format': kind}


def assert_revoked_upload(committed, pending, database):
    """A successful raw PUT remains staged, but its revoked login cannot resume."""
    assert committed['import']['id'] == pending['import']['id']
    assert committed['import']['state'] == pending['import']['state'] == 'staging'
    assert not committed['import']['canConfirm'] and not pending['import']['canConfirm']
    assert len(committed['items']) == 1
    assert [row['status'] for row in committed['upload']['files']] == ['successful']
    original_id = committed['items'][0]['id']
    assert pending['items'] == [] and pending['upload'] == {'files': [], 'canUpload': False}
    stored = next(row for row in database['items'] if row['id'] == original_id)
    assert stored['owner'] == 'member1' and stored['state'] == 'staged'
    assert stored['confirmed_at'] is None and stored['visibility'] == 'private'
    assert stored['previewBytes'] > 0 and stored['metadataBytes'] > 0
    return original_id


class Run(BaseRun):
    capture = CalendarRun.capture

    def __init__(self, root, bundle, folder, report, out, lifecycle):
        assert ThreadedWSGIServer.block_on_close is True
        lifecycle.enter_context(patch.object(ThreadedWSGIServer, 'daemon_threads', False))
        super().__init__(root, bundle, folder, report, out, lifecycle)
        self.engine = self.application.extensions['household_media']
        for name in ('app', 'household_media', 'media_local_upload', 'media_images', 'media_crypto',
                     'member_sessions', 'membership_storage', 'home_assistant', 'google_photos_picker'):
            actual = Path(importlib.import_module(name).__file__).resolve()
            assert actual == (root / (name + '.py')).resolve()
            report.setdefault('fixtureHashes', {})[name + '.py'] = sha(actual)
        for name in ('browser_expo_local_photo_check', 'browser_expo_finance_check',
                     'test_financial_files', 'test_app'):
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
        assert not self.application.config['GOOGLE_CLIENT_ID']
        with self.engine.transaction() as con:
            assert con.execute('SELECT count(*) FROM cloud_accounts').fetchone()[0] == 0
        self.raw_files = folder / 'selected-files'; self.raw_files.mkdir()

    def clear_finance(self):
        pass  # Each selected case gets a fresh isolated database.

    def record(self, name, value, group='httpEvidence'):
        target = self.out / (name + '.json')
        with target.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2); stream.write('\n')
        self.report[group].append({'path': target.relative_to(self.out.parent).as_posix(), 'sha256': sha(target)})

    def files(self, count=1, prefix='合成设备照片'):
        result, proof = [], []
        for n in range(count):
            kind, suffix, color = [('JPEG', 'jpg', '#736343'), ('PNG', 'png', '#126582'), ('WEBP', 'webp', '#795179')][n % 3]
            path = self.raw_files / (prefix + '-' + str(n + 1) + '.' + suffix)
            color = '#' + hashlib.sha256((prefix + str(n)).encode()).hexdigest()[:6]
            proof.append(make_picture(path, kind, color)); result.append(path)
        self.record(prefix + '-input', proof, 'databaseEvidence')
        return result

    def database_proof(self):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database)) as con:
            con.row_factory = sqlite3.Row
            rows = [dict(r) for r in con.execute('SELECT id,owner,account_id,state,revision,visibility,confirmed_at,length(preview_cipher) AS previewBytes,length(metadata_cipher) AS metadataBytes FROM media_items ORDER BY id')]
            for row in rows:
                if row['state'] in ('staged', 'ready'):
                    assert row['previewBytes'] > 0 and row['metadataBytes'] > 0
            return {'items': rows, 'imports': [dict(r) for r in con.execute('SELECT id,owner,state,revision FROM media_imports ORDER BY id')],
                    'audit': {r[0]: r[1] for r in con.execute("SELECT action,count(*) FROM audit WHERE action LIKE 'media_%' GROUP BY action")},
                    'accounts': con.execute('SELECT count(*) FROM cloud_accounts').fetchone()[0]}

    def import_card(self, page):
        return page.get_by_role('heading', name='添加照片', exact=True).locator('xpath=ancestor::*[@data-testid="section-card-content"][1]')

    def open_device(self, page):
        page.goto(self.base + '/app/photos'); page.bring_to_front()
        expect(page.get_by_role('heading', name='相册', exact=True)).to_be_visible(timeout=15000)
        expect(button(page, '选择照片')).to_be_enabled(); button(page, '选择照片').click()
        card = self.import_card(page); expect(card).to_be_visible()
        button(card, '设备照片').click()
        expect(card.get_by_text('从手机或电脑选择', exact=False)).to_be_visible()
        return card

    def choose(self, page, paths):
        card = self.import_card(page)
        with page.expect_file_chooser() as chooser:
            button(card, '从设备选择照片').click()
        chooser.value.set_files([str(path) for path in paths])
        # No fake File/DTO injection: the chooser supplies actual fixture bytes.
        for path in paths:
            expect(card.get_by_text(re.compile('^' + re.escape(path.name) + ' · '))).to_be_visible(timeout=15000)
        expect(card.get_by_role('checkbox', name=TEMPORARY, exact=True)).to_be_enabled()
        card.get_by_role('checkbox', name=TEMPORARY, exact=True).check()
        expect(button(card, '上传并生成预览')).to_be_enabled()

    def upload(self, page):
        with page.expect_response(lambda r: r.url.startswith(self.base + URL + '/') and r.url.endswith('/finish') and r.request.method == 'POST') as response:
            button(self.import_card(page), '上传并生成预览').click()
        assert response.value.status == 200 and response.value.finished() is None
        detail = response.value.json()
        assert detail['import']['source'] == 'local-upload' and detail['import']['canConfirm']
        expect(button(self.import_card(page), '保存选中的 ' + str(len(detail['items'])) + ' 项')).to_be_visible(timeout=15000)
        self.record('upload-finish', detail)
        return detail

    def save(self, page, detail):
        card, uid = self.import_card(page), detail['import']['id']
        card.get_by_role('checkbox', name=PERSIST, exact=True).check()
        with page.expect_response(lambda r: r.url == self.base + '/api/media/imports/' + uid + '/confirm' and r.request.method == 'POST') as response:
            button(card, '保存选中的 ' + str(len(detail['items'])) + ' 项').click()
        assert response.value.status == 200 and response.value.finished() is None
        receipt = response.value.json(); expected = {row['id'] for row in detail['items']}
        assert set(receipt['itemIds']) == expected
        expect(page.get_by_label('查看照片：未添加说明', exact=True)).to_have_count(len(expected), timeout=15000)
        self.record('original-confirm', {'request': response.value.request.post_data_json, 'response': receipt})
        return sorted(expected)

    def preview_proof(self, ctx, uid):
        item = self.get(ctx, '/api/media/items/' + uid)['item']
        assert item['id'] == uid and item['visibility'] == 'private' and item['source'] == 'local-upload' and item['accountId'] is None
        assert item['sourceCreatedAt'] is None and item['sourceTimeState'] == 'unknown'
        response = ctx.request.get(self.base + item['previewUrl']); assert response.status == 200
        raw = response.body()
        with Image.open(BytesIO(raw)) as image:
            image.load(); assert image.format == 'JPEG' and not image.info
        with self.engine.transaction() as con:
            stored = con.execute('SELECT preview_cipher,metadata_cipher FROM media_items WHERE id=?', (uid,)).fetchone()
            preview = stored[0].encode() if isinstance(stored[0], str) else bytes(stored[0])
            metadata = stored[1].encode() if isinstance(stored[1], str) else bytes(stored[1])
            assert raw not in preview and b'local-upload' not in metadata
        response.dispose()
        return {'item': item, 'previewBytes': len(raw), 'previewSha256': hashlib.sha256(raw).hexdigest(), 'encryptedAtRest': True}

    def mobile_private_save(self, browser):
        with self.flow(browser) as (ctx, page):
            assert self.get(ctx, '/api/accounts')['accounts'] == []
            paths = self.files(3); self.open_device(page); self.choose(page, paths)
            self.capture(page, 'selected-three-formats-390', button(self.import_card(page), '上传并生成预览'))
            detail = self.upload(page)
            before = self.database_proof(); assert len(before['items']) == 3 and all(r['state'] == 'staged' and r['confirmed_at'] is None and r['visibility'] == 'private' for r in before['items'])
            self.record('real-staged-before-consent', before, 'databaseEvidence')
            self.capture(page, 'preview-before-save-390', self.import_card(page).get_by_role('checkbox', name=PERSIST, exact=True))
            ids = self.save(page, detail)
            proofs = [self.preview_proof(ctx, uid) for uid in ids]
            revision = {p['item']['id']: p['item']['revision'] for p in proofs}
            page.reload(); expect(page.get_by_label('查看照片：未添加说明', exact=True)).to_have_count(3, timeout=15000)
            page.get_by_label('查看照片：未添加说明', exact=True).first.click()
            expect(page.get_by_role('textbox', name='照片说明', exact=True)).to_be_visible()
            expect(page.get_by_test_id('photo-editor')).to_contain_text('从设备上传')
            expect(page.get_by_test_id('photo-editor')).to_contain_text('设备上的原文件')
            after = self.database_proof(); assert sorted(r['id'] for r in after['items']) == ids
            assert all(r['state'] == 'ready' and r['revision'] == revision[r['id']] for r in after['items'])
            assert after['audit']['media_local_import_start'] == after['audit']['media_import_confirm'] == 1 and after['accounts'] == 0
            self.record('private-original-ids-after-reload', {'proofs': proofs, 'database': after}, 'databaseEvidence')
            self.capture(page, 'local-original-detail-390', page.get_by_role('textbox', name='照片说明', exact=True))
            self.passed('390px chooser uploads JPEG/PNG/WebP without Google; real encrypted staging precedes explicit private save; reload preserves IDs/revisions and source-specific detail')

    def drop_after_commit(self, page, pattern, records, expected_status):
        def lose(route):
            actual = route.fetch(max_redirects=0)
            try:
                assert actual.status == expected_status
                record = {'method': route.request.method, 'url': route.request.url, 'status': actual.status, 'response': actual.json()}
                if route.request.method == 'PUT':
                    raw = route.request.post_data_buffer
                    record.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), revision=route.request.headers.get('x-import-revision'))
                else:
                    record['request'] = route.request.post_data_json
                records.append(record); route.abort('failed')
            finally:
                actual.dispose()
        page.route(pattern, lose, times=1)
        return lose

    def lost_responses_partial_skip(self, browser):
        with self.flow(browser) as (ctx, page):
            page.set_viewport_size({'width': 1280, 'height': 900})
            paths = self.files(2); self.open_device(page); self.choose(page, paths)
            lost_create = []; self.drop_after_commit(page, self.base + URL, lost_create, 201)
            button(self.import_card(page), '上传并生成预览').click()
            expect(button(self.import_card(page), '核对本次上传')).to_be_enabled(timeout=15000)
            self.settle(page, lambda: len(lost_create) == 1)
            uid = lost_create[0]['response']['import']['id']; first_slot = lost_create[0]['response']['upload']['files'][0]['slotId']
            with page.expect_response(lambda r: r.url == self.base + URL and r.request.method == 'POST') as replay:
                button(self.import_card(page), '核对本次上传').click()
            assert replay.value.status == 200 and replay.value.finished() is None
            assert replay.value.json()['replayed'] and replay.value.json()['import']['id'] == uid
            assert replay.value.request.post_data_json == lost_create[0]['request']
            self.record('lost-create-original-replay', {'lost': lost_create, 'replay': replay.value.json()})
            put_path = URL + '/' + uid + '/files/' + first_slot
            lost_put = []; self.drop_after_commit(page, self.base + put_path, lost_put, 200)
            expect(button(self.import_card(page), '继续上传剩余照片')).to_be_enabled()
            button(self.import_card(page), '继续上传剩余照片').click()
            expect(button(self.import_card(page), '核对本次上传')).to_be_enabled(timeout=15000)
            self.settle(page, lambda: len(lost_put) == 1)
            assert lost_put[0]['sha256'] == sha(paths[0])
            staged = self.get(ctx, '/api/media/imports/' + uid)
            original = staged['items'][0]['id']; assert [s['status'] for s in staged['upload']['files']] == ['successful', 'pending']
            self.capture(page, 'raw-put-unknown-1280', button(self.import_card(page), '核对本次上传'))
            # A real navigation destroys File objects. Adopt the actual saved batch,
            # then explicitly end it; do not supply a replacement File or DTO.
            self.open_device(page)
            self.import_card(page).get_by_text('最近的选择', exact=True).click()
            self.import_card(page).get_by_text('从设备上传 · 正在准备预览', exact=True).click()
            expect(button(self.import_card(page), '结束本批并核对成功项')).to_be_enabled(timeout=15000)
            lost_finish = []; self.drop_after_commit(page, self.base + URL + '/' + uid + '/finish', lost_finish, 200)
            button(self.import_card(page), '结束本批并核对成功项').click()
            expect(button(self.import_card(page), '核对本次上传')).to_be_enabled(timeout=15000)
            self.settle(page, lambda: len(lost_finish) == 1)
            button(self.import_card(page), '核对本次上传').click()
            expect(button(self.import_card(page), '保存选中的 1 项')).to_be_visible(timeout=15000)
            expect(self.import_card(page).get_by_text(re.compile('^第 2 项：这张照片尚未上传，已跳过'))).to_be_visible()
            detail = self.get(ctx, '/api/media/imports/' + uid)
            assert detail['items'][0]['id'] == original and detail['upload']['files'][1]['error']['code'] == 'local_upload_incomplete'
            assert [s['status'] for s in detail['upload']['files']] == ['successful', 'skipped']
            self.capture(page, 'partial-skip-explained-1280', self.import_card(page).get_by_text(re.compile('^第 2 项：')))
            assert self.save(page, detail) == [original]
            after = self.database_proof()
            assert len(after['imports']) == len(after['items']) == 1 and after['items'][0]['id'] == original
            assert after['audit']['media_local_import_start'] == after['audit']['media_import_confirm'] == 1
            assert self.count_requests('POST', URL) == 2 and self.count_requests('PUT', put_path) == 1
            assert self.count_requests('POST', URL + '/' + uid + '/finish') == 1
            assert len([r for r in self.requests if r['method'] == 'PUT' and r['path'].startswith(URL)]) == 1
            self.record('lost-put-finish-and-original-counts', {'put': lost_put, 'finish': lost_finish, 'database': after, 'browserRequests': self.requests}, 'databaseEvidence')
            self.capture(page, 'partial-saved-once-1280', page.get_by_label('查看照片：未添加说明', exact=True))
            self.passed('Committed create/PUT/finish response loss is checked against original batch/slot; reload loses File and explicit finish skips pending with accurate reason; one media/confirm only')

    def identity_and_acl(self, browser):
        with self.flow(browser) as (owner, page):
            paths = self.files(); self.open_device(page); self.choose(page, paths)
            detail = self.upload(page); uid = self.save(page, detail)[0]
            item = self.get(owner, '/api/media/items/' + uid)['item']
            item = self.write(owner, 'PATCH', '/api/media/items/' + uid, {'revision': item['revision'], 'caption': '合成本地私密内容'})['item']
            peer = self.context(browser, 2); self.lifecycle.callback(peer.close)
            invitation = self.write(owner, 'POST', '/api/spaces/invitations', {}, 201)['invitation']
            family = self.write(owner, 'POST', '/api/spaces/redeem', {'invitation': invitation, 'name': '合成本地照片第二户', 'slug': 'local-photo-other', 'MEMBER1_PASSWORD': 'testing-password-one', 'MEMBER2_PASSWORD': 'testing-password-two'}, 201)
            child = self.context(browser, None); self.lifecycle.callback(child.close)
            assert child.request.get(self.base + family['entry']).status == 200; self.login(child)
            tv = self.context(browser, None); self.lifecycle.callback(tv.close)
            response = tv.request.post(self.base + '/api/pair/start', data={}); assert response.status == 200
            pair = response.json(); self.write(owner, 'POST', '/api/pair/approve', {'code': pair['code'], 'name': '合成本地照片电视'})
            assert tv.request.post(self.base + '/api/pair/poll', data={'secret': pair['secret']}).json()['approved']
            device = next(d for d in self.get(owner, '/api/devices') if d['name'] == '合成本地照片电视')
            acl = {}
            for name, ctx in [('peer', peer), ('otherHousehold', child)]:
                acl[name] = [ctx.request.get(self.base + '/api/media/items/' + uid + suffix).status for suffix in ('', '/preview')]
                assert acl[name] == [404, 404]
            assert self.get(tv, '/api/media-tv/items')['items'] == []
            assert tv.request.get(self.base + '/api/media-tv/items/' + uid + '/preview').status == 404
            assert tv.request.post(self.base + URL, data={}).status == 403
            item = self.write(owner, 'PATCH', '/api/media/items/' + uid, {'revision': item['revision'], 'visibility': 'shared'})['item']
            assert self.get(peer, '/api/media/items/' + uid)['item']['id'] == uid
            assert self.get(tv, '/api/media-tv/items')['items'] == []
            self.write(owner, 'PUT', '/api/media/items/' + uid + '/tv-grants', {'revision': item['revision'], 'deviceIds': [device['id']], 'consentVersion': 'media-v1', 'allowTvDisplay': True})
            assert tv.request.get(self.base + '/api/media-tv/items/' + uid + '/preview').status == 200
            peer_page = peer.new_page(); peer_page.goto(self.base + '/app/photos')
            expect(button(peer_page, '家人共享')).to_be_visible(timeout=15000); button(peer_page, '家人共享').click()
            peer_page.get_by_label('查看照片：合成本地私密内容', exact=True).click()
            expect(peer_page.get_by_test_id('photo-editor').get_by_text('合成本地私密内容', exact=True)).to_be_visible()
            self.capture(peer_page, 'explicit-shared-peer-390', peer_page.get_by_test_id('photo-editor'))
            item = self.get(owner, '/api/media/items/' + uid)['item']
            self.write(owner, 'PATCH', '/api/media/items/' + uid, {'revision': item['revision'], 'visibility': 'private'})
            expect(peer_page.get_by_text('合成本地私密内容', exact=True)).to_have_count(0, timeout=15000)
            expect(peer_page.get_by_test_id('photo-editor')).not_to_be_visible(timeout=15000)
            expect(peer_page.get_by_label('查看照片：合成本地私密内容', exact=True)).to_have_count(0)
            assert peer.request.get(self.base + '/api/media/items/' + uid).status == 404
            assert tv.request.get(self.base + '/api/media-tv/items/' + uid + '/preview').status == 404
            assert child.request.get(self.base + '/api/media/items/' + uid).status == 404
            self.capture(peer_page, 'revoked-peer-cleared-390', peer_page.get_by_role('heading', name='相册', exact=True))
            self.record('private-shared-revoked-acl', {'privateStatus': acl, 'sharedRequiredExplicitTvGrant': True, 'revokedPeerTvOther404': True})
            # Late response is a genuinely committed upload under member1, then
            # actual login changes cookies before its original response returns.
            new_paths = self.files(1, '合成晚回应私密文件'); self.open_device(page); self.choose(page, new_paths)
            late = []
            def switch(route):
                actual = route.fetch(max_redirects=0)
                try:
                    assert actual.status == 200
                    value = actual.json()
                    self.record('late-upload-committed-before-switch', {'response': value,
                        'requestSha256': hashlib.sha256(route.request.post_data_buffer).hexdigest(),
                        'database': self.database_proof()}, 'databaseEvidence')
                    self.login(owner, 2)
                    late.append(value); route.fulfill(response=actual)
                finally:
                    actual.dispose()
            page.route(re.compile(re.escape(self.base + URL) + r'/[a-f0-9]{24}/files/[a-f0-9]{24}$'), switch, times=1)
            mark = len(self.requests); button(self.import_card(page), '上传并生成预览').click()
            self.settle(page, lambda: len(late) == 1)
            expect(page.locator('body')).not_to_contain_text(new_paths[0].name, timeout=15000)
            expect(page.locator('body')).not_to_contain_text('合成本地私密内容')
            assert self.get(owner, '/api/me')['user']['id'] == 'member2'
            expect(page.get_by_role('heading', name='相册', exact=True)).to_be_visible(timeout=15000)
            expect(button(page, '选择照片')).to_be_enabled()
            expect(page.get_by_label('查看照片：合成本地私密内容', exact=True)).to_have_count(0)
            original_member = self.context(browser, 1); self.lifecycle.callback(original_member.close)
            pending_id = late[0]['import']['id']; pending = self.get(original_member, '/api/media/imports/' + pending_id)
            before = self.database_proof()
            self.record('late-upload-revoked-context-before-assert', {'originalResponse': late,
                'originalOwnerFreshRead': pending, 'database': before}, 'databaseEvidence')
            original_id = assert_revoked_upload(late[0], pending, before)
            assert not any(r['method'] == 'POST' and r['path'].endswith(('/finish', '/confirm')) for r in self.requests[mark:])
            assert peer.request.get(self.base + '/api/media/imports/' + pending_id).status == 404
            assert child.request.get(self.base + '/api/media/imports/' + pending_id).status == 404
            # Deliberate negative API probes, separate from browser write counts:
            # logging in again as the owner must not revive the old batch.
            rejected_finish = self.write(original_member, 'POST', URL + '/' + pending_id + '/finish',
                {'revision': pending['import']['revision'], 'requestId': 'rejected-finish-' + pending_id}, 410)
            rejected_confirm = self.write(original_member, 'POST', '/api/media/imports/' + pending_id + '/confirm',
                {'revision': pending['import']['revision'], 'confirmRequestId': 'rejected-confirm-' + pending_id,
                 'itemIds': [original_id], 'consentVersion': 'media-v1', 'persistSelected': True}, 410)
            after = self.database_proof(); assert before == after
            self.record('late-committed-upload-no-confirm', {'originalResponse': late, 'currentMember': 'member2',
                'originalPending': pending, 'rejectedFinish': rejected_finish, 'rejectedConfirm': rejected_confirm,
                'databaseBeforeNegativeProbes': before, 'databaseAfterNegativeProbes': after}, 'databaseEvidence')
            self.capture(page, 'late-upload-identity-cleared-390', page.locator('body'))
            self.passed('Private uploads reject peer/other household/TV; sharing and individual TV grant are explicit, revocation clears peer UI and bytes; committed late upload after real identity switch cannot confirm or reveal old content')

    @classmethod
    def run_scenarios(cls, root, bundle, report, out, browser, temp_root, cases=CASES):
        for name in cases:
            case_out = out / name; case_out.mkdir()
            folder, before, case = None, len(report['checks']), {'name': name, 'passed': False}
            screenshots_before = len(report['screenshots'])
            try:
                with ExitStack() as lifecycle:
                    folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='lp-', dir=temp_root)))
                    run = cls(root, bundle, folder, report, case_out, lifecycle)
                    getattr(run, name)(browser)
                assert len(report['checks']) == before + 1 and not folder.exists()
                assert len(report['screenshots']) - screenshots_before == CASE_SCREENSHOTS[name]
                assert run.server is None and not run.thread.is_alive()
                case.update(passed=True, listenerStopped=True)
            except Exception:
                del report['checks'][before:]
                failure = traceback.format_exc(); (case_out / 'failure.txt').write_text(failure, encoding='utf-8')
                report['scenarioFailures'].append({'scenario': name, 'traceback': failure})
                print('FAIL ' + name + '\n' + failure, flush=True)
            finally:
                case['temporaryFixtureRemoved'] = folder is not None and not folder.exists()
                report['scenarioResults'].append(case)
