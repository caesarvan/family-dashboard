"""Three isolated local-calendar privacy flows using real Flask/SQLite/HTTPS/Edge.

Only identity transport failures and offline delivery are injected. Event CRUD,
member sessions, TV pairing, assistant reads and exports reach the real app.
"""
import argparse
from contextlib import ExitStack, closing
from datetime import datetime, timezone
from io import BytesIO
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
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import ThreadedWSGIServer
from scripts import check_expo_calendar_conflicts_browser as calendar
from scripts import check_expo_task_dependencies_browser as previous
from browser_expo_finance_check import Run as BaseRun, button, sha
from browser_expo_assistant_trip_items_check import export_hashes

HARNESS = 'scripts/check_expo_calendar_privacy_browser.py'
BUILD_REUSE_PATHS = frozenset({HARNESS, 'tests/test_expo_calendar_privacy_browser.py', 'docs/EXPO-CALENDAR-PRIVACY-BROWSER.md'})
CASES = ('private_share_revoke', 'withdrawal_identity', 'identity_failure_draft')
CASE_SCREENSHOTS = dict(zip(CASES, (3, 2, 3)))
ITEMS, NOW, DAY = calendar.ITEMS, calendar.NOW, calendar.DAY


def selected_cases(values):
    if values is None:
        return CASES
    if not values or any(value not in CASES for value in values):
        raise ValueError('Select at least one known browser case')
    return tuple(dict.fromkeys(values))


def build_source_delta(git, head, evidence, build_head):
    assert re.fullmatch('[a-f0-9]{40}', build_head)
    assert evidence['sourceHead'] == build_head
    assert evidence['sourceTree'] == git('rev-parse', build_head + '^{tree}')
    assert git('merge-base', build_head, head) == build_head, 'Build source must be an ancestor'
    assert git('rev-parse', build_head + ':frontend') == git('rev-parse', head + ':frontend'), 'Complete frontend must be identical'
    changed = git('diff', '--name-only', build_head, head).splitlines()
    assert set(changed) <= BUILD_REUSE_PATHS, 'Only this reviewed harness, tests and document may differ'
    return changed


def exclusive_output(root):
    out = root / 'test-results' / ('expo-calendar-privacy-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True, exist_ok=False)
    return out


def textbox(page):
    return page.get_by_role('textbox', name='名称', exact=True)


class Run(calendar.Run):
    # Reuse HTTP exchange evidence, safe fixture lifecycle, DOM measurements and
    # failure capture. No modification of the shared helpers or business DTOs.
    def __init__(self, root, bundle, folder, report, out, lifecycle):
        self.exchange_number = 0
        assert ThreadedWSGIServer.block_on_close is True
        lifecycle.enter_context(patch.object(ThreadedWSGIServer, 'daemon_threads', False))
        BaseRun.__init__(self, root, bundle, folder, report, out, lifecycle)
        paths = {HARNESS: Path(__file__), 'scripts/check_expo_calendar_conflicts_browser.py': Path(calendar.__file__),
                 'scripts/check_expo_task_dependencies_browser.py': Path(previous.__file__)}
        paths.update({name + '.py': Path(sys.modules[name].__file__) for name in
                      ('app', 'calendar_privacy', 'cloud_accounts', 'cloud_providers', 'home_assistant',
                       'data_portability', 'member_sessions', 'membership_storage')})
        paths.update({'tests/' + name + '.py': Path(sys.modules[name].__file__) for name in
                      ('browser_expo_finance_check', 'browser_expo_assistant_trip_items_check')})
        for name, actual in paths.items():
            assert actual.resolve() == (root / name).resolve()
            assert report.setdefault('fixtureHashes', {}).setdefault(name, sha(actual)) == sha(actual)
        actual_paths = {name: str(path.resolve()) for name, path in paths.items()}
        assert report.setdefault('fixtureActualPaths', actual_paths) == actual_paths
        assert report['fixtureHashes'][HARNESS] == report['harnessSha256']
        for name in ('_model_json', 'model_plan', 'model_journey_brief'):
            lifecycle.enter_context(patch.object(sys.modules['home_assistant'], name, self.forbidden_provider))
        lifecycle.enter_context(patch.object(self.application.extensions['cloud_accounts'], 'active_provider', self.forbidden_provider))

    def open(self, page, route='calendar'):
        super().open(page, route)
        # RN Web Animated interpolates with Date.now(). Keep the synthetic
        # calendar date but release the inherited fixed clock for animations.
        page.clock.set_system_time(NOW)
        before = page.evaluate('Date.now()')
        page.wait_for_function('before => Date.now() > before + 32', arg=before, polling='raf', timeout=5000)
        clock = page.evaluate('() => ({now: Date.now(), day: new Date().toISOString().slice(0, 10)})')
        assert clock['day'] == DAY and 0 < clock['now'] - before < 5000
        self.report.setdefault('clockEvidence', []).append({'before': before, **clock})

    def seed_event(self, ctx, title, **fields):
        created = self.write(ctx, 'POST', ITEMS, dict(title=title, owner='member1', start=DAY + 'T09:00:00+08:00',
            end=DAY + 'T11:00:00+08:00', location=title + '地点', **fields), 201)
        return self.event(ctx, created['id'])

    def edit_event(self, page, event):
        button(page, '编辑安排：' + event['title']).click()
        expect(textbox(page)).to_have_value(event['title'])

    def scope(self, page, value):
        return page.get_by_role('radio', name='日程可见范围：' + {'private': '仅自己', 'shared': '家庭共享'}[value], exact=True)

    def refresh_calendar(self, page):
        # Register observers before triggering, and identify the trailing /me by
        # request order. This also works while Paper's edit dialog is open.
        requests, responses = [], []
        def requested(req):
            if req.method == 'GET' and req.url in (self.base + '/api/state', self.base + '/api/me'):
                requests.append(req)
        def responded(response):
            if response.request in requests:
                responses.append(response)
        page.on('request', requested); page.on('response', responded)
        try:
            page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
            self.settle(page, lambda: any(r.url == self.base + '/api/state' for r in responses), timeout=16000)
            state = next(r for r in responses if r.url == self.base + '/api/state')
            assert state.status == 200 and state.finished() is None
            index = requests.index(state.request)
            def tails():
                return [r for r in responses if r.url == self.base + '/api/me' and requests.index(r.request) > index]
            self.settle(page, lambda: bool(tails()))
            tail = tails()[0]; assert tail.status == 200 and tail.finished() is None
            expect(button(page, '刷新家庭数据')).to_be_enabled()
            return state.json(), {'stateStatus': state.status, 'identityStatus': tail.status,
                'stateRequestIndex': index, 'identityRequestIndex': requests.index(tail.request),
                'memberId': tail.json()['user']['id'], 'responseBodiesFinished': True}
        finally:
            page.remove_listener('request', requested); page.remove_listener('response', responded)

    def focus_member(self, page, ctx, uid):
        name = next(p['name'] for p in self.get(ctx, '/api/state')['people'] if p['id'] == uid)
        page.get_by_role('radiogroup', name='日程侧重', exact=True).get_by_role('radio', name=name, exact=True).click()

    def hidden(self, ctx, event):
        state = self.get(ctx, '/api/state')
        assert event['id'] not in {item['id'] for item in state['events']}
        raw = json.dumps(state, ensure_ascii=False)
        assert event['title'] not in raw and event['location'] not in raw
        return state

    def paired_tv(self, browser, owner):
        tv = self.context(browser, None)
        self.lifecycle.callback(tv.close)
        pairing = tv.request.post(self.base + '/api/pair/start', data={}).json()
        self.write(owner, 'POST', '/api/pair/approve', {'code': pairing['code'], 'name': '合成日程电视'})
        assert tv.request.post(self.base + '/api/pair/poll', data={'secret': pairing['secret']}).json()['approved']
        assert self.get(tv, '/api/me')['user']['role'] == 'tv'
        return tv

    def db_event(self, uid):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database)) as con:
            rows = con.execute("SELECT id,data,revision FROM entities WHERE kind='events'").fetchall()
            audits = con.execute('SELECT action,count(*) FROM audit WHERE target=? GROUP BY action', (uid,)).fetchall()
        return {'events': [{'id': row[0], 'data': json.loads(row[1]), 'revision': row[2]} for row in rows], 'audit': dict(audits)}

    def save_scope(self, page, ctx, event, mode):
        self.edit_event(page, event); self.scope(page, mode).click()
        exchange = self.exchange(page, ITEMS + '/' + event['id'], lambda: button(page, '保存').click())
        assert exchange['payload']['revision'] == event['revision']
        assert exchange['payload']['visibility'] == mode and 'createdBy' not in exchange['payload']
        expect(textbox(page)).to_have_count(0)
        result = self.event(ctx, event['id'])
        assert result['revision'] == event['revision'] + 1 and result['visibility'] == mode
        return result

    def private_share_revoke(self, browser):
        with self.flow(browser) as (owner, page):
            partner = self.context(browser, 2); self.lifecycle.callback(partner.close)
            tv = self.paired_tv(browser, owner)
            self.open(page); page.get_by_role('button', name='添加安排', exact=True).first.click()
            title = '合成默认私密安排'; textbox(page).fill(title)
            for label, value in [('开始日期（YYYY-MM-DD）', DAY), ('结束日期（YYYY-MM-DD）', DAY),
                                 ('开始时间（HH:mm）', '09:00'), ('结束时间（HH:mm）', '11:00'), ('地点（可选）', '合成私密地点一')]:
                page.get_by_role('textbox', name=label, exact=True).fill(value)
            expect(self.scope(page, 'private')).to_be_checked()
            # A real converged label, rather than a timer delay or changed CSS.
            label_geometry = '''() => {
              const input=document.querySelector('input[aria-label="地点（可选）"]');
              if(!input)return {separated:false};
              const box=input.getBoundingClientRect(), line=parseFloat(getComputedStyle(input).lineHeight);
              const visible=node=>{for(let n=node;n;n=n.parentElement){const s=getComputedStyle(n);
                if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)===0)return false;}return true;};
              const labels=[...document.querySelectorAll('*')].filter(n=>visible(n)&&[...n.childNodes].some(c=>c.nodeType===3&&c.textContent.trim()==='地点（可选）'))
                .map(n=>{const r=document.createRange();r.selectNodeContents(n);return {box:r.getBoundingClientRect().toJSON(),transform:getComputedStyle(n).transform};});
              const textTop=box.top+box.height/2-line/2;
              return {input:box.toJSON(),textTop,labels,separated:labels.length===1&&labels[0].box.bottom<textTop};
            }'''
            page.wait_for_function('() => (' + label_geometry + ')().separated', polling='raf', timeout=5000)
            self.record('location-label-stable', page.evaluate(label_geometry))
            self.capture(page, 'default-private-390', self.scope(page, 'private'))
            created = self.exchange(page, ITEMS, lambda: button(page, '保存').click(), method='POST', status=201)
            assert created['payload']['owner'] == 'member1' and created['payload']['visibility'] == 'private'
            assert 'createdBy' not in created['payload']
            expect(textbox(page)).to_have_count(0)
            event = self.event(owner, created['backendResult']['id'])
            assert event['createdBy'] == 'member1' and event['revision'] == 1 and event['visibility'] == 'private'
            self.record('private-reads', {'owner': event, 'partner': self.hidden(partner, event), 'tv': self.hidden(tv, event)})
            event = self.save_scope(page, owner, event, 'shared')
            assert self.event(partner, event['id']) == event and self.event(tv, event['id']) == event
            partner_page = partner.new_page(); partner_page.set_viewport_size({'width': 1280, 'height': 900})
            self.open(partner_page); self.focus_member(partner_page, partner, 'member1'); self.edit_event(partner_page, event)
            expect(partner_page.get_by_role('radiogroup', name='日程可见范围', exact=True)).to_have_count(0)
            expect(partner_page.get_by_text('家庭成员和电视可见；只有创建者可以收回共享。', exact=True)).to_be_visible()
            rejected = self.write(partner, 'PATCH', ITEMS + '/' + event['id'], {'revision': event['revision'], 'visibility': 'private'}, 403)
            assert rejected['code'] == 'calendar_privacy_forbidden'
            self.record('collaborator-no-scope', {'response': rejected, 'stillShared': self.event(owner, event['id'])})
            self.capture(partner_page, 'collaborator-shared-1280', textbox(partner_page))
            event = self.save_scope(page, owner, event, 'private')
            self.record('revoked-reads', {'owner': event, 'partner': self.hidden(partner, event), 'tv': self.hidden(tv, event)})
            self.capture(page, 'creator-revoked-390', page.get_by_test_id('calendar-event-' + event['id']))
            actual = self.db_event(event['id'])
            self.record('stable-original-id', actual, 'databaseEvidence')
            assert len(actual['events']) == 1 and actual['events'][0]['id'] == event['id'] and actual['events'][0]['revision'] == 3
            assert actual['audit'] == {'create_events': 1, 'update_events': 2}
            self.proof('sharing-final')
            self.passed('Default private, real partner/paired-TV read denial, explicit shared and creator revocation keep one original event')

    def private_read_surfaces(self, partner, event):
        path = ITEMS + '/' + event['id']
        rejected = self.write(partner, 'PATCH', path, {'revision': event['revision'], 'title': '不可越权'}, 404)
        assert rejected['code'] == 'calendar_event_unavailable'
        search = self.get(partner, '/api/assistant/search?q=' + event['id'])
        # Search by the actual title separately; ID search alone is not evidence.
        from urllib.parse import quote
        title_search = self.get(partner, '/api/assistant/search?q=' + quote(event['title']))
        brief = self.get(partner, '/api/assistant/brief')
        summary = self.get(partner, '/api/portability/summary')
        csrf = self.get(partner, '/api/me')['csrf']
        response = partner.request.post(self.base + '/api/portability/export', data={'includeShared': True},
            headers={'X-CSRF-Token': csrf, 'Origin': self.base})
        assert response.status == 200 and 'application/zip' in response.headers['content-type']
        archive = self.out / 'partner-export.zip'; archive.write_bytes(response.body())
        with ZipFile(BytesIO(response.body())) as z:
            exported = json.loads(z.read('data.json'))
        for result in [title_search, search, brief, summary, exported]:
            raw = json.dumps(result, ensure_ascii=False)
            # A search echoes its query; only matches may be checked for titles.
            if result is title_search or result is search:
                raw = json.dumps(result['matches'], ensure_ascii=False)
            assert event['id'] not in raw and event['title'] not in raw and event['location'] not in raw
        self.record('private-read-surfaces', {'patch404': rejected, 'search': title_search, 'brief': brief,
            'summary': summary, 'export': exported, 'exportSha256': sha(archive), 'exportPath': archive.name})

    def withdrawal_identity(self, browser):
        with self.flow(browser) as (owner, page):
            original = self.seed_event(owner, '合成撤共享敏感安排', visibility='shared')
            partner = self.context(browser, 2); self.lifecycle.callback(partner.close)
            pp = partner.new_page(); pp.set_viewport_size({'width': 1280, 'height': 900})
            self.open(pp); self.focus_member(pp, partner, 'member1'); self.edit_event(pp, original)
            textbox(pp).fill('合成伴侣旧草稿应隐藏')
            self.write(owner, 'PATCH', ITEMS + '/' + original['id'], {'revision': 1, 'visibility': 'private'})
            private = self.event(owner, original['id']); state, order = self.refresh_calendar(pp)
            expect(textbox(pp)).to_have_count(0); expect(pp.get_by_text('请重新读取日程', exact=True)).to_be_visible()
            assert original['id'] not in {item['id'] for item in state['events']}
            self.capture(pp, 'revoked-editor-1280', pp.get_by_text('请重新读取日程', exact=True))
            self.record('withdrawal-refresh-order', order); self.private_read_surfaces(partner, private)
            self.open(page); self.edit_event(page, private); textbox(page).fill('合成跨身份旧草稿')
            before = (self.count_requests('POST', ITEMS), self.count_requests('PATCH', ITEMS + '/' + original['id']))
            held = []
            def hold(route):
                response = route.fetch(max_redirects=0)
                assert response.status == 200 and 'set-cookie' not in response.headers
                held.append((route, response.status, response.headers, response.body()))
            url = self.base + '/api/state'; page.route(url, hold, times=1)
            try:
                page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
                self.settle(page, lambda: len(held) == 1)
                self.login(owner, 2)
                route, status, headers, raw = held.pop()
                assert original['id'] in {row['id'] for row in json.loads(raw)['events']}
                with page.expect_response(lambda r: r.url == self.base + '/api/me' and r.request.method == 'GET') as tail:
                    route.fulfill(status=status, headers=headers, body=raw)
                identity = tail.value; assert identity.status == 200 and identity.finished() is None
                assert identity.json()['user']['id'] == 'member2'
                expect(textbox(page)).to_have_count(0)
                expect(page.get_by_text(original['title'], exact=True)).to_have_count(0)
                expect(page.get_by_text('合成跨身份旧草稿', exact=True)).to_have_count(0)
                self.record('late-state-new-identity', {'oldState': json.loads(raw), 'identityAfter': identity.json()['user'],
                    'tailFinished': True, 'originalId': original['id']})
            finally:
                page.unroute(url, hold)
                for route, *_ in held:
                    route.abort('failed')
            self.refresh_calendar(page)
            self.capture(page, 'switched-member-390', page.get_by_role('heading', name='日程', exact=True))
            assert (self.count_requests('POST', ITEMS), self.count_requests('PATCH', ITEMS + '/' + original['id'])) == before
            actual = self.db_event(original['id']); assert len(actual['events']) == 1 and actual['events'][0]['revision'] == 2
            assert actual['events'][0]['data']['visibility'] == 'private'
            self.record('withdrawal-id-and-version', actual, 'databaseEvidence'); self.proof('withdrawal-final')
            self.passed('Revoked shared editor and delayed old state disappear; real partner CRUD/search/brief/export exclude the private original')

    def identity_failure_draft(self, browser):
        with self.flow(browser) as (owner, page):
            event = self.seed_event(owner, '合成身份恢复安排'); self.open(page); self.edit_event(page, event)
            draft = '合成身份恢复后保留草稿'; textbox(page).fill(draft); self.scope(page, 'shared').click()
            before, attempts = self.snapshot(), []
            path = ITEMS + '/' + event['id']; count = self.count_requests('PATCH', path)
            def identity_failure(route):
                real = route.fetch(max_redirects=0)
                assert real.status == 200 and real.json()['user']['id'] == 'member1'
                attempts.append({'realStatus': real.status, 'memberId': real.json()['user']['id'], 'deliveredStatus': 404})
                route.fulfill(status=404, content_type='application/json', body=json.dumps({'error': '合成身份通道暂不可用'}))
            url = self.base + '/api/me'; page.route(url, identity_failure)
            try:
                button(page, '保存').click()
                expect(page.get_by_text('请先核对日程身份', exact=True)).to_be_visible()
                expect(textbox(page)).to_have_count(0)
                assert attempts and self.count_requests('PATCH', path) == count and self.snapshot() == before
            finally:
                page.unroute(url, identity_failure)
            button(page, '核对身份并继续').click()
            expect(textbox(page)).to_have_value(draft); expect(self.scope(page, 'shared')).to_be_checked()
            expect(button(page, '保存')).to_be_enabled()
            self.capture(page, 'identity404-recovered-390', textbox(page))
            self.record('identity404-no-write', {'attempts': attempts, 'original': event, 'noPatch': True})
            owner.set_offline(True)
            try:
                # Chromium's network setting does not guarantee a DOM offline
                # event; dispatch the actual provider lifecycle event explicitly.
                page.evaluate("window.dispatchEvent(new Event('offline'))")
                expect(page.get_by_text('请先核对日程身份', exact=True)).to_be_visible()
                expect(textbox(page)).to_have_count(0)
                assert self.snapshot() == before
            finally:
                owner.set_offline(False)
            button(page, '核对身份并继续').click()
            expect(textbox(page)).to_have_value(draft); expect(self.scope(page, 'shared')).to_be_checked()
            self.capture(page, 'offline-recovered-390', textbox(page))
            assert self.count_requests('PATCH', path) == count and self.snapshot() == before
            failed = self.exchange(page, path, lambda: button(page, '保存').click(), status=404,
                before_fetch=lambda: self.write(owner, 'DELETE', path, {'revision': event['revision']}))
            assert failed['backendResult']['code'] == 'calendar_event_unavailable'
            assert failed['payload']['revision'] == event['revision'] and failed['payload']['title'] == draft
            expect(page.get_by_text('请重新读取日程', exact=True)).to_be_visible(); expect(textbox(page)).to_have_count(0)
            self.refresh_calendar(page)
            expect(textbox(page)).to_have_count(0)
            self.capture(page, 'true-record404-hidden-390', page.get_by_text('请重新读取日程', exact=True))
            assert self.count_requests('PATCH', path) == count + 1
            actual = self.db_event(event['id']); assert not actual['events'] and actual['audit'] == {'create_events': 1, 'delete_events': 1}
            self.record('no-repeat-no-copy', actual, 'databaseEvidence'); self.proof('recovery-final')
            self.passed('Real provider preflight404 and offline conceal/recover same-session draft without writing; actual item404 permanently hides it without retry')

    @classmethod
    def run_scenarios(cls, root, bundle, report, out, browser, temp_root, cases=CASES):
        for name in cases:
            case_out = out / name; case_out.mkdir()
            folder, before, case = None, len(report['checks']), {'name': name, 'passed': False}
            screenshots_before = len(report['screenshots'])
            try:
                with ExitStack() as lifecycle:
                    folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='cp-', dir=temp_root)))
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
    out = exclusive_output(root)
    shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], unexpectedProviderAttempts=[],
                  screenshots=[], scenarioResults=[], scenarioFailures=[], httpEvidence=[], databaseEvidence=[],
                  requestedChecks=len(cases), requestedCases=list(cases), expectedScreenshots=expected_screenshots, head=head, tree=tree, buildEvidenceSha256=sha(evidence_path),
                  harnessSha256=sha(out / 'executed-harness.py'), buildSourceHead=build_head, buildSourceTree=evidence['sourceTree'],
                  buildSourceDelta=build_delta, buildReusePolicy='only-calendar-privacy-harness-tests-docs; identical-complete-frontend-and-input-hashes',
                  sourceRoot=str(root), bundleRoot=str(bundle), sourceHashesBefore=hashes(), bundleHashesBefore=export_hashes(bundle),
                  productionWrites=0, realModel=False, realCloud=False, physicalTelevision=False,
                  scope='Only requestedCases ran as real local Flask/SQLite/HTTPS/Edge calendar-privacy flows. Actual member sessions, paired-TV HTTP reads, event CRUD, assistant search/brief and ZIP export. Identity transport404 and offline lifecycle injection only; no fake successful business DTO. No cloud/model/production or physical-TV display acceptance.')
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
