"""Prepare one fixed local-photo 73/9 source-update plan; no Docker or production reads."""
import argparse
import json
from pathlib import Path
import re
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy import build_local_photo_release as package
from deploy import prepare_media_video_activation as previous
from deploy.membership_release_controller import need, regular, read, put, relative, sha, encoded
from deploy.media_video_service_lifecycle import WEB_IMAGE

PARENT_SOURCE, PARENT_MANIFEST = package.INSTALLED_SOURCE, package.OLD_MANIFEST
KIND = 'local-photo-five-service-source-update-v1'
OPERATORS = sorted(set(previous.OPERATORS) | {
    'deploy/build_local_photo_release.py', 'deploy/prepare_local_photo_activation.py',
    'deploy/activate_local_photo_release.py'})
REVIEW_ROLES = {'source', 'browser', 'release', 'linux', 'resources'}
LIMITS = {'app': 384, 'web': 96, 'client': 64}
HOST_BUDGET = {'preflightMiB': 672, 'preflightSamples': 3, 'preflightIntervalSeconds': 1,
               'abortBelowMiB': 256, 'sampleIntervalSeconds': .25, 'maxSampleLagSeconds': 1}


def _profile(mode=None):
    # Only these source-controlled policies exist. No JSON-selected import.
    need(mode in (None, 'discovery-source-update', 'finance-flow-source-update',
                  'journey-finance-73-to-75', 'media-date-source-update', 'assistant-list-source-update', 'tv-trip-75-to-77', 'assistant-journey-status-source-update'), 'unsupported_source_update_profile')
    if mode == 'assistant-journey-status-source-update':
        from deploy import prepare_assistant_journey_status_activation
        return prepare_assistant_journey_status_activation
    if mode == 'tv-trip-75-to-77':
        from deploy import prepare_tv_trip_activation
        return prepare_tv_trip_activation
    if mode == 'assistant-list-source-update':
        from deploy import prepare_assistant_list_activation
        return prepare_assistant_list_activation
    if mode == 'media-date-source-update':
        from deploy import prepare_media_date_activation
        return prepare_media_date_activation
    if mode == 'journey-finance-73-to-75':
        from deploy import prepare_journey_finance_activation
        return prepare_journey_finance_activation
    if mode == 'finance-flow-source-update':
        from deploy import prepare_finance_flow_activation
        return prepare_finance_flow_activation
    if mode == 'discovery-source-update':
        from deploy import prepare_discovery_activation
        return prepare_discovery_activation
    return sys.modules[__name__]


def plan_images(plan, *, mode=None):
    cfg = _profile(mode); package = cfg.package
    images = plan.get('images')
    need(isinstance(images, dict) and set(images) == {'app', 'decoder'} and
         images['decoder'] == package.DECODER_IMAGE and
         re.fullmatch('sha256:[0-9a-f]{64}', images.get('app', '')) and
         images['app'] not in (package.PARENT_IMAGE, package.DECODER_IMAGE, WEB_IMAGE), 'local_photo_images_changed')
    return images


def check_plan(plan, *, mode=None):
    cfg = _profile(mode)
    cfg.plan_images(plan)
    need(plan.get('kind') == cfg.KIND and plan.get('parentSource') == cfg.PARENT_SOURCE and
         plan.get('parentManifest') == cfg.PARENT_MANIFEST and
         plan.get('schemaBefore') == ([77, 9] if mode == 'assistant-journey-status-source-update' else [75, 9] if mode in ('media-date-source-update', 'assistant-list-source-update', 'tv-trip-75-to-77') else [73, 9]) and
         plan.get('schemaAfter') == ([77, 9] if mode in ('tv-trip-75-to-77', 'assistant-journey-status-source-update') else [75, 9] if mode in ('journey-finance-73-to-75', 'media-date-source-update', 'assistant-list-source-update')
                                    else [73, 9]) and plan.get('productionWritesDuringPreparation') is False and
         re.fullmatch('[0-9a-f]{40}', plan.get('sourceHead', '')) and
         re.fullmatch('[0-9a-f]{40}', plan.get('tree', '')), 'local_photo_plan_changed')


def record(spec, name):
    need(isinstance(spec, dict) and set(spec) == {'root', 'sha256'} and Path(spec['root']).is_absolute(),
         'evidence_descriptor')
    root = regular(Path(spec['root']), directory=True)
    return root, read(root / name, spec['sha256'])


def reviewed(spec):
    need(set(spec) == {'path', 'sha256'} and Path(spec['path']).is_absolute(), 'review_descriptor')
    value = read(regular(spec['path']), spec['sha256'])
    previous.verify_review(value)
    return value


def runtime_proof(root, validation, meta, selection):
    previous.hashes_at(root, validation['evidence'])
    need(validation['runtimePath'] == 'proof/runtime.json' and validation['junitPath'] == 'proof/results.xml' and
         {'proof/runtime.json', 'proof/results.xml'} <= validation['evidence'].keys(), 'runtime_proof_missing')
    runtime = read(root / validation['runtimePath'])
    expected = {n[:-3]: '/app/' + n for n in meta['runtimeFiles'] if '/' not in n and n.endswith('.py')}
    need(runtime.get('pytestExitCode') == 0 and runtime.get('runtimeVerifiedBefore') is True and
         runtime.get('runtimeVerifiedAfter') is True and
         runtime.get('before') == runtime.get('after') == meta['runtimeFiles'] and
         runtime.get('sourceBefore') == runtime.get('sourceAfter') == {
             **meta['sourceFiles'], **{'static/experience/'+n: h for n, h in meta['exportFiles'].items()}} and
         runtime.get('loadedBefore') == runtime.get('loadedAfter') == expected and
         len(runtime.get('collected', [])) == len(selection['nodeids']) and
         set(runtime['collected']) == set(selection['nodeids']) and runtime.get('deselected') == [],
         'runtime_proof_changed')
    plugin = package.builder.SelectionPlugin(selection); plugin.reports = runtime['reports']
    need(plugin.accepted(), 'unapproved_test_results')
    need(package.builder.junit_result(root / validation['junitPath'], selection) == validation['counts'],
         'test_counts_changed')


def resources(spec, profile, meta):
    need(set(spec) == {'input', 'run'}, 'resource_descriptor')
    prepared, contract = record(spec['input'], 'input.json')
    root, result = record(spec['run'], 'result.json')
    expected = {n: h for n, h in meta['runtimeFiles'].items() if not n.startswith('static/experience/')}
    need(contract.get('kind') == 'local-photo-linux-input-v1' and contract.get('runtime') == expected and
         contract.get('images') == {'app': package.PARENT_IMAGE, 'web': WEB_IMAGE} and
         contract.get('limitsMiB') == LIMITS and contract.get('hostBudget') == HOST_BUDGET,
         'resource_runtime_or_limits_changed')
    # These runs use a complete exact runtime overlay on the same dependency
    # parent, not the new image. This distinction is retained in the plan.
    previous.hashes_at(prepared, contract['files'])
    need(contract['files'].get('nginx.original.conf') == package.NGINX_AFTER and
         all(contract['files'].get('runtime/'+n) == h for n, h in expected.items()) and
         contract['files'].get('tools/probe.py') == meta['sourceFiles'].get('deploy/local_photo_linux_probe.py') and
         contract['files'].get('tools/ipc.py') == meta['sourceFiles']['deploy/media_video_ipc_resource_probe.py'],
         'resource_input_closure_changed')
    need(result.get('passed') is True and result.get('profile') == profile and
         result.get('inputSha256') == spec['input']['sha256'] and result.get('failure') is None and
         result.get('cleanupErrors') == [] and result.get('unknownCreate') is None and
         result.get('hostMemory', {}).get('failure') is None and result.get('commands') and
         all(c.get('exitCode') == 0 and not c.get('abortedBy') for c in result['commands']), 'resource_not_passed')
    previous.hashes_at(root, result['artifacts'])
    for name in ('app/ready.json', 'app/gunicorn-worker.json', 'client/result.json', 'client/finished.json',
                 'app-final.json', 'client-final.json', 'cgroup-samples.json', 'host-memory.json'):
        need(name in result['artifacts'], 'resource_original_missing')
    memory = read(root/'host-memory.json')
    need(memory == result['hostMemory'] and memory.get('policy') == HOST_BUDGET and
         memory.get('failure') is None and memory.get('threadStarted') is True and
         memory.get('threadStopped') is True and type(memory.get('sampleCount')) is int and
         memory['sampleCount'] > 0 and memory.get('minimumAvailableKiB', 0) >= HOST_BUDGET['abortBelowMiB']*1024,
         'resource_host_monitor_incomplete')
    proof = read(root / 'client/result.json')
    need(proof == result.get('proof') and proof.get('passed') is True and proof.get('failure') is None and
         read(root/'client/finished.json') == {'passed': True, 'resultSha256': result['artifacts']['client/result.json']},
         'resource_http_incomplete')
    for name in ('app/ready.json', 'app/gunicorn-worker.json'):
        actual = read(root/name)['loaded']['modules']
        need({'app', 'media_local_upload', 'media_images'} <= actual.keys() and
             all(v == {'path': '/runtime/'+n+'.py', 'sha256': expected.get(n+'.py')} for n, v in actual.items()),
             'resource_import_provenance_changed')
    roles = ['app', 'client'] + (['web'] if profile == 'nginx_raw' else [])
    need(set(result['containers']) == set(roles), 'resource_roles_changed')
    for role in roles:
        name = role+'-final.json'; need(name in result['artifacts'], 'resource_final_missing')
        final = read(root/name); state = final['State']
        need(final['Id'] == result['containers'][role] and not state['Running'] and state['Pid'] == 0 and
             not state['OOMKilled'] and (role != 'client' or state['ExitCode'] == 0) and
             final['Image'] == (WEB_IMAGE if role == 'web' else package.PARENT_IMAGE) and
             final['HostConfig']['Memory'] == final['HostConfig']['MemorySwap'] == LIMITS[role]*1024**2,
             'resource_container_changed')
    samples = json.loads(regular(root/'cgroup-samples.json').read_bytes())
    need(samples, 'resource_measurements_missing')
    for sample in samples:
        need(set(sample['roles']) == set(roles), 'resource_measurements_incomplete')
        for role, state in sample['roles'].items():
            events = dict(line.split() for line in state['memory.events'].splitlines())
            need(int(state['memory.max']) == LIMITS[role]*1024**2 and
                 all(int(events.get(k, '0')) == 0 for k in ('max', 'oom', 'oom_kill', 'oom_group_kill')),
                 'resource_limit_event')
    if profile == 'image_overlap':
        overlap = proof.get('overlap', {})
        need(len(proof.get('checks', [])) == 3 and overlap.get('bytes') == 64*1024**2 and
             overlap.get('busyAfterEachImage') is True and
             all(item['input']['pixels'] == 20_000_000 for item in proof['checks']) and
             {item['input']['contentType'] for item in proof['checks']} == {'image/jpeg', 'image/png', 'image/webp'},
             'image_overlap_incomplete')
    else:
        need(result.get('temporaryEvents') == [] and not result.get('temporaryWatchError') and
             any(all(c.get(k) is True for k in ('twoSignedHouseholds', 'sameRawRoute', 'crossHouseholdIDsDenied',
                 'exact8MiBAccepted', 'oversize413', 'otherRaw415', 'csrfAndOrigin403')) for c in proof['checks']),
             'nginx_raw_incomplete')
    need(result.get('database'), 'resource_database_proof_missing')
    return {'input': {'input.json': spec['input']['sha256'], **contract['files']},
            'run': {'result.json': spec['run']['sha256'], **result['artifacts']}}


def verify_evidence(inputs, *, mode=None):
    cfg = _profile(mode); package = cfg.package
    expected_inputs = cfg.INPUT_ROLES if mode in ('media-date-source-update', 'assistant-list-source-update', 'tv-trip-75-to-77', 'assistant-journey-status-source-update') else ({'package', 'build', 'validation', 'selection', 'parentAudit',
                         'image_overlap', 'nginx_raw', 'reviews'} | ({'duplicates'} if mode else set())
         | ({'retainedDiscovery'} if mode == 'finance-flow-source-update' else set())
         | ({'retainedFinance', 'retainedDiscovery', 'migrationRehearsal'} if mode == 'journey-finance-73-to-75' else set()))
    need(set(inputs) == expected_inputs, 'release_inputs_incomplete')
    p = inputs['package']; need(set(p) == {'root', 'sha256'} and Path(p['root']).is_absolute(), 'package_descriptor')
    value = package.verify_package(p['root'], p['sha256']); meta = value['metadata']
    folder, built = record(inputs['build'], 'build.json')
    vroot, validation = record(inputs['validation'], 'validation.json')
    for item in (built, validation):
        need(item.get('exitCode') == 0 and item.get('productionOperations') is False and
             item.get('sourceHead') == meta['sourceHead'] and item.get('tree') == meta['tree'] and
             item.get('packageSha256') == p['sha256'] and item.get('manifestSha256') == meta['manifestSha256'],
             'application_evidence_changed')
    need(built['parentImage'] == package.PARENT_IMAGE and built['addedLayers'] == 2 and
         built['runtimeHashes'] == meta['runtimeFiles'] and validation['imageId'] == built['imageId'] and
         validation.get('allPassed') is True and validation.get('containerExitCode') == 0, 'application_build_or_tests_failed')
    cfg.plan_images({'images': {'app': built['imageId'], 'decoder': package.DECODER_IMAGE}})
    s = inputs['selection']; need(set(s) == {'path', 'sha256'}, 'selection_descriptor')
    need(Path(s['path']).is_absolute(), 'selection_location')
    selection = package.builder.selection_record(regular(s['path']).read_bytes(), s['sha256'], meta)
    need(selection['allowedSkips'] == {} and validation['selectionSha256'] == s['sha256'], 'selection_changed')
    runtime_proof(vroot, validation, meta, selection)
    parent = inputs['parentAudit']; need(parent['sha256'] == package.AUDIT_SHA256, 'parent_audit_changed')
    reviewed(parent)
    verified = {'package': previous.file_map(Path(p['root'])), 'build': previous.file_map(folder),
                'validation': previous.file_map(vroot), 'selection': s['sha256'], 'parentAudit': parent['sha256']}
    if mode:
        verified.update(cfg.resource_evidence(inputs, value, built))
    else:
        for profile in ('image_overlap', 'nginx_raw'):
            verified[profile] = resources(inputs[profile], profile, meta)
    need(isinstance(inputs['reviews'], dict) and set(inputs['reviews']) == cfg.REVIEW_ROLES, 'independent_reviews_missing')
    verified['reviews'] = {}
    for name, spec in inputs['reviews'].items():
        reviewed(spec); verified['reviews'][name] = spec['sha256']
    return value, built, verified


def prepare(inputs_file, env_sha256, output, *, mode=None):
    cfg = _profile(mode); package = cfg.package
    need(re.fullmatch('[0-9a-f]{64}', env_sha256), 'environment_digest_required')
    output = Path(output).absolute(); regular(output.parent, directory=True)
    need(not output.exists() and not output.is_symlink() and '..' not in output.parts, 'exclusive_candidate_required')
    inputs = read(inputs_file)
    def locations(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ('root', 'path') and isinstance(item, str): yield Path(item).absolute()
                else: yield from locations(item)
    for path in (Path(inputs_file).absolute(), *locations(inputs)):
        need(not output.is_relative_to(path) and not path.is_relative_to(output), 'output_overlaps_input')
    value, built, verified = cfg.verify_evidence(inputs); meta = value['metadata']
    blobs = {n: value['blobs'][n] for n in cfg.OPERATORS}
    executing = Path(__file__).resolve().parents[1]
    need(all(regular(executing/n).read_bytes() == raw for n, raw in blobs.items()), 'executed_operator_changed')
    output.mkdir(mode=0o700)
    for name, raw in blobs.items():
        target = output/'operator'/name; target.parent.mkdir(parents=True, exist_ok=True); put(target, raw)
    for name, raw in value['blobs'].items():
        target = output/'source'/relative(name); target.parent.mkdir(parents=True, exist_ok=True); put(target, raw)
    put(output/'source/RELEASE-MANIFEST.json', regular(Path(inputs['package']['root'])/'release-manifest.json').read_bytes())
    for path in (output/'source', *(output/'source').rglob('*')):
        regular(path, directory=path.is_dir()); path.chmod(0o755 if path.is_dir() else 0o644)
    operator = {'head': meta['sourceHead'], 'tree': meta['tree'], 'files': {n: sha(raw) for n, raw in blobs.items()}}
    put(output/'operator.json', operator)
    plan = {'kind': cfg.KIND, 'parentSource': cfg.PARENT_SOURCE, 'parentManifest': cfg.PARENT_MANIFEST,
            'sourceHead': meta['sourceHead'], 'tree': meta['tree'],
            'images': {'app': built['imageId'], 'decoder': package.DECODER_IMAGE},
            'envSha256': env_sha256, 'inputs': inputs, 'verifiedEvidence': verified,
            'operatorSha256': sha(encoded(operator)),
            'schemaBefore': [77, 9] if mode == 'assistant-journey-status-source-update' else [75, 9] if mode in ('media-date-source-update', 'assistant-list-source-update', 'tv-trip-75-to-77') else [73, 9],
            'schemaAfter': [77, 9] if mode in ('tv-trip-75-to-77', 'assistant-journey-status-source-update') else [75, 9] if mode in ('journey-finance-73-to-75', 'media-date-source-update', 'assistant-list-source-update') else [73, 9],
            'productionWritesDuringPreparation': False}
    cfg.check_plan(plan)
    need(cfg.verify_evidence(inputs)[2] == verified, 'evidence_changed_during_prepare')
    put(output/'plan.json', plan)
    return {'prepared': True, 'planSha256': sha(encoded(plan)), 'operatorSha256': sha(encoded(operator))}


def main(argv=None, *, mode=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('inputs-file', 'env-sha256', 'output'): parser.add_argument('--'+name, required=True)
    print(json.dumps(prepare(**vars(parser.parse_args(argv)), mode=mode)))


if __name__ == '__main__': main()
