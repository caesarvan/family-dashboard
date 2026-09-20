"""Real local journey expense allocation flows with synthetic records only.

Uses the existing HTTPS/Flask/SQLite/Edge fixture. Network faults only delay or
drop actual responses; no business result is substituted. Run after review of
the complete source and a fresh Expo export of that same source.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import traceback
from unittest.mock import patch
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from playwright.sync_api import expect, sync_playwright
from flask import request
import browser_finance_flow_mapping_check as fixture
from browser_expo_finance_check import DAY, Quiet, button, make_server, row, sha

HARNESS = 'tests/browser_expo_journey_finance_check.py'
PREFIX = '/api/finance-hub/journey-allocations'
CASES = ('allocate_refund_source', 'lost_confirmation_reload', 'identity_offline_late_read')


class Run(fixture.Run):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        assert Path(__file__).resolve() == (self.root / HARNESS).resolve()
        actual_hashes = {HARNESS: sha(Path(__file__))}
        for name in ('journey_finance', 'journey_workflows', 'finance_hub', 'finance_source_bridge'):
            actual = Path(sys.modules[name].__file__).resolve()
            relative = name + '.py'
            assert actual == (self.root / relative).resolve()
            actual_hashes[relative] = sha(actual)
        assert self.report.setdefault('journeyFixtureHashes', actual_hashes) == actual_hashes
        self.exchange = 0

    def start(self, port=0):
        if not hasattr(self, 'http'):
            # Parent construction installs the first journal before any browser
            # exists. Subsequent starts retain that same journal and lock.
            return super().start(port)
        self.application = self.source.create_app(self.cfg)

        @self.application.after_request
        def journal(response):
            if request.path.startswith('/api/'):
                with self.journal_lock:
                    self.http.append({'index': len(self.http), 'method': request.method,
                        'path': request.path, 'status': response.status_code})
            return response

        # Register on the newly created application before the listener can
        # accept even the first background request from the open browser.
        self.server = make_server('127.0.0.1', port, self.application, threaded=True,
                                  request_handler=Quiet, ssl_context='adhoc')
        self.base = 'https://127.0.0.1:' + str(self.server.server_port)
        self.cfg['PUBLIC_ORIGIN'] = self.base
        self.application.config['PUBLIC_ORIGIN'] = self.base
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def snapshot(self):
        result = super().snapshot()
        with closing(sqlite3.connect(self.database)) as con:
            for name in ('hub_journey_allocations', 'hub_journey_allocation_operations',
                         'journey_workflows', 'journey_links', 'entities', 'settings'):
                result[name] = sorted(con.execute('SELECT * FROM "' + name + '"').fetchall(), key=repr)
        return result

    def protected(self):
        """The allocation feature must leave these authority rows unchanged."""
        snap = self.snapshot()
        result = {name: snap[name] for name in ('hub_transactions', 'hub_imports',
            'hub_import_receipts', 'hub_reconciliations', 'hub_budgets',
            'journey_workflows', 'journey_links', 'entities', 'settings')}
        # audit() legitimately increments only settings.meta.revision. Its
        # exact increment and the exact new audit row are verified separately.
        result['settings'] = [(r[0], r[1], None) if r[0] == 'meta' else r for r in result['settings']]
        return result

    def audit_state(self):
        with closing(sqlite3.connect(self.database)) as con:
            return {'revision': con.execute("SELECT revision FROM settings WHERE id='meta'").fetchone()[0],
                    'rows': con.execute('SELECT * FROM audit ORDER BY id').fetchall()}

    def audit_increment(self, before, operation, target):
        after = self.audit_state()
        assert after['revision'] == before['revision'] + 1
        assert after['rows'][:-1] == before['rows']
        assert len(after['rows']) == len(before['rows']) + 1
        with closing(sqlite3.connect(self.database)) as con:
            actor, action, actual_target = con.execute('SELECT actor,action,target FROM audit ORDER BY id DESC LIMIT 1').fetchone()
        assert (actor, action, actual_target) == ('member1', 'finance.journey.' + operation, target)
        return after

    def allocation_rows(self):
        snap = self.snapshot()
        return {key: snap[key] for key in ('hub_journey_allocations', 'hub_journey_allocation_operations')}

    def journey(self, ctx, title='合成旅行费用核对'):
        plan = {'title': title, 'start': '2028-03-02', 'end': '2028-03-04',
            'budget': 100000, 'paid': 25000, 'saved': 20000, 'international': False,
            'memberIds': ['member1', 'member2'], 'checklist': [], 'segments': [],
            'destinations': [{'key': 'city', 'country': '中国', 'city': '杭州',
                'arrival': '2028-03-02', 'departure': '2028-03-04'}],
            'shopping': [{'key': 'supply', 'title': '合成已有采购', 'quantity': '1 件',
                'owner': 'member1', 'budget': 10000}]}
        preview = self.write(ctx, 'POST', '/api/journeys/preview', {'plan': plan})
        saved = self.write(ctx, 'POST', '/api/journeys/apply', {
            'previewToken': preview['previewToken'], 'idempotencyKey': uuid4().hex}, 201)
        return self.get(ctx, '/api/journeys/' + saved['id'])

    def payment(self, ctx, title='合成私人住宿付款', amount='1000.00', **kwargs):
        kind = kwargs.pop('kind', 'payments')
        self.seed(ctx, [row(title, amount, **kwargs)], kind=kind)
        month = kwargs.get('day', DAY)[:7]
        return self.find(self.overview(ctx, month=month), title)

    def reconciliation(self, ctx, kind, left, right, amount):
        preview = self.write(ctx, 'POST', '/api/finance-hub/reconciliation/preview', {
            'kind': kind, 'leftId': left['id'], 'rightId': right['id'], 'amount': amount})
        return self.write(ctx, 'POST', '/api/finance-hub/reconciliation/confirm',
                          {'previewToken': preview['previewToken']})

    def allocations(self, ctx, **query):
        return self.get(ctx, PREFIX + ('?' + urlencode(query) if query else ''))

    def open_trip(self, page, journey):
        page.goto(self.base + '/app/trips?' + urlencode({'request': '1001', 'item': journey['tripId']}))
        expect(page.get_by_role('heading', name='旅行详情', exact=True)).to_be_visible(timeout=15000)
        button(page, '我的旅行费用').click()
        expect(page.get_by_test_id('journey-finance-summary')).to_be_visible(timeout=15000)

    def draft(self, page, payment, amount):
        button(page, '选择实际付款').click()
        card = page.get_by_test_id('journey-payment-' + payment['id'])
        expect(card).to_be_visible(timeout=15000)
        card.get_by_role('button', name='选择这笔付款', exact=True).click()
        page.get_by_role('textbox', name='归集金额', exact=True).fill(amount)

    def post(self, page, suffix, action, *, drop=False, status=200):
        calls, url = [], self.base + PREFIX + suffix
        def intercept(route):
            assert route.request.method == 'POST'
            response = route.fetch(max_redirects=0)
            raw = response.body()
            calls.append({'payload': route.request.post_data_json, 'status': response.status,
                          'result': json.loads(raw), 'responseBytes': len(raw)})
            if drop:
                route.abort('failed')
            else:
                route.fulfill(status=response.status, headers=response.headers, body=raw)
        page.route(url, intercept)
        try:
            action()
            self.settle(page, lambda: len(calls) == 1)
            assert len(calls) == 1 and calls[0]['status'] == status, calls
            return calls[0]
        finally:
            page.unroute(url, intercept)
            self.exchange += 1
            self.proof('post-%02d' % self.exchange, {'path': PREFIX + suffix,
                'dropActualDelivery': drop, 'calls': calls})

    def preview(self, page, revoke=False):
        result = self.post(page, '/preview', lambda: button(page, '预览解除' if revoke else '预览归集').click())
        assert result['result']['unchanged'] == {'ledger': True, 'shopping': True, 'sharedTrip': True}
        expect(page.get_by_test_id('journey-finance-preview')).to_be_visible()
        return result

    def confirm(self, page, *, revoke=False, drop=False):
        result = self.post(page, '/confirm', lambda: button(page, '确认解除' if revoke else '确认归集').click(), drop=drop)
        if drop:
            expect(page.get_by_test_id('journey-finance-unknown')).to_be_visible(timeout=15000)
        else:
            expect(page.get_by_test_id('journey-finance-preview')).to_have_count(0, timeout=15000)
        return result

    def capture(self, page, name, width, target):
        page.set_viewport_size({'width': width, 'height': 1080 if width >= 1280 else 844})
        page.evaluate('() => document.fonts.ready')
        target.scroll_into_view_if_needed()
        page.wait_for_timeout(250)
        metrics = page.evaluate('''() => ({width:innerWidth,root:document.documentElement.scrollWidth,
          body:document.body.scrollWidth,clipped:[...document.querySelectorAll(
          '[data-testid="journey-finance-panel"] [role="button"],[data-testid="journey-finance-panel"] input')]
          .filter(n=>{const r=n.getBoundingClientRect();return r.width>0&&r.height>0&&r.bottom>0&&r.top<innerHeight
          &&(r.right>innerWidth+2||r.left< -2)}).map(n=>({label:n.getAttribute('aria-label')||n.textContent,
          box:n.getBoundingClientRect().toJSON()}))})''')
        assert metrics['root'] <= width + 2 and metrics['body'] <= width + 2 and not metrics['clipped'], metrics
        path = self.out / (name + '.png')
        page.screenshot(path=str(path), full_page=False)
        self.report['screenshots'].append({'path': path.relative_to(self.out.parent).as_posix(),
            'sha256': sha(path), 'metrics': metrics, 'scope': 'Actual visible viewport; no whole-page or physical-device claim'})

    def allocate_refund_source(self, browser):
        with self.flow(browser) as (ctx, page):
            journey = self.journey(ctx)
            payment = self.payment(ctx)
            order = self.payment(ctx, '合成同一住宿订单', kind='orders')
            self.reconciliation(ctx, 'order_payment', order, payment, '1000.00')
            shop = journey['shopping'][0]
            self.write(ctx, 'PATCH', '/api/items/shopping/' + shop['id'], {
                'revision': shop['revision'], 'actual': 30000, 'done': True})
            protected = self.protected()
            audit_before = self.audit_state()
            self.open_trip(page, journey)
            self.draft(page, payment, '700.00')
            preview = self.preview(page)['result']
            assert preview['afterAllocatedCents'] == 70000 and preview['payment']['netCents'] == 100000
            self.capture(page, 'private-allocation-preview', 390, button(page, '确认归集'))
            saved = self.confirm(page)
            allocation_id = saved['result']['receipt']['allocationId']
            self.audit_increment(audit_before, 'apply', allocation_id)
            current = self.allocations(ctx, journeyId=journey['id'])
            assert current['summary']['currentAllocatedCents'] == 70000
            assert current['summary']['sharedBudgetCents'] == 100000 and current['summary']['coverage'] == 'owner_partial'
            assert len(current['allocations']) == 1 and current['allocations'][0]['paymentId'] == payment['id']
            assert self.protected() == protected
            card = page.get_by_test_id('journey-allocation-' + allocation_id)
            expect(card).to_be_visible(timeout=15000)
            card.get_by_role('button', name='查看原付款', exact=True).click()
            original = page.get_by_test_id('journey-finance-original-payment')
            expect(original).to_be_visible(timeout=15000)
            expect(original).to_contain_text(payment['title'])
            assert self.get(ctx, '/api/finance-hub/reconciliation?' + urlencode({'transactionId': payment['id']}))['transaction']['id'] == payment['id']
            button(page, '返回旅行费用').click()
            expect(page.get_by_test_id('journey-allocation-' + allocation_id)).to_be_visible()
            rows = self.allocation_rows()
            journal_before_restart = len(self.http)
            self.restart()
            assert self.allocation_rows() == rows
            self.open_trip(page, journey)
            refund = self.payment(ctx, '合成跨月已确认退款', '400.00', flow='refund', day='2026-09-02')
            self.reconciliation(ctx, 'refund_payment', refund, payment, '400.00')
            self.open_trip(page, journey)
            drift = self.allocations(ctx, journeyId=journey['id'])
            assert drift['summary']['currentAllocatedCents'] == 0 and drift['summary']['needsReviewAllocatedCents'] == 70000
            assert drift['allocations'][0]['state'] == 'needs_review'
            protected_after_refund = self.protected()
            audit_after_refund = self.audit_state()
            card = page.get_by_test_id('journey-allocation-' + allocation_id)
            expect(card).to_contain_text('需核对')
            card.get_by_role('button', name='调整归集', exact=True).click()
            page.get_by_role('textbox', name='归集金额', exact=True).fill('600.00')
            self.preview(page)
            updated = self.confirm(page)['result']['receipt']
            assert updated['allocationId'] == allocation_id and updated['revision'] == 2
            self.audit_increment(audit_after_refund, 'update', allocation_id)
            final = self.allocations(ctx, journeyId=journey['id'])
            assert final['summary']['currentAllocatedCents'] == 60000 and final['summary']['needsReviewCount'] == 0
            assert self.protected() == protected_after_refund
            assert any(r['path'] == PREFIX + '/confirm' and r['status'] == 200 for r in self.http[journal_before_restart:])
            self.capture(page, 'refund-reconciled', 390, page.get_by_test_id('journey-finance-summary'))
            self.proof('authority-preserved', {'beforeAllocation': protected, 'afterRefund': protected_after_refund,
                'finalProtected': self.protected(), 'drift': drift, 'final': final})
            self.passed('Actual private payment allocation excludes order/shopping/manual-paid duplication, survives restart, opens original ID, and resolves later confirmed refund on the same allocation')

    def lost_confirmation_reload(self, browser):
        with self.flow(browser) as (ctx, page):
            page.set_viewport_size({'width': 1280, 'height': 1080})
            journey, payment = self.journey(ctx), self.payment(ctx)
            protected = self.protected()
            audit_before = self.audit_state()
            self.open_trip(page, journey)
            self.draft(page, payment, '300.00')
            self.preview(page)
            saved = self.confirm(page, drop=True)
            request_id = saved['payload']['requestId']
            committed_audit = self.audit_increment(audit_before, 'apply', saved['result']['receipt']['allocationId'])
            original_rows = self.allocation_rows()
            assert len(original_rows['hub_journey_allocations']) == len(original_rows['hub_journey_allocation_operations']) == 1
            self.capture(page, 'unknown-actual-commit', 1280, page.get_by_test_id('journey-finance-unknown'))
            # Re-entering the panel automatically queries the original receipt.
            # Observe that actual GET, rather than requiring an extra user click
            # or an unknown state that can already have resolved by this point.
            with page.expect_response(lambda response: urlsplit(response.url).path == PREFIX + '/operations/' + request_id
                                      and response.request.method == 'GET' and response.status == 200) as recovery:
                page.reload()
                if not page.get_by_test_id('journey-finance-panel').count():
                    button(page, '我的旅行费用').click()
            automatic = recovery.value.json()
            assert automatic['found'] and automatic['receipt'] == saved['result']['receipt']
            expect(page.get_by_test_id('journey-finance-unknown')).to_have_count(0, timeout=15000)
            expect(page.get_by_test_id('journey-finance-summary')).to_be_visible(timeout=15000)
            result = self.get(ctx, PREFIX + '/operations/' + request_id)
            assert result['found'] and result['receipt'] == saved['result']['receipt']
            assert self.allocation_rows() == original_rows and self.protected() == protected
            assert self.audit_state() == committed_audit
            assert self.count_requests('POST', PREFIX + '/confirm') == 1
            assert self.count_requests('GET', PREFIX + '/operations/' + request_id) >= 1
            self.capture(page, 'recovered-original-request', 1280, page.get_by_test_id('journey-finance-summary'))
            self.proof('same-original-request', {'requestId': request_id, 'receipt': result, 'automaticPageReceipt': automatic,
                'beforeRecovery': original_rows, 'afterRecovery': self.allocation_rows()})
            self.passed('Actual confirmed response is dropped, page reload restores the original request, GET recovery proves one persistent allocation and one operation with no second confirmation')

    def identity_offline_late_read(self, browser):
        with self.flow(browser) as (ctx, page):
            journey, payment = self.journey(ctx), self.payment(ctx)
            self.open_trip(page, journey)
            self.draft(page, payment, '12.34')
            ctx.set_offline(True)
            expect(page.get_by_test_id('journey-finance-summary')).to_have_count(0, timeout=15000)
            expect(page.locator('body')).not_to_contain_text(payment['title'])
            ctx.set_offline(False)
            self.settle(page, lambda: button(page, '预览归集').is_enabled())
            expect(page.get_by_role('textbox', name='归集金额', exact=True)).to_have_value('12.34')
            self.preview(page)
            saved = self.confirm(page)['result']['receipt']
            allocation_id = saved['allocationId']
            self.capture(page, 'owner-private-record', 390, page.get_by_test_id('journey-allocation-' + allocation_id))
            before = self.allocation_rows()
            held, url, holding = [], self.base + PREFIX + '*', True
            def hold(route):
                if not holding or route.request.method != 'GET' or urlsplit(route.request.url).path != PREFIX:
                    route.continue_(); return
                response = route.fetch(max_redirects=0)
                assert response.status == 200 and 'set-cookie' not in response.headers
                held.append((route, response.status, response.headers, response.body()))
            page.route(url, hold)
            try:
                page.reload()
                if not page.get_by_test_id('journey-finance-panel').count():
                    button(page, '我的旅行费用').click()
                self.settle(page, lambda: bool(held))
                assert any(any(a['id'] == allocation_id for a in json.loads(raw)['allocations']) for _, _, _, raw in held)
                expect(page.get_by_test_id('journey-allocation-' + allocation_id)).to_have_count(0)
                page.evaluate('''({id,title}) => {
                  const evidence = window.__journeyPrivacyEvidence = {violations:[]};
                  const check = () => {
                    if (document.querySelector('[data-testid="journey-allocation-'+id+'"]')
                        || document.body.textContent.includes(title))
                      evidence.violations.push({time:performance.now(),reason:'old-private-content-installed'});
                  };
                  window.__journeyPrivacyObserver = new MutationObserver(check);
                  window.__journeyPrivacyObserver.observe(document.body,
                    {subtree:true,childList:true,characterData:true,attributes:true});
                  check();
                }''', {'id': allocation_id, 'title': payment['title']})
                self.write(ctx, 'POST', '/api/logout', {})
                self.login(ctx, 2)
                pending = list(held)
                holding = False
                # Keep the interception registered until these captured routes
                # are fulfilled; removing it first can resume/handle a route.
                with page.expect_response(lambda response: urlsplit(response.url).path == '/api/me'
                    and response.request.method == 'GET' and response.status == 200
                    and response.json().get('user', {}).get('id') == 'member2') as fresh:
                    for entry in pending:
                        route, status, headers, raw = entry
                        route.fulfill(status=status, headers=headers, body=raw)
                        held.remove(entry)
                page_session = fresh.value.json()
                assert page_session['user']['id'] == 'member2'
                self.proof('held-real-owner-response', {'responses': [json.loads(raw) for _, _, _, raw in pending],
                    'deliveredAfterMemberSwitch': True})
                # Positive rendered completion: AppShell receives the new
                # provider identity, rather than treating an already-empty
                # loading panel as proof that the stale response was handled.
                expect(button(page, page_session['user']['name'] + '，账户菜单')).to_be_visible(timeout=15000)
                expect(page.locator('body')).not_to_contain_text(payment['title'])
                expect(page.get_by_test_id('journey-allocation-' + allocation_id)).to_have_count(0)
                observation = page.evaluate('''() => {
                  window.__journeyPrivacyObserver.disconnect();
                  return window.__journeyPrivacyEvidence;
                }''')
                assert observation['violations'] == []
                self.proof('page-identity-completion', {'pageMeStatus': fresh.value.status,
                    'pageUserId': page_session['user']['id'], 'renderedNewAccountMenu': True,
                    'mutationObservation': observation})
                own = self.allocations(ctx, journeyId=journey['id'])
                assert own['allocations'] == [] and own['summary']['currentAllocatedCents'] == 0
                receipt = self.get(ctx, PREFIX + '/operations/' + saved['requestId'])
                assert receipt['found'] is False and receipt['receipt'] is None
                assert self.get(ctx, '/api/me')['user']['id'] == 'member2'
                assert self.allocation_rows() == before
                assert self.count_requests('POST', PREFIX + '/confirm') == 1
                self.open_trip(page, journey)
                expect(page.locator('body')).not_to_contain_text(payment['title'])
                self.capture(page, 'other-member-empty', 390, page.get_by_test_id('journey-finance-summary'))
                self.proof('owner-boundary', {'otherMemberList': own, 'otherMemberReceipt': receipt,
                    'before': before, 'after': self.allocation_rows()})
            finally:
                for route, *_ in held:
                    route.abort('failed')
                page.unroute(url, hold)
            self.passed('Offline conceals private draft and same identity recovers it; delayed actual reads after real member switch cannot reveal another owner allocation or receipt')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--expected-build-evidence', required=True)
    parser.add_argument('--temp-root', required=True, type=Path)
    parser.add_argument('--case', action='append', choices=CASES, dest='cases')
    args = parser.parse_args()
    if not sys.dont_write_bytecode or sys.flags.optimize:
        raise RuntimeError('Run with -B and without Python optimization')
    assert re.fullmatch('[a-f0-9]{40}', args.expected_head) and re.fullmatch('[a-f0-9]{64}', args.expected_build_evidence)
    root, temp_root = args.source_root.resolve(), args.temp_root.resolve()
    bundle = args.bundle.absolute()
    if os.name == 'nt' and not str(bundle).startswith('\\\\?\\'):
        bundle = Path('\\\\?\\' + str(bundle))
    assert temp_root.is_dir() and not temp_root.is_symlink() and not temp_root.is_junction()
    def git(*command):
        return subprocess.check_output(['git', '--no-replace-objects', *command], cwd=root).decode('utf-8').strip()
    head, tree = git('rev-parse', 'HEAD'), git('rev-parse', 'HEAD^{tree}')
    assert head == args.expected_head and not git('status', '--porcelain=v1')
    assert Path(__file__).resolve() == (root / HARNESS).resolve()
    evidence_path = bundle.parent / 'build-evidence.json'
    assert sha(evidence_path) == args.expected_build_evidence
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    names = git('ls-files', '-z').rstrip('\0').split('\0')
    fixture.validate_build(git, root, head, evidence, names)
    assert fixture.exports(bundle) == evidence['files']
    def hashes(): return {name: sha(root / name) for name in names}
    cases = tuple(dict.fromkeys(args.cases or CASES))
    out = root / 'test-results' / ('journey-finance-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], screenshots=[], pageErrors=[], externalRequests=[], artifacts=[],
        scenarioResults=[], scenarioFailures=[], requestedCases=list(cases), head=head, tree=tree,
        buildSourceHead=head, buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(Path(__file__)),
        sourceHashesBefore=hashes(), bundleHashesBefore=fixture.exports(bundle), productionWrites=0,
        realFinancialData=False, realCloud=False, physicalTelevision=False,
        scope='Requested synthetic journey/payment/confirmed-refund browser flows using real Flask, SQLite, HTTPS and Edge. '
              'Frozen source/build; only actual responses held or dropped; no substituted business success.')
    original_connect = socket.socket.connect
    def local_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
            report['externalRequests'].append({'kind': 'non-loopback socket'})
            raise AssertionError('External network forbidden')
        return original_connect(sock, address)
    try:
        with patch.object(socket.socket, 'connect', local_connect), sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            try:
                Run.run_scenarios(root, bundle, report, out, browser, temp_root, cases)
                assert len(report['checks']) == len(cases) and len(report['screenshots']) == len(cases) * 2
                assert [c['name'] for c in report['scenarioResults']] == list(cases)
                assert not report['pageErrors'] and not report['externalRequests']
                report['passed'] = True
            finally:
                browser.close()
    except Exception:
        report['passed'] = False
        report['failure'] = traceback.format_exc(); print(report['failure'], flush=True)
    finally:
        try:
            report['sourceHashesAfter'], report['bundleHashesAfter'] = hashes(), fixture.exports(bundle)
            report['sourceUnchanged'] = report['sourceHashesBefore'] == report['sourceHashesAfter']
            report['bundleUnchanged'] = report['bundleHashesBefore'] == report['bundleHashesAfter']
            report['fixtureHashesAfter'] = {name: sha(root / name) for name in report.get('fixtureHashes', {})}
            report['fixturesUnchanged'] = bool(report.get('fixtureHashes')) and report['fixtureHashesAfter'] == report['fixtureHashes']
            report['journeyFixtureHashesAfter'] = {name: sha(root / name) for name in report.get('journeyFixtureHashes', {})}
            report['journeyFixturesUnchanged'] = bool(report.get('journeyFixtureHashes')) and report['journeyFixtureHashesAfter'] == report['journeyFixtureHashes']
            report['sourceStillFrozen'] = git('rev-parse', 'HEAD') == head and not git('status', '--porcelain=v1')
            report['temporaryFixturesRemoved'] = len(report['scenarioResults']) == len(cases) and all(
                c['temporaryFixtureRemoved'] and c['listenerStopped'] for c in report['scenarioResults'])
            report['passed'] = report['passed'] and all(report[k] for k in ('sourceUnchanged', 'bundleUnchanged',
                'fixturesUnchanged', 'journeyFixturesUnchanged', 'sourceStillFrozen', 'temporaryFixturesRemoved')) and not (
                report['pageErrors'] or report['externalRequests'])
        except Exception:
            report['passed'] = False; report['finalEvidenceFailure'] = traceback.format_exc()
        fixture.write_json(out / 'result.json', report)
        print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'report': str(out / 'result.json')}, ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
