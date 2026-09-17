"""Frozen Expo routines with real isolated Flask/SQLite/Edge and synthetic households.

No successful business-response mocks. Faults discard/delay genuine requests or
responses; only visibility and the signing clock are controlled by the fixture.
Calling the actual worker tick proves its local effect, not real scheduling.
"""
import argparse
from contextlib import ExitStack, closing
from datetime import date, datetime, timedelta, timezone
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

from itsdangerous.timed import TimestampSigner
from playwright.sync_api import expect, sync_playwright
import browser_expo_finance_check as fixture
from browser_expo_finance_check import Run as BaseRun, button, sha, visibility


BASE = '/api/routines'
WIDTHS = (320, 390, 1280, 1920)
CHECKS = 10
TITLE = '每周一起整理公共空间并检查旅行用品和备用充电线'
NOTE = '合成演示：整理完成后核对雨衣水壶及共同物品，不包含真实个人资料。'


def field(page, name):
    return page.get_by_role('textbox', name=name, exact=True)


def radio(page, name):
    return page.get_by_role('radio', name=name, exact=True)


class Run(BaseRun):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        assert Path(self.source.__file__).resolve() == (self.root / 'app.py').resolve()
        self.report['fixtureHashes'] = {}
        for path, name in ((Path(fixture.__file__), 'tests/browser_expo_finance_check.py'),
                           (Path(__file__), 'tests/browser_expo_routines_check.py')):
            assert sha(path) == sha(self.root / name)
            self.report['fixtureHashes'][name] = sha(path)
        # The actual signer still signs/verifies genuine server-generated tokens.
        # A monotonic offset avoids waiting ten minutes; no business DTO is mocked.
        self.signing_offset = 0
        timestamp = TimestampSigner.get_timestamp
        self.lifecycle.enter_context(patch.object(TimestampSigner, 'get_timestamp',
            lambda signer: timestamp(signer) + self.signing_offset))

    def clear_finance(self):
        pass  # Reuse only isolated server/auth/lifecycle helpers, no table resets.

    def snapshot(self):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database)) as con:
            return {table: sorted(con.execute('SELECT * FROM ' + table).fetchall(), key=repr)
                    for table in ('household_routines', 'routine_occurrences', 'routine_receipts', 'entities', 'audit', 'settings')}

    def context_data(self, ctx, plan_id=None):
        return self.get(ctx, BASE + '/context' + ('?planId=' + plan_id if plan_id else ''))

    def plan(self, ctx, plan_id):
        return next(p for p in self.context_data(ctx, plan_id)['plans'] if p['id'] == plan_id)

    def entity(self, ctx, kind, item_id):
        return next(item for item in self.get(ctx, '/api/state')[kind] if item['id'] == item_id)

    def payload(self, ctx, title, kind='tasks', owner='shared', budget=None):
        template = dict(title=title, owner=owner, note=NOTE)
        if kind == 'shopping':
            template.update(quantity='1 件', budget=budget)
        return dict(operation='create', kind=kind, template=template,
                    schedule=dict(frequency='weekly', interval=1, anchor=self.context_data(ctx)['today']))

    def api_create(self, ctx, title, **kwargs):
        preview = self.write(ctx, 'POST', BASE + '/preview', self.payload(ctx, title, **kwargs))
        return self.write(ctx, 'POST', BASE + '/confirm', {'previewToken': preview['previewToken']})

    def api_operation(self, ctx, plan, operation, **values):
        payload = dict(operation=operation, planId=plan['id'], revision=plan['revision'], **values)
        preview = self.write(ctx, 'POST', BASE + '/preview', payload)
        return self.write(ctx, 'POST', BASE + '/confirm', {'previewToken': preview['previewToken']})

    def open_panel(self, page):
        page.goto(self.base + '/app/more')
        entry = page.get_by_label('家庭例行计划', exact=True)
        expect(entry).to_have_count(1)
        entry.click()
        expect(page.get_by_test_id('routines-list')).to_be_visible(timeout=15000)
        expect(button(page, '新建例行计划')).to_be_enabled(timeout=15000)

    def detail(self, page, plan):
        with page.expect_response(lambda r: urlsplit(r.url).path == BASE + '/context' and r.request.method == 'GET') as pending:
            button(page, '查看计划：' + plan['template']['title']).click()
        assert pending.value.status == 200
        expect(page.get_by_test_id('routine-detail')).to_be_visible(timeout=15000)
        expect(button(page, '刷新当前计划')).to_be_enabled(timeout=15000)

    def refresh_plan(self, page):
        with page.expect_response(lambda r: urlsplit(r.url).path == BASE + '/context' and r.request.method == 'GET') as pending:
            button(page, '刷新当前计划').click()
        assert pending.value.status == 200
        expect(button(page, '刷新当前计划')).to_be_enabled(timeout=15000)

    def create_form(self, page, title, kind='tasks', owner='shared', budget=''):
        button(page, '新建例行计划').click()
        radio(page, '采购计划' if kind == 'shopping' else '待办计划').click()
        field(page, '例行计划名称').fill(title)
        people = self.get(page.context, '/api/state')['people']
        name = '共同负责' if owner == 'shared' else next(p['name'] for p in people if p['id'] == owner)
        radio(page, '例行负责人：' + name).click()
        radio(page, '按周').click()
        field(page, '每隔多少期').fill('1')
        field(page, '起始日期').fill(self.context_data(page.context)['today'])
        field(page, '例行计划备注').fill(NOTE)
        if kind == 'shopping':
            field(page, '采购数量').fill('2 份共同用品')
            field(page, '每期预算（元）').fill(budget)

    def preview(self, page, action='预览例行计划'):
        before = self.snapshot()
        confirmations = self.count_requests('POST', BASE + '/confirm')
        with page.expect_response(lambda r: urlsplit(r.url).path == BASE + '/preview' and r.request.method == 'POST') as pending:
            button(page, action).click()
        response = pending.value
        assert response.status == 200, response.text()
        result = response.json()
        expect(button(page, '确认例行计划操作')).to_be_enabled(timeout=15000)
        assert self.snapshot() == before and self.count_requests('POST', BASE + '/confirm') == confirmations
        return result

    def confirm(self, page):
        with page.expect_response(lambda r: urlsplit(r.url).path == BASE + '/confirm' and r.request.method == 'POST') as pending:
            button(page, '确认例行计划操作').click()
        response = pending.value
        assert response.status == 200, response.text()
        result = response.json()
        self.confirmed(page)
        return result

    def confirmed(self, page):
        expect(page.get_by_test_id('routines-unknown')).to_have_count(0, timeout=15000)
        expect(page.get_by_test_id('routines-receipt')).to_be_visible(timeout=15000)
        expect(button(page, '读取当前计划')).to_be_enabled(timeout=15000)
        expect(page.get_by_test_id('routine-detail')).to_be_visible()

    def write_then_lose_readback(self, page, action, method, path):
        # Business success comes from the real endpoint. Discard only the first
        # subsequent real context response; never substitute a successful DTO.
        dropped = []
        def lose_read(route):
            response = route.fetch(max_redirects=0)
            assert response.status == 200, response.text()
            dropped.append(response.json())
            route.abort('failed')
        page.route(self.base + BASE + '/context?*', lose_read, times=1)
        before_writes = self.count_requests(method, path)
        with page.expect_response(lambda r: urlsplit(r.url).path == path and r.request.method == method) as pending:
            button(page, action).click()
        response = pending.value
        assert response.status == 200, response.text()
        self.settle(page, lambda: len(dropped) == 1)
        # The recovery button becomes enabled only after the failed read and
        # final identity check settle. Old detail/actions must stay unavailable.
        expect(button(page, '读取当前计划')).to_have_count(1)
        expect(button(page, '读取当前计划')).to_be_enabled(timeout=15000)
        expect(page.get_by_test_id('routine-detail')).to_have_count(0)
        for name in ('暂停计划', '恢复计划', '编辑例行计划', '完成当前待办', '标记当前采购已买到', '跳过本期并保留事项', '归档计划'):
            expect(button(page, name)).to_have_count(0)
        expect(page.get_by_test_id('routines-unknown')).to_have_count(0)
        if method == 'POST':
            expect(page.get_by_test_id('routines-receipt')).to_be_visible()
        else:
            expect(page.get_by_test_id('routines-current-unavailable')).to_be_visible()
        assert self.count_requests(method, path) == before_writes + 1
        after_write = self.snapshot()
        with page.expect_response(lambda r: urlsplit(r.url).path == BASE + '/context' and r.request.method == 'GET') as reread:
            button(page, '读取当前计划').click()
        assert reread.value.status == 200
        expect(page.get_by_test_id('routine-detail')).to_be_visible(timeout=15000)
        expect(button(page, '刷新当前计划')).to_be_enabled(timeout=15000)
        assert self.snapshot() == after_write and self.count_requests(method, path) == before_writes + 1
        self.report.setdefault('readbackLoss', []).append({'method': method, 'successfulWriteStatus': 200,
            'discardedActualContextResponses': len(dropped), 'oldDetailRemoved': True, 'explicitGetRecovery': True})
        return response.json(), dropped[0]

    def shot(self, page, label, width, target):
        page.set_viewport_size({'width': width, 'height': 1080 if width >= 1280 else 844})
        page.evaluate('() => document.fonts.ready')
        target.scroll_into_view_if_needed()
        page.wait_for_timeout(400)  # Settle Paper/responsive animation, not network success.
        expect(target).to_be_in_viewport()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2'), (label, width)
        file = self.out / f'{label}-{width}.png'
        page.screenshot(path=str(file), full_page=False)
        self.report['screenshots'].append({'path': file.name, 'sha256': sha(file), 'width': width,
            'scope': 'Actual visible scrolled viewport; not the entire internal ScrollView or a physical device.'})

    def nav_lock(self, page):
        page.set_viewport_size({'width': 390, 'height': 844})
        location = page.url
        page.get_by_role('tab', name='首页', exact=True).click()
        expect(page.get_by_test_id('routines-panel')).to_be_visible()
        assert page.url == location
        expect(page.locator('body')).to_contain_text('请先保存或放弃例行计划的修改')

    def creation_and_restart(self, browser):
        with self.flow(browser) as (ctx, page):
            self.open_panel(page)
            self.create_form(page, TITLE, owner='member2')
            # Exercise actual keyboard selection without changing the intended rule.
            radio(page, '按周').focus(); page.keyboard.press('ArrowDown')
            expect(radio(page, '按月')).to_be_checked()
            page.keyboard.press('ArrowUp'); expect(radio(page, '按周')).to_be_checked()
            for width in WIDTHS:
                self.shot(page, 'routine-editor-light', width, field(page, '例行计划名称'))
            preview = self.preview(page)
            assert preview['after']['template']['owner'] == 'member2'
            assert preview['nextDates'][0] == preview['willGenerate']['scheduledOn']
            for width in WIDTHS:
                self.shot(page, 'routine-preview-light', width, button(page, '确认例行计划操作'))
            result = self.confirm(page)
            assert result['operationKey'] == preview['operationKey'] and not result['replayed']
            stored = self.plan(ctx, result['plan']['id'])
            assert stored['current']['entityId'] == result['generated']['id']
            assert stored['current']['entity']['owner'] == 'member2'
            before = self.snapshot()
            self.restart(); self.open_panel(page); self.detail(page, stored)
            assert self.plan(ctx, stored['id']) == stored and self.snapshot() == before
            self.passed('More UI task creation, real zero-write preview, keyboard period selection, explicit durable confirmation and actual Flask restart preserve the same plan/entity')

    def shopping_budgets(self, browser):
        with self.flow(browser) as (ctx, page):
            self.open_panel(page)
            for budget, owner in (('', 'shared'), ('0.00', 'member1')):
                self.create_form(page, '每期补充共同用品预算' + ('待确认' if not budget else '明确零元'), 'shopping', owner, budget)
                preview = self.preview(page)
                expected = None if not budget else 0
                assert preview['after']['template']['budget'] == expected
                result = self.confirm(page)
                record = self.entity(ctx, 'shopping', result['generated']['id'])
                assert record['budget'] == expected and record['actual'] is None and record['photoIds'] == []
                assert record['owner'] == owner and not record['done']
                button(page, '返回例行计划列表').click()
                expect(button(page, '新建例行计划')).to_be_enabled()
            prefs = self.get(ctx, '/api/preferences')
            self.write(ctx, 'PUT', '/api/preferences', {'revision': prefs['revision'], 'changes': {'colorMode': 'dark'}})
            self.open_panel(page); self.detail(page, result['plan'])
            page.wait_for_function("getComputedStyle(document.body).backgroundColor === 'rgb(17, 17, 19)'")
            for width in WIDTHS:
                self.shot(page, 'routine-detail-dark', width, page.get_by_test_id('routine-detail'))
            self.passed('UI shared/member shopping ownership and unknown versus confirmed-zero budget persist distinctly; no payment/photos copied; populated dark details captured at four widths')

    def progression(self, browser):
        with self.flow(browser) as (ctx, page):
            created = self.api_create(ctx, '每周一起检查共同物品')
            plan = created['plan']; original_id = created['generated']['id']
            self.open_panel(page); self.detail(page, plan)
            path = '/api/items/tasks/' + original_id
            count = self.count_requests('PATCH', path)
            changed, lost_context = self.write_then_lose_readback(page, '完成当前待办', 'PATCH', path)
            assert changed['ok'] is True
            assert next(p for p in lost_context['plans'] if p['id'] == plan['id'])['current']['entity']['done'] is True
            expect(button(page, '完成当前待办')).to_have_count(0)
            assert self.count_requests('PATCH', path) == count + 1
            assert self.entity(ctx, 'tasks', original_id)['done'] is True
            assert self.plan(ctx, plan['id'])['current']['entityId'] == original_id
            tick = self.application.extensions['household_routines'].tick()
            assert tick['generated'] == 1 and self.application.extensions['household_routines'].tick()['generated'] == 0
            next_plan = self.plan(ctx, plan['id'])
            assert next_plan['current']['index'] == 2 and next_plan['current']['entityId'] != original_id
            assert next_plan['current']['scheduledOn'] == (date.fromisoformat(plan['current']['scheduledOn']) + timedelta(days=7)).isoformat()
            assert next(h for h in next_plan['history'] if h['entityId'] == original_id)['state'] == 'completed'
            self.refresh_plan(page); expect(button(page, '暂停计划')).to_be_enabled()
            self.preview(page, '暂停计划')
            paused, lost_context = self.write_then_lose_readback(page, '确认例行计划操作', 'POST', BASE + '/confirm')
            assert paused['plan']['state'] == 'paused'
            assert next(p for p in lost_context['plans'] if p['id'] == plan['id'])['state'] == 'paused'
            expect(button(page, '恢复计划')).to_be_enabled()
            expect(button(page, '暂停计划')).to_have_count(0)
            paused_id = self.plan(ctx, plan['id'])['current']['entityId']
            with page.expect_response(lambda r: urlsplit(r.url).path == '/api/items/tasks/' + paused_id and r.request.method == 'PATCH') as completed:
                button(page, '完成当前待办').click()
            assert completed.value.status == 200
            expect(button(page, '刷新当前计划')).to_be_enabled(timeout=15000)
            assert self.entity(ctx, 'tasks', paused_id)['done'] is True
            assert self.application.extensions['household_routines'].tick()['generated'] == 0
            assert self.plan(ctx, plan['id'])['current']['entityId'] == paused_id
            self.preview(page, '恢复计划'); resumed = self.confirm(page)
            assert resumed['generated'] and resumed['plan']['current']['index'] == 3
            skipped_id = resumed['generated']['id']; preserved = self.entity(ctx, 'tasks', skipped_id)
            self.preview(page, '跳过本期并保留事项'); skipped = self.confirm(page)
            assert skipped['plan']['current']['index'] == 4 and skipped['generated']['id'] != skipped_id
            assert next(h for h in skipped['plan']['history'] if h['entityId'] == skipped_id)['state'] == 'skipped'
            assert self.entity(ctx, 'tasks', skipped_id) == preserved
            history = skipped['plan']['history']
            all_entities = self.snapshot()['entities']
            self.preview(page, '归档计划'); archived = self.confirm(page)
            assert archived['plan']['state'] == 'archived' and archived['generated'] is None
            assert archived['plan']['history'] == history
            assert self.snapshot()['entities'] == all_entities
            assert self.application.extensions['household_routines'].tick()['generated'] == 0
            self.report['worker'] = {'actualTickCalled': True, 'realWallClockSchedulingVerified': False}
            self.passed('Real completion/pause success followed by dropped context removes old details/actions until explicit GET; worker generates exactly one successor and pause/resume/skip/archive preserve prior entities/history')

    def boundaries(self, browser):
        with self.flow(browser) as (ctx, page), ExitStack() as stack:
            created = self.api_create(ctx, '共享管理的合成家庭计划'); plan = created['plan']
            partner = self.context(browser, 2); stack.callback(partner.close)
            partner_page = partner.new_page(); self.open_panel(partner_page); self.detail(partner_page, plan)
            self.preview(partner_page, '暂停计划'); saved = self.confirm(partner_page)
            assert self.plan(ctx, plan['id'])['state'] == saved['plan']['state'] == 'paused'
            self.get(partner, BASE + '/operations/' + created['operationKey'], 404)
            foreign = self.context(browser, None); stack.callback(foreign.close)
            invite = self.write(ctx, 'POST', '/api/spaces/invitations', {}, 201)['invitation']
            entry = self.write(ctx, 'POST', '/api/spaces/redeem', dict(invitation=invite, name='合成例行第二家庭', slug='routines-other',
                MEMBER1_PASSWORD='testing-password-one', MEMBER2_PASSWORD='testing-password-two'), 201)['entry']
            assert foreign.request.get(self.base + entry).status == 200
            self.login(foreign)
            assert self.context_data(foreign)['plans'] == []
            self.get(foreign, BASE + '/context?planId=' + plan['id'], 404)
            self.get(foreign, BASE + '/operations/' + created['operationKey'], 404)
            pending = self.write(ctx, 'POST', BASE + '/preview', self.payload(ctx, '不得跨成员转交的预览'))
            before = self.snapshot()
            for other in (partner, foreign):
                self.write(other, 'POST', BASE + '/confirm', {'previewToken': pending['previewToken']}, 403)
            tv = self.context(browser, None); stack.callback(tv.close)
            pair = tv.request.post(self.base + '/api/pair/start', data={}); assert pair.status == 200
            self.write(ctx, 'POST', '/api/pair/approve', {'code': pair.json()['code'], 'name': '合成例行只读电视'})
            polled = tv.request.post(self.base + '/api/pair/poll', data={'secret': pair.json()['secret']})
            assert polled.status == 200 and polled.json()['approved']
            assert any(c['name'] == 'household_tv' and c['httpOnly'] for c in tv.cookies())
            self.get(tv, BASE + '/context', 403); self.get(tv, BASE + '/operations/' + created['operationKey'], 403)
            csrf = self.get(ctx, '/api/me')['csrf']
            denied = tv.request.post(self.base + BASE + '/confirm', data={'previewToken': pending['previewToken']},
                headers={'Origin': self.base, 'X-CSRF-Token': csrf})
            assert denied.status == 403
            assert any(item['id'] == created['generated']['id'] for item in self.get(tv, '/api/state')['tasks'])
            # Pair approval legitimately audits; compare business records, not its audit row.
            assert all(self.snapshot()[t] == before[t] for t in ('household_routines', 'routine_occurrences', 'routine_receipts', 'entities'))
            self.passed('Partner UI manages shared plan but not owner receipt; actual second household and HttpOnly paired TV reject management/token transfer while TV sees generated shared tasks')

    def conflict(self, browser):
        with self.flow(browser) as (ctx, page):
            created = self.api_create(ctx, '合成冲突原计划'); plan = created['plan']
            self.open_panel(page); self.detail(page, plan); button(page, '编辑例行计划').click()
            field(page, '例行计划名称').fill('合成保留我的计划名称')
            external = self.api_operation(ctx, plan, 'update', template={**plan['template'], 'note': '另一成员已确认的新备注'}, schedule=plan['schedule'])['plan']
            before = self.snapshot()
            with page.expect_response(lambda r: urlsplit(r.url).path == BASE + '/preview' and r.request.method == 'POST') as response:
                button(page, '预览例行计划').click()
            assert response.value.status == 409
            expect(field(page, '例行计划名称')).to_have_value('合成保留我的计划名称')
            expect(page.get_by_test_id('routines-conflict')).to_be_visible()
            count = self.count_requests('POST', BASE + '/confirm')
            button(page, '读取最新计划').click(); expect(button(page, '保留草稿重新核对')).to_be_enabled(timeout=15000)
            button(page, '保留草稿重新核对').click()
            expect(field(page, '例行计划备注')).to_have_value(external['template']['note'])
            assert self.snapshot() == before and self.count_requests('POST', BASE + '/confirm') == count
            preview = self.preview(page); assert preview['before']['revision'] == external['revision']
            result = self.confirm(page)
            assert result['plan']['template']['title'] == '合成保留我的计划名称'
            assert result['plan']['template']['note'] == external['template']['note']
            assert result['generated'] is None and result['plan']['current']['entityId'] == plan['current']['entityId']
            self.passed('Actual concurrent revision yields 409 with draft intact; explicit fresh-read/keep merges unchanged fields, and separate preview/confirm saves without regenerating current item')

    def lose_confirmation(self, page, committed):
        attempts, saved = [], []
        def lose(route):
            if route.request.method != 'POST':
                return route.continue_()
            attempts.append(route.request.post_data_json)
            if committed:
                response = route.fetch(max_redirects=0); assert response.status == 200, response.text()
                saved.append(response.json())
            route.abort('failed')
        page.route(self.base + BASE + '/confirm', lose)
        button(page, '确认例行计划操作').click()
        expect(page.get_by_test_id('routines-unknown')).to_be_visible(timeout=15000)
        # unknown is installed BEFORE fetch; wait for busy to finish before unroute.
        expect(button(page, '核对例行操作结果')).to_be_enabled(timeout=15000)
        assert len(attempts) == 1 and len(saved) == int(committed)
        page.unroute(self.base + BASE + '/confirm', lose)
        return attempts[0], saved[0] if saved else None

    def unknown(self, browser, committed):
        with self.flow(browser) as (ctx, page):
            self.open_panel(page); self.create_form(page, '合成未知请求' + str(committed))
            preview = self.preview(page); before = self.snapshot()
            intent, saved = self.lose_confirmation(page, committed)
            assert intent == {'previewToken': preview['previewToken']}
            count = self.count_requests('POST', BASE + '/confirm')
            self.nav_lock(page)
            expect(button(page, '返回例行计划入口')).to_be_disabled()
            expect(button(page, '返回例行计划列表')).to_be_disabled()
            with page.expect_response(lambda r: urlsplit(r.url).path == BASE + '/operations/' + preview['operationKey']) as receipt:
                button(page, '核对例行操作结果').click()
            assert receipt.value.status == (200 if committed else 404)
            assert self.count_requests('POST', BASE + '/confirm') == count
            if committed:
                self.confirmed(page)
                assert receipt.value.json()['planId'] == saved['plan']['id']
            else:
                expect(button(page, '按原请求重试')).to_be_enabled(timeout=15000)
                expect(page.get_by_test_id('routines-unknown')).to_be_visible()
                expect(page.locator('body')).to_contain_text('不能据此判断未执行')
                assert self.snapshot() == before
                with page.expect_response(lambda r: urlsplit(r.url).path == BASE + '/confirm' and r.request.method == 'POST') as retry:
                    button(page, '按原请求重试').click()
                assert retry.value.status == 200 and retry.value.request.post_data_json == intent
                saved = retry.value.json(); self.confirmed(page)
            assert saved['operationKey'] == preview['operationKey']
            after = self.snapshot()
            replay = self.write(ctx, 'POST', BASE + '/confirm', intent)
            assert replay['replayed'] and replay['plan']['id'] == saved['plan']['id'] and self.snapshot() == after
            assert len(after['routine_receipts']) == len(before['routine_receipts']) + 1
            assert len(after['entities']) == len(before['entities']) + 1
            button(page, '返回例行计划入口').click()
            expect(page.get_by_role('heading', name='更多', exact=True)).to_be_visible()
            page.get_by_role('tab', name='首页', exact=True).click(); expect(button(page, '安排首页')).to_be_enabled(timeout=15000)
            self.passed(('Committed lost reply' if committed else 'Dropped before delivery') + ': unknown locks navigation; GET alone never repeats POST; original-token recovery creates one receipt/entity and explicit resolved exit unlocks navigation')

    def expiry(self, browser):
        with self.flow(browser) as (ctx, page):
            self.open_panel(page); self.create_form(page, '合成过期但已写入计划')
            original = self.preview(page); intent, saved = self.lose_confirmation(page, True)
            # Change current state after the historical operation, then recover later.
            self.api_operation(ctx, self.plan(ctx, saved['plan']['id']), 'archive')
            generated = self.entity(ctx, 'tasks', saved['generated']['id'])
            self.write(ctx, 'DELETE', '/api/items/tasks/' + generated['id'], {'revision': generated['revision']})
            self.signing_offset += 601
            before = self.snapshot()
            button(page, '核对例行操作结果').click(); self.confirmed(page)
            expect(page.get_by_test_id('routine-detail')).to_contain_text('当前事项已删除')
            assert self.plan(ctx, saved['plan']['id'])['state'] == 'archived'
            replay = self.write(ctx, 'POST', BASE + '/confirm', intent)
            assert replay['replayed'] and replay['operationKey'] == original['operationKey'] and self.snapshot() == before
            button(page, '返回例行计划列表').click()
            self.create_form(page, '合成过期尚未执行计划'); original = self.preview(page)
            intent, _ = self.lose_confirmation(page, False); self.signing_offset += 601
            before = self.snapshot()
            button(page, '核对例行操作结果').click(); expect(button(page, '按原请求重试')).to_be_enabled()
            expect(page.get_by_test_id('routines-unknown')).to_be_visible()
            with page.expect_response(lambda r: urlsplit(r.url).path == BASE + '/confirm' and r.request.method == 'POST') as expired:
                button(page, '按原请求重试').click()
            assert expired.value.status == 410 and expired.value.json()['code'] == 'preview_expired_unapplied'
            assert expired.value.request.post_data_json == intent and self.snapshot() == before
            expect(page.get_by_test_id('routines-unknown')).to_have_count(0)
            button(page, '读取最新计划').click(); expect(button(page, '保留草稿重新核对')).to_be_enabled()
            button(page, '保留草稿重新核对').click()
            fresh = self.preview(page); assert fresh['operationKey'] != original['operationKey']
            self.confirm(page)
            self.passed('Actual signer clock +601s: applied receipt/replay remains readable without resurrecting deleted/archived state; unapplied original retry returns exact 410 with zero writes before fresh explicit preview')

    def visibility_boundaries(self, browser):
        with self.flow(browser) as (ctx, page):
            self.open_panel(page); self.create_form(page, '合成仅内存例行草稿')
            before = self.snapshot(); writes = self.count_requests('POST', BASE + '/confirm')
            ctx.set_offline(True); expect(field(page, '例行计划名称')).to_be_hidden()
            ctx.set_offline(False); expect(field(page, '例行计划名称')).to_have_value('合成仅内存例行草稿', timeout=15000)
            self.nav_lock(page)
            visibility(page, True); expect(field(page, '例行计划名称')).to_be_hidden()
            held = []
            def hold(route):
                response = route.fetch(max_redirects=0); assert response.status == 200
                held.append((route, response))
            page.route(self.base + BASE + '/context?*', hold, times=1)
            visibility(page, False); self.settle(page, lambda: bool(held)); visibility(page, True)
            held[0][0].fulfill(response=held[0][1]); page.wait_for_timeout(250)
            expect(field(page, '例行计划名称')).to_be_hidden()
            visibility(page, False); expect(field(page, '例行计划名称')).to_have_value('合成仅内存例行草稿', timeout=15000)
            assert self.snapshot() == before and self.count_requests('POST', BASE + '/confirm') == writes
            button(page, '返回例行计划入口').click(); button(page, '确认放弃例行修改').click()
            expect(page.get_by_role('heading', name='更多', exact=True)).to_be_visible()
            page.get_by_role('tab', name='首页', exact=True).click(); expect(button(page, '安排首页')).to_be_enabled(timeout=15000)
            self.passed('Real offline and simulated background hide and preserve same-identity draft; late actual GET cannot restore hidden content; zero business writes and explicit discard unlocks navigation')

    def identity_boundary(self, browser):
        with self.flow(browser) as (ctx, page):
            self.open_panel(page); self.create_form(page, '合成旧身份的未确认草稿')
            before = self.snapshot(); held = []
            def switch_preview(route):
                response = route.fetch(max_redirects=0); assert response.status == 200
                self.login(ctx, 2); route.fulfill(response=response); held.append(response.json()['operationKey'])
            page.route(self.base + BASE + '/preview', switch_preview, times=1)
            button(page, '预览例行计划').click(); self.settle(page, lambda: len(held) == 1)
            expect(page.get_by_test_id('routines-panel')).to_have_count(0, timeout=15000)
            expect(page.locator('body')).not_to_contain_text('合成旧身份的未确认草稿')
            assert self.snapshot() == before
            self.login(ctx, 1); self.open_panel(page); self.create_form(page, '合成旧身份已提交回执')
            preview = self.preview(page); committed = []
            def switch_confirm(route):
                response = route.fetch(max_redirects=0); assert response.status == 200
                self.login(ctx, 2); route.fulfill(response=response); committed.append(response.json())
            page.route(self.base + BASE + '/confirm', switch_confirm, times=1)
            button(page, '确认例行计划操作').click()
            self.settle(page, lambda: len(committed) == 1)  # Do not mistake the pre-fetch hidden editor for completed I/O.
            expect(page.get_by_test_id('routines-panel')).to_have_count(0, timeout=15000)
            expect(page.get_by_test_id('routines-receipt')).to_have_count(0)
            self.get(ctx, BASE + '/operations/' + preview['operationKey'], 404)
            # Shared plan is legitimately visible to partner; only the old actor's
            # draft/token/receipt must disappear, not the shared business record.
            assert self.plan(ctx, committed[0]['plan']['id'])['template']['title'] == '合成旧身份已提交回执'
            self.passed('Real member-cookie changes before final /me discard late preview and committed reply; no old draft/receipt installs, partner receipt is 404 while shared plan remains legitimately readable')

    def run_scenarios(self, browser):
        for scenario in (self.creation_and_restart, self.shopping_budgets, self.progression, self.boundaries, self.conflict):
            scenario(browser)
        self.unknown(browser, True); self.unknown(browser, False)
        for scenario in (self.expiry, self.visibility_boundaries, self.identity_boundary):
            scenario(browser)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--expected-build-evidence', required=True)
    args = parser.parse_args(); root, bundle = args.source_root.resolve(), args.bundle.resolve()
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    assert head == args.expected_head
    evidence_path = bundle.parent / 'build-evidence.json'; assert sha(evidence_path) == args.expected_build_evidence
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    assert evidence['sourceHead'] == head
    assert evidence['sourceTree'] == subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=root, text=True).strip()
    assert not subprocess.check_output(['git', 'status', '--porcelain=v1', '--untracked-files=no'], cwd=root, text=True).strip()
    names = subprocess.check_output(['git', 'ls-files'], cwd=root, text=True).splitlines()
    hashes = lambda: {name: sha(root / name) for name in names}
    exports = lambda: {p.relative_to(bundle).as_posix(): sha(p) for p in bundle.rglob('*') if p.is_file()}
    assert exports() == evidence['files']
    assert all(sha(root / name) == digest for name, digest in evidence['inputFiles'].items())
    out = Path(__file__).resolve().parents[1] / 'test-results' / ('expo-routines-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True); shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], screenshots=[], head=head, tree=evidence['sourceTree'],
        buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(out / 'executed-harness.py'),
        sourceHashesBefore=hashes(), bundleHashesBefore=exports(), productionWrites=0, realCloud=False, realAI=False, physicalTelevision=False,
        scope='Real isolated Flask/SQLite/Edge and synthetic records. Actual tick called explicitly, no real wall-clock scheduling; signer clock and visibility controlled by fixture. No successful business mocks, real cloud, files or physical devices.')
    original_connect = socket.socket.connect
    def local_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
            report['externalRequests'].append({'kind': 'non-loopback socket'}); raise AssertionError('External network forbidden')
        return original_connect(sock, address)
    folder = None
    try:
        with patch.object(socket.socket, 'connect', local_connect), sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            try:
                with ExitStack() as lifecycle:
                    folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='expo-routines-')))
                    Run(root, bundle, folder, report, out, lifecycle).run_scenarios(browser)
                    assert len(report['checks']) == CHECKS and len(report['screenshots']) == 12
                    assert not report['pageErrors'] and not report['externalRequests']
                    report['passed'] = True
            finally:
                browser.close()
    except Exception:
        report['passed'] = False; report['failure'] = traceback.format_exc()
        print(report['failure'], flush=True)
    finally:
        report['sourceHashesAfter'] = hashes(); report['bundleHashesAfter'] = exports()
        report['sourceUnchanged'] = report['sourceHashesBefore'] == report['sourceHashesAfter']
        report['bundleUnchanged'] = report['bundleHashesBefore'] == report['bundleHashesAfter']
        report['temporaryFixtureRemoved'] = folder is not None and not folder.exists()
        report['passed'] = report['passed'] and report['sourceUnchanged'] and report['bundleUnchanged'] and report['temporaryFixtureRemoved']
        (out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'report': str(out / 'result.json')}, ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    raise SystemExit(main())
