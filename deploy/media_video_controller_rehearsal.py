"""Prepare/run a synthetic, isolated five-service controller rehearsal.

The admitted production plan is a separate proof. This explicit adapter changes
fixture identities, resource limits and timer/admission, never Docker results,
the controller lifecycle methods, the migration or the documented restore.
"""
import argparse
import copy
from contextlib import closing
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy import media_video_release_controller as controller
from deploy import prepare_media_video_activation as activation
from deploy import media_video_service_lifecycle as lifecycle
from deploy import media_video_release_package as package
from deploy import build_media_video_release as build
from deploy import membership_release_build as common
from deploy import membership_release_package as policy
from deploy import steady_linux_rehearsal as seed
from deploy import rehearse_restore as restore
from deploy.git_blobs import read_git_blobs

need, sha, encoded = controller.need, controller.sha, controller.encoded
BASE = 'd0c8362d80215e95bd044c325006b3ec5c160d0a'
SELF = 'deploy/media_video_controller_rehearsal.py'
ADDITIONS = {SELF, 'tests/test_media_video_controller_rehearsal.py',
             'tests/test_media_video_restore_fixture.py', 'docs/MEDIA-VIDEO-CONTROLLER-REHEARSAL.md'}
LIMITS = {'app': 192, 'media': 192, 'sync': 128, 'web': 64, 'decoder': 384}
BUDGET = {'preflightMiB': 1088, 'samples': 3, 'intervalSeconds': 1,
          'abortBelowMiB': 256, 'monitorIntervalSeconds': .25, 'maxLagSeconds': 1}
LAB = Path('/tmp/family-dashboard-controller-rehearsal')
IMAGES = {**activation.IMAGES, 'parent': lifecycle.PARENT_IMAGE, 'web': lifecycle.WEB_IMAGE}
LABEL = 'family-dashboard.synthetic-controller-rehearsal'
METHODS = ('stage', 'activate', 'data_call', 'helper_state', 'stop_data_helper', 'verify_rollback')


def save(path, value, mode=0o600):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    controller.put(path, value)
    path.chmod(mode)


def safe(path, *, exists=False):
    path = Path(path).absolute()
    need(not any(p.is_symlink() for p in (path, *path.parents)), 'linked_rehearsal_path')
    need(not any(c in str(path) for c in (',', '\n', '\r')), 'unsafe_mount_path')
    if exists: controller.regular(path, directory=True)
    return path


def tree(path):
    return common.tree_hashes(path)


def prepare(repo, head, package_dir, package_sha256, build_dir, build_sha256, output_dir):
    repo = safe(repo, exists=True)
    git_tree = policy.identity(repo, head)
    names = policy.tracked_files(repo, head)
    before = read_git_blobs(repo, BASE, sorted(policy.tracked_files(repo, BASE)))
    after = read_git_blobs(repo, head, sorted(names))
    changed = {n for n in set(before) | set(after) if before.get(n) != after.get(n)}
    need(changed <= ADDITIONS and set(after)-set(before) == ADDITIONS, 'rehearsal_scope_changed')
    need(all(policy.plain(repo/n) == raw for n, raw in after.items()), 'working_source_changed')
    verified = package.verify_package(package_dir, package_sha256)
    built = build.verify_build(build_dir, build_sha256, package_dir, package_sha256)
    need(verified['metadata']['sourceHead'] == activation.APP_SOURCE and built['images'] == activation.IMAGES,
         'immutable_application_differs')
    target = safe(output_dir)
    for path in (repo, safe(package_dir, exists=True), safe(build_dir, exists=True)):
        need(not target.is_relative_to(path) and not path.is_relative_to(target), 'input_output_overlap')
    need(not target.exists(), 'exclusive_output_required'); target.mkdir(mode=0o755, parents=True)
    operators = {n: raw for n, raw in after.items() if n.endswith('.py') and (n.startswith('deploy/') or '/' not in n)}
    parent = read_git_blobs(repo, activation.PARENT_SOURCE, ['app.py', 'requirements.txt', 'compose.yaml'])
    for prefix, values in (('operator', operators), ('source', verified['blobs']), ('parent', parent)):
        for name, raw in values.items(): save(target/prefix/name, raw, 0o644)
    # Retain complete checked original build/package inputs, not manufactured PASS receipts.
    for prefix, origin in (('package', Path(package_dir)), ('build', Path(build_dir))):
        for name in tree(origin): save(target/prefix/name, controller.regular(origin/name).read_bytes(), 0o644)
    restore_program, _ = restore.documented_programs(repo)
    save(target/'restore.py', restore_program.encode(), 0o644)
    seed_program = seed.SEED_PROGRAM.replace('len(tables)==61', 'len(tables)==71').replace("'householdTables':61", "'householdTables':71")
    need('len(tables)==71' in seed_program and "'householdTables':71" in seed_program, 'seed_anchor_changed')
    seed_program = "from pathlib import Path\nroot=Path('/data');proof=Path('/proof');runtime=Path('/app')\n" + seed_program
    seed_program += "\n(root/'membership-release-attempt.json').write_bytes("+repr(seed.SYNTHETIC_MARKER)+")\n"
    seed_program += "(root/'membership-release-attempt.json').chmod(0o600)\n"
    save(target/'seed.py', seed_program.encode(), 0o644)
    for folder in target.rglob('*'):
        if folder.is_dir(): folder.chmod(0o755)
    manifest = {'kind': 'synthetic-controller-rehearsal-v1', 'head': head, 'tree': git_tree, 'base': BASE,
                'packageSha256': package_sha256, 'buildSha256': build_sha256, 'images': IMAGES,
                'limitsMiB': LIMITS, 'budget': BUDGET, 'sourceHead': activation.APP_SOURCE,
                'parentSource': activation.PARENT_SOURCE, 'files': tree(target), 'productionOperations': False}
    save(target/'input.json', manifest, 0o644)
    return {'prepared': True, 'inputSha256': sha((target/'input.json').read_bytes()),
            'files': len(manifest['files']), 'dockerExecuted': False}


def verify(bundle, input_sha256):
    bundle = safe(bundle, exists=True)
    meta = controller.read(bundle/'input.json', input_sha256)
    need(meta['kind'] == 'synthetic-controller-rehearsal-v1' and meta['base'] == BASE and
         meta['images'] == IMAGES and meta['limitsMiB'] == LIMITS and meta['budget'] == BUDGET and
         meta['productionOperations'] is False, 'rehearsal_contract_changed')
    need(tree(bundle) == {**meta['files'], 'input.json': input_sha256}, 'rehearsal_bytes_changed')
    executing = Path(__file__).resolve().parents[1]
    for name, digest in meta['files'].items():
        if name.startswith('operator/'):
            need(sha(controller.regular(executing/name.removeprefix('operator/')).read_bytes()) == digest,
                 'executing_operator_differs')
    verified = package.verify_package(bundle/'package', meta['packageSha256'])
    built = build.verify_build(bundle/'build', meta['buildSha256'], bundle/'package', meta['packageSha256'])
    need(built['images'] == activation.IMAGES and verified['metadata']['sourceHead'] == activation.APP_SOURCE,
         'verified_images_differ')
    return bundle, meta, verified, built


def composition(project, candidate, port):
    need(re.fullmatch('fd-vcr-[a-f0-9]{16}-(success|failure)', project), 'isolated_project_required')
    need(type(port) is int and 1024 <= port <= 65535, 'loopback_port_required')
    image = IMAGES['app' if candidate else 'parent']
    app = {'image': image, 'restart': 'no', 'env_file': '.env', 'environment': {'DATA_DIR': '/data'},
           'volumes': ['household-data:/data'], 'read_only': True, 'tmpfs': ['/tmp'],
           'security_opt': ['no-new-privileges:true'], 'mem_limit': '192m', 'memswap_limit': '192m',
           'cpus': 1, 'pids_limit': 128, 'labels': {LABEL: project},
           'healthcheck': {'test': ['CMD', 'python', '-c', "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz')"],
                           'interval': '2s', 'timeout': '2s', 'retries': 25}}
    sync = copy.deepcopy(app); sync.update(command=['python', '-B', 'sync_worker.py'], mem_limit='128m', memswap_limit='128m')
    sync.pop('healthcheck')
    media = copy.deepcopy(sync); media.update(command=['python', '-B', 'media_import_worker.py'], mem_limit='192m', memswap_limit='192m')
    values = {'app': app, 'sync': sync, 'media': media,
              'web': {'image': IMAGES['web'], 'restart': 'no', 'ports': [f'127.0.0.1:{port}:80'],
                      'volumes': ['./deploy/nginx.conf:/etc/nginx/conf.d/default.conf:ro'], 'mem_limit': '64m',
                      'memswap_limit': '64m', 'cpus': 1, 'pids_limit': 128,
                      'security_opt': ['no-new-privileges:true'], 'labels': {LABEL: project}}}
    volumes = {'household-data': {'external': True, 'name': project+'_household-data'}}
    if candidate:
        media['environment']['MEDIA_VIDEO_SOCKET'] = lifecycle.SOCKET
        media['volumes'].append('decoder-socket:/decoder-private')
        values['decoder'] = {'image': IMAGES['decoder'], 'restart': 'no', 'user': '10001:10001',
            'network_mode': 'none', 'read_only': True, 'volumes': ['decoder-socket:/decoder-private'],
            'tmpfs': ['/decode-temp:rw,noexec,nosuid,nodev,size=384m,uid=10001,gid=10001,mode=0700'],
            'cap_drop': ['ALL'], 'security_opt': ['no-new-privileges:true'], 'mem_limit': '384m',
            'memswap_limit': '384m', 'cpus': 1, 'pids_limit': 128, 'labels': {LABEL: project},
            'ulimits': {'nofile': {'soft': 128, 'hard': 128}},
            'healthcheck': {'test': ['CMD', 'python', '-B', '-c', "import os,stat;s=os.stat('/decoder-private/video.sock',follow_symlinks=False);assert stat.S_ISSOCK(s.st_mode) and s.st_uid==10001 and stat.S_IMODE(s.st_mode)==0o600"],
                            'interval': '2s', 'timeout': '2s', 'retries': 30}}
        volumes['decoder-socket'] = {}
    return {'name': project, 'services': values, 'volumes': volumes,
            'networks': {'default': {'internal': True, 'labels': {LABEL: project}}}}


def available_kib():
    fields = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
    return int(fields['MemAvailable'].split()[0])


def preflight(reader=available_kib, sleeper=time.sleep):
    samples = []
    for i in range(BUDGET['samples']):
        try:
            if i: sleeper(BUDGET['intervalSeconds'])
            samples.append({'at': time.time(), 'availableKiB': reader()})
        except BaseException as error:
            return {'policy': BUDGET, 'samples': samples, 'passed': False, 'failedSample': i+1,
                    'failure': type(error).__name__+':'+str(error)}
    return {'policy': BUDGET, 'samples': samples,
            'passed': all(s['availableKiB'] >= BUDGET['preflightMiB']*1024 for s in samples)}


class Monitor:
    def __init__(self):
        self.stop = threading.Event(); self.failed = None; self.last = 0; self.minimum = None; self.count = 0
        self.thread = None; self.thread_started = False
    def sample(self):
        while not self.stop.is_set():
            try:
                value = available_kib(); self.last = time.monotonic(); self.count += 1
                self.minimum = value if self.minimum is None else min(value, self.minimum)
                if value < BUDGET['abortBelowMiB']*1024: self.failed = 'host_memory_below_floor'
            except Exception: self.failed = 'host_memory_read_failed'
            self.stop.wait(BUDGET['monitorIntervalSeconds'])
    def start(self):
        self.thread = threading.Thread(target=self.sample, daemon=True); self.thread.start()
        self.thread_started = True
        until = time.monotonic()+1
        while not self.last and time.monotonic()<until: time.sleep(.01)
        self.check()
    def check(self):
        if time.monotonic()-self.last > BUDGET['maxLagSeconds']: self.failed = 'host_memory_monitor_stalled'
        need(self.failed is None, self.failed or 'host_memory_monitor_failed')
    def finish(self):
        self.stop.set()
        if self.thread_started: self.thread.join(2)
        return {'policy': BUDGET, 'failure': self.failed, 'minimumAvailableKiB': self.minimum,
                'sampleCount': self.count, 'threadStarted': self.thread_started,
                'threadStopped': not self.thread_started or not self.thread.is_alive()}


def web_health_binding(project, web, network):
    """Bind only the running fixture Nginx endpoint on its internal bridge."""
    name = project+'_default'; cid = web.get('Id', '')
    need(re.fullmatch('[a-f0-9]{64}', cid) and web.get('Name') == '/'+project+'-web-1'
         and web.get('Image') == IMAGES['web'], 'health_web_identity_changed')
    labels = web.get('Config', {}).get('Labels') or {}
    need(labels.get(LABEL) == project and labels.get('com.docker.compose.project') == project
         and labels.get('com.docker.compose.service') == 'web', 'health_web_labels_changed')
    state = web.get('State', {})
    need(state.get('Running') is True and type(state.get('Pid')) is int and state['Pid'] > 0
         and not state.get('OOMKilled') and web.get('RestartCount') == 0, 'health_web_not_running')
    attached = web.get('NetworkSettings', {}).get('Networks') or {}
    need(set(attached) == {name} and web.get('HostConfig', {}).get('NetworkMode') == name,
         'health_web_network_changed')
    labels = network.get('Labels') or {}; nid = network.get('Id', '')
    need(re.fullmatch('[a-f0-9]{64}', nid) and network.get('Name') == name
         and network.get('Driver') == 'bridge' and network.get('Scope') == 'local'
         and network.get('Internal') is True and labels.get('com.docker.compose.project') == project
         and labels.get('com.docker.compose.network') == 'default', 'health_network_not_private_fixture')
    endpoint = attached[name]; listed = (network.get('Containers') or {}).get(cid, {})
    need(endpoint.get('NetworkID') == nid and listed.get('Name') == project+'-web-1'
         and re.fullmatch('[a-f0-9]{64}', endpoint.get('EndpointID', ''))
         and listed.get('EndpointID') == endpoint['EndpointID'], 'health_endpoint_identity_changed')
    try:
        address = ipaddress.IPv4Address(endpoint['IPAddress'])
        interface = ipaddress.IPv4Interface(listed['IPv4Address'])
        subnets = [ipaddress.IPv4Network(v['Subnet']) for v in network['IPAM']['Config'] if ':' not in v.get('Subnet', '')]
    except (KeyError, TypeError, ValueError): raise controller.ReleaseError('health_endpoint_address_invalid')
    need(address.is_private and not any((address.is_loopback, address.is_link_local, address.is_multicast, address.is_unspecified))
         and interface.ip == address and interface.network.prefixlen == endpoint.get('IPPrefixLen')
         and any(address in subnet and interface.network == subnet for subnet in subnets), 'health_endpoint_address_unowned')
    return {'containerId': cid, 'pid': state['Pid'], 'networkId': nid, 'endpointId': endpoint['EndpointID'],
            'networkName': name, 'actualUrl': 'http://'+str(address)+'/healthz'}


class Transport:
    """Actual Docker transport, with fixture-only selectors and retained handles."""
    def __init__(self, root, bundle, project, origin, monitor, scenario):
        self.root, self.bundle, self.project, self.origin = root, bundle, project, origin
        self.monitor, self.scenario = monitor, scenario
        self.output = root/'commands'; self.output.mkdir()
        self.records, self.owned, self.intents = [], {}, {}
        self.timer, self.cleanup, self.unknown = True, False, None
        self.discovery_admitted = False
        self.data_path = None; self.injected = None

    def execute(self, argv, timeout=240):
        if not self.cleanup: self.monitor.check()
        index = len(self.records); prefix = self.output/('%04d' % index)
        record = {'argv': argv, 'startedAt': time.time()}; self.records.append(record)
        env = {'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
               'HOME': str(self.root), 'DOCKER_CONFIG': str(self.root/'empty-docker-config'), 'LANG': 'C.UTF-8'}
        with prefix.with_suffix('.stdout').open('xb') as out, prefix.with_suffix('.stderr').open('xb') as err:
            proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=err, env=env)
            record['pid'] = proc.pid; save(prefix.with_suffix('.started.json'), record)
            deadline = time.monotonic()+timeout
            try:
                while proc.poll() is None:
                    if not self.cleanup: self.monitor.check()
                    need(time.monotonic()<deadline, 'fixture_command_timeout')
                    time.sleep(.05)
            except BaseException:
                proc.terminate()
                try: proc.wait(3)
                except subprocess.TimeoutExpired: proc.kill(); proc.wait()
                raise
            finally:
                record.update(exitCode=proc.returncode, completedAt=time.time())
                save(prefix.with_suffix('.json'), record)
        raw = prefix.with_suffix('.stdout').read_bytes()
        need(proc.returncode == 0, 'fixture_command_failed_'+str(index))
        return raw

    def raw(self, *args, timeout=240):
        return self.execute([*lifecycle.DOCKER, *args], timeout)

    def remember(self, identifier):
        value = json.loads(self.raw('inspect', identifier))[0]
        labels = value.get('Config', {}).get('Labels') or {}
        need(labels.get(LABEL) == self.project and value['Image'] in IMAGES.values(), 'unowned_container')
        name = value['Name'].lstrip('/')
        need(name.startswith(self.project+'-') or name in self.intents, 'unowned_container_name')
        self.owned[value['Id']] = {'name': name, 'image': value['Image'], 'state': value['State']}
        save(self.root/('owned-%s-%04d.json' % (value['Id'], len(self.records))), self.owned[value['Id']])
        return value

    def discover(self):
        need(self.discovery_admitted, 'fixture_discovery_not_admitted')
        raw = self.raw('ps', '--all', '--quiet', '--no-trunc', '--filter', 'label='+LABEL+'='+self.project)
        for cid in raw.decode().splitlines(): self.remember(cid)

    def fresh_project(self):
        for label in ('com.docker.compose.project', LABEL):
            need(not self.raw('ps','--all','--quiet','--filter','label='+label+'='+self.project).strip(),
                 'fixture_project_exists')

    def validate(self, args):
        need(bool(args), 'empty_docker_command')
        action = args[0]
        if action == 'inspect':
            need(len(args)==2 and (args[1] in IMAGES.values() or args[1] in self.owned or
                 args[1] in [self.project+'-'+n+'-1' for n in lifecycle.NEW_SERVICES]), 'foreign_inspect')
        elif action == 'ps':
            query = args[args.index('--filter')+1]
            need(query in ('volume='+self.project+'_household-data', 'volume='+self.project+'_decoder-socket',
                          'label=com.docker.compose.project='+self.project), 'foreign_ps_filter')
        elif action == 'volume':
            need(args[1:] in (['ls', '--quiet', '--filter', 'name=^'+self.project+'_decoder-socket$'],
                             ['inspect', self.project+'_decoder-socket']), 'foreign_volume_operation')
        elif action == 'network':
            need(args[1:] == ['inspect', self.project+'_default'], 'foreign_network_operation')
        elif action == 'compose':
            need(args[1:7] == ['--project-name', self.project, '--project-directory', str(self.root/'installed'),
                              '--file', str(self.root/'installed/compose.yaml')], 'foreign_compose_project')
            need(args[7] in ('config', 'up', 'stop'), 'unexpected_compose_mutation')
        elif action in ('start', 'stop', 'exec'):
            cid = args[1] if action == 'exec' else args[-1]
            need(cid in self.owned, 'unowned_mutation')
            self.remember(cid)
        elif action == 'tag':
            need(args[1] in IMAGES.values() and args[2].startswith(self.project+'-'), 'foreign_image_tag')
        elif action == 'create':
            need('--rm' not in args and '--privileged' not in args and
                 args[args.index('--network')+1]=='none' and '--read-only' in args and
                 args[args.index('--user')+1]=='10001:10001', 'helper_isolation_changed')
            name = args[args.index('--name')+1]
            need(re.fullmatch('family-dashboard-video-data-[a-f0-9]{24}', name), 'helper_name_changed')
            for index, value in enumerate(args):
                if value == '--env-file':
                    need(safe(args[index+1]).is_relative_to(self.root), 'foreign_environment')
                if value == '--mount':
                    mount = dict(part.split('=', 1) for part in args[index+1].split(',') if '=' in part)
                    need(mount.get('type') in ('bind', 'volume'), 'foreign_mount_type')
                    if mount['type']=='volume': need(mount['src']==self.project+'_household-data', 'foreign_data_volume')
                    else: need(safe(mount['src']).is_relative_to(self.root), 'foreign_bind_mount')
            self.intents[name] = {'name': name, 'at': time.time()}
        else: need(False, 'unapproved_docker_command')

    def web_health(self, argv, timeout):
        need(argv == ['curl', '--fail', '--silent', '--show-error', '--max-time', '30', self.origin+'/healthz'],
             'external_health_forbidden')
        need(self.discovery_admitted, 'fixture_discovery_not_admitted')
        web = self.remember(self.project+'-web-1')
        networks = json.loads(self([*lifecycle.DOCKER, 'network', 'inspect', self.project+'_default']))
        need(isinstance(networks, list) and len(networks) == 1, 'ambiguous_health_network')
        binding = web_health_binding(self.project, web, networks[0])
        actual = ['curl', '--fail', '--silent', '--show-error', '--noproxy', '*', '--proto', '=http',
                  '--max-time', '30', '--max-redirs', '0', '--max-filesize', '65536',
                  '--write-out', '\n%{http_code}', binding['actualUrl']]
        proof = {**binding, 'requestedUrl': argv[-1], 'requestedArgv': argv, 'actualArgv': actual,
                 'transport': 'host-to-verified-internal-nginx', 'hostPortPublishingVerified': False, 'completed': False}
        target = self.root/('health-transport-%04d.json' % len(self.records)); save(target.with_suffix('.started.json'), proof)
        try:
            raw = self.execute(actual, min(timeout, 35)); body, delimiter, status = raw.rpartition(b'\n')
            need(delimiter and status == b'200' and len(body) <= 65536, 'nginx_health_http_failed')
            need(web_health_binding(self.project, self.remember(binding['containerId']), networks[0]) == binding,
                 'health_endpoint_changed_during_read')
            proof.update(completed=True, httpStatus=200, bodySha256=sha(body)); return body
        except BaseException as error:
            proof['failure'] = type(error).__name__+':'+str(error); raise
        finally: save(target, proof)

    def __call__(self, argv, *, cwd=None, timeout=240):
        if argv[0]=='systemctl':
            need(argv[-1] in (controller.TIMER, 'family-dashboard-backup.service'), 'unexpected_timer')
            if argv[1] in ('start', 'stop'):
                need(argv[-1]==controller.TIMER, 'backup_mutation_forbidden'); self.timer = argv[1]=='start'
            save(self.root/('fixture-timer-%04d.json' % len(list(self.root.glob('fixture-timer-*')))),
                 {'argv': argv, 'active': self.timer, 'systemdExecuted': False})
            return (b'active' if self.timer else b'inactive') if argv[-1]==controller.TIMER else b'inactive'
        if argv[0]=='curl':
            return self.web_health(argv, timeout)
        need(argv[:3]==list(lifecycle.DOCKER), 'explicit_docker_socket_required')
        args = list(argv[3:])
        if args[0]=='tag':
            args[2] = self.project+'-'+args[2].removeprefix('family-dashboard-')
        self.validate(args)
        if args[0]=='create':
            if self.scenario=='failure' and "value=data.migrate(root,proof,**kwargs)" in args[-1]:
                files = sorted((self.data_path/'spaces').glob('*/household.sqlite3'))
                need(len(files)==1 and self.injected is None, 'failure_fixture_group')
                files[0].chmod(0o400); self.injected = files[0]
                save(self.root/'injected-failure.json', {'type': 'readonly_second_household', 'relative': files[0].relative_to(self.data_path).as_posix()})
            args[1:1] = ['--label', LABEL+'='+self.project]
            self.unknown = {'name': args[args.index('--name')+1]}
            save(self.root/('create-intent-%04d.json' % len(self.records)), self.unknown)
        try:
            raw = self.raw(*args, timeout=timeout)
            if args[0]=='create':
                cid = raw.decode().strip(); need(re.fullmatch('[a-f0-9]{64}', cid), 'create_unknown')
                self.remember(cid); self.unknown = None
            elif args[0]=='inspect' and args[1] in self.owned:
                self.owned[args[1]]['state'] = json.loads(raw)[0]['State']
            return raw
        finally:
            if args[:1]==['compose'] and args[7]=='up': self.discover()

    def stop_owned(self):
        self.cleanup = True; failures = []
        try:
            if self.discovery_admitted: self.discover()
        except Exception: failures.append('discovery_unconfirmed')
        for cid, saved in list(self.owned.items()):
            try:
                current = self.remember(cid)
            except Exception:
                try:
                    absent = not self.raw('ps','--all','--quiet','--no-trunc','--filter','id='+cid).strip()
                    need(absent and saved['state'].get('Running') is False, 'owned_identity_unconfirmed')
                    saved['removedAfterVerifiedStop'] = True
                except Exception: failures.append(cid+':inspect_unconfirmed')
                continue  # Only positive absence plus the earlier stopped proof permits removal.
            try:
                if current['State'].get('Running'): self.raw('stop', '--timeout', '5', cid, timeout=20)
                state = self.remember(cid)['State']
                need(state.get('Running') is False and state.get('Pid', 0)==0, 'owned_stop_unconfirmed')
            except Exception: failures.append(cid+':stop_unconfirmed')
        for suffix in ('_household-data','_decoder-socket'):
            try:
                need(not self.raw('ps','--quiet','--filter','volume='+self.project+suffix).strip(), 'remaining_fixture_writer')
            except Exception: failures.append('volume'+suffix+':stop_unconfirmed')
        if self.unknown: failures.append('unknown_create')
        result = {'complete': not failures, 'failures': failures, 'containers': self.owned, 'unknownCreate': self.unknown}
        save(self.root/'owned-cleanup.json', result)
        return result


class FixtureController(controller.Controller):
    """Only fixture admission differs; all transaction/lifecycle methods inherited."""
    def evidence(self):
        bundle, meta, verified, built = verify(self.fixture_bundle, self.fixture_input)
        need(controller.read(self.candidate/'plan.json', self.plan_sha)==self.plan, 'fixture_plan_changed')
        fixture = controller.read(self.candidate/'fixture.json', self.plan['fixtureSha256'])
        self.files = fixture['files']; self.metadata = verified['metadata']; self.build = built
        self.runtime = build.runtime_map('app', self.metadata['contexts']['app'])
        controller.source_hashes(self.source, self.files, exact=True)
        need(sha((self.source/'RELEASE-MANIFEST.json').read_bytes())==fixture['manifestSha256'], 'fixture_manifest_changed')
        for name in verified['blobs']:
            if name not in ('compose.yaml', 'deploy/nginx.conf'):
                need(self.files.get(name)==sha(verified['blobs'][name]), 'nonfixture_source_changed')


def materialize(folder, blobs):
    folder.mkdir(mode=0o755)
    for name, raw in blobs.items(): save(folder/controller.relative(name), raw, 0o644)
    for sub in folder.rglob('*'):
        if sub.is_dir(): sub.chmod(0o755)


def adapt(bundle, meta, verified, scenario_root, project, port):
    """Explicit process-local configuration only; original module files unchanged."""
    root, releases = scenario_root/'installed', scenario_root/'releases'; releases.mkdir(mode=0o700)
    origin = f'http://127.0.0.1:{port}'
    nginx = b'server { listen 80; location / { proxy_pass http://app:8000; proxy_set_header Host $host; } }\n'
    parent = {name: (bundle/'parent'/name).read_bytes() for name in ('app.py', 'requirements.txt')}
    parent.update({'compose.yaml': encoded(composition(project, False, port)), 'deploy/nginx.conf': nginx,
                   'static/experience/synthetic-parent.txt': b'explicit minimal parent source fixture\n'})
    materialize(root, parent)
    old = {'sourceHead': activation.PARENT_SOURCE, 'files': {n: sha(b) for n, b in parent.items()}}
    save(root/'RELEASE-MANIFEST.json', old, 0o644)
    # Application/seed requests keep the valid synthetic HTTPS origin and secure
    # cookies. The separate HTTP loopback transport is only for /healthz.
    env = {**seed.SYNTHETIC_ENV, 'TRUST_PROXY': '0', 'MEDIA_VIDEO_SOCKET': ''}
    save(root/'.env', ''.join(k+'='+v+'\n' for k, v in env.items()).encode())
    candidate = scenario_root/'candidate'; candidate.mkdir(mode=0o700)
    source = dict(verified['blobs']); source.update({'compose.yaml': encoded(composition(project, True, port)), 'deploy/nginx.conf': nginx})
    materialize(candidate/'source', source)
    files = {n: sha(b) for n, b in source.items()}
    manifest = {**verified['manifest'], 'files': files, 'syntheticAdaptation': True}
    save(candidate/'source/RELEASE-MANIFEST.json', manifest, 0o644)
    fixture = {'files': files, 'manifestSha256': sha((candidate/'source/RELEASE-MANIFEST.json').read_bytes())}
    save(candidate/'fixture.json', fixture)
    plan = {'kind': 'media-video-five-service-activation-v1', 'parentSource': activation.PARENT_SOURCE,
            'parentManifest': sha((root/'RELEASE-MANIFEST.json').read_bytes()), 'sourceHead': activation.APP_SOURCE,
            'images': activation.IMAGES, 'schemaBefore': [71, 9], 'schemaAfter': [73, 9],
            'envSha256': sha((root/'.env').read_bytes()), 'inputs': {'build': {'root': str(bundle/'build')}},
            'fixtureSha256': sha((candidate/'fixture.json').read_bytes())}
    save(candidate/'plan.json', plan)
    # These globals live only in the dedicated rehearsal process. No source edits.
    controller.ROOT = root; controller.RELEASES = releases
    controller.VOLUME = lifecycle.VOLUME = project+'_household-data'
    lifecycle.PROJECT = project; lifecycle.SOCKET_VOLUME = project+'_decoder-socket'
    lifecycle.MEMORY = dict(LIMITS)
    lifecycle.BEFORE_COMPOSE = sha(parent['compose.yaml']); lifecycle.AFTER_COMPOSE = sha(source['compose.yaml'])
    activation.PARENT_MANIFEST = plan['parentManifest']; controller.PUBLIC_ORIGIN = origin
    controller.DATA_PREFIX = ORIGINAL_DATA_PREFIX + "\nkwargs['marker_sha256']="+repr(sha(seed.SYNTHETIC_MARKER))+"\n"
    def fixture_decoder(value):
        host = value['HostConfig']
        need(host['Memory']==host['MemorySwap']==LIMITS['decoder']*1024**2, 'fixture_decoder_limit_changed')
        normalized = copy.deepcopy(value)
        normalized['HostConfig']['Memory'] = normalized['HostConfig']['MemorySwap'] = 768*1024**2
        ORIGINAL_DECODER_CONTRACT(normalized)  # Every remaining real decoder property still checked.
    lifecycle.decoder_contract = fixture_decoder
    methods = {name: sha(getattr(controller.Controller, name).__code__.co_code) for name in METHODS}
    save(scenario_root/'adaptations.json', {
        'syntheticOnly': True, 'productionPlanAdmissionExercised': False, 'actualDocker': True,
        'actualMigration': True, 'actualDocumentedRestore': True, 'actualSystemd': False, 'actualTLS': False,
        'project': project, 'volumes': [controller.VOLUME, lifecycle.SOCKET_VOLUME],
        'healthOrigin': origin, 'publicOrigin': env['PUBLIC_ORIGIN'], 'cookieSecure': env['COOKIE_SECURE']=='1',
        'healthTransport': 'host curl to verified internal Nginx bridge endpoint; not host published-port validation',
        'fixtureLimitsMiB': LIMITS, 'productionLimitsMiB': {'app': 384, 'media': 384, 'sync': 192, 'web': 96, 'decoder': 768},
        'helperLimitMiB': 384, 'maximumRunningServiceContainers': 5, 'resourceCapacityClaim': False,
        'parentManifest': {'production': ORIGINAL_PARENT_MANIFEST, 'fixture': plan['parentManifest']},
        'compose': {'parent': lifecycle.BEFORE_COMPOSE, 'candidate': lifecycle.AFTER_COMPOSE},
        'candidateChanges': {name: {'original': sha(verified['blobs'][name]), 'adapted': files[name]}
                             for name in ('compose.yaml', 'deploy/nginx.conf')},
        'minimalParentFiles': old['files'], 'syntheticMarkerSha256': sha(seed.SYNTHETIC_MARKER),
        'imageTagPrefix': project+'-', 'unchangedControllerMethodCodeHashes': methods,
        'decoderValidationAdapter': 'verify real 384MiB fixture limit, map only limit fields to original 768MiB validator',
        'planAdmissionAdapter': 'verify fixed operator, full actual package/build and all fixture hashes; no production review PASS fabrication'})
    return root, releases, candidate, sha((candidate/'plan.json').read_bytes()), origin


ORIGINAL_DATA_PREFIX = controller.DATA_PREFIX
ORIGINAL_DECODER_CONTRACT = lifecycle.decoder_contract
ORIGINAL_PARENT_MANIFEST = activation.PARENT_MANIFEST


def owned_helper(transport, image, program, mounts, env_file):
    """Non-controller fixture setup/restore helper; actual process and explicit CID."""
    name = transport.project+'-fixture-'+os.urandom(6).hex()
    args = ['create', '--name', name, '--label', LABEL+'='+transport.project, '--network', 'none',
            '--read-only', '--user', '10001:10001', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
            '--memory', '384m', '--memory-swap', '384m', '--cpus', '1', '--pids-limit', '128',
            '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=134217728,mode=1777', '--env-file', str(env_file)]
    for value in mounts: args += ['--mount', value]
    args += ['--entrypoint', 'python', image, '-B', '-c', program]
    transport.intents[name] = {'name': name, 'fixture': True}; transport.unknown = {'name': name}
    save(transport.root/('fixture-create-intent-%04d.json' % len(transport.records)), transport.unknown)
    cid = transport.raw(*args).decode().strip(); need(re.fullmatch('[a-f0-9]{64}', cid), 'fixture_create_unknown')
    transport.remember(cid); transport.unknown = None
    try:
        raw = transport.raw('start', '--attach', cid, timeout=360)
        state = transport.remember(cid)['State']
        need(state['Running'] is False and state['ExitCode']==0 and not state['OOMKilled'], 'fixture_helper_failed')
        return raw
    except BaseException:
        # Per-run final cleanup rechecks all known CIDs even if this CLI timed out.
        raise


def create_data_volume(transport):
    name = transport.project+'_household-data'
    for suffix in ('_household-data', '_decoder-socket'):
        existing = transport.raw('volume', 'ls', '--quiet', '--filter', 'name=^'+transport.project+suffix+'$')
        need(not existing.strip(), 'fixture_volume_already_exists')
    transport.raw('volume', 'create', '--label', LABEL+'='+transport.project, name)
    value = json.loads(transport.raw('volume', 'inspect', name))[0]
    need(value['Name']==name and value['Driver']=='local' and not value.get('Options') and
         value.get('Labels', {}).get(LABEL)==transport.project, 'fixture_volume_identity')
    path = safe(value['Mountpoint'], exists=True); need(not list(path.iterdir()), 'fixture_data_not_empty')
    os.chown(path, 10001, 10001); path.chmod(0o700); transport.data_path = path
    transport.discovery_admitted = True  # Only after an empty project and new, owned empty volume.
    save(transport.root/'fixture-volume.json', value)
    return path


def restore_fixture(c, transport, bundle):
    c.stopped(); need(not transport.timer, 'fixture_timer_not_stopped')
    if transport.injected: transport.injected.chmod(0o600)
    # Preserve the full failed/live source before restoring the explicit fixture parent.
    saved_root = transport.root/'source-before-rollback'; c.root.rename(saved_root)
    shutil.copytree(c.release/'source-before', c.root)
    shutil.copyfile(c.release/'env-before', c.root/'.env'); (c.root/'.env').chmod(0o600)
    proof = c.release/'proof'
    # Use the complete documented restore program without replacing its SQLite algorithm.
    code = """from pathlib import Path
import hashlib,json,shutil,sys
proof=Path('/proof');root=Path('/data')
receipt=json.loads((proof/'backup.json').read_bytes())
group=proof/'backup-group';manifest=json.loads((group/'backups'/receipt['manifest']).read_bytes())
assert len(manifest['snapshots'])==3
missing=[]
for name in ['backups/'+receipt['manifest'],*[x['path'] for x in manifest['snapshots']]]:
 src=group/name;target=root/name
 assert src.resolve().is_relative_to(group.resolve()) and target.resolve().is_relative_to(root.resolve())
 assert src.is_file() and not src.is_symlink() and not target.is_symlink()
 if target.exists():
  assert target.is_file() and hashlib.sha256(src.read_bytes()).digest()==hashlib.sha256(target.read_bytes()).digest()
 else: missing.append((src,target))
for src,target in missing:
 target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
 with src.open('rb') as source,target.open('xb') as destination: shutil.copyfileobj(source,destination)
 target.chmod(0o600)
sys.argv=['documented-restore',receipt['manifest'],'platform','default']
exec(compile(Path('/restore.py').read_text(),'<fixed-documented-restore>','exec'),{'__name__':'__main__'})
"""
    mounts = ['type=volume,src='+controller.VOLUME+',dst=/data',
              'type=bind,src='+str(proof)+',dst=/proof,readonly',
              'type=bind,src='+str(bundle/'restore.py')+',dst=/restore.py,readonly']
    owned_helper(transport, IMAGES['app'], code, mounts, c.root/'.env')
    return c.verify_rollback(c.release)


def partial_schema(root):
    """Read only the stopped synthetic group; prove first DB committed before failure."""
    paths = [root/'household.sqlite3', root/'platform.sqlite3', *sorted((root/'spaces').glob('*/household.sqlite3'))]
    need(len(paths)==3, 'partial_group_not_complete')
    counts = {}
    for path in paths:
        need(not any(Path(str(path)+suffix).exists() for suffix in ('-wal','-shm','-journal')), 'partial_group_not_stopped')
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1', uri=True)) as con:
            counts[path.relative_to(root).as_posix()] = con.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone()[0]
    need(counts['household.sqlite3']==73 and counts['platform.sqlite3']==9 and
         counts[paths[2].relative_to(root).as_posix()]==71, 'partial_migration_not_proven')
    return counts


def scenario(bundle, input_sha, meta, verified, output, name, run_id, monitor):
    root = output/name; root.mkdir(mode=0o700)
    project = 'fd-vcr-'+run_id+'-'+name
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    installed, releases, candidate, plan_sha, origin = adapt(bundle, meta, verified, root, project, port)
    transport = Transport(root, bundle, project, origin, monitor, name)
    result = {'passed': False, 'scenario': name, 'syntheticOnly': True, 'productionPlanAdmissionExercised': False}
    try:
        transport.fresh_project()
        data_path = create_data_volume(transport)
        proof = root/'seed-proof'; proof.mkdir(mode=0o700); os.chown(proof,10001,10001)
        mounts = ['type=volume,src='+controller.VOLUME+',dst=/data', 'type=bind,src='+str(proof)+',dst=/proof']
        raw = owned_helper(transport, IMAGES['parent'], (bundle/'seed.py').read_text(), mounts, installed/'.env')
        seeded = json.loads(raw); need(seeded['households']==2 and seeded['databases']==3 and seeded['householdTables']==71, 'wrong_seed')
        transport([*lifecycle.DOCKER, 'compose','--project-name',project,'--project-directory',str(installed),
                   '--file',str(installed/'compose.yaml'),'up','-d','--no-build','--pull','never','--wait',
                   '--wait-timeout','150','app','sync','media','web'], timeout=180)
        c = FixtureController(candidate, plan_sha, runner=transport, root=installed, releases=releases)
        c.fixture_bundle, c.fixture_input = bundle, input_sha
        with controller.release_lock():
            result['stage'] = c.stage()
            try: activated = c.activate()
            except controller.ReleaseError:
                need(name=='failure' and transport.injected is not None, 'unexpected_activation_failure')
                failed = controller.read(candidate/'failure.json')
                need(failed['candidateStop']['complete'] and failed['dataHelperStop']['complete'] and
                     not failed['automaticRestore'] and not transport.timer, 'failure_not_stopped')
                need((c.release/'proof/migration-attempt.json').is_file() and
                     not (c.release/'proof/migration-result.json').exists(), 'expected_real_migration_failure_missing')
                result['activationFailure'] = failed
                c.stopped()
                result['partialMigrationTables'] = partial_schema(data_path)
                save(root/'partial-migration.json', result['partialMigrationTables'])
            else:
                need(name=='success' and activated['completed'] and activated['schema']==[73,9], 'unexpected_activation_success')
                result['activation'] = activated
                transport(['systemctl','stop',controller.TIMER])
                c.lifecycle.drain('candidate', c.lifecycle.capture('candidate')); c.stopped()
            command_count = len(transport.records)
            try: c.stage()
            except controller.ReleaseError as error:
                need(str(error)=='plan_consumed' and len(transport.records)==command_count, 'replay_rejection_changed')
            else: need(False, 'consumed_plan_was_replayed')
            result['consumedPlanRejectedBeforeDocker'] = True
            result['rollback'] = restore_fixture(c, transport, bundle)
            need(result['rollback']['verified'] and result['rollback']['databases']==3, 'full_rollback_not_verified')
            result['passed'] = True
    except BaseException as error:
        result['failure'] = type(error).__name__+':'+str(error)
    finally:
        cleanup = transport.stop_owned(); result['cleanup'] = cleanup
        result['passed'] = bool(result['passed'] and cleanup['complete'])
        result['commands'] = transport.records; result['completedAt'] = time.time()
        save(root/'result.json', result)
    return result


def run(bundle, input_sha256, output_dir):
    need(sys.platform=='linux' and os.geteuid()==0 and sys.dont_write_bytecode and not sys.flags.optimize,
         'linux_root_python_B_required')
    need(not any(k.upper().startswith(('DOCKER_', 'COMPOSE_')) for k in os.environ), 'ambient_docker_selector')
    bundle, meta, verified, _ = verify(bundle, input_sha256)
    output = safe(output_dir)
    need(output.parent==LAB and re.fullmatch('run-[a-f0-9]{16}',output.name) and not output.exists(), 'exclusive_lab_output_required')
    output.mkdir(parents=True,mode=0o700)
    save(output/'started.json', {'pid': os.getpid(), 'at': time.time(), 'inputSha256': input_sha256})
    result = {'passed': False, 'inputSha256': input_sha256, 'productionAccess': False, 'scenarios': {},
              'productionPlanAdmissionExercised': False, 'fixtureLimitsMiB': LIMITS, 'containersCreated': 0}
    admission = preflight(); save(output/'preflight.json', admission)
    if not admission['passed']:
        result['status'] = 'preflight_failed' if admission.get('failure') else 'preflight_blocked'
        if admission.get('failure'): result['failure'] = admission['failure']
        result['completedAt'] = time.time()
        save(output/'result.json', result); return result
    def interrupt(*_): raise controller.ReleaseError('rehearsal_interrupted')
    for sig in (signal.SIGTERM, signal.SIGINT): signal.signal(sig, interrupt)
    monitor = Monitor()
    try:
        monitor.start()
        for name in ('success','failure'):
            result.pop('containersCreated', None)  # From here the per-scenario owned-CID receipts count actual work.
            outcome = scenario(bundle,input_sha256,meta,verified,output,name,output.name[4:],monitor)
            result['scenarios'][name] = sha((output/name/'result.json').read_bytes())
            need(outcome['passed'], 'scenario_failed_'+name)
        verify(bundle, input_sha256)
        result['inputBytesUnchanged'] = True
        result['passed'] = True
    except BaseException as error: result['failure'] = type(error).__name__+':'+str(error)
    finally:
        result['hostMemory'] = monitor.finish()
        result['passed'] = bool(result['passed'] and not result['hostMemory']['failure'] and result['hostMemory']['threadStopped'])
        result['completedAt'] = time.time(); save(output/'result.json', result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='action',required=True)
    fields = {'prepare': ('repo','head','package-dir','package-sha256','build-dir','build-sha256','output-dir'),
              'run': ('bundle','input-sha256','output-dir'), 'verify': ('bundle','input-sha256')}
    for name, options in fields.items():
        command = sub.add_parser(name)
        for option in options: command.add_argument('--'+option,required=True)
    args = vars(parser.parse_args(argv)); action = args.pop('action')
    value = {'verified': bool(verify(**args))} if action=='verify' else globals()[action](**args)
    print(json.dumps(value)); return 1 if value.get('passed') is False else 0


if __name__=='__main__': raise SystemExit(main())
