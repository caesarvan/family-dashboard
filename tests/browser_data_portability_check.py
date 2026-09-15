"""Settings -> explicit personal ZIP download, readback and failed-download recovery."""
import csv
import hashlib
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import threading
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from app import create_app
from test_data_portability import seed
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server, WSGIRequestHandler


class Quiet(WSGIRequestHandler):
    def log(self, *_args, **_kwargs):
        pass


def main():
    out = ROOT / 'test-results'
    out.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='family-export-browser-') as folder:
        app = create_app({'TESTING': True, 'SECRET_KEY': 'portability-browser-isolated-key', 'DATA_DIR': folder,
                          'SESSION_COOKIE_SECURE': False, 'MEMBER1_PASSWORD': 'testing-password-one',
                          'MEMBER2_PASSWORD': 'testing-password-two'})
        seed(app)  # Existing synthetic fixture: both members' distinct private markers and fake credentials.
        server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=Quiet)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        checks, errors, downloads = [], [], []
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
                context = browser.new_context(viewport={'width': 390, 'height': 844}, accept_downloads=True)
                assert context.request.post(base + '/api/login', data={'username': 'member1', 'password': 'testing-password-one'}).status == 200
                headers = {'X-CSRF-Token': context.request.get(base + '/api/me').json()['csrf']}
                assert context.request.post(base + '/api/finance-hub/investments', headers=headers,
                                            data={'name': 'EXPORT_OWN_UNKNOWN_VALUE', 'institution': 'SYNTHETIC_BANK', 'assetType': '基金',
                                                  'currency': 'USD', 'cost': '123.45', 'value': None, 'asOf': '2026-09-15'}).status == 201
                assert context.request.put(base + '/api/dashboard-layout', headers=headers,
                                           data={'revision': 0, 'order': ['tasks', 'calendar', 'finance', 'shopping', 'trips'], 'hidden': ['trips']}).status == 200
                summary = context.request.get(base + '/api/portability/summary').json()
                assert summary['personal'] == {'transactions': 1, 'investments': 1, 'budgets': 0, 'financeBaselines': 1, 'assistantPlans': 0}
                assert summary['shared'] == {'events': 1}

                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('download', lambda download: downloads.append(download.suggested_filename))
                page.goto(base)
                expect(page.locator('.ps-welcome')).to_be_visible()
                page.evaluate('ProductShell.navigate("settings")')
                page.locator('[data-portability-open]').click()
                expect(page.locator('#portability-form')).to_be_visible()
                expect(page.locator('#dialog .info-box')).to_have_text('1 条账单与订单 · 1 项投资 · 0 项预算')
                expect(page.locator('[name=includeShared]')).not_to_be_checked()
                assert not downloads
                for width, height in [(360, 800), (390, 844), (1440, 1000)]:
                    page.set_viewport_size({'width': width, 'height': height})
                    assert page.evaluate('document.querySelector("#dialog").scrollWidth<=document.querySelector("#dialog").clientWidth+1')
                    if width == 390:
                        page.screenshot(path=str(out / 'data-portability-phone.png'), full_page=True)
                checks.append('Settings entry and actual summary agree; shared checkbox unchecked; opening does not export')

                def download_zip(name):
                    with page.expect_download() as event:
                        page.locator('#portability-form [type=submit]').click()
                    download = event.value
                    assert download.failure() is None
                    assert download.suggested_filename.startswith('family-data-member1-') and download.suggested_filename.endswith('.zip')
                    target = Path(folder) / name
                    download.save_as(target)
                    expect(page.locator('#portability-status')).to_contain_text('已开始下载')
                    with ZipFile(target) as archive:
                        assert archive.testzip() is None
                        files = {name: archive.read(name) for name in archive.namelist()}
                    assert set(files) == {'data.json', 'transactions.csv', 'investments.csv', 'README.txt', 'manifest.json'}
                    manifest = json.loads(files['manifest.json'])
                    assert set(manifest['files']) == set(files) - {'manifest.json'}
                    for file, info in manifest['files'].items():
                        assert info['bytes'] == len(files[file]) and info['sha256'] == hashlib.sha256(files[file]).hexdigest()
                    for forbidden in [b'member2_PRIVATE', b'member2_MONTHLY', b'member2_BASELINE', b'member2_ACCOUNT_LABEL',
                                      b'PRIVATE_TOKEN_', b'PRIVATE_CLIENT_ID', b'PRIVATE_SUBJECT_', b'SHOULD_NOT_EXPORT_SYNC', b'scrypt:']:
                        assert forbidden not in b''.join(files.values()), forbidden
                    return json.loads(files['data.json']), files

                personal, files = download_zip('personal.zip')
                assert 'shared' not in personal and personal['coverage']['includesShared'] is False
                assert personal['member']['id'] == 'member1'
                assert personal['personal']['transactions'][0]['title'] == 'member1_PRIVATE'
                assert personal['personal']['transactions'][0]['amountCents'] == 12345
                assert personal['personal']['dashboardLayout'][0]['data']['hidden'] == ['trips']
                assert personal['personal']['financeBaselines'][0]['data']['private'] == 'member1_BASELINE'
                assert personal['personal']['connections'][0]['name'] == 'member1_ACCOUNT_LABEL'
                transaction_csv = list(csv.DictReader(StringIO(files['transactions.csv'].decode('utf-8-sig'))))
                investment_csv = list(csv.DictReader(StringIO(files['investments.csv'].decode('utf-8-sig'))))
                assert transaction_csv[0]['amount'] == '123.45' and transaction_csv[0]['currency'] == 'USD'
                assert investment_csv[0]['cost'] == '123.45' and investment_csv[0]['value'] == ''
                assert personal['personal']['investments'][0]['valueCents'] is None
                checks.append('Personal ZIP download: all five files, manifest bytes/hash valid; owner-only exact JSON; CSV units and unknown valuation correct')

                # Server/network failure keeps the explicit include-shared choice and allows retry.
                page.locator('[name=includeShared]').check()
                page.route('**/api/portability/export', lambda route: route.fulfill(status=503, content_type='application/json', body='{"error":"导出服务暂不可用"}'))
                page.locator('#portability-form [type=submit]').click()
                expect(page.locator('#portability-form .error')).to_have_text('导出服务暂不可用')
                expect(page.locator('[name=includeShared]')).to_be_checked()
                expect(page.locator('#portability-form [type=submit]')).to_be_enabled()
                expect(page.locator('#portability-status')).to_be_empty()
                assert len(downloads) == 1
                page.unroute('**/api/portability/export')
                shared, shared_files = download_zip('shared.zip')
                assert shared['coverage']['includesShared'] is True
                assert shared['shared']['entities']['events'][0]['title'] == 'SHARED_EVENT'
                assert len(shared['shared']['financeBaselines']) == 2
                assert shared['personal'] == personal['personal']
                assert context.request.get(base + '/api/portability/summary').json() == summary
                checks.append('503 retains includeShared selection and triggers no download; retry includes authorized shared records only')

                # Demo and television expose no member export button or background export request.
                nonmember_requests = []
                for path in ['/demo#settings', '/demo?tv=1']:
                    other = browser.new_page(viewport={'width': 1280, 'height': 720})
                    other.on('request', lambda req: nonmember_requests.append(req.url) if '/api/portability/' in req.url else None)
                    other.goto(base + path)
                    if 'tv=1' in path:
                        expect(other.locator('.board>.card')).to_have_count(5)
                    else:
                        expect(other.locator('[data-ps-page=settings]')).to_be_visible()
                    assert other.locator('[data-portability-open]').count() == 0
                    other.close()
                assert not nonmember_requests
                checks.append('Demo and TV have no export entry or portability API request')
                assert not errors, errors
                result = {'passed': True, 'checks': checks, 'downloadCount': len(downloads), 'downloadFiles': downloads,
                          'summary': summary, 'manifestEntries': len(json.loads(shared_files['manifest.json'])['files']),
                          'pageErrors': errors, 'productionWrites': 0}
                (out / 'data-portability-browser-verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                print(json.dumps(result, ensure_ascii=False, indent=2))
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == '__main__':
    main()
