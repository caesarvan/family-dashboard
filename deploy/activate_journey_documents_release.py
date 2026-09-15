"""Reviewed 42 -> 43 release controller; never restores a failed release.

CLI: python deploy/activate_journey_documents_release.py CANDIDATE IMAGE
     MANIFEST_SHA256 READY_SHA256

READY.json is externally approved by its SHA256, not by a self-declared flag.
Its evidence refs name normalized JSON envelopes under candidate/evidence/.
Every envelope has verified=true, complete sourceHashes, and nonempty records
refs to the original evidence bytes. The readiness author reviews those raw
reports; this controller checks their frozen identity, not their provenance.
No test, image build, remote connection or automatic database restore is run.
"""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile


ROOT = Path('/opt/family-dashboard')
RELEASES = Path('/opt/family-dashboard-releases')
PREVIOUS = 'sha256:f1e4cc56979f793f32585f498fa2fca55987356bd68f67e8cc6c14f0b1b6a01d'
BASE_SHA = '045ad0ac30e9130fc62c9fa0e12b7f0d2240e21feb5c352226002f4e1062a828'
OLD_MANIFEST_SHA = '4713e0a4486c3afa4fc7f73932b038dcda3df1697a408aaaa331735f099736f7'
VOLUME = 'family-dashboard_household-data'
HELPER = 'deploy/check_journey_documents_migration.py'
CONTROLLER = 'deploy/activate_journey_documents_release.py'
FORMAT = '{"id":{{json .Id}},"image":{{json .Image}},"running":{{json .State.Running}},"exitCode":{{json .State.ExitCode}},"oom":{{json .State.OOMKilled}},"health":{{with index .State "Health"}}{{json .Status}}{{else}}null{{end}}}'

# This wrapper is supplied on stdin to a fresh immutable-image container. It
# validates mounted code before executing it; it never imports the live ROOT.
CONTAINER_CODE = r'''
import hashlib,json,os,runpy,sys
from pathlib import Path
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def need(v):
    if not v:raise RuntimeError('frozen_input_mismatch')
action=sys.argv[1]; expected=json.loads(sys.argv[2]); inputs=Path('/release-check'); source=Path('/release-source')
for name,value in expected.items():need(digest(inputs/name)==value)
frozen=json.loads((inputs/'frozen.json').read_bytes())
need(digest(source/'RELEASE-MANIFEST.json')==frozen['manifestSha256'])
for name,value in frozen['sourceHashes'].items():need(digest(source/name)==value)
for name,value in frozen['runtimeHashes'].items():need(digest(Path('/app')/name)==value)
need('environment.json' in expected)
environment=json.loads((inputs/'environment.json').read_bytes())
need(isinstance(environment,dict) and environment.get('DATA_DIR')=='/data')
need(all(isinstance(k,str) and k and '=' not in k and '\x00' not in k and isinstance(v,str) and '\x00' not in v for k,v in environment.items()))
os.environ.update(environment)
if action=='verify-image':print(json.dumps({'imageSourceVerified':True}));sys.exit(0)
if 'backup-verification.json' in expected:
    backup=json.loads((inputs/'backup.json').read_bytes())
    proof=json.loads((inputs/'backup-verification.json').read_bytes())
    name=backup['manifest'];need(Path(name).name==name)
    need(digest(Path('/data/backups')/name)==proof['manifestSha256'])
sys.path.insert(0,str(source));os.environ['DATA_DIR']='/data'
if action=='backup':runpy.run_path(str(source/'deploy/backup.py'),run_name='__main__')
else:
    sys.argv=[str(source/'deploy/check_journey_documents_migration.py'),action,'--data-dir','/data','--inputs-dir',str(inputs)]
    runpy.run_path(sys.argv[0],run_name='__main__')
'''


def need(condition, label):
    if not condition:
        raise RuntimeError(label)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def hash_string(value):
    return isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value) is not None


def relative(name):
    need(isinstance(name, str) and name and '\\' not in name and ':' not in name, 'unsafe_path')
    path = PurePosixPath(name)
    need(not path.is_absolute() and all(p not in ('.', '..') for p in path.parts)
         and path.as_posix() == name, 'unsafe_path')
    need(not any(p.startswith('.env') or p in {'.git', '.venv', 'test-results', 'data'} for p in path.parts)
         and '.sqlite' not in name.lower() and 'credentials' not in name.lower(), 'private_path')
    return path


def plain_file(path):
    need(path.is_file() and not path.is_symlink(), 'file_missing_or_symlink')
    need(path.absolute() == path.resolve(strict=True), 'symlink_parent')
    return path.read_bytes()


def read_manifest(path, expected_sha):
    raw = plain_file(path)
    need(hash_string(expected_sha) and sha(raw) == expected_sha, 'manifest_changed')
    value = json.loads(raw)
    need(isinstance(value.get('files'), dict) and value['files'], 'invalid_manifest')
    for name, digest in value['files'].items():
        relative(name)
        need(hash_string(digest), 'invalid_file_digest')
    return value, raw


def source_files(directory, hashes):
    need(directory.is_dir() and directory.absolute() == directory.resolve(strict=True), 'source_directory')
    values = {}
    for name, digest in hashes.items():
        relative(name)
        value = plain_file(directory / name)
        need(sha(value) == digest, 'source_changed')
        values[name] = value
    return values


def integer(value, minimum=0):
    return type(value) is int and value >= minimum


def evidence(candidate, ready, hashes, image, schema_sha):
    """Validate normalized envelopes and preserve every referenced raw byte."""
    refs = ready['evidence']
    need(set(refs) == {'windows', 'linux', 'browsers', 'dockerRestore', 'gitReview'}, 'evidence_set')
    frozen = {}

    def read_ref(ref):
        need(isinstance(ref, dict) and set(ref) == {'path', 'sha256'}, 'evidence_ref')
        name = ref['path']; relative(name)
        need(name.startswith('evidence/') and hash_string(ref['sha256']), 'evidence_path')
        raw = plain_file(candidate / name)
        need(sha(raw) == ref['sha256'], 'evidence_changed')
        frozen[name] = raw
        return raw

    parsed = {}
    for kind, ref in refs.items():
        item = json.loads(read_ref(ref)); parsed[kind] = item
        need(item.get('verified') is True and item.get('sourceHashes') == hashes, 'evidence_source')
        need(isinstance(item.get('records'), list) and item['records'], 'original_evidence_missing')
        for record in item['records']:
            need(record['path'] != ref['path'], 'self_referencing_evidence')
            read_ref(record)
    for kind in ('windows', 'linux'):
        item = parsed[kind]
        need(item.get('exitCode') == 0 and type(item['exitCode']) is int, 'backend_exit')
        need(all(integer(item.get(k)) for k in ('passed', 'skipped', 'failed', 'errors'))
             and integer(item.get('tests'), 1), 'backend_counts')
        need(item['failed'] == item['errors'] == 0 and item['passed'] > 0
             and item['passed'] + item['skipped'] == item['tests'], 'backend_failed')
    need(parsed['windows']['tests'] == parsed['linux']['tests'], 'backend_collection_mismatch')
    need(parsed['linux'].get('image') == image
         and parsed['linux'].get('manifestSha256') == ready['manifestSha256'], 'linux_image')
    groups = parsed['browsers'].get('groups')
    need(isinstance(groups, list) and groups, 'browser_missing')
    for group in groups:
        need(group.get('passed') is True and integer(group.get('checks'), 1)
             and type(group.get('externalRequests')) is int and group['externalRequests'] == 0
             and isinstance(group.get('script'), str) and group['script'].startswith('tests/')
             and group['script'].endswith('.py') and group['script'] in hashes, 'browser_failed')
    restore = parsed['dockerRestore']
    need(restore.get('realDocker') is True and restore.get('image') == image
         and restore.get('manifestSha256') == ready['manifestSha256']
         and restore.get('schemaSha256') == schema_sha
         and integer(restore.get('restoredHouseholds'), 2), 'docker_restore_missing')
    review = parsed['gitReview']
    need(review.get('reviewed') is True and review.get('mainTree') == review.get('integrationTree'), 'git_unreviewed')
    for key in ('baseCommit', 'mainCommit', 'integrationCommit', 'mainTree', 'integrationTree'):
        need(isinstance(review.get(key), str) and re.fullmatch('[a-f0-9]{40}', review[key]), 'git_identity')
    need(review == ready['gitReview'], 'git_review_binding')
    return frozen


def runtime_hashes(values):
    # Current Dockerfile copies root Python modules, requirements and all static
    # assets. New modules omitted from COPY must fail the /app byte check.
    return {name: sha(value) for name, value in values.items()
            if (name.endswith('.py') and '/' not in name) or name.startswith('static/') or name == 'requirements.txt'}


def validated_environment(compose, running):
    """Keep Compose's parsed values exactly; never interpret dotenv ourselves."""
    need(isinstance(compose, dict) and isinstance(compose.get('services'), dict), 'compose_environment_invalid')
    application = compose['services'].get('app')
    need(isinstance(application, dict), 'compose_environment_invalid')
    environment = application.get('environment')
    need(isinstance(environment, dict) and environment.get('DATA_DIR') == '/data', 'compose_environment_invalid')
    need(all(isinstance(k, str) and k and '=' not in k and '\x00' not in k
             and isinstance(v, str) and '\x00' not in v for k, v in environment.items()), 'compose_environment_invalid')
    need(isinstance(running, list) and all(isinstance(v, str) and '=' in v for v in running), 'running_environment_invalid')
    actual = {}
    for item in running:
        key, value = item.split('=', 1)
        need(key not in actual, 'running_environment_ambiguous')
        actual[key] = value
    need(all(k in actual and actual[k] == v for k, v in environment.items()), 'running_environment_mismatch')
    return dict(environment)


def command(arguments, *, cwd, input_bytes=None, timeout=180):
    try:
        result = subprocess.run(arguments, cwd=cwd, input=input_bytes, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise RuntimeError('command_timeout') from None
    need(result.returncode == 0, 'command_failed_' + str(result.returncode))
    return result.stdout.decode('utf-8').strip()


def put(path, value, owner=False):
    need(not path.exists() and not path.is_symlink(), 'evidence_already_exists')
    with path.open('xb') as stream:
        stream.write(value)
    path.chmod(0o400 if owner else 0o600)
    if owner and os.name != 'nt':
        os.chown(path, 10001, 10001)


def activate(candidate_root, image, manifest_sha, ready_sha, *, root=ROOT, releases=RELEASES, runner=command):
    candidate_root, root, releases = map(Path, (candidate_root, root, releases))
    need(root.is_absolute() and root.resolve(strict=True) == root, 'root_path')
    need(candidate_root.is_absolute() and candidate_root.resolve(strict=True) == candidate_root
         and candidate_root.parent == root.parent and candidate_root.name.startswith('family-dashboard-candidate-journey-documents-'), 'candidate_path')
    need(releases.is_absolute() and releases.parent == root.parent and not releases.is_symlink(), 'release_path')
    need(isinstance(image, str) and re.fullmatch('sha256:[a-f0-9]{64}', image) and image != PREVIOUS, 'image_format')
    candidate, manifest_raw = read_manifest(candidate_root / 'RELEASE-MANIFEST.json', manifest_sha)
    values = source_files(candidate_root, candidate['files'])
    ready_raw = plain_file(candidate_root / 'READY.json')
    need(hash_string(ready_sha) and sha(ready_raw) == ready_sha, 'ready_changed')
    ready = json.loads(ready_raw)
    need(ready.get('verified') is True and type(ready.get('version')) is int and ready['version'] == 1 and ready.get('image') == image
         and ready.get('previousImage') == PREVIOUS and ready.get('manifestSha256') == manifest_sha
         and ready.get('sourceHashes') == candidate['files'], 'ready_identity')
    need(ready.get('migration') == {'from': 42, 'to': 43, 'newTables': ['journey_documents']}, 'migration_contract')
    base, base_raw = read_manifest(candidate_root / 'BASE-MANIFEST.json', BASE_SHA)
    need(ready.get('baseManifestSha256') == BASE_SHA and ready.get('baseHashes') == base['files']
         and len(base['files']) == 222, 'base_binding')
    old_values = source_files(root, base['files'])
    original_manifest = plain_file(root / 'RELEASE-MANIFEST.json')
    need(sha(original_manifest) == OLD_MANIFEST_SHA
         and ready.get('oldManifestSha256') == OLD_MANIFEST_SHA, 'old_manifest_changed')
    need(set(base['files']) <= set(candidate['files']), 'source_removal')
    changed = sorted(n for n, digest in candidate['files'].items() if base['files'].get(n) != digest)
    need(changed == sorted(ready['changedFiles']), 'unreviewed_source_change')
    need(not {'compose.yaml', 'requirements.txt', 'deploy/backup.py'} & set(changed), 'protected_source_change')
    need(HELPER in values and CONTROLLER in values and 'journey_documents.py' in values, 'required_source_missing')
    need(sha(plain_file(Path(__file__))) == candidate['files'][CONTROLLER], 'controller_changed')
    for name in set(candidate['files']) - set(base['files']):
        need(not (root / name).exists() and not (root / name).is_symlink(), 'unexpected_existing_source')
    tree = ast.parse(values['journey_documents.py'])
    sql = [ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
           and any(isinstance(t, ast.Name) and t.id == 'SCHEMA_SQL' for t in n.targets)]
    need(len(sql) == 1 and isinstance(sql[0], str), 'schema_missing')
    schema_sha = sha(sql[0].encode())
    need(ready.get('schemaSha256') == schema_sha and ready.get('helperSha256') == candidate['files'][HELPER], 'schema_binding')
    proof_bytes = evidence(candidate_root, ready, candidate['files'], image, schema_sha)
    environment = plain_file(root / '.env')
    need(hash_string(ready.get('environmentSha256')) and sha(environment) == ready['environmentSha256'], 'environment_changed')
    frozen = {'manifestSha256': manifest_sha, 'sourceHashes': candidate['files'], 'runtimeHashes': runtime_hashes(values)}

    def run(args, **kwargs):
        return runner(args, cwd=root, **kwargs)

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
    need(old['app']['image'] == old['sync']['image'] == PREVIOUS, 'previous_image_mismatch')
    for name in ('app', 'sync'):
        mounts = json.loads(run(['docker', 'inspect', '--format', '{{json .Mounts}}', old[name]['id']]))
        data_mounts = [m for m in mounts if m.get('Destination') == '/data']
        need(len(data_mounts) == 1 and data_mounts[0].get('Type') == 'volume'
             and data_mounts[0].get('Name') == VOLUME and data_mounts[0].get('RW') is True, 'data_volume_mismatch')
    volume_users = set(run(['docker', 'ps', '-q', '--no-trunc', '--filter', 'volume=' + VOLUME]).splitlines())
    need(volume_users == {old['app']['id'], old['sync']['id']}, 'unexpected_volume_user')
    need(run(['docker', 'image', 'inspect', '--format', '{{.Id}}', image]) == image, 'image_missing')
    parsed_environment = validated_environment(
        json.loads(run(['docker', 'compose', 'config', '--format', 'json'])),
        json.loads(run(['docker', 'inspect', '--format', '{{json .Config.Env}}', old['app']['id']])))
    need(plain_file(root / '.env') == environment, 'environment_changed')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    releases.mkdir(mode=0o700, exist_ok=True)
    need(releases.resolve(strict=True) == releases, 'release_parent_symlink')
    release = releases / ('journey-documents-' + stamp)
    release.mkdir(mode=0o700)
    inputs = release / 'verification'; inputs.mkdir(mode=0o700)
    if os.name != 'nt':
        os.chown(inputs, 10001, 10001)
    input_hashes = {}
    installed = False

    def save_input(name, value):
        raw = encoded(value); put(inputs / name, raw, True); input_hashes[name] = sha(raw)

    save_input('frozen.json', frozen)
    save_input('schema.json', {'sql': sql[0], 'sha256': schema_sha})
    save_input('environment.json', parsed_environment)
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
    report = {'phase': 'preflight', 'status': 'pending', 'image': image, 'previousImage': PREVIOUS,
              'manifestSha256': manifest_sha, 'readySha256': ready_sha, 'baseManifestSha256': BASE_SHA,
              'oldManifestSha256': OLD_MANIFEST_SHA, 'schemaSha256': schema_sha,
              'helperSha256': candidate['files'][HELPER], 'releaseDirectory': str(release),
              'resolvedEnvironmentSha256': input_hashes['environment.json'], 'resolvedEnvironmentMatchesRunningApp': True,
              'sourceBeforeSha256': sha((release / 'source-before.tar.gz').read_bytes()),
              'commitStarted': False, 'interrupted': False, 'automaticRestoreAttempted': False,
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
        name = 'family-dashboard-journey-check-' + stamp.lower() + '-' + str(len(report['helperContainers']))
        report['helperContainers'].append({'name': name, 'action': action}); record()
        args = ['docker', 'run', '--rm', '-i', '--name', name, '--network', 'none', '--read-only', '--user', '10001:10001',
                '--memory', '384m', '--pids-limit', '128', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
                '--tmpfs', '/tmp:rw,nosuid,noexec,size=64m',
                '-e', 'DATA_DIR=/data', '-e', 'PYTHONDONTWRITEBYTECODE=1',
                '--mount', 'type=bind,src=' + str(candidate_root) + ',dst=/release-source,readonly',
                '--mount', 'type=bind,src=' + str(inputs) + ',dst=/release-check,readonly']
        if action != 'verify-image':
            args += ['--mount', 'type=volume,src=' + VOLUME + ',dst=/data']
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
        need(value.get('originalTablesPreserved') == 42 and value.get('newTables') == 1
             and value.get('newTableEmpty') is True and value.get('schemaIndexesAndTriggersVerified') is True
             and value.get('allOriginalRowsAndSequencesPreserved') is True, 'migration_verification_failed')

    try:
        need(data('verify-image').get('imageSourceVerified') is True, 'image_source_mismatch')
        phase('stop-ingress'); report['interrupted'] = True; record(); stop(['web'])
        phase('stop-writers'); stop(['sync', 'app'])
        need(not run(['docker', 'ps', '-q', '--filter', 'volume=' + VOLUME]), 'unexpected_volume_user')
        phase('snapshot'); save_input('before.json', data('snapshot'))
        phase('backup'); backup = data('backup'); save_input('backup.json', backup)
        phase('validate-backup'); proof = data('validate-backup')
        need(proof.get('groupVerified') is True and hash_string(proof.get('manifestSha256'))
             and integer(proof.get('databases'), 2) and proof['databases'] == backup['databases'], 'backup_not_verified')
        save_input('backup-verification.json', proof); report['backup'] = backup; report['backupVerification'] = proof
        phase('warm'); warm = data('warm'); check_result(warm)
        need(warm.get('cloudTicks') == 0 and warm.get('backup') == proof, 'warm_backup_changed')
        report['initialization'] = warm
        phase('check-migration'); initial = data('check'); check_result(initial); report['migrationReadback'] = initial
        phase('install-source'); source_files(root, base['files'])
        need(plain_file(root / 'RELEASE-MANIFEST.json') == original_manifest, 'old_manifest_changed')
        for name in changed:
            target = root / name
            need(not target.is_symlink() and target.resolve().is_relative_to(root), 'install_symlink')
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + '.journey-release-tmp')
            put(temporary, values[name]); temporary.chmod(0o755 if name.startswith('deploy/') and name.endswith('.sh') else 0o644)
            temporary.replace(target)
        temp_manifest = root / 'RELEASE-MANIFEST.journey-release-tmp'
        put(temp_manifest, manifest_raw); temp_manifest.replace(root / 'RELEASE-MANIFEST.json')
        installed = True
        source_files(root, candidate['files']); unchanged()
        run(['docker', 'tag', image, 'family-dashboard-app'])
        phase('start-application'); run(['docker', 'compose', 'up', '-d', '--no-build', '--no-deps', '--wait', '--wait-timeout', '180', 'app'], timeout=220)
        running = services()
        need(running['app']['running'] and running['app']['health'] == 'healthy' and not running['app']['oom']
             and running['app']['image'] == image and not running['sync']['running'] and not running['web']['running'], 'startup_unhealthy')
        phase('check-startup'); report['startupReadback'] = data('check'); check_result(report['startupReadback'])
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
                      services=running, environmentPreserved=True, originalTablesPreserved=42, newTables=1,
                      stoppedDatabaseContentsPreserved=True)
        record(); return report
    except Exception as error:
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('image')
    parser.add_argument('manifest_sha256')
    parser.add_argument('ready_sha256')
    args = parser.parse_args()
    try:
        result = activate(args.candidate, args.image, args.manifest_sha256, args.ready_sha256)
    except Exception:
        # Details remain in restricted deployment.json; never print env/provider
        # output, exception payloads or tracebacks to a remote caller.
        print(json.dumps({'status': 'failed', 'manualReviewRequired': True}))
        raise SystemExit(1) from None
    print(json.dumps(result))


if __name__ == '__main__':
    main()
