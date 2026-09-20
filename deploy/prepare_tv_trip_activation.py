"""Prepare a fixed 75-to-77 TV-trip migration using the existing stopped backup flow."""
from pathlib import Path
import re
import hashlib
import json
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy import build_tv_trip_release as package
from deploy import prepare_assistant_list_activation as parent
from deploy import prepare_local_photo_activation as shared
from deploy.media_video_release_package import read_archive
from deploy.membership_release_controller import need, regular, read, sha

MODE = 'tv-trip-75-to-77'
KIND = 'tv-trip-five-service-migration-v1'
PARENT_SOURCE, PARENT_MANIFEST = package.INSTALLED_SOURCE, package.OLD_MANIFEST
PARENT_PLAN_SHA256 = '89c99949c18204fef03de42b3c1c0fc718cadad9a3404e9900d3c123d89ff0e8'
PARENT_BUILD_SHA256 = 'cd9dc600d2c72ff77731bedeeefade0fc7716257ce0e432bd31845cb12927c92'
OPERATORS = sorted(set(parent.OPERATORS) | {
    'deploy/build_tv_trip_release.py', 'deploy/prepare_tv_trip_activation.py',
    'deploy/activate_tv_trip_release.py', 'deploy/check_tv_trip_migration.py', 'deploy/tv_trip_release_data.py'})
REVIEW_ROLES = shared.REVIEW_ROLES | {'migration'}
INPUT_ROLES = {'package', 'build', 'validation', 'selection', 'parentAudit', 'retainedAssistantList', 'migrationRehearsal', 'reviews'}
# Exact collected selection; fixture dependencies are pinned separately from executed nodes.
TEST_MODULES = {'tests/test_media_trip_playback.py': 'dd35d418661675f36683d3cf6f7e7b23faf6262d27b4203af50ce9c781ea223a', 'tests/test_media_trip_playback_sessions.py': 'e1889212ce4d39991294f78f7ccca521f05ac881f1994c7aaebcd311ee6c88d9', 'tests/test_media_playback.py': '4d0c0ac7b11a4c51c5dc0ebc940884876d77c778fce2299a1383d9b479191559', 'tests/test_tv_trip_capacity.py': '13674de3e143a860496e406c35b4ff9a2289ffefc8b9499ed51a7d666e702501'}
FIXTURE_MODULES = {'tests/test_app.py': 'c1990dfff2fe13aa26a24ce905e06303cab0411155ad806f15a53239abb0690e', 'tests/test_device_sessions.py': '082d4fe6dc3a29e6b8b36556a7501ea6166dac550ff9313dcec81f762c0e625a', 'tests/test_google_photos_picker.py': 'b4df91dd11dfd9996d5b28370a59e1c00804f83bbd2c306df2f184b31fb958e8', 'tests/test_household_media.py': 'eda3f97d185f7ddae0c4315f99cf82a1abfebee234be1037925e88f0c973e781', 'tests/test_household_spaces.py': '378110afadca3bc2dd4b1c9fd77c1ce9c2f75f57fe44ba664dde8846c386a0fc', 'tests/test_journey_documents.py': '62dcb646b57b519f4e8055e4aea1c6f6e534894ad9a5833ae147d55411b9fff5', 'tests/test_journey_places.py': '36173296c3859e31be5ebf40535b959a1b2d319c70ca96983b570f9ed55028f8', 'tests/test_journey_routes.py': 'f9d4b9cf96cd17fbffb4a60c6094de74fb51a8a79fdde092593384313f343e99', 'tests/test_media_video_integration.py': 'fa5b30efaa5a0f196209c23627c445fcf16d5daa568633802641f6a2732473bf', 'tests/test_media_video_tv.py': 'b3ff05cd37bee702ef98d6f844c5ad925be44d314a4f2f68b456db6ae7ac906c'}
REQUIRED_NODEIDS_SHA256 = 'e497a538fe04cd4438bfeff75c5e1fdbf9e05a572dab008448ed308326bdebe6'


MIGRATION_STAGES = {'verify', 'seed', 'migrate', 'startup', 'check', 'rollback75',
                    'partial', 'populate77', 'restart', 'restore77'}
MIGRATION_RUNTIME_SOURCE = 'add881ed6a7d455e2743ce2affa6cf8b931b47d2'
MIGRATION_CLOSURE = {
    'media_trip_playback.py', 'journey_finance.py', 'finance_hub.py', 'financial_files.py',
    'finance_source_bridge.py', 'finance_baseline.py',
    'deploy/check_tv_trip_migration.py', 'deploy/tv_trip_release_data.py',
    'deploy/check_journey_finance_migration.py', 'deploy/journey_finance_release_data.py',
    'deploy/check_media_video_migration.py', 'deploy/media_video_release_data.py',
    'deploy/assistant_trip_change_release_data.py', 'deploy/membership_release_data.py',
    'deploy/membership_migration.py'}
POPULATED_ROWS = {'media_playback_journeys': 2, 'media_playback_operations': 3}


def plan_images(plan): return shared.plan_images(plan, mode=MODE)
def check_plan(plan): return shared.check_plan(plan, mode=MODE)
def prepare(inputs_file, env_sha256, output):
    return shared.prepare(inputs_file, env_sha256, output, mode=MODE)


def runtime_boundary(old, current):
    old, current = ({n: h for n, h in m.items() if not n.startswith('static/experience/')}
                    for m in (old, current))
    kept = {n: h for n, h in current.items() if n not in package.CHANGED_RUNTIME_FILES}
    need(len(current) == package.NON_EXPO_RUNTIME_COUNT and len(old) == 113 and
         len(kept) == package.PRESERVED_RUNTIME_COUNT and
         sha(package.package.encoded(kept)) == package.PRESERVED_RUNTIME_SHA256 and
         all(current.get(n) == h for n, h in package.CHANGED_MODULES.items()) and
         old == {**kept, **package.PARENT_MODULES} and
         sha(package.package.encoded(old)) == package.PARENT_RUNTIME_SHA256,
         'retained_tv_trip_runtime_boundary_changed')


def resource_evidence(inputs, value, built):
    # Read retained evidence as data, never execute the historical operator or plan.
    spec = inputs.get('retainedAssistantList')
    need(isinstance(spec, dict) and set(spec) == {'package', 'build', 'plan'} and
         spec['package'].get('sha256') == package.OLD_PACKAGE and
         spec['build'].get('sha256') == PARENT_BUILD_SHA256 and
         set(spec['plan']) == {'path', 'sha256'} and
         spec['plan'].get('sha256') == PARENT_PLAN_SHA256 and
         Path(spec['plan']['path']).is_absolute(), 'retained_assistant_list_identity_changed')
    proot, metadata = shared.record(spec['package'], 'package.json')
    broot, previous_build = shared.record(spec['build'], 'build.json')
    plan = read(regular(spec['plan']['path']), PARENT_PLAN_SHA256)
    manifest = read(proot/'release-manifest.json', package.OLD_MANIFEST)
    need(shared.previous.file_map(proot) == plan['verifiedEvidence']['package'] and
         shared.previous.file_map(broot) == plan['verifiedEvidence']['build'] and
         sha(regular(proot/'release.tar.gz').read_bytes()) == metadata['archiveSha256'] and
         sha(regular(proot/'build-evidence.json').read_bytes()) == metadata['buildEvidenceSha256'],
         'retained_assistant_list_originals_changed')
    blobs = read_archive(package.package.plain(proot/'release.tar.gz', package.package.MAX_TOTAL))
    need(blobs.pop('RELEASE-MANIFEST.json') == regular(proot/'release-manifest.json').read_bytes() and
         {n: sha(raw) for n, raw in blobs.items()} == manifest['files'], 'retained_assistant_list_archive_changed')
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
         'retained_assistant_list_build_changed')
    runtime_boundary(metadata['runtimeFiles'], value['metadata']['runtimeFiles'])
    return {'retainedAssistantList': {
        'scope': 'unchanged-decoding-import-only; excludes-modified-playback-new-TV-load-and-production-restore',
        'parentSource': package.INSTALLED_SOURCE, 'parentImage': package.PARENT_IMAGE,
        'preservedRuntimeCount': package.PRESERVED_RUNTIME_COUNT,
        'preservedRuntimeSha256': package.PRESERVED_RUNTIME_SHA256,
        'package': shared.previous.file_map(proot), 'build': shared.previous.file_map(broot),
        'plan': PARENT_PLAN_SHA256},
        'migrationRehearsal': verify_migration(inputs['migrationRehearsal'], value, built),
        'tvTripCapacity': verify_capacity(inputs['validation'], value, built)}


def verify_migration(spec, value, built):
    need(isinstance(spec, dict) and set(spec) == {'input', 'run'}, 'migration_descriptor')
    iroot, inputs = shared.record(spec['input'], 'input.json')
    root, result = shared.record(spec['run'], 'result.json')
    meta = value['metadata']
    modules = {n: h for n, h in meta['runtimeFiles'].items() if '/' not in n}
    need(inputs.get('kind') == 'tv-trip-migration-linux-input-v1' and
         inputs.get('historicalHead') == PARENT_SOURCE and inputs.get('productionOperations') is False and
         re.fullmatch('[0-9a-f]{40}', inputs.get('sourceHead', '')) and
         re.fullmatch('[0-9a-f]{40}', inputs.get('tree', '')) and
         inputs.get('runtimeSourceHead') == MIGRATION_RUNTIME_SOURCE and
         inputs.get('runtimeFiles') == modules, 'migration_runtime_differs')
    shared.previous.hashes_at(iroot, inputs['files'])
    sources = inputs.get('sourceFiles', {})
    tool = 'deploy/tv_trip_migration_linux_probe.py'
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
    for name in ('migrate', 'check', 'rollback75', 'partial', 'restore77'):
        item = stages[name]
        need(item.get('verified') is True and item.get('households') == 2 and item.get('databases') == 3,
             'migration_group_not_verified')
    need(re.fullmatch('[0-9a-f]{64}', stages['migrate'].get('logicalSha256', '')) and
         stages['check']['logicalSha256'] == stages['migrate']['logicalSha256'] and
         all(stages[n].get('completeGroupRestored') is True for n in ('rollback75', 'partial', 'restore77')) and
         stages['partial'].get('replayRejected') is True and
         sorted(stages['partial']['partialTableCounts'].values()) == [75, 77], 'migration_recovery_incomplete')
    need(stages['startup'].get('initialized') is True and stages['restart'].get('initialized') is True,
         'real_app_startup_missing')
    need(stages['populate77'].get('populated') is True and
         stages['populate77'].get('rowsPerNewTable') == POPULATED_ROWS,
         'nonempty_current_restore_missing')
    need(result.get('commands') and all(c.get('exitCode') == 0 for c in result['commands']), 'migration_command_failed')
    return {'operatorHead': inputs['sourceHead'], 'runtimeSourceHead': inputs['runtimeSourceHead'],
            'candidateSourceHead': meta['sourceHead'], 'runtimeBytesEquivalent': True,
            'imageId': built['imageId'], 'migrationClosure': {n: sources[n] for n in sorted(MIGRATION_CLOSURE | {tool})},
            'runFiles': shared.previous.file_map(root), 'inputFiles': shared.previous.file_map(iroot)}


def verify_capacity(spec, value, built):
    root, validation = shared.record(spec, 'validation.json')
    name = 'proof/tv-trip-capacity.json'
    meta = value['metadata']
    need(validation.get('imageId') == built['imageId'] and
         validation.get('sourceHead') == meta['sourceHead'] and
         validation.get('tree') == meta['tree'] and validation.get('allPassed') is True and
         validation.get('containerExitCode') == 0 and name in validation.get('evidence', {}),
         'tv_trip_capacity_missing')
    proof = read(regular(root/name), validation['evidence'][name])
    need(proof.get('kind') == 'tv-trip-capacity-v1' and proof.get('passed') is True and
         proof.get('linux') is True and proof.get('failure') is None and
         proof.get('fixture') == {'media': 2000, 'sharedStops': 100, 'televisions': 2,
             'creation': 'one-real-photo-confirmation-then-synthetic-encrypted-storage-fill'} and
         proof.get('bookkeepingNormalization') == ['member_sessions.last_seen_at'] and
         proof.get('deniedBlobReads') == [] and type(proof.get('scanCount')) is int and proof['scanCount'] >= 4 and
         isinstance(proof.get('databaseBefore'), dict) and bool(proof['databaseBefore']) and
         proof['databaseBefore'] == proof.get('databaseAfter') and
         all(re.fullmatch('[0-9a-f]{64}', h) for h in proof['databaseBefore'].values()),
         'tv_trip_capacity_incomplete')
    requests = proof.get('requests', [])
    need(len(requests) == 4 and all(r.get('status') == 200 and type(r.get('bytes')) is int and
         0 < r['bytes'] <= 512*1024 and isinstance(r.get('started'), (int, float)) and
         isinstance(r.get('finished'), (int, float)) and r['finished'] > r['started'] and
         re.fullmatch('[0-9a-f]{64}', r.get('bodySha256', '')) for r in requests), 'tv_trip_requests_incomplete')
    tv = [r for r in requests if r.get('method') == 'GET' and r.get('path') == '/api/media-tv/playback']
    member = [r for r in requests if r.get('method') == 'GET' and
              re.fullmatch('/api/media-playback/devices/[0-9a-f]{24}', r.get('path', ''))]
    preview = [r for r in requests if r.get('method') == 'POST' and
               re.fullmatch('/api/media-playback/devices/[0-9a-f]{24}/journey-preview', r.get('path', ''))]
    for item in requests:
        body = item.get('body', {})
        route = body.get('route') if 'route' in body else (body.get('journeyReview') or {}).get('route')
        body_hash = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
        need(item['bodySha256'] == body_hash and body.get('photoCount', body.get('mediaCount')) == 2000 and
             isinstance(route, dict) and len(route.get('stops', [])) == 100 and
             all(s.get('state') == 'available' for s in route['stops']), 'tv_trip_response_projection_changed')
    need(len(tv) == 2 and len({r['body'].get('deviceId') for r in tv}) == 2 and
         all(re.fullmatch('[0-9a-f]{24}', r['body'].get('deviceId', '')) for r in tv) and
         len(member) == len(preview) == 1 and
         member[0]['path'] != preview[0]['path'].removesuffix('/journey-preview') and
         min(r['finished'] for r in requests) - max(r['started'] for r in requests) > 0 and
         proof.get('fourRequestOverlapSeconds') == min(r['finished'] for r in requests)-max(r['started'] for r in requests),
         'tv_trip_concurrent_reads_missing')
    expected = {'media_trip_playback', 'media_playback', 'household_media', 'journey_routes', 'journey_places'}
    need(set(proof.get('loaded', {})) == expected and all(v == {'path': '/app/'+n+'.py',
         'sha256': meta['runtimeFiles'][n+'.py']} for n, v in proof['loaded'].items()),
         'tv_trip_capacity_runtime_changed')
    for name in ('cgroupBefore', 'cgroupAfter', 'cgroupFinal'):
        observed = proof.get(name, {})
        need(int(observed.get('memory.max', 0)) == 384*1024**2 and observed.get('memory.swap.max') == '0' and
             0 < int(observed.get('memory.peak', 0)) <= 384*1024**2, 'tv_trip_capacity_limit_changed')
        events = dict(line.split() for line in observed.get('memory.events', '').splitlines())
        need(all(events.get(k) == '0' for k in ('max', 'oom', 'oom_kill')) and
             events.get('oom_group_kill', '0') == '0', 'tv_trip_capacity_limit_event')
    need(type(proof.get('processPeakRssBytes')) is int and 0 < proof['processPeakRssBytes'] <= 384*1024**2,
         'tv_trip_process_peak_missing')
    return {'scope': 'four-Flask-WSGI-reads-only; no-Gunicorn-Nginx-throughput-or-decoder-load-claim',
            'candidateSourceHead': meta['sourceHead'], 'imageId': built['imageId'],
            'validationSha256': spec['sha256'], 'proofSha256': validation['evidence']['proof/tv-trip-capacity.json'],
            'memoryLimitBytes': 384*1024**2, 'cgroupPeakBytes': int(proof['cgroupFinal']['memory.peak'])}


def verify_selection(selection, metadata):
    need(len(selection['nodeids']) == 94 and TEST_MODULES and REQUIRED_NODEIDS_SHA256 and selection['allowedSkips'] == {} and
         sha(package.package.encoded(sorted(selection['nodeids']))) == REQUIRED_NODEIDS_SHA256 and
         set(selection['modules']) == set(TEST_MODULES) and
         all(metadata['sourceFiles'].get(n) == h for n, h in {**TEST_MODULES, **FIXTURE_MODULES}.items()),
         'tv_trip_exact_selection_required')


def verify_evidence(inputs):
    value, built, verified = shared.verify_evidence(inputs, mode=MODE)
    selection = read(regular(inputs['selection']['path']), inputs['selection']['sha256'])
    verify_selection(selection, value['metadata'])
    return value, built, verified


if __name__ == '__main__':
    shared.main(mode=MODE)
