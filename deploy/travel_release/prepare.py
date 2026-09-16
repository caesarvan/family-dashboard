"""Generate a bounded 55 -> 55 adapter from the published, reviewed operators.

Only pinned local bytes are read and new local files written. Generated entrypoints
are not executed. No SSH, Docker, network, Git mutation, DDL or production action.
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

from deploy.holdings_release.prepare import assignment, need, replace, safe_path, sha, substitutions, unique

BASE = 'expo-holdings-tools-20260917-r2/'
PINNED = {
    BASE + 'operators/ops_common.py': '957ef5b89884c753e732e618b2fae2913e7ea1060dae06dd392da3947b302d72',
    BASE + 'operators/expo_contract.py': 'd5d927fc82d937c056aeb9e6e36f0b2b387271433dd1dfdfbc3db47289044003',
    BASE + 'operators/build.py': '38ee81d4fc27f45ab5d51014d598023f2af536ef71e22386d619e6c2a3d7fd8d',
    BASE + 'operators/validate.py': 'cd0c738ba5307bf7aa38fff6a5e43b24ba0eb83c5389c9ee2b2eaf9c7fec0cc2',
    BASE + 'operators/stage.py': 'c46828c0c6e15799ced2026709811bb0e6f54f3332b9c3830d8e89094aaa45fe',
    BASE + 'operators/activate.py': '701113da058353cfe5c346391ad7dbe5e50bc13c6e3ed91386f8015c043d0bea',
    BASE + 'operators/post_readback.py': 'c137be0819141c38745e2cf0a8563fe5441f53a5cc522303b2d1fb5ac69d4d68',
    BASE + 'prepare-package.py': '6f55df770081c5a3cfc45bdfa24c4d02b3bac2282d7bbdf5992e6f76e7f2c1af',
    BASE + 'bind-release.py': '3b6784e83a575b2d4b3420682bf186189cc760d3172ca2094ab83a123dafd02b',
}
SCRIPTS = ('ops_common.py', 'expo_contract.py', 'build.py', 'validate.py', 'stage.py', 'activate.py', 'post_readback.py')
OLD_MANIFEST = '3ce6cae326bb426703ab316c693a4e06c80c7fcae0abf853a9f8a9b31b7b43fc'
OLD_ARCHIVE = 'a4f956af3b964fb9ea1296d06376ccd85b4186974aa6228b2ab4f8e56d625c08'
PARENT_IMAGE = 'sha256:3b831aaf898dacebcf3bb733ada13271e1be7707bb41ecfb14d85cb9d6ebf133'
ENV_SHA = 'a72d456815cf113b1ac0c1e032ac8c45b300ccf2cb499520c14b7f54d5314e07'
WEB_IMAGE = 'sha256:1ae82dcc4a34bcd976195b3c4c5a6b7e569505527a1e2a28c2101e032159a5c7'
UNCHANGED = ('Dockerfile', 'compose.yaml', 'requirements.txt', 'deploy/nginx.conf', 'deploy/backup.py',
             'finance_hub.py', 'investment_operations.py', 'investment_import.py', 'inventory_core.py',
             'deploy/check_inventory_migration.py', 'deploy/check_media_migration.py',
             'deploy/check_finance_receipt_migration.py', 'deploy/check_investment_operation_migration.py')
REQUIRED_TESTS = {'tests/test_travel_release.py', 'tests/test_assistant_journey_brief.py',
                  'tests/test_journey_workflows.py', 'tests/test_journey_transaction_session.py',
                  'tests/test_journey_publication_review.py', 'tests/test_journey_details.py', 'tests/test_member_sessions.py',
                  'tests/test_investment_operation_migration.py',
                  'tests/test_investment_operations.py', 'tests/test_platform_backup.py', 'tests/test_frontend_runtime.py'}
DOCKER_CONTRACT = """def verify_docker_delta(old, new):
    need(old == new, 'Dockerfile must remain byte-identical to current installed 55-table baseline')
"""

# Embedded in the diagnostic, also executed against real disposable SQLite groups
# by tests. verify_current explicitly accepts populated operation receipts.
PRESERVATION_FUNCTION = '''def verify_preserved(before, after, schema):
    before_profile = verify_current(before, schema)
    after_profile = verify_current(after, schema)
    if before != after:
        raise RuntimeError('55-table rows/schema/sequences or registry changed')
    return {'originalTablesPreserved': 55, 'newTables': 0,
            'households': before_profile['households'], 'receiptRows': after_profile['receiptRows'],
            'allRowsSchemaAndSequencesPreserved': True, 'registryPreserved': True}
'''


def function_replace(source, name, replacement):
    nodes = [node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == name]
    need(len(nodes) == 1, 'Expected one function: ' + name)
    node = nodes[0]
    old = ''.join(source.splitlines(keepends=True)[node.lineno - 1:node.end_lineno])
    return replace(source, old, replacement)


def verify_generated(raw, name):
    """Inspect Python and Python embedded in strings; never execute an entrypoint."""
    forbidden = {'migrate', 'verify_baseline', 'verify_addition', 'initialize_database', 'create_app', 'executescript'}
    def check(tree):
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                need(not any(alias.name in forbidden for alias in node.names), 'Migration import in ' + name)
            if isinstance(node, ast.Call):
                called = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ''
                need(called not in forbidden, 'Migration/DDL call in ' + name)
                if called in {'execute', 'executemany'}:
                    need(node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
                         and node.args[0].value.lstrip().upper().startswith(('SELECT ', 'PRAGMA ')), 'Non-read-only SQL in ' + name)
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                # Only complete Python fragments are executable embedded programs.
                try:
                    nested = ast.parse(node.value)
                except (SyntaxError, ValueError):
                    continue
                if any(isinstance(item, (ast.Call, ast.ImportFrom)) for item in ast.walk(nested)):
                    check(nested)
    check(ast.parse(raw, filename=name))


def adapt(inputs, access, output, config=None):
    operators = {name: inputs[BASE + 'operators/' + name].decode('utf-8') for name in SCRIPTS}
    operators['expo_contract.py'] = function_replace(operators['expo_contract.py'], 'verify_docker_delta', DOCKER_CONTRACT)
    common = operators['ops_common.py']
    for name, value in {'CANDIDATE': 'Path(' + repr('/opt/family-dashboard-candidates/' + output.name) + ')',
                        'PARENT_IMAGE': repr(PARENT_IMAGE), 'OLD_MANIFEST': repr(OLD_MANIFEST),
                        'EXPECTED_TEST_COUNT': repr(config['expectedTestCount'] if config else None),
                        'EXPECTED_TESTS': repr(tuple(config['validationTests']) if config else ())}.items():
        common = assignment(common, name, value)
    common = replace(common, 'Bound 54 -> 55 finance release guards.', 'Bound 55 -> 55 travel source-update guards.')
    common = replace(common, "for name in ('compose.yaml','requirements.txt','deploy/nginx.conf','inventory_core.py',\n                 'deploy/check_inventory_migration.py','deploy/check_media_migration.py','deploy/backup.py'):",
                     'for name in ' + repr(UNCHANGED) + ':')
    operators['ops_common.py'] = common
    operators['build.py'] = replace(operators['build.py'], 'family-dashboard-expo-holdings:', 'family-dashboard-expo-travel:')
    stage = replace(operators['stage.py'], 'householdTablesBefore=54,householdTablesAfter=55,schemaChange=True,',
                    'householdTablesBefore=55,householdTablesAfter=55,schemaChange=False,')
    operators['stage.py'] = replace(stage, 'migrationDefinitionVerified=True', 'schemaDefinitionVerified=True')
    activate = operators['activate.py']
    activate = substitutions(activate, {'54 -> 55 receipt publication': '55 -> 55 travel source publication',
        "ready.get('migrationDefinitionVerified')": "ready.get('schemaDefinitionVerified')",
        "ready.get('householdTablesBefore')==54": "ready.get('householdTablesBefore')==55 and ready.get('schemaChange') is False",
        'Finance migration was not staged': '55-table preservation was not staged',
        'expo-holdings': 'expo-travel',
        'schema_definition,snapshot,verify_baseline,verify_current,verify_addition,validate_backup,migrate': 'schema_definition,snapshot,verify_current,validate_backup',
        'value=snapshot(Path(\'/data\'));verify_baseline(value)': "value=snapshot(Path('/data'));verify_current(value,schema)",
        'verify_baseline(before)': 'verify_current(before,schema)',
        'complete_54_table_household_and_registry_backup_validated_and_preserved': 'complete_55_table_household_and_registry_backup_validated_and_preserved',
    })
    activate = replace(activate, "    snapshot_program=schema_guard+", "    schema_guard += " + repr(PRESERVATION_FUNCTION) + "\n    snapshot_program=schema_guard+")
    start = activate.index("    need(diagnostic(snapshot_program)==before, 'Data changed before receipt migration')")
    end = activate.index('    # Retire the entire verified generated directory', start)
    activate = replace(activate, activate[start:end], '''    need(diagnostic(current_program)==before, 'Data changed before source installation')
    record('all_55_tables_and_registry_unchanged_before_source_installation')

''')
    activate = replace(activate, "    need(after==migrated, 'App startup changed migrated 55 tables or registry')\n    write_new(proof/'after-app.json',after)",
'''    need(after==before, 'App startup changed 55-table data/schema/sequences or registry')
    write_new(proof/'after-app.json',after);os.chown(proof/'after-app.json',10001,10001)
    preservation_program=schema_guard+"""
before=json.loads(Path('/proof/before.json').read_text())
after=json.loads(Path('/proof/after-app.json').read_text())
if snapshot(Path('/data'))!=after:raise RuntimeError('Data changed after app snapshot')
print(json.dumps(verify_preserved(before,after,schema)))
"""
    preservation=diagnostic(preservation_program)
    need(preservation=={'originalTablesPreserved':55,'newTables':0,'households':len(before['households']),
         'receiptRows':sum(v['tables']['hub_investment_operations']['count'] for v in before['households'].values()),
         'allRowsSchemaAndSequencesPreserved':True,'registryPreserved':True}, 'Unexpected preservation result')
    write_new(proof/'preservation.json',preservation)
''')
    activate = replace(activate, "    write_new(CANDIDATE/'activation.json',report)",
                       "    report.pop('productionWrites', None)  # READY counted only the earlier read-only stage.\n    write_new(CANDIDATE/'activation.json',report)")
    activate = replace(activate, 'backupCheck=backup_check,schemaChange=True,\n        migrationResult=migration_result,migrationCheck=migration_check,baselineCheckPending=False,',
                       'backupCheck=backup_check,schemaChange=False,\n        preservationResult=preservation,baselineCheckPending=False,')
    operators['activate.py'] = activate
    post = replace(operators['post_readback.py'], 'expo-holdings-55-', 'expo-travel-55-')
    start = post.index("    for name in ('after-app.json','after-migration.json','migration.json','migration-check.json'):")
    end = post.index("    need(sha(ROOT/'RELEASE-MANIFEST.json')", start)
    post = replace(post, post[start:end], '''    for name in ('before.json','after-app.json','preservation.json'):
        need(sha(proof_root/name)==published['proofHashes'][name], 'Completed activation proof changed')
    activation_snapshot=read(proof_root/'after-app.json')
    preservation=read(proof_root/'preservation.json')
    need(activation_snapshot==read(proof_root/'before.json')
         and preservation==published['preservationResult']
         and preservation=={'originalTablesPreserved':55,'newTables':0,'households':published['households'],
             'receiptRows':sum(v['tables']['hub_investment_operations']['count'] for v in activation_snapshot['households'].values()),
             'allRowsSchemaAndSequencesPreserved':True,'registryPreserved':True}
         and published['householdTables']==55 and published['schemaChange'] is False
         and published['allExistingDataPreservedAtAppStartup'] is True,
         'Completed 55-table preservation evidence differs')
''')
    operators['post_readback.py'] = post
    prepare = inputs[BASE + 'prepare-package.py'].decode('utf-8')
    for name, value in {'A': 'Path(' + repr(str(access)) + ')', 'OUT': 'Path(' + repr(str(output / 'package')) + ')',
                        'CONTRACT': 'Path(' + repr(str(output / 'operators/expo_contract.py')) + ')',
                        'CONTRACT_SHA': repr(sha(operators['expo_contract.py'].encode()))}.items():
        prepare = assignment(prepare, name, value)
    prepare = substitutions(prepare, {
        'f5a49949e6d868533392f64fa46c4042a85df635b2f8123b3f05076a7d619976': OLD_MANIFEST,
        'sha256:4433d1d5c97ec4ed4a1336c2402b0fae121a04e092050ff9eb2821ac61fa4798': PARENT_IMAGE,
        'currently reviewed 54-table production baseline': 'currently reviewed 55-table production baseline',
    })
    prepare = replace(prepare, '    return value\n\n\ndef git(*args):',
                      '    need(value[\'oldArchiveSha256\']==' + repr(OLD_ARCHIVE) + ", 'Wrong installed holdings archive')\n    return value\n\n\ndef git(*args):")
    prepare = replace(prepare, "    contract['verify_docker_delta'](old_blobs['Dockerfile'], docker)",
                      "    contract['verify_docker_delta'](old_blobs['Dockerfile'], docker)\n    for name in " + repr(UNCHANGED) + ":\n        need(manifest.get(name)==old.get(name) and name in old, 'Unchanged schema/dependency differs: '+name)")
    prepare = replace(prepare, "'frontend/src/screens/FinanceScreen.tsx', 'frontend/src/screens/InvestmentsScreen.tsx'",
                      "'frontend/src/screens/FinanceScreen.tsx', 'frontend/src/screens/InvestmentsScreen.tsx',\n          'frontend/src/screens/JourneyBriefPanel.tsx', 'frontend/src/lib/journeyBrief.ts', 'journey_workflows.py'")
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
    namespace = {'__name__': 'travel_freeze_check', '__file__': str(access / 'travel-prepare-validation.py')}
    # Only reviewed definitions are evaluated; no package or Git operation is called.
    exec(compile(generated['prepare-package.py'], namespace['__file__'], 'exec'), namespace)
    namespace['validate_config'](config)
    need(REQUIRED_TESTS <= set(config['validationTests']), 'Required travel/preservation tests missing')
    need(not {'tests/test_expo_assistant_flow.py', 'tests/test_expo_trips_api.py'} & set(config['validationTests']),
         'Node/TypeScript tests cannot run in this Python-only image')
    return raw, config


def prepare(access, output, freeze=None):
    access, output = safe_path(access), safe_path(output, exists=False)
    need(output.parent == access and re.fullmatch('expo-travel-tools-[a-z0-9-]+', output.name), 'New travel output must be directly under access root')
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
