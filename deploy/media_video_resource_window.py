"""One reversible media-worker maintenance window for two isolated probes.

No production image/source/database change. Only the original media container
is stopped and restarted; it has no heartbeat, so restart proves process state
only. The frozen probe owns its new containers and the unchanged memory gates.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path('/opt/family-dashboard')
RELEASES = Path('/opt/family-dashboard-releases')
LAB = Path('/tmp/family-dashboard-media-ipc-probe')
PREPARED = LAB / 'ipc-8c8a-20260920-r1/prepared'
INPUTS = {'prepared.json': 'bd1f02ae12fdf6a6bf77fed82c0a96993211324ce060a771f3e468e4e58e4b72',
          'tools/inputs.json': '05e849a8e32e342e11a693b46b929480aeaa0aca3571c891de66eadf4cc5da8d',
          'tools/probe.py': '486683bde4531e02b2e70d26b46b94b667a3c72432e1fd623f26dbfa4fbba312'}
SOURCE = {'RELEASE-MANIFEST.json': '83ff8610c85eccf9dfc5e9dac788d2704543e8dc68d937e1463fbf7819add5c1',
          'compose.yaml': '803c3c1551f2ccb1f285a8d578dbeab7ea4e53102e1cbb64d9a69d6c4d30dad1',
          'Dockerfile': '511cc2a0b14439278630a905db8782ab601c62c3b52ca27926192ab9577a7f19',
          '.env': 'a72d456815cf113b1ac0c1e032ac8c45b300ccf2cb499520c14b7f54d5314e07'}
PARENT_IMAGE = 'sha256:a783c58c882748d273c5956e2d94a43c99261c61c6b41f0489118d9fd96f6654'
WEB_IMAGE = 'sha256:1ae82dcc4a34bcd976195b3c4c5a6b7e569505527a1e2a28c2101e032159a5c7'
IDS = {'app': '543d758b064caadbe91bbf685d0415ec0f99d33de18888a54913614e1cd8374e',
       'sync': 'd4a056e762d075edb98bef2e4f1a82c227d54e11e96601366b8be2a8b891d98b',
       'media': 'b61a8daec97a32f73a73a298d40918a782cf9933018099f5f11aad071b45bf6d',
       'web': '8109d1ec20e57ec990122bc85d0e44a9d52e83e95c1dfee08bc94bb94a383ce7'}
DOCKER = ['docker', '--host', 'unix:///var/run/docker.sock']
TIMER = 'family-dashboard-backup.timer'
SERVICE = 'family-dashboard-backup.service'


def need(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def save(path, value):
    with Path(path).open('x', encoding='utf8') as f:
        json.dump(value, f, indent=2); f.write('\n')


def regular(path):
    path = Path(path)
    need(path.is_absolute() and not any(p.is_symlink() for p in (path, *path.parents)), 'unsafe_path')
    need(path.is_file(), 'file_missing')
    return path


class Commands:
    def __init__(self, output):
        self.output, self.records = output, []

    def __call__(self, argv, *, timeout=120, private=False):
        index = len(self.records)
        env = {'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
               'HOME': str(self.output), 'DOCKER_CONFIG': str(self.output / 'empty-docker-config')}
        child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, env=env)
        started = {'argv': argv, 'pid': child.pid, 'startedAt': time.time(), 'privateOutput': private}
        save(self.output / f'command-{index:02d}.started.json', started)
        # Stop and probes use no observer deadline; their original process is
        # followed to terminal. Never kill an outstanding production stop RPC.
        try:
            out, err = child.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            child.kill(); out, err = child.communicate()
            code = 124
        else:
            code = child.returncode
        record = {**started, 'exitCode': code, 'childExitCode': child.returncode,
                  'completedAt': time.time(), 'stdoutSha256': digest(out), 'stderrSha256': digest(err)}
        if not private:
            (self.output / f'command-{index:02d}.stdout').write_bytes(out)
            (self.output / f'command-{index:02d}.stderr').write_bytes(err)
        save(self.output / f'command-{index:02d}.json', record); self.records.append(record)
        need(code == 0, 'command_failed_' + str(index))
        return out


class Window:
    def __init__(self, output, call, *, sleeper=time.sleep):
        self.output, self.call = Path(output), call
        self.sleep = sleeper
        self.baseline, self.profiles = None, []
        self.timer_stopped = self.stop_attempted = self.stop_completed = False

    def fixed_inputs(self):
        for base, files in ((ROOT, SOURCE), (PREPARED, INPUTS)):
            for name, expected in files.items():
                need(digest(regular(base / name).read_bytes()) == expected, 'input_changed_' + name)
        need((ROOT / '.env').stat().st_mode & 0o777 == 0o600, 'environment_permissions')

    def inspect(self, name):
        value = json.loads(self.call([*DOCKER, 'inspect', 'family-dashboard-' + name + '-1'], private=True))[0]
        need(value['Id'] == IDS[name] and value['Name'] == '/family-dashboard-' + name + '-1', 'parent_identity')
        labels = value['Config']['Labels']
        need(labels.get('com.docker.compose.project') == 'family-dashboard' and
             labels.get('com.docker.compose.service') == name, 'parent_labels')
        need(value['Image'] == (WEB_IMAGE if name == 'web' else PARENT_IMAGE), 'parent_image')
        need(not value['State']['OOMKilled'] and value['RestartCount'] == 0, 'parent_unhealthy')
        immutable = {key: value[key] for key in ('Id', 'Image', 'Config', 'HostConfig', 'Mounts')}
        # Docker constructs Mounts from a map; list order is not configuration.
        # Preserve every field while canonicalizing by unique destination.
        mounts = value['Mounts']
        need(isinstance(mounts, list) and all(isinstance(m, dict) and isinstance(m.get('Destination'), str)
             for m in mounts) and len({m['Destination'] for m in mounts}) == len(mounts), 'invalid_mounts')
        immutable['Mounts'] = sorted(mounts, key=lambda m: m['Destination'])
        state = value['State']
        return {'id': value['Id'], 'image': value['Image'], 'configurationSha256': digest(encoded(immutable)),
                'running': state['Running'], 'exitCode': state['ExitCode'], 'pid': state['Pid'],
                'startedAt': state['StartedAt'], 'health': state.get('Health', {}).get('Status')}

    def capture(self, *, media_running=True):
        current = {name: self.inspect(name) for name in IDS}
        actual = self.call([*DOCKER, 'ps', '--all', '--quiet', '--no-trunc', '--filter',
                            'label=com.docker.compose.project=family-dashboard']).decode().splitlines()
        need(len(actual) == 4 and set(actual) == set(IDS.values()), 'project_containers_changed')
        for name, value in current.items():
            need(value['running'] is (media_running if name == 'media' else True), 'parent_running_state')
            if name == 'app': need(value['health'] == 'healthy', 'app_unhealthy')
            if name == 'media' and not media_running: need(value['exitCode'] == 0, 'media_unclean_exit')
            if self.baseline:
                need(value['configurationSha256'] == self.baseline[name]['configurationSha256'], 'parent_configuration_changed')
                if name != 'media':
                    need(value['startedAt'] == self.baseline[name]['startedAt'] and
                         value['pid'] == self.baseline[name]['pid'], 'other_service_restarted')
        return current

    def unit(self, name):
        return self.call(['systemctl', 'show', '-p', 'ActiveState', '--value', name]).decode().strip()

    def experiments_stopped(self):
        for profile in self.profiles:
            proof = json.loads(regular(self.output / profile / 'result.json').read_bytes())
            need(proof.get('unconfirmedCreate') is None, 'experiment_create_unknown')
            for cid in proof['containers'].values():
                need(re.fullmatch('[0-9a-f]{64}', cid) and cid not in IDS.values(), 'experiment_identity_invalid')
                state = json.loads(self.call([*DOCKER, 'inspect', cid], private=True))[0]
                need(state['Id'] == cid and state['State']['Running'] is False, 'experiment_still_running')

    def run(self):
        result = {'passed': False, 'productionSourceChanged': False, 'mediaProcessRestored': False,
                  'workerTickVerified': False, 'profiles': [], 'failure': None, 'recoveryFailure': None}
        try:
            self.fixed_inputs(); self.baseline = self.capture()
            save(self.output / 'parent-before.json', self.baseline)
            need(self.unit(TIMER) == 'active' and self.unit(SERVICE) == 'inactive', 'backup_not_idle')
            self.timer_stopped = True
            self.call(['systemctl', 'stop', TIMER])
            need(self.unit(SERVICE) == 'inactive', 'backup_raced_timer_stop')
            self.fixed_inputs(); self.capture()
            self.stop_attempted = True
            self.call([*DOCKER, 'stop', '--signal', 'SIGTERM', '--timeout', '-1', IDS['media']], timeout=None)
            self.stop_completed = True
            save(self.output / 'parent-drained.json', self.capture(media_running=False))
            for profile in ('worker100', 'response64'):
                self.fixed_inputs(); self.capture(media_running=False)
                self.profiles.append(profile)
                self.call(['python3', '-B', '-X', 'utf8', str(PREPARED / 'tools/probe.py'), 'run',
                           '--prepared', str(PREPARED), '--output', str(self.output / profile),
                           '--profile', profile], timeout=None)
                proof_bytes = regular(self.output / profile / 'result.json').read_bytes()
                proof = json.loads(proof_bytes)
                self.experiments_stopped()
                need(proof.get('passed') is True and proof.get('status') == 'passed', 'resource_not_passed')
                result['profiles'].append({'profile': profile, 'resultSha256': digest(proof_bytes), 'passed': True})
            result['passed'] = True
        except BaseException as error:
            result['failure'] = type(error).__name__ + ':' + str(error)
        finally:
            if self.timer_stopped:
                try:
                    self.experiments_stopped(); self.fixed_inputs()
                    if self.stop_attempted:
                        need(self.stop_completed, 'original_stop_not_confirmed_terminal')
                        self.capture(media_running=False)
                        self.call([*DOCKER, 'start', IDS['media']])
                    restored = self.capture()
                    for index in range(2):
                        self.sleep(1)
                        observed = self.capture()
                        need(observed['media']['pid'] == restored['media']['pid'] and
                             observed['media']['startedAt'] == restored['media']['startedAt'], 'media_restarted_during_recovery')
                        restored = observed
                    save(self.output / 'parent-after.json', restored)
                    result['mediaProcessRestored'] = True
                    self.call(['systemctl', 'start', TIMER])
                    need(self.unit(TIMER) == 'active', 'backup_timer_restore_failed')
                    result['backupTimerRestored'] = True
                except BaseException as error:
                    result['recoveryFailure'] = type(error).__name__ + ':' + str(error)
            result['passed'] = bool(result['passed'] and result['mediaProcessRestored'] and
                                    result.get('backupTimerRestored') and not result['recoveryFailure'])
            save(self.output / 'result.json', result)
        return result


@contextmanager
def locks():
    import fcntl
    descriptors = []
    try:
        need(RELEASES.is_dir() and not any(p.is_symlink() for p in (RELEASES, *RELEASES.parents)), 'release_root_invalid')
        for name in ('.membership-release.lock', '.static-release.lock'):
            fd = os.open(RELEASES / name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            descriptors.append(fd); fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        for fd in reversed(descriptors): os.close(fd)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--output', type=Path, required=True)
    output = parser.parse_args().output
    need(sys.platform == 'linux' and os.geteuid() == 0 and sys.dont_write_bytecode and not sys.flags.optimize, 'linux_root_python_B_required')
    need(output.parent == LAB and not output.exists() and
         re.fullmatch('resource-window-[a-z0-9-]+', output.name) and
         not any(p.is_symlink() for p in (output, *output.parents)), 'fresh_isolated_output_required')
    with locks():
        output.mkdir(mode=0o700)
        save(output / 'started.json', {'startedAt': time.time(), 'pid': os.getpid(), 'operatorSha256': digest(Path(__file__).read_bytes())})
        result = Window(output, Commands(output)).run()
    print(json.dumps(result))
    raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()
