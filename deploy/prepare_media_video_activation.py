"""Offline, exclusive preparation for the reviewed two-image/five-service release.

No Docker, production configuration, credential or database reads. Evidence
paths name isolated retained experiments; the caller separately supplies the
hash of the production environment, never its contents.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy import media_video_release_package as package
from deploy import build_media_video_release as build
from deploy.membership_release_controller import need, regular, read, put, relative, sha, encoded

BASE = '2cc1b6e685b384575b59e6885fa2598c6fe99a8f'
PARENT_SOURCE = '8d3e6376a606155ff66a0388e43d04cb7562fe9f'
PARENT_MANIFEST = '83ff8610c85eccf9dfc5e9dac788d2704543e8dc68d937e1463fbf7819add5c1'
APP_SOURCE = 'b8c4d599257d77709f65f455bab9e1a5d5c7aff1'
IMAGES = {'app': 'sha256:75d2cf07e1fe01eb56fe1fed999442b922d046eba52c64e4227ed176a0e975a5',
          'decoder': 'sha256:005cc30d5eec73abdfa1fcc62f4d84d871edc2a1cc6169c96390e368f1511c8c'}
ADDITIONS = {'deploy/media_video_release_controller.py', 'deploy/prepare_media_video_activation.py',
             'tests/test_media_video_release_controller.py', 'docs/MEDIA-VIDEO-ACTIVATION.md'}
OPERATORS = sorted(ADDITIONS & {'deploy/media_video_release_controller.py', 'deploy/prepare_media_video_activation.py'} | {
    'deploy/media_video_service_lifecycle.py', 'deploy/media_video_release_package.py', 'deploy/build_media_video_release.py',
    'deploy/membership_release_package.py', 'deploy/membership_release_build.py',
    'deploy/membership_release_controller.py', 'deploy/git_blobs.py'})
EVIDENCE = {'migration', 'worker100', 'response64'}
MIGRATION_STAGES = {'verify', 'seed', 'migrate', 'startup', 'check', 'rollback71', 'partial', 'populate73', 'restart', 'restore73'}


def digest_file(path):
    path = regular(path)
    need(path.stat().st_size <= 1_000_000_000, 'evidence_file_too_large')
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()


def file_map(root):
    root = regular(root, directory=True)
    files = {}
    for path in root.rglob('*'):
        regular(path, directory=path.is_dir())
        if path.is_file():
            need(len(files) < 5000, 'too_many_evidence_files')
            files[relative(path.relative_to(root).as_posix())] = digest_file(path)
    return files


def checked_record(spec):
    need(set(spec) == {'root', 'result', 'sha256'}, 'evidence_descriptor')
    root = regular(Path(spec['root']), directory=True)
    result = read(root / relative(spec['result']), spec['sha256'])
    return root, result


def hashes_at(root, files):
    need(isinstance(files, dict) and files, 'evidence_hashes_missing')
    for name, expected in files.items():
        need(re.fullmatch('[0-9a-f]{64}', expected or '') and
             digest_file(root / relative(name)) == expected, 'evidence_hash_changed')


def verify_migration(spec, package_value):
    need(set(spec) == {'run', 'input'}, 'migration_descriptor')
    root, result = checked_record(spec['run'])
    inputs_root, inputs = checked_record(spec['input'])
    runtime = build.runtime_map('app', package_value['metadata']['contexts']['app'])
    modules = {n: h for n, h in runtime.items() if '/' not in n}
    need(result.get('passed') is True and result.get('syntheticOnly') is True and
         result.get('productionAccess') is False and result.get('imageId') == IMAGES['app'] and
         result.get('inputSha256') == spec['input']['sha256'], 'migration_not_passed')
    need(inputs.get('historicalHead') == PARENT_SOURCE and inputs.get('productionOperations') is False and
         inputs.get('runtimeFiles') == modules, 'migration_runtime_differs')
    hashes_at(inputs_root, inputs['files'])
    hashes_at(root / 'proof', result['proofHashes'])
    stages = result.get('stages', {})
    need(set(stages) == MIGRATION_STAGES and stages['verify'].get('verified') is True and
         stages['verify'].get('uid') == 10001 and stages['verify'].get('runtime') == modules,
         'migration_stages_incomplete')
    need(stages['seed'].get('households') == 2 and stages['seed'].get('databases') == 3,
         'migration_requires_two_households')
    for name in ('migrate', 'check', 'rollback71', 'partial', 'restore73'):
        value = stages[name]
        need(value.get('verified') is True and value.get('households') == 2 and value.get('databases') == 3,
             'migration_group_not_verified')
    need(stages['check']['logicalSha256'] == stages['migrate']['logicalSha256'] and
         all(stages[n].get('completeGroupRestored') is True for n in ('rollback71', 'partial', 'restore73')) and
         stages['partial'].get('replayRejected') is True and
         sorted(stages['partial']['partialTableCounts'].values()) == [71, 73], 'migration_recovery_incomplete')
    need(stages['startup'].get('initialized') is True and stages['restart'].get('initialized') is True,
         'real_app_startup_missing')
    need(stages['populate73'].get('populated') is True and stages['populate73'].get('rowsPerNewTable') == 2,
         'nonempty_current_restore_missing')
    need(all(c.get('exitCode') == 0 for c in result['commands']), 'migration_command_failed')
    return {'runFiles': file_map(root), 'inputFiles': file_map(inputs_root)}


def verify_resources(spec, profile, package_value):
    root, result = checked_record(spec)
    contract = result.get('contract', {})
    runtime = build.runtime_map('app', package_value['metadata']['contexts']['app'])
    modules = {n: h for n, h in runtime.items() if '/' not in n}
    decoder = build.runtime_map('decoder', package_value['metadata']['contexts']['decoder'])
    need(result.get('passed') is True and result.get('status') == 'passed' and result.get('profile') == profile and
         result.get('failure') is None and result.get('workerAttachExitCode') == 0 and
         not result.get('cleanupErrors') and result.get('unconfirmedCreate') is None, 'resource_profile_not_passed')
    need(contract.get('images') == {'application': IMAGES['app'], 'decoder': IMAGES['decoder']} and
         contract.get('limitsMiB') == {'application': 384, 'decoder': 768} and
         contract.get('app') == modules and contract.get('decoder') == decoder, 'resource_runtime_differs')
    memory = result.get('hostMemory', {})
    budget = {'preflightMiB': 1280, 'preflightSamples': 3, 'preflightIntervalSeconds': 1,
              'abortBelowMiB': 256, 'sampleIntervalSeconds': .25, 'maxSampleLagSeconds': 1}
    need(memory.get('failure') is None and memory.get('threadStarted') is True and memory.get('threadStopped') is True and
         memory.get('policy') == budget and type(memory.get('sampleCount')) is int and memory['sampleCount'] > 0 and
         memory.get('minimumAvailableKiB', 0) >= 256*1024, 'host_memory_aborted')
    required = {'preflight.json', 'host-memory.json', 'application/finished.json', 'decoder/finished.json',
                'application-container.json', 'decoder-container.json', 'application/application.json'}
    need(required <= result.get('artifacts', {}).keys(), 'resource_originals_missing')
    hashes_at(root, result['artifacts'])
    preflight = read(root/'preflight.json')
    need(preflight.get('status') == 'ready' and preflight.get('failure') is None and preflight.get('policy') == budget and
         len(preflight.get('samples', [])) == 3 and
         all(s.get('availableKiB', 0) >= 1280*1024 for s in preflight['samples']) and
         read(root/'host-memory.json') == memory, 'resource_host_gate_not_verified')
    proofs = result.get('proofs', {})
    need(set(proofs) == {'application', 'decoder'}, 'resource_roles_missing')
    identities = []
    for role, limit in (('application', 384), ('decoder', 768)):
        p = proofs[role]
        need(read(root/role/'finished.json') == p, 'resource_inner_receipt_differs')
        state = read(root/(role+'-container.json'))
        need(state.get('Image') == contract['images'][role] and state.get('Id') == result.get('containers', {}).get(role) and
             re.fullmatch('[0-9a-f]{64}', state.get('Id', '')) and state['State'].get('ExitCode') == 0 and
             state['State'].get('Running') is False and state['State'].get('OOMKilled') is False and
             state['HostConfig'].get('Memory') == state['HostConfig'].get('MemorySwap') == limit*1024**2 and
             state['HostConfig'].get('NetworkMode') == 'none' and state['HostConfig'].get('ReadonlyRootfs') is True and
             state['Config'].get('User') == '10001:10001', 'resource_container_not_verified')
        identities.append(state['Id'])
        need(p.get('role') == role and p.get('profile') == profile and p.get('exitCode') == 0 and
             p.get('loadedSourceVerified') is True and p.get('sourceHead') == contract.get('sourceHead'),
             'resource_inner_proof_failed')
        cgroup = p['cgroup']
        need(int(cgroup['memory.max']) == limit * 1024**2 and int(cgroup['memory.peak']) > 0 and
             int(cgroup['memory.peak']) <= limit * 1024**2 and cgroup['memory.swap.max'].strip() == '0' and
             cgroup['pids.max'].strip() == '128', 'resource_cgroup_limit')
        events = dict(line.split() for line in cgroup['memory.events'].splitlines())
        need({'max', 'oom', 'oom_kill'} <= events.keys() and
             all(int(events.get(k, '0')) == 0 for k in ('max', 'oom', 'oom_kill', 'oom_group_kill')), 'resource_oom')
    need(len(set(identities)) == 2, 'resource_requires_separate_containers')
    application = read(root/'application/application.json')
    need(application.get('profile') == profile and
         all(application.get(k) is True for k in ('responseClosed', 'busyWhileOpen', 'permitReleasedAfterClose',
              'otherMemberDenied', 'idRevisionPreserved', 'confirmationReplayed')) and
         application.get('counts') == {'media_items': 1, 'media_video_cache': 1} and application.get('reservedBytes') == 0,
         'resource_full_application_flow_missing')
    need((profile == 'worker100' and application.get('downloadBytes') == 100*1024**2 and
          len(application.get('socketCalls', [])) == 1) or
         (profile == 'response64' and application.get('responseBytes') == 64*1024**2 and
          application.get('response64IsExplicitSizeFixture') is True), 'resource_size_boundary_missing')
    return file_map(root)


def verify_review(record):
    need(isinstance(record, dict), 'review_not_passed')
    decisions = [record[k] for k in ('verdict', 'conclusion', 'status', 'decision') if k in record]
    findings = [record[k] for k in ('findings', 'blockingFindings') if k in record]
    need(decisions and all(isinstance(v, str) and (v == 'PASS' or v.startswith('PASS_'))
                           for v in decisions) and findings and
         all(isinstance(v, list) and not v for v in findings), 'review_not_passed')


def verify_evidence(inputs):
    need(set(inputs) == {'package', 'build', 'migration', 'worker100', 'response64', 'reviews'}, 'release_inputs_incomplete')
    p, b = inputs['package'], inputs['build']
    value = package.verify_package(p['root'], p['sha256'])
    need(value['metadata']['sourceHead'] == APP_SOURCE, 'unreviewed_application_source')
    built = build.verify_build(b['root'], b['sha256'], p['root'], p['sha256'])
    need(built['images'] == IMAGES, 'candidate_images_differ')
    verified = {'package': file_map(Path(p['root'])), 'build': file_map(Path(b['root'])),
                'migration': verify_migration(inputs['migration'], value)}
    for profile in ('worker100', 'response64'):
        verified[profile] = verify_resources(inputs[profile], profile, value)
    # Reviews are externally authored receipts explicitly bound by this plan.
    # The human approving the plan SHA verifies their scope; no generated PASS.
    need(isinstance(inputs['reviews'], dict) and
         {'package', 'lifecycle', 'controller', 'migration', 'resources', 'browser'} == set(inputs['reviews']),
         'independent_reviews_missing')
    verified['reviews'] = {}
    for name, item in inputs['reviews'].items():
        path = regular(Path(item['path']))
        need(set(item) == {'path', 'sha256'} and digest_file(path) == item['sha256'], 'review_changed')
        record = read(path)
        verify_review(record)
        verified['reviews'][name] = item['sha256']
    return value, built, verified


def operator_blobs(repo, head):
    common = package.common
    common.identity(repo, head)
    changed = common.git(repo, 'diff', '--name-only', BASE, head).decode().splitlines()
    need(set(changed) == ADDITIONS, 'operator_changes_outside_review_scope')
    blobs = package.read_git_blobs(repo, head, OPERATORS)
    need(all((Path(repo) / n).read_bytes() == raw for n, raw in blobs.items()), 'operator_worktree_differs')
    return blobs


def prepare(repo, head, inputs_file, env_sha256, output):
    need(re.fullmatch('[0-9a-f]{64}', env_sha256), 'environment_digest_required')
    output = Path(output).absolute()
    regular(output.parent, directory=True)
    need(not output.exists() and not output.is_symlink() and '..' not in output.parts, 'exclusive_candidate_required')
    inputs = read(inputs_file)
    def locations(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ('root', 'path') and isinstance(item, str): yield Path(item).absolute()
                else: yield from locations(item)
    for source in (Path(repo).absolute(), Path(inputs_file).absolute(), *locations(inputs)):
        need(not output.is_relative_to(source) and not source.is_relative_to(output), 'output_overlaps_input')
    value, built, verified = verify_evidence(inputs)
    blobs = operator_blobs(Path(repo), head)
    output.mkdir(mode=0o700)
    for name, raw in blobs.items():
        target = output / 'operator' / name; target.parent.mkdir(parents=True, exist_ok=True)
        put(target, raw)
    for name, raw in value['blobs'].items():
        target = output / 'source' / relative(name); target.parent.mkdir(parents=True, exist_ok=True)
        put(target, raw); target.chmod(0o644)
    put(output / 'source/RELEASE-MANIFEST.json', package.encoded(value['manifest']))
    (output / 'source/RELEASE-MANIFEST.json').chmod(0o644)
    # A root operator may use umask 077. The source mount contains no secrets
    # and must remain readable by the non-root migration helper.
    for directory in [output/'source', *(p for p in (output/'source').rglob('*') if p.is_dir())]:
        directory.chmod(0o755)
    operator = {'head': head, 'tree': package.common.git(repo, 'rev-parse', head+'^{tree}').decode().strip(),
                'files': package.hashes(blobs)}
    put(output / 'operator.json', operator)
    plan = {'kind': 'media-video-five-service-activation-v1', 'parentSource': PARENT_SOURCE,
            'parentManifest': PARENT_MANIFEST, 'sourceHead': APP_SOURCE, 'images': IMAGES,
            'envSha256': env_sha256, 'inputs': inputs, 'verifiedEvidence': verified,
            'operatorSha256': sha(encoded(operator)), 'schemaBefore': [71, 9], 'schemaAfter': [73, 9],
            'productionWritesDuringPreparation': False}
    need(verify_evidence(inputs)[2] == verified, 'evidence_changed_during_prepare')
    put(output / 'plan.json', plan)
    return {'planSha256': sha(encoded(plan)), 'operatorSha256': sha(encoded(operator)), 'prepared': True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('repo', 'head', 'inputs-file', 'env-sha256', 'output'):
        parser.add_argument('--'+name, required=True)
    print(json.dumps(prepare(**vars(parser.parse_args(argv)))))


if __name__ == '__main__':
    main()
