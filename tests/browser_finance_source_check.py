"""Real local Flask + browser source preview/confirm; synthetic input only."""
import json
from pathlib import Path
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from app import create_app
from test_finance_source_bridge import synthetic_candidate
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server, WSGIRequestHandler


class Quiet(WSGIRequestHandler):
    def log(self, *_args, **_kwargs):
        pass


def main():
    output = ROOT / 'test-results'
    output.mkdir(exist_ok=True)
    checks, errors, external = [], [], []
    with tempfile.TemporaryDirectory(prefix='family-finance-source-browser-') as folder:
        app = create_app({'TESTING': True, 'SECRET_KEY': 'source-browser-isolated-key', 'DATA_DIR': folder,
                          'SESSION_COOKIE_SECURE': False, 'MEMBER1_PASSWORD': 'testing-password-one',
                          'MEMBER2_PASSWORD': 'testing-password-two'})
        server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=Quiet)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        origin = f'http://127.0.0.1:{server.server_port}'
        file = Path(folder) / 'finance-source-candidate.json'
        file.write_text(json.dumps(synthetic_candidate()), encoding='utf-8')
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
                context = browser.new_context(viewport={'width': 390, 'height': 844})
                def guard(route):
                    if not route.request.url.startswith(origin + '/'):
                        external.append(route.request.url)
                        route.abort()
                    else:
                        route.continue_()
                context.route('**/*', guard)
                assert context.request.post(origin + '/api/login', data={'username': 'member1', 'password': 'testing-password-one'}).status == 200
                headers = {'X-CSRF-Token': context.request.get(origin + '/api/me').json()['csrf']}
                page = context.new_page()
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(origin)
                expect(page.locator('.ps-welcome')).to_be_visible()
                page.evaluate('ProductShell.navigate("finance")')
                page.locator('[data-action=wealth-private]').click()
                page.locator('[data-finance-source-open]').click()
                expect(page.locator('#finance-source-form')).to_be_visible()
                assert context.request.get(origin + '/api/finance-baseline/private').json() is None
                page.locator('[name=candidateFile]').set_input_files(file)
                page.locator('#finance-source-form [type=submit]').click()
                expect(page.locator('#finance-source-ack')).to_be_visible()
                expect(page.locator('[data-fs=confirm]')).to_be_disabled()
                expect(page.locator('.finance-source-dates')).to_contain_text('2026-08-31')
                expect(page.locator('.finance-source-shared')).not_to_contain_text('SYNTHETIC_PRIVATE')
                assert context.request.get(origin + '/api/finance-baseline/private').json() is None
                for width, height in [(360,800),(390,844),(1440,1000)]:
                    page.set_viewport_size({'width': width, 'height': height})
                    assert page.evaluate('document.querySelector("#dialog").scrollWidth <= document.querySelector("#dialog").clientWidth + 1')
                    if width in (390,1440):
                        page.screenshot(path=str(output / f'finance-source-preview-{width}.png'), full_page=True)
                checks.append('Private entry, file preview with no baseline write, clear source/balance dates, unchecked acknowledgement and 360/390/1440px layout')
                page.locator('#finance-source-ack').check()
                page.route('**/api/finance-baseline/imports/confirm', lambda route: route.fulfill(status=503, content_type='application/json', body='{"error":"Synthetic service unavailable"}'))
                page.locator('[data-fs=confirm]').click()
                expect(page.locator('#finance-source-error')).to_contain_text('来源服务暂时不可用。文件和预览仍保留，请稍后重试。')
                expect(page.locator('#finance-source-ack')).to_be_checked()
                expect(page.locator('[data-fs=confirm]')).to_be_enabled()
                assert context.request.get(origin + '/api/finance-baseline/private').json() is None
                page.unroute('**/api/finance-baseline/imports/confirm')
                page.locator('[data-fs=confirm]').click()
                expect(page.locator('#finance-source-success')).to_contain_text('已更新')
                saved = context.request.get(origin + '/api/finance-baseline/private').json()
                assert saved['revision'] == 1 and saved['assets'][0]['amountCents'] == 12000
                shared = context.request.get(origin + '/api/state').json()['wealth']
                assert shared[0]['recordedAssetCents'] == 12000 and 'SYNTHETIC_PRIVATE' not in json.dumps(shared)
                checks.append('503 keeps candidate/acknowledgement; retry confirms and persisted private/shared values read back')

                # A second device accepts a different candidate after this UI preview.
                second = synthetic_candidate(amount_cents=13000)
                file.write_text(json.dumps(second), encoding='utf-8')
                page.locator('[data-fs=open]').click()
                page.locator('[name=candidateFile]').set_input_files(file)
                page.locator('#finance-source-form [type=submit]').click()
                expect(page.locator('#finance-source-ack')).to_be_visible()
                concurrent = synthetic_candidate(amount_cents=14000)
                status = context.request.get(origin + '/api/finance-baseline/imports/status').json()['current']
                preview = context.request.post(origin + '/api/finance-baseline/imports/preview', headers=headers, data={'candidate': concurrent, 'expectedRevision': status['revision'], 'expectedSourceDigest': status['sourceDigest']})
                assert preview.status == 200, preview.text()
                applied = context.request.post(origin + '/api/finance-baseline/imports/confirm', headers=headers, data={'candidate': concurrent, 'previewToken': preview.json()['previewToken']})
                assert applied.status == 200, applied.text()
                page.locator('#finance-source-ack').check()
                page.locator('[data-fs=confirm]').click()
                expect(page.locator('#finance-source-error')).to_contain_text('文件仍保留')
                expect(page.locator('[data-fs=confirm]')).to_be_disabled()
                page.locator('[data-fs=preview]').click()
                expect(page.locator('#finance-source-ack')).to_be_enabled()
                expect(page.locator('#finance-source-ack')).not_to_be_checked()
                page.locator('#finance-source-ack').check()
                page.locator('[data-fs=confirm]').click()
                expect(page.locator('#finance-source-success')).to_be_visible()
                saved = context.request.get(origin + '/api/finance-baseline/private').json()
                assert saved['revision'] == 3 and saved['assets'][0]['amountCents'] == 13000
                checks.append('Actual second-device CAS conflict rejects stale confirm, retains file, requires new preview and acknowledgement')

                page.locator('[data-fs=open]').click()
                page.locator('[name=candidateFile]').set_input_files(file)
                page.locator('#finance-source-form [type=submit]').click()
                page.locator('#finance-source-ack').check()
                page.locator('[data-fs=confirm]').click()
                expect(page.locator('#finance-source-success')).to_contain_text('没有重复更新')
                assert context.request.get(origin + '/api/finance-baseline/private').json()['revision'] == 3
                checks.append('Reimporting identical source is unchanged, without increasing baseline revision')
                other = browser.new_context()
                assert other.request.post(origin + '/api/login', data={'username': 'member2', 'password': 'testing-password-two'}).status == 200
                assert other.request.get(origin + '/api/finance-baseline/private').json() is None
                assert other.request.get(origin + '/api/finance-baseline/imports/status').json()['lastReceipt'] is None
                other.close()
                private_requests = []
                for path in ['/demo#finance', '/demo?tv=1']:
                    page.goto(origin + path)
                    page.wait_for_function('() => typeof FinanceSourceUI === "object"')
                    page.on('request', lambda r: private_requests.append(r.url) if '/api/finance-baseline/' in r.url else None)
                    page.evaluate('FinanceSourceUI.open()')
                    expect(page.locator('[data-finance-source-open]')).to_have_count(0)
                    expect(page.locator('#finance-source-root')).to_have_count(0)
                assert not private_requests
                assert not errors and not external, (errors, external)
                checks.append('Other member cannot read baseline or receipts; demo and TV make no source-import requests')
                context.close()
                browser.close()
        finally:
            server.shutdown()
            worker.join(timeout=5)
    result = {'passed': True, 'checks': checks, 'pageErrors': errors, 'externalRequests': external,
              'productionWrites': 0, 'input': 'synthetic candidate only'}
    (output / 'finance-source-browser-verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
