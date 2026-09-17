"""Frozen member appearance with real local Flask, SQLite and Edge.

Eleven bounded flows use synthetic households and genuine member/TV cookies.
Interceptions only delay/drop real responses or switch a real login cookie;
they never substitute successful business JSON, HTML, or a cloud provider.
Run only after independent review of this harness and a frozen Expo export.
"""
import argparse
from contextlib import ExitStack, closing
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
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright
import browser_expo_finance_check as fixture
from browser_expo_finance_check import Run as BaseRun, button, row, sha, visibility


PATH = '/api/preferences'
DEFAULTS = dict(theme='forest', density='comfortable', homeView='today', colorMode='light')
WIDTHS = (320, 390, 1280, 1920)


def radio(page, name):
    return page.get_by_role('radio', name=name, exact=True)


class Run(BaseRun):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        assert Path(self.source.__file__).resolve() == (self.root / 'app.py').resolve()
        self.report['fixtureHashes'] = {}
        for file, name in ((Path(fixture.__file__), 'tests/browser_expo_finance_check.py'),
                           (Path(__file__), 'tests/browser_expo_appearance_check.py')):
            assert sha(file) == sha(self.root / name)
            self.report['fixtureHashes'][name] = sha(file)

    def clear_finance(self):
        pass  # Only inherit the isolated server/auth/lifecycle helpers.

    def snapshot(self):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database)) as con:
            return {table: sorted(con.execute('SELECT * FROM ' + table).fetchall(), key=repr)
                    for table in ('member_preferences', 'audit', 'settings')}

    def preferences(self, ctx):
        return self.get(ctx, PATH)

    def set_preferences(self, ctx, **changes):
        current = self.preferences(ctx)
        return self.write(ctx, 'PUT', PATH, {'revision': current['revision'], 'changes': changes})

    def open_panel(self, page):
        page.goto(self.base + '/app/more')
        expect(page.get_by_role('heading', name='更多', exact=True)).to_be_visible(timeout=15000)
        entry = page.get_by_label('外观设置', exact=True)
        expect(entry).to_have_count(1)
        entry.click()
        expect(page.get_by_role('heading', name='我的外观', exact=True)).to_be_visible()
        expect(radio(page, '浅色外观')).to_be_enabled(timeout=15000)

    def home(self, page):
        page.goto(self.base + '/app/home')
        expect(button(page, '安排首页')).to_be_enabled(timeout=15000)

    def save(self, page):
        self.target_size(button(page, '保存外观设置'), 'appearance-save')
        with page.expect_response(lambda response: urlsplit(response.url).path == PATH
                                  and response.request.method == 'PUT') as pending:
            button(page, '保存外观设置').click()
        reply = pending.value
        assert reply.status == 200, reply.text()
        result = reply.json()
        expect(page.get_by_text('外观设置已保存。', exact=True)).to_be_visible()
        expect(button(page, '保存外观设置')).to_be_disabled()
        assert self.preferences(page.context) == result
        return result

    def mode(self, page, color):
        expected = 'rgb(17, 17, 19)' if color == 'dark' else 'rgb(255, 255, 255)'
        page.wait_for_function('expected => getComputedStyle(document.body).backgroundColor === expected', arg=expected)
        actual = page.evaluate('''() => ({body:getComputedStyle(document.body).backgroundColor,
          html:getComputedStyle(document.documentElement).backgroundColor,
          colorScheme:getComputedStyle(document.documentElement).colorScheme})''')
        assert actual['body'] == expected and actual['html'] == expected
        assert actual['colorScheme'] == color
        return actual

    def contrast(self, locator, label):
        # A bounded computed-style sample, not a whole-page accessibility audit.
        expect(locator).to_be_visible()
        result = locator.evaluate('''node => {
          const rgb=s=>(s.match(/[\\d.]+/g)||[]).map(Number);
          const foreground=getComputedStyle(node).color;
          let ancestor=node, background='';
          while(ancestor){const c=getComputedStyle(ancestor).backgroundColor;
            if(rgb(c).length===3 || rgb(c)[3]===1){background=c;break;} ancestor=ancestor.parentElement;}
          const luminance=c=>rgb(c).slice(0,3).map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4)
            .reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
          const a=luminance(foreground),b=luminance(background);
          return {foreground,background,contrast:(Math.max(a,b)+.05)/(Math.min(a,b)+.05),
            fontSize:getComputedStyle(node).fontSize,text:node.textContent.slice(0,120)};
        }''')
        assert result['background'] and result['contrast'] >= 4.5, (label, result)
        self.report['styleSamples'].append({'label': label, **result})
        return result

    def target_size(self, control, label, required=True):
        box = control.bounding_box()
        assert box, label
        self.report['controlSamples'].append({'label': label, 'width': box['width'], 'height': box['height'],
            'requires44px': required})
        if required:
            assert box['width'] >= 44 and box['height'] >= 44, (label, box)

    def shot(self, page, name, width):
        page.set_viewport_size({'width': width, 'height': 1080 if width >= 1280 else 844})
        page.evaluate('() => document.fonts.ready')
        page.wait_for_timeout(400)  # Settle Paper's focus/label/responsive transitions.
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2'), (name, width)
        target = self.out / f'{name}-{width}.png'
        page.screenshot(path=str(target), full_page=False)
        self.report['screenshots'].append({'path': target.name, 'sha256': sha(target), 'width': width,
            'scope': 'Current viewport only; internal ScrollView contents are not all captured.'})

    def keyboard_and_widths(self, page):
        self.set_preferences(page.context, **DEFAULTS)
        self.open_panel(page)
        before, writes = self.snapshot(), self.count_requests('PUT', PATH)
        self.mode(page, 'light')
        for width in WIDTHS:
            self.shot(page, 'appearance-light', width)
            for name in ('浅色外观', '深色外观', '标准密度', '紧凑密度'):
                self.target_size(radio(page, name), f'{name}-{width}')
            for name in ('保存外观设置', '返回更多', '关闭外观设置'):
                self.target_size(button(page, name), f'{name}-{width}')
        page.set_viewport_size({'width': 320, 'height': 844})
        radio(page, '浅色外观').focus(); page.keyboard.press('ArrowDown')
        expect(radio(page, '深色外观')).to_be_checked()
        expect(radio(page, '深色外观')).to_be_focused()
        page.keyboard.press('ArrowUp'); expect(radio(page, '浅色外观')).to_be_checked()
        radio(page, '紧凑密度').focus(); page.keyboard.press('Space')
        expect(radio(page, '紧凑密度')).to_be_checked()
        focus = radio(page, '紧凑密度').evaluate('(n)=>({width:getComputedStyle(n).borderTopWidth,color:getComputedStyle(n).borderTopColor})')
        assert float(focus['width'].replace('px', '')) >= 2 and focus['color'] != 'rgba(0, 0, 0, 0)'
        self.report['focusSample'] = focus
        self.shot(page, 'appearance-keyboard-focus', 320)
        assert self.snapshot() == before and self.count_requests('PUT', PATH) == writes
        # Select the original state again; selection alone never writes.
        radio(page, '标准密度').click()
        expect(button(page, '保存外观设置')).to_be_disabled()
        self.passed('Four editor widths fit the viewport with 44px selection targets; real arrow/space focus and ARIA changes do not write preferences')

    def persistence_and_density(self, page):
        task = self.write(page.context, 'POST', '/api/items/tasks', {'title': '合成键盘待办', 'owner': 'shared'}, 201)
        self.home(page)
        title = page.get_by_role('heading', name='我，欢迎回家', exact=True)
        comfortable_font = title.evaluate('(n)=>getComputedStyle(n).fontSize')
        assert page.get_by_test_id('home-card-grid').evaluate('(n)=>parseFloat(getComputedStyle(n).gap)') == 20
        self.open_panel(page)
        radio(page, '深色外观').click(); radio(page, '紧凑密度').click()
        prior = self.preferences(page.context)
        saved = self.save(page)
        assert saved == {**prior, 'colorMode': 'dark', 'density': 'compact', 'revision': prior['revision'] + 1}
        self.mode(page, 'dark')
        for width in (390, 1280): self.shot(page, 'appearance-dark', width)
        button(page, '关闭外观设置').click()
        self.home(page); self.mode(page, 'dark')
        assert title.evaluate('(n)=>getComputedStyle(n).fontSize') == comfortable_font
        assert page.get_by_test_id('home-card-grid').evaluate('(n)=>parseFloat(getComputedStyle(n).gap)') == 12
        for width in WIDTHS:
            self.shot(page, 'home-dark-compact', width)
            self.contrast(title, f'home-heading-{width}')
            # Existing compact range controls are measured, not expanded into
            # a new all-interface touch-target failure matrix in this batch.
            for name in ('今日', '本周', '前后 3 天'):
                control = page.get_by_role('button', name=name, exact=True)
                self.target_size(control, f'existing-home-range-{name}-{width}', required=False)
            create = button(page, '新建记录') if width < 1280 else page.get_by_role('button', name=re.compile(r'新建$'))
            expect(create).to_have_count(1)
            for control in (button(page, '刷新家庭数据'), create):
                box = control.bounding_box()
                assert box and box['width'] >= 44 and box['height'] >= 44, (width, box)
        page.reload(); expect(button(page, '安排首页')).to_be_enabled()
        self.mode(page, 'dark'); assert self.preferences(page.context) == saved
        control = page.get_by_role('checkbox', name='完成待办：合成键盘待办', exact=True)
        self.target_size(control, 'home-task-checkbox')
        path = '/api/items/tasks/' + task['id']; writes = self.count_requests('PATCH', path)
        control.focus()
        with page.expect_response(lambda r: urlsplit(r.url).path == path and r.request.method == 'PATCH') as pending:
            page.keyboard.press('Space')
        assert pending.value.status == 200
        expect(control).to_be_hidden()
        stored = next(v for v in self.get(page.context, '/api/state')['tasks'] if v['id'] == task['id'])
        assert stored['done'] and stored['revision'] == task['revision'] + 1
        assert self.count_requests('PATCH', path) == writes + 1
        self.passed('Explicit PUT persists dark/compact across home/refresh; gaps change 20 to 12 without shrinking heading text; the enlarged task checkbox Space performs exactly one genuine PATCH')

    def isolation(self, browser, page):
        owner = page.context
        with ExitStack() as stack:
            second = self.context(browser); stack.callback(second.close)
            second_page = second.new_page(); self.home(second_page); self.mode(second_page, 'dark')
            assert self.preferences(second) == self.preferences(owner)
            partner = self.context(browser, member=2); stack.callback(partner.close)
            assert self.preferences(partner) == {**DEFAULTS, 'revision': 0}
            partner_page = partner.new_page(); self.home(partner_page); self.mode(partner_page, 'light')
            tv = self.context(browser, member=None); stack.callback(tv.close)
            pair = tv.request.post(self.base + '/api/pair/start', data={})
            assert pair.status == 200
            self.write(owner, 'POST', '/api/pair/approve', {'code': pair.json()['code'], 'name': '合成独立电视', 'focus': 'member2'})
            polled = tv.request.post(self.base + '/api/pair/poll', data={'secret': pair.json()['secret']})
            assert polled.status == 200 and polled.json()['approved']
            assert any(c['name'] == 'household_tv' and c['httpOnly'] for c in tv.cookies())
            tv_requests = []
            tvpage = tv.new_page(); tvpage.on('request', lambda r: tv_requests.append(urlsplit(r.url).path))
            tvpage.goto(self.base + '/app/tv')
            expect(tvpage.get_by_test_id('expo-tv-board')).to_be_visible(timeout=15000)
            before = self.get(tv, '/api/state'); devices = self.get(owner, '/api/devices')
            self.open_panel(page); radio(page, '标准密度').click(); self.save(page)
            tvpage.reload(); expect(tvpage.get_by_test_id('expo-tv-board')).to_be_visible(timeout=15000)
            after = self.get(tv, '/api/state')
            project = lambda value: {k: v for k, v in value.items() if k not in ('revision', 'updatedAt')}
            assert project(before) == project(after) and self.get(owner, '/api/devices') == devices
            assert PATH not in tv_requests
            self.get(tv, PATH, 403)
            assert self.preferences(partner) == {**DEFAULTS, 'revision': 0}
            invitation = self.write(owner, 'POST', '/api/spaces/invitations', {}, 201)['invitation']
            family = self.write(owner, 'POST', '/api/spaces/redeem', {'invitation': invitation,
                'name': '合成外观第二家庭', 'slug': 'appearance-other',
                'MEMBER1_PASSWORD': 'testing-password-one', 'MEMBER2_PASSWORD': 'testing-password-two'}, 201)
            child = self.context(browser, member=None); stack.callback(child.close)
            assert child.request.get(self.base + family['entry']).status == 200
            self.login(child)
            assert self.preferences(child) == {**DEFAULTS, 'revision': 0}
            self.set_preferences(child, theme='ocean')
            assert self.preferences(owner)['theme'] == 'forest' and self.preferences(partner)['theme'] == 'forest'
        self.passed('Second browser sees the same member settings; partner and signed second household remain independent; a genuinely paired TV never reads preferences and retains its display/state')

    def conflict(self, page):
        self.set_preferences(page.context, **DEFAULTS); self.open_panel(page)
        radio(page, '深色外观').click()
        latest = self.set_preferences(page.context, density='compact')
        before, writes = self.snapshot(), self.count_requests('PUT', PATH)
        with page.expect_response(lambda r: urlsplit(r.url).path == PATH and r.request.method == 'PUT') as pending:
            button(page, '保存外观设置').click()
        assert pending.value.status == 409
        expect(button(page, '查看最新外观设置')).to_be_enabled()
        expect(radio(page, '深色外观')).to_be_checked()
        expect(button(page, '保存外观设置')).to_be_disabled()
        button(page, '查看最新外观设置').click()
        expect(button(page, '保留我的修改')).to_be_enabled()
        for name in ('采用当前设置', '保留我的修改'):
            self.target_size(button(page, name), name)
        assert self.snapshot() == before and self.count_requests('PUT', PATH) == writes + 1
        button(page, '保留我的修改').click()
        expect(radio(page, '深色外观')).to_be_checked(); expect(radio(page, '紧凑密度')).to_be_checked()
        assert self.snapshot() == before
        saved = self.save(page)
        assert saved == {**latest, 'colorMode': 'dark', 'revision': latest['revision'] + 1}
        # Exercise the alternative explicit adoption without saving this draft.
        radio(page, '浅色外观').click(); latest = self.set_preferences(page.context, theme='ocean')
        button(page, '保存外观设置').click(); expect(button(page, '查看最新外观设置')).to_be_enabled()
        button(page, '查看最新外观设置').click(); expect(button(page, '采用当前设置')).to_be_enabled()
        before, writes = self.snapshot(), self.count_requests('PUT', PATH)
        button(page, '采用当前设置').click()
        expect(radio(page, '深色外观')).to_be_checked(); expect(button(page, '保存外观设置')).to_be_disabled()
        assert self.preferences(page.context) == latest and self.snapshot() == before and self.count_requests('PUT', PATH) == writes
        self.passed('Real CAS conflicts retain drafts; GET and explicit keep/adopt do not write; keeping merges only edited fields and needs a separate confirmed PUT')

    def blocked_navigation(self, page, text):
        page.set_viewport_size({'width': 390, 'height': 844})
        original = page.url
        page.get_by_role('tab', name='首页', exact=True).click()
        expect(page.get_by_text(text, exact=True)).to_be_visible()
        button(page, '知道了').click()
        expect(page.get_by_test_id('appearance-panel')).to_be_visible()
        assert page.url == original

    def committed_reply_loss(self, page):
        self.set_preferences(page.context, **DEFAULTS); self.open_panel(page)
        radio(page, '深色外观').click()
        self.blocked_navigation(page, '外观设置还未保存，请先保存或放弃修改。')
        original, attempts = self.preferences(page.context), []
        def lose(route):
            if route.request.method != 'PUT': return route.continue_()
            attempts.append(route.request.post_data_json)
            response = route.fetch(max_redirects=0)
            assert response.status == 200
            route.abort('failed')
        page.route(self.base + PATH, lose)
        button(page, '保存外观设置').click()
        expect(button(page, '核对外观保存结果')).to_be_enabled()
        self.target_size(button(page, '核对外观保存结果'), 'appearance-unknown-readback')
        page.unroute(self.base + PATH, lose)
        assert len(attempts) == 1 and attempts[0] == {'revision': original['revision'], 'changes': {'colorMode': 'dark'}}
        saved = self.preferences(page.context)
        assert saved == {**original, 'colorMode': 'dark', 'revision': original['revision'] + 1}
        expect(button(page, '关闭外观设置')).to_be_disabled()
        self.blocked_navigation(page, '外观设置的保存结果尚未核对，请先核对当前外观设置。')
        before, writes = self.snapshot(), self.count_requests('PUT', PATH)
        button(page, '核对外观保存结果').click()
        expect(button(page, '采用当前设置')).to_be_enabled()
        assert self.snapshot() == before and self.count_requests('PUT', PATH) == writes
        button(page, '采用当前设置').click()
        expect(page.get_by_test_id('appearance-unknown')).to_be_hidden()
        expect(button(page, '保存外观设置')).to_be_disabled()
        button(page, '关闭外观设置').click()
        page.get_by_role('tab', name='首页', exact=True).click()
        expect(button(page, '安排首页')).to_be_enabled()
        self.mode(page, 'dark')
        assert self.snapshot() == before and self.count_requests('PUT', PATH) == writes
        self.passed('Dirty/unknown navigation stays locked; committed reply loss saves exactly once, then GET plus explicit adoption releases navigation without another PUT')

    def offline_preflight(self, page):
        self.set_preferences(page.context, **DEFAULTS); self.open_panel(page)
        radio(page, '深色外观').click()
        before, writes = self.snapshot(), self.count_requests('PUT', PATH)
        page.context.set_offline(True)
        expect(radio(page, '深色外观')).to_be_hidden(); expect(button(page, '保存外观设置')).to_be_hidden()
        assert self.snapshot() == before and self.count_requests('PUT', PATH) == writes
        page.context.set_offline(False)
        expect(radio(page, '深色外观')).to_be_enabled(timeout=15000); expect(radio(page, '深色外观')).to_be_checked()
        failures = []
        def abort_identity(route):
            failures.append(True); route.abort('failed')
        page.route(self.base + '/api/me', abort_identity)
        button(page, '保存外观设置').click()
        expect(page.get_by_role('alert')).to_be_visible(timeout=15000)
        expect(button(page, '保存外观设置')).to_be_enabled()
        page.unroute(self.base + '/api/me', abort_identity)
        assert failures and self.snapshot() == before and self.count_requests('PUT', PATH) == writes
        expect(page.get_by_test_id('appearance-unknown')).to_be_hidden()
        button(page, '放弃修改并返回').click(); button(page, '确认放弃修改').click()
        expect(page.get_by_role('heading', name='更多', exact=True)).to_be_visible()
        self.passed('Offline conceal preserves the same-identity draft; failed preflight authentication makes no PUT and creates no unknown-write claim; explicit discard leaves stored values intact')

    def hidden_late_response(self, page):
        self.set_preferences(page.context, **DEFAULTS); self.open_panel(page)
        radio(page, '深色外观').click(); visibility(page, True)
        expect(radio(page, '深色外观')).to_be_hidden()
        held = []
        def hold(route):
            assert route.request.method == 'GET'
            response = route.fetch(max_redirects=0); assert response.status == 200
            held.append((route, response))
        page.route(self.base + PATH, hold, times=1)
        before, writes = self.snapshot(), self.count_requests('PUT', PATH)
        visibility(page, False); self.settle(page, lambda: bool(held)); visibility(page, True)
        held[0][0].fulfill(response=held[0][1]); page.wait_for_timeout(300)
        expect(radio(page, '深色外观')).to_be_hidden()
        visibility(page, False)
        expect(radio(page, '深色外观')).to_be_enabled(timeout=15000); expect(radio(page, '深色外观')).to_be_checked()
        assert self.snapshot() == before and self.count_requests('PUT', PATH) == writes
        visibility(page, True); self.set_preferences(page.context, density='compact')
        before = self.snapshot(); visibility(page, False)
        expect(button(page, '保留我的修改')).to_be_enabled(timeout=15000)
        expect(button(page, '保存外观设置')).to_be_disabled()
        button(page, '保留我的修改').click()
        expect(radio(page, '深色外观')).to_be_checked(); expect(radio(page, '紧凑密度')).to_be_checked()
        assert self.snapshot() == before and self.count_requests('PUT', PATH) == writes
        button(page, '放弃修改并返回').click(); button(page, '确认放弃修改').click()
        self.passed('Late real GET after simulated background cannot reveal controls; unchanged revision restores draft, changed revision requires explicit review without automatic saving')

    def post_write_identity(self, browser):
        with self.flow(browser) as (ctx, page):
            self.set_preferences(ctx, **DEFAULTS)
            partner = self.context(browser, member=2)
            try: partner_before = self.preferences(partner)
            finally: partner.close()
            self.open_panel(page); radio(page, '深色外观').click()
            original, sent = self.preferences(ctx), []
            def switch(route):
                if route.request.method != 'PUT': return route.continue_()
                response = route.fetch(max_redirects=0)
                assert response.status == 200
                sent.append(response.json())
                self.login(ctx, 2)  # Genuine session switch before the old response returns.
                assert self.get(ctx, '/api/me')['user']['id'] == 'member2'
                route.fulfill(response=response)
            page.route(self.base + PATH, switch)
            button(page, '保存外观设置').click()
            expect(page.get_by_test_id('appearance-panel')).to_be_hidden(timeout=15000)
            page.unroute(self.base + PATH, switch)
            assert len(sent) == 1 and sent[0] == {**original, 'colorMode': 'dark', 'revision': original['revision'] + 1}
            assert self.preferences(ctx) == partner_before
            self.open_panel(page)
            expect(radio(page, '浅色外观')).to_be_checked()
            expect(button(page, '保存外观设置')).to_be_disabled(); self.mode(page, 'light')
            expect(page.get_by_test_id('appearance-unknown')).to_be_hidden()
        self.passed('After an actual successful PUT, a real cookie identity switch before post-check discards the old workspace and never carries its draft/settings into the partner')

    def dark_business_pages(self, page):
        self.set_preferences(page.context, colorMode='dark', density='comfortable')
        self.seed(page.context, [row('合成咖啡采购，仅本人', '168.25')])
        made = self.write(page.context, 'POST', '/api/finance-hub/investments', {
            'name': '合成长期持仓', 'institution': '演示机构', 'assetType': '基金', 'currency': 'CNY',
            'quantity': '1', 'cost': '1000.00', 'value': '1050.25', 'asOf': '2026-09-17', 'note': '仅合成数据'}, 201)
        assert made['valueCents'] == 105025
        for route, title in (('finance', '家庭资金'), ('investments', '我的持仓'), ('connections', '账户与同步')):
            page.goto(self.base + '/app/' + route)
            heading = page.get_by_role('heading', name=title, exact=True)
            expect(heading).to_be_visible(timeout=15000); self.mode(page, 'dark')
            if route == 'finance':
                self.ledger(page)
                expect(button(page, '查看交易合成咖啡采购，仅本人')).to_be_enabled()
                sample = page.get_by_text('合成咖啡采购，仅本人', exact=True)
            elif route == 'investments':
                expect(button(page, '新增持仓')).to_be_enabled()
                sample = page.get_by_text('合成长期持仓', exact=True)
            else:
                sample = page.get_by_text('还没有连接账户', exact=True)
            expect(sample).to_be_visible()
            self.contrast(sample, route + '-record-or-empty-state')
            for width in (390, 1280):
                self.shot(page, 'dark-' + route, width); self.contrast(heading, f'{route}-heading-{width}')
        self.passed('Dark finance ledger, real synthetic holdings and unconfigured accounts are readable at phone/desktop widths; sampled real colors meet 4.5 contrast without authorizing any cloud provider')

    def classic(self, page):
        page.goto(self.base + '/classic')  # /?classic=1 is NOT a classic route.
        entry = page.locator('[data-ps-preferences]').first
        expect(entry).to_be_visible(timeout=15000); entry.click()
        form = page.locator('#ps-preferences-form')
        expect(form).to_be_visible()
        expect(form.locator('[name="density"]')).to_be_enabled()
        return form

    def classic_save(self, page):
        with page.expect_response(lambda r: urlsplit(r.url).path == PATH and r.request.method == 'PUT') as pending:
            button(page, '保存并同步').click()
        response = pending.value
        assert response.status == 200, response.text()
        expect(page.locator('#ps-preferences-form')).to_be_hidden()
        return response.json()

    def classic_save_and_conflict(self, page):
        self.set_preferences(page.context, **{**DEFAULTS, 'colorMode': 'dark'})
        form = self.classic(page)
        form.locator('[name="theme"][value="ocean"]').check()
        form.locator('[name="density"]').select_option('compact')
        saved = self.classic_save(page)
        assert saved['colorMode'] == 'dark' and saved['theme'] == 'ocean' and saved['density'] == 'compact'
        form = self.classic(page); form.locator('[name="homeView"]').select_option('week')
        latest = self.set_preferences(page.context, density='comfortable')
        before, writes = self.snapshot(), self.count_requests('PUT', PATH)
        with page.expect_response(lambda r: urlsplit(r.url).path == PATH and r.request.method == 'PUT') as pending:
            button(page, '保存并同步').click()
        assert pending.value.status == 409
        expect(button(page, '检查已保存设置')).to_be_enabled()
        expect(form.locator('[name="homeView"]')).to_have_value('week')
        button(page, '检查已保存设置').click(); expect(button(page, '保留我的草稿')).to_be_enabled()
        assert self.snapshot() == before and self.count_requests('PUT', PATH) == writes + 1
        button(page, '保留我的草稿').click()
        expect(form.locator('[name="homeView"]')).to_have_value('week')
        expect(form.locator('[name="density"]')).to_have_value('comfortable')
        assert self.snapshot() == before and self.count_requests('PUT', PATH) == writes + 1
        saved = self.classic_save(page)
        assert saved == {**latest, 'homeView': 'week', 'revision': latest['revision'] + 1}
        self.passed('Classic DOM form uses actual CAS saves without overwriting Expo colorMode; real 409 preserves changed fields and requires readback, explicit keep, then a separate save')

    def classic_reply_loss(self, page):
        form = self.classic(page); original = self.preferences(page.context)
        target = 'around' if original['homeView'] != 'around' else 'today'
        form.locator('[name="homeView"]').select_option(target)
        attempts = []
        def lose(route):
            if route.request.method != 'PUT': return route.continue_()
            attempts.append(route.request.post_data_json)
            response = route.fetch(max_redirects=0); assert response.status == 200
            route.abort('failed')
        page.route(self.base + PATH, lose); button(page, '保存并同步').click()
        expect(button(page, '检查已保存设置')).to_be_enabled(timeout=15000)
        page.unroute(self.base + PATH, lose)
        assert len(attempts) == 1
        current = self.preferences(page.context)
        assert current == {**original, 'homeView': target, 'revision': original['revision'] + 1}
        before, writes = self.snapshot(), self.count_requests('PUT', PATH)
        button(page, '检查已保存设置').click(); expect(button(page, '使用已保存设置')).to_be_enabled()
        assert self.snapshot() == before and self.count_requests('PUT', PATH) == writes
        button(page, '使用已保存设置').click()
        expect(button(page, '保存并同步')).to_be_enabled()
        expect(form.locator('[name="homeView"]')).to_have_value(target)
        assert self.snapshot() == before and self.count_requests('PUT', PATH) == writes
        self.passed('Classic committed response loss reads the real current settings and requires explicit adoption; no automatic retry or second PUT occurs and Expo colorMode remains preserved')

    def run_scenarios(self, browser):
        with self.flow(browser) as (_, page):
            self.keyboard_and_widths(page)
            self.persistence_and_density(page)
            self.isolation(browser, page)
            self.conflict(page)
            self.committed_reply_loss(page)
            self.offline_preflight(page)
            self.hidden_late_response(page)
        self.post_write_identity(browser)
        with self.flow(browser) as (_, page):
            self.dark_business_pages(page)
            self.classic_save_and_conflict(page)
            self.classic_reply_loss(page)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--expected-build-evidence', required=True)
    args = parser.parse_args()
    root, bundle = args.source_root.resolve(), args.bundle.resolve()
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    assert head == args.expected_head
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
    out = Path(__file__).resolve().parents[1] / 'test-results' / ('expo-appearance-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], screenshots=[], styleSamples=[], controlSamples=[],
        head=head, tree=evidence['sourceTree'], buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(out / 'executed-harness.py'),
        sourceHashesBefore=hashes(), bundleHashesBefore=bundle_hashes(), productionWrites=0, realCloud=False, realAI=False,
        physicalTelevision=False, scope='Real isolated Flask/SQLite/Edge; synthetic households, records and genuine member/TV cookies. No successful business-response mocks or HTML injection. Visibilitychange is simulated. Color samples and current-viewport screenshots are bounded, not full accessibility or physical-device acceptance.')
    original_connect = socket.socket.connect
    def local_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
            report['externalRequests'].append({'kind': 'non-loopback socket'})
            raise AssertionError('External network forbidden')
        return original_connect(sock, address)
    folder = None
    try:
        with patch.object(socket.socket, 'connect', local_connect), sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            try:
                with ExitStack() as lifecycle:
                    folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='expo-appearance-')))
                    run = Run(root, bundle, folder, report, out, lifecycle)
                    run.run_scenarios(browser)
                    assert len(report['checks']) == 11 and not report['pageErrors'] and not report['externalRequests']
                    report['passed'] = True
            finally:
                browser.close()
    except Exception:
        report['failure'] = traceback.format_exc()
        print(report['failure'], flush=True)
    finally:
        report['sourceHashesAfter'] = hashes(); report['bundleHashesAfter'] = bundle_hashes()
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
