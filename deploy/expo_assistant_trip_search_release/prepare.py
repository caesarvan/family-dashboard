"""Derive frontend-only assistant trip-search tools from installed settlement tools.

Every backend remains byte-identical, including the captured-session settlement
source. Local exclusive generation never packages, binds or contacts production.
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
from deploy.expo_shopping_settlement_release import prepare as previous

BASE = 'expo-shopping-settlement-tools-20260918-r1/'
PREPARE_SOURCE = BASE + 'prepare-package.py'
PINNED = {'expo-shopping-settlement-tools-20260918-r1/operators/ops_common.py': '1556c5a7c7fc363de0f968769df0fdcc09f3aa03d5a09997a6cf5ccc527bcbae',
 'expo-shopping-settlement-tools-20260918-r1/operators/expo_contract.py': '44cab8defbf73009bbe5106533ca60c522ec08f15593cc5e571e42a157d21f4b',
 'expo-shopping-settlement-tools-20260918-r1/operators/build.py': '5ee15792b4beca03467f7b12fb07b3e60bd9de52f0b5f5bfa6f9d422778a67e5',
 'expo-shopping-settlement-tools-20260918-r1/operators/validate.py': 'b903b27fe568e38f637b525717e8ba58f929471b5875f6e14fca503b84614e71',
 'expo-shopping-settlement-tools-20260918-r1/operators/stage.py': '0f52d72b2e145df966a9b2e78b6764f4a4a2384fee46e1b4a2709b6df5966a75',
 'expo-shopping-settlement-tools-20260918-r1/operators/activate.py': '1342e9aaf63887f23dd633b0d0949f4f337c5693d1c354190e5df0f09221e823',
 'expo-shopping-settlement-tools-20260918-r1/operators/post_readback.py': '2dcd9d9e75367ecfbdc031a1a1aa1a253e6642b084374fd8e7045c418a6cce38',
 'expo-shopping-settlement-tools-20260918-r1/prepare-package.py': '8abbd68d312bf2d3355bd4306cb20e3845ce9e36b65c8cbdc8d4c9c9b7b3a7bf',
 'expo-shopping-settlement-tools-20260918-r1/bind-release.py': '3b63bba0ee0bdd7e22a3628f8c7e0a28fe7a74e557208e04dbcf110c79547f8a'}
OLD_ARCHIVE = '973c547235d6efd64369ecadb8003bb8d21e1847d8506fa3d13b2077a1921cd3'
OLD_MANIFEST = 'b5143c3bf4947772f0211d86c36cdb2aaed36d72f6b82e3ba8601ff2043c7efd'
PARENT_IMAGE = 'sha256:c6246c280d19035ecc3b4ec49d8816cb019029a7a690a4285509ce73a9cf7cfd'
SOURCE_PINS = previous.reviewed_sources()
REQUIRED_CHANGED = {'frontend/src/screens/AssistantScreen.tsx', 'frontend/src/lib/assistantJourney.ts',
    'tests/test_expo_assistant_journey_entry.mjs'}
REQUIRED_ADDED = {'tests/browser_expo_assistant_trip_search_check.py',
    'deploy/expo_assistant_trip_search_release/prepare.py', 'tests/test_expo_assistant_trip_search_release.py'}
REQUIRED_TESTS = {'tests/test_home_assistant.py', 'tests/test_assistant_source_search.py',
    'tests/test_assistant_journey_brief.py', 'tests/test_household_spaces.py',
    'tests/test_household_members_migration.py', 'tests/test_platform_backup.py',
    'tests/test_frontend_runtime.py', 'tests/test_expo_assistant_trip_search_release.py'}
FORBIDDEN_TESTS = previous.FORBIDDEN_TESTS
BACKEND_UNCHANGED = (*previous.BACKEND_UNCHANGED, 'shopping_settlement.py')
UNCHANGED = (*previous.UNCHANGED, 'shopping_settlement.py')
LOCAL_BUILD_SOURCES = previous.LOCAL_BUILD_SOURCES
PRESERVATION_RESULT = previous.PRESERVATION_RESULT
PRESERVATION_FUNCTION = previous.PRESERVATION_FUNCTION
DOCKER_CONTRACT = previous.DOCKER_CONTRACT
verify_generated = previous.verify_generated


def reviewed_sources():
    pins = dict(SOURCE_PINS)
    need(set(pins) == set(previous.reviewed_sources())
         and all(isinstance(v, str) and re.fullmatch('[a-f0-9]{64}', v) for v in pins.values()),
         'Complete reviewed backend source pins required')
    return pins


def source_guard():
    return ''.join("    need(manifest.get(" + repr(name) + ") == " + repr(digest)
                   + ", 'Reviewed assistant trip search source changed: " + name + "')\n"
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
    common = replace(common, 'shopping settlement', 'assistant trip search')
    operators['ops_common.py'] = common
    for name, count in (('build.py', 1), ('activate.py', 4), ('post_readback.py', 1)):
        operators[name] = replace(operators[name], 'expo-shopping-settlement', 'expo-assistant-trip-search', count=count)
    operators['activate.py'] = replace(operators['activate.py'], 'shopping settlement source publication', 'assistant trip search source publication')
    package = inputs[PREPARE_SOURCE].decode('utf-8')
    for name, value in {'A': 'Path(' + repr(str(access)) + ')', 'OUT': 'Path(' + repr(str(output / 'package')) + ')',
                        'CONTRACT': 'Path(' + repr(str(output / 'operators/expo_contract.py')) + ')',
                        'CONTRACT_SHA': repr(sha(operators['expo_contract.py'].encode()))}.items():
        package = assignment(package, name, value)
    for before, after in ((previous.OLD_MANIFEST, OLD_MANIFEST), (previous.OLD_ARCHIVE, OLD_ARCHIVE),
                          (previous.PARENT_IMAGE, PARENT_IMAGE), (repr(previous.UNCHANGED), repr(UNCHANGED)),
                          ('Wrong installed column mapping archive', 'Wrong installed shopping settlement archive')):
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
    need(output.parent == access and re.fullmatch('expo-assistant-trip-search-tools-[a-z0-9-]+', output.name),
         'New assistant trip search output must be directly under access root')
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
