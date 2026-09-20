"""Two synthetic Linux experiments; no production, build, install or release actions."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time

if Path(__file__).name != 'probe.py':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BASE = '9bff5d4d21ef178a9c067f3fa39cb445819d03f0'
APP_IMAGE = 'sha256:75d2cf07e1fe01eb56fe1fed999442b922d046eba52c64e4227ed176a0e975a5'
WEB_IMAGE = 'sha256:1ae82dcc4a34bcd976195b3c4c5a6b7e569505527a1e2a28c2101e032159a5c7'
SELF = 'deploy/local_photo_linux_probe.py'
TOOLS = (SELF, 'tests/test_local_photo_linux_probe.py', 'docs/LOCAL-PHOTO-LINUX.md')
COMMON = 'deploy/media_video_ipc_resource_probe.py'
ROOT = Path('/tmp/family-dashboard-local-photo-probe')
PROFILES = ('image_overlap', 'nginx_raw')
LIMITS = {'app': 384, 'web': 96, 'client': 64}
BUDGET = {'preflightMiB': 672, 'preflightSamples': 3, 'preflightIntervalSeconds': 1,
          'abortBelowMiB': 256, 'sampleIntervalSeconds': .25, 'maxSampleLagSeconds': 1}
VIDEO_SHA = '77bae4c5e837e3db9f86b302f83a2e6881cc722604c39f6374a4977a61e71fde'
POSTER_SHA = 'cbb1abf57ac5d8e6f6f5004f45fab1185358dedf84cea18e0d8208a4974ba4f2'
MIB = 1024**2
PUBLIC = 'https://probe.invalid'
SECRET = 'synthetic-local-photo-probe-secret-not-a-real-credential'
PASSWORD = 'synthetic-local-photo-probe-password'


def need(value, message):
    if not value:
        raise RuntimeError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(64 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf8', newline='\n') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')


def safe(path, *, exists=True, remote=False):
    path = Path(path)
    need(path.is_absolute() and '..' not in path.parts and not any(x in str(path) for x in ',\n\r\x00'), 'unsafe path')
    need(not any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()) for p in (path, *path.parents)), 'linked path')
    need(path.exists() == exists, 'unexpected path existence')
    if remote:
        need(path.is_relative_to(ROOT) and path != ROOT, 'outside dedicated temporary root')
    return path


def runtime_names(blobs):
    """Exact current Docker COPY closure, not a hand-maintained partial overlay."""
    names = set()
    for line in blobs['Dockerfile'].decode().splitlines():
        if not line.startswith('COPY '):
            continue
        words = line.split()[1:]
        need(len(words) >= 2 and not any(x.startswith('--') for x in words), 'unreviewed Docker COPY syntax')
        for source in words[:-1]:
            if source in blobs:
                names.add(source)
            else:
                found = [n for n in blobs if n.startswith(source.rstrip('/') + '/')]
                need(found and source == 'static', 'unreviewed Docker directory source')
                names.update(found)
    need({'app.py', 'media_local_upload.py', 'media_images.py', 'media_crypto.py', 'requirements.txt'} <= names, 'runtime closure incomplete')
    return sorted(names)


def adapted_nginx(raw):
    text = raw.decode()
    need(text.count('proxy_request_buffering off;') == 2 and text.count('client_body_in_file_only off;') == 2, 'raw upload configuration absent')
    text = text.replace('listen 80;', 'listen 8080;').replace('listen 443 ssl', 'listen 8443 ssl')
    text = text.replace('home.caesarcharles.world', 'probe.invalid').replace('96.44.160.28', 'probe-default.invalid')
    text = re.sub(r'/etc/letsencrypt/live/family-dashboard(?:-domain)?/fullchain.pem', '/input/tls/cert.pem', text)
    text = re.sub(r'/etc/letsencrypt/live/family-dashboard(?:-domain)?/privkey.pem', '/input/tls/key.pem', text)
    text = text.replace('/var/log/nginx/access.log', '/dev/stdout')
    return ('worker_processes 1;\npid /tmp/nginx.pid;\nerror_log /dev/stderr notice;\n'
            'events { worker_connections 128; }\nhttp {\n'
            'client_body_temp_path /cache/client; proxy_temp_path /cache/proxy;\n'
            'fastcgi_temp_path /cache/fastcgi; uwsgi_temp_path /cache/uwsgi; scgi_temp_path /cache/scgi;\n'
            + text + '\n}\n').encode()


def make_images(folder):
    """Generate before any measured container starts; no unbounded noise matrix."""
    from PIL import Image
    specs = [('orientation.jpg', 'RGB', 'JPEG'), ('alpha.png', 'RGBA', 'PNG'), ('alpha.webp', 'RGBA', 'WEBP')]
    entries = []
    for index, (name, mode, fmt) in enumerate(specs):
        color = (55 + index * 40, 100, 170, 130) if mode == 'RGBA' else (55, 100, 170)
        with Image.new(mode, (5000, 4000), color) as im:
            kw = {'quality': 80} if fmt in ('JPEG', 'WEBP') else {}
            if fmt == 'JPEG':
                exif = Image.Exif(); exif[274] = 6; kw['exif'] = exif
            im.save(folder / name, fmt, **kw)
        p = folder / name
        need(0 < p.stat().st_size <= 8 * MIB, 'generated image exceeds contract')
        entries.append({'filename': name, 'contentType': {'JPEG': 'image/jpeg', 'PNG': 'image/png', 'WEBP': 'image/webp'}[fmt],
                        'bytes': p.stat().st_size, 'sha256': sha(p), 'pixels': 20_000_000, 'mode': mode})
    # JPEG trailing bytes are rejected by the sanitizer: use valid COM segments
    # before EOI to make an exactly 8 MiB, independently fully decoded image.
    with Image.new('RGB', (96, 64), (10, 80, 140)) as im:
        im.save(folder / 'small.jpg', 'JPEG')
    original = (folder / 'small.jpg').read_bytes(); missing = 8 * MIB - len(original)
    out = bytearray(original[:-2])
    while missing:
        size = min(65537, missing)
        if 0 < missing - size < 4: size -= 4
        need(size >= 4, 'invalid JPEG padding size')
        out.extend(b'\xff\xfe' + (size - 2).to_bytes(2, 'big') + b'x' * (size - 4)); missing -= size
    out.extend(b'\xff\xd9'); (folder / 'exact8.jpg').write_bytes(out)
    del out
    with Image.open(folder / 'exact8.jpg') as im: im.load(); need(im.size == (96, 64), 'padded JPEG decode differs')
    for name in ('small.jpg', 'exact8.jpg'):
        p = folder / name; entries.append({'filename': name, 'contentType': 'image/jpeg', 'bytes': p.stat().st_size, 'sha256': sha(p), 'pixels': 6144, 'mode': 'RGB'})
    return entries


def prepare(source, head, output, video_fixture):
    from deploy.git_blobs import read_git_blobs
    source, video_fixture, output = safe(source), safe(video_fixture), safe(output, exists=False)
    need(re.fullmatch('[a-f0-9]{40}', head), 'full commit required')
    def git(*args): return subprocess.check_output(['git', '--no-replace-objects', *args], cwd=source).decode().strip()
    need(git('rev-parse', 'HEAD') == head and not git('status', '--porcelain'), 'source must be fixed and clean')
    changed = git('diff', '--name-only', BASE, head).splitlines()
    need(set(changed) <= set(TOOLS), 'only the three reviewed probe files may differ from baseline')
    names = git('ls-tree', '-r', '--name-only', head).splitlines()
    candidates = [n for n in names if n == 'Dockerfile' or n == 'deploy/nginx.conf' or n == COMMON or n == SELF or '/' not in n or n.startswith('static/')]
    blobs = read_git_blobs(source, head, candidates); runtime = runtime_names(blobs)
    need(blobs[SELF] == Path(__file__).read_bytes(), 'executed probe differs from Git')
    need(sha(video_fixture / 'display.mp4') == VIDEO_SHA and (video_fixture / 'display.mp4').stat().st_size == 64 * MIB, 'unreviewed video fixture')
    need(sha(video_fixture / 'poster.jpg') == POSTER_SHA, 'unreviewed poster fixture')
    metadata = json.loads((video_fixture / 'fixture.json').read_text())
    need(metadata['width'] == 160 and metadata['height'] == 90 and metadata['durationMs'] == 12010 and metadata['hasAudio'] is True, 'video fixture metadata differs')
    output.mkdir(parents=True); (output / 'runtime').mkdir(); (output / 'fixtures').mkdir(); (output / 'tools').mkdir(); (output / 'tls').mkdir()
    for name in runtime:
        p = output / 'runtime' / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(blobs[name])
    (output / 'tools/probe.py').write_bytes(blobs[SELF]); (output / 'tools/ipc.py').write_bytes(blobs[COMMON])
    (output / 'nginx.original.conf').write_bytes(blobs['deploy/nginx.conf'])
    (output / 'nginx.conf').write_bytes(adapted_nginx(blobs['deploy/nginx.conf']))
    for name in ('display.mp4', 'poster.jpg', 'fixture.json'): shutil.copyfile(video_fixture / name, output / 'fixtures' / name)
    images = make_images(output / 'fixtures')
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from datetime import datetime, timedelta, timezone
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, 'Synthetic local photo probe')])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(days=14))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(n) for n in ('web', 'probe.invalid', 'probe-default.invalid')]), critical=False)
            .sign(key, hashes.SHA256()))
    (output / 'tls/cert.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (output / 'tls/key.pem').write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    contract = {'kind': 'local-photo-linux-input-v1', 'sourceHead': head, 'runtimeBase': BASE,
                'runtime': {n: hashlib.sha256(blobs[n]).hexdigest() for n in runtime}, 'images': {'app': APP_IMAGE, 'web': WEB_IMAGE},
                'limitsMiB': LIMITS, 'hostBudget': BUDGET, 'photoFixtures': images,
                'adaptations': ['private internal bridge, no host ports', 'synthetic HTTPS names/certificate and nonprivileged Nginx listeners',
                                'Nginx temporary paths exposed only in new synthetic directory', 'full Docker COPY runtime overlay; unchanged dependencies image',
                                'seeded already-confirmed size-only synthetic video; photo writes use real HTTP APIs'],
                'files': {p.relative_to(output).as_posix(): sha(p) for p in output.rglob('*') if p.is_file()}}
    save(output / 'input.json', contract)
    return contract


def checked_input(path):
    path = safe(path); c = json.loads((path / 'input.json').read_text())
    need(c['kind'] == 'local-photo-linux-input-v1' and c['runtimeBase'] == BASE and c['images'] == {'app': APP_IMAGE, 'web': WEB_IMAGE}
         and c['limitsMiB'] == LIMITS and c['hostBudget'] == BUDGET, 'input contract differs')
    files = {p.relative_to(path).as_posix() for p in path.rglob('*') if p.is_file()}
    need(files == set(c['files']) | {'input.json'}, 'unexpected prepared file')
    for n, digest in c['files'].items():
        need(not Path(n).is_absolute() and '..' not in Path(n).parts, 'unsafe manifest path')
        need(sha(safe(path / n)) == digest, 'prepared bytes differ: ' + n)
    need(sha(path / 'tools/probe.py') == sha(__file__), 'executed probe differs')
    need(sha(path / 'fixtures/display.mp4') == VIDEO_SHA and sha(path / 'fixtures/poster.jpg') == POSTER_SHA, 'video fixture changed')
    return c


def container_args(role, network, token, prepared, output, profile):
    need(role in LIMITS and profile in PROFILES and re.fullmatch('lp-[a-f0-9]{16}', token), 'invalid owned role')
    memory = LIMITS[role]
    args = ['create', '--pull=never', '--name', token + '-' + role, '--label', 'local-photo-probe=' + token,
            '--network', network, '--network-alias', role, '--read-only', '--user=10001:10001', '--cap-drop=ALL',
            '--security-opt=no-new-privileges:true', '--cpus=1', f'--memory={memory}m', f'--memory-swap={memory}m',
            '--pids-limit=64', '--ulimit=nofile=128:128', '--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=32m,mode=1777']
    mounts = [(prepared, '/input', True), (output / role, '/proof', False)]
    if role == 'app': mounts += [(prepared / 'runtime', '/runtime', True), (output / 'data', '/data', False)]
    if role == 'web': mounts += [(output / 'cache', '/cache', False)]
    for source, dest, readonly in mounts:
        args += ['--mount', f'type=bind,src={source},dst={dest}' + (',readonly' if readonly else '')]
    if role == 'web':
        return args + ['--entrypoint', '/usr/sbin/nginx', WEB_IMAGE, '-c', '/input/nginx.conf', '-g', 'daemon off;']
    return args + ['--entrypoint', '/usr/bin/env', APP_IMAGE, '-i', 'PATH=/usr/local/bin:/usr/bin:/bin', 'HOME=/tmp', 'LANG=C.UTF-8',
                   'PYTHONDONTWRITEBYTECODE=1', 'PYTHONUNBUFFERED=1', 'PYTHONPATH=/runtime', 'DATA_DIR=/data',
                   'SECRET_KEY=' + SECRET, 'MEMBER1_PASSWORD=' + PASSWORD, 'MEMBER2_PASSWORD=' + PASSWORD,
                   'PUBLIC_ORIGIN=' + PUBLIC, 'TRUST_PROXY=1', 'COOKIE_SECURE=1',
                   'python', '-B', '/input/tools/probe.py', 'inside', '--role', role, '--profile', profile]


def common_module():
    if Path(__file__).name == 'probe.py':
        import ipc as common
    else:
        from deploy import media_video_ipc_resource_probe as common
    # Only this probe process; no source/config or old policy is rewritten.
    common.HOST_BUDGET = dict(BUDGET)
    return common


def inspect_owned(ex, cid, role, token):
    need(re.fullmatch('[a-f0-9]{64}', cid), 'unknown CID')
    _, raw = ex.call(['inspect', '--format', '{{json .}}', cid])
    info = json.loads(raw)
    need(info['Id'] == cid and info['Config'].get('Labels', {}).get('local-photo-probe') == token
         and info['Name'] == '/' + token + '-' + role, 'container ownership differs')
    return info


def cgroup_state(pid):
    lines = Path(f'/proc/{pid}/cgroup').read_text().splitlines()
    path = next(x[3:] for x in lines if x.startswith('0::'))
    need(path.startswith('/') and '..' not in Path(path).parts, 'unknown cgroup path')
    root = Path('/sys/fs/cgroup') / path.lstrip('/')
    return {name: (root / name).read_text().strip() for name in ('memory.current', 'memory.peak', 'memory.events', 'memory.max')}


class TempWatch:
    """Linux kernel events, not an after-the-fact empty-directory assertion."""
    def __init__(self, root):
        import ctypes
        self.lib = ctypes.CDLL(None, use_errno=True); self.fd = self.lib.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        need(self.fd >= 0, 'inotify unavailable; inconclusive')
        self.events = []; self.names = {}
        for p in [root, *root.iterdir()]:
            need(p.is_dir() and not p.is_symlink(), 'unexpected temporary directory')
            wd = self.lib.inotify_add_watch(self.fd, os.fsencode(p), 0x00000100 | 0x00000200 | 0x00000002 | 0x00000008 | 0x00000040 | 0x00000080 | 0x00000400 | 0x00000800)
            need(wd >= 0, 'inotify watch failed; inconclusive'); self.names[wd] = p.name
    def sample(self):
        import struct
        while True:
            try: raw = os.read(self.fd, 65536)
            except BlockingIOError: break
            if not raw: break
            pos = 0
            while pos < len(raw):
                wd, mask, cookie, size = struct.unpack_from('iIII', raw, pos); pos += 16
                name = raw[pos:pos+size].split(b'\0')[0].decode('utf8', 'replace'); pos += size
                self.events.append({'at': time.time(), 'directory': self.names.get(wd), 'mask': mask, 'name': name})
                need(not mask & (0x4000 | 0x8000 | 0x400 | 0x800), 'inotify coverage lost; inconclusive')
    def finish(self):
        try: self.sample()
        finally: os.close(self.fd)
        need(not self.events, 'request/proxy temporary file activity observed')


def run(prepared, output, profile, expected_input_sha256):
    need(sys.platform == 'linux' and sys.dont_write_bytecode and not sys.flags.optimize, 'Linux python -B without -O required')
    need(profile in PROFILES, 'select one profile')
    prepared = safe(prepared, remote=True)
    need(re.fullmatch('[a-f0-9]{64}', expected_input_sha256 or '') and sha(prepared/'input.json') == expected_input_sha256, 'reviewed input hash differs')
    contract = checked_input(prepared)
    output = safe(output, exists=False, remote=True); output.mkdir(parents=True, mode=0o700)
    common = common_module(); ex = common.Executor(output); monitor = common.HostMemoryMonitor(output)
    owned = {}; network = None; token = 'lp-' + secrets.token_hex(8); failure = None; states = {}; samples = []; watch = None; unknown = None
    result = {'passed': False, 'profile': profile, 'inputSha256': sha(prepared/'input.json'), 'startedAt': time.time(), 'containers': owned}
    try:
        need(common.host_preflight(output)['status'] == 'ready', 'preflight blocked; no new workload')
        monitor.start()
        for folder in ('app', 'web', 'client', 'data', 'cache'):
            p = output / folder; p.mkdir(mode=0o755); os.chown(p, 10001, 10001)
        for name in ('client', 'proxy', 'fastcgi', 'uwsgi', 'scgi'):
            p = output/'cache'/name; p.mkdir(mode=0o700); os.chown(p, 10001, 10001)
        if profile == 'nginx_raw': watch = TempWatch(output/'cache')
        unknown = {'kind': 'network', 'name': token}
        _, raw = ex.call(['network', 'create', '--internal', '--driver=bridge', '--label', 'local-photo-probe='+token, token], guard=monitor, interruptible=False)
        network = raw.decode().strip(); need(re.fullmatch('[a-f0-9]{64}', network), 'unknown network creation'); unknown = None
        _, raw = ex.call(['network', 'inspect', network], guard=monitor)
        net = json.loads(raw)[0]; need(net['Id'] == network and net['Internal'] and net['Labels'].get('local-photo-probe') == token and not net['Containers'], 'network differs')
        roles = ['app'] + (['web'] if profile == 'nginx_raw' else []) + ['client']
        for role in roles:
            unknown = {'kind': 'container', 'role': role}
            _, raw = ex.call(container_args(role, network, token, prepared, output, profile), guard=monitor, interruptible=False)
            cid = raw.decode().strip(); need(re.fullmatch('[a-f0-9]{64}', cid), 'unknown container creation')
            owned[role] = cid; save(output/(role+'-owned.json'), {'id': cid}); unknown = None
            info = inspect_owned(ex, cid, role, token)
            need(info['Image'] == (WEB_IMAGE if role == 'web' else APP_IMAGE) and info['HostConfig']['Memory'] == LIMITS[role]*MIB
                 and info['HostConfig']['MemorySwap'] == LIMITS[role]*MIB and not info['HostConfig']['PortBindings'], 'container isolation differs')
        for role in roles:
            ex.call(['start', owned[role]], guard=monitor)
            if role == 'app':
                until = time.monotonic()+90
                while not (output/'app/ready.json').exists():
                    monitor.check(); need(time.monotonic()<until, 'app fixture setup timeout'); time.sleep(.25)
            states[role] = inspect_owned(ex, owned[role], role, token)
        until = time.monotonic()+240
        while not (output/'client/finished.json').exists():
            monitor.check(); need(time.monotonic()<until, 'profile timeout; unknown result')
            try:
                sample = {'at': time.time(), 'roles': {r: cgroup_state(s['State']['Pid']) for r,s in states.items()}}
            except (FileNotFoundError, ProcessLookupError):
                if (output/'client/finished.json').exists(): break
                raise
            samples.append(sample)
            if watch: watch.sample()
            time.sleep(.25)
        proof = json.loads((output/'client/result.json').read_text()); need(proof['passed'], 'HTTP profile failed or inconclusive')
        _, raw = ex.call(['wait', owned['client']], timeout=10, guard=monitor)
        need(raw.decode().strip() == '0', 'client process failed after receipt')
        if watch: watch.finish(); result['temporaryEvents'] = watch.events; watch = None
        need(samples, 'no actual cgroup measurements')
        for sample in samples:
            for state in sample['roles'].values():
                events = dict(line.split() for line in state['memory.events'].splitlines())
                need(all(int(events.get(k, '0')) == 0 for k in ('max', 'oom', 'oom_kill', 'oom_group_kill')), 'memory limit event')
        result['proof'] = proof
    except BaseException as error:
        failure = type(error).__name__+': '+str(error)
    finally:
        if watch:
            try: watch.sample()
            except Exception as error: failure = failure or str(error)
            result['temporaryEvents'] = watch.events; os.close(watch.fd)
        errors = []
        for role,cid in reversed(list(owned.items())):
            try:
                info = inspect_owned(ex,cid,role,token)
                if failure is None:
                    if role=='client' and (info['State']['Running'] or info['State']['ExitCode']!=0):
                        errors.append({'role':role,'error':'client did not exit successfully'})
                    if role!='client' and not info['State']['Running']:
                        errors.append({'role':role,'error':'service exited before controlled stop'})
                if info['State']['Running']:
                    if monitor.failure: ex.call(['kill',cid], check=False)
                    else: ex.call(['stop','--time=5',cid], timeout=10, check=False)
                info = inspect_owned(ex,cid,role,token); need(not info['State']['Running'] and info['State']['Pid']==0, 'owned container remains active')
                need(not info['State']['OOMKilled'], 'owned container OOM killed')
                save(output/(role+'-final.json'), info); ex.call(['logs',cid],check=False)
                ex.call(['rm',cid])
            except Exception as error: errors.append({'role':role,'error':str(error)})
        if network and not errors and not unknown:
            try: ex.call(['network','rm',network])
            except Exception as error: errors.append({'network':network,'error':str(error)})
        memory = monitor.finish() if monitor.thread is not None else {'threadStarted':False,'failure':None}
        save(output/'cgroup-samples.json', samples)
        if failure is None and not errors and 'proof' in result:
            try: result['database'] = database_proof(output/'data', result['proof'], profile)
            except Exception as error: failure = 'database proof: '+str(error)
        result.update(passed=failure is None and not errors and not unknown and not memory.get('failure'), failure=failure,
                      cleanupErrors=errors,unknownCreate=unknown,hostMemory=memory,commands=ex.records,completedAt=time.time())
        result['artifacts']={p.relative_to(output).as_posix():sha(p) for p in output.rglob('*') if p.is_file() and not p.is_relative_to(output/'data')}
        save(output/'result.json',result)
    need(result['passed'],'profile not passed; preserve original output, no automatic retry')


def runtime_proof(contract):
    import importlib.metadata
    versions = {}
    for line in Path('/runtime/requirements.txt').read_text().splitlines():
        package, version = line.split('=='); observed = importlib.metadata.version(package)
        need(observed == version, 'dependency version differs: '+package); versions[package] = observed
    for name,digest in contract['runtime'].items(): need(sha(Path('/runtime')/name)==digest,'runtime bytes differ: '+name)
    loaded={}
    for name,module in list(sys.modules.items()):
        if name+'.py' not in contract['runtime']: continue
        p=Path(module.__file__).resolve(); need(p==Path('/runtime')/(name+'.py'),'runtime import escaped overlay')
        loaded[name]={'path':str(p),'sha256':sha(p)}
    need('app' in loaded and 'media_local_upload' in loaded,'application imports incomplete')
    return {'modules': loaded, 'dependencies': versions}


def database_proof(data, proof, profile):
    import sqlite3
    from contextlib import closing
    paths = [data/'household.sqlite3', *sorted((data/'spaces').glob('*/household.sqlite3'))]
    need(len(paths) == (2 if profile == 'nginx_raw' else 1), 'household database count differs')
    records=[]; actual={}
    for path in paths:
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as con:
            con.row_factory=sqlite3.Row
            rows=[dict(r) for r in con.execute('SELECT id,state,visibility,revision,confirmed_at,length(preview_cipher) previewBytes,length(metadata_cipher) metadataBytes FROM media_items')]
            actual.update({r['id']:r for r in rows})
            records.append({'path':path.relative_to(data).as_posix(),'items':rows,'audit':dict(con.execute("SELECT action,count(*) FROM audit WHERE action LIKE 'media_%' GROUP BY action"))})
    expected=[r for r in proof['checks'] if 'id' in r]
    need(len(actual) == len(expected)+(1 if profile=='image_overlap' else 0), 'unexpected duplicate media row')
    for item in expected:
        row=actual[item['id']]
        need(row['revision']==item['revision'] and row['state']=='ready' and row['visibility']=='private' and row['confirmed_at'] is not None
             and row['previewBytes']>0 and row['metadataBytes']>0, 'SQLite does not match HTTP receipt')
    need(sum(r['audit'].get('media_import_confirm',0) for r in records)==len(actual), 'confirmation count differs')
    return records


def measured_app():
    """Actual Gunicorn factory; no business handlers replaced or wrapped."""
    from app import create_app
    app=create_app(); contract=json.loads(Path('/input/input.json').read_text())
    save('/proof/gunicorn-worker.json', {'pid':os.getpid(),'testing':app.testing,'loaded':runtime_proof(contract)})
    return app


def app_inside(profile):
    sys.path.insert(0,'/runtime')
    from app import create_app
    app=create_app(); engine=app.extensions['household_media']; c=app.test_client()
    need(not app.testing and app.config['SESSION_COOKIE_SECURE'],'real secure app required')
    need(c.post('/api/login',base_url=PUBLIC,json={'username':'member1','password':PASSWORD}).status_code==200,'seed login failed')
    headers={'Origin':PUBLIC,'X-CSRF-Token':c.get('/api/me',base_url=PUBLIC).json['csrf']}
    video_id=None
    if profile=='image_overlap':
        # Fixture-only seeding: actual local photo API creates an authorized row,
        # then the encrypted video cache and its metadata are seeded before serve.
        raw=Path('/input/fixtures/poster.jpg').read_bytes(); digest=hashlib.sha256(raw).hexdigest()
        start=c.post('/api/media/local-imports',base_url=PUBLIC,headers=headers,json={'requestId':secrets.token_hex(16),'consentVersion':'media-v1','allowTemporaryProcessing':True,
            'files':[{'clientFileId':secrets.token_hex(16),'filename':'fixture-poster.jpg','contentType':'image/jpeg','bytes':len(raw),'sha256':digest}]})
        need(start.status_code==201,'seed create failed'); d=start.json; uid=d['import']['id']; slot=d['upload']['files'][0]['slotId']
        put=c.put(f'/api/media/local-imports/{uid}/files/{slot}',base_url=PUBLIC,headers={**headers,'X-Import-Revision':str(d['import']['revision'])},content_type='image/jpeg',data=raw)
        need(put.status_code==200,'seed upload failed')
        finish=c.post(f'/api/media/local-imports/{uid}/finish',base_url=PUBLIC,headers=headers,json={'revision':put.json['import']['revision'],'requestId':secrets.token_hex(16)})
        d=finish.json; video_id=d['items'][0]['id']
        confirm=c.post(f'/api/media/imports/{uid}/confirm',base_url=PUBLIC,headers=headers,json={'revision':d['import']['revision'],'confirmRequestId':secrets.token_hex(16),'consentVersion':'media-v1','persistSelected':True,'itemIds':[video_id]})
        need(confirm.status_code==200,'seed confirmation failed')
        payload=Path('/input/fixtures/display.mp4').read_bytes(); cipher=engine.cipher.seal_bytes('media-video',payload); del payload
        with engine.transaction(True) as con:
            row=con.execute('SELECT * FROM media_items WHERE id=?',(video_id,)).fetchone(); meta=engine._metadata(row); key=secrets.token_hex(12)
            meta.update(mediaType='video',videoKey=key,videoSha256=VIDEO_SHA,videoBytes=64*MIB,durationMs=12010,hasAudio=True,width=160,height=90)
            con.execute('UPDATE media_items SET metadata_cipher=? WHERE id=?',(engine._seal('media-metadata',row,meta),video_id))
            con.execute('INSERT INTO media_video_cache VALUES(?,?,?,?)',(video_id,key,cipher,time.time()))
        del cipher,raw
    contract=json.loads(Path('/input/input.json').read_text())
    save('/proof/ready.json',{'sourceHead':contract['sourceHead'],'loaded':runtime_proof(contract),'videoId':video_id,'testing':app.testing,
                             'fixtureNote':'Seeded size-only encrypted video; no claim of actual local video import or codec validation.'})
    # Fresh interpreter/worker; no test client or seeded large buffers survive.
    os.chdir('/runtime')
    os.execvp('gunicorn',['gunicorn','--pythonpath','/input/tools,/runtime','--bind','0.0.0.0:8000','--workers','1','--threads','4','--timeout','45','--access-logfile','-','--access-logformat','%(m)s %(U)s %(s)s','probe:measured_app()'])


class HTTP:
    def __init__(self,tls=False,host='probe.invalid'):
        self.tls,self.host,self.cookies,self.csrf=tls,host,{},None; self.records=[]
    def connect(self):
        import http.client,ssl,socket
        if self.tls:
            c=http.client.HTTPConnection('web',8443,timeout=45); c.connect()
            context=ssl.create_default_context(cafile='/input/tls/cert.pem')
            c.sock=context.wrap_socket(c.sock,server_hostname=self.host)
        else: c=http.client.HTTPConnection('app',8000,timeout=45)
        if not self.tls:c.connect()
        c.sock.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,64*1024); return c
    def request(self,method,path,body=None,*,file=None,expected=200,extra=None,hold=False):
        from http.cookies import SimpleCookie
        c=self.connect(); headers={'Host':self.host,'Origin':'https://'+self.host,'X-Forwarded-Proto':'https','X-Forwarded-Host':self.host}
        if self.cookies: headers['Cookie']='; '.join(k+'='+v for k,v in self.cookies.items())
        if self.csrf: headers['X-CSRF-Token']=self.csrf
        data=None
        if body is not None: data=json.dumps(body).encode(); headers['Content-Type']='application/json'
        if file: headers['Content-Length']=str(Path(file).stat().st_size)
        elif data is not None: headers['Content-Length']=str(len(data))
        headers.update(extra or {})
        began=time.time(); c.putrequest(method,path,skip_host=True,skip_accept_encoding=True)
        for k,v in headers.items(): c.putheader(k,v)
        c.endheaders()
        if file:
            with Path(file).open('rb') as f:
                for block in iter(lambda:f.read(64*1024),b''): c.send(block)
        elif data is not None: c.send(data)
        response=c.getresponse()
        for k,v in response.getheaders():
            if k.lower()=='set-cookie':
                cookie=SimpleCookie();cookie.load(v)
                for name,item in cookie.items():self.cookies[name]=item.value
        record={'method':method,'path':path,'host':self.host,'tlsSNI':self.host if self.tls else None,
                'status':response.status,'startedAt':began,'headersAt':time.time()};self.records.append(record)
        need(response.status==expected,'HTTP status differs: '+method+' '+path+' '+str(response.status))
        if hold:return c,response,record
        raw=response.read(2*MIB+1);need(len(raw)<=2*MIB,'unexpected large control response');response.close();c.close();record['completedAt']=time.time()
        try:return json.loads(raw)
        except (ValueError,UnicodeDecodeError):return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    def login(self):
        self.request('POST','/api/login',{'username':'member1','password':PASSWORD})
        self.csrf=self.request('GET','/api/me')['csrf']


def upload_one(client,item):
    body={'requestId':secrets.token_hex(16),'consentVersion':'media-v1','allowTemporaryProcessing':True,'files':[{'clientFileId':secrets.token_hex(16),**{k:item[k] for k in ('filename','contentType','bytes','sha256')}}]}
    detail=client.request('POST','/api/media/local-imports',body,expected=201); uid=detail['import']['id'];slot=detail['upload']['files'][0]['slotId']
    detail=client.request('PUT',f'/api/media/local-imports/{uid}/files/{slot}',file=Path('/input/fixtures')/item['filename'],extra={'Content-Type':item['contentType'],'X-Import-Revision':str(detail['import']['revision'])})
    need(detail['upload']['files'][0]['status']=='successful','image processing failed')
    original=detail['items'][0]['id']; revision=detail['items'][0]['item']['revision']
    detail=client.request('POST',f'/api/media/local-imports/{uid}/finish',{'revision':detail['import']['revision'],'requestId':secrets.token_hex(16)})
    confirmed=client.request('POST',f'/api/media/imports/{uid}/confirm',{'revision':detail['import']['revision'],'confirmRequestId':secrets.token_hex(16),'itemIds':[original],'consentVersion':'media-v1','persistSelected':True})
    need(confirmed['itemIds']==[original],'confirmed identity differs')
    current=client.request('GET','/api/media/items/'+original)['item']
    need(current['visibility']=='private' and current['source']=='local-upload' and current['accountId'] is None and current['revision']==revision+1,'private record differs')
    preview=client.request('GET',current['previewUrl']);need(preview['bytes']>0,'empty preview')
    return {'batchId':uid,'id':original,'revision':current['revision'],'input':item,'preview':preview}


def client_inside(profile):
    c=HTTP(tls=profile=='nginx_raw');proof={'passed':False,'profile':profile,'checks':[]};failure=None
    try:
        # Startup readiness only; never retry a business write or unknown result.
        deadline=time.monotonic()+30
        while True:
            try:c.request('GET','/healthz');break
            except (ConnectionError,OSError):need(time.monotonic()<deadline,'health unavailable');time.sleep(.2)
        c.login();contract=json.loads(Path('/input/input.json').read_text());images=contract['photoFixtures']
        if profile=='image_overlap':
            listing=c.request('GET','/api/media/items')['items'];need(len(listing)==1,'video seed count differs');video=listing[0]['id'];url=f'/api/media/items/{video}/video'
            conn,response,start=c.request('GET',url,hold=True);need(int(response.getheader('Content-Length'))==64*MIB,'video length differs')
            try:
                need(c.request('GET',url,expected=503)['code']=='video_busy','video not held before images; inconclusive')
                opened=time.time()
                for item in images[:3]:
                    row=upload_one(c,item);need(c.request('GET',url,expected=503)['code']=='video_busy','video closed during image processing; inconclusive');proof['checks'].append(row)
                overlap_end=time.time();h=hashlib.sha256();length=0
                import socket
                if conn.sock: conn.sock.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,MIB)
                while True:
                    block=response.read(64*1024)
                    if not block:break
                    h.update(block);length+=len(block)
                need(length==64*MIB and h.hexdigest()==VIDEO_SHA,'video truncated or changed')
                proof['overlap']={'videoHeadersAt':start['headersAt'],'busyBeforeAt':opened,'busyAfterEachImage':True,'lastBusyAt':overlap_end,'drainedAt':time.time(),'bytes':length,'sha256':h.hexdigest()}
            finally:response.close();conn.close()
            # Drain a second real response: proves the WSGI close released the slot.
            conn,response,_=c.request('GET',url,hold=True)
            try:
                if conn.sock: conn.sock.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,MIB)
                length=0
                while block:=response.read(64*1024):length+=len(block)
                need(length==64*MIB,'post-close response incomplete')
            finally:response.close();conn.close()
        else:
            proof['checks'].append(upload_one(c,images[-1]))
            invitation=c.request('POST','/api/spaces/invitations',{},expected=201)['invitation']
            other=HTTP(tls=True,host='probe-default.invalid')
            space=other.request('POST','/api/spaces/redeem',{'invitation':invitation,'name':'Synthetic second family','slug':'second-probe','MEMBER1_PASSWORD':PASSWORD,'MEMBER2_PASSWORD':PASSWORD},expected=201)
            other.request('GET',space['entry'],expected=303);need('household_space' in other.cookies,'signed route cookie missing');other.login()
            row=upload_one(other,images[-2]);proof['checks'].append(row)
            c.request('GET','/api/media/items/'+row['id'],expected=404)
            other.request('GET','/api/media/items/'+proof['checks'][0]['id'],expected=404)
            # Declared too-large bytes are rejected before uploading. A raw request
            # with >8MiB Content-Length receives Nginx 413 without sending the body.
            need(len(other.cookies['household_space'])>20,'routing cookie not signed')
            path='/api/media/local-imports/'+'a'*24+'/files/'+'b'*24
            c.request('PUT',path,expected=413,extra={'Content-Type':'image/jpeg','Content-Length':str(8*MIB+1)})
            c.request('PUT','/api/items/tasks/'+'a'*24,file=Path('/input/fixtures/small.jpg'),expected=415,extra={'Content-Type':'image/jpeg'})
            c.request('PUT',path,file=Path('/input/fixtures/small.jpg'),expected=403,extra={'Content-Type':'image/jpeg','Origin':'https://elsewhere.invalid'})
            c.request('PUT',path,file=Path('/input/fixtures/small.jpg'),expected=403,extra={'Content-Type':'image/jpeg','X-CSRF-Token':'wrong'})
            proof['checks'].append({'twoSignedHouseholds':True,'sameRawRoute':True,'crossHouseholdIDsDenied':True,'exact8MiBAccepted':True,'oversize413':True,'otherRaw415':True,'csrfAndOrigin403':True})
            proof['secondHouseholdHTTP']=other.records
        proof['passed']=True
    except BaseException as error:failure=type(error).__name__+': '+str(error)
    finally:
        proof.update(failure=failure,http=c.records,completedAt=time.time());save('/proof/result.json',proof)
        save('/proof/finished.json',{'resultSha256':sha('/proof/result.json'),'passed':proof['passed']})
    need(proof['passed'],'HTTP profile failed; no retry')


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('prepare');a.add_argument('--source',type=Path,required=True);a.add_argument('--head',required=True);a.add_argument('--output',type=Path,required=True);a.add_argument('--video-fixture',type=Path,required=True)
    a=sub.add_parser('run');a.add_argument('--input',type=Path,required=True);a.add_argument('--expected-input-sha256',required=True);a.add_argument('--output',type=Path,required=True);a.add_argument('--profile',choices=PROFILES,required=True)
    a=sub.add_parser('inside');a.add_argument('--role',choices=('app','client'),required=True);a.add_argument('--profile',choices=PROFILES,required=True)
    a=p.parse_args()
    if a.command=='prepare':
        prepare(a.source,a.head,a.output,a.video_fixture)
        print(json.dumps({'input':str(a.output/'input.json'),'sha256':sha(a.output/'input.json')}))
    elif a.command=='run':run(a.input,a.output,a.profile,a.expected_input_sha256)
    else:
        need(sys.platform=='linux' and os.geteuid()==10001 and sys.dont_write_bytecode and not sys.flags.optimize,
             'inside execution requires the isolated nonroot Linux container')
        if a.role=='app':app_inside(a.profile)
        else:client_inside(a.profile)


if __name__=='__main__':main()
