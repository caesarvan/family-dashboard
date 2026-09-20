"""Prepare one fixed 73-to-75 journey-finance plan; no production operation."""
import ast
from pathlib import Path
import re
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy import build_journey_finance_release as package
from deploy import prepare_finance_flow_activation as parent
from deploy import prepare_local_photo_activation as shared
from deploy.membership_release_archive import read_archive
from deploy.membership_release_controller import need, regular, read, sha

MODE = 'journey-finance-73-to-75'
KIND = 'journey-finance-five-service-migration-v1'
PARENT_SOURCE, PARENT_MANIFEST = package.INSTALLED_SOURCE, package.OLD_MANIFEST
PARENT_PLAN_SHA256 = '8185025cdb0a65cd8fd8f0e30c968c14e4bea1f4dbcec5100af6a3765f632c34'
PARENT_BUILD_SHA256 = 'a880823a491b44e1568dd20c95026205e3e547f985ae0b6dce5e5bb51996e1e6'
OPERATORS = sorted(set(parent.OPERATORS) | {
    'deploy/build_journey_finance_release.py', 'deploy/prepare_journey_finance_activation.py',
    'deploy/activate_journey_finance_release.py', 'deploy/check_journey_finance_migration.py',
    'deploy/journey_finance_release_data.py'})
REVIEW_ROLES = shared.REVIEW_ROLES | {'migration'}
MIGRATION_STAGES = {'verify', 'seed', 'migrate', 'startup', 'check', 'rollback73',
                    'partial', 'populate75', 'restart', 'restore75'}
MIGRATION_RUNTIME_SOURCE = 'a47372624e66cab0e8100a37f54223737780eb73'
MIGRATION_CLOSURE = {
    'journey_finance.py', 'finance_hub.py', 'financial_files.py', 'finance_source_bridge.py', 'finance_baseline.py',
    'deploy/check_journey_finance_migration.py', 'deploy/journey_finance_release_data.py',
    'deploy/check_media_video_migration.py', 'deploy/media_video_release_data.py',
    'deploy/assistant_trip_change_release_data.py', 'deploy/membership_release_data.py',
    'deploy/membership_migration.py'}

POPULATED_ROWS = {'hub_journey_allocations': 3, 'hub_journey_allocation_operations': 1}
REQUIRED_NODEIDS_SHA256 = '5e36b8bf25cb156158ff813afd42586fed4ce442c0faf4b96173304c376628b4'
TEST_MODULES = {'tests/test_data_portability.py': 'd6bfa606fb5a5f136a6a2fd4bd2c9653077c11622657c2ba531580f592367fbe', 'tests/test_journey_finance.py': '9a068948f0943d49ec8018a35e7ae10cecb1dd8f06cd729fc98ca3cedb010067', 'tests/test_journey_finance_portability.py': '29ee389409d20456cd02b033428a154261cc612c4c39995951ef1e620626b104', 'tests/test_journey_finance_sessions.py': '71900fefb3ac70627022519a4e3135cef611971c61a0698057775ec70ee2e50b', 'tests/test_shopping_settlement.py': '7a5ee5da22dd67c0eae932a555f074cf8875ab70111a1b2889a523f7525d9fbc'}


def plan_images(plan): return shared.plan_images(plan, mode=MODE)
def check_plan(plan): return shared.check_plan(plan, mode=MODE)
def prepare(inputs_file, env_sha256, output):
    return shared.prepare(inputs_file, env_sha256, output, mode=MODE)


def runtime_boundary(old, current):
    old, current = ({n: h for n, h in m.items() if not n.startswith('static/experience/')}
                    for m in (old, current))
    kept = {n: h for n, h in current.items() if n not in package.CHANGED_RUNTIME_FILES}
    need(len(current) == 113 and len(kept) == 110 and
         sha(package.package.encoded(kept)) == package.PRESERVED_RUNTIME_SHA256 and
         all(current.get(n) == h for n, h in package.CHANGED_MODULES.items()) and
         old == {**kept, **package.PARENT_MODULES} and len(old) == 112 and
         sha(package.package.encoded(old)) == package.PARENT_RUNTIME_SHA256,
         'retained_journey_runtime_boundary_changed')


def unchanged_media_ast(name, before, after):
    """Strip only exact reviewed registration/export additions, never a whole function."""
    need(name in package.PARENT_MODULES and sha(before) == package.PARENT_MODULES[name] and
         sha(after) == package.CHANGED_MODULES[name], 'retained_journey_module_changed')
    original, current = ast.parse(before), ast.parse(after)
    if name == 'app.py':
        snippets = [
            'from journey_finance import register_journey_finance',
            'register_journey_finance(app, db, Problem, body, require_member, audit)']
    else:
        snippets = [
            'from journey_finance import export_owned_allocations',
            "if {'hub_journey_allocations', 'hub_journey_allocation_operations'}.issubset(available):\n"
            "    personal['journeyAllocations'] = export_owned_allocations(con, uid)\n"
            "    snapshot['coverage']['journeyAllocations'] = 'owner_allocations_and_minimal_operations_without_preview_or_source_digests'"]
        # The README entry is one list element; all other export statements remain compared.
        note = 'personal.journeyAllocations 仅含本人旅行费用关联和最小操作摘要，保留已删除旅行或付款的引用；不含请求编号、来源或请求摘要、预览凭据与历史标题。金额不加入共享旅行或原交易CSV，勾选共同记录不扩大权限。此副本不能导入或重放归集操作。\n'
        matches = 0
        for node in ast.walk(current):
            if isinstance(node, ast.List):
                for value in list(node.elts):
                    if isinstance(value, ast.Constant) and value.value == note:
                        node.elts.remove(value); matches += 1
        need(matches == 1, 'journey_export_note_changed')
    for text in snippets:
        expected = ast.dump(ast.parse(text).body[0], include_attributes=False)
        matches = 0
        for node in ast.walk(current):
            for _, values in ast.iter_fields(node):
                if isinstance(values, list):
                    for value in list(values):
                        if isinstance(value, ast.AST) and ast.dump(value, include_attributes=False) == expected:
                            values.remove(value); matches += 1
        need(matches == 1, 'journey_registration_changed')
    need(ast.dump(original, include_attributes=False) == ast.dump(current, include_attributes=False),
         'retained_media_behavior_changed')
    return {'sha256Before': sha(before), 'sha256After': sha(after), 'unchangedOutsideExactAdditions': True}


def retained_parent(inputs, value):
    spec = inputs.get('retainedFinance')
    need(isinstance(spec, dict) and set(spec) == {'package', 'build', 'plan'} and
         spec['package'].get('sha256') == package.OLD_PACKAGE and
         spec['build'].get('sha256') == PARENT_BUILD_SHA256 and
         spec['plan'].get('sha256') == PARENT_PLAN_SHA256 and
         set(spec['plan']) == {'path', 'sha256'} and Path(spec['plan']['path']).is_absolute(),
         'retained_finance_identity_changed')
    proot, metadata = shared.record(spec['package'], 'package.json')
    broot, built = shared.record(spec['build'], 'build.json')
    plan = read(regular(spec['plan']['path']), PARENT_PLAN_SHA256)
    manifest = read(proot/'release-manifest.json', package.OLD_MANIFEST)
    # Never execute retained Python or weaken the current packager's self check.
    need(shared.previous.file_map(proot) == plan['verifiedEvidence']['package'] and
         sha(regular(proot/'source.tar.gz').read_bytes()) == metadata['archiveSha256'] and
         sha(regular(proot/'build-evidence.json').read_bytes()) == metadata['buildEvidenceSha256'],
         'retained_finance_package_changed')
    blobs = read_archive(proot/'source.tar.gz')
    need(blobs.pop('RELEASE-MANIFEST.json') == regular(proot/'release-manifest.json').read_bytes() and
         {n: sha(raw) for n, raw in blobs.items()} == manifest['files'], 'retained_finance_archive_changed')
    package.package.validate_maps(metadata, manifest, read(proot/'build-evidence.json'), baseline=package.parent.BASELINE)
    need(shared.previous.file_map(broot) == plan['verifiedEvidence']['build'] and
         metadata['sourceHead'] == manifest['sourceHead'] == package.INSTALLED_SOURCE and
         metadata['tree'] == manifest['tree'] == package.INSTALLED_TREE and
         built.get('exitCode') == 0 and built.get('productionOperations') is False and
         built.get('sourceHead') == package.INSTALLED_SOURCE and built.get('tree') == package.INSTALLED_TREE and
         built.get('packageSha256') == package.OLD_PACKAGE and built.get('manifestSha256') == package.OLD_MANIFEST and
         built.get('imageId') == plan['images']['app'] == package.PARENT_IMAGE and
         built.get('runtimeHashes') == metadata['runtimeFiles'] and
         plan['images']['decoder'] == package.DECODER_IMAGE, 'retained_finance_build_changed')
    runtime_boundary(metadata['runtimeFiles'], value['metadata']['runtimeFiles'])
    parent.resource_descriptors(inputs, plan)
    retained = inputs.get('retainedDiscovery')
    need(isinstance(retained, dict) and set(retained) == {'package', 'build', 'plan'} and
         all(retained[k].get('sha256') == plan['inputs']['retainedDiscovery'][k]['sha256'] for k in retained),
         'retained_discovery_descriptor_changed')
    return {'metadata': metadata, 'blobs': blobs}, built, plan, {
        'package': shared.previous.file_map(proot), 'build': shared.previous.file_map(broot), 'plan': PARENT_PLAN_SHA256}


def resource_evidence(inputs, value, built):
    retained, old_build, plan, originals = retained_parent(inputs, value)
    old = parent.resource_evidence(inputs, retained, old_build)
    need(all(old[k] == plan['verifiedEvidence'][k] for k in old), 'retained_finance_resource_proof_changed')
    ast_proofs = {n: unchanged_media_ast(n, retained['blobs'][n], value['blobs'][n])
                  for n in package.PARENT_MODULES}
    return {**old, 'retainedFinance': {
        'scope': 'unchanged-media-and-metadata-only-not-journey-finance-load-or-75-restore',
        'parentSource': package.INSTALLED_SOURCE, 'parentRuntimeSha256': package.PARENT_RUNTIME_SHA256,
        'preservedRuntimeCount': 110, 'preservedRuntimeSha256': package.PRESERVED_RUNTIME_SHA256,
        'registrationAndExportAst': ast_proofs, **originals},
        'migrationRehearsal': verify_migration(inputs['migrationRehearsal'], value, built)}


def verify_migration(spec, value, built):
    need(isinstance(spec, dict) and set(spec) == {'input', 'run'}, 'migration_descriptor')
    iroot, inputs = shared.record(spec['input'], 'input.json')
    root, result = shared.record(spec['run'], 'result.json')
    meta = value['metadata']
    modules = {n: h for n, h in meta['runtimeFiles'].items() if '/' not in n}
    need(inputs.get('kind') == 'journey-finance-migration-linux-input-v1' and
         inputs.get('historicalHead') == PARENT_SOURCE and inputs.get('productionOperations') is False and
         re.fullmatch('[0-9a-f]{40}', inputs.get('sourceHead', '')) and
         re.fullmatch('[0-9a-f]{40}', inputs.get('tree', '')) and
         inputs.get('runtimeSourceHead') == MIGRATION_RUNTIME_SOURCE and
         inputs.get('runtimeFiles') == modules, 'migration_runtime_differs')
    shared.previous.hashes_at(iroot, inputs['files'])
    sources = inputs.get('sourceFiles', {})
    tool = 'deploy/journey_finance_migration_linux_probe.py'
    need(MIGRATION_CLOSURE | {tool} <= sources.keys() and
         all(sources[n] == meta['sourceFiles'].get(n) for n in MIGRATION_CLOSURE | {tool}) and
         {n.removeprefix('release/'): h for n, h in inputs['files'].items() if n.startswith('release/')} == sources,
         'migration_source_closure_changed')
    need(result.get('passed') is True and result.get('syntheticOnly') is True and
         result.get('productionAccess') is False and result.get('imageId') == built['imageId'] and
         result.get('inputSha256') == spec['input']['sha256'], 'migration_not_passed')
    shared.previous.hashes_at(root/'proof', result['proofHashes'])
    stages = result.get('stages', {})
    need(set(stages) == MIGRATION_STAGES and stages['verify'].get('verified') is True and
         stages['verify'].get('uid') == 10001 and stages['verify'].get('runtime') == modules,
         'migration_stages_incomplete')
    need(stages['seed'].get('households') == 2 and stages['seed'].get('databases') == 3,
         'migration_requires_two_households')
    for name in ('migrate', 'check', 'rollback73', 'partial', 'restore75'):
        item = stages[name]
        need(item.get('verified') is True and item.get('households') == 2 and item.get('databases') == 3,
             'migration_group_not_verified')
    need(re.fullmatch('[0-9a-f]{64}', stages['migrate'].get('logicalSha256', '')) and
         stages['check']['logicalSha256'] == stages['migrate']['logicalSha256'] and
         all(stages[n].get('completeGroupRestored') is True for n in ('rollback73', 'partial', 'restore75')) and
         stages['partial'].get('replayRejected') is True and
         sorted(stages['partial']['partialTableCounts'].values()) == [73, 75], 'migration_recovery_incomplete')
    need(stages['startup'].get('initialized') is True and stages['restart'].get('initialized') is True,
         'real_app_startup_missing')
    need(stages['populate75'].get('populated') is True and
         stages['populate75'].get('rowsPerNewTable') == POPULATED_ROWS,
         'nonempty_current_restore_missing')
    need(result.get('commands') and all(c.get('exitCode') == 0 for c in result['commands']), 'migration_command_failed')
    return {'operatorHead': inputs['sourceHead'], 'runtimeSourceHead': inputs['runtimeSourceHead'],
            'candidateSourceHead': meta['sourceHead'], 'runtimeBytesEquivalent': True,
            'imageId': built['imageId'], 'migrationClosure': {n: sources[n] for n in sorted(MIGRATION_CLOSURE | {tool})},
            'runFiles': shared.previous.file_map(root), 'inputFiles': shared.previous.file_map(iroot)}


def verify_selection(selection, metadata):
    need(len(selection['nodeids']) == 46 and selection['allowedSkips'] == {} and
         sha(package.package.encoded(sorted(selection['nodeids']))) == REQUIRED_NODEIDS_SHA256 and
         set(selection['modules']) == set(TEST_MODULES) and
         all(metadata['sourceFiles'].get(n) == h for n, h in TEST_MODULES.items()),
         'journey_finance_exact_selection_required')


def verify_evidence(inputs):
    value, built, verified = shared.verify_evidence(inputs, mode=MODE)
    selection = read(regular(inputs['selection']['path']), inputs['selection']['sha256'])
    verify_selection(selection, value['metadata'])
    return value, built, verified


if __name__ == '__main__': shared.main(mode=MODE)
