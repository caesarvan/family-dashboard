"""Real Edge membership regressions and cold account recovery, synthetic only."""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import traceback
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
import browser_expo_memberships_check as original
from browser_expo_memberships_check import button, row, sha, file_manifest, PASSWORD

AUTHOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AUTHOR))
from deploy.git_blobs import read_git_blobs

RECOVERY = ('invalid_route_recovery', 'missing_default_cold_recovery')
CASES = (*original.CASES, *RECOVERY)


class Run(original.Run):
    def __init__(self, *args):
        super().__init__(*args)
        name = 'tests/browser_expo_memberships_check.py'
        path = Path(original.__file__).resolve()
        assert sha(path) == sha(self.root / name)
        inherited = {'path': str(path), 'sha256': sha(path), 'sourcePath': name}
        assert self.report.setdefault('inheritedFixture', inherited) == inherited

    def account_write(self, ctx, path, body, *, member=False, status=200):
        account = self.get(ctx, '/api/account/me')
        headers = {'Origin': self.base}
        if path.startswith('/api/account/'):
            headers['X-CSRF-Token'] = account['csrf']
            if member:
                headers['X-Member-CSRF-Token'] = self.get(ctx, '/api/me')['csrf']
        else:
            assert member
            headers['X-CSRF-Token'] = self.get(ctx, '/api/me')['csrf']
            headers['X-Account-CSRF-Token'] = account['csrf']
        response = ctx.request.post(self.base + path, data=body, headers=headers)
        assert response.status == status, (path, response.status, response.text())
        return response.json()

    def recovery_setup(self, browser):
        ctx = self.context(browser)
        try:
            self.seed(ctx, [row('合成不可用原家庭的私人资料')])
            proof = self.account_write(ctx, '/api/account/eligibility',
                {'memberPassword': 'testing-password-one'}, member=True)
            account = self.account_write(ctx, '/api/account/register',
                {'requestId': secrets.token_hex(16), 'login': 'recovery.account', 'password': PASSWORD,
                 'eligibilityToken': proof['eligibilityToken']}, member=True, status=201)['account']
            def bind():
                user = self.get(ctx, '/api/me')['user']
                return self.account_write(ctx, '/api/membership-links',
                    {'requestId': secrets.token_hex(16), 'memberPassword': 'testing-password-one',
                     'expectedAuthVersion': user['auth_version'], 'expectedRevision': user['membershipRevision']}, member=True)
            first = bind()
            invitation = self.write(ctx, 'POST', '/api/spaces/invitations', {}, 201)['invitation']
            created = self.write(ctx, 'POST', '/api/spaces/redeem',
                {'invitation': invitation, 'name': '合成可恢复家庭', 'slug': 'recovery-target',
                 'MEMBER1_PASSWORD': 'testing-password-one', 'MEMBER2_PASSWORD': 'testing-password-two'}, 201)
            assert ctx.request.get(self.base + created['entry']).status == 200
            self.login(ctx)
            self.seed(ctx, [row('合成可用家庭的独立私人资料')])
            second = bind()
            directory = self.get(ctx, '/api/account/households')['memberships']
            assert len(directory) == 2 and first['householdId'] != second['householdId']
            target = next(h for h in directory if h['id'] == second['id'])
            self.account_write(ctx, '/api/account/logout', {'requestId': secrets.token_hex(16)})
            assert self.get(ctx, '/api/account/me')['account'] is None
            return account, target
        finally:
            ctx.close()

    def recover(self, browser, *, missing):
        self.stage('create two real households and explicitly bind the same personal account using setup APIs')
        account, target = self.recovery_setup(browser)
        original_rows = self.finance_rows()
        self.stage('close all fixture HTTP service state and cold-start with the selected actual fault')
        port = self.server.server_port
        self.stop()
        unavailable = self.database.with_suffix('.unavailable')
        if missing:
            assert self.database.resolve().is_relative_to(self.folder.resolve())
            assert not unavailable.exists()
            self.database.rename(unavailable)
            unavailable_sha = sha(unavailable)
        self.start(port)
        ctx = self.context(browser, None)
        page = ctx.new_page()
        self.page = page
        try:
            if not missing:
                ctx.add_cookies([{'name': 'household_space', 'value': 'invalid-signed-route',
                    'url': self.base, 'httpOnly': True, 'secure': True, 'sameSite': 'Lax'}])
            self.get(ctx, '/api/me', 503 if missing else 400)
            assert self.get(ctx, '/api/account/me')['account'] is None
            if missing:
                assert not self.database.exists()
            self.stage('open real /app shell and explicitly sign in from My family account')
            response = page.goto(self.base + '/app')
            assert response and response.status == 200
            expect(button(page, '我的家庭账户')).to_be_enabled(timeout=20000)
            button(page, '我的家庭账户').click()
            self.ready(page, 'account')
            expect(page.get_by_test_id('membership-household-unavailable')).to_be_visible()
            expect(page.locator('body')).not_to_contain_text('合成不可用原家庭的私人资料')
            page.get_by_label('个人账号', exact=True).fill('recovery.account')
            page.get_by_label('个人密码', exact=True).fill(PASSWORD)
            login, _ = self.actual(page, 'POST', '/api/account/login', lambda: button(page, '登录个人账户').click())
            assert login['account']['id'] == account['id']
            target_button = button(page, '进入家庭：' + target['name'])
            expect(target_button).to_be_enabled(timeout=20000)
            homes = self.get(ctx, '/api/account/households')
            assert any(h['id'] == target['id'] for h in homes['memberships'])
            if missing:
                assert homes['unavailable'] == [{'householdId': 'default', 'code': 'temporarily_unavailable'}]
                assert not self.database.exists()
            target_button.scroll_into_view_if_needed()
            screenshot = self.out / 'recovery-target.png'
            page.screenshot(path=str(screenshot), full_page=False)
            self.report['screenshots'].append({'path': screenshot.relative_to(self.out.parent).as_posix(),
                'sha256': sha(screenshot), 'scope': 'Visible recovery account/target viewport only.'})
            self.stage('explicitly switch through the UI and verify target identity and private-data isolation')
            user = self.switch(ctx, page, target)
            assert user['householdId'] == target['householdId'] and user['accountId'] == account['id']
            assert self.get(ctx, '/api/state')['people']
            titles = self.private_titles(ctx)
            assert '合成可用家庭的独立私人资料' in titles and '合成不可用原家庭的私人资料' not in titles
            assert self.count_requests('POST', '/api/account/login') == 1
            assert self.count_requests('POST', '/api/account/switch-household') == 1
            if missing:
                assert not self.database.exists() and sha(unavailable) == unavailable_sha
                assert self.finance_rows(unavailable) == original_rows
            else:
                assert self.finance_rows() == original_rows
            self.passed(('Missing default DB cold start' if missing else 'Invalid signed route cold start') +
                ': real /app shell, explicit personal login and target switch, no old private data or missing-DB recreation')
        except Exception:
            try:
                page.screenshot(path=str(self.out / 'failure.png'), full_page=True)
                (self.out / 'failure-aria.txt').write_text(page.locator('body').aria_snapshot(), encoding='utf-8')
            except Exception:
                pass
            raise
        finally:
            ctx.close()

    def invalid_route_recovery(self, browser):
        self.recover(browser, missing=False)

    def missing_default_cold_recovery(self, browser):
        self.recover(browser, missing=True)


def run_case(name, root, bundle, report, out, browser):
    folder = None
    case_out = out / name
    case_out.mkdir()
    before = tuple(len(report[k]) for k in ('checks', 'pageErrors', 'externalRequests'))
    case = {'name': name, 'passed': False, 'temporaryFixtureRemoved': False}
    try:
        with ExitStack() as lifecycle:
            folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='m-')))
            run = Run(root, bundle, folder, report, case_out, lifecycle)
            getattr(run, name)(browser)
        assert not folder.exists()
        assert tuple(len(report[k]) for k in ('checks', 'pageErrors', 'externalRequests')) == (before[0] + 1, before[1], before[2])
        case['passed'] = True
    except Exception:
        del report['checks'][before[0]:]
        failure = traceback.format_exc()
        (case_out / 'failure.txt').write_text(failure, encoding='utf-8')
        report['scenarioFailures'].append({'scenario': name, 'traceback': failure})
        print('FAIL ' + name + '\n' + failure, flush=True)
    finally:
        case['temporaryFixtureRemoved'] = folder is not None and not folder.exists()
        report['scenarioResults'].append(case)
    return case['passed']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--build-evidence', required=True, type=Path)
    parser.add_argument('--expected-build-evidence', required=True)
    args = parser.parse_args()
    root, bundle, evidence_path = args.source_root.resolve(), args.bundle.resolve(), args.build_evidence.resolve()
    assert sys.dont_write_bytecode and not sys.flags.optimize
    assert re.fullmatch('[a-f0-9]{40}', args.expected_head) and re.fullmatch('[a-f0-9]{64}', args.expected_build_evidence)
    def git(where, *command):
        return subprocess.check_output(['git', '--no-replace-objects', '--no-optional-locks', *command], cwd=where, text=True).strip()
    head, author_head = git(root, 'rev-parse', 'HEAD'), git(AUTHOR, 'rev-parse', 'HEAD')
    assert head == args.expected_head and not git(root, 'status', '--porcelain=v1') and not git(AUTHOR, 'status', '--porcelain=v1')
    script_name = 'tests/browser_expo_membership_recovery_check.py'
    assert read_git_blobs(AUTHOR, author_head, [script_name])[script_name] == Path(__file__).read_bytes()
    assert sha(evidence_path) == args.expected_build_evidence
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    assert evidence['buildExit'] == 0 and evidence['bundleMarkers'] is True
    assert git(root, 'rev-parse', evidence['head'] + '^{tree}') == evidence['tree']
    subprocess.run(['git', '--no-replace-objects', 'merge-base', '--is-ancestor', evidence['head'], head], cwd=root, check=True)
    inputs = evidence['inputFiles']
    assert len(inputs) == 107 and len(evidence['files']) == 23
    for blobs in (read_git_blobs(root, evidence['head'], inputs), read_git_blobs(root, head, inputs)):
        assert {name: hashlib.sha256(content).hexdigest() for name, content in blobs.items()} == inputs
    assert {name: sha(root / name) for name in inputs} == inputs
    assert file_manifest(bundle) == evidence['files']
    names = subprocess.check_output(['git', '--no-replace-objects', 'ls-files', '-z'], cwd=root).decode('utf-8').rstrip('\0').split('\0')
    def hashes():
        return {name: sha(root / name) for name in names}
    out = AUTHOR / 'test-results' / ('expo-membership-recovery-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], stages=[], pageErrors=[], externalRequests=[], screenshots=[], scenarioResults=[], scenarioFailures=[],
        head=head, tree=git(root, 'rev-parse', 'HEAD^{tree}'), buildHead=evidence['head'], buildTree=evidence['tree'], buildInputs=inputs,
        buildInputsEqual=True, buildEvidencePath=str(evidence_path), buildEvidenceSha256=sha(evidence_path),
        harnessHead=author_head, harnessSha256=sha(out / 'executed-harness.py'), sourceRoot=str(root), bundleRoot=str(bundle),
        sourceHashesBefore=hashes(), bundleHashesBefore=file_manifest(bundle), productionWrites=0, realFinancialData=False, realCloud=False,
        physicalDevice=False, scope='Four existing unchanged real membership flows followed by two real cold recovery flows; all temporary synthetic Flask/SQLite/HTTPS/Edge.')
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
                for name in original.CASES:
                    run_case(name, root, bundle, report, out, browser)
                assert not report['scenarioFailures'], 'Recovery cases require all four original flows to pass'
                for name in RECOVERY:
                    run_case(name, root, bundle, report, out, browser)
                assert not report['scenarioFailures'] and len(report['checks']) == 6 and len(report['screenshots']) == 8
                assert not report['pageErrors'] and not report['externalRequests']
                report['passed'] = True
            finally:
                browser.close()
    except Exception:
        report['failure'] = traceback.format_exc()
        print(report['failure'], flush=True)
    finally:
        report['sourceHashesAfter'], report['bundleHashesAfter'] = hashes(), file_manifest(bundle)
        report['sourceUnchanged'] = report['sourceHashesBefore'] == report['sourceHashesAfter']
        report['bundleUnchanged'] = report['bundleHashesBefore'] == report['bundleHashesAfter']
        report['fixtureHashesAfter'] = {name: sha(Path(path)) for name, path in report.get('fixtureActualPaths', {}).items()}
        report['fixturesUnchanged'] = bool(report.get('fixtureHashes')) and report['fixtureHashesAfter'] == report['fixtureHashes']
        inherited = report.get('inheritedFixture')
        report['inheritedFixtureUnchanged'] = bool(inherited) and sha(Path(inherited['path'])) == inherited['sha256'] == sha(root / inherited['sourcePath'])
        report['sourceStillFrozen'] = git(root, 'rev-parse', 'HEAD') == head and not git(root, 'status', '--porcelain=v1')
        report['harnessStillFrozen'] = git(AUTHOR, 'rev-parse', 'HEAD') == author_head and not git(AUTHOR, 'status', '--porcelain=v1') and sha(Path(__file__)) == report['harnessSha256']
        report['temporaryFixtureRemoved'] = len(report['scenarioResults']) == 6 and all(c['temporaryFixtureRemoved'] for c in report['scenarioResults'])
        report['passed'] = report['passed'] and report['sourceUnchanged'] and report['bundleUnchanged'] and report['fixturesUnchanged'] and report['inheritedFixtureUnchanged'] and report['sourceStillFrozen'] and report['harnessStillFrozen'] and report['temporaryFixtureRemoved']
        with (out / 'result.json').open('x', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'report': str(out / 'result.json')}), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
