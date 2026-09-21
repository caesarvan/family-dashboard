"""Fixed TV-trip migration on the installed five-service 75/9 parent."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy import build_assistant_list_release as parent

BASELINE = 'assistant-list-r1-tv-trip'
KIND = 'tv-trip-release-package'
INSTALLED_SOURCE = 'e8f0427b35157074d179bc4de86a7c5c4db0a755'
INSTALLED_TREE = '20943ac7e9e791e6d6dfa8c4ec5e0c0e3df8470e'
PARENT_IMAGE = 'sha256:e5195f8db0df97860ccec7ffd6955156240f4b9920406b40d8aad104f7392bf1'
DECODER_IMAGE = parent.DECODER_IMAGE
OLD_MANIFEST = '670859d5c9e9124f50381f410ac3cb231055ed05a8572af7e347be3daec4ec63'
OLD_PACKAGE = 'e73244becca1664973d4ee0e2f4d670c8cc79148ed9c3000d1501edb77eca0df'
AUDIT_SHA256 = '64d0a2bc1a062882c0f645e0c3cda931f28125e3df5c368226caf323d7b3b7f9'
DOCKER_BEFORE = parent.DOCKER_AFTER
DOCKER_AFTER = '1b4933916356920978d0fa9c684c39cff98896c2b0f12f825cba74bc944756c7'
COMPOSE_SHA256 = parent.COMPOSE_SHA256
NGINX_BEFORE = NGINX_AFTER = parent.NGINX_AFTER
DECODER_SOURCE_PINS = parent.DECODER_SOURCE_PINS
SCHEMA_BEFORE, SCHEMA_AFTER = (75, 9), (77, 9)
NON_EXPO_RUNTIME_COUNT, PRESERVED_RUNTIME_COUNT = 114, 112
PRESERVED_RUNTIME_SHA256 = '6dce39a483cd7a58c5ba17f96a966a3f3d635434196c672b73851c8757ba9fe0'
PARENT_RUNTIME_SHA256 = '0346c47f289d338a056628bf6a64aafe43044ac77fadf37f9416aee1dd7ec44b'
PARENT_MODULES = {'media_playback.py': 'ccdb4fb6ddc9bd58cbb8568c9e0112f374d6ca365d2708c5dee83413facce90d'}
# Fixed full API candidate; independent review and composed validation are still required.
CHANGED_MODULES = {'media_trip_playback.py': '372a94780c48649dc51e3f0b7c4d82acbce720ce99f8e13788a8c5e1fc45e40b', 'media_playback.py': '2aa8884f52fd56d5d685596c66484724957167854c6a2d73ae9c4424f8dfdf51'}
CHANGED_RUNTIME_FILES = frozenset(CHANGED_MODULES)
RUNTIME_ADDITIONS = parent.RUNTIME_ADDITIONS | {'media_trip_playback.py'}
FRONTEND_TESTS = parent.FRONTEND_TESTS | {'frontend/tests/tvTripRecap.test.mjs'}
BROWSER_SCRIPTS = parent.BROWSER_SCRIPTS | {'tests/browser_tv_trip_playback_check.py'}
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
