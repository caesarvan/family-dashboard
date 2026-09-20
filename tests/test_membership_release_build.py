"""Real local pytest/SQLite provenance checks plus a recording Docker stand-in.

No Docker daemon, cloud, production data or application is executed here.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from deploy import membership_release_build as build

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'sha256:' + 'a' * 64
CONTAINER = 'b' * 64


def write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


@pytest.fixture
def verified(tmp_path, monkeypatch):
    blobs = {'app.py': b'VALUE=7\n', 'static/experience/index.html': b'new expo',
             'static/index.html': b'classic', 'requirements.txt': b'pinned',
             'tests/test_example.py': b'def test_example(): pass\n'}
    files = {n: build.sha(v) for n, v in blobs.items()}
    manifest = {'files': files}
    meta = {'runtimeFiles': build.package.runtime_files(files), 'sourceHead': 'c' * 40, 'tree': 'd' * 40,
            'sourceFiles': files, 'manifestSha256': build.sha(build.encoded(manifest))}
    value = {'metadata': meta, 'manifest': manifest, 'blobs': blobs}
    directory = tmp_path / 'package'; directory.mkdir()
    write(directory / 'release-manifest.json', build.encoded(manifest))
    monkeypatch.setattr(build, 'checked_package', lambda *args: value)
    return directory, value


class Docker:
    def __init__(self, value, fault=None, parent_user='dashboard'):
        self.value, self.fault, self.calls = value, fault, []
        self.parent_user = parent_user

    def __call__(self, args, *, cwd=None, timeout=120):
        self.calls.append(args)
        raw, code = b'', 0
        if args[:2] == ['image', 'inspect']:
            child = args[-1] == IMAGE
            config = {'User': self.parent_user, 'Env': ['DATA_DIR=/data'], 'Cmd': ['gunicorn'], 'WorkingDir': '/app'}
            if child and self.fault == 'config':
                config['User'] = 'root'
            layers = ['old1', 'old2'] + (['cleanup', 'copy'] if child else [])
            if child and self.fault == 'layers':
                layers.append('extra')
            raw = json.dumps([{'Id': args[-1], 'Config': config, 'RootFS': {'Layers': layers}}]).encode()
        elif args[0] == 'build':
            recipe = (cwd / 'Dockerfile').read_text()
            lines = recipe.splitlines()
            assert lines[:2] == ['FROM ' + build.package.PARENT_IMAGE, 'USER 0']
            assert lines[2].startswith('RUN python -B -c ')
            assert lines[3:] == ['USER ' + self.parent_user, 'COPY --chown=10001:10001 runtime/ /app/']
            assert recipe.count('\nRUN ') == 1 and recipe.count('\nCOPY ') == 1
            assert 'pip install' not in recipe and 'apt-get' not in recipe
            assert '--network=none' in args and '--pull=false' in args
            Path(args[args.index('--iidfile') + 1]).write_text(IMAGE)
            if self.fault == 'build':
                code = 1
        elif args[0] == 'create':
            assert args[args.index('--network') + 1] == 'none'
            assert '--read-only' in args and '--cap-drop' in args and '--security-opt' in args
            assert args[args.index('--user') + 1] == '10001:10001'
            raw = CONTAINER.encode()
        elif args[0] == 'start':
            value = dict(self.value['metadata']['runtimeFiles'])
            if self.fault == 'runtime':
                value['app.py'] = '0' * 64
            raw = json.dumps(value).encode()
            if self.fault == 'probe':
                code = 1
        elif args[0] == 'rm':
            assert args == ['rm', '--force', CONTAINER]
        else:
            raise AssertionError(args)
        return subprocess.CompletedProcess(args, code, raw, b'')


@pytest.mark.parametrize('parent_user', ['dashboard', '10001:10001', 'dashboard:dashboard'])
def test_build_preserves_parent_and_exact_runtime(verified, tmp_path, parent_user):
    directory, value = verified
    docker = Docker(value, parent_user=parent_user)
    output = tmp_path / 'build'
    record = build.build(directory, 'e' * 64, output, runner=docker)
    assert record['imageId'] == IMAGE and record['addedLayers'] == 2
    assert record['runtimeHashes'] == value['metadata']['runtimeFiles']
    assert record['parentConfig']['User'] == parent_user
    assert docker.calls[-1] == ['rm', '--force', CONTAINER]
    assert (output / 'build.json').is_file()
    with pytest.raises(ValueError, match='new output'):
        build.build(directory, 'e' * 64, output, runner=docker)


@pytest.mark.parametrize('parent_user', [None, '', ' dashboard', 'dashboard:', 'dashboard:group:extra',
    'dashboard\nRUN touch /unexpected', 'dashboard\r\nUSER root', 'dashboard ${USER}'])
def test_build_rejects_unexpected_parent_user_before_recipe_or_build(verified, tmp_path, parent_user):
    directory, value = verified
    docker = Docker(value, parent_user=parent_user)
    output = tmp_path / 'attempt'
    with pytest.raises(ValueError, match='unsafe parent image user'):
        build.build(directory, 'e' * 64, output, runner=docker)
    assert docker.calls == [['image', 'inspect', build.package.PARENT_IMAGE]]
    assert not (output / 'context').exists() and not (output / 'build.json').exists()


@pytest.mark.parametrize('fault', ['config', 'layers', 'runtime', 'build', 'probe'])
def test_build_failure_never_seals_success(verified, tmp_path, fault):
    directory, value = verified
    docker = Docker(value, fault)
    output = tmp_path / 'attempt'
    with pytest.raises(ValueError):
        build.build(directory, 'e' * 64, output, runner=docker)
    assert (output / 'build.log').exists() and not (output / 'build.json').exists()
    if fault in ('runtime', 'probe'):
        assert docker.calls[-1] == ['rm', '--force', CONTAINER]


def test_create_and_start_failure_only_remove_owned_container():
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 124 if args[0] == 'start' else 0,
                                           CONTAINER.encode() if args[0] == 'create' else b'', b'')
    result = build.isolated(run, IMAGE, 'pass', writable=True)
    assert result.returncode == 124 and calls[-1] == ['rm', '--force', CONTAINER]
    assert '--tmpfs' in calls[0]


@pytest.mark.parametrize('timeout', [False, True])
def test_executor_preserves_command_even_before_final_report(tmp_path, monkeypatch, timeout):
    monkeypatch.setattr(sys, 'platform', 'linux')
    def execute(args, **kwargs):
        assert args[:3] == ['docker', '--host', 'unix:///var/run/docker.sock']
        if timeout:
            raise subprocess.TimeoutExpired(args, 1, output=b'partial original', stderr=b'partial error')
        return subprocess.CompletedProcess(args, 0, b'original stdout', b'original stderr')
    monkeypatch.setattr(subprocess, 'run', execute)
    result = build.Executor(tmp_path)(['image', 'inspect', IMAGE])
    assert result.returncode == (124 if timeout else 0)
    record = json.loads((tmp_path / 'commands/000.json').read_text())
    assert record['exitCode'] == result.returncode
    assert (tmp_path / record['stdout']).read_bytes() == result.stdout
    assert (tmp_path / record['stderr']).read_bytes() == result.stderr


def frozen(meta, nodes=None, skips=None):
    return {'schemaVersion': 1, 'sourceHead': meta['sourceHead'], 'manifestSha256': meta['manifestSha256'],
            'modules': ['tests/test_example.py'], 'nodeids': nodes or ['tests/test_example.py::test_example'],
            'allowedSkips': skips or {}}


@pytest.mark.parametrize('change', [
    lambda v: v.update(sourceHead='0' * 40),
    lambda v: v['nodeids'].append(v['nodeids'][0]),
    lambda v: v.update(modules=['tests/../app.py']),
    lambda v: v.update(nodeids=['tests/test_other.py::test_x']),
    lambda v: v.update(allowedSkips={'tests/test_other.py::test_x': 'anything'}),
])
def test_frozen_selection_rejects_identity_and_scope(verified, change):
    _directory, value = verified
    selection = frozen(value['metadata']); change(selection)
    raw = build.encoded(selection)
    with pytest.raises(ValueError):
        build.selection_record(raw, build.sha(raw), value['metadata'])


@pytest.fixture(scope='module')
def dependencies(tmp_path_factory):
    target = tmp_path_factory.mktemp('pytest-dependencies')
    for name in ('pytest', '_pytest', 'pluggy', 'iniconfig', 'packaging'):
        module = importlib.util.find_spec(name)
        shutil.copytree(Path(module.origin).parent, target / name,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    return target


def actual_validation(tmp_path, dependencies, body, *, extra_nodes=(), skips=None, shadow=False):
    runtime, support, proof, inputs = [tmp_path / n for n in ('runtime', 'support', 'proof', 'inputs')]
    for path in (runtime, support, proof, inputs):
        path.mkdir()
    write(runtime / 'membership_release_synthetic.py', b'VALUE=7\n')
    write(support / 'tests/__init__.py', b'')
    write(support / 'tests/test_example.py', body.encode())
    source = build.tree_hashes(support)
    manifest_raw = build.encoded({'files': source})
    write(support / 'RELEASE-MANIFEST.json', manifest_raw)
    meta = {'sourceHead': 'c' * 40, 'manifestSha256': build.sha(manifest_raw)}
    selection = frozen(meta, ['tests/test_example.py::test_example', *extra_nodes], skips)
    request = {'runtimeFiles': build.tree_hashes(runtime), 'sourceFiles': source, 'manifestSha256': build.sha(manifest_raw),
               'selection': selection, 'dependencies': build.tree_hashes(dependencies, dependencies=True)}
    write(inputs / 'request.json', build.encoded(request))
    program = ('import sys; from pathlib import Path; '
               f'sys.path.insert(0,{str(ROOT)!r}); from deploy.membership_release_build import container_validate; '
               f'sys.path[:0]=[{str(runtime)!r},{str(dependencies)!r}]; ')
    if shadow:
        alternate = tmp_path / 'shadow'; alternate.mkdir()
        write(alternate / 'membership_release_synthetic.py', b'VALUE=8\n')
        program += f'sys.path.insert(0,{str(alternate)!r}); import membership_release_synthetic; '
    program += 'raise SystemExit(container_validate(' + ','.join('Path(' + repr(str(p)) + ')' for p in
                (runtime, support, proof, inputs, dependencies)) + '))'
    result = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-c', program], cwd=tmp_path,
                            env=dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', PYTEST_ADDOPTS=''),
                            capture_output=True, timeout=45)
    return result, json.loads((proof / 'runtime.json').read_text()), proof, selection


SQLITE_CASE = '''import sqlite3
import membership_release_synthetic as runtime
def test_example(tmp_path):
    assert runtime.VALUE == 7
    with sqlite3.connect(tmp_path / 'synthetic.db') as con:
        con.execute('CREATE TABLE sample(value INTEGER)')
        con.execute('INSERT INTO sample VALUES (?)', (runtime.VALUE,))
        assert con.execute('SELECT value FROM sample').fetchone() == (7,)
'''


def test_actual_pytest_reads_runtime_and_real_sqlite(tmp_path, dependencies):
    process, record, proof, selection = actual_validation(tmp_path, dependencies, SQLITE_CASE)
    assert process.returncode == 0, process.stdout.decode() + process.stderr.decode()
    assert record['before'] == record['after'] and record['sourceBefore'] == record['sourceAfter']
    assert record['loadedBefore'] == record['loadedAfter'] == {
        'membership_release_synthetic': str((tmp_path / 'runtime/membership_release_synthetic.py').resolve())}
    assert record['collected'] == selection['nodeids'] and record['deselected'] == []
    assert build.junit_result(proof / 'results.xml', selection)['passed'] == 1


def test_actual_pytest_selects_frozen_nodes_without_running_other_module_tests(tmp_path, dependencies):
    body = SQLITE_CASE + '''
def test_unselected_failure():
    raise AssertionError('Unselected test must not execute')
def test_unselected_browser():
    raise AssertionError('Browser must not launch during API-only validation')
'''
    process, record, proof, selection = actual_validation(tmp_path, dependencies, body)
    assert process.returncode == 0, process.stdout.decode() + process.stderr.decode()
    assert record['runtimeVerifiedBefore'] and record['runtimeVerifiedAfter']
    assert record['before'] == record['after'] and record['sourceBefore'] == record['sourceAfter']
    assert record['collected'] == selection['nodeids'] and record['deselected'] == []
    assert set(record['reports']) == set(selection['nodeids'])
    assert build.junit_result(proof / 'results.xml', selection) == {
        'tests': 1, 'passed': 1, 'skipped': 0, 'failures': 0, 'errors': 0}


@pytest.mark.parametrize('fault', ['missing-node', 'skip', 'source-mutation', 'runtime-mutation', 'shadow'])
def test_actual_pytest_rejects_incomplete_or_drifting_validation(tmp_path, dependencies, fault):
    body = SQLITE_CASE
    if fault == 'skip':
        body = "import pytest\ndef test_example(): pytest.skip('unapproved platform skip')\n"
    elif fault == 'source-mutation':
        body = "from pathlib import Path\ndef test_example(): Path(__file__).write_text('changed')\n"
    elif fault == 'runtime-mutation':
        body = "from pathlib import Path\nimport membership_release_synthetic as r\ndef test_example(): Path(r.__file__).write_text('VALUE=9')\n"
    process, record, _proof, _selection = actual_validation(tmp_path, dependencies, body,
        extra_nodes=['tests/test_example.py::test_missing'] if fault == 'missing-node' else [], shadow=fault == 'shadow')
    assert process.returncode != 0 and not record['runtimeVerifiedAfter'] and record['error']


def test_actual_only_exact_allowlisted_skip(tmp_path, dependencies):
    node = 'tests/test_example.py::test_example'
    process, record, proof, selection = actual_validation(tmp_path, dependencies,
        "import pytest\ndef test_example(): pytest.skip('Windows junction only')\n", skips={node: 'Windows junction only'})
    assert process.returncode == 0, process.stderr.decode()
    assert record['runtimeVerifiedAfter'] is True and build.junit_result(proof / 'results.xml', selection)['skipped'] == 1


def test_junit_same_count_wrong_identity_is_rejected(tmp_path):
    path = tmp_path / 'results.xml'
    path.write_text('<testsuites><testsuite><testcase classname="tests.test_other" name="test_example"/></testsuite></testsuites>')
    with pytest.raises(ValueError, match='node identities'):
        build.junit_result(path, frozen({'sourceHead': 'c' * 40, 'manifestSha256': 'e' * 64}))


@pytest.mark.parametrize('fault', [None, 'shadow', 'skip', 'collection'])
def test_host_validation_seals_only_complete_evidence(verified, tmp_path, dependencies, fault):
    directory, value = verified
    selection = frozen(value['metadata'])
    selection_path = tmp_path / 'selection.json'
    selection_path.write_bytes(build.encoded(selection))
    node = selection['nodeids'][0]
    class ValidationDocker(Docker):
        def __call__(self, args, **kwargs):
            if args[0] == 'create':
                mounts = [args[i + 1] for i, part in enumerate(args) if part == '--mount']
                assert len(mounts) == 4 and sum(m.endswith(',readonly') for m in mounts) == 3
                assert all('dst=/data' not in m for m in mounts)
                parsed = {dict(part.split('=', 1) for part in m.split(',') if '=' in part)['dst']:
                          Path(dict(part.split('=', 1) for part in m.split(',') if '=' in part)['src']) for m in mounts}
                self.proof = parsed['/proof']
                self.request = json.loads((parsed['/validation-inputs'] / 'request.json').read_text())
                assert 'DATA_DIR=/tmp/membership-validation' in args and 'OPENAI_API_KEY=' in args
            if args[0] == 'start':
                request = self.request
                loaded = {'app': '/elsewhere/app.py' if fault == 'shadow' else '/app/app.py'}
                reports = [{'when': 'setup', 'outcome': 'passed', 'xfail': False},
                           {'when': 'call', 'outcome': 'passed', 'xfail': False},
                           {'when': 'teardown', 'outcome': 'passed', 'xfail': False}]
                if fault == 'skip':
                    reports[1] = {'when': 'call', 'outcome': 'skipped', 'xfail': False, 'reason': 'unapproved'}
                record = {'before': request['runtimeFiles'], 'after': request['runtimeFiles'],
                          'sourceBefore': request['sourceFiles'], 'sourceAfter': request['sourceFiles'],
                          'loadedBefore': loaded, 'loadedAfter': loaded, 'runtimeVerifiedBefore': True,
                          'runtimeVerifiedAfter': True, 'pytestExitCode': 0, 'deselected': [],
                          'collected': [] if fault == 'collection' else [node], 'reports': {node: reports}}
                write(self.proof / 'runtime.json', build.encoded(record))
                write(self.proof / 'results.xml', b'<testsuites><testsuite><testcase classname="tests.test_example" name="test_example"/></testsuite></testsuites>')
                self.calls.append(args)
                return subprocess.CompletedProcess(args, 0, b'unit fake container only', b'')
            return super().__call__(args, **kwargs)
    docker = ValidationDocker(value)
    record = build.validate(directory, 'e' * 64, IMAGE, selection_path, build.sha(selection_path.read_bytes()),
                            tmp_path / 'validation', dependencies, runner=docker)
    assert record['containerExitCode'] == 0
    assert record['allPassed'] is (fault is None) and record['exitCode'] == (0 if fault is None else 1)
    assert set(record['evidence']) == {'proof/results.xml', 'proof/runtime.json', 'proof/validation.log'}
    assert docker.calls[-1] == ['rm', '--force', CONTAINER]
