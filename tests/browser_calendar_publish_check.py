"""Actual browser calendar publication UI with fake provider HTTP only.

Every household/account/grant is synthetic and temporary. External browser
requests are denied. Queue processing invokes the real provider adapters with
the transport fixture; it never calls Microsoft or Google over the network.
"""
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import create_app
from test_calendar_publish import Remote
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server, WSGIRequestHandler


class Quiet(WSGIRequestHandler):
    def log(self, *_args, **_kwargs):
        pass


def run_provider(browser, provider, output):
    with tempfile.TemporaryDirectory() as temporary:
        remote = Remote()
        app = create_app({'TESTING': True, 'SECRET_KEY': 'browser-calendar-' + provider,
                          'DATA_DIR': temporary, 'SESSION_COOKIE_SECURE': False,
                          'PUBLIC_ORIGIN': 'http://localhost', 'MEMBER1_PASSWORD': 'testing-password-one',
                          'MEMBER2_PASSWORD': 'testing-password-two', 'GOOGLE_CLIENT_ID': 'test-client',
                          'GOOGLE_CLIENT_SECRET': 'test-secret', 'MICROSOFT_CLIENT_ID': 'test-client',
                          'MICROSOFT_CLIENT_SECRET': 'test-secret', 'CLOUD_TRANSPORT': remote.transport})
        accounts = app.extensions['cloud_accounts']
        queue = app.extensions['calendar_publish']
        read_scope = 'User.Read Calendars.Read Tasks.ReadWrite' if provider == 'microsoft' else 'https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/tasks'
        write_scope = 'User.Read Calendars.ReadWrite Tasks.ReadWrite' if provider == 'microsoft' else read_scope + ' https://www.googleapis.com/auth/calendar.events'
        with accounts.db() as con:
            for account_id, owner, display in [('mine', 'member1', '本人合成账户'), ('partner', 'member2', 'PARTNER_ACCOUNT_MUST_NOT_APPEAR')]:
                token = accounts.encrypt({'access_token': 'synthetic-token', 'refresh_token': 'synthetic-refresh',
                                          'scope': read_scope, 'expires_at': time.time() + 3600})
                con.execute('INSERT INTO cloud_accounts(id,owner,provider,client_id,subject,name,email,tokens) VALUES(?,?,?,?,?,?,?,?)',
                            (account_id, owner, provider, 'test-client', 'subject-' + account_id, display, account_id + '@synthetic.invalid', token))
                con.execute('INSERT INTO cloud_sources(id,account_id,remote_id,kind,name,owner) VALUES(?,?,?,?,?,?)',
                            ('source-' + account_id, account_id, 'calendar-' + account_id, 'calendar',
                             '本人旅行日历' if owner == 'member1' else 'PARTNER_CALENDAR_MUST_NOT_APPEAR', owner))
        client = app.test_client()
        assert client.post('/api/login', json={'username': 'member1', 'password': 'testing-password-one'}).status_code == 200
        headers = {'X-CSRF-Token': client.get('/api/me').json['csrf']}
        plan = {'title': '京都 · 合成旅行计划', 'start': '2026-10-01', 'end': '2026-10-04',
                'budget': 2000000, 'destinations': [{'city': '京都', 'country': '日本'}],
                'international': True, 'memberIds': ['member1', 'member2'], 'checklist': [], 'shopping': [], 'segments': []}
        preview = client.post('/api/journeys/preview', json={'plan': plan}, headers=headers)
        assert preview.status_code == 200, preview.json
        created = client.post('/api/journeys/apply', json={'previewToken': preview.json['previewToken'], 'idempotencyKey': 'browser-calendar-trip'}, headers=headers)
        assert created.status_code == 201, created.json
        journey_id, trip_id = created.json['id'], created.json['tripId']
        server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=Quiet)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f'http://127.0.0.1:{server.server_port}'
        context = browser.new_context(viewport={'width': 1365, 'height': 1000})
        blocked_external = []
        def only_local(route):
            if urlsplit(route.request.url).hostname in {'127.0.0.1', 'localhost'}:
                route.continue_()
            else:
                blocked_external.append(route.request.url)
                route.abort()
        context.route('**/*', only_local)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        try:
            page.goto(origin)
            page.locator('[name=password]').fill('testing-password-one')
            page.locator('#login-form button[type=submit]').click()
            page.wait_for_function('() => typeof JourneyUI === "object" && typeof CalendarPublish === "object" && typeof data !== "undefined" && data !== null')
            page.evaluate('(tripId) => JourneyUI.open(tripId)', trip_id)
            expect(page.locator('.journey-detail-top')).to_be_visible()
            page.locator('[data-journey=cloud-calendar]').click()
            expect(page.locator('#calendar-publish-root')).to_be_visible()
            expect(page.locator('#calendar-publish-form option')).to_have_count(1)
            expect(page.locator('#calendar-publish-form option')).to_contain_text('本人旅行日历')
            expect(page.locator('#calendar-publish-root')).not_to_contain_text('PARTNER_')
            expect(page.locator('[data-cp=authorize]')).to_have_count(1)
            expect(page.locator('#calendar-publish-root')).to_contain_text('开启日历写入')
            page.locator('#calendar-publish-form [type=submit]').click()
            expect(page.locator('#dialog')).to_contain_text('此账户尚未授予日历写权限')
            expect(page.locator('#dialog')).to_contain_text('2026-10-01 至 2026-10-04 · 全天')
            assert remote.calls == []
            with accounts.db() as con:
                assert con.execute('SELECT count(*) FROM calendar_publications').fetchone()[0] == 0
            page.locator('[data-cp=confirm]').click()
            expect(page.locator('#calendar-publications')).to_contain_text('等待日历写权限')
            with accounts.db() as con:
                publication = dict(con.execute('SELECT * FROM calendar_publications').fetchone())
            rid = publication['id']
            queue.process(rid)
            assert remote.calls == []
            page.screenshot(path=str(output / f'calendar-publish-{provider}-needs-permission.png'))
            # Simulate the user's completed OAuth grant in the temporary account.
            # Do not click authorization or navigate to any real provider page.
            with accounts.db() as con:
                old = con.execute("SELECT tokens FROM cloud_accounts WHERE id='mine'").fetchone()[0]
                token = accounts.decrypt(old)
                token['scope'] = write_scope
                con.execute("UPDATE cloud_accounts SET tokens=? WHERE id='mine'", (accounts.encrypt(token),))
            page.locator('[data-cp=retry]').click()
            expect(page.locator('#calendar-publications')).to_contain_text('等待发布')
            queue.process(rid)
            # Verify the UI's actual polling; don't reload to manufacture status.
            expect(page.locator('#calendar-publications')).to_contain_text('已发布 · 持续同步', timeout=9000)
            assert remote.created == 1 and remote.patched == 0
            page.locator('[data-cp=pause]').click()
            expect(page.locator('#calendar-publications')).to_contain_text('已停止自动发布')
            expect(page.locator('[data-cp=resume]')).to_be_visible()
            with accounts.db() as con:
                row = con.execute('SELECT * FROM entities WHERE id=?', (publication['entity_id'],)).fetchone()
                event = json.loads(row['data'])
                event['title'] = '京都 · 本地调整后的旅行'
                con.execute('UPDATE entities SET data=?,revision=revision+1 WHERE id=?', (json.dumps(event), row['id']))
            queue.process(rid)
            assert remote.patched == 0
            page.locator('[data-cp=resume]').click()
            expect(page.locator('#calendar-publications')).to_contain_text('等待发布')
            queue.process(rid)
            page.locator('[data-cp=refresh]').click()
            expect(page.locator('#calendar-publications')).to_contain_text('已发布 · 持续同步')
            assert remote.created == 1 and remote.patched == 1
            with accounts.db() as con:
                publication = dict(con.execute('SELECT * FROM calendar_publications WHERE id=?', (rid,)).fetchone())
            remote_record = remote.records[publication['remote_id']]
            etag_field = '@odata.etag' if provider == 'microsoft' else 'etag'
            title_field = 'subject' if provider == 'microsoft' else 'summary'
            remote_record[etag_field], remote_record[title_field] = '"browser-external-v1"', '云端用户调整的标题'
            queue.process(rid)
            page.locator('[data-cp=refresh]').click()
            expect(page.locator('#calendar-publications')).to_contain_text('云端变更 · 已暂停')
            assert remote.patched == 1
            page.locator('[data-cp=conflict-preview]').click()
            expect(page.locator('#dialog')).to_contain_text('核对云端修改')
            expect(page.locator('#dialog')).to_contain_text('京都 · 本地调整后的旅行')
            expect(page.locator('#dialog')).to_contain_text('云端用户调整的标题')
            expect(page.locator('#dialog').get_by_text('2026-10-01 至 2026-10-04 · 全天', exact=True)).to_have_count(2)
            expect(page.locator('#dialog')).not_to_contain_text('2026-10-05')
            expect(page.locator('#dialog')).not_to_contain_text('T00:00:00')
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.querySelector("#dialog").scrollWidth <= document.querySelector("#dialog").clientWidth + 2')
            page.screenshot(path=str(output / f'calendar-publish-{provider}-conflict-phone.png'))
            page.locator('[data-cp=conflict-confirm]').click()
            expect(page.locator('#calendar-publications')).to_contain_text('等待发布')
            assert remote.patched == 1  # UI confirmation enqueues; worker performs conditional PATCH.
            queue.process(rid)
            page.locator('[data-cp=refresh]').click()
            expect(page.locator('#calendar-publications')).to_contain_text('已发布 · 持续同步')
            assert remote_record[title_field] == '京都 · 本地调整后的旅行'
            assert remote.patched == 2
            # A second cloud edit after preview is not silently overwritten.
            remote_record[etag_field], remote_record[title_field] = '"browser-external-v2"', '云端第二次修改'
            queue.process(rid)
            page.locator('[data-cp=refresh]').click()
            page.locator('[data-cp=conflict-preview]').click()
            expect(page.locator('#dialog')).to_contain_text('云端第二次修改')
            remote_record[etag_field], remote_record[title_field] = '"browser-after-preview"', '预览以后再次改变的云端内容'
            page.locator('[data-cp=conflict-confirm]').click()
            expect(page.locator('#calendar-publications')).to_contain_text('等待发布')
            queue.process(rid)
            page.locator('[data-cp=refresh]').click()
            expect(page.locator('#calendar-publications')).to_contain_text('云端变更 · 已暂停')
            assert remote.patched == 2
            page.locator('[data-cp=conflict-preview]').click()
            expect(page.locator('#dialog')).to_contain_text('预览以后再次改变的云端内容')
            page.locator('[data-cp=pause]').click()
            expect(page.locator('#calendar-publications')).to_contain_text('已停止自动发布')
            assert remote_record[title_field] == '预览以后再次改变的云端内容'
            # OAuth scope is not proof of write access to an individual calendar.
            with accounts.db() as con:
                con.execute('INSERT INTO cloud_sources(id,account_id,remote_id,kind,name,owner) VALUES(?,?,?,?,?,?)',
                            ('read-only-target', 'mine', 'calendar-acl', 'calendar', '本人选中的只读共享日历', 'member1'))
            page.locator('[data-cp=refresh]').click()
            page.locator('#calendar-publish-form [name=sourceId]').select_option('read-only-target')
            page.locator('#calendar-publish-form [type=submit]').click()
            page.locator('[data-cp=confirm]').click()
            expect(page.locator('#calendar-publications')).to_contain_text('等待发布')
            with accounts.db() as con:
                restricted_id = con.execute("SELECT id FROM calendar_publications WHERE source_id='read-only-target'").fetchone()[0]
            remote.acl = False
            queue.process(restricted_id)
            page.locator('[data-cp=refresh]').click()
            expect(page.locator('#calendar-publications')).to_contain_text('该日历无编辑权限')
            assert remote.created == 1
            remote.acl = True
            page.locator('[data-cp=retry]').click()
            expect(page.locator('#calendar-publications')).to_contain_text('等待发布')
            queue.process(restricted_id)
            page.locator('[data-cp=refresh]').click()
            expect(page.locator('#calendar-publications')).to_contain_text('已发布 · 持续同步')
            assert remote.created == 2
            assert not any(call[0] == 'DELETE' for call in remote.calls)
            assert all('attendees' not in (call[2] or {}) for call in remote.calls if call[0] in {'POST', 'PATCH'})
            assert not errors, errors
            assert not blocked_external, blocked_external
            return {'provider': provider, 'journeyDetailEntry': 'passed', 'ownSourcesOnly': 'passed',
                    'missingWriteGrant': 'passed', 'previewNoQueueOrRemoteWrite': 'passed',
                    'confirmQueue': 'passed', 'polledPublishedState': 'passed', 'pauseResume': 'passed',
                    'conflictComparisonAndConfirm': 'passed', 'conflictAfterPreview': 'protected',
                    'allDayInclusiveComparisonDates': 'passed',
                    'keepRemoteAndPause': 'passed', 'calendarAclDenialAndRetry': 'passed',
                    'phoneOverflow': False, 'pageErrors': errors, 'externalRequests': len(blocked_external),
                    'providerTransport': 'synthetic only', 'oauthGrant': 'simulated in temporary database',
                    'createdRemoteFixtures': remote.created, 'patchedRemoteFixtures': remote.patched}
        finally:
            context.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


def main():
    output = ROOT / 'test-results'
    output.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
        try:
            result = {'providers': [run_provider(browser, provider, output) for provider in ('google', 'microsoft')],
                      'realCalendarWrites': 0, 'scope': 'real Flask/browser with synthetic accounts and provider transport'}
            (output / 'calendar-publish-browser-verification.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
            print(json.dumps(result, ensure_ascii=False))
        finally:
            browser.close()


if __name__ == '__main__':
    main()
