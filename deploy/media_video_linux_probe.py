"""Candidate-only codec probe. Preparation is offline; Linux build/run need review.

No SSH, production paths, Compose, existing tags, or automatic larger-limit retry.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET

PARENT = 'sha256:a783c58c882748d273c5956e2d94a43c99261c61c6b41f0489118d9fd96f6654'
REMOTE_ROOT = Path('/tmp/family-dashboard-media-probe')
SOURCE_FILES = {
    'media_videos.py': 'media_videos.py', 'media_images.py': 'media_images.py',
    'media_crypto.py': 'media_crypto.py', 'tests/test_media_videos.py': 'tests/test_media_videos.py',
    'deploy/media_video_linux_probe.py': 'probe.py',
    'deploy/Dockerfile.media-video-probe': 'Dockerfile',
}
CORE_NAMES = (
    'test_actual_h264_audio_complete_decode_poster_and_metadata',
    'test_actual_hevc_10bit_rotates_pixels_to_portrait',
    'test_actual_full_ten_minutes_is_not_a_short_preview',
    'test_actual_over_ten_minutes_rejected_without_truncation',
    'test_hdr_is_explicitly_unsupported_without_unverified_tonemapping',
    *(f'test_rejects_actual_damage_wrong_input_and_limits[{fault}]' for fault in
      ('truncated', 'fake-header', 'playlist', 'mime', 'empty', 'oversize')),
    'test_missing_tools_fail_explicitly_without_diagnostic_leak',
    'test_real_mov_external_track_cannot_fetch_loopback',
    'test_actual_subprocess_timeout_and_output_budget',
    'test_real_windows_job_memory_limit_or_posix_rlimit',
    'test_timeout_removes_private_temporary_files',
)


def need(value, message):
    if not value:
        raise RuntimeError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def safe_path(value, *, existing=False, remote=False):
    path = Path(value).absolute()
    need(not any(part in ('.', '..') for part in path.parts), 'relative traversal forbidden')
    need(not any(char in str(path) for char in ('\n', '\r', ',', '\x00')), 'unsafe path')
    for parent in (path, *path.parents):
        need(not parent.is_symlink(), 'symlink forbidden')
    if remote:
        need(path.is_relative_to(REMOTE_ROOT) and path != REMOTE_ROOT, 'remote output must be under dedicated /tmp root')
    need(path.exists() if existing else not path.exists(), 'unexpected path existence')
    return path


def prepare(source, head, output, ffmpeg_version):
    need(re.fullmatch('[0-9a-f]{40}', head), 'fixed Git head required')
    need(re.fullmatch(r'[0-9][A-Za-z0-9:.+~_-]{1,79}', ffmpeg_version), 'exact Debian FFmpeg version required')
    source = safe_path(source, existing=True)
    need(subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source).decode().strip() == head, 'source HEAD differs')
    output = safe_path(output); output.mkdir(parents=True, mode=0o700)
    context = output / 'context'; context.mkdir(mode=0o700)
    files = {}
    for original, target in SOURCE_FILES.items():
        raw = subprocess.check_output(['git', 'show', head + ':' + original], cwd=source)
        need(raw == (source / original).read_bytes(), 'working bytes differ: ' + original)
        destination = context / target; destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as stream: stream.write(raw)
        files[target] = digest(raw)
    need((context / 'probe.py').read_bytes() == Path(__file__).read_bytes(), 'executed caller differs')
    contract = {'sourceHead': head, 'parentImage': PARENT, 'ffmpegVersion': ffmpeg_version,
                'pytestVersion': '9.0.2', 'files': files, 'coreNodes': list(CORE_NAMES)}
    save(context / 'inputs.json', contract)
    save(output / 'prepared.json', {'inputsSha256': digest((context / 'inputs.json').read_bytes()), **contract})
    return output


def prepared(path):
    root = safe_path(path, existing=True)
    record = json.loads((root / 'prepared.json').read_text())
    context = root / 'context'; raw = (context / 'inputs.json').read_bytes()
    need(record['inputsSha256'] == digest(raw), 'input manifest differs')
    contract = json.loads(raw)
    need(contract == {k: v for k, v in record.items() if k != 'inputsSha256'}, 'contract differs')
    need(contract['parentImage'] == PARENT and contract['coreNodes'] == list(CORE_NAMES), 'fixed selection differs')
    need(set(contract['files']) == set(SOURCE_FILES.values()), 'context allowlist differs')
    actual = {p.relative_to(context).as_posix(): digest(p.read_bytes()) for p in context.rglob('*') if p.is_file()}
    need(not any(p.is_symlink() for p in context.rglob('*')), 'context symlink forbidden')
    need(actual == {**contract['files'], 'inputs.json': record['inputsSha256']}, 'context bytes differ')
    need((context / 'probe.py').read_bytes() == Path(__file__).read_bytes(), 'caller differs')
    return context, record


class Executor:
    def __init__(self, output):
        need(sys.platform == 'linux' and sys.dont_write_bytecode and not sys.flags.optimize, 'Linux python -B required')
        self.output, self.records = output, []

    def call(self, arguments, timeout=120, check=True):
        args = ['docker', '--host', 'unix:///var/run/docker.sock', *arguments]
        stem = self.output / f'command-{len(self.records):02d}'
        env = {'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
               'HOME': str(self.output), 'DOCKER_CONFIG': str(self.output / 'empty-docker-config')}
        with Path(str(stem)+'.stdout').open('xb') as stdout, Path(str(stem)+'.stderr').open('xb') as stderr:
            process = subprocess.Popen(args, env=env, stdout=stdout, stderr=stderr)
            started = {'argv': args, 'pid': process.pid, 'startedAt': time.time()}
            save(Path(str(stem)+'.started.json'), started)
            try: code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(); code = 124
        result = {**started, 'exitCode': code, 'completedAt': time.time(),
                  'stdoutSha256': digest(Path(str(stem)+'.stdout').read_bytes()),
                  'stderrSha256': digest(Path(str(stem)+'.stderr').read_bytes())}
        save(Path(str(stem)+'.json'), result); self.records.append(result)
        if check: need(code == 0, 'command failed; preserve output, no automatic retry')
        return code, Path(str(stem)+'.stdout').read_bytes()


def host_budget(memory):
    need(memory in (768, 1024), 'only reviewed candidate memory levels allowed')
    values = {key: int(amount) for key, amount in re.findall(r'^(\w+):\s+(\d+) kB', Path('/proc/meminfo').read_text(), re.M)}
    need(values['MemAvailable'] >= (memory + 384) * 1024, 'insufficient current host headroom; do not increase/retry automatically')
    return {'meminfoKiB': values, 'requestedMiB': memory, 'reservedHostMiB': 384, 'observedAt': time.time()}


def build_candidate(input_dir, output):
    context, contract = prepared(input_dir)
    output = safe_path(output, remote=True); output.mkdir(parents=True, mode=0o700)
    run = Executor(output)
    _, raw = run.call(['image', 'inspect', PARENT]); parent = json.loads(raw)[0]
    need(parent['Id'] == PARENT, 'immutable parent unavailable')
    for variable in parent['Config'].get('Env', []):
        key = variable.partition('=')[0].upper()
        need(not any(word in key for word in ('PASSWORD', 'SECRET', 'TOKEN', 'API_KEY', 'PROXY')), 'parent must not embed credentials/proxy')
    save(output / 'host-before.json', host_budget(768))
    iidfile = output / 'candidate-image-id'
    run.call(['build', '--pull=false', '--network=default', '--iidfile', str(iidfile),
              '--build-arg', 'FFMPEG_VERSION='+contract['ffmpegVersion'], str(context)], timeout=1800)
    image = iidfile.read_text().strip(); need(re.fullmatch('sha256:[0-9a-f]{64}', image), 'invalid image ID')
    _, raw = run.call(['image', 'inspect', image]); info = json.loads(raw)[0]
    need(info['Id'] == image and PARENT != image, 'candidate identity differs')
    # Retrieve an already built file without starting even this candidate.
    _, raw = run.call(['create', '--network=none', '--read-only', '--user=10001:10001',
        '--cap-drop=ALL', '--security-opt=no-new-privileges:true', '--entrypoint=/bin/true', image])
    inspector = raw.decode().strip(); need(re.fullmatch('[0-9a-f]{64}', inspector), 'invalid inspector ID')
    save(output/'owned-inspector.json', {'id': inspector})
    run.call(['cp', inspector+':/probe/toolchain.json', str(output/'toolchain.json')])
    run.call(['rm', inspector])
    toolchain = json.loads((output/'toolchain.json').read_text())
    need(('ffmpeg\t'+contract['ffmpegVersion']+'\n') in toolchain['debianPackages'], 'installed FFmpeg package differs')
    save(output / 'build-result.json', {'imageId': image, 'parentImage': PARENT,
        'sourceHead': contract['sourceHead'], 'inputsSha256': contract['inputsSha256'],
        'toolchainSha256': digest((output/'toolchain.json').read_bytes()), 'toolchain': toolchain, 'commands': run.records})


def run_args(image, proof, memory, profile):
    need(re.fullmatch('sha256:[0-9a-f]{64}', image) and image != PARENT, 'candidate immutable image required')
    need(profile in ('core', 'resources', 'crypto64') and memory in (768, 1024), 'invalid experiment')
    proof = safe_path(proof, existing=True, remote=True)
    return ['create', '--network=none', '--read-only', '--user=10001:10001', '--cap-drop=ALL',
        '--security-opt=no-new-privileges:true', '--cpus=1', '--memory='+str(memory)+'m',
        '--memory-swap='+str(memory)+'m', '--pids-limit=128', '--ulimit=nofile=128:128',
        '--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=402653184,mode=1777',
        '--mount=type=bind,src='+str(proof)+',dst=/proof', '--workdir=/probe', '--entrypoint=/usr/bin/env',
        image, '-i', 'PATH=/usr/local/bin:/usr/bin:/bin', 'HOME=/tmp', 'TMPDIR=/tmp',
        'PYTHONDONTWRITEBYTECODE=1', 'PYTHONUNBUFFERED=1', 'MEDIA_TEST_FFMPEG=/usr/bin/ffmpeg',
        'MEDIA_TEST_FFPROBE=/usr/bin/ffprobe', 'python', '-B', '/probe/probe.py', 'inside',
        '--profile', profile, '--memory-mib', str(memory)]


def run_candidate(input_dir, build_result, output, memory, profile):
    _, contract = prepared(input_dir)
    result = json.loads(safe_path(build_result, existing=True).read_text())
    need(result['parentImage'] == PARENT and result['inputsSha256'] == contract['inputsSha256']
         and result['sourceHead'] == contract['sourceHead'], 'build receipt differs')
    output = safe_path(output, remote=True); output.mkdir(parents=True, mode=0o700)
    save(output / 'host-before.json', host_budget(memory))
    proof = output / 'proof'; proof.mkdir(mode=0o700); os.chown(proof, 10001, 10001)
    run = Executor(output); image = result['imageId']
    _, raw = run.call(['image', 'inspect', image]); need(json.loads(raw)[0]['Id'] == image, 'candidate image missing')
    _, raw = run.call(run_args(image, proof, memory, profile)); container = raw.decode().strip()
    need(re.fullmatch('[0-9a-f]{64}', container), 'invalid owned container ID')
    save(output / 'owned-container.json', {'id': container, 'image': image, 'profile': profile, 'memoryMiB': memory})
    code = None
    try:
        code, _ = run.call(['start', '--attach', container], timeout=5400, check=False)
    finally:
        # Only this newly created container can be stopped. Preserve it for review.
        run.call(['stop', '--time=5', container], timeout=30, check=False)
        _, raw = run.call(['inspect', container]); state = json.loads(raw)[0]
        save(output / 'container-final.json', state)
        report = {'profile': profile, 'imageId': image, 'containerId': container, 'inputsSha256': contract['inputsSha256'],
            'sourceHead': contract['sourceHead'], 'memoryMiB': memory, 'attachExit': code,
            'state': state['State'], 'commands': run.records,
            'proof': {p.name: digest(p.read_bytes()) for p in proof.iterdir() if p.is_file()}}
        report['toolchainMatchesBuild'] = (proof/'toolchain.json').is_file() and json.loads((proof/'toolchain.json').read_text()) == result['toolchain']
        report['passed'] = (code == 0 and state['State']['ExitCode'] == 0 and not state['State']['OOMKilled']
            and report['toolchainMatchesBuild'] and (proof/'finished.json').is_file()
            and json.loads((proof/'finished.json').read_text())['exitCode'] == 0)
        save(output / 'run-result.json', report)
    need(report['passed'], 'probe failed; preserve original evidence, no automatic rerun')


def fingerprint(output):
    need(sys.platform == 'linux', 'Linux tools required')
    def capture(args): return subprocess.check_output(args, timeout=60).decode()
    save(output, {'tools': {name: {'sha256': digest(Path('/usr/bin/'+name).read_bytes()),
        'version': capture(['/usr/bin/'+name, '-version'])} for name in ('ffmpeg', 'ffprobe')},
        'debianPackages': capture(['dpkg-query', '-W', '-f=${Package}\t${Version}\n']),
        'pythonPackages': capture([sys.executable, '-m', 'pip', 'freeze']),
        'osRelease': Path('/etc/os-release').read_text()})


class Monitor:
    """Container cgroup includes tmpfs/page cache; summed RSS includes shared pages."""
    def __enter__(self):
        self.done = threading.Event(); self.rss = self.memory = 0; self.started = time.monotonic()
        self.cpu = int(re.search(r'^usage_usec (\d+)', Path('/sys/fs/cgroup/cpu.stat').read_text(), re.M)[1])
        def sample():
            while not self.done.is_set():
                rss = 0
                for path in Path('/proc').glob('[0-9]*/status'):
                    try:
                        found = re.search(r'^VmRSS:\s+(\d+) kB', path.read_text(), re.M)
                        if found: rss += int(found[1]) * 1024
                    except (OSError, ProcessLookupError): pass
                self.rss = max(self.rss, rss)
                self.memory = max(self.memory, int(Path('/sys/fs/cgroup/memory.current').read_text()))
                self.done.wait(.02)
        self.thread = threading.Thread(target=sample, daemon=True); self.thread.start(); return self

    def __exit__(self, *args):
        self.done.set(); self.thread.join(timeout=2)
        self.result = {'wallSeconds': time.monotonic()-self.started, 'sampledProcessTreeRssBytes': self.rss,
            'sampledCgroupCurrentPeakBytes': self.memory,
            'cpuSeconds': (int(re.search(r'^usage_usec (\d+)', Path('/sys/fs/cgroup/cpu.stat').read_text(), re.M)[1])-self.cpu)/1e6}


def resource_cases(proof, crypto_only=False):
    sys.path.insert(0, '/probe')
    from media_videos import VideoTools, sanitize_media_video, MAX_INPUT_BYTES, MAX_OUTPUT_BYTES
    from media_crypto import MediaCipher
    import tempfile
    tools = VideoTools('/usr/bin/ffmpeg', '/usr/bin/ffprobe')
    cipher = MediaCipher('synthetic-probe-secret-never-production', 'synthetic-probe-household')
    cases = ('max-buffer-encryption',) if crypto_only else ('h264-1080p-max-input', 'hevc-1080p-10bit-rotation')
    for kind in cases:
        with tempfile.TemporaryDirectory(prefix='representative-', dir='/tmp') as directory, Monitor() as monitor:
            directory = Path(directory); source = directory / 'source.mp4'
            if kind == 'max-buffer-encryption':
                # Explicit allocation envelope, not a valid movie or codec proof.
                raw = b'Z' * MAX_OUTPUT_BYTES; display = raw
                encrypted = cipher.seal_bytes('media-video', display)
                restored = cipher.open_bytes('media-video', encrypted)
                need(restored == display and len(raw) == MAX_OUTPUT_BYTES, 'encryption envelope differs')
                record = {'kind': kind, 'validMovie': False, 'inputBytes': len(raw), 'displayBytes': len(display), 'cipherBytes': len(encrypted)}
            else:
                hevc = kind.startswith('hevc')
                command = [tools.ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=1920x1080:rate=30:duration=12',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=12', '-c:v', 'libx265' if hevc else 'libx264',
                    '-preset', 'ultrafast', '-threads:v', '2', '-pix_fmt', 'yuv420p10le' if hevc else 'yuv420p', '-c:a', 'aac']
                if hevc: command += ['-x265-params', 'pools=1:frame-threads=1:log-level=error', '-tag:v', 'hvc1']
                subprocess.run([*command, str(source)], check=True, timeout=240, stdin=subprocess.DEVNULL)
                if hevc:
                    rotated = directory / 'rotated.mp4'
                    subprocess.run([tools.ffmpeg, '-v', 'error', '-y', '-display_rotation', '90', '-i', str(source), '-c', 'copy', str(rotated)], check=True, timeout=60)
                    source = rotated
                else:
                    # Valid self-contained MP4 with a top-level free box exercises
                    # the full source buffer budget without fake decoder success.
                    padding = MAX_INPUT_BYTES-source.stat().st_size
                    need(padding >= 8, 'fixture unexpectedly large')
                    with source.open('ab') as stream:
                        stream.write(padding.to_bytes(4, 'big')+b'free')
                        while padding > 8:
                            amount = min(padding-8, 1024*1024); stream.write(bytes(amount)); padding -= amount
                raw = source.read_bytes(); workspace = directory / 'processing'; workspace.mkdir()
                started = time.monotonic(); preview = sanitize_media_video(raw, 'video/mp4', tools=tools, temp_root=workspace)
                codec_seconds = time.monotonic()-started
                encrypted = cipher.seal_bytes('media-video', preview.data)
                need(cipher.open_bytes('media-video', encrypted) == preview.data, 'real output encryption differs')
                need(abs(preview.duration_ms-12000) <= 250 and preview.has_audio, 'full representative duration/audio differs')
                need((preview.width, preview.height) == ((720, 1280) if hevc else (1280, 720)), 'output rotation/dimensions differ')
                need(not list(workspace.iterdir()), 'temporary plaintext remained')
                record = {'kind': kind, 'validMovie': True, 'sourceBytes': len(raw), 'sourceSha256': digest(raw),
                    'sourceDimensions': [1920,1080], 'sourceDurationMs': 12000, 'sourcePadded': not hevc,
                    'outputBytes': len(preview.data), 'outputSha256': preview.sha256, 'durationMs': preview.duration_ms,
                    'width': preview.width, 'height': preview.height, 'cipherBytes': len(encrypted), 'codecWallSeconds': codec_seconds}
        save(proof / (kind+'.json'), {**record, **monitor.result})
        del raw, encrypted
        if kind == 'max-buffer-encryption': del display, restored
        else: del preview


def inside(profile, memory):
    need(sys.platform == 'linux' and os.getuid() == 10001 and sys.dont_write_bytecode, 'unprivileged Linux python -B required')
    root, proof = Path('/probe'), Path('/proof')
    contract = json.loads((root / 'inputs.json').read_text())
    for name, expected in contract['files'].items(): need(digest((root / name).read_bytes()) == expected, 'image input differs')
    need(contract['parentImage'] == PARENT and contract['coreNodes'] == list(CORE_NAMES), 'selection differs')
    cgroup = Path('/sys/fs/cgroup')
    need(int((cgroup/'memory.max').read_text()) == memory*1024**2, 'memory limit differs')
    need((cgroup/'memory.swap.max').read_text().strip() == '0', 'swap must be disabled')
    need((cgroup/'pids.max').read_text().strip() == '128', 'pid limit differs')
    quota, period = map(int, (cgroup/'cpu.max').read_text().split()); need(0 < quota <= period, 'CPU limit differs')
    save(proof/'toolchain.json', json.loads((root/'toolchain.json').read_text()))
    save(proof/'started.json', {'profile': profile, 'memoryMiB': memory, 'inputsSha256': digest((root/'inputs.json').read_bytes()), 'startedAt': time.time()})
    code = 1
    try:
        if profile == 'core':
            import pytest
            class Selection:
                def pytest_collection_modifyitems(self, session, config, items):
                    need([item.name for item in items] == list(CORE_NAMES), 'exact16 selection differs')
            pytest_code = int(pytest.main(['-q', '-p', 'no:cacheprovider', '--rootdir=/probe', '--basetemp=/tmp/pytest',
                '--junitxml=/proof/core.xml', '/probe/tests/test_media_videos.py'], plugins=[Selection()]))
            suites = ET.parse(proof/'core.xml').getroot(); nodes = list(suites.iter('testcase'))
            need(pytest_code == 0 and len(nodes) == 16 and not any(n.find(k) is not None for n in nodes for k in ('failure','error','skipped')), 'core16 failed or skipped')
            code = 0
        else:
            resource_cases(proof, crypto_only=profile == 'crypto64'); code = 0
    finally:
        save(proof/'finished.json', {'exitCode': code, 'completedAt': time.time(),
            'cgroup': {name: (cgroup/name).read_text() for name in ('memory.peak','memory.events','cpu.stat','pids.peak')}})
    need(code == 0, 'probe failed')


def main():
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare'); p.add_argument('--source', required=True); p.add_argument('--source-head', required=True); p.add_argument('--output', required=True); p.add_argument('--ffmpeg-version', required=True)
    p = sub.add_parser('build'); p.add_argument('--prepared', required=True); p.add_argument('--output', required=True)
    p = sub.add_parser('run'); p.add_argument('--prepared', required=True); p.add_argument('--build-result', required=True); p.add_argument('--output', required=True); p.add_argument('--memory-mib', type=int, choices=(768,1024), default=768); p.add_argument('--profile', choices=('core','resources','crypto64'), required=True)
    p = sub.add_parser('fingerprint'); p.add_argument('--output', required=True)
    p = sub.add_parser('inside'); p.add_argument('--profile', choices=('core','resources','crypto64'), required=True); p.add_argument('--memory-mib', type=int, choices=(768,1024), required=True)
    a = parser.parse_args()
    if a.command == 'prepare': prepare(a.source, a.source_head, a.output, a.ffmpeg_version)
    elif a.command == 'build': build_candidate(a.prepared, a.output)
    elif a.command == 'run': run_candidate(a.prepared, a.build_result, a.output, a.memory_mib, a.profile)
    elif a.command == 'fingerprint': fingerprint(a.output)
    else: inside(a.profile, a.memory_mib)


if __name__ == '__main__': main()
