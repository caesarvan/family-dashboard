"""Fixed shopping schedule 69/9 package/build/validate/assemble; no migration."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy.build_expo_trip_task_publish_release import RUNTIME_ADDITIONS, FRONTEND_TESTS as TASK_TESTS

# Source-selected identity, never supplied by a plan or command-line profile.
BASELINE = 'expo-trip-tasks-r1-shopping-schedule'
KIND = 'shopping-schedule-release-package'
INSTALLED_SOURCE = '8f7af253261f28269465f3a77b6c8433f2dc8142'
INSTALLED_TREE = 'f3ce2dbc584f446a750060a59bfaf2bb8c5d5710'
PARENT_IMAGE = 'sha256:6bfdeb35d63dd55e0654f7d21f958fe7e10ffdda81ab06c4e4f5f517c782bed9'
OLD_MANIFEST = '8f6dbcde84adca5a63710b121904c2e9eae04d8b9bde5abf79599a01fbd7c5ad'
OLD_PACKAGE = '28c7389664710fe1d46aedbd1a5347ac370143187e06c1f590e8ef7bb5397487'
AUDIT_SHA256 = '69a3cca9d82fa544e7a1a010611b31effb12dec8aca0932968f3f33f9b7bc73d'
DOCKER_BEFORE = DOCKER_AFTER = '36f5d699823890c26dbc243010f584c5aa5d44c109bd6e63b705e9e025a2a90b'
COPY_BEFORE = COPY_AFTER = b'COPY journey_routes.py ./\n'
FRONTEND_TESTS = TASK_TESTS | {'frontend/tests/shoppingSchedule.test.mjs'}
CHANGED_RUNTIME_FILES = frozenset({
    'app.py', 'data_portability.py', 'home_assistant.py',
    'journey_reschedule.py', 'journey_workflows.py',
})
CHANGED_ROOT_FILES = CHANGED_RUNTIME_FILES | {'README.md'}
SCHEMA_BEFORE = SCHEMA_AFTER = (69, 9)
NON_EXPO_RUNTIME_COUNT = 104
# package.encoded(installed runtimeFiles excluding static/experience/ and ONLY
# the five source-selected root modules above). Neither metadata nor the plan
# may supply exclusions or relax this installed 99-file name/hash map.
PRESERVED_RUNTIME_COUNT = 99
PRESERVED_RUNTIME_SHA256 = 'a62c7ecfc1ad8b7d533e2418c290b054b21c9cbbf76e1a02d876538a99c91697'

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
    from deploy import activate_shopping_schedule_release as controller
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
