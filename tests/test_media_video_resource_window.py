import copy
import json
from pathlib import Path

import pytest

from deploy import media_video_resource_window as window


class Simulation:
    def __init__(self, output, fault=None):
        self.output, self.fault, self.commands = output, fault, []
        self.running, self.timer, self.service_reads = True, 'active', 0
        self.started, self.app_pid, self.changed = False, 11, False
        self.web_reads = 0
        self.experiments = {}

    def __call__(self, argv, *, timeout=120, private=False):
        self.commands.append((argv, timeout, private))
        if argv[0] == 'systemctl':
            if argv[1] == 'show':
                if argv[-1] == window.TIMER: return self.timer.encode()
                self.service_reads += 1
                busy = self.fault == 'backup_active' or self.fault == 'backup_race' and self.service_reads > 1
                return b'active' if busy else b'inactive'
            self.timer = 'inactive' if argv[1] == 'stop' else 'active'
            return b''
        if argv[0] == 'python3':
            name = argv[-1]
            out = Path(argv[argv.index('--output') + 1]); out.mkdir()
            if self.fault == 'missing_result': raise RuntimeError('unknown_probe_result')
            if self.fault == 'app_restarted': self.app_pid += 1
            if self.fault == 'source_changed': self.changed = True
            ids = {} if self.fault == 'preflight_blocked' else {'application': ('e' if name == 'worker100' else 'f') * 64}
            for cid in ids.values(): self.experiments[cid] = self.fault == 'experiment_running'
            passed = self.fault not in ('preflight_blocked', 'profile_failed')
            window.save(out / 'result.json', {'passed': passed, 'status': 'passed' if passed else 'failed',
                        'containers': ids, 'unconfirmedCreate': None})
            if not passed: raise RuntimeError('probe_failed')
            return b''
        assert argv[:3] == window.DOCKER
        action = argv[3]
        if action == 'ps': return '\n'.join(window.IDS.values()).encode()
        if action == 'stop':
            assert argv == [*window.DOCKER, 'stop', '--signal', 'SIGTERM', '--timeout', '-1', window.IDS['media']]
            assert timeout is None
            if self.fault == 'unknown_stop': raise RuntimeError('stop_failed')
            self.running = False
            return window.IDS['media'].encode()
        if action == 'start':
            assert argv[-1] == window.IDS['media']
            if self.fault == 'start_failed': raise RuntimeError('start_failed')
            self.running, self.started = True, True
            return argv[-1].encode()
        assert action == 'inspect' and private
        key = argv[-1]
        if key in self.experiments:
            return json.dumps([{'Id': key, 'State': {'Running': self.experiments[key]}}]).encode()
        name = key.removeprefix('family-dashboard-').removesuffix('-1')
        running = self.running if name == 'media' else True
        value = {'Id': window.IDS[name], 'Name': '/' + key,
                 'Image': window.WEB_IMAGE if name == 'web' else window.PARENT_IMAGE,
                 'Config': {'Labels': {'com.docker.compose.project': 'family-dashboard', 'com.docker.compose.service': name},
                            'Env': ['PRIVATE_TEST_VALUE=never-store-inspect-stdout']},
                 'HostConfig': {}, 'Mounts': [], 'RestartCount': 0,
                 'State': {'Running': running, 'OOMKilled': False, 'ExitCode': 0,
                           'Pid': self.app_pid if name == 'app' else (22 if self.started and name == 'media' else 12),
                           'StartedAt': 'new' if self.started and name == 'media' else 'original',
                           'Health': {'Status': 'healthy'}}}
        if self.fault == 'wrong_parent': value['Id'] = '0' * 64
        if name == 'web' and self.fault in ('mount_order', 'mount_value', 'duplicate_mount'):
            self.web_reads += 1
            mounts = [{'Destination': '/a', 'Source': '/original-a', 'RW': False},
                      {'Destination': '/b', 'Source': '/original-b', 'RW': False}]
            if self.fault == 'duplicate_mount': mounts[1]['Destination'] = '/a'
            if self.fault == 'mount_value' and self.web_reads > 1: mounts[1]['RW'] = True
            value['Mounts'] = mounts if self.web_reads % 2 else list(reversed(mounts))
        return json.dumps([value]).encode()


@pytest.fixture
def rig(tmp_path, monkeypatch):
    def make(fault=None):
        sim = Simulation(tmp_path, fault)
        obj = window.Window(tmp_path, sim, sleeper=lambda _: None)
        def inputs():
            if fault == 'initial_input_changed' or sim.changed:
                raise RuntimeError('input_changed')
        monkeypatch.setattr(obj, 'fixed_inputs', inputs)
        return sim, obj
    return make


def mutations(sim):
    return [c[0] for c in sim.commands if c[0][0] == 'systemctl' and c[0][1] in ('stop', 'start')
            or c[0][:3] == window.DOCKER and c[0][3] in ('stop', 'start')]


def test_success_runs_two_profiles_then_recovers_only_original_media_and_timer(rig):
    sim, obj = rig(); result = obj.run()
    assert result['passed'] and result['mediaProcessRestored'] and result['backupTimerRestored']
    assert result['workerTickVerified'] is False and sim.timer == 'active'
    assert [p['profile'] for p in result['profiles']] == ['worker100', 'response64']
    assert len(mutations(sim)) == 4
    assert not any(any(x in c[0] for x in ('kill', 'rm', 'create', 'compose', 'restart')) for c in sim.commands)
    for p in result['profiles']:
        assert p['resultSha256'] == window.digest((obj.output / p['profile'] / 'result.json').read_bytes())


@pytest.mark.parametrize('fault', ['preflight_blocked', 'profile_failed'])
def test_failed_profile_restores_parent_without_running_second_profile(rig, fault):
    sim, obj = rig(fault); result = obj.run()
    assert not result['passed'] and result['mediaProcessRestored'] and result['backupTimerRestored']
    assert obj.profiles == ['worker100'] and sim.running and sim.timer == 'active'


@pytest.mark.parametrize('fault', ['backup_active', 'wrong_parent', 'initial_input_changed'])
def test_invalid_initial_state_has_no_mutating_commands(rig, fault):
    sim, obj = rig(fault); result = obj.run()
    assert not result['passed'] and not mutations(sim) and not obj.profiles


def test_backup_start_race_restores_timer_without_stopping_media(rig):
    sim, obj = rig('backup_race'); result = obj.run()
    assert not result['passed'] and result['mediaProcessRestored'] and result['backupTimerRestored']
    assert not obj.stop_attempted and not obj.profiles and len(mutations(sim)) == 2


@pytest.mark.parametrize('fault', ['missing_result', 'experiment_running', 'app_restarted', 'source_changed', 'unknown_stop', 'start_failed'])
def test_uncertain_or_changed_state_prevents_false_recovery_claim(rig, fault):
    sim, obj = rig(fault); result = obj.run()
    assert not result['passed'] and result['recoveryFailure'] and not result['mediaProcessRestored']
    assert sim.timer == 'inactive' and not result.get('backupTimerRestored')
    if fault != 'start_failed':
        assert [*window.DOCKER, 'start', window.IDS['media']] not in mutations(sim)


def test_frozen_input_validation_detects_changes_and_private_mode(tmp_path, monkeypatch):
    root, prep = tmp_path / 'app', tmp_path / 'prepared'; root.mkdir(); prep.mkdir()
    (root / '.env').write_bytes(b'fictional-local-only'); (root / '.env').chmod(0o600)
    (prep / 'probe.py').write_bytes(b'reviewed')
    monkeypatch.setattr(window, 'ROOT', root); monkeypatch.setattr(window, 'PREPARED', prep)
    monkeypatch.setattr(window, 'SOURCE', {'.env': window.digest(b'fictional-local-only')})
    monkeypatch.setattr(window, 'INPUTS', {'probe.py': window.digest(b'reviewed')})
    # Windows chmod does not expose POSIX permissions: use a stat wrapper only
    # for this Unix mode field, leaving actual file reads/hashes in place.
    original = Path.stat
    if __import__('os').name == 'nt':
        class Mode:
            st_mode = 0o100600
        def stat(path, *a, **kw):
            value = original(path, *a, **kw)
            return Mode() if path == root / '.env' else value
        monkeypatch.setattr(Path, 'stat', stat)
    obj = window.Window(tmp_path, None)
    obj.fixed_inputs()
    (prep / 'probe.py').write_bytes(b'changed')
    with pytest.raises(RuntimeError, match='input_changed_probe.py'): obj.fixed_inputs()


def test_private_command_output_is_hashed_but_never_written(tmp_path, monkeypatch):
    class Child:
        pid, returncode = 123, 0
        def communicate(self, timeout): return b'synthetic-private-inspect', b''
    monkeypatch.setattr(window.subprocess, 'Popen', lambda *a, **kw: Child())
    run = window.Commands(tmp_path)
    assert run([*window.DOCKER, 'inspect', window.IDS['media']], private=True) == b'synthetic-private-inspect'
    assert not list(tmp_path.glob('*.stdout')) and not list(tmp_path.glob('*.stderr'))
    assert all(b'synthetic-private-inspect' not in f.read_bytes() for f in tmp_path.iterdir())


def test_docker_mount_order_changes_do_not_block_drain_or_recovery(rig):
    sim, obj = rig('mount_order'); result = obj.run()
    assert result['passed'] and result['mediaProcessRestored'] and result['backupTimerRestored']
    assert sim.web_reads >= 5 and len(mutations(sim)) == 4


def test_changed_mount_value_is_still_rejected(rig):
    sim, obj = rig('mount_value'); result = obj.run()
    assert not result['passed'] and result['failure'].endswith('parent_configuration_changed')
    assert not obj.stop_attempted and not obj.profiles


def test_duplicate_mount_destinations_fail_before_mutation(rig):
    sim, obj = rig('duplicate_mount'); result = obj.run()
    assert not result['passed'] and result['failure'].endswith('invalid_mounts')
    assert not mutations(sim)
