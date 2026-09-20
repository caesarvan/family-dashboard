"""Three synthetic finance flow journeys through a frozen Expo build and real local APIs.

File selection, parsing, preview tokens, confirmation, receipts and budgets are real.
Fault injection only holds or drops an already received real response, or goes offline.
"""
import argparse
from contextlib import ExitStack, closing
from datetime import datetime, timezone
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

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from flask import request
from playwright.sync_api import expect, sync_playwright
import browser_expo_finance_check as fixture
import browser_finance_column_mapping_check as mapping_fixture
from browser_expo_finance_check import Run as BaseRun, button, csv_bytes, sha, visibility

HARNESS = 'tests/browser_finance_flow_mapping_check.py'
BASE = '/api/finance-hub/imports'
CASES = ('csv_flow_budget_dedup', 'xlsx_lost_confirm_receipt', 'identity_offline_late_preview')
HEADERS = ['记录时点', '记账数值', '内容说明', '记账单位', '交易方向']
ROWS = [[fixture.DAY, '10.50', '合成方向支出', 'CNY', '支出'],
        [fixture.DAY, '30.00', '合成方向收入', 'CNY', '收入']]
SUPPLEMENTS = {'tests/test_expo_journey_brief.mjs', 'tests/test_expo_trips.mjs',
    'tests/test_expo_assistant_journey_entry.mjs', 'tests/test_app.py',
    'tests/test_journey_workflows.py', 'tests/test_expo_photos.mjs',
    'tests/test_expo_journey_documents.mjs', 'tests/test_expo_calendar.mjs', 'deploy/git_blobs.py'}


def selected_cases(values):
    if values is None:
        return CASES
    if not values or any(value not in CASES for value in values):
        raise ValueError('Select at least one known finance flow case')
    return tuple(dict.fromkeys(values))


def exclusive_output(root):
    out = root / 'test-results' / ('finance-flow-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True, exist_ok=False)
    return out


def validate_build(git, root, head, evidence, names):
    assert evidence['sourceHead'] == head and evidence['sourceTree'] == git('rev-parse', head + '^{tree}')
    assert evidence['buildExit'] == 0 and evidence['executions']
    assert all(item['exitCode'] == 0 for item in evidence['executions'])
    assert evidence['dotenvDisabled'] is True and not evidence['ambientExpoPublicVariables']
    expected = {name for name in names if name.startswith('frontend/')} - {
        'frontend/.gitignore', 'frontend/LICENSE', 'frontend/README.md'}
    assert set(evidence['inputFiles']) == expected, 'Complete frontend inputs required'
    assert set(evidence['supplementalTestInputs']) == SUPPLEMENTS
    for values in (evidence['inputFiles'], evidence['supplementalTestInputs']):
        for name, digest in values.items():
            assert name in names and re.fullmatch('[a-f0-9]{64}', digest)
            assert sha(root / name) == digest, name


def exports(bundle):
    assert bundle.is_dir() and not bundle.is_symlink() and not bundle.is_junction()
    result = {}
    def failed(error):
        raise error
    for current, directories, files in os.walk(bundle, onerror=failed):
        for name in directories + files:
            path = Path(current) / name
            assert not path.is_symlink() and not path.is_junction()
        for name in files:
            path = Path(current) / name
            assert path.is_file()
            result[path.relative_to(bundle).as_posix()] = sha(path)
    return result


def write_json(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


class Run(BaseRun):
    # Reuse only existing real API/file-picker interactions, not the older main or
    # constructor that binds its own harness hash and six unrelated scenarios.
    headers = mapping_fixture.Run.headers
    select_columns = mapping_fixture.Run.select_columns
    mapped_preview = mapping_fixture.Run.mapped_preview
    save = mapping_fixture.Run.save

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        paths = {'app.py': self.source.__file__,
            'tests/browser_expo_finance_check.py': fixture.__file__,
            'tests/browser_finance_column_mapping_check.py': mapping_fixture.__file__,
            HARNESS: __file__, **{'tests/' + n + '.py': sys.modules[n].__file__
                                   for n in ('test_financial_files', 'test_app')}}
        for name, path in paths.items():
            assert Path(path).resolve() == (self.root / name).resolve(), name
        digests = {name: sha(Path(path)) for name, path in paths.items()}
        assert self.report.setdefault('fixtureHashes', digests) == digests
        self.http, self.journal_lock = [], threading.Lock()

        @self.application.after_request
        def journal(response):
            if request.path.startswith('/api/'):
                with self.journal_lock:
                    self.http.append({'index': len(self.http), 'method': request.method,
                        'path': request.path, 'status': response.status_code})
            return response

    def clear_finance(self):
        pass  # Each case owns a fresh temporary database; never clear another case.

    def proof(self, name, value):
        path = self.out / (name + '.json')
        write_json(path, value)
        self.report['artifacts'].append({'path': path.relative_to(self.out.parent).as_posix(), 'sha256': sha(path)})

    def actual(self, page, path, action, *, drop=False):
        result = mapping_fixture.Run.actual(self, page, path, action, drop=drop)
        self.proof('actual-' + str(len(self.report['artifacts'])), {'path': path,
            'dropDeliveryOnly': drop, **result})
        return result

    def records(self):
        with closing(sqlite3.connect(self.database)) as con:
            return con.execute('SELECT id,data,revision FROM hub_transactions ORDER BY id').fetchall()

    def receipt_counts(self):
        with closing(sqlite3.connect(self.database)) as con:
            return {**{table: con.execute('SELECT count(*) FROM ' + table).fetchone()[0]
                       for table in ('hub_transactions', 'hub_imports', 'hub_import_receipts')},
                'importAudits': con.execute("SELECT count(*) FROM audit WHERE action='finance.import'").fetchone()[0],
                'receiptAudits': con.execute("SELECT count(*) FROM audit WHERE action='finance.import.receipt'").fetchone()[0]}

    def start_import(self, page, raw=None, name='synthetic-flow.csv'):
        self.open_finance(page)
        self.open_import(page, csv_bytes(ROWS, HEADERS) if raw is None else raw, name=name)

    def choose_flow(self, page, columns, index=4):
        button(page, '收支方向（可选）').click()
        title = '自动识别' if index is None else next(
            c['columnLabel'] + ' 列 · ' + c['label'] for c in columns if c['index'] == index)
        page.get_by_role('menuitem', name=title, exact=True).click()
        expect(page.get_by_role('menuitem')).to_have_count(0)

    def mapping(self, page, index=4):
        columns = self.headers(page)['columns']
        self.select_columns(page, columns)
        self.choose_flow(page, columns, index)
        return columns

    def capture(self, page, name, width, target):
        page.set_viewport_size({'width': width, 'height': 1080 if width >= 1280 else 844})
        page.evaluate('() => document.fonts.ready')
        target.scroll_into_view_if_needed()
        page.wait_for_timeout(250)
        metrics = page.evaluate('''() => ({width:innerWidth,root:document.documentElement.scrollWidth,
          body:document.body.scrollWidth,clipped:[...document.querySelectorAll(
          '[data-testid="finance-column-mapping"] [role="button"],[data-testid="finance-column-mapping"] input')]
          .filter(n=>{const r=n.getBoundingClientRect();return r.width>0&&r.height>0&&r.bottom>0&&r.top<innerHeight
          &&(r.right>innerWidth+2||r.left< -2)}).map(n=>({label:n.getAttribute('aria-label')||n.textContent,
          box:n.getBoundingClientRect().toJSON()}))})''')
        assert metrics['root'] <= width + 2 and metrics['body'] <= width + 2 and not metrics['clipped'], metrics
        path = self.out / (name + '.png')
        page.screenshot(path=str(path), full_page=False)
        self.report['screenshots'].append({'path': path.relative_to(self.out.parent).as_posix(),
            'sha256': sha(path), 'metrics': metrics, 'scope': 'Visible settled viewport, not full-page vertical coverage'})

    def csv_flow_budget_dedup(self, browser):
        with self.flow(browser) as (ctx, page):
            self.start_import(page)
            columns = self.headers(page)['columns']
            self.select_columns(page, columns)
            automatic = self.mapped_preview(page)
            assert automatic['payload']['mapping']['flow'] is None
            assert [r['flow'] for r in automatic['result']['rows']] == ['unknown', 'unknown']
            assert not self.records()
            self.choose_flow(page, columns)
            expect(button(page, '确认导入 · 仅本人')).to_have_count(0)
            expect(page.get_by_role('heading', name='核对预览', exact=True)).to_have_count(0)
            expect(page.get_by_text('synthetic-flow.csv', exact=True)).to_be_visible()
            mapped = self.mapped_preview(page)
            assert mapped['payload']['mapping'] == {**mapping_fixture.MAPPING, 'version': 2, 'flow': 4}
            assert [r['flow'] for r in mapped['result']['rows']] == ['expense', 'income']
            assert all(r['visibility'] == 'private' for r in mapped['result']['rows'])
            assert not self.records()
            self.capture(page, 'direction-preview', 390, button(page, '确认导入 · 仅本人'))
            saved = self.save(page)
            assert saved['result']['imported'] == 2 and saved['result']['duplicates'] == 0
            original = self.records()
            assert len(original) == 2 and all(revision == 1 for _, _, revision in original)
            assert all(json.loads(raw)['provenance']['batchId'] == saved['result']['batchId'] for _, raw, _ in original)
            self.enter_receipt_ledger(page)
            self.ledger(page)
            self.make_budget(page, category='全部')
            overview = self.overview(ctx)
            total = self.total(overview)
            assert total['expenseCents'] == 1050 and total['incomeCents'] == 3000
            budget = next(b for b in overview['budgets'] if b['category'] == '全部' and b['currency'] == 'CNY')
            assert (budget['amountCents'], budget['spentCents'], budget['remainingCents']) == (10000, 1050, 8950)
            card = page.get_by_test_id('finance-budget-CNY-全部')
            expect(card).to_contain_text('10.50'); expect(card).to_contain_text('89.50')
            self.capture(page, 'actual-budget', 390, card)
            page.reload()
            self.start_import(page)
            columns = self.mapping(page)
            repeat = self.mapped_preview(page)['result']
            assert (repeat['newCount'], repeat['duplicateCount'], repeat['conflictCount']) == (0, 2, 0)
            unchanged = self.save(page)['result']
            assert (unchanged['imported'], unchanged['duplicates'], unchanged['conflicts']) == (0, 2, 0)
            assert self.records() == original
            page.reload(); self.start_import(page)
            columns = self.mapping(page)
            self.choose_flow(page, columns, None)
            expect(button(page, '确认导入 · 仅本人')).to_have_count(0)
            conflict = self.mapped_preview(page)['result']
            assert (conflict['newCount'], conflict['duplicateCount'], conflict['conflictCount']) == (0, 2, 2)
            again = self.save(page)['result']
            assert (again['imported'], again['duplicates'], again['conflicts']) == (0, 2, 2)
            assert self.records() == original and self.overview(ctx)['budgets'] == overview['budgets']
            self.proof('budget-original-records', {'original': original, 'after': self.records(), 'budget': budget})
            self.passed('CSV selected direction clears stale preview, private confirmation updates real budget, repeat/remap retains original records')

    def xlsx_lost_confirm_receipt(self, browser):
        with self.flow(browser) as (ctx, page):
            page.set_viewport_size({'width': 1280, 'height': 1080})
            self.start_import(page, self.workbook([HEADERS, *ROWS], second_sheet=True), 'synthetic-flow.xlsx')
            inspect = self.actual(page, BASE + '/preview', lambda: button(page, '预览文件').click())['result']
            assert inspect['requiresSheetSelection'] and inspect['previewToken'] is None
            button(page, '选择账单工作表').click()
            page.get_by_role('menuitem', name='支付账单', exact=True).click()
            self.mapping(page)
            preview = self.mapped_preview(page)['result']
            assert preview['fileInfo']['sheet'] == '支付账单'
            assert [r['flow'] for r in preview['rows']] == ['expense', 'income']
            actual = self.save(page, drop=True)
            assert actual['result']['imported'] == 2
            expect(button(page, '核对保存结果')).to_be_enabled()
            self.capture(page, 'unknown-confirm', 1280, button(page, '核对保存结果'))
            before = self.snapshot()
            counts = self.receipt_counts()
            assert counts == dict(hub_transactions=2, hub_imports=1, hub_import_receipts=1, importAudits=1, receiptAudits=1)
            button(page, '核对保存结果').click()
            expect(button(page, '查看已导入账本')).to_be_enabled()
            assert self.snapshot() == before and self.receipt_counts() == counts
            assert self.count_requests('POST', BASE + '/confirm') == 1
            receipt_path = BASE + '/results/' + actual['payload']['requestId']
            assert self.count_requests('GET', receipt_path) == 1
            self.capture(page, 'original-receipt', 1280, page.get_by_test_id('finance-import-receipt'))
            self.proof('single-confirm', {'requestId': actual['payload']['requestId'], 'receipt': actual['result'],
                'counts': counts, 'before': before, 'after': self.snapshot()})
            self.passed('XLSX actual successful confirm with lost delivery recovers original receipt with one POST, batch and audit')

    def identity_offline_late_preview(self, browser):
        with self.flow(browser) as (ctx, page):
            self.start_import(page)
            self.mapping(page); self.mapped_preview(page)
            saved = self.save(page)
            before = self.records()
            page.reload(); self.start_import(page, name='synthetic-private-draft.csv')
            self.mapping(page)
            ctx.set_offline(True)
            page.evaluate("window.dispatchEvent(new Event('offline'))")
            expect(page.get_by_test_id('finance-import-panel')).to_have_count(0)
            expect(page.get_by_text('synthetic-private-draft.csv', exact=True)).to_have_count(0)
            self.capture(page, 'offline-concealed', 390, button(page, '重新核对身份'))
            ctx.set_offline(False)
            page.evaluate("window.dispatchEvent(new Event('online'))")
            expect(button(page, '按所选列预览')).to_be_enabled(timeout=15000)
            expect(page.get_by_text('synthetic-private-draft.csv', exact=True)).to_be_visible()
            expect(page.get_by_test_id('finance-flow-mapping')).to_contain_text('E 列 · 交易方向')
            held, url = [], self.base + BASE + '/preview'
            def hold(route):
                response = route.fetch(max_redirects=0)
                assert response.status == 200 and 'set-cookie' not in response.headers
                held.append((route, response.headers, response.body(), route.request.post_data_json))
            page.route(url, hold)
            try:
                button(page, '按所选列预览').click()
                self.settle(page, lambda: len(held) == 1)
                visibility(page, True)
                expect(page.get_by_test_id('finance-import-panel')).to_have_count(0)
                self.write(ctx, 'POST', '/api/logout', {})
                self.login(ctx, 2)
                route, headers, raw, payload = held.pop()
                self.proof('late-preview', {'payload': payload, 'actualResponse': json.loads(raw), 'deliveredAfterMemberSwitch': True})
                route.fulfill(status=200, headers=headers, body=raw)
                with page.expect_response(lambda response: urlsplit(response.url).path == '/api/me'
                                          and response.request.method == 'GET') as fresh:
                    visibility(page, False)
                response = fresh.value
                assert response.status == 200 and response.json()['user']['id'] == 'member2'
                response.finished()
                page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
                expect(page.get_by_test_id('finance-import-panel')).to_have_count(0)
                expect(page.locator('body')).not_to_contain_text('synthetic-private-draft.csv')
                expect(page.locator('body')).not_to_contain_text(ROWS[0][2])
                expect(button(page, '确认导入 · 仅本人')).to_have_count(0)
                denied = self.get(ctx, BASE + '/results/' + saved['payload']['requestId'], 404)
                assert denied['code'] == 'import_result_not_found' and self.overview(ctx)['transactions'] == []
                assert self.get(ctx, '/api/me')['user']['id'] == 'member2'
                page.goto(self.base + '/app/finance')
                expect(page.get_by_role('heading', name='家庭资金', exact=True)).to_be_visible()
                self.capture(page, 'new-member-private-empty', 390, page.get_by_role('heading', name='家庭资金', exact=True))
                assert self.records() == before and self.count_requests('POST', BASE + '/confirm') == 1
                self.proof('identity-no-write', {'original': before, 'after': self.records(), 'receiptDenied': denied})
            finally:
                page.unroute(url, hold)
                for route, *_ in held:
                    route.abort('failed')
            self.passed('Offline hides draft and same identity recovers it; real late preview after member switch cannot reveal or commit private data')

    @classmethod
    def run_scenarios(cls, root, bundle, report, out, browser, temp_root, cases):
        for name in cases:
            case_out = out / name; case_out.mkdir()
            folder, run = None, None
            before = {k: len(report[k]) for k in ('checks', 'screenshots', 'pageErrors', 'externalRequests')}
            case = {'name': name, 'passed': False}
            try:
                with ExitStack() as lifecycle:
                    folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='finance-flow-', dir=temp_root)))
                    run = cls(root, bundle, folder, report, case_out, lifecycle)
                    try:
                        getattr(run, name)(browser)
                        assert not any(r['status'] >= 500 for r in run.http), run.http
                    finally:
                        run.proof('database-final', run.snapshot())
                assert not folder.exists()
                assert not any(r['status'] >= 500 for r in run.http), run.http
                assert len(report['checks']) == before['checks'] + 1 and len(report['screenshots']) == before['screenshots'] + 2
                assert all(len(report[k]) == before[k] for k in ('pageErrors', 'externalRequests'))
                case['passed'] = True
            except Exception:
                del report['checks'][before['checks']:]
                failure = traceback.format_exc()
                (case_out / 'failure.txt').write_text(failure, encoding='utf-8')
                report['scenarioFailures'].append({'scenario': name, 'traceback': failure})
                print('FAIL ' + name + '\n' + failure, flush=True)
            finally:
                if run is not None:
                    run.proof('actual-http-journal', run.http)
                case['temporaryFixtureRemoved'] = folder is not None and not folder.exists()
                case['listenerStopped'] = run is not None and run.server is None and not run.thread.is_alive()
                report['scenarioResults'].append(case)
        assert not report['scenarioFailures']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--expected-build-evidence', required=True)
    parser.add_argument('--temp-root', required=True, type=Path)
    parser.add_argument('--case', action='append', choices=CASES, dest='cases')
    args = parser.parse_args()
    assert sys.dont_write_bytecode and not sys.flags.optimize
    assert re.fullmatch('[a-f0-9]{40}', args.expected_head) and re.fullmatch('[a-f0-9]{64}', args.expected_build_evidence)
    root, temp_root = args.source_root.resolve(), args.temp_root.resolve()
    bundle = args.bundle.absolute()
    if os.name == 'nt' and not str(bundle).startswith('\\\\?\\'):
        bundle = Path('\\\\?\\' + str(bundle))
    assert temp_root.is_dir() and not temp_root.is_symlink() and not temp_root.is_junction()
    def git(*command):
        return subprocess.check_output(['git', '--no-replace-objects', *command], cwd=root).decode('utf-8').strip()
    head, tree = git('rev-parse', 'HEAD'), git('rev-parse', 'HEAD^{tree}')
    assert head == args.expected_head and not git('status', '--porcelain=v1')
    assert Path(__file__).resolve() == (root / HARNESS).resolve()
    evidence_path = bundle.parent / 'build-evidence.json'
    assert sha(evidence_path) == args.expected_build_evidence
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    names = git('ls-files', '-z').rstrip('\0').split('\0')
    validate_build(git, root, head, evidence, names)
    assert exports(bundle) == evidence['files']
    def hashes(): return {name: sha(root / name) for name in names}
    cases, out = selected_cases(args.cases), exclusive_output(root)
    shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], screenshots=[], pageErrors=[], externalRequests=[], artifacts=[],
        scenarioResults=[], scenarioFailures=[], requestedCases=list(cases), head=head, tree=tree,
        buildSourceHead=head, buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(Path(__file__)),
        sourceHashesBefore=hashes(), bundleHashesBefore=exports(bundle), productionWrites=0,
        realFinancialData=False, realCloud=False, physicalTelevision=False,
        scope='Only requested synthetic CSV/XLSX browser cases, real Flask/SQLite/HTTPS and file picker. '
              'Exact source/build required. Held or dropped actual responses; no substituted business success.')
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
                Run.run_scenarios(root, bundle, report, out, browser, temp_root, cases)
                assert len(report['checks']) == len(cases) and len(report['screenshots']) == len(cases) * 2
                assert [c['name'] for c in report['scenarioResults']] == list(cases)
                assert not report['pageErrors'] and not report['externalRequests']
                report['passed'] = True
            finally:
                browser.close()
    except Exception:
        report['failure'] = traceback.format_exc(); print(report['failure'], flush=True)
    finally:
        try:
            report['sourceHashesAfter'], report['bundleHashesAfter'] = hashes(), exports(bundle)
            report['sourceUnchanged'] = report['sourceHashesBefore'] == report['sourceHashesAfter']
            report['bundleUnchanged'] = report['bundleHashesBefore'] == report['bundleHashesAfter']
            report['fixtureHashesAfter'] = {name: sha(root / name) for name in report.get('fixtureHashes', {})}
            report['fixturesUnchanged'] = bool(report.get('fixtureHashes')) and report['fixtureHashesAfter'] == report['fixtureHashes']
            report['sourceStillFrozen'] = git('rev-parse', 'HEAD') == head and not git('status', '--porcelain=v1')
            report['temporaryFixturesRemoved'] = len(report['scenarioResults']) == len(cases) and all(
                c['temporaryFixtureRemoved'] and c['listenerStopped'] for c in report['scenarioResults'])
            report['passed'] = report['passed'] and all(report[k] for k in ('sourceUnchanged', 'bundleUnchanged',
                'fixturesUnchanged', 'sourceStillFrozen', 'temporaryFixturesRemoved'))
        except Exception:
            report['passed'] = False; report['finalEvidenceFailure'] = traceback.format_exc()
        write_json(out / 'result.json', report)
        print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'report': str(out / 'result.json')}, ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
