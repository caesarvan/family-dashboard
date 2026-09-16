"""Dedicated 43-to-44 controller. Import is read-only; never auto-restore.

READY's externally approved SHA binds the actual installed base, exact source,
image, DDL and raw evidence. Production authorization is outside this module.
Legacy 42-to-43 and 43-to-43 policies remain unchanged.
"""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import importlib.util
from io import BytesIO
import json
import os
from pathlib import Path
import re
import signal
import tarfile
import xml.etree.ElementTree as ET


ROOT = Path('/opt/family-dashboard')
RELEASES = Path('/opt/family-dashboard-releases')
VOLUME = 'family-dashboard_household-data'
CONTROLLER = 'deploy/activate_journey_places_release.py'
HELPER = 'deploy/check_journey_places_migration.py'
BUILDER = 'deploy/build_journey_places_release.py'
DEPENDENCIES = {
    'deploy/release_core.py': '845ef1897d91fe253683874412363668a9ede9a6756b82c4af496eda3a82ad5c',
    'deploy/activate_journey_documents_release.py': '703a1540f7a632301382ec32aaee3b68e2c2157943469a71492a0d1a9e75972c',
    'deploy/check_journey_documents_migration.py': '11adc9f40bf68aaca7015f3c9f18f92c7aa648b6c379b0812b60b5d22cd2781f',
    'deploy/build_static_release.py': '7304a4341b46cc6e275b6ecfe4c400c8d49207e7ec8dc2f325df8888621f70b6',
}
DEVELOPMENT_TOOLS = {'tools/inference_orchestrator/' + name + '.py'
                     for name in ('__init__', '__main__', 'client', 'runner')}
TOOLS = {CONTROLLER, HELPER, BUILDER, 'deploy/prepare_release.py'}
REQUIRED = {*DEPENDENCIES, *TOOLS, *DEVELOPMENT_TOOLS, 'DESIGN.md', 'journey_places.py',
            'journey_documents.py', 'deploy/backup.py', 'app.py', 'requirements.txt', 'Dockerfile', 'compose.yaml'}
SCHEMA_CONTRACT = {'from': 43, 'to': 44, 'newTables': ['journey_places']}


def load_core():
    root = Path(__file__).resolve().parents[1]
    for name, digest in DEPENDENCIES.items():
        path = root / name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError('places_release_dependency_changed')
    spec = importlib.util.spec_from_file_location('places_pinned_core', root / 'deploy/release_core.py')
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


C = load_core()
need, sha, encoded = C.need, C.sha, C.encoded
hash_string, relative, plain_file = C.hash_string, C.relative, C.plain_file
read_manifest, integer = C.read_manifest, C.integer
parse_compose_config_output, validated_environment = C.parse_compose_config_output, C.validated_environment
put, runtime_hashes, FORMAT = C.put, C.runtime_hashes, C.FORMAT
command, host_environment, release_lock = C.command, C.host_environment, C.release_lock
verify_images, static_hashes, backend_hashes, runtime_changes = C.verify_images, C.static_hashes, C.backend_hashes, C.runtime_changes


class PlacesPolicy:
    prefix = 'journey-places'
    mode = 'journey-places-migration'
    entry = CONTROLLER


POLICY = PlacesPolicy()
ANONYMOUS_PATHS = C.ANONYMOUS_PATHS + ['/api/journey-places', '/api/journey-places/' + '0' * 24]


def source_files(directory, hashes):
    values = C.source_files(directory, hashes)
    # The development package is delivered as source only. No arbitrary tools
    # subtree, ignored outputs, caches, plans or local job databases are allowed.
    tools = {p.relative_to(directory).as_posix() for p in (directory / 'tools').rglob('*')
             if (p.is_file() or p.is_symlink()) and '__pycache__' not in p.parts}
    need(tools <= DEVELOPMENT_TOOLS and tools <= set(hashes), 'unlisted_development_source')
    need(all(n in DEVELOPMENT_TOOLS for n in hashes if n.startswith('tools/')), 'development_source_allowlist')
    if (directory / 'DESIGN.md').exists():
        need('DESIGN.md' in hashes, 'unlisted_design_source')
    return values


def bind_modules(values):
    root = Path(__file__).resolve().parents[1]
    for name in {CONTROLLER, HELPER, BUILDER, *DEPENDENCIES}:
        need(values.get(name) == plain_file(root / name), 'places_tool_source_changed')


def validate_changes(base, candidate, changed):
    need(set(base) <= set(candidate), 'source_removal')
    need(changed == sorted(n for n, d in candidate.items() if base.get(n) != d), 'source_change_set')
    need(set(backend_hashes(candidate)) - set(backend_hashes(base)) == {'journey_places.py'}, 'new_backend_file_set')
    need('journey_places.py' not in base and REQUIRED <= set(candidate), 'required_places_source')
    for name in changed:
        allowed = (('/' not in name and name.endswith('.py') and (name in base or name == 'journey_places.py'))
                   or name.startswith('static/') or name in {'README.md', 'DESIGN.md', 'Dockerfile', 'docs/contract-inventory.json'}
                   or name.startswith('docs/') and name.endswith('.md')
                   or name.startswith('tests/') and name.endswith('.py')
                   or name in TOOLS | DEVELOPMENT_TOOLS)
        need(allowed, 'protected_source_change')
    need(all(candidate.get(n) == base.get(n) for n in ('requirements.txt', 'compose.yaml', 'deploy/backup.py')), 'protected_runtime_change')
    need(all(candidate.get(n) == digest for n, digest in DEPENDENCIES.items()), 'dependency_changed')


def schema_definition(values):
    tree = ast.parse(values['journey_places.py'])
    sql = [ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
           and any(isinstance(t, ast.Name) and t.id == 'SCHEMA_SQL' for t in n.targets)]
    need(len(sql) == 1 and isinstance(sql[0], str), 'schema_missing')
    return {'sql': sql[0], 'sha256': sha(sql[0].encode())}


def evidence(candidate, ready, hashes, image):
    refs = ready.get('evidence')
    need(isinstance(refs, dict) and set(refs) == {'placesBuild', 'windows', 'linux', 'browsers', 'migrationSafety', 'dockerRestore', 'gitReview'}, 'evidence_set')
    frozen, parsed = {}, {}
    def read(ref):
        need(isinstance(ref, dict) and set(ref) == {'path', 'sha256'}, 'evidence_ref')
        name = ref['path']; relative(name)
        need(name.startswith('evidence/') and hash_string(ref['sha256']), 'evidence_path')
        raw = plain_file(candidate / name)
        need(sha(raw) == ref['sha256'], 'evidence_changed'); frozen[name] = raw
        return raw
    for kind, ref in refs.items():
        value = json.loads(read(ref)); parsed[kind] = value
        need(value.get('verified') is True and value.get('sourceHashes') == hashes, 'evidence_source')
        need(isinstance(value.get('records'), list) and value['records'], 'raw_evidence_missing')
        for record in value['records']:
            need(record['path'] != ref['path'], 'self_referencing_evidence'); read(record)
    build = parsed['placesBuild']
    need(build.get('image') == image and build.get('parentImage') == ready['previousImage']
         and build.get('mode') == POLICY.mode and build.get('manifestSha256') == ready['manifestSha256']
         and build.get('baseManifestSha256') == ready['baseManifestSha256']
         and build.get('parentRuntimeHashes') == {**backend_hashes(ready['baseHashes']), **static_hashes(ready['baseHashes'])}
         and build.get('candidateRuntimeHashes') == {**backend_hashes(hashes), **static_hashes(hashes)}
         and build.get('runtimeChanges') == ready['approvedRuntimeChanges']
         and all(build.get(k) is True for k in ('parentLayersPreserved', 'configurationUnchanged', 'parentBackendVerified',
                                               'childBackendVerified', 'staticVerified', 'bytecodeExcluded'))
         and build.get('pipExecuted') is False, 'places_build')
    for platform in ('windows', 'linux'):
        value = parsed[platform]
        need(type(value.get('exitCode')) is int and value['exitCode'] == 0, 'backend_exit')
        scripts = value.get('scripts')
        need(isinstance(scripts, list) and scripts and len(scripts) == len(set(scripts))
             and all(isinstance(n, str) and n.startswith('tests/test_') and n.endswith('.py') and n in hashes for n in scripts), 'test_scripts')
        cases = list(ET.fromstring(read(value['junit'])).iter('testcase'))
        counts = {'tests':len(cases), 'skipped':sum(c.find('skipped') is not None for c in cases),
                  'failed':sum(c.find('failure') is not None for c in cases), 'errors':sum(c.find('error') is not None for c in cases)}
        counts['passed'] = counts['tests'] - counts['skipped'] - counts['failed'] - counts['errors']
        need(counts['passed'] > 0 and counts['failed'] == counts['errors'] == 0
             and all(type(value.get(k)) is int and value[k] == v for k,v in counts.items()), 'backend_junit')
        need(all(any(c.get('classname','') == n[:-3].replace('/','.') or c.get('classname','').startswith(n[:-3].replace('/','.')+'.') for c in cases) for n in scripts), 'backend_junit_scope')
        read(value['log'])
        if platform == 'linux': need(value.get('image') == image, 'linux_image')
    need(parsed['windows']['scripts'] == parsed['linux']['scripts'] and parsed['windows']['tests'] == parsed['linux']['tests'], 'platform_collection')
    groups = parsed['browsers'].get('groups')
    need(isinstance(groups, list) and groups, 'browser_missing')
    for group in groups:
        need(group.get('script') in hashes and group['script'].startswith('tests/') and group.get('passed') is True
             and integer(group.get('checks'), 1) and type(group.get('externalRequests')) is int and group['externalRequests'] == 0, 'browser_failed')
    for kind in ('migrationSafety', 'dockerRestore'):
        value = parsed[kind]
        need(value.get('realDocker') is True and value.get('image') == image
             and value.get('manifestSha256') == ready['manifestSha256'] and value.get('schemaSha256') == ready['schemaSha256']
             and integer(value.get('households'), 2) and integer(value.get('checks'), 1)
             and value.get('productionWrites') == 0 and type(value['productionWrites']) is int and value.get('allPassed') is True, 'docker_evidence')
    need(parsed['migrationSafety'].get('originalTablesPreserved') == 43 and parsed['migrationSafety'].get('newTables') == 1
         and parsed['migrationSafety'].get('newTableEmpty') is True, 'migration_evidence')
    need(parsed['dockerRestore'].get('householdTables') == 44 and parsed['dockerRestore'].get('placesRestored') is True
         and parsed['dockerRestore'].get('oldSessionsRevoked') is True, 'restore_evidence')
    review = parsed['gitReview']
    need(review.get('reviewed') is True and review.get('mainTree') == review.get('integrationTree')
         and review == ready.get('gitReview') and review.get('approvedRuntimeChanges') == ready['approvedRuntimeChanges'], 'git_review')
    for key in ('baseCommit','mainCommit','integrationCommit','mainTree','integrationTree'):
        need(isinstance(review.get(key), str) and re.fullmatch('[a-f0-9]{40}', review[key]), 'git_identity')
    return frozen


RUNTIME_BOUNDARY = C.BYTECODE_CHECK + '''
if any((Path('/app') / name).exists() for name in ('tools', 'DESIGN.md')):
    raise RuntimeError('development_source_in_runtime')
'''
CONTAINER_CODE = RUNTIME_BOUNDARY + C.CONTAINER_CODE.replace('check_static_release.py', 'check_journey_places_migration.py')
READBACK_CODE = RUNTIME_BOUNDARY + C.READBACK_CODE


def verify_http(value, hashes):
    need(value.get('healthStatus') == 200, 'http_health')
    need(value.get('staticAssets') == {n: {'status': 200, 'sha256': d} for n,d in hashes.items()}, 'http_static')
    need(value.get('anonymousChecks') == {n: 401 for n in ANONYMOUS_PATHS}, 'http_anonymous')


def _activate(candidate_root, image, manifest_sha, ready_sha, *, root=ROOT, releases=RELEASES,
              project='family-dashboard', volume=VOLUME, runner=command):
    policy = POLICY
    process_environment = host_environment()
    need(isinstance(project, str) and re.fullmatch('[a-z0-9][a-z0-9_-]{1,62}', project), 'project_name')
    need(volume == project + '_household-data', 'project_volume')
    candidate_root, root, releases = map(Path, (candidate_root, root, releases))
    need(root.is_absolute() and root.resolve(strict=True) == root, 'root_path')
    need(candidate_root.is_absolute() and candidate_root.resolve(strict=True) == candidate_root
         and candidate_root.parent == root.parent and candidate_root.name.startswith('family-dashboard-candidate-' + policy.prefix + '-'), 'candidate_path')
    need(releases.is_absolute() and releases.parent == root.parent and not releases.is_symlink(), 'release_path')
    need(isinstance(image, str) and re.fullmatch('sha256:[a-f0-9]{64}', image), 'image_format')
    candidate, manifest_raw = read_manifest(candidate_root / 'RELEASE-MANIFEST.json', manifest_sha)
    values = source_files(candidate_root, candidate['files'])
    ready_raw = plain_file(candidate_root / 'READY.json')
    need(hash_string(ready_sha) and sha(ready_raw) == ready_sha, 'ready_changed')
    ready = json.loads(ready_raw)
    need(ready.get('verified') is True and type(ready.get('version')) is int and ready['version'] == 1 and ready.get('image') == image
         and ready.get('mode') == policy.mode and ready.get('manifestSha256') == manifest_sha
         and ready.get('sourceHashes') == candidate['files'], 'ready_identity')
    previous = ready.get('previousImage')
    need(isinstance(previous, str) and re.fullmatch('sha256:[a-f0-9]{64}', previous) and previous != image, 'previous_image_format')
    need(ready.get('schema') == SCHEMA_CONTRACT, 'places_contract')
    base, base_raw = read_manifest(candidate_root / 'BASE-MANIFEST.json', ready['baseManifestSha256'])
    need(ready.get('baseHashes') == base['files']
         and base['files'], 'base_binding')
    old_values = source_files(root, base['files'])
    original_manifest = plain_file(root / 'RELEASE-MANIFEST.json')
    need(hash_string(ready.get('oldManifestSha256')) and sha(original_manifest) == ready['oldManifestSha256'], 'old_manifest_changed')
    need(set(base['files']) <= set(candidate['files']), 'source_removal')
    changed = sorted(n for n, digest in candidate['files'].items() if base['files'].get(n) != digest)
    need(changed == sorted(ready['changedFiles']), 'unreviewed_source_change')
    validate_changes(base['files'], candidate['files'], changed)
    need(ready.get('approvedRuntimeChanges') == runtime_changes(base['files'], candidate['files']), 'runtime_approval')
    need(all(n in values for n in REQUIRED | {policy.entry}), 'required_source_missing')
    need(all(candidate['files'][n] == digest for n, digest in DEPENDENCIES.items()), 'dependency_changed')
    bind_modules(values)
    for name in set(candidate['files']) - set(base['files']):
        need(not (root / name).exists() and not (root / name).is_symlink(), 'unexpected_existing_source')
    temporaries = [(root / name).with_name(Path(name).name + '.journey-places-release-tmp') for name in changed]
    temporaries.append(root / 'RELEASE-MANIFEST.journey-places-release-tmp')
    need(all(not p.exists() and not p.is_symlink() and p.resolve().is_relative_to(root) for p in temporaries),
         'existing_or_unsafe_install_temporary')
    definition = schema_definition(values)
    need(ready.get('schemaSha256') == definition['sha256'] and ready.get('helperSha256') == candidate['files'][HELPER], 'schema_binding')
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
    effective = dict(s.split('=', 1) for s in child_meta[0]['Config'].get('Env', []))
    effective.update(parsed_environment)
    need(effective.get('PYTHONDONTWRITEBYTECODE') == '1'
         and not effective.get('PYTHONPYCACHEPREFIX'), 'source_bytecode_environment')
    need(plain_file(root / '.env') == environment, 'environment_changed')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    releases.mkdir(mode=0o700, exist_ok=True)
    need(releases.resolve(strict=True) == releases, 'release_parent_symlink')
    release = releases / (policy.prefix + '-' + stamp)
    release.mkdir(mode=0o700)
    inputs = release / 'verification'; inputs.mkdir(mode=0o700)
    if os.name != 'nt':
        os.chown(inputs, 10001, 10001)
    input_hashes = {}
    installed = False

    def save_input(name, value):
        raw = encoded(value); put(inputs / name, raw, True); input_hashes[name] = sha(raw)

    save_input('frozen.json', frozen)
    save_input('schema.json', definition)
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
              'schemaSha256': definition['sha256'], 'oldManifestSha256': ready['oldManifestSha256'], 'helperSha256': candidate['files'][HELPER], 'mode': policy.mode, 'releaseDirectory': str(release),
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
        name = 'family-dashboard-' + policy.prefix + '-check-' + stamp.lower() + '-' + str(len(report['helperContainers']))
        report['helperContainers'].append({'name': name, 'action': action}); record()
        args = ['docker', 'run', '--rm', '-i', '--name', name, '--label', 'family-dashboard.' + policy.prefix + '-release=' + stamp,
                '--network', 'none', '--read-only', '--user', '10001:10001',
                '--memory', '384m', '--pids-limit', '128', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
                '--tmpfs', '/tmp:rw,nosuid,noexec,size=64m',
                '-e', 'DATA_DIR=/data', '-e', 'PYTHONDONTWRITEBYTECODE=1',
                '--mount', 'type=bind,src=' + str(candidate_root) + ',dst=/release-source,readonly',
                '--mount', 'type=bind,src=' + str(inputs) + ',dst=/release-check,readonly']
        if action != 'verify-image':
            args += ['--mount', 'type=volume,src=' + volume + ',dst=/data']
        args += [image, 'python', '-', action, encoded(input_hashes).decode()]
        program = CONTAINER_CODE
        result = json.loads(run(args, input_bytes=program.encode(), timeout=300))
        unchanged()
        return result

    def stop(names):
        run(['docker', 'compose', 'stop', '--timeout', '45', *names])
        for name in names:
            state = inspect(old[name]['id']); report['stops'].append({'service': name, **state})
            need(not state['running'] and not state['oom'] and state['exitCode'] == 0, 'unclean_stop')

    def check_result(value):
        need(value.get('originalTablesPreserved') == 43 and value.get('newTables') == 1 and value.get('newTableEmpty') is True
             and value.get('schemaIndexesAndTriggersVerified') is True
             and value.get('allOriginalRowsAndSequencesPreserved') is True
             and value.get('backup') == report.get('backupVerification'), 'places_verification_failed')

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
        phase('warm'); warm = data('warm'); check_result(warm)
        need(warm.get('cloudTicks') == 0 and warm.get('modelRequests') == 0, 'warm_external_io')
        report['initialization'] = warm
        phase('check-before-install'); initial = data('check'); check_result(initial)
        need(initial.get('backup') == proof, 'backup_changed')
        report['beforeInstallReadback'] = initial
        phase('install-source'); source_files(root, base['files'])
        need(plain_file(root / 'RELEASE-MANIFEST.json') == original_manifest, 'old_manifest_changed')
        for name in changed:
            target = root / name
            need(not target.is_symlink() and target.resolve().is_relative_to(root), 'install_symlink')
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + '.' + policy.prefix + '-release-tmp')
            need(not temporary.exists() and not temporary.is_symlink(), 'existing_install_temporary')
            put(temporary, values[name]); temporary.chmod(0o755 if name.startswith('deploy/') and name.endswith('.sh') else 0o644)
            temporary.replace(target)
        temp_manifest = root / ('RELEASE-MANIFEST.' + policy.prefix + '-release-tmp')
        need(not temp_manifest.exists() and not temp_manifest.is_symlink(), 'existing_manifest_temporary')
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
        program = READBACK_CODE
        report['httpReadback'] = json.loads(run(['docker', 'compose', 'exec', '-T', 'app', 'python', '-', encoded(expected_http).decode()], input_bytes=program.encode(), timeout=180))
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
                      services=running, environmentPreserved=True, originalTablesPreserved=43, newTables=1,
                      stoppedDatabaseContentsPreserved=True)
        report['bytecodeExcluded'] = True
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
                    need(labels.get('family-dashboard.' + policy.prefix + '-release') == stamp, 'helper_owner_changed')
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


def activate(candidate_root, image, manifest_sha, ready_sha, *, root=ROOT, releases=RELEASES,
             project='family-dashboard', volume=VOLUME, runner=command):
    need(Path(releases).parent == Path(root).parent, 'release_path')
    # Shared lock serializes against existing static/source controllers too.
    with release_lock(releases):
        return _activate(candidate_root, image, manifest_sha, ready_sha, root=root, releases=releases,
                         project=project, volume=volume, runner=runner)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('image')
    parser.add_argument('manifest_sha256')
    parser.add_argument('ready_sha256')
    args = parser.parse_args()
    def interrupted(*unused):
        raise RuntimeError('places_release_interrupted')
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, interrupted)
    try:
        result = activate(args.candidate, args.image, args.manifest_sha256, args.ready_sha256)
    except Exception:
        print(json.dumps({'status':'failed', 'manualReviewRequired':True}))
        raise SystemExit(1) from None
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
