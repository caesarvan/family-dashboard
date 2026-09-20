"""Fixed calendar-privacy 71/9 source update; preserve 103 runtime files, never migrate."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy.build_expo_calendar_conflicts_release import (
    RUNTIME_ADDITIONS as PARENT_RUNTIME, FRONTEND_TESTS as PARENT_TESTS,
    BROWSER_SCRIPTS as PARENT_SCRIPTS, ANONYMOUS_PATHS)

BASELINE = 'calendar-conflicts-r1-calendar-privacy'
KIND = 'calendar-privacy-release-package'
INSTALLED_SOURCE = 'ffb0b3cf46b6a4cf35b005d84879763b825cd822'
INSTALLED_TREE = '7bf8c1ea54018713ab6a67e676af3ebd7a1911f3'
PARENT_IMAGE = 'sha256:d11e94b576cc1b9497c85d1c43782b6b62fe5df4bd20d32f3337524c96edd73d'
OLD_MANIFEST = 'f359222a790ed60b494bfcb0e555716a800b96b1b54f497f12c57c9d48b5fc52'
OLD_PACKAGE = 'dfbcd03256962168ae19a27f993902cf91c0d64f2d1ff5c5f43962038c219491'
AUDIT_SHA256 = 'bf4e31d64f9ea6332ac17f4239fed468a5019cbcfb8c92fd3ba4a6b70629b46b'
DOCKER_BEFORE = '7fca420d3f86a35742385f7b39719c6d5ebf6c9d08c0e764333ae15ebb46763f'
DOCKER_AFTER = '511cc2a0b14439278630a905db8782ab601c62c3b52ca27926192ab9577a7f19'
COPY_BEFORE = b'COPY calendar_publish.py financial_files.py investment_import.py investment_operations.py ./\n'
COPY_AFTER = b'COPY calendar_publish.py calendar_privacy.py financial_files.py investment_import.py investment_operations.py ./\n'
RUNTIME_ADDITIONS = PARENT_RUNTIME | {'calendar_privacy.py'}
FRONTEND_TESTS = PARENT_TESTS | {'frontend/tests/calendarPrivacy.test.mjs'}
BROWSER_SCRIPTS = PARENT_SCRIPTS | {'scripts/check_expo_calendar_privacy_browser.py'}
CHANGED_RUNTIME_FILES = frozenset({'app.py', 'home_assistant.py', 'data_portability.py', 'calendar_privacy.py'})
CHANGED_ROOT_FILES = CHANGED_RUNTIME_FILES | BROWSER_SCRIPTS | {'README.md', 'Dockerfile'}
SCHEMA_BEFORE = SCHEMA_AFTER = (71, 9)
NON_EXPO_RUNTIME_COUNT = 107
PRESERVED_RUNTIME_COUNT = 103
# Encoded installed non-Expo map excluding precisely the three updated modules.
# calendar_privacy.py is new; settings, reminders and static bytes have no exemptions.
PRESERVED_RUNTIME_SHA256 = '4f6e79df28819373843d710b818e038992e0a281aa6ebae2c342f820adba0eaa'

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
    from deploy import activate_calendar_privacy_release as controller
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
