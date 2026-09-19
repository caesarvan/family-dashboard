"""Real local HTTPS/SQLite/browser analysis workflows with synthetic accounts.

Successful business responses are never substituted. Fault injection drops a
real committed response; all servers, sessions and data are disposable.
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

from playwright.sync_api import expect, sync_playwright
import browser_expo_finance_accounts_check as accounts

button, sha = accounts.button, accounts.sha
P = '/api/finance-analysis'
START, END, MID = '2026-09-01', '2026-09-18', '2026-09-10'
NAME = '合成本人账户分析'
CASES = ('cashflow_review_lifecycle', 'committed_recovery_and_privacy', 'coverage_and_responsive_summary')


class Run(accounts.Run):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for path, name in ((Path(accounts.__file__), 'tests/browser_expo_finance_accounts_check.py'),
                           (Path(__file__), 'tests/browser_expo_finance_analysis_check.py')):
            assert sha(path) == sha(self.root/name), name
            self.report['fixtureHashes'][name] = sha(path)

    def capture(self, page, name, width, target):
        page.set_viewport_size({'width': width, 'height': 1080 if width >= 1280 else 844})
        page.evaluate('() => document.fonts.ready')
        target.scroll_into_view_if_needed()
        page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
        metrics = page.evaluate('''() => ({width:innerWidth,scroll:document.documentElement.scrollWidth,
          clipped:[...document.querySelectorAll('[data-testid="finance-analysis-panel"] input,[data-testid="finance-analysis-panel"] textarea,[data-testid="finance-analysis-panel"] [role="button"],[data-testid="finance-analysis-panel"] [role="radio"]')]
          .filter(n=>{const r=n.getBoundingClientRect();return r.width>0&&r.height>0&&r.bottom>0&&r.top<innerHeight&&(r.right>innerWidth+2||r.left< -2)})
          .map(n=>({label:n.getAttribute('aria-label')||n.textContent,box:n.getBoundingClientRect().toJSON()}))})''')
        assert metrics['scroll'] <= width+2 and not metrics['clipped'], metrics
        path = self.out/f'{name}-{width}.png'
        page.screenshot(path=str(path), full_page=False)
        self.report['screenshots'].append({'path': path.relative_to(self.out.parent).as_posix(),
            'sha256': sha(path), 'width': width, 'metrics': metrics,
            'scope': 'Settled visible viewport of the actual analysis panel; not a whole inner ScrollView capture.'})

    def seed(self, ctx, name=NAME, currency='CNY', opening=100000, closing=120000, kind='asset'):
        rid = self.seed_account(ctx, name=name, amount=opening, day=START, currency=currency, kind=kind)['accountId']
        self.value(ctx, rid, END, closing)
        return rid

    def report_for(self, ctx, rid='all', status=200):
        return self.get(ctx, P+'/report?start='+START+'&end='+END+'&baseCurrency=CNY&step=month&accountIds='+rid, status)

    def open_analysis(self, page):
        self.open_accounts(page)
        button(page, '查看我的账户分析').click()
        expect(page.get_by_test_id('finance-analysis-panel')).to_be_visible(timeout=15000)
        expect(page.get_by_test_id('analysis-summary')).to_be_visible(timeout=15000)
        button(page, '自定义范围').click()
        page.get_by_role('textbox', name='起点 YYYY-MM-DD', exact=True).fill(START)
        page.get_by_role('textbox', name='终点 YYYY-MM-DD', exact=True).fill(END)
        button(page, '读取所选范围').click()
        expect(page.get_by_test_id('analysis-summary')).to_contain_text(START, timeout=15000)
        expect(button(page, '重新读取当前分析')).to_be_enabled(timeout=15000)

    def select_analysis(self, page, name=NAME):
        button(page, '核对 '+name).click()
        expect(page.get_by_test_id('analysis-detail')).to_be_visible(timeout=15000)
        expect(button(page, '登记资金进出')).to_be_enabled(timeout=15000)

    def flow_draft(self, page, amount='50.00', note='仅本人合成资金进出'):
        button(page, '登记资金进出').click()
        expect(page.get_by_test_id('analysis-editor')).to_be_visible()
        page.get_by_role('textbox', name='资金进出日期 YYYY-MM-DD', exact=True).fill(MID)
        page.get_by_role('textbox', name='原币金额（最多两位小数）', exact=True).fill(amount)
        page.get_by_role('textbox', name='本人备注', exact=True).fill(note)

    def save_flow(self, page, rid, drop=False):
        return self.mutation(page, 'POST', P+'/accounts/'+rid+'/cashflows',
            lambda: button(page, '保存').click(), drop=drop)

    def confirm_period(self, page, rid):
        button(page, '核对区间完整性').click()
        page.get_by_role('checkbox', name='我已核对两端估值及该区间全部外部资金进出，确认记录完整', exact=True).click()
        result = self.mutation(page, 'PUT', P+'/accounts/'+rid+'/reviews/'+START+'/'+END,
            lambda: button(page, '确认此区间完整').click())
        expect(page.get_by_test_id('analysis-editor')).to_have_count(0)
        expect(page.get_by_test_id('analysis-detail')).to_contain_text('区间已核对', timeout=15000)
        return result

    def cashflow_review_lifecycle(self, browser):
        with self.flow(browser) as (ctx, page):
            rid = self.seed(ctx)
            original = self.history(ctx, rid)
            self.open_analysis(page)
            self.select_analysis(page)
            before = self.report_for(ctx, rid)['accounts'][0]
            assert before['change']['valuationResidualCents'] is None
            self.flow_draft(page)
            saved = self.save_flow(page, rid)
            expect(page.get_by_test_id('analysis-editor')).to_have_count(0)
            expect(page.get_by_test_id('analysis-detail')).to_be_visible(timeout=15000)
            self.confirm_period(page, rid)
            item = self.report_for(ctx, rid)['accounts'][0]
            assert item['change']['recordedNetFlowCents'] == '5000'
            assert item['change']['valuationResidualCents'] == '15000'
            assert item['change']['fxEffectCents'] == '0'
            button(page, '修改此笔资金').click()
            page.get_by_role('textbox', name='原币金额（最多两位小数）', exact=True).fill('70.00')
            fid = saved['result']['result']['id']
            self.mutation(page, 'PATCH', P+'/accounts/'+rid+'/cashflows/'+fid,
                lambda: button(page, '保存').click())
            expect(page.get_by_test_id('analysis-detail')).to_contain_text('须重新核对', timeout=15000)
            item = self.report_for(ctx, rid)['accounts'][0]
            assert item['review']['status'] == 'stale' and item['change']['valuationResidualCents'] is None
            self.confirm_period(page, rid)
            assert self.report_for(ctx, rid)['accounts'][0]['change']['valuationResidualCents'] == '13000'
            self.capture(page, 'analysis-reviewed-phone', 390, page.get_by_test_id('analysis-detail'))
            self.restart()
            page.reload()
            self.open_analysis(page)
            self.select_analysis(page)
            assert self.report_for(ctx, rid)['accounts'][0]['change']['valuationResidualCents'] == '13000'
            assert self.history(ctx, rid) == original
            self.passed('Real browser cashflow create, explicit interval confirmation, correction invalidation, reconfirmation and application restart preserve exact original valuations and attribution')

    def committed_recovery_and_privacy(self, browser):
        with self.flow(browser) as (ctx, page), ExitStack() as extras:
            rid = self.seed(ctx)
            self.open_analysis(page)
            self.select_analysis(page)
            self.flow_draft(page, note='合成不可共享的账户备注')
            saved = self.save_flow(page, rid, drop=True)
            key = saved['body']['requestId']
            expect(page.get_by_test_id('analysis-recovery')).to_contain_text(key, timeout=15000)
            expect(button(page, '查询原操作结果')).to_be_enabled(timeout=15000)
            assert self.get(ctx, P+'/operations/'+key)['found']
            button(page, '查询原操作结果').click()
            expect(page.get_by_test_id('analysis-recovery')).to_have_count(0, timeout=15000)
            expect(page.get_by_test_id('analysis-detail')).to_be_visible(timeout=15000)
            assert self.count_requests('POST', P+'/accounts/'+rid+'/cashflows') == 1
            assert self.get(ctx, P+'/accounts/'+rid+'/cashflows?start='+START+'&end='+END)['total'] == 1
            partner = self.context(browser, member=2)
            extras.callback(partner.close)
            assert self.report_for(partner)['accounts'] == []
            self.report_for(partner, rid, status=404)
            assert not self.get(partner, P+'/operations/'+key)['found']
            partner_page = partner.new_page()
            self.open_analysis(partner_page)
            expect(partner_page.locator('body')).not_to_contain_text(NAME)
            expect(partner_page.locator('body')).not_to_contain_text('合成不可共享的账户备注')
            self.passed('Dropped real committed response recovers the original receipt without duplicate write; another actual member session cannot read the account, note or receipt')

    def coverage_and_responsive_summary(self, browser):
        with self.flow(browser) as (ctx, page):
            self.seed(ctx)
            self.seed(ctx, name='合成缺少参考汇率', currency='USD')
            self.seed(ctx, name='合成明确未知估值', closing=None)
            self.seed(ctx, name='合成已知负债', kind='liability', opening=20000, closing=30000)
            self.open_analysis(page)
            summary = self.report_for(ctx)['summary']
            assert summary['knownNetCents'] == '90000'
            assert summary['coverage']['missingFxCount'] == summary['coverage']['unknownValuationCount'] == 1
            assert not summary['complete']
            expect(page.get_by_test_id('analysis-summary')).to_contain_text('900.00')
            expect(page.get_by_test_id('analysis-trend')).to_be_visible(timeout=15000)
            self.capture(page, 'analysis-summary-phone', 390, page.get_by_test_id('analysis-summary'))
            self.capture(page, 'analysis-trend-desktop', 1280, page.get_by_test_id('analysis-trend'))
            self.select_analysis(page, '合成明确未知估值')
            button(page, '核对区间完整性').click()
            expect(button(page, '确认此区间完整')).to_be_disabled()
            expect(page.get_by_test_id('analysis-editor')).to_contain_text('补齐已知估值')
            self.passed('Mixed known debt, unknown valuation and missing FX remain explicit gaps; responsive summary/trend render and incomplete endpoints cannot be confirmed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--build-evidence', required=True, type=Path)
    parser.add_argument('--expected-build-evidence', required=True)
    args = parser.parse_args()
    root, bundle = args.source_root.resolve(), args.bundle.resolve()
    assert re.fullmatch('[a-f0-9]{40}', args.expected_head)
    assert re.fullmatch('[a-f0-9]{64}', args.expected_build_evidence)
    def git(*command):
        return subprocess.check_output(['git', '--no-replace-objects', *command], cwd=root, text=True).strip()
    assert git('rev-parse', 'HEAD') == args.expected_head and not git('status', '--porcelain=v1')
    evidence_path = args.build_evidence.resolve()
    assert sha(evidence_path) == args.expected_build_evidence
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    assert evidence['buildExit'] == 0 and evidence['bundleMarkers'] is True
    assert evidence['head'] == args.expected_head and evidence['tree'] == git('rev-parse', 'HEAD^{tree}')
    names = subprocess.check_output(['git', '--no-replace-objects', 'ls-files', '-z'], cwd=root).decode().rstrip('\0').split('\0')
    def hashes():
        return {name: sha(root/name) for name in names}
    def exports():
        return {p.relative_to(bundle).as_posix(): sha(p) for p in bundle.rglob('*') if p.is_file()}
    assert exports() == evidence['files'] and all(sha(root/name) == digest for name, digest in evidence['inputFiles'].items())
    assert sha(Path(__file__)) == sha(root/'tests/browser_expo_finance_analysis_check.py')
    out = root/'test-results'/('expo-finance-analysis-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    shutil.copyfile(__file__, out/'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], screenshots=[], scenarioResults=[], scenarioFailures=[],
        head=args.expected_head, tree=evidence['tree'], buildEvidenceSha256=sha(evidence_path),
        harnessSha256=sha(out/'executed-harness.py'), sourceHashesBefore=hashes(), bundleHashesBefore=exports(),
        productionWrites=0, realFinancialData=False, realCloud=False, physicalTelevision=False,
        scope='Real local Flask/SQLite/HTTPS/Edge with synthetic accounts. No successful business response substitution. Lost-response case drops a real committed response. Public-rate networking is forbidden here and tested separately. Screenshots need independent visual review.')
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
                for name in CASES:
                    folder, case_out = None, out/name
                    case_out.mkdir()
                    case = {'name': name, 'passed': False}
                    before = len(report['checks'])
                    try:
                        with ExitStack() as lifecycle:
                            folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='analysis-browser-')))
                            run = Run(root, bundle, folder, report, case_out, lifecycle)
                            getattr(run, name)(browser)
                        assert len(report['checks']) == before+1
                        case['passed'] = True
                    except Exception:
                        del report['checks'][before:]
                        failure = traceback.format_exc()
                        (case_out/'failure.txt').write_text(failure, encoding='utf-8')
                        report['scenarioFailures'].append({'name': name, 'failure': failure})
                        print(failure, flush=True)
                    finally:
                        case['temporaryFixtureRemoved'] = folder is not None and not folder.exists()
                        report['scenarioResults'].append(case)
                assert len(report['checks']) == len(CASES) and len(report['screenshots']) == 3
                assert not report['pageErrors'] and not report['externalRequests'] and not report['scenarioFailures']
                report['passed'] = True
            finally:
                browser.close()
    except Exception:
        report['failure'] = traceback.format_exc()
    finally:
        report['sourceUnchanged'] = hashes() == report['sourceHashesBefore'] and git('rev-parse', 'HEAD') == args.expected_head and not git('status', '--porcelain=v1')
        report['bundleUnchanged'] = exports() == report['bundleHashesBefore']
        report['passed'] = report['passed'] and report['sourceUnchanged'] and report['bundleUnchanged'] and all(c['temporaryFixtureRemoved'] for c in report['scenarioResults'])
        (out/'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'report': str(out/'result.json')}, ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    raise SystemExit(main())
