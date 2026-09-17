"""Generate unbound 58 -> 58 Trip Recap operators from pinned local originals.

Generation is local only. Packaging, binding and all server phases remain separate.
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from deploy.holdings_release.prepare import assignment, need, replace, safe_path, sha, unique
from deploy.travel_release.prepare import SCRIPTS, function_replace
from deploy.finance_accounts_release import prepare as previous
from deploy.packager_batch_read import transform_prepare

BASE = 'finance-accounts-tools-20260917-r1/'
PREPARE_SOURCE = BASE + 'prepare-package.py'
PINNED = {
    BASE + 'operators/ops_common.py': '52dc63d5e514e40d50753a093f9f63c2d9bd21e6ad127bec7320169d94e7f8b9',
    BASE + 'operators/expo_contract.py': '0b53d579f3c742bdaa33054b318af9d89e15b6f6e4c3bb05b28d9fea7e9f3184',
    BASE + 'operators/build.py': 'f1114c2d8feb28a857c58cbacb5098e2ae7c16a9ad3d27c368552c672011a8a7',
    BASE + 'operators/validate.py': '5d01889df2b86772915dcd643398fb3e8915cadee807a82aa7625ebc767a7c46',
    BASE + 'operators/stage.py': '314b7d8cf3e8961673069e0118ce39cd990ef2e488103f356ed6da26558d563b',
    BASE + 'operators/activate.py': 'a49e30e7e5b8a90bb8bcfd12b35bc89f0051d78134db32e96777ddc13b4e45b8',
    BASE + 'operators/post_readback.py': '574edcd2889088b7476bc762775deb31bfd6fa1730480f383ab549708dfb4647',
    PREPARE_SOURCE: 'b3db5b55d2fe26ec2596230ad4677176361e3545abece727838c6c51eddffc3a',
    BASE + 'bind-release.py': '6ec8136b07d67a9aea60cefbc579cf99cbc8dba55a60be1d6b3a2231af1af484',
}
OLD_ARCHIVE = '146e8e3553e8b4fcf00363a396414ee8f3da021f5fb68ecc588cbfee69dad74e'
OLD_MANIFEST = '16aa062f50fb203a5b6a1da4150824613a6989f517cccf3aac65ee81a931a763'
PARENT_IMAGE = 'sha256:6974cdb6cc98869d8cdc55927c7a1be05d941aaef76382645b1fbd8dfe422ad7'
REQUIRED_TESTS = {
    'tests/test_frontend_runtime.py', 'tests/test_household_spaces.py',
    'tests/test_platform_backup.py', 'tests/test_finance_accounts_migration.py',
    'tests/test_journey_workflows.py', 'tests/test_journey_places.py',
    'tests/test_household_media.py', 'tests/test_expo_trip_recap_release.py',
}
FORBIDDEN_TESTS = previous.FORBIDDEN_TESTS
REQUIRED_CHANGED = {'frontend/src/screens/TripsScreen.tsx'}
REQUIRED_ADDED = {
    'frontend/src/components/TripRecapPanel.tsx', 'frontend/src/lib/tripRecap.ts',
    'tests/test_expo_trip_recap.mjs', 'tests/browser_expo_trip_recap_check.py',
    'deploy/expo_trip_recap_release/prepare.py', 'tests/test_expo_trip_recap_release.py',
    'deploy/packager_batch_read.py', 'tests/test_packager_batch_read.py',
}
BACKEND_UNCHANGED = previous.previous.BACKEND_UNCHANGED + ('finance_accounts.py',)
LOCAL_BUILD_SOURCES = previous.LOCAL_BUILD_SOURCES
UNCHANGED = previous.UNCHANGED + tuple(name for name in (
    *BACKEND_UNCHANGED, 'Dockerfile', 'deploy/prepare_release.py',
    'deploy/check_finance_accounts_migration.py', 'deploy/git_blobs.py',
) if name not in previous.UNCHANGED)

DOCKER_CONTRACT = '''def verify_docker_delta(old, new):
    need(old == new, 'Dockerfile must remain byte-identical for Trip Recap')
'''
PRESERVATION_RESULT = "{'originalTablesPreserved':58,'newTables':0,'households':len(before['households']),\n         'allRowsSchemaAndSequencesPreserved':True,'registryPreserved':True}"
# verify_current accepts populated account tables. Full snapshot equality includes
# every row/blob, SQL schema, sequence and registry entry, not just table counts.
PRESERVATION_FUNCTION = '''
def verify_preserved(before,after,schema):
    verify_current(before,schema)
    verify_current(after,schema)
    if before != after:
        raise RuntimeError('Existing 58-table rows/schema/sequences or registry changed')
    return ''' + PRESERVATION_RESULT + '\n'


def verify_generated(raw, name):
    def check(tree):
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                called = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ''
                need(called not in {'migrate', 'verify_baseline', 'verify_addition', 'initialize_database',
                                   'create_app', 'executescript'}, 'Migration/initialization forbidden in ' + name)
                if called in ('execute', 'executemany'):
                    need(node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
                         and node.args[0].value.lstrip().upper().startswith(('SELECT ', 'PRAGMA ')), 'Inline mutating SQL forbidden')
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                try:
                    nested = ast.parse(node.value)
                except (SyntaxError, ValueError):
                    continue
                if any(isinstance(item, (ast.Call, ast.ImportFrom)) for item in ast.walk(nested)):
                    check(nested)
    check(ast.parse(raw, filename=name))


def activate_operator(code):
    code = replace(code, '55 -> 58 manual account publication', '58 -> 58 Trip Recap source publication')
    code = replace(code, 'finance-accounts', 'expo-trip-recap', count=4)
    code = replace(code, "ready.get('householdTablesBefore')==55 and ready.get('schemaChange') is True", "ready.get('householdTablesBefore')==58 and ready.get('schemaChange') is False")
    code = replace(code, '55-to-58 migration was not staged', '58-table preservation was not staged')
    code = replace(code, 'schema_definition,snapshot,verify_baseline,verify_current,validate_backup,migrate,verify_addition',
                   'schema_definition,snapshot,verify_current,validate_backup')
    marker = '    snapshot_program=schema_guard+'
    need(code.count(marker) == 1, 'Expected schema guard boundary')
    code = code.replace(marker, '    schema_guard += ' + repr(PRESERVATION_FUNCTION) + '\n' + marker)
    code = replace(code, 'verify_baseline(value)', 'verify_current(value,schema)')
    code = replace(code, 'verify_baseline(before)', 'verify_current(before,schema)')
    code = replace(code, 'complete_55_table_household_and_registry_backup_validated_and_preserved', 'complete_58_table_household_and_registry_backup_validated_and_preserved')
    # Match the complete fixed parent's migration block, rather than deleting a
    # broad range that could silently discard a later added safety check.
    migration = "    need(diagnostic(snapshot_program)==before, 'Data changed before migration')\n" + \
        '    migration_program=schema_guard+' + json.dumps(previous.MIGRATION_PROGRAM) + '\n' + \
        "    migration_result=diagnostic(migration_program)\n    need(migration_result==" + previous.ADDITION_RESULT + \
        ", 'Unexpected migration result')\n    write_new(proof/'migration.json',migration_result)\n" + \
        "    migrated=diagnostic(current_program)\n    write_new(proof/'after-migration.json',migrated);os.chown(proof/'after-migration.json',10001,10001)\n" + \
        "    record('exact_three_empty_tables_added_original_55_and_registry_preserved')"
    code = replace(code, migration, "    need(diagnostic(current_program)==before, 'Data changed before source installation')\n    record('all_58_tables_and_registry_unchanged_before_source_installation')")
    code = replace(code, "need(after==migrated, 'App startup changed migrated 58-table data/schema/sequences or registry')", "need(after==before, 'App startup changed 58-table data/schema/sequences or registry')")
    code = replace(code, 'verify_addition(before,after,schema)', 'verify_preserved(before,after,schema)')
    code = replace(code, previous.ADDITION_RESULT, PRESERVATION_RESULT)
    code = replace(code, 'new_app_healthy_all_58_tables_unchanged_since_exact_migration', 'new_app_healthy_all_58_tables_rows_schema_sequences_and_registry_unchanged')
    code = replace(code, 'schemaChange=True,migrationResult=migration_result', 'schemaChange=False')
    return code


def post_operator(code):
    code = replace(code, 'finance-accounts-58-', 'expo-trip-recap-58-')
    code = replace(code, "('before.json','after-migration.json','migration.json','after-app.json','preservation.json')", "('before.json','after-app.json','preservation.json')")
    old = """    need(activation_snapshot==read(proof_root/'after-migration.json')
         and preservation==published['preservationResult']==published['migrationResult']==read(proof_root/'migration.json')
         and preservation=={'originalTablesPreserved':55,'newTables':3,'households':published['households'],
             'newTablesEmpty':True,'oldRowsSchemaAndSequencesPreserved':True,'registryPreserved':True}
         and published['householdTables']==58 and published['schemaChange'] is True
         and published['allExistingDataPreservedAtAppStartup'] is True,
         'Completed 55-to-58 migration/startup evidence differs')
    addition_program="from pathlib import Path;import json,sys;sys.path.insert(0,'/release');from deploy.check_finance_accounts_migration import schema_definition,verify_addition;v=json.load(sys.stdin);print(json.dumps(verify_addition(v['before'],v['after'],schema_definition())))"
    checked_addition=subprocess.run(readonly_backup_args(image)[:3]+['-i']+readonly_backup_args(image)[3:]+['-c',addition_program],
        input=json.dumps({'before':read(proof_root/'before.json'),'after':activation_snapshot}),capture_output=True,text=True,cwd=ROOT)
    need(checked_addition.returncode==0 and json.loads(checked_addition.stdout)==preservation,
         'Activation original tables/schema/sequences or registry differ')
"""
    program = "from pathlib import Path\nimport json,sys\nsys.path.insert(0,'/release')\nfrom deploy.check_finance_accounts_migration import schema_definition,verify_current\n" + PRESERVATION_FUNCTION + "v=json.load(sys.stdin)\nprint(json.dumps(verify_preserved(v['before'],v['after'],schema_definition())))\n"
    new = """    need(activation_snapshot==read(proof_root/'before.json')
         and preservation==published['preservationResult']
         and preservation=={'originalTablesPreserved':58,'newTables':0,'households':published['households'],
             'allRowsSchemaAndSequencesPreserved':True,'registryPreserved':True}
         and published['householdTables']==58 and published['schemaChange'] is False
         and published['allExistingDataPreservedAtAppStartup'] is True,
         'Completed 58-table preservation/startup evidence differs')
    preservation_program=""" + repr(program) + """
    checked_preservation=subprocess.run(readonly_backup_args(image)[:3]+['-i']+readonly_backup_args(image)[3:]+['-c',preservation_program],
        input=json.dumps({'before':read(proof_root/'before.json'),'after':activation_snapshot}),capture_output=True,text=True,cwd=ROOT)
    need(checked_preservation.returncode==0 and json.loads(checked_preservation.stdout)==preservation,
         'Activation original tables/schema/sequences or registry differ')
"""
    return replace(code, old, new)


def adapt(inputs, access, output, config=None):
    operators = {name: inputs[BASE + 'operators/' + name].decode('utf-8') for name in SCRIPTS}
    operators['expo_contract.py'] = function_replace(operators['expo_contract.py'], 'verify_docker_delta', DOCKER_CONTRACT)
    common = operators['ops_common.py']
    for name, value in {'CANDIDATE': 'Path(' + repr('/opt/family-dashboard-candidates/' + output.name) + ')',
                        'PARENT_IMAGE': repr(PARENT_IMAGE), 'OLD_MANIFEST': repr(OLD_MANIFEST),
                        'EXPECTED_TEST_COUNT': repr(config['expectedTestCount'] if config else None),
                        'EXPECTED_TESTS': repr(tuple(config['validationTests']) if config else ())}.items():
        common = assignment(common, name, value)
    common = replace(common, '55 -> 58 manual account release guards', '58 -> 58 Trip Recap source-update guards')
    operators['ops_common.py'] = replace(common, repr(previous.UNCHANGED), repr(UNCHANGED))
    operators['build.py'] = replace(operators['build.py'], 'family-dashboard-finance-accounts:', 'family-dashboard-expo-trip-recap:')
    operators['stage.py'] = replace(operators['stage.py'], 'householdTablesBefore=55,householdTablesAfter=58,schemaChange=True', 'householdTablesBefore=58,householdTablesAfter=58,schemaChange=False')
    operators['activate.py'] = activate_operator(operators['activate.py'])
    operators['post_readback.py'] = post_operator(operators['post_readback.py'])
    # The reviewed opt-in transformation is applied only after read_sources has
    # verified the exact original parent. No existing tool is modified in place.
    prepare = transform_prepare(inputs[PREPARE_SOURCE]).decode('utf-8')
    for name, value in {'A': 'Path(' + repr(str(access)) + ')', 'OUT': 'Path(' + repr(str(output / 'package')) + ')',
                        'CONTRACT': 'Path(' + repr(str(output / 'operators/expo_contract.py')) + ')',
                        'CONTRACT_SHA': repr(sha(operators['expo_contract.py'].encode()))}.items():
        prepare = assignment(prepare, name, value)
    for before, after in ((previous.OLD_MANIFEST, OLD_MANIFEST), (previous.OLD_ARCHIVE, OLD_ARCHIVE),
                          (previous.PARENT_IMAGE, PARENT_IMAGE), (repr(previous.UNCHANGED), repr(UNCHANGED)),
                          ('Wrong installed source R2 archive', 'Wrong installed manual accounts archive')):
        prepare = replace(prepare, before, after)
    for field, old, new in (('validationTests', previous.REQUIRED_TESTS, REQUIRED_TESTS),
                            ('changedFiles', previous.REQUIRED_CHANGED, REQUIRED_CHANGED),
                            ('addedFiles', previous.REQUIRED_ADDED, REQUIRED_ADDED)):
        prepare = replace(prepare, 'set(' + repr(sorted(old)) + ") <= set(value['" + field + "'])", 'set(' + repr(sorted(new)) + ") <= set(value['" + field + "'])")
    prepare = replace(prepare, 'set(' + repr(sorted(previous.REQUIRED_CHANGED | previous.REQUIRED_ADDED)) + ') <= selected', 'set(' + repr(sorted(REQUIRED_CHANGED | REQUIRED_ADDED)) + ') <= selected')
    binder = inputs[BASE + 'bind-release.py'].decode('utf-8')
    for name, value in {'A': access, 'PACK': output / 'package', 'OPS': output / 'operators', 'PREPARE': output / 'prepare-package.py'}.items():
        binder = assignment(binder, name, 'Path(' + repr(str(value)) + ')')
    generated = {'operators/' + name: code.encode() for name, code in operators.items()}
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
    raw = path.read_bytes(); need(len(raw) <= 2_000_000, 'Freeze changed size')
    config = json.loads(raw.decode('utf-8'), object_pairs_hook=unique)
    namespace = {'__name__': 'trip_recap_freeze_check', '__file__': str(access / 'trip-recap-prepare-validation.py')}
    exec(compile(generated['prepare-package.py'], namespace['__file__'], 'exec'), namespace)
    namespace['validate_config'](config)
    return raw, config


def prepare(access, output, freeze=None):
    access, output = safe_path(access), safe_path(output, exists=False)
    need(output.parent == access and re.fullmatch('expo-trip-recap-tools-[a-z0-9-]+', output.name), 'New recap output must be directly under access root')
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
        'expectedTestCount': config['expectedTestCount'] if config else None, 'profile': 'finance_accounts58',
        'householdTablesBefore': 58, 'householdTablesAfter': 58, 'schemaChange': False,
        'serverCandidate': '/opt/family-dashboard-candidates/' + output.name, 'oldManifestSha256': OLD_MANIFEST,
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
