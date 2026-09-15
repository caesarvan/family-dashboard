"""Real controller/file flow with a fake Docker runner; no real Docker/SSH.

Database semantics belong to test_static_release_database.py. These tests
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
SPEC = importlib.util.spec_from_file_location('static_release_under_test', ROOT / 'deploy/activate_static_release.py')
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
        self.services = {n: {'id': str(i) * 64, 'image': fixture.previous if n != 'web' else 'sha256:' + '8' * 64,
                             'running': True, 'exitCode': 0, 'oom': False,
                             'health': 'healthy' if n == 'app' else None}
                         for i, n in enumerate(('web', 'sync', 'app'), 1)}

    def result(self):
        return {'households': 2, 'originalTablesPreserved': 43, 'newTables': 0, 'backup': self.proof(),
                'schemaIndexesAndTriggersVerified': True, 'allOriginalRowsAndSequencesPreserved': True}

    def proof(self):
        return {'databases': 3, 'manifestSha256': digest(b'{"synthetic":true}'), 'groupVerified': True}

    def __call__(self, args, *, cwd, input_bytes=None, timeout=180):
        assert Path(cwd) == self.f.root
        if args[:2] == ['docker', 'compose']:
            assert args[2:4] == ['--project-name', self.f.project]
            args = args[:2] + args[4:]
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
                return json.dumps({'family-dashboard.static-release': self.label})
            return json.dumps(state)
        if args[:3] == ['docker', 'image', 'inspect']:
            if self.fail == 'image':
                raise RuntimeError('fake image missing')
            if len(args) == 4:
                layers = ['sha256:' + 'a' * 64]
                config = {'User':'dashboard','Env':['DATA_DIR=/data'],'Cmd':['gunicorn']}
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
            return json.dumps({'services': {'app': {'environment': self.compose_environment}}}).replace('$', '$$')
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
        assert action == 'check'
        result = self.result()
        if self.bad_check:
            result['schemaIndexesAndTriggersVerified'] = False
        return json.dumps(result)


class Fixture:
    def __init__(self, tmp_path):
        self.root = tmp_path / 'family-dashboard'
        self.candidate = tmp_path / 'family-dashboard-candidate-static-synthetic'
        self.releases = tmp_path / 'releases'
        self.data = tmp_path / 'fake-data-volume'; self.data.mkdir()
        self.previous = 'sha256:' + '7' * 64
        self.project = 'synthetic-static'
        self.volume = self.project + '_household-data'
        self.base = {n: (ROOT / n).read_bytes() for n in C.REQUIRED - {C.HELPER, C.CONTROLLER}}
        self.base.update({'static/example.js': b'/* old static */\n',
                          'tests/browser_synthetic.py': b'# synthetic\n',
                          'docs/example.md': b'original documentation\n'})
        self.base_raw = dump({'files': {n: digest(v) for n, v in self.base.items()}})
        self.old_manifest = dump({'files': {'historical.txt': '0' * 64}, 'history': True})
        for n, v in self.base.items(): write(self.root / n, v)
        write(self.root / 'RELEASE-MANIFEST.json', self.old_manifest)
        write(self.root / '.env', b'SECRET_KEY="synthetic-secret-do-not-print"\n')
        self.values = {**self.base, 'static/example.js': b'/* reviewed new static */\n',
                       'docs/example.md': b'reviewed documentation\n',
                       C.HELPER: (ROOT / C.HELPER).read_bytes(),
                       C.CONTROLLER: (ROOT / C.CONTROLLER).read_bytes()}
        self.ready = {'version': 1, 'mode': 'static-only', 'verified': True,
                      'image': IMAGE, 'previousImage': self.previous,
                      'baseManifestSha256': digest(self.base_raw),
                      'baseHashes': json.loads(self.base_raw)['files'],
                      'oldManifestSha256': digest(self.old_manifest),
                      'environmentSha256': digest((self.root / '.env').read_bytes()),
                      'schema': {'from':43,'to':43,'newTables':[]}}
        write(self.candidate / 'BASE-MANIFEST.json', self.base_raw)
        self.runner = FakeDocker(self)
        self.refreeze_source()

    def refreeze_source(self):
        for n, v in self.values.items(): write(self.candidate / n, v)
        self.hashes = {n:digest(v) for n,v in self.values.items()}
        self.manifest = dump({'files': self.hashes})
        write(self.candidate / 'RELEASE-MANIFEST.json', self.manifest)
        self.ready.update(sourceHashes=self.hashes, manifestSha256=digest(self.manifest),
                          changedFiles=sorted(n for n,d in self.hashes.items() if self.ready['baseHashes'].get(n)!=d))
        self.envelopes = {}
        for kind in ('staticBuild','backendReuse','browsers','releaseSafety','gitReview'):
            record='evidence/'+kind+'-original.txt'
            raw=b'Synthetic fake-runner evidence, not actual Docker or a production result.'
            write(self.candidate / record,raw)
            self.envelopes[kind]={'verified':True,'sourceHashes':self.hashes,
                                  'records':[{'path':record,'sha256':digest(raw)}]}
        self.envelopes['staticBuild'].update(image=IMAGE,parentImage=self.previous,
            manifestSha256=digest(self.manifest),nonStaticRuntimeHashes=C.backend_hashes(self.hashes),
            staticHashes=C.static_hashes(self.hashes),parentLayersPreserved=True,configurationUnchanged=True,pipExecuted=False)
        self.envelopes['backendReuse'].update(coverageMode='unchanged-backend-dependencies',
            previousImage=self.previous,nonStaticRuntimeHashes=C.backend_hashes(self.hashes),singleFullRunPassed=False,
            windows={'tests':10,'passed':9,'skipped':1},linux={'tests':10,'passed':10,'skipped':0})
        self.envelopes['browsers'].update(groups=[{'script':'tests/browser_synthetic.py','checks':2,'passed':True,'externalRequests':0}])
        self.envelopes['releaseSafety'].update(realDocker=True,image=IMAGE,manifestSha256=digest(self.manifest),
            households=2,checks=2,originalTablesPreserved=43,newTables=0,productionWrites=0,allPassed=True)
        self.envelopes['gitReview'].update(reviewed=True,baseCommit='1'*40,mainCommit='2'*40,integrationCommit='3'*40,
                                            mainTree='4'*40,integrationTree='4'*40)
        self.freeze_evidence()

    def freeze_evidence(self):
        self.ready['evidence']={}
        for kind,item in self.envelopes.items():
            path='evidence/'+kind+'.json';raw=dump(item);write(self.candidate/path,raw)
            self.ready['evidence'][kind]={'path':path,'sha256':digest(raw)}
        self.ready['gitReview']=self.envelopes['gitReview']
        self.freeze_ready()

    def freeze_ready(self):
        raw=dump(self.ready);write(self.candidate/'READY.json',raw);self.ready_sha=digest(raw)

    def activate(self):
        return C.activate(self.candidate,IMAGE,digest(self.manifest),self.ready_sha,
                          root=self.root,releases=self.releases,project=self.project,volume=self.volume,runner=self.runner)

    def report(self):
        return json.loads(next(self.releases.glob('static-*/deployment.json')).read_bytes())


@pytest.fixture
def f(tmp_path):
    return Fixture(tmp_path)


def test_success_preserves_originals_and_opens_writers_only_after_http_and_three_checks(f):
    r=f.activate()
    assert r['status']=='published' and r['originalTablesPreserved']==43 and r['newTables']==0
    assert f.runner.actions==['verify-image','snapshot','backup','validate-backup','check','check','check']
    assert r['automaticRestoreAttempted'] is False
    assert [x[5:] for x in f.runner.calls if x[:3]==['docker','compose','stop']]==[['web'],['sync','app']]
    assert [x[-1] for x in f.runner.calls if x[:3]==['docker','compose','up']]==['app','sync','web']
    assert all((f.root/n).read_bytes()==v for n,v in f.values.items())
    release=Path(r['releaseDirectory'])
    assert (release/'.env').read_bytes()==(f.root/'.env').read_bytes()
    with tarfile.open(release/'source-before.tar.gz') as archive:
        assert archive.extractfile('RELEASE-MANIFEST.json').read()==f.old_manifest
        assert all(archive.extractfile(n).read()==v for n,v in f.base.items())
    assert 'synthetic-secret' not in json.dumps(r)


@pytest.mark.parametrize('name',['app.py','requirements.txt','Dockerfile','compose.yaml',
    'deploy/backup.py','deploy/nginx.conf','deploy/arbitrary.py'])
def test_static_contract_rejects_backend_configuration_and_unapproved_tool_changes(f,name):
    f.values[name]=b'changed';f.refreeze_source()
    with pytest.raises(RuntimeError,match='protected_source_change'):f.activate()
    assert not f.runner.calls


@pytest.mark.parametrize('problem',['ready-sha','base-sha','old-manifest','source','env','removed',
    'unlisted','dependency','layers','image-config','compose','other-volume'])
def test_preflight_failure_does_not_stop_old_services(f,problem):
    if problem=='ready-sha':f.ready_sha='0'*64
    elif problem=='base-sha':write(f.candidate/'BASE-MANIFEST.json',b'{}')
    elif problem=='old-manifest':write(f.root/'RELEASE-MANIFEST.json',f.base_raw)
    elif problem=='source':write(f.root/'app.py',b'changed')
    elif problem=='env':write(f.root/'.env',b'changed')
    elif problem=='removed':f.values.pop('docs/example.md');f.refreeze_source()
    elif problem=='unlisted':write(f.candidate/'static/hidden.js',b'unlisted')
    elif problem=='dependency':f.values['deploy/check_journey_documents_migration.py']=b'changed';f.refreeze_source()
    elif problem=='other-volume':f.runner.volume_extra=True
    else:f.runner.fail=problem
    with pytest.raises(RuntimeError):f.activate()
    assert not any(x[:3]==['docker','compose','stop'] for x in f.runner.calls)


@pytest.mark.parametrize('kind,key,value',[
 ('staticBuild','pipExecuted',True),('staticBuild','parentImage','wrong'),('staticBuild','staticHashes',{}),
 ('backendReuse','singleFullRunPassed',True),('backendReuse','nonStaticRuntimeHashes',{}),
 ('backendReuse','windows',{'tests':True,'passed':1,'skipped':0}),
 ('browsers','groups',[]),('releaseSafety','realDocker',False),('releaseSafety','newTables',1),
 ('releaseSafety','records',[]),('gitReview','reviewed',False),('gitReview','mainTree','5'*40)])
def test_bad_or_inapplicable_evidence_cannot_reach_docker(f,kind,key,value):
    f.envelopes[kind][key]=value;f.freeze_evidence()
    with pytest.raises(RuntimeError):f.activate()
    assert not f.runner.calls


@pytest.mark.parametrize('failure',['verify-image','stop','snapshot','backup','validate-backup','check',
    'tag','up-app','unhealthy','second-check','http','anonymous','static','up-sync','up-web','nginx'])
def test_failure_keeps_scene_and_never_restores_data(f,failure):
    f.runner.fail=failure
    with pytest.raises(RuntimeError,match='release_failed_at_') as error:f.activate()
    assert 'sensitive' not in str(error.value)
    r=f.report();assert r['status']=='failed' and r['automaticRestoreAttempted'] is False
    assert all(x['running'] for x in f.runner.services.values()) == (failure=='verify-image')
    if failure!='verify-image':assert not any(x['running'] for x in f.runner.services.values())
    assert 'warm' not in f.runner.actions
    assert not any('restore' in x or 'down' in x for x in f.runner.calls)


@pytest.mark.parametrize('exit_code',[1,137,143])
def test_unclean_stop_blocks_snapshot(f,exit_code):
    f.runner.stop_exit=exit_code
    with pytest.raises(RuntimeError):f.activate()
    assert f.runner.actions==['verify-image']


@pytest.mark.parametrize('target',['.env','candidate','before','backup','resolved'])
def test_input_drift_after_stop_is_not_silently_accepted(f,target):
    def mutate(action,inputs):
        if action!='validate-backup':return
        path={'.env':f.root/'.env','candidate':f.candidate/'app.py','before':inputs/'before.json',
              'backup':inputs/'backup.json','resolved':inputs/'environment.json'}[target]
        path.chmod(0o600);path.write_bytes(b'changed')
    f.runner.mutate=mutate
    with pytest.raises(RuntimeError):f.activate()
    assert 'check' not in f.runner.actions
    assert (f.root/'RELEASE-MANIFEST.json').read_bytes()==f.old_manifest


@pytest.mark.parametrize('action',['verify-image','check'])
def test_uncertain_helper_timeout_stops_only_current_release_owned_helper(f,action):
    f.runner.fail='timeout-'+action
    with pytest.raises(RuntimeError):f.activate()
    assert len(f.report()['helpersStoppedAfterFailure'])==1
    assert not any(x['running'] for x in f.runner.helpers.values())
    assert all(x[-1]=='f'*64 for x in f.runner.calls if x[:2]==['docker','stop'])


def test_partial_install_keeps_original_archive_without_starting_app(f,monkeypatch):
    original=C.put;writes=[]
    def fail(path,value,owner=False):
        if path.name.endswith('.static-release-tmp'):
            writes.append(path)
            if len(writes)==2:raise OSError('synthetic full disk')
        return original(path,value,owner)
    monkeypatch.setattr(C,'put',fail)
    with pytest.raises(RuntimeError,match='release_failed_at_install-source'):f.activate()
    assert not any(x[:3]==['docker','compose','up'] for x in f.runner.calls)
    with tarfile.open(Path(f.report()['releaseDirectory'])/'source-before.tar.gz') as archive:
        assert all(archive.extractfile(n).read()==v for n,v in f.base.items())


def test_exclusive_release_lock_prevents_second_controller(f):
    with C.release_lock(f.releases):
        with pytest.raises(RuntimeError,match='another_static_release_running'):f.activate()
    assert not f.runner.calls


def test_raw_evidence_tamper_is_rejected(f):
    write(f.candidate/'evidence/staticBuild-original.txt',b'changed')
    with pytest.raises(RuntimeError,match='evidence_changed'):f.activate()
    assert not f.runner.calls


def test_isolated_project_volume_and_tag_never_use_production_names(f):
    result=f.activate()
    assert result['project']=='synthetic-static' and result['volume']=='synthetic-static_household-data'
    assert ['docker','tag',IMAGE,'synthetic-static-app'] in f.runner.calls
    assert not any(C.VOLUME in str(x) or 'family-dashboard-app' in str(x) for x in f.runner.calls)


def test_mismatched_project_volume_is_rejected_before_commands(f):
    f.volume=C.VOLUME
    with pytest.raises(RuntimeError,match='project_volume'):f.activate()
    assert not f.runner.calls


def test_wrong_helper_ownership_is_preserved_for_manual_review(f):
    original=f.runner
    def run(args,**kwargs):
        if '{{json .Config.Labels}}' in args:return json.dumps({'family-dashboard.static-release':'another-release'})
        return original(args,**kwargs)
    original.fail='timeout-check'
    f.runner=run
    with pytest.raises(RuntimeError):f.activate()
    assert any(x['running'] for x in original.helpers.values())
    assert f.report()['helperStopAfterFailureFailed'] is True
    assert not any(x[:2]==['docker','stop'] for x in original.calls)


def test_interrupt_during_stopped_window_preserves_scene(f):
    original=f.runner
    def run(args,**kwargs):
        if args[:2]==['docker','run'] and args[-2]=='check':raise KeyboardInterrupt()
        return original(args,**kwargs)
    f.runner=run
    with pytest.raises(RuntimeError,match='release_failed_at_'):f.activate()
    assert not any(x['running'] for x in original.services.values())
    assert f.report()['errorType']=='KeyboardInterrupt'


def test_readback_code_only_uses_fixed_loopback_gets_without_proxies(monkeypatch,tmp_path,capsys):
    import urllib.request
    import urllib.error
    import sys
    calls=[]
    raw=b'synthetic static bytes'
    expected={'runtimeHashes':{},'staticHashes':{'static/a space.js':digest(raw)},'anonymousPaths':C.ANONYMOUS_PATHS}
    class Response:
        status=200
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def read(self):return raw
    class Opener:
        def open(self,url,timeout):
            calls.append(url)
            assert url.startswith('http://127.0.0.1:8000/') and timeout==20
            if '/api/' in url:raise urllib.error.HTTPError(url,401,'denied',{},None)
            return Response()
    def opener(*handlers):
        assert handlers[0].proxies=={}
        assert handlers[1].redirect_request(None,None,None,None,None,None) is None
        return Opener()
    monkeypatch.setattr(urllib.request,'build_opener',opener)
    monkeypatch.setattr(sys,'argv',['readback',json.dumps(expected)])
    exec(compile(C.READBACK_CODE,'<readback>','exec'),{'__name__':'__main__'})
    result=json.loads(capsys.readouterr().out)
    C.verify_http(result,expected['staticHashes'])
    assert 'http://127.0.0.1:8000/a%20space.js' in calls
    assert len(calls)==2+len(C.ANONYMOUS_PATHS)
