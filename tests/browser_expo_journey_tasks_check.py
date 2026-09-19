"""Frozen Expo travel task publication through real Flask/SQLite/HTTPS/Edge.

Only provider HTTP is synthetic (the existing test_task_publish.Remote).
Browser faults delay/drop genuine responses or explicitly leave a request unsent.
No model, production, real provider or physical-device operations are authorized.
Run only after independent review and a new, bound frontend export.
"""
import argparse
from contextlib import ExitStack, closing
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import ThreadedWSGIServer
import browser_expo_finance_check as fixture
import browser_expo_journey_brief_check as journey_fixture
import browser_expo_assistant_trip_items_check as item_fixture
from browser_expo_finance_check import Run as BaseRun, button, sha
from browser_expo_assistant_trip_items_check import export_hashes
from browser_expo_journey_brief_check import icon_button

HARNESS = 'tests/browser_expo_journey_tasks_check.py'
TP = '/api/task-publish'
WIDTHS = (390, 1280)
CASES = ('publish_completion_restart', 'unknown_confirm_recovery',
         'conflict_reconnect', 'late_preview_identity')
PROVIDERS = ('microsoft', 'google')
TABLES = ('entities', 'journey_workflows', 'journey_links', 'journey_actions',
          'task_publications', 'calendar_publications', 'audit')


class Run(BaseRun):
    record = item_fixture.Run.record
    exchange = item_fixture.Run.exchange
    show_saved = journey_fixture.Run.show_saved

    def __init__(self, *args, provider, **kwargs):
        self.provider, self.remote, self.exchange_number = provider, None, 0
        lifecycle = args[5]
        assert ThreadedWSGIServer.block_on_close is True
        lifecycle.enter_context(patch.object(ThreadedWSGIServer, 'daemon_threads', False))
        super().__init__(*args, **kwargs)
        assert not self.server.daemon_threads
        assert Path(self.source.__file__).resolve() == (self.root / 'app.py').resolve()
        paths = {HARNESS: Path(__file__), 'tests/browser_expo_finance_check.py': Path(fixture.__file__),
                 'tests/browser_expo_journey_brief_check.py': Path(journey_fixture.__file__),
                 'tests/browser_expo_assistant_trip_items_check.py': Path(item_fixture.__file__),
                 'tests/test_task_publish.py': Path(importlib.import_module('test_task_publish').__file__)}
        for name in ('app', 'task_publish', 'calendar_publish', 'cloud_accounts', 'cloud_providers', 'journey_workflows'):
            paths[name + '.py'] = Path(sys.modules[name].__file__)
        hashes = {name: sha(path) for name, path in paths.items()}
        assert all(value == sha(self.root / name) for name, value in hashes.items())
        assert hashes[HARNESS] == self.report['harnessSha256']
        assert self.report.setdefault('fixtureHashes', hashes) == hashes
        actual = {name: str(path.resolve()) for name, path in paths.items()}
        assert self.report.setdefault('fixtureActualPaths', actual) == actual
        assistant = importlib.import_module('home_assistant')
        lifecycle.enter_context(patch.object(assistant, '_model_json', self.forbidden_model))
        lifecycle.enter_context(patch.object(assistant, 'model_plan', self.forbidden_model))
        self.seed_accounts()

    def start(self, port=0):
        if self.remote is None:
            self.remote = importlib.import_module('test_task_publish').Remote()
        self.cfg.update(CLOUD_TRANSPORT=self.remote.transport,
                        GOOGLE_CLIENT_ID='synthetic-google-client', GOOGLE_CLIENT_SECRET='synthetic-google-secret',
                        MICROSOFT_CLIENT_ID='synthetic-ms-client', MICROSOFT_CLIENT_SECRET='synthetic-ms-secret')
        super().start(port)

    def forbidden_model(self, *_args, **_kwargs):
        self.report['unexpectedProviderAttempts'].append(self.out.name)
        raise AssertionError('No model is allowed in the task-publication suite')

    def clear_finance(self):
        pass  # Each case has its own temporary database; never clear shared state.

    def seed_accounts(self):
        engine = self.application.extensions['cloud_accounts']
        scope = ('User.Read Calendars.Read Tasks.ReadWrite' if self.provider == 'microsoft' else
                 'https://www.googleapis.com/auth/tasks https://www.googleapis.com/auth/calendar.readonly')
        with engine.db() as con:
            for suffix, owner in [('mine', 'member1'), ('partner', 'member2')]:
                token = engine.encrypt({'access_token': 'synthetic', 'scope': scope, 'expires_at': time.time() + 3600})
                con.execute('INSERT INTO cloud_accounts(id,owner,provider,client_id,subject,name,email,tokens) VALUES(?,?,?,?,?,?,?,?)',
                            ('account-' + suffix, owner, self.provider, self.cfg[self.provider.upper() + '_CLIENT_ID'],
                             'synthetic-' + suffix, 'PRIVATE_TASK_ACCOUNT_' + suffix, suffix + '@synthetic.invalid', token))
                con.execute('INSERT INTO cloud_sources(id,account_id,remote_id,kind,name,owner) VALUES(?,?,?,?,?,?)',
                            ('source-' + suffix, 'account-' + suffix, 'list-1' if suffix == 'mine' else 'list-2',
                             'tasks', '合成主清单' if suffix == 'mine' else 'PRIVATE_PARTNER_LIST', 'shared'))
            con.execute("UPDATE cloud_sources SET is_primary=1 WHERE id='source-mine'")

    def snapshot(self):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database)) as con:
            assert not con.execute('PRAGMA foreign_key_check').fetchall()
            return {table: sorted(con.execute('SELECT * FROM "' + table + '"').fetchall(), key=repr) for table in TABLES}

    def proof(self, name):
        return self.record(name, self.snapshot(), 'databaseEvidence')

    def state(self, ctx, journey):
        return self.get(ctx, TP + '/state?journeyId=' + journey)

    def local(self, entity_id):
        with closing(sqlite3.connect(self.database)) as con:
            row = con.execute('SELECT revision,data FROM entities WHERE id=?', (entity_id,)).fetchone()
            assert row
            return {'id': entity_id, 'revision': row[0], **json.loads(row[1])}

    def publication(self, rid):
        with closing(sqlite3.connect(self.database)) as con:
            con.row_factory = sqlite3.Row
            row = con.execute('SELECT * FROM task_publications WHERE id=?', (rid,)).fetchone()
            assert row
            return dict(row)

    def process(self, rid):
        self.application.extensions['task_publish'].process(rid)

    def remote_change(self, **changes):
        assert len(self.remote.records) == 1
        raw = next(iter(self.remote.records.values()))
        raw.update(changes)
        raw['@odata.etag' if self.provider == 'microsoft' else 'etag'] = '"synthetic-' + str(len(self.remote.calls)) + '"'

    def seed_journey(self, ctx):
        plan = {'title': '合成旅行待办验收', 'start': '2027-10-01', 'end': '2027-10-05', 'budget': 1000000,
                'international': True, 'memberIds': ['member1', 'member2'],
                'destinations': [{'key': 'kyoto', 'country': '日本', 'city': '京都'}],
                'checklist': [{'key': 'passport', 'title': '合成核对护照', 'owner': 'member2', 'dueOffsetDays': -7, 'note': '合成准备备注'},
                              {'key': 'packing', 'title': '合成整理行李', 'owner': 'shared', 'dueOffsetDays': -2, 'note': '合成行李备注'}],
                'shopping': [], 'segments': []}
        preview = self.write(ctx, 'POST', '/api/journeys/preview', {'plan': plan})
        saved = self.write(ctx, 'POST', '/api/journeys/apply',
                           {'previewToken': preview['previewToken'], 'idempotencyKey': 'synthetic-' + self.out.name}, status=201)
        detail = self.get(ctx, '/api/journeys/' + saved['id'])
        assert len(detail['tasks']) == 2
        self.record('saved-journey', detail)
        return saved, {row['title']: row['id'] for row in detail['tasks']}

    def open_tasks(self, page, trip_id):
        self.show_saved(page, trip_id)
        icon_button(page, '同步到主清单').click()
        expect(page.get_by_role('heading', name='旅行待办同步', exact=True)).to_be_visible()
        expect(button(page, '刷新状态')).to_be_enabled()

    def choose(self, page, title='合成核对护照', source=None):
        source = source or {'name': '合成主清单', 'accountName': 'PRIVATE_TASK_ACCOUNT_mine'}
        brand = 'Microsoft To Do' if self.provider == 'microsoft' else 'Google Tasks'
        control = page.get_by_role('radio', name='选择清单：' + brand + ' · ' + source['name'] + ' · ' + source['accountName'], exact=True)
        if control.get_attribute('aria-checked') != 'true':
            control.click()
        expect(control).to_have_attribute('aria-checked', 'true')
        task = page.get_by_role('checkbox', name='选择待办：' + title, exact=True)
        expect(task).to_be_enabled()
        assert task.get_attribute('aria-checked') == 'false', 'No task may be preselected'
        task.click()
        expect(task).to_have_attribute('aria-checked', 'true')
        expect(page.locator('body')).not_to_contain_text('PRIVATE_PARTNER_LIST')
        expect(page.locator('body')).not_to_contain_text('PRIVATE_TASK_ACCOUNT_partner')

    def preview(self, page):
        before, calls = self.snapshot(), len(self.remote.calls)
        value = self.exchange(page, TP + '/preview', lambda: button(page, '预览选中待办').click())
        assert self.snapshot() == before and len(self.remote.calls) == calls
        expect(button(page, '确认连接这 1 项待办')).to_be_enabled()
        assert len(value['result']['tasks']) == 1
        return value['result']

    def confirm(self, page, label='确认连接这 1 项待办', drop=None):
        value = self.exchange(page, TP + '/confirm', lambda: button(page, label).click(), drop=drop)
        return value

    def refresh_status(self, page):
        expect(button(page, '刷新状态')).to_be_enabled()
        with page.expect_response(lambda response: response.request.method == 'GET'
                                  and response.url.startswith(self.base + TP + '/state?')) as received:
            button(page, '刷新状态').click()
        assert received.value.status == 200
        expect(button(page, '刷新状态')).to_be_enabled()

    def screenshots(self, page, label):
        if self.provider != 'microsoft':
            return
        for width in WIDTHS:
            self.screenshot(page, label, width)
            body = page.evaluate('''() => ({viewport:innerWidth,bodyScroll:document.body.scrollWidth,
                bodyClient:document.body.clientWidth,rootScroll:document.documentElement.scrollWidth})''')
            assert body['bodyScroll'] <= width + 2 and body['rootScroll'] <= width + 2, body
            shot = self.report['screenshots'][-1]
            shot.update(path=self.out.name + '/' + shot['path'], bodyMetrics=body)
        page.set_viewport_size({'width': 390, 'height': 844})

    def no_duplicate(self, task_ids):
        with closing(sqlite3.connect(self.database)) as con:
            ids = {row[0] for row in con.execute("SELECT id FROM entities WHERE kind='tasks'")}
            assert ids == set(task_ids)
            assert con.execute("SELECT count(*) FROM entities WHERE id LIKE 'cloud-%'").fetchone()[0] == 0

    def publish_completion_restart(self, browser):
        with self.flow(browser) as (ctx, page):
            saved, tasks = self.seed_journey(ctx)
            self.open_tasks(page, saved['tripId'])
            self.choose(page)
            original = self.local(tasks['合成核对护照'])
            p = self.preview(page)
            assert p['tasks'][0]['id'] == original['id'] and p['tasks'][0]['owner'] == 'member2'
            self.screenshots(page, 'preview')
            receipt = self.confirm(page)['result']
            rid = receipt['publicationIds'][0]
            queued = self.publication(rid)
            assert queued['entity_id'] == original['id'] and queued['status'] == 'pending' and not self.remote.calls
            expect(page.get_by_text('等待同步', exact=True)).to_be_visible()
            self.process(rid)
            assert self.remote.created == 1
            self.refresh_status(page)
            expect(page.get_by_text('云端已确认', exact=True)).to_be_visible()
            self.remote_change(status='completed')
            self.process(rid)
            now = self.local(original['id'])
            assert now['done'] and all(now[key] == original[key] for key in ('id', 'owner', 'tripId', 'journeyId', 'note', 'due'))
            self.refresh_status(page)
            self.screenshots(page, 'confirmed')
            icon_button(page, '返回旅行').click()
            expect(page.get_by_text('准备 · 1/2', exact=True)).to_be_visible()
            self.no_duplicate(tasks.values())
            before = self.proof('before-app-recreation')
            self.restart()  # Same process, new actual Flask app/listener, same SQLite.
            assert self.proof('after-app-recreation') == before
            assert self.get(ctx, '/api/journeys/' + saved['id'])['progress']['done'] == 1
            self.record('provider-calls', self.remote.calls, 'providerEvidence')
            self.passed(self.out.name + ': original task publication, cloud completion, trip progress and app recreation persist without duplicate')

    def disable_periodic_refresh(self, ctx):
        # Deterministic fault inspection only: manual reads remain genuine HTTP.
        # Do not let the ten-second automatic status read race the unknown card.
        ctx.add_init_script('''(() => {const original=window.setInterval.bind(window);
          window.setInterval=(fn,ms,...args)=>original(fn,ms===10000?3600000:ms,...args);})()''')

    def unknown_confirm_recovery(self, browser):
        with self.flow(browser) as (ctx, page):
            self.disable_periodic_refresh(ctx)
            saved, tasks = self.seed_journey(ctx)
            self.open_tasks(page, saved['tripId'])
            self.choose(page)
            p1 = self.preview(page)
            lost = self.confirm(page, drop='response')
            assert lost['result']['queued'] is True
            expect(button(page, '核对当前状态')).to_be_enabled()
            expect(icon_button(page, '取消本页选择并返回旅行')).to_be_disabled()
            writes = self.count_requests('POST', TP + '/confirm')
            committed = self.proof('committed-before-readback')
            button(page, '核对当前状态').click()
            expect(page.get_by_text('已找到刚才所选待办与原清单的连接。请在下方查看云端实际进度。', exact=True)).to_be_visible()
            assert self.count_requests('POST', TP + '/confirm') == writes
            assert self.proof('recovered-by-read-only') == committed
            assert lost['payload']['previewToken'] == p1['previewToken'] and not self.remote.calls
            self.choose(page, '合成整理行李')
            p2 = self.preview(page)
            unsent = self.confirm(page, drop='request')
            assert unsent['sentToServer'] is False
            expect(button(page, '核对当前状态')).to_be_enabled()
            assert len(self.state(ctx, saved['id'])['publications']) == 1
            button(page, '核对当前状态').click()
            expect(button(page, '使用原确认再次核对')).to_be_enabled()
            retried = self.confirm(page, label='使用原确认再次核对')
            assert retried['payload'] == unsent['payload'] == {'previewToken': p2['previewToken']}
            rows = self.state(ctx, saved['id'])['publications']
            assert len(rows) == 2 and {row['entityId'] for row in rows} == set(tasks.values())
            # A provider create committed but its reply was lost. Retry must
            # search for the same publication marker, never issue another POST.
            rid = rows[0]['id']
            self.remote.lose_create = True
            self.process(rid)
            assert self.publication(rid)['status'] == 'uncertain' and self.remote.created == 1
            self.remote.hide = True
            self.refresh_status(page)
            self.exchange(page, TP + '/publications/' + rid + '/retry', lambda: button(page, '再次核对原清单').click())
            self.process(rid)
            assert self.remote.created == 1
            self.remote.hide = False
            self.process(rid)
            assert self.publication(rid)['status'] == 'published' and self.remote.created == 1
            for row in rows:
                if row['id'] != rid:
                    self.process(row['id'])
            assert self.remote.created == 2
            self.no_duplicate(tasks.values())
            self.record('provider-calls', self.remote.calls, 'providerEvidence')
            self.passed(self.out.name + ': committed response loss recovers read-only; unsent request reuses original credential; unknown provider create searches the original target without reposting')

    def conflict_reconnect(self, browser):
        with self.flow(browser) as (ctx, page):
            saved, tasks = self.seed_journey(ctx)
            self.open_tasks(page, saved['tripId'])
            self.choose(page)
            self.preview(page)
            rid = self.confirm(page)['result']['publicationIds'][0]
            self.process(rid)
            original_remote_id = self.publication(rid)['remote_id']
            assert original_remote_id
            original = self.local(tasks['合成核对护照'])
            self.remote_change(title='合成云端变更')
            self.process(rid)
            self.refresh_status(page)
            self.exchange(page, TP + '/publications/' + rid + '/conflict-preview', lambda: button(page, '对比并处理').click())
            expect(button(page, '采用云端内容')).to_be_enabled()
            self.screenshots(page, 'conflict')
            self.exchange(page, TP + '/publications/' + rid + '/conflict-confirm', lambda: button(page, '采用云端内容').click())
            current = self.local(original['id'])
            assert current['title'] == '合成云端变更'
            assert all(current[key] == original[key] for key in ('id', 'owner', 'journeyId', 'tripId'))
            self.write(ctx, 'PATCH', '/api/items/tasks/' + original['id'], {'revision': current['revision'], 'title': '合成本地再次修改'})
            self.refresh_status(page)
            expect(page.get_by_text('本地有新修改，等待云端确认', exact=True)).to_be_visible()
            self.remote_change(title='合成远端同时修改')
            self.process(rid)
            self.refresh_status(page)
            self.exchange(page, TP + '/publications/' + rid + '/conflict-preview', lambda: button(page, '对比并处理').click())
            comparison = page.get_by_text('看板本地', exact=True).locator('..')
            expect(comparison.get_by_text('合成本地再次修改', exact=True)).to_be_visible()
            expect(comparison.get_by_text('合成远端同时修改', exact=True)).to_be_visible()
            self.exchange(page, TP + '/publications/' + rid + '/conflict-confirm', lambda: button(page, '确认以本地更新云端').click())
            self.process(rid)
            assert next(iter(self.remote.records.values()))['title'] == '合成本地再次修改'
            self.refresh_status(page)
            self.exchange(page, TP + '/publications/' + rid + '/pause', lambda: button(page, '暂停同步').click())
            expect(button(page, '恢复同步')).to_be_enabled()
            self.exchange(page, TP + '/publications/' + rid + '/resume', lambda: button(page, '恢复同步').click())
            self.process(rid)
            accounts = self.application.extensions['cloud_accounts']
            accounts.select_sources('account-mine', 'member1', [])
            accounts.select_sources('account-mine', 'member1', [{'kind': 'tasks', 'remoteId': 'list-1'}])
            self.refresh_status(page)
            expect(page.get_by_text('原清单已断开', exact=True)).to_be_visible()
            sources = self.state(ctx, saved['id'])['sources']
            assert len(sources) == 1 and sources[0]['id'] != 'source-mine'
            self.choose(page, '合成本地再次修改', sources[0])
            p = self.preview(page)
            assert p['tasks'][0]['reconnect'] is True
            expect(page.get_by_text(re.compile('重新连接原清单，保留云端原任务'))).to_be_visible()
            result = self.confirm(page)['result']
            assert result['publicationIds'] == [rid]
            self.process(rid)
            connected = self.publication(rid)
            assert self.remote.created == 1 and connected['source_id'] == sources[0]['id']
            assert connected['remote_id'] == original_remote_id
            self.no_duplicate(tasks.values())
            self.proof('conflict-and-reconnection-preserve-originals')
            self.record('provider-calls', self.remote.calls, 'providerEvidence')
            self.passed(self.out.name + ': both conflict resolutions, simultaneous changes, pause/resume and same-target reconnect preserve original task and remote id')

    def late_preview_identity(self, browser):
        with self.flow(browser) as (ctx, page):
            self.disable_periodic_refresh(ctx)
            saved, _tasks = self.seed_journey(ctx)
            # The source is private in this case; revocation of shared primary is
            # a controlled fixture change before the page starts, not a fake DTO.
            with self.application.extensions['cloud_accounts'].db() as con:
                con.execute("UPDATE cloud_sources SET is_primary=0 WHERE id='source-mine'")
            self.open_tasks(page, saved['tripId'])
            self.choose(page)
            before = self.proof('before-held-preview')
            held, url, delivered = [], self.base + TP + '/preview', False
            def hold(route):
                response = route.fetch(max_redirects=0)
                assert response.status == 200 and 'set-cookie' not in response.headers
                held.append((route, response))
            page.route(url, hold, times=1)
            try:
                button(page, '预览选中待办').click()
                self.settle(page, lambda: bool(held))
                self.record('held-authentic-preview', held[0][1].json())
                self.login(ctx, 2)
                held[0][0].fulfill(response=held[0][1])
                delivered = True
                expect(page.locator('body')).not_to_contain_text('PRIVATE_TASK_ACCOUNT_mine', timeout=15000)
                expect(button(page, '确认连接这 1 项待办')).to_have_count(0)
                assert self.get(ctx, '/api/me')['user']['id'] == 'member2'
                assert self.state(ctx, saved['id'])['sources'][0]['accountOwner'] == 'member2'
                assert self.proof('after-member-switch-no-publication') == before
                assert self.count_requests('POST', TP + '/confirm') == 0 and not self.remote.calls
                assert not page.evaluate('''() => [...Object.values(localStorage),...Object.values(sessionStorage),location.href]
                    .some(value=>value.includes('PRIVATE_TASK_ACCOUNT_mine')||value.includes('previewToken'))''')
            finally:
                if held and not delivered:
                    held[0][0].abort('failed')
                page.unroute(url, hold)
            self.passed(self.out.name + ': actual member-cookie switch rejects authentic late private preview without publishing, persistent storage or provider calls')

    @classmethod
    def run_scenarios(cls, root, bundle, report, out, browser):
        for provider in PROVIDERS:
            for name in CASES:
                case_out = out / (provider + '-' + name)
                case_out.mkdir()
                folder, run = None, None
                before = len(report['checks'])
                case = {'provider': provider, 'name': name, 'passed': False}
                try:
                    with ExitStack() as lifecycle:
                        folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='expo-journey-tasks-')))
                        run = cls(root, bundle, folder, report, case_out, lifecycle, provider=provider)
                        getattr(run, name)(browser)
                    assert len(report['checks']) == before + 1 and not folder.exists()
                    assert run.server is None and not run.thread.is_alive()
                    case.update(passed=True, listenerStopped=True, syntheticProviderCreates=run.remote.created)
                except Exception:
                    del report['checks'][before:]
                    failure = traceback.format_exc()
                    (case_out / 'failure.txt').write_text(failure, encoding='utf-8')
                    report['scenarioFailures'].append({'scenario': case_out.name, 'traceback': failure})
                    print('FAIL ' + case_out.name + '\n' + failure, flush=True)
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
    args = parser.parse_args()
    root, bundle = args.source_root.resolve(), args.bundle.absolute()
    assert sys.dont_write_bytecode and not sys.flags.optimize
    assert re.fullmatch('[a-f0-9]{40}', args.expected_head) and re.fullmatch('[a-f0-9]{64}', args.expected_build_evidence)
    def git(*command):
        return subprocess.check_output(['git', '--no-replace-objects', *command], cwd=root, text=True).strip()
    head, tree = git('rev-parse', 'HEAD'), git('rev-parse', 'HEAD^{tree}')
    assert head == args.expected_head and not git('status', '--porcelain=v1')
    evidence_path = bundle.parent / 'build-evidence.json'
    assert sha(evidence_path) == args.expected_build_evidence
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    build_head = args.build_source_head or head
    assert re.fullmatch('[a-f0-9]{40}', build_head)
    assert evidence['sourceHead'] == build_head and evidence['sourceTree'] == git('rev-parse', build_head + '^{tree}')
    if build_head != head:
        git('merge-base', '--is-ancestor', build_head, head)
        assert git('rev-parse', build_head + ':frontend') == git('rev-parse', head + ':frontend')
    names = subprocess.check_output(['git', '--no-replace-objects', 'ls-files', '-z'], cwd=root).decode('utf-8').rstrip('\0').split('\0')
    def hashes():
        return {name: sha(root / name) for name in names}
    assert export_hashes(bundle) == evidence['files']
    assert all(sha(root / name) == value for name, value in evidence['inputFiles'].items())
    assert sha(Path(__file__)) == sha(root / HARNESS)
    out = root / 'test-results' / ('expo-journey-tasks-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], unexpectedProviderAttempts=[],
                  screenshots=[], scenarioResults=[], scenarioFailures=[], httpEvidence=[], databaseEvidence=[], providerEvidence=[],
                  requestedChecks=len(CASES)*len(PROVIDERS), head=head, tree=tree, buildEvidenceSha256=sha(evidence_path),
                  harnessSha256=sha(out / 'executed-harness.py'), buildSourceHead=build_head, buildSourceTree=evidence['sourceTree'],
                  sourceRoot=str(root), bundleRoot=str(bundle), sourceHashesBefore=hashes(), bundleHashesBefore=export_hashes(bundle),
                  productionWrites=0, realModel=False, realCloud=False, physicalTelevision=False,
                  scope='Eight independent synthetic Flask/SQLite/HTTPS/Edge flows, two real provider adapters with existing synthetic HTTP transport. Timers are slowed only in fault/identity cases. No real account or production validation.')
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
                Run.run_scenarios(root, bundle, report, out, browser)
                assert len(report['checks']) == len(CASES)*len(PROVIDERS) and len(report['screenshots']) == 6
                assert not any(report[key] for key in ('scenarioFailures', 'pageErrors', 'externalRequests', 'unexpectedProviderAttempts'))
                report['passed'] = True
            finally:
                browser.close()
    except Exception:
        report['failure'] = traceback.format_exc()
        print(report['failure'], flush=True)
    finally:
        try:
            report['sourceHashesAfter'], report['bundleHashesAfter'] = hashes(), export_hashes(bundle)
            report['sourceUnchanged'] = report['sourceHashesBefore'] == report['sourceHashesAfter']
            report['bundleUnchanged'] = report['bundleHashesBefore'] == report['bundleHashesAfter']
            report['fixtureHashesAfter'] = {name: sha(Path(path)) for name, path in report.get('fixtureActualPaths', {}).items()}
            report['fixturesUnchanged'] = bool(report.get('fixtureHashes')) and report['fixtureHashesAfter'] == report['fixtureHashes']
            report['sourceStillFrozen'] = git('rev-parse', 'HEAD') == head and git('rev-parse', 'HEAD^{tree}') == tree and not git('status', '--porcelain=v1')
            report['temporaryFixtureRemoved'] = len(report['scenarioResults']) == len(CASES)*len(PROVIDERS) and all(c['temporaryFixtureRemoved'] for c in report['scenarioResults'])
            report['passed'] = report['passed'] and all(report[key] for key in ('sourceUnchanged', 'bundleUnchanged', 'fixturesUnchanged', 'sourceStillFrozen', 'temporaryFixtureRemoved'))
        except Exception:
            report['passed'] = False
            report['finalEvidenceFailure'] = traceback.format_exc()
        with (out / 'result.json').open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'report': str(out / 'result.json')}, ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
