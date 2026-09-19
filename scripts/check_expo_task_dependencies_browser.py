"""Three bound Expo task-dependency flows on real temporary Flask/SQLite/HTTPS/Edge.

Only historical missing-reference setup uses SQL. Core mutations use real HTTP.
Faults discard a real committed reply or replace its transport status with 503;
they never fabricate a successful mutation, task DTO, or authorization result.
"""
import argparse
from contextlib import ExitStack, closing
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

HARNESS = 'scripts/check_expo_task_dependencies_browser.py'
BUILD_REUSE_PATHS = frozenset({HARNESS, 'tests/test_task_dependencies_browser.py',
                             'docs/EXPO-TASK-DEPENDENCIES-BROWSER.md'})
CASES = ('selection_completion', 'invalid_conflict_clear', 'committed_response_lost')
WIDTHS = (390, 1280)
ITEMS = '/api/items/tasks'
UNKNOWN = '暂时无法确认保存结果。请先关闭并刷新清单，核对后再操作，避免重复添加。'


def build_source_delta(git, head, evidence, build_head):
    assert re.fullmatch('[a-f0-9]{40}', build_head)
    assert evidence['sourceHead'] == build_head
    assert evidence['sourceTree'] == git('rev-parse', build_head + '^{tree}')
    assert git('merge-base', build_head, head) == build_head, 'Build source must be an ancestor'
    changed = git('diff', '--name-only', build_head, head).splitlines()
    assert set(changed) <= BUILD_REUSE_PATHS, 'Build reuse permits only this reviewed harness, its tests and documentation'
    return changed


def deliver(route, response, fault=None):
    """A transport fault is allowed only AFTER a genuine successful HTTP reply."""
    assert fault in (None, 'abort', 'gateway503')
    if fault:
        assert response.status in (200, 201), 'A failed backend write cannot prove a lost committed reply'
    if fault == 'abort':
        route.abort('failed')
    elif fault == 'gateway503':
        route.fulfill(status=503, content_type='application/json',
                      body=json.dumps({'error': 'Synthetic gateway lost the committed reply'}))
    else:
        route.fulfill(status=response.status, headers=response.headers, body=response.body())


def textbox(page, label='名称'):
    return page.get_by_role('textbox', name=label, exact=True)


def checkbox(page, label):
    return page.get_by_role('checkbox', name=label, exact=True)


def completed_periodic_refresh(page, base, settle):
    """Observe a new state read and its following identity read, through EOF."""
    requests, responses = [], []
    def requested(req):
        if req.method == 'GET' and req.url in (base + '/api/state', base + '/api/me'):
            requests.append(req)
    def responded(response):
        if response.request in requests:
            responses.append(response)
    page.on('request', requested); page.on('response', responded)
    try:
        settle(page, lambda: any(r.url == base + '/api/state' for r in responses), timeout=16000)
        state = next(r for r in responses if r.url == base + '/api/state')
        assert state.status == 200 and state.finished() is None
        state_value = state.json()
        state_index = requests.index(state.request)
        # The /me before /state belongs to the preflight. Only a later request
        # can be household.refresh's final identity check, after Promise.all.
        def identity_responses():
            return [r for r in responses if r.url == base + '/api/me'
                    and requests.index(r.request) > state_index]
        settle(page, lambda: bool(identity_responses()))
        identity = identity_responses()[0]
        assert identity.status == 200 and identity.finished() is None
        actor = identity.json()['user']
        assert actor['role'] == 'member'
        return state_value, {'stateStatus': state.status, 'identityStatus': identity.status,
                             'stateRequestIndex': state_index,
                             'identityRequestIndex': requests.index(identity.request),
                             'identityMemberId': actor['id'], 'responseBodiesFinished': True}
    finally:
        page.remove_listener('request', requested); page.remove_listener('response', responded)


class Run(BaseRun):
    def __init__(self, root, bundle, folder, report, out, lifecycle):
        self.exchange_number = 0
        assert ThreadedWSGIServer.block_on_close is True
        lifecycle.enter_context(patch.object(ThreadedWSGIServer, 'daemon_threads', False))
        super().__init__(root, bundle, folder, report, out, lifecycle)
        assert not self.server.daemon_threads
        paths = {HARNESS: Path(__file__), 'tests/browser_expo_finance_check.py': Path(fixture.__file__),
                 'tests/browser_expo_assistant_trip_items_check.py': Path(sys.modules['browser_expo_assistant_trip_items_check'].__file__)}
        paths.update({name + '.py': Path(sys.modules[name].__file__) for name in
                      ('app', 'task_dependencies', 'home_assistant', 'household_routines', 'journey_workflows', 'task_publish')})
        for name, actual in paths.items():
            assert actual.resolve() == (root / name).resolve()
            digest = sha(actual)
            assert report.setdefault('fixtureHashes', {}).setdefault(name, digest) == digest
        assert report['fixtureHashes'][HARNESS] == report['harnessSha256']
        actual_paths = {name: str(path.resolve()) for name, path in paths.items()}
        assert report.setdefault('fixtureActualPaths', actual_paths) == actual_paths
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
        pass  # Every case owns its own newly created temporary database.

    def record(self, name, value, group='httpEvidence'):
        path = self.out / (name + '.json')
        with path.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        self.report[group].append({'path': path.relative_to(self.out.parent).as_posix(), 'sha256': sha(path)})
        return value

    def snapshot(self):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database)) as con:
            assert not con.execute('PRAGMA foreign_key_check').fetchall()
            return {table: sorted(con.execute('SELECT * FROM "' + table + '"').fetchall(), key=repr)
                    for table in ('entities', 'audit', 'settings', 'task_publications')}

    def proof(self, label):
        return self.record(label, self.snapshot(), 'databaseEvidence')

    def tasks(self, ctx):
        return self.get(ctx, '/api/state')['tasks']

    def task(self, ctx, uid):
        return next(t for t in self.tasks(ctx) if t['id'] == uid)

    def seed_task(self, ctx, title, **fields):
        created = self.write(ctx, 'POST', ITEMS, {'title': title, 'sourceId': '', **fields}, 201)
        return self.task(ctx, created['id'])

    def open_list(self, page):
        page.goto(self.base + '/app/tasks')
        expect(page.get_by_role('heading', name='共同待办', exact=True)).to_be_visible(timeout=15000)

    def open_home(self, page):
        page.goto(self.base + '/app/')
        expect(button(page, '全部待办')).to_be_visible(timeout=15000)

    def edit(self, page, title):
        button(page, '编辑' + title).click()
        expect(textbox(page)).to_have_value(title)

    def expand_dependencies(self, page):
        page.get_by_role('button', name=re.compile(r'^前置事项')).click()
        expect(textbox(page, '搜索前置事项')).to_be_visible()

    def exchange(self, page, path, action, *, method='PATCH', status=200, before_fetch=None, fault=None):
        self.exchange_number += 1
        stem, calls, url = 'exchange-%02d' % self.exchange_number, [], self.base + path
        def intercept(route):
            assert route.request.method == method
            if before_fetch:
                before_fetch()
            response = route.fetch(max_redirects=0)
            raw = response.body()
            saved = self.out / (stem + '.body')
            with saved.open('xb') as stream:
                stream.write(raw)
            value = {'path': path, 'method': method, 'payload': route.request.post_data_json,
                     'backendStatus': response.status, 'backendResult': json.loads(raw),
                     'backendResponseSha256': sha(saved), 'deliveredFault': fault}
            deliver(route, response, fault)
            calls.append(value)
        page.route(url, intercept, times=1)
        try:
            action()
            self.settle(page, lambda: bool(calls))
            assert len(calls) == 1 and calls[0]['backendStatus'] == status, calls
            return calls[0]
        finally:
            page.unroute(url, intercept)
            self.record(stem, calls)

    def capture(self, page, label, focus, *, full_text=None):
        expect(focus).to_be_visible()
        focus.scroll_into_view_if_needed()
        page.evaluate('() => document.fonts.ready')
        page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
        metrics = page.evaluate('''() => ({viewport:innerWidth,bodyScroll:document.body.scrollWidth,
          rootScroll:document.documentElement.scrollWidth,
          clipped:[...document.querySelectorAll('input,textarea,button,[role="button"],[role="checkbox"]')]
          .filter(n=>{const r=n.getBoundingClientRect();return r.width>0&&r.height>0&&r.bottom>0&&r.top<innerHeight&&getComputedStyle(n).visibility!=='hidden'&&(r.left< -2||r.right>innerWidth+2)})
          .map(n=>({label:n.getAttribute('aria-label')||n.textContent,box:n.getBoundingClientRect().toJSON()}))})''')
        assert metrics['viewport'] in WIDTHS
        assert metrics['bodyScroll'] <= metrics['viewport'] + 2 and metrics['rootScroll'] <= metrics['viewport'] + 2 and not metrics['clipped'], metrics
        if full_text is not None:
            text_metrics = full_text.evaluate('''node => {const range=document.createRange();range.selectNodeContents(node);
              return {content:node.textContent,clientHeight:node.clientHeight,scrollHeight:node.scrollHeight,
              box:node.getBoundingClientRect().toJSON(),text:range.getBoundingClientRect().toJSON()};}''')
            assert text_metrics['scrollHeight'] <= text_metrics['clientHeight'] + 1, text_metrics
            assert text_metrics['text']['bottom'] <= text_metrics['box']['bottom'] + 1, text_metrics
            assert text_metrics['text']['top'] >= text_metrics['box']['top'] - 1, text_metrics
            metrics['fullText'] = text_metrics
        path = self.out / (label + '.png')
        page.screenshot(path=str(path), full_page=True)
        self.report['screenshots'].append({'path': path.relative_to(self.out.parent).as_posix(), 'sha256': sha(path), 'metrics': metrics})

    def selection_completion(self, browser):
        with self.flow(browser) as (ctx, page):
            for width in WIDTHS:
                page.set_viewport_size({'width': width, 'height': 844 if width == 390 else 1000})
                first = self.seed_task(ctx, '合成前置' + str(width))
                second = self.seed_task(ctx, '合成后续' + str(width))
                self.open_list(page); self.edit(page, second['title']); self.expand_dependencies(page)
                checkbox(page, '选择前置事项：' + first['title']).click()
                selected = checkbox(page, '取消前置事项：' + first['title'])
                expect(selected).to_have_attribute('aria-checked', 'true')
                self.capture(page, 'selection-' + str(width), selected)
                saved = self.exchange(page, ITEMS + '/' + second['id'], lambda: button(page, '保存').click())
                assert saved['payload']['revision'] == second['revision']
                assert saved['payload']['dependsOn'] == [first['id']]
                expect(textbox(page)).not_to_be_visible()
                current = self.task(ctx, second['id'])
                assert current['id'] == second['id'] and current['revision'] == second['revision'] + 1
                assert current['dependsOn'] == current['blockedBy'] == [first['id']]
                assert current['dependencyStatus'] == 'blocked' and current['done'] is False
                self.open_list(page)
                expect(checkbox(page, '完成' + second['title'])).to_be_disabled()
                expect(page.get_by_test_id('tasks-item-' + second['id'])).to_contain_text('先完成：' + first['title'])
                self.open_home(page)
                expect(checkbox(page, '完成待办：' + second['title'])).to_be_disabled()
                self.capture(page, 'home-blocked-' + str(width), checkbox(page, '完成待办：' + second['title']))
                if width == 1280:
                    self.open_list(page)
                before_first = self.task(ctx, first['id'])
                first_control = checkbox(page, ('完成' if width == 1280 else '完成待办：') + first['title'])
                done_first = self.exchange(page, ITEMS + '/' + first['id'], lambda: first_control.click())
                assert done_first['payload'] == {'revision': before_first['revision'], 'done': True}
                self.settle(page, lambda: self.task(ctx, first['id'])['done'])
                self.open_home(page) if width == 1280 else self.open_list(page)
                ready = checkbox(page, ('完成待办：' if width == 1280 else '完成') + second['title'])
                expect(ready).to_be_enabled()
                self.capture(page, 'ready-' + str(width), ready)
                saved_second = self.exchange(page, ITEMS + '/' + second['id'], lambda: ready.click())
                assert saved_second['payload'] == {'revision': current['revision'], 'done': True}
                self.settle(page, lambda: self.task(ctx, second['id'])['done'])
                final = self.task(ctx, second['id'])
                assert final['dependsOn'] == [first['id']] and final['dependencyStatus'] == 'done'
                assert final['revision'] == current['revision'] + 1
                self.record('persisted-' + str(width), {'first': self.task(ctx, first['id']), 'second': final})
            self.proof('completed-database')
            self.passed('Both 390 and 1280 select original IDs/revisions; real Home/List completion waits for the prerequisite and then persists exactly once')

    def invalid_conflict_clear(self, browser):
        with self.flow(browser) as (ctx, page):
            first = self.seed_task(ctx, '合成循环起点')
            child = self.seed_task(ctx, '合成循环候选', dependsOn=[first['id']])
            racing = self.seed_task(ctx, '合成并发候选')
            lost = self.seed_task(ctx, '合成历史失效引用')
            # Historical-corruption fixture only; ordinary deletion is protected.
            assert self.database.resolve().is_relative_to(self.folder.resolve())
            with closing(sqlite3.connect(self.database)) as con, con:
                raw = json.loads(con.execute('SELECT data FROM entities WHERE id=?', (lost['id'],)).fetchone()[0])
                con.execute('UPDATE entities SET data=?,revision=revision+1 WHERE id=?',
                            (json.dumps({**raw, 'dependsOn': ['synthetic-missing-reference']}), lost['id']))
                con.execute("UPDATE settings SET revision=revision+1 WHERE id='meta'")
            self.proof('historical-missing-fixture')
            self.open_list(page); self.edit(page, lost['title']); self.expand_dependencies(page)
            selected = checkbox(page, '取消前置事项：已失效的前置事项')
            expect(selected).to_have_attribute('aria-checked', 'true')
            textbox(page).fill('合成失效引用草稿保留')
            before, requests = self.snapshot(), self.count_requests('PATCH', ITEMS + '/' + lost['id'])
            button(page, '保存').click()
            expect(page.get_by_role('alert')).to_contain_text('前置事项已失效')
            expect(textbox(page)).to_have_value('合成失效引用草稿保留')
            assert self.snapshot() == before and self.count_requests('PATCH', ITEMS + '/' + lost['id']) == requests
            self.capture(page, 'missing-draft-390', selected)
            button(page, '清空前置事项').click()
            cleared = self.exchange(page, ITEMS + '/' + lost['id'], lambda: button(page, '保存').click())
            assert cleared['payload']['dependsOn'] == [] and cleared['payload']['revision'] == lost['revision'] + 1
            expect(textbox(page)).not_to_be_visible()
            assert self.task(ctx, lost['id'])['dependsOn'] == []
            self.open_list(page); self.edit(page, first['title']); self.expand_dependencies(page)
            expect(checkbox(page, '选择前置事项：' + first['title'])).to_have_count(0)
            expect(checkbox(page, '选择前置事项：' + child['title'])).to_have_count(0)
            checkbox(page, '选择前置事项：' + racing['title']).click()
            textbox(page).fill('合成并发409草稿保留')
            other = self.context(browser, member=2)
            try:
                def concurrent_change():
                    # This authenticated API edit commits after the browser has
                    # selected a candidate, before its real PATCH reaches Flask.
                    self.write(other, 'PATCH', ITEMS + '/' + racing['id'],
                               {'revision': racing['revision'], 'dependsOn': [first['id']]})
                    self.record('other-member-edit', self.task(other, racing['id']))
                conflict = self.exchange(page, ITEMS + '/' + first['id'], lambda: button(page, '保存').click(),
                                         status=409, before_fetch=concurrent_change)
                assert conflict['backendResult']['code'] == 'task_dependency_cycle'
                expect(page.get_by_role('alert')).to_contain_text('你的输入仍在')
                expect(textbox(page)).to_have_value('合成并发409草稿保留')
                expect(checkbox(page, '取消前置事项：' + racing['title'])).to_have_attribute('aria-checked', 'true')
                expect(button(page, '保存')).to_be_enabled()
                assert self.task(ctx, first['id']) == first
                page.set_viewport_size({'width': 1280, 'height': 1000})
                self.capture(page, 'cycle-conflict-1280', page.get_by_role('alert'), full_text=page.get_by_role('alert'))
                button(page, '清空前置事项').click()
                saved = self.exchange(page, ITEMS + '/' + first['id'], lambda: button(page, '保存').click())
                assert saved['payload']['revision'] == first['revision'] and saved['payload']['dependsOn'] == []
                expect(textbox(page)).not_to_be_visible()
                current = self.task(ctx, first['id'])
                assert current['title'] == '合成并发409草稿保留' and current['revision'] == first['revision'] + 1
                assert current['dependsOn'] == []
                self.proof('explicit-clear-database')
            finally:
                other.close()
            self.passed('Historical missing reference stays visible and removable; cycle choices are excluded; real concurrent API edit returns cycle409 without discarding draft, then explicit clear persists')

    def committed_response_lost(self, browser):
        with self.flow(browser) as (ctx, page):
            prerequisite = self.seed_task(ctx, '合成提交恢复前置')
            for width, fault in zip(WIDTHS, ('abort', 'gateway503')):
                page.set_viewport_size({'width': width, 'height': 844 if width == 390 else 1000})
                title = '合成已提交待核对' + str(width)
                self.open_list(page); button(page, '添加待办').click(); textbox(page).fill(title)
                self.expand_dependencies(page)
                checkbox(page, '选择前置事项：' + prerequisite['title']).click()
                before = self.count_requests('POST', ITEMS)
                committed = self.exchange(page, ITEMS, lambda: button(page, '保存').click(),
                                          method='POST', status=201, fault=fault)
                uid = committed['backendResult']['id']
                assert committed['payload']['dependsOn'] == [prerequisite['id']]
                assert committed['payload']['sourceId'] == ''
                alert = page.get_by_role('alert')
                expect(alert).to_have_text(UNKNOWN)
                expect(textbox(page)).to_have_value(title); expect(textbox(page)).to_be_disabled()
                selected = checkbox(page, '取消前置事项：' + prerequisite['title'])
                expect(selected).to_have_attribute('aria-checked', 'true'); expect(selected).to_be_disabled()
                expect(textbox(page, '搜索前置事项')).to_be_disabled()
                expect(button(page, '保存')).to_be_disabled(); expect(button(page, '清空前置事项')).to_be_disabled()
                expect(page.get_by_text('已保存待办', exact=True)).not_to_be_visible()
                rows = [t for t in self.tasks(ctx) if t['title'] == title]
                assert len(rows) == 1 and rows[0]['id'] == uid and rows[0]['revision'] == 1
                assert rows[0]['dependsOn'] == [prerequisite['id']]
                with closing(sqlite3.connect(self.database)) as con:
                    assert con.execute("SELECT count(*) FROM audit WHERE action='create_tasks' AND target=?", (uid,)).fetchone()[0] == 1
                self.capture(page, fault + '-' + str(width), alert, full_text=alert)
                # Let an actual periodic read finish. It must not unlock or replay.
                reads = self.count_requests('GET', '/api/state')
                snapshot, refresh_evidence = completed_periodic_refresh(page, self.base, self.settle)
                refreshed = next(t for t in snapshot['tasks'] if t['id'] == uid)
                assert refreshed['revision'] == 1 and refreshed['dependsOn'] == [prerequisite['id']]
                page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
                expect(page.get_by_role('button', name='刷新家庭数据', exact=True, include_hidden=True)).to_be_enabled()
                expect(page.get_by_test_id('tasks-item-' + uid)).to_contain_text(title)
                assert self.count_requests('GET', '/api/state') > reads
                expect(button(page, '保存')).to_be_disabled()
                expect(textbox(page)).to_have_value(title); expect(textbox(page)).to_be_disabled()
                expect(selected).to_have_attribute('aria-checked', 'true'); expect(selected).to_be_disabled()
                assert self.count_requests('POST', ITEMS) == before + 1
                self.record('periodic-refresh-' + fault, {**refresh_evidence, 'task': refreshed,
                            'renderedOriginalTask': True, 'refreshControlEnabled': True,
                            'editorFrozen': True, 'postCount': self.count_requests('POST', ITEMS) - before})
                button(page, '关闭并核对').click()
                self.open_list(page)
                expect(page.get_by_test_id('tasks-item-' + uid)).to_contain_text(title)
                rows = [t for t in self.tasks(ctx) if t['title'] == title]
                assert len(rows) == 1 and rows[0]['id'] == uid and rows[0]['revision'] == 1
                assert self.count_requests('POST', ITEMS) == before + 1
                self.record('recovered-' + fault, rows[0])
            self.proof('recovered-database')
            self.passed('Actual POST committed before response loss or gateway503; frozen editable draft survives polling and explicit refresh discovers the original ID without repeating a write')

    @classmethod
    def run_scenarios(cls, root, bundle, report, out, browser, temp_root):
        for name in CASES:
            case_out = out / name; case_out.mkdir()
            folder, before, case = None, len(report['checks']), {'name': name, 'passed': False}
            try:
                with ExitStack() as lifecycle:
                    folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='td-', dir=temp_root)))
                    run = cls(root, bundle, folder, report, case_out, lifecycle)
                    getattr(run, name)(browser)
                assert len(report['checks']) == before + 1 and not folder.exists()
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
    args = parser.parse_args()
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
    out = root / 'test-results' / ('expo-task-dependencies-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], unexpectedProviderAttempts=[],
                  screenshots=[], scenarioResults=[], scenarioFailures=[], httpEvidence=[], databaseEvidence=[],
                  requestedChecks=len(CASES), head=head, tree=tree, buildEvidenceSha256=sha(evidence_path),
                  harnessSha256=sha(out / 'executed-harness.py'), buildSourceHead=build_head, buildSourceTree=evidence['sourceTree'],
                  buildSourceDelta=build_delta, buildReusePaths=sorted(BUILD_REUSE_PATHS),
                  sourceRoot=str(root), bundleRoot=str(bundle), sourceHashesBefore=hashes(), bundleHashesBefore=export_hashes(bundle),
                  productionWrites=0, realModel=False, realCloud=False, physicalTelevision=False,
                  scope='Three real local Flask/SQLite/HTTPS/Edge flows. Original dependency CRUD, true completion/409, and committed response loss. Initial historical missing-reference fixture only; no cloud/model/production acceptance.')
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
                Run.run_scenarios(root, runtime_bundle, report, out, browser, temp_root)
                assert len(report['checks']) == len(CASES) and len(report['screenshots']) == 10
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
            report['temporaryFixtureRemoved'] = len(report['scenarioResults']) == len(CASES) and all(c['temporaryFixtureRemoved'] for c in report['scenarioResults'])
            report['passed'] = report['passed'] and all(report[k] for k in ('sourceUnchanged', 'bundleUnchanged', 'fixturesUnchanged', 'sourceStillFrozen', 'temporaryFixtureRemoved'))
        except Exception:
            report['passed'] = False; report['finalEvidenceFailure'] = traceback.format_exc()
        with (out / 'result.json').open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2); stream.write('\n')
        print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'report': str(out / 'result.json')}, ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
