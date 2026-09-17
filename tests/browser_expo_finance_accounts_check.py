"""Real, isolated Flask/SQLite/HTTPS/Edge acceptance for manual asset accounts.

Run only against a reviewed frozen source and its exact export. Successful
business responses are never mocked; faults drop or delay real HTTP traffic.
"""
import argparse
from contextlib import ExitStack, closing
from datetime import date, datetime, timedelta, timezone
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
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright
import browser_expo_finance_check as fixture
from browser_expo_finance_check import Run as BaseRun, button, sha, visibility

BASE = '/api/finance-accounts'
DAY = '2026-09-17'
CHECKS = 12
WIDTHS = (320, 390, 1280, 1920)
MARKER = '合成本人旅行备用账户'
LONG = '合成长标题账户：用于旅行、日常生活与未来家庭计划的本人手动资产记录，名称和机构并不表示已连接真实银行'


class Run(BaseRun):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        assert Path(self.source.__file__).resolve() == (self.root / 'app.py').resolve()
        self.report.setdefault('fixtureHashes', {})
        for path, name in ((Path(fixture.__file__), 'tests/browser_expo_finance_check.py'),
                           (Path(__file__), 'tests/browser_expo_finance_accounts_check.py')):
            assert sha(path) == sha(self.root / name), name
            old = self.report['fixtureHashes'].get(name)
            assert old is None or old == sha(path)
            self.report['fixtureHashes'][name] = sha(path)

    def clear_finance(self):
        pass  # Every scenario owns a fresh application and temporary database.

    def snapshot(self):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database)) as con:
            names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            return {n: con.execute('SELECT * FROM "' + n + '" ORDER BY rowid').fetchall() for n in names
                    if n not in {'users', 'member_sessions', 'member_session_browsers', 'attempts'}}

    def protected(self):
        result = self.snapshot()
        for name in ('finance_accounts', 'finance_account_valuations', 'finance_account_operations', 'audit', 'sqlite_sequence', 'settings'):
            result.pop(name, None)
        with closing(sqlite3.connect(self.database)) as con:
            result['settings_without_repaint'] = con.execute("SELECT * FROM settings WHERE id<>'meta' ORDER BY id").fetchall()
        return result

    def account_list(self, ctx, day=DAY, status='all'):
        return self.get(ctx, BASE + '?asOf=' + day + '&status=' + status)

    def history(self, ctx, account_id, page=1):
        return self.get(ctx, BASE + '/' + account_id + '/valuations?page=' + str(page) + '&pageSize=50')

    def operation(self, ctx, request_id):
        return self.get(ctx, BASE + '/operations/' + request_id)

    def seed_account(self, ctx, name=MARKER, amount=12345, day=DAY, kind='asset', currency='CNY', note='合成备注，仅用于本地验收'):
        return self.write(ctx, 'POST', BASE, {'requestId': uuid4().hex, 'revision': 0, 'name': name,
            'institution': '虚构机构', 'kind': kind, 'currency': currency, 'note': note,
            'valuation': {'asOf': day, 'amountCents': amount}}, 201)

    def revise(self, ctx, account_id, changes):
        account = self.history(ctx, account_id)['account']
        return self.write(ctx, 'PATCH', BASE + '/' + account_id,
            {'requestId': uuid4().hex, 'revision': account['revision'], 'changes': changes})

    def value(self, ctx, account_id, day, amount):
        account = self.history(ctx, account_id)['account']
        return self.write(ctx, 'PUT', BASE + '/' + account_id + '/valuations/' + day,
            {'requestId': uuid4().hex, 'revision': account['revision'], 'amountCents': amount})

    def ready_list(self, page):
        expect(button(page, '新增资产或负债账户')).to_be_enabled(timeout=15000)

    def open_accounts(self, page, navigate=True):
        if navigate:
            self.open_finance(page)
        expect(button(page, '我的资产账户')).to_be_enabled(timeout=15000)
        button(page, '我的资产账户').click()
        expect(page.get_by_test_id('finance-accounts-panel')).to_be_visible()
        # A returning unresolved operation intentionally locks the list controls.
        expect(page.get_by_role('textbox', name='查看日期', exact=True)).to_be_visible(timeout=15000)

    def list_back(self, page):
        button(page, '返回账户列表').click(); self.ready_list(page)

    def detail(self, page, name=MARKER):
        expect(button(page, '查看账户 ' + name)).to_be_enabled(timeout=15000)
        button(page, '查看账户 ' + name).click()
        self.detail_ready(page)

    def detail_ready(self, page):
        expect(page.get_by_test_id('finance-account-detail')).to_be_visible(timeout=15000)
        expect(button(page, '修改账户信息')).to_be_enabled(timeout=15000)

    def draft(self, page, name=MARKER, amount=None, day=DAY, kind='asset', currency='CNY'):
        button(page, '新增资产或负债账户').click()
        expect(page.get_by_test_id('finance-account-editor')).to_be_visible()
        page.get_by_role('textbox', name='账户名称', exact=True).fill(name)
        page.get_by_role('textbox', name='机构（可不填）', exact=True).fill('合成机构，非真实银行接入')
        page.get_by_role('textbox', name='账户备注', exact=True).fill('本人合成备注\n无真实财务数据')
        page.get_by_role('radio', name='资产账户' if kind == 'asset' else '负债账户', exact=True).click()
        page.get_by_role('textbox', name='原币种（三位大写字母）', exact=True).fill(currency)
        self.fill_value(page, day, amount)

    def fill_value(self, page, day, amount):
        page.get_by_role('textbox', name='估值日期', exact=True).fill(day)
        label = '金额未知' if amount is None else '填写已知金额'
        radio = page.get_by_role('radio', name=label, exact=True)
        radio.focus(); radio.press('Space')
        expect(radio).to_have_attribute('aria-checked', 'true')
        if amount is not None:
            page.get_by_role('textbox', name='估值金额', exact=True).fill(amount)

    def mutation(self, page, method, path, action, expected=200, drop=False, unsent=False, before_delivery=None):
        """Capture the actual response bytes before CDP can lose its body."""
        calls, url = [], self.base + path
        def intercept(route):
            assert route.request.method == method and route.request.url == url
            payload = route.request.post_data_json
            if unsent:
                route.abort('failed'); calls.append({'body': payload, 'status': None, 'result': None}); return
            response = route.fetch(max_redirects=0); raw = response.body(); result = json.loads(raw)
            if before_delivery:
                before_delivery(result)
            if drop:
                route.abort('failed')
            else:
                route.fulfill(status=response.status, headers=response.headers, body=raw)
            calls.append({'body': payload, 'status': response.status, 'result': result})
        page.route(url, intercept)
        try:
            action(); self.settle(page, lambda: len(calls) == 1)
            assert len(calls) == 1 and calls[0]['status'] == (None if unsent else expected), calls
            assert re.fullmatch('[a-f0-9]{32}', calls[0]['body']['requestId'])
            return calls[0]
        finally:
            page.unroute(url, intercept)

    def save(self, page, method='POST', path=BASE, **fault):
        return self.mutation(page, method, path, lambda: button(page, '保存账户记录').click(),
                             expected=201 if method == 'POST' else 200, **fault)

    def receipt_ready(self, page, request_id):
        expect(page.get_by_test_id('finance-accounts-receipt')).to_contain_text(request_id, timeout=15000)
        self.detail_ready(page)
        expect(page.get_by_test_id('finance-accounts-unknown')).to_have_count(0)
        expect(page.get_by_test_id('finance-account-editor')).to_have_count(0)

    def unknown_ready(self, page, request_id):
        expect(page.get_by_test_id('finance-accounts-unknown')).to_contain_text(request_id, timeout=15000)
        expect(button(page, '核对账户操作结果')).to_be_enabled(timeout=15000)
        expect(page.get_by_test_id('finance-account-detail')).to_have_count(0)

    def set_date(self, page, day):
        page.get_by_role('textbox', name='查看日期', exact=True).fill(day)
        button(page, '应用查看日期').click(); self.ready_list(page)

    def create_restart(self, browser):
        with self.flow(browser) as (ctx, page), ExitStack() as extras:
            protected = self.protected()
            self.open_accounts(page); self.ready_list(page); self.draft(page)
            first = self.save(page); self.receipt_ready(page, first['body']['requestId'])
            assert first['result']['result']['valuation']['amountCents'] is None
            self.list_back(page); self.draft(page, '合成明确零负债', '0.00', kind='liability')
            second = self.save(page); self.receipt_ready(page, second['body']['requestId'])
            assert second['result']['result']['valuation']['amountCents'] == 0
            assert self.count_requests('POST', BASE) == 2
            stored = self.account_list(ctx); assert len(stored['accounts']) == 2
            assert stored['totals'][0]['knownCount'] == stored['totals'][0]['unknownCount'] == 1
            self.restart(); page.reload(); self.open_accounts(page); self.ready_list(page)
            expect(page.get_by_test_id('finance-account-' + first['result']['accountId'])).to_contain_text('金额未知')
            expect(page.get_by_test_id('finance-account-' + second['result']['accountId'])).to_contain_text('CNY 0.00')
            other = self.context(browser); extras.callback(other.close)
            other_page = other.new_page(); self.open_accounts(other_page); self.ready_list(other_page)
            assert self.account_list(other) == stored and self.protected() == protected
            self.passed('UI saves unknown and known-zero accounts exactly once; refresh, new application instance and another browser retain exact private records without changing other finance data')

    def dates_and_history(self, browser):
        with self.flow(browser) as (ctx, page):
            rid = self.seed_account(ctx, day='2026-01-01', amount=1000)['accountId']
            self.open_accounts(page); self.detail(page)
            for day, amount in [('2026-01-02', None), ('2026-01-03', '0.00'), ('2026-01-01', '25.00')]:
                button(page, '记录估值').click(); self.fill_value(page, day, amount)
                saved = self.save(page, 'PUT', BASE + '/' + rid + '/valuations/' + day)
                self.receipt_ready(page, saved['body']['requestId'])
            history = self.history(ctx, rid)
            assert [(v['asOf'], v['amountCents']) for v in history['valuations']] == [('2026-01-03', 0), ('2026-01-02', None), ('2026-01-01', 2500)]
            self.list_back(page)
            for day, text in [('2025-12-31', '截至查看日期尚无估值记录'), ('2026-01-01', 'CNY 25.00'), ('2026-01-02', '金额未知'), ('2026-01-03', 'CNY 0.00')]:
                self.set_date(page, day)
                expect(page.get_by_test_id('finance-account-' + rid)).to_contain_text(text)
            for offset in range(3, 51):
                self.value(ctx, rid, (date(2026, 1, 1) + timedelta(days=offset)).isoformat(), offset * 100)
            self.detail(page); expect(page.get_by_test_id('finance-account-detail')).to_contain_text('第 1 / 2 页，共 51 项')
            button(page, '下一页').click(); self.detail_ready(page)
            expect(page.get_by_test_id('finance-account-detail')).to_contain_text('第 2 / 2 页，共 51 项')
            expect(page.get_by_test_id('finance-account-detail')).to_contain_text('CNY 25.00')
            assert self.history(ctx, rid, 2)['valuations'][0]['asOf'] == '2026-01-01'
            self.passed('Daily valuation UI distinguishes missing, unknown and zero, excludes future values, replaces only the same day and reads the actual second server history page')

    def archive_restore(self, browser):
        with self.flow(browser) as (ctx, page):
            rid = self.seed_account(ctx, amount=10000)['accountId']
            self.seed_account(ctx, name='合成负债', amount=25000, kind='liability')
            self.seed_account(ctx, name='合成未知美元', amount=None, currency='USD')
            self.open_accounts(page); self.detail(page)
            original = self.history(ctx, rid)['valuations']
            button(page, '归档账户').click()
            result = self.mutation(page, 'PATCH', BASE + '/' + rid, lambda: button(page, '确认归档账户').click())
            self.receipt_ready(page, result['body']['requestId']); expect(button(page, '记录估值')).to_be_disabled()
            assert self.history(ctx, rid)['valuations'] == original
            self.list_back(page); expect(page.get_by_test_id('finance-account-' + rid)).to_have_count(0)
            expect(page.locator('body')).to_contain_text('已知部分净额 CNY −250.00')
            page.get_by_role('radio', name='已归档账户', exact=True).click(); self.ready_list(page)
            self.detail(page); button(page, '恢复账户').click()
            result = self.mutation(page, 'PATCH', BASE + '/' + rid, lambda: button(page, '确认恢复账户').click())
            self.receipt_ready(page, result['body']['requestId']); expect(button(page, '记录估值')).to_be_enabled()
            self.list_back(page); page.get_by_role('radio', name='全部账户', exact=True).click(); self.ready_list(page)
            expect(page.locator('body')).to_contain_text('已知部分净额 CNY −150.00')
            expect(page.locator('body')).to_contain_text('暂无已知金额，不能确定净额')
            assert self.history(ctx, rid)['valuations'] == original
            self.passed('Explicit archive and restore preserve valuations, current filters update known original-currency subtotals, and wholly unknown currency is not presented as a zero net worth')

    def conflict_decisions(self, browser):
        with self.flow(browser) as (ctx, page):
            rid = self.seed_account(ctx)['accountId']; self.open_accounts(page); self.detail(page)
            for keep in (True, False):
                button(page, '修改账户信息').click()
                page.get_by_role('textbox', name='账户名称', exact=True).fill('合成未保存草稿')
                latest = self.revise(ctx, rid, {'name': '合成另一设备已保存', 'note': '另一设备的新备注'})
                before = self.snapshot(); writes = self.count_requests('PATCH', BASE + '/' + rid)
                failure = self.mutation(page, 'PATCH', BASE + '/' + rid,
                    lambda: button(page, '保存账户记录').click(), expected=409)
                expect(page.get_by_test_id('finance-account-conflict')).to_be_visible()
                expect(button(page, '读取最新账户核对')).to_be_enabled()
                assert failure['result']['code'] == 'revision_conflict' and self.snapshot() == before
                expect(page.get_by_role('textbox', name='账户名称', exact=True)).to_have_value('合成未保存草稿')
                button(page, '读取最新账户核对').click()
                choose = '保留我的账户草稿' if keep else '采用最新账户信息'
                expect(button(page, choose)).to_be_enabled(); button(page, choose).click()
                expect(button(page, '保存账户记录')).to_be_enabled()
                assert self.count_requests('PATCH', BASE + '/' + rid) == writes + 1 and self.snapshot() == before
                expected_name = '合成未保存草稿' if keep else '合成另一设备已保存'
                expect(page.get_by_role('textbox', name='账户名称', exact=True)).to_have_value(expected_name)
                saved = self.save(page, 'PATCH', BASE + '/' + rid); self.receipt_ready(page, saved['body']['requestId'])
                assert saved['body']['revision'] == latest['result']['account']['revision']
                assert self.history(ctx, rid)['account']['name'] == expected_name
            self.passed('Real CAS conflicts preserve draft and all database rows; current/keep choices never write automatically and the next explicit save uses the reviewed revision')

    def committed_recovery(self, browser):
        with self.flow(browser) as (ctx, page):
            self.open_accounts(page); self.draft(page, amount='10.00')
            first = self.save(page, drop=True); operation = first['body']['requestId']; rid = first['result']['accountId']
            self.unknown_ready(page, operation)
            self.revise(ctx, rid, {'name': '合成后来修改的当前名称'})
            before = self.snapshot(); button(page, '核对账户操作结果').click(); self.receipt_ready(page, operation)
            expect(page.get_by_test_id('finance-account-detail')).to_contain_text('合成后来修改的当前名称')
            assert self.snapshot() == before and self.count_requests('POST', BASE) == 1
            button(page, '记录估值').click(); self.fill_value(page, DAY, '20.00')
            lost = self.save(page, 'PUT', BASE + '/' + rid + '/valuations/' + DAY, drop=True)
            self.unknown_ready(page, lost['body']['requestId']); before = self.snapshot()
            retry = self.mutation(page, 'PUT', BASE + '/' + rid + '/valuations/' + DAY,
                lambda: button(page, '按原账户请求重试').click())
            self.receipt_ready(page, lost['body']['requestId'])
            assert retry['body'] == lost['body'] and retry['result']['replayed'] is True and self.snapshot() == before
            # A new genuine session can query history, but the historical value is not installed as current.
            self.value(ctx, rid, DAY, 3000); self.login(ctx); page.reload(); self.open_accounts(page); self.ready_list(page)
            page.get_by_role('textbox', name='账户操作编号', exact=True).fill(operation)
            button(page, '使用账户操作编号').click(); self.unknown_ready(page, operation)
            button(page, '核对账户操作结果').click(); self.receipt_ready(page, operation)
            expect(page.get_by_test_id('finance-account-detail')).to_contain_text('CNY 30.00')
            assert self.count_requests('POST', BASE) == 1 and self.count_requests('PUT', BASE + '/' + rid + '/valuations/' + DAY) == 2
            self.passed('Committed lost replies recover by exact GET or identical request replay without duplicate writes; a new session reads history while showing the latest account and valuation')

    def unsent_end_review(self, browser):
        with self.flow(browser) as (ctx, page):
            self.open_accounts(page); self.draft(page, amount='0.00'); before = self.snapshot()
            lost = self.save(page, unsent=True); operation = lost['body']['requestId']; self.unknown_ready(page, operation)
            expect(button(page, '结束本次核对')).to_have_count(0)
            assert self.operation(ctx, operation)['found'] is False and self.snapshot() == before
            button(page, '核对账户操作结果').click(); self.unknown_ready(page, operation)
            expect(button(page, '结束本次核对')).to_be_enabled()
            button(page, '结束本次核对').click()
            expect(page.get_by_role('heading', name='结束本次核对？', exact=True)).to_be_visible()
            expect(page.locator('body')).to_contain_text('原请求仍可能完成')
            assert self.snapshot() == before
            button(page, '确认结束账户核对').click(); self.ready_list(page)
            expect(page.get_by_test_id('finance-accounts-unknown')).to_have_count(0)
            expect(page.get_by_role('textbox', name='账户操作编号', exact=True)).to_have_value(operation)
            assert self.count_requests('POST', BASE) == 1 and self.snapshot() == before
            assert self.account_list(ctx)['accounts'] == []
            self.passed('An unsent write stays unknown despite found:false; fresh list and exact lookup enable a second explicit end decision, preserving the ID and never creating a replacement')

    def confirmed_read_failure(self, browser):
        with self.flow(browser) as (ctx, page):
            rid = self.seed_account(ctx)['accountId']; self.open_accounts(page); self.detail(page)
            button(page, '修改账户信息').click(); page.get_by_role('textbox', name='账户名称', exact=True).fill('合成已确认的新名称')
            losses = []
            pattern = re.compile(re.escape(self.base + BASE) + r'\?asOf=.*')
            def lose_read(route):
                response = route.fetch(max_redirects=0); raw = response.body()
                assert response.status == 200 and json.loads(raw)['accounts'][0]['name'] == '合成已确认的新名称'
                losses.append(True); route.abort('failed')
            page.route(pattern, lose_read)
            try:
                saved = self.save(page, 'PATCH', BASE + '/' + rid)
                expect(page.get_by_test_id('finance-accounts-receipt')).to_contain_text(saved['body']['requestId'])
                expect(button(page, '读取当前账户')).to_be_enabled(timeout=15000)
                assert losses == [True]
                expect(page.get_by_test_id('finance-account-detail')).to_have_count(0)
                expect(button(page, '修改账户信息')).to_have_count(0)
                expect(button(page, '记录估值')).to_have_count(0)
            finally:
                page.unroute(pattern, lose_read)
            before = self.snapshot(); button(page, '读取当前账户').click(); self.detail_ready(page)
            expect(page.get_by_test_id('finance-account-detail')).to_contain_text('合成已确认的新名称')
            assert self.snapshot() == before and self.count_requests('PATCH', BASE + '/' + rid) == 1
            self.passed('Confirmed write followed by a dropped real current GET invalidates old actions; only a manual fresh read restores current details without another write')

    def private_boundaries(self, browser):
        with self.flow(browser) as (ctx, page), ExitStack() as extras:
            saved = self.seed_account(ctx); rid, operation = saved['accountId'], saved['requestId']
            self.open_accounts(page); self.ready_list(page)
            partner = self.context(browser, 2); extras.callback(partner.close)
            partner_page = partner.new_page(); self.open_accounts(partner_page); self.ready_list(partner_page)
            expect(partner_page.locator('body')).not_to_contain_text(MARKER)
            assert self.account_list(partner)['accounts'] == [] and not self.operation(partner, operation)['found']
            self.get(partner, BASE + '/' + rid + '/valuations', 404)
            self.write(partner, 'PATCH', BASE + '/' + rid, {'requestId': uuid4().hex, 'revision': 1, 'changes': {'name': '禁止'}}, 404)
            invite = self.write(ctx, 'POST', '/api/spaces/invitations', {}, 201)['invitation']
            family = self.write(ctx, 'POST', '/api/spaces/redeem', {'invitation': invite, 'name': '合成资产第二家庭', 'slug': 'asset-other',
                'MEMBER1_PASSWORD': 'testing-password-one', 'MEMBER2_PASSWORD': 'testing-password-two'}, 201)
            foreign = self.context(browser, member=None); extras.callback(foreign.close)
            assert foreign.request.get(self.base + family['entry']).status == 200; self.login(foreign)
            assert self.account_list(foreign)['accounts'] == [] and not self.operation(foreign, operation)['found']
            self.get(foreign, BASE + '/' + rid + '/valuations', 404)
            tv = self.context(browser, member=None); extras.callback(tv.close)
            pair = tv.request.post(self.base + '/api/pair/start', data={}).json()
            self.write(ctx, 'POST', '/api/pair/approve', {'code': pair['code'], 'name': '合成只读账户电视'})
            assert tv.request.post(self.base + '/api/pair/poll', data={'secret': pair['secret']}).json()['approved']
            self.get(tv, BASE + '?asOf=' + DAY, 403)
            assert tv.request.post(self.base + BASE, data={}).status == 403
            tv_page = tv.new_page(); tv_page.goto(self.base + '/app/tv')
            expect(tv_page.get_by_test_id('expo-tv-board')).to_be_visible(timeout=15000)
            expect(tv_page.get_by_test_id('finance-accounts-panel')).to_have_count(0)
            expect(tv_page.locator('body')).not_to_contain_text(MARKER)
            anonymous = self.context(browser, member=None); extras.callback(anonymous.close)
            self.get(anonymous, BASE + '?asOf=' + DAY, 401)
            assert self.history(ctx, rid)['account']['name'] == MARKER
            self.passed('Actual partner, signed second household, paired TV and anonymous requests cannot read or alter private accounts; TV never renders the member panel')

    def late_identity(self, browser):
        with self.flow(browser) as (ctx, page), ExitStack() as extras:
            self.open_accounts(page); self.draft(page, amount='12.34')
            def switch(_receipt):
                self.login(ctx, 2)
            saved = self.save(page, before_delivery=switch)
            expect(page.get_by_test_id('finance-accounts-panel')).to_have_count(0, timeout=15000)
            expect(page.locator('body')).not_to_contain_text(MARKER)
            assert self.account_list(ctx)['accounts'] == [] and not self.operation(ctx, saved['body']['requestId'])['found']
            self.open_accounts(page, navigate=False); self.ready_list(page)
            expect(page.get_by_test_id('finance-accounts-unknown')).to_have_count(0)
            owner = self.context(browser); extras.callback(owner.close)
            assert self.operation(owner, saved['body']['requestId'])['found'] is True
            assert self.count_requests('POST', BASE) == 1
            self.passed('A real create commits before the cookie switches member; the late response and private draft are discarded, while only the original owner can recover its receipt')

    def lifecycle_draft(self, browser):
        with self.flow(browser) as (ctx, page):
            rid = self.seed_account(ctx)['accountId']; self.open_accounts(page); self.detail(page)
            button(page, '修改账户信息').click(); page.get_by_role('textbox', name='账户名称', exact=True).fill('合成仅内存草稿')
            before = self.snapshot(); visibility(page, True)
            expect(page.get_by_test_id('finance-account-editor')).to_have_count(0)
            expect(page.locator('body')).not_to_contain_text(MARKER)
            visibility(page, False)
            expect(page.get_by_role('textbox', name='账户名称', exact=True)).to_have_value('合成仅内存草稿', timeout=15000)
            expect(button(page, '保存账户记录')).to_be_enabled()
            assert self.snapshot() == before
            ctx.set_offline(True); expect(page.get_by_test_id('finance-account-editor')).to_have_count(0)
            ctx.set_offline(False)
            expect(page.get_by_role('textbox', name='账户名称', exact=True)).to_have_value('合成仅内存草稿', timeout=15000)
            visibility(page, True); self.revise(ctx, rid, {'name': '合成后台另一设备修改'})
            visibility(page, False)
            expect(page.get_by_test_id('finance-account-conflict')).to_be_visible(timeout=15000)
            expect(page.get_by_role('textbox', name='账户名称', exact=True)).to_have_value('合成仅内存草稿')
            expect(button(page, '保存账户记录')).to_be_disabled()
            assert self.count_requests('PATCH', BASE + '/' + rid) == 0
            self.passed('Hidden and offline views hide private content and preserve the same-identity draft; fresh unchanged reads restore it, changed revision requires review and never writes automatically')

    def navigation_recovery(self, browser):
        with self.flow(browser) as (ctx, page):
            page.set_viewport_size({'width': 1280, 'height': 1000})
            self.open_finance(page); self.ledger(page, '2026-08'); self.open_accounts(page, navigate=False)
            self.draft(page); button(page, '首页').click()
            expect(page.get_by_test_id('finance-account-editor')).to_be_visible()
            button(page, '返回财务').click(); expect(button(page, '放弃并返回财务')).to_be_visible()
            button(page, '继续核对').click()
            lost = self.save(page, unsent=True); operation = lost['body']['requestId']; self.unknown_ready(page, operation)
            button(page, '首页').click(); self.unknown_ready(page, operation)
            button(page, '保留操作编号并返回').click(); button(page, '保留编号并返回财务').click()
            expect(page.get_by_test_id('finance-accounts-panel')).to_have_count(0)
            expect(page.get_by_role('textbox', name='账本月份', exact=True)).to_have_value('2026-08')
            self.open_accounts(page, navigate=False); self.unknown_ready(page, operation)
            expect(button(page, '按原账户请求重试')).to_have_count(0)
            button(page, '核对账户操作结果').click(); self.unknown_ready(page, operation)
            button(page, '结束本次核对').click(); button(page, '确认结束账户核对').click(); self.ready_list(page)
            assert self.account_list(ctx)['accounts'] == [] and self.count_requests('POST', BASE) == 1
            button(page, '返回财务').click(); expect(button(page, '我的资产账户')).to_be_enabled(timeout=15000)
            button(page, '首页').click(); expect(page.get_by_test_id('home-content')).to_be_visible(timeout=15000)
            self.passed('Parent navigation protects drafts and unknown writes; explicit return preserves month and only the opaque ID, reentry offers readback, and explicit resolution unlocks navigation')

    def capture(self, page, name, width, target):
        page.set_viewport_size({'width': width, 'height': 1080 if width >= 1280 else 844})
        page.evaluate('() => document.fonts.ready'); target.scroll_into_view_if_needed(); page.wait_for_timeout(800)
        page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
        metrics = page.evaluate('''() => ({width:innerWidth,scroll:document.documentElement.scrollWidth,
          clipped:[...document.querySelectorAll('[data-testid="finance-accounts-panel"] input,[data-testid="finance-accounts-panel"] textarea,[data-testid="finance-accounts-panel"] [role="button"],[data-testid="finance-accounts-panel"] [role="radio"]')]
          .filter(n=>{const r=n.getBoundingClientRect();return r.width>0&&r.height>0&&r.bottom>0&&r.top<innerHeight&&(r.right>innerWidth+2||r.left< -2)})
          .map(n=>({label:n.getAttribute('aria-label')||n.textContent,box:n.getBoundingClientRect().toJSON()}))})''')
        assert metrics['scroll'] <= width + 2 and not metrics['clipped'], metrics
        box = button(page, '返回财务').bounding_box(); assert box and box['width'] >= 44 and box['height'] >= 44
        path = self.out / f'{name}-{width}.png'; page.screenshot(path=str(path), full_page=False)
        self.report['screenshots'].append({'path': path.relative_to(self.out.parent).as_posix(), 'sha256': sha(path),
            'width': width, 'metrics': metrics, 'scope': 'Settled visible viewport after scrolling; inner ScrollView not fully captured.'})

    def widths_and_themes(self, browser):
        with self.flow(browser) as (ctx, page):
            self.open_accounts(page); self.draft(page, name=LONG, amount='0.00')
            page.get_by_role('textbox', name='账户备注', exact=True).fill('合成完整备注，页面需要保留本人输入的中文与换行。\n' * 8)
            for width in WIDTHS:
                self.capture(page, 'accounts-editor-light', width, button(page, '保存账户记录'))
                for role, label, size in [('button', '保存账户记录', 44), ('radio', '填写已知金额', 48)]:
                    box = page.get_by_role(role, name=label, exact=True).bounding_box()
                    assert box and box['height'] >= size and box['width'] >= 44
            saved = self.mutation(page, 'POST', BASE,
                lambda: (button(page, '保存账户记录').focus(), button(page, '保存账户记录').press('Enter')), expected=201)
            self.receipt_ready(page, saved['body']['requestId']); assert self.count_requests('POST', BASE) == 1
            for i in range(10):
                self.seed_account(ctx, name=f'合成分页账户 {i:02}', amount=None if i % 2 else 0, currency='USD' if i % 2 else 'CNY')
            preferences = self.get(ctx, '/api/preferences')
            self.write(ctx, 'PUT', '/api/preferences', {'revision': preferences['revision'], 'changes': {'colorMode': 'dark', 'density': 'compact'}})
            page.reload(); self.open_accounts(page); self.ready_list(page)
            page.wait_for_function("getComputedStyle(document.documentElement).colorScheme === 'dark'")
            expect(page.locator('body')).to_contain_text('第 1 / 2 页，共 11 项')
            button(page, '下一页').click(); expect(page.locator('body')).to_contain_text('第 2 / 2 页，共 11 项')
            page.get_by_role('textbox', name='搜索全部已载入账户', exact=True).fill(LONG)
            expect(page.locator('body')).to_contain_text('第 1 / 1 页，共 1 项')
            row = page.get_by_test_id('finance-account-' + saved['result']['accountId'])
            for width in WIDTHS:
                self.capture(page, 'accounts-list-dark', width, row)
            self.detail(page, LONG)
            for width in WIDTHS:
                self.capture(page, 'accounts-detail-dark', width, page.get_by_test_id('finance-account-detail'))
                if width <= 390:
                    assert page.get_by_text(LONG, exact=True).bounding_box()['height'] > 40
            self.passed('Four widths capture populated light editor and dark compact list/detail; long text fits, list search spans pages, accessible controls meet targets and keyboard save writes once')

    @classmethod
    def run_scenarios(cls, root, bundle, report, out, browser):
        scenarios = tuple((name, name, ()) for name in (
            'create_restart', 'dates_and_history', 'archive_restore', 'conflict_decisions',
            'committed_recovery', 'unsent_end_review', 'confirmed_read_failure',
            'private_boundaries', 'late_identity', 'lifecycle_draft', 'navigation_recovery', 'widths_and_themes'))
        for name, method, args in scenarios:
            case_out = out / name; case_out.mkdir(); folder = None
            before = (len(report['checks']), len(report['pageErrors']), len(report['externalRequests']))
            case = {'name': name, 'passed': False, 'temporaryFixtureRemoved': False}
            try:
                with ExitStack() as lifecycle:
                    folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='expo-finance-accounts-browser-')))
                    case['temporaryDirectory'] = str(folder)
                    run = cls(root, bundle, folder, report, case_out, lifecycle)
                    getattr(run, method)(browser, *args)
                assert not folder.exists()
                assert len(report['checks']) == before[0] + 1 and len(report['pageErrors']) == before[1] and len(report['externalRequests']) == before[2]
                case['passed'] = True
            except Exception:
                del report['checks'][before[0]:]
                failure = traceback.format_exc(); (case_out / 'failure.txt').write_text(failure, encoding='utf-8')
                report['scenarioFailures'].append({'scenario': name, 'traceback': failure, 'artifacts': case_out.name})
                print('FAIL ' + name + '\n' + failure, flush=True)
            finally:
                case['temporaryFixtureRemoved'] = folder is not None and not folder.exists(); report['scenarioResults'].append(case)
        assert not report['scenarioFailures'], 'See independent scenarioFailures; no failed check counted as passed'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path); parser.add_argument('--expected-head', required=True)
    parser.add_argument('--bundle', required=True, type=Path); parser.add_argument('--expected-build-evidence', required=True)
    args = parser.parse_args(); root, bundle = args.source_root.resolve(), args.bundle.resolve()
    assert re.fullmatch('[a-f0-9]{40}', args.expected_head) and re.fullmatch('[a-f0-9]{64}', args.expected_build_evidence)
    def git(*command):
        return subprocess.check_output(['git', '--no-replace-objects', *command], cwd=root, text=True).strip()
    head = git('rev-parse', 'HEAD'); assert head == args.expected_head and not git('status', '--porcelain=v1')
    evidence_path = bundle.parent / 'build-evidence.json'; assert sha(evidence_path) == args.expected_build_evidence
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    assert evidence['sourceHead'] == head and evidence['sourceTree'] == git('rev-parse', 'HEAD^{tree}')
    names = subprocess.check_output(['git', '--no-replace-objects', 'ls-files', '-z'], cwd=root).decode('utf-8').rstrip('\0').split('\0')
    def hashes(): return {name: sha(root / name) for name in names}
    def exports(): return {p.relative_to(bundle).as_posix(): sha(p) for p in bundle.rglob('*') if p.is_file()}
    assert exports() == evidence['files'] and all(sha(root / name) == digest for name, digest in evidence['inputFiles'].items())
    assert sha(Path(__file__)) == sha(root / 'tests/browser_expo_finance_accounts_check.py')
    out = Path(__file__).resolve().parents[1] / 'test-results' / ('expo-finance-accounts-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True); shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], screenshots=[], scenarioResults=[], scenarioFailures=[], head=head, tree=evidence['sourceTree'],
        buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(out / 'executed-harness.py'), sourceHashesBefore=hashes(), bundleHashesBefore=exports(),
        productionWrites=0, realFinancialData=False, realCloud=False, physicalTelevision=False,
        scope='Twelve independent real local Flask/SQLite/HTTPS/Edge fixtures with synthetic manual accounts only. Real successful HTTP responses are captured before forwarding; faults drop or delay real requests or responses. No cloud, bank or production access. Visibility is simulated and offline uses browser network state. Screenshots require a separate visible-viewport review; no deployment or migration acceptance.')
    original_connect = socket.socket.connect
    def local_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
            report['externalRequests'].append({'kind': 'non-loopback socket'}); raise AssertionError('External network forbidden')
        return original_connect(sock, address)
    try:
        with patch.object(socket.socket, 'connect', local_connect), sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            try:
                Run.run_scenarios(root, bundle, report, out, browser)
                assert len(report['checks']) == CHECKS and len(report['screenshots']) == 12
                assert not report['pageErrors'] and not report['externalRequests']; report['passed'] = True
            finally: browser.close()
    except Exception:
        report['passed'] = False; report['failure'] = traceback.format_exc(); print(report['failure'], flush=True)
    finally:
        report['sourceHashesAfter'] = hashes(); report['bundleHashesAfter'] = exports()
        report['sourceUnchanged'] = report['sourceHashesBefore'] == report['sourceHashesAfter']
        report['bundleUnchanged'] = report['bundleHashesBefore'] == report['bundleHashesAfter']
        report['sourceStillFrozen'] = git('rev-parse', 'HEAD') == head and not git('status', '--porcelain=v1')
        report['temporaryFixtureRemoved'] = len(report['scenarioResults']) == CHECKS and all(case['temporaryFixtureRemoved'] for case in report['scenarioResults'])
        report['passed'] = report['passed'] and report['sourceUnchanged'] and report['bundleUnchanged'] and report['sourceStillFrozen'] and report['temporaryFixtureRemoved']
        (out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'report': str(out / 'result.json')}, ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    raise SystemExit(main())
