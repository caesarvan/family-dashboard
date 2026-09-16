"""Synthetic source/files and command stubs; no real Docker or production.

SQLite migration semantics are separately exercised with actual temporary DBs.
Synthetic READY envelopes below test gates, never serve as release evidence.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import tarfile

import pytest
from deploy import activate_journey_places_release as C

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'sha256:' + '9' * 64

def digest(value): return hashlib.sha256(value).hexdigest()
def dump(value): return json.dumps(value, ensure_ascii=False).encode()
def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(value)

@pytest.fixture(autouse=True)
def no_processes_or_network(monkeypatch):
    def deny(*a, **k): raise AssertionError('No real process/network in command-stub tests')
    monkeypatch.setattr(subprocess, 'run', deny)
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket, 'create_connection', deny)


class FakeDocker:
    def __init__(self, fixture):
        self.f = fixture
        self.calls = []
        self.raw_calls = []
        self.environments = []
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
        self.compose_extra = {}
        self.services = {n: {'id': str(i) * 64, 'image': fixture.previous if n != 'web' else 'sha256:' + '8' * 64,
                             'running': True, 'exitCode': 0, 'oom': False,
                             'health': 'healthy' if n == 'app' else None}
                         for i, n in enumerate(('web', 'sync', 'app'), 1)}

    def result(self):
        return {'households': 2, 'originalTablesPreserved': 43, 'newTables': 1, 'newTableEmpty': True, 'backup': self.proof(),
                'schemaIndexesAndTriggersVerified': True, 'allOriginalRowsAndSequencesPreserved': True}

    def proof(self):
        return {'databases': 3, 'manifestSha256': digest(b'{"synthetic":true}'), 'groupVerified': True}

    def __call__(self, args, *, cwd, env, input_bytes=None, timeout=180):
        assert Path(cwd) == self.f.root
        assert isinstance(env, dict) and not any(k.upper().startswith(('COMPOSE_', 'DOCKER_')) for k in env)
        self.raw_calls.append(list(args))
        self.environments.append(dict(env))
        if args[:2] == ['docker', 'compose']:
            assert args[2:8] == ['--project-name', self.f.project,
                                '--file', str(self.f.root / 'compose.yaml'),
                                '--env-file', str(self.f.root / '.env')]
            args = args[:2] + args[8:]
        self.calls.append(list(args))
        if args[:3] == ['docker', 'compose', 'ps']:
            return self.services[args[-1]]['id']
        if args[:2] == ['docker', 'inspect']:
            state = next(v for v in [*self.services.values(), *self.helpers.values()] if v['id'] == args[-1])
            if args[3] == '{{json .Config.Env}}':
                assert state is self.services['app']
                return json.dumps(self.app_environment)
            if args[3] == '{{json .Mounts}}':
                return json.dumps([{'Type': 'volume', 'Name': self.f.volume, 'Destination': '/data', 'RW': True}])
            if args[3] == '{{json .Config.Labels}}':
                return json.dumps({'family-dashboard.journey-places-release': self.label})
            return json.dumps(state)
        if args[:3] == ['docker', 'image', 'inspect']:
            if self.fail == 'image':
                raise RuntimeError('fake image missing')
            if len(args) == 4:
                layers = ['sha256:' + 'a' * 64]
                config = {'User':'dashboard','Env':['DATA_DIR=/data','PYTHONDONTWRITEBYTECODE=1'],'Cmd':['gunicorn']}
                if args[-1] == IMAGE:
                    layers += ['sha256:' + 'b' * 64]
                    if self.fail == 'layers': layers.append('extra')
                    if self.fail == 'image-config': config['User']='root'
                return json.dumps([{'Id':args[-1],'Config':config,'RootFS':{'Layers':layers}}])
            return IMAGE
        if args[:3] == ['docker', 'compose', 'config']:
            if self.fail == 'compose':
                raise RuntimeError('fake compose invalid')
            assert args[3:] == ['--format', 'json']
            # Compose 2.40.3 escapeDollarSign runs after JSON serialization.
            return json.dumps({'services': {'app': {'environment': self.compose_environment,
                                                   **self.compose_extra}}}).replace('$', '$$')
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
            assert args[2:] == [IMAGE, self.f.project + '-app']
            if self.fail == 'tag':
                raise RuntimeError('fake tag failed')
            return ''
        if args[:3] == ['docker', 'compose', 'up']:
            n = args[-1]
            if self.fail == 'up-' + n:
                raise RuntimeError('fake startup failed')
            if n in ('sync', 'web'):
                assert self.actions.count('check') == 3
                assert self.services['app']['health'] == 'healthy'
            self.services[n].update(running=True, exitCode=0)
            if n != 'web':
                self.services[n]['image'] = IMAGE
            if n == 'app' and self.fail == 'unhealthy':
                self.services[n]['health'] = 'unhealthy'
            return ''
        if args[:3] == ['docker', 'compose', 'exec']:
            if 'app' in args:
                assert self.actions.count('check') == 2
                assert not self.services['web']['running'] and not self.services['sync']['running']
                if self.fail == 'http': raise RuntimeError('fake private HTTP error')
                result={'healthStatus':200,'staticAssets':{n:{'status':200,'sha256':d} for n,d in C.static_hashes(self.f.hashes).items()},'anonymousChecks':{n:401 for n in C.ANONYMOUS_PATHS}}
                if self.fail == 'anonymous': result['anonymousChecks'][C.ANONYMOUS_PATHS[0]]=200
                if self.fail == 'static': result['staticAssets']['static/example.js']['sha256']='0'*64
                return json.dumps(result)
            if self.fail == 'nginx':
                raise RuntimeError('fake nginx invalid')
            return ''
        assert args[:2] == ['docker', 'run'], args
        action = args[-2]; self.actions.append(action)
        self.label=args[args.index('--label')+1].split('=',1)[1]
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
            assert any(x == 'type=volume,src=' + self.f.volume + ',dst=/data' for x in mounts)
            assert not self.services['web']['running'] and not self.services['sync']['running']
        if self.mutate:
            self.mutate(action, inputs)
        if self.fail == 'timeout-' + action:
            name = args[args.index('--name') + 1]
            self.helpers[name] = {'id': 'f' * 64, 'image': IMAGE, 'running': True,
                                  'exitCode': 0, 'oom': False, 'health': None}
            raise RuntimeError('command_timeout')
        if self.fail == action or (self.fail == 'second-check' and action == 'check' and self.actions.count('check') == 3):
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
        assert action in ('check','warm')
        result = self.result()
        if action == 'warm': result.update(cloudTicks=0, modelRequests=0)
        if self.bad_check:
            result['schemaIndexesAndTriggersVerified'] = False
        return json.dumps(result)


class Fixture:
    def __init__(self, path):
        self.root = path/'family-dashboard'; self.candidate = path/'family-dashboard-candidate-journey-places-synthetic'
        self.releases = path/'releases'; self.data = path/'fake-volume'; self.data.mkdir()
        self.previous = 'sha256:'+'7'*64; self.project = 'synthetic-places'; self.volume = self.project+'_household-data'
        names = {*C.DEPENDENCIES, 'app.py','requirements.txt','Dockerfile','compose.yaml','journey_documents.py','deploy/backup.py'}
        self.base = {n:(ROOT/n).read_bytes() for n in names}
        self.base.update({'static/index.html':b'<html>old</html>', 'static/example.js':b'/* old */',
                          'deploy/prepare_release.py':b'# previous explicit packaging list\n',
                          'tests/browser_synthetic.py':b'# synthetic browser fixture\n'})
        self.base_raw = dump({'files':{n:digest(v) for n,v in self.base.items()}})
        self.old_manifest = self.base_raw
        for name,value in self.base.items(): write(self.root/name,value)
        write(self.root/'RELEASE-MANIFEST.json',self.old_manifest)
        write(self.root/'.env',b'SECRET_KEY="synthetic-secret-do-not-print"\n')
        self.values = dict(self.base)
        self.values.update({n:(ROOT/n).read_bytes() for n in C.REQUIRED - C.DEVELOPMENT_TOOLS})
        self.values.update({n:b'# synthetic development package\n' for n in C.DEVELOPMENT_TOOLS})
        self.values.update({'static/index.html':b'<html>new</html>', 'static/example.js':b'/* new */',
                            'app.py':self.base['app.py']+b'\n# synthetic reviewed wiring\n',
                            'tests/test_journey_places_release.py':Path(__file__).read_bytes()})
        self.ready = {'version':1,'mode':C.POLICY.mode,'verified':True,'image':IMAGE,'previousImage':self.previous,
                      'baseManifestSha256':digest(self.base_raw),'baseHashes':json.loads(self.base_raw)['files'],
                      'oldManifestSha256':digest(self.old_manifest),'environmentSha256':digest((self.root/'.env').read_bytes()),
                      'schema':C.SCHEMA_CONTRACT}
        write(self.candidate/'BASE-MANIFEST.json',self.base_raw)
        self.runner = FakeDocker(self); self.refreeze_source()

    def ref(self,name,raw):
        write(self.candidate/name,raw); return {'path':name,'sha256':digest(raw)}

    def refreeze_source(self):
        for n,v in self.values.items(): write(self.candidate/n,v)
        self.hashes = {n:digest(v) for n,v in self.values.items()}; self.manifest=dump({'files':self.hashes})
        write(self.candidate/'RELEASE-MANIFEST.json',self.manifest)
        self.ready.update(sourceHashes=self.hashes,manifestSha256=digest(self.manifest),
                          changedFiles=sorted(n for n,d in self.hashes.items() if self.ready['baseHashes'].get(n)!=d),
                          approvedRuntimeChanges=C.runtime_changes(self.ready['baseHashes'],self.hashes),
                          schemaSha256=C.schema_definition(self.values)['sha256'],helperSha256=self.hashes[C.HELPER])
        self.envelopes={}
        for kind in ('placesBuild','windows','linux','browsers','migrationSafety','dockerRestore','gitReview'):
            ref=self.ref('evidence/'+kind+'-raw.txt',b'Synthetic command-stub evidence; not an actual release.')
            self.envelopes[kind]={'verified':True,'sourceHashes':self.hashes,'records':[ref]}
        self.envelopes['placesBuild'].update(image=IMAGE,parentImage=self.previous,mode=C.POLICY.mode,
            manifestSha256=digest(self.manifest),baseManifestSha256=digest(self.base_raw),
            parentRuntimeHashes={**C.backend_hashes(self.ready['baseHashes']),**C.static_hashes(self.ready['baseHashes'])},
            candidateRuntimeHashes={**C.backend_hashes(self.hashes),**C.static_hashes(self.hashes)},
            runtimeChanges=self.ready['approvedRuntimeChanges'],parentLayersPreserved=True,configurationUnchanged=True,
            parentBackendVerified=True,childBackendVerified=True,staticVerified=True,bytecodeExcluded=True,pipExecuted=False)
        for platform in ('windows','linux'):
            junit=self.ref('evidence/'+platform+'.xml',b'<testsuite><testcase classname="tests.test_journey_places_release" name="synthetic_case"/></testsuite>')
            log=self.ref('evidence/'+platform+'.log',b'Synthetic command-stub test log.')
            self.envelopes[platform].update(image=IMAGE,exitCode=0,tests=1,passed=1,failed=0,errors=0,skipped=0,
                scripts=['tests/test_journey_places_release.py'],junit=junit,log=log)
        self.envelopes['browsers'].update(groups=[{'script':'tests/browser_synthetic.py','passed':True,'checks':1,'externalRequests':0}])
        for kind in ('migrationSafety','dockerRestore'):
            self.envelopes[kind].update(realDocker=True,image=IMAGE,manifestSha256=digest(self.manifest),
                schemaSha256=self.ready['schemaSha256'],households=2,checks=1,productionWrites=0,allPassed=True)
        self.envelopes['migrationSafety'].update(originalTablesPreserved=43,newTables=1,newTableEmpty=True)
        self.envelopes['dockerRestore'].update(householdTables=44,placesRestored=True,oldSessionsRevoked=True)
        self.envelopes['gitReview'].update(reviewed=True,baseCommit='1'*40,mainCommit='2'*40,integrationCommit='3'*40,
            mainTree='4'*40,integrationTree='4'*40,approvedRuntimeChanges=self.ready['approvedRuntimeChanges'])
        self.freeze_evidence()

    def freeze_evidence(self):
        self.ready['evidence']={kind:self.ref('evidence/'+kind+'.json',dump(value)) for kind,value in self.envelopes.items()}
        self.ready['gitReview']=deepcopy(self.envelopes['gitReview']); self.freeze_ready()

    def freeze_ready(self):
        self.ready_raw=dump(self.ready); write(self.candidate/'READY.json',self.ready_raw)

    def activate(self):
        return C.activate(self.candidate,IMAGE,digest(self.manifest),digest(self.ready_raw),root=self.root,
                          releases=self.releases,project=self.project,volume=self.volume,runner=self.runner)


@pytest.fixture
def f(tmp_path): return Fixture(tmp_path)


def report(f):
    paths=list(f.releases.glob('journey-places-*/deployment.json')); assert len(paths)==1
    return json.loads(paths[0].read_bytes())


def test_transaction_migrates_before_install_and_exposes_services_after_three_readbacks(f):
    result=f.activate()
    assert result['status']=='published' and result['newTables']==1 and result['originalTablesPreserved']==43
    assert result['automaticRestoreAttempted'] is False and result['environmentPreserved'] is True
    assert f.runner.actions == ['verify-image','snapshot','backup','validate-backup','warm','check','check','check']
    assert (f.root/'.env').read_bytes()==b'SECRET_KEY="synthetic-secret-do-not-print"\n'
    assert all((f.root/n).read_bytes()==v for n,v in f.values.items())
    assert result['httpReadback']['anonymousChecks']['/api/journey-places']==401
    assert (Path(result['releaseDirectory'])/'verification/schema.json').is_file()


@pytest.mark.parametrize('failure', ['verify-image','snapshot','backup','validate-backup','warm','check','second-check',
                                    'tag','up-app','unhealthy','http','anonymous','static','up-sync','up-web','nginx','timeout-warm'])
def test_failures_never_restore_or_leave_services_open(f,failure):
    f.runner.fail=failure
    with pytest.raises(RuntimeError,match='release_failed_at_') as error: f.activate()
    assert 'sensitive' not in str(error.value) and 'synthetic-secret' not in str(error.value)
    value=report(f); assert value['status']=='failed' and value['automaticRestoreAttempted'] is False
    if failure!='verify-image': assert all(not v['running'] for v in f.runner.services.values())
    assert not any(arg in ('restore','rollback') for args in f.runner.calls for arg in args)
    if failure=='timeout-warm':
        assert value['helpersStoppedAfterFailure'] and all(not h['running'] for h in f.runner.helpers.values())


@pytest.mark.parametrize('exit_code',[1,137,143])
def test_unclean_stop_blocks_any_database_helper(f,exit_code):
    f.runner.stop_exit=exit_code
    with pytest.raises(RuntimeError): f.activate()
    assert f.runner.actions==['verify-image']


@pytest.mark.parametrize('key,value', [('schema',{'from':43,'to':43,'newTables':[]}),('schemaSha256','0'*64),
                                      ('helperSha256','0'*64),('approvedRuntimeChanges',[]),('environmentSha256','0'*64)])
def test_preflight_binding_rejects_before_downtime(f,key,value):
    f.ready[key]=value; f.freeze_ready()
    with pytest.raises(RuntimeError): f.activate()
    assert not f.runner.calls


@pytest.mark.parametrize('kind,key,value', [
    ('placesBuild','pipExecuted',True),('placesBuild','bytecodeExcluded',False),
    ('migrationSafety','realDocker',False),('migrationSafety','newTables',0),('migrationSafety','households',1),
    ('dockerRestore','householdTables',43),('dockerRestore','placesRestored',False),('dockerRestore','oldSessionsRevoked',False),
    ('linux','image','sha256:'+'0'*64),('windows','passed',2),('gitReview','reviewed',False)])
def test_insufficient_evidence_blocks_before_downtime(f,kind,key,value):
    f.envelopes[kind][key]=value; f.freeze_evidence()
    with pytest.raises(RuntimeError): f.activate()
    assert not f.runner.calls


def test_raw_junit_failure_cannot_be_hidden_by_passing_envelope(f):
    f.envelopes['windows']['junit']=f.ref('evidence/failure.xml',b'<testsuite><testcase classname="tests.test_journey_places_release"><failure/></testcase></testsuite>')
    f.freeze_evidence()
    with pytest.raises(RuntimeError,match='backend_junit'): f.activate()
    assert not f.runner.calls


@pytest.mark.parametrize('path',['compose.yaml','requirements.txt','deploy/backup.py','deploy/release_core.py','extra.py','tools/arbitrary.py'])
def test_protected_paths_and_extra_backend_modules_are_not_allowed(f,path):
    f.values[path]=f.values.get(path,b'')+b'\n# change\n'; f.refreeze_source()
    with pytest.raises(RuntimeError): f.activate()
    assert not f.runner.calls


def test_runtime_input_drift_after_stop_blocks_warm(f):
    def mutate(action,inputs):
        if action=='validate-backup': (inputs/'schema.json').write_bytes(b'{}')
    f.runner.mutate=mutate
    with pytest.raises(RuntimeError): f.activate()
    assert 'warm' not in f.runner.actions and all(not v['running'] for v in f.runner.services.values())


def test_compose_resolution_change_blocks_restart(f):
    def mutate(action,inputs):
        if action=='warm': f.runner.compose_extra['privileged']=True
    f.runner.mutate=mutate
    with pytest.raises(RuntimeError): f.activate()
    assert report(f)['phase']=='start-application' and all(not v['running'] for v in f.runner.services.values())


@pytest.mark.parametrize('name',['DOCKER_HOST','COMPOSE_FILE','COMPOSE_PROJECT_NAME'])
def test_host_docker_selectors_rejected_before_commands(f,monkeypatch,name):
    monkeypatch.setenv(name,'untrusted')
    with pytest.raises(RuntimeError,match='host_docker_compose_environment'): f.activate()
    assert not f.runner.calls


def test_lock_serializes_with_old_source_controller(f):
    with C.release_lock(f.releases):
        with pytest.raises(RuntimeError,match='another_static_release_running'): f.activate()
    assert not f.runner.calls


def test_partial_source_install_keeps_approved_backup_and_before_archive(f,monkeypatch):
    original=C.put; installed=[]
    def interrupted(path,value,owner=False):
        if path.name.endswith('.journey-places-release-tmp'):
            installed.append(path)
            if len(installed)==2:raise OSError('synthetic interrupted install')
        return original(path,value,owner)
    monkeypatch.setattr(C,'put',interrupted)
    with pytest.raises(RuntimeError,match='release_failed_at_install-source'):f.activate()
    value=report(f)
    assert value['manualReviewRequired'] and not value['automaticRestoreAttempted']
    assert all(not s['running'] for s in f.runner.services.values())
    assert (f.root/'RELEASE-MANIFEST.json').read_bytes()==f.old_manifest
    with tarfile.open(Path(value['releaseDirectory'])/'source-before.tar.gz') as archive:
        assert all(archive.extractfile(name).read()==raw for name,raw in f.base.items())
    assert value['backupVerification']==f.runner.proof()


def test_existing_install_temporary_is_never_overwritten(f):
    first=f.ready['changedFiles'][0]
    target=f.root/first
    temporary=target.with_name(target.name+'.journey-places-release-tmp')
    write(temporary,b'pre-existing sentinel')
    with pytest.raises(RuntimeError):f.activate()
    assert temporary.read_bytes()==b'pre-existing sentinel'
    assert not f.runner.calls


def test_late_install_temporary_is_rechecked_without_overwriting(f):
    target=f.root/f.ready['changedFiles'][0]
    temporary=target.with_name(target.name+'.journey-places-release-tmp')
    def mutate(action,inputs):
        if action=='warm':write(temporary,b'late sentinel')
    f.runner.mutate=mutate
    with pytest.raises(RuntimeError):f.activate()
    assert temporary.read_bytes()==b'late sentinel' and 'warm' in f.runner.actions
    assert all(not s['running'] for s in f.runner.services.values())


def test_secret_environment_dollars_survive_without_argv_or_report_exposure(f):
    secret='synthetic $literal $$ pair with spaces'
    f.runner.compose_environment['NVIDIA_API_KEY']=secret
    f.runner.app_environment.append('NVIDIA_API_KEY='+secret)
    value=f.activate()
    private=Path(value['releaseDirectory'])/'verification/environment.json'
    assert json.loads(private.read_bytes())['NVIDIA_API_KEY']==secret
    assert secret not in json.dumps(f.runner.raw_calls)+json.dumps(value)


def test_abort_exception_after_warm_stops_all_services(f):
    def mutate(action,inputs):
        if action=='warm':raise KeyboardInterrupt()
    f.runner.mutate=mutate
    with pytest.raises(RuntimeError,match='release_failed_at_warm'):f.activate()
    assert all(not s['running'] for s in f.runner.services.values())
    assert report(f)['errorType']=='KeyboardInterrupt'
