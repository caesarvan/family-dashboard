"""Generate unbound photo suggestion operators from the published 58-table release.

Only the independently reviewed household_media session fix may change backend
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
from deploy.expo_trip_recap_release import prepare as previous

BASE = 'expo-trip-recap-tools-20260918-r1/'
PREPARE_SOURCE = BASE + 'prepare-package.py'
PINNED = {
    BASE + 'operators/ops_common.py': 'bfb46e99aaeeabbf6801590922135b9b1a7e7a9011293dff3294c329d6ac75cd',
    BASE + 'operators/expo_contract.py': '03ff8c5be225482a913da109a30efa243bc1cc31a83a3d401ef7e5d7d666d95b',
    BASE + 'operators/build.py': '279be3de85184ae37420913c9911e0b50104f27ac24a058f5d8f61602642183a',
    BASE + 'operators/validate.py': '5d01889df2b86772915dcd643398fb3e8915cadee807a82aa7625ebc767a7c46',
    BASE + 'operators/stage.py': '0f52d72b2e145df966a9b2e78b6764f4a4a2384fee46e1b4a2709b6df5966a75',
    BASE + 'operators/activate.py': '5af24df0b1c70f2520b48aa2b19f9ee47bf5905185e5cb8d6112b30aed07bcee',
    BASE + 'operators/post_readback.py': 'fd468acce6e262071b001ae02b0f8aa8793d30fae76c18dd99b192779fe719fd',
    PREPARE_SOURCE: 'ba987da975c388c21f9fc4d802fed59b80ff51d8079f659522a7618c66087350',
    BASE + 'bind-release.py': '3090321ff60b3530dc7428c7872ca13cf0baa171df34cd083686a4ab3cd231c5',
}
OLD_ARCHIVE = 'efb82e79139454a6239b947d3ede510940930cb0fdf19c339850b31878cc4b1e'
OLD_MANIFEST = '2504bf48bf4d6275958a1bd2fc0b54efde933d88b7f918c1856fe0a2b245ca77'
PARENT_IMAGE = 'sha256:e7994bbca9f2b5d2116e1f8e1fb0db866c997be6477c89473983e9b125ece73b'
MEDIA_SOURCE_SHA256 = '63f2116462f66a33f851720b76234ada4686cff90f769c66441ae6fc109463a1'
REQUIRED_TESTS = (previous.REQUIRED_TESTS - {'tests/test_expo_trip_recap_release.py'}) | {
    'tests/test_media_journey_suggestions.py', 'tests/test_media_suggestion_sessions.py',
    'tests/test_expo_photo_suggestions_release.py',
}
FORBIDDEN_TESTS = previous.FORBIDDEN_TESTS
REQUIRED_CHANGED = {'frontend/src/screens/PhotosScreen.tsx', 'household_media.py'}
REQUIRED_ADDED = {
    'frontend/src/components/PhotoJourneySuggestions.tsx', 'frontend/src/lib/photoJourneySuggestions.ts',
    'tests/test_expo_photo_suggestions.mjs', 'tests/browser_expo_photo_suggestions_check.py',
    'tests/test_media_suggestion_sessions.py', 'deploy/expo_photo_suggestions_release/prepare.py',
    'tests/test_expo_photo_suggestions_release.py',
}
BACKEND_UNCHANGED = tuple(name for name in previous.BACKEND_UNCHANGED if name != 'household_media.py')
UNCHANGED = tuple(name for name in previous.UNCHANGED if name != 'household_media.py')
LOCAL_BUILD_SOURCES = previous.LOCAL_BUILD_SOURCES
PRESERVATION_FUNCTION = previous.PRESERVATION_FUNCTION
verify_generated = previous.verify_generated
DOCKER_CONTRACT = previous.DOCKER_CONTRACT.replace('Trip Recap', 'photo suggestions')
MEDIA_GUARD = "    need(manifest.get('household_media.py') == " + repr(MEDIA_SOURCE_SHA256) + ", 'Reviewed photo session source changed')\n"


def adapt(inputs, access, output, config=None):
    operators = {name: inputs[BASE + 'operators/' + name].decode('utf-8') for name in SCRIPTS}
    operators['expo_contract.py'] = function_replace(operators['expo_contract.py'], 'verify_docker_delta', DOCKER_CONTRACT)
    common = operators['ops_common.py']
    for name, value in {'CANDIDATE': 'Path(' + repr('/opt/family-dashboard-candidates/' + output.name) + ')',
                        'PARENT_IMAGE': repr(PARENT_IMAGE), 'OLD_MANIFEST': repr(OLD_MANIFEST),
                        'EXPECTED_TEST_COUNT': repr(config['expectedTestCount'] if config else None),
                        'EXPECTED_TESTS': repr(tuple(config['validationTests']) if config else ())}.items():
        common = assignment(common, name, value)
    common = replace(common, 'Trip Recap', 'photo suggestions')
    common = replace(common, repr(previous.UNCHANGED), repr(UNCHANGED))
    common = replace(common, "    need(all(name in manifest for name in config['validationTests'])",
                     MEDIA_GUARD + "    need(all(name in manifest for name in config['validationTests'])")
    operators['ops_common.py'] = common
    for name in ('build.py', 'activate.py', 'post_readback.py'):
        operators[name] = operators[name].replace('expo-trip-recap', 'expo-photo-suggestions').replace('Trip Recap', 'photo suggestions')
    # Parent already contains the reviewed batch Git reader. Do not transform it again.
    package = inputs[PREPARE_SOURCE].decode('utf-8')
    for name, value in {'A': 'Path(' + repr(str(access)) + ')', 'OUT': 'Path(' + repr(str(output / 'package')) + ')',
                        'CONTRACT': 'Path(' + repr(str(output / 'operators/expo_contract.py')) + ')',
                        'CONTRACT_SHA': repr(sha(operators['expo_contract.py'].encode()))}.items():
        package = assignment(package, name, value)
    for before, after in ((previous.OLD_MANIFEST, OLD_MANIFEST), (previous.OLD_ARCHIVE, OLD_ARCHIVE),
                          (previous.PARENT_IMAGE, PARENT_IMAGE), (repr(previous.UNCHANGED), repr(UNCHANGED)),
                          ('Wrong installed manual accounts archive', 'Wrong installed Trip Recap archive')):
        package = replace(package, before, after)
    for field, old, new in (('validationTests', previous.REQUIRED_TESTS, REQUIRED_TESTS),
                            ('changedFiles', previous.REQUIRED_CHANGED, REQUIRED_CHANGED),
                            ('addedFiles', previous.REQUIRED_ADDED, REQUIRED_ADDED)):
        package = replace(package, 'set(' + repr(sorted(old)) + ") <= set(value['" + field + "'])", 'set(' + repr(sorted(new)) + ") <= set(value['" + field + "'])")
    package = replace(package, 'set(' + repr(sorted(previous.REQUIRED_CHANGED | previous.REQUIRED_ADDED)) + ') <= selected',
                      'set(' + repr(sorted(REQUIRED_CHANGED | REQUIRED_ADDED)) + ') <= selected')
    package = replace(package, '    delta = verify_delta(old, manifest, config, contract)',
                      MEDIA_GUARD + '    delta = verify_delta(old, manifest, config, contract)')
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
    need(output.parent == access and re.fullmatch('expo-photo-suggestions-tools-[a-z0-9-]+', output.name),
         'New suggestion output must be directly under access root')
    need(not output.exists(), 'Output exists; preserve prior attempts')
    inputs = read_sources(access); generated = adapt(inputs, access, output)
    freeze_raw, config = previous.freeze_config(freeze, access, generated) if freeze else (None, None)
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
        'reviewedMediaSourceSha256': MEDIA_SOURCE_SHA256,
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
