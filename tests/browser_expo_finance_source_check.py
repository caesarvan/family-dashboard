"""Frozen-source real Flask/SQLite/HTTPS/Edge checks for source imports.

All source files are synthetic. Faults only drop or delay actual requests or
responses; no successful business DTO is substituted. Run after source review
and a build explicitly bound to that source. Every scenario owns its fixture.
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

from itsdangerous import TimestampSigner
from playwright.sync_api import expect, sync_playwright
import browser_expo_finance_check as fixture
from browser_expo_finance_check import Run as BaseRun, button, sha, visibility

BASE = '/api/finance-baseline/imports/'
PRIVATE = '/api/finance-baseline/private'
SPENDING = 'spending_observation'
CHECKS = 12
WIDTHS = (320, 390, 1280, 1920)
MARKER = '合成来源本人记录'
LONG = '合成长期备用金来源：用于核对家庭旅行与日常生活的历史账户记录，日期和覆盖范围均须明确核对，全部是虚构数据'
CONSENT = '我已核对来源日期、变化和共享范围'


class Run(BaseRun):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        assert Path(self.source.__file__).resolve() == (self.root / 'app.py').resolve()
        self.sources = importlib.import_module('test_finance_source_bridge')
        self.observations = importlib.import_module('test_spending_observations')
        self.report.setdefault('fixtureHashes', {})
        for path, name in ((Path(fixture.__file__), 'tests/browser_expo_finance_check.py'),
                           (Path(__file__), 'tests/browser_expo_finance_source_check.py'),
                           (Path(self.sources.__file__), 'tests/test_finance_source_bridge.py'),
                           (Path(self.observations.__file__), 'tests/test_spending_observations.py')):
            assert sha(path) == sha(self.root / name), name
            old = self.report['fixtureHashes'].get(name)
            assert old is None or old == sha(path)
            self.report['fixtureHashes'][name] = sha(path)

    def clear_finance(self):
        pass  # Each independent scenario starts with its own newly created DB.

    def snapshot(self):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database)) as con:
            names = [row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            return {name: con.execute('SELECT * FROM "' + name + '" ORDER BY rowid').fetchall() for name in names
                    if name not in {'users', 'member_sessions', 'member_session_browsers', 'attempts'}}

    def protected(self):
        values = self.snapshot()
        names = ('finance_baselines', 'private_finance', 'hub_transactions', 'hub_reconciliations',
                 'hub_investments', 'entities', 'hub_budgets', 'hub_shopping_settlements')
        with closing(sqlite3.connect(self.database)) as con:
            return {**{name: values[name] for name in names},
                    'finance': con.execute("SELECT * FROM settings WHERE id='finance'").fetchall()}

    def candidate(self, amount=12000, marker=MARKER):
        value = self.sources.synthetic_candidate(amount_cents=amount)
        value['assets'][0]['label'] = marker
        value['liabilities'][0]['label'] = marker + ' · 历史贷款'
        value['income'][0]['label'] = marker + ' · 历史收入'
        return value

    def observation(self, ctx):
        value = self.observations.observation(net=-100)
        value['spending']['monthly'].insert(0, deepcopy(self.get(ctx, PRIVATE)['spending']['monthly'][0]))
        return value

    def status(self, ctx, mode='baseline', operation=None):
        return self.get(ctx, BASE + 'status?mode=' + mode + ('&operationId=' + operation if operation else ''))

    def api_preview(self, ctx, candidate, mode='baseline'):
        status = self.status(ctx, mode)
        body = {'candidate': candidate}
        if mode == SPENDING:
            body.update(mode=mode, **status['expected'], acknowledgeUnknownPreviousCoverage=False)
        else:
            current = status['current']
            body.update(expectedRevision=current['revision'] if current else 0,
                        expectedSourceDigest=current['sourceDigest'] if current else None)
        result = self.write(ctx, 'POST', BASE + 'preview', body)
        confirm = {'candidate': candidate, 'previewToken': result['previewToken']}
        if mode == SPENDING:
            confirm['mode'] = mode
        return result, confirm

    def seed_baseline(self, ctx, amount=12000, marker=MARKER):
        preview, body = self.api_preview(ctx, self.candidate(amount, marker))
        receipt = self.write(ctx, 'POST', BASE + 'confirm', body)
        assert receipt['receiptId'] == preview['operationId']
        return receipt

    def ready(self, page):
        expect(page.get_by_role('textbox', name='来源 JSON', exact=True)).to_be_visible(timeout=15000)
        expect(button(page, '重新读取来源状态')).to_be_enabled(timeout=15000)

    def open_source(self, page, navigate=True, mode='baseline'):
        if navigate:
            self.open_finance(page)
        expect(button(page, '更新资产来源')).to_be_enabled(timeout=15000)
        button(page, '更新资产来源').click()
        expect(page.get_by_test_id('finance-source-import-panel')).to_be_visible()
        self.ready(page)
        if mode != 'baseline':
            page.get_by_role('radio', name='仅更新消费观察', exact=True).click()
            expect(page.get_by_role('radio', name='仅更新消费观察', exact=True)).to_have_attribute('aria-checked', 'true')
            self.ready(page)

    def paste(self, page, candidate):
        page.get_by_role('textbox', name='来源 JSON', exact=True).fill(json.dumps(candidate, ensure_ascii=False))

    def source_file(self, page, raw, name='synthetic-source.json'):
        with page.expect_file_chooser() as selected:
            button(page, '选择来源 JSON 文件').click()
        selected.value.set_files({'name': name, 'mimeType': 'application/json', 'buffer': raw})

    def post(self, page, endpoint, action, expected=200, drop=False, unsent=False):
        """Read the real response before forwarding: avoid CDP body lifetime races."""
        calls = []
        url = self.base + BASE + endpoint
        def intercept(route):
            assert route.request.method == 'POST' and route.request.url == url
            payload = route.request.post_data_json
            if unsent:
                route.abort('failed')
                calls.append({'body': payload, 'status': None, 'result': None})
                return
            response = route.fetch(max_redirects=0)
            raw = response.body()
            result = json.loads(raw)
            if drop:
                route.abort('failed')
            else:
                route.fulfill(status=response.status, headers=response.headers, body=raw)
            calls.append({'body': payload, 'status': response.status, 'result': result})
        page.route(url, intercept)
        try:
            action()
            self.settle(page, lambda: len(calls) == 1)
            assert len(calls) == 1 and calls[0]['status'] == (None if unsent else expected), calls
            return calls[0]
        finally:
            page.unroute(url, intercept)

    def preview_ui(self, page):
        before = self.snapshot()
        value = self.post(page, 'preview', lambda: button(page, '预览来源变化').click())['result']
        expect(page.get_by_test_id('source-import-preview')).to_be_visible(timeout=15000)
        expect(button(page, '确认保存来源')).to_be_disabled()
        expect(button(page, '预览来源变化')).to_be_enabled()
        assert self.snapshot() == before, 'Preview changed business rows'
        assert re.fullmatch('[a-f0-9]{64}', value['operationId']) and value['expiresIn'] == 1200
        return value

    def confirm_ui(self, page, **fault):
        control = page.get_by_role('checkbox', name=CONSENT, exact=True)
        control.focus(); control.press('Space')
        expect(control).to_have_attribute('aria-checked', 'true')
        return self.post(page, 'confirm', lambda: button(page, '确认保存来源').click(), **fault)

    def receipt_ready(self, page, operation):
        expect(page.get_by_test_id('source-import-receipt')).to_contain_text(operation, timeout=15000)
        expect(button(page, '重新读取来源状态')).to_be_enabled(timeout=15000)
        expect(page.get_by_test_id('source-import-unknown')).to_have_count(0)
        expect(page.get_by_test_id('source-import-preview')).to_have_count(0)

    def unknown_ready(self, page, operation):
        expect(page.get_by_test_id('source-import-unknown')).to_contain_text(operation, timeout=15000)
        expect(button(page, '核对操作结果')).to_be_enabled(timeout=15000)
        expect(button(page, '确认保存来源')).to_have_count(0)

    def baseline_file_restart(self, browser):
        with self.flow(browser) as (ctx, page):
            self.open_source(page)
            candidate = self.candidate()
            self.source_file(page, json.dumps(candidate, ensure_ascii=False).encode(), '合成资产来源.json')
            expect(page.get_by_text('已选择：合成资产来源.json', exact=True)).to_be_visible()
            preview = self.preview_ui(page)
            expect(page.get_by_test_id('source-import-preview')).to_contain_text('CNY 120.00')
            first = self.confirm_ui(page)['result']
            assert first['receiptId'] == preview['operationId'] and first['replayed'] is False
            self.receipt_ready(page, preview['operationId'])
            assert self.count_requests('POST', BASE + 'confirm') == 1
            saved = self.get(ctx, PRIVATE)
            assert saved['assets'][0]['label'] == MARKER and saved['totals']['recordedAssetCents'] == 12000
            snapshot = self.snapshot(); self.restart(); page.reload(); self.open_source(page, navigate=False)
            assert self.get(ctx, PRIVATE) == saved and self.snapshot() == snapshot
            assert self.status(ctx, operation=first['receiptId'])['receipt']['replayed'] is True
            self.passed('Actual JSON file -> zero-write preview -> explicit keyboard consent -> persistent baseline survives backend restart and browser reload')

    def spending_lane(self, browser):
        with self.flow(browser) as (ctx, page):
            self.seed_baseline(ctx)
            self.seed(ctx, [fixture.row('合成已有消费', '12.34')])
            self.write(ctx, 'POST', '/api/finance-hub/investments', {'name': '合成已有持仓', 'institution': '合成机构',
                'assetType': '基金', 'currency': 'USD', 'quantity': '12.5', 'cost': '100', 'value': '120',
                'asOf': '2026-09-04', 'note': '虚构隔离验收'}, 201)
            self.open_source(page, mode=SPENDING); candidate = self.observation(ctx)
            protected = self.protected(); self.paste(page, candidate); preview = self.preview_ui(page)
            assert protected['hub_transactions'] and protected['hub_investments'] and protected['finance']
            expect(page.get_by_test_id('source-import-preview')).to_contain_text('CNY -1.00')
            receipt = self.confirm_ui(page)['result']; self.receipt_ready(page, preview['operationId'])
            assert receipt['assetBaselineUnchanged'] is True and self.protected() == protected
            assert self.count_requests('POST', BASE + 'confirm') == 1
            private = self.get(ctx, PRIVATE)
            assert private['spending']['monthly'] == candidate['spending']['monthly']
            assert self.status(ctx, SPENDING, receipt['receiptId'])['found'] is True
            self.passed('Pasted consumption observation changes only its lane; baseline entire row, wallet, ledger and holdings remain byte-for-byte unchanged')

    def invalid_inputs(self, browser):
        with self.flow(browser) as (ctx, page):
            self.open_source(page); before = self.snapshot(); mark = self.count_requests('POST', BASE + 'preview')
            page.get_by_role('textbox', name='来源 JSON', exact=True).fill('{invalid')
            button(page, '预览来源变化').click()
            expect(page.get_by_role('alert')).to_contain_text('JSON 无法解析')
            self.source_file(page, b' ' * 1_950_000, 'oversize.json')
            expect(page.get_by_role('alert')).to_contain_text('小于 1.95 MB')
            self.paste(page, self.observations.observation()); button(page, '预览来源变化').click()
            expect(page.get_by_role('alert')).to_contain_text('所选更新范围不一致')
            assert self.count_requests('POST', BASE + 'preview') == mark
            bad = self.candidate(); bad['assets'][0]['amountCents'] = -1
            self.paste(page, bad)
            rejected = self.post(page, 'preview', lambda: button(page, '预览来源变化').click(), expected=400)
            assert rejected['result']['error']; expect(page.get_by_role('alert')).to_be_visible()
            expect(page.get_by_test_id('source-import-preview')).to_have_count(0)
            assert self.snapshot() == before and self.count_requests('POST', BASE + 'confirm') == 0
            self.passed('Malformed, oversized and wrong-lane input fails locally; actual backend rejects invalid money; neither preview errors nor file reads write business data')

    def source_conflict(self, browser):
        with self.flow(browser) as (ctx, page):
            self.seed_baseline(ctx); self.open_source(page); self.paste(page, self.candidate(13000))
            original = self.preview_ui(page)
            self.seed_baseline(ctx, 14000, '合成另一设备已更新'); changed = self.snapshot()
            rejected = self.confirm_ui(page, expected=409)
            assert rejected['result']['error'] and self.snapshot() == changed
            expect(page.get_by_test_id('source-import-preview')).to_have_count(0)
            expect(page.get_by_test_id('source-import-unknown')).to_have_count(0)
            expect(page.get_by_role('textbox', name='来源 JSON', exact=True)).to_have_value(re.compile('13000'))
            expect(button(page, '预览来源变化')).to_be_enabled()
            fresh = self.preview_ui(page); assert fresh['operationId'] != original['operationId']
            receipt = self.confirm_ui(page)['result']; self.receipt_ready(page, fresh['operationId'])
            assert receipt['revision'] == 3 and self.get(ctx, PRIVATE)['totals']['recordedAssetCents'] == 13000
            self.passed('Real concurrent source update yields CAS 409 without overwrite; original draft needs explicit fresh preview and confirmation')

    def committed_get_recovery(self, browser):
        with self.flow(browser) as (ctx, page):
            page.set_viewport_size({'width': 1280, 'height': 1000})
            self.open_source(page); self.paste(page, self.candidate()); preview = self.preview_ui(page)
            packet = self.confirm_ui(page, drop=True); self.unknown_ready(page, preview['operationId'])
            assert packet['result']['receiptId'] == preview['operationId']
            saved = self.snapshot(); writes = self.count_requests('POST', BASE + 'confirm')
            assert writes == 1
            button(page, '首页').click(); self.unknown_ready(page, preview['operationId'])
            assert urlsplit(page.url).path == '/app/finance'
            button(page, '核对操作结果').click(); self.receipt_ready(page, preview['operationId'])
            assert self.snapshot() == saved and self.count_requests('POST', BASE + 'confirm') == writes
            assert any(r['method'] == 'GET' and r['path'] == BASE + 'status' and 'operationId=' + preview['operationId'] in r['query'] for r in self.requests)
            self.passed('Actually committed response loss keeps navigation locked; exact operation GET recovers history with one and only one POST')

    def committed_original_retry(self, browser):
        with self.flow(browser) as (ctx, page):
            self.seed_baseline(ctx); self.open_source(page, mode=SPENDING); self.paste(page, self.observation(ctx))
            preview = self.preview_ui(page); first = self.confirm_ui(page, drop=True)
            self.unknown_ready(page, preview['operationId']); before = self.snapshot()
            retried = self.post(page, 'confirm', lambda: button(page, '按原请求重试').click())
            self.receipt_ready(page, preview['operationId'])
            assert first['body'] == retried['body'] and retried['result']['replayed'] is True
            assert retried['result']['receiptId'] == preview['operationId'] and self.snapshot() == before
            assert self.count_requests('POST', BASE + 'confirm') == 2
            self.passed('Same-foreground explicit retry uses the exact original spending candidate/token and returns its receipt without a second update')

    def unsent_and_end_review(self, browser):
        with self.flow(browser) as (ctx, page):
            self.open_source(page); self.paste(page, self.candidate()); preview = self.preview_ui(page)
            before = self.snapshot(); self.confirm_ui(page, unsent=True); self.unknown_ready(page, preview['operationId'])
            assert self.snapshot() == before
            expect(button(page, '结束本次核对')).to_have_count(0)
            writes = self.count_requests('POST', BASE + 'confirm')
            button(page, '核对操作结果').click()
            expect(button(page, '结束本次核对')).to_be_enabled(timeout=15000)
            expect(page.get_by_test_id('source-import-unknown')).to_be_visible()
            expect(page.locator('body')).to_contain_text('这不能证明没有保存')
            assert self.status(ctx, operation=preview['operationId']) == {'mode': 'baseline', 'operationId': preview['operationId'], 'found': False, 'receipt': None}
            button(page, '结束本次核对').click()
            expect(page.get_by_role('heading', name='结束本次核对？', exact=True)).to_be_visible()
            assert self.snapshot() == before and self.count_requests('POST', BASE + 'confirm') == writes
            button(page, '确认结束本次核对').click(); self.ready(page)
            expect(page.get_by_role('textbox', name='操作编号', exact=True)).to_have_value(preview['operationId'])
            assert self.snapshot() == before and self.count_requests('POST', BASE + 'confirm') == writes
            self.paste(page, self.candidate(13000)); fresh = self.preview_ui(page)
            assert fresh['operationId'] != preview['operationId'] and self.snapshot() == before
            self.confirm_ui(page); self.receipt_ready(page, fresh['operationId'])
            assert len(self.snapshot()['finance_source_receipts']) == 1
            self.passed('Unsent POST stays unknown after found=false; fresh GET and a second explicit end decision precede new preview; no automatic retry or false failure claim')

    def expiry_and_new_session(self, browser):
        with self.flow(browser) as (ctx, page):
            self.open_source(page); self.paste(page, self.candidate()); preview = self.preview_ui(page)
            before = self.snapshot(); original = TimestampSigner.get_timestamp
            with patch.object(TimestampSigner, 'get_timestamp', lambda signer: original(signer) + 1201):
                rejected = self.confirm_ui(page, expected=410)
            assert rejected['result']['code'] == 'preview_expired' and self.snapshot() == before
            expect(page.get_by_test_id('source-import-unknown')).to_have_count(0)
            expect(button(page, '预览来源变化')).to_be_enabled()
            fresh = self.preview_ui(page); packet = self.confirm_ui(page, drop=True)
            self.unknown_ready(page, fresh['operationId']); saved = self.snapshot()
            self.login(ctx)  # Actual new HttpOnly session for the same member.
            def accept_reload(dialog):
                assert dialog.type == 'beforeunload'; dialog.accept()
            page.on('dialog', accept_reload)
            try:
                page.reload()
            finally:
                page.remove_listener('dialog', accept_reload)
            self.open_source(page)
            page.get_by_role('textbox', name='操作编号', exact=True).fill(fresh['operationId'])
            button(page, '使用操作编号核对').click(); self.unknown_ready(page, fresh['operationId'])
            expect(button(page, '按原请求重试')).to_have_count(0)
            with patch.object(TimestampSigner, 'get_timestamp', lambda signer: original(signer) + 1201):
                button(page, '核对操作结果').click(); self.receipt_ready(page, fresh['operationId'])
                replay = self.write(ctx, 'POST', BASE + 'confirm', packet['body'])
            assert replay['replayed'] and replay['receiptId'] == fresh['operationId'] and self.snapshot() == saved
            self.passed('Unwritten expired token is precise 410; after new actual login an expired committed operation remains readable and replayable without data changes')

    def boundaries(self, browser):
        with self.flow(browser) as (ctx, page), ExitStack() as extras:
            preview, body = self.api_preview(ctx, self.candidate()); receipt = self.write(ctx, 'POST', BASE + 'confirm', body)
            partner = self.context(browser, member=2); extras.callback(partner.close)
            self.open_source(page); partner_page = partner.new_page(); self.open_source(partner_page)
            assert self.status(partner)['current'] is None and self.get(partner, PRIVATE) is None
            assert self.status(partner, operation=receipt['receiptId'])['found'] is False
            assert self.write(partner, 'POST', BASE + 'confirm', body, 403)['error']
            invitation = self.write(ctx, 'POST', '/api/spaces/invitations', {}, 201)['invitation']
            family = self.write(ctx, 'POST', '/api/spaces/redeem', {'invitation': invitation, 'name': '合成来源第二家庭',
                'slug': 'source-other', 'MEMBER1_PASSWORD': 'testing-password-one', 'MEMBER2_PASSWORD': 'testing-password-two'}, 201)
            foreign = self.context(browser, member=None); extras.callback(foreign.close)
            assert foreign.request.get(self.base + family['entry']).status == 200; self.login(foreign)
            assert self.status(foreign)['current'] is None and self.status(foreign, operation=receipt['receiptId'])['found'] is False
            assert self.write(foreign, 'POST', BASE + 'confirm', body, 409)['code'] == 'preview_invalid'
            tv = self.context(browser, member=None); extras.callback(tv.close)
            pair = tv.request.post(self.base + '/api/pair/start', data={}).json()
            self.write(ctx, 'POST', '/api/pair/approve', {'code': pair['code'], 'name': '合成来源只读电视'})
            assert tv.request.post(self.base + '/api/pair/poll', data={'secret': pair['secret']}).json()['approved']
            for mode in ('baseline', SPENDING):
                self.get(tv, BASE + 'status?mode=' + mode, 403)
                response = tv.request.post(self.base + BASE + 'preview', data={'mode': mode, 'candidate': self.candidate()})
                assert response.status == 403
            tv_page = tv.new_page(); tv_page.goto(self.base + '/app/tv')
            expect(tv_page.get_by_test_id('expo-tv-board')).to_be_visible(timeout=15000)
            expect(tv_page.get_by_test_id('finance-source-import-panel')).to_have_count(0)
            expect(tv_page.locator('body')).not_to_contain_text(MARKER)
            expect(partner_page.locator('body')).not_to_contain_text(MARKER)
            anonymous = self.context(browser, member=None); extras.callback(anonymous.close)
            self.get(anonymous, BASE + 'status?mode=baseline&operationId=' + preview['operationId'], 401)
            assert len(self.snapshot()['finance_source_receipts']) == 1
            self.passed('Actual second member, signed second household, anonymous and paired TV cannot read another member receipt or confirm its source; TV never mounts the member importer')

    def late_identity(self, browser):
        with self.flow(browser) as (ctx, page):
            self.open_source(page); self.paste(page, self.candidate()); before = self.snapshot(); delivered = []
            url = self.base + BASE + 'preview'
            def change_member(route):
                response = route.fetch(max_redirects=0); raw = response.body(); value = json.loads(raw)
                assert response.status == 200 and value['private']['assets'][0]['label'] == MARKER
                self.login(ctx, 2)
                route.fulfill(status=response.status, headers=response.headers, body=raw); delivered.append(True)
            page.route(url, change_member)
            try:
                button(page, '预览来源变化').click(); self.settle(page, lambda: delivered == [True])
                expect(page.get_by_test_id('finance-source-import-panel')).to_have_count(0, timeout=15000)
            finally:
                page.unroute(url, change_member)
            expect(page.locator('body')).not_to_contain_text(MARKER)
            assert self.snapshot() == before and self.count_requests('POST', BASE + 'confirm') == 0
            self.open_source(page, navigate=False)
            expect(page.get_by_role('textbox', name='来源 JSON', exact=True)).to_have_value('')
            assert self.status(ctx)['current'] is None
            self.passed('Actual preview completes before the cookie switches member; late private DTO is discarded, old panel unmounts and no draft or token enters the new member')

    def lifecycle_navigation(self, browser):
        with self.flow(browser) as (ctx, page):
            page.set_viewport_size({'width': 1280, 'height': 1000})
            self.open_finance(page); self.ledger(page, '2026-08'); self.open_source(page, navigate=False)
            self.paste(page, self.candidate()); button(page, '首页').click()
            expect(page.get_by_test_id('finance-source-import-panel')).to_be_visible()
            button(page, '返回财务').click()
            expect(page.get_by_role('heading', name='放弃未保存的来源？', exact=True)).to_be_visible()
            button(page, '继续核对').click()
            visibility(page, True); expect(page.get_by_role('textbox', name='来源 JSON', exact=True)).to_have_count(0)
            expect(page.locator('body')).not_to_contain_text(MARKER)
            visibility(page, False); self.ready(page)
            expect(page.get_by_role('textbox', name='来源 JSON', exact=True)).to_have_value('')
            self.paste(page, self.candidate()); ctx.set_offline(True)
            expect(page.get_by_role('textbox', name='来源 JSON', exact=True)).to_have_count(0)
            ctx.set_offline(False); self.ready(page)
            expect(page.get_by_role('textbox', name='来源 JSON', exact=True)).to_have_value('')
            assert self.count_requests('POST', BASE + 'confirm') == self.count_requests('POST', BASE + 'preview') == 0
            self.paste(page, self.candidate()); preview = self.preview_ui(page)
            self.confirm_ui(page, unsent=True); self.unknown_ready(page, preview['operationId'])
            visibility(page, True); expect(page.get_by_test_id('source-import-unknown')).to_have_count(0)
            visibility(page, False); self.unknown_ready(page, preview['operationId'])
            expect(button(page, '按原请求重试')).to_have_count(0)
            writes = self.count_requests('POST', BASE + 'confirm')
            button(page, '首页').click(); self.unknown_ready(page, preview['operationId'])
            button(page, '保留操作编号并返回').click(); button(page, '保留编号并返回').click()
            expect(page.get_by_test_id('finance-source-import-panel')).to_have_count(0)
            expect(page.get_by_role('textbox', name='账本月份', exact=True)).to_have_value('2026-08')
            expect(button(page, '更新资产来源')).to_be_enabled()
            button(page, '更新资产来源').click(); self.unknown_ready(page, preview['operationId'])
            expect(button(page, '按原请求重试')).to_have_count(0)
            assert self.count_requests('POST', BASE + 'confirm') == writes
            self.passed('Navigation cannot discard draft/unknown intent; hidden/offline clear private input, keep only unresolved ID, and explicit return preserves month and restores read-only recovery')

    def capture(self, page, name, width, target):
        page.set_viewport_size({'width': width, 'height': 1080 if width >= 1280 else 844})
        page.evaluate('() => document.fonts.ready'); target.scroll_into_view_if_needed(); page.wait_for_timeout(800)
        page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
        metrics = page.evaluate('''() => ({width:innerWidth,scroll:document.documentElement.scrollWidth,
          clipped:[...document.querySelectorAll('[data-testid="finance-source-import-panel"] input,[data-testid="finance-source-import-panel"] textarea,[data-testid="finance-source-import-panel"] [role="button"],[data-testid="finance-source-import-panel"] [role="checkbox"],[data-testid="finance-source-import-panel"] [role="radio"]')]
          .filter(n=>{const r=n.getBoundingClientRect();return r.width>0&&r.height>0&&r.bottom>0&&r.top<innerHeight&&(r.right>innerWidth+2||r.left< -2)})
          .map(n=>({label:n.getAttribute('aria-label')||n.textContent,box:n.getBoundingClientRect().toJSON()}))})''')
        assert metrics['scroll'] <= width + 2 and not metrics['clipped'], metrics
        for control in (button(page, '返回财务'), button(page, '重新读取来源状态')):
            box = control.bounding_box(); assert box and box['height'] >= 44 and box['width'] >= 44
        path = self.out / f'{name}-{width}.png'; page.screenshot(path=str(path), full_page=False)
        self.report['screenshots'].append({'path': path.relative_to(self.out.parent).as_posix(), 'sha256': sha(path),
            'width': width, 'metrics': metrics, 'scope': 'Settled visible viewport after scrolling; not all inner ScrollView contents.'})

    def widths_and_themes(self, browser):
        with self.flow(browser) as (ctx, page):
            candidate = self.candidate(); candidate['assets'][0]['label'] = LONG
            base = deepcopy(candidate['assets'][0])
            candidate['assets'].extend([{**base, 'id': 'zero', 'label': '合成零余额', 'amountCents': 0},
                {**base, 'id': 'unknown', 'label': '合成未知美元', 'amountCents': None, 'currency': 'USD',
                 'includedInRecordedSubtotal': False, 'exclusionReason': '尚未取得估值'}])
            self.open_source(page); self.paste(page, candidate); preview = self.preview_ui(page)
            expect(page.get_by_test_id('source-import-preview')).to_contain_text('金额待核对')
            expect(page.get_by_test_id('source-import-preview')).to_contain_text('CNY 0.00')
            for width in WIDTHS:
                self.capture(page, 'source-preview-light', width, page.get_by_text(LONG, exact=True))
                if width <= 390:
                    assert page.get_by_text(LONG, exact=True).bounding_box()['height'] > 40
            self.confirm_ui(page); self.receipt_ready(page, preview['operationId'])
            preferences = self.get(ctx, '/api/preferences')
            self.write(ctx, 'PUT', '/api/preferences', {'revision': preferences['revision'], 'changes': {'colorMode': 'dark', 'density': 'compact'}})
            page.reload(); self.open_source(page, mode=SPENDING)
            page.wait_for_function("getComputedStyle(document.documentElement).colorScheme === 'dark'")
            self.paste(page, self.observation(ctx)); preview = self.preview_ui(page)
            for width in WIDTHS:
                self.capture(page, 'source-spending-dark', width, page.get_by_test_id('source-import-preview'))
            self.confirm_ui(page); self.receipt_ready(page, preview['operationId'])
            for width in WIDTHS:
                self.capture(page, 'source-receipt-dark', width, page.get_by_test_id('source-import-receipt'))
            self.passed('Four settled widths capture populated light baseline, dark compact observation and actual receipt; long text wraps, visible controls fit and main actions measure at least 44px')

    @classmethod
    def run_scenarios(cls, root, bundle, report, out, browser):
        scenarios = tuple((name, name, ()) for name in (
            'baseline_file_restart', 'spending_lane', 'invalid_inputs', 'source_conflict',
            'committed_get_recovery', 'committed_original_retry', 'unsent_and_end_review',
            'expiry_and_new_session', 'boundaries', 'late_identity', 'lifecycle_navigation', 'widths_and_themes'))
        for name, method, args in scenarios:
            case_out = out / name; case_out.mkdir(); folder = None
            before = (len(report['checks']), len(report['pageErrors']), len(report['externalRequests']))
            case = {'name': name, 'passed': False, 'temporaryFixtureRemoved': False}
            try:
                with ExitStack() as lifecycle:
                    folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='expo-finance-source-browser-')))
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
    assert sha(Path(__file__)) == sha(root / 'tests/browser_expo_finance_source_check.py')
    out = Path(__file__).resolve().parents[1] / 'test-results' / ('expo-finance-source-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True); shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], screenshots=[], scenarioResults=[], scenarioFailures=[], head=head, tree=evidence['sourceTree'],
        buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(out / 'executed-harness.py'), sourceHashesBefore=hashes(), bundleHashesBefore=exports(),
        productionWrites=0, realFinancialData=False, realCloud=False, physicalTelevision=False,
        scope='Twelve independent real local Flask/SQLite/HTTPS/Edge fixtures; synthetic source JSON only. Interception drops or delays actual requests/responses. Signer time advances only in the expiry scenario; no real waiting, cloud or bank access. Visibility is simulated, offline uses browser network state. Screenshots need separate human review.')
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
