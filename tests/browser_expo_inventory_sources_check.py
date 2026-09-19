"""Real isolated order-import, stock-source and privacy browser acceptance.

Requires an independently reviewed frozen source and its original Expo export.
Uses synthetic OOXML, real Flask/SQLite/Edge, and drops only a real committed
response. No production, cloud business calls, or substituted success responses.
"""
import argparse
import base64
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
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
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright
import browser_expo_inventory_followup_check as followup

AUTHOR = Path(__file__).resolve().parents[1]
shopping = followup.shopping
button, fill, sha = shopping.button, shopping.fill, shopping.sha
file_manifest, read_git_blobs = shopping.file_manifest, shopping.read_git_blobs
P, INVENTORY = shopping.P, shopping.INVENTORY
CASES = ('order_stock_lifecycle', 'lost_source_response', 'changed_source_privacy')
SCREENSHOT_COUNTS = dict(zip(CASES, (2, 1, 1)))
ORDER_TITLE = '合成私人订单商品甲'
SECOND_TITLE = '合成私人订单商品乙'


def fixture_bindings(root):
    bindings = followup.fixture_bindings(root)
    name = 'tests/browser_expo_inventory_followup_check.py'
    actual = Path(followup.__file__).resolve()
    assert sha(actual) == sha(root / name)
    bindings[name] = {'path': str(actual), 'sha256': sha(actual)}
    return bindings


class Run(followup.Run):
    def __init__(self, root, bundle, folder, report, out, lifecycle):
        bindings = fixture_bindings(root)
        assert report.setdefault('followupFixtureBindings', bindings) == bindings
        self.api_requests = []
        shopping.Run.__init__(self, root, bundle, folder, report, out, lifecycle)
        self.schema_before = self.schema()

    def context(self, browser, member=1):
        # A genuine DPR 2 context; do not alter product CSS/font rendering.
        ctx = browser.new_context(viewport={'width': 390, 'height': 844},
                                  device_scale_factor=2, ignore_https_errors=True)
        def local_only(handler):
            url = urlsplit(handler.request.url)
            base = urlsplit(self.base)
            if (url.scheme, url.netloc) != (base.scheme, base.netloc):
                self.report['externalRequests'].append({'host': url.hostname, 'scheme': url.scheme})
                handler.abort()
            else:
                handler.continue_()
        ctx.route('**/*', local_only)
        ctx.on('page', lambda page: page.on('pageerror', lambda error: self.report['pageErrors'].append(str(error))))
        ctx.on('request', lambda req: self.requests.append({'method': req.method,
            'path': urlsplit(req.url).path, 'query': urlsplit(req.url).query}))
        if member:
            self.login(ctx, member)
        return ctx

    def prepare_order(self, ctx):
        shop = self.setup(ctx, '合成订单关联采购哨兵')
        # The already bound workbook helper creates a real OOXML file. All
        # order rows pass through the actual importer; no SQL source injection.
        helper = sys.modules['test_financial_files']
        headers = sys.modules['finance_hub'].TAOBAO_ORDER_HEADERS.copy()
        rows = [headers,
            ['SYNTHETIC_ORDER', '2026-09-14 12:00:00', '交易成功', '合成店铺',
             ORDER_TITLE, 'https://example.invalid/no-fetch', '合成规格甲', '两盒（请核对）', '42.00', '100.00', '5.00'],
            ['', '', '', '', SECOND_TITLE, 'https://example.invalid/no-fetch', '合成规格乙', '3', '23.00', '', '']]
        xml = helper.sheet_xml(rows).replace('</worksheet>', '<mergeCells>' +
            ''.join('<mergeCell ref="' + col + '2:' + col + '3"/>' for col in 'ABCDJK') + '</mergeCells></worksheet>')
        raw = self.workbook(rows=rows, sheet_override=xml,
            extra_parts={'[Content_Types].xml': helper.content_types_with_binary_default()})
        payload = {'source': 'taobao', 'kind': 'orders', 'file': {
            'name': 'synthetic-orders.xlsx', 'contentBase64': base64.b64encode(raw).decode(), 'sheet': '支付账单'}}
        preview = self.write(ctx, 'POST', '/api/finance-hub/imports/preview', payload)
        assert not preview['errorCount'] and preview['previewToken']
        saved = self.write(ctx, 'POST', '/api/finance-hub/imports/confirm', {**payload, 'previewToken': preview['previewToken']})
        assert saved['imported'] == 1
        order = next(row for row in self.overview(ctx, '2026-09')['transactions'] if row['kind'] == 'orders')
        assert order['orderGroup']['itemCount'] == 2 and len(order['orderItems']) == 2
        self.protected_before = self.protected()
        self.report.setdefault('realOrderImports', []).append({'scenario': self.out.name, 'orderId': order['id'],
            'source': 'taobao', 'kind': 'orders', 'items': 2, 'fileSha256': hashlib.sha256(raw).hexdigest()})
        return shop, order

    def order(self, ctx, uid):
        return self.get(ctx, P + '/orders/' + uid + '?limit=50&offset=0')

    def open_order(self, page, order, line='item:0', *, select=True):
        self.open_finance(page)
        self.ledger(page, '2026-09')
        self.transaction(page, order['title'])
        button(page, '登记或查看订单库存').click()
        if select:
            expect(button(page, '选择订单商品 ' + line)).to_be_enabled(timeout=20000)
            button(page, '选择订单商品 ' + line).click()
        else:
            expect(button(page, '打开订单关联批次 ' + line)).to_be_enabled(timeout=20000)

    def source_form(self, page):
        button(page, '关联这件订单商品').click()
        expect(page.get_by_role('heading', name='本人订单来源', exact=True)).to_be_visible(timeout=20000)
        expect(button(page, '预览关联订单来源')).to_be_enabled(timeout=20000)

    def prepare_existing(self, ctx, shop):
        item = self.create_item(ctx, '合成已有共享设备', 'shared')
        batch = self.create_batch(ctx, item, shop)
        return self.write(ctx, 'POST', P + '/acquisitions/' + batch['acquisition']['id'] + '/movements', {
            'requestId': secrets.token_hex(16), 'itemRevision': batch['item']['revision'],
            'revision': batch['acquisition']['revision'], 'confirmReceived': True,
            'data': {'kind': 'receive', 'quantity': 2, 'occurredOn': '2026-09-18', 'reason': '合成非零库存哨兵'}})

    def choose_existing(self, page, current):
        button(page, '选择物品 ' + current['item']['title']).click()
        expect(button(page, '关联已有批次 ' + current['acquisition']['id'])).to_be_enabled(timeout=20000)
        button(page, '关联已有批次 ' + current['acquisition']['id']).click()
        expect(button(page, '预览关联订单来源')).to_be_enabled(timeout=20000)

    def finish_case(self, description):
        assert self.protected() == self.protected_before, 'Source workflow changed financial/shopping/trip sentinels'
        assert self.schema() == self.schema_before
        self.report.setdefault('protectedUnchanged', []).append(self.out.name)
        self.report.setdefault('requestObservations', {})[self.out.name] = {'browser': self.requests, 'fixture': self.api_requests}
        self.passed(description)

    def order_stock_lifecycle(self, browser):
        with self.flow(browser) as (ctx, page):
            self.stage('Real merged order -> explicit private item and manual batch -> source -> receive -> restart')
            _shop, order = self.prepare_order(ctx)
            self.open_order(page, order)
            button(page, '用此商品新建私人物品').click()
            expect(page.get_by_role('textbox', name='物品名称', exact=True)).to_have_value(ORDER_TITLE)
            expect(page.get_by_role('radio', name='仅本人可见', exact=True)).to_have_attribute('aria-checked', 'true')
            fill(page, '计量单位', '节')
            button(page, '保存物品').click()
            expect(page.get_by_role('textbox', name='批次数量', exact=True)).to_be_enabled(timeout=20000)
            expect(page.get_by_role('textbox', name='批次数量', exact=True)).to_have_value('')
            fill(page, '批次数量', '6')
            page.get_by_role('radio', name='运输中', exact=True).click()
            button(page, '保存批次').click()
            expect(button(page, '关联这件订单商品')).to_be_enabled(timeout=20000)
            assert self.query('SELECT count(*) FROM inventory_items') == [(1,)]
            assert self.query('SELECT count(*) FROM inventory_acquisitions') == [(1,)]
            assert self.query('SELECT count(*) FROM inventory_movements') == [(0,)]
            self.source_form(page)
            untouched = self.no_write_snapshot()
            button(page, '预览关联订单来源').click()
            expect(button(page, '确认关联订单来源')).to_be_enabled(timeout=20000)
            assert self.no_write_snapshot() == untouched
            self.capture(page, 'private-source-preview', 390, page.get_by_test_id('inventory-source-preview'),
                         ready=('确认关联订单来源',))
            button(page, '确认关联订单来源').click()
            expect(button(page, '预览解除订单来源')).to_be_enabled(timeout=20000)
            lines = self.order(ctx, order['id'])['lines']
            assert lines[0]['linkState'] == 'linked' and lines[1]['linkState'] == 'none'
            link = lines[0]['link']
            current = self.get(ctx, P + '/acquisitions/' + link['acquisitionId'])
            assert current['item']['visibility'] == 'private' and current['item']['unit'] == '节'
            assert current['acquisition']['orderedQty'] == 6 and current['item']['onHandQty'] == 0
            button(page, '返回库存批次').click()
            button(page, '收货').click()
            fill(page, '本次数量', '2')
            page.get_by_role('checkbox', name='我已核对实际物品和数量', exact=True).click()
            button(page, '确认实物变动').click()
            expect(button(page, '编辑批次')).to_be_enabled(timeout=20000)
            current = self.get(ctx, P + '/acquisitions/' + link['acquisitionId'])
            assert current['item']['onHandQty'] == 2 and current['acquisition']['remainingExpectedQty'] == 4
            button(page, '返回原订单').click()
            expect(page.get_by_role('heading', name='交易详情', exact=True)).to_be_visible(timeout=20000)
            button(page, '返回账本').click()
            expect(page.get_by_role('textbox', name='账本月份', exact=True)).to_have_value('2026-09')
            assert self.protected() == self.protected_before
            self.restart()
            self.open_order(page, order, select=False)
            button(page, '打开订单关联批次 item:0').click()
            expect(button(page, '编辑批次')).to_be_enabled(timeout=20000)
            reread = self.get(ctx, P + '/acquisitions/' + link['acquisitionId'])
            assert reread == current
            self.capture(page, 'persisted-stock-batch', 1280, page.get_by_test_id('section-card-content').filter(
                has=page.get_by_role('heading', name='批次详情', exact=True)), ready=('编辑批次',))
            assert self.query('SELECT count(*) FROM inventory_source_links') == [(1,)]
            assert self.query('SELECT count(*) FROM inventory_movements') == [(1,)]
            self.finish_case('real merged order and manual private stock association persist through receive/restart; finance remains unchanged')

    def lost_source_response(self, browser):
        with self.flow(browser) as (ctx, page):
            self.stage('Drop real committed source confirmation; original receipt restores without another POST')
            shop, order = self.prepare_order(ctx)
            current = self.prepare_existing(ctx, shop)
            self.open_order(page, order)
            self.choose_existing(page, current)
            button(page, '预览关联订单来源').click()
            expect(button(page, '确认关联订单来源')).to_be_enabled(timeout=20000)
            before_physical = self.physical(ctx, current['acquisition']['id'])
            movements = self.table_rows(('inventory_movements',))
            dropped = {}
            path = P + '/sources/confirm'
            def drop(handler):
                if handler.request.method != 'POST' or dropped:
                    handler.continue_(); return
                response = handler.fetch()
                assert response.status == 200, response.text()
                dropped.update(body=handler.request.post_data_json, result=response.json(), status=response.status)
                handler.abort('failed')
            page.route(self.base + path, drop)
            button(page, '确认关联订单来源').click()
            expect(button(page, '核对原来源操作')).to_be_enabled(timeout=20000)
            expect(button(page, '返回库存批次')).to_be_disabled()
            request_id = dropped['body']['requestId']
            assert dropped['result']['operation']['replayed'] is False
            committed = self.no_write_snapshot()
            self.capture(page, 'unknown-source-result', 390, page.get_by_test_id('inventory-source-pending'),
                         ready=('核对原来源操作',), disabled=('返回库存批次',))
            button(page, '核对原来源操作').click()
            expect(button(page, '预览解除订单来源')).to_be_enabled(timeout=20000)
            assert self.count_requests('POST', path) == 1
            assert self.count_requests('GET', P + '/operations/' + request_id) == 1
            assert self.no_write_snapshot() == committed
            assert self.physical(ctx, current['acquisition']['id']) == before_physical
            assert self.table_rows(('inventory_movements',)) == movements
            self.report['droppedSourceResponse'] = {'actualStatus': dropped['status'], 'requestId': request_id,
                'confirmPosts': 1, 'receiptGets': 1, 'noSecondMutation': True}
            page.unroute(self.base + path, drop)
            self.finish_case('committed source response loss preserves pending state and recovers by original GET, with no duplicate source or stock change')

    def changed_source_privacy(self, browser):
        with self.flow(browser) as (ctx, page):
            self.stage('Private source on shared inventory; official source changes/deletion require explicit detach')
            shop, order = self.prepare_order(ctx)
            current = self.prepare_existing(ctx, shop)
            uid = current['acquisition']['id']
            self.open_order(page, order)
            self.choose_existing(page, current)
            button(page, '预览关联订单来源').click()
            button(page, '确认关联订单来源').click()
            expect(button(page, '预览解除订单来源')).to_be_enabled(timeout=20000)
            assert self.protected() == self.protected_before
            physical = self.physical(ctx, uid)
            partner = self.context(browser, 2)
            try:
                shared = self.get(partner, P + '/acquisitions/' + uid)
                assert not {'order', 'orderId', 'source', 'lineKey', 'sourceLinkId'} & set(shared['acquisition'])
                self.get(partner, P + '/orders/' + order['id'], 404)
                self.get(partner, P + '/acquisitions/' + uid + '/source', 403)
                partner_page = partner.new_page()
                self.open_source(partner_page, shop)
                button(partner_page, '处理关联批次 ' + uid).click()
                expect(button(partner_page, '编辑批次')).to_be_enabled(timeout=20000)
                expect(partner_page.get_by_text(ORDER_TITLE, exact=True)).to_have_count(0)
                expect(partner_page.get_by_test_id('inventory-source-current')).to_have_count(0)
                changed = self.write(ctx, 'PATCH', '/api/finance-hub/transactions/' + order['id'],
                    {'revision': order['revision'], 'category': '本人主动修改分类'})
                # Deliberate external-source mutation is separate from the
                # inventory assertions; record it and establish the next baseline.
                self.report['sourceSetupMutations'] = [{'method': 'PATCH', 'id': order['id'], 'revision': changed['revision']}]
                self.protected_before = self.protected()
                button(page, '返回库存批次').click()
                button(page, '查看本人订单来源').click()
                expect(page.get_by_text('原订单来源待核对', exact=True)).to_be_visible(timeout=20000)
                value = self.get(ctx, P + '/acquisitions/' + uid + '/source')
                assert value['link']['state'] == 'needs_review' and value['link']['line'] is None
                self.capture(page, 'changed-private-source', 390, page.get_by_test_id('inventory-source-current'),
                             ready=('预览解除订单来源',))
                assert self.protected() == self.protected_before and self.physical(ctx, uid) == physical
                self.write(ctx, 'DELETE', '/api/finance-hub/transactions/' + order['id'], {'revision': changed['revision']})
                self.report['sourceSetupMutations'].append({'method': 'DELETE', 'id': order['id']})
                self.protected_before = self.protected()
                value = self.get(ctx, P + '/acquisitions/' + uid + '/source')
                assert 'source_missing' in value['link']['reviewReasons']
                button(page, '预览解除订单来源').click()
                expect(button(page, '确认解除订单来源')).to_be_enabled(timeout=20000)
                button(page, '确认解除订单来源').click()
                expect(button(page, '返回库存批次')).to_be_enabled(timeout=20000)
                value = self.get(ctx, P + '/acquisitions/' + uid + '/source')
                assert value['link']['state'] == 'detached' and value['link']['status'] == 'detached'
                assert self.physical(ctx, uid) == physical
                assert self.query('SELECT status,count(*) FROM inventory_source_links GROUP BY status') == [('detached', 1)]
                latest = self.get(ctx, P + '/acquisitions/' + uid)
                self.write(ctx, 'PATCH', P + '/items/' + latest['item']['id'], {
                    'requestId': secrets.token_hex(16), 'revision': latest['item']['revision'],
                    'patch': {'visibility': 'private'}})
                unchanged = self.no_write_snapshot()
                shopping.fixture.visibility(partner_page, True)
                shopping.fixture.visibility(partner_page, False)
                expect(partner_page.get_by_text('这件物品已归档或不再对你可见，旧详情和草稿已清空。', exact=True)).to_be_visible(timeout=20000)
                expect(partner_page.get_by_text(current['item']['title'], exact=True)).to_have_count(0)
                self.get(partner, P + '/acquisitions/' + uid, 404)
                assert self.no_write_snapshot() == unchanged
                self.finish_case('shared stock does not expose private order sources; official source change/deletion is visible and explicit detach preserves stock and financial state')
            finally:
                partner.close()

def run_case(name, root, bundle, report, out, browser):
    folder = None
    case_out = out / name
    case_out.mkdir()
    before = tuple(len(report[key]) for key in ('checks', 'pageErrors', 'externalRequests'))
    case = {'name': name, 'passed': False, 'temporaryFixtureRemoved': False}
    try:
        with ExitStack() as lifecycle:
            folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='is-')))
            run = Run(root, bundle, folder, report, case_out, lifecycle)
            getattr(run, name)(browser)
        assert not folder.exists()
        assert tuple(len(report[key]) for key in ('checks', 'pageErrors', 'externalRequests')) == (before[0] + 1, before[1], before[2])
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--build-evidence', required=True, type=Path)
    parser.add_argument('--expected-build-evidence', required=True)
    parser.add_argument('--case', choices=('all', *CASES), default='all')
    args = parser.parse_args()
    selected = CASES if args.case == 'all' else (args.case,)
    root, bundle, evidence_path = args.source_root.resolve(), args.bundle.resolve(), args.build_evidence.resolve()
    assert sys.dont_write_bytecode and not sys.flags.optimize
    assert re.fullmatch('[a-f0-9]{40}', args.expected_head) and re.fullmatch('[a-f0-9]{64}', args.expected_build_evidence)
    def git(where, *command):
        return subprocess.check_output(['git', '--no-replace-objects', '--no-optional-locks', *command], cwd=where, text=True).strip()
    def tracked(commit):
        return set(git(root, 'ls-tree', '-r', '--name-only', commit).splitlines())
    head, author_head = git(root, 'rev-parse', 'HEAD'), git(AUTHOR, 'rev-parse', 'HEAD')
    assert head == args.expected_head and not git(root, 'status', '--porcelain=v1') and not git(AUTHOR, 'status', '--porcelain=v1')
    script_name = 'tests/browser_expo_inventory_sources_check.py'
    assert read_git_blobs(AUTHOR, author_head, [script_name])[script_name] == Path(__file__).read_bytes()
    assert sha(evidence_path) == args.expected_build_evidence
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    assert evidence['buildExit'] == 0 and evidence['bundleMarkers'] is True
    assert git(root, 'rev-parse', evidence['head'] + '^{tree}') == evidence['tree']
    subprocess.run(['git', '--no-replace-objects', 'merge-base', '--is-ancestor', evidence['head'], head], cwd=root, check=True)
    inputs = evidence['inputFiles']
    for commit in (evidence['head'], head):
        expected = {name for name in tracked(commit) if name.startswith('frontend/')
                    and name not in {'frontend/README.md', 'frontend/LICENSE', 'frontend/.gitignore'}}
        assert set(inputs) == expected, 'Incomplete Expo input manifest'
        assert {name: hashlib.sha256(raw).hexdigest() for name, raw in read_git_blobs(root, commit, inputs).items()} == inputs
    assert {name: sha(root / name) for name in inputs} == inputs
    assert file_manifest(bundle) == evidence['files'] and evidence['files']
    names = tracked(head)
    def hashes():
        return {name: sha(root / name) for name in sorted(names)}
    before = hashes()
    assert before == {name: hashlib.sha256(raw).hexdigest() for name, raw in read_git_blobs(root, head, names).items()}
    bindings = fixture_bindings(root)
    out = AUTHOR / 'test-results' / ('expo-inventory-sources-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], stages=[], pageErrors=[], externalRequests=[], screenshots=[], scenarioResults=[], scenarioFailures=[],
        head=head, tree=git(root, 'rev-parse', 'HEAD^{tree}'), buildHead=evidence['head'], buildTree=evidence['tree'], buildInputs=inputs,
        buildKind=evidence.get('kind'), buildEvidencePath=str(evidence_path), buildEvidenceSha256=sha(evidence_path),
        harnessHead=author_head, harnessSha256=sha(out / 'executed-harness.py'), sourceRoot=str(root), bundleRoot=str(bundle),
        sourceHashesBefore=before, bundleHashesBefore=file_manifest(bundle), followupFixtureBindings=bindings,
        productionWrites=0, realFinancialData=False, realCloud=False, physicalDevice=False,
        requestedScenarios=list(selected), fullSuite=args.case == 'all')
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
                for name in selected:
                    run_case(name, root, bundle, report, out, browser)
                assert not report['scenarioFailures'] and len(report['checks']) == len(selected)
                assert not report['pageErrors'] and not report['externalRequests']
                assert len(report['screenshots']) == sum(SCREENSHOT_COUNTS[name] for name in selected)
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
        report['buildEvidenceUnchanged'] = sha(evidence_path) == args.expected_build_evidence
        report['fixturesUnchanged'] = bool(report.get('fixtureHashes')) and all(
            sha(Path(path)) == report['fixtureHashes'][name] == sha(root / name)
            for name, path in report.get('fixtureActualPaths', {}).items())
        inherited = report.get('inheritedFixture')
        report['inheritedFixtureUnchanged'] = bool(inherited) and sha(Path(inherited['path'])) == inherited['sha256'] == sha(root / inherited['sourcePath'])
        report['followupFixturesUnchanged'] = all(sha(Path(value['path'])) == value['sha256'] == sha(root / name)
                                                 for name, value in bindings.items())
        report['sourceStillFrozen'] = git(root, 'rev-parse', 'HEAD') == head and not git(root, 'status', '--porcelain=v1')
        report['harnessStillFrozen'] = git(AUTHOR, 'rev-parse', 'HEAD') == author_head and not git(AUTHOR, 'status', '--porcelain=v1') and sha(Path(__file__)) == report['harnessSha256']
        report['temporaryFixtureRemoved'] = len(report['scenarioResults']) == len(selected) and all(case['temporaryFixtureRemoved'] for case in report['scenarioResults'])
        report['passed'] = report['passed'] and all(report[key] for key in ('sourceUnchanged', 'bundleUnchanged',
            'buildEvidenceUnchanged', 'fixturesUnchanged', 'inheritedFixtureUnchanged', 'followupFixturesUnchanged',
            'sourceStillFrozen', 'harnessStillFrozen', 'temporaryFixtureRemoved'))
        with (out / 'result.json').open('x', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'report': str(out / 'result.json')}), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
