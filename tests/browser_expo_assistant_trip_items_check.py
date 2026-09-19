"""Synthetic model -> real journey brief/items -> preview/apply in frozen Expo.

Four independent temporary Flask/SQLite/Edge scenarios. Only _model_json is
synthetic: production brief normalization, grounding, member resolution, HTTP,
preview and explicit apply execute unchanged. Interception may delay/drop real
responses, or label a request as unsent; it never invents a business response.
No real provider, production, cloud account or physical-device acceptance.

Use -B -X utf8 --source-root PATH --expected-head COMMIT --bundle EXPORT
--expected-build-evidence SHA. Optional --build-source-head must be an ancestor
with the identical complete frontend tree and individually bound build inputs.
"""
import argparse
from contextlib import ExitStack, closing
from copy import deepcopy
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

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import ThreadedWSGIServer
import browser_expo_finance_check as fixture
import browser_expo_journey_brief_check as brief_fixture
from browser_expo_finance_check import Run as BaseRun, button, sha
from browser_expo_journey_brief_check import BRIEF, PREVIEW, APPLY, TABLES, textfield, icon_button


HARNESS = 'tests/browser_expo_assistant_trip_items_check.py'
CASES = ('items_apply_restart', 'unresolved_and_duplicate_members',
         'edited_dates_lists_and_recovery', 'late_model_edit_and_identity')
WIDTHS = (390, 1280)


def example(title, *, other='合成同行', unknown=False):
    """Raw, untrusted model JSON; every advisory is backed by one prompt line."""
    task_lines = [f'准备：合成核对护照 | 负责人：{"合成未加入" if unknown else "我"} | 出发前：3天',
                  f'准备：合成打印行程 | 负责人：{other} | 截止日期：2027-09-30']
    purchase_lines = [f'采购：合成转换插头 | 数量：2 件 | 负责人：{other} | 预算：123.45元',
                      '采购：合成收纳袋 | 数量：1 件 | 负责人：我 | 预算：未知']
    prompt = '\n'.join([f'旅行名称：{title}', '出发日期：2027-10-01', '返程日期：2027-10-06',
                        '旅行类型：境外', '家庭总预算（人民币）：20000.25元',
                        '日本/东京 2027-10-01 至 2027-10-06', *task_lines, *purchase_lines])
    raw = dict(title=title, start='2027-10-01', end='2027-10-06', budgetCents=2000025,
               international=True, note='', destinations=[dict(country='日本', city='东京',
               arrival='2027-10-01', departure='2027-10-06')], checklist=[
        dict(title='合成核对护照', assigneeText='合成未加入' if unknown else '我', note='',
             sourceText=task_lines[0], due='', dueOffsetDays=-3),
        dict(title='合成打印行程', assigneeText=other, note='', sourceText=task_lines[1],
             due='2027-09-30', dueOffsetDays=None)], shopping=[
        dict(title='合成转换插头', assigneeText=other, note='', sourceText=purchase_lines[0],
             quantity='2 件', budgetCents=12345),
        dict(title='合成收纳袋', assigneeText='我', note='', sourceText=purchase_lines[1],
             quantity='1 件', budgetCents=None)])
    return prompt, raw


def export_hashes(bundle):
    """Do not silently omit Windows exports beyond MAX_PATH."""
    assert bundle.is_dir() and not bundle.is_symlink() and not bundle.is_junction()
    extended = Path('\\\\?\\' + str(bundle)) if os.name == 'nt' and not str(bundle).startswith('\\\\?\\') else bundle
    result = {}
    def walk_error(error):
        raise error
    for current, directories, leaves in os.walk(extended, onerror=walk_error):
        for name in directories + leaves:
            path = Path(current) / name
            assert not path.is_symlink() and not path.is_junction()
        for name in leaves:
            path = Path(current) / name
            assert path.is_file()
            key = path.relative_to(extended).as_posix()
            assert key not in result
            result[key] = sha(path)
    return result


class Run(BaseRun):
    # Reuse the existing real UI navigation; the parent brief constructor and
    # its model_journey_brief substitution are deliberately NOT invoked.
    open_assistant = brief_fixture.Run.open_assistant
    show_saved = brief_fixture.Run.show_saved

    def __init__(self, root, bundle, folder, report, out, lifecycle):
        assert ThreadedWSGIServer.block_on_close is True
        lifecycle.enter_context(patch.object(ThreadedWSGIServer, 'daemon_threads', False))
        super().__init__(root, bundle, folder, report, out, lifecycle)
        assert self.server.daemon_threads is False and self.server.block_on_close is True
        assert Path(self.source.__file__).resolve() == (root / 'app.py').resolve()
        assert {BRIEF, PREVIEW, APPLY} <= {rule.rule for rule in self.application.url_map.iter_rules()}
        paths = {HARNESS: Path(__file__), 'tests/browser_expo_finance_check.py': Path(fixture.__file__),
                 'tests/browser_expo_journey_brief_check.py': Path(brief_fixture.__file__)}
        for name in ('app', 'home_assistant', 'journey_workflows', 'member_sessions', 'membership_storage'):
            paths[name + '.py'] = Path(sys.modules[name].__file__)
        hashes = {name: sha(path) for name, path in paths.items()}
        assert all(value == sha(root / name) for name, value in hashes.items())
        assert hashes[HARNESS] == report['harnessSha256']
        assert report.setdefault('fixtureHashes', hashes) == hashes
        actual = {name: str(path.resolve()) for name, path in paths.items()}
        assert report.setdefault('fixtureActualPaths', actual) == actual
        report['requestThreadShutdown'] = {'daemonThreads': False, 'blockOnClose': True}
        self.assistant = sys.modules['home_assistant']
        self.model_outputs = {}
        self.exchange_number = 0
        lifecycle.enter_context(patch.object(self.assistant, '_model_json', self.synthetic_provider))
        lifecycle.enter_context(patch.object(self.assistant, 'model_plan', self.forbidden_provider))
        settings = dict(ASSISTANT_PROVIDER='openai', OPENAI_API_KEY='synthetic-key-never-sent', OPENAI_MODEL='synthetic-model')
        self.cfg.update(settings)
        self.application.config.update(settings)

    def forbidden_provider(self, *_args, **_kwargs):
        self.report['unexpectedProviderAttempts'].append(self.out.name)
        raise AssertionError('Only the registered synthetic journey-brief provider is allowed')

    def synthetic_provider(self, config, payload):
        assert config['OPENAI_API_KEY'] == 'synthetic-key-never-sent'
        value = json.loads(payload['input'])
        assert set(value) == {'request'}, 'No member list, household records or previous draft may reach the model'
        prompt = value['request']
        assert prompt in self.model_outputs, 'Unexpected provider input'
        raw = deepcopy(self.model_outputs[prompt])
        self.report['modelCalls'].append({'scenario': self.out.name, 'request': prompt,
            'input': value, 'instructions': payload['instructions'], 'rawAdvisory': raw})
        return raw

    def register_example(self, title, **kwargs):
        prompt, raw = example(title, **kwargs)
        assert prompt not in self.model_outputs
        self.model_outputs[prompt] = raw
        return prompt

    def clear_finance(self):
        pass  # A fresh temporary DB belongs exclusively to each scenario.

    def snapshot(self):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database)) as con:
            assert con.execute('PRAGMA foreign_key_check').fetchall() == []
            return {table: sorted(con.execute('SELECT * FROM "' + table + '"').fetchall(), key=repr) for table in TABLES}

    def record(self, name, value, group='httpEvidence'):
        path = self.out / (name + '.json')
        with path.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        self.report[group].append({'path': path.relative_to(self.out.parent).as_posix(), 'sha256': sha(path)})
        return value

    def database_proof(self, name):
        return self.record(name, self.snapshot(), 'databaseEvidence')

    def members(self, ctx, *, duplicate=False):
        # Setup goes through the actual profile endpoint, before business proofs.
        self.write(ctx, 'POST', '/api/profile', {'name': '合成同名' if duplicate else '合成本人'})
        self.login(ctx, 2)
        self.write(ctx, 'POST', '/api/profile', {'name': '合成同名' if duplicate else '合成同行'})
        self.login(ctx, 1)
        rows = self.get(ctx, '/api/state')['people']
        assert [row['id'] for row in rows] == ['member1', 'member2']
        return rows

    def choose_members(self, page):
        controls = page.get_by_role('checkbox', name=re.compile(r'^出行成员：'))
        expect(controls).to_have_count(2)
        for index in range(2):
            control = controls.nth(index)
            if control.get_attribute('aria-checked') != 'true':
                control.click()
            expect(control).to_have_attribute('aria-checked', 'true')

    def exchange(self, page, path, action, *, status=200, drop=None):
        """Only transport faults are synthetic; response bytes come from Flask."""
        assert drop in (None, 'request', 'response')
        self.exchange_number += 1
        stem = 'exchange-%02d' % self.exchange_number
        calls, url = [], self.base + path
        def intercept(route):
            assert route.request.method == 'POST'
            call = {'path': path, 'payload': route.request.post_data_json, 'drop': drop,
                    'sentToServer': drop != 'request', 'status': None, 'result': None}
            if drop == 'request':
                route.abort('failed')
            else:
                response = route.fetch(max_redirects=0)
                raw = response.body()
                saved = self.out / (stem + '.body')
                with saved.open('xb') as stream:
                    stream.write(raw)
                call.update(status=response.status, result=json.loads(raw), responseSha256=sha(saved))
                if drop == 'response':
                    route.abort('failed')
                else:
                    route.fulfill(status=response.status, headers=response.headers, body=raw)
            calls.append(call)  # Publish completion only after terminal action.
        page.route(url, intercept, times=1)
        try:
            action()
            self.settle(page, lambda: bool(calls))
            assert len(calls) == 1
            assert calls[0]['status'] == (None if drop == 'request' else status), calls
            return calls[0]
        finally:
            page.unroute(url, intercept)
            self.record(stem, calls)

    def start_items(self, page, prompt):
        self.open_assistant(page)
        textfield(page, '告诉助理你的需求').fill(prompt)
        page.get_by_role('checkbox', name='使用已配置的 AI 整理', exact=True).click()
        value = self.exchange(page, BRIEF, lambda: button(page, '整理并预览').click())['result']
        assert value['mode'] == 'model'
        expect(page.get_by_test_id('journey-brief-form')).to_be_visible(timeout=15000)
        expect(textfield(page, '旅行名称')).to_have_value(value['brief']['title'])
        expect(page.get_by_test_id('journey-brief-task-1')).to_be_visible()
        expect(page.get_by_test_id('journey-brief-purchase-1')).to_be_visible()
        return value

    def bridge(self, page):
        self.choose_members(page)
        value = self.exchange(page, PREVIEW, lambda: button(page, '核对并继续编辑').click())['result']
        assert value['canApply']
        expect(page.get_by_role('heading', name='计划旅行', exact=True)).to_be_visible(timeout=15000)
        expect(button(page, '预览变更')).to_be_enabled()
        return value

    def preview(self, page):
        value = self.exchange(page, PREVIEW, lambda: button(page, '预览变更').click())['result']
        assert value['canApply']
        expect(button(page, '确认保存旅行')).to_be_enabled()
        return value

    def choose_owner(self, page, kind, index, label):
        row = page.get_by_test_id(f'journey-brief-{kind}-{index}')
        control = button(row, ('准备负责人 ' if kind == 'task' else '采购负责人 ') + str(index))
        control.click()
        option = row.get_by_role('radio', name=label, exact=True)
        option.click()
        # The actual component closes the radiogroup after a choice.
        expect(control).to_contain_text('负责人：' + label)

    def shot(self, page, name, focus):
        for width in WIDTHS:
            page.set_viewport_size({'width': width, 'height': 844 if width == 390 else 1000})
            expect(focus).to_be_visible()
            focus.scroll_into_view_if_needed()
            page.evaluate('() => document.fonts.ready')
            page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
            metrics = page.evaluate('''() => ({width:innerWidth,scroll:document.documentElement.scrollWidth,
              clipped:[...document.querySelectorAll('input,textarea,button,[role="button"],[role="radio"],[role="checkbox"]')]
              .filter(n=>{const r=n.getBoundingClientRect();return r.width>0&&r.height>0&&r.bottom>0&&r.top<innerHeight&&getComputedStyle(n).visibility!=='hidden'&&(r.left< -2||r.right>innerWidth+2)})
              .map(n=>({label:n.getAttribute('aria-label')||n.textContent,box:n.getBoundingClientRect().toJSON()}))})''')
            assert metrics['scroll'] <= width + 2 and not metrics['clipped'], metrics
            path = self.out / f'{name}-{width}.png'
            page.screenshot(path=str(path), full_page=False)
            self.report['screenshots'].append({'path': path.relative_to(self.out.parent).as_posix(),
                'sha256': sha(path), 'metrics': metrics, 'scope': 'Settled visible viewport only; no claim for every inner scroll position.'})

    @staticmethod
    def no_external_queues(before, after):
        for table in ('assistant_plans', 'calendar_publications', 'task_publications'):
            assert after[table] == before[table], table

    def items_apply_restart(self, browser):
        with self.flow(browser) as (ctx, page):
            self.members(ctx)
            before = self.database_proof('before-brief')
            prompt = self.register_example('合成采购准备旅行')
            response = self.start_items(page, prompt)
            brief = response['brief']
            assert [row['owner'] for row in brief['checklist']] == ['member1', 'member2']
            assert [row['owner'] for row in brief['shopping']] == ['member2', 'member1']
            assert [row['budgetCents'] for row in brief['shopping']] == [12345, None]
            expect(textfield(page, '采购预算（元）1')).to_have_value('123.45')
            expect(textfield(page, '采购预算（元）2')).to_have_value('')
            assert self.snapshot() == before
            self.shot(page, 'extracted-items', page.get_by_test_id('journey-brief-shopping'))
            draft = self.bridge(page)['plan']
            assert draft['budget'] == 2000025 and draft['saved'] == draft['paid'] == 0
            assert draft['memberIds'] == ['member1', 'member2']
            assert [(r['owner'], r['due']) for r in draft['checklist']] == [('member1', '2027-09-28'), ('member2', '2027-09-30')]
            assert [(r['owner'], r['budget']) for r in draft['shopping']] == [('member2', 12345), ('member1', None)]
            assert self.snapshot() == before
            preview = self.preview(page)
            assert preview['plan'] == draft and self.snapshot() == before
            receipt = self.exchange(page, APPLY, lambda: button(page, '确认保存旅行').click(), status=201)['result']
            expect(page.get_by_role('heading', name='旅行详情', exact=True)).to_be_visible(timeout=15000)
            detail = self.record('saved-detail', self.get(ctx, '/api/journeys/' + receipt['id']))
            assert detail['plan'] == draft
            assert {r['title']: (r['owner'], r['budget']) for r in detail['shopping']} == {
                '合成转换插头': ('member2', 12345), '合成收纳袋': ('member1', None)}
            assert {r['title']: (r['owner'], r['due']) for r in detail['tasks']} == {
                '合成核对护照': ('member1', '2027-09-28'), '合成打印行程': ('member2', '2027-09-30')}
            assert detail['budget']['total'] == 2000025 and detail['budget']['purchaseBudget'] == 12345
            assert detail['budget']['unknownPurchaseBudgets'] == 1 and detail['calendar']['cloud'] == 'not_requested'
            assert all(r['tripId'] == receipt['tripId'] for group in ('tasks', 'shopping', 'events') for r in detail[group])
            after = self.database_proof('after-explicit-apply')
            assert len(after['journey_workflows']) == len(before['journey_workflows']) + 1
            assert len(after['journey_actions']) == len(before['journey_actions']) + 1
            self.no_external_queues(before, after)
            self.restart()
            assert self.get(ctx, '/api/journeys/' + receipt['id']) == detail
            assert self.database_proof('after-real-app-restart') == after
            self.show_saved(page, receipt['tripId'])
            expect(page.get_by_text('合成转换插头', exact=True)).to_be_visible()
            self.shot(page, 'persisted-items', page.get_by_text('合成转换插头', exact=True))
            assert len(self.report['modelCalls']) == 1
            self.passed('Synthetic model items ground through real brief; draft/preview write nothing; explicit apply persists exact owners/cents/null and independent total across app restart, without external queues')

    def unresolved_and_duplicate_members(self, browser):
        with self.flow(browser) as (ctx, page):
            self.members(ctx, duplicate=True)
            before = self.database_proof('before-ambiguous-brief')
            prompt = self.register_example('合成分工待核对旅行', other='合成同名', unknown=True)
            value = self.start_items(page, prompt)
            assert [r['owner'] for r in value['brief']['checklist']] == [None, None]
            assert [r['owner'] for r in value['brief']['shopping']] == [None, 'member1']
            self.choose_members(page)
            mark = self.count_requests('POST', PREVIEW)
            button(page, '核对并继续编辑').click()
            expect(page.get_by_role('alert')).to_be_visible()
            assert self.count_requests('POST', PREVIEW) == mark and self.snapshot() == before
            self.choose_owner(page, 'task', 1, '一起')
            self.choose_owner(page, 'task', 2, '合成同名（另一位成员）')
            self.choose_owner(page, 'purchase', 1, '合成同名（另一位成员）')
            preview = self.bridge(page)
            assert [r['owner'] for r in preview['plan']['checklist']] == ['shared', 'member2']
            assert [r['owner'] for r in preview['plan']['shopping']] == ['member2', 'member1']
            assert self.snapshot() == before
            self.record('explicit-member-resolution', preview)
            self.passed('Unknown and duplicate member wording stays unresolved and blocks preview; explicit UI choices identify the other same-name member or shared without guessing or saving')

    def edited_dates_lists_and_recovery(self, browser):
        with self.flow(browser) as (ctx, page):
            self.members(ctx)
            before = self.database_proof('before-edited-brief')
            self.start_items(page, self.register_example('合成编辑与原保存恢复'))
            textfield(page, '出发日期').fill('2027-10-02')
            textfield(page, '返程日期').fill('2027-10-07')
            expand = button(page, '展开目的地')
            if expand.count():
                expand.click()
            textfield(page, '抵达日期 1').fill('2027-10-02')
            textfield(page, '离开日期 1').fill('2027-10-07')
            textfield(page, '距出发天数 1').fill('-2')
            button(page, '移除准备事项 2').click()
            icon_button(page, '添加准备事项').click()
            textfield(page, '准备事项标题 2').fill('合成新增取件')
            self.choose_owner(page, 'task', 2, '合成同行')
            page.get_by_role('radio', name='固定截止日期 2', exact=True).click()
            textfield(page, '准备截止日期 2').fill('2027-10-01')
            button(page, '移除采购 1').click()
            icon_button(page, '添加采购').click()
            textfield(page, '采购名称 2').fill('合成新增雨具')
            textfield(page, '采购数量 2').fill('1 件')
            self.choose_owner(page, 'purchase', 2, '合成同行')
            textfield(page, '采购预算（元）2').fill('78.90')
            self.choose_members(page)
            lost_preview = self.exchange(page, PREVIEW, lambda: button(page, '核对并继续编辑').click(), drop='request')
            assert not lost_preview['sentToServer']
            expect(button(page, '核对并继续编辑')).to_be_enabled(timeout=15000)
            expect(page.get_by_role('alert')).to_be_visible()
            expect(textfield(page, '准备事项标题 2')).to_have_value('合成新增取件')
            expect(textfield(page, '采购预算（元）2')).to_have_value('78.90')
            expect(textfield(page, '出发日期')).to_have_value('2027-10-02')
            assert self.snapshot() == before
            plan = self.bridge(page)['plan']
            assert plan['start'] == '2027-10-02' and plan['end'] == '2027-10-07'
            assert [(r['title'], r['due']) for r in plan['checklist']] == [('合成核对护照', '2027-09-30'), ('合成新增取件', '2027-10-01')]
            assert [(r['title'], r['budget']) for r in plan['shopping']] == [('合成收纳袋', None), ('合成新增雨具', 7890)]
            assert plan['budget'] == 2000025 and self.snapshot() == before
            assert self.preview(page)['plan'] == plan
            lost = self.exchange(page, APPLY, lambda: button(page, '确认保存旅行').click(), status=201, drop='response')
            expect(button(page, '核对原保存')).to_be_enabled(timeout=15000)
            committed = self.database_proof('committed-before-lost-response-recovery')
            assert len(committed['journey_workflows']) == len(committed['journey_actions']) == 1
            self.no_external_queues(before, committed)
            replay = self.exchange(page, APPLY, lambda: button(page, '核对原保存').click())
            assert replay['payload'] == lost['payload']
            assert replay['result']['replayed'] is True and replay['result']['id'] == lost['result']['id']
            expect(page.get_by_role('heading', name='旅行详情', exact=True)).to_be_visible(timeout=15000)
            assert self.database_proof('recovered-without-duplicate') == committed
            assert self.get(ctx, '/api/journeys/' + replay['result']['id'])['plan'] == plan
            self.passed('Edited dates/offsets and delete/add lists reach the correct real preview; unsent preview transport failure keeps edits; committed apply response loss recovers identical token/key with one workflow/action')

    def held_model(self, page, prompt, while_held):
        textfield(page, '旅行原始需求').fill(prompt)
        held, url = [], self.base + BRIEF
        def hold(route):
            assert route.request.method == 'POST'
            response = route.fetch(max_redirects=0)
            assert response.status == 200 and 'set-cookie' not in response.headers
            held.append((route, response))
        page.route(url, hold, times=1)
        delivered = False
        try:
            button(page, '按当前文字重新整理').click()
            self.settle(page, lambda: bool(held))
            assert len(held) == 1 and held[0][1].json()['mode'] == 'model'
            self.record('held-model-%02d' % len(self.report['modelCalls']), held[0][1].json())
            while_held()
            held[0][0].fulfill(response=held[0][1])
            delivered = True
        finally:
            if held and not delivered:
                held[0][0].abort('failed')
            page.unroute(url, hold)

    def late_model_edit_and_identity(self, browser):
        with self.flow(browser) as (ctx, page):
            self.members(ctx)
            before = self.database_proof('before-late-model')
            self.start_items(page, self.register_example('合成初始内存简报'))
            edit_prompt = self.register_example('合成旧模型迟到名称')
            def edit():
                textfield(page, '旅行名称').fill('合成编辑后保留名称')
                textfield(page, '准备事项标题 1').fill('合成编辑后保留事项')
                textfield(page, '采购预算（元）1').fill('66.66')
            self.held_model(page, edit_prompt, edit)
            expect(button(page, '按当前文字重新整理')).to_be_enabled(timeout=15000)
            expect(textfield(page, '旅行名称')).to_have_value('合成编辑后保留名称')
            expect(textfield(page, '准备事项标题 1')).to_have_value('合成编辑后保留事项')
            expect(textfield(page, '采购预算（元）1')).to_have_value('66.66')
            assert self.snapshot() == before
            private = self.register_example('合成另一成员不可见的迟到简报')
            self.held_model(page, private, lambda: self.login(ctx, 2))
            assert self.get(ctx, '/api/me')['user']['id'] == 'member2'
            expect(page.get_by_test_id('journey-brief-form')).to_have_count(0, timeout=15000)
            for token in ('合成另一成员不可见的迟到简报', '合成编辑后保留事项', '合成编辑后保留名称', '合成转换插头'):
                expect(page.locator('body')).not_to_contain_text(token)
                assert not page.locator('input,textarea').evaluate_all('(nodes,t)=>nodes.some(n=>n.value.includes(t))', token)
                assert not page.evaluate('(t)=>[...Object.values(localStorage),...Object.values(sessionStorage),location.href].some(v=>v.includes(t))', token)
            assert self.database_proof('after-late-model-and-real-login') == before
            assert sum(c['scenario'] == self.out.name for c in self.report['modelCalls']) == 3
            self.passed('Authentic late model brief cannot overwrite edits or survive an actual member-cookie change; no automatic extra model call, storage leak or business write')

    @classmethod
    def run_scenarios(cls, root, bundle, report, out, browser):
        for name in CASES:
            case_out = out / name
            case_out.mkdir()
            folder = None
            before = len(report['checks'])
            case = {'name': name, 'passed': False}
            try:
                with ExitStack() as lifecycle:
                    folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='expo-trip-items-')))
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
    out = root / 'test-results' / ('expo-assistant-trip-items-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], unexpectedProviderAttempts=[],
        screenshots=[], scenarioResults=[], scenarioFailures=[], httpEvidence=[], databaseEvidence=[], modelCalls=[],
        requestedChecks=len(CASES), head=head, tree=tree, buildEvidenceSha256=sha(evidence_path),
        harnessSha256=sha(out / 'executed-harness.py'), buildSourceHead=build_head, buildSourceTree=evidence['sourceTree'],
        reusedBuild=build_head != head, buildSourceDelta=git('diff', '--name-only', build_head, head).splitlines(),
        sourceRoot=str(root), bundleRoot=str(bundle), sourceHashesBefore=hashes(), bundleHashesBefore=export_hashes(bundle),
        productionWrites=0, realModel=False, realCloud=False, physicalTelevision=False,
        scope='Four synthetic real Flask/SQLite/loopback HTTPS/Edge item flows; only raw model JSON is substituted. Ad hoc certificate is local only. No production or real model quality claim; screenshot coverage is stated per image.')
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
                assert len(report['checks']) == len(CASES) and len(report['screenshots']) == 4
                assert not any(report[key] for key in ('scenarioFailures', 'pageErrors', 'externalRequests', 'unexpectedProviderAttempts'))
                report['passed'] = True
            finally:
                browser.close()
    except Exception:
        report['failure'] = traceback.format_exc()
        print(report['failure'], flush=True)
    finally:
        report['sourceHashesAfter'], report['bundleHashesAfter'] = hashes(), export_hashes(bundle)
        report['sourceUnchanged'] = report['sourceHashesBefore'] == report['sourceHashesAfter']
        report['bundleUnchanged'] = report['bundleHashesBefore'] == report['bundleHashesAfter']
        report['fixtureHashesAfter'] = {name: sha(Path(path)) for name, path in report.get('fixtureActualPaths', {}).items()}
        report['fixturesUnchanged'] = bool(report.get('fixtureHashes')) and report['fixtureHashesAfter'] == report['fixtureHashes']
        report['sourceStillFrozen'] = git('rev-parse', 'HEAD') == head and git('rev-parse', 'HEAD^{tree}') == tree and not git('status', '--porcelain=v1')
        report['temporaryFixtureRemoved'] = len(report['scenarioResults']) == len(CASES) and all(c['temporaryFixtureRemoved'] for c in report['scenarioResults'])
        report['passed'] = report['passed'] and all(report[key] for key in ('sourceUnchanged', 'bundleUnchanged', 'fixturesUnchanged', 'sourceStillFrozen', 'temporaryFixtureRemoved'))
        with (out / 'result.json').open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'report': str(out / 'result.json')}, ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
