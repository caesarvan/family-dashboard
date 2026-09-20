"""Offline tool boundaries only. No Docker, large media, Flask, FFmpeg or SSH."""
import ast
from pathlib import Path
import socket
import subprocess
import sys
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
