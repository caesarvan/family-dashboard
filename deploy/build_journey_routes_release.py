"""Fixed journey-route profile and offline package/build/validate/assemble entry."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# This source-selected profile is never populated from a CLI argument or plan.
BASELINE = 'finance-query-r2-journey-routes'
KIND = 'journey-routes-release-package'
INSTALLED_SOURCE = '68631bfe02d822434e8557aa247f0148d4e9d7dd'
INSTALLED_TREE = '136dec1288fe7fe5ea94b59b0ea2282de32c8ebf'
PARENT_IMAGE = 'sha256:73f18b95d870e49296320347d0988bb0232f120c9481d5f881bba0ad2748abac'
OLD_MANIFEST = '21e0588d81730eda5e45fad16f25e9599e5f4f8bbb491b2aa65320d33d6b8270'
OLD_PACKAGE = '509fe53dc0c5504aa4c64aa60ff9ab293458110687135123481a66627c080f78'
AUDIT_SHA256 = '571afbe62c191018bab5c5d9ae63af1b12a4a73f7078a04f32bd3df17fe1575c'
DOCKER_BEFORE = 'f68324febf8438eb7e0ed1277998e33510c948503a8cf9c633062ba8027cdefb'
DOCKER_AFTER = '36f5d699823890c26dbc243010f584c5aa5d44c109bd6e63b705e9e025a2a90b'
COPY_BEFORE = b'COPY assistant_finance_query.py ./\n'
COPY_AFTER = COPY_BEFORE + b'COPY journey_routes.py ./\n'
RUNTIME_ADDITIONS = frozenset({'inventory_sources.py', 'finance_analysis.py', 'finance_fx.py',
    'assistant_trip_intent.py', 'assistant_trip_change_api.py', 'assistant_finance_query.py', 'journey_routes.py'})
FRONTEND_TESTS = frozenset({'frontend/tests/inventoryFollowup.test.mjs', 'frontend/tests/inventorySources.test.mjs',
    'frontend/tests/financeAnalysis.test.mjs', 'frontend/tests/assistantTripChange.test.mjs',
    'frontend/tests/assistantFinanceQuery.test.mjs', 'frontend/tests/journeyRoutes.test.mjs'})
CHANGED_ROOT_FILES = frozenset({'app.py', 'data_portability.py', 'journey_places.py', 'journey_routes.py',
                               'Dockerfile', 'README.md'})
SCHEMA_BEFORE, SCHEMA_AFTER = (66, 9), (69, 9)

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
    from deploy import activate_journey_routes_release as controller
    from deploy import build_journey_routes_release as entry
    return plan._assemble(**kwargs, package=entry, controller_type=controller.Controller)


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
