"""Frozen Expo finance workflow against real local Flask, SQLite and Edge.

All financial files and households are synthetic. Browser interceptions only
delay or drop real server responses; no business endpoint is substituted.
Run only against a reviewed source commit and its independently frozen export.
"""
import argparse
import base64
from contextlib import ExitStack, closing, contextmanager
import csv
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import importlib
import io
import json
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from unittest.mock import patch
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server, WSGIRequestHandler


BASE = '/api/finance-hub'
MONTH = '2026-08'
DAY = MONTH + '-12'
FINANCE_TABLES = ('hub_transactions', 'hub_imports', 'hub_import_receipts', 'hub_reconciliations', 'hub_budgets')


class Quiet(WSGIRequestHandler):
    def log(self, *_args, **_kwargs):
        pass


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def csv_bytes(rows, headers=None):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, lineterminator='\n')
    writer.writerow(headers or ['date', 'title', 'amount', 'currency', 'flow', 'category', 'id', 'status'])
    writer.writerows(rows)
    return stream.getvalue().encode('utf-8')


def row(title, amount='100.00', flow='expense', category='购物', day=DAY, currency='CNY', external=None):
    return [day, title, amount, currency, flow, category, external or title, '成功']


def file_payload(content, source='generic', kind='payments', name='synthetic.csv'):
    return {'source': source, 'kind': kind, 'file': {
        'name': name, 'contentBase64': base64.b64encode(content).decode('ascii'), 'encoding': 'auto'}}


def button(page, name):
    return page.get_by_role('button', name=name, exact=True)


def visibility(page, hidden):
    page.evaluate('''hidden => {
      Object.defineProperty(document, 'hidden', {configurable:true, get:()=>hidden});
      Object.defineProperty(document, 'visibilityState', {configurable:true, get:()=>hidden?'hidden':'visible'});
      document.dispatchEvent(new Event('visibilitychange'));
    }''', hidden)


class Run:
    def __init__(self, root, bundle, folder, report, out, lifecycle):
        self.root, self.bundle, self.folder = root, bundle, folder
        self.report, self.out, self.lifecycle = report, out, lifecycle
        sys.path[:0] = [str(root), str(root / 'tests')]
        self.source = importlib.import_module('app')
        self.workbook = importlib.import_module('test_financial_files').workbook
        shutil.copytree(root / 'static', folder / 'static', ignore=shutil.ignore_patterns('experience'))
        shutil.copytree(bundle, folder / 'static' / 'experience')
        lifecycle.enter_context(patch.object(self.source, 'ROOT', folder))
        lifecycle.enter_context(patch.dict('os.environ', {name: '' for name in (
            'OPENAI_API_KEY', 'OPENAI_MODEL', 'NVIDIA_API_KEY', 'NVIDIA_MODEL',
            'MICROSOFT_CLIENT_ID', 'MICROSOFT_CLIENT_SECRET', 'GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET')}))
        self.cfg = {'TESTING': True, 'SECRET_KEY': 'expo-finance-synthetic-only',
            'DATA_DIR': str(folder / 'data'), 'SESSION_COOKIE_SECURE': True, 'PUBLIC_ORIGIN': 'https://127.0.0.1',
            'MEMBER1_PASSWORD': 'testing-password-one', 'MEMBER2_PASSWORD': 'testing-password-two',
            'MICROSOFT_CLIENT_ID': '', 'MICROSOFT_CLIENT_SECRET': '', 'GOOGLE_CLIENT_ID': '',
            'GOOGLE_CLIENT_SECRET': '', 'OPENAI_API_KEY': '', 'OPENAI_MODEL': '',
            'NVIDIA_API_KEY': '', 'NVIDIA_MODEL': ''}
        self.database = folder / 'data' / 'household.sqlite3'
        self.server, self.thread = None, None
        self.start()
        lifecycle.callback(self.stop)
        self.page = None
        self.requests = []
        self.child_entry = None

    def start(self, port=0):
        self.application = self.source.create_app(self.cfg)
        self.server = make_server('127.0.0.1', port, self.application, threaded=True,
                                  request_handler=Quiet, ssl_context='adhoc')
        self.base = 'https://127.0.0.1:' + str(self.server.server_port)
        self.cfg['PUBLIC_ORIGIN'] = self.base
        self.application.config['PUBLIC_ORIGIN'] = self.base
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=5)
            assert not self.thread.is_alive(), 'Local Flask listener failed to stop'
            self.server = None

    def restart(self):
        port = self.server.server_port
        self.stop()
        self.start(port)

    def passed(self, name):
        self.report['checks'].append(name)
        print('PASS ' + name, flush=True)

    def context(self, browser, member=1):
        ctx = browser.new_context(viewport={'width': 390, 'height': 844}, ignore_https_errors=True)

        def route(handler):
            parsed = urlsplit(handler.request.url)
            if (parsed.scheme, parsed.netloc) != (urlsplit(self.base).scheme, urlsplit(self.base).netloc):
                self.report['externalRequests'].append({'host': parsed.hostname, 'scheme': parsed.scheme})
                handler.abort()
                return
            handler.continue_()

        ctx.route('**/*', route)
        ctx.on('page', lambda p: p.on('pageerror', lambda error: self.report['pageErrors'].append(str(error))))
        ctx.on('request', lambda req: self.requests.append({'method': req.method,
            'path': urlsplit(req.url).path, 'query': urlsplit(req.url).query}))
        if member:
            self.login(ctx, member)
        return ctx

    def login(self, ctx, member=1):
        response = ctx.request.post(self.base + '/api/login', data={'username': f'member{member}',
            'password': 'testing-password-' + ('one' if member == 1 else 'two')})
        assert response.status == 200, response.text()

    def get(self, ctx, path, status=200):
        response = ctx.request.get(self.base + path)
        assert response.status == status, (path, response.status, response.text())
        return response.json()

    def write(self, ctx, method, path, body, status=200):
        csrf = self.get(ctx, '/api/me')['csrf']
        response = ctx.request.fetch(self.base + path, method=method, data=body,
            headers={'X-CSRF-Token': csrf, 'Origin': self.base})
        assert response.status == status, (path, response.status, response.text())
        return response.json()

    def overview(self, ctx, month=MONTH):
        return self.get(ctx, BASE + '/overview?month=' + month)

    def seed(self, ctx, rows, source='generic', kind='payments'):
        # Setup only. User-facing import acceptance uses the file picker.
        value = file_payload(csv_bytes(rows), source, kind)
        preview = self.write(ctx, 'POST', BASE + '/imports/preview', value)
        assert preview['previewToken'] and not preview['errorCount']
        return self.write(ctx, 'POST', BASE + '/imports/confirm', {**value, 'previewToken': preview['previewToken']})

    def snapshot(self):
        with closing(sqlite3.connect(self.database)) as con:
            return {name: sorted(con.execute('SELECT * FROM "' + name + '"').fetchall(), key=repr)
                    for name in FINANCE_TABLES + ('audit',)}

    def raw_transactions(self):
        with closing(sqlite3.connect(self.database)) as con:
            return dict(con.execute('SELECT id,data FROM hub_transactions'))

    def clear_finance(self):
        # A test-fixture reset, restricted to this newly created temporary DB.
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database)) as con:
            for table in ('hub_reconciliations', 'hub_import_receipts', 'hub_transactions', 'hub_imports', 'hub_budgets'):
                con.execute('DELETE FROM "' + table + '"')
            con.commit()

    @contextmanager
    def flow(self, browser):
        self.clear_finance()
        ctx = self.context(browser)
        page = ctx.new_page()
        self.page = page
        try:
            yield ctx, page
        except Exception:
            if not page.is_closed():
                try:
                    page.screenshot(path=str(self.out / 'failure.png'), full_page=True)
                    (self.out / 'failure-aria.txt').write_text(page.locator('body').aria_snapshot(), encoding='utf-8')
                except Exception:
                    pass
            raise
        finally:
            ctx.close()

    def open_finance(self, page):
        page.goto(self.base + '/app/finance')
        expect(page.get_by_role('heading', name='家庭资金', exact=True)).to_be_visible(timeout=15000)

    def ledger(self, page, month=MONTH):
        detail = page.get_by_role('heading', name='交易详情', exact=True)
        if detail.count() and detail.is_visible():
            expect(button(page, '返回账本')).to_be_enabled()
            button(page, '返回账本').click()
        button(page, '我的账本').click()
        page.get_by_role('textbox', name='账本月份', exact=True).fill(month)
        button(page, '查看月份').click()
        expect(button(page, '刷新账本')).to_be_enabled()

    def transaction(self, page, title):
        button(page, '查看交易' + title).click()
        expect(page.get_by_role('textbox', name='交易分类', exact=True)).to_be_visible()

    def open_import(self, page, content, source='generic', kind='payments', name='synthetic.csv'):
        button(page, '导入账单').click()
        expect(button(page, '选择账单文件')).to_be_visible()
        if source != 'generic':
            button(page, '文件来源：通用表格').click()
            page.get_by_text({'alipay': '支付宝', 'wechat': '微信', 'taobao': '淘宝', 'pinduoduo': '拼多多'}[source], exact=True).click()
        if kind == 'orders':
            button(page, '订单记录').click()
        self.choose_file(page, content, name)

    @staticmethod
    def choose_file(page, content, name):
        with page.expect_file_chooser() as chosen:
            button(page, '选择账单文件').click()
        chosen.value.set_files({'name': name, 'mimeType': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                               if name.endswith('.xlsx') else 'text/csv', 'buffer': content})
        expect(page.get_by_text(name, exact=True)).to_be_visible()

    def preview_file(self, page, action='预览文件'):
        with page.expect_response(lambda response: urlsplit(response.url).path == BASE + '/imports/preview'
                                  and response.request.method == 'POST') as pending:
            button(page, action).click()
        response = pending.value
        assert response.status == 200, response.text()
        result = response.json()
        if result['requiresSheetSelection']:
            expect(button(page, '选择账单工作表')).to_be_enabled()
        elif result['requiresAmountSelection']:
            expect(button(page, '选择入账金额列')).to_be_enabled()
        else:
            expect(page.get_by_role('heading', name='核对预览', exact=True)).to_be_visible()
            if result['rows']:
                expect(page.get_by_test_id('finance-import-row-' + str(result['rows'][0]['line']))).to_be_visible()
            if result['errorCount'] or not result['rows']:
                expect(button(page, '确认导入 · 仅本人')).to_be_disabled()
            else:
                expect(button(page, '确认导入 · 仅本人')).to_be_enabled()
        expect(page.get_by_label('正在处理文件', exact=True)).to_have_count(0)
        return result

    def confirm_file(self, page):
        with page.expect_response(lambda response: urlsplit(response.url).path == BASE + '/imports/confirm'
                                  and response.request.method == 'POST') as pending:
            button(page, '确认导入 · 仅本人').click()
        response = pending.value
        assert response.status == 200, response.text()
        result = response.json()
        expect(button(page, '查看已导入账本')).to_be_enabled()
        return result

    def enter_receipt_ledger(self, page):
        button(page, '查看已导入账本').click()
        expect(button(page, '刷新账本')).to_be_enabled()

    def import_file(self, page, content, source='generic', kind='payments', name='synthetic.csv'):
        self.open_import(page, content, source, kind, name)
        preview = self.preview_file(page)
        assert preview['previewToken'] and not preview['errorCount']
        result = self.confirm_file(page)
        self.enter_receipt_ledger(page)
        return preview, result

    @staticmethod
    def total(overview, currency='CNY'):
        return next(value for value in overview['totals'] if value['currency'] == currency)

    @staticmethod
    def find(overview, title):
        return next(value for value in overview['transactions'] if value['title'] == title)

    @staticmethod
    def settle(page, check, timeout=15000):
        # Let real browser events advance while checking an authoritative state.
        deadline = time.monotonic() + timeout / 1000
        while time.monotonic() < deadline:
            if check():
                return
            page.wait_for_timeout(50)
        raise AssertionError('Expected asynchronous operation did not settle')

    def count_requests(self, method, path):
        return sum(req['method'] == method and req['path'] == path for req in self.requests)

    def screenshot(self, page, name, width, dialog=False):
        page.set_viewport_size({'width': width, 'height': 1000 if width >= 1040 else 844})
        page.evaluate('() => document.fonts.ready')
        if dialog:
            page.wait_for_function('''() => {
              const nodes=[...document.querySelectorAll('[data-testid="modal-surface"]')]
                .filter(e=>e.getBoundingClientRect().width>0&&e.getBoundingClientRect().height>0);
              return nodes.length===1&&nodes.every(e=>{
                for(let n=e;n;n=n.parentElement)if(Number(getComputedStyle(n).opacity)!==1)return false;
                return true;
              });
            }''')
        page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
        metrics = page.evaluate('''() => ({width:innerWidth,scroll:document.documentElement.scrollWidth,
          clipped:[...document.querySelectorAll('input,button,[role="button"],[role="checkbox"]')]
          .filter(e=>{const r=e.getBoundingClientRect();
            let scrolled=false;for(let n=e.parentElement;n&&n!==document.body;n=n.parentElement){
              const s=getComputedStyle(n),b=n.getBoundingClientRect();
              if(['auto','scroll'].includes(s.overflowX)&&n.scrollWidth>n.clientWidth&&b.right<=innerWidth+2&&b.left>=-2){scrolled=true;break;}}
            return !scrolled&&r.width>0&&r.height>0&&getComputedStyle(e).visibility!=='hidden'
            &&r.right>innerWidth+2&&r.left<innerWidth;})
          .map(e=>({label:e.getAttribute('aria-label')||e.innerText,left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right}))})''')
        assert metrics['scroll'] <= width + 2 and not metrics['clipped'], metrics
        path = self.out / f'{name}-{width}.png'
        page.screenshot(path=str(path), full_page=True)
        self.report['screenshots'].append({'path': path.name, 'sha256': sha(path), 'metrics': metrics})

    def run_scenarios(self, browser):
        self.shared_funds(browser)
        self.import_and_provenance(browser)
        self.amount_and_sheets(browser)
        self.cancel_and_read_failure(browser)
        self.unknown_receipt(browser)
        self.ledger_pagination(browser)
        self.reconciliation_loop(browser)
        self.version_conflicts(browser)
        self.private_boundaries(browser)
        self.async_boundaries(browser)

    def shared_funds(self, browser):
        with self.flow(browser) as (ctx, page):
            original = self.get(ctx, '/api/state')['finance']
            amounts = {'wallet': 1000000, 'livingBudget': 620000, 'livingSpent': 12345,
                'travelSaved': 340000, 'travelAnnualBudget': 15000000, 'longterm': 456789,
                'reserveTarget': 1000000, 'upcomingPayments': 89123}
            initial = {**amounts, 'contributionPercent': 50, 'note': '合成共享资金核对', 'revision': original['revision']}
            self.write(ctx, 'PUT', '/api/finance', initial)
            before = self.snapshot()
            self.open_finance(page)
            expect(page.get_by_text('CNY 10,000.00', exact=True).first).to_be_visible()
            button(page, '核对资金').click()
            wallet = page.get_by_role('textbox', name='荷包余额', exact=True)
            expect(wallet).to_have_value('10000.00')
            wallet.fill('123.45')
            self.screenshot(page, 'shared-funds-editor', 320, dialog=True)
            with page.expect_response(lambda response: urlsplit(response.url).path == '/api/finance'
                and response.request.method == 'PUT') as saved:
                button(page, '确认共同资金').click()
            assert saved.value.status == 200, saved.value.text()
            submitted = saved.value.request.post_data_json
            assert submitted['wallet'] == 12345 and type(submitted['wallet']) is int
            for field, value in amounts.items():
                if field != 'wallet':
                    assert submitted[field] == value and type(submitted[field]) is int
            assert submitted['contributionPercent'] == 50 and type(submitted['contributionPercent']) is int
            expect(button(page, '确认共同资金')).not_to_be_visible()
            stored = self.get(ctx, '/api/state')['finance']
            assert stored['wallet'] == 12345
            assert self.snapshot()['hub_transactions'] == before['hub_transactions']
            button(page, '核对资金').click()
            wallet.fill('200.00')
            self.write(ctx, 'PUT', '/api/finance', {**{k: stored[k] for k in initial}, 'wallet': 30000})
            with page.expect_response(lambda response: urlsplit(response.url).path == '/api/finance'
                and response.request.method == 'PUT') as changed:
                button(page, '确认共同资金').click()
            assert changed.value.status == 409
            expect(wallet).to_have_value('200.00')
            expect(button(page, '确认共同资金')).to_be_disabled()
            button(page, '读取最新资金').click()
            expect(wallet).to_have_value('300.00')
            expect(button(page, '确认共同资金')).to_be_enabled()
            button(page, '取消').click()
            assert self.get(ctx, '/api/state')['finance']['wallet'] == 30000
            self.passed('Shared funds display exact cents as yuan, preserve all eight integer-cent fields and integer contribution, write only on confirmation and recover a real revision conflict')

    def import_and_provenance(self, browser):
        with self.flow(browser) as (ctx, page):
            self.open_finance(page)
            content = csv_bytes([row('合成手冲咖啡', '12.34', category='餐饮', external='coffee-import-001')])
            self.open_import(page, content, name='synthetic-coffee.csv')
            before = self.snapshot()
            preview = self.preview_file(page)
            assert preview['newCount'] == 1 and not preview['errorCount'] and preview['rows'][0]['amountCents'] == 1234
            assert self.snapshot() == before, 'Import preview wrote to business or audit tables'
            for width in (320, 390, 1040, 1440):
                self.screenshot(page, 'import-preview', width)
            # Picking another file invalidates the old signed preview immediately.
            page.evaluate('''() => {
              const original = File.prototype.arrayBuffer;
              File.prototype.arrayBuffer = function() {
                if (this.name !== 'synthetic-coffee-reselected.csv') return original.call(this);
                const file = this;
                return new Promise(resolve => { window.releaseFinanceFile = async () => {
                  File.prototype.arrayBuffer = original; resolve(await original.call(file));
                }; });
              };
            }''')
            with page.expect_file_chooser() as replacement:
                button(page, '选择账单文件').click()
            replacement.value.set_files({'name': 'synthetic-coffee-reselected.csv', 'mimeType': 'text/csv', 'buffer': content})
            page.wait_for_function('() => typeof window.releaseFinanceFile === "function"')
            expect(button(page, '确认导入 · 仅本人')).to_have_count(0)
            expect(button(page, '选择账单文件')).to_be_disabled()
            assert self.snapshot() == before
            page.evaluate('() => window.releaseFinanceFile()')
            expect(page.get_by_text('synthetic-coffee-reselected.csv', exact=True)).to_be_visible()
            preview = self.preview_file(page)
            assert preview['previewToken']
            with page.expect_file_chooser() as invalid:
                button(page, '选择账单文件').click()
            invalid.value.set_files({'name': 'synthetic-empty.csv', 'mimeType': 'text/csv', 'buffer': b''})
            expect(page.locator('body')).to_contain_text('请选择非空且不超过 2 MiB 的文件。')
            expect(button(page, '确认导入 · 仅本人')).to_have_count(0)
            assert self.snapshot() == before
            self.choose_file(page, content, 'synthetic-coffee-reselected.csv')
            self.preview_file(page)
            posts = self.count_requests('POST', BASE + '/imports/confirm')
            result = self.confirm_file(page)
            assert result['imported'] == 1 and result['duplicates'] == 0 and result['conflicts'] == 0
            assert re.fullmatch('[0-9a-f]{32,64}', result['requestId']) and re.fullmatch('[0-9a-f]{64}', result['receiptId'])
            assert re.fullmatch('[0-9a-f]{24}', result['batchId'])
            assert result['resultMonths'] == [{'month': MONTH, 'recordCount': 1}]
            assert self.count_requests('POST', BASE + '/imports/confirm') == posts + 1
            stored = self.find(self.overview(ctx), '合成手冲咖啡')
            provenance = stored['provenance']
            assert provenance == {'status': 'recorded', 'batchId': result['batchId'], 'source': 'generic',
                'kind': 'payments', 'fileName': 'synthetic-coffee-reselected.csv', 'format': 'csv',
                'sheet': None, 'lineStart': 2, 'lineEnd': 2, 'lineKind': 'csv_lines', 'importedAt': stored['importedAt']}
            receipt = self.get(ctx, BASE + '/imports/results/' + result['requestId'])
            assert receipt['replayed'] and receipt['receiptId'] == result['receiptId'] and receipt['batchId'] == provenance['batchId']
            self.enter_receipt_ledger(page)
            expect(button(page, '查看交易合成手冲咖啡')).to_be_visible()
            expect(page.get_by_role('textbox', name='账本月份', exact=True)).to_have_value(MONTH)
            self.transaction(page, '合成手冲咖啡')
            expect(page.locator('body')).to_contain_text('synthetic-coffee-reselected.csv')
            expect(page.locator('body')).to_contain_text(result['batchId'])
            before_restart = self.overview(ctx)
            self.restart()
            self.open_finance(page)
            self.ledger(page)
            assert self.overview(ctx)['transactions'] == before_restart['transactions']
            expect(button(page, '查看交易合成手冲咖啡')).to_be_visible()
            self.passed('UI file preview and file replacement are stateless; one explicit confirmation persists exact cents, batch/line provenance and survives real Flask restart')

            _, duplicate = self.import_file(page, content, name='synthetic-coffee-reselected.csv')
            assert duplicate['imported'] == 0 and duplicate['duplicates'] == 1 and duplicate['conflicts'] == 0
            assert duplicate['requestId'] != result['requestId'] and duplicate['batchId'] is None
            conflict = csv_bytes([row('合成拟修改咖啡', '99.00', category='餐饮', day='2026-06-01', external='coffee-import-001')])
            _, changed = self.import_file(page, conflict, name='synthetic-coffee-conflict.csv')
            assert changed['imported'] == 0 and changed['conflicts'] == 1
            assert changed['resultMonths'] == [{'month': MONTH, 'recordCount': 1}]
            current = self.overview(ctx)
            assert current['totalRecordCount'] == 1 and current['transactions'][0]['amountCents'] == 1234
            assert current['transactions'][0]['provenance'] == provenance
            assert len(self.snapshot()['hub_imports']) == 1
            expect(page.get_by_role('textbox', name='账本月份', exact=True)).to_have_value(MONTH)
            self.passed('New explicit repeated import is deduplicated; changed same-ID amount/date retains old amount, batch provenance and actual result month')

            self.open_import(page, csv_bytes([row('合成七月记录', '1.00', day='2026-07-03'), row('合成八月记录', '2.00')]))
            assert self.preview_file(page)['newCount'] == 2
            multiple = self.confirm_file(page)
            assert multiple['resultMonths'] == [{'month': MONTH, 'recordCount': 1}, {'month': '2026-07', 'recordCount': 1}]
            self.enter_receipt_ledger(page)
            posts = self.count_requests('POST', BASE + '/imports/confirm')
            button(page, '2026-07 · 1 笔').click()
            expect(button(page, '查看交易合成七月记录')).to_be_visible()
            assert self.overview(ctx, '2026-07')['transactionCount'] == 1
            assert self.count_requests('POST', BASE + '/imports/confirm') == posts
            self.passed('Cross-month import preserves separate actual months; ledger navigation reads the selected month without confirming again')

    def amount_and_sheets(self, browser):
        with self.flow(browser) as (ctx, page):
            self.open_finance(page)
            self.open_import(page, csv_bytes([row('合成无效金额', '1,23')]), name='synthetic-invalid-amount.csv')
            before = self.snapshot()
            bad = self.preview_file(page)
            assert bad['errorCount'] == 1 and not bad['previewToken']
            expect(button(page, '确认导入 · 仅本人')).to_be_disabled()
            assert self.snapshot() == before
            workbook = self.workbook(rows=[['date', 'title', 'amount', 'amount', 'currency', 'flow', 'category', 'id', 'status'],
                [DAY, '合成双金额工作表', '9.00', '1,234.56', 'CNY', 'expense', '测试', 'sheet-amount-001', '成功']], second_sheet=True)
            self.choose_file(page, workbook, 'synthetic-two-sheets.xlsx')
            sheets = self.preview_file(page)
            assert sheets['requiresSheetSelection'] and not sheets['previewToken']
            button(page, '选择账单工作表').click()
            page.get_by_text('支付账单', exact=True).last.click()
            amounts = self.preview_file(page, '读取所选工作表')
            assert amounts['requiresAmountSelection'] and not amounts['previewToken']
            assert self.snapshot() == before
            button(page, '选择入账金额列').click()
            page.get_by_text(re.compile(r'^D 列')).click()
            parsed = self.preview_file(page, '按所选金额预览')
            assert parsed['rows'][0]['amountCents'] == 123456 and parsed['previewToken']
            assert self.snapshot() == before
            result = self.confirm_file(page)
            self.enter_receipt_ledger(page)
            current = self.overview(ctx)['transactions'][0]
            assert current['amountCents'] == 123456 and current['provenance']['sheet'] == '支付账单'
            assert current['provenance']['format'] == 'xlsx' and current['provenance']['lineKind'] == 'worksheet_rows'
            assert current['provenance']['batchId'] == result['batchId']
            self.passed('Malformed amount blocks the whole file; XLSX sheet and duplicate amount-column selection remain read-only and chosen grouped amount persists as integer cents')

    def cancel_and_read_failure(self, browser):
        with self.flow(browser) as (ctx, page):
            self.open_finance(page)
            content = csv_bytes([row('合成取消预览', '3.00')])
            self.open_import(page, content)
            before = self.snapshot()
            self.preview_file(page)
            button(page, '返回账本').click()
            expect(page.get_by_text('返回账本？', exact=True)).to_be_visible()
            self.screenshot(page, 'cancel-import', 320, dialog=True)
            button(page, '返回账本').last.click()
            expect(page.get_by_test_id('finance-import-panel')).to_have_count(0)
            assert self.snapshot() == before
            self.passed('Leaving an unconfirmed import requires explicit discard and preserves the complete financial/audit snapshot')

            self.open_import(page, content)
            self.preview_file(page)
            known = self.confirm_file(page)
            assert known['imported'] == 1
            posts = self.count_requests('POST', BASE + '/imports/confirm')
            dropped = []

            def lose_overview(handler):
                if not dropped:
                    response = handler.fetch(max_redirects=0)
                    assert response.status == 200
                    dropped.append(response.status)
                    handler.abort('failed')
                else:
                    handler.continue_()

            page.route(self.base + BASE + '/overview?*', lose_overview)
            button(page, '查看已导入账本').click()
            self.settle(page, lambda: bool(dropped))
            expect(button(page, '刷新账本')).to_be_enabled()
            page.unroute(self.base + BASE + '/overview?*', lose_overview)
            stored = self.overview(ctx)['transactions'][0]
            self.write(ctx, 'DELETE', BASE + '/transactions/' + stored['id'], {'revision': stored['revision']})
            button(page, '刷新账本').click()
            expect(button(page, '导入账单')).to_be_enabled()
            assert self.overview(ctx)['totalRecordCount'] == 0
            assert self.count_requests('POST', BASE + '/imports/confirm') == posts
            assert self.get(ctx, BASE + '/imports/results/' + known['requestId'])['imported'] == 1
            expect(button(page, '查看交易合成取消预览')).to_have_count(0)
            self.passed('Known confirmation followed by a lost real overview response retries only reads; later deletion stays deleted while the immutable receipt preserves its historical result')

    def unknown_receipt(self, browser):
        with self.flow(browser) as (ctx, page):
            self.open_finance(page)
            content = csv_bytes([row('合成确认回执', '17.00')])
            self.open_import(page, content, name='synthetic-receipt.csv')
            assert self.preview_file(page)['previewToken']
            dropped = {}

            def drop_commit(handler):
                if handler.request.method == 'POST' and not dropped:
                    dropped['body'] = handler.request.post_data_json
                    response = handler.fetch(max_redirects=0)
                    assert response.status == 200, response.text()
                    dropped['result'] = response.json()
                    handler.abort('failed')
                else:
                    handler.continue_()

            start_posts = self.count_requests('POST', BASE + '/imports/confirm')
            page.route(self.base + BASE + '/imports/confirm', drop_commit)
            button(page, '确认导入 · 仅本人').click()
            expect(button(page, '核对保存结果')).to_be_enabled()
            page.unroute(self.base + BASE + '/imports/confirm', drop_commit)
            assert dropped and self.overview(ctx)['totalRecordCount'] == 1
            assert self.count_requests('POST', BASE + '/imports/confirm') == start_posts + 1
            with page.expect_response(lambda response: urlsplit(response.url).path == BASE + '/imports/results/' + dropped['body']['requestId']) as readback:
                button(page, '核对保存结果').click()
            assert readback.value.status == 200 and readback.value.json()['receiptId'] == dropped['result']['receiptId']
            expect(button(page, '查看已导入账本')).to_be_enabled()
            assert self.count_requests('POST', BASE + '/imports/confirm') == start_posts + 1
            original = self.overview(ctx)['transactions'][0]
            self.write(ctx, 'DELETE', BASE + '/transactions/' + original['id'], {'revision': original['revision']})
            replay = self.write(ctx, 'POST', BASE + '/imports/confirm', dropped['body'])
            assert replay['replayed'] and replay['receiptId'] == dropped['result']['receiptId']
            assert self.overview(ctx)['totalRecordCount'] == 0
            self.enter_receipt_ledger(page)
            expect(button(page, '查看交易合成确认回执')).to_have_count(0)
            _, new_import = self.import_file(page, content, name='synthetic-receipt.csv')
            assert new_import['requestId'] != dropped['body']['requestId'] and new_import['imported'] == 1
            assert self.overview(ctx)['totalRecordCount'] == 1
            self.report['droppedConfirm'] = {'actualServerCommit': True, 'browserPostsBeforeReadback': 1,
                'readbackOnlyGet': True, 'sameRequestAfterDeletionReplayedWithoutResurrection': True}
            self.passed('Lost real committed confirmation is resolved by GET receipt only; exact old request cannot resurrect a deleted row, while a new explicit import can')

        with self.flow(browser) as (ctx, page):
            self.open_finance(page)
            self.open_import(page, csv_bytes([row('合成未送达请求', '23.00')]))
            self.preview_file(page)
            blocked = []

            def drop_before_send(handler):
                if handler.request.method == 'POST' and not blocked:
                    blocked.append(handler.request.post_data_json)
                    handler.abort('failed')
                else:
                    handler.continue_()

            page.route(self.base + BASE + '/imports/confirm', drop_before_send)
            button(page, '确认导入 · 仅本人').click()
            expect(button(page, '核对保存结果')).to_be_enabled()
            page.unroute(self.base + BASE + '/imports/confirm', drop_before_send)
            assert self.overview(ctx)['totalRecordCount'] == 0
            with page.expect_response(lambda response: urlsplit(response.url).path == BASE + '/imports/results/' + blocked[0]['requestId']) as missing:
                button(page, '核对保存结果').click()
            assert missing.value.status == 404 and missing.value.json()['code'] == 'import_result_not_found'
            expect(button(page, '使用原请求重试')).to_be_enabled()
            with page.expect_response(lambda response: urlsplit(response.url).path == BASE + '/imports/confirm') as retry:
                button(page, '使用原请求重试').click()
            assert retry.value.status == 200
            assert retry.value.request.post_data_json == blocked[0], 'Retry must preserve exact payload, request ID and preview token'
            expect(button(page, '查看已导入账本')).to_be_enabled()
            assert self.overview(ctx)['totalRecordCount'] == 1
            self.passed('Unsent request stays unknown until explicit GET; missing receipt allows only an explicit byte-equivalent logical request retry and saves once')

        with self.flow(browser) as (ctx, page):
            self.open_finance(page)
            self.open_import(page, csv_bytes([row('合成迟到原请求', '31.00')]))
            self.preview_file(page)
            delayed = []

            def delay_submission(handler):
                delayed.append(handler.request.post_data_json)
                handler.abort('failed')

            page.route(self.base + BASE + '/imports/confirm', delay_submission)
            button(page, '确认导入 · 仅本人').click()
            expect(button(page, '核对保存结果')).to_be_enabled()
            page.unroute(self.base + BASE + '/imports/confirm', delay_submission)
            button(page, '核对保存结果').click()
            expect(button(page, '使用原请求重试')).to_be_enabled()
            # Advance the real token validator's clock, never substitute a response.
            from itsdangerous.timed import TimestampSigner
            original_clock = TimestampSigner.get_timestamp
            with patch.object(TimestampSigner, 'get_timestamp', lambda signer: original_clock(signer)
                + (1300 if signer.salt == b'household-finance-preview-v1' else 0)):
                with page.expect_response(lambda response: urlsplit(response.url).path == BASE + '/imports/confirm') as expired:
                    button(page, '使用原请求重试').click()
                assert expired.value.status == 400
                assert expired.value.request.post_data_json == delayed[0]
                expect(button(page, '核对保存结果')).to_be_enabled()
            assert self.overview(ctx)['totalRecordCount'] == 0
            # Deliver the preserved request after the failed retry. The live API
            # validates and persists it; GET must still recover that exact ID.
            committed = self.write(ctx, 'POST', BASE + '/imports/confirm', delayed[0])
            with page.expect_response(lambda response: urlsplit(response.url).path == BASE + '/imports/results/' + delayed[0]['requestId']) as recovered:
                button(page, '核对保存结果').click()
            assert recovered.value.status == 200 and recovered.value.json()['receiptId'] == committed['receiptId']
            expect(button(page, '查看已导入账本')).to_be_enabled()
            assert self.overview(ctx)['totalRecordCount'] == 1
            self.passed('A real expired-token retry cannot discard the unknown request identity; later delivery of the preserved request remains recoverable through its exact GET receipt')

    def ledger_pagination(self, browser):
        with self.flow(browser) as (ctx, page):
            self.seed(ctx, [row(f'合成分页流水 {index:04d}', '1.00') for index in range(550)])
            deep_title = '合成深层订单：家庭旅行用品及非常长的商品名称与规格，仅供跨屏排版和第 500 条以后搜索验证'
            self.seed(ctx, [row(deep_title, '10.00', day='2026-08-01')], kind='orders')
            data = self.overview(ctx)
            assert data['truncated'] and len(data['transactions']) == 500 and data['transactionCount'] == 551
            assert self.total(data)['netSpendCents'] == 55000 and self.total(data)['orderCents'] == 1000
            self.open_finance(page)
            self.ledger(page)
            expect(page.locator('[data-testid^="finance-transaction-"]')).to_have_count(25)
            search = page.get_by_role('textbox', name='搜索账本', exact=True)
            search.fill('合成深层订单')
            with page.expect_response(lambda response: urlsplit(response.url).path == BASE + '/transactions') as searched:
                button(page, '搜索').click()
            assert searched.value.status == 200 and searched.value.json()['filteredCount'] == 1
            expect(button(page, '查看交易' + deep_title)).to_be_visible()
            for width in (320, 390, 1040, 1440):
                self.screenshot(page, 'ledger-search', width)
            search.fill('')
            button(page, '搜索').click()
            expect(page.locator('[data-testid^="finance-transaction-"]')).to_have_count(25)
            with page.expect_response(lambda response: urlsplit(response.url).path == BASE + '/transactions') as next_page:
                button(page, '下一页').click()
            assert next_page.value.status == 200 and next_page.value.json()['page'] == 2
            assert 'snapshot=' in next_page.value.request.url
            retained = next_page.value.json()['transactions'][0]
            self.write(ctx, 'PATCH', BASE + '/transactions/' + retained['id'], {'revision': retained['revision'], 'category': '合成其他标签页修改'})
            with page.expect_response(lambda response: urlsplit(response.url).path == BASE + '/transactions') as changed:
                button(page, '下一页').click()
            assert changed.value.status == 409 and changed.value.json()['code'] == 'ledger_changed'
            expect(page.locator('[data-testid^="finance-transaction-"]')).to_have_count(0)
            expect(page.locator('body')).to_contain_text('账本已变化')
            with page.expect_response(lambda response: urlsplit(response.url).path == BASE + '/transactions') as refreshed:
                button(page, '刷新账本').click()
            assert refreshed.value.status == 200 and 'snapshot=' not in refreshed.value.request.url
            assert self.total(self.overview(ctx))['netSpendCents'] == 55000
            self.passed('Actual 551-row ledger searches beyond overview limit, carries paging snapshot, refuses mixed versions and explicitly refreshes while full-month totals remain complete')

    def make_budget(self, page, amount='100.00', currency='CNY', category='购物'):
        button(page, '月预算').click()
        button(page, '新增预算').click()
        for name, value in (('预算月份', MONTH), ('预算币种', currency), ('预算分类', category), ('预算金额', amount)):
            page.get_by_role('textbox', name=name, exact=True).fill(value)
        with page.expect_response(lambda response: urlsplit(response.url).path == BASE + '/budgets' and response.request.method == 'PUT') as saved:
            button(page, '保存预算').click()
        assert saved.value.status == 200, saved.value.text()
        expect(page.get_by_test_id(f'finance-budget-{currency}-{category}')).to_be_visible()

    def reconciliation_loop(self, browser):
        with self.flow(browser) as (ctx, page):
            self.open_finance(page)
            self.ledger(page)
            # These four records are introduced through the actual UI, rather
            # than API seeding, so the main import -> reconciliation path is real.
            for title, amount, flow, source, kind, category in (
                ('合成订单100', '100.00', 'expense', 'taobao', 'orders', '购物'),
                ('合成付款100', '100.00', 'expense', 'generic', 'payments', '购物'),
                ('合成重复付款100', '100.00', 'expense', 'alipay', 'payments', '购物'),
                ('合成退款30', '30.00', 'refund', 'generic', 'payments', '原退款分类')):
                _, result = self.import_file(page, csv_bytes([row(title, amount, flow, category)]), source, kind, title + '.csv')
                assert result['imported'] == 1
            original = self.raw_transactions()
            data = self.overview(ctx)
            assert data['transactionCount'] == 4 and self.total(data)['netSpendCents'] == 17000
            self.make_budget(page)
            self.ledger(page)
            linked = {}
            for kind, left_title, amount in (('duplicate', '合成重复付款100', '100.00'),
                    ('order_payment', '合成订单100', '100.00'), ('refund_payment', '合成退款30', '30.00')):
                data = self.overview(ctx)
                left, right = self.find(data, left_title), self.find(data, '合成付款100')
                self.transaction(page, left_title)
                button(page, '查找关联').click()
                candidate = page.get_by_test_id(f"finance-candidate-{kind}-{left['id']}-{right['id']}")
                expect(candidate).to_be_visible()
                candidate.get_by_role('button', name='核对这组记录', exact=True).click()
                amount_field = page.get_by_role('textbox', name='分配金额', exact=True)
                if kind != 'duplicate':
                    amount_field.fill(amount)
                before = self.snapshot()
                with page.expect_response(lambda response: urlsplit(response.url).path == BASE + '/reconciliation/preview') as planned:
                    button(page, '预览关联').click()
                assert planned.value.status == 200 and planned.value.json()['amountCents'] == int(Decimal(amount) * 100)
                assert self.snapshot() == before, 'Reconciliation preview wrote to the database'
                expect(button(page, '确认关联')).to_be_enabled()
                if kind == 'refund_payment':
                    for width in (320, 390, 1040, 1440):
                        self.screenshot(page, 'refund-confirmation', width, dialog=True)
                with page.expect_response(lambda response: urlsplit(response.url).path == BASE + '/reconciliation/confirm') as confirmed:
                    button(page, '确认关联').click()
                assert confirmed.value.status == 200
                linked[kind] = confirmed.value.json()['relation']
                expect(button(page, '确认关联')).not_to_be_visible()
                replay = self.write(ctx, 'POST', BASE + '/reconciliation/confirm', {'previewToken': planned.value.json()['previewToken']})
                assert replay['replayed'] and replay['relation']['id'] == linked[kind]['id']
                self.ledger(page)
            final = self.overview(ctx)
            assert final['transactionCount'] == 4
            assert self.total(final)['netSpendCents'] == 7000 and self.total(final)['orderCents'] == 10000
            assert self.total(final)['duplicateCount'] == 1 and self.total(final)['categories']['购物'] == 7000
            budget = next(value for value in final['budgets'] if value['category'] == '购物' and value['currency'] == 'CNY')
            assert budget['amountCents'] == 10000 and budget['spentCents'] == 7000 and budget['remainingCents'] == 3000
            payment = self.find(final, '合成付款100')['reconciliation']
            assert payment['refundedCents'] == 3000 and payment['remainingAfterRefundCents'] == 7000
            assert self.raw_transactions() == original, 'Relationships must not rewrite the original imported JSON'
            button(page, '月预算').click()
            expect(page.get_by_test_id('finance-budget-CNY-购物')).to_contain_text('30')
            for width in (320, 390, 1040, 1440):
                self.screenshot(page, 'budget-net70', width)
            self.passed('Actual UI imports order/payment/refund/duplicate then previews and confirms three associations; exact net70/order100/refund30/budget30 remain separate with original rows preserved')

            self.ledger(page)
            self.transaction(page, '合成重复付款100')
            button(page, '查找关联').click()
            relation = page.get_by_test_id('finance-relation-' + linked['duplicate']['id'])
            relation.get_by_role('button', name='撤销关联', exact=True).click()
            with page.expect_response(lambda response: urlsplit(response.url).path == BASE + '/reconciliation/' + linked['duplicate']['id'] + '/revoke') as revoked:
                button(page, '确认撤销').click()
            assert revoked.value.status == 200 and revoked.value.json()['relation']['status'] == 'revoked'
            repeated = self.write(ctx, 'POST', BASE + '/reconciliation/' + linked['duplicate']['id'] + '/revoke',
                                  {'revision': linked['duplicate']['revision']})
            assert repeated['replayed']
            assert self.total(self.overview(ctx))['netSpendCents'] == 17000
            assert self.raw_transactions() == original
            self.seed(ctx, [row('合成美元付款', '8.00', currency='USD')])
            currency_data = self.overview(ctx)
            assert self.total(currency_data, 'USD')['netSpendCents'] == 800 and self.total(currency_data)['netSpendCents'] == 17000
            self.write(ctx, 'POST', BASE + '/reconciliation/preview', {'kind': 'refund_payment',
                'leftId': self.find(currency_data, '合成退款30')['id'], 'rightId': self.find(currency_data, '合成美元付款')['id'], 'amount': '1.00'}, 400)
            self.passed('Explicit UI revocation restores net170 without deleting or changing originals; same revocation is idempotent and currencies cannot be cross-allocated')

    def version_conflicts(self, browser):
        with self.flow(browser) as (ctx, page):
            self.seed(ctx, [row('合成部分退款付款', '100.00'), row('合成部分退款', '80.00', 'refund', '原退款分类')])
            self.open_finance(page)
            self.ledger(page)
            self.make_budget(page)
            old_budget = self.overview(ctx)['budgets'][0]
            page.get_by_test_id('finance-budget-CNY-购物').get_by_role('button', name='修改预算', exact=True).click()
            amount = page.get_by_role('textbox', name='预算金额', exact=True)
            amount.fill('120.00')
            self.write(ctx, 'PUT', BASE + '/budgets', {'month': MONTH, 'currency': 'CNY', 'category': '购物',
                'amount': '130.00', 'revision': old_budget['revision']})
            with page.expect_response(lambda response: urlsplit(response.url).path == BASE + '/budgets'
                                      and response.request.method == 'PUT') as stale:
                button(page, '保存预算').click()
            assert stale.value.status == 409
            expect(amount).to_have_value('120.00')
            expect(button(page, '保存预算')).to_be_disabled()
            button(page, '读取最新预算').click()
            expect(amount).to_have_value('130.00')
            amount.fill('140.00')
            with page.expect_response(lambda response: urlsplit(response.url).path == BASE + '/budgets'
                                      and response.request.method == 'PUT') as saved:
                button(page, '保存预算').click()
            assert saved.value.status == 200
            expect(button(page, '保存预算')).not_to_be_visible()
            assert self.overview(ctx)['budgets'][0]['amountCents'] == 14000

            self.ledger(page)
            data = self.overview(ctx)
            refund, payment = self.find(data, '合成部分退款'), self.find(data, '合成部分退款付款')
            self.transaction(page, '合成部分退款')
            candidate_id = f"finance-candidate-refund_payment-{refund['id']}-{payment['id']}"
            page.get_by_test_id(candidate_id).get_by_role('button', name='核对这组记录', exact=True).click()
            page.get_by_role('textbox', name='分配金额', exact=True).fill('20.00')
            with page.expect_response(lambda response: urlsplit(response.url).path == BASE + '/reconciliation/preview') as preview:
                button(page, '预览关联').click()
            assert preview.value.status == 200 and preview.value.json()['amountCents'] == 2000
            self.write(ctx, 'PATCH', BASE + '/transactions/' + payment['id'], {'revision': payment['revision'], 'category': '购物'})
            with page.expect_response(lambda response: urlsplit(response.url).path == BASE + '/reconciliation/confirm') as changed:
                button(page, '确认关联').click()
            assert changed.value.status == 409
            assert not self.snapshot()['hub_reconciliations']
            expect(button(page, '取消')).to_be_enabled()
            button(page, '取消').click()
            button(page, '重新读取交易').click()
            page.get_by_test_id(candidate_id).get_by_role('button', name='核对这组记录', exact=True).click()
            page.get_by_role('textbox', name='分配金额', exact=True).fill('20.00')
            button(page, '预览关联').click()
            expect(button(page, '确认关联')).to_be_enabled()
            with page.expect_response(lambda response: urlsplit(response.url).path == BASE + '/reconciliation/confirm') as final:
                button(page, '确认关联').click()
            assert final.value.status == 200
            data = self.overview(ctx)
            assert self.find(data, '合成部分退款')['amountCents'] == 8000
            assert self.find(data, '合成部分退款')['reconciliation']['unallocatedCents'] == 6000
            assert self.find(data, '合成部分退款付款')['reconciliation']['refundedCents'] == 2000
            assert self.total(data)['netSpendCents'] == 2000
            assert self.total(data)['categories'] == {'购物': 8000, '原退款分类': -6000}
            self.passed('Real budget409 preserves draft until latest version is read; stale relationship preview cannot commit, fresh partial20 allocation leaves refund60 unallocated without inferring full refund')

            self.transaction(page, '合成部分退款') if not page.get_by_role('heading', name='交易详情', exact=True).is_visible() else None
            current = self.find(self.overview(ctx), '合成部分退款')
            self.write(ctx, 'DELETE', BASE + '/transactions/' + current['id'], {'revision': current['revision']})
            button(page, '刷新账本').click()
            expect(button(page, '导入账单')).to_be_enabled()
            expect(page.get_by_role('textbox', name='交易分类', exact=True)).to_have_count(0)
            self.ledger(page)
            expect(button(page, '查看交易合成部分退款')).to_have_count(0)
            button(page, '刷新账本').click()
            expect(button(page, '导入账单')).to_be_enabled()
            assert not any(t['id'] == current['id'] for t in self.overview(ctx)['transactions'])
            self.passed('Deleting the currently viewed transaction through the real API clears the vanished detail and returns to a refreshable ledger without recreating the record')

    def private_boundaries(self, browser):
        with self.flow(browser) as (ctx, page):
            self.seed(ctx, [row('合成本人敏感流水', '42.50', category='私人类别')])
            owner_data = self.overview(ctx)
            record = owner_data['transactions'][0]
            partner = self.context(browser, 2)
            child = self.context(browser, None)
            tv = self.context(browser, None)
            try:
                partner_page = partner.new_page()
                self.open_finance(partner_page)
                self.ledger(partner_page)
                expect(partner_page.locator('body')).not_to_contain_text('合成本人敏感流水')
                assert self.overview(partner)['transactions'] == []
                self.get(partner, BASE + '/reconciliation?transactionId=' + record['id'], 404)
                self.write(partner, 'PATCH', BASE + '/transactions/' + record['id'], {'revision': record['revision'], 'category': '越权修改'}, 404)
                assert self.get(partner, BASE + '/shared?month=' + MONTH)['totals'] == []

                self.open_finance(page)
                self.ledger(page)
                self.transaction(page, '合成本人敏感流水')
                share = page.get_by_role('checkbox', name='将本笔金额纳入共同消费汇总', exact=True)
                share.focus()
                share.press('Space')
                expect(share).to_be_checked()
                with page.expect_response(lambda response: urlsplit(response.url).path == BASE + '/transactions/' + record['id']
                                          and response.request.method == 'PATCH') as saved:
                    button(page, '保存核对').click()
                assert saved.value.status == 200
                shared = self.get(partner, BASE + '/shared?month=' + MONTH)
                assert self.total(shared)['netSpendCents'] == 4250
                assert not any(value in json.dumps(shared, ensure_ascii=False) for value in (
                    '合成本人敏感流水', record['id'], record['provenance']['batchId']))
                assert self.overview(partner)['transactions'] == []
                assert '合成本人敏感流水' not in json.dumps(self.get(partner, '/api/state'), ensure_ascii=False)

                invitation = self.write(ctx, 'POST', '/api/spaces/invitations', {}, 201)['invitation']
                created = self.write(ctx, 'POST', '/api/spaces/redeem', {'invitation': invitation, 'name': '合成财务第二家庭',
                    'slug': 'expo-finance-two', 'MEMBER1_PASSWORD': 'testing-password-one', 'MEMBER2_PASSWORD': 'testing-password-two'}, 201)
                self.child_entry = created['entry']
                assert child.request.get(self.base + self.child_entry).status == 200
                self.login(child)
                child_page = child.new_page()
                self.open_finance(child_page)
                self.ledger(child_page)
                assert self.get(child, '/api/me')['user']['householdId'] != 'default'
                assert self.overview(child)['transactions'] == []
                self.get(child, BASE + '/reconciliation?transactionId=' + record['id'], 404)
                self.write(child, 'PATCH', BASE + '/transactions/' + record['id'], {'revision': record['revision'], 'category': '越权修改'}, 404)
                expect(child_page.locator('body')).not_to_contain_text('合成本人敏感流水')

                pairing = tv.request.post(self.base + '/api/pair/start', data={}).json()
                self.write(ctx, 'POST', '/api/pair/approve', {'code': pairing['code'], 'name': '合成财务电视'})
                assert tv.request.post(self.base + '/api/pair/poll', data={'secret': pairing['secret']}).json()['approved']
                assert self.get(tv, '/api/me')['user']['role'] == 'tv'
                for path in ('/overview', '/transactions', '/shared'):
                    self.get(tv, BASE + path, 403)
                tv_page = tv.new_page()
                tv_reads = []
                tv_page.on('request', lambda req: tv_reads.append(urlsplit(req.url).path))
                tv_page.goto(self.base + '/app/finance')
                tv_page.wait_for_load_state('networkidle')
                assert not any(path.startswith(BASE) for path in tv_reads)
                expect(tv_page.locator('body')).not_to_contain_text('合成本人敏感流水')
                self.passed('Real partner/second-household/paired-TV sessions cannot read or modify private rows; UI sharing emits aggregates only, without titles, IDs or provenance')
            finally:
                partner.close()
                child.close()
                tv.close()

    def async_boundaries(self, browser):
        assert self.child_entry, 'Second household must be created through the real invitation flow'
        with self.flow(browser) as (ctx, page):
            self.seed(ctx, [row('合成旧成员迟到流水', '6.00')])
            self.open_finance(page)
            self.ledger(page)
            expect(button(page, '查看交易合成旧成员迟到流水')).to_be_visible()
            visibility(page, True)
            expect(button(page, '查看交易合成旧成员迟到流水')).not_to_be_visible()
            visibility(page, False)
            expect(button(page, '查看交易合成旧成员迟到流水')).to_be_visible()
            ctx.set_offline(True)
            expect(button(page, '查看交易合成旧成员迟到流水')).not_to_be_visible()
            ctx.set_offline(False)
            expect(button(page, '查看交易合成旧成员迟到流水')).to_be_visible(timeout=15000)
            self.passed('Private ledger conceals immediately in background/offline and is restored only after a fresh real session read')

            for kind in ('member', 'household'):
                self.open_finance(page)
                self.ledger(page)
                held = []
                hold = [True]

                def hold_ledger(handler):
                    if handler.request.method == 'GET' and hold[0]:
                        response = handler.fetch(max_redirects=0)
                        assert response.status == 200
                        assert 'set-cookie' not in response.headers
                        held.append((handler, response))
                    else:
                        handler.continue_()

                page.route(self.base + BASE + '/transactions?*', hold_ledger)
                button(page, '刷新账本').click()
                self.settle(page, lambda: bool(held))
                visibility(page, True)
                if kind == 'member':
                    self.write(ctx, 'POST', '/api/logout', {})
                    self.login(ctx, 2)
                else:
                    assert ctx.request.get(self.base + self.child_entry).status == 200
                    self.login(ctx)
                hold[0] = False
                for handler, response in held:
                    handler.fulfill(response=response)
                page.unroute(self.base + BASE + '/transactions?*', hold_ledger)
                visibility(page, False)
                expect(button(page, '查看交易合成旧成员迟到流水')).to_have_count(0)
                self.open_finance(page)
                self.ledger(page)
                assert self.overview(ctx)['transactions'] == []
                expect(page.locator('body')).not_to_contain_text('合成旧成员迟到流水')
                assert ctx.request.get(self.base + '/space/home').status == 200
                self.login(ctx)
                self.passed('Held genuine old ledger response cannot repaint after real cookie-only ' + kind + ' switch')

        # A confirm can commit before its response arrives. New identity must
        # never inherit the receipt, file contents or authority to replay it.
        for kind in ('member', 'household'):
            with self.flow(browser) as (ctx, page):
                self.open_finance(page)
                self.open_import(page, csv_bytes([row('合成迟到导入私有名称', '11.00')]), name='synthetic-private-late.csv')
                self.preview_file(page)
                held = []

                def hold_confirmation(handler):
                    if handler.request.method == 'POST' and not held:
                        response = handler.fetch(max_redirects=0)
                        assert response.status == 200
                        held.append((handler, response, handler.request.post_data_json))
                    else:
                        handler.continue_()

                page.route(self.base + BASE + '/imports/confirm', hold_confirmation)
                button(page, '确认导入 · 仅本人').click()
                self.settle(page, lambda: bool(held))
                assert self.overview(ctx)['totalRecordCount'] == 1
                visibility(page, True)
                if kind == 'member':
                    self.write(ctx, 'POST', '/api/logout', {})
                    self.login(ctx, 2)
                else:
                    assert ctx.request.get(self.base + self.child_entry).status == 200
                    self.login(ctx)
                request_id = held[0][2]['requestId']
                for handler, response, _ in held:
                    handler.fulfill(response=response)
                page.unroute(self.base + BASE + '/imports/confirm', hold_confirmation)
                visibility(page, False)
                expect(page.locator('body')).not_to_contain_text('合成迟到导入私有名称')
                expect(page.locator('body')).not_to_contain_text('synthetic-private-late.csv')
                expect(button(page, '查看已导入账本')).to_have_count(0)
                denied = self.get(ctx, BASE + '/imports/results/' + request_id, 404)
                assert denied['code'] == 'import_result_not_found'
                assert self.overview(ctx)['transactions'] == []
                self.passed('Committed but held private import receipt is concealed after real ' + kind + ' switch; new session cannot read its receipt or reuse old draft')


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
    out = Path(__file__).resolve().parents[1] / 'test-results' / ('expo-finance-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], screenshots=[],
        eventInjections=['document.hidden/visibilityState plus visibilitychange for background/foreground'],
        head=head, tree=evidence['sourceTree'], buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(out / 'executed-harness.py'),
        sourceHashesBefore=hashes(), bundleHashesBefore=bundle_hashes(), productionWrites=0, realCloud=False, physicalTelevision=False,
        scope='Frozen Expo bundle, real local Flask/SQLite, real member/household/TV sessions and CSRF; synthetic financial files only.')
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
            folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='expo-finance-')))
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
