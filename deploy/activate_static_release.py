"""Static-only, 43-to-43 deployment. No schema initialization or automatic restore.

The caller independently approves READY's SHA and the referenced raw evidence.
This controller preserves/validates evidence, but does not manufacture test
results. Import is read-only. Production execution requires separate approval.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.util
from io import BytesIO
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tarfile


ROOT = Path('/opt/family-dashboard')
RELEASES = Path('/opt/family-dashboard-releases')
VOLUME = 'family-dashboard_household-data'
HELPER = 'deploy/check_static_release.py'
CONTROLLER = 'deploy/activate_static_release.py'
TOOLS = {HELPER, CONTROLLER, 'deploy/build_static_release.py', 'deploy/rehearse_static_release.py'}
DEPENDENCIES = {
    'deploy/activate_journey_documents_release.py': '703a1540f7a632301382ec32aaee3b68e2c2157943469a71492a0d1a9e75972c',
    'deploy/check_journey_documents_migration.py': '11adc9f40bf68aaca7015f3c9f18f92c7aa648b6c379b0812b60b5d22cd2781f',
}
REQUIRED = {HELPER, CONTROLLER, 'journey_documents.py', 'deploy/backup.py',
            'app.py', 'requirements.txt', 'Dockerfile', 'compose.yaml', *DEPENDENCIES}
ANONYMOUS_PATHS = ['/api/state', '/api/preferences', '/api/assistant/brief',
                   '/api/finance-hub/overview', '/api/finance-baseline/private',
                   '/api/journeys', '/api/journey-documents',
                   '/api/journey-documents/readback-nonexistent/file']


def load_legacy():
    name = 'deploy/activate_journey_documents_release.py'
    path = Path(__file__).resolve().parents[1] / name
    if hashlib.sha256(path.read_bytes()).hexdigest() != DEPENDENCIES[name]:
        raise RuntimeError('static_controller_dependency_changed')
    spec = importlib.util.spec_from_file_location('static_release_pure_dependency', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


L = load_legacy()
need, sha, encoded = L.need, L.sha, L.encoded
hash_string, relative, plain_file = L.hash_string, L.relative, L.plain_file
read_manifest, integer = L.read_manifest, L.integer
parse_compose_config_output, validated_environment = L.parse_compose_config_output, L.validated_environment
put, runtime_hashes, FORMAT = L.put, L.runtime_hashes, L.FORMAT


def host_environment():
    """Freeze CLI interpolation inputs without inheriting Docker/Compose selectors."""
    value = dict(os.environ)
    need(not any(k.upper().startswith(('COMPOSE_', 'DOCKER_')) for k in value),
         'host_docker_compose_environment')
    return value


def command(arguments, *, cwd, env, input_bytes=None, timeout=180):
    # Never emit argv, environment, stdout or stderr on failure: any can be private.
    need(isinstance(env, dict), 'command_environment_missing')
    try:
        result = subprocess.run(arguments, cwd=cwd, env=dict(env), input=input_bytes,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise RuntimeError('command_timeout') from None
    need(result.returncode == 0, 'command_failed_' + str(result.returncode))
    return result.stdout.decode('utf-8').strip()


def source_files(directory, hashes):
    values = L.source_files(directory, hashes)
    managed = set(p.name for p in directory.glob('*.py'))
    for folder in ('static', 'docs', 'tests', 'deploy'):
        for p in (directory / folder).rglob('*'):
            if '__pycache__' in p.parts:
                continue
            if p.is_file() and not p.name.endswith('.pyc'):
                managed.add(p.relative_to(directory).as_posix())
    need(managed <= set(hashes), 'unlisted_source')
    return values


def static_hashes(hashes):
    return {n: d for n, d in hashes.items() if n.startswith('static/')}


def backend_hashes(hashes):
    return {n: d for n, d in hashes.items() if n == 'requirements.txt' or n.endswith('.py') and '/' not in n}


def validate_changes(base, candidate, changed):
    need(set(base) <= set(candidate), 'source_removal')
    need(changed and any(n.startswith('static/') for n in changed), 'no_static_change')
    for name in changed:
        allowed = (name.startswith('static/') or name == 'README.md'
                   or name.startswith('docs/') and name.endswith('.md')
                   or name.startswith('tests/') and name.endswith('.py') or name in TOOLS)
        need(allowed, 'protected_source_change')
    need(backend_hashes(base) == backend_hashes(candidate), 'backend_changed')


def verify_images(parent, child, previous, image):
    need(isinstance(parent, list) and len(parent) == 1 and isinstance(child, list) and len(child) == 1, 'image_metadata')
    parent, child = parent[0], child[0]
    need(parent.get('Id') == previous and child.get('Id') == image, 'image_identity')
    old = parent.get('RootFS', {}).get('Layers')
    new = child.get('RootFS', {}).get('Layers')
    need(isinstance(old, list) and old and isinstance(new, list)
         and len(new) == len(old) + 1 and new[:-1] == old, 'image_parent_layers')
    need(isinstance(parent.get('Config'), dict) and parent['Config'] == child.get('Config'), 'image_configuration_changed')


def evidence(candidate, ready, hashes, image):
    refs = ready.get('evidence')
    need(isinstance(refs, dict) and set(refs) == {'staticBuild', 'backendReuse', 'browsers', 'releaseSafety', 'gitReview'}, 'evidence_set')
    frozen, parsed = {}, {}

    def read(ref):
        need(isinstance(ref, dict) and set(ref) == {'path', 'sha256'}, 'evidence_ref')
        name = ref['path']; relative(name)
        need(name.startswith('evidence/') and hash_string(ref['sha256']), 'evidence_path')
        raw = plain_file(candidate / name)
        need(sha(raw) == ref['sha256'], 'evidence_changed')
        frozen[name] = raw
        return raw

    for kind, ref in refs.items():
        item = json.loads(read(ref)); parsed[kind] = item
        need(item.get('verified') is True and item.get('sourceHashes') == hashes, 'evidence_source')
        need(isinstance(item.get('records'), list) and item['records'], 'original_evidence_missing')
        for record in item['records']:
            need(record['path'] != ref['path'], 'self_referencing_evidence'); read(record)
    build = parsed['staticBuild']
    need(build.get('image') == image and build.get('parentImage') == ready['previousImage']
         and build.get('manifestSha256') == ready['manifestSha256']
         and build.get('nonStaticRuntimeHashes') == backend_hashes(hashes)
         and build.get('staticHashes') == static_hashes(hashes)
         and build.get('parentLayersPreserved') is True
         and build.get('configurationUnchanged') is True and build.get('pipExecuted') is False, 'static_build')
    reuse = parsed['backendReuse']
    need(reuse.get('coverageMode') == 'unchanged-backend-dependencies'
         and reuse.get('previousImage') == ready['previousImage']
         and reuse.get('nonStaticRuntimeHashes') == backend_hashes(hashes)
         and reuse.get('singleFullRunPassed') is False, 'backend_reuse')
    for platform in ('windows', 'linux'):
        result = reuse.get(platform, {})
        need(integer(result.get('tests'), 1) and integer(result.get('passed'), 1)
             and integer(result.get('skipped')) and result['passed'] + result['skipped'] == result['tests'], 'backend_counts')
    need(reuse['windows']['tests'] == reuse['linux']['tests'], 'backend_collection')
    groups = parsed['browsers'].get('groups')
    need(isinstance(groups, list) and groups, 'browser_missing')
    scripts = []
    for group in groups:
        name = group.get('script'); scripts.append(name)
        need(isinstance(name, str) and name.startswith('tests/') and name in hashes
             and group.get('passed') is True and integer(group.get('checks'), 1)
             and type(group.get('externalRequests')) is int and group['externalRequests'] == 0, 'browser_failed')
    need(len(set(scripts)) == len(scripts), 'duplicate_browser')
    safety = parsed['releaseSafety']
    need(safety.get('realDocker') is True and safety.get('image') == image
         and safety.get('manifestSha256') == ready['manifestSha256']
         and integer(safety.get('households'), 2) and integer(safety.get('checks'), 1)
         and safety.get('originalTablesPreserved') == 43 and safety.get('newTables') == 0
         and safety.get('productionWrites') == 0 and safety.get('allPassed') is True, 'release_safety')
    review = parsed['gitReview']
    need(review.get('reviewed') is True and review.get('mainTree') == review.get('integrationTree'), 'git_unreviewed')
    for key in ('baseCommit', 'mainCommit', 'integrationCommit', 'mainTree', 'integrationTree'):
        need(isinstance(review.get(key), str) and re.fullmatch('[a-f0-9]{40}', review[key]), 'git_identity')
    need(review == ready.get('gitReview'), 'git_review_binding')
    return frozen


# All legacy code is hash-pinned before import; these two substitutions change
# only the called verifier and add an exact runtime/static file-set check.
CONTAINER_CODE = L.CONTAINER_CODE.replace('check_journey_documents_migration.py', 'check_static_release.py').replace(
    "need('environment.json' in expected)",
    "actual={p.relative_to(Path('/app')).as_posix() for p in Path('/app').glob('*.py')}\n"
    "actual.add('requirements.txt')\n"
    "actual.update(p.relative_to(Path('/app')).as_posix() for p in Path('/app/static').rglob('*') if p.is_file())\n"
    "need(actual==set(frozen['runtimeHashes']))\nneed('environment.json' in expected)")

READBACK_CODE = r'''
import hashlib,json,sys,urllib.request,urllib.error,urllib.parse
from pathlib import Path
expected=json.loads(sys.argv[1])
for name,digest in expected['runtimeHashes'].items():
    if hashlib.sha256((Path('/app')/name).read_bytes()).hexdigest()!=digest:raise RuntimeError('runtime_changed')
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*a,**k):return None
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
def read(path):
    try:
        with opener.open('http://127.0.0.1:8000'+path,timeout=20) as response:return response.status,response.read()
    except urllib.error.HTTPError as error:return error.code,b''
health,_=read('/healthz')
static={}
for name,digest in expected['staticHashes'].items():
    status,body=read('/' if name=='static/index.html' else '/'+urllib.parse.quote(name,safe='/'))
    static[name]={'status':status,'sha256':hashlib.sha256(body).hexdigest()}
anonymous={path:read(path)[0] for path in expected['anonymousPaths']}
print(json.dumps({'healthStatus':health,'staticAssets':static,'anonymousChecks':anonymous}))
'''


def verify_http(value, hashes):
    need(value.get('healthStatus') == 200, 'http_health')
    need(value.get('staticAssets') == {n: {'status': 200, 'sha256': d} for n, d in hashes.items()}, 'http_static')
    need(value.get('anonymousChecks') == {n: 401 for n in ANONYMOUS_PATHS}, 'http_anonymous')
def _activate(candidate_root, image, manifest_sha, ready_sha, *, root=ROOT, releases=RELEASES,
              project='family-dashboard', volume=VOLUME, runner=command):
    process_environment = host_environment()
    need(isinstance(project, str) and re.fullmatch('[a-z0-9][a-z0-9_-]{1,62}', project), 'project_name')
    need(volume == project + '_household-data', 'project_volume')
    candidate_root, root, releases = map(Path, (candidate_root, root, releases))
    need(root.is_absolute() and root.resolve(strict=True) == root, 'root_path')
    need(candidate_root.is_absolute() and candidate_root.resolve(strict=True) == candidate_root
         and candidate_root.parent == root.parent and candidate_root.name.startswith('family-dashboard-candidate-static-'), 'candidate_path')
    need(releases.is_absolute() and releases.parent == root.parent and not releases.is_symlink(), 'release_path')
    need(isinstance(image, str) and re.fullmatch('sha256:[a-f0-9]{64}', image), 'image_format')
    candidate, manifest_raw = read_manifest(candidate_root / 'RELEASE-MANIFEST.json', manifest_sha)
    values = source_files(candidate_root, candidate['files'])
    ready_raw = plain_file(candidate_root / 'READY.json')
    need(hash_string(ready_sha) and sha(ready_raw) == ready_sha, 'ready_changed')
    ready = json.loads(ready_raw)
    need(ready.get('verified') is True and type(ready.get('version')) is int and ready['version'] == 1 and ready.get('image') == image
         and ready.get('mode') == 'static-only' and ready.get('manifestSha256') == manifest_sha
         and ready.get('sourceHashes') == candidate['files'], 'ready_identity')
    previous = ready.get('previousImage')
    need(isinstance(previous, str) and re.fullmatch('sha256:[a-f0-9]{64}', previous) and previous != image, 'previous_image_format')
    need(ready.get('schema') == {'from': 43, 'to': 43, 'newTables': []}, 'static_contract')
    base, base_raw = read_manifest(candidate_root / 'BASE-MANIFEST.json', ready['baseManifestSha256'])
    need(ready.get('baseManifestSha256') == ready['baseManifestSha256'] and ready.get('baseHashes') == base['files']
         and base['files'], 'base_binding')
    old_values = source_files(root, base['files'])
    original_manifest = plain_file(root / 'RELEASE-MANIFEST.json')
    need(hash_string(ready.get('oldManifestSha256')) and sha(original_manifest) == ready['oldManifestSha256'], 'old_manifest_changed')
    need(set(base['files']) <= set(candidate['files']), 'source_removal')
    changed = sorted(n for n, digest in candidate['files'].items() if base['files'].get(n) != digest)
    need(changed == sorted(ready['changedFiles']), 'unreviewed_source_change')
    validate_changes(base['files'], candidate['files'], changed)
    need(all(n in values for n in REQUIRED), 'required_source_missing')
    need(all(candidate['files'][n] == digest for n, digest in DEPENDENCIES.items()), 'dependency_changed')
    need(sha(plain_file(Path(__file__))) == candidate['files'][CONTROLLER], 'controller_changed')
    for name in set(candidate['files']) - set(base['files']):
        need(not (root / name).exists() and not (root / name).is_symlink(), 'unexpected_existing_source')
    proof_bytes = evidence(candidate_root, ready, candidate['files'], image)
    environment = plain_file(root / '.env')
    need(hash_string(ready.get('environmentSha256')) and sha(environment) == ready['environmentSha256'], 'environment_changed')
    frozen = {'manifestSha256': manifest_sha, 'sourceHashes': candidate['files'], 'runtimeHashes': runtime_hashes(values)}
    compose_prefix = ['docker', 'compose', '--project-name', project,
                      '--file', str(root / 'compose.yaml'), '--env-file', str(root / '.env')]
    compose_configuration = None

    def run(args, **kwargs):
        if args[:2] == ['docker', 'compose']:
            need(plain_file(root / 'compose.yaml') == old_values['compose.yaml'], 'compose_file_changed')
            need(plain_file(root / '.env') == environment, 'environment_changed')
            if args[2] == 'up':
                current = parse_compose_config_output(runner(
                    compose_prefix + ['config', '--format', 'json'], cwd=root,
                    env=dict(process_environment)))
                need(compose_configuration is not None and encoded(current) == compose_configuration,
                     'compose_configuration_changed')
            args = compose_prefix + args[2:]
        return runner(args, cwd=root, env=dict(process_environment), **kwargs)

    def inspect(cid):
        need(re.fullmatch('[a-f0-9]{64}', cid) is not None, 'container_id')
        value = json.loads(run(['docker', 'inspect', '--format', FORMAT, cid]))
        need(value['id'] == cid, 'container_identity')
        return value

    def services():
        result = {}
        for name in ('web', 'sync', 'app'):
            ids = run(['docker', 'compose', 'ps', '-a', '-q', name]).splitlines()
            need(len(ids) == 1, 'service_not_unique')
            result[name] = inspect(ids[0])
        return result

    old = services()
    need(all(v['running'] and not v['oom'] for v in old.values()) and old['app']['health'] == 'healthy', 'services_unhealthy')
    need(old['app']['image'] == old['sync']['image'] == previous, 'previous_image_mismatch')
    for name in ('app', 'sync'):
        mounts = json.loads(run(['docker', 'inspect', '--format', '{{json .Mounts}}', old[name]['id']]))
        data_mounts = [m for m in mounts if m.get('Destination') == '/data']
        need(len(data_mounts) == 1 and data_mounts[0].get('Type') == 'volume'
             and data_mounts[0].get('Name') == volume and data_mounts[0].get('RW') is True, 'data_volume_mismatch')
    volume_users = set(run(['docker', 'ps', '-q', '--no-trunc', '--filter', 'volume=' + volume]).splitlines())
    need(volume_users == {old['app']['id'], old['sync']['id']}, 'unexpected_volume_user')
    need(run(['docker', 'image', 'inspect', '--format', '{{.Id}}', image]) == image, 'image_missing')
    parent_meta = json.loads(run(['docker', 'image', 'inspect', previous]))
    child_meta = json.loads(run(['docker', 'image', 'inspect', image]))
    verify_images(parent_meta, child_meta, previous, image)
    parsed_compose = parse_compose_config_output(run(['docker', 'compose', 'config', '--format', 'json']))
    compose_configuration = encoded(parsed_compose)
    parsed_environment = validated_environment(
        parsed_compose,
        json.loads(run(['docker', 'inspect', '--format', '{{json .Config.Env}}', old['app']['id']])))
    need(plain_file(root / '.env') == environment, 'environment_changed')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    releases.mkdir(mode=0o700, exist_ok=True)
    need(releases.resolve(strict=True) == releases, 'release_parent_symlink')
    release = releases / ('static-' + stamp)
    release.mkdir(mode=0o700)
    inputs = release / 'verification'; inputs.mkdir(mode=0o700)
    if os.name != 'nt':
        os.chown(inputs, 10001, 10001)
    input_hashes = {}
    installed = False

    def save_input(name, value):
        raw = encoded(value); put(inputs / name, raw, True); input_hashes[name] = sha(raw)

    save_input('frozen.json', frozen)
    save_input('environment.json', parsed_environment)
    save_input('compose-config.json', parsed_compose)
    put(release / '.env', environment)
    put(release / 'READY.json', ready_raw)
    put(release / 'BASE-MANIFEST.json', base_raw)
    put(release / 'original-RELEASE-MANIFEST.json', original_manifest)
    for name, raw in proof_bytes.items():
        target = release / name; target.parent.mkdir(parents=True, exist_ok=True, mode=0o700); put(target, raw)
    with tarfile.open(release / 'source-before.tar.gz', 'x:gz') as archive:
        for name, raw in {**old_values, 'RELEASE-MANIFEST.json': original_manifest}.items():
            member = tarfile.TarInfo(name); member.size = len(raw); member.mode = 0o644
            archive.addfile(member, BytesIO(raw))
    (release / 'source-before.tar.gz').chmod(0o600)
    report = {'phase': 'preflight', 'status': 'pending', 'image': image, 'previousImage': previous,
              'manifestSha256': manifest_sha, 'readySha256': ready_sha, 'baseManifestSha256': ready['baseManifestSha256'],
              'oldManifestSha256': ready['oldManifestSha256'], 'helperSha256': candidate['files'][HELPER], 'mode': 'static-only', 'releaseDirectory': str(release),
              'resolvedEnvironmentSha256': input_hashes['environment.json'], 'resolvedEnvironmentMatchesRunningApp': True,
              'resolvedComposeSha256': input_hashes['compose-config.json'], 'composeInputsExplicit': True,
              'sourceBeforeSha256': sha((release / 'source-before.tar.gz').read_bytes()),
              'commitStarted': False, 'interrupted': False, 'automaticRestoreAttempted': False,
              'project': project, 'volume': volume,
              'stops': [], 'helperContainers': [], 'helpersStoppedAfterFailure': []}

    def record():
        path = release / 'deployment.json'; path.write_bytes(encoded(report)); path.chmod(0o600)

    def phase(name):
        report['phase'] = name; report['inputHashes'] = dict(input_hashes); record()

    def unchanged():
        need(plain_file(root / '.env') == environment, 'environment_changed')
        need(plain_file(release / '.env') == environment, 'frozen_environment_changed')
        need(plain_file(candidate_root / 'READY.json') == ready_raw, 'ready_changed')
        need(plain_file(candidate_root / 'RELEASE-MANIFEST.json') == manifest_raw, 'manifest_changed')
        source_files(candidate_root, candidate['files'])
        source_files(root, candidate['files'] if installed else base['files'])
        need(plain_file(root / 'RELEASE-MANIFEST.json') == (manifest_raw if installed else original_manifest), 'root_manifest_changed')
        for name, digest in input_hashes.items():
            need(sha(plain_file(inputs / name)) == digest, 'input_changed')

    def data(action):
        unchanged()
        name = 'family-dashboard-static-check-' + stamp.lower() + '-' + str(len(report['helperContainers']))
        report['helperContainers'].append({'name': name, 'action': action}); record()
        args = ['docker', 'run', '--rm', '-i', '--name', name, '--label', 'family-dashboard.static-release=' + stamp,
                '--network', 'none', '--read-only', '--user', '10001:10001',
                '--memory', '384m', '--pids-limit', '128', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
                '--tmpfs', '/tmp:rw,nosuid,noexec,size=64m',
                '-e', 'DATA_DIR=/data', '-e', 'PYTHONDONTWRITEBYTECODE=1',
                '--mount', 'type=bind,src=' + str(candidate_root) + ',dst=/release-source,readonly',
                '--mount', 'type=bind,src=' + str(inputs) + ',dst=/release-check,readonly']
        if action != 'verify-image':
            args += ['--mount', 'type=volume,src=' + volume + ',dst=/data']
        args += [image, 'python', '-', action, encoded(input_hashes).decode()]
        result = json.loads(run(args, input_bytes=CONTAINER_CODE.encode(), timeout=300))
        unchanged()
        return result

    def stop(names):
        run(['docker', 'compose', 'stop', '--timeout', '45', *names])
        for name in names:
            state = inspect(old[name]['id']); report['stops'].append({'service': name, **state})
            need(not state['running'] and not state['oom'] and state['exitCode'] == 0, 'unclean_stop')

    def check_result(value):
        need(value.get('originalTablesPreserved') == 43 and value.get('newTables') == 0
             and value.get('schemaIndexesAndTriggersVerified') is True
             and value.get('allOriginalRowsAndSequencesPreserved') is True
             and value.get('backup') == report.get('backupVerification'), 'static_verification_failed')

    try:
        need(data('verify-image').get('imageSourceVerified') is True, 'image_source_mismatch')
        phase('stop-ingress'); report['interrupted'] = True; record(); stop(['web'])
        phase('stop-writers'); stop(['sync', 'app'])
        need(not run(['docker', 'ps', '-q', '--filter', 'volume=' + volume]), 'unexpected_volume_user')
        phase('snapshot'); save_input('before.json', data('snapshot'))
        phase('backup'); backup = data('backup'); save_input('backup.json', backup)
        phase('validate-backup'); proof = data('validate-backup')
        need(proof.get('groupVerified') is True and hash_string(proof.get('manifestSha256'))
             and integer(proof.get('databases'), 2) and proof['databases'] == backup['databases'], 'backup_not_verified')
        save_input('backup-verification.json', proof); report['backup'] = backup; report['backupVerification'] = proof
        phase('check-before-install'); initial = data('check'); check_result(initial)
        need(initial.get('backup') == proof, 'backup_changed')
        report['beforeInstallReadback'] = initial
        phase('install-source'); source_files(root, base['files'])
        need(plain_file(root / 'RELEASE-MANIFEST.json') == original_manifest, 'old_manifest_changed')
        for name in changed:
            target = root / name
            need(not target.is_symlink() and target.resolve().is_relative_to(root), 'install_symlink')
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + '.static-release-tmp')
            put(temporary, values[name]); temporary.chmod(0o755 if name.startswith('deploy/') and name.endswith('.sh') else 0o644)
            temporary.replace(target)
        temp_manifest = root / 'RELEASE-MANIFEST.static-release-tmp'
        put(temp_manifest, manifest_raw); temp_manifest.replace(root / 'RELEASE-MANIFEST.json')
        installed = True
        source_files(root, candidate['files']); unchanged()
        run(['docker', 'tag', image, project + '-app'])
        phase('start-application'); run(['docker', 'compose', 'up', '-d', '--no-build', '--no-deps', '--wait', '--wait-timeout', '180', 'app'], timeout=220)
        running = services()
        need(running['app']['running'] and running['app']['health'] == 'healthy' and not running['app']['oom']
             and running['app']['image'] == image and not running['sync']['running'] and not running['web']['running'], 'startup_unhealthy')
        phase('check-startup'); report['startupReadback'] = data('check'); check_result(report['startupReadback'])
        phase('http-readback')
        expected_http = {'runtimeHashes': frozen['runtimeHashes'], 'staticHashes': static_hashes(candidate['files']), 'anonymousPaths': ANONYMOUS_PATHS}
        report['httpReadback'] = json.loads(run(['docker', 'compose', 'exec', '-T', 'app', 'python', '-', encoded(expected_http).decode()], input_bytes=READBACK_CODE.encode(), timeout=180))
        verify_http(report['httpReadback'], expected_http['staticHashes'])
        phase('check-after-http'); report['afterHttpReadback'] = data('check'); check_result(report['afterHttpReadback'])
        source_files(root, candidate['files']); unchanged()
        phase('commit'); report['commitStarted'] = True; record()
        run(['docker', 'compose', 'up', '-d', '--no-build', '--no-deps', 'sync'])
        run(['docker', 'compose', 'up', '-d', '--no-deps', '--force-recreate', 'web'])
        run(['docker', 'compose', 'exec', '-T', 'web', 'nginx', '-t'])
        running = services()
        need(all(v['running'] and not v['oom'] for v in running.values()) and running['app']['health'] == 'healthy'
             and running['app']['image'] == running['sync']['image'] == image, 'final_services_unhealthy')
        unchanged(); source_files(root, candidate['files'])
        report.update(status='published', phase='complete', publishedAt=datetime.now(timezone.utc).isoformat(),
                      services=running, environmentPreserved=True, originalTablesPreserved=43, newTables=0,
                      stoppedDatabaseContentsPreserved=True)
        record(); return report
    except BaseException as error:
        report.update(status='failed', errorType=type(error).__name__, manualReviewRequired=report['interrupted'])
        if report['interrupted']:
            try:
                run(['docker', 'compose', 'stop', '--timeout', '45', 'web', 'sync', 'app'])
            except Exception:
                report['stopAfterFailureFailed'] = True
        # Killing a timed-out Docker client does not reliably stop its container.
        # Stop only this release's uniquely named helpers; never restore data.
        for helper in report['helperContainers']:
            try:
                ids = run(['docker', 'ps', '-a', '-q', '--no-trunc', '--filter',
                           'name=^/' + helper['name'] + '$']).splitlines()
                need(len(ids) <= 1, 'helper_not_unique')
                for cid in ids:
                    state = inspect(cid)
                    need(state['image'] == image, 'helper_image_changed')
                    labels = json.loads(run(['docker', 'inspect', '--format', '{{json .Config.Labels}}', cid]))
                    need(labels.get('family-dashboard.static-release') == stamp, 'helper_owner_changed')
                    if state['running']:
                        run(['docker', 'stop', '--time', '45', cid])
                        remaining = run(['docker', 'ps', '-a', '-q', '--no-trunc', '--filter',
                                         'name=^/' + helper['name'] + '$']).splitlines()
                        need(not remaining or (remaining == [cid] and not inspect(cid)['running']),
                             'helper_still_running')
                        report['helpersStoppedAfterFailure'].append(helper['name'])
            except Exception:
                report['helperStopAfterFailureFailed'] = True
                report['manualReviewRequired'] = True
        record()
        raise RuntimeError('release_failed_at_' + report['phase'] + '; evidence=' + str(release)) from None


@contextmanager
def release_lock(releases):
    """One process per app release root; never replaces an existing lock inode."""
    releases = Path(releases)
    need(releases.is_absolute() and not releases.is_symlink(), 'release_lock_path')
    releases.mkdir(mode=0o700, exist_ok=True)
    need(releases.resolve(strict=True) == releases, 'release_lock_path')
    path = releases / '.static-release.lock'
    need(not path.is_symlink(), 'release_lock_symlink')
    with path.open('a+b') as stream:
        path.chmod(0o600)
        if os.name == 'nt':
            import msvcrt
            if stream.seek(0, 2) == 0:
                stream.write(b'0'); stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise RuntimeError('another_static_release_running') from None
            try:
                yield
            finally:
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise RuntimeError('another_static_release_running') from None
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def activate(candidate_root, image, manifest_sha, ready_sha, *, root=ROOT, releases=RELEASES,
             project='family-dashboard', volume=VOLUME, runner=command):
    need(Path(releases).parent == Path(root).parent, 'release_path')
    with release_lock(releases):
        return _activate(candidate_root, image, manifest_sha, ready_sha, root=root, releases=releases,
                         project=project, volume=volume, runner=runner)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('image')
    parser.add_argument('manifest_sha256')
    parser.add_argument('ready_sha256')
    args = parser.parse_args(argv)

    def interrupted(*unused):
        raise RuntimeError('release_signal_interrupted')

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, interrupted)
    try:
        result = activate(args.candidate, args.image, args.manifest_sha256, args.ready_sha256)
    except BaseException:
        raise SystemExit('static_release_failed; inspect the private release record; no automatic restore') from None
    # The full private record stays on disk. No configuration values on stdout.
    print(json.dumps({k: result[k] for k in ('status', 'phase', 'image', 'publishedAt', 'releaseDirectory')}))


if __name__ == '__main__':
    main()
