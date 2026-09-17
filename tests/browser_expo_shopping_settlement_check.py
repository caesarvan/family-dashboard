"""Real, isolated Expo shopping-settlement browser acceptance.

Synthetic Flask/SQLite/HTTPS/Edge only. Faults drop or hold actual responses;
no business success is substituted. Execute only after independent review.
"""
import argparse
from contextlib import ExitStack, closing, contextmanager
from datetime import datetime, timezone
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

from playwright.sync_api import expect, sync_playwright
import browser_expo_finance_check as fixture
from browser_expo_finance_check import Run as BaseRun, button, row, sha, visibility

PREFIX = '/api/finance-hub/shopping-settlements'
ACK = '我确认共享整项实付和已买到状态'
CASES = ('apply_shared', 'transaction_dirty', 'update_revoke', 'refund_conflicts',
         'lost_commit', 'never_sent', 'saved_readback', 'privacy_late', 'background_draft', 'layout')
WIDTHS = (320, 390, 1280, 1920)


class Run(BaseRun):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        assert Path(self.source.__file__).resolve() == (self.root / 'app.py').resolve()
        paths = {'tests/browser_expo_finance_check.py': str(Path(fixture.__file__).resolve()),
                 'tests/browser_expo_shopping_settlement_check.py': str(Path(__file__).resolve()),
                 **{'tests/' + name + '.py': str(Path(sys.modules[name].__file__).resolve())
                    for name in ('test_financial_files', 'test_app')}}
        digests = {name: sha(Path(path)) for name, path in paths.items()}
        assert all(value == sha(self.root / name) for name, value in digests.items())
        assert digests['tests/browser_expo_shopping_settlement_check.py'] == self.report['harnessSha256']
        assert self.report.setdefault('fixtureActualPaths', paths) == paths
        assert self.report.setdefault('fixtureHashes', digests) == digests
        self.exchange_number = 0

    def clear_finance(self):
        pass  # Every case owns a new database; no reset of application data.

    def payment(self, ctx, title='合成本人私密付款编号', amount='100.00', **kwargs):
        kind = kwargs.pop('kind', 'payments')
        self.seed(ctx, [row(title, amount, **kwargs)], kind=kind)
        return self.find(self.overview(ctx), title)

    def shopping(self, ctx, title='合成旅行采购', **kwargs):
        value = self.write(ctx, 'POST', '/api/items/shopping', {
            'title': title, 'budget': 18000, 'actual': None, 'done': False, 'quantity': '2 件',
            'note': '原采购备注必须保持', 'owner': 'shared', **kwargs}, 201)
        return self.item(ctx, value['id'])

    def item(self, ctx, item_id):
        return next(item for item in self.get(ctx, '/api/state')['shopping'] if item['id'] == item_id)

    def protected(self):
        with closing(sqlite3.connect(self.database)) as con:
            tables = ('hub_transactions', 'hub_imports', 'hub_import_receipts', 'hub_reconciliations',
                      'hub_budgets', 'hub_investments', 'private_finance', 'finance_baselines')
            result = {name: sorted(con.execute('SELECT * FROM "' + name + '"').fetchall(), key=repr) for name in tables}
            result['finance'] = con.execute("SELECT * FROM settings WHERE id='finance'").fetchall()
            result['trips'] = con.execute("SELECT * FROM entities WHERE kind='trips' ORDER BY id").fetchall()
            return result

    def settlements(self):
        with closing(sqlite3.connect(self.database)) as con:
            return {name: sorted(con.execute('SELECT * FROM ' + name).fetchall(), key=repr)
                    for name in ('hub_shopping_settlements', 'hub_shopping_settlement_receipts')}

    def context_value(self, ctx, **query):
        from urllib.parse import urlencode
        return self.get(ctx, PREFIX + '/context?' + urlencode(query))

    def open_shopping(self, page, shop):
        page.goto(self.base + '/app/shopping')
        expect(page.get_by_role('heading', name='采购清单', exact=True)).to_be_visible(timeout=15000)
        if shop['done']:
            button(page, '全部').click()
        button(page, '核对实付：' + shop['title']).click()
        self.ready(page)

    @staticmethod
    def ready(page):
        expect(page.get_by_test_id('settlement-current')).to_be_visible(timeout=15000)
        expect(button(page, '预览共享变化')).to_be_enabled()

    def draft(self, page, pay, shop, amount='70.00', done=False):
        page.get_by_role('radio', name='选择付款：' + pay['title'], exact=True).click()
        page.get_by_role('radio', name='选择采购：' + shop['title'], exact=True).click()
        page.get_by_role('textbox', name='整项实付（元）', exact=True).fill(amount)
        check = page.get_by_role('checkbox', name='已买到', exact=True)
        if check.is_checked() != done:
            check.click()
        expect(check).to_be_checked(checked=done)

    def actual(self, page, suffix, action, *, status=200, fault=None):
        """One actual POST. Save original bytes before fulfilling or dropping."""
        url, calls = self.base + PREFIX + suffix, []
        self.exchange_number += 1
        stem = self.out / ('exchange-%02d' % self.exchange_number)
        def intercept(route):
            assert route.request.method == 'POST'
            item = {'payload': route.request.post_data_json, 'reachedServer': fault != 'before'}
            if fault == 'before':
                calls.append(item)
                route.abort('failed')
                return
            response = route.fetch(max_redirects=0)
            raw = response.body()
            stem.with_suffix('.body').write_bytes(raw)
            item.update(status=response.status, result=json.loads(raw), responseSha256=sha(stem.with_suffix('.body')))
            calls.append(item)
            if fault == 'after':
                route.abort('failed')
            else:
                route.fulfill(status=response.status, headers=response.headers, body=raw)
        page.route(url, intercept)
        try:
            action()
            self.settle(page, lambda: len(calls) == 1)
            assert len(calls) == 1 and (fault == 'before' or calls[0]['status'] == status), calls
            return calls[0]
        finally:
            page.unroute(url, intercept)
            stem.with_suffix('.json').write_text(json.dumps(calls, ensure_ascii=False, indent=2), encoding='utf-8')

    def preview(self, page, revoke=False, status=200):
        result = self.actual(page, '/preview', lambda: button(page, '预览解除影响' if revoke else '预览共享变化').click(), status=status)
        if status == 200:
            expect(page.get_by_test_id('settlement-preview')).to_be_visible()
            expect(button(page, '确认保存')).to_be_disabled()
            assert result['result']['sharing'] == {'fields': ['actual', 'done'], 'ledgerUnchanged': True}
        return result

    def confirm(self, page, *, fault=None, status=200, readback=True):
        page.get_by_role('checkbox', name=ACK, exact=True).click()
        result = self.actual(page, '/confirm', lambda: button(page, '确认保存').click(), fault=fault, status=status)
        if fault:
            expect(button(page, '读取当前核对资料')).to_be_enabled()
            expect(page.get_by_test_id('settlement-unknown')).to_be_visible()
        elif status != 200:
            expect(button(page, '读取当前核对资料')).to_be_enabled()
            expect(page.get_by_test_id('settlement-unknown')).to_have_count(0)
        elif readback:
            expect(button(page, '继续核对')).to_be_enabled()
            expect(page.get_by_test_id('settlement-preview')).to_have_count(0)
        return result

    @staticmethod
    def link_action(page, link, operation):
        target = button(page, ('更新关联：' if operation == 'update' else '解除关联：') + link['id'])
        if not target.is_visible():
            page.get_by_text('本人的关联记录', exact=True).click()
        target.click()
        expect(button(page, '预览共享变化' if operation == 'update' else '预览解除影响')).to_be_enabled()

    def reconcile(self, ctx, kind, left, right, amount):
        p = self.write(ctx, 'POST', '/api/finance-hub/reconciliation/preview', {
            'kind': kind, 'leftId': left['id'], 'rightId': right['id'], 'amount': amount})
        return self.write(ctx, 'POST', '/api/finance-hub/reconciliation/confirm', {'previewToken': p['previewToken']})

    def navigation_locked(self, page):
        # Desktop button is unique; app navigation, rather than browser hard navigation.
        page.set_viewport_size({'width': 1280, 'height': 960})
        before = page.url
        button(page, '家庭中枢首页').click()
        expect(page.get_by_text('请先完成或取消采购实付核对；保存结果不明时，先读取当前资料再离开。', exact=True)).to_be_visible()
        assert page.url == before
        expect(page.get_by_test_id('shopping-settlement-panel')).to_be_visible()

    @contextmanager
    def drop_get(self, page, path):
        calls = []
        def intercept(route):
            assert route.request.method == 'GET'
            if calls:
                route.continue_()
                return
            response = route.fetch(max_redirects=0)
            raw = response.body()
            calls.append({'status': response.status, 'body': raw})
            route.abort('failed')
        url = self.base + path + '*'
        page.route(url, intercept)
        try:
            yield calls
        finally:
            page.unroute(url, intercept)
            for value in calls:
                assert value['status'] == 200 and json.loads(value['body']) is not None

    def apply_shared(self, browser):
        with self.flow(browser) as (ctx, page), ExitStack() as extras:
            pay, shop = self.payment(ctx), self.shopping(ctx)
            partner = self.context(browser, 2); extras.callback(partner.close)
            original, protected = dict(shop), self.protected()
            self.open_shopping(page, shop); self.draft(page, pay, shop, done=True)
            before = self.settlements()
            proposal = self.preview(page)['result']
            assert proposal['before']['actual'] is None and proposal['after']['actual'] == 7000
            assert self.item(ctx, shop['id']) == original and self.settlements() == before
            receipt = self.confirm(page)['result']
            assert receipt['operation'] == 'apply' and not receipt['replayed']
            current = self.item(ctx, shop['id'])
            assert current == {**original, 'actual': 7000, 'done': True, 'revision': original['revision'] + 1}
            assert self.item(partner, shop['id']) == current and self.protected() == protected
            public = json.dumps(self.get(partner, '/api/state'), ensure_ascii=False)
            assert pay['title'] not in public and pay['id'] not in public
            private = self.context_value(partner, shoppingId=shop['id'])
            assert private['payments'] == [] and private['links'] == []
            saved = self.settlements(); self.restart()
            assert self.item(ctx, shop['id']) == current and self.settlements() == saved
            self.passed('Shopping apply persists exact cents across restart; partner sees only shared actual/done, all financial records stay unchanged')

    def transaction_dirty(self, browser):
        with self.flow(browser) as (ctx, page):
            pay = self.payment(ctx); order = self.payment(ctx, '合成订单线索', kind='orders')
            shop = self.shopping(ctx); original = self.protected()
            self.open_finance(page); self.ledger(page); self.transaction(page, pay['title'])
            page.get_by_role('textbox', name='交易分类', exact=True).fill('未保存分类')
            button(page, '核对采购实付').click()
            expect(page.get_by_test_id('shopping-settlement-panel')).to_have_count(0)
            expect(page.get_by_role('textbox', name='交易分类', exact=True)).to_have_value('未保存分类')
            expect(page.get_by_text('分类或共享设置尚未保存，请先保存核对，或重新读取交易后再核对采购实付。', exact=True)).to_be_visible()
            assert self.protected() == original
            button(page, '重新读取交易').click()
            expect(page.get_by_role('textbox', name='交易分类', exact=True)).to_have_value(pay['category'])
            button(page, '核对采购实付').click(); self.ready(page)
            self.draft(page, pay, shop, '12.34')
            button(page, '返回').click()
            expect(page.get_by_text('放弃本次输入？', exact=True)).to_be_visible()
            button(page, '放弃输入并返回').click()
            expect(page.get_by_test_id('shopping-settlement-panel')).to_have_count(0)
            expect(button(page, '返回账本')).to_be_enabled()
            button(page, '返回账本').click()
            expect(page.get_by_role('textbox', name='账本月份', exact=True)).to_have_value('2026-08')
            assert self.protected() == original
            self.ledger(page); self.transaction(page, order['title'])
            button(page, '核对采购实付').click(); self.ready(page)
            expect(page.get_by_role('radio', name='选择付款：' + pay['title'], exact=True)).to_have_count(0)
            button(page, '返回').click()
            self.reconcile(ctx, 'order_payment', order, pay, '100.00')
            self.ledger(page); self.transaction(page, order['title'])
            button(page, '核对采购实付').click(); self.ready(page)
            self.draft(page, pay, shop, '12.34'); self.preview(page); self.confirm(page)
            assert self.item(ctx, shop['id'])['actual'] == 1234
            self.passed('Transaction entry preserves dirty classification and month; order entry exposes only genuinely reconciled payments')

    def update_revoke(self, browser):
        with self.flow(browser) as (ctx, page):
            pay, shop = self.payment(ctx), self.shopping(ctx)
            protected = self.protected()
            self.open_shopping(page, shop); self.draft(page, pay, shop); self.preview(page)
            first = self.confirm(page)['result']['link']
            button(page, '继续核对').click(); self.link_action(page, first, 'update')
            page.get_by_role('textbox', name='整项实付（元）', exact=True).fill('60.00')
            page.get_by_role('checkbox', name='已买到', exact=True).click()
            self.preview(page); updated = self.confirm(page)['result']['link']
            assert updated['id'] == first['id'] and updated['paymentId'] == pay['id'] and updated['amountCents'] == 6000
            button(page, '继续核对').click(); self.link_action(page, updated, 'revoke')
            keep = self.item(ctx, shop['id']); self.preview(page, revoke=True); self.confirm(page)
            assert self.item(ctx, shop['id']) == keep
            button(page, '返回').click()
            # A separate item distinguishes null restoration from explicit zero.
            blank = self.shopping(ctx, '合成空实付待恢复')
            self.open_shopping(page, blank); self.draft(page, pay, blank, '0.00', True); self.preview(page)
            link = self.confirm(page)['result']['link']
            assert self.item(ctx, blank['id'])['actual'] == 0
            button(page, '继续核对').click(); self.link_action(page, link, 'revoke')
            page.get_by_role('radio', name='安全恢复核对前的采购值', exact=True).click()
            self.preview(page, revoke=True); self.confirm(page)
            restored = self.item(ctx, blank['id'])
            assert restored['actual'] is None and restored['done'] is False
            button(page, '返回').click()
            deleted = self.shopping(ctx, '合成稍后删除的采购')
            self.open_shopping(page, deleted); self.draft(page, pay, deleted, '10.00'); self.preview(page)
            link = self.confirm(page)['result']['link']
            button(page, '继续核对').click()
            current = self.item(ctx, deleted['id'])
            self.write(ctx, 'DELETE', '/api/items/shopping/' + deleted['id'], {'revision': current['revision']})
            self.link_action(page, link, 'revoke')
            self.preview(page, revoke=True); result = self.confirm(page)['result']
            assert result['link']['status'] == 'revoked' and result['shopping'] is None
            assert not any(s['id'] == deleted['id'] for s in self.get(ctx, '/api/state')['shopping'])
            assert self.protected() == protected
            self.passed('Update retains the association; detach keeps values, safe restore distinguishes zero/unknown, and link-only reads allow detach after shopping deletion')

    def refund_conflicts(self, browser):
        with self.flow(browser) as (ctx, page):
            pay, shop = self.payment(ctx), self.shopping(ctx)
            self.open_shopping(page, shop); self.draft(page, pay, shop, '80.00'); self.preview(page)
            refund = self.payment(ctx, '合成已核对退款', '30.00', flow='refund')
            self.reconcile(ctx, 'refund_payment', refund, pay, '30.00')
            before = self.settlements(); self.confirm(page, status=409)
            assert self.settlements() == before and self.item(ctx, shop['id']) == shop
            button(page, '读取当前核对资料').click(); self.ready(page)
            expect(page.get_by_role('textbox', name='整项实付（元）', exact=True)).to_have_value('80.00')
            assert next(p for p in self.context_value(ctx, transactionId=pay['id'])['payments'] if p['id'] == pay['id'])['netCents'] == 7000
            page.get_by_role('textbox', name='整项实付（元）', exact=True).fill('70.00')
            self.preview(page); link = self.confirm(page)['result']['link']
            current = self.item(ctx, shop['id'])
            self.write(ctx, 'PATCH', '/api/items/shopping/' + shop['id'], {'revision': current['revision'], 'note': '另一设备后来修改'})
            button(page, '继续核对').click(); self.link_action(page, link, 'revoke')
            page.get_by_role('radio', name='安全恢复核对前的采购值', exact=True).click()
            before = self.settlements(); changed = self.item(ctx, shop['id'])
            self.preview(page, revoke=True, status=409)
            expect(button(page, '读取当前核对资料')).to_be_enabled()
            assert self.item(ctx, shop['id']) == changed and self.settlements() == before
            self.passed('A real refund invalidates the signed preview; refresh preserves the amount draft and changed shopping blocks unsafe restoration')

    def lost_commit(self, browser):
        with self.flow(browser) as (ctx, page):
            pay, shop = self.payment(ctx), self.shopping(ctx)
            self.open_shopping(page, shop); self.draft(page, pay, shop); self.preview(page)
            reads = self.count_requests('GET', PREFIX + '/context')
            result = self.confirm(page, fault='after')
            assert result['result']['shopping']['actual'] == 7000
            assert self.count_requests('GET', PREFIX + '/context') == reads
            original = self.settlements(); self.navigation_locked(page)
            with self.drop_get(page, PREFIX + '/context') as dropped:
                button(page, '读取当前核对资料').click()
                self.settle(page, lambda: len(dropped) == 1)
                expect(button(page, '读取当前核对资料')).to_be_enabled()
                expect(button(page, '结束本次核对')).to_have_count(0)
            button(page, '读取当前核对资料').click()
            expect(button(page, '结束本次核对')).to_be_enabled()
            expect(page.get_by_test_id('settlement-unknown')).to_contain_text('当前资料不是本次操作的回执')
            assert self.settlements() == original and self.count_requests('POST', PREFIX + '/confirm') == 1
            button(page, '结束本次核对').click()
            expect(page.get_by_test_id('shopping-settlement-panel')).to_have_count(0)
            assert self.settlements() == original and self.count_requests('POST', PREFIX + '/confirm') == 1
            self.passed('Dropped real confirm 200 remains navigation-locked; failed and successful explicit GET recovery never resubmit or claim a receipt')

    def never_sent(self, browser):
        with self.flow(browser) as (ctx, page):
            pay, shop = self.payment(ctx), self.shopping(ctx)
            self.open_shopping(page, shop); self.draft(page, pay, shop); self.preview(page)
            before = self.settlements(); self.confirm(page, fault='before')
            assert self.item(ctx, shop['id']) == shop and self.settlements() == before
            self.write(ctx, 'DELETE', '/api/items/shopping/' + shop['id'], {'revision': shop['revision']})
            button(page, '读取当前核对资料').click()
            expect(button(page, '读取当前可用资料')).to_be_enabled()
            expect(button(page, '结束本次核对')).to_have_count(0)
            button(page, '读取当前可用资料').click()
            expect(button(page, '结束本次核对')).to_be_enabled()
            expect(page.get_by_test_id('settlement-unknown')).to_be_visible()
            assert self.settlements() == before and self.count_requests('POST', PREFIX + '/confirm') == 1
            button(page, '结束本次核对').click()
            expect(page.get_by_test_id('shopping-settlement-panel')).to_have_count(0)
            self.passed('Unsent confirmation and deleted target stay unknown; explicit unscoped read permits local exit with no settlement write or automatic retry')

    def saved_readback(self, browser):
        with self.flow(browser) as (ctx, page):
            pay = self.payment(ctx)
            for name, path in [('子面板', PREFIX + '/context'), ('父清单', '/api/state')]:
                shop = self.shopping(ctx, '合成' + name + '读回失败')
                self.open_shopping(page, shop); self.draft(page, pay, shop, '10.00'); self.preview(page)
                count = self.count_requests('POST', PREFIX + '/confirm')
                with self.drop_get(page, path) as dropped:
                    self.confirm(page, readback=False)
                    self.settle(page, lambda: len(dropped) == 1)
                    expect(button(page, '重新读取当前资料')).to_be_enabled()
                    expect(page.get_by_test_id('settlement-current')).to_have_count(0)
                    expect(button(page, '确认保存')).to_have_count(0)
                    self.navigation_locked(page)
                before = self.settlements()
                button(page, '重新读取当前资料').click()
                expect(button(page, '继续核对')).to_be_enabled()
                assert self.item(ctx, shop['id'])['actual'] == 1000
                assert self.settlements() == before and self.count_requests('POST', PREFIX + '/confirm') == count + 1
                button(page, '返回').click()
                expect(page.get_by_test_id('shopping-settlement-panel')).to_have_count(0)
            self.passed('Known confirmation survives both child context and parent state read failures; only fresh reads restore actions, never another POST')

    def privacy_late(self, browser):
        with self.flow(browser) as (ctx, page), ExitStack() as extras:
            pay, shop = self.payment(ctx), self.shopping(ctx)
            partner = self.context(browser, 2); extras.callback(partner.close)
            tv = self.context(browser, None); extras.callback(tv.close)
            self.get(partner, PREFIX + '/context?transactionId=' + pay['id'], 404)
            self.write(partner, 'POST', PREFIX + '/preview', {'operation': 'apply', 'paymentId': pay['id'],
                'shoppingId': shop['id'], 'shoppingRevision': shop['revision'], 'amountCents': 1000, 'done': False}, 404)
            pair = tv.request.post(self.base + '/api/pair/start', data={}).json()
            self.write(ctx, 'POST', '/api/pair/approve', {'code': pair['code'], 'name': '合成实付只读电视'})
            assert tv.request.post(self.base + '/api/pair/poll', data={'secret': pair['secret']}).json()['approved']
            self.get(tv, PREFIX + '/context', 403)
            for suffix in ('/preview', '/confirm'):
                denied = tv.request.post(self.base + PREFIX + suffix, data={}, headers={'Origin': self.base})
                assert denied.status == 403
            self.open_shopping(page, shop); self.draft(page, pay, shop)
            held = []; url = self.base + PREFIX + '/preview'
            def hold(route):
                response = route.fetch(max_redirects=0)
                assert response.status == 200 and 'set-cookie' not in response.headers
                held.append((route, response.status, response.headers, response.body()))
            page.route(url, hold)
            try:
                button(page, '预览共享变化').click(); self.settle(page, lambda: len(held) == 1)
                self.login(ctx, 2)
                route, status, headers, raw = held.pop(); route.fulfill(status=status, headers=headers, body=raw)
                expect(page.get_by_test_id('shopping-settlement-panel')).to_have_count(0, timeout=15000)
                expect(page.locator('body')).not_to_contain_text(pay['title'])
                assert self.count_requests('POST', PREFIX + '/confirm') == 0
                assert not self.settlements()['hub_shopping_settlements']
            finally:
                page.unroute(url, hold)
                for route, *_ in held: route.abort('failed')
            self.passed('Real partner and paired TV cannot read or confirm private sources; a late real preview after member-cookie replacement never appears or writes')

    def background_draft(self, browser):
        with self.flow(browser) as (ctx, page):
            pay, shop = self.payment(ctx), self.shopping(ctx)
            self.open_shopping(page, shop); self.draft(page, pay, shop, '12.34')
            original = self.settlements()
            for boundary in ('blur', 'hidden', 'offline'):
                self.preview(page)
                if boundary == 'hidden': visibility(page, True)
                elif boundary == 'blur': page.evaluate("window.dispatchEvent(new Event('blur'))")
                else:
                    ctx.set_offline(True)
                    page.evaluate("Object.defineProperty(navigator,'onLine',{configurable:true,get:()=>false});window.dispatchEvent(new Event('offline'))")
                expect(page.get_by_test_id('settlement-current')).to_have_count(0)
                expect(page.get_by_test_id('settlement-preview')).to_have_count(0)
                expect(page.locator('body')).not_to_contain_text(pay['title'])
                if boundary == 'hidden': visibility(page, False)
                elif boundary == 'blur': page.evaluate("window.dispatchEvent(new Event('focus'))")
                else:
                    ctx.set_offline(False)
                    page.evaluate("Object.defineProperty(navigator,'onLine',{configurable:true,get:()=>true});window.dispatchEvent(new Event('online'))")
                self.ready(page)
                expect(page.get_by_role('textbox', name='整项实付（元）', exact=True)).to_have_value('12.34')
                expect(page.get_by_test_id('settlement-preview')).to_have_count(0)
            assert self.settlements() == original and self.count_requests('POST', PREFIX + '/confirm') == 0
            self.passed('Blur, visibility and real offline transport conceal private previews; same-identity drafts return only after fresh reads and never submit')

    def capture(self, page, name, width, target):
        page.set_viewport_size({'width': width, 'height': 1000 if width >= 1280 else 844})
        page.evaluate('() => document.fonts.ready'); target.scroll_into_view_if_needed()
        page.evaluate('() => new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
        metrics = page.evaluate('''() => ({width:innerWidth,scroll:document.documentElement.scrollWidth,
          clipped:[...document.querySelectorAll('[data-testid="shopping-settlement-panel"] input,[data-testid="shopping-settlement-panel"] [role="button"],[data-testid="shopping-settlement-panel"] [role="radio"],[data-testid="shopping-settlement-panel"] [role="checkbox"]')]
          .filter(n=>{const b=n.getBoundingClientRect();return b.width>0&&b.height>0&&b.bottom>0&&b.top<innerHeight&&(b.left < -2||b.right>innerWidth+2)})
          .map(n=>({label:n.getAttribute('aria-label')||n.textContent,box:n.getBoundingClientRect().toJSON()}))})''')
        assert metrics['scroll'] <= width + 2 and not metrics['clipped'], metrics
        box = target.bounding_box(); assert box and box['height'] >= 44 and box['width'] >= 44, box
        path = self.out / f'{name}-{width}.png'; page.screenshot(path=str(path), full_page=False)
        self.report['screenshots'].append(dict(path=path.relative_to(self.out.parent).as_posix(), sha256=sha(path), metrics=metrics,
            target=box, scope='Actual visible viewport after scrolling; no full-page or physical-device claim.'))

    def layout(self, browser):
        with self.flow(browser) as (ctx, page):
            title = '合成长标题采购：出行准备需要逐件确认金额与收到状态，不将本人付款来源分享给其他成员'
            pay = self.payment(ctx, '合成私密付款长标题：旅行物品与保温水杯，原始编号只供本人核对')
            second = self.payment(ctx, '合成第二笔键盘选择付款')
            shop = self.shopping(ctx, title)
            for mode in ('light', 'dark'):
                pref = self.get(ctx, '/api/preferences')
                self.write(ctx, 'PUT', '/api/preferences', {'revision': pref['revision'], 'changes': {'colorMode': mode}})
                self.open_shopping(page, shop); self.draft(page, pay, shop, '12.34')
                page.wait_for_function("getComputedStyle(document.documentElement).colorScheme === '" + mode + "'")
                if mode == 'light':
                    selected = page.get_by_role('radio', name='选择付款：' + pay['title'], exact=True)
                    selected.focus(); selected.press('ArrowDown')
                    expect(page.get_by_role('radio', name='选择付款：' + second['title'], exact=True)).to_be_checked()
                    page.get_by_role('radio', name='选择付款：' + second['title'], exact=True).press('ArrowUp')
                    expect(selected).to_be_checked()
                    complete = page.get_by_role('checkbox', name='已买到', exact=True)
                    complete.focus(); complete.press('Space'); expect(complete).to_be_checked()
                    complete.press('Space'); expect(complete).not_to_be_checked()
                else:
                    self.actual(page, '/preview', lambda: (button(page, '预览共享变化').focus(), button(page, '预览共享变化').press('Enter')))
                    expect(page.get_by_test_id('settlement-preview')).to_be_visible()
                    ack = page.get_by_role('checkbox', name=ACK, exact=True)
                    ack.focus(); ack.press('Space'); expect(ack).to_be_checked()
                    expect(button(page, '确认保存')).to_be_enabled()
                for width in WIDTHS:
                    self.capture(page, 'settlement-' + mode, width, button(page, '预览共享变化' if mode == 'light' else '确认保存'))
                button(page, '返回').click(); button(page, '放弃输入并返回').click()
                expect(page.get_by_test_id('shopping-settlement-panel')).to_have_count(0)
            assert self.item(ctx, shop['id']) == shop and self.count_requests('POST', PREFIX + '/confirm') == 0
            self.passed('Four widths in both themes, scrolled draft/preview, long titles, 44px actions, radio arrows and single Space controls; keyboard preview remains write-free')

    @classmethod
    def run_scenarios(cls, root, bundle, report, out, browser):
        for name in CASES:
            case_out = out / name; case_out.mkdir()
            folder = None
            before = tuple(len(report[k]) for k in ('checks', 'pageErrors', 'externalRequests'))
            case = dict(name=name, passed=False, temporaryFixtureRemoved=False)
            try:
                with ExitStack() as lifecycle:
                    folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='expo-settlement-browser-')))
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
    assert changes_since_build <= {'tests/browser_expo_shopping_settlement_check.py', 'docs/EXPO-SHOPPING-SETTLEMENT-BROWSER.md'}, 'Only this harness and its documentation may differ from the tested build'
    names = subprocess.check_output(['git', '--no-replace-objects', 'ls-files', '-z'], cwd=root).decode('utf-8').rstrip('\0').split('\0')
    def hashes():
        return {name: sha(root / name) for name in names}
    def exports():
        return {p.relative_to(bundle).as_posix(): sha(p) for p in bundle.rglob('*') if p.is_file()}
    assert exports() == evidence['files'] and all(sha(root / name) == value for name, value in evidence['inputFiles'].items())
    assert sha(Path(__file__)) == sha(root / 'tests/browser_expo_shopping_settlement_check.py')
    out = Path(__file__).resolve().parents[1] / 'test-results' / ('expo-shopping-settlement-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], screenshots=[], scenarioResults=[], scenarioFailures=[],
        head=head, tree=git('rev-parse', 'HEAD^{tree}'), buildSourceHead=build_head, buildSourceTree=evidence['sourceTree'],
        buildInputsEqual=True, changedSinceBuild=sorted(changes_since_build), buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(out / 'executed-harness.py'), sourceRoot=str(root), bundleRoot=str(bundle),
        harnessHead=subprocess.check_output(['git', '--no-replace-objects', 'rev-parse', 'HEAD'], cwd=Path(__file__).resolve().parents[1], text=True).strip(),
        sourceHashesBefore=hashes(), bundleHashesBefore=exports(), productionWrites=0, realFinancialData=False, realCloud=False,
        physicalTelevision=False, scope='Ten independent temporary Flask/SQLite/HTTPS/Edge shopping-settlement scenarios; synthetic financial data, no cloud, production or device acceptance.')
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
                assert len(report['checks']) == len(CASES) and len(report['screenshots']) == 8
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
        report['temporaryFixtureRemoved'] = len(report['scenarioResults']) == len(CASES) and all(c['temporaryFixtureRemoved'] for c in report['scenarioResults'])
        report['passed'] = report['passed'] and report['sourceUnchanged'] and report['bundleUnchanged'] and report['fixturesUnchanged'] and report['sourceStillFrozen'] and report['temporaryFixtureRemoved']
        (out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(dict(passed=report['passed'], checks=len(report['checks']), report=str(out / 'result.json')), ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    raise SystemExit(main())
