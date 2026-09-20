"""Closed video source package and two disjoint build contexts; no Docker/network.

This is a new policy, not an override of any historic release profile.
"""
from datetime import datetime, timezone
import gzip
from io import BytesIO
import os
from pathlib import Path
import tarfile

from deploy import membership_release_package as common
from deploy.git_blobs import read_git_blobs

need, sha, encoded = common.need, common.digest, common.encoded
SELF = 'deploy/media_video_release_package.py'
BUILDER = 'deploy/build_media_video_release.py'
KIND = 'media-video-dual-image-package-v1'
BASE = 'db3786666d293c9a473f519766fa4112816f2b04'
BASE_TREE = '57939f9ebab4d52766a7b15032279a7d5989904a'
BASE_MAP_SHA = '4d6db69a743fc9f51a726e647d037373e1d2e51719a87e5cc0bdd660fb06018b'
BUILD_BASE = 'dfeaf22cf2e5a5bb87564f861418c1d847c9e830'
BUILD_TREE = '1846590b38f09452042022dfebe4f5ce847171a4'
BUILD_DELTA_SHA = '6b43a896e62c8fc609d2e107991fa7009d66aa6dea294fadd8d23a47458ba16f'
ADDITIONS = frozenset({SELF, BUILDER, 'tests/test_media_video_release_package.py', 'docs/MEDIA-VIDEO-RELEASE.md'})
DECODER_RECIPE = 'deploy/Dockerfile.media-video-service'
DECODER_MODULES = frozenset({'media_video_service.py', 'media_video_transport.py', 'media_videos.py', 'media_images.py'})
SUPPLEMENTAL = frozenset({'tests/test_expo_journey_brief.mjs', 'tests/test_expo_trips.mjs',
    'tests/test_expo_assistant_journey_entry.mjs', 'tests/test_app.py', 'tests/test_journey_workflows.py',
    'tests/test_expo_photos.mjs', 'tests/test_expo_journey_documents.mjs', 'tests/test_expo_calendar.mjs', 'deploy/git_blobs.py'})
PINS = {
    'Dockerfile': '593d5562448d525942f69004eb9ba6be6aa1be263ba809d9a110879abbbec5b6',
    'compose.yaml': '677afc31a129ec955630bef0cdf124d476be2c0d6b939a77b2bb8472f6a0215f',
    DECODER_RECIPE: 'da0ec9958d0d63259e328fd2cab0ba0610b1049b362ae1584f89d7591d23f046',
    'requirements.txt': 'e4889fb55a301f74cd120e71da2d711ed0de7036ca5149d55a12ece6763993f5',
    '.dockerignore': '5e71e26fba840933477c1451bbeb1a3dd9492ef2c382b6ce241fae9e092d0383',
    'deploy/git_blobs.py': 'c71a4e60e65b45581899d0e2347f2e510bdc37fd508559155db1df8d3c3cd89b',
    'deploy/membership_release_package.py': '6a534690ac925723394b25cc98f39ce2fa0e483a14685bc71190687fbd7cc885',
    'deploy/membership_release_build.py': '208419607fbc240f59b7bac59a2deaf84d9a09c2eeeb00e8ac30a6950c1849e2',
}


def hashes(blobs):
    return {n: sha(raw) for n, raw in sorted(blobs.items())}


def safe_names(names):
    common.names_unique(list(names))
    for name in names:
        common.source_name(name, name.startswith(common.PREFIX))
        need(not any(p.lower() in ('uploads', 'backups', '.venv', '.ssh') for p in name.split('/')),
             'private/runtime path forbidden')


def delta(before, after):
    return {n: {'before': before.get(n), 'after': after.get(n)} for n in sorted(before.keys() | after.keys())
            if before.get(n) != after.get(n)}


def contexts(blobs):
    """Parse COPY only after exact Docker pin; never include the full release context."""
    need(all(sha(blobs[n]) == h for n, h in PINS.items()), 'dependency/config pin differs')
    app = {'Dockerfile': blobs['Dockerfile'], '.dockerignore': blobs['.dockerignore']}
    for line in blobs['Dockerfile'].decode().splitlines():
        if line.startswith('COPY '):
            parts = line.split()[1:]
            need(parts[-1] in ('.', './', './static'), 'unexpected pinned COPY destination')
            for name in parts[:-1]:
                if name == 'static':
                    app.update({n: raw for n, raw in blobs.items() if n.startswith('static/')})
                else:
                    app[name] = blobs[name]
    decoder = {'Dockerfile': blobs[DECODER_RECIPE], **{n: blobs[n] for n in sorted(DECODER_MODULES)}}
    need(set(decoder) == {'Dockerfile'} | DECODER_MODULES, 'decoder context expanded')
    return {'app': app, 'decoder': decoder}


def evidence_contract(evidence, source, exports, build_delta, commit, tree):
    need(evidence.get('schemaVersion') == 1 and evidence.get('kind') == 'membership-expo-build'
         and evidence.get('feature') == 'expo-media-video' and type(evidence.get('buildExit')) is int
         and evidence['buildExit'] == 0 and evidence.get('bundleMarkers') is True
         and evidence.get('ambientExpoPublicVariables') is False and evidence.get('dotenvDisabled') is True,
         'successful isolated Expo build required')
    head = common.checksum(evidence['head'], 40)
    need((head == commit and evidence['tree'] == tree and not build_delta) or
         (head == BUILD_BASE and evidence['tree'] == BUILD_TREE and sha(encoded(build_delta)) == BUILD_DELTA_SHA),
         'build source outside exact reviewed reuse boundary')
    need(evidence.get('sourceHead') == head and evidence.get('sourceTree') == evidence['tree'], 'build identity differs')
    inputs = common.hash_map(evidence['inputFiles'])
    need(set(inputs) == common.required_build_inputs(source) and all(source[n] == h for n, h in inputs.items()),
         'complete frontend input bytes differ')
    supplemental = common.hash_map(evidence['supplementalTestInputs'])
    need(set(supplemental) == SUPPLEMENTAL and all(source.get(n) == h for n, h in supplemental.items()),
         'supplemental build input differs')
    need(common.hash_map(evidence['files'], True) == exports, 'export evidence differs')
    commands, executions = evidence.get('commands'), evidence.get('executions')
    need(isinstance(commands, list) and len(commands) == 5 and isinstance(executions, list)
         and len(executions) == 5, 'five explicit build stages required')
    for command, execution in zip(commands, executions):
        need(isinstance(command, list) and command and all(isinstance(x, str) for x in command)
             and execution.get('argv') == command and type(execution.get('exitCode')) is int
             and execution['exitCode'] == 0, 'failed or partial Expo stage')
        common.checksum(execution['stdoutSha256']); common.checksum(execution['stderrSha256'])
    need('ci' in commands[0] and '--include=dev' in commands[0] and
         'tsconfig.json' in commands[1] and 'tsconfig.tests.json' in commands[2] and
         '--test' in commands[3] and all(x in commands[4] for x in ('export', '--platform', 'web')),
         'build stage selection differs')


def validate(metadata, manifest, evidence, blobs):
    need(metadata.get('kind') == KIND and metadata.get('schemaVersion') == 1
         and metadata.get('productionOperations') is False, 'package contract differs')
    common.checksum(metadata['sourceHead'], 40); common.checksum(metadata['tree'], 40)
    source, baseline, exports = (common.hash_map(metadata[k], k == 'exportFiles')
                                  for k in ('sourceFiles', 'baselineFiles', 'exportFiles'))
    safe_names(source)
    need(sha(encoded(baseline)) == BASE_MAP_SHA and metadata['baselineHead'] == BASE
         and metadata['baselineTree'] == BASE_TREE, 'frozen source baseline differs')
    need(set(source) == set(baseline) | ADDITIONS and all(source[n] == h for n, h in baseline.items()),
         'candidate differs outside four release files')
    need(not any(n.startswith(common.PREFIX) for n in source), 'source/export overlap')
    common.validate_export_names(exports)
    need(manifest['files'] == {**source, **{common.PREFIX + n: h for n, h in exports.items()}}
         == hashes(blobs), 'archive partition differs')
    need(manifest['sourceHead'] == metadata['sourceHead'] and manifest['tree'] == metadata['tree'], 'manifest identity differs')
    need(metadata['pins'] == PINS and all(source.get(n) == h for n, h in PINS.items()), 'dependency/config pin differs')
    evidence_contract(evidence, source, exports, metadata['buildDelta'], metadata['sourceHead'], metadata['tree'])
    need(metadata['buildSourceHead'] == evidence['head'] and metadata['buildSourceTree'] == evidence['tree'],
         'build provenance differs')
    expected = {role: hashes(files) for role, files in contexts(blobs).items()}
    need(metadata['contexts'] == expected, 'image context partition differs')
    need(blobs[SELF] == common.plain(Path(__file__).absolute()), 'executed packager differs from package')
    need(len(blobs) <= common.MAX_FILES and sum(map(len, blobs.values())) <= common.MAX_TOTAL,
         'package limits exceeded')


def inspect_inputs(repo, commit, export_dir, build_evidence, evidence_sha256):
    repo = Path(repo).absolute(); tree = common.identity(repo, commit)
    tracked = common.tracked_files(repo, commit); safe_names(tracked)
    blobs = read_git_blobs(repo, commit, sorted(tracked))
    need(all(common.plain(repo / n) == raw for n, raw in blobs.items()), 'working source differs from Git')
    baseline = hashes(read_git_blobs(repo, BASE, sorted(common.tracked_files(repo, BASE))))
    need(common.git(repo, 'rev-parse', BASE + '^{tree}').decode().strip() == BASE_TREE, 'baseline tree differs')
    raw = common.plain(build_evidence, 2_000_000)
    need(sha(raw) == common.checksum(evidence_sha256), 'build evidence hash differs')
    evidence = common.json_value(raw); build_head = common.checksum(evidence['head'], 40)
    need(common.git(repo, 'rev-parse', build_head + '^{tree}').decode().strip() == evidence['tree'], 'build Git tree differs')
    built = hashes(read_git_blobs(repo, build_head, sorted(common.tracked_files(repo, build_head))))
    source = hashes(blobs)
    if build_head == commit:
        build_delta = {}
    else:
        need(build_head == BUILD_BASE, 'unreviewed build ancestor')
        build_delta = delta(built, baseline)
    build_inputs = {**evidence['inputFiles'], **evidence['supplementalTestInputs']}
    need(all(built.get(n) == h for n, h in build_inputs.items()) and
         common.required_build_inputs(built) == common.required_build_inputs(source), 'built inputs differ from Git')
    generated = common.export_blobs(export_dir)
    meta = dict(schemaVersion=1, kind=KIND, sourceHead=commit, tree=tree, baselineHead=BASE, baselineTree=BASE_TREE,
                baselineFiles=baseline, sourceFiles=source, exportFiles=hashes(generated), pins=PINS,
                buildSourceHead=build_head, buildSourceTree=evidence['tree'], buildDelta=build_delta,
                buildEvidenceSha256=evidence_sha256, productionOperations=False)
    blobs.update({common.PREFIX + n: raw for n, raw in generated.items()})
    meta['contexts'] = {role: hashes(files) for role, files in contexts(blobs).items()}
    manifest = dict(sourceHead=commit, tree=tree, files=hashes(blobs))
    validate(meta, manifest, evidence, blobs)
    need(common.identity(repo, commit) == tree, 'source changed during inspection')
    return blobs, manifest, meta, raw


def read_archive(raw):
    """Bounded read only; never extract untrusted archive paths to disk."""
    with gzip.GzipFile(fileobj=BytesIO(raw)) as gz:
        expanded = gz.read(common.MAX_TOTAL + 4_000_001)
    need(len(expanded) <= common.MAX_TOTAL + 4_000_000, 'expanded archive exceeds limit')
    blobs, total = {}, 0
    with tarfile.open(fileobj=BytesIO(expanded), mode='r:') as archive:
        for item in archive:
            safe_names([item.name])
            need(item.isfile() and not item.issparse() and not item.linkname and set(item.pax_headers) <= {'path'},
                 'nonregular archive member')
            need(item.name not in blobs and len(blobs) <= common.MAX_FILES and 0 <= item.size <= common.MAX_FILE,
                 'duplicate/oversized archive member')
            need(item.mode == (0o755 if item.name.startswith('deploy/') and item.name.endswith('.sh') else 0o644)
                 and item.uid == item.gid == item.mtime == 0, 'unexpected archive metadata')
            total += item.size; need(total <= common.MAX_TOTAL + 2_000_000, 'archive payload exceeds limit')
            blobs[item.name] = archive.extractfile(item).read(common.MAX_FILE + 1)
            need(len(blobs[item.name]) == item.size, 'truncated archive member')
        need(not any(expanded[archive.offset:]), 'unexpected trailing tar content')
    common.names_unique(list(blobs))
    return blobs


def verify_package(output_dir, package_sha256):
    output = common.checked(Path(output_dir).absolute(), True)
    need(set(os.listdir(output)) == {'release.tar.gz', 'release-manifest.json', 'build-evidence.json', 'package.json'},
         'unexpected package contents')
    raw = common.plain(output / 'package.json', 2_000_000)
    need(sha(raw) == common.checksum(package_sha256), 'package hash differs')
    meta = common.json_value(raw)
    manifest_raw = common.plain(output / 'release-manifest.json', 2_000_000)
    evidence_raw = common.plain(output / 'build-evidence.json', 2_000_000)
    archive = common.plain(output / 'release.tar.gz', common.MAX_TOTAL)
    need(sha(manifest_raw) == meta['manifestSha256'] and sha(evidence_raw) == meta['buildEvidenceSha256']
         and sha(archive) == meta['archiveSha256'], 'package member hash differs')
    blobs = read_archive(archive)
    need(blobs.pop('RELEASE-MANIFEST.json', None) == manifest_raw, 'embedded manifest differs')
    manifest = common.json_value(manifest_raw)
    validate(meta, manifest, common.json_value(evidence_raw), blobs)
    return dict(metadata=meta, manifest=manifest, blobs=blobs)


def prepare(repo, commit, export_dir, build_evidence, evidence_sha256, output_dir):
    output = Path(output_dir).absolute()
    common.checked(output.parent, True)
    need('..' not in output.parts and not output.exists() and not output.is_symlink(), 'new output required')
    need(not any(output.is_relative_to(Path(p).absolute()) or Path(p).absolute().is_relative_to(output)
                 for p in (repo, export_dir, build_evidence)), 'output overlaps input')
    args = (repo, commit, export_dir, build_evidence, evidence_sha256)
    blobs, manifest, meta, raw_evidence = inspect_inputs(*args)
    output.mkdir(mode=0o700)
    manifest_raw = encoded(manifest)
    common.write_new(output / 'release-manifest.json', manifest_raw)
    common.write_new(output / 'build-evidence.json', raw_evidence)
    common.make_archive(output / 'release.tar.gz', blobs, manifest_raw)
    need(inspect_inputs(*args) == (blobs, manifest, meta, raw_evidence), 'inputs changed during packaging')
    meta.update(manifestSha256=sha(manifest_raw), archiveSha256=sha(common.plain(output / 'release.tar.gz', common.MAX_TOTAL)),
                createdAt=datetime.now(timezone.utc).isoformat())
    package_raw = encoded(meta); common.write_new(output / 'package.json', package_raw)
    verify_package(output, sha(package_raw))
    return dict(packageSha256=sha(package_raw), archiveSha256=meta['archiveSha256'],
                manifestSha256=meta['manifestSha256'], sourceHead=commit, tree=meta['tree'], productionOperations=False)
