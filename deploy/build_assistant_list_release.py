"""Fixed assistant-list source update on the installed five-service 75/9 parent."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy import build_media_date_release as parent

BASELINE = 'media-date-r1-assistant-list'
KIND = 'assistant-list-release-package'
INSTALLED_SOURCE = '5fae5c5d7c809ddc1dd5d09f68bd56cbeb6d7fa1'
INSTALLED_TREE = 'f1beb973f01c9b050fb5d0d8cd53e745a34f868f'
PARENT_IMAGE = 'sha256:fb94ae0a5a708197fbeda3a632dda111f3a9413d0706f7d8e4ca3d6ff9c64779'
DECODER_IMAGE = parent.DECODER_IMAGE
OLD_MANIFEST = '25d2b4992e9f8fa3ac8f5108ea283ba88e3eb804bb42a6b16784d44786f67b42'
OLD_PACKAGE = '6bcb52573d7dadf8aea411db421a49e53995cccbf8903c5b681f774169e44093'
AUDIT_SHA256 = 'f4acf33ca8a31ea4808a10e6f2069f238478a872112b1fa65ccc9783ceb0227c'
DOCKER_BEFORE = DOCKER_AFTER = parent.DOCKER_AFTER
COMPOSE_SHA256 = parent.COMPOSE_SHA256
NGINX_BEFORE = NGINX_AFTER = parent.NGINX_AFTER
DECODER_SOURCE_PINS = parent.DECODER_SOURCE_PINS
SCHEMA_BEFORE = SCHEMA_AFTER = (75, 9)
NON_EXPO_RUNTIME_COUNT, PRESERVED_RUNTIME_COUNT = 113, 112
PRESERVED_RUNTIME_SHA256 = 'fc3e76c8e3ffb57b5c4718ceacfd6976abe4b4d5c76bb4e7a3aa8094bee5204b'
PARENT_RUNTIME_SHA256 = '278982bbf0d143aaeacaeed68faa976e15841ce0f38f50a4877a0e4ea12815be'
PARENT_MODULES = {'home_assistant.py': '16f1de26a2470b01bedef183dec39eefb4601b4aa66572cc375ab8ec8a87fe02'}
# Candidate API pins; publication requires independent review of this exact source.
CHANGED_MODULES = {'home_assistant.py': 'c2660208e22d93e82e95e4c6f712394de901c510ec4800eea49266385d9aed51'}
CHANGED_RUNTIME_FILES = frozenset(CHANGED_MODULES)
RUNTIME_ADDITIONS = parent.RUNTIME_ADDITIONS
FRONTEND_TESTS = parent.FRONTEND_TESTS | {'frontend/tests/assistantList.test.mjs'}
BROWSER_SCRIPTS = parent.BROWSER_SCRIPTS | {'tests/browser_assistant_list_editing_check.py'}
SUPPLEMENTAL_INPUTS = parent.SUPPLEMENTAL_INPUTS
ADDITIONAL_INPUTS = frozenset()

from deploy import membership_release_package as package
from deploy import membership_release_build as builder


def prepare(**kwargs): return package.prepare(**kwargs, baseline=BASELINE)
def verify_package(output_dir, package_sha256):
    return package.verify_package(output_dir, package_sha256, baseline=BASELINE)
def build(**kwargs): return builder.build(**kwargs, baseline=BASELINE)
def validate(**kwargs): return builder.validate(**kwargs, baseline=BASELINE)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    fields = {
        'prepare': ('repo', 'commit', 'export-dir', 'build-evidence', 'evidence-sha256', 'output-dir'),
        'verify': ('output-dir', 'package-sha256'),
        'build': ('package-dir', 'package-sha256', 'output-dir'),
        'validate': ('package-dir', 'package-sha256', 'image-id', 'selection', 'selection-sha256', 'output-dir')}
    for name, names in fields.items():
        command = commands.add_parser(name)
        for field in names: command.add_argument('--'+field, required=True)
        if name == 'validate': command.add_argument('--pytest-dependencies', default=builder.DEPS)
    args = vars(parser.parse_args(argv)); action = args.pop('action')
    if action == 'verify':
        value = verify_package(**args)
        result = {'verified': True, 'sourceHead': value['metadata']['sourceHead'], 'files': len(value['blobs'])}
    else: result = {'prepare': prepare, 'build': build, 'validate': validate}[action](**args)
    print(json.dumps(result))
    return 0 if result.get('allPassed', True) else 1


if __name__ == '__main__':
    raise SystemExit(main())
