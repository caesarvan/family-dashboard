"""Generate a reviewed, unbound 55 -> 55 Expo journey segments release; no remote actions."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from deploy.holdings_release.prepare import assignment, need, replace, safe_path, sha, unique
from deploy.travel_release.prepare import SCRIPTS, verify_generated
from deploy.expo_routines_release import prepare as previous

BASE = 'expo-routines-tools-20260917-r1/'
PREPARE_SOURCE = BASE + 'prepare-package.py'
PINNED = {
    BASE + 'operators/ops_common.py': '174b21013ccfb4408abdf97a2169d1307d534a06258a647cf9ea4cb6a317359d',
    BASE + 'operators/expo_contract.py': '87b27d86951c54cc44ed3619f256ec37d83d9c804624cb776e2ff97cc7ededbf',
    BASE + 'operators/build.py': '3ee43790e72df9a93f0fb16ea003b6a2c2418a2f3a6b3b5b842fa258cf5cb55c',
    BASE + 'operators/validate.py': '3c4de4349513bd8b8de5cd40c754fd3a0804c8f6f5c2d76ef1a02528605a2728',
    BASE + 'operators/stage.py': 'b2c97cc31499902adb67d901dec6efdee748b8a087981f737397bf2af652d74d',
    BASE + 'operators/activate.py': '207cabc4431ccbe16f61e184d3969f5df4f888305167b8727683776f1cee0aa8',
    BASE + 'operators/post_readback.py': '0cd58f01665ba35dfd1fca39482cc100c4f82170a2efb4a9d6d1ae2222e968a1',
    PREPARE_SOURCE: '9213aa0d2bf3ff0998f69e88978739b9862fe2346819ca262758e6b5a57f6811',
    BASE + 'bind-release.py': '4cb4f0231424ca7b2b4649f6423f27404118844d2f42dec13f93745b783f3ce2',
}
OLD_MANIFEST = '0cb3bb21365f6dc923264b1a6504396dec303a932b766e926f336937580ad8a4'
OLD_ARCHIVE = '41735eb43154748bc912e4216c07b7131f7fdbd91e668c8c0da8afa8e1d95e55'
PARENT_IMAGE = 'sha256:3c576cd3814f7ec8482ff190017eb3cc9a4c3b6dd2dd0aee7d9623e8d9ae7125'
# Exact final test count must come from collection, not a previous release.
REQUIRED_TESTS = {
    'tests/test_journey_edit_snapshot.py', 'tests/test_journey_workflows.py',
    'tests/test_journey_details.py', 'tests/test_journey_transaction_session.py',
    'tests/test_journey_reschedule.py', 'tests/test_journey_publication_review.py',
    'tests/test_frontend_runtime.py', 'tests/test_household_spaces.py',
    'tests/test_platform_backup.py', 'tests/test_investment_operation_migration.py',
    'tests/test_expo_segments_release.py',
}
FORBIDDEN_TESTS = previous.FORBIDDEN_TESTS
REQUIRED_CHANGED = {
    'journey_workflows.py', 'frontend/src/lib/types.ts',
    'frontend/src/screens/HouseholdApp.tsx', 'frontend/src/screens/TripsScreen.tsx',
    'frontend/src/screens/MapWorkspace.tsx', 'frontend/src/screens/AssistantScreen.tsx',
}
LOCAL_BUILD_SOURCES = (
    'frontend/tests/journeySegments.test.ts', 'frontend/tsconfig.tests.json', 'frontend/typecheck.mjs',
)
REQUIRED_ADDED = {
    'frontend/src/lib/journeySegments.ts',
    'frontend/src/components/JourneySegmentsPanel.tsx', 'frontend/src/components/JourneySegmentFields.tsx',
    'tests/test_journey_edit_snapshot.py', 'tests/browser_expo_segments_check.py',
    'deploy/expo_segments_release/prepare.py', 'tests/test_expo_segments_release.py',
} | set(LOCAL_BUILD_SOURCES)
# Only the reviewed edit-source snapshot API changes a previously protected file.
# Retain every other parent guard, including exact Docker and schema/backup bytes.
UNCHANGED = tuple(name for name in previous.UNCHANGED if name != 'journey_workflows.py')

DOCKER_CONTRACT = previous.DOCKER_CONTRACT


def add_anonymous_checks(code):
    # Exact insertion leaves every existing endpoint and the 401 assertion intact.
    return replace(code, "for path in ('/api/routines/context',",
                   "for path in ('/api/journeys/templates','/api/journeys/'+'0'*24,'/api/routines/context',")


def add_local_build_sources(code):
    # Archive the exact reviewed local build inputs; do not broaden directory
    # selection or remove any input from the unchanged partition verification.
    anchor = "    need(required <= tracked, 'Explicit allowlist source is not tracked')"
    return replace(code, anchor, '    required.update(' + repr(LOCAL_BUILD_SOURCES) + ')\n' + anchor)


def adapt(inputs, access, output, config=None):
    operators = {name: inputs[BASE + 'operators/' + name].decode('utf-8') for name in SCRIPTS}
    common = operators['ops_common.py']
    for name, value in {'CANDIDATE': 'Path(' + repr('/opt/family-dashboard-candidates/' + output.name) + ')',
                        'PARENT_IMAGE': repr(PARENT_IMAGE), 'OLD_MANIFEST': repr(OLD_MANIFEST),
                        'EXPECTED_TEST_COUNT': repr(config['expectedTestCount'] if config else None),
                        'EXPECTED_TESTS': repr(tuple(config['validationTests']) if config else ())}.items():
        common = assignment(common, name, value)
    common = replace(common, '55 -> 55 Expo household routines source-update guards', '55 -> 55 Expo journey segments source-update guards')
    common = replace(common, repr(previous.UNCHANGED), repr(UNCHANGED))
    operators['ops_common.py'] = common
    operators['build.py'] = replace(operators['build.py'], 'family-dashboard-expo-routines:', 'family-dashboard-expo-segments:')
    operators['activate.py'] = replace(operators['activate.py'], 'expo-routines', 'expo-segments', count=4)
    operators['post_readback.py'] = replace(operators['post_readback.py'], 'expo-routines-55-', 'expo-segments-55-')
    operators['post_readback.py'] = add_anonymous_checks(operators['post_readback.py'])
    prepare = inputs[PREPARE_SOURCE].decode('utf-8')
    for name, value in {'A': 'Path(' + repr(str(access)) + ')', 'OUT': 'Path(' + repr(str(output / 'package')) + ')',
                        'CONTRACT': 'Path(' + repr(str(output / 'operators/expo_contract.py')) + ')',
                        'CONTRACT_SHA': repr(sha(operators['expo_contract.py'].encode()))}.items():
        prepare = assignment(prepare, name, value)
    for before, after in ((previous.OLD_MANIFEST, OLD_MANIFEST), (previous.OLD_ARCHIVE, OLD_ARCHIVE),
                          (previous.PARENT_IMAGE, PARENT_IMAGE), ('Wrong installed Expo journey documents archive', 'Wrong installed Expo household routines archive'),
                          (repr(previous.UNCHANGED), repr(UNCHANGED))):
        prepare = replace(prepare, before, after)
    for field, old, new in (('validationTests', previous.REQUIRED_TESTS, REQUIRED_TESTS),
                            ('changedFiles', previous.REQUIRED_CHANGED, REQUIRED_CHANGED),
                            ('addedFiles', previous.REQUIRED_ADDED, REQUIRED_ADDED)):
        prepare = replace(prepare, 'set(' + repr(sorted(old)) + ") <= set(value['" + field + "'])",
                          'set(' + repr(sorted(new)) + ") <= set(value['" + field + "'])")
    prepare = replace(prepare, 'set(' + repr(sorted(previous.REQUIRED_CHANGED | previous.REQUIRED_ADDED)) + ') <= selected',
                      'set(' + repr(sorted(REQUIRED_CHANGED | REQUIRED_ADDED)) + ') <= selected')
    prepare = add_local_build_sources(prepare)
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
    namespace = {'__name__': 'expo_segments_freeze_check', '__file__': str(access / 'segments-prepare-validation.py')}
    exec(compile(generated['prepare-package.py'], namespace['__file__'], 'exec'), namespace)
    namespace['validate_config'](config)
    return raw, config


def prepare(access, output, freeze=None):
    access, output = safe_path(access), safe_path(output, exists=False)
    need(output.parent == access and re.fullmatch('expo-segments-tools-[a-z0-9-]+', output.name), 'New segments output must be directly under access root')
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
