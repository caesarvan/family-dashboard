"""Reviewed-source browser acceptance for owner-confirmed local-photo dates.

Real temporary HTTPS/Flask/SQLite and exported Expo; no business DTO mocks.
Only the MediaLibrary clock and delivery of real responses are controlled.
"""
import argparse
from contextlib import ExitStack, closing
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import traceback
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from flask import request
from playwright.sync_api import expect, sync_playwright
import browser_finance_flow_mapping_check as build_fixture
from browser_expo_finance_check import button, sha, visibility
from browser_expo_local_photo_check import Run as LocalRun
from browser_expo_photo_duplicates_check import BrowserHttpGuard
from browser_expo_photo_memories_check import MemoryClock
from browser_expo_photo_suggestions_check import Run as SuggestionRun

HARNESS = 'tests/browser_media_confirmed_date_check.py'
CASES = ('upload_date_journey_memories', 'lost_conflict_identity_clear')
CASE_SCREENSHOTS = {name: 3 for name in CASES}
MEMORIES = '/api/media/memories/on-this-day?limit=24&offset=0&dateMode=confirmed-or-source'
DAY = '2024-02-29T04:00:00+00:00'
TIMEOUT = 15000


class Run(LocalRun):
    make_journey = SuggestionRun.make_journey
    pair = SuggestionRun.pair

    def __init__(self, root, bundle, folder, report, out, lifecycle):
        super().__init__(root, bundle, folder, report, out, lifecycle)
        self.http_guard = BrowserHttpGuard(self.base, out.name, out, report)
        self.clock = MemoryClock(DAY)
        self.journal, self.journal_lock = [], threading.Lock()
        self.serial = 0
        paths = {HARNESS: Path(__file__)}
        for name in ('browser_expo_photo_suggestions_check', 'browser_expo_photo_memories_check',
                     'browser_expo_photo_duplicates_check', 'browser_finance_flow_mapping_check'):
            paths['tests/' + name + '.py'] = Path(sys.modules[name].__file__)
        for name in ('household_media', 'journey_workflows', 'media_crypto', 'media_local_upload'):
            paths[name + '.py'] = Path(importlib.import_module(name).__file__)
        for name, actual in paths.items():
            assert actual.resolve() == (root / name).resolve(), name
        hashes = {name: sha(actual) for name, actual in paths.items()}
        assert report.setdefault('dateFixtureHashes', hashes) == hashes

        @self.application.after_request
        def journal(response):
            # Installed before this fixture creates any browser/context/login.
            if request.path.startswith('/api/'):
                entry = dict(method=request.method, path=request.path,
                             query=request.query_string.decode(), status=response.status_code)
                if request.method == 'PATCH' and request.path.startswith('/api/media/items/'):
                    entry['request'] = request.get_json(silent=True)
                with self.journal_lock:
                    self.journal.append(entry)
                    with (out / 'server-http.jsonl').open('a', encoding='utf-8', newline='\n') as stream:
                        stream.write(json.dumps(entry, ensure_ascii=False) + '\n'); stream.flush()
            return response

    def context(self, browser, member=1):
        ctx = super().context(browser, member)
        ctx.set_default_timeout(TIMEOUT)
        ctx.set_default_navigation_timeout(TIMEOUT)
        self.http_guard.attach(ctx)
        return ctx

    def evidence(self, name, value, group='httpEvidence'):
        self.serial += 1
        self.record(f'{self.serial:03}-{name}', value, group)

    def completed_json(self, page, name, method, url, trigger, expected_status=200):
        self.serial += 1
        return super().completed_json(page, f'{self.serial:03}-{name}', method, url, trigger, expected_status)

    @staticmethod
    def item_path(uid):
        return '/api/media/items/' + uid

    def current(self, ctx, uid):
        item = self.get(ctx, self.item_path(uid))['item']
        assert item['id'] == uid
        return item

    def suggestions(self, ctx, uid):
        return self.get(ctx, self.item_path(uid) + '/journey-suggestions?dateMode=confirmed-or-source')

    def set_clock(self, stamp=DAY):
        self.clock.set(stamp)
        self.engine.clock = self.clock

    def saved_upload(self, ctx, page):
        paths = self.files(1)
        self.raw_input_hashes = {str(path): sha(path) for path in paths}
        self.open_device(page); self.choose(page, paths)
        detail = self.upload(page)
        uid = self.save(page, detail)[0]
        proof = self.preview_proof(ctx, uid)
        assert proof['item']['userConfirmedDate'] is None
        self.evidence('real-upload-confirm', proof)
        return uid

    def open_detail(self, page, uid, *, navigate=True):
        if navigate:
            page.goto(self.base + '/app/photos'); page.bring_to_front()
        expect(page.get_by_role('heading', name='相册', exact=True)).to_be_visible(timeout=TIMEOUT)
        item = self.current(page.context, uid)
        value, _ = self.completed_json(page, f'original-read-{self.serial}', 'GET',
            self.base + self.item_path(uid),
            lambda: page.get_by_label('查看照片：' + (item['caption'] or '未添加说明'), exact=True).click())
        assert value['item']['id'] == uid
        expect(page.get_by_test_id('photo-confirmed-date-input')).to_have_value(item['userConfirmedDate'] or '')
        return value['item']

    def snapshot(self, uid):
        """Only this case's synthetic DB; hashes exclude original bytes from reports."""
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        def digest(value):
            if isinstance(value, bytes): return hashlib.sha256(value).hexdigest()
            return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
        with closing(sqlite3.connect(self.database)) as con:
            con.row_factory = sqlite3.Row
            row = dict(con.execute('SELECT * FROM media_items WHERE id=?', (uid,)).fetchone())
            metadata = self.engine._metadata(row)
            state = dict(id=uid, revision=row['revision'], updatedAt=row['updated_at'],
                date=metadata.pop('userConfirmedDate', None), metadataSha256=digest(metadata),
                immutableColumns={k: digest(v) for k, v in row.items()
                    if k not in ('revision', 'updated_at', 'metadata_cipher')})
            state['tables'] = {name: digest(sorted([tuple(r) for r in con.execute('SELECT * FROM ' + name)], key=repr))
                for name in ('journey_workflows', 'journey_links', 'journey_actions', 'journey_places',
                             'media_imports', 'media_tv_grants', 'media_playback')}
            settings = [dict(r) for r in con.execute('SELECT * FROM settings ORDER BY id')]
            meta = next(r for r in settings if r['id'] == 'meta')
            state['metaRevision'] = meta['revision']
            meta['revision'] = None  # Only this exact audit increment is compared separately.
            state['tables']['settings'] = digest(settings)
            audits = [dict(r) for r in con.execute('SELECT id,actor,action,target FROM audit ORDER BY id')]
            state['audit'] = audits
            return state

    def date_only(self, before, after, value):
        assert after['id'] == before['id'] and after['revision'] == before['revision'] + 1
        assert after['date'] == value
        for key in ('metadataSha256', 'immutableColumns', 'tables'):
            assert before[key] == after[key], key
        assert after['metaRevision'] == before['metaRevision'] + 1
        assert after['audit'][:-1] == before['audit']
        assert {k: after['audit'][-1][k] for k in ('actor', 'action', 'target')} == {
            'actor': 'member1', 'action': 'media_item_update', 'target': before['id']}
        self.evidence('date-only-preservation', {'before': before, 'after': after}, 'databaseEvidence')

    def write_count(self, uid):
        with self.journal_lock:
            return sum(r['method'] == 'PATCH' and r['path'] == self.item_path(uid) for r in self.journal)

    def save_date(self, ctx, page, uid, value):
        before = self.snapshot(uid)
        field = page.get_by_test_id('photo-confirmed-date-input')
        if value is not None: field.fill(value)
        control = page.get_by_test_id('photo-confirmed-date-clear' if value is None else 'photo-confirmed-date-save')
        expect(control).to_be_enabled(timeout=TIMEOUT)
        result, payload = self.completed_json(page, f'date-save-{self.serial}', 'PATCH',
            self.base + self.item_path(uid), control.click)
        assert payload == {'revision': before['revision'], 'userConfirmedDate': value}
        assert result['item']['id'] == uid and result['item']['userConfirmedDate'] == value
        expect(page.get_by_test_id('photo-confirmed-date-status')).to_contain_text('照片日期已更新。')
        self.date_only(before, self.snapshot(uid), value)
        return self.current(ctx, uid)

    def link_suggestion(self, ctx, page, uid, journey, match_date):
        data, _ = self.completed_json(page, f'suggestions-{self.serial}', 'GET',
            self.base + self.item_path(uid) + '/journey-suggestions?dateMode=confirmed-or-source',
            lambda: button(page, '查看旅行建议').click())
        assert data['version'] == 2 and data['photoId'] == uid and data['dateBasis'] == 'userConfirmedDate'
        row = next(v for v in data['suggestions'] if v['journeyId'] == journey['id'])
        assert row['matchDate'] == match_date and 'sourceDate' not in row
        expect(page.get_by_test_id('photo-journey-suggestions')).to_contain_text('按本人确认日期匹配，未换算时区')
        page.get_by_role('radio', name='选择旅行：' + journey['trip']['title'], exact=True).click()
        item = self.current(ctx, uid)
        result, body = self.completed_json(page, f'link-{self.serial}', 'PATCH',
            self.base + self.item_path(uid), lambda: button(page, '确认关联所选旅行').click())
        assert body == dict(revision=item['revision'], journeyId=journey['id'],
            expectedJourneyRevision=row['journeyRevision'], expectedTripRevision=row['tripRevision'])
        assert result['item']['journey']['id'] == journey['id']
        assert self.current(ctx, uid)['userConfirmedDate'] == match_date

    def open_memories(self, page):
        result, _ = self.completed_json(page, f'memories-{self.serial}', 'GET', self.base + MEMORIES,
            lambda: button(page, '那年今日').click())
        assert result['version'] == 2 and result['referenceTimezone'] == 'Asia/Shanghai'
        assert result['datePolicy'] == 'confirmed-or-source' and result['offset'] == 0
        expect(page.get_by_test_id('photo-memories-summary')).to_be_visible(timeout=TIMEOUT)
        return result

    def upload_date_journey_memories(self, browser):
        with self.flow(browser) as (ctx, page):
            uid = self.saved_upload(ctx, page)
            self.set_clock()
            reference = self.get(ctx, MEMORIES)
            assert reference['referenceDate'] == '2024-02-29'
            date = reference['referenceDate'].replace('2024-', '2020-', 1)
            datetime.strptime(date, '%Y-%m-%d')  # Explicit previous leap year, not replace(year-1).
            journey = self.make_journey(ctx, title='合成闰日旅行', start=date, end=date, zone='Pacific/Honolulu')
            assert self.suggestions(ctx, uid)['dateBasis'] == 'unknown'
            self.open_detail(page, uid)
            original = self.preview_proof(ctx, uid)
            self.save_date(ctx, page, uid, date)
            self.capture(page, 'saved-date-390', page.get_by_test_id('photo-confirmed-date'))
            mark = self.write_count(uid)
            page.reload(); self.open_detail(page, uid, navigate=False)
            assert self.write_count(uid) == mark
            current = self.preview_proof(ctx, uid)
            assert current['previewSha256'] == original['previewSha256']
            assert current['item']['sourceCreatedAt'] is None and current['item']['sourceTimeState'] == 'unknown'
            self.link_suggestion(ctx, page, uid, journey, date)
            self.capture(page, 'explicit-original-journey-390', page.get_by_test_id('photo-editor'))
            button(page, '关闭').click()
            memory = self.open_memories(page)
            assert memory['total'] == 1 and memory['unknownSourceTimeCount'] == 1 and memory['unknownEffectiveDateCount'] == 0
            assert memory['items'][0]['item']['id'] == uid and memory['items'][0]['displayDate'] == date
            assert memory['items'][0]['dateBasis'] == 'userConfirmedDate' and memory['items'][0]['yearsAgo'] == 4
            self.capture(page, 'confirmed-date-memory-390', page.get_by_test_id('photo-memories-summary'))
            self.open_detail(page, uid, navigate=False)
            button(page, '关闭').click()
            # Only server time advances; browser clocks/animations continue naturally.
            self.set_clock('2024-02-29T15:59:59+00:00')
            assert self.get(ctx, MEMORIES)['referenceDate'] == reference['referenceDate']
            visibility(page, True)
            self.set_clock('2024-02-29T16:00:00+00:00')
            next_day, _ = self.completed_json(page, f'midnight-{self.serial}', 'GET', self.base + MEMORIES,
                lambda: visibility(page, False))
            assert next_day['referenceDate'] == '2024-03-01' and next_day['items'] == []
            expect(page.get_by_label('查看照片：未添加说明', exact=True)).to_have_count(0)
            assert self.current(ctx, uid)['journey']['id'] == journey['id']
            self.evidence('reference-date-and-midnight', {'reference': reference, 'matching': memory, 'afterMidnight': next_day})
            assert self.raw_input_hashes == {p: sha(Path(p)) for p in self.raw_input_hashes}
            self.http_guard.assert_clean()
            self.passed('390: actual device upload/private confirmation/date CAS/reload/original journey confirmation/memory original ID; leap-day and server Shanghai midnight remain explicit')

    def lost_conflict_identity_clear(self, browser):
        with self.flow(browser) as (ctx, page), ExitStack() as stack:
            page.set_viewport_size({'width': 1280, 'height': 900})
            uid = self.saved_upload(ctx, page); self.set_clock()
            reference = self.get(ctx, MEMORIES)['referenceDate']; assert reference == '2024-02-29'
            date, changed_date = '2020' + reference[4:], '2016' + reference[4:]
            journey = self.make_journey(ctx, title='合成已确认旅行保留', start=changed_date, end=changed_date)
            item = self.current(ctx, uid)
            item = self.write(ctx, 'PATCH', self.item_path(uid), dict(revision=item['revision'], visibility='shared'))['item']
            device, tv = self.pair(browser, ctx, stack, name='合成日期电视')
            self.write(ctx, 'PUT', self.item_path(uid) + '/tv-grants', dict(revision=item['revision'], deviceIds=[device['id']], consentVersion='media-v1', allowTvDisplay=True))
            self.open_detail(page, uid)
            before = self.snapshot(uid); lost = []
            def drop(route):
                if route.request.method != 'PATCH': route.continue_(); return
                actual = route.fetch(max_redirects=0, timeout=TIMEOUT)
                try:
                    assert actual.status == 200
                    lost.append({'request': route.request.post_data_json, 'status': actual.status, 'response': actual.json()})
                    self.evidence('actual-committed-before-drop', lost[-1])
                    route.abort('failed')
                finally: actual.dispose()
            url = self.base + self.item_path(uid)
            page.route(url, drop)
            try:
                page.get_by_test_id('photo-confirmed-date-input').fill(date)
                page.get_by_test_id('photo-confirmed-date-save').click()
                self.settle(page, lambda: len(lost) == 1, timeout=TIMEOUT)
                expect(page.get_by_test_id('photo-confirmed-date-recheck')).to_be_enabled(timeout=TIMEOUT)
            finally: page.unroute(url, drop)
            assert lost[0]['request'] == dict(revision=before['revision'], userConfirmedDate=date)
            self.date_only(before, self.snapshot(uid), date)
            expect(page.get_by_test_id('photo-confirmed-date-status')).to_contain_text('结果待核对')
            self.capture(page, 'committed-response-lost-1280', page.get_by_test_id('photo-confirmed-date'))
            count = self.write_count(uid); committed = self.snapshot(uid)
            self.completed_json(page, f'recheck-{self.serial}', 'GET', url,
                page.get_by_test_id('photo-confirmed-date-recheck').click)
            expect(page.get_by_test_id('photo-confirmed-date-status')).to_contain_text('这不是上一请求的执行回执')
            assert self.snapshot(uid) == committed and self.write_count(uid) == count
            # Actual competing CAS happens immediately before dispatching the held stale PATCH.
            stale = self.current(ctx, uid); rejected = []
            def conflict(route):
                if route.request.method != 'PATCH': route.continue_(); return
                rival = self.write(ctx, 'PATCH', self.item_path(uid), dict(revision=stale['revision'], userConfirmedDate=changed_date))
                actual = route.fetch(max_redirects=0, timeout=TIMEOUT)
                try:
                    rejected.append(dict(status=actual.status, request=route.request.post_data_json, rival=rival, response=actual.json()))
                    self.evidence('actual-stale-revision', rejected[-1])
                    route.fulfill(status=actual.status, headers=actual.headers, body=actual.body())
                finally: actual.dispose()
            page.route(url, conflict)
            try:
                page.get_by_test_id('photo-confirmed-date-input').fill('2021-07-19')
                page.get_by_test_id('photo-confirmed-date-save').click()
                self.settle(page, lambda: len(rejected) == 1, timeout=TIMEOUT)
                assert rejected[0]['status'] == 409 and rejected[0]['request']['revision'] == stale['revision']
                expect(page.get_by_test_id('photo-confirmed-date-input')).to_have_value('2021-07-19')
                expect(page.get_by_test_id('photo-confirmed-date-recheck')).to_be_enabled(timeout=TIMEOUT)
            finally: page.unroute(url, conflict)
            self.date_only(committed, self.snapshot(uid), changed_date)
            count = self.write_count(uid)
            self.completed_json(page, f'conflict-recheck-{self.serial}', 'GET', url,
                page.get_by_test_id('photo-confirmed-date-recheck').click)
            assert self.write_count(uid) == count
            expect(page.get_by_test_id('photo-confirmed-date-input')).to_have_value('2021-07-19')
            expect(page.get_by_test_id('photo-confirmed-date')).to_contain_text(changed_date)
            # Recheck does not discard the failed draft. This is an explicit edit
            # back to the fresh current value, without another write.
            page.get_by_test_id('photo-confirmed-date-input').fill(changed_date)
            self.link_suggestion(ctx, page, uid, journey, changed_date)
            self.capture(page, 'stale-rejected-current-date-1280', page.get_by_test_id('photo-confirmed-date'))
            self.identity_boundary(browser, ctx, page, uid, tv)
            self.login(ctx); self.open_detail(page, uid)
            original = self.preview_proof_shared(ctx, uid)
            self.save_date(ctx, page, uid, None)
            item = self.current(ctx, uid)
            assert item['journey']['id'] == journey['id'] and item['visibility'] == 'shared'
            assert self.preview_proof_shared(ctx, uid) == original
            assert self.get(ctx, self.item_path(uid) + '/tv-grants')['deviceIds'] == [device['id']]
            suggestions = self.suggestions(ctx, uid)
            assert suggestions['dateBasis'] == 'unknown' and suggestions['suggestions'] == [] and suggestions['currentJourneyId'] == journey['id']
            button(page, '关闭').click(); memory = self.open_memories(page)
            assert memory['items'] == [] and memory['unknownEffectiveDateCount'] == 1
            self.capture(page, 'cleared-date-no-memory-1280', page.get_by_test_id('photo-memories-summary'))
            self.evidence('clear-preserves-original-association', dict(item=item, suggestions=suggestions, memory=memory), 'databaseEvidence')
            assert self.raw_input_hashes == {p: sha(Path(p)) for p in self.raw_input_hashes}
            self.http_guard.assert_clean()
            self.passed('1280: actual committed PATCH loss recovers by GET without rewrite; stale CAS rejects, late owner response is fenced, clear removes effective-date matches but preserves journey/shared/TV/source/image')

    def preview_proof_shared(self, ctx, uid):
        response = ctx.request.get(self.base + self.current(ctx, uid)['previewUrl'])
        try:
            assert response.status == 200
            return hashlib.sha256(response.body()).hexdigest()
        finally: response.dispose()

    def identity_boundary(self, browser, ctx, page, uid, tv):
        # Two actual households, not two synthetic owner labels in one DB.
        invitation = self.write(ctx, 'POST', '/api/spaces/invitations', {}, 201)['invitation']
        family = self.write(ctx, 'POST', '/api/spaces/redeem', dict(invitation=invitation,
            name='合成日期第二家庭', slug='date-other', MEMBER1_PASSWORD='testing-password-one', MEMBER2_PASSWORD='testing-password-two'), 201)
        child = self.context(browser, None); self.lifecycle.callback(child.close)
        assert child.request.get(self.base + family['entry']).status == 200; self.login(child)
        assert child.request.get(self.base + self.item_path(uid)).status == 404
        assert self.write(child, 'PATCH', self.item_path(uid), {'revision': self.current(ctx, uid)['revision'], 'userConfirmedDate': '2016-02-29'}, 404)
        assert 'userConfirmedDate' not in next(v for v in self.get(tv, '/api/media-tv/items')['items'] if v['id'] == uid)
        response = tv.request.patch(self.base + self.item_path(uid), data={'revision': 1, 'userConfirmedDate': None}, headers={'Origin': self.base})
        assert response.status == 403; response.dispose()
        button(page, '关闭').click()
        held = []; holding = True; url = self.base + self.item_path(uid)
        def hold(route):
            if not holding or route.request.method != 'GET': route.continue_(); return
            actual = route.fetch(max_redirects=0, timeout=TIMEOUT)
            try:
                assert actual.status == 200 and actual.json()['item']['userConfirmedDate'] == '2016-02-29'
                held.append((route, actual.status, actual.headers, actual.body()))
            finally: actual.dispose()
        page.route(url, hold)
        try:
            page.get_by_label('查看照片：未添加说明', exact=True).click()
            self.settle(page, lambda: bool(held), timeout=TIMEOUT)
            expect(page.get_by_test_id('photo-confirmed-date')).to_have_count(0)
            page.evaluate('''() => {
              window.__dateLeaks=[];
              const check=()=>{if(document.querySelector('[data-testid="photo-confirmed-date"]'))
                window.__dateLeaks.push({reason:'old-owner-date-editor',at:performance.now()});};
              window.__dateObserver=new MutationObserver(check);
              window.__dateObserver.observe(document.body,{subtree:true,childList:true,attributes:true});check();
            }''')
            self.login(ctx, 2)
            pending = list(held); holding = False
            with page.expect_response(lambda r: urlsplit(r.url).path == '/api/me' and r.request.method == 'GET'
                    and r.status == 200 and r.json().get('user', {}).get('id') == 'member2', timeout=TIMEOUT) as fresh:
                for route, status, headers, raw in pending:
                    route.fulfill(status=status, headers=headers, body=raw); held.remove((route, status, headers, raw))
            me = fresh.value.json()
            expect(button(page, me['user']['name'] + '，账户菜单')).to_be_visible(timeout=TIMEOUT)
            expect(page.get_by_test_id('photo-confirmed-date')).to_have_count(0)
            leaks = page.evaluate('() => {window.__dateObserver.disconnect(); return window.__dateLeaks;}')
            assert leaks == []
            item = self.current(ctx, uid); assert 'userConfirmedDate' not in item
            self.write(ctx, 'PATCH', self.item_path(uid), {'revision': item['revision'], 'userConfirmedDate': None}, 403)
            self.evidence('actual-late-owner-response', dict(deliveredAfterRealMemberSwitch=True,
                heldResponses=[json.loads(raw) for _, _, _, raw in pending], currentPageUser=me['user']['id'],
                sharedProjection=item, leaks=leaks, secondHouseholdReadWriteStatus=404, tvWriteStatus=403))
        finally:
            for route, *_ in held: route.abort('failed')
            page.unroute(url, hold)

    @classmethod
    def run_scenarios(cls, root, bundle, report, out, browser, temp_root, cases=CASES):
        # Existing lifecycle: fresh DB per case; non-daemon request handlers joined,
        # actual listener closed, temporary tree removed, failures retained.
        # The inherited method resolves CASE_SCREENSHOTS in its module: all selected
        # cases deliberately use the same three-shot contract, supplied locally below.
        from browser_expo_local_photo_check import CASE_SCREENSHOTS as parent_counts
        with patch.dict(parent_counts, CASE_SCREENSHOTS):
            super().run_scenarios(root, bundle, report, out, browser, temp_root, cases)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source-root', 'bundle', 'temp-root'): parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--build-source-head')
    parser.add_argument('--expected-build-evidence', required=True)
    parser.add_argument('--case', action='append', choices=CASES, dest='cases')
    args = parser.parse_args()
    if not sys.dont_write_bytecode or sys.flags.optimize: raise RuntimeError('Use -B; optimization is forbidden')
    assert re.fullmatch('[a-f0-9]{40}', args.expected_head) and re.fullmatch('[a-f0-9]{64}', args.expected_build_evidence)
    root, bundle, temp_root = args.source_root.resolve(), args.bundle.absolute(), args.temp_root.resolve()
    if os.name == 'nt' and not str(bundle).startswith('\\\\?\\'): bundle = Path('\\\\?\\' + str(bundle))
    assert temp_root.is_dir() and not temp_root.is_symlink() and not temp_root.is_junction()
    def git(*command): return subprocess.check_output(['git', '--no-replace-objects', *command], cwd=root).decode('utf-8').strip()
    head, tree = git('rev-parse', 'HEAD'), git('rev-parse', 'HEAD^{tree}')
    assert head == args.expected_head and not git('status', '--porcelain=v1')
    assert Path(__file__).resolve() == (root / HARNESS).resolve()
    build_head = args.build_source_head or head
    assert re.fullmatch('[a-f0-9]{40}', build_head)
    build_changes = []
    if build_head != head:
        git('merge-base', '--is-ancestor', build_head, head)
        build_changes = git('diff', '--no-renames', '--name-only', '-z', build_head, head, '--').rstrip('\0').split('\0')
        assert set(build_changes) <= {HARNESS, 'docs/MEDIA-CONFIRMED-DATE-BROWSER.md'}, 'Only this harness and its documentation may differ from the build commit'
    evidence_path = bundle.parent / 'build-evidence.json'
    assert sha(evidence_path) == args.expected_build_evidence
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    names = git('ls-files', '-z').rstrip('\0').split('\0')
    build_fixture.validate_build(git, root, build_head, evidence, names)
    for name, digest in evidence.get('additionalTestInputs', {}).items():
        assert name in names and sha(root / name) == digest
    assert build_fixture.exports(bundle) == evidence['files']
    def hashes(): return {name: sha(root / name) for name in names}
    cases = tuple(dict.fromkeys(args.cases or CASES))
    out = root / 'test-results' / ('media-confirmed-date-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True, exist_ok=False); shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], screenshots=[], pageErrors=[], externalRequests=[], unexpectedProviderAttempts=[],
        httpEvidence=[], databaseEvidence=[], scenarioResults=[], scenarioFailures=[], requestedCases=list(cases),
        head=head, sourceHead=head, tree=tree, buildSourceHead=build_head, buildSourceTree=evidence['sourceTree'],
        buildReusePaths=build_changes, buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(Path(__file__)),
        sourceHashesBefore=hashes(), bundleHashesBefore=build_fixture.exports(bundle), productionWrites=0,
        realCloud=False, realModel=False, physicalTelevision=False,
        scope='Two selected real local HTTPS/Flask/SQLite/Edge flows with synthetic device bytes/two households. '
              'Only server MediaLibrary time and delivery of actual responses are injected. '
              'Browser clocks run normally; shared/TV checks are API/fixture checks, not physical TV acceptance.')
    original_connect = socket.socket.connect
    def local_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
            report['externalRequests'].append({'kind': 'non-loopback socket'}); raise AssertionError('External network forbidden')
        return original_connect(sock, address)
    try:
        with patch.object(socket.socket, 'connect', local_connect), sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            try:
                Run.run_scenarios(root, bundle, report, out, browser, temp_root, cases)
                assert len(report['checks']) == len(cases) and len(report['screenshots']) == 3 * len(cases)
                assert [c['name'] for c in report['scenarioResults']] == list(cases)
                assert not any(report[k] for k in ('scenarioFailures', 'pageErrors', 'externalRequests', 'unexpectedProviderAttempts', 'unexpectedHttpServerErrors', 'httpCaptureErrors'))
                report['passed'] = True
            finally: browser.close()
    except Exception:
        report['passed'] = False; report['failure'] = traceback.format_exc(); print(report['failure'], flush=True)
    finally:
        try:
            report['sourceHashesAfter'], report['bundleHashesAfter'] = hashes(), build_fixture.exports(bundle)
            report['sourceUnchanged'] = report['sourceHashesBefore'] == report['sourceHashesAfter']
            report['bundleUnchanged'] = report['bundleHashesBefore'] == report['bundleHashesAfter']
            for key in ('fixtureHashes', 'dateFixtureHashes'):
                report[key + 'After'] = {name: sha(root / name) for name in report.get(key, {})}
                assert report.get(key) and report[key + 'After'] == report[key]
            report['sourceStillFrozen'] = git('rev-parse', 'HEAD') == head and not git('status', '--porcelain=v1')
            report['temporaryFixtureRemoved'] = len(report['scenarioResults']) == len(cases) and all(c.get('listenerStopped') and c['temporaryFixtureRemoved'] for c in report['scenarioResults'])
            report['passed'] = report['passed'] and all(report[k] for k in ('sourceUnchanged', 'bundleUnchanged', 'sourceStillFrozen', 'temporaryFixtureRemoved'))
        except Exception:
            report['passed'] = False; report['finalEvidenceFailure'] = traceback.format_exc()
        build_fixture.write_json(out / 'result.json', report)
        print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'report': str(out / 'result.json')}, ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
