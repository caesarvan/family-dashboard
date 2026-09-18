"""Release admission and destructive-step order, without Docker or production."""
import hashlib
import json
from pathlib import Path

import pytest

from deploy import membership_release_controller as release


@pytest.mark.parametrize('value', ['../data', '/tmp/file', 'a/../b', 'a\\b', 'a:b', './file', ''])
def test_manifest_path_cannot_escape(value):
    with pytest.raises(release.ReleaseError):
        release.relative(value)


def test_duplicate_evidence_fields_rejected(tmp_path):
    path = tmp_path / 'proof.json'
    path.write_text('{"image":"first","image":"second"}')
    with pytest.raises(release.ReleaseError, match='duplicate_json_key'):
        release.read(path)


def test_exclusive_evidence_retains_original(tmp_path):
    path = tmp_path / 'proof.json'
    release.put(path, {'state': 'failed'})
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        release.put(path, {'state': 'passed'})
    assert path.read_bytes() == before


@pytest.mark.parametrize('kind', ['failure', 'error', 'skip', 'duplicate', 'wrong_case', 'summary'])
def test_junit_rejects_incomplete_or_changed_results(tmp_path, kind):
    inside = {'failure': '<failure/>', 'error': '<error/>', 'skip': '<skipped message="unavailable"/>',
              'duplicate': '', 'wrong_case': '', 'summary': ''}[kind]
    case = '<testcase classname="tests.test_a" name="test_one">' + inside + '</testcase>'
    count = 1
    if kind == 'duplicate':
        case += case
        count = 2
    if kind == 'summary':
        count = 5
    path = tmp_path / 'results.xml'
    path.write_text(f'<testsuites><testsuite tests="{count}" failures="0" errors="0" skipped="0">{case}</testsuite></testsuites>')
    expected = [['tests.test_a', 'test_other' if kind == 'wrong_case' else 'test_one']]
    with pytest.raises(release.ReleaseError):
        release.verify_junit(path, expected, [])


def test_junit_only_accepts_exact_platform_skip(tmp_path):
    path = tmp_path / 'results.xml'
    path.write_text('<testsuites><testsuite tests="2" failures="0" errors="0" skipped="1">'
                    '<testcase classname="tests.test_a" name="test_one"/>'
                    '<testcase classname="tests.test_frontend_runtime" name="test_windows_junction_rejected">'
                    '<skipped message="Windows junction semantics"/></testcase></testsuite></testsuites>')
    cases = [['tests.test_a', 'test_one'], ['tests.test_frontend_runtime', 'test_windows_junction_rejected']]
    allowed = [{'classname': cases[1][0], 'name': cases[1][1], 'message': 'Windows junction semantics'}]
    assert release.verify_junit(path, cases, allowed) == {'tests': 2, 'passed': 1, 'skipped': 1}
    with pytest.raises(release.ReleaseError):
        release.verify_junit(path, cases, [])


def test_source_check_rejects_unlisted_runtime_and_static_files(tmp_path):
    (tmp_path / 'static').mkdir()
    (tmp_path / 'app.py').write_bytes(b'known')
    expected = {'app.py': release.sha(b'known')}
    release.source_hashes(tmp_path, expected)
    extra = tmp_path / 'static/private-copy.json'
    extra.write_bytes(b'private')
    with pytest.raises(release.ReleaseError, match='unexpected_static_files'):
        release.source_hashes(tmp_path, expected)
    extra.unlink()
    (tmp_path / 'unreviewed.py').write_bytes(b'unknown')
    with pytest.raises(release.ReleaseError, match='unexpected_runtime_module'):
        release.source_hashes(tmp_path, expected)


@pytest.fixture
def simulation(tmp_path, monkeypatch):
    root = tmp_path / 'installation'
    source = tmp_path / 'candidate/source'
    candidate = source.parent
    releases = tmp_path / 'releases'
    releases.mkdir()
    for folder in (root, source):
        (folder / 'static/experience').mkdir(parents=True)
    old = {'app.py': b'old app', 'static/experience/index.html': b'old entry'}
    new = {'app.py': b'new app', 'static/experience/index.html': b'new entry'}
    for folder, blobs in ((root, old), (source, new)):
        for name, raw in blobs.items():
            (folder / name).write_bytes(raw)
        release.put(folder / 'RELEASE-MANIFEST.json', {'files': {n: release.sha(b) for n,b in blobs.items()}})
    release.put(root / '.env', b'SYNTHETIC_ONLY=1\n')
    controller = release.Controller.__new__(release.Controller)
    controller.root, controller.releases, controller.candidate, controller.source = root, releases, candidate, source
    controller.plan_sha = 'd' * 64
    controller.plan = {'imageId': 'sha256:' + '1' * 64, 'envSha256': release.sha((root / '.env').read_bytes())}
    controller.files = {n: release.sha(b) for n,b in new.items()}
    controller.runtime = dict(controller.files)
    controller.package = {'sourceHead': 'a' * 40, 'tree': 'b' * 40}
    services = {n: {'id': 'old-' + n, 'image': release.WEB_IMAGE if n == 'web' else release.PARENT_IMAGE} for n in release.SERVICES}
    environment = ['DATA_DIR=/data', 'PUBLIC_ORIGIN=https://example.invalid', 'SECRET_KEY=synthetic-$quote"#=value']
    services['app']['environmentSha256'] = release.sha(release.runtime_environment(environment))
    old_files = {n: release.sha(b) for n,b in old.items()}
    release.put(candidate / 'stage.json', {'planSha256': controller.plan_sha, 'services': services, 'oldFiles': old_files})
    calls, data_calls = [], []
    monkeypatch.setattr(release.os, 'chown', lambda *args: None, raising=False)
    controller.candidate_image = lambda: calls.append('checked_image')
    controller.validate_evidence = lambda: calls.append('checked_tests')
    controller.baseline = lambda: (old_files, services)
    controller.current_services = lambda image: {n: {'id': 'new-' + n, 'image': image} for n in release.SERVICES}
    controller.inspect = lambda ref: {'State': {'Running': False, 'OOMKilled': False, 'ExitCode': 0, 'Health': {'Status': 'healthy'}},
        'Image': services[ref[4:]]['image'] if ref.startswith('old-') else controller.plan['imageId'],
        'Id': ref, 'Config': {'Env': environment}}
    def runner(argv, **kwargs):
        calls.append(argv)
        if argv[:2] == ['systemctl', 'is-active']:
            return b'active\n'
        if argv[:2] == ['systemctl', 'show']:
            return b'inactive\n'
        if argv[:2] == ['docker', 'exec']:
            return release.encoded(controller.runtime)
        if argv[0] == 'curl':
            return b'{"status":"ok"}'
        return b''
    controller.runner = runner
    def data_call(proof, program, **kwargs):
        data_calls.append(program)
        calls.append('backup' if program == release.BACKUP_PROGRAM else 'warm' if program == release.WARM_PROGRAM else 'recheck')
        return {'verified': True}
    controller.data_call = data_call
    return controller, calls, data_calls, old


@pytest.mark.parametrize('failed', ['backup', 'warm', 'recheck'])
def test_failure_never_starts_workers_or_automatically_restores(simulation, failed):
    controller, calls, data_calls, old = simulation
    original = controller.data_call
    def fail(proof, program, **kwargs):
        name = 'backup' if program == release.BACKUP_PROGRAM else 'warm' if program == release.WARM_PROGRAM else 'recheck'
        if name == failed:
            calls.append('failed_' + failed)
            raise release.ReleaseError('synthetic_failure')
        return original(proof, program, **kwargs)
    controller.data_call = fail
    with pytest.raises(release.ReleaseError, match='synthetic_failure'):
        controller.activate()
    record = release.read(controller.candidate / 'activation.json')
    assert record['completed'] is False
    assert not any(isinstance(c, list) and c[:3] == ['docker', 'compose', 'up'] and 'sync' in c for c in calls)
    assert not any(isinstance(c, list) and c[:2] == ['systemctl', 'start'] for c in calls)
    if failed in {'backup', 'warm'}:
        assert (controller.root / 'app.py').read_bytes() == old['app.py']
        assert (controller.root / 'static/experience/index.html').read_bytes() == old['static/experience/index.html']
    with pytest.raises(FileExistsError):
        controller.activate()
    # Reattempt admission may inspect state; no repeated stop/data/install step.
    assert calls.count('failed_' + failed) == 1


def test_success_starts_workers_only_after_backup_migration_and_app_readback(simulation):
    controller, calls, data_calls, _ = simulation
    result = controller.activate()
    assert result['completed'] is True
    workers = next(i for i,c in enumerate(calls) if isinstance(c, list) and c[:3] == ['docker', 'compose', 'up'] and 'sync' in c)
    assert calls.index('backup') < calls.index('warm') < calls.index('recheck') < workers
    assert len(data_calls) == 3
    assert result['householdTables'] == 61 and result['platformTables'] == 9
    assert (Path(result['releaseDirectory']) / 'source-before/app.py').read_bytes() == b'old app'
    assert (Path(result['releaseDirectory']) / 'expo-before/index.html').read_bytes() == b'old entry'
    assert (controller.root / 'static/experience/index.html').read_bytes() == b'new entry'
    assert release.read(controller.candidate / 'activation.json') == result


def test_stage_rejects_failed_validation_before_baseline(simulation):
    controller, calls, _, _ = simulation
    controller.validate_evidence = lambda: (_ for _ in ()).throw(release.ReleaseError('tests_failed'))
    controller.baseline = lambda: pytest.fail('Must not reach baseline after failed admission')
    with pytest.raises(release.ReleaseError, match='tests_failed'):
        controller.stage()
    assert not any(isinstance(c, list) and 'stop' in c for c in calls)


@pytest.mark.parametrize('window', ['first_app_start', 'app_health', 'runtime_readback', 'worker_start', 'public_health'])
def test_partial_candidate_start_is_stopped_on_failure(simulation, window):
    controller, calls, _, _ = simulation
    original_runner, original_inspect = controller.runner, controller.inspect
    def runner(argv, **kwargs):
        if (window == 'first_app_start' and argv[:3] == ['docker','compose','up']
            or window == 'runtime_readback' and argv[:2] == ['docker','exec']
            or window == 'worker_start' and argv[:3] == ['docker','compose','up'] and 'sync' in argv
            or window == 'public_health' and argv[0] == 'curl'):
            calls.append(['failed', window])
            raise release.ReleaseError('synthetic_start_failure')
        return original_runner(argv, **kwargs)
    controller.runner = runner
    if window == 'app_health':
        def inspect(reference):
            value = original_inspect(reference)
            if reference == 'family-dashboard-app-1':
                value['State']['Health']['Status'] = 'unhealthy'
            return value
        controller.inspect = inspect
    with pytest.raises(release.ReleaseError):
        controller.activate()
    proof = release.read(controller.candidate / 'activation.json')
    assert proof['completed'] is False and proof['candidateStoppedAfterFailure'] is True
    assert ['docker', 'compose', 'stop', '--timeout', '360', 'media', 'sync', 'app'] == calls[-2]
    assert calls[-1][:3] == ['docker','ps','-q']
    assert not any(isinstance(c,list) and c[:2] == ['systemctl','start'] for c in calls)


def test_failed_cleanup_is_recorded_without_claiming_stopped(simulation):
    controller, calls, _, _ = simulation
    original_runner = controller.runner
    def runner(argv, **kwargs):
        if argv[:3] == ['docker','compose','up']:
            raise release.ReleaseError('synthetic_start_failure')
        if controller.candidate_started and argv[:3] == ['docker','compose','stop']:
            raise release.ReleaseError('synthetic_cleanup_failure')
        return original_runner(argv, **kwargs)
    controller.runner = runner
    with pytest.raises(release.ReleaseError, match='synthetic_start_failure'):
        controller.activate()
    proof = release.read(controller.candidate / 'activation.json')
    assert proof['completed'] is False and proof['candidateStoppedAfterFailure'] is False


@pytest.mark.parametrize('change', ['none', 'failed_guard', 'wrong_package', 'shadowed_module', 'changed_source'])
def test_validation_originals_are_resolved_under_report_directory(tmp_path, change):
    controller = release.Controller.__new__(release.Controller)
    controller.candidate = tmp_path
    proof = tmp_path / 'validation/proof'
    proof.mkdir(parents=True)
    controller.package = {'sourceHead': 'a'*40, 'manifestSha256': 'b'*64}
    controller.runtime = {'app.py': 'c'*64}
    controller.files = {**controller.runtime, 'tests/test_a.py': 'd'*64}
    runtime = {'before': controller.runtime, 'after': controller.runtime,
               'loadedBefore': {'app': '/app/app.py'}, 'loadedAfter': {'app': '/app/app.py'},
               'sourceBefore': controller.files, 'sourceAfter': controller.files}
    if change == 'shadowed_module':
        runtime['loadedAfter'] = {'app': '/test-support/app.py'}
    if change == 'changed_source':
        runtime['sourceAfter'] = {'app.py': 'e'*64}
    release.put(proof / 'runtime.json', runtime)
    release.put(proof / 'results.xml', b'<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0">'
        b'<testcase classname="tests.test_a" name="test_one"/></testsuite></testsuites>')
    report = {'imageId': 'sha256:'+'1'*64, 'sourceHead': controller.package['sourceHead'],
              'manifestSha256': controller.package['manifestSha256'], 'exitCode': 0, 'allPassed': change != 'failed_guard',
              'packageSha256': 'f'*64 if change == 'wrong_package' else 'e'*64,
              'junitPath': 'proof/results.xml', 'runtimePath': 'proof/runtime.json',
              'evidence': {'proof/'+p.name: release.sha(p.read_bytes()) for p in proof.iterdir()}}
    release.put(proof.parent / 'validation.json', report)
    controller.plan = {'imageId': report['imageId'], 'packageSha256': 'e'*64,
                       'validation': {'path': 'validation/validation.json', 'sha256': release.sha((proof.parent/'validation.json').read_bytes())},
                       'testCases': [['tests.test_a', 'test_one']], 'allowedSkips': []}
    if change == 'none':
        assert controller.validate_evidence() == {'tests': 1, 'passed': 1, 'skipped': 0}
    else:
        with pytest.raises(release.ReleaseError):
            controller.validate_evidence()


def test_config_env_serialization_preserves_resolved_and_literal_values(tmp_path):
    # The origin was already parsed by Compose; literal quotes in other values
    # must survive. Docker env-files do not expand $, backslashes or inline #.
    values = ['DATA_DIR=/data', 'PUBLIC_ORIGIN=https://example.invalid',
              'SECRET_KEY="literal quotes" $VALUE # = \\ keep ', 'EMPTY=',
              'UNICODE=家庭', 'TRUST_PROXY=1', 'COOKIE_SECURE=1', 'PYTHONDONTWRITEBYTECODE=1']
    raw = release.runtime_environment(values)
    path = tmp_path / 'runtime.env'
    release.put(path, raw)
    assert path.read_bytes() == (
        'DATA_DIR=/data\nPUBLIC_ORIGIN=https://example.invalid\n'
        'SECRET_KEY="literal quotes" $VALUE # = \\ keep \nEMPTY=\nUNICODE=家庭\n'
        'TRUST_PROXY=1\nCOOKIE_SECURE=1\nPYTHONDONTWRITEBYTECODE=1\n').encode('utf-8')
    assert (path.stat().st_mode & 0o777) == (0o600 if release.os.name == 'posix' else 0o666)


@pytest.mark.parametrize('value,code', [
    (None, 'runtime_environment_shape'), ([], 'runtime_environment_shape'),
    (['DATA_DIR=/data', 'NO_ASSIGNMENT'], 'runtime_environment_entry'),
    (['DATA_DIR=/data', 'SECRET=a\nINJECTED=b'], 'runtime_environment_entry'),
    (['DATA_DIR=/data', 'SECRET=a\rb'], 'runtime_environment_entry'),
    (['DATA_DIR=/data', 'SECRET=a\x00b'], 'runtime_environment_entry'),
    (['DATA_DIR=/data', 'SECRET=one', 'SECRET=two'], 'runtime_environment_key'),
    (['DATA_DIR=/data', ' KEY=value'], 'runtime_environment_key'),
    (['DATA_DIR=/elsewhere'], 'runtime_data_directory'),
    (['DATA_DIR=/data', 'SECRET=\ud800'], 'runtime_environment_encoding'),
])
def test_runtime_env_rejects_unrepresentable_or_ambiguous_inputs(value, code):
    with pytest.raises(release.ReleaseError) as caught:
        release.runtime_environment(value)
    assert str(caught.value) == code  # Never echo a rejected secret value.


def test_service_snapshot_binds_full_app_environment():
    controller = release.Controller.__new__(release.Controller)
    environment = ['DATA_DIR=/data', 'PUBLIC_ORIGIN=https://example.invalid', 'SECRET_KEY=first']
    def inspect(ref):
        name = ref.removeprefix('family-dashboard-').removesuffix('-1')
        return {'Id': 'id-' + name, 'Image': release.WEB_IMAGE if name == 'web' else release.PARENT_IMAGE,
                'State': {'Running': True, 'OOMKilled': False, 'Health': {'Status': 'healthy'}},
                'Config': {'Env': environment, 'Labels': {'com.docker.compose.project': 'family-dashboard',
                           'com.docker.compose.service': name}},
                'Mounts': [{'Destination': '/data', 'Type': 'volume', 'Name': release.VOLUME}]}
    controller.inspect = inspect
    first = controller.current_services(release.PARENT_IMAGE)
    environment[-1] = 'SECRET_KEY=second'
    second = controller.current_services(release.PARENT_IMAGE)
    assert first['app']['environmentSha256'] != second['app']['environmentSha256']
    assert first['app']['id'] == second['app']['id']
    assert 'SECRET_KEY' not in json.dumps(second)


@pytest.mark.parametrize('change', ['id', 'image', 'environment'])
def test_environment_binding_drift_stops_before_any_service_stop(simulation, change):
    controller, calls, _, _ = simulation
    original = controller.inspect
    def inspect(ref):
        value = original(ref)
        if ref == 'old-app':
            if change == 'environment':
                value['Config']['Env'] = ['DATA_DIR=/data', 'SECRET_KEY=changed']
            else:
                value['Id' if change == 'id' else 'Image'] = 'changed'
        return value
    controller.inspect = inspect
    with pytest.raises(release.ReleaseError, match='runtime_environment_'):
        controller.activate()
    assert not any(isinstance(c, list) and 'stop' in c for c in calls)
    assert 'backup' not in calls and 'warm' not in calls


@pytest.mark.parametrize('change', ['none', 'unbound', 'file', 'original', 'permissions'])
def test_data_call_uses_only_bound_runtime_env_and_rechecks_it(simulation, monkeypatch, change):
    controller, calls, _, _ = simulation
    release_dir = controller.releases / 'synthetic-release'
    proof = release_dir / 'proof'
    proof.mkdir(parents=True)
    service = release.read(controller.candidate / 'stage.json')['services']['app']
    if change != 'unbound':
        controller.bind_data_environment(release_dir, service)
    if change == 'file':
        (release_dir / 'app-runtime.env').write_bytes(b'DATA_DIR=/data\nSECRET_KEY=changed\n')
    if change == 'original':
        (controller.root / '.env').write_bytes(b'changed')
    # Windows has no POSIX file modes. Exercise both admission outcomes through
    # this narrow mode seam; production always enforces the real stat mode.
    monkeypatch.setattr(release.stat, 'S_IMODE', lambda mode: 0o644 if change == 'permissions' else 0o600)
    def runner(argv, **kwargs):
        calls.append(argv)
        return b'{"verified":true}'
    controller.runner = runner
    if change != 'none':
        with pytest.raises(release.ReleaseError):
            release.Controller.data_call(controller, proof, 'pass')
        assert calls == []
        return
    assert release.Controller.data_call(controller, proof, 'pass', write=False) == {'verified': True}
    argv = calls[0]
    assert argv[argv.index('--env-file') + 1] == str(release_dir / 'app-runtime.env')
    assert str(controller.root / '.env') not in argv and '-e' not in argv
    assert argv[argv.index('--network') + 1] == 'none'
    assert argv[argv.index('--user') + 1] == '10001:10001' and '--read-only' in argv
    assert release.VOLUME + ':/data:ro' in argv
    assert not any('SECRET_KEY' in str(arg) or 'synthetic-$quote' in str(arg) for arg in argv)
