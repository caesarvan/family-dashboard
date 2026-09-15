"""Synthetic investment files through real temporary Flask, SQLite and Edge."""
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import create_app
from browser_financial_files_check import Quiet
from test_financial_files import workbook, sheet_xml
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server

HEADERS = ['holdingKey', 'name', 'institution', 'assetType', 'currency', 'quantity', 'cost', 'value', 'asOf', 'note', 'recordId']


def file_rows(value='120', day='2026-09-12', name='synthetic-investments.csv'):
    text = io.StringIO(newline='')
    writer = csv.writer(text)
    writer.writerow(HEADERS)
    writer.writerow(['cny-fund', 'SYNTHETIC_CNY_FUND', '测试银行', '基金', 'CNY', '2', '100', value, day, '虚构测试', ''])
    writer.writerow(['usd-deposit', 'SYNTHETIC_USD_DEPOSIT', '测试海外机构', '存款', 'USD', '', '200', '', '2026-09-12', '', ''])
    return {'name': name, 'mimeType': 'text/csv', 'buffer': text.getvalue().encode('utf-8')}


def main():
    out = ROOT / 'test-results'; out.mkdir(exist_ok=True)
    paths = ['app.py', 'finance_hub.py', 'investment_import.py', 'static/investment-import.js',
             'static/investment-import.css', 'static/finance-hub.js', 'static/index.html',
             'tests/browser_investment_import_check.py']
    hashes = {n: hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in paths}
    report = {'passed': False, 'checks': [], 'externalRequests': [], 'pageErrors': [],
              'sourceHashes': hashes, 'productionWrites': 0, 'realCloudWrites': 0, 'realFinancialInputs': 0,
              'scope': 'Synthetic holdings, real loopback Flask/SQLite/Edge; no bank, model or production access'}
    def passed(name): report['checks'].append(name)
    with tempfile.TemporaryDirectory(prefix='investment-import-ui-') as temp:
        app = create_app({'TESTING': True, 'DATA_DIR': temp, 'SECRET_KEY': 'synthetic-investment-browser',
            'SESSION_COOKIE_SECURE': False, 'MEMBER1_PASSWORD': 'testing-password-one',
            'MEMBER2_PASSWORD': 'testing-password-two', 'MICROSOFT_CLIENT_ID': '', 'GOOGLE_CLIENT_ID': '', 'OPENAI_API_KEY': ''})
        server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=Quiet)
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        origin = 'http://127.0.0.1:' + str(server.server_port)
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
                context = browser.new_context(viewport={'width': 360, 'height': 844}, accept_downloads=True)
                def guard(route):
                    if route.request.url.startswith(origin+'/'): route.continue_()
                    else: report['externalRequests'].append(route.request.url); route.abort()
                context.route('**/*', guard)
                page = context.new_page(); page.on('pageerror', lambda error: report['pageErrors'].append(str(error)))
                def login(member='member1'):
                    password='testing-password-one' if member=='member1' else 'testing-password-two'
                    assert context.request.post(origin+'/api/login', data={'username':member,'password':password}).status==200
                    page.goto(origin); expect(page.locator('.ps-welcome')).to_be_visible()
                    page.evaluate('()=>clearInterval(pollTimer)')
                def holdings():
                    response=context.request.get(origin+'/api/finance-hub/overview?month=2026-09')
                    assert response.status==200
                    return response.json()['investments']
                def upload(file=None):
                    page.evaluate('InvestmentImport.open()')
                    form=page.locator('#investment-import-form');expect(form).to_be_visible()
                    form.locator('[name=sourceName]').fill('测试投资来源')
                    form.locator('[name=file]').set_input_files(file or file_rows())
                    form.locator('[type=submit]').click()
                    expect(page.locator('.ii-review-list')).to_be_visible()
                    assert page.locator('.investment-import').evaluate("n=>n.closest('.dialog-content').scrollTop===0")
                    assert page.locator('#dialog').evaluate('n=>n.scrollTop===0')
                    assert page.locator('.ii-intro').bounding_box()['y'] >= page.locator('.dialog-header').bounding_box()['y']
                def confirm():
                    page.locator('[name=ack]').check();page.locator('[data-ii=confirm]').click()
                    expect(page.locator('.ii-success')).to_be_visible()
                def wait_held(held):
                    for _ in range(250):
                        if held:return
                        page.wait_for_timeout(20)
                    raise AssertionError('Expected pending HTTP request was not observed')

                login()
                page.evaluate('FinanceHub.open("investments")')
                expect(page.locator('[data-investment-import-open]')).to_be_visible()
                page.locator('[data-investment-import-open]').click()
                expect(page.locator('#investment-import-form')).to_be_visible()
                with page.expect_download() as download:
                    page.locator('[data-ii=sample]').click()
                assert download.value.suggested_filename.endswith('.csv') and not holdings()
                passed('investment_entry_and_sample_download_do_not_create_holdings')

                upload()
                expect(page.locator('.ii-row')).to_have_count(2)
                expect(page.locator('[data-ii=confirm]')).to_be_disabled()
                assert holdings()==[]
                expect(page.locator('.ii-review-list')).to_contain_text('待估值')
                passed('csv_preview_shows_two_currencies_unknown_value_and_requires_confirmation')
                for width,theme in [(360,'forest'),(360,'ocean'),(1440,'light')]:
                    page.set_viewport_size({'width':width,'height':900 if width>500 else 844})
                    page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                    assert page.locator('#dialog').evaluate('(n)=>n.scrollWidth<=n.clientWidth+1')
                    assert page.locator('.investment-import').evaluate('(n)=>n.scrollWidth<=n.clientWidth+1')
                    assert page.locator('[data-ii=confirm]').bounding_box()['height']>=44
                    page.screenshot(path=str(out/f'investment-import-{theme}-{width}.png'),full_page=False)
                passed('phone_desktop_three_themes_readable_without_horizontal_overflow')
                confirm(); first=holdings()
                assert len(first)==2
                keyed={row['name']:row for row in first}
                assert keyed['SYNTHETIC_CNY_FUND']['valueCents']==12000
                assert keyed['SYNTHETIC_USD_DEPOSIT']['valueCents'] is None
                ids={r['id'] for r in first}
                passed('confirmed_holdings_read_back_private_with_no_cross_currency_conversion')
                upload();confirm();assert {r['id'] for r in holdings()}==ids
                passed('repeat_file_confirmation_does_not_duplicate_holdings')
                upload(file_rows('130','2026-09-13'))
                expect(page.locator('.ii-review-list')).to_contain_text('120.00')
                expect(page.locator('.ii-review-list')).to_contain_text('130.00')
                confirm();updated=holdings()
                assert {r['id'] for r in updated}==ids
                assert next(r for r in updated if r['name']=='SYNTHETIC_CNY_FUND')['valueCents']==13000
                passed('stable_holding_key_updates_original_id_with_before_after_values')
                for value,day,label in [('', '2026-09-14','missing_known_valuation'),('140','2026-09-01','older_statement')]:
                    upload(file_rows(value,day));expect(page.locator('[data-ii=confirm]')).to_be_disabled()
                    assert any(t.strip() for t in page.locator('.ii-view .error').all_text_contents())
                    assert holdings()==updated
                    passed(label+'_blocks_batch_without_changing_holdings')

                # Workbook names are selected before trying to parse a cover sheet.
                rows=[HEADERS,['xlsx-key','SYNTHETIC_XLSX','测试机构','基金','CNY','','50','55','2026-09-14','','']]
                xlsx=workbook(extra_parts={'xl/worksheets/sheet1.xml':sheet_xml(rows)})
                page.evaluate('InvestmentImport.open()');form=page.locator('#investment-import-form');expect(form).to_be_visible()
                form.locator('[name=sourceName]').fill('工作表来源')
                form.locator('[name=file]').set_input_files({'name':'synthetic-holdings.xlsx','mimeType':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','buffer':xlsx})
                form.locator('[type=submit]').click();expect(page.locator('#investment-sheet-form')).to_be_visible()
                select=page.locator('#investment-sheet-form [name=sheet]')
                values=select.locator('option').evaluate_all('(nodes)=>nodes.map(n=>n.value).filter(Boolean)')
                assert values and holdings()==updated
                select.select_option(values[0]);page.locator('#investment-sheet-form [type=submit]').click()
                expect(page.locator('.ii-review-list')).to_contain_text('SYNTHETIC_XLSX')
                passed('xlsx_explicit_sheet_selection_before_investment_preview')

                # Re-preview invalidates prior approval immediately; a 503 keeps retry actionable.
                attempts=[]
                def fail_preview(route):
                    attempts.append(1)
                    if len(attempts)==1:route.fulfill(status=503,json={'error':'SYNTHETIC_PREVIEW_RETRY'})
                    else:route.continue_()
                page.route('**/api/finance-hub/investments/imports/preview',fail_preview)
                page.locator('[name=ack]').check();page.locator('[data-ii=preview]').click()
                expect(page.locator('.ii-message')).to_contain_text('SYNTHETIC_PREVIEW_RETRY')
                expect(page.locator('[data-ii=confirm]')).to_be_disabled()
                page.locator('[data-ii=preview]').click();expect(page.locator('[name=ack]')).to_be_enabled()
                expect(page.locator('[data-ii=confirm]')).to_be_disabled()
                page.unroute('**/api/finance-hub/investments/imports/preview',fail_preview)
                passed('failed_repreview_disables_old_confirmation_and_can_retry_same_file')

                # Save really succeeds but its response is lost; same token retry must replay.
                attempts=[]
                def lose_confirmation(route):
                    attempts.append(1)
                    if len(attempts)==1:
                        actual=route.fetch();assert actual.status==200
                        route.fulfill(status=503,json={'error':'SYNTHETIC_RESPONSE_LOST'})
                    else:route.continue_()
                page.route('**/api/finance-hub/investments/imports/confirm',lose_confirmation)
                page.locator('[name=ack]').check();page.locator('[data-ii=confirm]').click()
                expect(page.locator('.ii-message')).to_contain_text('SYNTHETIC_RESPONSE_LOST')
                assert len(holdings())==3
                expect(page.locator('[data-ii=confirm]')).to_be_enabled();page.locator('[data-ii=confirm]').click()
                expect(page.locator('.ii-success')).to_contain_text('已经保存')
                assert len(holdings())==3
                page.unroute('**/api/finance-hub/investments/imports/confirm',lose_confirmation)
                passed('lost_success_response_same_confirmation_replays_without_duplicate')

                # Export current records provides explicit IDs, allowing manual records to join a source.
                me=context.request.get(origin+'/api/me').json()
                manual=context.request.post(origin+'/api/finance-hub/investments',headers={'X-CSRF-Token':me['csrf']},data={
                    'name':'SYNTHETIC_MANUAL','institution':'测试手工机构','assetType':'基金','currency':'CNY',
                    'quantity':'1','cost':'20','value':'25','asOf':'2026-09-14','note':''})
                assert manual.status==201
                page.evaluate('InvestmentImport.open()');form=page.locator('#investment-import-form');expect(form).to_be_visible()
                form.locator('[name=sourceName]').fill('测试投资来源')
                with page.expect_download() as downloaded:page.locator('[data-ii=export]').click()
                exported=Path(downloaded.value.path()).read_bytes()
                assert manual.json()['id'].encode() in exported and b'holdingKey' in exported
                form.locator('[name=file]').set_input_files({'name':'exported-holdings.csv','mimeType':'text/csv','buffer':exported})
                form.locator('[type=submit]').click();expect(page.locator('.ii-review-list')).to_contain_text('SYNTHETIC_MANUAL')
                confirm();assert len(holdings())==4
                passed('export_existing_manual_holdings_then_explicit_id_link_no_duplicate')

                # A response belonging to an old form cannot replace a new draft.
                held=[]
                def hold(route):held.append((route,route.fetch()))
                page.evaluate('InvestmentImport.open()');form=page.locator('#investment-import-form');expect(form).to_be_visible()
                form.locator('[name=sourceName]').fill('测试投资来源');form.locator('[name=file]').set_input_files(file_rows('150','2026-09-15'))
                page.route('**/api/finance-hub/investments/imports/preview',hold)
                form.locator('[type=submit]').click();wait_held(held)
                page.evaluate('InvestmentImport.open()');newform=page.locator('#investment-import-form');expect(newform).to_be_visible()
                newform.locator('[name=sourceName]').fill('SYNTHETIC_NEW_DRAFT')
                old=newform.element_handle();held[0][0].fulfill(response=held[0][1]);page.unroute('**/api/finance-hub/investments/imports/preview',hold)
                page.wait_for_timeout(150)
                assert old.evaluate('(n)=>n.isConnected')
                expect(newform.locator('[name=sourceName]')).to_have_value('SYNTHETIC_NEW_DRAFT')
                passed('late_old_preview_cannot_replace_new_file_draft')

                # Cookie-only actor changes are checked with the actual /me response.
                held=[];page.route('**/api/finance-hub/investments/imports/preview',hold)
                newform.locator('[name=sourceName]').fill('测试投资来源');newform.locator('[name=file]').set_input_files(file_rows('151','2026-09-15'))
                newform.locator('[type=submit]').click();wait_held(held)
                assert context.request.post(origin+'/api/login',data={'username':'member2','password':'testing-password-two'}).status==200
                held[0][0].fulfill(response=held[0][1]);page.unroute('**/api/finance-hub/investments/imports/preview',hold)
                expect(page.locator('.investment-import')).to_contain_text('重新核对登录状态')
                expect(page.locator('.ii-review-list')).to_have_count(0);assert holdings()==[]
                passed('actual_member_switch_redacts_late_preview_and_preserves_partner_isolation')
                for path in ['/demo','/demo?tv=1','/tv']:
                    page.goto(origin+path);page.wait_for_timeout(150)
                    assert page.locator('[data-investment-import-open]').count()==0
                    page.evaluate('InvestmentImport.open()');assert page.locator('.investment-import').count()==0
                passed('demo_and_television_do_not_offer_private_investment_import')
                assert not report['externalRequests'] and not report['pageErrors']
                browser.close()
            report['passed']=True
        except BaseException as error:
            report['failureType']=type(error).__name__
            raise
        finally:
            server.shutdown();server.server_close();worker.join(timeout=5)
            report['sourceUnchanged']=hashes=={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in paths}
            if not report['sourceUnchanged']:
                report['passed']=False
                report['failureType']='SourceDrift'
            (out/'investment-import-browser-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(report,ensure_ascii=False))
    assert report['sourceUnchanged']


if __name__=='__main__':main()
