"""UI-only package/plan boundaries and recording lifecycle; no Docker/network."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import json

import pytest
from deploy import build_expo_trip_task_publish_release as package
from deploy import activate_expo_trip_task_publish_release as controller
from deploy import assistant_trip_items_release_controller as prior_controller
from deploy import assistant_trip_items_release_profile as prior_profile
from deploy import membership_release_package as policy
from deploy import membership_release_controller as common
import test_assistant_trip_change_release as lifecycle
import test_steady_release_package as package_tests
from test_assistant_trip_change_release import steady_simulation, old_simulation
from test_journey_routes_release import environment, refresh_evidence
from test_membership_release_package import ROOT, write, commit, evidence_update


@pytest.fixture
def package_environment(environment):
    repo = environment['repo']
    for name in controller.SPEC.operators:
        write(repo, 'deploy/' + name, (ROOT / 'deploy' / name).read_bytes())
    write(repo, 'Dockerfile', (ROOT / 'Dockerfile').read_bytes())
    # Use the actual unchanged runtime bytes: never monkeypatch the production
    # 104-file hash/count to make a synthetic package pass the new policy.
    runtime = {p.name for p in repo.glob('*.py')} | package.RUNTIME_ADDITIONS | {'requirements.txt'}
    runtime |= {p.relative_to(ROOT).as_posix() for p in (ROOT / 'static').rglob('*')
                if p.is_file() and not p.relative_to(ROOT).as_posix().startswith(policy.PREFIX)}
    for name in runtime:
        write(repo, name, (ROOT / name).read_bytes())
    assert len(runtime) == 104
    assert policy.digest(policy.encoded({n: policy.digest((repo / n).read_bytes()) for n in runtime})) == package.NON_EXPO_RUNTIME_SHA256
    for name in package.FRONTEND_TESTS:
        write(repo, name, b'// synthetic frontend test\n')
    refresh_evidence(environment)
    return environment


def test_roundtrip_pins_real_non_expo_bytes_and_exclusive_output(package_environment):
    result = package.prepare(**package_environment)
    checked = package.verify_package(package_environment['output_dir'], result['packageSha256'])
    meta = checked['metadata']
    assert (meta['kind'], meta['parentImage'], meta['oldManifestSha256']) == (package.KIND, package.PARENT_IMAGE, package.OLD_MANIFEST)
    preserved = {n: h for n, h in meta['runtimeFiles'].items() if not n.startswith(policy.PREFIX)}
    assert len(preserved) == package.NON_EXPO_RUNTIME_COUNT == 104
    assert policy.digest(policy.encoded(preserved)) == package.NON_EXPO_RUNTIME_SHA256
    assert package.FRONTEND_TESTS <= meta['sourceFiles'].keys()
    assert package.RUNTIME_ADDITIONS <= meta['runtimeFiles'].keys()
    assert meta['fixedFiles'] == {**policy.FIXED, 'Dockerfile': package.DOCKER_AFTER}
    for baseline in (None, prior_profile.BASELINE, 'finance-query-r2-journey-routes'):
        with pytest.raises(ValueError): policy.verify_package(package_environment['output_dir'], result['packageSha256'], baseline=baseline)
    with pytest.raises(ValueError, match='output must be new'): package.prepare(**package_environment)


@pytest.mark.parametrize('fault', ['backend', 'legacy-static', 'add-static', 'remove-static', 'rename-static', 'requirements'])
def test_every_non_expo_runtime_drift_fails_before_output(package_environment, fault):
    env = package_environment; repo = env['repo']
    if fault == 'backend': write(repo, 'task_publish.py', b'# changed backend\n')
    elif fault == 'legacy-static': write(repo, 'static/index.html', b'<p>changed</p>')
    elif fault == 'add-static': write(repo, 'static/unreviewed.js', b'changed')
    elif fault == 'remove-static': (repo / 'static/index.html').unlink()
    elif fault == 'rename-static': (repo / 'static/index.html').rename(repo / 'static/renamed.html')
    else: write(repo, 'requirements.txt', b'changed dependency\n')
    refresh_evidence(env)
    with pytest.raises(ValueError, match='non-Expo runtime'): package.prepare(**env)
    assert not env['output_dir'].exists()


def test_rehashed_manifest_and_metadata_cannot_relax_non_expo_pin(package_environment):
    result = package.prepare(**package_environment)
    checked = package.verify_package(package_environment['output_dir'], result['packageSha256'])
    meta, manifest = deepcopy(checked['metadata']), deepcopy(checked['manifest'])
    evidence = json.loads(package_environment['build_evidence'].read_bytes())
    for mapping in (meta['runtimeFiles'], meta['sourceFiles'], manifest['files']): mapping['task_publish.py'] = 'a' * 64
    with pytest.raises(ValueError, match='non-Expo runtime'):
        policy.validate_maps(meta, manifest, evidence, baseline=package.BASELINE)


@pytest.mark.parametrize('fault', ['missing-task-test', 'unknown-frontend', 'docker', 'missing-backend'])
def test_new_profile_rejects_unreviewed_inputs_before_output(package_environment, fault):
    env = package_environment
    if fault == 'missing-task-test': (env['repo'] / 'frontend/tests/taskPublish.test.mjs').unlink()
    elif fault == 'unknown-frontend': write(env['repo'], 'frontend/tests/unreviewed.test.mjs', b'// unreviewed\n')
    elif fault == 'docker': write(env['repo'], 'Dockerfile', (ROOT / 'Dockerfile').read_bytes() + b'RUN echo changed\n')
    else: (env['repo'] / 'journey_routes.py').unlink()
    refresh_evidence(env)
    with pytest.raises(ValueError): package.prepare(**env)
    assert not env['output_dir'].exists()


def test_only_non_frontend_followup_can_reuse_the_exact_build(package_environment):
    env = package_environment; built_head = env['commit']
    write(env['repo'], 'docs/RELEASE-NOTE.md', b'documentation only\n')
    env['commit'] = commit(env['repo'])
    result = package.prepare(**env)
    meta = package.verify_package(env['output_dir'], result['packageSha256'])['metadata']
    assert meta['buildSourceHead'] == built_head != meta['sourceHead']
    assert 'docs/RELEASE-NOTE.md' in meta['sourceFiles']


def test_changed_frontend_cannot_reuse_the_old_export(package_environment):
    env = package_environment
    write(env['repo'], 'frontend/src/index.ts', b'changed frontend\n')
    env['commit'] = commit(env['repo'])
    with pytest.raises(ValueError, match='build source bytes differ'): package.prepare(**env)
    assert not env['output_dir'].exists()


def test_historical_defaults_and_old_profile_remain_unchanged(environment):
    original = policy.prepare(**environment)
    meta = policy.verify_package(environment['output_dir'], original['packageSha256'])['metadata']
    assert meta['kind'] == 'membership-release-package' and meta['fixedFiles'] == policy.FIXED
    assert policy.baseline_values(prior_profile.BASELINE) == (prior_profile.KIND, prior_profile.PARENT_IMAGE, prior_profile.OLD_MANIFEST)
    assert prior_controller.SPEC.schema_pair == (69, 9)
    assert controller.SPEC.schema_pair == (69, 9)
    with pytest.raises(FrozenInstanceError): controller.SPEC.schema_pair = (66, 9)
    with pytest.raises(ValueError, match='unsupported release baseline'): policy.baseline_values('plan-selected-profile')


@pytest.fixture
def assembly(package_environment, tmp_path, monkeypatch):
    monkeypatch.setattr(package_tests, 'steady', package)
    return package_tests.assembly.__wrapped__(package_environment, tmp_path)


def test_new_offline_plan_binds_all_operators_and_refuses_consumed_entry(assembly):
    result = package.assemble(**assembly)
    operator = controller.Controller(assembly['candidate'], result['planSha256'])
    assert result['assembled'] and not result['productionOperations']
    assert operator.validate_evidence() == {'tests': 1, 'passed': 1, 'skipped': 0}
    assert operator.plan['kind'] == 'expo-trip-task-publish-release-plan'
    assert set(operator.plan['operatorHashes']) == {'deploy/' + n for n in controller.SPEC.operators}
    assert len(controller.SPEC.operators) == len(set(controller.SPEC.operators)) == 23
    with pytest.raises(common.ReleaseError, match='plan_kind'): prior_controller.Controller(assembly['candidate'], result['planSha256'])
    with pytest.raises(common.ReleaseError, match='new_and_separate'): package.assemble(**assembly)


@pytest.mark.parametrize('fault', ['old-parent', 'old-manifest', 'old-kind', 'environment', 'profile', 'data-reader'])
def test_plan_cannot_replace_pinned_baseline_or_shared_reader(assembly, fault):
    package.assemble(**assembly)
    path = assembly['candidate'] / 'release-plan.json'; value = json.loads(path.read_bytes())
    if fault == 'old-parent': value['parentImage'] = prior_profile.PARENT_IMAGE
    elif fault == 'old-manifest': value['oldManifestSha256'] = prior_profile.OLD_MANIFEST
    elif fault == 'old-kind': value['kind'] = prior_controller.SPEC.plan_kind
    elif fault == 'environment': value['envSha256'] = 'a' * 64
    else:
        name = 'build_expo_trip_task_publish_release.py' if fault == 'profile' else 'assistant_trip_items_release_data.py'
        value['operatorHashes']['deploy/' + name] = 'a' * 64
    path.write_bytes(policy.encoded(value))
    with pytest.raises(common.ReleaseError):
        controller.Controller(assembly['candidate'], policy.digest(path.read_bytes()), runner=lambda *a, **k: pytest.fail('no external action during admission'))


@pytest.fixture
def simulation(steady_simulation):
    value = lifecycle.simulation.__wrapped__(steady_simulation)
    value[0].__class__ = controller.Controller
    return value


def test_unchanged69_lifecycle_checks_full_group_before_workers(simulation):
    operator, calls, programs, _ = simulation
    result = operator.activate()
    starts = [i for i, c in enumerate(calls) if isinstance(c, list) and c[:3] == ['docker', 'compose', 'up']]
    workers = next(i for i in starts if 'sync' in calls[i])
    assert calls.index('backup') < starts[0] < calls.index('check') < workers
    assert result['completed'] and result['householdTables'] == 69 and result['platformTables'] == 9
    assert result['stoppedBackup']['logicalSha256'] == result['preservation']['logicalSha256']
    assert 'migration' not in result and '/expo-trip-task-publish-69-' in result['releaseDirectory'].replace('\\', '/')
    assert len(programs) == 2 and all('assistant_trip_items_release_data' in p for p in programs)
    assert all('.migrate(' not in p and 'warm_once' not in p for p in programs)


def test_stage_reports_fixed69_without_changing_existing_profiles(simulation):
    operator = simulation[0]
    (operator.candidate / 'stage.json').unlink()  # Only this synthetic fixture's receipt.
    value = operator.stage()
    assert value['schemaBefore'] == value['schemaAfter'] == [69, 9]
    assert value['productionWrites'] is False


@pytest.mark.parametrize('failed', ['backup', 'check'])
def test_failure_keeps_stopped_evidence_without_replay(simulation, failed):
    lifecycle.test_failed_data_phase_stops_and_cannot_replay_activation(simulation, failed)
