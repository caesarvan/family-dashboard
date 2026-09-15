"""Real local layout editing, conflict resolution, device isolation and responsive rendering."""
import json
from pathlib import Path
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import create_app
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server, WSGIRequestHandler


class Quiet(WSGIRequestHandler):
    def log(self, *_args, **_kwargs):
        pass


def main():
    output = ROOT / 'test-results'
    output.mkdir(exist_ok=True)
    checks, errors = [], []
    with tempfile.TemporaryDirectory(prefix='family-layout-browser-') as folder:
        app = create_app({'TESTING': True, 'SECRET_KEY': 'layout-browser-isolated-key', 'DATA_DIR': folder,
                          'SESSION_COOKIE_SECURE': False, 'MEMBER1_PASSWORD': 'testing-password-one',
                          'MEMBER2_PASSWORD': 'testing-password-two'})
        server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=Quiet)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)

                def logged_context(number=1, width=1440, height=1000):
                    context = browser.new_context(viewport={'width': width, 'height': height})
                    response = context.request.post(base + '/api/login', data={'username': f'member{number}', 'password': 'testing-password-' + ('one' if number == 1 else 'two')})
                    assert response.status == 200
                    page = context.new_page()
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(base)
                    expect(page.locator('.ps-home-board')).to_be_visible()
                    return context, page

                def visible_cards(page):
                    return page.locator('.ps-home-board > [data-dashboard-card]').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.dashboardCard)')

                def open_editor(page):
                    page.locator('[data-ps-layout]').first.click()
                    expect(page.locator('#ps-layout-form [type=submit]')).to_be_enabled()

                def save(page):
                    page.locator('#ps-layout-form [type=submit]').click()
                    expect(page.locator('#dialog')).not_to_be_visible()

                desktop, page = logged_context()
                expect(page.locator('.ps-home-board > .card')).to_have_count(5)
                open_editor(page)
                page.locator('[data-layout-key=tasks][data-layout-move="-1"]').click()
                page.locator('[data-layout-key=tasks][data-layout-move="-1"]').click()
                page.locator('[data-layout-card=shopping]').focus()
                page.keyboard.press('Alt+ArrowUp')
                expect(page.locator('.ps-layout-row').first).to_have_attribute('data-layout-card', 'tasks')
                expect(page.locator('.ps-layout-row').nth(2)).to_have_attribute('data-layout-card', 'shopping')
                page.locator('[data-layout-visible=finance]').uncheck()
                page.screenshot(path=str(output / 'layout-editor-desktop.png'), full_page=True)
                save(page)
                expect(page.locator('.ps-home-board > .card')).to_have_count(4)
                assert visible_cards(page) == ['tasks', 'calendar', 'shopping', 'trips']
                actual = desktop.request.get(base + '/api/dashboard-layout').json()
                assert actual == {'revision': 1, 'order': ['tasks', 'calendar', 'shopping', 'finance', 'trips'], 'hidden': ['finance']}
                checks.append('Desktop buttons and Alt+Arrow reorder; hide finance; actual API readback matches')
                page.screenshot(path=str(output / 'layout-custom-desktop.png'), full_page=True)

                mobile_context, mobile = logged_context(width=390, height=844)
                expect(mobile.locator('.ps-home-board > .card')).to_have_count(4)
                expect(mobile.locator('.ps-home-board > .card').first).to_have_attribute('data-dashboard-card', 'tasks')
                checks.append('Fresh phone browser reads same member layout from backend')
                for width, height in [(360, 800), (390, 844), (820, 1180), (1440, 1000)]:
                    mobile.set_viewport_size({'width': width, 'height': height})
                    assert mobile.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                    open_editor(mobile)
                    assert mobile.evaluate('document.querySelector("#dialog").scrollWidth<=document.querySelector("#dialog").clientWidth+1')
                    dimensions = mobile.locator('.ps-layout-move button').first.bounding_box()
                    assert dimensions['width'] >= 44 and dimensions['height'] >= 44
                    if width == 390:
                        button_box=mobile.locator('#ps-layout-form [type=submit]').bounding_box()
                        dialog_box=mobile.locator('#dialog').bounding_box()
                        assert button_box['y']+button_box['height']<=dialog_box['y']+dialog_box['height']+1
                        expect(mobile.locator('[data-layout-retry]')).not_to_be_visible()
                        mobile.screenshot(path=str(output / 'layout-editor-phone.png'), full_page=True)
                    mobile.locator('#ps-layout-form [data-action=close]').click()
                checks.append('360/390/820/1440 layouts and dialogs no horizontal overflow; move buttons at least 44px')

                # All hidden is prevented in the real form; defaults are only applied after save.
                mobile.set_viewport_size({'width': 390, 'height': 844})
                open_editor(mobile)
                for key in ['calendar', 'shopping', 'trips']:
                    mobile.locator(f'[data-layout-visible={key}]').uncheck()
                mobile.locator('[data-layout-visible=tasks]').click()
                expect(mobile.locator('[data-layout-visible=tasks]')).to_be_checked()
                expect(mobile.locator('#ps-layout-form .error')).to_contain_text('至少保留一张')
                mobile.locator('[data-layout-reset]').click()
                expect(mobile.locator('.ps-layout-row input:checked')).to_have_count(5)
                assert desktop.request.get(base + '/api/dashboard-layout').json()['revision'] == 1
                save(mobile)
                assert desktop.request.get(base + '/api/dashboard-layout').json()['revision'] == 2
                checks.append('At least one visible card; reset is a draft until saved')

                # A failed save retains both the draft and existing server layout.
                mobile.route('**/api/dashboard-layout', lambda route: route.fulfill(status=503, content_type='application/json', body='{"error":"布局保存暂不可用"}') if route.request.method == 'PUT' else route.continue_())
                open_editor(mobile)
                mobile.locator('[data-layout-visible=trips]').uncheck()
                mobile.locator('#ps-layout-form [type=submit]').click()
                expect(mobile.locator('#ps-layout-form .error')).to_contain_text('布局保存暂不可用')
                expect(mobile.locator('[data-layout-visible=trips]')).not_to_be_checked()
                assert mobile_context.request.get(base + '/api/dashboard-layout').json()['hidden'] == []
                mobile.locator('#ps-layout-form [data-action=close]').click()
                mobile.unroute('**/api/dashboard-layout')
                checks.append('503 retains unsaved draft and leaves actual server state unchanged')

                # A second device changes the same member while this form is open.
                open_editor(mobile)
                mobile.locator('[data-layout-key=finance][data-layout-move="-1"]').click()
                mobile.locator('[data-layout-visible=calendar]').uncheck()
                csrf = desktop.request.get(base + '/api/me').json()['csrf']
                remote = {'revision': 2, 'order': ['trips', 'calendar', 'finance', 'tasks', 'shopping'], 'hidden': ['tasks']}
                assert desktop.request.put(base + '/api/dashboard-layout', data=remote, headers={'X-CSRF-Token': csrf}).status == 200
                mobile.locator('#ps-layout-form [type=submit]').click()
                expect(mobile.locator('[data-layout-compare]')).to_be_visible()
                expect(mobile.locator('[data-layout-visible=calendar]')).not_to_be_checked()
                mobile.locator('[data-layout-compare]').click()
                expect(mobile.locator('.ps-layout-conflict li').first).to_have_text('旅行计划')
                mobile.locator('[data-layout-keep-draft]').click()
                assert desktop.request.get(base + '/api/dashboard-layout').json()['hidden'] == ['tasks']
                save(mobile)
                persisted = desktop.request.get(base + '/api/dashboard-layout').json()
                assert persisted['revision'] == 4 and persisted['hidden'] == ['calendar'] and persisted['order'][0] == 'finance'
                checks.append('409 preserves draft, compares actual remote layout, explicit keep+save resolves conflict')

                # Returning to a foreground page reads remote change without sharing a draft.
                page.evaluate('document.dispatchEvent(new Event("visibilitychange"))')
                expect(page.locator('.ps-home-board > .card').first).to_have_attribute('data-dashboard-card', 'finance')
                expect(page.locator('.ps-home-board > [data-dashboard-card=calendar]')).to_have_count(0)
                checks.append('Foreground refresh synchronizes saved layout to existing desktop')
                _, partner = logged_context(number=2, width=390, height=844)
                expect(partner.locator('.ps-home-board > .card')).to_have_count(5)
                expect(partner.locator('.ps-home-board > .card').first).to_have_attribute('data-dashboard-card', 'calendar')
                checks.append('Other member still receives independent default layout')

                # Hide does not remove a module's page or business data.
                mobile.evaluate('ProductShell.navigate("calendar")')
                expect(mobile.locator('.ps-calendar-workspace > .calendar-card')).to_be_visible()
                mobile.evaluate('ProductShell.navigate("settings")')
                expect(mobile.locator('[data-portability-open]')).to_be_visible()
                mobile.evaluate('ProductShell.navigate("tasks")')
                expect(mobile.locator('[data-task-publish-open="1"]')).to_be_visible()
                assert mobile.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                checks.append('Hidden calendar still opens from navigation; export/settings and member task-publish entries visible')

                demo = browser.new_page(viewport={'width': 390, 'height': 844})
                demo_writes = []
                demo.on('request', lambda req: demo_writes.append(req.url) if '/api/' in req.url and req.method in ['PUT', 'POST', 'PATCH', 'DELETE'] else None)
                demo.goto(base + '/demo')
                open_editor(demo)
                demo.locator('[data-layout-visible=finance]').uncheck()
                save(demo)
                expect(demo.locator('.ps-home-board > .card')).to_have_count(4)
                demo.reload()
                expect(demo.locator('.ps-home-board > .card')).to_have_count(4)
                assert demo_writes == []
                checks.append('Demo applies and reloads local layout without API writes')

                tv = browser.new_page()
                tv_requests = []
                tv.on('request', lambda req: tv_requests.append(req.url) if '/api/dashboard-layout' in req.url else None)
                for width, height in [(1280, 720), (1920, 1080), (3840, 2160)]:
                    tv.set_viewport_size({'width': width, 'height': height})
                    tv.goto(base + '/demo?tv=1')
                    expect(tv.locator('.board > .card')).to_have_count(5)
                    assert tv.locator('[data-ps-layout]').count() == 0
                    assert tv.evaluate('document.documentElement.scrollWidth<=innerWidth+1 && document.documentElement.scrollHeight<=innerHeight+1')
                assert tv_requests == []
                checks.append('720p/1080p/4K TV retains fixed five-card layout with zero layout API requests')
                assert errors == [], errors
                result = {'passed': True, 'checks': checks, 'pageErrors': errors, 'productionWrites': 0, 'apiLayoutFinal': persisted}
                (output / 'dashboard-layout-verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                print(json.dumps(result, ensure_ascii=False, indent=2))
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == '__main__':
    main()
