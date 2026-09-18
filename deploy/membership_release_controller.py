"""One reviewed membership release: inspect, stage, activate; no automatic rollback.

The caller supplies an independently reviewed plan by its SHA256. Building and
isolated tests precede staging. This controller never installs dependencies or
restores data. Production defaults cannot be selected through environment vars.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import xml.etree.ElementTree as ET

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


ROOT = Path('/opt/family-dashboard')
RELEASES = Path('/opt/family-dashboard-releases')
VOLUME = 'family-dashboard_household-data'
SERVICES = ('app', 'sync', 'media', 'web')
PARENT_IMAGE = 'sha256:09f583b81f5782ceebc008995665fe095ac6ef0822302bc9b5d84ab3aa3f42f2'
WEB_IMAGE = 'sha256:1ae82dcc4a34bcd976195b3c4c5a6b7e569505527a1e2a28c2101e032159a5c7'
OLD_MANIFEST = 'db3a984f570d38b88c62cb040181f3b4f9d812ace04193ac21c509f899c4c246'
PUBLIC_ORIGIN = 'https://home.caesarcharles.world'


class ReleaseError(RuntimeError):
    pass


def need(value, code):
    if not value:
        raise ReleaseError(code)


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def relative(name):
    need(isinstance(name, str) and name and '\\' not in name and ':' not in name, 'unsafe_path')
    path = PurePosixPath(name)
    need(not path.is_absolute() and path.as_posix() == name and '..' not in path.parts, 'unsafe_path')
    return name


def regular(path, *, directory=False):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        try:
            value = item.lstat()
        except OSError:
            raise ReleaseError('missing_input') from None
        need(not stat.S_ISLNK(value.st_mode) and not getattr(value, 'st_file_attributes', 0) & 1024, 'linked_input')
    need(path.is_dir() if directory else path.is_file(), 'wrong_input_type')
    return path


def read(path, expected=None):
    path = regular(path)
    need(path.stat().st_size <= 32_000_000, 'oversized_input')
    raw = path.read_bytes()
    if expected is not None:
        need(sha(raw) == expected, 'input_digest_changed')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            need(key not in result, 'duplicate_json_key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


def put(path, value):
    raw = value if isinstance(value, bytes) else encoded(value)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def runtime_environment(value):
    """Serialize Docker Config.Env verbatim, never reinterpret Compose syntax."""
    need(isinstance(value, list) and value, 'runtime_environment_shape')
    keys = set()
    for entry in value:
        need(isinstance(entry, str) and not any(c in entry for c in '\x00\r\n')
             and '=' in entry, 'runtime_environment_entry')
        key = entry.split('=', 1)[0]
        need(re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', key) and key not in keys,
             'runtime_environment_key')
        keys.add(key)
    need('DATA_DIR=/data' in value, 'runtime_data_directory')
    try:
        return ('\n'.join(value) + '\n').encode('utf-8')
    except UnicodeError:
        raise ReleaseError('runtime_environment_encoding') from None


def run(argv, *, cwd=ROOT, timeout=240, input_bytes=None):
    try:
        result = subprocess.run(argv, cwd=cwd, input=input_bytes, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ReleaseError('command_unavailable_or_timeout') from None
    need(result.returncode == 0, 'command_failed')
    return result.stdout


def source_hashes(root, files, *, exact=False):
    root = regular(root, directory=True)
    for name, digest in files.items():
        path = regular(root / relative(name))
        need(sha(path.read_bytes()) == digest, 'source_changed')
    if exact:
        actual = set()
        for path in root.rglob('*'):
            need(not path.is_symlink(), 'source_link')
            if path.is_file():
                actual.add(path.relative_to(root).as_posix())
        need(actual == set(files) | {'RELEASE-MANIFEST.json'}, 'unexpected_source_files')
    else:
        need({p.name for p in root.glob('*.py')} == {n for n in files if '/' not in n and n.endswith('.py')}, 'unexpected_runtime_module')
        for folder in ('static',):
            actual = {p.relative_to(root).as_posix() for p in (root / folder).rglob('*') if p.is_file()}
            need(actual == {n for n in files if n.startswith(folder + '/')}, 'unexpected_static_files')


RUNTIME_PROGRAM = """
from pathlib import Path
import hashlib,json
root=Path('/app'); result={}
for p in root.rglob('*'):
 if p.is_symlink() or p.suffix in ('.pyc','.pyo'):raise RuntimeError('runtime_link_or_cache')
 if p.is_file():result[p.relative_to(root).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
print(json.dumps(result))
"""


def verify_junit(path, expected_cases, allowed_skips):
    root = ET.fromstring(regular(path).read_bytes())
    cases = list(root.iter('testcase'))
    identities = [[c.get('classname'), c.get('name')] for c in cases]
    need(identities and len({tuple(v) for v in identities}) == len(identities), 'duplicate_or_empty_tests')
    need(sorted(identities) == sorted(expected_cases), 'test_selection_changed')
    need(not list(root.iter('failure')) and not list(root.iter('error')), 'tests_failed')
    skips = [{'classname': c.get('classname'), 'name': c.get('name'), 'message': s.get('message')}
             for c in cases for s in c.findall('skipped')]
    need(skips == allowed_skips, 'unexpected_test_skip')
    suites = list(root.iter('testsuite'))
    need(sum(int(s.get('tests', 0)) for s in suites) == len(cases), 'test_count_changed')
    need(sum(int(s.get('failures', 0)) + int(s.get('errors', 0)) for s in suites) == 0, 'test_summary_failed')
    need(sum(int(s.get('skipped', 0)) for s in suites) == len(skips), 'skip_summary_changed')
    return {'tests': len(cases), 'passed': len(cases) - len(skips), 'skipped': len(skips)}


class Controller:
    def __init__(self, candidate, plan_sha256, *, runner=run, root=ROOT, releases=RELEASES):
        self.candidate = regular(candidate, directory=True)
        self.root, self.releases, self.runner = root, releases, runner
        self.plan_sha = plan_sha256
        self.plan = read(self.candidate / 'release-plan.json', plan_sha256)
        need(self.plan.get('schemaVersion') == 1 and self.plan.get('kind') == 'membership-release-plan', 'plan_kind')
        need(sha(regular(Path(__file__)).read_bytes()) == self.plan.get('controllerSha256'), 'controller_not_reviewed')
        need(re.fullmatch('sha256:[0-9a-f]{64}', self.plan.get('imageId', '')), 'image_id')
        need(self.plan.get('parentImage') == PARENT_IMAGE and self.plan.get('webImage') == WEB_IMAGE
             and self.plan.get('oldManifestSha256') == OLD_MANIFEST, 'baseline_changed')
        verifier_path = regular(Path(__file__).with_name('membership_release_package.py'))
        need(sha(verifier_path.read_bytes()) == self.plan.get('packageVerifierSha256'), 'package_verifier_not_reviewed')
        from deploy import membership_release_package as verifier
        need(regular(verifier.__file__) == verifier_path, 'package_verifier_import_changed')
        self.verified = verifier.verify_package(self.candidate / 'package', self.plan['packageSha256'])
        # verify_package's public return contract is normalized by the package
        # author; this controller binds the same original package metadata.
        self.package = read(self.candidate / 'package/package.json', self.plan['packageSha256'])
        self.manifest = read(self.candidate / 'package/release-manifest.json', self.package['manifestSha256'])
        self.files = self.manifest['files']
        self.runtime = self.package['runtimeFiles']
        self.source = regular(self.candidate / 'source', directory=True)
        need(sha((self.source / 'RELEASE-MANIFEST.json').read_bytes()) == self.package['manifestSha256'], 'extracted_manifest_changed')
        source_hashes(self.source, self.files, exact=True)
        need(self.package['parentImage'] == PARENT_IMAGE and self.package['oldManifestSha256'] == OLD_MANIFEST, 'package_baseline')
        need(self.plan.get('reviews'), 'reviews_required')
        for name, digest in self.plan['reviews'].items():
            need(sha(regular(self.candidate / relative(name)).read_bytes()) == digest, 'review_changed')

    def call(self, argv, **kwargs):
        return self.runner(argv, cwd=self.root, **kwargs)

    def inspect(self, reference):
        value = json.loads(self.call(['docker', 'inspect', reference]))
        need(len(value) == 1, 'ambiguous_container')
        return value[0]

    def current_services(self, expected_image):
        result = {}
        for name in SERVICES:
            value = self.inspect('family-dashboard-' + name + '-1')
            need(value['State']['Running'] and not value['State']['OOMKilled'], 'service_not_running')
            need(value['Image'] == (WEB_IMAGE if name == 'web' else expected_image), 'service_image_changed')
            labels = value['Config'].get('Labels') or {}
            need(labels.get('com.docker.compose.project') == 'family-dashboard'
                 and labels.get('com.docker.compose.service') == name, 'service_identity_changed')
            if name != 'web':
                mounts = [m for m in value['Mounts'] if m['Destination'] == '/data']
                need(len(mounts) == 1 and mounts[0]['Type'] == 'volume' and mounts[0]['Name'] == VOLUME, 'volume_changed')
            if name == 'app':
                need(value['State']['Health']['Status'] == 'healthy', 'app_unhealthy')
            result[name] = {'id': value['Id'], 'image': value['Image']}
            if name == 'app':
                result[name]['environmentSha256'] = sha(runtime_environment(value['Config'].get('Env')))
        return result

    def baseline(self):
        need(sha(regular(self.root / 'RELEASE-MANIFEST.json').read_bytes()) == OLD_MANIFEST, 'installed_manifest_changed')
        old = read(self.root / 'RELEASE-MANIFEST.json')['files']
        source_hashes(self.root, old)
        env = regular(self.root / '.env')
        need(sha(env.read_bytes()) == self.plan['envSha256'] and stat.S_IMODE(env.stat().st_mode) == 0o600, 'environment_changed')
        need(old['compose.yaml'] == self.files['compose.yaml'] and old['deploy/nginx.conf'] == self.files['deploy/nginx.conf']
             and old['requirements.txt'] == self.files['requirements.txt'], 'deployment_or_dependency_change')
        need(all(n.startswith('static/experience/') or not (n.endswith('.py') or n.startswith('static/'))
                 for n in set(old) - set(self.files)), 'unsupported_runtime_removal')
        return old, self.current_services(PARENT_IMAGE)

    def candidate_image(self):
        image = self.plan['imageId']
        parent, child = self.inspect(PARENT_IMAGE), self.inspect(image)
        layers = parent['RootFS']['Layers']
        need(child['RootFS']['Layers'][:len(layers)] == layers and len(child['RootFS']['Layers']) == len(layers) + 2, 'image_parent_changed')
        need({k:v for k,v in parent['Config'].items() if k != 'Image'} ==
             {k:v for k,v in child['Config'].items() if k != 'Image'}, 'image_configuration_changed')
        observed = json.loads(self.call(['docker', 'run', '--rm', '--network', 'none', '--read-only', '--user', '10001:10001',
            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true', '--entrypoint', 'python', image, '-B', '-c', RUNTIME_PROGRAM]))
        need(observed == self.runtime, 'image_runtime_changed')

    def validate_evidence(self):
        proof = self.plan['validation']
        report_path = self.candidate / relative(proof['path'])
        report = read(report_path, proof['sha256'])
        validation_root = report_path.parent
        need(report.get('imageId') == self.plan['imageId'] and report.get('sourceHead') == self.package['sourceHead']
             and report.get('manifestSha256') == self.package['manifestSha256'] and report.get('exitCode') == 0
             and report.get('allPassed') is True and report.get('packageSha256') == self.plan['packageSha256'],
             'validation_identity_changed')
        originals = report['evidence']
        for name, digest in originals.items():
            need(sha(regular(validation_root / relative(name)).read_bytes()) == digest, 'validation_original_changed')
        counts = verify_junit(validation_root / relative(report['junitPath']), self.plan['testCases'], self.plan['allowedSkips'])
        need(report['junitPath'] in originals, 'unbound_junit')
        runtime = read(validation_root / relative(report['runtimePath']))
        modules = {n[:-3]: '/app/' + n for n in self.runtime if '/' not in n and n.endswith('.py')}
        need(report['runtimePath'] in originals and runtime.get('before') == self.runtime
             and runtime.get('after') == self.runtime and runtime.get('loadedBefore') == modules
             and runtime.get('loadedAfter') == modules and runtime.get('sourceBefore') == self.files
             and runtime.get('sourceAfter') == self.files,
             'validation_runtime_changed')
        return counts

    def stage(self):
        self.candidate_image()
        counts = self.validate_evidence()
        old, services = self.baseline()
        self.call(['docker', 'compose', 'config', '--quiet'])
        value = {'planSha256': self.plan_sha, 'services': services, 'oldFiles': old, 'tests': counts,
                 'imageId': self.plan['imageId'], 'schemaBefore': [58, 2], 'schemaAfter': [61, 9], 'productionWrites': False}
        put(self.candidate / 'stage.json', value)
        return value

    def bind_data_environment(self, release, service):
        value = self.inspect(service['id'])
        need(value['Id'] == service['id'] and value['Image'] == service['image'], 'runtime_environment_service_changed')
        raw = runtime_environment(value['Config'].get('Env'))
        need(sha(raw) == service.get('environmentSha256'), 'runtime_environment_changed')
        path = regular(release, directory=True) / 'app-runtime.env'
        put(path, raw)
        self.data_environment = (path, sha(raw))

    def data_call(self, proof, program, *, write=True):
        binding = getattr(self, 'data_environment', None)
        need(binding is not None, 'runtime_environment_not_bound')
        path, digest = binding
        need(path == proof.parent / 'app-runtime.env', 'runtime_environment_location')
        path = regular(path)
        need(stat.S_IMODE(path.stat().st_mode) == 0o600 and sha(path.read_bytes()) == digest,
             'runtime_environment_file_changed')
        original = regular(self.root / '.env')
        need(stat.S_IMODE(original.stat().st_mode) == 0o600
             and sha(original.read_bytes()) == self.plan['envSha256'], 'environment_changed')
        mount = VOLUME + ':/data' + ('' if write else ':ro')
        args = ['docker', 'run', '--rm', '--network', 'none', '--read-only', '--user', '10001:10001', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges:true', '--memory', '512m', '--tmpfs', '/tmp:rw,size=268435456,mode=1777',
                '--env-file', str(path),
                '-v', mount, '-v', str(self.source) + ':/release:ro', '-v', str(proof) + ':/proof',
                '--entrypoint', 'python', self.plan['imageId'], '-B', '-c', DATA_PREFIX + program]
        return json.loads(self.call(args, timeout=360))

    def activate(self):
        self.candidate_started = False
        try:
            return self._activate()
        except BaseException:
            # A failed health check or a partially successful compose up can
            # leave new writers running. Stop those writers; never restore data
            # or revive the old application after the schema migration.
            if self.candidate_started:
                stopped = True
                for command in (
                    ['systemctl', 'stop', 'family-dashboard-backup.timer'],
                    ['docker', 'compose', 'stop', 'web'],
                    ['docker', 'compose', 'stop', '--timeout', '360', 'media', 'sync', 'app'],
                ):
                    try:
                        self.call(command, timeout=420)
                    except Exception:
                        stopped = False
                try:
                    stopped = stopped and not self.call(['docker', 'ps', '-q', '--filter', 'volume=' + VOLUME]).strip()
                    value = read(self.candidate / 'activation.json')
                    value.update(completed=False, candidateStoppedAfterFailure=bool(stopped))
                    import uuid
                    temporary = self.candidate / ('activation.failure-' + uuid.uuid4().hex + '.json')
                    put(temporary, value)
                    os.replace(temporary, self.candidate / 'activation.json')
                except Exception:
                    pass  # Preserve the earlier phase record if storage itself failed.
            raise

    def _activate(self):
        staged = read(self.candidate / 'stage.json')
        need(staged['planSha256'] == self.plan_sha, 'stage_plan_changed')
        self.candidate_image()
        self.validate_evidence()
        old, services = self.baseline()
        need(staged['services'] == services and staged['oldFiles'] == old, 'stage_baseline_changed')
        need(self.call(['systemctl', 'is-active', 'family-dashboard-backup.timer']).strip() == b'active', 'backup_timer_not_active')
        # `show` exits successfully for inactive units and avoids logging their environment.
        need(self.call(['systemctl', 'show', '-p', 'ActiveState', '--value', 'family-dashboard-backup.service']).strip() == b'inactive', 'backup_running')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        report = {'planSha256': self.plan_sha, 'completed': False, 'steps': []}
        put(self.candidate / 'activation.json', report)
        release = self.releases / ('memberships-61-' + stamp)
        release.mkdir(mode=0o700)
        report['releaseDirectory'] = str(release)
        def record(step):
            report['steps'].append(step)
            tmp = self.candidate / 'activation.next.json'
            put(tmp, report)
            os.replace(tmp, self.candidate / 'activation.json')
        old_dir = release / 'source-before'
        old_dir.mkdir(mode=0o700)
        for name in [*old, 'RELEASE-MANIFEST.json']:
            target = old_dir / relative(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(regular(self.root / name), target)
        source_hashes(old_dir, old, exact=True)
        put(release / 'env-before', regular(self.root / '.env').read_bytes())
        self.bind_data_environment(release, services['app'])
        for i, image in enumerate(sorted({v['image'] for v in services.values()})):
            self.call(['docker', 'tag', image, 'family-dashboard-preserved:memberships-' + stamp.lower() + '-' + str(i)])
        record('old_source_configuration_images_preserved')
        self.call(['systemctl', 'stop', 'family-dashboard-backup.timer'])
        need(self.call(['systemctl', 'show', '-p', 'ActiveState', '--value', 'family-dashboard-backup.service']).strip() == b'inactive', 'backup_raced_stop')
        self.call(['docker', 'compose', 'stop', 'web'])
        self.call(['docker', 'compose', 'stop', '--timeout', '360', 'media', 'sync', 'app'], timeout=420)
        need(not self.call(['docker', 'ps', '-q', '--filter', 'volume=' + VOLUME]).strip(), 'data_writer_still_running')
        for item in services.values():
            state = self.inspect(item['id'])['State']
            need(not state['Running'] and not state['OOMKilled'] and state['ExitCode'] in (0, 143), 'unclean_stop')
        record('all_writers_stopped')
        proof = release / 'proof'
        proof.mkdir(mode=0o700)
        os.chown(proof, 10001, 10001)
        identity = {'head': self.package['sourceHead'], 'tree': self.package['tree'], 'imageId': self.plan['imageId'],
                    'sourceHashes': self.files, 'runtimeHashes': self.runtime}
        put(proof / 'identity.json', identity)
        os.chown(proof / 'identity.json', 10001, 10001)
        before = self.data_call(proof, BACKUP_PROGRAM)
        record('full_stopped_backup_verified_and_preserved')
        migrated = self.data_call(proof, WARM_PROGRAM)
        need(migrated.get('verified') is True, 'migration_not_verified')
        record('all_households_and_platform_migrated_and_verified')
        # Original generated files are kept outside the served directory.
        regular(self.root / 'static/experience', directory=True)
        os.rename(self.root / 'static/experience', release / 'expo-before')
        for name in [*self.files, 'RELEASE-MANIFEST.json']:
            target = self.root / relative(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            regular(target.parent, directory=True)
            need(not target.is_symlink(), 'linked_install_target')
            temporary = target.with_name(target.name + '.memberships-new')
            put(temporary, regular(self.source / name).read_bytes())
            temporary.chmod(0o755 if name.startswith('deploy/') and name.endswith('.sh') else 0o644)
            os.replace(temporary, target)
        source_hashes(self.root, self.files)
        need(sha((self.root / '.env').read_bytes()) == self.plan['envSha256'], 'environment_changed')
        record('new_source_installed')
        self.call(['docker', 'tag', self.plan['imageId'], 'family-dashboard-app:latest'])
        self.candidate_started = True
        self.call(['docker', 'compose', 'up', '-d', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '150', 'app'])
        app = self.inspect('family-dashboard-app-1')
        need(app['Image'] == self.plan['imageId'] and app['State']['Health']['Status'] == 'healthy', 'new_app_unhealthy')
        observed = json.loads(self.call(['docker', 'exec', app['Id'], 'python', '-B', '-c', RUNTIME_PROGRAM]))
        need(observed == self.runtime, 'new_app_runtime_changed')
        # Recheck closed SQLite files after the real app's initialization.
        self.call(['docker', 'compose', 'stop', '--timeout', '60', 'app'])
        need(not self.call(['docker', 'ps', '-q', '--filter', 'volume=' + VOLUME]).strip(), 'app_did_not_stop')
        after = self.data_call(proof, "value=data.check_current_after(proof/'attempt',root); print(json.dumps({'verified':True}))", write=False)
        need(after == {'verified': True}, 'app_startup_changed_data')
        record('real_app_startup_preserved_migrated_data')
        self.call(['docker', 'compose', 'up', '-d', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '150', 'app'])
        self.call(['docker', 'compose', 'up', '-d', '--no-deps', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '150', 'sync', 'media', 'web'])
        current = self.current_services(self.plan['imageId'])
        health = self.call(['curl', '--fail', '--silent', '--show-error', '--max-time', '30', PUBLIC_ORIGIN + '/healthz'])
        need(json.loads(health).get('status') == 'ok', 'public_health_failed')
        source_hashes(self.root, self.files)
        self.call(['systemctl', 'start', 'family-dashboard-backup.timer'])
        report.update(completed=True, completedAt=datetime.now(timezone.utc).isoformat(), services=current,
                      migration=migrated, stoppedBackup=before, householdTables=61, platformTables=9)
        record('new_services_verified_and_backup_timer_started')
        return report


DATA_PREFIX = """
from pathlib import Path
import hashlib,json,os,shutil,sys
sys.path.insert(0,'/app');sys.path.insert(1,'/release')
from deploy import membership_release_data as data
from deploy.membership_release_controller import source_hashes,RUNTIME_PROGRAM
root=Path('/data');proof=Path('/proof')
identity=json.loads((proof/'identity.json').read_bytes())
source_hashes(Path('/release'),identity['sourceHashes'],exact=True)
observed={}
for p in Path('/app').rglob('*'):
 if p.is_symlink():raise RuntimeError('runtime_link')
 if p.is_file():observed[p.relative_to('/app').as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
if observed!=identity['runtimeHashes']:raise RuntimeError('runtime_changed')
"""
BACKUP_PROGRAM = """
from deploy.backup import backup_all
before=data.snapshot(root)
receipt=backup_all(root)
manifest=root/'backups'/receipt['manifest']
finished=data.finish_stopped_backup(root,before,manifest)
saved=proof/'backup-group';saved.mkdir(mode=0o700)
value=json.loads(manifest.read_bytes())
for item in value['snapshots']:
 target=saved/item['path'];target.parent.mkdir(parents=True,exist_ok=True)
 shutil.copyfile(root/item['path'],target);target.chmod(0o600)
saved_manifest=saved/'backups'/receipt['manifest']
saved_manifest.parent.mkdir(parents=True,exist_ok=True)
shutil.copyfile(manifest,saved_manifest);saved_manifest.chmod(0o600)
data.validate_backup(root,before,saved_manifest)
for name,value in [('before.json',before),('backup.json',receipt),('backup-finish.json',finished)]:
 with (proof/name).open('x') as stream:json.dump(value,stream)
 (proof/name).chmod(0o600)
print(json.dumps({'verified':True,'manifest':receipt['manifest'],'databases':receipt['databases']}))
"""
WARM_PROGRAM = """
before=json.loads((proof/'before.json').read_bytes())
receipt=json.loads((proof/'backup.json').read_bytes())
def warm():
 import app
 if Path(app.__file__).resolve()!=Path('/app/app.py'):raise RuntimeError('app_import_changed')
 application=app.create_app()
 platform=application.extensions['household_platform']
 for household in platform.households():platform.child(household)
result=data.warm_once(root,before,proof/'backup-group/backups'/receipt['manifest'],proof/'attempt',source_identity=identity,warm=warm)
data.check_current_after(proof/'attempt',root)
print(json.dumps({'verified':True}))
"""


@contextmanager
def release_lock():
    import fcntl
    regular(RELEASES, directory=True)
    fd = os.open(RELEASES / '.membership-release.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def main(argv=None):
    import argparse
    import signal
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['stage', 'activate'])
    parser.add_argument('candidate', type=Path)
    parser.add_argument('plan_sha256')
    args = parser.parse_args(argv)
    need(sys.platform == 'linux' and os.geteuid() == 0 and sys.dont_write_bytecode
         and not sys.flags.optimize and sys.pycache_prefix is None, 'operator_runtime')
    need(not any(n.upper().startswith(('COMPOSE_', 'DOCKER_')) for n in os.environ), 'ambient_docker_selector')
    need(args.candidate.parent == Path('/opt/family-dashboard-candidates'), 'candidate_location')
    def interrupted(*unused):
        raise ReleaseError('release_interrupted')
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, interrupted)
    with release_lock():
        controller = Controller(args.candidate, args.plan_sha256)
        value = getattr(controller, args.action)()
    print(json.dumps({'action': args.action, 'completed': value.get('completed', False),
                      'staged': args.action == 'stage', 'planSha256': args.plan_sha256}))


if __name__ == '__main__':
    try:
        main()
    except (ReleaseError, OSError, ValueError, KeyError):
        raise SystemExit('membership_release_failed; preserve evidence and stopped state; no automatic restore') from None
