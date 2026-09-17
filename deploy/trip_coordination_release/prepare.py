"""Generate a new 55 -> 55 trip/calendar candidate from pinned local operators.

Only new local files are written. No generated entrypoint, server command, Git
mutation, database migration or network operation is executed by this adapter.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from deploy.holdings_release.prepare import assignment, need, replace, safe_path, sha, unique
from deploy.travel_release.prepare import SCRIPTS, UNCHANGED, verify_generated
from deploy.travel_release.prepare import REQUIRED_TESTS as PREVIOUS_TESTS

BASE = 'expo-travel-tools-20260917-r1/'
PINNED = {
    BASE + 'operators/ops_common.py': '63f7a87e9e4a391afc5f1115cac2c48d512d95a41dfca83191e9656797f1b82c',
    BASE + 'operators/expo_contract.py': 'bf7624974a065467b6c56581710a185a7da38e01ad980fd9c4f857add7b96659',
    BASE + 'operators/build.py': '6fdaebbd76a413c25b70afbf8306b52c32be71bfcae2b2b2fb2669228fe8abb2',
    BASE + 'operators/validate.py': 'cd0c738ba5307bf7aa38fff6a5e43b24ba0eb83c5389c9ee2b2eaf9c7fec0cc2',
    BASE + 'operators/stage.py': 'b2c97cc31499902adb67d901dec6efdee748b8a087981f737397bf2af652d74d',
    BASE + 'operators/activate.py': '93362badf7836d9c35520b4b206c22d210ee89f120fc3217dbac5df804bcfcbb',
    BASE + 'operators/post_readback.py': '496da6a8888f5be70a5fc97577e63bfcec97bc636b15735247af558bbc57afbc',
    BASE + 'prepare-package.py': '39854506f7c2fbdd89ac0691fc1d2bbbf3e748c3cfb674589ef9730334ae57f3',
    BASE + 'bind-release.py': 'a19deb94655b364182fc256142d1a8cdf747f45b9cf70cf8e1f18ddec879d1f9',
}
OLD_MANIFEST = '4534b837252ec4cb31d7bc0ad074cfff53f1b0901117cbbfd234c6d570378e9c'
OLD_ARCHIVE = '6b652f275cfebcb67f1dc382734218ef7a095d198734064f9329c0dad27e284c'
PARENT_IMAGE = 'sha256:b394b59bc8e13f60d597f01e87e887c90358be81b073a928f6430d6a5b5b576f'
REQUIRED_TESTS = PREVIOUS_TESTS | {
    'tests/test_calendar_publish.py', 'tests/test_calendar_publication_session.py',
    'tests/test_journey_place_source_revision.py', 'tests/test_journey_places.py',
    'tests/test_trip_coordination_release.py',
}
REQUIRED_CHANGED = {'calendar_publish.py', 'journey_places.py',
                    'frontend/src/screens/TripsScreen.tsx', 'frontend/src/screens/MapScreen.tsx'}
REQUIRED_ADDED = {'frontend/src/screens/JourneyCalendarPanel.tsx', 'frontend/src/lib/calendarPublish.ts',
                  'frontend/src/screens/JourneyPlacesPanel.tsx', 'frontend/src/lib/journeyPlaces.ts',
                  'deploy/trip_coordination_release/prepare.py',
                  'tests/test_calendar_publication_session.py', 'tests/test_journey_place_source_revision.py',
                  'tests/test_trip_coordination_release.py'}
FORBIDDEN_TESTS = {'tests/test_expo_assistant_flow.py', 'tests/test_expo_trips_api.py'}


def adapt(inputs, access, output, config=None):
    """Exact-fragment updates; preservation/backup/restore code is inherited intact."""
    operators = {name: inputs[BASE + 'operators/' + name].decode('utf-8') for name in SCRIPTS}
    common = operators['ops_common.py']
    for name, value in {'CANDIDATE': 'Path(' + repr('/opt/family-dashboard-candidates/' + output.name) + ')',
                        'PARENT_IMAGE': repr(PARENT_IMAGE), 'OLD_MANIFEST': repr(OLD_MANIFEST),
                        'EXPECTED_TEST_COUNT': repr(config['expectedTestCount'] if config else None),
                        'EXPECTED_TESTS': repr(tuple(config['validationTests']) if config else ())}.items():
        common = assignment(common, name, value)
    common = replace(common, '55 -> 55 travel source-update guards', '55 -> 55 trip coordination source-update guards')
    common = replace(common, "    need('investment_operations.py' in expected, 'Finance runtime module absent')",
                     "    need({'investment_operations.py','calendar_publish.py','journey_places.py'} <= expected, 'Trip/finance runtime module absent')")
    operators['ops_common.py'] = common
    operators['build.py'] = replace(operators['build.py'], 'family-dashboard-expo-travel:', 'family-dashboard-trip-coordination:')
    operators['activate.py'] = replace(operators['activate.py'], 'expo-travel', 'trip-coordination', count=4)
    operators['post_readback.py'] = replace(operators['post_readback.py'], 'expo-travel-55-', 'trip-coordination-55-')
    prepare = inputs[BASE + 'prepare-package.py'].decode('utf-8')
    for name, value in {'A': 'Path(' + repr(str(access)) + ')', 'OUT': 'Path(' + repr(str(output / 'package')) + ')',
                        'CONTRACT': 'Path(' + repr(str(output / 'operators/expo_contract.py')) + ')',
                        'CONTRACT_SHA': repr(sha(operators['expo_contract.py'].encode()))}.items():
        prepare = assignment(prepare, name, value)
    for before, after in (
        ('3ce6cae326bb426703ab316c693a4e06c80c7fcae0abf853a9f8a9b31b7b43fc', OLD_MANIFEST),
        ('sha256:3b831aaf898dacebcf3bb733ada13271e1be7707bb41ecfb14d85cb9d6ebf133', PARENT_IMAGE),
        ('a4f956af3b964fb9ea1296d06376ccd85b4186974aa6228b2ab4f8e56d625c08', OLD_ARCHIVE),
        ('Wrong installed holdings archive', 'Wrong installed travel archive'),
    ):
        prepare = replace(prepare, before, after)
    # Enforce these in the generated packager/binder, not just this generator.
    checks = (
        '    need(set(' + repr(sorted(REQUIRED_TESTS)) + ") <= set(value['validationTests']), 'Required trip/preservation tests missing')\n"
        '    need(not set(' + repr(sorted(FORBIDDEN_TESTS)) + ") & set(value['validationTests']), 'Node/TypeScript tests cannot run in this Python-only image')\n"
        '    need(set(' + repr(sorted(REQUIRED_CHANGED)) + ") <= set(value['changedFiles']), 'Required changed trip modules missing')\n"
        '    need(set(' + repr(sorted(REQUIRED_ADDED)) + ") <= set(value['addedFiles']), 'Required new trip modules missing')\n"
    )
    prepare = replace(prepare, '    return value\n\n\ndef git(*args):', checks + '    return value\n\n\ndef git(*args):')
    prepare = replace(prepare, "    need(set(config['validationTests']) <= selected, 'Validation source is absent from package')",
                      '    need(set(' + repr(sorted(REQUIRED_CHANGED | REQUIRED_ADDED)) + ") <= selected, 'Trip package dependencies missing')\n"
                      "    need(set(config['validationTests']) <= selected, 'Validation source is absent from package')")
    binder = inputs[BASE + 'bind-release.py'].decode('utf-8')
    for name, value in {'A': access, 'PACK': output / 'package', 'OPS': output / 'operators', 'PREPARE': output / 'prepare-package.py'}.items():
        binder = assignment(binder, name, 'Path(' + repr(str(value)) + ')')
    generated = {'operators/' + name: code.encode('utf-8') for name, code in operators.items()}
    generated.update({'prepare-package.py': prepare.encode(), 'bind-release.py': binder.encode()})
    for name, raw in generated.items():
        verify_generated(raw, name)
    return generated


def read_sources(access):
    need(safe_path(access).is_dir(), 'Operator source root must be a directory')
    inputs = {}
    for name, expected in PINNED.items():
        path = safe_path(access / name)
        need(path.is_file() and path.stat().st_size < 100_000, 'Bounded operator file required')
        raw = path.read_bytes()
        need(sha(raw) == expected, 'Reviewed operator source checksum changed: ' + name)
        inputs[name] = raw.replace(b'\r\n', b'\n')
    return inputs


def freeze_config(path, access, generated):
    path = safe_path(path)
    need(path.is_file() and path.is_relative_to(access) and path.stat().st_size <= 2_000_000, 'Bounded private freeze required')
    raw = path.read_bytes()
    need(len(raw) <= 2_000_000, 'Freeze changed size')
    config = json.loads(raw.decode('utf-8'), object_pairs_hook=unique)
    namespace = {'__name__': 'trip_coordination_freeze_check', '__file__': str(access / 'trip-prepare-validation.py')}
    exec(compile(generated['prepare-package.py'], namespace['__file__'], 'exec'), namespace)
    namespace['validate_config'](config)
    return raw, config


def prepare(access, output, freeze=None):
    access, output = safe_path(access), safe_path(output, exists=False)
    need(output.parent == access and re.fullmatch('trip-coordination-tools-[a-z0-9-]+', output.name), 'New trip output must be directly under access root')
    need(not output.exists(), 'Output exists; preserve prior attempts')
    inputs = read_sources(access)
    generated = adapt(inputs, access, output)
    freeze_raw, config = freeze_config(freeze, access, generated) if freeze else (None, None)
    if config:
        generated = adapt(inputs, access, output, config)
    need(read_sources(access) == inputs, 'Reviewed input changed during generation')
    if freeze:
        need(safe_path(freeze).read_bytes() == freeze_raw, 'Freeze changed during generation')
    output.mkdir(mode=0o700)
    for name, raw in generated.items():
        path = output / name
        path.parent.mkdir(exist_ok=True, mode=0o700)
        with path.open('xb') as stream:
            stream.write(raw)
        path.chmod(0o600)
    report = {'schemaVersion': 1, 'bound': False, 'requiresIndependentOperatorReview': True,
              'finalFreezeProvided': config is not None, 'freezeSha256': sha(freeze_raw) if freeze_raw else None,
              'expectedTestCount': config['expectedTestCount'] if config else None, 'profile': 'investment_operations55',
              'householdTablesBefore': 55, 'householdTablesAfter': 55, 'schemaChange': False,
              'serverCandidate': '/opt/family-dashboard-candidates/' + output.name,
              'oldManifestSha256': OLD_MANIFEST, 'sourceHashes': PINNED,
              'generatedHashes': {name: sha(raw) for name, raw in generated.items()},
              'productionOperations': False, 'repositoryMutations': False}
    with (output / 'generation.json').open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
    (output / 'generation.json').chmod(0o600)
    need(all((output / name).read_bytes() == raw for name, raw in generated.items()), 'Generated bytes changed')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--freeze', type=Path)
    args = parser.parse_args()
    need(sys.dont_write_bytecode and not sys.flags.optimize and sys.pycache_prefix is None, 'Run python -B without optimization or pycache prefix')
    print(json.dumps(prepare(args.source_root, args.output, args.freeze), indent=2))


if __name__ == '__main__':
    main()
