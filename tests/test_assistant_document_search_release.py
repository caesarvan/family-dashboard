"""Fixed 102-file preservation, real temporary packaging and recorded 69/9 lifecycle.

No business app, Docker, production database or network is invoked.
"""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
import os
import subprocess
import sys

import pytest
from deploy import build_assistant_document_search_release as package
from deploy import activate_assistant_document_search_release as controller
from deploy import build_shopping_schedule_release as previous_package
from deploy import activate_shopping_schedule_release as previous_controller
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
    preserved = {n: policy.digest((repo / n).read_bytes()) for n in runtime if n not in package.CHANGED_RUNTIME_FILES}
    assert len(runtime) == package.NON_EXPO_RUNTIME_COUNT == 104
    assert len(preserved) == package.PRESERVED_RUNTIME_COUNT == 102
    assert policy.digest(policy.encoded(preserved)) == package.PRESERVED_RUNTIME_SHA256
    for name in package.FRONTEND_TESTS:
        write(repo, name, b'// synthetic frontend test\n')
    refresh_evidence(environment)
    return environment


def test_package_roundtrip_only_two_runtime_exclusions_and_required_frontend_evidence(package_environment):
    env = package_environment
    assert package.CHANGED_RUNTIME_FILES == {'home_assistant.py', 'journey_documents.py'}
    for name in package.CHANGED_ROOT_FILES:
        write(env['repo'], name, (env['repo'] / name).read_bytes() + b'\n# reviewed synthetic delta\n')
    refresh_evidence(env)
    result = package.prepare(**env)
    meta = package.verify_package(env['output_dir'], result['packageSha256'])['metadata']
    assert (meta['kind'], meta['parentImage'], meta['oldManifestSha256']) == (package.KIND, package.PARENT_IMAGE, package.OLD_MANIFEST)
    kept = {n: h for n, h in meta['runtimeFiles'].items() if not n.startswith(policy.PREFIX) and n not in package.CHANGED_RUNTIME_FILES}
    assert len(kept) == 102 and policy.digest(policy.encoded(kept)) == package.PRESERVED_RUNTIME_SHA256
    assert package.FRONTEND_TESTS <= meta['sourceFiles'].keys()
    assert package.FRONTEND_TESTS - previous_package.FRONTEND_TESTS == {'frontend/tests/assistantDocumentSearch.test.mjs'}
    assert meta['fixedFiles'] == {**policy.FIXED, 'Dockerfile': package.DOCKER_AFTER}
    for baseline in (None, previous_package.BASELINE):
        with pytest.raises(ValueError): policy.verify_package(env['output_dir'], result['packageSha256'], baseline=baseline)
    with pytest.raises(ValueError, match='output must be new'): package.prepare(**env)


@pytest.mark.parametrize('fault', ['previously-allowed-app', 'other-backend', 'legacy-static', 'add-static',
                                  'remove-static', 'rename-static', 'requirements', 'remove-required-root'])
def test_non_expo_scope_drift_fails_before_output(package_environment, fault):
    env = package_environment; repo = env['repo']
    if fault == 'previously-allowed-app': write(repo, 'app.py', b'# forbidden new app delta\n')
    elif fault == 'other-backend': write(repo, 'task_publish.py', b'# forbidden delta\n')
    elif fault == 'legacy-static': write(repo, 'static/index.html', b'<p>changed</p>')
    elif fault == 'add-static': write(repo, 'static/unreviewed.js', b'changed')
    elif fault == 'remove-static': (repo / 'static/index.html').unlink()
    elif fault == 'rename-static': (repo / 'static/index.html').rename(repo / 'static/renamed.html')
    elif fault == 'remove-required-root': (repo / 'journey_documents.py').unlink()
    else: write(repo, 'requirements.txt', b'changed dependency\n')
    refresh_evidence(env)
    with pytest.raises(ValueError): package.prepare(**env)
    assert not env['output_dir'].exists()


def test_rehashing_metadata_cannot_exempt_an_extra_runtime_file(package_environment):
    result = package.prepare(**package_environment)
    checked = package.verify_package(package_environment['output_dir'], result['packageSha256'])
    meta, manifest = deepcopy(checked['metadata']), deepcopy(checked['manifest'])
    evidence = json.loads(package_environment['build_evidence'].read_bytes())
    for mapping in (meta['runtimeFiles'], meta['sourceFiles'], manifest['files']): mapping['app.py'] = 'a' * 64
    meta['changedRuntimeFiles'] = list(package.CHANGED_RUNTIME_FILES | {'app.py'})
    with pytest.raises(ValueError, match='102-file preservation'):
        policy.validate_maps(meta, manifest, evidence, baseline=package.BASELINE)


@pytest.mark.parametrize('fault', ['missing-new-test', 'missing-shopping-test', 'unknown-frontend-test',
                                  'docker', 'compose', 'nginx', 'frontend-dependency'])
def test_required_frontend_and_deployment_pins_fail_closed(package_environment, fault):
    env = package_environment; repo = env['repo']
    if fault.startswith('missing-'):
        name = 'assistantDocumentSearch.test.mjs' if fault == 'missing-new-test' else 'shoppingSchedule.test.mjs'
        (repo / 'frontend/tests' / name).unlink()
    elif fault == 'unknown-frontend-test': write(repo, 'frontend/tests/unreviewed.test.mjs', b'// unexpected\n')
    else:
        name = {'docker': 'Dockerfile', 'compose': 'compose.yaml', 'nginx': 'deploy/nginx.conf', 'frontend-dependency': 'frontend/package.json'}[fault]
        write(repo, name, (repo / name).read_bytes() + b'\nchanged\n')
    refresh_evidence(env)
    with pytest.raises(ValueError): package.prepare(**env)
    assert not env['output_dir'].exists()


@pytest.mark.parametrize('frontend_changed', [False, True])
def test_ancestor_export_reuse_requires_identical_frontend_bytes(package_environment, frontend_changed):
    env = package_environment; build_head = env['commit']
    write(env['repo'], 'frontend/src/index.ts' if frontend_changed else 'docs/REVIEWED.md', b'updated\n')
    env['commit'] = commit(env['repo'])
    if frontend_changed:
        with pytest.raises(ValueError, match='build source bytes differ'): package.prepare(**env)
        assert not env['output_dir'].exists()
    else:
        result = package.prepare(**env)
        meta = package.verify_package(env['output_dir'], result['packageSha256'])['metadata']
        assert meta['buildSourceHead'] == build_head != meta['sourceHead']


def test_old_shopping_policy_and_default_remain_separate(package_environment):
    env = package_environment
    result = package.prepare(**env)
    checked = package.verify_package(env['output_dir'], result['packageSha256'])
    meta, manifest = deepcopy(checked['metadata']), deepcopy(checked['manifest'])
    evidence = json.loads(env['build_evidence'].read_bytes())
    meta.update(kind=previous_package.KIND, parentImage=previous_package.PARENT_IMAGE, oldManifestSha256=previous_package.OLD_MANIFEST)
    name = 'frontend/tests/assistantDocumentSearch.test.mjs'
    for mapping in (meta['sourceFiles'], manifest['files'], meta['inputFiles'], evidence['inputFiles']): mapping.pop(name)
    with pytest.raises(ValueError, match='99-file preservation'):
        policy.validate_maps(meta, manifest, evidence, baseline=previous_package.BASELINE)
    # Verified installed 6bf6c8 package hash contract; not a fake production pin,
    # not an archive replay, and no Git-history dependency inside Linux tests.
    for mapping in (meta['runtimeFiles'], meta['sourceFiles'], manifest['files']):
        mapping['journey_documents.py'] = '68b2aa3e035abe3bf39a3bff70e9e291d3e27ea3cccaf6caf3b58c880afa8602'
    policy.validate_maps(meta, manifest, evidence, baseline=previous_package.BASELINE)
    assert policy.baseline_values(None)[0] == 'membership-release-package'
    assert previous_controller.SPEC.schema_pair == controller.SPEC.schema_pair == (69, 9)
    assert previous_controller.SPEC.env_sha256 == controller.SPEC.env_sha256
    with pytest.raises(FrozenInstanceError): controller.SPEC.schema_pair = (66, 9)
    with pytest.raises(ValueError, match='unsupported release baseline'): policy.baseline_values('json-selected-profile')


@pytest.fixture
def assembly(package_environment, tmp_path, monkeypatch):
    monkeypatch.setattr(package_tests, 'steady', package)
    return package_tests.assembly.__wrapped__(package_environment, tmp_path)


def test_offline_plan_binds27_operators_and_exact_package_evidence(assembly):
    result = package.assemble(**assembly)
    operator = controller.Controller(assembly['candidate'], result['planSha256'])
    assert result['assembled'] and not result['productionOperations']
    assert operator.validate_evidence() == {'tests': 1, 'passed': 1, 'skipped': 0}
    assert operator.plan['kind'] == 'assistant-document-search-release-plan'
    assert set(operator.plan['operatorHashes']) == {'deploy/' + n for n in controller.SPEC.operators}
    assert len(controller.SPEC.operators) == len(set(controller.SPEC.operators)) == 27
    with pytest.raises(common.ReleaseError, match='plan_kind'): previous_controller.Controller(assembly['candidate'], result['planSha256'])
    with pytest.raises(common.ReleaseError, match='new_and_separate'): package.assemble(**assembly)


@pytest.mark.parametrize('fault', ['parent', 'manifest', 'kind', 'environment', 'profile', 'data-reader'])
def test_plan_cannot_replace_source_selected_baseline(assembly, fault):
    package.assemble(**assembly)
    path = assembly['candidate'] / 'release-plan.json'; value = json.loads(path.read_bytes())
    if fault == 'parent': value['parentImage'] = previous_package.PARENT_IMAGE
    elif fault == 'manifest': value['oldManifestSha256'] = previous_package.OLD_MANIFEST
    elif fault == 'kind': value['kind'] = previous_controller.SPEC.plan_kind
    elif fault == 'environment': value['envSha256'] = 'a' * 64
    else:
        name = 'build_assistant_document_search_release.py' if fault == 'profile' else 'assistant_trip_items_release_data.py'
        value['operatorHashes']['deploy/' + name] = 'a' * 64
    path.write_bytes(policy.encoded(value))
    with pytest.raises(common.ReleaseError):
        controller.Controller(assembly['candidate'], policy.digest(path.read_bytes()), runner=lambda *a, **k: pytest.fail('no external admission action'))


@pytest.fixture
def baseline(tmp_path, monkeypatch):
    root, source = tmp_path / 'installed', tmp_path / 'candidate'
    root.mkdir(); source.mkdir()
    names = package.CHANGED_ROOT_FILES | {'app.py', 'compose.yaml', 'requirements.txt', 'Dockerfile', 'deploy/nginx.conf'}
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
    calls = []; operator.current_services = lambda image: calls.append(image) or {'recorded': True}
    return operator, calls


@pytest.mark.parametrize('name,allowed', [('home_assistant.py', True), ('journey_documents.py', True), ('README.md', True),
                                        ('app.py', False), ('data_portability.py', False), ('task_publish.py', False)])
def test_runtime_scope_checked_before_service_inspection(baseline, name, allowed):
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


def test_recorded_lifecycle_preserves69_9_before_workers_without_migration(simulation):
    operator, calls, programs, _ = simulation
    result = operator.activate()
    starts = [i for i, c in enumerate(calls) if isinstance(c, list) and c[:3] == ['docker', 'compose', 'up']]
    workers = next(i for i in starts if 'sync' in calls[i])
    assert calls.index('backup') < starts[0] < calls.index('check') < workers
    assert result['completed'] and (result['householdTables'], result['platformTables']) == (69, 9)
    assert result['stoppedBackup']['logicalSha256'] == result['preservation']['logicalSha256']
    assert 'migration' not in result and '/assistant-document-search-69-' in result['releaseDirectory'].replace('\\', '/')
    assert len(programs) == 2 and all('assistant_trip_items_release_data' in p for p in programs)
    assert all('.migrate(' not in p and 'warm_once' not in p for p in programs)


def test_stage_receipt_keeps69_9_and_records_no_production_writes(simulation):
    operator = simulation[0]
    (operator.candidate / 'stage.json').unlink()  # Only this synthetic receipt.
    result = operator.stage()
    assert result['schemaBefore'] == result['schemaAfter'] == [69, 9] and result['productionWrites'] is False


@pytest.mark.parametrize('failed', ['backup', 'check'])
def test_failure_preserves_stopped_evidence_and_rejects_replay(simulation, failed):
    lifecycle.test_failed_data_phase_stops_and_cannot_replay_activation(simulation, failed)


@pytest.mark.parametrize('entry,schema', [
    ('assistant_trip_change_release_controller.py', '66/9'),
    ('activate_shopping_schedule_release.py', '69/9'),
    ('activate_assistant_document_search_release.py', '69/9'),
])
def test_entry_help_reports_actual_selected_schema_without_activation(entry, schema):
    result = subprocess.run([sys.executable, '-B', str(ROOT / 'deploy' / entry), '--help'],
                            cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0 and not result.stderr
    assert f'Reviewed {schema} source update' in result.stdout
    assert f'stopped {schema} group' in result.stdout
    assert ('66/9' if schema == '69/9' else '69/9') not in result.stdout
