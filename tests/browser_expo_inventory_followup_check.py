"""Four real, isolated after-sales-to-household-task browser acceptance cases.

Compile/review this harness first. Execute only with an explicit frozen source
and its original Expo build evidence. Inherit the reviewed shopping/membership/
finance fixture; never replace business endpoints or manufacture success.
"""
import argparse
from collections import Counter
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
import browser_expo_shopping_inventory_check as shopping

AUTHOR = Path(__file__).resolve().parents[1]
button, fill, sha = shopping.button, shopping.fill, shopping.sha
file_manifest, read_git_blobs = shopping.file_manifest, shopping.read_git_blobs
P, INVENTORY = shopping.P, shopping.INVENTORY
CASES = ('private_task_lifecycle', 'lost_create_response',
         'partner_conflict_deleted', 'private_link_revocation')
SCREENSHOT_COUNTS = dict(zip(CASES, (2, 2, 1, 0)))
TITLE = '售后待办标题'
DUE = '待办截止日（可选，YYYY-MM-DD）'
NOTE = '待办备注（可选，共享）'
DELETED = '这条售后待办已删除，关联历史保留，不会自动补建。'
PRIVATE_TITLE = '合成私密设备名称不应进入家庭任务'
PRIVATE_NOTE = '合成私密批次备注不应进入家庭任务'
TASK_FIELDS = {'title', 'owner', 'due', 'done', 'note', 'tripId'}


def fixture_bindings(root):
    """Check actually imported helper bytes before any inherited fixture starts."""
    modules = {'tests/browser_expo_shopping_inventory_check.py': shopping,
               'tests/browser_expo_memberships_check.py': shopping.fixture,
               'tests/browser_expo_finance_check.py': shopping.fixture.fixture,
               'deploy/git_blobs.py': sys.modules['deploy.git_blobs']}
    result = {}
    for name, module in modules.items():
        actual = Path(module.__file__).resolve()
        digest = sha(actual)
        assert digest == sha(root / name), 'Imported fixture differs from frozen source: ' + name
        result[name] = {'path': str(actual), 'sha256': digest}
    # BaseRun imports these from the supplied source. Reject cached substitutes
    # before construction, then its own fixtureHashes verifies the resolved files.
    for name in ('app', 'test_financial_files', 'test_app'):
        if name in sys.modules:
            relative = name + '.py' if name == 'app' else 'tests/' + name + '.py'
            assert Path(sys.modules[name].__file__).resolve() == (root / relative).resolve()
    return result


class Run(shopping.Run):
    def __init__(self, root, bundle, folder, report, out, lifecycle):
        bindings = fixture_bindings(root)
        assert report.setdefault('followupFixtureBindings', bindings) == bindings
        self.api_requests = []
        super().__init__(root, bundle, folder, report, out, lifecycle)
        self.schema_before = self.schema()

    def get(self, ctx, path, status=200):
        value = super().get(ctx, path, status)
        self.api_requests.append({'method': 'GET', 'path': path, 'status': status})
        return value

    def write(self, ctx, method, path, body, status=200):
        value = super().write(ctx, method, path, body, status)
        self.api_requests.append({'method': method, 'path': path, 'status': status})
        return value

    def query(self, sql, parameters=()):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database.as_uri() + '?mode=ro', uri=True)) as con:
            return con.execute(sql, parameters).fetchall()

    def schema(self):
        return {'objects': self.query('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name'),
                'version': self.query('PRAGMA user_version')}

    def tasks(self):
        return {identifier: {'revision': revision, 'data': json.loads(data)}
                for identifier, revision, data in self.query(
                    "SELECT id,revision,data FROM entities WHERE kind='tasks' ORDER BY id")}

    def no_write_snapshot(self):
        return {'inventory': self.table_rows(INVENTORY), 'tasks': self.tasks(),
                'audit_settings': self.table_rows(('audit', 'settings'))}

    def physical(self, ctx, acquisition_id):
        value = self.get(ctx, P + '/acquisitions/' + acquisition_id)
        # Only revision/timestamp and permission projections can change with an
        # explicit task association. Compare every remaining business field.
        ignored = {'revision', 'itemRevision', 'updatedAt', 'canRead', 'canMutate',
                   'canManage', 'canManageSources', 'canEditAllFields', 'editableFields'}
        return {kind: {key: item for key, item in value[kind].items() if key not in ignored}
                for kind in ('item', 'acquisition')}

    @staticmethod
    def followup_path(acquisition_id):
        return P + '/acquisitions/' + acquisition_id + '/followup'

    @staticmethod
    def payload(current, **data):
        return {'requestId': secrets.token_hex(16), 'itemRevision': current['item']['revision'],
                'revision': current['acquisition']['revision'],
                'data': {'title': '跟进售后', 'owner': 'shared', 'due': '', 'note': '', **data}}

    def prepare_batch(self, ctx, shop, *, visibility='private', title=PRIVATE_TITLE):
        item = self.create_item(ctx, title, visibility)
        current = self.write(ctx, 'POST', P + '/items/' + item['id'] + '/acquisitions', {
            'requestId': secrets.token_hex(16), 'itemRevision': item['revision'],
            'data': {'kind': 'purchase', 'orderedQty': 6, 'orderState': 'in_transit',
                     'shoppingId': shop['id'], 'afterSalesState': 'open', 'note': PRIVATE_NOTE}}, 201)
        batch = current['acquisition']
        # A real nonzero physical sentinel makes accidental stock changes visible.
        current = self.write(ctx, 'POST', P + '/acquisitions/' + batch['id'] + '/movements', {
            'requestId': secrets.token_hex(16), 'itemRevision': current['item']['revision'],
            'revision': batch['revision'], 'confirmReceived': True,
            'data': {'kind': 'receive', 'quantity': 2, 'occurredOn': '2026-09-18',
                     'reason': '合成夹具已核对两件实物'}})
        assert current['item']['onHandQty'] == 2 and current['acquisition']['afterSalesState'] == 'open'
        return current

    def prepare(self, ctx, *, visibility='private'):
        shop = self.setup(ctx, '合成售后来源采购')
        protected = self.protected()
        assert protected['hub_transactions'] and len(protected['shopping_and_trips']) >= 2
        kinds = self.query("SELECT kind,count(*) FROM entities WHERE kind IN ('shopping','trips') GROUP BY kind")
        assert dict(kinds).get('shopping', 0) >= 1 and dict(kinds).get('trips', 0) >= 1
        return shop, self.prepare_batch(ctx, shop, visibility=visibility)

    def open_batch(self, page, shop, acquisition_id):
        self.open_source(page, shop)
        button(page, '处理关联批次 ' + acquisition_id).click()
        expect(button(page, '编辑批次')).to_be_enabled(timeout=20000)
        expect(page.get_by_text('售后家庭待办', exact=True)).to_be_visible()
        expect(page.get_by_text('正在核对售后待办关联。', exact=True)).to_have_count(0, timeout=20000)

    @staticmethod
    def draft(page):
        expect(button(page, '创建售后待办')).to_be_enabled(timeout=20000)
        button(page, '创建售后待办').click()
        expect(page.get_by_role('textbox', name=TITLE, exact=True)).to_have_value('跟进售后')
        expect(page.get_by_role('textbox', name=NOTE, exact=True)).to_have_value('')
        expect(page.get_by_role('textbox', name=DUE, exact=True)).to_have_value('')
        expect(page.get_by_role('radio', name='售后待办负责人 共同', exact=True)).to_be_checked()
        expect(page.get_by_text('这条待办会在家庭清单中共享', exact=True)).to_be_visible()

    @staticmethod
    def linked_card(page, task, owner_name='共同'):
        expect(page.get_by_role('textbox', name=TITLE, exact=True)).to_have_count(0)
        expect(page.get_by_text(task['title'], exact=True)).to_be_visible(timeout=20000)
        line = owner_name + ' · ' + ('截止 ' + task['due'] if task['due'] else '未设置截止日')
        line += ' · ' + ('已完成' if task['done'] else '待完成')
        expect(page.get_by_text(line, exact=True)).to_be_visible()
        expect(button(page, '创建售后待办')).to_have_count(0)

    def assert_one_task(self, acquisition_id, task_id, tasks_before, *, request_id=None):
        tasks = self.tasks()
        assert set(tasks) - set(tasks_before) == {task_id}
        assert all(tasks[key] == value for key, value in tasks_before.items())
        assert set(tasks[task_id]['data']) == TASK_FIELDS
        text = json.dumps(tasks[task_id], ensure_ascii=False)
        assert PRIVATE_TITLE not in text and PRIVATE_NOTE not in text
        receipts = self.query("SELECT request_id,result FROM inventory_operations "
                              "WHERE operation='create_followup' AND acquisition_id=?", (acquisition_id,))
        assert len(receipts) == 1 and json.loads(receipts[0][1])['entityId'] == task_id
        if request_id is not None:
            assert receipts[0][0] == request_id
            assert self.query('SELECT count(*) FROM inventory_operations WHERE request_id=?',
                              (request_id,)) == [(1,)]
        return tasks[task_id]

    def finish_case(self, name):
        assert self.schema() == self.schema_before, 'Schema changed during browser acceptance'
        counts = lambda values: dict(sorted(Counter(row['method'] + ' ' + row['path'] for row in values).items()))
        self.report.setdefault('requestCounts', {})[self.out.name] = {
            'browser': counts(self.requests), 'fixtureApi': counts(self.api_requests)}
        self.report.setdefault('databaseChecks', {})[self.out.name] = {
            'schemaUnchanged': True, 'taskCount': len(self.tasks()),
            'followupOperationCount': self.query("SELECT count(*) FROM inventory_operations WHERE operation='create_followup'")[0][0],
            'movementCount': self.query('SELECT count(*) FROM inventory_movements')[0][0],
            'protectedSha256': hashlib.sha256(json.dumps(self.protected(), sort_keys=True).encode()).hexdigest()}
        super().finish_case(name)

    def private_task_lifecycle(self, browser):
        with self.flow(browser) as (ctx, page):
            self.stage('Private batch: explicit sharing, cancel, one UI create, family list completion and real restart')
            shop, current = self.prepare(ctx)
            acquisition_id = current['acquisition']['id']
            physical = self.physical(ctx, acquisition_id)
            movements = self.table_rows(('inventory_movements', 'inventory_source_links'))
            tasks_before = self.tasks()
            self.open_batch(page, shop, acquisition_id)
            self.draft(page)
            before_cancel = self.no_write_snapshot()
            fill(page, TITLE, '不会保存的合成草稿')
            self.cancel(page)
            assert self.no_write_snapshot() == before_cancel
            assert self.get(ctx, self.followup_path(acquisition_id))['state'] == 'none'
            assert self.count_requests('POST', self.followup_path(acquisition_id)) == 0
            self.draft(page)
            me, people = self.get(ctx, '/api/me')['user'], self.get(ctx, '/api/state')['people']
            other = next(person for person in people if person['id'] != me['id'])
            page.get_by_role('radio', name='售后待办负责人 ' + other['name'], exact=True).click()
            fill(page, DUE, '2026-10-02')
            fill(page, NOTE, '只共享本次明确填写的联系时间')
            form = page.get_by_test_id('section-card-content').filter(
                has=page.get_by_role('heading', name='创建售后待办', exact=True))
            self.capture(page, 'explicit-shared-draft', 390, form,
                         ready=('创建家庭待办', '取消编辑'), fields=(TITLE, DUE, NOTE))
            result, body = self.actual(page, 'POST', self.followup_path(acquisition_id),
                                       lambda: button(page, '创建家庭待办').click(), 201)
            task_id = result['operation']['entityId']
            expected = {'title': '跟进售后', 'owner': other['id'], 'due': '2026-10-02',
                        'done': False, 'note': '只共享本次明确填写的联系时间', 'tripId': ''}
            assert self.assert_one_task(acquisition_id, task_id, tasks_before, request_id=body['requestId'])['data'] == expected
            assert body['data'] == {key: expected[key] for key in ('title', 'owner', 'due', 'note')}
            self.linked_card(page, expected, other['name'])
            button(page, '返回原采购').click()
            expect(button(page, '登记或查看库存：' + shop['title'])).to_be_enabled()
            # The desktop navigation uses buttons; the mobile bar has its own
            # tab semantics. The form itself was captured at 390 px above.
            page.set_viewport_size({'width': 1280, 'height': 1000})
            button(page, '待办').click()
            expect(page.get_by_role('heading', name='共同待办', exact=True)).to_be_visible(timeout=20000)
            task_row = page.get_by_test_id('tasks-item-' + task_id)
            expect(task_row).to_be_visible()
            expect(task_row.get_by_text(expected['title'], exact=True)).to_be_visible()
            assert PRIVATE_TITLE not in page.locator('body').inner_text()
            assert PRIVATE_NOTE not in page.locator('body').inner_text()
            state_task = next(task for task in self.get(ctx, '/api/state')['tasks'] if task['id'] == task_id)
            assert set(state_task) <= TASK_FIELDS | {'id', 'revision'} and 'inventory' not in json.dumps(state_task)
            checkbox = task_row.get_by_role('checkbox', name='完成' + expected['title'], exact=True)
            checkbox.focus()
            self.actual(page, 'PATCH', '/api/items/tasks/' + task_id, lambda: checkbox.press('Space'))
            expect(task_row).to_have_count(0)
            expected['done'] = True
            self.open_batch(page, shop, acquisition_id)
            self.linked_card(page, expected, other['name'])
            projection = self.get(ctx, self.followup_path(acquisition_id))
            assert projection['task']['id'] == task_id and projection['task']['done']
            assert self.physical(ctx, acquisition_id) == physical
            assert self.table_rows(('inventory_movements', 'inventory_source_links')) == movements
            task_card = page.get_by_text('售后家庭待办', exact=True).locator('..')
            self.capture(page, 'completed-task-live-projection', 1280, task_card,
                         ready=('编辑批次', '刷新物品', '返回原采购'))
            persisted = self.no_write_snapshot()
            application, database = self.application, self.database
            self.restart()
            assert self.application is not application and self.database == database
            reauthenticated = self.get(ctx, '/api/me')['user'] is None
            if reauthenticated:
                self.login(ctx)
            self.open_batch(page, shop, acquisition_id)
            self.linked_card(page, expected, other['name'])
            assert self.get(ctx, self.followup_path(acquisition_id)) == projection
            assert self.no_write_snapshot() == persisted
            assert self.physical(ctx, acquisition_id) == physical
            assert self.count_requests('POST', self.followup_path(acquisition_id)) == 1
            self.report['taskRestart'] = {'actualFlaskRestart': True, 'sameDatabase': True,
                'sameTaskAndLink': True, 'reauthenticated': reauthenticated}
            self.finish_case('private batch shares only explicit task fields; cancel is read-only; actual list completion and Flask restart preserve link and independent after-sales/stock')

    def lost_create_response(self, browser):
        with self.flow(browser) as (ctx, page):
            self.stage('Drop a real committed POST 201; recover the original receipt with no second POST')
            shop, current = self.prepare(ctx)
            acquisition_id = current['acquisition']['id']
            path = self.followup_path(acquisition_id)
            tasks_before, physical = self.tasks(), self.physical(ctx, acquisition_id)
            movements = self.table_rows(('inventory_movements', 'inventory_source_links'))
            page.set_viewport_size({'width': 1280, 'height': 1000})
            self.open_batch(page, shop, acquisition_id)
            self.draft(page)
            fill(page, TITLE, '合成未知结果待办')
            fill(page, NOTE, '结果不明时保留本次输入')
            dropped, submitted = {}, []
            def record(request):
                if request.method == 'POST' and urlsplit(request.url).path == path:
                    submitted.append(request.post_data_json)
            def drop(handler):
                assert handler.request.url == self.base + path
                if handler.request.method != 'POST' or dropped:
                    handler.continue_()
                    return
                response = handler.fetch()
                assert response.status == 201, response.text()
                dropped.update(body=handler.request.post_data_json, result=response.json())
                handler.abort('failed')
            page.on('request', record)
            pattern = self.base + path
            page.route(pattern, drop)
            button(page, '创建家庭待办').click()
            expect(button(page, '核对并重试本次操作')).to_be_enabled(timeout=20000)
            expect(button(page, '返回原采购')).to_be_disabled()
            expect(button(page, '取消编辑')).to_be_disabled()
            expect(page.get_by_role('textbox', name=TITLE, exact=True)).to_have_value('合成未知结果待办')
            expect(page.get_by_role('textbox', name=NOTE, exact=True)).to_have_value('结果不明时保留本次输入')
            button(page, '日程').click()
            expect(page.get_by_text('请先核对本次库存操作的结果，再离开。', exact=True)).to_be_visible()
            expect(page).to_have_url(self.base + '/app/shopping')
            # Dismiss only the actual navigation-lock snackbar through its UI;
            # pending state and disabled exit/cancel controls must remain intact.
            button(page, '知道了').click()
            task_id, request_id = dropped['result']['operation']['entityId'], dropped['body']['requestId']
            self.assert_one_task(acquisition_id, task_id, tasks_before, request_id=request_id)
            committed = self.no_write_snapshot()
            recovery = page.get_by_test_id('section-card-content').filter(
                has=page.get_by_role('heading', name='先核对本次操作', exact=True))
            self.capture(page, 'unknown-recovery', 390, recovery, ready=('核对并重试本次操作',),
                         disabled=('返回原采购', '取消编辑'))
            draft = page.get_by_test_id('section-card-content').filter(
                has=page.get_by_role('heading', name='创建售后待办', exact=True))
            self.capture(page, 'unknown-retained-draft', 390, draft, ready=('核对并重试本次操作',),
                         disabled=('返回原采购', '取消编辑'), fields=(TITLE, DUE, NOTE))
            receipt_path = P + '/operations/' + request_id
            receipt, _ = self.actual(page, 'GET', receipt_path,
                                     lambda: button(page, '核对并重试本次操作').click())
            self.linked_card(page, dropped['body']['data'] | {'done': False})
            page.unroute(pattern, drop)
            assert receipt['operation']['entityId'] == task_id and receipt['operation']['replayed']
            assert submitted == [dropped['body']]
            assert self.count_requests('POST', path) == 1 and self.count_requests('GET', receipt_path) == 1
            assert self.no_write_snapshot() == committed
            assert self.physical(ctx, acquisition_id) == physical
            assert self.table_rows(('inventory_movements', 'inventory_source_links')) == movements
            self.report['droppedResponse'] = {'realCommittedStatus': 201, 'requestId': request_id,
                'entityId': task_id, 'postCount': 1, 'receiptGetCount': 1, 'taskCountAdded': 1,
                'operationCountAdded': 1, 'receiptRecoveryDatabaseUnchanged': True}
            self.finish_case('real committed response loss retains draft and navigation lock; original GET receipt restores exactly one task and operation without another POST')

    def partner_conflict_deleted(self, browser):
        with self.flow(browser) as (owner, page):
            self.stage('Partner creates first; real 409 rechecks the existing task; deletion never permits replacement')
            shop, current = self.prepare(owner, visibility='shared')
            acquisition_id = current['acquisition']['id']
            path = self.followup_path(acquisition_id)
            tasks_before, physical = self.tasks(), self.physical(owner, acquisition_id)
            movements = self.table_rows(('inventory_movements', 'inventory_source_links'))
            self.open_batch(page, shop, acquisition_id)
            self.draft(page)
            fill(page, TITLE, '不应创建的原成员草稿')
            partner = self.context(browser, 2)
            try:
                other_payload = self.payload(current, title='伙伴先创建的合成待办')
                created = self.write(partner, 'POST', path, other_payload, 201)
                task_id = created['operation']['entityId']
                before_conflict = self.no_write_snapshot()
                _, rejected = self.actual(page, 'POST', path, lambda: button(page, '创建家庭待办').click(), 409)
                expect(button(page, '重新核对并修改草稿')).to_be_enabled()
                expect(page.get_by_role('textbox', name=TITLE, exact=True)).to_have_value('不应创建的原成员草稿')
                assert self.no_write_snapshot() == before_conflict
                self.actual(page, 'GET', path, lambda: button(page, '重新核对并修改草稿').click())
                self.linked_card(page, other_payload['data'] | {'done': False})
                task = self.assert_one_task(acquisition_id, task_id, tasks_before, request_id=other_payload['requestId'])
                assert self.query('SELECT count(*) FROM inventory_operations WHERE request_id=?', (rejected['requestId'],)) == [(0,)]
                assert self.count_requests('POST', path) == 1
                assert self.no_write_snapshot() == before_conflict
                self.write(partner, 'DELETE', '/api/items/tasks/' + task_id, {'revision': task['revision']})
                self.actual(page, 'GET', path, lambda: button(page, '刷新物品').click())
                self.deleted(page, owner, acquisition_id)
                button(page, '返回原采购').click()
                expect(button(page, '登记或查看库存：' + shop['title'])).to_be_enabled()
                self.open_batch(page, shop, acquisition_id)
                self.deleted(page, owner, acquisition_id)
                # Real batch editor closes after-sales; it must not recreate a task.
                button(page, '编辑批次').click()
                page.get_by_text('日期、售后与采购关联', exact=True).click()
                page.get_by_role('radio', name='售后已结束', exact=True).click()
                self.actual(page, 'PATCH', P + '/acquisitions/' + acquisition_id,
                            lambda: button(page, '保存批次').click())
                self.deleted(page, owner, acquisition_id)
                expect(page.get_by_text('售后已结束', exact=True)).to_be_visible()
                physical['acquisition']['afterSalesState'] = 'closed'
                assert self.physical(owner, acquisition_id) == physical
                assert self.table_rows(('inventory_movements', 'inventory_source_links')) == movements
                assert self.tasks() == tasks_before
                assert self.query("SELECT count(*) FROM inventory_operations WHERE operation='create_followup' AND acquisition_id=?", (acquisition_id,)) == [(1,)]
                assert self.count_requests('POST', path) == 1
                batch_card = page.get_by_test_id('section-card-content').filter(
                    has=page.get_by_role('heading', name='批次详情', exact=True))
                self.capture(page, 'deleted-history-after-sales-closed', 1280, batch_card,
                             ready=('编辑批次', '刷新物品', '返回原采购'))
                self.report['partnerConflict'] = {'realStatus': 409, 'rejectedRequestId': rejected['requestId'],
                    'taskCountAddedBeforeDelete': 1, 'taskCountAddedAfterDelete': 0,
                    'followupOperationCount': 1, 'noReplacementAfterRefreshReopenClose': True}
                self.finish_case('real partner-first creation rejects stale draft; recheck finds existing task; real DELETE, refresh, reopen and after-sales closure preserve deleted history without replacement')
            finally:
                partner.close()

    def deleted(self, page, ctx, acquisition_id):
        expect(page.get_by_text(DELETED, exact=True)).to_be_visible(timeout=20000)
        expect(button(page, '创建售后待办')).to_have_count(0)
        expect(button(page, '创建家庭待办')).to_have_count(0)
        value = self.get(ctx, self.followup_path(acquisition_id))
        assert value['state'] == 'deleted' and value['task'] is None

    def capture(self, page, name, width, target, *, ready=(), disabled=(), fields=()):
        """Capture an actual RN scroll target after business and visual settling.

        Only viewport, scrolling and read-only measurements change here. Do not
        hide labels, disable animations, inject styles or crop overlap away.
        """
        page.set_viewport_size({'width': width, 'height': 1000 if width >= 1040 else 844})
        for label in ready:
            expect(button(page, label)).to_be_enabled(timeout=20000)
        for label in disabled:
            expect(button(page, label)).to_be_disabled(timeout=20000)
        expect(target).to_have_count(1)
        expect(target).to_be_visible(timeout=20000)
        page.evaluate('() => document.fonts.ready')
        target.evaluate("element => element.scrollIntoView({block:'center', inline:'nearest', behavior:'instant'})")
        # Paper uses both CSS and JS-driven transforms. Sample rendered leaf
        # nodes AND all their ancestor boxes/styles, so a label transition is
        # not mistaken for stability merely because the input box is stationary.
        stability = target.evaluate('''async root => {
          const started=performance.now(); let last=null, since=started, samples=0, changes=0;
          const round=n=>Math.round(n*1000)/1000;
          const measure=()=>{
            const nodes=new Set([root,...root.querySelectorAll('*')]);
            for(let parent=root.parentElement;parent;parent=parent.parentElement)nodes.add(parent);
            const geometry=[...nodes].map(element=>{
              const rect=element.getBoundingClientRect(), style=getComputedStyle(element);
              return {tag:element.tagName,role:element.getAttribute('role'),
                box:[rect.x,rect.y,rect.width,rect.height].map(round),
                opacity:style.opacity,transform:style.transform,visibility:style.visibility,
                display:style.display,font:style.font,letterSpacing:style.letterSpacing};
            });
            const running=[...document.getAnimations()].some(animation=>
              ['pending','running'].includes(animation.playState));
            return {geometry,running,fonts:document.fonts.status};
          };
          while(performance.now()-started<12000){
            await new Promise(resolve=>setTimeout(resolve,100));
            const value=measure(), signature=JSON.stringify(value), now=performance.now();
            if(signature!==last){last=signature;since=now;samples=1;changes++;}else samples++;
            if(now-since>=600&&samples>=7&&!value.running&&value.fonts==='loaded')
              return {requiredStableMs:600,observedStableMs:round(now-since),samples,
                changedSamples:changes,totalWaitMs:round(now-started),elements:value.geometry.length,
                signature};
          }
          throw new Error('Paper label/opacity/transform/geometry did not stabilize for 600 ms');
        }''')
        signature = stability.pop('signature')
        stability['geometrySha256'] = hashlib.sha256(signature.encode()).hexdigest()
        def geometry():
            return target.evaluate('''element=>{
              const box=element.getBoundingClientRect();
              let left=0,top=0,right=innerWidth,bottom=innerHeight;
              for(let parent=element.parentElement;parent;parent=parent.parentElement){
                const style=getComputedStyle(parent),rect=parent.getBoundingClientRect();
                if(['hidden','auto','scroll','clip'].includes(style.overflowX)){
                  left=Math.max(left,rect.left);right=Math.min(right,rect.right);}
                if(['hidden','auto','scroll','clip'].includes(style.overflowY)){
                  top=Math.max(top,rect.top);bottom=Math.min(bottom,rect.bottom);}
              }
              return {x:box.x,y:box.y,width:box.width,height:box.height,
                clip:{left,top,right,bottom},fullyVisible:box.width>0&&box.height>0
                  &&box.left>=left-1&&box.right<=right+1&&box.top>=top-1&&box.bottom<=bottom+1};
            }''')
        before = geometry()
        assert before['fullyVisible'], ('Key screenshot target is clipped', name, before)
        field_geometry = {}
        for label in fields:
            field = target.get_by_role('textbox', name=label, exact=True)
            expect(field).to_be_visible()
            field_geometry[label] = {'inputBox': field.bounding_box(),
                'labels': target.get_by_text(label, exact=True).evaluate_all('''nodes=>nodes.map(element=>{
                  const rect=element.getBoundingClientRect(),style=getComputedStyle(element);
                  return {box:{x:rect.x,y:rect.y,width:rect.width,height:rect.height},
                    opacity:style.opacity,transform:style.transform};
                })''')}
        super().screenshot(page, name, width)
        for label in ready:
            expect(button(page, label)).to_be_enabled()
        for label in disabled:
            expect(button(page, label)).to_be_disabled()
        after = geometry()
        assert after['fullyVisible'] and all(abs(after[key]-before[key]) <= 0.5 for key in ('x','y','width','height'))
        self.report['screenshots'][-1].update(targetBox=after, stability=stability,
            businessReady=list(ready), businessDisabled=list(disabled), fieldGeometry=field_geometry)

    def private_link_revocation(self, browser):
        with self.flow(browser) as (owner, _page):
            self.stage('Private batch/link stays hidden; revoked sharing clears the partner followup draft on foreground')
            shop, private = self.prepare(owner)
            private_id = private['acquisition']['id']
            private_body = self.payload(private, title='已明确共享的通用售后待办')
            created = self.write(owner, 'POST', self.followup_path(private_id), private_body, 201)
            shared = self.prepare_batch(owner, shop, visibility='shared', title='合成临时共享物品')
            shared_id = shared['acquisition']['id']
            partner = self.context(browser, 2)
            try:
                page = partner.new_page()
                self.page = page
                self.open_source(page, shop)
                linked = self.linked(partner, shop)
                assert linked['total'] == 1 and linked['items'][0]['acquisition']['id'] == shared_id
                expect(button(page, '处理关联批次 ' + private_id)).to_have_count(0)
                expect(page.get_by_text(PRIVATE_TITLE, exact=True)).to_have_count(0)
                self.get(partner, P + '/acquisitions/' + private_id, 404)
                self.get(partner, self.followup_path(private_id), 404)
                self.get(partner, P + '/operations/' + private_body['requestId'], 404)
                task_id = created['operation']['entityId']
                public_task = next(task for task in self.get(partner, '/api/state')['tasks'] if task['id'] == task_id)
                assert set(public_task) <= TASK_FIELDS | {'id', 'revision'}
                assert PRIVATE_TITLE not in json.dumps(public_task, ensure_ascii=False)
                assert PRIVATE_NOTE not in json.dumps(public_task, ensure_ascii=False)
                button(page, '处理关联批次 ' + shared_id).click()
                self.draft(page)
                fill(page, TITLE, '撤共享后不得保存的伙伴草稿')
                fill(page, NOTE, '撤共享后应清空的输入')
                self.write(owner, 'PATCH', P + '/items/' + shared['item']['id'], {
                    'requestId': secrets.token_hex(16), 'revision': shared['item']['revision'],
                    'patch': {'visibility': 'private'}})
                before_foreground = self.no_write_snapshot()
                physical = self.physical(owner, shared_id)
                shopping.fixture.visibility(page, True)
                shopping.fixture.visibility(page, False)
                expect(page.get_by_text('这件物品已归档或不再对你可见，旧详情和草稿已清空。', exact=True)).to_be_visible(timeout=20000)
                expect(page.get_by_role('textbox', name=TITLE, exact=True)).to_have_count(0)
                expect(page.get_by_role('textbox', name=NOTE, exact=True)).to_have_count(0)
                expect(page.get_by_text(shared['item']['title'], exact=True)).to_have_count(0)
                expect(button(page, '创建家庭待办')).to_have_count(0)
                assert self.linked(partner, shop)['total'] == 0
                self.get(partner, P + '/acquisitions/' + shared_id, 404)
                self.get(partner, self.followup_path(shared_id), 404)
                assert self.get(owner, self.followup_path(shared_id))['state'] == 'none'
                assert self.no_write_snapshot() == before_foreground
                assert self.physical(owner, shared_id) == physical
                assert self.count_requests('POST', self.followup_path(shared_id)) == 0
                assert self.query("SELECT count(*) FROM inventory_operations WHERE operation='create_followup' AND acquisition_id=?", (shared_id,)) == [(0,)]
                assert self.tasks()[task_id]['data']['title'] == private_body['data']['title']
                self.finish_case('partner cannot read private batch/link/receipt; explicit household task has no source fields; foreground after revocation clears draft with no task or inventory writes')
            finally:
                partner.close()


def run_case(name, root, bundle, report, out, browser):
    folder = None
    case_out = out / name
    case_out.mkdir()
    before = tuple(len(report[key]) for key in ('checks', 'pageErrors', 'externalRequests'))
    case = {'name': name, 'passed': False, 'temporaryFixtureRemoved': False}
    try:
        with ExitStack() as lifecycle:
            folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='if-')))
            run = Run(root, bundle, folder, report, case_out, lifecycle)
            getattr(run, name)(browser)
        assert not folder.exists()
        assert tuple(len(report[key]) for key in ('checks', 'pageErrors', 'externalRequests')) == (before[0] + 1, before[1], before[2])
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
    parser.add_argument('--case', choices=('all', *CASES), default='all')
    args = parser.parse_args()
    selected = CASES if args.case == 'all' else (args.case,)
    root, bundle, evidence_path = args.source_root.resolve(), args.bundle.resolve(), args.build_evidence.resolve()
    assert sys.dont_write_bytecode and not sys.flags.optimize
    assert re.fullmatch('[a-f0-9]{40}', args.expected_head) and re.fullmatch('[a-f0-9]{64}', args.expected_build_evidence)
    def git(where, *command):
        return subprocess.check_output(['git', '--no-replace-objects', '--no-optional-locks', *command], cwd=where, text=True).strip()
    def tracked(commit):
        return set(git(root, 'ls-tree', '-r', '--name-only', commit).splitlines())
    head, author_head = git(root, 'rev-parse', 'HEAD'), git(AUTHOR, 'rev-parse', 'HEAD')
    assert head == args.expected_head and not git(root, 'status', '--porcelain=v1') and not git(AUTHOR, 'status', '--porcelain=v1')
    script_name = 'tests/browser_expo_inventory_followup_check.py'
    assert read_git_blobs(AUTHOR, author_head, [script_name])[script_name] == Path(__file__).read_bytes()
    assert sha(evidence_path) == args.expected_build_evidence
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    assert evidence['buildExit'] == 0 and evidence['bundleMarkers'] is True
    assert git(root, 'rev-parse', evidence['head'] + '^{tree}') == evidence['tree']
    subprocess.run(['git', '--no-replace-objects', 'merge-base', '--is-ancestor', evidence['head'], head], cwd=root, check=True)
    inputs = evidence['inputFiles']
    for commit in (evidence['head'], head):
        expected = {name for name in tracked(commit) if name.startswith('frontend/')
                    and name not in {'frontend/README.md', 'frontend/LICENSE', 'frontend/.gitignore'}}
        assert set(inputs) == expected, 'Incomplete Expo input manifest'
        assert {name: hashlib.sha256(raw).hexdigest() for name, raw in read_git_blobs(root, commit, inputs).items()} == inputs
    assert {name: sha(root / name) for name in inputs} == inputs
    assert file_manifest(bundle) == evidence['files'] and evidence['files']
    names = tracked(head)
    def hashes():
        return {name: sha(root / name) for name in sorted(names)}
    before = hashes()
    assert before == {name: hashlib.sha256(raw).hexdigest() for name, raw in read_git_blobs(root, head, names).items()}
    bindings = fixture_bindings(root)
    out = AUTHOR / 'test-results' / ('expo-inventory-followup-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], stages=[], pageErrors=[], externalRequests=[], screenshots=[], scenarioResults=[], scenarioFailures=[],
        head=head, tree=git(root, 'rev-parse', 'HEAD^{tree}'), buildHead=evidence['head'], buildTree=evidence['tree'], buildInputs=inputs,
        buildKind=evidence.get('kind'), buildEvidencePath=str(evidence_path), buildEvidenceSha256=sha(evidence_path),
        harnessHead=author_head, harnessSha256=sha(out / 'executed-harness.py'), sourceRoot=str(root), bundleRoot=str(bundle),
        sourceHashesBefore=before, bundleHashesBefore=file_manifest(bundle), followupFixtureBindings=bindings,
        productionWrites=0, realFinancialData=False, realCloud=False, physicalDevice=False,
        requestedScenarios=list(selected), fullSuite=args.case == 'all')
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
                assert len(report['screenshots']) == sum(SCREENSHOT_COUNTS[name] for name in selected)
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
        report['followupFixturesUnchanged'] = all(sha(Path(value['path'])) == value['sha256'] == sha(root / name)
                                                 for name, value in bindings.items())
        report['sourceStillFrozen'] = git(root, 'rev-parse', 'HEAD') == head and not git(root, 'status', '--porcelain=v1')
        report['harnessStillFrozen'] = git(AUTHOR, 'rev-parse', 'HEAD') == author_head and not git(AUTHOR, 'status', '--porcelain=v1') and sha(Path(__file__)) == report['harnessSha256']
        report['temporaryFixtureRemoved'] = len(report['scenarioResults']) == len(selected) and all(case['temporaryFixtureRemoved'] for case in report['scenarioResults'])
        report['passed'] = report['passed'] and all(report[key] for key in ('sourceUnchanged', 'bundleUnchanged',
            'buildEvidenceUnchanged', 'fixturesUnchanged', 'inheritedFixtureUnchanged', 'followupFixturesUnchanged',
            'sourceStillFrozen', 'harnessStillFrozen', 'temporaryFixtureRemoved'))
        with (out / 'result.json').open('x', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'report': str(out / 'result.json')}), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
