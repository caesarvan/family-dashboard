"""Synthetic package/plan/admission/failure checks; no Docker, app or network."""
from dataclasses import FrozenInstanceError, replace
import json
import os
from pathlib import Path

import pytest
from deploy import build_journey_routes_release as package
from deploy import build_journey_routes_release as profile
from deploy import activate_journey_routes_release as controller
from deploy import build_journey_routes_release as plan
from deploy import assistant_trip_change_release_controller as trip_controller
from deploy import assistant_trip_change_release_profile as trip_profile
from deploy import membership_release_package as shared
from deploy import membership_release_controller as common
import test_assistant_trip_change_release as trip_tests
import test_steady_release_package as package_tests
import test_steady_release_controller as controller_tests
from test_membership_release_package import write, commit, git, ROOT
from test_assistant_trip_change_release import steady_simulation, old_simulation
import test_membership_release_package as base_tests
from deploy import assistant_finance_query_release_profile as old_profile
from deploy import finance_analysis_release_controller as old_migration
import ast
import inspect


def refresh_evidence(env):
    env['commit'] = commit(env['repo'])
    evidence = json.loads(env['build_evidence'].read_bytes())
    evidence.update(head=env['commit'], tree=git(env['repo'], 'rev-parse', 'HEAD^{tree}'),
        inputFiles={n: shared.digest((env['repo'] / n).read_bytes()) for n in shared.required_build_inputs(
            shared.tracked_files(env['repo'], env['commit']))})
    env['build_evidence'].write_bytes(shared.encoded(evidence))
    env['evidence_sha256'] = shared.digest(env['build_evidence'].read_bytes())


def new_docker():
    raw = (ROOT / 'Dockerfile').read_bytes()
    if shared.digest(raw) == profile.DOCKER_AFTER:
        return raw
    assert shared.digest(raw) == profile.DOCKER_BEFORE
    return raw.replace(profile.COPY_BEFORE, profile.COPY_AFTER, 1)


@pytest.fixture
def environment(tmp_path, monkeypatch):
    def historical_blob(name):
        raw = (ROOT / name).read_bytes()
        if name == 'Dockerfile':
            raw = new_docker().replace(profile.COPY_AFTER, profile.COPY_BEFORE, 1)
            raw = raw.replace(old_profile.COPY_AFTER, old_profile.COPY_BEFORE, 1)
            raw = raw.replace(trip_profile.COPY_AFTER, trip_profile.COPY_BEFORE, 1)
            raw = raw.replace(shared.INVENTORY_COPY_AFTER, shared.INVENTORY_COPY_BEFORE, 1)
            raw = raw.replace(b'COPY finance_analysis.py finance_fx.py ./\n', b'', 1)
        assert shared.digest(raw) == shared.FIXED[name]
        return raw
    monkeypatch.setattr(base_tests, 'historical_fixed_blob', historical_blob)
    return base_tests.environment.__wrapped__(tmp_path)


@pytest.fixture
def package_environment(environment):
    for name in controller.SPEC.operators:
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
        (env['repo'] / 'journey_routes.py').unlink()
    elif fault == 'old-docker':
        write(env['repo'], 'Dockerfile', new_docker().replace(profile.COPY_AFTER, profile.COPY_BEFORE, 1))
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
    assert operator.plan['controllerSha256'] == shared.digest((ROOT / 'deploy/activate_journey_routes_release.py').read_bytes())
    assert set(operator.plan['operatorHashes']) == {'deploy/' + n for n in controller.SPEC.operators}
    assert len(controller.SPEC.operators) == len(set(controller.SPEC.operators)) == 17
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
        name = 'assistant_trip_change_release_controller.py' if fault == 'shared-core' else 'build_journey_routes_release.py'
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
    assert profile.RUNTIME_ADDITIONS == old_profile.RUNTIME_ADDITIONS | {'journey_routes.py'}
    assert shared.fixed_files(trip_profile.BASELINE)['Dockerfile'] == trip_profile.DOCKER_AFTER
    with pytest.raises(ValueError, match='23-file'):
        shared.validate_export_names({'index.html', 'metadata.json', '_expo/static/js/web/entry-one.js'})


@pytest.fixture
def simulation(steady_simulation):
    operator, calls, programs, old = steady_simulation
    operator.__class__ = controller.Controller
    def data_call(proof, program, **kwargs):
        phase = 'backup' if 'routes.begin(' in program else 'migrate' if 'routes.migrate(' in program else 'check'
        calls.append(phase); programs.append(program)
        if phase == 'check': assert kwargs == {'write': False}
        return {'verified': True, 'logicalSha256': ('a' if phase == 'backup' else 'b') * 64}
    operator.data_call = data_call
    return operator, calls, programs, old


def test_new_entry_migrates_after_full_backup_and_checks_startup_before_workers(simulation):
    operator, calls, programs, old = simulation
    result = operator.activate()
    workers = next(i for i, c in enumerate(calls) if isinstance(c, list) and c[:3] == ['docker', 'compose', 'up'] and 'sync' in c)
    app = next(i for i, c in enumerate(calls) if isinstance(c, list) and c[:3] == ['docker', 'compose', 'up'])
    assert calls.index('backup') < calls.index('migrate') < app < calls.index('check') < workers
    assert len(programs) == 3 and result['completed']
    assert result['householdTables'] == 69 and result['platformTables'] == 9
    assert result['stoppedBackup']['logicalSha256'] == 'a' * 64
    assert result['migration']['logicalSha256'] == result['preservation']['logicalSha256'] == 'b' * 64
    assert '/journey-routes-69-' in result['releaseDirectory'].replace('\\', '/')
    assert (Path(result['releaseDirectory']) / 'source-before/app.py').read_bytes() == old['app.py']


@pytest.mark.parametrize('failed', ['backup', 'migrate', 'check'])
def test_data_failure_retains_attempt_and_prevents_replay(simulation, failed):
    operator, calls, _, old = simulation
    original = operator.data_call
    def fail(proof, program, **kwargs):
        if ('begin(' if failed == 'backup' else 'migrate(' if failed == 'migrate' else 'check_stopped(') in program:
            raise common.ReleaseError('synthetic_phase_failure')
        return original(proof, program, **kwargs)
    operator.data_call = fail
    with pytest.raises(common.ReleaseError, match='synthetic_phase_failure'): operator.activate()
    path = operator.candidate / 'activation.json'; raw = path.read_bytes(); value = json.loads(raw)
    assert value['completed'] is False
    assert not any(isinstance(c, list) and c[:3] == ['docker', 'compose', 'up'] and 'sync' in c for c in calls)
    if failed in ('backup', 'migrate'): assert (operator.root / 'app.py').read_bytes() == old['app.py']
    else: assert value['candidateStoppedAfterFailure'] is True
    with pytest.raises(FileExistsError): operator.activate()
    assert path.read_bytes() == raw


@pytest.mark.parametrize('window', ['first_app', 'health', 'runtime', 'worker', 'public_health', 'timer'])
def test_failure_after_candidate_start_stops_writers_without_restore(simulation, window):
    controller_tests.test_partial_start_failure_stops_candidate_without_restore(simulation, window)


def test_cleanup_failure_does_not_claim_stopped(simulation):
    controller_tests.test_cleanup_failure_does_not_claim_stopped(simulation)


def test_migration_lifecycle_only_changes_reviewed_profile_fields():
    # An executable structural comparison binds reuse of the reviewed sequencing.
    prior = inspect.getsource(old_migration.Controller._activate)
    new = inspect.getsource(controller.Controller._activate)
    expected = prior.replace("self.releases / ('finance-analysis-66-' + stamp)", "self.releases / (self.spec.release_prefix + stamp)")
    expected = expected.replace('exact_five_table_migration_verified', 'exact_three_table_migration_verified').replace('householdTables=66', 'householdTables=69')
    import textwrap
    assert ast.dump(ast.parse(textwrap.dedent(new))) == ast.dump(ast.parse(textwrap.dedent(expected)))


@pytest.fixture
def baseline(tmp_path, monkeypatch):
    root, source = tmp_path / 'installed', tmp_path / 'candidate'
    root.mkdir(); source.mkdir()
    old = {}
    for name in ('app.py', 'data_portability.py', 'journey_places.py', 'finance_accounts.py', 'compose.yaml', 'requirements.txt', 'Dockerfile', 'deploy/nginx.conf'):
        raw = new_docker().replace(profile.COPY_AFTER, profile.COPY_BEFORE, 1) if name == 'Dockerfile' else (ROOT / name).read_bytes()
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


@pytest.mark.parametrize('path,allowed', [('app.py', True), ('data_portability.py', True), ('journey_places.py', True),
    ('journey_routes.py', True), ('membership_storage.py', False),
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
