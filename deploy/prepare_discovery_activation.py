"""Closed discovery admission: retained parent media proofs plus a new scan resource run."""
import ast
import json
from pathlib import Path
import sys
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy import build_discovery_release as package
from deploy import prepare_local_photo_activation as shared
from deploy.membership_release_controller import need, regular, read, sha, encoded

MODE = 'discovery-source-update'
KIND = 'discovery-five-service-source-update-v1'
PARENT_SOURCE, PARENT_MANIFEST = package.INSTALLED_SOURCE, package.OLD_MANIFEST
OPERATORS = sorted(set(shared.OPERATORS) | {
    'deploy/build_discovery_release.py', 'deploy/prepare_discovery_activation.py',
    'deploy/activate_discovery_release.py'})
REVIEW_ROLES = shared.REVIEW_ROLES
DUPLICATE_LIMITS = {'app': 384, 'client': 64}
DUPLICATE_HOST_BUDGET = {'preflightMiB': 640, 'preflightSamples': 3, 'preflightIntervalSeconds': 1,
    'abortBelowMiB': 256, 'sampleIntervalSeconds': .25, 'maxSampleLagSeconds': 1}
REQUIRED_NODES = {
    'tests/test_media_duplicate_hints.py::test_scan_cap_is_real_bounded_sql_and_does_not_claim_exhaustiveness',
    'tests/test_media_duplicate_hints.py::test_real_lock_contention_returns_recoverable_failure_without_writes'}


def plan_images(plan): return shared.plan_images(plan, mode=MODE)
def check_plan(plan): return shared.check_plan(plan, mode=MODE)
def prepare(**kwargs): return shared.prepare(**kwargs, mode=MODE)


def unchanged_media_ast(name, before, after):
    """Compare existing AST outside search additions and two integrity lookups.

    Full old/new module hashes are pinned separately; this check additionally
    The preview exception permits only missing-key-safe reads of bytes/sha256;
    its remaining decryption, integrity rejection and authority checks must match.
    """
    need(sha(before) == package.PARENT_MODULES[name] and sha(after) == package.CHANGED_MODULES[name],
         'resource_module_pin_changed')
    def normalize(raw, new):
        tree = ast.parse(raw)
        if name == 'home_assistant.py':
            scope = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'register_assistant')
            scope.body = [n for n in scope.body if not (new and isinstance(n, ast.FunctionDef)
                                                      and n.name == 'search_place_metadata')]
            node = next(n for n in scope.body if isinstance(n, ast.FunctionDef) and n.name == 'search_records')
            node.body = [ast.Pass()]
        elif name == 'household_media.py' and new:
            tree.body = [n for n in tree.body if not (
                isinstance(n, ast.Import) and len(n.names) == 1 and n.names[0].name == 'sqlite3' or
                isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
                and n.targets[0].id == 'DUPLICATE_SCAN_LIMIT')]
            media = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MediaLibrary')
            added = {'_display_fingerprint', '_duplicate_source', '_duplicate_snapshot', 'duplicate_hints'}
            media.body = [n for n in media.body if not (isinstance(n, ast.FunctionDef) and n.name in added)]
            preview = next(n for n in media.body if isinstance(n, ast.FunctionDef) and n.name == 'preview')
            guards = [n for n in preview.body if isinstance(n, ast.If)]
            safe_condition = "raw is None or len(raw)!=meta.get('bytes') or hashlib.sha256(raw).hexdigest()!=meta.get('sha256')"
            original_condition = "raw is None or len(raw)!=meta['bytes'] or hashlib.sha256(raw).hexdigest()!=meta['sha256']"
            need(len(guards) == 1 and ast.dump(guards[0].test, include_attributes=False)
                 == ast.dump(ast.parse(safe_condition, mode='eval').body, include_attributes=False),
                 'resource_preview_guard_changed')
            guards[0].test = ast.parse(original_condition, mode='eval').body
            register = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'register_media_library')
            register.body = [n for n in register.body if not (isinstance(n, ast.FunctionDef) and n.name == 'media_duplicate_hints')]
        return ast.dump(tree, include_attributes=False)
    need(normalize(before, False) == normalize(after, True), 'resource_media_behavior_changed')
    return {'before': sha(before), 'after': sha(after), 'unchangedOutsidePinnedNodes': True,
            'previewMissingIntegrityGuard': name == 'household_media.py'}


def parent_resources(spec, profile, value):
    meta = value['metadata']
    current = {n: h for n, h in meta['runtimeFiles'].items() if not n.startswith('static/experience/')}
    kept = {n: h for n, h in current.items() if n not in package.CHANGED_MODULES}
    need(len(current) == 112 and len(kept) == 110 and sha(package.package.encoded(kept)) == package.PRESERVED_RUNTIME_SHA256
         and all(current.get(n) == h for n, h in package.CHANGED_MODULES.items()), 'resource_preservation_changed')
    original = {**kept, **package.PARENT_MODULES}
    need(sha(package.package.encoded(original)) == package.PARENT_RUNTIME_SHA256, 'parent_resource_map_changed')
    # Deliberately validate the old run against its exact original 112 modules,
    # not against the current application's different two module hashes.
    proof = shared.resources(spec, profile, {**meta, 'runtimeFiles': original})
    prepared, _ = shared.record(spec['input'], 'input.json')
    boundary = {n: unchanged_media_ast(n, regular(prepared/'runtime'/n).read_bytes(), value['blobs'][n])
                for n in package.CHANGED_MODULES}
    return {**proof, 'scope': 'retained-parent-media-paths-only', 'parentSource': PARENT_SOURCE,
            'parentRuntimeSha256': package.PARENT_RUNTIME_SHA256,
            'candidatePreservedFiles': 110, 'astBoundary': boundary}


def duplicate_resources(spec, value, built, package_sha, build_sha):
    """Read the bounded new workload's actual originals; an attestation alone is insufficient."""
    need(set(spec) == {'input', 'run'}, 'duplicate_resource_descriptor')
    prepared, contract = shared.record(spec['input'], 'input.json')
    root, result = shared.record(spec['run'], 'result.json')
    meta = value['metadata']; expected = {n: h for n, h in meta['runtimeFiles'].items()
                                         if not n.startswith('static/experience/')}
    need(contract.get('kind') == 'discovery-duplicates-linux-input-v1' and
         contract.get('sourceHead') == meta['sourceHead'] and contract.get('tree') == meta['tree'] and
         contract.get('packageSha256') == package_sha and contract.get('manifestSha256') == meta['manifestSha256'] and
         contract.get('imageId') == built['imageId'] and contract.get('buildSha256') == build_sha and
         contract.get('runtimeFiles') == expected and contract.get('exportFiles') == meta['exportFiles'] and
         contract.get('limitsMiB') == DUPLICATE_LIMITS and contract.get('hostBudget') == DUPLICATE_HOST_BUDGET,
         'duplicate_resource_input_changed')
    shared.previous.hashes_at(prepared, contract['files'])
    need(contract['files'].get('tools/probe.py') == meta['sourceFiles'].get('deploy/discovery_duplicate_linux_probe.py')
         and contract['files'].get('tools/probe.py') is not None, 'duplicate_probe_source_changed')
    need(result.get('kind') == 'discovery-duplicates-linux-result-v1' and result.get('passed') is True and
         result.get('inputSha256') == spec['input']['sha256'] and result.get('failure') is None and
         result.get('cleanupErrors') == [] and result.get('unknownCreate') is None and result.get('commands') and
         all(c.get('exitCode') == 0 and not c.get('abortedBy') for c in result['commands']), 'duplicate_resource_failed')
    shared.previous.hashes_at(root, result['artifacts'])
    required = {'app/ready.json', 'app/gunicorn-worker.json', 'client/result.json', 'client/finished.json',
                'app-final.json', 'client-final.json', 'cgroup-samples.json', 'host-memory.json', 'database.json'}
    need(required <= result['artifacts'].keys(), 'duplicate_resource_original_missing')
    proof = read(root/'client/result.json')
    need(proof == result.get('proof') and proof.get('passed') is True and proof.get('failure') is None and
         read(root/'client/finished.json') == {'passed': True, 'resultSha256': result['artifacts']['client/result.json']},
         'duplicate_http_incomplete')
    need(proof.get('concurrency') == 4 and proof.get('ownerReadyRecords') == 1002 and
         proof.get('candidateRecords') == 1001 and proof.get('scanLimit') == 1000 and
         proof.get('scanInvocationCount', 0) >= 1 and proof.get('blobReadCount') == 0 and
         len(proof.get('responses', [])) == 4 and proof.get('overlapObserved') is True and
         all(p.get('status') == 200 or (p.get('status') == 503 and p.get('code') == 'unavailable')
             for p in proof['responses']) and proof.get('recoveryStatus') == 200 and proof.get('coverageCapped') is True,
         'duplicate_workload_incomplete')
    database = read(root/'database.json')
    need(database == result.get('database') and database.get('before') == database.get('after') and
         isinstance(database.get('before'), str) and len(database['before']) == 64, 'duplicate_database_changed')
    for name in ('app/ready.json', 'app/gunicorn-worker.json'):
        actual = read(root/name)['loaded']['modules']
        need({'app', 'household_media', 'media_crypto'} <= actual.keys() and
             all(v == {'path': '/app/'+n+'.py', 'sha256': expected.get(n+'.py')} for n, v in actual.items()),
             'duplicate_runtime_import_changed')
    memory = read(root/'host-memory.json')
    need(memory == result.get('hostMemory') and memory.get('policy') == DUPLICATE_HOST_BUDGET and
         memory.get('failure') is None and memory.get('threadStarted') is True and memory.get('threadStopped') is True and
         type(memory.get('sampleCount')) is int and memory['sampleCount'] > 0 and
         memory.get('minimumAvailableKiB', 0) >= DUPLICATE_HOST_BUDGET['abortBelowMiB']*1024,
         'duplicate_host_monitor_incomplete')
    need(set(result['containers']) == set(DUPLICATE_LIMITS), 'duplicate_roles_changed')
    for role, limit in DUPLICATE_LIMITS.items():
        final = read(root/(role+'-final.json')); state = final['State']
        need(final['Id'] == result['containers'][role] and not state['Running'] and state['Pid'] == 0 and
             not state['OOMKilled'] and (role != 'client' or state['ExitCode'] == 0) and final['Image'] == built['imageId'] and
             final['HostConfig']['Memory'] == final['HostConfig']['MemorySwap'] == limit*1024**2,
             'duplicate_container_changed')
    samples = read(root/'cgroup-samples.json'); need(samples, 'duplicate_measurements_missing')
    for sample in samples:
        need(set(sample['roles']) == set(DUPLICATE_LIMITS), 'duplicate_measurements_incomplete')
        for role, state in sample['roles'].items():
            events = dict(line.split() for line in state['memory.events'].splitlines())
            need(int(state['memory.max']) == DUPLICATE_LIMITS[role]*1024**2 and
                 0 < int(state['memory.peak']) <= DUPLICATE_LIMITS[role]*1024**2 and
                 all(k in events and int(events[k]) == 0 for k in ('max', 'oom', 'oom_kill')),
                 'duplicate_resource_limit_event')
    return {'scope': 'four-concurrent-bounded-metadata-requests-only',
            'input': {'input.json': spec['input']['sha256'], **contract['files']},
            'run': {'result.json': spec['run']['sha256'], **result['artifacts']}}


def resource_evidence(inputs, value, built):
    return {**{p: parent_resources(inputs[p], p, value) for p in ('image_overlap', 'nginx_raw')},
            'duplicates': duplicate_resources(inputs['duplicates'], value, built,
                                             inputs['package']['sha256'], inputs['build']['sha256'])}


def verify_evidence(inputs):
    value, built, verified = shared.verify_evidence(inputs, mode=MODE)
    s = inputs['selection']; selection = read(s['path'], s['sha256'])
    need(REQUIRED_NODES <= set(selection['nodeids']), 'duplicate_bounded_scan_tests_missing')
    return value, built, verified


def main(argv=None): return shared.main(argv, mode=MODE)
if __name__ == '__main__': main()
