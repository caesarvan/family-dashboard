"""Generate unbound role-aware 58 -> 58 column-mapping release tools.

Generation is local only. Missing reviewed finance source pins fail before any
output directory is created. Existing member roles and all data stay unchanged.
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

from deploy.holdings_release.prepare import assignment, need, replace, safe_path, sha
from deploy.travel_release.prepare import SCRIPTS, function_replace
from deploy.household_members_release import prepare as previous
from deploy.expo_trip_recap_release import prepare as preservation

BASE = 'household-members-tools-20260918-r1/'
PREPARE_SOURCE = BASE + 'prepare-package.py'
PINNED = {
    BASE + 'operators/ops_common.py': 'e78f5b5bbac09e416aa29ec503fc6f129118c2b7ec643cd1ddbb1a9eefae6c65',
    BASE + 'operators/expo_contract.py': '9b6e9e2ca05655eef3176c89bb6dbfaf71ed102c90238efc821fcc9dd2eb5330',
    BASE + 'operators/build.py': '6275fd89f1ee746c14e0ee1de9ec010a2ee28b09895bf367103357cce941b664',
    BASE + 'operators/validate.py': 'b903b27fe568e38f637b525717e8ba58f929471b5875f6e14fca503b84614e71',
    BASE + 'operators/stage.py': '048953678781cc8a9e32bdc0b1aac41ee0ba51fd6b59be7304e16fc7fdc6d27a',
    BASE + 'operators/activate.py': 'd2f92597bea8b05bb2c5061a1773f0948f42f1b6d7f0d7bdd9ceab32a3d0c9bb',
    BASE + 'operators/post_readback.py': 'a586756fac18d3c3e4c0ad7691d9090d2320d1f524208a44431c5d72d1483d0b',
    PREPARE_SOURCE: '2c7b7372805efb60fb2a873c20ab614c58d10940e660ebed55c2337d53184f7e',
    BASE + 'bind-release.py': 'f250ebac177c9564f25cd3da02fb694d76db010c79c757920f485aaada24dfaa',
}
OLD_ARCHIVE = '57cee29157d0ab96f500e760506139cef47d88fa90875409916cda4fab20e276'
OLD_MANIFEST = 'af59bbbe1fd637930ae8c7878392e4a688f651a83f4061f015ec26cbce7b3fad'
PARENT_IMAGE = 'sha256:5fa4c5d0b89e2a5ebce3f72c1691b3f4238f665a01c7419aff19a7aae2df98cc'
# API 8c835bf independently reviewed; a missing or malformed pin fails closed.
FINANCE_SOURCE_SHA256 = '093fb1cd54adb4cce7e486b44834800ec018be01cd7b668fc51ceb33f21d3091'
SOURCE_PINS = dict(previous.SOURCE_PINS)
SOURCE_PINS['financial_files.py'] = 'cfbc2bfc6b8c51ff9b7d4ed12b4ecf5e5ebe8d03df0064e60bae340bec89140e'
REQUIRED_CHANGED = {'finance_hub.py', 'frontend/src/screens/FinanceImportPanel.tsx', 'frontend/src/lib/financeImport.ts'}
REQUIRED_ADDED = {
    'tests/test_finance_column_mapping.py', 'tests/test_finance_column_mapping_sessions.py',
    'tests/browser_finance_column_mapping_check.py', 'deploy/finance_column_mapping_release/prepare.py',
    'tests/test_finance_column_mapping_release.py',
}
REQUIRED_TESTS = {
    'tests/test_finance_column_mapping.py', 'tests/test_finance_column_mapping_sessions.py',
    'tests/test_finance_hub.py', 'tests/test_financial_files.py', 'tests/test_finance_amount_columns.py',
    'tests/test_finance_import_amounts.py', 'tests/test_financial_sheet_discovery.py',
    'tests/test_finance_import_receipts.py', 'tests/test_finance_import_navigation.py',
    'tests/test_taobao_order_groups.py',
    'tests/test_household_members_migration.py', 'tests/test_household_spaces.py',
    'tests/test_platform_backup.py', 'tests/test_frontend_runtime.py', 'tests/test_finance_column_mapping_release.py',
}
FORBIDDEN_TESTS = previous.FORBIDDEN_TESTS
BACKEND_UNCHANGED = tuple(n for n in (*previous.BACKEND_UNCHANGED, 'app.py', 'household_members.py') if n != 'finance_hub.py')
UNCHANGED = tuple(n for n in previous.UNCHANGED if n != 'finance_hub.py') + tuple(n for n in (
    'app.py', 'household_members.py', 'Dockerfile', 'deploy/prepare_release.py',
    'deploy/check_household_members_migration.py',
) if n not in previous.UNCHANGED)
LOCAL_BUILD_SOURCES = previous.LOCAL_BUILD_SOURCES
PRESERVATION_RESULT = preservation.PRESERVATION_RESULT
PRESERVATION_FUNCTION = preservation.PRESERVATION_FUNCTION
DOCKER_CONTRACT = '''def verify_docker_delta(old, new):
    need(old == new, 'Dockerfile must remain byte-identical for column mapping')
'''


def reviewed_sources():
    pins = {**SOURCE_PINS, 'finance_hub.py': FINANCE_SOURCE_SHA256}
    need(all(isinstance(v, str) and re.fullmatch('[a-f0-9]{64}', v) for v in pins.values()),
         'Independently reviewed finance source pin required')
    return pins


def source_guard():
    return ''.join("    need(manifest.get(" + repr(name) + ") == " + repr(digest)
                   + ", 'Reviewed column mapping source changed: " + name + "')\n"
                   for name, digest in reviewed_sources().items())


def verify_generated(raw, name):
    preservation.verify_generated(raw, name)
    previous.verify_generated(raw, name)  # Additionally rejects nested init_schema.


def activate_operator(code):
    code = replace(code, 'household-members', 'finance-column-mapping', count=4)
    code = replace(code, 'household-role column migration', 'column mapping source publication')
    code = replace(code, "ready.get('schemaChange') is True", "ready.get('schemaChange') is False")
    code = replace(code, '58-table role-column migration was not staged', 'Role-aware 58-table preservation was not staged')
    code = replace(code, 'schema_definition,snapshot,verify_baseline,verify_current,validate_backup,migrate,verify_addition',
                   'schema_definition,snapshot,verify_current,validate_backup')
    marker = '    snapshot_program=schema_guard+'
    code = replace(code, marker, '    schema_guard += ' + repr(PRESERVATION_FUNCTION) + '\n' + marker)
    code = replace(code, 'verify_baseline(value)', 'verify_current(value,schema)')
    code = replace(code, 'verify_baseline(before)', 'verify_current(before,schema)')
    migration = "    need(diagnostic(snapshot_program)==before, 'Data changed before migration')\n" + \
        '    migration_program=schema_guard+' + repr(previous.MIGRATION_PROGRAM) + '\n' + \
        "    migration_result=diagnostic(migration_program)\n    need(migration_result==" + previous.ADDITION_RESULT + \
        ", 'Unexpected role migration result')\n    write_new(proof/'migration.json',migration_result)\n" + \
        "    migrated=diagnostic(current_program)\n    write_new(proof/'after-migration.json',migrated);os.chown(proof/'after-migration.json',10001,10001)\n" + \
        "    record('exact_users_role_column_added_original_five_columns_other_57_tables_and_registry_preserved')"
    code = replace(code, migration, "    need(diagnostic(current_program)==before, 'Data changed before source installation')\n    record('all_58_tables_roles_and_registry_unchanged_before_source_installation')")
    code = replace(code, "need(after==migrated, 'App startup changed migrated 58-table rows/schema/sequences or registry')",
                   "need(after==before, 'App startup changed 58-table roles/rows/schema/sequences or registry')")
    code = replace(code, 'verify_addition(before,after,schema)', 'verify_preserved(before,after,schema)')
    code = replace(code, previous.ADDITION_RESULT, PRESERVATION_RESULT)
    code = replace(code, 'new_app_healthy_all_58_tables_exactly_match_after_migration', 'new_app_healthy_all_58_tables_roles_and_registry_unchanged')
    code = replace(code, 'schemaChange=True,migrationResult=migration_result', 'schemaChange=False')
    return code


def post_operator(code):
    code = replace(code, 'household-members-58-', 'finance-column-mapping-58-')
    code = replace(code, "('before.json','after-migration.json','migration.json','after-app.json','preservation.json')",
                   "('before.json','after-app.json','preservation.json')")
    old = """    need(activation_snapshot==read(proof_root/'after-migration.json')
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
""".replace('EXPECTED_ADDITION', previous.ADDITION_RESULT.replace("len(before['households'])", "published['households']"))
    expected = PRESERVATION_RESULT.replace("len(before['households'])", "published['households']")
    program = "from pathlib import Path\nimport json,sys\nsys.path.insert(0,'/release')\nfrom deploy.check_household_members_migration import schema_definition,verify_current\n" + PRESERVATION_FUNCTION + "v=json.load(sys.stdin)\nprint(json.dumps(verify_preserved(v['before'],v['after'],schema_definition())))\n"
    new = "    need(activation_snapshot==read(proof_root/'before.json')\n" + \
        "         and preservation==published['preservationResult']==" + expected + "\n" + \
        "         and published['householdTables']==58 and published['schemaChange'] is False\n" + \
        "         and published['allExistingDataPreservedAtAppStartup'] is True,\n" + \
        "         'Completed role-aware 58-table preservation evidence differs')\n" + \
        '    preservation_program=' + repr(program) + '\n' + \
        "    checked_preservation=subprocess.run(readonly_backup_args(image)[:3]+['-i']+readonly_backup_args(image)[3:]+['-c',preservation_program],\n" + \
        "        input=json.dumps({'before':read(proof_root/'before.json'),'after':activation_snapshot}),capture_output=True,text=True,cwd=ROOT)\n" + \
        "    need(checked_preservation.returncode==0 and json.loads(checked_preservation.stdout)==preservation,\n" + \
        "         'Activation roles/rows/schema/sequences or registry differ')\n"
    code = replace(code, old, new)
    # Parent backup reader retains immutable paths/hashes/sidecars, full snapshot
    # fingerprints, users_projection, verify_current and validate_backup verbatim.
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
    common = replace(common, previous.source_guard(), guard)
    common = replace(common, 'household roles', 'column mapping')
    operators['ops_common.py'] = common
    operators['build.py'] = replace(operators['build.py'], 'family-dashboard-household-members:', 'family-dashboard-finance-column-mapping:')
    operators['stage.py'] = replace(operators['stage.py'], 'householdTablesBefore=58,householdTablesAfter=58,schemaChange=True', 'householdTablesBefore=58,householdTablesAfter=58,schemaChange=False')
    operators['activate.py'] = activate_operator(operators['activate.py'])
    operators['post_readback.py'] = post_operator(operators['post_readback.py'])
    package = inputs[PREPARE_SOURCE].decode('utf-8')
    for name, value in {'A': 'Path(' + repr(str(access)) + ')', 'OUT': 'Path(' + repr(str(output / 'package')) + ')',
                        'CONTRACT': 'Path(' + repr(str(output / 'operators/expo_contract.py')) + ')',
                        'CONTRACT_SHA': repr(sha(operators['expo_contract.py'].encode()))}.items():
        package = assignment(package, name, value)
    for before, after in ((previous.OLD_MANIFEST, OLD_MANIFEST), (previous.OLD_ARCHIVE, OLD_ARCHIVE),
                          (previous.PARENT_IMAGE, PARENT_IMAGE), (repr(previous.UNCHANGED), repr(UNCHANGED)),
                          ('Wrong installed trip import archive', 'Wrong installed household members archive')):
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
    need(output.parent == access and re.fullmatch('finance-column-mapping-tools-[a-z0-9-]+', output.name),
         'New column mapping output must be directly under access root')
    need(not output.exists(), 'Output exists; preserve prior attempts')
    inputs = read_sources(access); generated = adapt(inputs, access, output)
    freeze_raw, config = previous.schema_release.freeze_config(freeze, access, generated) if freeze else (None, None)
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
