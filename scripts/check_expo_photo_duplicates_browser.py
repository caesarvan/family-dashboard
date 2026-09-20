"""Run exact frozen source and its fresh Expo export against actual local duplicate-photo flows."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import traceback
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from playwright.sync_api import sync_playwright
from browser_expo_finance_check import sha
from browser_expo_assistant_trip_items_check import export_hashes
from browser_expo_photo_duplicates_check import Run, CASES, CASE_SCREENSHOTS, HARNESS

WRAPPER = 'scripts/check_expo_photo_duplicates_browser.py'


def selected_cases(values):
    if values is None: return CASES
    if not values or any(value not in CASES for value in values):
        raise ValueError('Select at least one known browser case')
    return tuple(dict.fromkeys(values))


def validate_build(git, root, head, evidence, names):
    # A fresh build of this exact combined source is required. No reuse exceptions.
    assert evidence['sourceHead'] == head, 'Exact build source required'
    assert evidence['sourceTree'] == git('rev-parse', head + '^{tree}'), 'Exact build tree required'
    assert evidence['buildExit'] == 0 and evidence['executions']
    assert all(item['exitCode'] == 0 for item in evidence['executions'])
    assert evidence['dotenvDisabled'] is True and not evidence['ambientExpoPublicVariables']
    inputs = evidence['inputFiles']
    expected = {name for name in names if name.startswith('frontend/')} - {
        'frontend/.gitignore', 'frontend/LICENSE', 'frontend/README.md'}
    assert set(inputs) == expected, 'Complete frontend build inputs required'
    supplements = evidence['supplementalTestInputs']
    assert set(supplements) == {
        'tests/test_expo_journey_brief.mjs', 'tests/test_expo_trips.mjs',
        'tests/test_expo_assistant_journey_entry.mjs', 'tests/test_app.py',
        'tests/test_journey_workflows.py', 'tests/test_expo_photos.mjs',
        'tests/test_expo_journey_documents.mjs', 'tests/test_expo_calendar.mjs', 'deploy/git_blobs.py'}
    for mapping in (inputs, supplements):
        for name, digest in mapping.items():
            assert name in names and re.fullmatch('[a-f0-9]{64}', digest)
            assert sha(root / name) == digest, 'Changed build input: ' + name


def exclusive_output(root):
    out = root / 'test-results' / ('expo-photo-duplicates-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True, exist_ok=False)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--expected-build-evidence', required=True)
    parser.add_argument('--temp-root', required=True, type=Path)
    parser.add_argument('--case', action='append', choices=CASES, dest='cases')
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
    names = subprocess.check_output(['git', '--no-replace-objects', 'ls-files', '-z'], cwd=root).decode('utf-8').rstrip('\0').split('\0')
    def hashes(): return {name: sha(root / name) for name in names}
    assert export_hashes(bundle) == evidence['files']
    validate_build(git, root, head, evidence, names)
    assert Path(__file__).resolve() == (root / WRAPPER).resolve()
    assert Path(sys.modules['browser_expo_photo_duplicates_check'].__file__).resolve() == (root / HARNESS).resolve()
    out = exclusive_output(root)
    shutil.copyfile(root / HARNESS, out / 'executed-harness.py')
    shutil.copyfile(__file__, out / 'executed-wrapper.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], unexpectedProviderAttempts=[],
        screenshots=[], scenarioResults=[], scenarioFailures=[], httpEvidence=[], databaseEvidence=[],
        requestedChecks=len(cases), requestedCases=list(cases), expectedScreenshots=expected_screenshots,
        head=head, tree=tree, buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(root / HARNESS),
        wrapperSha256=sha(root / WRAPPER), buildSourceHead=head, buildSourceTree=evidence['sourceTree'],
        buildReusePolicy='none; exact HEAD/tree and complete frontend plus nine supplemental build inputs',
        sourceRoot=str(root), bundleRoot=str(bundle), sourceHashesBefore=hashes(), bundleHashesBefore=export_hashes(bundle),
        productionWrites=0, realCloud=False, realModel=False, physicalTelevision=False,
        scope='Actual temporary Flask/SQLite/HTTPS/Edge with synthetic Google account/job metadata and real same-byte JPEG processing/encrypted persistence across Google and local sources. Actual duplicate GET, original ID/revision detail, explicit pagination, draft cancellation, partial legacy scope and source/member/household/TV denial. No provider/model calls, production, original-image or perceptual matching, physical TV or real-cloud acceptance. Only requested cases run.')
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
            report['fixtureHashesAfter'] = {name: sha(root / name) for name in report.get('fixtureHashes', {})}
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
