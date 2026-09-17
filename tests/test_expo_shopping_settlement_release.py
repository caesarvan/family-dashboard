"""Role-aware no-DDL guards; optional private CLI uses only temporary generated files."""
from __future__ import annotations

import ast
import copy
import difflib
import io
import json
from pathlib import Path
import re
import socket
import subprocess
import sys
import tarfile
import tempfile
from unittest.mock import patch

import pytest

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy.expo_shopping_settlement_release import prepare as adapter
from deploy.git_blobs import read_git_blobs
from tests import test_expo_trip_recap_release as shared
from tests import test_household_members_release as members


from tests import test_finance_column_mapping_release as mapping


def test_scope_and_reviewed_source_guards():
    assert len(adapter.REQUIRED_TESTS) == 8
    assert set(adapter.UNCHANGED) == (set(adapter.previous.UNCHANGED) - {'shopping_settlement.py'}) | {'finance_hub.py'}
    assert set(adapter.BACKEND_UNCHANGED) == (set(adapter.previous.BACKEND_UNCHANGED) - {'shopping_settlement.py'}) | {'finance_hub.py'}
    assert adapter.LOCAL_BUILD_SOURCES == adapter.previous.LOCAL_BUILD_SOURCES
    assert not (adapter.REQUIRED_CHANGED | adapter.REQUIRED_ADDED) & set(adapter.UNCHANGED)
    assert not adapter.REQUIRED_CHANGED & adapter.REQUIRED_ADDED
    assert len(adapter.PINNED) == len(set(adapter.PINNED.values())) == 9
    pins = adapter.reviewed_sources()
    assert pins['finance_hub.py'] == '093fb1cd54adb4cce7e486b44834800ec018be01cd7b668fc51ceb33f21d3091'
    guard = compile(adapter.source_guard().replace('    need(', 'need('), '<source pins>', 'exec')
    exec(guard, {'manifest': pins, 'need': adapter.need})
    for path in pins:
        for replacement in (None, '0'*64):
            with pytest.raises(RuntimeError):
                exec(guard, {'manifest': {**pins, path: replacement}, 'need': adapter.need})


def test_missing_or_malformed_review_pin_creates_no_output(tmp_path, monkeypatch):
    output = tmp_path/'expo-shopping-settlement-tools-synthetic'
    for pin in (None, '', '0'*63, 'A'*64, True):
        monkeypatch.setattr(adapter, 'SHOPPING_SOURCE_SHA256', pin)
        with pytest.raises(RuntimeError, match='reviewed shopping source pin'):
            adapter.prepare(tmp_path, output)
        assert not output.exists()


def test_docker_bytes_cannot_change():
    with patch.object(mapping, 'adapter', adapter):
        mapping.test_docker_bytes_cannot_change()


def test_original_bytes_paths_and_size_are_strict(tmp_path, monkeypatch):
    with patch.object(members, 'adapter', adapter):
        members.test_pinned_original_bytes_paths_and_size_are_strict(tmp_path, monkeypatch)


def test_generation_is_exclusive_confined_unbound_and_rechecks_inputs(tmp_path, monkeypatch):
    raw = b'# original\n'; path = tmp_path/'source.py'; path.write_bytes(raw)
    monkeypatch.setattr(adapter, 'PINNED', {'source.py': adapter.sha(raw)})
    monkeypatch.setattr(adapter, 'adapt', lambda *_: {'operators/build.py': b'raise RuntimeError("unbound")\n'})
    output = tmp_path/'expo-shopping-settlement-tools-synthetic'
    report = adapter.prepare(tmp_path, output)
    assert not report['bound'] and not report['schemaChange'] and not report['productionOperations']
    assert report['profile'] == 'household_members58' and report['expectedTestCount'] is None
    assert report['householdTablesBefore'] == report['householdTablesAfter'] == 58
    assert not (output/'operator-bindings.json').exists()
    for wrong in (output, tmp_path.parent/output.name, tmp_path/'finance-column-mapping-tools-replay'):
        with pytest.raises(RuntimeError): adapter.prepare(tmp_path, wrong)
    def drift(*_):
        path.write_bytes(b'# changed\n'); return {}
    monkeypatch.setattr(adapter, 'adapt', drift)
    raced = tmp_path/'expo-shopping-settlement-tools-race'
    with pytest.raises(RuntimeError, match='checksum'): adapter.prepare(tmp_path, raced)
    assert not raced.exists()


def test_bad_freeze_rejected_before_code_evaluation(tmp_path):
    for damage in ('outside', 'large', 'duplicate'):
        root = tmp_path/damage/'access'; root.mkdir(parents=True)
        path = (root.parent if damage == 'outside' else root)/'freeze.json'
        path.write_bytes(b'x'*2_000_001 if damage == 'large' else b'{"main":1,"main":2}')
        with pytest.raises(RuntimeError):
            adapter.freeze_config(path, root, {'prepare-package.py': b'raise AssertionError("not evaluated")'})


def test_no_phase_can_replay_migration_or_mutate_sql():
    for code in ("migrate(Path('/data'),before,backup,schema)", 'verify_baseline(before)',
                 'verify_addition(before,after,schema)', 'init_schema(con)', 'initialize_database(a,b)',
                 'create_app(config)', "program='con.executescript(sql)'", "program=\"con.execute('ALTER TABLE users ADD x')\""):
        for phase in ('operators/activate.py', 'operators/post_readback.py'):
            with pytest.raises(RuntimeError): adapter.verify_generated(code, phase)


def test_populated_role_aware_preservation_and_restart(tmp_path, monkeypatch):
    with patch.object(mapping, 'adapter', adapter):
        mapping.test_populated_role_aware_snapshot_backup_and_app_restart(tmp_path, monkeypatch)


def function_source(code, name):
    node = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(code.decode() if isinstance(code, bytes) else code, node)


def check_pinned_local_operators(source_root, git_repo, git_revision, evidence_dir):
    """Private originals + fixed Git only; generated programs cannot launch process/network."""
    inputs = adapter.read_sources(source_root)
    archive = adapter.safe_path(source_root/adapter.BASE/'package/release.tar.gz').read_bytes()
    assert adapter.sha(archive) == adapter.OLD_ARCHIVE
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as packed:
        raw = packed.extractfile('RELEASE-MANIFEST.json').read()
        assert adapter.sha(raw) == adapter.OLD_MANIFEST
        old = json.loads(raw)['files']; old_docker = packed.extractfile('Dockerfile').read()
    assert re.fullmatch('[a-f0-9]{40}', git_revision)
    names = set(subprocess.check_output(['git', '--no-replace-objects', '-C', str(git_repo), 'ls-tree', '-rz', '--name-only', git_revision]).decode().rstrip('\0').split('\0'))
    pins = adapter.reviewed_sources()
    blobs = read_git_blobs(git_repo, git_revision, sorted({*adapter.UNCHANGED, *pins, 'deploy/prepare_release.py'}))
    for path in adapter.UNCHANGED: assert adapter.sha(blobs[path]) == old[path], path
    for path, digest in pins.items(): assert adapter.sha(blobs[path]) == digest, path
    def deny(*_a, **_k): raise AssertionError('No process or network in generated checks')
    with tempfile.TemporaryDirectory(prefix='shopping-settlement-release-') as folder, \
         patch('subprocess.run', deny), patch('subprocess.Popen', deny), patch('subprocess.check_output', deny), \
         patch('socket.create_connection', deny), patch.object(socket.socket, 'connect', deny):
        access = Path(folder).resolve()
        for name in adapter.PINNED:
            target = access/name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes((source_root/name).read_bytes())
        output = access/'expo-shopping-settlement-tools-synthetic'
        report = adapter.prepare(access, output)
        generated = {name: (output/name).read_bytes() for name in report['generatedHashes']}
        delta = ''
        for name, raw in generated.items():
            assert adapter.sha(raw) == report['generatedHashes'][name]; adapter.verify_generated(raw, name)
            original = inputs[adapter.BASE+name]
            delta += ''.join(difflib.unified_diff(original.decode().splitlines(True), raw.decode().splitlines(True), fromfile='parent/'+name, tofile='generated/'+name))
        for name in ('validate.py', 'stage.py', 'expo_contract.py'):
            assert generated['operators/'+name] == inputs[adapter.BASE+'operators/'+name]
        # Runtime limits, backup/readback helpers, byte partition and binding
        # implementations must remain the actual installed implementations.
        untouched_functions = 0
        for name, changed in {
            'prepare-package.py': {'validate_config', 'inspect_inputs'},
            'bind-release.py': set(), 'operators/ops_common.py': {'source_state'},
            'operators/build.py': {'main'}, 'operators/activate.py': {'main'},
            'operators/post_readback.py': {'main'},
        }.items():
            for node in ast.parse(inputs[adapter.BASE+name]).body:
                if isinstance(node, ast.FunctionDef) and node.name not in changed:
                    assert function_source(generated[name], node.name) == function_source(inputs[adapter.BASE+name], node.name)
                    untouched_functions += 1
        for name in ('inspect_backup_group', 'readonly_backup_args', 'backup_names'):
            assert function_source(generated['operators/post_readback.py'], name) == function_source(inputs[adapter.BASE+'operators/post_readback.py'], name)
        shared.check_activation_evidence(generated['operators/post_readback.py'])
        anonymous = members.anonymous_checks(generated['operators/post_readback.py'])
        parent_anonymous = members.anonymous_checks(inputs[adapter.BASE+'operators/post_readback.py'])
        assert len(set(anonymous)) == 39 and set(anonymous) - set(parent_anonymous) == {'/api/finance-hub/shopping-settlements/context'}
        assert set(parent_anonymous) <= set(anonymous)
        contract = shared.load_module('shopping_contract', output/'operators/expo_contract.py')
        contract.verify_docker_delta(old_docker, blobs['Dockerfile'])
        package = shared.load_module('shopping_package', output/'prepare-package.py')
        selected = package.selected_sources(names, blobs['deploy/prepare_release.py'])
        unsafe = {'.env', 'frontend/.env.local', 'frontend/node_modules/unsafe.js', 'data/private.sqlite3', 'frontend/dist/unsafe.js'}
        assert not package.selected_sources(names | unsafe, blobs['deploy/prepare_release.py']) & unsafe
        required_inputs = contract.required_inputs(names, blobs['Dockerfile'])
        assert required_inputs <= selected and set(adapter.LOCAL_BUILD_SOURCES) <= selected
        missing = (adapter.REQUIRED_CHANGED | adapter.REQUIRED_ADDED) - selected
        assert missing <= {'deploy/expo_shopping_settlement_release/prepare.py', 'tests/test_expo_shopping_settlement_release.py'}
        rejected = []
        for name, function in (('operators/ops_common.py', 'source_state'), ('prepare-package.py', 'inspect_inputs')):
            tree = ast.parse(generated[name]); body = next(n.body for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == function)
            loop = next(n for n in body if isinstance(n, ast.For) and isinstance(n.iter, ast.Tuple) and all(isinstance(v, ast.Constant) for v in n.iter.elts))
            assert ast.literal_eval(loop.iter) == adapter.UNCHANGED
            guards = [n for n in body if isinstance(n, ast.Expr) and 'Reviewed shopping settlement source changed:' in ast.unparse(n)]
            assert len(guards) == len(pins)
            program = compile(ast.fix_missing_locations(ast.Module(body=[loop, *guards], type_ignores=[])), name, 'exec')
            manifest = {**old, **{path: adapter.sha(raw) for path, raw in blobs.items()}}
            scope = {'need': adapter.need, 'old': old, 'manifest': manifest}; exec(program, scope)
            for path in set(adapter.UNCHANGED) | set(pins):
                scope['manifest'] = {**manifest, path: '0'*64}
                with pytest.raises(RuntimeError): exec(program, scope)
                rejected.append(name+':'+path)
        with patch.object(shared, 'adapter', adapter): config = shared.synthetic_config(access)
        assert package.validate_config(config) == config
        bad_configs = []
        for field, bad in [('oldManifestSha256', adapter.previous.OLD_MANIFEST), ('oldArchiveSha256', adapter.previous.OLD_ARCHIVE),
                           ('parentImage', adapter.previous.PARENT_IMAGE), ('expectedTestCount', True)]:
            changed = copy.deepcopy(config); changed[field] = bad; bad_configs.append(changed)
        for field, required in [('validationTests', adapter.REQUIRED_TESTS), ('changedFiles', adapter.REQUIRED_CHANGED), ('addedFiles', adapter.REQUIRED_ADDED)]:
            for item in required:
                changed = copy.deepcopy(config); changed[field].remove(item); bad_configs.append(changed)
        for changed in bad_configs:
            with pytest.raises(RuntimeError): package.validate_config(changed)
        freeze = access/'freeze.json'; freeze.write_text(json.dumps(config))
        frozen = access/'expo-shopping-settlement-tools-frozen'; frozen_report = adapter.prepare(access, frozen, freeze)
        assert frozen_report['expectedTestCount'] == 9991  # Only synthetic config; never a collected count.
        invalid = access/'invalid-freeze.json'; invalid.write_text('{}')
        with patch.object(sys, 'argv', [str(output/'prepare-package.py'), '--freeze', str(invalid)]), pytest.raises(RuntimeError):
            package.main()
        assert not (output/'package').exists()
        binder = shared.load_module('shopping_binder', output/'bind-release.py')
        with patch.object(sys, 'argv', [str(output/'bind-release.py'), '--operator-review', str(access/'absent.json'), '--operator-review-sha256', 'invalid']), pytest.raises(RuntimeError, match='checksum'):
            binder.main()
        assert not (output/'package/operator-bindings.json').exists()
        saved = {name: sys.modules.get(name) for name in ('expo_contract', 'ops_common')}; checked = ['prepare-package.py', 'bind-release.py']
        try:
            ops = frozen/'operators'
            sys.modules['expo_contract'] = shared.load_module('shopping_frozen_contract', ops/'expo_contract.py')
            common = shared.load_module('shopping_frozen_common', ops/'ops_common.py'); sys.modules['ops_common'] = common
            common.CANDIDATE = ops; common.BINDING_PATH = ops/'operator-bindings.json'; common.host_guard = lambda: None
            for name in ('build.py', 'validate.py', 'stage.py', 'activate.py', 'post_readback.py'):
                phase = shared.load_module('shopping_'+name[:-3], ops/name)
                argv = [str(ops/name)]
                if name == 'post_readback.py': argv += ['--reviewed-sha256', adapter.sha((ops/name).read_bytes())]
                with patch.object(sys, 'argv', argv), pytest.raises(RuntimeError, match='unbound'): phase.main()
                checked.append(name)
        finally:
            for name, value in saved.items():
                if value is None: sys.modules.pop(name, None)
                else: sys.modules[name] = value
        with (evidence_dir/'generated-delta.patch').open('x', encoding='utf-8', newline='\n') as stream: stream.write(delta)
        return dict(sourceHashes=adapter.PINNED, reviewedSourceHashes=pins, generatedHashes=report['generatedHashes'],
            gitRevision=git_revision, pendingReleaseFiles=sorted(missing), requiredBuildInputs=len(required_inputs),
            sourceMutationRejections=len(rejected), badFreezeRejections=len(bad_configs),
            anonymous401Paths=list(dict.fromkeys(anonymous)), anonymousCheckRequests=len(anonymous),
            rejectedEntrypoints=checked, invalidLocalEntrypoints=checked[:2], unboundPhaseEntrypoints=checked[2:],
            syntheticFreezeCount=9991, schemaChange=False,
            unchangedParentFunctions=untouched_functions,
            profile='household_members58', productionOperations=False, networkOrGeneratedProcessCalls=False,
            generatedDeltaSha256=adapter.sha((evidence_dir/'generated-delta.patch').read_bytes()))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--git-repo', type=Path, required=True); parser.add_argument('--git-revision', required=True)
    parser.add_argument('--evidence-dir', type=Path, required=True)
    args = parser.parse_args(); assert sys.dont_write_bytecode and not sys.flags.optimize
    assert args.evidence_dir.is_dir() and not any(args.evidence_dir.iterdir())
    print(json.dumps(check_pinned_local_operators(args.source_root, args.git_repo, args.git_revision, args.evidence_dir), indent=2))
