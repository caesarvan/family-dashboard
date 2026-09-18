"""Four real Expo membership chains, restricted to temporary loopback fixtures.

UI writes use the actual application and SQLite. The only intercepted write
response is fetched from the real server and then dropped, never substituted.
The independently committed harness and the exact application/build are bound
separately so this test need not be shipped in the application being exercised.
"""
import argparse
from contextlib import ExitStack, closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import traceback
from unittest.mock import patch
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server
import browser_expo_finance_check as fixture
from browser_expo_finance_check import Run as BaseRun, Quiet, button, row, sha, visibility

CASES = ('legacy_binding', 'invitation_lifecycle', 'two_households_logout', 'lost_invitation_layout')
PANELS = {'account': 'personal-account-panel', 'invitation': 'membership-invitations-panel',
          'management': 'membership-management-panel'}
LABELS = {'account': '我的家庭账户', 'invitation': '邀请与加入家庭', 'management': '管理成员关系'}
PASSWORD = 'synthetic-personal-password'


def readable_path(path):
    value = str(Path(path).resolve())
    if os.name == 'nt' and not value.startswith('\\\\?\\'):
        value = '\\\\?\\' + value
    return Path(value)


def file_manifest(root):
    root = readable_path(root)
    result = {}
    for folder, directories, files in os.walk(root):
        assert not any((Path(folder) / name).is_symlink() for name in directories + files)
        for name in files:
            path = Path(folder) / name
            result[path.relative_to(root).as_posix()] = sha(path)
    return result


class Run(BaseRun):
    def start(self, port=0):
        # Reserve the real HTTPS port before constructing PersonalAccounts,
        # whose origin is captured at initialization. No endpoint is replaced.
        self.server = make_server('127.0.0.1', port, lambda *_: (), threaded=True,
                                  request_handler=Quiet, ssl_context='adhoc')
        self.lifecycle.callback(self.stop)
        self.base = 'https://127.0.0.1:' + str(self.server.server_port)
        self.cfg['PUBLIC_ORIGIN'] = self.base
        try:
            self.application = self.source.create_app(self.cfg)
            self.server.set_app(self.application)
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
        except Exception:
            self.server.server_close()
            self.server = None
            raise

    def __init__(self, root, bundle, folder, report, out, lifecycle):
        # The short temp prefix also keeps Flask's normal filesystem paths
        # below MAX_PATH; source exports may still need the extended prefix.
        expected = file_manifest(bundle)
        if os.name == 'nt':
            assert all(len(str(folder / 'static' / 'experience' / name)) < 260 for name in expected)
        super().__init__(root, readable_path(bundle), folder, report, out, lifecycle)
        assert file_manifest(folder / 'static' / 'experience') == expected
        report.setdefault('fixtureExportCopies', []).append({'case': out.name, 'files': len(expected), 'hashesEqual': True})
        assert Path(self.source.__file__).resolve() == (self.root / 'app.py').resolve()
        paths = {'tests/browser_expo_finance_check.py': str(Path(fixture.__file__).resolve()),
                 **{'tests/' + name + '.py': str(Path(sys.modules[name].__file__).resolve())
                    for name in ('test_financial_files', 'test_app')}}
        digests = {name: sha(Path(path)) for name, path in paths.items()}
        assert all(digest == sha(self.root / name) for name, digest in digests.items())
        assert self.report.setdefault('fixtureActualPaths', paths) == paths
        assert self.report.setdefault('fixtureHashes', digests) == digests
        self.stage_number = 0

    def clear_finance(self):
        pass  # Each chain has its own new databases; no business-data reset.

    def stage(self, name):
        self.stage_number += 1
        self.report['stages'].append({'case': self.out.name, 'number': self.stage_number, 'started': name})
        print(self.out.name + ': ' + name, flush=True)

    def ready(self, page, kind):
        panel = page.get_by_test_id(PANELS[kind])
        expect(panel).to_be_visible(timeout=20000)
        expect(button(panel, '清空未提交内容' if kind != 'management' else '刷新成员关系')).to_be_enabled(timeout=20000)
        expect(panel.get_by_label('正在核对账户与家庭', exact=True)).to_have_count(0)
        return panel

    def open_panel(self, page, kind, *, signed_member=True):
        page.bring_to_front()
        page.goto(self.base + '/app/more')
        if signed_member:
            target = page.get_by_label('家庭与成员', exact=True)
            expect(target).to_be_visible(timeout=20000)
            target.click()
            expect(button(page, LABELS[kind])).to_be_enabled(timeout=20000)
            button(page, LABELS[kind]).click()
        else:
            label = '使用邀请加入家庭' if kind == 'invitation' else '我的家庭账户'
            expect(button(page, label)).to_be_enabled(timeout=20000)
            button(page, label).click()
        return self.ready(page, kind)

    def actual(self, page, method, path, action, status=200):
        with page.expect_response(lambda r: urlsplit(r.url).path == path and r.request.method == method) as pending:
            action()
        response = pending.value
        assert response.status == status, (path, response.status, response.text())
        return response.json(), response.request.post_data_json

    def command(self, page, action, path, *, confirm='确认继续', status=200):
        button(page, action).click()
        expect(button(page, confirm)).to_be_enabled()
        result, body = self.actual(page, 'POST', path, lambda: button(page, confirm).click(), status)
        expect(button(page, '读取当前状态')).to_be_enabled(timeout=20000)
        expect(page.get_by_test_id('membership-operation')).to_contain_text(body['requestId'])
        return result, body

    def finish(self, page):
        button(page, '读取当前状态').click()
        expect(page.get_by_test_id('membership-operation')).to_have_count(0, timeout=20000)

    def register_old(self, ctx, page, login):
        self.open_panel(page, 'account')
        page.get_by_label('个人账号', exact=True).fill(login)
        page.get_by_label('个人密码', exact=True).fill(PASSWORD)
        page.get_by_label('当前家庭密码', exact=True).fill('testing-password-one')
        self.actual(page, 'POST', '/api/account/eligibility', lambda: button(page, '验证当前家庭身份').click())
        result, _ = self.command(page, '创建个人账户', '/api/account/register', status=201)
        self.finish(page)
        self.ready(page, 'account')
        assert self.get(ctx, '/api/account/me')['account'] == result['account']
        assert not self.get(ctx, '/api/account/households')['memberships'], 'Registration must not bind silently'
        return result['account']

    def bind(self, ctx, page):
        page.get_by_label('当前家庭密码', exact=True).fill('testing-password-one')
        result, _ = self.command(page, '绑定这个身份', '/api/membership-links')
        self.finish(page)
        self.ready(page, 'account')
        directory = self.get(ctx, '/api/account/households')['memberships']
        assert any(h['id'] == result['id'] and h['memberId'] == result['memberId'] for h in directory)
        return result

    def invite(self, ctx, page):
        self.open_panel(page, 'invitation')
        result, body = self.command(page, '创建邀请码', '/api/member-invitations')
        token = result['token']
        assert re.fullmatch('[A-Za-z0-9_-]{43}', token)
        self.finish(page)
        expect(page.get_by_test_id('membership-invitation-secret')).to_contain_text(token)
        button(page, '我已保存邀请码').click()
        expect(page.get_by_test_id('membership-invitation-secret')).to_have_count(0)
        receipt = self.get(ctx, '/api/membership-operations/' + body['requestId'])
        assert receipt['state'] == 'completed' and 'token' not in receipt['result']
        return token, result['invitation']['id']

    def inspect(self, page, token, slug='home'):
        page.get_by_label('家庭地址简称', exact=True).fill(slug)
        page.get_by_label('邀请码', exact=True).fill(token)
        result, _ = self.actual(page, 'POST', '/api/account/invitations/inspect', lambda: button(page, '核对邀请').click())
        expect(page.get_by_test_id('membership-join-preview')).to_contain_text(result['household']['name'])
        return result

    def join(self, ctx, page, token, *, register=False):
        self.open_panel(page, 'invitation', signed_member=False)
        self.inspect(page, token)
        if register:
            page.get_by_label('个人账号', exact=True).fill('synthetic-third-person')
            page.get_by_label('个人密码', exact=True).fill(PASSWORD)
            self.command(page, '创建个人账户', '/api/account/register', status=201)
            self.finish(page)
            self.ready(page, 'invitation')
            expect(page.get_by_test_id('membership-join-preview')).to_have_count(0)
            assert not self.get(ctx, '/api/account/households')['memberships']
            self.inspect(page, token)
        result, _ = self.command(page, '加入这个家庭', '/api/account/invitations/accept')
        assert result['state'] == 'active' and result['householdRole'] == 'member'
        assert self.get(ctx, '/api/me')['user'] is None, 'Join must not switch silently'
        self.finish(page)
        self.ready(page, 'account')
        return result

    def switch(self, ctx, page, household):
        result, _ = self.command(page, '进入家庭：' + household['name'], '/api/account/switch-household')
        self.finish(page)
        user = self.get(ctx, '/api/me')['user']
        assert user['id'] == result['memberId'] and user['householdId'] == result['householdId']
        assert user['accountId'] == self.get(ctx, '/api/account/me')['account']['id']
        return user

    def finance_rows(self, database=None):
        with closing(sqlite3.connect(database or self.database)) as con:
            return con.execute('SELECT id,owner,data FROM hub_transactions ORDER BY id').fetchall()

    def private_titles(self, ctx):
        return json.dumps(self.get(ctx, '/api/finance-hub/transactions?month=2026-08'), ensure_ascii=False)

    def legacy_binding(self, browser):
        with self.flow(browser) as (ctx, page):
            self.stage('persist private data under the existing member1 owner')
            self.seed(ctx, [row('合成旧身份私人资料')])
            before = self.finance_rows()
            with closing(sqlite3.connect(self.database)) as con:
                users = con.execute('SELECT id,name,password,auth_version,household_role FROM users ORDER BY id').fetchall()
            self.stage('register by proving the old member, then explicitly bind')
            account = self.register_old(ctx, page, 'synthetic-old-owner')
            membership = self.bind(ctx, page)
            assert membership['memberId'] == 'member1' and membership['householdRole'] == 'admin'
            assert membership['id'] != account['id']
            assert self.finance_rows() == before and all(r[1] == 'member1' for r in before)
            with closing(sqlite3.connect(self.database)) as con:
                assert con.execute('SELECT id,name,password,auth_version,household_role FROM users ORDER BY id').fetchall() == users
                assert con.execute('SELECT account_id FROM household_memberships WHERE member_id=?', ('member1',)).fetchone()[0] == account['id']
            assert '合成旧身份私人资料' in self.private_titles(ctx)
            partner = self.context(browser, 2)
            try:
                assert '合成旧身份私人资料' not in self.private_titles(partner)
            finally:
                partner.close()
            self.passed('Old-member proof, personal registration and explicit UI binding retain private owner IDs and data; partner sees none')

    def invitation_lifecycle(self, browser):
        with self.flow(browser) as (admin, page), ExitStack() as extras:
            self.stage('admin creates one-time invite, third person registers and explicitly joins')
            token, invitation_id = self.invite(admin, page)
            guest = self.context(browser, None); extras.callback(guest.close)
            guest_page = guest.new_page()
            member = self.join(guest, guest_page, token, register=True)
            assert re.fullmatch('m_[a-f0-9]{24}', member['memberId'])
            home = self.get(guest, '/api/account/households')['memberships'][0]
            self.switch(guest, guest_page, home)
            self.seed(guest, [row('合成第三人成员私人资料')])
            saved = self.finance_rows()
            assert any(r[1] == member['memberId'] for r in saved)
            assert '合成第三人成员私人资料' not in self.private_titles(admin)
            assert next(i for i in self.get(admin, '/api/member-invitations')['invitations'] if i['id'] == invitation_id)['state'] == 'used'
            self.stage('admin removes the member; old derived session is rejected and data stays')
            self.open_panel(page, 'management')
            removed, _ = self.command(page, '移除成员：' + member['memberName'], '/api/memberships/' + member['memberId'] + '/remove', confirm='确认移除成员')
            self.finish(page)
            assert removed['state'] == 'removed'
            self.get(guest, '/api/state', 401)
            assert self.get(guest, '/api/account/me')['account'] is not None
            assert not self.get(guest, '/api/account/households')['memberships']
            assert self.finance_rows() == saved
            self.stage('fresh invite rejoins the same owner, then self-leave invalidates the new cookie')
            token2, _ = self.invite(admin, page)
            again = self.join(guest, guest_page, token2)
            assert again['memberId'] == member['memberId'] and again['id'] == member['id']
            assert again['householdRole'] == 'member' and again['revision'] > member['revision']
            self.switch(guest, guest_page, self.get(guest, '/api/account/households')['memberships'][0])
            assert '合成第三人成员私人资料' in self.private_titles(guest)
            self.open_panel(guest_page, 'management')
            left, body = self.command(guest_page, '退出这个家庭', '/api/memberships/self/leave', confirm='确认退出家庭')
            self.finish(guest_page)
            assert left['state'] == 'left'
            self.get(guest, '/api/state', 401)
            receipt = self.get(guest, '/api/account/operations/' + body['requestId'])
            assert receipt['state'] == 'completed' and receipt['result'] == left
            assert not self.get(guest, '/api/account/households')['memberships'] and self.finance_rows() == saved
            self.passed('One-time invite UI registration/join/switch; admin removal, rejoin with stable private owner, and self-leave revoke derived access')

    def two_households_logout(self, browser):
        with self.flow(browser) as (ctx, page), ExitStack() as extras:
            self.stage('bind one personal account to two distinct member1 identities')
            self.seed(ctx, [row('合成甲户专属资料')])
            self.register_old(ctx, page, 'synthetic-two-homes')
            first = self.bind(ctx, page)
            invite = self.write(ctx, 'POST', '/api/spaces/invitations', {}, 201)['invitation']
            second = self.write(ctx, 'POST', '/api/spaces/redeem', dict(invitation=invite,
                name='合成第二家庭：同名成员资料各自保管', slug='membership-other',
                MEMBER1_PASSWORD='testing-password-one', MEMBER2_PASSWORD='testing-password-two'), 201)
            page.goto(self.base + second['entry'])
            self.login(ctx)
            self.seed(ctx, [row('合成乙户专属资料')])
            self.open_panel(page, 'account')
            bound = self.bind(ctx, page)
            homes = self.get(ctx, '/api/account/households')['memberships']
            assert len(homes) == 2 and all(h['memberId'] == 'member1' for h in homes)
            assert first['id'] != bound['id'] and first['householdId'] != bound['householdId']
            a = next(h for h in homes if h['householdId'] == first['householdId'])
            b = next(h for h in homes if h['householdId'] == bound['householdId'])
            self.stage('switch between homes through UI; stale derived cookie cannot follow a newer generation')
            self.switch(ctx, page, b)
            assert '合成乙户专属资料' in self.private_titles(ctx) and '合成甲户专属资料' not in self.private_titles(ctx)
            stale = self.context(browser, None); extras.callback(stale.close)
            stale.add_cookies(ctx.cookies())
            self.open_panel(page, 'account')
            self.switch(ctx, page, a)
            self.get(stale, '/api/state', 401)
            assert '合成甲户专属资料' in self.private_titles(ctx) and '合成乙户专属资料' not in self.private_titles(ctx)
            self.stage('personal logout revokes current derived household login')
            self.open_panel(page, 'account')
            self.command(page, '退出个人账户', '/api/account/logout')
            self.finish(page)
            assert self.get(ctx, '/api/account/me')['account'] is None
            self.get(ctx, '/api/state', 401)
            assert len(self.finance_rows()) == 1
            other_db = self.folder / 'data' / 'spaces' / bound['householdId'] / 'household.sqlite3'
            assert len(self.finance_rows(other_db)) == 1
            self.passed('Same-named member1 owners remain household-local; explicit switches fence older derived generations and personal logout revokes current access')

    def lost_invitation_layout(self, browser):
        with self.flow(browser) as (ctx, page):
            self.stage('drop one actual committed invitation response and preserve original operation ID')
            self.open_panel(page, 'invitation')
            captured = []
            url = self.base + '/api/member-invitations'
            def drop(route):
                if route.request.method != 'POST':
                    route.continue_(); return
                response = route.fetch(max_redirects=0)
                assert response.status == 200
                captured.append((route.request.post_data_json, response.json()))
                route.abort('failed')
            page.route(url, drop)
            try:
                button(page, '创建邀请码').click()
                button(page, '确认继续').click()
                self.settle(page, lambda: len(captured) == 1)
                expect(button(page, '查询原操作')).to_be_enabled(timeout=20000)
            finally:
                page.unroute(url, drop)
            payload, committed = captured[0]
            request_id, token = payload['requestId'], committed['token']
            operation = '/api/membership-operations/' + request_id
            expect(page.get_by_test_id('membership-operation')).to_contain_text(request_id)
            expect(button(page, '返回')).to_be_disabled()
            assert self.count_requests('POST', '/api/member-invitations') == 1
            assert self.count_requests('GET', operation) == 0
            assert len(self.get(ctx, '/api/member-invitations')['invitations']) == 1
            self.stage('explicit GET restores receipt only, replay never rediscloses the raw invitation')
            receipt, _ = self.actual(page, 'GET', operation, lambda: button(page, '查询原操作').click())
            assert receipt['state'] == 'completed' and 'token' not in receipt['result']
            expect(button(page, '读取当前状态')).to_be_enabled()
            self.finish(page)
            expect(page.get_by_test_id('membership-invitation-secret')).to_have_count(0)
            expect(page.locator('body')).not_to_contain_text(token)
            assert self.count_requests('POST', '/api/member-invitations') == 1
            replay = self.write(ctx, 'POST', '/api/member-invitations', payload)
            assert 'token' not in replay and replay['invitation']['id'] == committed['invitation']['id']
            assert len(self.get(ctx, '/api/member-invitations')['invitations']) == 1
            self.stage('clear a newly displayed secret on hidden and exercise keyboard/three-width layouts')
            # Explicitly revoke the inaccessible invite before creating another.
            old_id = committed['invitation']['id']
            self.command(page, '撤销邀请：' + old_id[-6:], '/api/member-invitations/' + old_id + '/revoke')
            self.finish(page)
            created, _ = self.command(page, '创建邀请码', '/api/member-invitations')
            self.finish(page)
            expect(page.get_by_test_id('membership-invitation-secret')).to_contain_text(created['token'])
            visibility(page, True)
            expect(page.get_by_test_id('membership-invitation-secret')).to_have_count(0)
            visibility(page, False)
            self.ready(page, 'invitation')
            expect(page.locator('body')).not_to_contain_text(created['token'])
            storage = page.evaluate('({local:{...localStorage},session:{...sessionStorage}})')
            assert token not in json.dumps(storage) and created['token'] not in json.dumps(storage)
            for mode in ('light', 'dark'):
                preferences = self.get(ctx, '/api/preferences')
                self.write(ctx, 'PUT', '/api/preferences', {'revision': preferences['revision'], 'changes': {'colorMode': mode}})
                self.open_panel(page, 'invitation')
                page.wait_for_function("getComputedStyle(document.documentElement).colorScheme === '" + mode + "'")
                history = button(page, '按编号查询原操作')
                history.focus(); history.press('Enter')
                expect(page.get_by_label('原操作编号', exact=True)).to_be_visible()
                for width in (320, 390, 1280):
                    self.capture(page, mode, width, history)
            self.passed('Lost actual write reply stays locked until explicit original-ID GET; invitation replay hides token, background clears secrets, keyboard and six visible layouts')

    def capture(self, page, mode, width, target):
        page.set_viewport_size({'width': width, 'height': 900 if width >= 1280 else 844})
        target.scroll_into_view_if_needed()
        page.evaluate('() => document.fonts.ready')
        page.evaluate('() => new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
        metrics = page.evaluate('''() => ({width:innerWidth,scroll:document.documentElement.scrollWidth,
          clipped:[...document.querySelectorAll('[data-testid="membership-invitations-panel"] input,[data-testid="membership-invitations-panel"] [role="button"]')]
          .filter(n=>{const b=n.getBoundingClientRect();return b.width>0&&b.height>0&&b.bottom>0&&b.top<innerHeight&&(b.left < -2||b.right>innerWidth+2)})
          .map(n=>({label:n.getAttribute('aria-label'),box:n.getBoundingClientRect().toJSON()}))})''')
        assert metrics['scroll'] <= width + 2 and not metrics['clipped'], metrics
        box = target.bounding_box()
        assert box and box['height'] >= 44 and box['width'] >= 44, box
        path = self.out / f'memberships-{mode}-{width}.png'
        page.screenshot(path=str(path), full_page=False)
        self.report['screenshots'].append({'path': path.relative_to(self.out.parent).as_posix(), 'sha256': sha(path),
            'metrics': metrics, 'target': box, 'scope': 'Visible viewport only, after scrolling; no physical-device or whole-page claim.'})

    @classmethod
    def run_scenarios(cls, root, bundle, report, out, browser):
        for name in CASES:
            case_out = out / name; case_out.mkdir()
            folder = None
            before = tuple(len(report[k]) for k in ('checks', 'pageErrors', 'externalRequests'))
            case = dict(name=name, passed=False, temporaryFixtureRemoved=False)
            try:
                with ExitStack() as lifecycle:
                    folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='m-')))
                    run = cls(root, bundle, folder, report, case_out, lifecycle)
                    getattr(run, name)(browser)
                assert not folder.exists()
                assert tuple(len(report[k]) for k in ('checks', 'pageErrors', 'externalRequests')) == (before[0] + 1, before[1], before[2])
                case['passed'] = True
            except Exception:
                del report['checks'][before[0]:]
                failure = traceback.format_exc()
                (case_out / 'failure.txt').write_text(failure, encoding='utf-8')
                report['scenarioFailures'].append(dict(scenario=name, traceback=failure))
                print('FAIL ' + name + '\n' + failure, flush=True)
            finally:
                case['temporaryFixtureRemoved'] = folder is not None and not folder.exists()
                report['scenarioResults'].append(case)
        assert not report['scenarioFailures']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--build-evidence', required=True, type=Path)
    parser.add_argument('--expected-build-evidence', required=True)
    args = parser.parse_args()
    root, bundle = args.source_root.resolve(), args.bundle.resolve()
    author = Path(__file__).resolve().parents[1]
    assert sys.dont_write_bytecode and not sys.flags.optimize
    assert re.fullmatch('[a-f0-9]{40}', args.expected_head) and re.fullmatch('[a-f0-9]{64}', args.expected_build_evidence)
    def git_at(where, *command):
        return subprocess.check_output(['git', '--no-replace-objects', *command], cwd=where, text=True).strip()
    def git(*command):
        return git_at(root, *command)
    head, author_head = git('rev-parse', 'HEAD'), git_at(author, 'rev-parse', 'HEAD')
    assert head == args.expected_head and not git('status', '--porcelain=v1')
    assert not git_at(author, 'status', '--porcelain=v1')
    harness_bytes = subprocess.check_output(['git', '--no-replace-objects', 'show', author_head + ':tests/browser_expo_memberships_check.py'], cwd=author)
    assert hashlib.sha256(harness_bytes).hexdigest() == sha(Path(__file__))
    evidence_path = args.build_evidence.resolve()
    assert sha(evidence_path) == args.expected_build_evidence
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    assert evidence['head'] == head and evidence['tree'] == git('rev-parse', 'HEAD^{tree}')
    assert evidence['buildExit'] == 0 and evidence['bundleMarkers'] is True
    names = subprocess.check_output(['git', '--no-replace-objects', 'ls-files', '-z'], cwd=root).decode('utf-8').rstrip('\0').split('\0')
    def hashes():
        return {name: sha(root / name) for name in names}
    def exports():
        return file_manifest(bundle)
    assert exports() == evidence['files']
    out = author / 'test-results' / ('expo-memberships-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], stages=[], pageErrors=[], externalRequests=[], screenshots=[], scenarioResults=[], scenarioFailures=[],
        head=head, tree=git('rev-parse', 'HEAD^{tree}'), buildEvidencePath=str(evidence_path), buildEvidenceSha256=sha(evidence_path),
        harnessHead=author_head, harnessSha256=sha(out / 'executed-harness.py'), sourceRoot=str(root), bundleRoot=str(bundle),
        sourceHashesBefore=hashes(), bundleHashesBefore=exports(), productionWrites=0, realFinancialData=False, realCloud=False,
        physicalDevice=False, scope='Four independent temporary Flask/SQLite/HTTPS/Edge membership chains; UI writes, synthetic accounts and private records only.')
    original_connect = socket.socket.connect
    def local_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
            report['externalRequests'].append({'kind': 'non-loopback socket'})
            raise AssertionError('External network forbidden')
        return original_connect(sock, address)
    try:
        with patch.object(socket.socket, 'connect', local_connect), sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            try:
                Run.run_scenarios(root, bundle, report, out, browser)
                assert len(report['checks']) == len(CASES) and len(report['screenshots']) == 6
                assert not report['pageErrors'] and not report['externalRequests']
                report['passed'] = True
            finally:
                browser.close()
    except Exception:
        report['passed'] = False
        report['failure'] = traceback.format_exc()
        print(report['failure'], flush=True)
    finally:
        report['sourceHashesAfter'], report['bundleHashesAfter'] = hashes(), exports()
        report['sourceUnchanged'] = report['sourceHashesBefore'] == report['sourceHashesAfter']
        report['bundleUnchanged'] = report['bundleHashesBefore'] == report['bundleHashesAfter']
        report['fixtureHashesAfter'] = {name: sha(Path(path)) for name, path in report.get('fixtureActualPaths', {}).items()}
        report['fixturesUnchanged'] = bool(report.get('fixtureHashes')) and report['fixtureHashesAfter'] == report['fixtureHashes']
        report['sourceStillFrozen'] = git('rev-parse', 'HEAD') == head and not git('status', '--porcelain=v1')
        report['harnessStillFrozen'] = git_at(author, 'rev-parse', 'HEAD') == author_head and not git_at(author, 'status', '--porcelain=v1') and sha(Path(__file__)) == report['harnessSha256']
        report['temporaryFixtureRemoved'] = len(report['scenarioResults']) == len(CASES) and all(c['temporaryFixtureRemoved'] for c in report['scenarioResults'])
        report['passed'] = report['passed'] and report['sourceUnchanged'] and report['bundleUnchanged'] and report['fixturesUnchanged'] and report['sourceStillFrozen'] and report['harnessStillFrozen'] and report['temporaryFixtureRemoved']
        with (out / 'result.json').open('x', encoding='utf-8') as target:
            target.write(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(dict(passed=report['passed'], checks=len(report['checks']), report=str(out / 'result.json')), ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    raise SystemExit(main())
