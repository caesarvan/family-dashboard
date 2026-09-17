"""Isolated real-browser acceptance for explicit generic bill column mapping.

Successful responses come from temporary Flask/SQLite; injected faults only
drop or hold real traffic. No production, personal files, or external services.
"""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import traceback
from unittest.mock import patch
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright
import browser_expo_finance_check as fixture
from browser_expo_finance_check import Run as BaseRun, button, csv_bytes, sha, visibility

BASE = '/api/finance-hub/imports'
HEADERS = ['记录时点', '记账数值', '内容说明', '记账单位', '调整数值']
ROWS = [['2026-09-18', '12.34', '合成早餐\n仅用于映射验收', 'CNY', '56.78'],
        ['2026-09-19', '0.01', '合成一分记录', 'USD', '0.02']]
MAPPING = dict(version=1, headerLine=1, date=0, amount=1, title=2, currency=3)
CHECKS = 6
WIDTHS = (320, 390, 1280, 1920)


class Run(BaseRun):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        assert Path(self.source.__file__).resolve() == (self.root / 'app.py').resolve()
        paths = {'tests/browser_expo_finance_check.py': str(Path(fixture.__file__).resolve()),
                 'tests/browser_finance_column_mapping_check.py': str(Path(__file__).resolve()),
                 **{'tests/' + name + '.py': str(Path(sys.modules[name].__file__).resolve())
                    for name in ('test_financial_files', 'test_app')}}
        digests = {name: sha(Path(path)) for name, path in paths.items()}
        for name, digest in digests.items():
            assert digest == sha(self.root / name), name
        assert digests['tests/browser_finance_column_mapping_check.py'] == self.report['harnessSha256']
        assert self.report.setdefault('fixtureActualPaths', paths) == paths
        assert self.report.setdefault('fixtureHashes', digests) == digests

    def clear_finance(self):
        pass  # Each independent scenario has a fresh database.

    def start_import(self, page, raw=None, name='synthetic-mapping.csv'):
        self.open_finance(page)
        self.open_import(page, csv_bytes(ROWS, HEADERS) if raw is None else raw, name=name)

    def actual(self, page, path, action, *, drop=False):
        """Retain actual response bytes before browser navigation can release them."""
        calls = []
        def intercept(route):
            assert route.request.method == 'POST'
            response = route.fetch(max_redirects=0)
            raw = response.body()
            calls.append(dict(payload=route.request.post_data_json, status=response.status, result=json.loads(raw)))
            if drop:
                route.abort('failed')
            else:
                route.fulfill(status=response.status, headers=response.headers, body=raw)
        url = self.base + path
        page.route(url, intercept)
        try:
            action()
            self.settle(page, lambda: len(calls) == 1)
            assert len(calls) == 1 and calls[0]['status'] == 200, calls
            if not drop:
                expect(page.get_by_label('正在处理文件', exact=True)).to_have_count(0)
            return calls[0]
        finally:
            page.unroute(url, intercept)

    def headers(self, page):
        if button(page, '手动指定列').count():
            button(page, '手动指定列').click()
        result = self.actual(page, BASE + '/preview', lambda: button(page, '读取表头').click())['result']
        assert result['requiresColumnSelection'] and result['previewToken'] is None
        assert not result['rows'] and not result['errors']
        expect(page.get_by_test_id('finance-column-mapping')).to_be_visible()
        return result['columnSelection']

    def select_columns(self, page, columns, mapping=None):
        mapping = mapping or MAPPING
        for key, label in [('date', '日期列'), ('amount', '金额列'), ('title', '标题列'), ('currency', '币种列')]:
            column = next(c for c in columns if c['index'] == mapping[key])
            page.get_by_role('button', name=label, exact=True).click()
            page.get_by_role('menuitem', name=column['columnLabel'] + ' 列 · ' + (column['label'] or '无标题'), exact=True).click()
            expect(page.get_by_role('menuitem')).to_have_count(0)

    def mapped_preview(self, page):
        result = self.actual(page, BASE + '/preview', lambda: button(page, '按所选列预览').click())
        assert not result['result']['requiresColumnSelection']
        expect(page.get_by_role('heading', name='核对预览', exact=True)).to_be_visible()
        return result

    def save(self, page, drop=False):
        return self.actual(page, BASE + '/confirm', lambda: button(page, '确认导入 · 仅本人').click(), drop=drop)

    def prepare(self, page):
        self.start_import(page)
        meta = self.headers(page)
        self.select_columns(page, meta['columns'])
        return self.mapped_preview(page), meta

    def csv_persistence(self, browser):
        with self.flow(browser) as (ctx, page):
            preview, _ = self.prepare(page)
            value = preview['result']
            assert value['newCount'] == 2 and value['errorCount'] == 0
            assert [(r['amountCents'], r['currency']) for r in value['rows']] == [(1234, 'CNY'), (1, 'USD')]
            assert value['rows'][0]['sourceLocation'] == dict(lineStart=2, lineEnd=3, lineKind='csv_lines')
            saved = self.save(page)
            assert saved['result']['imported'] == 2
            original = self.raw_transactions()
            assert len(original) == 2
            stored = {json.loads(raw)['title']: json.loads(raw) for raw in original.values()}
            provenance = stored[ROWS[0][2]]['provenance']
            assert provenance['status'] == 'recorded' and provenance['fileName'] == 'synthetic-mapping.csv'
            assert provenance['batchId'] == saved['result']['batchId']
            assert (provenance['lineStart'], provenance['lineEnd'], provenance['lineKind']) == (2, 3, 'csv_lines')
            self.restart()
            assert self.raw_transactions() == original
            page.reload()
            repeat, meta = self.prepare(page)
            assert repeat['result']['duplicateCount'] == 2 and repeat['result']['newCount'] == 0
            self.select_columns(page, meta['columns'], {**MAPPING, 'amount': 4})
            changed = self.mapped_preview(page)
            assert changed['result']['conflictCount'] == 2 and changed['result']['newCount'] == 0
            again = self.save(page)
            assert again['result']['imported'] == 0 and again['result']['conflicts'] == 2
            assert self.raw_transactions() == original
            self.passed('CSV mapping preserves exact currencies and physical multiline source location across restart; repeat and remap retain original two records')

    def xlsx_sheet(self, browser):
        with self.flow(browser) as (ctx, page):
            raw = self.workbook([HEADERS, *ROWS], second_sheet=True)
            self.start_import(page, raw, 'synthetic-mapping.xlsx')
            inspect = self.actual(page, BASE + '/preview', lambda: button(page, '预览文件').click())['result']
            assert inspect['requiresSheetSelection'] and inspect['previewToken'] is None
            button(page, '选择账单工作表').click()
            page.get_by_role('menuitem', name='支付账单', exact=True).click()
            meta = self.headers(page)
            self.select_columns(page, meta['columns'])
            preview = self.mapped_preview(page)
            assert preview['result']['fileInfo']['sheet'] == '支付账单'
            assert preview['result']['rows'][0]['sourceLocation'] == dict(lineStart=2, lineEnd=2, lineKind='worksheet_rows')
            changed_sheet = {**preview['payload'], 'file': {**preview['payload']['file'], 'sheet': '订单'},
                             'previewToken': preview['result']['previewToken'], 'requestId': uuid4().hex}
            me = self.get(ctx, '/api/me')
            response = ctx.request.post(self.base + BASE + '/confirm', data=changed_sheet,
                                       headers={'X-CSRF-Token': me['csrf'], 'Origin': self.base})
            assert response.status in (400, 409, 422) and not self.raw_transactions()
            assert self.save(page)['result']['imported'] == 2
            self.passed('XLSX sheet selection precedes mapping; original worksheet coordinates persist and old token cannot authorize another sheet')

    def invalidation_and_errors(self, browser):
        with self.flow(browser) as (ctx, page):
            preview, meta = self.prepare(page)
            self.select_columns(page, meta['columns'], {**MAPPING, 'amount': 4})
            expect(button(page, '确认导入 · 仅本人')).to_have_count(0)
            changed = {**preview['payload'], 'mapping': {**MAPPING, 'amount': 4},
                       'previewToken': preview['result']['previewToken'], 'requestId': uuid4().hex}
            me = self.get(ctx, '/api/me')
            response = ctx.request.post(self.base + BASE + '/confirm', data=changed,
                                       headers={'X-CSRF-Token': me['csrf'], 'Origin': self.base})
            assert response.status in (400, 409, 422) and not self.raw_transactions()
            bad_rows = [['2026-09-18', 'not-a-number', '合成错误金额', 'CNY', '0'],
                        ['2026-09-18', '1.00', '合成短行缺少币种'],
                        ['2026-09-18', '2.00', '合成有效行也不部分保存', 'CNY', '0']]
            self.choose_file(page, csv_bytes(bad_rows, HEADERS), 'synthetic-invalid.csv')
            expect(button(page, '确认导入 · 仅本人')).to_have_count(0)
            meta = self.headers(page)
            self.select_columns(page, meta['columns'])
            bad = self.mapped_preview(page)['result']
            assert bad['errorCount'] == 2 and len(bad['rows']) == 1 and not bad['previewToken']
            expect(button(page, '确认导入 · 仅本人')).to_be_disabled()
            assert not self.raw_transactions()
            self.passed('Changing columns or file invalidates the old preview; mismatched token, malformed amount and missing currency prevent even valid rows from being saved')

    def lost_response(self, browser):
        with self.flow(browser) as (ctx, page):
            self.prepare(page)
            actual = self.save(page, drop=True)
            assert actual['result']['imported'] == 2
            expect(button(page, '核对保存结果')).to_be_enabled()
            assert self.count_requests('POST', BASE + '/confirm') == 1
            before = self.raw_transactions()
            button(page, '核对保存结果').click()
            expect(button(page, '查看已导入账本')).to_be_enabled()
            assert self.raw_transactions() == before and len(before) == 2
            assert self.count_requests('POST', BASE + '/confirm') == 1
            assert self.count_requests('GET', BASE + '/results/' + actual['payload']['requestId']) == 1
            self.passed('A dropped real successful confirm response recovers from its original durable receipt with one write and unchanged transactions')

    def private_and_late(self, browser):
        with self.flow(browser) as (ctx, page), ExitStack() as extras:
            self.prepare(page)
            saved = self.save(page)
            other = self.context(browser, 2)
            extras.callback(other.close)
            self.get(other, BASE + '/results/' + saved['payload']['requestId'], 404)
            assert all(r['title'] not in [row[2] for row in ROWS] for r in self.overview(other, '2026-09')['transactions'])
            page.reload()
            self.start_import(page)
            meta = self.headers(page)
            self.select_columns(page, meta['columns'])
            held = []
            url = self.base + BASE + '/preview'
            def hold(route):
                response = route.fetch(max_redirects=0)
                assert response.status == 200
                assert 'set-cookie' not in response.headers
                held.append((route, response.status, response.headers, response.body()))
            page.route(url, hold)
            try:
                button(page, '按所选列预览').click()
                self.settle(page, lambda: len(held) == 1)
                visibility(page, True)
                self.write(ctx, 'POST', '/api/logout', {})
                route, status, headers, raw = held.pop()
                route.fulfill(status=status, headers=headers, body=raw)
                visibility(page, False)
                expect(page.get_by_label('登录密码', exact=True)).to_be_visible(timeout=15000)
                expect(page.get_by_test_id('finance-import-panel')).to_have_count(0)
                expect(page.get_by_text(ROWS[0][2], exact=True)).to_have_count(0)
                assert self.count_requests('POST', BASE + '/confirm') == 1
            finally:
                page.unroute(url, hold)
                for route, *_ in held:
                    route.abort('failed')
            self.passed('Another member cannot read imported records or receipts; real preview bytes arriving after logout stay concealed and cannot write')

    def capture(self, page, name, width, target):
        page.set_viewport_size({'width': width, 'height': 1080 if width >= 1280 else 844})
        page.evaluate('() => document.fonts.ready')
        target.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
        metrics = page.evaluate('''() => ({width:innerWidth,scroll:document.documentElement.scrollWidth,
          clipped:[...document.querySelectorAll('[data-testid="finance-column-mapping"] [role="button"],[data-testid="finance-column-mapping"] input')]
          .filter(n=>{const r=n.getBoundingClientRect();return r.width>0&&r.height>0&&r.bottom>0&&r.top<innerHeight&&(r.right>innerWidth+2||r.left< -2)})
          .map(n=>({label:n.getAttribute('aria-label')||n.textContent,box:n.getBoundingClientRect().toJSON()}))})''')
        assert metrics['scroll'] <= width + 2 and not metrics['clipped'], metrics
        path = self.out / f'{name}-{width}.png'
        page.screenshot(path=str(path), full_page=False)
        self.report['screenshots'].append(dict(path=path.relative_to(self.out.parent).as_posix(), sha256=sha(path),
            metrics=metrics, scope='Settled visible viewport; inner scroll regions require separate review.'))

    def widths_and_themes(self, browser):
        with self.flow(browser) as (ctx, page):
            for mode in ('light', 'dark'):
                preferences = self.get(ctx, '/api/preferences')
                self.write(ctx, 'PUT', '/api/preferences', {'revision': preferences['revision'], 'changes': {'colorMode': mode}})
                page.reload()
                self.start_import(page)
                meta = self.headers(page)
                self.select_columns(page, meta['columns'])
                page.wait_for_function("getComputedStyle(document.documentElement).colorScheme === '" + mode + "'")
                for width in WIDTHS:
                    self.capture(page, 'mapping-' + mode, width, button(page, '按所选列预览'))
                    box = button(page, '按所选列预览').bounding_box()
                    assert box and box['height'] >= 44 and box['width'] >= 44
            result = self.actual(page, BASE + '/preview', lambda: (button(page, '按所选列预览').focus(), button(page, '按所选列预览').press('Enter')))
            assert result['result']['newCount'] == 2 and not self.raw_transactions()
            self.passed('Four widths in both themes display explicit mapping controls with usable targets; keyboard previews without saving')

    @classmethod
    def run_scenarios(cls, root, bundle, report, out, browser):
        for name in ('csv_persistence', 'xlsx_sheet', 'invalidation_and_errors', 'lost_response', 'private_and_late', 'widths_and_themes'):
            case_out = out / name
            case_out.mkdir()
            folder = None
            before = tuple(len(report[k]) for k in ('checks', 'pageErrors', 'externalRequests'))
            case = dict(name=name, passed=False, temporaryFixtureRemoved=False)
            try:
                with ExitStack() as lifecycle:
                    folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='finance-mapping-browser-')))
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
    parser.add_argument('--expected-build-evidence', required=True)
    args = parser.parse_args()
    root, bundle = args.source_root.resolve(), args.bundle.resolve()
    assert sys.dont_write_bytecode and not sys.flags.optimize
    assert re.fullmatch('[a-f0-9]{40}', args.expected_head) and re.fullmatch('[a-f0-9]{64}', args.expected_build_evidence)
    def git(*command):
        return subprocess.check_output(['git', '--no-replace-objects', *command], cwd=root, text=True).strip()
    head = git('rev-parse', 'HEAD')
    assert head == args.expected_head and not git('status', '--porcelain=v1')
    evidence_path = bundle.parent / 'build-evidence.json'
    assert sha(evidence_path) == args.expected_build_evidence
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    build_head = evidence['sourceHead']
    assert re.fullmatch('[a-f0-9]{40}', build_head)
    assert evidence['sourceTree'] == git('rev-parse', build_head + '^{tree}')
    subprocess.run(['git', '--no-replace-objects', 'merge-base', '--is-ancestor', build_head, head], cwd=root, check=True)
    changes_since_build = set(git('diff', '--name-only', build_head, head).splitlines())
    assert changes_since_build <= {'tests/browser_finance_column_mapping_check.py', 'docs/FINANCE-COLUMN-MAPPING-BROWSER.md'}, 'Only this harness and its documentation may differ from the tested build'
    names = subprocess.check_output(['git', '--no-replace-objects', 'ls-files', '-z'], cwd=root).decode('utf-8').rstrip('\0').split('\0')
    def hashes():
        return {name: sha(root / name) for name in names}
    def exports():
        return {p.relative_to(bundle).as_posix(): sha(p) for p in bundle.rglob('*') if p.is_file()}
    assert exports() == evidence['files'] and all(sha(root / name) == value for name, value in evidence['inputFiles'].items())
    assert sha(Path(__file__)) == sha(root / 'tests/browser_finance_column_mapping_check.py')
    out = Path(__file__).resolve().parents[1] / 'test-results' / ('finance-column-mapping-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], screenshots=[], scenarioResults=[], scenarioFailures=[],
        head=head, tree=git('rev-parse', 'HEAD^{tree}'), buildSourceHead=build_head, buildSourceTree=evidence['sourceTree'],
        buildInputsEqual=True, changedSinceBuild=sorted(changes_since_build), buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(out / 'executed-harness.py'),
        sourceHashesBefore=hashes(), bundleHashesBefore=exports(), productionWrites=0, realFinancialData=False, realCloud=False,
        physicalTelevision=False, scope='Six independent temporary Flask/SQLite/HTTPS/Edge scenarios with synthetic generic files; no real platform export, cloud or device acceptance.')
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
                assert len(report['checks']) == CHECKS and len(report['screenshots']) == 8
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
        report['temporaryFixtureRemoved'] = len(report['scenarioResults']) == CHECKS and all(c['temporaryFixtureRemoved'] for c in report['scenarioResults'])
        report['passed'] = report['passed'] and report['sourceUnchanged'] and report['bundleUnchanged'] and report['fixturesUnchanged'] and report['sourceStillFrozen'] and report['temporaryFixtureRemoved']
        (out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(dict(passed=report['passed'], checks=len(report['checks']), report=str(out / 'result.json')), ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    raise SystemExit(main())
