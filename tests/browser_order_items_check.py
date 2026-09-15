"""Private item UI on real Flask/SQLite/Edge, with two explicit evidence modes.

contract: real CSV parsing/confirmation plus server-owned synthetic item metadata;
          proves UI contract only, never claims the merged XLSX adapter was run.
adapter:  unmodified backend parses a synthetic 11-column/six-merge XLSX; intended
          for a reviewed integration containing the order-group implementation.
Neither mode reads real inputs or permits provider/network access beyond loopback.
"""
import argparse
from contextlib import closing, ExitStack
from copy import deepcopy
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from urllib.parse import urlsplit
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import finance_hub
from app import create_app
from flask import g, request
from playwright.sync_api import expect, sync_playwright
from test_financial_files import sheet_xml, workbook
from werkzeug.serving import make_server, WSGIRequestHandler

DAY = '2026-08-12'
TITLE = 'SYNTHETIC_FIRST <img src="https://example.invalid/x" onerror="window.orderXss=1">'
SECOND = 'SYNTHETIC_SECOND 商品二'
ITEMS = [
    {'title': TITLE, 'variant': '<svg onload="window.orderXss=2">蓝色</svg>', 'quantityText': '02 件',
     'listedAmountText': '￥999.00（原价）', 'productUrl': 'https://example.invalid/item?a=1&b=<script>raw</script>', 'sourceLine': 2},
    {'title': SECOND, 'variant': '大号 & 特别款', 'quantityText': '1 套', 'listedAmountText': '88.00 / 套',
     'productUrl': 'javascript:window.orderXss=3', 'sourceLine': 3},
]
SINGLE = {'title': 'SYNTHETIC_SINGLE', 'variant': '', 'quantityText': '1', 'listedAmountText': '70.00',
          'productUrl': '', 'sourceLine': 4}


class Quiet(WSGIRequestHandler):
    def log(self, *_args, **_kwargs): pass


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def sources():
    tracked = subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', '-z']).decode().split('\0')
    names = {n for n in tracked if n and not n.lower().endswith('.md')}
    names.add(Path(__file__).relative_to(ROOT).as_posix())
    return {name: sha(ROOT / name) for name in sorted(names)}


def csv_file(rows):
    out = io.StringIO(newline='')
    writer = csv.writer(out)
    writer.writerow(['date', 'title', 'amount', 'currency', 'flow', 'category', 'id', 'status'])
    for rid, title, amount in rows:
        writer.writerow([DAY, title, amount, 'CNY', 'expense', '购物', rid, '交易成功'])
    return out.getvalue().encode('utf-8-sig')


def merged_file(amount='120.00'):
    headers = ['订单号', '订单提交时间', '订单状态', '店铺名称', '商品名称', '商品链接',
               '型号款式', '商品数量', '商品金额', '实付金额', '运费']
    def item_values(item):
        return [item['title'], item['productUrl'], item['variant'], item['quantityText'], item['listedAmountText']]
    rows = [headers,
            ['SYNTHETIC-O1', DAY, '交易成功', 'SYNTHETIC_SHOP'] + item_values(ITEMS[0]) + [amount, '5.00'],
            ['', '', '', ''] + item_values(ITEMS[1]) + ['', ''],
            ['SYNTHETIC-O2', DAY, '交易成功', 'SYNTHETIC_SHOP'] + item_values(SINGLE) + ['50.00', '0']]
    merges = '<mergeCells count="6">' + ''.join(f'<mergeCell ref="{col}2:{col}3"/>' for col in 'ABCDJK') + '</mergeCells>'
    return workbook(sheet_override=sheet_xml(rows).replace('</worksheet>', merges + '</worksheet>'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['contract', 'adapter'], default='contract')
    mode = parser.parse_args().mode
    out = ROOT / 'test-results'; out.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target = out / f'order-items-{mode}-browser-verification.json'
    if target.exists(): shutil.copy2(target, out / f'order-items-{mode}-history-{stamp}.json')
    report = {'mode': mode, 'passed': False, 'checks': [], 'sourceHashesBefore': sources(), 'screenshots': [],
              'pageErrors': [], 'externalRequests': [], 'providerCalls': [], 'requestCounts': {},
              'realPrivateInputs': 0, 'productionWrites': 0, 'realCloudWrites': 0,
              'adapterExecuted': mode == 'adapter', 'serverOwnedContractInjection': mode == 'contract',
              'scope': 'Temporary real Flask/SQLite/Edge. Contract mode injects item/preview-conflict fields server-side; adapter mode uses the real merged XLSX parser without patches.',
              'knownBoundary': 'A Cookie change after final /me is non-atomic; already-sent confirmation cannot be cancelled. No real platform input or production validation.'}
    def passed(name):
        report['checks'].append({'name': name, 'passed': True}); print('PASS ' + name, flush=True)
    original_connect, original_dns = socket.socket.connect, socket.getaddrinfo
    def local(host): return host in ('127.0.0.1', '::1', 'localhost', b'127.0.0.1', b'::1', b'localhost')
    def connect(sock, address):
        if isinstance(address, tuple) and not local(address[0]):
            report['externalRequests'].append('socket'); raise AssertionError('External socket forbidden')
        return original_connect(sock, address)
    def dns(host, *args, **kwargs):
        if host is not None and not local(host):
            report['externalRequests'].append('dns'); raise AssertionError('External DNS forbidden')
        return original_dns(host, *args, **kwargs)
    def deny(*_args, **_kwargs):
        report['providerCalls'].append('blocked'); raise AssertionError('Provider forbidden')
    started = time.monotonic()
    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(socket.socket, 'connect', connect))
            stack.enter_context(patch.object(socket, 'getaddrinfo', dns))
            folder = stack.enter_context(tempfile.TemporaryDirectory(prefix='order-items-'))
            db = Path(folder) / 'household.sqlite3'
            if mode == 'contract':
                original_parse = finance_hub.parse_import
                def contract_parse(payload):
                    result = original_parse(payload)
                    for row in result['rows']:
                        if row['kind'] != 'orders' or not row['externalId'].startswith('SYNTHETIC-O'): continue
                        items = deepcopy(ITEMS if row['externalId'] == 'SYNTHETIC-O1' else [SINGLE])
                        row['orderItems'] = items
                        row['orderGroup'] = {'format': 'taobao-merged-v1', 'itemCount': len(items),
                                             'sourceRows': [i['sourceLine'] for i in items],
                                             'shippingAmountText': '5.00' if len(items) == 2 else '0'}
                    return result
                stack.enter_context(patch.object(finance_hub, 'parse_import', contract_parse))
            app = create_app({'TESTING': True, 'DATA_DIR': folder, 'SECRET_KEY': 'synthetic-order-items',
                              'SESSION_COOKIE_SECURE': False, 'PUBLIC_ORIGIN': 'http://localhost',
                              'MEMBER1_PASSWORD': 'testing-password-one', 'MEMBER2_PASSWORD': 'testing-password-two',
                              'MICROSOFT_CLIENT_ID': '', 'GOOGLE_CLIENT_ID': '', 'OPENAI_API_KEY': '', 'OPENAI_MODEL': '',
                              'CLOUD_TRANSPORT': deny, 'OAUTH_TRANSPORT': deny})
            if mode == 'contract':
                @app.after_request
                def inject_preview_conflict(response):
                    if request.path == '/api/finance-hub/imports/preview' and response.status_code == 200:
                        value = response.get_json()
                        # Presentation-contract fixture, not the future adapter's conflict implementation.
                        with closing(sqlite3.connect(db)) as con:
                            old = {r[0]: json.loads(r[1]) for r in con.execute('SELECT fingerprint,data FROM hub_transactions WHERE owner=?', (g.actor['id'],))}
                        for row in value['rows']:
                            row['conflict'] = row['fingerprint'] in old and old[row['fingerprint']]['amountCents'] != row['amountCents']
                        value['conflictCount'] = sum(r['conflict'] for r in value['rows'])
                        response.set_data(json.dumps(value, ensure_ascii=False)); response.content_type = 'application/json'
                    return response
            server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=Quiet)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            try:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
                    def login(ctx, member=1, child=False):
                        with closing(sqlite3.connect(db)) as con: con.execute('DELETE FROM attempts'); con.commit()
                        r = ctx.request.post(base + '/api/login', data={'username': 'member' + str(member),
                            'password': ('child-password-' if child else 'testing-password-') + ('one' if member == 1 else 'two')})
                        assert r.status == 200
                    def headers(ctx): return {'X-CSRF-Token': ctx.request.get(base + '/api/me').json()['csrf']}
                    admin = browser.new_context(); login(admin)
                    invitation = admin.request.post(base + '/api/spaces/invitations', headers=headers(admin), data={}); assert invitation.status == 201
                    child = admin.request.post(base + '/api/spaces/redeem', data={'invitation': invitation.json()['invitation'],
                        'name': 'Synthetic Order Items Household', 'slug': 'synthetic-order-items',
                        'MEMBER1_PASSWORD': 'child-password-one', 'MEMBER2_PASSWORD': 'child-password-two'})
                    assert child.status == 201; child_entry = child.json()['entry']
                    class Flow:
                        def __init__(self, reset=True):
                            if reset:
                                with closing(sqlite3.connect(db)) as con:
                                    for table in ['hub_reconciliations', 'hub_imports', 'hub_transactions']: con.execute('DELETE FROM ' + table)
                                    con.commit()
                            self.ctx = browser.new_context(viewport={'width': 1440, 'height': 1000}, service_workers='block')
                            self.held = []; self.holding = None; self.calls = []
                            self.ctx.route('**/*', self.route); login(self.ctx)
                            self.ctx.add_init_script('window.orderPending=0;const orderFetch=fetch;window.fetch=async(...a)=>{window.orderPending++;try{return await orderFetch(...a)}finally{window.orderPending--}};')
                            self.page = self.ctx.new_page(); self.page.on('pageerror', lambda e: report['pageErrors'].append(str(e)))
                            self.page.goto(base); expect(self.page.locator('.ps-welcome')).to_be_visible()
                            self.page.evaluate('()=>clearInterval(pollTimer)')
                        def route(self, route):
                            req = route.request; key = (req.method, urlsplit(req.url).path)
                            if not req.url.startswith(base + '/'):
                                report['externalRequests'].append(urlsplit(req.url).hostname); route.abort(); return
                            self.calls.append(key); label = ' '.join(key); report['requestCounts'][label] = report['requestCounts'].get(label, 0) + 1
                            if self.holding == key:
                                self.holding = None; self.held.append((route, route.fetch())); return
                            route.continue_()
                        def settle(self): self.page.wait_for_function('()=>window.orderPending===0')
                        def hold(self, path): self.holding = ('GET' if path.endswith('overview') else 'POST', path)
                        def waitheld(self):
                            deadline = time.monotonic() + 15
                            while not self.held and time.monotonic() < deadline: self.page.wait_for_timeout(25)
                            assert self.held, 'Expected held actual response'
                        def release(self, fail=False):
                            route, response = self.held.pop(0)
                            if fail: route.fulfill(status=503, content_type='application/json', body='{"error":"SYNTHETIC_READ_FAILED"}')
                            else: route.fulfill(response=response)
                            self.settle()
                        def open(self, tab='import'):
                            self.page.evaluate('(tab)=>FinanceHub.open(tab)', tab)
                            expect(self.page.locator('#fh-import-form' if tab == 'import' else '.fh-ledger')).to_be_visible()
                        def prepare(self, amount='120.00', rows=None, kind='orders'):
                            self.open(); form = self.page.locator('#fh-import-form')
                            form.locator('[name=source]').select_option('taobao' if kind == 'orders' else 'generic')
                            form.locator('[name=kind]').select_option(kind)
                            if mode == 'adapter' and rows is None:
                                raw, name = merged_file(amount), 'synthetic-merged-orders.xlsx'
                                form.locator('[name=sheet]').fill('支付账单')
                            else:
                                raw, name = csv_file(rows or [('SYNTHETIC-O1', 'SYNTHETIC_FIRST 等2件商品', amount), ('SYNTHETIC-O2', 'SYNTHETIC_SINGLE', '50')]), 'synthetic-orders.csv'
                            form.locator('[name=file]').set_input_files({'name': name, 'mimeType': 'application/octet-stream', 'buffer': raw})
                            holding_preview = self.holding == ('POST', '/api/finance-hub/imports/preview')
                            form.locator('[type=submit]').click()
                            if holding_preview: self.waitheld()
                            else: expect(self.page.locator('[data-fh=confirm]')).to_be_enabled()
                        def overview(self):
                            r = self.ctx.request.get(base + '/api/finance-hub/overview?month=' + DAY[:7]); assert r.status == 200; return r.json()
                        def confirm(self): self.page.locator('[data-fh=confirm]').click()
                        def ledger(self): expect(self.page.locator('.fh-ledger')).to_be_visible(); self.settle()
                        def posts(self): return self.calls.count(('POST', '/api/finance-hub/imports/confirm'))
                        def close(self):
                            assert not self.held; self.ctx.close()
                    f = Flow()
                    try:
                        f.prepare(); p = f.page
                        expect(p.locator('[data-fh-order-summary]')).to_contain_text('2 个订单 · 3 项商品')
                        expect(p.locator('.fh-metrics')).to_contain_text('2 单')
                        assert f.overview()['transactionCount'] == 0
                        passed('preview_counts_two_orders_three_items_and_writes_nothing')
                        detail = p.locator('[data-fh-order-items]').first; detail.locator('summary').click()
                        expect(detail.locator('[data-fh-order-item]')).to_have_count(2)
                        for text in [TITLE, SECOND, '02 件', '￥999.00（原价）', '5.00', ITEMS[1]['productUrl']]: expect(detail).to_contain_text(text)
                        assert detail.locator('a,img,svg,script,iframe').count() == 0 and p.evaluate('window.orderXss||0') == 0
                        assert p.locator('.fh-table tbody tr[data-fh-preview-row]').count() == 2
                        passed('all_source_strings_escaped_and_urls_remain_inert_text')
                        for theme, width in [('forest', 360), ('light', 768), ('ocean', 1440)]:
                            p.set_viewport_size({'width': width, 'height': 1000}); p.evaluate('(v)=>document.documentElement.dataset.theme=v', theme)
                            assert p.locator('#dialog').evaluate('(n)=>n.scrollWidth<=n.clientWidth+1')
                            assert detail.evaluate('(n)=>n.scrollWidth<=n.clientWidth+1')
                            screenshot = out / f'order-items-{mode}-{theme}-{width}-{stamp}.png'; p.screenshot(path=str(screenshot), full_page=True)
                            report['screenshots'].append({'path': str(screenshot), 'sha256': sha(screenshot)})
                        passed('three_themes_phone_tablet_desktop_expanded_content_no_horizontal_overflow')
                        f.hold('/api/finance-hub/overview'); f.confirm(); f.waitheld(); assert f.posts() == 1
                        f.release(True); expect(p.locator('[data-fh-import-receipt]')).to_contain_text('导入确认已完成')
                        p.locator('[data-fh=receipt-retry]').click(); f.ledger(); assert f.posts() == 1
                        current = f.overview(); assert current['transactionCount'] == 2
                        assert current['totals'][0]['orderCents'] == 17000 and current['totals'][0]['netSpendCents'] == 0
                        order = next(t for t in current['transactions'] if t['externalId'] == 'SYNTHETIC-O1')
                        assert order['orderItems'] == ITEMS and order['amountCents'] == 12000
                        passed('confirmed_two_orders_not_item_sums_and_failed_readback_retries_get_only')
                        row = p.locator('.fh-transaction').filter(has_text='SYNTHETIC_FIRST')
                        row.locator('[data-fh-order-items] summary').click(); expect(row).to_contain_text(SECOND)
                        row.locator('[data-fh=transaction]').click(); expect(p.locator('#fh-editor [data-fh-order-items]')).to_have_count(1)
                        p.locator('#fh-editor [data-fh-order-items] summary').click(); expect(p.locator('#fh-editor')).to_contain_text(SECOND)
                        p.locator('[data-fh=reconcile]').click(); expect(p.locator('#fh-match-search')).to_be_visible()
                        p.locator('[data-fh-order-items] summary').first.click(); expect(p.locator('[data-fh-order-items]').first).to_contain_text(SECOND)
                        passed('persisted_ledger_review_and_reconciliation_keep_all_private_items')
                        f.prepare(amount='130.00'); expect(p.locator('[data-fh-import-conflicts]')).to_contain_text('1 单与原记录不同')
                        expect(p.locator('.fh-table')).to_contain_text('与原记录不同 · 保留原记录')
                        f.confirm(); f.ledger(); expect(p.locator('[data-fh-import-receipt]')).to_contain_text('1 条冲突保留原记录')
                        kept = next(t for t in f.overview()['transactions'] if t['id'] == order['id'])
                        assert kept['amountCents'] == 12000 and kept['orderItems'] == ITEMS
                        passed('preview_conflict_explicit_and_confirmation_preserves_original_amount_and_items')
                        f.prepare(); expect(p.locator('.fh-table')).to_contain_text('重复 · 跳过'); f.confirm(); f.ledger()
                        assert f.overview()['transactionCount'] == 2
                        passed('identical_import_keeps_two_orders_without_duplicate_items_or_money')
                        f.prepare(rows=[('LEGACY-PAYMENT', 'LEGACY_PAYMENT', '5')], kind='payments')
                        expect(p.locator('[data-fh-order-items]')).to_have_count(0); expect(p.locator('.fh-metrics')).to_contain_text('1 条')
                        f.confirm(); f.ledger(); legacy = p.locator('.fh-transaction').filter(has_text='LEGACY_PAYMENT')
                        expect(legacy.locator('[data-fh-order-items]')).to_have_count(0)
                        assert f.overview()['totals'][0]['netSpendCents'] == 500
                        passed('legacy_payment_ui_and_amounts_unchanged_without_new_fields')
                        shared = f.ctx.request.get(base + '/api/state').text() + f.ctx.request.get(base + '/api/finance-hub/shared').text()
                        assert 'SYNTHETIC_SECOND' not in shared and 'orderItems' not in shared
                        passed('shared_state_and_finance_summary_exclude_private_item_metadata')
                        login(f.ctx, 2); f.page.evaluate('boot()'); f.open('ledger')
                        expect(f.page.locator('[data-fh-order-items]')).to_have_count(0)
                        assert f.ctx.request.get(base + '/api/finance-hub/reconciliation?transactionId=' + order['id']).status == 404
                        passed('partner_cannot_read_order_items_or_direct_reconciliation')
                        f.ctx.request.get(base + child_entry); login(f.ctx, child=True); f.page.evaluate('boot()'); f.open('ledger')
                        expect(f.page.locator('[data-fh-order-items]')).to_have_count(0)
                        assert f.ctx.request.get(base + '/api/finance-hub/reconciliation?transactionId=' + order['id']).status == 404
                        passed('other_household_cannot_read_original_member_item_records')
                    finally: f.close()
                    # Keep full-order/item expansion available within the first100 rows only;
                    # generic payment previews still describe lines, not orders.
                    f = Flow()
                    try:
                        for kind in ['orders', 'payments']:
                            f.prepare(rows=[('LIMIT-' + str(i), 'SYNTHETIC_LIMIT_' + str(i), '1') for i in range(101)], kind=kind)
                            expect(f.page.locator('.fh-table tbody tr[data-fh-preview-row]')).to_have_count(100)
                            expect(f.page.locator('#dialog')).to_contain_text('前 100 个订单' if kind == 'orders' else '前 100 行')
                        assert f.overview()['transactionCount'] == 0
                        passed('hundred_order_limit_and_legacy_payment_line_wording_are_distinct_and_readonly')
                    finally: f.close()
                    for phase, action, fail in [('preview', 'draft', False), ('preview', 'member', False),
                                                ('readback', 'household', False), ('readback', 'draft', True)]:
                        f = Flow()
                        try:
                            if phase == 'preview': f.hold('/api/finance-hub/imports/preview'); f.prepare()
                            else: f.prepare(); f.hold('/api/finance-hub/overview'); f.confirm()
                            f.waitheld()
                            if action == 'draft':
                                f.open(); f.page.locator('#fh-import-form [name=sheet]').fill('NEW_PRIVATE_DRAFT')
                            else:
                                if action == 'household': f.ctx.request.get(base + child_entry)
                                login(f.ctx, member=2 if action == 'member' else 1, child=action == 'household')
                            f.release(fail)
                            expect(f.page.locator('[data-fh-order-items]')).to_have_count(0)
                            if action == 'draft': expect(f.page.locator('#fh-import-form [name=sheet]')).to_have_value('NEW_PRIVATE_DRAFT')
                            else: expect(f.page.locator('#dialog')).to_contain_text('登录成员或家庭已变化')
                            assert f.posts() == (1 if phase == 'readback' else 0)
                            passed(f'late_{phase}_{action}_{"error" if fail else "success"}_does_not_restore_old_items')
                        finally: f.close()
                    tv = browser.new_context(); start = tv.request.post(base + '/api/pair/start', data={}); assert start.status == 200
                    login(admin); approved = admin.request.post(base + '/api/pair/approve', headers=headers(admin), data={'code': start.json()['code']}); assert approved.status == 200
                    polled = tv.request.post(base + '/api/pair/poll', data={'secret': start.json()['secret']}); assert polled.status == 200 and polled.json()['approved']
                    tv.route('**/*', lambda r: r.continue_() if r.request.url.startswith(base + '/') else (report['externalRequests'].append('tv'), r.abort()))
                    page = tv.new_page(); page.on('pageerror', lambda e: report['pageErrors'].append(str(e))); page.goto(base + '/tv')
                    page.wait_for_function('()=>isTV&&data!==null'); page.evaluate('FinanceHub.open("ledger")')
                    assert page.locator('[data-fh-order-items]').count() == 0
                    assert tv.request.get(base + '/api/finance-hub/overview').status == 403
                    passed('paired_tv_hides_finance_items_and_private_api_is_forbidden')
                    tv.close(); admin.close(); browser.close()
            finally: server.shutdown(); thread.join(timeout=5); server.server_close()
        assert not report['pageErrors'] and not report['externalRequests'] and not report['providerCalls']
        report['passed'] = True
    except Exception:
        report['traceback'] = traceback.format_exc(); print(report['traceback'], flush=True)
    finally:
        report['sourceHashesAfter'] = sources(); report['sourceUnchanged'] = report['sourceHashesBefore'] == report['sourceHashesAfter']
        report['passed'] = report['passed'] and report['sourceUnchanged']; report['checkCount'] = len(report['checks'])
        report['durationSeconds'] = round(time.monotonic() - started, 2); report['exitCode'] = 0 if report['passed'] else 1
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'report': str(target), 'mode': mode, 'passed': report['passed'], 'checks': report['checkCount'], 'exitCode': report['exitCode']}, ensure_ascii=False), flush=True)
    return report['exitCode']


if __name__ == '__main__': raise SystemExit(main())
