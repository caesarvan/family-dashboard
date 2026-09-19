"""Real temporary Git/tar/filesystem checks; no app, Docker or network."""
import ast
from io import BytesIO
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

import pytest

from deploy import membership_release_package as package

ROOT = Path(__file__).resolve().parents[1]


def git(repo, *args):
    return subprocess.check_output(['git', '--no-replace-objects', *args], cwd=repo, stderr=subprocess.PIPE).decode().strip()


def write(root, name, raw):
    p = package.readable(root / name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(raw)


def commit(repo):
    git(repo, 'add', '--all')
    git(repo, 'commit', '-qm', 'synthetic fixture')
    return git(repo, 'rev-parse', 'HEAD')


def historical_fixed_blob(name):
    raw = (ROOT / name).read_bytes()
    if name == 'Dockerfile':
        # Reconstruct only the audited COPY addition, then assert the original
        # immutable digest. Keep this fixture runnable without repository Git.
        raw = raw.replace(package.INVENTORY_COPY_AFTER, package.INVENTORY_COPY_BEFORE)
    assert package.digest(raw) == package.FIXED[name]
    return raw


@pytest.fixture
def environment(tmp_path):
    repo, export = tmp_path / 'repo', tmp_path / 'export'
    repo.mkdir(); export.mkdir()
    git(repo, 'init', '-q')
    git(repo, 'config', 'user.email', 'synthetic@example.invalid')
    git(repo, 'config', 'user.name', 'Synthetic Package Fixture')
    git(repo, 'config', 'core.autocrlf', 'false')
    policy = (ROOT / 'deploy/prepare_release.py').read_bytes()
    names = next(ast.literal_eval(n.value) for n in ast.parse(policy).body if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == 'FILES' for t in n.targets))
    names += [package.SELF, 'tests/test_synthetic.py', 'docs/SYNTHETIC.md', 'static/index.html',
              'frontend/src/index.ts', 'frontend/public/home.svg']
    names += ['frontend/' + n for n in ('package.json', 'package-lock.json', 'app.json', 'tsconfig.json',
              'README.md', 'LICENSE', 'tests/journeySegments.test.ts', 'tsconfig.tests.json', 'typecheck.mjs')]
    for name in names:
        raw = historical_fixed_blob(name) if name in package.FIXED else (
            (ROOT / name).read_bytes() if name == package.SELF else b'synthetic fixture\n')
        write(repo, name, raw)
    for name, digest in package.FIXED.items():
        write(repo, name, historical_fixed_blob(name))
        assert package.digest((repo / name).read_bytes()) == digest
    head = commit(repo)
    exports = {'index.html': b'<script src="/_expo/static/js/web/entry-synthetic.js"></script>',
               'metadata.json': b'{"synthetic":true}', '_expo/static/js/web/entry-synthetic.js': b'// synthetic export'}
    exports.update({f'assets/image-{i}.png': b'synthetic-image-' + str(i).encode() for i in range(20)})
    for name, raw in exports.items():
        write(export, name, raw)
    tracked = package.tracked_files(repo, head)
    evidence = {'schemaVersion': 1, 'kind': 'membership-expo-build', 'head': head,
                'tree': git(repo, 'rev-parse', 'HEAD^{tree}'), 'buildExit': 0, 'bundleMarkers': True,
                'inputFiles': {n: package.digest((repo / n).read_bytes()) for n in package.required_build_inputs(tracked)},
                'files': {n: package.digest(v) for n, v in exports.items()}}
    record = tmp_path / 'build.json'
    record.write_bytes(package.encoded(evidence))
    return {'repo': repo, 'commit': head, 'export_dir': export, 'build_evidence': record,
            'evidence_sha256': package.digest(record.read_bytes()), 'output_dir': tmp_path / 'package'}


def evidence_update(env, change):
    value = json.loads(env['build_evidence'].read_text())
    change(value)
    env['build_evidence'].write_bytes(package.encoded(value))
    env['evidence_sha256'] = package.digest(env['build_evidence'].read_bytes())


def test_roundtrip_complete_partitions_and_exclusive_output(environment):
    env = environment
    result = package.prepare(**env)
    checked = package.verify_package(env['output_dir'], result['packageSha256'])
    meta = checked['metadata']
    assert len(meta['exportFiles']) == 23 and meta['sourceHead'] == env['commit']
    assert meta['parentImage'] == package.PARENT_IMAGE and meta['oldManifestSha256'] == package.OLD_MANIFEST
    assert meta['runtimeFiles'] == package.runtime_files(checked['manifest']['files'])
    assert checked['blobs']['app.py'] == b'synthetic fixture\n'
    assert not any('node_modules' in n for n in meta['sourceFiles'])
    with pytest.raises(ValueError, match='output must be new'):
        package.prepare(**env)
    assert not git(env['repo'], 'status', '--porcelain')


@pytest.mark.parametrize('change', [
    lambda v: v['inputFiles'].pop('frontend/src/index.ts'),
    lambda v: v['inputFiles'].__setitem__('frontend/src/index.ts', 'a' * 64),
    lambda v: v['files'].pop('assets/image-0.png'),
    lambda v: v.__setitem__('tree', 'a' * 40),
    lambda v: v.__setitem__('buildExit', 1),
    lambda v: v.__setitem__('buildExit', False),
])
def test_bad_build_evidence_is_rejected_before_output(environment, change):
    evidence_update(environment, change)
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        package.prepare(**environment)
    assert not environment['output_dir'].exists()


def test_missing_or_extra_export_is_not_silently_omitted(environment):
    (environment['export_dir'] / 'assets/image-0.png').unlink()
    with pytest.raises(ValueError, match='23-file'):
        package.prepare(**environment)
    write(environment['export_dir'], 'assets/secret.map', b'synthetic private source map')
    with pytest.raises(ValueError, match='extension'):
        package.prepare(**environment)


def test_git_source_and_pinned_configuration_drift(environment):
    env = environment
    write(env['repo'], 'app.py', b'changed working source')
    with pytest.raises(ValueError, match='dirty'):
        package.prepare(**env)
    write(env['repo'], 'app.py', b'synthetic fixture\n')
    write(env['repo'], 'Dockerfile', b'FROM unsafe:latest\n')
    env['commit'] = commit(env['repo'])
    with pytest.raises(ValueError, match='dependency/config pin'):
        package.prepare(**env)


def test_test_only_commit_can_reuse_exact_build_inputs(environment):
    env = environment
    old = env['commit']
    write(env['repo'], 'tests/test_added.py', b'# synthetic test-only change\n')
    env['commit'] = commit(env['repo'])
    result = package.prepare(**env)
    value = package.verify_package(env['output_dir'], result['packageSha256'])
    assert value['metadata']['buildSourceHead'] == old != value['metadata']['sourceHead']
    assert 'tests/test_added.py' in value['blobs']


@pytest.mark.parametrize('name', ['docs/.env.secret', 'tests/runtime.sqlite3', 'tests/test-results/private.json'])
def test_tracked_private_files_refused(environment, name):
    write(environment['repo'], name, b'synthetic forbidden file')
    environment['commit'] = commit(environment['repo'])
    with pytest.raises(ValueError, match='private/runtime'):
        package.prepare(**environment)


def test_linked_export_refused(environment):
    env = environment
    target = env['export_dir'] / 'assets/image-0.png'
    target.unlink()
    try:
        target.symlink_to(env['repo'] / 'app.py')
    except OSError:
        pytest.skip('Platform cannot create a symlink in the temporary fixture')
    with pytest.raises(ValueError, match='linked/reparse'):
        package.prepare(**env)


def test_windows_length_export_is_in_complete_manifest(environment):
    env = environment
    old = env['export_dir'] / 'assets/image-0.png'
    content = old.read_bytes(); old.unlink()
    name = 'assets/' + ('nested-' * 18) + '/' + ('image-' * 18) + '.png'
    write(env['export_dir'], name, content)
    evidence_update(env, lambda v: v['files'].__setitem__(name, v['files'].pop('assets/image-0.png')))
    result = package.prepare(**env)
    checked = package.verify_package(env['output_dir'], result['packageSha256'])
    assert checked['blobs'][package.PREFIX + name] == content
    assert len(checked['metadata']['exportFiles']) == 23


@pytest.mark.parametrize('attack', ['duplicate', 'traversal', 'symlink', 'oversize', 'extra', 'trailing'])
def test_resigned_malicious_archive_never_extracts(environment, attack):
    env = environment
    package.prepare(**env)
    archive_path = env['output_dir'] / 'release.tar.gz'
    with tarfile.open(archive_path) as archive:
        members = [(m, archive.extractfile(m).read()) for m in archive]
    with tarfile.open(archive_path, 'w:gz') as archive:
        for m, raw in members:
            archive.addfile(m, BytesIO(raw))
        item = tarfile.TarInfo('app.py' if attack == 'duplicate' else '../escape' if attack == 'traversal' else 'extra.txt')
        item.mode = 0o644
        if attack == 'symlink':
            item.type = tarfile.SYMTYPE; item.linkname = '../../escape'
        elif attack == 'oversize':
            item.size = package.MAX_FILE + 1
            # tar header says too large; its body intentionally remains absent.
            archive.fileobj.write(item.tobuf()); archive.offset += 512
        if attack not in ('oversize', 'trailing'):
            archive.addfile(item, BytesIO(b''))
    if attack == 'trailing':
        with archive_path.open('ab') as stream:
            stream.write(gzip.compress(b'nonzero unreviewed trailer'))
    metadata_path = env['output_dir'] / 'package.json'
    metadata = json.loads(metadata_path.read_text())
    metadata['archiveSha256'] = package.digest(archive_path.read_bytes())
    metadata_path.write_bytes(package.encoded(metadata))
    with pytest.raises((ValueError, tarfile.TarError)):
        package.verify_package(env['output_dir'], package.digest(metadata_path.read_bytes()))
    assert not (env['output_dir'].parent / 'escape').exists()


def test_source_race_leaves_unsealed_attempt(environment, monkeypatch):
    original = package.make_archive
    def changed(path, blobs, manifest):
        original(path, blobs, manifest)
        write(environment['repo'], 'app.py', b'changed during archive creation')
    monkeypatch.setattr(package, 'make_archive', changed)
    with pytest.raises(ValueError, match='dirty'):
        package.prepare(**environment)
    assert (environment['output_dir'] / 'release.tar.gz').is_file()
    assert not (environment['output_dir'] / 'package.json').exists()


def test_duplicate_json_and_wrong_external_hash(environment):
    env = environment
    env['build_evidence'].write_bytes(b'{"head":"a","head":"b"}')
    env['evidence_sha256'] = package.digest(env['build_evidence'].read_bytes())
    with pytest.raises(ValueError, match='duplicate JSON'):
        package.prepare(**env)
    env['evidence_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='evidence hash'):
        package.prepare(**env)
