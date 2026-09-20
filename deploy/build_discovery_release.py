"""Fixed discovery source update: two API modules, unchanged media decoding and 73/9."""
import argparse
import json
from pathlib import Path
import sys
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy import build_local_photo_release as parent

BASELINE = 'local-photo-r1-discovery'
KIND = 'discovery-release-package'
INSTALLED_SOURCE = '79e5ef912517c796f3b6a4183762f8bcbf5464ba'
INSTALLED_TREE = '18626b20bfe3c4ab09e220e9f7e32c491e6f9670'
PARENT_IMAGE = 'sha256:ede2e6f716a75e5d245ed6d90c485d39fd0847108abb6e24e42de8e4f272a1c2'
DECODER_IMAGE = parent.DECODER_IMAGE
OLD_MANIFEST = 'c9723cf4df9a2e2ee36f2300d4374cfd6a0358e91ebd5d5a9392151f20da8f76'
OLD_PACKAGE = 'd305d95ba169718b71856e6aa2f2b2459a4c9f6a7b89d3a13e9e631e3e741873'
AUDIT_SHA256 = '95426d1d937dc29a4d927cd37ae35916389444e5eb46283f2801a05f58d58e83'
DOCKER_AFTER = parent.DOCKER_AFTER
COMPOSE_SHA256 = parent.COMPOSE_SHA256
NGINX_BEFORE = NGINX_AFTER = parent.NGINX_AFTER
DECODER_SOURCE_PINS = parent.DECODER_SOURCE_PINS
SCHEMA_BEFORE = SCHEMA_AFTER = (73, 9)
NON_EXPO_RUNTIME_COUNT, PRESERVED_RUNTIME_COUNT = 112, 110
PRESERVED_RUNTIME_SHA256 = 'd4ee0ce4d45a25e3d716e8b6bc879dce28d193d048a801f08eb906a72742b8d4'
PARENT_RUNTIME_SHA256 = '5b1bc982f31597b2bbbfc5a996e1f6d6ced38a6a78a9127c1416450c1880f78a'
PARENT_MODULES = {
    'home_assistant.py': '4f6edcb20adbd224559e7cacd1ded5a99f786ac78fdcc576f36e3116fa84f709',
    'household_media.py': 'a8120f3b1ef1c9ae0958878ab6d29c7f97b7f1fe7fbcd2b340e666f44fc12223',
}
CHANGED_MODULES = {
    'home_assistant.py': '16f1de26a2470b01bedef183dec39eefb4601b4aa66572cc375ab8ec8a87fe02',
    'household_media.py': '1a8c120b9ee7c43d560ff7f2d23a9731549aee25e6c058a9982b4b1a3bcd0f31',
}
CHANGED_RUNTIME_FILES = frozenset(CHANGED_MODULES)
RUNTIME_ADDITIONS = parent.RUNTIME_ADDITIONS
FRONTEND_TESTS = parent.FRONTEND_TESTS | {
    'frontend/tests/assistantPlaces.test.mjs', 'frontend/tests/photoDuplicates.test.mjs',
    'frontend/tests/photoDuplicatesUI.test.mjs'}
BROWSER_SCRIPTS = parent.BROWSER_SCRIPTS | {'scripts/check_expo_assistant_places_browser.py',
                                         'scripts/check_expo_photo_duplicates_browser.py'}

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
