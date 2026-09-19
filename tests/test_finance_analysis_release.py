"""Fixed new baseline, immutable package and recorded migration failure order."""
import json
import os

import pytest
from deploy import finance_analysis_release_package as package
from deploy import finance_analysis_release_profile as profile
from deploy import finance_analysis_release_controller as controller
from deploy import finance_analysis_release_plan as plan
from deploy import membership_release_package as shared
from deploy import membership_release_controller as common
from test_membership_release_package import environment, write, commit, ROOT
from test_steady_release_controller import simulation as steady_simulation
from test_membership_release_controller import simulation as old_simulation
import test_steady_release_package as prior_package_tests


@pytest.fixture
def package_environment(environment):
    for name in plan.OPERATORS:
        write(environment['repo'], 'deploy/' + name, (ROOT / 'deploy' / name).read_bytes())
    write(environment['repo'], 'Dockerfile', (ROOT / 'Dockerfile').read_bytes())
    for name in profile.RUNTIME_ADDITIONS:
        write(environment['repo'], name, ('# synthetic ' + name + '\n').encode())
    environment['commit'] = commit(environment['repo'])
    return environment


def test_new_package_binds_three_runtime_additions_and_cannot_replay_consumed_baseline(package_environment):
    result = package.prepare(**package_environment)
    checked = package.verify_package(package_environment['output_dir'], result['packageSha256'])
    meta = checked['metadata']
    assert meta['kind'] == profile.KIND and meta['parentImage'] == profile.PARENT_IMAGE
    assert meta['oldManifestSha256'] == profile.OLD_MANIFEST
    assert profile.RUNTIME_ADDITIONS <= meta['runtimeFiles'].keys()
    assert meta['fixedFiles']['Dockerfile'] == profile.DOCKER_AFTER
    for old in (None, 'memberships-r3-steady', 'shopping-r1-steady', 'followup-r1-steady'):
        with pytest.raises(ValueError):
            shared.verify_package(package_environment['output_dir'], result['packageSha256'], baseline=old)


@pytest.mark.parametrize('fault', ['missing-core', 'missing-fx', 'docker-extra', 'old-docker'])
def test_packaging_failure_happens_before_output_creation(package_environment, fault):
    env = package_environment
    if fault.startswith('missing'):
        (env['repo'] / ('finance_analysis.py' if fault == 'missing-core' else 'finance_fx.py')).unlink()
    else:
        path = env['repo'] / 'Dockerfile'
        raw = path.read_bytes()
        path.write_bytes(raw + b'RUN echo extra\n' if fault == 'docker-extra' else raw.replace(profile.COPY_AFTER, profile.COPY_BEFORE))
    env['commit'] = commit(env['repo'])
    with pytest.raises(ValueError):
        package.prepare(**env)
    assert not env['output_dir'].exists()


def test_historical_export_bound_and_new_exact_evidence_partition_remain_separate():
    minimal = {'index.html', 'metadata.json', '_expo/static/js/web/entry-one.js'}
    shared.validate_export_names(minimal, baseline=profile.BASELINE)
    with pytest.raises(ValueError, match='23-file'):
        shared.validate_export_names(minimal)
    with pytest.raises(ValueError, match='exactly one'):
        shared.validate_export_names(minimal | {'_expo/static/js/web/entry-two.js'}, baseline=profile.BASELINE)


@pytest.fixture
def assembly(package_environment, tmp_path, monkeypatch):
    # Reuse synthetic evidence construction, with this fixed new package identity.
    monkeypatch.setattr(prior_package_tests, 'steady', package)
    return prior_package_tests.assembly.__wrapped__(package_environment, tmp_path)


def test_offline_new_plan_binds_all_operators_and_exact_junit(assembly):
    result = plan.assemble(**assembly)
    assert result['assembled'] and result['reviewRequired'] and not result['productionOperations']
    operator = controller.Controller(assembly['candidate'], result['planSha256'])
    assert operator.validate_evidence() == {'tests': 1, 'passed': 1, 'skipped': 0}
    assert operator.plan['kind'] == 'finance-analysis-release-plan'
    assert set(operator.plan['operatorHashes']) == {'deploy/' + name for name in plan.OPERATORS}
    with pytest.raises(common.ReleaseError, match='new_and_separate'):
        plan.assemble(**assembly)


@pytest.mark.parametrize('changed', ['build', 'source', 'selection'])
def test_offline_plan_rejects_changed_evidence(assembly, changed):
    if changed == 'build':
        path = assembly['build_dir'] / 'build.json'; value = json.loads(path.read_bytes())
        value['parentImage'] = shared.PARENT_IMAGE
        path.write_bytes(shared.encoded(value)); assembly['build_sha256'] = shared.digest(path.read_bytes())
    elif changed == 'source':
        (assembly['validation_dir'] / 'proof/runtime.json').write_bytes(b'{}')
    else:
        path = assembly['reviews'].parent / 'selection.json'
        value = json.loads(path.read_bytes()); value['nodeids'] = ['tests/test_synthetic.py::test_changed']
        path.write_bytes(shared.encoded(value))
    with pytest.raises((ValueError, common.ReleaseError)):
        plan.assemble(**assembly)


@pytest.fixture
def simulation(steady_simulation):
    operator, calls, programs, old = steady_simulation
    operator.__class__ = controller.Controller
    def data_call(proof, program, **kwargs):
        programs.append(program)
        calls.append('backup' if '.begin(' in program else 'migrate' if '.migrate(' in program else 'check')
        return {'verified': True, 'logicalSha256': 'f' * 64}
    operator.data_call = data_call
    return operator, calls, programs, old


def test_full_backup_then_five_table_migration_then_app_preservation_before_workers(simulation):
    operator, calls, programs, old = simulation
    result = operator.activate()
    starts = [i for i, c in enumerate(calls) if isinstance(c, list) and c[:3] == ['docker', 'compose', 'up']]
    workers = next(i for i in starts if 'sync' in calls[i])
    assert calls.index('backup') < calls.index('migrate') < starts[0] < calls.index('check') < workers
    assert len(programs) == 3 and not any('warm_once' in p for p in programs)
    assert result['completed'] and result['householdTables'] == 66 and result['platformTables'] == 9
    assert 'migration' in result and 'preservation' in result


@pytest.mark.parametrize('failed', ['backup', 'migrate', 'check'])
def test_failed_data_phase_stops_and_cannot_replay_activation(simulation, failed):
    operator, calls, _, old = simulation
    original = operator.data_call
    def failing(proof, program, **kwargs):
        phase = 'backup' if '.begin(' in program else 'migrate' if '.migrate(' in program else 'check'
        if phase == failed:
            raise common.ReleaseError('synthetic_data_failure')
        return original(proof, program, **kwargs)
    operator.data_call = failing
    with pytest.raises(common.ReleaseError, match='synthetic_data_failure'):
        operator.activate()
    assert not any(isinstance(c, list) and c[:3] == ['docker', 'compose', 'up'] and 'sync' in c for c in calls)
    record = common.read(operator.candidate / 'activation.json')
    assert not record['completed']
    if failed != 'check':
        assert (operator.root / 'app.py').read_bytes() == old['app.py']
    else:
        assert record['candidateStoppedAfterFailure']
    with pytest.raises(FileExistsError):
        operator.activate()


@pytest.fixture
def baseline(tmp_path, monkeypatch):
    root = tmp_path / 'installed'; root.mkdir()
    source = tmp_path / 'candidate'; source.mkdir()
    old = {}
    for name in ('app.py', 'finance_accounts.py', 'compose.yaml', 'requirements.txt', 'Dockerfile', 'deploy/nginx.conf'):
        raw = (ROOT / name).read_bytes()
        if name == 'Dockerfile':
            raw = raw.replace(profile.COPY_AFTER, profile.COPY_BEFORE)
        path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        old[name] = common.sha(raw)
    manifest = root / 'RELEASE-MANIFEST.json'; manifest.write_text(json.dumps({'files': old}))
    monkeypatch.setattr(controller, 'OLD_MANIFEST', common.sha(manifest.read_bytes()))
    env = root / '.env'; env.write_bytes(b'SYNTHETIC=1\n'); env.chmod(0o600)
    if os.name == 'nt':
        monkeypatch.setattr(controller.stat, 'S_IMODE', lambda _: 0o600)
    (source / 'Dockerfile').write_bytes((ROOT / 'Dockerfile').read_bytes())
    operator = object.__new__(controller.Controller)
    operator.root, operator.source = root, source
    operator.files = {**old, 'Dockerfile': profile.DOCKER_AFTER}
    operator.plan = {'envSha256': common.sha(env.read_bytes())}
    calls = []
    operator.current_services = lambda image: calls.append(image) or {'recorded': True}
    return operator, calls


@pytest.mark.parametrize('path,allowed', [('app.py', True), ('data_portability.py', True),
    ('finance_analysis.py', True), ('finance_fx.py', True), ('finance_accounts.py', False),
    ('inventory_core.py', False), ('unexpected.py', False)])
def test_exact_source_scope_before_live_service_inspection(baseline, path, allowed):
    operator, calls = baseline
    operator.files[path] = 'a' * 64
    if allowed:
        operator.baseline()
        assert calls == [profile.PARENT_IMAGE]
    else:
        with pytest.raises(common.ReleaseError, match='unsupported_source_change'):
            operator.baseline()
        assert calls == []
