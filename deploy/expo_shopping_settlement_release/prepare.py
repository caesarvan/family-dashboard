"""Generate unbound Expo shopping-settlement tools from the installed mapping release.

The only mutable backend requires an independently reviewed pin. Generation is
local, exclusive and unbound; it never packages, binds or contacts production.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from deploy.holdings_release.prepare import assignment, need, replace, safe_path, sha
from deploy.travel_release.prepare import SCRIPTS
from deploy.finance_accounts_release.prepare import freeze_config
from deploy.finance_column_mapping_release import prepare as previous

BASE = 'finance-column-mapping-tools-20260918-r1/'
PREPARE_SOURCE = BASE + 'prepare-package.py'
PINNED = {'finance-column-mapping-tools-20260918-r1/operators/ops_common.py': '8be20189365df61185fdfd9b658e7c4b6c58063df2c91edcb732ca61d510782d',
 'finance-column-mapping-tools-20260918-r1/operators/expo_contract.py': '44cab8defbf73009bbe5106533ca60c522ec08f15593cc5e571e42a157d21f4b',
 'finance-column-mapping-tools-20260918-r1/operators/build.py': '4d7da4356f046cff0c5ba05598219c2c080ffd4c8203ca1db3ae9371de13279c',
 'finance-column-mapping-tools-20260918-r1/operators/validate.py': 'b903b27fe568e38f637b525717e8ba58f929471b5875f6e14fca503b84614e71',
 'finance-column-mapping-tools-20260918-r1/operators/stage.py': '0f52d72b2e145df966a9b2e78b6764f4a4a2384fee46e1b4a2709b6df5966a75',
 'finance-column-mapping-tools-20260918-r1/operators/activate.py': 'dfa0f818210850e2f1edf71a3aa759b60e65de9b9a0f807118da3d87933c6faa',
 'finance-column-mapping-tools-20260918-r1/operators/post_readback.py': '56cf698ee387f15c660e2a60770c3faa3998ea5254a2b8c7b289f8d1b9404fe7',
 'finance-column-mapping-tools-20260918-r1/prepare-package.py': 'e6ad6dddd90391e82955bb0b14751aefdf2c6680e017801bba58ef2ac11ec8a6',
 'finance-column-mapping-tools-20260918-r1/bind-release.py': '41b5745652b5866948a4878e66400233a3760ede5f0ca5a35d94a7211ff6c98c'}
OLD_ARCHIVE = '3ff158acd53ec13b411f55d7b810e386e16c41c38ea65c07ccc0470846f31631'
OLD_MANIFEST = '32590f6186738d9de32064fd3e80de80de259c77f96981080c0583eb7525e0c9'
PARENT_IMAGE = 'sha256:039f7c7f4a601273bfbffa22ea9ca9494d8de2045240bf43244d41668469ada6'
# API 1f569df independently reviewed; a missing or malformed pin fails closed.
SHOPPING_SOURCE_SHA256 = '90543ed9a2cbb41136a36d27da1558922fbf144030a50a689300ec15fd3e2067'
SOURCE_PINS = previous.reviewed_sources()
REQUIRED_CHANGED = {'shopping_settlement.py', 'frontend/src/screens/ListScreen.tsx',
    'frontend/src/screens/FinanceScreen.tsx', 'frontend/src/screens/HouseholdApp.tsx', 'frontend/src/lib/types.ts'}
REQUIRED_ADDED = {'frontend/src/components/ShoppingSettlementPanel.tsx',
    'frontend/src/lib/shoppingSettlement.ts', 'tests/test_expo_shopping_settlement.mjs',
    'tests/test_shopping_settlement_sessions.py', 'tests/browser_expo_shopping_settlement_check.py',
    'deploy/expo_shopping_settlement_release/prepare.py', 'tests/test_expo_shopping_settlement_release.py'}
REQUIRED_TESTS = {'tests/test_shopping_settlement.py', 'tests/test_shopping_settlement_sessions.py',
    'tests/test_shopping_settlement_journeys.py', 'tests/test_household_members_migration.py',
    'tests/test_household_spaces.py', 'tests/test_platform_backup.py', 'tests/test_frontend_runtime.py',
    'tests/test_expo_shopping_settlement_release.py'}
FORBIDDEN_TESTS = previous.FORBIDDEN_TESTS
BACKEND_UNCHANGED = tuple(n for n in previous.BACKEND_UNCHANGED if n != 'shopping_settlement.py') + ('finance_hub.py',)
UNCHANGED = tuple(n for n in previous.UNCHANGED if n != 'shopping_settlement.py') + ('finance_hub.py',)
LOCAL_BUILD_SOURCES = previous.LOCAL_BUILD_SOURCES
PRESERVATION_RESULT = previous.PRESERVATION_RESULT
PRESERVATION_FUNCTION = previous.PRESERVATION_FUNCTION
DOCKER_CONTRACT = previous.DOCKER_CONTRACT
verify_generated = previous.verify_generated


def reviewed_sources():
    pins = {**SOURCE_PINS, 'shopping_settlement.py': SHOPPING_SOURCE_SHA256}
    need(all(isinstance(v, str) and re.fullmatch('[a-f0-9]{64}', v) for v in pins.values()),
         'Independently reviewed shopping source pin required')
    return pins


def source_guard():
    return ''.join("    need(manifest.get(" + repr(name) + ") == " + repr(digest)
                   + ", 'Reviewed shopping settlement source changed: " + name + "')\n"
                   for name, digest in reviewed_sources().items())


def adapt(inputs, access, output, config=None):
    guard = source_guard()
    operators = {name: inputs[BASE + 'operators/' + name].decode('utf-8') for name in SCRIPTS}
    common = operators['ops_common.py']
    for name, value in {'CANDIDATE': 'Path(' + repr('/opt/family-dashboard-candidates/' + output.name) + ')',
                        'PARENT_IMAGE': repr(PARENT_IMAGE), 'OLD_MANIFEST': repr(OLD_MANIFEST),
                        'EXPECTED_TEST_COUNT': repr(config['expectedTestCount'] if config else None),
                        'EXPECTED_TESTS': repr(tuple(config['validationTests']) if config else ())}.items():
        common = assignment(common, name, value)
    common = replace(common, repr(previous.UNCHANGED), repr(UNCHANGED))
    common = replace(common, previous.source_guard(), guard)
    common = replace(common, 'column mapping', 'shopping settlement')
    operators['ops_common.py'] = common
    for name, count in (('build.py', 1), ('activate.py', 4), ('post_readback.py', 1)):
        operators[name] = replace(operators[name], 'finance-column-mapping', 'expo-shopping-settlement', count=count)
    operators['activate.py'] = replace(operators['activate.py'], 'column mapping source publication', 'shopping settlement source publication')
    operators['post_readback.py'] = replace(operators['post_readback.py'],
        "for path in ('/api/members',", "for path in ('/api/finance-hub/shopping-settlements/context','/api/members',")
    package = inputs[PREPARE_SOURCE].decode('utf-8')
    for name, value in {'A': 'Path(' + repr(str(access)) + ')', 'OUT': 'Path(' + repr(str(output / 'package')) + ')',
                        'CONTRACT': 'Path(' + repr(str(output / 'operators/expo_contract.py')) + ')',
                        'CONTRACT_SHA': repr(sha(operators['expo_contract.py'].encode()))}.items():
        package = assignment(package, name, value)
    for before, after in ((previous.OLD_MANIFEST, OLD_MANIFEST), (previous.OLD_ARCHIVE, OLD_ARCHIVE),
                          (previous.PARENT_IMAGE, PARENT_IMAGE), (repr(previous.UNCHANGED), repr(UNCHANGED)),
                          ('Wrong installed household members archive', 'Wrong installed column mapping archive')):
        package = replace(package, before, after)
    package = replace(package, previous.source_guard(), guard)
    for field, old, new in (('validationTests', previous.REQUIRED_TESTS, REQUIRED_TESTS),
                            ('changedFiles', previous.REQUIRED_CHANGED, REQUIRED_CHANGED), ('addedFiles', previous.REQUIRED_ADDED, REQUIRED_ADDED)):
        package = replace(package, 'set(' + repr(sorted(old)) + ") <= set(value['" + field + "'])", 'set(' + repr(sorted(new)) + ") <= set(value['" + field + "'])")
    package = replace(package, 'set(' + repr(sorted(previous.REQUIRED_CHANGED | previous.REQUIRED_ADDED)) + ') <= selected', 'set(' + repr(sorted(REQUIRED_CHANGED | REQUIRED_ADDED)) + ') <= selected')
    binder = inputs[BASE + 'bind-release.py'].decode('utf-8')
    for name, value in {'A': access, 'PACK': output / 'package', 'OPS': output / 'operators', 'PREPARE': output / 'prepare-package.py'}.items():
        binder = assignment(binder, name, 'Path(' + repr(str(value)) + ')')
    generated = {'operators/' + name: code.encode() for name, code in operators.items()}
    generated.update({'prepare-package.py': package.encode(), 'bind-release.py': binder.encode()})
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


def prepare(access, output, freeze=None):
    reviewed_sources()
    access, output = safe_path(access), safe_path(output, exists=False)
    need(output.parent == access and re.fullmatch('expo-shopping-settlement-tools-[a-z0-9-]+', output.name),
         'New shopping settlement output must be directly under access root')
    need(not output.exists(), 'Output exists; preserve prior attempts')
    inputs = read_sources(access); generated = adapt(inputs, access, output)
    freeze_raw, config = freeze_config(freeze, access, generated) if freeze else (None, None)
    if config:
        generated = adapt(inputs, access, output, config)
    need(read_sources(access) == inputs, 'Reviewed input changed during generation')
    if freeze:
        need(safe_path(freeze).read_bytes() == freeze_raw, 'Freeze changed during generation')
    output.mkdir(mode=0o700)
    for name, raw in generated.items():
        path = output / name; path.parent.mkdir(exist_ok=True, mode=0o700)
        with path.open('xb') as stream:
            stream.write(raw)
        path.chmod(0o600)
    report = {'schemaVersion': 1, 'bound': False, 'requiresIndependentOperatorReview': True,
        'finalFreezeProvided': config is not None, 'freezeSha256': sha(freeze_raw) if freeze_raw else None,
        'expectedTestCount': config['expectedTestCount'] if config else None, 'profile': 'household_members58',
        'householdTablesBefore': 58, 'householdTablesAfter': 58, 'schemaChange': False,
        'serverCandidate': '/opt/family-dashboard-candidates/' + output.name, 'oldManifestSha256': OLD_MANIFEST,
        'reviewedSourceHashes': reviewed_sources(), 'sourceHashes': PINNED,
        'generatedHashes': {name: sha(raw) for name, raw in generated.items()},
        'productionOperations': False, 'repositoryMutations': False}
    with (output / 'generation.json').open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
    (output / 'generation.json').chmod(0o600)
    need(all((output / name).read_bytes() == raw for name, raw in generated.items()), 'Generated bytes changed')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--freeze', type=Path)
    args = parser.parse_args()
    need(sys.dont_write_bytecode and not sys.flags.optimize and sys.pycache_prefix is None, 'Run python -B without optimization or pycache prefix')
    print(json.dumps(prepare(args.source_root, args.output, args.freeze), indent=2))


if __name__ == '__main__':
    main()
