"""Offline tool boundaries only. No Docker, large media, Flask, FFmpeg or SSH."""
import ast
import json
from pathlib import Path
import socket
import stat
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from deploy import media_video_ipc_resource_probe as probe


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, 'ROOT', tmp_path)
    tools = tmp_path / 'prepared/tools'; tools.mkdir(parents=True)
    output = tmp_path / 'worker100'; output.mkdir()
    return tools, output


@pytest.mark.parametrize('profile', probe.PROFILES)
def test_roles_have_separate_fixed_limits_and_no_private_data_mount_in_decoder(paths, profile):
    tools, output = paths
    for role, memory in [('application', 384), ('decoder', 768)]:
        image = 'sha256:' + ('1' if role == 'application' else '2') * 64
        argv = probe.container_args(role, profile, image, tools, output)
        assert f'--memory={memory}m' in argv and f'--memory-swap={memory}m' in argv
        assert '--network=none' in argv and '--read-only' in argv and '--user=10001:10001' in argv
        assert '--cap-drop=ALL' in argv and '--security-opt=no-new-privileges:true' in argv
        assert '--pids-limit=128' in argv and '--cpus=1' in argv
        mounts = [a for a in argv if a.startswith('--mount=')]
        assert len(mounts) == 4
        assert any('dst=/fixtures' in a and a.endswith(',readonly') == (role == 'application') for a in mounts)
        assert any(str(output / role) in a and 'dst=/proof' in a for a in mounts)
        assert not any(str(output / ('application' if role == 'decoder' else 'decoder')) in a for a in mounts)
        assert not any(s in ' '.join(argv) for s in ('--env-file', 'docker.sock', '/data', '--privileged', '--publish'))
        assert argv.count(image) == 1 and '-i' in argv


@pytest.mark.parametrize('role,profile,image', [('worker', 'worker100', 'sha256:' + '1'*64),
    ('application', 'all', 'sha256:' + '1'*64), ('decoder', 'worker100', 'decoder:latest')])
def test_unreviewed_role_profile_or_mutable_image_refused(paths, role, profile, image):
    with pytest.raises(RuntimeError): probe.container_args(role, profile, image, *paths)


def test_mount_paths_traversal_reuse_and_option_injection_fail_closed(paths):
    tools, output = paths
    with pytest.raises(RuntimeError): probe.safe(output)
    with pytest.raises(RuntimeError): probe.safe(output / '..' / 'x')
    with pytest.raises(RuntimeError): probe.safe(str(output) + ',dst=/data')
    with pytest.raises(RuntimeError): probe.safe(Path.cwd(), exists=True, remote=True)


def test_exact_socket_guard_delegates_only_authorized_unix_connect(monkeypatch):
    # Tiny delegate, not a fake successful decoder or Linux execution claim.
    monkeypatch.setattr(socket, 'AF_UNIX', 1, raising=False)
    delegated = []
    monkeypatch.setattr(socket.socket, 'connect', lambda peer, address: delegated.append(address))
    with probe.network_guard() as (calls, _):
        socket.socket.connect(SimpleNamespace(family=socket.AF_UNIX), probe.SOCKET)
        assert calls == [{'family': 'AF_UNIX', 'path': probe.SOCKET}] and delegated == [probe.SOCKET]
        for peer, address in [(SimpleNamespace(family=socket.AF_INET), ('127.0.0.1', 443)),
                              (SimpleNamespace(family=socket.AF_UNIX), '/tmp/other.sock'),
                              (SimpleNamespace(family=socket.AF_UNIX), probe.SOCKET.encode())]:
            with pytest.raises(RuntimeError): socket.socket.connect(peer, address)
        with pytest.raises(RuntimeError): socket.create_connection(('example.invalid', 443))
        with pytest.raises(RuntimeError): socket.getaddrinfo('example.invalid', 443)
        with pytest.raises(RuntimeError): socket.socket.connect_ex(SimpleNamespace(), probe.SOCKET)
    assert delegated == [probe.SOCKET]


def final_fixture():
    contract = {'sourceHead': 'a'*40, 'images': {'application': 'sha256:'+'1'*64, 'decoder': 'sha256:'+'2'*64}}
    states = {}; proofs = {}
    for index, role in enumerate(probe.LIMITS):
        states[role] = {'Id': str(index+1)*64, 'Image': contract['images'][role],
            'Config': {'User': '10001:10001'}, 'State': {'ExitCode': 0, 'Running': False, 'OOMKilled': False},
            'HostConfig': {'Memory': probe.LIMITS[role]*1024**2, 'MemorySwap': probe.LIMITS[role]*1024**2,
                           'NetworkMode': 'none', 'ReadonlyRootfs': True}}
        proofs[role] = {'role': role, 'profile': 'worker100', 'sourceHead': contract['sourceHead'],
            'exitCode': 0, 'loadedSourceVerified': True, 'cgroup': {'memory.events': 'max 0\noom 0\noom_kill 0\n'}}
    return states, proofs, contract


@pytest.mark.parametrize('fault', ['expanded-app', 'one-container', 'oom', 'nonzero', 'running',
    'missing-proof', 'stale-source', 'wrong-image', 'network', 'limit-event', 'no-source-verification'])
def test_failed_or_misbound_resource_observation_cannot_turn_green(fault):
    states, proofs, contract = final_fixture()
    probe.verify_final(states, proofs, 0, contract, 'worker100')
    if fault == 'expanded-app': states['application']['HostConfig']['Memory'] = 768*1024**2
    elif fault == 'one-container': states['decoder']['Id'] = states['application']['Id']
    elif fault == 'oom': states['decoder']['State']['OOMKilled'] = True
    elif fault == 'nonzero': states['application']['State']['ExitCode'] = 137
    elif fault == 'running': states['decoder']['State']['Running'] = True
    elif fault == 'missing-proof': proofs.pop('decoder')
    elif fault == 'stale-source': proofs['application']['sourceHead'] = 'b'*40
    elif fault == 'wrong-image': states['application']['Image'] = contract['images']['decoder']
    elif fault == 'network': states['application']['HostConfig']['NetworkMode'] = 'host'
    elif fault == 'limit-event': proofs['decoder']['cgroup']['memory.events'] = 'max 1\noom 0\noom_kill 0\n'
    elif fault == 'no-source-verification': proofs['application']['loadedSourceVerified'] = False
    with pytest.raises(RuntimeError): probe.verify_final(states, proofs, 0, contract, 'worker100')


def test_source_closure_covers_actual_local_imports_and_current_docker_copy():
    root = Path(__file__).parents[1]; names = set(probe.APP_FILES)
    assert len(names) == len(probe.APP_FILES)
    assert {'media_playback_progress.py', 'media_video_transport.py', 'media_crypto.py', 'app.py'} <= names
    docker = (root / 'Dockerfile').read_text()
    copies = {name for line in docker.splitlines() if line.startswith('COPY ') for name in line.split()[1:-1] if name.endswith('.py')}
    assert copies == names - {'requirements.txt'}
    for name in names:
        if not name.endswith('.py'): continue
        for node in ast.walk(ast.parse((root/name).read_bytes())):
            mods = ([node.module] if isinstance(node, ast.ImportFrom) and node.module else
                    [a.name for a in node.names] if isinstance(node, ast.Import) else [])
            for module in mods:
                local = module.split('.')[0] + '.py'
                assert not (root/local).is_file() or local in names, (name, local)


def test_file_transport_and_padding_use_bounded_reads_with_real_small_file(tmp_path):
    file = tmp_path/'tiny.mp4'; first = b'original-synthetic-container'; file.write_bytes(first)
    probe.padded_mp4(file, len(first)+1048576)
    with file.open('rb') as stream:
        assert stream.read(len(first)) == first
        assert stream.read(8) == (1048576).to_bytes(4, 'big') + b'free'
    response = probe.FileResponse(file); seen = 0
    with pytest.raises(RuntimeError): response.read1(65537)
    while chunk := response.read1(65536): seen += len(chunk)
    response.close()
    assert response.closed and response.stream.closed and response.bytes_read == seen == file.stat().st_size
    with pytest.raises(RuntimeError): probe.padded_mp4(file, file.stat().st_size + 7)


def test_real_cli_exposes_only_preparation_run_inside_no_build_or_memory_override():
    output = subprocess.run([sys.executable, '-B', probe.__file__, '--help'], capture_output=True, text=True, timeout=20)
    assert output.returncode == 0 and '{prepare,run,inside}' in output.stdout
    invalid = subprocess.run([sys.executable, '-B', probe.__file__, 'run', '--memory-mib', '1024'],
                             capture_output=True, text=True, timeout=20)
    assert invalid.returncode != 0


@pytest.mark.parametrize('readings,expected', [([1280, 1281, 1280], 'ready'),
    ([1280, 1279, 1281], 'preflight_blocked'), ([1279, 1281, 1281], 'preflight_blocked')])
def test_budget_preflight_requires_all_three_readings_without_retry(tmp_path, readings, expected):
    values = iter(readings); pauses = []; calls = []
    def read():
        value = next(values); calls.append(value); return value * 1024
    result = probe.host_preflight(tmp_path, reader=read, sleeper=pauses.append)
    assert result['status'] == expected and calls == readings and pauses == [.5, .5]
    assert json.loads((tmp_path/'preflight.json').read_text()) == result
    assert not list(tmp_path.glob('*owned*'))


def test_budget_preflight_read_failure_is_preserved(tmp_path):
    def failed(): raise OSError('synthetic unavailable proc')
    record = probe.host_preflight(tmp_path, reader=failed, sleeper=lambda _: None)
    assert record['status'] == 'preflight_blocked' and record['samples'] == []
    assert record['failure'] == 'host_memory_read_failed:OSError'


@pytest.mark.parametrize('fault', ['below', 'read-error', 'thread-error'])
def test_budget_monitor_latches_low_memory_and_reader_thread_errors(tmp_path, fault):
    calls = []
    def reader():
        calls.append(1)
        if fault == 'read-error': raise OSError('synthetic read')
        if fault == 'thread-error': raise SystemExit('synthetic thread exit')
        return 255 * 1024
    monitor = probe.HostMemoryMonitor(tmp_path, reader=reader)
    with pytest.raises(probe.HostMemoryAbort): monitor.start()
    first = monitor.failure.copy()
    monitor.reader = lambda: 2048 * 1024
    with pytest.raises(probe.HostMemoryAbort): monitor.check()
    record = monitor.finish()
    assert record['failure'] == first and record['threadStopped'] and calls
    assert json.loads((tmp_path/'host-memory.json').read_text()) == record
    assert (tmp_path/'host-memory-samples.jsonl').is_file()


def test_budget_monitor_normal_boundary_and_unexpected_thread_death(tmp_path):
    monitor = probe.HostMemoryMonitor(tmp_path, reader=lambda: 256 * 1024)
    monitor.start(); monitor.check()
    record = monitor.finish()
    assert record['failure'] is None and record['sampleCount'] >= 1 and record['minimumAvailableKiB'] == 256 * 1024
    other = tmp_path/'unexpected'; other.mkdir()
    monitor = probe.HostMemoryMonitor(other, reader=lambda: 300 * 1024)
    monitor.start(); monitor.stop_event.set(); monitor.thread.join(1)
    with pytest.raises(probe.HostMemoryAbort, match='stopped'): monitor.check()
    assert monitor.finish()['failure']['reason'] == 'host_memory_monitor_stopped'


def test_budget_monitor_stalled_reader_fails_closed(tmp_path, monkeypatch):
    release = threading.Event()
    policy = {**probe.HOST_BUDGET, 'maxSampleLagSeconds': .05}
    monkeypatch.setattr(probe, 'HOST_BUDGET', policy)
    def reader():
        release.wait(2); return 2048 * 1024
    monitor = probe.HostMemoryMonitor(tmp_path, reader=reader)
    try:
        with pytest.raises(probe.HostMemoryAbort, match='stalled'): monitor.start()
    finally:
        release.set(); monitor.thread.join(1)
        record = monitor.finish()
    assert record['failure']['reason'] == 'host_memory_monitor_stalled' and record['threadStopped']


def test_budget_inflight_executor_checks_guard_and_preserves_original_child_receipt(tmp_path, monkeypatch):
    class Child:
        pid = 12345
        def __init__(self): self.waits = []; self.killed = 0
        def wait(self, timeout=None):
            self.waits.append(timeout)
            if timeout is not None: raise subprocess.TimeoutExpired('synthetic docker attach', timeout)
            return -9
        def kill(self): self.killed += 1
    child = Child(); spawned = []
    def spawn(argv, **kwargs): spawned.append(argv); return child
    monkeypatch.setattr(probe.subprocess, 'Popen', spawn)
    class Guard:
        calls = 0
        def check(self):
            self.calls += 1
            if self.calls == 3: raise probe.HostMemoryAbort('synthetic pressure')
    executor = probe.Executor(tmp_path)
    with pytest.raises(probe.HostMemoryAbort):
        executor.call(['start', '--attach', '1'*64], timeout=1800, check=False, guard=Guard())
    assert len(spawned) == 1 and child.waits == [.25, None] and child.killed == 1
    record = json.loads((tmp_path/'command-00.json').read_text())
    assert record['exitCode'] == 125 and record['abortedBy'] == 'HostMemoryAbort' and record['pid'] == 12345
    assert record['childExitCode'] == -9
    assert (tmp_path/'command-00.started.json').is_file() and (tmp_path/'command-00.stdout').is_file()


@pytest.mark.parametrize('pressure', [False, True, 'during-stop'])
def test_budget_cleanup_targets_only_owned_ids_and_kills_before_inspection(tmp_path, pressure):
    owned = {'decoder': '2'*64, 'application': '1'*64}; calls = []
    class Guard:
        failure = pressure is True
        def check(self):
            if self.failure: raise probe.HostMemoryAbort('synthetic pressure')
    guard = Guard()
    class Executor:
        def call(self, args, **kwargs):
            calls.append((args, kwargs))
            if pressure == 'during-stop' and args[0] == 'stop':
                guard.failure = True; raise probe.HostMemoryAbort('pressure during stop')
            if args[0] == 'inspect': return 0, json.dumps([{'Id': args[-1], 'State': {'Running': False}}]).encode()
            return 0, b''
    states, errors = probe.cleanup_owned(Executor(), owned, tmp_path, guard)
    assert not errors and set(states) == set(owned)
    assert all(args[-1] in owned.values() for args, _ in calls)
    if pressure:
        killed = [(i, args[-1]) for i, (args, _) in enumerate(calls) if args[0] == 'kill']
        assert {cid for _, cid in killed} == set(owned.values())
        assert max(i for i, _ in killed) < next(i for i,(args,_) in enumerate(calls) if args[0] == 'inspect')
        assert all('guard' not in kw for args, kw in calls if args[0] in ('kill', 'inspect', 'logs'))
    else:
        assert [args[0] for args, _ in calls] == ['stop', 'stop', 'inspect', 'logs', 'inspect', 'logs']
    assert all((tmp_path/(role+'-container.json')).is_file() for role in owned)


def test_budget_run_preflight_blocked_creates_evidence_and_no_executor(tmp_path, monkeypatch):
    tools = tmp_path/'prepared/tools'; tools.mkdir(parents=True)
    monkeypatch.setattr(probe, 'ROOT', tmp_path)
    monkeypatch.setattr(probe.sys, 'platform', 'linux')
    monkeypatch.setattr(probe, 'prepared', lambda _: (tools, {'sourceHead': 'a'*40}))
    monkeypatch.setattr(probe, 'mem_available_kib', lambda: 1279*1024)
    monkeypatch.setattr(probe.time, 'sleep', lambda _: None)
    def forbidden(_): raise AssertionError('no executor may exist before preflight passes')
    monkeypatch.setattr(probe, 'Executor', forbidden)
    output = tmp_path/'blocked'
    with pytest.raises(RuntimeError, match='preflight_blocked'): probe.run(tmp_path/'prepared', output, 'worker100')
    result = json.loads((output/'result.json').read_text())
    assert not result['passed'] and result['status'] == 'preflight_blocked' and result['containers'] == {} and result['commands'] == []
    assert set(result['artifacts']) == {'started.json', 'preflight.json'}


@pytest.mark.parametrize('abort_after_create', [False, True, 'create-timeout'])
def test_budget_coordinator_records_both_ids_before_workload_and_keeps_terminal_evidence(tmp_path, monkeypatch, abort_after_create):
    # Coordinator control-flow fixture only; no real container or inside business proof is claimed.
    tools = tmp_path/'prepared/tools'; tools.mkdir(parents=True)
    states, proofs, contract = final_fixture(); output = tmp_path/'run'; calls = []; created = []
    ids = {role: state['Id'] for role, state in states.items()}
    monkeypatch.setattr(probe, 'ROOT', tmp_path)
    monkeypatch.setattr(probe.sys, 'platform', 'linux')
    monkeypatch.setattr(probe, 'prepared', lambda _: (tools, contract))
    monkeypatch.setattr(probe.os, 'chown', lambda *args: None, raising=False)
    monkeypatch.setattr(probe, 'mem_available_kib', lambda: 2048*1024)
    monkeypatch.setattr(probe.time, 'sleep', lambda _: None)
    original_lstat = Path.lstat
    def lstat(path):
        result = original_lstat(path)
        if path == output/'socket/video.sock':
            return SimpleNamespace(st_mode=stat.S_IFSOCK | 0o600, st_uid=10001)
        return result
    monkeypatch.setattr(Path, 'lstat', lstat)
    class Executor:
        def __init__(self, _): self.records = []
        def call(self, args, **kwargs):
            calls.append(args); self.records.append({'arguments': args, 'syntheticOfflineOnly': True})
            guard = kwargs.get('guard')
            if guard: guard.check()
            if args[0] == 'image': return 0, json.dumps([{'Id': args[-1], 'Config': {}}]).encode()
            if args[0] == 'create':
                assert kwargs['interruptible'] is False and kwargs['timeout'] == 10
                role = args[args.index('--role') + 1]; created.append(role)
                if abort_after_create == 'create-timeout' and len(created) == 2:
                    raise RuntimeError('synthetic create timeout without returned ID')
                if abort_after_create is True and len(created) == 2: guard.latch('synthetic_pressure_after_create')
                return 0, ids[role].encode()
            if args[0] == 'start':
                assert created == ['decoder', 'application']
                assert all((output/(role+'-owned.json')).is_file() for role in created)
                if '--attach' not in args:
                    (output/'socket/video.sock').touch(); (output/'fixtures/fixture.json').write_text('{}')
                else:
                    for role in created: probe.save(output/role/'finished.json', proofs[role])
            if args[0] == 'inspect':
                role = next(r for r, cid in ids.items() if cid == args[-1])
                return 0, json.dumps([states[role]]).encode()
            return 0, b''
    monkeypatch.setattr(probe, 'Executor', Executor)
    if abort_after_create:
        with pytest.raises(RuntimeError, match='resource experiment failed'):
            probe.run(tmp_path/'prepared', output, 'worker100')
    else:
        probe.run(tmp_path/'prepared', output, 'worker100')
    result = json.loads((output/'result.json').read_text())
    expected_ids = {'decoder': ids['decoder']} if abort_after_create == 'create-timeout' else ids
    assert result['passed'] is (not abort_after_create) and result['containers'] == expected_ids
    assert result['status'] == ('failed' if abort_after_create == 'create-timeout' else 'aborted' if abort_after_create else 'passed')
    assert not result['cleanupErrors'] and result['hostMemory']['threadStopped']
    if abort_after_create:
        assert not any(args[0] == 'start' for args in calls)
        if abort_after_create is True:
            assert {args[-1] for args in calls if args[0] == 'kill'} == set(ids.values())
        else:
            assert result['unconfirmedCreate']['role'] == 'application'
            assert all(args[-1] == ids['decoder'] for args in calls if args[0] in ('kill', 'stop', 'inspect', 'logs'))
        assert result['proofs'] == {} and result['workerAttachExitCode'] is None
    else:
        assert not any(args[0] == 'kill' for args in calls)
        assert result['workerAttachExitCode'] == 0
