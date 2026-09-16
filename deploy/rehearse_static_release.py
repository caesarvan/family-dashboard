"""Rehearse a static release in two NEW synthetic households, never production.

Requires already-local immutable parent, child and nginx images plus a real
static-build proof. Fixture READY envelopes drive the real controller; their
synthetic assertions are NOT release evidence. Only the actual controller
record, independent data checks and cleanup form this rehearsal's result.
No restore is performed. Run only after independent review on a Linux host.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import signal
import subprocess
import sys
import uuid

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy import release_core as core

LABEL = 'org.family-dashboard.static-rehearsal'
IMAGE = re.compile(r'sha256:[a-f0-9]{64}\Z')
RUN = re.compile(r'[a-f0-9]{32}\Z')
CONTROLLER = 'deploy/activate_static_release.py'
SELF = 'deploy/rehearse_static_release.py'
FIXTURE = 'tests/restore_rehearsal_fixture.py'


class DockerFailure(RuntimeError):
    def __init__(self, result):
        super().__init__('docker_command_failed')
        self.stdout, self.stderr, self.returncode = result.stdout, result.stderr, result.returncode


def need(value, label):
    if not value:
        raise RuntimeError(label)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()


def plain(path):
    path = Path(path)
    need(path.is_file() and not path.is_symlink() and path.absolute() == path.resolve(strict=True), 'unsafe_file')
    return path.read_bytes()


def relative(name):
    need(isinstance(name, str) and name and ':' not in name and '\\' not in name, 'unsafe_name')
    p = PurePosixPath(name)
    need(not p.is_absolute() and p.as_posix() == name and '..' not in p.parts, 'unsafe_name')
    need(not any(x.startswith('.env') or x in ('.git', '.venv', 'data', 'test-results') for x in p.parts), 'private_source')
    return name


def frozen_source(root, manifest_sha):
    raw = plain(root / 'RELEASE-MANIFEST.json')
    need(sha(raw) == manifest_sha, 'manifest_sha')
    files = json.loads(raw)['files']
    need(isinstance(files, dict) and files, 'manifest_files')
    values = {}
    for name, digest in files.items():
        relative(name)
        need(re.fullmatch(r'[a-f0-9]{64}', digest) is not None, 'file_sha')
        value = plain(root / name)
        need(sha(value) == digest, 'source_changed')
        values[name] = value
    return raw, values


def load_controller(candidate, policy=core.STATIC):
    path = candidate / policy.entry
    spec = importlib.util.spec_from_file_location('synthetic_static_controller', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def compose_config(project, run_id, nginx_image, proof, tests):
    need(RUN.fullmatch(run_id) and project == 'fd-static-' + run_id, 'synthetic_project')
    common = {'image': project + '-app', 'pull_policy': 'never', 'network_mode': 'none',
              'read_only': True, 'restart': 'no', 'user': '10001:10001', 'env_file': '.env',
              'cap_drop': ['ALL'], 'security_opt': ['no-new-privileges:true'],
              'pids_limit': 128, 'mem_limit': '384m', 'tmpfs': ['/tmp:rw,nosuid,noexec,size=64m'],
              'labels': {LABEL: run_id}, 'volumes': ['household-data:/data']}
    app = {**common, 'container_name': project + '-app',
           'command': ['gunicorn', '--bind', '127.0.0.1:8000', '--workers', '1', '--threads', '4', '--timeout', '45', 'app:create_app()'],
           'volumes': [*common['volumes'], str(proof) + ':/proof', str(tests) + ':/rehearsal/tests:ro'],
           'healthcheck': {'test': ['CMD', 'python', '-c', "import urllib.request; o=urllib.request.build_opener(urllib.request.ProxyHandler({})); assert o.open('http://127.0.0.1:8000/healthz',timeout=2).status==200"],
                           'interval': '2s', 'timeout': '3s', 'retries': 40}}
    sync = {**common, 'container_name': project + '-sync', 'command': ['python', 'sync_worker.py']}
    web = {'image': nginx_image, 'pull_policy': 'never', 'container_name': project + '-web',
           'network_mode': 'none', 'read_only': True, 'restart': 'no', 'labels': {LABEL: run_id},
           'entrypoint': ['nginx'], 'command': ['-g', 'daemon off;'],
           'tmpfs': ['/var/cache/nginx', '/var/run', '/tmp'], 'mem_limit': '96m', 'pids_limit': 64,
           'security_opt': ['no-new-privileges:true'],
           'volumes': ['./deploy/nginx.conf:/etc/nginx/conf.d/default.conf:ro']}
    return {'name': project, 'services': {'app': app, 'sync': sync, 'web': web},
            'volumes': {'household-data': {'external': True, 'name': project + '_household-data'}}}


PARENT_FILES = r'''
import base64,hashlib,json,pathlib,sys
root=pathlib.Path('/app'); expected=json.loads(sys.argv[1]); result={}
actual={p.name for p in root.glob('*.py') if p.is_file()}|{'requirements.txt'}
assert actual==set(expected)
assert all(hashlib.sha256((root/n).read_bytes()).hexdigest()==h for n,h in expected.items())
for p in sorted((root/'static').rglob('*')):
    if p.is_dir():assert not p.is_symlink();continue
    assert p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(root)
    raw=p.read_bytes();assert len(raw)<=5000000
    result[p.relative_to(root).as_posix()]=base64.b64encode(raw).decode()
assert sum(len(v) for v in result.values())<40000000
print(json.dumps(result))
'''

# This comparison deliberately does not call restore fixture.verify: a static
# update must retain authentication too, whereas restore invalidates sessions.
DATA_VERIFY = r'''
import json,os,pathlib,sys
sys.path.insert(0,'/rehearsal/tests')
import restore_rehearsal_fixture as F
p=pathlib.Path('/proof/expected.json');expected=json.loads(p.read_bytes())
assert expected['runId']==os.environ['REHEARSAL_RUN_ID']
root=pathlib.Path('/data');houses=F.registry(root)
assert len(houses)==2 and F.snapshot(root/'platform.sqlite3')==expected['registry']
for h in houses:assert F.snapshot(F.database_path(root,h['id']))==expected['databases'][h['id']]
assert sum(len(h['documents']) for h in expected['households'])==8
# Reuse retained cookies; only a local read is requested, never login/provider.
audit=F.Audit('static-files');downloads=0
with F.only_loopback(audit):
 for house in expected['households']:
  for uid,member in house['members'].items():
   c=F.Client('http://127.0.0.1:8000',audit,member['cookies'])
   for item in house['documents']:
    meta=item['metadata']
    if meta['owner']!=uid:continue
    raw=c.request('GET','/api/journey-documents/'+meta['id']+'/file',raw=True)
    assert F.digest(raw)==item['sha256'];downloads+=1
assert downloads==8 and not audit.external
print(json.dumps({'passed':True,'households':2,'householdTables':43,'platformTables':2,'documents':8,
 'allRowsSchemaSequencesAndAuthenticationPreserved':True,'documentDownloads':downloads,
 'externalRequests':0,'restorePerformed':False}))
'''


def fixture_ready(candidate, base_hashes, hashes, parent, image, proof_raw, env_raw, *, policy=core.STATIC):
    """Synthetic controller inputs, explicitly not proof of a passed rehearsal."""
    evidence = candidate / 'evidence'; evidence.mkdir(mode=0o700)
    records = {'build-original.json': proof_raw, 'fixture-input.json': encoded({
        'synthetic': True, 'isAcceptanceEvidence': False,
        'purpose': 'Exercise actual static controller; this declaration proves no tests or deployment.',
        'adaptation': 'Only synthetic deployment config differs outside image runtime; original build bytes retained.'})}
    for name, raw in records.items():
        (evidence / name).write_bytes(raw)
    refs = [{'path': 'evidence/' + name, 'sha256': sha(raw)} for name, raw in records.items()]
    common = {'synthetic': True, 'isAcceptanceEvidence': False, 'verified': True, 'sourceHashes': hashes, 'records': refs}
    manifest_sha = sha(plain(candidate / 'RELEASE-MANIFEST.json'))
    backend = {n: h for n, h in hashes.items() if n == 'requirements.txt' or '/' not in n and n.endswith('.py')}
    static = {n: h for n, h in hashes.items() if n.startswith('static/')}
    # Small synthetic counts satisfy the controller's input contract. They are
    # never returned as successful test counts or promoted to real envelopes.
    review = {**common, 'reviewed': True, **{k: '1' * 40 for k in ('baseCommit', 'mainCommit', 'integrationCommit', 'mainTree', 'integrationTree')}}
    envelopes = {
        'staticBuild': {**common, 'image': image, 'parentImage': parent, 'manifestSha256': manifest_sha,
                        'nonStaticRuntimeHashes': backend, 'staticHashes': static,
                        'parentLayersPreserved': True, 'configurationUnchanged': True, 'pipExecuted': False},
        'backendReuse': {**common, 'coverageMode': 'unchanged-backend-dependencies', 'previousImage': parent,
                         'nonStaticRuntimeHashes': backend, 'singleFullRunPassed': False,
                         'windows': {'tests': 1, 'passed': 1, 'skipped': 0}, 'linux': {'tests': 1, 'passed': 1, 'skipped': 0}},
        'browsers': {**common, 'groups': [{'script': FIXTURE, 'passed': True, 'checks': 1, 'externalRequests': 0}]},
        'releaseSafety': {**common, 'realDocker': True, 'image': image, 'manifestSha256': manifest_sha,
                          'households': 2, 'checks': 1, 'originalTablesPreserved': 43, 'newTables': 0, 'productionWrites': 0, 'allPassed': True},
        'gitReview': review}
    if policy is core.SOURCE:
        changes = core.runtime_changes(base_hashes, hashes)
        python = sorted(x['path'] for x in changes if x['kind'] == 'rootPython')
        build = envelopes.pop('staticBuild'); envelopes.pop('backendReuse')
        base_sha = sha(encoded({'files': base_hashes}))
        build.update(mode=policy.mode, baseManifestSha256=base_sha,
                     parentRuntimeHashes={**core.backend_hashes(base_hashes), **core.static_hashes(base_hashes)},
                     candidateRuntimeHashes={**backend, **static}, approvedRuntimeChanges=changes,
                     parentBackendVerified=True, childBackendVerified=True, staticVerified=True, bytecodeExcluded=True)
        envelopes['sourceBuild'] = build
        # These marked fixture runs only drive the actual controller. No test
        # claim from them is copied into this rehearsal's acceptance report.
        script = 'tests/test_source_release.py'
        xml = b'<testsuite><testcase classname="tests.test_source_release" name="synthetic_driver"/></testsuite>'
        log = b'Synthetic controller driver only; no pytest run.\n'
        for name, raw in [('fixture.xml', xml), ('fixture.log', log)]:
            (evidence / name).write_bytes(raw)
        dependencies = {**backend, script: hashes[script]}
        runs = [{'platform': p, 'scripts': [script], 'coveredChanges': python,
                 'tests': 1, 'passed': 1, 'skipped': 0, 'failures': 0, 'errors': 0, 'exitCode': 0,
                 'dependencyHashesBefore': dependencies, 'dependencyHashesAfter': dependencies,
                 'image': image, 'junit': {'path': 'evidence/fixture.xml', 'sha256': sha(xml)},
                 'log': {'path': 'evidence/fixture.log', 'sha256': sha(log)}} for p in ('windows', 'linux')]
        envelopes['backendValidation'] = {**common, 'coverageMode': 'affected-source-tests',
            'changedPython': python, 'compatibility': dict(core.COMPATIBILITY), 'runs': runs, 'historicalReuse': []}
        review.update(approvedRuntimeChanges=changes, compatibility=dict(core.COMPATIBILITY))
    references = {}
    for name, value in envelopes.items():
        raw = encoded(value); (evidence / (name + '.json')).write_bytes(raw)
        references[name] = {'path': 'evidence/' + name + '.json', 'sha256': sha(raw)}
    base_raw = encoded({'files': base_hashes}); (candidate / 'BASE-MANIFEST.json').write_bytes(base_raw)
    ready = {'version': 1, 'verified': True, 'synthetic': True, 'isAcceptanceEvidence': False,
             'mode': policy.mode, 'image': image, 'previousImage': parent, 'manifestSha256': manifest_sha,
             'sourceHashes': hashes, 'baseHashes': base_hashes, 'baseManifestSha256': sha(base_raw),
             'oldManifestSha256': sha(base_raw), 'environmentSha256': sha(env_raw),
             'changedFiles': sorted(n for n, h in hashes.items() if base_hashes.get(n) != h),
             'schema': {'from': 43, 'to': 43, 'newTables': []}, 'evidence': references, 'gitReview': review}
    if policy is core.SOURCE: ready['approvedRuntimeChanges'] = changes
    raw = encoded(ready); (candidate / 'READY.json').write_bytes(raw)
    return manifest_sha, sha(raw)


class Rehearsal:
    # The original CLI/class are permanently static. SourceRehearsal is a
    # separate reviewed entry class; READY never selects this attribute.
    policy = core.STATIC
    def __init__(self, source, manifest_sha, parent, image, build_proof, proof_sha, nginx_image, output, *, runner=None):
        self.source, self.output, self.proof = Path(source), Path(output), Path(build_proof)
        need(all(isinstance(i, str) and IMAGE.fullmatch(i) for i in (parent, image, nginx_image)) and parent != image, 'immutable_images')
        need(self.source.is_absolute() and self.source.resolve(strict=True) == self.source, 'source_path')
        need(self.output.is_absolute() and self.output.parent.resolve(strict=True) == self.output.parent
             and not self.output.exists() and not self.output.is_symlink(), 'new_output_required')
        need(not self.output.is_relative_to(self.source) and not self.source.is_relative_to(self.output), 'output_source_overlap')
        need(re.fullmatch('[a-f0-9]{64}', manifest_sha) and re.fullmatch('[a-f0-9]{64}', proof_sha), 'input_sha')
        self.manifest_sha, self.proof_sha = manifest_sha, proof_sha
        self.parent, self.image, self.nginx = parent, image, nginx_image
        self.run_id = uuid.uuid4().hex; self.project = 'fd-static-' + self.run_id
        self.volume = self.project + '_household-data'; self.tag = self.project + '-app'
        self.resources = {}; self.runner = runner or self.process
        self.host_environment = dict(os.environ)
        self.root = self.output / 'app'; self.candidate = self.output / ('family-dashboard-candidate-' + self.policy.prefix + '-' + self.run_id)
        self.releases = self.output / 'releases'; self.proof_dir = self.output / 'proof'
        self.created = False; self.counter = 0; self.tag_created = False; self.container_ids = set()
        self.report = {'runId': self.run_id, 'startedAt': datetime.now(timezone.utc).isoformat(),
                       'scope': 'synthetic ' + self.policy.mode + ' deployment, not restore or production', 'passed': False,
                       'parentImage': parent, 'image': image, 'nginxImage': nginx_image,
                       'productionWrites': 0, 'restorePerformed': False, 'checks': [], 'resources': []}

    @staticmethod
    def process(args, *, cwd, input_bytes=None, timeout=180, env=None):
        need(args and args[0] == 'docker', 'docker_only')
        # Never inherit COMPOSE_FILE/PROJECT or a remote Docker context from the host.
        env = {k: v for k, v in (os.environ if env is None else env).items()
               if not k.upper().startswith(('COMPOSE_', 'DOCKER_'))}
        p = subprocess.run(['docker', '--host', 'unix:///var/run/docker.sock', *args[1:]],
                           cwd=cwd, env=env, input=input_bytes, capture_output=True, timeout=timeout)
        if p.returncode != 0:raise DockerFailure(p)
        return p.stdout.decode('utf-8').strip()

    def call(self, args, *, input_bytes=None, timeout=180):
        return self.runner(['docker', *args], cwd=self.output, input_bytes=input_bytes, timeout=timeout, env=dict(self.host_environment))

    def check(self, name, value):
        self.report['checks'].append({'name': name, 'passed': bool(value)})
        need(value, name)

    def list_names(self, kind, name):
        pattern = '^/' + name + '$' if kind == 'container' else '^' + name + '$'
        return self.call([kind, 'ls', *(['-a'] if kind == 'container' else []), '--filter', 'name=' + pattern,
                          '--format', '{{.Names}}' if kind == 'container' else '{{.Name}}']).splitlines()

    def owned(self, kind, name):
        need((kind, name) in self.resources, 'untracked_resource')
        rows = json.loads(self.call([kind, 'inspect', name])); need(len(rows) == 1, 'resource_not_unique')
        value = rows[0]; labels = value.get('Labels') if kind == 'volume' else value.get('Config', {}).get('Labels')
        need(value.get('Name', '').lstrip('/') == name and (labels or {}).get(LABEL) == self.run_id, 'ownership_changed')
        if kind == 'container':
            need(value['Image'] in (self.parent, self.image, self.nginx)
                 and value['HostConfig']['NetworkMode'] == 'none' and not value['HostConfig'].get('PortBindings'), 'container_isolation')
            cid = value.get('Id')
            if isinstance(cid, str) and re.fullmatch('[a-f0-9]{64}', cid):self.container_ids.add(cid)
        return value

    def track_new(self, kind, name):
        need((kind, name) not in self.resources and name not in self.list_names(kind, name), 'resource_already_exists')
        self.resources[(kind, name)] = True
        self.report['resources'].append({'kind': kind, 'name': name})

    def ephemeral(self, image, command, *, mounts=(), user='10001:10001'):
        self.counter += 1; name = self.project + '-helper-' + str(self.counter)
        self.track_new('container', name)
        args = ['container', 'create', '--name', name, '--label', LABEL + '=' + self.run_id,
                '--pull', 'never', '--network', 'none', '--read-only', '--user', user,
                '--memory', '384m', '--pids-limit', '128', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges:true', '--tmpfs', '/tmp:rw,nosuid,noexec,size=64m']
        if user == '0:0':
            need(command == ['python', '-c', "import os;os.chown('/data',10001,10001);os.chmod('/data',0o700)"], 'root_only_initializes_new_volume')
            args += ['--cap-add', 'CHOWN', '--cap-add', 'FOWNER', '--cap-add', 'DAC_OVERRIDE']
        for name_volume in mounts:
            need(name_volume == self.volume, 'foreign_volume'); self.owned('volume', name_volume)
            args += ['--mount', 'type=volume,src=' + name_volume + ',dst=/data']
        self.call([*args, '--entrypoint', command[0], image, *command[1:]])
        self.owned('container', name)
        result = self.call(['start', '-a', name], timeout=180)
        info = self.owned('container', name)
        need(not info['State']['Running'] and info['State']['ExitCode'] == 0, 'helper_failed')
        return result

    def compose_prefix(self):
        return ['docker', 'compose', '--project-name', self.project, '--file', str(self.root / 'compose.yaml'),
                '--env-file', str(self.root / '.env')]

    def controller_runner(self, args, *, cwd, input_bytes=None, timeout=180, env=None):
        """Preserve actual controller commands; enforce synthetic scope/add label."""
        need(Path(cwd) == self.root and args and args[0] == 'docker', 'controller_command_scope')
        need(env is None or env == self.host_environment, 'controller_environment_changed')
        if args[1:2] == ['compose']:
            need(args[:8] == self.compose_prefix() and len(args) > 8 and args[8] in ('config', 'ps', 'stop', 'up', 'exec')
                 and not any(x in args[8:] for x in ('--file', '-f', '--env-file', '--project-name', '-p', '--project-directory')), 'foreign_compose_project')
        if args[1:2] == ['inspect']:
            need(args[-1] in self.container_ids, 'foreign_container_id')
        if args[1:2] == ['stop']:
            need(args[-1] in self.container_ids or ('container', args[-1]) in self.resources, 'foreign_stop')
        if args[1:2] == ['image']:
            need(args[2] == 'inspect' and args[-1] in (self.parent, self.image, self.nginx), 'foreign_image_operation')
        if args[1:2] == ['ps']:
            filters = [args[i + 1] for i, v in enumerate(args) if v == '--filter']
            valid = {'volume=' + self.volume} | {'name=^/' + n + '$' for k, n in self.resources if k == 'container'}
            need(len(filters) == 1 and filters[0] in valid, 'unscoped_container_query')
        if args[1:2] == ['tag']:
            need(args == ['docker', 'tag', self.image, self.tag], 'foreign_tag')
        if args[1:2] == ['run']:
            need('--name' in args and '--rm' in args and '--network' in args and args[args.index('--network') + 1] == 'none'
                 and '--read-only' in args and '--user' in args and args[args.index('--user') + 1] == '10001:10001', 'unsafe_controller_helper')
            name = args[args.index('--name') + 1]
            need(re.fullmatch(r'family-dashboard-' + self.policy.prefix + r'-check-[a-z0-9]+-[0-9]+', name), 'controller_helper_name')
            self.track_new('container', name)
            for i, arg in enumerate(args):
                if arg == '--mount':
                    mount = args[i + 1]
                    allowed = ('type=volume,src=' + self.volume + ',dst=/data',
                               'type=bind,src=' + str(self.candidate) + ',dst=/release-source,readonly')
                    valid_input = mount.startswith('type=bind,src=' + str(self.releases) + '/' + self.policy.prefix + '-') and mount.endswith('/verification,dst=/release-check,readonly') and '..' not in mount
                    need(mount in allowed or valid_input, 'foreign_mount')
            args = args[:2] + ['--label', LABEL + '=' + self.run_id] + args[2:]
        # The audited controller has no arbitrary host shell, pull, rm or prune.
        need(args[1] in ('compose', 'inspect', 'ps', 'image', 'tag', 'run', 'stop'), 'unexpected_controller_operation')
        try:
            result = self.runner(args, cwd=cwd, input_bytes=input_bytes, timeout=timeout, env=dict(self.host_environment))
        finally:
            # Docker may create a helper before returning a timeout. Track its
            # actual identity for the real controller's subsequent safe stop.
            candidates = ([name] if args[1:2] == ['run'] else
                          [self.project + '-' + x for x in ('app', 'sync', 'web')] if args[1:2] == ['compose'] and 'up' in args else [])
            for candidate in candidates:
                if candidate in self.list_names('container', candidate):self.owned('container', candidate)
        return result

    def prepare(self):
        need(not any(k.upper().startswith(('COMPOSE_', 'DOCKER_')) for k in os.environ), 'host_compose_environment')
        self.host_environment = dict(os.environ)
        manifest_raw, values = frozen_source(self.source, self.manifest_sha)
        need(values.get(SELF) == plain(Path(__file__)), 'harness_source_changed')
        need(all(n in values for n in (CONTROLLER, FIXTURE, 'deploy/check_static_release.py', 'deploy/backup.py', 'compose.yaml', 'Dockerfile', 'deploy/nginx.conf')), 'missing_dependency')
        proof_raw = plain(self.proof); need(sha(proof_raw) == self.proof_sha, 'proof_sha')
        core.bind_modules(values, [core.CORE] + ([core.SOURCE_ENTRY] if self.policy is core.SOURCE else []))
        proof = json.loads(proof_raw); hashes = {n: sha(v) for n, v in values.items()}
        backend = {n: h for n, h in hashes.items() if n == 'requirements.txt' or '/' not in n and n.endswith('.py')}
        static = {n: h for n, h in hashes.items() if n.startswith('static/')}
        need(proof.get('status') == 'built' and proof.get('image') == self.image and proof.get('parentImage') == self.parent
             and proof.get('manifestSha256') == self.manifest_sha and proof.get('sourceHashes') == hashes
             and proof.get('nonStaticRuntimeHashes') == backend and proof.get('staticHashes') == static
             and all(proof.get(k) is True for k in ('parentLayersPreserved', 'configurationUnchanged',
                     'parentBackendVerified', 'childBackendVerified', 'staticVerified'))
             and proof.get('pipExecuted') is False and proof.get('productionOperations') is False, 'invalid_build_proof')
        if self.policy is core.SOURCE:
            self.base_manifest, self.base_values = frozen_source(self.base_source, self.base_manifest_sha)
            core.source_files(self.base_source, {n: sha(v) for n, v in self.base_values.items()})
            old_hashes = {n: sha(v) for n, v in self.base_values.items()}
            need(plain(self.source / 'BASE-MANIFEST.json') == self.base_manifest, 'rehearsal_base_binding')
            core.validate_changes(old_hashes, hashes, sorted(n for n in hashes if old_hashes.get(n) != hashes[n]), policy=self.policy)
            need(proof.get('mode') == self.policy.mode and proof.get('baseManifestSha256') == self.base_manifest_sha
                 and proof.get('parentRuntimeHashes') == {**core.backend_hashes(old_hashes), **core.static_hashes(old_hashes)}
                 and proof.get('candidateRuntimeHashes') == {**backend, **static}
                 and proof.get('bytecodeExcluded') is True
                 and self.base_values.get(FIXTURE) == values[FIXTURE], 'source_rehearsal_proof')
            parent_backend = core.backend_hashes(old_hashes)
        else:
            parent_backend = backend
        self.output.mkdir(mode=0o700); self.created = True
        for image in (self.parent, self.image, self.nginx):
            info = json.loads(self.call(['image', 'inspect', image])); need(len(info) == 1 and info[0]['Id'] == image and info[0]['Os'] == 'linux', 'local_image')
        # This is a new run-specific tag, never the production app tag.
        need(self.tag not in self.call(['image', 'ls', '--filter', 'reference=' + self.tag, '--format', '{{.Repository}}']).splitlines(), 'existing_tag')
        parent_static = json.loads(self.ephemeral(self.parent, ['python', '-c', PARENT_FILES, json.dumps(parent_backend)]))
        old_static = {relative(n): base64.b64decode(v, validate=True) for n, v in parent_static.items()}
        need(old_static and all(n.startswith('static/') for n in old_static) and set(old_static) <= set(static), 'parent_static_inventory')
        self.proof_dir.mkdir(mode=0o700)
        if os.name == 'posix':os.chown(self.proof_dir, 10001, 10001)
        config = encoded(compose_config(self.project, self.run_id, self.nginx, self.proof_dir, self.root / 'tests'))
        nginx = b'server { listen 8080; location / { return 200 "Synthetic static rehearsal\\n"; } }\n'
        new_values = {**values, 'compose.yaml': config, 'deploy/nginx.conf': nginx}
        if self.policy is core.SOURCE:
            need(old_static == {n: v for n, v in self.base_values.items() if n.startswith('static/')}, 'parent_base_static')
            old_values = {**self.base_values, 'compose.yaml': config, 'deploy/nginx.conf': nginx}
        else:
            old_values = {n: v for n, v in new_values.items() if not n.startswith('static/')}; old_values.update(old_static)
        for directory, content in ((self.root, old_values), (self.candidate, new_values)):
            directory.mkdir(mode=0o755)
            for name, raw in content.items():
                target = directory / name; target.parent.mkdir(parents=True, exist_ok=True)
                for parent in target.parents:
                    if parent == directory:break
                    parent.chmod(0o755)
                target.write_bytes(raw); target.chmod(0o644)
            (directory / 'RELEASE-MANIFEST.json').write_bytes(encoded({'files': {n: sha(v) for n, v in content.items()}}))
        env = {'DATA_DIR': '/data', 'SECRET_KEY': secrets.token_hex(32), 'MEMBER1_PASSWORD': 'synthetic-' + secrets.token_hex(16),
               'MEMBER2_PASSWORD': 'synthetic-' + secrets.token_hex(16), 'PUBLIC_ORIGIN': 'https://127.0.0.1:8000',
               'COOKIE_SECURE': '0', 'TRUST_PROXY': '0', 'MICROSOFT_CLIENT_ID': 'synthetic-static-client',
               'MICROSOFT_CLIENT_SECRET': 'synthetic-static-secret', 'GOOGLE_CLIENT_ID': 'synthetic-static-client',
               'GOOGLE_CLIENT_SECRET': 'synthetic-static-secret', 'OPENAI_API_KEY': '', 'OPENAI_MODEL': '',
               'FAMILY_DASHBOARD_SYNTHETIC_REHEARSAL': '1', 'REHEARSAL_RUN_ID': self.run_id}
        env_raw = ''.join(k + '=' + v + '\n' for k, v in env.items()).encode()
        (self.root / '.env').write_bytes(env_raw); (self.root / '.env').chmod(0o600)
        candidate_hashes = {n: sha(v) for n, v in new_values.items()}; base_hashes = {n: sha(v) for n, v in old_values.items()}
        self.manifest, self.ready_sha = fixture_ready(self.candidate, base_hashes, candidate_hashes, self.parent, self.image, proof_raw, env_raw, policy=self.policy)
        self.controller = load_controller(self.candidate, self.policy)
        self.controller.evidence(self.candidate, json.loads(plain(self.candidate / 'READY.json')), candidate_hashes, self.image)
        self.controller.validate_changes(base_hashes, candidate_hashes, sorted(n for n in candidate_hashes if base_hashes.get(n) != candidate_hashes[n]))
        self.report.update(source=str(self.source), buildProof=str(self.proof),
                           sourceManifestSha256=self.manifest_sha, sourceHashes=hashes, buildProofSha256=self.proof_sha,
                           syntheticManifestSha256=self.manifest, syntheticReadySha256=self.ready_sha,
                           syntheticEnvelopesAreAcceptanceEvidence=False,
                           sourceAdaptations={n: {'originalSha256': hashes[n], 'syntheticSha256': candidate_hashes[n]}
                                              for n in candidate_hashes if hashes[n] != candidate_hashes[n]})
        self.original_values, self.original_manifest = values, manifest_raw
        if self.policy is core.SOURCE:
            self.report.update(baseSource=str(self.base_source), baseManifestSha256=self.base_manifest_sha,
                baseSourceHashes=old_hashes, baseSourceAdaptations={n: {'originalSha256': old_hashes[n], 'syntheticSha256': base_hashes[n]}
                    for n in old_hashes if old_hashes[n] != base_hashes[n]})

    def compose(self, *args, timeout=180):
        return self.runner([*self.compose_prefix(), *args], cwd=self.root, timeout=timeout, env=dict(self.host_environment))

    def fixture_result(self, label, *args):
        # Only the two audited synthetic fixture commands use this recorder.
        # Compose config/inspect environment output must never be saved here.
        need(label in ('seed', 'data-verification'), 'fixture_record_label')
        try:
            raw = self.compose(*args, timeout=240).encode()
        except DockerFailure as error:
            for suffix, value in (('stdout', error.stdout), ('stderr', error.stderr)):
                path = self.output / (label + '-' + suffix + '.log')
                with path.open('xb') as stream:stream.write(value)
                path.chmod(0o600)
            self.report[label + 'Failure'] = {'exitCode': error.returncode,
                'stdout': str(self.output / (label + '-stdout.log')), 'stdoutSha256': sha(error.stdout),
                'stderr': str(self.output / (label + '-stderr.log')), 'stderrSha256': sha(error.stderr)}
            raise
        path = self.output / (label + '-result.json')
        with path.open('xb') as stream:stream.write(raw)
        path.chmod(0o600)
        self.report[label + 'Record'] = {'path': str(path), 'sha256': sha(raw)}
        return json.loads(raw)

    def run(self):
        need(os.name == 'posix', 'linux_host_required')
        self.report['phase'] = 'prepare'
        self.prepare()
        self.report['phase'] = 'seed'
        self.track_new('volume', self.volume)
        self.call(['volume', 'create', '--label', LABEL + '=' + self.run_id, self.volume]); self.owned('volume', self.volume)
        self.ephemeral(self.parent, ['python', '-c', "import os;os.chown('/data',10001,10001);os.chmod('/data',0o700)"], mounts=[self.volume], user='0:0')
        for service in ('app', 'sync', 'web'):self.track_new('container', self.project + '-' + service)
        self.tag_created = True  # Preserve intent if Docker times out after tagging.
        self.call(['tag', self.parent, self.tag])
        self.compose('up', '-d', '--no-build', '--no-deps', '--wait', '--wait-timeout', '180', 'app', timeout=220)
        app = self.project + '-app'; self.owned('container', app)
        seed = self.fixture_result('seed', 'exec', '-T', 'app', 'python', '/rehearsal/tests/restore_rehearsal_fixture.py', 'seed', '--proof-dir', '/proof')
        self.check('two_household_seed', seed.get('passed') is True and seed.get('counts', {}).get('households') == 2
                   and seed['counts'].get('journeyDocuments') == 8 and not seed.get('externalRequests'))
        self.report['seed'] = seed
        self.compose('up', '-d', '--no-build', '--no-deps', 'sync', 'web')
        for service in ('app', 'sync', 'web'):self.owned('container', self.project + '-' + service)
        self.report['phase'] = 'actual-controller'
        result = self.controller.activate(self.candidate, self.image, self.manifest, self.ready_sha,
                 root=self.root, releases=self.releases, project=self.project, volume=self.volume, runner=self.controller_runner)
        original = Path(result['releaseDirectory']) / 'deployment.json'
        need(original.is_relative_to(self.releases) and json.loads(plain(original)) == result, 'controller_original_record')
        self.check('actual_controller_completed', result.get('status') == 'published' and result.get('environmentPreserved') is True
                   and result.get('originalTablesPreserved') == 43 and result.get('newTables') == 0
                   and result.get('stoppedDatabaseContentsPreserved') is True and result.get('automaticRestoreAttempted') is False
                   and result.get('backupVerification', {}).get('databases') == 3)
        self.report['controller'] = {'path': str(original), 'sha256': sha(plain(original)), 'status': result['status'],
            'originalTablesPreserved': 43, 'newTables': 0, 'backupDatabases': 3,
            'beforeInstallReadback': result['beforeInstallReadback'], 'startupReadback': result['startupReadback'],
            'afterHttpReadback': result['afterHttpReadback']}
        self.report['phase'] = 'independent-data-readback'
        verified = self.fixture_result('data-verification', 'exec', '-T', 'app', 'python', '-c', DATA_VERIFY)
        self.check('rows_authentication_and_binary_files', verified.get('passed') is True and verified.get('documents') == 8)
        self.report['dataVerification'] = verified
        raw, values = frozen_source(self.source, self.manifest_sha)
        self.check('input_source_unchanged', raw == self.original_manifest and values == self.original_values and sha(plain(self.proof)) == self.proof_sha)
        if self.policy is core.SOURCE:
            raw, values = frozen_source(self.base_source, self.base_manifest_sha)
            self.check('base_source_unchanged', raw == self.base_manifest and values == self.base_values
                       and plain(self.source / 'BASE-MANIFEST.json') == raw)
        self.report['passed'] = True
        self.report['phase'] = 'complete'

    def cleanup(self):
        failures = []
        for kind, name in reversed(list(self.resources)):
            try:
                if name not in self.list_names(kind, name):continue
                info = self.owned(kind, name)
                if kind == 'container':
                    if info['State']['Running']:self.call(['stop', '--time', '45', name], timeout=60)
                    self.owned(kind, name); self.call(['container', 'rm', name])
                else:self.call(['volume', 'rm', name])
                need(name not in self.list_names(kind, name), 'resource_not_removed')
            except Exception as e:failures.append({'kind': kind, 'name': name, 'errorType': type(e).__name__})
        self.report['cleanup'] = {'passed': not failures, 'failures': failures, 'tracked': len(self.resources)}
        # Removing the final tag can delete the supplied untagged child image.
        # Keep only our unique tag; never prune or remove caller-supplied images.
        self.report['retainedImageTag'] = self.tag if self.tag_created else None
        self.report['retainedImageTagReason'] = 'Protect caller-supplied immutable images; removing their final tag could delete them.'
        self.report['allDockerObjectsRemoved'] = False if self.tag_created else not failures
        if failures:self.report['passed'] = False

    def execute(self):
        try:self.run()
        except BaseException as e:self.report.update(passed=False, errorType=type(e).__name__)
        finally:
            if self.created:self.cleanup()
        self.report['completedAt'] = datetime.now(timezone.utc).isoformat()
        if self.created:
            path = self.output / (self.policy.prefix + '-rehearsal.json')
            with path.open('xb') as f:f.write(encoded(self.report))
            path.chmod(0o600)
        return self.report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'manifest-sha256', 'parent-image', 'image', 'build-proof', 'build-proof-sha256', 'nginx-image', 'output'):
        parser.add_argument('--' + name, required=True)
    a = parser.parse_args(argv)
    try:
        run = Rehearsal(a.source, a.manifest_sha256, a.parent_image, a.image, a.build_proof, a.build_proof_sha256, a.nginx_image, a.output)
        def interrupted(*unused):raise RuntimeError('static_rehearsal_interrupted')
        for sig in (signal.SIGTERM, signal.SIGINT):signal.signal(sig, interrupted)
        result = run.execute()
    except Exception:
        print(json.dumps({'passed': False, 'error': 'static_rehearsal_preflight_failed'})); return 1
    print(json.dumps({'passed': result['passed'], 'runId': run.run_id, 'report': str(run.output / 'static-rehearsal.json')}))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
