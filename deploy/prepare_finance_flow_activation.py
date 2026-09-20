"""Fixed finance admission; retained media evidence is not a finance load test."""
import ast
from pathlib import Path
import sys
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy import build_finance_flow_release as package
from deploy import prepare_local_photo_activation as shared
from deploy import prepare_discovery_activation as discovery
from deploy.media_video_release_package import read_archive
from deploy.membership_release_controller import need, regular, read, sha, encoded

MODE = 'finance-flow-source-update'
KIND = 'finance-flow-five-service-source-update-v1'
PARENT_SOURCE, PARENT_MANIFEST = package.INSTALLED_SOURCE, package.OLD_MANIFEST
OPERATORS = sorted(set(discovery.OPERATORS) | {
    'deploy/build_finance_flow_release.py', 'deploy/prepare_finance_flow_activation.py',
    'deploy/activate_finance_flow_release.py'})
REVIEW_ROLES = shared.REVIEW_ROLES
PARENT_PLAN_SHA256 = '542b77bd046f3cc853cb6ca3b70234464142a688611c0bf5c2f1a6782498bbd2'
PARENT_BUILD_SHA256 = '18caab501faa2f695290c0489e984fba168ca44478aadebfbece4bd02014552f'
# Filled from the original 33-node author JUnit selection, not a future test run.
REQUIRED_NODEIDS_SHA256 = '51ecf844ed7c4f4cc4131095b229f8645a4c1e9ae5885b34054078b589ac6609'
TEST_MODULES = {
    'tests/test_finance_column_mapping.py': '99bee29eddd8329821e388a20aff081a396573547c85e37ef9b4d04b206e9c05',
    'tests/test_finance_flow_mapping.py': '90080beee47c8d32c6c8eac65835cea2c7b7c9c2d97ce830a8a0e55e7c3a7f26',
    'tests/test_finance_hub.py': '541e343e24e1b505e4300f187cbe76881b5a345e32a54ddf567ecf873b547ba1',
}


def plan_images(plan): return shared.plan_images(plan, mode=MODE)
def check_plan(plan): return shared.check_plan(plan, mode=MODE)
def prepare(**kwargs): return shared.prepare(**kwargs, mode=MODE)


def unchanged_finance_ast(before, after):
    need(sha(before) == package.PARENT_MODULES['finance_hub.py'] and
         sha(after) == package.CHANGED_MODULES['finance_hub.py'], 'finance_resource_pin_changed')
    def outside(raw):
        tree = ast.parse(raw)
        changed = {'_import_conflict', '_column_controls', 'parse_import'}
        need(all(sum(isinstance(n, ast.FunctionDef) and n.name == name for n in tree.body) == 1
                 for name in changed), 'finance_resource_function_shape_changed')
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in changed:
                node.body = [ast.Pass()]
        return ast.dump(tree, include_attributes=False)
    need(outside(before) == outside(after), 'finance_resource_behavior_changed')
    return {'before': sha(before), 'after': sha(after),
            'changedOnlyInside': ['_import_conflict', '_column_controls', 'parse_import']}


def runtime_boundary(old_runtime, current_runtime):
    current = {n: h for n, h in current_runtime.items() if not n.startswith('static/experience/')}
    kept = {n: h for n, h in current.items() if n not in package.CHANGED_MODULES}
    original = {n: h for n, h in old_runtime.items() if not n.startswith('static/experience/')}
    need(len(current) == 112 and len(kept) == 111 and
         sha(package.package.encoded(kept)) == package.PRESERVED_RUNTIME_SHA256 and
         all(current.get(n) == h for n, h in package.CHANGED_MODULES.items()) and
         original == {**kept, **package.PARENT_MODULES} and
         sha(package.package.encoded(original)) == package.PARENT_RUNTIME_SHA256,
         'retained_runtime_boundary_changed')


def resource_descriptors(inputs, plan):
    for profile in ('image_overlap', 'nginx_raw', 'duplicates'):
        need(set(inputs[profile]) == {'input', 'run'} and
             all(inputs[profile][role]['sha256'] == plan['inputs'][profile][role]['sha256']
                 for role in ('input', 'run')), 'retained_resource_receipt_changed')


def retained_parent(inputs, value):
    """Validate the exact old receipts without executing a package-supplied policy.

    The current packager must not impersonate the old package's executing hash.
    Instead, fixed production package/manifest/build/plan digests bind the old
    metadata and archive; the existing resource verifiers still read all originals.
    """
    spec = inputs['retainedDiscovery']
    need(isinstance(spec, dict) and set(spec) == {'package', 'build', 'plan'}, 'retained_discovery_descriptor')
    need(spec['package'].get('sha256') == package.OLD_PACKAGE and
         spec['build'].get('sha256') == PARENT_BUILD_SHA256 and
         set(spec['plan']) == {'path', 'sha256'} and Path(spec['plan']['path']).is_absolute() and
         spec['plan']['sha256'] == PARENT_PLAN_SHA256, 'retained_discovery_identity_changed')
    old_root, meta = shared.record(spec['package'], 'package.json')
    build_root, built = shared.record(spec['build'], 'build.json')
    plan = read(regular(spec['plan']['path']), PARENT_PLAN_SHA256)
    manifest = read(old_root/'release-manifest.json', package.OLD_MANIFEST)
    old_files = shared.previous.file_map(old_root)
    need(old_files == plan['verifiedEvidence']['package'] and
         old_files['release.tar.gz'] == meta['archiveSha256'] and
         old_files['build-evidence.json'] == meta['buildEvidenceSha256'], 'retained_package_originals_changed')
    old_blobs = read_archive(package.package.plain(old_root/'release.tar.gz', package.package.MAX_TOTAL))
    need(old_blobs.pop('RELEASE-MANIFEST.json', None) == regular(old_root/'release-manifest.json').read_bytes()
         and {n: sha(raw) for n, raw in old_blobs.items()} == manifest['files'], 'retained_archive_changed')
    package.package.validate_maps(meta, manifest, read(old_root/'build-evidence.json'), baseline=package.parent.BASELINE)
    build_files = shared.previous.file_map(build_root)
    need(build_files == plan['verifiedEvidence']['build'], 'retained_build_originals_changed')
    need(meta['sourceHead'] == manifest['sourceHead'] == plan['sourceHead'] == package.INSTALLED_SOURCE and
         meta['tree'] == manifest['tree'] == plan['tree'] == package.INSTALLED_TREE and
         meta['manifestSha256'] == package.OLD_MANIFEST and
         plan['inputs']['package']['sha256'] == package.OLD_PACKAGE and
         plan['inputs']['build']['sha256'] == PARENT_BUILD_SHA256 and
         built['imageId'] == plan['images']['app'] == package.PARENT_IMAGE and
         plan['images']['decoder'] == package.DECODER_IMAGE and
         built['packageSha256'] == package.OLD_PACKAGE and built['manifestSha256'] == package.OLD_MANIFEST and
         built['sourceHead'] == meta['sourceHead'] and built['tree'] == meta['tree'] and
         built['runtimeHashes'] == meta['runtimeFiles'] and built['exitCode'] == 0 and
         built['productionOperations'] is False, 'retained_parent_binding_changed')
    runtime_boundary(meta['runtimeFiles'], value['metadata']['runtimeFiles'])
    resource_descriptors(inputs, plan)
    return {'metadata': meta, 'blobs': old_blobs}, built, plan, {
        'package': old_files, 'build': build_files, 'plan': PARENT_PLAN_SHA256}


def resource_evidence(inputs, value, built):
    retained, old_build, plan, original_files = retained_parent(inputs, value)
    # These two modules are byte-identical to the installed discovery version.
    # Only the old map is used to validate the old workload; candidate finance
    # bytes must never be passed off as having run in that experiment.
    proof = {p: discovery.parent_resources(inputs[p], p, retained)
             for p in ('image_overlap', 'nginx_raw')}
    proof['duplicates'] = discovery.duplicate_resources(inputs['duplicates'], retained, old_build,
                                                       package.OLD_PACKAGE, PARENT_BUILD_SHA256)
    need(all(proof[p] == plan['verifiedEvidence'][p] for p in proof), 'retained_resource_result_changed')
    prepared, _ = shared.record(inputs['image_overlap']['input'], 'input.json')
    boundary = unchanged_finance_ast(regular(prepared/'runtime/finance_hub.py').read_bytes(),
                                     value['blobs']['finance_hub.py'])
    return {**proof, 'retainedDiscovery': {**original_files,
        'scope': 'unchanged-media-and-duplicate-metadata-paths-only-not-finance-load',
        'parentSource': package.INSTALLED_SOURCE, 'parentRuntimeSha256': package.PARENT_RUNTIME_SHA256,
        'candidatePreservedFiles': 111, 'financeAstBoundary': boundary}}


def verify_selection(selection, metadata):
    need(selection.get('allowedSkips') == {} and isinstance(selection.get('nodeids'), list) and
         len(selection['nodeids']) == len(set(selection['nodeids'])) == 33 and
         sha(package.package.encoded(sorted(selection['nodeids']))) == REQUIRED_NODEIDS_SHA256,
         'finance_exact33_tests_required')
    need(set(selection['modules']) == set(TEST_MODULES) and
         all(metadata['sourceFiles'].get(n) == h for n, h in TEST_MODULES.items()),
         'finance_test_module_changed')


def verify_evidence(inputs):
    value, built, verified = shared.verify_evidence(inputs, mode=MODE)
    spec = inputs['selection']
    verify_selection(read(spec['path'], spec['sha256']), value['metadata'])
    return value, built, verified


def main(argv=None): return shared.main(argv, mode=MODE)
if __name__ == '__main__': main()
