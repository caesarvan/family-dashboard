"""Separate 384 MiB application and 768 MiB decoder resource experiments.

Preparation is offline. Only the coordinator runs reviewed immutable images;
no build, SSH, production data, automatic retry or memory-limit expansion.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import stat
import subprocess
import sys
import threading
import time

ROOT = Path('/tmp/family-dashboard-media-ipc-probe')
SOCKET = '/decoder-private/video.sock'
PROFILES = ('worker100', 'response64')
LIMITS = {'application': 384, 'decoder': 768}
HOST_BUDGET = {'preflightMiB': 1280, 'preflightSamples': 3, 'preflightIntervalSeconds': 1,
               'abortBelowMiB': 256, 'sampleIntervalSeconds': .25, 'maxSampleLagSeconds': 1}
DECODER_FILES = ('media_video_service.py', 'media_video_transport.py', 'media_videos.py', 'media_images.py')
APP_FILES = tuple('''app.py frontend_runtime.py member_sessions.py household_members.py tv_display.py
sync_health.py household_memberships.py personal_accounts.py membership_storage.py membership_http.py
cloud_accounts.py cloud_providers.py sync_worker.py google_photos_picker.py media_crypto.py media_images.py
household_media.py media_import_worker.py media_playback.py shopping_media.py shopping_settlement.py
finance_baseline.py spending_observations.py finance_source_bridge.py finance_accounts.py journey_time.py
journey_reschedule.py finance_analysis.py finance_fx.py household_spaces.py journey_workflows.py finance_hub.py
home_assistant.py assistant_trip_intent.py assistant_trip_change_api.py assistant_finance_query.py journey_routes.py
journey_documents.py journey_places.py inventory_core.py inventory_api.py inventory_sources.py calendar_publish.py
calendar_privacy.py financial_files.py investment_import.py investment_operations.py dashboard_preferences.py
data_portability.py task_publish.py household_routines.py task_dependencies.py task_reminders.py media_videos.py
media_video_storage.py media_playback_progress.py media_video_transport.py requirements.txt'''.split())
SELF = 'deploy/media_video_ipc_resource_probe.py'


def need(value, message):
    if not value:
        raise RuntimeError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf8') as f:
        json.dump(value, f, indent=2, ensure_ascii=False)
        f.write('\n')


def safe(path, *, exists=False, remote=False):
    path = Path(path)
    need(path.is_absolute() and '..' not in path.parts, 'absolute non-traversing path required')
    need(not any(c in str(path) for c in '\r\n,\x00'), 'unsafe mount path')
    need(not any(p.is_symlink() for p in (path, *path.parents)), 'symlink forbidden')
    need(path.exists() == exists, 'unexpected output existence')
    if remote:
        need(path.is_relative_to(ROOT) and path != ROOT, 'outside isolated probe root')
    return path


def image_id(value):
    need(isinstance(value, str) and re.fullmatch('sha256:[0-9a-f]{64}', value), 'immutable image ID required')
    return value


def prepare(source, head, output, application_image, decoder_image):
    """Hash Git inputs; actual runtime must come from each immutable image."""
    source = safe(source, exists=True)
    need(re.fullmatch('[0-9a-f]{40}', head), 'full source commit required')
    need(subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source).decode().strip() == head, 'HEAD differs')
    image_id(application_image); image_id(decoder_image)
    need(application_image != decoder_image, 'distinct images required')
    blobs = {}
    for name in dict.fromkeys((*APP_FILES, *DECODER_FILES, SELF)):
        raw = subprocess.check_output(['git', 'show', head + ':' + name], cwd=source)
        need(raw == (source / name).read_bytes(), 'working bytes differ: ' + name)
        blobs[name] = hashlib.sha256(raw).hexdigest()
        if name.endswith('.py') and name != SELF:
            for node in ast.walk(ast.parse(raw)):
                imports = ([node.module] if isinstance(node, ast.ImportFrom) and node.module else
                           [a.name for a in node.names] if isinstance(node, ast.Import) else [])
                for module in imports:
                    local = module.split('.')[0] + '.py'
                    need(not (source / local).is_file() or local in blobs or local in APP_FILES or local in DECODER_FILES,
                         'unbound local import: ' + local)
    need(blobs[SELF] == sha(__file__), 'executed preparation tool differs')
    output = safe(output); output.mkdir(parents=True, mode=0o755)
    tools = output / 'tools'; tools.mkdir(mode=0o755)
    (tools / 'probe.py').write_bytes(Path(__file__).read_bytes())
    contract = {'sourceHead': head, 'images': {'application': application_image, 'decoder': decoder_image},
                'limitsMiB': LIMITS, 'app': {n: blobs[n] for n in APP_FILES},
                'decoder': {n: blobs[n] for n in DECODER_FILES}, 'probeSha256': blobs[SELF]}
    save(tools / 'inputs.json', contract)
    for path in tools.iterdir(): path.chmod(0o644)
    save(output / 'prepared.json', {'inputsSha256': sha(tools / 'inputs.json'), **contract})
    return contract


def prepared(path):
    path = safe(path, exists=True)
    record = json.loads((path / 'prepared.json').read_text())
    tools = path / 'tools'; contract = json.loads((tools / 'inputs.json').read_text())
    need(record == {'inputsSha256': sha(tools / 'inputs.json'), **contract}, 'manifest binding differs')
    need(contract['limitsMiB'] == LIMITS and set(contract['app']) == set(APP_FILES)
         and set(contract['decoder']) == set(DECODER_FILES)
         and set(contract['images']) == set(LIMITS), 'source closure differs')
    need({p.name for p in tools.iterdir()} == {'probe.py', 'inputs.json'} and
         not any(p.is_symlink() for p in tools.iterdir()), 'unexpected tools input')
    need(sha(tools / 'probe.py') == sha(__file__) == contract['probeSha256'], 'probe bytes differ')
    for image in contract['images'].values():
        image_id(image)
    need(contract['images']['application'] != contract['images']['decoder'], 'same image forbidden')
    return tools, record


def container_args(role, profile, image, tools, output):
    need(role in LIMITS and profile in PROFILES, 'unreviewed role or profile')
    image_id(image)
    tools = safe(tools, exists=True, remote=True); output = safe(output, exists=True, remote=True)
    memory = LIMITS[role]
    mounts = [(tools, '/input', True), (output / role, '/proof', False),
              (output / 'socket', '/decoder-private', False), (output / 'fixtures', '/fixtures', role == 'application')]
    args = ['create', '--network=none', '--read-only', '--user=10001:10001', '--cap-drop=ALL',
            '--security-opt=no-new-privileges:true', '--cpus=1', f'--memory={memory}m',
            f'--memory-swap={memory}m', '--pids-limit=128', '--ulimit=nofile=128:128',
            '--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=384m,mode=1777']
    if role == 'decoder':
        args.append('--tmpfs=/decode-temp:rw,noexec,nosuid,nodev,size=384m,mode=0700,uid=10001,gid=10001')
    args.extend('--mount=type=bind,src=' + str(src) + ',dst=' + dst + (',readonly' if ro else '')
                for src, dst, ro in mounts)
    args += ['--workdir=/' + ('app' if role == 'application' else 'decoder'), '--entrypoint=/usr/bin/env', image,
             '-i', 'PATH=/usr/local/bin:/usr/bin:/bin', 'LANG=C.UTF-8', 'HOME=/tmp',
             'PYTHONDONTWRITEBYTECODE=1', 'PYTHONUNBUFFERED=1', 'python', '-B', '-X', 'utf8',
             '/input/probe.py', 'inside', '--role', role, '--profile', profile]
    return args


def mem_available_kib():
    match = re.search(r'^MemAvailable:\s+(\d+) kB$', Path('/proc/meminfo').read_text(), re.M)
    need(match is not None, 'MemAvailable missing or malformed')
    return int(match[1])


def host_preflight(output, *, reader=None, sleeper=None):
    reader, sleeper = reader or mem_available_kib, sleeper or time.sleep
    samples = []; failure = None
    try:
        for index in range(HOST_BUDGET['preflightSamples']):
            if index: sleeper(HOST_BUDGET['preflightIntervalSeconds'])
            value = reader()
            need(type(value) is int and value >= 0, 'invalid MemAvailable reading')
            samples.append({'at': time.time(), 'monotonic': time.monotonic(), 'availableKiB': value})
        if any(s['availableKiB'] < HOST_BUDGET['preflightMiB'] * 1024 for s in samples):
            failure = 'host_memory_below_preflight_threshold'
    except BaseException as error:
        failure = 'host_memory_read_failed:' + type(error).__name__
    record = {'status': 'preflight_blocked' if failure else 'ready', 'policy': HOST_BUDGET,
              'samples': samples, 'failure': failure}
    save(output / 'preflight.json', record)
    return record


class HostMemoryAbort(RuntimeError):
    pass


class HostMemoryMonitor:
    """One read-only sampler; only the coordinator may issue Docker commands."""
    def __init__(self, output, *, reader=None):
        self.output, self.reader = output, reader or mem_available_kib
        self.stop_event, self.ready = threading.Event(), threading.Event()
        self.lock = threading.Lock(); self.failure = None
        self.count = 0; self.minimum = None; self.last_sample = time.monotonic()
        self.thread = None; self.thread_started = False; self.stream = None

    def latch(self, reason):
        with self.lock:
            if self.failure is None: self.failure = {'reason': reason, 'at': time.time()}

    def _sample(self):
        try:
            while not self.stop_event.is_set():
                value = self.reader()
                need(type(value) is int and value >= 0, 'invalid MemAvailable reading')
                if self.stop_event.is_set(): break
                sample = {'at': time.time(), 'monotonic': time.monotonic(), 'availableKiB': value}
                self.stream.write(json.dumps(sample) + '\n'); self.stream.flush()
                with self.lock:
                    self.count += 1; self.minimum = value if self.minimum is None else min(self.minimum, value)
                    self.last_sample = sample['monotonic']
                if value < HOST_BUDGET['abortBelowMiB'] * 1024: self.latch('host_memory_below_abort_threshold')
                self.ready.set()
                if self.stop_event.wait(HOST_BUDGET['sampleIntervalSeconds']): break
        except BaseException as error:
            self.latch('host_memory_monitor_failed:' + type(error).__name__); self.ready.set()

    def start(self):
        self.stream = (self.output / 'host-memory-samples.jsonl').open('x', encoding='utf8')
        self.thread = threading.Thread(target=self._sample, name='host-memory-monitor', daemon=True)
        try:
            self.thread.start()
            self.thread_started = True
        except BaseException as error:
            self.latch('host_memory_thread_start_failed:' + type(error).__name__)
            raise HostMemoryAbort(self.failure['reason']) from error
        if not self.ready.wait(HOST_BUDGET['maxSampleLagSeconds']): self.latch('host_memory_monitor_stalled')
        self.check()

    def check(self):
        if not self.thread_started or not self.thread.is_alive(): self.latch('host_memory_monitor_stopped')
        if time.monotonic() - self.last_sample > HOST_BUDGET['maxSampleLagSeconds']:
            self.latch('host_memory_monitor_stalled')
        if self.failure: raise HostMemoryAbort(self.failure['reason'])

    def finish(self):
        # Check before our deliberate stop so an unexpected dead thread cannot pass.
        try: self.check()
        except HostMemoryAbort: pass
        self.stop_event.set()
        if self.thread_started: self.thread.join(HOST_BUDGET['maxSampleLagSeconds'])
        if self.thread_started and self.thread.is_alive(): self.latch('host_memory_monitor_join_failed')
        elif self.stream: self.stream.close()
        record = {'policy': HOST_BUDGET, 'sampleCount': self.count, 'minimumAvailableKiB': self.minimum,
                  'failure': self.failure, 'threadStarted': self.thread_started,
                  'threadStopped': not self.thread_started or not self.thread.is_alive()}
        save(self.output / 'host-memory.json', record)
        return record


class Executor:
    def __init__(self, output):
        self.output, self.records = output, []

    def call(self, args, *, timeout=120, check=True, guard=None, interruptible=True):
        if guard: guard.check()
        argv = ['docker', '--host', 'unix:///var/run/docker.sock', *args]
        stem = self.output / f'command-{len(self.records):02d}'
        env = {'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
               'HOME': str(self.output), 'DOCKER_CONFIG': str(self.output / 'empty-docker-config')}
        with Path(str(stem) + '.stdout').open('xb') as out, Path(str(stem) + '.stderr').open('xb') as err:
            child = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err)
            started = {'argv': argv, 'pid': child.pid, 'startedAt': time.time()}
            save(str(stem) + '.started.json', started)
            aborted = None; child_code = None; deadline = time.monotonic() + timeout
            try:
                while True:
                    if guard and interruptible: guard.check()
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        child.kill(); child_code = child.wait(); code = 124; break
                    try:
                        code = child_code = child.wait(timeout=min(.25, remaining)); break
                    except subprocess.TimeoutExpired:
                        continue
            except BaseException as error:
                child.kill(); child_code = child.wait(); code = 125; aborted = error
        receipt = {**started, 'exitCode': code, 'completedAt': time.time(),
                   'childExitCode': child_code,
                   'abortedBy': type(aborted).__name__ if aborted else None,
                   'stdoutSha256': sha(str(stem) + '.stdout'), 'stderrSha256': sha(str(stem) + '.stderr')}
        save(str(stem) + '.json', receipt); self.records.append(receipt)
        if aborted is not None: raise aborted
        if check:
            need(code == 0, 'command failed; preserve evidence, no retry')
        return code, Path(str(stem) + '.stdout').read_bytes()


def cleanup_owned(executor, owned, output, monitor):
    """On pressure, kill all known new IDs first; never wait ten seconds per role."""
    errors = []; states = {}; ids = list(reversed(list(owned.items())))
    need(all(re.fullmatch('[0-9a-f]{64}', cid) for _, cid in ids), 'invalid owned cleanup ID')
    pressure = False
    try: monitor.check()
    except HostMemoryAbort: pressure = True
    if not pressure:
        for role, cid in ids:
            try: executor.call(['stop', '--time=10', cid], timeout=30, check=False, guard=monitor)
            except HostMemoryAbort:
                pressure = True; break
            except Exception as error: errors.append({'role': role, 'error': type(error).__name__})
    if pressure:
        for role, cid in ids:
            try: executor.call(['kill', cid], timeout=10, check=False)
            except Exception as error: errors.append({'role': role, 'error': type(error).__name__})
    for role, cid in ids:
        try:
            _, raw = executor.call(['inspect', cid]); states[role] = json.loads(raw)[0]
            save(output / (role + '-container.json'), states[role])
            executor.call(['logs', cid], check=False)
        except Exception as error: errors.append({'role': role, 'error': type(error).__name__})
    return states, errors


def verify_final(states, proofs, worker_exit, contract, profile):
    need(worker_exit == 0 and set(states) == set(LIMITS) and set(proofs) == set(LIMITS), 'both roles required')
    for role in LIMITS:
        state, proof = states[role], proofs[role]
        need(state['Image'] == contract['images'][role] and proof['sourceHead'] == contract['sourceHead']
             and proof['profile'] == profile, 'role/source/image binding differs')
        need(state['State']['ExitCode'] == 0 and not state['State']['OOMKilled']
             and not state['State']['Running'], 'container failed or still running: ' + role)
        need(state['HostConfig']['Memory'] == LIMITS[role] * 1024**2
             and state['HostConfig']['MemorySwap'] == LIMITS[role] * 1024**2, 'limit differs')
        need(state['HostConfig']['NetworkMode'] == 'none' and state['HostConfig']['ReadonlyRootfs']
             and state['Config']['User'] == '10001:10001', 'actual isolation differs')
        need(proof['exitCode'] == 0 and proof['role'] == role and proof['loadedSourceVerified'], 'inside proof failed')
        need(all(int(line.split()[1]) == 0 for line in proof['cgroup']['memory.events'].splitlines()
                 if line.split()[0] in ('oom', 'oom_kill', 'oom_group_kill', 'max')), 'cgroup limit event')
    need(states['application']['Id'] != states['decoder']['Id'], 'same cgroup experiment forbidden')


def run(input_dir, output, profile):
    need(sys.platform == 'linux' and sys.dont_write_bytecode and not sys.flags.optimize, 'Linux python -B without -O required')
    need(profile in PROFILES, 'unreviewed profile')
    tools, contract = prepared(input_dir)
    safe(tools, exists=True, remote=True)
    output = safe(output, remote=True); output.mkdir(parents=True, mode=0o700)
    save(output / 'started.json', {'profile': profile, 'contract': contract, 'hostBudget': HOST_BUDGET, 'startedAt': time.time()})
    preflight = host_preflight(output)
    if preflight['status'] == 'preflight_blocked':
        save(output / 'result.json', {'passed': False, 'status': 'preflight_blocked', 'profile': profile,
             'contract': contract, 'failure': preflight['failure'], 'containers': {}, 'commands': [],
             'artifacts': {f.name: sha(f) for f in output.iterdir() if f.is_file()}, 'completedAt': time.time()})
        raise RuntimeError('preflight_blocked; no containers created, no automatic retry')
    for name in ('application', 'decoder', 'socket', 'fixtures'):
        folder = output / name; folder.mkdir(mode=0o700); os.chown(folder, 10001, 10001)
    executor = Executor(output); owned = {}; states = {}; worker_exit = None; failure = None; unconfirmed_create = None
    monitor = HostMemoryMonitor(output)
    try:
        monitor.start()
        for role, image in contract['images'].items():
            _, raw = executor.call(['image', 'inspect', image], guard=monitor); info = json.loads(raw)[0]
            need(info['Id'] == image, 'image identity differs')
            for value in info['Config'].get('Env', []):
                need(not any(k in value.partition('=')[0].upper() for k in ('SECRET', 'PASSWORD', 'TOKEN', 'API_KEY', 'PROXY')), 'image embeds unsafe environment')
        for role in ('decoder', 'application'):
            # Create both containers before starting either workload. Obtain each
            # ID before consuming an abort so owned-only cleanup has a known target.
            unconfirmed_create = {'role': role, 'reason': 'create attempt has no confirmed ID; see original command receipt'}
            _, raw = executor.call(container_args(role, profile, contract['images'][role], tools, output),
                                   timeout=10, guard=monitor, interruptible=False)
            cid = raw.decode().strip(); need(re.fullmatch('[0-9a-f]{64}', cid), 'invalid container ID')
            owned[role] = cid; save(output / (role + '-owned.json'), {'id': cid, 'image': contract['images'][role]})
            unconfirmed_create = None
            monitor.check()
        executor.call(['start', owned['decoder']], guard=monitor)
        until = time.monotonic() + 240
        while True:
            monitor.check()
            path = output / 'socket/video.sock'
            if path.exists():
                mode = path.lstat()
                need(stat.S_ISSOCK(mode.st_mode) and stat.S_IMODE(mode.st_mode) == 0o600 and mode.st_uid == 10001,
                     'decoder socket ownership differs')
                need((output / 'fixtures/fixture.json').is_file(), 'fixture missing')
                break
            need(not (output / 'decoder/finished.json').exists() and time.monotonic() < until, 'decoder setup failed/timed out')
            time.sleep(.1)
        worker_exit, _ = executor.call(['start', '--attach', owned['application']], timeout=1800, check=False, guard=monitor)
        monitor.check()
    except BaseException as error:
        failure = type(error).__name__ + ': ' + str(error)
    finally:
        states, cleanup_errors = cleanup_owned(executor, owned, output, monitor)
        host_memory = monitor.finish()
        if host_memory['failure']:
            failure = failure or host_memory['failure']['reason']
        proofs = {}
        for role in owned:
            path = output / role / 'finished.json'
            if path.is_file():
                try: proofs[role] = json.loads(path.read_text())
                except Exception as error: cleanup_errors.append({'role': role, 'error': 'partial_inside_proof:' + type(error).__name__})
        passed = False
        if failure is None and not cleanup_errors:
            try:
                verify_final(states, proofs, worker_exit, contract, profile); passed = True
            except Exception as error:
                failure = type(error).__name__ + ': ' + str(error)
        save(output / 'result.json', {'passed': passed, 'failure': failure, 'profile': profile,
             'contract': contract, 'workerAttachExitCode': worker_exit, 'containers': owned,
             'unconfirmedCreate': unconfirmed_create,
             'status': 'passed' if passed else 'aborted' if host_memory['failure'] else 'failed',
             'hostMemory': host_memory,
             'proofs': proofs, 'cleanupErrors': cleanup_errors, 'commands': executor.records,
             'artifacts': {f.relative_to(output).as_posix(): sha(f) for f in output.rglob('*') if f.is_file()},
             'completedAt': time.time()})
    need(passed, 'resource experiment failed; original evidence retained, no retry')


def cgroup(role):
    root = Path('/sys/fs/cgroup')
    values = {n: (root / n).read_text() for n in ('memory.max', 'memory.swap.max', 'memory.peak',
               'memory.events', 'memory.current', 'cpu.max', 'cpu.stat', 'pids.max', 'pids.peak')}
    need(int(values['memory.max']) == LIMITS[role] * 1024**2 and values['memory.swap.max'].strip() == '0', 'actual cgroup memory differs')
    need(values['pids.max'].strip() == '128', 'actual pids limit differs')
    quota, period = map(int, values['cpu.max'].split()); need(0 < quota <= period, 'actual CPU limit differs')
    return values


def verify_runtime(contract, role):
    root = Path('/app' if role == 'application' else '/decoder')
    expected = contract['app' if role == 'application' else 'decoder']
    for name, value in expected.items():
        path = root / name
        need(not path.is_symlink() and sha(path) == value, 'runtime differs: ' + name)
    loaded = {}
    for name, module in tuple(sys.modules.items()):
        path = getattr(module, '__file__', None)
        if not path:
            continue
        actual = Path(path).resolve()
        if actual.parent == root:
            need(actual.name in expected and name + '.py' == actual.name, 'unexpected installed local module')
        if name + '.py' not in expected:
            continue
        need(actual == root / (name + '.py'), 'unbound runtime import: ' + name)
        loaded[name] = {'path': str(actual), 'sha256': sha(actual)}
    return loaded


def padded_mp4(path, target):
    extra = target - path.stat().st_size
    need(8 <= extra < 2**32, 'invalid MP4 free-box padding')
    with path.open('ab') as stream:
        stream.write(extra.to_bytes(4, 'big') + b'free')
        while extra > 8:
            amount = min(extra - 8, 1024**2); stream.write(bytes(amount)); extra -= amount
    need(path.stat().st_size == target, 'size fixture differs')


def decoder_case(profile, proof):
    from media_videos import VideoTools, sanitize_media_video
    from media_video_service import serve
    tools = VideoTools('/usr/bin/ffmpeg', '/usr/bin/ffprobe')
    fixtures = Path('/fixtures'); source = fixtures / 'source.mp4'
    argv = [tools.ffmpeg, '-v', 'error', '-nostdin', '-y', '-f', 'lavfi', '-i',
            'testsrc2=size=160x90:rate=15:duration=12', '-f', 'lavfi', '-i',
            'sine=frequency=440:sample_rate=48000:duration=12', '-c:v', 'libx264', '-threads:v', '2',
            '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(source)]
    commands = []
    def command(args):
        stem = proof / f'fixture-{len(commands)}'
        with Path(str(stem) + '.stdout').open('xb') as out, Path(str(stem) + '.stderr').open('xb') as err:
            result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=out, stderr=err, timeout=180)
        commands.append({'argv': args, 'exitCode': result.returncode, 'stdoutSha256': sha(str(stem) + '.stdout'), 'stderrSha256': sha(str(stem) + '.stderr')})
        save(str(stem) + '.json', commands[-1]); need(result.returncode == 0, 'real fixture codec failed')
    for executable in tools.paths(): command([executable, '-version'])
    command(argv)
    if profile == 'worker100':
        padded_mp4(source, 100 * 1024**2)
        info = {'path': source.name, 'bytes': source.stat().st_size, 'sha256': sha(source)}
    else:
        video = sanitize_media_video(source.read_bytes(), 'video/mp4', tools=tools, temp_root='/decode-temp')
        target = fixtures / 'display.mp4'; target.write_bytes(video.data); padded_mp4(target, 64 * 1024**2)
        (fixtures / 'poster.jpg').write_bytes(video.poster.data)
        info = {'path': target.name, 'bytes': target.stat().st_size, 'sha256': sha(target),
                'width': video.width, 'height': video.height, 'durationMs': video.duration_ms, 'hasAudio': video.has_audio,
                'posterBytes': len(video.poster.data), 'posterSha256': video.poster.sha256,
                'posterWidth': video.poster.width, 'posterHeight': video.poster.height}
    command([tools.ffmpeg, '-v', 'error', '-nostdin', '-xerror', '-i', str(fixtures / info['path']), '-f', 'null', '-'])
    save(fixtures / 'fixture.json', {'profile': profile, **info,
         'note': 'Actual complete synthetic MP4 plus legal free-box padding; size pressure, not coding complexity.'})
    save(proof / 'decoder-ready.json', {'tools': {n: {'path': p, 'sha256': sha(p)} for n, p in zip(('ffmpeg', 'ffprobe'), tools.paths())}, 'fixture': info})
    serve(SOCKET, tools=tools, temp_root='/decode-temp')
    need(not Path(SOCKET).exists() and not list(Path('/decode-temp').iterdir()), 'decoder shutdown left private state')


@contextmanager
def network_guard():
    """Exact private IPC only; no DNS/TCP/alternate Unix sockets or fallback."""
    from unittest.mock import patch
    original = socket.socket.connect
    calls = []
    def connect(peer, address):
        need(peer.family == socket.AF_UNIX and address == SOCKET, 'network outside exact decoder socket forbidden')
        calls.append({'family': 'AF_UNIX', 'path': SOCKET})
        return original(peer, address)
    def forbidden(*_args, **_kwargs):
        raise RuntimeError('external network or local codec fallback forbidden')
    with patch.object(socket.socket, 'connect', connect), patch.object(socket.socket, 'connect_ex', forbidden), \
         patch.object(socket, 'create_connection', forbidden), patch.object(socket, 'getaddrinfo', forbidden):
        yield calls, forbidden


class FileResponse:
    def __init__(self, path):
        from email.message import Message
        self.stream = path.open('rb'); self.status = 200; self.url = None; self.closed = False; self.bytes_read = 0
        self.headers = Message(); self.headers['Content-Type'] = 'video/mp4'; self.headers['Content-Length'] = str(path.stat().st_size)

    def geturl(self): return self.url

    def read1(self, size):
        need(type(size) is int and 0 < size <= 65536, 'unbounded Picker transport read')
        raw = self.stream.read(size); self.bytes_read += len(raw); return raw

    def close(self):
        self.stream.close(); self.closed = True


class JsonResponse:
    def __init__(self, value=None, status=200):
        from email.message import Message
        from io import BytesIO
        self.stream = BytesIO(json.dumps(value).encode() if value is not None else b'')
        self.status = status; self.url = None; self.headers = Message(); self.headers['Content-Type'] = 'application/json'

    def geturl(self): return self.url
    def read1(self, size): return self.stream.read(size)
    def close(self): self.stream.close()


def application_case(profile, proof):
    """Real app/member sessions/Picker parser/worker/AES/SQLite/WSGI. Synthetic seeds only."""
    import gc
    from unittest.mock import patch
    from app import create_app
    from cloud_accounts import GOOGLE_PHOTOS_SCOPE
    from google_photos_picker import GooglePhotosPicker
    from media_import_worker import MediaImportWorker
    from media_images import Preview
    import media_videos
    from media_videos import VideoPreview
    import media_crypto
    with network_guard() as (socket_calls, forbidden), patch.object(media_videos, 'sanitize_media_video', forbidden):
        os.environ['MEMBER1_PASSWORD'] = os.environ['MEMBER2_PASSWORD'] = 'synthetic-ipc-password'
        app = create_app({'TESTING': True, 'DATA_DIR': str(proof / 'household'), 'SECRET_KEY': 'synthetic-ipc-secret',
            'SESSION_COOKIE_SECURE': False, 'PUBLIC_ORIGIN': 'http://localhost', 'MEDIA_VIDEO_SOCKET': SOCKET,
            'GOOGLE_CLIENT_ID': 'synthetic-client', 'GOOGLE_CLIENT_SECRET': 'synthetic-secret',
            'MICROSOFT_CLIENT_ID': '', 'MICROSOFT_CLIENT_SECRET': '', 'OPENAI_API_KEY': '', 'NVIDIA_API_KEY': ''})
        engine = app.extensions['household_media']; account = secrets.token_hex(16)
        with engine.accounts.db() as con:
            tokens = engine.accounts.encrypt({'access_token': 'synthetic-token', 'scope': GOOGLE_PHOTOS_SCOPE, 'expires_at': time.time() + 3600})
            con.execute('INSERT INTO cloud_accounts(id,owner,provider,client_id,subject,name,email,tokens) VALUES(?,?,?,?,?,?,?,?)',
                        (account, 'member1', 'google', 'synthetic-client', 'synthetic-subject', 'Synthetic', 'test.invalid', tokens))
        def login(number):
            c = app.test_client(); c.get('/api/me')
            need(c.post('/api/login', json={'username': 'member' + str(number), 'password': 'synthetic-ipc-password'}).status_code == 200, 'login failed')
            return c, {'X-CSRF-Token': c.get('/api/me').json['csrf'], 'Origin': 'http://localhost'}
        client, headers = login(1); other, _ = login(2)
        response = client.post('/api/media/imports', json={'requestId': secrets.token_hex(16), 'accountId': account,
            'consentVersion': 'media-v1', 'allowTemporaryProcessing': True}, headers=headers)
        need(response.status_code == 202, 'real import creation failed'); imp = response.json['import']
        session = {'id': 'synthetic-session', 'pickerUri': 'https://photos.google.com/picker/synthetic',
                   'expireTime': datetime.fromtimestamp(time.time() + 3600, timezone.utc).isoformat(), 'mediaItemsSet': True}
        item = {'id': 'synthetic-video', 'createTime': '2026-09-01T00:00:00Z', 'type': 'VIDEO', 'mediaFile': {
            'baseUrl': 'https://lh3.googleusercontent.com/p/synthetic-video', 'mimeType': 'video/mp4', 'filename': 'synthetic.mp4',
            'mediaFileMetadata': {'width': 160, 'height': 90, 'videoMetadata': {'processingStatus': 'READY'}}}}
        fixture = json.loads(Path('/fixtures/fixture.json').read_text()); need(fixture['profile'] == profile, 'profile fixture differs')
        need(fixture['path'] == ('source.mp4' if profile == 'worker100' else 'display.mp4'), 'unexpected fixture path')
        path = Path('/fixtures') / fixture['path']; need(sha(path) == fixture['sha256'] and path.stat().st_size == fixture['bytes'], 'fixture bytes differ')
        transport_calls = []; stream = None
        if profile == 'worker100':
            need(fixture['bytes'] == 100 * 1024**2, '100MiB source required')
            stream = FileResponse(path)
            queue = [session, session, {'mediaItems': [item]}, session, {'mediaItems': [item]}, stream, JsonResponse(status=204)]
            def transport(method, url, *, headers, body, timeout):
                need(bool(queue), 'unexpected Picker transport call')
                transport_calls.append({'method': method, 'video': url.endswith('=dv')})
                value = queue.pop(0); value = JsonResponse(value) if isinstance(value, dict) else value
                value.url = url; return value
            worker = MediaImportWorker(engine, picker_factory=lambda token: GooglePhotosPicker(token, transport=transport), jitter=lambda: 0)
            try:
                need(worker.tick() and worker.tick() and worker.tick(), 'three actual worker claims failed')
                need(stream.closed and stream.bytes_read == 100 * 1024**2, 'actual full Picker download differs')
                need(len(socket_calls) == 1, 'worker did not use exact one real IPC decode')
            finally:
                stream.close()
        else:
            need(fixture['bytes'] == 64 * 1024**2, '64MiB display fixture required')
            need(engine.complete(engine.claim_next(), session), 'fixture create failed')
            public_item = json.loads(json.dumps(item)); public_item['mediaFile'].pop('baseUrl')
            need(engine.complete(engine.claim_next(), [public_item]), 'fixture list failed')
            poster = Path('/fixtures/poster.jpg').read_bytes(); need(hashlib.sha256(poster).hexdigest() == fixture['posterSha256'], 'poster differs')
            data = path.read_bytes()
            video = VideoPreview(data, 'video/mp4', fixture['width'], fixture['height'], fixture['durationMs'],
                fixture['hasAudio'], fixture['sha256'], Preview(poster, 'image/jpeg', fixture['posterWidth'], fixture['posterHeight'], fixture['posterSha256']))
            need(engine.complete(engine.claim_next(), {'mediaId': item['id'], 'manifest': [public_item], 'preview': video.poster, 'video': video}), 'size fixture stage failed')
            del video, data, poster; gc.collect()
        detail = client.get('/api/media/imports/' + imp['id']).json
        need(detail['import']['state'] == 'awaiting_confirmation' and len(detail['items']) == 1, 'real video not staged')
        payload = {'revision': detail['import']['revision'], 'confirmRequestId': secrets.token_hex(16),
                   'itemIds': [detail['items'][0]['id']], 'consentVersion': 'media-v1', 'persistSelected': True}
        confirmed = client.post('/api/media/imports/' + imp['id'] + '/confirm', json=payload, headers=headers)
        need(confirmed.status_code == 200, 'real confirmation failed'); uid = confirmed.json['itemIds'][0]
        if profile == 'worker100':
            need(worker.tick() and not queue, 'Picker cleanup incomplete')
        with engine.transaction() as con:
            row = con.execute('SELECT * FROM media_items WHERE id=?', (uid,)).fetchone(); meta = engine._metadata(row)
        before = client.get('/api/media/items/' + uid).json['item']; need(before['visibility'] == 'private' and before['mediaType'] == 'video', 'metadata differs')
        need(other.get('/api/media/items/' + uid).status_code == 404, 'other member sees private metadata')
        denied = other.get(before['videoUrl']); need(denied.status_code == 404, 'other member sees private bytes'); denied.close()
        response = client.get(before['videoUrl'], buffered=False); length = 0; observed = hashlib.sha256()
        try:
            need(response.status_code == 200 and response.content_type == 'video/mp4' and 'no-store' in response.headers['Cache-Control'], 'real WSGI GET failed')
            busy = client.get(before['videoUrl']); need(busy.status_code == 503 and busy.json['code'] == 'video_busy', 'response permit released before close'); busy.close()
            for chunk in response.response:
                need(type(chunk) is bytes, 'non-bytes WSGI body'); length += len(chunk); observed.update(chunk)
            del chunk
            need(length == meta['videoBytes'] and observed.hexdigest() == meta['videoSha256'], 'full WSGI bytes differ')
        finally:
            response.close()
        del response; gc.collect()
        import household_media
        acquired = household_media._VIDEO_READ_SLOT.acquire(blocking=False)
        if acquired: household_media._VIDEO_READ_SLOT.release()
        need(acquired, 'WSGI close did not release video permit')
        after = client.get('/api/media/items/' + uid).json['item']
        need(after['id'] == before['id'] and after['revision'] == before['revision'], 'read changed identity/revision')
        replay = client.post('/api/media/imports/' + imp['id'] + '/confirm', json=payload, headers=headers)
        need(replay.status_code == 200 and replay.json['replayed'] and replay.json['itemIds'] == [uid], 'confirmation replay differs')
        with engine.transaction() as con:
            cache = con.execute('SELECT length(cipher),substr(cipher,1,?) FROM media_video_cache WHERE media_id=?', (len(media_crypto._VIDEO_HEADER), uid)).fetchone()
            counts = {n: con.execute('SELECT count(*) FROM ' + n).fetchone()[0] for n in ('media_items', 'media_video_cache')}
            reserved = con.execute('SELECT reserved_bytes FROM media_imports WHERE id=?', (imp['id'],)).fetchone()[0]
        need(cache[0] == length + media_crypto._VIDEO_OVERHEAD and cache[1] == media_crypto._VIDEO_HEADER, 'AES envelope differs')
        need(counts == {'media_items': 1, 'media_video_cache': 1} and reserved == 0, 'commit/quota differs')
        save(proof / 'application.json', {'profile': profile, 'sourceHeadScope': 'Installed fixed candidate modules, not parent fallback',
             'transportCalls': transport_calls, 'socketCalls': socket_calls, 'downloadBytes': stream.bytes_read if stream else None,
             'responseBytes': length, 'responseSha256': observed.hexdigest(), 'responseClosed': True, 'busyWhileOpen': True,
             'permitReleasedAfterClose': acquired, 'otherMemberDenied': True, 'idRevisionPreserved': True,
             'confirmationReplayed': True, 'cipherBytes': cache[0], 'counts': counts, 'reservedBytes': reserved,
             'fixtureNote': fixture['note'], 'response64IsExplicitSizeFixture': profile == 'response64'})


def inside(role, profile):
    need(sys.platform == 'linux' and os.geteuid() == 10001 and sys.dont_write_bytecode and not sys.flags.optimize,
         'unprivileged Linux python -B without -O required')
    need(role in LIMITS and profile in PROFILES, 'invalid inside role')
    proof = Path('/proof'); contract = json.loads(Path('/input/inputs.json').read_text())
    need(contract['limitsMiB'] == LIMITS and sha(__file__) == contract['probeSha256'], 'inside contract differs')
    sys.path[:0] = ['/app' if role == 'application' else '/decoder']
    save(proof / 'started.json', {'role': role, 'profile': profile, 'sourceHead': contract['sourceHead'], 'startedAt': time.time(), 'cgroup': cgroup(role)})
    code = 1; loaded = {}; verified = False; dependencies = {}
    try:
        verify_runtime(contract, role)
        from importlib.metadata import version
        if role == 'application':
            for line in Path('/app/requirements.txt').read_text().splitlines():
                if not line.strip() or line.startswith('#'): continue
                name, expected = line.split('=='); dependencies[name] = version(name)
                need(dependencies[name] == expected, 'installed dependency differs: ' + name)
        else:
            dependencies['Pillow'] = version('Pillow')
        if role == 'application': application_case(profile, proof)
        else: decoder_case(profile, proof)
        loaded = verify_runtime(contract, role); verified = True; code = 0
    finally:
        save(proof / 'finished.json', {'role': role, 'profile': profile, 'exitCode': code, 'loadedSourceVerified': verified,
             'loadedModules': loaded, 'dependencies': dependencies, 'sourceHead': contract['sourceHead'],
             'completedAt': time.time(), 'cgroup': cgroup(role)})


def main():
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare')
    for n in ('source', 'head', 'output', 'application-image', 'decoder-image'): p.add_argument('--' + n, required=True)
    p = sub.add_parser('run'); p.add_argument('--prepared', required=True); p.add_argument('--output', required=True); p.add_argument('--profile', choices=PROFILES, required=True)
    p = sub.add_parser('inside'); p.add_argument('--role', choices=tuple(LIMITS), required=True); p.add_argument('--profile', choices=PROFILES, required=True)
    a = parser.parse_args()
    if a.command == 'prepare': prepare(a.source, a.head, a.output, a.application_image, a.decoder_image)
    elif a.command == 'run': run(a.prepared, a.output, a.profile)
    else: inside(a.role, a.profile)


if __name__ == '__main__':
    main()
