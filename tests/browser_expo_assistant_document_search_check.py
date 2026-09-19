"""Frozen Expo document/photo search on synthetic Flask/SQLite/HTTPS/Edge.

Search and detail replies are genuine. Only a completed HTTP response may be
held to test late delivery. Photo provider jobs use synthetic fixture inputs;
no browser-facing business DTO, authorization result or success is fabricated.
"""
import argparse
from contextlib import ExitStack, closing, contextmanager
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
from urllib.parse import parse_qs, urlencode

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import ThreadedWSGIServer
import browser_expo_finance_check as fixture
import browser_expo_trip_recap_check as media_fixture
import browser_expo_journey_documents_check as document_fixture
from browser_expo_finance_check import button, sha
from browser_expo_trip_recap_check import Run as MediaRun
from browser_expo_assistant_trip_items_check import export_hashes

HARNESS = 'tests/browser_expo_assistant_document_search_check.py'
CASES = ('content_pagination', 'orphan_document', 'revoked_deleted', 'identity_late')
WIDTHS = (390, 1280)
PATH = '/api/journey-documents'
PROMPT = '告诉助理你的需求'
BUILD_REUSE_PATHS = frozenset({HARNESS, 'tests/test_assistant_document_search_browser.py',
                             'docs/EXPO-ASSISTANT-DOCUMENT-SEARCH-BROWSER.md'})


def build_source_delta(git, head, evidence, build_head):
    """Reuse only an explicit ancestor changed in these harness-only paths."""
    assert re.fullmatch('[a-f0-9]{40}', build_head)
    assert evidence['sourceHead'] == build_head
    assert evidence['sourceTree'] == git('rev-parse', build_head + '^{tree}')
    assert git('merge-base', build_head, head) == build_head, 'Build source must be an ancestor'
    changed = git('diff', '--name-only', build_head, head).splitlines()
    assert set(changed) <= BUILD_REUSE_PATHS, 'Build reuse permits only the reviewed harness, its tests and documentation'
    return changed


class Run(MediaRun):
    journey = document_fixture.Run.journey
    seed_document = document_fixture.Run.seed_document
    metadata = staticmethod(document_fixture.Run.metadata)

    def __init__(self, root, bundle, folder, report, out, lifecycle):
        assert ThreadedWSGIServer.block_on_close is True
        lifecycle.enter_context(patch.object(ThreadedWSGIServer, 'daemon_threads', False))
        super().__init__(root, bundle, folder, report, out, lifecycle)
        assert not self.server.daemon_threads
        self.exchange_number = 0
        paths = {HARNESS: Path(__file__), 'tests/browser_expo_finance_check.py': Path(fixture.__file__),
                 'tests/browser_expo_trip_recap_check.py': Path(media_fixture.__file__),
                 'tests/browser_expo_journey_documents_check.py': Path(document_fixture.__file__)}
        paths.update({name + '.py': Path(sys.modules[name].__file__)
                      for name in ('app', 'home_assistant', 'journey_documents', 'household_media', 'media_images')})
        paths['tests/browser_expo_assistant_trip_items_check.py'] = Path(sys.modules['browser_expo_assistant_trip_items_check'].__file__)
        for name, actual in paths.items():
            assert actual.resolve() == (root / name).resolve()
            digest = sha(actual)
            assert digest == sha(root / name)
            assert report.setdefault('fixtureHashes', {}).setdefault(name, digest) == digest
        assert report['fixtureHashes'][HARNESS] == report['harnessSha256']
        actual_paths = {name: str((root / name).resolve()) for name in report['fixtureHashes']}
        assert report.setdefault('fixtureActualPaths', actual_paths) == actual_paths
        for name in ('_model_json', 'model_plan', 'model_journey_brief'):
            lifecycle.enter_context(patch.object(sys.modules['home_assistant'], name, self.forbidden_model))

    def start(self, port=0):
        self.cfg['ASSISTANT_PROVIDER'] = 'local'
        super().start(port)

    def forbidden_model(self, *_args, **_kwargs):
        self.report['unexpectedProviderAttempts'].append(self.out.name)
        raise AssertionError('Search must remain local; real model calls are forbidden')

    def record(self, name, value, group='httpEvidence'):
        path = self.out / (name + '.json')
        with path.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        self.report[group].append({'path': path.relative_to(self.out.parent).as_posix(), 'sha256': sha(path)})
        return value

    def snapshot(self):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        tables = ('entities', 'journey_documents', 'journey_workflows', 'journey_links',
                  'journey_actions', 'assistant_plans', 'media_items', 'media_imports', 'media_tv_grants')
        with closing(sqlite3.connect(self.database)) as con:
            assert not con.execute('PRAGMA foreign_key_check').fetchall()
            return {name: hashlib.sha256(repr(sorted(con.execute('SELECT * FROM "' + name + '"').fetchall(), key=repr)).encode()).hexdigest()
                    for name in tables}

    def unchanged(self, before, mark):
        assert self.snapshot() == before, 'Searching/opening must not modify original content or sharing'
        calls = self.requests[mark:]
        assert all(r['method'] == 'GET' or (r['method'] == 'POST' and r['path'] == '/api/assistant/plan') for r in calls), calls
        assert not any(r['path'].startswith(PATH + '/') and r['path'].endswith('/file') for r in calls), 'No automatic document download'
        assert not any('/tv-grants' in r['path'] and r['method'] != 'GET' for r in calls)

    @staticmethod
    def input(page):
        return page.get_by_role('textbox', name=PROMPT, exact=True)

    def open_assistant(self, page):
        page.goto(self.base + '/app/assistant')
        expect(page.get_by_role('heading', name='家庭助理', exact=True)).to_be_visible(timeout=15000)
        expect(self.input(page)).to_be_enabled(timeout=15000)

    def search(self, page, query):
        prompt = '搜索：' + query
        self.input(page).fill(prompt)
        with page.expect_response(lambda r: r.url == self.base + '/api/assistant/plan' and r.request.method == 'POST') as pending:
            button(page, '整理并预览').click()
        response = pending.value
        assert response.status == 200, response.text()
        result = response.json()
        assert response.request.post_data_json == dict(prompt=prompt, useModel=False, includeHouseholdContext=False)
        assert result['mode'] == 'local' and result['id'] is None and result['actions'] == []
        assert result['search']['query'] == query
        self.exchange_number += 1
        self.record('search-%02d' % self.exchange_number, {'payload': response.request.post_data_json, 'response': result})
        expect(self.input(page)).to_be_enabled()
        expect(page.get_by_text('第 1 页', exact=True)).to_be_visible()
        return {**result['search'], 'matches': result['matches']}

    def result_button(self, page, kind, uid):
        return page.get_by_test_id('assistant-search-' + kind + '-' + uid).get_by_role('button')

    def return_search(self, page, query, offset, kind):
        before = len(self.requests)
        if kind == 'documents':
            button(page, '返回资料搜索').click()
        else:
            # The gallery header also has a disabled return while the dialog is open.
            dialog = page.get_by_test_id('photo-editor')
            target = dialog.get_by_role('button', name='返回搜索', exact=True) if dialog.count() and dialog.is_visible() else button(page, '返回搜索')
            target.click()
        expect(self.input(page)).to_have_value('搜索：' + query, timeout=15000)
        expect(page.get_by_text('第 ' + str(offset // 20 + 1) + ' 页', exact=True)).to_be_visible(timeout=15000)
        calls = self.requests[before:]
        assert any(r['path'] == '/api/assistant/search' and parse_qs(r['query']) ==
                   dict(q=[query], limit=['20'], offset=[str(offset)]) for r in calls), calls
        assert any(r['path'] == '/api/me' for r in calls)

    def open_document(self, page, record, journey=None, shared=False):
        mark = len(self.requests)
        self.result_button(page, 'documents', record['id']).click()
        detail = page.get_by_test_id('journey-document-detail')
        expect(detail).to_be_visible(timeout=15000)
        expect(detail).to_contain_text(record['title'])
        expect(button(page, '下载资料')).to_be_enabled()
        expect(button(page, '编辑资料')).to_have_count(0 if shared else 1)
        expected = {'journeyId': [journey['id']]} if journey else {}
        assert any(r['path'] == PATH and parse_qs(r['query']) == expected for r in self.requests[mark:])
        self.record('opened-document-' + record['id'], {'id': record['id'], 'journeyId': journey['id'] if journey else None, 'reads': self.requests[mark:]})
        return detail

    def open_photo(self, page, photo):
        reads = self.count_requests('GET', '/api/media/items/' + photo['id'])
        self.result_button(page, 'media', photo['id']).click()
        detail = page.get_by_test_id('photo-editor')
        expect(detail).to_be_visible(timeout=15000)
        expect(detail.get_by_role('textbox', name='照片说明', exact=True)).to_have_value(photo['caption'])
        expect(detail.get_by_text('已读取当前版本，保留你的未保存修改；请比较后再保存。', exact=True)).to_have_count(0)
        expect(detail.get_by_text('照片已更新。你的草稿仍保留，请读取当前版本后核对。', exact=True)).to_have_count(0)
        assert self.count_requests('GET', '/api/media/items/' + photo['id']) > reads
        self.record('opened-photo-' + photo['id'], {'id': photo['id'], 'readsAfter': self.count_requests('GET', '/api/media/items/' + photo['id'])})
        return detail

    def capture(self, page, label, target):
        for width in WIDTHS:
            page.set_viewport_size({'width': width, 'height': 844 if width == 390 else 1000})
            expect(target).to_be_visible()
            target.scroll_into_view_if_needed()
            page.evaluate('() => document.fonts.ready')
            page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
            metrics = page.evaluate('''() => ({viewport:innerWidth,bodyScroll:document.body.scrollWidth,
              bodyClient:document.body.clientWidth,rootScroll:document.documentElement.scrollWidth,
              clipped:[...document.querySelectorAll('input,textarea,button,[role="button"],[role="radio"]')]
              .filter(n=>{const r=n.getBoundingClientRect();return r.width>0&&r.height>0&&r.bottom>0&&r.top<innerHeight&&getComputedStyle(n).visibility!=='hidden'&&(r.left< -2||r.right>innerWidth+2)})
              .map(n=>({label:n.getAttribute('aria-label')||n.textContent,box:n.getBoundingClientRect().toJSON()}))})''')
            assert metrics['bodyScroll'] <= width + 2 and metrics['rootScroll'] <= width + 2 and not metrics['clipped'], metrics
            path = self.out / f'{label}-{width}.png'
            page.screenshot(path=str(path), full_page=True)
            self.report['screenshots'].append({'path': path.relative_to(self.out.parent).as_posix(), 'sha256': sha(path), 'metrics': metrics})
        page.set_viewport_size({'width': 390, 'height': 844})

    def content_pagination(self, browser):
        with self.flow(browser) as (ctx, page):
            journey = self.journey(ctx, '合成原旅行')
            query = '合成内容分页'
            documents = [self.seed_document(ctx, journey, query + ' 凭证 %02d' % n)[0] for n in range(21)]
            photo = self.photos(ctx, journey, caption=query + ' 原照片')[0]
            before, mark = self.snapshot(), len(self.requests)
            self.open_assistant(page)
            assert self.search(page, query)['total'] == 22
            button(page, '下一页').click()
            expect(page.get_by_text('第 2 页', exact=True)).to_be_visible()
            second = self.get(ctx, '/api/assistant/search?' + urlencode(dict(q=query, limit=20, offset=20)))
            self.record('actual-second-page', second)
            assert len(second['matches']) == 2 and {m['kind'] for m in second['matches']} == {'documents', 'media'}
            match = next(m for m in second['matches'] if m['kind'] == 'documents')
            original = next(d for d in documents if d['id'] == match['id'])
            self.capture(page, 'second-page', self.result_button(page, 'documents', original['id']))
            detail = self.open_document(page, original, journey)
            self.capture(page, 'original-document', detail)
            self.return_search(page, query, 20, 'documents')
            detail = self.open_photo(page, photo)
            self.capture(page, 'original-photo', detail.get_by_role('textbox', name='照片说明', exact=True))
            self.return_search(page, query, 20, 'media')
            self.unchanged(before, mark)
            self.record('readonly-content', before, 'databaseEvidence')
            self.passed('Page two document/photo results open their original authorized IDs and return the same prompt/query/page; no content, sharing or download write')

    def orphan_document(self, browser):
        with self.flow(browser) as (ctx, page):
            journey = self.journey(ctx, '合成可解除旅行')
            record = self.seed_document(ctx, journey, '合成本人未关联凭证')[0]
            self.open_assistant(page)
            result = self.search(page, record['title'])
            assert result['total'] == 1 and result['matches'][0]['journey']['id'] == journey['id']
            trip = next(row for row in self.get(ctx, '/api/state')['trips'] if row['id'] == journey['tripId'])
            self.write(ctx, 'DELETE', '/api/items/trips/' + trip['id'], {'revision': trip['revision']})
            before, mark = self.snapshot(), len(self.requests)
            self.result_button(page, 'documents', record['id']).click()
            expect(page.get_by_role('alert')).to_contain_text('这份资料已移出原搜索范围。请返回搜索重新查询。')
            expect(page.get_by_test_id('journey-document-detail')).to_have_count(0)
            assert not any(r['path'] == PATH and not r['query'] for r in self.requests[mark:]), 'Targeted search must not fall back into the personal library'
            self.return_search(page, record['title'], 0, 'documents')
            result = self.get(ctx, '/api/assistant/search?' + urlencode(dict(q=record['title'], limit=20, offset=0)))
            assert result['total'] == 1 and result['matches'][0]['id'] == record['id']
            assert result['matches'][0]['journey'] is None and result['matches'][0]['visibility'] == 'private'
            detail = self.open_document(page, record)
            expect(page.get_by_role('heading', name='我的旅行资料', exact=True)).to_be_visible()
            self.capture(page, 'own-unlinked-document', detail)
            self.return_search(page, record['title'], 0, 'documents')
            self.unchanged(before, mark)
            self.record('readonly-orphan', before, 'databaseEvidence')
            self.passed('Deleted original journey rejects the stale scoped entry; fresh search finds the same private orphan ID and explicitly opens the personal library')

    def revoked_deleted(self, browser):
        with self.flow(browser) as (ctx, page), ExitStack() as stack:
            journey = self.journey(ctx, '合成共享旅行')
            document = self.seed_document(ctx, journey, '合成共享后撤销凭证', 'shared')[0]
            photo = self.photos(ctx, journey, shared=True, caption='合成共享后删除照片')[0]
            owner = self.context(browser, 1)
            stack.callback(owner.close)
            self.login(ctx, 2)
            self.open_assistant(page)
            assert self.search(page, document['title'])['total'] == 1
            self.open_document(page, document, journey, shared=True)
            self.return_search(page, document['title'], 0, 'documents')
            self.write(owner, 'PATCH', PATH + '/' + document['id'], self.metadata(document, visibility='private'))
            before, mark = self.snapshot(), len(self.requests)
            self.result_button(page, 'documents', document['id']).click()
            expect(page.get_by_role('alert')).to_contain_text('这份资料已移除、移出当前范围，或不再对你可见。')
            expect(page.get_by_test_id('journey-document-detail')).to_have_count(0)
            expect(button(page, '下载资料')).to_have_count(0)
            self.return_search(page, document['title'], 0, 'documents')
            expect(self.result_button(page, 'documents', document['id'])).to_have_count(0)
            self.unchanged(before, mark)
            assert self.search(page, photo['caption'])['total'] == 1
            self.write(owner, 'DELETE', '/api/media/items/' + photo['id'], {'revision': photo['revision']})
            before, mark = self.snapshot(), len(self.requests)
            self.result_button(page, 'media', photo['id']).click()
            expect(page.get_by_role('alert')).to_contain_text('照片已移除或不再可见。')
            expect(page.get_by_test_id('photo-editor')).not_to_be_visible()
            self.return_search(page, photo['caption'], 0, 'media')
            expect(self.result_button(page, 'media', photo['id'])).to_have_count(0)
            self.unchanged(before, mark)
            self.record('revoked-deleted-final', before, 'databaseEvidence')
            self.passed('Partner can read shared original document; real owner revocation and photo deletion after search reject stale detail and fresh searches remove both targets')

    @contextmanager
    def held_response(self, page, url):
        held = []
        def hold(route):
            response = route.fetch(max_redirects=0)
            assert response.status == 200 and 'set-cookie' not in response.headers
            raw = response.body()
            self.exchange_number += 1
            self.record('held-%02d' % self.exchange_number, {'url': url, 'status': response.status,
                        'response': json.loads(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
            held.append((route, response.status, response.headers, raw))
        page.route(url, hold)
        try:
            yield held
        finally:
            page.unroute(url, hold)
            for route, *_ in held:
                route.abort('failed')

    def identity_late(self, browser):
        with self.flow(browser) as (ctx, page):
            journey = self.journey(ctx, '合成身份隔离旅行')
            document = self.seed_document(ctx, journey, '合成旧成员私人凭证')[0]
            photo = self.photos(ctx, journey, caption='合成旧成员私人照片')[0]
            for kind, item, url in (
                ('documents', document, self.base + PATH + '?journeyId=' + journey['id']),
                ('media', photo, self.base + '/api/media/items/' + photo['id']),
            ):
                self.login(ctx, 1)
                self.open_assistant(page)
                query = item['title'] if kind == 'documents' else item['caption']
                assert self.search(page, query)['total'] == 1
                before = self.snapshot()
                old = self.get(ctx, '/api/me')['user']
                with self.held_response(page, url) as held:
                    self.result_button(page, kind, item['id']).click()
                    self.settle(page, lambda: len(held) == 1)
                    self.login(ctx, 2)
                    assert self.get(ctx, '/api/me')['user']['id'] != old['id']
                    reads = self.count_requests('GET', '/api/me')
                    route, status, headers, raw = held.pop()
                    route.fulfill(status=status, headers=headers, body=raw)
                    self.settle(page, lambda: self.count_requests('GET', '/api/me') > reads)
                    # Wait for the identity-driven remount, not absence while a request is pending.
                    expect(self.input(page)).to_be_enabled(timeout=15000)
                    expect(page.get_by_test_id('journey-document-detail')).to_have_count(0)
                    expect(page.get_by_test_id('photo-editor')).not_to_be_visible()
                    expect(self.result_button(page, kind, item['id'])).to_have_count(0)
                    assert self.search(page, query)['total'] == 0
                assert self.snapshot() == before
            self.record('identity-final', self.snapshot(), 'databaseEvidence')
            self.passed('Real member-cookie replacement discards delayed document list and photo detail; fresh second-member search cannot reveal private first-member content')

    @classmethod
    def run_scenarios(cls, root, bundle, report, out, browser, cases=CASES):
        for name in cases:
            case_out = out / name
            case_out.mkdir()
            folder, before, case = None, len(report['checks']), {'name': name, 'passed': False}
            try:
                with ExitStack() as lifecycle:
                    folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='expo-assistant-doc-search-')))
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
    parser.add_argument('--scenario', choices=('content_pagination',), help='Run only the initial photo-entry regression; default runs all four cases')
    args = parser.parse_args()
    cases = (args.scenario,) if args.scenario else CASES
    expected_screenshots = 6 if args.scenario else 8
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
    build_delta = build_source_delta(git, head, evidence, build_head)
    names = subprocess.check_output(['git', '--no-replace-objects', 'ls-files', '-z'], cwd=root).decode('utf-8').rstrip('\0').split('\0')
    def hashes():
        return {name: sha(root / name) for name in names}
    assert export_hashes(bundle) == evidence['files']
    assert all(sha(root / name) == value for name, value in evidence['inputFiles'].items())
    assert Path(__file__).resolve() == (root / HARNESS).resolve()
    out = root / 'test-results' / ('expo-assistant-document-search-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], unexpectedProviderAttempts=[],
                  screenshots=[], scenarioResults=[], scenarioFailures=[], httpEvidence=[], databaseEvidence=[],
                  requestedChecks=len(cases), selectedScenarios=list(cases), head=head, tree=tree, buildEvidenceSha256=sha(evidence_path),
                  harnessSha256=sha(out / 'executed-harness.py'), buildSourceHead=build_head, buildSourceTree=evidence['sourceTree'],
                  buildSourceDelta=build_delta, buildReusePaths=sorted(BUILD_REUSE_PATHS),
                  sourceRoot=str(root), bundleRoot=str(bundle), sourceHashesBefore=hashes(), bundleHashesBefore=export_hashes(bundle),
                  productionWrites=0, realModel=False, realCloud=False, physicalTelevision=False,
                  scope=f'{len(cases)} isolated local Flask/SQLite/HTTPS/Edge flow(s); synthetic document uploads and media job inputs, original business HTTP. No real cloud, model or production acceptance.')
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
                Run.run_scenarios(root, bundle, report, out, browser, cases)
                assert len(report['checks']) == len(cases) and len(report['screenshots']) == expected_screenshots
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
            report['temporaryFixtureRemoved'] = len(report['scenarioResults']) == len(cases) and all(c['temporaryFixtureRemoved'] for c in report['scenarioResults'])
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
