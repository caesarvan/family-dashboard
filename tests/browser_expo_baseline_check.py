"""Reviewed-source-only Expo baseline browser checks with synthetic local data.

Each scenario owns a fresh Flask app, SQLite household, TLS listener and browser
context. Business DTOs come from genuine import/GET endpoints (legacy fixtures
use the actual database importer). Interception only delays or drops real GETs.
"""
import argparse
from contextlib import ExitStack, closing
from copy import deepcopy
from datetime import datetime, timezone
import importlib
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
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright
import browser_expo_finance_check as fixture
from browser_expo_finance_check import Run as BaseRun, button, sha, visibility

PRIVATE = '/api/finance-baseline/private'
IMPORTS = '/api/finance-baseline/imports/'
WIDTHS = (320, 390, 1280, 1920)
CHECKS = 9
MARKER = '合成本人记录'
LONG_TITLE = '合成长标题：用于核对旅行备用金和家庭长期资金的原始记录，需要完整显示账户说明及记录日期，所有内容均为虚构数据'


def heading(page, name):
    return page.get_by_role('heading', name=name, exact=True)


def card(page, title):
    return heading(page, title).locator('xpath=ancestor::*[@data-testid="section-card-content"][1]')


class Run(BaseRun):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        assert Path(self.source.__file__).resolve() == (self.root / 'app.py').resolve()
        self.source_fixture = importlib.import_module('test_finance_source_bridge')
        self.observation_fixture = importlib.import_module('test_spending_observations')
        self.baseline_module = importlib.import_module('finance_baseline')
        self.report.setdefault('fixtureHashes', {})
        for file, name in ((Path(fixture.__file__), 'tests/browser_expo_finance_check.py'),
                           (Path(__file__), 'tests/browser_expo_baseline_check.py'),
                           (Path(self.source_fixture.__file__), 'tests/test_finance_source_bridge.py'),
                           (Path(self.observation_fixture.__file__), 'tests/test_spending_observations.py'),
                           (Path(self.baseline_module.__file__), 'finance_baseline.py')):
            assert sha(file) == sha(self.root / name), name
            previous = self.report['fixtureHashes'].get(name)
            assert previous is None or previous == sha(file)
            self.report['fixtureHashes'][name] = sha(file)

    def clear_finance(self):
        pass  # Every case has a new database; do not reset inherited finance rows.

    def snapshot(self):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        tables = ('finance_baselines', 'finance_source_receipts', 'finance_spending_observations',
                  'finance_spending_receipts', 'hub_transactions', 'hub_investments', 'private_finance', 'settings')
        with closing(sqlite3.connect(self.database)) as con:
            return {name: sorted(con.execute('SELECT * FROM "' + name + '"').fetchall(), key=repr) for name in tables}

    def candidate(self, marker=MARKER, extra=0):
        value = self.source_fixture.synthetic_candidate()
        value['assets'][0]['label'] = marker + ' · 存款'
        value['liabilities'][0]['label'] = marker + ' · 贷款'
        value['income'][0]['label'] = marker + ' · 历史收入'
        base = deepcopy(value['assets'][0])
        for key, label, amount, currency, include, reason in (
            ('unknown', marker + ' · 未估值美元', None, 'USD', False, '尚未取得估值'),
            ('zero', marker + ' · 零余额', 0, 'CNY', True, ''),
            ('foreign', marker + ' · 已知美元', 50000, 'USD', False, '外币单列，未换算汇率'),
            ('long', LONG_TITLE, 0, 'CNY', True, '')):
            value['assets'].append({**base, 'id': key, 'label': label, 'amountCents': amount,
                'currency': currency, 'includedInRecordedSubtotal': include, 'exclusionReason': reason})
        for index in range(extra):
            value['assets'].append({**base, 'id': f'page-{index:03d}', 'label': f'合成分页来源 {index:03d}', 'amountCents': 0})
        return value

    def seed_baseline(self, ctx, marker=MARKER, extra=0, legacy=False):
        candidate = self.candidate(marker, extra)
        if legacy:
            owner = self.get(ctx, '/api/me')['user']['id']
            _, private, shared, _ = self.source_fixture.normalize_candidate(candidate, owner)
            private.pop('sourceBridge')
            private['importedAt'] = shared['importedAt'] = '2026-09-14 12:00+0800'
            private['spending'] = {'monthly': [{'period': '2026-09', 'netSpendCents': 0, 'transactionCount': 0}], 'note': '合成旧报告未记录覆盖范围'}
            assert self.database.resolve().is_relative_to(self.folder.resolve())
            with closing(sqlite3.connect(self.database)) as con:
                with con:
                    self.baseline_module.import_baseline(con, private, shared)
        else:
            state = self.get(ctx, IMPORTS + 'status')['current']
            preview = self.write(ctx, 'POST', IMPORTS + 'preview', {'candidate': candidate,
                'expectedRevision': state['revision'] if state else 0, 'expectedSourceDigest': state['sourceDigest'] if state else None})
            self.write(ctx, 'POST', IMPORTS + 'confirm', {'candidate': candidate, 'previewToken': preview['previewToken']})
        result = self.get(ctx, PRIVATE)
        assert result['assets'] and result['totals']['recordedAssetCents'] == 12000
        return result

    def seed_observation(self, ctx):
        before = self.get(ctx, PRIVATE)
        candidate = self.observation_fixture.observation(net=-100)
        candidate['spending']['monthly'].insert(0, deepcopy(before['spending']['monthly'][0]))
        status = self.get(ctx, IMPORTS + 'status?mode=spending_observation')
        preview = self.write(ctx, 'POST', IMPORTS + 'preview', {'mode': 'spending_observation', 'candidate': candidate,
            **status['expected'], 'acknowledgeUnknownPreviousCoverage': False})
        self.write(ctx, 'POST', IMPORTS + 'confirm', {'mode': 'spending_observation', 'candidate': candidate, 'previewToken': preview['previewToken']})
        result = self.get(ctx, PRIVATE)
        assert result['spendingObservation']['origin'] == 'spending_observation'
        assert result['assets'] == before['assets'] and result['revision'] == before['revision']
        return result

    def create_family(self, ctx):
        invitation = self.write(ctx, 'POST', '/api/spaces/invitations', {}, 201)['invitation']
        return self.write(ctx, 'POST', '/api/spaces/redeem', {'invitation': invitation,
            'name': '合成资产第二家庭', 'slug': 'baseline-other', 'MEMBER1_PASSWORD': 'testing-password-one',
            'MEMBER2_PASSWORD': 'testing-password-two'}, 201)

    def open_panel(self, page, navigate=True):
        if navigate:
            self.open_finance(page)
        expect(button(page, '我的资产与来源报告')).to_be_enabled(timeout=15000)
        button(page, '我的资产与来源报告').click()
        expect(heading(page, '我的资产与来源报告')).to_be_visible()

    def loaded(self, page):
        expect(page.get_by_test_id('finance-baseline-content')).to_be_visible(timeout=15000)
        expect(page.get_by_label('正在核对本人来源报告', exact=True)).to_have_count(0)

    def category(self, page, title):
        button(page, title + '分类').click()
        if title != '概览':
            expect(page.get_by_test_id('baseline-search')).to_be_visible()

    def read_only(self, mark, before):
        assert self.snapshot() == before, 'Read-only viewer changed a financial row'
        calls = [request for request in self.requests[mark:] if request['path'].startswith('/api/finance-baseline/')]
        assert calls and all(request['method'] == 'GET' and request['path'] == PRIVATE and not request['query'] for request in calls), calls

    def entry_and_empty(self, browser):
        with self.flow(browser) as (ctx, page):
            assert self.get(ctx, PRIVATE) is None
            self.open_finance(page); button(page, '我的账本').click()
            field = page.get_by_role('textbox', name='账本月份', exact=True)
            field.fill('2026-08'); button(page, '查看月份').click()
            expect(button(page, '刷新账本')).to_be_enabled()
            self.open_panel(page, navigate=False)
            expect(page.get_by_text('还没有本人资产来源记录', exact=True)).to_be_visible(timeout=15000)
            button(page, '返回财务').click()
            expect(field).to_have_value('2026-08'); expect(button(page, '刷新账本')).to_be_enabled()
            self.seed_baseline(ctx, legacy=True)
            before, mark = self.snapshot(), len(self.requests)
            self.open_panel(page, navigate=False); self.loaded(page)
            expect(page.locator('body')).to_contain_text('2026/09/14 12:00（北京时间）')
            self.category(page, '消费观察')
            expect(card(page, '2026-09 · 币种待核对')).to_contain_text('币种待核对 0.00')
            expect(card(page, '2026-09 · 币种待核对')).to_contain_text('金额待核对')
            expect(page.locator('body')).to_contain_text('日期待核对')
            self.category(page, '来源说明'); expect(page.get_by_text('旧记录未提供结构化来源清单', exact=True)).to_be_visible()
            button(page, '返回财务').click(); expect(field).to_have_value('2026-08')
            expect(button(page, '刷新账本')).to_be_enabled(); self.read_only(mark, before)
            self.passed('Real null and legacy source states are distinct; timezone-without-seconds renders, unknown currency is not CNY, return keeps selected ledger month')

    def values_and_observation(self, browser):
        with self.flow(browser) as (ctx, page):
            self.seed_baseline(ctx); record = self.seed_observation(ctx)
            before, mark = self.snapshot(), len(self.requests)
            self.open_panel(page); self.loaded(page)
            summary = card(page, '已录入的人民币记录')
            expect(summary).to_contain_text('CNY 120.00'); expect(summary).to_contain_text('CNY 45.00')
            expect(summary).to_contain_text('整体资产、负债和净资产仍待核对'); expect(summary).not_to_contain_text('620.00')
            self.category(page, '资产')
            expect(card(page, MARKER + ' · 未估值美元')).to_contain_text('金额待核对')
            expect(card(page, MARKER + ' · 零余额')).to_contain_text('CNY 0.00')
            expect(card(page, MARKER + ' · 已知美元')).to_contain_text('USD 500.00')
            expect(card(page, MARKER + ' · 已知美元')).to_contain_text('未计入人民币小计')
            self.category(page, '负债'); expect(card(page, MARKER + ' · 贷款')).to_contain_text('CNY 45.00')
            self.category(page, '收入'); expect(card(page, MARKER + ' · 历史收入')).to_contain_text('CNY 98.00')
            expect(page.locator('body')).to_contain_text('不推断为当前月收入')
            self.category(page, '消费观察'); expect(card(page, '2026-09 · CNY')).to_contain_text('CNY -1.00')
            expect(page.locator('body')).to_contain_text('消费报告更新没有改写资产记录。')
            expect(card(page, '消费报告覆盖')).to_contain_text('2026/09/15 08:00（北京时间）')
            expect(card(page, '消费报告覆盖')).to_contain_text('2025-09-15 至 2026-09-15')
            expect(card(page, '消费报告覆盖')).to_contain_text('无法读取的账单：2')
            self.category(page, '来源说明')
            expect(card(page, '资产来源报告')).to_contain_text('2026/09/14 10:00（北京时间）')
            expect(page.locator('body')).to_contain_text('04_Banking/accounts.csv')
            assert page.get_by_test_id('finance-baseline-content').get_by_role('link').count() == 0
            assert self.get(ctx, PRIVATE) == record; self.read_only(mark, before)
            self.passed('Real imported amounts keep null/zero/USD/income separate; later negative-net observation preserves assets and has independent coverage/source dates; file paths are text only')

    def pagination_and_search(self, browser):
        with self.flow(browser) as (ctx, page):
            record = self.seed_baseline(ctx, extra=25); before, mark = self.snapshot(), len(self.requests)
            self.open_panel(page); self.loaded(page); self.category(page, '资产')
            titles = [item['label'] for item in record['assets']]; seen = []
            for index in range(3):
                expect(page.locator('body')).to_contain_text(f'第 {index+1} / 3 页 · 共 30 条')
                present = [name for name in titles if heading(page, name).count()]
                assert len(present) == 10, present
                seen.extend(present)
                if index < 2: button(page, '下一页记录').click()
            assert sorted(seen) == sorted(titles); expect(button(page, '下一页记录')).to_be_disabled()
            page.get_by_test_id('baseline-search').fill('合成分页来源 024')
            expect(heading(page, '合成分页来源 024')).to_be_visible()
            expect(page.locator('body')).to_contain_text('共 1 条')
            page.get_by_test_id('baseline-search').fill('不存在的合成记录')
            expect(page.get_by_text('没有匹配的记录', exact=True)).to_be_visible()
            page.get_by_test_id('baseline-search').fill(''); expect(page.locator('body')).to_contain_text('第 1 / 3 页')
            self.category(page, '来源说明'); page.get_by_test_id('baseline-search').fill('04_Banking')
            expect(page.locator('body')).to_contain_text('04_Banking/accounts.csv'); expect(page.locator('body')).to_contain_text('共 1 条')
            self.read_only(mark, before)
            self.passed('Every one of 30 actual assets is reachable in three pages; section-wide search finds late rows and empty results; source search remains read-only')

    def member_family_tv(self, browser):
        with self.flow(browser) as (ctx, page), ExitStack() as stack:
            self.seed_baseline(ctx)
            partner = self.context(browser, member=2); stack.callback(partner.close)
            assert self.get(partner, PRIVATE + '?owner=member1') is None
            self.seed_baseline(partner, marker='合成伴侣记录')
            family = self.create_family(ctx)
            child = self.context(browser, member=None); stack.callback(child.close)
            assert child.request.get(self.base + family['entry']).status == 200; self.login(child)
            assert self.get(child, PRIVATE) is None
            self.seed_baseline(child, marker='合成另一家庭记录')
            assert self.get(ctx, '/api/me')['user']['householdId'] != self.get(child, '/api/me')['user']['householdId']
            for context, marker, forbidden in ((ctx, MARKER, '合成伴侣记录'), (partner, '合成伴侣记录', MARKER), (child, '合成另一家庭记录', MARKER)):
                view = page if context is ctx else context.new_page()
                self.open_panel(view); self.loaded(view); self.category(view, '资产')
                expect(heading(view, marker + ' · 存款')).to_be_visible(); expect(view.locator('body')).not_to_contain_text(forbidden)
            tv = self.context(browser, member=None); stack.callback(tv.close)
            pair = tv.request.post(self.base + '/api/pair/start', data={}); assert pair.status == 200
            self.write(ctx, 'POST', '/api/pair/approve', {'code': pair.json()['code'], 'name': '合成资产电视', 'focus': 'member1'})
            assert tv.request.post(self.base + '/api/pair/poll', data={'secret': pair.json()['secret']}).json()['approved']
            self.get(tv, PRIVATE, 403)
            tv_page = tv.new_page(); calls = []; tv_page.on('request', lambda request: calls.append(urlsplit(request.url).path))
            tv_page.goto(self.base + '/app/tv'); expect(tv_page.get_by_test_id('expo-tv-board')).to_be_visible(timeout=15000)
            expect(tv_page.locator('body')).not_to_contain_text(MARKER); assert PRIVATE not in calls
            anonymous = self.context(browser, member=None); stack.callback(anonymous.close); self.get(anonymous, PRIVATE, 401)
            self.passed('Genuine member/partner/signed second household each see their own source; owner query cannot select another; actual paired TV is 403 and never requests this view')

    def late_identity(self, browser, household):
        with self.flow(browser) as (ctx, page):
            self.seed_baseline(ctx)
            family = self.create_family(ctx) if household else None
            self.open_panel(page); self.loaded(page); self.category(page, '资产')
            before, mark, sent = self.snapshot(), len(self.requests), []
            def switch(route):
                response = route.fetch(max_redirects=0); assert response.status == 200
                value = response.json(); assert any(item['label'] == MARKER + ' · 存款' for item in value['assets'])
                if household:
                    assert ctx.request.get(self.base + family['entry']).status == 200
                    self.login(ctx)
                else: self.login(ctx, 2)
                route.fulfill(response=response); sent.append(True)
            page.route(self.base + PRIVATE, switch, times=1)
            button(page, '重新读取来源报告').click(); self.settle(page, lambda: len(sent) == 1)
            # Wait for real post-/me actor replacement, not only the pre-read conceal.
            expect(page.get_by_test_id('finance-baseline-panel')).to_have_count(0, timeout=15000)
            expect(page.locator('body')).not_to_contain_text(MARKER)
            assert self.get(ctx, PRIVATE) is None
            self.open_panel(page, navigate=False)
            expect(page.get_by_text('还没有本人资产来源记录', exact=True)).to_be_visible(timeout=15000)
            expect(page.locator('body')).not_to_contain_text(MARKER); self.read_only(mark, before)
            self.passed('Late real private GET is discarded after ' + ('signed household + login' if household else 'member cookie') + ' change; old panel unmounts before fresh empty report opens')

    def visibility_offline(self, browser):
        with self.flow(browser) as (ctx, page):
            self.seed_baseline(ctx); before, mark = self.snapshot(), len(self.requests)
            self.open_panel(page); self.loaded(page); self.category(page, '资产')
            page.get_by_test_id('baseline-search').fill(MARKER)
            ctx.set_offline(True); expect(page.get_by_test_id('finance-baseline-content')).to_have_count(0)
            expect(page.locator('body')).not_to_contain_text(MARKER)
            ctx.set_offline(False); self.loaded(page); expect(page.get_by_test_id('baseline-search')).to_have_value('')
            visibility(page, True); expect(page.get_by_test_id('finance-baseline-content')).to_have_count(0)
            held = []
            def hold(route):
                response = route.fetch(max_redirects=0); assert response.status == 200; held.append((route, response))
            page.route(self.base + PRIVATE, hold, times=1)
            visibility(page, False); self.settle(page, lambda: len(held) == 1); visibility(page, True)
            held[0][0].fulfill(response=held[0][1]); page.wait_for_timeout(300)
            expect(page.get_by_test_id('finance-baseline-content')).to_have_count(0); expect(page.locator('body')).not_to_contain_text(MARKER)
            calls = self.count_requests('GET', PRIVATE)
            visibility(page, False); self.loaded(page)
            assert self.count_requests('GET', PRIVATE) > calls
            expect(page.get_by_test_id('baseline-search')).to_have_value(''); self.read_only(mark, before)
            self.passed('Real offline and simulated visibility clear private DOM/search; late actual GET cannot restore hidden content; foreground must issue a fresh guarded read')

    def failed_read_and_return(self, browser):
        with self.flow(browser) as (ctx, page):
            self.seed_baseline(ctx); before, mark = self.snapshot(), len(self.requests)
            self.open_panel(page); self.loaded(page); dropped = []
            def lose(route):
                response = route.fetch(max_redirects=0); assert response.status == 200; route.abort('failed'); dropped.append(True)
            page.route(self.base + PRIVATE, lose, times=1)
            button(page, '重新读取来源报告').click(); self.settle(page, lambda: len(dropped) == 1)
            expect(page.get_by_role('alert')).to_be_visible(); expect(page.get_by_test_id('finance-baseline-content')).to_have_count(0)
            expect(button(page, '重新读取来源报告')).to_be_enabled()
            button(page, '重新读取来源报告').click(); self.loaded(page)
            held = []
            def hold(route):
                response = route.fetch(max_redirects=0); assert response.status == 200; held.append((route, response))
            page.route(self.base + PRIVATE, hold, times=1); button(page, '重新读取来源报告').click()
            self.settle(page, lambda: len(held) == 1); button(page, '返回财务').click()
            expect(page.get_by_test_id('finance-baseline-panel')).to_have_count(0)
            held[0][0].fulfill(response=held[0][1]); expect(button(page, '我的资产与来源报告')).to_be_enabled(timeout=15000)
            expect(page.locator('body')).not_to_contain_text(MARKER)
            self.open_panel(page, navigate=False); self.loaded(page); self.read_only(mark, before)
            self.passed('Dropped genuine GET clears old private content and retries by explicit GET; returning while GET is held cancels it and cannot reopen private panel')

    def capture(self, page, name, width, target):
        page.set_viewport_size({'width': width, 'height': 1080 if width >= 1280 else 844})
        page.evaluate('() => document.fonts.ready'); target.scroll_into_view_if_needed()
        page.wait_for_timeout(800)  # Paper labels, fonts and responsive layout settle.
        page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
        metrics = page.evaluate('''() => ({width:innerWidth,scroll:document.documentElement.scrollWidth,
          clipped:[...document.querySelectorAll('[data-testid="finance-baseline-panel"] input,[data-testid="finance-baseline-panel"] [role="button"]')]
          .filter(n=>{const r=n.getBoundingClientRect();return r.width>0&&r.height>0&&r.bottom>0&&r.top<innerHeight&&(r.right>innerWidth+2||r.left< -2)})
          .map(n=>({label:n.getAttribute('aria-label')||n.textContent,box:n.getBoundingClientRect().toJSON()}))})''')
        assert metrics['scroll'] <= width + 2 and not metrics['clipped'], metrics
        for control in (button(page, '返回财务'), button(page, '资产分类'), button(page, '重新读取来源报告')):
            box = control.bounding_box(); assert box and box['height'] >= 44 and box['width'] >= 44
        path = self.out / f'{name}-{width}.png'; page.screenshot(path=str(path), full_page=False)
        self.report['screenshots'].append({'path': path.relative_to(self.out.parent).as_posix(), 'sha256': sha(path), 'width': width,
            'metrics': metrics, 'scope': 'Settled current viewport after actual scroll to target; not all inner ScrollView content.'})

    def widths_and_dark(self, browser):
        with self.flow(browser) as (ctx, page):
            self.seed_baseline(ctx); self.seed_observation(ctx); self.open_panel(page); self.loaded(page)
            for width in WIDTHS: self.capture(page, 'baseline-overview-light', width, heading(page, '已录入的人民币记录'))
            self.category(page, '资产')
            for width in WIDTHS:
                self.capture(page, 'baseline-assets-light', width, heading(page, LONG_TITLE))
                if width <= 390:
                    box = heading(page, LONG_TITLE).bounding_box(); assert box and box['height'] > 40, 'Long title must wrap'
            preferences = self.get(ctx, '/api/preferences')
            self.write(ctx, 'PUT', '/api/preferences', {'revision': preferences['revision'], 'changes': {'colorMode': 'dark', 'density': 'compact'}})
            self.open_panel(page); self.loaded(page); self.category(page, '消费观察')
            page.wait_for_function("getComputedStyle(document.documentElement).colorScheme === 'dark'")
            for width in WIDTHS: self.capture(page, 'baseline-spending-dark', width, heading(page, '2026-09 · CNY'))
            self.passed('Four settled widths capture overview/long asset and dark compact spending; new controls measure at least 44px and bounded visible controls do not overflow')

    @classmethod
    def run_scenarios(cls, root, bundle, report, out, browser):
        scenarios = (('entry_and_empty', 'entry_and_empty', ()), ('values_and_observation', 'values_and_observation', ()),
            ('pagination_and_search', 'pagination_and_search', ()), ('member_family_tv', 'member_family_tv', ()),
            ('late_member', 'late_identity', (False,)), ('late_household', 'late_identity', (True,)),
            ('visibility_offline', 'visibility_offline', ()), ('failed_read_and_return', 'failed_read_and_return', ()), ('widths_and_dark', 'widths_and_dark', ()))
        for name, method, args in scenarios:
            case_out = out / name; case_out.mkdir(); folder = None
            before = (len(report['checks']), len(report['pageErrors']), len(report['externalRequests']))
            case = {'name': name, 'passed': False, 'temporaryFixtureRemoved': False}
            try:
                with ExitStack() as lifecycle:
                    folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='expo-baseline-browser-')))
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
    assert sha(Path(__file__)) == sha(root / 'tests/browser_expo_baseline_check.py')
    out = Path(__file__).resolve().parents[1] / 'test-results' / ('expo-baseline-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True); shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], screenshots=[], scenarioResults=[], scenarioFailures=[], head=head, tree=evidence['sourceTree'],
        buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(out / 'executed-harness.py'), sourceHashesBefore=hashes(), bundleHashesBefore=exports(),
        productionWrites=0, realFinancialData=False, realCloud=False, physicalTelevision=False,
        scope='Nine independent real local Flask/SQLite/Edge fixtures. Synthetic imports only, no successful business mocks. Visibility is simulated; offline uses browser network state. Screenshots need separate human visual review.')
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
