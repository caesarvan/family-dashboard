"""Fixed trip-items entry reusing the populated-group source update lifecycle."""
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy import assistant_trip_change_release_controller as shared
from deploy import assistant_trip_items_release_profile as profile

SPEC = shared.ReleaseSpec(
    profile.BASELINE, 'assistant-trip-items-release-plan', profile.PARENT_IMAGE, profile.OLD_MANIFEST,
    profile.DOCKER_BEFORE, profile.DOCKER_AFTER, profile.COPY_BEFORE, profile.COPY_AFTER,
    profile.CHANGED_ROOT_FILES, 'assistant_trip_items_release_controller.py',
    shared.OPERATORS + ('assistant_trip_items_release_profile.py', 'assistant_trip_items_release_package.py',
                        'assistant_trip_items_release_controller.py', 'assistant_trip_items_release_data.py',
                        'assistant_trip_items_release_plan.py', 'check_journey_routes_migration.py',
                        'build_journey_routes_release.py'),
    'assistant-trip-items-69-', shared.SPEC.env_sha256, schema_pair=profile.SCHEMA_AFTER)


class Controller(shared.Controller):
    SPEC = SPEC

    def backup_program(self):
        return ("from deploy import assistant_trip_items_release_data as steady\n"
                "result=steady.begin(root,proof,source_identity=identity,plan_sha256=" + repr(self.plan_sha) + ")\n"
                "print(json.dumps(result))")

    def check_program(self):
        return ("from deploy import assistant_trip_items_release_data as steady\n"
                "result=steady.check_stopped(root,proof,source_identity=identity,plan_sha256=" + repr(self.plan_sha) + ")\n"
                "print(json.dumps(result))")


def main(argv=None):
    shared.main(argv, controller_type=Controller)


if __name__ == '__main__':
    try:
        main()
    except (shared.ReleaseError, OSError, ValueError, KeyError):
        raise SystemExit('assistant_trip_items_release_failed; preserve evidence and stopped state; no automatic restore') from None
