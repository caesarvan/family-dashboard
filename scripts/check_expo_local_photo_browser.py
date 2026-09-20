"""Run only a reviewed fixed source + fresh Expo export against synthetic local photo uploads."""
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
from browser_expo_local_photo_check import Run, CASES, CASE_SCREENSHOTS, HARNESS

WRAPPER = 'scripts/check_expo_local_photo_browser.py'
BUILD_REUSE_PATHS = frozenset({WRAPPER, HARNESS, 'tests/test_expo_local_photo_browser.py', 'docs/LOCAL-PHOTO-BROWSER.md'})
REVIEWED_BACKEND_HEAD = 'da7e78a9429750030f2b8fa0a1e2d85ba30967bc'
REVIEWED_BACKEND_PATHS = frozenset({'home_assistant.py', 'tests/test_media_search_revocation.py', 'docs/LOCAL-PHOTO-IMPORT.md'})


def selected_cases(values):
    if values is None: return CASES
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
    assert set(changed) <= BUILD_REUSE_PATHS | REVIEWED_BACKEND_PATHS, 'Only exact reviewed tool paths and backend fix may differ'
    if set(changed) & REVIEWED_BACKEND_PATHS:
        assert git('merge-base', REVIEWED_BACKEND_HEAD, head) == REVIEWED_BACKEND_HEAD, 'Reviewed backend must be an ancestor'
        for path in REVIEWED_BACKEND_PATHS:
            assert git('rev-parse', head + ':' + path) == git('rev-parse', REVIEWED_BACKEND_HEAD + ':' + path), 'Reviewed backend bytes changed: ' + path
    return changed


def exclusive_output(root):
    out = root / 'test-results' / ('expo-local-photo-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True, exist_ok=False)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--build-source-head')
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
    build_head = args.build_source_head or head
    build_delta = build_source_delta(git, head, evidence, build_head)
    names = subprocess.check_output(['git', '--no-replace-objects', 'ls-files', '-z'], cwd=root).decode('utf-8').rstrip('\0').split('\0')
    def hashes(): return {name: sha(root / name) for name in names}
    assert export_hashes(bundle) == evidence['files']
    assert all(sha(root / name) == digest for name, digest in evidence['inputFiles'].items())
    assert Path(__file__).resolve() == (root / WRAPPER).resolve()
    assert Path(sys.modules['browser_expo_local_photo_check'].__file__).resolve() == (root / HARNESS).resolve()
    out = exclusive_output(root)
    shutil.copyfile(root / HARNESS, out / 'executed-harness.py')
    shutil.copyfile(__file__, out / 'executed-wrapper.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], unexpectedProviderAttempts=[],
        screenshots=[], scenarioResults=[], scenarioFailures=[], httpEvidence=[], databaseEvidence=[],
        requestedChecks=len(cases), requestedCases=list(cases), expectedScreenshots=expected_screenshots,
        head=head, tree=tree, buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(root / HARNESS),
        wrapperSha256=sha(root / WRAPPER), buildSourceHead=build_head, buildSourceTree=evidence['sourceTree'],
        buildSourceDelta=build_delta, buildReusePolicy='four-tool-paths plus exact da7e78a backend blobs; identical-complete-frontend-and-build-inputs',
        reviewedBackendHead=REVIEWED_BACKEND_HEAD, reviewedBackendPaths=sorted(REVIEWED_BACKEND_PATHS),
        sourceRoot=str(root), bundleRoot=str(bundle), sourceHashesBefore=hashes(), bundleHashesBefore=export_hashes(bundle),
        productionWrites=0, realCloud=False, realModel=False, physicalTelevision=False,
        scope='Actual local Flask/SQLite/HTTPS/Edge. Synthetic JPEG/PNG/WebP files are chosen through the actual browser input, processed by real raw HTTP/Pillow/SQLite and confirmed under original IDs. Fault routes only lose real committed responses or change identity using actual login; peer/family/TV setup and shared ACL changes use actual APIs. No business DTO stubs, production, cloud, model, physical-TV display or native-app acceptance; only requestedCases ran.')
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
