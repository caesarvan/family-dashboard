"""Offline fixture/selector/handle checks. Never starts Docker or Linux services."""
import json
import copy
from pathlib import Path
import subprocess
import sqlite3
import sys

import pytest

from deploy import media_video_controller_rehearsal as rehearsal

PROJECT = 'fd-vcr-0123456789abcdef-success'


def test_fixture_composition_keeps_five_real_processes_and_private_network():
    value = rehearsal.composition(PROJECT, True, 38127)
    services = value['services']
    assert set(services)=={'app','sync','media','web','decoder'}
    assert sum(int(v['mem_limit'][:-1]) for v in services.values())==960
    assert all(v['memswap_limit']==v['mem_limit'] for v in services.values())
    assert services['web']['ports']==['127.0.0.1:38127:80']
    assert value['networks']['default']['internal'] is True
    assert services['sync']['command']==['python','-B','sync_worker.py']
    assert services['media']['command']==['python','-B','media_import_worker.py']
    assert services['decoder']['network_mode']=='none'
    assert 'command' not in services['app'] and 'entrypoint' not in services['decoder']
    assert all(v['restart']=='no' and 'build' not in v for v in services.values())
    raw=json.dumps(value)
    assert '/var/lib/family-dashboard' not in raw and '/opt/family-dashboard' not in raw
    assert 'family-dashboard_household-data' not in raw


@pytest.mark.parametrize('project,port',[('family-dashboard',38127),(PROJECT,80),(PROJECT,True)])
def test_production_project_or_privileged_health_port_is_refused(project,port):
    with pytest.raises(rehearsal.controller.ReleaseError): rehearsal.composition(project,True,port)


def test_parent_fixture_has_only_original_four_services():
    value=rehearsal.composition(PROJECT,False,38127)
    assert set(value['services'])=={'app','sync','media','web'}
    assert all(value['services'][n]['image']==rehearsal.IMAGES['parent'] for n in ('app','sync','media'))
    assert set(value['volumes'])=={'household-data'}


def test_fixture_https_application_and_http_health_are_separate(tmp_path,monkeypatch):
    # Exercise the actual adapter and non-testing app/SQLite factory. Only the
    # package bytes here are minimal synthetic inputs; no Docker/network is used.
    for module,names in ((rehearsal.controller,('ROOT','RELEASES','VOLUME','PUBLIC_ORIGIN','DATA_PREFIX')),
                         (rehearsal.lifecycle,('VOLUME','PROJECT','SOCKET_VOLUME','MEMORY','BEFORE_COMPOSE','AFTER_COMPOSE','decoder_contract')),
                         (rehearsal.activation,('PARENT_MANIFEST',))):
        for name in names:monkeypatch.setattr(module,name,getattr(module,name))
    bundle=tmp_path/'bundle';parent=bundle/'parent';parent.mkdir(parents=True)
    (parent/'app.py').write_bytes(b'# synthetic parent source fixture\n')
    (parent/'requirements.txt').write_bytes(b'# synthetic dependency fixture\n')
    scenario=tmp_path/'scenario';scenario.mkdir()
    verified={'blobs':{'compose.yaml':b'synthetic compose','deploy/nginx.conf':b'synthetic nginx'},'manifest':{}}
    installed,_,_,_,health=rehearsal.adapt(bundle,{},verified,scenario,PROJECT,38127)
    env=dict(line.split('=',1) for line in (installed/'.env').read_text().splitlines())
    public=env['PUBLIC_ORIGIN']
    assert public==rehearsal.seed.SYNTHETIC_ENV['PUBLIC_ORIGIN'] and public.startswith('https://')
    assert health==rehearsal.controller.PUBLIC_ORIGIN=='http://127.0.0.1:38127'
    assert env['COOKIE_SECURE']=='1' and env['TRUST_PROXY']=='0'
    adaptation=json.loads((scenario/'adaptations.json').read_bytes())
    assert adaptation['publicOrigin']==public and adaptation['healthOrigin']==health
    assert adaptation['cookieSecure'] and adaptation['actualTLS'] is False
    for key,value in env.items():monkeypatch.setenv(key,value)
    monkeypatch.setenv('DATA_DIR',str(tmp_path/'data'))
    monkeypatch.setattr(rehearsal.socket.socket,'connect',lambda *a:pytest.fail('no network permitted'))
    from app import create_app
    application=create_app({'TESTING':False})
    assert not application.testing and application.config['SESSION_COOKIE_SECURE'] is True
    assert application.extensions['cloud_accounts'].origin==public
    client=application.test_client()
    assert client.get('/healthz',base_url=health).json=={'status':'ok'}
    login=client.post('/api/login',base_url=public,headers={'Origin':public},
                      json={'username':'member1','password':env['MEMBER1_PASSWORD']})
    assert login.status_code==200 and any('; Secure;' in v for v in login.headers.getlist('Set-Cookie'))
    identity=client.get('/api/me',base_url=public).json
    created=client.post('/api/items/tasks',base_url=public,
                        headers={'Origin':public,'X-CSRF-Token':identity['csrf']},json={'title':'Synthetic origin check'})
    assert created.status_code==201
    with rehearsal.closing(sqlite3.connect(tmp_path/'data/household.sqlite3')) as con:
        assert con.execute("SELECT count(*) FROM entities WHERE kind='tasks'").fetchone()[0]==1
    # A loopback HTTP PUBLIC_ORIGIN must still fail the real application guard.
    monkeypatch.setenv('PUBLIC_ORIGIN',health)
    with pytest.raises(RuntimeError,match='PUBLIC_ORIGIN must be an HTTPS origin'):
        create_app({'TESTING':False,'DATA_DIR':str(tmp_path/'invalid-data')})


def test_admission_samples_all_three_and_never_polls_for_a_high_point():
    values=iter([1088*1024,1088*1024-1,2048*1024]);slept=[]
    result=rehearsal.preflight(reader=lambda:next(values),sleeper=slept.append)
    assert not result['passed'] and len(result['samples'])==3 and slept==[1,1]
    with pytest.raises(StopIteration):next(values)
    assert rehearsal.preflight(reader=lambda:1088*1024,sleeper=lambda _:None)['passed']


def test_preflight_read_error_retains_completed_samples():
    calls=[];sleeps=[]
    def read():
        calls.append(1)
        if len(calls)==2:raise OSError('synthetic memory read refused')
        return 1200*1024
    result=rehearsal.preflight(reader=read,sleeper=sleeps.append)
    assert not result['passed'] and result['failedSample']==2
    assert result['failure']=='OSError:synthetic memory read refused'
    assert [s['availableKiB'] for s in result['samples']]==[1200*1024]
    assert len(calls)==2 and sleeps==[1]


@pytest.mark.parametrize('failure',['first_read','thread_start'])
def test_coordinator_initialization_failure_keeps_zero_container_receipt(tmp_path,monkeypatch,failure):
    # Only platform/input/resource admission are synthetic; execute the real run()
    # exception/finalization path. No Docker or scenario may be entered.
    monkeypatch.setattr(rehearsal.sys,'platform','linux')
    monkeypatch.setattr(rehearsal.os,'geteuid',lambda:0,raising=False)
    for key in list(rehearsal.os.environ):
        if key.upper().startswith(('DOCKER_','COMPOSE_')):monkeypatch.delenv(key)
    monkeypatch.setattr(rehearsal,'LAB',tmp_path/'lab')
    monkeypatch.setattr(rehearsal,'verify',lambda *a:(tmp_path,{}, {}, {}))
    monkeypatch.setattr(rehearsal.signal,'signal',lambda *a:None)
    monkeypatch.setattr(rehearsal,'scenario',lambda *a:pytest.fail('no scenario before monitoring starts'))
    monkeypatch.setattr(rehearsal.subprocess,'Popen',lambda *a,**k:pytest.fail('no child process permitted'))
    def bad_read():raise OSError('synthetic memory read refused')
    original_preflight=rehearsal.preflight
    monkeypatch.setattr(rehearsal,'preflight',lambda:original_preflight(
        reader=bad_read if failure=='first_read' else lambda:1200*1024,sleeper=lambda _:None))
    if failure=='thread_start':
        def failed_start(_):raise RuntimeError('synthetic monitor start refused')
        monkeypatch.setattr(rehearsal.threading.Thread,'start',failed_start)
        monkeypatch.setattr(rehearsal.threading.Thread,'join',lambda *a:pytest.fail('must not join an unstarted thread'))
    out=rehearsal.LAB/'run-0123456789abcdef'
    result=rehearsal.run(tmp_path,'a'*64,out)
    assert result==json.loads((out/'result.json').read_bytes())
    assert not result['passed'] and result['containersCreated']==0 and result['scenarios']=={}
    assert (out/'started.json').is_file()
    admission=json.loads((out/'preflight.json').read_bytes())
    if failure=='first_read':
        assert result['status']=='preflight_failed' and result['failure']=='OSError:synthetic memory read refused'
        assert admission['samples']==[] and admission['failedSample']==1
    else:
        assert result['failure']=='RuntimeError:synthetic monitor start refused' and admission['passed']
        assert result['hostMemory']['threadStarted'] is False and result['hostMemory']['threadStopped'] is True


def test_monitor_started_thread_is_actually_joined(monkeypatch):
    monkeypatch.setattr(rehearsal,'available_kib',lambda:1200*1024)
    monitor=rehearsal.Monitor()
    try:
        monitor.start();assert monitor.thread_started
    finally:result=monitor.finish()
    assert result['threadStarted'] and result['threadStopped'] and result['sampleCount']>=1
    assert not monitor.thread.is_alive() and result['failure'] is None


class Healthy:
    def check(self): pass


@pytest.fixture
def transport(tmp_path):
    return rehearsal.Transport(tmp_path,tmp_path/'bundle',PROJECT,'http://127.0.0.1:38127',Healthy(),'success')


def health_fixture():
    cid,nid,eid='a'*64,'b'*64,'c'*64;name=PROJECT+'_default'
    endpoint={'NetworkID':nid,'EndpointID':eid,'IPAddress':'172.29.0.5','IPPrefixLen':16}
    web={'Id':cid,'Name':'/'+PROJECT+'-web-1','Image':rehearsal.IMAGES['web'],
         'Config':{'Labels':{rehearsal.LABEL:PROJECT,'com.docker.compose.project':PROJECT,'com.docker.compose.service':'web'}},
         'State':{'Running':True,'Pid':12345,'OOMKilled':False},'RestartCount':0,
         'HostConfig':{'NetworkMode':name},'NetworkSettings':{'Networks':{name:endpoint},'Ports':{'80/tcp':None}}}
    network={'Id':nid,'Name':name,'Driver':'bridge','Scope':'local','Internal':True,
             'Labels':{'com.docker.compose.project':PROJECT,'com.docker.compose.network':'default'},
             'IPAM':{'Config':[{'Subnet':'172.29.0.0/16'}]},
             'Containers':{cid:{'Name':PROJECT+'-web-1','EndpointID':eid,'IPv4Address':'172.29.0.5/16'}}}
    return web,network


@pytest.mark.parametrize('fault',['external_ip','outside_subnet','wrong_cid','wrong_endpoint','wrong_project','external_network','extra_network'])
def test_health_binding_rejects_unowned_address_or_identity(fault):
    web,network=health_fixture();endpoint=web['NetworkSettings']['Networks'][PROJECT+'_default']
    if fault in ('external_ip','outside_subnet'):
        ip='8.8.8.8' if fault=='external_ip' else '172.30.0.5'
        endpoint['IPAddress']=ip;network['Containers'][web['Id']]['IPv4Address']=ip+'/16'
        if fault=='external_ip':network['IPAM']['Config']=[{'Subnet':'8.8.0.0/16'}]
    elif fault=='wrong_cid':web['Id']='d'*64
    elif fault=='wrong_endpoint':network['Containers'][web['Id']]['EndpointID']='d'*64
    elif fault=='wrong_project':network['Labels']['com.docker.compose.project']='family-dashboard'
    elif fault=='external_network':network['Internal']=False
    elif fault=='extra_network':web['NetworkSettings']['Networks']['other']=copy.deepcopy(endpoint)
    with pytest.raises(rehearsal.controller.ReleaseError):rehearsal.web_health_binding(PROJECT,web,network)


@pytest.mark.parametrize('status,changed',[('200',False),('302',False),('200',True)])
def test_health_transport_uses_actual_nginx_curl_and_retains_outcome(transport,monkeypatch,status,changed):
    web,network=health_fixture();calls=[];transport.discovery_admitted=True
    def execute(argv,timeout=240):
        calls.append((argv,timeout));transport.records.append({'argv':argv})
        if argv[:4]==[*rehearsal.lifecycle.DOCKER,'inspect']:
            value=copy.deepcopy(web)
            if changed and argv[-1]==web['Id']:value['State']['Pid']+=1
            return json.dumps([value]).encode()
        if argv[:5]==[*rehearsal.lifecycle.DOCKER,'network','inspect']:return json.dumps([network]).encode()
        assert argv==['curl','--fail','--silent','--show-error','--noproxy','*','--proto','=http',
                      '--max-time','30','--max-redirs','0','--max-filesize','65536','--write-out','\n%{http_code}',
                      'http://172.29.0.5/healthz']
        assert timeout==35
        return b'{"status":"ok"}\n'+status.encode()
    monkeypatch.setattr(transport,'execute',execute)
    requested=['curl','--fail','--silent','--show-error','--max-time','30',transport.origin+'/healthz']
    if status=='200' and not changed:assert json.loads(transport(requested))=={'status':'ok'}
    else:
        with pytest.raises(rehearsal.controller.ReleaseError):transport(requested)
    proof=json.loads((transport.root/'health-transport-0002.json').read_bytes())
    assert proof['requestedArgv']==requested and proof['requestedUrl']==transport.origin+'/healthz'
    assert proof['actualUrl']=='http://172.29.0.5/healthz' and proof['containerId']==web['Id']
    assert proof['completed']==(status=='200' and not changed) and proof['hostPortPublishingVerified'] is False
    assert sum(argv[0]=='curl' for argv,_ in calls)==1


def test_health_transport_refuses_external_request_and_foreign_network_before_process(transport,monkeypatch):
    monkeypatch.setattr(transport,'execute',lambda *a,**k:pytest.fail('no process for foreign target'))
    with pytest.raises(rehearsal.controller.ReleaseError,match='external_health_forbidden'):
        transport(['curl','--fail','--silent','--show-error','--max-time','30','https://example.com/healthz'])
    with pytest.raises(rehearsal.controller.ReleaseError,match='foreign_network_operation'):
        transport([*rehearsal.lifecycle.DOCKER,'network','inspect','family-dashboard_default'])


@pytest.mark.parametrize('args',[
    ['inspect','family-dashboard-app-1'],
    ['stop','--timeout','5','f'*64],
    ['ps','--quiet','--filter','volume=family-dashboard_household-data'],
    ['volume','inspect','family-dashboard_decoder-socket'],
    ['tag',rehearsal.IMAGES['app'],'family-dashboard-app:latest'],
    ['compose','--project-name','family-dashboard','up','-d'],
    ['rm','--force','f'*64],
])
def test_transport_blocks_foreign_selectors_before_any_process(transport,args):
    with pytest.raises(rehearsal.controller.ReleaseError):transport.validate(args)
    assert not transport.records


def test_helper_cannot_bind_production_data_or_environment(transport):
    args=['create','--name','family-dashboard-video-data-'+'1'*24,'--network','none','--read-only',
          '--user','10001:10001','--env-file','/opt/family-dashboard/.env']
    with pytest.raises(rehearsal.controller.ReleaseError,match='foreign_environment'):transport.validate(args)
    assert not transport.intents


def test_rehearsal_inherits_all_real_controller_transaction_methods():
    for name in rehearsal.METHODS:
        assert getattr(rehearsal.FixtureController,name) is getattr(rehearsal.controller.Controller,name)
    assert rehearsal.FixtureController.evidence is not rehearsal.controller.Controller.evidence


def test_process_timeout_retains_original_pid_and_terminal(transport):
    with pytest.raises(rehearsal.controller.ReleaseError,match='fixture_command_timeout'):
        transport.execute([sys.executable,'-B','-c','import time;time.sleep(20)'],timeout=.1)
    started=json.loads((transport.output/'0000.started.json').read_bytes())
    terminal=json.loads((transport.output/'0000.json').read_bytes())
    assert started['pid']==terminal['pid'] and terminal['exitCode'] is not None
    assert terminal['completedAt']>=started['startedAt']
    assert (transport.output/'0000.stdout').is_file() and (transport.output/'0000.stderr').is_file()


def test_unknown_creation_never_claims_cleanup_complete(transport,monkeypatch):
    transport.discovery_admitted=True
    transport.unknown={'name':'fixture-create-result-unavailable'}
    monkeypatch.setattr(transport,'discover',lambda:None)
    calls=[]
    monkeypatch.setattr(transport,'raw',lambda *args,**kw:calls.append(args) or b'')
    result=transport.stop_owned()
    assert not result['complete'] and 'unknown_create' in result['failures']
    assert all(args[0]=='ps' for args in calls)


def test_changed_container_identity_is_not_treated_as_removed(transport,monkeypatch):
    transport.discovery_admitted=True
    cid='a'*64;transport.owned[cid]={'name':'fixture','image':rehearsal.IMAGES['app'],'state':{'Running':False}}
    monkeypatch.setattr(transport,'discover',lambda:None)
    def changed(_):raise rehearsal.controller.ReleaseError('unowned_container')
    monkeypatch.setattr(transport,'remember',changed)
    calls=[]
    def raw(*args,**kw):
        calls.append(args)
        return cid.encode() if 'id='+cid in args else b''
    monkeypatch.setattr(transport,'raw',raw)
    result=transport.stop_owned()
    assert not result['complete'] and cid+':inspect_unconfirmed' in result['failures']
    assert not any(x[0]=='stop' for x in calls)


def test_existing_standalone_run_label_is_never_adopted_for_cleanup(transport,monkeypatch):
    cid='b'*64;calls=[]
    def raw(*args,**kw):
        calls.append(args)
        return cid.encode() if ('label='+rehearsal.LABEL+'='+PROJECT) in args else b''
    monkeypatch.setattr(transport,'raw',raw)
    with pytest.raises(rehearsal.controller.ReleaseError,match='fixture_project_exists'):
        transport.fresh_project()
    monkeypatch.setattr(transport,'discover',lambda:pytest.fail('unadmitted project cannot be adopted'))
    assert not transport.discovery_admitted and not transport.owned
    transport.stop_owned()
    assert not any(x[0] in ('inspect','stop','start','create') for x in calls)


def test_discovery_requires_completed_fresh_fixture_admission(transport,monkeypatch):
    monkeypatch.setattr(transport,'raw',lambda *a,**k:pytest.fail('must fail before reading containers'))
    with pytest.raises(rehearsal.controller.ReleaseError,match='fixture_discovery_not_admitted'):
        transport.discover()


@pytest.mark.parametrize('suffix',['_household-data','_decoder-socket'])
def test_existing_fixture_volume_blocks_before_any_creation(transport,monkeypatch,suffix):
    calls=[]
    def raw(*args,**kw):
        calls.append(args)
        assert args[:2]==('volume','ls'), 'must not create/inspect/change an existing volume'
        return (PROJECT+suffix).encode() if args[-1]=='name=^'+PROJECT+suffix+'$' else b''
    monkeypatch.setattr(transport,'raw',raw)
    with pytest.raises(rehearsal.controller.ReleaseError,match='fixture_volume_already_exists'):
        rehearsal.create_data_volume(transport)
    assert not transport.discovery_admitted and transport.data_path is None and not transport.owned
    assert len(calls)==(1 if suffix=='_household-data' else 2)


def test_host_pressure_latches_before_any_next_command(transport,monkeypatch):
    monitor=rehearsal.Monitor();monitor.last=rehearsal.time.monotonic();monitor.failed='host_memory_below_floor'
    transport.monitor=monitor
    with pytest.raises(rehearsal.controller.ReleaseError,match='host_memory_below_floor'):
        transport.execute([sys.executable,'-c','raise AssertionError("must not start")'])
    assert not transport.records


def test_partial_schema_requires_real_first_commit_and_unmigrated_second(tmp_path):
    child=tmp_path/'spaces'/'synthetic'/'household.sqlite3';child.parent.mkdir(parents=True)
    for path,count in ((tmp_path/'household.sqlite3',73),(tmp_path/'platform.sqlite3',9),(child,71)):
        with sqlite3.connect(path) as con:
            for index in range(count):con.execute('CREATE TABLE t%d(value)' % index)
    before={p:p.read_bytes() for p in tmp_path.rglob('*.sqlite3')}
    result=rehearsal.partial_schema(tmp_path)
    assert sorted(result.values())==[9,71,73]
    assert all(path.read_bytes()==raw for path,raw in before.items())
    with sqlite3.connect(child) as con:con.execute('CREATE TABLE unexpected(value)')
    with pytest.raises(rehearsal.controller.ReleaseError,match='partial_migration_not_proven'):
        rehearsal.partial_schema(tmp_path)


def test_separate_rehearsal_changes_no_fixed_controller_or_lifecycle_bytes():
    root=Path(__file__).resolve().parents[1]
    for name in ('deploy/media_video_release_controller.py','deploy/media_video_service_lifecycle.py',
                 'deploy/check_media_video_migration.py','deploy/prepare_media_video_activation.py'):
        frozen=subprocess.check_output(['git','show',rehearsal.BASE+':'+name],cwd=root)
        assert (root/name).read_bytes()==frozen
