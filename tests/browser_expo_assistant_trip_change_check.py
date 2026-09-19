"""Synthetic local Flask/SQLite/Edge trip-change flows; real business responses.

Requires a frozen integrated source and its exact Expo build. Only a real
committed response is dropped; no business response or model answer is mocked.
Preparing/AST-checking this harness is not browser acceptance.
"""
import argparse
from contextlib import ExitStack, closing
from datetime import datetime, timezone
import hashlib
import json
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
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright
import browser_expo_finance_check as fixture
from browser_expo_finance_check import Run as BaseRun, button, sha

HARNESS = 'tests/browser_expo_assistant_trip_change_check.py'
CASES = ('reschedule_and_recover', 'choose_clarify_and_stale', 'identity_and_search')
CHANGE = '/api/assistant/trip-change'
TITLE = '合成冰岛旅行'


class Run(BaseRun):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        assert Path(self.source.__file__).resolve() == (self.root / 'app.py').resolve()
        assert CHANGE in {rule.rule for rule in self.application.url_map.iter_rules()}, 'Integrated trip-change route is required'
        paths = {HARNESS: str(Path(__file__).resolve()), 'tests/browser_expo_finance_check.py': str(Path(fixture.__file__).resolve())}
        for module in ('test_financial_files', 'test_app', 'assistant_trip_intent', 'assistant_trip_change_api', 'home_assistant'):
            key = ('tests/' if module.startswith('test_') else '') + module + '.py'
            paths[key] = str(Path(sys.modules[module].__file__).resolve())
        digests = {name: sha(Path(path)) for name, path in paths.items()}
        assert all(value == sha(self.root / name) for name, value in digests.items())
        assert digests[HARNESS] == self.report['harnessSha256']
        assert self.report.setdefault('fixtureActualPaths', paths) == paths
        assert self.report.setdefault('fixtureHashes', digests) == digests
        def forbidden_provider(*_args, **_kwargs):
            self.report['providerAttempts'].append(self.out.name)
            raise AssertionError('Real model calls are forbidden in local browser acceptance')
        self.lifecycle.enter_context(patch.object(sys.modules['home_assistant'], '_model_json', forbidden_provider))
        self.exchange_number = 0

    def clear_finance(self):
        pass  # Every scenario has a new isolated temporary database.

    def protected(self):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database)) as con:
            return {name: hashlib.sha256(repr(sorted(con.execute('SELECT * FROM ' + name).fetchall(), key=repr)).encode()).hexdigest()
                    for name in ('entities', 'journey_workflows', 'journey_links', 'journey_actions', 'assistant_plans', 'hub_transactions')}

    def seed_trip(self, ctx, title=TITLE):
        plan = dict(title=title, start='2028-03-02', end='2028-03-04', international=True,
            memberIds=['member1', 'member2'], budget=123450, paid=10000, saved=20000,
            destinations=[dict(key='iceland', city='雷克雅未克', country='冰岛', arrival='2028-03-02', departure='2028-03-04')],
            checklist=[dict(key='packing', title='合成打包行李', owner='member1', due='2028-03-01')], shopping=[], segments=[])
        preview = self.write(ctx, 'POST', '/api/journeys/preview', {'plan': plan})
        receipt = self.write(ctx, 'POST', '/api/journeys/apply', dict(previewToken=preview['previewToken'], idempotencyKey=uuid4().hex), 201)
        return self.get(ctx, '/api/journeys/' + receipt['id'])

    def open_assistant(self, page):
        page.goto(self.base + '/app/assistant')
        expect(page.get_by_role('textbox', name='告诉助理你的需求', exact=True)).to_be_enabled(timeout=15000)

    def actual_post(self, page, path, action, status=200, drop=False, after_response=None):
        self.exchange_number += 1
        calls, url = [], self.base + path
        saved = self.out / ('exchange-%02d.body' % self.exchange_number)
        def intercept(route):
            assert route.request.method == 'POST'
            response = route.fetch(max_redirects=0)
            raw = response.body(); saved.write_bytes(raw)
            calls.append(dict(payload=route.request.post_data_json, status=response.status, result=json.loads(raw), responseSha256=sha(saved)))
            if after_response:
                assert 'set-cookie' not in response.headers
                after_response()
            if drop:
                route.abort('failed')
            else:
                route.fulfill(status=response.status, headers=response.headers, body=raw)
        page.route(url, intercept)
        try:
            action(); self.settle(page, lambda: len(calls) >= 1)
            assert len(calls) == 1 and calls[0]['status'] == status, calls
            return calls[0]
        finally:
            page.unroute(url, intercept)

    def initial(self, page, prompt, **kwargs):
        page.get_by_role('textbox', name='告诉助理你的需求', exact=True).fill(prompt)
        result = self.actual_post(page, CHANGE, lambda: button(page, '整理并预览').click(), **kwargs)
        assert result['payload'] == dict(prompt=prompt, useModel=False)
        return result['result']

    def capture(self, page, width):
        page.set_viewport_size({'width': width, 'height': 1000 if width >= 1280 else 844})
        page.evaluate('() => document.fonts.ready')
        button(page, '核对改期影响').scroll_into_view_if_needed()
        page.evaluate('() => new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
        metrics = page.evaluate('''() => ({width:innerWidth,scroll:document.documentElement.scrollWidth,
          clipped:[...document.querySelectorAll('[data-testid="assistant-trip-change-panel"] [role="button"], [data-testid="assistant-trip-change-panel"] textarea')]
          .filter(n=>{const r=n.getBoundingClientRect();return r.width>0&&r.height>0&&r.bottom>0&&r.top<innerHeight&&(r.left< -2||r.right>innerWidth+2)})
          .map(n=>({label:n.getAttribute('aria-label')||n.textContent,box:n.getBoundingClientRect().toJSON()}))})''')
        assert metrics['scroll'] <= width + 2 and not metrics['clipped'], metrics
        path = self.out / f'trip-change-{width}.png'; page.screenshot(path=str(path), full_page=False)
        self.report['screenshots'].append(dict(path=path.relative_to(self.out.parent).as_posix(), sha256=sha(path), width=width, metrics=metrics,
            scope='Settled visible viewport, not a whole internal ScrollView or physical-device check.'))

    def reschedule_and_recover(self, browser):
        with self.flow(browser) as (ctx, page):
            trip = self.seed_trip(ctx); before = self.protected(); self.open_assistant(page)
            result = self.initial(page, '把' + TITLE + '延后三天')
            assert result['status'] == 'ready' and result['source']['journeyId'] == trip['id']
            expect(page.get_by_test_id('assistant-trip-change-suggestion')).to_contain_text('2028-03-05', timeout=15000)
            assert self.protected() == before
            for width in (390, 1280): self.capture(page, width)
            reads = self.count_requests('GET', '/api/journeys/' + trip['id'] + '/reschedule')
            button(page, '核对改期影响').click()
            expect(page.get_by_role('textbox', name='新的出发日期', exact=True)).to_have_value('2028-03-05', timeout=15000)
            expect(page.get_by_role('textbox', name='新的返程日期', exact=True)).to_have_value('2028-03-07')
            assert self.count_requests('GET', '/api/journeys/' + trip['id'] + '/reschedule') > reads
            choice = page.get_by_role('checkbox', name='联动改期：合成打包行李', exact=True)
            expect(choice).not_to_be_checked(); choice.click()
            preview = self.actual_post(page, '/api/journeys/' + trip['id'] + '/reschedule-preview', lambda: button(page, '预览改期').click())
            assert preview['payload']['selectedKeys'] == ['task:packing'] and preview['result']['canApply']
            assert self.protected() == before
            saved = self.actual_post(page, '/api/journeys/apply', lambda: button(page, '确认改期').click(), drop=True)
            expect(page.get_by_test_id('journey-reschedule-unknown')).to_be_visible(timeout=15000)
            expect(button(page, '返回旅行')).to_be_disabled()
            key = saved['payload']['idempotencyKey']
            assert self.get(ctx, '/api/journeys/operations/' + key)['found']
            button(page, '核对保存结果').click()
            expect(button(page, '返回旅行详情')).to_be_visible(timeout=15000)
            assert self.count_requests('POST', '/api/journeys/apply') == 1
            after = self.get(ctx, '/api/journeys/' + trip['id'])
            assert after['tripId'] == trip['tripId'] and after['revision'] == trip['revision'] + 1
            assert after['trip']['start'] == '2028-03-05' and after['trip']['end'] == '2028-03-07'
            assert next(t for t in after['tasks'] if t['workflowKey'] == 'task:packing')['due'] == '2028-03-04'
            assert all(after['trip'][key] == trip['trip'][key] for key in ('budget', 'paid', 'saved'))
            button(page, '返回旅行详情').click()
            expect(page.get_by_role('heading', name='旅行详情', exact=True)).to_be_visible(timeout=15000)
            self.restart(); assert self.get(ctx, '/api/journeys/' + trip['id']) == after
            self.passed('Natural-language existing-trip input -> fresh source -> explicit association selection -> original preview/apply; dropped real committed response recovers once and persists after restart')

    def choose_clarify_and_stale(self, browser):
        with self.flow(browser) as (ctx, page):
            first = self.seed_trip(ctx, '合成冰岛秋季旅行'); self.seed_trip(ctx, '合成冰岛冬季旅行')
            self.open_assistant(page); before = self.protected()
            result = self.initial(page, '把合成冰岛旅行延后三天'); assert result['status'] == 'choose_trip'
            selected = next(c for c in result['candidates'] if c['journeyId'] == first['id'])
            picked = self.actual_post(page, CHANGE, lambda: button(page, '选择旅行 合成冰岛秋季旅行 2028-03-02').click())
            assert picked['payload'] == dict(selectionToken=result['selectionToken'], selectedRef=selected['ref'])
            assert picked['result']['status'] == 'ready' and self.protected() == before
            field = page.get_by_role('textbox', name='改期需求', exact=True)
            field.fill('把合成冰岛秋季旅行改到10月8日')
            missing = self.actual_post(page, CHANGE, lambda: button(page, '整理改期建议').click())
            assert missing['result']['missingFields'] == ['year'] and missing['result']['draft'] is None
            expect(page.get_by_test_id('assistant-trip-change-clarification')).to_contain_text('请补充年份')
            expect(button(page, '核对改期影响')).to_have_count(0)
            field.fill('把合成冰岛旅行延后三天')
            choices = self.actual_post(page, CHANGE, lambda: button(page, '整理改期建议').click())['result']
            self.write(ctx, 'PATCH', '/api/items/trips/' + first['tripId'], {'revision': first['trip']['revision'], 'title': '合成冰岛秋季旅行新标题'})
            rejected = self.actual_post(page, CHANGE, lambda: button(page, '选择旅行 合成冰岛秋季旅行 2028-03-02').click(), status=409)
            assert rejected['payload']['selectionToken'] == choices['selectionToken']
            expect(page.get_by_text('旅行来源或选择期限已变化。需求仍保留，请重新整理。', exact=True)).to_be_visible()
            field.fill('把合成冰岛秋季旅行延后三天')
            ready = self.actual_post(page, CHANGE, lambda: button(page, '整理改期建议').click())['result']
            assert ready['status'] == 'ready'
            live = self.get(ctx, '/api/journeys/' + first['id'])['trip']
            self.write(ctx, 'PATCH', '/api/items/trips/' + first['tripId'], {'revision': live['revision'], 'title': '合成冰岛秋季旅行再次改名'})
            button(page, '核对改期影响').click()
            expect(page.get_by_text('旅行内容已变化，请返回助理重新整理需求。原建议没有带入或保存。', exact=True)).to_be_visible(timeout=15000)
            expect(page.get_by_role('textbox', name='新的出发日期', exact=True)).to_have_count(0)
            assert self.count_requests('POST', '/api/journeys/' + first['id'] + '/reschedule-preview') == 0
            self.passed('Actual multi-candidate ticket selection, missing-year clarification, stale-ticket 409 and renamed-source rejection preserve the original request without unintended preview/apply')

    def identity_and_search(self, browser):
        with self.flow(browser) as (ctx, page):
            self.seed_trip(ctx); self.open_assistant(page); before = self.protected()
            page.get_by_role('textbox', name='告诉助理你的需求', exact=True).fill('搜索 ' + TITLE)
            found = self.actual_post(page, '/api/assistant/plan', lambda: button(page, '整理并预览').click())
            assert found['result']['mode'] == 'local' and found['payload']['useModel'] is False
            assert self.count_requests('POST', CHANGE) == 0 and self.protected() == before
            self.open_assistant(page)
            result = self.initial(page, '把' + TITLE + '延后三天', after_response=lambda: self.login(ctx, 2))
            assert result['status'] == 'ready'  # Real old-session response, delivered unchanged.
            self.settle(page, lambda: self.get(ctx, '/api/me')['user']['id'] == 'member2')
            original = page.get_by_role('textbox', name='告诉助理你的需求', exact=True)
            expect(original).to_be_enabled(timeout=15000)
            expect(original).to_have_value('')
            expect(page.get_by_test_id('assistant-trip-change-suggestion')).to_have_count(0, timeout=15000)
            expect(page.get_by_role('textbox', name='改期需求', exact=True)).to_have_count(0, timeout=15000)
            assert self.protected() == before and self.count_requests('POST', '/api/journeys/apply') == 0
            self.passed('Explicit search remains local; another actual session replaces the actor during a real response and the prior request/suggestion is cleared before handoff')

    @classmethod
    def run_scenarios(cls, root, bundle, report, out, browser):
        for name in CASES:
            case_out = out / name; case_out.mkdir(); folder = None
            before = len(report['checks']); case = dict(name=name, passed=False)
            try:
                with ExitStack() as lifecycle:
                    folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='expo-trip-change-')))
                    run = cls(root, bundle, folder, report, case_out, lifecycle)
                    getattr(run, name)(browser)
                assert len(report['checks']) == before + 1 and not folder.exists()
                case['passed'] = True
            except Exception:
                del report['checks'][before:]
                failure = traceback.format_exc(); (case_out / 'failure.txt').write_text(failure, encoding='utf-8')
                report['scenarioFailures'].append(dict(scenario=name, traceback=failure))
                print('FAIL ' + name + '\n' + failure, flush=True)
            finally:
                case['temporaryFixtureRemoved'] = folder is not None and not folder.exists()
                report['scenarioResults'].append(case)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path); parser.add_argument('--expected-head', required=True)
    parser.add_argument('--bundle', required=True, type=Path); parser.add_argument('--expected-build-evidence', required=True)
    args = parser.parse_args(); root, bundle = args.source_root.resolve(), args.bundle.resolve()
    assert sys.dont_write_bytecode and not sys.flags.optimize
    assert re.fullmatch('[a-f0-9]{40}', args.expected_head) and re.fullmatch('[a-f0-9]{64}', args.expected_build_evidence)
    def git(*command): return subprocess.check_output(['git', '--no-replace-objects', *command], cwd=root, text=True).strip()
    head, tree = git('rev-parse', 'HEAD'), git('rev-parse', 'HEAD^{tree}')
    assert head == args.expected_head and not git('status', '--porcelain=v1')
    evidence_path = bundle.parent / 'build-evidence.json'; assert sha(evidence_path) == args.expected_build_evidence
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    assert evidence['sourceHead'] == head and evidence['sourceTree'] == tree
    names = subprocess.check_output(['git', '--no-replace-objects', 'ls-files', '-z'], cwd=root).decode('utf-8').rstrip('\0').split('\0')
    def hashes(): return {name: sha(root / name) for name in names}
    def exports(): return {p.relative_to(bundle).as_posix(): sha(p) for p in bundle.rglob('*') if p.is_file()}
    assert exports() == evidence['files'] and all(sha(root / name) == value for name, value in evidence['inputFiles'].items())
    assert sha(Path(__file__)) == sha(root / HARNESS)
    out = Path(__file__).resolve().parents[1] / 'test-results' / ('expo-trip-change-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True); shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], providerAttempts=[], screenshots=[], scenarioResults=[], scenarioFailures=[],
        requestedChecks=len(CASES), head=head, tree=tree, buildSourceHead=evidence['sourceHead'], buildSourceTree=evidence['sourceTree'],
        buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(out / 'executed-harness.py'), sourceRoot=str(root), bundleRoot=str(bundle),
        sourceHashesBefore=hashes(), bundleHashesBefore=exports(), productionWrites=0, realModel=False, realCloud=False, physicalTelevision=False,
        scope='Three independent temporary Flask/SQLite/HTTPS/Edge local-intent trip-change scenarios; real business HTTP, no model/provider call or production data.')
    original_connect = socket.socket.connect
    def local_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
            report['externalRequests'].append({'kind': 'non-loopback socket'}); raise AssertionError('External network forbidden')
        return original_connect(sock, address)
    try:
        with patch.object(socket.socket, 'connect', local_connect), sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            try:
                Run.run_scenarios(root, bundle, report, out, browser)
                assert len(report['checks']) == len(CASES) and len(report['screenshots']) == 2
                assert not report['scenarioFailures'] and not report['pageErrors'] and not report['externalRequests'] and not report['providerAttempts']
                report['passed'] = True
            finally: browser.close()
    except Exception:
        report['failure'] = traceback.format_exc(); print(report['failure'], flush=True)
    finally:
        report['sourceHashesAfter'], report['bundleHashesAfter'] = hashes(), exports()
        report['sourceUnchanged'] = report['sourceHashesBefore'] == report['sourceHashesAfter']
        report['bundleUnchanged'] = report['bundleHashesBefore'] == report['bundleHashesAfter']
        report['fixtureHashesAfter'] = {name: sha(Path(path)) for name, path in report.get('fixtureActualPaths', {}).items()}
        report['fixturesUnchanged'] = bool(report.get('fixtureHashes')) and report['fixtureHashesAfter'] == report['fixtureHashes']
        report['sourceStillFrozen'] = git('rev-parse', 'HEAD') == head and git('rev-parse', 'HEAD^{tree}') == tree and not git('status', '--porcelain=v1')
        report['temporaryFixtureRemoved'] = len(report['scenarioResults']) == len(CASES) and all(c['temporaryFixtureRemoved'] for c in report['scenarioResults'])
        report['passed'] = report['passed'] and all(report[k] for k in ('sourceUnchanged', 'bundleUnchanged', 'fixturesUnchanged', 'sourceStillFrozen', 'temporaryFixtureRemoved'))
        (out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(dict(passed=report['passed'], checks=len(report['checks']), report=str(out / 'result.json')), ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    raise SystemExit(main())
