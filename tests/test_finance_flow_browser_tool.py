"""Narrow tool checks only: closed build inputs, evidence outputs, real fixture lifecycle."""
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

import pytest
import browser_finance_flow_mapping_check as tool


def test_selection_and_exclusive_evidence_directory(tmp_path):
    assert tool.selected_cases(None) == tool.CASES
    assert tool.selected_cases([tool.CASES[2], tool.CASES[0], tool.CASES[2]]) == (tool.CASES[2], tool.CASES[0])
    for bad in ([], ['unknown']):
        with pytest.raises(ValueError): tool.selected_cases(bad)
    with patch.object(tool, 'datetime') as clock:
        clock.now.return_value = datetime(2027, 1, 2, tzinfo=timezone.utc)
        out = tool.exclusive_output(tmp_path)
        tool.write_json(out / 'result.json', {'passed': False})
        with pytest.raises(FileExistsError): tool.exclusive_output(tmp_path)
        with pytest.raises(FileExistsError): tool.write_json(out / 'result.json', {'passed': True})
        assert json.loads((out / 'result.json').read_text()) == {'passed': False}


def test_build_gate_binds_exact_git_and_complete_inputs(tmp_path):
    def git(*args):
        return subprocess.check_output(['git', '-c', 'user.name=Synthetic Check',
            '-c', 'user.email=synthetic@example.invalid', *args], cwd=tmp_path).decode().strip()
    git('init', '--quiet')
    names = ['frontend/src/main.tsx', 'frontend/package-lock.json', 'frontend/README.md', *sorted(tool.SUPPLEMENTS)]
    for name in names:
        path = tmp_path / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('synthetic ' + name, encoding='utf-8')
    git('add', '--', *names); git('commit', '--quiet', '-m', 'Synthetic build input')
    head = git('rev-parse', 'HEAD')
    evidence = dict(sourceHead=head, sourceTree=git('rev-parse', 'HEAD^{tree}'), buildExit=0,
        executions=[{'exitCode': 0}], dotenvDisabled=True, ambientExpoPublicVariables=[],
        inputFiles={n: tool.sha(tmp_path / n) for n in names[:2]},
        supplementalTestInputs={n: tool.sha(tmp_path / n) for n in names[3:]})
    tool.validate_build(git, tmp_path, head, evidence, names)
    for change in ('head', 'tree', 'missing_front', 'missing_extra', 'failed', 'public_env', 'dotenv', 'path', 'phase'):
        changed = deepcopy(evidence)
        if change == 'head': changed['sourceHead'] = '0' * 40
        if change == 'tree': changed['sourceTree'] = '0' * 40
        if change == 'missing_front': changed['inputFiles'].pop(names[0])
        if change == 'missing_extra': changed['supplementalTestInputs'].pop(names[3])
        if change == 'failed': changed['buildExit'] = 1
        if change == 'phase': changed['executions'][0]['exitCode'] = 1
        if change == 'public_env': changed['ambientExpoPublicVariables'] = ['EXPO_PUBLIC_UNREVIEWED']
        if change == 'dotenv': changed['dotenvDisabled'] = False
        if change == 'path': changed['inputFiles']['../outside'] = '0' * 64
        with pytest.raises(AssertionError): tool.validate_build(git, tmp_path, head, changed, names)
    (tmp_path / names[0]).write_text('changed input')
    with pytest.raises(AssertionError): tool.validate_build(git, tmp_path, head, evidence, names)
    bundle = tmp_path / 'web'; bundle.mkdir()
    (bundle / 'index.html').write_text('synthetic export')
    assert tool.exports(bundle) == {'index.html': tool.sha(bundle / 'index.html')}


def test_real_fixture_inputs_receipt_oracle_and_closed_sqlite_cleanup(tmp_path):
    # Flask test client and synthetic CSV/XLSX; does not launch Edge or claim browser coverage.
    bundle = tmp_path / 'unused-export'; bundle.mkdir()
    (bundle / 'index.html').write_text('<title>Tool fixture only</title>')
    out = tmp_path / 'proof'; out.mkdir()
    report = {'artifacts': []}
    with ExitStack() as lifecycle:
        folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='finance-flow-unit-', dir=tmp_path)))
        run = tool.Run(tool.ROOT, bundle, folder, report, out, lifecycle)
        assert run.thread.is_alive()
        client = run.application.test_client()
        response = client.post('/api/login', json={'username': 'member1', 'password': 'testing-password-one'}, base_url=run.base)
        assert response.status_code == 200
        headers = {'X-CSRF-Token': client.get('/api/me', base_url=run.base).json['csrf'], 'Origin': run.base}
        payload = tool.fixture.file_payload(tool.csv_bytes(tool.ROWS, tool.HEADERS))
        payload['mapping'] = {**tool.mapping_fixture.MAPPING, 'version': 2, 'flow': None}
        automatic = client.post(tool.BASE + '/preview', json=payload, headers=headers, base_url=run.base)
        assert automatic.status_code == 200 and [r['flow'] for r in automatic.json['rows']] == ['unknown', 'unknown']
        assert not run.records()
        payload['mapping']['flow'] = 4
        response = client.post(tool.BASE + '/preview', json=payload, headers=headers, base_url=run.base)
        assert response.status_code == 200 and [r['flow'] for r in response.json['rows']] == ['expense', 'income']
        body = {**payload, 'requestId': 'a' * 32, 'previewToken': response.json['previewToken']}
        saved = client.post(tool.BASE + '/confirm', json=body, headers=headers, base_url=run.base)
        assert saved.status_code == 200 and saved.json['imported'] == 2
        original = run.snapshot()
        assert run.receipt_counts() == dict(hub_transactions=2, hub_imports=1, hub_import_receipts=1, importAudits=1, receiptAudits=1)
        assert len(run.records()) == 2 and all(row[2] == 1 for row in run.records())
        receipt = client.get(tool.BASE + '/results/' + 'a' * 32, base_url=run.base)
        assert receipt.status_code == 200 and receipt.json['receiptId'] == saved.json['receiptId']
        assert run.snapshot() == original
        xlsx = tool.fixture.file_payload(run.workbook([tool.HEADERS, *tool.ROWS], second_sheet=True), name='synthetic-flow.xlsx')
        xlsx['file']['sheet'] = '支付账单'; xlsx['mapping'] = dict(payload['mapping'])
        result = client.post(tool.BASE + '/preview', json=xlsx, headers=headers, base_url=run.base)
        assert result.status_code == 200 and result.json['fileInfo']['sheet'] == '支付账单'
        assert [r['flow'] for r in result.json['rows']] == ['expense', 'income']
        assert all(r['status'] < 500 for r in run.http)
        assert [r['index'] for r in run.http] == list(range(len(run.http)))
        run.proof('synthetic-oracle', {'records': run.records(), 'counts': run.receipt_counts(), 'http': run.http})
    assert run.server is None and not run.thread.is_alive() and not folder.exists()
    assert report['fixtureHashes'][tool.HARNESS] == tool.sha(tool.ROOT / tool.HARNESS)
