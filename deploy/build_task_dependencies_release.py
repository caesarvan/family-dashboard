"""Fixed local-task dependency 69/9 package entry; preserve 97 runtime files."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy.build_assistant_document_search_release import (
    RUNTIME_ADDITIONS as DOCUMENT_RUNTIME, FRONTEND_TESTS as DOCUMENT_TESTS)

BASELINE = 'assistant-document-search-r1-task-dependencies'
KIND = 'task-dependencies-release-package'
INSTALLED_SOURCE = 'fd3ef3692528a18e3e6afc779fb15efe8463d559'
INSTALLED_TREE = '419b5b62f962cb06e1fa52a8f2af541e44189452'
PARENT_IMAGE = 'sha256:3c572b73396b71dd651e1a02e9774484f06d50476d6d3b6a2a50b6306bb1b747'
OLD_MANIFEST = 'da779fc25df1b6df3c71c50851355bb452fb0afa65cde7b829a8b2604bd23b0c'
OLD_PACKAGE = '3da0f27a68eb375f5fddd0ad69c227018b869a7266ae93442935458cc87dfe9a'
AUDIT_SHA256 = '0cab19c440085447f5db199a0797a231bd9fc3c2096eb9a04d04604bf31c103b'
DOCKER_BEFORE = '36f5d699823890c26dbc243010f584c5aa5d44c109bd6e63b705e9e025a2a90b'
DOCKER_AFTER = '6960db583e7c84dbeddd3c026054b989a878e31e56c9787728c9e9cde3bfebc9'
COPY_BEFORE = b'COPY task_publish.py household_routines.py ./\r\n'
COPY_AFTER = b'COPY task_publish.py household_routines.py task_dependencies.py ./\r\n'
RUNTIME_ADDITIONS = DOCUMENT_RUNTIME | {'task_dependencies.py'}
FRONTEND_TESTS = DOCUMENT_TESTS | {'frontend/tests/taskDependencies.test.mjs'}
BROWSER_SCRIPTS = frozenset({'scripts/check_expo_task_dependencies_browser.py'})
CHANGED_RUNTIME_FILES = frozenset({
    'app.py', 'cloud_accounts.py', 'data_portability.py', 'home_assistant.py',
    'household_routines.py', 'journey_workflows.py', 'task_publish.py', 'task_dependencies.py',
})
# The one reviewed script is permitted by exact path, never by its directory.
CHANGED_ROOT_FILES = CHANGED_RUNTIME_FILES | BROWSER_SCRIPTS | {'README.md', 'Dockerfile'}
SCHEMA_BEFORE = SCHEMA_AFTER = (69, 9)
NON_EXPO_RUNTIME_COUNT = 105
PRESERVED_RUNTIME_COUNT = 97
# Encoded installed runtime name/hash map excluding Expo and the seven changed
# existing modules. The eighth allowed module is new; no metadata exemptions.
PRESERVED_RUNTIME_SHA256 = 'cddfd03c86a5ce77d023178438bd56e7c410d555bd44c7f8ef9a4c6c8f614b42'

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
    from deploy import activate_task_dependencies_release as controller
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
