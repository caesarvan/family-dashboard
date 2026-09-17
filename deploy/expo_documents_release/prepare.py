"""Generate a reviewed, unbound 55 -> 55 Expo journey documents release; no remote actions."""
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
from deploy.expo_appearance_release import prepare as previous

BASE = 'expo-appearance-tools-20260917-r1/'
PREPARE_SOURCE = BASE + 'prepare-package.py'
PINNED = {
    BASE + 'operators/ops_common.py': '419580c78616aa2b397eb6d04f78ccd148954aec3771191a1a8d02f988b704c0',
    BASE + 'operators/expo_contract.py': '87b27d86951c54cc44ed3619f256ec37d83d9c804624cb776e2ff97cc7ededbf',
    BASE + 'operators/build.py': '2a3d61ef19d5fdad89fac2bf2d7aea4da605fa729b88dc7a42b3fc414cd41cd1',
    BASE + 'operators/validate.py': '3c4de4349513bd8b8de5cd40c754fd3a0804c8f6f5c2d76ef1a02528605a2728',
    BASE + 'operators/stage.py': 'b2c97cc31499902adb67d901dec6efdee748b8a087981f737397bf2af652d74d',
    BASE + 'operators/activate.py': 'f7571abfc897b194a265cb59c27918b9fb134979ad975c33a68e217cc034b267',
    BASE + 'operators/post_readback.py': 'bd1c46ee540cf4958a0360517974c2cae38315e27eeebb21197da2c5d8798014',
    PREPARE_SOURCE: '8261817ae3c8b86d8945aa2d0e88dd85d046fb61f0ee60e7e1d71670d04dea58',
    BASE + 'bind-release.py': '83409e734fab764c4e8266f04c31122f56cf96b34417c16230de9d60a09359eb',
}
OLD_MANIFEST = '14374023ae120c9c3d6ddbe009c0f1b97a4ab845d104ce5bc7fd05b8de2cff11'
OLD_ARCHIVE = '4244790d034ae3602a6d734982165cdd7c6eb83962cdffc24a09a032ae0d2e65'
PARENT_IMAGE = 'sha256:6c1650d84ecfdff6f46fc9358ddd332a11b1f812a95279d5621fb63735fc447e'
# Exact final test count must come from collection, not a previous release.
REQUIRED_TESTS = {
    'tests/test_journey_documents.py', 'tests/test_journey_document_sessions.py',
    'tests/test_member_sessions.py', 'tests/test_household_spaces.py',
    'tests/test_frontend_runtime.py', 'tests/test_platform_backup.py',
    'tests/test_investment_operation_migration.py', 'tests/test_expo_documents_release.py',
}
FORBIDDEN_TESTS = previous.FORBIDDEN_TESTS
REQUIRED_CHANGED = {
    'journey_documents.py', 'frontend/src/lib/types.ts',
    'frontend/src/screens/AssistantScreen.tsx', 'frontend/src/screens/CalendarScreen.tsx',
    'frontend/src/screens/HouseholdApp.tsx', 'frontend/src/screens/ListScreen.tsx',
    'frontend/src/screens/MapWorkspace.tsx', 'frontend/src/screens/OtherScreens.tsx',
    'frontend/src/screens/TripsScreen.tsx', 'docs/JOURNEY-DOCUMENTS.md',
}
REQUIRED_ADDED = {
    'frontend/src/lib/journeyDocuments.ts', 'frontend/src/screens/JourneyDocumentsPanel.tsx',
    'tests/test_expo_journey_documents.mjs', 'tests/test_journey_document_sessions.py',
    'tests/browser_expo_journey_documents_check.py',
    'deploy/expo_documents_release/prepare.py', 'tests/test_expo_documents_release.py',
}
# The parent's tuple already excludes journey_documents.py. Preserve every
# inherited guard, including Docker, schema/backup helpers and the TV renderer.
UNCHANGED = previous.UNCHANGED

DOCKER_CONTRACT = previous.DOCKER_CONTRACT


def adapt(inputs, access, output, config=None):
    operators = {name: inputs[BASE + 'operators/' + name].decode('utf-8') for name in SCRIPTS}
    common = operators['ops_common.py']
    for name, value in {'CANDIDATE': 'Path(' + repr('/opt/family-dashboard-candidates/' + output.name) + ')',
                        'PARENT_IMAGE': repr(PARENT_IMAGE), 'OLD_MANIFEST': repr(OLD_MANIFEST),
                        'EXPECTED_TEST_COUNT': repr(config['expectedTestCount'] if config else None),
                        'EXPECTED_TESTS': repr(tuple(config['validationTests']) if config else ())}.items():
        common = assignment(common, name, value)
    common = replace(common, '55 -> 55 Expo member appearance source-update guards', '55 -> 55 Expo journey documents source-update guards')
    common = replace(common, repr(previous.UNCHANGED), repr(UNCHANGED))
    operators['ops_common.py'] = common
    operators['build.py'] = replace(operators['build.py'], 'family-dashboard-expo-appearance:', 'family-dashboard-expo-documents:')
    operators['activate.py'] = replace(operators['activate.py'], 'expo-appearance', 'expo-documents', count=4)
    operators['post_readback.py'] = replace(operators['post_readback.py'], 'expo-appearance-55-', 'expo-documents-55-')
    prepare = inputs[PREPARE_SOURCE].decode('utf-8')
    for name, value in {'A': 'Path(' + repr(str(access)) + ')', 'OUT': 'Path(' + repr(str(output / 'package')) + ')',
                        'CONTRACT': 'Path(' + repr(str(output / 'operators/expo_contract.py')) + ')',
                        'CONTRACT_SHA': repr(sha(operators['expo_contract.py'].encode()))}.items():
        prepare = assignment(prepare, name, value)
    for before, after in ((previous.OLD_MANIFEST, OLD_MANIFEST), (previous.OLD_ARCHIVE, OLD_ARCHIVE),
                          (previous.PARENT_IMAGE, PARENT_IMAGE), ('Wrong installed Expo home layout archive', 'Wrong installed Expo member appearance archive'),
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
    namespace = {'__name__': 'expo_documents_freeze_check', '__file__': str(access / 'documents-prepare-validation.py')}
    exec(compile(generated['prepare-package.py'], namespace['__file__'], 'exec'), namespace)
    namespace['validate_config'](config)
    return raw, config


def prepare(access, output, freeze=None):
    access, output = safe_path(access), safe_path(output, exists=False)
    need(output.parent == access and re.fullmatch('expo-documents-tools-[a-z0-9-]+', output.name), 'New documents output must be directly under access root')
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
