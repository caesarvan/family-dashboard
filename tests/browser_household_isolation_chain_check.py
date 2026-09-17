"""Six ordered checkpoints in one real synthetic two-household environment.

No successful business DTO is mocked. Media provider completions are synthetic;
the application persists and serves actual sanitized JPEG/PDF bytes. A failed
checkpoint leaves dependent checkpoints not_run. Never run against production.
"""
import argparse
from contextlib import ExitStack, closing
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
import time
import traceback
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
import browser_expo_finance_check as finance_fixture
import browser_expo_household_members_check as members_fixture
import browser_expo_trip_recap_check as recap_fixture
from browser_expo_finance_check import button, sha, visibility

STEPS = ('identities', 'private_records', 'explicit_sharing', 'revoke_two_sessions',
         'old_sessions_and_late_bytes', 'fresh_login')
ACCOUNTS = '/api/finance-accounts'
MEMBERS = '/api/members'
DAY = '2026-09-18'
OPERATION = 'c' * 32
PRIVATE = 'D链 A2 私人合成记录'
SHARED = 'D链 A2 明确共享记录'


def digest(value):
    return hashlib.sha256(repr(value).encode('utf-8')).hexdigest()


class Run(recap_fixture.Run):
    # Reuse only focused, already real-response helpers, never their scenario
    # runners/flow() resets. All six checkpoints share these exact databases.
    members = members_fixture.Run.members
    member = staticmethod(members_fixture.Run.member)
    ready = members_fixture.Run.ready
    open_members = members_fixture.Run.open_members
    choose = members_fixture.Run.choose
    confirm_write = members_fixture.Run.confirm_write
    unknown_ready = members_fixture.Run.unknown_ready
    end_review = members_fixture.Run.end_review
    trace = members_fixture.Run.trace
    watch = members_fixture.Run.watch

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.members_started = time.monotonic()
        self.members_timeline = self.report.setdefault('timeline', [])
        modules = {'tests/browser_expo_finance_check.py': finance_fixture,
                   'tests/browser_expo_household_members_check.py': members_fixture,
                   'tests/browser_expo_trip_recap_check.py': recap_fixture,
                   'media_images.py': self.images,
                   **{'tests/' + n + '.py': sys.modules[n] for n in
                      ('test_financial_files', 'test_app', 'test_journey_documents', 'test_household_media')}}
        paths = {name: str(Path(module.__file__).resolve()) for name, module in modules.items()}
        for name, path in paths.items():
            assert sha(Path(path)) == sha(self.root / name), name
        paths['tests/browser_household_isolation_chain_check.py'] = str(Path(__file__).resolve())
        self.report['fixtureActualPaths'] = paths
        self.report['fixtureHashes'] = {name: sha(Path(path)) for name, path in paths.items()}
        assert self.report['fixtureHashes']['tests/browser_household_isolation_chain_check.py'] == self.report['harnessSha256']
        self.documents = sys.modules['test_journey_documents']
        self.held_image = []

    def ctx(self, browser, member=None, entry=None):
        ctx = self.context(browser, None)
        self.lifecycle.callback(ctx.close)
        if entry:
            assert ctx.request.get(self.base + entry).status == 200
        if member:
            self.login(ctx, member)
        return ctx

    def get(self, ctx, path, status=200):
        value = super().get(ctx, path, status)
        self.report.setdefault('apiChecks', []).append(dict(method='GET', path=path, status=status))
        return value

    def write(self, ctx, method, path, body, status=200):
        value = super().write(ctx, method, path, body, status)
        self.report.setdefault('apiChecks', []).append(dict(method=method, path=path, status=status))
        return value

    def read_rows(self, path, query, values=()):
        assert path.resolve().is_relative_to(self.folder.resolve()) and path.is_file()
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as con:
            return con.execute(query, values).fetchall()

    def business(self, path):
        names = self.read_rows(path, "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        excluded = {'users', 'member_sessions', 'member_session_browsers', 'attempts', 'audit', 'sqlite_sequence', 'settings'}
        result = {name: digest(self.read_rows(path, 'SELECT * FROM "' + name + '" ORDER BY rowid'))
                  for (name,) in names if name not in excluded}
        result['user_private_fields'] = digest(self.read_rows(path, 'SELECT id,username,name,password FROM users ORDER BY id'))
        result['settings_without_meta'] = digest(self.read_rows(path, "SELECT * FROM settings WHERE id<>'meta' ORDER BY id"))
        result['business_sequences'] = digest(self.read_rows(path, "SELECT name,seq FROM sqlite_sequence WHERE name<>'audit' ORDER BY name"))
        result['schema'] = digest(self.read_rows(path, "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"))
        return result

    def session_state(self, path):
        # last_seen_at is deliberately excluded: reading a session may touch it.
        return {'users': self.read_rows(path, 'SELECT id,household_role,auth_version FROM users ORDER BY id'),
                'sessions': self.read_rows(path, 'SELECT id,owner,auth_version,browser_hash,revoked_at FROM member_sessions ORDER BY id'),
                'browsers': self.read_rows(path, 'SELECT browser_hash,generation FROM member_session_browsers ORDER BY browser_hash')}

    def preserved(self):
        return {'A': self.business(self.database), 'B': self.business(self.other_database),
                'registry': {table: digest(self.read_rows(self.registry, 'SELECT * FROM ' + table + ' ORDER BY rowid'))
                             for table in ('households', 'household_invitations')}}

    def binary(self, ctx, path, status=200, mime=None):
        response = ctx.request.get(self.base + path)
        assert response.status == status, (path, response.status)
        raw = response.body()
        if mime:
            assert response.headers['content-type'].split(';')[0] == mime
            assert 'no-store' in response.headers['cache-control']
        self.report.setdefault('binaryChecks', []).append(dict(path=path, status=response.status,
            bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
        return raw

    def accounts(self, ctx):
        return self.get(ctx, ACCOUNTS + '?asOf=' + DAY + '&status=all')

    def operation(self, ctx):
        return self.get(ctx, ACCOUNTS + '/operations/' + OPERATION)

    def capture(self, page, name, target, width):
        page.set_viewport_size({'width': width, 'height': 844 if width < 1000 else 1000})
        target.scroll_into_view_if_needed()
        page.evaluate('() => document.fonts.ready')
        page.evaluate('() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done)))')
        expect(target).to_be_visible()
        metrics = page.evaluate('() => ({width:innerWidth,scroll:document.documentElement.scrollWidth})')
        assert metrics['scroll'] <= width + 2, metrics
        path = self.out / (name + '.png')
        page.screenshot(path=str(path), full_page=False)
        self.report['screenshots'].append(dict(path=path.name, sha256=sha(path), metrics=metrics,
            scope='Visible viewport only; human visual review is separate.'))

    def identities(self, browser):
        self.a1 = self.ctx(browser, 1)
        family = self.create_family(self.a1)
        self.b1 = self.ctx(browser, 1, family['entry'])
        self.b2 = self.ctx(browser, 2, family['entry'])
        a = self.get(self.a1, '/api/me')['user']; b = self.get(self.b1, '/api/me')['user']
        assert a['id'] == b['id'] == 'member1' and a['householdId'] != b['householdId']
        self.other_database = self.folder / 'data' / 'spaces' / b['householdId'] / 'household.sqlite3'
        self.registry = self.folder / 'data' / 'platform.sqlite3'
        assert self.other_database.is_file() and self.registry.is_file()
        b_before = self.session_state(self.other_database)
        target = self.member(self.members(self.a1))
        self.write(self.a1, 'PATCH', MEMBERS + '/member2/role',
                   {'expectedAuthVersion': target['authVersion'], 'householdRole': 'member'})
        self.a2 = self.ctx(browser, 2); self.a2_second = self.ctx(browser, 2)
        assert self.get(self.a2, '/api/me')['user']['id'] == self.get(self.b2, '/api/me')['user']['id'] == 'member2'
        roster = self.members(self.a2)
        assert all(r['activeSessionCount'] is None and not any(r['capabilities'].values()) for r in roster['members'])
        self.write(self.a2, 'POST', MEMBERS + '/member1/revoke-sessions',
                   {'expectedAuthVersion': self.member(roster, 'member1')['authVersion']}, 403)
        mixed = self.ctx(browser, None, family['entry'])
        cookie = next(c for c in self.a2.cookies() if c['name'] == 'session')
        mixed.add_cookies([cookie])
        self.get(mixed, MEMBERS, 401)
        assert self.session_state(self.other_database) == b_before
        assert self.member(self.members(self.a1))['activeSessionCount'] == 2
        self.report['households'] = {'A': a['householdId'], 'B': b['householdId'],
                                     'memberIdsInBoth': ['member1', 'member2']}

    def private_records(self, _browser):
        def account(ctx, name, cents):
            return self.write(ctx, 'POST', ACCOUNTS, dict(requestId=OPERATION, revision=0, name=name,
                institution='合成机构', kind='asset', currency='CNY', note='仅本地验收',
                valuation={'asOf': DAY, 'amountCents': cents}), 201)
        self.account_a = account(self.a2, PRIVATE, 123456)
        self.account_b = account(self.b2, 'D链 B2 私人合成记录', 765432)
        assert self.account_a['accountId'] != self.account_b['accountId']
        self.journey_a = self.journey(self.a2)
        self.photos_a = self.photos(self.a2, self.journey_a, count=2, member=2, caption=PRIVATE)
        self.places_a = [self.place(self.a2, self.journey_a, name=PRIVATE + str(i)) for i in range(2)]
        self.docs_a = [self.write(self.a2, 'POST', '/api/journey-documents',
            self.documents.payload(self.journey_a['id'], title=PRIVATE + str(i)), 201)['document'] for i in range(2)]
        imports = self.read_rows(self.database, 'SELECT id FROM media_imports WHERE owner=? ORDER BY id', ('member2',))
        assert len(imports) == 1
        self.import_path = '/api/media/imports/' + imports[0][0]
        self.import_result = self.get(self.a2, self.import_path)['import']
        assert self.import_result['counts']['saved'] == 2
        assert self.operation(self.a2)['receipt']['accountId'] == self.account_a['accountId']
        assert self.operation(self.b2)['receipt']['accountId'] == self.account_b['accountId']
        assert self.accounts(self.a1)['accounts'] == [] and not self.operation(self.a1)['found']
        assert not self.operation(self.b1)['found']
        for ctx in (self.a1, self.b1, self.b2):
            self.get(ctx, ACCOUNTS + '/' + self.account_a['accountId'] + '/valuations', 404)
            self.get(ctx, '/api/media/items/' + self.photos_a[0]['id'], 404)
            self.binary(ctx, '/api/media/items/' + self.photos_a[0]['id'] + '/preview', 404)
            self.get(ctx, '/api/journey-places/' + self.places_a[0]['id'], 404)
            self.binary(ctx, self.docs_a[0]['downloadUrl'], 404)
            self.get(ctx, self.import_path, 404)
            assert self.get(ctx, '/api/media/items?scope=visible')['items'] == []
            assert self.get(ctx, '/api/journey-places?scope=visible')['items'] == []
            assert self.get(ctx, '/api/journey-documents')['documents'] == []
        assert [r['name'] for r in self.accounts(self.b2)['accounts']] == ['D链 B2 私人合成记录']
        assert self.binary(self.a2, self.docs_a[0]['downloadUrl'], mime='application/pdf') == self.documents.PDF
        own = self.binary(self.a2, '/api/media/items/' + self.photos_a[0]['id'] + '/preview', mime='image/jpeg')
        assert own.startswith(b'\xff\xd8') and own.endswith(b'\xff\xd9')
        self.report['seedBusinessHashes'] = self.preserved()

    def explicit_sharing(self, browser):
        photo, place, document = self.photos_a[0], self.places_a[0], self.docs_a[0]
        self.photos_a[0] = self.write(self.a2, 'PATCH', '/api/media/items/' + photo['id'],
            dict(revision=photo['revision'], visibility='shared', caption=SHARED))['item']
        self.places_a[0] = self.write(self.a2, 'PATCH', '/api/journey-places/' + place['id'],
            dict(revision=place['revision'], visibility='shared', name=SHARED, coordinateDisclosure='coarse'))['place']
        self.docs_a[0] = self.write(self.a2, 'PATCH', '/api/journey-documents/' + document['id'],
            self.documents.patch_value(document, visibility='shared', title=SHARED))['document']
        visible = self.get(self.a1, self.list_path(self.journey_a))['items']
        assert [p['id'] for p in visible] == [photo['id']]
        places = self.get(self.a1, self.list_path(self.journey_a, 'places'))['items']
        assert len(places) == 1 and places[0]['id'] == place['id'] and not places[0]['canManage']
        assert places[0]['coordinatePrecision'] == 'approximate'
        assert places[0]['coordinates'] == self.places_a[0]['sharedCoordinates']
        assert places[0]['coordinates'] != place['coordinates']
        assert self.binary(self.a1, document['downloadUrl'], mime='application/pdf') == self.documents.PDF
        jpeg_path = '/api/media/items/' + photo['id'] + '/preview'
        assert self.binary(self.a1, jpeg_path, mime='image/jpeg') == self.binary(self.a2, jpeg_path, mime='image/jpeg')
        self.write(self.a1, 'PATCH', '/api/journey-documents/' + document['id'],
                   self.documents.patch_value(self.docs_a[0], title='无权修改'), 403)
        for ctx in (self.a1, self.b2):
            self.get(ctx, '/api/media/items/' + self.photos_a[1]['id'], 404)
            self.get(ctx, '/api/journey-places/' + self.places_a[1]['id'], 404)
            self.binary(ctx, self.docs_a[1]['downloadUrl'], 404)
            self.get(ctx, self.import_path, 404)
        self.binary(self.b2, jpeg_path, 404); self.binary(self.b2, document['downloadUrl'], 404)
        assert self.accounts(self.a1)['accounts'] == []
        tv = self.ctx(browser)
        pairing = tv.request.post(self.base + '/api/pair/start', data={}).json()
        self.write(self.a1, 'POST', '/api/pair/approve', {'code': pairing['code'], 'name': 'D链合成电视'})
        assert tv.request.post(self.base + '/api/pair/poll', data={'secret': pairing['secret']}).json()['approved']
        for path in (MEMBERS, ACCOUNTS, '/api/journey-places', self.import_path):
            self.get(tv, path, 403)
        self.binary(tv, document['downloadUrl'], 403)
        self.admin_page = self.a1.new_page(); self.page = self.admin_page
        self.admin_page.goto(self.base + '/app/map')
        expect(self.admin_page.get_by_role('heading', name='足迹地图', exact=True)).to_be_visible(timeout=15000)
        location = button(self.admin_page, '打开地点：' + SHARED)
        expect(location).to_be_enabled(timeout=15000); location.click()
        expect(self.admin_page.locator('body')).not_to_contain_text(PRIVATE)
        self.capture(self.admin_page, 'shared-map-1280', location, 1280)
        self.before_revoke = self.preserved()
        self.b_auth = self.session_state(self.other_database)

    def revoke_two_sessions(self, _browser):
        self.target_page = self.a2.new_page(); self.page = self.target_page
        self.open_panel(self.target_page, self.journey_a)
        self.old_blob = self.open_photo(self.target_page)
        self.old_csrf = self.get(self.a2, '/api/me')['csrf']
        def hold(route):
            response = route.fetch(max_redirects=0); raw = response.body()
            assert response.status == 200 and response.headers['content-type'].startswith('image/jpeg')
            assert len(self.held_image) == 0
            self.held_image.append(dict(route=route, status=response.status, headers=response.headers, raw=raw))
            self.trace('real-jpeg-held', bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        self.target_page.route(self.base + '/api/media/items/*/preview', hold, times=1)
        button(self.target_page, '刷新旅行回顾').click()
        self.settle(self.target_page, lambda: len(self.held_image) == 1)
        visibility(self.target_page, True); self.assert_cleared(self.target_page)
        self.assert_blob_revoked(self.target_page, self.old_blob)
        self.page = self.admin_page; self.watch(self.admin_page); self.open_members(self.admin_page)
        target = self.member(self.members(self.a1)); assert target['activeSessionCount'] == 2
        self.target_before = target
        self.audit_before = self.read_rows(self.database, 'SELECT * FROM audit ORDER BY id')
        self.auth_before = self.session_state(self.database)
        self.choose(self.admin_page, 'revoke', target)
        result = self.confirm_write(self.admin_page, 'revoke', target, drop=True)
        assert result['result']['revoked'] == 2 and result['result']['ok'] is True
        self.unknown_ready(self.admin_page)
        reads = self.count_requests('GET', MEMBERS)
        self.capture(self.admin_page, 'revoke-unknown-390', self.admin_page.get_by_test_id('members-unknown'), 390)
        assert self.count_requests('GET', MEMBERS) == reads, 'Unknown state performed an implicit member read'
        self.end_review(self.admin_page)
        current = self.member(self.members(self.a1))
        assert current['authVersion'] == target['authVersion'] + 1 and current['activeSessionCount'] == 0
        assert current['householdRole'] == 'member'
        assert self.count_requests('POST', MEMBERS + '/member2/revoke-sessions') == 1
        audit = self.read_rows(self.database, 'SELECT * FROM audit ORDER BY id')
        assert audit[:-1] == self.audit_before and len(audit) == len(self.audit_before) + 1
        assert self.read_rows(self.database, 'SELECT action,target FROM audit ORDER BY id DESC LIMIT 1') == [('household_member_sessions_revoke', 'member2')]
        after = self.session_state(self.database)
        old_sessions = {r[0]: r for r in self.auth_before['sessions']}
        assert len(old_sessions) == len(after['sessions'])
        for row in after['sessions']:
            prior = old_sessions[row[0]]
            assert row[:4] == prior[:4]
            if row[1] == 'member2':
                assert row[4] is not None
            else:
                assert row == prior
        target_hashes = {r[3] for r in old_sessions.values() if r[1] == 'member2'}
        generations = dict(self.auth_before['browsers'])
        assert all(g == generations[k] + (k in target_hashes) for k, g in after['browsers'])
        assert self.preserved() == self.before_revoke and self.session_state(self.other_database) == self.b_auth

    def old_sessions_and_late_bytes(self, _browser):
        paths = [MEMBERS, ACCOUNTS, ACCOUNTS + '/' + self.account_a['accountId'] + '/valuations',
                 ACCOUNTS + '/operations/' + OPERATION, '/api/media/items/' + self.photos_a[0]['id'],
                 '/api/media/items/' + self.photos_a[0]['id'] + '/preview', '/api/journey-places',
                 self.docs_a[0]['downloadUrl'], self.import_path]
        for ctx in (self.a2, self.a2_second):
            for path in paths:
                response = ctx.request.get(self.base + path)
                assert response.status == 401, (path, response.status)
                self.report.setdefault('apiChecks', []).append(dict(method='GET', path=path, status=response.status))
            denied = ctx.request.patch(self.base + '/api/media/items/' + self.photos_a[1]['id'],
                data={'revision': self.photos_a[1]['revision'], 'caption': '禁止保存'},
                headers={'X-CSRF-Token': self.old_csrf, 'Origin': self.base})
            assert denied.status == 401
        held = self.held_image.pop()
        held['route'].fulfill(status=held['status'], headers=held['headers'], body=held['raw'])
        self.trace('late-real-jpeg-released-after-revoke')
        self.target_page.evaluate('() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done)))')
        self.assert_cleared(self.target_page)
        self.assert_blob_revoked(self.target_page, self.old_blob)
        me_reads = []
        def observe(route):
            assert route.request.method == 'GET'
            response = route.fetch(max_redirects=0); raw = response.body()
            assert response.status == 200 and len(me_reads) < 32
            me_reads.append(json.loads(raw))
            route.fulfill(status=response.status, headers=response.headers, body=raw)
        self.target_page.route(self.base + '/api/me', observe)
        try:
            self.target_page.bring_to_front(); visibility(self.target_page, False)
            self.target_page.evaluate("window.dispatchEvent(new Event('focus'))")
            self.settle(self.target_page, lambda: bool(me_reads))
            assert any(value['user'] is None for value in me_reads)
            expect(self.target_page.get_by_test_id('trip-recap-panel')).to_have_count(0, timeout=15000)
            expect(self.target_page.locator('body')).not_to_contain_text(PRIVATE)
        finally:
            self.target_page.unroute(self.base + '/api/me', observe)
        assert self.preserved() == self.before_revoke and self.session_state(self.other_database) == self.b_auth
        assert self.get(self.a1, '/api/me')['user']['id'] == self.get(self.b1, '/api/me')['user']['id'] == 'member1'
        assert self.get(self.b2, '/api/me')['user']['id'] == 'member2'
        self.report['revokeProof'] = {'revokedSessions': 2, 'versionBefore': self.target_before['authVersion'],
            'versionAfter': self.member(self.members(self.a1))['authVersion'], 'oldCookieDeniedRequests': len(paths) * 2,
            'oldCookieDeniedWrites': 2, 'businessHashes': self.preserved(), 'foreignAuthUnchanged': True}

    def fresh_login(self, _browser):
        self.login(self.a2, 2)
        assert self.get(self.a2, '/api/me')['user']['id'] == 'member2'
        roster = self.members(self.a2)
        assert self.member(roster)['householdRole'] == 'member'
        assert all(r['activeSessionCount'] is None and not any(r['capabilities'].values()) for r in roster['members'])
        assert self.operation(self.a2)['receipt']['accountId'] == self.account_a['accountId']
        assert self.operation(self.b2)['receipt']['accountId'] == self.account_b['accountId']
        assert [r['name'] for r in self.accounts(self.a2)['accounts']] == [PRIVATE]
        assert self.get(self.a2, self.import_path)['import']['counts'] == self.import_result['counts']
        assert self.get(self.a2, self.import_path)['import']['results'] == self.import_result['results']
        assert len(self.get(self.a2, self.list_path(self.journey_a))['items']) == 2
        assert len(self.get(self.a2, self.list_path(self.journey_a, 'places'))['items']) == 2
        assert self.binary(self.a2, self.docs_a[1]['downloadUrl'], mime='application/pdf') == self.documents.PDF
        assert self.accounts(self.a1)['accounts'] == [] and not self.operation(self.a1)['found']
        self.binary(self.a1, self.docs_a[1]['downloadUrl'], 404)
        self.binary(self.b2, self.docs_a[0]['downloadUrl'], 404)
        self.page = self.target_page; self.target_page.bring_to_front()
        self.open_finance(self.target_page)
        button(self.target_page, '我的资产账户').click()
        expect(button(self.target_page, '查看账户 ' + PRIVATE)).to_be_enabled(timeout=15000)
        self.capture(self.target_page, 'fresh-owner-account-390', button(self.target_page, '查看账户 ' + PRIVATE), 390)
        assert self.member(self.members(self.a1))['activeSessionCount'] == 1
        assert self.preserved() == self.before_revoke and self.session_state(self.other_database) == self.b_auth
        assert self.count_requests('POST', MEMBERS + '/member2/revoke-sessions') == 1

    @classmethod
    def run_chain(cls, root, bundle, report, out, browser):
        report['checkpointResults'] = [{'name': name, 'status': 'not_run'} for name in STEPS]
        folder = None
        try:
            with ExitStack() as resources:
                folder = Path(resources.enter_context(tempfile.TemporaryDirectory(prefix='household-isolation-chain-')))
                report['temporaryDirectory'] = str(folder)
                run = cls(root, bundle, folder, report, out, resources)
                for result in report['checkpointResults']:
                    started = time.monotonic()
                    try:
                        getattr(run, result['name'])(browser)
                        assert not report['pageErrors'] and not report['externalRequests']
                        result['status'] = 'passed'; run.passed(result['name'])
                    except Exception:
                        result['status'] = 'failed'; result['failure'] = traceback.format_exc()
                        (out / (result['name'] + '-failure.txt')).write_text(result['failure'], encoding='utf-8')
                        if run.page and not run.page.is_closed():
                            try:
                                run.page.screenshot(path=str(out / (result['name'] + '-failure.png')), full_page=False)
                                (out / (result['name'] + '-failure-aria.txt')).write_text(run.page.locator('body').aria_snapshot(), encoding='utf-8')
                            except Exception as capture_error:
                                result['failureCaptureError'] = repr(capture_error)
                        raise
                    finally:
                        result['seconds'] = round(time.monotonic() - started, 3)
        finally:
            report['temporaryFixtureRemoved'] = folder is not None and not folder.exists()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-harness-head', required=True); parser.add_argument('--expected-harness-sha256', required=True)
    parser.add_argument('--source-root', required=True, type=Path); parser.add_argument('--expected-head', required=True)
    parser.add_argument('--bundle', required=True, type=Path); parser.add_argument('--expected-build-evidence', required=True)
    args = parser.parse_args(); root, bundle = args.source_root.resolve(), args.bundle.resolve()
    assert all(re.fullmatch('[a-f0-9]{40}', v) for v in (args.expected_head, args.expected_harness_head))
    assert all(re.fullmatch('[a-f0-9]{64}', v) for v in (args.expected_build_evidence, args.expected_harness_sha256))
    harness_root = Path(__file__).resolve().parents[1]
    def command_git(directory, *command): return subprocess.check_output(['git', '--no-replace-objects', *command], cwd=directory, text=True).strip()
    def git(*command): return command_git(root, *command)
    def harness_git(*command): return command_git(harness_root, *command)
    head = git('rev-parse', 'HEAD'); harness_head = harness_git('rev-parse', 'HEAD')
    assert head == args.expected_head and harness_head == args.expected_harness_head
    assert not git('status', '--porcelain=v1') and not harness_git('status', '--porcelain=v1')
    assert sha(Path(__file__)) == args.expected_harness_sha256
    own_names = ('tests/browser_household_isolation_chain_check.py', 'docs/HOUSEHOLD-ISOLATION-CHAIN.md')
    def harness_hashes(): return {name: sha(harness_root / name) for name in own_names}
    evidence_path = bundle.parent / 'build-evidence.json'; assert sha(evidence_path) == args.expected_build_evidence
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    assert evidence['sourceHead'] == head and evidence['sourceTree'] == git('rev-parse', 'HEAD^{tree}')
    names = subprocess.check_output(['git', '--no-replace-objects', 'ls-files', '-z'], cwd=root).decode('utf-8').rstrip('\0').split('\0')
    def hashes(): return {name: sha(root / name) for name in names}
    def exports(): return {p.relative_to(bundle).as_posix(): sha(p) for p in bundle.rglob('*') if p.is_file()}
    assert exports() == evidence['files'] and all(sha(root / name) == value for name, value in evidence['inputFiles'].items())
    out = harness_root / 'test-results' / ('household-isolation-chain-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True); shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], screenshots=[], head=head, tree=evidence['sourceTree'],
        sourceRoot=str(root), harnessRoot=str(harness_root), harnessHead=harness_head, harnessTree=harness_git('rev-parse', 'HEAD^{tree}'),
        harnessSourceHashesBefore=harness_hashes(), harnessPathPresentInApplicationHead=own_names[0] in names,
        buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(out / 'executed-harness.py'), sourceHashesBefore=hashes(), bundleHashesBefore=exports(),
        requestedChecks=len(STEPS), productionWrites=0, realPersonalData=False, realFinancialData=False, realCloud=False, realAI=False, physicalTelevision=False,
        syntheticMediaProvider=True, temporaryFixtureRemoved=False, command=sys.argv,
        scope='One continuous synthetic two-household Flask/SQLite/HTTPS/Edge fixture, six dependent checkpoints. Synthetic media provider completions; real business DTOs and file bytes. Visibility/window focus events are simulated; one real JPEG response is held across revocation. Three viewport captures require separate human review. No join/leave/global identity/cloud or physical TV acceptance.')
    original_connect = socket.socket.connect
    def local_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
            report['externalRequests'].append({'kind': 'non-loopback socket'}); raise AssertionError('External network forbidden')
        return original_connect(sock, address)
    try:
        with patch.object(socket.socket, 'connect', local_connect), sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            try:
                Run.run_chain(root, bundle, report, out, browser)
                assert len(report['checks']) == len(STEPS) and len(report['screenshots']) == 3
                assert len(report['fixtureHashes']) == 9 and not report['pageErrors'] and not report['externalRequests']; report['passed'] = True
            finally: browser.close()
    except Exception:
        report['passed'] = False; report['failure'] = traceback.format_exc(); print(report['failure'], flush=True)
    finally:
        report['sourceHashesAfter'] = hashes(); report['bundleHashesAfter'] = exports()
        report['sourceUnchanged'] = report['sourceHashesBefore'] == report['sourceHashesAfter']; report['bundleUnchanged'] = report['bundleHashesBefore'] == report['bundleHashesAfter']
        report['sourceStillFrozen'] = git('rev-parse', 'HEAD') == head and not git('status', '--porcelain=v1')
        report['harnessSourceHashesAfter'] = harness_hashes()
        report['harnessStillFrozen'] = harness_git('rev-parse', 'HEAD') == harness_head and not harness_git('status', '--porcelain=v1') and report['harnessSourceHashesBefore'] == report['harnessSourceHashesAfter']
        report['fixtureHashesAfter'] = {name: sha(Path(path)) for name, path in report.get('fixtureActualPaths', {}).items()}
        report['fixturesUnchanged'] = len(report.get('fixtureHashes', {})) == 9 and report['fixtureHashesAfter'] == report['fixtureHashes']
        report.setdefault('temporaryFixtureRemoved', False)
        report['passed'] = report['passed'] and all(report[k] for k in ('sourceUnchanged', 'bundleUnchanged', 'sourceStillFrozen', 'harnessStillFrozen', 'fixturesUnchanged', 'temporaryFixtureRemoved'))
        with (out / 'result.json').open('x', encoding='utf-8') as stream: stream.write(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'report': str(out / 'result.json')}, ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    raise SystemExit(main())
