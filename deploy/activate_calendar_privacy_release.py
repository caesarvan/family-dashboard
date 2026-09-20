"""Calendar privacy 71/9 source update; preserve all tables and populated reminders."""
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy import assistant_trip_change_release_controller as core
from deploy import activate_expo_calendar_conflicts_release as previous
from deploy import build_calendar_privacy_release as profile
from deploy.membership_release_controller import PUBLIC_ORIGIN, need

SPEC = core.ReleaseSpec(
    profile.BASELINE, 'calendar-privacy-release-plan', profile.PARENT_IMAGE, profile.OLD_MANIFEST,
    profile.DOCKER_BEFORE, profile.DOCKER_AFTER, profile.COPY_BEFORE, profile.COPY_AFTER,
    profile.CHANGED_ROOT_FILES, 'activate_calendar_privacy_release.py',
    previous.SPEC.operators + ('build_calendar_privacy_release.py',
        'activate_calendar_privacy_release.py', 'calendar_privacy_release_data.py'),
    'calendar-privacy-71-', previous.SPEC.env_sha256, schema_pair=profile.SCHEMA_AFTER)


class Controller(core.Controller):
    # Inherit the source-update lifecycle directly, never the reminder migration.
    SPEC = SPEC

    def validate_evidence(self):
        counts = super().validate_evidence()
        need(profile.AUDIT_SHA256 in self.plan['reviews'].values(), 'parent_production_audit_required')
        return counts

    def backup_program(self):
        return ("from deploy import calendar_privacy_release_data as steady\n"
                "result=steady.begin(root,proof,source_identity=identity,plan_sha256=" + repr(self.plan_sha) + ")\n"
                "print(json.dumps(result))")

    def check_program(self):
        return ("from deploy import calendar_privacy_release_data as steady\n"
                "result=steady.check_stopped(root,proof,source_identity=identity,plan_sha256=" + repr(self.plan_sha) + ")\n"
                "print(json.dumps(result))")

    def current_services(self, expected_image):
        services = super().current_services(expected_image)
        # baseline() supplies the parent image. Only the final four-service
        # check in the inherited _activate supplies the candidate image.
        if expected_image == self.plan['imageId']:
            for path in profile.ANONYMOUS_PATHS:
                code = self.call(['curl', '--silent', '--show-error', '--max-time', '30',
                    '--request', 'GET', '--output', '/dev/null', '--write-out', '%{http_code}', PUBLIC_ORIGIN + path])
                need(code == b'401', 'anonymous_reminder_access_allowed')
        return services


def main(argv=None):
    core.main(argv, controller_type=Controller, description=__doc__)


if __name__ == '__main__':
    try:
        main()
    except (core.ReleaseError, OSError, ValueError, KeyError):
        raise SystemExit('calendar_privacy_release_failed; preserve evidence and stopped state; no automatic restore') from None
