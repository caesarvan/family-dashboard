"""Real controller/file flow with a fake Docker runner; no real Docker/SSH.

Database semantics belong to test_journey_documents_migration.py. These tests
exercise ordering, failure handling, SHA binding and preservation on disk. They
do not claim a real Docker rollback or a production migration was performed.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tarfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('journey_release_under_test', ROOT / 'deploy/activate_journey_documents_release.py')
C = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(C)
IMAGE = 'sha256:' + '9' * 64


def digest(value):
    return hashlib.sha256(value).hexdigest()


def dump(value):
    return json.dumps(value, ensure_ascii=False).encode()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


@pytest.fixture(autouse=True)
def no_processes_or_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError('Real external process/network forbidden')
    monkeypatch.setattr(subprocess, 'run', deny)
    import socket
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket, 'create_connection', deny)


class FakeDocker:
    def __init__(self, fixture):
        self.f = fixture
        self.calls = []
        self.actions = []
        self.fail = None
        self.mutate = None
        self.bad_check = False
        self.stop_exit = 0
        self.volume_extra = False
        self.helpers = {}
        self.compose_environment = {'DATA_DIR': '/data', 'PUBLIC_ORIGIN': 'https://synthetic.invalid',
                                    'SECRET_KEY': 'synthetic-secret-do-not-print'}
        self.app_environment = [k + '=' + v for k, v in self.compose_environment.items()]
        self.services = {n: {'id': str(i) * 64, 'image': C.PREVIOUS if n != 'web' else 'sha256:' + '8' * 64,
                             'running': True, 'exitCode': 0, 'oom': False,
                             'health': 'healthy' if n == 'app' else None}
                         for i, n in enumerate(('web', 'sync', 'app'), 1)}

    def result(self):
        return {'households': 2, 'originalTablesPreserved': 42, 'newTables': 1, 'newTableEmpty': True,
                'schemaIndexesAndTriggersVerified': True, 'allOriginalRowsAndSequencesPreserved': True}

    def __call__(self, args, *, cwd, input_bytes=None, timeout=180):
        assert Path(cwd) == self.f.root
        self.calls.append(list(args))
        if args[:3] == ['docker', 'compose', 'ps']:
            return self.services[args[-1]]['id']
        if args[:2] == ['docker', 'inspect']:
            state = next(v for v in [*self.services.values(), *self.helpers.values()] if v['id'] == args[-1])
            if args[3] == '{{json .Config.Env}}':
                assert state is self.services['app']
                return json.dumps(self.app_environment)
            if args[3] == '{{json .Mounts}}':
                return json.dumps([{'Type': 'volume', 'Name': C.VOLUME, 'Destination': '/data', 'RW': True}])
            return json.dumps(state)
        if args[:3] == ['docker', 'image', 'inspect']:
            if self.fail == 'image':
                raise RuntimeError('fake image missing')
            return IMAGE
        if args[:3] == ['docker', 'compose', 'config']:
            if self.fail == 'compose':
                raise RuntimeError('fake compose invalid')
            assert args[3:] == ['--format', 'json']
            return json.dumps({'services': {'app': {'environment': self.compose_environment}}})
        if args[:2] == ['docker', 'ps']:
            if args[-1].startswith('name=^/'):
                name = args[-1][7:-1]
                return self.helpers[name]['id'] if name in self.helpers else ''
            live = [v['id'] for n, v in self.services.items() if n != 'web' and v['running']]
            if self.volume_extra:
                live.append('a' * 64)
            return '\n'.join(live)
        if args[:2] == ['docker', 'stop']:
            assert args[2:4] == ['--time', '45']
            state = next(v for v in self.helpers.values() if v['id'] == args[-1])
            state['running'] = False
            return args[-1]
        if args[:3] == ['docker', 'compose', 'stop']:
            for n in args[5:]:
                self.services[n].update(running=False, exitCode=self.stop_exit)
            if self.fail == 'stop':
                raise RuntimeError('fake partial stop')
            return ''
        if args[:2] == ['docker', 'tag']:
            assert args[2:] == [IMAGE, 'family-dashboard-app']
            if self.fail == 'tag':
                raise RuntimeError('fake tag failed')
            return ''
        if args[:3] == ['docker', 'compose', 'up']:
            n = args[-1]
            if self.fail == 'up-' + n:
                raise RuntimeError('fake startup failed')
            if n in ('sync', 'web'):
                assert self.actions.count('check') == 2
                assert self.services['app']['health'] == 'healthy'
            self.services[n].update(running=True, exitCode=0)
            if n != 'web':
                self.services[n]['image'] = IMAGE
            if n == 'app' and self.fail == 'unhealthy':
                self.services[n]['health'] = 'unhealthy'
            return ''
        if args[:3] == ['docker', 'compose', 'exec']:
            if self.fail == 'nginx':
                raise RuntimeError('fake nginx invalid')
            return ''
        assert args[:2] == ['docker', 'run'], args
        action = args[-2]; self.actions.append(action)
        assert input_bytes == C.CONTAINER_CODE.encode()
        assert args[args.index('--network') + 1] == 'none' and '--read-only' in args
        assert args[args.index('--user') + 1] == '10001:10001'
        assert args[args.index('--memory') + 1] == '384m'
        assert args[args.index('--tmpfs') + 1].endswith('size=64m')
        assert '--env-file' not in args
        assert args[-5:-2] == [IMAGE, 'python', '-']
        mounts = [args[i + 1] for i, value in enumerate(args) if value == '--mount']
        assert any(x.endswith('dst=/release-source,readonly') for x in mounts)
        check_mount = next(x for x in mounts if x.endswith('dst=/release-check,readonly'))
        inputs = Path(check_mount.split(',src=', 1)[1].split(',dst=', 1)[0])
        for name, expected in json.loads(args[-1]).items():
            assert digest((inputs / name).read_bytes()) == expected
        assert 'environment.json' in json.loads(args[-1])
        if action == 'verify-image':
            assert not any('type=volume' in x for x in mounts)
        else:
            assert any(x == 'type=volume,src=' + C.VOLUME + ',dst=/data' for x in mounts)
            assert not self.services['web']['running'] and not self.services['sync']['running']
        if self.mutate:
            self.mutate(action, inputs)
        if self.fail == 'timeout-' + action:
            name = args[args.index('--name') + 1]
            self.helpers[name] = {'id': 'f' * 64, 'image': IMAGE, 'running': True,
                                  'exitCode': 0, 'oom': False, 'health': None}
            raise RuntimeError('command_timeout')
        if self.fail == action or (self.fail == 'second-check' and action == 'check' and self.actions.count('check') == 2):
            raise RuntimeError('synthetic sensitive stderr must not escape')
        if action == 'verify-image':
            return json.dumps({'imageSourceVerified': True})
        if action == 'snapshot':
            return json.dumps({'registry': {'synthetic': True}, 'households': {'default': {}, 'a' * 24: {}}})
        if action == 'backup':
            write(self.f.data / 'backups/manifest-20260915T000000Z.json', b'{"synthetic":true}')
            return json.dumps({'manifest': 'manifest-20260915T000000Z.json', 'databases': 3})
        proof = {'databases': 3, 'manifestSha256': digest(b'{"synthetic":true}'), 'groupVerified': True}
        if action == 'validate-backup':
            return json.dumps(proof)
        if action == 'warm':
            assert (inputs / 'backup-verification.json').exists()
            self.f.migrated.write_bytes(b'new schema was applied; must never be erased on failure')
            return json.dumps({**self.result(), 'cloudTicks': 0, 'backup': proof})
        assert action == 'check'
        result = self.result()
        if self.bad_check:
            result['schemaIndexesAndTriggersVerified'] = False
        return json.dumps(result)


class Fixture:
    def __init__(self, tmp_path, monkeypatch):
        self.root = tmp_path / 'family-dashboard'
        self.candidate = tmp_path / 'family-dashboard-candidate-journey-documents-synthetic'
        self.releases = tmp_path / 'releases'
        self.data = tmp_path / 'fake-data-volume'
        self.migrated = self.data / 'migrated-marker'
        self.data.mkdir()
        self.base = {'app.py': b'# old application\n', 'compose.yaml': b'name: family-dashboard\n',
                     'requirements.txt': b'flask\n', 'deploy/backup.py': b'# approved backup\n',
                     'Dockerfile': b'COPY app.py ./\n', 'static/example.js': b'/* old static */\n',
                     'tests/browser_synthetic.py': b'# synthetic browser fixture\n'}
        while len(self.base) < 222:
            self.base['docs/synthetic-' + str(len(self.base)) + '.md'] = b'fictional documentation\n'
        base_hashes = {n: digest(v) for n, v in self.base.items()}
        self.base_raw = dump({'files': base_hashes})
        self.old_manifest = dump({'files': dict(list(base_hashes.items())[:218]), 'historical': 'keep exact bytes'})
        monkeypatch.setattr(C, 'BASE_SHA', digest(self.base_raw))
        monkeypatch.setattr(C, 'OLD_MANIFEST_SHA', digest(self.old_manifest))
        for name, raw in self.base.items():
            write(self.root / name, raw)
        write(self.root / 'RELEASE-MANIFEST.json', self.old_manifest)
        write(self.root / '.env', b'SECRET_KEY="synthetic-secret-do-not-print"\nPUBLIC_ORIGIN="https://synthetic.invalid"\n')
        self.values = {**self.base, 'app.py': b'# new reviewed application\n',
                       'Dockerfile': b'COPY app.py journey_documents.py ./\n',
                       'journey_documents.py': b'SCHEMA_SQL = "CREATE TABLE journey_documents(id TEXT);"\n',
                       C.HELPER: b'# verified helper fixture, replaced by fake runner\n',
                       C.CONTROLLER: Path(C.__file__).read_bytes()}
        for name, raw in self.values.items():
            write(self.candidate / name, raw)
        self.hashes = {n: digest(v) for n, v in self.values.items()}
        self.manifest = dump({'files': self.hashes})
        write(self.candidate / 'RELEASE-MANIFEST.json', self.manifest)
        write(self.candidate / 'BASE-MANIFEST.json', self.base_raw)
        self.schema_sha = digest(b'CREATE TABLE journey_documents(id TEXT);')
        self.ready = {'version': 1, 'verified': True, 'image': IMAGE, 'previousImage': C.PREVIOUS,
                      'manifestSha256': digest(self.manifest), 'sourceHashes': self.hashes,
                      'baseManifestSha256': C.BASE_SHA, 'baseHashes': base_hashes,
                      'oldManifestSha256': C.OLD_MANIFEST_SHA,
                      'changedFiles': sorted(n for n, v in self.hashes.items() if base_hashes.get(n) != v),
                      'environmentSha256': digest((self.root / '.env').read_bytes()),
                      'migration': {'from': 42, 'to': 43, 'newTables': ['journey_documents']},
                      'schemaSha256': self.schema_sha, 'helperSha256': self.hashes[C.HELPER], 'evidence': {}}
        self.envelopes = {}
        for kind in ('windows', 'linux', 'browsers', 'dockerRestore', 'gitReview'):
            record = 'evidence/' + kind + '-original.txt'
            write(self.candidate / record, b'synthetic original test record - never real production evidence')
            item = {'verified': True, 'sourceHashes': self.hashes,
                    'records': [{'path': record, 'sha256': digest((self.candidate / record).read_bytes())}]}
            if kind in ('windows', 'linux'):
                item.update(exitCode=0, tests=100, passed=99, skipped=1, failed=0, errors=0)
            if kind == 'linux':
                item.update(image=IMAGE, manifestSha256=digest(self.manifest))
            if kind == 'browsers':
                item['groups'] = [{'script': 'tests/browser_synthetic.py', 'checks': 5, 'passed': True, 'externalRequests': 0}]
            if kind == 'dockerRestore':
                item.update(realDocker=True, image=IMAGE, manifestSha256=digest(self.manifest),
                            schemaSha256=self.schema_sha, restoredHouseholds=2)
            if kind == 'gitReview':
                item.update(reviewed=True, baseCommit='1'*40, mainCommit='2'*40,
                            integrationCommit='3'*40, mainTree='4'*40, integrationTree='4'*40)
                self.ready['gitReview'] = item
            self.envelopes[kind] = item
        self.freeze_evidence()
        self.runner = FakeDocker(self)

    def freeze_evidence(self):
        for kind, item in self.envelopes.items():
            path = 'evidence/' + kind + '.json'; raw = dump(item)
            write(self.candidate / path, raw)
            self.ready['evidence'][kind] = {'path': path, 'sha256': digest(raw)}
        self.freeze_ready()

    def freeze_ready(self):
        raw = dump(self.ready); write(self.candidate / 'READY.json', raw); self.ready_sha = digest(raw)

    def refreeze_source(self):
        """Approve the changed fixture bytes, so invariant checks get exercised."""
        self.hashes = {n: digest(v) for n, v in self.values.items()}
        for name, raw in self.values.items(): write(self.candidate / name, raw)
        self.manifest = dump({'files': self.hashes})
        write(self.candidate / 'RELEASE-MANIFEST.json', self.manifest)
        self.ready.update(sourceHashes=self.hashes, manifestSha256=digest(self.manifest),
                          changedFiles=sorted(n for n, v in self.hashes.items() if self.ready['baseHashes'].get(n) != v))
        for kind, item in self.envelopes.items():
            item['sourceHashes'] = self.hashes
            if kind in ('linux', 'dockerRestore'): item['manifestSha256'] = digest(self.manifest)
        self.freeze_evidence()

    def activate(self):
        return C.activate(self.candidate, IMAGE, digest(self.manifest), self.ready_sha,
                          root=self.root, releases=self.releases, runner=self.runner)

    def report(self):
        return json.loads(next(self.releases.glob('journey-documents-*/deployment.json')).read_bytes())


@pytest.fixture
def f(tmp_path, monkeypatch):
    return Fixture(tmp_path, monkeypatch)


def test_resolved_environment_is_private_exact_and_raw_dotenv_is_preserved(f, monkeypatch):
    # Compose is the parser; this fake supplies its result and the real app's
    # Config.Env independently. The actual container guard is exercised below.
    secret = '"quoted" \'single\' $cash${TOKEN}$$ C:\\private\\key\nsecond\r\n密钥=tail'
    environment = {**f.runner.compose_environment, 'SECRET_KEY': secret, 'EMPTY': ''}
    f.runner.compose_environment = environment
    f.runner.app_environment = [k + '=' + v for k, v in environment.items()] + ['IMAGE_ONLY=unchanged']
    raw = (f.root / '.env').read_bytes()
    writes = []
    original_put = C.put
    def capture(path, value, owner=False):
        if path.name == 'environment.json': writes.append((path, value, owner))
        return original_put(path, value, owner)
    monkeypatch.setattr(C, 'put', capture)
    report = f.activate()
    assert len(writes) == 1 and writes[0][2] is True
    path, stored, _ = writes[0]
    assert json.loads(stored) == environment and path.read_bytes() == stored
    assert report['resolvedEnvironmentSha256'] == digest(stored)
    assert report['inputHashes']['environment.json'] == digest(stored)
    assert report['resolvedEnvironmentMatchesRunningApp'] is True
    assert (f.root / '.env').read_bytes() == raw
    assert (Path(report['releaseDirectory']) / '.env').read_bytes() == raw
    assert secret not in json.dumps(report, ensure_ascii=False)
    assert 'SECRET_KEY' not in json.dumps(report)
    assert 'SECRET_KEY' not in (f.candidate / 'READY.json').read_text()
    assert all(secret not in arg for args in f.runner.calls for arg in args)
    assert all('--env-file' not in args for args in f.runner.calls)
    import os
    if os.name != 'nt':
        stat = path.stat()
        assert stat.st_mode & 0o777 == 0o400 and stat.st_uid == stat.st_gid == 10001


@pytest.mark.parametrize('change,label', [
    ('secret', 'running_environment_mismatch'), ('origin', 'running_environment_mismatch'),
    ('missing', 'running_environment_mismatch'), ('duplicate', 'running_environment_ambiguous'),
    ('null', 'compose_environment_invalid'), ('number', 'compose_environment_invalid'),
    ('data-dir', 'compose_environment_invalid'), ('nul-value', 'compose_environment_invalid'),
    ('bad-key', 'compose_environment_invalid'), ('malformed-running', 'running_environment_invalid'),
])
def test_resolved_environment_rejects_drift_before_any_downtime(f, change, label):
    if change in ('secret', 'origin'):
        key = 'SECRET_KEY' if change == 'secret' else 'PUBLIC_ORIGIN'
        f.runner.app_environment = [x for x in f.runner.app_environment if not x.startswith(key + '=')]
        f.runner.app_environment.append(key + '=sensitive-mismatch')
    elif change == 'missing': f.runner.app_environment = ['DATA_DIR=/data']
    elif change == 'duplicate': f.runner.app_environment.append('SECRET_KEY=sensitive-duplicate')
    elif change == 'null': f.runner.compose_environment['SECRET_KEY'] = None
    elif change == 'number': f.runner.compose_environment['SECRET_KEY'] = 123
    elif change == 'data-dir': f.runner.compose_environment['DATA_DIR'] = '/other'
    elif change == 'nul-value': f.runner.compose_environment['SECRET_KEY'] = 'bad\x00value'
    elif change == 'bad-key': f.runner.compose_environment['BAD=KEY'] = 'private'
    else: f.runner.app_environment.append('malformed-private-value')
    with pytest.raises(RuntimeError, match='^' + label + '$'):
        f.activate()
    assert not any(a[:3] == ['docker', 'compose', 'stop'] or a[:2] == ['docker', 'run'] for a in f.runner.calls)
    assert all(s['running'] for s in f.runner.services.values())
    assert not f.releases.exists() and not f.migrated.exists()


def test_raw_dotenv_drift_during_resolution_is_rejected_before_downtime(f):
    original = f.runner
    def mutate(args, **kwargs):
        result = original(args, **kwargs)
        if args[:3] == ['docker', 'compose', 'config']:
            (f.root / '.env').write_bytes(b'changed during read-only preflight')
        return result
    f.runner = mutate
    with pytest.raises(RuntimeError, match='^environment_changed$'):
        f.activate()
    assert not f.releases.exists() and all(s['running'] for s in original.services.values())
    assert not any(a[:3] == ['docker', 'compose', 'stop'] or a[:2] == ['docker', 'run'] for a in original.calls)


def test_success_real_file_install_after_backups_and_checks(f):
    result = f.activate()
    assert result['status'] == 'published' and result['automaticRestoreAttempted'] is False
    assert f.runner.actions == ['verify-image', 'snapshot', 'backup', 'validate-backup', 'warm', 'check', 'check']
    stops = [x[5:] for x in f.runner.calls if x[:3] == ['docker', 'compose', 'stop']]
    assert stops == [['web'], ['sync', 'app']]
    ups = [x[-1] for x in f.runner.calls if x[:3] == ['docker', 'compose', 'up']]
    assert ups == ['app', 'sync', 'web']
    for name, value in f.values.items():
        assert (f.root / name).read_bytes() == value
    assert (f.root / 'RELEASE-MANIFEST.json').read_bytes() == f.manifest
    release = Path(result['releaseDirectory'])
    assert (release / 'original-RELEASE-MANIFEST.json').read_bytes() == f.old_manifest
    assert (release / 'BASE-MANIFEST.json').read_bytes() == f.base_raw
    assert (release / '.env').read_bytes() == (f.root / '.env').read_bytes()
    with tarfile.open(release / 'source-before.tar.gz') as ar:
        assert ar.extractfile('RELEASE-MANIFEST.json').read() == f.old_manifest
        assert len(ar.getmembers()) == 223
        for name, value in f.base.items():
            assert ar.extractfile(name).read() == value
    for name, digest_value in result['inputHashes'].items():
        assert digest((release / 'verification' / name).read_bytes()) == digest_value
    assert 'synthetic-secret' not in json.dumps(result)


@pytest.mark.parametrize('problem', ['ready-sha', 'base-sha', 'old-manifest', 'source', 'env', 'helper',
                                    'protected-compose', 'removed-source', 'existing-new', 'image', 'compose', 'other-volume'])
def test_preflight_rejections_never_stop_services(f, problem):
    if problem == 'ready-sha': f.ready_sha = '0' * 64
    elif problem == 'base-sha': (f.candidate / 'BASE-MANIFEST.json').write_bytes(b'{}')
    elif problem == 'old-manifest': (f.root / 'RELEASE-MANIFEST.json').write_bytes(f.base_raw)
    elif problem == 'source': (f.root / 'app.py').write_bytes(b'changed')
    elif problem == 'env': (f.root / '.env').write_bytes(b'changed secret')
    elif problem == 'helper': f.ready['helperSha256'] = '0' * 64; f.freeze_ready()
    elif problem == 'protected-compose': f.values['compose.yaml'] = b'name: changed-project\n'; f.refreeze_source()
    elif problem == 'removed-source': f.values.pop('docs/synthetic-7.md'); f.refreeze_source()
    elif problem == 'existing-new': write(f.root / 'journey_documents.py', b'preexisting unknown source')
    elif problem == 'other-volume': f.runner.volume_extra = True
    else: f.runner.fail = problem
    with pytest.raises(RuntimeError) as failure: f.activate()
    if problem == 'protected-compose': assert str(failure.value) == 'protected_source_change'
    if problem == 'removed-source': assert str(failure.value) == 'source_removal'
    assert not any(x[:3] == ['docker', 'compose', 'stop'] for x in f.runner.calls)
    assert not f.migrated.exists()


@pytest.mark.parametrize('kind,key,value', [
    ('windows', 'failed', 1), ('windows', 'tests', True), ('windows', 'exitCode', 1),
    ('linux', 'image', C.PREVIOUS), ('linux', 'tests', 101), ('linux', 'sourceHashes', {}),
    ('browsers', 'groups', []), ('dockerRestore', 'realDocker', False),
    ('dockerRestore', 'restoredHouseholds', 0), ('dockerRestore', 'schemaSha256', '0'*64),
    ('gitReview', 'reviewed', False), ('gitReview', 'mainTree', '5'*40),
    ('windows', 'records', []),
])
def test_incomplete_or_wrong_evidence_rejected_before_any_docker(f, kind, key, value):
    f.envelopes[kind][key] = value; f.freeze_evidence()
    with pytest.raises(RuntimeError): f.activate()
    assert f.runner.calls == []


def test_raw_evidence_bytes_must_exist_and_match(f):
    (f.candidate / 'evidence/windows-original.txt').write_bytes(b'late edited report')
    with pytest.raises(RuntimeError, match='evidence_changed'): f.activate()
    assert not f.runner.calls


@pytest.mark.parametrize('failure', ['verify-image', 'stop', 'snapshot', 'backup', 'validate-backup', 'warm',
                                    'check', 'tag', 'up-app', 'unhealthy', 'second-check', 'up-sync', 'up-web', 'nginx'])
def test_actual_phase_failure_keeps_services_closed_and_never_restores(f, failure):
    f.runner.fail = failure
    with pytest.raises(RuntimeError, match='release_failed_at_') as error: f.activate()
    assert 'synthetic sensitive' not in str(error.value)
    report = f.report()
    assert report['status'] == 'failed' and report['automaticRestoreAttempted'] is False
    if failure == 'verify-image':
        assert not report['interrupted'] and all(s['running'] for s in f.runner.services.values())
    else:
        assert report['interrupted'] and not any(s['running'] for s in f.runner.services.values())
        assert any(x[:3] == ['docker', 'compose', 'stop'] and x[-3:] == ['web', 'sync', 'app'] for x in f.runner.calls)
    if failure in ('backup', 'validate-backup'):
        assert 'warm' not in f.runner.actions and not f.migrated.exists()
    if failure in ('check', 'tag', 'up-app', 'unhealthy', 'second-check', 'up-sync', 'up-web', 'nginx'):
        assert f.migrated.read_bytes().startswith(b'new schema was applied')
    if failure in ('up-sync', 'up-web', 'nginx'):
        assert report['commitStarted'] is True
    assert not any('restore' in x or 'down' in x for x in f.runner.calls)


@pytest.mark.parametrize('exit_code', [1, 137, 143])
def test_unclean_stop_cannot_reach_snapshot(f, exit_code):
    f.runner.stop_exit = exit_code
    with pytest.raises(RuntimeError): f.activate()
    assert f.runner.actions == ['verify-image'] and not f.migrated.exists()


@pytest.mark.parametrize('target', ['environment', 'resolved-environment', 'candidate', 'before', 'schema', 'backup', 'root-compose'])
def test_hash_drift_after_stop_blocks_warm_without_overwriting_originals(f, target):
    def mutate(action, inputs):
        if action != 'validate-backup': return
        path = {'environment': f.root / '.env', 'candidate': f.candidate / 'app.py',
                'resolved-environment': inputs / 'environment.json',
                'before': inputs / 'before.json', 'schema': inputs / 'schema.json',
                'backup': inputs / 'backup.json', 'root-compose': f.root / 'compose.yaml'}[target]
        path.chmod(0o600); path.write_bytes(b'changed after verification')
    f.runner.mutate = mutate
    with pytest.raises(RuntimeError): f.activate()
    assert 'warm' not in f.runner.actions and not f.migrated.exists()
    assert not any(s['running'] for s in f.runner.services.values())
    assert (f.root / 'RELEASE-MANIFEST.json').read_bytes() == f.old_manifest


def test_false_schema_proof_cannot_start_application(f):
    f.runner.bad_check = True
    with pytest.raises(RuntimeError): f.activate()
    assert not any(x[:3] == ['docker', 'compose', 'up'] for x in f.runner.calls)
    assert f.migrated.exists()


def test_partial_source_install_failure_keeps_snapshot_and_does_not_start_app(f, monkeypatch):
    original_put = C.put
    writes = []
    def disk_failure(path, value, owner=False):
        if path.name.endswith('.journey-release-tmp'):
            writes.append(path)
            if len(writes) == 2:
                raise OSError('synthetic disk write failure')
        return original_put(path, value, owner)
    monkeypatch.setattr(C, 'put', disk_failure)
    with pytest.raises(RuntimeError, match='release_failed_at_install-source'): f.activate()
    assert f.migrated.exists() and not any(s['running'] for s in f.runner.services.values())
    assert not any(x[:3] == ['docker', 'compose', 'up'] for x in f.runner.calls)
    # The first changed file remains as evidence; no blind source rollback.
    assert (f.root / 'Dockerfile').read_bytes() == f.values['Dockerfile']
    assert (f.root / 'app.py').read_bytes() == f.base['app.py']
    report = f.report()
    assert report['automaticRestoreAttempted'] is False
    with tarfile.open(Path(report['releaseDirectory']) / 'source-before.tar.gz') as archive:
        for name, raw in f.base.items():
            assert archive.extractfile(name).read() == raw
    assert (f.root / 'RELEASE-MANIFEST.json').read_bytes() == f.old_manifest


@pytest.mark.parametrize('action', ['verify-image', 'warm', 'check'])
def test_client_timeout_stops_only_this_release_helper_and_preserves_scene(f, action):
    f.runner.fail = 'timeout-' + action
    with pytest.raises(RuntimeError): f.activate()
    assert f.runner.helpers and not any(x['running'] for x in f.runner.helpers.values())
    report = f.report()
    assert len(report['helpersStoppedAfterFailure']) == 1
    assert report['automaticRestoreAttempted'] is False
    assert all(s['running'] for s in f.runner.services.values()) == (action == 'verify-image')
    if action == 'check':
        assert f.migrated.exists()
    assert all(x[-1] == 'f' * 64 for x in f.runner.calls if x[:2] == ['docker', 'stop'])


def test_command_timeout_hides_process_output(monkeypatch, tmp_path):
    def expired(*args, **kwargs):
        raise subprocess.TimeoutExpired(['synthetic'], 1, output=b'private output', stderr=b'private error')
    monkeypatch.setattr(subprocess, 'run', expired)
    with pytest.raises(RuntimeError, match='^command_timeout$'):
        C.command(['synthetic'], cwd=tmp_path, timeout=1)


@pytest.mark.parametrize('name', ['../.env', '/outside', 'docs/../../.env', '.env', 'docs/.env.secret',
                                'docs/f.sqlite3', 'test-results/private.json', 'C:/private', 'docs\\secret'])
def test_manifest_and_evidence_paths_cannot_escape_or_include_private_inputs(name):
    with pytest.raises(RuntimeError): C.relative(name)


@pytest.mark.parametrize('secret', ['"double" and \'single\'', '$cash${TOKEN}$$', r'C:\private\path',
                                    'first\nsecond\r\nthird', ' unicode 密钥 = with spaces '])
def test_container_guard_checks_image_source_and_backup_manifest_before_runpy(secret):
    # Execute the real stdin guard with a synthetic in-memory filesystem and a
    # fake runpy, not a second implementation of its checks.
    import sys
    import os
    code = compile(C.CONTAINER_CODE, '<real-container-guard>', 'exec')
    source = b'# candidate module'; backup_bytes = b'{"frozen":"backup"}'
    frozen = {'manifestSha256': digest(b'manifest'), 'sourceHashes': {'app.py': digest(source)},
              'runtimeHashes': {'app.py': digest(source)}}
    payloads = {'/release-check/frozen.json': C.encoded(frozen), '/release-source/RELEASE-MANIFEST.json': b'manifest',
                '/release-check/environment.json': C.encoded({'DATA_DIR': '/data', 'SECRET_KEY': secret,
                                                             'PUBLIC_ORIGIN': 'https://synthetic.invalid'}),
                '/release-source/app.py': source, '/app/app.py': source,
                '/release-check/backup.json': C.encoded({'manifest': 'manifest-2026Z.json'}),
                '/release-check/backup-verification.json': C.encoded({'manifestSha256': digest(backup_bytes)}),
                '/data/backups/manifest-2026Z.json': backup_bytes}
    expected = {p.rsplit('/', 1)[1]: digest(v) for p, v in payloads.items() if p.startswith('/release-check/')}
    class FakePath:
        def __init__(self, path): self.path = str(path)
        def __truediv__(self, item): return FakePath(self.path + '/' + str(item))
        def __str__(self): return self.path
        @property
        def name(self): return self.path.rsplit('/', 1)[-1]
        def read_bytes(self): return payloads[self.path]
    from unittest.mock import patch
    with patch('pathlib.Path', FakePath), patch('runpy.run_path') as dispatch, patch.object(sys, 'path', list(sys.path)), patch.dict('os.environ', {}, clear=True):
        def execute():
            with patch.object(sys, 'argv', ['-', 'check', json.dumps(expected)]):
                exec(code, {})
        execute()
        assert dispatch.call_count == 1
        assert os.environ['SECRET_KEY'] == secret
        assert os.environ['PUBLIC_ORIGIN'] == 'https://synthetic.invalid'
        dispatch.reset_mock()
        payloads['/app/app.py'] = b'different runtime'
        with pytest.raises(RuntimeError, match='frozen_input_mismatch'): execute()
        assert not dispatch.called
        payloads['/app/app.py'] = source
        payloads['/data/backups/manifest-2026Z.json'] = b'different backup'
        with pytest.raises(RuntimeError, match='frozen_input_mismatch'): execute()
        assert not dispatch.called
        payloads['/data/backups/manifest-2026Z.json'] = backup_bytes
        original_environment = payloads['/release-check/environment.json']
        payloads['/release-check/environment.json'] = C.encoded({'DATA_DIR': '/data', 'SECRET_KEY': 'tampered'})
        with pytest.raises(RuntimeError, match='frozen_input_mismatch'): execute()
        assert not dispatch.called
        payloads['/release-check/environment.json'] = original_environment
        del expected['environment.json']
        with pytest.raises(RuntimeError, match='frozen_input_mismatch'): execute()
        assert not dispatch.called
