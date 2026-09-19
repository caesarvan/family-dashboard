"""Three explicit reminder flows on real temporary Flask/SQLite/HTTPS/Edge.

Initial cloud records and a frozen reminder clock are synthetic. Task writes,
reminder state, receipt recovery and session checks run the real application.
Faults follow genuine successful replies; no successful business DTO is mocked.
"""
import argparse
from contextlib import ExitStack, closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import traceback
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import ThreadedWSGIServer
import browser_expo_finance_check as fixture
from browser_expo_finance_check import Run as BaseRun, button, sha
from browser_expo_assistant_trip_items_check import export_hashes
from scripts import check_expo_task_dependencies_browser as previous

HARNESS = 'scripts/check_expo_task_reminders_browser.py'
CASES = ('read_snooze_edit', 'committed_response_lost', 'committed_identity_read_failed')
CASE_SCREENSHOTS = dict(zip(CASES, (2, 4, 4)))
WIDTHS = (390, 1280)
ITEMS = '/api/items/tasks'
REMINDERS = '/api/task-reminders'
STORAGE_KEY = 'family.task-reminder-recovery.v1'
NOW = datetime(2027, 10, 10, 1, tzinfo=timezone.utc)
DUE = '2027-10-10'
CONFIRMED = '这次提醒操作已确认。待办的完成状态没有改变。'


def selected_cases(values):
    if values is None:
        return CASES
    if not values or any(name not in CASES for name in values):
        raise ValueError('Select at least one known browser case')
    return tuple(dict.fromkeys(values))


def build_source_delta(git, head, evidence, build_head):
    """An export is reusable only with identical complete frontend Git bytes."""
    assert re.fullmatch('[a-f0-9]{40}', build_head)
    assert evidence['sourceHead'] == build_head
    assert evidence['sourceTree'] == git('rev-parse', build_head + '^{tree}')
    assert git('merge-base', build_head, head) == build_head, 'Build source must be an ancestor'
    assert git('rev-parse', build_head + ':frontend') == git('rev-parse', head + ':frontend'), 'Complete frontend must be identical'
    return git('diff', '--name-only', build_head, head).splitlines()


def labelled_button(parent, label):
    # Paper may prefix its icon. Literal Unicode survives Python-to-JS regex;
    # do not emit raw Python \U escapes or silently pick one ambiguous control.
    result = parent.get_by_role('button', name=re.compile(re.escape(label) + r'$'))
    expect(result).to_have_count(1)
    return result


def reminder_card(page, title):
    card = page.get_by_test_id('section-card-content').filter(has=page.get_by_role('heading', name=title, exact=True))
    expect(card).to_have_count(1)
    return card


def stored_recovery(page):
    raw = page.evaluate('(key) => sessionStorage.getItem(key)', STORAGE_KEY)
    if raw is None:
        return None
    value = json.loads(raw)
    assert set(value) == {'version', 'scope', 'recovery'} and value['version'] == 1
    assert re.fullmatch('[a-f0-9]{64}', value['scope'])
    recovery = value['recovery']; intent = recovery['intent']
    assert set(recovery) == {'intent', 'filter', 'page'}
    assert set(intent) <= {'taskId', 'requestId', 'occurrence', 'revision', 'action', 'snoozedUntil'}
    assert {'taskId', 'requestId', 'occurrence', 'revision', 'action'} <= set(intent)
    assert re.fullmatch('[a-f0-9]{32}', intent['requestId']) and re.fullmatch('[a-f0-9]{64}', intent['occurrence'])
    return value


def identity_fault(route, response, status, committed):
    """A fake identity transport failure never serves a fake successful /me."""
    assert status in (404, 429)
    assert committed and response.status == 200, 'Identity fault needs a committed action and real successful identity read'
    actor = response.json()['user']
    assert actor['role'] == 'member'
    evidence = {'backendStatus': response.status, 'deliveredStatus': status,
                'memberId': actor['id'], 'householdId': actor['householdId'],
                'backendResponseSha256': hashlib.sha256(response.body()).hexdigest()}
    route.fulfill(status=status, content_type='application/json',
                  body=json.dumps({'error': 'Synthetic identity-read transport failure'}))
    return evidence  # Never persist the /me response body, Cookie or CSRF.


class Run(BaseRun):
    record = previous.Run.record
    proof = previous.Run.proof
    capture = previous.Run.capture
    tasks = previous.Run.tasks
    task = previous.Run.task

    def __init__(self, root, bundle, folder, report, out, lifecycle):
        self.exchange_number = 0
        assert ThreadedWSGIServer.block_on_close is True
        lifecycle.enter_context(patch.object(ThreadedWSGIServer, 'daemon_threads', False))
        super().__init__(root, bundle, folder, report, out, lifecycle)
        assert not self.server.daemon_threads
        paths = {HARNESS: Path(__file__), 'scripts/check_expo_task_dependencies_browser.py': Path(previous.__file__),
                 'tests/browser_expo_finance_check.py': Path(fixture.__file__),
                 'tests/browser_expo_assistant_trip_items_check.py': Path(sys.modules['browser_expo_assistant_trip_items_check'].__file__)}
        paths.update({name + '.py': Path(sys.modules[name].__file__) for name in
                      ('app', 'home_assistant', 'task_reminders', 'task_dependencies', 'cloud_accounts', 'cloud_providers',
                       'member_sessions', 'household_memberships', 'finance_source_bridge', 'membership_storage')})
        for name, actual in paths.items():
            assert actual.resolve() == (root / name).resolve()
            assert report.setdefault('fixtureHashes', {}).setdefault(name, sha(actual)) == sha(actual)
        actual_paths = {name: str(path.resolve()) for name, path in paths.items()}
        assert report.setdefault('fixtureActualPaths', actual_paths) == actual_paths
        assert report['fixtureHashes'][HARNESS] == report['harnessSha256']
        lifecycle.enter_context(patch.object(sys.modules['task_reminders'], 'clock', lambda: NOW))
        for name in ('_model_json', 'model_plan', 'model_journey_brief'):
            lifecycle.enter_context(patch.object(sys.modules['home_assistant'], name, self.forbidden_provider))
        lifecycle.enter_context(patch.object(self.application.extensions['cloud_accounts'], 'active_provider', self.forbidden_provider))

    def start(self, port=0):
        self.cfg['ASSISTANT_PROVIDER'] = 'local'
        super().start(port)

    def forbidden_provider(self, *_args, **_kwargs):
        self.report['unexpectedProviderAttempts'].append(self.out.name)
        raise AssertionError('Real model and cloud calls are forbidden')

    def clear_finance(self):
        pass  # Each selected case owns a fresh temporary database.

    def snapshot(self):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database)) as con:
            assert not con.execute('PRAGMA foreign_key_check').fetchall()
            return {table: sorted(con.execute('SELECT * FROM "' + table + '"').fetchall(), key=repr)
                    for table in ('entities', 'task_reminders', 'task_reminder_operations', 'audit', 'settings')}

    def seed_task(self, ctx, title):
        created = self.write(ctx, 'POST', ITEMS, {'title': title, 'owner': 'member1', 'due': DUE, 'sourceId': ''}, 201)
        return self.task(ctx, created['id'])

    def seed_cloud(self):
        # A synthetic initial mirror, normalized by the real provider parser;
        # no OAuth, credentials, provider transport or successful HTTP is faked.
        title = '合成共享云任务长标题：' + '行程资料🧭与出发准备，' * 18
        provider = sys.modules['cloud_providers'].CloudProvider('google', 'synthetic-unused', transport=self.forbidden_provider)
        record = provider._task({'id': 'synthetic-remote', 'title': title, 'due': '2027-10-09T00:00:00Z', 'status': 'needsAction'})
        uid = 'cloud-synthetic-long-reminder'
        data = {**record['data'], 'sync': {'provider': 'google', 'sourceId': 'synthetic-source',
                'remoteId': record['id'], 'version': record['version'], 'readOnly': False}}
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database)) as con, con:
            con.execute("INSERT INTO cloud_accounts(id,owner,provider,client_id,subject,name,email,tokens) VALUES('synthetic-account','member1','google','synthetic','synthetic','Synthetic','','none')")
            con.execute("INSERT INTO cloud_sources(id,account_id,remote_id,kind,name,owner) VALUES('synthetic-source','synthetic-account','synthetic-list','tasks','Synthetic','shared')")
            con.execute("INSERT INTO entities(id,kind,data,updated_at) VALUES(?,'tasks',?,'synthetic')", (uid, json.dumps(data)))
            con.execute('INSERT INTO cloud_items VALUES(?,?,?)', (uid, 'synthetic-source', record['id']))
            con.execute("UPDATE settings SET revision=revision+1 WHERE id='meta'")
        self.record('synthetic-cloud-fixture', {'id': uid, 'normalized': record, 'selectedSharedSource': True})
        return uid, title

    def open_reminders(self, page, *, navigate=True):
        if navigate:
            page.goto(self.base + '/app/')
        labelled_button(page, '我的提醒').click()
        expect(page.get_by_test_id('task-reminders-panel')).to_be_visible(timeout=15000)
        expect(labelled_button(page, '刷新提醒')).to_be_enabled(timeout=15000)

    def exchange(self, page, path, action, *, method='POST', status=200, fault=None, committed=None):
        self.exchange_number += 1
        stem, calls, url = 'exchange-%02d' % self.exchange_number, [], self.base + path
        def intercept(route):
            assert route.request.method == method
            response = route.fetch(max_redirects=0)
            raw = response.body()
            saved = self.out / (stem + '.body')
            with saved.open('xb') as stream:
                stream.write(raw)
            result = {'path': path, 'method': method, 'payload': route.request.post_data_json,
                      'backendStatus': response.status, 'backendResult': json.loads(raw),
                      'backendResponseSha256': sha(saved), 'deliveredFault': fault}
            assert response.status == status, result
            if committed:
                assert method == 'POST' and status == 200
                committed(result)
            previous.deliver(route, response, fault)
            calls.append(result)
        page.route(url, intercept, times=1)
        try:
            action()
            self.settle(page, lambda: bool(calls))
            assert len(calls) == 1
            return calls[0]
        finally:
            page.unroute(url, intercept)
            self.record(stem, calls)

    def assert_single_operation(self, uid, operation):
        with closing(sqlite3.connect(self.database)) as con:
            rows = con.execute('SELECT result FROM task_reminder_operations WHERE owner=?', ('member1',)).fetchall()
            matching = [json.loads(row[0]) for row in rows if json.loads(row[0])['taskId'] == uid]
            assert matching == [operation], matching
            rows = con.execute('SELECT revision,read_at,snoozed_until FROM task_reminders WHERE owner=? AND task_id=? AND due=?',
                               ('member1', uid, DUE)).fetchall()
            assert rows == [(operation['revision'], operation['readAt'], operation['snoozedUntil'])]

    def read_snooze_edit(self, browser):
        with self.flow(browser) as (ctx, page):
            for n in range(41):
                self.seed_task(ctx, '合成提醒事项 %02d' % n)
            cloud_id, long_title = self.seed_cloud()
            self.open_reminders(page)
            heading = page.get_by_role('heading', name=long_title, exact=True)
            expect(heading).to_be_visible()
            self.capture(page, 'long-cloud-title-390', heading, full_text=heading)
            button(reminder_card(page, long_title), '打开待办').click()
            expect(page.get_by_text('这项待办来自同步清单，请在原应用中修改。', exact=True)).to_be_visible()
            expect(previous.textbox(page)).not_to_be_visible()
            labelled_button(page.get_by_test_id('task-reminders-panel'), '全部').click()
            expect(labelled_button(page, '下一页')).to_be_enabled()
            labelled_button(page, '下一页').click()
            current_page = self.get(ctx, REMINDERS + '?filter=all&page=1')
            assert current_page['page'] == 1 and current_page['total'] == 42
            target = current_page['items'][0]['task']; uid = target['id']
            expect(reminder_card(page, target['title'])).to_be_visible()
            # A genuine later task edit proves the editor does not reuse the
            # reminder projection's old revision or partial fields.
            self.write(ctx, 'PATCH', ITEMS + '/' + uid, {'revision': target['revision'], 'note': '合成最新完整备注'})
            live = self.task(ctx, uid)
            button(reminder_card(page, target['title']), '打开待办').click()
            expect(previous.textbox(page)).to_have_value(target['title'])
            title = '合成提醒打开原事项后编辑'
            previous.textbox(page).fill(title)
            edited = self.exchange(page, ITEMS + '/' + uid, lambda: button(page, '保存').click(), method='PATCH')
            assert edited['payload']['revision'] == live['revision']
            expect(previous.textbox(page)).not_to_be_visible()
            expect(page.get_by_text(re.compile(r'^第\s*2\s*页$'))).to_be_visible()
            self.settle(page, lambda: reminder_card(page, title).is_visible())
            current = self.task(ctx, uid)
            assert current['id'] == uid and current['revision'] == live['revision'] + 1
            assert current['note'] == '合成最新完整备注' and current['done'] is False
            entities = self.snapshot()['entities']
            read = self.exchange(page, REMINDERS + '/' + uid + '/actions', lambda: button(reminder_card(page, title), '标为已读').click())
            assert read['payload']['action'] == 'read' and read['payload']['revision'] == 0
            expect(page.get_by_text(CONFIRMED, exact=True)).to_be_visible()
            expect(button(reminder_card(page, title), '1 小时后提醒')).to_be_enabled()
            snooze = self.exchange(page, REMINDERS + '/' + uid + '/actions', lambda: button(reminder_card(page, title), '1 小时后提醒').click())
            operation = snooze['backendResult']['operation']
            assert snooze['payload']['action'] == 'snooze' and snooze['payload']['revision'] == 1
            assert operation['revision'] == 2 and operation['readAt'] is None
            assert datetime.fromisoformat(operation['snoozedUntil']) == NOW + timedelta(hours=1)
            expect(reminder_card(page, title)).to_contain_text('暂缓至')
            assert self.snapshot()['entities'] == entities and stored_recovery(page) is None
            page.set_viewport_size({'width': 1280, 'height': 1000})
            self.capture(page, 'read-snooze-edit-page-1280', reminder_card(page, title))
            self.record('persisted-read-snooze-edit', {'task': current, 'cloudId': cloud_id, 'page': current_page,
                        'read': read['backendResult'], 'snooze': snooze['backendResult'], 'taskRowsUnchangedByReminderActions': True})
            self.proof('read-snooze-database')
            self.passed('Real read/snooze retain original unfinished task; fresh original editor ID/revision and all/page2 survive return at1280; full long cloud title is measured at390')

    def committed_response_lost(self, browser):
        with self.flow(browser) as (ctx, page):
            for width, fault in zip(WIDTHS, ('abort', 'gateway503')):
                page.set_viewport_size({'width': width, 'height': 844 if width == 390 else 1000})
                task = self.seed_task(ctx, '合成提醒响应丢失 ' + fault); uid = task['id']
                self.open_reminders(page)
                path = REMINDERS + '/' + uid + '/actions'
                before = self.count_requests('POST', path); entities = self.snapshot()['entities']
                committed = self.exchange(page, path, lambda: button(reminder_card(page, task['title']), '1 小时后提醒').click(), fault=fault)
                expect(page.get_by_role('heading', name='一项操作待核对', exact=True)).to_be_visible()
                envelope = stored_recovery(page); intent = envelope['recovery']['intent']
                assert {k: v for k, v in intent.items() if k != 'taskId'} == committed['payload'] and intent['taskId'] == uid
                self.assert_single_operation(uid, committed['backendResult']['operation'])
                self.capture(page, fault + '-pending-' + str(width), page.get_by_role('heading', name='一项操作待核对', exact=True))
                page.reload(wait_until='domcontentloaded')
                assert stored_recovery(page) == envelope
                receipt = self.exchange(page, REMINDERS + '/operations/' + intent['requestId'],
                                        lambda: self.open_reminders(page, navigate=False), method='GET')
                expect(page.get_by_text(CONFIRMED, exact=True)).to_be_visible()
                assert receipt['backendResult'] == committed['backendResult'] and stored_recovery(page) is None
                assert self.count_requests('POST', path) == before + 1 and self.snapshot()['entities'] == entities
                self.assert_single_operation(uid, committed['backendResult']['operation'])
                self.capture(page, fault + '-restored-' + str(width), page.get_by_text(CONFIRMED, exact=True))
                self.record(fault + '-restoration', {'originalEnvelope': envelope, 'postCount': 1,
                            'actualReload': True, 'receiptMatched': True, 'unchangedTask': self.task(ctx, uid)})
            self.proof('lost-response-database')
            self.passed('Actual committed reply lost by abort/503; same-tab reload restores original intent, reads real receipt and creates no second operation or POST')

    def committed_identity_read_failed(self, browser):
        with self.flow(browser) as (ctx, page):
            for width, status in zip(WIDTHS, (429, 404)):
                page.set_viewport_size({'width': width, 'height': 844 if width == 390 else 1000})
                task = self.seed_task(ctx, '合成提醒身份读取失败 ' + str(status)); uid = task['id']
                self.open_reminders(page)
                path = REMINDERS + '/' + uid + '/actions'; before = self.count_requests('POST', path)
                entities = self.snapshot()['entities']; gate = {'committed': None}; faults = []
                def intercept(route):
                    if not gate['committed']:
                        route.continue_(); return
                    response = route.fetch(max_redirects=0)
                    faults.append(identity_fault(route, response, status, gate['committed']))
                page.route(self.base + '/api/me', intercept)
                try:
                    committed = self.exchange(page, path, lambda: button(reminder_card(page, task['title']), '标为已读').click(),
                                              committed=lambda result: gate.update(committed=result))
                    expect(page.get_by_role('heading', name='一项操作待核对', exact=True)).to_be_visible()
                    envelope = stored_recovery(page); intent = envelope['recovery']['intent']
                    assert intent['requestId'] == committed['payload']['requestId']
                    assert faults and all(row['backendStatus'] == 200 and row['deliveredStatus'] == status for row in faults)
                    expect(page.get_by_text('这次操作未保存', exact=False)).not_to_be_visible()
                    stable = self.snapshot(); count = len(faults)
                    labelled_button(page, '刷新提醒').click()
                    self.settle(page, lambda: len(faults) > count)
                    expect(labelled_button(page, '刷新提醒')).to_be_enabled()
                    assert stored_recovery(page) == envelope and self.snapshot() == stable
                    assert self.count_requests('POST', path) == before + 1
                    self.capture(page, 'identity-' + str(status) + '-pending-' + str(width),
                                 page.get_by_role('heading', name='一项操作待核对', exact=True))
                finally:
                    page.unroute(self.base + '/api/me', intercept)
                    self.record('identity-' + str(status) + '-faults', faults)
                with page.expect_response(lambda response: response.request.method == 'GET' and
                                          response.url == self.base + REMINDERS + '?filter=unread&page=0',
                                          timeout=15000) as refreshed:
                    receipt = self.exchange(page, REMINDERS + '/operations/' + intent['requestId'],
                                            lambda: button(page, '核对操作结果').click(), method='GET')
                refreshed_response = refreshed.value
                assert refreshed_response.status == 200
                refreshed_list = refreshed_response.json()
                assert refreshed_list['items'] == [] and refreshed_list['unreadCount'] == 0
                expect(page.get_by_text(CONFIRMED, exact=True)).to_be_visible()
                # The receipt notice appears before readList finishes. Wait for
                # the same panel's real list and trailing identity fence, so the
                # screenshot proves a usable final state rather than a spinner.
                expect(labelled_button(page, '刷新提醒')).to_be_enabled(timeout=15000)
                expect(button(page, '返回首页')).to_be_enabled()
                expect(page.get_by_label('正在核对提醒')).not_to_be_visible()
                expect(page.get_by_text('暂时没有未读提醒', exact=True)).to_be_visible()
                assert receipt['backendResult'] == committed['backendResult'] and stored_recovery(page) is None
                assert self.count_requests('POST', path) == before + 1 and self.snapshot()['entities'] == entities
                self.assert_single_operation(uid, committed['backendResult']['operation'])
                self.capture(page, 'identity-' + str(status) + '-restored-' + str(width), page.get_by_text(CONFIRMED, exact=True))
                self.record('identity-' + str(status) + '-restoration', {'originalEnvelope': envelope, 'postCount': 1,
                            'receiptMatched': True, 'unchangedTask': self.task(ctx, uid),
                            'samePageRefreshSettled': True, 'listAfterReceipt': refreshed_list})
            self.proof('identity-failure-database')
            self.passed('Real POST200 plus later genuine /me200 replaced with429/404 retains exact intent; refresh and recovery only read, with one persisted operation')

    @classmethod
    def run_scenarios(cls, root, bundle, report, out, browser, temp_root, cases=CASES):
        for name in cases:
            case_out = out / name; case_out.mkdir()
            folder, before, case = None, len(report['checks']), {'name': name, 'passed': False}
            screenshots_before = len(report['screenshots'])
            try:
                with ExitStack() as lifecycle:
                    folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='tr-', dir=temp_root)))
                    run = cls(root, bundle, folder, report, case_out, lifecycle)
                    getattr(run, name)(browser)
                assert len(report['checks']) == before + 1 and not folder.exists()
                assert len(report['screenshots']) - screenshots_before == CASE_SCREENSHOTS[name]
                assert run.server is None and not run.thread.is_alive()
                case.update(passed=True, listenerStopped=True)
            except Exception:
                del report['checks'][before:]
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
    parser.add_argument('--build-source-head')
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--expected-build-evidence', required=True)
    parser.add_argument('--temp-root', required=True, type=Path, help='Existing short local parent for exclusive temporary fixtures, e.g. C:/tmp')
    parser.add_argument('--case', action='append', choices=CASES, dest='cases', help='Run only this case; repeat to select more. Default: all three.')
    args = parser.parse_args()
    cases = selected_cases(args.cases)
    expected_screenshots = sum(CASE_SCREENSHOTS[name] for name in cases)
    root, bundle, temp_root = args.source_root.resolve(), args.bundle.absolute(), args.temp_root.resolve()
    assert sys.dont_write_bytecode and not sys.flags.optimize
    assert re.fullmatch('[a-f0-9]{40}', args.expected_head) and re.fullmatch('[a-f0-9]{64}', args.expected_build_evidence)
    assert temp_root.is_dir() and not temp_root.is_symlink() and not temp_root.is_junction()
    def git(*command):
        return subprocess.check_output(['git', '--no-replace-objects', *command], cwd=root, text=True).strip()
    head, tree = git('rev-parse', 'HEAD'), git('rev-parse', 'HEAD^{tree}')
    assert head == args.expected_head and not git('status', '--porcelain=v1')
    evidence_path = bundle.parent / 'build-evidence.json'
    assert sha(evidence_path) == args.expected_build_evidence
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    build_head = args.build_source_head or head
    build_delta = build_source_delta(git, head, evidence, build_head)
    names = subprocess.check_output(['git', '--no-replace-objects', 'ls-files', '-z'], cwd=root).decode('utf-8').rstrip('\0').split('\0')
    def hashes():
        return {name: sha(root / name) for name in names}
    assert export_hashes(bundle) == evidence['files']
    assert all(sha(root / name) == digest for name, digest in evidence['inputFiles'].items())
    assert Path(__file__).resolve() == (root / HARNESS).resolve()
    out = root / 'test-results' / ('expo-task-reminders-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], unexpectedProviderAttempts=[],
                  screenshots=[], scenarioResults=[], scenarioFailures=[], httpEvidence=[], databaseEvidence=[],
                  requestedChecks=len(cases), requestedCases=list(cases), expectedScreenshots=expected_screenshots, head=head, tree=tree, buildEvidenceSha256=sha(evidence_path),
                  harnessSha256=sha(out / 'executed-harness.py'), buildSourceHead=build_head, buildSourceTree=evidence['sourceTree'],
                  buildSourceDelta=build_delta, buildReusePolicy='identical-complete-frontend-tree-and-input-hashes',
                  sourceRoot=str(root), bundleRoot=str(bundle), sourceHashesBefore=hashes(), bundleHashesBefore=export_hashes(bundle),
                  productionWrites=0, realModel=False, realCloud=False, physicalTelevision=False,
                  scope='Only requestedCases ran as real local Flask/SQLite/HTTPS/Edge reminder flows. Real task edits, read/snooze and receipt persistence. Frozen reminder clock and initial synthetic cloud mirror; successful business responses are never mocked. No cloud/model/production acceptance.')
    original_connect = socket.socket.connect
    def local_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
            report['externalRequests'].append({'kind': 'non-loopback socket'})
            raise AssertionError('External network forbidden')
        return original_connect(sock, address)
    runtime_bundle = Path('\\\\?\\' + str(bundle)) if os.name == 'nt' and not str(bundle).startswith('\\\\?\\') else bundle
    try:
        with patch.object(socket.socket, 'connect', local_connect), sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            try:
                Run.run_scenarios(root, runtime_bundle, report, out, browser, temp_root, cases)
                assert len(report['checks']) == len(cases) and len(report['screenshots']) == expected_screenshots
                assert [case['name'] for case in report['scenarioResults']] == list(cases)
                assert not any(report[key] for key in ('scenarioFailures', 'pageErrors', 'externalRequests', 'unexpectedProviderAttempts'))
                report['passed'] = True
            finally:
                browser.close()
    except Exception:
        report['failure'] = traceback.format_exc(); print(report['failure'], flush=True)
    finally:
        try:
            report['sourceHashesAfter'], report['bundleHashesAfter'] = hashes(), export_hashes(bundle)
            report['sourceUnchanged'] = report['sourceHashesBefore'] == report['sourceHashesAfter']
            report['bundleUnchanged'] = report['bundleHashesBefore'] == report['bundleHashesAfter']
            report['fixtureHashesAfter'] = {name: sha(Path(path)) for name, path in report.get('fixtureActualPaths', {}).items()}
            report['fixturesUnchanged'] = bool(report.get('fixtureHashes')) and report['fixtureHashesAfter'] == report['fixtureHashes']
            report['sourceStillFrozen'] = git('rev-parse', 'HEAD') == head and git('rev-parse', 'HEAD^{tree}') == tree and not git('status', '--porcelain=v1')
            report['temporaryFixtureRemoved'] = len(report['scenarioResults']) == len(cases) and all(c['temporaryFixtureRemoved'] for c in report['scenarioResults'])
            report['passed'] = report['passed'] and all(report[k] for k in ('sourceUnchanged', 'bundleUnchanged', 'fixturesUnchanged', 'sourceStillFrozen', 'temporaryFixtureRemoved'))
        except Exception:
            report['passed'] = False; report['finalEvidenceFailure'] = traceback.format_exc()
        with (out / 'result.json').open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2); stream.write('\n')
        print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'report': str(out / 'result.json')}, ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
