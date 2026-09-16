"""Materialize the reviewed finance operators with a bounded 54 -> 55 adapter.

Reads only pinned local operator sources. Does not run generated code, Git,
Docker, SSH, network clients, database tools or production commands.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import sys


BASE = 'expo-finance-release-20260917-r2/'
PINNED = {
    BASE + 'ops_common.py': '79c01bfb72086082298e12f7ea5891d7403a38e9ec960f661156b56ee07832c5',
    BASE + 'expo_contract.py': '17d3f2ddc67051220b470da1ff239ab4b0bb2e1daf0a8803ae70ad19179b9085',
    BASE + 'build.py': 'f99854ffa1d94125eb48f6d27be550bf4b0f75997d657c5dc1ad1d13ccc24169',
    BASE + 'validate.py': '4c0d8fa8a38133b1e420d8f2b141606c406e1ea142146851831c73421bc9937f',
    BASE + 'stage.py': '8ef2d1dda6fc6715c0bda07c0a8e0eb4c3607a39857d4e117c1d71587fe2cc22',
    BASE + 'activate.py': '7d21934dde859788ea7fc147f864307dea0a3920cf1c0399f5dfe386476482a0',
    BASE + 'post_readback.py': '91f3aa348ee4d36472ceffc6a7398cc4974e6d189ea87d38a3eee35dcda94603',
    'expo-finance-post-r3-20260917/post_readback_r3.py': '09c32314b68f1a135bc9f613daa3a02bbc74b8cd4aa35486c5abbb8335383d35',
    'prepare-expo-finance-package.py': 'e0bdc96511015cf2b882da1be88db9fb9e058fdae264cdf7533b43a7eab5a2f9',
    'bind-expo-finance-release-r2.py': '9d28ec054d48f3ddb5e87534f0e032a1ca2e31b78955d0d86286046ddef45d02',
}
OLD_MANIFEST = 'f5a49949e6d868533392f64fa46c4042a85df635b2f8123b3f05076a7d619976'
PARENT_IMAGE = 'sha256:4433d1d5c97ec4ed4a1336c2402b0fae121a04e092050ff9eb2821ac61fa4798'
WEB_IMAGE = 'sha256:1ae82dcc4a34bcd976195b3c4c5a6b7e569505527a1e2a28c2101e032159a5c7'
ENV_SHA = 'a72d456815cf113b1ac0c1e032ac8c45b300ccf2cb499520c14b7f54d5314e07'
SCRIPTS = ('ops_common.py', 'expo_contract.py', 'build.py', 'validate.py', 'stage.py', 'activate.py', 'post_readback.py')
REQUIRED_TESTS = {
    'tests/test_investment_operations.py', 'tests/test_investment_import.py',
    'tests/test_finance_hub.py', 'tests/test_investment_operation_migration.py',
    'tests/test_investment_operation_portability.py', 'tests/test_frontend_runtime.py',
}


def need(value, message):
    if not value:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def safe_path(path, *, exists=True):
    path = Path(path)
    need(path.is_absolute() and '..' not in path.parts and not any(p.is_symlink() or getattr(p, 'is_junction', lambda: False)()
                                       for p in (path, *path.parents)), 'Absolute unlinked path required')
    if exists:
        need(path.exists(), 'Required local input missing')
    return path


def unique(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, 'Duplicate JSON key')
        result[key] = value
    return result


def replace(source, before, after, count=1):
    need(source.count(before) == count, 'Pinned source fragment differs: ' + before[:85])
    return source.replace(before, after)


def substitutions(source, mapping):
    """Simultaneous replacements: an old 54 must not also replace a new 54."""
    need(all(source.count(key) for key in mapping), 'Pinned source substitution absent')
    pattern = '|'.join(re.escape(key) for key in sorted(mapping, key=len, reverse=True))
    return re.sub(pattern, lambda match: mapping[match[0]], source)


def assignment(source, name, expression):
    nodes = [node for node in ast.parse(source).body if isinstance(node, ast.Assign)
             and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)]
    need(len(nodes) == 1, 'Expected unique source assignment: ' + name)
    node = nodes[0]
    lines = source.splitlines(keepends=True)
    old = ''.join(lines[node.lineno - 1:node.end_lineno])
    return replace(source, old, name + ' = ' + expression + '\n')


DOCKER_CONTRACT = '''def verify_docker_delta(old, new):
    before = b'COPY calendar_publish.py financial_files.py investment_import.py ./\\r\\n'
    after = b'COPY calendar_publish.py financial_files.py investment_import.py investment_operations.py ./\\n'
    need(old.count(before) == 1 and b'investment_operations.py' not in old,
         'Installed Dockerfile does not have the reviewed investment COPY line')
    need(new == old.replace(before, after),
         'Only investment_operations.py may be added to the existing Docker COPY')
'''


MIGRATION_ENVIRONMENT = '''# Test deploy helpers come from /test-support, while modules must use /app.
# Both the 55-table helper and its 54-table predecessor check their own origins.
schema_bindings=[]
for helper_name,module_name in (
 ('deploy.check_finance_receipt_migration','finance_hub'),
 ('deploy.check_investment_operation_migration','investment_operations')):
 helper=importlib.import_module(helper_name)
 module=importlib.import_module(module_name)
 helper_file=helper_name.replace('.','/')+'.py';module_file=module_name+'.py'
 helper_path=support/helper_file
 if Path(helper.__file__).resolve()!=helper_path or helper.ROOT!=support:
  raise RuntimeError('Migration helper must originate in checked test-support source')
 if Path(module.__file__).resolve()!=runtime/module_file or getattr(helper,module_name) is not module:
  raise RuntimeError('Migration must use the real image schema module')
 source_digest=manifest[module_file]
 if hashlib.sha256((runtime/module_file).read_bytes()).hexdigest()!=source_digest or hashlib.sha256((support/module_file).read_bytes()).hexdigest()!=source_digest:
  raise RuntimeError('Runtime and source schema bytes differ')
 if hashlib.sha256(helper_path.read_bytes()).hexdigest()!=manifest[helper_file]:
  raise RuntimeError('Migration helper bytes changed')
 helper.ROOT=runtime
 schema=helper.schema_definition()
 if schema['sourceSha256']!=source_digest:raise RuntimeError('Migration schema-source check failed')
 schema_bindings.append((helper,module,module_name,schema))
evidence['migrationTestEnvironment']=[
 {'helperPath':str(Path(helper.__file__).resolve()),'originalSchemaRoot':str(support),
  'schemaRoot':str(runtime),'modulePath':str(Path(module.__file__).resolve()),
  'sourceSha256':schema['sourceSha256'],'schemaSha256':schema['sha256'],
  'adaptation':'Only helper ROOT points to verified image source; production helper/assertions unchanged'}
 for helper,module,module_name,schema in schema_bindings]
'''


def adapt(inputs, access, output, config=None):
    """Pure text adaptation of pinned sources. No generated operator executes."""
    server = '/opt/family-dashboard-candidates/' + output.name
    operators = {name: inputs[BASE + name].decode('utf-8') for name in SCRIPTS}
    contract = replace(operators['expo_contract.py'],
        "def verify_docker_delta(old, new):\n    need(old == new, 'Dockerfile must remain byte-identical to current installed baseline')\n",
        DOCKER_CONTRACT)
    operators['expo_contract.py'] = contract
    common = operators['ops_common.py']
    common = assignment(common, 'CANDIDATE', 'Path(' + repr(server) + ')')
    common = assignment(common, 'PARENT_IMAGE', repr(PARENT_IMAGE))
    common = assignment(common, 'OLD_MANIFEST', repr(OLD_MANIFEST))
    common = assignment(common, 'EXPECTED_TEST_COUNT', repr(config['expectedTestCount'] if config else None))
    common = assignment(common, 'EXPECTED_TESTS', repr(tuple(config['validationTests']) if config else ()))
    common = substitutions(common, {
        '53 -> 54': '54 -> 55', 'finance_receipts54': 'investment_operations55',
        'deploy.check_finance_receipt_migration': 'deploy.check_investment_operation_migration',
        'deploy/check_finance_receipt_migration.py': 'deploy/check_investment_operation_migration.py',
        "'finance_hub.py'": "'investment_operations.py'",
        'Linux count differs from reviewed 418-test selection': 'Linux count differs from frozen test selection',
        'JUnit must contain 417 passes and only the exact Windows junction skip': 'JUnit must match the frozen count and exact Windows junction skip',
    })
    # None/empty are deliberately unusable before a real final freeze is supplied.
    common = replace(common, '    binding=read(BINDING_PATH)\n',
        "    need(type(EXPECTED_TEST_COUNT) is int and 1 < EXPECTED_TEST_COUNT < 10000 and EXPECTED_TESTS,\n"
        "         'Operator template lacks a final verified test/source freeze')\n    binding=read(BINDING_PATH)\n")
    operators['ops_common.py'] = common
    operators['build.py'] = replace(operators['build.py'], 'family-dashboard-expo-finance:', 'family-dashboard-expo-holdings:')
    validate = operators['validate.py']
    start = validate.index('# The image owns runtime modules;')
    end = validate.index("(proof/'runtime.json').write_text", start)
    validate = replace(validate, validate[start:end], MIGRATION_ENVIRONMENT)
    validate = replace(validate,
        "if receipt_migration.ROOT!=runtime or receipt_migration.finance_hub is not finance_module or receipt_migration.schema_definition()!=schema:\n raise RuntimeError('Migration test source binding changed')",
        "for helper,module,module_name,schema in schema_bindings:\n"
        " if helper.ROOT!=runtime or getattr(helper,module_name) is not module or helper.schema_definition()!=schema:\n"
        "  raise RuntimeError('Migration test source binding changed')")
    validate = replace(validate, 'Frozen Linux selection: 417 passes plus the exact Windows junction skip;',
                        'Frozen Linux selection: verified count and the exact Windows junction skip;')
    operators['validate.py'] = validate
    operators['stage.py'] = replace(operators['stage.py'], 'householdTablesBefore=53,householdTablesAfter=54',
                                    'householdTablesBefore=54,householdTablesAfter=55')
    operators['activate.py'] = substitutions(operators['activate.py'], {
        '53 -> 54': '54 -> 55', "==53 and ready.get('householdTablesAfter')==54": "==54 and ready.get('householdTablesAfter')==55",
        'expo-finance-54-': 'expo-holdings-55-', 'expo-finance': 'expo-holdings',
        'deploy.check_finance_receipt_migration': 'deploy.check_investment_operation_migration',
        'complete_53_table': 'complete_54_table', 'all_53_tables': 'all_54_tables',
        'complete 53-table': 'complete 54-table', 'migrated 54 tables': 'migrated 55 tables',
        'new_app_healthy_all_54_tables': 'new_app_healthy_all_55_tables', 'householdTables=54': 'householdTables=55',
    })
    operators['activate.py'] = replace(operators['activate.py'],
        "'originalTablesPreserved':53", "'originalTablesPreserved':54")
    # Use the whole independently reviewed r3 operator, keeping its fresh backup
    # service invocation binding and closed-snapshot-only immutable reads intact.
    post = inputs['expo-finance-post-r3-20260917/post_readback_r3.py'].decode('utf-8')
    post = substitutions(post, {
        "own_path.name=='post_readback_r3.py'": "own_path.name=='post_readback.py'",
        'deploy.check_finance_receipt_migration': 'deploy.check_investment_operation_migration',
        'expo-finance-54-': 'expo-holdings-55-', 'householdTables\']==54': "householdTables']==55",
        'Completed 54-table': 'Completed 55-table', "tablesPerHousehold']==54": "tablesPerHousehold']==55",
        'activationHouseholdTables=54': 'activationHouseholdTables=55', 'activationStartup54Verified': 'activationStartup55Verified',
        'post-readback-r3': 'post-readback',
    })
    post = replace(post, "not (CANDIDATE/'post-readback.json').exists() and not (CANDIDATE/'post-readback.json').exists()",
                        "not (CANDIDATE/'post-readback.json').exists()")
    post = replace(post, "'/app/connections','/app/finance'):", "'/app/connections','/app/finance','/app/investments'):")
    post = replace(post, "'/api/finance-hub/imports/results/'+'0'*32):",
        "'/api/finance-hub/imports/results/'+'0'*32,\n"
        "                 '/api/finance-hub/investments','/api/finance-hub/investments/operations/'+'0'*32,\n"
        "                 '/api/finance-hub/investments/imports/receipts?sourceName=anonymous&sourceDigest='+'0'*64):")
    operators['post_readback.py'] = post

    prepare = inputs['prepare-expo-finance-package.py'].decode('utf-8')
    prepare = assignment(prepare, 'A', 'Path(' + repr(str(access)) + ')')
    prepare = assignment(prepare, 'OUT', 'Path(' + repr(str(output / 'package')) + ')')
    prepare = assignment(prepare, 'CONTRACT', 'Path(' + repr(str(output / 'operators' / 'expo_contract.py')) + ')')
    prepare = assignment(prepare, 'CONTRACT_SHA', repr(sha(contract.encode())))
    prepare = replace(prepare, "old_raw, old, _ = archive_contents(config['oldArchivePath'], config['oldArchiveSha256'], config['oldManifestSha256'])",
                               "old_raw, old, old_blobs = archive_contents(config['oldArchivePath'], config['oldArchiveSha256'], config['oldManifestSha256'])")
    prepare = replace(prepare, "need('Dockerfile' in old and old['Dockerfile'] == manifest['Dockerfile'], 'Installed Dockerfile must remain identical')",
        "need('Dockerfile' in old, 'Installed Dockerfile absent')\n    contract['verify_docker_delta'](old_blobs['Dockerfile'], docker)")
    prepare = substitutions(prepare, {
        "blobs['finance_hub.py']": "blobs['investment_operations.py']",
        'FINANCE_IMPORT_RECEIPTS_SCHEMA_SQL': 'INVESTMENT_OPERATIONS_SCHEMA_SQL',
        "manifest['finance_hub.py']": "manifest['investment_operations.py']",
        "'deploy/check_finance_receipt_migration.py'": "'deploy/check_investment_operation_migration.py'",
        "'frontend/src/screens/FinanceImportPanel.tsx'": "'frontend/src/screens/InvestmentsScreen.tsx'",
    })
    prepare = replace(prepare, "need({'finance_hub.py', 'data_portability.py',", "need({'finance_hub.py', 'investment_operations.py', 'data_portability.py',")
    final_check = ("    need(value['oldManifestSha256']==" + repr(OLD_MANIFEST)
        + " and value['parentImage']==" + repr(PARENT_IMAGE) + "\n"
        + "         and value['envSha256']==" + repr(ENV_SHA) + " and value['oldImages']['web']==" + repr(WEB_IMAGE)
        + ", 'Freeze must use the currently reviewed 54-table production baseline')\n")
    prepare = replace(prepare, '    return value\n\n\ndef git(*args):', final_check + '    return value\n\n\ndef git(*args):')
    prepare = replace(prepare, 'prepare-expo-finance-package.py --freeze FINAL.json', 'prepare-package.py --freeze FINAL.json')
    binder = inputs['bind-expo-finance-release-r2.py'].decode('utf-8')
    for name, value in {'A': access, 'PACK': output / 'package', 'OPS': output / 'operators', 'PREPARE': output / 'prepare-package.py'}.items():
        binder = assignment(binder, name, 'Path(' + repr(str(value)) + ')')
    binder = substitutions(binder, {'finance_receipts54': 'investment_operations55', "manifest['finance_hub.py']": "manifest['investment_operations.py']",
                                     'bind-expo-finance-release-r2.py --operator-review': 'bind-release.py --operator-review'})
    generated = {'operators/' + name: code.encode('utf-8') for name, code in operators.items()}
    generated.update({'prepare-package.py': prepare.encode('utf-8'), 'bind-release.py': binder.encode('utf-8')})
    for name, raw in generated.items():
        ast.parse(raw, filename=name)
    return generated


def read_sources(access):
    need(safe_path(access).is_dir(), 'Operator source root must be a directory')
    result = {}
    for relative, expected in PINNED.items():
        path = safe_path(access / relative)
        need(path.is_file() and path.stat().st_size < 100_000, 'Bounded operator source required')
        raw = path.read_bytes()
        need(sha(raw) == expected, 'Reviewed operator source checksum changed: ' + relative)
        # All original operators are pinned as bytes; normalize only the local
        # representation used by exact text replacements, never source files.
        result[relative] = raw.replace(b'\r\n', b'\n')
    return result


def freeze_config(path, access, sources):
    path = safe_path(path)
    need(path.is_file() and path.is_relative_to(access) and path.stat().st_size <= 2_000_000,
         'Freeze must be a bounded private access artifact')
    raw = path.read_bytes()
    need(len(raw) <= 2_000_000, 'Freeze changed size during reading')
    config = json.loads(raw.decode('utf-8'), object_pairs_hook=unique)
    # Only execute pinned, previously reviewed definition/import code. Its
    # validation reads path metadata; package preparation and Git are not called.
    namespace = {'__name__': 'holdings_freeze_validation', '__file__': str(access / 'prepare-expo-finance-package.py')}
    exec(compile(sources['prepare-expo-finance-package.py'], namespace['__file__'], 'exec'), namespace)
    namespace['validate_config'](config)
    need(REQUIRED_TESTS <= set(config['validationTests']), 'Required holdings and migration tests missing')
    need(config['oldManifestSha256'] == OLD_MANIFEST and config['parentImage'] == PARENT_IMAGE
         and config['envSha256'] == ENV_SHA and config['oldImages']['web'] == WEB_IMAGE,
         'Freeze is not the reviewed current 54-table baseline')
    return raw, config


def prepare(access, output, freeze=None):
    access, output = safe_path(access), safe_path(output, exists=False)
    need(output.parent == access and re.fullmatch('expo-holdings-tools-[a-z0-9-]+', output.name),
         'Output must be a new named holdings tools directory directly under the private access root')
    need(not output.exists(), 'Output already exists; preserve previous attempts')
    sources = read_sources(access)
    freeze_raw, config = freeze_config(safe_path(freeze), access, sources) if freeze else (None, None)
    generated = adapt(sources, access, output, config)
    # Exclusive directory/file creation and a second full source read prevent
    # overwriting earlier attempts or materializing changed reviewed inputs.
    need(read_sources(access) == sources, 'Reviewed source changed during generation')
    if freeze:
        need(safe_path(freeze).read_bytes() == freeze_raw, 'Final freeze changed during generation')
    output.mkdir(mode=0o700)
    for name, raw in generated.items():
        path = output / name
        path.parent.mkdir(exist_ok=True, mode=0o700)
        with path.open('xb') as stream:
            stream.write(raw)
        path.chmod(0o600)
    report = {'schemaVersion': 1, 'bound': False, 'requiresIndependentOperatorReview': True,
              'finalFreezeProvided': config is not None, 'freezeSha256': sha(freeze_raw) if freeze_raw else None,
              'expectedTestCount': config['expectedTestCount'] if config else None,
              'serverCandidate': '/opt/family-dashboard-candidates/' + output.name,
              'profile': 'investment_operations55', 'oldManifestSha256': OLD_MANIFEST,
              'sourceHashes': PINNED, 'generatedHashes': {name: sha(raw) for name, raw in generated.items()},
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
    need(sys.dont_write_bytecode and not sys.flags.optimize and sys.pycache_prefix is None,
         'Run python -B without optimization or pycache prefix')
    print(json.dumps(prepare(args.source_root, args.output, args.freeze), indent=2))


if __name__ == '__main__':
    main()
