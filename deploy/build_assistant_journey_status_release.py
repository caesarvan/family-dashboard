"""Fixed assistant journey-status update on the installed five-service 77/9 parent."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy import build_tv_trip_release as parent

BASELINE = 'tv-trip-r1-assistant-journey-status'
KIND = 'assistant-journey-status-release-package'
INSTALLED_SOURCE = 'd4346d34ed5271699f2cffac7c29aa098edc8a07'
INSTALLED_TREE = '1bc76b9896873589de1597f6a9f50de097c1c5c5'
PARENT_IMAGE = 'sha256:3c55bfbac391346af9f88253be65de96602f55179a2fee698fe694ab34e70b64'
DECODER_IMAGE = parent.DECODER_IMAGE
OLD_MANIFEST = 'f10633fd7688b8c53d6923933097f479cd53c07d44800c52ad2d8217cd387467'
OLD_PACKAGE = 'd1784a3df473d41dbf9c2602e05d569b518b2cd88230d6e0db3afda29c0cecb1'
AUDIT_SHA256 = '50cc64d543b95a582907f726061ff61bb7f674cd0f43dea4a96b18b105fce6a9'
DOCKER_BEFORE = DOCKER_AFTER = parent.DOCKER_AFTER
COMPOSE_SHA256 = parent.COMPOSE_SHA256
NGINX_BEFORE = NGINX_AFTER = parent.NGINX_AFTER
DECODER_SOURCE_PINS = parent.DECODER_SOURCE_PINS
SCHEMA_BEFORE = SCHEMA_AFTER = (77, 9)
NON_EXPO_RUNTIME_COUNT, PRESERVED_RUNTIME_COUNT = 114, 113
PRESERVED_RUNTIME_SHA256 = '8b3b56ec83756693465e72f6f92546e593bd4cafc94e7f9bb85d3f8e1de4b9d0'
PARENT_RUNTIME_SHA256 = '12582ed4f3d2803e4a24d6b621943bd499799bc35a5d31898add9849616989f4'
PARENT_MODULES = {'journey_workflows.py': '67f390a382d7e0e648952274bdb43aac12135a68197fdd7cf5da45adcddbf51b'}
# Candidate API pins; publication requires independent review of this exact source.
CHANGED_MODULES = {'journey_workflows.py': '0320ade60437b4907ebbb41b65cc40617ac69059c3ceac3fd495a4c044aafd51'}
CHANGED_RUNTIME_FILES = frozenset(CHANGED_MODULES)
RUNTIME_ADDITIONS = parent.RUNTIME_ADDITIONS
FRONTEND_TESTS = parent.FRONTEND_TESTS | {'frontend/tests/assistantJourneyStatus.test.mjs'}
BROWSER_SCRIPTS = parent.BROWSER_SCRIPTS | {'tests/browser_assistant_journey_status_check.py'}
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
