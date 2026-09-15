"""Travel timing hold/review in actual Flask and browser, fake provider HTTP."""
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from test_calendar_publish import env, queue, publication
from test_journey_publication_review import hold_timing
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server, WSGIRequestHandler


class Quiet(WSGIRequestHandler):
    def log(self, *_args, **_kwargs):
        pass


def run(browser, provider, output):
    errors, external = [], []
    with tempfile.TemporaryDirectory(prefix='family-timing-review-') as folder:
        fixture = env.__wrapped__(Path(folder), SimpleNamespace(param=provider))
        app, client, headers, remote, _ = fixture
        with app.extensions['cloud_accounts'].db() as con:
            con.execute("UPDATE entities SET data=? WHERE id='trip-1'", (json.dumps({'title':'Synthetic journey','destination':'Synthetic city','start':'2026-10-01','end':'2026-10-03','budget':0,'paid':0,'saved':0,'note':''}),))
        rid = queue(fixture)
        publisher = app.extensions['calendar_publish']
        publisher.process(rid)
        hold_timing(app)
        server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=Quiet)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        origin = f'http://127.0.0.1:{server.server_port}'
        context = browser.new_context(viewport={'width': 390, 'height': 844})
        try:
            def guard(route):
                if not route.request.url.startswith(origin + '/'):
                    external.append(route.request.url)
                    route.abort()
                else:
                    route.continue_()
            context.route('**/*', guard)
            assert context.request.post(origin + '/api/login', data={'username':'member1','password':'testing-password-one'}).status == 200
            page = context.new_page()
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(origin)
            page.wait_for_function('() => typeof CalendarPublish === "object" && user?.role === "member"')
            page.evaluate('CalendarPublish.open("journey-1")')
            expect(page.locator('[data-cp=review-preview]')).to_be_visible()
            expect(page.locator('[data-cp=retry]')).to_have_count(0)
            before = len(remote.calls)
            page.locator('[data-cp=review-preview]').click()
            expect(page.locator('#dialog-title')).to_have_text('核对旅行时间变化')
            expect(page.locator('#dialog')).to_contain_text('Asia/Tokyo')
            assert not any(c[0] in {'POST','PATCH','DELETE'} for c in remote.calls[before:])
            for width, height in [(360,800),(390,844),(1440,1000)]:
                page.set_viewport_size({'width':width,'height':height})
                assert page.evaluate('document.querySelector("#dialog").scrollWidth <= document.querySelector("#dialog").clientWidth + 1')
                if width == 390:
                    page.screenshot(path=str(output / f'timing-review-{provider}-phone.png'), full_page=True)
            page.locator('[data-cp=pause]').click()
            expect(page.locator('[data-cp=review-preview]')).to_be_visible()
            expect(page.locator('[data-cp=resume]')).to_have_count(0)
            assert publication(fixture)['reviewRequired'] == 1
            page.locator('[data-cp=review-preview]').click()
            page.locator('[data-cp=review-confirm]').click()
            expect(page.locator('#calendar-publish-root')).to_be_visible()
            assert publication(fixture)['reviewRequired'] == 0
            assert remote.created == 1 and remote.patched == 0
            publisher.process(rid)
            assert remote.created == 1 and remote.patched == 1
            page.locator('[data-cp=refresh]').click()
            expect(page.locator('#calendar-publications')).to_contain_text('已发布')
            assert not errors and not external, (errors, external)
        finally:
            context.close()
            server.shutdown()
            worker.join(timeout=5)
    return {'provider':provider,'passed':True,'checks':['semantic-hold-visible','preview-GET-only','pause-cannot-bypass-review','360/390/1440px-layout','explicit-review-confirm','worker-updates-original-remote-id'],
            'pageErrors':errors,'externalRequests':external,'realCloudWrites':0}


def main():
    output = ROOT / 'test-results'
    output.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
        try:
            result = {'passed':True,'results':[run(browser, provider, output) for provider in ('microsoft','google')]}
        finally:
            browser.close()
    (output / 'journey-timing-review-browser-verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
