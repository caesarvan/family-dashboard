"""Generate a reviewed, unbound 55 -> 55 Expo private baseline release; no remote actions."""
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
from deploy.expo_segments_release import prepare as previous

BASE = 'expo-segments-tools-20260917-r1/'
PREPARE_SOURCE = BASE + 'prepare-package.py'
PINNED = {
    BASE + 'operators/ops_common.py': '0117137ba2bcbe4084388ba3b226f7a885b0ec3e8f25379ca7395c73e6f181f2',
    BASE + 'operators/expo_contract.py': '87b27d86951c54cc44ed3619f256ec37d83d9c804624cb776e2ff97cc7ededbf',
    BASE + 'operators/build.py': '85d06d183493ce0a8bb912219719aa123f58dd31856f42513640370b67d35010',
    BASE + 'operators/validate.py': '3c4de4349513bd8b8de5cd40c754fd3a0804c8f6f5c2d76ef1a02528605a2728',
    BASE + 'operators/stage.py': 'b2c97cc31499902adb67d901dec6efdee748b8a087981f737397bf2af652d74d',
    BASE + 'operators/activate.py': 'f0a14356169d76134a2ff14ae61b8e28147d4775b385d4e23f64b3c9a342f5e8',
    BASE + 'operators/post_readback.py': 'b385003ff20f85c60df238224401ae8feb9c012b74572ab09167cf0e698b8f25',
    BASE + 'prepare-package.py': '75db67d8e368c8bbe95c4c959ca6d1a0fe5c189640f6c213fb2e990e5478afd8',
    BASE + 'bind-release.py': '27721b3ae21d33c8b09eae9f5069091cf6360358375d373aeb9f3a841eafe943',
}
OLD_MANIFEST = '88de50dabe7bd2309f8f0d46f69ffbe3a3f9f3ecf03449445410f816564124bd'
OLD_ARCHIVE = '7e49d1ff34cdb5930f33646dec596dab4ca2572c8fb884b74c9d74287a846cf6'
PARENT_IMAGE = 'sha256:f06313c2495f9e348a6f82fef00d09ef16aa73e07367e2554761876042f26c9b'
# Exact final test count must come from collection, not a previous release.
REQUIRED_TESTS = {
    'tests/test_finance_baseline_read_session.py', 'tests/test_finance_import_sessions.py',
    'tests/test_finance_baseline.py', 'tests/test_finance_source_bridge.py',
    'tests/test_spending_observations.py', 'tests/test_frontend_runtime.py',
    'tests/test_household_spaces.py', 'tests/test_platform_backup.py',
    'tests/test_investment_operation_migration.py', 'tests/test_expo_baseline_release.py',
}
FORBIDDEN_TESTS = previous.FORBIDDEN_TESTS
REQUIRED_CHANGED = {
    'finance_baseline.py', 'finance_source_bridge.py', 'spending_observations.py',
    'frontend/src/screens/FinanceScreen.tsx',
}
# Already present in the pinned parent's exact selector; never append them again.
LOCAL_BUILD_SOURCES = previous.LOCAL_BUILD_SOURCES
REQUIRED_ADDED = {
    'frontend/src/lib/financeBaseline.ts', 'frontend/src/components/FinanceBaselinePanel.tsx',
    'tests/test_expo_baseline.mjs', 'tests/browser_expo_baseline_check.py',
    'tests/test_finance_baseline_read_session.py', 'tests/test_finance_import_sessions.py',
    'deploy/expo_baseline_release/prepare.py', 'tests/test_expo_baseline_release.py',
}
UNCHANGED = previous.UNCHANGED
ANONYMOUS_PATHS = (
    '/api/finance-baseline/private', '/api/finance-baseline/imports/status',
    '/api/finance-baseline/imports/status?mode=spending_observation',
    '/api/finance-baseline/imports/status?mode=baseline&operationId=' + '0' * 64,
    '/api/finance-baseline/imports/status?mode=spending_observation&operationId=' + '0' * 64,
)

DOCKER_CONTRACT = previous.DOCKER_CONTRACT


def add_anonymous_checks(code):
    # Keep all 29 prior paths and their exact 401-only assertion.
    anchor = "for path in ('/api/journeys/templates',"
    return replace(code, anchor, 'for path in (' +
                   ','.join(repr(path) for path in ANONYMOUS_PATHS) + ",'/api/journeys/templates',")


def adapt(inputs, access, output, config=None):
    operators = {name: inputs[BASE + 'operators/' + name].decode('utf-8') for name in SCRIPTS}
    common = operators['ops_common.py']
    for name, value in {'CANDIDATE': 'Path(' + repr('/opt/family-dashboard-candidates/' + output.name) + ')',
                        'PARENT_IMAGE': repr(PARENT_IMAGE), 'OLD_MANIFEST': repr(OLD_MANIFEST),
                        'EXPECTED_TEST_COUNT': repr(config['expectedTestCount'] if config else None),
                        'EXPECTED_TESTS': repr(tuple(config['validationTests']) if config else ())}.items():
        common = assignment(common, name, value)
    common = replace(common, '55 -> 55 Expo journey segments source-update guards', '55 -> 55 Expo private baseline source-update guards')
    common = replace(common, repr(previous.UNCHANGED), repr(UNCHANGED))
    operators['ops_common.py'] = common
    operators['build.py'] = replace(operators['build.py'], 'family-dashboard-expo-segments:', 'family-dashboard-expo-baseline:')
    operators['activate.py'] = replace(operators['activate.py'], 'expo-segments', 'expo-baseline', count=4)
    operators['post_readback.py'] = replace(operators['post_readback.py'], 'expo-segments-55-', 'expo-baseline-55-')
    operators['post_readback.py'] = add_anonymous_checks(operators['post_readback.py'])
    prepare = inputs[PREPARE_SOURCE].decode('utf-8')
    for name, value in {'A': 'Path(' + repr(str(access)) + ')', 'OUT': 'Path(' + repr(str(output / 'package')) + ')',
                        'CONTRACT': 'Path(' + repr(str(output / 'operators/expo_contract.py')) + ')',
                        'CONTRACT_SHA': repr(sha(operators['expo_contract.py'].encode()))}.items():
        prepare = assignment(prepare, name, value)
    for before, after in ((previous.OLD_MANIFEST, OLD_MANIFEST), (previous.OLD_ARCHIVE, OLD_ARCHIVE),
                          (previous.PARENT_IMAGE, PARENT_IMAGE), ('Wrong installed Expo household routines archive', 'Wrong installed Expo journey segments archive'),
                          (repr(previous.UNCHANGED), repr(UNCHANGED))):
        prepare = replace(prepare, before, after)
    for field, old, new in (('validationTests', previous.REQUIRED_TESTS, REQUIRED_TESTS),
                            ('changedFiles', previous.REQUIRED_CHANGED, REQUIRED_CHANGED),
                            ('addedFiles', previous.REQUIRED_ADDED, REQUIRED_ADDED)):
        prepare = replace(prepare, 'set(' + repr(sorted(old)) + ") <= set(value['" + field + "'])",
                          'set(' + repr(sorted(new)) + ") <= set(value['" + field + "'])")
    prepare = replace(prepare, 'set(' + repr(sorted(previous.REQUIRED_CHANGED | previous.REQUIRED_ADDED)) + ') <= selected',
                      'set(' + repr(sorted(REQUIRED_CHANGED | REQUIRED_ADDED)) + ') <= selected')
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
    namespace = {'__name__': 'expo_baseline_freeze_check', '__file__': str(access / 'baseline-prepare-validation.py')}
    exec(compile(generated['prepare-package.py'], namespace['__file__'], 'exec'), namespace)
    namespace['validate_config'](config)
    return raw, config


def prepare(access, output, freeze=None):
    access, output = safe_path(access), safe_path(output, exists=False)
    need(output.parent == access and re.fullmatch('expo-baseline-tools-[a-z0-9-]+', output.name), 'New baseline output must be directly under access root')
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
