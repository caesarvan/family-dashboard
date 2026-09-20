"""Fixed UI-only 71/9 package/build/validate/assemble entry; never migrate."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy.build_task_reminders_release import (
    RUNTIME_ADDITIONS, FRONTEND_TESTS as REMINDER_TESTS,
    BROWSER_SCRIPTS as REMINDER_SCRIPTS, ANONYMOUS_PATHS)

BASELINE = 'task-reminders-r1-expo-calendar-conflicts'
KIND = 'expo-calendar-conflicts-release-package'
INSTALLED_SOURCE = '77150610f4fa2eae1edaaadb94198e9f3093f3c5'
INSTALLED_TREE = 'fa940fcb63d8ca6fe470e674539fd74492cae602'
PARENT_IMAGE = 'sha256:a99d11dec43be931f36496368e0565f9dfc87492fcd391dfbff92d2a61470f0e'
OLD_MANIFEST = '0690076adebf7e8c2204ecde005444ee1aa3489eb888fd08c9fd9053e7e3c727'
OLD_PACKAGE = '67720847156174e624e8a5d648f83126e3f7db23fa5dc5839a04225359ab0590'
AUDIT_SHA256 = '313e15072070f499f286c817d20227378309ec1a6129feb8e985d597f88e30f8'
DOCKER_BEFORE = DOCKER_AFTER = '7fca420d3f86a35742385f7b39719c6d5ebf6c9d08c0e764333ae15ebb46763f'
COPY_BEFORE = COPY_AFTER = b'COPY task_publish.py household_routines.py task_dependencies.py task_reminders.py ./\n'
FRONTEND_TESTS = REMINDER_TESTS | {'frontend/tests/calendarConflicts.test.mjs'}
BROWSER_SCRIPTS = REMINDER_SCRIPTS | {'scripts/check_expo_calendar_conflicts_browser.py'}
CHANGED_ROOT_FILES = BROWSER_SCRIPTS | {'README.md'}
SCHEMA_BEFORE = SCHEMA_AFTER = (71, 9)
# package.encoded map of all installed non-Expo runtime bytes; no exemptions.
NON_EXPO_RUNTIME_COUNT = 106
NON_EXPO_RUNTIME_SHA256 = 'ea4c3158b6cc40fc85994814d705d7d902db25858a2054e9760f1958b2d2a6db'

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
    from deploy import activate_expo_calendar_conflicts_release as controller
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
