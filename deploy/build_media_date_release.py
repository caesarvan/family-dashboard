"""Fixed photo-date source update on the installed five-service 75/9 parent."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy import build_journey_finance_release as parent

BASELINE = 'journey-finance-r1-media-date'
KIND = 'media-date-release-package'
INSTALLED_SOURCE = '302a62d6c32676b4c8628bd5c0fdf967e1d143c5'
INSTALLED_TREE = '121b31a1f5b820ffd9f935671125bfa86e51fa17'
PARENT_IMAGE = 'sha256:1f957a9458cfed01108a4b028e6cdc3297e22bc0a83776c08d4bf374e09feaca'
DECODER_IMAGE = parent.DECODER_IMAGE
OLD_MANIFEST = '9a44d4c5d6002fb600e79069a44438371461b530eda03e89194927314a32820e'
OLD_PACKAGE = 'eca8fbaa739fe4f9300ebc2756292bbeced290badacca16489f30c4a7adf1be2'
AUDIT_SHA256 = 'dac5e57fb87513995c1e7441efe9046c3d43fd6fd0c168c24c089f1012ab85b7'
DOCKER_BEFORE = DOCKER_AFTER = parent.DOCKER_AFTER
COMPOSE_SHA256 = parent.COMPOSE_SHA256
NGINX_BEFORE = NGINX_AFTER = parent.NGINX_AFTER
DECODER_SOURCE_PINS = parent.DECODER_SOURCE_PINS
SCHEMA_BEFORE = SCHEMA_AFTER = (75, 9)
NON_EXPO_RUNTIME_COUNT, PRESERVED_RUNTIME_COUNT = 113, 111
PRESERVED_RUNTIME_SHA256 = 'defff8ab079b0ac64cb9464160ad4d9a65866ba9b91b65eb615f56b481e29910'
PARENT_RUNTIME_SHA256 = '156e41a818ed978a934b3e52c17a4d26b6fb7dc578f1fa88430e3a558018d8f8'
PARENT_MODULES = {
    'household_media.py': 'ec115045b5711fdd7dadbe15cda4cc7c76d4a06254e332eb4c40a440fbfcda1a',
    'data_portability.py': '84a75046d7dd3f8c9655f883a6ae8ee670cdf9170a80a5ed771d26f390ad08fc'}
CHANGED_MODULES = {
    'household_media.py': 'fe222c03fa5bac2f82c1614fda6290686b01ba0651a5d9e22a030601ea425512',
    'data_portability.py': 'f9f69c027323ab27ce1b381d54dd6c2ad431450c5bb8a54fa6f151f9d91841d2'}
CHANGED_RUNTIME_FILES = frozenset(CHANGED_MODULES)
RUNTIME_ADDITIONS = parent.RUNTIME_ADDITIONS
FRONTEND_TESTS = parent.FRONTEND_TESTS | {
    'frontend/tests/photoConfirmedDate.test.mjs', 'frontend/tests/photoConfirmedDateUI.test.mjs'}
BROWSER_SCRIPTS = parent.BROWSER_SCRIPTS | {'tests/browser_media_confirmed_date_check.py'}
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
