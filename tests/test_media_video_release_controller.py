"""Offline orchestration/receipt tests; no daemon, production or real migration.

The real Lifecycle runs against its reviewed recording Docker model. Package
verification is separately tested by its existing suite; flow fixtures replace
only external package/experiment receipts and Docker transport, never SQLite.
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import importlib.util

import pytest

from deploy import media_video_release_controller as control
from deploy import prepare_media_video_activation as prepare
from deploy import media_video_service_lifecycle as lifecycle
from deploy.membership_release_controller import ReleaseError, encoded, sha, put

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('lifecycle_recording_model', ROOT/'tests/test_media_video_service_lifecycle.py')
model = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(model)


def write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw if isinstance(raw, bytes) else encoded(raw))
    return sha(path.read_bytes())


class Runner(model.RecordingDocker):
    def __init__(self, root):
        super().__init__(root)
        self.timer = True; self.data = []; self.fault = None; self.started = []
        self.app_config = {'Env': model.BASE_ENV}
        self.decoder_config = {'Env': model.DECODER_ENV}
        self.helpers, self.helper_fault = {}, None

    def __call__(self, argv, *, cwd, timeout):
        if argv[0] == 'systemctl':
            self.calls.append((argv, timeout))
            if argv[1] == 'stop': self.timer = False
            if argv[1] == 'start': self.timer = True
            if argv[1] == 'is-active': return b'active' if self.timer else b'inactive'
            if argv[1] == 'show': return (b'active' if self.timer else b'inactive') if argv[-1] == control.TIMER else b'inactive'
            return b''
        if argv[0] == 'curl':
            self.calls.append((argv, timeout))
            if self.fault == 'health': raise ReleaseError('injected_health_failure')
            return b'{"status":"ok"}'
        args = argv[3:]
        if args[:1] == ['compose'] and args[-2:] == ['config','--quiet']:
            self.calls.append((argv,timeout));return b''
        if args[:1] == ['inspect'] and args[1] in prepare.IMAGES.values():
            self.calls.append((argv, timeout))
            role = next(k for k,v in prepare.IMAGES.items() if v == args[1])
            return json.dumps([{'Id':args[1], 'Config':self.app_config if role == 'app' else self.decoder_config}]).encode()
        if args[:1] == ['tag']:
            self.calls.append((argv, timeout)); return b''
        if args[:2] == ['volume', 'ls']:
            self.calls.append((argv, timeout)); return b''
        if args[:1] == ['exec']:
            self.calls.append((argv, timeout)); return b'{"initialized":true,"households":2}'
        if args[:1] == ['create']:
            self.calls.append((argv, timeout))
            program = args[-1]
            action = next(k for k,v in control.DATA_ACTIONS.items() if v in program)
            assert not any(v['State']['Running'] for v in self.values.values())
            assert '--network' in args and args[args.index('--network')+1] == 'none'
            assert '--env-file' in args and not any('synthetic-only' in item for item in args)
            assert args[args.index('--memory')+1] == '384m'
            cid = sha(str(len(self.helpers)).encode())
            labels = dict(args[index+1].split('=',1) for index,x in enumerate(args) if x == '--label')
            self.helpers[cid] = {'Id':cid,'Name':'/'+args[args.index('--name')+1], 'Image':prepare.IMAGES['app'],
                'Config':{'Labels':labels}, 'State':{'Status':'created','Running':False,'Pid':0,
                    'ExitCode':0,'OOMKilled':False,'FinishedAt':''}, 'action':action}
            if action == 'migrate' and self.helper_fault == 'unknown-create':
                raise ReleaseError('command_unavailable_or_timeout')
            return cid.encode()
        if args[:1] == ['inspect'] and args[-1] in self.helpers:
            self.calls.append((argv,timeout)); value = self.helpers[args[-1]]
            if value['State']['Running'] and self.helper_fault == 'identity-changed':
                value['Config']['Labels']['family-dashboard.release-plan'] = 'f'*64
            return json.dumps([value]).encode()
        if args[:1] == ['stop'] and args[-1] in self.helpers:
            self.calls.append((argv,timeout)); value = self.helpers[args[-1]]
            assert args[1:-1] == ['--signal','SIGTERM','--timeout','30']
            if self.helper_fault == 'stop-failed':raise ReleaseError('stop_rpc_timed_out')
            value['State'].update(Status='exited',Running=False,Pid=0,ExitCode=143,FinishedAt='stopped')
            return args[-1].encode()
        if args[:2] == ['start','--attach'] and args[-1] in self.helpers:
            self.calls.append((argv,timeout)); value = self.helpers[args[-1]]; action = value['action']
            self.data.append(action); value['State'].update(Status='running',Running=True,Pid=909)
            if action == 'migrate' and self.helper_fault in ('timeout','stop-failed','identity-changed'):
                raise ReleaseError('command_unavailable_or_timeout')
            if action == 'migrate' and self.helper_fault == 'interrupt':raise KeyboardInterrupt('synthetic interruption')
            value['State'].update(Status='exited',Running=False,Pid=0,FinishedAt='completed')
            if self.fault == action:
                value['State']['ExitCode']=1
                raise ReleaseError('injected_'+action)
            value = dict(verified=True,households=2,databases=3,planSha256=self.plan_sha,
                         logicalSha256='2'*64,sourceIdentitySha256='3'*64)
            if action == 'check' and self.fault == 'logical-drift': value['logicalSha256']='4'*64
            return json.dumps(value).encode()
        if args[:1] == ['ps'] and 'volume='+control.VOLUME in args:
            raw = super().__call__(argv,cwd=cwd,timeout=timeout)
            live = [cid for cid,v in self.helpers.items() if v['State']['Running']]
            return raw + ('\n'.join(live)+ ('\n' if live else '')).encode()
        if 'up' in args: self.started.extend(args[args.index('--wait-timeout')+2:])
        return super().__call__(argv,cwd=cwd,timeout=timeout)


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setattr(model,'APP',prepare.IMAGES['app']); monkeypatch.setattr(model,'DECODER',prepare.IMAGES['decoder'])
    # Windows exposes 0666 for owner-only writable files; production checks stay strict.
    if os.name == 'nt':
        original=control.stat.S_IMODE
        monkeypatch.setattr(control.stat,'S_IMODE',lambda mode:0o600 if original(mode)==0o666 else original(mode))
    root=tmp_path/'installed'; root.mkdir(); releases=tmp_path/'releases'; releases.mkdir()
    before=subprocess.check_output(['git','show',prepare.PARENT_SOURCE+':compose.yaml'],cwd=ROOT)
    old_blobs={'compose.yaml':before,'app.py':b'old application\n','static/experience/old.js':b'old export\n'}
    old={'sourceHead':prepare.PARENT_SOURCE,'tree':'1'*40,'files':{n:write(root/n,b) for n,b in old_blobs.items()}}
    parent_sha=write(root/'RELEASE-MANIFEST.json',old); monkeypatch.setattr(prepare,'PARENT_MANIFEST',parent_sha)
    env_sha=write(root/'.env',b'SYNTHETIC_ENV=only-for-test\n'); (root/'.env').chmod(0o600)
    candidate=tmp_path/'candidate'; candidate.mkdir()
    blobs={'compose.yaml':(ROOT/'compose.yaml').read_bytes(),'app.py':b'new application\n','static/experience/new.js':b'new export\n'}
    files={n:write(candidate/'source'/n,b) for n,b in blobs.items()}
    manifest={'sourceHead':prepare.APP_SOURCE,'tree':'2'*40,'files':files}
    manifest_sha=write(candidate/'source/RELEASE-MANIFEST.json',manifest)
    operators={n:write(candidate/'operator'/n,(ROOT/n).read_bytes()) for n in prepare.OPERATORS}
    operator_sha=write(candidate/'operator.json',{'head':'4'*40,'tree':'5'*40,'files':operators})
    runner=Runner(root)
    build_dir=tmp_path/'build'
    records={role:write(build_dir/role/'build.json',{'verification':{'config':runner.app_config if role=='app' else runner.decoder_config}})
             for role in ('app','decoder')}
    metadata={'sourceHead':prepare.APP_SOURCE,'tree':'2'*40,'manifestSha256':manifest_sha,
              'contexts':{'app':files,'decoder':{}}}
    value={'metadata':metadata,'manifest':manifest,'blobs':blobs}
    built={'images':prepare.IMAGES,'builds':records}
    inputs={'build':{'root':str(build_dir)}}
    plan={'kind':'media-video-five-service-activation-v1','parentSource':prepare.PARENT_SOURCE,
          'parentManifest':parent_sha,'sourceHead':prepare.APP_SOURCE,'images':prepare.IMAGES,
          'envSha256':env_sha,'inputs':inputs,'verifiedEvidence':{'synthetic':'recording transport'},
          'operatorSha256':operator_sha,'schemaBefore':[71,9],'schemaAfter':[73,9]}
    plan_sha=write(candidate/'plan.json',plan); runner.plan_sha=plan_sha
    monkeypatch.setattr(prepare,'verify_evidence',lambda supplied:(value,built,{'synthetic':'recording transport'}))
    c=control.Controller(candidate,plan_sha,runner=runner,root=root,releases=releases)
    return c,runner,old


def test_stage_is_readonly_and_plan_consumed_exactly_once(rig):
    c,r,old=rig; staged=c.stage()
    assert staged['productionWrites'] is False
    assert all(not any(x in argv for x in ('run','up','stop','tag','exec')) for argv,_ in r.calls)
    result=c.activate()
    assert result['completed'] and result['schema']==[73,9]
    assert r.data==['backup','migrate','check']
    assert r.started==['app','app','decoder','sync','media','web']
    assert r.timer and c.lifecycle.phase=='live'
    assert (c.release/'source-before/app.py').read_bytes()==b'old application\n'
    assert (c.release/'expo-before/old.js').read_bytes()==b'old export\n'
    assert (c.root/'app.py').read_bytes()==b'new application\n'
    assert not (c.root/'static/experience/old.js').exists()
    assert 'SYNTHETIC_ENV' not in json.dumps(result)
    before=len(r.calls)
    with pytest.raises(ReleaseError,match='plan_consumed'):c.activate()
    assert len(r.calls)==before


@pytest.mark.parametrize('fault',['backup','migrate','check','logical-drift','health'])
def test_failed_phase_retains_backup_source_and_never_restores_or_restarts_parent(rig,fault):
    c,r,old=rig; c.stage(); r.fault=fault
    with pytest.raises(ReleaseError):c.activate()
    failure=json.loads((c.candidate/'failure.json').read_bytes())
    assert not failure['completed'] and failure['automaticRestore'] is False and not r.timer
    assert not any(v['State']['Running'] for v in r.values.values())
    assert (c.release/'source-before/RELEASE-MANIFEST.json').exists()
    assert not any('rm' in argv or 'kill' in argv for argv,_ in r.calls)
    assert 'verify-rollback' not in r.data
    if fault in ('backup','migrate'):assert not r.started
    if fault=='logical-drift':assert 'decoder' not in r.started


def test_partial_media_start_failure_records_candidates_then_stops_decoder_after_media(rig):
    c,r,_=rig;c.stage();r.fail_up='media'
    with pytest.raises(ReleaseError):c.activate()
    assert not any(v['State']['Running'] for v in r.values.values())
    assert json.loads((c.candidate/'failure.json').read_bytes())['candidateStop']['complete']


@pytest.mark.parametrize('fault',['environment','source','operator','image','stage'])
def test_drift_refuses_activation_before_mutation(rig,fault):
    c,r,_=rig;c.stage();prior=len(r.calls)
    if fault=='environment':(c.root/'.env').write_bytes(b'changed')
    elif fault=='source':(c.source/'app.py').write_bytes(b'changed')
    elif fault=='operator':(c.candidate/'operator'/prepare.OPERATORS[0]).write_bytes(b'changed')
    elif fault=='image':r.app_config={'Env':['changed']}
    else:(c.candidate/'stage.json').write_bytes(b'{}')
    with pytest.raises((ReleaseError,KeyError)):c.activate()
    assert not (c.candidate/'activation-started.json').exists()
    assert not any(any(v in argv for v in ('run','stop','tag','up','exec')) for argv,_ in r.calls[prior:])


def test_rollback_verification_requires_stopped_group_and_manual_original_source_restore(rig):
    c,r,old=rig;c.stage();r.fault='check'
    with pytest.raises(ReleaseError):c.activate()
    r.fault=None
    with pytest.raises(ReleaseError):c.verify_rollback(c.release)
    # Simulate the separate operator's source restoration, never done by controller.
    for p in list((c.root/'static/experience').iterdir()):p.unlink()
    for name in [*old['files'],'RELEASE-MANIFEST.json']:
        write(c.root/name,(c.release/'source-before'/name).read_bytes())
    result=c.verify_rollback(c.release)
    assert result['verified'] and r.data[-1]=='verify-rollback'
    assert not any(v['State']['Running'] for v in r.values.values()) and not r.timer
    receipt=json.loads((c.release/'rollback-verified.json').read_bytes())
    assert receipt['servicesStarted'] is False


@pytest.fixture
def resource(tmp_path):
    root=tmp_path/'profile';root.mkdir()
    modules={'app.py':'a'*64,'requirements.txt':'b'*64};decoder={'media_video_service.py':'c'*64}
    package_value={'metadata':{'contexts':{'app':modules,'decoder':decoder}}}
    proofs={}
    for role,limit in [('application',384),('decoder',768)]:
        proofs[role]={'role':role,'profile':'worker100','exitCode':0,'loadedSourceVerified':True,'sourceHead':'e'*40,
                      'cgroup':{'memory.max':str(limit*1024**2),'memory.peak':'10000','memory.swap.max':'0',
                                'pids.max':'128','memory.events':'max 0\noom 0\noom_kill 0\n'}}
    budget={'preflightMiB':1280,'preflightSamples':3,'preflightIntervalSeconds':1,'abortBelowMiB':256,
            'sampleIntervalSeconds':.25,'maxSampleLagSeconds':1}
    memory={'failure':None,'policy':budget,'threadStarted':True,'threadStopped':True,'sampleCount':10,
            'minimumAvailableKiB':1000000}
    result={'passed':True,'status':'passed','profile':'worker100','failure':None,'workerAttachExitCode':0,
            'cleanupErrors':[],'unconfirmedCreate':None,'hostMemory':memory,'proofs':proofs,'containers':{},
            'contract':{'sourceHead':'e'*40,'images':{'application':prepare.IMAGES['app'],'decoder':prepare.IMAGES['decoder']},
                        'limitsMiB':{'application':384,'decoder':768},'app':modules,'decoder':decoder},
            'artifacts':{'proof.txt':write(root/'proof.txt',b'explicit synthetic test proof')}}
    originals={'preflight.json':{'status':'ready','failure':None,'policy':budget,'samples':[{'availableKiB':1500000}]*3},
               'host-memory.json':memory,'application/application.json':{'profile':'worker100','responseClosed':True,
                  'busyWhileOpen':True,'permitReleasedAfterClose':True,'otherMemberDenied':True,'idRevisionPreserved':True,
                  'confirmationReplayed':True,'counts':{'media_items':1,'media_video_cache':1},'reservedBytes':0,
                  'downloadBytes':100*1024**2,'socketCalls':[{}]}}
    for role,limit in [('application',384),('decoder',768)]:
        uid=('1' if role=='application' else '2')*64;result['containers'][role]=uid
        originals[role+'/finished.json']=proofs[role]
        originals[role+'-container.json']={'Id':uid,'Image':result['contract']['images'][role],
                'State':{'ExitCode':0,'Running':False,'OOMKilled':False},'Config':{'User':'10001:10001'},
                'HostConfig':{'Memory':limit*1024**2,'MemorySwap':limit*1024**2,'NetworkMode':'none','ReadonlyRootfs':True}}
    result['artifacts'].update({n:write(root/n,b) for n,b in originals.items()})
    return root,result,package_value


@pytest.mark.parametrize('fault',['missing-role','aborted','oom','limit','image','runtime','partial','tampered','missing-original','container-oom'])
def test_resource_partial_failed_wrong_runtime_or_tampered_receipts_never_enable_plan(resource,fault):
    root,result,value=resource
    if fault=='missing-role':result['proofs'].pop('decoder')
    elif fault=='aborted':result['hostMemory']['failure']='low_memory'
    elif fault=='oom':result['proofs']['application']['cgroup']['memory.events']='max 1\noom 1\noom_kill 1\n'
    elif fault=='limit':result['contract']['limitsMiB']['application']=768
    elif fault=='image':result['contract']['images']['decoder']='sha256:'+'0'*64
    elif fault=='runtime':result['contract']['app']={'app.py':'f'*64}
    elif fault=='partial':result['passed']=False
    elif fault=='tampered':(root/'proof.txt').write_bytes(b'changed')
    elif fault=='missing-original':result['artifacts'].pop('application/application.json')
    else:
        name='application-container.json';state=json.loads((root/name).read_bytes());state['State']['OOMKilled']=True
        result['artifacts'][name]=write(root/name,state)
    digest=write(root/'result.json',result)
    with pytest.raises(ReleaseError):prepare.verify_resources({'root':str(root),'result':'result.json','sha256':digest},'worker100',value)


def test_resource_contract_accepts_separate_tool_head_only_with_exact_runtime(resource):
    root,result,value=resource
    digest=write(root/'result.json',result)
    observed=prepare.verify_resources({'root':str(root),'result':'result.json','sha256':digest},'worker100',value)
    assert observed['result.json']==digest and result['contract']['sourceHead']!=prepare.APP_SOURCE


@pytest.mark.parametrize('record', [
    {'verdict': 'PASS', 'findings': []},
    {'conclusion': 'PASS_FOR_COMPONENT', 'findings': []},
    {'status': 'PASS_REAL_PACKAGE_AND_B2_EVIDENCE_ONLY', 'findings': []},
    {'decision': 'PASS_ACTUAL_ISOLATED_LINUX_MIGRATION_AND_RESTORE', 'blockingFindings': []},
    {'decision': 'PASS_FOR_RECORDED_LOCAL_BROWSER_SCOPE', 'blockingFindings': []},
])
def test_independent_review_accepts_existing_report_formats(record):
    prepare.verify_review(record)


@pytest.mark.parametrize('record', [
    {'verdict': 'PASS', 'decision': 'BLOCKED', 'findings': []},
    {'decision': 'PASS', 'findings': [], 'blockingFindings': ['unresolved migration']},
    {'decision': 'PASS', 'findings': ['unresolved identity'], 'blockingFindings': []},
    {'decision': 'PASS', 'blockingFindings': None},
    {'decision': 'PASS', 'blockingFindings': {}},
    {'decision': 'PASS'},
    {'verdict': None, 'decision': 'PASS', 'blockingFindings': []},
    {'decision': 'PASSIVE', 'blockingFindings': []},
    {'decision': 'BLOCKED', 'blockingFindings': []},
    {'findings': []},
    [],
])
def test_independent_review_rejects_conflicts_unresolved_or_malformed_reports(record):
    with pytest.raises(ReleaseError, match='review_not_passed'):
        prepare.verify_review(record)


def test_missing_resource_inputs_and_absent_reviews_are_rejected_without_output(tmp_path):
    with pytest.raises(ReleaseError,match='release_inputs_incomplete'):prepare.verify_evidence({})
    with pytest.raises(ReleaseError):prepare.checked_record({'root':str(tmp_path),'result':'../outside','sha256':'1'*64})


def test_consumed_stage_is_not_reusable(rig):
    c,r,_=rig;put(c.candidate/'activation-started.json',{'planSha256':c.plan_sha})
    with pytest.raises(ReleaseError,match='plan_consumed'):c.stage()
    assert not r.calls


def operator_repo(tmp_path, monkeypatch):
    repo=tmp_path/'operator-repo';repo.mkdir()
    def git(*args):return subprocess.check_output(['git',*args],cwd=repo,stderr=subprocess.PIPE).decode().strip()
    git('init','-q');git('config','user.email','fixture@example.invalid');git('config','user.name','Synthetic Operator')
    for name in set(prepare.OPERATORS)-prepare.ADDITIONS:write(repo/name,(ROOT/name).read_bytes())
    git('add','deploy');git('commit','-qm','synthetic fixed dependency baseline');base=git('rev-parse','HEAD')
    monkeypatch.setattr(prepare,'BASE',base)
    for name in prepare.ADDITIONS:write(repo/name,(ROOT/name).read_bytes())
    git('add','deploy','tests','docs');git('commit','-qm','synthetic operator candidate')
    return repo,git('rev-parse','HEAD'),git


def test_prepare_exclusive_real_git_closure_and_portable_source_bytes(rig,tmp_path,monkeypatch):
    c,r,_=rig
    repo,head,git=operator_repo(tmp_path,monkeypatch)
    inputs=tmp_path/'inputs.json';write(inputs,c.plan['inputs'])
    target=tmp_path/'prepared'
    result=prepare.prepare(repo,head,inputs,c.plan['envSha256'],target)
    assert result['prepared'] and not r.calls
    plan=json.loads((target/'plan.json').read_bytes())
    assert sha((target/'plan.json').read_bytes())==result['planSha256']
    assert set(json.loads((target/'operator.json').read_bytes())['files'])==set(prepare.OPERATORS)
    assert (target/'source/app.py').read_bytes()==(c.source/'app.py').read_bytes()
    assert not any(p.name=='.env' for p in target.rglob('*'))
    with pytest.raises(ReleaseError,match='exclusive_candidate_required'):
        prepare.prepare(repo,head,inputs,c.plan['envSha256'],target)


def test_operator_extra_committed_path_and_working_change_are_rejected(tmp_path,monkeypatch):
    repo,head,git=operator_repo(tmp_path,monkeypatch)
    assert len(prepare.operator_blobs(repo,head))==9
    (repo/'deploy/media_video_release_controller.py').write_bytes(b'changed')
    with pytest.raises(ValueError):prepare.operator_blobs(repo,head)
    git('add','deploy');git('commit','-qm','record change')
    write(repo/'outside.txt',b'unreviewed');git('add','outside.txt');git('commit','-qm','outside scope')
    with pytest.raises(ReleaseError,match='operator_changes_outside_review_scope'):
        prepare.operator_blobs(repo,git('rev-parse','HEAD'))


def test_prepare_refuses_overlap_before_creating_candidate(rig,tmp_path,monkeypatch):
    c,_,_=rig;repo,head,_=operator_repo(tmp_path,monkeypatch)
    inputs=tmp_path/'inputs.json';write(inputs,c.plan['inputs'])
    target=repo/'nested-candidate'
    with pytest.raises(ReleaseError,match='output_overlaps_input'):
        prepare.prepare(repo,head,inputs,c.plan['envSha256'],target)
    assert not target.exists()


def test_failure_with_media_still_running_never_claims_decoder_drained(rig):
    c,r,_=rig;c.stage();r.fault='health';r.fail_stop='media'
    with pytest.raises(ReleaseError):c.activate()
    failure=json.loads((c.candidate/'failure.json').read_bytes())
    assert not failure['candidateStop']['complete']
    assert 'decoder:media_stop_unverified' in failure['candidateStop']['failed']
    assert r.values['decoder']['State']['Running'] and r.values['media']['State']['Running']
    assert not r.timer


def test_existing_socket_volume_with_stale_entry_is_preserved_and_rejected(rig,tmp_path,monkeypatch):
    c,r,_=rig
    directory=tmp_path/'socket-volume';directory.mkdir();write(directory/'video.sock',b'stale fixture')
    original=c.docker
    def docker(*args,**kwargs):
        if args[:2]==('volume','ls'):return (lifecycle.SOCKET_VOLUME+'\n').encode()
        if args[:2]==('volume','inspect'):
            return json.dumps([{'Name':lifecycle.SOCKET_VOLUME,'Driver':'local','Options':None,'Mountpoint':str(directory)}]).encode()
        return original(*args,**kwargs)
    monkeypatch.setattr(c,'docker',docker)
    with pytest.raises(ReleaseError,match='socket_volume_not_empty_private'):c.socket_ready()
    assert (directory/'video.sock').read_bytes()==b'stale fixture'


@pytest.mark.parametrize('fault',['timeout','interrupt'])
def test_helper_timeout_or_signal_stops_recorded_cid_before_failed_handoff(rig,fault):
    c,r,_=rig;c.stage();r.helper_fault=fault
    with pytest.raises((ReleaseError,KeyboardInterrupt)):c.activate()
    failure=json.loads((c.candidate/'failure.json').read_bytes())
    receipt=failure['dataHelperStop'];cid=receipt['helper']['id']
    assert receipt['complete'] and receipt['terminal']['Pid']==0 and receipt['terminal']['Status']=='exited'
    assert failure['candidateStop']['complete'] and not failure['automaticRestore'] and not r.timer
    assert r.data==['backup','migrate'] and not r.started
    assert not any(v['State']['Running'] for v in r.helpers.values())
    receipts=[json.loads(p.read_bytes()) for p in sorted(c.release.glob('phase-*.json'))]
    created=next(x for x in receipts if x['event']=='data_helper_created' and x['helper']['id']==cid)
    assert created['helper']['action']=='migrate'
    commands=[a[3:] for a,_ in r.calls if a[:3]==list(lifecycle.DOCKER)]
    start=commands.index(['start','--attach',cid]); stop=commands.index(['stop','--signal','SIGTERM','--timeout','30',cid])
    assert start<stop and ['inspect',cid] in commands[stop+1:]
    assert not any(a[0] in ('run','rm','kill') for a in commands)
    assert len([a for a in commands if a==['start','--attach',cid]])==1
    assert len([a for a in commands if a[0]=='stop'])==1  # Only the exact helper, no broad selector.


@pytest.mark.parametrize('fault',['unknown-create','stop-failed','identity-changed'])
def test_unconfirmed_helper_is_retained_without_false_stopped_or_retry(rig,fault):
    c,r,_=rig;c.stage();r.helper_fault=fault
    with pytest.raises(ReleaseError):c.activate()
    failure=json.loads((c.candidate/'failure.json').read_bytes())
    assert not failure['dataHelperStop']['complete'] and not failure['candidateStop']['complete']
    assert 'data-helper:stop_unverified' in failure['candidateStop']['failed']
    assert not r.timer and not r.started and not failure['automaticRestore']
    assert r.data==(['backup'] if fault=='unknown-create' else ['backup','migrate'])
    helpers=[v for v in r.helpers.values() if v['action']=='migrate'];assert len(helpers)==1
    cid=helpers[0]['Id']
    stops=[a for a,_ in r.calls if a[:4]==[*lifecycle.DOCKER,'stop']]
    if fault in ('unknown-create','identity-changed'):assert not stops
    else:assert len(stops)==1 and stops[0][-1]==cid and helpers[0]['State']['Running']
    with pytest.raises(ReleaseError,match='plan_consumed'):c.activate()


@pytest.fixture
def native_lock_backend(tmp_path,monkeypatch):
    """Real OS locks. Windows adapter tests fd lifetime, not Linux flock semantics."""
    import sys
    if os.name=='nt':
        import msvcrt
        from types import SimpleNamespace
        def flock(fd,operation):
            os.lseek(fd,0,os.SEEK_SET)
            msvcrt.locking(fd,msvcrt.LK_NBLCK,1)
        backend=SimpleNamespace(LOCK_EX=1,LOCK_NB=2,flock=flock)
        monkeypatch.setitem(sys.modules,'fcntl',backend)
        monkeypatch.setattr(control.os,'O_NOFOLLOW',0,raising=False)
    else:
        import fcntl as backend
    monkeypatch.setattr(control,'RELEASES',tmp_path)
    for name in ('.membership-release.lock','.static-release.lock'):(tmp_path/name).write_bytes(b'0')
    return backend,tmp_path


@pytest.mark.parametrize('held',['.membership-release.lock','.static-release.lock'])
def test_both_historical_lock_contention_releases_partial_acquisition(native_lock_backend,held):
    backend,path=native_lock_backend
    occupied=os.open(path/held,os.O_RDWR)
    try:
        backend.flock(occupied,backend.LOCK_EX|backend.LOCK_NB)
        with pytest.raises(OSError):
            with control.release_lock():pytest.fail('must not enter while a historical lock is held')
    finally:os.close(occupied)
    with control.release_lock():pass  # Includes the first fd after second-lock contention.


def test_dual_lock_order_and_body_exception_close_every_fd(native_lock_backend,monkeypatch):
    _,_=native_lock_backend;opened=[];original=os.open
    def tracked(path,*args,**kwargs):
        fd=original(path,*args,**kwargs);opened.append((Path(path).name,fd));return fd
    monkeypatch.setattr(control.os,'open',tracked)
    with pytest.raises(RuntimeError,match='inside action'):
        with control.release_lock():raise RuntimeError('inside action')
    assert [n for n,_ in opened]==['.membership-release.lock','.static-release.lock']
    for _,fd in opened:
        with pytest.raises(OSError):os.fstat(fd)
    with control.release_lock():pass


def test_second_lock_open_error_closes_first_fd(native_lock_backend,monkeypatch):
    _,_=native_lock_backend;opened=[];original=os.open
    def tracked(path,*args,**kwargs):
        if Path(path).name=='.static-release.lock':raise OSError('synthetic second-open error')
        fd=original(path,*args,**kwargs);opened.append(fd);return fd
    monkeypatch.setattr(control.os,'open',tracked)
    with pytest.raises(OSError,match='second-open'):
        with control.release_lock():pytest.fail('must not enter after second-open failure')
    assert len(opened)==1
    with pytest.raises(OSError):os.fstat(opened[0])
