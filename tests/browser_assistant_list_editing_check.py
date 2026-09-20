"""Two real assistant list workflows on isolated HTTPS/SQLite and frozen Expo.

Only delivery of real HTTP responses and synthetic session revocation are
controlled. No model/provider or business response is simulated.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
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
import threading
import traceback
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from flask import request
from playwright.sync_api import expect, sync_playwright
import browser_finance_flow_mapping_check as build_fixture
from browser_expo_assistant_places_check import button
from browser_expo_finance_check import sha
from browser_expo_local_photo_check import Run as LocalRun
from browser_expo_photo_duplicates_check import BrowserHttpGuard
from browser_expo_photo_memories_check import revoke_member_sessions

HARNESS = 'tests/browser_assistant_list_editing_check.py'
DOC = 'docs/ASSISTANT-LIST-BROWSER.md'
CASES = ('mobile_edit_save_home', 'lost_reload_identity')
CASE_SCREENSHOTS = {name: 3 for name in CASES}
TIMEOUT = 15000
STORAGE = 'family-assistant-plan-v1'


class Run(LocalRun):
    def __init__(self, root, bundle, folder, report, out, lifecycle):
        super().__init__(root, bundle, folder, report, out, lifecycle)
        self.http_guard = BrowserHttpGuard(self.base, out.name, out, report)
        self.serial = 0
        self.journal, self.journal_lock = [], threading.Lock()
        paths = [HARNESS, 'tests/browser_finance_flow_mapping_check.py',
                 'tests/browser_expo_assistant_places_check.py',
                 'tests/browser_expo_photo_duplicates_check.py',
                 'tests/browser_expo_photo_memories_check.py']
        for name in paths:
            actual = Path(sys.modules[Path(name).stem].__file__) if name != HARNESS else Path(__file__)
            assert actual.resolve() == (root / name).resolve()
        hashes = {name: sha(root / name) for name in paths}
        assert report.setdefault('listFixtureHashes', hashes) == hashes

        @self.application.after_request
        def journal(response):
            if request.path.startswith('/api/'):
                entry = dict(method=request.method, path=request.path, status=response.status_code)
                if request.method == 'POST' and request.path.startswith('/api/assistant/'):
                    entry['request'] = request.get_json(silent=True)
                with self.journal_lock:
                    self.journal.append(entry)
                    with (out / 'server-http.jsonl').open('a', encoding='utf-8', newline='\n') as stream:
                        stream.write(json.dumps(entry, ensure_ascii=False) + '\n'); stream.flush()
            return response

    def context(self, browser, member=1):
        ctx = super().context(browser, member)
        ctx.set_default_timeout(TIMEOUT); ctx.set_default_navigation_timeout(TIMEOUT)
        self.http_guard.attach(ctx)
        return ctx

    def evidence(self, name, value, group='httpEvidence'):
        self.serial += 1
        self.record(f'{self.serial:03}-{name}', value, group)

    def exchange(self, page, name, method, path, trigger, status=200):
        self.serial += 1
        return self.completed_json(page, f'{self.serial:03}-{name}', method, self.base + path, trigger, status)

    @staticmethod
    def plan_path(uid):
        assert re.fullmatch('[a-f0-9]{32}', uid)
        return '/api/assistant/plans/' + uid

    def assistant(self, page):
        page.goto(self.base + '/app/assistant'); page.bring_to_front()
        expect(page.get_by_role('heading', name='家庭助理', exact=True)).to_be_visible()
        expect(page.get_by_role('textbox', name='告诉助理你的需求', exact=True)).to_be_enabled()

    def plan(self, page, prompt):
        page.get_by_role('textbox', name='告诉助理你的需求', exact=True).fill(prompt)
        value, body = self.exchange(page, 'plan', 'POST', '/api/assistant/plan',
                                   lambda: button(page, '整理并预览').click())
        assert body == dict(prompt=prompt, useModel=False, includeHouseholdContext=False)
        assert value['mode'] == 'local' and value['actions'] and value['matches'] == []
        self.plan_path(value['id'])
        expect(page.get_by_test_id('assistant-list-apply')).to_be_enabled()
        return value

    def edit(self, page, index, data):
        page.get_by_test_id('action-edit-' + str(index)).click()
        editor = page.get_by_test_id('assistant-action-editor')
        expect(editor).to_be_visible()
        for key in ('title', 'due', 'note', 'quantity'):
            if key in data: editor.get_by_test_id('action-' + key).fill(data[key])
        if 'budget' in data:
            editor.get_by_test_id('action-budget').fill('' if data['budget'] is None else
                f"{data['budget'] // 100}.{data['budget'] % 100:02}")
        for key in ('owner', 'priority'):
            if key in data: editor.get_by_test_id('action-' + key + '-' + data[key]).get_by_role('radio').click()
        editor.get_by_test_id('action-edit-save').click()
        expect(editor).to_have_count(0)
        expect(page.get_by_test_id('assistant-list-action-' + str(index))).to_contain_text(data['title'])

    def snapshot(self):
        """Synthetic DB only. Preserve all unrelated financial/inventory/media rows."""
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        def digest(rows): return hashlib.sha256(repr(rows).encode()).hexdigest()
        with closing(sqlite3.connect(self.database)) as con:
            con.row_factory = sqlite3.Row
            names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            protected = [n for n in names if n.startswith(('hub_', 'inventory_', 'media_', 'journey_', 'cloud_'))]
            settings = [dict(r) for r in con.execute('SELECT * FROM settings ORDER BY id')]
            meta = next(r for r in settings if r['id'] == 'meta'); revision = meta['revision']; meta['revision'] = None
            return dict(entities={r['id']: dict(r) for r in con.execute('SELECT * FROM entities ORDER BY id')},
                plans=[dict(r) for r in con.execute('SELECT * FROM assistant_plans ORDER BY id')],
                audit=[dict(r) for r in con.execute('SELECT id,actor,action,target FROM audit ORDER BY id')],
                metaRevision=revision, settingsSha256=digest(settings),
                protected={n: digest(sorted([tuple(r) for r in con.execute('SELECT * FROM "' + n + '"')], key=repr)) for n in protected})

    def saved(self, before, after, plan, receipt, values):
        assert receipt['ok'] is True and receipt['destination'] == 'household'
        created = receipt['created']; assert len(created) == len(values)
        ids = [r['id'] for r in created]; assert len(set(ids)) == len(ids)
        assert set(after['entities']) - set(before['entities']) == set(ids)
        assert all(after['entities'][uid] == row for uid, row in before['entities'].items())
        for item, expected in zip(created, values):
            row = after['entities'][item['id']]; data = json.loads(row['data'])
            assert row['kind'] == item['kind'] and data['title'] == item['title']
            assert data['done'] is False
            assert all(data.get(k) == v for k, v in expected.items()), (data, expected)
        assert after['audit'][:-1] == before['audit'] and after['metaRevision'] == before['metaRevision'] + 1
        assert {k: after['audit'][-1][k] for k in ('actor', 'action', 'target')} == dict(
            actor='member1', action='assistant_plan_applied', target=plan['id'])
        assert after['protected'] == before['protected'] and after['settingsSha256'] == before['settingsSha256']
        old = {p['id']: p for p in before['plans']}; new = {p['id']: p for p in after['plans']}
        assert set(old) == set(new) and all(new[k] == v for k, v in old.items() if k != plan['id'])
        assert new[plan['id']]['applied_at'] and json.loads(new[plan['id']]['result']) == receipt
        self.evidence('original-ids-and-preservation', dict(before=before, after=after, receipt=receipt), 'databaseEvidence')

    def apply_count(self, uid):
        with self.journal_lock:
            return sum(r['method'] == 'POST' and r['path'] == self.plan_path(uid) + '/apply' for r in self.journal)

    def storage(self, page, uid):
        values = page.evaluate('key => [localStorage.getItem(key),sessionStorage.getItem(key)]', STORAGE)
        found = [json.loads(v) for v in values if v is not None]
        assert len(found) == 1 and set(found[0]) == {'memberIdentity', 'planId'}
        assert found[0]['planId'] == uid and isinstance(found[0]['memberIdentity'], str)
        self.evidence('minimal-recovery-storage', found[0])

    def mobile_edit_save_home(self, browser):
        with self.flow(browser) as (ctx, page):
            self.assistant(page)
            day = self.get(ctx, '/api/assistant/brief')['today']
            plan = self.plan(page, f'采购：{day} 合成牛奶；合成面包；合成水杯')
            assert len(plan['actions']) == 3 and plan['actions'][0]['data']['due'] == day
            base = self.snapshot()
            values = [dict(title=title, owner=owner, due=day, note='合成用户明确修改',
                           quantity='2 件', budget=budget, priority=priority) for title, owner, budget, priority in (
                ('合成全脂牛奶', 'member2', None, 'high'), ('合成全麦面包', 'shared', 0, 'normal'),
                ('合成旅行水杯', 'member1', 15990, 'low'))]
            for index, data in enumerate(values): self.edit(page, index, data)
            assert self.snapshot() == base, 'Editing a draft must not write entities or the stored plan'
            self.capture(page, 'edited-shopping-390', page.get_by_test_id('assistant-list-action-0'))
            receipt, body = self.exchange(page, 'apply-shopping', 'POST', self.plan_path(plan['id']) + '/apply',
                                         lambda: page.get_by_test_id('assistant-list-apply').click())
            assert body['selected'] == [0, 1, 2]
            assert {r['index']: r['data'] for r in body['overrides']} == dict(enumerate(values))
            self.saved(base, self.snapshot(), plan, receipt, values)
            expect(page.get_by_test_id('assistant-list-receipt')).to_contain_text('合成旅行水杯')
            button(page, '查看采购').click()
            expect(page.get_by_role('heading', name='采购清单', exact=True)).to_be_visible()
            for row in values: expect(page.locator('body')).to_contain_text(row['title'])
            page.reload(); expect(page.locator('body')).to_contain_text('合成旅行水杯')
            self.capture(page, 'saved-shopping-390', page.get_by_role('heading', name='采购清单', exact=True))
            self.assistant(page)
            task = self.plan(page, '待办：检查证件')
            value = dict(title='合成核对护照', owner='member2', due=day, note='明确分工，不调用云清单')
            before = self.snapshot(); self.edit(page, 0, value)
            result, _ = self.exchange(page, 'apply-task', 'POST', self.plan_path(task['id']) + '/apply',
                                     lambda: page.get_by_test_id('assistant-list-apply').click())
            self.saved(before, self.snapshot(), task, result, [value])
            page.goto(self.base + '/app'); home = page.get_by_test_id('home-content')
            expect(home).to_be_visible(); expect(home).to_contain_text(value['title'])
            people = {person['id']: person['name'] for person in self.get(ctx, '/api/state')['people']}
            for original, fields in zip(receipt['created'], values):
                row = page.get_by_test_id('home-shopping-' + original['id'])
                expect(row).to_contain_text(fields['title']); expect(row).to_contain_text(day)
                expect(row).to_contain_text(people.get(fields['owner'], '共同'))
                expect(row).to_contain_text({'high': '高优先级', 'normal': '普通', 'low': '低优先级'}[fields['priority']])
            self.capture(page, 'home-original-items-390', home)
            state = self.get(ctx, '/api/state')
            for result, kind, expected in ((receipt, 'shopping', values), (result, 'tasks', [value])):
                rows = {r['id']: r for r in state[kind]}
                for item, fields in zip(result['created'], expected):
                    assert all(rows[item['id']].get(k) == v for k, v in fields.items())
            self.http_guard.assert_clean()
            self.passed('390: explicit draft edits persist original IDs, null/zero/integer-cent budgets, assignments/dates and refresh/home; no unrelated business mutation')

    def lost_reload_identity(self, browser):
        with self.flow(browser) as (ctx, page):
            page.set_viewport_size({'width': 1280, 'height': 900}); self.assistant(page)
            plan = self.plan(page, '采购：合成回执唯一采购'); uid = plan['id']; path = self.plan_path(uid)
            value = dict(title='合成丢响应已提交采购', owner='member1', due='', note='仅一次明确确认',
                         quantity='1 件', budget=1234, priority='normal')
            self.edit(page, 0, value); before = self.snapshot(); lost = []
            def discard(route):
                actual = route.fetch(max_redirects=0, timeout=TIMEOUT)
                try:
                    assert actual.status == 200
                    lost.append(actual.json())
                    self.evidence('committed-before-response-loss', dict(receipt=lost[-1], request=route.request.post_data_json,
                        database=self.snapshot()), 'databaseEvidence')
                    route.abort('failed')
                finally: actual.dispose()
            page.route(self.base + path + '/apply', discard, times=1)
            # Pending is visible before transport completes; wait for our actual abort.
            with page.expect_event('requestfailed', predicate=lambda request: request.method == 'POST'
                    and request.url == self.base + path + '/apply', timeout=TIMEOUT) as aborted:
                page.get_by_test_id('assistant-list-apply').click()
            assert aborted.value.failure == 'net::ERR_FAILED'
            expect(page.get_by_test_id('assistant-list-unknown')).to_be_visible()
            expect(page.get_by_test_id('assistant-list-recheck')).to_be_enabled()
            assert len(lost) == 1; committed = self.snapshot()
            self.saved(before, committed, plan, lost[0], [value]); self.storage(page, uid)
            self.capture(page, 'unknown-original-plan-1280', page.get_by_test_id('assistant-list-unknown'))
            recovered, _ = self.exchange(page, 'get-receipt', 'GET', path,
                                        lambda: page.get_by_test_id('assistant-list-recheck').click())
            assert recovered['id'] == uid and recovered['status'] == 'applied' and recovered['receipt'] == lost[0]
            expect(page.get_by_test_id('assistant-list-receipt')).to_contain_text(value['title'])
            reload_value, _ = self.exchange(page, 'reload-same-plan', 'GET', path, lambda: page.reload())
            assert reload_value['receipt'] == lost[0]
            expect(page.get_by_test_id('assistant-list-receipt')).to_contain_text(value['title'])
            assert self.snapshot() == committed and self.apply_count(uid) == 1
            self.capture(page, 'reloaded-real-receipt-1280', page.get_by_test_id('assistant-list-receipt'))
            # Conceal on an actual browser offline event; no business DTO replacement.
            ctx.set_offline(True); page.evaluate("() => window.dispatchEvent(new Event('offline'))")
            expect(page.get_by_test_id('assistant-list-receipt')).to_have_count(0)
            ctx.set_offline(False); page.evaluate("() => window.dispatchEvent(new Event('online'))")
            expect(page.get_by_test_id('assistant-list-receipt')).to_contain_text(value['title'])
            self.identity_boundary(browser, ctx, page, uid, value['title'])
            assert self.apply_count(uid) == 1
            self.http_guard.assert_clean()
            self.passed('1280: actual commit/drop, original GET/reload without second POST, offline concealment, real member switch/revocation and late-response isolation')

    def identity_boundary(self, browser, ctx, page, uid, title):
        held = []; holding = True; url = self.base + self.plan_path(uid)
        def hold(route):
            if not holding or route.request.method != 'GET': route.continue_(); return
            actual = route.fetch(max_redirects=0, timeout=TIMEOUT)
            try:
                assert actual.status == 200 and actual.json()['status'] == 'applied'
                held.append((route, actual.status, actual.headers, actual.body()))
            finally: actual.dispose()
        page.route(url, hold)
        try:
            page.reload(); self.settle(page, lambda: bool(held), timeout=TIMEOUT)
            expect(page.get_by_test_id('assistant-list-receipt')).to_have_count(0)
            page.evaluate('''title => {
              window.__listLeaks=[];
              const check=()=>{if(document.body.innerText.includes(title)) window.__listLeaks.push(performance.now());};
              window.__listObserver=new MutationObserver(check);
              window.__listObserver.observe(document.body,{subtree:true,childList:true,characterData:true});check();
            }''', title)
            self.login(ctx, 2); pending = list(held); holding = False
            with page.expect_response(lambda r: urlsplit(r.url).path == '/api/me' and r.request.method == 'GET'
                    and r.status == 200 and r.json().get('user', {}).get('id') == 'member2', timeout=TIMEOUT) as fresh:
                for entry in pending:
                    route, status, headers, raw = entry
                    route.fulfill(status=status, headers=headers, body=raw); held.remove(entry)
            me = fresh.value.json()
            expect(button(page, me['user']['name'] + '，账户菜单')).to_be_visible()
            expect(page.get_by_test_id('assistant-list-receipt')).to_have_count(0)
            leaks = page.evaluate('() => {window.__listObserver.disconnect();return window.__listLeaks;}')
            assert leaks == []
            assert page.evaluate('key => localStorage.getItem(key)===null && sessionStorage.getItem(key)===null', STORAGE)
            peer = self.get(ctx, self.plan_path(uid), 404)
            self.evidence('late-real-owner-receipt', dict(delivered=[json.loads(e[3]) for e in pending],
                currentMember=me['user']['id'], leaks=leaks, peerDenied=peer))
            self.capture(page, 'late-owner-cleared-1280', page.locator('body'))
        finally:
            for route, *_ in held: route.abort('failed')
            page.unroute(url, hold)
        # Separately prove a real revoked session cannot recover the original plan.
        owner = self.context(browser); self.lifecycle.callback(owner.close)
        assert self.get(owner, self.plan_path(uid))['status'] == 'applied'
        changed = revoke_member_sessions(self.database, self.folder)
        denied = self.get(owner, self.plan_path(uid), 401)
        self.evidence('actual-session-revocation', dict(revoked=changed, status=401, response=denied))

    @classmethod
    def run_scenarios(cls, root, bundle, report, out, browser, temp_root, cases=CASES):
        from browser_expo_local_photo_check import CASE_SCREENSHOTS as parent_counts
        with patch.dict(parent_counts, CASE_SCREENSHOTS):
            super().run_scenarios(root, bundle, report, out, browser, temp_root, cases)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source-root', 'bundle', 'temp-root'): parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--build-source-head')
    parser.add_argument('--expected-build-evidence', required=True)
    parser.add_argument('--case', action='append', choices=CASES, dest='cases')
    args = parser.parse_args()
    if not sys.dont_write_bytecode or sys.flags.optimize: raise RuntimeError('Use -B; optimization is forbidden')
    assert re.fullmatch('[a-f0-9]{40}', args.expected_head) and re.fullmatch('[a-f0-9]{64}', args.expected_build_evidence)
    root, bundle, temp_root = args.source_root.resolve(), args.bundle.absolute(), args.temp_root.resolve()
    if os.name == 'nt' and not str(bundle).startswith('\\\\?\\'): bundle = Path('\\\\?\\' + str(bundle))
    assert temp_root.is_dir() and not temp_root.is_symlink() and not temp_root.is_junction()
    def git(*command): return subprocess.check_output(['git', '--no-replace-objects', *command], cwd=root).decode('utf-8').strip()
    head, tree = git('rev-parse', 'HEAD'), git('rev-parse', 'HEAD^{tree}')
    assert head == args.expected_head and not git('status', '--porcelain=v1')
    assert Path(__file__).resolve() == (root / HARNESS).resolve()
    build_head = args.build_source_head or head; assert re.fullmatch('[a-f0-9]{40}', build_head)
    changes = []
    if build_head != head:
        git('merge-base', '--is-ancestor', build_head, head)
        changes = git('diff', '--no-renames', '--name-only', '-z', build_head, head, '--').rstrip('\0').split('\0')
        assert set(changes) <= {HARNESS, DOC}
    evidence_path = bundle.parent / 'build-evidence.json'; assert sha(evidence_path) == args.expected_build_evidence
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    names = git('ls-files', '-z').rstrip('\0').split('\0')
    build_fixture.validate_build(git, root, build_head, evidence, names)
    for name, digest in evidence.get('additionalTestInputs', {}).items():
        assert name in names and sha(root / name) == digest
    assert build_fixture.exports(bundle) == evidence['files']
    def hashes(): return {name: sha(root / name) for name in names}
    cases = tuple(dict.fromkeys(args.cases or CASES))
    out = root / 'test-results' / ('assistant-list-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True, exist_ok=False); shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], screenshots=[], pageErrors=[], externalRequests=[], unexpectedProviderAttempts=[],
        httpEvidence=[], databaseEvidence=[], scenarioResults=[], scenarioFailures=[], requestedCases=list(cases),
        sourceHead=head, head=head, tree=tree, buildSourceHead=build_head, buildSourceTree=evidence['sourceTree'],
        buildReusePaths=changes, buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(Path(__file__)),
        sourceHashesBefore=hashes(), bundleHashesBefore=build_fixture.exports(bundle), productionWrites=0,
        realCloud=False, realModel=False, scope='Two synthetic local HTTPS/Flask/SQLite/Edge cases; real local plans, explicit UI edits and persistent commits. No external provider/user acceptance.')
    original_connect = socket.socket.connect
    def local_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
            report['externalRequests'].append({'kind': 'non-loopback socket'}); raise AssertionError('External network forbidden')
        return original_connect(sock, address)
    try:
        with patch.object(socket.socket, 'connect', local_connect), sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            try:
                Run.run_scenarios(root, bundle, report, out, browser, temp_root, cases)
                assert len(report['checks']) == len(cases) and len(report['screenshots']) == 3 * len(cases)
                assert [c['name'] for c in report['scenarioResults']] == list(cases)
                assert not any(report[k] for k in ('scenarioFailures', 'pageErrors', 'externalRequests', 'unexpectedProviderAttempts', 'unexpectedHttpServerErrors', 'httpCaptureErrors'))
                report['passed'] = True
            finally: browser.close()
    except Exception:
        report['passed'] = False; report['failure'] = traceback.format_exc(); print(report['failure'], flush=True)
    finally:
        try:
            report['sourceHashesAfter'], report['bundleHashesAfter'] = hashes(), build_fixture.exports(bundle)
            report['sourceUnchanged'] = report['sourceHashesBefore'] == report['sourceHashesAfter']
            report['bundleUnchanged'] = report['bundleHashesBefore'] == report['bundleHashesAfter']
            for key in ('fixtureHashes', 'listFixtureHashes'):
                report[key + 'After'] = {name: sha(root / name) for name in report.get(key, {})}
                assert report.get(key) and report[key + 'After'] == report[key]
            report['sourceStillFrozen'] = git('rev-parse', 'HEAD') == head and not git('status', '--porcelain=v1')
            report['temporaryFixtureRemoved'] = len(report['scenarioResults']) == len(cases) and all(c.get('listenerStopped') and c['temporaryFixtureRemoved'] for c in report['scenarioResults'])
            report['passed'] = report['passed'] and all(report[k] for k in ('sourceUnchanged', 'bundleUnchanged', 'sourceStillFrozen', 'temporaryFixtureRemoved'))
        except Exception:
            report['passed'] = False; report['finalEvidenceFailure'] = traceback.format_exc()
        build_fixture.write_json(out / 'result.json', report)
        print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'report': str(out / 'result.json')}, ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
