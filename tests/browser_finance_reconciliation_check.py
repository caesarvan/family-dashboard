"""Synthetic import -> real reconciliation UI -> derived totals -> revoke; no production."""
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import create_app, TZ
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server, WSGIRequestHandler


class Quiet(WSGIRequestHandler):
    def log(self, *_args, **_kwargs):
        pass


def main():
    out = ROOT / 'test-results'
    out.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='family-reconciliation-browser-') as folder:
        app = create_app({'TESTING': True, 'SECRET_KEY': 'reconciliation-local-browser-key', 'DATA_DIR': folder,
                          'SESSION_COOKIE_SECURE': False, 'MEMBER1_PASSWORD': 'testing-password-one',
                          'MEMBER2_PASSWORD': 'testing-password-two'})
        server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=Quiet)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        day = datetime.now(TZ).date().isoformat()
        month = day[:7]
        errors, checks, receipts = [], [], []
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
                context = browser.new_context(viewport={'width': 1440, 'height': 1000})
                assert context.request.post(base + '/api/login', data={'username': 'member1', 'password': 'testing-password-one'}).status == 200
                headers = {'X-CSRF-Token': context.request.get(base + '/api/me').json()['csrf']}

                def overview():
                    response = context.request.get(base + '/api/finance-hub/overview?month=' + month)
                    assert response.status == 200
                    return response.json()

                # Exercise public import contracts; no direct insertion bypasses validation.
                for title, amount, flow, category, kind, source in [
                    ('SYNTHETIC_ORDER_100', '100', 'expense', '购物', 'orders', 'taobao'),
                    ('SYNTHETIC_PAYMENT_100', '100', 'expense', '购物', 'payments', 'generic'),
                    ('SYNTHETIC_DUPLICATE_100', '100', 'expense', '购物', 'payments', 'alipay'),
                    ('SYNTHETIC_REFUND_30', '30', 'refund', '退款待核对', 'payments', 'generic'),
                ]:
                    payload = {'source': source, 'kind': kind, 'csv': 'date,title,amount,currency,flow,category,id,status\n' +
                               f'{day},{title},{amount},CNY,{flow},{category},{title},成功\n'}
                    preview = context.request.post(base + '/api/finance-hub/imports/preview', headers=headers, data=payload)
                    assert preview.status == 200, preview.text()
                    imported = context.request.post(base + '/api/finance-hub/imports/confirm', headers=headers,
                                                    data={**payload, 'previewToken': preview.json()['previewToken']})
                    assert imported.status == 200, imported.text()
                initial = overview()
                assert initial['transactionCount'] == 4 and initial['totals'][0]['netSpendCents'] == 17000
                records = {row['title']: row for row in initial['transactions']}
                assert context.request.put(base + '/api/finance-hub/budgets', headers=headers,
                                           data={'month': month, 'currency': 'CNY', 'category': '购物', 'amount': '100', 'revision': 0}).status == 200
                with closing(sqlite3.connect(Path(folder) / 'household.sqlite3')) as con:
                    original_raw = dict(con.execute('SELECT id,data FROM hub_transactions'))

                page = context.new_page()
                page.on('pageerror', lambda err: errors.append(str(err)))
                page.goto(base)
                expect(page.locator('.ps-welcome')).to_be_visible()
                page.evaluate('ProductShell.navigate("finance")')
                page.locator('[data-ps-module=FinanceHub][data-ps-id=ledger]').click()
                expect(page.locator('.fh-transaction')).to_have_count(4)

                def open_record(title):
                    page.evaluate('FinanceHub.open("ledger")')
                    expect(page.locator('.fh-transaction')).to_have_count(4)
                    page.locator('.fh-transaction').filter(has_text=title).locator('[data-fh=transaction]').click()
                    expect(page.locator('#fh-editor')).to_be_visible()
                    page.locator('[data-fh=reconcile]').click()
                    expect(page.locator('#fh-match-search')).to_be_visible()

                for kind, focus_title, label, amount in [
                    ('duplicate', 'SYNTHETIC_DUPLICATE_100', '确认重复记录', '100'),
                    ('order_payment', 'SYNTHETIC_ORDER_100', '订单关联付款', '100'),
                    ('refund_payment', 'SYNTHETIC_REFUND_30', '退款关联原付款', '30'),
                ]:
                    open_record(focus_title)
                    candidates = page.locator('.fh-match').filter(has_text=label).filter(has_text='SYNTHETIC_PAYMENT_100')
                    expect(candidates).to_have_count(1)
                    if kind == 'duplicate':
                        for width, height in [(360, 800), (390, 844), (1440, 1000)]:
                            page.set_viewport_size({'width': width, 'height': height})
                            assert page.evaluate('document.querySelector("#dialog").scrollWidth<=document.querySelector("#dialog").clientWidth+1')
                            if width == 390:
                                page.screenshot(path=str(out / 'finance-reconciliation-candidates-phone.png'), full_page=True)
                    before = overview()['totals'][0]['netSpendCents']
                    candidates.locator('[data-fh=choose-reconciliation]').click()
                    expect(page.locator('#fh-reconciliation-form')).to_be_visible()
                    if kind == 'duplicate':
                        expect(page.locator('[name=amount]')).to_have_attribute('readonly', '')
                    else:
                        page.locator('[name=amount]').fill(amount)
                    with page.expect_response(lambda response: response.url.endswith('/api/finance-hub/reconciliation/preview')) as preview_response:
                        page.locator('#fh-reconciliation-form [type=submit]').click()
                    planned = preview_response.value.json()
                    expect(page.locator('[data-fh=confirm-reconciliation]')).to_be_visible()
                    assert planned['kind'] == kind and planned['amountCents'] == int(amount) * 100
                    assert overview()['totals'][0]['netSpendCents'] == before
                    if kind == 'refund_payment':
                        page.set_viewport_size({'width': 390, 'height': 844})
                        page.screenshot(path=str(out / 'finance-reconciliation-refund-preview-phone.png'), full_page=True)
                    with page.expect_response(lambda response: response.url.endswith('/api/finance-hub/reconciliation/confirm')) as confirmed_response:
                        page.locator('[data-fh=confirm-reconciliation]').click()
                    receipt = confirmed_response.value.json()
                    receipts.append(receipt['relation'])
                    expect(page.locator('[data-fh=revoke-reconciliation]')).to_have_count(1)
                    replayed = context.request.post(base + '/api/finance-hub/reconciliation/confirm', headers=headers,
                                                   data={'previewToken': planned['previewToken']})
                    assert replayed.status == 200 and replayed.json()['replayed'] is True
                    checks.append(kind + ': actual UI candidate -> amount -> preview(no write) -> confirm -> idempotent replay')

                linked = overview()
                assert linked['transactionCount'] == 4
                assert linked['totals'][0]['netSpendCents'] == 7000
                assert linked['totals'][0]['orderCents'] == 10000
                assert linked['totals'][0]['duplicateCount'] == 1
                assert linked['totals'][0]['categories']['购物'] == 7000
                assert linked['budgets'][0]['spentCents'] == 7000 and linked['budgets'][0]['remainingCents'] == 3000
                pay = next(row for row in linked['transactions'] if row['title'] == 'SYNTHETIC_PAYMENT_100')
                assert pay['reconciliation']['refundedCents'] == 3000 and pay['reconciliation']['remainingAfterRefundCents'] == 7000
                page.evaluate('FinanceHub.open("overview")')
                expect(page.locator('.fh-currency .fh-metrics > div').first).to_contain_text('CNY 70')
                expect(page.locator('.fh-budget')).to_contain_text('剩余 CNY 30')
                page.screenshot(path=str(out / 'finance-reconciliation-net70-phone.png'), full_page=True)
                checks.append('Confirmed links yield CNY70 net spend, order100 separate, budget remaining30, payment refund30')

                # Revoke from the real UI with the browser's explicit confirmation.
                open_record('SYNTHETIC_DUPLICATE_100')
                page.once('dialog', lambda dialog: dialog.accept())
                page.locator('[data-fh=revoke-reconciliation]').click()
                expect(page.locator('[data-fh=revoke-reconciliation]')).to_have_count(0)
                expect(page.locator('.fh-match').filter(has_text='确认重复记录 · 已撤销')).to_be_visible()
                revoked = overview()
                assert revoked['totals'][0]['netSpendCents'] == 17000 and revoked['transactionCount'] == 4
                with closing(sqlite3.connect(Path(folder) / 'household.sqlite3')) as con:
                    after_raw = dict(con.execute('SELECT id,data FROM hub_transactions'))
                    assert original_raw == after_raw
                    assert con.execute("SELECT count(*) FROM hub_reconciliations WHERE status='active'").fetchone()[0] == 2
                page.evaluate('FinanceHub.open("overview")')
                expect(page.locator('.fh-currency .fh-metrics > div').first).to_contain_text('CNY 170')
                checks.append('UI revoke duplicate returns CNY170; four original JSON records and amounts unchanged')

                partner_context = browser.new_context(viewport={'width': 390, 'height': 844})
                assert partner_context.request.post(base + '/api/login', data={'username': 'member2', 'password': 'testing-password-two'}).status == 200
                partner = partner_context.new_page()
                partner.on('pageerror', lambda err: errors.append(str(err)))
                partner.goto(base)
                expect(partner.locator('.ps-welcome')).to_be_visible()
                partner.evaluate('FinanceHub.open("ledger")')
                expect(partner.locator('.fh-workspace')).to_be_visible()
                expect(partner.locator('.fh-transaction')).to_have_count(0)
                hidden = partner_context.request.get(base + '/api/finance-hub/reconciliation?transactionId=' + records['SYNTHETIC_PAYMENT_100']['id'])
                assert hidden.status == 404
                assert 'SYNTHETIC_' not in partner_context.request.get(base + '/api/state').text()
                checks.append('Partner UI has no records; direct candidate request is404; shared state excludes synthetic titles')
                assert errors == [], errors
                result = {'passed': True, 'checks': checks, 'netSpendBeforeCents': 17000, 'netSpendConfirmedCents': 7000,
                          'netSpendAfterRevokeCents': 17000, 'rawRecordsPreserved': 4, 'relations': receipts,
                          'pageErrors': errors, 'productionWrites': 0}
                (out / 'finance-reconciliation-browser-verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                print(json.dumps(result, ensure_ascii=False, indent=2))
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == '__main__':
    main()
