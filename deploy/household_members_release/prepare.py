"""Generate unbound 58 -> 58 household-role migration operators from pinned bytes.

Only local generation and configuration checks run here. No package, binding,
database, Docker, network or production phase is executed.
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
from deploy.expo_trip_import_release import prepare as previous
from deploy.finance_accounts_release import prepare as schema_release

BASE = 'expo-trip-import-tools-20260918-r1/'
PREPARE_SOURCE = BASE + 'prepare-package.py'
PINNED = {
    BASE + 'operators/ops_common.py': 'cde8f53182bbe245d22228a8fe318bfb0dccf51ffca826441870bb235b029055',
    BASE + 'operators/expo_contract.py': '9474328d21c3b898b020a9da691e5dcfd1109a418a616e93c4610fa480c180b9',
    BASE + 'operators/build.py': 'f9706156b66f7a5cd5d2ed8c860533ee7976bb1531141a6838aa63052ae7f8e8',
    BASE + 'operators/validate.py': '5d01889df2b86772915dcd643398fb3e8915cadee807a82aa7625ebc767a7c46',
    BASE + 'operators/stage.py': '0f52d72b2e145df966a9b2e78b6764f4a4a2384fee46e1b4a2709b6df5966a75',
    BASE + 'operators/activate.py': '30ef6e97fbe9a1c94007c2afe21401f8dafa8025c76186f9f7c8305132142e11',
    BASE + 'operators/post_readback.py': '9bd702b12de68022cfb6b0acf3c278c78834fb2b2ce8c9011c3ae46ac36ea4a3',
    PREPARE_SOURCE: 'd70988a96b00bab50ddb4dd679a185230b03afb710d54cb31070088204318960',
    BASE + 'bind-release.py': '5688a78305f1aefbb317be6b3a8239c5da24f09f65056e10ccb3b6cef206f7a6',
}
OLD_ARCHIVE = '0206b70e83f111fc99431c6021096e90d29cad15787c15788ba8022540c677e4'
OLD_MANIFEST = '79679fa35c8a1ca234c38f26d277150797c1e6ad445d5843d19cde7bfc6fc5a3'
PARENT_IMAGE = 'sha256:578142cb4d209d573ee0c54408d9494833ec49a74df1c5647a403e47ec5a72c1'
SOURCE_PINS = {
    'app.py': '90d5e191c5294219c5c2538cfc3f292fabde1b1e7ec79c263f23a188c696428f',
    'household_members.py': '7c52fd65426f3eaee0c970982abd0563d01ddab44fd1a9ff38f9661eb4a3ffa9',
    'Dockerfile': '465164741d385ee40887111a6f8258b3cd37f551dbe7f38d83d06e63e0f022a1',
    'deploy/check_household_members_migration.py': '733257bb1e087d8fa54ad50941c7530bbfaed720444cd22563eef1c94c245287',
}
REQUIRED_TESTS = {
    'tests/test_household_members.py', 'tests/test_household_members_migration.py',
    'tests/test_member_sessions.py', 'tests/test_household_spaces.py', 'tests/test_device_sessions.py',
    'tests/test_platform_backup.py', 'tests/test_frontend_runtime.py', 'tests/test_household_members_release.py',
}
FORBIDDEN_TESTS = previous.FORBIDDEN_TESTS
REQUIRED_CHANGED = {
    'app.py', 'Dockerfile', 'deploy/prepare_release.py', 'frontend/src/lib/types.ts',
    'frontend/src/screens/HouseholdApp.tsx', 'frontend/src/screens/OtherScreens.tsx',
}
REQUIRED_ADDED = {
    'household_members.py', 'deploy/check_household_members_migration.py',
    'frontend/src/lib/householdMembers.ts', 'frontend/src/components/HouseholdMembersPanel.tsx',
    'tests/test_expo_household_members.mjs', 'tests/browser_expo_household_members_check.py',
    'tests/test_household_members.py', 'tests/test_household_members_migration.py',
    'deploy/household_members_release/prepare.py', 'tests/test_household_members_release.py',
}
BACKEND_UNCHANGED = tuple(n for n in (*previous.BACKEND_UNCHANGED, 'journey_workflows.py') if n != 'app.py')
UNCHANGED = tuple(n for n in (*previous.UNCHANGED, 'journey_workflows.py')
                  if n not in ('app.py', 'Dockerfile', 'deploy/prepare_release.py'))
LOCAL_BUILD_SOURCES = previous.LOCAL_BUILD_SOURCES

DOCKER_CONTRACT = '''def verify_docker_delta(old, new):
    before = b'COPY app.py frontend_runtime.py member_sessions.py tv_display.py sync_health.py ./\\r\\n'
    after = b'COPY app.py frontend_runtime.py member_sessions.py household_members.py tv_display.py sync_health.py ./\\n'
    need(old.count(before) == 1 and b'household_members.py' not in old,
         'Installed Dockerfile lacks reviewed member COPY location')
    need(new == old.replace(before, after), 'Only reviewed member COPY bytes may change')
'''
ADDITION_RESULT = "{'profile':'household_members58','originalTablesPreserved':58,'newTables':0,\n         'addedColumns':['users.household_role'],'households':len(before['households']),\n         'originalUserColumnsPreserved':5,'initialRolesVerified':True,\n         'otherRowsSchemaAndSequencesPreserved':True,'registryPreserved':True}"
MIGRATION_PROGRAM = schema_release.MIGRATION_PROGRAM


def source_guard():
    need(all(isinstance(v, str) and re.fullmatch('[a-f0-9]{64}', v) for v in SOURCE_PINS.values()),
         'Independently reviewed member source pins required')
    return ''.join("    need(manifest.get(" + repr(name) + ") == " + repr(digest)
                   + ", 'Reviewed member source changed: " + name + "')\n" for name, digest in SOURCE_PINS.items())


def verify_generated(raw, name):
    schema_release.verify_generated(raw, name)
    # The sole mutation is the pinned migration helper, never direct API init.
    def check(tree):
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                called = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ''
                need(called != 'init_schema', 'Direct schema initialization forbidden')
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                try: nested = ast.parse(node.value)
                except (SyntaxError, ValueError): continue
                if any(isinstance(n, (ast.Call, ast.ImportFrom)) for n in ast.walk(nested)): check(nested)
    check(ast.parse(raw, filename=name))


def activate_operator(code):
    code = replace(code, 'expo-trip-import', 'household-members', count=4)
    code = replace(code, 'trip imports source publication', 'household-role column migration')
    code = replace(code, "ready.get('schemaChange') is False", "ready.get('schemaChange') is True")
    code = replace(code, '58-table preservation was not staged', '58-table role-column migration was not staged')
    code = replace(code, 'from deploy.check_finance_accounts_migration import (\n    schema_definition,snapshot,verify_current,validate_backup)',
        'from deploy.check_household_members_migration import (\n    schema_definition,snapshot,verify_baseline,verify_current,validate_backup,migrate,verify_addition)')
    # Remove exactly the old no-schema-change equality function.
    fragments = [n for n in ast.walk(ast.parse(code)) if isinstance(n, ast.AugAssign)
                 and isinstance(n.target, ast.Name) and n.target.id == 'schema_guard' and isinstance(n.value, ast.Constant)]
    need(len(fragments) == 1 and fragments[0].value.value == previous.PRESERVATION_FUNCTION, 'Old preservation function changed')
    node = fragments[0]
    code = replace(code, ''.join(code.splitlines(keepends=True)[node.lineno-1:node.end_lineno]), '')
    code = replace(code, "snapshot_program=schema_guard+\"\"\"\nvalue=snapshot(Path('/data'));verify_current(value,schema)",
        "snapshot_program=schema_guard+\"\"\"\nvalue=snapshot(Path('/data'));verify_baseline(value)")
    code = replace(code, 'verify_current(before,schema)\nif snapshot', 'verify_baseline(before)\nif snapshot')
    code = replace(code, "need(diagnostic(current_program)==before, 'Data changed before source installation')\n    record('all_58_tables_and_registry_unchanged_before_source_installation')",
        "need(diagnostic(snapshot_program)==before, 'Data changed before migration')\n"
        "    migration_program=schema_guard+" + repr(MIGRATION_PROGRAM) + "\n"
        "    migration_result=diagnostic(migration_program)\n"
        "    need(migration_result==" + ADDITION_RESULT + ", 'Unexpected role migration result')\n"
        "    write_new(proof/'migration.json',migration_result)\n"
        "    migrated=diagnostic(current_program)\n"
        "    write_new(proof/'after-migration.json',migrated);os.chown(proof/'after-migration.json',10001,10001)\n"
        "    record('exact_users_role_column_added_original_five_columns_other_57_tables_and_registry_preserved')")
    code = replace(code, "need(after==before, 'App startup changed 58-table data/schema/sequences or registry')",
        "need(after==migrated, 'App startup changed migrated 58-table rows/schema/sequences or registry')")
    code = replace(code, 'print(json.dumps(verify_preserved(before,after,schema)))', 'print(json.dumps(verify_addition(before,after,schema)))')
    old_result = "{'originalTablesPreserved':58,'newTables':0,'households':len(before['households']),\n         'allRowsSchemaAndSequencesPreserved':True,'registryPreserved':True}"
    code = replace(code, old_result, ADDITION_RESULT)
    code = replace(code, 'new_app_healthy_all_58_tables_rows_schema_sequences_and_registry_unchanged', 'new_app_healthy_all_58_tables_exactly_match_after_migration')
    code = replace(code, 'backupCheck=backup_check,schemaChange=False', 'backupCheck=backup_check,schemaChange=True,migrationResult=migration_result')
    return code


def post_operator(code):
    code = replace(code, 'expo-trip-import-58-', 'household-members-58-')
    code = replace(code, 'from deploy.check_finance_accounts_migration import schema_definition,verify_current,media',
        'from deploy.check_household_members_migration import schema_definition,verify_current,media,users_projection,validate_backup')
    code = replace(code, '    current_profile=verify_current(current,schema)',
        "    current['usersProjection']={uid:users_projection(paths[media.relative_database(uid)],\n"
        "        current['households'][uid]['tables']['users'],immutable=True) for uid in households}\n"
        '    current_profile=verify_current(current,schema)')
    code = replace(code, 'verified=media.validate_backup(root,current,receipt)', 'verified=validate_backup(root,current,receipt)')
    code = replace(code, "('before.json','after-app.json','preservation.json')", "('before.json','after-migration.json','migration.json','after-app.json','preservation.json')")
    start = code.index("    need(activation_snapshot==read(proof_root/'before.json')")
    end = code.index("    need(sha(ROOT/'RELEASE-MANIFEST.json')", start)
    code = code[:start] + """    need(activation_snapshot==read(proof_root/'after-migration.json')
         and preservation==published['preservationResult']==published['migrationResult']==read(proof_root/'migration.json')
         and preservation==EXPECTED_ADDITION
         and published['householdTables']==58 and published['schemaChange'] is True
         and published['allExistingDataPreservedAtAppStartup'] is True,
         'Completed role-column migration/startup evidence differs')
    addition_program="from pathlib import Path;import json,sys;sys.path.insert(0,'/release');from deploy.check_household_members_migration import schema_definition,verify_addition;v=json.load(sys.stdin);print(json.dumps(verify_addition(v['before'],v['after'],schema_definition())))"
    checked_addition=subprocess.run(readonly_backup_args(image)[:3]+['-i']+readonly_backup_args(image)[3:]+['-c',addition_program],
        input=json.dumps({'before':read(proof_root/'before.json'),'after':activation_snapshot}),capture_output=True,text=True,cwd=ROOT)
    need(checked_addition.returncode==0 and json.loads(checked_addition.stdout)==preservation,
         'Activation old user columns/other tables/schema/sequences or registry differ')
""".replace('EXPECTED_ADDITION', ADDITION_RESULT.replace("len(before['households'])", "published['households']")) + code[end:]
    code = replace(code, "for path in ('/api/", "for path in ('/api/members','/api/", count=1)
    return code


def adapt(inputs, access, output, config=None):
    guard = source_guard()
    operators = {name: inputs[BASE + 'operators/' + name].decode('utf-8') for name in SCRIPTS}
    operators['expo_contract.py'] = function_replace(operators['expo_contract.py'], 'verify_docker_delta', DOCKER_CONTRACT)
    common = operators['ops_common.py']
    for name, value in {'CANDIDATE': 'Path(' + repr('/opt/family-dashboard-candidates/' + output.name) + ')',
                        'PARENT_IMAGE': repr(PARENT_IMAGE), 'OLD_MANIFEST': repr(OLD_MANIFEST),
                        'EXPECTED_TEST_COUNT': repr(config['expectedTestCount'] if config else None),
                        'EXPECTED_TESTS': repr(tuple(config['validationTests']) if config else ())}.items():
        common = assignment(common, name, value)
    common = replace(common, repr(previous.UNCHANGED), repr(UNCHANGED))
    for before, after in (('trip imports', 'household roles'), ('finance_accounts58', 'household_members58'),
        ('deploy.check_finance_accounts_migration', 'deploy.check_household_members_migration'),
        ("sha(SOURCE/'finance_accounts.py')", "sha(SOURCE/'household_members.py')"),
        ("manifest.get('finance_accounts.py')==release_binding()", "manifest.get('household_members.py')==release_binding()"),
        ("and 'deploy/check_finance_accounts_migration.py' in manifest", "and 'deploy/check_household_members_migration.py' in manifest"),
        ("{'finance_accounts.py','investment_operations.py'", "{'household_members.py','finance_accounts.py','investment_operations.py'")):
        common = replace(common, before, after)
    common = replace(common, "    need(all(name in manifest for name in config['validationTests'])", guard + "    need(all(name in manifest for name in config['validationTests'])")
    operators['ops_common.py'] = common
    operators['build.py'] = replace(operators['build.py'], 'family-dashboard-expo-trip-import:', 'family-dashboard-household-members:')
    operators['validate.py'] = replace(operators['validate.py'], "('deploy.check_finance_accounts_migration','finance_accounts')):",
        "('deploy.check_finance_accounts_migration','finance_accounts'),\n ('deploy.check_household_members_migration','household_members')):")
    operators['validate.py'] = replace(operators['validate.py'], '# All three schema helpers', '# All four schema helpers')
    operators['stage.py'] = replace(operators['stage.py'], 'householdTablesBefore=58,householdTablesAfter=58,schemaChange=False', 'householdTablesBefore=58,householdTablesAfter=58,schemaChange=True')
    operators['activate.py'] = activate_operator(operators['activate.py'])
    operators['post_readback.py'] = post_operator(operators['post_readback.py'])
    package = inputs[PREPARE_SOURCE].decode('utf-8')
    for name, value in {'A': 'Path(' + repr(str(access)) + ')', 'OUT': 'Path(' + repr(str(output / 'package')) + ')',
                        'CONTRACT': 'Path(' + repr(str(output / 'operators/expo_contract.py')) + ')',
                        'CONTRACT_SHA': repr(sha(operators['expo_contract.py'].encode()))}.items():
        package = assignment(package, name, value)
    for before, after in ((previous.OLD_MANIFEST, OLD_MANIFEST), (previous.OLD_ARCHIVE, OLD_ARCHIVE),
                          (previous.PARENT_IMAGE, PARENT_IMAGE), (repr(previous.UNCHANGED), repr(UNCHANGED)),
                          ('Wrong installed photo suggestions archive', 'Wrong installed trip import archive'),
                          ("constants(blobs['finance_accounts.py'], ('FINANCE_ACCOUNTS_SCHEMA_SQL',))['FINANCE_ACCOUNTS_SCHEMA_SQL']", "constants(blobs['household_members.py'], ('HOUSEHOLD_ROLE_COLUMN_SQL',))['HOUSEHOLD_ROLE_COLUMN_SQL']"),
                          ("migrationSourceSha256=manifest['finance_accounts.py']", "migrationSourceSha256=manifest['household_members.py']")):
        package = replace(package, before, after)
    for field, old, new in (('validationTests', previous.REQUIRED_TESTS, REQUIRED_TESTS),
                            ('changedFiles', previous.REQUIRED_CHANGED, REQUIRED_CHANGED), ('addedFiles', previous.REQUIRED_ADDED, REQUIRED_ADDED)):
        package = replace(package, 'set(' + repr(sorted(old)) + ") <= set(value['" + field + "'])", 'set(' + repr(sorted(new)) + ") <= set(value['" + field + "'])")
    package = replace(package, 'set(' + repr(sorted(previous.REQUIRED_CHANGED | previous.REQUIRED_ADDED)) + ') <= selected', 'set(' + repr(sorted(REQUIRED_CHANGED | REQUIRED_ADDED)) + ') <= selected')
    package = replace(package, '    delta = verify_delta(old, manifest, config, contract)', guard + '    delta = verify_delta(old, manifest, config, contract)')
    binder = inputs[BASE + 'bind-release.py'].decode('utf-8')
    for name, value in {'A': access, 'PACK': output / 'package', 'OPS': output / 'operators', 'PREPARE': output / 'prepare-package.py'}.items():
        binder = assignment(binder, name, 'Path(' + repr(str(value)) + ')')
    binder = replace(binder, "manifest['finance_accounts.py']", "manifest['household_members.py']", count=2)
    binder = replace(binder, 'finance_accounts58', 'household_members58')
    generated = {'operators/' + name: code.encode() for name, code in operators.items()}
    generated.update({'prepare-package.py': package.encode(), 'bind-release.py': binder.encode()})
    for name, raw in generated.items(): verify_generated(raw, name)
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
    need(output.parent == access and re.fullmatch('household-members-tools-[a-z0-9-]+', output.name), 'New member output must be directly under access root')
    need(not output.exists(), 'Output exists; preserve prior attempts')
    inputs = read_sources(access); generated = adapt(inputs, access, output)
    freeze_raw, config = schema_release.freeze_config(freeze, access, generated) if freeze else (None, None)
    if config: generated = adapt(inputs, access, output, config)
    need(read_sources(access) == inputs, 'Reviewed input changed during generation')
    if freeze: need(safe_path(freeze).read_bytes() == freeze_raw, 'Freeze changed during generation')
    output.mkdir(mode=0o700)
    for name, raw in generated.items():
        path = output / name; path.parent.mkdir(exist_ok=True, mode=0o700)
        with path.open('xb') as stream: stream.write(raw)
        path.chmod(0o600)
    report = {'schemaVersion': 1, 'bound': False, 'requiresIndependentOperatorReview': True,
        'finalFreezeProvided': config is not None, 'freezeSha256': sha(freeze_raw) if freeze_raw else None,
        'expectedTestCount': config['expectedTestCount'] if config else None, 'profile': 'household_members58',
        'householdTablesBefore': 58, 'householdTablesAfter': 58, 'schemaChange': True,
        'serverCandidate': '/opt/family-dashboard-candidates/' + output.name, 'oldManifestSha256': OLD_MANIFEST,
        'reviewedSourceHashes': SOURCE_PINS, 'sourceHashes': PINNED,
        'generatedHashes': {name: sha(raw) for name, raw in generated.items()},
        'productionOperations': False, 'repositoryMutations': False}
    with (output / 'generation.json').open('x', encoding='utf-8') as stream: json.dump(report, stream, indent=2)
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


if __name__ == '__main__': main()
