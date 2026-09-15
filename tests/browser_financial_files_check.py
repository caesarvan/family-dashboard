"""Exercise XLSX and GB18030 uploads through the actual browser import form."""
import json
from pathlib import Path
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import create_app
from test_financial_files import workbook
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server, WSGIRequestHandler


class Quiet(WSGIRequestHandler):
    def log(self, *_args, **_kwargs):
        pass


def main():
    output = ROOT / 'test-results'
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        app = create_app({'TESTING': True, 'SECRET_KEY': 'financial-file-browser-only', 'DATA_DIR': temp,
                          'SESSION_COOKIE_SECURE': False, 'MEMBER1_PASSWORD': 'testing-password-one',
                          'MEMBER2_PASSWORD': 'testing-password-two'})
        server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=Quiet)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
                context = browser.new_context(viewport={'width': 390, 'height': 844})
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda err: errors.append(str(err)))
                origin = f'http://127.0.0.1:{server.server_port}'
                page.goto(origin)
                page.locator('[name=password]').fill('testing-password-one')
                page.locator('#login-form button[type=submit]').click()
                page.wait_for_function('() => typeof FinanceHub === "object" && typeof data !== "undefined" && data !== null')
                page.evaluate('FinanceHub.open("import")')
                form = page.locator('#fh-import-form')
                form.locator('[name=source]').select_option('wechat')
                form.locator('[name=file]').set_input_files({'name': '微信合成账单.xlsx', 'mimeType': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'buffer': workbook(second_sheet=True)})
                form.locator('[type=submit]').click()
                expect(page.locator('#dialog')).to_contain_text('尚未解析记录')
                page.locator('#fh-sheet-select').select_option('支付账单')
                expect(page.locator('#dialog')).to_contain_text('合成咖啡')
                expect(page.locator('#dialog')).to_contain_text('OOXML / UTF-8')
                assert context.request.get(origin + '/api/finance-hub/overview').json()['totalRecordCount'] == 0
                page.locator('#fh-sheet-select').select_option('订单')
                expect(page.locator('.fh-table')).to_contain_text('第二工作表')
                expect(page.locator('[data-fh=confirm]')).to_be_enabled()
                page.screenshot(path=str(output / 'finance-xlsx-preview-phone.png'), full_page=True)
                page.locator('[data-fh=confirm]').click()
                expect(page.locator('.fh-ledger')).to_contain_text('第二工作表')
                first = context.request.get(origin + '/api/finance-hub/overview?month=2026-09').json()
                assert first['totalRecordCount'] == 1
                assert first['transactions'][0]['title'] == '第二工作表'
                assert first['transactions'][0]['amountCents'] == 2180
                page.evaluate('FinanceHub.open("import")')
                form = page.locator('#fh-import-form')
                csv = '交易创建时间,商品名称,金额（元）,收支,交易号\n2026-09-14,合成茶饮,18.50,支出,alipay001\n'
                form.locator('[name=file]').set_input_files({'name': '支付宝合成账单.csv', 'mimeType': 'text/csv', 'buffer': csv.encode('gb18030')})
                form.locator('[type=submit]').click()
                expect(page.locator('.fh-table')).to_contain_text('合成茶饮')
                expect(page.locator('#dialog')).to_contain_text('GB18030')
                page.locator('[data-fh=confirm]').click()
                expect(page.locator('.fh-ledger')).to_contain_text('合成茶饮')
                result = context.request.get(origin + '/api/finance-hub/overview?month=2026-09').json()
                assert result['totalRecordCount'] == 2
                assert result['totals'][0]['netSpendCents'] == 4030
                assert page.evaluate('document.querySelector("#dialog").scrollWidth <= document.querySelector("#dialog").clientWidth + 2')
                assert not errors, errors
                report = {'xlsxFileInput': 'passed', 'sheetSelection': 'passed', 'previewNoWrite': 'passed',
                          'confirm': 'passed', 'gb18030AutoDetection': 'passed', 'phoneOverflow': False,
                          'scope': 'synthetic files only', 'pageErrors': errors}
                (output / 'financial-files-browser-verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
                print(json.dumps(report))
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == '__main__':
    main()
