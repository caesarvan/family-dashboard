"""Frozen Expo journey brief against real local Flask, SQLite and Edge.

Only the optional model function is synthetic. All business HTTP handlers and
SQLite writes are real; response-loss cases commit before dropping the reply.
No production, real AI, real cloud calendar, file import or physical TV claim.
"""
import argparse
from contextlib import ExitStack, closing
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
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
import browser_expo_finance_check as fixture_harness
from browser_expo_finance_check import Run as FinanceRun, button, sha


BRIEF = '/api/assistant/journey-brief'
PREVIEW = '/api/journeys/preview'
APPLY = '/api/journeys/apply'
TABLES = ('entities', 'journey_workflows', 'journey_links', 'journey_actions',
          'assistant_plans', 'calendar_publications', 'task_publications')
WIDTHS = (320, 390, 1040, 1440)
PROMPT = '''旅行名称：合成东京京都旅行
出发日期：2027-10-01
返程日期：2027-10-06
旅行类型：境外
家庭总预算（人民币）：20000.25元
日本/东京 2027-10-01 至 2027-10-03
日本/京都 2027-10-03 至 2027-10-06'''


def textfield(page, name):
    return page.get_by_role('textbox', name=name, exact=True)


class Run(FinanceRun):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        loaded = Path(fixture_harness.__file__).resolve()
        assert sha(loaded) == sha(self.root / 'tests/browser_expo_finance_check.py')
        assert sha(Path(__file__)) == sha(self.root / 'tests/browser_expo_journey_brief_check.py')
        self.report.update(fixtureHarnessPath=str(loaded), fixtureHarnessSha256=sha(loaded), modelCalls=[])
        self.model_mode = 'success'
        self.assistant = importlib.import_module('home_assistant')
        self.lifecycle.enter_context(patch.object(self.assistant, 'model_journey_brief', self.fake_model))
        self.lifecycle.enter_context(patch.object(self.assistant, 'model_plan', self.unexpected_model))
        # Synthetic credentials permit the explicit model UI; fake_model is the
        # sole provider implementation and the socket guard also forbids egress.
        self.cfg.update(OPENAI_API_KEY='synthetic-key-never-sent', OPENAI_MODEL='synthetic-model')
        self.application.config.update(OPENAI_API_KEY='synthetic-key-never-sent', OPENAI_MODEL='synthetic-model')

    def fake_model(self, config, prompt):
        assert config['OPENAI_API_KEY'] == 'synthetic-key-never-sent'
        self.report['modelCalls'].append({'prompt': prompt, 'mode': self.model_mode})
        if self.model_mode == 'fail':
            raise ValueError('Synthetic model unavailable')
        return self.assistant.local_journey_brief(prompt)

    @staticmethod
    def unexpected_model(*_args, **_kwargs):
        raise AssertionError('No generic assistant model call was authorized by this fixture')

    def clear_finance(self):
        # Override the inherited financial fixture reset: these scenarios use
        # fresh browser sessions but preserve all synthetic business records.
        pass

    def snapshot(self):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database)) as con:
            return {table: sorted(con.execute('SELECT * FROM "' + table + '"').fetchall(), key=repr)
                    for table in TABLES}

    def open_assistant(self, page):
        page.goto(self.base + '/app/assistant')
        expect(page.get_by_role('heading', name='家庭助理', exact=True)).to_be_visible(timeout=15000)
        expect(textfield(page, '告诉助理你的需求')).to_be_enabled()

    def start_brief(self, page, prompt=PROMPT, model=False):
        self.open_assistant(page)
        textfield(page, '告诉助理你的需求').fill(prompt)
        if model:
            page.get_by_role('checkbox', name='使用已配置的 AI 整理', exact=True).click()
        with page.expect_response(lambda r: urlsplit(r.url).path == BRIEF and r.request.method == 'POST') as pending:
            button(page, '整理并预览').click()
        response = pending.value
        expect(page.get_by_test_id('journey-brief-form')).to_be_visible()
        return response

    def fill_brief(self, page, title='合成手补旅行', budget='0'):
        for label, value in [('旅行名称', title), ('出发日期', '2028-03-02'),
                ('返程日期', '2028-03-04'), ('旅行总预算（元）', budget),
                ('国家或地区 1', '日本'), ('城市 1', '东京'),
                ('抵达日期 1', '2028-03-02'), ('离开日期 1', '2028-03-04')]:
            textfield(page, label).fill(value)
        page.get_by_role('radio', name='境外旅行', exact=True).click()

    def choose_members(self, page, identifiers=('member1', 'member2')):
        people = self.get(page.context, '/api/state')['people']
        for person in people:
            control = page.get_by_role('checkbox', name='出行成员：' + person['name'], exact=True)
            if control.is_checked() != (person['id'] in identifiers):
                control.click()

    def bridge(self, page, members=('member1', 'member2')):
        self.choose_members(page, members)
        with page.expect_response(lambda r: urlsplit(r.url).path == PREVIEW and r.request.method == 'POST') as pending:
            button(page, '核对并继续编辑').click()
        result = pending.value
        assert result.status == 200, result.text()
        expect(page.get_by_role('heading', name='计划旅行', exact=True)).to_be_visible()
        expect(button(page, '预览变更')).to_be_enabled()
        assert result.json()['canApply']
        return result.json()

    def preview(self, page):
        with page.expect_response(lambda r: urlsplit(r.url).path == PREVIEW and r.request.method == 'POST') as pending:
            button(page, '预览变更').click()
        result = pending.value
        assert result.status == 200, result.text()
        expect(button(page, '确认保存旅行')).to_be_enabled()
        assert result.json()['canApply']
        return result.json()

    def confirm(self, page, name='确认保存旅行'):
        with page.expect_response(lambda r: urlsplit(r.url).path == APPLY and r.request.method == 'POST') as pending:
            button(page, name).click()
        result = pending.value
        assert result.status in (200, 201), result.text()
        value = result.json()
        expect(page.get_by_role('heading', name='旅行详情', exact=True)).to_be_visible()
        expect(button(page, '编辑旅行')).to_be_enabled()
        return value

    def show_saved(self, page, trip_id):
        page.goto(self.base + '/app/trips?request=1001&item=' + trip_id)
        expect(page.get_by_role('heading', name='旅行详情', exact=True)).to_be_visible(timeout=15000)
        expect(button(page, '编辑旅行')).to_be_enabled()

    def ordinary_task(self, browser):
        with self.flow(browser) as (ctx, page):
            self.open_assistant(page)
            before = self.snapshot()
            calls = self.count_requests('POST', BRIEF)
            textfield(page, '告诉助理你的需求').fill('待办：合成核对旅行酒店')
            button(page, '整理并预览').click()
            expect(button(page, '确认保存 1 项')).to_be_enabled()
            assert self.snapshot()['entities'] == before['entities']
            button(page, '确认保存 1 项').click()
            expect(page.get_by_text('本次已保存 1 项', exact=True)).to_be_visible()
            tasks = self.get(ctx, '/api/state')['tasks']
            assert len([row for row in tasks if row['title'] == '合成核对旅行酒店']) == 1
            assert self.count_requests('POST', BRIEF) == calls
            assert self.snapshot()['journey_workflows'] == before['journey_workflows']
            self.passed('Explicit local task containing travel text still previews and saves one real task without entering the travel brief')

    def missing_fields(self, browser):
        with self.flow(browser) as (ctx, page):
            before = self.snapshot()
            response = self.start_brief(page, '未来旅行想去日本，时间和总预算还没有决定')
            assert response.status == 200 and response.json()['brief']['budgetCents'] is None
            expect(textfield(page, '旅行总预算（元）')).to_have_value('')
            expect(textfield(page, '出发日期')).to_have_value('')
            self.fill_brief(page, budget='')
            self.choose_members(page, ('member2',))
            previews = self.count_requests('POST', PREVIEW)
            button(page, '核对并继续编辑').click()
            expect(page.get_by_test_id('journey-brief-form')).to_be_visible()
            assert self.count_requests('POST', PREVIEW) == previews
            assert self.snapshot() == before
            textfield(page, '旅行总预算（元）').fill('0')
            for width in WIDTHS:
                self.screenshot(page, 'brief-completed', width)
            normalized = self.bridge(page, ('member2',))
            assert normalized['plan']['budget'] == 0
            assert normalized['plan']['memberIds'] == ['member2']
            assert self.snapshot() == before
            self.passed('Unknown dates and budget require manual completion; explicit zero survives the real normalization preview and no business rows change')

    def full_roundtrip(self, browser):
        with self.flow(browser) as (ctx, page):
            before = self.snapshot()
            response = self.start_brief(page)
            assert response.status == 200 and response.json()['brief']['budgetCents'] == 2000025
            expect(textfield(page, '旅行名称')).to_have_value('合成东京京都旅行')
            assert self.snapshot() == before
            self.bridge(page)
            assert self.snapshot() == before
            people = {row['id']: row['name'] for row in self.get(ctx, '/api/state')['people']}
            # The normalized suggestions remain editable before a new, explicit
            # confirmation. We test actual selected owners, not their labels only.
            page.get_by_text('准备清单与采购', exact=True).click()
            textfield(page, '准备事项 1').fill('合成核对证件')
            page.get_by_label('准备负责人 1：' + people['member1'], exact=True).click()
            button(page, '增加采购').click()
            textfield(page, '采购名称 1').fill('合成转换插头')
            textfield(page, '采购数量 1').fill('2 件')
            page.get_by_label('采购负责人 1：' + people['member2'], exact=True).click()
            textfield(page, '采购预算（元，可不填） 1').fill('123.45')
            button(page, '增加采购').click()
            textfield(page, '采购名称 2').fill('合成未定预算收纳袋')
            expect(textfield(page, '采购预算（元，可不填） 2')).to_have_value('')
            normalized = self.preview(page)
            assert normalized['plan']['shopping'][0]['budget'] == 12345
            assert normalized['plan']['shopping'][1]['budget'] is None
            assert self.snapshot() == before
            for width in WIDTHS:
                self.screenshot(page, 'journey-confirmation', width)
            receipt = self.confirm(page)
            detail = self.get(ctx, '/api/journeys/' + receipt['id'])
            assert detail['tripId'] == receipt['tripId'] and detail['plan']['budget'] == 2000025
            assert detail['plan']['memberIds'] == ['member1', 'member2']
            assert next(item for item in detail['tasks'] if item['title'] == '合成核对证件')['owner'] == 'member1'
            purchase = next(item for item in detail['shopping'] if item['title'] == '合成转换插头')
            assert (purchase['owner'], purchase['budget'], purchase['quantity']) == ('member2', 12345, '2 件')
            assert next(item for item in detail['shopping'] if item['title'] == '合成未定预算收纳袋')['budget'] is None
            assert detail['budget']['unknownPurchaseBudgets'] == 1
            assert detail['calendar']['cloud'] == 'not_requested'
            assert all(item['tripId'] == receipt['tripId'] for group in ('events', 'tasks', 'shopping') for item in detail[group])
            after = self.snapshot()
            assert len(after['journey_workflows']) == len(before['journey_workflows']) + 1
            assert len(after['journey_actions']) == len(before['journey_actions']) + 1
            assert after['calendar_publications'] == before['calendar_publications']
            assert after['task_publications'] == before['task_publications']
            self.restart()
            assert self.get(ctx, '/api/journeys/' + receipt['id']) == detail
            self.show_saved(page, receipt['tripId'])
            expect(page.get_by_text('合成核对证件', exact=True)).to_be_visible()
            expect(page.get_by_text('合成转换插头', exact=True)).to_be_visible()
            for width in WIDTHS:
                self.screenshot(page, 'journey-persisted', width)
            self.passed('Brief, normalized draft and final preview are read-only; explicit confirmation persists member choices, preparation owners, exact purchase cents and unknown budgets across a real app restart')

    def failed_model(self, browser):
        with self.flow(browser) as (ctx, page):
            before = self.snapshot()
            self.model_mode = 'fail'
            calls = len(self.report['modelCalls'])
            response = self.start_brief(page, PROMPT.replace('合成东京京都旅行', '合成模型失败后保留'), model=True)
            assert response.status == 502
            expect(textfield(page, '旅行原始需求')).to_have_value(PROMPT.replace('合成东京京都旅行', '合成模型失败后保留'))
            assert len(self.report['modelCalls']) == calls + 1 and self.snapshot() == before
            page.get_by_role('checkbox', name='使用 AI 整理这段文字', exact=True).click()
            with page.expect_response(lambda r: urlsplit(r.url).path == BRIEF and r.request.method == 'POST') as retry:
                button(page, '整理旅行简报').click()
            assert retry.value.status == 200 and retry.value.json()['mode'] == 'local'
            expect(textfield(page, '旅行名称')).to_have_value('合成模型失败后保留')
            assert len(self.report['modelCalls']) == calls + 1 and self.snapshot() == before
            self.model_mode = 'success'
            self.passed('Explicit synthetic model failure preserves the original input; only user-selected local retry continues and no model or save is automatically repeated')

    def lost_apply_reply(self, browser):
        with self.flow(browser) as (ctx, page):
            before = self.snapshot()
            response = self.start_brief(page, PROMPT.replace('合成东京京都旅行', '合成原确认恢复'))
            assert response.status == 200
            self.bridge(page)
            self.preview(page)
            attempts, real_results = [], []

            def lose(route):
                if route.request.method != 'POST':
                    return route.continue_()
                attempts.append(route.request.post_data_json)
                reply = route.fetch(max_redirects=0)
                assert reply.status == 201, reply.text()
                real_results.append(reply.json())
                route.abort('failed')

            page.route(self.base + APPLY, lose)
            button(page, '确认保存旅行').click()
            expect(button(page, '核对原保存')).to_be_enabled(timeout=15000)
            page.unroute(self.base + APPLY, lose)
            assert len(attempts) == len(real_results) == 1
            committed = self.snapshot()
            assert len(committed['journey_actions']) == len(before['journey_actions']) + 1
            with page.expect_response(lambda r: urlsplit(r.url).path == APPLY and r.request.method == 'POST') as pending:
                button(page, '核对原保存').click()
            response = pending.value
            assert response.status == 200 and response.json()['replayed'] is True
            assert response.request.post_data_json == attempts[0]
            assert response.json()['id'] == real_results[0]['id']
            expect(page.get_by_role('heading', name='旅行详情', exact=True)).to_be_visible()
            assert self.snapshot() == committed
            assert self.get(ctx, '/api/journeys/' + response.json()['id'])['trip']['title'] == '合成原确认恢复'
            self.passed('Dropped successful apply reply is recovered by the identical preview token and operation key; SQLite has exactly one workflow action and no duplicate entities')

    def late_identity(self, browser, path):
        with self.flow(browser) as (ctx, page):
            before = self.snapshot()
            unique = '合成旧成员迟到简报' if path == BRIEF else '合成旧成员迟到桥接'
            prompt = PROMPT.replace('合成东京京都旅行', unique)
            if path == BRIEF:
                self.open_assistant(page)
                textfield(page, '告诉助理你的需求').fill(prompt)
            else:
                assert self.start_brief(page, prompt).status == 200
                self.choose_members(page)
            held = []

            def hold(route):
                held.append((route, route.fetch(max_redirects=0)))

            page.route(self.base + path, hold)
            button(page, '整理并预览' if path == BRIEF else '核对并继续编辑').click()
            self.settle(page, lambda: bool(held))
            assert held[0][1].status == 200
            self.login(ctx, 2)
            assert self.get(ctx, '/api/me')['user']['id'] == 'member2'
            for route, response in held:
                route.fulfill(response=response)
            page.unroute(self.base + path, hold)
            expect(page.get_by_test_id('journey-brief-form')).to_have_count(0, timeout=15000)
            expect(textfield(page, '出发日期（YYYY-MM-DD）')).to_have_count(0)
            expect(page.locator('body')).not_to_contain_text(unique)
            assert not page.locator('input,textarea').evaluate_all(
                '(elements, token) => elements.some(e => e.getBoundingClientRect().width > 0 && e.value.includes(token))', unique)
            assert self.snapshot() == before
            assert not any(unique in str(value) for value in self.get(ctx, '/api/journeys')['journeys'])
            self.passed('Late ' + path + ' response after a real member-cookie change cannot install old draft content or create records')

    def run_scenarios(self, browser):
        self.ordinary_task(browser)
        self.missing_fields(browser)
        self.full_roundtrip(browser)
        self.failed_model(browser)
        self.lost_apply_reply(browser)
        self.late_identity(browser, BRIEF)
        self.late_identity(browser, PREVIEW)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--expected-build-evidence', required=True)
    args = parser.parse_args()
    root, bundle = args.source_root.resolve(), args.bundle.resolve()
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    assert head == args.expected_head, 'Unexpected source commit'
    evidence_path = bundle.parent / 'build-evidence.json'
    assert sha(evidence_path) == args.expected_build_evidence
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    assert evidence['sourceHead'] == head
    assert evidence['sourceTree'] == subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=root, text=True).strip()
    assert not subprocess.check_output(['git', 'status', '--porcelain=v1', '--untracked-files=no'], cwd=root, text=True).strip()
    names = subprocess.check_output(['git', 'ls-files'], cwd=root, text=True).splitlines()
    hashes = lambda: {name: sha(root / name) for name in names}
    bundle_hashes = lambda: {p.relative_to(bundle).as_posix(): sha(p) for p in bundle.rglob('*') if p.is_file()}
    assert bundle_hashes() == evidence['files']
    assert all(sha(root / name) == digest for name, digest in evidence['inputFiles'].items())
    out = Path(__file__).resolve().parents[1] / 'test-results' / ('expo-journey-brief-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], screenshots=[],
        head=head, tree=evidence['sourceTree'], buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(out / 'executed-harness.py'),
        sourceHashesBefore=hashes(), bundleHashesBefore=bundle_hashes(), productionWrites=0, realCloud=False,
        realAI=False, fileImport=False, physicalTelevision=False,
        scope='Frozen Expo bundle, actual local Flask/SQLite/Edge/member sessions/CSRF. Synthetic travel text and optional fake model only. Screenshots cover visible viewport content, not every inner scroll position.')
    original_connect = socket.socket.connect

    def local_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
            report['externalRequests'].append({'kind': 'non-loopback socket'})
            raise AssertionError('External network forbidden')
        return original_connect(sock, address)

    try:
        with ExitStack() as lifecycle:
            lifecycle.enter_context(patch.object(socket.socket, 'connect', local_connect))
            folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='expo-journey-brief-')))
            run = Run(root, bundle, folder, report, out, lifecycle)
            with sync_playwright() as pw, ExitStack() as browsers:
                browser = pw.chromium.launch(channel='msedge', headless=True)
                browsers.callback(browser.close)
                run.run_scenarios(browser)
                assert not report['pageErrors'] and not report['externalRequests']
                report['passed'] = True
    except Exception:
        report['failure'] = traceback.format_exc()
        print(report['failure'], flush=True)
    finally:
        report['sourceHashesAfter'] = hashes()
        report['bundleHashesAfter'] = bundle_hashes()
        report['sourceUnchanged'] = report['sourceHashesBefore'] == report['sourceHashesAfter']
        report['bundleUnchanged'] = report['bundleHashesBefore'] == report['bundleHashesAfter']
        report['passed'] = report['passed'] and report['sourceUnchanged'] and report['bundleUnchanged']
        (out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'report': str(out / 'result.json')}, ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    raise SystemExit(main())
