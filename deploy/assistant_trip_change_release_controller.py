"""Reviewed 66/9 source update with complete populated-group preservation.

The membership marker is immutable. No DDL migration or warm callback runs;
normal new app startup is checked against the stopped 66/9 group. Shared admission and failure-stop helpers
remain in the original controller, whose bytes are included in the plan.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy import membership_release_controller as shared
from deploy import assistant_trip_change_release_package as package
from deploy import assistant_trip_change_release_data as data
from deploy import membership_release_package as package_policy
from deploy import assistant_trip_change_release_profile as profile
from deploy.membership_release_controller import (
    ROOT, RELEASES, VOLUME, SERVICES, WEB_IMAGE, PUBLIC_ORIGIN, RUNTIME_PROGRAM,
    ReleaseError, need, read, put, regular, relative, sha, source_hashes, run, runtime_environment,
)

PARENT_IMAGE, OLD_MANIFEST = package.PARENT_IMAGE, package.OLD_MANIFEST


@dataclass(frozen=True)
class ReleaseSpec:
    """Source-selected identity, never selected or populated by a release plan."""
    baseline: str
    plan_kind: str
    parent_image: str
    old_manifest: str
    docker_before: str
    docker_after: str
    copy_before: bytes
    copy_after: bytes
    changed_root_files: frozenset
    controller_file: str
    operators: tuple
    release_prefix: str
    env_sha256: str
    schema_pair: tuple = (66, 9)


OPERATORS = ('assistant_trip_change_release_controller.py', 'assistant_trip_change_release_package.py', 'assistant_trip_change_release_data.py', 'assistant_trip_change_release_plan.py',
             'membership_release_controller.py', 'membership_release_package.py',
             'membership_release_build.py', 'membership_release_data.py',
             'assistant_trip_change_release_profile.py', 'check_finance_analysis_migration.py', 'steady_release_data.py', 'finance_analysis_release_data.py',
             'membership_migration.py', 'backup.py')
SPEC = ReleaseSpec(package.BASELINE, 'assistant-trip-change-release-plan', PARENT_IMAGE, OLD_MANIFEST,
                   profile.DOCKER_BEFORE, profile.DOCKER_AFTER, profile.COPY_BEFORE, profile.COPY_AFTER,
                   profile.CHANGED_ROOT_FILES, 'assistant_trip_change_release_controller.py', OPERATORS,
                   'assistant-trip-change-66-', 'a72d456815cf113b1ac0c1e032ac8c45b300ccf2cb499520c14b7f54d5314e07')

MARKER_PROGRAM = """
from pathlib import Path
import hashlib,stat
p=Path('/data/membership-release-attempt.json')
for part in (p,*p.parents):
 if stat.S_ISLNK(part.lstat().st_mode):raise RuntimeError('linked_marker')
if not p.is_file() or p.stat().st_size>65536:raise RuntimeError('invalid_marker')
print(hashlib.sha256(p.read_bytes()).hexdigest())
"""


class Controller(shared.Controller):
    SPEC = SPEC

    @property
    def spec(self):
        return self.SPEC

    def __init__(self, candidate, plan_sha256, *, runner=run, root=ROOT, releases=RELEASES):
        self.candidate = regular(candidate, directory=True)
        self.root, self.releases, self.runner = root, releases, runner
        self.plan_sha = plan_sha256
        self.plan = read(self.candidate / 'release-plan.json', plan_sha256)
        need(self.plan.get('schemaVersion') == 1 and self.plan.get('kind') == self.spec.plan_kind, 'plan_kind')
        entry = regular(Path(__file__).with_name(self.spec.controller_file))
        need(regular(sys.modules[type(self).__module__].__file__) == entry, 'controller_entry_import_changed')
        need(sha(entry.read_bytes()) == self.plan.get('controllerSha256'), 'controller_not_reviewed')
        need(re.fullmatch('sha256:[0-9a-f]{64}', self.plan.get('imageId', '')), 'image_id')
        need(self.plan.get('parentImage') == self.spec.parent_image and self.plan.get('webImage') == WEB_IMAGE
             and self.plan.get('oldManifestSha256') == self.spec.old_manifest, 'baseline_changed')
        need(self.plan.get('envSha256') == self.spec.env_sha256, 'environment_baseline_changed')
        verifier_path = regular(Path(__file__).with_name('membership_release_package.py'))
        need(sha(verifier_path.read_bytes()) == self.plan.get('packageVerifierSha256'), 'package_verifier_not_reviewed')
        from deploy import membership_release_package as verifier
        need(regular(verifier.__file__) == verifier_path, 'package_verifier_import_changed')
        self.verified = verifier.verify_package(self.candidate / 'package', self.plan['packageSha256'], baseline=self.spec.baseline)
        # verify_package's public return contract is normalized by the package
        # author; this controller binds the same original package metadata.
        self.package = read(self.candidate / 'package/package.json', self.plan['packageSha256'])
        self.manifest = read(self.candidate / 'package/release-manifest.json', self.package['manifestSha256'])
        self.files = self.manifest['files']
        self.runtime = self.package['runtimeFiles']
        self.source = regular(self.candidate / 'source', directory=True)
        need(sha((self.source / 'RELEASE-MANIFEST.json').read_bytes()) == self.package['manifestSha256'], 'extracted_manifest_changed')
        source_hashes(self.source, self.files, exact=True)
        need(self.package['parentImage'] == self.spec.parent_image and self.package['oldManifestSha256'] == self.spec.old_manifest, 'package_baseline')
        need(self.plan.get('reviews'), 'reviews_required')
        for name, digest in self.plan['reviews'].items():
            need(sha(regular(self.candidate / relative(name)).read_bytes()) == digest, 'review_changed')

        need(self.plan.get('membershipMarkerSha256') == data.MEMBERSHIP_MARKER_SHA256, 'marker_baseline_changed')
        expected = {'deploy/' + name: sha(regular(Path(__file__).with_name(name)).read_bytes()) for name in self.spec.operators}
        need(self.plan.get('operatorHashes') == expected and
             all(self.files.get(name) == digest for name, digest in expected.items()), 'operator_source_changed')

    def baseline(self):
        need(sha(regular(self.root / 'RELEASE-MANIFEST.json').read_bytes()) == self.spec.old_manifest, 'installed_manifest_changed')
        old = read(self.root / 'RELEASE-MANIFEST.json')['files']
        source_hashes(self.root, old)
        env = regular(self.root / '.env')
        need(sha(env.read_bytes()) == self.plan['envSha256'] and stat.S_IMODE(env.stat().st_mode) == 0o600, 'environment_changed')
        need(old['compose.yaml'] == self.files['compose.yaml'] and old['deploy/nginx.conf'] == self.files['deploy/nginx.conf']
             and old['requirements.txt'] == self.files['requirements.txt'], 'deployment_or_dependency_change')
        before_docker = regular(self.root / 'Dockerfile').read_bytes()
        after_docker = regular(self.source / 'Dockerfile').read_bytes()
        need(old['Dockerfile'] == self.spec.docker_before
             and self.files['Dockerfile'] == self.spec.docker_after
             and sha(after_docker) == self.spec.docker_after
             and before_docker.count(self.spec.copy_before) == 1
             and after_docker == before_docker.replace(self.spec.copy_before, self.spec.copy_after, 1),
             'unsupported_docker_change')
        need(all(n.startswith('static/experience/') or not (n.endswith('.py') or n.startswith('static/'))
                 for n in set(old) - set(self.files)), 'unsupported_runtime_removal')
        changed = {n for n in set(old) | set(self.files) if old.get(n) != self.files.get(n)}
        need(all(n in self.spec.changed_root_files or n.startswith(
            ('frontend/', 'static/experience/', 'docs/', 'tests/', 'deploy/')) for n in changed), 'unsupported_source_change')
        return old, self.current_services(self.spec.parent_image)

    def current_services(self, expected_image):
        result = super().current_services(expected_image)
        for name in ('sync', 'media'):
            value = self.inspect(result[name]['id'])
            need(value['Id'] == result[name]['id'] and value['Image'] == expected_image, 'service_identity_changed')
            result[name]['environmentSha256'] = sha(runtime_environment(value['Config'].get('Env')))
        return result

    def candidate_image(self):
        image = self.plan['imageId']
        parent, child = self.inspect(self.spec.parent_image), self.inspect(image)
        layers = parent['RootFS']['Layers']
        need(child['RootFS']['Layers'][:len(layers)] == layers and len(child['RootFS']['Layers']) == len(layers) + 2, 'image_parent_changed')
        need({k:v for k,v in parent['Config'].items() if k != 'Image'} ==
             {k:v for k,v in child['Config'].items() if k != 'Image'}, 'image_configuration_changed')
        observed = json.loads(self.call(['docker', 'run', '--rm', '--network', 'none', '--read-only', '--user', '10001:10001',
            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true', '--entrypoint', 'python', image, '-B', '-c', RUNTIME_PROGRAM]))
        need(observed == self.runtime, 'image_runtime_changed')

    def validate_evidence(self):
        counts = super().validate_evidence()
        proof = self.plan['build']
        build = read(self.candidate / relative(proof['path']), proof['sha256'])
        need(build.get('exitCode') == 0 and build.get('parentImage') == self.spec.parent_image
             and build.get('imageId') == self.plan['imageId'] and build.get('addedLayers') == 2
             and build.get('packageSha256') == self.plan['packageSha256']
             and build.get('sourceHead') == self.package['sourceHead'] and build.get('tree') == self.package['tree']
             and build.get('manifestSha256') == self.package['manifestSha256']
             and build.get('runtimeHashes') == self.runtime, 'build_evidence_changed')
        return counts

    def stage(self):
        self.candidate_image()
        counts = self.validate_evidence()
        old, services = self.baseline()
        self.marker_preflight()
        self.call(['docker', 'compose', 'config', '--quiet'])
        value = {'planSha256': self.plan_sha, 'services': services, 'oldFiles': old, 'tests': counts,
                 'imageId': self.plan['imageId'], 'schemaBefore': list(self.spec.schema_pair), 'schemaAfter': list(self.spec.schema_pair),
                 'membershipMarkerSha256': data.MEMBERSHIP_MARKER_SHA256, 'productionWrites': False}
        put(self.candidate / 'stage.json', value)
        return value

    def marker_preflight(self):
        # Only the regular marker is read. No app imports, env, or live SQLite.
        observed = self.call(['docker', 'run', '--rm', '--network', 'none', '--read-only',
            '--user', '10001:10001', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
            '-v', VOLUME + ':/data:ro', '--entrypoint', 'python', self.plan['imageId'],
            '-B', '-c', MARKER_PROGRAM])
        need(observed.strip() == data.MEMBERSHIP_MARKER_SHA256.encode('ascii'), 'successful_membership_marker_changed')

    def bind_service_environments(self, release, services):
        self.bind_data_environment(release, services['app'])
        self.service_environments = {'app': self.data_environment}
        for name in ('sync', 'media'):
            service = services[name]
            value = self.inspect(service['id'])
            need(value['Id'] == service['id'] and value['Image'] == service['image'], 'runtime_environment_service_changed')
            raw = runtime_environment(value['Config'].get('Env'))
            need(sha(raw) == service.get('environmentSha256'), 'runtime_environment_changed')
            path = regular(release, directory=True) / (name + '-runtime.env')
            put(path, raw)
            self.service_environments[name] = (path, sha(raw))

    def check_environment(self, container, name='app'):
        # Compose may reorder Env, but must preserve every key and value. The
        # shared serializer rejects duplicate keys and embedded newlines first.
        path, digest = self.service_environments[name]
        expected = regular(path).read_bytes()
        need(sha(expected) == digest and stat.S_IMODE(path.stat().st_mode) == 0o600, 'runtime_environment_file_changed')
        observed = runtime_environment(self.inspect(container)['Config'].get('Env'))
        pairs = lambda raw: dict(line.split('=', 1) for line in raw.decode('utf-8').splitlines())
        need(pairs(observed) == pairs(expected), 'new_service_environment_changed')

    def backup_program(self):
        return ("from deploy import assistant_trip_change_release_data as steady\n"
                "result=steady.begin(root,proof,source_identity=identity,plan_sha256=" + repr(self.plan_sha) + ")\n"
                "print(json.dumps(result))")

    def check_program(self):
        return ("from deploy import assistant_trip_change_release_data as steady\n"
                "result=steady.check_stopped(root,proof,source_identity=identity,plan_sha256=" + repr(self.plan_sha) + ")\n"
                "print(json.dumps(result))")

    def _activate(self):
        staged = read(self.candidate / 'stage.json')
        need(staged['planSha256'] == self.plan_sha, 'stage_plan_changed')
        self.candidate_image()
        self.validate_evidence()
        old, services = self.baseline()
        need(staged['services'] == services and staged['oldFiles'] == old, 'stage_baseline_changed')
        self.marker_preflight()
        need(self.call(['systemctl', 'is-active', 'family-dashboard-backup.timer']).strip() == b'active', 'backup_timer_not_active')
        # `show` exits successfully for inactive units and avoids logging their environment.
        need(self.call(['systemctl', 'show', '-p', 'ActiveState', '--value', 'family-dashboard-backup.service']).strip() == b'inactive', 'backup_running')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        report = {'planSha256': self.plan_sha, 'completed': False, 'steps': []}
        put(self.candidate / 'activation.json', report)
        release = self.releases / (self.spec.release_prefix + stamp)
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
        self.bind_service_environments(release, services)
        for i, image in enumerate(sorted({v['image'] for v in services.values()})):
            self.call(['docker', 'tag', image, 'family-dashboard-preserved:steady-' + stamp.lower() + '-' + str(i)])
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
        before = self.data_call(proof, self.backup_program())
        need(before.get('verified') is True, 'backup_not_verified')
        record('full_stopped_backup_verified_and_preserved')
        # Original generated files are kept outside the served directory.
        regular(self.root / 'static/experience', directory=True)
        os.rename(self.root / 'static/experience', release / 'expo-before')
        for name in [*self.files, 'RELEASE-MANIFEST.json']:
            target = self.root / relative(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            regular(target.parent, directory=True)
            need(not target.is_symlink(), 'linked_install_target')
            temporary = target.with_name(target.name + '.steady-new')
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
        self.check_environment(app['Id'])
        observed = json.loads(self.call(['docker', 'exec', app['Id'], 'python', '-B', '-c', RUNTIME_PROGRAM]))
        need(observed == self.runtime, 'new_app_runtime_changed')
        # Recheck closed SQLite files after the real app's initialization.
        self.call(['docker', 'compose', 'stop', '--timeout', '60', 'app'])
        need(not self.call(['docker', 'ps', '-q', '--filter', 'volume=' + VOLUME]).strip(), 'app_did_not_stop')
        state = self.inspect(app['Id'])['State']
        need(not state['Running'] and not state['OOMKilled'] and state['ExitCode'] in (0, 143), 'unclean_candidate_stop')
        after = self.data_call(proof, self.check_program(), write=False)
        need(after.get('verified') is True and after.get('logicalSha256') == before.get('logicalSha256'), 'app_startup_changed_data')
        record('real_app_startup_preserved_full_group_and_marker')
        self.call(['docker', 'compose', 'up', '-d', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '150', 'app'])
        self.call(['docker', 'compose', 'up', '-d', '--no-deps', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '150', 'sync', 'media', 'web'])
        current = self.current_services(self.plan['imageId'])
        for name in ('app', 'sync', 'media'):
            self.check_environment(current[name]['id'], name)
            observed = json.loads(self.call(['docker', 'exec', current[name]['id'], 'python', '-B', '-c', RUNTIME_PROGRAM]))
            need(observed == self.runtime, 'running_service_runtime_changed')
        health = self.call(['curl', '--fail', '--silent', '--show-error', '--max-time', '30', PUBLIC_ORIGIN + '/healthz'])
        need(json.loads(health).get('status') == 'ok', 'public_health_failed')
        source_hashes(self.root, self.files)
        self.call(['systemctl', 'start', 'family-dashboard-backup.timer'])
        need(self.call(['systemctl', 'is-active', 'family-dashboard-backup.timer']).strip() == b'active', 'backup_timer_not_restarted')
        report.update(completed=True, completedAt=datetime.now(timezone.utc).isoformat(), services=current,
                      preservation=after, stoppedBackup=before, householdTables=self.spec.schema_pair[0], platformTables=self.spec.schema_pair[1])
        record('new_services_verified_and_backup_timer_started')
        return report


def main(argv=None, *, controller_type=Controller, description=None):
    import argparse
    import signal
    parser = argparse.ArgumentParser(description=(__doc__.replace('66/9', '/'.join(map(str, controller_type.SPEC.schema_pair)))
                                                  if description is None else description))
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
    with shared.release_lock():
        controller = controller_type(args.candidate, args.plan_sha256)
        value = getattr(controller, args.action)()
    print(json.dumps({'action': args.action, 'completed': value.get('completed', False),
                      'staged': args.action == 'stage', 'planSha256': args.plan_sha256}))


if __name__ == '__main__':
    try:
        main()
    except (ReleaseError, OSError, ValueError, KeyError):
        raise SystemExit('assistant_trip_change_release_failed; preserve evidence and stopped state; no automatic restore') from None
