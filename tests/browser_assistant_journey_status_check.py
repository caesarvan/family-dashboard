"""Two real Expo/Flask/SQLite preparation-query flows with synthetic families.

Only a completed real GET is delayed for the identity test. No successful DTO,
mutation, model output or authentication result is substituted.
"""
import argparse
from contextlib import ExitStack, closing, contextmanager
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import traceback
from unittest.mock import patch
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests'), str(ROOT / 'scripts')]
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import ThreadedWSGIServer
from browser_expo_finance_check import Run as BaseRun, sha
from browser_expo_local_photo_check import Run as LocalRun
from browser_expo_assistant_trip_items_check import export_hashes
from check_expo_calendar_conflicts_browser import Run as CalendarRun

HARNESS = 'tests/browser_assistant_journey_status_check.py'
PATH = '/api/assistant/journey-status'
PREFIX = 'assistant-journey-status-'
CASES = ('original_completion_return', 'paging_offline_identity')
SHOTS = dict(zip(CASES, (3, 3)))


def button(page, text):
    return page.get_by_role('button', name=re.compile(r'^(?:\S+\s+)?' + re.escape(text) + r'$'))


def candidate_path(query, offset=0):
    return PATH + '?' + urlencode(dict(limit=20, offset=offset, q=query))


def status_path(uid, section='tasks', offset=0, version=None):
    values = dict(limit=20, offset=offset, tripId=uid, section=section)
    if version is not None:
        values['sourceVersion'] = version
    return PATH + '?' + urlencode(values)


class Run(BaseRun):
    record = LocalRun.record
    completed_json = LocalRun.completed_json
    capture = CalendarRun.capture

    def __init__(self, *args):
        lifecycle = args[-1]
        lifecycle.enter_context(patch.object(ThreadedWSGIServer, 'daemon_threads', False))
        super().__init__(*args)
        self.serial = 0
        model = importlib.import_module('home_assistant')
        def forbidden(*_args, **_kwargs):
            self.report['unexpectedProviderAttempts'].append('model/provider call')
            raise AssertionError('Status query called a model/provider')
        for name in ('_model_json', 'model_plan', 'model_journey_brief'):
            lifecycle.enter_context(patch.object(model, name, forbidden))
        for name in ('app', 'journey_workflows', 'home_assistant', 'member_sessions',
                     'browser_expo_finance_check', 'browser_expo_local_photo_check',
                     'browser_expo_assistant_trip_items_check', 'check_expo_calendar_conflicts_browser'):
            source = Path(importlib.import_module(name).__file__).resolve()
            if not source.is_relative_to(self.root):
                raise RuntimeError('Unexpected imported fixture: ' + name)
            self.report.setdefault('fixtureHashes', {})[source.relative_to(self.root).as_posix()] = sha(source)

    def start(self, port=0):
        # A synthetically configured switch proves read routing with AI enabled.
        self.cfg.update(ASSISTANT_PROVIDER='nvidia', NVIDIA_API_KEY='synthetic-not-a-credential',
                        NVIDIA_MODEL='synthetic-never-called')
        super().start(port)

    def clear_finance(self):
        pass

    def snapshot(self):
        with closing(sqlite3.connect(self.database)) as con:
            names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            result = {}
            for name in names:
                columns = [r[1] for r in con.execute('PRAGMA table_info("' + name + '")')]
                # Authentication touches its own session timestamp; business
                # entities, audit and all operation receipts remain compared.
                excluded = {'last_seen_at'} if name == 'member_sessions' else set()
                fields = ','.join('"' + c + '"' for c in columns if c not in excluded)
                rows = sorted(con.execute('SELECT ' + fields + ' FROM "' + name + '"').fetchall(), key=repr)
                result[name] = hashlib.sha256(repr(rows).encode()).hexdigest()
            return result

    def exchange(self, page, label, method, path, action, status=200):
        self.serial += 1
        value, body = self.completed_json(page, '%02d-%s' % (self.serial, label), method,
                                          self.base + path, action, status)
        return value, body

    def journey(self, ctx, title, start='2026-12-01', task_count=2):
        end = start[:8] + ('04' if start.endswith('01') else '14')
        plan = dict(title=title, start=start, end=end, budget=0,
            memberIds=['member1', 'member2'], international=False,
            destinations=[dict(key='city', city='合成目的地', country='合成地区', arrival=start, departure=end)],
            checklist=[dict(key='task-%02d' % n, title='合成准备 %02d' % n, owner='member1', dueOffsetDays=-7)
                       for n in range(task_count)],
            shopping=[dict(key='item', title='合成转换插头', owner='member2', quantity='1 件', budget=0)], segments=[])
        preview = self.write(ctx, 'POST', '/api/journeys/preview', dict(plan=plan))
        receipt = self.write(ctx, 'POST', '/api/journeys/apply',
            dict(previewToken=preview['previewToken'], idempotencyKey=secrets.token_hex(16)), 201)
        return self.get(ctx, '/api/journeys/' + receipt['id'])

    def assistant(self, page):
        page.goto(self.base + '/app/assistant')
        expect(page.get_by_role('textbox', name='告诉助理你的需求', exact=True)).to_be_enabled(timeout=15000)

    def query(self, page, prompt, term):
        page.get_by_role('textbox', name='告诉助理你的需求', exact=True).fill(prompt)
        return self.exchange(page, 'candidates', 'GET', candidate_path(term),
                             lambda: button(page, '查询').click())[0]

    def choose(self, page, uid):
        control = page.get_by_test_id(PREFIX + 'candidate-' + uid).get_by_role('button')
        value, _ = self.exchange(page, 'status', 'GET', status_path(uid), control.click)
        expect(page.get_by_test_id(PREFIX + 'status')).to_be_visible(timeout=15000)
        return value

    def original_completion_return(self, browser):
        with self.flow(browser) as (ctx, page):
            first = self.journey(ctx, '合成冰岛旅行')
            other = self.journey(ctx, '合成冰岛旅行', '2026-12-11')
            tasks = sorted(first['tasks'], key=lambda item: item['title'])
            self.write(ctx, 'PATCH', '/api/items/tasks/' + tasks[1]['id'],
                       dict(revision=tasks[1]['revision'], dependsOn=[tasks[0]['id']]))
            before = self.snapshot(); mark = len(self.requests)
            self.assistant(page)
            page.get_by_role('checkbox', name='使用已配置的 AI 整理', exact=True).click()
            result = self.query(page, '合成冰岛旅行准备得怎么样', '合成冰岛')
            assert {item['tripId'] for item in result['items']} == {first['tripId'], other['tripId']}
            expect(page.get_by_test_id(PREFIX + 'status')).to_have_count(0)
            self.capture(page, 'same-title-choice-390', page.get_by_test_id(PREFIX + 'candidate-' + first['tripId']))
            current = self.choose(page, first['tripId'])
            assert current['summary']['tasks'] == dict(done=0, total=2, remaining=2, blocked=1)
            assert current['summary']['shopping']['remaining'] == 1
            assert self.snapshot() == before
            assert all(r['method'] == 'GET' for r in self.requests[mark:] if r['path'].startswith('/api/'))
            self.capture(page, 'blocked-preparation-390', page.get_by_test_id(PREFIX + 'summary'))
            button_open = page.get_by_test_id(PREFIX + 'open')
            button_open.click()
            expect(page.get_by_role('checkbox', name='完成' + tasks[0]['title'], exact=True)).to_be_enabled(timeout=15000)
            self.exchange(page, 'complete-original-task', 'PATCH', '/api/items/tasks/' + tasks[0]['id'],
                lambda: page.get_by_role('checkbox', name='完成' + tasks[0]['title'], exact=True).click())
            purchase = first['shopping'][0]
            expect(page.get_by_role('checkbox', name='完成' + purchase['title'], exact=True)).to_be_enabled(timeout=15000)
            self.exchange(page, 'complete-original-purchase', 'PATCH', '/api/items/shopping/' + purchase['id'],
                lambda: page.get_by_role('checkbox', name='完成' + purchase['title'], exact=True).click())
            expect(button(page, '返回助理')).to_be_enabled(timeout=15000)
            current, _ = self.exchange(page, 'return-current', 'GET', status_path(first['tripId']),
                                       lambda: button(page, '返回助理').click())
            assert current['summary']['tasks'] == dict(done=1, total=2, remaining=1, blocked=0)
            assert current['summary']['shopping'] == dict(done=1, total=1, remaining=0)
            assert current['trip']['tripId'] == first['tripId']
            expect(page.get_by_test_id(PREFIX + 'question')).to_have_text('原问题：合成冰岛旅行准备得怎么样')
            self.capture(page, 'fresh-after-original-completion-390', page.get_by_test_id(PREFIX + 'summary'))
            self.exchange(page, 'return-query', 'GET', candidate_path('合成冰岛'),
                          lambda: page.get_by_test_id(PREFIX + 'back-candidates').click())
            expect(page.get_by_test_id(PREFIX + 'query')).to_have_value('合成冰岛')
            actual = self.get(ctx, '/api/journeys/' + first['id'])
            assert next(t for t in actual['tasks'] if t['id'] == tasks[0]['id'])['done'] is True
            assert actual['shopping'][0]['done'] is True
            self.record('original-entity-completion', dict(tripId=first['tripId'], taskId=tasks[0]['id'],
                        purchaseId=purchase['id'], before=before, after=self.snapshot()), 'databaseEvidence')
            self.passed('original_completion_return')

    @contextmanager
    def held_status(self, page, uid):
        held = []; url = self.base + status_path(uid)
        def hold(route):
            response = route.fetch(timeout=15000, max_redirects=0)
            assert response.status == 200 and 'set-cookie' not in response.headers
            raw = response.body()
            self.record('held-real-status', dict(status=response.status, value=json.loads(raw), sha256=hashlib.sha256(raw).hexdigest()))
            held.append((route, response.status, response.headers, raw))
        page.route(url, hold)
        try:
            yield held
        finally:
            page.unroute(url, hold)
            for route, *_ in held:
                route.abort('failed')

    def paging_offline_identity(self, browser):
        with self.flow(browser) as (ctx, page):
            page.set_viewport_size(dict(width=1280, height=1000))
            journeys = [self.journey(ctx, '合成分页旅行 %02d' % n, task_count=21) for n in range(21)]
            self.assistant(page)
            first = self.query(page, '合成分页旅行准备进度', '合成分页')
            assert first['nextOffset'] == 20 and len(first['items']) == 20
            second, _ = self.exchange(page, 'candidate-page-two', 'GET', candidate_path('合成分页', 20),
                                      lambda: page.get_by_test_id(PREFIX + 'candidates-next').click())
            assert len(second['items']) == 1
            uid = second['items'][0]['tripId']; target = next(j for j in journeys if j['tripId'] == uid)
            current = self.choose(page, uid)
            version = current['sourceVersion']
            later, _ = self.exchange(page, 'items-page-two', 'GET', status_path(uid, offset=20, version=version),
                                     lambda: page.get_by_test_id(PREFIX + 'items-next').click())
            assert len(later['items']) == 1 and later['summary']['tasks']['total'] == 21
            assert later['items'][0]['id'] not in {item['id'] for item in current['items']}
            self.capture(page, 'original-page-two-1280', page.get_by_test_id(PREFIX + 'status'))
            self.exchange(page, 'items-page-one', 'GET', status_path(uid),
                          lambda: page.get_by_test_id(PREFIX + 'items-prev').click())
            task = target['tasks'][0]
            self.write(ctx, 'PATCH', '/api/items/tasks/' + task['id'], dict(revision=task['revision'], done=True))
            stale, _ = self.exchange(page, 'stale-page', 'GET', status_path(uid, offset=20, version=version),
                lambda: page.get_by_test_id(PREFIX + 'items-next').click(), 409)
            assert stale['code'] == 'stale_journey_status'
            expect(page.get_by_test_id(PREFIX + 'summary')).to_have_count(0)
            current, _ = self.exchange(page, 'refresh-version', 'GET', status_path(uid),
                                       lambda: page.get_by_test_id(PREFIX + 'refresh').click())
            assert current['summary']['tasks']['done'] == 1 and current['summary']['tasks']['remaining'] == 20
            ctx.set_offline(True); page.evaluate("() => window.dispatchEvent(new Event('offline'))")
            expect(page.get_by_test_id(PREFIX + 'summary')).to_have_count(0)
            self.capture(page, 'offline-clears-current-1280', page.get_by_test_id(PREFIX + 'hidden'))
            ctx.set_offline(False); page.evaluate("() => window.dispatchEvent(new Event('online'))")
            expect(page.get_by_test_id(PREFIX + 'summary')).to_be_visible(timeout=20000)
            with self.held_status(page, uid) as held:
                page.get_by_test_id(PREFIX + 'refresh').click()
                self.settle(page, lambda: len(held) == 1)
                old = self.get(ctx, '/api/me')['user']['id']; self.login(ctx, 2)
                new = self.get(ctx, '/api/me')['user']['id']; assert new != old
                before = self.snapshot()
                page.evaluate('''() => {
                  window.__ajsLateSummary = false;
                  window.__ajsObserver = new MutationObserver(() => {
                    if (document.querySelector('[data-testid="assistant-journey-status-summary"]')) window.__ajsLateSummary = true;
                  });
                  window.__ajsObserver.observe(document.body, {subtree:true, childList:true});
                }''')
                route, status, headers, raw = held.pop()
                issued = []
                def requested(req):
                    if req.method == 'GET' and req.url == self.base + '/api/me':
                        issued.append(req)
                page.on('request', requested)
                try:
                    with page.expect_request_finished(predicate=lambda req: req in issued, timeout=15000) as finished:
                        route.fulfill(status=status, headers=headers, body=raw)
                    identity = finished.value.response()
                    assert identity.status == 200 and identity.json()['user']['id'] == new
                    expect(page.get_by_role('textbox', name='告诉助理你的需求', exact=True)).to_be_enabled(timeout=15000)
                finally:
                    page.remove_listener('request', requested)
                expect(page.get_by_test_id(PREFIX + 'summary')).to_have_count(0)
                expect(page.get_by_test_id(PREFIX + 'query')).to_have_count(0)
                reappeared = page.evaluate('''() => {window.__ajsObserver.disconnect(); return window.__ajsLateSummary;}''')
                assert reappeared is False
                self.record('late-identity-postflight', dict(member=new, status=identity.status,
                            completedRealIdentityRead=True, summaryReappeared=reappeared))
            self.capture(page, 'late-identity-cleared-1280', page.get_by_role('heading', name='家庭助理', exact=True))
            after = self.snapshot()
            assert before == after
            self.record('identity-business-preserved', dict(before=before, after=after, oldMember=old, newMember=new), 'databaseEvidence')
            self.passed('paging_offline_identity')

    @classmethod
    def run_scenarios(cls, root, bundle, report, out, browser, temp_root, cases):
        for name in cases:
            target = out / name; target.mkdir(); folder = None; run = None
            count = len(report['checks']); shots = len(report['screenshots']); case = dict(name=name, passed=False)
            try:
                with ExitStack() as lifecycle:
                    folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='ajs-', dir=temp_root)))
                    run = cls(root, bundle, folder, report, target, lifecycle)
                    getattr(run, name)(browser)
                assert len(report['checks']) == count + 1 and len(report['screenshots']) - shots == SHOTS[name]
                assert not folder.exists() and run.server is None and not run.thread.is_alive()
                case.update(passed=True, listenerStopped=True)
            except Exception:
                del report['checks'][count:]
                failure = traceback.format_exc(); (target / 'failure.txt').write_text(failure, encoding='utf-8')
                report['scenarioFailures'].append(dict(name=name, traceback=failure))
                print('FAIL ' + name + '\n' + failure, flush=True)
            finally:
                case['temporaryFixtureRemoved'] = folder is not None and not folder.exists()
                report['scenarioResults'].append(case)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('expected-head', 'expected-build-evidence'):
        parser.add_argument('--' + name, required=True)
    for name in ('source-root', 'bundle', 'temp-root'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--case', choices=CASES, action='append', dest='cases')
    args = parser.parse_args(); root = args.source_root.resolve(); bundle = args.bundle.absolute(); temp_root = args.temp_root.resolve()
    if sys.flags.optimize or not sys.dont_write_bytecode or root != ROOT:
        raise RuntimeError('Run the bound source without bytecode or optimized assertions')
    if not temp_root.is_dir() or temp_root.is_symlink() or temp_root.is_junction():
        raise RuntimeError('Provide an existing plain temporary root')
    def git(*a):
        return subprocess.check_output(['git', '--no-replace-objects', *a], cwd=root, text=True, encoding='utf-8').strip()
    head = git('rev-parse', 'HEAD'); tree = git('rev-parse', 'HEAD^{tree}')
    if head != args.expected_head or git('status', '--porcelain'):
        raise RuntimeError('Source is not the clean reviewed head')
    evidence_path = bundle.parent / 'build-evidence.json'
    if sha(evidence_path) != args.expected_build_evidence:
        raise RuntimeError('Build evidence changed')
    build = json.loads(evidence_path.read_text(encoding='utf-8'))
    build_head = build['sourceHead']; delta = git('diff', '--name-only', build_head, head).splitlines()
    if (git('merge-base', build_head, head) != build_head or set(delta) - {HARNESS, 'docs/ASSISTANT-JOURNEY-STATUS-BROWSER.md'}
            or git('rev-parse', build_head + ':frontend') != git('rev-parse', head + ':frontend')
            or build['sourceTree'] != git('rev-parse', build_head + '^{tree}')
            or export_hashes(bundle) != build['files']
            or any(sha(root / name) != digest for name, digest in build['inputFiles'].items())):
        raise RuntimeError('Source and Expo build are not the approved identical runtime')
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().rstrip('\0').split('\0')
    def hashes():
        return {name: sha(root / name) for name in names}
    cases = tuple(dict.fromkeys(args.cases or CASES))
    out = root / 'test-results' / ('assistant-journey-status-browser-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True, exist_ok=False)
    (out / 'executed-harness.py').write_bytes(Path(__file__).read_bytes())
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], unexpectedProviderAttempts=[],
        screenshots=[], httpEvidence=[], databaseEvidence=[], scenarioResults=[], scenarioFailures=[],
        requestedCases=list(cases), head=head, tree=tree, buildSourceHead=build_head, buildSourceDelta=delta,
        buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(Path(__file__)),
        sourceHashesBefore=hashes(), bundleHashesBefore=export_hashes(bundle), productionWrites=0,
        realCloud=False, realModel=False, physicalTelevision=False,
        scope='Actual local HTTPS/Flask/SQLite/Edge; synthetic journeys; original writes and current reads. No production, external model, cloud or physical-device acceptance.')
    connect = socket.socket.connect
    def local_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
            report['externalRequests'].append({'kind': 'non-loopback socket'})
            raise AssertionError('External network forbidden')
        return connect(sock, address)
    runtime_bundle = Path('\\\\?\\' + str(bundle)) if os.name == 'nt' and not str(bundle).startswith('\\\\?\\') else bundle
    try:
        with patch.object(socket.socket, 'connect', local_connect), sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            try:
                Run.run_scenarios(root, runtime_bundle, report, out, browser, temp_root, cases)
            finally:
                browser.close()
        report['passed'] = (len(report['checks']) == len(cases) and
            not any(report[k] for k in ('pageErrors', 'externalRequests', 'unexpectedProviderAttempts', 'scenarioFailures')))
    except Exception:
        report['failure'] = traceback.format_exc(); print(report['failure'], flush=True)
    finally:
        report['sourceUnchanged'] = hashes() == report['sourceHashesBefore']
        report['bundleUnchanged'] = export_hashes(bundle) == report['bundleHashesBefore']
        report['sourceStillFrozen'] = git('rev-parse', 'HEAD') == head and not git('status', '--porcelain')
        report['fixturesUnchanged'] = all(sha(root / p) == h for p,h in report.get('fixtureHashes', {}).items())
        report['passed'] = report['passed'] and all(report[k] for k in ('sourceUnchanged', 'bundleUnchanged', 'sourceStillFrozen', 'fixturesUnchanged'))
        (out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(dict(passed=report['passed'], checks=len(report['checks']), report=str(out / 'result.json'))), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
