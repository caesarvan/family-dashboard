"""Recording controller faults, no Docker or production execution."""
import json
import os
from pathlib import Path

import pytest
from deploy import steady_release_controller as steady
from deploy import membership_release_controller as shared
from test_membership_release_controller import simulation as old_simulation


@pytest.fixture
def simulation(old_simulation, monkeypatch):
    operator, calls, data_calls, old = old_simulation
    operator.__class__ = steady.Controller
    operator.marker_preflight = lambda: calls.append('marker_checked')
    if os.name == 'nt':
        # Recording controller only: Windows chmod does not implement POSIX
        # owner-only bits. The real CLI admits Linux exclusively.
        monkeypatch.setattr(steady.stat, 'S_IMODE', lambda mode: 0o600)
    old_files, services = operator.baseline()
    for name in ('sync', 'media'):
        services[name]['environmentSha256'] = shared.sha(shared.runtime_environment(operator.inspect(services[name]['id'])['Config']['Env']))
    path = operator.candidate / 'stage.json'
    record = json.loads(path.read_bytes()); record['services'] = services
    path.write_text(json.dumps(record))
    def data_call(proof, program, **kwargs):
        data_calls.append(program)
        calls.append('backup' if 'steady.begin(' in program else 'check')
        return {'verified': True, 'logicalSha256': 'f' * 64}
    operator.data_call = data_call
    return operator, calls, data_calls, old


def test_starts_workers_only_after_whole_group_preservation(simulation):
    operator, calls, programs, old = simulation
    result = operator.activate()
    workers = next(i for i, c in enumerate(calls) if isinstance(c, list) and c[:3] == ['docker', 'compose', 'up'] and 'sync' in c)
    first_app = next(i for i, c in enumerate(calls) if isinstance(c, list) and c[:3] == ['docker', 'compose', 'up'])
    assert calls.index('backup') < first_app < calls.index('check') < workers
    assert calls.index('marker_checked') < next(i for i, c in enumerate(calls) if isinstance(c, list) and c[:2] == ['systemctl', 'stop'])
    assert len(programs) == 2 and not any('warm_once' in p for p in programs)
    assert result['completed'] and 'preservation' in result and 'migration' not in result
    assert result['householdTables'] == 61 and result['platformTables'] == 9
    assert (Path(result['releaseDirectory']) / 'source-before/app.py').read_bytes() == old['app.py']
    assert calls[-1] == ['systemctl', 'is-active', 'family-dashboard-backup.timer']


@pytest.mark.parametrize('failed', ['backup', 'check'])
def test_data_failure_preserves_attempt_and_never_starts_workers(simulation, failed):
    operator, calls, _, old = simulation
    original = operator.data_call
    def data_call(proof, program, **kwargs):
        if (failed == 'backup') == ('steady.begin(' in program):
            raise shared.ReleaseError('synthetic_data_failure')
        return original(proof, program, **kwargs)
    operator.data_call = data_call
    with pytest.raises(shared.ReleaseError, match='synthetic_data_failure'):
        operator.activate()
    report = shared.read(operator.candidate / 'activation.json')
    assert report['completed'] is False
    assert not any(isinstance(c, list) and c[:3] == ['docker', 'compose', 'up'] and 'sync' in c for c in calls)
    if failed == 'backup':
        assert (operator.root / 'app.py').read_bytes() == old['app.py']
    else:
        assert report['candidateStoppedAfterFailure'] is True
    original_report = (operator.candidate / 'activation.json').read_bytes()
    with pytest.raises(FileExistsError):
        operator.activate()
    assert (operator.candidate / 'activation.json').read_bytes() == original_report


@pytest.mark.parametrize('window', ['first_app', 'health', 'runtime', 'worker', 'public_health', 'timer'])
def test_partial_start_failure_stops_candidate_without_restore(simulation, window):
    operator, calls, _, _ = simulation
    original_run, original_inspect = operator.runner, operator.inspect
    def run(args, **kwargs):
        if (window == 'first_app' and args[:3] == ['docker', 'compose', 'up'] or
            window == 'runtime' and args[:2] == ['docker', 'exec'] or
            window == 'worker' and args[:3] == ['docker', 'compose', 'up'] and 'sync' in args or
            window == 'public_health' and args[0] == 'curl' or
            window == 'timer' and args[:2] == ['systemctl', 'start']):
            calls.append(['injected', window])
            raise shared.ReleaseError('synthetic_start_failure')
        return original_run(args, **kwargs)
    operator.runner = run
    if window == 'health':
        def inspect(ref):
            value = original_inspect(ref)
            if ref == 'family-dashboard-app-1':
                calls.append(['injected', window])
                value['State']['Health']['Status'] = 'unhealthy'
            return value
        operator.inspect = inspect
    with pytest.raises(shared.ReleaseError):
        operator.activate()
    record = shared.read(operator.candidate / 'activation.json')
    assert record['completed'] is False and record['candidateStoppedAfterFailure'] is True
    assert ['injected', window] in calls
    assert calls[-1][:3] == ['docker', 'ps', '-q']


def test_cleanup_failure_does_not_claim_stopped(simulation):
    operator, calls, _, _ = simulation
    original = operator.runner
    def run(args, **kwargs):
        if args[:3] == ['docker', 'compose', 'up']:
            raise shared.ReleaseError('synthetic_start_failure')
        if operator.candidate_started and args[:3] == ['docker', 'compose', 'stop']:
            raise shared.ReleaseError('synthetic_stop_failure')
        return original(args, **kwargs)
    operator.runner = run
    with pytest.raises(shared.ReleaseError):
        operator.activate()
    assert shared.read(operator.candidate / 'activation.json')['candidateStoppedAfterFailure'] is False


@pytest.mark.parametrize('change', ['order', 'value', 'duplicate', 'newline', 'bound-file'])
def test_environment_reordering_only_is_accepted(simulation, tmp_path, change):
    operator, _, _, _ = simulation
    env = ['DATA_DIR=/data', 'SECRET_KEY=literal-$"#=x', 'EMPTY=']
    binding = tmp_path / 'app-runtime.env'; binding.write_bytes(shared.runtime_environment(env))
    binding.chmod(0o600)
    operator.data_environment = (binding, shared.sha(binding.read_bytes()))
    operator.service_environments = {'app': operator.data_environment}
    observed = list(reversed(env))
    if change == 'value': observed[1] += 'changed'
    if change == 'duplicate': observed += ['EMPTY=']
    if change == 'newline': observed[1] += '\nINJECTED=1'
    if change == 'bound-file': binding.write_bytes(b'changed')
    operator.inspect = lambda ref: {'Config': {'Env': observed}}
    if change == 'order':
        operator.check_environment('synthetic')
    else:
        with pytest.raises(shared.ReleaseError):
            operator.check_environment('synthetic')


def test_stage_drift_fails_before_stop_or_backup(simulation):
    operator, calls, _, _ = simulation
    path = operator.candidate / 'stage.json'
    record = json.loads(path.read_bytes()); record['services']['app']['environmentSha256'] = '0' * 64
    path.write_text(json.dumps(record))
    with pytest.raises(shared.ReleaseError, match='stage_baseline_changed'):
        operator.activate()
    assert not (operator.candidate / 'activation.json').exists()
    assert 'backup' not in calls


def test_workers_keep_their_own_distinct_resolved_environment(simulation):
    operator, calls, _, _ = simulation
    inspect = operator.inspect
    def distinct(reference):
        value = inspect(reference)
        if reference.endswith(('-sync', '-media')):
            value['Config']['Env'] = ['DATA_DIR=/data', 'WORKER_VALUE=synthetic-only']
        return value
    operator.inspect = distinct
    _, services = operator.baseline()
    for name in ('sync', 'media'):
        services[name]['environmentSha256'] = shared.sha(shared.runtime_environment(distinct(services[name]['id'])['Config']['Env']))
    path = operator.candidate / 'stage.json'; record = json.loads(path.read_bytes()); record['services'] = services
    path.write_text(json.dumps(record))
    assert operator.activate()['completed'] is True


def test_worker_environment_drift_is_rejected_before_stop(simulation):
    operator, calls, _, _ = simulation
    inspect = operator.inspect
    def changed(reference):
        value = inspect(reference)
        if reference == 'old-media':
            value['Config']['Env'] = ['DATA_DIR=/data', 'CHANGED=1']
        return value
    operator.inspect = changed
    with pytest.raises(shared.ReleaseError, match='runtime_environment_changed'):
        operator.activate()
    assert not any(isinstance(c, list) and c[:3] == ['docker', 'compose', 'stop'] for c in calls)
    assert 'backup' not in calls


@pytest.mark.parametrize('fault', ['missing', 'changed'])
def test_marker_preflight_refuses_before_service_stop(simulation, fault):
    operator, calls, _, _ = simulation
    operator.marker_preflight = lambda: steady.Controller.marker_preflight(operator)
    original = operator.runner
    def runner(args, **kwargs):
        if args[:2] == ['docker', 'run']:
            assert steady.VOLUME + ':/data:ro' in args and '--network' in args
            assert '--env-file' not in args and args[-1] == steady.MARKER_PROGRAM
            if fault == 'missing':
                raise shared.ReleaseError('command_failed')
            return b'changed-marker'
        return original(args, **kwargs)
    operator.runner = runner
    with pytest.raises(shared.ReleaseError):
        operator.activate()
    assert not (operator.candidate / 'activation.json').exists()
    assert not any(isinstance(c, list) and c[:2] == ['systemctl', 'stop'] for c in calls)


@pytest.mark.parametrize('changed,allowed', [('app.py', True), ('inventory_api.py', True), ('finance_hub.py', False)])
def test_followup_baseline_only_expands_to_registered_app_adapter(tmp_path, monkeypatch, changed, allowed):
    """Real files and admission checks; service inspection alone is recorded."""
    root = tmp_path / 'installed'; root.mkdir()
    names = ('app.py', 'inventory_api.py', 'finance_hub.py', 'compose.yaml',
             'Dockerfile', 'requirements.txt', 'deploy/nginx.conf')
    old = {}
    for name in names:
        path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(('synthetic original ' + name).encode())
        old[name] = shared.sha(path.read_bytes())
    manifest = root / 'RELEASE-MANIFEST.json'
    manifest.write_text(json.dumps({'files': old}), encoding='utf-8')
    monkeypatch.setattr(steady, 'OLD_MANIFEST', shared.sha(manifest.read_bytes()))
    env = root / '.env'; env.write_bytes(b'SYNTHETIC_ONLY=1\n'); env.chmod(0o600)
    if os.name == 'nt':
        monkeypatch.setattr(steady.stat, 'S_IMODE', lambda mode: 0o600)
    operator = object.__new__(steady.Controller)
    operator.root = root
    operator.files = {**old, changed: shared.sha(b'candidate adapter')}
    operator.plan = {'envSha256': shared.sha(env.read_bytes())}
    inspected = []
    operator.current_services = lambda image: inspected.append(image) or {'recorded': True}
    if allowed:
        assert operator.baseline() == (old, {'recorded': True})
        assert inspected == [steady.PARENT_IMAGE]
    else:
        with pytest.raises(shared.ReleaseError, match='unsupported_source_change'):
            operator.baseline()
        assert inspected == []
