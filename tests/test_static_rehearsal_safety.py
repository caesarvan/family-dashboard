"""Static rehearsal safety tests: real files, command substitutes, no Docker."""
import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location('static_rehearsal', Path(__file__).parents[1] / 'deploy/rehearse_static_release.py')
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)
PARENT, CHILD, NGINX = ('sha256:' + x * 64 for x in 'abc')


@pytest.fixture(autouse=True)
def forbid_real_process(monkeypatch):
    def forbidden(*a, **k):raise AssertionError('No real process in safety tests')
    monkeypatch.setattr(subprocess, 'run', forbidden)


@pytest.fixture
def obj(tmp_path):
    source = tmp_path / 'source'; source.mkdir()
    proof = tmp_path / 'build.json'; proof.write_text('{}')
    return R.Rehearsal(source, '1' * 64, PARENT, CHILD, proof, '2' * 64, NGINX, tmp_path / 'output')


@pytest.mark.parametrize('bad', ['latest', 'family-dashboard-app', 'sha256:abc', PARENT + '\n'])
def test_rejects_mutable_images_before_any_process(tmp_path, bad):
    with pytest.raises(RuntimeError, match='immutable_images'):
        R.Rehearsal(tmp_path, '1' * 64, bad, CHILD, tmp_path / 'proof', '2' * 64, NGINX, tmp_path / 'output')


def test_existing_output_and_source_overlap_are_rejected(tmp_path):
    marker = tmp_path / 'marker'; marker.write_bytes(b'keep')
    with pytest.raises(RuntimeError, match='new_output_required'):
        R.Rehearsal(tmp_path, '1' * 64, PARENT, CHILD, tmp_path / 'proof', '2' * 64, NGINX, tmp_path)
    with pytest.raises(RuntimeError, match='output_source_overlap'):
        R.Rehearsal(tmp_path, '1' * 64, PARENT, CHILD, tmp_path / 'proof', '2' * 64, NGINX, tmp_path / 'output')
    assert marker.read_bytes() == b'keep'


@pytest.mark.parametrize('bad', ['../private', '/etc/passwd', 'C:/data', 'static/../a', '.env', 'static/.env.local', 'data/a', 'test-results/a', '.git/config'])
def test_source_names_cannot_escape_or_take_private_inputs(bad):
    with pytest.raises(RuntimeError):R.relative(bad)


def test_plain_file_rejects_symlink(obj, tmp_path):
    target = tmp_path / 'real'; target.write_bytes(b'private')
    link = tmp_path / 'alias'
    try:link.symlink_to(target)
    except OSError:pytest.skip('Host cannot create symlinks')
    with pytest.raises(RuntimeError):R.plain(link)


def test_frozen_source_checks_digest_before_copy(obj):
    p = obj.source / 'app.py'; p.write_bytes(b'# synthetic')
    raw = R.encoded({'files': {'app.py': R.sha(p.read_bytes())}})
    (obj.source / 'RELEASE-MANIFEST.json').write_bytes(raw)
    assert R.frozen_source(obj.source, R.sha(raw))[1] == {'app.py': b'# synthetic'}
    p.write_bytes(b'drift')
    with pytest.raises(RuntimeError, match='source_changed'):R.frozen_source(obj.source, R.sha(raw))


def test_failed_proof_or_self_binding_creates_no_output(obj):
    values = {R.SELF: Path(R.__file__).read_bytes(), R.CONTROLLER: b'# synthetic', R.FIXTURE: b'# fixture',
              'deploy/check_static_release.py': b'# checker', 'deploy/backup.py': b'# backup', 'Dockerfile': b'FROM synthetic',
              'compose.yaml': b'{}', 'deploy/nginx.conf': b'# synthetic'}
    for name, raw in values.items():
        p = obj.source / name;p.parent.mkdir(parents=True, exist_ok=True);p.write_bytes(raw)
    raw = R.encoded({'files': {n: R.sha(v) for n, v in values.items()}})
    (obj.source / 'RELEASE-MANIFEST.json').write_bytes(raw);obj.manifest_sha = R.sha(raw)
    with pytest.raises(RuntimeError, match='proof_sha'):obj.prepare()
    assert not obj.output.exists()
    (obj.source / R.SELF).write_bytes(b'changed')
    with pytest.raises(RuntimeError, match='source_changed'):obj.prepare()


def test_synthetic_compose_cannot_use_production_ports_network_or_certificates(obj):
    config = R.compose_config(obj.project, obj.run_id, NGINX, obj.proof_dir, obj.root / 'tests')
    for name, service in config['services'].items():
        assert service['network_mode'] == 'none' and service['read_only'] is True
        assert 'ports' not in service and 'networks' not in service and 'build' not in service
        assert service['pull_policy'] == 'never' and service['labels'] == {R.LABEL: obj.run_id}
        assert service['container_name'] == obj.project + '-' + name
    assert config['services']['sync']['command'] == ['python', 'sync_worker.py']
    assert config['volumes']['household-data'] == {'external': True, 'name': obj.volume}
    assert 'letsencrypt' not in json.dumps(config) and '/opt/family-dashboard' not in json.dumps(config)
    with pytest.raises(RuntimeError):R.compose_config('family-dashboard', obj.run_id, NGINX, obj.proof_dir, obj.root)


def test_fixture_ready_is_labelled_synthetic_and_original_build_not_rewritten(obj):
    obj.candidate.mkdir(parents=True)
    hashes = {'app.py': 'a' * 64, 'requirements.txt': 'b' * 64, 'static/index.html': 'c' * 64, R.FIXTURE: 'd' * 64}
    original = b'{ "status": "built", "realProof": true }\n'
    manifest = R.encoded({'files': hashes});(obj.candidate / 'RELEASE-MANIFEST.json').write_bytes(manifest)
    m, ready_sha = R.fixture_ready(obj.candidate, {**hashes, 'static/index.html': 'e' * 64}, hashes, PARENT, CHILD, original, b'SECRET_KEY=synthetic\n')
    ready = json.loads((obj.candidate / 'READY.json').read_bytes())
    assert m == R.sha(manifest) and ready_sha == R.sha((obj.candidate / 'READY.json').read_bytes())
    assert ready['synthetic'] and ready['isAcceptanceEvidence'] is False
    assert (obj.candidate / 'evidence/build-original.json').read_bytes() == original
    for ref in ready['evidence'].values():
        raw = (obj.candidate / ref['path']).read_bytes();assert R.sha(raw) == ref['sha256']
        envelope = json.loads(raw);assert envelope['synthetic'] and envelope['isAcceptanceEvidence'] is False
        assert envelope['sourceHashes'] == hashes and envelope['records']
    assert ready['schema'] == {'from': 43, 'to': 43, 'newTables': []}


class Docker:
    def __init__(self, obj):self.obj=obj;self.entries={};self.calls=[];self.fail_create=False;self.fail_list=False
    def add(self, kind, name, owner=None):
        self.entries[(kind,name)]={'Name':name,'Labels':{R.LABEL:owner or self.obj.run_id},
          'Config':{'Labels':{R.LABEL:owner or self.obj.run_id}},'Image':CHILD,
          'HostConfig':{'NetworkMode':'none','PortBindings':{}},'State':{'Running':True,'ExitCode':0}}
    def __call__(self, args, **kwargs):
        self.calls.append((args,kwargs));assert args[0]=='docker';a=args[1:]
        if len(a)>1 and a[1]=='ls':
            assert '--filter' in a and 'name=' in a[a.index('--filter')+1]
            if self.fail_list:raise RuntimeError('daemon unavailable')
            return '\n'.join(n for (k,n) in self.entries if k==a[0])
        if len(a)>1 and a[1]=='inspect':return json.dumps([self.entries[(a[0],a[2])]])
        if a[:2]==['volume','create']:
            self.add('volume',a[-1])
            if self.fail_create:raise subprocess.TimeoutExpired('docker',1)
            return a[-1]
        if a[0]=='stop':
            self.entries[('container',a[-1])]['State']['Running']=False;return a[-1]
        if len(a)>1 and a[1]=='rm':del self.entries[(a[0],a[2])];return ''
        raise AssertionError(args)


@pytest.mark.parametrize('kind',['container','volume'])
def test_existing_resources_not_claimed_or_cleaned(obj,kind):
    d=Docker(obj);obj.runner=d;name=obj.project+'-old';d.add(kind,name,'foreign')
    with pytest.raises(RuntimeError,match='resource_already_exists'):obj.track_new(kind,name)
    assert not obj.resources
    obj.cleanup();assert (kind,name) in d.entries
    assert not any(x[0][1:2] in (['stop'],['rm']) for x in d.calls)


@pytest.mark.parametrize('kind',['container','volume'])
def test_changed_ownership_fails_cleanup_without_mutation(obj,kind):
    d=Docker(obj);obj.runner=d;name=obj.project+'-owned';obj.track_new(kind,name);d.add(kind,name,'foreign')
    obj.cleanup()
    assert not obj.report['cleanup']['passed'] and (kind,name) in d.entries
    assert not any('rm' in x[0] or 'stop' in x[0] for x in d.calls)


def test_uncertain_creation_is_tracked_and_removed_only_after_owned_readback(obj):
    d=Docker(obj);obj.runner=d;obj.track_new('volume',obj.volume);d.fail_create=True
    with pytest.raises(subprocess.TimeoutExpired):obj.call(['volume','create',obj.volume])
    obj.cleanup()
    assert not d.entries and obj.report['cleanup']['passed']


def test_cleanup_daemon_failure_does_not_blindly_remove(obj):
    d=Docker(obj);obj.runner=d;obj.track_new('volume',obj.volume);d.add('volume',obj.volume);d.fail_list=True
    obj.cleanup();assert not obj.report['cleanup']['passed'] and d.entries
    assert not any('rm' in x[0] for x in d.calls)


def test_running_containers_stop_before_volume_cleanup_and_input_images_retained(obj):
    d=Docker(obj);obj.runner=d;obj.track_new('volume',obj.volume);d.add('volume',obj.volume)
    name=obj.project+'-app';obj.track_new('container',name);d.add('container',name);obj.tag_created=True
    obj.cleanup();assert not d.entries and obj.report['cleanup']['passed']
    mutations=[a for a,k in d.calls if 'stop' in a or 'rm' in a]
    assert mutations==[['docker','stop','--time','45',name],['docker','container','rm',name],['docker','volume','rm',obj.volume]]
    assert obj.report['retainedImageTag']==obj.tag and not obj.report['allDockerObjectsRemoved']


@pytest.mark.parametrize('args',[
 ['docker','compose','--project-name','family-dashboard','stop','app'],
 ['docker','tag',CHILD,'family-dashboard-app'],['docker','system','prune'],['sh','-c','anything'],
 ['docker','run','--name','x',CHILD,'python'], ['docker','inspect','f'*64],
 ['docker','stop','f'*64], ['docker','ps','-q'], ['docker','image','rm',CHILD],
])
def test_controller_commands_cannot_escape_project_or_use_shell(obj,args):
    with pytest.raises(RuntimeError):obj.controller_runner(args,cwd=obj.root)


def test_controller_helper_preserves_flags_adds_only_run_label_and_tracks_before_execution(obj):
    calls=[]
    def runner(args,**kw):
        calls.append(args)
        if args[1:3]==['container','ls']:return ''
        assert ('container','family-dashboard-static-check-20260101t000000z-0') in obj.resources
        raise subprocess.TimeoutExpired('docker',1)
    obj.runner=runner
    args=['docker','run','--rm','--name','family-dashboard-static-check-20260101t000000z-0',
          '--label','family-dashboard.static-release=20260101T000000Z','--network','none','--read-only',
          '--user','10001:10001','--mount','type=volume,src='+obj.volume+',dst=/data',CHILD,'python','-']
    with pytest.raises(subprocess.TimeoutExpired):obj.controller_runner(args,cwd=obj.root,input_bytes=b'print(1)')
    assert calls[-2]==args[:2]+['--label',R.LABEL+'='+obj.run_id]+args[2:]


def test_controller_helper_rejects_production_volume(obj):
    obj.runner=lambda *a,**k:''
    args=['docker','run','--rm','--name','family-dashboard-static-check-20260101t000000z-0','--network','none','--read-only',
          '--user','10001:10001','--mount','type=volume,src=family-dashboard_household-data,dst=/data',CHILD,'python']
    with pytest.raises(RuntimeError,match='foreign_mount'):obj.controller_runner(args,cwd=obj.root)


def test_failure_receipt_contains_no_exception_text_and_never_overwrites_old_output(obj,monkeypatch):
    def fail():
        obj.output.mkdir();obj.created=True;raise RuntimeError('synthetic-secret-detail')
    monkeypatch.setattr(obj,'run',fail)
    result=obj.execute();raw=(obj.output/'static-rehearsal.json').read_bytes()
    assert not result['passed'] and b'synthetic-secret-detail' not in raw
    with pytest.raises(RuntimeError,match='new_output_required'):
        R.Rehearsal(obj.source,obj.manifest_sha,PARENT,CHILD,obj.proof,obj.proof_sha,NGINX,obj.output)
    assert (obj.output/'static-rehearsal.json').read_bytes()==raw


def test_embedded_programs_parse_and_verify_is_not_restore():
    ast.parse(R.PARENT_FILES);ast.parse(R.DATA_VERIFY)
    assert 'F.snapshot' in R.DATA_VERIFY and 'expected[\'databases\']' in R.DATA_VERIFY
    assert 'F.digest(raw)' in R.DATA_VERIFY and 'restorePerformed' in R.DATA_VERIFY
    assert 'executescript' not in R.DATA_VERIFY and 'F.verify(' not in R.DATA_VERIFY

def test_process_uses_only_local_socket_and_ignores_foreign_compose_environment(monkeypatch,tmp_path):
    seen={}
    monkeypatch.setenv('COMPOSE_FILE','/opt/family-dashboard/compose.yaml')
    monkeypatch.setenv('COMPOSE_PROJECT_NAME','family-dashboard')
    monkeypatch.setenv('DOCKER_HOST','ssh://production')
    def fake(args,**kw):
        seen.update(args=args,**kw)
        return subprocess.CompletedProcess(args,0,b'ok',b'')
    monkeypatch.setattr(subprocess,'run',fake)
    assert R.Rehearsal.process(['docker','image','inspect',CHILD],cwd=tmp_path)=='ok'
    assert seen['args'][:3]==['docker','--host','unix:///var/run/docker.sock']
    assert not any(k.startswith('COMPOSE_') for k in seen['env'])
    assert 'DOCKER_HOST' not in seen['env'] and 'DOCKER_CONTEXT' not in seen['env']


@pytest.mark.parametrize('key',['COMPOSE_FILE','compose_file','DOCKER_HOST','docker_context'])
def test_host_compose_override_is_rejected_before_output_or_process(obj,monkeypatch,key):
    monkeypatch.setenv(key,'foreign')
    with pytest.raises(RuntimeError,match='host_compose_environment'):obj.prepare()
    assert not obj.output.exists()


def test_initial_and_controller_compose_use_only_frozen_files_and_environment(obj,monkeypatch):
    calls=[]
    obj.runner=lambda a,**k:calls.append((a,k)) or ''
    monkeypatch.setenv('UNRELATED_NEW_HOST_VALUE','drift')
    obj.compose('config','--format','json')
    obj.controller_runner([*obj.compose_prefix(),'config','--format','json'],cwd=obj.root,env=dict(obj.host_environment))
    assert calls[0][0]==calls[1][0] and calls[0][1]['env']==calls[1][1]['env']
    assert 'UNRELATED_NEW_HOST_VALUE' not in calls[0][1]['env']
    assert calls[0][0][:8]==['docker','compose','--project-name',obj.project,'--file',str(obj.root/'compose.yaml'),
                           '--env-file',str(obj.root/'.env')]
    with pytest.raises(RuntimeError,match='controller_environment_changed'):
        obj.controller_runner([*obj.compose_prefix(),'config'],cwd=obj.root,env={**obj.host_environment,'DRIFT':'1'})
    with pytest.raises(RuntimeError,match='foreign_compose_project'):
        obj.controller_runner([*obj.compose_prefix(),'config','--file','/foreign.yaml'],cwd=obj.root)


def test_supplied_frozen_environment_not_replaced_by_later_host_environment(monkeypatch,tmp_path):
    seen={}
    def fake(args,**kw):
        seen.update(kw)
        return subprocess.CompletedProcess(args,0,b'{}',b'')
    monkeypatch.setattr(subprocess,'run',fake)
    monkeypatch.setenv('NEW_HOST_DRIFT','new')
    R.Rehearsal.process(['docker','image','inspect',CHILD],cwd=tmp_path,env={'FROZEN':'old'})
    assert seen['env']=={'FROZEN':'old'}


def test_fixture_failure_original_bytes_are_private_and_not_in_summary(obj,monkeypatch):
    obj.output.mkdir()
    failed = subprocess.CompletedProcess([],1,b'{"passed":false,"stage":"snapshot"}',b'synthetic diagnostic\n')
    def fail(*args,**kwargs):raise R.DockerFailure(failed)
    monkeypatch.setattr(obj,'compose',fail)
    with pytest.raises(R.DockerFailure):obj.fixture_result('data-verification','exec')
    proof=obj.report['data-verificationFailure']
    assert Path(proof['stdout']).read_bytes()==failed.stdout and proof['stdoutSha256']==R.sha(failed.stdout)
    assert Path(proof['stderr']).read_bytes()==failed.stderr and proof['stderrSha256']==R.sha(failed.stderr)
    assert b'synthetic diagnostic' not in R.encoded(obj.report)
    with pytest.raises(RuntimeError,match='fixture_record_label'):obj.fixture_result('environment','config')


@pytest.mark.parametrize('failure',[None,'controller-rejected','record-mismatch','data-changed','input-drift'])
def test_actual_controller_call_and_independent_readback_gate_success(obj,monkeypatch,failure):
    events=[]
    monkeypatch.setattr(R,'os',SimpleNamespace(name='posix'))
    manifest=R.encoded({'files':{'app.py':R.sha(b'# frozen')}})
    (obj.source/'app.py').write_bytes(b'# frozen')
    (obj.source/'RELEASE-MANIFEST.json').write_bytes(manifest)
    obj.proof_sha=R.sha(obj.proof.read_bytes());obj.manifest_sha=R.sha(manifest)
    def activate(candidate,image,manifest_sha,ready_sha,**kw):
        events.append('controller')
        assert candidate==obj.candidate and image==CHILD and manifest_sha==obj.manifest and ready_sha==obj.ready_sha
        assert kw=={'root':obj.root,'releases':obj.releases,'project':obj.project,'volume':obj.volume,'runner':obj.controller_runner}
        release=obj.releases/'static-synthetic';release.mkdir(parents=True)
        result={'releaseDirectory':str(release),'status':'published','environmentPreserved':True,
                'originalTablesPreserved':43,'newTables':0,'stoppedDatabaseContentsPreserved':True,
                'automaticRestoreAttempted':False,'backupVerification':{'databases':3},
                'beforeInstallReadback':{'checked':1},'startupReadback':{'checked':2},'afterHttpReadback':{'checked':3}}
        if failure=='controller-rejected':result['status']='failed'
        (release/'deployment.json').write_bytes(R.encoded({} if failure=='record-mismatch' else result))
        return result
    def prepare():
        obj.output.mkdir();obj.created=True;obj.root.mkdir();obj.candidate.mkdir()
        obj.original_values={'app.py':b'# frozen'};obj.original_manifest=manifest
        obj.manifest='m';obj.ready_sha='r';obj.controller=SimpleNamespace(activate=activate)
    def result(label,*args):
        events.append(label)
        if label=='seed':return {'passed':True,'counts':{'households':2,'journeyDocuments':8},'externalRequests':[]}
        if failure=='input-drift':(obj.source/'app.py').write_bytes(b'# changed')
        return {'passed':failure!='data-changed','documents':8}
    monkeypatch.setattr(obj,'prepare',prepare)
    monkeypatch.setattr(obj,'track_new',lambda *a:None)
    monkeypatch.setattr(obj,'call',lambda *a,**k:'')
    monkeypatch.setattr(obj,'owned',lambda *a:{})
    monkeypatch.setattr(obj,'ephemeral',lambda *a,**k:'')
    monkeypatch.setattr(obj,'compose',lambda *a,**k:events.append('compose:'+a[0]))
    monkeypatch.setattr(obj,'fixture_result',result)
    monkeypatch.setattr(obj,'cleanup',lambda:events.append('cleanup'))
    result=obj.execute()
    assert events.index('seed')<events.index('controller') and events[-1]=='cleanup'
    assert result['passed'] is (failure is None)
    if failure in ('controller-rejected','record-mismatch'):assert 'data-verification' not in events
    else:assert events.index('controller')<events.index('data-verification')
    if failure is None:
        assert result['phase']=='complete' and result['controller']['backupDatabases']==3
        assert R.sha(Path(result['controller']['path']).read_bytes())==result['controller']['sha256']
    assert json.loads((obj.output/'static-rehearsal.json').read_bytes())==result
