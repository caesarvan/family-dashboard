"""Expo holdings with actual local Flask/SQLite/Edge and synthetic data only.

Uses the reviewed finance browser fixture for TLS, source freezing and screenshots.
Response loss tests forward to the real backend before aborting the browser reply.
"""
import argparse
from contextlib import ExitStack, closing
from datetime import datetime, timezone
import json
from pathlib import Path
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
from browser_expo_finance_check import Run as FinanceRun, button, visibility, sha, csv_bytes


BASE = '/api/finance-hub/investments'
COLUMNS = ['holdingKey', 'name', 'institution', 'assetType', 'currency', 'quantity', 'cost', 'value', 'asOf', 'note', 'recordId']


class Run(FinanceRun):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.report['fixtureHarnessSha256'] = sha(self.root / 'tests/browser_expo_finance_check.py')

    def clear_finance(self):
        super().clear_finance()
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database)) as con:
            for table in ('hub_investment_operations', 'hub_investment_import_previews',
                          'hub_investment_import_receipts', 'hub_investment_links',
                          'hub_investment_sources', 'hub_investments'):
                con.execute('DELETE FROM "' + table + '"')
            con.commit()

    def holdings(self, ctx):
        return self.get(ctx, BASE)['investments']

    def open_holdings(self, page):
        page.goto(self.base + '/app/investments')
        expect(page.get_by_role('heading', name='我的持仓', exact=True)).to_be_visible(timeout=15000)
        expect(button(page, '新增持仓')).to_be_enabled()

    def edit_fields(self, page, name='合成私人持仓', value=''):
        for label, content in [('持仓名称', name), ('持仓机构', '合成机构'), ('资产类型', '基金'),
                ('持仓币种', 'USD'), ('持仓数量', '1.25000001'), ('持仓成本', '123.45'),
                ('持仓估值', value), ('估值核对日期', '2026-09-17'), ('持仓备注', '仅合成数据')]:
            page.get_by_role('textbox', name=label, exact=True).fill(content)

    def manual_crud(self, browser):
        with self.flow(browser) as (ctx, page):
            self.open_holdings(page)
            button(page, '新增持仓').click()
            self.edit_fields(page)
            for width in (320, 390, 1040, 1440):
                self.screenshot(page, 'holding-editor', width)
            with page.expect_response(lambda r: urlsplit(r.url).path == BASE and r.request.method == 'POST') as response:
                button(page, '保存当前记录').click()
            assert response.value.status == 201, response.value.text()
            created = response.value.json()
            assert created['valueCents'] is None and created['costCents'] == 12345
            expect(button(page, '查看持仓 合成私人持仓')).to_be_visible()
            button(page, '查看持仓 合成私人持仓').click()
            button(page, '编辑这条持仓').click()
            page.get_by_role('textbox', name='持仓估值', exact=True).fill('0')
            with page.expect_response(lambda r: r.request.method == 'PATCH' and urlsplit(r.url).path == BASE + '/' + created['id']) as updated:
                button(page, '保存当前记录').click()
            assert updated.value.status == 200 and updated.value.json()['valueCents'] == 0
            self.restart()
            self.open_holdings(page)
            assert self.holdings(ctx)[0]['valueCents'] == 0
            for width in (320, 390, 1040, 1440):
                self.screenshot(page, 'holdings', width)
            button(page, '查看持仓 合成私人持仓').click()
            button(page, '删除这条持仓').click()
            expect(page.get_by_text('删除本地持仓记录？', exact=True)).to_be_visible()
            assert len(self.holdings(ctx)) == 1
            with page.expect_response(lambda r: r.request.method == 'DELETE') as deleted:
                button(page, '确认删除本地记录').click()
            assert deleted.value.status == 200 and deleted.value.json()['deleted']
            assert self.holdings(ctx) == []
            self.passed('Manual create/update/delete use real persisted records; unknown valuation stays distinct from zero; restart and four widths verified')

    def unknown_create(self, browser):
        with self.flow(browser) as (ctx, page):
            self.open_holdings(page)
            button(page, '新增持仓').click()
            self.edit_fields(page, '合成响应丢失持仓')
            captured = []
            def lose_reply(route):
                if route.request.method != 'POST': return route.continue_()
                captured.append(route.request.post_data_json)
                reply = route.fetch()
                assert reply.status == 201
                route.abort('failed')
            page.route(self.base + BASE, lose_reply)
            button(page, '保存当前记录').click()
            expect(button(page, '核对操作结果')).to_be_enabled()
            page.unroute(self.base + BASE, lose_reply)
            assert len(captured) == 1 and len(self.holdings(ctx)) == 1
            button(page, '核对操作结果').click()
            expect(button(page, '查看持仓 合成响应丢失持仓')).to_be_visible()
            assert len(self.holdings(ctx)) == 1
            read = self.get(ctx, BASE + '/operations/' + captured[0]['requestId'])
            assert read['recordId'] == self.holdings(ctx)[0]['id']
            self.passed('Lost successful POST response is recovered by its original durable operation receipt without duplicate creation')

    def open_import(self, page, content, name='synthetic-holdings.csv'):
        button(page, '导入持仓').click()
        expect(page.get_by_test_id('investment-import-panel')).to_be_visible()
        page.get_by_role('textbox', name='持仓来源名称', exact=True).fill('合成稳定来源')
        with page.expect_file_chooser() as chooser:
            button(page, '选择持仓文件').click()
        chooser.value.set_files({'name': name, 'mimeType': 'text/csv', 'buffer': content})
        button(page, '预览持仓文件').click()
        expect(page.get_by_test_id('investment-import-preview')).to_be_visible()

    def import_roundtrip(self, browser):
        with self.flow(browser) as (ctx, page):
            content = csv_bytes([['stable-1', '合成导入基金', '合成机构', '基金', 'CNY', '10', '100.00', '105.01',
                                  '2026-09-17', '合成备注', '']], COLUMNS)
            self.open_holdings(page)
            self.open_import(page, content)
            assert self.holdings(ctx) == []
            for width in (320, 390, 1040, 1440):
                self.screenshot(page, 'holding-import-preview', width)
            with page.expect_response(lambda r: urlsplit(r.url).path == BASE + '/imports/confirm') as confirmed:
                button(page, '确认导入持仓 · 仅本人').click()
            assert confirmed.value.status == 200 and confirmed.value.json()['created'] == 1
            expect(page.get_by_test_id('investment-import-receipt')).to_be_visible()
            button(page, '查看持仓').click()
            expect(button(page, '查看持仓 合成导入基金')).to_be_visible()
            row = self.holdings(ctx)[0]
            assert row['source'] == {'sourceName': '合成稳定来源', 'holdingKey': 'stable-1'}
            button(page, '查看持仓 合成导入基金').click()
            expect(page.get_by_text('stable-1', exact=False)).to_be_visible()
            button(page, '返回持仓列表').click()
            self.open_import(page, content)
            with page.expect_response(lambda r: urlsplit(r.url).path == BASE + '/imports/confirm') as replayed:
                button(page, '确认导入持仓 · 仅本人').click()
            assert replayed.value.status == 200 and replayed.value.json()['replayed']
            assert len(self.holdings(ctx)) == 1
            button(page, '查看持仓').click()
            self.passed('File preview writes no holdings; explicit confirmation persists source and stable key; repeated original file returns historical receipt without duplicate')

    def private_visibility(self, browser):
        with self.flow(browser) as (ctx, page):
            self.open_holdings(page)
            button(page, '新增持仓').click()
            self.edit_fields(page, 'PRIVATE_MARKER_甲')
            button(page, '保存当前记录').click()
            expect(button(page, '查看持仓 PRIVATE_MARKER_甲')).to_be_visible()
            ctx.set_offline(True)
            expect(button(page, '查看持仓 PRIVATE_MARKER_甲')).not_to_be_visible()
            ctx.set_offline(False)
            expect(button(page, '查看持仓 PRIVATE_MARKER_甲')).to_be_visible(timeout=15000)
            visibility(page, True)
            expect(button(page, '查看持仓 PRIVATE_MARKER_甲')).not_to_be_visible()
            visibility(page, False)
            expect(button(page, '查看持仓 PRIVATE_MARKER_甲')).to_be_visible(timeout=15000)
            self.write(ctx, 'POST', '/api/logout', {})
            self.login(ctx, 2)
            self.open_holdings(page)
            assert self.holdings(ctx) == []
            assert 'PRIVATE_MARKER_甲' not in page.locator('body').inner_text()
            self.passed('Private holdings hide offline and in background and do not cross a real member login change')

    def unknown_import(self, browser):
        with self.flow(browser) as (ctx, page):
            content = csv_bytes([['lost-1', '合成导入响应丢失', '合成机构', '基金', 'USD', '', '50.01', '',
                                  '2026-09-17', '', '']], COLUMNS)
            self.open_holdings(page)
            self.open_import(page, content)
            captured = []
            def lose_reply(route):
                captured.append(route.request.post_data_json)
                reply = route.fetch()
                assert reply.status == 200 and reply.json()['created'] == 1
                route.abort('failed')
            page.route(self.base + BASE + '/imports/confirm', lose_reply)
            button(page, '确认导入持仓 · 仅本人').click()
            expect(button(page, '核对持仓保存结果')).to_be_enabled()
            page.unroute(self.base + BASE + '/imports/confirm', lose_reply)
            assert len(captured) == 1 and len(self.holdings(ctx)) == 1
            button(page, '核对持仓保存结果').click()
            expect(page.get_by_test_id('investment-import-receipt')).to_be_visible()
            button(page, '查看持仓').click()
            expect(button(page, '查看持仓 合成导入响应丢失')).to_be_visible()
            assert len(self.holdings(ctx)) == 1
            self.passed('Lost real import success is recovered by source/digest receipt; no repeated holding write')

    def run_scenarios(self, browser):
        self.manual_crud(browser)
        self.unknown_create(browser)
        self.import_roundtrip(browser)
        self.unknown_import(browser)
        self.private_visibility(browser)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--expected-build-evidence', required=True)
    args = parser.parse_args()
    root, bundle = args.source_root.resolve(), args.bundle.resolve()
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    assert head == args.expected_head, 'Unexpected source commit'
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
    out = Path(__file__).resolve().parents[1] / 'test-results' / ('expo-investments-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], screenshots=[],
        eventInjections=['document.hidden/visibilityState plus visibilitychange for background/foreground'],
        head=head, tree=evidence['sourceTree'], buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(out / 'executed-harness.py'),
        sourceHashesBefore=hashes(), bundleHashesBefore=bundle_hashes(), productionWrites=0, realCloud=False, physicalTelevision=False,
        scope='Frozen Expo bundle, real local Flask/SQLite, real member sessions and CSRF; synthetic holding files only. Household/TV isolation is validated separately in backend tests.')
    original_connect = socket.socket.connect

    def local_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
            report['externalRequests'].append({'kind': 'non-loopback socket'})
            raise AssertionError('External network forbidden')
        return original_connect(sock, address)

    run = None
    try:
        with ExitStack() as lifecycle:
            lifecycle.enter_context(patch.object(socket.socket, 'connect', local_connect))
            folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='expo-investments-')))
            run = Run(root, bundle, folder, report, out, lifecycle)
            with sync_playwright() as pw, ExitStack() as browsers:
                browser = pw.chromium.launch(channel='msedge', headless=True)
                browsers.callback(browser.close)

                def capture_failure():
                    if not report['passed'] and run.page is not None and not run.page.is_closed():
                        try:
                            run.page.screenshot(path=str(out / 'failure.png'), full_page=True)
                            (out / 'failure-aria.txt').write_text(run.page.locator('body').aria_snapshot(), encoding='utf-8')
                        except Exception:
                            pass

                browsers.callback(capture_failure)
                run.run_scenarios(browser)
                assert not report['pageErrors'] and not report['externalRequests']
                report['passed'] = True
    except Exception:
        report['passed'] = False
        report['failure'] = traceback.format_exc()
        print(report['failure'], flush=True)
    finally:
        report['sourceHashesAfter'] = hashes()
        report['bundleHashesAfter'] = bundle_hashes()
        report['sourceUnchanged'] = report['sourceHashesBefore'] == report['sourceHashesAfter']
        report['bundleUnchanged'] = report['bundleHashesBefore'] == report['bundleHashesAfter']
        report['passed'] = report['passed'] and report['sourceUnchanged'] and report['bundleUnchanged']
        (out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'report': str(out / 'result.json')}, ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    raise SystemExit(main())
