"""Loopback-only amount selection, real Flask/SQLite/Edge, synthetic files."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import create_app
from test_financial_files import workbook
from browser_financial_files_check import Quiet
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server


def main():
    output = ROOT / 'test-results'; output.mkdir(exist_ok=True)
    paths = ['finance_hub.py', 'static/finance-hub.js', 'static/finance-hub.css']
    hashes = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in paths}
    report = {'passed': False, 'checks': [], 'sourceSha256': hashes, 'pageErrors': [], 'externalRequests': [],
              'scope': 'Synthetic CSV/XLSX, temporary real Flask/SQLite/Edge; no provider access or production writes.'}
    def passed(name): report['checks'].append({'name': name, 'passed': True})
    with tempfile.TemporaryDirectory(prefix='amount-column-browser-') as temp:
        app = create_app({'TESTING': True, 'SECRET_KEY': 'synthetic-amount-browser', 'DATA_DIR': temp,
                          'SESSION_COOKIE_SECURE': False, 'MEMBER1_PASSWORD': 'testing-password-one',
                          'MEMBER2_PASSWORD': 'testing-password-two', 'MICROSOFT_CLIENT_ID': '',
                          'GOOGLE_CLIENT_ID': '', 'OPENAI_API_KEY': ''})
        assert app.config['SESSION_REFRESH_EACH_REQUEST'] is False
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
                def login(member='member1', password='testing-password-one'):
                    assert context.request.post(origin + '/api/login', data={'username': member, 'password': password}).status == 200
                    page.goto(origin); expect(page.locator('.ps-welcome')).to_be_visible()
                    page.evaluate('()=>clearInterval(pollTimer)')
                def counts(): return context.request.get(origin + '/api/finance-hub/overview?month=2026-09').json()
                def form_for(source, file):
                    page.evaluate('FinanceHub.open("import")')
                    form = page.locator('#fh-import-form'); expect(form).to_be_visible()
                    form.locator('[name=source]').select_option(source)
                    form.locator('[name=file]').set_input_files(file)
                    form.locator('[type=submit]').click()
                    if file['name'].endswith('.xlsx'):
                        expect(page.locator('#fh-sheet-select')).to_be_visible()
                        page.locator('#fh-sheet-select').select_option('支付账单')
                    expect(page.locator('#fh-amount-form')).to_be_visible()
                def choose(index):
                    page.locator(f'#fh-amount-form [value="{index}"]').check()
                    page.locator('#fh-amount-form [type=submit]').click()
                    expect(page.locator('[data-fh=confirm]')).to_be_enabled()
                def overflow():
                    assert page.locator('#dialog').evaluate('(node)=>node.scrollWidth<=node.clientWidth+1')
                    assert page.locator('.fh-amount-selection').evaluate('(node)=>node.scrollWidth<=node.clientWidth+1')
                login()
                for width, fmt in [(360, 'csv'), (390, 'xlsx')]:
                    page.set_viewport_size({'width': width, 'height': 844})
                    header = ['交易时间', '商品', '订单金额', '实付款', '币种', '收/支', '交易单号'] if fmt == 'csv' else ['交易时间', '商品', '金额', '金额', '币种', '收/支', '交易单号']
                    row = ['2026-09-02', 'SYNTHETIC_' + fmt, '100.00', '80.00', 'CNY', '支出', 'synthetic-' + fmt]
                    raw = (','.join(header) + '\n' + ','.join(row) + '\n').encode() if fmt == 'csv' else workbook(rows=[header, row])
                    file = {'name': 'synthetic.' + fmt, 'mimeType': 'text/csv' if fmt == 'csv' else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'buffer': raw}
                    before = counts()['totalRecordCount']
                    form_for('taobao' if fmt == 'csv' else 'wechat', file)
                    expect(page.locator('[data-fh=confirm]')).to_be_disabled()
                    expect(page.locator('.fh-table tbody tr')).to_have_count(0)
                    assert counts()['totalRecordCount'] == before
                    expect(page.locator('#fh-amount-form')).to_contain_text('C 列')
                    expect(page.locator('#fh-amount-form')).to_contain_text('D 列')
                    overflow(); page.screenshot(path=str(output / f'amount-choice-{width}.png'), full_page=True)
                    passed(f'{fmt}_{width}_ambiguous_choice_blocks_confirmation_and_fits')
                    choose(2)
                    expect(page.locator('.fh-table')).to_contain_text('CNY 100')
                    page.locator('#fh-amount-form [value="3"]').check()
                    expect(page.locator('[data-fh=confirm]')).to_be_disabled()
                    expect(page.locator('#fh-amount-state')).to_contain_text('请重新预览')
                    page.locator('#fh-amount-form [type=submit]').click()
                    expect(page.locator('[data-fh=confirm]')).to_be_enabled()
                    expect(page.locator('.fh-table')).to_contain_text('CNY 80')
                    expect(page.locator('.fh-amount-selection')).to_contain_text('金额来源：D 列')
                    overflow(); page.screenshot(path=str(output / f'amount-preview-{width}.png'), full_page=True)
                    assert counts()['totalRecordCount'] == before
                    passed(f'{fmt}_{width}_changed_choice_requires_fresh_preview')
                    page.locator('[data-fh=confirm]').click()
                    expect(page.locator('.fh-ledger')).to_contain_text('SYNTHETIC_' + fmt)
                    state = counts(); assert state['totalRecordCount'] == before + 1
                    record = next(row for row in state['transactions'] if row['title'] == 'SYNTHETIC_' + fmt)
                    assert record['amountCents'] == 8000 and record['visibility'] == 'private'
                    if fmt == 'csv': assert state['totals'][0]['orderCents'] == 8000 and state['totals'][0]['netSpendCents'] == 0
                    else: assert state['totals'][0]['orderCents'] == state['totals'][0]['netSpendCents'] == 8000
                    passed(f'{fmt}_{width}_confirmed_amount_readback_and_separate_orders')
                    form_for('taobao' if fmt == 'csv' else 'wechat', file); choose(2)
                    expect(page.locator('.fh-table')).to_contain_text('重复')
                    page.locator('[data-fh=confirm]').click(); expect(page.locator('.fh-ledger')).to_be_visible()
                    assert counts()['totalRecordCount'] == before + 1
                    assert next(row for row in counts()['transactions'] if row['title'] == 'SYNTHETIC_' + fmt)['amountCents'] == 8000
                    passed(f'{fmt}_{width}_reimport_other_column_keeps_existing_amount')

                # Delayed preview must not replace a later import form.
                page.evaluate('FinanceHub.open("import")'); form = page.locator('#fh-import-form'); expect(form).to_be_visible()
                form.locator('[name=file]').set_input_files(file)
                held = []
                def hold(route): held.append((route, route.fetch()))
                page.route('**/api/finance-hub/imports/preview', hold)
                form.locator('[type=submit]').click()
                for _ in range(200):
                    if held: break
                    page.wait_for_timeout(20)
                assert len(held) == 1
                page.evaluate('FinanceHub.open("import")'); expect(page.locator('#fh-import-form')).to_be_visible()
                original = page.locator('#fh-import-form').element_handle()
                held[0][0].fulfill(response=held[0][1]); page.unroute('**/api/finance-hub/imports/preview', hold)
                page.wait_for_timeout(200)
                assert original.evaluate('(node)=>node.isConnected')
                expect(page.locator('#fh-amount-form')).to_have_count(0)
                passed('late_preview_does_not_take_over_new_import')

                # Text input invalidates a pending preview before blur/change fires.
                page.evaluate('FinanceHub.open("import")'); form = page.locator('#fh-import-form'); expect(form).to_be_visible()
                form.locator('[name=file]').set_input_files(file)
                held = []; page.route('**/api/finance-hub/imports/preview', hold)
                form.locator('[type=submit]').click()
                for _ in range(200):
                    if held: break
                    page.wait_for_timeout(20)
                assert len(held) == 1
                original = form.element_handle()
                form.locator('[name=sheet]').fill('订单')  # input only, deliberately no blur
                held[0][0].fulfill(response=held[0][1]); page.unroute('**/api/finance-hub/imports/preview', hold)
                page.wait_for_timeout(200)
                assert original.evaluate('(node)=>node.isConnected')
                expect(form.locator('[name=sheet]')).to_have_value('订单')
                expect(page.locator('#fh-amount-form')).to_have_count(0)
                passed('late_preview_does_not_replace_same_form_text_input_before_blur')

                # Actual account change before confirmation is detected and no POST is sent.
                form_for('wechat', file); choose(3)
                sent = []
                page.on('request', lambda request: sent.append(request.url) if request.url.endswith('/imports/confirm') else None)
                assert context.request.post(origin + '/api/login', data={'username': 'member2', 'password': 'testing-password-two'}).status == 200
                page.locator('[data-fh=confirm]').click()
                expect(page.locator('#dialog')).to_contain_text('登录成员或家庭已变化')
                expect(page.locator('.fh-table')).to_have_count(0)
                assert not sent and counts()['totalRecordCount'] == 0
                login('member2', 'testing-password-two'); page.evaluate('FinanceHub.open("ledger")')
                expect(page.locator('.fh-ledger')).to_be_visible(); expect(page.locator('.fh-ledger')).not_to_contain_text('SYNTHETIC_')
                passed('actual_member_change_redacts_preview_prevents_write_and_hides_other_ledger')

                login()
                token = context.request.get(origin + '/api/me').json()['csrf']
                payload = {'source': 'generic', 'kind': 'payments', 'amountColumn': 3,
                           'csv': 'date,title,amount,amount,currency,flow,id\n2026-09-02,SYNTHETIC_GUARD,100,80,CNY,expense,guard\n'}
                preview = context.request.post(origin + '/api/finance-hub/imports/preview', data=payload, headers={'X-CSRF-Token': token}).json()
                invitation = context.request.post(origin + '/api/spaces/invitations', data={}, headers={'X-CSRF-Token': token}).json()['invitation']
                child = browser.new_context(); child.route('**/*', guard)
                created = child.request.post(origin + '/api/spaces/redeem', data={'invitation': invitation, 'name': 'Synthetic amount family', 'slug': 'amount-only', 'MEMBER1_PASSWORD': 'synthetic-child-one', 'MEMBER2_PASSWORD': 'synthetic-child-two'})
                assert created.status == 201
                child.request.get(origin + created.json()['entry'])
                assert child.request.post(origin + '/api/login', data={'username': 'member1', 'password': 'synthetic-child-one'}).status == 200
                child_token = child.request.get(origin + '/api/me').json()['csrf']
                assert child.request.post(origin + '/api/finance-hub/imports/confirm', data={**payload, 'previewToken': preview['previewToken']}, headers={'X-CSRF-Token': child_token}).status == 400
                child_page = child.new_page(); child_page.on('pageerror', lambda error: report['pageErrors'].append(str(error)))
                child_page.goto(origin); expect(child_page.locator('.ps-welcome')).to_be_visible(); child_page.evaluate('FinanceHub.open("ledger")')
                expect(child_page.locator('.fh-ledger')).to_be_visible(); expect(child_page.locator('.fh-ledger')).not_to_contain_text('SYNTHETIC_')
                passed('actual_other_household_rejects_preview_token_and_shows_empty_ledger')

                tv = browser.new_context(); tv.route('**/*', guard)
                pair = tv.request.post(origin + '/api/pair/start', data={}).json()
                assert context.request.post(origin + '/api/pair/approve', data={'code': pair['code'], 'name': 'Synthetic TV', 'focus': 'member1'}, headers={'X-CSRF-Token': token}).status == 200
                assert tv.request.post(origin + '/api/pair/poll', data={'secret': pair['secret']}).json()['approved']
                television = tv.new_page(); television.on('pageerror', lambda error: report['pageErrors'].append(str(error)))
                television.goto(origin + '/tv'); expect(television.locator('.board')).to_be_visible()
                television.evaluate('FinanceHub.open("import")'); expect(television.locator('#fh-import-form')).to_have_count(0)
                assert tv.request.post(origin + '/api/finance-hub/imports/preview', data=payload).status == 403
                assert tv.request.post(origin + '/api/finance-hub/imports/confirm', data={**payload, 'previewToken': preview['previewToken']}).status == 403
                passed('paired_tv_has_no_import_ui_and_both_apis_forbidden')
                assert not report['externalRequests'] and not report['pageErrors']
                browser.close()
            report['passed'] = True
        except BaseException as error:
            report['failureType'] = type(error).__name__
            raise
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)
            report['sourceUnchanged'] = hashes == {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in paths}
            (output / 'finance-amount-columns-browser-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(report, ensure_ascii=False))
    assert report['sourceUnchanged']


if __name__ == '__main__': main()
