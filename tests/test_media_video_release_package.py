"""Real temporary Git/archive policy and recording Docker boundaries; no daemon/network."""
import gzip
from io import BytesIO
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

import pytest

from deploy import media_video_release_package as package
from deploy import build_media_video_release as build

ROOT = Path(__file__).resolve().parents[1]
COMMON = package.common
APP = 'sha256:' + 'a' * 64
DECODER = 'sha256:' + 'b' * 64
CONTAINER = 'c' * 64


def git(root, *args):
    return COMMON.git(root, *args).decode().strip()


def write(root, name, raw):
    path = COMMON.readable(root / name)
    path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)


def commit(root):
    git(root, 'add', '--all'); git(root, '-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid',
                                'commit', '-qm', 'synthetic release fixture')
    return git(root, 'rev-parse', 'HEAD')


def clone(source, target, head):
    # Local object reuse only; no fetch, remote transport, shared working files or refs.
    git(source, 'clone', '--quiet', '--shared', '--no-checkout', str(source), str(target))
    git(target, 'config', 'core.autocrlf', 'false'); git(target, 'config', 'core.longpaths', 'true')
    git(target, 'checkout', '--quiet', '--detach', head)


@pytest.fixture(scope='module')
def reference(tmp_path_factory):
    root = tmp_path_factory.mktemp('video-package'); repo = root / 'repo'; export = root / 'export'; export.mkdir()
    clone(ROOT, repo, package.BASE)
    for name in package.ADDITIONS:
        write(repo, name, (ROOT / name).read_bytes())
    head = commit(repo)
    tracked = COMMON.tracked_files(repo, head)
    exports = {'index.html': b'<script src="/_expo/static/js/web/entry-synthetic.js"></script>',
               'metadata.json': b'{"synthetic":true}', '_expo/static/js/web/entry-synthetic.js': b'// synthetic policy fixture'}
    exports.update({f'assets/image-{n}.png': b'synthetic-' + str(n).encode() for n in range(20)})
    for name, raw in exports.items(): write(export, name, raw)
    commands = [['node', 'npm-cli.js', 'ci', '--include=dev'], ['node', 'tsc', '-p', 'tsconfig.json'],
                ['node', 'tsc', '-p', 'tsconfig.tests.json'], ['node', '--test', 'tests/memberVideo.test.mjs'],
                ['node', 'expo', 'export', '--platform', 'web']]
    evidence = dict(schemaVersion=1, kind='membership-expo-build', feature='expo-media-video',
        head=package.BUILD_BASE, tree=package.BUILD_TREE, sourceHead=package.BUILD_BASE, sourceTree=package.BUILD_TREE,
        buildExit=0, bundleMarkers=True, ambientExpoPublicVariables=False, dotenvDisabled=True,
        inputFiles={n: package.sha(COMMON.plain(repo / n)) for n in COMMON.required_build_inputs(tracked)},
        supplementalTestInputs={n: package.sha(COMMON.plain(repo / n)) for n in package.SUPPLEMENTAL},
        files=package.hashes(exports), commands=commands,
        executions=[dict(argv=c, exitCode=0, stdoutSha256='1' * 64, stderrSha256='2' * 64) for c in commands])
    record = root / 'synthetic-build.json'; record.write_bytes(package.encoded(evidence))
    env = dict(repo=repo, commit=head, export_dir=export, build_evidence=record,
               evidence_sha256=package.sha(record.read_bytes()), output_dir=root / 'package')
    result = package.prepare(**env)
    return root, env, result


def copy_package(reference, tmp_path):
    _, env, result = reference
    output = tmp_path / 'package'; shutil.copytree(env['output_dir'], output)
    return output, result['packageSha256']


def resign(output):
    record = COMMON.json_value((output / 'package.json').read_bytes())
    record['archiveSha256'] = package.sha((output / 'release.tar.gz').read_bytes())
    raw = package.encoded(record); (output / 'package.json').write_bytes(raw)
    return package.sha(raw)


def test_closed_package_and_minimal_separate_contexts(reference):
    _, env, result = reference
    value = package.verify_package(env['output_dir'], result['packageSha256'])
    meta = value['metadata']; contexts = package.contexts(value['blobs'])
    assert len(meta['sourceFiles']) == 1080 and len(meta['exportFiles']) == 23
    assert meta['buildSourceHead'] == package.BUILD_BASE != meta['sourceHead']
    assert len(meta['buildDelta']) == 8
    assert set(contexts['decoder']) == {'Dockerfile'} | package.DECODER_MODULES
    assert 'media_video_service.py' not in contexts['app']
    assert 'media_video_transport.py' in contexts['app']
    assert not any(n.startswith(('docs/', 'tests/', 'frontend/')) or n == 'compose.yaml' for n in contexts['app'])
    assert {n.removeprefix(COMMON.PREFIX): package.sha(raw) for n, raw in contexts['app'].items()
            if n.startswith(COMMON.PREFIX)} == meta['exportFiles']
    with pytest.raises(ValueError, match='new output'):
        package.prepare(**env)


@pytest.mark.parametrize('field,value', [('buildExit', 1), ('buildExit', False), ('dotenvDisabled', False),
                                      ('ambientExpoPublicVariables', True), ('tree', 'f' * 40)])
def test_incomplete_build_evidence_refused_before_output(reference, tmp_path, field, value):
    _, env, _ = reference; evidence = COMMON.json_value(env['build_evidence'].read_bytes()); evidence[field] = value
    path = tmp_path / 'bad.json'; path.write_bytes(package.encoded(evidence)); output = tmp_path / 'out'
    with pytest.raises(ValueError):
        package.prepare(**{**env, 'build_evidence': path, 'evidence_sha256': package.sha(path.read_bytes()), 'output_dir': output})
    assert not output.exists()


@pytest.mark.parametrize('fault', ['input', 'supplemental', 'stage', 'ancestor'])
def test_build_input_and_reuse_boundaries(reference, tmp_path, fault):
    _, env, _ = reference; evidence = COMMON.json_value(env['build_evidence'].read_bytes())
    if fault == 'input': evidence['inputFiles'].pop(next(iter(evidence['inputFiles'])))
    elif fault == 'supplemental': evidence['supplementalTestInputs'].pop(next(iter(evidence['supplementalTestInputs'])))
    elif fault == 'stage': evidence['executions'][2]['exitCode'] = 1
    else:
        evidence['head'] = package.BASE; evidence['tree'] = package.BASE_TREE
        evidence['sourceHead'] = package.BASE; evidence['sourceTree'] = package.BASE_TREE
    path = tmp_path / 'bad.json'; path.write_bytes(package.encoded(evidence))
    with pytest.raises(ValueError):
        package.prepare(**{**env, 'build_evidence': path, 'evidence_sha256': package.sha(path.read_bytes()),
                           'output_dir': tmp_path / 'out'})
    assert not (tmp_path / 'out').exists()


@pytest.mark.parametrize('name', ['app.py', 'compose.yaml', 'frontend/src/lib/photos.ts', 'docs/.env.secret',
                                'tests/runtime.sqlite3', 'tests/test-results/private.json', 'uploads/photo.jpg'])
def test_unreviewed_source_and_private_paths_are_not_packaged(reference, tmp_path, name):
    _, env, _ = reference; repo = tmp_path / 'repo'; clone(env['repo'], repo, env['commit'])
    write(repo, name, b'synthetic forbidden drift\n')
    git(repo, 'add', '--force', '--', name); head = commit(repo)
    with pytest.raises(ValueError):
        package.prepare(**{**env, 'repo': repo, 'commit': head, 'output_dir': tmp_path / 'out'})
    assert not (tmp_path / 'out').exists()


def test_dirty_source_and_export_tamper(reference, tmp_path):
    _, env, _ = reference; repo = tmp_path / 'repo'; clone(env['repo'], repo, env['commit'])
    write(repo, 'app.py', b'dirty')
    with pytest.raises(ValueError, match='dirty'):
        package.prepare(**{**env, 'repo': repo, 'output_dir': tmp_path / 'out'})
    export = tmp_path / 'export'; shutil.copytree(env['export_dir'], export)
    write(export, 'assets/image-0.png', b'changed')
    with pytest.raises(ValueError, match='export evidence'):
        package.prepare(**{**env, 'export_dir': export, 'output_dir': tmp_path / 'out'})


@pytest.mark.parametrize('attack', ['duplicate', 'traversal', 'symlink', 'extra', 'trailing'])
def test_resigned_archive_attacks_are_rejected_without_extraction(reference, tmp_path, attack):
    output, _ = copy_package(reference, tmp_path); path = output / 'release.tar.gz'
    with tarfile.open(path) as archive:
        originals = [(m, archive.extractfile(m).read()) for m in archive]
    with tarfile.open(path, 'w:gz') as archive:
        for member, raw in originals: archive.addfile(member, BytesIO(raw))
        if attack != 'trailing':
            item = tarfile.TarInfo('app.py' if attack == 'duplicate' else '../escape' if attack == 'traversal' else 'extra.txt')
            item.mode = 0o644
            if attack == 'symlink': item.type = tarfile.SYMTYPE; item.linkname = '../../escape'
            archive.addfile(item, BytesIO(b''))
    if attack == 'trailing':
        with path.open('ab') as stream: stream.write(gzip.compress(b'nonzero trailer'))
    with pytest.raises(ValueError): package.verify_package(output, resign(output))
    assert not (tmp_path / 'escape').exists()


def test_resigned_context_expansion_rejected(reference, tmp_path):
    output, _ = copy_package(reference, tmp_path); path = output / 'package.json'
    meta = COMMON.json_value(path.read_bytes()); meta['contexts']['decoder']['app.py'] = meta['sourceFiles']['app.py']
    path.write_bytes(package.encoded(meta))
    with pytest.raises(ValueError, match='context partition'):
        package.verify_package(output, package.sha(path.read_bytes()))


class Docker:
    """Recording stand-in only: no real image/runtime success claim."""
    def __init__(self, value, fault=None):
        self.value, self.fault, self.calls, self.role = value, fault, [], None

    def __call__(self, args, *, cwd=None, timeout=120):
        self.calls.append(args); raw = b''; code = 0
        if args[0] == 'build':
            self.role = cwd.parent.name
            assert '--pull=false' in args and '--network=default' in args and not any(x in args for x in ('-t', '--tag'))
            assert common_hashes(cwd) == self.value['metadata']['contexts'][self.role]
            Path(args[args.index('--iidfile') + 1]).write_text(APP if self.role == 'app' else DECODER)
            if self.fault == self.role + '-build': code = 1
            if self.fault == 'floating' and self.role == 'decoder':
                Path(args[args.index('--iidfile') + 1]).write_text('candidate:latest')
            if self.fault == 'same-image' and self.role == 'decoder':
                Path(args[args.index('--iidfile') + 1]).write_text(APP)
        elif args[:2] == ['image', 'inspect']:
            role = 'app' if args[-1] == APP else 'decoder'
            # Match exact frozen recipe; changing user must still fail.
            config = {'User': 'dashboard' if role == 'app' else '10001:10001',
                      'WorkingDir': '/app' if role == 'app' else '/decoder',
                      'Entrypoint': None if role == 'app' else ['python','-B','/decoder/media_video_service.py']}
            recipe = self.value['blobs']['Dockerfile' if role == 'app' else package.DECODER_RECIPE].decode()
            config['Cmd'] = json.loads(next(line[4:] for line in recipe.splitlines() if line.startswith('CMD ')))
            if self.fault == 'config' and role == 'decoder': config['User'] = 'root'
            raw = json.dumps([{'Id': args[-1], 'Config': config}]).encode()
        elif args[0] == 'create':
            assert args[args.index('--network') + 1] == 'none' and '--read-only' in args
            assert '--mount' not in args and '--env' not in args and '--cap-drop' in args
            raw = CONTAINER.encode()
        elif args[0] == 'start':
            files = build.runtime_map(self.role, self.value['metadata']['contexts'][self.role])
            value = {'uid':10001, 'files': dict(files)}
            if self.role == 'decoder':
                value.update(pillow='12.3.0', ffmpegPackage=build.FFMPEG_PACKAGE,
                             tools={n:{'sha256':'1'*64,'version':n+' version 7.1.5'} for n in ('ffmpeg','ffprobe')})
                if self.fault == 'runtime': value['files']['unreviewed.py'] = '0' * 64
                if self.fault == 'toolchain': value['ffmpegPackage'] = 'unreviewed'
            raw = json.dumps(value).encode()
        elif args[0] == 'rm': assert args == ['rm', '--force', CONTAINER]
        else: raise AssertionError(args)
        return subprocess.CompletedProcess(args, code, raw, b'')


def common_hashes(root):
    return build.common.tree_hashes(root)


def test_dual_build_records_and_offline_reverification(reference, tmp_path):
    _, env, result = reference; value = package.verify_package(env['output_dir'], result['packageSha256'])
    docker = Docker(value); output = tmp_path / 'build'
    record = build.build(env['output_dir'], result['packageSha256'], output, runner=docker)
    assert record['allPassed'] and record['images'] == {'app': APP, 'decoder': DECODER}
    digest = package.sha((output / 'build.json').read_bytes())
    assert build.verify_build(output, digest, env['output_dir'], result['packageSha256']) == record
    assert len([c for c in docker.calls if c[0] == 'build']) == 2
    assert not any(c[0] in ('compose', 'push', 'tag') for c in docker.calls)
    with pytest.raises(ValueError, match='new output'):
        build.build(env['output_dir'], result['packageSha256'], output, runner=docker)
    (output / 'decoder/build.json').unlink()
    with pytest.raises((OSError, ValueError)):
        build.verify_build(output, digest, env['output_dir'], result['packageSha256'])


@pytest.mark.parametrize('fault', ['app-build','decoder-build','floating','same-image','config','runtime','toolchain'])
def test_partial_or_invalid_image_pair_never_creates_overall_success(reference, tmp_path, fault):
    _, env, result = reference; value = package.verify_package(env['output_dir'], result['packageSha256'])
    docker = Docker(value, fault); output = tmp_path / 'build'
    with pytest.raises(ValueError):
        build.build(env['output_dir'], result['packageSha256'], output, runner=docker)
    assert not (output / 'build.json').exists() and (output / 'failed.json').exists()
    failed = COMMON.json_value((output / 'failed.json').read_bytes())
    if fault == 'app-build':
        assert failed['completedRoles'] == [] and not (output / 'decoder').exists()
    else:
        assert failed['completedRoles'] == ['app']
        assert COMMON.json_value((output / 'app/build.json').read_bytes())['successful'] is True
        assert COMMON.json_value((output / 'decoder/build.json').read_bytes())['successful'] is False


@pytest.mark.parametrize('fault', ['config', 'toolchain', 'output', 'image-id'])
def test_resigned_build_record_cannot_hide_invalid_runtime_or_changed_raw_output(reference, tmp_path, fault):
    _, env, result = reference; value = package.verify_package(env['output_dir'], result['packageSha256'])
    output = tmp_path / 'build'
    build.build(env['output_dir'], result['packageSha256'], output, runner=Docker(value))
    path = output / 'decoder/build.json'; record = COMMON.json_value(path.read_bytes())
    if fault == 'config': record['verification']['config']['User'] = 'root'
    elif fault == 'toolchain': record['verification']['runtime']['ffmpegPackage'] = 'unreviewed'
    elif fault == 'output': (output / 'decoder/stdout').write_bytes(b'changed after build')
    else: (output / 'decoder/image-id').write_text(APP)
    path.write_bytes(package.encoded(record))
    overall = output / 'build.json'; receipt = COMMON.json_value(overall.read_bytes())
    receipt['builds']['decoder'] = package.sha(path.read_bytes()); overall.write_bytes(package.encoded(receipt))
    with pytest.raises(ValueError):
        build.verify_build(output, package.sha(overall.read_bytes()), env['output_dir'], result['packageSha256'])
