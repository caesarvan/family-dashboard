"""Fixed finance flow source update: one module, unchanged media paths and 73/9."""
import argparse
import json
from pathlib import Path
import sys
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy import build_discovery_release as parent

BASELINE = 'discovery-r1-finance-flow'
KIND = 'finance-flow-release-package'
INSTALLED_SOURCE = '63dc63476b046856bf9893c19595e2971ebc13c7'
INSTALLED_TREE = '0767de6bdcc85dda4be520242274b7f07b578a90'
PARENT_IMAGE = 'sha256:b63c1f57eac42a5b25c30d03b342030788796b57f9b51775569f126ae7997fa2'
DECODER_IMAGE = parent.DECODER_IMAGE
OLD_MANIFEST = '7b77dfbc5c3a1f132706817fa10fbbf0f01c022ce27207c58999df60b5645d3f'
OLD_PACKAGE = '57d835b23db00e28408cbd405024be0b588bf8a822b75c02ec701a745d68ec7c'
AUDIT_SHA256 = '0d77aeaf6be26223ef8f9aec069f4ccb2b27960c482beb6a4de7e33c807a2a8c'
DOCKER_AFTER = parent.DOCKER_AFTER
COMPOSE_SHA256 = parent.COMPOSE_SHA256
NGINX_BEFORE = NGINX_AFTER = parent.NGINX_AFTER
DECODER_SOURCE_PINS = parent.DECODER_SOURCE_PINS
SCHEMA_BEFORE = SCHEMA_AFTER = (73, 9)
NON_EXPO_RUNTIME_COUNT, PRESERVED_RUNTIME_COUNT = 112, 111
PRESERVED_RUNTIME_SHA256 = '2876c42431addf37659ac4133132aec7835386ac060558f52f01d1a494b04e16'
PARENT_RUNTIME_SHA256 = '3baf21b99f97f479ebff7a5a1a5f232234aa89a771e3d6ffc0cb3dab3ea0fd86'
PARENT_MODULES = {'finance_hub.py': '093fb1cd54adb4cce7e486b44834800ec018be01cd7b668fc51ceb33f21d3091'}
CHANGED_MODULES = {'finance_hub.py': '27ef835bca9a472a2ef1b98f06bbf1c19fdd4ed0ade03bf0862b7c9d530fdf88'}
CHANGED_RUNTIME_FILES = frozenset(CHANGED_MODULES)
RUNTIME_ADDITIONS = parent.RUNTIME_ADDITIONS
FRONTEND_TESTS = parent.FRONTEND_TESTS | {'frontend/tests/financeImportFlow.test.mjs'}
BROWSER_SCRIPTS = parent.BROWSER_SCRIPTS
SUPPLEMENTAL_INPUTS = frozenset({'tests/test_expo_journey_brief.mjs', 'tests/test_expo_trips.mjs',
    'tests/test_expo_assistant_journey_entry.mjs', 'tests/test_app.py', 'tests/test_journey_workflows.py',
    'tests/test_expo_photos.mjs', 'tests/test_expo_journey_documents.mjs', 'tests/test_expo_calendar.mjs',
    'deploy/git_blobs.py'})
ADDITIONAL_INPUTS = frozenset({'tests/test_expo_finance_import.mjs'})

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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    fields = {
        'prepare': ('repo', 'commit', 'export-dir', 'build-evidence', 'evidence-sha256', 'output-dir'),
        'verify': ('output-dir', 'package-sha256'),
        'build': ('package-dir', 'package-sha256', 'output-dir'),
        'validate': ('package-dir', 'package-sha256', 'image-id', 'selection', 'selection-sha256', 'output-dir'),
    }
    for name, names in fields.items():
        command = commands.add_parser(name)
        for field in names:
            command.add_argument('--'+field, required=True)
        if name == 'validate': command.add_argument('--pytest-dependencies', default=builder.DEPS)
    args = vars(parser.parse_args(argv)); action = args.pop('action')
    if action == 'verify':
        checked = verify_package(**args)
        result = {'verified': True, 'sourceHead': checked['metadata']['sourceHead'], 'files': len(checked['blobs'])}
    else: result = {'prepare': prepare, 'build': build, 'validate': validate}[action](**args)
    print(json.dumps(result))
    return 0 if result.get('allPassed', True) else 1


if __name__ == '__main__': raise SystemExit(main())
