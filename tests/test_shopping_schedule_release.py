"""Fixed 99-file preservation and recorded 69/9 lifecycle; no Docker/network."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
import os

import pytest
from deploy import build_shopping_schedule_release as package
from deploy import activate_shopping_schedule_release as controller
from deploy import build_expo_trip_task_publish_release as previous_package
from deploy import activate_expo_trip_task_publish_release as previous_controller
from deploy import assistant_trip_change_release_controller as core
from deploy import membership_release_package as policy
from deploy import membership_release_controller as common
import test_assistant_trip_change_release as lifecycle
import test_steady_release_package as package_tests
from test_assistant_trip_change_release import steady_simulation, old_simulation
from test_journey_routes_release import environment, refresh_evidence
from test_membership_release_package import ROOT, write, commit


@pytest.fixture
def package_environment(environment):
    repo = environment['repo']
    for name in controller.SPEC.operators:
        write(repo, 'deploy/' + name, (ROOT / 'deploy' / name).read_bytes())
    write(repo, 'Dockerfile', (ROOT / 'Dockerfile').read_bytes())
    runtime = {p.name for p in repo.glob('*.py')} | package.RUNTIME_ADDITIONS | {'requirements.txt'}
    runtime |= {p.relative_to(ROOT).as_posix() for p in (ROOT / 'static').rglob('*')
                if p.is_file() and not p.relative_to(ROOT).as_posix().startswith(policy.PREFIX)}
    for name in runtime:
        write(repo, name, (ROOT / name).read_bytes())
    preserved = {n: policy.digest((repo / n).read_bytes()) for n in runtime
                 if n not in package.CHANGED_RUNTIME_FILES}
    # Exercise real unchanged runtime bytes; never patch production pins.
    assert len(runtime) == package.NON_EXPO_RUNTIME_COUNT == 104
    assert len(preserved) == package.PRESERVED_RUNTIME_COUNT == 99
    assert policy.digest(policy.encoded(preserved)) == package.PRESERVED_RUNTIME_SHA256
    for name in package.FRONTEND_TESTS:
        write(repo, name, b'// synthetic frontend test\n')
    refresh_evidence(environment)
    return environment


def test_roundtrip_allows_only_five_runtime_exclusions_and_exact_frontend_tests(package_environment):
    env = package_environment
    for name in package.CHANGED_RUNTIME_FILES | {'README.md'}:
        write(env['repo'], name, (env['repo'] / name).read_bytes() + b'\n# reviewed synthetic change\n')
    refresh_evidence(env)
    result = package.prepare(**env)
    meta = package.verify_package(env['output_dir'], result['packageSha256'])['metadata']
    assert (meta['kind'], meta['parentImage'], meta['oldManifestSha256']) == (
        package.KIND, package.PARENT_IMAGE, package.OLD_MANIFEST)
    non_expo = {n: h for n, h in meta['runtimeFiles'].items() if not n.startswith(policy.PREFIX)}
    preserved = {n: h for n, h in non_expo.items() if n not in package.CHANGED_RUNTIME_FILES}
    assert len(non_expo) == 104 and len(preserved) == 99
    assert policy.digest(policy.encoded(preserved)) == package.PRESERVED_RUNTIME_SHA256
    assert package.FRONTEND_TESTS <= meta['sourceFiles'].keys()
    assert previous_package.FRONTEND_TESTS < package.FRONTEND_TESTS
    assert package.RUNTIME_ADDITIONS <= meta['runtimeFiles'].keys()
    assert meta['fixedFiles'] == {**policy.FIXED, 'Dockerfile': package.DOCKER_AFTER}
    for baseline in (None, previous_package.BASELINE, 'journey-routes-r1-assistant-trip-items'):
        with pytest.raises(ValueError):
            policy.verify_package(env['output_dir'], result['packageSha256'], baseline=baseline)
    with pytest.raises(ValueError, match='output must be new'):
        package.prepare(**env)


@pytest.mark.parametrize('fault', ['other-backend', 'legacy-static', 'add-static', 'remove-static',
                                  'rename-static', 'requirements', 'remove-allowed-root'])
def test_non_expo_scope_drift_fails_before_output(package_environment, fault):
    env = package_environment; repo = env['repo']
    if fault == 'other-backend': write(repo, 'task_publish.py', b'# changed backend\n')
    elif fault == 'legacy-static': write(repo, 'static/index.html', b'<p>changed</p>')
    elif fault == 'add-static': write(repo, 'static/unreviewed.js', b'changed')
    elif fault == 'remove-static': (repo / 'static/index.html').unlink()
    elif fault == 'rename-static': (repo / 'static/index.html').rename(repo / 'static/renamed.html')
    elif fault == 'remove-allowed-root': (repo / 'home_assistant.py').unlink()
    else: write(repo, 'requirements.txt', b'changed dependency\n')
    refresh_evidence(env)
    with pytest.raises(ValueError): package.prepare(**env)
    assert not env['output_dir'].exists()


def test_rehashed_metadata_cannot_choose_its_own_runtime_exclusions(package_environment):
    result = package.prepare(**package_environment)
    checked = package.verify_package(package_environment['output_dir'], result['packageSha256'])
    meta, manifest = deepcopy(checked['metadata']), deepcopy(checked['manifest'])
    evidence = json.loads(package_environment['build_evidence'].read_bytes())
    for mapping in (meta['runtimeFiles'], meta['sourceFiles'], manifest['files']):
        mapping['finance_accounts.py'] = 'a' * 64
    meta['changedRuntimeFiles'] = list(package.CHANGED_RUNTIME_FILES | {'finance_accounts.py'})
    with pytest.raises(ValueError, match='99-file preservation'):
        policy.validate_maps(meta, manifest, evidence, baseline=package.BASELINE)


@pytest.mark.parametrize('fault', ['missing-shopping-test', 'missing-task-test', 'missing-prior-test',
                                  'unknown-frontend', 'docker', 'compose', 'nginx', 'frontend-dependency'])
def test_policy_rejects_missing_tests_and_deployment_or_dependency_drift(package_environment, fault):
    env = package_environment; repo = env['repo']
    if fault.startswith('missing-'):
        name = {'missing-shopping-test': 'shoppingSchedule.test.mjs', 'missing-task-test': 'taskPublish.test.mjs',
                'missing-prior-test': 'journeyBriefItems.test.mjs'}[fault]
        (repo / 'frontend/tests' / name).unlink()
    elif fault == 'unknown-frontend': write(repo, 'frontend/tests/unreviewed.test.mjs', b'// unreviewed\n')
    else:
        name = {'docker': 'Dockerfile', 'compose': 'compose.yaml', 'nginx': 'deploy/nginx.conf',
                'frontend-dependency': 'frontend/package.json'}[fault]
        write(repo, name, (repo / name).read_bytes() + b'\nchanged\n')
    refresh_evidence(env)
    with pytest.raises(ValueError): package.prepare(**env)
    assert not env['output_dir'].exists()


def test_non_frontend_followup_reuses_only_identical_build_inputs(package_environment):
    env = package_environment; built_head = env['commit']
    write(env['repo'], 'docs/RELEASE-NOTE.md', b'documentation only\n')
    write(env['repo'], 'deploy/reviewed-note.py', b'# non-runtime packaging note\n')
    env['commit'] = commit(env['repo'])
    result = package.prepare(**env)
    meta = package.verify_package(env['output_dir'], result['packageSha256'])['metadata']
    assert meta['buildSourceHead'] == built_head != meta['sourceHead']


def test_changed_frontend_cannot_reuse_old_export(package_environment):
    env = package_environment
    write(env['repo'], 'frontend/src/index.ts', b'changed frontend\n')
    env['commit'] = commit(env['repo'])
    with pytest.raises(ValueError, match='build source bytes differ'): package.prepare(**env)
    assert not env['output_dir'].exists()


def test_previous_profile_keeps104_file_hash_contract_without_history_checkout(package_environment):
    env = package_environment
    result = package.prepare(**env)
    checked = package.verify_package(env['output_dir'], result['packageSha256'])
    meta, manifest = deepcopy(checked['metadata']), deepcopy(checked['manifest'])
    evidence = json.loads(env['build_evidence'].read_bytes())
    meta.update(kind=previous_package.KIND, parentImage=previous_package.PARENT_IMAGE,
                oldManifestSha256=previous_package.OLD_MANIFEST)
    name = 'frontend/tests/shoppingSchedule.test.mjs'
    for mapping in (meta['sourceFiles'], manifest['files'], meta['inputFiles'], evidence['inputFiles']):
        mapping.pop(name)
    with pytest.raises(ValueError, match='104-file baseline'):
        policy.validate_maps(meta, manifest, evidence, baseline=previous_package.BASELINE)
    # Hash-contract fixture from the installed 28c738 package. The other 99
    # entries still use actual source bytes. No repository history or external
    # package is needed inside Linux validation; this is not an archive replay.
    old_hashes = {
        'app.py': '10324f4fe98eae4171ecac65db6f74e44a89301d2833a1312b67878f3721d688',
        'data_portability.py': '828d4fefb5c87d742bd03effaba99fd130678124f9126d0093d1de93e2c6085f',
        'home_assistant.py': '1cecdbf92ba777d2339512ff493c6adfc42bacaf6cc7766bbf4f85ded3ca1679',
        'journey_reschedule.py': 'dfdcd831598012719cd3f36dfd4cc3c032e19d62a231874dab5e260967f76bef',
        'journey_workflows.py': '5f6569ca2c8510c058bf0eaa41c5de40acc60b9f6aaaecdbe3a86c7a1de66f91',
    }
    for mapping in (meta['runtimeFiles'], meta['sourceFiles'], manifest['files']): mapping.update(old_hashes)
    policy.validate_maps(meta, manifest, evidence, baseline=previous_package.BASELINE)
    preserved = {n: h for n, h in meta['runtimeFiles'].items() if not n.startswith(policy.PREFIX)}
    assert policy.digest(policy.encoded(preserved)) == previous_package.NON_EXPO_RUNTIME_SHA256
    with pytest.raises(ValueError, match='installed parent differs'):
        policy.validate_maps(meta, manifest, evidence, baseline=package.BASELINE)


def test_default_profile_schema_and_frozen_source_selected_scope_remain_unchanged(environment):
    original = policy.prepare(**environment)
    meta = policy.verify_package(environment['output_dir'], original['packageSha256'])['metadata']
    assert meta['kind'] == 'membership-release-package' and meta['fixedFiles'] == policy.FIXED
    assert policy.baseline_values(previous_package.BASELINE) == (
        previous_package.KIND, previous_package.PARENT_IMAGE, previous_package.OLD_MANIFEST)
    assert previous_controller.SPEC.schema_pair == controller.SPEC.schema_pair == (69, 9)
    assert controller.SPEC.env_sha256 == previous_controller.SPEC.env_sha256
    with pytest.raises(FrozenInstanceError): controller.SPEC.schema_pair = (66, 9)
    with pytest.raises(ValueError, match='unsupported release baseline'): policy.baseline_values('plan-selected-profile')


@pytest.fixture
def assembly(package_environment, tmp_path, monkeypatch):
    monkeypatch.setattr(package_tests, 'steady', package)
    return package_tests.assembly.__wrapped__(package_environment, tmp_path)


def test_offline_plan_binds_new_entry_all25_operators_and_exact_evidence(assembly):
    result = package.assemble(**assembly)
    operator = controller.Controller(assembly['candidate'], result['planSha256'])
    assert result['assembled'] and not result['productionOperations']
    assert operator.validate_evidence() == {'tests': 1, 'passed': 1, 'skipped': 0}
    assert operator.plan['kind'] == 'shopping-schedule-release-plan'
    assert set(operator.plan['operatorHashes']) == {'deploy/' + n for n in controller.SPEC.operators}
    assert len(controller.SPEC.operators) == len(set(controller.SPEC.operators)) == 25
    with pytest.raises(common.ReleaseError, match='plan_kind'):
        previous_controller.Controller(assembly['candidate'], result['planSha256'])
    with pytest.raises(common.ReleaseError, match='new_and_separate'): package.assemble(**assembly)


@pytest.mark.parametrize('fault', ['old-parent', 'old-manifest', 'old-kind', 'environment', 'profile', 'data-reader'])
def test_plan_cannot_replace_baseline_or_shared_reader(assembly, fault):
    package.assemble(**assembly)
    path = assembly['candidate'] / 'release-plan.json'; value = json.loads(path.read_bytes())
    if fault == 'old-parent': value['parentImage'] = previous_package.PARENT_IMAGE
    elif fault == 'old-manifest': value['oldManifestSha256'] = previous_package.OLD_MANIFEST
    elif fault == 'old-kind': value['kind'] = previous_controller.SPEC.plan_kind
    elif fault == 'environment': value['envSha256'] = 'a' * 64
    else:
        name = 'build_shopping_schedule_release.py' if fault == 'profile' else 'assistant_trip_items_release_data.py'
        value['operatorHashes']['deploy/' + name] = 'a' * 64
    path.write_bytes(policy.encoded(value))
    with pytest.raises(common.ReleaseError):
        controller.Controller(assembly['candidate'], policy.digest(path.read_bytes()),
            runner=lambda *a, **k: pytest.fail('no external action during admission'))


@pytest.fixture
def baseline(tmp_path, monkeypatch):
    root, source = tmp_path / 'installed', tmp_path / 'candidate'
    root.mkdir(); source.mkdir()
    names = package.CHANGED_ROOT_FILES | {'task_publish.py', 'compose.yaml', 'requirements.txt',
                                         'Dockerfile', 'deploy/nginx.conf'}
    old = {}
    for name in names:
        raw = (ROOT / name).read_bytes(); write(root, name, raw); old[name] = common.sha(raw)
    manifest = root / 'RELEASE-MANIFEST.json'; manifest.write_bytes(policy.encoded({'files': old}))
    monkeypatch.setattr(controller.Controller, 'SPEC', replace(controller.SPEC, old_manifest=common.sha(manifest.read_bytes())))
    env = root / '.env'; env.write_bytes(b'SYNTHETIC=1\n'); env.chmod(0o600)
    if os.name == 'nt': monkeypatch.setattr(core.stat, 'S_IMODE', lambda _: 0o600)
    write(source, 'Dockerfile', (ROOT / 'Dockerfile').read_bytes())
    operator = object.__new__(controller.Controller)
    operator.root, operator.source, operator.files = root, source, dict(old)
    operator.plan = {'envSha256': common.sha(env.read_bytes())}
    calls = []
    operator.current_services = lambda image: calls.append(image) or {'recorded': True}
    return operator, calls


@pytest.mark.parametrize('name,allowed', [(n, True) for n in sorted(package.CHANGED_ROOT_FILES)] + [
    ('task_publish.py', False), ('finance_accounts.py', False), ('inventory_core.py', False), ('unexpected.py', False)])
def test_stage_source_scope_precedes_live_service_inspection(baseline, name, allowed):
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


def test_recorded69_lifecycle_preserves_group_before_workers_without_migration(simulation):
    operator, calls, programs, _ = simulation
    result = operator.activate()
    starts = [i for i, c in enumerate(calls) if isinstance(c, list) and c[:3] == ['docker', 'compose', 'up']]
    workers = next(i for i in starts if 'sync' in calls[i])
    assert calls.index('backup') < starts[0] < calls.index('check') < workers
    assert result['completed'] and result['householdTables'] == 69 and result['platformTables'] == 9
    assert result['stoppedBackup']['logicalSha256'] == result['preservation']['logicalSha256']
    assert 'migration' not in result and '/shopping-schedule-69-' in result['releaseDirectory'].replace('\\', '/')
    assert len(programs) == 2 and all('assistant_trip_items_release_data' in p for p in programs)
    assert all('.migrate(' not in p and 'warm_once' not in p for p in programs)


def test_stage_receipt_is69_to69_without_production_writes(simulation):
    operator = simulation[0]
    (operator.candidate / 'stage.json').unlink()  # Only the synthetic fixture receipt.
    result = operator.stage()
    assert result['schemaBefore'] == result['schemaAfter'] == [69, 9]
    assert result['productionWrites'] is False


@pytest.mark.parametrize('failed', ['backup', 'check'])
def test_failure_keeps_stopped_evidence_and_refuses_replay(simulation, failed):
    lifecycle.test_failed_data_phase_stops_and_cannot_replay_activation(simulation, failed)
