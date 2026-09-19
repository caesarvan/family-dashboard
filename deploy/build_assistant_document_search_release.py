"""Fixed document/photo search 69/9 package entry; preserve 102 runtime files."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy.build_shopping_schedule_release import RUNTIME_ADDITIONS, FRONTEND_TESTS as SHOPPING_TESTS

BASELINE = 'shopping-schedule-r1-assistant-document-search'
KIND = 'assistant-document-search-release-package'
INSTALLED_SOURCE = '67e5b0d5cafd28b50abce7e42fd64f64c8059997'
INSTALLED_TREE = '3ee7134cca45d1fe6d2227b11c921fdd5833243c'
PARENT_IMAGE = 'sha256:086e40df931f84ceef7d3fba3684bc08444e364d311f22e59ad01a372a560916'
OLD_MANIFEST = '6d8324ff8a8f071c7bb0160b081f9a5b503da9070e649ef8956a034e94d3ee5c'
OLD_PACKAGE = '6bf6c8cf7994899c7deadd9ec25cb8c4cc8a57596e5591ede663ec9bc389c447'
AUDIT_SHA256 = '4fce162234123a7f770d58fc875104011cdf9d52e7d77d7d397ccc15f48f9ded'
DOCKER_BEFORE = DOCKER_AFTER = '36f5d699823890c26dbc243010f584c5aa5d44c109bd6e63b705e9e025a2a90b'
COPY_BEFORE = COPY_AFTER = b'COPY journey_routes.py ./\n'
FRONTEND_TESTS = SHOPPING_TESTS | {'frontend/tests/assistantDocumentSearch.test.mjs'}
CHANGED_RUNTIME_FILES = frozenset({'home_assistant.py', 'journey_documents.py'})
CHANGED_ROOT_FILES = CHANGED_RUNTIME_FILES | {'README.md'}
SCHEMA_BEFORE = SCHEMA_AFTER = (69, 9)
NON_EXPO_RUNTIME_COUNT = 104
PRESERVED_RUNTIME_COUNT = 102
# Encoded installed runtime name/hash map excluding Expo and only the two
# source-selected modules above. Plans/metadata cannot supply exemptions.
PRESERVED_RUNTIME_SHA256 = 'c3d59eef7e79228506eea3cca6a5aa53d7b2227e671579e4d98deade61aca370'

from deploy import membership_release_package as package
from deploy import membership_release_build as builder


def prepare(**kwargs):
    return package.prepare(**kwargs, baseline=BASELINE)


def verify_package(output_dir, package_sha256):
    return package.verify_package(output_dir, package_sha256, baseline=BASELINE)


def build(**kwargs):
    return builder.build(**kwargs, baseline=BASELINE)


def validate(**kwargs):
    return builder.validate(**kwargs, baseline=BASELINE)


def assemble(**kwargs):
    from deploy import assistant_trip_change_release_plan as plan
    from deploy import activate_assistant_document_search_release as controller
    return plan._assemble(**kwargs, package=sys.modules[__name__], controller_type=controller.Controller)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    fields = {
        'prepare': ('repo', 'commit', 'export-dir', 'build-evidence', 'evidence-sha256', 'output-dir'),
        'verify': ('output-dir', 'package-sha256'),
        'build': ('package-dir', 'package-sha256', 'output-dir'),
        'validate': ('package-dir', 'package-sha256', 'image-id', 'selection', 'selection-sha256', 'output-dir'),
        'assemble': ('package-dir', 'package-sha256', 'build-dir', 'build-sha256', 'validation-dir',
                     'validation-sha256', 'reviews', 'reviews-sha256', 'candidate'),
    }
    for name, names in fields.items():
        command = commands.add_parser(name)
        for field in names:
            command.add_argument('--' + field, required=True)
        if name == 'validate':
            command.add_argument('--pytest-dependencies', default=builder.DEPS)
    args = vars(parser.parse_args(argv)); action = args.pop('action')
    if action == 'verify':
        checked = verify_package(**args)
        result = {'verified': True, 'sourceHead': checked['metadata']['sourceHead'], 'files': len(checked['blobs'])}
    else:
        result = {'prepare': prepare, 'build': build, 'validate': validate, 'assemble': assemble}[action](**args)
    print(json.dumps(result))
    return 0 if result.get('allPassed', True) else 1


if __name__ == '__main__':
    raise SystemExit(main())
