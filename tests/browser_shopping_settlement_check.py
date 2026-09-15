"""Loopback Flask/SQLite/Edge shopping settlement and delayed-response checks."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import traceback
from urllib.parse import urlsplit

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
    paths = set(ROOT.glob('*.py')) | {Path(__file__)}
    for folder in ('static', 'deploy'):
        paths.update(path for path in (ROOT/folder).rglob('*') if path.is_file() and '__pycache__' not in path.parts)
    paths.update(ROOT/name for name in ('Dockerfile', 'compose.yaml', 'requirements.txt', 'pytest.ini'))
    def hashes():
        return {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths)}
    checks, errors, external, providers, screenshots, request_counts = [], [], [], [], [], {}
    report = {'passed': False, 'checks': checks, 'pageErrors': errors, 'externalRequests': external,
              'providerCalls': providers, 'requestCounts': request_counts, 'screenshots': screenshots,
              'sourceHashes': hashes(), 'realCloudWrites': 0, 'productionWrites': 0, 'realPrivateInputs': 0,
              'scope': 'Real temporary Flask/SQLite/Edge; own payment to shared shopping, preview/confirm/readback, old responses and actual cookie identity changes. No real account/provider/production use.'}
    def passed(name):
        assert name not in checks
        checks.append(name)
    def deny(*_args, **_kwargs):
        providers.append('unexpected-provider-call')
        raise AssertionError('External provider access is forbidden')

    with tempfile.TemporaryDirectory(prefix='shopping-settlement-browser-') as temporary:
        app = create_app({'TESTING': True, 'SECRET_KEY': 'synthetic-shopping-settlement-secret',
                          'DATA_DIR': temporary, 'SESSION_COOKIE_SECURE': False,
                          'MEMBER1_PASSWORD': 'testing-password-one', 'MEMBER2_PASSWORD': 'testing-password-two',
                          'PUBLIC_ORIGIN': 'http://localhost', 'CLOUD_TRANSPORT': deny,
                          'OAUTH_TRANSPORT': deny, 'CLOUD_PROVIDER_FACTORY': deny, 'OPENAI_API_KEY': ''})
        assert app.config['SESSION_REFRESH_EACH_REQUEST'] is False
        endpoint = '/api/finance-hub/shopping-settlements'
        assert any(rule.rule == endpoint+'/context' for rule in app.url_map.iter_rules())
        database = Path(temporary)/'household.sqlite3'
        def sql(statement, parameters=()):
            with closing(sqlite3.connect(database)) as con:
                rows = con.execute(statement, parameters).fetchall()
                con.commit()
                return rows
        day = datetime.now(timezone.utc).date().isoformat()
        month = day[:7]
        counter = 0
        server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=Quiet)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
                def login(context, member=1, child=False):
                    sql('DELETE FROM attempts')
                    context.request.get(base+'/api/me')
                    prefix = 'second-home-password-' if child else 'testing-password-'
                    response = context.request.post(base+'/api/login', data={'username': f'member{member}', 'password': prefix+('one' if member == 1 else 'two')})
                    assert response.status == 200, response.text()
                def headers(context):
                    return {'X-CSRF-Token': context.request.get(base+'/api/me').json()['csrf']}
                def post(context, path, payload):
                    response = context.request.post(base+path, headers=headers(context), data=payload)
                    assert response.status in (200, 201), response.text()
                    return response.json()
                def shopping(context, title='共同采购', actual=1200, done=False):
                    result = post(context, '/api/items/shopping', {'title': title, 'quantity': '1 件', 'owner': 'shared',
                                  'budget': 16000, 'actual': actual, 'done': done, 'note': '虚构测试规格', 'photoIds': []})
                    return next(value for value in context.request.get(base+'/api/state').json()['shopping'] if value['id'] == result['id'])
                def payment(context, title, kind='payments', flow='expense', value='100.00', currency='CNY'):
                    nonlocal counter
                    counter += 1
                    payload = {'source': 'generic', 'kind': kind,
                               'csv': 'date,title,amount,currency,flow,category,id,status\n'+f'{day},{title},{value},{currency},{flow},居家,browser-{counter},成功\n'}
                    preview = post(context, '/api/finance-hub/imports/preview', payload)
                    post(context, '/api/finance-hub/imports/confirm', {**payload, 'previewToken': preview['previewToken']})
                    values = context.request.get(base+'/api/finance-hub/overview?month='+month).json()['transactions']
                    return next(value for value in values if value['externalId'] == f'browser-{counter}')
                def item(context, uid):
                    return next(value for value in context.request.get(base+'/api/state').json()['shopping'] if value['id'] == uid)
                def context_json(context, shopping_id='', transaction_id='', link_id=''):
                    params = {'shoppingId': shopping_id, 'transactionId': transaction_id, 'linkId': link_id}
                    response = context.request.get(base+endpoint+'/context', params={key: value for key, value in params.items() if value})
                    assert response.status == 200, response.text()
                    return response.json()
                def financial_snapshot():
                    return {'records': sql('SELECT id,owner,data,revision FROM hub_transactions ORDER BY id'),
                            'finance': sql("SELECT data,revision FROM settings WHERE id='finance'"),
                            'budgets': sql('SELECT * FROM hub_budgets ORDER BY 1'),
                            'investments': sql('SELECT * FROM hub_investments ORDER BY id')}

                seed = browser.new_context()
                login(seed)
                invitation = post(seed, '/api/spaces/invitations', {})
                child_entry = post(seed, '/api/spaces/redeem', {'invitation': invitation['invitation'],
                                  'name': 'Synthetic Settlement Household', 'slug': 'synthetic-settlement',
                                  'MEMBER1_PASSWORD': 'second-home-password-one', 'MEMBER2_PASSWORD': 'second-home-password-two'})['entry']
                partner = browser.new_context();login(partner, 2)
                private_partner = payment(partner, 'PARTNER_ONLY_SETTLEMENT_PAYMENT')
                partner.close()

                class Flow:
                    def __init__(self, width=390, source_kind='payments', open_now=True):
                        self.context = browser.new_context(viewport={'width': width, 'height': 920})
                        self.held, self.gate, self.calls = [], None, []
                        self.context.route('**/*', self.route)
                        login(self.context)
                        self.shopping = shopping(self.context, '共同采购 '+str(counter+1))
                        self.payment = payment(self.context, 'PRIVATE_OWNER_PAYMENT_'+str(counter+1))
                        self.transaction = payment(self.context, 'PRIVATE_ORDER_'+str(counter+1), kind='orders') if source_kind == 'orders' else self.payment
                        self.page = self.context.new_page()
                        self.page.on('pageerror', lambda error: errors.append(str(error)))
                        self.page.goto(base)
                        expect(self.page.locator('.ps-welcome')).to_be_visible()
                        self.page.evaluate('clearInterval(pollTimer)')
                        if open_now:self.open()
                    def route(self, route):
                        request = route.request
                        if not request.url.startswith(base+'/'):
                            external.append({'method': request.method, 'url': request.url});route.abort();return
                        path = urlsplit(request.url).path
                        key = request.method+' '+path
                        request_counts[key] = request_counts.get(key, 0)+1
                        if path.startswith(endpoint):self.calls.append((request.method, path, request.post_data))
                        if self.gate and self.gate(request.method, path):
                            self.gate = None
                            response = route.fetch()
                            assert response.status == 200, response.text()
                            assert 'set-cookie' not in response.headers
                            self.held.append((route, response))
                        else:route.continue_()
                    def open(self):
                        self.page.evaluate('options=>ShoppingSettlement.open(options)', {'shoppingId': self.shopping['id'], 'transactionId': self.transaction['id']})
                        expect(self.page.locator('#shopping-settlement-form')).to_be_visible()
                    def draft(self, value='80.00', done=False):
                        self.page.locator(f'[name=paymentId][value="{self.payment["id"]}"]').check()
                        self.page.locator(f'[name=shoppingId][value="{self.shopping["id"]}"]').check()
                        self.page.locator('[name=amount]').fill(value)
                        self.page.locator('#shopping-settlement-form [name=done]').set_checked(done)
                    def preview(self, value='80.00', done=False):
                        self.draft(value, done)
                        self.page.locator('#shopping-settlement-form [type=submit]').click()
                        expect(self.page.locator('[name=shareAck]')).to_be_visible()
                    def confirm(self):
                        self.page.locator('[name=shareAck]').check()
                        self.page.locator('[data-ss=confirm]').click()
                        expect(self.page.locator('.ss-result')).to_be_visible()
                    def apply(self, value='80.00', done=False):
                        self.preview(value, done);self.confirm()
                    def links(self):
                        return [value for value in context_json(self.context, self.shopping['id'])['links'] if value['shoppingId']==self.shopping['id']]
                    def active_link(self):
                        return next(value for value in self.links() if value['shoppingId'] == self.shopping['id'] and value['status'] == 'active')
                    def show_links(self):
                        links = self.page.locator('.ss-links')
                        if links.get_attribute('open') is None:links.locator('summary').click()
                    def revoke_preview(self, restore=False):
                        self.open();self.show_links()
                        link = self.active_link()
                        self.page.locator(f'[data-ss-link="{link["id"]}"] [data-ss=revoke]').click()
                        expect(self.page.locator('#shopping-settlement-revoke')).to_be_visible()
                        if restore:self.page.locator('[value=restore_if_unchanged]').check()
                        self.page.locator('#shopping-settlement-revoke [type=submit]').click()
                        expect(self.page.locator('[name=shareAck]')).to_be_visible()
                    def arm(self, operation):
                        if operation == 'read' or operation.endswith('context'):
                            self.gate = lambda method, path: method == 'GET' and path == endpoint+'/context'
                        elif operation.endswith('state'):
                            self.gate = lambda method, path: method == 'GET' and path == '/api/state'
                        elif operation == 'me':self.gate = lambda method, path: method == 'GET' and path == '/api/me'
                        else:self.gate = lambda method, path: method == 'POST' and path == endpoint+('/preview' if operation == 'preview' else '/confirm')
                    def trigger(self, operation):
                        if operation in ('read', 'me'):
                            self.page.locator('#shopping-settlement-search [type=submit]').click()
                        elif operation == 'preview':self.page.locator('#shopping-settlement-form [type=submit]').click()
                        else:
                            self.page.locator('[name=shareAck]').check();self.page.locator('[data-ss=confirm]').click()
                        for _ in range(300):
                            if self.held:break
                            self.page.wait_for_timeout(10)
                        assert len(self.held) == 1, operation
                    def release(self, error=False):
                        route, response = self.held.pop()
                        if error:route.fulfill(status=503, content_type='application/json', body=json.dumps({'error': 'SYNTHETIC_OLD_FAILURE'}))
                        else:route.fulfill(response=response)
                        self.page.wait_for_timeout(180)
                    def switch(self, target, boot=True):
                        if target == 'household':
                            assert self.context.request.get(base+child_entry).status == 200
                            login(self.context, child=True)
                        else:login(self.context, 2)
                        if boot:
                            self.page.evaluate('boot()')
                            expected = self.context.request.get(base+'/api/me').json()['user']
                            expect(self.page.locator('.ps-welcome')).to_be_visible()
                            for _ in range(100):
                                actual = self.page.evaluate('({id:user?.id,householdId:user?.householdId})')
                                if actual['id'] == expected['id'] and actual['householdId'] == expected['householdId']:break
                                self.page.wait_for_timeout(10)
                            assert actual['id'] == expected['id'] and actual['householdId'] == expected['householdId']
                            self.page.evaluate('clearInterval(pollTimer)')
                    def close(self):
                        for route,response in self.held:route.fulfill(response=response)
                        self.held=[];self.context.close()

                flow=Flow(open_now=False)
                try:
                    flow.page.evaluate('ShoppingUI.openManager()')
                    flow.page.locator(f'[data-shopping-settlement-shopping="{flow.shopping["id"]}"]').click()
                    expect(flow.page.locator('#shopping-settlement-form')).to_be_visible()
                    expect(flow.page.locator('[data-shopping-settlement]')).not_to_contain_text('PARTNER_ONLY_SETTLEMENT_PAYMENT')
                    passed('real_saved_shopping_row_entry_private_owner_only')
                    before=financial_snapshot();flow.preview('80.00',False)
                    assert item(flow.context,flow.shopping['id'])['actual']==1200
                    assert financial_snapshot()==before
                    expect(flow.page.locator('[data-ss=confirm]')).to_be_disabled()
                    passed('preview_does_not_write_shared_item_or_ledger_and_requires_ack')
                    flow.confirm()
                    value=item(flow.context,flow.shopping['id'])
                    assert value['actual']==8000 and value['done'] is False and value['budget']==16000
                    assert financial_snapshot()==before
                    passed('confirm_replaces_whole_actual_without_done_or_budget_double_count')
                    flow.page.locator('[data-ss=open-shopping]').click()
                    expect(flow.page.locator('.shopping-form [name=actual]')).to_have_value('80.00')
                    expect(flow.page.locator('.shopping-form [name=done]')).not_to_be_checked()
                    passed('fresh_state_opens_exact_original_shopping_editor')
                    flow.open();flow.show_links();link=flow.active_link()
                    flow.page.locator(f'[data-ss-link="{link["id"]}"] [data-ss=update]').click()
                    expect(flow.page.locator('[name=amount]')).to_have_value('80.00')
                    flow.preview('70.00',True);flow.confirm()
                    value=item(flow.context,flow.shopping['id'])
                    assert value['actual']==7000 and value['done'] is True and len([v for v in flow.links() if v['status']=='active'])==1
                    assert financial_snapshot()==before
                    passed('update_keeps_link_and_payment_and_independent_done')
                    flow.revoke_preview();flow.confirm()
                    value=item(flow.context,flow.shopping['id'])
                    assert value['actual']==7000 and value['done'] is True
                    assert flow.links()[0]['status']=='revoked'
                    passed('default_detach_keeps_current_shared_values')
                finally:flow.close()

                flow=Flow()
                try:
                    flow.apply('0.00',True)
                    assert item(flow.context,flow.shopping['id'])['actual']==0
                    flow.revoke_preview(True);flow.confirm()
                    value=item(flow.context,flow.shopping['id'])
                    assert value['actual']==1200 and value['done'] is False
                    passed('zero_amount_valid_and_restore_unchanged_returns_original_values')
                finally:flow.close()

                flow=Flow(source_kind='orders')
                try:
                    expect(flow.page.locator('[name=paymentId]')).to_have_count(0)
                    flow.page.locator('[data-ss=reconcile]').click()
                    expect(flow.page.locator('#fh-match-search')).to_be_visible()
                    flow.page.locator('#fh-match-search [name=query]').fill(flow.payment['title'])
                    flow.page.locator('#fh-match-search [type=submit]').click()
                    expect(flow.page.locator('[data-fh=choose-reconciliation]')).to_have_count(1)
                    flow.page.locator('[data-fh=choose-reconciliation]').click()
                    flow.page.locator('#fh-reconciliation-form [type=submit]').click()
                    flow.page.locator('[data-fh=confirm-reconciliation]').click()
                    expect(flow.page.locator('[data-fh=return-shopping-settlement]')).to_be_visible()
                    flow.page.locator('[data-fh=return-shopping-settlement]').click()
                    expect(flow.page.locator(f'[name=paymentId][value="{flow.payment["id"]}"]')).to_be_visible()
                    flow.apply('60.00',False)
                    assert item(flow.context,flow.shopping['id'])['actual']==6000
                    passed('order_to_original_reconciliation_and_back_then_shopping_confirm')
                finally:flow.close()

                flow=Flow(open_now=False)
                try:
                    flow.page.evaluate('FinanceHub.open("ledger")')
                    row=flow.page.locator('.fh-transaction').filter(has_text=flow.payment['title'])
                    row.locator('[data-fh=shopping-settlement]').click()
                    expect(flow.page.locator('#shopping-settlement-form')).to_be_visible()
                    assert flow.page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                    passed('real_ledger_entry_mobile_no_horizontal_overflow')
                finally:flow.close()

                for change in ['source_changed','refund','source_deleted','shopping_deleted']:
                    flow=Flow()
                    try:
                        flow.apply();link=flow.active_link()
                        if change=='source_changed':
                            response=flow.context.request.patch(base+'/api/finance-hub/transactions/'+flow.payment['id'],headers=headers(flow.context),
                                data={'category':'后来修改分类','flow':'expense','visibility':'private','revision':flow.payment['revision']})
                        elif change=='refund':
                            refund=payment(flow.context,'PRIVATE_REFUND_'+str(counter+1),flow='refund',value='20.00')
                            preview=post(flow.context,'/api/finance-hub/reconciliation/preview',{'kind':'refund_payment','leftId':refund['id'],'rightId':flow.payment['id'],'amount':'20.00'})
                            post(flow.context,'/api/finance-hub/reconciliation/confirm',{'previewToken':preview['previewToken']})
                            response=None
                        elif change=='source_deleted':
                            response=flow.context.request.delete(base+'/api/finance-hub/transactions/'+flow.payment['id'],headers=headers(flow.context),data={'revision':flow.payment['revision']})
                        else:
                            latest=item(flow.context,flow.shopping['id'])
                            response=flow.context.request.delete(base+'/api/items/shopping/'+latest['id'],headers=headers(flow.context),data={'revision':latest['revision']})
                        if response is not None:assert response.status==200,response.text()
                        sent=len([call for call in flow.calls if call[1].endswith('/confirm')])
                        flow.page.locator('[data-ss=reload]').click()
                        expect(flow.page.locator(f'[data-ss-link="{link["id"]}"]')).to_contain_text('需要重新核对')
                        assert len([call for call in flow.calls if call[1].endswith('/confirm')])==sent
                        if change!='shopping_deleted':assert item(flow.context,flow.shopping['id'])['actual']==8000
                        if change in ('source_deleted','shopping_deleted'):
                            flow.page.locator(f'[data-ss-link="{link["id"]}"] [data-ss=revoke]').click()
                            flow.page.locator('#shopping-settlement-revoke [type=submit]').click()
                            expect(flow.page.locator('[name=shareAck]')).to_be_visible();flow.confirm()
                            value=context_json(flow.context,link_id=link['id'])
                            assert next(row for row in value['links'] if row['id']==link['id'])['status']=='revoked'
                        passed(change+'_requires_review_without_auto_write_and_missing_source_can_detach')
                    finally:flow.close()

                flow=Flow()
                try:
                    flow.apply();old=item(flow.context,flow.shopping['id'])
                    response=flow.context.request.patch(base+'/api/items/shopping/'+old['id'],headers=headers(flow.context),
                        data={'revision':old['revision'],'actual':4400})
                    assert response.status==200,response.text()
                    flow.open();flow.show_links();link=flow.active_link()
                    flow.page.locator(f'[data-ss-link="{link["id"]}"] [data-ss=revoke]').click()
                    flow.page.locator('[value=restore_if_unchanged]').check()
                    flow.page.locator('#shopping-settlement-revoke [type=submit]').click()
                    expect(flow.page.locator('.ss-error')).to_contain_text('重新预览')
                    expect(flow.page.locator('[value=restore_if_unchanged]')).to_be_checked()
                    assert item(flow.context,old['id'])['actual']==4400
                    flow.page.locator('[value=detach_keep_current]').check()
                    flow.page.locator('#shopping-settlement-revoke [type=submit]').click()
                    expect(flow.page.locator('[name=shareAck]')).to_be_visible();flow.confirm()
                    assert item(flow.context,old['id'])['actual']==4400
                    passed('unsafe_restore_409_preserves_choice_and_explicit_keep_current_detaches')
                finally:flow.close()

                for stage in ['preview','confirm']:
                    flow=Flow()
                    try:
                        flow.preview() if stage=='confirm' else flow.draft()
                        flow.arm(stage);flow.trigger(stage);flow.release(True)
                        expect(flow.page.locator('.ss-error')).to_contain_text('SYNTHETIC_OLD_FAILURE')
                        if stage=='preview':
                            expect(flow.page.locator('[name=amount]')).to_have_value('80.00')
                            flow.page.locator('#shopping-settlement-form [type=submit]').click()
                            expect(flow.page.locator('[name=shareAck]')).to_be_visible()
                            assert item(flow.context,flow.shopping['id'])['actual']==1200
                        else:
                            token1=json.loads([call[2] for call in flow.calls if call[1].endswith('/confirm')][0])
                            flow.page.locator('[data-ss=confirm]').click()
                            expect(flow.page.locator('.ss-result')).to_be_visible()
                            tokens=[json.loads(call[2]) for call in flow.calls if call[1].endswith('/confirm')]
                            assert len(tokens)==2 and tokens[0]==tokens[1]==token1
                            assert len(flow.links())==1
                        passed(stage+'_503_preserves_original_draft_or_confirmation_token')
                    finally:flow.close()

                flow=Flow()
                try:
                    flow.preview();old=item(flow.context,flow.shopping['id'])
                    changed={**old,'actual':3300,'revision':old['revision']};changed.pop('id')
                    response=flow.context.request.patch(base+'/api/items/shopping/'+old['id'],headers=headers(flow.context),data=changed)
                    assert response.status==200,response.text()
                    flow.page.locator('[name=shareAck]').check();flow.page.locator('[data-ss=confirm]').click()
                    expect(flow.page.locator('.ss-error')).to_contain_text('重新预览')
                    expect(flow.page.locator('[data-ss=confirm]')).to_be_disabled()
                    flow.page.locator('[data-ss=reload]').click()
                    expect(flow.page.locator('[name=amount]')).to_have_value('80.00')
                    assert item(flow.context,old['id'])['actual']==3300
                    passed('409_disables_old_receipt_and_keeps_amount_for_fresh_preview')
                finally:flow.close()

                for stage in ['read','preview','confirm','confirm_context','confirm_state','revoke_confirm']:
                    for target in ['new','close','member','household']:
                        flow=Flow()
                        try:
                            if stage=='preview':flow.draft()
                            elif stage=='revoke_confirm':flow.apply();flow.revoke_preview()
                            elif stage!='read':flow.preview()
                            flow.arm('confirm' if stage=='revoke_confirm' else stage);flow.trigger('confirm' if stage=='revoke_confirm' else stage)
                            if target=='close':flow.page.locator('#dialog [data-action=close]').click()
                            else:
                                if target in ('member','household'):flow.switch(target)
                                flow.page.evaluate('ShoppingSettlement.open({})')
                                expect(flow.page.locator('#shopping-settlement-form')).to_be_visible()
                                flow.page.locator('[name=amount]').fill('19.99')
                                flow.page.evaluate('window.newSettlementNode=document.querySelector("#shopping-settlement-form")')
                            sent=len([call for call in flow.calls if call[1].endswith('/confirm')])
                            flow.release()
                            if target=='close':expect(flow.page.locator('#dialog')).not_to_be_visible()
                            else:
                                assert flow.page.evaluate('window.newSettlementNode.isConnected')
                                expect(flow.page.locator('[name=amount]')).to_have_value('19.99')
                                expect(flow.page.locator('.ss-error')).to_have_text('')
                                if target in ('member','household'):
                                    expect(flow.page.locator('[data-shopping-settlement]')).not_to_contain_text(flow.payment['title'])
                            assert len([call for call in flow.calls if call[1].endswith('/confirm')])==sent
                            passed('late_'+stage+'_cannot_replace_'+target)
                        finally:flow.close()

                for stage in ['read','preview','confirm_state','me']:
                    flow=Flow()
                    try:
                        if stage=='preview':flow.draft()
                        elif stage=='confirm_state':flow.preview()
                        flow.arm(stage);flow.trigger(stage)
                        flow.page.evaluate('ShoppingSettlement.open({})')
                        expect(flow.page.locator('#shopping-settlement-form')).to_be_visible()
                        flow.page.locator('[name=amount]').fill('28.88')
                        flow.release(True)
                        expect(flow.page.locator('[name=amount]')).to_have_value('28.88')
                        expect(flow.page.locator('.ss-error')).to_have_text('')
                        passed('late_'+stage+'_503_does_not_pollute_new_flow')
                    finally:flow.close()

                for stage in ['read','preview']:
                    flow=Flow()
                    try:
                        if stage=='preview':flow.draft()
                        flow.arm(stage);flow.trigger(stage)
                        flow.page.locator('[name=amount]').fill('17.17')
                        flow.release()
                        expect(flow.page.locator('[name=amount]')).to_have_value('17.17')
                        expect(flow.page.locator('.ss-review')).to_have_count(0)
                        passed('same_form_edit_invalidates_'+stage)
                    finally:flow.close()

                flow=Flow()
                try:
                    flow.switch('member',boot=False)
                    flow.page.locator('#shopping-settlement-search [type=submit]').click()
                    expect(flow.page.locator('[data-shopping-settlement]')).to_contain_text('请重新核对登录状态')
                    expect(flow.page.locator('[data-shopping-settlement]')).not_to_contain_text(flow.payment['title'])
                    passed('cookie_only_member_switch_clears_private_view_on_next_explicit_read')
                finally:flow.close()

                flow=Flow()
                try:
                    flow.preview();flow.arm('confirm');flow.trigger('confirm')
                    flow.page.evaluate('document.querySelector("[data-ss=confirm]").click()')
                    assert len([call for call in flow.calls if call[1].endswith('/confirm')])==1
                    flow.release();expect(flow.page.locator('.ss-result')).to_be_visible()
                    assert len(flow.links())==1
                    passed('confirm_in_flight_duplicate_click_sends_one_request')
                finally:flow.close()

                flow=Flow()
                try:
                    flow.draft('17.17',True)
                    expect(flow.page.locator('[data-ss=next]')).to_be_enabled()
                    flow.page.locator('[data-ss=next]').click()
                    expect(flow.page.locator('.ss-pagination')).to_contain_text('第 2 页')
                    expect(flow.page.locator('[name=amount]')).to_have_value('17.17')
                    expect(flow.page.locator(f'[name=paymentId][value="{flow.payment["id"]}"]')).to_be_checked()
                    expect(flow.page.locator(f'[name=shoppingId][value="{flow.shopping["id"]}"]')).to_be_checked()
                    flow.page.locator('[data-ss=previous]').click()
                    expect(flow.page.locator('.ss-pagination')).to_contain_text('第 1 页')
                    flow.page.locator('#shopping-settlement-search [name=q]').fill('NO_MATCH_EXCEPT_PINNED')
                    flow.page.locator('#shopping-settlement-search [type=submit]').click()
                    expect(flow.page.locator('[name=paymentId]')).to_have_count(1)
                    expect(flow.page.locator('[name=shoppingId]')).to_have_count(1)
                    expect(flow.page.locator('[name=amount]')).to_have_value('17.17')
                    expect(flow.page.locator('[name=done]')).to_be_checked()
                    passed('pagination_and_search_preserve_selected_ids_amount_and_done')
                finally:flow.close()

                for theme in ['forest','light','ocean']:
                    for width in [360,768,1440]:
                        flow=Flow(width=width)
                        try:
                            response=flow.context.request.put(base+'/api/preferences',headers=headers(flow.context),data={'theme':theme,'density':'comfortable','homeView':'today'})
                            assert response.status==200
                            flow.page.reload();expect(flow.page.locator('.ps-welcome')).to_be_visible();flow.page.evaluate('clearInterval(pollTimer)');flow.open()
                            flow.draft('80.00')
                            assert flow.page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                            assert flow.page.locator('[data-shopping-settlement]').evaluate('(node)=>node.scrollWidth<=node.clientWidth+1')
                            path=output/f'shopping-settlement-{theme}-{width}.png'
                            flow.page.screenshot(path=str(path),full_page=True);screenshots.append(str(path))
                            passed(f'theme_{theme}_{width}_no_horizontal_overflow')
                        finally:flow.close()

                public=browser.new_context();public_calls=[]
                public.route('**/*',lambda route: route.continue_() if route.request.url.startswith(base+'/') else (external.append({'url':route.request.url}),route.abort()))
                demo=public.new_page();demo.on('pageerror',lambda error:errors.append(str(error)))
                demo.on('request',lambda request:public_calls.append(request.url))
                demo.goto(base+'/demo');expect(demo.locator('.ps-welcome')).to_be_visible()
                before=len([url for url in public_calls if endpoint in url]);demo.evaluate('ShoppingSettlement.open({})');demo.wait_for_timeout(100)
                assert len([url for url in public_calls if endpoint in url])==before
                assert demo.locator('[data-shopping-settlement]').count()==0
                passed('demo_does_not_read_private_settlement_api')
                demo.close();public.close()
                tv=browser.new_context();pair=tv.request.post(base+'/api/pair/start',data={}).json()
                login(seed)
                post(seed,'/api/pair/approve',{'code':pair['code'],'name':'Synthetic Settlement TV','focus':'member1','calendarView':'today'})
                assert tv.request.post(base+'/api/pair/poll',data={'secret':pair['secret']}).json()['approved']
                television=tv.new_page();television.on('pageerror',lambda error:errors.append(str(error)))
                television.route('**/*',lambda route: route.continue_() if route.request.url.startswith(base+'/') else (external.append({'url':route.request.url}),route.abort()))
                television.goto(base+'/tv');expect(television.locator('body.tv .shell')).to_be_visible()
                television.evaluate('ShoppingSettlement.open({})');television.wait_for_timeout(100)
                assert television.locator('[data-shopping-settlement],[data-shopping-settlement-shopping],[data-fh=shopping-settlement]').count()==0
                assert tv.request.get(base+endpoint+'/context',headers={'X-Display-Mode':'tv'}).status==403
                state=tv.request.get(base+'/api/state',headers={'X-Display-Mode':'tv'}).text()
                assert 'PRIVATE_OWNER_PAYMENT' not in state and 'PARTNER_ONLY_SETTLEMENT_PAYMENT' not in state and 'paymentId' not in state
                passed('tv_readonly_shared_values_without_private_links_or_entry')
                tv.close();seed.close();browser.close()
                assert not errors and not external and not providers
                report['passed']=True
        except Exception as error:
            report['failure']=str(error)
            report['traceback']=traceback.format_exc()
            raise
        finally:
            server.shutdown();thread.join(timeout=5)
            report['sourceHashesAfter']=hashes()
            report['sourceUnchanged']=report['sourceHashes']==report['sourceHashesAfter']
            report['passed']=report['passed'] and report['sourceUnchanged'] and not errors and not external and not providers
            (output/'shopping-settlement-browser-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'passed':report['passed'],'checks':len(checks),'sourceUnchanged':report['sourceUnchanged'],'pageErrors':errors,'failure':report.get('failure')},ensure_ascii=False))


if __name__ == '__main__':
    main()
