"""Generate unbound trip import operators from the published 58-table release.

Only the independently reviewed journey_workflows session fix may change backend
bytes. Generation never packages, binds or contacts production.
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
from deploy.travel_release.prepare import SCRIPTS, function_replace
from deploy.expo_photo_suggestions_release import prepare as previous

BASE = 'expo-photo-suggestions-tools-20260918-r1/'
PREPARE_SOURCE = BASE + 'prepare-package.py'
PINNED = {
    BASE + 'operators/ops_common.py': '504a3a1d715c2434f7789cd7a4c6cff443d68389f2490b1d13684718abc4e903',
    BASE + 'operators/expo_contract.py': 'a83cf895bb5afa6463b59ead8dacc0ab37eb74da045e890deca45b67e7e2039a',
    BASE + 'operators/build.py': 'fbafa8a1be545998eb9cca27469bd1349f6a8eae60ea067dd27582ce4ce0a01f',
    BASE + 'operators/validate.py': '5d01889df2b86772915dcd643398fb3e8915cadee807a82aa7625ebc767a7c46',
    BASE + 'operators/stage.py': '0f52d72b2e145df966a9b2e78b6764f4a4a2384fee46e1b4a2709b6df5966a75',
    BASE + 'operators/activate.py': '540da7bd4b013ad56eab823feff65ee889ca35aa0398d6c99d4a7f3a6c05c783',
    BASE + 'operators/post_readback.py': 'fa4e45c02645f4f9eb53bffb969ea1983321e1d65df644a996f05161bd74f3eb',
    BASE + 'prepare-package.py': 'f7bf91999c7e6b244d9ac6544a7c7cf0f4d6817b8e24f0e13d4e84ca1983d5d4',
    BASE + 'bind-release.py': '524edf63d5e1a490e6ee537a678e85be205646d19fa7ebb7f0168a7a3b6b885e',
}
OLD_ARCHIVE = 'a14d695ed265b7ee136a0275042ef62d124179db5a0697e4457cdce69376230f'
OLD_MANIFEST = 'da2a4cb1f44debec1e2c458b2f92a80de6b813842af04ba28cdb303333a21eb4'
PARENT_IMAGE = 'sha256:4235322eb02f02d1533e479194331c324aa095850fe08d1540e02088342a1104'
JOURNEY_SOURCE_SHA256 = 'ed2e81503361dd4ab25a13956c7c307e872cf5b2c820131e57400ca178475295'
REQUIRED_TESTS = {
    'tests/test_frontend_runtime.py', 'tests/test_household_spaces.py',
    'tests/test_platform_backup.py', 'tests/test_finance_accounts_migration.py',
    'tests/test_journey_workflows.py', 'tests/test_journey_details.py',
    'tests/test_journey_edit_snapshot.py', 'tests/test_journey_transaction_session.py',
    'tests/test_journey_reschedule.py', 'tests/test_journey_import_sessions.py',
    'tests/test_journey_examples.py', 'tests/test_expo_trip_import_release.py',
}
FORBIDDEN_TESTS = previous.FORBIDDEN_TESTS
REQUIRED_CHANGED = {
    'frontend/src/lib/types.ts', 'frontend/src/screens/TripsScreen.tsx',
    'frontend/src/screens/HouseholdApp.tsx', 'frontend/src/screens/MapWorkspace.tsx',
    'frontend/src/screens/AssistantScreen.tsx', 'journey_workflows.py',
}
REQUIRED_ADDED = {
    'frontend/src/components/TripImportPanel.tsx', 'frontend/src/lib/tripImport.ts',
    'tests/test_expo_trip_import.mjs', 'tests/browser_expo_trip_import_check.py',
    'tests/test_journey_import_sessions.py', 'deploy/expo_trip_import_release/prepare.py',
    'tests/test_expo_trip_import_release.py',
}
BACKEND_UNCHANGED = tuple(name for name in (*previous.BACKEND_UNCHANGED, 'household_media.py') if name != 'journey_workflows.py')
UNCHANGED = tuple(name for name in (*previous.UNCHANGED, 'household_media.py') if name != 'journey_workflows.py')
LOCAL_BUILD_SOURCES = previous.LOCAL_BUILD_SOURCES
PRESERVATION_FUNCTION = previous.PRESERVATION_FUNCTION
verify_generated = previous.verify_generated
DOCKER_CONTRACT = previous.DOCKER_CONTRACT.replace('photo suggestions', 'trip imports')
JOURNEY_GUARD = "    need(manifest.get('journey_workflows.py') == " + repr(JOURNEY_SOURCE_SHA256) + ", 'Reviewed journey session source changed')\n"


def adapt(inputs, access, output, config=None):
    need(isinstance(JOURNEY_SOURCE_SHA256, str) and re.fullmatch('[a-f0-9]{64}', JOURNEY_SOURCE_SHA256), 'Reviewed journey source pin is required')
    operators = {name: inputs[BASE + 'operators/' + name].decode('utf-8') for name in SCRIPTS}
    operators['expo_contract.py'] = function_replace(operators['expo_contract.py'], 'verify_docker_delta', DOCKER_CONTRACT)
    common = operators['ops_common.py']
    for name, value in {'CANDIDATE': 'Path(' + repr('/opt/family-dashboard-candidates/' + output.name) + ')',
                        'PARENT_IMAGE': repr(PARENT_IMAGE), 'OLD_MANIFEST': repr(OLD_MANIFEST),
                        'EXPECTED_TEST_COUNT': repr(config['expectedTestCount'] if config else None),
                        'EXPECTED_TESTS': repr(tuple(config['validationTests']) if config else ())}.items():
        common = assignment(common, name, value)
    common = replace(common, 'photo suggestions', 'trip imports')
    common = replace(common, repr(previous.UNCHANGED), repr(UNCHANGED))
    common = replace(common, "    need(all(name in manifest for name in config['validationTests'])",
                     JOURNEY_GUARD + "    need(all(name in manifest for name in config['validationTests'])")
    operators['ops_common.py'] = common
    for name in ('build.py', 'activate.py', 'post_readback.py'):
        operators[name] = operators[name].replace('expo-photo-suggestions', 'expo-trip-import').replace('photo suggestions', 'trip imports')
    # Parent already contains the reviewed batch Git reader. Do not transform it again.
    package = inputs[PREPARE_SOURCE].decode('utf-8')
    for name, value in {'A': 'Path(' + repr(str(access)) + ')', 'OUT': 'Path(' + repr(str(output / 'package')) + ')',
                        'CONTRACT': 'Path(' + repr(str(output / 'operators/expo_contract.py')) + ')',
                        'CONTRACT_SHA': repr(sha(operators['expo_contract.py'].encode()))}.items():
        package = assignment(package, name, value)
    for before, after in ((previous.OLD_MANIFEST, OLD_MANIFEST), (previous.OLD_ARCHIVE, OLD_ARCHIVE),
                          (previous.PARENT_IMAGE, PARENT_IMAGE), (repr(previous.UNCHANGED), repr(UNCHANGED)),
                          ('Wrong installed Trip Recap archive', 'Wrong installed photo suggestions archive')):
        package = replace(package, before, after)
    for field, old, new in (('validationTests', previous.REQUIRED_TESTS, REQUIRED_TESTS),
                            ('changedFiles', previous.REQUIRED_CHANGED, REQUIRED_CHANGED),
                            ('addedFiles', previous.REQUIRED_ADDED, REQUIRED_ADDED)):
        package = replace(package, 'set(' + repr(sorted(old)) + ") <= set(value['" + field + "'])", 'set(' + repr(sorted(new)) + ") <= set(value['" + field + "'])")
    package = replace(package, 'set(' + repr(sorted(previous.REQUIRED_CHANGED | previous.REQUIRED_ADDED)) + ') <= selected',
                      'set(' + repr(sorted(REQUIRED_CHANGED | REQUIRED_ADDED)) + ') <= selected')
    package = replace(package, '    delta = verify_delta(old, manifest, config, contract)',
                      JOURNEY_GUARD + '    delta = verify_delta(old, manifest, config, contract)')
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
    access, output = safe_path(access), safe_path(output, exists=False)
    need(output.parent == access and re.fullmatch('expo-trip-import-tools-[a-z0-9-]+', output.name),
         'New trip import output must be directly under access root')
    need(not output.exists(), 'Output exists; preserve prior attempts')
    inputs = read_sources(access); generated = adapt(inputs, access, output)
    freeze_raw, config = previous.previous.freeze_config(freeze, access, generated) if freeze else (None, None)
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
        'expectedTestCount': config['expectedTestCount'] if config else None, 'profile': 'finance_accounts58',
        'householdTablesBefore': 58, 'householdTablesAfter': 58, 'schemaChange': False,
        'serverCandidate': '/opt/family-dashboard-candidates/' + output.name, 'oldManifestSha256': OLD_MANIFEST,
        'reviewedJourneySourceSha256': JOURNEY_SOURCE_SHA256,
        'sourceHashes': PINNED, 'generatedHashes': {name: sha(raw) for name, raw in generated.items()},
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
