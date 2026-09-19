"""Fixed finance-query entry; reuse the reviewed populated 66/9 lifecycle."""
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy import assistant_trip_change_release_controller as shared
from deploy import assistant_finance_query_release_profile as profile

SPEC = shared.ReleaseSpec(
    profile.BASELINE, 'assistant-finance-query-release-plan', profile.PARENT_IMAGE, profile.OLD_MANIFEST,
    profile.DOCKER_BEFORE, profile.DOCKER_AFTER, profile.COPY_BEFORE, profile.COPY_AFTER,
    profile.CHANGED_ROOT_FILES, 'assistant_finance_query_release_controller.py',
    shared.OPERATORS + ('assistant_finance_query_release_profile.py', 'assistant_finance_query_release_package.py',
                        'assistant_finance_query_release_controller.py', 'assistant_finance_query_release_plan.py'),
    'assistant-finance-query-66-', shared.SPEC.env_sha256)


class Controller(shared.Controller):
    SPEC = SPEC


def main(argv=None):
    shared.main(argv, controller_type=Controller)


if __name__ == '__main__':
    try:
        main()
    except (shared.ReleaseError, OSError, ValueError, KeyError):
        raise SystemExit('assistant_finance_query_release_failed; preserve evidence and stopped state; no automatic restore') from None
