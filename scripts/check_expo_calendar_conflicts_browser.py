"""Three isolated calendar-conflict flows on real Flask/SQLite/HTTPS/Edge.

Only a starting imported event projection is synthetic SQL. Calendar edits,
preferences, stale versions and identity checks use actual application HTTP.
"""
import argparse
from contextlib import ExitStack, closing
from datetime import datetime, timedelta, timezone
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

HARNESS = 'scripts/check_expo_calendar_conflicts_browser.py'
BUILD_REUSE_PATHS = frozenset({HARNESS, 'tests/test_expo_calendar_conflicts_browser.py', 'docs/EXPO-CALENDAR-CONFLICTS-BROWSER.md'})
CASES = ('home_edit_resolve', 'ranges_focus_readonly', 'draft_identity')
CASE_SCREENSHOTS = dict(zip(CASES, (2, 3, 3)))
NOW = datetime(2027, 10, 13, 4, tzinfo=timezone.utc)  # Wednesday, Beijing noon.
DAY = '2027-10-13'
ITEMS = '/api/items/events'

LAYOUT_SCRIPT = '''() => {
  const clipped=[], scrollableClipped=[];
  function reachableByHorizontalScroll(node, rect) {
    for (let parent=node;parent&&parent!==document.body;parent=parent.parentElement) {
      const style=getComputedStyle(parent);
      if(style.position==='fixed'||style.position==='sticky') return false;
      if(parent===node) continue;
      const box=parent.getBoundingClientRect(), left=box.left+parent.clientLeft;
      const right=left+parent.clientWidth;
      if((style.overflowX==='hidden'||style.overflowX==='clip')&&(rect.left<left-2||rect.right>right+2)) return false;
      if((style.overflowX==='auto'||style.overflowX==='scroll')&&parent.scrollWidth>parent.clientWidth+2) {
        const contentLeft=rect.left-left+parent.scrollLeft,contentRight=rect.right-left+parent.scrollLeft;
        return parent.clientWidth>0&&left>=-2&&right<=innerWidth+2&&rect.width<=parent.clientWidth+2
          &&contentLeft>=-2&&contentRight<=parent.scrollWidth+2;
      }
    }
    return false;
  }
  for(const node of document.querySelectorAll('input,textarea,button,[role="button"],[role="checkbox"]')) {
    const rect=node.getBoundingClientRect();
    if(rect.width>0&&rect.height>0&&rect.bottom>0&&rect.top<innerHeight&&getComputedStyle(node).visibility!=='hidden'
        &&(rect.left< -2||rect.right>innerWidth+2)) {
      const item={label:node.getAttribute('aria-label')||node.textContent,box:rect.toJSON()};
      (reachableByHorizontalScroll(node,rect)?scrollableClipped:clipped).push(item);
    }
  }
  return {viewport:innerWidth,bodyScroll:document.body.scrollWidth,rootScroll:document.documentElement.scrollWidth,clipped,scrollableClipped};
}'''


def layout_metrics(page):
    return page.evaluate(LAYOUT_SCRIPT)


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
    out = root / 'test-results' / ('expo-calendar-conflicts-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True, exist_ok=False)
    return out


def range_button(page, label):
    assert label in ('今日', '本周', '前后 3 天')
    return page.get_by_test_id('calendar-range-controls').get_by_role('button', name=re.compile('^' + re.escape(label) + '(?:，已选择)?$'))


class Run(BaseRun):
    record = previous.Run.record
    proof = previous.Run.proof
    exchange = previous.Run.exchange

    def __init__(self, root, bundle, folder, report, out, lifecycle):
        self.exchange_number = 0
        assert ThreadedWSGIServer.block_on_close is True
        lifecycle.enter_context(patch.object(ThreadedWSGIServer, 'daemon_threads', False))
        super().__init__(root, bundle, folder, report, out, lifecycle)
        paths = {HARNESS: Path(__file__), 'scripts/check_expo_task_dependencies_browser.py': Path(previous.__file__),
                 'tests/browser_expo_finance_check.py': Path(fixture.__file__),
                 'tests/browser_expo_assistant_trip_items_check.py': Path(sys.modules['browser_expo_assistant_trip_items_check'].__file__)}
        paths.update({name + '.py': Path(sys.modules[name].__file__) for name in
                      ('app', 'cloud_accounts', 'cloud_providers', 'home_assistant', 'member_sessions', 'membership_storage')})
        for name, actual in paths.items():
            assert actual.resolve() == (root / name).resolve()
            assert report.setdefault('fixtureHashes', {}).setdefault(name, sha(actual)) == sha(actual)
        actual_paths = {name: str(path.resolve()) for name, path in paths.items()}
        assert report.setdefault('fixtureActualPaths', actual_paths) == actual_paths
        assert report['fixtureHashes'][HARNESS] == report['harnessSha256']
        for name in ('_model_json', 'model_plan', 'model_journey_brief'):
            lifecycle.enter_context(patch.object(sys.modules['home_assistant'], name, self.forbidden_provider))
        lifecycle.enter_context(patch.object(self.application.extensions['cloud_accounts'], 'active_provider', self.forbidden_provider))

    def start(self, port=0):
        self.cfg['ASSISTANT_PROVIDER'] = 'local'
        super().start(port)

    def forbidden_provider(self, *_args, **_kwargs):
        self.report['unexpectedProviderAttempts'].append(self.out.name)
        raise AssertionError('Real cloud/model calls forbidden')

    def clear_finance(self):
        pass

    def snapshot(self):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database)) as con:
            assert not con.execute('PRAGMA foreign_key_check').fetchall()
            return {table: sorted(con.execute('SELECT * FROM "' + table + '"').fetchall(), key=repr)
                    for table in ('entities', 'settings', 'audit')}

    def capture(self, page, label, focus, *, full_text=None):
        expect(focus).to_be_visible()
        focus.scroll_into_view_if_needed()
        page.evaluate('() => document.fonts.ready')
        page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
        metrics = layout_metrics(page)
        assert metrics['viewport'] in (390, 1280)
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

    def events(self, ctx):
        return self.get(ctx, '/api/state')['events']

    def event(self, ctx, uid):
        return next(row for row in self.events(ctx) if row['id'] == uid)

    def seed(self, ctx, title, start='09:00', end='11:00', owner='member1', date=DAY, end_date=None):
        result = self.write(ctx, 'POST', ITEMS, dict(title=title, owner=owner, start=date + 'T' + start + ':00+08:00',
            end=(end_date or date) + 'T' + end + ':00+08:00', allDay=False, location='合成地点：家庭活动室'), 201)
        return self.event(ctx, result['id'])

    def preferences(self, ctx, **changes):
        current = self.get(ctx, '/api/preferences')
        return self.write(ctx, 'PUT', '/api/preferences', {'revision': current['revision'], 'changes': changes})

    def open(self, page, route='calendar'):
        page.clock.set_fixed_time(NOW)
        page.goto(self.base + '/app/' + route)
        expect(button(page, '安排首页') if not route else page.get_by_role('heading', name='日程', exact=True)).to_be_visible(timeout=15000)

    def conflicts(self, page, count):
        panel = page.get_by_test_id('calendar-conflicts')
        if count:
            expect(panel.get_by_role('heading', name=f'时间重叠 · {count} 组', exact=True)).to_be_visible()
        else:
            expect(panel).to_have_count(0)
        return panel

    def expand(self, page, index=1):
        group = page.get_by_test_id(f'calendar-conflict-{index}')
        group.get_by_role('button', name=re.compile(f'^展开第 {index} 组')).click()
        expect(group.get_by_role('button', name=re.compile(f'^收起第 {index} 组'))).to_be_visible()
        return group

    def edit(self, page, event):
        button(page.get_by_test_id('calendar-conflicts'), '调整安排：' + event['title']).click()
        expect(page.get_by_role('textbox', name='名称', exact=True)).to_have_value(event['title'])

    def home_edit_resolve(self, browser):
        with self.flow(browser) as (ctx, page):
            title = '合成出发准备：核对护照航班行李与全家集合时间并确认交通安排'
            first = self.seed(ctx, title); self.seed(ctx, '合成共同早餐', '10:00', '12:00', 'shared')
            self.preferences(ctx, homeView='week')
            ids = sorted(row['id'] for row in self.events(ctx)); self.proof('before-edit')
            self.open(page, '')
            entry = page.get_by_role('button', name='查看当前范围的 1 组时间重叠', exact=True)
            expect(entry).to_be_visible()
            page.get_by_role('button', name=re.compile('^2027-10-14，')).click()
            expect(entry).to_be_visible()  # Home's chosen day must not narrow the pair count.
            entry.click(); group = self.expand(page)
            self.capture(page, 'home-open-original-390', group, full_text=group.get_by_text(title, exact=True))
            self.edit(page, first)
            page.get_by_role('textbox', name='开始时间（HH:mm）', exact=True).fill('13:00')
            page.get_by_role('textbox', name='结束时间（HH:mm）', exact=True).fill('14:00')
            path = ITEMS + '/' + first['id']; before = self.count_requests('PATCH', path)
            exchange = self.exchange(page, path, lambda: button(page, '保存').click())
            assert exchange['payload']['revision'] == first['revision']
            expect(page.get_by_role('textbox', name='名称', exact=True)).to_have_count(0)
            self.conflicts(page, 0); expect(range_button(page, '本周')).to_have_accessible_name('本周，已选择')
            current = self.event(ctx, first['id'])
            assert current['revision'] == first['revision'] + 1 and current['start'].startswith(DAY + 'T13:00')
            assert sorted(row['id'] for row in self.events(ctx)) == ids
            assert self.count_requests('PATCH', path) == before + 1
            page.reload(); self.conflicts(page, 0)
            expect(page.get_by_test_id('calendar-event-' + first['id'])).to_be_visible()
            self.capture(page, 'resolved-original-390', page.get_by_test_id('calendar-event-' + first['id']))
            self.proof('after-original-edit')
            self.record('original-identity', {'ids': ids, 'before': first, 'after': current, 'patches': 1})
            self.passed('Home current-week pair opens originals; real PATCH changes same ID/revision once and refresh removes overlap without copies')

    def ranges_focus_readonly(self, browser):
        with self.flow(browser) as (ctx, page):
            page.set_viewport_size({'width': 1280, 'height': 900})
            local = [self.seed(ctx, '合成密集安排' + str(i)) for i in range(4)]
            cloud = local[0]; long_title = '合成同步长标题：' + '完整展示出行资料🧭和当天安排，' * 18
            with closing(sqlite3.connect(self.database)) as con, con:
                data = json.loads(con.execute('SELECT data FROM entities WHERE id=?', (cloud['id'],)).fetchone()[0])
                data.update(title=long_title, sync={'provider': 'microsoft', 'sourceId': 'synthetic-readonly', 'readOnly': True})
                con.execute('UPDATE entities SET data=? WHERE id=?', (json.dumps(data), cloud['id']))
            self.seed(ctx, '合成跨日一', '23:00', '01:00', date='2027-10-12', end_date=DAY)
            self.seed(ctx, '合成跨日二', '23:30', '00:30', date='2027-10-12', end_date=DAY)
            self.seed(ctx, '合成伴侣一', '12:00', '13:00', 'member2')
            self.seed(ctx, '合成伴侣二', '12:30', '14:00', 'member2')
            self.preferences(ctx, homeView='week', density='compact')
            baseline = self.snapshot(); self.open(page)
            panel = self.conflicts(page, 7)
            expect(panel.get_by_test_id(re.compile('^calendar-conflict-[0-9]+$'))).to_have_count(3)
            crossing = self.expand(page)
            expect(crossing.get_by_text('2027-10-12 · 23:30–24:00 · 30 分钟', exact=True)).to_be_visible()
            expect(crossing.get_by_text('2027-10-13 · 00:00–00:30 · 30 分钟', exact=True)).to_be_visible()
            self.capture(page, 'cross-day-week-1280', crossing)
            for _ in range(2):
                panel.get_by_role('button', name=re.compile(r'再显示 [0-9]+ 组')).click()
            expect(panel.get_by_test_id(re.compile('^calendar-conflict-[0-9]+$'))).to_have_count(7)
            cloud_group = panel.get_by_test_id(re.compile('^calendar-conflict-[0-9]+$')).filter(has_text=long_title).first
            cloud_group.get_by_role('button', name=re.compile('^展开第 ')).click()
            expect(cloud_group.get_by_text('同步日程 · 只读，请在原应用调整。', exact=True)).to_be_visible()
            expect(button(cloud_group, '调整安排：' + long_title)).to_have_count(0)
            self.capture(page, 'long-readonly-compact-1280', cloud_group, full_text=cloud_group.get_by_text(long_title, exact=True))
            range_button(page, '前后 3 天').click()
            expect(range_button(page, '前后 3 天')).to_have_accessible_name('前后 3 天，已选择')
            panel = self.conflicts(page, 7)
            expect(panel.get_by_test_id(re.compile('^calendar-conflict-[0-9]+$'))).to_have_count(3)
            expect(panel.get_by_role('button', name=re.compile('^收起第 '))).to_have_count(0)
            person = next(p for p in self.get(ctx, '/api/state')['people'] if p['id'] == 'member2')
            page.get_by_role('radio', name=person['name'], exact=True).click()
            self.conflicts(page, 1); group = self.expand(page)
            expect(group.get_by_text('合成伴侣一', exact=True)).to_be_visible()
            expect(group.get_by_text(long_title, exact=True)).to_have_count(0)
            self.capture(page, 'partner-around-1280', group)
            assert self.snapshot()['entities'] == baseline['entities'], 'Read-only/range/focus must not mutate any event'
            assert self.count_requests('PATCH', ITEMS + '/' + cloud['id']) == 0
            self.proof('range-readonly-final')
            self.passed('Week/around member focus, one cross-day pair, compact 3-group pagination and full readonly imported title use actual unchanged events')

    def draft_identity(self, browser):
        with self.flow(browser) as (ctx, page):
            original = self.seed(ctx, '合成原安排'); self.seed(ctx, '合成重叠安排')
            self.preferences(ctx, homeView='around'); self.open(page); self.expand(page); self.edit(page, original)
            draft = '合成未保存草稿不得传给新成员'
            field = page.get_by_role('textbox', name='名称', exact=True); field.fill(draft)
            path = ITEMS + '/' + original['id']
            def competing_update():
                self.write(ctx, 'PATCH', path, {**original, 'location': '另一客户端已更新地点'})
            exchange = self.exchange(page, path, lambda: button(page, '保存').click(), status=409, before_fetch=competing_update)
            assert exchange['payload']['revision'] == original['revision']
            expect(page.get_by_text('这条记录已更新。你的输入仍在，请关闭后重新打开最新记录。', exact=True)).to_be_visible()
            expect(field).to_have_value(draft)
            self.capture(page, 'real-conflict-draft-390', field)
            current = self.event(ctx, original['id']); assert current['title'] == original['title'] and current['revision'] == original['revision'] + 1
            button(page, '取消').click(); expect(range_button(page, '前后 3 天')).to_have_accessible_name('前后 3 天，已选择')
            # A completed 409 refresh must retain the selected range and use the fresh revision.
            self.edit(page, current); field.fill(draft); before_offline = self.snapshot()
            ctx.set_offline(True)
            try:
                button(page, '保存').click()
                expect(page.get_by_text(previous.UNKNOWN, exact=True)).to_be_visible()
                expect(field).to_have_value(draft); expect(button(page, '保存')).to_be_disabled()
                self.capture(page, 'offline-draft-390', field)
                assert self.snapshot() == before_offline
            finally:
                ctx.set_offline(False)
            button(page, '关闭并核对').click()
            button(page, '刷新家庭数据').click()
            expect(button(page, '刷新家庭数据')).to_be_enabled()
            expect(range_button(page, '前后 3 天')).to_have_accessible_name('前后 3 天，已选择')
            if page.get_by_role('button', name=re.compile('^展开第 1 组')).count():
                self.expand(page)
            self.edit(page, current); field.fill(draft)
            identity_writes = (self.count_requests('PATCH', path), self.count_requests('POST', ITEMS))
            held = []
            def hold(route):
                response = route.fetch(max_redirects=0)
                assert response.status == 200 and 'set-cookie' not in response.headers
                held.append((route, response.status, response.headers, response.body()))
            url = self.base + '/api/state'; page.route(url, hold, times=1)
            try:
                page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
                self.settle(page, lambda: len(held) == 1)
                self.login(ctx, 2)
                actor = self.get(ctx, '/api/me')['user']; assert actor['id'] == 'member2'
                route, status, headers, raw = held.pop()
                self.record('held-old-state', {'status': status, 'response': json.loads(raw)})
                with page.expect_response(lambda response: response.url == self.base + '/api/me' and response.request.method == 'GET') as identity_tail:
                    route.fulfill(status=status, headers=headers, body=raw)
                identity = identity_tail.value
                assert identity.status == 200 and identity.finished() is None
                assert identity.json()['user']['id'] == 'member2'
                expect(field).to_have_count(0, timeout=15000)
                expect(page.get_by_text(draft, exact=True)).to_have_count(0)
                expect(page.get_by_test_id('calendar-conflicts')).to_have_count(0)
            finally:
                page.unroute(url, hold)
                for route, *_ in held:
                    route.abort('failed')
            with page.expect_response(lambda response: response.url == self.base + '/api/state') as reread:
                button(page, '刷新家庭数据').click()
            fresh = reread.value
            assert fresh.status == 200 and fresh.finished() is None
            expect(button(page, '刷新家庭数据')).to_be_enabled()
            page.get_by_role('radio', name='伴侣', exact=True).click()
            self.conflicts(page, 0)
            expect(page.get_by_role('radio', name='伴侣', exact=True)).to_be_checked()
            self.capture(page, 'member-isolation-390', page.get_by_role('heading', name='日程', exact=True))
            assert self.event(ctx, original['id']) == current
            assert (self.count_requests('PATCH', path), self.count_requests('POST', ITEMS)) == identity_writes
            self.proof('failed-writes-and-identity-final')
            self.record('identity-discard', {'receivedOldStateStatus': 200, 'identityAfterOldState': {'status': identity.status, 'bodyFinished': True, 'memberId': 'member2'},
                'freshState': fresh.json(), 'freshStateBodyFinished': True, 'newMemberId': actor['id'], 'draftNotShown': True,
                'noAdditionalPatchOrPost': True, 'original': current})
            self.passed('Real stale PATCH keeps draft/range, offline save preserves locked draft without DB write, delayed old state is discarded on member switch')

    @classmethod
    def run_scenarios(cls, root, bundle, report, out, browser, temp_root, cases=CASES):
        for name in cases:
            case_out = out / name; case_out.mkdir()
            folder, before, case = None, len(report['checks']), {'name': name, 'passed': False}
            screenshots_before = len(report['screenshots'])
            try:
                with ExitStack() as lifecycle:
                    folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='cc-', dir=temp_root)))
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
                  buildSourceDelta=build_delta, buildReusePolicy='only-calendar-harness-tests-docs; identical-complete-frontend-and-input-hashes',
                  sourceRoot=str(root), bundleRoot=str(bundle), sourceHashesBefore=hashes(), bundleHashesBefore=export_hashes(bundle),
                  productionWrites=0, realModel=False, realCloud=False, physicalTelevision=False,
                  scope='Only requestedCases ran as real local Flask/SQLite/HTTPS/Edge calendar-conflict flows. Actual preferences and original event PATCH/version conflicts; a synthetic initial readonly event and fixed browser display date. No fake successful business DTO, cloud/model/production or physical-TV acceptance.')
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
