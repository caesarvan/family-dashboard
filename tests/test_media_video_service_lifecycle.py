"""Offline controller-component tests; recording Docker model, no daemon."""
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from deploy import media_video_service_lifecycle as service
from deploy.membership_release_controller import ReleaseError

ROOT = Path(__file__).resolve().parents[1]
APP, DECODER = 'sha256:' + 'a' * 64, 'sha256:' + 'b' * 64
BASE_ENV = ['DATA_DIR=/data', 'PRIVATE_TEST_TOKEN=synthetic-only', 'PATH=/usr/local/bin:/usr/bin']
DECODER_ENV = ['PATH=/usr/local/bin:/usr/bin', 'PYTHONDONTWRITEBYTECODE=1', 'PYTHONUNBUFFERED=1']


def container(name, phase):
    digest = hashlib.sha256((name + phase).encode()).hexdigest()
    mounts = []
    if name in ('app', 'sync', 'media'):
        mounts.append(dict(Type='volume', Name=service.VOLUME, Destination='/data', RW=True))
    if name == 'decoder' or (name == 'media' and phase == 'candidate'):
        mounts.append(dict(Type='volume', Name=service.SOCKET_VOLUME, Destination='/decoder-private', RW=True))
    env = list(DECODER_ENV if name == 'decoder' else BASE_ENV)
    if name == 'media' and phase == 'candidate':
        env.append('MEDIA_VIDEO_SOCKET=' + service.SOCKET)
    image = service.WEB_IMAGE if name == 'web' else service.PARENT_IMAGE if phase == 'parent' else DECODER if name == 'decoder' else APP
    config = dict(Env=env, User='10001:10001' if name == 'decoder' else 'dashboard',
                  Labels={'com.docker.compose.project': service.PROJECT, 'com.docker.compose.service': name})
    host = dict(Memory=service.MEMORY[name] * service.MIB, ReadonlyRootfs=name != 'web')
    if name == 'decoder':
        config.update(WorkingDir='/decoder', Entrypoint=['python', '-B', '/decoder/media_video_service.py'],
                      Cmd=['--socket', service.SOCKET, '--temp-root', '/decode-temp', '--ffmpeg', '/usr/bin/ffmpeg',
                           '--ffprobe', '/usr/bin/ffprobe'])
        host.update(NetworkMode='none', MemorySwap=768 * service.MIB, NanoCpus=1_000_000_000, PidsLimit=128,
                    CapDrop=['ALL'], CapAdd=None, Privileged=False, SecurityOpt=['no-new-privileges:true'],
                    Ulimits=[{'Name': 'nofile', 'Hard': 128, 'Soft': 128}],
                    Tmpfs={'/decode-temp': 'rw,noexec,nosuid,nodev,size=384m,uid=10001,gid=10001,mode=0700'})
    return dict(Id=digest, Name='/' + service.PROJECT + '-' + name + '-1', Image=image, Config=config,
                HostConfig=host, Mounts=mounts, RestartCount=0,
                State={'Running': True, 'OOMKilled': False, 'ExitCode': 0, 'Health': {'Status': 'healthy'}})


class RecordingDocker:
    def __init__(self, root):
        self.root, self.calls = root, []
        self.values = {n: container(n, 'parent') for n in service.OLD_SERVICES}
        self.fail_up, self.fail_stop, self.unrelated, self.changed_before_stop = None, None, False, None

    def __call__(self, argv, *, cwd, timeout):
        self.calls.append((argv, timeout))
        assert argv[:3] == list(service.DOCKER) and cwd == self.root
        args = argv[3:]
        if args[0] == 'inspect':
            if args[1] == DECODER:
                return json.dumps([{'Config': {'Env': DECODER_ENV}}]).encode()
            for name, value in self.values.items():
                if args[1] in (value['Id'], service.PROJECT + '-' + name + '-1'):
                    return json.dumps([value]).encode()
            raise ReleaseError('missing_test_container')
        if args[0] == 'ps':
            selected = list(self.values.values())
            if '--all' not in args:
                selected = [v for v in selected if v['State']['Running']]
            query = args[args.index('--filter') + 1]
            if query.startswith('volume='):
                selected = [v for v in selected if any(m.get('Name') == query[7:] for m in v['Mounts'])]
            ids = [v['Id'] for v in selected]
            if self.unrelated:
                ids.append('c' * 64)
            return ('\n'.join(ids) + ('\n' if ids else '')).encode()
        if args[0] == 'stop':
            assert args[1] == '--timeout'
            for name, value in self.values.items():
                if value['Id'] == args[-1]:
                    if name == self.fail_stop:
                        raise ReleaseError('injected_stop_failure')
                    value['State']['Running'] = False
                    return b''
            raise ReleaseError('unknown_stop_id')
        assert args[:7] == ['compose', '--project-name', service.PROJECT, '--project-directory', str(self.root),
                           '--file', str(self.root / 'compose.yaml')]
        operation = args[7:]
        if operation[0] == 'stop':
            assert operation[1] == '--timeout'
            name = operation[-1]
            self.values[name]['State']['Running'] = False
            if self.changed_before_stop:
                self.values[self.changed_before_stop]['Id'] = 'd' * 64
                self.changed_before_stop = None
            return b''
        assert operation[:8] == ['up', '-d', '--no-deps', '--no-build', '--pull', 'never', '--wait', '--wait-timeout']
        for name in operation[9:]:
            self.values[name] = container(name, 'candidate')
            if name == self.fail_up:
                raise ReleaseError('injected_partial_compose_failure')
        return b''


@pytest.fixture
def rig(tmp_path):
    before = subprocess.check_output(['git', 'show', '8d3e6376a606155ff66a0388e43d04cb7562fe9f:compose.yaml'], cwd=ROOT)
    after = (ROOT / 'compose.yaml').read_bytes()
    assert service.sha(before) == service.BEFORE_COMPOSE and service.sha(after) == service.AFTER_COMPOSE
    (tmp_path / 'compose.yaml').write_bytes(before)
    runner = RecordingDocker(tmp_path)
    return service.Lifecycle(runner, APP, DECODER, root=tmp_path), runner, after


def stopped(rig):
    lifecycle, runner, after = rig
    captured = lifecycle.capture('parent')
    result = lifecycle.drain('parent', captured)
    assert result['stopped'] == ['web', 'sync', 'media', 'app']
    (runner.root / 'compose.yaml').write_bytes(after)
    return lifecycle, runner


def proof():
    return dict(verified=True, households=2, databases=3, planSha256='1' * 64,
                logicalSha256='2' * 64, sourceIdentitySha256='3' * 64)


def preserved(rig):
    lifecycle, runner = stopped(rig)
    app = lifecycle.start_app_only()
    assert [n for n, v in runner.values.items() if v['State']['Running']] == ['app']
    lifecycle.stop_app_only(app)
    return lifecycle, runner


def test_complete_service_order_and_private_receipts(rig):
    lifecycle, runner = preserved(rig)
    current = lifecycle.start_after_preservation(proof(), proof())
    assert set(current) == set(service.NEW_SERVICES) and lifecycle.phase == 'live'
    assert 'PRIVATE_TEST_TOKEN' not in json.dumps(current) and 'synthetic-only' not in json.dumps(current)
    ups = [c[0][-1] for c in runner.calls if 'up' in c[0]]
    assert ups == ['app', 'app', 'decoder', 'media', 'web']
    commands_before = len(runner.calls)
    drained = lifecycle.drain('candidate', current)
    assert drained['stopped'] == ['web', 'sync', 'media', 'decoder', 'app']
    stops = [c for c in runner.calls[commands_before:] if 'stop' in c[0]]
    assert [(a[-1], a[-2], timeout) for a, timeout in stops] == [
        ('web', '30', 90), ('sync', '60', 120), ('media', '1200', 1260), ('decoder', '30', 90), ('app', '60', 120)]


@pytest.mark.parametrize('fault', ['network', 'data-volume', 'credentials', 'memory', 'swap', 'uid', 'caps', 'tmpfs', 'command'])
def test_decoder_isolation_drift_is_rejected_before_workers_start(rig, fault):
    lifecycle, runner = preserved(rig)
    decoder = container('decoder', 'candidate')
    if fault == 'network': decoder['HostConfig']['NetworkMode'] = 'bridge'
    elif fault == 'data-volume': decoder['Mounts'].append(dict(Type='volume', Name=service.VOLUME, Destination='/data', RW=True))
    elif fault == 'credentials': decoder['Config']['Env'].append('OAUTH_SECRET=synthetic-only')
    elif fault == 'memory': decoder['HostConfig']['Memory'] = 1024 * service.MIB
    elif fault == 'swap': decoder['HostConfig']['MemorySwap'] = -1
    elif fault == 'uid': decoder['Config']['User'] = '0'
    elif fault == 'caps': decoder['HostConfig']['CapAdd'] = ['SYS_ADMIN']
    elif fault == 'tmpfs': decoder['HostConfig']['Tmpfs']['/decode-temp'] = 'rw,size=384m'
    else: decoder['Config']['Cmd'][1] = '/other.sock'
    with pytest.raises(ReleaseError): lifecycle.check('decoder', decoder, 'candidate')
    assert not any('up' in a and a[-1] in ('media', 'web') for a, _ in runner.calls)


@pytest.mark.parametrize('fault', ['project', 'name', 'image', 'extra-container', 'env-after-capture', 'source'])
def test_changed_parent_rejected_before_mutating_commands(rig, fault):
    lifecycle, runner, _ = rig
    if fault in ('env-after-capture', 'source'):
        captured = lifecycle.capture('parent')
        if fault == 'env-after-capture': runner.values['media']['Config']['Env'].append('EXTRA=changed')
        else: (runner.root / 'compose.yaml').write_text('changed')
        with pytest.raises(ReleaseError): lifecycle.drain('parent', captured)
    else:
        if fault == 'project': runner.values['app']['Config']['Labels']['com.docker.compose.project'] = 'different'
        elif fault == 'name': runner.values['media']['Name'] = '/different-media-1'
        elif fault == 'image': runner.values['app']['Image'] = APP
        else: runner.unrelated = True
        with pytest.raises(ReleaseError): lifecycle.capture('parent')
    assert not any('stop' in a or 'up' in a for a, _ in runner.calls)


def test_container_replaced_during_drain_is_not_stopped(rig):
    lifecycle, runner, _ = rig
    captured = lifecycle.capture('parent')
    runner.changed_before_stop = 'media'
    with pytest.raises(ReleaseError, match='replaced_before_stop'): lifecycle.drain('parent', captured)
    assert not any('stop' in a and a[-1] == 'media' for a, _ in runner.calls)


@pytest.mark.parametrize('fault', ['unverified', 'wrong-plan', 'logical-drift', 'partial-group', 'phase'])
def test_workers_stay_stopped_without_complete_same_identity_preservation(rig, fault):
    lifecycle, runner = preserved(rig)
    prior = len(runner.calls)
    actual = proof()
    if fault == 'unverified': actual['verified'] = False
    elif fault == 'wrong-plan': actual['planSha256'] = '4' * 64
    elif fault == 'logical-drift': actual['logicalSha256'] = '4' * 64
    elif fault == 'partial-group': actual['databases'] = 2
    else: lifecycle.phase = 'app-only'
    with pytest.raises(ReleaseError): lifecycle.start_after_preservation(proof(), actual)
    assert not any('up' in a for a, _ in runner.calls[prior:])


@pytest.mark.parametrize('name', ['app', 'decoder', 'media', 'web'])
def test_partial_up_records_created_ids_and_stops_only_owned_candidates(rig, name):
    lifecycle, runner = preserved(rig)
    runner.fail_up = name
    with pytest.raises(ReleaseError): lifecycle.start_after_preservation(proof(), proof())
    assert name in lifecycle.recorded
    current_ids = {v['id'] for v in lifecycle.recorded.values()}
    result = lifecycle.stop_after_failure()
    assert result['complete'] and not any(v['State']['Running'] for v in runner.values.values())
    stops = [a for a, _ in runner.calls if a[3:4] == ['stop']]
    assert all(a[-1] in current_ids for a in stops)
    assert not any('rm' in a or 'volume' in a or 'kill' in a for a, _ in runner.calls)


def test_failure_stop_attempts_other_owned_containers_after_one_stop_fails(rig):
    lifecycle, runner = preserved(rig)
    lifecycle.start_after_preservation(proof(), proof())
    runner.fail_stop = 'media'
    result = lifecycle.stop_after_failure()
    assert result['complete'] is False and 'media' in result['failed']
    assert {'web', 'sync', 'app'} <= set(result['stopped'])
    assert 'decoder:media_stop_unverified' in result['failed']
    assert runner.values['decoder']['State']['Running']
    assert lifecycle.phase == 'failed-unverified'


def test_decoder_stays_running_when_media_stop_identity_is_unknown(rig):
    lifecycle, runner = preserved(rig)
    lifecycle.start_after_preservation(proof(), proof())
    runner.values['media']['Id'] = 'f' * 64
    result = lifecycle.stop_after_failure()
    assert not result['complete'] and 'decoder:media_stop_unverified' in result['failed']
    assert runner.values['decoder']['State']['Running']
    assert not any(a[3:4] == ['stop'] and a[-1] == runner.values['decoder']['Id'] for a, _ in runner.calls)


def test_unrecorded_running_project_member_prevents_false_complete_stop(rig):
    lifecycle, runner = preserved(rig)
    runner.values['web']['State']['Running'] = True
    result = lifecycle.stop_after_failure()
    assert not result['complete'] and 'running:project' in result['failed']
    assert runner.values['web']['State']['Running']


def test_media_adds_only_the_expected_socket_environment(rig):
    lifecycle, _ = stopped(rig)
    value = container('media', 'candidate')
    lifecycle.check('media', value, 'candidate')
    value['Config']['Env'].append('EXTRA=changed')
    with pytest.raises(ReleaseError, match='environment_changed'): lifecycle.check('media', value, 'candidate')


def test_app_cannot_start_before_data_writers_stop(rig):
    lifecycle, runner, _ = rig
    lifecycle.capture('parent')
    with pytest.raises(ReleaseError): lifecycle.start_app_only()
    assert not any('up' in a for a, _ in runner.calls)
