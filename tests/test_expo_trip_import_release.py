"""Trip import release guards; optional CLI checks actual pinned local operators without deployment."""
from __future__ import annotations

import ast
import copy
import json
from pathlib import Path
import socket
import sys
import tempfile
from unittest.mock import patch

import pytest

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy.expo_trip_import_release import prepare as adapter
from tests import test_expo_trip_recap_release as parent_tests


def test_only_reviewed_journey_backend_can_change():
    assert set(adapter.previous.BACKEND_UNCHANGED) - set(adapter.BACKEND_UNCHANGED) == {'journey_workflows.py'}
    assert set(adapter.previous.UNCHANGED) - set(adapter.UNCHANGED) == {'journey_workflows.py'}
    assert set(adapter.BACKEND_UNCHANGED) - set(adapter.previous.BACKEND_UNCHANGED) == {'household_media.py'}
    assert set(adapter.UNCHANGED) - set(adapter.previous.UNCHANGED) == {'household_media.py'}
    assert isinstance(adapter.JOURNEY_SOURCE_SHA256, str) and len(adapter.JOURNEY_SOURCE_SHA256) == 64
    assert len(adapter.BACKEND_UNCHANGED) == 37
    scope = {'need': adapter.need, 'manifest': {'journey_workflows.py': adapter.JOURNEY_SOURCE_SHA256}}
    exec(adapter.JOURNEY_GUARD.strip(), scope)
    for wrong in (None, '0' * 64, adapter.JOURNEY_SOURCE_SHA256 + '0'):
        scope['manifest'] = {'journey_workflows.py': wrong}
        with pytest.raises(RuntimeError, match='Reviewed journey session source changed'):
            exec(adapter.JOURNEY_GUARD.strip(), scope)
    assert len(adapter.REQUIRED_TESTS) == 12
    assert not (adapter.REQUIRED_CHANGED | adapter.REQUIRED_ADDED) & set(adapter.UNCHANGED)


def test_changed_pinned_source_and_generation_race_leave_no_output(tmp_path, monkeypatch):
    raw = b'# synthetic\r\n'; (tmp_path / 'original.py').write_bytes(raw)
    monkeypatch.setattr(adapter, 'PINNED', {'original.py': adapter.sha(raw)})
    assert adapter.read_sources(tmp_path) == {'original.py': b'# synthetic\n'}
    def drift(*_):
        (tmp_path / 'original.py').write_bytes(b'# changed\n'); return {}
    monkeypatch.setattr(adapter, 'adapt', drift)
    output = tmp_path / 'expo-trip-import-tools-synthetic'
    with pytest.raises(RuntimeError, match='checksum'): adapter.prepare(tmp_path, output)
    assert not output.exists()


def test_output_cannot_overwrite_or_escape_source_root(tmp_path, monkeypatch):
    raw = b'# synthetic\n'; (tmp_path / 'original.py').write_bytes(raw)
    monkeypatch.setattr(adapter, 'PINNED', {'original.py': adapter.sha(raw)})
    monkeypatch.setattr(adapter, 'adapt', lambda *_: {'operators/build.py': b'raise RuntimeError("unbound")\n'})
    output = tmp_path / 'expo-trip-import-tools-synthetic'
    result = adapter.prepare(tmp_path, output)
    assert not result['bound'] and not result['productionOperations'] and not result['schemaChange']
    assert result['householdTablesBefore'] == result['householdTablesAfter'] == 58
    assert not (output / 'operators/operator-bindings.json').exists()
    with pytest.raises(RuntimeError, match='exists'): adapter.prepare(tmp_path, output)
    with pytest.raises(RuntimeError): adapter.prepare(tmp_path, tmp_path.parent / output.name)
    with pytest.raises(RuntimeError): adapter.prepare(tmp_path, tmp_path / 'expo-photo-suggestions-tools-replay')


@pytest.mark.parametrize('code', ['migrate(root)', 'create_app(config)', 'initialize_database(a,b)',
    "program='con.executescript(sql)'", "program=\"con.execute('DROP TABLE x')\""])
def test_no_migration_or_initialization_allowed(code):
    with pytest.raises(RuntimeError): adapter.verify_generated(code, 'operators/activate.py')


def check_pinned_local_operators(source_root):
    """Exercise actual generated source, freeze, and absent-binding guards locally."""
    inputs = adapter.read_sources(source_root)
    def deny(*_args, **_kwargs): raise AssertionError('No process or network in operator review')
    with tempfile.TemporaryDirectory(prefix='trip-import-release-check-') as folder, \
         patch('subprocess.run', deny), patch('subprocess.Popen', deny), \
         patch('subprocess.check_output', deny), patch('socket.create_connection', deny), \
         patch.object(socket.socket, 'connect', deny):
        access = Path(folder).resolve()
        for name in adapter.PINNED:
            path = access / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((source_root / name).read_bytes())
        output = access / 'expo-trip-import-tools-synthetic'
        report = adapter.prepare(access, output)
        generated = {name: (output / name).read_bytes() for name in report['generatedHashes']}
        for name, raw in generated.items():
            assert adapter.sha(raw) == report['generatedHashes'][name]
            adapter.verify_generated(raw, name)
        # Schema/startup preservation and validation mechanics remain the published bytes.
        for name in ('validate.py', 'stage.py'):
            assert generated['operators/' + name] == inputs[adapter.BASE + 'operators/' + name]
        for name in ('build.py', 'activate.py', 'post_readback.py'):
            old = inputs[adapter.BASE + 'operators/' + name].decode()
            assert generated['operators/' + name].decode() == old.replace('expo-photo-suggestions', 'expo-trip-import').replace('photo suggestions', 'trip imports')
        parent_tests.check_activation_evidence(generated['operators/post_readback.py'].decode())
        rejected = []
        for name, function in (('operators/ops_common.py', 'source_state'), ('prepare-package.py', 'inspect_inputs')):
            tree = ast.parse(generated[name])
            body = next(n.body for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == function)
            loop = next(n for n in body if isinstance(n, ast.For) and isinstance(n.iter, ast.Tuple)
                        and all(isinstance(v, ast.Constant) for v in n.iter.elts))
            assert ast.literal_eval(loop.iter) == adapter.UNCHANGED
            pinned = next(n for n in body if isinstance(n, ast.Expr) and 'Reviewed journey session source changed' in ast.unparse(n))
            media = next(n for n in body if isinstance(n, ast.Expr) and 'Reviewed photo session source changed' in ast.unparse(n))
            program = compile(ast.fix_missing_locations(ast.Module(body=[loop, media, pinned], type_ignores=[])), name, 'exec')
            old = {path: 'a' * 64 for path in adapter.UNCHANGED}
            old['household_media.py'] = adapter.previous.MEDIA_SOURCE_SHA256
            manifest = {**old, 'journey_workflows.py': adapter.JOURNEY_SOURCE_SHA256}
            scope = {'need': adapter.need, 'old': old, 'manifest': manifest}
            exec(program, scope)
            for path in (*adapter.UNCHANGED, 'journey_workflows.py'):
                scope['manifest'] = {**manifest, path: '0' * 64}
                with pytest.raises(RuntimeError): exec(program, scope)
                rejected.append(name + ':' + path)
        package = parent_tests.load_module('trip_import_package_guard', output / 'prepare-package.py')
        with patch.object(parent_tests, 'adapter', adapter):
            config = parent_tests.synthetic_config(access)
        assert package.validate_config(config) == config
        for field, bad in [('oldManifestSha256', adapter.previous.OLD_MANIFEST),
                           ('oldArchiveSha256', adapter.previous.OLD_ARCHIVE),
                           ('parentImage', adapter.previous.PARENT_IMAGE), ('expectedTestCount', True)]:
            changed = copy.deepcopy(config); changed[field] = bad
            with pytest.raises(RuntimeError): package.validate_config(changed)
        for field, required in [('validationTests', adapter.REQUIRED_TESTS),
                                ('changedFiles', adapter.REQUIRED_CHANGED), ('addedFiles', adapter.REQUIRED_ADDED)]:
            for item in required:
                changed = copy.deepcopy(config); changed[field].remove(item)
                with pytest.raises(RuntimeError): package.validate_config(changed)
        freeze = access / 'freeze.json'; freeze.write_text(json.dumps(config))
        frozen = access / 'expo-trip-import-tools-frozen'
        frozen_report = adapter.prepare(access, frozen, freeze)
        assert frozen_report['expectedTestCount'] == 9991  # Synthetic, never a real collection count.
        operator_dir = frozen / 'operators'
        saved = {name: sys.modules.get(name) for name in ('expo_contract', 'ops_common')}
        checked = []
        try:
            contract = parent_tests.load_module('trip_import_contract_guard', operator_dir / 'expo_contract.py')
            sys.modules['expo_contract'] = contract
            common = parent_tests.load_module('trip_import_common_guard', operator_dir / 'ops_common.py')
            sys.modules['ops_common'] = common
            common.CANDIDATE = operator_dir; common.BINDING_PATH = operator_dir / 'operator-bindings.json'
            common.host_guard = lambda: None  # Reach actual binding check past Linux-only location check.
            for name in ('build.py', 'validate.py', 'stage.py', 'activate.py', 'post_readback.py'):
                value = parent_tests.load_module('trip_import_' + name[:-3], operator_dir / name)
                argv = [str(operator_dir / name)]
                if name == 'post_readback.py': argv += ['--reviewed-sha256', adapter.sha((operator_dir / name).read_bytes())]
                with patch.object(sys, 'argv', argv), pytest.raises(RuntimeError, match='unbound'):
                    value.main()
                checked.append(name)
        finally:
            for name, value in saved.items():
                if value is None: sys.modules.pop(name, None)
                else: sys.modules[name] = value
        return dict(sourceHashes=adapter.PINNED, generatedHashes=report['generatedHashes'],
                    preservedBackendFiles=37, reviewedJourneySourceSha256=adapter.JOURNEY_SOURCE_SHA256,
                    sourceMutationRejections=len(rejected), unboundEntrypointsRejected=checked,
                    productionOperations=False, networkOrProcessCalls=False,
                    syntheticFreezeCount=9991, schemaChange=False)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    args = parser.parse_args()
    assert sys.dont_write_bytecode and not sys.flags.optimize
    print(json.dumps(check_pinned_local_operators(args.source_root), indent=2))
