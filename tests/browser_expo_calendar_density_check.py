"""Focused calendar/list density acceptance: frozen Expo + real local Flask/SQLite/Edge.

Synthetic records only; no successful business-response mocks, real cloud or TV.
The read-only task is a synthetic imported projection, not a cloud-sync claim.
"""
import argparse
from contextlib import ExitStack, closing
from datetime import datetime, timedelta, timezone
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
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright
import browser_expo_finance_check as fixture
from browser_expo_finance_check import Run as BaseRun, button, sha


WIDTHS = (320, 390, 1280, 1920)
PREFERENCES = '/api/preferences'
NAMES = ('合成成员甲的长中文显示名称用于换行检查', '合成成员乙的长中文显示名称用于换行检查')
TITLES = {
    'event': '一起核对周末行程并带上雨衣和水壶再到约定地点碰面',
    'task': '出发前一起检查行李中的雨衣水壶证件和备用充电线',
    'shopping': '采购适合两个人一起使用的雨衣水壶和旅行备用用品',
    'readonly': '合成外部来源的只读待办',
}
LOCATION = '合成城市春日路家庭活动中心一层靠近花园的长桌请从东侧入口进入'


class Run(BaseRun):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        assert Path(self.source.__file__).resolve() == (self.root / 'app.py').resolve()
        self.report['fixtureHashes'] = {}
        for path, name in ((Path(fixture.__file__), 'tests/browser_expo_finance_check.py'),
                           (Path(__file__), 'tests/browser_expo_calendar_density_check.py')):
            assert sha(path) == sha(self.root / name)
            self.report['fixtureHashes'][name] = sha(path)

    def clear_finance(self):
        pass  # Inherit only isolated server, real authentication and lifecycle.

    def preferences(self, ctx, **changes):
        current = self.get(ctx, PREFERENCES)
        return self.write(ctx, 'PUT', PREFERENCES, {'revision': current['revision'], 'changes': changes})

    def seed_records(self, browser, ctx):
        self.write(ctx, 'POST', '/api/profile', {'name': NAMES[0]})
        partner = self.context(browser, member=2)
        try:
            self.write(partner, 'POST', '/api/profile', {'name': NAMES[1]})
        finally:
            partner.close()
        self.preferences(ctx, theme='forest', colorMode='light', density='comfortable', homeView='today')
        today = datetime.now(timezone(timedelta(hours=8))).date()
        self.ids = {}
        for key, kind, value in (
            ('event', 'events', dict(title=TITLES['event'], location=LOCATION, allDay=True,
                start=today.isoformat() + 'T00:00:00+08:00',
                end=(today + timedelta(days=1)).isoformat() + 'T00:00:00+08:00')),
            ('event_short', 'events', dict(title='合成短日程', location='合成地点', allDay=True,
                start=today.isoformat() + 'T00:00:00+08:00',
                end=(today + timedelta(days=1)).isoformat() + 'T00:00:00+08:00')),
            ('task', 'tasks', dict(title=TITLES['task'], due=today.isoformat())),
            ('task_short', 'tasks', dict(title='合成短待办', due=today.isoformat())),
            ('readonly', 'tasks', dict(title=TITLES['readonly'], due=today.isoformat())),
            ('shopping', 'shopping', dict(title=TITLES['shopping'], quantity='1 件', budget=1250)),
            ('shopping_short', 'shopping', dict(title='合成短采购', quantity='1 件', budget=0)),
        ):
            result = self.write(ctx, 'POST', '/api/items/' + kind, {'owner': 'shared', **value}, status=201)
            self.ids[key] = result['id']
        # This is fixture setup inside a new temporary database, never a mocked
        # HTTP response or a claim that a real provider imported these records.
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database)) as con:
            data = json.loads(con.execute('SELECT data FROM entities WHERE id=?', (self.ids['readonly'],)).fetchone()[0])
            data['sync'] = {'provider': 'microsoft', 'readOnly': True, 'sourceId': 'synthetic-readonly'}
            con.execute('UPDATE entities SET data=? WHERE id=?', (json.dumps(data), self.ids['readonly']))
            con.commit()

    def open(self, page, route):
        page.goto(self.base + '/app/' + route)
        if route == 'home':
            expect(button(page, '安排首页')).to_be_enabled(timeout=15000)
        else:
            title = {'calendar': '日程', 'tasks': '共同待办', 'shopping': '采购清单'}[route]
            expect(page.get_by_role('heading', name=title, exact=True)).to_be_visible(timeout=15000)
        key = {'home': 'event', 'calendar': 'event', 'tasks': 'task', 'shopping': 'shopping'}[route]
        prefix = 'calendar-event-' if key == 'event' else route + '-item-'
        expect(page.get_by_test_id(prefix + self.ids[key])).to_be_visible(timeout=15000)
        page.evaluate('() => document.fonts.ready')

    def viewport(self, page, width):
        page.set_viewport_size({'width': width, 'height': 1080 if width >= 1280 else 844})
        page.wait_for_timeout(400)  # Settle Paper/responsive transitions, not network assertions.

    def target(self, locator, label, minimum=44):
        expect(locator).to_have_count(1)
        locator.scroll_into_view_if_needed()
        expect(locator).to_be_visible()
        box = locator.bounding_box()
        assert box and box['width'] >= minimum and box['height'] >= minimum, (label, box, minimum)
        self.report['controlSamples'].append({'label': label, 'minimum': minimum, **box})

    def text_bounds(self, locator, label):
        expect(locator).to_have_count(1)
        locator.scroll_into_view_if_needed()
        result = locator.evaluate('''node => {
          const rect=node.getBoundingClientRect(), style=getComputedStyle(node);
          return {text:node.textContent,left:rect.left,right:rect.right,viewport:innerWidth,
            clientWidth:node.clientWidth,scrollWidth:node.scrollWidth,
            clientHeight:node.clientHeight,scrollHeight:node.scrollHeight,
            lineClamp:style.webkitLineClamp,fontSize:style.fontSize,lineHeight:style.lineHeight};
        }''')
        assert result['left'] >= -2 and result['right'] <= result['viewport'] + 2, (label, result)
        assert result['scrollWidth'] <= result['clientWidth'] + 2, (label, result)
        assert result['scrollHeight'] <= result['clientHeight'] + 2, (label, result)
        assert result['lineClamp'] in ('none', '', '0'), (label, result)
        self.report['textSamples'].append({'label': label, **result})

    def shot(self, page, name, width):
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2'), (name, width)
        file = self.out / f'{name}-{width}.png'
        page.screenshot(path=str(file), full_page=False)
        self.report['screenshots'].append({'path': file.name, 'sha256': sha(file), 'width': width,
            'scope': 'Current visible viewport; internal ScrollView contents are not all captured.'})

    def range_controls(self, page, label):
        group = page.get_by_test_id('calendar-range-controls')
        for name in ('今日', '本周', '前后 3 天'):
            self.target(button(group, name), label + '/' + name)
        for name in NAMES:
            control = group.get_by_role('radio', name=name, exact=True)
            self.target(control, label + '/' + name, minimum=48)
            self.text_bounds(control.get_by_text(name, exact=True), label + '/member-text')

    def calendar_widths(self, page):
        for route in ('home', 'calendar'):
            self.open(page, route)
            for width in WIDTHS:
                self.viewport(page, width)
                self.range_controls(page, f'{route}-{width}')
                if route == 'calendar':
                    for name in ('前一段时间', '后一段时间', '回到今天'):
                        self.target(button(page, name), f'{route}-{width}/{name}')
                self.target(button(page, '编辑安排：' + TITLES['event']), f'{route}-{width}/edit-event')
                row = page.get_by_test_id('calendar-event-' + self.ids['event'])
                self.text_bounds(row.get_by_text(TITLES['event'], exact=True), f'{route}-{width}/title')
                self.text_bounds(row.get_by_text(re.compile(re.escape(LOCATION))), f'{route}-{width}/location')
                self.shot(page, route + '-long-content', width)
        self.passed('Home and calendar: actual range/nav/event targets >=44, member radio >=48, long Chinese names/title/location untruncated at 320/390/1280/1920')

    def list_widths(self, page):
        for kind, key in (('tasks', 'task'), ('shopping', 'shopping')):
            self.open(page, kind)
            for width in WIDTHS:
                self.viewport(page, width)
                row = page.get_by_test_id(kind + '-item-' + self.ids[key])
                self.target(row.get_by_role('checkbox', name='完成' + TITLES[key], exact=True), f'{kind}-{width}/complete')
                self.target(button(row, '编辑' + TITLES[key]), f'{kind}-{width}/edit')
                for label in (('待完成', '已完成', '全部') if kind == 'tasks' else ('待采购', '已买到', '全部')):
                    self.target(button(page, label), f'{kind}-{width}/filter-{label}')
                self.text_bounds(row.get_by_text(TITLES[key], exact=True), f'{kind}-{width}/title')
                self.shot(page, kind + '-long-content', width)
        self.passed('Task and shopping rows: real checkbox/edit/filter hit boxes >=44 and full long titles without horizontal overflow at all four widths')

    def density_sample(self, page, route, key, title):
        self.open(page, route)
        prefix = 'calendar-event-' if route == 'calendar' else route + '-item-'
        row = page.get_by_test_id(prefix + self.ids[key])
        row.scroll_into_view_if_needed()
        result = row.evaluate('''node => {const s=getComputedStyle(node);return {
          height:node.getBoundingClientRect().height,paddingTop:s.paddingTop,paddingBottom:s.paddingBottom};}''')
        result.update(row.get_by_text(title, exact=True).evaluate('''node => {
          const s=getComputedStyle(node);return {fontSize:s.fontSize,lineHeight:s.lineHeight};}'''))
        return result

    def contrast(self, locator, label):
        result = locator.evaluate('''node => {
          const rgb=s=>(s.match(/[\\d.]+/g)||[]).map(Number),foreground=getComputedStyle(node).color;
          let current=node,background='';while(current){const c=getComputedStyle(current).backgroundColor;
            if(rgb(c).length===3||rgb(c)[3]===1){background=c;break;}current=current.parentElement;}
          const lum=c=>rgb(c).slice(0,3).map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4)
            .reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
          return {foreground,background,ratio:(Math.max(lum(foreground),lum(background))+.05)/(Math.min(lum(foreground),lum(background))+.05)};
        }''')
        assert result['background'] and result['ratio'] >= 4.5, (label, result)
        self.report['styleSamples'].append({'label': label, **result})

    def density(self, page):
        self.viewport(page, 390)  # Both measurements at exactly the same viewport.
        records = (('calendar', 'event_short', '合成短日程'), ('tasks', 'task_short', '合成短待办'),
                   ('shopping', 'shopping_short', '合成短采购'))
        samples = {}
        for mode in ('comfortable', 'compact'):
            self.preferences(page.context, density=mode, colorMode='light')
            samples[mode] = {route: self.density_sample(page, route, key, title) for route, key, title in records}
        for route, _, _ in records:
            normal, compact = samples['comfortable'][route], samples['compact'][route]
            assert normal['fontSize'] == compact['fontSize'] and normal['lineHeight'] == compact['lineHeight'], samples
            assert compact['height'] < normal['height'], samples
            assert float(compact['paddingTop'][:-2]) < float(normal['paddingTop'][:-2]), samples
        self.report['densitySamples'] = samples
        self.preferences(page.context, colorMode='dark')
        for route, key in (('calendar', 'event'), ('tasks', 'task')):
            self.open(page, route)
            page.wait_for_function("getComputedStyle(document.body).backgroundColor === 'rgb(17, 17, 19)'")
            self.contrast(page.get_by_text(TITLES[key], exact=True), route + '/dark-title')
            if route == 'calendar':
                self.contrast(page.get_by_text(re.compile(re.escape(LOCATION))), route + '/dark-location')
            else:
                self.contrast(page.get_by_text('来源只读', exact=True), route + '/dark-readonly')
            self.shot(page, route + '-dark-compact', 390)
        self.passed('Fixed 390px viewport: compact reduces real calendar/task/shopping row heights without shrinking fonts; dark calendar title/location and task/read-only text sampled at >=4.5 contrast')

    def keyboard_and_range(self, page):
        self.preferences(page.context, density='comfortable', colorMode='light', homeView='today')
        self.open(page, 'calendar')
        first, second = (page.get_by_role('radio', name=name, exact=True) for name in NAMES)
        first.focus(); page.keyboard.press('Space'); expect(first).to_be_checked()
        page.keyboard.press('ArrowRight'); expect(second).to_be_focused(); expect(second).to_be_checked()
        page.keyboard.press('ArrowLeft'); expect(first).to_be_focused(); expect(first).to_be_checked()
        before = self.count_requests('PUT', PREFERENCES)
        with page.expect_response(lambda r: urlsplit(r.url).path == PREFERENCES and r.request.method == 'PUT') as response:
            button(page, '本周').click()
        assert response.value.status == 200
        expect(button(page, '本周')).to_be_enabled()
        assert self.count_requests('PUT', PREFERENCES) == before + 1
        assert self.get(page.context, PREFERENCES)['homeView'] == 'week'
        page.reload(); expect(button(page, '本周')).to_have_attribute('aria-checked', 'true')
        row = page.get_by_test_id('calendar-event-' + self.ids['event'])
        expect(row).to_be_visible()
        button(page, '后一段时间').click(); expect(row).to_have_count(0)
        button(page, '前一段时间').click(); expect(row).to_be_visible()
        button(page, '前一段时间').click(); expect(row).to_have_count(0)
        button(page, '回到今天').click(); expect(row).to_be_visible()
        self.passed('Member radio Space/arrows update actual focus/checked state; one range PUT persists across reload; previous/next/return-to-today keep real event visibility correct')

    def completion(self, page):
        for kind, key in (('tasks', 'task_short'), ('shopping', 'shopping_short')):
            self.open(page, kind)
            before_record = next(x for x in self.get(page.context, '/api/state')[kind] if x['id'] == self.ids[key])
            path = '/api/items/' + kind + '/' + self.ids[key]
            before = self.count_requests('PATCH', path)
            control = page.get_by_test_id(kind + '-item-' + self.ids[key]).get_by_role('checkbox')
            control.focus()
            with page.expect_response(lambda r: urlsplit(r.url).path == path and r.request.method == 'PATCH') as response:
                page.keyboard.press('Space')
            assert response.value.status == 200
            expect(page.get_by_test_id(kind + '-item-' + self.ids[key])).to_have_count(0)
            current = next(x for x in self.get(page.context, '/api/state')[kind] if x['id'] == self.ids[key])
            assert current['done'] is True and current['revision'] == before_record['revision'] + 1
            assert self.count_requests('PATCH', path) == before + 1
            self.report['writeSamples'].append({'kind': kind, 'spacePatchCount': 1, 'revisionDelta': 1})
        self.open(page, 'tasks')
        row = page.get_by_test_id('tasks-item-' + self.ids['readonly'])
        control = row.get_by_role('checkbox', name='完成' + TITLES['readonly'], exact=True)
        expect(control).to_be_disabled(); expect(button(row, '编辑' + TITLES['readonly'])).to_have_count(0)
        before = self.get(page.context, '/api/state')['tasks']
        path = '/api/items/tasks/' + self.ids['readonly']
        writes = self.count_requests('PATCH', path)
        # Start from a known enabled local control and traverse a bounded page.
        button(page, '编辑' + TITLES['task']).focus()
        for _ in range(8):
            page.keyboard.press('Tab'); expect(control).not_to_be_focused()
        assert self.count_requests('PATCH', path) == writes == 0
        assert self.get(page.context, '/api/state')['tasks'] == before
        self.passed('Actual local task/shopping Space each commits one PATCH and one revision; imported read-only task has disabled checkbox, no edit action, keyboard Tab skips it and writes zero times')

    def run_scenarios(self, browser):
        with self.flow(browser) as (ctx, page):
            self.seed_records(browser, ctx)
            self.calendar_widths(page)
            self.list_widths(page)
            self.density(page)
            self.keyboard_and_range(page)
            self.completion(page)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--expected-build-evidence', required=True)
    args = parser.parse_args()
    root, bundle = args.source_root.resolve(), args.bundle.resolve()
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    assert head == args.expected_head
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
    out = Path(__file__).resolve().parents[1] / 'test-results' / ('expo-calendar-density-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], screenshots=[], styleSamples=[], controlSamples=[], textSamples=[], writeSamples=[],
        head=head, tree=evidence['sourceTree'], buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(out / 'executed-harness.py'),
        sourceHashesBefore=hashes(), bundleHashesBefore=bundle_hashes(), productionWrites=0, realCloud=False, realAI=False,
        physicalTelevision=False, scope='Real isolated Flask/SQLite/Edge, synthetic member profiles and events/lists. Only the read-only imported task projection is seeded directly in the temporary DB. No business-response mocks or HTML injection. Measured hit boxes and visible viewport screenshots, not a full accessibility/physical-device/cloud acceptance.')
    original_connect = socket.socket.connect
    def local_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
            report['externalRequests'].append({'kind': 'non-loopback socket'})
            raise AssertionError('External network forbidden')
        return original_connect(sock, address)
    folder = None
    try:
        with patch.object(socket.socket, 'connect', local_connect), sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            try:
                with ExitStack() as lifecycle:
                    folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='expo-calendar-density-')))
                    run = Run(root, bundle, folder, report, out, lifecycle)
                    run.run_scenarios(browser)
                    assert len(report['checks']) == 5 and len(report['screenshots']) == 18
                    assert not report['pageErrors'] and not report['externalRequests']
                    report['passed'] = True
            finally:
                browser.close()
    except Exception:
        report['passed'] = False
        report['failure'] = traceback.format_exc()
        print(report['failure'], flush=True)
    finally:
        report['sourceHashesAfter'] = hashes(); report['bundleHashesAfter'] = bundle_hashes()
        report['sourceUnchanged'] = report['sourceHashesBefore'] == report['sourceHashesAfter']
        report['bundleUnchanged'] = report['bundleHashesBefore'] == report['bundleHashesAfter']
        report['temporaryFixtureRemoved'] = folder is not None and not folder.exists()
        report['passed'] = report['passed'] and report['sourceUnchanged'] and report['bundleUnchanged'] and report['temporaryFixtureRemoved']
        (out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'report': str(out / 'result.json')}, ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    raise SystemExit(main())
