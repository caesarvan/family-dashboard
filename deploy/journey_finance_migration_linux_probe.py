"""Closed synthetic 73/9 -> 75/9 Linux app-only migration and full-group restore.

Prepare uses local Git; run is a separate operation with one immutable app image.
No production paths, workers, Git or pytest are needed inside the containers.
"""
import argparse
import ast
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy import media_video_migration_linux_probe as video

policy, build, routes, previous = video.policy, video.build, video.routes, video.previous
need, sha, encoded, hashes = video.need, video.sha, video.encoded, video.hashes
BASE = 'a47372624e66cab0e8100a37f54223737780eb73'
BASE_MAP_SHA = 'ae7a2c2e13e5ef906ac49ff7cbdd4a0c8263672af9b8daff246a2907e597c2e4'
HISTORY = '53ea3fdb571eae69154e61d264f3c3542631cb49'
SEED_REFERENCE = 'dc2b54cfc7fc9063eb839ece87fdab72a21855be'
SELF = 'deploy/journey_finance_migration_linux_probe.py'
ADDITIONS = {SELF, 'tests/test_journey_finance_migration_linux_probe.py',
             'docs/JOURNEY-FINANCE-MIGRATION-LINUX.md'}
FIXTURES = video.FIXTURES | {'tests/test_journey_finance_migration.py'}
STAGES = ('verify', 'seed', 'migrate', 'startup', 'check', 'rollback73', 'partial',
          'populate75', 'restart', 'restore75')
ROWS = {'hub_journey_allocations': 3, 'hub_journey_allocation_operations': 1}
OLD_STAGE = dict(zip(STAGES, video.STAGES))


def programs(blobs, source):
    """Keep the reviewed container programs; change only the fixed schema fixture."""
    codes, binding = video.programs(blobs, source)
    bind = routes.replace_once(video.BIND, 'import check_media_video_migration as migration',
                               'import check_journey_finance_migration as migration')
    bind = routes.replace_once(bind, 'import media_video_release_data as current',
                               'import journey_finance_release_data as current')
    old_fixture = blobs['tests/test_media_video_migration.py']
    fixture = blobs['tests/test_journey_finance_migration.py']
    common = (video.dml(routes.POPULATE_FINANCE), video.dml(routes.POPULATE_ROUTES))
    old_seed = '\n'.join((*common, video.dml(old_fixture, 'baseline71')))
    new_seed = '\n'.join((*common, video.dml(fixture, 'baseline73')))
    seed = routes.replace_once(codes['seed'], 'len(tables)==71', 'len(tables)==73')
    seed = routes.replace_once(seed, "'householdTables':71", "'householdTables':73")
    codes['seed'] = routes.replace_once(seed, repr(old_seed), repr(new_seed))
    result = {}
    for name, old in OLD_STAGE.items():
        code = codes[old]
        if name != 'seed':
            code = routes.replace_once(code, video.BIND, bind)
        if name == 'rollback73':
            code = routes.replace_once(code, 'rollback71-result.json', 'rollback73-result.json')
        elif name == 'partial':
            code = routes.replace_once(code, 'list(counts.values())==[73,71]', 'list(counts.values())==[75,73]')
        elif name == 'populate75':
            code = routes.replace_once(code, repr(video.dml(old_fixture, 'populate')),
                                       repr(video.dml(fixture, 'populate')))
            code = routes.replace_once(code, "assert all(new['tables'][n]['count']==2 for n in migration.NEW_TABLES)",
                                       "assert {n:new['tables'][n]['count'] for n in migration.NEW_TABLES}==" + repr(ROWS))
            code = routes.replace_once(code, "'rowsPerNewTable':2,'opaqueSyntheticBytesNotVideo':True",
                                       "'rowsPerNewTable':" + repr(ROWS) + ", 'syntheticStorageFixturesNotApiActions':True")
        elif name == 'restore75':
            code = routes.replace_once(code, 'restored73-result.json', 'restored75-result.json')
        ast.parse(code)
        result[name] = code
    binding.update(historicalRuntimeReference=SEED_REFERENCE, historicalRuntimeMatchesProduction=True,
                   rowsPerNewTable=ROWS, schemaTransition='73/9 -> 75/9',
                   imageSourceScope='root Python modules and requirements only; not frontend/package admission')
    return result, binding


def prepare(repo, commit, output_dir):
    repo = Path(repo).absolute(); tree = policy.identity(repo, commit)
    tracked = policy.tracked_files(repo, commit); baseline = policy.tracked_files(repo, BASE)
    old = video.read_git_blobs(repo, BASE, sorted(baseline))
    candidate = video.read_git_blobs(repo, commit, sorted(tracked))
    need(sha(encoded(hashes(old))) == BASE_MAP_SHA and set(candidate) == baseline | ADDITIONS and
         all(candidate[n] == raw for n, raw in old.items()), 'outside frozen base plus three tools')
    need(all(policy.plain(repo / n) == raw for n, raw in candidate.items()), 'working source differs')
    names = {n for n in candidate if (n.endswith('.py') and '/' not in n) or
             (n.startswith('deploy/') and n.endswith('.py'))} | FIXTURES | video.DOCS | {'Dockerfile', 'requirements.txt'}
    release = {n: candidate[n] for n in names}
    root_py = lambda head: {n for n in policy.tracked_files(repo, head) if n.endswith('.py') and '/' not in n}
    history_names = root_py(HISTORY)
    need(history_names == root_py(SEED_REFERENCE) and 'journey_finance.py' not in history_names,
         'historical module set changed')
    historical = video.read_git_blobs(repo, HISTORY, sorted(history_names))
    reference = video.read_git_blobs(repo, SEED_REFERENCE, sorted(history_names))
    requirements = video.read_git_blobs(repo, HISTORY, ['requirements.txt'])['requirements.txt']
    need(historical == reference and requirements == candidate['requirements.txt'],
         'historical runtime/dependencies do not match fixed seed reference')
    codes, binding = programs(release, repo)
    runtime = set()
    for line in old['Dockerfile'].decode().splitlines():
        if line.startswith('COPY '):
            runtime.update(n for n in line.split()[1:-1] if n.endswith('.py') or n == 'requirements.txt')
    files = {**{'release/' + n: raw for n, raw in release.items()},
             **{'history/' + n: raw for n, raw in historical.items()},
             **{'programs/' + n + '.py': code.encode() for n, code in codes.items()}}
    target = Path(output_dir).absolute()
    need(not repo.is_relative_to(target), 'output overlaps repository')
    target = build.new_output(target, repo); target.chmod(0o755)
    for name, raw in files.items():
        build.save(target / name, raw)
    manifest = {'kind': 'journey-finance-migration-linux-input-v1', 'sourceHead': commit, 'tree': tree,
                'runtimeSourceHead': BASE, 'historicalHead': HISTORY, 'historyFiles': hashes(historical),
                'sourceFiles': hashes(release), 'runtimeFiles': {n: sha(candidate[n]) for n in sorted(runtime)},
                'files': hashes(files), 'stages': list(STAGES), 'binding': binding,
                'syntheticMarkerSha256': sha(previous.SYNTHETIC_MARKER), 'productionOperations': False}
    need(policy.identity(repo, commit) == tree and all(policy.plain(repo / n) == raw for n, raw in candidate.items()),
         'source changed')
    raw = encoded(manifest); policy.write_new(target / 'input.json', raw)
    verify(target, sha(raw))
    return {'inputSha256': sha(raw), 'sourceHead': commit, 'files': len(files), 'outputDir': str(target),
            'dockerExecuted': False}


def verify(bundle, input_sha256):
    bundle = policy.checked(Path(bundle).absolute(), True)
    raw = policy.plain(bundle / 'input.json', 2_000_000)
    need(sha(raw) == policy.checksum(input_sha256), 'input manifest hash differs')
    meta = policy.json_value(raw)
    need(meta['kind'] == 'journey-finance-migration-linux-input-v1' and meta['runtimeSourceHead'] == BASE and
         meta['historicalHead'] == HISTORY and meta['productionOperations'] is False and meta['stages'] == list(STAGES),
         'input policy differs')
    policy.hash_map(meta['files'])
    need(build.tree_hashes(bundle) == dict(meta['files'], **{'input.json': sha(raw)}), 'input bytes differ')
    need(meta['files']['release/' + SELF] == sha(policy.plain(Path(__file__).absolute())), 'executed runner differs')
    need({n.removeprefix('release/'): v for n, v in meta['files'].items() if n.startswith('release/')} == meta['sourceFiles'] and
         {n.removeprefix('history/'): v for n, v in meta['files'].items() if n.startswith('history/')} == meta['historyFiles'],
         'source partition differs')
    need(meta['runtimeFiles'] and all(meta['sourceFiles'].get(n) == value for n, value in meta['runtimeFiles'].items()),
         'runtime differs from source')
    need(meta['binding']['rowsPerNewTable'] == ROWS and meta['syntheticMarkerSha256'] == sha(previous.SYNTHETIC_MARKER),
         'fixture policy differs')
    return bundle, meta


def container_args(image, bundle, output, stage, contract_sha):
    need(stage in STAGES, 'unknown stage')
    args = video.container_args(image, bundle, output, OLD_STAGE[stage], contract_sha)
    need(args[-1] == '/programs/' + OLD_STAGE[stage] + '.py', 'container program contract changed')
    return args[:-1] + ['/programs/' + stage + '.py']


def run(bundle, input_sha256, image_id, output_dir):
    need(sys.platform == 'linux' and os.geteuid() == 0 and sys.dont_write_bytecode and not sys.flags.optimize,
         'Linux root python -B without optimization required')
    need(not any(n.upper().startswith(('DOCKER_', 'COMPOSE_')) for n in os.environ), 'ambient Docker selector')
    bundle, meta = verify(bundle, input_sha256); build.image_id(image_id)
    need(not bundle.is_relative_to(Path(output_dir).absolute()), 'output overlaps input')
    output = build.new_output(output_dir, bundle)
    for name in ('data', 'proof', 'data/main', 'proof/main'):
        path = output / name; path.mkdir(mode=0o700); os.chown(path, 10001, 10001)
    contract = {'inputSha256': input_sha256, 'historyFiles': meta['historyFiles'],
                'syntheticMarkerSha256': meta['syntheticMarkerSha256'],
                'identity': {'head': meta['sourceHead'], 'tree': meta['tree'], 'imageId': image_id,
                             'sourceHashes': meta['sourceFiles'], 'runtimeHashes': meta['runtimeFiles']}}
    raw = encoded(contract); policy.write_new(output / 'proof/contract.json', raw)
    os.chown(output / 'proof/contract.json', 10001, 10001)
    docker = build.Executor(output)
    result = {'passed': False, 'inputSha256': input_sha256, 'imageId': image_id, 'stages': {},
              'syntheticOnly': True, 'productionAccess': False, **meta['binding']}
    try:
        build.inspect_image(docker, image_id)
        for name in STAGES:
            identifier = build.must(docker(container_args(image_id, bundle, output, name, sha(raw))),
                                    'container create failed').decode().strip()
            need(len(identifier) == 64 and all(c in '0123456789abcdef' for c in identifier), 'invalid container id')
            try:
                execution = docker(['start', '--attach', identifier], timeout=360)
                value = policy.json_value(build.must(execution, 'phase failed: ' + name))
                if name == 'verify':
                    need(value.get('verified') is True and value.get('uid') == 10001, 'runtime verification failed')
                result['stages'][name] = value
            finally:
                build.must(docker(['rm', '--force', identifier]), 'owned container cleanup failed')
        need(len(result['stages']) == len(STAGES) and verify(bundle, input_sha256)[1] == meta,
             'incomplete or changed input')
        result['passed'] = True
    except Exception as error:
        result['errorType'] = type(error).__name__; result['error'] = str(error)
    finally:
        result['completedAt'] = datetime.now(timezone.utc).isoformat()
        result['proofHashes'] = build.tree_hashes(output / 'proof')
        result['commands'] = docker.records
        policy.write_new(output / 'result.json', encoded(result))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); commands = parser.add_subparsers(dest='action', required=True)
    for name, options in {'prepare': ('repo', 'commit', 'output-dir'), 'verify': ('bundle', 'input-sha256'),
                          'run': ('bundle', 'input-sha256', 'image-id', 'output-dir')}.items():
        sub = commands.add_parser(name)
        for option in options:
            sub.add_argument('--' + option, required=True)
    args = vars(parser.parse_args(argv)); action = args.pop('action')
    result = ({'prepare': prepare, 'run': run}[action](**args) if action != 'verify' else {'verified': bool(verify(**args))})
    print(json.dumps(result)); return 1 if result.get('passed') is False else 0


if __name__ == '__main__':
    raise SystemExit(main())
