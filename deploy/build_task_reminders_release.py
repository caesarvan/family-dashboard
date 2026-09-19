"""Fixed reminder 69/9 to 71/9 package; preserve 101 non-Expo runtime files."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy.build_task_dependencies_release import (
    RUNTIME_ADDITIONS as DEPENDENCY_RUNTIME, FRONTEND_TESTS as DEPENDENCY_TESTS,
    BROWSER_SCRIPTS as DEPENDENCY_SCRIPTS)

BASELINE = 'task-dependencies-r2-task-reminders'
KIND = 'task-reminders-release-package'
INSTALLED_SOURCE = '456585bc1a4f820ca238b3308f09a8d591628f41'
INSTALLED_TREE = '65a93964e5f20088a8cd0bad878fd03c84dccc94'
PARENT_IMAGE = 'sha256:fbb221027f4542cbfb3f9dc66b26d38314bfbbf2df00e43744936b8288fea547'
OLD_MANIFEST = '14f5d762ae07ee33a5228631faa6dc6984da7b2a71e2fc5e508781d786e4aeec'
OLD_PACKAGE = 'e4bf7d523a46870de53cc13cdbde3fd5510e39577c325beb452f75a9788b0ca2'
AUDIT_SHA256 = 'ea6f6cebea08105f7d809d0220c28c8e8de02ae35b599fcf6cd371d690ca17df'
DOCKER_BEFORE = '6960db583e7c84dbeddd3c026054b989a878e31e56c9787728c9e9cde3bfebc9'
DOCKER_AFTER = '7fca420d3f86a35742385f7b39719c6d5ebf6c9d08c0e764333ae15ebb46763f'
COPY_BEFORE = b'COPY task_publish.py household_routines.py task_dependencies.py ./\r\n'
COPY_AFTER = b'COPY task_publish.py household_routines.py task_dependencies.py task_reminders.py ./\n'
RUNTIME_ADDITIONS = DEPENDENCY_RUNTIME | {'task_reminders.py'}
FRONTEND_TESTS = DEPENDENCY_TESTS | {'frontend/tests/taskReminders.test.mjs'}
BROWSER_SCRIPTS = DEPENDENCY_SCRIPTS | {'scripts/check_expo_task_reminders_browser.py'}
CHANGED_RUNTIME_FILES = frozenset({'app.py', 'sync_worker.py', 'household_memberships.py',
                                 'data_portability.py', 'task_reminders.py'})
CHANGED_ROOT_FILES = CHANGED_RUNTIME_FILES | BROWSER_SCRIPTS | {'README.md', 'Dockerfile'}
SCHEMA_BEFORE, SCHEMA_AFTER = (69, 9), (71, 9)
NON_EXPO_RUNTIME_COUNT, PRESERVED_RUNTIME_COUNT = 106, 101
PRESERVED_RUNTIME_SHA256 = 'bfb422fbe62093446a2f6c14e0a6a705470b6b2e4e27989b509624a46665f3c0'
ANONYMOUS_PATHS = ('/api/task-reminders', '/api/task-reminders/operations/' + '0' * 32)

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
    from deploy import activate_task_reminders_release as controller
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
