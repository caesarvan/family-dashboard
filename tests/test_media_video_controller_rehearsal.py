"""Offline fixture/selector/handle checks. Never starts Docker or Linux services."""
import json
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


def test_admission_samples_all_three_and_never_polls_for_a_high_point():
    values=iter([1088*1024,1088*1024-1,2048*1024]);slept=[]
    result=rehearsal.preflight(reader=lambda:next(values),sleeper=slept.append)
    assert not result['passed'] and len(result['samples'])==3 and slept==[1,1]
    with pytest.raises(StopIteration):next(values)
    assert rehearsal.preflight(reader=lambda:1088*1024,sleeper=lambda _:None)['passed']


class Healthy:
    def check(self): pass


@pytest.fixture
def transport(tmp_path):
    return rehearsal.Transport(tmp_path,tmp_path/'bundle',PROJECT,'http://127.0.0.1:38127',Healthy(),'success')


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
    transport.unknown={'name':'fixture-create-result-unavailable'}
    monkeypatch.setattr(transport,'discover',lambda:None)
    calls=[]
    monkeypatch.setattr(transport,'raw',lambda *args,**kw:calls.append(args) or b'')
    result=transport.stop_owned()
    assert not result['complete'] and 'unknown_create' in result['failures']
    assert all(args[0]=='ps' for args in calls)


def test_changed_container_identity_is_not_treated_as_removed(transport,monkeypatch):
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
