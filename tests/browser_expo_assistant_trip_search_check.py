"""Reviewed-source Expo assistant trip search on synthetic local Flask/SQLite/Edge.

Each scenario owns its HTTPS application and database. Responses are real;
faults only delay or drop them. Preparing this harness is not browser acceptance.
"""
import argparse
from contextlib import ExitStack, closing, contextmanager
from datetime import datetime, timezone
import hashlib
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
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright
import browser_expo_finance_check as fixture
from browser_expo_finance_check import Run as BaseRun, button, sha, visibility

HARNESS = 'tests/browser_expo_assistant_trip_search_check.py'
CASES = ('prefix_routing', 'details_and_return', 'delete_and_failure',
         'identity_late', 'unknown_save', 'layout')
PROMPT = '告诉助理你的需求'


class Run(BaseRun):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        assert Path(self.source.__file__).resolve() == (self.root / 'app.py').resolve()
        paths = {HARNESS: str(Path(__file__).resolve()),
                 'tests/browser_expo_finance_check.py': str(Path(fixture.__file__).resolve()),
                 'static/examples/journey-plan-v2.json': str(self.root / 'static/examples/journey-plan-v2.json'),
                 **{'tests/' + name + '.py': str(Path(sys.modules[name].__file__).resolve())
                    for name in ('test_financial_files', 'test_app')}}
        digests = {name: sha(Path(path)) for name, path in paths.items()}
        assert all(value == sha(self.root / name) for name, value in digests.items())
        assert digests[HARNESS] == self.report['harnessSha256']
        assert self.report.setdefault('fixtureActualPaths', paths) == paths
        assert self.report.setdefault('fixtureHashes', digests) == digests
        # Synthetic configuration makes the real AI option selectable. Any call
        # to either real provider path is an error, never a fabricated result.
        self.application.config.update(ASSISTANT_PROVIDER='openai',
                                       OPENAI_API_KEY='synthetic-only', OPENAI_MODEL='synthetic-only')
        assistant = sys.modules['home_assistant']
        assert Path(assistant.__file__).resolve() == (self.root / 'home_assistant.py').resolve()
        def forbidden_provider(*_args, **_kwargs):
            self.report['providerAttempts'].append(self.out.name)
            raise AssertionError('Provider calls are forbidden in local search acceptance')
        self.lifecycle.enter_context(patch.object(assistant, '_model_json', forbidden_provider))
        self.exchange_number = 0

    def clear_finance(self):
        pass  # Fresh per-case database; no business resets between checkpoints.

    def protected(self, include_plans=True):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database)) as con:
            names = ['entities', 'journey_workflows', 'journey_links', 'journey_actions']
            if include_plans:
                names.append('assistant_plans')
            return {name: hashlib.sha256(repr(sorted(con.execute('SELECT * FROM ' + name).fetchall(), key=repr)).encode()).hexdigest()
                    for name in names}

    def seed_trip(self, ctx, title, version=1):
        if version == 2:
            plan = json.loads((self.root / 'static/examples/journey-plan-v2.json').read_text(encoding='utf-8'))
            plan['title'] = title
        else:
            plan = dict(title=title, start='2027-10-01', end='2027-10-12', international=True,
                destinations=[dict(key='tokyo', city='东京', country='日本', arrival='2027-10-01', departure='2027-10-12')],
                checklist=[dict(key='packing', title='合成准备检查', owner='member1', due='2027-09-28')],
                shopping=[dict(key='unknown', title='合成未知预算', owner='member2', quantity='2 件', budget=None),
                          dict(key='zero', title='合成零预算', owner='shared', quantity='1 件', budget=0)],
                segments=[dict(key='legacy-stable', title='合成原日期段', start='2027-10-02', end='2027-10-03', note='原日期')])
        plan.update(memberIds=['member1', 'member2'], budget=1234567, saved=23456, paid=7890)
        preview = self.write(ctx, 'POST', '/api/journeys/preview', {'plan': plan})
        receipt = self.write(ctx, 'POST', '/api/journeys/apply',
                             dict(previewToken=preview['previewToken'], idempotencyKey=uuid4().hex), 201)
        detail = self.get(ctx, '/api/journeys/' + receipt['id'])
        assert detail['tripId'] == receipt['tripId'] and detail['id'] != detail['tripId']
        return detail

    def basic_trip(self, ctx, title):
        return self.write(ctx, 'POST', '/api/items/trips', dict(title=title, destination='合成目的地',
                          start='2027-10-01', end='2027-10-12', budget=0, saved=0, paid=0, owner='shared'), 201)

    @staticmethod
    def input(page):
        return page.get_by_role('textbox', name=PROMPT, exact=True)

    @staticmethod
    def edit_button(page):
        return page.get_by_role('button', name=re.compile(r'(?:^|\s)编辑旅行$'))

    def open_assistant(self, page):
        page.goto(self.base + '/app/assistant')
        expect(page.get_by_role('heading', name='家庭助理', exact=True)).to_be_visible(timeout=15000)
        expect(self.input(page)).to_be_enabled(timeout=15000)

    def actual_post(self, page, path, action, status=200, drop=False):
        self.exchange_number += 1
        calls, url = [], self.base + path
        stem = self.out / ('exchange-%02d' % self.exchange_number)
        def intercept(route):
            assert route.request.method == 'POST'
            response = route.fetch(max_redirects=0)
            raw = response.body()
            stem.with_suffix('.body').write_bytes(raw)
            calls.append(dict(payload=route.request.post_data_json, status=response.status,
                              result=json.loads(raw), responseSha256=sha(stem.with_suffix('.body'))))
            if drop:
                route.abort('failed')
            else:
                route.fulfill(status=response.status, headers=response.headers, body=raw)
        page.route(url, intercept)
        try:
            action()
            self.settle(page, lambda: len(calls) >= 1)
            assert len(calls) == 1 and calls[0]['status'] == status, calls
            return calls[0]
        finally:
            page.unroute(url, intercept)

    def search(self, page, prompt, title=None):
        self.input(page).fill(prompt)
        call = self.actual_post(page, '/api/assistant/plan', lambda: button(page, '整理并预览').click())
        assert call['payload'] == dict(prompt=prompt, useModel=False, includeHouseholdContext=False), call
        assert call['result']['mode'] == 'local' and call['result']['id'] is None and call['result']['actions'] == []
        expect(self.input(page)).to_be_enabled()
        if title:
            expect(button(page, '查看旅行 ' + title)).to_be_visible()
        return call['result']

    def open_match(self, page, title, trip_id, journey_id=None, keyboard=False):
        card = page.get_by_test_id('assistant-search-trips-' + trip_id)
        expect(card).to_be_visible()
        target = button(page, '查看旅行 ' + title)
        reads = self.count_requests('GET', '/api/journeys/' + journey_id) if journey_id else 0
        if keyboard:
            target.focus(); target.press('Enter')
        else:
            target.click()
        expect(page.get_by_role('heading', name='旅行详情', exact=True)).to_be_visible(timeout=15000)
        expect(page.get_by_role('heading', name=title, exact=True)).to_be_visible()
        expect(self.edit_button(page)).to_have_count(1)
        expect(self.edit_button(page)).to_be_enabled()
        expect(button(page, '返回助理')).to_be_visible()
        expect(page.get_by_role('heading', name='计划旅行', exact=True)).to_have_count(0)
        if journey_id:
            assert self.count_requests('GET', '/api/journeys/' + journey_id) > reads
            assert self.count_requests('GET', '/api/journeys/' + trip_id) == 0

    def return_search(self, page, prompt, query, offset):
        before = len(self.requests)
        button(page, '返回助理').click()
        expect(self.input(page)).to_have_value(prompt, timeout=15000)
        expect(page.get_by_text('第 ' + str(offset // 20 + 1) + ' 页', exact=True)).to_be_visible(timeout=15000)
        recent = self.requests[before:]
        searches = [r for r in recent if r['method'] == 'GET' and r['path'] == '/api/assistant/search']
        assert searches and any(parse_qs(r['query']) == dict(q=[query], limit=['20'], offset=[str(offset)]) for r in searches)
        assert any(r['path'] == '/api/me' for r in recent) and any(r['path'] == '/api/assistant/brief' for r in recent)

    def prefix_routing(self, browser):
        with self.flow(browser) as (ctx, page):
            title = '合成冰岛旅行检索'
            self.seed_trip(ctx, title)
            self.open_assistant(page)
            before = self.protected()
            ai = page.get_by_role('checkbox', name='使用已配置的 AI 整理', exact=True)
            expect(ai).to_be_enabled(); ai.click(); expect(ai).to_be_checked()
            prompts = ['搜索 ' + title, '查找：' + title, '找一下' + title]
            for prompt in prompts:
                result = self.search(page, prompt, title)
                assert result['search']['query'] == title
                expect(page.get_by_text('本次只查找已有记录，不会发送给 AI。', exact=True)).to_be_visible()
                expect(ai).to_be_checked()
                assert self.protected() == before
            ai.click(); expect(ai).not_to_be_checked()
            self.input(page).fill('规划一次旅行')
            call = self.actual_post(page, '/api/assistant/journey-brief', lambda: button(page, '整理并预览').click())
            assert call['payload']['useModel'] is False and call['result']['mode'] == 'local'
            expect(page.get_by_test_id('journey-brief-form')).to_be_visible()
            assert self.protected() == before
            button(page, '返回助理').click(); expect(self.input(page)).to_be_enabled()
            self.input(page).fill('待办：明天确认旅行酒店')
            task = self.actual_post(page, '/api/assistant/plan', lambda: button(page, '整理并预览').click())['result']
            assert len(task['actions']) == 1 and task['actions'][0]['kind'] == 'tasks'
            assert task['actions'][0]['data']['title'] == '确认旅行酒店'
            expect(button(page, '确认保存 1 项')).to_be_enabled()
            assert self.protected(False) == {k: v for k, v in before.items() if k != 'assistant_plans'}
            assert self.count_requests('POST', '/api/assistant/plans/' + task['id'] + '/apply') == 0
            assert not self.report['providerAttempts']
            self.report['routing'] = dict(prompts=prompts, explicitSearchNoBusinessWrites=True,
                realTaskPlanPersistedButNotApplied=True, newJourneyBriefNotApplied=True, providerCalls=0)
            self.passed('Three search prefixes force local flags even with AI selected; genuine journey brief and task draft keep their original routes without applying')

    def details_and_return(self, browser):
        with self.flow(browser) as (ctx, page):
            rows = [self.seed_trip(ctx, '合成一版既有旅行', 1), self.seed_trip(ctx, '合成二版既有旅行', 2)]
            for i in range(21):
                self.basic_trip(ctx, '合成分页旅行 %02d' % i)
            before = self.protected()
            self.open_assistant(page)
            for detail in rows:
                title = detail['plan']['title']; prompt = '找一下：' + title
                result = self.search(page, prompt, title)
                assert any(m['kind'] == 'trips' and m['id'] == detail['tripId'] for m in result['matches'])
                self.open_match(page, title, detail['tripId'], detail['id'])
                expect(button(page, '旅行回顾')).to_be_visible()
                expect(button(page, '行程分段')).to_be_visible()
                self.return_search(page, prompt, title, 0)
                assert self.get(ctx, '/api/journeys/' + detail['id']) == detail
            query, prompt = '合成分页旅行', '搜索 合成分页旅行'
            self.search(page, prompt)
            button(page, '下一页').click()
            expect(page.get_by_text('第 2 页', exact=True)).to_be_visible()
            second = self.get(ctx, '/api/assistant/search?' + urlencode(dict(q=query, limit=20, offset=20)))
            assert second['total'] == 21 and len(second['matches']) == 1
            match = second['matches'][0]; assert match['kind'] == 'trips'
            self.open_match(page, match['title'], match['id'])
            self.return_search(page, prompt, query, 20)
            expect(button(page, '查看旅行 ' + match['title'])).to_be_visible()
            assert self.protected() == before
            self.report['detailTargets'] = [dict(journeyId=d['id'], tripId=d['tripId']) for d in rows]
            self.passed('Real v1/v2 matches open the original workflow by trip ID; legacy page-two match and original prompt/query/offset return through fresh reads without writes')

    def delete_and_failure(self, browser):
        with self.flow(browser) as (ctx, page):
            deleted = self.seed_trip(ctx, '合成查后删除旅行')
            other = self.seed_trip(ctx, '合成详情丢失旅行', 2)
            self.open_assistant(page)
            self.search(page, '搜索 合成查后删除旅行', '合成查后删除旅行')
            trip = next(t for t in self.get(ctx, '/api/state')['trips'] if t['id'] == deleted['tripId'])
            self.write(ctx, 'DELETE', '/api/items/trips/' + trip['id'], {'revision': trip['revision']})
            self.get(ctx, '/api/journeys/' + deleted['id'], 404)
            button(page, '查看旅行 合成查后删除旅行').click()
            expect(page.get_by_text('这趟旅行已被删除，请刷新', exact=True)).to_be_visible()
            expect(page.get_by_role('heading', name='旅行详情', exact=True)).to_have_count(0)
            expect(self.edit_button(page)).to_have_count(0)
            self.return_search(page, '搜索 合成查后删除旅行', '合成查后删除旅行', 0)
            expect(button(page, '查看旅行 合成查后删除旅行')).to_have_count(0)
            title = other['plan']['title']; prompt = '搜索 ' + title
            self.search(page, prompt, title)
            before = self.protected(); dropped = []
            url = self.base + '/api/journeys/' + other['id']
            def lose(route):
                response = route.fetch(max_redirects=0)
                assert response.status == 200 and response.json()['id'] == other['id']
                dropped.append(response.status); route.abort('failed')
            page.route(url, lose)
            try:
                button(page, '查看旅行 ' + title).click()
                self.settle(page, lambda: bool(dropped))
                expect(page.get_by_role('alert')).to_be_visible()
                expect(page.get_by_role('heading', name='旅行详情', exact=True)).to_have_count(0)
                expect(self.edit_button(page)).to_have_count(0)
            finally:
                page.unroute(url, lose)
            self.return_search(page, prompt, title, 0)
            self.open_match(page, title, other['tripId'], other['id'])
            assert self.protected() == before
            self.passed('Deletion after search cannot open stale detail; dropped real detail stays hidden until explicit return/search/open succeeds, without creating a replacement trip')

    @contextmanager
    def held_response(self, page, url):
        held = []
        def hold(route):
            response = route.fetch(max_redirects=0)
            assert response.status == 200 and 'set-cookie' not in response.headers
            held.append((route, response.status, response.headers, response.body()))
        page.route(url, hold)
        try:
            yield held
        finally:
            page.unroute(url, hold)
            for route, *_ in held:
                route.abort('failed')

    @staticmethod
    def release(held):
        assert len(held) == 1
        route, status, headers, raw = held.pop()
        route.fulfill(status=status, headers=headers, body=raw)

    def identity_late(self, browser):
        with self.flow(browser) as (ctx, page):
            detail = self.seed_trip(ctx, '合成身份变化前旅行')
            invitation = self.write(ctx, 'POST', '/api/spaces/invitations', {}, 201)['invitation']
            family = self.write(ctx, 'POST', '/api/spaces/redeem', dict(invitation=invitation,
                name='合成第二家庭', slug='assistant-trip-other', MEMBER1_PASSWORD='testing-password-one',
                MEMBER2_PASSWORD='testing-password-two'), 201)
            self.open_assistant(page)
            old = self.get(ctx, '/api/me')
            with self.held_response(page, self.base + '/api/assistant/plan') as held:
                self.input(page).fill('找一下 合成身份变化前旅行'); button(page, '整理并预览').click()
                self.settle(page, lambda: len(held) == 1)
                self.login(ctx, 1)  # Real same-owner replacement session; auth_version need not change.
                fresh = self.get(ctx, '/api/me')
                assert fresh['user'] == old['user'] and fresh['csrf'] != old['csrf']
                self.release(held)
                expect(page.get_by_role('alert')).to_contain_text('登录身份已变化')
                expect(button(page, '查看旅行 合成身份变化前旅行')).to_have_count(0)
            self.open_assistant(page)
            self.search(page, '查找 合成身份变化前旅行', '合成身份变化前旅行')
            # Conceal current result on hide/offline, then explicitly search afresh.
            for boundary in ('hidden', 'offline'):
                if boundary == 'hidden':
                    visibility(page, True)
                else:
                    ctx.set_offline(True)
                    page.evaluate("Object.defineProperty(navigator,'onLine',{configurable:true,get:()=>false});window.dispatchEvent(new Event('offline'))")
                expect(button(page, '查看旅行 合成身份变化前旅行')).to_have_count(0)
                if boundary == 'hidden':
                    visibility(page, False)
                else:
                    ctx.set_offline(False)
                    page.evaluate("Object.defineProperty(navigator,'onLine',{configurable:true,get:()=>true});window.dispatchEvent(new Event('online'))")
                expect(self.input(page)).to_be_enabled()
                self.search(page, '查找 合成身份变化前旅行', '合成身份变化前旅行')
            other = self.context(browser, None)
            try:
                assert other.request.get(self.base + family['entry']).status == 200
                self.login(other, 1)
                assert self.get(other, '/api/me')['user']['householdId'] != old['user']['householdId']
                with self.held_response(page, self.base + '/api/journeys/' + detail['id']) as held:
                    button(page, '查看旅行 合成身份变化前旅行').click()
                    self.settle(page, lambda: len(held) == 1)
                    checks_before = self.count_requests('GET', '/api/me')
                    ctx.clear_cookies(); ctx.add_cookies(other.cookies())
                    self.release(held)
                    self.settle(page, lambda: self.count_requests('GET', '/api/me') > checks_before)
                    # Wait for the identity-driven remount, not an immediate
                    # absence assertion while the original read is still held.
                    expect(self.input(page)).to_be_enabled(timeout=15000)
                    expect(page.get_by_role('heading', name='合成身份变化前旅行', exact=True)).to_have_count(0)
                    expect(self.edit_button(page)).to_have_count(0)
                    result = self.search(page, '搜索 合成身份变化前旅行')
                    assert result['search']['total'] == 0
                    expect(button(page, '查看旅行 合成身份变化前旅行')).to_have_count(0)
            finally:
                other.close()
            self.passed('Real same-owner cookie replacement rejects a delayed search; household replacement rejects delayed detail; hide/offline conceal results and fresh second-family search has no first-family match')

    def unknown_save(self, browser):
        with self.flow(browser) as (ctx, page):
            detail = self.seed_trip(ctx, '合成原旅行待核对')
            self.open_assistant(page); self.search(page, '搜索 合成原旅行待核对', '合成原旅行待核对')
            self.open_match(page, '合成原旅行待核对', detail['tripId'], detail['id'])
            self.edit_button(page).click()
            page.get_by_role('textbox', name='旅行名称', exact=True).fill('合成已提交待核对旅行')
            self.actual_post(page, '/api/journeys/preview', lambda: button(page, '预览变更').click())
            expect(button(page, '确认保存旅行')).to_be_enabled()
            call = self.actual_post(page, '/api/journeys/apply', lambda: button(page, '确认保存旅行').click(), drop=True)
            assert call['result']['id'] == detail['id'] and call['result']['tripId'] == detail['tripId']
            expect(button(page, '核对原保存')).to_be_enabled()
            expect(button(page, '取消编辑')).to_be_disabled()
            expect(button(page, '返回助理')).to_have_count(0)
            expect(self.input(page)).to_have_count(0)
            assert self.count_requests('POST', '/api/journeys/apply') == 1
            committed = self.get(ctx, '/api/journeys/' + detail['id'])
            assert committed['plan']['title'] == '合成已提交待核对旅行'
            replay = self.actual_post(page, '/api/journeys/apply', lambda: button(page, '核对原保存').click())
            assert replay['payload'] == call['payload'] and replay['result']['replayed'] is True
            assert replay['result']['tripId'] == detail['tripId']
            expect(button(page, '返回助理')).to_be_visible()
            assert self.count_requests('POST', '/api/journeys/apply') == 2
            assert self.get(ctx, '/api/journeys/' + detail['id']) == committed
            self.report['unknownSave'] = dict(actualCommit=True, automaticRetry=False, exactOriginalPayloadReplay=True,
                originalTripId=detail['tripId'], newSearchEntryUnavailableUntilResolved=True)
            self.passed('Lost actual save response keeps original trip/payload locked; the new search entry and return cannot bypass unknown state, and explicit original replay does not duplicate')

    def capture(self, page, mode, width, target):
        page.set_viewport_size({'width': width, 'height': 1000 if width >= 1280 else 844})
        page.evaluate('() => document.fonts.ready'); target.scroll_into_view_if_needed()
        page.evaluate('() => new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
        metrics = page.evaluate('''() => ({width:innerWidth,scroll:document.documentElement.scrollWidth,
          clipped:[...document.querySelectorAll('[data-testid^="assistant-search-trips-"] [role="button"]')]
          .filter(n=>{const b=n.getBoundingClientRect();return b.width>0&&b.height>0&&b.bottom>0&&b.top<innerHeight&&(b.left < -2||b.right>innerWidth+2)})
          .map(n=>({label:n.getAttribute('aria-label'),box:n.getBoundingClientRect().toJSON()}))})''')
        box = target.bounding_box()
        assert metrics['scroll'] <= width + 2 and not metrics['clipped'], metrics
        assert box and box['height'] >= 44 and box['width'] >= 44, box
        path = self.out / f'assistant-search-{mode}-{width}.png'
        page.screenshot(path=str(path), full_page=False)
        self.report['screenshots'].append(dict(path=path.relative_to(self.out.parent).as_posix(), sha256=sha(path),
            theme=mode, metrics=metrics, target=box, scope='Visible viewport after scrolling to the real result action; not whole-page or physical-device acceptance.'))

    def layout(self, browser):
        with self.flow(browser) as (ctx, page):
            title = '合成长标题旅行：从东京到京都再返回，逐项核对日期与准备清单的既有旅行记录'
            detail = self.seed_trip(ctx, title, 2)
            before = self.protected()
            for mode in ('light', 'dark'):
                preferences = self.get(ctx, '/api/preferences')
                self.write(ctx, 'PUT', '/api/preferences', dict(revision=preferences['revision'], changes={'colorMode': mode}))
                self.open_assistant(page); self.search(page, '搜索 合成长标题旅行', title)
                page.wait_for_function("getComputedStyle(document.documentElement).colorScheme === '" + mode + "'")
                for width in (320, 1280):
                    self.capture(page, mode, width, button(page, '查看旅行 ' + title))
                self.open_match(page, title, detail['tripId'], detail['id'], keyboard=True)
                self.return_search(page, '搜索 合成长标题旅行', '合成长标题旅行', 0)
            assert self.protected() == before
            self.passed('Mobile/desktop in both themes: four real viewport images, long trip title, 44px result action and keyboard Enter detail/return, without business writes')

    @classmethod
    def run_scenarios(cls, root, bundle, report, out, browser):
        for name in CASES:
            case_out = out / name; case_out.mkdir()
            folder = None
            before = tuple(len(report[k]) for k in ('checks', 'pageErrors', 'externalRequests', 'providerAttempts'))
            case = dict(name=name, passed=False, temporaryFixtureRemoved=False)
            try:
                with ExitStack() as lifecycle:
                    folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='expo-assistant-trip-search-')))
                    run = cls(root, bundle, folder, report, case_out, lifecycle)
                    getattr(run, name)(browser)
                assert not folder.exists()
                assert tuple(len(report[k]) for k in ('checks', 'pageErrors', 'externalRequests', 'providerAttempts')) == (before[0] + 1, *before[1:])
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
    tree = git('rev-parse', 'HEAD^{tree}')
    evidence_path = bundle.parent / 'build-evidence.json'
    assert sha(evidence_path) == args.expected_build_evidence
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    assert evidence['sourceHead'] == head and evidence['sourceTree'] == tree
    names = subprocess.check_output(['git', '--no-replace-objects', 'ls-files', '-z'], cwd=root).decode('utf-8').rstrip('\0').split('\0')
    def hashes():
        return {name: sha(root / name) for name in names}
    def exports():
        return {p.relative_to(bundle).as_posix(): sha(p) for p in bundle.rglob('*') if p.is_file()}
    assert exports() == evidence['files'] and all(sha(root / name) == value for name, value in evidence['inputFiles'].items())
    assert sha(Path(__file__)) == sha(root / HARNESS)
    out = Path(__file__).resolve().parents[1] / 'test-results' / ('expo-assistant-trip-search-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], providerAttempts=[], screenshots=[], scenarioResults=[], scenarioFailures=[],
        requestedChecks=len(CASES), fullSuite=True, head=head, tree=tree, buildSourceHead=evidence['sourceHead'],
        buildSourceTree=evidence['sourceTree'], buildInputsEqual=True, buildEvidenceSha256=sha(evidence_path),
        harnessSha256=sha(out / 'executed-harness.py'), sourceRoot=str(root), bundleRoot=str(bundle),
        harnessHead=subprocess.check_output(['git', '--no-replace-objects', 'rev-parse', 'HEAD'], cwd=Path(__file__).resolve().parents[1], text=True).strip(),
        sourceHashesBefore=hashes(), bundleHashesBefore=exports(), productionWrites=0, realCloud=False, physicalTelevision=False,
        scope='Six independent temporary Flask/SQLite/HTTPS/Edge assistant-trip-search scenarios. Synthetic households/trips only, no provider, production or physical-device acceptance.')
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
                assert len(report['checks']) == len(CASES) and len(report['screenshots']) == 4
                assert not report['pageErrors'] and not report['externalRequests'] and not report['providerAttempts']
                report['passed'] = True
            finally:
                browser.close()
    except Exception:
        report['passed'] = False; report['failure'] = traceback.format_exc()
        print(report['failure'], flush=True)
    finally:
        report['sourceHashesAfter'], report['bundleHashesAfter'] = hashes(), exports()
        report['sourceUnchanged'] = report['sourceHashesBefore'] == report['sourceHashesAfter']
        report['bundleUnchanged'] = report['bundleHashesBefore'] == report['bundleHashesAfter']
        report['fixtureHashesAfter'] = {name: sha(Path(path)) for name, path in report.get('fixtureActualPaths', {}).items()}
        report['fixturesUnchanged'] = bool(report.get('fixtureHashes')) and report['fixtureHashesAfter'] == report['fixtureHashes']
        report['sourceStillFrozen'] = git('rev-parse', 'HEAD') == head and git('rev-parse', 'HEAD^{tree}') == tree and not git('status', '--porcelain=v1')
        report['temporaryFixtureRemoved'] = len(report['scenarioResults']) == len(CASES) and all(c['temporaryFixtureRemoved'] for c in report['scenarioResults'])
        report['passed'] = report['passed'] and report['sourceUnchanged'] and report['bundleUnchanged'] and report['fixturesUnchanged'] and report['sourceStillFrozen'] and report['temporaryFixtureRemoved']
        (out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(dict(passed=report['passed'], checks=len(report['checks']), report=str(out / 'result.json')), ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    raise SystemExit(main())
