"""Actual temporary Flask/SQLite/Edge import checks; no real data or provider traffic."""
from copy import deepcopy
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
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server, WSGIRequestHandler


class Quiet(WSGIRequestHandler):
    def log(self, *_args, **_kwargs):
        pass


def synthetic_plan(version=2):
    plan = {'title': '虚构导入 · 日本法国三城', 'start': '2026-10-01', 'end': '2026-10-12',
            'international': True, 'memberIds': ['member1', 'member2'], 'budget': 2000000, 'paid': 0, 'saved': 0,
            'destinations': [{'key': 'tokyo', 'country': '日本', 'city': '东京', 'arrival': '2026-10-01', 'departure': '2026-10-04', 'timeZone': 'Asia/Tokyo'},
                             {'key': 'kyoto', 'country': '日本', 'city': '京都', 'arrival': '2026-10-04', 'departure': '2026-10-07', 'timeZone': 'Asia/Tokyo'},
                             {'key': 'paris', 'country': '法国', 'city': '巴黎', 'arrival': '2026-10-08', 'departure': '2026-10-12', 'timeZone': 'Europe/Paris'}],
            'checklist': [{'key': 'entry', 'title': '核对证件 · 虚构准备', 'owner': 'member1', 'dueOffsetDays': -30},
                          {'key': 'pack', 'title': '行李清单 · 虚构准备', 'owner': 'shared', 'dueOffsetDays': -2}],
            'shopping': [{'key': 'adapter', 'title': '转换插头 · 虚构采购', 'quantity': '1件', 'owner': 'shared', 'budget': 10000}]}
    if version == 1:
        plan['title'] = '虚构粘贴 · 日本法国三城'
        for item in plan['destinations']:
            item.pop('timeZone')
        return plan
    return {**plan, 'schemaVersion': 2, 'referenceTimezone': 'Asia/Shanghai',
            'segments': [{'key': 'flight', 'kind': 'flight', 'title': '虚构航班',
                          'departure': {'airport': 'PVG', 'city': '上海', 'local': '2026-10-01T10:00', 'timeZone': 'Asia/Shanghai'},
                          'arrival': {'airport': 'NRT', 'city': '东京', 'local': '2026-10-01T15:00', 'timeZone': 'Asia/Tokyo'}},
                         {'key': 'stay', 'kind': 'stay', 'title': '虚构东京住宿', 'propertyName': '虚构旅馆', 'address': '示例地址',
                          'timeZone': 'Asia/Tokyo', 'checkInDate': '2026-10-01', 'checkOutDate': '2026-10-03'},
                         {'key': 'walk', 'kind': 'activity', 'title': '虚构巴黎散步',
                          'start': {'local': '2026-10-09T10:00', 'timeZone': 'Europe/Paris'},
                          'end': {'local': '2026-10-09T11:00', 'timeZone': 'Europe/Paris'}}]}


def main():
    output = ROOT / 'test-results'
    output.mkdir(exist_ok=True)
    report = {'passed': False, 'scope': 'Actual loopback Flask / temporary SQLite / Edge / synthetic input only',
              'checks': [], 'screenshots': [], 'externalRequests': [], 'pageErrors': [],
              'configurationBoundary': {'usesConfigurationOverride': False, 'requiresActualDefault': {'SESSION_REFRESH_EACH_REQUEST': False},
                'reason': 'Joint frontend/backend candidate verification; app.py dependency recorded separately. Not deployed.',
                'baselineFailureReport': 'journey-import-baseline-cookie-failure.json'}}
    page = None

    def passed(name, **detail):
        report['checks'].append({'name': name, 'passed': True, **detail})

    def shot(name):
        path = output / ('journey-import-' + name + '.png')
        page.screenshot(path=str(path))
        report['screenshots'].append(str(path))

    with tempfile.TemporaryDirectory(prefix='journey-import-guard-') as temp:
        app = create_app({'TESTING': True, 'DATA_DIR': temp, 'SECRET_KEY': 'synthetic-import-guard',
                          'SESSION_COOKIE_SECURE': False, 'MEMBER1_PASSWORD': 'testing-password-one', 'MEMBER2_PASSWORD': 'testing-password-two',
                          'MICROSOFT_CLIENT_ID': '', 'MICROSOFT_CLIENT_SECRET': '', 'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': '', 'OPENAI_API_KEY': ''})
        assert app.config['SESSION_REFRESH_EACH_REQUEST'] is False, 'Requires the reviewed session-default patch; do not mask it with test configuration.'
        server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=Quiet)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
                ctx = browser.new_context(viewport={'width': 1440, 'height': 1000})

                def guard(route):
                    if route.request.url.startswith(base + '/'):
                        route.continue_()
                    else:
                        report['externalRequests'].append(route.request.url)
                        route.abort()

                ctx.route('**/*', guard)
                page = ctx.new_page()
                page.on('pageerror', lambda error: report['pageErrors'].append(str(error)))

                def login(member='member1', password='testing-password-one', reload=True):
                    assert ctx.request.post(base + '/api/login', data={'username': member, 'password': password}).status == 200
                    if reload:
                        page.goto(base)
                        expect(page.locator('.ps-welcome')).to_be_visible()

                def counts():
                    state = ctx.request.get(base + '/api/state').json()
                    return {kind: len(state[kind]) for kind in ('trips', 'tasks', 'shopping', 'events')}

                def new_draft(title='尚未保存的手工草稿'):
                    page.evaluate('JourneyUI.create()')
                    page.locator('#journey-core-fields [name=title]').fill(title)
                    page.locator('#journey-trip-note').fill('必须保留的草稿备注')
                    page.locator('.journey-import > summary').click()

                def fields():
                    return page.evaluate('[...document.querySelectorAll("#journey-core-fields input,#journey-core-fields select,#journey-trip-note,#journey-destinations input")].map(x=>[x.name,x.value,x.checked])')

                def settle():
                    page.evaluate('new Promise(resolve => setTimeout(resolve, 100))')
                    page.wait_for_load_state('networkidle')

                def wait_for(predicate):
                    for _ in range(100):
                        if predicate():
                            return
                        page.evaluate('new Promise(resolve => setTimeout(resolve, 20))')
                    raise AssertionError('Controlled asynchronous request did not reach its test boundary')

                def import_json(plan):
                    page.locator('#journey-import-json').fill(json.dumps(plan, ensure_ascii=False))
                    page.locator('[data-journey=import]').click()

                def hold_preview(plan):
                    held = []
                    page.route('**/api/journeys/preview', lambda route: held.append(route))
                    import_json(plan)
                    wait_for(lambda: bool(held))
                    return held[0]

                def release_preview(route, response=None, error=False):
                    if error:
                        route.fulfill(status=503, json={'error': '旧导入请求的合成错误'})
                    else:
                        route.fulfill(response=response or route.fetch())
                    page.unroute('**/api/journeys/preview')
                    settle()

                def install_file_hold():
                    page.evaluate('''() => {
                      window.syntheticFileReads = [];
                      window.nativeFileText ||= File.prototype.text;
                      File.prototype.text = function() {
                        const file = this;
                        return new Promise((resolve, reject) => syntheticFileReads.push({
                          name:file.name, resolve:() => nativeFileText.call(file).then(resolve,reject),
                          reject:() => reject(new Error('旧文件读取的合成错误'))
                        }));
                      };
                    }''')

                def choose_file(plan, filename='fictional-plan.json'):
                    page.locator('#journey-import-file').set_input_files({'name': filename, 'mimeType': 'application/json', 'buffer': json.dumps(plan, ensure_ascii=False).encode()})

                def release_file(index=0, error=False):
                    page.evaluate('([index,error]) => { if(error) syntheticFileReads[index].reject(); else syntheticFileReads[index].resolve(); }', [index, error])
                    settle()

                login()
                baseline = counts()
                new_draft()
                wrapper = {'plan': synthetic_plan(), 'journeyId': 'foreign-target-not-accepted', 'revision': 99, 'previewToken': 'external-receipt-not-accepted'}
                choose_file(wrapper)
                expect(page.locator('#journey-import-json')).to_have_value(json.dumps(wrapper, ensure_ascii=False))
                page.locator('[data-journey=import]').click()
                expect(page.locator('#journey-core-fields [name=title]')).to_have_value(wrapper['plan']['title'])
                expect(page.locator('.journey-destination')).to_have_count(3)
                expect(page.locator('.journey-v2-segment')).to_have_count(3)
                expect(page.locator('#journey-core-fields [name=budget]')).to_have_value('20000')
                assert counts() == baseline
                page.locator('#journey-core-fields [name=title]').fill(wrapper['plan']['title'] + ' · 已审阅')
                page.locator('#journey-form [type=submit]').click()
                expect(page.locator('#journey-apply')).to_be_enabled()
                assert counts() == baseline
                shot('v2-review-desktop')
                page.locator('#journey-apply').click()
                expect(page.locator('.journey-detail-top')).to_be_visible()
                assert counts() == {'trips': 1, 'tasks': 2, 'shopping': 1, 'events': 4}
                first = ctx.request.get(base + '/api/journeys').json()['journeys'][0]
                assert first['id'] != wrapper['journeyId'] and len(first['plan']['destinations']) == 3
                passed('v2_file_two_countries_three_cities_review_then_explicit_apply', entities=counts())

                new_draft()
                before = counts()
                import_json(synthetic_plan(1))
                expect(page.locator('#journey-core-fields [name=title]')).to_have_value(synthetic_plan(1)['title'])
                assert counts() == before
                page.locator('#journey-form [type=submit]').click()
                expect(page.locator('#journey-apply')).to_be_enabled()
                assert counts() == before
                page.locator('#journey-apply').click()
                expect(page.locator('.journey-detail-top')).to_be_visible()
                assert counts() == {'trips': 2, 'tasks': 4, 'shopping': 2, 'events': 8}
                passed('v1_paste_two_countries_three_cities_explicit_apply', entities=counts())
                baseline = counts()
                page.set_viewport_size({'width': 390, 'height': 844})

                for version, method in [(1, 'file'), (2, 'paste')]:
                    new_draft()
                    if method == 'file':
                        choose_file(synthetic_plan(version))
                        expect(page.locator('#journey-import-json')).to_have_value(json.dumps(synthetic_plan(version), ensure_ascii=False))
                        page.locator('[data-journey=import]').click()
                    else:
                        import_json(synthetic_plan(version))
                    expect(page.locator('#journey-core-fields [name=title]')).to_have_value(synthetic_plan(version)['title'])
                    assert counts() == baseline
                    passed(f'v{version}_{method}_review_without_creation')

                bad_inputs = [('invalid_json', '{broken'), ('invalid_top_level', '[]'),
                              ('unsupported_schema', json.dumps({**synthetic_plan(1), 'schemaVersion': 99})),
                              ('paste_size_limit', ' ' * 200001),
                              ('fractional_minor_units', json.dumps({**synthetic_plan(1), 'budget': 1.5}))]
                for name, raw in bad_inputs:
                    new_draft()
                    saved = fields()
                    page.locator('#journey-import-json').fill(raw)
                    page.locator('[data-journey=import]').click()
                    expect(page.locator('.journey-error')).not_to_have_text('')
                    expect(page.locator('[data-journey=import]')).to_be_enabled()
                    assert fields() == saved and counts() == baseline
                    passed(name + '_preserves_draft')
                shot('invalid-amount-draft-mobile')

                new_draft()
                saved = fields()
                page.locator('#journey-import-json').fill('之前的粘贴内容')
                page.locator('#journey-import-file').set_input_files({'name': 'oversize.json', 'mimeType': 'application/json', 'buffer': b' ' * 200001})
                expect(page.locator('.journey-error')).to_contain_text('200 KB')
                expect(page.locator('#journey-import-json')).to_have_value('之前的粘贴内容')
                assert fields() == saved
                passed('oversize_file_preserves_paste_and_manual_fields')

                new_draft()
                saved = fields()
                page.route('**/api/journeys/templates', lambda route: route.fulfill(status=200, json={'supportedSchemaVersions': [1]}))
                import_json(synthetic_plan())
                expect(page.locator('.journey-error')).to_contain_text('不支持 v2')
                assert fields() == saved
                page.unroute('**/api/journeys/templates')
                passed('old_server_capability_preserves_v2_input_and_draft')

                new_draft()
                saved = fields()
                held = hold_preview(synthetic_plan(1))
                release_preview(held, error=True)
                expect(page.locator('.journey-error')).to_contain_text('合成错误')
                assert fields() == saved and counts() == baseline
                expect(page.locator('#journey-import-json')).to_have_value(json.dumps(synthetic_plan(1), ensure_ascii=False))
                passed('active_preview_503_keeps_original_draft_and_json')

                for outcome, destination in [('success', 'new'), ('error', 'new'), ('success', 'close'), ('error', 'close'), ('success', 'same_form_edit')]:
                    new_draft()
                    held = hold_preview(synthetic_plan(1))
                    response = held.fetch() if outcome == 'success' else None
                    if destination == 'new':
                        new_draft('后来新建的草稿B')
                    elif destination == 'close':
                        page.locator('#dialog [aria-label=关闭]').click()
                    else:
                        page.locator('#journey-core-fields [name=title]').fill('同一表单的新输入B')
                    release_preview(held, response, error=outcome == 'error')
                    if destination == 'close':
                        expect(page.locator('#dialog')).not_to_be_visible()
                    else:
                        expect(page.locator('#journey-core-fields [name=title]')).to_have_value('后来新建的草稿B' if destination == 'new' else '同一表单的新输入B')
                        expect(page.locator('.journey-error')).to_have_text('')
                    assert counts() == baseline
                    passed('late_preview_' + outcome + '_after_' + destination)
                shot('newer-draft-preserved-mobile')

                # A real workflow revision conflict, rather than only a synthetic status code.
                page.evaluate('(id) => JourneyUI.open(id)', first['id'])
                page.locator('[data-journey=edit]').click()
                page.locator('.journey-import > summary').click()
                saved = fields()
                headers = {'X-CSRF-Token': ctx.request.get(base + '/api/me').json()['csrf']}
                changed = deepcopy(first['plan'])
                changed['title'] += ' · 另一端更新'
                preview = ctx.request.post(base + '/api/journeys/preview', data={'journeyId': first['id'], 'revision': first['revision'], 'plan': changed}, headers=headers)
                assert preview.status == 200, preview.text()
                applied = ctx.request.post(base + '/api/journeys/apply', data={'previewToken': preview.json()['previewToken'], 'idempotencyKey': 'synthetic-concurrent-import-change'}, headers=headers)
                assert applied.status in (200, 201), applied.text()
                import_json(synthetic_plan())
                expect(page.locator('.journey-error')).to_contain_text('版本')
                assert fields() == saved
                passed('actual_409_during_import_preserves_existing_edit_draft')

                install_file_hold()
                for outcome, destination in [('success', 'new'), ('error', 'new'), ('success', 'close'), ('error', 'close'), ('success', 'same_form_paste')]:
                    new_draft()
                    index = page.evaluate('syntheticFileReads.length')
                    choose_file(synthetic_plan())
                    wait_for(lambda: page.evaluate('syntheticFileReads.length') > index)
                    if destination == 'new':
                        new_draft('文件读取期间的新草稿B')
                        page.locator('#journey-import-json').fill('新草稿的粘贴内容B')
                    elif destination == 'close':
                        page.locator('#dialog [aria-label=关闭]').click()
                    else:
                        page.locator('#journey-import-json').fill('同页后来粘贴B')
                    release_file(index, error=outcome == 'error')
                    if destination == 'close':
                        expect(page.locator('#dialog')).not_to_be_visible()
                    else:
                        expect(page.locator('#journey-import-json')).to_have_value('新草稿的粘贴内容B' if destination == 'new' else '同页后来粘贴B')
                        expect(page.locator('.journey-error')).to_have_text('')
                    passed('late_file_' + outcome + '_after_' + destination)

                new_draft()
                saved = fields()
                index = page.evaluate('syntheticFileReads.length')
                choose_file(synthetic_plan())
                wait_for(lambda: page.evaluate('syntheticFileReads.length') == index + 1)
                release_file(index, error=True)
                expect(page.locator('.journey-error')).to_contain_text('旧文件读取的合成错误')
                assert fields() == saved
                passed('active_file_read_rejection_is_caught_and_draft_retained')

                new_draft()
                index = page.evaluate('syntheticFileReads.length')
                choose_file(synthetic_plan(), 'first.json')
                wait_for(lambda: page.evaluate('syntheticFileReads.length') == index + 1)
                second_plan = {**synthetic_plan(1), 'title': '第二次选择的文件'}
                choose_file(second_plan, 'second.json')
                wait_for(lambda: page.evaluate('syntheticFileReads.length') == index + 2)
                release_file(index + 1)
                expect(page.locator('#journey-import-json')).to_have_value(json.dumps(second_plan, ensure_ascii=False))
                release_file(index)
                expect(page.locator('#journey-import-json')).to_have_value(json.dumps(second_plan, ensure_ascii=False))
                passed('second_file_wins_when_first_read_finishes_later')

                new_draft()
                held = hold_preview(synthetic_plan(1))
                response = held.fetch()
                login('member2', 'testing-password-two', reload=False)
                release_preview(held, response)
                expect(page.locator('#dialog')).to_contain_text('登录成员或家庭已变化')
                expect(page.locator('#dialog')).not_to_contain_text('虚构导入')
                expect(page.locator('#journey-import-json')).to_have_count(0)
                passed('actual_member_cookie_change_before_preview_result_clears_old_content')
                shot('identity-change-mobile')

                login('member2', 'testing-password-two')
                install_file_hold()
                new_draft()
                choose_file(synthetic_plan())
                wait_for(lambda: page.evaluate('syntheticFileReads.length') == 1)
                login(reload=False)
                release_file()
                expect(page.locator('#dialog')).to_contain_text('登录成员或家庭已变化')
                expect(page.locator('#journey-import-json')).to_have_count(0)
                passed('actual_member_cookie_change_before_file_result_clears_old_content')

                login()
                new_draft()
                held = hold_preview(synthetic_plan(1))
                response = held.fetch()
                invitation = ctx.request.post(base + '/api/spaces/invitations', data={}, headers={'X-CSRF-Token': ctx.request.get(base + '/api/me').json()['csrf']}).json()['invitation']
                child = ctx.request.post(base + '/api/spaces/redeem', data={'invitation': invitation, 'name': '另一个虚构家庭', 'slug': 'import-isolation',
                                         'MEMBER1_PASSWORD': 'testing-child-one', 'MEMBER2_PASSWORD': 'testing-child-two'})
                assert child.status == 201, child.text()
                ctx.request.get(base + child.json()['entry'])
                login('member1', 'testing-child-one', reload=False)
                release_preview(held, response)
                expect(page.locator('#dialog')).to_contain_text('登录成员或家庭已变化')
                expect(page.locator('#journey-import-json')).to_have_count(0)
                assert counts() == {'trips': 0, 'tasks': 0, 'shopping': 0, 'events': 0}
                passed('actual_household_switch_drops_old_import_result')

                page.goto(base + '/demo')
                expect(page.locator('.ps-welcome')).to_be_visible()
                requests = []
                page.on('request', lambda request: requests.append(request.url) if '/api/' in request.url else None)
                new_draft()
                import_json(synthetic_plan())
                expect(page.locator('#journey-core-fields [name=title]')).to_have_value(synthetic_plan()['title'])
                page.locator('#journey-form [type=submit]').click()
                expect(page.locator('#journey-apply')).to_be_disabled()
                assert not requests, requests
                assert page.locator('#dialog').evaluate('(el) => el.scrollWidth <= el.clientWidth + 1')
                passed('mobile_demo_import_previews_without_network_or_apply')
                shot('demo-review-mobile')

                television = browser.new_context(viewport={'width': 1920, 'height': 1080})
                television.route('**/*', guard)
                pair = television.request.post(base + '/api/pair/start', data={}).json()
                admin = app.test_client()
                assert admin.post('/api/login', json={'username': 'member1', 'password': 'testing-password-one'}).status_code == 200
                token = admin.get('/api/me').json['csrf']
                assert admin.post('/api/pair/approve', json={'code': pair['code'], 'name': '虚构导入电视', 'focus': 'member1'}, headers={'X-CSRF-Token': token}).status_code == 200
                assert television.request.post(base + '/api/pair/poll', data={'secret': pair['secret']}).json()['approved']
                tv = television.new_page()
                tv.goto(base + '/tv')
                expect(tv.locator('.board')).to_be_visible()
                tv.evaluate('JourneyUI.create()')
                expect(tv.locator('#journey-import-json')).to_have_count(0)
                assert television.request.post(base + '/api/journeys/preview', data={'plan': synthetic_plan()}).status == 403
                passed('paired_tv_has_no_import_editor_and_preview_is_forbidden')

                with app.extensions['cloud_accounts'].db() as con:
                    cloud = {table: con.execute('SELECT count(*) FROM ' + table).fetchone()[0] for table in ('task_publications', 'calendar_publications')}
                assert cloud == {'task_publications': 0, 'calendar_publications': 0}
                assert not report['externalRequests'] and not report['pageErrors']
                passed('no_cloud_publications_external_requests_or_page_errors')
                report['passed'] = True
                browser.close()
        except Exception as error:
            report['failure'] = repr(error)
            if page and not page.is_closed():
                try:
                    shot('failure')
                except Exception:
                    pass
            raise
        finally:
            server.shutdown()
            report['sourceHashes'] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in ('app.py', 'static/journey-ui.js', 'tests/browser_journey_import_guard_check.py')}
            path = output / 'journey-import-guard-verification.json'
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'report': str(path), 'failure': report.get('failure')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
