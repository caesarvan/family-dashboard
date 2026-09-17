"""Generate reviewed 55 -> 55 Expo device operators; never execute a release."""
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
from deploy.journey_reschedule_release import prepare as previous

BASE = 'journey-reschedule-tools-20260917-r1/'
PINNED = {
    BASE + 'operators/ops_common.py': '36d47cabc0cdf7895dc9b7efa60ad74d695f12d2f9e7960ab7fe6761716ad77a',
    BASE + 'operators/expo_contract.py': 'eebd52ce21067d54c01c2e4a541d0032d86e42e3222adf8e47f1f299004ffde8',
    BASE + 'operators/build.py': '5ca32fdecdf0c670d12d0b2652b41c9ee9401345adb2b054705cc76bb70c33da',
    BASE + 'operators/validate.py': '3677fb98e1d2c4a55e62f3c20d48d6ca1d7fafaf9ce358809e6c42e1e55bda94',
    BASE + 'operators/stage.py': 'b2c97cc31499902adb67d901dec6efdee748b8a087981f737397bf2af652d74d',
    BASE + 'operators/activate.py': '51734c39223db6461a23669244688ed6d7aee83e582c23a911f671cafe9e8359',
    BASE + 'operators/post_readback.py': '78b7cbf5eb3fda7cd06f49dea6c96157c5784fa10444101f741e85295d8f313f',
    BASE + 'prepare-package.py': '54e59c958c11da1c4ca1798161b9a364c077d56649154700688c15409d6c12ed',
    BASE + 'bind-release.py': 'ceaa6c168ab4c6fa31d3d266b8a4f3c1a2ae7256fdced6a800bbc40ad2ccb1d9',
}
OLD_MANIFEST = '0d07e455fbda2e22ddd69a47e733afbd2e6f520eba2a8fc315e6409286e4f384'
OLD_ARCHIVE = '8b3d994670549e8353714e0874870f2bb446876a0bd2223183aa724e59ae7373'
PARENT_IMAGE = 'sha256:b83c0d9c272c00932d10a21640f0902776189bbfbef6e82a8dc05463330c6250'
PREVIOUS_TESTS = previous.REQUIRED_TESTS
REQUIRED_TESTS = PREVIOUS_TESTS | {'tests/test_device_sessions.py', 'tests/test_tv_display.py',
    'tests/test_media_playback.py', 'tests/test_expo_devices_release.py'}
FORBIDDEN_TESTS = previous.FORBIDDEN_TESTS
REQUIRED_CHANGED = {'app.py', 'frontend/src/lib/types.ts', 'frontend/src/screens/HouseholdApp.tsx',
    'frontend/src/screens/OtherScreens.tsx', 'frontend/src/screens/PhotosScreen.tsx'}
REQUIRED_ADDED = {'frontend/src/screens/DevicesScreen.tsx', 'frontend/src/lib/devices.ts',
    'tests/test_device_sessions.py', 'tests/browser_expo_devices_check.py', 'tests/test_expo_devices.mjs',
    'deploy/expo_devices_release/prepare.py', 'tests/test_expo_devices_release.py'}
UNCHANGED = previous.UNCHANGED + ('Dockerfile', 'journey_workflows.py', 'journey_reschedule.py',
    'household_media.py', 'media_playback.py', 'tv_display.py')
DOCKER_CONTRACT = ("def verify_docker_delta(old, new):\n"
    "    need(old == new, 'Device release must preserve the installed Dockerfile exactly')\n")


def adapt(inputs, access, output, config=None):
    operators = {name: inputs[BASE + 'operators/' + name].decode('utf-8') for name in SCRIPTS}
    operators['expo_contract.py'] = function_replace(operators['expo_contract.py'], 'verify_docker_delta', DOCKER_CONTRACT)
    common = operators['ops_common.py']
    for name, value in {'CANDIDATE': 'Path(' + repr('/opt/family-dashboard-candidates/' + output.name) + ')',
                        'PARENT_IMAGE': repr(PARENT_IMAGE), 'OLD_MANIFEST': repr(OLD_MANIFEST),
                        'EXPECTED_TEST_COUNT': repr(config['expectedTestCount'] if config else None),
                        'EXPECTED_TESTS': repr(tuple(config['validationTests']) if config else ())}.items():
        common = assignment(common, name, value)
    common = replace(common, '55 -> 55 journey reschedule source-update guards', '55 -> 55 Expo device source-update guards')
    common = replace(common, repr(previous.UNCHANGED), repr(UNCHANGED))
    common = replace(common, "need({'investment_operations.py','calendar_publish.py','journey_places.py','journey_reschedule.py'} <= expected, 'Trip/finance/reschedule runtime module absent')",
                     "need({'investment_operations.py','calendar_publish.py','journey_places.py','journey_reschedule.py','media_playback.py','tv_display.py'} <= expected, 'Device/trip/finance runtime module absent')")
    operators['ops_common.py'] = common
    operators['build.py'] = replace(operators['build.py'], 'family-dashboard-journey-reschedule:', 'family-dashboard-expo-devices:')
    operators['activate.py'] = replace(operators['activate.py'], 'journey-reschedule', 'expo-devices', count=4)
    operators['post_readback.py'] = replace(operators['post_readback.py'], 'journey-reschedule-55-', 'expo-devices-55-')
    operators['post_readback.py'] = replace(operators['post_readback.py'], "'/app/connections','/app/finance'", "'/app/connections','/app/devices','/app/finance'")
    operators['post_readback.py'] = replace(operators['post_readback.py'], "'/api/accounts','/api/journey-places'",
        "'/api/accounts','/api/devices','/api/media-playback/devices/'+'0'*24,'/api/journey-places'")
    prepare = inputs[BASE + 'prepare-package.py'].decode('utf-8')
    for name, value in {'A': 'Path(' + repr(str(access)) + ')', 'OUT': 'Path(' + repr(str(output / 'package')) + ')',
                        'CONTRACT': 'Path(' + repr(str(output / 'operators/expo_contract.py')) + ')',
                        'CONTRACT_SHA': repr(sha(operators['expo_contract.py'].encode()))}.items():
        prepare = assignment(prepare, name, value)
    for before, after in ((previous.OLD_MANIFEST, OLD_MANIFEST), (previous.OLD_ARCHIVE, OLD_ARCHIVE),
                          (previous.PARENT_IMAGE, PARENT_IMAGE), ('Wrong installed trip coordination archive', 'Wrong installed journey reschedule archive'),
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
    namespace = {'__name__': 'expo_devices_freeze_check', '__file__': str(access / 'devices-prepare-validation.py')}
    exec(compile(generated['prepare-package.py'], namespace['__file__'], 'exec'), namespace)
    namespace['validate_config'](config)
    return raw, config


def prepare(access, output, freeze=None):
    access, output = safe_path(access), safe_path(output, exists=False)
    need(output.parent == access and re.fullmatch('expo-devices-tools-[a-z0-9-]+', output.name), 'New device output must be directly under access root')
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
