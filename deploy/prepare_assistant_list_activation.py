"""Prepare a fixed 75-to-75 assistant-list update using the existing stopped backup flow."""
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy import build_assistant_list_release as package
from deploy import prepare_media_date_activation as parent
from deploy import prepare_local_photo_activation as shared
from deploy.media_video_release_package import read_archive
from deploy.membership_release_controller import need, regular, read, sha

MODE = 'assistant-list-source-update'
KIND = 'assistant-list-five-service-source-update-v1'
PARENT_SOURCE, PARENT_MANIFEST = package.INSTALLED_SOURCE, package.OLD_MANIFEST
PARENT_PLAN_SHA256 = 'f28fd2fb6527c5f02be726dbd742e1a2af6080a426a59cd240d41b437f4bb403'
PARENT_BUILD_SHA256 = '65427ed50f0878a9ea395ae84d08e2f8b8ea6af5697c6b3022468f28853046be'
OPERATORS = sorted(set(parent.OPERATORS) | {
    'deploy/build_assistant_list_release.py', 'deploy/prepare_assistant_list_activation.py',
    'deploy/activate_assistant_list_release.py'})
REVIEW_ROLES = shared.REVIEW_ROLES
INPUT_ROLES = {'package', 'build', 'validation', 'selection', 'parentAudit', 'retainedMediaDate', 'reviews'}
# Exact candidate selection; source and test hashes are independently reviewed before release.
TEST_MODULES = {'tests/test_assistant_list_editing.py': 'f6feb12ac448fc8198dba3fb82ebc65da2c44d49f5bd22cd3bfc1f93c42a7e02', 'tests/test_assistant_source_search.py': '889132bdc6ea5da3d65b3f99d13f4500be0b58a0733d5c8251c688925b23b48c', 'tests/test_home_assistant.py': '517cffded68ac80be313d41408336068f85f9f07f57b4b8d56bffb275ad5e32f'}
REQUIRED_NODEIDS_SHA256 = '05e4cdef8c0da63c52772d512cfa1a2211682d123a38a71a191161cba7d1cf00'


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
         'retained_assistant_list_runtime_boundary_changed')


def resource_evidence(inputs, value, built):
    # Read retained evidence as data, never execute the historical operator or plan.
    spec = inputs.get('retainedMediaDate')
    need(isinstance(spec, dict) and set(spec) == {'package', 'build', 'plan'} and
         spec['package'].get('sha256') == package.OLD_PACKAGE and
         spec['build'].get('sha256') == PARENT_BUILD_SHA256 and
         set(spec['plan']) == {'path', 'sha256'} and
         spec['plan'].get('sha256') == PARENT_PLAN_SHA256 and
         Path(spec['plan']['path']).is_absolute(), 'retained_media_date_identity_changed')
    proot, metadata = shared.record(spec['package'], 'package.json')
    broot, previous_build = shared.record(spec['build'], 'build.json')
    plan = read(regular(spec['plan']['path']), PARENT_PLAN_SHA256)
    manifest = read(proot/'release-manifest.json', package.OLD_MANIFEST)
    need(shared.previous.file_map(proot) == plan['verifiedEvidence']['package'] and
         shared.previous.file_map(broot) == plan['verifiedEvidence']['build'] and
         sha(regular(proot/'release.tar.gz').read_bytes()) == metadata['archiveSha256'] and
         sha(regular(proot/'build-evidence.json').read_bytes()) == metadata['buildEvidenceSha256'],
         'retained_media_date_originals_changed')
    blobs = read_archive(package.package.plain(proot/'release.tar.gz', package.package.MAX_TOTAL))
    need(blobs.pop('RELEASE-MANIFEST.json') == regular(proot/'release-manifest.json').read_bytes() and
         {n: sha(raw) for n, raw in blobs.items()} == manifest['files'], 'retained_media_date_archive_changed')
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
         'retained_media_date_build_changed')
    runtime_boundary(metadata['runtimeFiles'], value['metadata']['runtimeFiles'])
    return {'retainedMediaDate': {
        'scope': 'unchanged-media-runtime-only; no-new-assistant-load-or-production-restore-claim',
        'parentSource': package.INSTALLED_SOURCE, 'parentImage': package.PARENT_IMAGE,
        'preservedRuntimeCount': package.PRESERVED_RUNTIME_COUNT,
        'preservedRuntimeSha256': package.PRESERVED_RUNTIME_SHA256,
        'package': shared.previous.file_map(proot), 'build': shared.previous.file_map(broot),
        'plan': PARENT_PLAN_SHA256}}


def verify_selection(selection, metadata):
    need(TEST_MODULES and REQUIRED_NODEIDS_SHA256 and selection['allowedSkips'] == {} and
         sha(package.package.encoded(sorted(selection['nodeids']))) == REQUIRED_NODEIDS_SHA256 and
         set(selection['modules']) == set(TEST_MODULES) and
         all(metadata['sourceFiles'].get(n) == h for n, h in TEST_MODULES.items()),
         'assistant_list_exact_selection_required')


def verify_evidence(inputs):
    value, built, verified = shared.verify_evidence(inputs, mode=MODE)
    selection = read(regular(inputs['selection']['path']), inputs['selection']['sha256'])
    verify_selection(selection, value['metadata'])
    return value, built, verified


if __name__ == '__main__':
    shared.main(mode=MODE)
