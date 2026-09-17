"""Local adapter guards. Optional CLI checks pinned originals, never packages or deploys."""
from __future__ import annotations

import ast
import copy
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

from deploy.household_members_release import prepare as adapter
from deploy.git_blobs import read_git_blobs
from tests import test_expo_trip_recap_release as parent_tests


def test_scope_and_exact_sources_reject_drift():
    assert len(adapter.REQUIRED_TESTS) == 8
    assert set(adapter.UNCHANGED) == (set(adapter.previous.UNCHANGED) - {'app.py', 'Dockerfile', 'deploy/prepare_release.py'}) | {'journey_workflows.py'}
    assert set(adapter.BACKEND_UNCHANGED) == (set(adapter.previous.BACKEND_UNCHANGED) - {'app.py'}) | {'journey_workflows.py'}
    assert adapter.LOCAL_BUILD_SOURCES == adapter.previous.LOCAL_BUILD_SOURCES
    assert not (adapter.REQUIRED_CHANGED | adapter.REQUIRED_ADDED) & set(adapter.UNCHANGED)
    assert not adapter.REQUIRED_CHANGED & adapter.REQUIRED_ADDED
    guard = compile(adapter.source_guard().replace('    need(', 'need('), '<source pins>', 'exec')
    exec(guard, {'manifest': adapter.SOURCE_PINS, 'need': adapter.need})
    for path in adapter.SOURCE_PINS:
        for replacement in (None, '0'*64):
            with pytest.raises(RuntimeError):
                exec(guard, {'manifest': {**adapter.SOURCE_PINS, path: replacement}, 'need': adapter.need})


def test_docker_allows_only_reviewed_copy_bytes():
    scope = {'need': adapter.need}
    exec(adapter.DOCKER_CONTRACT, scope)
    old = b'FROM parent\nCOPY app.py frontend_runtime.py member_sessions.py tv_display.py sync_health.py ./\r\nUSER dashboard\n'
    new = old.replace(b'member_sessions.py tv_display', b'member_sessions.py household_members.py tv_display').replace(b'./\r\n', b'./\n')
    scope['verify_docker_delta'](old, new)
    for wrong in (old, new+b'RUN echo unexpected\n', new.replace(b'USER dashboard', b'USER root'), new.replace(b'FROM parent', b'FROM other')):
        with pytest.raises(RuntimeError): scope['verify_docker_delta'](old, wrong)


def test_pinned_original_bytes_paths_and_size_are_strict(tmp_path, monkeypatch):
    raw = b'# synthetic\r\n'; path = tmp_path/'source.py'; path.write_bytes(raw)
    monkeypatch.setattr(adapter, 'PINNED', {'source.py': adapter.sha(raw)})
    assert adapter.read_sources(tmp_path) == {'source.py': raw.replace(b'\r\n', b'\n')}
    path.write_bytes(raw.replace(b'\r\n', b'\n'))
    with pytest.raises(RuntimeError, match='checksum'): adapter.read_sources(tmp_path)
    path.write_bytes(b'x'*100_000)
    with pytest.raises(RuntimeError, match='Bounded'): adapter.read_sources(tmp_path)
    with pytest.raises(RuntimeError): adapter.safe_path(Path('relative'))
    with pytest.raises(RuntimeError): adapter.safe_path(tmp_path/'..'/'outside', exists=False)


def test_input_race_leaves_no_output(tmp_path, monkeypatch):
    raw = b'# original\n'; (tmp_path/'source.py').write_bytes(raw)
    monkeypatch.setattr(adapter, 'PINNED', {'source.py': adapter.sha(raw)})
    def drift(*_):
        (tmp_path/'source.py').write_bytes(b'# changed\n'); return {}
    monkeypatch.setattr(adapter, 'adapt', drift)
    output = tmp_path/'household-members-tools-synthetic'
    with pytest.raises(RuntimeError, match='checksum'): adapter.prepare(tmp_path, output)
    assert not output.exists()


def test_new_output_is_exclusive_confined_and_unbound(tmp_path, monkeypatch):
    raw = b'# original\n'; (tmp_path/'source.py').write_bytes(raw)
    monkeypatch.setattr(adapter, 'PINNED', {'source.py': adapter.sha(raw)})
    monkeypatch.setattr(adapter, 'adapt', lambda *_: {'operators/build.py': b'raise RuntimeError("unbound")\n'})
    output = tmp_path/'household-members-tools-synthetic'
    result = adapter.prepare(tmp_path, output)
    assert not result['bound'] and not result['productionOperations'] and result['schemaChange']
    assert result['profile'] == 'household_members58'
    assert result['householdTablesBefore'] == result['householdTablesAfter'] == 58
    assert result['expectedTestCount'] is None
    assert not (output/'operator-bindings.json').exists()
    with pytest.raises(RuntimeError, match='exists'): adapter.prepare(tmp_path, output)
    with pytest.raises(RuntimeError): adapter.prepare(tmp_path, tmp_path.parent/output.name)
    with pytest.raises(RuntimeError): adapter.prepare(tmp_path, tmp_path/'expo-trip-import-tools-replay')


@pytest.mark.parametrize('damage', ['outside', 'large', 'duplicate'])
def test_bad_freeze_is_rejected_before_code_evaluation(tmp_path, damage):
    root = tmp_path/'access'; root.mkdir()
    path = (tmp_path if damage == 'outside' else root)/'freeze.json'
    path.write_bytes(b'x'*2_000_001 if damage == 'large' else b'{"main":1,"main":2}')
    with pytest.raises(RuntimeError):
        adapter.schema_release.freeze_config(path, root, {'prepare-package.py': b'raise AssertionError("must not execute")'})


def test_only_exact_activation_helper_call_can_migrate():
    exact = "migrate(Path('/data'),before,backup,schema)"
    adapter.verify_generated(exact, 'operators/activate.py')
    for name, code in [('operators/post_readback.py', exact), ('operators/activate.py', 'migrate(root)'),
        ('operators/activate.py', 'init_schema(con)'), ('operators/activate.py', 'create_app(config)'),
        ('operators/activate.py', "program='con.executescript(sql)'"),
        ('operators/activate.py', "program=\"con.execute('ALTER TABLE users ADD x')\""),
        ('operators/stage.py', 'verify_baseline(before)')]:
        with pytest.raises(RuntimeError): adapter.verify_generated(code, name)


def proof_checks(code):
    main = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    node = next(n for n in main.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                and isinstance(n.value.func, ast.Name) and n.value.func.id == 'need'
                and 'activation_snapshot' in ast.unparse(n.value.args[0]))
    program = compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), '<actual activation proof>', 'exec')
    expected = eval(adapter.ADDITION_RESULT, {'before': {'households': {'default': {}, 'synthetic': {}}}})
    rejected = []
    for damage in (None, 'startup', 'schemaFlag', 'originalUserColumnsPreserved', 'initialRolesVerified',
                   'otherRowsSchemaAndSequencesPreserved', 'registryPreserved', 'addedColumns', 'migration'):
        snapshot = {'synthetic': 'full migrated snapshot'}
        proofs = {'after-migration.json': copy.deepcopy(snapshot), 'migration.json': copy.deepcopy(expected)}
        published = dict(preservationResult=copy.deepcopy(expected), migrationResult=copy.deepcopy(expected),
                         households=2, householdTables=58, schemaChange=True, allExistingDataPreservedAtAppStartup=True)
        if damage == 'startup': proofs['after-migration.json']['synthetic'] = 'drift'
        elif damage == 'schemaFlag': published['schemaChange'] = False
        elif damage == 'migration': published['migrationResult']['newTables'] = 1
        elif damage: published['preservationResult'][damage] = None
        scope = dict(need=adapter.need, activation_snapshot=snapshot, preservation=expected, published=published,
                     proof_root=Path('synthetic'), read=lambda path: proofs[path.name])
        if damage:
            with pytest.raises(RuntimeError): exec(program, scope)
            rejected.append(damage)
        else: exec(program, scope)
    return rejected


def anonymous_checks(code):
    from urllib.error import HTTPError
    main = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    loop = next(n for n in main.body if isinstance(n, ast.For) and isinstance(n.iter, ast.Tuple)
                and '/api/members' in [getattr(v, 'value', None) for v in n.iter.elts])
    assert all(isinstance(n, (ast.Tuple, ast.Constant, ast.Load, ast.BinOp, ast.Add, ast.Mult)) for n in ast.walk(loop.iter))
    paths = eval(compile(ast.Expression(loop.iter), '<pinned anonymous paths>', 'eval'), {'__builtins__': {}})
    assert paths.count('/api/members') == 1
    # Preserve the parent's repeated media-playback request; report unique URLs.
    assert len(paths)-len(set(paths)) == 1
    program = compile(ast.fix_missing_locations(ast.Module(body=[loop], type_ignores=[])), '<actual anonymous guard>', 'exec')
    for status in (401, 200, 403, 404, 500):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            @property
            def status(self): return 200
        def urlopen(url, timeout):
            assert timeout == 15
            value = status if url.endswith('/api/members') else 401
            if value == 200: return Response()
            raise HTTPError(url, value, 'synthetic status boundary', {}, None)
        scope = {'urlopen': urlopen, 'HTTPError': HTTPError, 'need': adapter.need, 'denied': {}}
        if status != 401:
            with pytest.raises(RuntimeError): exec(program, scope)
        else:
            exec(program, scope); assert len(scope['denied']) == len(set(paths))
    return paths


def check_pinned_local_operators(source_root, git_repo, git_revision):
    """One actual-parent temporary generation; generated process/network calls denied."""
    inputs = adapter.read_sources(source_root)
    archive = adapter.safe_path(source_root/adapter.BASE/'package/release.tar.gz').read_bytes()
    assert adapter.sha(archive) == adapter.OLD_ARCHIVE
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as packed:
        raw = packed.extractfile('RELEASE-MANIFEST.json').read()
        assert adapter.sha(raw) == adapter.OLD_MANIFEST
        old = json.loads(raw)['files']; old_docker = packed.extractfile('Dockerfile').read()
    assert re.fullmatch('[a-f0-9]{40}', git_revision)
    names = set(subprocess.check_output(['git', '--no-replace-objects', '-C', str(git_repo), 'ls-tree', '-rz', '--name-only', git_revision]).decode().rstrip('\0').split('\0'))
    requested = {*adapter.UNCHANGED, *adapter.SOURCE_PINS, 'deploy/prepare_release.py'}
    blobs = read_git_blobs(git_repo, git_revision, sorted(requested))
    for path in adapter.UNCHANGED: assert adapter.sha(blobs[path]) == old[path], path
    for path, expected in adapter.SOURCE_PINS.items(): assert adapter.sha(blobs[path]) == expected, path

    def deny(*_a, **_k): raise AssertionError('No process or network in generated checks')
    with tempfile.TemporaryDirectory(prefix='household-members-release-') as folder, \
         patch('subprocess.run', deny), patch('subprocess.Popen', deny), patch('subprocess.check_output', deny), \
         patch('socket.create_connection', deny), patch.object(socket.socket, 'connect', deny):
        access = Path(folder).resolve()
        for name in adapter.PINNED:
            path = access/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes((source_root/name).read_bytes())
        output = access/'household-members-tools-synthetic'
        report = adapter.prepare(access, output)
        generated = {name: (output/name).read_bytes() for name in report['generatedHashes']}
        for name, raw in generated.items():
            assert adapter.sha(raw) == report['generatedHashes'][name]; adapter.verify_generated(raw, name)
        proof_rejections = proof_checks(generated['operators/post_readback.py'])
        anonymous_paths = anonymous_checks(generated['operators/post_readback.py'])
        contract = parent_tests.load_module('household_members_contract', output/'operators/expo_contract.py')
        contract.verify_docker_delta(old_docker, blobs['Dockerfile'])
        with pytest.raises(RuntimeError): contract.verify_docker_delta(old_docker, blobs['Dockerfile']+b'RUN unexpected\n')
        package = parent_tests.load_module('household_members_package', output/'prepare-package.py')
        selected = package.selected_sources(names, blobs['deploy/prepare_release.py'])
        assert contract.required_inputs(names, blobs['Dockerfile']) <= selected
        assert set(adapter.LOCAL_BUILD_SOURCES) <= selected
        missing = (adapter.REQUIRED_CHANGED | adapter.REQUIRED_ADDED) - selected
        # This check can run before the release adapter is merged, never claim a final freeze.
        assert missing <= {'deploy/household_members_release/prepare.py', 'tests/test_household_members_release.py'}
        rejected = []
        for name, function in (('operators/ops_common.py', 'source_state'), ('prepare-package.py', 'inspect_inputs')):
            tree = ast.parse(generated[name]); body = next(n.body for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == function)
            loop = next(n for n in body if isinstance(n, ast.For) and isinstance(n.iter, ast.Tuple)
                        and all(isinstance(v, ast.Constant) for v in n.iter.elts))
            assert ast.literal_eval(loop.iter) == adapter.UNCHANGED
            guards = [n for n in body if isinstance(n, ast.Expr) and 'Reviewed member source changed:' in ast.unparse(n)]
            assert len(guards) == len(adapter.SOURCE_PINS)
            program = compile(ast.fix_missing_locations(ast.Module(body=[loop, *guards], type_ignores=[])), name, 'exec')
            manifest = {**old, **{path: adapter.sha(raw) for path, raw in blobs.items()}}
            scope = {'need': adapter.need, 'old': old, 'manifest': manifest}
            exec(program, scope)
            for path in set(adapter.UNCHANGED) | set(adapter.SOURCE_PINS):
                scope['manifest'] = {**manifest, path: '0'*64}
                with pytest.raises(RuntimeError): exec(program, scope)
                rejected.append(name+':'+path)
        with patch.object(parent_tests, 'adapter', adapter): config = parent_tests.synthetic_config(access)
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
        frozen = access/'household-members-tools-frozen'; frozen_report = adapter.prepare(access, frozen, freeze)
        assert frozen_report['expectedTestCount'] == 9991  # Synthetic count, not collected or executed tests.
        saved = {name: sys.modules.get(name) for name in ('expo_contract', 'ops_common')}
        checked = []
        try:
            ops = frozen/'operators'
            sys.modules['expo_contract'] = parent_tests.load_module('members_frozen_contract', ops/'expo_contract.py')
            common = parent_tests.load_module('members_frozen_common', ops/'ops_common.py'); sys.modules['ops_common'] = common
            common.CANDIDATE = ops; common.BINDING_PATH = ops/'operator-bindings.json'
            common.host_guard = lambda: None  # Reach unchanged binding rejection without Linux/path requirement.
            for name in ('build.py', 'validate.py', 'stage.py', 'activate.py', 'post_readback.py'):
                phase = parent_tests.load_module('members_'+name[:-3], ops/name)
                argv = [str(ops/name)]
                if name == 'post_readback.py': argv += ['--reviewed-sha256', adapter.sha((ops/name).read_bytes())]
                with patch.object(sys, 'argv', argv), pytest.raises(RuntimeError, match='unbound'): phase.main()
                checked.append(name)
        finally:
            for name, value in saved.items():
                if value is None: sys.modules.pop(name, None)
                else: sys.modules[name] = value
        return dict(sourceHashes=adapter.PINNED, reviewedSourceHashes=adapter.SOURCE_PINS,
            generatedHashes=report['generatedHashes'], gitRevision=git_revision, missingFinalSources=sorted(missing),
            requiredBuildInputs=len(contract.required_inputs(names, blobs['Dockerfile'])),
            sourceMutationRejections=len(rejected), badFreezeRejections=len(bad_configs), proofRejections=proof_rejections,
            anonymous401Paths=list(dict.fromkeys(anonymous_paths)), anonymousCheckRequests=len(anonymous_paths),
            unboundEntrypointsRejected=checked, syntheticFreezeCount=9991,
            schemaChange=True, profile='household_members58', productionOperations=False, networkOrGeneratedProcessCalls=False)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--git-repo', type=Path, required=True); parser.add_argument('--git-revision', required=True)
    args = parser.parse_args()
    assert sys.dont_write_bytecode and not sys.flags.optimize
    print(json.dumps(check_pinned_local_operators(args.source_root, args.git_repo, args.git_revision), indent=2))
