"""Offline input gates and real encrypted fixture checks; no browser acceptance."""
from contextlib import ExitStack, closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

import pytest
from scripts import check_expo_photo_duplicates_browser as wrapper
from browser_expo_photo_duplicates_check import Run, picture, BrowserHttpGuard, LEGACY_PREVIEW


@pytest.fixture
def build(tmp_path):
    def git(*args):
        return subprocess.check_output(['git', '-c', 'user.name=Synthetic Tool Check',
            '-c', 'user.email=synthetic@example.invalid', *args], cwd=tmp_path).decode().strip()
    git('init', '--quiet')
    paths = ['frontend/src/main.tsx', 'frontend/package-lock.json', 'frontend/README.md',
        'tests/test_expo_journey_brief.mjs', 'tests/test_expo_trips.mjs',
        'tests/test_expo_assistant_journey_entry.mjs', 'tests/test_app.py',
        'tests/test_journey_workflows.py', 'tests/test_expo_photos.mjs',
        'tests/test_expo_journey_documents.mjs', 'tests/test_expo_calendar.mjs', 'deploy/git_blobs.py']
    for name in paths:
        p = tmp_path / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('synthetic input ' + name)
    git('add', '--', *paths); git('commit', '--quiet', '-m', 'Synthetic source')
    head = git('rev-parse', 'HEAD')
    evidence = dict(sourceHead=head, sourceTree=git('rev-parse', head + '^{tree}'), buildExit=0,
        executions=[{'exitCode': 0}], dotenvDisabled=True, ambientExpoPublicVariables=[],
        inputFiles={n: wrapper.sha(tmp_path/n) for n in paths[:2]},
        supplementalTestInputs={n: wrapper.sha(tmp_path/n) for n in paths[3:]})
    return git, tmp_path, head, evidence, paths


def test_cases_deduplicate_and_preserve_failure_output(tmp_path):
    assert wrapper.selected_cases(None) == wrapper.CASES
    assert sum(wrapper.CASE_SCREENSHOTS.values()) == 10
    assert wrapper.selected_cases([wrapper.CASES[2], wrapper.CASES[0], wrapper.CASES[2]]) == (wrapper.CASES[2], wrapper.CASES[0])
    for invalid in ([], ['unknown']):
        with pytest.raises(ValueError): wrapper.selected_cases(invalid)
    with patch.object(wrapper, 'datetime') as clock:
        clock.now.return_value = datetime(2027, 10, 13, tzinfo=timezone.utc)
        out = wrapper.exclusive_output(tmp_path); (out/'failure.txt').write_text('retained')
        with pytest.raises(FileExistsError): wrapper.exclusive_output(tmp_path)
        assert (out/'failure.txt').read_text() == 'retained'


def test_exact_build_source_and_complete_inputs_accept(build):
    wrapper.validate_build(*build)


@pytest.mark.parametrize('change', ['head', 'tree', 'frontend_missing', 'supplement_missing',
    'input_changed', 'extra_path', 'failed_build', 'failed_phase', 'dotenv', 'public_env'])
def test_build_input_gate_rejects_changed_or_incomplete_evidence(build, change):
    git, root, head, evidence, names = build
    if change == 'head': evidence['sourceHead'] = '0'*40
    elif change == 'tree': evidence['sourceTree'] = '0'*40
    elif change == 'frontend_missing': evidence['inputFiles'].pop('frontend/src/main.tsx')
    elif change == 'supplement_missing': evidence['supplementalTestInputs'].pop('tests/test_app.py')
    elif change == 'input_changed': (root/'frontend/src/main.tsx').write_text('changed')
    elif change == 'extra_path': evidence['inputFiles']['../outside'] = '0'*64
    elif change == 'failed_build': evidence['buildExit'] = 1
    elif change == 'failed_phase': evidence['executions'][0]['exitCode'] = 1
    elif change == 'dotenv': evidence['dotenvDisabled'] = False
    elif change == 'public_env': evidence['ambientExpoPublicVariables'] = ['EXPO_PUBLIC_UNREVIEWED']
    with pytest.raises(AssertionError): wrapper.validate_build(git, root, head, evidence, names)


class FlaskRequests:
    """Real Flask responses adapted to the setup helper's HTTP client interface."""
    def __init__(self, client):
        self.client = client; self.request = self

    def fetch(self, url, method='GET', data=None, headers=None):
        path = urlsplit(url).path
        if urlsplit(url).query: path += '?' + urlsplit(url).query
        kwargs = {'headers': headers or {}}
        if isinstance(data, bytes): kwargs['data'] = data
        elif data is not None: kwargs['json'] = data
        response = self.client.open(path, method=method, **kwargs)
        return SimpleNamespace(status=response.status_code, json=lambda: response.json,
                               text=lambda: response.get_data(as_text=True), body=lambda: response.data)

    def get(self, url, **kwargs): return self.fetch(url, 'GET', **kwargs)
    def put(self, url, **kwargs): return self.fetch(url, 'PUT', **kwargs)


@pytest.fixture
def real_media(tmp_path, monkeypatch):
    import test_household_media as fixture
    import media_images
    app, engine, clock, ids = fixture.configured(tmp_path/'database', monkeypatch)
    client, _ = fixture.login(app)
    ctx = FlaskRequests(client)
    run = Run.__new__(Run)
    run.base = 'http://localhost'; run.folder = tmp_path; run.database = Path(engine.sessions.path)
    run.engine, run.synthetic_accounts, run.images, run.media_fixture = engine, ids, media_images, fixture
    run.out = tmp_path/'evidence'; run.out.mkdir()
    run.report = {'databaseEvidence': [], 'httpEvidence': []}
    return run, ctx


def test_real_google_and_raw_local_fixture_share_display_bytes_and_original_ids(real_media):
    run, ctx = real_media
    google, local = run.fixture(ctx, 21)
    assert len({x['id'] for x in google} | {local['id']}) == 22
    assert all(x['source'] == 'google-photos' and len(x['accountId']) == 32 for x in google)
    assert local['source'] == 'local-upload' and local['accountId'] is None
    with run.engine.transaction() as con:
        rows = con.execute('SELECT * FROM media_items').fetchall()
        assert len(rows) == 22
        assert all(row['state'] == 'ready' and row['confirmed_at'] and row['visibility'] == 'private' for row in rows)
        metadata = [run.engine._metadata(row) for row in rows]
        assert len({(m['sha256'], m['width'], m['height'], m['bytes']) for m in metadata}) == 1
        assert all(bytes(row['metadata_cipher']) != json.dumps(m).encode() for row, m in zip(rows, metadata))
        assert all(run.engine.cipher.open_bytes('media-preview', bytes(row['preview_cipher'])) != picture() for row in rows)
    proof = json.loads((run.out/'real-source-fixture.json').read_text(encoding='utf-8'))
    assert proof['sameDisplayBytes'] and len(set(proof['previewSha256'])) == 1


def test_different_real_pixels_and_legacy_cap_do_not_invent_matching_hash(real_media):
    run, ctx = real_media
    google, local = run.fixture(ctx, different=True)
    proof = json.loads((run.out/'real-source-fixture.json').read_text(encoding='utf-8'))
    assert not proof['sameDisplayBytes'] and len(set(proof['previewSha256'])) == 2
    run.legacy_cap(google[0])
    with run.engine.transaction() as con:
        rows = con.execute('SELECT * FROM media_items ORDER BY id LIMIT 1001').fetchall()
        assert len(rows) == 1001 and [r['id'] for r in rows] == [f'{n:024x}' for n in range(1001)]
        values = [run.engine._metadata(row) for row in rows]
        assert 'sha256' not in values[0]
        for row, meta in zip(rows[1:], values[1:]):
            raw = run.engine.cipher.open_bytes('media-preview', bytes(row['preview_cipher']))
            assert hashlib.sha256(raw).hexdigest() == meta['sha256'] and len(raw) == meta['bytes']
    with patch.object(sqlite3, 'connect', wraps=sqlite3.connect) as connect:
        assert run.snapshot() == run.snapshot()
        assert connect.call_count == 2


def test_real_fixture_listener_and_thread_cleanup_without_browser(tmp_path):
    bundle = tmp_path/'unused-export'; bundle.mkdir(); (bundle/'index.html').write_text('<title>Not browser acceptance</title>')
    out = tmp_path/'output'; out.mkdir(); report = {'unexpectedProviderAttempts': []}
    with ExitStack() as lifecycle:
        folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='pd-init-', dir=tmp_path)))
        run = Run(wrapper.ROOT, bundle, folder, report, out, lifecycle)
        assert run.server is not None and run.thread.is_alive()
        assert len(run.synthetic_accounts) == 2 and all(len(a) == 32 for a in run.synthetic_accounts.values())
        assert len(report['fixtureHashes']) >= 14 and not report['unexpectedProviderAttempts']
    assert run.server is None and not run.thread.is_alive() and not folder.exists()


class ResponseContext:
    """Offline event seam only; it is not an actual browser or HTTP server."""
    def on(self, event, callback):
        assert event == 'response'
        self.callback = callback

    def emit(self, status, path='/api/media/items/owner/duplicates', method='GET', origin='https://127.0.0.1:8443'):
        self.callback(SimpleNamespace(status=status, url=origin + path, request=SimpleNamespace(method=method)))


def http_guard(tmp_path, case='coverage_and_draft'):
    report = {}
    guard = BrowserHttpGuard('https://127.0.0.1:8443', case, tmp_path, report)
    context = ResponseContext(); guard.attach(context)
    return guard, context, report


@pytest.mark.parametrize('status,path,method,origin', [
    (500, LEGACY_PREVIEW, 'GET', 'https://127.0.0.1:8443'),
    (500, '/api/media/items/owner/duplicates', 'GET', 'https://127.0.0.1:8443'),
    (503, '/api/media/items/another/preview', 'GET', 'https://127.0.0.1:8443'),
    (503, LEGACY_PREVIEW, 'POST', 'https://127.0.0.1:8443'),
    (503, LEGACY_PREVIEW, 'GET', 'https://other.invalid'),
    (503, LEGACY_PREVIEW + '?other=1', 'GET', 'https://127.0.0.1:8443'),
])
def test_http_guard_rejects_unexpected_server_errors(tmp_path, status, path, method, origin):
    guard, context, report = http_guard(tmp_path)
    guard.permit_legacy_fixture()
    context.emit(status, path, method, origin)
    with pytest.raises(AssertionError): guard.assert_clean()
    entry = report['unexpectedHttpServerErrors'][0]
    assert (entry['method'], entry['path'], entry['status']) == (method, urlsplit(path).path, status)
    assert entry['expectedErrorReason'] is None
    assert json.loads(guard.path.read_text()) == entry  # flushed before any final assertion


def test_http_guard_exact_seeded_503_records_reason_and_all_context_pages(tmp_path):
    guard, first, report = http_guard(tmp_path)
    guard.permit_legacy_fixture()
    second = ResponseContext(); guard.attach(second)
    first.emit(200)
    second.emit(503, LEGACY_PREVIEW)
    second.emit(404, '/api/media/items/revoked')  # existing business assertions own expected 4xx
    guard.assert_clean()
    entries = [json.loads(line) for line in guard.path.read_text().splitlines()]
    assert [r['context'] for r in entries] == [1, 2, 2]
    assert entries[1]['expectedErrorReason'].startswith('Deliberately seeded legacy photo')
    assert len(report['browserHttpResponses']) == 3 and not report['unexpectedHttpServerErrors']


def test_http_guard_exception_requires_actual_fixture_opt_in(tmp_path):
    guard, context, report = http_guard(tmp_path)
    context.emit(503, LEGACY_PREVIEW)
    with pytest.raises(AssertionError): guard.assert_clean()
    other = tmp_path/'other'; other.mkdir()
    guard, _, _ = http_guard(other, 'cross_source_pages')
    with pytest.raises(AssertionError): guard.permit_legacy_fixture()


def test_http_guard_capture_error_and_missing_responses_fail_closed(tmp_path):
    guard, context, report = http_guard(tmp_path)
    with pytest.raises(AssertionError): guard.assert_clean()
    context.callback(SimpleNamespace(status=500))  # listener must latch malformed observations
    context.emit(200)
    assert report['httpCaptureErrors'] == [{'case': 'coverage_and_draft', 'error': 'AttributeError'}]
    with pytest.raises(AssertionError): guard.assert_clean()


def test_http_guard_case_failure_overrides_prior_business_pass(tmp_path):
    report = dict(checks=[], screenshots=[], scenarioFailures=[], scenarioResults=[])
    class ObservedRun(Run):
        def __init__(self, root, bundle, folder, report, out, lifecycle):
            self.report = report
            self.http_guard = BrowserHttpGuard('https://127.0.0.1:8443', out.name, out, report)
            self.server = None; self.thread = SimpleNamespace(is_alive=lambda: False)

        def coverage_and_draft(self, browser):
            context = ResponseContext(); self.http_guard.attach(context)
            context.emit(500, LEGACY_PREVIEW)
            self.report['checks'].append('business assertions passed')
            self.report['screenshots'].extend(['offline-placeholder'] * 3)

    ObservedRun.run_scenarios(tmp_path, tmp_path, report, tmp_path, None, tmp_path, ('coverage_and_draft',))
    assert not report['checks'] and len(report['scenarioFailures']) == 1
    case = report['scenarioResults'][0]
    assert case['passed'] is False and case['temporaryFixtureRemoved'] and case['listenerStopped']
    assert case['browserHttpEvidence']['responses'] == 1
    assert not case.get('httpGuardPassed')
