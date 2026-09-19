"""Real local Flask/SQLite/Expo finance queries with synthetic records only.

Run against a frozen integrated source and that source's exact Expo export.
No provider answers or business responses are fabricated. One authentic response
is delayed until another member logs in to exercise stale identity handling.
An explicitly named earlier build is reusable only with an identical frontend
tree; its original build identity remains in the result.
"""
import argparse
from contextlib import ExitStack, closing
from datetime import datetime, timedelta, timezone
import hashlib
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
from zoneinfo import ZoneInfo

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import ThreadedWSGIServer
import browser_expo_finance_check as fixture
from browser_expo_finance_check import Run as BaseRun, button, row, sha, visibility


HARNESS = 'tests/browser_expo_assistant_finance_query_check.py'
QUERY = '/api/assistant/finance-query'
CASES = ('budget_and_month_navigation', 'empty_clarify_and_search', 'identity_and_visibility')


class Run(BaseRun):
    def __init__(self, root, bundle, folder, report, out, lifecycle):
        # server_close must join active requests before Windows deletes SQLite.
        assert ThreadedWSGIServer.block_on_close is True
        lifecycle.enter_context(patch.object(ThreadedWSGIServer, 'daemon_threads', False))
        super().__init__(root, bundle, folder, report, out, lifecycle)
        assert self.server.daemon_threads is False and self.server.block_on_close is True
        self.report['requestThreadShutdown'] = {'daemonThreads': False, 'blockOnClose': True}
        assert Path(self.source.__file__).resolve() == (self.root / 'app.py').resolve()
        assert QUERY in {rule.rule for rule in self.application.url_map.iter_rules()}
        names = {HARNESS: str(Path(__file__).resolve()),
                 'tests/browser_expo_finance_check.py': str(Path(fixture.__file__).resolve())}
        for name in ('assistant_finance_query', 'finance_hub', 'home_assistant'):
            names[name + '.py'] = str(Path(sys.modules[name].__file__).resolve())
        digests = {name: sha(Path(path)) for name, path in names.items()}
        assert all(value == sha(self.root / name) for name, value in digests.items())
        assert digests[HARNESS] == self.report['harnessSha256']
        assert self.report.setdefault('fixtureActualPaths', names) == names
        assert self.report.setdefault('fixtureHashes', digests) == digests
        def forbidden_provider(*_args, **_kwargs):
            self.report['providerAttempts'].append(self.out.name)
            raise AssertionError('Model requests are forbidden in local browser acceptance')
        self.lifecycle.enter_context(patch.object(sys.modules['home_assistant'], '_model_json', forbidden_provider))
        today = datetime.now(ZoneInfo('Asia/Shanghai')).date()
        self.month = today.strftime('%Y-%m')
        self.previous = (today.replace(day=1) - timedelta(days=1)).strftime('%Y-%m')
        self.exchange_number = 0

    def clear_finance(self):
        pass  # Each scenario owns a new temporary database.

    def protected(self):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database)) as con:
            excluded = {'users', 'member_sessions', 'member_session_browsers', 'attempts'}
            tables = [(name, sql) for name, sql in con.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name")
                      if name not in excluded]
            assert self.report.setdefault('protectedTables', [name for name, _ in tables]) == [name for name, _ in tables]
            assert self.report.setdefault('authenticationTablesExcluded', sorted(excluded)) == sorted(excluded)
            return {name: hashlib.sha256(repr((sql, sorted(con.execute('SELECT * FROM "' + name.replace('"', '""') + '"').fetchall(), key=repr))).encode()).hexdigest()
                    for name, sql in tables}

    def open_assistant(self, page):
        page.goto(self.base + '/app/assistant')
        expect(page.get_by_role('textbox', name='告诉助理你的需求', exact=True)).to_be_enabled(timeout=15000)

    def actual_post(self, page, path, action, after_response=None):
        self.exchange_number += 1
        calls, url = [], self.base + path
        saved = self.out / ('exchange-%02d.json' % self.exchange_number)

        def intercept(route):
            assert route.request.method == 'POST'
            response = route.fetch(max_redirects=0)
            raw = response.body()
            saved.write_bytes(raw)
            call = dict(payload=route.request.post_data_json, status=response.status,
                        result=json.loads(raw), responseSha256=sha(saved))
            if after_response:
                assert 'set-cookie' not in response.headers
                after_response()
            route.fulfill(status=response.status, headers=response.headers, body=raw)
            calls.append(call)  # Terminal action precedes completion/unroute.

        page.route(url, intercept)
        try:
            action()
            self.settle(page, lambda: bool(calls))
            assert len(calls) == 1 and calls[0]['status'] == 200, calls
            return calls[0]['result']
        finally:
            page.unroute(url, intercept)

    def initial(self, page, prompt, **kwargs):
        page.get_by_role('textbox', name='告诉助理你的需求', exact=True).fill(prompt)
        return self.actual_post(page, QUERY, lambda: button(page, '查询').click(), **kwargs)

    def query(self, page, prompt):
        page.get_by_role('textbox', name='财务问题', exact=True).fill(prompt)
        return self.actual_post(page, QUERY, lambda: button(page, '查询').click())

    def seed_month(self, ctx, month, prefix='合成'):
        self.seed(ctx, [row(prefix + '支出', '100.00', day=month + '-02', category='餐饮'),
                        row(prefix + '退款', '20.00', day=month + '-03', flow='refund', category='餐饮'),
                        row(prefix + '美元支出', '5.00', day=month + '-04', currency='USD')])
        self.write(ctx, 'PUT', '/api/finance-hub/budgets', dict(month=month, currency='CNY', category='全部', amount='200.00', revision=0))

    def visible_shot(self, page, width):
        page.set_viewport_size({'width': width, 'height': 1000 if width >= 1040 else 844})
        panel = page.get_by_test_id('assistant-finance-query-result')
        expect(panel).to_be_visible()
        panel.scroll_into_view_if_needed()
        page.evaluate('() => document.fonts.ready')
        page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
        metrics = page.evaluate('''() => ({width:innerWidth,scroll:document.documentElement.scrollWidth,
          clipped:[...document.querySelectorAll('[data-testid="assistant-finance-query-panel"] [role="button"], [data-testid="assistant-finance-query-panel"] textarea')]
          .filter(n=>{const r=n.getBoundingClientRect();return r.width>0&&r.height>0&&r.bottom>0&&r.top<innerHeight&&(r.left< -2||r.right>innerWidth+2)})
          .map(n=>({label:n.getAttribute('aria-label')||n.textContent,box:n.getBoundingClientRect().toJSON()}))})''')
        assert metrics['scroll'] <= width + 2 and not metrics['clipped'], metrics
        path = self.out / ('finance-query-%s.png' % width)
        page.screenshot(path=str(path), full_page=False)
        self.report['screenshots'].append(dict(path=path.relative_to(self.out.parent).as_posix(), sha256=sha(path), width=width,
            metrics=metrics, scope='Settled visible viewport only; not full internal scroll coverage or physical television.'))

    def budget_and_month_navigation(self, browser):
        with self.flow(browser) as (ctx, page):
            self.seed_month(ctx, self.month)
            self.seed_month(ctx, self.previous, '合成上月')
            before = self.protected()
            self.open_assistant(page)
            result = self.initial(page, '本月预算还剩多少')
            assert result['status'] == 'ready' and result['query']['month'] == self.month
            assert {v['currency']: v['netSpendCents'] for v in result['totals']} == {'CNY': 8000, 'USD': 500}
            assert result['budgets'][0]['remainingCents'] == 12000
            expect(page.get_by_test_id('assistant-finance-query-result')).to_contain_text('CNY')
            expect(page.get_by_test_id('assistant-finance-query-result')).to_contain_text('USD')
            for width in (390, 1280):
                self.visible_shot(page, width)
            result = self.query(page, '上月预算还剩多少')
            assert result['query']['month'] == self.previous
            assert result['navigation'] == dict(screen='finance', tab='budgets', month=self.previous)
            button(page, '查看月预算').click()
            expect(page.get_by_text(self.previous + ' 本人月预算', exact=True)).to_be_visible(timeout=15000)
            expect(page.get_by_test_id('finance-budget-CNY-全部')).to_contain_text('120.00')
            button(page, '返回查询').click()
            expect(page.get_by_role('textbox', name='财务问题', exact=True)).to_have_value('上月预算还剩多少')
            expect(page.get_by_test_id('assistant-finance-query-result')).to_be_visible(timeout=15000)
            result = self.query(page, '上月花了多少钱')
            assert result['navigation'] == dict(screen='finance', tab='ledger', month=self.previous)
            button(page, '查看本人账本').click()
            expect(page.get_by_role('textbox', name='账本月份', exact=True)).to_have_value(self.previous, timeout=15000)
            expect(button(page, '查看交易合成上月支出')).to_be_visible()
            button(page, '返回查询').click()
            expect(page.get_by_role('textbox', name='财务问题', exact=True)).to_have_value('上月花了多少钱')
            assert self.protected() == before
            assert self.count_requests('POST', '/api/assistant/plan') == 0
            self.passed('Real current/previous-month CNY and USD summaries and budgets; correct finance tab/month and query return; no domain writes')

    def empty_clarify_and_search(self, browser):
        with self.flow(browser) as (ctx, page):
            before = self.protected()
            self.open_assistant(page)
            result = self.initial(page, '本月花了多少钱')
            assert result['status'] == 'ready' and result['coverage']['status'] == 'no_records'
            assert result['totals'] == [] and result['budgets'] == []
            expect(page.get_by_test_id('assistant-finance-query-result')).to_be_visible()
            result = self.query(page, '八月支出多少')
            assert result['status'] == 'clarify' and not result['totals'] and not result['budgets']
            expect(page.get_by_test_id('assistant-finance-query-clarification')).to_be_visible()
            result = self.query(page, '查本月支出并把预算改成100元')
            assert result['status'] in ('clarify', 'unsupported') and not result['totals'] and not result['budgets']
            result = self.query(page, '伴侣本月花了多少钱')
            assert result['status'] == 'unsupported' and not result['totals'] and not result['budgets']
            assert self.protected() == before
            button(page, '返回助理').click()
            original = page.get_by_role('textbox', name='告诉助理你的需求', exact=True)
            expect(original).to_be_enabled(timeout=15000)
            original.fill('搜索 本月预算')
            query_count = self.count_requests('POST', QUERY)
            found = self.actual_post(page, '/api/assistant/plan', lambda: button(page, '整理并预览').click())
            assert found['mode'] == 'local' and self.count_requests('POST', QUERY) == query_count
            assert self.protected() == before
            self.passed('No records remain distinct from zero; missing year and mixed writes clarify; partner privacy denied; explicit search keeps its original route')

    def identity_and_visibility(self, browser):
        with self.flow(browser) as (ctx, page):
            self.seed_month(ctx, self.month)
            before = self.protected()
            self.open_assistant(page)
            assert self.initial(page, '本月预算还剩多少')['status'] == 'ready'
            expect(page.get_by_test_id('assistant-finance-query-result')).to_be_visible()
            visibility(page, True)
            expect(page.get_by_test_id('assistant-finance-query-result')).not_to_be_visible()
            visibility(page, False)
            expect(page.get_by_test_id('assistant-finance-query-result')).to_be_visible(timeout=15000)
            prompt = page.get_by_role('textbox', name='财务问题', exact=True)
            prompt.fill('本月花了多少钱')
            result = self.actual_post(page, QUERY, lambda: button(page, '查询').click(), after_response=lambda: self.login(ctx, 2))
            assert result['status'] == 'ready' and result['totals']  # Authentic old-member data.
            original = page.get_by_role('textbox', name='告诉助理你的需求', exact=True)
            expect(original).to_be_enabled(timeout=15000)
            expect(original).to_have_value('')
            expect(page.get_by_test_id('assistant-finance-query-result')).to_have_count(0)
            expect(page.get_by_role('textbox', name='财务问题', exact=True)).to_have_count(0)
            assert self.protected() == before
            self.passed('Background hides private summary; actual member replacement while a response is pending discards both prior results and prompt')

    @classmethod
    def run_scenarios(cls, root, bundle, report, out, browser):
        for name in CASES:
            case_out = out / name
            case_out.mkdir()
            folder = None
            before = len(report['checks'])
            case = dict(name=name, passed=False)
            try:
                with ExitStack() as lifecycle:
                    folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='expo-finance-query-')))
                    run = cls(root, bundle, folder, report, case_out, lifecycle)
                    getattr(run, name)(browser)
                assert len(report['checks']) == before + 1 and not folder.exists()
                case['passed'] = True
            except Exception:
                del report['checks'][before:]
                failure = traceback.format_exc()
                (case_out / 'failure.txt').write_text(failure, encoding='utf-8')
                report['scenarioFailures'].append(dict(scenario=name, traceback=failure))
                print('FAIL ' + name + '\n' + failure, flush=True)
            finally:
                case['temporaryFixtureRemoved'] = folder is not None and not folder.exists()
                report['scenarioResults'].append(case)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--build-source-head', help='Explicit earlier build commit; the complete frontend tree must be identical.')
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--expected-build-evidence', required=True)
    args = parser.parse_args()
    root, bundle = args.source_root.resolve(), args.bundle.resolve()
    assert sys.dont_write_bytecode and not sys.flags.optimize
    assert re.fullmatch('[a-f0-9]{40}', args.expected_head) and re.fullmatch('[a-f0-9]{64}', args.expected_build_evidence)
    def git(*command):
        return subprocess.check_output(['git', '--no-replace-objects', *command], cwd=root, text=True).strip()
    head, tree = git('rev-parse', 'HEAD'), git('rev-parse', 'HEAD^{tree}')
    assert head == args.expected_head and not git('status', '--porcelain=v1')
    evidence_path = bundle.parent / 'build-evidence.json'
    assert sha(evidence_path) == args.expected_build_evidence
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    build_head = args.build_source_head or head
    assert re.fullmatch('[a-f0-9]{40}', build_head)
    assert evidence['sourceHead'] == build_head and evidence['sourceTree'] == git('rev-parse', build_head + '^{tree}')
    if build_head != head:
        git('merge-base', '--is-ancestor', build_head, head)
        assert git('rev-parse', build_head + ':frontend') == git('rev-parse', head + ':frontend'), 'Reused build frontend differs'
    names = subprocess.check_output(['git', '--no-replace-objects', 'ls-files', '-z'], cwd=root).decode('utf-8').rstrip('\0').split('\0')
    def hashes():
        return {name: sha(root / name) for name in names}
    def exports():
        return {p.relative_to(bundle).as_posix(): sha(p) for p in bundle.rglob('*') if p.is_file()}
    assert exports() == evidence['files'] and all(sha(root / name) == value for name, value in evidence['inputFiles'].items())
    assert sha(Path(__file__)) == sha(root / HARNESS)
    out = root / 'test-results' / ('expo-finance-query-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], providerAttempts=[], screenshots=[], scenarioResults=[], scenarioFailures=[],
        requestedChecks=len(CASES), head=head, tree=tree, buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(out / 'executed-harness.py'),
        buildSourceHead=build_head, buildSourceTree=evidence['sourceTree'], reusedBuild=build_head != head,
        sourceRoot=str(root), bundleRoot=str(bundle), sourceHashesBefore=hashes(), bundleHashesBefore=exports(),
        productionWrites=0, realModel=False, realCloud=False, physicalTelevision=False,
        scope='Three independent temporary Flask/SQLite/HTTPS/Edge natural-language finance flows with real business responses and synthetic records.')
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
                assert len(report['checks']) == len(CASES) and len(report['screenshots']) == 2
                assert not report['scenarioFailures'] and not report['pageErrors'] and not report['externalRequests'] and not report['providerAttempts']
                report['passed'] = True
            finally:
                browser.close()
    except Exception:
        report['failure'] = traceback.format_exc()
        print(report['failure'], flush=True)
    finally:
        report['sourceHashesAfter'], report['bundleHashesAfter'] = hashes(), exports()
        report['sourceUnchanged'] = report['sourceHashesBefore'] == report['sourceHashesAfter']
        report['bundleUnchanged'] = report['bundleHashesBefore'] == report['bundleHashesAfter']
        report['fixtureHashesAfter'] = {name: sha(Path(path)) for name, path in report.get('fixtureActualPaths', {}).items()}
        report['fixturesUnchanged'] = bool(report.get('fixtureHashes')) and report['fixtureHashesAfter'] == report['fixtureHashes']
        report['sourceStillFrozen'] = git('rev-parse', 'HEAD') == head and git('rev-parse', 'HEAD^{tree}') == tree and not git('status', '--porcelain=v1')
        report['temporaryFixtureRemoved'] = len(report['scenarioResults']) == len(CASES) and all(c['temporaryFixtureRemoved'] for c in report['scenarioResults'])
        report['passed'] = report['passed'] and all(report[key] for key in ('sourceUnchanged', 'bundleUnchanged', 'fixturesUnchanged', 'sourceStillFrozen', 'temporaryFixtureRemoved'))
        (out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(dict(passed=report['passed'], checks=len(report['checks']), report=str(out / 'result.json')), ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
