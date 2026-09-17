"""Seven independent real local member-management checks; reviewed bundle only.

Successful DTOs always come from Flask/SQLite. Fault injection drops real
responses or a request before dispatch. No cloud, worker or production access.
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
import time
import traceback
from unittest.mock import patch
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright
import browser_expo_finance_check as fixture
from browser_expo_finance_check import Run as BaseRun, button, sha, visibility

BASE = '/api/members'
SCENARIOS = ('roles_login_restart', 'revoke_and_login', 'permission_boundaries',
             'lost_write_responses', 'conflict_and_readback_failure', 'lifecycle_and_identity', 'widths_and_themes')
WIDTHS = (320, 390, 1280, 1920)


class Run(BaseRun):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        assert Path(self.source.__file__).resolve() == (self.root / 'app.py').resolve()
        paths = {'tests/browser_expo_household_members_check.py': str(Path(__file__).resolve()),
                 'tests/browser_expo_finance_check.py': str(Path(fixture.__file__).resolve()),
                 **{'tests/' + name + '.py': str(Path(sys.modules[name].__file__).resolve())
                    for name in ('test_financial_files', 'test_app')}}
        digests = {name: sha(Path(path)) for name, path in paths.items()}
        assert digests['tests/browser_expo_household_members_check.py'] == self.report['harnessSha256']
        for name, path in paths.items():
            if name != 'tests/browser_expo_household_members_check.py':
                assert sha(Path(path)) == sha(self.root / name), name
        assert self.report.setdefault('fixtureActualPaths', paths) == paths
        assert self.report.setdefault('fixtureHashes', digests) == digests
        self.members_started = time.monotonic()
        self.members_timeline = self.report.setdefault('timelines', {}).setdefault(self.out.name, [])

    def clear_finance(self):
        pass  # Each case has a new independent temporary household database.

    def trace(self, event, **fields):
        assert len(self.members_timeline) < 1000, 'Bounded member request timeline exceeded'
        self.members_timeline.append(dict(ms=round((time.monotonic() - self.members_started) * 1000), event=event, **fields))

    def watch(self, page):
        def relevant(req): return urlsplit(req.url).path.startswith(BASE)
        page.on('request', lambda req: self.trace('browser-request', method=req.method, path=urlsplit(req.url).path) if relevant(req) else None)
        page.on('response', lambda res: self.trace('browser-response', method=res.request.method, path=urlsplit(res.url).path, status=res.status) if relevant(res.request) else None)
        page.on('requestfailed', lambda req: self.trace('browser-request-failed', method=req.method, path=urlsplit(req.url).path) if relevant(req) else None)

    def protected(self):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database)) as con:
            tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            skipped = {'users', 'member_sessions', 'member_session_browsers', 'attempts', 'audit', 'sqlite_sequence', 'settings'}
            return {**{name: con.execute('SELECT * FROM "' + name + '" ORDER BY rowid').fetchall() for name in tables if name not in skipped},
                    'settings_without_meta': con.execute("SELECT * FROM settings WHERE id<>'meta' ORDER BY id").fetchall(),
                    'user_private_fields': con.execute('SELECT id,username,name,password FROM users ORDER BY id').fetchall()}

    def members(self, ctx): return self.get(ctx, BASE)

    @staticmethod
    def member(snapshot, uid='member2'): return next(row for row in snapshot['members'] if row['id'] == uid)

    def ready(self, page):
        expect(page.get_by_test_id('members-current')).to_be_visible(timeout=15000)
        expect(button(page, '刷新成员列表')).to_be_enabled(timeout=15000)
        expect(page.get_by_label('正在核对家庭成员', exact=True)).to_have_count(0)

    def open_members(self, page, navigate=True):
        page.bring_to_front()
        if navigate: page.goto(self.base + '/app/more')
        page.get_by_label('家庭与成员', exact=True).click()
        expect(page.get_by_test_id('household-members-panel')).to_be_visible(timeout=15000)
        self.ready(page)

    def choose(self, page, kind, target):
        button(page, ('调整角色：' if kind == 'role' else '退出所有浏览器：') + target['name']).click()
        expect(page.get_by_role('heading', name='调整成员角色？' if kind == 'role' else '退出所有浏览器？', exact=True)).to_be_visible()
        expect(page.get_by_text('成员：' + target['name'], exact=True)).to_be_visible()

    def confirm_write(self, page, kind, target, expected=200, drop=False, unsent=False, on_result=None):
        method = 'PATCH' if kind == 'role' else 'POST'
        path = BASE + '/' + target['id'] + ('/role' if kind == 'role' else '/revoke-sessions')
        wanted = {'expectedAuthVersion': target['authVersion']}
        if kind == 'role': wanted['householdRole'] = 'member' if target['householdRole'] == 'admin' else 'admin'
        calls = []
        def forward(route):
            assert route.request.method == method and route.request.url == self.base + path
            body = route.request.post_data_json; assert body == wanted
            self.trace('mutation-intercepted', method=method, path=path)
            if unsent:
                calls.append(dict(body=body, status=None)); self.trace('mutation-not-dispatched', method=method, path=path); route.abort('failed'); return
            response = route.fetch(max_redirects=0); raw = response.body(); result = json.loads(raw)
            self.trace('real-mutation-response', method=method, path=path, status=response.status)
            calls.append(dict(body=body, status=response.status, result=result))
            if on_result: on_result(calls[-1])
            if drop: route.abort('failed')
            else: route.fulfill(status=response.status, headers=response.headers, body=raw)
        page.route(self.base + path, forward)
        try:
            button(page, '确认调整角色' if kind == 'role' else '确认退出所有浏览器').click()
            self.settle(page, lambda: len(calls) == 1)
            assert calls[0]['status'] == (None if unsent else expected), calls
            return calls[0]
        finally: page.unroute(self.base + path, forward)

    def unknown_ready(self, page):
        expect(page.get_by_test_id('members-unknown')).to_be_visible()
        expect(button(page, '读取当前成员状态')).to_be_enabled(timeout=15000)
        expect(page.get_by_label('正在核对家庭成员', exact=True)).to_have_count(0)
        expect(button(page, '结束本次核对')).to_have_count(0)

    def end_review(self, page):
        button(page, '读取当前成员状态').click()
        expect(button(page, '结束本次核对')).to_be_enabled(timeout=15000)
        expect(page.get_by_test_id('members-current')).to_be_visible()
        expect(page.get_by_role('button', name=re.compile(r'^(调整角色|退出所有浏览器)：'))).to_have_count(0)
        button(page, '结束本次核对').click(); self.ready(page)
        expect(page.get_by_test_id('members-unknown')).to_have_count(0)

    def roles_login_restart(self, browser):
        with self.flow(browser) as (ctx, page), ExitStack() as extras:
            partner = self.context(browser, 2); extras.callback(partner.close)
            before = self.members(ctx); assert [r['householdRole'] for r in before['members']] == ['admin', 'admin']
            preserved = self.protected(); self.watch(page); self.open_members(page)
            expect(page.get_by_test_id('members-current')).to_contain_text('管理员')
            target = self.member(before); self.choose(page, 'role', target); result = self.confirm_write(page, 'role', target)
            self.ready(page); assert result['result']['revoked'] == 1
            self.get(partner, BASE, 401); self.login(partner, 2)
            ordinary = self.members(partner); assert ordinary['currentMemberId'] == 'member2'
            assert all(r['activeSessionCount'] is None and not any(r['capabilities'].values()) for r in ordinary['members'])
            other_page = partner.new_page(); self.open_members(other_page)
            expect(other_page.get_by_test_id('members-current')).to_contain_text('普通成员 · 本人')
            expect(other_page.get_by_role('button', name=re.compile(r'^(调整角色|退出所有浏览器)：'))).to_have_count(0)
            page.bring_to_front(); self.ready(page); button(page, '刷新成员列表').click(); self.ready(page)
            target = self.member(self.members(ctx)); assert target['householdRole'] == 'member'
            self.choose(page, 'role', target); self.confirm_write(page, 'role', target); self.ready(page)
            self.get(partner, BASE, 401); self.login(partner, 2); assert self.member(self.members(partner))['householdRole'] == 'admin'
            self.restart(); assert all(r['householdRole'] == 'admin' for r in self.members(ctx)['members'])
            assert self.protected() == preserved
            self.passed('Both defaults are administrators; real role changes revoke the target session, ordinary login hides management, promotion/restart preserve current role and private data')

    def revoke_and_login(self, browser):
        with self.flow(browser) as (ctx, page), ExitStack() as extras:
            targets = [self.context(browser, 2) for _ in range(2)]
            for other in targets: extras.callback(other.close)
            target = self.member(self.members(ctx)); assert target['activeSessionCount'] == 2
            preserved = self.protected(); self.watch(page); self.open_members(page); self.choose(page, 'revoke', target)
            result = self.confirm_write(page, 'revoke', target); self.ready(page)
            assert result['result']['revoked'] == 2
            for other in targets: self.get(other, BASE, 401)
            assert self.get(ctx, '/api/me')['user']['id'] == 'member1'
            current = self.member(self.members(ctx)); assert current['authVersion'] == target['authVersion'] + 1 and current['activeSessionCount'] == 0
            self.login(targets[0], 2); assert self.get(targets[0], '/api/me')['user']['role'] == 'member'
            assert self.member(self.members(ctx))['activeSessionCount'] == 1 and self.protected() == preserved
            assert self.count_requests('POST', BASE + '/member2/revoke-sessions') == 1
            self.passed('One explicit revocation invalidates two real target cookies, preserves the caller and data, and permits target login again')

    def permission_boundaries(self, browser):
        with self.flow(browser) as (ctx, page), ExitStack() as extras:
            anonymous = self.context(browser, None); extras.callback(anonymous.close)
            self.get(anonymous, BASE, 401)
            assert anonymous.request.post(self.base + BASE + '/member2/revoke-sessions', data={'expectedAuthVersion': 1}).status == 401
            tv = self.context(browser, None); extras.callback(tv.close)
            pair = tv.request.post(self.base + '/api/pair/start', data={}).json()
            self.write(ctx, 'POST', '/api/pair/approve', {'code': pair['code'], 'name': '合成成员管理只读电视'})
            assert tv.request.post(self.base + '/api/pair/poll', data={'secret': pair['secret']}).json()['approved']
            self.get(tv, BASE, 403)
            assert tv.request.post(self.base + BASE + '/member2/revoke-sessions', data={'expectedAuthVersion': 1}).status == 403
            target = self.member(self.members(ctx)); self.write(ctx, 'PATCH', BASE + '/member2/role', {'expectedAuthVersion': target['authVersion'], 'householdRole': 'member'})
            ordinary = self.context(browser, 2); extras.callback(ordinary.close)
            source = self.members(ordinary); main_version = self.member(source, 'member1')['authVersion']
            self.write(ordinary, 'POST', BASE + '/member1/revoke-sessions', {'expectedAuthVersion': main_version}, 403)
            self.write(ordinary, 'PATCH', BASE + '/member1/role', {'expectedAuthVersion': main_version, 'householdRole': 'member'}, 403)
            invitation = self.write(ctx, 'POST', '/api/spaces/invitations', {}, 201)['invitation']
            family = self.write(ctx, 'POST', '/api/spaces/redeem', {'invitation': invitation, 'name': '合成成员第二家庭', 'slug': 'members-other',
                'MEMBER1_PASSWORD': 'testing-password-one', 'MEMBER2_PASSWORD': 'testing-password-two'}, 201)
            foreign = self.context(browser, None); extras.callback(foreign.close)
            assert foreign.request.get(self.base + family['entry']).status == 200; self.login(foreign)
            self.write(foreign, 'POST', '/api/profile', {'name': '合成第二家庭管理员'})
            before = self.members(ctx); foreign_target = self.member(self.members(foreign))
            self.write(foreign, 'POST', BASE + '/member2/revoke-sessions', {'expectedAuthVersion': foreign_target['authVersion']})
            assert self.member(self.members(foreign))['authVersion'] == foreign_target['authVersion'] + 1
            assert self.members(ctx) == before
            self.write(foreign, 'POST', BASE + '/member2/revoke-sessions', {'expectedAuthVersion': 2, 'household': 'default'}, 400)
            self.open_members(page); expect(page.locator('body')).not_to_contain_text('合成第二家庭管理员')
            tv_page = tv.new_page(); tv_page.goto(self.base + '/app/tv')
            expect(tv_page.get_by_test_id('expo-tv-board')).to_be_visible(timeout=15000)
            expect(tv_page.get_by_test_id('household-members-panel')).to_have_count(0)
            self.passed('Anonymous/paired TV/ordinary direct management is rejected; the same member IDs in another signed household only affect its own database')

    def lost_write_responses(self, browser):
        with self.flow(browser) as (ctx, page):
            self.watch(page); self.open_members(page); preserved = self.protected()
            for kind in ('revoke', 'role'):
                target = self.member(self.members(ctx)); self.choose(page, kind, target)
                reads = self.count_requests('GET', BASE)
                result = self.confirm_write(page, kind, target, drop=True); self.unknown_ready(page)
                assert result['result']['member']['authVersion'] == target['authVersion'] + 1
                assert self.count_requests('GET', BASE) == reads, 'Unknown result must not auto-read or submit'
                expect(page.get_by_test_id('members-current')).to_have_count(0)
                self.end_review(page)
                path = BASE + '/member2/' + ('role' if kind == 'role' else 'revoke-sessions')
                assert self.count_requests('PATCH' if kind == 'role' else 'POST', path) == 1
                assert self.member(self.members(ctx))['authVersion'] == target['authVersion'] + 1
            assert self.protected() == preserved
            self.passed('Real POST and PATCH each commit once with dropped replies; only explicit GET plus local acknowledgement unlocks, without interpreting the list as a receipt or writing again')

    def conflict_and_readback_failure(self, browser):
        with self.flow(browser) as (ctx, page), ExitStack() as extras:
            parallel = self.context(browser); extras.callback(parallel.close)
            self.watch(page); self.open_members(page); target = self.member(self.members(ctx))
            self.choose(page, 'revoke', target)
            self.write(parallel, 'POST', BASE + '/member2/revoke-sessions', {'expectedAuthVersion': target['authVersion']})
            self.confirm_write(page, 'revoke', target, expected=409)
            expect(button(page, '重新读取成员列表')).to_be_enabled(timeout=15000)
            expect(page.get_by_test_id('members-current')).to_have_count(0); expect(page.get_by_test_id('members-unknown')).to_have_count(0)
            button(page, '重新读取成员列表').click(); self.ready(page)
            target = self.member(self.members(ctx)); armed = False; dropped = []
            def arm(packet):
                nonlocal armed
                assert packet['status'] == 200; armed = True; self.trace('readback-fault-armed')
            def lose_current(route):
                assert route.request.method == 'GET'
                response = route.fetch(max_redirects=0); raw = response.body()
                if armed and response.status == 200:
                    assert len(dropped) < 32; dropped.append(json.loads(raw)); self.trace('real-current-get-dropped', status=200); route.abort('failed')
                else: route.fulfill(status=response.status, headers=response.headers, body=raw)
            page.route(self.base + BASE, lose_current)
            try:
                self.choose(page, 'role', target); self.confirm_write(page, 'role', target, on_result=arm)
                self.settle(page, lambda: len(dropped) >= 1)
                expect(button(page, '重新读取成员列表')).to_be_enabled(timeout=15000)
                expect(page.get_by_test_id('members-current')).to_have_count(0); expect(page.get_by_test_id('members-unknown')).to_have_count(0)
                expect(page.get_by_role('button', name=re.compile(r'^(调整角色|退出所有浏览器)：'))).to_have_count(0)
                assert self.member(self.members(ctx))['householdRole'] == 'member'
            finally: page.unroute(self.base + BASE, lose_current)
            self.trace('fault-released-for-explicit-read'); button(page, '重新读取成员列表').click(); self.ready(page)
            expect(page.get_by_test_id('household-member-member2')).to_contain_text('普通成员')
            assert self.count_requests('PATCH', BASE + '/member2/role') == 1
            self.passed('A real concurrent version change yields 409 and fresh selection; after accepted PATCH every matching real current GET is dropped until explicit read-only recovery, with no duplicate PATCH')

    def lifecycle_and_identity(self, browser):
        with self.flow(browser) as (ctx, page):
            page.set_viewport_size({'width': 1280, 'height': 1000}); self.watch(page); self.open_members(page)
            target = self.member(self.members(ctx)); self.choose(page, 'revoke', target)
            visibility(page, True); expect(page.get_by_test_id('members-current')).to_have_count(0); expect(button(page, '确认退出所有浏览器')).not_to_be_visible()
            visibility(page, False); expect(button(page, '确认退出所有浏览器')).to_be_enabled(timeout=15000); button(page, '取消').click(); self.ready(page)
            page.evaluate("window.dispatchEvent(new Event('blur'))"); expect(page.get_by_test_id('members-current')).to_have_count(0)
            visibility(page, False); page.evaluate("window.dispatchEvent(new Event('online'))"); expect(page.get_by_test_id('members-current')).to_have_count(0)
            page.evaluate("window.dispatchEvent(new Event('focus'))"); self.ready(page)
            ctx.set_offline(True); expect(page.get_by_test_id('members-current')).to_have_count(0)
            ctx.set_offline(False); self.ready(page)
            self.choose(page, 'revoke', target); self.confirm_write(page, 'revoke', target, unsent=True); self.unknown_ready(page)
            version = self.member(self.members(ctx))['authVersion']; assert version == target['authVersion']
            button(page, '首页').click(); self.unknown_ready(page); expect(page.get_by_test_id('household-members-panel')).to_be_visible()
            visibility(page, True); expect(page.get_by_test_id('members-unknown')).to_have_count(0)
            reads = self.count_requests('GET', BASE); visibility(page, False); self.unknown_ready(page)
            assert self.count_requests('GET', BASE) == reads
            self.end_review(page); assert self.count_requests('POST', BASE + '/member2/revoke-sessions') == 1
            button(page, '返回更多').click(); expect(page.get_by_test_id('household-members-panel')).to_have_count(0)
            self.open_members(page, navigate=False); delivered = []
            def late_identity(route):
                response = route.fetch(max_redirects=0); raw = response.body(); assert response.status == 200
                assert json.loads(raw)['currentMemberId'] == 'member1'
                self.login(ctx, 2); route.fulfill(status=response.status, headers=response.headers, body=raw); delivered.append(True)
            page.route(self.base + BASE, late_identity)
            try:
                button(page, '刷新成员列表').click(); self.settle(page, lambda: delivered == [True])
                expect(page.get_by_test_id('household-members-panel')).to_have_count(0, timeout=15000)
            finally: page.unroute(self.base + BASE, late_identity)
            self.open_members(page, navigate=False)
            expect(page.get_by_test_id('household-member-member2')).to_contain_text('本人')
            expect(page.get_by_test_id('members-unknown')).to_have_count(0)
            self.passed('Hidden/window blur/offline conceal members and stale actions; unresolved intent blocks navigation until explicit review, and a real cookie switch discards a late old-member response')

    def capture_members(self, page, label, width, target, controls):
        page.set_viewport_size({'width': width, 'height': 1080 if width >= 1280 else 844})
        page.evaluate('() => document.fonts.ready'); target.scroll_into_view_if_needed(); page.wait_for_timeout(800)
        page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
        metrics = page.evaluate('''() => ({width:innerWidth,scroll:document.documentElement.scrollWidth,
          clipped:[...document.querySelectorAll('[data-testid="household-members-panel"] [role="button"],[data-testid="modal-surface"] [role="button"]')]
            .filter(n=>{const r=n.getBoundingClientRect();return r.width>0&&r.height>0&&r.bottom>0&&r.top<innerHeight&&(r.right>innerWidth+2||r.left< -2)})
            .map(n=>({label:n.getAttribute('aria-label'),box:n.getBoundingClientRect().toJSON()}))})''')
        assert metrics['scroll'] <= width + 2 and not metrics['clipped'], metrics
        for control in controls:
            box = control.bounding_box(); assert box and box['width'] >= 44 and box['height'] >= 44, box
        path = self.out / f'{label}-{width}.png'; page.screenshot(path=str(path), full_page=False)
        self.report['screenshots'].append(dict(path=path.relative_to(self.out.parent).as_posix(), sha256=sha(path), width=width,
            metrics=metrics, scope='Settled visible viewport after scrolling; inner ScrollView and all-screen accessibility are not fully covered.'))

    def widths_and_themes(self, browser):
        with self.flow(browser) as (ctx, page), ExitStack() as extras:
            partner = self.context(browser, 2); extras.callback(partner.close)
            long_name = '合成共同管理员姓名用于窄屏换行'
            self.write(partner, 'POST', '/api/profile', {'name': long_name})
            self.open_members(page); target = self.member(self.members(ctx))
            for width in WIDTHS:
                self.capture_members(page, 'members-light', width, page.get_by_test_id('household-member-member2'),
                    [button(page, '调整角色：' + long_name), button(page, '退出所有浏览器：' + long_name)])
            preferences = self.get(ctx, '/api/preferences')
            self.write(ctx, 'PUT', '/api/preferences', {'revision': preferences['revision'], 'changes': {'colorMode': 'dark', 'density': 'compact'}})
            page.reload(); self.open_members(page)
            page.wait_for_function("getComputedStyle(document.documentElement).colorScheme === 'dark'")
            button(page, '调整角色：' + long_name).focus(); page.keyboard.press('Enter')
            expect(button(page, '确认调整角色')).to_be_enabled()
            for width in WIDTHS:
                self.capture_members(page, 'members-confirm-dark', width, page.get_by_test_id('modal-surface'), [button(page, '取消'), button(page, '确认调整角色')])
            button(page, '取消').focus(); page.keyboard.press('Enter'); self.ready(page)
            assert self.member(self.members(ctx)) == target
            assert self.count_requests('PATCH', BASE + '/member2/role') == self.count_requests('POST', BASE + '/member2/revoke-sessions') == 0
            self.passed('Eight settled four-width captures cover populated light members and dark compact confirmation; new buttons measure 44px and keyboard opening/cancel performs no write')

    @classmethod
    def run_scenarios(cls, root, bundle, report, out, browser):
        for name in SCENARIOS:
            case_out = out / name; case_out.mkdir(); folder = None
            before = (len(report['checks']), len(report['pageErrors']), len(report['externalRequests']))
            case = dict(name=name, passed=False, temporaryFixtureRemoved=False)
            try:
                with ExitStack() as resources:
                    folder = Path(resources.enter_context(tempfile.TemporaryDirectory(prefix='household-members-browser-')))
                    case['temporaryDirectory'] = str(folder)
                    run = cls(root, bundle, folder, report, case_out, resources); getattr(run, name)(browser)
                assert not folder.exists() and len(report['checks']) == before[0] + 1
                assert len(report['pageErrors']) == before[1] and len(report['externalRequests']) == before[2]
                case['passed'] = True
            except Exception:
                del report['checks'][before[0]:]
                failure = traceback.format_exc(); (case_out / 'failure.txt').write_text(failure, encoding='utf-8')
                report['scenarioFailures'].append(dict(scenario=name, traceback=failure, artifacts=name)); print('FAIL ' + name + '\n' + failure, flush=True)
            finally:
                case['temporaryFixtureRemoved'] = folder is not None and not folder.exists(); report['scenarioResults'].append(case)
        assert not report['scenarioFailures'], 'Independent failures retained; no failed scenario is counted as passed'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-harness-head', required=True); parser.add_argument('--expected-harness-sha256', required=True)
    parser.add_argument('--source-root', required=True, type=Path); parser.add_argument('--expected-head', required=True)
    parser.add_argument('--bundle', required=True, type=Path); parser.add_argument('--expected-build-evidence', required=True)
    args = parser.parse_args(); root, bundle = args.source_root.resolve(), args.bundle.resolve()
    assert all(re.fullmatch('[a-f0-9]{40}', v) for v in (args.expected_head, args.expected_harness_head))
    assert all(re.fullmatch('[a-f0-9]{64}', v) for v in (args.expected_build_evidence, args.expected_harness_sha256))
    harness_root = Path(__file__).resolve().parents[1]
    def command_git(directory, *command): return subprocess.check_output(['git', '--no-replace-objects', *command], cwd=directory, text=True).strip()
    def git(*command): return command_git(root, *command)
    def harness_git(*command): return command_git(harness_root, *command)
    head = git('rev-parse', 'HEAD'); harness_head = harness_git('rev-parse', 'HEAD')
    assert head == args.expected_head and harness_head == args.expected_harness_head
    assert not git('status', '--porcelain=v1') and not harness_git('status', '--porcelain=v1')
    assert sha(Path(__file__)) == args.expected_harness_sha256
    own_names = ('tests/browser_expo_household_members_check.py', 'docs/EXPO-HOUSEHOLD-MEMBERS-BROWSER.md')
    def harness_hashes(): return {name: sha(harness_root / name) for name in own_names}
    evidence_path = bundle.parent / 'build-evidence.json'; assert sha(evidence_path) == args.expected_build_evidence
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    assert evidence['sourceHead'] == head and evidence['sourceTree'] == git('rev-parse', 'HEAD^{tree}')
    names = subprocess.check_output(['git', '--no-replace-objects', 'ls-files', '-z'], cwd=root).decode('utf-8').rstrip('\0').split('\0')
    def hashes(): return {name: sha(root / name) for name in names}
    def exports(): return {p.relative_to(bundle).as_posix(): sha(p) for p in bundle.rglob('*') if p.is_file()}
    assert exports() == evidence['files'] and all(sha(root / name) == value for name, value in evidence['inputFiles'].items())
    out = harness_root / 'test-results' / ('expo-household-members-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True); shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], screenshots=[], scenarioResults=[], scenarioFailures=[], head=head, tree=evidence['sourceTree'],
        sourceRoot=str(root), harnessRoot=str(harness_root), harnessHead=harness_head, harnessTree=harness_git('rev-parse', 'HEAD^{tree}'),
        harnessSourceHashesBefore=harness_hashes(), harnessPathPresentInApplicationHead=own_names[0] in names,
        buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(out / 'executed-harness.py'), sourceHashesBefore=hashes(), bundleHashesBefore=exports(),
        requestedChecks=len(SCENARIOS), productionWrites=0, realPersonalData=False, realCloud=False, physicalTelevision=False,
        scope='Seven independent local Flask/SQLite/HTTPS/Edge fixtures. Real business responses only; bounded real-response drops. Visibility/window focus events are simulated, offline is browser network state. Eight viewport captures require separate human review, not full accessibility or physical TV acceptance.')
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
                assert len(report['checks']) == len(SCENARIOS) and len(report['screenshots']) == 8
                assert len(report['fixtureHashes']) == 4 and not report['pageErrors'] and not report['externalRequests']; report['passed'] = True
            finally: browser.close()
    except Exception:
        report['passed'] = False; report['failure'] = traceback.format_exc(); print(report['failure'], flush=True)
    finally:
        report['sourceHashesAfter'] = hashes(); report['bundleHashesAfter'] = exports()
        report['sourceUnchanged'] = report['sourceHashesBefore'] == report['sourceHashesAfter']; report['bundleUnchanged'] = report['bundleHashesBefore'] == report['bundleHashesAfter']
        report['sourceStillFrozen'] = git('rev-parse', 'HEAD') == head and not git('status', '--porcelain=v1')
        report['harnessSourceHashesAfter'] = harness_hashes()
        report['harnessStillFrozen'] = harness_git('rev-parse', 'HEAD') == harness_head and not harness_git('status', '--porcelain=v1') and report['harnessSourceHashesBefore'] == report['harnessSourceHashesAfter']
        report['fixtureHashesAfter'] = {name: sha(Path(path)) for name, path in report.get('fixtureActualPaths', {}).items()}
        report['fixturesUnchanged'] = len(report.get('fixtureHashes', {})) == 4 and report['fixtureHashesAfter'] == report['fixtureHashes']
        report['temporaryFixtureRemoved'] = len(report['scenarioResults']) == len(SCENARIOS) and all(c['temporaryFixtureRemoved'] for c in report['scenarioResults'])
        report['passed'] = report['passed'] and all(report[k] for k in ('sourceUnchanged', 'bundleUnchanged', 'sourceStillFrozen', 'harnessStillFrozen', 'fixturesUnchanged', 'temporaryFixtureRemoved'))
        with (out / 'result.json').open('x', encoding='utf-8') as stream: stream.write(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'report': str(out / 'result.json')}, ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    raise SystemExit(main())
