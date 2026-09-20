"""Real local photo memories flows; synthetic persisted photos, never DTO mocks."""
from contextlib import ExitStack, closing
from datetime import datetime
from io import BytesIO
import importlib
import json
from pathlib import Path
import re
import secrets
import sqlite3
import sys
import tempfile
import threading
import time
import traceback
from unittest.mock import patch
from urllib.parse import urlsplit

from PIL import Image
from playwright.sync_api import expect
from werkzeug.serving import ThreadedWSGIServer
from browser_expo_finance_check import button, sha, visibility
from browser_expo_trip_recap_check import Run as MediaRun
from scripts.check_expo_calendar_conflicts_browser import Run as CalendarRun

HARNESS = 'tests/browser_expo_photo_memories_check.py'
URL = '/api/media/memories/on-this-day'
CASES = ('mobile_page_edit', 'midnight_poll_resume', 'identity_and_revocation')
CASE_SCREENSHOTS = dict(zip(CASES, (3, 2, 3)))
TODAY = '2026-09-20T00:00:00+00:00'


class MemoryClock:
    """Only the real MediaLibrary clock is injected; browser timers keep running."""
    def __init__(self, instant=TODAY):
        self.lock = threading.Lock()
        self.set(instant)

    def set(self, instant):
        value = datetime.fromisoformat(instant)
        assert value.tzinfo is not None
        with self.lock:
            self.timestamp = value.timestamp()

    def __call__(self):
        with self.lock:
            return self.timestamp


def remove_source_time(engine, uid):
    # Legacy encrypted-row fixture, not an altered API response.
    with engine.transaction(True) as con:
        row = con.execute('SELECT * FROM media_items WHERE id=?', (uid,)).fetchone()
        value = engine._metadata(row)
        value.pop('sourceCreatedAt', None)
        con.execute('UPDATE media_items SET metadata_cipher=? WHERE id=?',
                    (engine._seal('media-metadata', row, value), uid))


def revoke_member_sessions(database, folder):
    assert database.resolve().is_relative_to(folder.resolve())
    with closing(sqlite3.connect(database)) as con:
        with con:
            changed = con.execute("UPDATE member_sessions SET revoked_at=1 WHERE owner='member1' AND revoked_at IS NULL").rowcount
            assert changed > 0
    return changed


class Run(MediaRun):
    capture = CalendarRun.capture

    def __init__(self, root, bundle, folder, report, out, lifecycle):
        assert ThreadedWSGIServer.block_on_close is True
        lifecycle.enter_context(patch.object(ThreadedWSGIServer, 'daemon_threads', False))
        super().__init__(root, bundle, folder, report, out, lifecycle)
        self.memory_clock = MemoryClock()
        # Seed import jobs at real time; install the deterministic clock only
        # after they have been confirmed and cleanup receipts persisted.
        modules = ('app', 'household_media', 'media_crypto', 'media_images', 'member_sessions',
                   'membership_storage', 'home_assistant', 'google_photos_picker')
        for name in modules:
            actual = Path(importlib.import_module(name).__file__).resolve()
            assert actual == (root / (name + '.py')).resolve()
            report.setdefault('fixtureHashes', {})[name + '.py'] = sha(actual)
        for name in ('browser_expo_photo_memories_check', 'browser_expo_finance_check', 'browser_expo_trip_recap_check'):
            actual = Path(sys.modules[name].__file__).resolve()
            assert actual == (root / 'tests' / (name + '.py')).resolve()
            report['fixtureHashes']['tests/' + name + '.py'] = sha(actual)
        report['fixtureHashes']['scripts/check_expo_calendar_conflicts_browser.py'] = sha(root / 'scripts/check_expo_calendar_conflicts_browser.py')
        def forbidden(*_args, **_kwargs):
            report['unexpectedProviderAttempts'].append('external provider/model')
            raise AssertionError('External provider/model forbidden')
        lifecycle.enter_context(patch.object(sys.modules['google_photos_picker'], '_transport', forbidden))
        lifecycle.enter_context(patch.object(self.engine.accounts, 'active_provider', forbidden))
        for name in ('_model_json', 'model_plan', 'model_journey_brief'):
            lifecycle.enter_context(patch.object(sys.modules['home_assistant'], name, forbidden))

    def record(self, name, value, group='httpEvidence'):
        target = self.out / (name + '.json')
        with target.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2); stream.write('\n')
        self.report[group].append({'path': target.relative_to(self.out.parent).as_posix(), 'sha256': sha(target)})

    def set_day(self, instant=TODAY):
        self.memory_clock.set(instant)
        self.engine.clock = self.memory_clock

    @staticmethod
    def path(offset=0):
        return URL + '?limit=24&offset=' + str(offset)

    def seed_photos(self, ctx, specs, member=1):
        """Real import/confirm/PATCH; only provider job completions are fixtures."""
        saved = []
        for start in range(0, len(specs), 20):
            batch = specs[start:start + 20]
            imported = self.write(ctx, 'POST', '/api/media/imports', dict(requestId=secrets.token_hex(16),
                accountId=self.synthetic_accounts[member], consentVersion='media-v1', allowTemporaryProcessing=True), 202)['import']
            job = self.engine.claim_next(); assert job and job['action'] == 'create'
            assert self.engine.complete(job, self.media_fixture.session((None, None, [time.time()], None)))
            selected = []
            for stamp, caption in batch:
                source = self.media_fixture.selected(secrets.token_hex(12))
                source['createTime'] = stamp or '2025-09-20T00:00:00Z'
                selected.append(source)
            job = self.engine.claim_next(); assert job and job['action'] == 'list'
            assert self.engine.complete(job, selected)
            while (job := self.engine.claim_next()) is not None:
                if job['action'] == 'cleanup':
                    assert self.engine.complete(job, None)
                    break
                assert job['action'] == 'download'
                stream = BytesIO(); Image.new('RGB', (48, 32), '#69774a').save(stream, 'PNG')
                jpeg = self.images.sanitize_media_preview(stream.getvalue(), 'image/png')
                assert self.engine.complete(job, dict(mediaId=job['media']['id'], manifest=selected, preview=jpeg))
            detail = self.get(ctx, '/api/media/imports/' + imported['id'])
            assert detail['import']['canConfirm'] and len(detail['items']) == len(batch)
            self.write(ctx, 'POST', '/api/media/imports/' + imported['id'] + '/confirm', dict(revision=detail['import']['revision'],
                confirmRequestId=secrets.token_hex(16), itemIds=[row['id'] for row in detail['items']], consentVersion='media-v1', persistSelected=True))
            for row, (stamp, caption) in zip(detail['items'], batch):
                item = self.get(ctx, '/api/media/items/' + row['id'])['item']
                item = self.write(ctx, 'PATCH', '/api/media/items/' + item['id'], dict(revision=item['revision'], caption=caption))['item']
                if stamp is None:
                    remove_source_time(self.engine, item['id'])
                    item = self.get(ctx, '/api/media/items/' + item['id'])['item']
                assert item['sourceCreatedAt'] == stamp and item['visibility'] == 'private'
                saved.append(item)
        return saved

    def open_memories(self, page):
        page.goto(self.base + '/app/photos'); page.bring_to_front()
        expect(page.get_by_role('heading', name='相册', exact=True)).to_be_visible(timeout=15000)
        with page.expect_response(lambda r: r.url == self.base + self.path() and r.request.method == 'GET') as pending:
            button(page, '那年今日').click()
        return self.checked_page(page, pending.value)

    def checked_page(self, page, response):
        assert response.status == 200 and response.finished() is None
        value = response.json()
        expect(page.get_by_test_id('photo-memories-summary')).to_be_visible(timeout=15000)
        expect(page.get_by_label('正在读取相册', exact=True)).to_have_count(0)
        expect(page.get_by_text(f"共 {value['total']} 项 · 第 {value['offset'] // 24 + 1} 页", exact=True)).to_be_visible()
        labels = page.get_by_label(re.compile('^查看照片：'))
        expect(labels).to_have_count(len(value['items']))
        assert labels.evaluate_all("nodes => nodes.map(n => n.getAttribute('aria-label'))") == [
            '查看照片：' + row['item']['caption'] for row in value['items']]
        return value

    def next_page(self, page):
        with page.expect_response(lambda r: r.url == self.base + self.path(24) and r.request.method == 'GET') as pending:
            button(page, '下一页').click()
        return self.checked_page(page, pending.value)

    def db_rows(self):
        with closing(sqlite3.connect(self.database)) as con:
            con.row_factory = sqlite3.Row
            return [dict(row) for row in con.execute('SELECT id,owner,state,revision,visibility,confirmed_at FROM media_items ORDER BY id')]

    def mobile_page_edit(self, browser):
        with self.flow(browser) as (ctx, page):
            specs = [('2025-09-19T16:00:00Z', f'合成去年同日 {n:02}') for n in range(20)]
            specs += [('2024-09-20T15:59:59Z', f'合成前年同日 {n:02}') for n in range(10)]
            specs += [(None, '合成来源未知一'), (None, '合成来源未知二'),
                      ('2026-09-20T00:00:00Z', '合成今年不纳入'), ('2025-09-20T16:00:00Z', '合成相邻日期不纳入')]
            self.seed_photos(ctx, specs); self.set_day()
            first = self.open_memories(page)
            assert first['total'] == 30 and first['unknownSourceTimeCount'] == 2
            expect(page.get_by_test_id('photo-memories-summary')).to_contain_text('2 张照片没有可核对的来源日期')
            expect(page.get_by_role('heading', name='2025 年 · 1 年前', exact=True)).to_be_visible()
            expect(page.get_by_role('heading', name='2024 年 · 2 年前', exact=True)).to_have_count(1)
            self.capture(page, 'memories-years-390', page.get_by_test_id('photo-memories-summary'))
            second = self.next_page(page); assert len(second['items']) == 6
            assert not set(row['item']['id'] for row in first['items']) & set(row['item']['id'] for row in second['items'])
            target = second['items'][0]['item']; before = self.db_rows()
            path = '/api/media/items/' + target['id']
            with page.expect_response(lambda r: r.url == self.base + path and r.request.method == 'GET') as original:
                page.get_by_label('查看照片：' + target['caption'], exact=True).click()
            assert original.value.status == 200 and original.value.json()['item']['revision'] == target['revision']
            field = page.get_by_role('textbox', name='照片说明', exact=True)
            expect(field).to_have_value(target['caption']); field.fill('合成从那年今日修改原照片')
            with page.expect_response(lambda r: r.url == self.base + path and r.request.method == 'PATCH') as saved:
                button(page, '保存照片设置').click()
            response = saved.value; assert response.status == 200 and response.finished() is None
            assert response.request.post_data_json['revision'] == target['revision']
            expect(page.get_by_text('照片设置已保存。', exact=True)).to_be_visible()
            expect(button(page, '保存照片设置')).to_be_disabled()
            self.capture(page, 'original-photo-edited-390', field)
            button(page, '关闭').click(); expect(field).to_have_count(0)
            current = self.get(ctx, self.path(24))
            expect(page.get_by_text('共 30 项 · 第 2 页', exact=True)).to_be_visible()
            expect(page.get_by_label('查看照片：合成从那年今日修改原照片', exact=True)).to_be_visible()
            after = self.db_rows(); assert len(before) == len(after)
            assert [v['id'] for v in before] == [v['id'] for v in after]
            changes = [(a, b) for a, b in zip(before, after) if a != b]
            assert len(changes) == 1 and changes[0][0]['id'] == target['id']
            assert changes[0][1] == {**changes[0][0], 'revision': target['revision'] + 1}
            assert next(row['item'] for row in current['items'] if row['item']['id'] == target['id'])['sourceCreatedAt'] == target['sourceCreatedAt']
            assert self.count_requests('PATCH', path) == 1
            self.capture(page, 'same-page-return-390', page.get_by_label('查看照片：合成从那年今日修改原照片', exact=True))
            self.record('pages-and-original-write', dict(first=first, second=second, returned=current,
                request=response.request.post_data_json, response=response.json()))
            self.record('same-id-revision-only', dict(before=before, after=after), 'databaseEvidence')
            self.passed('390px: real source-date/year/unknown pagination and original-ID revision edit return to the same second page, without copies')

    def midnight_poll_resume(self, browser):
        with self.flow(browser) as (ctx, page):
            page.set_viewport_size({'width': 1280, 'height': 900})
            specs = [(f'2025-09-{day:02}T00:00:00Z', f'合成{day}日照片 {n:02}') for day in (19, 20, 21) for n in range(25)]
            self.seed_photos(ctx, specs); self.set_day('2026-09-19T15:59:59+00:00')
            self.open_memories(page); self.next_page(page)
            before = self.snapshot(); mark = len(self.requests)
            for day, hidden in ((20, False), (21, True)):
                if hidden:
                    self.next_page(page); visibility(page, True)
                    expect(page.get_by_test_id('photo-memories-summary')).to_have_count(0)
                page.evaluate("""() => {window.__memoryStates=[];window.__memoryObserver?.disconnect();
                  const take=()=>{const summary=document.querySelector('[data-testid="photo-memories-summary"]');
                    if(summary)window.__memoryStates.push({summary:summary.textContent,second:document.body.textContent.includes('第 2 页')});};
                  window.__memoryObserver=new MutationObserver(take);window.__memoryObserver.observe(document.body,{childList:true,subtree:true,characterData:true});take();}""")
                # Genuine five-second polling (visible) or genuine lifecycle
                # resume (hidden); never advance browser timers or replace DTOs.
                with page.expect_response(lambda r: r.url == self.base + self.path() and r.request.method == 'GET', timeout=15000) as reset:
                    with page.expect_response(lambda r: r.url == self.base + self.path(24) and r.request.method == 'GET', timeout=15000) as obsolete:
                        self.set_day(f'2026-09-{day-1:02}T16:00:00+00:00')
                        if hidden: visibility(page, False)
                assert obsolete.value.status == 200 and obsolete.value.finished() is None
                old_offset = obsolete.value.json(); current = self.checked_page(page, reset.value)
                assert old_offset['referenceDate'] == current['referenceDate'] == f'2026-09-{day:02}'
                assert old_offset['offset'] == 24 and len(old_offset['items']) == 1
                assert current['offset'] == 0 and len(current['items']) == 24
                states = page.evaluate('() => {window.__memoryObserver.disconnect();return window.__memoryStates;}')
                assert not any(f'9 月 {day} 日' in row['summary'] and row['second'] for row in states), states
                expect(page.get_by_test_id('photo-memories-summary')).to_contain_text(f'9 月 {day} 日')
                self.record(f'midnight-{day}', dict(serverEpoch=self.memory_clock(), oldOffset=old_offset, reset=current,
                    observations=states, trigger='visibility-resume' if hidden else 'natural-five-second-poll'))
                self.capture(page, f'midnight-{day}-1280', page.get_by_test_id('photo-memories-summary'))
            assert self.snapshot() == before
            assert all(r['method'] == 'GET' for r in self.requests[mark:] if r['path'].startswith('/api/'))
            self.record('midnight-no-business-writes', {'rows': self.db_rows(), 'unchanged': True}, 'databaseEvidence')
            self.passed('1280px: real server Beijing midnight resets second-page poll and hidden/resume to page one; old offset never installed under the new date')

    def identity_and_revocation(self, browser):
        with self.flow(browser) as (ctx, page):
            owner = self.seed_photos(ctx, [('2025-09-20T00:00:00Z', '合成本人私密日期'), (None, '合成本人未知日期')])[0]
            partner = self.context(browser, 2); self.lifecycle.callback(partner.close)
            theirs = self.seed_photos(partner, [('2024-09-20T00:00:00Z', '合成伴侣自己的日期')], 2)[0]
            owner = self.write(ctx, 'PATCH', '/api/media/items/' + owner['id'], {'revision': owner['revision'], 'visibility': 'shared'})['item']
            family = self.create_family(ctx)
            child = self.context(browser, None); self.lifecycle.callback(child.close)
            assert child.request.get(self.base + family['entry']).status == 200; self.login(child)
            tv = self.context(browser, None); self.lifecycle.callback(tv.close)
            pair = tv.request.post(self.base + '/api/pair/start', data={}); assert pair.status == 200
            self.write(ctx, 'POST', '/api/pair/approve', {'code': pair.json()['code'], 'name': '合成回顾电视'})
            assert tv.request.post(self.base + '/api/pair/poll', data={'secret': pair.json()['secret']}).json()['approved']
            self.set_day()
            owned, peer, other = [self.get(c, self.path()) for c in (ctx, partner, child)]
            assert owned['total'] == 1 and owned['unknownSourceTimeCount'] == 1
            assert peer['total'] == 1 and peer['unknownSourceTimeCount'] == 0 and peer['items'][0]['item']['id'] == theirs['id']
            assert other['total'] == 0 and other['unknownSourceTimeCount'] == 0
            assert owner['id'] not in json.dumps([peer, other]) and '2025-09-20' not in json.dumps([peer, other])
            denied = self.get(tv, self.path(), 403)
            self.record('owner-peer-other-tv', dict(owner=owned, peer=peer, otherHousehold=other, television403=denied))
            self.open_memories(page)
            page.get_by_label('查看照片：' + owner['caption'], exact=True).click()
            field = page.get_by_role('textbox', name='照片说明', exact=True)
            expect(field).to_have_value(owner['caption']); field.fill('合成离线草稿不外露')
            mark, before = len(self.requests), self.snapshot()
            ctx.set_offline(True); page.evaluate("() => window.dispatchEvent(new Event('offline'))")
            expect(field).to_have_count(0); expect(page.get_by_test_id('photo-memories-summary')).to_have_count(0)
            self.capture(page, 'offline-concealed-390', page.get_by_text('照片内容已隐藏', exact=True))
            ctx.set_offline(False); page.evaluate("() => window.dispatchEvent(new Event('online'))")
            expect(field).to_have_value('合成离线草稿不外露', timeout=15000)
            field.fill(owner['caption']); button(page, '关闭').click(); expect(field).to_have_count(0)
            old = []
            def switch(route):
                actual = route.fetch(max_redirects=0); assert actual.status == 200
                value = actual.json(); assert value['items'][0]['item']['id'] == owner['id']
                self.login(ctx, 2)
                old.append(value); route.fulfill(response=actual)
            target = self.base + self.path(); page.route(target, switch, times=1)
            try:
                # Natural five-second polling consumes this route. An extra
                # click races the resulting identity clear/remount; the icon
                # button also does not have the exact accessible name "刷新".
                self.settle(page, lambda: len(old) == 1)
                expect(page.get_by_label('查看照片：' + owner['caption'], exact=True)).to_have_count(0)
                expect(page.locator('body')).not_to_contain_text('合成离线草稿不外露')
                assert self.get(ctx, '/api/me')['user']['id'] == 'member2'
                self.capture(page, 'changed-member-cleared-390', page.locator('body'))
            finally:
                page.unroute(target, switch)
            # An independent original-member session proves actual server
            # revocation, not just a transport error or a synthetic /me DTO.
            fresh = self.context(browser, 1); self.lifecycle.callback(fresh.close)
            revoked_page = fresh.new_page(); self.open_memories(revoked_page)
            changed = revoke_member_sessions(self.database, self.folder)
            visibility(revoked_page, True); visibility(revoked_page, False)
            expect(revoked_page.get_by_test_id('photo-memories-summary')).to_have_count(0)
            expect(revoked_page.get_by_label('查看照片：' + owner['caption'], exact=True)).to_have_count(0)
            assert fresh.request.get(self.base + self.path()).status == 401
            self.capture(revoked_page, 'revoked-session-cleared-390', revoked_page.locator('body'))
            assert self.snapshot() == before
            writes = [r for r in self.requests[mark:] if r['method'] != 'GET' and r['path'].startswith('/api/') and r['path'] != '/api/login']
            assert not writes, writes
            self.record('late-read-and-real-revocation', dict(oldAuthorizedResponse=old, revokedSessions=changed,
                peerCurrent=self.get(ctx, self.path()), businessRowsUnchanged=True), 'databaseEvidence')
            self.passed('Owner-only dates/counters remain isolated across member, household and paired TV; offline hides/restores draft, late old identity and real revocation clear content')

    @classmethod
    def run_scenarios(cls, root, bundle, report, out, browser, temp_root, cases=CASES):
        for name in cases:
            case_out = out / name; case_out.mkdir()
            folder, before, case = None, len(report['checks']), {'name': name, 'passed': False}
            screenshots_before = len(report['screenshots'])
            try:
                with ExitStack() as lifecycle:
                    folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='pm-', dir=temp_root)))
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
