"""Build and verify one immutable membership source package; never deploy.

Only explicit clean Git commits, complete Expo evidence and new output paths
are accepted. No application import, dependency install, Docker or network call.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import gzip
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tarfile

PARENT_IMAGE = 'sha256:09f583b81f5782ceebc008995665fe095ac6ef0822302bc9b5d84ab3aa3f42f2'
OLD_MANIFEST = 'db3a984f570d38b88c62cb040181f3b4f9d812ace04193ac21c509f899c4c246'
PREFIX = 'static/experience/'
MAX_FILE, MAX_TOTAL, MAX_FILES = 32_000_000, 180_000_000, 2500
SELF = 'deploy/membership_release_package.py'
EXPORT_TYPES = {'.js', '.css', '.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg', '.ico', '.avif', '.ttf', '.otf', '.woff', '.woff2'}
FIXED = {
    'deploy/prepare_release.py': '03853e656b900c3785efe540fd62e12c97e193c3125f0bea45582870d9cc035a',
    'deploy/git_blobs.py': 'c71a4e60e65b45581899d0e2347f2e510bdc37fd508559155db1df8d3c3cd89b',
    'Dockerfile': 'c20a41d40bc99fac5910e109a56d4e6c431b8d92c7ea3fc5b30363417de86798',
    'compose.yaml': '803c3c1551f2ccb1f285a8d578dbeab7ea4e53102e1cbb64d9a69d6c4d30dad1',
    'requirements.txt': 'e4889fb55a301f74cd120e71da2d711ed0de7036ca5149d55a12ece6763993f5',
    'deploy/nginx.conf': 'c22066f070f5eeb80ddae0cd9d8973642148f7c3e324af46ce78e702c385dde9',
    '.dockerignore': '5e71e26fba840933477c1451bbeb1a3dd9492ef2c382b6ce241fae9e092d0383',
    'frontend/package.json': '0245a08c3b009150fa48b38c0b842162a7c541a3f1f6e60c2c46c9648b999c7f',
    'frontend/package-lock.json': 'bf87db5dbbbe14d227ff0098b0b629fa6842206345b83da5f3f218405920d91b',
}
FOLLOWUP_DOCKER_SHA256 = '6ed4fa73f1bdc7f0c1b0c2d660610434648dadb44890abb4d493fe46b6e904ff'
INVENTORY_COPY_BEFORE = b'COPY inventory_core.py inventory_api.py ./\n'
INVENTORY_COPY_AFTER = b'COPY inventory_core.py inventory_api.py inventory_sources.py ./\n'


def need(ok, message):
    if not ok:
        raise ValueError(message)


def baseline_values(baseline=None):
    # Explicit audited callers only; defaults keep the original migration contract.
    if baseline is None:
        return 'membership-release-package', PARENT_IMAGE, OLD_MANIFEST
    if baseline == 'expo-trip-tasks-r1-shopping-schedule':
        from deploy import build_shopping_schedule_release as shopping
        return shopping.KIND, shopping.PARENT_IMAGE, shopping.OLD_MANIFEST
    if baseline == 'assistant-trip-items-r1-expo-task-publish':
        from deploy import build_expo_trip_task_publish_release as tasks
        return tasks.KIND, tasks.PARENT_IMAGE, tasks.OLD_MANIFEST
    if baseline == 'journey-routes-r1-assistant-trip-items':
        from deploy import assistant_trip_items_release_profile as items
        return items.KIND, items.PARENT_IMAGE, items.OLD_MANIFEST
    if baseline == 'finance-query-r2-journey-routes':
        from deploy import build_journey_routes_release as routes
        return routes.KIND, routes.PARENT_IMAGE, routes.OLD_MANIFEST
    if baseline == 'assistant-trip-change-r1-finance-query':
        from deploy import assistant_finance_query_release_profile as finance_query
        return finance_query.KIND, finance_query.PARENT_IMAGE, finance_query.OLD_MANIFEST
    if baseline == 'finance-analysis-r1-assistant-trip-change':
        from deploy import assistant_trip_change_release_profile as assistant
        return assistant.KIND, assistant.PARENT_IMAGE, assistant.OLD_MANIFEST
    if baseline == 'order-inventory-r1-finance-analysis':
        from deploy import finance_analysis_release_profile as analysis
        return analysis.KIND, analysis.PARENT_IMAGE, analysis.OLD_MANIFEST
    if baseline == 'memberships-r3-steady':
        return ('steady-release-package',
                'sha256:c8e3da47800e3d11f609677bd6aca5f69aef6e7d7a49827c04fb6bea29946771',
                'c89f045dbf6456b7dcd50c8c340dea09d60a020765735ba7f27ad6e80e383e54')
    if baseline == 'shopping-r1-steady':
        return ('steady-release-package',
                'sha256:3ebb0a10eaf3aac44c5646478f25d49b85a66d9130007286ac869274e99b6c68',
                '910b4ab67459d47dd77ec32fbb986fe298e71c24baf75c39c334ebc4db89fb1e')
    need(baseline == 'followup-r1-steady', 'unsupported release baseline')
    return ('steady-release-package',
            'sha256:8e7092a44ba311f6ac333500cfab2c6dcf5137484cf02d9aca1f52590963815c',
            'd926bba0c7fc7374f8b0c0d6b661f51b5a0a15029428bfa016e92b750ddbd85c')


def fixed_files(baseline=None):
    baseline_values(baseline)
    if baseline == 'expo-trip-tasks-r1-shopping-schedule':
        from deploy import build_shopping_schedule_release as shopping
        return {**FIXED, 'Dockerfile': shopping.DOCKER_AFTER}
    if baseline == 'assistant-trip-items-r1-expo-task-publish':
        from deploy import build_expo_trip_task_publish_release as tasks
        return {**FIXED, 'Dockerfile': tasks.DOCKER_AFTER}
    if baseline == 'journey-routes-r1-assistant-trip-items':
        from deploy import assistant_trip_items_release_profile as items
        return {**FIXED, 'Dockerfile': items.DOCKER_AFTER}
    if baseline == 'finance-query-r2-journey-routes':
        from deploy import build_journey_routes_release as routes
        return {**FIXED, 'Dockerfile': routes.DOCKER_AFTER}
    if baseline == 'assistant-trip-change-r1-finance-query':
        from deploy import assistant_finance_query_release_profile as finance_query
        return {**FIXED, 'Dockerfile': finance_query.DOCKER_AFTER}
    if baseline == 'finance-analysis-r1-assistant-trip-change':
        from deploy import assistant_trip_change_release_profile as assistant
        return {**FIXED, 'Dockerfile': assistant.DOCKER_AFTER}
    if baseline == 'order-inventory-r1-finance-analysis':
        from deploy import finance_analysis_release_profile as analysis
        return {**FIXED, 'Dockerfile': analysis.DOCKER_AFTER}
    return {**FIXED, **({'Dockerfile': FOLLOWUP_DOCKER_SHA256} if baseline == 'followup-r1-steady' else {})}


def baseline_kwargs(baseline):
    baseline_values(baseline)
    return {} if baseline is None else {'baseline': baseline}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def checksum(value, length=64):
    need(isinstance(value, str) and re.fullmatch('[a-f0-9]{%d}' % length, value), 'invalid checksum')
    return value


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def json_value(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            need(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=unique)
    need(isinstance(value, dict), 'JSON object required')
    return value


def readable(path):
    path = Path(path).absolute()
    if os.name == 'nt' and not str(path).startswith('\\\\?\\'):
        path = Path('\\\\?\\' + str(path))
    return path


def checked(path, directory=False):
    path = Path(path)
    need(path.is_absolute() and '..' not in path.parts, 'canonical absolute path required')
    path = readable(path)
    for item in (path, *path.parents):
        info = item.lstat()
        need(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 1024,
             'linked/reparse input forbidden')
    need(path.is_dir() if directory else path.is_file(), 'missing regular input')
    return path


def plain(path, maximum=MAX_FILE):
    path = checked(path)
    need(path.stat().st_size <= maximum, 'input size exceeded')
    with path.open('rb') as stream:
        raw = stream.read(maximum + 1)
    need(len(raw) <= maximum, 'input grew beyond limit')
    return raw


def source_name(name, exported=False):
    need(isinstance(name, str) and 0 < len(name) <= 600, 'invalid relative path')
    p = PurePosixPath(name)
    need(not p.is_absolute() and p.as_posix() == name and '\\' not in name and ':' not in name
         and all(31 < ord(c) != 127 for c in name)
         and all(x not in ('', '.', '..') and not x.endswith((' ', '.')) for x in p.parts), 'unsafe relative path')
    need(not any(x.lower().startswith('.env') or x.lower() in ('.git', '__pycache__', 'test-results', 'data', 'private')
                 or (x.lower() == 'node_modules' and not exported) for x in p.parts)
         and not any(x in name.lower() for x in ('.sqlite', 'credentials'))
         and p.suffix.lower() not in ('.pyc', '.pyo', '.db', '.pem', '.key', '.p12'), 'private/runtime path forbidden')
    need(not any(re.fullmatch(r'(?:con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\..*)?', x, re.I) for x in p.parts), 'reserved path')
    return name


def names_unique(names):
    need(len(names) == len(set(names)) == len({n.casefold() for n in names}), 'duplicate/case-colliding paths')


def hash_map(value, exported=False):
    need(isinstance(value, dict) and value, 'nonempty file map required')
    names_unique(list(value))
    for name, sha in value.items():
        source_name(name, exported); checksum(sha)
    return value


def git(repo, *args):
    return subprocess.check_output(['git', '--no-replace-objects', '--no-optional-locks', *args], cwd=repo,
        env=dict(os.environ, GIT_NO_LAZY_FETCH='1', GIT_TERMINAL_PROMPT='0'), stderr=subprocess.PIPE, timeout=60)


def identity(repo, commit):
    checksum(commit, 40); checked(repo, True)
    need(git(repo, 'rev-parse', 'HEAD').decode().strip() == commit, 'HEAD differs from explicit commit')
    need(not git(repo, 'status', '--porcelain=v1', '--untracked-files=all').strip(), 'source tree is dirty')
    return git(repo, 'rev-parse', commit + '^{tree}').decode().strip()


def tracked_files(repo, commit):
    checksum(commit, 40)
    result = []
    for row in git(repo, 'ls-tree', '-rz', '--full-tree', commit).split(b'\0'):
        if not row:
            continue
        properties, name = row.split(b'\t', 1)
        mode, kind, _oid = properties.split()
        need(mode in (b'100644', b'100755') and kind == b'blob', 'tracked links/submodules forbidden')
        result.append(source_name(name.decode('utf-8')))
    names_unique(result)
    return set(result)


def required_build_inputs(tracked_paths):
    """All tracked frontend inputs except the three explicit non-build files."""
    return {n for n in tracked_paths if n.startswith('frontend/')
            and n not in {'frontend/README.md', 'frontend/LICENSE', 'frontend/.gitignore'}}


def selected_sources(tracked, policy, *, baseline=None):
    baseline_values(baseline)
    constants = {}
    for node in ast.parse(policy).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ('FILES', 'FOLDERS'):
                    need(target.id not in constants, 'repeated packaging constant')
                    constants[target.id] = ast.literal_eval(node.value)
    need(set(constants) == {'FILES', 'FOLDERS'}, 'packaging constants missing')
    need(all(isinstance(v, list) and all(isinstance(n, str) for n in v) for v in constants.values()), 'invalid allowlist')
    need(set(constants['FOLDERS']) == {'static', 'deploy', 'docs', 'tests'}, 'allowlist directories changed')
    required = set(constants['FILES']) | {SELF} | {'frontend/' + n for n in
        ('package.json', 'package-lock.json', 'app.json', 'tsconfig.json', 'README.md', 'LICENSE',
         'tests/journeySegments.test.ts', 'tsconfig.tests.json', 'typecheck.mjs')}
    if baseline == 'expo-trip-tasks-r1-shopping-schedule':
        from deploy import build_shopping_schedule_release as shopping
        required |= shopping.RUNTIME_ADDITIONS | shopping.FRONTEND_TESTS | {
            'deploy/build_shopping_schedule_release.py', 'deploy/activate_shopping_schedule_release.py'}
    if baseline == 'assistant-trip-items-r1-expo-task-publish':
        from deploy import build_expo_trip_task_publish_release as tasks
        required |= tasks.RUNTIME_ADDITIONS | {'deploy/build_expo_trip_task_publish_release.py',
            'deploy/activate_expo_trip_task_publish_release.py', 'frontend/tests/taskPublish.test.mjs'}
    if baseline == 'journey-routes-r1-assistant-trip-items':
        from deploy import assistant_trip_items_release_profile as items
        required |= items.RUNTIME_ADDITIONS | {'deploy/assistant_trip_items_release_' + part + '.py'
            for part in ('profile', 'package', 'controller', 'data', 'plan')}
    if baseline == 'finance-query-r2-journey-routes':
        from deploy import build_journey_routes_release as routes
        required |= routes.RUNTIME_ADDITIONS | {'deploy/build_journey_routes_release.py',
            'deploy/check_journey_routes_migration.py', 'deploy/activate_journey_routes_release.py'}
    if baseline == 'assistant-trip-change-r1-finance-query':
        from deploy import assistant_finance_query_release_profile as finance_query
        required |= finance_query.RUNTIME_ADDITIONS | {'deploy/assistant_finance_query_release_profile.py'}
    if baseline == 'finance-analysis-r1-assistant-trip-change':
        from deploy import assistant_trip_change_release_profile as assistant
        required |= assistant.RUNTIME_ADDITIONS | {'deploy/assistant_trip_change_release_profile.py'}
    if baseline == 'order-inventory-r1-finance-analysis':
        from deploy import finance_analysis_release_profile as analysis
        required |= analysis.RUNTIME_ADDITIONS | {'deploy/finance_analysis_release_profile.py'}
    if baseline == 'followup-r1-steady':
        required.add('inventory_sources.py')
    need(required <= tracked, 'allowlisted file missing from Git')
    need(not any(n.startswith(PREFIX) for n in tracked), 'generated exports must not be tracked')
    selected = required | {n for n in tracked if n.startswith(tuple(f + '/' for f in constants['FOLDERS'])
                                                             + ('frontend/src/', 'frontend/public/'))}
    selected |= tracked & {'frontend/tests/inventoryFollowup.test.mjs'}
    if baseline == 'assistant-trip-items-r1-expo-task-publish':
        selected |= tracked & tasks.FRONTEND_TESTS
    if baseline == 'followup-r1-steady':
        selected |= tracked & {'frontend/tests/inventorySources.test.mjs'}
    if baseline == 'order-inventory-r1-finance-analysis':
        selected |= tracked & analysis.FRONTEND_TESTS
    if baseline == 'finance-analysis-r1-assistant-trip-change':
        selected |= tracked & assistant.FRONTEND_TESTS
    if baseline == 'assistant-trip-change-r1-finance-query':
        selected |= tracked & finance_query.FRONTEND_TESTS
    if baseline == 'finance-query-r2-journey-routes':
        selected |= tracked & routes.FRONTEND_TESTS
    if baseline == 'journey-routes-r1-assistant-trip-items':
        selected |= tracked & items.FRONTEND_TESTS
    need(required_build_inputs(tracked) <= selected, 'new frontend input needs an explicit packaging policy')
    return selected


def export_blobs(directory, *, baseline=None):
    directory = checked(directory, True)
    result = {}
    for folder, dirs, files in os.walk(directory):
        for name in dirs:
            checked(Path(folder) / name, True)
        for name in files:
            path = Path(folder) / name
            relative = source_name(path.relative_to(directory).as_posix(), True)
            result[relative] = plain(path)
    validate_export_names(result, baseline=baseline)
    return result


def validate_export_names(names, *, baseline=None):
    names_unique(list(names))
    need(all(n in ('index.html', 'metadata.json') or PurePosixPath(n).suffix.lower() in EXPORT_TYPES for n in names),
         'unexpected export extension')
    if baseline in ('order-inventory-r1-finance-analysis', 'finance-analysis-r1-assistant-trip-change',
                    'assistant-trip-change-r1-finance-query', 'finance-query-r2-journey-routes',
                    'journey-routes-r1-assistant-trip-items', 'assistant-trip-items-r1-expo-task-publish',
                    'expo-trip-tasks-r1-shopping-schedule'):
        from deploy import finance_analysis_release_profile as analysis
        need(3 <= len(names) <= MAX_FILES and 'index.html' in names and 'metadata.json' in names,
             'complete bounded export required')
    else:
        need(len(names) == 23 and 'index.html' in names and 'metadata.json' in names,
             'complete 23-file export required')
    need(sum(n.startswith('_expo/static/js/web/entry-') and n.endswith('.js') for n in names) == 1,
         'exactly one Expo entry required')


def runtime_files(files):
    return {n: h for n, h in files.items() if n.startswith('static/') or n == 'requirements.txt'
            or n.endswith('.py') and '/' not in n}


def validate_maps(metadata, manifest, evidence, *, baseline=None):
    kind, parent, old_manifest = baseline_values(baseline)
    fixed = fixed_files(baseline)
    files = hash_map(manifest['files'], True)
    source = hash_map(metadata['sourceFiles'])
    exports = hash_map(metadata['exportFiles'], True)
    validate_export_names(exports, baseline=baseline)
    need(not any(n.startswith(PREFIX) for n in source), 'source/export overlap')
    need(files == {**source, **{PREFIX + n: h for n, h in exports.items()}}, 'manifest partition differs')
    need(metadata['runtimeFiles'] == runtime_files(files), 'runtime partition differs')
    if baseline == 'expo-trip-tasks-r1-shopping-schedule':
        from deploy import build_shopping_schedule_release as shopping
        non_expo = {n: h for n, h in metadata['runtimeFiles'].items() if not n.startswith(PREFIX)}
        preserved = {n: h for n, h in non_expo.items() if n not in shopping.CHANGED_RUNTIME_FILES}
        need(len(non_expo) == shopping.NON_EXPO_RUNTIME_COUNT
             and shopping.CHANGED_RUNTIME_FILES <= non_expo.keys()
             and len(preserved) == shopping.PRESERVED_RUNTIME_COUNT
             and digest(encoded(preserved)) == shopping.PRESERVED_RUNTIME_SHA256,
             'shopping non-Expo runtime differs from installed 99-file preservation baseline')
    if baseline == 'assistant-trip-items-r1-expo-task-publish':
        from deploy import build_expo_trip_task_publish_release as tasks
        preserved = {n: h for n, h in metadata['runtimeFiles'].items() if not n.startswith(PREFIX)}
        need(len(preserved) == tasks.NON_EXPO_RUNTIME_COUNT
             and digest(encoded(preserved)) == tasks.NON_EXPO_RUNTIME_SHA256,
             'UI-only non-Expo runtime differs from installed 104-file baseline')
    need(metadata['fixedFiles'] == fixed and all(source.get(n) == h for n, h in fixed.items()), 'dependency/config pin differs')
    need(metadata['kind'] == kind and metadata['parentImage'] == parent
         and metadata['oldManifestSha256'] == old_manifest, 'installed parent differs')
    need(evidence.get('schemaVersion') == 1 and evidence.get('kind') == 'membership-expo-build'
         and type(evidence.get('buildExit')) is int and evidence['buildExit'] == 0 and evidence.get('bundleMarkers') is True,
         'successful explicit build evidence required')
    checksum(evidence['head'], 40); checksum(evidence['tree'], 40)
    inputs = hash_map(evidence['inputFiles'])
    need(set(inputs) == required_build_inputs(source) and all(source[n] == h for n, h in inputs.items()),
         'build input set/bytes differs')
    need(hash_map(evidence['files'], True) == exports, 'export evidence differs')
    need(metadata['inputFiles'] == inputs and metadata['buildSourceHead'] == evidence['head']
         and metadata['buildSourceTree'] == evidence['tree'], 'input provenance differs')
    checksum(metadata['sourceHead'], 40); checksum(metadata['tree'], 40)


def inspect_inputs(repo, commit, export_dir, build_evidence, evidence_sha256, *, baseline=None):
    """Re-read live files and fixed Git blobs; return payload and provenance."""
    kind, parent, old_manifest = baseline_values(baseline)
    repo = Path(repo).absolute()
    tree = identity(repo, commit)
    tracked = tracked_files(repo, commit)
    policy = git(repo, 'show', commit + ':deploy/prepare_release.py')
    reader = git(repo, 'show', commit + ':deploy/git_blobs.py')
    need(digest(policy) == FIXED['deploy/prepare_release.py'] and digest(reader) == FIXED['deploy/git_blobs.py'],
         'packaging policy/reader changed')
    namespace = {'__name__': 'fixed_package_blob_reader'}
    exec(compile(reader, 'fixed_git_blobs.py', 'exec'), namespace)
    selected = selected_sources(tracked, policy, **baseline_kwargs(baseline))
    blobs = namespace['read_git_blobs'](repo, commit, sorted(selected))
    need(all(len(raw) <= MAX_FILE and plain(repo / name) == raw for name, raw in blobs.items()), 'working source differs from Git')
    need(blobs[SELF] == plain(Path(__file__).absolute()), 'executed packager differs from candidate')
    raw_evidence = plain(build_evidence, 2_000_000)
    need(digest(raw_evidence) == checksum(evidence_sha256), 'build evidence hash differs')
    evidence = json_value(raw_evidence)
    build_head = checksum(evidence['head'], 40)
    need(git(repo, 'rev-parse', build_head + '^{tree}').decode().strip() == evidence['tree'], 'build commit/tree differs')
    inputs = required_build_inputs(tracked)
    need(inputs == required_build_inputs(tracked_files(repo, build_head)) == set(evidence['inputFiles']), 'build input set incomplete')
    built = namespace['read_git_blobs'](repo, build_head, sorted(inputs))
    need(all(digest(built[n]) == evidence['inputFiles'][n] == digest(blobs[n]) for n in inputs), 'build source bytes differ')
    generated = export_blobs(export_dir, baseline=baseline)
    source_hashes = {n: digest(v) for n, v in blobs.items()}
    export_hashes = {n: digest(v) for n, v in generated.items()}
    blobs.update({PREFIX + n: v for n, v in generated.items()})
    need(len(blobs) <= MAX_FILES and sum(map(len, blobs.values())) <= MAX_TOTAL, 'package limits exceeded')
    files = {n: digest(v) for n, v in blobs.items()}
    metadata = dict(schemaVersion=1, kind=kind, sourceHead=commit, tree=tree,
        sourceFiles=source_hashes, exportFiles=export_hashes, runtimeFiles=runtime_files(files), fixedFiles=fixed_files(baseline),
        inputFiles=evidence['inputFiles'], buildSourceHead=build_head, buildSourceTree=evidence['tree'],
        buildEvidenceSha256=evidence_sha256, packagerSha256=digest(blobs[SELF]), parentImage=parent,
        oldManifestSha256=old_manifest, productionOperations=False)
    manifest = {'files': files, 'sourceHead': commit, 'tree': tree,
                'excluded': ['credentials', 'runtime databases', 'private finance imports', 'test-results']}
    validate_maps(metadata, manifest, evidence, **baseline_kwargs(baseline))
    need(identity(repo, commit) == tree, 'source moved while inspecting')
    return blobs, manifest, metadata, raw_evidence


def write_new(path, raw):
    with Path(path).open('xb') as stream:
        stream.write(raw)
    Path(path).chmod(0o600)


def make_archive(path, blobs, manifest_raw):
    with Path(path).open('xb') as target, gzip.GzipFile(filename='', mode='wb', fileobj=target, mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode='w', format=tarfile.PAX_FORMAT) as archive:
            for name, raw in sorted({**blobs, 'RELEASE-MANIFEST.json': manifest_raw}.items()):
                info = tarfile.TarInfo(name)
                info.size = len(raw)
                info.mode = 0o755 if name.startswith('deploy/') and name.endswith('.sh') else 0o644
                archive.addfile(info, BytesIO(raw))
    Path(path).chmod(0o600)


def verify_package(output_dir, package_sha256, *, baseline=None):
    """Return verified {metadata, manifest, blobs}; never extract or mutate."""
    kind, _, _ = baseline_values(baseline)
    output = checked(output_dir, True)
    need(set(os.listdir(output)) == {'release.tar.gz', 'release-manifest.json', 'build-evidence.json', 'package.json'},
         'unexpected package directory contents')
    raw = plain(output / 'package.json', 2_000_000)
    need(digest(raw) == checksum(package_sha256), 'package metadata hash differs')
    metadata = json_value(raw)
    need(metadata.get('schemaVersion') == 1 and metadata.get('kind') == kind
         and metadata.get('productionOperations') is False, 'package contract differs')
    manifest_raw = plain(output / 'release-manifest.json', 2_000_000)
    need(digest(manifest_raw) == metadata['manifestSha256'], 'manifest hash differs')
    manifest = json_value(manifest_raw)
    evidence_raw = plain(output / 'build-evidence.json', 2_000_000)
    need(digest(evidence_raw) == metadata['buildEvidenceSha256'], 'packaged build evidence differs')
    validate_maps(metadata, manifest, json_value(evidence_raw), **baseline_kwargs(baseline))
    need(manifest['sourceHead'] == metadata['sourceHead'] and manifest['tree'] == metadata['tree'], 'manifest identity differs')
    compressed = plain(output / 'release.tar.gz', MAX_TOTAL)
    need(digest(compressed) == metadata['archiveSha256'], 'archive hash differs')
    with gzip.GzipFile(fileobj=BytesIO(compressed)) as gz:
        tar_raw = gz.read(MAX_TOTAL + 4_000_001)
    need(len(tar_raw) <= MAX_TOTAL + 4_000_000, 'expanded archive exceeds limit')
    blobs, total = {}, 0
    with tarfile.open(fileobj=BytesIO(tar_raw), mode='r:') as archive:
        for item in archive:
            name = source_name(item.name, item.name.startswith(PREFIX))
            need(item.isfile() and not item.issparse() and not item.linkname
                 and set(item.pax_headers) <= {'path'}, 'nonregular archive member')
            need(name not in blobs and len(blobs) <= MAX_FILES and 0 <= item.size <= MAX_FILE, 'duplicate/oversized archive member')
            need(item.mode == (0o755 if name.startswith('deploy/') and name.endswith('.sh') else 0o644)
                 and item.uid == item.gid == item.mtime == 0, 'unexpected archive metadata')
            total += item.size
            need(total <= MAX_TOTAL + 2_000_000, 'archive payload exceeds limit')
            blobs[name] = archive.extractfile(item).read(MAX_FILE + 1)
            need(len(blobs[name]) == item.size, 'truncated archive member')
        need(not any(tar_raw[archive.offset:]), 'unexpected trailing tar content')
    names_unique(list(blobs))
    need(blobs.pop('RELEASE-MANIFEST.json', None) == manifest_raw, 'embedded manifest differs')
    need({n: digest(v) for n, v in blobs.items()} == manifest['files'], 'archive contents differ from whitelist')
    need(digest(blobs[SELF]) == metadata['packagerSha256'] == digest(plain(Path(__file__).absolute())), 'packager identity differs')
    need(selected_sources(set(metadata['sourceFiles']), blobs['deploy/prepare_release.py'], **baseline_kwargs(baseline))
         == set(metadata['sourceFiles']), 'source outside original allowlist')
    return {'metadata': metadata, 'manifest': manifest, 'blobs': blobs}


def prepare(repo, commit, export_dir, build_evidence, evidence_sha256, output_dir, *, baseline=None):
    output = Path(output_dir).absolute()
    need('..' not in output.parts, 'canonical output required')
    checked(output.parent, True)
    need(not output.exists() and not output.is_symlink(), 'output must be new; keep prior attempts')
    need(not output.is_relative_to(Path(repo).absolute()) and not output.is_relative_to(Path(export_dir).absolute()),
         'output must be outside source/export')
    inputs = (repo, commit, export_dir, build_evidence, evidence_sha256)
    blobs, manifest, metadata, raw_evidence = inspect_inputs(*inputs, **baseline_kwargs(baseline))
    manifest['createdAt'] = datetime.now(timezone.utc).isoformat()
    manifest_raw = encoded(manifest)
    output.mkdir(mode=0o700)
    write_new(output / 'release-manifest.json', manifest_raw)
    write_new(output / 'build-evidence.json', raw_evidence)
    make_archive(output / 'release.tar.gz', blobs, manifest_raw)
    repeated = inspect_inputs(*inputs, **baseline_kwargs(baseline))
    need(repeated[0] == blobs and repeated[2] == metadata and repeated[3] == raw_evidence, 'inputs changed during packaging')
    metadata.update(archiveSha256=digest(plain(output / 'release.tar.gz', MAX_TOTAL)), manifestSha256=digest(manifest_raw))
    package_raw = encoded(metadata)
    write_new(output / 'package.json', package_raw)
    verify_package(output, digest(package_raw), **baseline_kwargs(baseline))
    return {'outputDirectory': str(output), 'packageSha256': digest(package_raw),
            'archiveSha256': metadata['archiveSha256'], 'manifestSha256': metadata['manifestSha256'],
            'sourceHead': commit, 'tree': metadata['tree'], 'files': len(blobs), 'productionOperations': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    create = commands.add_parser('prepare')
    for field in ('repo', 'commit', 'export-dir', 'build-evidence', 'evidence-sha256', 'output-dir'):
        create.add_argument('--' + field, required=True)
    verify = commands.add_parser('verify')
    verify.add_argument('--output-dir', required=True)
    verify.add_argument('--package-sha256', required=True)
    args = vars(parser.parse_args())
    action = args.pop('action')
    if action == 'prepare':
        value = prepare(**args)
    else:
        value = verify_package(**args)
        value = {'verified': True, 'files': len(value['blobs']), 'sourceHead': value['metadata']['sourceHead']}
    print(json.dumps(value, ensure_ascii=False))


if __name__ == '__main__':
    main()
