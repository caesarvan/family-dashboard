"""Generate unbound, reviewable 55 -> 58 account operators from pinned local bytes.

Only local generation/config validation runs here. No packaging, database,
Docker, network, binding or production phase is executed.
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
from deploy.expo_finance_source_release import prepare as previous

BASE = 'expo-finance-source-tools-20260917-r2/'
PREPARE_SOURCE = BASE + 'prepare-package.py'
PINNED = {
    BASE + 'operators/ops_common.py': '7b4f9f628800ca8d3540d67e5d5a60471c014ccb44ab6d7310969ef82ba71892',
    BASE + 'operators/expo_contract.py': '87b27d86951c54cc44ed3619f256ec37d83d9c804624cb776e2ff97cc7ededbf',
    BASE + 'operators/build.py': '795a6a952a590d3329300a006ef464d200c6409c694dbd16612ecef78949666f',
    BASE + 'operators/validate.py': '3c4de4349513bd8b8de5cd40c754fd3a0804c8f6f5c2d76ef1a02528605a2728',
    BASE + 'operators/stage.py': 'b2c97cc31499902adb67d901dec6efdee748b8a087981f737397bf2af652d74d',
    BASE + 'operators/activate.py': '3151c11f945a248165722a55bb45f61169c49838de5e454ba5d848c8c1ac194b',
    BASE + 'operators/post_readback.py': '672981e098a6024d4eb6ca309917efb1b6b22ebb0f5a056e117717b9558f1c4f',
    PREPARE_SOURCE: '3735712195a289a7960e5b774dccd8a969c98c2f791624746b39883556ad83a3',
    BASE + 'bind-release.py': '3645028fde923a29f97a2de0d2a493b21e853394efb581dff6a1f0b0a0a56bbd',
}
OLD_ARCHIVE = '93426c1c8feac4c8f8c8f2626c74637ed9d1ba6fb884da276cbab49393fce5f5'
OLD_MANIFEST = 'f11d9d58971fa9bcf91ac2a53f19ad23c426fbd833f9f6b1a575c0dfb4e1f7c0'
PARENT_IMAGE = 'sha256:6b886eb5123916673d8c9ac38810390cb7ec6b46db5941c651602835769cab68'
REQUIRED_TESTS = {
    'tests/test_finance_accounts.py', 'tests/test_finance_accounts_migration.py',
    'tests/test_finance_accounts_portability.py', 'tests/test_data_portability.py',
    'tests/test_member_session_portability.py', 'tests/test_investment_operation_migration.py',
    'tests/test_frontend_runtime.py', 'tests/test_household_spaces.py',
    'tests/test_platform_backup.py', 'tests/test_finance_accounts_release.py',
}
FORBIDDEN_TESTS = previous.FORBIDDEN_TESTS
REQUIRED_CHANGED = {
    'app.py', 'data_portability.py', 'Dockerfile', 'deploy/prepare_release.py',
    'frontend/src/lib/types.ts', 'frontend/src/screens/FinanceScreen.tsx',
    'frontend/src/screens/HouseholdApp.tsx', 'tests/test_investment_operation_migration.py',
}
REQUIRED_ADDED = {
    'finance_accounts.py', 'deploy/check_finance_accounts_migration.py',
    'frontend/src/lib/financeAccounts.ts', 'frontend/src/components/FinanceAccountsPanel.tsx',
    'tests/test_expo_finance_accounts.mjs', 'tests/browser_expo_finance_accounts_check.py',
    'tests/test_finance_accounts.py', 'tests/test_finance_accounts_migration.py',
    'tests/test_finance_accounts_portability.py',
    'deploy/finance_accounts_release/prepare.py', 'tests/test_finance_accounts_release.py',
}
BACKEND_UNCHANGED = tuple(n for n in previous.BACKEND_UNCHANGED if n not in ('app.py', 'data_portability.py'))
UNCHANGED = tuple(n for n in previous.UNCHANGED if n not in ('Dockerfile', 'app.py', 'data_portability.py'))
LOCAL_BUILD_SOURCES = previous.LOCAL_BUILD_SOURCES
ANONYMOUS_PATHS = ('/api/finance-accounts?asOf=2000-01-01&status=all',
    '/api/finance-accounts/' + '0' * 24 + '/valuations',
    '/api/finance-accounts/operations/' + '0' * 32)

DOCKER_CONTRACT = '''def verify_docker_delta(old, new):
    before = b'COPY finance_source_bridge.py journey_time.py journey_reschedule.py ./\\n'
    after = b'COPY finance_source_bridge.py finance_accounts.py journey_time.py journey_reschedule.py ./\\n'
    need(old.count(before) == 1 and b'finance_accounts.py' not in old,
         'Installed Dockerfile lacks the reviewed account COPY location')
    need(new == old.replace(before, after), 'Only finance_accounts.py may be added to Docker COPY')
'''

MIGRATION_PROGRAM = '''before=json.loads(Path('/proof/before.json').read_text())
backup=json.loads(Path('/proof/backup.json').read_text())
print(json.dumps(migrate(Path('/data'),before,backup,schema)))
'''
ADDITION_RESULT = "{'originalTablesPreserved':55,'newTables':3,'households':len(before['households']),\n         'newTablesEmpty':True,'oldRowsSchemaAndSequencesPreserved':True,'registryPreserved':True}"


def verify_generated(raw, name):
    """Recursively inspect embedded Python; only one reviewed activation call migrates."""
    def check(tree):
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                called = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ''
                need(called not in {'initialize_database', 'create_app', 'executescript'}, 'Uncontrolled database initialization in ' + name)
                if called == 'migrate':
                    need(name == 'operators/activate.py' and ast.unparse(node) == "migrate(Path('/data'), before, backup, schema)", 'Unreviewed migration call')
                if called == 'verify_baseline':
                    need(name == 'operators/activate.py', 'Baseline-only check outside activation')
                if called == 'verify_addition':
                    need(name in ('operators/activate.py', 'operators/post_readback.py'), 'Addition check outside publication')
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
    code = replace(code, '55 -> 55 travel source publication', '55 -> 58 manual account publication')
    code = replace(code, 'expo-finance-source', 'finance-accounts', count=4)
    code = replace(code, 'finance-accounts-55-', 'finance-accounts-58-')
    code = replace(code, "ready.get('schemaChange') is False and ready.get('householdTablesAfter')==55", "ready.get('schemaChange') is True and ready.get('householdTablesAfter')==58")
    code = replace(code, '55-table preservation was not staged', '55-to-58 migration was not staged')
    code = replace(code, 'from deploy.check_investment_operation_migration import (\n    schema_definition,snapshot,verify_current,validate_backup)',
        'from deploy.check_finance_accounts_migration import (\n    schema_definition,snapshot,verify_baseline,verify_current,validate_backup,migrate,verify_addition)')
    # The old preservation function is embedded as one Python string assignment.
    tree = ast.parse(code)
    augments = [n for n in ast.walk(tree) if isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name)
                and n.target.id == 'schema_guard' and isinstance(n.value, ast.Constant)]
    need(len(augments) == 1, 'Expected old preservation fragment')
    lines = code.splitlines(keepends=True); node = augments[0]
    code = replace(code, ''.join(lines[node.lineno-1:node.end_lineno]), '')
    code = replace(code, "snapshot_program=schema_guard+\"\"\"\nvalue=snapshot(Path('/data'));verify_current(value,schema)",
        "snapshot_program=schema_guard+\"\"\"\nvalue=snapshot(Path('/data'));verify_baseline(value)")
    code = replace(code, 'verify_current(before,schema)\nif snapshot', 'verify_baseline(before)\nif snapshot')
    code = replace(code, "need(diagnostic(current_program)==before, 'Data changed before source installation')\n    record('all_55_tables_and_registry_unchanged_before_source_installation')",
        "need(diagnostic(snapshot_program)==before, 'Data changed before migration')\n"
        "    migration_program=schema_guard+" + repr(MIGRATION_PROGRAM) + "\n"
        "    migration_result=diagnostic(migration_program)\n"
        "    need(migration_result==" + ADDITION_RESULT + ", 'Unexpected migration result')\n"
        "    write_new(proof/'migration.json',migration_result)\n"
        "    migrated=diagnostic(current_program)\n"
        "    write_new(proof/'after-migration.json',migrated);os.chown(proof/'after-migration.json',10001,10001)\n"
        "    record('exact_three_empty_tables_added_original_55_and_registry_preserved')")
    code = replace(code, "need(after==before, 'App startup changed 55-table data/schema/sequences or registry')",
        "need(after==migrated, 'App startup changed migrated 58-table data/schema/sequences or registry')")
    code = replace(code, 'print(json.dumps(verify_preserved(before,after,schema)))', 'print(json.dumps(verify_addition(before,after,schema)))')
    code = replace(code, "{'originalTablesPreserved':55,'newTables':0,'households':len(before['households']),\n         'receiptRows':sum(v['tables']['hub_investment_operations']['count'] for v in before['households'].values()),\n         'allRowsSchemaAndSequencesPreserved':True,'registryPreserved':True}", ADDITION_RESULT)
    code = replace(code, 'new_app_healthy_all_55_tables_rows_schema_sequences_and_registry_unchanged', 'new_app_healthy_all_58_tables_unchanged_since_exact_migration')
    code = replace(code, 'publicHttpsHealth=200,householdTables=55', 'publicHttpsHealth=200,householdTables=58')
    code = replace(code, 'backupCheck=backup_check,schemaChange=False', 'backupCheck=backup_check,schemaChange=True,migrationResult=migration_result')
    return code


def post_operator(code):
    code = replace(code, 'deploy.check_investment_operation_migration', 'deploy.check_finance_accounts_migration')
    code = replace(code, 'expo-finance-source-55-', 'finance-accounts-58-')
    code = replace(code, "('before.json','after-app.json','preservation.json')", "('before.json','after-migration.json','migration.json','after-app.json','preservation.json')")
    start = code.index("    need(activation_snapshot==read(proof_root/'before.json')")
    end = code.index("    need(sha(ROOT/'RELEASE-MANIFEST.json')", start)
    code = code[:start] + """    need(activation_snapshot==read(proof_root/'after-migration.json')
         and preservation==published['preservationResult']==published['migrationResult']==read(proof_root/'migration.json')
         and preservation=={'originalTablesPreserved':55,'newTables':3,'households':published['households'],
             'newTablesEmpty':True,'oldRowsSchemaAndSequencesPreserved':True,'registryPreserved':True}
         and published['householdTables']==58 and published['schemaChange'] is True
         and published['allExistingDataPreservedAtAppStartup'] is True,
         'Completed 55-to-58 migration/startup evidence differs')
    addition_program=\"from pathlib import Path;import json,sys;sys.path.insert(0,'/release');from deploy.check_finance_accounts_migration import schema_definition,verify_addition;v=json.load(sys.stdin);print(json.dumps(verify_addition(v['before'],v['after'],schema_definition())))\"
    checked_addition=subprocess.run(readonly_backup_args(image)[:3]+['-i']+readonly_backup_args(image)[3:]+['-c',addition_program],
        input=json.dumps({'before':read(proof_root/'before.json'),'after':activation_snapshot}),capture_output=True,text=True,cwd=ROOT)
    need(checked_addition.returncode==0 and json.loads(checked_addition.stdout)==preservation,
         'Activation original tables/schema/sequences or registry differ')
""" + code[end:]
    code = replace(code, "for path in ('/api/finance-baseline/private'", "for path in (" + ','.join(map(repr, ANONYMOUS_PATHS)) + ",'/api/finance-baseline/private'")
    code = replace(code, "backup_schema['tablesPerHousehold']==55", "backup_schema['tablesPerHousehold']==58")
    code = replace(code, 'activationHouseholdTables=55', 'activationHouseholdTables=58')
    code = replace(code, 'activationStartup55Verified=True', 'activationStartup58Verified=True')
    return code


def adapt(inputs, access, output, config=None):
    operators = {name: inputs[BASE + 'operators/' + name].decode('utf-8') for name in SCRIPTS}
    operators['expo_contract.py'] = function_replace(operators['expo_contract.py'], 'verify_docker_delta', DOCKER_CONTRACT)
    common = operators['ops_common.py']
    for name, value in {'CANDIDATE': 'Path(' + repr('/opt/family-dashboard-candidates/' + output.name) + ')',
                        'PARENT_IMAGE': repr(PARENT_IMAGE), 'OLD_MANIFEST': repr(OLD_MANIFEST),
                        'EXPECTED_TEST_COUNT': repr(config['expectedTestCount'] if config else None),
                        'EXPECTED_TESTS': repr(tuple(config['validationTests']) if config else ())}.items():
        common = assignment(common, name, value)
    common = replace(common, '55 -> 55 Expo finance source import UI source-update guards', '55 -> 58 manual account release guards')
    common = replace(common, repr(previous.UNCHANGED), repr(UNCHANGED))
    for before, after, count in (
        ('investment_operations55', 'finance_accounts58', 1),
        ('deploy.check_investment_operation_migration', 'deploy.check_finance_accounts_migration', 1),
        ("sha(SOURCE/'investment_operations.py')", "sha(SOURCE/'finance_accounts.py')", 1),
        ("manifest.get('investment_operations.py')==release_binding()", "manifest.get('finance_accounts.py')==release_binding()", 1),
        ("and 'deploy/check_investment_operation_migration.py' in manifest", "and 'deploy/check_finance_accounts_migration.py' in manifest", 1),
        ("{'investment_operations.py','calendar_publish.py'", "{'finance_accounts.py','investment_operations.py','calendar_publish.py'", 1)):
        common = replace(common, before, after, count=count)
    operators['ops_common.py'] = common
    operators['build.py'] = replace(operators['build.py'], 'family-dashboard-expo-finance-source:', 'family-dashboard-finance-accounts:')
    operators['validate.py'] = replace(operators['validate.py'], "('deploy.check_investment_operation_migration','investment_operations')):",
        "('deploy.check_investment_operation_migration','investment_operations'),\n ('deploy.check_finance_accounts_migration','finance_accounts')):")
    operators['validate.py'] = replace(operators['validate.py'], '# Both the 55-table helper and its 54-table predecessor check their own origins.', '# All three schema helpers bind their real immutable image modules.')
    operators['stage.py'] = replace(operators['stage.py'], 'householdTablesBefore=55,householdTablesAfter=55,schemaChange=False', 'householdTablesBefore=55,householdTablesAfter=58,schemaChange=True')
    operators['activate.py'] = activate_operator(operators['activate.py'])
    operators['post_readback.py'] = post_operator(operators['post_readback.py'])
    prepare = inputs[PREPARE_SOURCE].decode('utf-8')
    for name, value in {'A': 'Path(' + repr(str(access)) + ')', 'OUT': 'Path(' + repr(str(output / 'package')) + ')',
                        'CONTRACT': 'Path(' + repr(str(output / 'operators/expo_contract.py')) + ')',
                        'CONTRACT_SHA': repr(sha(operators['expo_contract.py'].encode()))}.items():
        prepare = assignment(prepare, name, value)
    for before, after in ((previous.OLD_MANIFEST, OLD_MANIFEST), (previous.OLD_ARCHIVE, OLD_ARCHIVE),
                          (previous.PARENT_IMAGE, PARENT_IMAGE), (repr(previous.UNCHANGED), repr(UNCHANGED)),
                          ('Wrong installed Expo private baseline archive', 'Wrong installed source R2 archive'),
                          ("constants(blobs['investment_operations.py'], ('INVESTMENT_OPERATIONS_SCHEMA_SQL',))['INVESTMENT_OPERATIONS_SCHEMA_SQL']", "constants(blobs['finance_accounts.py'], ('FINANCE_ACCOUNTS_SCHEMA_SQL',))['FINANCE_ACCOUNTS_SCHEMA_SQL']"),
                          ("migrationSourceSha256=manifest['investment_operations.py']", "migrationSourceSha256=manifest['finance_accounts.py']")):
        prepare = replace(prepare, before, after)
    for field, old, new in (('validationTests', previous.REQUIRED_TESTS, REQUIRED_TESTS),
                            ('changedFiles', previous.REQUIRED_CHANGED, REQUIRED_CHANGED),
                            ('addedFiles', previous.REQUIRED_ADDED, REQUIRED_ADDED)):
        prepare = replace(prepare, 'set(' + repr(sorted(old)) + ") <= set(value['" + field + "'])", 'set(' + repr(sorted(new)) + ") <= set(value['" + field + "'])")
    prepare = replace(prepare, 'set(' + repr(sorted(previous.REQUIRED_CHANGED | previous.REQUIRED_ADDED)) + ') <= selected', 'set(' + repr(sorted(REQUIRED_CHANGED | REQUIRED_ADDED)) + ') <= selected')
    binder = inputs[BASE + 'bind-release.py'].decode('utf-8')
    for name, value in {'A': access, 'PACK': output / 'package', 'OPS': output / 'operators', 'PREPARE': output / 'prepare-package.py'}.items():
        binder = assignment(binder, name, 'Path(' + repr(str(value)) + ')')
    binder = replace(binder, "manifest['investment_operations.py']", "manifest['finance_accounts.py']", count=2)
    binder = replace(binder, 'investment_operations55', 'finance_accounts58')
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
    namespace = {'__name__': 'accounts_freeze_check', '__file__': str(access / 'accounts-prepare-validation.py')}
    exec(compile(generated['prepare-package.py'], namespace['__file__'], 'exec'), namespace)
    namespace['validate_config'](config)
    return raw, config


def prepare(access, output, freeze=None):
    access, output = safe_path(access), safe_path(output, exists=False)
    need(output.parent == access and re.fullmatch('finance-accounts-tools-[a-z0-9-]+', output.name), 'New account output must be directly under access root')
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
        'householdTablesBefore': 55, 'householdTablesAfter': 58, 'schemaChange': True,
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
