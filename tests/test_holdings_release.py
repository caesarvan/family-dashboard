"""Synthetic local guards for the bounded 54 -> 55 operator adapter."""
import json
from pathlib import Path
import socket
import subprocess

import pytest

from deploy.holdings_release import prepare as adapter


@pytest.fixture(autouse=True)
def no_external_actions(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError('Release adapter tests cannot run external actions')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(subprocess, 'run', deny)
    monkeypatch.setattr(subprocess, 'check_output', deny)


def contract():
    namespace = {'need': adapter.need}
    exec(adapter.DOCKER_CONTRACT, namespace)
    return namespace['verify_docker_delta']


def docker_pair():
    old = b'FROM synthetic-pinned-image\nCOPY calendar_publish.py financial_files.py investment_import.py ./\nUSER dashboard\n'
    return old, old.replace(b'investment_import.py ./', b'investment_import.py investment_operations.py ./')


def test_docker_delta_allows_only_the_single_new_runtime_module():
    contract()(*docker_pair())


@pytest.mark.parametrize('change', ['unchanged', 'base', 'user', 'extra_module', 'other_line', 'duplicate_copy', 'missing_old_line'])
def test_docker_contract_rejects_unreviewed_changes(change):
    old, new = docker_pair()
    if change == 'unchanged':
        new = old
    elif change == 'base':
        new = new.replace(b'synthetic-pinned-image', b'other-image')
    elif change == 'user':
        new = new.replace(b'USER dashboard', b'USER root')
    elif change == 'extra_module':
        new = new.replace(b'investment_operations.py', b'investment_operations.py extra.py')
    elif change == 'other_line':
        new += b'RUN arbitrary-command\n'
    elif change == 'duplicate_copy':
        old += b'COPY calendar_publish.py financial_files.py investment_import.py ./\n'
    else:
        old = old.replace(b'investment_import.py ./', b'investment_import.py old.py ./')
    with pytest.raises(RuntimeError):
        contract()(old, new)


def test_assignment_handles_multiline_without_touching_other_code():
    source = 'COUNT=418\nTESTS=(\n "old",\n)\nOTHER="COUNT=418"\n'
    changed = adapter.assignment(source, 'TESTS', repr(('a', 'b')))
    assert changed == 'COUNT=418\nTESTS = (\'a\', \'b\')\nOTHER="COUNT=418"\n'
    assert adapter.assignment(changed, 'COUNT', 'None').startswith('COUNT = None\n')


@pytest.mark.parametrize('source', ['OTHER=1\n', 'COUNT=1\nCOUNT=2\n'])
def test_assignment_rejects_absent_or_ambiguous_anchor(source):
    with pytest.raises(RuntimeError):
        adapter.assignment(source, 'COUNT', 'None')


def test_replacements_are_exact_and_simultaneous():
    assert adapter.substitutions('53 -> 54; old54; 5354hash', {'53 -> 54': '54 -> 55', 'old54': 'new55'}) == '54 -> 55; new55; 5354hash'
    with pytest.raises(RuntimeError):
        adapter.replace('x x', 'x', 'y')
    with pytest.raises(RuntimeError):
        adapter.substitutions('x', {'missing': 'y'})


def synthetic_sources(tmp_path, monkeypatch):
    directory = tmp_path / 'private-access'
    directory.mkdir()
    raw = b'# synthetic reviewed operator\r\n'
    (directory / 'reviewed.py').write_bytes(raw)
    monkeypatch.setattr(adapter, 'PINNED', {'reviewed.py': adapter.sha(raw)})
    return directory, raw


def test_source_hashes_bind_raw_bytes_before_line_normalization(tmp_path, monkeypatch):
    directory, raw = synthetic_sources(tmp_path, monkeypatch)
    assert adapter.read_sources(directory) == {'reviewed.py': raw.replace(b'\r\n', b'\n')}
    (directory / 'reviewed.py').write_bytes(raw.replace(b'\r\n', b'\n'))
    with pytest.raises(RuntimeError, match='checksum'):
        adapter.read_sources(directory)


def test_source_alteration_or_missing_file_rejects(tmp_path, monkeypatch):
    directory, _ = synthetic_sources(tmp_path, monkeypatch)
    (directory / 'reviewed.py').write_text('different', encoding='utf-8')
    with pytest.raises(RuntimeError):
        adapter.read_sources(directory)
    monkeypatch.setattr(adapter, 'PINNED', {'absent.py': 'a' * 64})
    with pytest.raises(RuntimeError):
        adapter.read_sources(directory)


@pytest.mark.parametrize('name', ['relative.json', '../outside.json'])
def test_relative_and_traversing_paths_reject(name):
    with pytest.raises(RuntimeError):
        adapter.safe_path(Path(name), exists=False)


def test_absolute_traversal_and_linked_ancestor_reject(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError):
        adapter.safe_path(tmp_path / '..' / 'outside', exists=False)
    original = Path.is_symlink
    monkeypatch.setattr(Path, 'is_symlink', lambda self: self == tmp_path or original(self))
    with pytest.raises(RuntimeError):
        adapter.safe_path(tmp_path / 'output', exists=False)


def test_output_is_new_confined_and_unbound(tmp_path, monkeypatch):
    directory, _ = synthetic_sources(tmp_path, monkeypatch)
    # This test isolates exclusive artifact creation and its audit report;
    # the real pinned transformation is checked separately against local originals.
    generated = {'operators/build.py': b'raise RuntimeError("unbound synthetic operator")\n'}
    monkeypatch.setattr(adapter, 'adapt', lambda *_args: generated)
    output = directory / 'expo-holdings-tools-synthetic'
    report = adapter.prepare(directory, output)
    assert report['bound'] is False and report['finalFreezeProvided'] is False
    assert report['expectedTestCount'] is None and report['freezeSha256'] is None
    assert report['requiresIndependentOperatorReview'] is True and report['productionOperations'] is False
    assert not (output / 'operators' / 'operator-bindings.json').exists()
    assert (output / 'operators/build.py').read_bytes() == generated['operators/build.py']
    assert json.loads((output / 'generation.json').read_text()) == report
    with pytest.raises(RuntimeError, match='already exists'):
        adapter.prepare(directory, output)
    with pytest.raises(RuntimeError, match='Output must'):
        adapter.prepare(directory, tmp_path / 'expo-holdings-tools-outside')


def test_no_output_when_pinned_source_changes_during_generation(tmp_path, monkeypatch):
    directory, _ = synthetic_sources(tmp_path, monkeypatch)
    def changed(*_args):
        (directory / 'reviewed.py').write_text('changed while generating', encoding='utf-8')
        return {'operators/build.py': b'# not written\n'}
    monkeypatch.setattr(adapter, 'adapt', changed)
    output = directory / 'expo-holdings-tools-synthetic'
    with pytest.raises(RuntimeError, match='checksum'):
        adapter.prepare(directory, output)
    assert not output.exists()


def test_freeze_rejects_outside_and_oversize_before_parsing(tmp_path):
    directory = tmp_path / 'private-access'
    directory.mkdir()
    outside = tmp_path / 'outside.json'
    outside.write_text('{}')
    with pytest.raises(RuntimeError, match='bounded private'):
        adapter.freeze_config(outside, directory, {})
    huge = directory / 'large.json'
    huge.write_bytes(b'x' * 2_000_001)
    with pytest.raises(RuntimeError, match='bounded private'):
        adapter.freeze_config(huge, directory, {})


def test_duplicate_freeze_keys_reject(tmp_path):
    path = tmp_path / 'freeze.json'
    path.write_text('{"main":"a","main":"b"}')
    with pytest.raises(RuntimeError, match='Duplicate'):
        adapter.freeze_config(path, tmp_path, {})


def check_pinned_local_operators(source_root):
    """Explicit local integration check; external reviewed originals are not CI fixtures.

    Invoked separately with --source-root, never silently skipped by pytest.
    It executes only generated entrypoints that must reject an absent binding;
    subprocess and network calls raise before they can perform any action.
    """
    import ast
    import sys
    import tempfile
    import types
    from unittest.mock import patch
    original_sources = adapter.read_sources(source_root)
    def deny(*_args, **_kwargs):
        raise AssertionError('Unbound operator attempted an external action')
    with tempfile.TemporaryDirectory(prefix='holdings-operator-guards-') as folder:
        access = Path(folder).resolve()
        for name in adapter.PINNED:
            destination = access / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((source_root / name).read_bytes())
        assert adapter.read_sources(access) == original_sources
        output = access / 'expo-holdings-tools-synthetic'
        generated = adapter.prepare(access, output)
        assert generated['bound'] is False and generated['finalFreezeProvided'] is False
        directory = output / 'operators'
        # Check generated executable syntax, including Python inside strings:
        # unchanged old lines do not appear in the adapter's reviewed diff.
        def assert_no_old_table_count(tree):
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant):
                    assert not (type(node.value) is int and node.value == 53)
                    if isinstance(node.value, str):
                        try:
                            embedded = ast.parse(node.value)
                        except (SyntaxError, ValueError):
                            continue
                        assert_no_old_table_count(embedded)
        for filename in generated['generatedHashes']:
            assert_no_old_table_count(ast.parse((output / filename).read_bytes()))
        activation = ast.parse((directory / 'activate.py').read_bytes())
        migration_guards = [node for node in ast.walk(activation)
                            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                            and node.func.id == 'need' and node.args
                            and isinstance(node.args[0], ast.Compare)
                            and isinstance(node.args[0].left, ast.Name)
                            and node.args[0].left.id == 'migration_result']
        assert len(migration_guards) == 1
        guard = compile(ast.fix_missing_locations(ast.Module(
            body=[ast.Expr(value=migration_guards[0])], type_ignores=[])), '<generated-migration-guard>', 'exec')
        expected_result = {'originalTablesPreserved': 54, 'newTables': 1, 'households': 2,
                           'newTableEmpty': True, 'oldRowsSchemaAndSequencesPreserved': True,
                           'registryPreserved': True}
        rejected_results = [('old_53', {'originalTablesPreserved': 53}),
                            ('after_55', {'originalTablesPreserved': 55}),
                            ('wrong_new_count', {'newTables': 0}), ('wrong_households', {'households': 1}),
                            ('not_empty', {'newTableEmpty': False}),
                            ('old_data_changed', {'oldRowsSchemaAndSequencesPreserved': False}),
                            ('registry_changed', {'registryPreserved': False}), ('extra_key', {'extra': True})]
        for mode, change in [('valid_54_two_households', {}), *rejected_results]:
            context = {'__builtins__': {'len': len}, 'need': adapter.need,
                       'before': {'households': [{}, {}]}, 'migration_result': {**expected_result, **change}}
            try:
                exec(guard, context)
            except RuntimeError as exc:
                assert mode != 'valid_54_two_households' and str(exc) == 'Unexpected migration result'
            else:
                assert mode == 'valid_54_two_households', mode
        blocked = []
        with patch.object(subprocess, 'run', deny), patch.object(subprocess, 'check_output', deny), patch.object(socket.socket, 'connect', deny):
            def load(name, filename):
                module = types.ModuleType(name)
                module.__file__ = str(directory / filename)
                raw = (directory / filename).read_bytes()
                ast.parse(raw)
                exec(compile(raw, module.__file__, 'exec'), module.__dict__)
                return module
            contract_module = load('expo_contract', 'expo_contract.py')
            with patch.dict(sys.modules, {'expo_contract': contract_module}):
                common = load('ops_common', 'ops_common.py')
                common.CANDIDATE = directory
                common.BINDING_PATH = directory / 'operator-bindings.json'
                with patch.dict(sys.modules, {'ops_common': common}):
                    for name in ('build.py', 'validate.py', 'stage.py', 'activate.py', 'post_readback.py'):
                        operator = load('synthetic_' + name[:-3], name)
                        with patch.object(sys, 'argv', [name, '--reviewed-sha256', adapter.sha((directory / name).read_bytes())]):
                            try:
                                operator.main()
                            except RuntimeError as exc:
                                assert 'Release unbound' in str(exc), (name, str(exc))
                                blocked.append(name)
                            else:
                                raise AssertionError('Unbound operator did not reject: ' + name)
                common.BINDING_PATH.write_text('{"bound":true}')
                try:
                    common.release_binding()
                except RuntimeError as exc:
                    assert 'lacks a final verified' in str(exc)
                else:
                    raise AssertionError('Unfrozen template accepted a fabricated binding')
                # Exercise the actual reused JUnit parser with synthetic data;
                # this is not a Linux run or a production test-count assertion.
                import xml.etree.ElementTree as ET
                common.EXPECTED_TEST_COUNT = 3
                junit_checks = []
                for mode in ('valid', 'wrong_name', 'wrong_message', 'duplicate', 'wrong_count', 'failure'):
                    suite = ET.Element('testsuite', tests='4' if mode == 'wrong_count' else '3',
                                       failures='1' if mode == 'failure' else '0', errors='0', skipped='1')
                    ET.SubElement(suite, 'testcase', classname='tests.synthetic', name='one')
                    second = ET.SubElement(suite, 'testcase', classname='tests.synthetic', name='one' if mode == 'duplicate' else 'two')
                    if mode == 'failure':
                        ET.SubElement(second, 'failure')
                    case = ET.SubElement(suite, 'testcase', classname='tests.test_frontend_runtime',
                                         name='other' if mode == 'wrong_name' else 'test_windows_junction_rejected')
                    ET.SubElement(case, 'skipped', message='different' if mode == 'wrong_message' else 'Windows junction semantics')
                    junit = access / (mode + '.xml')
                    ET.ElementTree(suite).write(junit)
                    accepted = common.junit_result(junit)[-1]
                    assert accepted is (mode == 'valid')
                    junit_checks.append(mode)
                # Retained r3 checks must reject a stale invocation or a backup
                # manifest which this invocation did not uniquely produce.
                filename = 'manifest-20260917T010101123456Z.json'
                previous = {'ActiveState': 'inactive', 'InvocationID': 'a' * 32, 'ExecMainStartTimestampMonotonic': '1'}
                completed = {'ActiveState': 'inactive', 'SubState': 'dead', 'Result': 'success',
                             'InvocationID': 'b' * 32, 'ExecMainCode': '1', 'ExecMainStatus': '0',
                             'ExecMainStartTimestampMonotonic': '2', 'ExecMainExitTimestampMonotonic': '3'}
                receipt = {'manifest': filename, 'databases': 3}
                assert operator.select_fresh_backup([], [filename], previous, completed, json.dumps(receipt)) == receipt
                backup_checks = []
                for mode in ('stale_invocation', 'manifest_not_new', 'failed_service'):
                    after = {**completed}
                    before_names = []
                    if mode == 'stale_invocation':
                        after['InvocationID'] = previous['InvocationID']
                    elif mode == 'manifest_not_new':
                        before_names = [filename]
                    else:
                        after['Result'] = 'failed'
                    try:
                        operator.select_fresh_backup(before_names, [filename], previous, after, json.dumps(receipt))
                    except RuntimeError:
                        backup_checks.append(mode)
                    else:
                        raise AssertionError('Fresh backup guard accepted: ' + mode)
        assert adapter.read_sources(source_root) == original_sources
        return {'sourceHashes': adapter.PINNED, 'transformedPythonFiles': 9,
                'generatedMigrationGuard': {'accepted': 'valid_54_two_households',
                                            'rejected': [mode for mode, _ in rejected_results]},
                'oldTableCount53AbsentFromGeneratedSyntax': True,
                'unboundEntrypointsRejected': blocked, 'unfrozenBindingRejected': True,
                'syntheticJunitParserChecks': junit_checks, 'syntheticFreshBackupRejections': backup_checks,
                'freshBackupR3SourceSha256': adapter.PINNED['expo-finance-post-r3-20260917/post_readback_r3.py'],
                'externalActions': False, 'productionOperations': False,
                'scope': 'Actual pinned-source transformation and unbound entrypoint rejection; no package/build/activation'}


if __name__ == '__main__':
    import argparse
    import sys
    parser = argparse.ArgumentParser(description='Check pinned local operators without external actions')
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    adapter.need(sys.dont_write_bytecode and not sys.flags.optimize, 'Run python -B')
    adapter.need(not args.report.exists(), 'Report exists; preserve previous evidence')
    result = check_pinned_local_operators(args.source_root)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps(result))
