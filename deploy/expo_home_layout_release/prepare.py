"""Generate a reviewed, unbound 55 -> 55 Expo home layout release; no remote actions."""
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
from deploy.expo_tv_release import prepare as previous

BASE = 'expo-tv-tools-20260917-r1/'
PREPARE_SOURCE = BASE + 'prepare-package.py'
PINNED = {
    BASE + 'operators/ops_common.py': '11e5dab23ef9e680acbaaafe0da2e988abe3d98c5a665b107f18a6387ead2ef1',
    BASE + 'operators/expo_contract.py': '87b27d86951c54cc44ed3619f256ec37d83d9c804624cb776e2ff97cc7ededbf',
    BASE + 'operators/build.py': '9555d9594bf03d8b06e041c9601b73b5c5f7f629f7740c17990e8029662be49d',
    BASE + 'operators/validate.py': '3c4de4349513bd8b8de5cd40c754fd3a0804c8f6f5c2d76ef1a02528605a2728',
    BASE + 'operators/stage.py': 'b2c97cc31499902adb67d901dec6efdee748b8a087981f737397bf2af652d74d',
    BASE + 'operators/activate.py': '45b278f2aca1e62042c8ab9588bab3f8476a5bc99518d4008b35dfa247be5136',
    BASE + 'operators/post_readback.py': '531e39dc3a182bb355acd4a94370583abd61b54defdb13f06eb22e81e7e21159',
    PREPARE_SOURCE: '72325a734b9a797e036c927248eb4cd077c788deb6882f6e3848343b45486767',
    BASE + 'bind-release.py': '8bd6e771d36a2e943e5a77519e497c6fcad5dd9e0d5e11cca71438a84b080931',
}
OLD_MANIFEST = 'ca1e82499be5548e0cd59aa0d83be4296a5fde3c123274f3062190ff8bf3aa30'
OLD_ARCHIVE = '857e571d816ec05f1a3df9575f7982fb8756e8b8a2faba7c47c82b022efc127a'
PARENT_IMAGE = 'sha256:15f5e99ade61c694583137c88033ef6082bafc26ab06c3aa5921342bdfc62191'
# Select this change's layout, authoritative session, household, hosting and
# preservation dependencies. Final collection supplies the exact case count.
REQUIRED_TESTS = {
    'tests/test_dashboard_layout.py', 'tests/test_dashboard_layout_sessions.py',
    'tests/test_member_sessions.py', 'tests/test_household_spaces.py',
    'tests/test_frontend_runtime.py', 'tests/test_platform_backup.py',
    'tests/test_investment_operation_migration.py', 'tests/test_expo_home_layout_release.py',
}
FORBIDDEN_TESTS = previous.FORBIDDEN_TESTS
REQUIRED_CHANGED = {
    'dashboard_preferences.py', 'frontend/src/lib/household.tsx', 'frontend/src/lib/types.ts',
    'frontend/src/screens/HomeScreen.tsx', 'frontend/src/screens/HouseholdApp.tsx',
}
REQUIRED_ADDED = {
    'frontend/src/lib/homeLayout.ts', 'frontend/src/screens/HomeLayoutPanel.tsx',
    'tests/test_dashboard_layout_sessions.py', 'tests/test_expo_home_layout.mjs',
    'tests/browser_expo_home_layout_check.py',
    'deploy/expo_home_layout_release/prepare.py', 'tests/test_expo_home_layout_release.py',
}
# dashboard_preferences.py changes deliberately; it is not in the inherited
# byte-preserved set. The deployed TV route/controller/board/player stay exact.
UNCHANGED = previous.UNCHANGED + (
    'app.py', 'frontend_runtime.py', 'frontend/src/app/_layout.tsx', 'frontend/src/app/tv.tsx',
    'frontend/src/screens/TVScreen.tsx', 'frontend/src/lib/tv.ts',
    'frontend/src/ui/TVBoard.tsx', 'frontend/src/ui/TVBoard.model.ts',
    'frontend/src/ui/TVPhotoPlayer.tsx', 'frontend/src/ui/TVPhotoPlayer.web.tsx',
    'frontend/src/ui/TVPhotoPlayer.model.ts',
)
DOCKER_CONTRACT = previous.DOCKER_CONTRACT


def adapt(inputs, access, output, config=None):
    operators = {name: inputs[BASE + 'operators/' + name].decode('utf-8') for name in SCRIPTS}
    common = operators['ops_common.py']
    for name, value in {'CANDIDATE': 'Path(' + repr('/opt/family-dashboard-candidates/' + output.name) + ')',
                        'PARENT_IMAGE': repr(PARENT_IMAGE), 'OLD_MANIFEST': repr(OLD_MANIFEST),
                        'EXPECTED_TEST_COUNT': repr(config['expectedTestCount'] if config else None),
                        'EXPECTED_TESTS': repr(tuple(config['validationTests']) if config else ())}.items():
        common = assignment(common, name, value)
    common = replace(common, '55 -> 55 Expo television source-update guards', '55 -> 55 Expo home layout source-update guards')
    common = replace(common, repr(previous.UNCHANGED), repr(UNCHANGED))
    operators['ops_common.py'] = common
    operators['build.py'] = replace(operators['build.py'], 'family-dashboard-expo-tv:', 'family-dashboard-expo-home-layout:')
    operators['activate.py'] = replace(operators['activate.py'], 'expo-tv', 'expo-home-layout', count=4)
    operators['post_readback.py'] = replace(operators['post_readback.py'], 'expo-tv-55-', 'expo-home-layout-55-')
    prepare = inputs[PREPARE_SOURCE].decode('utf-8')
    for name, value in {'A': 'Path(' + repr(str(access)) + ')', 'OUT': 'Path(' + repr(str(output / 'package')) + ')',
                        'CONTRACT': 'Path(' + repr(str(output / 'operators/expo_contract.py')) + ')',
                        'CONTRACT_SHA': repr(sha(operators['expo_contract.py'].encode()))}.items():
        prepare = assignment(prepare, name, value)
    for before, after in ((previous.OLD_MANIFEST, OLD_MANIFEST), (previous.OLD_ARCHIVE, OLD_ARCHIVE),
                          (previous.PARENT_IMAGE, PARENT_IMAGE), ('Wrong installed Expo devices archive', 'Wrong installed Expo television archive'),
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
    namespace = {'__name__': 'expo_home_layout_freeze_check', '__file__': str(access / 'home-layout-prepare-validation.py')}
    exec(compile(generated['prepare-package.py'], namespace['__file__'], 'exec'), namespace)
    namespace['validate_config'](config)
    return raw, config


def prepare(access, output, freeze=None):
    access, output = safe_path(access), safe_path(output, exists=False)
    need(output.parent == access and re.fullmatch('expo-home-layout-tools-[a-z0-9-]+', output.name), 'New home layout output must be directly under access root')
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
