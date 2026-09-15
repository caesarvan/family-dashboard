"""Temporary real Flask + Edge UI; provider discovery is synthetic GET only.

OAuth completion is simulated with a same-origin page reload, not a provider
authorization test. No provider website or real calendar/task write is used.
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
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import WSGIRequestHandler, make_server


class Quiet(WSGIRequestHandler):
    def log(self, *_args, **_kwargs):
        pass


def run(browser, provider, output):
    transport_calls = []

    def transport(method, url, _token, body=None, headers=None):
        transport_calls.append(method)
        assert method == 'GET', 'Discovery flow must never write to a provider'
        path = urlsplit(url).path
        wrapper = 'value' if provider == 'microsoft' else 'items'
        if path.endswith('/calendars') or path.endswith('/calendarList'):
            return {wrapper: [{'id': 'calendar-1', 'name': '合成日历', 'summary': '合成日历'}]}
        if path.endswith('/lists'):
            return {wrapper: [{'id': 'list-1', 'displayName': '合成清单', 'title': '合成清单'}]}
        raise AssertionError('Only synthetic source discovery is permitted')

    with tempfile.TemporaryDirectory() as directory:
        app = create_app({'TESTING': True, 'SECRET_KEY': 'connection-return-synthetic', 'DATA_DIR': directory,
                          'SESSION_COOKIE_SECURE': False, 'PUBLIC_ORIGIN': 'http://localhost',
                          'MEMBER1_PASSWORD': 'testing-password-one', 'MEMBER2_PASSWORD': 'testing-password-two',
                          'MICROSOFT_CLIENT_ID': 'test-client', 'MICROSOFT_CLIENT_SECRET': 'test-secret',
                          'GOOGLE_CLIENT_ID': 'test-client', 'GOOGLE_CLIENT_SECRET': 'test-secret',
                          'CLOUD_TRANSPORT': transport})
        accounts = app.extensions['cloud_accounts']
        scopes = 'User.Read Calendars.Read Tasks.ReadWrite' if provider == 'microsoft' else 'https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/tasks'
        with accounts.db() as con:
            for owner, name in [('member1', '本人合成账户'), ('member2', 'OTHER_MEMBER_ACCOUNT')]:
                con.execute('INSERT INTO cloud_accounts(id,owner,provider,client_id,subject,name,email,tokens) VALUES(?,?,?,?,?,?,?,?)',
                            ('account-' + owner, owner, provider, 'test-client', owner, name, owner + '@example.invalid',
                             accounts.encrypt({'access_token': 'synthetic-only', 'scope': scopes, 'expires_at': time.time() + 3600})))
        client = app.test_client()
        assert client.post('/api/login', json={'username': 'member1', 'password': 'testing-password-one'}).status_code == 200
        headers = {'X-CSRF-Token': client.get('/api/me').json['csrf']}
        plan = {'title': '合成旅行 · 连接返回测试', 'start': '2026-10-01', 'end': '2026-10-04', 'budget': 100000,
                'international': False, 'memberIds': ['member1', 'member2'], 'destinations': [{'country': '中国', 'city': '杭州'}],
                'checklist': [{'key': 'packing', 'title': '原始合成待办', 'owner': 'member1', 'dueOffsetDays': -2}],
                'shopping': [], 'segments': []}
        preview = client.post('/api/journeys/preview', json={'plan': plan}, headers=headers)
        assert preview.status_code == 200
        applied = client.post('/api/journeys/apply', json={'previewToken': preview.json['previewToken'], 'idempotencyKey': 'connection-return-synthetic'}, headers=headers)
        assert applied.status_code == 201
        journey_id, trip_id = applied.json['id'], applied.json['tripId']
        with accounts.db() as con:
            entity_id = con.execute("SELECT entity_id FROM journey_links WHERE journey_id=? AND kind='tasks'", (journey_id,)).fetchone()[0]
        server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=Quiet)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        origin = 'http://127.0.0.1:' + str(server.server_port)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        external = []; errors = []; requests = []

        def only_local(route):
            if urlsplit(route.request.url).hostname == '127.0.0.1':
                route.continue_()
            else:
                external.append(urlsplit(route.request.url).hostname); route.abort()

        context.route('**/*', only_local)
        page = context.new_page(); page.on('pageerror', lambda err: errors.append(str(err)))
        page.on('request', lambda request: requests.append((request.method, urlsplit(request.url).path)))

        def login(member='member1'):
            page.goto(origin)
            page.locator('#login-form [name=username]').select_option(member)
            page.locator('#login-form [name=password]').fill('testing-password-one' if member == 'member1' else 'testing-password-two')
            page.locator('#login-form button[type=submit]').click()
            page.wait_for_function('() => typeof data !== "undefined" && !!data && canEdit()')

        def empty_sources():
            accounts.select_sources('account-member1', 'member1', [])

        def check_no_publication():
            with accounts.db() as con:
                assert con.execute('SELECT count(*) FROM calendar_publications').fetchone()[0] == 0
                assert con.execute('SELECT count(*) FROM task_publications').fetchone()[0] == 0
            assert all(method == 'GET' for method in transport_calls)

        def open_calendar():
            page.evaluate('(id) => CalendarPublish.open(id)', journey_id)
            expect(page.locator('#calendar-publish-root')).to_be_visible()

        def open_tasks():
            page.evaluate('(id) => TaskPublish.open({entityIds:[id]})', entity_id)
            expect(page.locator('#task-publish-root')).to_be_visible()

        def enter_connection(kind):
            page.locator('[data-' + ('cp' if kind == 'calendar' else 'tp') + '=connect]').click()
            expect(page.locator('#account-return')).to_be_visible()
            expect(page.locator('#dialog')).not_to_contain_text('OTHER_MEMBER_ACCOUNT')

        def save_sources(kinds):
            page.locator('[data-account-select=account-member1]').click()
            expect(page.locator('#account-sources-form')).to_be_visible()
            page.locator('[name=source-0]').set_checked('calendar' in kinds)
            page.locator('[name=source-1]').set_checked('tasks' in kinds)
            page.locator('[name=consent]').check()
            page.locator('#account-sources-form button[type=submit]').click()
            expect(page.locator('#account-return')).to_be_visible()
            assert page.locator('#calendar-publish-root, #task-publish-root').count() == 0

        def stage_oauth():
            # Exercise the exact serialization helper used immediately before
            # trusted provider navigation; deliberately do not navigate there.
            page.evaluate('() => AccountsReturn.prepareOAuth()')
            saved = page.evaluate('() => JSON.parse(sessionStorage.getItem("family-dashboard.connection-return.v1"))')
            assert set(saved) == {'v', 'flowId', 'target', 'memberId', 'householdId', 'authVersion', 'createdAt', 'expiresAt'}
            assert saved['expiresAt'] - saved['createdAt'] == 600000
            assert set(saved['target']) <= {'kind', 'journeyId', 'entityIds'}
            assert not any(word in json.dumps(saved).lower() for word in ['csrf', 'token', 'email', 'password', 'title'])
            return saved

        try:
            login()
            # Actual journey entry -> no sources -> existing source manager ->
            # explicit save -> explicit fresh return. Never authorize/publish.
            page.evaluate('(id) => JourneyUI.open(id)', trip_id)
            page.locator('[data-journey=cloud-calendar]').click()
            expect(page.locator('[data-cp=connect]')).to_be_visible()
            enter_connection('calendar'); save_sources({'calendar'})
            before = len([r for r in requests if r[1].startswith('/api/calendar-publish/journeys/')])
            page.locator('#account-return').click()
            expect(page.locator('#calendar-publish-form')).to_be_visible()
            assert page.locator('#calendar-publish-root').get_attribute('data-journey-id') == journey_id
            assert len([r for r in requests if r[1].startswith('/api/calendar-publish/journeys/')]) >= before + 2
            assert page.locator('[data-cp=confirm]').count() == 0
            check_no_publication()

            open_tasks(); enter_connection('tasks'); save_sources({'calendar', 'tasks'})
            with accounts.db() as con:
                row = con.execute('SELECT data FROM entities WHERE id=?', (entity_id,)).fetchone()
                value = json.loads(row[0]); value['title'] = '已更新 · 必须重新读取的合成待办'
                con.execute('UPDATE entities SET data=?,revision=revision+1 WHERE id=?', (json.dumps(value), entity_id))
            page.locator('#account-return').click()
            expect(page.locator('#task-publish-form')).to_contain_text('已更新 · 必须重新读取')
            assert page.locator('[name=entityId]').count() == 1
            assert page.locator('[name=entityId]:checked').count() == 0
            check_no_publication()

            # Late readonly previews cannot place their result or error in a
            # freshly reopened publishing page.
            for kind in ['tasks', 'calendar']:
                opener = open_tasks if kind == 'tasks' else open_calendar
                prefix = 'task' if kind == 'tasks' else 'calendar'
                opener(); held_preview = []

                def delay_preview(route):
                    held_preview.append((route, route.fetch()))

                pattern = '**/api/' + prefix + '-publish/preview'
                page.route(pattern, delay_preview)
                if kind == 'tasks':
                    page.locator('[name=entityId]').first.check()
                page.locator('#' + prefix + '-publish-form button[type=submit]').click()
                for _ in range(100):
                    if held_preview:
                        break
                    page.wait_for_timeout(20)
                assert held_preview
                opener()
                held_preview[0][0].fulfill(response=held_preview[0][1])
                page.wait_for_timeout(150)
                expect(page.locator('#' + prefix + '-publish-error')).to_be_empty()
                assert page.locator('[data-tp=confirm], [data-cp=confirm]').count() == 0
                page.unroute(pattern, delay_preview)
                check_no_publication()

            # Small-screen CTA + account-return footer use the existing layout.
            empty_sources(); open_tasks(); page.set_viewport_size({'width': 390, 'height': 844})
            expect(page.locator('[data-tp=connect]')).to_be_visible()
            page.screenshot(path=str(output / ('connection-return-empty-phone-' + provider + '.png')), full_page=True)
            assert page.evaluate('() => document.documentElement.scrollWidth <= innerWidth + 1')
            enter_connection('tasks')
            page.screenshot(path=str(output / ('connection-return-manager-phone-' + provider + '.png')), full_page=True)
            assert page.evaluate('() => document.documentElement.scrollWidth <= innerWidth + 1')

            # Simulated full-page OAuth callback restores only a restart button.
            stage_oauth(); page.goto(origin + '/?auth=connected')
            expect(page.locator('#account-return')).to_have_text('重新打开待办发布')
            assert page.locator('#task-publish-root, [data-tp=confirm]').count() == 0
            assert page.evaluate('() => sessionStorage.getItem("family-dashboard.connection-return.v1")') is None
            save_sources({'tasks'}); page.locator('#account-return').click()
            expect(page.locator('#task-publish-form')).to_be_visible()
            assert page.locator('[name=entityId]:checked').count() == 0
            check_no_publication()

            # Calendar OAuth return also drops old preview/confirmation state.
            empty_sources(); open_calendar(); enter_connection('calendar'); stage_oauth()
            page.goto(origin + '/?auth=error&reason=access_denied')
            expect(page.locator('#account-return')).to_have_text('重新打开日历发布')
            assert page.locator('#calendar-publish-root, [data-cp=confirm]').count() == 0
            page.locator('#account-return').click()
            expect(page.locator('[data-cp=connect]')).to_be_visible()

            # A slow old account read cannot remove or replace a newer flow.
            held = []
            intercepted = {'first': True}

            def delay_first_accounts(route):
                if intercepted['first']:
                    intercepted['first'] = False
                    response = route.fetch()
                    held.append((route, response))
                else:
                    route.continue_()

            page.route('**/api/accounts', delay_first_accounts)
            page.locator('[data-cp=connect]').click()
            for _ in range(100):
                if held:
                    break
                page.wait_for_timeout(20)
            assert held
            open_tasks(); enter_connection('tasks')
            expect(page.locator('#account-return')).to_have_text('返回待办发布')
            held[0][0].fulfill(response=held[0][1])
            page.wait_for_timeout(250)
            expect(page.locator('#account-return')).to_have_text('返回待办发布')
            page.unroute('**/api/accounts', delay_first_accounts)

            # A delayed full-page staging read must not clear a newer same-page
            # return flow or persist its obsolete target.
            held_me = []; intercept_me = {'first': True}

            def delay_me(route):
                if intercept_me['first']:
                    intercept_me['first'] = False; held_me.append((route, route.fetch()))
                else:
                    route.continue_()

            page.route('**/api/me', delay_me)
            page.evaluate('''id => { window.oldOAuthAttempt=AccountsReturn.prepareOAuth({kind:'calendar',journeyId:id}).then(()=> 'unexpected',()=> 'discarded'); }''', journey_id)
            for _ in range(100):
                if held_me:
                    break
                page.wait_for_timeout(20)
            assert held_me
            open_tasks(); enter_connection('tasks')
            held_me[0][0].fulfill(response=held_me[0][1])
            assert page.evaluate('() => window.oldOAuthAttempt') == 'discarded'
            expect(page.locator('#account-return')).to_have_text('返回待办发布')
            assert page.evaluate('() => sessionStorage.getItem("family-dashboard.connection-return.v1")') is None
            page.unroute('**/api/me', delay_me)

            # An expired or another-member/household intent must not be resumed.
            for change in ['expired', 'member', 'household', 'bad-target']:
                open_calendar(); enter_connection('calendar'); stage_oauth()
                page.evaluate('''change => {
                    const key='family-dashboard.connection-return.v1', s=JSON.parse(sessionStorage.getItem(key));
                    if(change==='expired'){s.createdAt-=700000;s.expiresAt-=700000}
                    if(change==='member')s.memberId='member2';
                    if(change==='household')s.householdId='different-synthetic-household';
                    if(change==='bad-target')s.target={kind:'tasks',entityIds:[]};
                    sessionStorage.setItem(key,JSON.stringify(s));
                }''', change)
                page.goto(origin + '/?auth=connected')
                expect(page.locator('#account-refresh')).to_be_visible()
                assert page.locator('#account-return, #calendar-publish-root, #task-publish-root').count() == 0
                assert page.evaluate('() => sessionStorage.getItem("family-dashboard.connection-return.v1")') is None

            # Removed targets are not downgraded to an unscoped task workspace.
            open_tasks(); enter_connection('tasks'); saved = stage_oauth()
            with accounts.db() as con:
                con.execute('DELETE FROM entities WHERE id=?', (entity_id,))
            page.goto(origin + '/?auth=connected')
            expect(page.locator('#account-refresh')).to_be_visible()
            assert page.locator('#account-return, #task-publish-root').count() == 0

            # An actual cookie change while the old page remains open is caught
            # with fresh /me, even before boot refreshes the JavaScript actor.
            open_calendar(); enter_connection('calendar'); stage_oauth()
            browser_csrf = page.evaluate('() => csrf')
            assert context.request.post(origin + '/api/logout', data={}, headers={'X-CSRF-Token': browser_csrf}).status == 200
            assert context.request.post(origin + '/api/login', data={'username': 'member2', 'password': 'testing-password-two'}).status == 200
            page.locator('#account-return').click()
            expect(page.locator('#dialog-title')).to_have_text('登录状态已改变')
            expect(page.locator('#dialog')).not_to_contain_text('本人合成账户')
            assert page.locator('#account-return, #calendar-publish-root').count() == 0
            assert page.evaluate('() => sessionStorage.getItem("family-dashboard.connection-return.v1")') is None
            me = context.request.get(origin + '/api/me').json()
            assert context.request.post(origin + '/api/logout', data={}, headers={'X-CSRF-Token': me['csrf']}).status == 200
            login()

            # Login and household-switch submission clear the stored intent.
            open_calendar(); enter_connection('calendar'); stage_oauth()
            page.evaluate('''() => { const f=document.createElement('form');f.id='space-switch';document.body.append(f);f.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));f.remove(); }''')
            assert page.evaluate('() => sessionStorage.getItem("family-dashboard.connection-return.v1")') is None
            open_calendar(); enter_connection('calendar'); stage_oauth()
            page.evaluate('''() => { const b=document.createElement('button');b.dataset.action='logout';document.body.append(b);b.click();b.remove(); }''')
            expect(page.locator('#login-form')).to_be_visible()
            assert page.evaluate('() => sessionStorage.getItem("family-dashboard.connection-return.v1")') is None
            login('member2')
            page.evaluate('() => accountsModal()')
            expect(page.locator('#account-refresh')).to_be_visible()
            assert page.locator('#account-return').count() == 0
            expect(page.locator('#dialog')).not_to_contain_text('本人合成账户')

            check_no_publication()
            assert not [r for r in requests if r[0] == 'POST' and r[1] in {'/api/accounts/bind', '/api/calendar-publish/authorize', '/api/calendar-publish/confirm', '/api/task-publish/confirm'}]
            assert not errors and not external
            return {'provider': provider, 'passed': True, 'realCloudWrites': 0, 'externalRequests': 0,
                    'publicationRows': 0, 'providerDiscoveryGetCalls': len(transport_calls),
                    'oauthEvidence': 'same-origin callback simulation only; actual provider navigation untested',
                    'checks': ['journey-entry', 'calendar-source-save-explicit-return', 'task-id-preserved-fresh-read',
                               'no-autoselection-or-publish', 'private-account-filter', '390px-layout',
                               'calendar-and-task-full-page-restart-only', 'no-credential-in-intent',
                               'expired-cross-member-cross-household-invalid-target-discard', 'removed-target-no-fallback',
                               'late-preview-cannot-contaminate-new-page', 'old-request-cannot-clear-new-flow',
                               'late-oauth-staging-cannot-clear-new-flow', 'actual-cookie-switch-redacts-old-view',
                               'household-switch-logout-clear', 'member2-no-old-return'], 'jsErrors': errors}
        finally:
            context.close(); server.shutdown(); thread.join(timeout=5)


def main():
    output = ROOT / 'test-results'; output.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
        try:
            results = [run(browser, provider, output) for provider in ['microsoft', 'google']]
            (output / 'connection-return-browser-verification.json').write_text(json.dumps({'passed': True, 'results': results}, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(results, ensure_ascii=False))
        finally:
            browser.close()


if __name__ == '__main__':
    main()
