"""Synthetic adapter checks; explicit CLI additionally checks private pinned originals.

The CLI uses temporary files and blocks all generated process/network calls.
It does not bind, package the application, connect to servers or run production.
"""
from __future__ import annotations

import ast
import copy
import importlib.util
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
from deploy.expo_appearance_release import prepare as adapter


def test_pinned_bytes_and_unsafe_paths_are_rejected(tmp_path, monkeypatch):
    raw = b'# synthetic\r\n'; (tmp_path / 'source.py').write_bytes(raw)
    monkeypatch.setattr(adapter, 'PINNED', {'source.py': adapter.sha(raw)})
    assert adapter.read_sources(tmp_path) == {'source.py': b'# synthetic\n'}
    (tmp_path / 'source.py').write_bytes(b'# synthetic\n')
    with pytest.raises(RuntimeError, match='checksum'): adapter.read_sources(tmp_path)
    for path in (Path('relative'), tmp_path / '..' / 'escape'):
        with pytest.raises(RuntimeError): adapter.safe_path(path, exists=False)


def test_new_output_is_confined_exclusive_and_unbound(tmp_path, monkeypatch):
    raw = b'# original\n'; (tmp_path / 'source.py').write_bytes(raw)
    monkeypatch.setattr(adapter, 'PINNED', {'source.py': adapter.sha(raw)})
    monkeypatch.setattr(adapter, 'adapt', lambda *_: {'operators/build.py': b'raise RuntimeError("unbound")\n'})
    output = tmp_path / 'expo-appearance-tools-synthetic'
    result = adapter.prepare(tmp_path, output)
    assert result['bound'] is False and result['schemaChange'] is False
    assert result['householdTablesBefore'] == result['householdTablesAfter'] == 55
    assert result['expectedTestCount'] is None and result['productionOperations'] is False
    assert not (output / 'operator-bindings.json').exists()
    with pytest.raises(RuntimeError, match='exists'): adapter.prepare(tmp_path, output)
    with pytest.raises(RuntimeError): adapter.prepare(tmp_path, tmp_path.parent / output.name)
    with pytest.raises(RuntimeError): adapter.prepare(tmp_path, tmp_path / 'trip-coordination-tools-replay')


def test_input_race_fails_before_any_output(tmp_path, monkeypatch):
    raw = b'# original\n'; (tmp_path / 'source.py').write_bytes(raw)
    monkeypatch.setattr(adapter, 'PINNED', {'source.py': adapter.sha(raw)})
    def drift(*_):
        (tmp_path / 'source.py').write_bytes(b'# changed\n'); return {}
    monkeypatch.setattr(adapter, 'adapt', drift)
    output = tmp_path / 'expo-appearance-tools-synthetic'
    with pytest.raises(RuntimeError, match='checksum'): adapter.prepare(tmp_path, output)
    assert not output.exists()


@pytest.mark.parametrize('damage', ['outside', 'large', 'duplicate'])
def test_invalid_freeze_never_evaluates_generated_code(tmp_path, damage):
    root = tmp_path / 'access'; root.mkdir()
    path = (tmp_path if damage == 'outside' else root) / 'freeze.json'
    path.write_bytes(b'x' * 2_000_001 if damage == 'large' else b'{"main":1,"main":2}')
    with pytest.raises(RuntimeError):
        adapter.freeze_config(path, root, {'prepare-package.py': b'raise AssertionError("must not execute")'})


@pytest.mark.parametrize('code', ['migrate(root)', 'verify_addition(a,b,c)', 'initialize_database(a,b)',
                                  'create_app(config)', "program='con.executescript(sql)'",
                                  "program=\"con.execute('CREATE TABLE x(y)')\""])
def test_generated_program_refuses_migration_and_ddl(code):
    with pytest.raises(RuntimeError): adapter.verify_generated(code, 'synthetic.py')


def test_required_scope_covers_appearance_auth_hosting_and_preservation():
    assert adapter.REQUIRED_TESTS == {
        'tests/test_member_preferences.py', 'tests/test_member_sessions.py',
        'tests/test_household_spaces.py', 'tests/test_dashboard_layout.py',
        'tests/test_dashboard_layout_sessions.py', 'tests/test_frontend_runtime.py',
        'tests/test_platform_backup.py', 'tests/test_investment_operation_migration.py',
        'tests/test_expo_appearance_release.py',
    }
    assert {'household_spaces.py', 'frontend/src/app/_layout.tsx', 'static/product-shell.js'} <= adapter.REQUIRED_CHANGED
    assert {'frontend/src/screens/AppearancePanel.tsx', 'tests/browser_expo_appearance_check.py'} <= adapter.REQUIRED_ADDED
    assert not adapter.REQUIRED_ADDED & adapter.REQUIRED_CHANGED
    assert not (adapter.REQUIRED_ADDED | adapter.REQUIRED_CHANGED) & set(adapter.UNCHANGED)
    removed = set(adapter.previous.UNCHANGED) - set(adapter.UNCHANGED)
    assert removed == {'household_spaces.py', 'frontend/src/app/_layout.tsx'}
    assert set(adapter.UNCHANGED) - set(adapter.previous.UNCHANGED) == {'dashboard_preferences.py'}
    assert {'Dockerfile', 'finance_hub.py', 'investment_operations.py', 'deploy/backup.py',
            'calendar_publish.py', 'journey_places.py', 'journey_reschedule.py', 'media_playback.py',
            'tv_display.py', 'app.py', 'frontend_runtime.py', 'dashboard_preferences.py',
            'frontend/src/app/tv.tsx', 'frontend/src/screens/TVScreen.tsx', 'frontend/src/lib/tv.ts',
            'frontend/src/ui/TVBoard.tsx', 'frontend/src/ui/TVBoard.model.ts',
            'frontend/src/ui/TVPhotoPlayer.tsx', 'frontend/src/ui/TVPhotoPlayer.web.tsx',
            'frontend/src/ui/TVPhotoPlayer.model.ts'} <= set(adapter.UNCHANGED)
    assert len(adapter.PINNED) == 9 and len(set(adapter.PINNED.values())) == 9


@pytest.mark.parametrize('damage', ['extra_line', 'normalize_all', 'extra_copy', 'wrong_module', 'new_image', 'remove_line', 'both_changed'])
def test_dockerfile_must_remain_byte_identical(damage):
    old = b'FROM fixed-parent\r\nCOPY journey_reschedule.py ./\nCOPY app.py ./\r\n'
    new = old
    ns = {'need': adapter.need}; exec(adapter.DOCKER_CONTRACT, ns)
    ns['verify_docker_delta'](old, new)
    bad_old, bad_new = old, new
    if damage == 'extra_line': bad_new += b'\n'
    elif damage == 'normalize_all': bad_new = new.replace(b'\r\n', b'\n')
    elif damage == 'extra_copy': bad_new += b'COPY secret ./\n'
    elif damage == 'wrong_module': bad_new = new.replace(b'journey_reschedule.py', b'other.py')
    elif damage == 'new_image': bad_new = new.replace(b'fixed-parent', b'other-image')
    elif damage == 'remove_line': bad_new = new.replace(b'COPY app.py ./\r\n', b'')
    else: bad_old = old + b'# old\n'; bad_new = new + b'# new\n'
    with pytest.raises(RuntimeError): ns['verify_docker_delta'](bad_old, bad_new)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


def synthetic_config(access):
    file = access / 'synthetic-input'; file.write_bytes(b'synthetic')
    return dict(schemaVersion=1, main='1' * 40, integration='2' * 40, tree='3' * 40,
        buildEvidencePath=str(file), testedBuildEvidencePath=str(file), exportDirectory=str(access),
        buildEvidenceSha256='a' * 64, testedBuildEvidenceSha256='b' * 64,
        oldArchivePath=str(file), oldArchiveSha256=adapter.OLD_ARCHIVE,
        oldManifestSha256=adapter.OLD_MANIFEST, parentImage=adapter.PARENT_IMAGE,
        oldImages={**{name: adapter.PARENT_IMAGE for name in ('app', 'sync', 'media')},
                   'web': 'sha256:1ae82dcc4a34bcd976195b3c4c5a6b7e569505527a1e2a28c2101e032159a5c7'},
        envSha256='a72d456815cf113b1ac0c1e032ac8c45b300ccf2cb499520c14b7f54d5314e07',
        migrationSqlSha256='c' * 64, validationTests=sorted(adapter.REQUIRED_TESTS), expectedTestCount=9991,
        changedFiles=sorted(adapter.REQUIRED_CHANGED), addedFiles=sorted(adapter.REQUIRED_ADDED), removedFiles=[])


def check_pinned_local_operators(source_root, git_repo, git_revision):
    """Inspect actual generated guards, never a replacement implementation."""
    inputs = adapter.read_sources(source_root)
    archive = adapter.safe_path(source_root / adapter.BASE / 'package/release.tar.gz')
    raw = archive.read_bytes(); assert adapter.sha(raw) == adapter.OLD_ARCHIVE
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as packed:
        manifest_raw = packed.extractfile('RELEASE-MANIFEST.json').read()
        assert adapter.sha(manifest_raw) == adapter.OLD_MANIFEST
        manifest = json.loads(manifest_raw)['files']
        old_docker = packed.extractfile('Dockerfile').read()
        assert adapter.sha(old_docker) == manifest['Dockerfile']
    assert re.fullmatch('[0-9a-f]{40}', git_revision)
    docker = subprocess.run(['git', '-C', str(adapter.safe_path(git_repo)), 'show', git_revision + ':Dockerfile'],
                            check=True, capture_output=True).stdout
    def deny(*_args, **_kwargs): raise AssertionError('Generated operator attempted an external action')
    with tempfile.TemporaryDirectory(prefix='expo-appearance-guards-') as folder:
        access = Path(folder).resolve()
        for name in adapter.PINNED:
            target = access / name; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((source_root / name).read_bytes())
        output = access / 'expo-appearance-tools-synthetic'; report = adapter.prepare(access, output)
        operator_dir = output / 'operators'
        contract = load_module('trip_contract_test', operator_dir / 'expo_contract.py')
        contract.verify_docker_delta(old_docker, docker)
        expected_paths = contract.runtime_paths(docker, set(manifest))
        assert {'journey_reschedule.py', 'media_playback.py', 'tv_display.py'} <= expected_paths
        validation = inputs[adapter.BASE + 'operators/validate.py']
        assert b"'--memory','896m'" in validation and b'/tmp:rw,size=671088640,mode=1777' in validation
        with pytest.raises(RuntimeError): contract.verify_docker_delta(old_docker, docker + b'\n')
        # Stage and the successful 896/640 validation resources remain byte-identical.
        for name in ('stage.py', 'validate.py', 'expo_contract.py'):
            assert (operator_dir / name).read_bytes() == inputs[adapter.BASE + 'operators/' + name]
        for name in ('activate.py', 'post_readback.py'):
            original = inputs[adapter.BASE + 'operators/' + name].replace(b'expo-home-layout', b'expo-appearance')
            assert (operator_dir / name).read_bytes() == original
        post = (operator_dir / 'post_readback.py').read_text()
        assert "'/app/tv','/tv'" in post and "'/tv?classic=1'" in post
        assert "TV did not redirect to Expo display" in post
        package = load_module('trip_package_test', output / 'prepare-package.py')
        config = synthetic_config(access); assert package.validate_config(config) == config
        # A real final-freeze generation must retain its explicit selection/count;
        # 9991 here is deliberately synthetic, never a collected production count.
        freeze = access / 'synthetic-freeze.json'; freeze.write_text(json.dumps(config))
        frozen_output = access / 'expo-appearance-tools-frozen-synthetic'
        frozen = adapter.prepare(access, frozen_output, freeze)
        assert frozen['finalFreezeProvided'] and frozen['bound'] is False
        assert frozen['expectedTestCount'] == 9991 and frozen['freezeSha256'] == adapter.sha(freeze.read_bytes())
        frozen_common = ast.parse((frozen_output / 'operators/ops_common.py').read_text())
        constants = {node.targets[0].id: ast.literal_eval(node.value) for node in frozen_common.body
                     if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                     and node.targets[0].id in ('EXPECTED_TEST_COUNT', 'EXPECTED_TESTS')}
        assert constants == {'EXPECTED_TEST_COUNT': 9991, 'EXPECTED_TESTS': tuple(config['validationTests'])}
        rejected = []
        for key, bad in [('oldManifestSha256', adapter.previous.OLD_MANIFEST),
                         ('oldArchiveSha256', adapter.previous.OLD_ARCHIVE),
                         ('parentImage', adapter.previous.PARENT_IMAGE)]:
            changed = copy.deepcopy(config); changed[key] = bad
            if key == 'parentImage': changed['oldImages'].update({name: bad for name in ('app', 'sync', 'media')})
            with pytest.raises(RuntimeError): package.validate_config(changed)
            rejected.append(key)
        for key, required in [('validationTests', adapter.REQUIRED_TESTS), ('changedFiles', adapter.REQUIRED_CHANGED),
                              ('addedFiles', adapter.REQUIRED_ADDED)]:
            for item in sorted(required):
                changed = copy.deepcopy(config); changed[key].remove(item)
                with pytest.raises(RuntimeError): package.validate_config(changed)
                rejected.append(key + ':' + item)
        for name in adapter.FORBIDDEN_TESTS:
            changed = copy.deepcopy(config); changed['validationTests'].append(name)
            with pytest.raises(RuntimeError): package.validate_config(changed)
            rejected.append('forbiddenTest:' + name)
        for count in (0, True, 10_000):
            changed = copy.deepcopy(config); changed['expectedTestCount'] = count
            with pytest.raises(RuntimeError): package.validate_config(changed)
            rejected.append('expectedTestCount:' + str(count))
        # Nonempty receipt preservation is the previous independently tested exact program.
        activation = (operator_dir / 'activate.py').read_text()
        assert "report.pop('productionWrites', None)" in activation
        assert "need(after==before," in activation and "'originalTablesPreserved':55,'newTables':0" in activation
        assert all(term not in activation for term in ('after-migration.json', 'migrationResult', 'migrate('))
        checked = []; previous = {name: sys.modules.get(name) for name in ('expo_contract', 'ops_common')}
        try:
            sys.modules['expo_contract'] = contract
            common = load_module('trip_common_test', operator_dir / 'ops_common.py'); sys.modules['ops_common'] = common
            common.CANDIDATE = operator_dir; common.BINDING_PATH = operator_dir / 'operator-bindings.json'
            common.host_guard = lambda: None  # Reach actual absent-binding guard past Linux location validation.
            with patch('subprocess.run', deny), patch('subprocess.Popen', deny), patch('subprocess.check_output', deny), \
                 patch('socket.create_connection', deny), patch.object(socket.socket, 'connect', deny):
                for name in ('build.py', 'validate.py', 'stage.py', 'activate.py', 'post_readback.py'):
                    value = load_module('trip_' + name.removesuffix('.py'), operator_dir / name)
                    argv = [str(operator_dir / name)]
                    if name == 'post_readback.py': argv += ['--reviewed-sha256', adapter.sha((operator_dir / name).read_bytes())]
                    with patch.object(sys, 'argv', argv), pytest.raises(RuntimeError, match='unbound'): value.main()
                    checked.append(name)
                for name in ('prepare-package.py', 'bind-release.py'):
                    value = load_module('trip_' + name.replace('-', '_').removesuffix('.py'), output / name)
                    missing = output / 'absent.json'
                    argv = [str(output / name), '--freeze', str(missing)] if name == 'prepare-package.py' else [str(output / name), '--operator-review', str(missing), '--operator-review-sha256', 'a' * 64]
                    with patch.object(sys, 'argv', argv), pytest.raises(RuntimeError): value.main()
                    checked.append(name)
        finally:
            for name, module in previous.items():
                if module is None: sys.modules.pop(name, None)
                else: sys.modules[name] = module
        for name, digest in report['generatedHashes'].items():
            raw = (output / name).read_bytes(); assert adapter.sha(raw) == digest; adapter.verify_generated(raw, name)
        return dict(pinnedSources=adapter.PINNED, generatedHashes=report['generatedHashes'],
            unboundRejected=checked, freezeRejected=rejected, actualDockerArchiveSha256=adapter.OLD_ARCHIVE,
            actualDockerUnchanged=docker == old_docker, gitRevision=git_revision,
            preservationStageValidationUnchanged=True, recursiveGeneratedSyntaxVerified=True,
            syntheticFinalFreezeSelectionAndCountVerified=True,
            validationMemoryMiB=896, validationTmpfsMiB=640,
            productionOperations=False, unboundNetworkOrProcessActions=False)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--git-repo', type=Path, required=True)
    parser.add_argument('--git-revision', required=True)
    args = parser.parse_args()
    assert sys.dont_write_bytecode and not sys.flags.optimize
    print(json.dumps(check_pinned_local_operators(args.source_root, args.git_repo, args.git_revision), indent=2))
