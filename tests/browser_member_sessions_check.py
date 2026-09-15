"""Member session UI: real loopback Flask/SQLite/Edge; synthetic login sessions only."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
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
    names = ['app.py', 'member_sessions.py', 'static/app.js', 'static/index.html',
             'static/product-shell.js', 'static/member-sessions.js', 'static/member-sessions.css',
             'tests/browser_member_sessions_check.py']
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}
    checks, external, errors, details, counts = [], [], [], [], {}
    passed = False
    with tempfile.TemporaryDirectory(prefix='member-sessions-browser-') as folder:
        app = create_app({'TESTING': True, 'SECRET_KEY': 'synthetic-member-sessions-browser-key',
                          'DATA_DIR': folder, 'SESSION_COOKIE_SECURE': False,
                          'MEMBER1_PASSWORD': 'testing-password-one', 'MEMBER2_PASSWORD': 'testing-password-two'})
        assert app.config['SESSION_REFRESH_EACH_REQUEST'] is False
        server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=Quiet)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        database = Path(folder) / 'household.sqlite3'
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)

                def clear_attempts():
                    with closing(sqlite3.connect(database)) as con:
                        con.execute('DELETE FROM attempts')
                        con.commit()

                def login(context, member='member1', password=None):
                    context.request.get(base + '/api/me')  # Actual anonymous bootstrap, no forged cookie/token.
                    result = context.request.post(base + '/api/login', data={'username': member, 'password': password or (
                        'testing-password-one' if member == 'member1' else 'testing-password-two')})
                    assert result.status == 200, result.text()

                def auth(context):
                    return {'X-CSRF-Token': context.request.get(base + '/api/me').json()['csrf']}

                # A second real household is used only for authentication/routing boundary checks.
                seed = browser.new_context()
                login(seed)
                invitation = seed.request.post(base + '/api/spaces/invitations', headers=auth(seed), data={})
                assert invitation.status == 201, invitation.text()
                redeemed = seed.request.post(base + '/api/spaces/redeem', headers=auth(seed), data={
                    'name': 'Synthetic Session Household', 'slug': 'session-browser-second',
                    'invitation': invitation.json()['invitation'], 'MEMBER1_PASSWORD': 'second-home-password-one',
                    'MEMBER2_PASSWORD': 'second-home-password-two'})
                assert redeemed.status == 201, redeemed.text()
                child_entry = redeemed.json()['entry']
                seed.close()

                class Flow:
                    def __init__(self, open_ui=True):
                        clear_attempts()
                        self.context = browser.new_context(viewport={'width': 390, 'height': 844})
                        login(self.context)
                        cleanup = self.context.request.post(base + '/api/sessions/revoke-others', headers=auth(self.context), data={})
                        assert cleanup.status == 200, cleanup.text()
                        self.others = [browser.new_context(user_agent=ua) for ua in [
                            'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 Version/17.0 Safari/605.1.15 SYNTHETIC_RAW_UA_ONE',
                            'Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0 SYNTHETIC_RAW_UA_TWO']]
                        for context in self.others:
                            login(context)
                        self.ids = [next(s['id'] for s in context.request.get(base + '/api/sessions').json()['sessions'] if s['current']) for context in self.others]
                        self.initial = self.context.request.get(base + '/api/sessions').json()
                        assert len(self.initial['sessions']) == 3, self.initial
                        self.held, self.gate, self.requests = [], None, []
                        self.context.route('**/*', self.route)
                        self.page = self.context.new_page()
                        self.page.on('pageerror', lambda error: errors.append(str(error)))
                        self.page.goto(base)
                        expect(self.page.locator('.ps-welcome')).to_be_visible()
                        self.page.evaluate('ProductShell.navigate("settings")')
                        if open_ui:
                            self.open()

                    def route(self, route):
                        request = route.request
                        if not request.url.startswith(base + '/'):
                            external.append({'url': request.url, 'method': request.method})
                            route.abort()
                            return
                        path = urlsplit(request.url).path
                        key = request.method + ' ' + path
                        counts[key] = counts.get(key, 0) + 1
                        if path.startswith('/api/sessions'):
                            self.requests.append({'path': path, 'method': request.method})
                        if self.gate and self.gate(request.method, path):
                            self.gate = None
                            response = route.fetch()
                            assert response.status == 200, response.text()
                            assert 'set-cookie' not in response.headers, response.headers
                            self.held.append((route, response))
                        else:
                            route.continue_()

                    def open(self):
                        self.page.evaluate('void MemberSessions.open()')
                        expect(self.page.locator('.ms-view')).to_be_visible()

                    def review(self, all_others=False):
                        if all_others:
                            self.page.locator('[data-ms=review-others]').click()
                        else:
                            self.page.locator('button[data-ms=review][data-ms-id="' + self.ids[0] + '"]').click()
                        expect(self.page.locator('.ms-confirm')).to_be_visible()

                    def pending(self):
                        for _ in range(250):
                            if self.held:
                                break
                            self.page.wait_for_timeout(20)
                        assert self.held, 'Expected an actual held HTTP response'

                    def release(self, fail=False):
                        route, response = self.held.pop(0)
                        if fail:
                            route.fulfill(status=503, content_type='application/json', body='{"error":"SYNTHETIC_OLD_FAILURE"}')
                        else:
                            route.fulfill(response=response)
                        self.page.wait_for_timeout(140)

                    def switch(self, kind, boot=True):
                        if kind == 'household':
                            self.context.request.get(base + child_entry)
                            login(self.context, password='second-home-password-one')
                        else:
                            login(self.context, 'member2' if kind == 'member' else 'member1')
                        if boot:
                            self.page.evaluate('boot()')
                            expect(self.page.locator('.ps-sidebar')).to_be_attached()
                        return self.context.request.get(base + '/api/me').json()

                    def draft(self):
                        self.page.locator('#dialog [data-action=close]').click()
                        self.page.evaluate('ProductShell.navigate("settings")')
                        self.page.locator('[data-action=profile]').click()
                        self.page.locator('#dialog [name=name]').fill('KEEP_NEW_DRAFT')
                        self.page.evaluate('window.memberSessionNewNode=document.querySelector("#dialog form")')

                    def assert_draft(self):
                        assert self.page.evaluate('window.memberSessionNewNode.isConnected')
                        expect(self.page.locator('#dialog [name=name]')).to_have_value('KEEP_NEW_DRAFT')
                        expect(self.page.locator('.member-sessions')).to_have_count(0)
                        assert 'SYNTHETIC_OLD_FAILURE' not in self.page.locator('#dialog').inner_text()

                    def writes(self):
                        return [item for item in self.requests if item['method'] in ('DELETE', 'POST')]

                    def close(self):
                        for route, _ in self.held:
                            route.abort()
                        self.context.close()
                        for context in self.others:
                            context.close()

                flow = Flow(False)
                try:
                    flow.page.locator('[data-member-sessions-open]').click()
                    expect(flow.page.locator('.ms-card')).to_have_count(3)
                    expect(flow.page.locator('.ms-card.is-current')).to_have_count(1)
                    expect(flow.page.locator('[data-ms=review]')).to_have_count(2)
                    text = flow.page.locator('.member-sessions').inner_text()
                    assert '5 分钟' in text and '不能精确识别物理设备' in text
                    assert 'SYNTHETIC_RAW_UA' not in text and '127.0.0.1' not in text
                    for session in flow.initial['sessions']:
                        assert set(session) == {'id', 'device', 'createdAt', 'lastSeenAt', 'expiresAt', 'current'}
                    assert not flow.writes()
                    checks.append('settings_entry_current_and_others_safe_server_fields_no_mutation')
                    for width, height, theme in [(360, 800, 'forest'), (1440, 1000, 'light'), (360, 800, 'ocean')]:
                        flow.page.set_viewport_size({'width': width, 'height': height})
                        flow.page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
                        assert flow.page.evaluate('document.querySelector("#dialog").scrollWidth<=document.querySelector("#dialog").clientWidth+1')
                        assert flow.page.locator('.member-sessions .btn').evaluate_all('(nodes)=>nodes.every(node=>node.getBoundingClientRect().height>=44)')
                        flow.page.screenshot(path=str(out / f'member-sessions-{width}-{theme}.png'), full_page=True)
                    checks.append('360_and_1440_theme_compatible_no_dialog_horizontal_overflow')
                    flow.review()
                    assert not flow.writes()
                    flow.page.locator('[data-ms=refresh]').click()
                    expect(flow.page.locator('.ms-card')).to_have_count(3)
                    assert not flow.writes()
                    checks.append('explicit_confirmation_cancel_returns_list_without_revoke')
                    flow.review()
                    flow.page.locator('[data-ms=confirm]').click()
                    expect(flow.page.locator('.ms-card')).to_have_count(2)
                    assert flow.others[0].request.get(base + '/api/state').status == 401
                    assert flow.others[1].request.get(base + '/api/state').status == 200
                    assert flow.context.request.get(base + '/api/state').status == 200
                    assert len(flow.writes()) == 1
                    checks.append('single_revoke_real_readback_target401_current_and_other_preserved')
                finally:
                    flow.close()

                flow = Flow()
                partner = browser.new_context()
                try:
                    login(partner, 'member2')
                    flow.review(True)
                    assert not flow.writes()
                    flow.page.locator('[data-ms=confirm]').click()
                    expect(flow.page.locator('.ms-card')).to_have_count(1)
                    expect(flow.page.locator('.ms-message')).to_contain_text('已退出 2 个')
                    expect(flow.page.locator('[data-ms=review-others]')).to_be_disabled()
                    assert all(context.request.get(base + '/api/state').status == 401 for context in flow.others)
                    assert partner.request.get(base + '/api/state').status == 200
                    assert flow.context.request.get(base + '/api/state').status == 200
                    checks.append('revoke_others_preserves_current_and_other_member_actual_sessions')
                finally:
                    partner.close()
                    flow.close()

                # Failed GET/write keeps a useful original retry path; no implicit write retry.
                for operation in ['read', 'write']:
                    flow = Flow()
                    try:
                        if operation == 'write':
                            flow.review()
                        suffix = '/api/sessions' if operation == 'read' else '/api/sessions/' + flow.ids[0]
                        flow.page.route('**' + suffix, lambda route: route.fulfill(status=503, content_type='application/json', body='{"error":"SYNTHETIC_503"}'))
                        flow.page.locator('[data-ms=' + ('refresh' if operation == 'read' else 'confirm') + ']').click()
                        expect(flow.page.locator('.ms-message')).to_contain_text('SYNTHETIC_503')
                        expect(flow.page.locator('[data-ms=' + ('refresh' if operation == 'read' else 'confirm') + ']')).to_be_enabled()
                        assert flow.others[0].request.get(base + '/api/state').status == 200
                        flow.page.unroute('**' + suffix)
                        flow.page.locator('[data-ms=' + ('refresh' if operation == 'read' else 'confirm') + ']').click()
                        expect(flow.page.locator('.ms-card')).to_have_count(3 if operation == 'read' else 2)
                        checks.append(operation + '_503_original_view_retained_explicit_retry')
                    finally:
                        flow.close()

                # Real cookie-only switching must reject the old confirmation before any write.
                for identity in ['member', 'household', 'csrf']:
                    flow = Flow()
                    try:
                        flow.review()
                        owner = flow.page.evaluate('({id:user.id,household:user.householdId,csrf})')
                        fresh = flow.switch(identity, False)
                        assert flow.page.evaluate('csrf') == owner['csrf'] and fresh['csrf'] != owner['csrf']
                        flow.page.locator('[data-ms=confirm]').click()
                        expect(flow.page.locator('.ms-empty')).to_contain_text('登录状态已变化')
                        assert not flow.writes()
                        assert not flow.page.locator('.ms-card').count()
                        checks.append('cookie_only_' + identity + '_old_confirmation_rejected_no_write')
                    finally:
                        flow.close()

                flow = Flow()
                try:
                    flow.review()
                    original = next(item['id'] for item in flow.initial['sessions'] if item['current'])
                    assert flow.others[0].request.delete(base + '/api/sessions/' + original, headers=auth(flow.others[0]), data={}).status == 200
                    flow.page.locator('[data-ms=confirm]').click()
                    expect(flow.page.locator('.ms-empty')).to_contain_text('登录状态已变化')
                    assert not flow.writes()
                    assert flow.context.request.get(base + '/api/state').status == 401
                    checks.append('current_session_revoked_elsewhere_blocks_pending_confirmation')
                finally:
                    flow.close()

                # Fetch actual responses before delaying delivery; late success/error must not own new DOM.
                for stage in ['read', 'review_me', 'write', 'readback']:
                    for transition in ['draft', 'member']:
                        for failure in [False, True]:
                            flow = Flow()
                            try:
                                if stage in ('write', 'readback'):
                                    flow.review()
                                if stage in ('read', 'readback'):
                                    flow.gate = lambda method, path: method == 'GET' and path == '/api/sessions'
                                elif stage == 'review_me':
                                    flow.gate = lambda method, path: method == 'GET' and path == '/api/me'
                                else:
                                    flow.gate = lambda method, path: method == 'DELETE'
                                if stage == 'read':
                                    flow.page.locator('[data-ms=refresh]').click()
                                elif stage == 'review_me':
                                    flow.page.locator('[data-ms=review]').first.click()
                                else:
                                    flow.page.locator('[data-ms=confirm]').click()
                                flow.pending()
                                if transition == 'member':
                                    fresh = flow.switch('member')
                                    assert fresh['user']['id'] == 'member2'
                                flow.draft()
                                flow.release(failure)
                                flow.assert_draft()
                                expected_writes = 1 if stage in ('write', 'readback') else 0
                                assert len(flow.writes()) == expected_writes, flow.writes()
                                if expected_writes:
                                    assert flow.others[0].request.get(base + '/api/state').status == 401
                                checks.append(f'{stage}:late_{"503" if failure else "success"}:{transition}:new_form_preserved')
                            finally:
                                flow.close()

                for failure in [False, True]:
                    flow = Flow()
                    try:
                        flow.gate = lambda method, path: method == 'GET' and path == '/api/sessions'
                        flow.page.locator('[data-ms=refresh]').click()
                        flow.pending()
                        flow.switch('member')
                        flow.open()
                        flow.page.evaluate('window.memberSessionNewNode=document.querySelector(".member-sessions")')
                        visible_ids = flow.page.locator('.ms-card').evaluate_all('(nodes)=>nodes.map(node=>node.dataset.msId)')
                        flow.release(failure)
                        assert flow.page.evaluate('window.memberSessionNewNode.isConnected')
                        assert flow.page.locator('.ms-card').evaluate_all('(nodes)=>nodes.map(node=>node.dataset.msId)') == visible_ids
                        assert not set(visible_ids).intersection(flow.ids)
                        assert 'SYNTHETIC_OLD_FAILURE' not in flow.page.locator('#dialog').inner_text()
                        assert not flow.writes()
                        checks.append('old_read_' + ('503' if failure else 'success') + '_cannot_replace_new_member_session_modal')
                    finally:
                        flow.close()

                # A second in-flight button supersedes the first while each button stays retryable.
                flow = Flow()
                try:
                    for selector in ['[data-ms=refresh]', '[data-ms=review-others]']:
                        flow.gate = lambda method, path: method == 'GET' and path == '/api/me'
                        flow.page.locator(selector).click()
                        wanted = 1 if selector == '[data-ms=refresh]' else 2
                        for _ in range(250):
                            if len(flow.held) == wanted:
                                break
                            flow.page.wait_for_timeout(20)
                        assert len(flow.held) == wanted
                    first = flow.held.pop(0)
                    flow.release(True)
                    expect(flow.page.locator('[data-ms=review-others]')).to_be_enabled()
                    flow.held.append(first)
                    flow.release()
                    expect(flow.page.locator('[data-ms=refresh]')).to_be_enabled()
                    expect(flow.page.locator('.ms-confirm')).to_have_count(0)
                    assert not flow.writes()
                    checks.append('two_buttons_late_request_new503_both_can_retry_no_old_confirmation')
                finally:
                    flow.close()

                for mode in ['/demo', '/demo?tv=1', '/tv']:
                    context = browser.new_context()
                    requests = []
                    def public_route(route):
                        if not route.request.url.startswith(base + '/'):
                            external.append({'url': route.request.url, 'method': route.request.method})
                            route.abort()
                        else:
                            if '/api/sessions' in route.request.url:
                                requests.append(route.request.url)
                            route.continue_()
                    context.route('**/*', public_route)
                    page = context.new_page()
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(base + mode)
                    expect(page.locator('#app')).not_to_contain_text('正在打开家庭看板')
                    page.evaluate('void MemberSessions.open()')
                    page.wait_for_timeout(120)
                    assert page.locator('[data-member-sessions-open]').count() == 0
                    assert page.locator('.member-sessions').count() == 0
                    assert requests == []
                    checks.append(mode + ':no_entry_no_private_session_request')
                    context.close()

                browser.close()
            assert not errors and not external, (errors, external)
            assert hashes == {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}
            passed = True
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)
            report = {'passed': passed, 'checks': checks, 'details': details, 'sourceHashes': hashes,
                      'externalRequests': external, 'pageErrors': errors, 'requestCounts': counts,
                      'productionWrites': 0, 'realCloudWrites': 0, 'financialWrites': 0,
                      'scope': 'Real local authentication and session revocations; synthetic members/household; delayed actual responses; no production or external providers.'}
            (out / 'member-sessions-browser-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
