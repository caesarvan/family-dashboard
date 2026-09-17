"""Two local scenario-A seams using real Expo, Flask, SQLite and synthetic JSON.

Calendar connections are synthetic; provider calls are forbidden, no worker runs,
and the calendar UI stops at preview. Review and freeze this source before use.
"""
import argparse
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import traceback
from unittest.mock import patch
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright
import browser_expo_trip_import_check as import_fixture
from browser_expo_trip_import_check import Run as ImportRun, APPLY, PREVIEW
from browser_expo_finance_check import button, sha

CHECKS = 2
SCENARIOS = ('same_trip_chain', 'completed_write_lost_readback')
TITLE = '合成本地整链旅行'
PLACE_TITLE = '合成东京私人计划地点'
ACTIVITY_TITLE = '合成东京日期级活动'
TASK_TITLES = ('合成核对证件', '合成整理行李')
SHOP_TITLES = ('合成已有转换插头', '合成待估价收纳袋')
CP = '/api/calendar-publish'
PLACE = '/api/journey-places'


def icon_button(page, name):
    # Paper icons may be included in the accessible name; still require one role.
    return page.get_by_role('button', name=re.compile(r'(?:^|\s)' + re.escape(name) + r'$'))


def textfield(page, name):
    return page.get_by_role('textbox', name=name, exact=True)


def entity_ids(detail):
    return {'journeyId': detail['id'], 'tripId': detail['tripId'],
            **{kind: {row['workflowKey']: row['id'] for row in detail[kind]}
               for kind in ('tasks', 'shopping', 'events')}}


class Run(ImportRun):
    def __init__(self, *args, **kwargs):
        self.provider_calls = []
        super().__init__(*args, **kwargs)
        own_relative = 'tests/browser_expo_travel_chain_check.py'
        own_digest = sha(Path(__file__))
        assert own_digest == self.report['harnessSha256']
        assert self.report['fixtureHashes'].get(own_relative, own_digest) == own_digest
        self.report['fixtureHashes'][own_relative] = own_digest
        actual_fixtures = {name: str(self.root / name) for name in self.report['fixtureHashes']}
        actual_fixtures['tests/browser_expo_travel_chain_check.py'] = str(Path(__file__).resolve())
        for module in ('browser_expo_trip_import_check', 'browser_expo_finance_check', 'test_financial_files', 'test_app'):
            actual_fixtures['tests/' + module + '.py'] = str(Path(sys.modules[module].__file__).resolve())
        assert self.report.setdefault('fixtureActualPaths', actual_fixtures) == actual_fixtures
        self.report['fixtureOrigins'] = {name: dict(path=path, sha256=self.report['fixtureHashes'][name],
            binding='independent_harness' if name == own_relative else 'actual_file_matches_frozen_application')
            for name, path in actual_fixtures.items()}
        self.seed_calendar_sources()

    def start(self, port=0):
        self.cfg.update(CLOUD_TRANSPORT=self.deny_provider,
            MICROSOFT_CLIENT_ID='synthetic-travel-chain', MICROSOFT_CLIENT_SECRET='synthetic-only')
        super().start(port)

    def deny_provider(self, *_args, **_kwargs):
        self.provider_calls.append('forbidden provider call')
        raise AssertionError('This local chain authorizes calendar preview only')

    def seed_calendar_sources(self):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        engine = self.application.extensions['cloud_accounts']
        with engine.db() as con:
            for suffix, owner, name in [('mine', 'member1', '本人合成旅行日历'),
                    ('partner', 'member2', 'PARTNER_CALENDAR_PRIVATE')]:
                token = engine.encrypt({'access_token': 'synthetic-token', 'refresh_token': 'synthetic-refresh',
                    'scope': 'User.Read Calendars.ReadWrite', 'expires_at': time.time() + 3600})
                con.execute('INSERT INTO cloud_accounts(id,owner,provider,client_id,subject,name,email,tokens) VALUES(?,?,?,?,?,?,?,?)',
                    ('chain-account-' + suffix, owner, 'microsoft', self.cfg['MICROSOFT_CLIENT_ID'],
                     'synthetic-' + suffix, '合成账户' if suffix == 'mine' else 'PARTNER_ACCOUNT_PRIVATE',
                     suffix + '@synthetic.invalid', token))
                con.execute('INSERT INTO cloud_sources(id,account_id,remote_id,kind,name,owner) VALUES(?,?,?,?,?,?)',
                    ('chain-source-' + suffix, 'chain-account-' + suffix, 'synthetic-calendar-' + suffix,
                     'calendar', name, owner))

    def synthetic_plan(self):
        plan = self.plan(2, TITLE)
        plan.update(start='2027-10-01', end='2027-10-03', referenceTimezone='Asia/Tokyo')
        plan['destinations'] = [dict(plan['destinations'][0], departure='2027-10-03')]
        activity = deepcopy(plan['segments'][2])
        activity.update(key='tokyo-day', destinationKey='tokyo', title=ACTIVITY_TITLE, location='东京',
                        dateRange={'startDate': '2027-10-02', 'endDateExclusive': '2027-10-03'})
        plan['segments'] = [activity]
        plan['checklist'] = plan['checklist'][:2]
        for row, title, due in zip(plan['checklist'], TASK_TITLES, ('2027-09-30', '2027-09-29')):
            row.pop('dueOffsetDays', None)
            row.update(title=title, owner='shared', due=due)
        for row, title in zip(plan['shopping'], SHOP_TITLES):
            row.update(title=title, owner='shared')
        return plan

    def detail(self, ctx, journey_id):
        return self.get(ctx, '/api/journeys/' + journey_id)

    def proof(self, step, detail, **extra):
        self.report.setdefault('chainEvidence', []).append(dict(scenario=self.out.name, step=step,
            ids=entity_ids(detail), revision=detail['revision'], progress=detail['progress'], **extra))

    def no_cloud(self):
        assert not self.provider_calls
        assert self.count_requests('POST', CP + '/confirm') == 0
        assert not any(row['method'] != 'GET' and row['path'].startswith(CP + '/')
                       and row['path'] != CP + '/preview' for row in self.requests)
        state = self.snapshot()
        assert not state['calendar_publications'] and not state['task_publications']

    def import_one(self, page):
        self.open_import(page)
        plan = self.synthetic_plan()
        self.choose_file(page, json.dumps({'plan': plan}, ensure_ascii=False).encode('utf-8'), '合成本地整链.json')
        preview, sent = self.preview(page)
        assert sent == plan
        packet = self.confirm(page)
        self.current_ready(page, TITLE)
        detail = self.persisted(page.context, packet, preview)
        assert len(detail['tasks']) == len(detail['shopping']) == len(detail['events']) == 2
        assert detail['plan']['schemaVersion'] == 2
        self.no_cloud(); self.proof('imported', detail)
        return detail

    def capture_mutation(self, page, path, method, action, expected=200):
        """Forward exactly one real mutation and retain its original response bytes."""
        records = []; url = self.base + path
        def forward(route):
            assert route.request.url == url and route.request.method == method
            response = route.fetch(max_redirects=0); raw = response.body()
            records.append(dict(body=route.request.post_data_json, status=response.status, result=json.loads(raw)))
            route.fulfill(status=response.status, headers=response.headers, body=raw)
        page.route(url, forward)
        try:
            action(); self.settle(page, lambda: len(records) == 1)
            assert len(records) == 1 and records[0]['status'] == expected, records
            return records[0]
        finally:
            page.unroute(url, forward)

    def places_roundtrip(self, page, original):
        before = self.snapshot()
        icon_button(page, '旅行地点').click()
        expect(page.get_by_test_id('journey-places-panel')).to_be_visible()
        button(page, '整理目的地：东京').click()
        textfield(page, '地点名称').fill(PLACE_TITLE)
        expect(textfield(page, '纬度（可不填）')).to_have_value('')
        expect(textfield(page, '经度（可不填）')).to_have_value('')
        expect(page.get_by_role('checkbox', name='向家庭共享这个地点', exact=True)).not_to_be_checked()
        assert self.snapshot() == before
        packet = self.capture_mutation(page, PLACE, 'POST', lambda: button(page, '确认保存地点').click(), 201)
        place = packet['result']['place']
        assert place['journeyId'] == original['id'] and place['status'] == 'planned'
        assert place['visibility'] == 'private' and place['coordinateDisclosure'] == 'hidden'
        assert not place['visitedConfirmedAt'] and not place['visitedConfirmedBy']
        assert (place['startDate'], place['endDate']) == ('2027-10-01', '2027-10-03')
        button(page, '在地图查看这个地点').click()
        expect(page.get_by_role('heading', name='足迹地图', exact=True)).to_be_visible()
        expect(page.locator('body')).to_contain_text(PLACE_TITLE)
        expect(button(page, '查看旅行')).to_be_enabled()
        button(page, '查看旅行').click(); self.current_ready(page, TITLE)
        current = self.detail(page.context, original['id'])
        assert entity_ids(current) == entity_ids(original)
        assert self.get(page.context, PLACE + '/' + place['id'])['place'] == place
        self.proof('place_map_return', current, placeId=place['id'])
        return place

    def assign_owners(self, page, original):
        people = {row['id']: row['name'] for row in self.get(page.context, '/api/state')['people']}
        button(page, '管理清单').click()
        page.get_by_text('准备清单与采购', exact=True).click()
        page.get_by_label('准备负责人 1：' + people['member1'], exact=True).click()
        page.get_by_label('采购负责人 1：' + people['member2'], exact=True).click()
        before = self.snapshot()
        packet = self.capture_mutation(page, PREVIEW, 'POST', lambda: button(page, '预览变更').click())
        assert packet['body']['journeyId'] == original['id']
        preview = packet['result']; assert preview['canApply'] and self.snapshot() == before
        expect(button(page, '确认保存旅行')).to_be_enabled()
        saved = self.capture_mutation(page, APPLY, 'POST', lambda: button(page, '确认保存旅行').click())
        assert saved['result']['id'] == original['id'] and saved['result']['tripId'] == original['tripId']
        self.current_ready(page, TITLE)
        current = self.detail(page.context, original['id'])
        assert entity_ids(current) == entity_ids(original)
        assert next(row for row in current['tasks'] if row['title'] == TASK_TITLES[0])['owner'] == 'member1'
        purchases = {row['title']: row for row in current['shopping']}
        assert purchases[SHOP_TITLES[0]]['owner'] == 'member2'
        assert purchases[SHOP_TITLES[0]]['budget'] == 0 and purchases[SHOP_TITLES[1]]['budget'] is None
        assert current['plan']['segments'] == original['plan']['segments']
        assert current['budget'] == original['budget']
        self.proof('assigned_owners', current)
        return current

    def calendar_preview_only(self, page, detail, label):
        before = self.snapshot()
        icon_button(page, '同步到日历').click()
        expect(page.get_by_role('heading', name='旅行日历同步', exact=True)).to_be_visible()
        source = page.get_by_role('radio', name='选择日历：本人合成旅行日历 · 合成账户', exact=True)
        expect(source).to_be_enabled(); source.click()
        expect(page.locator('body')).not_to_contain_text('PARTNER_CALENDAR_PRIVATE')
        packet = self.capture_mutation(page, CP + '/preview', 'POST', lambda: button(page, '预览日程').click())
        assert packet['body'] == {'journeyId': detail['id'], 'sourceId': 'chain-source-mine'}
        preview = packet['result']
        assert preview['source']['id'] == 'chain-source-mine' and preview['source']['writeAuthorized']
        assert {row['id'] for row in preview['events']} == {row['id'] for row in detail['events']}
        for row in preview['events']:
            live = next(item for item in detail['events'] if item['id'] == row['id'])
            assert (row['start'], row['end']) == (live['start'], live['end'])
        expect(button(page, '确认加入同步')).to_be_enabled()
        assert self.snapshot() == before
        self.no_cloud()
        icon_button(page, '返回旅行').click(); self.current_ready(page, TITLE)
        assert self.detail(page.context, detail['id']) == detail
        self.proof(label, detail, sourceId='chain-source-mine', cloudConfirmed=False)

    def reschedule(self, page, original, place):
        button(page, '调整日期').click()
        expect(page.get_by_test_id('journey-reschedule-selection')).to_be_visible()
        expect(textfield(page, '新的出发日期')).to_be_editable()
        assert all(not row.is_checked() for row in page.get_by_role('checkbox').all())
        textfield(page, '新的出发日期').fill('2027-10-04')
        textfield(page, '新的返程日期').fill('2027-10-06')
        for name in ('东京', ACTIVITY_TITLE, TASK_TITLES[0], PLACE_TITLE):
            choice = page.get_by_role('checkbox', name='联动改期：' + name, exact=True)
            expect(choice).not_to_be_checked(); choice.click(); expect(choice).to_be_checked()
        before = self.snapshot()
        packet = self.capture_mutation(page, '/api/journeys/' + original['id'] + '/reschedule-preview',
            'POST', lambda: button(page, '预览改期').click())
        preview = packet['result']; assert preview['canApply'] and self.snapshot() == before
        first_task = next(row for row in original['tasks'] if row['title'] == TASK_TITLES[0])
        selected = {row['key'] for row in preview['items'] if row['selected'] and row['key'] != 'trip'}
        assert selected == {'destination:tokyo', 'segment:tokyo-day', first_task['workflowKey'], 'place:' + place['id']}
        expect(page.get_by_test_id('journey-reschedule-preview')).to_be_visible()
        expect(button(page, '确认改期')).to_be_enabled()
        saved = self.capture_mutation(page, APPLY, 'POST', lambda: button(page, '确认改期').click())
        assert saved['result']['operation'] == 'reschedule' and saved['result']['id'] == original['id']
        expect(button(page, '返回旅行详情')).to_be_enabled()
        button(page, '返回旅行详情').click(); self.current_ready(page, TITLE)
        current = self.detail(page.context, original['id'])
        assert entity_ids(current) == entity_ids(original) and current['revision'] == original['revision'] + 1
        assert (current['trip']['start'], current['trip']['end']) == ('2027-10-04', '2027-10-06')
        destination = current['plan']['destinations'][0]
        assert (destination['arrival'], destination['departure']) == ('2027-10-04', '2027-10-06')
        assert current['plan']['segments'][0]['dateRange'] == {'startDate': '2027-10-05', 'endDateExclusive': '2027-10-06'}
        assert next(row for row in current['tasks'] if row['id'] == first_task['id'])['due'] == '2027-10-03'
        shifted_task = next(row for row in current['tasks'] if row['id'] == first_task['id'])
        for field in ('title', 'owner', 'note', 'done'):
            assert shifted_task[field] == first_task[field]
        unchanged = next(row for row in original['tasks'] if row['title'] == TASK_TITLES[1])
        assert next(row for row in current['tasks'] if row['id'] == unchanged['id']) == unchanged
        assert current['shopping'] == original['shopping'] and current['budget'] == original['budget']
        shifted = self.get(page.context, PLACE + '/' + place['id'])['place']
        assert (shifted['startDate'], shifted['endDate']) == ('2027-10-04', '2027-10-06')
        for key in ('id', 'journeyId', 'visibility', 'status', 'coordinateDisclosure', 'coordinates'):
            assert shifted[key] == place[key]
        self.no_cloud(); self.proof('rescheduled', current, placeId=place['id'])
        return current, shifted

    def complete_item(self, page, kind, item, journey_id):
        path = '/api/items/' + kind + '/' + item['id']; previous = self.count_requests('PATCH', path)
        checkbox = page.get_by_role('checkbox', name='完成' + item['title'], exact=True)
        expect(checkbox).to_be_enabled()
        packet = self.capture_mutation(page, path, 'PATCH', checkbox.click)
        assert packet['body'] == {'revision': item['revision'], 'done': True}
        expect(page.get_by_role('checkbox', name='恢复' + item['title'], exact=True)).to_be_enabled()
        self.current_ready(page, TITLE)
        current = self.detail(page.context, journey_id)
        saved = next(row for row in current[kind] if row['id'] == item['id'])
        assert saved['done'] is True and saved['revision'] == item['revision'] + 1
        assert {k: v for k, v in saved.items() if k not in ('done', 'revision')} == {
            k: v for k, v in item.items() if k not in ('done', 'revision')}
        assert self.count_requests('PATCH', path) == previous + 1
        return current

    def capture_view(self, page, label):
        target = page.get_by_role('heading', name=re.compile(r'^准备 · '))
        target.scroll_into_view_if_needed()
        page.evaluate('() => document.fonts.ready')
        page.wait_for_timeout(400)  # Capture only; no wait is used to make a mutation pass.
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2')
        path = self.out / (label + '.png'); page.screenshot(path=str(path))
        self.report['screenshots'].append(dict(path=path.relative_to(self.out.parent).as_posix(),
            sha256=sha(path), viewport=page.viewport_size, scope='Current visible viewport, internal scroll not exhaustive'))

    def same_trip_chain(self, browser):
        with self.flow(browser) as (ctx, page):
            original = self.import_one(page)
            place = self.places_roundtrip(page, original)
            assigned = self.assign_owners(page, original)
            self.calendar_preview_only(page, assigned, 'calendar_preview_before')
            shifted, shifted_place = self.reschedule(page, assigned, place)
            self.calendar_preview_only(page, shifted, 'calendar_preview_after')
            current = shifted
            for kind in ('tasks', 'shopping'):
                for item in shifted[kind]:
                    current = self.complete_item(page, kind, item, original['id'])
            assert entity_ids(current) == entity_ids(original)
            assert current['progress'] == {'done': 2, 'total': 2, 'purchased': 2, 'purchaseCount': 2}
            assert current['budget']['total'] == 1234567 and current['budget']['paid'] == 7890
            assert current['budget']['reserved'] == 23456 and current['budget']['purchaseBudget'] == 0
            assert current['budget']['unknownPurchaseBudgets'] == 1
            assert current['budget']['purchaseActual'] == 0 and current['budget']['unknownPurchaseActuals'] == 2
            expect(page.get_by_role('heading', name='准备 · 2/2', exact=True)).to_be_visible()
            expect(page.get_by_role('heading', name='采购 · 2/2', exact=True)).to_be_visible()
            self.no_cloud(); before = self.snapshot(); self.restart()
            page.goto(self.base + '/app/trips?request=1001&item=' + original['tripId'])
            self.current_ready(page, TITLE)
            assert self.detail(ctx, original['id']) == current
            assert self.get(ctx, PLACE + '/' + place['id'])['place'] == shifted_place
            assert self.snapshot() == before
            assert len(self.get(ctx, '/api/journeys')['journeys']) == 1
            assert self.count_requests('POST', APPLY) == 3  # Import, owner edit, explicit reschedule.
            assert sum(row['method'] == 'PATCH' and row['path'].startswith('/api/items/') for row in self.requests) == 4
            self.no_cloud(); self.proof('completed_and_restarted', current, placeId=place['id'])
            self.capture_view(page, 'completed-same-trip')
            self.passed('One real UI-imported trip retains IDs through private map, owner assignment, calendar-only previews, explicit reschedule, completion and restart')

    def completed_write_lost_readback(self, browser):
        with self.flow(browser) as (ctx, page):
            timeline = []; began = time.monotonic(); request_ids = {}
            self.report.setdefault('requestTimelines', {})[self.out.name] = timeline
            def trace(event, request=None, **data):
                if request is not None and not urlsplit(request.url).path.startswith('/api/'):
                    return
                assert len(timeline) < 1000, 'Bounded diagnostic request timeline exceeded'
                if request is not None:
                    request_ids.setdefault(request, len(request_ids) + 1)
                    data.update(requestId=request_ids[request], method=request.method, path=urlsplit(request.url).path)
                timeline.append(dict(sequence=len(timeline) + 1, elapsedMs=round((time.monotonic() - began) * 1000), event=event, **data))
            ctx.on('request', lambda request: trace('browser-request', request))
            ctx.on('response', lambda response: trace('browser-response', response.request, status=response.status))
            ctx.on('requestfinished', lambda request: trace('browser-request-finished', request))
            ctx.on('requestfailed', lambda request: trace('browser-request-failed', request, error=request.failure))
            original = self.import_one(page); item = original['tasks'][0]
            path = '/api/items/tasks/' + item['id']; url = self.base + '/api/journeys/' + original['id']
            patches = self.count_requests('PATCH', path); lost = []; armed = [False]; recovery_ready = False
            def drop_readback(route):
                assert route.request.method == 'GET'
                response = route.fetch(max_redirects=0); raw = response.body()
                assert response.status == 200, raw
                # A request begun before PATCH may finish after it. Decide at
                # response time, and never let a later successful GET bypass the fault.
                if not armed[0]:
                    trace('actual-detail-forwarded-before-commit', route.request, status=response.status)
                    route.fulfill(status=response.status, headers=response.headers, body=raw); return
                detail = json.loads(raw)
                assert detail['id'] == original['id'] and len(lost) < 32
                done = next(row for row in detail['tasks'] if row['id'] == item['id'])['done']
                trace('actual-detail-200-discarded', route.request, status=response.status, completed=done)
                lost.append(detail); route.abort('failed')
            def commit_then_arm(route):
                assert route.request.method == 'PATCH' and route.request.post_data_json == {'revision': item['revision'], 'done': True}
                response = route.fetch(max_redirects=0); raw = response.body()
                assert response.status == 200, raw
                armed[0] = True
                trace('actual-patch-committed', route.request, status=response.status)
                route.fulfill(status=response.status, headers=response.headers, body=raw)
            page.route(url, drop_readback); page.route(self.base + path, commit_then_arm)
            try:
                page.get_by_role('checkbox', name='完成' + item['title'], exact=True).click()
                self.settle(page, lambda: len(lost) >= 1)
                expect(page.get_by_text('旅行暂时无法读取', exact=True)).to_be_visible()
                expect(button(page, '重试')).to_be_enabled()
                expect(page.get_by_role('checkbox', name='完成' + item['title'], exact=True)).to_have_count(0)
                expect(button(page, '管理清单')).to_have_count(0)
                trace('readback-unavailable-controls-cleared')
                assert armed[0] and self.count_requests('PATCH', path) == patches + 1
                assert any(next(row for row in detail['tasks'] if row['id'] == item['id'])['done'] is True for detail in lost)
                # APIRequestContext reads the real server separately; it does not
                # bypass the still-blocked UI or manufacture a browser success.
                committed = self.detail(ctx, original['id'])
                saved_task = next(row for row in committed['tasks'] if row['id'] == item['id'])
                assert saved_task['done'] is True and saved_task['revision'] == item['revision'] + 1
                trace('independent-server-read-confirms-completion')
                before = self.snapshot(); recovery_ready = True
            finally:
                page.unroute(url, drop_readback); page.unroute(self.base + path, commit_then_arm)
                trace('fault-released-for-explicit-read' if recovery_ready else 'fault-cleaned-after-test-failure')
            trace('user-clicks-read-only-retry'); button(page, '重试').click()
            card = page.get_by_test_id('section-card-content').filter(has=page.get_by_role('heading', name=TITLE, exact=True))
            expect(card.get_by_role('button', name='查看', exact=True)).to_be_enabled()
            card.get_by_role('button', name='查看', exact=True).click(); self.current_ready(page, TITLE)
            expect(page.get_by_role('checkbox', name='恢复' + item['title'], exact=True)).to_be_enabled()
            expect(page.get_by_role('heading', name='准备 · 1/2', exact=True)).to_be_visible()
            assert self.detail(ctx, original['id']) == committed and self.snapshot() == before
            assert self.count_requests('PATCH', path) == patches + 1
            assert self.count_requests('POST', APPLY) == 1
            assert entity_ids(committed) == entity_ids(original)
            assert committed['shopping'] == original['shopping'] and committed['budget'] == original['budget']
            trace('fresh-ui-completion-restored', patchCount=self.count_requests('PATCH', path) - patches)
            self.no_cloud(); self.proof('completed_readback_recovered', committed, mutationCount=1, discardedDetailResponses=len(lost))
            self.capture_view(page, 'readback-recovered')
            self.passed('A real completion PATCH commits once; blocked actual detail responses clear stale controls and explicit readback recovers without another PATCH')

    @classmethod
    def run_scenarios(cls, root, bundle, report, out, browser, scenarios):
        for name in scenarios:
            case_out = out / name; case_out.mkdir(); folder = None
            before = (len(report['checks']), len(report['pageErrors']), len(report['externalRequests']))
            case = dict(name=name, passed=False, temporaryFixtureRemoved=False)
            try:
                with ExitStack() as resources:
                    folder = Path(resources.enter_context(tempfile.TemporaryDirectory(prefix='expo-travel-chain-')))
                    case['temporaryDirectory'] = str(folder)
                    run = cls(root, bundle, folder, report, case_out, resources)
                    getattr(run, name)(browser)
                    run.no_cloud(); case['providerCalls'] = len(run.provider_calls)
                    case['calendarConfirmRequests'] = run.count_requests('POST', CP + '/confirm')
                assert not folder.exists() and len(report['checks']) == before[0] + 1
                assert len(report['pageErrors']) == before[1] and len(report['externalRequests']) == before[2]
                case['passed'] = True
            except Exception:
                del report['checks'][before[0]:]
                failure = traceback.format_exc(); (case_out / 'failure.txt').write_text(failure, encoding='utf-8')
                report['scenarioFailures'].append(dict(scenario=name, traceback=failure, artifacts=name))
                print('FAIL ' + name + '\n' + failure, flush=True)
            finally:
                case['temporaryFixtureRemoved'] = folder is not None and not folder.exists()
                report['scenarioResults'].append(case)
        assert not report['scenarioFailures'], 'Every selected case must pass; failures retained'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-harness-head', required=True)
    parser.add_argument('--expected-harness-sha256', required=True)
    parser.add_argument('--scenario', choices=('all', *SCENARIOS), default='all', help='Explicit subset; never reported as both cases passing')
    parser.add_argument('--source-root', required=True, type=Path); parser.add_argument('--expected-head', required=True)
    parser.add_argument('--bundle', required=True, type=Path); parser.add_argument('--expected-build-evidence', required=True)
    args = parser.parse_args(); root, bundle = args.source_root.resolve(), args.bundle.resolve()
    scenarios = SCENARIOS if args.scenario == 'all' else (args.scenario,)
    assert all(re.fullmatch('[a-f0-9]{40}', value) for value in (args.expected_head, args.expected_harness_head))
    assert all(re.fullmatch('[a-f0-9]{64}', value) for value in (args.expected_build_evidence, args.expected_harness_sha256))
    harness_root = Path(__file__).resolve().parents[1]
    def harness_git(*command):
        return subprocess.check_output(['git', '--no-replace-objects', *command], cwd=harness_root, text=True).strip()
    harness_head = harness_git('rev-parse', 'HEAD')
    assert harness_head == args.expected_harness_head and not harness_git('status', '--porcelain=v1')
    assert sha(Path(__file__)) == args.expected_harness_sha256
    own_names = ('tests/browser_expo_travel_chain_check.py', 'docs/EXPO-TRAVEL-CHAIN.md')
    def harness_hashes(): return {name: sha(harness_root / name) for name in own_names}
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
    out = Path(__file__).resolve().parents[1] / 'test-results' / ('expo-travel-chain-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True); shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], screenshots=[], scenarioResults=[], scenarioFailures=[], head=head, tree=evidence['sourceTree'],
        sourceRoot=str(root), harnessRoot=str(harness_root), harnessHead=harness_head,
        selectedScenarios=list(scenarios), requestedChecks=len(scenarios), fullSuite=False,
        harnessTree=harness_git('rev-parse', 'HEAD^{tree}'), harnessSourceHashesBefore=harness_hashes(),
        harnessPathPresentInApplicationHead='tests/browser_expo_travel_chain_check.py' in names,
        buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(out / 'executed-harness.py'), sourceHashesBefore=hashes(), bundleHashesBefore=exports(),
        productionWrites=0, realFinancialData=False, realCloud=False, realAI=False, physicalTelevision=False,
        scope='Explicitly selected real Flask/SQLite/HTTPS/Edge cases from the two-case local chain suite. Readback faults discard actual 200 responses until explicit recovery. Synthetic JSON and calendar accounts; no worker, provider call or calendar confirmation. Task/purchase completion is not proof of an actual completed trip. Captures cover visible viewports only.')
    original_connect = socket.socket.connect
    def local_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
            report['externalRequests'].append({'kind': 'non-loopback socket'}); raise AssertionError('External network forbidden')
        return original_connect(sock, address)
    try:
        with patch.object(socket.socket, 'connect', local_connect), sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            try:
                Run.run_scenarios(root, bundle, report, out, browser, scenarios)
                assert len(report['checks']) == len(scenarios) and len(report['screenshots']) == len(scenarios)
                assert len(report['fixtureHashes']) == 7
                assert not report['pageErrors'] and not report['externalRequests']; report['passed'] = True
            finally: browser.close()
    except Exception:
        report['passed'] = False; report['failure'] = traceback.format_exc(); print(report['failure'], flush=True)
    finally:
        report['sourceHashesAfter'] = hashes(); report['bundleHashesAfter'] = exports()
        report['sourceUnchanged'] = report['sourceHashesBefore'] == report['sourceHashesAfter']
        report['bundleUnchanged'] = report['bundleHashesBefore'] == report['bundleHashesAfter']
        report['sourceStillFrozen'] = git('rev-parse', 'HEAD') == head and not git('status', '--porcelain=v1')
        report['harnessSourceHashesAfter'] = harness_hashes()
        report['harnessStillFrozen'] = (harness_git('rev-parse', 'HEAD') == harness_head
            and not harness_git('status', '--porcelain=v1')
            and report['harnessSourceHashesBefore'] == report['harnessSourceHashesAfter']
            and sha(Path(__file__)) == args.expected_harness_sha256)
        report['fixtureHashesAfter'] = {name: sha(Path(path)) for name, path in report.get('fixtureActualPaths', {}).items()}
        report['fixturesUnchanged'] = len(report.get('fixtureHashes', {})) == 7 and report['fixtureHashesAfter'] == report['fixtureHashes']
        report['temporaryFixtureRemoved'] = len(report['scenarioResults']) == len(scenarios) and all(case['temporaryFixtureRemoved'] for case in report['scenarioResults'])
        report['passed'] = report['passed'] and report['sourceUnchanged'] and report['bundleUnchanged'] and report['sourceStillFrozen'] and report['harnessStillFrozen'] and report['fixturesUnchanged'] and report['temporaryFixtureRemoved']
        report['fullSuite'] = report['passed'] and len(scenarios) == CHECKS
        with (out / 'result.json').open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'report': str(out / 'result.json')}, ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    raise SystemExit(main())
