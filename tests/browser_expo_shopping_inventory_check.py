"""Five bounded shopping/inventory/Home flows on real isolated Flask/SQLite/Edge.

Run only after review, with an explicit frozen source and original Expo build
evidence. Synthetic setup uses real APIs; fault injection drops a real committed
response. No substituted business responses, production data or external calls.
"""
import argparse
from contextlib import ExitStack, closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import traceback
from unittest.mock import patch
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright
import browser_expo_memberships_check as fixture
from browser_expo_finance_check import row, sha
from browser_expo_memberships_check import file_manifest

AUTHOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AUTHOR))
from deploy.git_blobs import read_git_blobs

CASES = ('existing_receive_return', 'new_item_cancel', 'lost_movement_response',
         'partner_privacy_revocation', 'home_edit_cancel_conflict')
P = '/api/inventory'
INVENTORY = ('inventory_items', 'inventory_acquisitions', 'inventory_movements',
             'inventory_operations', 'inventory_source_links')


def button(page, name):
    # Paper's decorative icon enters the actual accessible name when no explicit
    # label is supplied. Permit one PUA icon plus space; keep the text exact.
    icon = r'(?:[\ue000-\uf8ff\U000f0000-\U000ffffd\U00100000-\U0010fffd]\s+)?'
    return page.get_by_role('button', name=re.compile('^' + icon + re.escape(name) + '$'))


def fill(page, label, value):
    page.get_by_role('textbox', name=label, exact=True).fill(str(value))


class Run(fixture.Run):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        path = Path(fixture.__file__).resolve()
        name = 'tests/browser_expo_memberships_check.py'
        assert sha(path) == sha(self.root / name)
        inherited = {'path': str(path), 'sourcePath': name, 'sha256': sha(path)}
        assert self.report.setdefault('inheritedFixture', inherited) == inherited

    def table_rows(self, names):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database.as_uri() + '?mode=ro', uri=True)) as con:
            return {name: sorted(con.execute('SELECT * FROM "' + name + '"').fetchall(), key=repr)
                    for name in names}

    def protected(self):
        result = self.table_rows(('hub_transactions', 'hub_imports', 'hub_import_receipts',
            'hub_reconciliations', 'hub_budgets', 'hub_investments', 'private_finance',
            'finance_baselines', 'hub_shopping_settlements', 'hub_shopping_settlement_receipts'))
        with closing(sqlite3.connect(self.database.as_uri() + '?mode=ro', uri=True)) as con:
            result['shopping_and_trips'] = con.execute(
                "SELECT * FROM entities WHERE kind IN ('shopping','trips') ORDER BY id").fetchall()
            result['finance'] = con.execute("SELECT * FROM settings WHERE id='finance'").fetchall()
        return result

    def screenshot(self, page, name, width, dialog=False):
        super().screenshot(page, name, width, dialog)
        self.report['screenshots'][-1]['path'] = self.out.name + '/' + self.report['screenshots'][-1]['path']

    def setup(self, ctx, title='合成采购电池', *, done=False):
        self.seed(ctx, [row('合成私密付款哨兵', '137.29')])
        self.write(ctx, 'POST', '/api/items/trips', {'title': '合成旅行哨兵', 'destination': '合成地点',
            'start': '2026-09-20', 'end': '2026-09-22', 'budget': 99900, 'saved': 20000, 'paid': 12345}, 201)
        shop = self.write(ctx, 'POST', '/api/items/shopping', {'title': title, 'owner': 'shared',
            'quantity': '一盒约六节（请核对）', 'done': done, 'budget': 19800, 'actual': 13729,
            'note': '采购、财务和旅行数据不随实物登记改变'}, 201)
        self.protected_before = self.protected()
        return next(item for item in self.get(ctx, '/api/state')['shopping'] if item['id'] == shop['id'])

    def finish_case(self, name):
        assert self.protected() == self.protected_before, 'Shopping/finance/trip sentinel changed'
        self.report.setdefault('protectedUnchanged', []).append(self.out.name)
        self.passed(name)

    def create_item(self, ctx, title='合成已有电池', visibility='private'):
        return self.write(ctx, 'POST', P + '/items', {'requestId': secrets.token_hex(16),
            'data': {'title': title, 'unit': '节', 'visibility': visibility}}, 201)['item']

    def create_batch(self, ctx, item, shop):
        return self.write(ctx, 'POST', P + '/items/' + item['id'] + '/acquisitions', {
            'requestId': secrets.token_hex(16), 'itemRevision': item['revision'],
            'data': {'kind': 'purchase', 'orderedQty': 6, 'orderState': 'in_transit',
                     'shoppingId': shop['id']}}, 201)

    def linked(self, ctx, shop):
        return self.get(ctx, P + '/shopping/' + shop['id'] + '/acquisitions?limit=12&offset=0')

    def open_source(self, page, shop, *, filtered=False):
        page.goto(self.base + '/app/shopping')
        expect(button(page, '添加采购')).to_be_enabled(timeout=20000)
        if filtered or shop['done']:
            button(page, '已买到').click()
        if filtered:
            page.get_by_placeholder('搜索物品', exact=True).fill(shop['title'])
        button(page, '登记或查看库存：' + shop['title']).click()
        self.source_ready(page)

    @staticmethod
    def source_ready(page):
        expect(page.get_by_role('heading', name='这次采购的库存', exact=True)).to_be_visible(timeout=20000)
        expect(button(page, '刷新物品')).to_be_enabled(timeout=20000)

    def select_existing(self, page, item):
        button(page, '选择已有物品').click()
        button(page, '选择物品 ' + item['title']).click()
        expect(page.get_by_role('textbox', name='批次数量', exact=True)).to_have_value('')
        expect(page.get_by_text('计量单位：节。请按这个单位填写本批数量，再点击“保存批次”确认。', exact=True)).to_be_visible()

    def save_batch(self, page, item):
        fill(page, '批次数量', 6)
        page.get_by_role('radio', name='运输中', exact=True).click()
        result, payload = self.actual(page, 'POST', P + '/items/' + item['id'] + '/acquisitions',
                                      lambda: button(page, '保存批次').click(), 201)
        expect(button(page, '收货')).to_be_enabled()
        assert result['item']['onHandQty'] == 0 and result['acquisition']['receivedQty'] == 0
        assert payload['data']['orderedQty'] == 6
        return result

    @staticmethod
    def movement_draft(page, kind, quantity):
        if kind == 'receive':
            button(page, '收货').click()
        else:
            page.get_by_text('更多实物操作', exact=True).click()
            button(page, '记录退回').click()
        fill(page, '本次数量', quantity)
        fill(page, '操作原因', '合成已核对实物')
        checkbox = page.get_by_role('checkbox', name='我已核对实际物品和数量', exact=True)
        checkbox.focus()
        checkbox.press('Space')
        expect(checkbox).to_be_checked()

    def movement(self, page, acquisition, kind, quantity):
        self.movement_draft(page, kind, quantity)
        result, _ = self.actual(page, 'POST', P + '/acquisitions/' + acquisition['id'] + '/movements',
                                lambda: button(page, '确认实物变动').click())
        expect(button(page, '收货')).to_be_enabled()
        return result

    @staticmethod
    def cancel(page):
        button(page, '取消编辑').click()
        button(page, '放弃这次编辑').click()
        expect(button(page, '返回原采购')).to_be_enabled()

    def existing_receive_return(self, browser):
        with self.flow(browser) as (ctx, page):
            self.stage('Select existing item; explicitly enter quantity, then receive 2 + 4 and return 1')
            shop = self.setup(ctx, done=True)
            item = self.create_item(ctx)
            self.open_source(page, shop, filtered=True)
            self.select_existing(page, item)
            result = self.save_batch(page, item)
            batch = result['acquisition']
            assert batch['shoppingId'] == shop['id']
            first = self.movement(page, batch, 'receive', 2)
            assert (first['item']['onHandQty'], first['acquisition']['remainingExpectedQty']) == (2, 4)
            self.movement(page, batch, 'receive', 4)
            result = self.movement(page, batch, 'return', 1)
            assert (result['item']['onHandQty'], result['acquisition']['receivedQty'],
                    result['acquisition']['returnedQty'], result['acquisition']['remainingExpectedQty']) == (5, 6, 1, 0)
            expect(page.get_by_text('剩余待收 0 节', exact=True)).to_be_visible()
            self.screenshot(page, 'receive-return', 390)
            button(page, '返回原采购').click()
            expect(page.get_by_placeholder('搜索物品', exact=True)).to_have_value(shop['title'])
            expect(button(page, '已买到')).to_have_attribute('aria-checked', 'true')
            target = page.get_by_test_id('shopping-item-' + shop['id'])
            expect(target).to_be_focused()
            button(page, '登记或查看库存：' + shop['title']).click()
            self.source_ready(page)
            button(page, '处理关联批次 ' + batch['id']).click()
            expect(button(page, '收货')).to_be_enabled()
            assert self.linked(ctx, shop)['total'] == 1
            assert len(self.table_rows(INVENTORY)['inventory_movements']) == 3
            self.stage('Stop/start the actual Flask server and reopen the persisted original batch')
            path = P + '/acquisitions/' + batch['id']
            before_restart = self.get(ctx, path)
            inventory_before = self.table_rows(INVENTORY)
            self.restart()
            reauthenticated = self.get(ctx, '/api/me')['user'] is None
            if reauthenticated:
                self.login(ctx)
            self.open_source(page, shop, filtered=True)
            button(page, '处理关联批次 ' + batch['id']).click()
            expect(button(page, '收货')).to_be_enabled()
            expect(page.get_by_text('剩余待收 0 节', exact=True)).to_be_visible()
            persisted = self.get(ctx, path)
            assert persisted == before_restart and persisted['acquisition']['id'] == batch['id']
            assert (persisted['item']['onHandQty'], persisted['acquisition']['receivedQty'],
                    persisted['acquisition']['returnedQty'], persisted['acquisition']['remainingExpectedQty']) == (5, 6, 1, 0)
            assert self.table_rows(INVENTORY) == inventory_before
            assert self.get(ctx, path + '/movements')['total'] == 3
            self.report['inventoryRestart'] = {'actualFlaskRestart': True, 'reauthenticated': reauthenticated,
                'sameBatchId': True, 'inventoryTablesUnchanged': True, 'movementCount': 3}
            self.finish_case('existing item receives 2+4, returns 1, stock 5 / outstanding 0; filtered return, re-entry and real restart persistence')

    def new_item_cancel(self, browser):
        with self.flow(browser) as (ctx, page):
            self.stage('New private item, explicit batch continuation, and cancellation boundaries')
            shop = self.setup(ctx, '合成新购收纳盒')
            self.open_source(page, shop)
            before = self.table_rows(INVENTORY)
            button(page, '新建物品并登记').click()
            expect(page.get_by_role('textbox', name='物品名称', exact=True)).to_have_value(shop['title'])
            expect(page.get_by_role('radio', name='仅本人可见', exact=True)).to_be_checked()
            fill(page, '物品名称', '不应保存的草稿')
            expect(button(page, '返回原采购')).to_be_disabled()
            self.cancel(page)
            assert self.table_rows(INVENTORY) == before
            button(page, '新建物品并登记').click()
            result, _ = self.actual(page, 'POST', P + '/items', lambda: button(page, '保存物品').click(), 201)
            item = result['item']
            expect(page.get_by_role('textbox', name='批次数量', exact=True)).to_have_value('')
            assert item['visibility'] == 'private' and item['onHandQty'] == 0
            assert self.linked(ctx, shop)['total'] == 0
            before = self.table_rows(INVENTORY)
            fill(page, '批次数量', 3)
            self.screenshot(page, 'new-item-batch-draft', 390)
            self.cancel(page)
            assert self.table_rows(INVENTORY) == before, 'Cancel must not save a batch or undo an already saved item'
            button(page, '返回原采购').click()
            button(page, '登记或查看库存：' + shop['title']).click()
            self.source_ready(page)
            assert self.linked(ctx, shop)['total'] == 0
            self.finish_case('new item defaults private; item and batch cancellations write nothing; saved item retained')

    def lost_movement_response(self, browser):
        with self.flow(browser) as (ctx, page):
            self.stage('Drop only the actual committed receipt, then recover once using its original requestId')
            shop = self.setup(ctx)
            item = self.create_item(ctx)
            batch = self.create_batch(ctx, item, shop)['acquisition']
            page.set_viewport_size({'width': 1280, 'height': 1000})
            self.open_source(page, shop)
            button(page, '处理关联批次 ' + batch['id']).click()
            path = P + '/acquisitions/' + batch['id'] + '/movements'
            dropped, submitted = {}, []
            def record(request):
                if request.method == 'POST' and urlsplit(request.url).path == path:
                    submitted.append(request.post_data_json['requestId'])
            def drop(handler):
                if handler.request.method != 'POST' or dropped:
                    handler.continue_()
                    return
                response = handler.fetch()
                assert response.status == 200, response.text()
                dropped.update(requestId=handler.request.post_data_json['requestId'], result=response.json())
                handler.abort('failed')
            page.on('request', record)
            pattern = '**' + path
            page.route(pattern, drop)
            self.movement_draft(page, 'receive', 2)
            button(page, '确认实物变动').click()
            expect(button(page, '核对并重试本次操作')).to_be_enabled()
            expect(button(page, '返回原采购')).to_be_disabled()
            button(page, '日程').click()
            expect(page.get_by_text('请先核对本次库存操作的结果，再离开。', exact=True)).to_be_visible()
            expect(page).to_have_url(self.base + '/app/shopping')
            expect(page.get_by_role('textbox', name='本次数量', exact=True)).to_have_value('2')
            assert dropped['result']['item']['onHandQty'] == 2
            self.screenshot(page, 'unknown-result', 1280)
            receipt, _ = self.actual(page, 'GET', P + '/operations/' + dropped['requestId'],
                                     lambda: button(page, '核对并重试本次操作').click())
            expect(button(page, '收货')).to_be_enabled()
            page.unroute(pattern, drop)
            assert submitted == [dropped['requestId']] and receipt['operation']['replayed']
            assert self.get(ctx, path)['total'] == 1
            with closing(sqlite3.connect(self.database.as_uri() + '?mode=ro', uri=True)) as con:
                for table in ('inventory_operations', 'inventory_movements'):
                    assert con.execute('SELECT count(*) FROM ' + table + ' WHERE request_id=?',
                                       (dropped['requestId'],)).fetchone()[0] == 1
            self.report['droppedResponse'] = {'realServerCommit': True, 'requestId': dropped['requestId'],
                                             'postCount': len(submitted), 'movementCount': 1}
            self.finish_case('real committed response loss locks navigation; original receipt recovery creates no duplicate movement')

    def partner_privacy_revocation(self, browser):
        with self.flow(browser) as (owner, _page):
            self.stage('Partner cannot see private linked inventory; shared detail disappears after withdrawal')
            shop = self.setup(owner)
            private = self.create_item(owner, '合成只属于本人的物品')
            private_batch = self.create_batch(owner, private, shop)['acquisition']
            shared = self.create_item(owner, '合成共享后撤回物品', 'shared')
            saved = self.create_batch(owner, shared, shop)
            partner = self.context(browser, 2)
            try:
                page = partner.new_page()
                self.page = page
                self.open_source(page, shop)
                linked = self.linked(partner, shop)
                assert linked['total'] == 1 and linked['items'][0]['item']['id'] == shared['id']
                expect(button(page, '处理关联批次 ' + private_batch['id'])).to_have_count(0)
                expect(page.get_by_text(private['title'], exact=True)).to_have_count(0)
                button(page, '处理关联批次 ' + saved['acquisition']['id']).click()
                expect(button(page, '收货')).to_be_enabled()
                button(page, '收货').click()
                fill(page, '本次数量', 1)
                self.write(owner, 'PATCH', P + '/items/' + shared['id'], {'requestId': secrets.token_hex(16),
                    'revision': saved['item']['revision'], 'patch': {'visibility': 'private'}})
                before = self.table_rows(INVENTORY)
                # Foreground explicitly rechecks the real identity and permissions.
                fixture.visibility(page, True)
                fixture.visibility(page, False)
                expect(page.get_by_text('这件物品已归档或不再对你可见，旧详情和草稿已清空。', exact=True)).to_be_visible()
                expect(page.get_by_role('textbox', name='本次数量', exact=True)).to_have_count(0)
                expect(page.get_by_text(shared['title'], exact=True)).to_have_count(0)
                assert self.linked(partner, shop)['total'] == 0
                assert self.table_rows(INVENTORY) == before
                self.get(partner, P + '/acquisitions/' + saved['acquisition']['id'], 404)
                self.finish_case('private item and count hidden from partner; withdrawn share clears draft/details without writes')
            finally:
                partner.close()

    def home_edit_cancel_conflict(self, browser):
        with self.flow(browser) as (ctx, page):
            self.stage('Home edit uses the existing task editor: owner/date save, cancel and actual 409')
            self.setup(ctx)
            task = self.write(ctx, 'POST', '/api/items/tasks', {'title': '合成首页待办',
                'owner': 'shared', 'done': False, 'due': '2026-01-01'}, 201)
            state = self.get(ctx, '/api/state')
            task = next(t for t in state['tasks'] if t['id'] == task['id'])
            other = next(person for person in state['people'] if person['id'] != self.get(ctx, '/api/me')['user']['id'])
            page.set_viewport_size({'width': 1280, 'height': 1000})
            page.goto(self.base + '/app')
            edit = '编辑待办：' + task['title']
            expect(button(page, edit)).to_be_enabled(timeout=20000)
            button(page, edit).click()
            button(page, other['name']).click()
            page.get_by_text('更多选项', exact=True).click()
            fill(page, '截止日期（YYYY-MM-DD，可选）', '2026-01-02')
            self.actual(page, 'PATCH', '/api/items/tasks/' + task['id'], lambda: button(page, '保存').click())
            expect(button(page, edit)).to_be_enabled()
            fresh = next(t for t in self.get(ctx, '/api/state')['tasks'] if t['id'] == task['id'])
            assert fresh['owner'] == other['id'] and fresh['due'] == '2026-01-02' and not fresh['done']
            self.screenshot(page, 'home-edited', 1280)
            button(page, edit).click()
            fill(page, '名称', '取消的待办草稿')
            button(page, '取消').click()
            expect(button(page, edit)).to_be_enabled()
            assert next(t for t in self.get(ctx, '/api/state')['tasks'] if t['id'] == task['id']) == fresh
            button(page, edit).click()
            fill(page, '名称', '冲突时保留的草稿')
            self.write(ctx, 'PATCH', '/api/items/tasks/' + task['id'], {**fresh, 'note': '另一个真实写入', 'due': '2026-01-03'})
            self.actual(page, 'PATCH', '/api/items/tasks/' + task['id'], lambda: button(page, '保存').click(), 409)
            expect(page.get_by_text('这条记录已更新。你的输入仍在，请关闭后重新打开最新记录。', exact=True)).to_be_visible()
            expect(page.get_by_role('textbox', name='名称', exact=True)).to_have_value('冲突时保留的草稿')
            button(page, '取消').click()
            latest = next(t for t in self.get(ctx, '/api/state')['tasks'] if t['id'] == task['id'])
            assert latest['title'] == task['title'] and latest['due'] == '2026-01-03'
            self.finish_case('Home owner/due edit saves; cancel does not write; concurrent 409 preserves draft and newer record')


def run_case(name, root, bundle, report, out, browser):
    folder = None
    case_out = out / name
    case_out.mkdir()
    before = tuple(len(report[k]) for k in ('checks', 'pageErrors', 'externalRequests'))
    case = {'name': name, 'passed': False, 'temporaryFixtureRemoved': False}
    try:
        with ExitStack() as lifecycle:
            folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='si-')))
            run = Run(root, bundle, folder, report, case_out, lifecycle)
            getattr(run, name)(browser)
        assert not folder.exists()
        assert tuple(len(report[k]) for k in ('checks', 'pageErrors', 'externalRequests')) == (before[0] + 1, before[1], before[2])
        case['passed'] = True
    except Exception:
        del report['checks'][before[0]:]
        failure = traceback.format_exc()
        (case_out / 'failure.txt').write_text(failure, encoding='utf-8')
        report['scenarioFailures'].append({'scenario': name, 'traceback': failure})
        print('FAIL ' + name + '\n' + failure, flush=True)
    finally:
        case['temporaryFixtureRemoved'] = folder is not None and not folder.exists()
        report['scenarioResults'].append(case)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--build-evidence', required=True, type=Path)
    parser.add_argument('--expected-build-evidence', required=True)
    parser.add_argument('--scenario', choices=('all', 'shopping', *CASES), default='all')
    args = parser.parse_args()
    selected = CASES if args.scenario == 'all' else CASES[:4] if args.scenario == 'shopping' else (args.scenario,)
    root, bundle, evidence_path = args.source_root.resolve(), args.bundle.resolve(), args.build_evidence.resolve()
    assert sys.dont_write_bytecode and not sys.flags.optimize
    assert re.fullmatch('[a-f0-9]{40}', args.expected_head) and re.fullmatch('[a-f0-9]{64}', args.expected_build_evidence)
    def git(where, *command):
        return subprocess.check_output(['git', '--no-replace-objects', '--no-optional-locks', *command], cwd=where, text=True).strip()
    def tracked(commit):
        return set(git(root, 'ls-tree', '-r', '--name-only', commit).splitlines())
    head, author_head = git(root, 'rev-parse', 'HEAD'), git(AUTHOR, 'rev-parse', 'HEAD')
    assert head == args.expected_head and not git(root, 'status', '--porcelain=v1') and not git(AUTHOR, 'status', '--porcelain=v1')
    script_name = 'tests/browser_expo_shopping_inventory_check.py'
    assert read_git_blobs(AUTHOR, author_head, [script_name])[script_name] == Path(__file__).read_bytes()
    assert sha(evidence_path) == args.expected_build_evidence
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    assert evidence['buildExit'] == 0 and evidence['bundleMarkers'] is True
    assert git(root, 'rev-parse', evidence['head'] + '^{tree}') == evidence['tree']
    subprocess.run(['git', '--no-replace-objects', 'merge-base', '--is-ancestor', evidence['head'], head], cwd=root, check=True)
    inputs = evidence['inputFiles']
    for commit in (evidence['head'], head):
        expected = {n for n in tracked(commit) if n.startswith('frontend/')
                    and n not in {'frontend/README.md', 'frontend/LICENSE', 'frontend/.gitignore'}}
        assert set(inputs) == expected, 'Incomplete Expo input manifest'
        assert {n: hashlib.sha256(b).hexdigest() for n, b in read_git_blobs(root, commit, inputs).items()} == inputs
    assert {name: sha(root / name) for name in inputs} == inputs
    assert file_manifest(bundle) == evidence['files'] and evidence['files']
    names = tracked(head)
    def hashes():
        return {name: sha(root / name) for name in sorted(names)}
    before = hashes()
    assert before == {n: hashlib.sha256(b).hexdigest() for n, b in read_git_blobs(root, head, names).items()}
    out = AUTHOR / 'test-results' / ('expo-shopping-inventory-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], stages=[], pageErrors=[], externalRequests=[], screenshots=[], scenarioResults=[], scenarioFailures=[],
        head=head, tree=git(root, 'rev-parse', 'HEAD^{tree}'), buildHead=evidence['head'], buildTree=evidence['tree'], buildInputs=inputs,
        buildKind=evidence.get('kind'), buildEvidencePath=str(evidence_path), buildEvidenceSha256=sha(evidence_path),
        harnessHead=author_head, harnessSha256=sha(out / 'executed-harness.py'), sourceRoot=str(root), bundleRoot=str(bundle),
        sourceHashesBefore=before, bundleHashesBefore=file_manifest(bundle), productionWrites=0, realFinancialData=False,
        realCloud=False, physicalDevice=False, requestedScenarios=list(selected), fullSuite=args.scenario == 'all')
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
                for name in selected:
                    run_case(name, root, bundle, report, out, browser)
                assert not report['scenarioFailures'] and len(report['checks']) == len(selected)
                assert not report['pageErrors'] and not report['externalRequests']
                if args.scenario == 'all':
                    assert len(report['screenshots']) == 4
                report['passed'] = True
            finally:
                browser.close()
    except Exception:
        report['failure'] = traceback.format_exc()
        print(report['failure'], flush=True)
    finally:
        report['sourceHashesAfter'], report['bundleHashesAfter'] = hashes(), file_manifest(bundle)
        report['sourceUnchanged'] = report['sourceHashesBefore'] == report['sourceHashesAfter']
        report['bundleUnchanged'] = report['bundleHashesBefore'] == report['bundleHashesAfter']
        report['buildEvidenceUnchanged'] = sha(evidence_path) == args.expected_build_evidence
        report['fixturesUnchanged'] = bool(report.get('fixtureHashes')) and all(
            sha(Path(path)) == report['fixtureHashes'][name] == sha(root / name)
            for name, path in report.get('fixtureActualPaths', {}).items())
        inherited = report.get('inheritedFixture')
        report['inheritedFixtureUnchanged'] = bool(inherited) and sha(Path(inherited['path'])) == inherited['sha256'] == sha(root / inherited['sourcePath'])
        report['sourceStillFrozen'] = git(root, 'rev-parse', 'HEAD') == head and not git(root, 'status', '--porcelain=v1')
        report['harnessStillFrozen'] = git(AUTHOR, 'rev-parse', 'HEAD') == author_head and not git(AUTHOR, 'status', '--porcelain=v1') and sha(Path(__file__)) == report['harnessSha256']
        report['temporaryFixtureRemoved'] = len(report['scenarioResults']) == len(selected) and all(c['temporaryFixtureRemoved'] for c in report['scenarioResults'])
        report['passed'] = report['passed'] and all(report[k] for k in ('sourceUnchanged', 'bundleUnchanged',
            'buildEvidenceUnchanged', 'fixturesUnchanged', 'inheritedFixtureUnchanged', 'sourceStillFrozen', 'harnessStillFrozen', 'temporaryFixtureRemoved'))
        with (out / 'result.json').open('x', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'report': str(out / 'result.json')}), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
