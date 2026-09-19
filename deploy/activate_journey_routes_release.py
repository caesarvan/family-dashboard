"""Fixed 66/9 -> 69/9 route release with full stopped backups and failure stop.

Admission/environment/runtime checks and failure cleanup reuse the source-update
controller. The migration lifecycle preserves the existing finance migration
order, with only this profile's prefix, three-table step and final count changed.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy import assistant_trip_change_release_controller as shared
from deploy import build_journey_routes_release as profile
from deploy import check_journey_routes_migration as data
from deploy.membership_release_controller import (
    VOLUME, PUBLIC_ORIGIN, RUNTIME_PROGRAM, ReleaseError, need, read, put,
    regular, relative, sha, source_hashes,
)

SPEC = shared.ReleaseSpec(
    profile.BASELINE, 'journey-routes-release-plan', profile.PARENT_IMAGE, profile.OLD_MANIFEST,
    profile.DOCKER_BEFORE, profile.DOCKER_AFTER, profile.COPY_BEFORE, profile.COPY_AFTER,
    profile.CHANGED_ROOT_FILES, 'activate_journey_routes_release.py',
    shared.OPERATORS + ('check_journey_routes_migration.py', 'build_journey_routes_release.py',
                        'activate_journey_routes_release.py'),
    'journey-routes-69-', shared.SPEC.env_sha256)


class Controller(shared.Controller):
    SPEC = SPEC

    def stage(self):
        self.candidate_image()
        counts = self.validate_evidence()
        old, services = self.baseline()
        self.marker_preflight()
        self.call(['docker', 'compose', 'config', '--quiet'])
        value = {'planSha256': self.plan_sha, 'services': services, 'oldFiles': old, 'tests': counts,
                 'imageId': self.plan['imageId'], 'schemaBefore': [66, 9], 'schemaAfter': [69, 9],
                 'membershipMarkerSha256': data.MEMBERSHIP_MARKER_SHA256, 'productionWrites': False}
        put(self.candidate / 'stage.json', value)
        return value

    def backup_program(self):
        return ("from deploy import check_journey_routes_migration as routes\n"
                "result=routes.begin(root,proof,source_identity=identity,plan_sha256=" + repr(self.plan_sha) + ")\n"
                "print(json.dumps(result))")

    def migration_program(self):
        return ("from deploy import check_journey_routes_migration as routes\n"
                "result=routes.migrate(root,proof,source_identity=identity,plan_sha256=" + repr(self.plan_sha) + ")\n"
                "print(json.dumps(result))")

    def check_program(self):
        return ("from deploy import check_journey_routes_migration as routes\n"
                "result=routes.check_stopped(root,proof,source_identity=identity,plan_sha256=" + repr(self.plan_sha) + ")\n"
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
        migrated = self.data_call(proof, self.migration_program())
        need(migrated.get('verified') is True, 'migration_not_verified')
        record('exact_three_table_migration_verified')
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
        need(after.get('verified') is True and after.get('logicalSha256') == migrated.get('logicalSha256'), 'app_startup_changed_data')
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
                      preservation=after, stoppedBackup=before, migration=migrated, householdTables=69, platformTables=9)
        record('new_services_verified_and_backup_timer_started')
        return report


def main(argv=None):
    shared.main(argv, controller_type=Controller)


if __name__ == '__main__':
    try:
        main()
    except (ReleaseError, OSError, ValueError, KeyError):
        raise SystemExit('journey_routes_release_failed; preserve evidence and stopped state; no automatic restore') from None
