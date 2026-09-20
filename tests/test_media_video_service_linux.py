"""Actual Linux AF_UNIX lifecycle; unsupported platforms FAIL, never skip.

Run only in the separately reviewed isolated, non-root Linux test container.
No Flask, accounts, database, Google, production path or network is involved.
"""
from contextlib import closing
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time

import pytest

from media_videos import VideoTools
import media_video_service as service
import media_video_transport as wire


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def wait_until(predicate, seconds=10):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        value = predicate()
        if value:
            return value
        time.sleep(.025)
    raise AssertionError('Observed condition did not finish within bounded wait')


def process(pid):
    """PID + start ticks avoids accidentally signalling a reused unrelated PID."""
    try:
        root = Path('/proc') / str(pid)
        fields = (root / 'stat').read_text().rsplit(')', 1)[1].split()
        return dict(pid=pid, parent=int(fields[1]), startTicks=int(fields[19]), state=fields[0],
                    argv=(root / 'cmdline').read_bytes().split(b'\0')[:-1])
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return None


def descendants(parent):
    rows = {}
    for root in Path('/proc').iterdir():
        if root.name.isdecimal():
            value = process(int(root.name))
            if value:
                rows[value['pid']] = value
    selected, pending = {}, {parent}
    while pending:
        found = {pid: row for pid, row in rows.items() if row['parent'] in pending and pid not in selected}
        selected.update(found); pending = set(found)
    return selected


def alive(original):
    current = process(original['pid'])
    return bool(current and current['startTicks'] == original['startTicks'])


def public_process(value):
    return {**value, 'argv': [part.decode(errors='replace') for part in value['argv']]}


@pytest.fixture(scope='module', autouse=True)
def linux_only():
    if not sys.platform.startswith('linux') or not hasattr(socket, 'AF_UNIX'):
        pytest.fail('Linux AF_UNIX required: Windows collection is preparation only; do not claim skipped success')
    if os.geteuid() == 0:
        pytest.fail('This suite requires the reviewed non-root test-container user')
    assert Path('/proc/self/stat').is_file(), 'Actual /proc lifecycle observation is required'


@pytest.fixture(scope='module')
def configuration(linux_only):
    destination = os.environ.get('MEDIA_SERVICE_TEST_EVIDENCE_DIR', '')
    assert destination, 'Set a new dedicated evidence directory inside the disposable proof mount'
    evidence = Path(destination)
    assert evidence.is_absolute() and evidence.parent.is_dir() and not evidence.exists()
    assert not any(p.is_symlink() for p in (evidence, *evidence.parents))
    evidence.mkdir(mode=0o700)
    paths = [os.environ.get('MEDIA_TEST_' + name.upper()) or shutil.which(name) for name in ('ffmpeg', 'ffprobe')]
    assert all(paths), 'Real FFmpeg and ffprobe required, never a synthetic-success decoder'
    tools = VideoTools(*(str(Path(path).resolve(strict=True)) for path in paths))
    tools.paths()
    identities = {}
    for name, path in zip(('ffmpeg', 'ffprobe'), tools.paths()):
        result = subprocess.run([path, '-version'], capture_output=True, timeout=10)
        assert result.returncode == 0
        identities[name] = dict(path=path, sha256=sha(path), version=result.stdout.decode(errors='replace'))
    source = {}
    for name in ('media_video_service', 'media_video_transport', 'media_videos', 'media_images'):
        path = Path(importlib.import_module(name).__file__).resolve()
        source[name] = dict(path=str(path), sha256=sha(path))
    source_roots = tuple(dict.fromkeys(str(Path(value['path']).parent) for value in source.values()))
    with (evidence / 'inputs.json').open('x') as stream:
        json.dump(dict(platform=sys.platform, uid=os.geteuid(), tools=identities, source=source,
                       testSha256=sha(__file__)), stream, indent=2)
    yield tools, evidence, source_roots
    assert all(sha(value['path']) == value['sha256'] for value in source.values())
    assert all(sha(value['path']) == value['sha256'] for value in identities.values())


class Scenario:
    def __init__(self, name, configuration):
        self.tools, evidence, self.source_roots = configuration
        self.out = evidence / name; self.out.mkdir(mode=0o700)
        parent = Path(os.environ.get('MEDIA_SERVICE_TEST_TEMP_ROOT', '/tmp'))
        assert parent.is_absolute() and parent.is_dir() and not parent.is_symlink()
        self.root = Path(tempfile.mkdtemp(prefix='vsl-', dir=parent)).resolve()
        self.ipc, self.work = self.root / 'ipc', self.root / 'work'
        self.ipc.mkdir(mode=0o700); self.work.mkdir(mode=0o700)
        self.path = self.ipc / 'video.sock'
        assert len(os.fsencode(self.path)) <= 103
        self.server = None; self.logs = []; self.children = {}
        self.evidence = dict(name=name, root=str(self.root), uid=os.geteuid(), observations=[], forcedCleanup=False)

    def start(self, timeout=30, paced=False):
        ffmpeg = self.tools.ffmpeg
        if paced:
            # Read-only fixed helper, NOT an executable written into noexec /tmp.
            # Its only special behavior is pacing actual /usr/bin/ffmpeg input.
            wrapper = Path(os.environ.get('MEDIA_SERVICE_TEST_FFMPEG_WRAPPER',
                str(Path(__file__).parent / 'fixtures/media_video_realtime_ffmpeg.py'))).resolve(strict=True)
            expected = Path(__file__).parent / 'fixtures/media_video_realtime_ffmpeg.py'
            assert wrapper.is_file() and os.access(wrapper, os.X_OK) and sha(wrapper) == sha(expected)
            assert Path(ffmpeg).resolve() == Path('/usr/bin/ffmpeg').resolve()
            assert Path('/usr/local/bin/python3').is_file()
            ffmpeg = str(wrapper)
            self.evidence['testWrapper'] = dict(path=str(wrapper), sha256=sha(wrapper), change='real FFmpeg -re input pacing only')
        script = ('import sys,json;sys.path[:0]=json.loads(sys.argv[1]);'
                  'from media_video_service import serve;from media_videos import VideoTools;'
                  'serve(sys.argv[2],tools=VideoTools(sys.argv[4],sys.argv[5]),temp_root=sys.argv[3],timeout=float(sys.argv[6]))')
        argv = [sys.executable, '-B', '-I', '-c', script, json.dumps(self.source_roots), str(self.path), str(self.work),
                ffmpeg, self.tools.ffprobe, str(timeout)]
        # Pass no inherited app configuration, OAuth/model keys or database paths.
        env = {'PATH': os.defpath, 'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'}
        self.logs = [(self.out / name).open('xb') for name in ('service.stdout', 'service.stderr')]
        self.server = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL,
            stdout=self.logs[0], stderr=self.logs[1], start_new_session=True, cwd=self.root)
        self.evidence.update(argv=argv, servicePid=self.server.pid, timeout=timeout, passedEnvironmentNames=sorted(env))
        def ready():
            assert self.server.poll() is None, 'Service exited before opening Unix socket'
            if not self.path.exists(): return False
            current = self.path.lstat()
            return stat.S_ISSOCK(current.st_mode) and stat.S_IMODE(current.st_mode) == 0o600
        wait_until(ready)
        status = Path('/proc', str(self.server.pid), 'status').read_text()
        ids = next(line for line in status.splitlines() if line.startswith('Uid:')).split()[1:]
        assert all(int(value) == os.geteuid() for value in ids)
        assert stat.S_IMODE(self.ipc.stat().st_mode) == stat.S_IMODE(self.work.stat().st_mode) == 0o700
        assert self.path.stat().st_uid == os.geteuid()
        self.evidence['serviceObservedUid'] = list(map(int, ids))
        self.evidence['socketMode'] = oct(stat.S_IMODE(self.path.stat().st_mode))
        return self

    def connect(self):
        wire.private_socket_path(self.path, existing=True)
        # Binding becomes visible just before listen(); retry connection only,
        # never a request or business action, and only while this child lives.
        until = time.monotonic() + 2
        while True:
            peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); peer.settimeout(5)
            try:
                peer.connect(str(self.path)); return peer
            except ConnectionRefusedError:
                peer.close()
                assert self.server.poll() is None and time.monotonic() < until
                time.sleep(.01)

    def observe_decoder(self):
        def active():
            rows = descendants(self.server.pid)
            self.children.update(rows)
            for row in rows.values():
                if (row['argv'] and row['argv'][0] == os.fsencode(self.tools.ffmpeg)
                        and os.fsencode('display.mp4') in row['argv'][-1]):
                    return row
            return None
        actual = wait_until(active, seconds=4)
        assert list(self.work.iterdir()), 'Actual codec workspace must exist before cancellation'
        self.evidence['observations'].append({'actualFFmpeg': public_process(actual),
            'workspace': [str(p.relative_to(self.work)) for p in self.work.rglob('*')]})
        return actual

    def clean_decode(self):
        wait_until(lambda: not list(self.work.iterdir()), seconds=10)
        wait_until(lambda: not any(alive(row) for row in self.children.values()), seconds=5)
        self.evidence['observations'].append({'decoderWorkspaceEmpty': True, 'observedChildrenGone': True})

    def close(self):
        errors = []
        try:
            if self.server is not None:
                self.children.update(descendants(self.server.pid))
                if self.server.poll() is None: self.server.terminate()
                try: self.server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.evidence['forcedCleanup'] = True; self.server.kill(); self.server.wait(timeout=5)
                    errors.append('Graceful SIGTERM did not finish')
                self.evidence['serviceExitCode'] = self.server.returncode
                if self.server.returncode != 0: errors.append('Service did not exit normally')
                try: self.clean_decode()
                except AssertionError: errors.append('Decoder child/temp remained after service stop')
                if self.path.exists(): errors.append('Owned socket remained after stop')
                self.evidence['socketRemoved'] = not self.path.exists()
                for row in self.children.values():
                    if alive(row):
                        # Emergency teardown only for captured descendants with
                        # matching start ticks; never turn forced cleanup green.
                        self.evidence['forcedCleanup'] = True
                        try: os.kill(row['pid'], signal.SIGKILL)
                        except ProcessLookupError: pass
            self.evidence['teardownErrors'] = errors
            self.evidence['remainingTemp'] = [str(p.relative_to(self.work)) for p in self.work.rglob('*')]
        finally:
            for stream in self.logs: stream.close()
            self.evidence['logHashes'] = {p.name: sha(p) for p in self.out.iterdir() if p.is_file()}
            with (self.out / 'evidence.json').open('x') as stream: json.dump(self.evidence, stream, indent=2)
            # Only our freshly created synthetic directory, after retaining all
            # logs/cleanup observations. No arbitrary path supplied to deletion.
            assert self.root.parent == Path(os.environ.get('MEDIA_SERVICE_TEST_TEMP_ROOT', '/tmp')).resolve()
            assert self.root.name.startswith('vsl-') and not self.root.is_symlink()
            shutil.rmtree(self.root)
        assert not errors and not self.evidence['forcedCleanup'], self.evidence


@pytest.fixture
def scenario(request, configuration):
    name = request.node.name.replace('[', '-').replace(']', '')
    value = Scenario(name, configuration)
    try:
        yield value
    except BaseException as error:
        value.evidence['testBodyCompleted'] = False
        value.evidence['testBodyFailure'] = type(error).__name__ + ': ' + str(error)[:1000]
        raise
    else:
        value.evidence['testBodyCompleted'] = True
    finally:
        value.close()


@pytest.fixture(scope='module')
def source(configuration):
    tools, evidence, _ = configuration
    target = evidence / 'synthetic-source.mp4'
    argv = [tools.ffmpeg, '-v', 'error', '-nostdin', '-y', '-f', 'lavfi', '-i',
        'testsrc2=size=160x90:rate=15:duration=12', '-f', 'lavfi', '-i',
        'sine=frequency=440:sample_rate=48000:duration=12', '-c:v', 'libx264', '-threads:v', '2',
        '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(target)]
    result = subprocess.run(argv, capture_output=True, timeout=45)
    (evidence / 'source.stdout').write_bytes(result.stdout); (evidence / 'source.stderr').write_bytes(result.stderr)
    assert result.returncode == 0, result.stderr[-1000:]
    raw = target.read_bytes(); assert 0 < len(raw) < 4 * 1024**2
    with (evidence / 'source.json').open('x') as stream:
        json.dump(dict(argv=argv, exitCode=result.returncode, sha256=sha(target), bytes=len(raw)), stream, indent=2)
    return raw


def test_linux_actual_unix_pipeline_permissions_and_stop(scenario, source):
    scenario.start()
    with closing(scenario.connect()) as peer:
        value = wire.exchange(peer, source, 'video/mp4', wire.deadline_after(25))
    assert 11800 <= value.duration_ms <= 12300 and value.has_audio
    assert value.sha256 == hashlib.sha256(value.data).hexdigest()
    assert value.poster.sha256 == hashlib.sha256(value.poster.data).hexdigest()
    assert value.content_type == 'video/mp4' and value.poster.content_type == 'image/jpeg'
    assert not list(scenario.work.iterdir())
    target = scenario.out / 'returned.mp4'; target.write_bytes(value.data)
    argv = [scenario.tools.ffmpeg, '-v', 'error', '-nostdin', '-xerror', '-i', str(target), '-f', 'null', '-']
    result = subprocess.run(argv, capture_output=True, timeout=30)
    (scenario.out / 'decode.stdout').write_bytes(result.stdout); (scenario.out / 'decode.stderr').write_bytes(result.stderr)
    assert result.returncode == 0, result.stderr[-1000:]
    scenario.evidence['actualOutput'] = dict(bytes=len(value.data), sha256=value.sha256, durationMs=value.duration_ms,
        posterBytes=len(value.poster.data), independentDecodeArgv=argv, independentDecodeExitCode=result.returncode)


def test_linux_private_paths_reject_permissions_symlink_and_stale(scenario):
    # Real filesystem/socket modes, not patched stat() results.
    scenario.ipc.chmod(0o750)
    with pytest.raises(wire.ProtocolError): wire.private_socket_path(scenario.path, existing=False)
    scenario.ipc.chmod(0o700)
    assert wire.private_socket_path(scenario.path, existing=False) == scenario.path
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.bind(str(scenario.path)); scenario.path.chmod(0o600)
        assert wire.private_socket_path(scenario.path, existing=True) == scenario.path
        scenario.path.chmod(0o660)
        with pytest.raises(wire.ProtocolError): wire.private_socket_path(scenario.path, existing=True)
        scenario.path.chmod(0o600)
        alias = scenario.root / 'alias'; alias.symlink_to(scenario.ipc, target_is_directory=True)
        with pytest.raises(wire.ProtocolError): wire.private_socket_path(alias / 'video.sock', existing=True)
    inode = scenario.path.stat().st_ino
    with pytest.raises(wire.ProtocolError):
        service.serve(scenario.path, tools=scenario.tools, temp_root=scenario.work, timeout=1)
    assert scenario.path.exists() and scenario.path.stat().st_ino == inode
    scenario.evidence['observations'].append({'staleSocketPreserved': True, 'directory750Rejected': True,
        'socket660Rejected': True, 'symlinkRejected': True})


def test_linux_single_slot_busy_and_total_receive_deadline(scenario):
    scenario.start(timeout=1.5)
    with closing(scenario.connect()) as first:
        start = time.monotonic()
        wire.send_header(first, {'v': 1, 'mime': 'video/mp4', 'length': 10, 'sha256': '0' * 64}, wire.deadline_after(2))
        first.sendall(b'a'); time.sleep(.15)
        with closing(scenario.connect()) as second:
            busy = wire.receive_header(second, wire.deadline_after(2))
            assert busy == {'v': 1, 'ok': False, 'code': 'timeout'} and second.recv(1) == b''
        for _ in range(3):
            time.sleep(.2); first.sendall(b'b')
        first.settimeout(3); assert first.recv(1) == b''
        elapsed = time.monotonic() - start
        assert 1 <= elapsed < 3, 'Incoming chunks must not renew the absolute request deadline'
    assert scenario.server.poll() is None and not descendants(scenario.server.pid)
    time.sleep(.05)  # EOF precedes the handler's immediately following slot.release().
    with closing(scenario.connect()) as fresh, pytest.raises(wire.ProtocolError) as rejected:
        wire.exchange(fresh, b'not-a-video', 'video/mp4', wire.deadline_after(2))
    assert rejected.value.code == 'invalid', 'A fresh request must reach the released slot'
    scenario.evidence['observations'].append({'busy': busy, 'elapsedSeconds': elapsed, 'slotRecovered': True})


@pytest.mark.parametrize('trigger', ('disconnect', 'sigterm', 'deadline'))
def test_linux_cancels_actual_ffmpeg_without_child_or_temp_leak(scenario, source, trigger):
    timeout = 6 if trigger == 'deadline' else 30
    scenario.start(timeout=timeout, paced=True)
    with closing(scenario.connect()) as peer:
        start = time.monotonic()
        wire.send_header(peer, {'v': 1, 'mime': 'video/mp4', 'length': len(source),
                               'sha256': hashlib.sha256(source).hexdigest()}, wire.deadline_after(5))
        peer.sendall(source)
        actual = scenario.observe_decoder()
        assert time.monotonic() - start < 4, 'Cancellation must target a live real transcode'
        if trigger == 'disconnect':
            peer.close()
        elif trigger == 'sigterm':
            scenario.server.terminate(); assert scenario.server.wait(timeout=10) == 0
        else:
            peer.settimeout(8); assert peer.recv(1) == b''
            assert 5 <= time.monotonic() - start < 9
        scenario.clean_decode()
        assert not alive(actual)
    if trigger != 'sigterm':
        assert scenario.server.poll() is None and scenario.path.exists()
        time.sleep(.05)  # Let connection close and the following slot release finish.
        with closing(scenario.connect()) as fresh, pytest.raises(wire.ProtocolError) as rejected:
            wire.exchange(fresh, b'not-a-video', 'video/mp4', wire.deadline_after(2))
        assert rejected.value.code == 'invalid'
    scenario.evidence['observations'].append({'trigger': trigger, 'elapsedSeconds': time.monotonic() - start,
                                             'actualFFmpegGone': True, 'noFakeDecoder': True})
