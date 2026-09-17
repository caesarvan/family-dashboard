"""Generate a reviewed, unbound 55 -> 55 Expo member appearance release; no remote actions."""
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
from deploy.expo_home_layout_release import prepare as previous

BASE = 'expo-home-layout-tools-20260917-r1/'
PREPARE_SOURCE = BASE + 'prepare-package.py'
PINNED = {
    BASE + 'operators/ops_common.py': '29f6f125108d988f14a94049aeb8f6e806039893337067d69ae33110a47d14c5',
    BASE + 'operators/expo_contract.py': '87b27d86951c54cc44ed3619f256ec37d83d9c804624cb776e2ff97cc7ededbf',
    BASE + 'operators/build.py': 'b355fa62e12927fdab3e151add2eb5d1f844dcc8cde45e9fb9c02d648896337f',
    BASE + 'operators/validate.py': '3c4de4349513bd8b8de5cd40c754fd3a0804c8f6f5c2d76ef1a02528605a2728',
    BASE + 'operators/stage.py': 'b2c97cc31499902adb67d901dec6efdee748b8a087981f737397bf2af652d74d',
    BASE + 'operators/activate.py': '677524b9abd64344b8d106621ce642986806b0b9863080f3ebb2a628eb337a2e',
    BASE + 'operators/post_readback.py': '62b07068625aa33f9518692b01010100c35c2bb59788af8345486f24f7d1b79f',
    PREPARE_SOURCE: '6c260db3e74574a8e83487f98c364c75d5bc40466ab9a2401725986f095fb250',
    BASE + 'bind-release.py': 'c0f6984db7dd5f0ce0c14f6e77097563807dad0fc77b42528c798a4d4f3b7bed',
}
OLD_MANIFEST = 'b1b6d2783ef69dbb18be23fc7841194306448ebc1921086fb22dd4d4f6a1b9dd'
OLD_ARCHIVE = '5b3ecfca687de81e9243e1a5472a4a1a3ebf3dd75a9c055a56f71cc926df39d3'
PARENT_IMAGE = 'sha256:ac795a38f4da34b6b9c9be6e47d125a160d870eb3eb4a594fb1e64c56319ee17'
# Select appearance CAS, sessions/isolation, layout compatibility, hosting and
# data-preservation dependencies. Exact count comes from final collection.
REQUIRED_TESTS = {
    'tests/test_member_preferences.py', 'tests/test_member_sessions.py',
    'tests/test_household_spaces.py', 'tests/test_dashboard_layout.py',
    'tests/test_dashboard_layout_sessions.py', 'tests/test_frontend_runtime.py',
    'tests/test_platform_backup.py', 'tests/test_investment_operation_migration.py',
    'tests/test_expo_appearance_release.py',
}
FORBIDDEN_TESTS = previous.FORBIDDEN_TESTS
REQUIRED_CHANGED = {
    'household_spaces.py', 'frontend/src/app/_layout.tsx',
    'frontend/src/lib/household.tsx', 'frontend/src/lib/types.ts',
    'frontend/src/screens/AccountsScreen.tsx', 'frontend/src/screens/FinanceScreen.tsx',
    'frontend/src/screens/HomeScreen.tsx', 'frontend/src/screens/HouseholdApp.tsx',
    'frontend/src/screens/InvestmentsScreen.tsx', 'frontend/src/screens/OtherScreens.tsx',
    'frontend/src/ui/AppShell.tsx', 'frontend/src/ui/components.tsx', 'frontend/src/ui/theme.ts',
    'static/product-shell.js', 'tests/test_dashboard_layout.py', 'tests/test_household_spaces.py',
    'docs/PLATFORM-API.md', 'docs/WORKSPACE-UI.md',
}
REQUIRED_ADDED = {
    'frontend/src/lib/preferences.ts', 'frontend/src/screens/AppearancePanel.tsx',
    'tests/test_member_preferences.py', 'tests/test_expo_preferences.mjs',
    'tests/test_expo_appearance_theme.mjs', 'tests/browser_expo_appearance_check.py',
    'deploy/expo_appearance_release/prepare.py', 'tests/test_expo_appearance_release.py',
}
# Only the two explicitly changed inherited paths leave the preserved set.
# TV entry/controller/Board/Player remain exact, as does the layout API module.
UNCHANGED = tuple(name for name in previous.UNCHANGED
                  if name not in ('household_spaces.py', 'frontend/src/app/_layout.tsx')) + ('dashboard_preferences.py',)
DOCKER_CONTRACT = previous.DOCKER_CONTRACT


def adapt(inputs, access, output, config=None):
    operators = {name: inputs[BASE + 'operators/' + name].decode('utf-8') for name in SCRIPTS}
    common = operators['ops_common.py']
    for name, value in {'CANDIDATE': 'Path(' + repr('/opt/family-dashboard-candidates/' + output.name) + ')',
                        'PARENT_IMAGE': repr(PARENT_IMAGE), 'OLD_MANIFEST': repr(OLD_MANIFEST),
                        'EXPECTED_TEST_COUNT': repr(config['expectedTestCount'] if config else None),
                        'EXPECTED_TESTS': repr(tuple(config['validationTests']) if config else ())}.items():
        common = assignment(common, name, value)
    common = replace(common, '55 -> 55 Expo home layout source-update guards', '55 -> 55 Expo member appearance source-update guards')
    common = replace(common, repr(previous.UNCHANGED), repr(UNCHANGED))
    operators['ops_common.py'] = common
    operators['build.py'] = replace(operators['build.py'], 'family-dashboard-expo-home-layout:', 'family-dashboard-expo-appearance:')
    operators['activate.py'] = replace(operators['activate.py'], 'expo-home-layout', 'expo-appearance', count=4)
    operators['post_readback.py'] = replace(operators['post_readback.py'], 'expo-home-layout-55-', 'expo-appearance-55-')
    prepare = inputs[PREPARE_SOURCE].decode('utf-8')
    for name, value in {'A': 'Path(' + repr(str(access)) + ')', 'OUT': 'Path(' + repr(str(output / 'package')) + ')',
                        'CONTRACT': 'Path(' + repr(str(output / 'operators/expo_contract.py')) + ')',
                        'CONTRACT_SHA': repr(sha(operators['expo_contract.py'].encode()))}.items():
        prepare = assignment(prepare, name, value)
    for before, after in ((previous.OLD_MANIFEST, OLD_MANIFEST), (previous.OLD_ARCHIVE, OLD_ARCHIVE),
                          (previous.PARENT_IMAGE, PARENT_IMAGE), ('Wrong installed Expo television archive', 'Wrong installed Expo home layout archive'),
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
    namespace = {'__name__': 'expo_appearance_freeze_check', '__file__': str(access / 'appearance-prepare-validation.py')}
    exec(compile(generated['prepare-package.py'], namespace['__file__'], 'exec'), namespace)
    namespace['validate_config'](config)
    return raw, config


def prepare(access, output, freeze=None):
    access, output = safe_path(access), safe_path(output, exists=False)
    need(output.parent == access and re.fullmatch('expo-appearance-tools-[a-z0-9-]+', output.name), 'New appearance output must be directly under access root')
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
