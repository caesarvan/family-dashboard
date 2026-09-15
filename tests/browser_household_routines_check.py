"""Real loopback Flask/SQLite/Edge routines, lifecycle, drafts and actor races."""
from contextlib import closing
from datetime import date
import hashlib
import base64
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import traceback
from urllib.parse import urlsplit
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import create_app
import household_routines
from playwright.sync_api import expect, sync_playwright
from PIL import Image
from werkzeug.serving import make_server, WSGIRequestHandler


class Quiet(WSGIRequestHandler):
    def log(self, *_args, **_kwargs):
        pass


def main():
    output = ROOT / 'test-results'
    output.mkdir(exist_ok=True)
    paths = set(ROOT.glob('*.py')) | {Path(__file__)}
    for folder in ('static', 'deploy'):
        paths.update(p for p in (ROOT / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    paths.update(ROOT / n for n in ('Dockerfile', 'compose.yaml', 'requirements.txt', 'pytest.ini'))
    def hashes():
        return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
    checks, errors, external, providers, screenshots, requests = [], [], [], [], [], {}
    report = {'passed': False, 'checks': checks, 'pageErrors': errors, 'externalRequests': external,
              'providerCalls': providers, 'requestCounts': requests, 'screenshots': screenshots,
              'sourceHashes': hashes(), 'realCloudWrites': 0, 'productionWrites': 0, 'realPrivateInputs': 0,
              'scope': 'Real temporary Flask/SQLite/Edge; fixed synthetic household date and explicit local engine tick. No public site, real account, provider or production data.'}
    def passed(name):
        assert name not in checks
        checks.append(name)
        print('PASS ' + name, flush=True)
    def deny(*_args, **_kwargs):
        providers.append('unexpected-provider-call')
        raise AssertionError('Provider calls are forbidden')
    clock = [date(2026, 1, 31)]
    with tempfile.TemporaryDirectory(prefix='household-routines-browser-') as temporary, patch.object(household_routines, 'today', lambda: clock[0]):
        app = create_app({'TESTING': True, 'SECRET_KEY': 'synthetic-household-routines-secret',
                          'DATA_DIR': temporary, 'SESSION_COOKIE_SECURE': False,
                          'MEMBER1_PASSWORD': 'testing-password-one', 'MEMBER2_PASSWORD': 'testing-password-two',
                          'PUBLIC_ORIGIN': 'http://localhost', 'CLOUD_TRANSPORT': deny, 'OAUTH_TRANSPORT': deny,
                          'CLOUD_PROVIDER_FACTORY': deny, 'OPENAI_API_KEY': ''})
        assert app.config['SESSION_REFRESH_EACH_REQUEST'] is False
        assert any(r.rule == '/api/routines/context' for r in app.url_map.iter_rules())
        database = Path(temporary) / 'household.sqlite3'
        def sql(statement, params=()):
            with closing(sqlite3.connect(database)) as con:
                rows = con.execute(statement, params).fetchall()
                con.commit()
                return rows
        def tick():
            with app.app_context():
                return app.extensions['household_routines'].tick()
        server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=Quiet)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
                def login(context, member=1, child=False):
                    sql('DELETE FROM attempts')
                    context.request.get(base + '/api/me')
                    prefix = 'second-home-password-' if child else 'testing-password-'
                    response = context.request.post(base + '/api/login', data={'username': f'member{member}', 'password': prefix + ('one' if member == 1 else 'two')})
                    assert response.status == 200, response.text()
                def headers(context):
                    return {'X-CSRF-Token': context.request.get(base + '/api/me').json()['csrf']}
                def post(context, path, payload):
                    response = context.request.post(base + path, headers=headers(context), data=payload)
                    assert response.status in (200, 201), response.text()
                    return response.json()
                def plans(context, plan_id=''):
                    result = context.request.get(base + '/api/routines/context', params={'planId': plan_id, 'includeArchived': 'true'})
                    assert result.status == 200, result.text()
                    return result.json()
                def plan(context, uid):
                    return next(p for p in plans(context, uid)['plans'] if p['id'] == uid)
                def patch_item(context, kind, uid, payload):
                    state = context.request.get(base + '/api/state').json()
                    item = next(v for v in state[kind] if v['id'] == uid)
                    response = context.request.patch(base + '/api/items/' + kind + '/' + uid, headers=headers(context), data={**payload, 'revision': item['revision']})
                    assert response.status == 200, response.text()
                def delete_item(context, kind, uid):
                    item = next(v for v in context.request.get(base + '/api/state').json()[kind] if v['id'] == uid)
                    response = context.request.delete(base + '/api/items/' + kind + '/' + uid, headers=headers(context), data={'revision': item['revision']})
                    assert response.status == 200, response.text()
                counter = [0]
                def create_plan(context, title=None, kind='tasks'):
                    counter[0] += 1
                    template = {'title': title or '合成计划 ' + str(counter[0]), 'owner': 'shared', 'note': '虚构例行事项'}
                    if kind == 'shopping':
                        template.update(quantity='1 件', budget=12000)
                    value = {'operation': 'create', 'kind': kind, 'template': template,
                             'schedule': {'frequency': 'weekly', 'interval': 1, 'anchor': clock[0].isoformat()}}
                    preview = post(context, '/api/routines/preview', value)
                    return post(context, '/api/routines/confirm', {'previewToken': preview['previewToken']})['plan']
                seed = browser.new_context()
                login(seed)
                invitation = post(seed, '/api/spaces/invitations', {})
                child_entry = post(seed, '/api/spaces/redeem', {'invitation': invitation['invitation'], 'name': 'Synthetic Routines Home',
                                  'slug': 'synthetic-routines', 'MEMBER1_PASSWORD': 'second-home-password-one', 'MEMBER2_PASSWORD': 'second-home-password-two'})['entry']

                class Flow:
                    def __init__(self, existing=True, kind='tasks', width=390):
                        self.context = browser.new_context(viewport={'width': width, 'height': 940})
                        self.held, self.gate, self.calls = [], None, []
                        self.context.route('**/*', self.route)
                        login(self.context)
                        self.plan = create_plan(self.context, kind=kind) if existing else None
                        self.page = self.context.new_page()
                        self.page.on('pageerror', lambda err: errors.append(str(err)))
                        self.page.goto(base)
                        expect(self.page.locator('.ps-welcome')).to_be_visible()
                        self.page.evaluate('clearInterval(pollTimer)')
                        self.open(self.plan['id'] if self.plan else '')
                    def route(self, route):
                        req = route.request
                        if not req.url.startswith(base + '/'):
                            external.append({'method': req.method, 'url': req.url}); route.abort(); return
                        path = urlsplit(req.url).path
                        key = req.method + ' ' + path
                        requests[key] = requests.get(key, 0) + 1
                        if path.startswith('/api/routines'):
                            self.calls.append((req.method, path, req.post_data))
                        if self.gate and self.gate(req.method, path):
                            self.gate = None
                            response = route.fetch()
                            assert response.status == 200, response.text()
                            assert 'set-cookie' not in response.headers
                            self.held.append((route, response))
                        else:
                            route.continue_()
                    def open(self, uid=''):
                        self.page.evaluate('options=>{void HouseholdRoutines.open(options)}', {'planId': uid} if uid else {})
                        expect(self.page.locator('.hr-detail-view' if uid else '.hr-list-view')).to_be_visible()
                    def start_form(self, new=False):
                        self.page.locator('[data-hr=create]' if new else '[data-hr=edit]').first.click()
                        expect(self.page.locator('#household-routine-form')).to_be_visible()
                    def fill(self, title='合成例行模板', frequency='weekly', kind=None):
                        form = self.page.locator('#household-routine-form')
                        form.locator('[name=title]').fill(title)
                        if kind: form.locator('[name=kind]').select_option(kind)
                        form.locator('[name=frequency]').select_option(frequency)
                        form.locator('[name=interval]').fill('1')
                        form.locator('[name=anchor]').fill(clock[0].isoformat())
                        form.locator('[name=note]').fill('合成备注，不含真实家庭资料')
                    def preview(self):
                        self.page.locator('#household-routine-form [type=submit]').click()
                        expect(self.page.locator('.hr-review')).to_be_visible()
                    def confirm(self):
                        self.page.locator('[name=confirmAck]').check()
                        self.page.locator('[data-hr=confirm]').click()
                        expect(self.page.locator('.hr-detail-view')).to_be_visible()
                    def refresh(self):
                        self.page.locator('[data-hr=refresh]').click()
                        expect(self.page.locator('.hr-detail-view')).to_be_visible()
                        expect(self.page.locator('[data-hr=refresh]')).to_be_enabled()
                    def action(self, name):
                        self.page.locator('[data-hr=' + name + ']').click()
                        expect(self.page.locator('.hr-review')).to_be_visible()
                    def arm(self, stage):
                        path = {'read': '/api/routines/context', 'context': '/api/routines/context', 'state': '/api/state',
                                'me': '/api/me', 'preview': '/api/routines/preview', 'confirm': '/api/routines/confirm'}[stage]
                        method = 'POST' if stage in ('preview', 'confirm') else 'GET'
                        self.gate = lambda m, p: m == method and p == path
                    def wait_held(self):
                        for _ in range(300):
                            if self.held: break
                            self.page.wait_for_timeout(10)
                        assert len(self.held) == 1
                    def release(self, error=False):
                        route, response = self.held.pop()
                        if error: route.fulfill(status=503, content_type='application/json', body=json.dumps({'error': 'SYNTHETIC_OLD_FAILURE'}))
                        else: route.fulfill(response=response)
                        self.page.wait_for_timeout(180)
                    def switch(self, household=False, boot=True):
                        if household:
                            assert self.context.request.get(base + child_entry).status == 200
                        login(self.context, 1 if household else 2, child=household)
                        if boot:
                            self.page.evaluate('boot()')
                            expected = self.context.request.get(base + '/api/me').json()['user']
                            assert self.page.evaluate('user.id') == expected['id']
                            assert self.page.evaluate('user.householdId') == expected['householdId']
                            self.page.evaluate('clearInterval(pollTimer)')
                    def replacement_draft(self):
                        self.page.once('dialog', lambda dialog: dialog.accept())
                        self.open()
                        self.start_form(new=True)
                        self.fill('NEW_FLOW_DRAFT_B')
                        self.page.locator('#household-routine-form').evaluate('(node)=>window.__hrNewForm=node')
                    def close(self):
                        for route, response in self.held: route.fulfill(response=response)
                        self.held = []; self.context.close()

                flow = Flow(existing=False)
                try:
                    flow.page.locator('[data-action=close]').click()
                    flow.page.goto(base + '/#tasks')
                    expect(flow.page.locator('[data-ps-module=HouseholdRoutines]')).to_be_visible()
                    flow.page.locator('[data-ps-module=HouseholdRoutines]').click()
                    expect(flow.page.locator('.hr-list-view')).to_be_visible()
                    passed('real_tasks_toolbar_entry')
                    flow.start_form(new=True); flow.fill('每月固定31日', 'monthly')
                    before = sql('SELECT count(*) FROM household_routines')[0][0]
                    flow.preview()
                    expect(flow.page.locator('.hr-schedule')).to_contain_text('2026-01-31')
                    expect(flow.page.locator('.hr-schedule')).to_contain_text('2026-02-28')
                    expect(flow.page.locator('.hr-schedule')).to_contain_text('2026-03-31')
                    assert sql('SELECT count(*) FROM household_routines')[0][0] == before
                    passed('monthly31_three_dates_preview_has_no_write')
                    flow.confirm(); uid = flow.page.locator('.hr-detail-view').get_attribute('data-hr-plan')
                    p = plan(flow.context, uid); first = p['current']['entityId']
                    assert p['current']['scheduledOn'] == '2026-01-31'
                    passed('explicit_create_generates_one_current_and_reads_back')
                    patch_item(flow.context, 'tasks', first, {'done': True}); tick(); flow.refresh()
                    p = plan(flow.context, uid); assert p['current']['scheduledOn'] == '2026-02-28'
                    clock[0] = date(2026, 2, 28)
                    patch_item(flow.context, 'tasks', p['current']['entityId'], {'done': True}); tick(); flow.refresh()
                    p = plan(flow.context, uid); assert p['current']['scheduledOn'] == '2026-03-31'
                    expect(flow.page.locator('.hr-detail-view')).to_contain_text('2026-03-31')
                    passed('actual_completion_tick_clamps_then_returns_original31')
                    old_id = p['current']['entityId']; old_entity = p['current']['entity']
                    flow.start_form(); flow.fill('以后使用的新模板', 'weekly'); flow.preview()
                    expect(flow.page.locator('.hr-review')).to_contain_text('仅更新未来模板')
                    flow.confirm(); p = plan(flow.context, uid)
                    assert p['current']['entityId'] == old_id and p['current']['entity'] == old_entity
                    passed('template_update_preserves_current_entity_all_fields')
                    flow.action('pause'); flow.confirm(); assert plan(flow.context, uid)['state'] == 'paused'
                    patch_item(flow.context, 'tasks', old_id, {'done': True}); tick()
                    assert plan(flow.context, uid)['current']['entityId'] == old_id
                    passed('paused_plan_does_not_advance_completed_current')
                    flow.action('resume'); flow.confirm(); p = plan(flow.context, uid)
                    assert p['state'] == 'active' and p['current']['entityId'] != old_id
                    passed('resume_completed_current_generates_next_once')
                    current_id = p['current']['entityId']
                    flow.action('skip'); expect(flow.page.locator('.hr-review')).to_contain_text('跳过本期并保留现有事项')
                    flow.confirm(); p = plan(flow.context, uid)
                    old = next(v for v in p['history'] if v['entityId'] == current_id)
                    assert old['state'] == 'skipped' and old['entity']['done'] is False
                    patch_item(flow.context, 'tasks', current_id, {'done': True})
                    assert next(v for v in plan(flow.context, uid)['history'] if v['entityId'] == current_id)['state'] == 'skipped'
                    passed('skip_preserves_entity_and_never_relabels_history_completed')
                    missing_id = p['current']['entityId']; delete_item(flow.context, 'tasks', missing_id); tick(); flow.refresh()
                    expect(flow.page.locator('.hr-detail-view')).to_contain_text('本期事项已删除')
                    assert sql('SELECT count(*) FROM entities WHERE id=?', (missing_id,))[0][0] == 0
                    flow.action('skip'); flow.confirm()
                    assert plan(flow.context, uid)['current']['entityId'] != missing_id
                    assert sql('SELECT count(*) FROM entities WHERE id=?', (missing_id,))[0][0] == 0
                    passed('deleted_current_not_revived_explicit_skip_continues')
                    flow.action('archive'); flow.confirm(); assert plan(flow.context, uid)['state'] == 'archived'
                    expect(flow.page.locator('[data-hr=resume]')).to_have_count(0)
                    expect(flow.page.locator('[data-hr=edit]')).to_have_count(0)
                    flow.page.locator('[data-hr=list]').click(); expect(flow.page.locator('.hr-list-view')).to_be_visible()
                    flow.page.locator('[data-filter=archived]').click()
                    expect(flow.page.locator('[data-hr-plan="' + uid + '"]')).to_be_visible()
                    passed('archive_read_only_and_list_filter_visible')
                finally:
                    flow.close(); clock[0] = date(2026, 1, 31)

                flow = Flow(existing=False)
                try:
                    flow.start_form(new=True); flow.fill('定期采购咖啡豆', kind='shopping')
                    form = flow.page.locator('#household-routine-form')
                    expect(form.locator('[name=quantity]')).to_be_visible()
                    form.locator('[name=quantity]').fill('2 袋'); form.locator('[name=budget]').fill('0')
                    for theme in ('forest', 'light', 'ocean'):
                        for width in (360, 768, 1440):
                            flow.page.set_viewport_size({'width': width, 'height': 1000})
                            flow.page.evaluate('theme=>document.documentElement.dataset.theme=theme', theme)
                            flow.page.locator('.dialog-content').evaluate('(node)=>node.scrollTop=0')
                            assert flow.page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                            assert flow.page.locator('[data-household-routines]').evaluate('(node)=>node.scrollWidth<=node.clientWidth+1')
                            target = output / f'household-routines-{theme}-{width}.png'
                            flow.page.screenshot(path=str(target), full_page=True)
                            screenshots.append({'path': str(target), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'theme': theme, 'width': width})
                    passed('nine_theme_viewports_form_no_horizontal_overflow')
                    flow.preview(); flow.confirm(); uid = flow.page.locator('.hr-detail-view').get_attribute('data-hr-plan')
                    p = plan(flow.context, uid); first = p['current']['entityId']
                    assert p['current']['entity']['budget'] == 0
                    picture = io.BytesIO(); Image.new('RGB', (16, 16), '#77aa88').save(picture, 'PNG')
                    photo = post(flow.context, '/api/photos', {'dataUrl': 'data:image/png;base64,' + base64.b64encode(picture.getvalue()).decode()})
                    patch_item(flow.context, 'shopping', first, {'actual': 7600, 'done': True, 'photoIds': [photo['id']]})
                    tick(); flow.refresh(); p = plan(flow.context, uid)
                    fresh = p['current']['entity']
                    assert p['current']['entityId'] != first and fresh['actual'] is None and fresh['done'] is False
                    assert fresh['photoIds'] == [] and fresh['budget'] == 0 and fresh['quantity'] == '2 袋'
                    assert not any(k in fresh for k in ('tripId', 'paymentId', 'transactionId'))
                    passed('new_shopping_period_clears_actual_done_photos_and_links')
                    flow.page.locator('[data-hr=open-item]').first.click()
                    expect(flow.page.locator('.shopping-form')).to_be_visible()
                    expect(flow.page.locator('.shopping-form [name=title]')).to_have_value('定期采购咖啡豆')
                    passed('open_exact_original_shopping_editor')
                    flow.page.locator('#shopping-photo-input').set_input_files({'name': 'synthetic.png', 'mimeType': 'image/png', 'buffer': picture.getvalue()})
                    expect(flow.page.locator('#shopping-photo-list img')).to_have_count(1)
                    expect(flow.page.locator('.shopping-form [type=submit]')).to_be_enabled()
                    flow.page.locator('[data-hr-return-plan]').click()
                    expect(flow.page.locator('[data-hr-return] .hr-error')).to_contain_text('尚未保存')
                    expect(flow.page.locator('#shopping-photo-list img')).to_have_count(1)
                    flow.page.locator('[data-photo-remove]').click()
                    passed('return_does_not_discard_unsaved_uploaded_photo')
                    flow.page.locator('[data-hr-return-plan]').click()
                    expect(flow.page.locator('.hr-detail-view')).to_have_attribute('data-hr-plan', uid)
                    passed('shopping_editor_explicit_return_reads_original_plan')
                    flow.page.locator('[data-action=close]').click()
                    flow.page.goto(base + '/#shopping')
                    expect(flow.page.locator('[data-ps-module=HouseholdRoutines]')).to_be_visible()
                    flow.page.locator('[data-ps-module=HouseholdRoutines]').click()
                    expect(flow.page.locator('.hr-list-view')).to_be_visible()
                    passed('real_shopping_toolbar_entry')
                finally:
                    flow.close()

                for failure in (False, True):
                    flow = Flow()
                    try:
                        flow.page.locator('[data-hr=open-item]').first.click()
                        expect(flow.page.locator('[data-hr-return-plan]')).to_be_visible()
                        flow.arm('me'); flow.page.locator('[data-hr-return-plan]').click(); flow.wait_held()
                        flow.replacement_draft(); flow.release(error=failure)
                        expect(flow.page.locator('#household-routine-form [name=title]')).to_have_value('NEW_FLOW_DRAFT_B')
                        expect(flow.page.locator('.hr-error')).to_have_text('')
                        passed('return_late_' + ('503' if failure else 'success') + '_keeps_new_plan_draft')
                    finally:
                        flow.close()
                flow = Flow()
                try:
                    flow.page.locator('[data-action=close]').click()
                    # Exercise queued native close arriving after a new assistant opens.
                    flow.page.evaluate('HomeAssistant.open()')
                    expect(flow.page.locator('#assistant-form')).to_be_visible()
                    if not flow.page.locator('[data-assistant-action=routines]').is_visible():
                        flow.page.locator('#assistant-composer > summary').click()
                    flow.page.locator('[data-assistant-action=routines]').click()
                    expect(flow.page.locator('.hr-list-view')).to_be_visible()
                    flow.page.locator('[data-plan-id="' + flow.plan['id'] + '"]').click()
                    expect(flow.page.locator('.hr-detail-view')).to_be_visible()
                    flow.page.locator('[data-hr=open-item]').first.click()
                    expect(flow.page.locator('#assistant-return-bar')).to_be_visible()
                    flow.page.locator('[data-hr-return-plan]').click()
                    expect(flow.page.locator('.hr-detail-view')).to_have_attribute('data-hr-plan', flow.plan['id'])
                    expect(flow.page.locator('#assistant-workspace')).to_have_count(0)
                    flow.page.locator('[data-assistant-action=return]').click()
                    expect(flow.page.locator('#assistant-workspace')).to_be_visible()
                    passed('explicit_plan_return_coexists_with_outer_assistant_return')
                finally:
                    flow.close()

                flow = Flow()
                try:
                    flow.page.locator('[data-hr=open-item]').first.click()
                    expect(flow.page.locator('#dialog form')).to_be_visible()
                    flow.page.locator('#dialog form [name=title]').fill('本期编辑后保存')
                    flow.gate = lambda method, path: method == 'PATCH' and path.startswith('/api/items/tasks/')
                    flow.page.locator('#dialog form [type=submit]').click(); flow.wait_held()
                    flow.page.locator('[data-hr-return-plan]').click()
                    expect(flow.page.locator('[data-hr-return] .hr-error')).to_contain_text('正在保存')
                    expect(flow.page.locator('#dialog form')).to_be_visible()
                    flow.release(); expect(flow.page.locator('#dialog')).not_to_be_visible()
                    flow.open(flow.plan['id'])
                    expect(flow.page.locator('.hr-current-title')).to_have_text('本期编辑后保存')
                    assert plan(flow.context, flow.plan['id'])['template']['title'] == flow.plan['template']['title']
                    passed('return_does_not_close_inflight_original_item_save')
                finally:
                    flow.close()
                flow = Flow()
                try:
                    flow.page.locator('[data-hr=open-item]').first.click()
                    expect(flow.page.locator('[data-hr-return-plan]')).to_be_visible()
                    flow.switch(boot=False)
                    flow.page.locator('[data-hr-return-plan]').click()
                    expect(flow.page.locator('[data-hr-return-loading]')).to_contain_text('登录成员或家庭已变化')
                    expect(flow.page.locator('.hr-detail-view')).to_have_count(0)
                    passed('return_cookie_only_member_switch_does_not_restore_old_plan')
                finally:
                    flow.close()

                flow = Flow()
                try:
                    flow.page.locator('[data-hr=open-item]').first.click()
                    expect(flow.page.locator('#dialog form')).to_be_visible()
                    expect(flow.page.locator('#dialog form [name=title]')).to_have_value(flow.plan['template']['title'])
                    passed('open_exact_original_task_editor')
                    flow.page.locator('#dialog form [name=title]').fill('原事项尚未保存')
                    flow.page.locator('[data-hr-return-plan]').click()
                    expect(flow.page.locator('[data-hr-return] .hr-error')).to_contain_text('尚未保存')
                    expect(flow.page.locator('#dialog form [name=title]')).to_have_value('原事项尚未保存')
                    flow.page.locator('#dialog form [name=title]').fill(flow.plan['template']['title'])
                    flow.page.locator('[data-hr-return-plan]').click()
                    expect(flow.page.locator('.hr-detail-view')).to_have_attribute('data-hr-plan', flow.plan['id'])
                    passed('task_editor_return_preserves_unsaved_draft_and_original_plan')
                    calls = len([c for c in flow.calls if c[0] == 'POST'])
                    flow.page.locator('[data-hr=publish-item]').click()
                    expect(flow.page.locator('#task-publish-root')).to_be_visible()
                    assert len([c for c in flow.calls if c[0] == 'POST']) == calls
                    passed('task_publish_exact_entry_without_routine_or_cloud_write')
                    flow.page.locator('[data-hr-return-plan]').click()
                    expect(flow.page.locator('.hr-detail-view')).to_have_attribute('data-hr-plan', flow.plan['id'])
                    passed('task_publish_explicit_return_reads_original_plan')
                finally:
                    flow.close()

                flow = Flow()
                try:
                    flow.start_form(); flow.fill('未保存的草稿')
                    flow.page.once('dialog', lambda d: d.dismiss())
                    flow.page.locator('[data-hr=cancel-edit]').click()
                    expect(flow.page.locator('#household-routine-form [name=title]')).to_have_value('未保存的草稿')
                    flow.page.evaluate('data.revision+=1;HouseholdRoutines.notifyStateChanged()')
                    expect(flow.page.locator('[data-hr-stale]')).to_contain_text('状态可能已变化')
                    expect(flow.page.locator('#household-routine-form [name=title]')).to_have_value('未保存的草稿')
                    passed('cancel_decline_and_state_notice_keep_draft_without_auto_read')
                    flow.preview(); flow.arm('preview'); flow.page.locator('[data-hr=repreview]').click(); flow.wait_held()
                    expect(flow.page.locator('[data-hr=confirm]')).to_be_disabled()
                    flow.release(error=True)
                    expect(flow.page.locator('[data-hr=confirm]')).to_be_disabled()
                    expect(flow.page.locator('.hr-error')).to_contain_text('SYNTHETIC_OLD_FAILURE')
                    flow.page.locator('[data-hr=repreview]').click(); expect(flow.page.locator('[name=confirmAck]')).to_be_enabled()
                    passed('repreview_pending_and503_never_reenables_old_confirmation')
                    flow.arm('confirm'); flow.page.locator('[name=confirmAck]').check(); flow.page.locator('[data-hr=confirm]').click(); flow.wait_held()
                    flow.release(error=True)
                    expect(flow.page.locator('.hr-error')).to_contain_text('确认请求已经发出')
                    requests_before = [c for c in flow.calls if c[1] == '/api/routines/confirm']
                    flow.page.locator('[data-hr=confirm]').click(); expect(flow.page.locator('.hr-detail-view')).to_be_visible()
                    sent = [c for c in flow.calls if c[1] == '/api/routines/confirm']
                    assert len(sent) == len(requests_before) + 1 and sent[-1][2] == sent[-2][2]
                    expect(flow.page.locator('.hr-note')).to_contain_text('原确认回执')
                    passed('lost_confirm_response_manual_retry_same_token_no_duplicate')
                    flow.start_form(); flow.fill('读取失败保留确认回执'); flow.preview(); flow.arm('context')
                    flow.page.locator('[name=confirmAck]').check(); flow.page.locator('[data-hr=confirm]').click(); flow.wait_held(); flow.release(error=True)
                    expect(flow.page.locator('.hr-error')).to_contain_text('SYNTHETIC_OLD_FAILURE')
                    count = len([c for c in flow.calls if c[1] == '/api/routines/confirm'])
                    flow.page.locator('[data-hr=confirm]').click(); expect(flow.page.locator('.hr-detail-view')).to_be_visible()
                    assert len([c for c in flow.calls if c[1] == '/api/routines/confirm']) == count
                    passed('known_confirmation_readback_retry_does_not_repost')
                    flow.start_form(); flow.fill('并发后仍保留的草稿'); flow.preview()
                    original = plan(flow.context, flow.plan['id'])
                    other = post(flow.context, '/api/routines/preview', {'operation': 'pause', 'planId': original['id'], 'revision': original['revision']})
                    post(flow.context, '/api/routines/confirm', {'previewToken': other['previewToken']})
                    flow.page.locator('[name=confirmAck]').check(); flow.page.locator('[data-hr=confirm]').click()
                    expect(flow.page.locator('.hr-error')).to_contain_text('记录已变化')
                    expect(flow.page.locator('[data-hr=confirm]')).to_be_disabled()
                    flow.page.locator('[data-hr=back-preview]').click()
                    expect(flow.page.locator('#household-routine-form [name=title]')).to_have_value('并发后仍保留的草稿')
                    flow.page.locator('[data-hr=reload-draft]').click()
                    expect(flow.page.locator('.hr-error')).to_contain_text('已读取最新版本')
                    flow.preview(); flow.confirm()
                    assert plan(flow.context, original['id'])['template']['title'] == '并发后仍保留的草稿'
                    passed('409_keep_draft_reload_revision_repreview_explicit_confirm')
                finally:
                    flow.close()

                for stage in ('read', 'preview', 'confirm', 'context', 'state'):
                    for target in ('new', 'close', 'member', 'household'):
                        for failure in (False, True):
                            flow = Flow()
                            try:
                                if stage != 'read':
                                    flow.start_form(); flow.fill('OLD_FLOW_TEMPLATE_A')
                                    if stage != 'preview': flow.preview()
                                flow.arm(stage)
                                if stage == 'read': flow.page.locator('[data-hr=refresh]').click()
                                elif stage == 'preview': flow.page.locator('#household-routine-form [type=submit]').click()
                                else:
                                    flow.page.locator('[name=confirmAck]').check(); flow.page.locator('[data-hr=confirm]').click()
                                flow.wait_held()
                                if target in ('member', 'household'): flow.switch(household=target == 'household')
                                if target == 'close':
                                    flow.page.locator('[data-action=close]').click()
                                    flow.page.evaluate("openModal('后来的窗口','<p id=hr-unrelated>新的窗口内容</p>')")
                                else: flow.replacement_draft()
                                flow.release(error=failure)
                                if target == 'close': expect(flow.page.locator('#hr-unrelated')).to_have_text('新的窗口内容')
                                else:
                                    expect(flow.page.locator('#household-routine-form [name=title]')).to_have_value('NEW_FLOW_DRAFT_B')
                                    assert flow.page.locator('#household-routine-form').evaluate('(node)=>node===window.__hrNewForm')
                                    expect(flow.page.locator('.hr-error')).to_have_text('')
                                    expect(flow.page.locator('.hr-review')).to_have_count(0)
                                passed(f'late_{stage}_{"503" if failure else "success"}_preserves_{target}')
                            finally:
                                flow.close()

                for action in ('create', 'edit', 'pause'):
                    flow = Flow(existing=action != 'create')
                    try:
                        count = len([c for c in flow.calls if c[0] == 'POST'])
                        flow.switch(boot=False)
                        flow.page.locator('[data-hr=' + action + ']').first.click()
                        expect(flow.page.locator('[data-household-routines]')).to_contain_text('请重新核对登录状态')
                        assert len([c for c in flow.calls if c[0] == 'POST']) == count
                        passed('cookie_only_member_switch_rejects_cached_' + action)
                    finally:
                        flow.close()

                flow = Flow(existing=False)
                try:
                    for i in range(42):
                        create_plan(flow.context, '分页例行计划 ' + str(i))
                    flow.page.locator('[data-hr=refresh]').click(); expect(flow.page.locator('[data-hr=next]')).to_be_enabled()
                    flow.page.locator('[data-hr=next]').click(); expect(flow.page.locator('.hr-pagination')).to_contain_text('第 2 页')
                    assert flow.page.locator('.hr-card').count() > 0
                    passed('more_than40_plans_reachable_with_next_page')
                finally:
                    flow.close()

                for url, tv in (('/demo', False), ('/demo?tv=1', True)):
                    context = browser.new_context(); page = context.new_page(); seen = []
                    context.route('**/*', lambda r: r.continue_() if r.request.url.startswith(base + '/') else (external.append(r.request.url), r.abort()))
                    page.on('request', lambda req: seen.append(urlsplit(req.url).path))
                    page.on('pageerror', lambda err: errors.append(str(err)))
                    page.goto(base + url)
                    expect(page.locator('.ps-welcome' if not tv else '.board')).to_be_visible()
                    page.evaluate('HouseholdRoutines.open();HouseholdRoutines.refresh();HouseholdRoutines.notifyStateChanged()')
                    expect(page.locator('[data-ps-module=HouseholdRoutines]')).to_have_count(0)
                    assert '/api/routines/context' not in seen
                    context.close(); passed('demo_tv_no_routine_api_or_controls' if tv else 'demo_member_no_routine_api_or_controls')
                login(seed)
                tv_context = browser.new_context(); tv_page = tv_context.new_page(); tv_seen = []
                tv_context.route('**/*', lambda r: r.continue_() if r.request.url.startswith(base + '/') else (external.append(r.request.url), r.abort()))
                tv_page.on('request', lambda req: tv_seen.append(urlsplit(req.url).path))
                tv_page.on('pageerror', lambda err: errors.append(str(err)))
                start = tv_context.request.post(base + '/api/pair/start', data={}).json()
                post(seed, '/api/pair/approve', {'code': start['code'], 'name': '合成例行电视', 'focus': 'member1'})
                poll = tv_context.request.post(base + '/api/pair/poll', data={'secret': start['secret']})
                assert poll.status == 200
                tv_page.goto(base + '/tv'); expect(tv_page.locator('.board')).to_be_visible()
                tv_page.evaluate('HouseholdRoutines.open();HouseholdRoutines.refresh();HouseholdRoutines.notifyStateChanged()')
                assert '/api/routines/context' not in tv_seen
                assert tv_context.request.get(base + '/api/routines/context').status == 403
                expect(tv_page.locator('[data-ps-module=HouseholdRoutines]')).to_have_count(0)
                passed('paired_tv_shared_items_only_no_routine_management')
                tv_context.close(); seed.close(); browser.close()
                assert not errors and not external and not providers
                report['passed'] = True
        except Exception:
            report['error'] = traceback.format_exc()
        finally:
            server.shutdown(); thread.join(timeout=5)
    report['sourceHashesAfter'] = hashes()
    report['sourceUnchanged'] = report['sourceHashes'] == report['sourceHashesAfter']
    report['passed'] = report['passed'] and report['sourceUnchanged']
    report['exitCode'] = 0 if report['passed'] else 1
    target = output / 'household-routines-browser-verification.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'checks': len(checks), 'sourceUnchanged': report['sourceUnchanged'],
                      'pageErrors': errors, 'externalRequests': external, 'report': str(target), 'error': report.get('error')}, ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
