"""Frozen Expo trip coordination: real Flask/SQLite/Edge, fake provider HTTP only.

No real calendar, AI, geocoder, production data or physical TV is accessed.
The inherited journey harness supplies the local server, auth, file bindings,
travel UI helpers and viewport checks; existing Remote supplies provider I/O.
"""
import argparse
from contextlib import ExitStack, closing
from copy import deepcopy
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright
import browser_expo_journey_brief_check as journey_fixture
from browser_expo_journey_brief_check import Run as JourneyRun, button, icon_button, textfield, sha, WIDTHS


CP = '/api/calendar-publish'
PLACE = '/api/journey-places'
PROMPT = '''旅行名称：合成东京协作旅行
出发日期：2028-03-02
返程日期：2028-03-04
旅行类型：境外
家庭总预算（人民币）：1000元
日本/东京 2028-03-02 至 2028-03-04'''


class Run(JourneyRun):
    def __init__(self, *args, provider, **kwargs):
        self.provider = provider
        self.remote = None
        super().__init__(*args, **kwargs)
        for module, relative in [(journey_fixture, 'tests/browser_expo_journey_brief_check.py'),
                (importlib.import_module('test_calendar_publish'), 'tests/test_calendar_publish.py')]:
            assert sha(Path(module.__file__)) == sha(self.root / relative)
            self.report.setdefault('fixtureHashes', {})[relative] = sha(Path(module.__file__))
        assert sha(Path(__file__)) == sha(self.root / 'tests/browser_expo_trip_coordination_check.py')
        self.seed_accounts()

    def start(self, port=0):
        if self.remote is None:
            self.remote = importlib.import_module('test_calendar_publish').Remote()
        self.cfg.update(CLOUD_TRANSPORT=self.remote.transport,
            GOOGLE_CLIENT_ID='synthetic-google-client', GOOGLE_CLIENT_SECRET='synthetic-google-secret',
            MICROSOFT_CLIENT_ID='synthetic-ms-client', MICROSOFT_CLIENT_SECRET='synthetic-ms-secret')
        super().start(port)

    def fake_model(self, *_args, **_kwargs):
        raise AssertionError('This suite authorizes local extraction only, never model execution')

    def seed_accounts(self):
        engine = self.application.extensions['cloud_accounts']
        self.scope = ('User.Read Calendars.ReadWrite Tasks.ReadWrite' if self.provider == 'microsoft' else
            'https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/tasks')
        with engine.db() as con:
            for suffix, owner, name in [('mine', 'member1', '本人合成旅行日历'),
                    ('partner', 'member2', 'PARTNER_CALENDAR_PRIVATE')]:
                token = engine.encrypt({'access_token': 'synthetic-token', 'refresh_token': 'synthetic-refresh',
                    'scope': self.scope, 'expires_at': time.time() + 3600})
                con.execute('INSERT INTO cloud_accounts(id,owner,provider,client_id,subject,name,email,tokens) VALUES(?,?,?,?,?,?,?,?)',
                    ('account-' + suffix, owner, self.provider, self.cfg[self.provider.upper() + '_CLIENT_ID'],
                     'synthetic-subject-' + suffix, '合成账户' if suffix == 'mine' else 'PARTNER_ACCOUNT_PRIVATE',
                     suffix + '@synthetic.invalid', token))
                con.execute('INSERT INTO cloud_sources(id,account_id,remote_id,kind,name,owner) VALUES(?,?,?,?,?,?)',
                    ('source-' + suffix, 'account-' + suffix, 'calendar-' + suffix, 'calendar', name, owner))

    def snapshot(self):
        result = super().snapshot()
        with closing(sqlite3.connect(self.database)) as con:
            result['journey_places'] = sorted(con.execute('SELECT * FROM journey_places').fetchall(), key=repr)
        return result

    def publication(self, rid):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database)) as con:
            con.row_factory = sqlite3.Row
            return dict(con.execute('SELECT * FROM calendar_publications WHERE id=?', (rid,)).fetchone())

    def state(self, ctx, journey):
        return self.get(ctx, CP + '/journeys/' + journey)

    def detail(self, ctx, journey):
        return self.get(ctx, '/api/journeys/' + journey)

    def shots(self, page, label):
        # Four widths once; the second provider exercises the same components.
        if self.provider == 'microsoft':
            for width in WIDTHS:
                self.screenshot(page, label, width)
            page.set_viewport_size({'width': 390, 'height': 844})

    def open_calendar(self, page, trip=None):
        if trip:
            self.show_saved(page, trip)
        button(page, '同步到日历').click()
        expect(page.get_by_role('heading', name='旅行日历同步', exact=True)).to_be_visible()
        expect(button(page, '刷新同步状态')).to_be_enabled()

    def choose_source(self, page):
        page.get_by_label('选择日历：本人合成旅行日历 · 合成账户', exact=True).click()
        expect(page.locator('body')).not_to_contain_text('PARTNER_CALENDAR_PRIVATE')
        expect(page.locator('body')).not_to_contain_text('PARTNER_ACCOUNT_PRIVATE')

    def calendar_preview(self, page, expected_events=1):
        before, calls = self.snapshot(), len(self.remote.calls)
        with page.expect_response(lambda r: urlsplit(r.url).path == CP + '/preview' and r.request.method == 'POST') as pending:
            button(page, '预览日程').click()
        response = pending.value
        assert response.status == 200, response.text()
        assert len(response.json()['events']) == expected_events
        assert self.snapshot() == before, 'Publication preview changed business rows'
        assert len(self.remote.calls) == calls, 'Publication preview called the provider'
        expect(button(page, '确认加入同步')).to_be_enabled()
        return response.json()

    def calendar_confirm(self, page):
        with page.expect_response(lambda r: urlsplit(r.url).path == CP + '/confirm' and r.request.method == 'POST') as pending:
            button(page, '确认加入同步').click()
        response = pending.value
        assert response.status == 200, response.text()
        return response.json()['publicationIds']

    def create_trip_ui(self, page):
        before = self.snapshot()
        assert self.start_brief(page, PROMPT).status == 200
        normalized = self.bridge(page)
        assert len(normalized['plan']['segments']) == 1
        page.get_by_text('分段行程与备注', exact=True).click()
        button(page, '移出分段 1').click()
        planned = self.preview(page)
        assert planned['summary']['create']['events'] == 1 and planned['plan']['segments'] == []
        assert self.snapshot() == before
        receipt = self.confirm(page)
        saved = self.detail(page.context, receipt['id'])
        assert len(saved['events']) == 1 and saved['events'][0]['workflowKey'] == 'event:overview'
        self.passed(self.provider + ': local brief and actual UI save one overview event; all previews are zero-write')
        return receipt

    def places_roundtrip(self, page, receipt):
        ctx = page.context
        before = self.snapshot()
        button(page, '旅行地点').click()
        expect(page.get_by_test_id('journey-places-panel')).to_be_visible()
        button(page, '整理目的地：东京').click()
        expect(textfield(page, '纬度（可不填）')).to_have_value('')
        expect(textfield(page, '经度（可不填）')).to_have_value('')
        shared = page.get_by_role('checkbox', name='向家庭共享这个地点', exact=True)
        expect(shared).to_have_attribute('aria-checked', 'false')
        button(page, '取消地点编辑').click()
        assert self.snapshot() == before
        button(page, '整理目的地：东京').click()
        textfield(page, '地点名称').fill('合成东京计划地点')
        textfield(page, '纬度（可不填）').fill('35.68')
        textfield(page, '经度（可不填）').fill('139.76')
        self.shots(page, 'planned-private-place')
        with page.expect_response(lambda r: urlsplit(r.url).path == PLACE and r.request.method == 'POST') as pending:
            button(page, '确认保存地点').click()
        response = pending.value
        assert response.status in (200, 201), response.text()
        place = response.json()['place']
        assert place['journeyId'] == receipt['id'] and place['status'] == 'planned'
        assert place['visibility'] == 'private' and place['coordinateDisclosure'] == 'hidden'
        assert place['coordinates'] == {'latitude': 35.68, 'longitude': 139.76}
        assert not place['visitedConfirmedAt'] and not place['visitedConfirmedBy']
        button(page, '在地图查看这个地点').click()
        expect(page.get_by_role('heading', name='足迹地图', exact=True)).to_be_visible()
        expect(button(page, '查看旅行')).to_be_enabled()
        assert self.get(ctx, PLACE + '/' + place['id'])['place']['status'] == 'planned'
        button(page, '查看旅行').click()
        expect(page.get_by_role('heading', name='旅行详情', exact=True)).to_be_visible()
        expect(page.get_by_role('heading', name='合成东京协作旅行', exact=True)).to_be_visible()
        self.passed(self.provider + ': suggestion and cancel do not save; explicit planned/private place persists and map selects the linked trip')
        return place

    def publish_unknown(self, page, receipt):
        self.open_calendar(page)
        self.choose_source(page)
        self.calendar_preview(page)
        self.shots(page, 'calendar-preview')
        dropped = {}

        def lose_reply(handler):
            if handler.request.method == 'POST' and not dropped:
                response = handler.fetch(max_redirects=0)
                assert response.status == 200, response.text()
                dropped.update(body=handler.request.post_data_json, result=response.json())
                handler.abort('failed')
            else:
                handler.continue_()

        posts = self.count_requests('POST', CP + '/confirm')
        page.route(self.base + CP + '/confirm', lose_reply)
        button(page, '确认加入同步').click()
        expect(button(page, '核对当前状态')).to_be_enabled()
        page.unroute(self.base + CP + '/confirm', lose_reply)
        assert len(dropped['result']['publicationIds']) == 1
        rid = dropped['result']['publicationIds'][0]
        before = self.snapshot()
        with page.expect_response(lambda r: urlsplit(r.url).path == CP + '/journeys/' + receipt['id']) as checked:
            button(page, '核对当前状态').click()
        assert checked.value.status == 200
        expect(button(page, '核对当前状态')).to_be_enabled()
        assert self.count_requests('POST', CP + '/confirm') == posts + 1
        assert self.snapshot() == before
        assert self.state(page.context, receipt['id'])['publications'][0]['id'] == rid
        # A new explicit preview+confirm must keep the existing queue identity.
        # The conservative unknown state remains locked until leaving the panel.
        button(page, '返回旅行').click()
        self.open_calendar(page)
        self.choose_source(page)
        self.calendar_preview(page)
        assert self.calendar_confirm(page) == [rid]
        worker = self.application.extensions['calendar_publish']
        self.remote.lose_create = True
        worker.process(rid)
        assert self.publication(rid)['status'] == 'retry' and self.remote.created == 1
        worker.process(rid)
        assert self.publication(rid)['status'] == 'published' and self.remote.created == 1
        assert self.remote.patched == 0 and len(self.remote.records) == 1
        button(page, '刷新同步状态').click()
        self.passed(self.provider + ': unknown confirm only reads; explicit reconfirm and lost provider create retain one queue and one remote event')
        return rid

    def ordinary_reschedule(self, page, receipt, rid, place):
        ctx = page.context
        old = self.detail(ctx, receipt['id'])
        remote_id = self.publication(rid)['remote_id']
        button(page, '返回旅行').click()
        icon_button(page, '编辑旅行').click()
        for name, value in [('出发日期（YYYY-MM-DD）', '2028-03-05'), ('返程日期（包含当天）', '2028-03-07'),
                ('抵达日期 1', '2028-03-05'), ('离开日期 1', '2028-03-07')]:
            textfield(page, name).fill(value)
        assert self.preview(page)['summary']['cloudReviews'] == []
        self.confirm(page)
        current = self.detail(ctx, receipt['id'])
        assert current['events'][0]['id'] == old['events'][0]['id']
        assert current['events'][0]['start'].startswith('2028-03-05')
        assert {r['id']: r.get('due') for r in current['tasks']} == {r['id']: r.get('due') for r in old['tasks']}
        saved_place = self.get(ctx, PLACE + '/' + place['id'])['place']
        assert saved_place['startDate'] == place['startDate'], 'Map dates are not automatically coordinated'
        worker = self.application.extensions['calendar_publish']
        self.remote.lose_patch = True
        worker.process(rid)
        assert self.publication(rid)['status'] == 'retry' and self.remote.patched == 1
        worker.process(rid)
        row = self.publication(rid)
        assert row['status'] == 'published' and row['review_required'] == 0
        assert row['remote_id'] == remote_id and self.remote.created == 1 and self.remote.patched == 1
        self.open_calendar(page)
        button(page, '刷新同步状态').click()
        self.passed(self.provider + ': actual date edit updates the same remote event once despite lost PATCH; task/map dates are explicitly not auto-shifted')

    def api_apply(self, ctx, plan, current=None):
        body = {'plan': plan}
        if current:
            body.update(journeyId=current['id'], revision=current['revision'])
        before = self.snapshot()
        preview = self.write(ctx, 'POST', '/api/journeys/preview', body)
        assert preview['canApply'] and preview['previewToken'] and self.snapshot() == before
        result = self.write(ctx, 'POST', '/api/journeys/apply',
            {'previewToken': preview['previewToken'], 'idempotencyKey': uuid4().hex}, 200 if current else 201)
        return self.detail(ctx, result['id'])

    def timing_review(self, page):
        # Complex segment editing is API setup, NOT claimed as an Expo editor feature.
        ctx = page.context
        plan = {'title': '合成时间复核旅行', 'start': '2028-04-01', 'end': '2028-04-03', 'budget': 0,
            'international': True, 'memberIds': ['member1', 'member2'], 'checklist': [], 'shopping': [],
            'destinations': [{'key': 'tokyo', 'country': '日本', 'city': '东京', 'arrival': '2028-04-01', 'departure': '2028-04-03'}],
            'segments': [{'key': 'activity', 'title': '合成需要复核的活动', 'start': '2028-04-02', 'end': '2028-04-02', 'location': '东京', 'note': ''}]}
        old = self.api_apply(ctx, plan)
        self.open_calendar(page, old['tripId'])
        self.choose_source(page)
        self.calendar_preview(page, 2)
        ids = self.calendar_confirm(page)
        assert len(ids) == 2
        worker = self.application.extensions['calendar_publish']
        for rid in ids:
            worker.process(rid)
        event = next(e for e in old['events'] if e['workflowKey'] == 'segment:activity')
        rid = next(r for r in ids if self.publication(r)['entity_id'] == event['id'])
        remote_id = self.publication(rid)['remote_id']
        created, patched = self.remote.created, self.remote.patched
        advanced = deepcopy(old['plan'])
        advanced.update(schemaVersion=2, referenceTimezone='Asia/Shanghai')
        advanced['destinations'][0]['timeZone'] = 'Asia/Tokyo'
        advanced['segments'] = [{'key': 'activity', 'kind': 'activity', 'title': event['title'], 'location': '东京', 'note': '',
            'start': {'local': '2028-04-02T10:00:00', 'timeZone': 'Asia/Tokyo'},
            'end': {'local': '2028-04-02T12:00:00', 'timeZone': 'Asia/Tokyo'}}]
        self.api_apply(ctx, advanced, old)
        assert self.publication(rid)['review_required'] == 1
        calls = len(self.remote.calls)
        worker.process(rid)
        assert len(self.remote.calls) == calls
        button(page, '刷新同步状态').click()
        before = self.snapshot()
        with page.expect_response(lambda r: urlsplit(r.url).path == CP + '/publications/' + rid + '/review-preview') as pending:
            button(page, '核对时间变化：' + event['title']).click()
        response = pending.value
        assert response.status == 200, response.text()
        assert response.json()['remote']['allDay'] is True and response.json()['local']['allDay'] is False
        assert self.snapshot() == before
        assert all(call[0] == 'GET' for call in self.remote.calls[calls:])
        self.shots(page, 'calendar-time-review')
        with page.expect_response(lambda r: urlsplit(r.url).path == CP + '/publications/' + rid + '/review-confirm') as pending:
            button(page, '确认变化并恢复同步').click()
        assert pending.value.status == 200
        assert self.remote.created == created and self.remote.patched == patched
        worker.process(rid)
        assert self.publication(rid)['remote_id'] == remote_id and self.publication(rid)['status'] == 'published'
        assert self.remote.created == created and self.remote.patched == patched + 1
        self.passed(self.provider + ': real workflow semantic change holds the original publication; UI preview is read-only and explicit review updates its existing remote ID')

    def conflict_and_stop(self, page, receipt, rid):
        self.open_calendar(page, receipt['tripId'])
        worker = self.application.extensions['calendar_publish']
        remote_id = self.publication(rid)['remote_id']
        raw = self.remote.records[remote_id]
        raw['subject' if self.provider == 'microsoft' else 'summary'] = '合成云端独立修改'
        raw['@odata.etag' if self.provider == 'microsoft' else 'etag'] = '"external-edit"'
        created, patched = self.remote.created, self.remote.patched
        worker.process(rid)
        assert self.publication(rid)['status'] == 'conflict'
        assert (self.remote.created, self.remote.patched) == (created, patched)
        button(page, '刷新同步状态').click()
        before, calls = self.snapshot(), len(self.remote.calls)
        with page.expect_response(lambda r: urlsplit(r.url).path == CP + '/publications/' + rid + '/conflict-preview') as pending:
            button(page, '核对云端修改：合成东京协作旅行').click()
        assert pending.value.status == 200
        assert pending.value.json()['remote']['title'] == '合成云端独立修改'
        assert self.snapshot() == before and all(c[0] == 'GET' for c in self.remote.calls[calls:])
        expect(page.get_by_text('合成云端独立修改', exact=True)).to_be_visible()
        with page.expect_response(lambda r: urlsplit(r.url).path == CP + '/publications/' + rid + '/conflict-confirm') as pending:
            button(page, '确认用本地内容更新').click()
        assert pending.value.status == 200
        assert (self.remote.created, self.remote.patched) == (created, patched)
        worker.process(rid)
        assert self.publication(rid)['status'] == 'published' and self.publication(rid)['remote_id'] == remote_id
        assert (self.remote.created, self.remote.patched) == (created, patched + 1)
        button(page, '刷新同步状态').click()
        remote_before = deepcopy(self.remote.records)
        with page.expect_response(lambda r: urlsplit(r.url).path == CP + '/publications/' + rid + '/pause') as pending:
            button(page, '停止同步：合成东京协作旅行').click()
        assert pending.value.status == 200 and self.publication(rid)['status'] == 'paused'
        worker.process(rid)
        assert self.remote.records == remote_before
        with page.expect_response(lambda r: urlsplit(r.url).path == CP + '/publications/' + rid + '/resume') as pending:
            button(page, '恢复同步：合成东京协作旅行').click()
        assert pending.value.status == 200
        worker.process(rid)
        assert self.publication(rid)['status'] == 'published' and self.remote.records == remote_before
        self.passed(self.provider + ': external conflict needs explicit read/compare/confirm; stopping preserves the remote event and resuming creates no duplicate')

    def permissions_and_identity(self, browser, page, receipt, rid, place):
        ctx = page.context
        self.open_calendar(page, receipt['tripId'])
        engine = self.application.extensions['cloud_accounts']
        # Synthetic grant revocation: no real account or provider is changed.
        read_scope = ('User.Read Calendars.Read Tasks.ReadWrite' if self.provider == 'microsoft' else
            'https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/tasks')
        with engine.db() as con:
            con.execute('UPDATE cloud_accounts SET tokens=? WHERE id=?', (engine.encrypt({
                'access_token': 'synthetic-token', 'refresh_token': 'synthetic-refresh', 'scope': read_scope,
                'expires_at': time.time() + 3600}), 'account-mine'))
        calls = len(self.remote.calls)
        self.application.extensions['calendar_publish'].process(rid)
        assert self.publication(rid)['status'] == 'needs_authorization'
        assert not any(c[0] in {'POST', 'PATCH', 'DELETE'} for c in self.remote.calls[calls:])
        button(page, '刷新同步状态').click()
        expect(button(page, '开启日历写入：合成账户')).to_be_visible()
        partner, child = self.context(browser, 2), self.context(browser, None)
        try:
            partner_state = self.state(partner, receipt['id'])
            assert partner_state['publications'] == []
            assert all(s['id'] != 'source-mine' for s in partner_state['sources'])
            self.get(partner, PLACE + '/' + place['id'], 404)
            self.write(partner, 'POST', CP + '/publications/' + rid + '/pause', {}, 404)
            invitation = self.write(ctx, 'POST', '/api/spaces/invitations', {}, 201)['invitation']
            entry = self.write(ctx, 'POST', '/api/spaces/redeem', {'invitation': invitation,
                'name': '合成旅行隔离家庭', 'slug': 'trip-coordination-' + self.provider,
                'MEMBER1_PASSWORD': 'testing-password-one', 'MEMBER2_PASSWORD': 'testing-password-two'}, 201)['entry']
            assert child.request.get(self.base + entry).status == 200
            self.login(child)
            assert self.get(child, '/api/me')['user']['householdId'] != 'default'
            self.get(child, CP + '/journeys/' + receipt['id'], 404)
            self.get(child, PLACE + '/' + place['id'], 404)
            self.write(child, 'POST', CP + '/publications/' + rid + '/pause', {}, 404)
        finally:
            partner.close()
            child.close()
        held = []
        endpoint = self.base + CP + '/journeys/' + receipt['id']

        def delay_read(handler):
            response = handler.fetch(max_redirects=0)
            assert response.status == 200 and 'set-cookie' not in response.headers
            held.append((handler, response))

        page.route(endpoint, delay_read)
        button(page, '刷新同步状态').click()
        self.settle(page, lambda: bool(held))
        self.login(ctx, 2)
        assert self.get(ctx, '/api/me')['user']['id'] == 'member2'
        for handler, response in held:
            handler.fulfill(response=response)
        page.unroute(endpoint, delay_read)
        expect(page.get_by_label('选择日历：本人合成旅行日历 · 合成账户', exact=True)).to_have_count(0)
        expect(page.locator('body')).not_to_contain_text('本人合成旅行日历')
        self.passed(self.provider + ': revoked write scope blocks worker writes; partner/foreign household cannot control private records and late old-member reads conceal sources')

    def run_scenarios(self, browser):
        with self.flow(browser) as (ctx, page):
            receipt = self.create_trip_ui(page)
            place = self.places_roundtrip(page, receipt)
            rid = self.publish_unknown(page, receipt)
            self.ordinary_reschedule(page, receipt, rid, place)
            self.timing_review(page)
            self.conflict_and_stop(page, receipt, rid)
            self.permissions_and_identity(browser, page, receipt, rid, place)
            assert self.report['modelCalls'] == []


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
    out = Path(__file__).resolve().parents[1] / 'test-results' / ('expo-trip-coordination-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], screenshots=[],
        head=head, tree=evidence['sourceTree'], buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(out / 'executed-harness.py'),
        sourceHashesBefore=hashes(), bundleHashesBefore=bundle_hashes(), productionWrites=0,
        realCloud=False, realAI=False, physicalTelevision=False, providers=[],
        scope='Actual local Flask/SQLite/Edge/member sessions/CSRF. Only calendar HTTP is fake. Advanced semantic edits are real API setup, not Expo editing acceptance. Screenshots cover visible inner scroll positions only.')
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
                        folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='expo-trip-coordination-')))
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
