"""First TV pairing: real loopback Flask/SQLite/Edge, synthetic families only."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import create_app
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server, WSGIRequestHandler


class Quiet(WSGIRequestHandler):
    def log(self, *_args, **_kwargs):
        pass


def main():
    out = ROOT / 'test-results'
    out.mkdir(exist_ok=True)
    names = ['app.py', 'household_spaces.py', 'member_sessions.py', 'static/app.js',
             'static/product-shell.js', 'static/index.html', 'tests/browser_tv_onboarding_check.py']
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}
    checks, external, errors, counts, evidence = [], [], [], {}, {}
    passed = False
    with tempfile.TemporaryDirectory(prefix='tv-onboarding-browser-') as folder:
        app = create_app({'TESTING': True, 'SECRET_KEY': 'synthetic-tv-onboarding-key',
                          'DATA_DIR': folder, 'SESSION_COOKIE_SECURE': False,
                          'MEMBER1_PASSWORD': 'testing-password-one', 'MEMBER2_PASSWORD': 'testing-password-two'})
        assert app.config['SESSION_REFRESH_EACH_REQUEST'] is False
        database = Path(folder) / 'household.sqlite3'
        server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=Quiet)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)

                def sql(statement, values=(), db=database):
                    with closing(sqlite3.connect(db)) as con:
                        result = con.execute(statement, values).fetchall()
                        con.commit()
                        return result

                def login(context, member='member1', password=None):
                    context.request.get(base + '/api/me')
                    response = context.request.post(base + '/api/login', data={'username': member, 'password': password or (
                        'testing-password-one' if member == 'member1' else 'testing-password-two')})
                    assert response.status == 200, response.text()

                def auth(context):
                    return {'X-CSRF-Token': context.request.get(base + '/api/me').json()['csrf']}

                seed = browser.new_context()
                login(seed)
                invitation = seed.request.post(base + '/api/spaces/invitations', headers=auth(seed), data={})
                assert invitation.status == 201, invitation.text()
                created = seed.request.post(base + '/api/spaces/redeem', headers=auth(seed), data={
                    'name': 'Synthetic TV Household', 'slug': 'synthetic-tv-second',
                    'invitation': invitation.json()['invitation'], 'MEMBER1_PASSWORD': 'second-home-password-one',
                    'MEMBER2_PASSWORD': 'second-home-password-two'})
                assert created.status == 201, created.text()
                child_entry = created.json()['entry']
                seed.close()

                class Flow:
                    def __init__(self, width=360):
                        sql('DELETE FROM attempts')
                        sql('DELETE FROM devices')
                        self.context = browser.new_context(viewport={'width': width, 'height': 900})
                        login(self.context)
                        self.held, self.gate, self.requests = [], None, []
                        self.context.route('**/*', self.route)
                        self.page = self.context.new_page()
                        self.page.on('pageerror', lambda error: errors.append(str(error)))
                        self.page.goto(base)
                        expect(self.page.locator('.ps-welcome')).to_be_visible()
                        self.page.evaluate('ProductShell.navigate("connections")')

                    def route(self, route):
                        request = route.request
                        if not request.url.startswith(base + '/'):
                            external.append({'url': request.url, 'method': request.method})
                            route.abort()
                            return
                        path = urlsplit(request.url).path
                        key = request.method + ' ' + path
                        counts[key] = counts.get(key, 0) + 1
                        self.requests.append((request.method, path))
                        if self.gate and self.gate(request.method, path):
                            self.gate = None
                            response = route.fetch()  # Fetch real old HTTP response before delaying delivery.
                            assert 'set-cookie' not in response.headers, response.headers
                            self.held.append((route, response))
                        else:
                            route.continue_()

                    def devices(self):
                        self.page.evaluate('void devicesModal()')
                        expect(self.page.locator('.tv-devices-flow [data-action=pair]')).to_be_visible()

                    def pair(self):
                        self.page.evaluate('void pairForm()')
                        expect(self.page.locator('#tv-pair-form')).to_be_visible()

                    def code(self):
                        response = self.context.request.post(base + '/api/pair/start', data={})
                        assert response.status == 200, response.text()
                        return response.json()['code']

                    def fill(self, code=None, name='Synthetic Living TV'):
                        self.page.locator('#tv-pair-form [name=code]').fill(code or self.code())
                        self.page.locator('#tv-pair-form [name=name]').fill(name)
                        self.page.locator('#tv-pair-form [name=focus]').select_option('member2')
                        self.page.locator('#tv-pair-form [name=calendarView]').select_option('week')

                    def submit(self):
                        self.page.locator('#tv-pair-form button[type=submit]').click()

                    def pending(self):
                        for _ in range(250):
                            if self.held:
                                return
                            self.page.wait_for_timeout(20)
                        raise AssertionError('Expected held actual response')

                    def release(self, fail=False):
                        route, response = self.held.pop(0)
                        if fail:
                            route.fulfill(status=503, content_type='application/json', body='{"error":"SYNTHETIC_OLD_FAILURE"}')
                        else:
                            route.fulfill(response=response)
                        self.page.wait_for_timeout(200)

                    def switch(self, kind, boot=True):
                        if kind == 'household':
                            response = self.context.request.get(base + child_entry)
                            assert response.status == 200
                            login(self.context, password='second-home-password-one')
                        else:
                            login(self.context, 'member2')
                        actual = self.context.request.get(base + '/api/me').json()
                        if boot:
                            self.page.evaluate('boot()')
                            expect(self.page.locator('.ps-sidebar')).to_be_attached()
                            assert self.page.evaluate('user.id') == actual['user']['id']
                            assert self.page.evaluate('user.householdId') == actual['user']['householdId']
                        return actual

                    def draft(self, pair=False):
                        self.page.locator('#dialog .dialog-header [data-action=close]').click()
                        if pair:
                            self.pair()
                            self.fill('BBBBBBBB', 'KEEP_NEW_DRAFT')
                        else:
                            self.page.evaluate('ProductShell.navigate("settings")')
                            self.page.locator('[data-action=profile]').click()
                            self.page.locator('#dialog [name=name]').fill('KEEP_NEW_DRAFT')
                        self.page.evaluate('window.tvNewDraft=document.querySelector("#dialog form")')

                    def assert_draft(self):
                        assert self.page.evaluate('window.tvNewDraft.isConnected')
                        expect(self.page.locator('#dialog [name=name]')).to_have_value('KEEP_NEW_DRAFT')
                        assert 'SYNTHETIC_OLD_FAILURE' not in self.page.locator('#dialog').inner_text()
                        expect(self.page.locator('.tv-devices-flow')).to_have_count(0)

                    def writes(self):
                        return [item for item in self.requests if item == ('POST', '/api/pair/approve')]

                    def close(self):
                        for route, _ in self.held:
                            route.abort()
                        self.context.close()

                flow = Flow()
                tv = browser.new_context(viewport={'width': 1920, 'height': 1080})
                tv.route('**/*', flow.route)
                television = tv.new_page()
                television.on('pageerror', lambda error: errors.append(str(error)))
                try:
                    assert flow.context.request.get(base + '/api/devices').json() == []
                    flow.page.locator('[data-action=devices]').click()
                    expect(flow.page.locator('.tv-devices-flow [data-action=pair]')).to_have_text('连接第一块电视')
                    assert flow.page.locator('#dialog').evaluate('(node)=>node.scrollWidth<=node.clientWidth+1')
                    flow.page.screenshot(path=str(out / 'tv-onboarding-mobile-empty.png'), full_page=True)
                    checks.append('360px_connection_center_zero_devices_has_first_pair_button')
                    flow.page.locator('.tv-devices-flow [data-action=pair]').click()
                    expect(flow.page.locator('#tv-pair-form')).to_be_visible()
                    flow.fill('ZZZZZZZZ')
                    flow.submit()
                    expect(flow.page.locator('#tv-pair-form .error')).to_contain_text('配对码不正确或已过期')
                    expect(flow.page.locator('#tv-pair-form [name=name]')).to_have_value('Synthetic Living TV')
                    expect(flow.page.locator('#tv-pair-form [name=calendarView]')).to_have_value('week')
                    expect(flow.page.locator('#tv-pair-form button[type=submit]')).to_be_enabled()
                    checks.append('invalid_code_preserves_name_focus_view_and_enables_retry')
                    television.goto(base + '/tv')
                    expect(television.locator('.pair-code')).to_be_visible()
                    old_code = television.locator('.pair-code').inner_text().replace(' ', '')
                    sql('UPDATE devices SET expires=? WHERE code=?', (time.time() - 2, old_code))
                    flow.page.locator('#tv-pair-form [name=code]').fill(old_code)
                    flow.submit()
                    expect(flow.page.locator('#tv-pair-form .error')).to_contain_text('配对码不正确或已过期')
                    expect(flow.page.locator('#tv-pair-form [name=name]')).to_have_value('Synthetic Living TV')
                    checks.append('real_expired_code_preserves_draft')
                    television.reload()
                    expect(television.locator('.pair-code')).to_be_visible()
                    code = television.locator('.pair-code').inner_text()
                    flow.page.locator('#tv-pair-form [name=code]').fill(code)
                    flow.submit()
                    expect(flow.page.locator('.device-row')).to_have_count(1)
                    expect(flow.page.locator('.tv-devices-flow')).to_contain_text('电视已连接')
                    devices = flow.context.request.get(base + '/api/devices').json()
                    assert len(devices) == 1 and devices[0]['name'] == 'Synthetic Living TV'
                    assert devices[0]['focus'] == 'member2' and devices[0]['calendarView'] == 'week'
                    expect(television.locator('body.tv .shell')).to_be_visible(timeout=12000)
                    assert tv.request.get(base + '/api/me').json()['user']['role'] == 'tv'
                    assert tv.request.get(base + '/api/devices').status == 403
                    assert tv.request.post(base + '/api/pair/approve', data={'code': 'ZZZZZZZZ'}).status == 403
                    assert tv.request.get(base + '/api/finance-hub/overview').status == 403
                    assert television.locator('[data-action=pair], [data-action=revoke], [data-action=toggle]').count() == 0
                    television.screenshot(path=str(out / 'tv-onboarding-readonly-tv.png'), full_page=True)
                    flow.page.screenshot(path=str(out / 'tv-onboarding-mobile-connected.png'), full_page=True)
                    checks.append('retry_real_pair_poll_tv_cookie_readonly_and_member_list_readback')
                    expect(flow.page.locator('.tv-devices-flow [data-action=pair]')).to_have_text('再连接一块电视')
                    flow.page.locator('[data-action=device-edit]').click()
                    expect(flow.page.locator('#dialog [name=name]')).to_have_value('Synthetic Living TV')
                    flow.page.locator('#dialog [name=name]').fill('Synthetic Updated TV')
                    flow.page.locator('#dialog [name=calendarView]').select_option('around')
                    flow.page.locator('#dialog button[type=submit]').click()
                    expect(flow.page.locator('[data-tv-message]')).to_contain_text('已保存并读取服务器设置')
                    flow.page.locator('[data-tv-display-action=back]').click()
                    expect(flow.page.locator('.tv-devices-flow')).to_be_visible()
                    expect(flow.page.locator('.device-row')).to_contain_text('Synthetic Updated TV')
                    updated = flow.context.request.get(base + '/api/devices').json()[0]
                    assert updated['calendarView'] == 'around' and updated['revision'] > devices[0]['revision']
                    checks.append('existing_device_settings_still_update_name_and_view')
                    flow.page.once('dialog', lambda dialog: dialog.accept())
                    flow.page.locator('[data-action=revoke]').click()
                    expect(flow.page.locator('.device-row')).to_have_count(0)
                    expect(flow.page.locator('.tv-devices-flow [data-action=pair]')).to_have_text('连接第一块电视')
                    assert flow.context.request.get(base + '/api/devices').json() == []
                    assert tv.request.get(base + '/api/state').status == 401
                    checks.append('existing_revoke_revokes_real_tv_cookie_and_returns_first_pair_entry')
                finally:
                    tv.close()
                    flow.close()

                flow = Flow(1440)
                try:
                    flow.devices()
                    flow.page.screenshot(path=str(out / 'tv-onboarding-desktop-empty.png'), full_page=True)
                    flow.page.locator('.tv-devices-flow [data-action=pair]').click()
                    expect(flow.page.locator('#tv-pair-form')).to_be_visible()
                    assert flow.page.locator('#dialog').evaluate('(node)=>node.scrollWidth<=node.clientWidth+1')
                    flow.page.screenshot(path=str(out / 'tv-onboarding-desktop-form.png'), full_page=True)
                    checks.append('1440px_empty_entry_and_pair_form_render_without_overflow')
                finally:
                    flow.close()

                # Delayed real reads and their errors must not adopt a different original modal or actor.
                for source in ['pair_initial_me', 'devices_read']:
                    for failure in [False, True]:
                        flow = Flow()
                        try:
                            endpoint = '/api/me' if source == 'pair_initial_me' else '/api/devices'
                            flow.gate = lambda method, path: method == 'GET' and path == endpoint
                            flow.page.evaluate('void ' + ('pairForm' if source == 'pair_initial_me' else 'devicesModal') + '()')
                            flow.pending()
                            flow.draft()
                            flow.release(failure)
                            flow.assert_draft()
                            assert not flow.writes()
                            checks.append(source + '_late_' + ('503' if failure else 'success') + '_keeps_new_modal')
                        finally:
                            flow.close()

                for actor_change in ['member', 'household']:
                    for failure in [False, True]:
                        flow = Flow()
                        try:
                            flow.gate = lambda method, path: method == 'GET' and path == '/api/devices'
                            flow.page.evaluate('void devicesModal()')
                            flow.pending()
                            flow.switch(actor_change)
                            flow.draft(pair=True)
                            flow.release(failure)
                            flow.assert_draft()
                            assert not flow.writes()
                            checks.append('devices_late_' + ('503' if failure else 'success') + '_new_' + actor_change + '_draft_preserved')
                        finally:
                            flow.close()

                # Writes really reach SQLite once; closing a modal cannot cancel them.
                for target in ['profile', 'new_pair', 'member', 'household', 'same_form_edit', 'readback']:
                    for failure in [False, True]:
                        flow = Flow()
                        try:
                            flow.pair()
                            flow.fill()
                            endpoint = '/api/devices' if target == 'readback' else '/api/pair/approve'
                            method_wanted = 'GET' if target == 'readback' else 'POST'
                            flow.gate = lambda method, path: method == method_wanted and path == endpoint
                            flow.submit()
                            flow.pending()
                            assert sql('SELECT count(*) FROM devices WHERE approved=1')[0][0] == 1
                            if target in ['member', 'household']:
                                flow.switch(target)
                            if target == 'same_form_edit':
                                flow.page.locator('#tv-pair-form [name=name]').fill('KEEP_NEW_DRAFT')
                                flow.page.evaluate('window.tvNewDraft=document.querySelector("#dialog form")')
                            else:
                                flow.draft(pair=target == 'new_pair')
                            flow.release(failure)
                            flow.assert_draft()
                            assert len(flow.writes()) == 1
                            assert sql('SELECT count(*) FROM devices WHERE approved=1')[0][0] == 1
                            checks.append('sent_pair_' + target + '_late_' + ('503' if failure else 'success') + '_one_write_new_context_preserved')
                        finally:
                            flow.close()

                flow = Flow()
                try:
                    flow.pair()
                    flow.fill()
                    flow.gate = lambda method, path: method == 'GET' and path == '/api/me'
                    flow.submit()
                    flow.pending()
                    flow.switch('member')
                    flow.draft(pair=True)
                    flow.release()
                    flow.assert_draft()
                    assert not flow.writes()
                    checks.append('identity_precheck_late_after_member_switch_sends_no_pair_write')
                finally:
                    flow.close()

                for phase in ['read', 'submit']:
                    flow = Flow()
                    try:
                        if phase == 'submit':
                            flow.pair()
                            flow.fill()
                            flow.switch('member', boot=False)
                            flow.submit()
                        else:
                            flow.gate = lambda method, path: method == 'GET' and path == '/api/devices'
                            flow.page.evaluate('void devicesModal()')
                            flow.pending()
                            flow.switch('member', boot=False)
                            flow.release()
                        expect(flow.page.locator('#dialog')).to_contain_text('无法确认当前家庭的登录状态')
                        expect(flow.page.locator('#tv-pair-form')).to_have_count(0)
                        expect(flow.page.locator('.device-row')).to_have_count(0)
                        assert not flow.writes()
                        checks.append('cookie_only_member_switch_' + phase + '_neutral_without_old_content_or_write')
                    finally:
                        flow.close()

                flow = Flow()
                try:
                    flow.switch('household')
                    flow.pair()
                    flow.fill('ZZZZZZZZ')
                    household_id = flow.context.request.get(base + '/api/me').json()['user']['householdId']
                    child_db = Path(folder) / 'spaces' / household_id / 'household.sqlite3'
                    saved = child_db.with_suffix('.test-preserved')
                    child_db.rename(saved)
                    try:
                        assert flow.context.request.get(base + '/api/me').status == 503
                        flow.submit()
                        expect(flow.page.locator('#dialog')).to_contain_text('无法确认当前家庭的登录状态')
                        assert not flow.writes()
                        assert not child_db.exists()
                        checks.append('actual_missing_child_database_fails_closed_without_pair_write_or_empty_database')
                    finally:
                        saved.rename(child_db)
                    flow.pair()
                    expect(flow.page.locator('#tv-pair-form')).to_be_visible()
                    checks.append('restored_child_database_allows_explicit_pair_form_retry')
                finally:
                    flow.close()

                for mode in ['/demo', '/demo?tv=1', '/tv']:
                    sql('DELETE FROM attempts')
                    context = browser.new_context()
                    private = []
                    def public_route(route):
                        request = route.request
                        if not request.url.startswith(base + '/'):
                            external.append(request.url)
                            route.abort()
                        else:
                            path = urlsplit(request.url).path
                            if path == '/api/devices' or path == '/api/pair/approve':
                                private.append((request.method, path))
                            route.continue_()
                    context.route('**/*', public_route)
                    page = context.new_page()
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(base + mode)
                    expect(page.locator('#app')).not_to_contain_text('正在打开家庭看板')
                    page.evaluate('void pairForm(); void devicesModal()')
                    page.wait_for_timeout(150)
                    expect(page.locator('.tv-pair-flow, .tv-devices-flow')).to_have_count(0)
                    assert private == []
                    checks.append(mode + '_no_member_pairing_or_devices_api')
                    context.close()

                browser.close()
            assert not external and not errors, (external, errors)
            after = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}
            evidence['sourceHashesAfter'] = after
            assert hashes == after, 'Actual UI dependencies changed during this run'
            passed = True
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)
            report = {'passed': passed, 'checks': checks, 'sourceHashes': hashes, **evidence,
                      'externalRequests': external, 'pageErrors': errors, 'requestCounts': counts,
                      'productionWrites': 0, 'realCloudWrites': 0, 'financialWrites': 0,
                      'scope': 'Real temporary Flask/SQLite/Edge, two synthetic households; first TV pairing/readback, invalid/expired retry, original settings/revoke happy paths, owned pairing/list async boundaries. Legacy device edit/revoke async handlers are not comprehensively hardened by this change.'}
            (out / 'tv-onboarding-browser-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
