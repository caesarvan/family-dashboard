"""Source update gates and shared control flow; synthetic files/fake Docker only.

The unchanged database-checker module has its own real SQLite tests. These
tests do not claim a Docker build, two-household rehearsal or production run.
"""
from copy import deepcopy
import base64
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys
import pathlib

import pytest

from deploy import source_release as S
from deploy import release_core as C
from deploy import build_static_release as B
from deploy import rehearse_static_release as R

ROOT = Path(__file__).resolve().parents[1]


def load_test(name):
    spec = importlib.util.spec_from_file_location('source_fixture_' + name, ROOT / 'tests' / (name + '.py'))
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


OLD = load_test('test_static_release')
BUILD = load_test('test_static_build')


@pytest.fixture(autouse=True)
def no_external_processes(monkeypatch):
    def deny(*args, **kwargs): raise AssertionError('No real Docker, SSH or network in source unit tests')
    monkeypatch.setattr(subprocess, 'run', deny)
    monkeypatch.setattr(socket, 'create_connection', deny)
    monkeypatch.setattr(socket.socket, 'connect', deny)


class FakeDocker(OLD.FakeDocker):
    def __call__(self, args, **kwargs):
        if args[:2] == ['docker', 'run']:
            assert kwargs['input_bytes'] == C.SOURCE_CONTAINER_CODE.encode()
            kwargs['input_bytes'] = C.CONTAINER_CODE.encode()
        if args[:3] == ['docker', 'compose', 'exec'] and 'app' in args:
            assert kwargs['input_bytes'] == C.SOURCE_READBACK_CODE.encode()
        if args[:2] == ['docker', 'inspect'] and args[3] == '{{json .Config.Labels}}':
            return json.dumps({'family-dashboard.source-release': self.label})
        result = super().__call__(args, **kwargs)
        if args[:3] == ['docker', 'image', 'inspect'] and len(args) == 4:
            value = json.loads(result); value[0]['Config']['Env'].append('PYTHONDONTWRITEBYTECODE=1')
            result = json.dumps(value)
        return result


class Fixture(OLD.Fixture):
    def __init__(self, path):
        super().__init__(path)
        self.candidate = path / 'family-dashboard-candidate-source-synthetic'
        OLD.write(self.candidate / 'BASE-MANIFEST.json', self.base_raw)
        self.values['app.py'] = self.base['app.py'] + b'\n# synthetic reviewed source change\n'
        self.values[C.SOURCE_ENTRY] = (ROOT / C.SOURCE_ENTRY).read_bytes()
        self.values['tests/test_source_release.py'] = Path(__file__).read_bytes()
        self.runner = FakeDocker(self)
        self.refreeze_source()

    def refreeze_source(self):
        super().refreeze_source()
        changes = C.runtime_changes(self.ready['baseHashes'], self.hashes)
        python = sorted(x['path'] for x in changes if x['kind'] == 'rootPython')
        self.ready.update(mode='source-update', approvedRuntimeChanges=changes)
        build = self.envelopes.pop('staticBuild'); self.envelopes.pop('backendReuse')
        build.update(mode='source-update', baseManifestSha256=self.ready['baseManifestSha256'],
                     parentRuntimeHashes={**C.backend_hashes(self.ready['baseHashes']), **C.static_hashes(self.ready['baseHashes'])},
                     candidateRuntimeHashes={**C.backend_hashes(self.hashes), **C.static_hashes(self.hashes)},
                     approvedRuntimeChanges=changes, parentBackendVerified=True, childBackendVerified=True,
                     staticVerified=True, bytecodeExcluded=True)
        self.envelopes['sourceBuild'] = build
        script = 'tests/test_source_release.py'
        xml = b'<testsuite><testcase classname="tests.test_source_release" name="synthetic_gate_driver"/></testsuite>'
        log = b'Synthetic fixture, not a real prior test report.\n'
        OLD.write(self.candidate / 'evidence/current.xml', xml)
        OLD.write(self.candidate / 'evidence/current.log', log)
        deps = {**C.backend_hashes(self.hashes), script: self.hashes.get(script, '0' * 64)}
        common = {k: build[k] for k in ('verified', 'sourceHashes', 'records')}
        self.envelopes['backendValidation'] = {**common, 'coverageMode': 'affected-source-tests',
            'changedPython': python, 'compatibility': dict(C.COMPATIBILITY), 'historicalReuse': [],
            'runs': [{'platform': p, 'scripts': [script], 'coveredChanges': python, 'image': OLD.IMAGE,
                      'dependencyHashesBefore': deepcopy(deps), 'dependencyHashesAfter': deepcopy(deps),
                      'tests': 1, 'passed': 1, 'skipped': 0, 'failures': 0, 'errors': 0, 'exitCode': 0,
                      'junit': {'path': 'evidence/current.xml', 'sha256': C.sha(xml)},
                      'log': {'path': 'evidence/current.log', 'sha256': C.sha(log)}} for p in ('windows', 'linux')]}
        self.envelopes['gitReview'].update(approvedRuntimeChanges=changes, compatibility=dict(C.COMPATIBILITY))
        self.freeze_evidence()

    def activate(self):
        return S.activate(self.candidate, OLD.IMAGE, C.sha(self.manifest), self.ready_sha,
            root=self.root, releases=self.releases, project=self.project, volume=self.volume, runner=self.runner)

    def report(self):
        return json.loads(next(self.releases.glob('source-*/deployment.json')).read_bytes())


@pytest.fixture
def f(tmp_path): return Fixture(tmp_path)


def test_source_update_uses_shared_ordering_preserves_originals_and_never_restores(f):
    before = (f.root / '.env').read_bytes()
    r = f.activate()
    assert r['status'] == 'published' and r['mode'] == 'source-update'
    assert r['originalTablesPreserved'] == 43 and r['newTables'] == 0
    assert f.runner.actions == ['verify-image', 'snapshot', 'backup', 'validate-backup', 'check', 'check', 'check']
    assert r['beforeInstallReadback'] == r['startupReadback'] == r['afterHttpReadback']
    assert r['automaticRestoreAttempted'] is False and r['environmentPreserved']
    assert (Path(r['releaseDirectory']) / 'original-RELEASE-MANIFEST.json').read_bytes() == f.old_manifest
    assert (f.root / '.env').read_bytes() == before
    assert all((f.root / n).read_bytes() == raw for n, raw in f.values.items())
    assert not any('warm' in x or 'restore' in x for x in f.runner.actions)


def test_static_update_still_rejects_contract_inventory_json():
    name = 'docs/contract-inventory.json'
    base = {'static/app.js': '0' * 64, name: '1' * 64}
    candidate = {'static/app.js': '2' * 64, name: '3' * 64}
    with pytest.raises(RuntimeError, match='protected_source_change'):
        C.validate_changes(base, candidate, sorted(candidate), policy=C.STATIC)


def test_source_update_accepts_the_known_contract_inventory_json(f):
    name = 'docs/contract-inventory.json'
    original_environment = (f.root / '.env').read_bytes()
    f.values[name] = b'{"scope":"synthetic source inventory","routes":[]}\n'
    f.refreeze_source()
    result = f.activate()
    assert result['status'] == 'published'
    assert (f.root / name).read_bytes() == f.values[name]
    assert (f.root / '.env').read_bytes() == original_environment
    assert name not in {change['path'] for change in C.runtime_changes(f.ready['baseHashes'], f.hashes)}


@pytest.mark.parametrize('name', ['requirements.txt', 'Dockerfile', 'compose.yaml', 'deploy/nginx.conf',
                                 'deploy/backup.py', 'deploy/other.py', 'new_backend.py',
                                 'docs/settings.json', 'docs/nested/contract-inventory.json',
                                 'docs/contract-inventory.json.backup', 'contract-inventory.json'])
def test_unapproved_scope_rejected_before_any_process(f, name):
    f.values[name] = f.values.get(name, b'') + b'\n# changed\n'; f.refreeze_source()
    with pytest.raises(RuntimeError): f.activate()
    assert not f.runner.calls and all(v['running'] for v in f.runner.services.values())


@pytest.mark.parametrize('change', ['missing-approval', 'extra-approval', 'wrong-before', 'wrong-base',
                                   'wrong-mode', 'delete', 'common-module', 'entry-module'])
def test_manifest_policy_and_shared_module_bindings_cannot_be_declared_away(f, change):
    if change == 'missing-approval': f.ready['approvedRuntimeChanges'] = []
    if change == 'extra-approval': f.ready['approvedRuntimeChanges'].append({'path': 'other.py'})
    if change == 'wrong-before': f.ready['approvedRuntimeChanges'][0]['beforeSha256'] = '0' * 64
    if change == 'wrong-base': f.ready['baseManifestSha256'] = '0' * 64
    if change == 'wrong-mode': f.ready['mode'] = 'static-only'
    if change == 'delete':
        del f.values['docs/example.md']; (f.candidate / 'docs/example.md').unlink(); f.refreeze_source()
    if change in ('common-module', 'entry-module'):
        f.values[C.CORE if change == 'common-module' else C.SOURCE_ENTRY] = b'# different executable module'; f.refreeze_source()
    f.freeze_ready()
    with pytest.raises(RuntimeError): f.activate()
    assert not f.runner.calls


def test_static_entry_still_rejects_source_ready_and_source_policy_cannot_be_injected(f, tmp_path):
    with pytest.raises(RuntimeError):
        OLD.C.activate(f.candidate, OLD.IMAGE, C.sha(f.manifest), f.ready_sha,
            root=f.root, releases=f.releases, project=f.project, volume=f.volume, runner=f.runner)
    with pytest.raises(TypeError): OLD.C.validate_changes(f.ready['baseHashes'], f.hashes, f.ready['changedFiles'], policy=C.SOURCE)
    with pytest.raises(RuntimeError): OLD.C.validate_changes(f.ready['baseHashes'], f.hashes, f.ready['changedFiles'])
    assert not f.runner.calls


def test_static_and_source_contend_on_the_original_lock_inode(f):
    with OLD.C.release_lock(f.releases):
        with pytest.raises(RuntimeError, match='another_static_release_running'): f.activate()
    assert not f.runner.calls and (f.releases / '.static-release.lock').exists()
    assert not (f.releases / '.source-release.lock').exists()


@pytest.mark.parametrize('failure', ['verify-image', 'backup', 'validate-backup', 'check', 'tag',
    'up-app', 'unhealthy', 'http', 'anonymous', 'second-check', 'up-sync', 'nginx',
    'timeout-snapshot', 'timeout-check'])
def test_source_failure_closes_services_and_retains_scene_without_restore(f, failure):
    f.runner.fail = failure
    with pytest.raises(RuntimeError): f.activate()
    r = f.report()
    assert r['status'] == 'failed' and r['automaticRestoreAttempted'] is False
    assert (Path(r['releaseDirectory']) / 'original-RELEASE-MANIFEST.json').read_bytes() == f.old_manifest
    if failure == 'verify-image': assert all(v['running'] for v in f.runner.services.values())
    else: assert not any(v['running'] for v in f.runner.services.values())
    if failure in ('backup', 'validate-backup', 'check'):
        assert (f.root / 'app.py').read_bytes() == f.base['app.py']
        assert not any(x[:3] == ['docker', 'compose', 'up'] for x in f.runner.calls)
    assert not any(v['running'] for v in f.runner.helpers.values())


@pytest.mark.parametrize('change', ['old-coverage', 'wrong-image', 'old-dependencies', 'extra-dependency',
                                   'missing-platform', 'false-compatibility', 'integer-compatibility',
                                   'count-lie', 'missing-coverage', 'wrong-scripts'])
def test_new_backend_evidence_requires_current_real_record_shape_and_coverage(f, change):
    e = f.envelopes['backendValidation']; r = e['runs'][1]
    if change == 'old-coverage': e['coverageMode'] = 'unchanged-backend-dependencies'
    if change == 'wrong-image': r['image'] = f.previous
    if change == 'old-dependencies': r['dependencyHashesBefore']['app.py'] = f.ready['baseHashes']['app.py']
    if change == 'extra-dependency': r['dependencyHashesBefore']['private.txt'] = r['dependencyHashesAfter']['private.txt'] = '0' * 64
    if change == 'missing-platform': e['runs'].pop()
    if change == 'false-compatibility': e['compatibility']['noSchemaChanges'] = False
    if change == 'integer-compatibility': e['compatibility']['noSchemaChanges'] = 1
    if change == 'count-lie': r['passed'] = r['tests'] = 2
    if change == 'missing-coverage': r['coveredChanges'] = []
    if change == 'wrong-scripts': r['scripts'] = ['tests/browser_synthetic.py']
    f.freeze_evidence()
    with pytest.raises(RuntimeError): f.activate()
    assert not f.runner.calls


@pytest.mark.parametrize('xml', [b'<broken', b'<testsuite><testcase classname="tests.test_source_release"><failure/></testcase></testsuite>',
    b'<testsuite><testcase classname="tests.unrelated"/></testsuite>',
    b'<testsuite><testcase classname="tests.test_source_release_unrelated"/></testsuite>'])
def test_raw_junit_failure_or_unrelated_scope_is_not_promoted(f, xml):
    OLD.write(f.candidate / 'evidence/current.xml', xml)
    for r in f.envelopes['backendValidation']['runs']: r['junit']['sha256'] = C.sha(xml)
    f.freeze_evidence()
    with pytest.raises(Exception): f.activate()
    assert not f.runner.calls


def test_historical_reuse_cannot_claim_a_changed_python_dependency(f):
    e = f.envelopes['backendValidation']
    e['historicalReuse'] = [{'dependencyHashes': {'app.py': f.hashes['app.py']},
        'excludedChangedFiles': ['app.py'], 'reason': 'not really unchanged', 'record': e['records'][0]}]
    f.freeze_evidence()
    with pytest.raises(RuntimeError, match='source_history_applicability'): f.activate()
    assert not f.runner.calls


class BuildFixture(BUILD.Fixture):
    def __init__(self, path):
        super().__init__(path)
        self.values[C.SOURCE_ENTRY] = (ROOT / C.SOURCE_ENTRY).read_bytes()
        self.base_values = deepcopy(self.values)
        self.base_hashes = {n: C.sha(v) for n, v in self.base_values.items()}
        self.base_raw = C.encoded({'files': self.base_hashes})
        (self.source / 'BASE-MANIFEST.json').write_bytes(self.base_raw)
        self.values['app.py'] += b'# new source\n'
        self.values['static/app.js'] += b'const changed = true;\n'; self.freeze()
        for image in self.images.values(): image['Config']['Env'].append('PYTHONDONTWRITEBYTECODE=1')
        self.bad_bytecode = None

    def runner(self, args, *, cwd, **kwargs):
        if args[:2] == ['docker', 'run'] and args[-1] == B.BYTECODE_PROBE:
            self.calls.append(args)
            image = args[args.index('--entrypoint') + 2]
            return json.dumps({'bytecodeExcluded': image != self.bad_bytecode})
        if args[:2] == ['docker', 'run'] and args[args.index('--entrypoint') + 2] == BUILD.PARENT:
            self.calls.append(args)
            expected = json.loads(args[-1])
            return json.dumps({'hashes': {n: self.base_hashes[n] for n in expected},
                'backendFiles': sorted(C.backend_hashes(self.base_hashes)), 'staticFiles': sorted(C.static_hashes(self.base_hashes))})
        if args[:2] == ['docker', 'build']:
            self.calls.append(args)
            context = Path(args[-1])
            assert (context / 'Dockerfile').read_text() == f'FROM {BUILD.PARENT}\nCOPY --chown=10001:10001 app/ /app/\n'
            assert sorted(p.relative_to(context).as_posix() for p in context.rglob('*') if p.is_file()) == [
                'Dockerfile', 'app/app.py', 'app/static/app.js', 'app/static/index.html']
            assert (context / 'app/app.py').read_bytes() == self.values['app.py']
            assert '--pull=false' in args and args[args.index('--network') + 1] == 'none'
            if self.on_build: self.on_build(context)
            Path(args[args.index('--iidfile') + 1]).write_text(BUILD.CHILD)
            return 'synthetic build'
        return super().runner(args, cwd=cwd, **kwargs)

    def run(self):
        return S.build(self.source, BUILD.PARENT, self.manifest_sha, C.sha(self.base_raw), self.output, runner=self.runner)


def test_source_build_parent_is_old_base_and_child_is_new_candidate(tmp_path):
    f = BuildFixture(tmp_path); r = f.run()
    assert r['status'] == 'built' and r['mode'] == 'source-update'
    assert r['parentRuntimeHashes']['app.py'] != r['candidateRuntimeHashes']['app.py']
    assert r['parentRuntimeHashes'] == {**C.backend_hashes(f.base_hashes), **C.static_hashes(f.base_hashes)}
    assert r['runtimeChanges'] == C.runtime_changes(f.base_hashes, f.hashes)
    assert r['baseManifestSha256'] == C.sha(f.base_raw)
    assert r['configurationUnchanged'] and r['parentLayersPreserved'] and not r['pipExecuted']


@pytest.mark.parametrize('change', ['missing-base', 'wrong-base', 'requirements', 'common', 'config', 'layers',
                                   'child-old-python', 'context-extra', 'context-python', 'base-drift'])
def test_source_build_cannot_hide_input_or_parent_child_drift(tmp_path, change):
    f = BuildFixture(tmp_path)
    if change == 'missing-base': (f.source / 'BASE-MANIFEST.json').unlink()
    if change == 'wrong-base': (f.source / 'BASE-MANIFEST.json').write_bytes(b'{}')
    if change == 'requirements': f.values['requirements.txt'] += b'new'; f.freeze()
    if change == 'common': f.values[C.CORE] = b'# unbound'; f.freeze()
    if change == 'config': f.images[BUILD.CHILD]['Config']['User'] = '0'
    if change == 'layers': f.images[BUILD.CHILD]['RootFS']['Layers'].append('sha256:' + 'f' * 64)
    if change == 'child-old-python': f.probe_change = lambda v, parent: v['hashes'].update({'app.py': f.base_hashes['app.py']})
    def mutate(context):
        if change == 'context-extra': (context / 'app/extra.py').write_bytes(b'not approved')
        if change == 'context-python': (context / 'app/app.py').write_bytes(b'not approved')
        if change == 'base-drift': (f.source / 'BASE-MANIFEST.json').write_bytes(b'{}')
    f.on_build = mutate
    with pytest.raises(RuntimeError): f.run()
    assert not any('compose' in x or 'tag' in x for x in f.calls)


@pytest.mark.parametrize('bad', ['--mode', '--root', '--volume', '--allow-backend'])
def test_production_cli_has_no_policy_or_target_escape(bad):
    with pytest.raises(SystemExit): S.main(['activate', 'candidate', 'image', 'manifest', 'ready', bad, 'x'])


def test_source_rehearsal_requires_a_separate_explicit_old_source(tmp_path):
    source = tmp_path / 'source'; source.mkdir()
    with pytest.raises(RuntimeError, match='separate_base_source'):
        S.rehearsal(source, '1'*64, BUILD.PARENT, BUILD.CHILD, tmp_path/'proof', '2'*64,
            'sha256:'+'c'*64, tmp_path/'output', base_source=source, base_manifest_sha='3'*64)


def test_synthetic_source_ready_does_not_rewrite_real_build_or_claim_acceptance(f):
    f.values[R.FIXTURE] = (ROOT / R.FIXTURE).read_bytes(); f.refreeze_source()
    path = f.root.parent / 'fixture'; path.mkdir()
    raw = C.encoded({'files': f.hashes}); (path / 'RELEASE-MANIFEST.json').write_bytes(raw)
    original = b'{ "status": "built", "scope": "original, retained" }\n'
    R.fixture_ready(path, f.ready['baseHashes'], f.hashes, f.previous, OLD.IMAGE,
                    original, b'SECRET_KEY=synthetic\n', policy=C.SOURCE)
    ready = json.loads((path / 'READY.json').read_bytes())
    assert ready['synthetic'] and ready['isAcceptanceEvidence'] is False
    assert (path / 'evidence/build-original.json').read_bytes() == original
    assert ready['mode'] == 'source-update'
    frozen = S.evidence(path, ready, f.hashes, OLD.IMAGE)
    assert frozen['evidence/build-original.json'] == original
    for ref in ready['evidence'].values():
        e = json.loads((path / ref['path']).read_bytes())
        assert e['synthetic'] and e['isAcceptanceEvidence'] is False


def prepared_rehearsal(f, monkeypatch):
    extra = {'static/index.html': b'<p>synthetic</p>', 'deploy/nginx.conf': b'# old synthetic configuration\n'}
    extra.update({n: (ROOT / n).read_bytes() for n in (R.SELF, R.FIXTURE, 'deploy/build_static_release.py')})
    f.base.update(extra); f.values.update(extra)
    f.base_raw = C.encoded({'files': {n: C.sha(v) for n, v in f.base.items()}})
    for n, v in f.base.items(): OLD.write(f.root / n, v)
    OLD.write(f.root / 'RELEASE-MANIFEST.json', f.base_raw)
    OLD.write(f.candidate / 'BASE-MANIFEST.json', f.base_raw)
    f.ready.update(baseHashes=json.loads(f.base_raw)['files'], baseManifestSha256=C.sha(f.base_raw))
    f.refreeze_source()
    proof = {**f.envelopes['sourceBuild'], 'status': 'built', 'productionOperations': False,
             'runtimeChanges': f.ready['approvedRuntimeChanges']}
    raw = C.encoded(proof); proof_path = f.root.parent / 'original-build.json'; proof_path.write_bytes(raw)
    run = S.rehearsal(f.candidate, C.sha(f.manifest), f.previous, OLD.IMAGE, proof_path, C.sha(raw),
        'sha256:'+'c'*64, f.root.parent / 'rehearsal', base_source=f.root, base_manifest_sha=C.sha(f.base_raw))
    calls = []
    def call(args, **kwargs):
        calls.append(args)
        if args[:2] == ['image', 'inspect']: return json.dumps([{'Id': args[-1], 'Os': 'linux'}])
        if args[:2] == ['image', 'ls']: return ''
        raise AssertionError('No resource operation in prepare-only substitute')
    def ephemeral(image, args, **kwargs):
        assert image == f.previous and args[:3] == ['python', '-c', R.PARENT_FILES]
        assert json.loads(args[-1]) == C.backend_hashes(f.ready['baseHashes'])
        return json.dumps({n: base64.b64encode(v).decode() for n, v in f.base.items() if n.startswith('static/')})
    monkeypatch.setattr(run, 'call', call)
    monkeypatch.setattr(run, 'ephemeral', ephemeral)
    return run, calls, raw


def test_source_rehearsal_prepares_actual_old_python_and_new_python_with_equal_isolated_config(f, monkeypatch):
    run, calls, proof = prepared_rehearsal(f, monkeypatch)
    run.prepare()
    assert (run.root / 'app.py').read_bytes() == f.base['app.py']
    assert (run.candidate / 'app.py').read_bytes() == f.values['app.py']
    assert f.base['app.py'] != f.values['app.py']
    assert (run.root / 'compose.yaml').read_bytes() == (run.candidate / 'compose.yaml').read_bytes()
    assert (run.root / 'deploy/nginx.conf').read_bytes() == (run.candidate / 'deploy/nginx.conf').read_bytes()
    configuration = json.loads((run.root / 'compose.yaml').read_bytes())
    assert all(s['network_mode'] == 'none' and not s.get('ports') for s in configuration['services'].values())
    assert (run.candidate / 'evidence/build-original.json').read_bytes() == proof
    assert run.report['syntheticEnvelopesAreAcceptanceEvidence'] is False
    assert set(run.report['baseSourceAdaptations']) == {'compose.yaml', 'deploy/nginx.conf'}
    assert run.report['baseManifestSha256'] == C.sha(f.base_raw)
    assert run.report['passed'] is False and not run.resources


@pytest.mark.parametrize('changed', ['base-file', 'base-manifest', 'candidate-base', 'proof-base', 'proof-parent-runtime'])
def test_source_rehearsal_refuses_base_or_proof_drift_before_docker(f, monkeypatch, changed):
    run, calls, raw = prepared_rehearsal(f, monkeypatch)
    if changed == 'base-file': (f.root / 'app.py').write_bytes(b'# wrong old app')
    if changed == 'base-manifest': (f.root / 'RELEASE-MANIFEST.json').write_bytes(b'{}')
    if changed == 'candidate-base': (f.candidate / 'BASE-MANIFEST.json').write_bytes(b'{}')
    if changed.startswith('proof-'):
        p = json.loads(raw)
        if changed == 'proof-base': p['baseManifestSha256'] = '0'*64
        else: p['parentRuntimeHashes']['app.py'] = f.hashes['app.py']
        raw = C.encoded(p); run.proof.write_bytes(raw); run.proof_sha = C.sha(raw)
    with pytest.raises(RuntimeError): run.prepare()
    assert not calls and not run.output.exists()


@pytest.mark.parametrize('name', ['COMPOSE_FILE', 'docker_host'])
def test_source_builder_rejects_host_selectors_before_any_command(tmp_path, monkeypatch, name):
    f = BuildFixture(tmp_path); monkeypatch.setenv(name, 'synthetic-override')
    with pytest.raises(RuntimeError, match='host_docker_compose_environment'): f.run()
    assert not f.calls


def test_source_builder_passes_one_frozen_environment_to_all_commands(tmp_path, monkeypatch):
    f = BuildFixture(tmp_path); monkeypatch.setenv('SYNTHETIC_SOURCE_INPUT', 'before')
    supplied = []
    def runner(args, **kwargs):
        supplied.append(kwargs['env'])
        monkeypatch.setenv('SYNTHETIC_SOURCE_INPUT', 'after')
        return f.runner(args, **kwargs)
    r = S.build(f.source, BUILD.PARENT, f.manifest_sha, C.sha(f.base_raw), f.output, runner=runner)
    assert r['status'] == 'built' and len(supplied) > 2
    assert all(e['SYNTHETIC_SOURCE_INPUT'] == 'before' for e in supplied)


@pytest.mark.parametrize('image', [BUILD.PARENT, BUILD.CHILD])
def test_source_builder_rejects_parent_or_child_bytecode_cache(tmp_path, image):
    f = BuildFixture(tmp_path); f.bad_bytecode = image
    with pytest.raises(RuntimeError): f.run()
    assert not any('compose' in c for c in f.calls)


@pytest.mark.parametrize('change', ['none', 'pyc', 'pyo', 'prefix', 'write-enabled'])
def test_actual_embedded_bytecode_guard_checks_real_files_and_interpreter_flags(tmp_path, monkeypatch, change):
    if change in ('pyc', 'pyo'):
        cache = tmp_path / '__pycache__'; cache.mkdir(); (cache / ('app.' + change)).write_bytes(b'synthetic old code')
    original = pathlib.Path
    with monkeypatch.context() as m:
        m.setattr(pathlib, 'Path', lambda p: tmp_path if p == '/app' else original(p))
        m.setattr(sys, 'dont_write_bytecode', change != 'write-enabled')
        m.setattr(sys, 'pycache_prefix', '/synthetic-cache' if change == 'prefix' else None)
        if change == 'none': exec(compile(C.BYTECODE_CHECK, '<actual bytecode guard>', 'exec'), {})
        else:
            with pytest.raises(RuntimeError, match='source_bytecode_unsafe'):
                exec(compile(C.BYTECODE_CHECK, '<actual bytecode guard>', 'exec'), {})


@pytest.mark.parametrize('name,value', [('PYTHONPYCACHEPREFIX','/data/cache'), ('PYTHONDONTWRITEBYTECODE','0')])
def test_source_activation_rejects_effective_compose_cache_override_before_stop(f, name, value):
    f.runner.compose_environment[name] = value
    f.runner.app_environment.append(name + '=' + value)
    with pytest.raises(RuntimeError, match='source_bytecode_environment'): f.activate()
    assert not f.runner.actions and all(v['running'] for v in f.runner.services.values())
