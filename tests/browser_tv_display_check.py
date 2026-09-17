"""Real loopback TV layouts and member-editor races; synthetic households only."""
from contextlib import closing
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from app import create_app
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server, WSGIRequestHandler

CARDS = ['calendar', 'finance', 'tasks', 'shopping', 'trips']
DEFAULT = {'order': CARDS, 'hidden': [], 'theme': 'forest', 'density': 'comfortable'}


class Quiet(WSGIRequestHandler):
    def log(self, *_args, **_kwargs):
        pass


def main():
    out = ROOT / 'test-results'
    out.mkdir(exist_ok=True)
    paths = set(ROOT.glob('*.py')) | {ROOT / 'tests/browser_tv_display_check.py'}
    paths.update(p for p in (ROOT / 'static').rglob('*') if p.is_file())
    hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
    checks, errors, external, counts, details, screenshots = [], [], [], {}, [], []
    report = {'passed': False, 'checks': checks, 'pageErrors': errors, 'externalRequests': external,
              'requestCounts': counts, 'sourceHashes': hashes, 'details': details, 'screenshots': screenshots,
              'realCloudWrites': 0, 'productionWrites': 0, 'realPrivateInputs': 0,
              'scope': 'Actual temporary Flask/SQLite/Edge; two independently paired televisions, two synthetic households; TV layout, original editor ownership and delayed actual responses.'}

    def passed(name):
        checks.append(name)

    with tempfile.TemporaryDirectory(prefix='tv-display-browser-') as folder:
        app = create_app({'TESTING': True, 'SECRET_KEY': 'synthetic-tv-display-secret', 'DATA_DIR': folder,
                          'SESSION_COOKIE_SECURE': False, 'MEMBER1_PASSWORD': 'testing-password-one',
                          'MEMBER2_PASSWORD': 'testing-password-two', 'MICROSOFT_CLIENT_ID': '',
                          'GOOGLE_CLIENT_ID': '', 'OPENAI_API_KEY': ''})
        assert app.config['SESSION_REFRESH_EACH_REQUEST'] is False
        database = Path(folder) / 'household.sqlite3'
        server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=Quiet)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)

                def sql(statement, parameters=()):
                    with closing(sqlite3.connect(database)) as con:
                        rows = con.execute(statement, parameters).fetchall()
                        con.commit()
                        return rows

                def auth(context):
                    me = context.request.get(base + '/api/me')
                    assert me.status == 200 and me.json()['user']['role'] == 'member'
                    return {'X-CSRF-Token': me.json()['csrf']}

                def login(context, number=1, child=False):
                    context.request.get(base + '/api/me')
                    password = ('second-home-password-' if child else 'testing-password-') + ('one' if number == 1 else 'two')
                    result = context.request.post(base + '/api/login', data={'username': f'member{number}', 'password': password})
                    assert result.status == 200, result.status

                def device(context, rid):
                    result = context.request.get(base + '/api/devices')
                    assert result.status == 200
                    return next(x for x in result.json() if x['id'] == rid)

                def patch(context, rid, **changes):
                    old = device(context, rid)
                    value = {k: old[k] for k in ['name', 'focus', 'calendarView', 'revision', 'layout']}
                    result = context.request.patch(base + '/api/devices/' + rid, headers=auth(context), data={**value, **changes})
                    assert result.status == 200, result.status
                    return device(context, rid)

                def screenshot(page, name):
                    page.screenshot(path=str(out / name), full_page=True)
                    screenshots.append(name)

                def no_overflow(page, selector='body'):
                    assert page.locator(selector).evaluate('(n)=>n.scrollWidth<=n.clientWidth+2'), selector
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')

                def observed_context(**kwargs):
                    context = browser.new_context(**kwargs)
                    def route(r):
                        u = urlsplit(r.request.url)
                        if not r.request.url.startswith(base + '/'):
                            external.append({'method': r.request.method, 'host': u.hostname, 'path': u.path})
                            r.abort()
                        else:
                            key = r.request.method + ' ' + u.path
                            counts[key] = counts.get(key, 0) + 1
                            r.continue_()
                    context.route('**/*', route)
                    return context

                seed = observed_context()
                login(seed)
                invitation = seed.request.post(base + '/api/spaces/invitations', headers=auth(seed), data={})
                assert invitation.status == 201
                created = seed.request.post(base + '/api/spaces/redeem', headers=auth(seed), data={
                    'name': 'Synthetic TV Display Household', 'slug': 'synthetic-tv-display-second',
                    'invitation': invitation.json()['invitation'], 'MEMBER1_PASSWORD': 'second-home-password-one',
                    'MEMBER2_PASSWORD': 'second-home-password-two'})
                assert created.status == 201
                child_entry = created.json()['entry']

                def pair(label, focus):
                    context = observed_context(viewport={'width': 1920, 'height': 1080})
                    token = context.request.post(base + '/api/pair/start', data={})
                    assert token.status == 200
                    result = seed.request.post(base + '/api/pair/approve', headers=auth(seed), data={
                        'code': token.json()['code'], 'name': label, 'focus': focus, 'calendarView': 'today'})
                    assert result.status == 200
                    result = context.request.post(base + '/api/pair/poll', data={'secret': token.json()['secret']})
                    assert result.status == 200 and result.json()['approved'] is True
                    records = seed.request.get(base + '/api/devices').json()
                    rid = next(x['id'] for x in records if x['name'] == label)
                    page = context.new_page()
                    page.on('pageerror', lambda exc: errors.append(str(exc)))
                    page.goto(base + '/tv')
                    expect(page.locator('body.tv .board[data-tv-count]')).to_be_visible()
                    return context, page, rid

                tv1, screen1, first_id = pair('SYNTHETIC_LIVING_TV', 'member1')
                tv2, screen2, second_id = pair('SYNTHETIC_SECOND_TV', 'member2')
                assert device(seed, first_id)['layout'] == DEFAULT
                assert device(seed, second_id)['layout'] == DEFAULT
                passed('existing_paired_devices_get_five_card_forest_comfortable_defaults')

                today = datetime.now(ZoneInfo('Asia/Shanghai')).date()
                shared_rows = [
                    ('tasks', {'title': '合成共同待办：确认周末安排', 'owner': 'shared'}),
                    ('shopping', {'title': '合成采购：补充家庭用品', 'quantity': '一份', 'owner': 'shared'}),
                    ('events', {'title': '合成家庭日程：完整标题与地点', 'owner': 'shared', 'start': str(today) + 'T10:00:00+08:00',
                                'end': str(today) + 'T11:00:00+08:00', 'location': '合成地点，不对应真实预订'}),
                    ('trips', {'title': '合成旅行计划', 'destination': '合成城市', 'start': str(today + timedelta(days=5)),
                               'end': str(today + timedelta(days=8)), 'budget': 10000, 'saved': 2000, 'paid': 0, 'note': ''}),
                ]
                for kind, value in shared_rows:
                    result = seed.request.post(base + '/api/items/' + kind, headers=auth(seed), data=value)
                    assert result.status in {200, 201}, (kind, result.status)
                secret_asset = seed.request.post(base + '/api/finance-hub/investments', headers=auth(seed), data={
                    'name': 'SYNTHETIC_PRIVATE_TV_EXCLUDED', 'institution': 'SYNTHETIC_PRIVATE_INSTITUTION',
                    'assetType': '基金', 'currency': 'USD', 'quantity': '1', 'cost': '10', 'value': '11', 'asOf': str(today), 'note': ''})
                assert secret_asset.status == 201
                private_before = sql('SELECT id,owner,data,revision FROM hub_investments ORDER BY id')
                home = {'revision': 0, 'order': ['trips', 'tasks', 'shopping', 'calendar', 'finance'], 'hidden': ['finance']}
                saved_home = seed.request.put(base + '/api/dashboard-layout', headers=auth(seed), data=home)
                assert saved_home.status == 200
                home_before = saved_home.json()

                class Flow:
                    def __init__(self, width=360):
                        sql('DELETE FROM attempts')
                        self.context = browser.new_context(viewport={'width': width, 'height': 900})
                        login(self.context)
                        self.held, self.gate, self.calls = [], None, []
                        self.context.route('**/*', self.route)
                        self.page = self.context.new_page()
                        self.page.on('pageerror', lambda exc: errors.append(str(exc)))
                        self.page.goto(base)
                        expect(self.page.locator('.ps-welcome')).to_be_visible()

                    def route(self, route):
                        request = route.request
                        path = urlsplit(request.url).path
                        if not request.url.startswith(base + '/'):
                            external.append({'method': request.method, 'path': path})
                            route.abort()
                            return
                        self.calls.append((request.method, path))
                        key = request.method + ' ' + path
                        counts[key] = counts.get(key, 0) + 1
                        if self.gate and self.gate(request.method, path):
                            self.gate = None
                            response = route.fetch()
                            assert 'set-cookie' not in response.headers, 'Read/write response must not refresh member cookie'
                            self.held.append((route, response))
                        else:
                            route.continue_()

                    def open(self, rid=first_id, wait=True):
                        self.page.evaluate('id=>void TVDisplay.openDevice(id)', rid)
                        if wait:
                            expect(self.page.locator('#tv-display-form [name=name]')).to_have_value(device(self.context, rid)['name'])
                        return self

                    def form(self):
                        return self.page.locator('#tv-display-form')

                    def fill_layout(self, order=CARDS, hidden=(), theme='forest', density='comfortable'):
                        form = self.form()
                        for key in CARDS:
                            form.locator(f'[name=visible][value="{key}"]').set_checked(key not in hidden)
                        for wanted, key in enumerate(order):
                            for _ in range(6):
                                current = form.locator('[data-tv-card-row]').evaluate_all('(rows)=>rows.map(n=>n.dataset.tvCardRow)')
                                if current.index(key) == wanted:
                                    break
                                form.locator(f'[data-tv-display-action=up][data-key="{key}"]').click()
                            assert form.locator('[data-tv-card-row]').evaluate_all('(rows)=>rows.map(n=>n.dataset.tvCardRow)') == list(order[:wanted+1]) + [x for x in current if x not in order[:wanted+1]]
                        form.locator(f'[data-theme-choice="{theme}"]').click()
                        form.locator('[name=density]').select_option(density)

                    def save(self, status=200):
                        with self.page.expect_response(lambda r: r.request.method == 'PATCH' and urlsplit(r.url).path.startswith('/api/devices/')) as response:
                            self.form().locator('button[type=submit]').click()
                        assert response.value.status == status, response.value.status
                        self.page.wait_for_timeout(100)

                    def hold(self, method, path):
                        self.gate = lambda m, p: (m, p) == (method, path)

                    def pending(self):
                        for _ in range(300):
                            if self.held:
                                return
                            self.page.wait_for_timeout(20)
                        raise AssertionError('Expected a delayed real HTTP response')

                    def release(self, result='success'):
                        route, response = self.held.pop(0)
                        if result == 'error':
                            route.fulfill(status=503, content_type='application/json', body='{"error":"SYNTHETIC_OLD_TV_FAILURE"}')
                        elif result == 'missing-me':
                            route.fulfill(status=200, content_type='application/json', body='{}')
                        else:
                            route.fulfill(response=response)
                        self.page.wait_for_timeout(220)

                    def switch(self, mode, boot=True):
                        if mode == 'household':
                            self.context.request.get(base + child_entry)
                            login(self.context, child=True)
                        else:
                            login(self.context, 2)
                        actual = self.context.request.get(base + '/api/me').json()['user']
                        if boot:
                            self.page.evaluate('void boot()')
                            self.page.wait_for_function('(me)=>user?.id===me.id && user?.householdId===me.householdId', arg=actual)

                    def new_draft(self):
                        self.page.evaluate('profileForm()')
                        self.page.locator('#dialog [name=name]').fill('KEEP_NEW_TV_DRAFT')
                        self.page.evaluate('window.syntheticTVNewDraft=document.querySelector("#dialog form")')

                    def assert_draft(self):
                        assert self.page.evaluate('window.syntheticTVNewDraft?.isConnected')
                        expect(self.page.locator('#dialog [name=name]')).to_have_value('KEEP_NEW_TV_DRAFT')
                        assert 'SYNTHETIC_OLD_TV_FAILURE' not in self.page.locator('#dialog').inner_text()

                    def patch_calls(self):
                        return sum(method == 'PATCH' and path.startswith('/api/devices/') for method, path in self.calls)

                    def close(self):
                        self.context.close()

                flow = Flow().open()
                try:
                    before_revision = tv1.request.get(base + '/api/state').json()['revision']
                    wanted = ['tasks', 'shopping', 'trips', 'calendar', 'finance']
                    flow.fill_layout(wanted, ['finance'], 'ocean', 'compact')
                    flow.form().locator('[name=name]').fill('SYNTHETIC_LIVING_UPDATED')
                    flow.form().locator('[name=focus]').select_option('member2')
                    flow.form().locator('[name=calendarView]').select_option('week')
                    flow.save()
                    saved = device(seed, first_id)
                    assert saved['layout'] == {'order': wanted, 'hidden': ['finance'], 'theme': 'ocean', 'density': 'compact'}
                    assert saved['focus'] == 'member2' and saved['calendarView'] == 'week'
                    # Observe the actual interval refresh for the first edited device.
                    expect(screen1.locator('.board')).to_have_attribute('data-tv-count', '4', timeout=15000)
                    expect(screen1.locator('body')).to_have_attribute('data-tv-theme', 'ocean')
                    expect(screen1.locator('body')).to_have_attribute('data-tv-density', 'compact')
                    assert screen1.locator('.board > [data-tv-card]:not([hidden])').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.tvCard)') == wanted[:-1]
                    assert tv1.request.get(base + '/api/state').json()['display']['layout'] == saved['layout']
                    assert tv1.request.get(base + '/api/state').json()['revision'] != before_revision
                    assert device(seed, second_id)['layout'] == DEFAULT
                    assert tv2.request.get(base + '/api/state').json()['display']['layout'] == DEFAULT
                    assert seed.request.get(base + '/api/dashboard-layout').json() == home_before
                    passed('phone_changes_first_tv_order_hidden_theme_density_focus_view_and_poll_refreshes_only_that_tv')

                    flow.open(second_id)
                    second_order = ['trips', 'finance', 'calendar', 'shopping', 'tasks']
                    flow.fill_layout(second_order, ['tasks', 'shopping'], 'light', 'comfortable')
                    flow.save()
                    screen2.evaluate('refresh(true)')
                    expect(screen2.locator('.board')).to_have_attribute('data-tv-count', '3')
                    assert device(seed, first_id)['layout'] == saved['layout']
                    passed('second_tv_has_independent_three_card_light_layout')

                    for width, height in [(1280, 720), (1920, 1080), (3840, 2160)]:
                        screen1.set_viewport_size({'width': width, 'height': height})
                        for visible in range(1, 6):
                            flow.open(first_id)
                            flow.fill_layout(CARDS, CARDS[visible:], 'ocean', 'compact' if visible >= 4 else 'comfortable')
                            flow.save()
                            screen1.evaluate('refresh(true)')
                            expect(screen1.locator('.board')).to_have_attribute('data-tv-count', str(visible))
                            assert screen1.locator('.board > [data-tv-card]:not([hidden])').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.tvCard)') == CARDS[:visible]
                            no_overflow(screen1)
                            no_overflow(screen1, '.board')
                            bounds = screen1.locator('.board > [data-tv-card]:not([hidden])').evaluate_all('(nodes)=>nodes.map(n=>({width:n.getBoundingClientRect().width,height:n.getBoundingClientRect().height,font:parseFloat(getComputedStyle(n).fontSize)}))')
                            assert all(x['width'] > 100 and x['height'] > 80 for x in bounds)
                            details.append({'kind': 'viewport', 'width': width, 'height': height, 'visibleCards': visible, 'cardBounds': bounds})
                            passed(f'{width}x{height}_{visible}_visible_cards_order_and_no_horizontal_overflow')
                            if visible in {1, 5}:
                                screenshot(screen1, f'tv-display-{width}-{visible}-cards.png')

                    theme_values = []
                    for theme in ['forest', 'light', 'ocean']:
                        prefs = seed.request.get(base + '/api/preferences').json()
                        changed = seed.request.put(base + '/api/preferences', headers=auth(seed), data={'revision': prefs['revision'], 'changes': {'theme': theme}})
                        assert changed.status == 200
                        flow.page.evaluate('void boot()')
                        expect(flow.page.locator('.ps-welcome')).to_be_visible()
                        flow.open(first_id)
                        flow.fill_layout(CARDS, ['trips'], theme, 'comfortable')
                        no_overflow(flow.page, '#dialog')
                        expect(flow.form().locator('button[type=submit]')).to_be_enabled()
                        screenshot(flow.page, f'tv-display-phone-{theme}-360.png')
                        flow.save()
                        screen1.evaluate('refresh(true)')
                        expect(screen1.locator('.board')).to_have_attribute('data-tv-count', '4')
                        theme_values.append(screen1.evaluate('getComputedStyle(document.body).getPropertyValue("--bg").trim()'))
                        passed(f'phone_360_{theme}_settings_usable_and_tv_theme_saved')
                    assert len(set(theme_values)) == 3
                    passed('tv_three_themes_have_distinct_actual_rendered_palette')
                finally:
                    flow.close()

                for television in [tv1, tv2]:
                    state = television.request.get(base + '/api/state')
                    assert state.status == 200 and 'SYNTHETIC_PRIVATE' not in state.text()
                    assert television.request.get(base + '/api/finance-hub/overview').status == 403
                    assert television.request.get(base + '/api/devices').status == 403
                    assert television.request.patch(base + '/api/devices/' + first_id, data={'revision': 1, 'layout': DEFAULT}).status == 403
                assert seed.request.get(base + '/api/dashboard-layout').json() == home_before
                assert sql('SELECT id,owner,data,revision FROM hub_investments ORDER BY id') == private_before
                passed('tv_cannot_write_layout_or_read_private_finance_and_member_home_layout_remains_private')

                # Actual CAS conflict, preserving the draft until an explicit reload decision.
                for choice in ['keep-draft', 'use-latest']:
                    flow = Flow().open()
                    try:
                        flow.form().locator('[name=name]').fill('KEEP_CONFLICT_DRAFT')
                        newer = patch(seed, first_id, name='LATEST_SERVER_TV')
                        flow.save(status=409)
                        expect(flow.form().locator('[name=name]')).to_have_value('KEEP_CONFLICT_DRAFT')
                        expect(flow.page.locator('[data-tv-display-action=reload]:visible').first).to_be_visible()
                        written = flow.patch_calls()
                        flow.page.locator('[data-tv-display-action=reload]:visible').first.click()
                        flow.page.locator(f'[data-tv-display-action={choice}]').click()
                        expect(flow.form().locator('[name=name]')).to_have_value('KEEP_CONFLICT_DRAFT' if choice == 'keep-draft' else newer['name'])
                        assert flow.patch_calls() == written
                        if choice == 'keep-draft':
                            flow.save()
                            assert device(seed, first_id)['name'] == 'KEEP_CONFLICT_DRAFT'
                            assert flow.patch_calls() == written + 1
                        passed('actual_409_preserves_draft_and_explicit_reload_' + choice)
                    finally:
                        flow.close()

                flow = Flow().open()
                try:
                    old = device(seed, first_id)
                    flow.form().locator('[name=name]').fill('DOUBLE_CLICK_ONCE')
                    flow.hold('PATCH', '/api/devices/' + first_id)
                    flow.form().locator('button[type=submit]').evaluate('(n)=>{n.click();n.click()}')
                    flow.pending()
                    assert flow.patch_calls() == 1
                    flow.release()
                    assert device(seed, first_id)['revision'] == old['revision'] + 1
                    assert flow.patch_calls() == 1
                    passed('double_click_while_write_pending_sends_exactly_one_patch')
                finally:
                    flow.close()

                for phase in ['identity', 'patch', 'readback']:
                    flow = Flow().open()
                    try:
                        old = device(seed, first_id)
                        flow.form().locator('[name=name]').fill('EXPLICIT_SUBMIT_ONCE')
                        method, path = ('GET', '/api/me') if phase == 'identity' else (
                            ('PATCH', '/api/devices/' + first_id) if phase == 'patch' else ('GET', '/api/devices'))
                        flow.hold(method, path)
                        flow.form().evaluate('(form)=>{form.requestSubmit();form.requestSubmit()}')
                        flow.pending()
                        flow.form().evaluate('(form)=>form.requestSubmit()')
                        assert flow.patch_calls() == (0 if phase == 'identity' else 1)
                        flow.release()
                        flow.page.wait_for_timeout(180)
                        assert flow.patch_calls() == 1
                        assert device(seed, first_id)['revision'] == old['revision'] + 1
                        passed('repeated_form_submit_during_' + phase + '_does_not_resend')
                    finally:
                        flow.close()

                for operation in ['reload', 'write', 'readback']:
                    flow = Flow().open()
                    try:
                        flow.form().locator('[name=name]').fill('ORIGINAL_SENT_DRAFT')
                        old_form = flow.form().element_handle()
                        flow.hold('PATCH' if operation == 'write' else 'GET', '/api/devices/' + first_id if operation == 'write' else '/api/devices')
                        if operation == 'reload':
                            flow.page.locator('[data-tv-display-action=reload]:visible').first.click()
                        else:
                            flow.form().evaluate('(form)=>form.requestSubmit()')
                        flow.pending()
                        flow.form().locator('[name=name]').fill('KEEP_SAME_FORM_EDIT')
                        if operation != 'reload':
                            flow.form().evaluate('(form)=>form.requestSubmit()')
                        flow.release()
                        assert old_form.evaluate('(form)=>form.isConnected')
                        expect(flow.form().locator('[name=name]')).to_have_value('KEEP_SAME_FORM_EDIT')
                        assert flow.patch_calls() == (0 if operation == 'reload' else 1)
                        expect(flow.page.locator('[data-tv-display-action=reload]:visible').first).to_be_visible()
                        if operation != 'reload':
                            assert device(seed, first_id)['name'] == 'ORIGINAL_SENT_DRAFT'
                        passed('late_' + operation + '_preserves_same_form_edits_without_automatic_resubmit')
                    finally:
                        flow.close()

                # Delayed original reads, writes and post-write list readbacks may
                # finish on the server; they must not replace a later UI workflow.
                for operation in ['read', 'write', 'readback']:
                    for ending in ['new-device', 'new-dialog', 'close', 'member', 'household']:
                        for result in ['success', 'error']:
                            flow = Flow()
                            try:
                                if operation == 'read':
                                    flow.hold('GET', '/api/devices')
                                    flow.open(wait=False)
                                else:
                                    flow.open()
                                    flow.form().locator('[name=name]').fill('SENT_OLD_TV_DRAFT')
                                    flow.hold('PATCH' if operation == 'write' else 'GET', '/api/devices/' + first_id if operation == 'write' else '/api/devices')
                                    flow.form().locator('button[type=submit]').click()
                                flow.pending()
                                sent = flow.patch_calls()
                                if ending == 'new-device':
                                    flow.open(second_id)
                                    flow.form().locator('[name=name]').fill('KEEP_SECOND_TV_DRAFT')
                                    flow.page.evaluate('window.syntheticTVLaterForm=document.querySelector("#tv-display-form")')
                                elif ending == 'close':
                                    flow.page.locator('#dialog .dialog-header [data-action=close]').click()
                                else:
                                    if ending in {'member', 'household'}:
                                        flow.switch(ending)
                                    flow.new_draft()
                                flow.release(result)
                                if ending == 'new-device':
                                    assert flow.page.evaluate('window.syntheticTVLaterForm.isConnected')
                                    expect(flow.form().locator('[name=name]')).to_have_value('KEEP_SECOND_TV_DRAFT')
                                    assert 'SYNTHETIC_OLD_TV_FAILURE' not in flow.page.locator('#dialog').inner_text()
                                elif ending == 'close':
                                    assert flow.page.evaluate('!document.querySelector("#dialog").open')
                                else:
                                    flow.assert_draft()
                                assert flow.patch_calls() == sent
                                details.append({'kind': 'delayed', 'operation': operation, 'ending': ending, 'result': result,
                                                'patchCount': sent, 'noAutomaticResend': True, 'oldResponseSetCookie': False})
                                passed('late_' + operation + '_' + result + '_cannot_replace_' + ending)
                            finally:
                                flow.close()

                for endpoint in ['me', 'devices']:
                    flow = Flow()
                    try:
                        flow.hold('GET', '/api/' + endpoint)
                        flow.open(wait=False)
                        flow.pending()
                        flow.open(second_id)
                        flow.form().locator('[name=name]').fill('KEEP_AFTER_MISSING_IDENTITY')
                        flow.release('missing-me' if endpoint == 'me' else 'error')
                        expect(flow.form().locator('[name=name]')).to_have_value('KEEP_AFTER_MISSING_IDENTITY')
                        assert flow.patch_calls() == 0
                        passed('late_' + endpoint + '_failure_does_not_clear_new_device_flow')
                    finally:
                        flow.close()

                for ending in ['member', 'household']:
                    flow = Flow().open()
                    try:
                        flow.form().locator('[name=name]').fill('MUST_NOT_SEND_OLD_ACTOR')
                        flow.switch(ending, boot=False)
                        flow.form().locator('button[type=submit]').click()
                        flow.page.wait_for_timeout(300)
                        assert flow.patch_calls() == 0
                        assert flow.page.locator('#tv-display-form').count() == 0
                        passed('cookie_only_' + ending + '_change_before_submit_sends_no_patch')
                    finally:
                        flow.close()

                for failure in ['missing', 'unavailable']:
                    flow = Flow().open()
                    try:
                        def missing_me(route):
                            route.fulfill(status=200 if failure == 'missing' else 503, content_type='application/json',
                                          body='{}' if failure == 'missing' else '{"error":"SYNTHETIC_IDENTITY_UNAVAILABLE"}')
                        flow.page.route('**/api/me', missing_me)
                        flow.form().locator('[name=name]').fill('MUST_NOT_SEND_UNVERIFIED')
                        flow.form().locator('button[type=submit]').click()
                        flow.page.wait_for_timeout(300)
                        assert flow.patch_calls() == 0
                        passed('identity_' + failure + '_before_save_refuses_write')
                    finally:
                        flow.close()

                assert sql('SELECT id,owner,data,revision FROM hub_investments ORDER BY id') == private_before
                tv1.close(); tv2.close(); seed.close(); browser.close()
            assert not errors and not external
            report['passed'] = True
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)
            after = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
            report['sourceUnchanged'] = hashes == after
            report['sourceHashesAfter'] = after
            report['passed'] = report['passed'] and report['sourceUnchanged']
            (out / 'tv-display-browser-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            print(json.dumps({'passed': report['passed'], 'checks': len(checks), 'sourceUnchanged': report['sourceUnchanged'],
                              'pageErrors': errors, 'externalRequests': external}, ensure_ascii=False), flush=True)
    assert report['passed']


if __name__ == '__main__':
    main()
