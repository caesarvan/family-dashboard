"""Generate reviewed 55 -> 55 reschedule operators; never execute a release."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from deploy.holdings_release.prepare import assignment, need, replace, safe_path, sha, unique
from deploy.travel_release.prepare import SCRIPTS, function_replace, verify_generated
from deploy.trip_coordination_release import prepare as previous

BASE = 'trip-coordination-tools-20260917-r2/'
PINNED = {
    BASE + 'operators/ops_common.py': 'ae7ecb1532e110f0580a60df3a7f1e0ec48a3644ff650c26332e82c2a2e63468',
    BASE + 'operators/expo_contract.py': 'bf7624974a065467b6c56581710a185a7da38e01ad980fd9c4f857add7b96659',
    BASE + 'operators/build.py': 'b472b531037121431e44bbc2108e87be1290901f51c43ba94c35b4fd0a449b51',
    BASE + 'operators/validate.py': '3677fb98e1d2c4a55e62f3c20d48d6ca1d7fafaf9ce358809e6c42e1e55bda94',
    BASE + 'operators/stage.py': 'b2c97cc31499902adb67d901dec6efdee748b8a087981f737397bf2af652d74d',
    BASE + 'operators/activate.py': '88d7b476a2bacca712e71bb825bf5bcede519e50672cedc2b6790ef9fff91ebc',
    BASE + 'operators/post_readback.py': 'e3c37648c6d6eeef1077bc503ed61273e11bd12f52df60e4996aa9812a48c238',
    BASE + 'prepare-package.py': 'c3f884a42668a9b08e4d3ed54d4a3c6e0d52cea7656f10c14db54cfd2157ac79',
    BASE + 'bind-release.py': 'ebe86f7c29e32cf3e9f45cc268afd19603f3ea63de5c0ad9f3bad244db69a932',
}
OLD_MANIFEST = 'b2095ebe61b64980f5d9d87a17d5b11e434ecf7e378232cdc91b8ffadaf0334f'
OLD_ARCHIVE = 'e2314cd61234e3039fb988208e711aedee8a8c391e2cada68477b15dd2040c97'
PARENT_IMAGE = 'sha256:32b81bb0af5882333c1fafd5dfe9ca99b9eaf5c70999cd215dbe749bfad84c1a'
PREVIOUS_TESTS = previous.REQUIRED_TESTS
REQUIRED_TESTS = PREVIOUS_TESTS | {'tests/test_journey_reschedule.py', 'tests/test_journey_reschedule_release.py'}
FORBIDDEN_TESTS = previous.FORBIDDEN_TESTS
REQUIRED_CHANGED = {'Dockerfile', 'deploy/prepare_release.py', 'journey_workflows.py', 'frontend/src/screens/TripsScreen.tsx'}
REQUIRED_ADDED = {'journey_reschedule.py', 'frontend/src/screens/JourneyReschedulePanel.tsx',
                  'frontend/src/lib/journeyReschedule.ts', 'tests/test_journey_reschedule.py',
                  'deploy/journey_reschedule_release/prepare.py', 'tests/test_journey_reschedule_release.py'}
UNCHANGED = tuple(name for name in previous.UNCHANGED if name != 'Dockerfile') + (
    'member_sessions.py', 'journey_time.py', 'journey_places.py', 'calendar_publish.py')
# The installed Dockerfile is mixed-line-ending data. Permit only this exact
# reviewed old CRLF line becoming the new LF line; never normalize the whole file.
DOCKER_OLD = b'COPY finance_source_bridge.py journey_time.py ./\r\n'
DOCKER_NEW = b'COPY finance_source_bridge.py journey_time.py journey_reschedule.py ./\n'
DOCKER_CONTRACT = ("def verify_docker_delta(old, new):\n"
    "    before = " + repr(DOCKER_OLD) + "\n"
    "    after = " + repr(DOCKER_NEW) + "\n"
    "    need(old.count(before) == 1 and new == old.replace(before, after, 1), 'Only the reviewed journey_reschedule COPY addition is permitted')\n")


def adapt(inputs, access, output, config=None):
    operators = {name: inputs[BASE + 'operators/' + name].decode('utf-8') for name in SCRIPTS}
    operators['expo_contract.py'] = function_replace(operators['expo_contract.py'], 'verify_docker_delta', DOCKER_CONTRACT)
    common = operators['ops_common.py']
    for name, value in {'CANDIDATE': 'Path(' + repr('/opt/family-dashboard-candidates/' + output.name) + ')',
                        'PARENT_IMAGE': repr(PARENT_IMAGE), 'OLD_MANIFEST': repr(OLD_MANIFEST),
                        'EXPECTED_TEST_COUNT': repr(config['expectedTestCount'] if config else None),
                        'EXPECTED_TESTS': repr(tuple(config['validationTests']) if config else ())}.items():
        common = assignment(common, name, value)
    common = replace(common, '55 -> 55 trip coordination source-update guards', '55 -> 55 journey reschedule source-update guards')
    common = replace(common, repr(previous.UNCHANGED), repr(UNCHANGED))
    common = replace(common, "need({'investment_operations.py','calendar_publish.py','journey_places.py'} <= expected, 'Trip/finance runtime module absent')",
                     "need({'investment_operations.py','calendar_publish.py','journey_places.py','journey_reschedule.py'} <= expected, 'Trip/finance/reschedule runtime module absent')")
    operators['ops_common.py'] = common
    operators['build.py'] = replace(operators['build.py'], 'family-dashboard-trip-coordination:', 'family-dashboard-journey-reschedule:')
    operators['activate.py'] = replace(operators['activate.py'], 'trip-coordination', 'journey-reschedule', count=4)
    operators['post_readback.py'] = replace(operators['post_readback.py'], 'trip-coordination-55-', 'journey-reschedule-55-')
    operators['post_readback.py'] = replace(operators['post_readback.py'], "'/api/accounts','/api/journey-places','/api/journeys',",
        "'/api/accounts','/api/journey-places','/api/journeys','/api/journeys/'+'0'*24+'/reschedule','/api/journeys/operations/'+'0'*32,")
    prepare = inputs[BASE + 'prepare-package.py'].decode('utf-8')
    for name, value in {'A': 'Path(' + repr(str(access)) + ')', 'OUT': 'Path(' + repr(str(output / 'package')) + ')',
                        'CONTRACT': 'Path(' + repr(str(output / 'operators/expo_contract.py')) + ')',
                        'CONTRACT_SHA': repr(sha(operators['expo_contract.py'].encode()))}.items():
        prepare = assignment(prepare, name, value)
    for before, after in ((previous.OLD_MANIFEST, OLD_MANIFEST), (previous.OLD_ARCHIVE, OLD_ARCHIVE),
                          (previous.PARENT_IMAGE, PARENT_IMAGE), ('Wrong installed travel archive', 'Wrong installed trip coordination archive'),
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
    namespace = {'__name__': 'journey_reschedule_freeze_check', '__file__': str(access / 'reschedule-prepare-validation.py')}
    exec(compile(generated['prepare-package.py'], namespace['__file__'], 'exec'), namespace)
    namespace['validate_config'](config)
    return raw, config


def prepare(access, output, freeze=None):
    access, output = safe_path(access), safe_path(output, exists=False)
    need(output.parent == access and re.fullmatch('journey-reschedule-tools-[a-z0-9-]+', output.name), 'New reschedule output must be directly under access root')
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
