"""Fixed UI-only 69/9 package/build/validate/assemble entry; never migrate."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy.assistant_trip_items_release_profile import RUNTIME_ADDITIONS, FRONTEND_TESTS as ITEMS_TESTS

# Source-selected identity, never supplied by a plan or command-line profile.
BASELINE = 'assistant-trip-items-r1-expo-task-publish'
KIND = 'expo-trip-task-publish-release-package'
INSTALLED_SOURCE = '882dce5d0bc7bba182d4fe4ba1175c040123e6fd'
INSTALLED_TREE = '71ce91c011b89e70aa95cab17ae44b41fa182e3b'
PARENT_IMAGE = 'sha256:dc5ecb91f25017a19a7e59a992e94d8d281a7e68f1e97e0ca0b5dfeaf2872bd6'
OLD_MANIFEST = '47dec854a77262458bc74573f0b36083c856b772c940587d8d1644d44e032b70'
OLD_PACKAGE = 'a740a95187ee2d62fc61483c1799953b6fb769ccc9e5a9444a9144bace8b61b4'
AUDIT_SHA256 = '4ad1226c392ab0d371df7f1ca36331c03da52e00815c2bd06aacb992a49580d7'
DOCKER_BEFORE = DOCKER_AFTER = '36f5d699823890c26dbc243010f584c5aa5d44c109bd6e63b705e9e025a2a90b'
COPY_BEFORE = COPY_AFTER = b'COPY journey_routes.py ./\n'
FRONTEND_TESTS = ITEMS_TESTS | {'frontend/tests/taskPublish.test.mjs'}
CHANGED_ROOT_FILES = frozenset({'README.md'})
SCHEMA_BEFORE = SCHEMA_AFTER = (69, 9)
# Hash of package.encoded(runtimeFiles excluding static/experience/), from the
# installed package above: 50 root Python + 53 legacy static + requirements.txt.
NON_EXPO_RUNTIME_COUNT = 104
NON_EXPO_RUNTIME_SHA256 = '70b5a4fd7ad2fe27237d27013b32912c4bd2d58408ec210539b0bcc9713afc02'

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
    from deploy import activate_expo_trip_task_publish_release as controller
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
