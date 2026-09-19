"""Real Git/package baseline isolation and offline plan assembly."""
import json
import os
from pathlib import Path
import stat
import subprocess

import pytest
from deploy import steady_release_package as steady
from deploy import steady_release_plan as plan
from deploy import membership_release_package as shared
from deploy import membership_release_build as builder
from test_membership_release_package import environment, write, commit, ROOT, historical_fixed_blob


@pytest.fixture
def package_environment(environment):
    for name in (*plan.OPERATORS, 'steady_release_plan.py'):
        write(environment['repo'], 'deploy/' + name, (ROOT / 'deploy' / name).read_bytes())
    write(environment['repo'], 'Dockerfile', (ROOT / 'Dockerfile').read_bytes().replace(
        b'COPY finance_analysis.py finance_fx.py ./\n', b''))
    write(environment['repo'], 'inventory_sources.py', b'# synthetic inventory sources module\n')
    environment['commit'] = commit(environment['repo'])
    return environment


def test_real_package_cross_baseline_rejection_and_recursive_verification(package_environment, monkeypatch):
    seen = []
    original = shared.verify_package
    def verify(*args, **kwargs):
        seen.append(kwargs.get('baseline')); return original(*args, **kwargs)
    monkeypatch.setattr(shared, 'verify_package', verify)
    result = steady.prepare(**package_environment)
    checked = steady.verify_package(package_environment['output_dir'], result['packageSha256'])
    assert seen == [steady.BASELINE, steady.BASELINE]
    assert checked['metadata']['parentImage'] == steady.PARENT_IMAGE
    assert checked['metadata']['oldManifestSha256'] == steady.OLD_MANIFEST
    assert checked['metadata']['kind'] == 'steady-release-package'
    assert checked['metadata']['fixedFiles'] == shared.fixed_files(steady.BASELINE)
    assert checked['metadata']['runtimeFiles']['inventory_sources.py'] == shared.digest(
        checked['blobs']['inventory_sources.py'])
    with pytest.raises(ValueError):
        original(package_environment['output_dir'], result['packageSha256'])
    with pytest.raises(ValueError):
        original(package_environment['output_dir'], result['packageSha256'], baseline='memberships-r3-steady')
    with pytest.raises(ValueError):
        original(package_environment['output_dir'], result['packageSha256'], baseline='shopping-r1-steady')
    with pytest.raises(ValueError, match='unsupported release baseline'):
        original(package_environment['output_dir'], result['packageSha256'], baseline='arbitrary')


def test_recording_build_threads_fixed_baseline_and_parent(package_environment, tmp_path, monkeypatch):
    result = steady.prepare(**package_environment)
    value = steady.verify_package(package_environment['output_dir'], result['packageSha256'])
    seen, calls = [], []
    verify = builder.checked_package
    def checked(*args, **kwargs):
        seen.append(kwargs.get('baseline')); return verify(*args, **kwargs)
    monkeypatch.setattr(builder, 'checked_package', checked)
    image, container = 'sha256:' + '1' * 64, '2' * 64
    def docker(args, *, cwd=None, timeout=0):
        calls.append(args); raw = b''
        if args[:2] == ['image', 'inspect']:
            layers = ['parent'] + (['cleanup', 'copy'] if args[-1] == image else [])
            raw = shared.encoded([{'Id': args[-1], 'Config': {'User': 'dashboard'}, 'RootFS': {'Layers': layers}}])
        elif args[0] == 'build':
            assert (cwd / 'Dockerfile').read_text().startswith('FROM ' + steady.PARENT_IMAGE + '\n')
            assert (cwd / 'runtime/inventory_sources.py').read_bytes() == value['blobs']['inventory_sources.py']
            Path(args[args.index('--iidfile') + 1]).write_text(image)
        elif args[0] == 'create': raw = container.encode()
        elif args[0] == 'start': raw = shared.encoded(value['metadata']['runtimeFiles'])
        elif args[0] != 'rm': raise AssertionError(args)
        return subprocess.CompletedProcess(args, 0, raw, b'')
    built = steady.build(package_dir=package_environment['output_dir'], package_sha256=result['packageSha256'],
                         output_dir=tmp_path / 'image-build', runner=docker)
    assert built['parentImage'] == steady.PARENT_IMAGE and built['runtimeHashes'] == value['metadata']['runtimeFiles']
    assert seen == [steady.BASELINE, steady.BASELINE]
    assert calls[-1] == ['rm', '--force', container]


def test_recording_validation_rechecks_same_fixed_baseline(package_environment, tmp_path, monkeypatch):
    receipt = steady.prepare(**package_environment)
    value = steady.verify_package(package_environment['output_dir'], receipt['packageSha256'])
    meta = value['metadata']; node = 'tests/test_synthetic.py::test_one'
    selection = {'schemaVersion': 1, 'sourceHead': meta['sourceHead'], 'manifestSha256': meta['manifestSha256'],
                 'modules': ['tests/test_synthetic.py'], 'nodeids': [node], 'allowedSkips': {}}
    selection_path = tmp_path / 'selection.json'; selection_path.write_bytes(shared.encoded(selection))
    deps = tmp_path / 'dependencies'; write(deps, 'pytest/__init__.py', b'# recording fixture only\n')
    seen, mounted = [], {}
    original = builder.checked_package
    def checked(*args, **kwargs):
        seen.append(kwargs.get('baseline')); return original(*args, **kwargs)
    monkeypatch.setattr(builder, 'checked_package', checked)
    image, container = 'sha256:' + '1' * 64, '2' * 64
    def docker(args, **kwargs):
        raw = b''
        if args[:2] == ['image', 'inspect']:
            raw = shared.encoded([{'Id': image}])
        elif args[0] == 'create':
            for i, arg in enumerate(args):
                if arg == '--mount':
                    parts = dict(v.split('=', 1) for v in args[i + 1].split(',') if '=' in v)
                    mounted[parts['dst']] = Path(parts['src'])
            raw = container.encode()
        elif args[0] == 'start':
            request = json.loads((mounted['/validation-inputs'] / 'request.json').read_bytes())
            loaded = {n[:-3]: '/app/' + n for n in meta['runtimeFiles'] if '/' not in n and n.endswith('.py')}
            runtime = {'before': request['runtimeFiles'], 'after': request['runtimeFiles'],
                       'sourceBefore': request['sourceFiles'], 'sourceAfter': request['sourceFiles'],
                       'loadedBefore': loaded, 'loadedAfter': loaded, 'runtimeVerifiedBefore': True,
                       'runtimeVerifiedAfter': True, 'pytestExitCode': 0, 'deselected': [], 'collected': [node],
                       'reports': {node: [{'when': phase, 'outcome': 'passed', 'xfail': False}
                                          for phase in ('setup', 'call', 'teardown')]}}
            write(mounted['/proof'], 'runtime.json', shared.encoded(runtime))
            write(mounted['/proof'], 'results.xml', b'<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0"><testcase classname="tests.test_synthetic" name="test_one"/></testsuite></testsuites>')
        elif args[0] != 'rm': raise AssertionError(args)
        return subprocess.CompletedProcess(args, 0, raw, b'')
    result = steady.validate(package_dir=package_environment['output_dir'], package_sha256=receipt['packageSha256'],
        image_id=image, selection=selection_path, selection_sha256=shared.digest(selection_path.read_bytes()),
        output_dir=tmp_path / 'validation-run', pytest_dependencies=deps, runner=docker)
    assert result['allPassed'] is True and result['counts']['passed'] == 1
    assert seen == [steady.BASELINE, steady.BASELINE]


@pytest.fixture
def assembly(package_environment, tmp_path):
    receipt = steady.prepare(**package_environment)
    checked = steady.verify_package(package_environment['output_dir'], receipt['packageSha256'])
    meta, files = checked['metadata'], checked['manifest']['files']
    image = 'sha256:' + '1' * 64
    builddir, validationdir, reviewsdir = [tmp_path / n for n in ('build', 'validation', 'reviews')]
    for p in (builddir, validationdir, reviewsdir): p.mkdir()
    common = {'schemaVersion': 1, 'packageSha256': receipt['packageSha256'], 'sourceHead': meta['sourceHead'],
              'tree': meta['tree'], 'manifestSha256': meta['manifestSha256'], 'imageId': image, 'exitCode': 0}
    build = dict(common, parentImage=steady.PARENT_IMAGE, addedLayers=2, runtimeHashes=meta['runtimeFiles'])
    write(builddir, 'build.json', shared.encoded(build))
    selection = {'schemaVersion': 1, 'sourceHead': meta['sourceHead'], 'manifestSha256': meta['manifestSha256'],
                 'modules': ['tests/test_synthetic.py'], 'nodeids': ['tests/test_synthetic.py::test_one'], 'allowedSkips': {}}
    write(reviewsdir, 'selection.json', shared.encoded(selection))
    write(reviewsdir, 'review.json', shared.encoded({'kind': 'synthetic-only', 'reviewed': True}))
    reviews = {n: str(reviewsdir / n) for n in ('selection.json', 'review.json')}
    write(reviewsdir, 'files.json', shared.encoded(reviews))
    loaded = {n[:-3]: '/app/' + n for n in meta['runtimeFiles'] if '/' not in n and n.endswith('.py')}
    runtime = {'before': meta['runtimeFiles'], 'after': meta['runtimeFiles'], 'sourceBefore': files,
               'sourceAfter': files, 'loadedBefore': loaded, 'loadedAfter': loaded}
    write(validationdir, 'proof/runtime.json', shared.encoded(runtime))
    write(validationdir, 'proof/results.xml', b'<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0"><testcase classname="tests.test_synthetic" name="test_one"/></testsuite></testsuites>')
    validation = dict(common, allPassed=True, evidence={n: shared.digest((validationdir / n).read_bytes())
        for n in ('proof/results.xml', 'proof/runtime.json')}, junitPath='proof/results.xml', runtimePath='proof/runtime.json',
        selectionSha256=shared.digest((reviewsdir / 'selection.json').read_bytes()))
    write(validationdir, 'validation.json', shared.encoded(validation))
    return {'package_dir': package_environment['output_dir'], 'package_sha256': receipt['packageSha256'],
            'build_dir': builddir, 'build_sha256': shared.digest((builddir / 'build.json').read_bytes()),
            'validation_dir': validationdir, 'validation_sha256': shared.digest((validationdir / 'validation.json').read_bytes()),
            'reviews': reviewsdir / 'files.json', 'reviews_sha256': shared.digest((reviewsdir / 'files.json').read_bytes()),
            'candidate': tmp_path / 'candidate'}


def test_offline_assembly_binds_source_operators_and_evidence(assembly):
    result = plan.assemble(**assembly)
    assert result['assembled'] is True and result['reviewRequired'] is True and result['productionOperations'] is False
    operator = plan.controller.Controller(assembly['candidate'], result['planSha256'])
    assert operator.validate_evidence() == {'tests': 1, 'passed': 1, 'skipped': 0}
    with pytest.raises(plan.controller.ReleaseError, match='new_and_separate'):
        plan.assemble(**assembly)


def test_assembled_public_source_readable_by_container_uid_without_opening_private_files(assembly, monkeypatch):
    chmods = {}
    original = Path.chmod
    def chmod(path, mode, *args, **kwargs):
        chmods[path] = mode
        return original(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, 'chmod', chmod)
    plan.assemble(**assembly)
    source = assembly['candidate'] / 'source'
    for path in (source, *source.rglob('*')):
        expected = 0o755 if path.is_dir() else 0o644
        # Catch the regression on Windows too; its filesystem does not model
        # Linux owner/group bits. Actual uid-10001 access needs Linux rehearsal.
        assert chmods[path] == expected
        if os.name != 'nt':
            assert stat.S_IMODE(path.stat().st_mode) == expected
    for path in assembly['candidate'].rglob('*'):
        if path.is_file() and not path.is_relative_to(source):
            assert chmods.get(path) != 0o644
            if os.name != 'nt':
                assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize('changed', ['build', 'original', 'selection'])
def test_assembly_rejects_incomplete_or_changed_evidence(assembly, changed):
    if changed == 'build':
        path = assembly['build_dir'] / 'build.json'; value = json.loads(path.read_bytes()); value['parentImage'] = shared.PARENT_IMAGE
        path.write_bytes(shared.encoded(value)); assembly['build_sha256'] = shared.digest(path.read_bytes())
    elif changed == 'original':
        (assembly['validation_dir'] / 'proof/runtime.json').write_bytes(b'{}')
    else:
        path = assembly['reviews'].parent / 'selection.json'; value = json.loads(path.read_bytes()); value['nodeids'] = ['tests/test_synthetic.py::test_wrong']
        path.write_bytes(shared.encoded(value))
    with pytest.raises((ValueError, plan.controller.ReleaseError)):
        plan.assemble(**assembly)


@pytest.mark.parametrize('name', ['frontend/tests/inventoryFollowup.test.mjs', 'frontend/tests/inventorySources.test.mjs'])
def test_explicit_inventory_test_input_is_packaged_without_opening_other_frontend_paths(package_environment, name):
    env = package_environment
    write(env['repo'], name, b'// synthetic followup test input\n')
    env['commit'] = commit(env['repo'])
    evidence = json.loads(env['build_evidence'].read_text())
    evidence.update(head=env['commit'], tree=subprocess.check_output(
        ['git', 'rev-parse', 'HEAD^{tree}'], cwd=env['repo']).decode().strip())
    evidence['inputFiles'][name] = shared.digest((env['repo'] / name).read_bytes())
    env['build_evidence'].write_bytes(shared.encoded(evidence))
    env['evidence_sha256'] = shared.digest(env['build_evidence'].read_bytes())
    result = steady.prepare(**env)
    verified = steady.verify_package(env['output_dir'], result['packageSha256'])
    assert verified['blobs'][name] == b'// synthetic followup test input\n'
    tracked = shared.tracked_files(env['repo'], env['commit'])
    with pytest.raises(ValueError, match='new frontend input needs an explicit packaging policy'):
        shared.selected_sources(tracked | {'frontend/tests/unreviewed.mjs'},
                                (env['repo'] / 'deploy/prepare_release.py').read_bytes(), baseline=steady.BASELINE)


@pytest.mark.parametrize('baseline', [None, 'memberships-r3-steady', 'shopping-r1-steady'])
def test_historical_baselines_keep_original_docker_and_do_not_admit_new_test_input(environment, baseline):
    result = shared.prepare(**environment, baseline=baseline)
    verified = shared.verify_package(environment['output_dir'], result['packageSha256'], baseline=baseline)
    assert verified['metadata']['fixedFiles'] == shared.FIXED
    assert verified['blobs']['Dockerfile'] == historical_fixed_blob('Dockerfile')
    assert 'inventory_sources.py' not in verified['metadata']['runtimeFiles']
    with pytest.raises(ValueError):
        steady.verify_package(environment['output_dir'], result['packageSha256'])
    with pytest.raises(ValueError, match='new frontend input needs an explicit packaging policy'):
        shared.selected_sources(set(verified['metadata']['sourceFiles']) | {'frontend/tests/inventorySources.test.mjs'},
                                verified['blobs']['deploy/prepare_release.py'], baseline=baseline)


@pytest.mark.parametrize('fault', ['missing-module', 'old-docker', 'extra-docker-command', 'extra-copy-module'])
def test_new_baseline_requires_module_and_exact_docker_bytes_before_creating_output(package_environment, fault):
    env = package_environment
    if fault == 'missing-module':
        (env['repo'] / 'inventory_sources.py').unlink()
    else:
        docker = (env['repo'] / 'Dockerfile').read_bytes()
        if fault == 'old-docker':
            docker = historical_fixed_blob('Dockerfile')
        elif fault == 'extra-docker-command':
            docker += b'RUN echo unreviewed\n'
        else:
            docker = docker.replace(b'inventory_sources.py ./', b'inventory_sources.py unreviewed.py ./')
        write(env['repo'], 'Dockerfile', docker)
    env['commit'] = commit(env['repo'])
    with pytest.raises(ValueError, match='allowlisted file missing' if fault == 'missing-module' else 'dependency/config pin'):
        steady.prepare(**env)
    assert not env['output_dir'].exists()


def test_fixed_baseline_pins_are_isolated():
    assert steady.BASELINE == 'followup-r1-steady'
    assert steady.PARENT_IMAGE == 'sha256:8e7092a44ba311f6ac333500cfab2c6dcf5137484cf02d9aca1f52590963815c'
    assert steady.OLD_MANIFEST == 'd926bba0c7fc7374f8b0c0d6b661f51b5a0a15029428bfa016e92b750ddbd85c'
    historical = historical_fixed_blob('Dockerfile')
    candidate = (ROOT / 'Dockerfile').read_bytes().replace(b'COPY finance_analysis.py finance_fx.py ./\n', b'')
    assert historical.count(shared.INVENTORY_COPY_BEFORE) == 1
    assert candidate == historical.replace(shared.INVENTORY_COPY_BEFORE, shared.INVENTORY_COPY_AFTER, 1)
    fixed = shared.fixed_files(steady.BASELINE)
    assert {n for n in shared.FIXED if shared.FIXED[n] != fixed[n]} == {'Dockerfile'}
    fixed['requirements.txt'] = '0' * 64
    assert shared.fixed_files(steady.BASELINE)['requirements.txt'] == shared.FIXED['requirements.txt']
