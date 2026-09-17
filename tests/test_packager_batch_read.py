"""Opt-in local tests against the hash-pinned account packager; no release actions.

Set PACKAGER_BATCH_PARENT to its private prepare-package.py for pytest. The CLI
compares complete inspect_inputs calls in a disposable Git checkout, never
prepare(), bind(), remote commands, or shared repository writes.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

import pytest

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy.packager_batch_read import READER_SHA256, transform_prepare

PARENT_SHA = 'b3db5b55d2fe26ec2596230ad4677176361e3545abece727838c6c51eddffc3a'
ROOT = Path(__file__).resolve().parents[1]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def parent_bytes(path):
    path = Path(path)
    assert path.is_absolute() and not path.is_symlink()
    raw = path.read_bytes()
    assert sha(raw) == PARENT_SHA, 'Not the reviewed immutable account packager'
    return raw


def namespace(raw):
    ns = {'__name__': 'packager_inspect_test', '__file__': '<checked-packager>'}
    exec(compile(raw, ns['__file__'], 'exec'), ns)
    return ns


@pytest.fixture(scope='session')
def parent():
    path = os.environ.get('PACKAGER_BATCH_PARENT')
    if not path:
        pytest.skip('Explicit private pinned packager required; no discovery or download')
    return parent_bytes(path)


def git(repo, *args, data=None):
    return subprocess.run(['git', '--no-replace-objects', '--no-optional-locks', '-C', str(repo), *args],
                          input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
                          env=dict(os.environ, GIT_NO_LAZY_FETCH='1', GIT_TERMINAL_PROMPT='0'), timeout=60).stdout


def initialize(repo):
    repo.mkdir()
    git(repo, 'init', '-b', 'main')
    git(repo, 'config', 'core.autocrlf', 'false')
    git(repo, 'config', 'user.name', 'Local synthetic test')
    git(repo, 'config', 'user.email', 'synthetic@example.invalid')


def commit(repo):
    git(repo, 'add', '--all')
    git(repo, 'commit', '-m', 'synthetic fixture')
    head = git(repo, 'rev-parse', 'HEAD').decode().strip()
    git(repo, 'update-ref', 'refs/heads/codex/integration', head)
    return dict(main=head, integration=head, tree=git(repo, 'rev-parse', 'HEAD^{tree}').decode().strip())


@pytest.fixture
def small_repo(tmp_path, parent):
    repo = tmp_path / 'repo'; initialize(repo)
    reader = (ROOT / 'deploy/git_blobs.py').read_bytes()
    assert sha(reader) == READER_SHA256
    (repo / 'deploy').mkdir()
    (repo / 'deploy/git_blobs.py').write_bytes(reader)
    (repo / 'data.txt').write_bytes(b'original\x00\xff\n')
    config = commit(repo)
    ns = namespace(transform_prepare(parent)); ns['REPO'] = repo
    return repo, config, ns


def test_transform_preserves_every_other_function_and_top_level_statement(parent):
    before = ast.parse(parent)
    after = ast.parse(transform_prepare(parent))
    exempt = {'git', 'git_identity', 'inspect_inputs', 'load_blob_reader'}
    def guards(tree):
        return [ast.dump(n) for n in tree.body
                if not (isinstance(n, ast.FunctionDef) and n.name in exempt)
                and not (isinstance(n, ast.Import) and n.names[0].name == 'os')]
    assert guards(before) == guards(after)
    # Both original complete inspections in prepare, and all outer freeze/output
    # readback guards remain byte-for-byte AST equal, not replaced by this helper.
    assert transform_prepare(parent.replace(b'\r\n', b'\n')) == transform_prepare(parent)
    with patch('subprocess.Popen', side_effect=AssertionError('pure transform ran process')):
        transform_prepare(parent)


@pytest.mark.parametrize('damage', ['twice', 'git', 'build', 'working', 'ancestry', 'duplicate', 'profile'])
def test_transform_rejects_unreviewed_shape(parent, damage):
    changes = {
        'git': (b"stderr=subprocess.PIPE)\n", b"stderr=None)\n"),
        'build': (b"for record in (evidence, tested):", b"for record in (evidence,):"),
        'working': (b"raw = git('show', head + ':' + name)", b"raw = b''"),
        'ancestry': (b"'merge-base', '--is-ancestor'", b"'merge-base', '--is-octopus'"),
        'profile': (b'FINANCE_ACCOUNTS_SCHEMA_SQL', b'OTHER_SCHEMA_SQL'),
    }
    damaged = parent.replace(b'\r\n', b'\n')
    if damage == 'twice': damaged = transform_prepare(damaged)
    elif damage == 'duplicate': damaged += b'\ndef tracked_files(head):\n    return set()\n'
    elif damage == 'profile': damaged = damaged.replace(*changes[damage])
    else: damaged = damaged.replace(*changes[damage], 1)
    with pytest.raises(ValueError): transform_prepare(damaged)


def test_bootstrap_is_immutable_and_hash_checked(small_repo):
    repo, config, ns = small_repo
    (repo / 'deploy/git_blobs.py').write_bytes(b'raise AssertionError("working import")\n')
    read = ns['load_blob_reader'](config['main'])
    assert read(repo, config['main'], ['data.txt']) == {'data.txt': b'original\x00\xff\n'}
    newer = commit(repo)
    with pytest.raises(RuntimeError, match='reader changed'):
        ns['load_blob_reader'](newer['main'])


@pytest.mark.parametrize('damage', ['dirty', 'main', 'integration', 'tree'])
def test_full_identity_guards_remain(small_repo, damage):
    repo, config, ns = small_repo
    ns['git_identity'](config)
    if damage == 'dirty': (repo / 'data.txt').write_bytes(b'dirty')
    else: config[damage] = '0' * 40
    with pytest.raises((RuntimeError, subprocess.CalledProcessError)):
        ns['git_identity'](config)


@pytest.mark.parametrize('name,mode', [('.env', '100644'), ('credentials.txt', '100644'),
                                      ('linked', '120000'), ('module', '160000')])
def test_tracked_policy_precedes_batch_reader(small_repo, name, mode):
    repo, config, ns = small_repo
    oid = config['main'] if mode == '160000' else git(repo, 'hash-object', '-w', '--stdin', data=b'target').decode().strip()
    git(repo, 'update-index', '--add', '--cacheinfo', mode, oid, name)
    git(repo, 'commit', '-m', 'unsafe synthetic tree')
    head = git(repo, 'rev-parse', 'HEAD').decode().strip()
    with pytest.raises(RuntimeError): ns['tracked_files'](head)


def test_replace_refs_do_not_change_guard_or_blob_identity(small_repo):
    repo, config, ns = small_repo
    (repo / 'data.txt').write_bytes(b'replacement')
    replacement = commit(repo)['main']
    # Only this disposable repository's refs/index/files are restored.
    git(repo, 'update-ref', 'refs/heads/main', config['main'])
    git(repo, 'update-ref', 'refs/heads/codex/integration', config['main'])
    git(repo, 'read-tree', config['main'])
    git(repo, 'checkout-index', '--all', '--force')
    git(repo, 'update-ref', 'refs/replace/' + config['main'], replacement)
    ns['git_identity'](config)
    read = ns['load_blob_reader'](config['main'])
    assert read(repo, config['main'], ['data.txt'])['data.txt'] == b'original\x00\xff\n'


@contextmanager
def inspect_only_processes():
    counts = Counter()
    original = subprocess.Popen
    allowed = {'branch', 'status', 'rev-parse', 'merge-base', 'ls-tree', 'show', 'cat-file'}
    def counted(args, *a, **kw):
        assert isinstance(args, list) and args[0] == 'git' and not kw.get('shell')
        rest = list(args[1:])
        while rest and rest[0].startswith('-'):
            opt = rest.pop(0)
            if opt == '-C': rest.pop(0)
            else: assert opt in {'--no-replace-objects', '--no-optional-locks'}
        assert rest and rest[0] in allowed, 'Inspection attempted a non-read Git command'
        counts[rest[0]] += 1
        return original(args, *a, **kw)
    with patch('subprocess.Popen', side_effect=counted), \
            patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')), \
            patch.object(socket, 'create_connection', side_effect=AssertionError('network forbidden')):
        yield counts


def frozen_files(config, parent_path):
    paths = [parent_path, parent_path.parent / 'generation.json',
             parent_path.parent / 'bind-release.py',
             *sorted((parent_path.parent / 'operators').glob('*.py')),
             Path(config['buildEvidencePath']), Path(config['testedBuildEvidencePath']),
             Path(config['oldArchivePath'])]
    paths.extend(p for p in Path(config['exportDirectory']).rglob('*') if p.is_file())
    return {str(p): sha(p.read_bytes()) for p in paths}


def benchmark(parent_path, freeze, source_repo, output):
    """Actual fixed bytes, exact private checkout, read-only inspection only."""
    output.mkdir(parents=True, exist_ok=False)
    raw = parent_bytes(parent_path)
    converted = transform_prepare(raw)
    config = json.loads(freeze.read_bytes())
    original, revised = namespace(raw), namespace(converted)
    before = frozen_files(config, parent_path)
    local_inputs = [freeze, ROOT / 'deploy/packager_batch_read.py', Path(__file__)]
    before.update({str(p): sha(p.read_bytes()) for p in local_inputs})
    report = dict(passed=False, packageExecuted=False, bindExecuted=False, networkCalls=0,
                  parentSha256=sha(raw), transformedSha256=sha(converted),
                  helperSha256=sha((ROOT / 'deploy/packager_batch_read.py').read_bytes()),
                  testSha256=sha(Path(__file__).read_bytes()), freezeSha256=sha(freeze.read_bytes()),
                  main=config['main'], integration=config['integration'], tree=config['tree'])
    (output / 'transformed-prepare.py').write_bytes(converted)
    try:
        with tempfile.TemporaryDirectory(prefix='packager-batch-inspect-') as temporary:
            scratch = Path(temporary); repo = scratch / 'repo'; initialize(repo)
            report['privateCheckout'] = str(repo)
            objects = Path(git(source_repo, 'rev-parse', '--path-format=absolute', '--git-common-dir').decode().strip()) / 'objects'
            assert objects.is_dir() and not objects.is_symlink()
            (repo / '.git/objects/info/alternates').write_bytes((objects.as_posix() + '\n').encode('utf-8'))
            git(repo, 'update-ref', 'refs/heads/main', config['main'])
            git(repo, 'update-ref', 'refs/heads/codex/integration', config['integration'])
            git(repo, 'read-tree', config['main'])
            git(repo, 'checkout-index', '--all')
            original['REPO'] = revised['REPO'] = repo
            contract = original['load_contract']()
            original['validate_config'](config); revised['validate_config'](config)
            results = []
            for name, ns in [('original', original), ('batch', revised), ('batchRepeat', revised)]:
                started = time.perf_counter()
                with inspect_only_processes() as counts:
                    result = ns['inspect_inputs'](config, contract)
                report[name] = dict(seconds=time.perf_counter() - started,
                                    gitProcesses=sum(counts.values()), commands=dict(counts))
                results.append(result)
            assert results[0] == results[1] == results[2], 'Full six-value inspect result changed'
            report['equalAllSixResults'] = True
            report['sourceAndExportCount'] = len(results[0][0])
            report['buildInputs'] = len(results[0][3]['inputFiles'])
            report['manifestSha256'] = sha(json.dumps(results[0][1], sort_keys=True).encode())
            assert report['batch']['gitProcesses'] < report['original']['gitProcesses']
            assert report['batchRepeat']['commands'] == report['batch']['commands'], 'Unexpected cross-call cache'
            report['rejections'] = []
            def reject(label, changed=config, changed_contract=contract):
                with inspect_only_processes():
                    try: revised['inspect_inputs'](changed, changed_contract)
                    except (RuntimeError, subprocess.CalledProcessError): pass
                    else: raise AssertionError('Inspection accepted ' + label)
                report['rejections'].append(label)
            # Each damage is in this disposable tree/inputs only, never in A.
            target = repo / 'app.py'; saved = target.read_bytes()
            target.write_bytes(saved + b'\n# changed during package readback\n')
            reject('working-source-drift'); target.write_bytes(saved)
            git(repo, 'update-ref', 'refs/heads/codex/integration', results[0][3]['sourceHead'])
            reject('integration-ref-drift')
            git(repo, 'update-ref', 'refs/heads/codex/integration', config['integration'])
            bad = dict(config, tree='0' * 40); reject('frozen-tree-drift', bad)
            private = scratch / 'private'; private.mkdir(); revised['A'] = private
            evidence = private / 'evidence.json'; evidence.write_bytes(results[0][2])
            cfg = dict(config, buildEvidencePath=str(evidence), testedBuildEvidencePath=str(evidence))
            evidence.write_bytes(results[0][2] + b'\n'); reject('build-evidence-drift', cfg)
            evidence.write_bytes(results[0][2])
            edited = json.loads(evidence.read_bytes()); edited['inputFiles'].pop('Dockerfile')
            evidence.write_text(json.dumps(edited), encoding='utf-8')
            cfg2 = dict(cfg, buildEvidenceSha256=sha(evidence.read_bytes()), testedBuildEvidenceSha256=sha(evidence.read_bytes()))
            reject('incomplete-build-input-set', cfg2)
            evidence.write_bytes(results[0][2])
            exports = private / 'dist'; exports.mkdir()
            for name in results[0][3]['files']:
                dst = exports / name; dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes((Path(config['exportDirectory']) / name).read_bytes())
            export = exports / next(iter(results[0][3]['files']))
            export.write_bytes(export.read_bytes() + b'\nchanged')
            reject('export-drift', dict(cfg, exportDirectory=str(exports)))
            old = private / 'old.tar.gz'; old.write_bytes(Path(config['oldArchivePath']).read_bytes() + b'changed')
            reject('old-archive-drift', dict(cfg, oldArchivePath=str(old)))
            reject('reviewed-delta-drift', dict(cfg, changedFiles=[]))
            reject('schema-hash-drift', dict(cfg, migrationSqlSha256='0' * 64))
            # Untracked private files cannot enter selected sources.
            (repo / 'test-results').mkdir(exist_ok=True)
            (repo / 'test-results/private.txt').write_text('synthetic only', encoding='utf-8')
            with inspect_only_processes():
                final = revised['inspect_inputs'](cfg, contract)
            assert final == results[0]
            report['ignoredPrivateFileExcluded'] = True
            report['privateSourceCleanAfter'] = not git(repo, 'status', '--porcelain')
            assert report['privateSourceCleanAfter']
        report['temporaryFixtureRemoved'] = not Path(report['privateCheckout']).exists()
        assert report['temporaryFixtureRemoved']
        report['passed'] = True
    except BaseException as exc:
        import traceback
        report['failure'] = traceback.format_exc()
        if isinstance(exc, subprocess.CalledProcessError):
            report['processError'] = (exc.stderr or b'').decode('utf-8', errors='replace')
        raise
    finally:
        if 'privateCheckout' in report:
            report['temporaryFixtureRemoved'] = not Path(report['privateCheckout']).exists()
        after = frozen_files(config, parent_path)
        after.update({str(p): sha(p.read_bytes()) for p in local_inputs})
        report['inputHashesBeforeAfter'] = dict(before=before, after=after, same=before == after)
        if before != after: report['passed'] = False
        (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    assert report['passed']
    print(json.dumps({key: report[key] for key in ('passed', 'original', 'batch', 'batchRepeat', 'sourceAndExportCount', 'buildInputs')}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent', type=Path, required=True)
    parser.add_argument('--freeze', type=Path, required=True)
    parser.add_argument('--source-repo', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    benchmark(args.parent.resolve(strict=True), args.freeze.resolve(strict=True),
              args.source_repo.resolve(strict=True), args.output.resolve())
