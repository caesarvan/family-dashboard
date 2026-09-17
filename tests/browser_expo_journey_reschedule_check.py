"""Explicit rescheduling in real local Flask/SQLite/Edge; fake calendar HTTP only.

Requires a frozen source checkout and its exact Expo build evidence. This suite
inherits the server/auth/viewport fixtures, never runs the old 20 scenarios, and
does not access production, real calendars, real AI or physical televisions.
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
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright
import browser_expo_trip_coordination_check as coordination_fixture
from browser_expo_trip_coordination_check import Run as CoordinationRun, CP, PLACE
from browser_expo_journey_brief_check import button, textfield, sha


APPLY = '/api/journeys/apply'
OPERATIONS = '/api/journeys/operations/'


class Run(CoordinationRun):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for module_path, name in ((Path(coordination_fixture.__file__), 'tests/browser_expo_trip_coordination_check.py'),
                                  (Path(__file__), 'tests/browser_expo_journey_reschedule_check.py')):
            assert sha(module_path) == sha(self.root / name)
            self.report['fixtureHashes'][name] = sha(module_path)

    def snapshot(self):
        value = super().snapshot()
        with closing(sqlite3.connect(self.database)) as con:
            value['audit'] = sorted(con.execute('SELECT * FROM audit').fetchall(), key=repr)
        return value

    def seed(self, ctx):
        plan = {'title': '合成明确改期旅行', 'start': '2028-03-02', 'end': '2028-03-04',
            'budget': 123450, 'paid': 10000, 'saved': 20000, 'international': True,
            'memberIds': ['member1', 'member2'],
            'destinations': [{'key': 'tokyo', 'country': '日本', 'city': '东京', 'arrival': '2028-03-02', 'departure': '2028-03-04'}],
            'checklist': [{'key': 'pack', 'title': '合成待准备', 'owner': 'member1', 'due': '2028-03-01', 'note': '独立备注'},
                          {'key': 'done', 'title': '合成已完成', 'owner': 'member2', 'due': '2028-02-28'},
                          {'key': 'manual', 'title': '合成手工日期', 'owner': 'shared', 'due': '2028-02-29'}],
            'shopping': [{'key': 'purchase', 'title': '合成采购金额', 'quantity': '2 件', 'owner': 'member2', 'budget': None}],
            'segments': []}
        d = self.api_apply(ctx, plan)
        done = next(t for t in d['tasks'] if t['workflowKey'] == 'task:done')
        self.write(ctx, 'PATCH', '/api/items/tasks/' + done['id'], {'revision': done['revision'], 'done': True})
        manual = next(t for t in d['tasks'] if t['workflowKey'] == 'task:manual')
        self.write(ctx, 'PATCH', '/api/items/tasks/' + manual['id'], {'revision': manual['revision'], 'due': '2028-02-20'})
        place = self.write(ctx, 'POST', PLACE, {'requestId': uuid4().hex, 'name': '合成私人计划地点',
            'journeyId': d['id'], 'status': 'planned', 'startDate': '2028-03-02', 'endDate': '2028-03-04',
            'coordinates': {'latitude': 35.68, 'longitude': 139.76}}, 201)['place']
        visited = self.write(ctx, 'POST', PLACE, {'requestId': uuid4().hex, 'name': '合成到访历史',
            'journeyId': d['id'], 'status': 'visited', 'confirmVisited': True,
            'startDate': '2027-03-02', 'endDate': '2027-03-04'}, 201)['place']
        payload = {'journeyId': d['id'], 'sourceId': 'source-mine'}
        p = self.write(ctx, 'POST', CP + '/preview', payload)
        receipt = self.write(ctx, 'POST', CP + '/confirm', {**payload, 'previewToken': p['previewToken']})
        assert len(receipt['publicationIds']) == 1
        rid = receipt['publicationIds'][0]
        self.application.extensions['calendar_publish'].process(rid)
        assert self.publication(rid)['status'] == 'published' and self.remote.created == 1
        return self.detail(ctx, d['id']), place, visited, rid

    def open_panel(self, page, journey):
        self.show_saved(page, journey['tripId'])
        before, calls = self.snapshot(), len(self.remote.calls)
        with page.expect_response(lambda r: urlsplit(r.url).path == '/api/journeys/' + journey['id'] + '/reschedule'
                                  and r.request.method == 'GET') as pending:
            button(page, '调整日期').click()
        response = pending.value
        assert response.status == 200, response.text()
        expect(page.get_by_role('heading', name='调整旅行日期', exact=True)).to_be_visible()
        expect(textfield(page, '新的出发日期')).to_be_enabled()
        assert self.snapshot() == before and len(self.remote.calls) == calls
        return response.json()

    @staticmethod
    def dates(page, start, end):
        textfield(page, '新的出发日期').fill(start)
        textfield(page, '新的返程日期').fill(end)

    @staticmethod
    def choose(page, title):
        checkbox = page.get_by_role('checkbox', name='联动改期：' + title, exact=True)
        expect(checkbox).not_to_be_checked()
        checkbox.click()
        expect(checkbox).to_be_checked()

    def preview_reschedule(self, page, journey, can_apply=True):
        before, calls = self.snapshot(), len(self.remote.calls)
        with page.expect_response(lambda r: urlsplit(r.url).path == '/api/journeys/' + journey['id'] + '/reschedule-preview'
                                  and r.request.method == 'POST') as pending:
            button(page, '预览改期').click()
        response = pending.value
        assert response.status == 200, response.text()
        result = response.json()
        assert result['canApply'] is can_apply
        assert self.snapshot() == before and len(self.remote.calls) == calls
        if can_apply:
            expect(page.get_by_test_id('journey-reschedule-preview')).to_be_visible()
            expect(button(page, '确认改期')).to_be_enabled()
        return result

    def shots_settled(self, page, label):
        if self.provider == 'microsoft':
            for width in (320, 390, 1040, 1440):
                page.set_viewport_size({'width': width, 'height': 1000 if width >= 1040 else 844})
                page.wait_for_timeout(400)  # Paper labels/layout animation must settle before the screenshot.
                self.screenshot(page, label, width)
            page.set_viewport_size({'width': 390, 'height': 844})

    def selected_preview_and_confirmation(self, page, d, place, visited, rid):
        ctx = page.context
        current = self.open_panel(page, d)
        assert all(not node.is_checked() for node in page.get_by_role('checkbox').all())
        self.dates(page, '2028-03-05', '2028-03-07')
        proposed = self.preview_reschedule(page, d)
        assert all(row['after'] == row['before'] for row in proposed['items'] if row['key'] != 'trip')
        button(page, '继续修改').click()
        self.choose(page, '合成待准备')
        self.choose(page, '合成私人计划地点')
        for title in ('合成已完成', '合成到访历史', '合成采购金额'):
            locked = page.get_by_role('checkbox', name='联动改期：' + title, exact=True)
            assert not locked.count() or not locked.is_enabled()
        self.shots_settled(page, 'reschedule-selection')
        proposed = self.preview_reschedule(page, d)
        selected = {r['key'] for r in proposed['items'] if r['selected'] and r['key'] != 'trip'}
        assert selected == {'task:pack', 'place:' + place['id']}
        self.shots_settled(page, 'reschedule-preview')
        self.passed(self.provider + ': default keeps optional dates; explicit selection and before/after preview are zero-write and protected rows cannot be selected')
        remote_id = self.publication(rid)['remote_id']
        calls = len(self.remote.calls)
        with page.expect_response(lambda r: urlsplit(r.url).path == APPLY and r.request.method == 'POST') as pending:
            button(page, '确认改期').click()
        response = pending.value
        assert response.status == 200 and response.json()['operation'] == 'reschedule', response.text()
        expect(button(page, '返回旅行详情')).to_be_enabled()
        changed = self.detail(ctx, d['id'])
        assert changed['revision'] == d['revision'] + 1 and changed['events'][0]['id'] == d['events'][0]['id']
        rows = {t['workflowKey']: t for t in changed['tasks']}
        assert rows['task:pack']['due'] == '2028-03-04'
        for key in ('task:done', 'task:manual'):
            assert rows[key] == next(t for t in d['tasks'] if t['workflowKey'] == key)
        assert changed['shopping'] == d['shopping'] and changed['budget'] == d['budget']
        assert self.get(ctx, PLACE + '/' + visited['id'])['place'] == visited
        shifted = self.get(ctx, PLACE + '/' + place['id'])['place']
        assert shifted['startDate'] == '2028-03-05' and shifted['endDate'] == '2028-03-07'
        assert shifted['coordinates'] == place['coordinates'] and shifted['visibility'] == 'private'
        assert len(self.remote.calls) == calls
        self.remote.lose_patch = True
        worker = self.application.extensions['calendar_publish']
        worker.process(rid)
        assert self.publication(rid)['status'] == 'retry' and self.remote.patched == 1
        worker.process(rid)
        assert self.publication(rid)['status'] == 'published' and self.publication(rid)['remote_id'] == remote_id
        assert self.remote.created == self.remote.patched == 1
        button(page, '返回旅行详情').click()
        expect(page.get_by_role('heading', name='旅行详情', exact=True)).to_be_visible()
        self.passed(self.provider + ': explicit confirmation updates selected dates and stable local/remote IDs once; completed/history/manual/amount fields remain unchanged')

    def unknown_recovery(self, page, d, *, committed):
        current = self.detail(page.context, d['id'])
        self.open_panel(page, current)
        self.dates(page, '2028-03-08' if committed else '2028-03-11', '2028-03-10' if committed else '2028-03-13')
        self.choose(page, '合成待准备')
        self.preview_reschedule(page, current)
        attempts, replies = [], []
        before = self.snapshot()
        def lose(route):
            attempts.append(route.request.post_data_json)
            if committed:
                reply = route.fetch(max_redirects=0)
                assert reply.status == 200, reply.text()
                replies.append(reply.json())
            route.abort('failed')
        page.route(self.base + APPLY, lose)
        button(page, '确认改期').click()
        expect(page.get_by_test_id('journey-reschedule-unknown')).to_be_visible()
        expect(button(page, '核对保存结果')).to_be_enabled()
        page.unroute(self.base + APPLY, lose)
        assert len(attempts) == 1
        operation = attempts[0]['idempotencyKey']
        saved = self.snapshot()
        if not committed:
            assert saved == before
        # Both app navigation paths must keep the pending intent mounted. The
        # operation GET / identical retry below proves its original key/token.
        original_url, request_start = page.url, len(self.requests)
        page.set_viewport_size({'width': 390, 'height': 844})
        page.get_by_role('tab', name='首页', exact=True).click()
        expect(page.get_by_test_id('journey-reschedule-unknown')).to_be_visible()
        assert page.url == original_url
        button(page, '新建记录').click()
        page.get_by_role('menuitem', name=re.compile(r'(?:^|\s)计划旅行$')).click()
        expect(page.get_by_test_id('journey-reschedule-unknown')).to_be_visible()
        expect(page.get_by_role('heading', name='调整旅行日期', exact=True)).to_be_visible()
        expect(textfield(page, '新的出发日期')).to_have_value('2028-03-08' if committed else '2028-03-11')
        expect(textfield(page, '新的出发日期')).to_be_disabled()
        expect(button(page, '核对保存结果')).to_be_enabled()
        assert page.url == original_url and self.snapshot() == saved
        assert not [r for r in self.requests[request_start:] if r['method'] == 'POST']
        expect(page.get_by_text('请先核对这次改期的保存结果，再离开旅行页面。', exact=True)).to_be_visible()
        button(page, '知道了').click()
        with page.expect_response(lambda r: urlsplit(r.url).path == OPERATIONS + operation and r.request.method == 'GET') as pending:
            button(page, '核对保存结果').click()
        response = pending.value
        assert response.status == (200 if committed else 404), response.text()
        assert self.snapshot() == saved, 'Unknown recovery must read, never resubmit'
        if committed:
            assert response.json()['result']['id'] == replies[0]['id']
            expect(button(page, '返回旅行详情')).to_be_enabled()
        else:
            assert response.json()['code'] == 'operation_not_found'
            expect(page.get_by_test_id('journey-reschedule-unknown')).to_be_visible()
            expect(button(page, '按原操作重试')).to_be_enabled()
            with page.expect_response(lambda r: urlsplit(r.url).path == APPLY and r.request.method == 'POST') as retry:
                button(page, '按原操作重试').click()
            assert retry.value.status == 200 and retry.value.request.post_data_json == attempts[0]
            expect(button(page, '返回旅行详情')).to_be_enabled()
        button(page, '返回旅行详情').click()
        expect(page.get_by_role('heading', name='旅行详情', exact=True)).to_be_visible()
        final = self.detail(page.context, d['id'])
        assert final['revision'] == current['revision'] + 1
        assert next(t for t in final['tasks'] if t['workflowKey'] == 'task:pack')['due'] == ('2028-03-07' if committed else '2028-03-10')
        page.get_by_role('tab', name='首页', exact=True).click()
        expect(page.get_by_role('heading', name=re.compile(r'，欢迎回家$'))).to_be_visible()
        expect(page.get_by_test_id('journey-reschedule-panel')).to_have_count(0)
        self.passed(self.provider + (': lost committed reply recovers by GET receipt only; no second shift'
            if committed else ': real absent receipt stays unknown; only explicit retry sends identical original token/key once')
            + '; app home/create navigation preserves pending intent and becomes available after receipt')

    def conflict(self, page, d, place):
        ctx = page.context
        current = self.detail(ctx, d['id'])
        self.open_panel(page, current)
        self.dates(page, '2028-03-14', '2028-03-16')
        self.choose(page, '合成待准备')
        self.choose(page, '合成私人计划地点')
        self.preview_reschedule(page, current)
        actual = self.get(ctx, PLACE + '/' + place['id'])['place']
        self.write(ctx, 'PATCH', PLACE + '/' + place['id'], {'revision': actual['revision'], 'name': '其他操作改过的地点'})
        before = self.snapshot()
        with page.expect_response(lambda r: urlsplit(r.url).path == APPLY and r.request.method == 'POST') as pending:
            button(page, '确认改期').click()
        assert pending.value.status == 409 and self.snapshot() == before
        expect(button(page, '读取最新并重新核对')).to_be_enabled()
        assert not button(page, '确认改期').count() or not button(page, '确认改期').is_enabled()
        self.shots_settled(page, 'reschedule-conflict')
        button(page, '读取最新并重新核对').click()
        expect(button(page, '已核对最新内容')).to_be_enabled()
        button(page, '已核对最新内容').click()
        expect(button(page, '预览改期')).to_be_enabled()
        assert self.snapshot() == before
        self.passed(self.provider + ': stale place revision rejects entire apply; explicit reread/review never silently retries or changes other records')

    def late_identity(self, browser, d):
        with self.flow(browser) as (ctx, page):
            private = self.write(ctx, 'POST', PLACE, {'requestId': uuid4().hex, 'name': 'LATE-PRIVATE-RESCHEDULE',
                'journeyId': d['id'], 'status': 'planned', 'startDate': '2028-03-11', 'endDate': '2028-03-13'}, 201)['place']
            self.open_panel(page, self.detail(ctx, d['id']))
            self.dates(page, '2028-03-14', '2028-03-16')
            self.choose(page, 'LATE-PRIVATE-RESCHEDULE')
            endpoint = self.base + '/api/journeys/' + d['id'] + '/reschedule-preview'
            held = []
            def delay(route):
                reply = route.fetch(max_redirects=0)
                assert reply.status == 200 and 'set-cookie' not in reply.headers
                held.append((route, reply))
            before = self.snapshot()
            page.route(endpoint, delay)
            button(page, '预览改期').click()
            self.settle(page, lambda: bool(held))
            self.login(ctx, 2)
            assert self.get(ctx, '/api/me')['user']['id'] == 'member2'
            for route, reply in held:
                route.fulfill(response=reply)
            page.unroute(endpoint, delay)
            expect(page.get_by_role('checkbox', name='联动改期：LATE-PRIVATE-RESCHEDULE', exact=True)).to_have_count(0)
            expect(page.locator('body')).not_to_contain_text('LATE-PRIVATE-RESCHEDULE')
            assert self.snapshot() == before
            self.get(ctx, PLACE + '/' + private['id'], 404)
            self.passed(self.provider + ': late real old-member preview is discarded and private place concealed after actual cookie identity change')

    def dst_correction(self, browser, *, fold):
        old, new = ('2026-10-24', '2026-10-25') if fold else ('2026-03-28', '2026-03-29')
        with self.flow(browser) as (ctx, page):
            d = self.api_apply(ctx, {'title': '合成时区改期', 'schemaVersion': 2, 'referenceTimezone': 'Europe/Berlin',
                'start': old, 'end': old, 'international': True, 'memberIds': ['member1'], 'budget': 0,
                'destinations': [{'key': 'berlin', 'country': '德国', 'city': '柏林', 'arrival': old,
                                  'departure': old, 'timeZone': 'Europe/Berlin'}], 'checklist': [], 'shopping': [],
                'segments': [{'key': 'walk', 'kind': 'activity', 'title': '合成夏令时活动',
                              'start': {'local': old + 'T02:30', 'timeZone': 'Europe/Berlin'},
                              'end': {'local': old + 'T04:00', 'timeZone': 'Europe/Berlin'}}]})
            self.open_panel(page, d)
            self.dates(page, new, new)
            self.choose(page, '合成夏令时活动')
            blocked = self.preview_reschedule(page, d, can_apply=False)
            code = 'ambiguous_local_time' if fold else 'nonexistent_local_time'
            issue = next(row for row in blocked['blockingIssues'] if row['code'] == code)
            assert issue['key'] == 'segment:walk' and blocked['previewToken'] is None
            assert not button(page, '确认改期').count() or not button(page, '确认改期').is_enabled()
            correction = textfield(page, '纠正当地开始时间：segment:walk')
            expect(correction).to_be_visible()
            offset = 120
            local = new + ('T02:30' if fold else 'T03:30')
            if fold:
                choice = next(row for row in issue['choices'] if row['offsetMinutes'] == 60)
                offset = choice['offsetMinutes']
                group = page.get_by_role('radiogroup', name='选择时区偏移：segment:walk:start', exact=True)
                radio = group.get_by_role('radio', name='UTC+01:00 · ' + choice['instant'], exact=True)
                expect(radio).not_to_be_checked()
                radio.click()
                expect(radio).to_be_checked()
            else:
                correction.fill(local)
            confirmed = self.preview_reschedule(page, d)
            row = next(item for item in confirmed['items'] if item['key'] == 'segment:walk')
            assert row['timeBefore']['start']['local'].startswith(old + 'T02:30')
            assert row['timeAfter']['start']['local'].startswith(local)
            assert row['timeAfter']['start']['offsetMinutes'] == offset
            visible = page.get_by_test_id('journey-reschedule-preview')
            expect(visible).to_contain_text(local.replace('T', ' '))
            expect(visible).to_contain_text('UTC+01:00' if fold else 'UTC+02:00')
            with page.expect_response(lambda r: urlsplit(r.url).path == APPLY and r.request.method == 'POST') as pending:
                button(page, '确认改期').click()
            response = pending.value
            assert response.status == 200 and 'segment:walk' in response.json()['reschedule']['changedKeys']
            expect(button(page, '返回旅行详情')).to_be_enabled()
            saved = self.detail(ctx, d['id'])
            original_event = next(e for e in d['events'] if e['workflowKey'] == 'segment:walk')
            event = next(e for e in saved['events'] if e['workflowKey'] == 'segment:walk')
            assert event['id'] == original_event['id'] and event['travelTiming']['startLocal'].startswith(local)
            button(page, '返回旅行详情').click()
            expect(page.get_by_role('heading', name='旅行详情', exact=True)).to_be_visible()
            self.passed('DST ' + ('fold' if fold else 'gap') + ': real backend blocks guessing; explicit local clock/offset is visibly previewed and saved to the same event')

    def home_visuals(self, browser):
        with self.flow(browser) as (ctx, page):
            finance = self.get(ctx, '/api/state')['finance']
            assert not finance.get('confirmedAt')
            page.goto(self.base + '/app/')
            expect(page.get_by_role('heading', name=re.compile(r'，欢迎回家$'))).to_be_visible()
            expect(button(page, '核对资金')).to_be_enabled()
            expect(page.get_by_text('共同资金尚未核对。请先确认余额、本月支出和预算。', exact=True)).to_have_count(1)
            expect(page.get_by_text('待核对', exact=True)).to_have_count(0)
            before = self.snapshot()
            for width in (320, 390, 1040, 1440):
                page.set_viewport_size({'width': width, 'height': 1000 if width >= 1040 else 844})
                page.get_by_role('heading', name=re.compile(r'，欢迎回家$')).click()
                page.wait_for_timeout(400)
                self.screenshot(page, 'home-unconfirmed', width)
                cards = {}
                for title in ('接下来的安排', '共同资金'):
                    cards[title] = page.get_by_role('heading', name=title, exact=True).evaluate('''node => {
                      for(let n=node;n;n=n.parentElement){const s=getComputedStyle(n);
                        if(s.backgroundColor==='rgb(248, 248, 250)'&&parseFloat(s.borderTopLeftRadius)>=24){
                          const r=n.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};}}
                      throw new Error('Expected visible SectionCard surface');}''')
                if width >= 1040:
                    assert abs(cards['接下来的安排']['y'] - cards['共同资金']['y']) < 2, cards
                    assert abs(cards['接下来的安排']['height'] - cards['共同资金']['height']) > 2, cards
                assert cards['共同资金']['height'] < 300, cards
                self.report.setdefault('homeCardBounds', []).append({'width': width, 'cards': cards})
                if width in (390, 1440):
                    account = page.get_by_role('button', name=re.compile(r'，账户菜单$'))
                    account.focus()
                    page.keyboard.press('Shift+Tab')
                    page.keyboard.press('Tab')
                    expect(account).to_be_focused()
                    focus = account.evaluate('''node => {
                      const s=getComputedStyle(node),r=node.getBoundingClientRect();
                      return {active:document.activeElement===node,focusVisible:node.matches(':focus-visible'),
                        outlineStyle:s.outlineStyle,outlineWidth:s.outlineWidth,outlineColor:s.outlineColor,
                        outlineOffset:s.outlineOffset,borderRadius:s.borderRadius,boxShadow:s.boxShadow,
                        x:r.x,y:r.y,width:r.width,height:r.height};}''')
                    assert focus['active'] and focus['focusVisible'], focus
                    assert focus['outlineStyle'] != 'none' and float(focus['outlineWidth'].removesuffix('px')) > 0, focus
                    assert focus['outlineOffset'] == '-3px' and float(focus['borderRadius'].removesuffix('px')) >= focus['width'] / 2, focus
                    self.report.setdefault('homeFocus', []).append({'viewport': width, **focus})
                    self.screenshot(page, 'home-keyboard-focus', width)
            button(page, '核对资金').click()
            expect(page.get_by_role('heading', name='家庭资金', exact=True)).to_be_visible()
            expect(button(page, '核对资金')).to_be_enabled()
            assert self.get(ctx, '/api/state')['finance'] == finance and self.snapshot() == before
            self.passed('Home: one unconfirmed shared-finance message opens real finance; four widths use natural card heights; keyboard account focus remains visible within rounded bounds')

    def nested_map_recovery(self, browser):
        with self.flow(browser) as (ctx, page):
            d = self.api_apply(ctx, {'title': '合成地图嵌套改期', 'start': '2028-05-03', 'end': '2028-05-06',
                'budget': 0, 'memberIds': ['member1'], 'international': False,
                'destinations': [{'key': 'map-city', 'country': '中国', 'city': '上海',
                                  'arrival': '2028-05-03', 'departure': '2028-05-06'}],
                'checklist': [{'key': 'pack', 'title': '合成地图准备', 'owner': 'member1', 'due': '2028-05-01'}],
                'shopping': [], 'segments': []})
            self.write(ctx, 'POST', PLACE, {'requestId': uuid4().hex, 'name': 'MAP-PENDING-RESCHEDULE',
                'journeyId': d['id'], 'status': 'planned', 'startDate': '2028-05-03', 'endDate': '2028-05-06',
                'coordinates': {'latitude': 31.23, 'longitude': 121.47}}, 201)
            page.goto(self.base + '/app/map')
            expect(page.get_by_role('heading', name='足迹地图', exact=True)).to_be_visible()
            button(page, '打开地点：MAP-PENDING-RESCHEDULE').click()
            expect(button(page, '查看旅行')).to_be_enabled()
            button(page, '查看旅行').click()
            expect(page.get_by_role('heading', name='旅行详情', exact=True)).to_be_visible()
            expect(button(page, '返回足迹地图')).to_be_enabled()
            button(page, '调整日期').click()
            expect(textfield(page, '新的出发日期')).to_be_enabled()
            self.dates(page, '2028-05-06', '2028-05-09')
            self.choose(page, '合成地图准备')
            self.preview_reschedule(page, d)
            attempts = []
            def lose(route):
                attempts.append(route.request.post_data_json)
                response = route.fetch(max_redirects=0)
                assert response.status == 200 and response.json()['id'] == d['id']
                route.abort('failed')
            page.route(self.base + APPLY, lose)
            button(page, '确认改期').click()
            expect(page.get_by_test_id('journey-reschedule-unknown')).to_be_visible()
            expect(button(page, '核对保存结果')).to_be_enabled()
            page.unroute(self.base + APPLY, lose)
            assert len(attempts) == 1
            original_url, before, request_start = page.url, self.snapshot(), len(self.requests)
            page.get_by_role('tab', name='首页', exact=True).click()
            expect(page.get_by_test_id('journey-reschedule-unknown')).to_be_visible()
            expect(textfield(page, '新的出发日期')).to_have_value('2028-05-06')
            assert page.url == original_url and urlsplit(page.url).path == '/app/map'
            expect(page.get_by_text('请先核对这次改期的保存结果，再离开旅行页面。', exact=True)).to_be_visible()
            button(page, '知道了').click()
            with page.expect_response(lambda r: urlsplit(r.url).path == OPERATIONS + attempts[0]['idempotencyKey']
                                      and r.request.method == 'GET') as pending:
                button(page, '核对保存结果').click()
            assert pending.value.status == 200 and pending.value.json()['result']['id'] == d['id']
            expect(button(page, '返回旅行详情')).to_be_enabled()
            assert self.snapshot() == before
            assert not [r for r in self.requests[request_start:] if r['method'] == 'POST']
            saved = self.detail(ctx, d['id'])
            assert saved['revision'] == d['revision'] + 1 and saved['tasks'][0]['id'] == d['tasks'][0]['id']
            assert saved['tasks'][0]['due'] == '2028-05-04'
            button(page, '返回旅行详情').click()
            expect(button(page, '返回足迹地图')).to_be_enabled()
            button(page, '返回足迹地图').click()
            expect(page.get_by_role('heading', name='足迹地图', exact=True)).to_be_visible()
            page.get_by_role('tab', name='首页', exact=True).click()
            expect(page.get_by_role('heading', name=re.compile(r'，欢迎回家$'))).to_be_visible()
            self.passed('Map nested trip: lost committed reschedule reply retains original operation across home navigation, recovers by receipt GET and returns through map without another shift; assistant nesting is not exercised')

    def run_scenarios(self, browser):
        with self.flow(browser) as (ctx, page):
            d, place, visited, rid = self.seed(ctx)
            self.selected_preview_and_confirmation(page, d, place, visited, rid)
            self.unknown_recovery(page, d, committed=True)
            self.unknown_recovery(page, d, committed=False)
            self.conflict(page, d, place)
        self.late_identity(browser, d)
        if self.provider == 'microsoft':
            self.dst_correction(browser, fold=False)
            self.dst_correction(browser, fold=True)
            self.nested_map_recovery(browser)
            self.home_visuals(browser)


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
    out = Path(__file__).resolve().parents[1] / 'test-results' / ('expo-journey-reschedule-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], screenshots=[],
        head=head, tree=evidence['sourceTree'], buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(out / 'executed-harness.py'),
        sourceHashesBefore=hashes(), bundleHashesBefore=bundle_hashes(), productionWrites=0,
        realCloud=False, realAI=False, physicalTelevision=False, providers=[],
        scope='Actual local Flask/SQLite/Edge and real reschedule routes. Calendar provider HTTP alone is fake. Apply reply or request loss is injected explicitly. Screenshots cover settled visible inner scroll positions only. DST gap/fold correction runs once through real UI and API; transaction races and booked v2 protection are separate backend tests, not browser claims.')
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
                for provider in ('microsoft', 'google'):
                    with ExitStack() as lifecycle:
                        folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='expo-journey-reschedule-')))
                        run = Run(root, bundle, folder, report, out, lifecycle, provider=provider)
                        run.run_scenarios(browser)
                        report['providers'].append({'provider': provider, 'passed': True,
                            'syntheticRemoteCreated': run.remote.created, 'syntheticRemotePatched': run.remote.patched})
                assert not report['pageErrors'] and not report['externalRequests']
                report['passed'] = True
            finally:
                browser.close()
    except Exception:
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
