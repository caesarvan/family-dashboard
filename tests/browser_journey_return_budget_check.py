"""Real loopback Flask/SQLite/Edge verification; all records and images are synthetic."""
import base64
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import create_app
from browser_assistant_actions_check import Quiet, seed, synthetic_png
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server


def main():
    out = ROOT / 'test-results'
    out.mkdir(exist_ok=True)
    report = {'passed': False, 'scope': 'temporary Flask + SQLite, actual Edge, synthetic data, loopback only',
              'checks': [], 'screenshots': [], 'externalRequests': [], 'privateRequests': [], 'pageErrors': []}
    page = None

    def passed(name, **details):
        report['checks'].append({'name': name, 'passed': True, **details})

    def screenshot(name):
        path = out / ('journey-return-' + name + '.png')
        page.screenshot(path=str(path))
        report['screenshots'].append(str(path))

    with tempfile.TemporaryDirectory(prefix='journey-return-budget-') as temp:
        app = create_app({'TESTING': True, 'SECRET_KEY': 'synthetic-journey-return-key', 'DATA_DIR': temp,
                          'SESSION_COOKIE_SECURE': False, 'MEMBER1_PASSWORD': 'testing-password-one',
                          'MEMBER2_PASSWORD': 'testing-password-two', 'OPENAI_API_KEY': '', 'OPENAI_MODEL': '',
                          'MICROSOFT_CLIENT_ID': '', 'MICROSOFT_CLIENT_SECRET': '', 'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': ''})
        ids = seed(app)
        admin = app.test_client()
        admin.post('/api/login', json={'username': 'member1', 'password': 'testing-password-one'})
        ah = {'X-CSRF-Token': admin.get('/api/me').json['csrf']}
        detail = admin.get('/api/journeys/' + ids['journey']).json
        plan = detail['plan']
        plan['shopping'].append({'key': 'bag', 'title': '第二件采购 · 防水收纳袋', 'quantity': '1 件', 'owner': 'shared', 'budget': None})
        preview = admin.post('/api/journeys/preview', json={'journeyId': ids['journey'], 'revision': detail['revision'], 'plan': plan}, headers=ah)
        assert preview.status_code == 200, preview.json
        applied = admin.post('/api/journeys/apply', json={'previewToken': preview.json['previewToken'], 'idempotencyKey': 'synthetic-second-purchase'}, headers=ah)
        assert applied.status_code in (200, 201), applied.json
        detail = admin.get('/api/journeys/' + ids['journey']).json
        ids['second'] = next(item['id'] for item in detail['shopping'] if item['workflowKey'] == 'shopping:bag')
        ids['prep'] = detail['tasks'][0]['id']
        image = admin.post('/api/photos', json={'dataUrl': 'data:image/png;base64,' + base64.b64encode(synthetic_png()).decode()}, headers=ah).json
        first = next(item for item in detail['shopping'] if item['id'] == ids['shopping'])
        assert admin.patch('/api/items/shopping/' + ids['shopping'], json={'revision': first['revision'], 'photoIds': [image['id']]}, headers=ah).status_code == 200
        other_plan = {**plan, 'title': '另一趟虚构旅行'}
        preview = admin.post('/api/journeys/preview', json={'plan': other_plan}, headers=ah)
        assert preview.status_code == 200, preview.json
        applied = admin.post('/api/journeys/apply', json={'previewToken': preview.json['previewToken'], 'idempotencyKey': 'synthetic-other-journey'}, headers=ah)
        assert applied.status_code == 201, applied.json
        ids['otherJourney'] = applied.json['id']
        server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=Quiet)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
                ctx = browser.new_context(viewport={'width': 1440, 'height': 1000})

                def guard(route):
                    if not route.request.url.startswith(base + '/'):
                        report['externalRequests'].append(route.request.url)
                        route.abort()
                    else:
                        route.continue_()

                ctx.route('**/*', guard)
                assert ctx.request.post(base + '/api/login', data={'username': 'member1', 'password': 'testing-password-one'}).status == 200
                headers = {'X-CSRF-Token': ctx.request.get(base + '/api/me').json()['csrf']}
                page = ctx.new_page()
                page.on('pageerror', lambda error: report['pageErrors'].append(str(error)))
                writes = []
                page.on('request', lambda req: writes.append(urlsplit(req.url).path) if req.method not in ('GET', 'HEAD') else None)
                page.on('request', lambda req: report['privateRequests'].append(req.url) if any(part in req.url for part in ('/api/finance-hub/', '/api/private-finance', '/api/finance-baseline')) else None)
                page.goto(base + '/#trips')
                expect(page.locator('.ps-trip-grid')).to_be_visible()

                def latest():
                    response = ctx.request.get(base + '/api/journeys/' + ids['journey'])
                    assert response.status == 200, response.text()
                    return response.json()

                def item(kind, uid):
                    return next(row for row in latest()[kind] if row['id'] == uid)

                def open_trip():
                    page.evaluate('(id) => JourneyUI.open(id)', ids['journey'])
                    expect(page.locator('.journey-detail-top')).to_be_visible()

                def edit(kind, uid):
                    page.locator(f'[data-journey="linked-edit"][data-kind="{kind}"][data-id="{uid}"]').click()
                    expect(page.locator('#journey-return-bar')).to_be_visible()
                    expect(page.locator('#dialog form')).to_be_visible()

                def returned(kind, uid):
                    expect(page.locator(f'[data-journey-region="{kind}"] .journey-return-result')).to_be_visible()
                    expect(page.locator('#dialog-title')).to_have_text('虚构行程 · 海边三日')
                    expect(page.locator(f'[data-journey="linked-edit"][data-id="{uid}"]')).to_be_focused()

                open_trip()
                for uid, budget in ((ids['shopping'], '123.45'), (ids['second'], '50')):
                    edit('shopping', uid)
                    page.locator('#dialog form [name=budget]').fill(budget)
                    page.locator('#dialog form [name=actual]').fill(budget)
                    page.locator('#dialog form [name=done]').check()
                    before = len(writes)
                    page.locator('#dialog form [type=submit]').click()
                    returned('shopping', uid)
                    assert item('shopping', uid)['budget'] == round(float(budget) * 100)
                    assert len(writes) == before + 1
                assert latest()['budget']['purchaseBudget'] == 17345
                assert latest()['budget']['purchaseActual'] == 17345
                expect(page.locator('[data-journey-region=shopping]')).to_contain_text('2 / 2')
                passed('two_consecutive_purchase_edits_return_same_trip_row_with_real_budget_progress', purchaseBudget=17345, purchaseActual=17345)
                screenshot('desktop-purchases')

                edit('tasks', ids['prep'])
                page.locator('#dialog form [name=done]').check()
                page.locator('#dialog form [type=submit]').click()
                returned('tasks', ids['prep'])
                assert item('tasks', ids['prep'])['done']
                expect(page.locator('[data-journey-region=tasks] .pill')).to_contain_text('1 /')
                passed('preparation_save_updates_progress_and_returns_original_region')

                page.set_viewport_size({'width': 390, 'height': 844})
                edit('shopping', ids['shopping'])
                original = item('shopping', ids['shopping'])
                page.locator('#dialog form [name=title]').fill('未保存的临时修改')
                before = len(writes)
                page.locator('[data-journey=return-linked]').click()
                expect(page.locator('#journey-return-bar .error')).to_contain_text('尚未保存')
                expect(page.locator('#dialog form [name=title]')).to_have_value('未保存的临时修改')
                page.locator('#dialog .dialog-footer [data-action=close]').click()
                returned('shopping', ids['shopping'])
                assert item('shopping', ids['shopping']) == original
                assert len(writes) == before
                passed('dirty_text_preserved_return_cancel_discards_explicitly_without_write')

                edit('shopping', ids['shopping'])
                page.locator('[data-photo-remove]').click()
                page.locator('[data-journey=return-linked]').click()
                expect(page.locator('#journey-return-bar .error')).to_contain_text('尚未保存')
                expect(page.locator('#shopping-photo-list img')).to_have_count(0)
                assert len(writes) == before
                screenshot('mobile-photo-draft')
                page.locator('#dialog .dialog-footer [data-action=close]').click()
                returned('shopping', ids['shopping'])
                assert item('shopping', ids['shopping'])['photoIds'] == [image['id']]
                passed('photo_only_removal_draft_is_guarded_and_explicit_cancel_keeps_saved_photo')

                edit('shopping', ids['second'])
                pending_photos = []
                page.route('**/api/photos', lambda route: pending_photos.append(route) if route.request.method == 'POST' else route.continue_())
                page.locator('#shopping-photo-input').set_input_files({'name': 'fictional.png', 'mimeType': 'image/png', 'buffer': synthetic_png()})
                expect(page.locator('#dialog form [type=submit]')).to_be_disabled()
                page.locator('[data-journey=return-linked]').click()
                expect(page.locator('#journey-return-bar .error')).to_contain_text('正在保存或上传')
                assert len(pending_photos) == 1
                pending_photos[0].continue_()
                page.unroute('**/api/photos')
                expect(page.locator('#shopping-photo-list img')).to_have_count(1)
                expect(page.locator('#dialog form [type=submit]')).to_be_enabled()
                page.locator('[data-journey=return-linked]').click()
                expect(page.locator('#journey-return-bar .error')).to_contain_text('尚未保存')
                page.locator('#dialog form [type=submit]').click()
                returned('shopping', ids['second'])
                assert len(item('shopping', ids['second'])['photoIds']) == 1
                passed('inflight_and_completed_photo_upload_guarded_until_saved')

                edit('shopping', ids['second'])
                page.locator('#dialog form [name=budget]').fill('222')
                old = item('shopping', ids['second'])
                assert ctx.request.patch(base + '/api/items/shopping/' + ids['second'], headers=headers, data={'revision': old['revision'], 'budget': 7777}).status == 200
                page.locator('#dialog form [type=submit]').click()
                expect(page.locator('#dialog form .error')).to_contain_text('更新')
                expect(page.locator('#dialog form [name=budget]')).to_have_value('222')
                expect(page.locator('#journey-return-bar')).to_be_visible()
                assert item('shopping', ids['second'])['budget'] == 7777
                page.locator('#dialog .dialog-footer [data-action=close]').click()
                returned('shopping', ids['second'])
                passed('real_409_keeps_draft_and_cancel_reads_new_revision')

                edit('shopping', ids['second'])
                page.locator('#dialog form [name=budget]').fill('333')
                url = '**/api/items/shopping/' + ids['second']
                page.route(url, lambda route: route.fulfill(status=503, json={'error': '合成保存服务暂不可用'}) if route.request.method == 'PATCH' else route.continue_())
                page.locator('#dialog form [type=submit]').click()
                expect(page.locator('#dialog form .error')).to_contain_text('合成保存服务暂不可用')
                expect(page.locator('#dialog form [name=budget]')).to_have_value('333')
                page.unroute(url)
                assert item('shopping', ids['second'])['budget'] == 7777
                page.locator('#dialog .dialog-footer [data-action=close]').click()
                returned('shopping', ids['second'])
                passed('503_save_keeps_original_editor_draft_without_false_return')

                edit('shopping', ids['second'])
                page.locator('#dialog form [name=budget]').fill('444')
                url = '**/api/journeys/' + ids['journey']
                page.route(url, lambda route: route.fulfill(status=503, json={'error': '合成读回暂不可用'}))
                before = len(writes)
                page.locator('#dialog form [type=submit]').click()
                expect(page.locator('#journey-return-pending')).to_contain_text('合成读回暂不可用')
                expect(page.locator('#dialog')).not_to_contain_text('虚构行程')
                expect(page.locator('.journey-metrics')).to_have_count(0)
                assert item('shopping', ids['second'])['budget'] == 44400
                page.unroute(url)
                page.locator('[data-journey=retry-return]').click()
                returned('shopping', ids['second'])
                assert len(writes) == before + 1
                passed('successful_save_failed_readback_neutral_retry_without_duplicate_write')

                # Real server values; procurement is deliberately nonzero, never added again.
                for paid, reserved, label, amount, kind in ((10000, 20000, '还需准备', '¥200', 'remaining'),
                                                           (20000, 40000, '已付 + 预留超额', '¥100', 'reserved'),
                                                           (70000, 30000, '已付款超预算', '¥200', 'paid')):
                    trip = latest()['trip']
                    assert ctx.request.patch(base + '/api/items/trips/' + ids['trip'], headers=headers, data={'revision': trip['revision'], 'budget': 50000, 'paid': paid, 'saved': reserved}).status == 200
                    open_trip()
                    status = page.locator('[data-budget-status]')
                    expect(status).to_have_attribute('data-budget-status', kind)
                    expect(status).to_contain_text(label)
                    expect(status).to_contain_text(amount)
                    passed('budget_' + kind + '_with_procurement_not_double_counted', total=50000, paid=paid, reserved=reserved)
                    screenshot('mobile-budget-' + kind)
                    page.evaluate('refresh(true).then(() => manage("trips"))')
                    old_card = page.locator('.trip-item').filter(has=page.locator('h3', has_text='虚构行程 · 海边三日'))
                    expect(old_card.locator('.trip-stats span').last).to_contain_text(label)
                    expect(old_card.locator('.trip-stats span').last).to_contain_text(amount)
                passed('legacy_travel_manager_uses_same_three_budget_meanings')
                open_trip()
                assert page.locator('#dialog').evaluate('(el) => el.scrollWidth <= el.clientWidth + 1')
                assert page.locator('body').evaluate('(el) => el.scrollWidth <= innerWidth + 1')
                passed('mobile_390px_no_horizontal_overflow')

                # Assistant owns the original return chain; no competing journey bar/close callback.
                page.evaluate('HomeAssistant.open()')
                expect(page.locator('.assistant-desk-group')).to_have_count(5)
                page.locator(f'[data-assistant-action=visit][data-kind=trips][data-id="{ids["trip"]}"]').click()
                expect(page.locator('#assistant-return-bar')).to_be_visible()
                page.locator(f'[data-journey=linked-edit][data-id="{ids["second"]}"]').click()
                expect(page.locator('#assistant-return-bar')).to_be_visible()
                expect(page.locator('#journey-return-bar')).to_have_count(0)
                page.locator('#dialog .dialog-footer [data-action=close]').click()
                expect(page.locator('.assistant-desk-group')).to_have_count(5)
                expect(page.locator('#assistant-refresh')).to_be_enabled()
                passed('assistant_parent_return_takes_priority_without_double_reopen')
                page.locator('#dialog [aria-label=关闭]').click()

                open_trip()
                edit('shopping', ids['second'])
                before = len(writes)
                held = []
                page.route('**/api/me', lambda route: held.append(route))
                page.locator('[data-journey=return-linked]').click()
                expect(page.locator('#journey-return-pending')).to_contain_text('正在核对')
                expect(page.locator('#dialog')).not_to_contain_text('虚构行程')
                assert len(held) == 1
                held[0].fulfill(status=503, json={'error': '身份核对服务暂不可用'})
                expect(page.locator('#journey-return-pending')).to_contain_text('身份核对服务暂不可用')
                expect(page.locator('#dialog')).not_to_contain_text('第二件采购')
                page.unroute('**/api/me')
                page.locator('[data-journey=retry-return]').click()
                returned('shopping', ids['second'])
                assert len(writes) == before
                passed('pending_or_failed_identity_check_never_paints_cached_travel')

                old_me = ctx.request.get(base + '/api/me').json()
                held = []
                page.route('**/api/me', lambda route: held.append(route) if not held else route.continue_())
                page.locator(f'[data-journey=linked-edit][data-id="{ids["second"]}"]').click()
                page.evaluate('(id) => JourneyUI.open(id)', ids['otherJourney'])
                expect(page.locator('#dialog-title')).to_have_text('另一趟虚构旅行')
                with page.expect_response(lambda response: response.url == base + '/api/me'):
                    held[0].fulfill(status=200, json=old_me)
                page.unroute('**/api/me')
                page.evaluate('new Promise(resolve => setTimeout(resolve, 100))')
                expect(page.locator('#dialog .journey-error')).to_have_text('')
                expect(page.locator('#dialog form')).to_have_count(0)
                passed('late_linked_edit_response_does_not_mutate_new_trip')
                open_trip()

                edit('shopping', ids['second'])
                assert ctx.request.post(base + '/api/login', data={'username': 'member2', 'password': 'testing-password-two'}).status == 200
                page.locator('[data-journey=return-linked]').click()
                expect(page.locator('#dialog')).to_contain_text('登录成员或家庭已变化')
                expect(page.locator('#dialog')).not_to_contain_text('虚构行程')
                expect(page.locator('[data-journey=retry-return]')).to_have_count(0)
                assert len(writes) == before
                passed('server_member_switch_drops_old_context_without_write')

                page.reload()
                expect(page.locator('.ps-trip-grid')).to_be_visible()
                open_trip()
                assert ctx.request.post(base + '/api/login', data={'username': 'member1', 'password': 'testing-password-one'}).status == 200
                page.locator(f'[data-journey=linked-edit][data-id="{ids["second"]}"]').click()
                expect(page.locator('#dialog')).to_contain_text('登录成员或家庭已变化')
                expect(page.locator('#dialog')).not_to_contain_text('虚构行程')
                expect(page.locator('#dialog form')).to_have_count(0)
                passed('member_switch_before_linked_edit_clears_old_details')

                # Start an old A return, then open B before releasing A's delayed identity response.
                page.reload()
                expect(page.locator('.ps-trip-grid')).to_be_visible()
                open_trip()
                edit('shopping', ids['second'])
                old_me = ctx.request.get(base + '/api/me').json()
                held = []
                page.route('**/api/me', lambda route: held.append(route) if not held else route.continue_())
                page.locator('[data-journey=return-linked]').click()
                expect(page.locator('#journey-return-pending')).to_be_visible()
                assert ctx.request.post(base + '/api/login', data={'username': 'member2', 'password': 'testing-password-two'}).status == 200
                page.evaluate('boot()')
                open_trip()
                held[0].fulfill(status=200, json=old_me)
                page.unroute('**/api/me')
                page.evaluate('new Promise(resolve => setTimeout(resolve, 100))')
                expect(page.locator('.journey-detail-top')).to_be_visible()
                expect(page.locator('#dialog')).not_to_contain_text('登录成员或家庭已变化')
                passed('late_old_identity_response_cannot_clear_new_member_trip')

                # Actual routing-cookie switch to a second independently initialized household.
                edit('shopping', ids['second'])
                invitation = admin.post('/api/spaces/invitations', json={}, headers=ah).json['invitation']
                child = ctx.request.post(base + '/api/spaces/redeem', data={'invitation': invitation, 'name': '隔离测试家庭', 'slug': 'journey-return-test',
                    'MEMBER1_PASSWORD': 'testing-child-one', 'MEMBER2_PASSWORD': 'testing-child-two'})
                assert child.status == 201, child.text()
                ctx.request.get(base + child.json()['entry'])
                assert ctx.request.post(base + '/api/login', data={'username': 'member1', 'password': 'testing-child-one'}).status == 200
                before = len(writes)
                page.locator('[data-journey=return-linked]').click()
                expect(page.locator('#dialog')).to_contain_text('登录成员或家庭已变化')
                expect(page.locator('#dialog')).not_to_contain_text('虚构行程')
                assert ctx.request.get(base + '/api/journeys/' + ids['journey']).status == 404
                assert len(writes) == before
                passed('real_household_switch_clears_travel_context_and_id_isolation')

                page.goto(base + '/demo#trips')
                expect(page.locator('.ps-trip-grid')).to_be_visible()
                before = len(writes)
                page.evaluate('JourneyUI.open()')
                expect(page.locator('#dialog')).to_contain_text('演示空间')
                expect(page.locator('[data-journey=linked-edit]')).to_have_count(0)
                assert len(writes) == before
                passed('demonstration_has_no_persistent_editor_or_write')
                television = browser.new_context(viewport={'width': 1920, 'height': 1080})
                television.route('**/*', guard)
                pair = television.request.post(base + '/api/pair/start', data={}).json()
                assert admin.post('/api/pair/approve', json={'code': pair['code'], 'name': '合成旅行电视', 'focus': 'member1'}, headers=ah).status_code == 200
                assert television.request.post(base + '/api/pair/poll', data={'secret': pair['secret']}).json()['approved']
                tv = television.new_page()
                tv.goto(base + '/tv')
                expect(tv.locator('.board')).to_be_visible()
                expect(tv.locator('.topbar')).to_contain_text('电视 · 只读')
                tv.evaluate('(id) => JourneyUI.open(id)', ids['journey'])
                expect(tv.locator('[data-journey=linked-edit]')).to_have_count(0)
                expect(tv.locator('#journey-return-bar')).to_have_count(0)
                passed('paired_tv_keeps_readonly_layout_without_return_editor')
                assert not report['externalRequests'], report['externalRequests']
                assert not report['privateRequests'], report['privateRequests']
                assert not report['pageErrors'], report['pageErrors']
                passed('no_external_account_finance_or_console_error')
                report['passed'] = True
                browser.close()
        except Exception as error:
            report['error'] = repr(error)
            if page and not page.is_closed():
                try:
                    screenshot('failure')
                except Exception:
                    pass
            raise
        finally:
            server.shutdown()
            report['sourceHashes'] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in ('static/journey-ui.js', 'static/journey-ui.css', 'static/app.js')}
            (out / 'journey-return-budget-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'report': str(out / 'journey-return-budget-verification.json')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
