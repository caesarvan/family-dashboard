"""Prepare a fixed 75-to-75 photo-date update using the existing stopped backup flow."""
import ast
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy import build_media_date_release as package
from deploy import prepare_journey_finance_activation as parent
from deploy import prepare_local_photo_activation as shared
from deploy.media_video_release_package import read_archive
from deploy.membership_release_controller import need, regular, read, sha

MODE = 'media-date-source-update'
KIND = 'media-date-five-service-source-update-v1'
PARENT_SOURCE, PARENT_MANIFEST = package.INSTALLED_SOURCE, package.OLD_MANIFEST
PARENT_PLAN_SHA256 = '33e59a0988dcd1d84eac50c30c7ef4eac507f8645df046ca7a949f4620b000ca'
PARENT_BUILD_SHA256 = '8842ca3125888f2724b210cd301ac05ca047fce732183526d5385b3d0f2fbb15'
OPERATORS = sorted(set(parent.OPERATORS) | {
    'deploy/build_media_date_release.py', 'deploy/prepare_media_date_activation.py',
    'deploy/activate_media_date_release.py'})
REVIEW_ROLES = shared.REVIEW_ROLES
INPUT_ROLES = {'package', 'build', 'validation', 'selection', 'parentAudit', 'retainedJourney', 'reviews'}
TEST_MODULES = {
    'tests/test_household_media.py': 'eda3f97d185f7ddae0c4315f99cf82a1abfebee234be1037925e88f0c973e781',
    'tests/test_local_photo_import.py': '0915c9358a792a3938289aa0b63d6af87b548a03421930cdc6bfab21cf105dac',
    'tests/test_media_confirmed_date.py': '7d72426d9e249da73f68903ead15f1eda4b4881e4f36c7f9ff909ab16af0e433',
    'tests/test_media_journey_suggestions.py': '8e6df9e3be7c3f07c25be16237e2076d10b81f70d7ce7c7a272e48f5fc5277c2',
    'tests/test_media_memories.py': 'b143a44ac4870e6616ebf1259fc9114c9c9167187bf87b3c86b8f04231903117',
    'tests/test_media_portability.py': '65259ace1e6abd3510488c2378bfb99fe5956291e506295d8f0da6caf5d6f2a3'}
REQUIRED_NODEIDS_SHA256 = 'a7f377bda7becae23544c692edf1f8a5e55fb4a04c274031d95fb6852db7f327'


def plan_images(plan): return shared.plan_images(plan, mode=MODE)
def check_plan(plan): return shared.check_plan(plan, mode=MODE)
def prepare(inputs_file, env_sha256, output):
    return shared.prepare(inputs_file, env_sha256, output, mode=MODE)


def runtime_boundary(old, current):
    old, current = ({n: h for n, h in m.items() if not n.startswith('static/experience/')}
                    for m in (old, current))
    kept = {n: h for n, h in current.items() if n not in package.CHANGED_RUNTIME_FILES}
    need(len(current) == len(old) == package.NON_EXPO_RUNTIME_COUNT and
         len(kept) == package.PRESERVED_RUNTIME_COUNT and
         sha(package.package.encoded(kept)) == package.PRESERVED_RUNTIME_SHA256 and
         all(current.get(n) == h for n, h in package.CHANGED_MODULES.items()) and
         old == {**kept, **package.PARENT_MODULES} and
         sha(package.package.encoded(old)) == package.PARENT_RUNTIME_SHA256,
         'retained_media_date_runtime_boundary_changed')


def unchanged_media_processing(before, after):
    """Compare media processing entry points; date/DTO queries are outside this claim."""
    need(sha(before) == package.PARENT_MODULES['household_media.py'] and
         sha(after) == package.CHANGED_MODULES['household_media.py'], 'media_date_module_changed')
    def definitions(raw):
        tree = ast.parse(raw)
        engine = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MediaLibrary')
        return {n.name: ast.dump(n, include_attributes=False) for n in engine.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    old, new = definitions(before), definitions(after)
    processing = {
        'transaction', '_seal', '_open', '_quota', '_authority', '_import_source', '_media_authority',
        '_context_valid', '_import', '_manifest', '_result_summary', '_terminal_receipt', '_import_dto',
        'create_import', '_delete_item', '_terminate', 'maintenance', 'on_account_removed',
        'on_account_authority_changed', 'claim_next', '_job', 'validate_job', '_session',
        '_finish_staging', 'complete', 'fail', '_metadata', '_item', 'confirm_import', 'cancel_import',
        'delete_item', 'tv_grants', '_tv', 'preview', '_video_identity', 'video'}
    need(processing <= old.keys() and all(old[n] == new.get(n) for n in processing),
         'retained_media_processing_changed')
    return sorted(processing)


def resource_evidence(inputs, value, built):
    # Read retained evidence as data, never execute the historical operator or plan.
    spec = inputs.get('retainedJourney')
    need(isinstance(spec, dict) and set(spec) == {'package', 'build', 'plan'} and
         spec['package'].get('sha256') == package.OLD_PACKAGE and
         spec['build'].get('sha256') == PARENT_BUILD_SHA256 and
         set(spec['plan']) == {'path', 'sha256'} and
         spec['plan'].get('sha256') == PARENT_PLAN_SHA256 and
         Path(spec['plan']['path']).is_absolute(), 'retained_journey_identity_changed')
    proot, metadata = shared.record(spec['package'], 'package.json')
    broot, previous_build = shared.record(spec['build'], 'build.json')
    plan = read(regular(spec['plan']['path']), PARENT_PLAN_SHA256)
    manifest = read(proot/'release-manifest.json', package.OLD_MANIFEST)
    need(shared.previous.file_map(proot) == plan['verifiedEvidence']['package'] and
         shared.previous.file_map(broot) == plan['verifiedEvidence']['build'] and
         sha(regular(proot/'release.tar.gz').read_bytes()) == metadata['archiveSha256'] and
         sha(regular(proot/'build-evidence.json').read_bytes()) == metadata['buildEvidenceSha256'],
         'retained_journey_originals_changed')
    blobs = read_archive(package.package.plain(proot/'release.tar.gz', package.package.MAX_TOTAL))
    need(blobs.pop('RELEASE-MANIFEST.json') == regular(proot/'release-manifest.json').read_bytes() and
         {n: sha(raw) for n, raw in blobs.items()} == manifest['files'], 'retained_journey_archive_changed')
    package.package.validate_maps(metadata, manifest, read(proot/'build-evidence.json'), baseline=package.parent.BASELINE)
    need(metadata['sourceHead'] == manifest['sourceHead'] == package.INSTALLED_SOURCE and
         metadata['tree'] == manifest['tree'] == package.INSTALLED_TREE and
         previous_build.get('exitCode') == 0 and previous_build.get('productionOperations') is False and
         previous_build.get('sourceHead') == package.INSTALLED_SOURCE and
         previous_build.get('tree') == package.INSTALLED_TREE and
         previous_build.get('packageSha256') == package.OLD_PACKAGE and
         previous_build.get('manifestSha256') == package.OLD_MANIFEST and
         previous_build.get('imageId') == plan['images']['app'] == package.PARENT_IMAGE and
         previous_build.get('runtimeHashes') == metadata['runtimeFiles'] and
         plan['images']['decoder'] == package.DECODER_IMAGE and plan['schemaAfter'] == [75, 9],
         'retained_journey_build_changed')
    runtime_boundary(metadata['runtimeFiles'], value['metadata']['runtimeFiles'])
    methods = unchanged_media_processing(blobs['household_media.py'], value['blobs']['household_media.py'])
    return {'retainedJourney': {
        'scope': 'unchanged-media-processing-only; no-new-date-query-load-or-production-restore-claim',
        'parentSource': package.INSTALLED_SOURCE, 'parentImage': package.PARENT_IMAGE,
        'preservedRuntimeCount': package.PRESERVED_RUNTIME_COUNT,
        'preservedRuntimeSha256': package.PRESERVED_RUNTIME_SHA256,
        'unchangedMediaMethods': methods,
        'package': shared.previous.file_map(proot), 'build': shared.previous.file_map(broot),
        'plan': PARENT_PLAN_SHA256}}


def verify_selection(selection, metadata):
    need(TEST_MODULES and REQUIRED_NODEIDS_SHA256 and selection['allowedSkips'] == {} and
         sha(package.package.encoded(sorted(selection['nodeids']))) == REQUIRED_NODEIDS_SHA256 and
         set(selection['modules']) == set(TEST_MODULES) and
         all(metadata['sourceFiles'].get(n) == h for n, h in TEST_MODULES.items()),
         'media_date_exact_selection_required')


def verify_evidence(inputs):
    value, built, verified = shared.verify_evidence(inputs, mode=MODE)
    selection = read(regular(inputs['selection']['path']), inputs['selection']['sha256'])
    verify_selection(selection, value['metadata'])
    return value, built, verified


if __name__ == '__main__':
    shared.main(mode=MODE)
