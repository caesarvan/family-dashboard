"""Member homepage layouts against frozen Expo, real Flask/SQLite and Edge.

Only synthetic households and actual cookie authentication are used. Faults
delay/drop real responses; no successful business response or HTML is mocked.
The nine focused flows do not rerun the inherited finance or TV suites.
"""
import argparse
from contextlib import ExitStack, closing
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

from playwright.sync_api import expect, sync_playwright
import browser_expo_finance_check as fixture
from browser_expo_finance_check import Run as BaseRun, button, sha, visibility


PATH = '/api/dashboard-layout'
CARDS = ['calendar', 'finance', 'tasks', 'shopping', 'trips']
NAMES = dict(calendar='日程安排', finance='共同资金', tasks='共同待办', shopping='采购清单', trips='下一趟旅行')
HEADINGS = dict(calendar='接下来的安排', finance='共同资金', tasks='先做这几件', shopping='需要添置', trips='下一趟旅行')
FUTURE = 'synthetic-future-weather'


def checkbox(page, key):
    return page.get_by_role('checkbox', name='在首页显示：' + NAMES[key], exact=True)


class Run(BaseRun):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        assert Path(self.source.__file__).resolve() == (self.root / 'app.py').resolve()
        self.report['fixtureHashes'] = {}
        for file, name in ((Path(fixture.__file__), 'tests/browser_expo_finance_check.py'),
                           (Path(__file__), 'tests/browser_expo_home_layout_check.py')):
            assert sha(file) == sha(self.root / name)
            self.report['fixtureHashes'][name] = sha(file)

    def clear_finance(self):
        pass  # The base class supplies only server/auth/lifecycle helpers.

    def snapshot(self):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database)) as con:
            return {table: sorted(con.execute('SELECT * FROM ' + table).fetchall(), key=repr)
                    for table in ('member_dashboard_layout', 'member_preferences', 'devices', 'audit', 'settings', 'entities')}

    def layout(self, ctx):
        return self.get(ctx, PATH)

    def set_layout(self, ctx, order=None, hidden=None):
        current = self.layout(ctx)
        return self.write(ctx, 'PUT', PATH, {'revision': current['revision'],
            'order': CARDS if order is None else order, 'hidden': [] if hidden is None else hidden})

    def home(self, page):
        page.goto(self.base + '/app/home')
        expect(button(page, '安排首页')).to_be_enabled(timeout=15000)

    def open_panel(self, page):
        self.home(page)
        button(page, '安排首页').click()
        expect(page.get_by_role('heading', name='安排我的首页', exact=True)).to_be_visible()
        expect(checkbox(page, 'calendar')).to_be_enabled()
        expect(button(page, '恢复默认布局')).to_be_enabled()

    def panel_order(self, page):
        return page.get_by_test_id(re.compile(r'^home-layout-card-(?:calendar|finance|tasks|shopping|trips)$')).evaluate_all(
            '(nodes) => nodes.map(node => node.dataset.testid.replace("home-layout-card-", ""))')

    def assert_home(self, page, layout):
        expected = [HEADINGS[key] for key in layout['order'] if key in HEADINGS and key not in layout['hidden']]
        headings = page.get_by_role('heading', name=re.compile('^(?:' + '|'.join(map(re.escape, HEADINGS.values())) + ')$'))
        expect(headings).to_have_text(expected)
        assert len(expected) >= 1

    def save(self, page):
        original = self.layout(page.context)
        with page.expect_response(lambda response: urlsplit(response.url).path == PATH and response.request.method == 'PUT') as pending:
            button(page, '保存首页布局').click()
        assert pending.value.status == 200, pending.value.text()
        expect(page.get_by_test_id('home-layout-message')).to_have_text('首页布局已保存。')
        expect(button(page, '关闭首页布局')).to_be_enabled()
        result = self.layout(page.context)
        assert result == pending.value.json() and result['revision'] == original['revision'] + 1
        return result

    def shot(self, page, name, width):
        page.set_viewport_size({'width': width, 'height': 1080 if width >= 1040 else 844})
        page.evaluate('() => document.fonts.ready')
        page.wait_for_timeout(400)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2')
        if page.get_by_test_id('home-layout-panel').count():
            assert page.get_by_test_id('home-layout-panel').get_by_role('checkbox').evaluate_all('''nodes => nodes.every(node => {
                const r=node.getBoundingClientRect(); return r.width > 0 && r.left >= -2 && r.right <= innerWidth + 2;
            })''')
        path = self.out / f'{name}-{width}.png'
        page.screenshot(path=str(path), full_page=False)
        self.report['screenshots'].append({'path': path.name, 'sha256': sha(path), 'width': width,
            'height': 1080 if width >= 1040 else 844, 'scope': 'current viewport; inner scroll contents not all captured'})

    def layout_keyboard_and_viewports(self, page):
        self.set_layout(page.context)
        self.open_panel(page)
        before = self.snapshot()
        for width in (320, 390, 1280, 1920):
            self.shot(page, 'home-layout-editor', width)
        page.set_viewport_size({'width': 320, 'height': 844})
        checkbox(page, 'finance').focus()
        checkbox(page, 'finance').press('Space')
        expect(checkbox(page, 'finance')).not_to_be_checked()
        checkbox(page, 'finance').press('Space')
        expect(checkbox(page, 'finance')).to_be_checked()
        button(page, '上移：共同资金').focus()
        button(page, '上移：共同资金').press('Enter')
        assert self.panel_order(page) == ['finance', 'calendar', 'tasks', 'shopping', 'trips']
        checkbox(page, 'tasks').focus()
        assert checkbox(page, 'tasks').evaluate('(node) => node === document.activeElement')
        self.shot(page, 'home-layout-keyboard-focus', 320)
        for key in ('calendar', 'tasks', 'shopping', 'trips'):
            checkbox(page, key).click()
        checkbox(page, 'finance').click()
        expect(checkbox(page, 'finance')).to_be_checked()
        expect(page.get_by_role('alert')).to_contain_text('至少保留一张')
        assert self.snapshot() == before
        button(page, '恢复默认布局').click()
        assert self.panel_order(page) == CARDS
        assert all(checkbox(page, key).is_checked() for key in CARDS)
        expect(button(page, '保存首页布局')).to_be_disabled()
        self.passed('Four-width editor and real keyboard Space/Enter work; at least one card remains; edits/default reset are zero-write until saved')

    def persistence_and_default(self, page):
        button(page, '上移：共同资金').click()
        checkbox(page, 'shopping').click()
        held = []
        old_layout = self.layout(page.context)
        def hold_old_poll(route):
            assert route.request.method == 'GET'
            response = route.fetch(max_redirects=0)
            assert response.status == 200 and response.json() == old_layout
            held.append((route, response))
        page.route(self.base + PATH, hold_old_poll, times=1)
        button(page, '刷新家庭数据').click()
        self.settle(page, lambda: bool(held))
        saved = self.save(page)
        assert saved['order'] == ['finance', 'calendar', 'tasks', 'shopping', 'trips'] and saved['hidden'] == ['shopping']
        button(page, '关闭首页布局').click()
        expect(button(page, '安排首页')).to_be_enabled()
        self.assert_home(page, saved)
        # Deliver the genuine earlier provider GET only after the new layout
        # is visible. It must not replace the just-confirmed higher revision.
        held[0][0].fulfill(response=held[0][1])
        expect(button(page, '刷新家庭数据')).to_be_enabled()
        self.assert_home(page, saved)
        for width in (320, 390, 1280, 1920):
            self.shot(page, 'home-layout-saved', width)
        page.reload()
        expect(button(page, '安排首页')).to_be_enabled()
        self.assert_home(page, saved)
        self.open_panel(page)
        button(page, '恢复默认布局').click()
        assert self.layout(page.context) == saved
        restored = self.save(page)
        assert restored['order'] == CARDS and restored['hidden'] == []
        button(page, '关闭首页布局').click()
        self.assert_home(page, restored)
        self.passed('Explicit save persists order/hidden cards into SQLite, home and reload; a delayed old provider GET cannot replace it; restoring defaults requires another explicit save')

    def isolation(self, browser, page):
        owner = page.context
        with ExitStack() as stack:
            partner = self.context(browser, member=2); stack.callback(partner.close)
            partner_page = partner.new_page()
            self.set_layout(partner, order=list(reversed(CARDS)), hidden=['calendar'])
            second_layout = self.layout(partner)
            television = self.context(browser, member=None); stack.callback(television.close)
            pair = self.write_anonymous(television, '/api/pair/start', {})
            self.write(owner, 'POST', '/api/pair/approve', {'code': pair['code'], 'name': '合成独立电视', 'focus': 'member2'})
            assert self.write_anonymous(television, '/api/pair/poll', {'secret': pair['secret']})['approved']
            assert any(cookie['name'] == 'household_tv' and cookie['httpOnly'] for cookie in television.cookies())
            tv_before = self.get(television, '/api/state')
            devices_before = self.get(owner, '/api/devices')
            tvpage = television.new_page(); tvpage.goto(self.base + '/app/tv')
            expect(tvpage.get_by_test_id('expo-tv-board')).to_be_visible(timeout=15000)
            self.open_panel(page); checkbox(page, 'tasks').click(); saved = self.save(page)
            assert self.layout(partner) == second_layout and self.get(owner, '/api/devices') == devices_before
            tv_after = self.get(television, '/api/state')
            # The existing global audit revision and response timestamp may
            # advance; actual shared data and per-device display must not.
            assert {k: v for k, v in tv_after.items() if k not in ('revision', 'updatedAt')} == {
                k: v for k, v in tv_before.items() if k not in ('revision', 'updatedAt')}
            self.get(television, PATH, 403)
            tvpage.reload(); expect(tvpage.get_by_test_id('expo-tv-board')).to_be_visible(timeout=15000)
            self.home(partner_page); self.assert_home(partner_page, second_layout)
            invitation = self.write(owner, 'POST', '/api/spaces/invitations', {}, 201)['invitation']
            family = self.write(owner, 'POST', '/api/spaces/redeem', {'invitation': invitation, 'name': '合成布局第二家庭',
                'slug': 'expo-layout-other', 'MEMBER1_PASSWORD': 'testing-password-one', 'MEMBER2_PASSWORD': 'testing-password-two'}, 201)
            child = self.context(browser, member=None); stack.callback(child.close)
            assert child.request.get(self.base + family['entry']).status == 200
            self.login(child)
            assert self.layout(child) == {'revision': 0, 'order': CARDS, 'hidden': []}
            child_page = child.new_page(); self.open_panel(child_page)
            checkbox(child_page, 'finance').click(); child_saved = self.save(child_page)
            assert child_saved['hidden'] == ['finance'] and self.layout(owner) == saved and self.layout(partner) == second_layout
        self.passed('Two members and a signed second household retain independent home layouts; genuine paired TV state/configuration remain unchanged and member-layout API is forbidden')

    def write_anonymous(self, ctx, path, payload):
        response = ctx.request.post(self.base + path, data=payload)
        assert response.status == 200, response.text()
        return response.json()

    def future_keys(self, page):
        current = self.layout(page.context)
        # Future schema fixture only: the old-client public API correctly cannot introduce unknown keys.
        data = {'order': [FUTURE] + CARDS, 'hidden': [FUTURE, 'finance']}
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with sqlite3.connect(self.database) as con:
            con.execute('UPDATE member_dashboard_layout SET data=?,revision=? WHERE owner=?',
                        (json.dumps(data), current['revision'] + 1, 'member1'))
        self.open_panel(page)
        expect(page.get_by_text('还有 1 个当前版本暂不支持的卡片，其设置将由服务器保留。', exact=True)).to_be_visible()
        button(page, '恢复默认布局').click()
        saved = self.save(page)
        assert saved['order'] == CARDS + [FUTURE] and saved['hidden'] == [FUTURE]
        button(page, '关闭首页布局').click(); self.assert_home(page, saved)
        self.passed('A real future stored card survives an older-client default reset/save, with its hidden flag retained and no unknown component rendered')

    def conflict(self, page):
        self.open_panel(page)
        checkbox(page, 'finance').click()
        draft_order = self.panel_order(page)
        self.set_layout(page.context, order=list(reversed(CARDS)), hidden=['shopping'])
        before, writes = self.snapshot(), self.count_requests('PUT', PATH)
        with page.expect_response(lambda response: urlsplit(response.url).path == PATH and response.request.method == 'PUT') as pending:
            button(page, '保存首页布局').click()
        assert pending.value.status == 409
        expect(button(page, '查看最新首页布局')).to_be_enabled()
        assert self.panel_order(page) == draft_order
        expect(checkbox(page, 'finance')).not_to_be_checked()
        expect(button(page, '保存首页布局')).to_be_disabled()
        button(page, '查看最新首页布局').click()
        expect(page.get_by_test_id('home-layout-review')).to_be_visible()
        expect(button(page, '保留我的修改')).to_be_enabled()
        assert self.snapshot() == before and self.count_requests('PUT', PATH) == writes + 1
        button(page, '保留我的修改').click()
        expect(button(page, '保存首页布局')).to_be_enabled()
        assert self.snapshot() == before and self.panel_order(page) == draft_order
        saved = self.save(page)
        assert saved['order'] == draft_order + [FUTURE] and saved['hidden'] == ['finance', FUTURE]
        self.passed('Actual CAS 409 preserves draft; reading current layout and keeping modifications are zero-write; only an explicit second save overwrites the latest version')

    def blocked_navigation(self, page, message):
        original = page.url
        page.set_viewport_size({'width': 390, 'height': 844})
        page.get_by_role('tab', name='待办', exact=True).click()
        expect(page.get_by_text(message, exact=True)).to_be_visible()
        button(page, '知道了').click()
        expect(page.get_by_test_id('home-layout-panel')).to_be_visible()
        assert page.url == original
        button(page, '新建记录').click()
        page.get_by_role('menuitem', name='添加待办', exact=True).click()
        expect(page.get_by_text(message, exact=True)).to_be_visible()
        button(page, '知道了').click()
        expect(page.get_by_test_id('home-layout-panel')).to_be_visible()
        assert page.url == original

    def committed_reply_loss(self, page):
        self.open_panel(page)
        checkbox(page, 'tasks').click()
        before = self.layout(page.context)
        self.blocked_navigation(page, '首页布局还未保存，请先保存或放弃修改。')
        assert self.layout(page.context) == before
        attempts = []
        def lose(route):
            if route.request.method != 'PUT':
                route.continue_(); return
            attempts.append(route.request.post_data_json)
            response = route.fetch(max_redirects=0)
            assert response.status == 200
            route.abort('failed')
        page.route(self.base + PATH, lose)
        button(page, '保存首页布局').click()
        expect(page.get_by_test_id('home-layout-unknown')).to_be_visible()
        expect(button(page, '核对首页保存结果')).to_be_enabled()
        page.unroute(self.base + PATH, lose)
        assert len(attempts) == 1
        saved = self.layout(page.context)
        assert saved['revision'] == before['revision'] + 1 and 'tasks' in saved['hidden']
        expect(button(page, '关闭首页布局')).to_be_disabled()
        self.blocked_navigation(page, '首页布局的保存结果尚未核对，请先核对当前布局。')
        writes, stored = self.count_requests('PUT', PATH), self.snapshot()
        button(page, '核对首页保存结果').click()
        expect(page.get_by_test_id('home-layout-review')).to_be_visible()
        expect(button(page, '采用当前布局')).to_be_enabled()
        assert self.count_requests('PUT', PATH) == writes and self.snapshot() == stored
        button(page, '采用当前布局').click()
        expect(page.get_by_test_id('home-layout-unknown')).to_be_hidden()
        expect(button(page, '保存首页布局')).to_be_disabled()
        button(page, '关闭首页布局').click(); self.assert_home(page, saved)
        page.get_by_role('tab', name='待办', exact=True).click()
        expect(page.get_by_role('heading', name='共同待办', exact=True)).to_be_visible()
        assert self.count_requests('PUT', PATH) == writes and self.snapshot() == stored
        self.passed('Dirty/unknown navigation and create actions stay locked; a real committed reply loss is recovered by GET and explicit adoption with exactly one PUT')

    def offline_and_preflight(self, page):
        self.open_panel(page)
        checkbox(page, 'trips').click()
        before, writes = self.snapshot(), self.count_requests('PUT', PATH)
        page.context.set_offline(True)
        expect(checkbox(page, 'trips')).to_be_hidden()
        expect(button(page, '保存首页布局')).to_be_hidden()
        assert self.snapshot() == before and self.count_requests('PUT', PATH) == writes
        page.context.set_offline(False)
        expect(checkbox(page, 'trips')).to_be_enabled(timeout=15000)
        expect(checkbox(page, 'trips')).not_to_be_checked()
        expect(button(page, '保存首页布局')).to_be_enabled()
        failures = []
        def missing_identity(route):
            failures.append(True); route.abort('failed')
        page.route(self.base + '/api/me', missing_identity)
        button(page, '保存首页布局').click()
        expect(page.get_by_role('alert')).to_contain_text('连接中断', timeout=15000)
        page.unroute(self.base + '/api/me', missing_identity)
        assert failures and self.count_requests('PUT', PATH) == writes and self.snapshot() == before
        expect(page.get_by_test_id('home-layout-unknown')).to_be_hidden()
        button(page, '放弃修改并返回').click()
        button(page, '确认放弃修改').click()
        expect(button(page, '安排首页')).to_be_enabled()
        assert self.count_requests('PUT', PATH) == writes and self.snapshot() == before
        self.passed('Offline before submission conceals but preserves same-identity draft without a PUT; failed preflight identity read does not claim an unknown write or auto-save on recovery')

    def background_late_read(self, page):
        self.open_panel(page)
        checkbox(page, 'trips').click()
        draft_order = self.panel_order(page)
        visibility(page, True)
        expect(checkbox(page, 'trips')).to_be_hidden()
        held = []
        def hold(route):
            assert route.request.method == 'GET'
            response = route.fetch(max_redirects=0)
            assert response.status == 200
            held.append((route, response))
        page.route(self.base + PATH, hold, times=1)
        before, writes = self.snapshot(), self.count_requests('PUT', PATH)
        visibility(page, False)
        self.settle(page, lambda: bool(held))
        visibility(page, True)
        expect(checkbox(page, 'calendar')).to_be_hidden()
        held[0][0].fulfill(response=held[0][1])
        page.wait_for_timeout(300)
        expect(checkbox(page, 'calendar')).to_be_hidden()
        visibility(page, False)
        expect(checkbox(page, 'calendar')).to_be_enabled(timeout=15000)
        assert self.panel_order(page) == draft_order
        expect(checkbox(page, 'trips')).not_to_be_checked()
        expect(button(page, '保存首页布局')).to_be_enabled()
        assert self.snapshot() == before and self.count_requests('PUT', PATH) == writes
        # If the real version changes while hidden, the draft instead requires
        # explicit review; reading and discarding it must not silently save.
        visibility(page, True)
        latest = self.set_layout(page.context, hidden=['shopping'])
        changed_snapshot = self.snapshot()
        visibility(page, False)
        expect(page.get_by_test_id('home-layout-review')).to_be_visible(timeout=15000)
        expect(button(page, '保存首页布局')).to_be_disabled()
        expect(checkbox(page, 'trips')).not_to_be_checked()
        button(page, '采用当前布局').click()
        expect(checkbox(page, 'trips')).to_be_checked()
        expect(checkbox(page, 'shopping')).not_to_be_checked()
        assert self.snapshot() == changed_snapshot and self.count_requests('PUT', PATH) == writes
        button(page, '关闭首页布局').click(); self.assert_home(page, latest)
        self.passed('Late responses after background stay concealed; same-identity/current-revision draft resumes, while a changed real revision requires explicit review with no automatic save')

    def late_member_switch(self, browser):
        with self.flow(browser) as (ctx, page):
            self.home(page)
            original = self.layout(ctx)
            intercepted = []
            def switch(route):
                response = route.fetch(max_redirects=0)
                assert response.status == 200 and response.json() == original
                self.login(ctx, 2)
                assert self.get(ctx, '/api/me')['user']['id'] == 'member2'
                intercepted.append(True)
                route.fulfill(response=response)
            before, writes = self.snapshot(), self.count_requests('PUT', PATH)
            page.route(self.base + PATH, switch, times=1)
            button(page, '安排首页').click()
            expect(page.get_by_role('heading', name='伴侣，欢迎回家', exact=True)).to_be_visible(timeout=15000)
            expect(page.get_by_test_id('home-layout-panel')).to_be_hidden()
            assert intercepted and self.snapshot() == before and self.count_requests('PUT', PATH) == writes
            current = self.layout(ctx)
            assert current != original
            self.assert_home(page, current)
            button(page, '安排首页').click()
            expect(checkbox(page, 'calendar')).not_to_be_checked()
            assert self.panel_order(page) == list(reversed(CARDS))
        self.passed('A real old-member layout response cannot populate the editor after a genuine cookie login switch; the next editor belongs only to the new member')

    def run_scenarios(self, browser):
        with self.flow(browser) as (_, page):
            self.layout_keyboard_and_viewports(page)
            self.persistence_and_default(page)
            self.isolation(browser, page)
            self.future_keys(page)
            self.conflict(page)
            self.committed_reply_loss(page)
            self.offline_and_preflight(page)
            self.background_late_read(page)
        self.late_member_switch(browser)


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
    out = Path(__file__).resolve().parents[1] / 'test-results' / ('expo-home-layout-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], screenshots=[],
        head=head, tree=evidence['sourceTree'], buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(out / 'executed-harness.py'),
        sourceHashesBefore=hashes(), bundleHashesBefore=bundle_hashes(), productionWrites=0, realCloud=False, realAI=False,
        physicalTelevision=False, scope='Real isolated Flask/SQLite/Edge, synthetic households and actual session/TV cookies. No successful business-response mocks or HTML injection. Visibilitychange is explicitly simulated; screenshots show current viewports, not every inner-scroll position.')
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
                    folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='expo-home-layout-')))
                    run = Run(root, bundle, folder, report, out, lifecycle)
                    run.run_scenarios(browser)
                    assert len(report['checks']) == 9 and not report['pageErrors'] and not report['externalRequests']
                    report['passed'] = True
            finally:
                browser.close()
    except Exception:
        report['failure'] = traceback.format_exc()
        print(report['failure'], flush=True)
    finally:
        report['sourceHashesAfter'] = hashes(); report['bundleHashesAfter'] = bundle_hashes()
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
