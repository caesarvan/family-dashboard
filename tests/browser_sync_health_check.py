"""Real local Flask/SQLite/Edge sync-health UX, ownership and delayed reads.

All credentials and data are synthetic. No worker, provider or production data
is used; run with the existing loopback browser bootstrap for an extra guard.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from app import create_app
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server, WSGIRequestHandler
import test_sync_health as fixtures


class Quiet(WSGIRequestHandler):
    def log(self, *_args, **_kwargs):
        pass


def main():
    out = ROOT / 'test-results'
    out.mkdir(exist_ok=True)
    paths = set(ROOT.glob('*.py')) | {Path(__file__), ROOT / 'tests/test_sync_health.py'}
    for directory in ('static', 'deploy'):
        paths.update(p for p in (ROOT / directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    paths.update(ROOT / name for name in ('Dockerfile', 'compose.yaml', 'requirements.txt', 'pytest.ini') if (ROOT / name).exists())
    def source_hashes():
        return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
    checks, errors, external, provider_calls, screenshots, requests = [], [], [], [], [], {}
    report = {'passed': False, 'checks': checks, 'pageErrors': errors, 'externalRequests': external,
              'providerCalls': provider_calls, 'screenshots': screenshots, 'requestCounts': requests,
              'sourceHashes': source_hashes(), 'realCloudWrites': 0, 'productionWrites': 0, 'realPrivateInputs': 0,
              'scope': 'Actual temporary Flask/SQLite/Edge; read-only mixed freshness and publication guidance, original-page navigation, same-revision refresh and delayed identity-bound reads.'}
    def passed(name):
        assert name not in checks
        checks.append(name)
    def deny_provider(*_args, **_kwargs):
        provider_calls.append('unexpected_provider_operation')
        raise AssertionError('No provider operation is allowed')
    with tempfile.TemporaryDirectory(prefix='sync-health-browser-') as temporary:
        app = create_app({'TESTING': True, 'SECRET_KEY': 'synthetic-sync-health-browser-secret',
                          'DATA_DIR': temporary, 'SESSION_COOKIE_SECURE': False,
                          'MEMBER1_PASSWORD': 'testing-password-one', 'MEMBER2_PASSWORD': 'testing-password-two',
                          'PUBLIC_ORIGIN': 'http://localhost', 'GOOGLE_CLIENT_ID': fixtures.CLIENTS['google'],
                          'MICROSOFT_CLIENT_ID': fixtures.CLIENTS['microsoft'],
                          'GOOGLE_CLIENT_SECRET': 'synthetic-secret', 'MICROSOFT_CLIENT_SECRET': 'synthetic-secret',
                          'CLOUD_TRANSPORT': deny_provider, 'OAUTH_TRANSPORT': deny_provider,
                          'CLOUD_PROVIDER_FACTORY': deny_provider, 'OPENAI_API_KEY': ''})
        assert any(r.rule == '/api/sync-health' for r in app.url_map.iter_rules()), 'Root registration must be integrated'
        assert app.config['SESSION_REFRESH_EACH_REQUEST'] is False
        database = Path(temporary) / 'household.sqlite3'
        def sql(statement, parameters=()):
            with closing(sqlite3.connect(database)) as con:
                rows = con.execute(statement, parameters).fetchall()
                con.commit()
                return rows
        def business_snapshot():
            tables = ('cloud_accounts', 'cloud_sources', 'calendar_publications', 'task_publications',
                      'entities', 'journey_workflows', 'journey_links', 'hub_transactions', 'hub_investments')
            return {table: sql('SELECT * FROM ' + table + ' ORDER BY 1') for table in tables}
        fixtures.NOW = datetime.now(timezone.utc)
        now = fixtures.NOW
        fixtures.account(app, label='我的合成 Google 账户')
        fixtures.account(app, uid='account-ms', provider='microsoft', label='我的合成 Microsoft 账户', reauth=1)
        fixtures.account(app, uid='partner-account', owner='member2', label='PARTNER_ONLY_ACCOUNT')
        for sid, success, error, kind in [
            ('source-1', now.isoformat(), '', 'calendar'),
            ('source-stale', (now - timedelta(minutes=25)).isoformat(), '', 'calendar'),
            ('source-waiting', '', '', 'tasks'),
            ('source-error', now.isoformat(), 'SYNTHETIC_RAW_UPSTREAM_ERROR', 'tasks'),
            ('source-unknown', 'invalid-date', '', 'calendar'),
        ]:
            fixtures.source(app, uid=sid, success=success, error=error, kind=kind)
        fixtures.source(app, uid='source-reauth', aid='account-ms')
        fixtures.source(app, uid='PARTNER_ONLY_SOURCE', aid='partner-account', success=now.isoformat())
        # Encrypt only fake tokens so existing management GETs can inspect scopes.
        cloud = app.extensions['cloud_accounts']
        with cloud.db() as con:
            con.execute('UPDATE cloud_accounts SET tokens=?', (cloud.encrypt({'access_token': 'synthetic', 'refresh_token': 'synthetic',
                        'scope': 'https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/tasks User.Read Calendars.Read Tasks.ReadWrite',
                        'expires_at': now.timestamp() + 3600}),))
        client = app.test_client()
        assert client.post('/api/login', json={'username': 'member1', 'password': 'testing-password-one'}).status_code == 200
        headers = {'X-CSRF-Token': client.get('/api/me').json['csrf']}
        start = (now + timedelta(days=25)).date().isoformat()
        end = (now + timedelta(days=28)).date().isoformat()
        plan = {'title': '合成旅行日历发布', 'start': start, 'end': end, 'budget': 10000,
                'destinations': [{'city': '合成城市', 'country': '合成国家'}], 'international': False,
                'memberIds': ['member1', 'member2'], 'checklist': [], 'shopping': [], 'segments': []}
        preview = client.post('/api/journeys/preview', json={'plan': plan}, headers=headers)
        assert preview.status_code == 200
        created = client.post('/api/journeys/apply', json={'previewToken': preview.json['previewToken'], 'idempotencyKey': 'synthetic-health-trip'}, headers=headers)
        assert created.status_code == 201
        journey_id = created.json['id']
        fixtures.publication(app, 'calendar-attention', status='conflict', review=1, title='本人日历需要核对')
        sql("UPDATE calendar_publications SET journey_id=? WHERE id='calendar-attention'", (journey_id,))
        task_id = fixtures.publication(app, 'own-task', kind='tasks', status='retry', title='本人待办需要检查')
        fixtures.publication(app, 'managed-task', kind='tasks', owner='member2', account_owner='member1', status='paused', title='本人账户可管理的共同待办')
        fixtures.publication(app, 'partner-task', kind='tasks', owner='member2', account_owner='member2', status='pending', title='PARTNER_ONLY_PUBLICATION')
        fixtures.publication(app, 'partner-calendar', owner='member2', status='needs_authorization', title='PARTNER_ONLY_CALENDAR')
        fixtures.publication(app, 'published-task', kind='tasks', status='published', title='PUBLISHED_TASK_COUNT_ONLY')
        fixture_snapshot = business_snapshot()
        server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=Quiet)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
                def login(context, number=1, child=False):
                    context.request.get(base + '/api/me')
                    prefix = 'second-home-password-' if child else 'testing-password-'
                    response = context.request.post(base + '/api/login', data={'username': f'member{number}', 'password': prefix + ('one' if number == 1 else 'two')})
                    assert response.status == 200
                def auth(context):
                    return {'X-CSRF-Token': context.request.get(base + '/api/me').json()['csrf']}
                seed = browser.new_context()
                login(seed)
                invitation = seed.request.post(base + '/api/spaces/invitations', headers=auth(seed), data={})
                assert invitation.status == 201
                child = seed.request.post(base + '/api/spaces/redeem', headers=auth(seed), data={
                    'name': 'Synthetic Health Household', 'slug': 'synthetic-health-second',
                    'invitation': invitation.json()['invitation'], 'MEMBER1_PASSWORD': 'second-home-password-one',
                    'MEMBER2_PASSWORD': 'second-home-password-two'})
                assert child.status == 201
                child_entry = child.json()['entry']

                class Flow:
                    def __init__(self, width=360, role='member', number=1):
                        sql('DELETE FROM attempts')
                        self.context = browser.new_context(viewport={'width': width, 'height': 950})
                        self.held, self.gate, self.calls, self.fail_reads = [], None, [], set()
                        self.context.route('**/*', self.route)
                        if role == 'member':
                            login(self.context, number)
                        elif role == 'tv':
                            # Many isolated browser cases intentionally exceed
                            # the real 16-session cap. Renew the fixture owner.
                            login(seed)
                            pair = self.context.request.post(base + '/api/pair/start', data={}).json()
                            approved = seed.request.post(base + '/api/pair/approve', headers=auth(seed), data={
                                'code': pair['code'], 'name': 'SYNTHETIC_HEALTH_TV', 'focus': 'member1', 'calendarView': 'today'})
                            assert approved.status == 200, approved.status
                            paired = self.context.request.post(base + '/api/pair/poll', data={'secret': pair['secret']})
                            assert paired.status == 200 and paired.json()['approved']
                        self.page = self.context.new_page()
                        self.page.on('pageerror', lambda error: errors.append(str(error)))
                        self.page.goto(base + ('/demo' if role == 'demo' else '/tv' if role == 'tv' else ''))
                        expect(self.page.locator('.board' if role == 'tv' else '.ps-welcome')).to_be_visible()
                        self.page.evaluate('clearInterval(pollTimer)')
                    def route(self, route):
                        request = route.request
                        path = urlsplit(request.url).path
                        if not request.url.startswith(base + '/'):
                            external.append({'method': request.method, 'path': path})
                            route.abort()
                            return
                        self.calls.append((request.method, path))
                        key = request.method + ' ' + path
                        requests[key] = requests.get(key, 0) + 1
                        if request.method == 'GET' and path in self.fail_reads:
                            route.fulfill(status=503, content_type='application/json', body='{"error":"SYNTHETIC_RAW_FAILURE_NEVER_RENDER"}')
                        elif self.gate and self.gate(request.method, path):
                            self.gate = None
                            response = route.fetch()
                            assert 'set-cookie' not in response.headers, 'Held reads must not refresh identity cookies'
                            self.held.append((route, response))
                        else:
                            route.continue_()
                    def hold(self, path, occurrence=1):
                        counter = [0]
                        def match(method, actual):
                            if method == 'GET' and actual == path:
                                counter[0] += 1
                                return counter[0] == occurrence
                            return False
                        self.gate = match
                    def pending(self):
                        for _ in range(300):
                            if self.held:
                                return
                            self.page.wait_for_timeout(20)
                        raise AssertionError('The intended real HTTP response was not held')
                    def release(self, result='success'):
                        route, response = self.held.pop(0)
                        if result == 'error':
                            route.fulfill(status=503, content_type='application/json', body='{"error":"SYNTHETIC_RAW_FAILURE_NEVER_RENDER"}')
                        elif result == 'missing':
                            route.fulfill(status=200, content_type='application/json', body='{}')
                        else:
                            route.fulfill(response=response)
                        self.page.wait_for_timeout(180)
                    def open(self, wait=True):
                        self.page.evaluate('void SyncHealth.open()')
                        if wait:
                            expect(self.page.locator('[data-sync-health-root] .sh-view')).to_be_visible()
                        return self
                    def connections(self):
                        self.page.evaluate("ProductShell.navigate('connections')")
                        expect(self.page.locator('[data-sync-health-summary]')).to_be_visible()
                    def other(self):
                        self.page.evaluate('ProductShell.openSearch()')
                        self.page.locator('#ps-search-input').fill('KEEP_NEW_HEALTH_SEARCH')
                        self.page.evaluate('window.newHealthNode=document.querySelector("#ps-search-input")')
                    def assert_other(self):
                        assert self.page.evaluate('window.newHealthNode.isConnected')
                        expect(self.page.locator('#ps-search-input')).to_have_value('KEEP_NEW_HEALTH_SEARCH')
                        assert 'SYNTHETIC_RAW_FAILURE' not in self.page.locator('#dialog').inner_text()
                    def switch(self, mode, boot=False):
                        if mode == 'household':
                            self.context.request.get(base + child_entry)
                            login(self.context, child=True)
                        else:
                            login(self.context, 1 if mode == 'same-member' else 2)
                        if boot:
                            actual = self.context.request.get(base + '/api/me').json()['user']
                            self.page.evaluate('void boot()')
                            self.page.wait_for_function('(a)=>user?.id===a.id&&user?.householdId===a.householdId', arg=actual)
                            self.page.evaluate('clearInterval(pollTimer)')
                    def no_writes(self, since=0):
                        assert not [(m, p) for m, p in self.calls[since:] if m != 'GET'], self.calls[since:]
                    def close(self):
                        self.context.close()

                f = Flow(1440)
                f.connections()
                expect(f.page.locator('[data-sync-health-summary]')).to_contain_text('部分同步需要关注')
                expect(f.page.locator('[data-sync-health-summary]')).to_contain_text('超过 5 分钟')
                expect(f.page.locator('[data-sync-health-summary]')).to_contain_text('等待首次同步')
                expect(f.page.locator('[data-sync-health-summary]')).to_contain_text('授权需要处理')
                value = f.context.request.get(base + '/api/state').json()['sync']['health']
                assert value['latestSuccess'] and value['lastCompleteSuccess'] is None
                passed('recent_success_does_not_hide_stale_waiting_error_or_authorization')
                f.page.locator('[data-sync-health-open]').click()
                expect(f.page.locator('.sh-view')).to_be_visible()
                assert set(f.page.locator('[data-sh-source-state]').evaluate_all('(n)=>n.map(x=>x.dataset.shSourceState)')) == {
                    'current', 'delayed', 'waiting', 'error', 'unknown', 'needs_authorization'}
                passed('all_six_source_states_render_independently')
                body = f.page.locator('[data-sync-health-root]').inner_text()
                assert 'PARTNER_ONLY_' not in body and fixtures.SENTINEL not in body and 'SYNTHETIC_RAW_' not in body
                assert '本人账户可管理的共同待办' in body and '本人日历需要核对' in body
                assert 'PUBLISHED_TASK_COUNT_ONLY' not in body and '1 项已发布' in body
                passed('private_source_and_publication_details_are_member_scoped_with_published_counts')
                f.no_writes()
                passed('open_and_status_read_do_not_post_sync_retry_or_publication')
                f.close()

                for width in (360, 768, 1440):
                    f = Flow(width)
                    for theme in ('forest', 'light', 'ocean'):
                        f.page.evaluate('ProductShell.openPreferences()')
                        f.page.locator(f'[name=theme][value={theme}]').check()
                        f.page.locator('#ps-preferences-form [type=submit]').click()
                        expect(f.page.locator('#dialog')).not_to_be_visible()
                        expect(f.page.locator('html')).to_have_attribute('data-theme', theme)
                        f.connections()
                        f.open()
                        assert f.page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
                        assert f.page.locator('[data-sync-health-root]').evaluate('(n)=>n.scrollWidth<=n.clientWidth+2')
                        name = f'sync-health-{theme}-{width}.png'
                        f.page.screenshot(path=str(out / name), full_page=True)
                        screenshots.append(name)
                        f.page.evaluate('closeModal()')
                        passed(f'actual_theme_{theme}_at_{width}px_no_horizontal_overflow')
                    f.close()

                f = Flow(1440)
                f.page.evaluate("ProductShell.navigate('tasks')")
                f.page.locator('[data-ps-list-search]').fill('本人待办')
                f.page.locator('[data-ps-list-search]').focus()
                node = f.page.locator('[data-ps-list-search]').element_handle()
                revision = f.context.request.get(base + '/api/state').json()['revision']
                source_before = sql('SELECT id,last_success,error,failures FROM cloud_sources ORDER BY id')
                account_before = sql('SELECT id,needs_reauth FROM cloud_accounts ORDER BY id')
                sql("UPDATE cloud_sources SET last_success=?,error='',failures=0", (datetime.now(timezone.utc).isoformat(),))
                sql('UPDATE cloud_accounts SET needs_reauth=0')
                assert f.context.request.get(base + '/api/state').json()['revision'] == revision
                f.page.evaluate('refresh()')
                assert node.evaluate('(n)=>n.isConnected&&document.activeElement===n')
                expect(f.page.locator('[data-ps-list-search]')).to_have_value('本人待办')
                expect(f.page.locator('#connection')).to_contain_text('全部 7 个来源最近已更新')
                passed('same_revision_status_change_updates_footer_preserving_list_search_and_focus')
                f.other()
                f.page.evaluate('refresh()')
                f.assert_other()
                assert f.page.locator('#ps-search-input').evaluate('(n)=>document.activeElement===n')
                passed('same_revision_refresh_preserves_global_search_dialog_and_focus')
                f.page.evaluate('closeModal()')
                f.connections()
                f.page.locator('[data-sync-health-open]').focus()
                button = f.page.locator('[data-sync-health-open]').element_handle()
                f.page.evaluate('refresh()')
                assert button.evaluate('(n)=>n.isConnected&&document.activeElement===n')
                passed('unchanged_summary_preserves_existing_action_node')
                sql("UPDATE cloud_sources SET last_success=? WHERE id='source-stale'", ((now - timedelta(minutes=25)).isoformat(),))
                f.page.evaluate('refresh()')
                expect(f.page.locator('[data-sync-health-summary]')).to_contain_text('部分同步需要关注')
                assert f.page.locator('[data-sync-health-open]').evaluate('(n)=>document.activeElement===n')
                passed('same_revision_changed_summary_updates_in_place_and_retains_action_focus')
                old = f.page.evaluate('JSON.stringify(data)')
                f.hold('/api/state')
                f.page.evaluate('void refresh()')
                f.pending()
                f.release('error')
                assert f.page.evaluate('JSON.stringify(data)') == old
                expect(f.page.locator('#connection')).to_contain_text('显示上次获取的数据')
                expect(f.page.locator('[data-sync-health-summary]')).to_contain_text('上次记录')
                passed('offline_state_refresh_retains_last_snapshot_and_marks_it_stale')
                for sid, success, error, failures in source_before:
                    sql('UPDATE cloud_sources SET last_success=?,error=?,failures=? WHERE id=?', (success, error, failures, sid))
                for aid, reauth in account_before:
                    sql('UPDATE cloud_accounts SET needs_reauth=? WHERE id=?', (reauth, aid))
                f.close()

                for result in ('error', 'missing'):
                    f = Flow()
                    f.hold('/api/sync-health')
                    f.open(False)
                    f.pending()
                    f.release(result)
                    expect(f.page.locator('[data-sh-message]')).to_contain_text('暂时无法读取同步状态')
                    assert 'SYNTHETIC_RAW_FAILURE' not in f.page.locator('#dialog').inner_text()
                    assert f.page.locator('.sh-account').count() == 0
                    passed('initial_' + result + '_has_fixed_prompt_and_no_partial_private_result')
                    f.close()
                f = Flow().open()
                f.hold('/api/sync-health')
                f.page.locator('[data-sh=refresh]').click()
                f.pending()
                assert f.page.locator('.sh-account').count() == 0
                f.release('error')
                expect(f.page.locator('.sh-stale')).to_be_visible()
                expect(f.page.locator('.sh-account').first).to_be_visible()
                assert 'SYNTHETIC_RAW_FAILURE' not in f.page.locator('#dialog').inner_text()
                passed('failed_dialog_refresh_rechecks_identity_then_marks_last_private_snapshot_stale')
                f.close()

                for outcome in ('success', 'error'):
                    for replacement in ('close', 'other', 'new-health'):
                        f = Flow()
                        f.hold('/api/sync-health')
                        f.open(False)
                        f.pending()
                        if replacement == 'close':
                            f.page.evaluate('closeModal()')
                        elif replacement == 'other':
                            f.other()
                        else:
                            f.open()
                            f.page.evaluate('window.replacementHealth=document.querySelector(".sh-view")')
                        f.release(outcome)
                        if replacement == 'close':
                            expect(f.page.locator('#dialog')).not_to_be_visible()
                        elif replacement == 'other':
                            f.assert_other()
                        else:
                            assert f.page.evaluate('window.replacementHealth.isConnected')
                            assert 'SYNTHETIC_RAW_FAILURE' not in f.page.locator('#dialog').inner_text()
                        passed(f'late_health_{outcome}_cannot_replace_{replacement}')
                        f.close()

                for phase, path, occurrence in [('before-read', '/api/me', 1), ('after-read', '/api/sync-health', 1), ('after-identity', '/api/me', 2)]:
                    for mode in ('member', 'household', 'same-member'):
                        f = Flow()
                        f.hold(path, occurrence)
                        f.open(False)
                        f.pending()
                        f.switch(mode)
                        f.release()
                        # The last phase's captured old /me is a real old response.
                        # Read-only cookies do not resurrect identity; the module
                        # cannot know a cookie-only switch after its final read.
                        if phase == 'after-identity':
                            f.page.locator('[data-sh=refresh]').click()
                        expect(f.page.locator('[data-sync-health-root]')).to_contain_text('登录或家庭已变化')
                        assert f.page.locator('.sh-account').count() == 0
                        passed(f'{mode}_change_{phase}_rejects_private_details' + ('_on_next_explicit_read' if phase == 'after-identity' else ''))
                        f.close()

                for mode in ('member', 'household'):
                    for outcome in ('success', 'error'):
                        f = Flow()
                        f.hold('/api/sync-health')
                        f.open(False)
                        f.pending()
                        f.switch(mode, boot=True)
                        f.other()
                        f.release(outcome)
                        f.assert_other()
                        passed(f'late_{outcome}_after_{mode}_boot_cannot_clear_new_search')
                        f.close()
                for result in ('error', 'missing'):
                    for occurrence in (1, 2):
                        f = Flow()
                        f.hold('/api/me', occurrence)
                        f.open(False)
                        f.pending()
                        f.release(result)
                        expect(f.page.locator('[data-sync-health-root]')).to_contain_text('暂时无法读取同步状态' if result == 'error' else '登录或家庭已变化')
                        assert f.page.locator('.sh-account').count() == 0
                        passed(f'identity_read_{occurrence}_{result}_does_not_render_private_details')
                        f.close()
                f = Flow().open()
                f.fail_reads.add('/api/me')
                f.page.locator('[data-sh=refresh]').click()
                expect(f.page.locator('[data-sync-health-root]')).to_contain_text('暂时无法核对登录状态')
                assert f.page.locator('.sh-account').count() == 0
                assert 'SYNTHETIC_RAW_FAILURE' not in f.page.locator('#dialog').inner_text()
                passed('persistent_identity_read_failure_clears_private_cache_and_uses_fixed_prompt')
                f.close()

                for action, selector in [('accounts', '[data-sh=accounts]'), ('calendar', '[data-sh-kind=calendar]'), ('tasks', '[data-sh-kind=tasks]')]:
                    f = Flow().open()
                    before = len(f.calls)
                    if action == 'tasks':
                        item = f.page.locator('.sh-publication').filter(has_text='本人待办需要检查').locator('[data-sh=publication]')
                    else:
                        item = f.page.locator(selector).first
                    item.click()
                    if action == 'accounts':
                        expect(f.page.locator('#account-refresh')).to_be_visible()
                    elif action == 'calendar':
                        expect(f.page.locator('#calendar-publish-form')).to_be_visible()
                        assert any('/api/' in p and journey_id in p for _, p in f.calls[before:])
                    else:
                        expect(f.page.locator('#task-publish-form')).to_be_visible()
                        assert any(p == '/api/task-publish/state' for _, p in f.calls[before:])
                    f.no_writes(before)
                    passed(action + '_navigation_opens_original_management_page_without_post')
                    f.close()
                    for replacement in ('other', 'member', 'household'):
                        f = Flow().open()
                        before = len(f.calls)
                        f.hold('/api/me')
                        f.page.locator(selector).first.click()
                        f.pending()
                        if replacement == 'other':
                            f.other()
                        else:
                            f.switch(replacement, boot=True)
                            f.other()
                        f.release()
                        f.assert_other()
                        f.no_writes(before)
                        passed(f'{action}_delayed_navigation_cannot_replace_{replacement}_page')
                        f.close()

                f = Flow(number=2).open()
                text = f.page.locator('[data-sync-health-root]').inner_text()
                assert 'PARTNER_ONLY_ACCOUNT' in text and '我的合成 Google 账户' not in text
                assert '本人日历需要核对' not in text
                passed('member_two_sees_own_sources_and_only_manageable_publications')
                f.close()
                f = Flow()
                f.switch('household', boot=True)
                f.open()
                expect(f.page.locator('[data-sync-health-root]')).to_contain_text('你还没有连接账户')
                assert f.page.locator('.sh-account').count() == 0 and f.page.locator('.sh-publication').count() == 0
                passed('separate_household_does_not_inherit_original_private_sources_or_queues')
                f.close()
                for role in ('tv', 'demo'):
                    f = Flow(1440, role=role)
                    before = len(f.calls)
                    f.page.evaluate('void SyncHealth.open()')
                    f.page.wait_for_timeout(150)
                    assert not any(path == '/api/sync-health' for _, path in f.calls)
                    assert f.page.locator('[data-sync-health-root]').count() == 0
                    if role == 'tv':
                        assert f.context.request.get(base + '/api/sync-health').status == 403
                        # Shared event/task titles may be on TV even when the
                        # publication's management record is not accessible.
                        body = f.page.locator('body').inner_text()
                        assert 'PARTNER_ONLY_ACCOUNT' not in body and 'PARTNER_ONLY_SOURCE' not in body
                    else:
                        f.connections()
                        assert f.page.locator('[data-sync-health-open]').count() == 0
                    f.no_writes(before)
                    passed(role + '_never_requests_private_health_details_or_management')
                    f.close()
                assert business_snapshot() == fixture_snapshot
                passed('all_health_reads_and_navigation_leave_original_business_rows_unchanged')
                assert not errors and not external and not provider_calls
                passed('no_javascript_errors_external_requests_or_provider_operations')
                seed.close()
                browser.close()
                report['passed'] = True
        finally:
            server.shutdown()
            thread.join(timeout=5)
            report['sourceHashesAfter'] = source_hashes()
            report['sourceUnchanged'] = report['sourceHashesAfter'] == report['sourceHashes']
            report['passed'] = report['passed'] and report['sourceUnchanged']
            (out / 'sync-health-browser-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            print(json.dumps({'passed': report['passed'], 'checks': len(checks), 'sourceUnchanged': report['sourceUnchanged'],
                              'pageErrors': len(errors), 'externalRequests': len(external), 'providerCalls': len(provider_calls)}))
    assert report['passed']


if __name__ == '__main__':
    main()
