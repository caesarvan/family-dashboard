"""Four frozen Expo shopping schedule flows through real Flask/SQLite/HTTPS/Edge.

The assistant uses its actual local parser. No business DTO or model response is
substituted. Browser offline is a transport failure, never a fabricated success.
Run only after independent review and a bound combined-source frontend export.
"""
import argparse
from contextlib import ExitStack, closing
from datetime import datetime, timezone
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

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import ThreadedWSGIServer
import browser_expo_finance_check as fixture
import browser_expo_journey_brief_check as brief_fixture
import browser_expo_assistant_trip_items_check as item_fixture
from browser_expo_finance_check import Run as BaseRun, button, sha
from browser_expo_journey_brief_check import BRIEF, PREVIEW, APPLY, TABLES, textfield, icon_button
from browser_expo_assistant_trip_items_check import export_hashes

HARNESS = 'tests/browser_expo_shopping_schedule_check.py'
CASES = ('ordinary_schedule', 'local_brief_schedule', 'selected_reschedule', 'offline_draft')
WIDTHS = (390, 1280)
ITEMS = '/api/items/shopping'
PROMPT = ('旅行名称：合成采购日期旅行\n出发日期：2027-10-01\n返程日期：2027-10-07\n'
          '旅行类型：境外\n总预算：20000元\n冰岛/雷克雅未克 2027-10-01 至 2027-10-07\n'
          '采购：转换插头 | 负责人：我 | 数量：2件 | 预算：100元 | 截止：出发前3天 | 优先级：高')


class Run(BaseRun):
    record = item_fixture.Run.record
    open_assistant = brief_fixture.Run.open_assistant
    choose_members = brief_fixture.Run.choose_members
    show_saved = brief_fixture.Run.show_saved

    def __init__(self, root, bundle, folder, report, out, lifecycle):
        self.exchange_number = 0
        assert ThreadedWSGIServer.block_on_close is True
        lifecycle.enter_context(patch.object(ThreadedWSGIServer, 'daemon_threads', False))
        super().__init__(root, bundle, folder, report, out, lifecycle)
        assert not self.server.daemon_threads
        paths = {HARNESS: Path(__file__), 'tests/browser_expo_finance_check.py': Path(fixture.__file__),
                 'tests/browser_expo_journey_brief_check.py': Path(brief_fixture.__file__),
                 'tests/browser_expo_assistant_trip_items_check.py': Path(item_fixture.__file__)}
        for name in ('app', 'home_assistant', 'journey_workflows', 'journey_reschedule'):
            paths[name + '.py'] = Path(sys.modules[name].__file__)
        hashes = {name: sha(path) for name, path in paths.items()}
        assert all(path.resolve() == (root / name).resolve() for name, path in paths.items())
        assert all(digest == sha(root / name) for name, digest in hashes.items())
        assert hashes[HARNESS] == report['harnessSha256']
        assert report.setdefault('fixtureHashes', hashes) == hashes
        assert report.setdefault('fixtureActualPaths', {n: str(p.resolve()) for n, p in paths.items()}) == {n: str(p.resolve()) for n, p in paths.items()}
        assistant = sys.modules['home_assistant']
        for name in ('_model_json', 'model_plan', 'model_journey_brief'):
            lifecycle.enter_context(patch.object(assistant, name, self.forbidden_model))

    def start(self, port=0):
        self.cfg['ASSISTANT_PROVIDER'] = 'local'
        super().start(port)

    def forbidden_model(self, *_args, **_kwargs):
        self.report['unexpectedProviderAttempts'].append(self.out.name)
        raise AssertionError('Only the real local assistant parser is allowed')

    def clear_finance(self):
        pass  # Each scenario owns an independent temporary database.

    def snapshot(self):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database)) as con:
            assert not con.execute('PRAGMA foreign_key_check').fetchall()
            return {name: sorted(con.execute('SELECT * FROM "' + name + '"').fetchall(), key=repr) for name in TABLES}

    def proof(self, name):
        return self.record(name, self.snapshot(), 'databaseEvidence')

    def shopping(self, ctx):
        return self.get(ctx, '/api/state')['shopping']

    def item(self, ctx, uid):
        return next(row for row in self.shopping(ctx) if row['id'] == uid)

    def exchange(self, page, path, action, *, method='POST', status=200):
        """Observe and deliver real response bytes, including PATCH responses."""
        self.exchange_number += 1
        stem, calls, url = 'exchange-%02d' % self.exchange_number, [], self.base + path

        def intercept(route):
            assert route.request.method == method
            response = route.fetch(max_redirects=0)
            raw = response.body()
            saved = self.out / (stem + '.body')
            with saved.open('xb') as stream:
                stream.write(raw)
            value = {'path': path, 'method': method, 'payload': route.request.post_data_json,
                     'status': response.status, 'result': json.loads(raw), 'responseSha256': sha(saved)}
            route.fulfill(status=response.status, headers=response.headers, body=raw)
            calls.append(value)

        page.route(url, intercept, times=1)
        try:
            action()
            self.settle(page, lambda: bool(calls))
            assert len(calls) == 1 and calls[0]['status'] == status, calls
            return calls[0]
        finally:
            page.unroute(url, intercept)
            self.record(stem, calls)

    def capture(self, page, label, focus):
        for width in WIDTHS:
            page.set_viewport_size({'width': width, 'height': 844 if width == 390 else 1000})
            expect(focus).to_be_visible()
            focus.scroll_into_view_if_needed()
            page.evaluate('() => document.fonts.ready')
            page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
            metrics = page.evaluate('''() => ({viewport:innerWidth,bodyScroll:document.body.scrollWidth,
              bodyClient:document.body.clientWidth,rootScroll:document.documentElement.scrollWidth,
              clipped:[...document.querySelectorAll('input,textarea,button,[role="button"],[role="radio"],[role="checkbox"]')]
              .filter(n=>{const r=n.getBoundingClientRect();return r.width>0&&r.height>0&&r.bottom>0&&r.top<innerHeight&&getComputedStyle(n).visibility!=='hidden'&&(r.left< -2||r.right>innerWidth+2)})
              .map(n=>({label:n.getAttribute('aria-label')||n.textContent,box:n.getBoundingClientRect().toJSON()}))})''')
            assert metrics['bodyScroll'] <= width + 2 and metrics['rootScroll'] <= width + 2 and not metrics['clipped'], metrics
            path = self.out / f'{label}-{width}.png'
            page.screenshot(path=str(path), full_page=True)
            self.report['screenshots'].append({'path': path.relative_to(self.out.parent).as_posix(), 'sha256': sha(path), 'metrics': metrics})
        page.set_viewport_size({'width': 390, 'height': 844})

    def open_shopping(self, page):
        page.goto(self.base + '/app/shopping')
        expect(page.get_by_role('heading', name='采购清单', exact=True)).to_be_visible(timeout=15000)

    def fill_purchase(self, page, title, due, priority='高'):
        textfield(page, '物品名称').fill(title)
        textfield(page, '采购截止日期（可选）').fill(due)
        page.get_by_label('采购优先级：' + priority, exact=True).click()

    def saved_item(self, page, uid):
        expect(textfield(page, '物品名称')).not_to_be_visible()
        expect(page.get_by_test_id('shopping-item-' + uid)).to_be_visible()

    def ordinary_schedule(self, browser):
        with self.flow(browser) as (ctx, page):
            self.open_shopping(page)
            button(page, '添加采购').click()
            self.fill_purchase(page, '合成普通采购', '2027-09-28')
            textfield(page, '预计总价（元，可选）').fill('123.45')
            self.capture(page, 'create-form', textfield(page, '采购截止日期（可选）'))
            created = self.exchange(page, ITEMS, lambda: button(page, '保存').click(), status=201)
            uid = created['result']['id']
            self.saved_item(page, uid)
            original = self.item(ctx, uid)
            assert (original['due'], original['priority'], original['budget']) == ('2027-09-28', 'high', 12345)
            self.open_shopping(page)
            expect(page.get_by_test_id('shopping-item-' + uid)).to_contain_text('2027-09-28')
            icon_button(page, '编辑合成普通采购').click()
            expect(textfield(page, '采购截止日期（可选）')).to_have_value('2027-09-28')
            self.fill_purchase(page, '合成普通采购', '2027-09-29', '低')
            edited = self.exchange(page, ITEMS + '/' + uid, lambda: button(page, '保存').click(), method='PATCH')
            assert edited['payload']['revision'] == original['revision']
            self.saved_item(page, uid)
            assert (self.item(ctx, uid)['due'], self.item(ctx, uid)['priority']) == ('2027-09-29', 'low')
            self.open_shopping(page)
            icon_button(page, '编辑合成普通采购').click()
            expect(textfield(page, '采购截止日期（可选）')).to_have_value('2027-09-29')
            self.fill_purchase(page, '合成普通采购', '', '普通')
            cleared = self.exchange(page, ITEMS + '/' + uid, lambda: button(page, '保存').click(), method='PATCH')
            assert cleared['payload']['due'] == '' and cleared['payload']['priority'] == 'normal'
            self.saved_item(page, uid)
            self.restart()
            self.open_shopping(page)
            expect(page.get_by_test_id('shopping-item-' + uid)).to_contain_text('未设截止日')
            final = self.item(ctx, uid)
            assert len(self.shopping(ctx)) == 1 and (final['due'], final['priority']) == ('', 'normal')
            assert all(final[key] == original[key] for key in ('id', 'owner', 'quantity', 'budget', 'actual', 'photoIds', 'done'))
            self.record('final-item', final)
            self.proof('final-database')
            self.passed('Ordinary UI create/edit/clear retains original purchase and money; real refresh and app restart preserve empty deadline/normal priority')

    def local_brief_schedule(self, browser):
        with self.flow(browser) as (ctx, page):
            self.open_assistant(page)
            before = self.proof('before-local-brief')
            textfield(page, '告诉助理你的需求').fill(PROMPT)
            brief = self.exchange(page, BRIEF, lambda: button(page, '整理并预览').click())
            assert brief['payload'].get('useModel', False) is False and brief['result']['mode'] == 'local'
            advisory = brief['result']['brief']['shopping'][0]
            assert (advisory['due'], advisory['dueOffsetDays'], advisory['priority'], advisory['owner']) == ('', -3, 'high', 'member1')
            assert advisory['sourceText'] == PROMPT.splitlines()[-1]
            assert self.snapshot() == before
            expect(page.get_by_test_id('journey-brief-purchase-1')).to_be_visible()
            textfield(page, '采购距出发天数 1').fill('-5')
            page.get_by_role('radio', name='采购优先级低 1', exact=True).click()
            self.choose_members(page)
            bridged = self.exchange(page, PREVIEW, lambda: button(page, '核对并继续编辑').click())['result']
            assert bridged['canApply']
            row = bridged['plan']['shopping'][0]
            assert (row['due'], row['priority'], row['budget']) == ('2027-09-26', 'low', 10000)
            expect(page.get_by_role('heading', name='计划旅行', exact=True)).to_be_visible()
            accordion = page.get_by_role('button', name=re.compile('准备清单与采购'))
            if not textfield(page, '采购截止日期 1（可选）').is_visible():
                accordion.click()
            expect(textfield(page, '采购截止日期 1（可选）')).to_have_value('2027-09-26')
            textfield(page, '采购截止日期 1（可选）').fill('2027-09-27')
            page.get_by_label('采购优先级 1：高', exact=True).click()
            preview = self.exchange(page, PREVIEW, lambda: button(page, '预览变更').click())['result']
            assert preview['canApply'] and self.snapshot() == before
            assert (preview['plan']['shopping'][0]['due'], preview['plan']['shopping'][0]['priority']) == ('2027-09-27', 'high')
            self.capture(page, 'travel-preview', button(page, '确认保存旅行'))
            saved = self.exchange(page, APPLY, lambda: button(page, '确认保存旅行').click(), status=201)['result']
            self.show_saved(page, saved['tripId'])
            detail = self.get(ctx, '/api/journeys/' + saved['id'])
            assert len(detail['shopping']) == 1
            actual = detail['shopping'][0]
            assert (actual['due'], actual['priority'], actual['budget'], actual['owner']) == ('2027-09-27', 'high', 10000, 'member1')
            assert actual['workflowKey'] == 'shopping:' + preview['plan']['shopping'][0]['key']
            assert self.item(ctx, actual['id'])['due'] == actual['due']
            self.open_shopping(page)
            expect(page.get_by_test_id('shopping-item-' + actual['id'])).to_contain_text('2027-09-27')
            expect(page.get_by_test_id('shopping-item-' + actual['id'])).to_contain_text('高优先级')
            self.record('saved-journey', detail)
            final = self.proof('final-database')
            assert final['task_publications'] == before['task_publications'] and final['calendar_publications'] == before['calendar_publications']
            self.passed('Real local assistant explicit source -> editable relative deadline/priority -> main editor -> real preview/apply -> same linked purchase visible in shopping')

    def seed_journey(self, ctx):
        rows = [{'key': key, 'title': title, 'due': due, 'priority': priority, 'budget': 10000, 'quantity': '2 件', 'owner': 'member1', 'note': '合成采购'}
                for key, title, due, priority in [('move', '合成移动采购', '2027-09-28', 'high'), ('keep', '合成保留采购', '2027-09-29', 'low'),
                                                ('done', '合成已买采购', '2027-09-27', 'normal'), ('empty', '合成无日期采购', '', 'normal')]]
        plan = {'title': '合成采购改期旅行', 'start': '2027-10-01', 'end': '2027-10-07', 'international': True,
                'memberIds': ['member1', 'member2'], 'budget': 2000000, 'shopping': rows, 'checklist': [], 'segments': [],
                'destinations': [{'key': 'stop', 'city': '东京', 'country': '日本'}]}
        p = self.write(ctx, 'POST', PREVIEW, {'plan': plan})
        saved = self.write(ctx, 'POST', APPLY, {'previewToken': p['previewToken'], 'idempotencyKey': 'synthetic-shopping-reschedule'}, status=201)
        detail = self.get(ctx, '/api/journeys/' + saved['id'])
        done = next(row for row in detail['shopping'] if row['workflowKey'] == 'shopping:done')
        self.write(ctx, 'PATCH', ITEMS + '/' + done['id'], {'revision': done['revision'], 'done': True})
        return self.get(ctx, '/api/journeys/' + saved['id'])

    def selected_reschedule(self, browser):
        with self.flow(browser) as (ctx, page):
            original = self.seed_journey(ctx)
            before = self.proof('before-reschedule')
            self.show_saved(page, original['tripId'])
            icon_button(page, '调整日期').click()
            expect(textfield(page, '新的出发日期')).to_have_value('2027-10-01')
            for title in ('合成移动采购', '合成保留采购'):
                expect(page.get_by_role('checkbox', name='联动改期：' + title, exact=True)).not_to_be_checked()
            for title in ('合成已买采购', '合成无日期采购'):
                expect(page.get_by_role('checkbox', name='联动改期：' + title, exact=True)).to_have_count(0)
            textfield(page, '新的出发日期').fill('2027-10-08')
            textfield(page, '新的返程日期').fill('2027-10-14')
            page.get_by_role('checkbox', name='联动改期：合成移动采购', exact=True).click()
            preview = self.exchange(page, '/api/journeys/' + original['id'] + '/reschedule-preview', lambda: button(page, '预览改期').click())
            assert preview['payload']['selectedKeys'] == ['shopping:move'] and preview['result']['canApply']
            rows = {row['key']: row for row in preview['result']['items']}
            assert rows['shopping:move']['after']['start'] == '2027-10-05'
            assert all(rows[key]['after'] == rows[key]['before'] and not rows[key]['selected'] for key in ('shopping:keep', 'shopping:done', 'shopping:empty'))
            assert self.snapshot() == before
            self.capture(page, 'reschedule-preview', button(page, '确认改期'))
            self.exchange(page, APPLY, lambda: button(page, '确认改期').click())
            expect(button(page, '返回旅行详情')).to_be_visible()
            button(page, '返回旅行详情').click()
            updated = self.get(ctx, '/api/journeys/' + original['id'])
            assert updated['tripId'] == original['tripId'] and updated['trip']['start'] == '2027-10-08'
            for old in original['shopping']:
                new = next(row for row in updated['shopping'] if row['id'] == old['id'])
                if old['workflowKey'] != 'shopping:move':
                    assert new == old
                else:
                    assert new['due'] == '2027-10-05' and new['revision'] == old['revision'] + 1
                    assert all(new[key] == old[key] for key in ('id', 'owner', 'tripId', 'journeyId', 'workflowKey', 'priority', 'quantity', 'budget', 'actual', 'photoIds', 'done', 'note'))
            self.restart()
            assert self.get(ctx, '/api/journeys/' + original['id']) == updated
            self.record('saved-journey', updated)
            self.proof('final-database')
            self.passed('Real travel reschedule moves exactly one selected dated unfinished purchase; completed, undated and unselected rows and unrelated metadata remain unchanged after restart')

    def offline_draft(self, browser):
        with self.flow(browser) as (ctx, page):
            self.open_shopping(page)
            button(page, '添加采购').click()
            self.fill_purchase(page, '合成离线采购', '2027-09-30', '低')
            expect(page.get_by_label('采购优先级：低', exact=True)).to_have_attribute('aria-checked', 'true')
            before = self.proof('before-offline')
            posts = self.count_requests('POST', ITEMS)
            try:
                ctx.set_offline(True)
                page.wait_for_function('() => navigator.onLine === false')
                button(page, '保存').click()
                expect(page.get_by_text(re.compile('暂时无法确认保存结果'))).to_be_visible()
                expect(textfield(page, '物品名称')).to_have_value('合成离线采购')
                expect(textfield(page, '采购截止日期（可选）')).to_have_value('2027-09-30')
                expect(page.get_by_label('采购优先级：低', exact=True)).to_have_attribute('aria-checked', 'true')
                expect(button(page, '保存')).to_be_disabled()
                expect(page.get_by_label('采购优先级：高', exact=True)).to_be_disabled()
                expect(page.get_by_text('已保存采购', exact=True)).not_to_be_visible()
                assert self.snapshot() == before
                self.capture(page, 'offline-draft', textfield(page, '采购截止日期（可选）'))
            finally:
                ctx.set_offline(False)
            assert self.shopping(ctx) == [] and self.count_requests('POST', ITEMS) == posts
            expect(textfield(page, '采购截止日期（可选）')).to_have_value('2027-09-30')
            expect(page.get_by_label('采购优先级：低', exact=True)).to_have_attribute('aria-checked', 'true')
            expect(button(page, '保存')).to_be_disabled()
            # Explicitly close only after checking actual server state; the UI
            # neither discarded this draft on failure nor resent it on reconnect.
            button(page, '关闭并核对').click()
            self.open_shopping(page)
            expect(page.get_by_text('合成离线采购', exact=True)).not_to_be_visible()
            button(page, '添加采购').click()
            self.fill_purchase(page, '合成离线采购', '2027-09-30', '低')
            saved = self.exchange(page, ITEMS, lambda: button(page, '保存').click(), status=201)['result']
            self.saved_item(page, saved['id'])
            rows = self.shopping(ctx)
            assert len(rows) == 1 and (rows[0]['due'], rows[0]['priority']) == ('2027-09-30', 'low')
            assert self.count_requests('POST', ITEMS) == posts + 1
            self.record('recovered-purchase', rows[0])
            self.proof('final-database')
            self.passed('Actual browser offline fails before write, preserves date/priority draft, shows no saved result and sends nothing automatically after reconnect; explicit new save creates once')

    @classmethod
    def run_scenarios(cls, root, bundle, report, out, browser):
        for name in CASES:
            case_out = out / name
            case_out.mkdir()
            folder, before, case = None, len(report['checks']), {'name': name, 'passed': False}
            try:
                with ExitStack() as lifecycle:
                    folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='expo-shopping-schedule-')))
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
    out = root / 'test-results' / ('expo-shopping-schedule-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], unexpectedProviderAttempts=[],
                  screenshots=[], scenarioResults=[], scenarioFailures=[], httpEvidence=[], databaseEvidence=[], providerEvidence=[],
                  requestedChecks=len(CASES), head=head, tree=tree, buildEvidenceSha256=sha(evidence_path),
                  harnessSha256=sha(out / 'executed-harness.py'), buildSourceHead=build_head, buildSourceTree=evidence['sourceTree'],
                  sourceRoot=str(root), bundleRoot=str(bundle), sourceHashesBefore=hashes(), bundleHashesBefore=export_hashes(bundle),
                  productionWrites=0, realModel=False, realCloud=False, physicalTelevision=False,
                  scope='Four independent real local Flask/SQLite/HTTPS/Edge flows. Actual local assistant parser, original business HTTP, browser offline failure. No model/provider substitution, real cloud or production validation.')
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
                assert len(report['checks']) == len(CASES) and len(report['screenshots']) == 8
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
            report['temporaryFixtureRemoved'] = len(report['scenarioResults']) == len(CASES) and all(c['temporaryFixtureRemoved'] for c in report['scenarioResults'])
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
