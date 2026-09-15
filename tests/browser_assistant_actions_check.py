"""Synthetic action-desk closure checks. Loopback only; never uses real accounts or data.

Run with the project Python. Screenshots and a failure-preserving JSON report are
written to test-results/. This script intentionally requires the real Edge DOM,
Flask authorization, CAS revisions and SQLite readback, rather than UI mocks.
"""
from datetime import datetime, timedelta
import base64
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import create_app, TZ
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server, WSGIRequestHandler
from PIL import Image


class Quiet(WSGIRequestHandler):
    def log(self, *_args, **_kwargs):
        pass


def synthetic_png():
    stream = BytesIO()
    Image.new('RGB', (32, 24), '#9ad1b1').save(stream, format='PNG')
    return stream.getvalue()


def seed(app):
    client = app.test_client()
    assert client.post('/api/login', json={'username': 'member1', 'password': 'testing-password-one'}).status_code == 200
    headers = {'X-CSRF-Token': client.get('/api/me').json['csrf']}
    today = datetime.now(TZ).date()
    day, end = today.isoformat(), (today + timedelta(days=3)).isoformat()

    def add(kind, title, **values):
        response = client.post('/api/items/' + kind, json={'title': title, 'owner': 'shared', **values}, headers=headers)
        assert response.status_code == 201, response.json
        return response.json['id']

    task = add('tasks', '原事项 · 周末保洁', due=day)
    conflict_task = add('tasks', '版本冲突保留项', due=day)
    failure_task = add('tasks', '网络失败保留项', due=day)
    readback_task = add('tasks', '写入成功后读回中断', due=day)
    photo = client.post('/api/photos', json={'dataUrl': 'data:image/png;base64,' + base64.b64encode(synthetic_png()).decode('ascii')}, headers=headers)
    assert photo.status_code == 201, photo.json
    photo_item = add('shopping', '仅照片变更的采购', photoIds=[photo.json['id']], budget=None)
    ordinary = add('events', '家庭讨论 · 原始安排', start=day + 'T10:00:00+08:00', end=day + 'T11:00:00+08:00', location='原始地点')
    add('events', '午前采购 · 重叠安排', start=day + 'T10:30:00+08:00', end=day + 'T11:30:00+08:00')
    plan = {'schemaVersion': 2, 'referenceTimezone': 'Asia/Shanghai', 'title': '虚构行程 · 海边三日', 'start': day, 'end': end,
            'international': False, 'memberIds': ['member1', 'member2'], 'budget': 120000,
            'destinations': [{'key': 'coast', 'country': '中国', 'city': '虚构海滨', 'arrival': day, 'departure': end, 'timeZone': 'Asia/Shanghai'}],
            'segments': [{'key': 'walk', 'kind': 'activity', 'title': '虚构海边散步', 'location': '虚构步道',
                          'start': {'local': day + 'T10:15', 'timeZone': 'Asia/Shanghai'},
                          'end': {'local': day + 'T10:45', 'timeZone': 'Asia/Shanghai'}}],
            'shopping': [{'key': 'adapter', 'title': '旅行转换插头 · 待补预算', 'quantity': '1 件', 'owner': 'shared', 'budget': 8000}]}
    preview = client.post('/api/journeys/preview', json={'plan': plan}, headers=headers)
    assert preview.status_code == 200, preview.json
    applied = client.post('/api/journeys/apply', json={'previewToken': preview.json['previewToken'], 'idempotencyKey': 'synthetic-action-desk-seed'}, headers=headers)
    assert applied.status_code == 201, applied.json
    journey_id = applied.json['id']
    detail = client.get('/api/journeys/' + journey_id).json
    shopping = detail['shopping'][0]
    updated = client.patch('/api/items/shopping/' + shopping['id'], json={'budget': None, 'revision': shopping['revision']}, headers=headers)
    assert updated.status_code == 200, updated.json
    v2event = next(item for item in detail['events'] if item.get('workflowKey') == 'segment:walk')
    # These private records must never be requested or rendered by the action desk.
    with sqlite3.connect(Path(app.config['DATA_DIR']) / 'household.sqlite3') as con:
        con.execute('INSERT INTO entities(id,kind,data,updated_at) VALUES(?,?,?,?)',
                    ('synthetic-mirror-task', 'tasks', json.dumps({'title': '同步清单的原事项', 'owner': 'shared', 'due': day,
                     'done': False, 'note': '合成来源，不连接第三方', 'sync': {'provider': 'microsoft', 'readOnly': False}}), day))
        for uid in ('member1', 'member2'):
            record = {'date': day, 'title': uid + '_PRIVATE_PAYMENT', 'amountCents': 12345, 'currency': 'CNY',
                      'kind': 'payments', 'flow': 'expense', 'category': '测试', 'source': 'generic', 'visibility': 'private'}
            con.execute('INSERT INTO hub_transactions(id,owner,fingerprint,data,created_at) VALUES(?,?,?,?,?)',
                        ('private-' + uid, uid, 'private-fp-' + uid, json.dumps(record), day))
    return {'task': task, 'conflictTask': conflict_task, 'failureTask': failure_task, 'readbackTask': readback_task,
            'ordinary': ordinary, 'journey': journey_id, 'trip': detail['tripId'], 'shopping': shopping['id'],
            'v2event': v2event['id'], 'photoItem': photo_item, 'originalPhoto': photo.json['id'], 'day': day}


def main():
    out = ROOT / 'test-results'
    out.mkdir(exist_ok=True)
    report = {'passed': False, 'scope': 'isolated loopback Flask / temporary SQLite / synthetic records / Edge',
              'checks': [], 'externalRequests': [], 'privateEndpointRequests': [], 'pageErrors': [], 'screenshots': []}
    page = None

    def passed(name, **details):
        report['checks'].append({'name': name, 'passed': True, **details})

    def screenshot(name):
        path = out / ('assistant-actions-' + name + '.png')
        page.screenshot(path=str(path), full_page=False)
        report['screenshots'].append(str(path))

    with tempfile.TemporaryDirectory(prefix='assistant-action-desk-') as temp:
        app = create_app({'TESTING': True, 'SECRET_KEY': 'synthetic-action-desk-test-key', 'DATA_DIR': temp,
                          'SESSION_COOKIE_SECURE': False, 'MEMBER1_PASSWORD': 'testing-password-one', 'MEMBER2_PASSWORD': 'testing-password-two',
                          'OPENAI_API_KEY': '', 'OPENAI_MODEL': '', 'MICROSOFT_CLIENT_ID': '', 'MICROSOFT_CLIENT_SECRET': '',
                          'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': ''})
        ids = seed(app)
        server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=Quiet)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        browser = None
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)

                def new_context(width=1440):
                    context = browser.new_context(viewport={'width': width, 'height': 1000 if width > 500 else 844})

                    def guard(route):
                        if not route.request.url.startswith(base + '/'):
                            report['externalRequests'].append(route.request.url)
                            route.abort()
                        else:
                            route.continue_()

                    context.route('**/*', guard)
                    return context

                def new_page(context):
                    tab = context.new_page()
                    tab.on('pageerror', lambda error: report['pageErrors'].append(str(error)))
                    tab.on('request', lambda req: report['privateEndpointRequests'].append(urlsplit(req.url).path)
                           if any(part in req.url for part in ('/api/private-finance', '/api/finance-hub/overview', '/api/finance-hub/transactions', '/api/finance-hub/investments', '/api/finance-baseline')) else None)
                    return tab

                ctx = new_context()
                assert ctx.request.post(base + '/api/login', data={'username': 'member1', 'password': 'testing-password-one'}).status == 200
                csrf = ctx.request.get(base + '/api/me').json()['csrf']
                headers = {'X-CSRF-Token': csrf}

                def shared():
                    response = ctx.request.get(base + '/api/state')
                    assert response.status == 200, response.text()
                    return response.json()

                def item(kind, uid):
                    return next(row for row in shared()[kind] if row['id'] == uid)

                def action_row(kind, uid):
                    return page.locator(f'.assistant-record[data-record-kind="{kind}"][data-record-id="{uid}"]')

                def open_desk():
                    page.evaluate('HomeAssistant.open()')
                    expect(page.locator('.assistant-desk-group')).to_have_count(5)
                    expect(page.locator('#assistant-refresh')).to_be_enabled()

                def visit(kind, uid):
                    page.locator(f'[data-assistant-action="visit"][data-kind="{kind}"][data-id="{uid}"]').first.click()
                    expect(page.locator('#assistant-return-bar')).to_be_visible()

                def desk_returned():
                    expect(page.locator('.assistant-desk-group')).to_have_count(5)
                    expect(page.locator('#assistant-refresh')).to_be_enabled()

                page = new_page(ctx)
                writes = []
                page.on('request', lambda req: writes.append({'method': req.method, 'path': urlsplit(req.url).path}) if req.method not in ('GET', 'HEAD') else None)
                page.goto(base)
                expect(page.locator('.ps-welcome')).to_be_visible()
                open_desk()
                expect(page.locator('#assistant-workspace')).to_contain_text('原事项 · 周末保洁')
                expect(page.locator('#assistant-workspace')).to_contain_text('旅行转换插头 · 待补预算')
                expect(page.locator('#assistant-workspace')).to_contain_text('虚构行程 · 海边三日')
                expect(page.locator('[data-assistant-action=finance]')).to_be_visible()
                assert page.locator('[data-assistant-action=visit][data-kind=events]').count() >= 2
                screenshot('desktop')
                passed('five_categories_with_original_record_ids')

                assert action_row('tasks', 'synthetic-mirror-task').locator('[data-assistant-action=complete]').count() == 0
                visit('tasks', 'synthetic-mirror-task')
                expect(page.locator('.assistant-readonly')).to_contain_text('同步清单的原事项')
                expect(page.locator('.assistant-readonly')).to_contain_text('请在原应用调整')
                assert page.locator('#dialog form').count() == 0
                page.locator('[data-assistant-action=return]').click()
                desk_returned()
                passed('synchronized_record_opens_readonly_without_cloud_write')

                # Existing assistant draft is preserved while visiting and saving an original editor.
                prompt = '待办：明天只创建这一项；这一项暂不创建'
                page.locator('#assistant-form textarea').fill(prompt)
                page.locator('#assistant-form [type=submit]').click()
                expect(page.locator('[data-plan-index]')).to_have_count(2)
                page.locator('[data-plan-index="1"]').uncheck()
                initial = shared()
                wallet = initial['finance']['wallet']
                before_count = len(initial['shopping'])
                visit('shopping', ids['shopping'])
                expect(page.locator('#dialog form [name=title]')).to_have_value('旅行转换插头 · 待补预算')
                page.set_viewport_size({'width': 390, 'height': 844})
                page.locator('#dialog form [name=budget]').fill('120.50')
                page.locator('[data-assistant-action=return]').click()
                expect(page.locator('#assistant-return-bar .error')).to_contain_text('尚未保存')
                expect(page.locator('#dialog form [name=budget]')).to_have_value('120.50')
                screenshot('shopping-dirty-phone')
                page.locator('#dialog form [type=submit]').click()
                desk_returned()
                expect(page.locator('.assistant-readback')).to_contain_text('已更新')
                expect(page.locator('#assistant-form textarea')).to_have_value(prompt)
                expect(page.locator('[data-plan-index="1"]')).not_to_be_checked()
                actual = item('shopping', ids['shopping'])
                assert actual['budget'] == 12050
                latest = shared()
                assert len(latest['shopping']) == before_count and latest['finance']['wallet'] == wallet
                journey = ctx.request.get(base + '/api/journeys/' + ids['journey']).json()
                assert journey['budget']['purchaseBudget'] == 12050, journey['budget']
                passed('shopping_exact_edit_dirty_guard_readback_and_journey_budget', originalId=ids['shopping'], purchaseBudget=12050, walletUnchanged=True)

                # Photo IDs live outside form controls: removal, upload and in-flight upload all need protection.
                visit('shopping', ids['photoItem'])
                expect(page.locator('#shopping-photo-list img')).to_have_count(1)
                page.locator('[data-photo-remove]').click()
                page.locator('[data-assistant-action=return]').click()
                expect(page.locator('#assistant-return-bar .error')).to_contain_text('尚未保存')
                expect(page.locator('.shopping-form')).to_be_visible()
                assert item('shopping', ids['photoItem'])['photoIds'] == [ids['originalPhoto']]
                screenshot('photo-removal-dirty-phone')
                page.get_by_role('button', name='取消', exact=True).click()
                desk_returned()
                visit('shopping', ids['photoItem'])
                pending_photo = []
                page.route(base + '/api/photos', lambda route: pending_photo.append(route))
                with page.expect_request(lambda req: req.url == base + '/api/photos' and req.method == 'POST'):
                    page.locator('#shopping-photo-input').set_input_files({'name': 'synthetic.png', 'mimeType': 'image/png', 'buffer': synthetic_png()})
                page.locator('[data-assistant-action=return]').click()
                expect(page.locator('#assistant-return-bar .error')).to_contain_text('正在保存或上传图片')
                assert pending_photo
                pending_photo[0].continue_()
                expect(page.locator('#shopping-photo-list img')).to_have_count(2)
                expect(page.locator('.shopping-form [type=submit]')).to_be_enabled()
                assert page.locator('#shopping-photo-input').input_value() == ''
                page.unroute(base + '/api/photos')
                page.locator('[data-assistant-action=return]').click()
                expect(page.locator('#assistant-return-bar .error')).to_contain_text('尚未保存')
                assert item('shopping', ids['photoItem'])['photoIds'] == [ids['originalPhoto']]
                page.locator('.shopping-form [type=submit]').click()
                desk_returned()
                assert len(item('shopping', ids['photoItem'])['photoIds']) == 2
                visit('shopping', ids['photoItem'])
                page.locator('[data-photo-remove]').first.click()
                page.locator('[data-assistant-action=return]').click()
                expect(page.locator('#assistant-return-bar .error')).to_contain_text('尚未保存')
                page.locator('.shopping-form [type=submit]').click()
                desk_returned()
                actual_photos = item('shopping', ids['photoItem'])['photoIds']
                assert len(actual_photos) == 1 and ids['originalPhoto'] not in actual_photos
                passed('photo_only_remove_upload_and_inflight_return_guard_with_readback')

                # Exact local conflict editor, then exact v2 journey route.
                visit('events', ids['ordinary'])
                expect(page.locator('#dialog form [name=title]')).to_have_value('家庭讨论 · 原始安排')
                page.locator('#dialog form [name=location]').fill('更新后地点')
                page.locator('#dialog form [type=submit]').click()
                desk_returned()
                assert item('events', ids['ordinary'])['location'] == '更新后地点'
                visit('events', ids['v2event'])
                expect(page.locator('#dialog h2')).to_have_text('虚构行程 · 海边三日')
                page.locator('[data-assistant-action=return]').click()
                desk_returned()
                expect(page.locator('#assistant-form textarea')).to_have_value(prompt)
                visit('trips', ids['trip'])
                expect(page.locator('#dialog h2')).to_have_text('虚构行程 · 海边三日')
                page.locator('[data-assistant-action=return]').click()
                desk_returned()
                passed('conflict_exact_event_edit_and_v2_exact_journey_entry')

                # Marking the same original task twice only makes one PATCH and no new task.
                before_tasks = len(shared()['tasks'])
                complete = action_row('tasks', ids['task']).locator('[data-assistant-action=complete]')
                complete.evaluate('(button)=>{button.click();button.click()}')
                expect(action_row('tasks', ids['task'])).to_have_count(0)
                expect(page.locator('.assistant-readback')).to_contain_text('已完成')
                assert item('tasks', ids['task'])['done'] is True and len(shared()['tasks']) == before_tasks
                assert sum(row['path'] == '/api/items/tasks/' + ids['task'] for row in writes) == 1
                passed('complete_original_task_id_no_duplicate_write')

                # A conflicting revision must never overwrite another device's edit.
                stale = item('tasks', ids['conflictTask'])
                response = ctx.request.patch(base + '/api/items/tasks/' + ids['conflictTask'], headers=headers,
                                             data={'title': '另一设备的新标题', 'revision': stale['revision']})
                assert response.status == 200
                action_row('tasks', ids['conflictTask']).locator('[data-assistant-action=complete]').click()
                expect(page.locator('.assistant-desk-error')).to_contain_text('未覆盖他人的修改')
                expect(action_row('tasks', ids['conflictTask'])).to_contain_text('另一设备的新标题')
                assert item('tasks', ids['conflictTask'])['done'] is False
                expect(page.locator('#assistant-form textarea')).to_have_value(prompt)
                passed('409_keeps_draft_and_reloads_without_overwrite')

                # Inject only a local failing write; this request does not reach SQLite.
                failure_url = base + '/api/items/tasks/' + ids['failureTask']
                page.route(failure_url, lambda route: route.fulfill(status=503, content_type='application/json', body=json.dumps({'error': '合成网络故障'})))
                action_row('tasks', ids['failureTask']).locator('[data-assistant-action=complete]').click()
                expect(page.locator('.assistant-desk-error')).to_contain_text('合成网络故障')
                assert item('tasks', ids['failureTask'])['done'] is False
                expect(page.locator('#assistant-form textarea')).to_have_value(prompt)
                expect(page.locator('[data-plan-index="1"]')).not_to_be_checked()
                page.unroute(failure_url)
                passed('503_preserves_original_task_and_planning_selection')

                # Successful write followed by failed readback is explicitly unresolved.
                page.route(base + '/api/state', lambda route: route.fulfill(status=503, content_type='application/json', body=json.dumps({'error': '合成读回故障'})))
                action_row('tasks', ids['readbackTask']).locator('[data-assistant-action=complete]').click()
                expect(page.locator('.assistant-desk-error')).to_contain_text('结果尚未读回')
                expect(action_row('tasks', ids['readbackTask']).locator('[data-assistant-action=complete]')).to_be_disabled()
                assert item('tasks', ids['readbackTask'])['done'] is True
                page.unroute(base + '/api/state')
                page.locator('#assistant-refresh').click()
                expect(action_row('tasks', ids['readbackTask'])).to_have_count(0)
                expect(page.locator('#assistant-refresh')).to_be_enabled()
                passed('readback_failure_blocks_repeat_until_refresh')

                # Preserve the original two-choice plan across all operations; apply only one.
                expect(page.locator('[data-plan-index="0"]')).to_be_checked()
                expect(page.locator('[data-plan-index="1"]')).not_to_be_checked()
                page.locator('#assistant-apply').click()
                expect(page.locator('#assistant-apply')).to_have_text('已创建 1 项')
                expect(page.locator('#assistant-apply')).to_be_disabled()
                after = shared()
                assert len(after['tasks']) == before_tasks + 1
                created = next(row for row in after['tasks'] if row['title'] == '只创建这一项')
                page.locator('#assistant-apply').evaluate('(button)=>button.click()')
                assert len(shared()['tasks']) == before_tasks + 1
                page.locator(f'.assistant-created [data-id="{created["id"]}"]').click()
                expect(page.locator('#dialog form [name=title]')).to_have_value('只创建这一项')
                page.locator('[data-assistant-action=return]').click()
                desk_returned()
                passed('draft_selection_apply_and_created_item_exact_entry')

                page.locator('[data-assistant-action=finance]').click()
                expect(page.locator('#dialog form [name=wallet]')).to_be_visible()
                page.locator('#dialog form [name=wallet]').fill('1234.56')
                page.locator('#dialog form [type=submit]').click()
                desk_returned()
                assert shared()['finance']['wallet'] == 123456 and shared()['finance']['confirmedAt']
                expect(page.locator('[data-assistant-action=finance]')).to_have_count(0)
                assert not any('/finance-hub/' in row['path'] for row in writes)
                passed('public_finance_manual_confirmation_no_ledger_or_bank_write')

                # Search results now open the exact source item instead of plain text.
                page.locator('#assistant-form textarea').fill('搜索：另一设备的新标题')
                page.locator('#assistant-form [type=submit]').click()
                expect(page.locator('.assistant-search-record')).to_have_count(1)
                page.locator('.assistant-search-record [data-assistant-action=visit]').click()
                expect(page.locator('#dialog form [name=title]')).to_have_value('另一设备的新标题')
                page.locator('[data-assistant-action=return]').click()
                desk_returned()
                passed('search_result_exact_record_entry')

                for width, name in ((390, 'phone'), (360, 'small-phone'), (1440, 'desktop-readback')):
                    page.set_viewport_size({'width': width, 'height': 900 if width > 500 else 844})
                    page.locator('#assistant-workspace').evaluate('(el)=>el.closest("dialog").scrollTop=0')
                    assert page.evaluate('document.querySelector("#dialog").scrollWidth<=document.querySelector("#dialog").clientWidth+1')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                    screenshot(name)
                passed('desktop_390_and_360_phone_no_horizontal_overflow')

                page.set_viewport_size({'width': 390, 'height': 844})
                page.locator('[data-assistant-action=jump][data-group=trips]').click()
                expect(page.locator('#assistant-group-trips')).to_be_focused()
                screenshot('trip-shortcut-phone')
                passed('phone_category_shortcut_focuses_original_group')

                # Closing while the brief is in flight must not unexpectedly reopen the modal.
                cached_brief = ctx.request.get(base + '/api/assistant/brief').json()
                page.locator('#dialog [data-action=close]').click()
                pending = []
                page.route(base + '/api/assistant/brief', lambda route: pending.append(route))
                with page.expect_request(lambda req: req.url == base + '/api/assistant/brief'):
                    page.evaluate('()=>{HomeAssistant.open()}')
                expect(page.locator('#dialog')).to_contain_text('正在核对登录状态')
                page.locator('#dialog [data-action=close]').click()
                assert pending
                with page.expect_response(lambda response: response.url == base + '/api/me'):
                    pending[0].fulfill(status=200, content_type='application/json', body=json.dumps(cached_brief))
                page.evaluate('()=>new Promise(requestAnimationFrame)')
                expect(page.locator('#dialog')).not_to_be_visible()
                page.unroute(base + '/api/assistant/brief')
                open_desk()
                expect(page.locator('#assistant-form textarea')).to_have_value('搜索：另一设备的新标题')
                passed('closing_inflight_open_stays_closed_and_context_survives')

                for theme in ('light', 'ocean'):
                    page.evaluate('(theme)=>{document.documentElement.dataset.theme=theme}', theme)
                    assert page.evaluate('document.querySelector("#dialog").scrollWidth<=document.querySelector("#dialog").clientWidth+1')
                    screenshot(theme + '-phone')
                page.evaluate('document.documentElement.dataset.theme="forest"')
                passed('action_cards_inherit_existing_light_and_ocean_themes')

                # Returning from an editor must not paint cached prompt or records while /me is unresolved or fails.
                private_prompt = '搜索：另一设备的新标题'
                visit('tasks', ids['conflictTask'])
                writes_before_return = len(writes)
                pending_me = []
                page.route(base + '/api/me', lambda route: pending_me.append(route))
                with page.expect_request(lambda req: req.url == base + '/api/me'):
                    page.locator('[data-assistant-action=return]').click()
                expect(page.locator('#dialog')).to_contain_text('正在核对登录状态')
                expect(page.locator('#assistant-form')).to_have_count(0)
                expect(page.locator('#dialog')).not_to_contain_text(private_prompt)
                assert pending_me
                pending_me[0].fulfill(status=503, content_type='application/json', body=json.dumps({'error': '合成身份核对故障'}))
                expect(page.locator('#dialog')).to_contain_text('合成身份核对故障')
                expect(page.locator('#assistant-form')).to_have_count(0)
                expect(page.locator('#dialog')).not_to_contain_text(private_prompt)
                screenshot('return-verification-failure-phone')
                page.unroute(base + '/api/me')
                page.locator('[data-assistant-action=refresh]').click()
                desk_returned()
                expect(page.locator('#assistant-form textarea')).to_have_value(private_prompt)
                assert len(writes) == writes_before_return
                passed('return_does_not_render_cached_context_before_identity_verification_or_after_503')

                # A real member switch completes while the old member's first /me response is delayed.
                # Only the browser globals normally updated by boot are refreshed here, without reloading the JS closure.
                old_me = ctx.request.get(base + '/api/me').json()
                writes_before_race = len(writes)
                first_me = []
                def delay_first_me(route):
                    if not first_me:
                        first_me.append(route)
                    else:
                        route.continue_()
                page.route(base + '/api/me', delay_first_me)
                with page.expect_request(lambda req: req.url == base + '/api/me'):
                    page.evaluate('()=>{HomeAssistant.open()}')
                assert ctx.request.post(base + '/api/login', data={'username': 'member2', 'password': 'testing-password-two'}).status == 200
                member2_me = ctx.request.get(base + '/api/me').json()
                page.evaluate('(me)=>{user=me.user;csrf=me.csrf;HomeAssistant.open()}', member2_me)
                desk_returned()
                new_prompt = '第二位成员正在编辑的新草稿'
                page.locator('#assistant-form textarea').fill(new_prompt)
                assert first_me
                with page.expect_response(lambda response: response.url == base + '/api/me'):
                    first_me[0].fulfill(status=200, content_type='application/json', body=json.dumps(old_me))
                page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
                expect(page.locator('#assistant-form textarea')).to_have_value(new_prompt)
                expect(page.locator('.assistant-desk-group')).to_have_count(5)
                expect(page.locator('#dialog')).not_to_contain_text('登录成员或家庭已变化')
                assert len(writes) == writes_before_race
                page.unroute(base + '/api/me')
                passed('late_member1_verify_cannot_clear_new_member2_context')

                # Reopen under the original member for the independent stale-global session check below.
                assert ctx.request.post(base + '/api/login', data={'username': 'member1', 'password': 'testing-password-one'}).status == 200
                fresh_member1 = ctx.request.get(base + '/api/me').json()
                page.evaluate('(me)=>{user=me.user;csrf=me.csrf;HomeAssistant.open()}', fresh_member1)
                desk_returned()

                # Changed session in the same tab: old prompt is removed before any action.
                assert ctx.request.post(base + '/api/login', data={'username': 'member2', 'password': 'testing-password-two'}).status == 200
                write_count = len(writes)
                page.locator('#assistant-refresh').click()
                expect(page.locator('#dialog')).to_contain_text('登录成员或家庭已变化')
                expect(page.locator('#dialog')).not_to_contain_text('另一设备的新标题')
                assert len(writes) == write_count
                page.reload()
                expect(page.locator('.ps-welcome')).to_be_visible()
                open_desk()
                expect(page.locator('#assistant-form textarea')).to_have_value('')
                expect(page.locator('#dialog')).not_to_contain_text('PRIVATE_PAYMENT')
                passed('member_switch_discards_context_and_private_data_absent')

                # An actual second household uses its own routing cookie and database.
                admin = app.test_client()
                admin.post('/api/login', json={'username': 'member1', 'password': 'testing-password-one'})
                admin_headers = {'X-CSRF-Token': admin.get('/api/me').json['csrf']}
                invitation = admin.post('/api/spaces/invitations', json={}, headers=admin_headers).json['invitation']
                child = new_context(390)
                response = child.request.post(base + '/api/spaces/redeem', data={'invitation': invitation, 'name': '另一个虚构家庭', 'slug': 'action-test',
                                                                                 'MEMBER1_PASSWORD': 'testing-child-one', 'MEMBER2_PASSWORD': 'testing-child-two'})
                assert response.status == 201, response.text()
                child.request.get(base + response.json()['entry'])
                assert child.request.post(base + '/api/login', data={'username': 'member1', 'password': 'testing-child-one'}).status == 200
                child_headers = {'X-CSRF-Token': child.request.get(base + '/api/me').json()['csrf']}
                assert child.request.post(base + '/api/items/tasks', headers=child_headers, data={'title': '第二家庭独有待办', 'owner': 'shared', 'due': ids['day']}).status == 201
                child_page = new_page(child)
                child_page.goto(base)
                expect(child_page.locator('.ps-welcome')).to_be_visible()
                child_page.evaluate('HomeAssistant.open()')
                expect(child_page.locator('#dialog')).to_contain_text('第二家庭独有待办')
                expect(child_page.locator('#dialog')).not_to_contain_text('旅行转换插头')
                expect(child_page.locator('#assistant-form textarea')).to_have_value('')
                assert child.request.patch(base + '/api/items/tasks/' + ids['task'], headers=child_headers, data={'done': False, 'revision': 1}).status == 404
                passed('real_second_household_cookie_and_original_id_isolation')

                # Pair only a synthetic device in the temporary server, then exercise real TV refusal.
                television = new_context()
                pair = television.request.post(base + '/api/pair/start', data={}).json()
                approved = admin.post('/api/pair/approve', json={'code': pair['code'], 'name': '合成测试电视', 'focus': 'member1'}, headers=admin_headers)
                assert approved.status_code == 200, approved.json
                assert television.request.post(base + '/api/pair/poll', data={'secret': pair['secret']}).json()['approved']
                assert television.request.get(base + '/api/assistant/brief').status == 403
                tvpage = new_page(television)
                tvpage.goto(base + '/tv')
                expect(tvpage.locator('.board')).to_be_visible()
                tv_requests = []
                tvpage.on('request', lambda req: tv_requests.append(req.url) if '/api/assistant/' in req.url else None)
                tvpage.evaluate('HomeAssistant.open()')
                expect(tvpage.locator('#assistant-workspace')).to_have_count(0)
                assert not tv_requests
                anonymous = new_context()
                assert anonymous.request.get(base + '/api/assistant/brief').status == 401
                demo_page = new_page(anonymous)
                demo_page.goto(base + '/demo')
                expect(demo_page.locator('.ps-welcome')).to_be_visible()
                demo_requests = []
                demo_page.on('request', lambda req: demo_requests.append(req.url) if '/api/' in req.url else None)
                demo_page.evaluate('HomeAssistant.open()')
                expect(demo_page.locator('#assistant-demo')).to_contain_text('虚构内容')
                assert not demo_requests
                passed('anonymous_401_paired_tv_403_and_demo_no_requests')

                assert not report['privateEndpointRequests'], report['privateEndpointRequests']
                assert not report['externalRequests'], report['externalRequests']
                assert not report['pageErrors'], report['pageErrors']
                report['browserWrites'] = writes
                report['changedStaticSha256'] = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                                 for path in (ROOT / 'static/home-assistant.js', ROOT / 'static/home-assistant.css')}
                report['passed'] = True
                browser.close()
                browser = None
        except Exception as error:
            report['failure'] = type(error).__name__ + ': ' + str(error)
            if page:
                try:
                    screenshot('failure')
                except Exception:
                    pass
            raise
        finally:
            (out / 'assistant-actions-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'report': str(out / 'assistant-actions-verification.json'), 'failure': report.get('failure')}, ensure_ascii=False))
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == '__main__':
    main()
