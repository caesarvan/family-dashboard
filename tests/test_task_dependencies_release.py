"""Fixed 97-file preservation and recorded 69/9 lifecycle; no Docker/network."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
import os

import pytest
from deploy import build_task_dependencies_release as package
from deploy import activate_task_dependencies_release as controller
from deploy import build_assistant_document_search_release as previous_package
from deploy import activate_assistant_document_search_release as previous_controller
from deploy import membership_release_package as policy
from deploy import membership_release_controller as common
from deploy import assistant_trip_change_release_controller as core
import test_journey_routes_release as routes
import test_assistant_trip_change_release as lifecycle
import test_steady_release_package as package_tests
from test_assistant_trip_change_release import steady_simulation, old_simulation
from test_membership_release_package import ROOT, write


def parent_docker():
    raw = (ROOT / 'Dockerfile').read_bytes()
    assert policy.digest(raw) == package.DOCKER_AFTER and raw.count(package.COPY_AFTER) == 1
    old = raw.replace(package.COPY_AFTER, package.COPY_BEFORE, 1)
    assert policy.digest(old) == package.DOCKER_BEFORE == previous_package.DOCKER_AFTER
    return old


@pytest.fixture
def package_environment(tmp_path, monkeypatch):
    # Reconstruct only the new COPY addition before the existing historical
    # fixture verifies its original immutable Docker digest. No Git history.
    monkeypatch.setattr(routes, 'new_docker', parent_docker)
    env = routes.environment.__wrapped__(tmp_path, monkeypatch)
    repo = env['repo']
    for name in controller.SPEC.operators:
        write(repo, 'deploy/' + name, (ROOT / 'deploy' / name).read_bytes())
    write(repo, 'Dockerfile', (ROOT / 'Dockerfile').read_bytes())
    runtime = {p.name for p in repo.glob('*.py')} | package.RUNTIME_ADDITIONS | {'requirements.txt'}
    runtime |= {p.relative_to(ROOT).as_posix() for p in (ROOT / 'static').rglob('*')
                if p.is_file() and not p.relative_to(ROOT).as_posix().startswith(policy.PREFIX)}
    for name in runtime:
        write(repo, name, (ROOT / name).read_bytes())
    kept = {n: policy.digest((repo / n).read_bytes()) for n in runtime if n not in package.CHANGED_RUNTIME_FILES}
    assert len(runtime) == package.NON_EXPO_RUNTIME_COUNT == 105
    assert len(kept) == package.PRESERVED_RUNTIME_COUNT == 97
    assert policy.digest(policy.encoded(kept)) == package.PRESERVED_RUNTIME_SHA256
    for name in package.FRONTEND_TESTS:
        write(repo, name, b'// synthetic frontend test\n')
    for name in package.BROWSER_SCRIPTS:
        write(repo, name, (ROOT / name).read_bytes())
    routes.refresh_evidence(env)
    return env


def test_roundtrip_exact_runtime_frontend_and_single_browser_script(package_environment):
    env = package_environment
    for name in package.CHANGED_RUNTIME_FILES:
        write(env['repo'], name, (env['repo'] / name).read_bytes() + b'\n# reviewed synthetic delta\n')
    write(env['repo'], 'scripts/unreviewed.py', b'# must not enter package\n')
    routes.refresh_evidence(env)
    result = package.prepare(**env)
    checked = package.verify_package(env['output_dir'], result['packageSha256'])
    meta = checked['metadata']
    assert (meta['kind'], meta['parentImage'], meta['oldManifestSha256']) == (package.KIND, package.PARENT_IMAGE, package.OLD_MANIFEST)
    kept = {n: h for n, h in meta['runtimeFiles'].items() if not n.startswith(policy.PREFIX) and n not in package.CHANGED_RUNTIME_FILES}
    assert len(kept) == 97 and policy.digest(policy.encoded(kept)) == package.PRESERVED_RUNTIME_SHA256
    assert package.RUNTIME_ADDITIONS - previous_package.RUNTIME_ADDITIONS == {'task_dependencies.py'}
    assert package.FRONTEND_TESTS - previous_package.FRONTEND_TESTS == {'frontend/tests/taskDependencies.test.mjs'}
    assert package.FRONTEND_TESTS <= meta['sourceFiles'].keys()
    assert {n for n in meta['sourceFiles'] if n.startswith('scripts/')} == package.BROWSER_SCRIPTS
    assert meta['fixedFiles'] == {**policy.FIXED, 'Dockerfile': package.DOCKER_AFTER}
    for baseline in (None, previous_package.BASELINE):
        with pytest.raises(ValueError): policy.verify_package(env['output_dir'], result['packageSha256'], baseline=baseline)
    with pytest.raises(ValueError, match='output must be new'): package.prepare(**env)


@pytest.mark.parametrize('fault', ['other-backend', 'legacy-static', 'add-static', 'remove-static',
    'requirements', 'missing-module', 'missing-new-test', 'missing-old-test', 'missing-browser',
    'unknown-frontend-test', 'old-docker', 'extra-copy', 'compose'])
def test_scope_and_required_inputs_reject_before_output(package_environment, fault):
    env = package_environment; repo = env['repo']
    remove = {'remove-static': 'static/index.html', 'missing-module': 'task_dependencies.py',
              'missing-new-test': 'frontend/tests/taskDependencies.test.mjs',
              'missing-old-test': 'frontend/tests/assistantDocumentSearch.test.mjs',
              'missing-browser': 'scripts/check_expo_task_dependencies_browser.py'}
    if fault in remove: (repo / remove[fault]).unlink()
    elif fault == 'old-docker': write(repo, 'Dockerfile', parent_docker())
    elif fault == 'extra-copy': write(repo, 'Dockerfile', (repo / 'Dockerfile').read_bytes() + b'COPY unrelated.py ./\n')
    else:
        name = {'other-backend': 'journey_documents.py', 'legacy-static': 'static/index.html',
                'add-static': 'static/unreviewed.js', 'requirements': 'requirements.txt',
                'unknown-frontend-test': 'frontend/tests/unreviewed.test.mjs', 'compose': 'compose.yaml'}[fault]
        write(repo, name, b'unreviewed delta\n')
    routes.refresh_evidence(env)
    with pytest.raises(ValueError): package.prepare(**env)
    assert not env['output_dir'].exists()


def test_rehashed_metadata_cannot_exempt_ninth_runtime_or_widen_scripts(package_environment):
    env = package_environment
    result = package.prepare(**env)
    checked = package.verify_package(env['output_dir'], result['packageSha256'])
    meta, manifest = deepcopy(checked['metadata']), deepcopy(checked['manifest'])
    evidence = json.loads(env['build_evidence'].read_bytes())
    for mapping in (meta['runtimeFiles'], meta['sourceFiles'], manifest['files']): mapping['journey_documents.py'] = 'a' * 64
    meta['changedRuntimeFiles'] = list(package.CHANGED_RUNTIME_FILES | {'journey_documents.py'})
    with pytest.raises(ValueError, match='97-file preservation'):
        policy.validate_maps(meta, manifest, evidence, baseline=package.BASELINE)
    names = set(checked['metadata']['sourceFiles']) | {'scripts/unreviewed.py'}
    selected = policy.selected_sources(names, checked['blobs']['deploy/prepare_release.py'], baseline=package.BASELINE)
    assert 'scripts/unreviewed.py' not in selected and package.BROWSER_SCRIPTS <= selected
    # Old dispatch/allowlist paths cannot acquire the new module or script.
    with pytest.raises(ValueError, match='new frontend input needs an explicit packaging policy'):
        policy.selected_sources(names, checked['blobs']['deploy/prepare_release.py'], baseline=previous_package.BASELINE)
    old_inputs = names - (package.FRONTEND_TESTS - previous_package.FRONTEND_TESTS)
    old_selected = policy.selected_sources(old_inputs, checked['blobs']['deploy/prepare_release.py'], baseline=previous_package.BASELINE)
    assert not (package.BROWSER_SCRIPTS | {'task_dependencies.py'}) & old_selected
    assert policy.baseline_values(None)[0] == 'membership-release-package'
    assert policy.fixed_files(previous_package.BASELINE)['Dockerfile'] == package.DOCKER_BEFORE
    with pytest.raises(ValueError, match='unsupported release baseline'): policy.baseline_values('unreviewed')
    assert previous_controller.SPEC.schema_pair == controller.SPEC.schema_pair == (69, 9)
    with pytest.raises(FrozenInstanceError): controller.SPEC.schema_pair = (70, 9)


@pytest.fixture
def assembly(package_environment, tmp_path, monkeypatch):
    monkeypatch.setattr(package_tests, 'steady', package)
    return package_tests.assembly.__wrapped__(package_environment, tmp_path)


def test_offline_plan_binds29_operators_and_exact_package(assembly):
    result = package.assemble(**assembly)
    operator = controller.Controller(assembly['candidate'], result['planSha256'])
    assert result['assembled'] and not result['productionOperations']
    assert operator.validate_evidence() == {'tests': 1, 'passed': 1, 'skipped': 0}
    assert operator.plan['kind'] == 'task-dependencies-release-plan'
    assert set(operator.plan['operatorHashes']) == {'deploy/' + n for n in controller.SPEC.operators}
    assert len(controller.SPEC.operators) == len(set(controller.SPEC.operators)) == 29
    with pytest.raises(common.ReleaseError, match='plan_kind'): previous_controller.Controller(assembly['candidate'], result['planSha256'])
    with pytest.raises(common.ReleaseError, match='new_and_separate'): package.assemble(**assembly)


@pytest.mark.parametrize('fault', ['parent', 'environment', 'profile', 'data-reader'])
def test_plan_cannot_replace_fixed_admission(assembly, fault):
    package.assemble(**assembly)
    path = assembly['candidate'] / 'release-plan.json'; value = json.loads(path.read_bytes())
    if fault == 'parent': value['parentImage'] = previous_package.PARENT_IMAGE
    elif fault == 'environment': value['envSha256'] = 'a' * 64
    else:
        name = 'build_task_dependencies_release.py' if fault == 'profile' else 'assistant_trip_items_release_data.py'
        value['operatorHashes']['deploy/' + name] = 'a' * 64
    path.write_bytes(policy.encoded(value))
    with pytest.raises(common.ReleaseError):
        controller.Controller(assembly['candidate'], policy.digest(path.read_bytes()), runner=lambda *a, **k: pytest.fail('no external action'))


@pytest.fixture
def baseline(tmp_path, monkeypatch):
    root, source = tmp_path / 'installed', tmp_path / 'candidate'
    root.mkdir(); source.mkdir()
    names = (package.CHANGED_RUNTIME_FILES - {'task_dependencies.py'}) | {'README.md', 'compose.yaml', 'requirements.txt', 'Dockerfile', 'deploy/nginx.conf'}
    old = {}
    for name in names:
        raw = parent_docker() if name == 'Dockerfile' else (ROOT / name).read_bytes()
        write(root, name, raw); old[name] = common.sha(raw)
    manifest = root / 'RELEASE-MANIFEST.json'; manifest.write_bytes(policy.encoded({'files': old}))
    monkeypatch.setattr(controller.Controller, 'SPEC', replace(controller.SPEC, old_manifest=common.sha(manifest.read_bytes())))
    env = root / '.env'; env.write_bytes(b'SYNTHETIC=1\n'); env.chmod(0o600)
    if os.name == 'nt': monkeypatch.setattr(core.stat, 'S_IMODE', lambda _: 0o600)
    write(source, 'Dockerfile', (ROOT / 'Dockerfile').read_bytes())
    operator = object.__new__(controller.Controller)
    operator.root, operator.source, operator.files = root, source, {**old, 'Dockerfile': package.DOCKER_AFTER}
    operator.plan = {'envSha256': common.sha(env.read_bytes())}
    calls = []; operator.current_services = lambda image: calls.append(image) or {'recorded': True}
    return operator, calls


@pytest.mark.parametrize('name,allowed', [(n, True) for n in sorted(package.CHANGED_RUNTIME_FILES | package.BROWSER_SCRIPTS)] + [
    ('journey_documents.py', False), ('scripts/unreviewed.py', False)])
def test_baseline_accepts_only_exact_changed_modules_and_browser_path(baseline, name, allowed):
    operator, calls = baseline; operator.files[name] = 'a' * 64
    if allowed:
        operator.baseline(); assert calls == [package.PARENT_IMAGE]
    else:
        with pytest.raises(common.ReleaseError, match='unsupported_source_change'): operator.baseline()
        assert calls == []


@pytest.fixture
def simulation(steady_simulation):
    value = lifecycle.simulation.__wrapped__(steady_simulation)
    value[0].__class__ = controller.Controller
    return value


def test_recorded_lifecycle69_9_backup_before_start_and_no_migration(simulation):
    operator, calls, programs, _ = simulation
    result = operator.activate()
    starts = [i for i, c in enumerate(calls) if isinstance(c, list) and c[:3] == ['docker', 'compose', 'up']]
    workers = next(i for i in starts if 'sync' in calls[i])
    assert calls.index('backup') < starts[0] < calls.index('check') < workers
    assert result['completed'] and (result['householdTables'], result['platformTables']) == (69, 9)
    assert result['stoppedBackup']['logicalSha256'] == result['preservation']['logicalSha256']
    assert 'migration' not in result and '/task-dependencies-69-' in result['releaseDirectory'].replace('\\', '/')
    assert len(programs) == 2 and all('assistant_trip_items_release_data' in p for p in programs)
    assert all('.migrate(' not in p and 'warm_once' not in p for p in programs)


def test_stage_keeps69_9_without_production_writes(simulation):
    operator = simulation[0]
    (operator.candidate / 'stage.json').unlink()  # Synthetic fixture only.
    result = operator.stage()
    assert result['schemaBefore'] == result['schemaAfter'] == [69, 9] and result['productionWrites'] is False


@pytest.mark.parametrize('failed', ['backup', 'check'])
def test_failed_data_phase_retains_stopped_evidence_and_rejects_replay(simulation, failed):
    lifecycle.test_failed_data_phase_stops_and_cannot_replay_activation(simulation, failed)
