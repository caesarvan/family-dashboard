"""Fixed package and recording-controller boundaries; no Docker or network."""
from dataclasses import FrozenInstanceError, replace
import json
import os

import pytest
from deploy import assistant_trip_items_release_profile as profile
from deploy import assistant_trip_items_release_package as package
from deploy import assistant_trip_items_release_controller as controller
from deploy import assistant_trip_items_release_plan as plan
from deploy import assistant_trip_change_release_controller as old_controller
from deploy import membership_release_package as policy
from deploy import membership_release_controller as common
import test_assistant_trip_change_release as old_tests
import test_steady_release_package as package_tests
import test_steady_release_controller as recording
from test_journey_routes_release import environment, refresh_evidence
from test_membership_release_package import ROOT, write
from test_assistant_trip_change_release import steady_simulation, old_simulation


@pytest.fixture
def package_environment(environment):
    for name in controller.SPEC.operators:
        write(environment['repo'], 'deploy/' + name, (ROOT / 'deploy' / name).read_bytes())
    write(environment['repo'], 'Dockerfile', (ROOT / 'Dockerfile').read_bytes())
    for name in profile.RUNTIME_ADDITIONS:
        write(environment['repo'], name, ('# synthetic ' + name + '\n').encode())
    for name in profile.FRONTEND_TESTS:
        write(environment['repo'], name, b'// synthetic frontend test\n')
    refresh_evidence(environment)
    return environment


def test_fixed_baseline_unchanged_docker_runtime_and_explicit_frontend(package_environment):
    result = package.prepare(**package_environment)
    checked = package.verify_package(package_environment['output_dir'], result['packageSha256'])
    meta = checked['metadata']
    assert (meta['kind'], meta['parentImage'], meta['oldManifestSha256']) == (
        profile.KIND, profile.PARENT_IMAGE, profile.OLD_MANIFEST)
    assert profile.RUNTIME_ADDITIONS <= meta['runtimeFiles'].keys()
    assert profile.FRONTEND_TESTS <= meta['sourceFiles'].keys()
    assert meta['fixedFiles'] == {**policy.FIXED, 'Dockerfile': profile.DOCKER_AFTER}
    for baseline in (None, old_controller.SPEC.baseline, 'finance-query-r2-journey-routes'):
        with pytest.raises(ValueError):
            policy.verify_package(package_environment['output_dir'], result['packageSha256'], baseline=baseline)
    with pytest.raises(ValueError, match='unsupported release baseline'):
        policy.baseline_values('unreviewed-profile')


@pytest.mark.parametrize('fault', ['missing-runtime', 'extra-docker', 'dependency', 'unknown-frontend'])
def test_admission_rejects_unreviewed_inputs_before_output(package_environment, fault):
    env = package_environment
    if fault == 'missing-runtime': (env['repo'] / 'journey_routes.py').unlink()
    elif fault == 'extra-docker': write(env['repo'], 'Dockerfile', (ROOT / 'Dockerfile').read_bytes() + b'RUN echo changed\n')
    elif fault == 'dependency': write(env['repo'], 'requirements.txt', b'unreviewed\n')
    else: write(env['repo'], 'frontend/tests/unreviewed.test.mjs', b'// unreviewed\n')
    refresh_evidence(env)
    with pytest.raises(ValueError): package.prepare(**env)
    assert not env['output_dir'].exists()


@pytest.fixture
def assembly(package_environment, tmp_path, monkeypatch):
    monkeypatch.setattr(package_tests, 'steady', package)
    return package_tests.assembly.__wrapped__(package_environment, tmp_path)


def test_plan_binds_entire_operator_chain_and_refuses_old_entry(assembly):
    result = plan.assemble(**assembly)
    operator = controller.Controller(assembly['candidate'], result['planSha256'])
    assert result['assembled'] and not result['productionOperations']
    assert operator.validate_evidence() == {'tests': 1, 'passed': 1, 'skipped': 0}
    assert operator.plan['kind'] == controller.SPEC.plan_kind
    assert set(operator.plan['operatorHashes']) == {'deploy/' + n for n in controller.SPEC.operators}
    assert len(controller.SPEC.operators) == len(set(controller.SPEC.operators)) == 21
    with pytest.raises(common.ReleaseError, match='plan_kind'):
        old_controller.Controller(assembly['candidate'], result['planSha256'])
    with pytest.raises(common.ReleaseError, match='new_and_separate'): plan.assemble(**assembly)


@pytest.mark.parametrize('name', ['assistant_trip_change_release_data.py', 'assistant_trip_items_release_data.py',
                                 'check_journey_routes_migration.py', 'assistant_trip_items_release_profile.py'])
def test_plan_cannot_change_source_selected_profile_or_reader(assembly, name):
    plan.assemble(**assembly)
    path = assembly['candidate'] / 'release-plan.json'
    value = json.loads(path.read_bytes()); value['operatorHashes']['deploy/' + name] = 'a' * 64
    path.write_bytes(policy.encoded(value))
    with pytest.raises(common.ReleaseError):
        controller.Controller(assembly['candidate'], policy.digest(path.read_bytes()),
                              runner=lambda *a, **k: pytest.fail('admission must not execute'))


@pytest.fixture
def simulation(steady_simulation):
    result = old_tests.simulation.__wrapped__(steady_simulation)
    result[0].__class__ = controller.Controller
    return result


def test_source_update_keeps_whole_group_before_workers_and_reports69(simulation):
    operator, calls, programs, _ = simulation
    result = operator.activate()
    starts = [i for i, c in enumerate(calls) if isinstance(c, list) and c[:3] == ['docker', 'compose', 'up']]
    workers = next(i for i in starts if 'sync' in calls[i])
    assert calls.index('backup') < starts[0] < calls.index('check') < workers
    assert result['completed'] and result['householdTables'] == 69 and result['platformTables'] == 9
    assert result['stoppedBackup']['logicalSha256'] == result['preservation']['logicalSha256']
    assert 'migration' not in result and '/assistant-trip-items-69-' in result['releaseDirectory'].replace('\\', '/')
    assert len(programs) == 2 and all('assistant_trip_items_release_data' in p for p in programs)
    assert all('.migrate(' not in p and 'warm_once' not in p for p in programs)


def test_stage_reports_source_fixed69_and_old_default_stays66(simulation):
    operator = simulation[0]
    (operator.candidate / 'stage.json').unlink()  # Synthetic fixture's already-staged record only.
    value = operator.stage()
    assert value['schemaBefore'] == value['schemaAfter'] == [69, 9]
    assert old_controller.SPEC.schema_pair == (66, 9)
    with pytest.raises(FrozenInstanceError): controller.SPEC.schema_pair = (66, 9)


@pytest.mark.parametrize('failed', ['backup', 'check'])
def test_failure_stops_without_replay(simulation, failed):
    old_tests.test_failed_data_phase_stops_and_cannot_replay_activation(simulation, failed)


@pytest.mark.parametrize('window', ['health', 'worker'])
def test_partial_start_failure_preserves_stopped_evidence(simulation, window):
    recording.test_partial_start_failure_stops_candidate_without_restore(simulation, window)


@pytest.fixture
def baseline(tmp_path, monkeypatch):
    root = tmp_path / 'installed'; root.mkdir()
    source = tmp_path / 'source'; source.mkdir()
    files = {}
    for name in ('home_assistant.py', 'app.py', 'compose.yaml', 'requirements.txt', 'Dockerfile', 'deploy/nginx.conf'):
        raw = (ROOT / name).read_bytes()
        write(root, name, raw); files[name] = common.sha(raw)
    manifest = root / 'RELEASE-MANIFEST.json'; manifest.write_bytes(policy.encoded({'files': files}))
    monkeypatch.setattr(controller.Controller, 'SPEC', replace(controller.SPEC, old_manifest=common.sha(manifest.read_bytes())))
    env = root / '.env'; env.write_bytes(b'SYNTHETIC=1\n'); env.chmod(0o600)
    if os.name == 'nt': monkeypatch.setattr(old_controller.stat, 'S_IMODE', lambda _: 0o600)
    write(source, 'Dockerfile', (ROOT / 'Dockerfile').read_bytes())
    operator = object.__new__(controller.Controller)
    operator.root, operator.source, operator.files = root, source, dict(files)
    operator.plan = {'envSha256': common.sha(env.read_bytes())}
    calls = []; operator.current_services = lambda image: calls.append(image) or {'recorded': True}
    return operator, calls


@pytest.mark.parametrize('path,allowed', [('home_assistant.py', True), ('README.md', True), ('app.py', False),
    ('journey_routes.py', False), ('finance_hub.py', False), ('unexpected.py', False)])
def test_exact_root_scope_precedes_service_inspection(baseline, path, allowed):
    operator, calls = baseline
    operator.files[path] = 'a' * 64
    if allowed:
        operator.baseline(); assert calls == [profile.PARENT_IMAGE]
    else:
        with pytest.raises(common.ReleaseError, match='unsupported_source_change'): operator.baseline()
        assert calls == []
