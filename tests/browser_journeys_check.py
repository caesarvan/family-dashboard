"""Synthetic end-to-end travel wizard, update and demo checks in real Edge."""
from datetime import date, timedelta
import json
from pathlib import Path
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import create_app
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server, WSGIRequestHandler


class Quiet(WSGIRequestHandler):
    def log(self, *_args, **_kwargs):
        pass


def main():
    result_dir = ROOT / 'test-results'
    result_dir.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        app = create_app({'TESTING': True, 'SECRET_KEY': 'journey-browser-only-key', 'DATA_DIR': temp,
                          'SESSION_COOKIE_SECURE': False, 'MEMBER1_PASSWORD': 'testing-password-one',
                          'MEMBER2_PASSWORD': 'testing-password-two'})
        server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=Quiet)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
                context = browser.new_context(viewport={'width': 1440, 'height': 1050})
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                origin = f'http://127.0.0.1:{server.server_port}'
                page.goto(origin)
                page.locator('[name=password]').fill('testing-password-one')
                page.locator('#login-form button[type=submit]').click()
                page.wait_for_function('() => typeof JourneyUI === "object" && typeof data !== "undefined" && data !== null')
                page.evaluate('JourneyUI.create()')
                form = page.locator('#journey-form')
                form.locator('[name=title]').fill('京都 · 秋日准备')
                form.locator('[name=international]').select_option('true')
                form.locator('[name=budget]').fill('20000')
                form.locator('[name=country]').fill('日本')
                form.locator('[name=city]').fill('京都')
                form.locator('[type=submit]').click()
                expect(page.locator('#journey-checklist .journey-review-row')).to_have_count(7)
                page.locator('[data-journey=purchase]').click()
                purchase = page.locator('#journey-purchases .purchase')
                purchase.locator('[name=title]').fill('旅行收纳袋')
                purchase.locator('[name=budget]').fill('128.50')
                purchase.locator('[name=owner]').select_option('member2')
                expect(page.locator('#journey-apply')).to_be_disabled()
                page.locator('[data-journey=repreview]').click()
                expect(page.locator('#journey-apply')).to_be_enabled()
                page.screenshot(path=str(result_dir / 'journey-preview-desktop.png'), full_page=True)
                page.locator('#journey-apply').click()
                expect(page.locator('.journey-detail-top')).to_be_visible()
                first = context.request.get(origin + '/api/journeys').json()['journeys'][0]
                assert first['shopping'][0]['budget'] == 12850
                assert len(first['events']) == 2
                assert len(first['tasks']) == 7
                page.locator('[data-journey=toggle][data-kind=tasks]').first.click()
                expect(page.locator('.journey-task-list .completed')).to_have_count(1)
                page.locator('[data-journey=edit]').click()
                form = page.locator('#journey-form')
                original_start = form.locator('[name=start]').input_value()
                start = date.fromisoformat(original_start)
                form.locator('[name=start]').fill(str(start + timedelta(days=2)))
                form.locator('[name=start]').press('Tab')
                form.locator('[name=start]').fill(str(start + timedelta(days=5)))
                form.locator('[name=start]').press('Tab')
                assert form.locator('[name=arrival]').input_value() == str(start + timedelta(days=5))
                form.locator('[type=submit]').click()
                expect(page.locator('#journey-apply')).to_be_enabled()
                page.locator('#journey-apply').click()
                expect(page.locator('.journey-detail-top')).to_be_visible()
                updated = context.request.get(origin + '/api/journeys').json()['journeys'][0]
                assert updated['revision'] == 2
                assert updated['trip']['start'] == str(start + timedelta(days=5))
                for kind in ('tasks', 'shopping', 'events'):
                    assert {item['id'] for item in first[kind]} == {item['id'] for item in updated[kind]}
                assert updated['progress']['done'] == 1
                for width, height in [(1440, 1050), (390, 844)]:
                    page.set_viewport_size({'width': width, 'height': height})
                    assert page.evaluate('document.querySelector("#dialog").scrollWidth <= document.querySelector("#dialog").clientWidth + 2')
                    page.screenshot(path=str(result_dir / f'journey-detail-{width}.png'), full_page=True)
                page.locator('[data-action=close]').click()
                # Stable trip entity IDs open the same workflow from the board.
                page.evaluate('(id) => JourneyUI.open(id)', updated['tripId'])
                expect(page.locator('.journey-detail-top')).to_be_visible()
                demo = browser.new_context(viewport={'width': 390, 'height': 844})
                demo_page = demo.new_page()
                requests = []
                demo_page.on('request', lambda request: requests.append(request.url) if '/api/journeys' in request.url else None)
                demo_page.on('pageerror', lambda error: errors.append(str(error)))
                demo_page.goto(origin + '/demo')
                demo_page.wait_for_function('() => typeof JourneyUI === "object" && typeof data !== "undefined" && data !== null')
                demo_page.evaluate('JourneyUI.create()')
                demo_page.locator('#journey-form [name=title]').fill('演示旅程')
                demo_page.locator('#journey-form [name=city]').fill('京都')
                demo_page.locator('#journey-form [type=submit]').click()
                expect(demo_page.locator('#journey-apply')).to_be_disabled()
                assert requests == [], requests
                assert not errors, errors
                report = {'create': 'passed', 'rescheduleSameIds': 'passed', 'completedState': 'preserved',
                          'tripIdEntry': 'passed', 'desktopAndPhone': 'passed', 'demoBackendWrites': 0, 'pageErrors': errors}
                (result_dir / 'journey-browser-verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
                print(json.dumps(report))
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == '__main__':
    main()
