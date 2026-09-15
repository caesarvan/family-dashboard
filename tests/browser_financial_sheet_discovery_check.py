"""Real loopback Flask/SQLite/Edge sheet discovery and protected retry flow."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import create_app
from test_financial_files import NS, REL, DR, workbook, sheet_xml
from browser_financial_files_check import Quiet
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server


def mixed_workbook():
    names = ['说明页', '支付账单', '订单', '公式说明']
    parts = {
        'xl/workbook.xml': f'<workbook xmlns="{NS}" xmlns:r="{DR}"><sheets>' + ''.join(
            f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>' for i, name in enumerate(names, 1)) + '</sheets></workbook>',
        'xl/_rels/workbook.xml.rels': f'<Relationships xmlns="{REL}">' + ''.join(
            f'<Relationship Id="rId{i}" Target="worksheets/sheet{i}.xml" Type="{DR}/worksheet"/>' for i in range(1, 5)) + '</Relationships>',
        'xl/worksheets/sheet1.xml': sheet_xml([['SYNTHETIC_COVER_NO_RECORDS']]),
        'xl/worksheets/sheet2.xml': sheet_xml([['date', 'title', 'amount', '实付款', 'currency', 'flow', 'id'],
                                             ['2026-09-02', 'SYNTHETIC_PAYMENT', '60', '40', 'CNY', 'expense', 'synthetic-payment']]),
        'xl/worksheets/sheet3.xml': sheet_xml([['amount', 'date', 'title', 'currency', 'flow', 'id'],
                                             ['15', '2026-09-02', 'SYNTHETIC_OTHER_SHEET', 'CNY', 'expense', 'synthetic-other']]),
        'xl/worksheets/sheet4.xml': f'<worksheet xmlns="{NS}"><sheetData><row r="1"><c r="A1"><f>1+1</f><v>2</v></c></row></sheetData></worksheet>'}
    return workbook(extra_parts=parts)


def main():
    output = ROOT / 'test-results'; output.mkdir(exist_ok=True)
    paths = ['finance_hub.py', 'financial_files.py', 'static/finance-hub.js', 'static/finance-hub.css']
    hashes = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}
    report = {'passed': False, 'checks': [], 'pageErrors': [], 'externalRequests': [], 'sourceSha256': hashes,
              'scope': 'Synthetic XLSX only, temporary real Flask/SQLite/Edge; no external provider calls or production writes.'}
    def passed(name): report['checks'].append({'name': name, 'passed': True})
    with tempfile.TemporaryDirectory(prefix='xlsx-discovery-browser-') as temp:
        app = create_app({'TESTING': True, 'DATA_DIR': temp, 'SECRET_KEY': 'synthetic-sheet-browser',
                          'SESSION_COOKIE_SECURE': False, 'MEMBER1_PASSWORD': 'testing-password-one',
                          'MEMBER2_PASSWORD': 'testing-password-two', 'MICROSOFT_CLIENT_ID': '', 'GOOGLE_CLIENT_ID': '', 'OPENAI_API_KEY': ''})
        server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=Quiet)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        origin = 'http://127.0.0.1:' + str(server.server_port)
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
                context = browser.new_context(viewport={'width': 360, 'height': 844})
                def guard(route):
                    if route.request.url.startswith(origin + '/'): route.continue_()
                    else: report['externalRequests'].append(route.request.url); route.abort()
                context.route('**/*', guard)
                page = context.new_page(); page.on('pageerror', lambda error: report['pageErrors'].append(str(error)))
                def login():
                    assert context.request.post(origin + '/api/login', data={'username': 'member1', 'password': 'testing-password-one'}).status == 200
                    page.goto(origin); expect(page.locator('.ps-welcome')).to_be_visible(); page.evaluate('()=>clearInterval(pollTimer)')
                def count(): return context.request.get(origin + '/api/finance-hub/overview?month=2026-09').json()['totalRecordCount']
                file = {'name': 'synthetic-sheets.xlsx', 'mimeType': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'buffer': mixed_workbook()}
                def upload():
                    page.evaluate('FinanceHub.open("import")'); form = page.locator('#fh-import-form'); expect(form).to_be_visible()
                    form.locator('[name=file]').set_input_files(file); form.locator('[type=submit]').click()
                    expect(page.locator('#fh-sheet-select')).to_be_visible()
                def wait_held(held):
                    for _ in range(200):
                        if held: return
                        page.wait_for_timeout(20)
                    raise AssertionError('Expected held request not reached')
                login()
                for width in [360, 390]:
                    page.set_viewport_size({'width': width, 'height': 844}); upload()
                    expect(page.locator('#dialog-title')).to_have_text('选择账单工作表')
                    expect(page.locator('#dialog')).to_contain_text('尚未解析记录')
                    expect(page.locator('#fh-sheet-select option')).to_have_count(5)
                    expect(page.locator('[data-fh=confirm]')).to_be_disabled()
                    assert count() == 0
                    assert page.locator('#dialog').evaluate('(node)=>node.scrollWidth<=node.clientWidth+1')
                    assert page.locator('.fh-sheet-selection').evaluate('(node)=>node.scrollWidth<=node.clientWidth+1')
                    page.screenshot(path=str(output / f'xlsx-sheet-choice-{width}.png'), full_page=True)
                    passed(f'{width}_cover_workbook_lists_sheets_without_record_validation_or_overflow')
                    page.locator('#fh-sheet-select').select_option('说明页')
                    expect(page.locator('#fh-confirm-error')).to_contain_text('未识别日期与金额列')
                    expect(page.locator('#fh-sheet-select')).to_be_enabled()
                    expect(page.locator('#fh-sheet-retry')).to_be_enabled()
                    page.locator('#fh-sheet-select').select_option('公式说明')
                    expect(page.locator('#fh-confirm-error')).to_contain_text('包含公式')
                    expect(page.locator('[data-fh=confirm]')).to_be_disabled()
                    page.locator('#fh-sheet-select').select_option('支付账单')
                    expect(page.locator('#fh-amount-form')).to_be_visible()
                    page.locator('#fh-amount-form [value="3"]').check(); page.locator('#fh-amount-form [type=submit]').click()
                    expect(page.locator('.fh-table')).to_contain_text('CNY 40')
                    expect(page.locator('[data-fh=confirm]')).to_be_enabled()
                    assert count() == 0
                    passed(f'{width}_bad_cover_and_formula_keep_list_then_amount_preview_succeeds')

                # A new sheet has different amount positions; old selection/token/rows vanish immediately.
                held = []
                def hold_other(route):
                    if route.request.post_data_json.get('file', {}).get('sheet') == '订单': held.append((route, route.fetch()))
                    else: route.continue_()
                page.route('**/api/finance-hub/imports/preview', hold_other)
                page.locator('#fh-sheet-select').select_option('订单'); wait_held(held)
                expect(page.locator('#fh-amount-form')).to_have_count(0)
                expect(page.locator('.fh-table tbody tr')).to_have_count(0)
                expect(page.locator('[data-fh=confirm]')).to_be_disabled()
                sent = held[0][0].request.post_data_json
                assert 'amountColumn' not in sent and 'inspectSheets' not in sent and sent['previewToken'] is None
                held[0][0].fulfill(response=held[0][1]); page.unroute('**/api/finance-hub/imports/preview', hold_other)
                expect(page.locator('.fh-table')).to_contain_text('CNY 15')
                expect(page.locator('#dialog')).to_contain_text('金额来源：A 列')
                passed('sheet_change_clears_amount_token_and_rows_before_new_preview')

                # Late success/failure for a previous sheet cannot replace a newer preview.
                for outcome in ['success', 'failure']:
                    held = []
                    def hold_payment(route):
                        if route.request.post_data_json.get('file', {}).get('sheet') == '支付账单': held.append((route, route.fetch()))
                        else: route.continue_()
                    page.route('**/api/finance-hub/imports/preview', hold_payment)
                    page.locator('#fh-sheet-select').select_option('支付账单'); wait_held(held)
                    page.locator('#fh-sheet-select').select_option('订单'); expect(page.locator('.fh-table')).to_contain_text('CNY 15')
                    original = page.locator('#fh-import-preview').element_handle()
                    if outcome == 'success': held[0][0].fulfill(response=held[0][1])
                    else: held[0][0].fulfill(status=503, json={'error': 'SYNTHETIC_STALE_SHEET_ERROR'})
                    page.unroute('**/api/finance-hub/imports/preview', hold_payment); page.wait_for_timeout(150)
                    assert original.evaluate('(node)=>node.isConnected')
                    expect(page.locator('#fh-sheet-select')).to_have_value('订单')
                    expect(page.locator('#fh-confirm-error')).to_have_text('')
                    expect(page.locator('#fh-amount-form')).to_have_count(0)
                    passed(f'late_old_sheet_{outcome}_cannot_replace_current_preview')

                # A transient selected-sheet failure remains retryable on the same sheet.
                attempts = []
                def fail_once(route):
                    attempts.append(1)
                    if len(attempts) == 1: route.fulfill(status=503, json={'error': 'SYNTHETIC_TRY_AGAIN'})
                    else: route.continue_()
                page.route('**/api/finance-hub/imports/preview', fail_once)
                page.locator('#fh-sheet-retry').click(); expect(page.locator('#fh-confirm-error')).to_contain_text('SYNTHETIC_TRY_AGAIN')
                page.locator('#fh-sheet-retry').click(); expect(page.locator('.fh-table')).to_contain_text('CNY 15')
                page.unroute('**/api/finance-hub/imports/preview', fail_once)
                assert len(attempts) == 2
                passed('same_sheet_retry_after_transient_failure_is_actionable')
                page.locator('[data-fh=confirm]').click(); expect(page.locator('.fh-ledger')).to_contain_text('SYNTHETIC_OTHER_SHEET')
                assert count() == 1
                state = context.request.get(origin + '/api/finance-hub/overview?month=2026-09').json()
                assert state['transactions'][0]['amountCents'] == 1500
                assert state['transactions'][0]['visibility'] == 'private'
                passed('explicit_confirmation_writes_only_selected_sheet_and_readback_matches')

                # Hold discovery, edit the same form without blur, then release: input survives.
                page.evaluate('FinanceHub.open("import")'); form = page.locator('#fh-import-form'); expect(form).to_be_visible()
                form.locator('[name=file]').set_input_files(file); held = []
                def hold_discovery(route): held.append((route, route.fetch()))
                page.route('**/api/finance-hub/imports/preview', hold_discovery)
                form.locator('[type=submit]').click(); wait_held(held)
                original = form.element_handle(); form.locator('[name=sheet]').fill('订单')
                held[0][0].fulfill(response=held[0][1]); page.unroute('**/api/finance-hub/imports/preview', hold_discovery); page.wait_for_timeout(150)
                assert original.evaluate('(node)=>node.isConnected')
                expect(form.locator('[name=sheet]')).to_have_value('订单')
                expect(page.locator('#fh-sheet-select')).to_have_count(0)
                passed('late_discovery_preserves_same_form_input_before_blur')

                # A real member switch drops sheet names/result and never confirms.
                upload(); held = []; page.route('**/api/finance-hub/imports/preview', hold_discovery)
                page.locator('#fh-sheet-select').select_option('订单'); wait_held(held)
                assert context.request.post(origin + '/api/login', data={'username': 'member2', 'password': 'testing-password-two'}).status == 200
                held[0][0].fulfill(response=held[0][1]); page.unroute('**/api/finance-hub/imports/preview', hold_discovery)
                expect(page.locator('#dialog')).to_contain_text('登录成员或家庭已变化')
                expect(page.locator('#fh-sheet-select')).to_have_count(0); expect(page.locator('.fh-table')).to_have_count(0)
                assert count() == 0
                passed('real_member_change_redacts_sheet_result_and_keeps_partner_ledger_empty')
                assert not report['pageErrors'] and not report['externalRequests']
                browser.close()
            report['passed'] = True
        except BaseException as error:
            report['failureType'] = type(error).__name__
            raise
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)
            report['sourceUnchanged'] = hashes == {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}
            (output / 'financial-sheet-discovery-browser-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(report, ensure_ascii=False))
    assert report['sourceUnchanged']


if __name__ == '__main__': main()
