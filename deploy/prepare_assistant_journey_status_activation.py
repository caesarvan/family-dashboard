"""Prepare a fixed 77-to-77 assistant journey-status update using the existing stopped backup flow."""
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy import build_assistant_journey_status_release as package
from deploy import prepare_tv_trip_activation as parent
from deploy import prepare_local_photo_activation as shared
from deploy.media_video_release_package import read_archive
from deploy.membership_release_controller import need, regular, read, sha

MODE = 'assistant-journey-status-source-update'
KIND = 'assistant-journey-status-five-service-source-update-v1'
PARENT_SOURCE, PARENT_MANIFEST = package.INSTALLED_SOURCE, package.OLD_MANIFEST
PARENT_PLAN_SHA256 = '9b0c1f83668338810f981928418fdadf70e58e05e21161647f29ad62be3502a0'
PARENT_BUILD_SHA256 = '6dea9834cdce1288c75dcf682b9a47df88296f3dc1c1a8e0a562fdfed519fd96'
OPERATORS = sorted(set(parent.OPERATORS) | {
    'deploy/build_assistant_journey_status_release.py', 'deploy/prepare_assistant_journey_status_activation.py',
    'deploy/activate_assistant_journey_status_release.py'})
REVIEW_ROLES = shared.REVIEW_ROLES
INPUT_ROLES = {'package', 'build', 'validation', 'selection', 'parentAudit', 'retainedTvTrip', 'reviews'}
# Exact candidate selection; source and test hashes are independently reviewed before release.
TEST_MODULES = {'tests/test_assistant_journey_status.py': '5ff17a16a33e020beafb1c2bd1268acee1f08d658ba42c75173d4b8f45588fae', 'tests/test_journey_workflows.py': 'e0feb9196557222adc25460f26b138f11d45e0e29da6fb00428436f219fea0e2'}
FIXTURE_MODULES = {'tests/test_app.py': 'c1990dfff2fe13aa26a24ce905e06303cab0411155ad806f15a53239abb0690e', 'tests/test_household_spaces.py': '378110afadca3bc2dd4b1c9fd77c1ce9c2f75f57fe44ba664dde8846c386a0fc'}
REQUIRED_NODEIDS_SHA256 = 'b817634ac9e356a981269085557c4017640518c91ac52a1d0425132b5c2b568e'



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
         'retained_assistant_journey_status_runtime_boundary_changed')


def resource_evidence(inputs, value, built):
    # Read retained evidence as data, never execute the historical operator or plan.
    spec = inputs.get('retainedTvTrip')
    need(isinstance(spec, dict) and set(spec) == {'package', 'build', 'plan'} and
         spec['package'].get('sha256') == package.OLD_PACKAGE and
         spec['build'].get('sha256') == PARENT_BUILD_SHA256 and
         set(spec['plan']) == {'path', 'sha256'} and
         spec['plan'].get('sha256') == PARENT_PLAN_SHA256 and
         Path(spec['plan']['path']).is_absolute(), 'retained_tv_trip_identity_changed')
    proot, metadata = shared.record(spec['package'], 'package.json')
    broot, previous_build = shared.record(spec['build'], 'build.json')
    plan = read(regular(spec['plan']['path']), PARENT_PLAN_SHA256)
    manifest = read(proot/'release-manifest.json', package.OLD_MANIFEST)
    need(shared.previous.file_map(proot) == plan['verifiedEvidence']['package'] and
         shared.previous.file_map(broot) == plan['verifiedEvidence']['build'] and
         sha(regular(proot/'release.tar.gz').read_bytes()) == metadata['archiveSha256'] and
         sha(regular(proot/'build-evidence.json').read_bytes()) == metadata['buildEvidenceSha256'],
         'retained_tv_trip_originals_changed')
    blobs = read_archive(package.package.plain(proot/'release.tar.gz', package.package.MAX_TOTAL))
    need(blobs.pop('RELEASE-MANIFEST.json') == regular(proot/'release-manifest.json').read_bytes() and
         {n: sha(raw) for n, raw in blobs.items()} == manifest['files'], 'retained_tv_trip_archive_changed')
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
         plan['images']['decoder'] == package.DECODER_IMAGE and plan['schemaAfter'] == [77, 9],
         'retained_tv_trip_build_changed')
    runtime_boundary(metadata['runtimeFiles'], value['metadata']['runtimeFiles'])
    return {'retainedTvTrip': {
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
         all(metadata['sourceFiles'].get(n) == h for n, h in {**TEST_MODULES, **FIXTURE_MODULES}.items()),
         'assistant_journey_status_exact_selection_required')


def verify_evidence(inputs):
    value, built, verified = shared.verify_evidence(inputs, mode=MODE)
    selection = read(regular(inputs['selection']['path']), inputs['selection']['sha256'])
    verify_selection(selection, value['metadata'])
    return value, built, verified


if __name__ == '__main__':
    shared.main(mode=MODE)
