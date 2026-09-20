"""Isolated real five-service 73-to-73 controller rehearsal, never production admission.

Reuse the reviewed transport, budgets, locks and documented complete-group restore.
Only fixture identities/TLS and a stopped synthetic sentinel fault are adapted.
"""
import argparse
from contextlib import contextmanager, closing
from datetime import datetime, timedelta, timezone
import copy
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import sys
import time

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy import media_video_controller_rehearsal as old
from deploy import activate_local_photo_release as entry
from deploy import prepare_local_photo_activation as admission
from deploy import build_local_photo_release as package
from deploy import media_video_release_data as data
from deploy import membership_release_data as core
from deploy.git_blobs import read_git_blobs

control, lifecycle, policy, common = old.controller, old.lifecycle, old.policy, old.common
need, sha, encoded, save, safe, tree = old.need, old.sha, old.encoded, old.save, old.safe, old.tree
BASE = '88524d58ef9d2d54a5b7e3df7f86328601f9f5da'
SELF = 'deploy/local_photo_controller_rehearsal.py'
ADDITIONS = {SELF, 'tests/test_local_photo_controller_rehearsal.py', 'docs/LOCAL-PHOTO-CONTROLLER-REHEARSAL.md'}
BUILD_FIX = {'deploy/membership_release_build.py', 'tests/test_membership_release_build.py', 'docs/LOCAL-PHOTO-RELEASE.md'}
LAB = Path('/tmp/family-dashboard-local-photo-controller-rehearsal')
HOST = 'local-photo-rehearsal.invalid'
MARKER = sha(old.seed.SYNTHETIC_MARKER)
SENTINEL = 'synthetic-local-photo-preservation'
ORIGINAL_NGINX = package.NGINX_BEFORE
REQUIRED_NONEMPTY = ('media_items', 'media_video_cache', 'media_playback_progress', 'task_reminders', 'task_reminder_operations')


@contextmanager
def bindings(values):
    previous = [(module, name, getattr(module, name)) for module, name, value in values]
    try:
        for module, name, value in values: setattr(module, name, value)
        yield
    finally:
        for module, name, value in reversed(previous): setattr(module, name, value)


def source_scope(before, after, allowed, *, required=()):
    changed = {n for n in before.keys() | after.keys() if before.get(n) != after.get(n)}
    need(changed <= set(allowed) and set(required) <= changed and not before.keys()-after.keys(), 'source_scope_changed')
    return sorted(changed)


def checked_build(folder, digest, verified, package_digest):
    folder = safe(folder, exists=True); value = control.read(folder/'build.json', digest)
    meta = verified['metadata']
    need(value.get('exitCode') == 0 and value.get('productionOperations') is False and
         value.get('sourceHead') == meta['sourceHead'] and value.get('tree') == meta['tree'] and
         value.get('packageSha256') == package_digest and value.get('manifestSha256') == meta['manifestSha256'] and
         value.get('parentImage') == package.PARENT_IMAGE and value.get('addedLayers') == 2 and
         value.get('runtimeHashes') == meta['runtimeFiles'] and isinstance(value.get('parentConfig'), dict), 'build_binding_changed')
    admission.plan_images({'images': {'app': value['imageId'], 'decoder': package.DECODER_IMAGE}})
    need((folder/'image-id').read_text().strip() == value['imageId'] and
         tree(folder/'context/runtime') == meta['runtimeFiles'] and
         sha(control.regular(folder/'context/Dockerfile').read_bytes()) == value['dockerfileSha256'], 'build_context_changed')
    records = control.read(folder/'commands.json')['commands']
    need(records and all(c.get('exitCode') == 0 for c in records), 'build_commands_failed')
    allowed = {'build.json', 'build.log', 'commands.json', 'image-id', 'context/Dockerfile'}
    allowed.update('context/runtime/'+n for n in meta['runtimeFiles'])
    for index, record in enumerate(records):
        need(record['stdout'] == 'commands/%03d.stdout' % index and record['stderr'] == 'commands/%03d.stderr' % index,
             'build_log_path_changed')
        need(control.read(folder/('commands/%03d.json' % index)) == record, 'build_command_changed')
        control.regular(folder/control.relative(record['stdout']))
        control.regular(folder/control.relative(record['stderr']))
        allowed.update({'commands/%03d.json' % index, record['stdout'], record['stderr']})
    need(set(tree(folder)) == allowed, 'unexpected_build_artifact')
    return value


# The parent app creates both households and all schema via real login/invite APIs.
# These explicitly synthetic rows test persistence, not actual video decoding.
POPULATE = r'''
nonempty={}
for relative in counts:
 with closing(sqlite3.connect(root/relative)) as con:
  con.executescript("""
INSERT INTO settings(id,data) VALUES('synthetic-local-photo-preservation','{"value":"before"}');
INSERT INTO task_reminders VALUES('member1','synthetic-gone','2026-01-01','read',NULL,3,0,'now','now');
INSERT INTO task_reminder_operations VALUES('member1','synthetic-read','digest','{"revision":3}','now');
INSERT INTO media_imports(id,owner,request_id,request_key,state,created_at,updated_at,expires_at,confirm_request_id,confirm_key,context_cipher)
 VALUES('synthetic-import','member1','selection','digest','confirmed',1,2,3,'confirmation','confirm-digest',X'ABCD');
INSERT INTO media_items(id,owner,import_id,source_key,state,visibility,metadata_cipher,preview_cipher,preview_key,created_at,updated_at,confirmed_at)
 VALUES('synthetic-private','member1','synthetic-import','source1','ready','private',X'AB',X'CD','preview1',1,2,2),
 ('synthetic-shared','member1','synthetic-import','source2','ready','shared',X'EF',X'12','preview2',1,2,2);
INSERT INTO devices(id,secret_hash,name,approved,expires,created_at) VALUES('synthetic-tv','synthetic','Synthetic TV',1,9999999999,'now');
INSERT INTO media_tv_grants VALUES('synthetic-shared','synthetic-tv','member1',1);
INSERT INTO media_playback VALUES('synthetic-tv','photos',0,10,0,1,1,1);
INSERT INTO media_video_cache VALUES('synthetic-shared','video',X'010203',1);
INSERT INTO media_playback_progress VALUES('synthetic-tv','synthetic-shared',1,'111111111111111111111111',2500,3,2);
""")
  con.commit(); assert con.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]==0
  nonempty[relative]={name:con.execute('SELECT count(*) FROM '+name).fetchone()[0] for name in
   ('media_items','media_video_cache','media_playback_progress','task_reminders','task_reminder_operations')}
  assert all(nonempty[relative].values())
with (proof/'nonempty-seed.json').open('x') as f: json.dump(nonempty,f)
with (root/'membership-release-attempt.json').open('xb') as f:f.write(MARKER_BYTES)
(root/'membership-release-attempt.json').chmod(0o600)
print(json.dumps({'seeded':True,'households':2,'databases':3,'householdTables':73,'platformTables':9,'nonempty':nonempty}))
'''


def seed_program():
    value = old.seed.SEED_PROGRAM.replace('len(tables)==61', 'len(tables)==73')
    last = "print(json.dumps({'seeded':True,'households':2,'databases':3,'householdTables':61,'platformTables':9}))"
    need(value.count(last) == 1, 'seed_anchor_changed')
    return ("from pathlib import Path\nroot=Path('/data');proof=Path('/proof');runtime=Path('/app')\n" +
            value.replace(last, '') + '\nMARKER_BYTES='+repr(old.seed.SYNTHETIC_MARKER)+'\n'+POPULATE)


def prepare(repo, head, package_dir, package_sha256, build_dir, build_sha256, output_dir):
    repo = safe(repo, exists=True); git_tree = policy.identity(repo, head)
    baseline = read_git_blobs(repo, BASE, sorted(policy.tracked_files(repo, BASE)))
    current = read_git_blobs(repo, head, sorted(policy.tracked_files(repo, head)))
    tool_delta = source_scope(baseline, current, ADDITIONS, required=ADDITIONS)
    need(all(policy.plain(repo/n) == raw for n, raw in current.items()), 'working_source_changed')
    verified = package.verify_package(package_dir, package_sha256); meta = verified['metadata']
    package_git = read_git_blobs(repo, meta['sourceHead'], sorted(policy.tracked_files(repo, meta['sourceHead'])))
    package_delta = source_scope(baseline, package_git, BUILD_FIX | ADDITIONS)
    need(all(package_git[n] == raw for n, raw in verified['blobs'].items() if not n.startswith('static/experience/')),
         'package_git_changed')
    built = checked_build(build_dir, build_sha256, verified, package_sha256)
    target = safe(output_dir)
    for path in (repo, safe(package_dir, exists=True), safe(build_dir, exists=True)):
        need(not target.is_relative_to(path) and not path.is_relative_to(target), 'input_output_overlap')
    need(not target.exists(), 'exclusive_output_required'); target.mkdir(mode=0o755, parents=True)
    operators = {n: raw for n, raw in verified['blobs'].items() if n.endswith('.py') and (n.startswith('deploy/') or '/' not in n)}
    operators[SELF] = current[SELF]
    parent = read_git_blobs(repo, package.INSTALLED_SOURCE, ['app.py', 'requirements.txt'])
    for prefix, values in (('operator', operators), ('parent', parent)):
        for name, raw in values.items(): save(target/prefix/name, raw, 0o644)
    for prefix, origin in (('package', Path(package_dir)), ('build', Path(build_dir))):
        for name in tree(origin): save(target/prefix/name, control.regular(origin/name).read_bytes(), 0o644)
    restore_program, _ = old.restore.documented_programs(repo)
    save(target/'restore.py', restore_program.encode(), 0o644)
    save(target/'seed.py', seed_program().encode(), 0o644)
    meta_input = {'kind': 'local-photo-controller-rehearsal-v1', 'head': head, 'tree': git_tree, 'base': BASE,
        'toolDelta': tool_delta, 'packageDelta': package_delta, 'sourceHead': meta['sourceHead'], 'sourceTree': meta['tree'],
        'packageSha256': package_sha256, 'buildSha256': build_sha256,
        'images': {'app': built['imageId'], 'decoder': package.DECODER_IMAGE, 'parent': package.PARENT_IMAGE, 'web': lifecycle.WEB_IMAGE},
        'limitsMiB': old.LIMITS, 'budget': old.BUDGET, 'files': tree(target), 'productionOperations': False}
    for path in target.rglob('*'):
        if path.is_dir(): path.chmod(0o755)
    save(target/'input.json', meta_input, 0o644)
    return {'prepared': True, 'inputSha256': sha((target/'input.json').read_bytes()), 'files': len(meta_input['files']), 'dockerExecuted': False}


def verify(bundle, input_sha256):
    bundle = safe(bundle, exists=True); meta = control.read(bundle/'input.json', input_sha256)
    need(meta['kind'] == 'local-photo-controller-rehearsal-v1' and meta['base'] == BASE and
         set(meta['toolDelta']) == ADDITIONS and set(meta['packageDelta']) <= BUILD_FIX | ADDITIONS and
         meta['limitsMiB'] == old.LIMITS and meta['budget'] == old.BUDGET and meta['productionOperations'] is False,
         'rehearsal_contract_changed')
    need(tree(bundle) == {**meta['files'], 'input.json': input_sha256}, 'rehearsal_bytes_changed')
    executing = Path(__file__).resolve().parents[1]
    for name, digest in meta['files'].items():
        if name.startswith('operator/'):
            need(sha(control.regular(executing/name.removeprefix('operator/')).read_bytes()) == digest, 'executing_operator_differs')
    verified = package.verify_package(bundle/'package', meta['packageSha256'])
    built = checked_build(bundle/'build', meta['buildSha256'], verified, meta['packageSha256'])
    need(meta['sourceHead'] == verified['metadata']['sourceHead'] and meta['sourceTree'] == verified['metadata']['tree'] and
         meta['images'] == {'app': built['imageId'], 'decoder': package.DECODER_IMAGE,
                            'parent': package.PARENT_IMAGE, 'web': lifecycle.WEB_IMAGE}, 'images_or_source_changed')
    need((bundle/'seed.py').read_bytes() == seed_program().encode(), 'seed_program_changed')
    return bundle, meta, verified, built


def tls_files():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, HOST)])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5))
        .not_valid_after(now+timedelta(days=2)).add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(HOST)]), critical=False).sign(key, hashes.SHA256()))
    return {'deploy/rehearsal-cert.pem': cert.public_bytes(serialization.Encoding.PEM),
            'deploy/rehearsal-key.pem': key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())}


def composition(project, candidate, port):
    value = old.composition(project, True, port)  # Both sides have all five services.
    for name in ('app', 'sync', 'media'): value['services'][name]['image'] = old.IMAGES['app' if candidate else 'parent']
    web = value['services']['web']; web['ports'] = [f'127.0.0.1:{port}:443']
    web['volumes'] += ['./deploy/rehearsal-cert.pem:/fixture/cert.pem:ro', './deploy/rehearsal-key.pem:/fixture/key.pem:ro']
    return value


def inject_sentinel(root, evidence):
    """Call only after actual stopped-writer proof; modify one synthetic row."""
    paths = core.enumerate_databases(root)
    secondary = [name for name in paths if name.startswith('spaces/')]
    need(len(paths) == 3 and len(secondary) == 1, 'synthetic_group_required')
    target = safe(root/secondary[0]); control.regular(target)
    before = {n: sha(control.regular(root/n).read_bytes()) for n in paths}
    need(not any(Path(str(target)+suffix).exists() for suffix in ('-wal', '-shm', '-journal')), 'sentinel_database_not_stopped')
    with closing(sqlite3.connect(target.as_uri()+'?mode=rw', uri=True)) as con:
        need(con.execute('SELECT data FROM settings WHERE id=?', (SENTINEL,)).fetchall() == [('{"value":"before"}',)], 'wrong_synthetic_sentinel')
        con.execute('UPDATE settings SET data=? WHERE id=?', ('{"value":"injected"}', SENTINEL)); con.commit()
        need(con.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0] == 0, 'sentinel_checkpoint_failed')
    after = {n: sha(control.regular(root/n).read_bytes()) for n in paths}
    need({n for n in paths if before[n] != after[n]} == set(secondary), 'injection_changed_other_database')
    result = {'type': 'stopped_second_household_sentinel', 'relative': secondary[0], 'before': before, 'after': after,
              'sqliteMutation': 'UPDATE one explicitly synthetic settings row', 'automaticRestore': False}
    save(evidence, result); return result


class Transport(old.Transport):
    controller = None
    sentinel_fault = None

    def __call__(self, argv, *, cwd=None, timeout=240):
        if argv[:4] == [*lifecycle.DOCKER, 'create'] and 'value=data.check_stopped(root,proof,**kwargs)' in argv[-1] and self.scenario == 'failure':
            need(self.controller is not None and self.controller.lifecycle.phase == 'app-stopped' and self.sentinel_fault is None,
                 'fault_requires_app_only_stopped')
            self.controller.stopped()
            self.sentinel_fault = inject_sentinel(self.data_path, self.root/'injected-failure.json')
        return super().__call__(argv, cwd=cwd, timeout=timeout)

    def web_health(self, argv, timeout):
        need(argv == ['curl', '--fail', '--silent', '--show-error', '--max-time', '30', self.origin+'/healthz'], 'external_health_forbidden')
        need(self.discovery_admitted, 'fixture_discovery_not_admitted')
        web = self.remember(self.project+'-web-1')
        networks = json.loads(self([*lifecycle.DOCKER, 'network', 'inspect', self.project+'_default']))
        need(len(networks) == 1, 'ambiguous_health_network')
        bound = old.web_health_binding(self.project, web, networks[0])
        ip = bound['actualUrl'].removeprefix('http://').split('/')[0]
        cert = self.root/'installed/deploy/rehearsal-cert.pem'
        actual = ['curl', '--fail', '--silent', '--show-error', '--noproxy', '*', '--proto', '=https',
                  '--cacert', str(cert), '--resolve', HOST+':443:'+ip, '--max-time', '30', '--max-redirs', '0',
                  '--max-filesize', '65536', '--write-out', '\n%{http_code}', self.origin+'/healthz']
        proof = {**bound, 'requestedUrl': argv[-1], 'actualArgv': actual, 'caSha256': sha(cert.read_bytes()),
                 'actualTLS': True, 'hostPortPublishingVerified': False, 'completed': False}
        target = self.root/('health-tls-%04d.json' % len(self.records)); save(target.with_suffix('.started.json'), proof)
        try:
            raw = self.execute(actual, min(timeout, 35)); body, delimiter, status = raw.rpartition(b'\n')
            need(delimiter and status == b'200', 'nginx_tls_health_failed')
            need(old.web_health_binding(self.project, self.remember(bound['containerId']), networks[0]) == bound, 'health_identity_changed')
            proof.update(completed=True, httpStatus=200, bodySha256=sha(body)); return body
        except BaseException as error:
            proof['failure'] = type(error).__name__+':'+str(error); raise
        finally: save(target, proof)


class FixtureController(entry.Controller):
    """Only evidence admission is synthetic; stage/activate/data/rollback inherited."""
    def evidence(self):
        _, meta, verified, built = verify(self.fixture_bundle, self.fixture_input)
        need(control.read(self.candidate/'plan.json', self.plan_sha) == self.plan, 'fixture_plan_changed')
        fixture = control.read(self.candidate/'fixture.json', self.plan['fixtureSha256'])
        self.files, self.metadata, self.build = fixture['files'], verified['metadata'], built
        self.runtime = self.metadata['runtimeFiles']
        control.source_hashes(self.source, self.files, exact=True)
        need(sha((self.source/'RELEASE-MANIFEST.json').read_bytes()) == fixture['manifestSha256'], 'fixture_manifest_changed')
        adapted = {'compose.yaml', 'deploy/nginx.conf', 'deploy/rehearsal-cert.pem', 'deploy/rehearsal-key.pem'}
        need(set(self.files) == set(verified['blobs']) | adapted and
             all(self.files[n] == sha(raw) for n, raw in verified['blobs'].items() if n not in adapted), 'fixture_source_changed')
        need(self.plan['sourceHead'] == meta['sourceHead'] and self.plan['tree'] == meta['sourceTree'] and
             self.images['app'] == built['imageId'], 'fixture_identity_changed')


@contextmanager
def adapted(bundle, meta, verified, root, project, port):
    installed, releases = root/'installed', root/'releases'; releases.mkdir(mode=0o700)
    origin = 'https://'+HOST
    nginx = ('server { listen 443 ssl; server_name '+HOST+'; ssl_certificate /fixture/cert.pem; '
             'ssl_certificate_key /fixture/key.pem; location / { proxy_pass http://app:8000; '
             'proxy_set_header Host $host; proxy_set_header X-Forwarded-Proto https; } }\n').encode()
    certificates = tls_files()
    parent = {n: (bundle/'parent'/n).read_bytes() for n in ('app.py', 'requirements.txt')}
    parent.update({'compose.yaml': encoded(composition(project, False, port)), 'deploy/nginx.conf': nginx,
                   'static/experience/synthetic-parent.txt': b'explicit minimal parent fixture\n', **certificates})
    old.materialize(installed, parent)
    save(installed/'RELEASE-MANIFEST.json', {'sourceHead': package.INSTALLED_SOURCE, 'files': {n: sha(b) for n,b in parent.items()}}, 0o644)
    env = {**old.seed.SYNTHETIC_ENV, 'PUBLIC_ORIGIN': origin, 'TRUST_PROXY': '0', 'MEDIA_VIDEO_SOCKET': lifecycle.SOCKET}
    save(installed/'.env', ''.join(k+'='+v+'\n' for k,v in env.items()).encode())
    candidate = root/'candidate'; candidate.mkdir(mode=0o700)
    source = {**verified['blobs'], 'compose.yaml': encoded(composition(project, True, port)), 'deploy/nginx.conf': nginx, **certificates}
    old.materialize(candidate/'source', source); files = {n: sha(b) for n,b in source.items()}
    save(candidate/'source/RELEASE-MANIFEST.json', {**verified['manifest'], 'files': files, 'syntheticAdaptation': True}, 0o644)
    save(candidate/'fixture.json', {'files': files, 'manifestSha256': sha((candidate/'source/RELEASE-MANIFEST.json').read_bytes())})
    parent_sha = sha((installed/'RELEASE-MANIFEST.json').read_bytes())
    plan = {'kind': admission.KIND, 'parentSource': package.INSTALLED_SOURCE, 'parentManifest': parent_sha,
        'sourceHead': meta['sourceHead'], 'tree': meta['sourceTree'], 'images': {n: meta['images'][n] for n in ('app','decoder')},
        'schemaBefore': [73,9], 'schemaAfter': [73,9], 'productionWritesDuringPreparation': False,
        'envSha256': sha((installed/'.env').read_bytes()), 'inputs': {'build': {'root': str(bundle/'build')}},
        'fixtureSha256': sha((candidate/'fixture.json').read_bytes())}
    save(candidate/'plan.json', plan)
    def decoder(value):
        need(value['HostConfig']['Memory'] == value['HostConfig']['MemorySwap'] == old.LIMITS['decoder']*1024**2, 'fixture_decoder_limit_changed')
        normalized = copy.deepcopy(value)
        normalized['HostConfig']['Memory'] = normalized['HostConfig']['MemorySwap'] = 768*1024**2
        old.ORIGINAL_DECODER_CONTRACT(normalized)
    changes = [(control,'ROOT',installed), (control,'RELEASES',releases), (control,'VOLUME',project+'_household-data'),
        (control,'PUBLIC_ORIGIN',origin), (lifecycle,'VOLUME',project+'_household-data'), (lifecycle,'PROJECT',project),
        (lifecycle,'SOCKET_VOLUME',project+'_decoder-socket'), (lifecycle,'MEMORY',dict(old.LIMITS)),
        (lifecycle,'AFTER_COMPOSE',sha(source['compose.yaml'])), (lifecycle,'decoder_contract',decoder),
        (admission,'PARENT_MANIFEST',parent_sha), (package,'NGINX_BEFORE',sha(nginx))]
    save(root/'adaptations.json', {'actualDocker': True, 'actualTLS': True, 'actualMigration': False,
        'actualSystemd': False, 'productionPlanAdmissionExercised': False, 'resourceCapacityClaim': False,
        'fixtureLimitsMiB': old.LIMITS, 'budget': old.BUDGET, 'helperLimitMiB': 384,
        'candidateChanges': sorted({'compose.yaml','deploy/nginx.conf',*certificates}),
        'syntheticMarkerSha256': MARKER, 'parentProductionManifest': package.OLD_MANIFEST, 'fixtureManifest': parent_sha,
        'markerAdapter': 'only generated helper module marker constant and begin/check keyword defaults',
        'unchangedControllerMethodCodeHashes': {n: sha(getattr(control.Controller,n).__code__.co_code) for n in old.METHODS},
        'unchangedDocumentedRestoreSha256': sha((bundle/'restore.py').read_bytes())})
    with bindings(changes):
        yield installed, releases, candidate, sha((candidate/'plan.json').read_bytes()), origin, sha(parent['compose.yaml'])


def marker_prefix(prefix):
    return prefix + "\ndata.MEMBERSHIP_MARKER_SHA256="+repr(MARKER)+"\n" + (
        "data.begin.__kwdefaults__={**data.begin.__kwdefaults__,'marker_sha256':data.MEMBERSHIP_MARKER_SHA256}\n"
        "data.check_stopped.__kwdefaults__={**data.check_stopped.__kwdefaults__,'marker_sha256':data.MEMBERSHIP_MARKER_SHA256}\n")


def preservation_summary(proof):
    before, after = (control.read(proof/n) for n in ('before.json','after.json'))
    data.SPEC.profile(before); data.SPEC.profile(after)
    need(before['households'] == after['households'] == 2 and set(before['databases']) == set(after['databases']), 'group_changed')
    populated = {}
    for name, prior in before['databases'].items():
        current = after['databases'][name]
        need({k:v for k,v in prior.items() if k!='fileSha256'} == {k:v for k,v in current.items() if k!='fileSha256'}, 'full_preservation_failed')
        if name != 'platform.sqlite3':
            populated[name] = {n: prior['tables'][n]['count'] for n in REQUIRED_NONEMPTY}
            need(all(populated[name].values()), 'required_nonempty_rows_missing')
    return {'households': 2, 'databases': 3, 'householdTables': 73, 'platformTables': 9, 'nonempty': populated}


def scenario(bundle, input_sha, meta, verified, output, name, run_id, monitor):
    root = output/name; root.mkdir(mode=0o700); project = 'fd-vcr-'+run_id+'-'+name
    with socket.socket() as sock: sock.bind(('127.0.0.1',0)); port = sock.getsockname()[1]
    result = {'passed': False, 'scenario': name, 'syntheticOnly': True, 'productionPlanAdmissionExercised': False}
    with adapted(bundle, meta, verified, root, project, port) as (installed,releases,candidate,plan_sha,origin,before_compose):
        transport = Transport(root,bundle,project,origin,monitor,name)
        try:
            transport.fresh_project(); old.create_data_volume(transport)
            proof = root/'seed-proof'; proof.mkdir(mode=0o700); os.chown(proof,10001,10001)
            mounts = ['type=volume,src='+control.VOLUME+',dst=/data', 'type=bind,src='+str(proof)+',dst=/proof']
            seeded = json.loads(old.owned_helper(transport, meta['images']['parent'], (bundle/'seed.py').read_text(), mounts, installed/'.env'))
            need(seeded['households']==2 and seeded['databases']==3 and seeded['householdTables']==73 and
                 len(seeded['nonempty'])==2 and all(all(v.values()) for v in seeded['nonempty'].values()), 'wrong_seed')
            # Let the decoder image initialize its private socket volume before
            # media mounts it; all five parent services are then identity-checked.
            for names in (('app','decoder'), ('sync','media','web')):
                transport([*lifecycle.DOCKER,'compose','--project-name',project,'--project-directory',str(installed),
                    '--file',str(installed/'compose.yaml'),'up','-d','--no-build','--pull','never','--wait','--wait-timeout','150',
                    *names], timeout=180)
            c = FixtureController(candidate,plan_sha,runner=transport,root=installed,releases=releases)
            c.fixture_bundle,c.fixture_input = bundle,input_sha; c.lifecycle.before_compose=before_compose
            c.data_prefix = marker_prefix(c.data_prefix); transport.controller=c
            need(set(c.data_actions)=={'backup','check','verify-rollback'}, 'migration_must_not_run')
            with control.release_lock():
                result['stage']=c.stage()
                try: activated=c.activate()
                except control.ReleaseError:
                    need(name=='failure' and transport.sentinel_fault is not None, 'unexpected_activation_failure')
                    failed=control.read(candidate/'failure.json'); c.stopped()
                    need(failed['candidateStop']['complete'] and failed['dataHelperStop']['complete'] and
                         not failed['automaticRestore'] and not transport.timer, 'failure_not_stopped')
                    need(not (c.release/'proof/result.json').exists() and (c.release/'proof/attempt.json').is_file(), 'preservation_failure_missing')
                    # A sentinel change must reach the actual checker; record its exact failed helper stderr.
                    errors = [p.read_text() for p in transport.output.glob('*.stderr')]
                    need(any('assistant_database_drift' in s for s in errors), 'wrong_check_failure')
                    result['activationFailure']=failed; result['injected']=transport.sentinel_fault
                else:
                    need(name=='success' and activated['completed'] and activated['schema']==[73,9] and 'migration' not in activated,
                         'unexpected_activation_success')
                    result['activation']=activated; result['preservation']=preservation_summary(c.release/'proof')
                    transport(['systemctl','stop',control.TIMER]); c.lifecycle.drain('candidate',c.lifecycle.capture('candidate')); c.stopped()
                commands=len(transport.records)
                try: c.stage()
                except control.ReleaseError as error:
                    need(str(error)=='plan_consumed' and len(transport.records)==commands, 'replay_rejection_changed')
                else: need(False,'consumed_plan_replayed')
                result['consumedPlanRejectedBeforeDocker']=True
                result['rollback']=old.restore_fixture(c,transport,bundle)
                need(result['rollback']['verified'] and result['rollback']['databases']==3, 'full_rollback_not_verified')
                result['passed']=True
        except BaseException as error: result['failure']=type(error).__name__+':'+str(error)
        finally:
            result['cleanup']=transport.stop_owned(); result['passed']=bool(result['passed'] and result['cleanup']['complete'])
            result['commands']=transport.records; result['completedAt']=time.time(); save(root/'result.json',result)
    return result


def run(bundle, input_sha256, output_dir):
    _, meta, _, _ = verify(bundle,input_sha256)
    # Reuse the complete reviewed orchestration, admission, monitor and cleanup.
    with bindings([(old,'LAB',LAB),(old,'IMAGES',meta['images']),(old,'verify',verify),(old,'scenario',scenario)]):
        return old.run(bundle,input_sha256,output_dir)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__); sub=parser.add_subparsers(dest='action',required=True)
    for name, fields in {'prepare':('repo','head','package-dir','package-sha256','build-dir','build-sha256','output-dir'),
        'verify':('bundle','input-sha256'), 'run':('bundle','input-sha256','output-dir')}.items():
        command=sub.add_parser(name)
        for field in fields: command.add_argument('--'+field,required=True)
    args=vars(parser.parse_args(argv)); action=args.pop('action')
    value={'verified':bool(verify(**args))} if action=='verify' else globals()[action](**args)
    print(json.dumps(value)); return 1 if value.get('passed') is False else 0


if __name__=='__main__': raise SystemExit(main())
