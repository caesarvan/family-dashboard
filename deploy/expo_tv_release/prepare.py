"""Generate a reviewed, unbound 55 -> 55 Expo television release; no remote actions."""
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
from deploy.expo_devices_release import prepare as previous

BASE = 'expo-devices-tools-20260917-r2/'
PREPARE_SOURCE = 'expo-devices-tools-20260917-r1/prepare-package.py'
PINNED = {
    BASE + 'operators/ops_common.py': '0d886b8f7493f6630530d1a6e1ec1cca4466a116d81aac9613cbf8c90019a308',
    BASE + 'operators/expo_contract.py': '87b27d86951c54cc44ed3619f256ec37d83d9c804624cb776e2ff97cc7ededbf',
    BASE + 'operators/build.py': 'd37b1fdb67b5411f633c882509a3a8e2090a98b4f803ac30e4ec9e03ad7e4ec7',
    BASE + 'operators/validate.py': '3c4de4349513bd8b8de5cd40c754fd3a0804c8f6f5c2d76ef1a02528605a2728',
    BASE + 'operators/stage.py': 'b2c97cc31499902adb67d901dec6efdee748b8a087981f737397bf2af652d74d',
    BASE + 'operators/activate.py': '84e12117900b8ee3bf60d456f208cc7a2054e17230b8558a53b1e5d705022b57',
    BASE + 'operators/post_readback.py': '9bdb6a7008623c916341ca85f22dd48a76f02569a82ccf929bb2c3b864f06356',
    PREPARE_SOURCE: '112b87c91cb30b38e8e5a194a4a1ac35ad516247593ce76a9ae7631f09cab49d',
    BASE + 'bind-release.py': '17274cd0b31ec98fa8783a3575a7139610a8027ceb3197daf7e34bdaeb23b89a',
}
OLD_MANIFEST = 'c51883945ec77ec0c6eb4fa1377cad4d60a4600d2daf36c1ee808b1b9815c3d8'
OLD_ARCHIVE = 'a8d823f475079ac0afe9a3a5c42496ffe98c562ece580ab9ef31002ae26f99ba'
PARENT_IMAGE = 'sha256:9a4e032f5817de67a995cd2a849f7c02c8c90ca8f87ffeb3644764b9f0fd2f62'
# Test the actual TV, identity, static-hosting and data-preservation dependencies.
# Unchanged finance/travel implementation is byte-bound instead of re-running
# every earlier feature's growing test union for this UI-only release.
REQUIRED_TESTS = {
    'tests/test_app.py', 'tests/test_frontend_runtime.py', 'tests/test_tv_display.py',
    'tests/test_device_sessions.py', 'tests/test_media_playback.py', 'tests/test_household_media.py',
    'tests/test_member_sessions.py', 'tests/test_household_spaces.py',
    'tests/test_platform_backup.py', 'tests/test_investment_operation_migration.py',
    'tests/test_expo_tv_release.py',
}
FORBIDDEN_TESTS = previous.FORBIDDEN_TESTS
REQUIRED_CHANGED = {'app.py', 'frontend_runtime.py', 'frontend/src/app/_layout.tsx', 'tests/test_frontend_runtime.py'}
REQUIRED_ADDED = {
    'frontend/src/app/tv.tsx', 'frontend/src/screens/TVScreen.tsx', 'frontend/src/lib/tv.ts',
    'frontend/src/ui/TVBoard.tsx', 'frontend/src/ui/TVBoard.model.ts',
    'frontend/src/ui/TVPhotoPlayer.tsx', 'frontend/src/ui/TVPhotoPlayer.web.tsx', 'frontend/src/ui/TVPhotoPlayer.model.ts',
    'tests/browser_expo_tv_check.py', 'tests/expo_tv_model_test.mjs', 'tests/test_tv_photo_player.mjs',
    'deploy/expo_tv_release/prepare.py', 'tests/test_expo_tv_release.py',
}
UNCHANGED = previous.UNCHANGED + ('frontend/package.json', 'frontend/package-lock.json',
    'household_spaces.py', 'member_sessions.py', 'home_assistant.py', 'cloud_accounts.py')
DOCKER_CONTRACT = previous.DOCKER_CONTRACT


def adapt(inputs, access, output, config=None):
    operators = {name: inputs[BASE + 'operators/' + name].decode('utf-8') for name in SCRIPTS}
    common = operators['ops_common.py']
    for name, value in {'CANDIDATE': 'Path(' + repr('/opt/family-dashboard-candidates/' + output.name) + ')',
                        'PARENT_IMAGE': repr(PARENT_IMAGE), 'OLD_MANIFEST': repr(OLD_MANIFEST),
                        'EXPECTED_TEST_COUNT': repr(config['expectedTestCount'] if config else None),
                        'EXPECTED_TESTS': repr(tuple(config['validationTests']) if config else ())}.items():
        common = assignment(common, name, value)
    common = replace(common, '55 -> 55 Expo device source-update guards', '55 -> 55 Expo television source-update guards')
    common = replace(common, repr(previous.UNCHANGED), repr(UNCHANGED))
    operators['ops_common.py'] = common
    operators['build.py'] = replace(operators['build.py'], 'family-dashboard-expo-devices:', 'family-dashboard-expo-tv:')
    operators['activate.py'] = replace(operators['activate.py'], 'expo-devices', 'expo-tv', count=4)
    post = replace(operators['post_readback.py'], 'expo-devices-55-', 'expo-tv-55-')
    post = replace(post, "'/app/devices','/app/finance'", "'/app/devices','/app/tv','/tv','/app/finance'")
    post = replace(post, "('/classic','/tv','/demo')", "('/classic','/tv?classic=1','/demo')")
    post = replace(post, "if path=='/':need(response.geturl()==origin+'/app','Home did not redirect to Expo')",
        "if path=='/':need(response.geturl()==origin+'/app','Home did not redirect to Expo')\n"
        "            if path=='/tv':need(response.geturl()==origin+'/app/tv','TV did not redirect to Expo display')")
    operators['post_readback.py'] = post
    prepare = inputs[PREPARE_SOURCE].decode('utf-8')
    for name, value in {'A': 'Path(' + repr(str(access)) + ')', 'OUT': 'Path(' + repr(str(output / 'package')) + ')',
                        'CONTRACT': 'Path(' + repr(str(output / 'operators/expo_contract.py')) + ')',
                        'CONTRACT_SHA': repr(sha(operators['expo_contract.py'].encode()))}.items():
        prepare = assignment(prepare, name, value)
    for before, after in ((previous.OLD_MANIFEST, OLD_MANIFEST), (previous.OLD_ARCHIVE, OLD_ARCHIVE),
                          (previous.PARENT_IMAGE, PARENT_IMAGE), ('Wrong installed journey reschedule archive', 'Wrong installed Expo devices archive'),
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
    namespace = {'__name__': 'expo_tv_freeze_check', '__file__': str(access / 'tv-prepare-validation.py')}
    exec(compile(generated['prepare-package.py'], namespace['__file__'], 'exec'), namespace)
    namespace['validate_config'](config)
    return raw, config


def prepare(access, output, freeze=None):
    access, output = safe_path(access), safe_path(output, exists=False)
    need(output.parent == access and re.fullmatch('expo-tv-tools-[a-z0-9-]+', output.name), 'New TV output must be directly under access root')
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
