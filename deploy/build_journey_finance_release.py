"""Fixed journey-finance migration: installed five-service 73/9 parent to 75/9."""
import argparse
import json
from pathlib import Path
import sys
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy import build_finance_flow_release as parent

BASELINE = 'finance-flow-r1-journey-finance'
KIND = 'journey-finance-release-package'
INSTALLED_SOURCE = '53ea3fdb571eae69154e61d264f3c3542631cb49'
INSTALLED_TREE = 'cf243a21008a73a421b3a4128ccd49af1f814b31'
PARENT_IMAGE = 'sha256:cdbe4702e9fc1b7557e8cefb84b664b6d8c369fb0d9788e0235ff426f3c18ac2'
DECODER_IMAGE = parent.DECODER_IMAGE
OLD_MANIFEST = 'e6898a234eb21c20a28b08a9bc48241202380c3857210f18b0278ad02a3b0ed9'
OLD_PACKAGE = '44f8d8c3fd9a5a91e5cfde9e1893c89be345a2d5445b2636c77e3d5733e3466f'
AUDIT_SHA256 = '0fd34df78ff372ab3589c75643743169b9ad802dba393572a8470af84fde2cfb'
DOCKER_BEFORE = parent.DOCKER_AFTER
DOCKER_AFTER = 'dfa16c0ffec43c22aa57226783710439117df54bb054d3e9a26f514715236231'
COMPOSE_SHA256 = parent.COMPOSE_SHA256
NGINX_BEFORE = NGINX_AFTER = parent.NGINX_AFTER
DECODER_SOURCE_PINS = parent.DECODER_SOURCE_PINS
SCHEMA_BEFORE, SCHEMA_AFTER = (73, 9), (75, 9)
NON_EXPO_RUNTIME_COUNT, PRESERVED_RUNTIME_COUNT = 113, 110
PRESERVED_RUNTIME_SHA256 = '6446389f36f281c62537db33355b144be5941a145c82107db07024ab531a463e'
PARENT_RUNTIME_SHA256 = '6be554fcb597c902e39e3d7ac6cf0701b93c00d80406a579d47eb129fc2266c0'
PARENT_MODULES = {'app.py': '34ec457ecff2a3a7bde8599b4c630616ae51f0823ab677d74bf35a4a1525f636', 'data_portability.py': '7b8d5552fc81acaff79e49ac8bc261bddbd5728ae2dd3d5e132a048deef272d7'}
CHANGED_MODULES = {'app.py': 'd7938f5e65ee1276eed72d742bdbafe27cb53e311ba5ad756cae40e369cec53e', 'data_portability.py': '84a75046d7dd3f8c9655f883a6ae8ee670cdf9170a80a5ed771d26f390ad08fc', 'journey_finance.py': '750c3732fbfb0952d7ee01386d6a93529414098cfaa61f1428af2c09acf62a6e'}
CHANGED_RUNTIME_FILES = frozenset(CHANGED_MODULES)
RUNTIME_ADDITIONS = parent.RUNTIME_ADDITIONS | {'journey_finance.py'}
FRONTEND_TESTS = parent.FRONTEND_TESTS
BROWSER_SCRIPTS = parent.BROWSER_SCRIPTS
SUPPLEMENTAL_INPUTS = parent.SUPPLEMENTAL_INPUTS
ADDITIONAL_INPUTS = frozenset({'tests/test_expo_journey_finance.mjs'})

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
