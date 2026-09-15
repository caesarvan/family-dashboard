"""Exercise real frozen build contexts with a command substitute, not Docker.

The separate release rehearsal proves actual container/layer behavior.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from deploy import build_static_release as B


PARENT = 'sha256:' + 'a' * 64
CHILD = 'sha256:' + 'b' * 64
LAYERS = ['sha256:' + '1' * 64, 'sha256:' + '2' * 64]


class Fixture:
    def __init__(self, root):
        self.source = root / 'candidate'; self.source.mkdir()
        self.output = root / 'build'
        self.values = {'app.py': b'# synthetic backend\n', 'requirements.txt': b'Flask==3.1.2\n',
                       'static/index.html': b'<p>Synthetic new trip entry</p>',
                       'static/app.js': b'const synthetic = true;\n',
                       'deploy/build_static_release.py': Path(B.__file__).read_bytes(),
                       'deploy/activate_journey_documents_release.py': Path(B.common.__file__).read_bytes()}
        self.freeze()
        config = {'User': '10001', 'Env': ['DATA_DIR=/data', 'PYTHONDONTWRITEBYTECODE=1'],
                  'Cmd': ['gunicorn', 'app:app'], 'Entrypoint': None, 'WorkingDir': '/app',
                  'Healthcheck': {'Test': ['CMD', 'python', '-c', 'print(1)']}}
        self.images = {PARENT: {'Id': PARENT, 'Config': config, 'RootFS': {'Type': 'layers', 'Layers': LAYERS}},
                       CHILD: {'Id': CHILD, 'Config': deepcopy(config),
                               'RootFS': {'Type': 'layers', 'Layers': LAYERS + ['sha256:' + '3' * 64]}}}
        self.calls = []
        self.extra_static = []
        self.probe_change = None
        self.on_build = None

    def freeze(self):
        for name, value in self.values.items():
            target = self.source / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(value)
        self.hashes = {name: B.sha(value) for name, value in self.values.items()}
        raw = B.encoded({'files': self.hashes})
        (self.source / 'RELEASE-MANIFEST.json').write_bytes(raw)
        self.manifest_sha = B.sha(raw)

    def runner(self, args, *, cwd, **kwargs):
        self.calls.append(args)
        if args[:3] == ['docker', 'image', 'inspect']:
            return json.dumps([self.images[args[3]]])
        if args[:2] == ['docker', 'run']:
            assert '--network' in args and args[args.index('--network') + 1] == 'none'
            assert '--read-only' in args and '--mount' not in args and '-v' not in args
            assert args[args.index('--entrypoint') + 1] == 'python'
            assert args[-2] == B.PROBE
            parent = args[args.index('--entrypoint') + 2] == PARENT
            names = json.loads(args[-1])
            value = {'hashes': {n: self.hashes[n] for n in names},
                     'backendFiles': sorted(n for n in self.hashes if n in ('app.py', 'requirements.txt')),
                     'staticFiles': sorted(n for n in self.hashes if n.startswith('static/')) + self.extra_static}
            if self.probe_change:
                self.probe_change(value, parent)
            return json.dumps(value)
        if args[:2] == ['docker', 'build']:
            assert '--network' in args and args[args.index('--network') + 1] == 'none'
            assert '--pull=false' in args and '--tag' not in args and '-t' not in args
            context = Path(args[-1])
            assert (context / 'Dockerfile').read_text() == f'FROM {PARENT}\nCOPY --chown=10001:10001 static/ /app/static/\n'
            assert sorted(p.relative_to(context).as_posix() for p in context.rglob('*') if p.is_file()) == ['Dockerfile', 'static/app.js', 'static/index.html']
            if self.on_build:
                self.on_build(context)
            Path(args[args.index('--iidfile') + 1]).write_text(CHILD)
            return 'synthetic build output'
        raise AssertionError(args)

    def run(self):
        return B.build(self.source, PARENT, self.manifest_sha, self.output, runner=self.runner)


@pytest.fixture
def f(tmp_path):
    return Fixture(tmp_path)


def test_frozen_static_only_build_records_exact_parent_and_source(f):
    result = f.run()
    assert result['status'] == 'built' and result['image'] == CHILD
    assert result['sourceHashes'] == f.hashes and result['parentImage'] == PARENT
    assert result['nonStaticRuntimeHashes'] == {n: f.hashes[n] for n in ('app.py', 'requirements.txt')}
    assert result['parentConfigSha256'] == result['childConfigSha256']
    assert result['parentLayersPreserved'] and result['configurationUnchanged']
    assert result['staticVerified'] and result['parentBackendVerified'] and result['childBackendVerified']
    assert not result['pipExecuted'] and not result['productionOperations']
    assert json.loads((f.output / 'build.json').read_bytes()) == result
    assert not any('compose' in call or 'tag' in call for call in f.calls)


@pytest.mark.parametrize('change', ['source', 'manifest', 'builder', 'common', 'existing-output', 'missing-static', 'static-removal'])
def test_preflight_rejects_unbound_or_unsupported_inputs_without_build(f, change):
    if change == 'source': (f.source / 'app.py').write_bytes(b'changed')
    if change == 'manifest': (f.source / 'RELEASE-MANIFEST.json').write_bytes(b'{}')
    if change in ('builder', 'common'):
        name = 'deploy/build_static_release.py' if change == 'builder' else 'deploy/activate_journey_documents_release.py'
        f.values[name] = b'changed'; f.freeze()
    if change == 'existing-output': f.output.mkdir()
    if change == 'missing-static': del f.values['static/index.html']; f.freeze()
    if change == 'static-removal': f.extra_static = ['static/old.js']
    with pytest.raises((RuntimeError, FileNotFoundError)):
        f.run()
    assert not any(call[:2] == ['docker', 'build'] for call in f.calls)


@pytest.mark.parametrize('change', ['parent-bytes', 'extra-backend'])
def test_parent_must_match_frozen_backend_exactly(f, change):
    def mutate(value, parent):
        if parent:
            if change == 'parent-bytes': value['hashes']['app.py'] = 'f' * 64
            else: value['backendFiles'].append('unknown.py')
    f.probe_change = mutate
    with pytest.raises(RuntimeError, match='parent_backend_differs'): f.run()
    assert not f.output.exists()


@pytest.mark.parametrize('change', ['config', 'parent-layer', 'extra-layer', 'child-backend', 'child-static', 'child-extra-static'])
def test_built_image_must_be_only_one_static_layer_with_identical_config_and_files(f, change):
    if change == 'config': f.images[CHILD]['Config']['Env'].append('UNEXPECTED=1')
    if change == 'parent-layer': f.images[CHILD]['RootFS']['Layers'][0] = 'sha256:' + '9' * 64
    if change == 'extra-layer': f.images[CHILD]['RootFS']['Layers'].append('sha256:' + '9' * 64)
    def mutate(value, parent):
        if not parent:
            if change == 'child-backend': value['hashes']['app.py'] = 'f' * 64
            if change == 'child-static': value['hashes']['static/app.js'] = 'f' * 64
            if change == 'child-extra-static': value['staticFiles'].append('static/injected.js')
    f.probe_change = mutate
    with pytest.raises(RuntimeError, match='static_build_failed'): f.run()
    assert json.loads((f.output / 'build.json').read_bytes())['status'] == 'failed'
    assert not any('compose' in call or 'tag' in call for call in f.calls)


@pytest.mark.parametrize('change', ['recipe', 'context-extra', 'static-bytes', 'source', 'manifest'])
def test_concurrent_input_change_cannot_be_reported_as_built(f, change):
    def mutate(context):
        if change == 'recipe': (context / 'Dockerfile').write_text('FROM bad\nRUN bad\n')
        if change == 'context-extra': (context / 'unexpected.env').write_text('synthetic=1')
        if change == 'static-bytes': (context / 'static/app.js').write_bytes(b'changed')
        if change == 'source': (f.source / 'app.py').write_bytes(b'changed')
        if change == 'manifest': (f.source / 'RELEASE-MANIFEST.json').write_bytes(b'{}')
    f.on_build = mutate
    with pytest.raises(RuntimeError, match='static_build_failed'): f.run()
    assert json.loads((f.output / 'build.json').read_bytes())['status'] == 'failed'


def test_build_failure_preserves_private_receipt_without_raw_command_output(f):
    def fail(_context): raise RuntimeError('synthetic-private-command-output')
    f.on_build = fail
    with pytest.raises(RuntimeError, match='static_build_failed') as error: f.run()
    raw = (f.output / 'build.json').read_text()
    assert 'synthetic-private-command-output' not in raw + str(error.value)
    assert json.loads(raw)['status'] == 'failed'


def test_existing_source_symlink_is_rejected(tmp_path):
    f = Fixture(tmp_path)
    path = f.source / 'static/app.js'; path.unlink()
    try: path.symlink_to(f.source / 'app.py')
    except OSError: pytest.skip('Creating symlinks is not permitted on this host')
    with pytest.raises(RuntimeError): f.run()
    assert not f.calls
