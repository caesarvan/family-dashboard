"""Synthetic package/plan/admission/failure checks; no Docker, app or network."""
from dataclasses import FrozenInstanceError, replace
import json
import os
from pathlib import Path

import pytest
from deploy import assistant_finance_query_release_package as package
from deploy import assistant_finance_query_release_profile as profile
from deploy import assistant_finance_query_release_controller as controller
from deploy import assistant_finance_query_release_plan as plan
from deploy import assistant_trip_change_release_controller as trip_controller
from deploy import assistant_trip_change_release_profile as trip_profile
from deploy import membership_release_package as shared
from deploy import membership_release_controller as common
import test_assistant_trip_change_release as trip_tests
import test_steady_release_package as package_tests
import test_steady_release_controller as controller_tests
from test_membership_release_package import write, commit, git, ROOT
from test_assistant_trip_change_release import environment, steady_simulation, old_simulation


def refresh_evidence(env):
    env['commit'] = commit(env['repo'])
    evidence = json.loads(env['build_evidence'].read_bytes())
    evidence.update(head=env['commit'], tree=git(env['repo'], 'rev-parse', 'HEAD^{tree}'),
        inputFiles={n: shared.digest((env['repo'] / n).read_bytes()) for n in shared.required_build_inputs(
            shared.tracked_files(env['repo'], env['commit']))})
    env['build_evidence'].write_bytes(shared.encoded(evidence))
    env['evidence_sha256'] = shared.digest(env['build_evidence'].read_bytes())


def new_docker():
    raw = trip_tests.trip_docker()
    # Also runnable after the exact new Docker COPY is integrated into this checkout.
    assert shared.digest(raw) == profile.DOCKER_BEFORE
    raw = raw.replace(profile.COPY_BEFORE, profile.COPY_AFTER, 1)
    assert shared.digest(raw) == profile.DOCKER_AFTER
    return raw


@pytest.fixture
def package_environment(environment):
    for name in plan.OPERATORS:
        write(environment['repo'], 'deploy/' + name, (ROOT / 'deploy' / name).read_bytes())
    write(environment['repo'], 'Dockerfile', new_docker())
    for name in profile.RUNTIME_ADDITIONS:
        write(environment['repo'], name, ('# synthetic ' + name + '\n').encode())
    for name in profile.FRONTEND_TESTS:
        write(environment['repo'], name, b'// synthetic frontend test\n')
    refresh_evidence(environment)
    return environment


def test_new_profile_package_preserves_exact_modules_tests_and_fixed_baseline(package_environment):
    result = package.prepare(**package_environment)
    checked = package.verify_package(package_environment['output_dir'], result['packageSha256'])
    meta = checked['metadata']
    assert (meta['kind'], meta['parentImage'], meta['oldManifestSha256']) == (
        profile.KIND, profile.PARENT_IMAGE, profile.OLD_MANIFEST)
    assert profile.RUNTIME_ADDITIONS <= meta['runtimeFiles'].keys()
    assert profile.FRONTEND_TESTS <= meta['sourceFiles'].keys()
    assert meta['fixedFiles'] == {**shared.FIXED, 'Dockerfile': profile.DOCKER_AFTER}
    for baseline in (None, 'memberships-r3-steady', 'shopping-r1-steady', 'followup-r1-steady',
                     'order-inventory-r1-finance-analysis', trip_profile.BASELINE):
        with pytest.raises(ValueError):
            shared.verify_package(package_environment['output_dir'], result['packageSha256'], baseline=baseline)
    with pytest.raises(ValueError, match='unsupported release baseline'):
        shared.baseline_values('unreviewed-profile')


@pytest.mark.parametrize('fault', ['missing-module', 'old-docker', 'extra-copy', 'dependency', 'unknown-frontend'])
def test_new_admission_failure_precedes_output(package_environment, fault):
    env = package_environment
    if fault == 'missing-module':
        (env['repo'] / 'assistant_finance_query.py').unlink()
    elif fault == 'old-docker':
        write(env['repo'], 'Dockerfile', trip_tests.trip_docker())
    elif fault == 'extra-copy':
        write(env['repo'], 'Dockerfile', new_docker() + b'COPY unexpected.py ./\n')
    elif fault == 'dependency':
        write(env['repo'], 'requirements.txt', b'unreviewed-dependency\n')
    else:
        write(env['repo'], 'frontend/tests/unreviewed.test.mjs', b'// unreviewed input\n')
    refresh_evidence(env)
    with pytest.raises(ValueError):
        package.prepare(**env)
    assert not env['output_dir'].exists()


@pytest.fixture
def assembly(package_environment, tmp_path, monkeypatch):
    monkeypatch.setattr(package_tests, 'steady', package)
    return package_tests.assembly.__wrapped__(package_environment, tmp_path)


def test_offline_plan_binds_thin_entry_shared_core_and_exact_evidence(assembly):
    result = plan.assemble(**assembly)
    assert result['assembled'] and result['reviewRequired'] and not result['productionOperations']
    operator = controller.Controller(assembly['candidate'], result['planSha256'])
    assert operator.validate_evidence() == {'tests': 1, 'passed': 1, 'skipped': 0}
    assert operator.plan['kind'] == controller.SPEC.plan_kind
    assert operator.plan['controllerSha256'] == shared.digest((ROOT / 'deploy/assistant_finance_query_release_controller.py').read_bytes())
    assert set(operator.plan['operatorHashes']) == {'deploy/' + n for n in plan.OPERATORS}
    assert len(plan.OPERATORS) == len(set(plan.OPERATORS)) == 18
    with pytest.raises(common.ReleaseError, match='plan_kind'):
        trip_controller.Controller(assembly['candidate'], result['planSha256'])
    class UnknownEntry(controller.Controller):
        pass
    with pytest.raises(common.ReleaseError, match='controller_entry_import_changed'):
        UnknownEntry(assembly['candidate'], result['planSha256'])
    with pytest.raises(common.ReleaseError, match='new_and_separate'):
        plan.assemble(**assembly)


@pytest.mark.parametrize('fault', ['old-kind', 'old-parent', 'old-manifest', 'environment', 'entry', 'shared-core', 'new-profile'])
def test_changed_plan_cannot_admit_wrong_or_unreviewed_operator(assembly, fault):
    plan.assemble(**assembly)
    path = assembly['candidate'] / 'release-plan.json'
    value = json.loads(path.read_bytes())
    if fault == 'old-kind': value['kind'] = trip_controller.SPEC.plan_kind
    elif fault == 'old-parent': value['parentImage'] = trip_profile.PARENT_IMAGE
    elif fault == 'old-manifest': value['oldManifestSha256'] = trip_profile.OLD_MANIFEST
    elif fault == 'environment': value['envSha256'] = 'a' * 64
    elif fault == 'entry': value['controllerSha256'] = 'a' * 64
    else:
        name = 'assistant_trip_change_release_controller.py' if fault == 'shared-core' else 'assistant_finance_query_release_profile.py'
        value['operatorHashes']['deploy/' + name] = 'a' * 64
    path.write_bytes(shared.encoded(value))
    with pytest.raises(common.ReleaseError):
        controller.Controller(assembly['candidate'], shared.digest(path.read_bytes()),
                              runner=lambda *a, **k: pytest.fail('admission must not run an operator'))


@pytest.mark.parametrize('changed', ['build', 'source', 'selection'])
def test_changed_original_evidence_is_rejected(assembly, changed):
    if changed == 'build':
        path = assembly['build_dir'] / 'build.json'; value = json.loads(path.read_bytes())
        value['parentImage'] = trip_profile.PARENT_IMAGE
        path.write_bytes(shared.encoded(value)); assembly['build_sha256'] = shared.digest(path.read_bytes())
    elif changed == 'source':
        (assembly['validation_dir'] / 'proof/runtime.json').write_bytes(b'{}')
    else:
        path = assembly['reviews'].parent / 'selection.json'
        value = json.loads(path.read_bytes()); value['nodeids'] = ['tests/test_synthetic.py::test_changed']
        path.write_bytes(shared.encoded(value))
    with pytest.raises((ValueError, common.ReleaseError)):
        plan.assemble(**assembly)


def test_specs_are_immutable_and_keep_the_historical_profile():
    with pytest.raises(FrozenInstanceError):
        controller.SPEC.parent_image = trip_profile.PARENT_IMAGE
    assert trip_controller.SPEC.parent_image == trip_profile.PARENT_IMAGE
    assert trip_controller.SPEC.old_manifest == trip_profile.OLD_MANIFEST
    assert trip_controller.SPEC.operators == trip_controller.OPERATORS
    assert profile.RUNTIME_ADDITIONS == trip_profile.RUNTIME_ADDITIONS | {'assistant_finance_query.py'}
    assert shared.fixed_files(trip_profile.BASELINE)['Dockerfile'] == trip_profile.DOCKER_AFTER
    with pytest.raises(ValueError, match='23-file'):
        shared.validate_export_names({'index.html', 'metadata.json', '_expo/static/js/web/entry-one.js'})


@pytest.fixture
def simulation(steady_simulation):
    operator, calls, programs, old = steady_simulation
    operator.__class__ = controller.Controller
    return operator, calls, programs, old


def test_new_entry_keeps_backup_startup_preservation_worker_order(simulation):
    trip_tests.test_populated66_backup_then_app_preservation_before_workers_without_migration(simulation)
    operator = simulation[0]
    record = common.read(operator.candidate / 'activation.json')
    assert '/assistant-finance-query-66-' in record['releaseDirectory'].replace('\\', '/')


@pytest.mark.parametrize('failed', ['backup', 'check'])
def test_data_failure_retains_attempt_and_prevents_replay(simulation, failed):
    trip_tests.test_failed_data_phase_stops_and_cannot_replay_activation(simulation, failed)


@pytest.mark.parametrize('window', ['first_app', 'health', 'runtime', 'worker', 'public_health', 'timer'])
def test_failure_after_candidate_start_stops_writers_without_restore(simulation, window):
    controller_tests.test_partial_start_failure_stops_candidate_without_restore(simulation, window)


def test_cleanup_failure_does_not_claim_stopped(simulation):
    controller_tests.test_cleanup_failure_does_not_claim_stopped(simulation)


@pytest.fixture
def baseline(tmp_path, monkeypatch):
    root, source = tmp_path / 'installed', tmp_path / 'candidate'
    root.mkdir(); source.mkdir()
    old = {}
    for name in ('app.py', 'finance_hub.py', 'finance_accounts.py', 'compose.yaml', 'requirements.txt', 'Dockerfile', 'deploy/nginx.conf'):
        raw = trip_tests.trip_docker() if name == 'Dockerfile' else (ROOT / name).read_bytes()
        write(root, name, raw); old[name] = shared.digest(raw)
    manifest = root / 'RELEASE-MANIFEST.json'; manifest.write_bytes(shared.encoded({'files': old}))
    monkeypatch.setattr(controller.Controller, 'SPEC', replace(controller.SPEC, old_manifest=shared.digest(manifest.read_bytes())))
    env = root / '.env'; env.write_bytes(b'SYNTHETIC=1\n'); env.chmod(0o600)
    if os.name == 'nt': monkeypatch.setattr(trip_controller.stat, 'S_IMODE', lambda _: 0o600)
    write(source, 'Dockerfile', new_docker())
    operator = object.__new__(controller.Controller)
    operator.root, operator.source, operator.files = root, source, {**old, 'Dockerfile': profile.DOCKER_AFTER}
    operator.plan = {'envSha256': shared.digest(env.read_bytes())}
    calls = []
    operator.current_services = lambda image: calls.append(image) or {'recorded': True}
    return operator, calls


@pytest.mark.parametrize('path,allowed', [('app.py', True), ('finance_hub.py', True), ('assistant_finance_query.py', True),
    ('assistant_trip_change_api.py', False), ('finance_accounts.py', False), ('finance_analysis.py', False),
    ('home_assistant.py', False), ('unreviewed.py', False)])
def test_new_root_scope_before_service_inspection(baseline, path, allowed):
    operator, calls = baseline
    operator.files[path] = 'a' * 64
    if allowed:
        operator.baseline(); assert calls == [profile.PARENT_IMAGE]
    else:
        with pytest.raises(common.ReleaseError, match='unsupported_source_change'): operator.baseline()
        assert calls == []


@pytest.mark.parametrize('phase', ['build', 'validate'])
def test_existing_builder_carries_the_new_profile(package_environment, tmp_path, monkeypatch, phase):
    monkeypatch.setattr(package_tests, 'steady', package)
    method = (package_tests.test_recording_build_threads_fixed_baseline_and_parent if phase == 'build'
              else package_tests.test_recording_validation_rechecks_same_fixed_baseline)
    method(package_environment, tmp_path, monkeypatch)


@pytest.mark.parametrize('release', ['historical', 'trip', 'finance-query'])
def test_combined_docker_fixture_roundtrips_exact_original_profiles(tmp_path, monkeypatch, release):
    # Emulate only the final checkout's approved Docker bytes. All other reads,
    # temporary Git commits, package extraction and policy checks remain real.
    combined = new_docker()
    original_read = Path.read_bytes
    monkeypatch.setattr(Path, 'read_bytes', lambda path: combined if path == ROOT / 'Dockerfile' else original_read(path))
    env = trip_tests.environment.__wrapped__(tmp_path, monkeypatch)
    if release == 'historical':
        target = shared
    elif release == 'trip':
        env = trip_tests.package_environment.__wrapped__(env)
        target = trip_tests.package
    else:
        env = package_environment.__wrapped__(env)
        target = package
    result = target.prepare(**env)
    checked = target.verify_package(env['output_dir'], result['packageSha256'])
    expected = {'historical': shared.FIXED['Dockerfile'], 'trip': trip_profile.DOCKER_AFTER,
                'finance-query': profile.DOCKER_AFTER}[release]
    assert checked['metadata']['fixedFiles']['Dockerfile'] == expected


@pytest.mark.parametrize('extra', [b'COPY assistant_finance_query.py ./\n', b'RUN echo unreviewed\n'])
def test_fixture_refuses_any_unreviewed_docker_change(monkeypatch, extra):
    raw = new_docker() + extra
    original_read = Path.read_bytes
    monkeypatch.setattr(Path, 'read_bytes', lambda path: raw if path == ROOT / 'Dockerfile' else original_read(path))
    with pytest.raises(AssertionError):
        trip_tests.trip_docker()
