"""Document/photo search entry retaining the reviewed 69/9 preservation lifecycle."""
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy import assistant_trip_change_release_controller as core
from deploy import activate_shopping_schedule_release as previous
from deploy import build_assistant_document_search_release as profile

SPEC = core.ReleaseSpec(
    profile.BASELINE, 'assistant-document-search-release-plan', profile.PARENT_IMAGE, profile.OLD_MANIFEST,
    profile.DOCKER_BEFORE, profile.DOCKER_AFTER, profile.COPY_BEFORE, profile.COPY_AFTER,
    profile.CHANGED_ROOT_FILES, 'activate_assistant_document_search_release.py',
    previous.SPEC.operators + ('build_assistant_document_search_release.py', 'activate_assistant_document_search_release.py'),
    'assistant-document-search-69-', previous.SPEC.env_sha256, schema_pair=profile.SCHEMA_AFTER)


class Controller(previous.Controller):
    SPEC = SPEC


def main(argv=None):
    core.main(argv, controller_type=Controller)


if __name__ == '__main__':
    try:
        main()
    except (core.ReleaseError, OSError, ValueError, KeyError):
        raise SystemExit('assistant_document_search_release_failed; preserve evidence and stopped state; no automatic restore') from None
