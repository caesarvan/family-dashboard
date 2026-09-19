"""UI-only entry retaining the reviewed 69/9 backup/startup/check lifecycle."""
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy import assistant_trip_change_release_controller as core
from deploy import assistant_trip_items_release_controller as shared
from deploy import build_expo_trip_task_publish_release as profile

SPEC = core.ReleaseSpec(
    profile.BASELINE, 'expo-trip-task-publish-release-plan', profile.PARENT_IMAGE, profile.OLD_MANIFEST,
    profile.DOCKER_BEFORE, profile.DOCKER_AFTER, profile.COPY_BEFORE, profile.COPY_AFTER,
    profile.CHANGED_ROOT_FILES, 'activate_expo_trip_task_publish_release.py',
    shared.SPEC.operators + ('build_expo_trip_task_publish_release.py', 'activate_expo_trip_task_publish_release.py'),
    'expo-trip-task-publish-69-', shared.SPEC.env_sha256, schema_pair=profile.SCHEMA_AFTER)


class Controller(shared.Controller):
    # The package verifier independently pins every non-Expo runtime byte.
    # Keep the existing populated 69/9 data reader and its plan/source binding.
    SPEC = SPEC


def main(argv=None):
    core.main(argv, controller_type=Controller)


if __name__ == '__main__':
    try:
        main()
    except (core.ReleaseError, OSError, ValueError, KeyError):
        raise SystemExit('expo_trip_task_publish_release_failed; preserve evidence and stopped state; no automatic restore') from None
